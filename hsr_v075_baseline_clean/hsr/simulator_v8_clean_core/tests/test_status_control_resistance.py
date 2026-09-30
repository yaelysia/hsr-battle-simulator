from __future__ import annotations

import json
import math
import sys
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, EffectIR, IRSource
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.status import (
    StatusSystem, _runtime_chance_admission, _runtime_modifiers,
)
from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem
from hsr.simulator_v8_clean_core.systems.unit_stats import effective_status_resistance
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering, _attach_target_expressions_to_effect_payload,
    _standard_add_modifier_payload, _standard_remove_modifier_payload,
    _synchronize_effect_target_expression_metadata,
)
from hsr.simulator_v8_clean_core.tbgd.target_source import (
    build_target_language_definitions, close_target_expression_language,
)


@lru_cache(maxsize=1)
def _source_case():
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    relative = "Config/ConfigAbility/Avatar/Avatar_Luocha_00_Ability.json"
    document = json.loads((root / relative).read_text())
    index, ability = next(
        (i, ability) for i, ability in enumerate(document["AbilityList"])
        if ability.get("Name") == "Avatar_Luocha_SkillTree03"
    )
    raw = ability["OnStart"][0]
    name = raw["ModifierName"]["Value"]
    lowered = TBGDLowering(root)._lower_ability_file(root / relative, {}, ability_file_order=0)
    definition = next(row for row in lowered.entities if row.fields.get("modifier_name") == name)
    callbacks = tuple(row for row in lowered.status_callbacks if row.modifier_name == name)
    tasks = tuple(row for row in lowered.status_callback_tasks if row.modifier_name == name)
    source = IRSource(relative, "AddModifier", "test:control_resistance", {"json_path": f"$.AbilityList[{index}].OnStart[0]"})
    payload, expressions = _attach_target_expressions_to_effect_payload(
        {"standard": _standard_add_modifier_payload(raw)}, raw,
        effect_id="test:control_resistance", source=source,
    )
    definitions = build_target_language_definitions(root)
    expressions = [close_target_expression_language(row, definitions) for row in expressions]
    effect = EffectIR(
        "test:control_resistance", "AddModifier", payload, source,
        coverage_status="executable", modifier_definition_id=definition.entity_id,
        status_callback_ids=tuple(row.callback_id for row in callbacks),
        source_mode="mainline",
    )
    effect = _synchronize_effect_target_expression_metadata([effect], expressions)[0]
    # Cleanup is a synthetic RemoveModifier request, not an authored Luocha expiry claim.
    remove_raw = {"$type": "RPG.GameCore.RemoveModifier", "TargetType": raw["TargetType"], "ModifierName": raw["ModifierName"]}
    remove_source = IRSource("fixture/control_resistance_remove.json", "RemoveModifier", "test:remove", {"json_path": "$.OnStart[0]"})
    remove_payload, remove_expressions = _attach_target_expressions_to_effect_payload(
        {"standard": _standard_remove_modifier_payload(remove_raw, "RemoveModifier", "")},
        remove_raw, effect_id="test:remove", source=remove_source,
    )
    remove_expressions = [close_target_expression_language(row, definitions) for row in remove_expressions]
    remove_effect = EffectIR("test:remove", "RemoveModifier", remove_payload, remove_source, coverage_status="executable", source_mode="mainline")
    remove_effect = _synchronize_effect_target_expression_metadata([remove_effect], remove_expressions)[0]
    rules = RuleBook(CanonicalIR(
        "test", entities=(definition,), effects=(effect, remove_effect),
        status_callbacks=callbacks, status_callback_tasks=tasks,
        target_expressions=(*expressions, *remove_expressions, *(row.expression for row in definitions)),
    ))
    return rules, effect, definition, callbacks[0], tasks[0]


def _state():
    return BattleState(units={
        "holder": UnitState("holder", "ally", "test:holder", hp=100.0, max_hp=100.0, resources={"effect_resistance": 0.3}),
        "opponent": UnitState("opponent", "enemy", "test:opponent", hp=100.0, max_hp=100.0),
    })


def _apply(state, rules=None, effect=None, *, dynamic_values=None):
    source_rules, source_effect, *_ = _source_case()
    return StatusSystem(rules or source_rules).apply_add_modifier(
        state, effect or source_effect, caster_id="holder", source_id="test:trace",
        dynamic_values=({"1153510288": 0.7} if dynamic_values is None else dynamic_values),
    )


