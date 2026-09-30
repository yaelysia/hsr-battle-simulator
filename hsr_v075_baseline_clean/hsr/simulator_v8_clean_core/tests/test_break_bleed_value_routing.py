"""The pinned ordinary Bleed request already contains its Break Effect factor."""
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.rules.engine_rule_registry import build_engine_rule_registry
from hsr.simulator_v8_clean_core.rules.evaluator import NumericEvaluationContext, RuleEvaluator
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.damage import DamagePacket, DamageSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering


def test_real_bleed_value_keeps_target_factors_without_second_break_bonus():
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    lowering = TBGDLowering(root)
    templates, _, _, _, _, _ = lowering._lower_break_templates()
    lowered = lowering._lower_ability_file(
        root / "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json",
        {}, ability_file_order=0,
    )
    emission = next(item for item in lowered.status_damage_emissions
                    if item.modifier_name == "MCommon_Element_Bleed" and item.event == "OnPhase1")
    assert (emission.damage_formula_family, emission.break_amount_mode,
            emission.base_includes_break_bonus, emission.coverage_status) == (
        "break", "value", True, "executable",
    )
    entries = {
        f"value_{index}": {"scope": "status_instance", "owner_id": "target",
                           "name": f"bleed_value_{index}", "hash": str(hash_key), "value": value}
        for index, (hash_key, value) in enumerate((
            (286452074, 100.0), (369211422, 0.5), (1912601768, 1.0),
        ))
    }
    source = {"source_type": "status_instance", "status_instance_id": "bleed-1",
              "entries": entries,
              "by_hash": {entry["hash"]: [key] for key, entry in entries.items()}}
    evaluated = RuleEvaluator().evaluate_numeric(
        emission.scaling_expr, NumericEvaluationContext(binding_sources=(source,)),
    )
    assert evaluated.ok, evaluated.to_json()
    assert evaluated.value == pytest.approx(150.0)  # capped base 100 × (1 + BE 0.5) × layer 1

    rules = RuleBook(CanonicalIR(
        "real-bleed-value-check", break_templates=tuple(templates),
        status_damage_emissions=(emission,),
    ))
    state = BattleState(units={
        "attacker": UnitState("attacker", "ally", "fixture:attacker", level=80,
                              resources={"break_damage_added_ratio": 0.5,
                                         "damage_added_ratio": 2.0, "crit_rate": 1.0,
                                         "crit_damage": 2.0}),
        "target": UnitState("target", "enemy", "fixture:target", level=80,
                            max_hp=1000.0, hp=1000.0, defense=100.0,
                            resources={"Physical_resistance": 0.2,
                                       "damage_taken_ratio": 0.1,
                                       "damage_reduction": 0.1}),
    })
    packet = DamagePacket(
        attacker_id="attacker", target_id="target", attack_type=emission.attack_type,
        damage_formula_family=emission.damage_formula_family,
        amount=evaluated.value, amount_stage="family_base", element_type=emission.element_type,
        status_damage_emission_id=emission.status_damage_emission_id,
        break_template_id="break_template:StanceBreak_Physical",
        base_includes_break_bonus=emission.base_includes_break_bonus,
    )
    result = DamageSystem(rules, engine_rules=build_engine_rule_registry()).apply_packet(state, packet)
    assert result.ok, result.errors
    assert next(item.after for item in result.mutations if item.path == ("units", "target", "hp")) == pytest.approx(892.0)
    pipeline = next(item["payload"]["damage_pipeline"] for item in result.records
                    if item["record_type"] == "break_dot_tick")
    stages = {item["stage"]: item for item in pipeline["stages"]}
    assert all(not stages[name]["applicable"] for name in ("critical", "damage_bonus", "break_bonus"))
    assert all(stages[name]["applicable"] for name in ("defense", "resistance", "damage_taken", "damage_reduction"))
