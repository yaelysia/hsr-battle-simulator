from __future__ import annotations

from dataclasses import dataclass

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
        result = self.timeline.end_turn(state, actor_id, rule, turn_kind="regular")
        after = self.reducer.apply_all(state, result.mutations)
        return SchedulerStepResult(
            after,
            _transition(
                before_state=state,
                after_state=after,
                action_id="timeline:end_current_turn",
                actor_id=actor_id,
                events=result.events,
                mutations=result.mutations,
                records=_mutation_records("turn_end", result.mutations, result.plan),
                coverage={"timeline_rule": rule.to_json(), "turn_advance_plan": result.plan.to_json()},
            ),
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
