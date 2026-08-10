from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from ..core.model import ActionCommand, BattleState, BattleTransition, JSONValue
from ..rules.rulebook import RuleBook
from .action_availability import ActionAvailabilitySystem, ActionAvailabilityView, ActionChoice
from .action_selection import ActionTargetSelectionContext
from .phase_machine import TURN_END, CombatPhaseMachine
from .scheduler import (
    CombatScheduler,
    SchedulerStepResult,
    _issue_decision_submission_authorization,
)


DECISION_CONTRACT_SCHEMA_VERSION = "p7_s8_decision_contract_v1"
DECISION_TOKEN_SCHEMA_VERSION = "p7_s8_decision_token_v1"
_EXTERNAL_DECISION_MODES = {"external_selectable", "queued_selectable", "timeline_actor_selectable"}


@dataclass(frozen=True)
class DecisionToken:
    schema_version: str
    decision_id: str
    state_revision: str
    choice_revision: str
    mode: str
    actor_id: str
    current_window: str

    def __post_init__(self) -> None:
        if type(self) is not DecisionToken:
            raise TypeError("decision token must not be subclassed")
        if self.schema_version != DECISION_TOKEN_SCHEMA_VERSION:
            raise ValueError("decision token schema is invalid")
        checks = {
            "decision_id": (self.decision_id, "decision:"),
            "state_revision": (self.state_revision, "state:"),
            "choice_revision": (self.choice_revision, "choices:"),
        }
        for label, (value, prefix) in checks.items():
            if not isinstance(value, str) or not value.startswith(prefix):
                raise ValueError(f"decision token {label} is invalid")
        if not all(isinstance(value, str) and value for value in (self.mode, self.current_window)):
            raise ValueError("decision token context is incomplete")
        if not isinstance(self.actor_id, str) or (
            not self.actor_id and self.mode != "timeline_actor_selectable"
        ):
            raise ValueError("decision token actor context is invalid")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "state_revision": self.state_revision,
            "choice_revision": self.choice_revision,
            "mode": self.mode,
            "actor_id": self.actor_id,
            "current_window": self.current_window,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, JSONValue]) -> "DecisionToken":
        expected = {
            "schema_version",
            "decision_id",
            "state_revision",
            "choice_revision",
            "mode",
            "actor_id",
            "current_window",
        }
        if set(value) != expected:
            raise ValueError("decision token fields are invalid")
        if any(not isinstance(value[key], str) for key in expected):
            raise TypeError("decision token fields must be strings")
        return cls(
            schema_version=value["schema_version"],  # type: ignore[arg-type]
            decision_id=value["decision_id"],  # type: ignore[arg-type]
            state_revision=value["state_revision"],  # type: ignore[arg-type]
            choice_revision=value["choice_revision"],  # type: ignore[arg-type]
            mode=value["mode"],  # type: ignore[arg-type]
            actor_id=value["actor_id"],  # type: ignore[arg-type]
            current_window=value["current_window"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class CurrentDecision:
    ready: bool
    availability: ActionAvailabilityView
    token: DecisionToken | None = None
    blocked_reason: str = ""
    combat_phase: str = ""
    allowed_next_phases: tuple[str, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "schema_version": DECISION_CONTRACT_SCHEMA_VERSION,
            "ready": self.ready,
            "token": self.token.to_json() if self.token is not None else None,
            "blocked_reason": self.blocked_reason,
            "combat_phase": self.combat_phase,
            "allowed_next_phases": list(self.allowed_next_phases),
            "availability": self.availability.to_json(),
        }


@dataclass(frozen=True)
class DecisionAdvanceResult:
    after_state: BattleState
    decision: CurrentDecision
    transitions: tuple[BattleTransition, ...] = ()
    blocked_reason: str = ""
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "schema_version": DECISION_CONTRACT_SCHEMA_VERSION,
            "decision": self.decision.to_json(),
            "transition_count": len(self.transitions),
            "transition_outcomes": [transition.outcome.to_json() for transition in self.transitions],
            "blocked_reason": self.blocked_reason,
            "metadata": self.metadata,
        }


class DecisionSystem:
    """Single query/submit boundary for both ally and enemy decisions."""

    def __init__(self, rules: RuleBook):
        self.rules = rules
        self.availability = ActionAvailabilitySystem(rules)
        self.action_targets = self.availability.action_targets
        self.scheduler = CombatScheduler(rules)
        self.phases = CombatPhaseMachine()

    def current_decision(self, state: BattleState) -> CurrentDecision:
        availability = self.availability.view(state)
        combat_phase = self.phases.current_phase(state)
        allowed_next_phases = self.phases.allowed_next_phases(state)
        phase_operation = (
            "query_timeline_actor_choice"
            if availability.mode == "timeline_actor_selectable"
            else "query_decision"
        )
        phase_reason = self.phases.operation_blocked_reason(state, phase_operation)
        if phase_reason:
            return CurrentDecision(
                ready=False,
                availability=availability,
                blocked_reason=phase_reason,
                combat_phase=combat_phase,
                allowed_next_phases=allowed_next_phases,
            )
        if availability.mode not in _EXTERNAL_DECISION_MODES:
            return CurrentDecision(
                ready=False,
                availability=availability,
                blocked_reason=availability.ordinary_input_blocked_reason,
                combat_phase=combat_phase,
                allowed_next_phases=allowed_next_phases,
            )
        ambiguous_identity = _ambiguous_choice_identity(availability.choices)
        if ambiguous_identity is not None:
            return CurrentDecision(
                ready=False,
                availability=availability,
                blocked_reason=(
                    "decision_choice_identity_ambiguous:"
                    + ":".join(str(item) for item in ambiguous_identity)
                ),
                combat_phase=combat_phase,
                allowed_next_phases=allowed_next_phases,
            )
        choice_revision = _choice_revision(availability)
        state_revision = _state_revision(state)
        actor_id = availability.turn_owner_id or _single_choice_actor_id(availability.choices)
        identity = {
            "schema_version": DECISION_TOKEN_SCHEMA_VERSION,
            "state_revision": state_revision,
            "choice_revision": choice_revision,
            "mode": availability.mode,
            "actor_id": actor_id,
            "current_window": availability.current_window,
        }
        token = DecisionToken(
            schema_version=DECISION_TOKEN_SCHEMA_VERSION,
            decision_id=_digest("decision", identity),
            state_revision=state_revision,
            choice_revision=choice_revision,
            mode=availability.mode,
            actor_id=actor_id,
            current_window=availability.current_window,
        )
        return CurrentDecision(
            ready=True,
            availability=availability,
            token=token,
            combat_phase=combat_phase,
            allowed_next_phases=allowed_next_phases,
        )

    def advance_to_decision(self, state: BattleState, *, max_internal_steps: int = 64) -> DecisionAdvanceResult:
        current = state
        transitions: list[BattleTransition] = []
        seen_revisions: set[str] = set()
        for step_index in range(max_internal_steps + 1):
            decision = self.current_decision(current)
            requires_internal_step = (
                decision.availability.requires_scheduler_step
                or decision.combat_phase == TURN_END
            )
            if decision.ready or not requires_internal_step:
                return DecisionAdvanceResult(
                    after_state=current,
                    decision=decision,
                    transitions=tuple(transitions),
                    blocked_reason=decision.blocked_reason if not decision.ready else "",
                    metadata={"internal_step_count": len(transitions)},
                )
            revision = _state_revision(current)
            if revision in seen_revisions:
                return DecisionAdvanceResult(
                    after_state=current,
                    decision=decision,
                    transitions=tuple(transitions),
                    blocked_reason="decision_advance_no_progress",
                    metadata={"internal_step_count": len(transitions), "repeated_state_revision": revision},
                )
            seen_revisions.add(revision)
            if step_index >= max_internal_steps:
                return DecisionAdvanceResult(
                    after_state=current,
                    decision=decision,
                    transitions=tuple(transitions),
                    blocked_reason="decision_advance_step_limit",
                    metadata={"internal_step_count": len(transitions), "max_internal_steps": max_internal_steps},
                )
            step = self.scheduler.step(current)
            transitions.append(step.transition)
            if not step.transition.outcome.successor_eligible:
                blocked_reason = str(step.transition.coverage.get("blocked_reason") or "decision_advance_blocked")
                return DecisionAdvanceResult(
                    after_state=current,
                    decision=self.current_decision(current),
                    transitions=tuple(transitions),
                    blocked_reason=blocked_reason,
                    metadata={"internal_step_count": len(transitions)},
                )
            current = step.after_state
        raise AssertionError("decision advance loop exhausted without returning")

    def submit(
        self,
        state: BattleState,
        token: DecisionToken,
        command: ActionCommand,
    ) -> SchedulerStepResult:
        if type(token) is not DecisionToken:
            return self.scheduler.reject_decision_submission(
                state,
                "decision_token_type_mismatch",
                {"command": _command_payload(command)},
            )
        current = self.current_decision(state)
        if token.schema_version != DECISION_TOKEN_SCHEMA_VERSION:
            return self.scheduler.reject_decision_submission(
                state,
                "decision_token_schema_mismatch",
                {"command": _command_payload(command), "submitted_token": token.to_json()},
            )
        if token.state_revision != _state_revision(state):
            return self.scheduler.reject_decision_submission(
                state,
                "stale_decision_token",
                {
                    "command": _command_payload(command),
                    "submitted_token": token.to_json(),
                    "current_state_revision": _state_revision(state),
                },
            )
        if not current.ready or current.token is None:
            return self.scheduler.reject_decision_submission(
                state,
                "decision_not_ready",
                {"command": _command_payload(command), "current_decision": current.to_json()},
            )
        if token != current.token:
            return self.scheduler.reject_decision_submission(
                state,
                "stale_decision_token",
                {
                    "command": _command_payload(command),
                    "submitted_token": token.to_json(),
                    "current_token": current.token.to_json(),
                },
            )
        choice, choice_reason = _matching_choice(
            current.availability.choices,
            command,
        )
        if choice is None:
            return self.scheduler.reject_decision_submission(
                state,
                choice_reason,
                {
                    "command": _command_payload(command),
                    "decision_id": token.decision_id,
                    "choice_ids": [choice.choice_id for choice in current.availability.choices],
                },
            )
        canonical_command, envelope_reason = _canonical_command_for_choice(
            choice,
            command,
        )
        if canonical_command is None:
            return self.scheduler.reject_decision_submission(
                state,
                envelope_reason or "decision_command_envelope_blocked",
                {
                    "command": _command_payload(command),
                    "choice_id": choice.choice_id,
                },
            )
        selection_context: ActionTargetSelectionContext | None = None
        if choice.choice_kind != "timeline_actor":
            if choice.target_query is None:
                return self.scheduler.reject_decision_submission(
                    state,
                    "action_target_query_missing",
                    {"command": _command_payload(command), "choice_id": choice.choice_id},
                )
            target_decision = self.action_targets.accept(
                state,
                choice.target_query,
                canonical_command.target_ids,
            )
            if not target_decision.accepted or target_decision.context is None:
                return self.scheduler.reject_decision_submission(
                    state,
                    target_decision.blocked_reason or "action_target_selection_blocked",
                    {
                        "command": _command_payload(canonical_command),
                        "choice_id": choice.choice_id,
                        "target_decision": target_decision.to_json(),
                    },
                )
            selection_context = target_decision.context
        authorization = _issue_decision_submission_authorization(
            decision_id=token.decision_id,
            state_revision=token.state_revision,
            actor_id=canonical_command.actor_id,
            action_id=canonical_command.action_id,
            action_level=canonical_command.action_level,
            selection_context=selection_context,
        )
        return self.scheduler.step(
            state,
            canonical_command,
            decision_authorization=authorization,
        )


def _matching_choice(
    choices: tuple[ActionChoice, ...],
    command: ActionCommand,
) -> tuple[ActionChoice | None, str]:
    matches = tuple(
        choice
        for choice in choices
        if (
            choice.actor_id == command.actor_id
            and choice.action_id == command.action_id
            and choice.action_level == command.action_level
        )
    )
    if not matches:
        return None, "command_not_in_decision_choices"
    if len(matches) != 1:
        return None, "decision_choice_identity_ambiguous"
    return matches[0], ""


def _ambiguous_choice_identity(
    choices: tuple[ActionChoice, ...],
) -> tuple[str, str, int] | None:
    seen: set[tuple[str, str, int]] = set()
    for choice in choices:
        identity = (choice.actor_id, choice.action_id, choice.action_level)
        if identity in seen:
            return identity
        seen.add(identity)
    return None


_DECISION_ENVELOPE_METADATA = frozenset(
    {
        "action_choice_source",
        "effective_action_level",
        "effective_action_level_bonus",
        "effective_action_level_source",
        "enemy_action_candidate",
        "parent_queue_entry_id",
        "queue_entry_id",
        "queue_intent_id",
        "queue_parent",
        "queue_resolution_id",
        "queue_window_plan",
        "requested_action_level",
        "scheduler_parent",
        "selection_controller",
        "timeline_choice_id",
    }
)


def _canonical_command_for_choice(
    choice: ActionChoice,
    submitted: ActionCommand,
) -> tuple[ActionCommand | None, str]:
    template = choice.command_template
    template_metadata = template.get("metadata")
    if not isinstance(template_metadata, Mapping):
        return None, "decision_choice_command_metadata_invalid"
    injected = tuple(
        sorted(
            key
            for key in _DECISION_ENVELOPE_METADATA
            if key in submitted.metadata
            and submitted.metadata.get(key) != template_metadata.get(key)
        )
    )
    if injected:
        return None, "decision_command_envelope_metadata_mismatch:" + ",".join(injected)
    external_metadata = {
        key: value
        for key, value in submitted.metadata.items()
        if key not in _DECISION_ENVELOPE_METADATA and key not in template_metadata
    }
    source = template.get("source")
    queue_name = template.get("queue_name")
    if source not in {"manual", "ai", "queue", "system"}:
        return None, "decision_choice_command_source_invalid"
    if queue_name is not None and (
        not isinstance(queue_name, str) or not queue_name
    ):
        return None, "decision_choice_command_queue_invalid"
    return (
        ActionCommand(
            actor_id=choice.actor_id,
            action_id=choice.action_id,
            action_level=choice.action_level,
            target_ids=submitted.target_ids,
            source=source,  # type: ignore[arg-type]
            queue_name=queue_name,
            metadata={**external_metadata, **dict(template_metadata)},
        ),
        "",
    )


def _choice_revision(availability: ActionAvailabilityView) -> str:
    payload = {
        "mode": availability.mode,
        "current_window": availability.current_window,
        "turn_owner_id": availability.turn_owner_id,
        "choices": [
            {
                "choice_id": choice.choice_id,
                "choice_kind": choice.choice_kind,
                "control": choice.control,
                "actor_id": choice.actor_id,
                "actor_side": choice.actor_side,
                "action_id": choice.action_id,
                "action_level": choice.action_level,
                "admission_id": choice.admission_id,
                "target_query_fingerprint": (
                    choice.target_query.query_fingerprint
                    if choice.target_query is not None
                    else ""
                ),
                "resource_status": choice.resource_status,
            }
            for choice in availability.choices
        ],
        "selectable_windows": [window.to_json() for window in availability.selectable_windows],
    }
    return _digest("choices", payload)


def _state_revision(state: BattleState) -> str:
    return _digest("state", state.snapshot().to_json())


def _single_choice_actor_id(choices: tuple[ActionChoice, ...]) -> str:
    actor_ids = {choice.actor_id for choice in choices if choice.actor_id}
    return next(iter(actor_ids)) if len(actor_ids) == 1 else ""


def _digest(prefix: str, value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def _command_payload(command: ActionCommand) -> dict[str, JSONValue]:
    return {
        "actor_id": command.actor_id,
        "action_id": command.action_id,
        "action_level": command.action_level,
        "target_ids": list(command.target_ids),
        "source": command.source,
        "queue_name": command.queue_name,
        "metadata": command.metadata,
    }
