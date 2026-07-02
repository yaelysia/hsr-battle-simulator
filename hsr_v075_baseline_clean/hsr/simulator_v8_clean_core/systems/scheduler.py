from __future__ import annotations

from dataclasses import dataclass, replace

from ..core.model import (
    ActionCommand,
    ActionSettlement,
    ActionTransaction,
    BattleState,
    BattleTransition,
    GameEvent,
    JSONValue,
    Mutation,
    TargetResolution,
)
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..rules.ir import AbilityPhaseIR, IRSource, QueueResolutionIR
from ..rules.rulebook import RuleBook
from .ability import AbilityTaskSystem
from .effect import EffectRegistry
from .enemy_action import EnemyActionCandidate, EnemyActionSystem
from .event_dispatch import EventDispatchSystem
from .queue import QUEUE_WINDOW_FAMILY_ORDER, QueueDrainPlan, QueueEntry, QueueSystem
from .resource import ResourceSystem
from .status import StatusSystem, status_control_gate_for_actor
from .timeline import TimelineSystem, TurnAdvancePlan, TurnAdvanceResult
from .wave import WaveSystem


@dataclass(frozen=True)
class SchedulerStepResult:
    after_state: BattleState
    transition: BattleTransition
    child_transitions: tuple[BattleTransition, ...] = ()


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
        self.ability_tasks = AbilityTaskSystem(rules, self.effects, reducer=self.reducer)
        self.event_dispatcher = EventDispatchSystem(rules, self.effects, reducer=self.reducer)
        self.wave = WaveSystem(rules)

    def action_availability(self, state: BattleState):
        from .action_availability import ActionAvailabilitySystem

        return ActionAvailabilitySystem(self.rules).view(state)

    def initialize_timeline(
        self,
        state: BattleState,
        *,
        explicit_overrides: tuple[str, ...] = (),
    ) -> SchedulerStepResult:
        rule = self.rules.default_timeline_rule()
        result = self.timeline.initialize_action_values(state, rule, explicit_overrides=explicit_overrides)
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
        target_ids = tuple(target_id for target_id in command.target_ids if target_id in state.units)
        if not target_ids:
            return self._blocked(
                state,
                "queue:manual_ultimate_request",
                "manual_ultimate_target_not_resolved",
                {"command": _command_payload(command), "requested_targets": list(command.target_ids)},
            )
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
            "target_ids": list(target_ids),
            "actor_alias": "ManualRouteActor",
            "target_alias": "ManualRouteTarget",
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
                "resource_rule_id": self.rules.default_ultimate_energy_cost_rule().resource_rule_id,
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
                    target_id=target_ids[0],
                    event_id=f"event:{state.event_index}:manual_ultimate:{command.actor_id}",
                    window="manual_ultimate",
                    process_only=True,
                    payload={"queue_entry": entry.to_json(), "command": _command_payload(command)},
                ),
            ),
            mutations=(mutation,),
            records=records,
            coverage={
                "manual_ultimate": True,
                "queue_entry": entry.to_json(),
                "source_trace": source_trace,
            },
        )
        return SchedulerStepResult(after, transition)

    def step(self, state: BattleState, command: ActionCommand | None = None) -> SchedulerStepResult:
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

        begin_result = self.advance_to_next_turn(state)
        if begin_result.transition.coverage.get("blocked_reason"):
            return begin_result

        actor_id = begin_result.transition.transaction.command.actor_id
        if command is None:
            return _with_scheduler_record(
                begin_result,
                record_type="scheduler_turn_begin_step",
                payload={
                    "scheduler_step": "turn_begin_only",
                    "actor_id": actor_id,
                    "blocking_dependency": "manual_route_command_or_ai_policy",
                },
            )

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

        actor = begin_result.after_state.units.get(actor_id)
        enemy_candidate: EnemyActionCandidate | None = None
        if actor is not None and actor.side == "enemy":
            enemy_candidate = self.enemy_actions.next_candidate(begin_result.after_state, actor_id)
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
            target_blocked_reason = _enemy_action_target_blocked_reason(enemy_candidate, command)
            if target_blocked_reason:
                return self._blocked(
                    state,
                    "scheduler:enemy_action_target_blocked",
                    target_blocked_reason,
                    {
                        "enemy_action_candidate": enemy_candidate.to_json(),
                        "command": _command_payload(command),
                    },
                )

        from ..core.executor import CombatExecutor

        parent_metadata = {
            "scheduler_parent": {
                "turn_actor_id": actor_id,
                "turn_transition_action_id": begin_result.transition.transaction.command.action_id,
                "turn_sequence_index": begin_result.after_state.global_flags.get("turn_sequence_index", 0),
                "source": "timeline_scheduler.step",
            }
        }
        control_gate = status_control_gate_for_actor(begin_result.after_state.units[actor_id])
        if control_gate is not None:
            return self._blocked(
                state,
                "scheduler:status_control_gate",
                str(control_gate.get("reason") or "status_control_gate"),
                {
                    "control_gate": control_gate,
                    "command": _command_payload(command),
                    "turn_begin_candidate": begin_result.transition.coverage,
                },
            )
        scheduled_command = replace(
            command,
            metadata={**command.metadata, **parent_metadata},
        )
        after_action, action_transition = CombatExecutor(self.rules).execute(scheduled_command, begin_result.after_state)
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
        if _has_queue_entries(after_action_for_lifecycle):
            pending_mutation = self._pending_turn_end_mutation(after_action_for_lifecycle, actor_id, action_transition.transaction.command.action_id)
            after_pending = self.reducer.apply_all(after_action_for_lifecycle, (pending_mutation,))
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
                            "turn_begin_action_id": begin_result.transition.transaction.command.action_id,
                            "child_action_id": action_transition.transaction.command.action_id,
                        "turn_end": "deferred_until_pending_queue_drained",
                        "enemy_action_candidate": enemy_candidate.to_json() if enemy_candidate is not None else {},
                        "enemy_action_cursor_advanced": cursor_mutation is not None,
                    },
                ),
                *(begin_result.transition.transaction.settlement.records if begin_result.transition.transaction.settlement else ()),
                *(action_transition.transaction.settlement.records if action_transition.transaction.settlement else ()),
                *cursor_records,
                pending_record,
            ),
                events=(
                    *begin_result.transition.transaction.events,
                    GameEvent(
                        "scheduler.action.before",
                        source_id=actor_id,
                        event_id=f"event:{begin_result.after_state.event_index}:scheduler_action_before:{actor_id}",
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
                    *begin_result.transition.transaction.mutations,
                    *action_transition.transaction.mutations,
                    *((cursor_mutation,) if cursor_mutation is not None else ()),
                    pending_mutation,
                ),
                target_resolution=action_transition.target_resolution,
                coverage={
                    "scheduler_step": "manual_action_turn_lifecycle_deferred_for_queue",
                    "turn_begin": begin_result.transition.coverage,
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
                    "unsupported_hooks": _unsupported_turn_hooks(),
                },
            )
            return SchedulerStepResult(
                after_pending,
                combined,
                child_transitions=(begin_result.transition, action_transition),
            )
        action_lifecycle = self._apply_status_lifecycle_tick(after_action_for_lifecycle, "ActionPhaseEnd", actor_id=actor_id)
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
                        "turn_begin_action_id": begin_result.transition.transaction.command.action_id,
                        "child_action_id": action_transition.transaction.command.action_id,
                        "action_lifecycle_hook": "ActionPhaseEnd",
                        "turn_end_action_id": end_result.transition.transaction.command.action_id,
                        "enemy_action_candidate": enemy_candidate.to_json() if enemy_candidate is not None else {},
                        "enemy_action_cursor_advanced": cursor_mutation is not None,
                    },
                ),
                *(begin_result.transition.transaction.settlement.records if begin_result.transition.transaction.settlement else ()),
                *(action_transition.transaction.settlement.records if action_transition.transaction.settlement else ()),
                *cursor_records,
                *action_lifecycle.records,
                *(end_result.transition.transaction.settlement.records if end_result.transition.transaction.settlement else ()),
            ),
            events=(
                *begin_result.transition.transaction.events,
                GameEvent(
                    "scheduler.action.before",
                    source_id=actor_id,
                    event_id=f"event:{begin_result.after_state.event_index}:scheduler_action_before:{actor_id}",
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
                *action_lifecycle.events,
                *end_result.transition.transaction.events,
            ),
            mutations=(
                *begin_result.transition.transaction.mutations,
                *action_transition.transaction.mutations,
                *((cursor_mutation,) if cursor_mutation is not None else ()),
                *action_lifecycle.mutations,
                *end_result.transition.transaction.mutations,
            ),
            target_resolution=action_transition.target_resolution,
            coverage={
                "scheduler_step": "manual_action_turn_lifecycle",
                "turn_begin": begin_result.transition.coverage,
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
                "unsupported_hooks": _unsupported_turn_hooks(),
            },
        )
        return SchedulerStepResult(
            end_result.after_state,
            combined,
            child_transitions=(begin_result.transition, action_transition, end_result.transition),
        )

    def advance_to_next_turn(self, state: BattleState) -> SchedulerStepResult:
        queue_step = self._try_queue_drain(state)
        if queue_step is not None:
            return queue_step

        rule = self.rules.default_timeline_rule()
        plan = self.timeline.plan_next_actor(state, rule)
        if not plan.ok:
            return self._blocked(state, "timeline:advance", plan.blocked_reason, {"turn_advance_plan": plan.to_json()})

        actor = state.units[plan.actor_id]
        enemy_candidate = None
        if actor.side == "enemy":
            enemy_candidate = self.enemy_actions.next_candidate(state, actor.unit_id)
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

        advance = self.timeline.advance_to_next_actor(state, plan)
        after_advance = self.reducer.apply_all(state, advance.mutations)
        begin = self.timeline.begin_turn(after_advance, plan, turn_kind="regular")
        after_begin = self.reducer.apply_all(after_advance, begin.mutations)
        mutations = (*advance.mutations, *begin.mutations)
        events = (*advance.events, *begin.events)
        records = (
            *_mutation_records("timeline_advance", advance.mutations, plan),
            *_mutation_records("turn_begin", begin.mutations, plan),
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
            after_begin,
            _transition(
                before_state=state,
                after_state=after_begin,
                action_id="timeline:advance_to_next_turn",
                actor_id=plan.actor_id,
                events=(*events, *candidate_events),
                mutations=mutations,
                records=records,
                coverage={
                    "turn_advance_plan": plan.to_json(),
                    "timeline_rule": rule.to_json(),
                    "enemy_action_candidate": enemy_candidate.to_json() if enemy_candidate is not None else {},
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
        rule = self.rules.default_timeline_rule()
        lifecycle = self._apply_status_lifecycle_tick(state, "ModifierPhase1End", actor_id=actor_id)
        turn_end_dispatch_enabled = lifecycle.after_state.global_flags.get("admit_turn_end_listener_dispatch") is True
        if turn_end_dispatch_enabled:
            turn_end_event = GameEvent(
                "turn.end",
                source_id=actor_id,
                event_id=f"event:{lifecycle.after_state.event_index}:turn_end_dispatch:{actor_id}",
                window="turn.end",
                process_only=True,
                payload={
                    "actor_id": actor_id,
                    "listener_scope": "global_listener",
                    "life_step_moment": "ModifierPhase1End",
                },
            )
            dispatch = self.event_dispatcher.dispatch_event(lifecycle.after_state, event=turn_end_event)
        else:
            dispatch = self.event_dispatcher.dispatch_blocked(
                lifecycle.after_state,
                event=GameEvent(
                    "turn.end",
                    source_id=actor_id,
                    event_id=f"event:{lifecycle.after_state.event_index}:turn_end_dispatch_blocked:{actor_id}",
                    window="turn.end",
                    process_only=True,
                    payload={
                        "actor_id": actor_id,
                        "listener_scope": "global_listener",
                        "life_step_moment": "ModifierPhase1End",
                    },
                ),
                listener_kind="listener_dispatch",
                scope="global_listener",
                reason="turn_end_listener_dispatch_requires_explicit_admission",
                metadata={"actor_id": actor_id, "life_step_moment": "ModifierPhase1End"},
            )
        result = self.timeline.end_turn(dispatch.after_state, actor_id, rule, turn_kind="regular")
        after = self.reducer.apply_all(dispatch.after_state, result.mutations)
        return SchedulerStepResult(
            after,
            _transition(
                before_state=state,
                after_state=after,
                action_id="timeline:end_current_turn",
                actor_id=actor_id,
                events=(*lifecycle.events, *dispatch.events, *result.events),
                mutations=(*lifecycle.mutations, *dispatch.mutations, *result.mutations),
                records=(
                    *lifecycle.records,
                    *dispatch.records,
                    *_mutation_records("turn_end", result.mutations, result.plan),
                ),
                coverage={
                    "timeline_rule": rule.to_json(),
                    "turn_advance_plan": result.plan.to_json(),
                    "status_lifecycle": {
                        "life_step_moment": "ModifierPhase1End",
                        "mutation_count": len(lifecycle.mutations),
                    },
                },
            ),
        )

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
                phase1_event = _status_phase1_lifecycle_event(current, unit_id, detail, life_step_moment)
                if phase1_event is not None:
                    dispatch = self.event_dispatcher.dispatch_status_callback(
                        current,
                        event=phase1_event,
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
                        continue
                    detail = refreshed_detail
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
                    coverage={"wave_transition": plan.to_json(), "blocked_reason": plan.blocked_reason},
                ),
            )
        after = self.reducer.apply_all(state, result.mutations)
        return SchedulerStepResult(
            after,
            _transition(
                before_state=state,
                after_state=after,
                action_id="wave:transition",
                actor_id="wave_system",
                events=result.events,
                mutations=result.mutations,
                records=result.records,
                coverage={"wave_transition": plan.to_json(), "scheduler_step": "wave_transition"},
            ),
        )

    def _try_queue_drain(self, state: BattleState, command: ActionCommand | None = None) -> SchedulerStepResult | None:
        plan = select_next_queue_drain_plan(self.rules, self.queue, state)
        if plan is None:
            return None
        if not plan.ok:
            return self._blocked(
                state,
                "queue:drain",
                plan.blocked_reason or "queue_drain_blocked",
                {"drain_plan": plan.to_json()},
            )
        resolution = _resolution_for_drain_plan(self.rules, state, plan)
        if resolution is None:
            return self._blocked(state, "queue:drain", "queue_resolution_missing", {"drain_plan": plan.to_json()})
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
            after_state = ability_result.after_state
            mutations = (*mutations, *ability_result.mutations)
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
            after_action, action_transition = CombatExecutor(self.rules).execute(queue_command, after_dequeue)
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
        return SchedulerStepResult(
            after_state,
            _transition(
                before_state=state,
                after_state=after_state,
                action_id="queue:drain_admitted",
                actor_id=str(plan.queue_entry.get("actor_id") or ""),
                events=events,
                mutations=mutations,
                records=tuple(records),
                coverage={
                    "drain_plan": plan.to_json(),
                    "queue_resolution": resolution.to_json(),
                    "queue_window_plan": plan.queue_window or {},
                },
            ),
            child_transitions=child_transitions,
        )

    def _queue_action_preflight_reason(self, state: BattleState, plan: QueueDrainPlan, *, command: ActionCommand | None = None) -> str:
        actor_id = str(plan.queue_entry.get("actor_id") or "")
        if not actor_id or actor_id not in state.units:
            return "queue_action_actor_missing"
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
                selected_targets = tuple(target_id for target_id in command.target_ids if target_id in state.units)
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
        if not selected_targets:
            return "queue_action_target_missing"
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
            op="set",
            path=("global_flags", "pending_turn_end"),
            before=state.global_flags.get("pending_turn_end"),
            after=None,
            reason="clear deferred natural turn end marker",
            source="timeline_system",
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
            coverage={
                "scheduler_step": "complete_deferred_turn_lifecycle",
                "pending_turn_end": pending_turn_end,
                "action_lifecycle": {"life_step_moment": "ActionPhaseEnd", "mutation_count": len(action_lifecycle.mutations)},
                "turn_end": end_result.transition.coverage,
            },
        )
        return SchedulerStepResult(after_clear, combined, child_transitions=(end_result.transition,))

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
            coverage={"blocked_reason": reason},
        )
        return SchedulerStepResult(state, transition)


