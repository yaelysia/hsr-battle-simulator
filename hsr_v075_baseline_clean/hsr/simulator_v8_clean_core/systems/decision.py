from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from ..core.model import ActionCommand, BattleState, BattleTransition, JSONValue
from ..rules.rulebook import RuleBook
from .action_availability import ActionAvailabilitySystem, ActionAvailabilityView, ActionChoice
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
    def from_json(cls, value: dict[str, JSONValue]) -> "DecisionToken":
        return cls(
            schema_version=str(value.get("schema_version") or ""),
            decision_id=str(value.get("decision_id") or ""),
            state_revision=str(value.get("state_revision") or ""),
            choice_revision=str(value.get("choice_revision") or ""),
            mode=str(value.get("mode") or ""),
            actor_id=str(value.get("actor_id") or ""),
            current_window=str(value.get("current_window") or ""),
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
        choice = _matching_choice(current.availability.choices, command)
        if choice is None:
            return self.scheduler.reject_decision_submission(
                state,
                "command_not_in_decision_choices",
                {
                    "command": _command_payload(command),
                    "decision_id": token.decision_id,
                    "choice_ids": [choice.choice_id for choice in current.availability.choices],
                },
            )
        authorization = _issue_decision_submission_authorization(
            decision_id=token.decision_id,
            state_revision=token.state_revision,
            actor_id=command.actor_id,
            action_id=command.action_id,
            action_level=command.action_level,
        )
        return self.scheduler.step(state, command, decision_authorization=authorization)


def _matching_choice(choices: tuple[ActionChoice, ...], command: ActionCommand) -> ActionChoice | None:
    for choice in choices:
        if (
            choice.actor_id == command.actor_id
            and choice.action_id == command.action_id
            and choice.action_level == command.action_level
        ):
            if (
                choice.choice_kind == "timeline_actor"
                and command.metadata.get("timeline_choice_id") != choice.metadata.get("timeline_choice_id")
            ):
                continue
            return choice
    return None


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
                "auto_target_ids": list(choice.auto_target_ids),
                "selectable_target_ids": list(choice.selectable_target_ids),
                "target_policy": choice.target_policy,
                "target_status": choice.target_status,
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
