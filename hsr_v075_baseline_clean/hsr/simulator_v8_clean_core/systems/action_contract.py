from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from ..core.model import ActionCommand, BattleState, JSONValue
from ..rules.ir import ActionAdmissionIR
from ..rules.rulebook import RuleBook
from .action_preflight import (
    action_binding_blocked_reason,
    action_event_blocked_reason,
    action_resource_blocked_reason,
    action_resource_plan,
    combined_blocked_reason,
)
from .resource import ResourceSystem
from .status import status_control_gate_for_actor
from .unit_lifecycle import UnitLifecycleSystem
from .ability_task_contract import ability_task_runtime_blocked_reason


ACTION_SUBMISSION_CONTRACT_SCHEMA = "p7_s6_action_submission_contract_v1"
_ACTION_AUTHORIZATION_ISSUER = object()


@dataclass(frozen=True)
class _ActionAuthorizationSeal:
    issuer: object = field(repr=False, compare=False)
    claims: tuple[object, ...]


@dataclass(frozen=True)
class ActionSubmissionAuthorization:
    submission_mode: str
    actor_id: str
    owner_entity_ref: str
    action_id: str
    action_level: int
    window: str
    source_id: str
    state_revision: str = ""
    _seal: _ActionAuthorizationSeal | None = field(default=None, repr=False, compare=False)

    def blocked_reason(
        self,
        command: ActionCommand,
        actual_owner_entity_ref: str,
        actual_state_revision: str,
    ) -> str:
        if not _action_authorization_seal_valid(self):
            return "action_submission_authorization_not_issued"
        if self.state_revision != actual_state_revision:
            return "action_submission_authorization_state_mismatch"
        if self.submission_mode not in {"queue", "insert_window", "trigger", "out_of_combat"}:
            return "action_submission_authorization_mode_invalid"
        if self.actor_id != command.actor_id:
            return "action_submission_authorization_actor_mismatch"
        if self.owner_entity_ref != actual_owner_entity_ref:
            return "action_submission_authorization_owner_mismatch"
        if self.action_id != command.action_id or self.action_level != command.action_level:
            return "action_submission_authorization_action_mismatch"
        if not self.window or not self.source_id:
            return "action_submission_authorization_identity_missing"
        return ""


def _issue_action_submission_authorization(
    *,
    state: BattleState,
    submission_mode: str,
    actor_id: str,
    owner_entity_ref: str,
    action_id: str,
    action_level: int,
    window: str,
    source_id: str,
) -> ActionSubmissionAuthorization:
    authorization = ActionSubmissionAuthorization(
        submission_mode=submission_mode,
        actor_id=actor_id,
        owner_entity_ref=owner_entity_ref,
        action_id=action_id,
        action_level=action_level,
        window=window,
        source_id=source_id,
        state_revision=_action_state_revision(state),
    )
    return ActionSubmissionAuthorization(
        **_action_authorization_payload(authorization),
        _seal=_ActionAuthorizationSeal(
            issuer=_ACTION_AUTHORIZATION_ISSUER,
            claims=_action_authorization_claims(authorization),
        ),
    )


def _action_state_revision(state: BattleState) -> str:
    payload = json.dumps(
        state.snapshot().to_json(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"state:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def _action_authorization_payload(
    authorization: ActionSubmissionAuthorization,
) -> dict[str, object]:
    return {
        "submission_mode": authorization.submission_mode,
        "actor_id": authorization.actor_id,
        "owner_entity_ref": authorization.owner_entity_ref,
        "action_id": authorization.action_id,
        "action_level": authorization.action_level,
        "window": authorization.window,
        "source_id": authorization.source_id,
        "state_revision": authorization.state_revision,
    }


def _action_authorization_claims(
    authorization: ActionSubmissionAuthorization,
) -> tuple[object, ...]:
    payload = _action_authorization_payload(authorization)
    return tuple(payload[key] for key in (
        "submission_mode",
        "actor_id",
        "owner_entity_ref",
        "action_id",
        "action_level",
        "window",
        "source_id",
        "state_revision",
    ))


def _action_authorization_seal_valid(authorization: ActionSubmissionAuthorization) -> bool:
    seal = authorization._seal
    return (
        isinstance(seal, _ActionAuthorizationSeal)
        and seal.issuer is _ACTION_AUTHORIZATION_ISSUER
        and seal.claims == _action_authorization_claims(authorization)
    )


@dataclass(frozen=True)
class ActionContractDecision:
    ok: bool
    actor_id: str
    owner_entity_ref: str
    action_id: str
    action_level: int
    submission_mode: str
    current_window: str
    admission: ActionAdmissionIR | None = None
    blocked_reason: str = ""
    resource_status: str = "not_checked"
    resource_blocked_reason: str = ""
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "schema_version": ACTION_SUBMISSION_CONTRACT_SCHEMA,
            "ok": self.ok,
            "actor_id": self.actor_id,
            "owner_entity_ref": self.owner_entity_ref,
            "action_id": self.action_id,
            "action_level": self.action_level,
            "submission_mode": self.submission_mode,
            "current_window": self.current_window,
            "admission": self.admission.to_json() if self.admission is not None else None,
            "blocked_reason": self.blocked_reason,
            "resource_status": self.resource_status,
            "resource_blocked_reason": self.resource_blocked_reason,
            "metadata": self.metadata,
        }


