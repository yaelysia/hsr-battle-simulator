"""A source-status control gate covers its attached skill restriction only."""
import json
from dataclasses import replace
from pathlib import Path

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.status import StatusInstance, status_control_gate_for_actor
from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering, _status_callback_task_admission


def test_actual_attached_skill_disable_uses_current_source_control_lifetime():
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    path = root / "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json"
    raw = json.loads(path.read_text())["ModifierMap"]
    lowered = TBGDLowering(root)._lower_ability_file(path, {}, ability_file_order=0)
    rules = RuleBook(CanonicalIR("attached-skill-disable-check",
        status_callbacks=tuple(lowered.status_callbacks), status_callback_tasks=tuple(lowered.status_callback_tasks),
        effects=tuple(lowered.effects), target_expressions=tuple(lowered.target_expressions)))
    system = StatusCallbackSystem(rules)
    for modifier in ("MCommon_Element_Confine", "MCommon_Element_Entangle"):
        task = next(task for task in lowered.status_callback_tasks
                    if task.modifier_name == modifier and task.opcode == "AttachSkillTypeDisable")
        callback = next(row for row in lowered.status_callbacks if row.callback_id == task.callback_id)
        assert task.coverage_status == "executable" and rules.effect(task.effect_id).coverage_status == "executable"
        detail = StatusInstance("current", f"modifier:{modifier}", modifier, "holder", "break", "caster",
            remaining_duration=1, life_step_moment=raw[modifier]["LifeStepMoment"],
            behavior_flags=tuple(raw[modifier]["BehaviorFlagList"]), status_category="control").to_json()
        unit = UnitState("holder", "enemy", "fixture:holder", hp=100, max_hp=100,
                         statuses=(detail["status_id"],), flags={"status_details": [detail]})
        state = BattleState(units={"holder": unit})
        result = system._execute_task(state, callback, task, detail, None, {task.task_id: task}, None)
        assert result.ok and len(result.mutations) == 1
        restricted = result.after_state.units["holder"]
        assert restricted.flags["status_details"][0]["disabled_skill_types"] == ["Ultra"]
        assert result.records[0]["record_type"] == "status_skill_type_disable"
        from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
        audit = RuntimeSourceAuditor(rules).validate_execution(result.mutations, result.records)
        assert audit.ok, audit.to_json()
        mutation = result.mutations[0]
        forged = replace(mutation, after=[{**mutation.after[0], "disabled_skill_types": ["Skill", "Ultra"]}], mutation_id="")
        reassociated = tuple({**record, "mutation_id": forged.stable_id()} for record in result.records)
        assert not RuntimeSourceAuditor(rules).validate_execution((forged,), reassociated).ok
        repeated = system._execute_task(result.after_state, callback, task, detail, None, {task.task_id: task}, None)
        assert repeated.ok and not repeated.mutations and repeated.after_state == result.after_state
        # Another live control must not cover a removed source's attachment.
        other = {**detail, "instance_id": "other"}
        removed = replace(state, units={"holder": replace(unit, flags={"status_details": [other]})})
        denied = system._execute_task(removed, callback, task, detail, None, {task.task_id: task}, None)
        assert not denied.ok and not denied.mutations
        cleared = replace(restricted, statuses=(), flags={"status_details": []})
        assert status_control_gate_for_actor(cleared) is None
    source_task = next(task for cb in raw[modifier]["_CallbackList"] for task in cb["CallbackConfig"]
                       if task.get("$type") == "RPG.GameCore.AttachSkillTypeDisable")
    assert _status_callback_task_admission("OnStack", "AttachSkillTypeDisable", {**source_task, "LifeTime": 99})[0] == "blocked"
