from __future__ import annotations

from dataclasses import dataclass

from ..core.model import (
    ActionCommand,
    BattleState,
    GameEvent,
    JSONValue,
    TargetResolution,
)
from ..rules.condition_state import (
    TransientConditionOperandRequest,
    TransientConditionOperandResolution,
)
from ..rules.ir import ActionDefinitionIR
from ..rules.rulebook import RuleBook


@dataclass(frozen=True)
class ActionConditionFactProvider:
    invocation_id: str
    action_id: str
    action_level: int
    actor_id: str
    window: str
    source_identity: str = ""
    target_type: str = ""
    dynamic_target: bool | None = None
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        if type(self) is not ActionConditionFactProvider:
            raise TypeError("action condition provider must not be subclassed")
        for value in (
            self.invocation_id,
            self.action_id,
            self.actor_id,
            self.window,
        ):
            if not isinstance(value, str) or not value:
                raise ValueError("action condition provider identity is incomplete")
        if (
            not isinstance(self.action_level, int)
            or isinstance(self.action_level, bool)
            or self.action_level <= 0
        ):
            raise ValueError("action condition provider level is invalid")
        if self.blocked_reason:
            if self.source_identity or self.target_type or self.dynamic_target is not None:
                raise ValueError("blocked action condition provider carries formal facts")
            return
        if (
            not isinstance(self.source_identity, str)
            or not self.source_identity
            or not isinstance(self.target_type, str)
            or not self.target_type
            or type(self.dynamic_target) is not bool
        ):
            raise ValueError("action condition provider facts are incomplete")

    def resolve_transient(
        self,
        request: TransientConditionOperandRequest,
    ) -> TransientConditionOperandResolution:
        if type(request) is not TransientConditionOperandRequest:
            raise TypeError("action condition request must use the exact contract")
        if request.invocation_id != self.invocation_id:
            return TransientConditionOperandResolution.blocked(
                "action_condition_invocation_mismatch",
                fact_kind=request.fact_kind,
                invocation_id=request.invocation_id,
            )
        if request.window != self.window:
            return TransientConditionOperandResolution.blocked(
                "action_condition_window_mismatch",
                fact_kind=request.fact_kind,
                invocation_id=request.invocation_id,
            )
        if self.blocked_reason:
            return TransientConditionOperandResolution.blocked(
                self.blocked_reason,
                fact_kind=request.fact_kind,
                invocation_id=request.invocation_id,
            )
        if request.subject_ids or request.parameters:
            return TransientConditionOperandResolution.blocked(
                "action_condition_request_shape_invalid",
                fact_kind=request.fact_kind,
                invocation_id=request.invocation_id,
            )
        if request.fact_kind == "action.target_type":
            return TransientConditionOperandResolution.resolved(
                "string",
                self.target_type,
                fact_kind=request.fact_kind,
                invocation_id=request.invocation_id,
                window=self.window,
                source_identity=self.source_identity,
            )
        if request.fact_kind == "action.dynamic_target":
            return TransientConditionOperandResolution.resolved(
                "boolean",
                self.dynamic_target,
                fact_kind=request.fact_kind,
                invocation_id=request.invocation_id,
                window=self.window,
                source_identity=self.source_identity,
            )
        return TransientConditionOperandResolution.blocked(
            "transient_fact_producer_not_available",
            fact_kind=request.fact_kind,
            invocation_id=request.invocation_id,
        )