class ActionContractSystem:
    """Shared ownership/role/window/resource gate for query and submission."""

    def __init__(self, rules: RuleBook) -> None:
        self.rules = rules
        self.lifecycle = UnitLifecycleSystem()
        self.resources = ResourceSystem()

    def evaluate(
        self,
        state: BattleState,
        command: ActionCommand,
        *,
        submission_mode: str | None = None,
        authorization: ActionSubmissionAuthorization | None = None,
        queue_resource_policy: dict[str, JSONValue] | None = None,
    ) -> ActionContractDecision:
        actor = state.units.get(command.actor_id)
        owner_entity_ref = actor.template_id if actor is not None else ""
        mode = authorization.submission_mode if authorization is not None else (
            submission_mode or submission_mode_for_command(command)
        )
        current_window = authorization.window if authorization is not None else _current_window(state)
        base = {
            "actor_id": command.actor_id,
            "owner_entity_ref": owner_entity_ref,
            "action_id": command.action_id,
            "action_level": command.action_level,
            "submission_mode": mode,
            "current_window": current_window,
        }
        if actor is None:
            return ActionContractDecision(**base, ok=False, blocked_reason="action_actor_missing")
        if authorization is not None:
            authorization_reason = authorization.blocked_reason(
                command,
                owner_entity_ref,
                _action_state_revision(state),
            )
            if authorization_reason:
                return ActionContractDecision(
                    **base,
                    ok=False,
                    blocked_reason=authorization_reason,
                    metadata={"authorization_source_id": authorization.source_id},
                )
        actor_ok, actor_reason = self.lifecycle.can_act(state, actor.unit_id)
        if not actor_ok:
            return ActionContractDecision(
                **base,
                ok=False,
                blocked_reason=f"action_actor_{actor_reason}",
            )
        control_gate = status_control_gate_for_actor(actor)
        if control_gate is not None:
            return ActionContractDecision(
                **base,
                ok=False,
                blocked_reason=str(control_gate.get("reason") or "status_control_gate"),
                metadata={"control_gate": control_gate},
            )
        admission, reason = self.rules.action_admission_resolution(
            owner_entity_ref,
            command.action_id,
            command.action_level,
            mode,
        )
        if admission is None:
            return ActionContractDecision(**base, ok=False, blocked_reason=reason)
        if mode == "external_turn":
            turn_owner_id = str(state.global_flags.get("turn_owner_id") or "")
            if turn_owner_id != actor.unit_id:
                return ActionContractDecision(
                    **base,
                    ok=False,
                    admission=admission,
                    blocked_reason="action_actor_not_turn_owner",
                    metadata={"turn_owner_id": turn_owner_id},
                )
            if current_window not in admission.allowed_windows:
                return ActionContractDecision(
                    **base,
                    ok=False,
                    admission=admission,
                    blocked_reason=f"action_window_not_admitted:{current_window}",
                )
        elif mode == "insert_window" and current_window not in admission.allowed_windows:
            return ActionContractDecision(
                **base,
                ok=False,
                admission=admission,
                blocked_reason=f"action_window_not_admitted:{current_window}",
            )
        definition = self.rules.action_definition(command.action_id, command.action_level)
        if definition is None:
            return ActionContractDecision(
                **base,
                ok=False,
                admission=admission,
                blocked_reason="action_definition_missing",
            )
        if admission.resource_gate_kind == "ultimate_energy" and (
            actor.max_energy <= 0 or actor.energy < actor.max_energy
        ):
            return ActionContractDecision(
                **base,
                ok=False,
                admission=admission,
                blocked_reason="ultimate_energy_not_ready",
                resource_status="blocked",
                resource_blocked_reason="ultimate_energy_not_ready",
                metadata={"energy": actor.energy, "max_energy": actor.max_energy},
            )
        resource_result = self.resources.plan_action_resources(
            state,
            actor.unit_id,
            action_resource_plan(
                definition,
                source="action_contract.resource_gate",
                metadata={"admission_id": admission.admission_id},
                queue_resource_policy=queue_resource_policy or {},
            ),
        )
        if not resource_result.ok:
            resource_reason = action_resource_blocked_reason(resource_result.errors)
            return ActionContractDecision(
                **base,
                ok=False,
                admission=admission,
                blocked_reason=resource_reason,
                resource_status="blocked",
                resource_blocked_reason=resource_reason,
            )
        binding_reason = action_binding_blocked_reason(
            self.rules.action_ability_binding(command.action_id, command.action_level)
        )
        event_reason = action_event_blocked_reason(
            self.rules.action_event(command.action_id, command.action_level)
        )
        selected_tasks = self.rules.ability_tasks_for_action(
            command.action_id,
            command.action_level,
        )
        task_reasons = tuple(
            reason
            for task in selected_tasks
            if (reason := ability_task_runtime_blocked_reason(self.rules, task))
        )
        graph_reason = combined_blocked_reason(
            binding_reason,
            event_reason,
            *task_reasons,
        )
        if graph_reason:
            return ActionContractDecision(
                **base,
                ok=False,
                admission=admission,
                blocked_reason=graph_reason,
                resource_status="ok",
                metadata={
                    "selected_task_ids": [task.task_id for task in selected_tasks],
                },
            )
        return ActionContractDecision(
            **base,
            ok=True,
            admission=admission,
            resource_status="ok",
            metadata={
                "action_role": admission.action_role,
                "allowed_windows": list(admission.allowed_windows),
                "submission_modes": list(admission.submission_modes),
            },
        )


def submission_mode_for_command(command: ActionCommand) -> str:
    del command
    return "external_turn"


def _current_window(state: BattleState) -> str:
    return str(state.global_flags.get("current_window") or "idle")
