"""Real DOT callbacks sample the living status caster at each callback."""
from dataclasses import replace
import json
from pathlib import Path

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.ir_types import IRSource
from hsr.simulator_v8_clean_core.systems.dynamic_values import (
    DynamicValueExecutionRequest, plan_dynamic_value_operation,
)
from hsr.simulator_v8_clean_core.tbgd.lowering import lower_character_dynamic_value_operation


def test_real_dot_properties_follow_living_caster_buffs_and_require_source_identity():
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    source_path = "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json"
    modifiers = json.loads((root / source_path).read_text())["ModifierMap"]
    for modifier_name, property_name, expected in (
        ("MCommon_DOT_Tear", "Attack", (100.0, 150.0)),
        ("MCommon_Element_Bleed", "BreakDamageAddedRatio", (0.5, 0.75)),
    ):
        detail = {
            "instance_id": "dot:1", "status_id": "status:dot",
            "modifier_name": modifier_name, "owner_id": "target",
            "source_id": "ability:source", "caster_id": "caster", "dynamic_values": {},
        }
        caster = UnitState("caster", "enemy", "fixture:caster", attack=100.0,
                           resources={"break_damage_added_ratio": 0.5})
        target = UnitState("target", "ally", "fixture:target", attack=999.0,
                           resources={"break_damage_added_ratio": 9.0},
                           flags={"status_details": [detail]})
        state = BattleState(units={"caster": caster, "target": target})
        for event, expected_value in zip(("OnCreate", "OnPhase1"), expected):
            callback_index, callback = next(
                (index, item) for index, item in enumerate(modifiers[modifier_name]["_CallbackList"])
                if item["Event"] == event
            )
            task_index, task = next(
                (index, item) for index, item in enumerate(callback["CallbackConfig"])
                if item.get("$type") == "RPG.GameCore.SetDynamicValueByProperty"
                and item.get("ReadTargetType", {}).get("Alias") == "SnapshotPropertyEntity"
                and item.get("Value") == property_name
            )
            operation = lower_character_dynamic_value_operation(
                "SetDynamicValueByProperty", task,
                IRSource(source_path, task["$type"],
                         f"ModifierMap.{modifier_name}._CallbackList[{callback_index}].CallbackConfig[{task_index}]"),
                source_modifier_name=modifier_name,
            )
            request = DynamicValueExecutionRequest(
                caster_id="caster", owner_id="target", source_id="ability:source",
                effect_id="effect:property", opcode="SetDynamicValueByProperty",
                status_instance_id="dot:1", status_modifier_name=modifier_name,
                status_id="status:dot", status_source_id="ability:source",
                operation_event_id=event,
            )
            plan = plan_dynamic_value_operation(state, operation, request)
            assert plan.ok, plan.blocked_reason
            assert plan.result_value == expected_value
            assert plan.evaluation["bindings"]["source_unit_id"] == "caster"
            state = MutationReducer().apply_all(state, plan.mutations)
            if event == "OnCreate":
                caster = replace(caster, flags={"status_details": [{
                    "instance_id": "buff:1", "modifiers": [
                        {"bucket": "attribute", "key": "attack_added_ratio", "value": 0.5},
                        {"bucket": "break_bonus", "key": "break_damage_added_ratio", "value": 0.25},
                    ],
                }]})
                state = replace(state, units={**state.units, "caster": caster})

        next_request = replace(request, operation_event_id="next-tick")
        for unavailable in (None, replace(caster, hp=0.0, lifecycle_status="defeated"),
                            replace(caster, lifecycle_status="removed")):
            units = {"target": state.units["target"]}
            if unavailable is not None:
                units["caster"] = unavailable
            missing_state = replace(state, units=units)
            before = missing_state.snapshot().to_json()
            blocked = plan_dynamic_value_operation(missing_state, operation, next_request)
            assert not blocked.ok and not blocked.mutations
            assert blocked.blocked_reason == "snapshot_property_alive_source_unavailable"
            assert missing_state.snapshot().to_json() == before
        forged = plan_dynamic_value_operation(
            state, operation, replace(next_request, caster_id="target"),
        )
        assert not forged.ok and not forged.mutations
        assert forged.blocked_reason == "snapshot_property_status_caster_mismatch"
