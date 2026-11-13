# Fixed-cap ShieldSystem contract from PR8 F04 section 7.
from __future__ import annotations

import math
import unittest
from dataclasses import replace

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.ir import ActionDefinitionIR, IRSource
from hsr.simulator_v8_clean_core.systems.damage import DamagePacket, DamageSystem
from hsr.simulator_v8_clean_core.systems.shield import ShieldSystem


class CappedShieldTest(unittest.TestCase):
    def setUp(self) -> None:
        self.shields = ShieldSystem()

    @staticmethod
    def _state(shield_instances=()) -> BattleState:
        return BattleState(
            units={
                "target": UnitState(
                    "target",
                    "ally",
                    "synthetic:target",
                    shield_instances=shield_instances,
                )
            }
        )

    def _apply(self, state: BattleState, amount: float, *, max_capacity=None, falling_cap_policy="reject"):
        return self.shields.apply_effect(
            state,
            target_id="target",
            shield_id="synthetic:stackable",
            source_id="synthetic:source",
            source_kind="synthetic",
            opcode="StackShield",
            amount=amount,
            source_trace={"kind": "synthetic"},
            actor_id="caster",
            event_source_id="synthetic:event",
            owner_modifier_name="synthetic:modifier",
            status_instance_id="synthetic:instance",
            max_capacity=max_capacity,
            falling_cap_policy=falling_cap_policy,
        )

    @staticmethod
    def _commit(state: BattleState, result) -> BattleState:
        assert result.mutation is not None
        target = replace(
            state.units["target"],
            shield_instances=tuple(result.mutation.after),
        )
        return replace(state, units={"target": target})

    def _stacked_state(self, amount: float) -> BattleState:
        state = self._state()
        return self._commit(state, self._apply(state, amount))

    def test_stack_uses_supplied_cap_and_preserves_instance_identity(self) -> None:
        result = self._apply(self._stacked_state(500), 1000, max_capacity=2000)

        self.assertTrue(result.ok)
        instance = result.mutation.after[0]
        self.assertEqual((instance["remaining"], instance["capacity"]), (1500, 2000))
        self.assertEqual(instance["source_actor_id"], "caster")
        self.assertEqual(instance["status_instance_id"], "synthetic:instance")
        self.assertEqual(result.mutation.metadata["max_capacity"], 2000)
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0]["payload"]["max_capacity"], 2000)

    def test_stack_clamps_at_supplied_cap(self) -> None:
        result = self._apply(self._stacked_state(1700), 1000, max_capacity=2000)

        self.assertTrue(result.ok)
        self.assertEqual(result.mutation.after[0]["remaining"], 2000)

    def test_saturated_cap_is_successful_process_only_noop(self) -> None:
        state = self._stacked_state(2000)
        result = self._apply(state, 1000, max_capacity=2000)

        self.assertTrue(result.ok)
        self.assertIsNone(result.mutation)
        self.assertEqual(result.events, ())
        self.assertTrue(result.records[0]["process_only"])
        self.assertIsNone(result.records[0]["mutation_id"])

    def test_explicit_falling_cap_policy_preserves_existing_and_reports_assumption(self):
        state = self._stacked_state(2500)
        result = self._apply(state, 1000, max_capacity=2000, falling_cap_policy="retain_existing")
        self.assertTrue(result.ok)
        self.assertIsNone(result.mutation)
        notice = next(r['payload'] for r in result.records if r['record_type'] == 'rule_assumption')
        self.assertEqual(notice['status'], '未实证')
        self.assertEqual((notice['remaining'], notice['current_cap']), (2500, 2000))
        increased = self._apply(state, 1000, max_capacity=3000, falling_cap_policy="retain_existing")
        self.assertEqual(increased.mutation.after[0]['remaining'], 3000)

    def test_zero_cap_is_successful_noop_without_zero_shield_instance(self) -> None:
        result = self._apply(self._state(), 1000, max_capacity=0)

        self.assertTrue(result.ok)
        self.assertIsNone(result.mutation)
        self.assertEqual(result.events, ())
        self.assertTrue(result.records[0]["process_only"])
        self.assertIsNone(result.records[0]["mutation_id"])

    def test_reapplying_an_undamaged_shield_is_successful_without_fake_mutation(self) -> None:
        kwargs = dict(target_id="target", shield_id="shield", source_id="caster", source_kind="status",
            opcode="Shield", amount=1000, source_trace={"fixture": "refresh"}, actor_id="caster",
            event_source_id="shield", status_instance_id="same-instance")
        first = self.shields.apply_effect(self._state(), **kwargs)
        state = self._commit(self._state(), first)
        repeated = self.shields.apply_effect(state, **kwargs)
        self.assertTrue(repeated.ok)
        self.assertIsNone(repeated.mutation)
        self.assertFalse(repeated.events)
        self.assertTrue(repeated.records[0]["process_only"])

    def test_missing_cap_preserves_existing_stack_behavior(self) -> None:
        result = self._apply(self._stacked_state(500), 1000)

        self.assertTrue(result.ok)
        self.assertEqual(
            (result.mutation.after[0]["remaining"], result.mutation.after[0]["capacity"]),
            (1500, 1500),
        )

    def test_invalid_cap_and_preexisting_excess_are_non_mutating(self) -> None:
        for cap in (True, -1.0, math.nan, math.inf, "2000"):
            with self.subTest(cap=cap):
                result = self._apply(self._state(), 1000, max_capacity=cap)
                self.assertFalse(result.ok)
                self.assertIsNone(result.mutation)
                self.assertEqual(result.events, ())
                self.assertEqual(result.records, ())

        result = self._apply(self._stacked_state(2100), 1000, max_capacity=2000)
        self.assertFalse(result.ok)
        self.assertEqual(
            result.blocked_reason,
            "shield_existing_remaining_exceeds_max_capacity",
        )
        self.assertIsNone(result.mutation)
        self.assertEqual(result.events, ())
        self.assertEqual(result.records, ())

    def test_nonfinite_or_boolean_amount_is_non_mutating(self) -> None:
        for amount in (math.nan, math.inf, True):
            with self.subTest(amount=amount):
                result = self._apply(self._state(), amount, max_capacity=2000)
                self.assertFalse(result.ok)
                self.assertEqual(result.blocked_reason, "shield_amount_invalid")
                self.assertIsNone(result.mutation)
                self.assertEqual(result.events, ())
                self.assertEqual(result.records, ())


class ShieldAbsorptionBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.state = BattleState(units={
            "caster": UnitState("caster", "enemy", "synthetic:caster", attack=900.0),
            "target": UnitState("target", "ally", "synthetic:target", max_hp=2000.0, hp=2000.0),
        })
        self.shields = ShieldSystem()
        self.damage = DamageSystem()
        self.reducer = MutationReducer()

    def _grant(self, state, source, *, amount=600.0, opcode="InitShield", families=None):
        result = self.shields.apply_effect(
            state, target_id="target", shield_id=f"shield:{source}", source_id=source,
            source_kind="synthetic", opcode=opcode, amount=amount,
            source_trace={"kind": "synthetic"}, actor_id="caster", event_source_id=source,
            absorb_families=families or ("direct", "additional", "dot", "break", "super_break", "true_damage"),
            max_capacity=1200.0 if opcode == "StackShield" else None,
        )
        self.assertTrue(result.ok, result.blocked_reason)
        return self.reducer.apply_all(state, (result.mutation,))

    @staticmethod
    def _packet(family, amount=900.0):
        packet = DamagePacket(
            "caster", "target", "Normal", family, amount,
            "fixed_final" if family in {"true_damage", "hp_loss"} else "family_base",
            status_damage_emission_id="synthetic:status" if family in {"additional", "dot"} else "",
            break_damage_emission_id="synthetic:break" if family == "break" else "",
            break_template_id="synthetic:break-template" if family == "break" else "",
            super_break_emission_id="synthetic:super-break" if family == "super_break" else "",
            source_trace={"kind": "synthetic"},
        )
        if family == "direct":
            definition = ActionDefinitionIR(
                "synthetic:action", "synthetic:action", 1, "Normal", "SingleAttack", "single",
                0, 0, 0, 0, (), (), (), None, IRSource("synthetic", "action", "test"),
            )
            packet = replace(
                packet, action_definition=definition, scaling_ratio=1.0,
                scaling_basis={"kind": "fixed", "value": amount},
                metadata={"crit_mode": "noncrit"},
            )
        return packet

    def test_all_absorbing_damage_consumers_use_parallel_shields(self):
        state = self._grant(self._grant(self.state, "first"), "second")
        for family in ("direct", "additional", "dot", "break", "super_break", "true_damage"):
            with self.subTest(family=family):
                result = self.damage.apply_packet(state, self._packet(family))
                self.assertTrue(result.ok, result.errors)
                route = next(record["payload"] for record in result.records
                             if record["record_type"] == "shield_absorption")
                damage = route["incoming_damage"]
                self.assertEqual(route["absorption_mode"], "parallel_ordinary")
                self.assertEqual(route["pool_loss_total"], 2 * min(damage, 600.0))
                self.assertEqual(route["absorbed_damage"], min(damage, 600.0))
                after = self.reducer.apply_all(state, result.mutations)
                self.assertEqual(after.units["target"].hp, 2000.0 - max(0.0, damage - 600.0))
                self.assertEqual(len(after.units["target"].shield_instances), 0 if damage >= 600.0 else 2)
                self.assertTrue(self.reducer.replay_snapshot(state, result.mutations, after.snapshot().to_json()).ok)

    def test_single_shield_and_same_source_stack_still_absorb_then_overflow(self):
        single = self._grant(self.state, "only")
        stacked = self._grant(self._grant(self.state, "only", amount=300.0, opcode="StackShield"),
                              "only", amount=300.0, opcode="StackShield")
        for state in (single, stacked):
            self.assertEqual(len(state.units["target"].shield_instances), 1)
            result = self.damage.apply_packet(state, self._packet("dot"))
            self.assertTrue(result.ok, result.errors)
            self.assertEqual(sum(event.event_type == "shield.change" for event in result.events), 1)
            self.assertEqual(sum(event.event_type == "shield.exhausted" for event in result.events), 1)
            self.assertEqual(sum(event.event_type == "hp.change" for event in result.events), 1)
            after = self.reducer.apply_all(state, result.mutations)
            self.assertEqual(after.units["target"].hp, 1700.0)
            self.assertEqual(after.units["target"].shield_instances, ())
            self.assertTrue(self.reducer.replay_snapshot(state, result.mutations, after.snapshot().to_json()).ok)

    def test_ineligible_other_shield_does_not_block_single_eligible_pool(self):
        state = self._grant(self._grant(self.state, "dot-only", families=("dot",)),
                            "direct-only", families=("direct",))
        result = self.damage.apply_packet(state, self._packet("dot"))
        self.assertTrue(result.ok, result.errors)
        after = self.reducer.apply_all(state, result.mutations)
        self.assertEqual(after.units["target"].hp, 1700.0)
        self.assertEqual(len(after.units["target"].shield_instances), 1)
        self.assertEqual(after.units["target"].shield_instances[0]["source_id"], "direct-only")
        self.assertEqual(after.units["target"].shield_instances[0]["remaining"], 600.0)

    def test_hp_loss_bypasses_coexisting_shields_and_zero_damage_does_not_drain(self):
        state = self._grant(self._grant(self.state, "first"), "second")
        bypassed = self.damage.apply_packet(state, self._packet("hp_loss"))
        self.assertTrue(bypassed.ok, bypassed.errors)
        after = self.reducer.apply_all(state, bypassed.mutations)
        self.assertEqual(after.units["target"].hp, 1100.0)
        self.assertEqual(after.units["target"].shield_instances, state.units["target"].shield_instances)
        zero = self.damage.apply_packet(state, self._packet("dot", 0.0))
        self.assertTrue(zero.ok, zero.errors)
        self.assertEqual(self.reducer.apply_all(state, zero.mutations), state)


if __name__ == "__main__":
    unittest.main()
