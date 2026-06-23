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
from ..rules.ir import AbilityPhaseIR, QueueResolutionIR
from ..rules.rulebook import RuleBook
from .ability import AbilityTaskSystem
from .effect import EffectRegistry
from .queue import QueueDrainPlan, QueueSystem
from .status import StatusSystem
from .timeline import TimelineSystem, TurnAdvancePlan, TurnAdvanceResult


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
        self.status = StatusSystem(rules)
        self.effects = EffectRegistry(self.status)
        self.ability_tasks = AbilityTaskSystem(rules, self.effects, reducer=self.reducer)

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

    def step(self, state: BattleState, command: ActionCommand | None = None) -> SchedulerStepResult:
        """Run one scheduler step.

        The scheduler owns turn lifecycle ordering only. Queue drain and action
        mechanics stay in their existing systems so source audit continues to
        validate the underlying mutation source instead of a scheduler shortcut.
        """
        queue_step = self._try_queue_drain(state)
        if queue_step is not None:
            return _with_scheduler_record(
                queue_step,
                record_type="scheduler_queue_step",
                payload={"scheduler_step": "queue_drain_priority"},
            )

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

        from ..core.executor import CombatExecutor

        parent_metadata = {
            "scheduler_parent": {
                "turn_actor_id": actor_id,
                "turn_transition_action_id": begin_result.transition.transaction.command.action_id,
                "turn_sequence_index": begin_result.after_state.global_flags.get("turn_sequence_index", 0),
                "source": "timeline_scheduler.step",
            }
        }
        scheduled_command = replace(
            command,
            metadata={**command.metadata, **parent_metadata},
        )
        after_action, action_transition = CombatExecutor(self.rules).execute(scheduled_command, begin_result.after_state)
        action_lifecycle = self._apply_status_lifecycle_tick(after_action, "ActionPhaseEnd", actor_id=actor_id)
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
                    },
                ),
                *(begin_result.transition.transaction.settlement.records if begin_result.transition.transaction.settlement else ()),
                *(action_transition.transaction.settlement.records if action_transition.transaction.settlement else ()),
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
        if actor.side == "enemy" and actor.flags.get("ai_policy_admitted") is not True:
            return self._blocked(
                state,
                "timeline:enemy_ai_missing",
                "enemy_ai_missing",
                {"turn_advance_plan": plan.to_json(), "actor_id": actor.unit_id},
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
        )
        return SchedulerStepResult(
            after_begin,
            _transition(
                before_state=state,
                after_state=after_begin,
                action_id="timeline:advance_to_next_turn",
                actor_id=plan.actor_id,
                events=events,
                mutations=mutations,
                records=records,
                coverage={"turn_advance_plan": plan.to_json(), "timeline_rule": rule.to_json()},
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
        result = self.timeline.end_turn(lifecycle.after_state, actor_id, rule, turn_kind="regular")
        after = self.reducer.apply_all(lifecycle.after_state, result.mutations)
        return SchedulerStepResult(
            after,
            _transition(
                before_state=state,
                after_state=after,
                action_id="timeline:end_current_turn",
                actor_id=actor_id,
                events=(*lifecycle.events, *result.events),
                mutations=(*lifecycle.mutations, *result.mutations),
                records=(
                    *lifecycle.records,
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
        records: list[dict[str, JSONValue]] = []
        for unit_id in sorted(tuple(current.units)):
            details = tuple(
                item
                for item in current.units[unit_id].flags.get("status_details", ())
                if isinstance(item, dict)
            )
            for detail in details:
                result = self.status.apply_lifecycle_tick(current, unit_id, detail, life_step_moment)
                records.extend(result.records)
                if result.mutations:
                    mutations.extend(result.mutations)
                    current = self.reducer.apply_all(current, result.mutations)
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
        return _StatusLifecycleSweep(
            after_state=current,
            events=(event,),
            mutations=tuple(mutations),
            records=tuple(records),
        )

    def _try_queue_drain(self, state: BattleState) -> SchedulerStepResult | None:
        plans: list[QueueDrainPlan] = []
        for queue_name in sorted(state.queues):
            resolutions = _resolutions_for_queue(self.rules, state, queue_name)
            if not resolutions:
                continue
            plan = self.queue.plan_next_drain(state, queue_name, resolutions)
            if plan.ok:
                plans.append(plan)
        if not plans:
            return None
        plan = sorted(
            plans,
            key=lambda item: (
                float(item.priority_value) if item.priority_value is not None else float("inf"),
                item.drain_order if item.drain_order is not None else 0,
                str(item.queue_entry.get("entry_id") or ""),
            ),
        )[0]
        resolution = self.rules.queue_resolution(plan.queue_resolution_id)
        if resolution is None:
            return self._blocked(state, "queue:drain", "queue_resolution_missing", {"drain_plan": plan.to_json()})
        dequeue = self.queue.drain_admitted(
            state,
            plan,
            source="queue_system",
            metadata={"queue_operation": "dequeue", "scheduler": "timeline_scheduler"},
        )
        after_dequeue = self.reducer.apply_all(state, (dequeue,))
        records: list[dict[str, JSONValue]] = [
            SettlementRecord(
                record_type="queue_dequeue",
                source="queue_system",
                mutation_id=dequeue.stable_id(),
                process_only=False,
                payload={"drain_plan": plan.to_json(), "queue_resolution": resolution.to_json()},
                trace=plan.source_trace or {},
            ).to_json()
        ]
        mutations: tuple[Mutation, ...] = (dequeue,)
        events: tuple[GameEvent, ...] = (
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
                coverage={"drain_plan": plan.to_json(), "queue_resolution": resolution.to_json()},
            ),
        )

    def _blocked(
        self,
        state: BattleState,
        action_id: str,
        reason: str,
        payload: dict[str, JSONValue],
    ) -> SchedulerStepResult:
        record = SettlementRecord(
            record_type="scheduler_blocked",
            source="timeline_scheduler",
            process_only=True,
            payload={"reason": reason, **payload},
            trace={},
        ).to_json()
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
            ),
            records=(record,),
            coverage={"blocked_reason": reason},
        )
        return SchedulerStepResult(state, transition)


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


def _unsupported_turn_hooks() -> dict[str, JSONValue]:
    return {
        "duration_tick": {
            "status": "admitted_for_current_scope",
            "scope": "fixed numeric LifeTime with admitted ModifierPhase1End or ActionPhaseEnd",
            "remaining_blocking_dependency": "dynamic/postfix LifeTime and unsupported LifeStepMoment admission",
        },
        "extra_turn": {
            "status": "blocked",
            "blocking_dependency": "extra-turn queue/window admission",
        },
        "ultimate": {
            "status": "blocked",
            "blocking_dependency": "ultimate interrupt queue priority admission",
        },
        "interrupt": {
            "status": "blocked",
            "blocking_dependency": "interrupt window admission",
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


def _resolutions_for_queue(rules: RuleBook, state: BattleState, queue_name: str) -> dict[str, QueueResolutionIR]:
    resolutions: dict[str, QueueResolutionIR] = {}
    for entry in state.queues.get(queue_name, ()):
        if not isinstance(entry, dict):
            continue
        intent_id = str(entry.get("queue_intent_id") or "")
        resolution = rules.queue_resolution_for_intent(intent_id)
        if resolution is not None:
            resolutions[intent_id] = resolution
    return resolutions


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
