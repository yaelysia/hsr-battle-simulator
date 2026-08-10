from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace

from ..core.atomic_commit import (
    events_for_atomic_result,
    finalize_selected_execution_graph,
    records_for_atomic_result,
    rng_events_for_atomic_result,
)
from ..core.model import (
    ActionCommand,
    ActionSettlement,
    ActionTransaction,
    BattleState,
    BattleTransition,
    GameEvent,
    JSONValue,
    Mutation,
    RNGEvent,
    TargetResolution,
)
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..core.transition_outcome import ExecutionNodeResult, ExecutionNodeStatus
from ..rules.ir import AbilityPhaseIR, IRSource, QueueResolutionIR
from ..rules.rulebook import RuleBook
from .ability import AbilityTaskSystem
from .action_contract import _issue_action_submission_authorization
from .action_selection import ActionTargetSelectionContext, ActionTargetSelectionSystem
from .effect import EffectRegistry
from .enemy_action import EnemyActionCandidate, EnemyActionSystem
from .event_dispatch import EventDispatchSystem
from .queue import QUEUE_DRAIN_STEP_BUDGET, QUEUE_WINDOW_FAMILY_ORDER, QueueDrainPlan, QueueEntry, QueueSystem
from .phase_machine import (
    ACTION_EXECUTION,
    AWAITING_DECISION,
    IDLE,
    POST_ACTION,
    PRE_ACTION,
    TIMELINE_ADVANCING,
    TURN_BEGIN,
    TURN_END,
    WAVE_TRANSITION,
    ENDED,
    CombatPhaseMachine,
)
from .resource import ResourceSystem
from .status import StatusSystem, status_control_gate_for_actor
from .timeline import TimelineSystem, TurnAdvancePlan, TurnAdvanceResult
from .wave import WaveSystem


_DECISION_AUTHORIZATION_ISSUER = object()
TIMELINE_TIE_CHOICE_ACTION_ID = "timeline:select_tied_actor"


@dataclass(frozen=True)
class _DecisionAuthorizationSeal:
    issuer: object = field(repr=False, compare=False)
    claims: tuple[object, ...]


@dataclass(frozen=True)
class SchedulerStepResult:
    after_state: BattleState
    transition: BattleTransition
    child_transitions: tuple[BattleTransition, ...] = ()


@dataclass(frozen=True)
class DecisionSubmissionAuthorization:
    decision_id: str
    state_revision: str
    actor_id: str
    action_id: str
    action_level: int
    selection_context: ActionTargetSelectionContext | None = None
    _seal: _DecisionAuthorizationSeal | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self) is not DecisionSubmissionAuthorization:
            raise TypeError("decision submission authorization must not be subclassed")
        if not all(
            isinstance(value, str) and value
            for value in (self.decision_id, self.state_revision, self.actor_id, self.action_id)
        ):
            raise ValueError("decision submission authorization identity is incomplete")
        if (
            not isinstance(self.action_level, int)
            or isinstance(self.action_level, bool)
            or self.action_level < 0
        ):
            raise ValueError("decision submission authorization level is invalid")
        if self.selection_context is not None and type(self.selection_context) is not ActionTargetSelectionContext:
            raise TypeError("decision submission authorization selection context has the wrong type")

    def blocked_reason(self, command: ActionCommand, actual_state_revision: str) -> str:
        if not _decision_authorization_seal_valid(self):
            return "decision_submission_authorization_not_issued"
        if not self.decision_id or not self.state_revision:
            return "decision_submission_authorization_identity_missing"
        if self.state_revision != actual_state_revision:
            return "decision_submission_authorization_state_mismatch"
        if self.actor_id != command.actor_id:
            return "decision_submission_authorization_actor_mismatch"
        if self.action_id != command.action_id or self.action_level != command.action_level:
            return "decision_submission_authorization_action_mismatch"
        if command.action_id == TIMELINE_TIE_CHOICE_ACTION_ID:
            if self.selection_context is not None or command.target_ids:
                return "timeline_decision_must_be_targetless"
        elif type(self.selection_context) is not ActionTargetSelectionContext:
            return "decision_target_selection_context_required"
        return ""


def _issue_decision_submission_authorization(
    *,
    decision_id: str,
    state_revision: str,
    actor_id: str,
    action_id: str,
    action_level: int,
    selection_context: ActionTargetSelectionContext | None,
) -> DecisionSubmissionAuthorization:
    authorization = DecisionSubmissionAuthorization(
        decision_id=decision_id,
        state_revision=state_revision,
        actor_id=actor_id,
        action_id=action_id,
        action_level=action_level,
        selection_context=selection_context,
    )
    return DecisionSubmissionAuthorization(
        **_decision_authorization_payload(authorization),
        _seal=_DecisionAuthorizationSeal(
            issuer=_DECISION_AUTHORIZATION_ISSUER,
            claims=_decision_authorization_claims(authorization),
        ),
    )


def _decision_authorization_payload(
    authorization: DecisionSubmissionAuthorization,
) -> dict[str, object]:
    return {
        "decision_id": authorization.decision_id,
        "state_revision": authorization.state_revision,
        "actor_id": authorization.actor_id,
        "action_id": authorization.action_id,
        "action_level": authorization.action_level,
        "selection_context": authorization.selection_context,
    }


def _decision_authorization_claims(
    authorization: DecisionSubmissionAuthorization,
) -> tuple[object, ...]:
    payload = _decision_authorization_payload(authorization)
    identity = tuple(payload[key] for key in (
        "decision_id",
        "state_revision",
        "actor_id",
        "action_id",
        "action_level",
    ))
    context = authorization.selection_context
    return (*identity, context.context_fingerprint if context is not None else "")


def _decision_authorization_seal_valid(authorization: DecisionSubmissionAuthorization) -> bool:
    seal = authorization._seal
    return (
        type(seal) is _DecisionAuthorizationSeal
        and seal.issuer is _DECISION_AUTHORIZATION_ISSUER
        and seal.claims == _decision_authorization_claims(authorization)
    )


