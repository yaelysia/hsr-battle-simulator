from __future__ import annotations

from ..core.model import ActionCommand, BattleState, GameEvent, JSONValue
from ..rules.ir import ActionDefinitionIR


def condition_skill_type(action_definition: ActionDefinitionIR) -> str:
    text = (
        f"{action_definition.attack_type} "
        f"{action_definition.skill_effect}"
    ).lower()
    if any(token in text for token in ("ultra", "ultimate")):
        return "Ultra"
    if any(token in text for token in ("bpskill", "skill")):
        return "Skill"
    return "Normal"


def damage_listener_window_event(
    state: BattleState,
    command: ActionCommand,
    action_definition: ActionDefinitionIR,
    *,
    event_type: str,
    target_id: str,
    selected_target_ids: tuple[str, ...],
    primary_target_id: str | None,
    source_trace: dict[str, JSONValue],
    is_critical: bool | None = None,
    final_damage: float | None = None,
    damage_custom_name: str = "",
    damage_tags: tuple[str, ...] = (),
    sequence_id: str = "",
) -> GameEvent:
    event_token = event_type.replace(".", "_")
    sequence_token = f":{sequence_id}" if sequence_id else ""
    return GameEvent(
        event_type=event_type,
        source_id=command.actor_id,
        target_id=target_id,
        event_id=(
            f"event:{state.event_index}:{event_token}:"
            f"{command.actor_id}:{target_id}{sequence_token}"
        ),
        window=event_type,
        process_only=True,
        payload={
            "action_id": command.action_id,
            "action_level": command.action_level,
            "actor_id": command.actor_id,
            "attacker_id": command.actor_id,
            "damage_attacker_id": command.actor_id,
            "param_entity_id": target_id,
            "primary_target_id": primary_target_id or target_id,
            "primary_action_target_id": primary_target_id or target_id,
            "current_hit_target_id": target_id,
            "target_id": target_id,
            "selected_target_ids": list(selected_target_ids),
            "target_ids": list(selected_target_ids),
            "attack_type": action_definition.attack_type,
            "skill_type": condition_skill_type(action_definition),
            "SkillType": condition_skill_type(action_definition),
            "skill_effect": action_definition.skill_effect,
            "is_current_skill_active": True,
            "is_insert_action": command.source == "queue",
            "is_critical": is_critical,
            "amount": final_damage,
            "final_damage": final_damage,
            "damage_custom_name": damage_custom_name,
            "damage_tags": list(damage_tags),
            "damage_sequence_source_task_id": sequence_id,
            "source_trace": source_trace,
        },
    )
