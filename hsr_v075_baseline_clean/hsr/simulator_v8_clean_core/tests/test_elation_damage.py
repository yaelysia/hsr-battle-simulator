"""One small formula and normal-shield discriminator; no source compilation."""
from dataclasses import replace
import unittest

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.engine_rule_registry import build_engine_rule_registry
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, DamageModifierIR, FormulaIR, IRSource
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.damage import DamageModifierContribution, DamagePacket, DamageSystem
from hsr.simulator_v8_clean_core.systems.elation import resolve_elation_damage_context
from hsr.simulator_v8_clean_core.systems.shield import ShieldSystem


class ElationDamageTest(unittest.TestCase):
    def test_formula_shared_modifiers_and_parallel_shields(self):
        source = IRSource("fixture:elation", "formula", "formula")
        registry = build_engine_rule_registry()
        formulas = (
            FormulaIR("formula:elation_level_base", "elation_level_base", {"values": {"80": 1000}}, source, "executable"),
            FormulaIR("formula:elation_multiplier_rule", "elation_multiplier_rule",
                      {"punchline_numerator": 5.0, "punchline_offset": 240.0}, source, "executable"),
        )
        rules = RuleBook(CanonicalIR("fixture:elation", formulas=formulas,
            damage_formula_rules=registry.damage_formula_rules,
            damage_route_rules=registry.damage_route_rules,
            shield_priority_rules=registry.shield_priority_rules))
        actor = UnitState("actor", "ally", "fixture:actor", attack=999999, max_hp=999999, hp=999999,
            resources={"critical_chance": 1, "critical_damage": .5, "elation_echo_point": 40,
                "elation_damage_added_ratio": .2, "elation_damage_extra_added_ratio": .1,
                "damage_added_ratio": 90, "Fire_damage_added_ratio": 90, "weaken": .9},
            flags={"status_details": [{"instance_id": "elation-buff", "modifiers": [
                {"bucket": "damage_bonus", "key": "elation_damage_added_ratio", "value": .3},
                {"bucket": "damage_bonus", "key": "elation_damage_extra_added_ratio", "value": .1},
                {"bucket": "weaken", "key": "weaken_ratio", "scope": "actor", "value": .9},
            ]}]})
        target = UnitState("target", "enemy", "fixture:target", hp=10000, max_hp=10000,
            defense=200, toughness=30, max_toughness=30,
            resources={"Fire_resistance": .2, "damage_taken_ratio": .1, "damage_reduction": .2},
            flags={"status_details": [{"instance_id": "reduction", "modifiers": [
                {"bucket": "damage_reduction", "key": "damage_reduction", "value": .3},
            ]}]})
        state = BattleState(units={"actor": actor, "target": target})
        for shield_id, amount in (("small", 100.), ("large", 200.)):
            grant = ShieldSystem().apply_effect(state, target_id="target", shield_id=shield_id,
                source_id=shield_id, source_kind="fixture", opcode="InitShield", amount=amount,
                source_trace=source.to_json(), actor_id="actor", event_source_id="actor")
            self.assertTrue(grant.ok, grant.blocked_reason)
            state = MutationReducer().apply_all(state, (grant.mutation,))
        transient = DamageModifierIR("modifier:hit", "callback:hit", "task:hit", "fixture", "OnBeforeHit",
            "ParamEntity", ({"bucket": "damage_taken", "key": "damage_taken_ratio"},
                            {"bucket": "damage_bonus", "key": "damage_added_ratio"}), source, "executable")
        packet = DamagePacket("actor", "target", "ElationDamage", "elation", element_type="Fire",
            damage_emission_id="emission:elation", source_task_id="task:elation", scaling_ratio=2.,
            scaling_basis={"kind": "elation_level_base"}, source_trace=source.to_json(),
            modifier_contributions=(DamageModifierContribution(transient, 0, .1),
                                    DamageModifierContribution(transient, 1, 999.)),
            elation_context=resolve_elation_damage_context(state, "actor", point_source="echo"))
        before = state.snapshot().to_json()
        hit = DamageSystem(rules).apply_packet(state, packet)
        self.assertTrue(hit.ok, hit.errors)
        payload = next(row["payload"] for row in hit.records if row["record_type"] == "damage")
        expected = 1000 * 2 * 1.5 * 1.5 * (1 + 5 * 40 / 280) * 1.2 * (1000 / 1200) * .8 * 1.2 * .8 * .7 * .9
        self.assertAlmostEqual(payload["final_damage"], expected)
        self.assertEqual(len(hit.rng_events), 1)
        self.assertTrue(payload["crit_resolution"]["is_crit"])
        stages = {row["stage"]: row for row in payload["damage_pipeline"]["stages"]}
        for excluded in ("base", "damage_bonus", "weakness"):
            self.assertFalse(stages[excluded]["applicable"])
        self.assertIn("modifier:hit", str(stages["damage_bonus"]["bucket"]["skipped_terms"]))
        self.assertEqual(payload["elation_formula"]["level_formula_source"], source.to_json())
        committed = MutationReducer().apply_all_result(state, hit.mutations)
        self.assertTrue(committed.ok, committed.to_json())
        self.assertAlmostEqual(committed.after_state.units["target"].hp, 10000 - expected + 200)
        self.assertEqual(committed.after_state.units["target"].shield_instances, ())
        override = DamageModifierIR("modifier:elation-hit", "callback:hit", "task:elation-hit", "fixture",
            "OnListenBeforeHitAll", "ModifierOwnerEntity", (
                {"bucket": "elation_bonus", "key": "elation_damage_added_ratio"},
                {"bucket": "elation_context", "key": "points"},
                {"bucket": "elation_context", "key": "point_multiplier_enabled"},
            ), source, "executable")
        contributions = (*packet.modifier_contributions, DamageModifierContribution(override, 0, .7),
            DamageModifierContribution(override, 1, 20), DamageModifierContribution(override, 2, 0))
        context = resolve_elation_damage_context(state, "actor", point_source="echo",
            modifier_contributions=contributions)
        overridden_packet = replace(packet, modifier_contributions=contributions, elation_context=context)
        overridden = DamageSystem(rules).apply_packet(state, overridden_packet)
        self.assertTrue(overridden.ok, overridden.errors)
        overridden_payload = next(row["payload"] for row in overridden.records if row["record_type"] == "damage")
        overridden_expected = expected * (2.2 / 1.5) * ((1 + 5 * 20 / 260) / (1 + 5 * 40 / 280))
        self.assertAlmostEqual(overridden_payload["final_damage"], overridden_expected)
        self.assertEqual(context.points, 20)
        overridden_stages = {row["stage"]: row for row in overridden_payload["damage_pipeline"]["stages"]}
        self.assertAlmostEqual(overridden_stages["elation_bonus"]["multiplier"], 2.2)
        self.assertEqual(sum(term.get("source_id") == override.damage_modifier_id
            for term in overridden_stages["elation_bonus"]["bucket"]["applied_terms"]), 1)
        for current, invalid in (
            (state, replace(overridden_packet, modifier_contributions=packet.modifier_contributions)),
            (state, replace(overridden_packet, elation_context=packet.elation_context)),
            (replace(state, event_index=state.event_index + 1), overridden_packet),
        ):
            rejected = DamageSystem(rules).apply_packet(current, invalid)
            self.assertFalse(rejected.ok)
            self.assertEqual(rejected.mutations, ())
            self.assertEqual(rejected.rng_events, ())
        for invalid_terms in (
            (DamageModifierContribution(override, 2, 1), DamageModifierContribution(override, 1, 20)),
            (DamageModifierContribution(override, 2, 0),),
            (DamageModifierContribution(override, 1, -1),),
            (DamageModifierContribution(override, 1, 20), DamageModifierContribution(override, 1, 30)),
        ):
            with self.assertRaises(ValueError):
                resolve_elation_damage_context(state, "actor", point_source="echo",
                    modifier_contributions=invalid_terms)
        for invalid in (replace(packet, elation_context=None), replace(packet, amount=1000),
                        replace(packet, scaling_basis={"kind": "unit_stat", "stat": "attack"})):
            rejected = DamageSystem(rules).apply_packet(state, invalid)
            self.assertFalse(rejected.ok)
            self.assertEqual(rejected.mutations, ())
            self.assertEqual(rejected.rng_events, ())
        missing_level = RuleBook(replace(rules.ir, formulas=(replace(formulas[0], expression={"values": {"79": 1}}), formulas[1])))
        self.assertEqual(DamageSystem(missing_level).apply_packet(state, packet).errors,
                         ("elation_level_base_missing_or_invalid",))
        self.assertEqual(state.snapshot().to_json(), before)


if __name__ == "__main__":
    unittest.main()