def _scheduler_state_revision(state: BattleState) -> str:
    payload = json.dumps(
        state.snapshot().to_json(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"state:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


@dataclass(frozen=True)
class _StatusLifecycleSweep:
    after_state: BattleState
    events: tuple[GameEvent, ...] = ()
    mutations: tuple[Mutation, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    rng_events: tuple = ()


class CombatScheduler:
    """Timeline and queue scheduling boundary.

    The scheduler coordinates timeline/queue decisions. It does not implement
    action mechanics; admitted actions still go through CombatExecutor or the
    standalone ability task runner.
    """

    def __init__(self, rules: RuleBook):
        self.rules = rules
        self.reducer = MutationReducer()
        self.timeline = TimelineSystem()
        self.queue = QueueSystem()
        self.resources = ResourceSystem()
        self.status = StatusSystem(rules)
        self.effects = EffectRegistry(self.status)
        self.enemy_actions = EnemyActionSystem(rules)
        self.action_targets = ActionTargetSelectionSystem(rules)
        self.event_dispatcher = EventDispatchSystem(rules, self.effects, reducer=self.reducer)
        self.ability_tasks = AbilityTaskSystem(
            rules,
            self.effects,
            reducer=self.reducer,
            event_dispatcher=self.event_dispatcher,
        )
        self.wave = WaveSystem(rules)
        self.phases = CombatPhaseMachine()

    def action_availability(self, state: BattleState):
        from .action_availability import ActionAvailabilitySystem

        return ActionAvailabilitySystem(self.rules).view(state)

    def reject_decision_submission(
        self,
        state: BattleState,
        reason: str,
        payload: dict[str, JSONValue],
    ) -> SchedulerStepResult:
        return self._blocked(state, "scheduler:decision_submission", reason, payload)

    def initialize_timeline(
        self,
        state: BattleState,
        *,
        explicit_overrides: tuple[str, ...] = (),
    ) -> SchedulerStepResult:
        rule, rule_blocked_reason = self.rules.select_timeline_rule()
        if rule is None:
            return self._blocked(
                state,
                "timeline:initialize",
                rule_blocked_reason,
                {"engine_rule_kind": "timeline"},
            )
        result = self.timeline.initialize_action_values(
            state,
            rule,
            explicit_overrides=explicit_overrides,
            initialization_phase="scheduler",
        )
        if not result.plan.ok:
            return self._blocked(
                state,
                "timeline:initialize",
                result.plan.blocked_reason
                or "timeline_initialization_blocked",
                {"timeline_plan": result.plan.to_json()},
            )
        after = self.reducer.apply_all(state, result.mutations)
        return SchedulerStepResult(
            after,
            _transition(
                before_state=state,
                after_state=after,
                action_id="timeline:initialize",
                events=result.events,
                mutations=result.mutations,
                records=_mutation_records("timeline_initialize", result.mutations, result.plan),
                node_results=(_scheduler_node("timeline", "timeline:initialize"),),
                coverage={"timeline_rule": rule.to_json()},
            ),
        )

    def enqueue_manual_ultimate(self, state: BattleState, command: ActionCommand) -> SchedulerStepResult:
        actor = state.units.get(command.actor_id)
        if actor is None:
            return self._blocked(state, "queue:manual_ultimate_request", "manual_ultimate_actor_missing", {"command": _command_payload(command)})
        definition = self.rules.action_definition(command.action_id, command.action_level)
        action_event = self.rules.action_event(command.action_id, command.action_level)
        if definition is None:
            return self._blocked(state, "queue:manual_ultimate_request", "manual_ultimate_action_definition_missing", {"command": _command_payload(command)})
        if action_event is None:
            return self._blocked(state, "queue:manual_ultimate_request", "manual_ultimate_action_event_missing", {"command": _command_payload(command)})
        admission, admission_reason = self.rules.action_admission_resolution(
            actor.template_id,
            command.action_id,
            command.action_level,
            "insert_window",
        )
        if admission is None:
            return self._blocked(
                state,
                "queue:manual_ultimate_request",
                f"manual_ultimate_action_not_admitted:{admission_reason}",
                {"command": _command_payload(command), "owner_entity_ref": actor.template_id},
            )
        target_query = self.action_targets.query(
            state,
            command.actor_id,
            command.action_id,
            command.action_level,
        )
        target_decision = self.action_targets.accept(state, target_query, command.target_ids)
        if not target_decision.accepted or target_decision.context is None:
            return self._blocked(
                state,
                "queue:manual_ultimate_request",
                target_decision.blocked_reason or "manual_ultimate_target_selection_blocked",
                {
                    "command": _command_payload(command),
                    "target_decision": target_decision.to_json(),
                },
            )
        target_context = target_decision.context
        ultimate_rule, rule_blocked_reason = self.rules.select_resource_rule("ultimate_energy_cost")
        if ultimate_rule is None:
            return self._blocked(
                state,
                "queue:manual_ultimate_request",
                rule_blocked_reason,
                {"command": _command_payload(command), "engine_rule_kind": "ultimate_energy_cost"},
            )
        if not _is_ultimate_definition(definition.attack_type, definition.skill_effect):
            return self._blocked(
                state,
                "queue:manual_ultimate_request",
                "manual_ultimate_action_not_ultra",
                {"command": _command_payload(command), "definition": definition.to_json()},
            )
        if actor.max_energy <= 0 or actor.energy < actor.max_energy:
            return self._blocked(
                state,
                "queue:manual_ultimate_request",
                "manual_ultimate_energy_not_ready",
                {"actor_id": actor.unit_id, "energy": actor.energy, "max_energy": actor.max_energy, "command": _command_payload(command)},
            )
        target_ids = target_context.accepted.submitted_target_ids
        queue_intent_id = f"manual_ultimate:{command.actor_id}:{command.action_id}:{command.action_level}:{state.event_index}"
        source_trace = {
            "manual_input_source": {
                "source_path": "manual_route_input",
                "raw_type": "ManualUltimateRequest",
                "raw_id": queue_intent_id,
                "evidence": {"command": _command_payload(command)},
            },
            "action_definition_source": definition.source.to_json(),
            "action_event_source": action_event.source.to_json(),
            "action_admission_source": admission.source.to_json(),
        }
        priority_source = {
            "field": "manual_route_input",
            "priority_table": "manual_ultimate",
            "priority_key": "manual_ultimate",
            "priority_value": 0.0,
            "priority_ordering_admitted": True,
            "source_trace": source_trace["manual_input_source"],
        }
        target_resolution = {
            "ok": True,
            "actor_id": command.actor_id,
            "submitted_target_ids": list(target_ids),
            "selected_target_ids": list(target_context.accepted.selected_target_ids),
            "query_fingerprint": target_context.accepted.query_fingerprint,
            "selection_fingerprint": target_context.accepted.selection_fingerprint,
            "selection_context_fingerprint": target_context.context_fingerprint,
            "blocked_reason": "",
            "source_trace": source_trace,
        }
        entry = QueueEntry(
            entry_id=f"queue_entry:{queue_intent_id}:0",
            queue_name="manual_ultimate",
            queue_kind="manual_ultimate",
            queue_intent_id=queue_intent_id,
            actor_id=command.actor_id,
            action_or_ability_ref=command.action_id,
            target_ids=target_ids,
            priority_source=priority_source,
            source_trace=source_trace,
            action_level=command.action_level,
            resource_policy={},
            priority_key="manual_ultimate",
            priority_value=0.0,
            queue_window_id=f"manual_queue_window:ultimate:{queue_intent_id}",
            window_family="ultimate",
            window_policy={
                "window_family": "ultimate",
                "priority_ordering_admitted": True,
                "priority_value": 0.0,
                "source_basis": "manual_route_input",
                "dequeue_before_execute": True,
                "drain_via_scheduler": True,
                "energy_preflight_admitted": True,
                "energy_cost_policy": "set_actor_energy_to_action_spbase_after_admitted_execution",
                "resource_rule_id": ultimate_rule.resource_rule_id,
            },
            target_resolution=target_resolution,
            owner_id=command.actor_id,
            source_id=queue_intent_id,
            expiration_policy={
                "status": "source_gap_blocked",
                "blocked_reason": "manual_ultimate_expiration_policy_source_missing",
            },
            cancel_policy={
                "actor_removed": "blocked_process_only",
                "actor_defeated": "blocked_process_only",
                "target_invalid": "blocked_process_only",
                "retarget": "source_gap_blocked",
            },
            status="pending",
            drain_status="pending_resolution",
        )
        mutation = self.queue.enqueue(
            state,
            "manual_ultimate",
            entry,
            source="queue_system",
            metadata={
                "queue_intent_id": queue_intent_id,
                "queue_window_id": entry.queue_window_id,
                "window_family": entry.window_family,
                "queue_kind": entry.queue_kind,
                "manual_ultimate": True,
                "action_id": command.action_id,
                "action_level": command.action_level,
                "definition_id": definition.definition_id,
                "action_event_id": action_event.action_event_id,
                "priority_key": entry.priority_key,
                "priority_value": entry.priority_value,
                "target_resolution": target_resolution,
                "manual_input_source": source_trace["manual_input_source"],
                "source_trace": source_trace,
            },
        )
        after = self.reducer.apply_all(state, (mutation,))
        records = (
            SettlementRecord(
                record_type="queue_enqueue",
                source="queue_system",
                mutation_id=mutation.stable_id(),
                process_only=False,
                payload={
                    "queue_entry": entry.to_json(),
                    "manual_ultimate": True,
                    "command": _command_payload(command),
                    "drain_candidate": False,
                    "drain_blocked_reason": "manual_ultimate_queue_resolution_not_admitted_yet",
                },
                trace=source_trace,
            ).to_json(),
        )
        transition = _transition(
            before_state=state,
            after_state=after,
            action_id="queue:manual_ultimate_request",
            actor_id=command.actor_id,
            events=(
                GameEvent(
                    "queue.manual_ultimate.requested",
                    source_id=command.actor_id,
                    target_id=target_context.accepted.selected_target_ids[0],
                    event_id=f"event:{state.event_index}:manual_ultimate:{command.actor_id}",
                    window="manual_ultimate",
                    process_only=True,
                    payload={"queue_entry": entry.to_json(), "command": _command_payload(command)},
                ),
            ),
            mutations=(mutation,),
            records=records,
            node_results=(_scheduler_node("queue", "queue:manual_ultimate_request"),),
            coverage={
                "manual_ultimate": True,
                "queue_entry": entry.to_json(),
                "source_trace": source_trace,
            },
        )
        return SchedulerStepResult(after, transition)

    def step(
        self,
        state: BattleState,
        command: ActionCommand | None = None,
        *,
        decision_authorization: DecisionSubmissionAuthorization | None = None,
    ) -> SchedulerStepResult:
        """Run one scheduler step.

        The scheduler owns turn lifecycle ordering only. Queue drain and action
        mechanics stay in their existing systems so source audit continues to
        validate the underlying mutation source instead of a scheduler shortcut.
        """
        if state.global_flags.get("phase") == "ended" or isinstance(state.global_flags.get("battle_outcome"), str):
            return self._blocked(
                state,
                "scheduler:battle_ended",
                "battle_ended",
                {"battle_outcome": str(state.global_flags.get("battle_outcome") or "")},
            )

        if command is not None:
            if decision_authorization is None:
                return self._blocked(
                    state,
                    "scheduler:decision_submission",
                    "decision_token_required",
                    {"command": _command_payload(command)},
                )
            authorization_reason = decision_authorization.blocked_reason(
                command,
                _scheduler_state_revision(state),
            )
            if authorization_reason:
                return self._blocked(
                    state,
                    "scheduler:decision_submission",
                    authorization_reason,
                    {
                        "command": _command_payload(command),
                        "decision_id": decision_authorization.decision_id,
                        "state_revision": decision_authorization.state_revision,
                    },
                )
            if command.action_id != TIMELINE_TIE_CHOICE_ACTION_ID:
                selection_reason = self.action_targets.context_blocked_reason(
                    state,
                    command,
                    decision_authorization.selection_context,
                )
                if selection_reason:
                    return self._blocked(
                        state,
                        "scheduler:decision_submission",
                        selection_reason,
                        {
                            "command": _command_payload(command),
                            "decision_id": decision_authorization.decision_id,
                        },
                    )

        if command is not None and command.action_id == TIMELINE_TIE_CHOICE_ACTION_ID:
            if str(state.global_flags.get("turn_owner_id") or ""):
                return self._blocked(
                    state,
                    "timeline:tie_choice",
                    "timeline_tie_choice_not_idle",
                    {"command": _command_payload(command)},
                )
            return self.advance_to_next_turn(
                state,
                tie_choice_actor_id=command.actor_id,
                tie_choice_id=str(command.metadata.get("timeline_choice_id") or ""),
                tie_choice_source=(
                    command.metadata.get("source_trace")
                    if isinstance(command.metadata.get("source_trace"), dict)
                    else None
                ),
            )
        timeline_rule, rule_blocked_reason = self.rules.select_timeline_rule()
        if timeline_rule is None:
            return self._blocked(
                state,
                "scheduler:engine_rule",
                rule_blocked_reason,
                {"engine_rule_kind": "timeline"},
            )

        if self.phases.current_phase(state) == TURN_END:
            if command is not None:
                return self._blocked(
                    state,
                    "scheduler:turn_end",
                    "decision_not_active",
                    {"combat_phase": TURN_END, "command": _command_payload(command)},
                )
            return self.end_current_turn(state)

        queue_step = self._try_queue_drain(state, command=command)
        if queue_step is not None:
            return _with_scheduler_record(
                queue_step,
                record_type="scheduler_queue_step",
                payload={"scheduler_step": "queue_drain_priority"},
            )

        pending_turn_end = state.global_flags.get("pending_turn_end")
        if isinstance(pending_turn_end, dict):
            return self._complete_pending_turn_end(state, pending_turn_end)

        wave_step = self._try_wave_transition(state)
        if wave_step is not None:
            return wave_step


        active_actor_id = str(state.global_flags.get("turn_owner_id") or "")
        begin_result: SchedulerStepResult | None = None
        if active_actor_id:
            actor_id = active_actor_id
            decision_state = state
            if command is None:
                return self._blocked(
                    state,
                    "scheduler:decision_required",
                    "external_decision_required",
                    {"actor_id": actor_id},
                )
        else:
            if command is not None:
                return self._blocked(
                    state,
                    "scheduler:decision_submission",
                    "decision_not_active",
                    {
                        "command": _command_payload(command),
                        "decision_id": decision_authorization.decision_id,
                    },
                )
            begin_result = self.advance_to_next_turn(state)
            if begin_result.transition.coverage.get("blocked_reason"):
                return begin_result
            actor_id = begin_result.transition.transaction.command.actor_id
            decision_state = begin_result.after_state
            return _with_scheduler_record(
                begin_result,
                record_type="scheduler_turn_begin_step",
                payload={
                    "scheduler_step": "turn_begin_only",
                    "actor_id": actor_id,
                    "blocking_dependency": "external_decision",
                },
            )

        turn_begin_action_id = "scheduler:existing_decision"
        turn_begin_coverage: dict[str, JSONValue] = {
            "existing_decision": True,
            "actor_id": actor_id,
            "turn_sequence_index": decision_state.global_flags.get("turn_sequence_index", 0),
        }
        turn_begin_records: tuple[dict[str, JSONValue], ...] = ()
        turn_begin_events: tuple[GameEvent, ...] = ()
        turn_begin_mutations: tuple[Mutation, ...] = ()
        turn_begin_children: tuple[BattleTransition, ...] = ()

        if command.actor_id != actor_id:
            return self._blocked(
                state,
                "scheduler:manual_actor_mismatch",
                "manual_command_actor_mismatch",
                {
                    "expected_actor_id": actor_id,
                    "actual_actor_id": command.actor_id,
                    "command": _command_payload(command),
                },
            )

        actor = decision_state.units.get(actor_id)
        enemy_candidate: EnemyActionCandidate | None = None
        if actor is not None and actor.side == "enemy":
            candidate_constraint = self.enemy_actions.candidate_constraint(decision_state, actor_id)
            if candidate_constraint.get("ok") is not True:
                return self._blocked(
                    state,
                    "scheduler:enemy_action_candidate_blocked",
                    str(candidate_constraint.get("blocked_reason") or "enemy_action_candidate_blocked"),
                    {"candidate_constraint": candidate_constraint, "command": _command_payload(command)},
                )
            if candidate_constraint.get("mode") == "fixed_sequence_constraint":
                enemy_candidate = self.enemy_actions.next_candidate(decision_state, actor_id)
                if enemy_candidate.status != "available":
                    return self._blocked(
                        state,
                        "scheduler:enemy_action_candidate_blocked",
                        enemy_candidate.blocked_reason or "enemy_action_candidate_blocked",
                        {"enemy_action_candidate": enemy_candidate.to_json(), "command": _command_payload(command)},
                    )
                if command.action_id != enemy_candidate.action_ref or int(command.action_level) != int(enemy_candidate.action_level):
                    return self._blocked(
                        state,
                        "scheduler:enemy_action_command_mismatch",
                        "enemy_action_command_mismatch",
                        {
                            "enemy_action_candidate": enemy_candidate.to_json(),
                            "command": _command_payload(command),
                        },
                    )
        phase_reason = self.phases.operation_blocked_reason(decision_state, "submit_turn_action")
        if phase_reason:
            return self._blocked(
                state,
                "scheduler:decision_submission",
                phase_reason,
                {"actor_id": actor_id, "combat_phase": self.phases.current_phase(decision_state)},
            )
        phase_execution = self.phases.transition(
            decision_state,
            ACTION_EXECUTION,
            actor_id=actor_id,
            reason="consume external decision and enter action execution",
            metadata=_phase_rule_metadata(timeline_rule, f"decision:{decision_authorization.decision_id}"),
        )
        if not phase_execution.plan.ok:
            return self._blocked(state, "scheduler:decision_submission", phase_execution.plan.blocked_reason, phase_execution.plan.to_json())
        action_state = self.reducer.apply_all(decision_state, phase_execution.mutations)

        from ..core.executor import CombatExecutor

        parent_metadata = {
            "scheduler_parent": {
                "turn_actor_id": actor_id,
                "turn_transition_action_id": turn_begin_action_id,
                "turn_sequence_index": decision_state.global_flags.get("turn_sequence_index", 0),
                "decision_id": decision_authorization.decision_id,
                "state_revision": decision_authorization.state_revision,
                "source": "timeline_scheduler.step",
            }
        }
        control_gate = status_control_gate_for_actor(action_state.units[actor_id])
        if control_gate is not None:
            return self._blocked(
                state,
                "scheduler:status_control_gate",
                str(control_gate.get("reason") or "status_control_gate"),
                {
                    "control_gate": control_gate,
                    "command": _command_payload(command),
                    "turn_begin_candidate": turn_begin_coverage,
                },
            )
        scheduled_command = replace(
            command,
            metadata={**command.metadata, **parent_metadata},
        )
        selection_context = decision_authorization.selection_context
        assert selection_context is not None
        action_authorization = _issue_action_submission_authorization(
            state=action_state,
            submission_mode="external_turn",
            actor_id=scheduled_command.actor_id,
            owner_entity_ref=action_state.units[actor_id].template_id,
            action_id=scheduled_command.action_id,
            action_level=scheduled_command.action_level,
            window=str(action_state.global_flags.get("current_window") or "action_execution"),
            source_id=decision_authorization.decision_id,
            selection_context_fingerprint=selection_context.context_fingerprint,
        )
        after_action, action_transition = CombatExecutor(self.rules).execute(
            scheduled_command,
            action_state,
            submission_authorization=action_authorization,
            target_selection_context=selection_context,
        )
        cursor_mutation = (
            self.enemy_actions.advance_cursor_mutation(after_action, enemy_candidate, scheduled_command, action_transition)
            if enemy_candidate is not None
            else None
        )
        cursor_records = (
            (_enemy_action_cursor_record(cursor_mutation, enemy_candidate, scheduled_command),)
            if cursor_mutation is not None and enemy_candidate is not None
            else ()
        )
        after_action_for_lifecycle = (
            self.reducer.apply_all(after_action, (cursor_mutation,))
            if cursor_mutation is not None
            else after_action
        )
        phase_post_action = self.phases.transition(
            after_action_for_lifecycle,
            POST_ACTION,
            actor_id=actor_id,
            reason="enter post-action settlement phase",
            metadata=_phase_rule_metadata(timeline_rule, f"decision:{decision_authorization.decision_id}"),
        )
        if not phase_post_action.plan.ok:
            return self._blocked(state, "scheduler:post_action_phase", phase_post_action.plan.blocked_reason, phase_post_action.plan.to_json())
        after_post_action = self.reducer.apply_all(after_action_for_lifecycle, phase_post_action.mutations)
        if _has_queue_entries(after_action_for_lifecycle):
            pending_mutation = self._pending_turn_end_mutation(after_post_action, actor_id, action_transition.transaction.command.action_id)
            after_pending = self.reducer.apply_all(after_post_action, (pending_mutation,))
            pending_record = SettlementRecord(
                record_type="scheduler_turn_end_deferred",
                source="timeline_scheduler",
                mutation_id=pending_mutation.stable_id(),
                process_only=False,
                payload={
                    "reason": "queue_entries_pending_after_action",
                    "actor_id": actor_id,
                    "child_action_id": action_transition.transaction.command.action_id,
                    "pending_turn_end": pending_mutation.after,
                },
                trace=pending_mutation.metadata.get("source_trace") if isinstance(pending_mutation.metadata.get("source_trace"), dict) else {},
            ).to_json()
            combined = _combine_scheduler_transitions(
                before_state=state,
                after_state=after_pending,
                actor_id=actor_id,
                records=(
                    *_scheduler_process_records(
                        "scheduler_action_step",
                        {
                            "scheduler_step": "manual_action_turn_lifecycle_deferred_for_queue",
                            "turn_begin_action_id": turn_begin_action_id,
                            "child_action_id": action_transition.transaction.command.action_id,
                        "turn_end": "deferred_until_pending_queue_drained",
                        "enemy_action_candidate": enemy_candidate.to_json() if enemy_candidate is not None else {},
                        "enemy_action_cursor_advanced": cursor_mutation is not None,
                    },
                ),
                *turn_begin_records,
                *phase_execution.records,
                *(action_transition.transaction.settlement.records if action_transition.transaction.settlement else ()),
                *cursor_records,
                *phase_post_action.records,
                pending_record,
            ),
                events=(
                    *turn_begin_events,
                    *phase_execution.events,
                    GameEvent(
                        "scheduler.action.before",
                        source_id=actor_id,
                        event_id=f"event:{decision_state.event_index}:scheduler_action_before:{actor_id}",
                        window="scheduler",
                        process_only=True,
                        payload={"command": _command_payload(scheduled_command)},
                    ),
                    *action_transition.transaction.events,
                    GameEvent(
                        "scheduler.action.after",
                        source_id=actor_id,
                        event_id=f"event:{after_action.event_index}:scheduler_action_after:{actor_id}",
                        window="scheduler",
                        process_only=True,
                        payload={"command": _command_payload(scheduled_command)},
                    ),
                    *phase_post_action.events,
                    GameEvent(
                        "scheduler.turn_end_deferred",
                        source_id=actor_id,
                        event_id=f"event:{after_action.event_index}:turn_end_deferred:{actor_id}",
                        window="scheduler",
                        process_only=True,
                        payload={"pending_turn_end": pending_mutation.after},
                    ),
                ),
                mutations=(
                    *turn_begin_mutations,
                    *phase_execution.mutations,
                    *action_transition.transaction.mutations,
                    *((cursor_mutation,) if cursor_mutation is not None else ()),
                    *phase_post_action.mutations,
                    pending_mutation,
                ),
                target_resolution=action_transition.target_resolution,
                child_transitions=(*turn_begin_children, action_transition),
                coverage={
                    "scheduler_step": "manual_action_turn_lifecycle_deferred_for_queue",
                    "turn_begin": turn_begin_coverage,
                    "action_child": {
                        "command": _command_payload(scheduled_command),
                        "coverage": action_transition.coverage,
                    },
                    "enemy_action_candidate": enemy_candidate.to_json() if enemy_candidate is not None else {},
                    "enemy_action_sequence_cursor": {
                        "advanced": cursor_mutation is not None,
                        "mutation_id": cursor_mutation.stable_id() if cursor_mutation is not None else "",
                    },
                    "turn_end": {"deferred": True, "reason": "queue_entries_pending_after_action"},
                    "phase_machine": {
                        "from_phase": AWAITING_DECISION,
                        "execution_phase": ACTION_EXECUTION,
                        "after_action_phase": POST_ACTION,
                    },
                    "unsupported_hooks": _unsupported_turn_hooks(),
                },
            )
            return SchedulerStepResult(
                _eligible_scheduler_state(state, after_pending, combined),
                combined,
                child_transitions=(*turn_begin_children, action_transition),
            )
        action_lifecycle = self._apply_status_lifecycle_tick(after_post_action, "ActionPhaseEnd", actor_id=actor_id)
        end_result = self.end_current_turn(action_lifecycle.after_state)
        combined = _combine_scheduler_transitions(
            before_state=state,
            after_state=end_result.after_state,
            actor_id=actor_id,
            records=(
                *_scheduler_process_records(
                    "scheduler_action_step",
                    {
                        "scheduler_step": "manual_action_turn_lifecycle",
                        "turn_begin_action_id": turn_begin_action_id,
                        "child_action_id": action_transition.transaction.command.action_id,
                        "action_lifecycle_hook": "ActionPhaseEnd",
                        "turn_end_action_id": end_result.transition.transaction.command.action_id,
                        "enemy_action_candidate": enemy_candidate.to_json() if enemy_candidate is not None else {},
                        "enemy_action_cursor_advanced": cursor_mutation is not None,
                    },
                ),
                *turn_begin_records,
                *phase_execution.records,
                *(action_transition.transaction.settlement.records if action_transition.transaction.settlement else ()),
                *cursor_records,
                *phase_post_action.records,
                *action_lifecycle.records,
                *(end_result.transition.transaction.settlement.records if end_result.transition.transaction.settlement else ()),
            ),
            events=(
                *turn_begin_events,
                *phase_execution.events,
                GameEvent(
                    "scheduler.action.before",
                    source_id=actor_id,
                    event_id=f"event:{decision_state.event_index}:scheduler_action_before:{actor_id}",
                    window="scheduler",
                    process_only=True,
                    payload={"command": _command_payload(scheduled_command)},
                ),
                *action_transition.transaction.events,
                GameEvent(
                    "scheduler.action.after",
                    source_id=actor_id,
                    event_id=f"event:{after_action.event_index}:scheduler_action_after:{actor_id}",
                    window="scheduler",
                    process_only=True,
                    payload={"command": _command_payload(scheduled_command)},
                ),
                *phase_post_action.events,
                *action_lifecycle.events,
                *end_result.transition.transaction.events,
            ),
            mutations=(
                *turn_begin_mutations,
                *phase_execution.mutations,
                *action_transition.transaction.mutations,
                *((cursor_mutation,) if cursor_mutation is not None else ()),
                *phase_post_action.mutations,
                *action_lifecycle.mutations,
                *end_result.transition.transaction.mutations,
            ),
            target_resolution=action_transition.target_resolution,
            child_transitions=(*turn_begin_children, action_transition, end_result.transition),
            coverage={
                "scheduler_step": "manual_action_turn_lifecycle",
                "turn_begin": turn_begin_coverage,
                "action_child": {
                    "command": _command_payload(scheduled_command),
                    "coverage": action_transition.coverage,
                },
                "enemy_action_candidate": enemy_candidate.to_json() if enemy_candidate is not None else {},
                "enemy_action_sequence_cursor": {
                    "advanced": cursor_mutation is not None,
                    "mutation_id": cursor_mutation.stable_id() if cursor_mutation is not None else "",
                },
                "action_lifecycle": {"life_step_moment": "ActionPhaseEnd", "mutation_count": len(action_lifecycle.mutations)},
                "turn_end": end_result.transition.coverage,
                "phase_machine": {
                    "from_phase": AWAITING_DECISION,
                    "execution_phase": ACTION_EXECUTION,
                    "after_action_phase": POST_ACTION,
                    "final_phase": IDLE,
                },
                "unsupported_hooks": _unsupported_turn_hooks(),
            },
        )
        return SchedulerStepResult(
            _eligible_scheduler_state(state, end_result.after_state, combined),
            combined,
            child_transitions=(*turn_begin_children, action_transition, end_result.transition),
        )

    def advance_to_next_turn(
        self,
        state: BattleState,
        *,
        tie_choice_actor_id: str = "",
        tie_choice_id: str = "",
        tie_choice_source: dict[str, JSONValue] | None = None,
    ) -> SchedulerStepResult:
        queue_step = self._try_queue_drain(state)
        if queue_step is not None:
            return queue_step

        phase_reason = self.phases.operation_blocked_reason(state, "advance_timeline")
        if phase_reason:
            return self._blocked(
                state,
                "timeline:advance",
                phase_reason,
                {"combat_phase": self.phases.current_phase(state)},
            )

        rule, rule_blocked_reason = self.rules.select_timeline_rule()
        if rule is None:
            return self._blocked(
                state,
                "timeline:advance",
                rule_blocked_reason,
                {"engine_rule_kind": "timeline"},
            )
        phase_timeline = self.phases.transition(
            state,
            TIMELINE_ADVANCING,
            reason="advance scheduler to next actor",
            metadata=_phase_rule_metadata(rule, "phase:timeline_advancing"),
        )
        if not phase_timeline.plan.ok:
            return self._blocked(state, "timeline:advance", phase_timeline.plan.blocked_reason, phase_timeline.plan.to_json())
        after_phase_timeline = self.reducer.apply_all(state, phase_timeline.mutations)
        plan = self.timeline.plan_next_actor(
            after_phase_timeline,
            rule,
            tie_choice_actor_id=tie_choice_actor_id,
            tie_choice_id=tie_choice_id,
            tie_choice_source=tie_choice_source,
        )
        if not plan.ok:
            return self._blocked(state, "timeline:advance", plan.blocked_reason, {"turn_advance_plan": plan.to_json()})

        actor = after_phase_timeline.units[plan.actor_id]
        enemy_candidate = None

        advance = self.timeline.advance_to_next_actor(after_phase_timeline, plan)
        after_advance = self.reducer.apply_all(after_phase_timeline, advance.mutations)
        phase_begin = self.phases.transition(
            after_advance,
            TURN_BEGIN,
            actor_id=plan.actor_id,
            reason="enter regular turn begin phase",
            metadata=_phase_rule_metadata(rule, plan.plan_id),
        )
        if not phase_begin.plan.ok:
            return self._blocked(state, "timeline:advance", phase_begin.plan.blocked_reason, phase_begin.plan.to_json())
        after_phase_begin = self.reducer.apply_all(after_advance, phase_begin.mutations)
        begin = self.timeline.begin_turn(after_phase_begin, plan, turn_kind="regular")
        after_begin = self.reducer.apply_all(after_phase_begin, begin.mutations)
        turn_begin_event = GameEvent(
            "turn.begin",
            source_id=plan.actor_id,
            target_id=plan.actor_id,
            event_id=f"event:{after_begin.event_index}:turn_begin_dispatch:{plan.actor_id}",
            window="turn_begin",
            process_only=True,
            payload={
                "actor_id": plan.actor_id,
                "turn_kind": "regular",
                "turn_advance_plan": plan.to_json(),
                "combat_phase": TURN_BEGIN,
            },
        )
        begin_dispatch = self.event_dispatcher.dispatch_event(after_begin, event=turn_begin_event)
        phase_pre_action = self.phases.transition(
            begin_dispatch.after_state,
            PRE_ACTION,
            actor_id=plan.actor_id,
            reason="enter before-action settlement phase",
            metadata=_phase_rule_metadata(rule, plan.plan_id),
        )
        if not phase_pre_action.plan.ok:
            return self._blocked(state, "timeline:advance", phase_pre_action.plan.blocked_reason, phase_pre_action.plan.to_json())
        after_phase_pre_action = self.reducer.apply_all(begin_dispatch.after_state, phase_pre_action.mutations)
        pre_action_lifecycle = self._apply_status_lifecycle_tick(
            after_phase_pre_action,
            "ModifierPhase1End",
            actor_id=plan.actor_id,
        )
        control_gate = status_control_gate_for_actor(pre_action_lifecycle.after_state.units[plan.actor_id])
        if control_gate is not None:
            phase_control_end = self.phases.transition(
                pre_action_lifecycle.after_state,
                TURN_END,
                actor_id=plan.actor_id,
                reason="consume regular turn blocked by structured control status",
                metadata={
                    **_phase_rule_metadata(rule, plan.plan_id),
                    "control_gate": control_gate,
                },
            )
            if not phase_control_end.plan.ok:
                return self._blocked(
                    state,
                    "timeline:control_skip",
                    phase_control_end.plan.blocked_reason,
                    phase_control_end.plan.to_json(),
                )
            after_control_end = self.reducer.apply_all(pre_action_lifecycle.after_state, phase_control_end.mutations)
            control_event = GameEvent(
                "turn.control_skipped",
                source_id=plan.actor_id,
                target_id=plan.actor_id,
                event_id=f"event:{after_control_end.event_index}:turn_control_skipped:{plan.actor_id}",
                window=TURN_END,
                process_only=True,
                payload={"control_gate": control_gate, "turn_advance_plan": plan.to_json()},
            )
            mutations = (
                *phase_timeline.mutations,
                *advance.mutations,
                *phase_begin.mutations,
                *begin.mutations,
                *begin_dispatch.mutations,
                *phase_pre_action.mutations,
                *pre_action_lifecycle.mutations,
                *phase_control_end.mutations,
            )
            events = (
                *phase_timeline.events,
                *advance.events,
                *phase_begin.events,
                *begin.events,
                *begin_dispatch.events,
                *phase_pre_action.events,
                *pre_action_lifecycle.events,
                *phase_control_end.events,
                control_event,
            )
            records = (
                *phase_timeline.records,
                *_mutation_records("timeline_advance", advance.mutations, plan),
                *phase_begin.records,
                *_mutation_records("turn_begin", begin.mutations, plan),
                *begin_dispatch.records,
                *phase_pre_action.records,
                *pre_action_lifecycle.records,
                *phase_control_end.records,
                *_scheduler_process_records(
                    "status_control_turn_skipped",
                    {
                        "actor_id": plan.actor_id,
                        "control_gate": control_gate,
                        "terminal_phase": TURN_END,
                        "next_scheduler_operation": "end_current_turn",
                    },
                ),
            )
            transition = _transition(
                before_state=state,
                after_state=after_control_end,
                action_id="timeline:consume_controlled_turn",
                actor_id=plan.actor_id,
                events=events,
                mutations=mutations,
                records=records,
                node_results=(
                    *begin_dispatch.node_results,
                    _scheduler_node("timeline", "timeline:consume_controlled_turn"),
                ),
                coverage={
                    "turn_advance_plan": plan.to_json(),
                    "timeline_rule": rule.to_json(),
                    "control_skip": {
                        "consumed": True,
                        "control_gate": control_gate,
                        "state": "pending_turn_end",
                    },
                    "phase_machine": {
                        "schema_version": "p7_s9_combat_phase_machine_v1",
                        "path": [IDLE, TIMELINE_ADVANCING, TURN_BEGIN, PRE_ACTION, TURN_END],
                    },
                    "pre_action_lifecycle": {
                        "life_step_moment": "ModifierPhase1End",
                        "mutation_count": len(pre_action_lifecycle.mutations),
                    },
                },
            )
            return SchedulerStepResult(
                _eligible_scheduler_state(state, after_control_end, transition),
                transition,
            )

        if actor.side == "enemy":
            candidate_constraint = self.enemy_actions.candidate_constraint(
                pre_action_lifecycle.after_state,
                actor.unit_id,
            )
            if candidate_constraint.get("ok") is not True:
                return self._blocked(
                    state,
                    "timeline:enemy_action_candidate",
                    str(candidate_constraint.get("blocked_reason") or "enemy_action_candidate_blocked"),
                    {
                        "turn_advance_plan": plan.to_json(),
                        "actor_id": actor.unit_id,
                        "candidate_constraint": candidate_constraint,
                    },
                )
            if candidate_constraint.get("mode") == "fixed_sequence_constraint":
                enemy_candidate = self.enemy_actions.next_candidate(pre_action_lifecycle.after_state, actor.unit_id)
                if enemy_candidate.status != "available":
                    return self._blocked(
                        state,
                        "timeline:enemy_action_candidate",
                        enemy_candidate.blocked_reason or "enemy_action_candidate_blocked",
                        {
                            "turn_advance_plan": plan.to_json(),
                            "actor_id": actor.unit_id,
                            "enemy_action_candidate": enemy_candidate.to_json(),
                        },
                    )
        phase_decision = self.phases.transition(
            pre_action_lifecycle.after_state,
            AWAITING_DECISION,
            actor_id=plan.actor_id,
            reason="open external regular-action decision",
            metadata=_phase_rule_metadata(rule, plan.plan_id),
        )
        if not phase_decision.plan.ok:
            return self._blocked(state, "timeline:advance", phase_decision.plan.blocked_reason, phase_decision.plan.to_json())
        after_phase_decision = self.reducer.apply_all(pre_action_lifecycle.after_state, phase_decision.mutations)
        decision_window = self.timeline.open_decision_window(after_phase_decision, plan)
        after_decision = self.reducer.apply_all(after_phase_decision, decision_window.mutations)
        mutations = (
            *phase_timeline.mutations,
            *advance.mutations,
            *phase_begin.mutations,
            *begin.mutations,
            *begin_dispatch.mutations,
            *phase_pre_action.mutations,
            *pre_action_lifecycle.mutations,
            *phase_decision.mutations,
            *decision_window.mutations,
        )
        events = (
            *phase_timeline.events,
            *advance.events,
            *phase_begin.events,
            *begin.events,
            *begin_dispatch.events,
            *phase_pre_action.events,
            *pre_action_lifecycle.events,
            *phase_decision.events,
            *decision_window.events,
        )
        records = (
            *phase_timeline.records,
            *_mutation_records("timeline_advance", advance.mutations, plan),
            *phase_begin.records,
            *_mutation_records("turn_begin", begin.mutations, plan),
            *begin_dispatch.records,
            *phase_pre_action.records,
            *pre_action_lifecycle.records,
            *phase_decision.records,
            *_mutation_records("turn_decision", decision_window.mutations, plan),
            *(
                _scheduler_process_records(
                    "enemy_action_candidate",
                    {"turn_advance_plan": plan.to_json(), "enemy_action_candidate": enemy_candidate.to_json()},
                )
                if enemy_candidate is not None
                else ()
            ),
        )
        candidate_events = (
            (
                GameEvent(
                    "enemy.action.candidate",
                    source_id=actor.unit_id,
                    event_id=f"event:{after_begin.event_index}:enemy_action_candidate:{actor.unit_id}",
                    window="scheduler",
                    process_only=True,
                    payload={"enemy_action_candidate": enemy_candidate.to_json()},
                ),
            )
            if enemy_candidate is not None
            else ()
        )
        return SchedulerStepResult(
            after_decision,
            _transition(
                before_state=state,
                after_state=after_decision,
                action_id="timeline:advance_to_next_turn",
                actor_id=plan.actor_id,
                events=(*events, *candidate_events),
                mutations=mutations,
                records=records,
                node_results=(
                    *begin_dispatch.node_results,
                    _scheduler_node("timeline", "timeline:advance_to_next_turn"),
                ),
                coverage={
                    "turn_advance_plan": plan.to_json(),
                    "timeline_rule": rule.to_json(),
                    "enemy_action_candidate": enemy_candidate.to_json() if enemy_candidate is not None else {},
                    "phase_machine": {
                        "schema_version": "p7_s9_combat_phase_machine_v1",
                        "path": [IDLE, TIMELINE_ADVANCING, TURN_BEGIN, PRE_ACTION, AWAITING_DECISION],
                    },
                    "pre_action_lifecycle": {
                        "life_step_moment": "ModifierPhase1End",
                        "mutation_count": len(pre_action_lifecycle.mutations),
                    },
                },
            ),
        )

    def end_current_turn(self, state: BattleState) -> SchedulerStepResult:
        active_turn = state.global_flags.get("active_turn")
        actor_id = ""
        if isinstance(active_turn, dict):
            actor_id = str(active_turn.get("actor_id") or "")
        actor_id = actor_id or str(state.global_flags.get("turn_owner_id") or "")
        if not actor_id or actor_id not in state.units:
            return self._blocked(state, "timeline:turn_end", "active_turn_missing", {"active_turn": active_turn})
        rule, rule_blocked_reason = self.rules.select_timeline_rule()
        if rule is None:
            return self._blocked(
                state,
                "timeline:turn_end",
                rule_blocked_reason,
                {"engine_rule_kind": "timeline"},
            )
        already_in_turn_end = self.phases.current_phase(state) == TURN_END
        if already_in_turn_end:
            phase_end_events: tuple[GameEvent, ...] = ()
            phase_end_mutations: tuple[Mutation, ...] = ()
            phase_end_records: tuple[dict[str, JSONValue], ...] = ()
            after_phase_end = state
        else:
            phase_end = self.phases.transition(
                state,
                TURN_END,
                actor_id=actor_id,
                reason="enter regular turn-end settlement phase",
                metadata=_phase_rule_metadata(rule, f"turn_end:{state.event_index}:{actor_id}"),
            )
            if not phase_end.plan.ok:
                return self._blocked(state, "timeline:turn_end", phase_end.plan.blocked_reason, phase_end.plan.to_json())
            phase_end_events = phase_end.events
            phase_end_mutations = phase_end.mutations
            phase_end_records = phase_end.records
            after_phase_end = self.reducer.apply_all(state, phase_end_mutations)
        lifecycle = self._apply_status_lifecycle_tick(after_phase_end, "TurnEnd", actor_id=actor_id)
        turn_end_event = GameEvent(
            "turn.end",
            source_id=actor_id,
            target_id=actor_id,
            event_id=f"event:{lifecycle.after_state.event_index}:turn_end_dispatch:{actor_id}",
            window="turn_end",
            process_only=True,
            payload={
                "actor_id": actor_id,
                "listener_scope": "global_listener",
                "life_step_moment": "TurnEnd",
                "combat_phase": TURN_END,
            },
        )
        dispatch = self.event_dispatcher.dispatch_event(lifecycle.after_state, event=turn_end_event)
        result = self.timeline.end_turn(dispatch.after_state, actor_id, rule, turn_kind="regular")
        after_timeline_end = self.reducer.apply_all(dispatch.after_state, result.mutations)
        phase_idle = self.phases.transition(
            after_timeline_end,
            IDLE,
            actor_id=actor_id,
            reason="close regular turn and return scheduler to idle",
            metadata=_phase_rule_metadata(rule, result.plan.plan_id),
        )
        if not phase_idle.plan.ok:
            return self._blocked(state, "timeline:turn_end", phase_idle.plan.blocked_reason, phase_idle.plan.to_json())
        after = self.reducer.apply_all(after_timeline_end, phase_idle.mutations)
        transition = _transition(
            before_state=state,
            after_state=after,
            action_id="timeline:end_current_turn",
            actor_id=actor_id,
            events=(
                *phase_end_events,
                *lifecycle.events,
                *dispatch.events,
                *result.events,
                *phase_idle.events,
            ),
            mutations=(
                *phase_end_mutations,
                *lifecycle.mutations,
                *dispatch.mutations,
                *result.mutations,
                *phase_idle.mutations,
            ),
            records=(
                *phase_end_records,
                *lifecycle.records,
                *dispatch.records,
                *_mutation_records("turn_end", result.mutations, result.plan),
                *phase_idle.records,
            ),
            node_results=(*dispatch.node_results, _scheduler_node("timeline", "timeline:end_current_turn")),
            coverage={
                "timeline_rule": rule.to_json(),
                "turn_advance_plan": result.plan.to_json(),
                "status_lifecycle": {
                    "life_step_moment": "TurnEnd",
                    "mutation_count": len(lifecycle.mutations),
                },
                "phase_machine": {
                    "schema_version": "p7_s9_combat_phase_machine_v1",
                    "path": ([TURN_END, IDLE] if already_in_turn_end else [POST_ACTION, TURN_END, IDLE]),
                },
            },
        )
        return SchedulerStepResult(_eligible_scheduler_state(state, after, transition), transition)

    def _apply_status_lifecycle_tick(
        self,
        state: BattleState,
        life_step_moment: str,
        *,
        actor_id: str,
    ) -> _StatusLifecycleSweep:
        current = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        records: list[dict[str, JSONValue]] = []
        rng_events: list = []
        for unit_id in (actor_id,):
            if unit_id not in current.units:
                continue
            details = tuple(
                item
                for item in current.units[unit_id].flags.get("status_details", ())
                if isinstance(item, dict)
            )
            for detail in details:
                status_removed_during_phase = False
                for phase_event_name in ("OnPhase1", "OnPhase2"):
                    phase_event = _status_phase_lifecycle_event(
                        current,
                        unit_id,
                        detail,
                        life_step_moment,
                        phase_event_name,
                    )
                    if phase_event is None:
                        continue
                    dispatch = self.event_dispatcher.dispatch_status_callback(
                        current,
                        event=phase_event,
                        unit_id=unit_id,
                        modifier_name=str(detail.get("modifier_name") or ""),
                    )
                    events.extend(dispatch.events)
                    records.extend(dispatch.records)
                    rng_events.extend(dispatch.rng_events)
                    if dispatch.mutations:
                        mutations.extend(dispatch.mutations)
                        current = dispatch.after_state
                    refreshed_detail = _status_detail_by_instance(
                        current,
                        unit_id,
                        str(detail.get("instance_id") or ""),
                    )
                    if refreshed_detail is None:
                        status_removed_during_phase = True
                        break
                    detail = refreshed_detail
                if status_removed_during_phase:
                    continue
                result = self.status.apply_lifecycle_tick(current, unit_id, detail, life_step_moment)
                records.extend(result.records)
                events.extend(result.events)
                if result.mutations:
                    mutations.extend(result.mutations)
                    current = self.reducer.apply_all(current, result.mutations)
                for lifecycle_event in result.events:
                    dispatch = self.event_dispatcher.dispatch_status_callback(
                        current,
                        event=lifecycle_event,
                        unit_id=unit_id,
                        modifier_name=str(detail.get("modifier_name") or ""),
                    )
                    events.extend(dispatch.events)
                    records.extend(dispatch.records)
                    rng_events.extend(dispatch.rng_events)
                    if dispatch.mutations:
                        mutations.extend(dispatch.mutations)
                        current = dispatch.after_state
        event = GameEvent(
            "status.lifecycle.tick",
            source_id=actor_id,
            event_id=f"event:{state.event_index}:status_lifecycle:{life_step_moment}:{actor_id}",
            window=life_step_moment,
            process_only=True,
            payload={
                "life_step_moment": life_step_moment,
                "mutation_count": len(mutations),
                "record_count": len(records),
            },
        )
        events.append(event)
        return _StatusLifecycleSweep(
            after_state=current,
            events=tuple(events),
            mutations=tuple(mutations),
            records=tuple(records),
            rng_events=tuple(rng_events),
        )

    def _try_wave_transition(self, state: BattleState) -> SchedulerStepResult | None:
        plan = self.wave.plan_transition(state)
        if plan.status == "no_change" or plan.blocked_reason == "wave_runtime_not_configured":
            return None
        result = self.wave.apply_transition(state, plan)
        if plan.status == "blocked":
            return SchedulerStepResult(
                state,
                _transition(
                    before_state=state,
                    after_state=state,
                    action_id="wave:transition",
                    actor_id="wave_system",
                    events=result.events,
                    mutations=(),
                    records=result.records,
                    node_results=(
                        _scheduler_node(
                            "wave",
                            "wave:transition",
                            status="blocked",
                            reason=plan.blocked_reason or "wave_transition_blocked",
                        ),
                    ),
                    preflight_blocked=True,
                    preflight_reason=plan.blocked_reason,
                    coverage={"wave_transition": plan.to_json(), "blocked_reason": plan.blocked_reason},
                ),
            )
        phase_enter = self.phases.transition(
            state,
            WAVE_TRANSITION,
            actor_id="wave_system",
            reason="enter explicit wave lifecycle",
            metadata={
                "wave_transition_plan": plan.to_json(),
                "wave_definition_id": plan.wave_definition_id,
                "source_trace": plan.source_trace,
                "lifecycle_operation": "phase_enter",
            },
            mutation_source="wave_system",
        )
        if not phase_enter.plan.ok:
            return self._blocked(
                state,
                "wave:phase_enter",
                phase_enter.plan.blocked_reason or "wave_phase_enter_blocked",
                {"wave_transition": plan.to_json(), "phase_transition": phase_enter.plan.to_json()},
            )
        mutations: list[Mutation] = list(phase_enter.mutations)
        events: list[GameEvent] = list(phase_enter.events)
        records: list[dict[str, JSONValue]] = list(phase_enter.records)
        rng_events: list[RNGEvent] = []
        nodes: list[ExecutionNodeResult] = [_scheduler_node("wave_phase", "wave:phase_enter")]
        candidate = self.reducer.apply_all(state, phase_enter.mutations)
        candidate = self.reducer.apply_all(candidate, result.mutations)
        mutations.extend(result.mutations)
        records.extend(result.records)
        nodes.append(_scheduler_node("wave", "wave:transition"))
        halo_result = self.status.reconcile_halo_relations(candidate)
        events_to_dispatch: tuple[GameEvent, ...] = ()
        if not halo_result.ok:
            records.extend(halo_result.records)
            nodes.append(
                _scheduler_node(
                    "status_halo_reconciliation",
                    "wave:status_halo_reconciliation",
                    status="blocked",
                    reason=(
                        ";".join(halo_result.unsupported)
                        or "status_halo_reconciliation_blocked"
                    ),
                )
            )
        else:
            halo_reduction = self.reducer.apply_all_result(
                candidate,
                halo_result.mutations,
            )
            if not halo_reduction.ok:
                nodes.append(
                    _scheduler_node(
                        "status_halo_reconciliation",
                        "wave:status_halo_reconciliation",
                        status="blocked",
                        reason=(
                            "status_halo_reconciliation_reducer_conflict:"
                            f"{halo_reduction.conflicts[0].code}"
                        ),
                    )
                )
            else:
                candidate = halo_reduction.after_state
                mutations.extend(halo_result.mutations)
                records.extend(halo_result.records)
                rng_events.extend(halo_result.rng_events)
                nodes.append(
                    _scheduler_node(
                        "status_halo_reconciliation",
                        "wave:status_halo_reconciliation",
                    )
                )
                events_to_dispatch = (*result.events, *halo_result.events)
        dispatch_error_count = 0
        for event in events_to_dispatch:
            dispatch = self.event_dispatcher.dispatch_event(candidate, event=event)
            candidate = dispatch.after_state
            mutations.extend(dispatch.mutations)
            events.extend(dispatch.events)
            rng_events.extend(dispatch.rng_events)
            records.extend(dispatch.records)
            nodes.extend(dispatch.node_results)
            dispatch_error_count += len(dispatch.errors)
        exit_phase = ENDED if plan.status in {"battle_victory", "battle_defeat"} else IDLE
        phase_exit = self.phases.transition(
            candidate,
            exit_phase,
            actor_id="wave_system",
            reason="leave explicit wave lifecycle",
            metadata={
                "wave_transition_plan": plan.to_json(),
                "wave_definition_id": plan.wave_definition_id,
                "source_trace": plan.source_trace,
                "lifecycle_operation": "phase_exit",
            },
            mutation_source="wave_system",
        )
        if not phase_exit.plan.ok:
            nodes.append(
                _scheduler_node(
                    "wave_phase",
                    "wave:phase_exit",
                    status="blocked",
                    reason=phase_exit.plan.blocked_reason or "wave_phase_exit_blocked",
                )
            )
        else:
            candidate = self.reducer.apply_all(candidate, phase_exit.mutations)
            mutations.extend(phase_exit.mutations)
            events.extend(phase_exit.events)
            records.extend(phase_exit.records)
            nodes.append(_scheduler_node("wave_phase", "wave:phase_exit"))
        transition = _transition(
            before_state=state,
            after_state=candidate,
            action_id="wave:transition",
            actor_id="wave_system",
            events=tuple(events),
            mutations=tuple(mutations),
            records=tuple(records),
            rng_events=tuple(rng_events),
            node_results=tuple(nodes),
            coverage={
                "wave_transition": plan.to_json(),
                "scheduler_step": "wave_transition",
                "wave_lifecycle": {
                    "phase_enter": phase_enter.plan.to_json(),
                    "phase_exit": phase_exit.plan.to_json(),
                    "dispatched_event_count": len(events_to_dispatch),
                    "dispatch_error_count": dispatch_error_count,
                },
            },
        )
        after = _eligible_scheduler_state(state, candidate, transition)
        return SchedulerStepResult(after, transition)

    def _try_queue_drain(self, state: BattleState, command: ActionCommand | None = None) -> SchedulerStepResult | None:
        plan = select_next_queue_drain_plan(self.rules, self.queue, state)
        if plan is None:
            return None
        if plan.status == "waiting_window":
            return None
        queue_phase_reason = self.phases.operation_blocked_reason(state, "resolve_queue_entry")
        if queue_phase_reason:
            return self._blocked(
                state,
                "queue:phase_admission",
                queue_phase_reason,
                {
                    "drain_plan": plan.to_json(),
                    "combat_phase": self.phases.current_phase(state),
                    "phase_operation": "resolve_queue_entry",
                },
            )
        if not plan.ok:
            return self._terminalize_queue_entry(
                state,
                plan.blocked_reason or "queue_drain_blocked",
                plan,
            )
        resolution = _resolution_for_drain_plan(self.rules, state, plan)
        if resolution is None:
            return self._terminalize_queue_entry(state, "queue_resolution_missing", plan)
        requires_external_command = queue_plan_requires_external_command(plan, resolution)
        if requires_external_command and command is None:
            return self._blocked(
                state,
                "queue:selectable_drain",
                "queue_selectable_command_missing",
                {"drain_plan": plan.to_json(), "queue_resolution": resolution.to_json()},
            )
        if not requires_external_command and command is not None:
            return self._blocked(
                state,
                "queue:mandatory_drain",
                "queue_mandatory_blocks_external_command",
                {"drain_plan": plan.to_json(), "queue_resolution": resolution.to_json(), "command": _command_payload(command)},
            )
        action_transition = None
        if resolution.resolved_kind == "action_definition" or _is_extra_turn_action_choice_plan(plan, resolution):
            preflight_reason = self._queue_action_preflight_reason(state, plan, command=command)
            if preflight_reason:
                if not _queue_submission_rejection_reason(preflight_reason):
                    return self._terminalize_queue_entry(state, preflight_reason, plan)
                return self._blocked(
                    state,
                    "queue:action_drain",
                    preflight_reason,
                    {
                        "drain_plan": plan.to_json(),
                        "queue_resolution": resolution.to_json(),
                        "queue_window_plan": plan.queue_window or {},
                    },
                )
        dequeue = self.queue.drain_admitted(
            state,
            plan,
            source="queue_system",
            metadata={
                "queue_operation": "dequeue",
                "scheduler": "timeline_scheduler",
                "queue_window_plan": plan.queue_window or {},
                "queue_lifecycle_policy_id": _queue_lifecycle_policy_id(plan),
                "extra_action_policy_id": _extra_action_policy_id(plan),
                **_manual_ultimate_dequeue_metadata(self.rules, plan),
            },
        )
        after_dequeue = self.reducer.apply_all(state, (dequeue,))
        drain_payload: dict[str, JSONValue] = {
            "drain_plan": plan.to_json(),
            "queue_resolution": resolution.to_json(),
            "queue_window_plan": plan.queue_window or {},
            "external_command": _command_payload(command) if command is not None else {},
        }
        records: list[dict[str, JSONValue]] = [
            SettlementRecord(
                record_type="queue_drain_begin",
                source="queue_system",
                process_only=True,
                payload=drain_payload,
                trace=plan.source_trace or {},
            ).to_json(),
            SettlementRecord(
                record_type="queue_dequeue",
                source="queue_system",
                mutation_id=dequeue.stable_id(),
                process_only=False,
                payload=drain_payload,
                trace=plan.source_trace or {},
            ).to_json()
        ]
        mutations: tuple[Mutation, ...] = (dequeue,)
        events: tuple[GameEvent, ...] = (
            GameEvent(
                "queue.drain.begin",
                source_id=str(plan.queue_entry.get("actor_id") or ""),
                event_id=f"event:{state.event_index}:queue_drain_begin:{plan.queue_intent_id}",
                window="queue",
                process_only=True,
                payload=drain_payload,
            ),
            GameEvent(
                "queue.drained",
                source_id=str(plan.queue_entry.get("actor_id") or ""),
                event_id=f"event:{state.event_index}:queue_drained:{plan.queue_intent_id}",
                window="queue",
                process_only=True,
                payload={"drain_plan": plan.to_json()},
            ),
        )
        after_state = after_dequeue
        window_family = str((plan.queue_window or {}).get("window_family") or "")
        if window_family == "extra_turn":
            lifecycle_policy = _queue_lifecycle_policy(plan)
            events = (
                *events,
                GameEvent(
                    "extra_turn.begin",
                    source_id=str(plan.queue_entry.get("actor_id") or ""),
                    event_id=f"event:{after_dequeue.event_index}:extra_turn_begin:{plan.queue_intent_id}",
                    window="extra_turn",
                    process_only=True,
                    payload={"drain_plan": plan.to_json(), "lifecycle_policy": lifecycle_policy},
                ),
            )
            records.extend(
                _scheduler_process_records(
                    "extra_turn_begin",
                    {
                        "queue_intent_id": plan.queue_intent_id,
                        "queue_window_plan": plan.queue_window or {},
                        "lifecycle_policy": lifecycle_policy,
                    },
                )
            )
        if resolution.resolved_kind == "standalone_ability_graph":
            graph_id = _first_str(resolution.resolved_ids.get("standalone_ability_graph_id"))
            phases = _phases_for_graph(self.rules, graph_id)
            ability_result = self.ability_tasks.execute_standalone(
                after_dequeue,
                phases=phases,
                actor_id=str(plan.queue_entry.get("actor_id") or ""),
                target_ids=tuple(str(item) for item in plan.queue_entry.get("target_ids", ()) if isinstance(item, str)),
                queue_entry=plan.queue_entry,
                queue_resolution=resolution.to_json(),
            )
            ability_commit = finalize_selected_execution_graph(
                after_dequeue,
                ability_result.after_state,
                ability_result.mutations,
                ability_result.node_results,
                reducer=self.reducer,
            )
            if not ability_commit.outcome.successor_eligible:
                reasons = ",".join(ability_commit.outcome.reason_codes) or ability_commit.outcome.category
                return self._terminalize_queue_entry(
                    state,
                    f"queue_standalone_ability_not_successor:{reasons}",
                    plan,
                    child_evidence={
                        "resolved_kind": "standalone_ability_graph",
                        "graph_id": graph_id,
                        "outcome": ability_commit.outcome.to_json(),
                        "atomic_commit": ability_commit.evidence,
                        "planned_mutation_count": len(ability_result.mutations),
                        "published": False,
                    },
                )
            after_state = ability_commit.after_state
            mutations = (*mutations, *ability_commit.committed_mutations)
            events = (*events, *ability_result.events)
            records.extend(ability_result.records)
        elif resolution.resolved_kind == "action_definition" or _is_extra_turn_action_choice_plan(plan, resolution):
            from ..core.executor import CombatExecutor

            actor_id = str(plan.queue_entry.get("actor_id") or "")
            selected_command = self._queue_action_command_from_plan(plan, command)
            queue_command = ActionCommand(
                actor_id=actor_id,
                action_id=selected_command.action_id,
                action_level=selected_command.action_level,
                target_ids=selected_command.target_ids,
                source="queue",
                queue_name=plan.queue_name,
                metadata={
                    "queue_parent": {
                        "queue_entry": plan.queue_entry,
                        "queue_intent_id": plan.queue_intent_id,
                        "queue_resolution_id": plan.queue_resolution_id,
                        "queue_priority_id": plan.queue_priority_id,
                        "priority_key": plan.priority_key,
                        "priority_value": plan.priority_value,
                        "drain_order": plan.drain_order,
                        "queue_window_plan": plan.queue_window or {},
                        "extra_action_policy": _extra_action_policy_payload(self.rules, plan),
                        "action_choice_source": selected_command.metadata.get("action_choice_source", "queue_resolution"),
                    }
                },
            )
            actor = after_dequeue.units.get(actor_id)
            target_query = self.action_targets.query(
                after_dequeue,
                actor_id,
                queue_command.action_id,
                queue_command.action_level,
            )
            target_decision = self.action_targets.accept(
                after_dequeue,
                target_query,
                queue_command.target_ids,
            )
            if not target_decision.accepted or target_decision.context is None:
                return self._terminalize_queue_entry(
                    state,
                    target_decision.blocked_reason or "queue_action_target_selection_blocked",
                    plan,
                    child_evidence={
                        "resolved_kind": resolution.resolved_kind,
                        "target_decision": target_decision.to_json(),
                        "published": False,
                    },
                )
            target_context = target_decision.context
            authorization = _issue_action_submission_authorization(
                state=after_dequeue,
                submission_mode="queue",
                actor_id=actor_id,
                owner_entity_ref=actor.template_id if actor is not None else "",
                action_id=queue_command.action_id,
                action_level=queue_command.action_level,
                window=str((plan.queue_window or {}).get("window_family") or "queue"),
                source_id=str(plan.queue_entry.get("entry_id") or plan.queue_intent_id),
                selection_context_fingerprint=target_context.context_fingerprint,
            )
            after_action, action_transition = CombatExecutor(self.rules).execute(
                queue_command,
                after_dequeue,
                submission_authorization=authorization,
                target_selection_context=target_context,
            )
            if not action_transition.outcome.successor_eligible:
                reasons = ",".join(action_transition.outcome.reason_codes) or action_transition.outcome.category
                return self._terminalize_queue_entry(
                    state,
                    f"queue_child_transition_not_successor:{reasons}",
                    plan,
                    child_transition=action_transition,
                )
            after_state = after_action
            mutations = (*mutations, *action_transition.transaction.mutations)
            events = (
                *events,
                GameEvent(
                    "queue.action.before",
                    source_id=actor_id,
                    event_id=f"event:{after_dequeue.event_index}:queue_action_before:{plan.queue_intent_id}",
                    window="queue",
                    process_only=True,
                    payload={"command": _command_payload(queue_command), "drain_plan": plan.to_json()},
                ),
                *action_transition.transaction.events,
                GameEvent(
                    "queue.action.after",
                    source_id=actor_id,
                    event_id=f"event:{after_action.event_index}:queue_action_after:{plan.queue_intent_id}",
                    window="queue",
                    process_only=True,
                    payload={"command": _command_payload(queue_command), "drain_plan": plan.to_json()},
                ),
            )
            if action_transition.transaction.settlement:
                records.extend(action_transition.transaction.settlement.records)
            if plan.queue_intent_id.startswith("manual_ultimate:") and action_transition.coverage.get("action_enabled") is True:
                energy_mutation = self._ultimate_energy_cost_mutation(after_state, plan, queue_command)
                after_state = self.reducer.apply_all(after_state, (energy_mutation,))
                mutations = (*mutations, energy_mutation)
                records.append(
                    SettlementRecord(
                        record_type="ultimate_energy_cost",
                        source="combat_executor.resources",
                        mutation_id=energy_mutation.stable_id(),
                        process_only=False,
                        payload={
                            "actor_id": actor_id,
                            "action_id": queue_command.action_id,
                            "action_level": queue_command.action_level,
                            "queue_intent_id": plan.queue_intent_id,
                            "queue_resolution_id": plan.queue_resolution_id,
                            "queue_window_plan": plan.queue_window or {},
                            "resource_rule_id": energy_mutation.metadata.get("resource_rule_id"),
                            "before_energy": energy_mutation.before,
                            "after_energy": energy_mutation.after,
                            "post_use_energy_gain": energy_mutation.metadata.get("post_use_energy_gain"),
                            "post_use_energy_gain_source": energy_mutation.metadata.get("post_use_energy_gain_source"),
                        },
                        trace=energy_mutation.metadata.get("source_trace") if isinstance(energy_mutation.metadata.get("source_trace"), dict) else {},
                    ).to_json()
                )
        if window_family == "extra_turn":
            lifecycle_policy = _queue_lifecycle_policy(plan)
            events = (
                *events,
                GameEvent(
                    "extra_turn.end",
                    source_id=str(plan.queue_entry.get("actor_id") or ""),
                    event_id=f"event:{after_state.event_index}:extra_turn_end:{plan.queue_intent_id}",
                    window="extra_turn",
                    process_only=True,
                    payload={"drain_plan": plan.to_json(), "lifecycle_policy": lifecycle_policy},
                ),
            )
            records.extend(
                _scheduler_process_records(
                    "extra_turn_end",
                    {
                        "queue_intent_id": plan.queue_intent_id,
                        "queue_window_plan": plan.queue_window or {},
                        "lifecycle_policy": lifecycle_policy,
                    },
                )
            )
        child_transitions = (action_transition,) if action_transition is not None else ()
        drain_end_payload: dict[str, JSONValue] = {
            **drain_payload,
            "child_transition_present": action_transition is not None,
            "mutation_count": len(mutations),
            "event_count": len(events) + 1,
        }
        events = (
            *events,
            GameEvent(
                "queue.drain.end",
                source_id=str(plan.queue_entry.get("actor_id") or ""),
                event_id=f"event:{after_state.event_index}:queue_drain_end:{plan.queue_intent_id}",
                window="queue",
                process_only=True,
                payload=drain_end_payload,
            ),
        )
        records.append(
            SettlementRecord(
                record_type="queue_drain_end",
                source="queue_system",
                process_only=True,
                payload=drain_end_payload,
                trace=plan.source_trace or {},
            ).to_json()
        )
        transition = _transition(
            before_state=state,
            after_state=after_state,
            action_id="queue:drain_admitted",
            actor_id=str(plan.queue_entry.get("actor_id") or ""),
            events=events,
            mutations=mutations,
            records=tuple(records),
            node_results=(
                _scheduler_node("queue", "queue:drain_admitted"),
                *(ability_result.node_results if resolution.resolved_kind == "standalone_ability_graph" else ()),
                *_child_transition_node_results(child_transitions),
            ),
            coverage={
                "drain_plan": plan.to_json(),
                "queue_resolution": resolution.to_json(),
                "queue_window_plan": plan.queue_window or {},
                "queue_progress": {
                    "step_budget": QUEUE_DRAIN_STEP_BUDGET,
                    "steps_used": 1,
                    "before_length": len(state.queues.get(plan.queue_name, ())),
                    "after_length": len(after_state.queues.get(plan.queue_name, ())),
                    "terminal_disposition": "completed",
                    "monotonic_progress": len(after_state.queues.get(plan.queue_name, ())) < len(state.queues.get(plan.queue_name, ())),
                },
                "phase_machine": {
                    "operation": "resolve_queue_entry",
                    "current_phase": self.phases.current_phase(state),
                    "admitted": True,
                },
            },
        )
        return SchedulerStepResult(
            _eligible_scheduler_state(state, after_state, transition),
            transition,
            child_transitions=child_transitions,
        )

    def _terminalize_queue_entry(
        self,
        state: BattleState,
        blocked_reason: str,
        plan: QueueDrainPlan,
        *,
        child_transition: BattleTransition | None = None,
        child_evidence: dict[str, JSONValue] | None = None,
    ) -> SchedulerStepResult:
        terminal_plan = self.queue.plan_terminal_resolution(
            state,
            plan,
            blocked_reason=blocked_reason,
        )
        terminal = self.queue.resolve_terminal(state, terminal_plan)
        after = self.reducer.apply_all(state, terminal.mutations)
        transition_evidence: dict[str, JSONValue] = (
            {
                "action_id": child_transition.transaction.command.action_id,
                "outcome": child_transition.outcome.to_json(),
                "mutation_count": len(child_transition.transaction.mutations),
                "published": False,
            }
            if child_transition is not None
            else (child_evidence or {})
        )
        records = (
            *terminal.records,
            *_scheduler_process_records(
                "queue_entry_terminal_resolution",
                {
                    "queue_terminal_plan": terminal_plan.to_json(),
                    "child_transition": transition_evidence,
                },
            ),
        )
        transition = _transition(
            before_state=state,
            after_state=after,
            action_id=f"queue:{terminal_plan.disposition}",
            actor_id=str(plan.queue_entry.get("actor_id") or ""),
            events=terminal.events,
            mutations=terminal.mutations,
            records=records,
            node_results=(
                _scheduler_node("queue_terminal", f"queue:{terminal_plan.disposition}:{terminal_plan.entry_id}"),
            ),
            coverage={
                "drain_plan": plan.to_json(),
                "queue_terminal_plan": terminal_plan.to_json(),
                "child_transition": transition_evidence,
                "queue_progress": {
                    "step_budget": QUEUE_DRAIN_STEP_BUDGET,
                    "steps_used": 1,
                    "before_length": terminal_plan.before_length,
                    "after_length": terminal_plan.after_length,
                    "retained": terminal_plan.retained,
                    "monotonic_progress": terminal_plan.to_json()["monotonic_progress"],
                },
                "phase_machine": {
                    "operation": "resolve_queue_entry",
                    "current_phase": self.phases.current_phase(state),
                    "admitted": True,
                },
            },
        )
        return SchedulerStepResult(
            _eligible_scheduler_state(state, after, transition),
            transition,
        )

    def _queue_action_preflight_reason(self, state: BattleState, plan: QueueDrainPlan, *, command: ActionCommand | None = None) -> str:
        actor_id = str(plan.queue_entry.get("actor_id") or "")
        if not actor_id or actor_id not in state.units:
            return "queue_action_actor_missing"
        if not state.units[actor_id].template_id:
            return "queue_action_actor_template_missing"
        control_gate = status_control_gate_for_actor(state.units[actor_id])
        if control_gate is not None:
            return str(control_gate.get("reason") or "status_control_gate")
        selected_action_id = plan.resolved_action_id
        selected_action_level = plan.resolved_action_level
        selected_targets = tuple(str(item) for item in plan.queue_entry.get("target_ids", ()) if isinstance(item, str))
        extra_policy = self._extra_action_policy_for_plan(plan)
        window_family = str((plan.queue_window or {}).get("window_family") or "")
        if window_family == "extra_turn":
            if extra_policy is None:
                return "extra_turn_action_policy_missing"
            if extra_policy.coverage_status != "executable":
                return extra_policy.blocked_reason or f"extra_turn_action_policy_not_executable:{extra_policy.coverage_status}"
            if extra_policy.action_selection_kind in {
                "route_or_source_selected_action",
                "route_or_source_selected_non_ultimate_action",
            }:
                if command is None:
                    return "extra_turn_route_action_choice_missing"
                if command.actor_id != actor_id:
                    return "extra_turn_route_action_actor_mismatch"
                selected_action_id = command.action_id
                selected_action_level = command.action_level
                selected_targets = command.target_ids
        if window_family == "ultimate":
            if command is None:
                return "queue_selectable_command_missing"
            if command.actor_id != actor_id:
                return "manual_ultimate_action_actor_mismatch"
            if command.action_id != selected_action_id or int(command.action_level) != int(selected_action_level or 0):
                return "manual_ultimate_action_mismatch"
            requested_targets = tuple(command.target_ids)
            if requested_targets != selected_targets:
                return "manual_ultimate_target_mismatch"
            selected_action_id = command.action_id
            selected_action_level = command.action_level
            selected_targets = requested_targets
        if not selected_action_id or selected_action_level is None:
            return "queue_action_resolution_missing"
        target_query = self.action_targets.query(
            state,
            actor_id,
            selected_action_id,
            selected_action_level,
        )
        target_decision = self.action_targets.accept(
            state,
            target_query,
            selected_targets,
        )
        if not target_decision.accepted:
            return target_decision.blocked_reason or "queue_action_target_selection_blocked"
        definition = self.rules.action_definition(selected_action_id, selected_action_level)
        if definition is None:
            return "queue_action_definition_missing"
        action_event = self.rules.action_event(selected_action_id, selected_action_level)
        if action_event is None:
            return "queue_action_event_missing"
        if action_event.coverage_status in {"blocked", "audit_only", "discovered_only", "unsupported"}:
            return f"queue_action_event_not_admitted:{action_event.coverage_status}"
        if window_family == "extra_turn" and extra_policy is not None:
            allowed = set(extra_policy.allowed_action_kinds)
            if allowed and not _action_kind_allowed(definition.attack_type, definition.skill_effect, allowed):
                return "extra_turn_action_kind_not_admitted"
        resource_policy = _queue_entry_resource_policy(plan)
        if resource_policy.get("ignore_skill_point_delta") is not True and definition.bp_need > state.skill_points:
            return "queue_action_resource_preflight_failed:insufficient_skill_points"
        if plan.queue_intent_id.startswith("manual_ultimate:"):
            ultimate_rule, rule_blocked_reason = self.rules.select_resource_rule("ultimate_energy_cost")
            if ultimate_rule is None:
                return rule_blocked_reason
            actor = state.units[actor_id]
            if actor.max_energy <= 0 or actor.energy < actor.max_energy:
                return "manual_ultimate_energy_not_ready_at_drain"
        window = plan.queue_window or {}
        if window.get("ok") is not True:
            return str(window.get("blocked_reason") or "queue_window_not_admitted")
        return ""

    def _queue_action_command_from_plan(self, plan: QueueDrainPlan, command: ActionCommand | None) -> ActionCommand:
        window_family = str((plan.queue_window or {}).get("window_family") or "")
        if window_family in {"extra_turn", "ultimate"} and command is not None:
            source = "route_manual_ultimate" if window_family == "ultimate" else "route_manual_extra_turn"
            return replace(
                command,
                source="queue",
                queue_name=plan.queue_name,
                metadata={**command.metadata, "action_choice_source": source},
            )
        return ActionCommand(
            actor_id=str(plan.queue_entry.get("actor_id") or ""),
            action_id=plan.resolved_action_id,
            action_level=plan.resolved_action_level or 0,
            target_ids=tuple(str(item) for item in plan.queue_entry.get("target_ids", ()) if isinstance(item, str)),
            source="queue",
            queue_name=plan.queue_name,
            metadata={"action_choice_source": "queue_resolution"},
        )

    def _extra_action_policy_for_plan(self, plan: QueueDrainPlan):
        window = plan.queue_window or {}
        policy_id = ""
        policy = window.get("window_policy")
        if isinstance(policy, dict):
            policy_id = str(policy.get("extra_action_policy_id") or "")
        if policy_id:
            return self.rules.extra_action_policy(policy_id)
        queue_window_id = str(window.get("queue_window_id") or "")
        if queue_window_id:
            return self.rules.extra_action_policy_for_window(queue_window_id)
        return self.rules.extra_action_policy_for_intent(plan.queue_intent_id)

    def _pending_turn_end_mutation(self, state: BattleState, actor_id: str, child_action_id: str) -> Mutation:
        rule = self.rules.default_timeline_rule()
        plan_id = f"turn_advance_plan:{state.event_index}:{actor_id}:pending_turn_end"
        pending = {
            "actor_id": actor_id,
            "child_action_id": child_action_id,
            "turn_sequence_index": state.global_flags.get("turn_sequence_index", 0),
            "timeline_rule_id": rule.timeline_rule_id,
            "reason": "queue_entries_pending_after_action",
        }
        return Mutation(
            op="set",
            path=("global_flags", "pending_turn_end"),
            before=state.global_flags.get("pending_turn_end"),
            after=pending,
            reason="defer natural turn end while queue entries are pending",
            source="timeline_system",
            before_exists="pending_turn_end" in state.global_flags,
            metadata={
                "timeline_rule_id": rule.timeline_rule_id,
                "turn_advance_plan_id": plan_id,
                "source_trace": rule.source.to_json(),
                "scheduler_operation": "defer_turn_end_for_queue",
            },
            mutation_id=f"mutation:timeline:pending_turn_end:{state.event_index}:{actor_id}",
        )

    def _clear_pending_turn_end_mutation(self, state: BattleState, actor_id: str) -> Mutation:
        rule = self.rules.default_timeline_rule()
        plan_id = f"turn_advance_plan:{state.event_index}:{actor_id}:clear_pending_turn_end"
        return Mutation(
            op="delete",
            path=("global_flags", "pending_turn_end"),
            before=state.global_flags.get("pending_turn_end"),
            after=None,
            reason="clear deferred natural turn end marker",
            source="timeline_system",
            after_exists=False,
            metadata={
                "timeline_rule_id": rule.timeline_rule_id,
                "turn_advance_plan_id": plan_id,
                "source_trace": rule.source.to_json(),
                "scheduler_operation": "clear_deferred_turn_end",
            },
            mutation_id=f"mutation:timeline:pending_turn_end_clear:{state.event_index}:{actor_id}",
        )

    def _complete_pending_turn_end(self, state: BattleState, pending_turn_end: dict[str, JSONValue]) -> SchedulerStepResult:
        actor_id = str(pending_turn_end.get("actor_id") or "")
        if not actor_id or actor_id not in state.units:
            return self._blocked(
                state,
                "scheduler:pending_turn_end",
                "pending_turn_end_actor_missing",
                {"pending_turn_end": pending_turn_end},
            )
        action_lifecycle = self._apply_status_lifecycle_tick(state, "ActionPhaseEnd", actor_id=actor_id)
        end_result = self.end_current_turn(action_lifecycle.after_state)
        clear_mutation = self._clear_pending_turn_end_mutation(end_result.after_state, actor_id)
        after_clear = self.reducer.apply_all(end_result.after_state, (clear_mutation,))
        clear_record = SettlementRecord(
            record_type="scheduler_pending_turn_end_cleared",
            source="timeline_scheduler",
            mutation_id=clear_mutation.stable_id(),
            process_only=False,
            payload={"pending_turn_end": pending_turn_end},
            trace=clear_mutation.metadata.get("source_trace") if isinstance(clear_mutation.metadata.get("source_trace"), dict) else {},
        ).to_json()
        combined = _combine_scheduler_transitions(
            before_state=state,
            after_state=after_clear,
            actor_id=actor_id,
            records=(
                *_scheduler_process_records(
                    "scheduler_pending_turn_end_step",
                    {
                        "scheduler_step": "complete_deferred_turn_lifecycle",
                        "pending_turn_end": pending_turn_end,
                        "action_lifecycle_hook": "ActionPhaseEnd",
                    },
                ),
                *action_lifecycle.records,
                *(end_result.transition.transaction.settlement.records if end_result.transition.transaction.settlement else ()),
                clear_record,
            ),
            events=(
                GameEvent(
                    "scheduler.pending_turn_end.begin",
                    source_id=actor_id,
                    event_id=f"event:{state.event_index}:pending_turn_end_begin:{actor_id}",
                    window="scheduler",
                    process_only=True,
                    payload={"pending_turn_end": pending_turn_end},
                ),
                *action_lifecycle.events,
                *end_result.transition.transaction.events,
                GameEvent(
                    "scheduler.pending_turn_end.end",
                    source_id=actor_id,
                    event_id=f"event:{after_clear.event_index}:pending_turn_end_end:{actor_id}",
                    window="scheduler",
                    process_only=True,
                    payload={"pending_turn_end": pending_turn_end},
                ),
            ),
            mutations=(
                *action_lifecycle.mutations,
                *end_result.transition.transaction.mutations,
                clear_mutation,
            ),
            target_resolution=TargetResolution(reason="pending_turn_end_no_target", source="timeline_scheduler"),
            child_transitions=(end_result.transition,),
            coverage={
                "scheduler_step": "complete_deferred_turn_lifecycle",
                "pending_turn_end": pending_turn_end,
                "action_lifecycle": {"life_step_moment": "ActionPhaseEnd", "mutation_count": len(action_lifecycle.mutations)},
                "turn_end": end_result.transition.coverage,
            },
        )
        return SchedulerStepResult(
            _eligible_scheduler_state(state, after_clear, combined),
            combined,
            child_transitions=(end_result.transition,),
        )

    def _ultimate_energy_cost_mutation(
        self,
        state: BattleState,
        plan: QueueDrainPlan,
        command: ActionCommand,
    ) -> Mutation:
        rule = self.rules.default_ultimate_energy_cost_rule()
        definition = self.rules.require_action_definition(command.action_id, command.action_level)
        action_event = self.rules.require_action_event(command.action_id, command.action_level)
        action_trace = self.rules.action_definition_source_trace(command.action_id, command.action_level) or {}
        source_trace = {
            **action_trace,
            "action_event_source_trace": action_event.source.to_json(),
            "queue_parent": command.metadata.get("queue_parent") if isinstance(command.metadata.get("queue_parent"), dict) else {},
            "resource_rule_source": rule.source.to_json(),
        }
        post_use_energy_gain = max(0.0, float(definition.sp_base))
        return self.resources.spend_ultimate_energy(
            state,
            command.actor_id,
            rule,
            post_use_energy_gain=post_use_energy_gain,
            metadata={
                "action_id": command.action_id,
                "action_level": command.action_level,
                "definition_id": definition.definition_id,
                "action_event_id": action_event.action_event_id,
                "action_sp_base": post_use_energy_gain,
                "post_use_energy_gain_source": "ActionDefinitionIR.sp_base",
                "queue_parent": command.metadata.get("queue_parent") if isinstance(command.metadata.get("queue_parent"), dict) else {},
                "queue_intent_id": plan.queue_intent_id,
                "queue_resolution_id": plan.queue_resolution_id,
                "queue_priority_id": plan.queue_priority_id,
                "queue_window_plan": plan.queue_window or {},
                "source_trace": source_trace,
            },
        )

    def _blocked(
        self,
        state: BattleState,
        action_id: str,
        reason: str,
        payload: dict[str, JSONValue],
    ) -> SchedulerStepResult:
        is_queue_block = action_id.startswith("queue:")
        record = SettlementRecord(
            record_type="scheduler_blocked",
            source="timeline_scheduler",
            process_only=True,
            payload={"reason": reason, **payload},
            trace={},
        ).to_json()
        queue_record = (
            SettlementRecord(
                record_type="queue_drain_blocked",
                source="queue_system",
                process_only=True,
                payload={"reason": reason, **payload},
                trace={},
            ).to_json(),
        ) if is_queue_block else ()
        queue_event = (
            GameEvent(
                "queue.drain.blocked",
                event_id=f"event:{state.event_index}:{action_id}:queue_drain_blocked",
                window="queue",
                process_only=True,
                payload={"reason": reason, **payload},
            ),
        ) if is_queue_block else ()
        transition = _transition(
            before_state=state,
            after_state=state,
            action_id=action_id,
            events=(
                GameEvent(
                    "scheduler.blocked",
                    event_id=f"event:{state.event_index}:{action_id}:blocked",
                    window="scheduler",
                    process_only=True,
                    payload={"reason": reason, **payload},
                ),
                *queue_event,
            ),
            records=(record, *queue_record),
            node_results=(_scheduler_node("scheduler", action_id, status="blocked", reason=reason),),
            preflight_blocked=True,
            preflight_reason=reason,
            coverage={"blocked_reason": reason},
        )
        return SchedulerStepResult(state, transition)


def _status_phase1_lifecycle_event(
    state: BattleState,
    unit_id: str,
    detail: dict[str, JSONValue],
    life_step_moment: str,
) -> GameEvent | None:
    return _status_phase_lifecycle_event(
        state,
        unit_id,
        detail,
        life_step_moment,
        "OnPhase1",
    )


def _status_phase_lifecycle_event(
    state: BattleState,
    unit_id: str,
    detail: dict[str, JSONValue],
    life_step_moment: str,
    callback_event: str,
) -> GameEvent | None:
    if life_step_moment != "ModifierPhase1End":
        return None
    trigger_ids_by_event = detail.get("trigger_ids_by_event")
    trigger_ids = trigger_ids_by_event.get(callback_event) if isinstance(trigger_ids_by_event, dict) else None
    if not isinstance(trigger_ids, list) or not any(isinstance(item, str) and item for item in trigger_ids):
        return None
    source_trace = detail.get("source_trace") if isinstance(detail.get("source_trace"), dict) else {}
    modifier_name = str(detail.get("modifier_name") or "")
    status_id = str(detail.get("status_id") or "")
    status_instance_id = str(detail.get("instance_id") or "")
    caster_id = str(detail.get("caster_id") or unit_id)
    return GameEvent(
        "status.lifecycle",
        source_id=caster_id,
        target_id=unit_id,
        event_id=(
            f"event:{state.event_index}:status_lifecycle:{callback_event}:"
            f"{unit_id}:{status_id.replace(':', '_')}:{status_instance_id}"
        ),
        window=callback_event,
        process_only=True,
        payload={
            "callback_event": callback_event,
            "listener_scope": "status_local",
            "lifecycle_operation": "tick",
            "life_step_moment": life_step_moment,
            "target_id": unit_id,
            "owner_id": unit_id,
            "modifier_name": modifier_name,
            "status_id": status_id,
            "status_instance_id": status_instance_id,
            "source_trace": source_trace,
        },
    )


def _status_detail_by_instance(
    state: BattleState,
    unit_id: str,
    instance_id: str,
) -> dict[str, JSONValue] | None:
    if not instance_id or unit_id not in state.units:
        return None
    details = state.units[unit_id].flags.get("status_details", ())
    if not isinstance(details, (list, tuple)):
        return None
    for item in details:
        if isinstance(item, dict) and item.get("instance_id") == instance_id:
            return item
    return None


def _transition(
    *,
    before_state: BattleState,
    after_state: BattleState,
    action_id: str,
    actor_id: str = "scheduler",
    events: tuple[GameEvent, ...] = (),
    mutations: tuple[Mutation, ...] = (),
    records: tuple[dict[str, JSONValue], ...] = (),
    rng_events: tuple[RNGEvent, ...] = (),
    node_results: tuple[ExecutionNodeResult, ...],
    preflight_blocked: bool = False,
    preflight_reason: str = "",
    coverage: dict[str, JSONValue] | None = None,
) -> BattleTransition:
    atomic_commit = finalize_selected_execution_graph(
        before_state,
        after_state,
        mutations,
        node_results,
        preflight_blocked=preflight_blocked,
        preflight_reason=preflight_reason,
    )
    command = ActionCommand(actor_id=actor_id, action_id=action_id, action_level=0, metadata={"scheduler": "timeline"})
    settlement = ActionSettlement(
        action_id=action_id,
        actor_id=actor_id,
        target_ids=(),
        records=records_for_atomic_result(records, atomic_commit),
    )
    phase_coverage = _phase_coverage(atomic_commit.after_state)
    requested_coverage = coverage or {}
    requested_phase = requested_coverage.get("phase_machine")
    if isinstance(requested_phase, dict):
        phase_coverage = {**phase_coverage, **requested_phase}
    return BattleTransition(
        transaction=ActionTransaction(
            command=command,
            before=before_state.snapshot(),
            events=events_for_atomic_result(events, atomic_commit),
            mutations=atomic_commit.committed_mutations,
            trigger_windows=(),
            settlement=settlement,
        ),
        after=atomic_commit.after_state.snapshot(),
        target_resolution=TargetResolution(reason="scheduler_no_target", source="timeline_scheduler"),
        rng_events=rng_events_for_atomic_result(rng_events, atomic_commit),
        outcome=atomic_commit.outcome,
        coverage={
            **requested_coverage,
            "phase_machine": phase_coverage,
            "atomic_commit": atomic_commit.evidence,
        },
    )


def _combine_scheduler_transitions(
    *,
    before_state: BattleState,
    after_state: BattleState,
    actor_id: str,
    events: tuple[GameEvent, ...],
    mutations: tuple[Mutation, ...],
    records: tuple[dict[str, JSONValue], ...],
    target_resolution: TargetResolution,
    child_transitions: tuple[BattleTransition, ...],
    coverage: dict[str, JSONValue],
) -> BattleTransition:
    action_id = "scheduler:step"
    command = ActionCommand(
        actor_id=actor_id,
        action_id=action_id,
        action_level=0,
        metadata={"scheduler": "timeline", "scheduler_step": coverage.get("scheduler_step", "")},
    )
    node_results = (
        _scheduler_node("scheduler", action_id),
        *_child_transition_node_results(child_transitions),
    )
    atomic_commit = finalize_selected_execution_graph(
        before_state,
        after_state,
        mutations,
        node_results,
    )
    settlement = ActionSettlement(
        action_id=action_id,
        actor_id=actor_id,
        target_ids=(),
        records=records_for_atomic_result(records, atomic_commit),
    )
    phase_coverage = _phase_coverage(atomic_commit.after_state)
    requested_phase = coverage.get("phase_machine")
    if isinstance(requested_phase, dict):
        phase_coverage = {**phase_coverage, **requested_phase}
    return BattleTransition(
        transaction=ActionTransaction(
            command=command,
            before=before_state.snapshot(),
            events=events_for_atomic_result(events, atomic_commit),
            mutations=atomic_commit.committed_mutations,
            trigger_windows=(),
            settlement=settlement,
        ),
        after=atomic_commit.after_state.snapshot(),
        target_resolution=target_resolution,
        outcome=atomic_commit.outcome,
        coverage={
            **coverage,
            "phase_machine": phase_coverage,
            "atomic_commit": atomic_commit.evidence,
        },
    )


def _phase_coverage(state: BattleState) -> dict[str, JSONValue]:
    machine = CombatPhaseMachine()
    return {
        "schema_version": "p7_s9_combat_phase_machine_v1",
        "current_phase": machine.current_phase(state),
        "allowed_next_phases": list(machine.allowed_next_phases(state)),
    }


def _with_scheduler_record(
    result: SchedulerStepResult,
    *,
    record_type: str,
    payload: dict[str, JSONValue],
) -> SchedulerStepResult:
    settlement = result.transition.transaction.settlement
    records = settlement.records if settlement else ()
    appended = (*records, *_scheduler_process_records(record_type, payload))
    command = result.transition.transaction.command
    replacement = BattleTransition(
        transaction=ActionTransaction(
            command=command,
            before=result.transition.transaction.before,
            events=result.transition.transaction.events,
            mutations=result.transition.transaction.mutations,
            trigger_windows=result.transition.transaction.trigger_windows,
            settlement=ActionSettlement(
                action_id=command.action_id,
                actor_id=command.actor_id,
                target_ids=command.target_ids,
                records=appended,
            ),
        ),
        after=result.transition.after,
        target_resolution=result.transition.target_resolution,
        rng_events=result.transition.rng_events,
        outcome=result.transition.outcome,
        coverage={**result.transition.coverage, **payload},
        contract_validation=result.transition.contract_validation,
    )
    return SchedulerStepResult(result.after_state, replacement, result.child_transitions)


def _scheduler_node(
    node_kind: str,
    node_id: str,
    *,
    status: ExecutionNodeStatus = "complete",
    reason: str = "",
) -> ExecutionNodeResult:
    return ExecutionNodeResult(
        node_kind=node_kind,
        node_id=node_id,
        status=status,
        reason_code=reason,
    )


def _child_transition_node_results(
    transitions: tuple[BattleTransition, ...],
) -> tuple[ExecutionNodeResult, ...]:
    results: list[ExecutionNodeResult] = []
    for index, transition in enumerate(transitions):
        results.append(
            ExecutionNodeResult(
                node_kind="child_transition",
                node_id=transition.transaction.command.action_id or f"child:{index}",
                status="complete" if transition.outcome.successor_eligible else "partial",
                reason_code=""
                if transition.outcome.successor_eligible
                else ",".join(transition.outcome.reason_codes)
                or f"child_transition_{transition.outcome.category}",
            )
        )
        results.extend(transition.outcome.node_results)
    return tuple(results)


def _eligible_scheduler_state(
    before_state: BattleState,
    candidate_after_state: BattleState,
    transition: BattleTransition,
) -> BattleState:
    return candidate_after_state if transition.outcome.successor_eligible else before_state


def _scheduler_process_records(
    record_type: str,
    payload: dict[str, JSONValue],
) -> tuple[dict[str, JSONValue], ...]:
    return (
        SettlementRecord(
            record_type=record_type,
            source="timeline_scheduler",
            process_only=True,
            payload=payload,
            trace={},
        ).to_json(),
    )


def _phase_rule_metadata(rule, plan_id: str) -> dict[str, JSONValue]:
    return {
        "timeline_rule_id": rule.timeline_rule_id,
        "turn_advance_plan_id": plan_id,
        "source_trace": rule.source.to_json(),
    }


def _enemy_action_cursor_record(
    mutation: Mutation,
    candidate: EnemyActionCandidate,
    command: ActionCommand,
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="enemy_action_sequence_cursor",
        source="enemy_action_system",
        mutation_id=mutation.stable_id(),
        process_only=False,
        payload={
            "actor_id": candidate.actor_id,
            "monster_data_card_id": candidate.monster_data_card_id,
            "sequence_index": candidate.sequence_index,
            "action_id": command.action_id,
            "action_level": command.action_level,
            "target_ids": list(command.target_ids),
            "before_cursor": mutation.before,
            "after_cursor": mutation.after,
            "mutation_path": list(mutation.path),
            "enemy_action_candidate": candidate.to_json(),
        },
        trace=candidate.source_trace,
    ).to_json()


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


def _has_queue_entries(state: BattleState) -> bool:
    return any(bool(entries) for entries in state.queues.values())


def _unsupported_turn_hooks() -> dict[str, JSONValue]:
    blocked_window_dependency = "requires admitted QueueWindowIR, QueueTargetResolution, queue priority, and source-specific window policy"
    return {
        "duration_tick": {
            "status": "admitted_for_current_scope",
            "scope": "fixed numeric LifeTime with admitted ModifierPhase1End or ActionPhaseEnd",
            "remaining_blocking_dependency": "dynamic/postfix LifeTime and unsupported LifeStepMoment admission",
        },
        "extra_turn": {
            "status": "queue_window_gate",
            "window_family": "extra_turn",
            "blocking_dependency": blocked_window_dependency,
        },
        "ultimate": {
            "status": "admitted_for_manual_queue_current_scope",
            "window_family": "ultimate",
            "remaining_blocking_dependency": "TBGD automatic ultimate interrupt priority admission",
        },
        "follow_up": {
            "status": "queue_window_gate",
            "window_family": "follow_up",
            "blocking_dependency": blocked_window_dependency,
        },
        "counter": {
            "status": "queue_window_gate",
            "window_family": "counter",
            "blocking_dependency": blocked_window_dependency,
        },
        "interrupt": {
            "status": "blocked",
            "window_family": "interrupt",
            "blocking_dependency": blocked_window_dependency,
        },
    }


def _mutation_records(
    record_type: str,
    mutations: tuple[Mutation, ...],
    plan: TurnAdvancePlan,
) -> tuple[dict[str, JSONValue], ...]:
    return tuple(
        SettlementRecord(
            record_type=record_type,
            source=mutation.source,
            mutation_id=mutation.stable_id(),
            process_only=False,
            payload={"turn_advance_plan": plan.to_json(), "mutation_path": list(mutation.path)},
            trace=plan.source_trace,
        ).to_json()
        for mutation in mutations
    )


def select_next_queue_drain_plan(rules: RuleBook, queue: QueueSystem, state: BattleState) -> QueueDrainPlan | None:
    admitted: list[QueueDrainPlan] = []
    blocked: list[QueueDrainPlan] = []
    for queue_name in sorted(state.queues):
        if not state.queues.get(queue_name):
            continue
        resolutions = _resolutions_for_queue(rules, state, queue_name)
        plan = queue.plan_next_drain(state, queue_name, resolutions)
        if plan.ok:
            admitted.append(plan)
        else:
            blocked.append(plan)
    if admitted:
        return sorted(admitted, key=_queue_plan_sort_key)[0]
    if blocked:
        return sorted(blocked, key=_queue_plan_sort_key)[0]
    return None


def queue_plan_requires_external_command(plan: QueueDrainPlan, resolution: QueueResolutionIR) -> bool:
    window_family = str((plan.queue_window or {}).get("window_family") or "")
    if window_family == "ultimate":
        return True
    return _is_extra_turn_action_choice_plan(plan, resolution)


def _queue_plan_sort_key(plan: QueueDrainPlan) -> tuple[int, float, int, str]:
    window = plan.queue_window or {}
    return (
        QUEUE_WINDOW_FAMILY_ORDER.get(str(window.get("window_family") or "unknown"), 999),
        float(plan.priority_value) if plan.priority_value is not None else float("inf"),
        plan.drain_order if plan.drain_order is not None else 0,
        str(plan.queue_entry.get("entry_id") or ""),
    )


def _resolutions_for_queue(rules: RuleBook, state: BattleState, queue_name: str) -> dict[str, QueueResolutionIR]:
    resolutions: dict[str, QueueResolutionIR] = {}
    for entry in state.queues.get(queue_name, ()):
        if not isinstance(entry, dict):
            continue
        intent_id = str(entry.get("queue_intent_id") or "")
        if intent_id.startswith("manual_ultimate:"):
            resolution = _manual_ultimate_resolution_for_entry(state, entry)
            if resolution is not None:
                resolutions[intent_id] = resolution
            continue
        resolution = rules.queue_resolution_for_intent(intent_id)
        if resolution is not None:
            resolutions[intent_id] = resolution
    return resolutions


def _queue_lifecycle_policy_id(plan: QueueDrainPlan) -> str:
    window = plan.queue_window or {}
    policy = window.get("window_policy") if isinstance(window.get("window_policy"), dict) else {}
    return str(policy.get("queue_lifecycle_policy_id") or "")


def _extra_action_policy_id(plan: QueueDrainPlan) -> str:
    window = plan.queue_window or {}
    policy = window.get("window_policy") if isinstance(window.get("window_policy"), dict) else {}
    return str(policy.get("extra_action_policy_id") or "")


def _queue_lifecycle_policy(plan: QueueDrainPlan) -> dict[str, JSONValue]:
    window = plan.queue_window or {}
    policy = window.get("window_policy") if isinstance(window.get("window_policy"), dict) else {}
    lifecycle_basis = policy.get("extra_turn_source_basis")
    return {
        "queue_lifecycle_policy_id": str(policy.get("queue_lifecycle_policy_id") or ""),
        "extra_action_policy_id": str(policy.get("extra_action_policy_id") or ""),
        "lifecycle_policy_admitted": policy.get("lifecycle_policy_admitted") is True,
        "turn_lifecycle_policy": str(policy.get("turn_lifecycle_policy") or ""),
        "duration_tick_policy": str(policy.get("duration_tick_policy") or ""),
        "natural_av_advance": str(policy.get("natural_av_advance") or ""),
        "extra_turn_source_basis": lifecycle_basis if isinstance(lifecycle_basis, dict) else {},
    }


def _extra_action_policy_payload(rules: RuleBook, plan: QueueDrainPlan) -> dict[str, JSONValue]:
    window = plan.queue_window or {}
    policy = window.get("window_policy") if isinstance(window.get("window_policy"), dict) else {}
    policy_id = str(policy.get("extra_action_policy_id") or "")
    item = rules.extra_action_policy(policy_id) if policy_id else None
    return item.to_json() if item is not None else {}


def _resolution_for_drain_plan(rules: RuleBook, state: BattleState, plan: QueueDrainPlan) -> QueueResolutionIR | None:
    if plan.queue_intent_id.startswith("manual_ultimate:"):
        return _manual_ultimate_resolution_for_entry(state, plan.queue_entry)
    return rules.queue_resolution(plan.queue_resolution_id)


def _manual_ultimate_resolution_for_entry(state: BattleState, entry: dict[str, JSONValue]) -> QueueResolutionIR | None:
    intent_id = str(entry.get("queue_intent_id") or "")
    actor_id = str(entry.get("actor_id") or "")
    action_id = str(entry.get("action_or_ability_ref") or "")
    if not intent_id or not actor_id or not action_id:
        return None
    actor = state.units.get(actor_id)
    if actor is None or not actor.template_id:
        return None
    source_trace = entry.get("source_trace") if isinstance(entry.get("source_trace"), dict) else {}
    action_level = entry.get("action_level")
    if not isinstance(action_level, int):
        return None
    source = IRSource(
        source_path="manual_route_input",
        raw_type="ManualQueueResolution",
        raw_id=intent_id,
        evidence={
            "queue_entry": entry,
            "manual_input_source": source_trace.get("manual_input_source", {}),
            "resolution_kind": "manual_ultimate_action_definition",
        },
    )
    return QueueResolutionIR(
        queue_resolution_id=f"manual_queue_resolution:ultimate:{intent_id}",
        queue_intent_id=intent_id,
        action_or_ability_ref=action_id,
        resolved_kind="action_definition",
        resolved_ids={
            "manual_ultimate": True,
            "action_set_candidates": [
                {
                    "combatant_action_set_id": "manual_route_input",
                    "entity_ref": actor.template_id,
                    "skill_index": "",
                    "action_ref": action_id,
                    "action_level": action_level,
                    "source": source.to_json(),
                }
            ],
        },
        source=source,
        coverage_status="executable",
        blocked_reason="",
    )


def _manual_ultimate_dequeue_metadata(rules: RuleBook, plan: QueueDrainPlan) -> dict[str, JSONValue]:
    if not plan.queue_intent_id.startswith("manual_ultimate:"):
        return {}
    source_trace = plan.queue_entry.get("source_trace") if isinstance(plan.queue_entry.get("source_trace"), dict) else {}
    action_id = str(plan.resolved_action_id or plan.queue_entry.get("action_or_ability_ref") or "")
    action_level = plan.queue_entry.get("action_level")
    if not isinstance(action_level, int):
        action_level = plan.resolved_action_level if isinstance(plan.resolved_action_level, int) else 0
    definition = rules.action_definition(action_id, action_level) if action_id else None
    action_event = rules.action_event(action_id, action_level) if action_id else None
    return {
        "manual_ultimate": True,
        "manual_input_source": source_trace.get("manual_input_source", {}),
        "action_id": action_id,
        "action_level": action_level,
        "definition_id": definition.definition_id if definition is not None else "",
        "action_event_id": action_event.action_event_id if action_event is not None else "",
        "source_trace": source_trace,
        "target_resolution": (plan.queue_window or {}).get("target_resolution", plan.queue_entry.get("target_resolution", {})),
    }


def _is_extra_turn_action_choice_plan(plan: QueueDrainPlan, resolution: QueueResolutionIR) -> bool:
    window_family = str((plan.queue_window or {}).get("window_family") or "")
    return window_family == "extra_turn" and resolution.resolved_kind == "extra_turn_action_choice"


def _queue_submission_rejection_reason(reason: str) -> bool:
    return reason in {
        "queue_selectable_command_missing",
        "extra_turn_route_action_choice_missing",
        "extra_turn_route_action_actor_mismatch",
        "manual_ultimate_action_actor_mismatch",
        "manual_ultimate_action_mismatch",
        "manual_ultimate_target_mismatch",
    }


def _queue_entry_resource_policy(plan: QueueDrainPlan) -> dict[str, JSONValue]:
    policy = plan.queue_entry.get("resource_policy")
    return policy if isinstance(policy, dict) else {}


def _phases_for_graph(rules: RuleBook, graph_id: str) -> tuple[AbilityPhaseIR, ...]:
    graph = rules.standalone_ability_graph(graph_id)
    if graph is None:
        return ()
    phases = []
    for phase_id in graph.phase_ids:
        phase = rules.ability_phase(phase_id)
        if phase is not None:
            phases.append(phase)
    return tuple(phases)


def _first_str(value: JSONValue) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                return item
    return ""


def _is_ultimate_definition(attack_type: str, skill_effect: str) -> bool:
    text = f"{attack_type} {skill_effect}".lower()
    return any(token in text for token in ("ultra", "ultimate"))


def _is_basic_or_skill_definition(attack_type: str, skill_effect: str) -> bool:
    text = f"{attack_type} {skill_effect}".lower()
    return any(token in text for token in ("normal", "basic", "bpskill", "skill"))


def _action_kind_allowed(attack_type: str, skill_effect: str, allowed: set[str]) -> bool:
    normalized = {item.lower() for item in allowed}
    if "ultimate" in normalized and _is_ultimate_definition(attack_type, skill_effect):
        return True
    if {"basic", "skill"} & normalized and _is_basic_or_skill_definition(attack_type, skill_effect):
        text = f"{attack_type} {skill_effect}".lower()
        if "basic" in normalized and any(token in text for token in ("normal", "basic")):
            return True
        if "skill" in normalized and any(token in text for token in ("bpskill", "skill")):
            return True
    return False
