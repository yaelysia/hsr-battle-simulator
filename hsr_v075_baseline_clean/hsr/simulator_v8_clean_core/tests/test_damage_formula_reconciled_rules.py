"""Synthetic discriminators for the admitted PR8 ordinary-damage model.

Run from the repository root with PYTHONPATH=hsr_v075_baseline_clean
and python -m unittest hsr.simulator_v8_clean_core.tests.test_damage_formula_reconciled_rules.
"""
from __future__ import annotations

import unittest
from dataclasses import replace

import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState, UnitStatPool
from hsr.simulator_v8_clean_core.rules.ir import ActionDefinitionIR, IRSource
from hsr.simulator_v8_clean_core.systems.damage_formula import DamageFormulaInput, DirectDamageFormula
from hsr.simulator_v8_clean_core.systems.damage_pipeline import DamageStagePipeline
from hsr.simulator_v8_clean_core.systems.damage import DamagePacket, DamageSystem


def _modifier(instance_id, bucket, key, value):
    return {
        "instance_id": instance_id,
        "modifiers": [{"bucket": bucket, "key": key, "value": value,
                       "raw_path": f"synthetic.{instance_id}.{key}"}],
    }


class DamageFormulaReconciledRulesTest(unittest.TestCase):
    def test_additional_damage_rolls_shared_crit_without_dot_or_elation_bonus(self):
        actor = UnitState('actor', 'ally', 'synthetic:actor', level=80,
                          resources={'critical_chance': 1.0, 'critical_damage': 0.5},
                          flags={'status_details': [
                              _modifier('generic', 'damage_bonus', 'damage_added_ratio', 0.2),
                              _modifier('elation', 'damage_bonus', 'elation_damage_added_ratio', 10),
                          ]})
        target = UnitState('target', 'enemy', 'synthetic:target', hp=10000, max_hp=10000)
        state = BattleState(units={'actor': actor, 'target': target})
        packet = DamagePacket('actor', 'target', 'Pursued', 'additional', amount=100,
                              amount_stage='family_base', status_damage_emission_id='test:additional',
                              source_task_id='test:task', status_instance_id='test:instance')
        critical = DamageSystem().apply_packet(state, packet)
        self.assertTrue(critical.ok, critical.errors)
        damage = next(row['payload'] for row in critical.records if row['record_type'] == 'additional_damage')
        self.assertTrue(damage['crit_resolution']['is_crit'])
        self.assertEqual(len(critical.rng_events), 1)
        bonus = next(row for row in damage['damage_pipeline']['stages'] if row['stage'] == 'damage_bonus')
        self.assertAlmostEqual(bonus['multiplier'], 1.2)
        state = replace(state, units={**state.units, 'actor': replace(actor, resources={'critical_chance': 0.0})})
        noncritical = DamageSystem().apply_packet(state, packet)
        base = next(row['payload'] for row in noncritical.records if row['record_type'] == 'additional_damage')
        self.assertAlmostEqual(damage['final_damage'], base['final_damage'] * 1.5)
        dot = DamageSystem().apply_packet(state, replace(packet, attack_type='DOT', damage_formula_family='dot'))
        self.assertTrue(dot.ok, dot.errors)
        self.assertFalse(dot.rng_events)
        self.assertFalse(any(row.applicable for row in DamageStagePipeline().calculate(
            state, family='dot', attacker_id='actor', target_id='target', producer_base_amount=100,
            element_type=None, source_trace={},
        ).stage_buckets if row.stage == 'critical'))

    def setUp(self):
        self.actor = UnitState("actor", "ally", "synthetic:actor", level=80, attack=1000)
        self.target = UnitState("target", "enemy", "synthetic:target", defense=200)
        self.action = ActionDefinitionIR(
            definition_id="synthetic:action", action_id="synthetic:action", level=1,
            attack_type="Normal", skill_effect="SingleAttack", target_mode="Single",
            bp_need=0, bp_add=0, sp_base=0, sp_multiple_ratio=0,
            param_list=(), show_stance_list=(), show_damage_list=(),
            stance_damage_type="Fire", source=IRSource("synthetic", "validation", "action"),
        )

    def _calculate(self, *, direct_terms=()):
        state = BattleState(units={"actor": self.actor, "target": self.target})
        before = state.snapshot().to_json()
        direct = DirectDamageFormula().calculate(DamageFormulaInput(
            state=state, attacker_id="actor", target_id="target",
            action_definition=self.action, attack_type="Normal", element_type="Fire",
            scaling_ratio=1, scaling_basis={"kind": "unit_stat", "unit_ref": "attacker", "stat": "attack"},
            crit_mode="noncrit", direct_modifier_terms=direct_terms,
        ))
        pipeline = DamageStagePipeline().calculate(
            state, family="dot", attacker_id="actor", target_id="target",
            producer_base_amount=1000, element_type="Fire", source_trace={"kind": "synthetic"},
        )
        self.assertTrue(pipeline.ok)
        self.assertEqual(state.snapshot().to_json(), before)
        return direct, pipeline

    def _buckets(self, results, name):
        direct, pipeline = results
        return (
            next(bucket for bucket in direct.modifier_ledger.buckets if bucket.bucket == name),
            next(bucket for bucket in pipeline.stage_buckets if bucket.stage == name),
        )

    def test_dynamic_defense_ratio_uses_base_pool_and_preserves_flat(self):
        detail = _modifier("defense-buff", "attribute", "defense_added_ratio", 0.2)
        self.target = replace(self.target, stat_pools=(UnitStatPool("defense", 100, 0.5, 50),),
                              flags={"status_details": [detail]})
        for bucket in self._buckets(self._calculate(), "defense"):
            self.assertEqual(bucket.metadata["effective_defense"], 220)
            self.assertAlmostEqual(bucket.multiplier, 1000 / 1220)
            stat = bucket.metadata["effective_defense_stat"]
            self.assertEqual((stat["base_value"], stat["static_ratio"], stat["static_flat"]), (100, 0.5, 50))
            self.assertTrue(stat["source_terms"])

    def test_source_installed_toughness_reduction_is_counted_once_in_both_consumers(self):
        self.target = replace(self.target, toughness=30, max_toughness=30, flags={
            "toughness_reduction_mode": "status",
            "status_details": [_modifier("ordinary-toughness", "damage_reduction", "damage_reduction", 0.1)],
        })
        results = self._calculate()
        for bucket in self._buckets(results, "toughness_state"):
            self.assertEqual(bucket.multiplier, 1.0)
        for bucket in self._buckets(results, "damage_reduction"):
            self.assertAlmostEqual(bucket.multiplier, 0.9)
        # Removing the source status must not revive an implicit extra reduction.
        self.target = replace(self.target, flags={"toughness_reduction_mode": "status"})
        results = self._calculate()
        for name in ("toughness_state", "damage_reduction"):
            for bucket in self._buckets(results, name):
                self.assertEqual(bucket.multiplier, 1.0)

    def test_plain_defense_reduction_and_ignore_are_additive_and_saturate(self):
        self.actor = replace(self.actor, resources={"def_ignore": 0.1})
        for reduction, expected in ((0.4, 100), (0.95, 0)):
            self.target = replace(self.target, resources={"def_reduction": reduction})
            for bucket in self._buckets(self._calculate(), "defense"):
                self.assertAlmostEqual(bucket.metadata["effective_defense"], expected)
                self.assertAlmostEqual(bucket.multiplier, 1000 / (1000 + expected))

    def test_independent_reductions_multiply_and_keep_source_terms(self):
        detail = _modifier("reduction", "damage_reduction", "damage_reduction", 0.3)
        # The status producer has already resolved its layers to one contribution.
        detail["layer"] = 3
        self.target = replace(self.target, resources={"damage_reduction": 0.2},
                              flags={"status_details": [detail]})
        for bucket in self._buckets(self._calculate(), "damage_reduction"):
            self.assertAlmostEqual(bucket.multiplier, 0.8 * 0.7)
            self.assertEqual(bucket.metadata["aggregation"], "independent_reduction_product")
            self.assertEqual(bucket.metadata["reduction_residuals"], [0.8, 0.7])
            self.assertIn("synthetic.reduction.damage_reduction", str(bucket.to_json()))
        direct, _ = self._calculate(direct_terms=({
            "bucket": "damage_reduction", "key": "damage_reduction", "value": 0.4,
            "source_id": "hit-reduction", "raw_path": "synthetic.hit",
        },))
        self.assertAlmostEqual(direct.damage_reduction_mult, 0.8 * 0.7 * 0.6)

    def test_excess_reduction_cannot_turn_two_negative_residuals_positive(self):
        self.target = replace(self.target, resources={"damage_reduction": 1.2}, flags={
            "status_details": [_modifier("excess", "damage_reduction", "damage_reduction", 1.3)]})
        for bucket in self._buckets(self._calculate(), "damage_reduction"):
            self.assertEqual(bucket.multiplier, 0)
        # Preserve the nonnegative damage floor; do not invent a 99% native cap.
        self.target = replace(self.target, resources={"damage_reduction": 0.995}, flags={})
        for bucket in self._buckets(self._calculate(), "damage_reduction"):
            self.assertAlmostEqual(bucket.multiplier, 0.005)

    def test_same_status_property_writes_add_before_independent_product(self):
        combined = _modifier("combined", "damage_reduction", "damage_reduction", 0.1)
        combined["modifiers"].append({
            "bucket": "damage_reduction", "key": "damage_reduction", "value": 0.2,
            "raw_path": "synthetic.combined.second_write",
        })
        independent = _modifier("independent", "damage_reduction", "damage_reduction", 0.2)
        self.target = replace(self.target, flags={"status_details": [combined, independent]})
        for bucket in self._buckets(self._calculate(), "damage_reduction"):
            self.assertAlmostEqual(bucket.multiplier, 0.7 * 0.8)
            self.assertEqual(bucket.metadata["reduction_residuals"], [1, 0.7, 0.8])
            self.assertIn("synthetic.combined.second_write", str(bucket.to_json()))

    def test_unmodified_damage_and_one_reduction_remain_unchanged(self):
        for reduction in (0, 0.3):
            self.target = replace(self.target, resources={"damage_reduction": reduction})
            direct, pipeline = self._calculate()
            expected = 1000 * (1000 / 1200) * (1 - reduction)
            self.assertAlmostEqual(direct.final_damage, expected)
            self.assertAlmostEqual(pipeline.final_amount, expected)


