"""Camera follow/reset stay source-audited presentation without combat work."""
import json
from pathlib import Path
from types import SimpleNamespace

from hsr.simulator_v8_clean_core.tbgd.character_ability_scope import character_ability_semantic_kind
from hsr.simulator_v8_clean_core.tbgd.coverage import ability_task_execution_mode
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering, _process_only_ability_task_source_blocked_reason,
    _status_callback_task_admission,
)


def test_real_camera_follow_and_reset_use_generic_presentation_contract():
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    path = "Config/ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json"
    abilities = json.loads((root / path).read_text())["AbilityList"]
    rows = [(ability_index, ability, index, child_index, child)
            for ability_index, ability in enumerate(abilities)
            for index, task in enumerate(ability["OnStart"])
            for child_index, child in enumerate(task.get("FailedTaskList", []))
            if child.get("$type") == "RPG.GameCore.SetCameraRootFollow"]
    assert len(rows) == 2
    assert character_ability_semantic_kind("SetCameraRootFollow") == "presentation_only"
    lowering = TBGDLowering(root)
    for ability_index, ability, index, child_index, raw in rows:
        task_path = f"OnStart[{index}].FailedTaskList[{child_index}]"
        result = lowering._lower_ability_task_tree(
            raw, definition=SimpleNamespace(action_id="check:camera", level=1),
            phase_id="check:phase", ability_name=ability["Name"], ability_path=path,
            ability_index=ability_index, callback_kind="OnStart", task_index=child_index,
            task_path=task_path, branch="failed", parent_task_id="",
        )
        task, = result.ability_tasks
        effect = next(effect for effect in result.effects if effect.effect_id == task.effect_id)
        assert task.execution_mode == "process_only" and task.coverage_status == "audit_only"
        assert not task.blocked_reason and effect.coverage_status == "audit_only"
        assert effect.source == task.source and task.source.source_path == path
        assert effect.payload["process_only_contract"]["source_shape_status"] == "admitted"
        assert _process_only_ability_task_source_blocked_reason(
            {**raw, "TaskList": [{"$type": "RPG.GameCore.AddModifier"}]}, "SetCameraRootFollow")
        assert _process_only_ability_task_source_blocked_reason(
            {**raw, "TargetType": {"$type": "RPG.GameCore.UnknownTarget"}}, "SetCameraRootFollow")
    assert _process_only_ability_task_source_blocked_reason(
        {"$type": "RPG.GameCore.SetCameraRootFollow"}, "SetCameraRootFollow")


def test_mixed_shield_callbacks_share_the_ability_presentation_taxonomy():
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    path = root / "Config/ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json"
    lowered = TBGDLowering(root)._lower_ability_file(path, {}, ability_file_order=0)
    visuals = [task for task in lowered.status_callback_tasks
               if task.opcode in {"ModifierOverrideOnHitEffect", "StackStatusDesc"}]
    assert {task.opcode for task in visuals} == {"ModifierOverrideOnHitEffect", "StackStatusDesc"}
    for task in visuals:
        assert task.blocked_reason == "source_proven_presentation_only"
        effect = next(effect for effect in lowered.effects if effect.effect_id == task.effect_id)
        assert effect.coverage_status == "audit_only"
        assert effect.payload["process_only_contract"]["source_shape_status"] == "admitted"
        assert ability_task_execution_mode(task.opcode) == "process_only"
    for task in (task for task in lowered.status_callback_tasks if task.opcode == "SetResilience"):
        assert task.coverage_status == "executable"
        callback = next(callback for callback in lowered.status_callbacks if callback.callback_id == task.callback_id)
        assert callback.coverage_status == "executable"
    raw = {"$type": "RPG.GameCore.ModifierOverrideOnHitEffect", "EffectPath": "visual.prefab"}
    for child in ("AddModifier", "UnknownTask"):
        unsafe = {**raw, "OnFinish": [{"$type": f"RPG.GameCore.{child}"}]}
        assert _status_callback_task_admission("OnCreate", "ModifierOverrideOnHitEffect", unsafe)[1] == "presentation_task_has_gameplay_or_unknown_child"