def _status_phase1_lifecycle_event(
    state: BattleState,
    unit_id: str,
    detail: dict[str, JSONValue],
    life_step_moment: str,
) -> GameEvent | None:
    if life_step_moment != "ModifierPhase1End":
        return None
    trigger_ids_by_event = detail.get("trigger_ids_by_event")
    trigger_ids = trigger_ids_by_event.get("OnPhase1") if isinstance(trigger_ids_by_event, dict) else None
    if not isinstance(trigger_ids, list) or not any(isinstance(item, str) and item for item in trigger_ids):
        return None
    source_trace = detail.get("source_trace")
    if not isinstance(source_trace, dict) or not source_trace:
        return None
    modifier_name = str(detail.get("modifier_name") or "")
    status_id = str(detail.get("status_id") or "")
    status_instance_id = str(detail.get("instance_id") or "")
    caster_id = str(detail.get("caster_id") or unit_id)
    return GameEvent(
        "status.lifecycle",
        source_id=caster_id,
        target_id=unit_id,
        event_id=(
            f"event:{state.event_index}:status_lifecycle:OnPhase1:"
            f"{unit_id}:{status_id.replace(':', '_')}:{status_instance_id}"
        ),
        window="OnPhase1",
        process_only=True,
        payload={
            "callback_event": "OnPhase1",
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
    coverage: dict[str, JSONValue] | None = None,
) -> BattleTransition:
    command = ActionCommand(actor_id=actor_id, action_id=action_id, action_level=0, metadata={"scheduler": "timeline"})
    settlement = ActionSettlement(action_id=action_id, actor_id=actor_id, target_ids=(), records=records)
    return BattleTransition(
        transaction=ActionTransaction(
            command=command,
            before=before_state.snapshot(),
            events=events,
            mutations=mutations,
            trigger_windows=(),
            settlement=settlement,
        ),
        after=after_state.snapshot(),
        target_resolution=TargetResolution(reason="scheduler_no_target", source="timeline_scheduler"),
        coverage=coverage or {},
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
    coverage: dict[str, JSONValue],
) -> BattleTransition:
    action_id = "scheduler:step"
    command = ActionCommand(
        actor_id=actor_id,
        action_id=action_id,
        action_level=0,
        metadata={"scheduler": "timeline", "scheduler_step": coverage.get("scheduler_step", "")},
    )
    settlement = ActionSettlement(action_id=action_id, actor_id=actor_id, target_ids=(), records=records)
    return BattleTransition(
        transaction=ActionTransaction(
            command=command,
            before=before_state.snapshot(),
            events=events,
            mutations=mutations,
            trigger_windows=(),
            settlement=settlement,
        ),
        after=after_state.snapshot(),
        target_resolution=target_resolution,
        coverage=coverage,
    )


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
        coverage={**result.transition.coverage, **payload},
        contract_validation=result.transition.contract_validation,
    )
    return SchedulerStepResult(result.after_state, replacement, result.child_transitions)


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