if __name__ == "__main__":
    unittest.main()

# --- R05 review: damage block admission, lifecycle and settlement linkage -----------------


def _r05_block_case():
    from dataclasses import replace

    from hsr.simulator_v8_clean_core.tests.test_kill_energy_shared_producer import (
        _primitive_case,
    )

    state, packet = _primitive_case()
    detail = {
        "instance_id": "block:instance",
        "status_id": "modifier:BlockDamage_Count",
        "modifier_name": "BlockDamage_Count",
        "owner_id": "target",
        "caster_id": "target",
        "stacks": 1,
        "lifecycle_state": "active",
        "behavior_flags": ["BlockDamageExcludeDot"],
    }
    target = replace(
        state.units["target"],
        hp=100.0,
        statuses=(detail["status_id"],),
        flags={"status_details": [detail]},
    )
    state = replace(state, units={**state.units, "target": target})
    return state, replace(packet, damage_formula_family="direct")


def test_r05_damage_block_does_not_admit_an_invalid_direct_packet():
    from dataclasses import replace

    from hsr.simulator_v8_clean_core.systems.damage import DamageSystem

    state, packet = _r05_block_case()
    without_block = replace(
        state,
        units={
            **state.units,
            "target": replace(state.units["target"], flags={}, statuses=()),
        },
    )
    control = DamageSystem().apply_packet(without_block, packet)
    assert not control.ok, control.to_json()
    result = DamageSystem().apply_packet(state, packet)
    assert not result.ok and not result.mutations, result.to_json()


