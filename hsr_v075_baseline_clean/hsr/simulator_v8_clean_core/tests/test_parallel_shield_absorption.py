from __future__ import annotations

import unittest
from dataclasses import replace

from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.ir import (
    CanonicalIR, EffectIR, IRSource, StatusCallbackIR, StatusCallbackTaskIR,
)
from hsr.simulator_v8_clean_core.rules.engine_rule_registry import build_engine_rule_registry
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.damage import DamageSystem
from hsr.simulator_v8_clean_core.systems.effect import EffectRegistry
from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
from hsr.simulator_v8_clean_core.systems.shield import ShieldSystem
from hsr.simulator_v8_clean_core.systems.status import StatusInstance, StatusSystem
from hsr.simulator_v8_clean_core.systems.unit_stats import effective_unit_stat
from hsr.simulator_v8_clean_core.tools.validate_p7_s13_shield_hp_routing import (
    _apply_shield,
    _damage_packet,
    _state,
)


class ParallelShieldAbsorptionTest(unittest.TestCase):
    def test_exhausted_shield_removes_only_its_status_and_effect(self) -> None:
        source = IRSource("fixture:shield", "RemoveShield", "fixture:remove")
        effect = EffectIR(
            "effect:remove", "RemoveShield",
            {"standard": {
                "target_alias": "ModifierOwnerEntity",
                "target_expression_id": "target:owner",
                "target_expression_coverage_status": "executable",
                "removal_identity": "current_status_instance",
            }},
            source, "executable", source_mode="mainline",
        )
        callback = StatusCallbackIR(
            "callback:small", "Small", "OnDestroy", ("task:remove",), source,
            (0, 0), coverage_status="executable", admission_status="executable",
            source_mode="mainline_global_modifier",
        )
        task = StatusCallbackTaskIR(
            "task:remove", callback.callback_id, "Small", "OnDestroy", 0,
            "root", "root", "RemoveShield", source, effect_id=effect.effect_id,
            coverage_status="executable",
        )
        engine_rules = build_engine_rule_registry()
        rules = RuleBook(CanonicalIR(
            "fixture:shield", effects=(effect,), status_callbacks=(callback,),
            status_callback_tasks=(task,),
            damage_route_rules=engine_rules.damage_route_rules,
            shield_priority_rules=engine_rules.shield_priority_rules,
        ))
        state = _state()
        target = state.units["enemy:target"]
        small = StatusInstance(
            "status:small", "modifier:Small", "Small", target.unit_id,
            "source:small", "ally:actor", source_trace={"kind": "fixture"},
            modifiers=({"bucket": "aggro", "key": "aggro_added_ratio", "value": 0.5},),
            trigger_ids_by_event={"OnDestroy": (callback.callback_id,)},
        ).to_json()
        large = StatusInstance(
            "status:large", "modifier:Large", "Large", target.unit_id,
            "source:large", "ally:actor", source_trace={"kind": "fixture"},
        ).to_json()
        state = replace(state, units={
            **state.units,
            target.unit_id: replace(
                target, hp=2000.0, max_hp=2000.0,
                statuses=("modifier:Small", "modifier:Large"),
                resources={"base_aggro": 100.0},
                flags={"status_details": [small, large]},
            ),
        })
        for name, amount, modifier, instance_id in (
            ("small", 1000.0, "Small", "status:small"),
            ("large", 1500.0, "Large", "status:large"),
        ):
            grant = ShieldSystem().apply_effect(
                state, target_id=target.unit_id, shield_id=f"shield:{name}",
                source_id=name, source_kind="fixture", opcode="InitShield",
                amount=amount, source_trace={"kind": "fixture"},
                actor_id="ally:actor", event_source_id="ally:actor",
                owner_modifier_name=modifier, status_instance_id=instance_id,
            )
            self.assertTrue(grant.ok, grant.blocked_reason)
            state = MutationReducer().apply_all(state, (grant.mutation,))
        self.assertEqual(effective_unit_stat(state.units[target.unit_id], "base_aggro").value, 150.0)

        before_hit = state
        hit = DamageSystem(rules).apply_packet(state, _damage_packet(1200.0))
        self.assertTrue(hit.ok, hit.errors)
        state = MutationReducer().apply_all(state, hit.mutations)
        action_mutations = list(hit.mutations)
        dispatcher = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules)))
        exhausted = next(event for event in hit.events if event.event_type == "shield.exhausted")
        untyped = dispatcher.dispatch_event(state, event=replace(exhausted, shield_exhaustion_fact=None))
        self.assertEqual(untyped.errors, ("shield_exhaustion_typed_fact_missing_or_mismatch",))
        self.assertEqual(untyped.mutations, ())
        self.assertEqual(untyped.after_state.snapshot(), state.snapshot())
        records = []
        for event in hit.events:
            dispatched = dispatcher.dispatch_event(state, event=event)
            self.assertFalse(dispatched.errors, dispatched.errors)
            state = dispatched.after_state
            action_mutations.extend(dispatched.mutations)
            records.extend(dispatched.records)
        remaining = state.units[target.unit_id]
        self.assertEqual(remaining.hp, 2000.0)
        self.assertEqual([(shield["owner_modifier_name"], shield["remaining"]) for shield in remaining.shield_instances], [("Large", 300.0)])
        self.assertEqual([detail["instance_id"] for detail in remaining.flags["status_details"]], ["status:large"])
        self.assertEqual(effective_unit_stat(remaining, "base_aggro").value, 100.0)
        self.assertTrue(any(record["record_type"] == "shield_remove" and record["process_only"] for record in records))
        self.assertTrue(MutationReducer().replay_snapshot(
            before_hit, action_mutations, state.snapshot().to_json(),
        ).ok)

    def test_each_pool_loses_full_hit_but_hp_overflows_once(self) -> None:
        state = _state()
        target = state.units["enemy:target"]
        state = replace(state, units={**state.units, target.unit_id: replace(target, hp=2000.0, max_hp=2000.0)})
        state, _ = _apply_shield(state, "small", 1000.0)
        state, _ = _apply_shield(state, "large", 1500.0)

        first = DamageSystem().apply_packet(state, _damage_packet(1200.0))
        self.assertTrue(first.ok, first.errors)
        committed = MutationReducer().apply_all_result(state, first.mutations)
        self.assertTrue(committed.ok)
        after = committed.after_state.units[target.unit_id]
        self.assertEqual(after.hp, 2000.0)
        self.assertEqual(
            {item["source_id"]: item["remaining"] for item in after.shield_instances},
            {"large": 300.0},
        )
        self.assertEqual(
            [event.payload["exhausted_instance_ids"] for event in first.events if event.event_type == "shield.exhausted"],
            [["validation:small:source:small:actor:ally:actor"]],
        )
        absorbed = [record["payload"]["absorbed_damage"] for record in first.records if record["record_type"] == "shield_absorption"]
        self.assertEqual(absorbed, [1200.0])

        second = DamageSystem().apply_packet(committed.after_state, _damage_packet(400.0))
        self.assertTrue(second.ok, second.errors)
        committed = MutationReducer().apply_all_result(committed.after_state, second.mutations)
        self.assertTrue(committed.ok)
        after = committed.after_state.units[target.unit_id]
        self.assertEqual((after.hp, after.shield_instances), (1900.0, ()))
        self.assertEqual(
            [event.payload["exhausted_instance_ids"] for event in second.events if event.event_type == "shield.exhausted"],
            [["validation:large:source:large:actor:ally:actor"]],
        )


if __name__ == "__main__":
    unittest.main()
