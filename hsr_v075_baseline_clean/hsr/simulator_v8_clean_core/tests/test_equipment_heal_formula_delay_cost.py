"""R06 components: healer-ATK heal default, additive current-skill delay cost and
Remodifier IncludeLimbo admission, using the real TBGD equipment shapes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.ir import (
    CanonicalIR, EffectIR, IRSource, StatusCallbackIR, StatusCallbackTaskIR, TimelineRuleIR,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry
from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem
from hsr.simulator_v8_clean_core.systems.timeline import TimelineSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _effect_coverage_status, _effect_payload, _equipment_task_admission,
    _remodifier_task_admission, _status_callback_runtime_payload,
)

ROOT = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"


def _walk(value, wanted: str):
    if isinstance(value, dict):
        if str(value.get("$type", "")).rsplit(".", 1)[-1] == wanted:
            yield value
        for item in value.values():
            yield from _walk(item, wanted)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item, wanted)


def _ability_document(relative: str, ability_name: str) -> dict:
    document = json.loads((ROOT / relative).read_text())
    for ability in document["AbilityList"]:
        if ability.get("Name") == ability_name:
            return ability
    raise AssertionError(f"ability source missing: {ability_name}")


def _heal_effect(percentage: float | None, flat: float | None = None) -> EffectIR:
    raw = {
        "$type": "RPG.GameCore.HealHP",
        "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "ParamEntity"},
    }
    if percentage is not None:
        raw["HealPercentage"] = {"IsDynamic": False, "FixedValue": {"Value": percentage}}
    if flat is not None:
        raw["ModifyValue"] = {"IsDynamic": False, "FixedValue": {"Value": flat}}
    payload = _effect_payload(raw, "HealHP", "")
    return EffectIR(
        "test:heal", "HealHP", payload,
        IRSource("synthetic:heal", "HealHP", "test"),
        _effect_coverage_status("HealHP", payload),
    )


def _heal_state() -> BattleState:
    return BattleState(units={
        "caster": UnitState("caster", "ally", "synthetic:caster", max_hp=5000.0, hp=1000.0,
                            attack=1000.0, defense=200.0),
        "target": UnitState("target", "ally", "synthetic:target", max_hp=2000.0, hp=1000.0,
                            defense=100.0),
    })


def _execute_heal(effect: EffectIR):
    state = _heal_state()
    before = state.snapshot().to_json()
    context = EffectExecutionContext(state, "caster", "synthetic:heal", owner_id="target",
                                     param_entity_id="target", current_action_target_id="target")
    result = EffectRegistry().execute(effect, context)
    assert state.snapshot().to_json() == before
    return state, result


def test_real_light_cone_heal_shapes_adopt_the_healer_attack_base():
    cases = []
    for relative, ability_name, hashes in (
        ("Config/ConfigAbility/Equip/EquipmemtAbility.json", "Ability21033", {-189278419}),
        ("Config/ConfigAbility/Equip/EquipmemtAbility.json", "Ability23002", {-433231534}),
        ("Config/ConfigAbility/Equip/Equip36.json", "Ability23051", {-1986698890, 545944933}),
    ):
        ability = _ability_document(relative, ability_name)
        seen = set()
        for task in _walk(ability, "HealHP"):
            digests = {
                int(item)
                for item in task["HealPercentage"]["PostfixExpr"]["DynamicHashes"]
            }
            seen.update(digests)
            payload = _effect_payload(task, "HealHP", "")
            standard = payload["standard"]
            assert standard["formula_type"] == "HealByHealerAttack", (ability_name, digests)
            assert standard["formula_base"] == "caster.attack"
            assert standard["amount_role"] == "ratio"
            assert standard["formula_type_source"] == "adopted_healer_attack_default"
            assert standard.get("blocked_reason", "") == ""
            assert _effect_coverage_status("HealHP", payload) == "executable"
        assert seen == hashes, (ability_name, seen)
        cases.append(ability_name)
    assert cases == ["Ability21033", "Ability23002", "Ability23051"]


def test_healer_attack_heal_ratio_applies_to_effective_attack():
    state, result = _execute_heal(_heal_effect(0.12))
    assert not result.unsupported, result.records
    details = result.mutations[0].metadata["formula_details"]
    assert details["formula_type"] == "HealByHealerAttack"
    assert details["formula_base"] == "caster.attack"
    assert details["base_value"] == pytest.approx(1000.0)
    assert details["base_amount"] == pytest.approx(120.0)
    after = MutationReducer().apply_all(state, result.mutations)
    assert after.units["target"].hp == pytest.approx(1120.0)


def test_healer_attack_ratio_with_flat_addition_keeps_both_terms():
    state, result = _execute_heal(_heal_effect(0.1, flat=80.0))
    assert not result.unsupported, result.records
    details = result.mutations[0].metadata["formula_details"]
    assert details["base_amount"] == pytest.approx(180.0)
    after = MutationReducer().apply_all(state, result.mutations)
    assert after.units["target"].hp == pytest.approx(1180.0)


def test_malformed_or_conflicting_heal_shapes_stay_fail_closed():
    conflicting = {
        "$type": "RPG.GameCore.HealHP",
        "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "ParamEntity"},
        "FormulaType": "HealByHealerMaxHP",
        "HealPercentage": {"IsDynamic": False, "FixedValue": {"Value": 0.1}},
        "ModifyValue": {},
    }
    payload = _effect_payload(conflicting, "HealHP", "")
    assert payload["standard"]["blocked_reason"]
    assert _effect_coverage_status("HealHP", payload) == "blocked"
    missing = {
        "$type": "RPG.GameCore.HealHP",
        "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "ParamEntity"},
        "FormulaType": "HealByHealerAttack",
    }
    assert _effect_coverage_status("HealHP", _effect_payload(missing, "HealHP", "")) == "blocked"


def _delay_fixture():
    relative = "Config/ConfigAbility/Equip/EquipmemtAbility.json"
    ability = _ability_document(relative, "Ability20015")
    modifier = ability["Modifiers"]["MEquip_20015_Main"]
    raw = modifier["_CallbackList"][0]["CallbackConfig"][0]["SuccessTaskList"][0]
    assert raw["$type"].rsplit(".", 1)[-1] == "ModifyCurrentSkillDelayCost"
    assert "ModifyFunction" not in raw
    source = IRSource(relative, "ModifyCurrentSkillDelayCost", "test:20015", {
        "json_path": "$.AbilityList[16].Modifiers.MEquip_20015_Main._CallbackList[0]"
                     ".CallbackConfig[0].SuccessTaskList[0]",
    })
    callback = StatusCallbackIR("test:20015", "MEquip_20015_Main", "OnBeforeSkillUse",
                                ("test:20015-task",), source, (0, 0),
                                coverage_status="executable", admission_status="executable")
    payload = _effect_payload(raw, "ModifyCurrentSkillDelayCost",
                              callback.modifier_name, source=source)
    effect = EffectIR("test:20015-effect", "ModifyCurrentSkillDelayCost", payload,
                      source, _effect_coverage_status("ModifyCurrentSkillDelayCost", payload))
    task = StatusCallbackTaskIR("test:20015-task", callback.callback_id,
                                callback.modifier_name, callback.event, 0,
                                "CallbackConfig[0].SuccessTaskList[0]", "root",
                                "ModifyCurrentSkillDelayCost", source,
                                effect_id=effect.effect_id,
                                coverage_status="executable",
                                task_payload=_status_callback_runtime_payload(raw))
    rule = TimelineRuleIR("test:ordinary-clock", 10000, "base_action_gauge_div_speed",
                          "base_action_gauge_div_speed", "engine_convention",
                          IRSource("fixture:clock", "test", "clock"))
    rules = RuleBook(CanonicalIR("test:delay", status_callbacks=(callback,),
                                 status_callback_tasks=(task,), effects=(effect,),
                                 timeline_rules=(rule,)))
    state = BattleState(
        units={"holder": UnitState("holder", "enemy", "test:holder", hp=100.0,
                                   max_hp=100.0, speed=100.0, action_value=17.0)},
        global_flags={
            "turn_owner_id": "holder",
            "active_turn": {"actor_id": "holder", "turn_kind": "regular",
                            "turn_sequence_index": 1,
                            "timeline_rule_id": rule.timeline_rule_id},
            "current_window": "turn_active",
        },
    )
    return rules, state, callback, task, raw, rule


def test_real_omitted_delay_cost_operation_is_additive_action_advance():
    rules, state, callback, task, raw, rule = _delay_fixture()
    status, reason = _equipment_task_admission(callback.event, task.opcode, raw,
                                               modifier_name=callback.modifier_name)
    assert status == "executable", reason
    payload = _effect_payload(raw, "ModifyCurrentSkillDelayCost", callback.modifier_name,
                              source=task.source)
    standard = payload["standard"]
    assert standard["modify_function"] == "Add"
    assert standard["omitted_modify_function"] is True
    assert standard["adopted_rule_source"]["kind"] == "adopted_mechanism_data"
    assert _effect_coverage_status("ModifyCurrentSkillDelayCost", payload) == "executable"
    result = StatusCallbackSystem(rules)._execute_current_skill_delay_cost_task(
        state, callback, task,
        {
            "owner_id": "holder",
            "instance_id": "test:20015-instance",
            # Light-cone parameter binding carried by the formal startup spec.
            "dynamic_values": {"-1928492453": 0.12},
        },
        GameEvent("action.window.before_skill_use", source_id="holder",
                  event_id="event:20015", payload={"actor_id": "holder"}),
    )
    assert result.ok, result.errors
    finished = TimelineSystem().end_turn(result.after_state, "holder", rule)
    assert finished.plan.ok, finished.plan.blocked_reason
    after = MutationReducer().apply_all(result.after_state, finished.mutations)
    # No modifier leaves 100; the -12% normalized cost advances it by 12.
    assert after.units["holder"].action_value == pytest.approx(88.0)


def test_explicit_invalid_delay_cost_operation_still_blocks():
    _, _, callback, task, raw, _ = _delay_fixture()
    for operation in (None, "Multiply"):
        candidate = {**raw, "ModifyFunction": operation}
        status, _ = _equipment_task_admission(callback.event, task.opcode, candidate,
                                              modifier_name=callback.modifier_name)
        assert status == "blocked"


def test_real_remodifier_include_limbo_field_is_admitted_as_boolean():
    relative = "Config/ConfigAbility/Equip/Equip32.json"
    ability = _ability_document(relative, "Ability23041")
    raw = ability["Modifiers"]["MEquip_23041_Main"]["_CallbackList"][1]["CallbackConfig"][0]
    assert raw["$type"].rsplit(".", 1)[-1] == "Remodifier"
    assert raw["IncludeLimbo"] is True
    status, reason = _remodifier_task_admission(raw)
    assert status == "executable", reason
    payload = _effect_payload(raw, "Remodifier", "MEquip_23041_Main")
    standard = payload["standard"]
    assert standard["blocked_reason"] == ""
    assert standard["query"]["IncludeLimbo"] is True
    assert _effect_coverage_status("Remodifier", payload) == "executable"
    for invalid in ("yes", 1, None):
        candidate = {**raw, "IncludeLimbo": invalid}
        blocked_status, blocked_reason = _remodifier_task_admission(candidate)
        assert blocked_status == "blocked"
        assert blocked_reason == "remodifier_include_limbo_not_boolean"


if __name__ == "__main__":
    test_real_light_cone_heal_shapes_adopt_the_healer_attack_base()
    test_healer_attack_heal_ratio_applies_to_effective_attack()
    test_healer_attack_ratio_with_flat_addition_keeps_both_terms()
    test_malformed_or_conflicting_heal_shapes_stay_fail_closed()
    test_real_omitted_delay_cost_operation_is_additive_action_advance()
    test_explicit_invalid_delay_cost_operation_still_blocks()
    test_real_remodifier_include_limbo_field_is_admitted_as_boolean()
    print("7 R06 equipment formula/component checks passed")