def test_r05_exhausted_damage_block_links_every_native_mutation():
    from dataclasses import replace

    from hsr.simulator_v8_clean_core.rules.ir import ActionDefinitionIR, IRSource
    from hsr.simulator_v8_clean_core.systems.damage import DamagePacket, DamageSystem

    state, previous = _r05_block_case()
    state = replace(
        state,
        units={
            **state.units,
            "source": replace(state.units["source"], attack=10.0),
        },
    )
    source = IRSource("component", "validation", "normal-hit")
    action = ActionDefinitionIR(
        "definition", "action", 1, "Normal", "SingleAttack", "Single",
        0, 0, 0, 0, (), (), (), "Fire", source,
    )
    packet = DamagePacket(
        "source", "target", "Normal", "direct", action_definition=action,
        scaling_ratio=1.0,
        scaling_basis={"kind": "unit_stat", "unit_ref": "attacker", "stat": "attack"},
        element_type="Fire", source_frame=previous.source_frame,
        source_trace=source.to_json(), metadata={"crit_mode": "noncrit"},
    )
    control_state = replace(
        state,
        units={
            **state.units,
            "target": replace(state.units["target"], flags={}, statuses=()),
        },
    )
    assert DamageSystem().apply_packet(control_state, packet).ok
    result = DamageSystem().apply_packet(state, packet)
    assert result.ok
    mutation_ids = {mutation.stable_id() for mutation in result.mutations}
    record_ids = {record.get("mutation_id") for record in result.records}
    assert mutation_ids <= record_ids, {
        "unlinked_mutations": mutation_ids - record_ids,
    }