def test_real_source_control_resistance_applies_once_and_removes():
    rules, effect, _, callback, task = _source_case()
    state = _state()
    applied = _apply(state)
    assert applied.ok, applied.unsupported
    after = MutationReducer().apply_all(state, applied.mutations)
    assert state.units["holder"].statuses == ()
    control = effective_status_resistance(after.units["holder"], control_kind="CTRL_Frozen")
    ordinary = effective_status_resistance(after.units["holder"])
    assert math.isclose(control.resistance_chance, 0.79)
    assert ordinary.control_resistance == 0.0
    for category, expected in (("control", 0.21), ("debuff", 0.7)):
        chance = _runtime_chance_admission(
            {"chance": {"kind": "fixed", "value": 1.0}}, effect, after,
            caster_id="opponent", target_id="holder", dynamic_values=None, binding_sources=(),
            status_metadata={"status_category": category, "control_kind": "CTRL_Frozen"},
        )
        assert math.isclose(chance["final_success_probability"], expected)
    detail = after.units["holder"].flags["status_details"][0]
    result = StatusCallbackSystem(rules)._execute_task(
        after, callback, task, detail, None, {task.task_id: task}, None,
    )
    assert result.ok, result.errors
    assert not result.mutations
    assert detail["modifiers"][0]["producer_task_path"] == task.task_path
    wrong = replace(task, task_path=task.task_path + ".other")
    mismatch = StatusCallbackSystem(rules)._execute_task(
        after, callback, wrong, detail, None, {wrong.task_id: wrong}, None,
    )
    assert not mismatch.ok and not mismatch.mutations
    foreign = replace(task, task_payload={**task.task_payload, "status_resistance_producer_key": "other:source"})
    mismatch = StatusCallbackSystem(rules)._execute_task(
        after, callback, foreign, detail, None, {foreign.task_id: foreign}, None,
    )
    assert not mismatch.ok and not mismatch.mutations
    repeated = _apply(after)
    assert repeated.ok, repeated.unsupported
    refreshed = MutationReducer().apply_all(after, repeated.mutations)
    assert math.isclose(effective_status_resistance(refreshed.units["holder"], control_kind="CTRL_Frozen").control_resistance, 0.7)
    removed = StatusSystem(rules).apply_remove_modifier(
        after, rules.effect("test:remove"), caster_id="holder", source_id="test:remove",
    )
    assert removed.ok, removed.unsupported
    final = MutationReducer().apply_all(after, removed.mutations)
    assert effective_status_resistance(final.units["holder"], control_kind="CTRL_Frozen").control_resistance == 0.0


def test_missing_parameter_unknown_category_and_foreign_holder_fail_closed():
    rules, effect, definition, *_ = _source_case()
    missing = _apply(_state(), dynamic_values={})
    assert not missing.ok and not missing.mutations
    fields = dict(definition.fields)
    fields["stack_properties"] = [{**fields["stack_properties"][0], "behavior_flag": "UnknownCategory"}]
    unknown = replace(definition, fields=fields)
    blocked = _apply(_state(), RuleBook(replace(rules.ir, entities=(unknown,))), effect)
    assert not blocked.ok and not blocked.mutations
    modifiers, unsupported = _runtime_modifiers(
        definition, {"741349151": 0.7}, caster_id="opponent", target_id="holder",
    )
    assert not modifiers and unsupported == ["status_resistance_target_is_not_holder"]


def test_overlap_and_callback_without_installed_producer_fail_closed():
    rules, effect, definition, callback, task = _source_case()
    state = _state()
    unit = state.units["holder"]
    state = replace(state, units={**state.units, "holder": replace(unit, resources={**unit.resources, "control_resistance": 0.2})})
    result = _apply(state)
    assert not result.ok and not result.mutations
    assert "status_resistance_overlap_not_admitted" in result.unsupported
    duplicate = replace(definition, fields={
        **definition.fields, "stack_properties": definition.fields["stack_properties"] * 2,
    })
    blocked = _apply(_state(), RuleBook(replace(rules.ir, entities=(duplicate,))), effect)
    assert not blocked.ok and not blocked.mutations
    assert "status_resistance_overlap_not_admitted" in blocked.unsupported
    blocked = StatusCallbackSystem(rules)._execute_task(
        _state(), callback, task, {"modifiers": []}, None, {task.task_id: task}, None,
    )
    assert not blocked.ok and not blocked.mutations


if __name__ == "__main__":
    test_real_source_control_resistance_applies_once_and_removes()
    test_missing_parameter_unknown_category_and_foreign_holder_fail_closed()
    test_overlap_and_callback_without_installed_producer_fail_closed()
    print("status control resistance: 3 checks passed")