def _enemy_action_target_blocked_reason(candidate: EnemyActionCandidate, command: ActionCommand) -> str:
    requested = tuple(command.target_ids)
    selectable = set(candidate.selectable_target_ids)
    auto_targets = set(candidate.auto_target_ids)
    if auto_targets:
        if requested and not set(requested).issubset(auto_targets):
            return "enemy_action_target_not_in_auto_target_group"
        return ""
    if not requested:
        return "enemy_action_target_missing"
    if not set(requested).issubset(selectable):
        return "enemy_action_target_not_in_candidate"
    return ""


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
    command = _manual_ultimate_command_payload(source_trace)
    action_level = command.get("action_level")
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
    command = _manual_ultimate_command_payload(source_trace)
    action_id = str(command.get("action_id") or plan.resolved_action_id or plan.queue_entry.get("action_or_ability_ref") or "")
    action_level = command.get("action_level")
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


def _manual_ultimate_command_payload(source_trace: dict[str, JSONValue]) -> dict[str, JSONValue]:
    manual_source = source_trace.get("manual_input_source") if isinstance(source_trace.get("manual_input_source"), dict) else {}
    evidence = manual_source.get("evidence") if isinstance(manual_source.get("evidence"), dict) else {}
    command = evidence.get("command") if isinstance(evidence.get("command"), dict) else {}
    return command


def _is_extra_turn_action_choice_plan(plan: QueueDrainPlan, resolution: QueueResolutionIR) -> bool:
    window_family = str((plan.queue_window or {}).get("window_family") or "")
    return window_family == "extra_turn" and resolution.resolved_kind == "extra_turn_action_choice"


def _queue_entry_resource_policy(plan: QueueDrainPlan) -> dict[str, JSONValue]:
    source_trace = plan.queue_entry.get("source_trace") if isinstance(plan.queue_entry.get("source_trace"), dict) else {}
    policy = source_trace.get("queue_intent_resource_policy") if isinstance(source_trace, dict) else None
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