def test_r05_status_damage_pursued_formula_keeps_the_break_chain():
    import json
    from pathlib import Path

    from hsr.simulator_v8_clean_core.tbgd.lowering import (
        _status_callback_task_admission,
    )

    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    data = json.loads(
        (root / "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json").read_text()
    )
    for modifier in ("MCommon_Element_Frozen", "MCommon_Element_Entangle"):
        tasks = [
            task
            for callback in data["ModifierMap"][modifier]["_CallbackList"]
            if callback["Event"] == "OnPhase1"
            for task in callback["CallbackConfig"]
            if task.get("$type") == "RPG.GameCore.DamageByAttackProperty"
        ]
        assert len(tasks) == 1
        attack = tasks[0]["AttackProperty"]
        assert attack["FormulaType"] == "ByBreakDamage"
        assert attack["AttackType"] == "Pursued"
        assert _status_callback_task_admission(
            "OnPhase1", "DamageByAttackProperty", tasks[0]
        ) == ("executable", "")

def test_r05_damage_block_consumes_one_remaining_layer_formally():
    from dataclasses import replace

    from hsr.simulator_v8_clean_core.rules.ir import ActionDefinitionIR, IRSource
    from hsr.simulator_v8_clean_core.systems.damage import DamagePacket, DamageSystem

    state, previous = _r05_block_case()
    target = state.units["target"]
    layered = {
        **target.flags["status_details"][0],
        "stacks": 2,
        "max_stacks": 2,
        "stack_policy": "Layer",
    }
    state = replace(
        state,
        units={
            **state.units,
            "target": replace(
                target,
                flags={"status_details": [layered]},
                statuses=(layered["status_id"],),
            ),
            "source": replace(state.units["source"], attack=10.0),
        },
    )
    source = IRSource("component", "validation", "normal-hit")
    action = ActionDefinitionIR(
        "definition", "action", 1, "Normal", "SingleAttack", "Single",
        0, 0, 0, 0, (), (), (), "Fire", source,
    )
    packet = DamagePacket(
        "source", "target", "Normal", "direct", action_definition=action,
        scaling_ratio=1.0,
        scaling_basis={"kind": "unit_stat", "unit_ref": "attacker", "stat": "attack"},
        element_type="Fire", source_frame=previous.source_frame,
        source_trace=source.to_json(), metadata={"crit_mode": "noncrit"},
    )
    result = DamageSystem().apply_packet(state, packet)
    assert result.ok, result.errors
    mutation_ids = {mutation.stable_id() for mutation in result.mutations}
    record_ids = {record.get("mutation_id") for record in result.records}
    assert mutation_ids <= record_ids
    after_details = next(
        mutation.after
        for mutation in result.mutations
        if mutation.path == ("units", "target", "flags", "status_details")
    )
    assert after_details[0]["stacks"] == 1


@pytest.mark.parametrize(
    "basis",
    [
        {"kind": "unsupported"},
        {"kind": "unit_stat", "unit_ref": "attacker", "stat": "unsupported"},
        {"kind": "unit_stat", "unit_ref": "unbound", "stat": "attack"},
    ],
)
def test_r05_block_preserves_the_real_formula_basis_admission(basis):
    from dataclasses import replace

    from hsr.simulator_v8_clean_core.systems.damage import DamageSystem

    state, packet = _r05_block_case()
    packet = replace(packet, scaling_basis=basis)
    without_block = replace(
        state,
        units={
            **state.units,
            "target": replace(state.units["target"], statuses=(), flags={}),
        },
    )
    control = DamageSystem().apply_packet(without_block, packet)
    assert not control.ok, control.to_json()
    result = DamageSystem().apply_packet(state, packet)
    assert not result.ok and not result.mutations and not result.rng_events


def test_r05_block_preserves_elation_actor_authority_admission():
    from dataclasses import replace

    from hsr.simulator_v8_clean_core.systems.damage import DamageSystem
    from hsr.simulator_v8_clean_core.systems.elation import (
        resolve_elation_damage_context,
    )

    from hsr.simulator_v8_clean_core.systems.damage import DamagePacket

    state, previous = _r05_block_case()
    context = resolve_elation_damage_context(state, "target", point_source="echo")
    packet = DamagePacket(
        "source",
        "target",
        "Normal",
        "elation",
        elation_context=context,
        scaling_ratio=1.0,
        scaling_basis={"kind": "elation_level_base"},
        source_frame=previous.source_frame,
        source_trace={
            "kind": "validation_fixture",
            "scope": "elation actor authority",
        },
        metadata={"crit_mode": "noncrit"},
    )
    without_block = replace(
        state,
        units={
            **state.units,
            "target": replace(state.units["target"], statuses=(), flags={}),
        },
    )
    control = DamageSystem().apply_packet(without_block, packet)
    assert not control.ok
    assert "elation_context_actor_mismatch" in control.errors, control.errors
    result = DamageSystem().apply_packet(state, packet)
    assert not result.ok and not result.mutations and not result.rng_events, {
        "control": control.errors,
        "ok": result.ok,
        "writes": [list(mutation.path) for mutation in result.mutations],
    }
