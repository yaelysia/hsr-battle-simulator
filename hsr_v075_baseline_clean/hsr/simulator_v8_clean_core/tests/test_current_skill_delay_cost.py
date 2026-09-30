"""Pinned Frozen cost task -> producer -> turn completion; not full freeze/recovery."""
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.ir import (
    CanonicalIR, IRSource, StatusCallbackIR, StatusCallbackTaskIR, TimelineRuleIR,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem
from hsr.simulator_v8_clean_core.systems.timeline import TimelineSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import _equipment_task_admission, _status_callback_runtime_payload


def _case():
    relative = "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json"
    document = json.loads((Path(__file__).resolve().parents[4] / "turnbasedgamedata-main" / relative).read_text())
    raw = document["ModifierMap"]["MCommon_Element_Frozen"]["_CallbackList"][2]["CallbackConfig"][5]
    assert raw["$type"] == "RPG.GameCore.ModifyCurrentSkillDelayCost"
    assert raw["ModifyFunction"] == "Set"
    source = IRSource(relative, "ModifyCurrentSkillDelayCost", "test:frozen:cost", {
        "json_path": "$.ModifierMap.MCommon_Element_Frozen._CallbackList[2].CallbackConfig[5]",
    })
    callback = StatusCallbackIR("test:frozen:phase1", "MCommon_Element_Frozen", "OnPhase1",
        ("test:frozen:cost",), source, (0, 2), coverage_status="executable", admission_status="executable")
    task = StatusCallbackTaskIR("test:frozen:cost", callback.callback_id, callback.modifier_name,
        callback.event, 5, "CallbackConfig[5]", "root", "ModifyCurrentSkillDelayCost", source,
        coverage_status="executable", task_payload=raw)
    rule = TimelineRuleIR("test:ordinary-clock", 10000, "base_action_gauge_div_speed",
        "base_action_gauge_div_speed", "engine_convention", IRSource("fixture:clock", "test", "clock"))
    rules = RuleBook(CanonicalIR("test:current-cost", status_callbacks=(callback,),
        status_callback_tasks=(task,), timeline_rules=(rule,)))
    state = BattleState(units={"holder": UnitState("holder", "enemy", "test:holder",
        hp=100.0, max_hp=100.0, speed=100.0, action_value=17.0)}, global_flags={"turn_owner_id": "holder",
        "active_turn": {"actor_id": "holder", "turn_kind": "regular", "turn_sequence_index": 1,
                        "timeline_rule_id": rule.timeline_rule_id}, "current_window": "turn_active"})
    return rules, state, callback, task, rule


def _apply(rules, state, callback, task, operation, event_id):
    raw = {**task.task_payload, "ModifyFunction": operation}
    status, reason = _equipment_task_admission(callback.event, task.opcode, raw, modifier_name=callback.modifier_name)
    assert status == "executable", reason
    return StatusCallbackSystem(rules)._execute_current_skill_delay_cost_task(
        state, callback, replace(task, task_payload=_status_callback_runtime_payload(raw)),
        {"owner_id": "holder", "instance_id": "test:frozen-instance"},
        GameEvent("turn.begin", source_id="holder", event_id=event_id, payload={"actor_id": "holder"}),
    )


def test_set_and_add_keep_distinct_costs_and_committed_order():
    rules, state, callback, task, rule = _case()
    for operations, expected in (((), 100), (("Set",), 50), (("Add",), 150),
                                 (("Set", "Add"), 100), (("Add", "Set"), 50)):
        candidate = state
        for index, operation in enumerate(operations):
            # Reverse lexical event IDs to distinguish producer order from sorting IDs.
            result = _apply(rules, candidate, callback, task, operation, f"event:{9-index}")
            assert result.ok, result.errors
            candidate = result.after_state
        finished = TimelineSystem().end_turn(candidate, "holder", rule)
        assert finished.plan.ok, finished.plan.blocked_reason
        after = MutationReducer().apply_all(candidate, finished.mutations)
        assert after.units["holder"].action_value == expected
        assert not after.global_flags.get("turn_action_delay_cost_modifiers")


def test_unknown_operation_and_missing_order_are_blocked():
    rules, state, callback, task, rule = _case()
    for operation in (None, "Multiply", []):
        raw = {**task.task_payload, "ModifyFunction": operation}
        status, _ = _equipment_task_admission(callback.event, task.opcode, raw, modifier_name=callback.modifier_name)
        assert status == "blocked"
        result = StatusCallbackSystem(rules)._execute_current_skill_delay_cost_task(
            state, callback, replace(task, task_payload=raw), {}, None,
        )
        assert not result.ok and not result.mutations and result.after_state == state
    result = _apply(rules, state, callback, task, "Set", "event:1")
    registry = result.after_state.global_flags["turn_action_delay_cost_modifiers"]
    invalid = {key: {k: v for k, v in row.items() if k != "operation_index"} for key, row in registry.items()}
    candidate = replace(result.after_state, global_flags={**result.after_state.global_flags,
        "turn_action_delay_cost_modifiers": invalid})
    finished = TimelineSystem().end_turn(candidate, "holder", rule)
    assert not finished.plan.ok and not finished.mutations


def test_extra_turn_does_not_consume_ordinary_cost():
    rules, state, callback, task, rule = _case()
    candidate = _apply(rules, state, callback, task, "Set", "event:1").after_state
    finished = TimelineSystem().end_turn(candidate, "holder", rule, turn_kind="extra_turn")
    assert finished.plan.ok
    after = MutationReducer().apply_all(candidate, finished.mutations)
    assert after.units["holder"].action_value == 17
    assert after.global_flags["turn_action_delay_cost_modifiers"] == candidate.global_flags["turn_action_delay_cost_modifiers"]


if __name__ == "__main__":
    test_set_and_add_keep_distinct_costs_and_committed_order()
    test_unknown_operation_and_missing_order_are_blocked()
    test_extra_turn_does_not_consume_ordinary_cost()
    print("3 current skill delay cost checks passed")