def action_condition_fact_provider(
    rules: RuleBook | None,
    state: BattleState,
    *,
    actor_id: str,
    action_id: str,
    action_level: int,
    invocation_id: str,
    window: str,
) -> ActionConditionFactProvider:
    if not isinstance(invocation_id, str) or not invocation_id:
        raise ValueError("action condition invocation identity is required")

    def blocked(reason: str) -> ActionConditionFactProvider:
        return ActionConditionFactProvider(
            invocation_id=invocation_id,
            action_id=action_id,
            action_level=action_level,
            actor_id=actor_id,
            window=window,
            blocked_reason=reason,
        )

    if type(rules) is not RuleBook:
        return blocked("action_condition_rulebook_missing")
    if actor_id not in state.units:
        return blocked("action_condition_actor_missing")
    definition = rules.action_definition(action_id, action_level)
    if definition is None:
        return blocked("action_condition_definition_missing")
    resolution = rules.action_target_contract(action_id, action_level)
    contract = resolution.value
    if resolution.resolution_status != "resolved" or contract is None:
        return blocked(resolution.blocked_reason or "action_target_contract_unresolved")
    target_components = tuple(
        item
        for item in contract.source_components
        if item.component_kind == "target_type"
        and item.semantic_role == "action_selection"
    )
    if len(target_components) != 1:
        return blocked("action_target_type_source_not_unique")
    target_type = target_components[0].raw_value
    if not target_type or type(contract.dynamic_target) is not bool:
        return blocked("action_target_condition_fact_incomplete")
    return ActionConditionFactProvider(
        invocation_id=invocation_id,
        action_id=action_id,
        action_level=action_level,
        actor_id=actor_id,
        window=window,
        source_identity=contract.contract_id,
        target_type=target_type,
        dynamic_target=contract.dynamic_target,
    )


def admitted_action_condition_fact_provider(
    rules: RuleBook,
    state: BattleState,
    *,
    command: ActionCommand,
    action_definition: ActionDefinitionIR,
    target_resolution: TargetResolution,
    window: str,
) -> ActionConditionFactProvider | None:
    """Project facts only from an already-admitted action invocation.

    Payload dictionaries are deliberately absent from this boundary.  The
    selection-context fingerprint is produced by the action target admission
    path and is the invocation identity carried into condition evaluation.
    """

    if (
        type(command) is not ActionCommand
        or type(action_definition) is not ActionDefinitionIR
        or type(target_resolution) is not TargetResolution
    ):
        raise TypeError("action condition admission requires exact runtime types")
    if command.action_level <= 0 or not isinstance(window, str) or not window:
        return None
    fallback_identity = (
        f"unadmitted:{state.event_index}:{command.actor_id}:"
        f"{command.action_id}:{command.action_level}:{window}"
    )
    selection_identity = target_resolution.metadata.get(
        "selection_context_fingerprint"
    )
    invocation_id = (
        selection_identity
        if isinstance(selection_identity, str) and selection_identity
        else fallback_identity
    )

    def blocked(reason: str) -> ActionConditionFactProvider:
        return ActionConditionFactProvider(
            invocation_id=invocation_id,
            action_id=command.action_id,
            action_level=command.action_level,
            actor_id=command.actor_id,
            window=window,
            blocked_reason=reason,
        )

    admission_identities = {
        key: target_resolution.metadata.get(key)
        for key in (
            "selection_context_fingerprint",
            "selection_fingerprint",
            "query_fingerprint",
            "contract_fingerprint",
        )
    }
    if any(
        not isinstance(value, str) or not value
        for value in admission_identities.values()
    ):
        return blocked("action_condition_admission_identity_missing")
    if (
        target_resolution.source != "action_target_selection_system"
        or not target_resolution.selected
    ):
        return blocked("action_condition_target_resolution_not_admitted")
    if (
        action_definition.action_id != command.action_id
        or action_definition.level != command.action_level
    ):
        return blocked("action_condition_definition_identity_mismatch")
    canonical_definition = rules.action_definition(
        command.action_id,
        command.action_level,
    )
    if canonical_definition != action_definition:
        return blocked("action_condition_definition_not_canonical")
    contract_resolution = rules.action_target_contract(
        command.action_id,
        command.action_level,
    )
    contract = contract_resolution.value
    if contract_resolution.resolution_status != "resolved" or contract is None:
        return blocked(
            contract_resolution.blocked_reason
            or "action_target_contract_unresolved"
        )
    supplied_contract_fingerprint = admission_identities["contract_fingerprint"]
    if supplied_contract_fingerprint != contract.contract_fingerprint:
        return blocked("action_condition_target_contract_mismatch")
    return action_condition_fact_provider(
        rules,
        state,
        actor_id=command.actor_id,
        action_id=command.action_id,
        action_level=command.action_level,
        invocation_id=invocation_id,
        window=window,
    )


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
