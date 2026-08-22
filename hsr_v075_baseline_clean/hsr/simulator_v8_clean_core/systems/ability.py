from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal, cast

from ..core.model import ActionCommand, BattleState, GameEvent, JSONValue, Mutation, RNGEvent, TargetResolution
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..core.transition_outcome import ExecutionNodeResult
from ..rules.evaluator import NumericEvaluationContext, RuleEvaluator
from ..rules.ir import AbilityPhaseIR, AbilityTaskIR, ActionDefinitionIR, IRSource
from ..rules.rulebook import RuleBook
from ..rules.task_graph import TaskGraphIR, TaskGraphNumericDefinitionIR
from .damage import DamagePacket, DamageSourceFrame, DamageSystem, DamageWindowLedger
from .dynamic_values import (
    binding_source_from_store,
    character_skill_param_binding_sources,
    status_binding_sources,
    store_from_state,
)
from .effect import EffectExecutionContext, EffectRegistry
from .event_dispatch import EventDispatchResult, EventDispatchSystem
from .action_event_contract import (
    admitted_action_condition_fact_provider,
    damage_listener_window_event,
)
from .summon import SummonSystem
from .toughness import ToughnessPacket, ToughnessSystem
from .ability_task_contract import (
    ability_task_runtime_blocked_reason,
    is_process_only_ability_task,
)
from .target import TargetSystem
from .task_graph import (
    TaskGraphBranchResult,
    TaskGraphConditionResult,
    TaskGraphContinuation,
    TaskGraphCountResult,
    TaskGraphExecutionContext,
    TaskGraphExecutionHooks,
    TaskGraphExecutor,
    TaskGraphGraphResult,
    TaskGraphHookRequest,
    TaskGraphLeafResult,
    TaskGraphNodeProjection,
    TaskGraphSettlementRecord,
    TaskGraphTargetResult,
)
from .unit_relation import TargetEvaluationContext, committed_turn_owner_id


_STANDALONE_CALLBACK_ORDER = ("OnStart", "OnAttack", "OnHit", "OnEnd")


@dataclass(frozen=True)
class AbilityTaskExecutionResult:
    after_state: BattleState
    mutations: tuple[Mutation, ...] = ()
    events: tuple[GameEvent, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    task_records: tuple[dict[str, JSONValue], ...] = ()
    node_results: tuple[ExecutionNodeResult, ...] = ()


@dataclass(frozen=True)
class StandaloneAbilityInvocation:
    graph_id: str
    actor_id: str
    target_ids: tuple[str, ...]
    queue_name: str
    queue_entry_id: str
    queue_intent_id: str
    queue_resolution_id: str

    def __post_init__(self) -> None:
        if type(self) is not StandaloneAbilityInvocation:
            raise TypeError("standalone ability invocation must not be subclassed")
        values = (
            self.graph_id,
            self.actor_id,
            self.queue_name,
            self.queue_entry_id,
            self.queue_intent_id,
            self.queue_resolution_id,
        )
        if any(type(value) is not str or not value for value in values):
            raise ValueError("standalone ability invocation identity is incomplete")
        targets = tuple(self.target_ids)
        if any(type(value) is not str or not value for value in targets):
            raise ValueError("standalone ability invocation targets are invalid")
        if len(targets) != len(set(targets)):
            raise ValueError("standalone ability invocation targets are duplicated")
        object.__setattr__(self, "target_ids", targets)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "graph_id": self.graph_id,
            "actor_id": self.actor_id,
            "target_ids": list(self.target_ids),
            "queue_name": self.queue_name,
            "queue_entry_id": self.queue_entry_id,
            "queue_intent_id": self.queue_intent_id,
            "queue_resolution_id": self.queue_resolution_id,
        }


@dataclass(frozen=True)
class _FormalAbilityInvocation:
    invocation_kind: Literal["action", "queue_standalone"]
    actor_id: str
    ability_id: str
    ability_level: int
    target_resolution: TargetResolution
    action_command: ActionCommand | None = None
    action_definition: ActionDefinitionIR | None = None
    standalone: StandaloneAbilityInvocation | None = None
    execution_path: str = ""
    iteration_index: int | None = None

    def __post_init__(self) -> None:
        if type(self) is not _FormalAbilityInvocation:
            raise TypeError("formal ability invocation must not be subclassed")
        if (
            type(self.actor_id) is not str
            or not self.actor_id
            or type(self.ability_id) is not str
            or not self.ability_id
            or type(self.ability_level) is not int
            or self.ability_level < 0
            or type(self.target_resolution) is not TargetResolution
        ):
            raise ValueError("formal ability invocation identity is invalid")
        if self.invocation_kind == "action":
            if (
                type(self.action_command) is not ActionCommand
                or type(self.action_definition) is not ActionDefinitionIR
                or self.standalone is not None
                or self.action_command.actor_id != self.actor_id
                or self.action_command.action_id != self.ability_id
                or self.action_command.action_level != self.ability_level
                or self.action_definition.action_id != self.ability_id
                or self.action_definition.level != self.ability_level
            ):
                raise ValueError("formal action invocation is inconsistent")
        elif self.invocation_kind == "queue_standalone":
            if (
                self.action_command is not None
                or self.action_definition is not None
                or type(self.standalone) is not StandaloneAbilityInvocation
                or self.standalone.actor_id != self.actor_id
            ):
                raise ValueError("formal standalone invocation is inconsistent")
        else:
            raise ValueError("formal ability invocation kind is invalid")


class AbilityTaskSystem:
    """Executes Canonical IR ability tasks conservatively."""

    def __init__(
        self,
        rules: RuleBook,
        effect_registry: EffectRegistry,
        evaluator: RuleEvaluator | None = None,
        reducer: MutationReducer | None = None,
        damage: DamageSystem | None = None,
        event_dispatcher: EventDispatchSystem | None = None,
    ) -> None:
        self.rules = rules
        self.effect_registry = effect_registry
        self.evaluator = evaluator or RuleEvaluator()
        self.reducer = reducer or MutationReducer()
        self.damage = damage or DamageSystem(rules)
        self.event_dispatcher = event_dispatcher
        self.toughness = ToughnessSystem(rules)
        self.summons = SummonSystem(rules)
        self.targets = TargetSystem(rules)
        self.task_graph_executor = TaskGraphExecutor()

    def execute_callback(
        self,
        state: BattleState,
        *,
        phases: tuple[AbilityPhaseIR, ...],
        callback_kind: str,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        target_resolution: TargetResolution,
    ) -> AbilityTaskExecutionResult:
        roles = {phase.invocation_role for phase in phases}
        formal_roles = {"action_root", "nested_only"}
        formal_invocation = None
        if roles.intersection(
            {*formal_roles, "standalone_root", "unbound_definition"}
        ):
            if (
                command.action_id != action_definition.action_id
                or command.action_level != action_definition.level
            ):
                return self._formal_action_input_blocked(
                    state,
                    callback_kind,
                    command,
                    "ability_action_definition_identity_mismatch",
                )
            formal_invocation = _FormalAbilityInvocation(
                "action",
                command.actor_id,
                command.action_id,
                command.action_level,
                target_resolution,
                action_command=command,
                action_definition=action_definition,
            )
        if "action_root" in roles:
            invalid_roles = roles - formal_roles - {"non_gameplay_noop"}
            if invalid_roles:
                return self._formal_callback_blocked(
                    state,
                    callback_kind,
                    cast(_FormalAbilityInvocation, formal_invocation),
                    f"ability_action_invocation_roles_mixed:{','.join(sorted(invalid_roles))}",
                )
            return self._execute_formal_action_callback(
                state,
                phases=phases,
                callback_kind=callback_kind,
                command=command,
                action_definition=action_definition,
                target_resolution=target_resolution,
            )
        if "standalone_root" in roles:
            return self._formal_callback_blocked(
                state,
                callback_kind,
                cast(_FormalAbilityInvocation, formal_invocation),
                "standalone_ability_requires_admitted_queue_invocation",
            )
        if "nested_only" in roles and not roles.intersection(
            {"standalone_root", "external_legacy"}
        ):
            return self._formal_callback_blocked(
                state,
                callback_kind,
                cast(_FormalAbilityInvocation, formal_invocation),
                "nested_ability_phase_cannot_be_invoked_as_root",
            )
        if "unbound_definition" in roles:
            return self._formal_callback_blocked(
                state,
                callback_kind,
                cast(_FormalAbilityInvocation, formal_invocation),
                "unbound_ability_definition_cannot_be_invoked",
            )
        return self._execute_legacy_callback(
            state,
            phases=phases,
            callback_kind=callback_kind,
            command=command,
            action_definition=action_definition,
            target_resolution=target_resolution,
        )

    def _execute_legacy_callback(
        self,
        state: BattleState,
        *,
        phases: tuple[AbilityPhaseIR, ...],
        callback_kind: str,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        target_resolution: TargetResolution,
    ) -> AbilityTaskExecutionResult:
        current = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        records: list[dict[str, JSONValue]] = []
        task_records: list[dict[str, JSONValue]] = []
        primary_target = target_resolution.selected[0] if target_resolution.selected else None

        for phase in phases:
            tasks = {
                task.task_id: task
                for task in self.rules.ability_tasks_for_phase(phase.phase_id)
                if task.callback_kind == callback_kind
            }
            roots = tuple(
                sorted(
                    (task for task in tasks.values() if not task.parent_task_id),
                    key=lambda item: (item.task_index, item.task_path, item.task_id),
                )
            )
            for task in roots:
                current, task_mutations, task_events, task_rng_events, task_records_for_root = self._execute_task(
                    current,
                    task,
                    tasks,
                    command=command,
                    action_definition=action_definition,
                    primary_target=primary_target,
                    target_resolution=target_resolution,
                )
                mutations.extend(task_mutations)
                events.extend(task_events)
                rng_events.extend(task_rng_events)
                records.extend(task_records_for_root)
                task_records.extend(
                    record.get("payload", {})
                    for record in task_records_for_root
                    if isinstance(record, dict) and record.get("record_type") == "ability_task"
                )

        if task_records:
            events.append(
                GameEvent(
                    event_type="ability_task.callback",
                    source_id=command.actor_id,
                    target_id=primary_target,
                    event_id=f"event:{state.event_index}:ability_task:{callback_kind}",
                    window=callback_kind,
                    process_only=True,
                    payload={
                        "callback_kind": callback_kind,
                        "task_record_count": len(task_records),
                        "mutation_count": len(mutations),
                    },
                )
            )
        return AbilityTaskExecutionResult(
            after_state=current,
            mutations=tuple(mutations),
            events=tuple(events),
            rng_events=tuple(rng_events),
            records=tuple(records),
            task_records=tuple(task_records),
            node_results=_node_results_from_task_records(task_records),
        )

    def _execute_formal_action_callback(
        self,
        state: BattleState,
        *,
        phases: tuple[AbilityPhaseIR, ...],
        callback_kind: str,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        target_resolution: TargetResolution,
    ) -> AbilityTaskExecutionResult:
        invocation = _FormalAbilityInvocation(
            "action",
            command.actor_id,
            command.action_id,
            command.action_level,
            target_resolution,
            action_command=command,
            action_definition=action_definition,
        )
        roots = tuple(phase for phase in phases if phase.invocation_role == "action_root")
        if not roots:
            return self._formal_callback_blocked(
                state,
                callback_kind,
                invocation,
                "ability_action_root_missing",
            )
        if any(
            phase.action_id != command.action_id
            or phase.level != command.action_level
            or phase.action_id != action_definition.action_id
            or phase.level != action_definition.level
            for phase in phases
            if phase.invocation_role in {"action_root", "nested_only"}
        ):
            return self._formal_callback_blocked(
                state,
                callback_kind,
                invocation,
                "ability_action_phase_identity_mismatch",
            )

        selected_roots = tuple(
            phase
            for phase in roots
            if any(
                task.callback_kind == callback_kind
                for task in self.rules.ability_tasks_for_phase(phase.phase_id)
            )
        )
        if not selected_roots:
            return AbilityTaskExecutionResult(after_state=state)

        return self._execute_formal_entries(
            state,
            entries=tuple((phase, callback_kind) for phase in selected_roots),
            invocation=invocation,
        )

    def _execute_formal_entries(
        self,
        state: BattleState,
        *,
        entries: tuple[tuple[AbilityPhaseIR, str], ...],
        invocation: _FormalAbilityInvocation,
    ) -> AbilityTaskExecutionResult:
        if not entries:
            return AbilityTaskExecutionResult(after_state=state)

        current = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        records: list[dict[str, JSONValue]] = []
        task_records: list[dict[str, JSONValue]] = []
        node_results: list[ExecutionNodeResult] = []
        mutation_ids: set[str] = set()
        event_ids: set[str] = set()
        rng_event_ids: set[str] = set()
        for ordinal, (phase, callback_kind) in enumerate(entries):
            entry_result = self.rules.query_task_graph_entry(
                "ability_phase_callback",
                phase.phase_id,
                callback_kind,
            )
            if entry_result.status != "resolved":
                return self._formal_callback_blocked(
                    state,
                    callback_kind,
                    invocation,
                    entry_result.blocked_reason or "ability_action_task_graph_entry_missing",
                    node_results=tuple(node_results),
                )
            entry = entry_result.value
            if (
                entry is None
                or entry.owner_id != phase.phase_id
                or entry.callback_kind != callback_kind
                or entry.entry_kind != "ability_phase_callback"
            ):
                return self._formal_callback_blocked(
                    state,
                    callback_kind,
                    invocation,
                    "ability_action_task_graph_entry_identity_mismatch",
                    node_results=tuple(node_results),
                )
            graph_result = self.rules.query_task_graph(entry.graph_id)
            graph = graph_result.value
            if (
                graph_result.status != "resolved"
                or type(graph) is not TaskGraphIR
                or graph.entry_id != entry.entry_id
                or graph.owner_id != phase.phase_id
                or graph.callback_kind != callback_kind
            ):
                return self._formal_callback_blocked(
                    state,
                    callback_kind,
                    invocation,
                    graph_result.blocked_reason
                    or "ability_action_task_graph_identity_mismatch",
                    node_results=tuple(node_results),
                )
            invocation_id = (
                f"ability_{invocation.invocation_kind}:{state.event_index}:"
                f"{invocation.actor_id}:{invocation.ability_id}:"
                f"{invocation.ability_level}:{callback_kind}:"
                f"{ordinal}:{phase.phase_id}"
            )
            context_values: dict[str, JSONValue] = {
                "invocation_kind": invocation.invocation_kind,
                "actor_id": invocation.actor_id,
                "ability_id": invocation.ability_id,
                "ability_level": invocation.ability_level,
                "callback_kind": callback_kind,
                "primary_target_id": invocation.target_resolution.primary,
                "selected_target_ids": list(invocation.target_resolution.selected),
            }
            if invocation.standalone is not None:
                context_values.update(invocation.standalone.to_json())
            execution = self.task_graph_executor.execute(
                current,
                graph,
                TaskGraphExecutionContext(
                    invocation_id,
                    context_values,
                ),
                self._formal_task_graph_hooks(
                    invocation=invocation,
                ),
            )
            node_results.extend(execution.outcome.node_results)
            if not execution.ok:
                return self._formal_callback_blocked(
                    state,
                    callback_kind,
                    invocation,
                    execution.errors[0]
                    if execution.errors
                    else "ability_action_task_graph_execution_blocked",
                    node_results=tuple(node_results),
                )
            new_mutation_ids = tuple(item.stable_id() for item in execution.mutations)
            new_event_ids = tuple(
                cast(str, item.to_json()["event_id"]) for item in execution.events
            )
            new_rng_event_ids = tuple(
                cast(str, item.to_json()["event_id"]) for item in execution.rng_events
            )
            duplicate_channel = next(
                (
                    channel
                    for channel, values, seen in (
                        ("mutation", new_mutation_ids, mutation_ids),
                        ("event", new_event_ids, event_ids),
                        ("rng", new_rng_event_ids, rng_event_ids),
                    )
                    if any(value in seen for value in values)
                ),
                "",
            )
            if duplicate_channel:
                return self._formal_callback_blocked(
                    state,
                    callback_kind,
                    invocation,
                    f"ability_action_task_graph_duplicate_{duplicate_channel}_identity",
                    node_results=tuple(node_results),
                )
            mutation_ids.update(new_mutation_ids)
            event_ids.update(new_event_ids)
            rng_event_ids.update(new_rng_event_ids)
            current = execution.after_state
            mutations.extend(execution.mutations)
            events.extend(execution.events)
            rng_events.extend(execution.rng_events)
            graph_records = tuple(item.to_json() for item in execution.settlement_records)
            records.extend(graph_records)
            task_records.extend(
                cast(dict[str, JSONValue], record["payload"])
                for record in graph_records
                if record.get("record_type") == "ability_task"
                and isinstance(record.get("payload"), dict)
            )
        return AbilityTaskExecutionResult(
            after_state=current,
            mutations=tuple(mutations),
            events=tuple(events),
            rng_events=tuple(rng_events),
            records=tuple(records),
            task_records=tuple(task_records),
            node_results=tuple(node_results),
        )

    def _formal_task_graph_hooks(
        self,
        *,
        invocation: _FormalAbilityInvocation,
    ) -> TaskGraphExecutionHooks:
        return TaskGraphExecutionHooks(
            leaf=lambda request, state: self._execute_formal_leaf(
                request,
                state,
                invocation=invocation,
            ),
            condition=lambda request, state: self._evaluate_formal_condition(
                request,
                state,
                invocation=invocation,
            ),
            branch=lambda _request, _state: TaskGraphBranchResult(
                "blocked",
                blocked_reason="ability_task_graph_branch_domain_not_admitted",
            ),
            count=lambda request, definition, state: self._resolve_formal_count(
                request,
                definition,
                state,
                invocation=invocation,
            ),
            targets=lambda request, state: self._resolve_formal_targets(
                request,
                state,
                invocation=invocation,
            ),
            graph=lambda request, state: self._resolve_formal_nested_graph(
                request,
                state,
            ),
        )

    def _execute_formal_leaf(
        self,
        request: TaskGraphHookRequest,
        state: BattleState,
        *,
        invocation: _FormalAbilityInvocation,
    ) -> TaskGraphLeafResult:
        task, reason = self._formal_task_for_request(request)
        if task is None:
            return TaskGraphLeafResult("blocked", outcome_kind="", blocked_reason=reason)
        if not is_process_only_ability_task(task):
            unresolved = tuple(
                reference
                for reference in request.references
                if reference.resolution_status != "resolved"
            )
            if unresolved:
                return TaskGraphLeafResult(
                    "blocked",
                    outcome_kind="",
                    blocked_reason=unresolved[0].blocked_reason
                    or "ability_task_graph_leaf_reference_not_resolved",
                )
        scoped_resolution = _task_graph_target_resolution(
            request, invocation.target_resolution
        )
        scoped_invocation = replace(
            invocation,
            target_resolution=scoped_resolution,
            execution_path=_task_graph_execution_path(request),
            iteration_index=request.iteration_index,
        )
        continuation = TaskGraphContinuation.from_hook_request(request)
        _, mutations, events, rng_events, records, child_projections = (
            self._execute_formal_leaf_task(
                state,
                task,
                invocation=scoped_invocation,
                primary_target=scoped_resolution.primary,
                target_resolution=scoped_resolution,
                task_graph_continuation=continuation,
                nested_ability_hooks=self._formal_task_graph_hooks(
                    invocation=scoped_invocation,
                ),
            )
        )
        blocker = _ability_task_records_blocked_reason(records)
        if blocker:
            return TaskGraphLeafResult("blocked", outcome_kind="", blocked_reason=blocker)
        try:
            settlement = _task_graph_settlement_records(records)
        except (TypeError, ValueError):
            return TaskGraphLeafResult(
                "blocked",
                outcome_kind="",
                blocked_reason="ability_task_graph_leaf_settlement_invalid",
            )
        return TaskGraphLeafResult(
            "resolved",
            tuple(mutations),
            tuple(events),
            tuple(rng_events),
            settlement,
            child_projections=tuple(child_projections),
        )

    def _execute_formal_leaf_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        *,
        invocation: _FormalAbilityInvocation,
        primary_target: str | None,
        target_resolution: TargetResolution,
        task_graph_continuation: TaskGraphContinuation,
        nested_ability_hooks: TaskGraphExecutionHooks,
    ) -> tuple[
        BattleState,
        list[Mutation],
        list[GameEvent],
        list[RNGEvent],
        list[dict[str, JSONValue]],
        list[TaskGraphNodeProjection],
    ]:
        if invocation.invocation_kind == "action":
            command = cast(ActionCommand, invocation.action_command)
            action_definition = cast(ActionDefinitionIR, invocation.action_definition)
            scoped_command = replace(
                command,
                metadata={
                    **command.metadata,
                    "ability_task_execution_path": invocation.execution_path,
                    "ability_task_iteration_index": invocation.iteration_index,
                },
            )
            return self._execute_ability_leaf_task(
                state,
                task,
                command=scoped_command,
                action_definition=action_definition,
                primary_target=primary_target,
                target_resolution=target_resolution,
                task_graph_continuation=task_graph_continuation,
                nested_ability_hooks=nested_ability_hooks,
            )

        if self.rules.damage_emissions_for_task(task.task_id):
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason="standalone_ability_damage_context_deferred_to_s8c",
                )
            ], []
        admission_reason = ability_task_runtime_blocked_reason(self.rules, task)
        if admission_reason:
            return state, [], [], [], [
                _task_process_record(task, ok=False, blocked_reason=admission_reason)
            ], []
        if is_process_only_ability_task(task):
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=True,
                    blocked_reason="process_only_ability_task",
                    effect_id=task.effect_id,
                    effect_opcode=task.opcode,
                    effect_coverage="process_only",
                )
            ], []
        if task.opcode in {
            "PredicateTaskList",
            "LoopExecuteTaskListWithInterval",
            "TriggerAbility",
        }:
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason="ability_task_graph_structural_node_reached_leaf",
                )
            ], []
        if task.opcode == "SummonMonster":
            result = self.execute_summon_monster_task(
                state, task, actor_id=invocation.actor_id
            )
            return (*result, [])
        result = self._execute_effect_leaf_task(
            state,
            task,
            invocation=invocation,
            primary_target=primary_target,
            target_resolution=target_resolution,
            reduce_candidate=False,
        )
        return (*result, [])

    def _execute_effect_leaf_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        *,
        invocation: _FormalAbilityInvocation,
        primary_target: str | None,
        target_resolution: TargetResolution,
        reduce_candidate: bool,
    ) -> tuple[BattleState, list[Mutation], list[GameEvent], list[RNGEvent], list[dict[str, JSONValue]]]:
        if not task.effect_id:
            return state, [], [], [], [
                _task_process_record(task, ok=False, blocked_reason="task_has_no_effect")
            ]
        effect = self.rules.effect(task.effect_id)
        if effect is None:
            return state, [], [], [], [
                _task_process_record(task, ok=False, blocked_reason="missing_effect")
            ]
        effect_coverage = self.effect_registry.coverage(effect)
        if effect_coverage != "executable":
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason=f"effect_not_executable:{effect_coverage}",
                    effect_id=effect.effect_id,
                    effect_opcode=effect.opcode,
                    effect_coverage=effect_coverage,
                )
            ]
        ability_instance_prefix = (
            "ability_action"
            if invocation.invocation_kind == "action"
            else "queue_standalone"
        )
        result = self.effect_registry.execute(
            effect,
            EffectExecutionContext(
                state=state,
                caster_id=invocation.actor_id,
                source_id=f"ability_task:{task.task_id}",
                owner_id=invocation.actor_id,
                param_entity_id=primary_target or invocation.actor_id,
                current_action_target_id=primary_target,
                target_resolution=target_resolution,
                event_payload={
                    **_formal_effect_event_payload(
                        invocation, primary_target, target_resolution
                    ),
                    "task_id": task.task_id,
                    "hit_index": task.task_index,
                    "rng_decision_index": task.task_index,
                    "ability_instance_id": (
                        f"{ability_instance_prefix}:{state.event_index}:"
                        f"{invocation.actor_id}:{invocation.ability_id}:"
                        f"{invocation.ability_level}"
                    ),
                    "operation_event_id": (
                        f"ability_task:{state.event_index}:"
                        f"{invocation.actor_id}:{invocation.ability_id}:"
                        f"{task.task_id}:{invocation.execution_path}"
                    ),
                },
                binding_sources=_binding_sources(
                    self.rules,
                    state,
                    invocation.actor_id,
                    primary_target,
                    action_level=invocation.ability_level,
                    current_action_trigger_key=_formal_action_trigger_key(invocation),
                ),
            ),
        )
        after = (
            self.reducer.apply_all(state, result.mutations)
            if reduce_candidate
            else state
        )
        records = [
            *result.records,
            _task_process_record(
                task,
                ok=not result.unsupported,
                blocked_reason=",".join(result.unsupported),
                effect_id=effect.effect_id,
                effect_opcode=effect.opcode,
                effect_coverage=effect_coverage,
                mutation_count=len(result.mutations),
                record_count=len(result.records),
            ),
        ]
        return (
            after,
            list(result.mutations),
            list(result.events),
            list(result.rng_events),
            records,
        )

    def _evaluate_formal_ability_condition(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        *,
        invocation: _FormalAbilityInvocation,
        primary_target: str | None,
        target_resolution: TargetResolution,
    ) -> tuple[bool | None, str, dict[str, JSONValue]]:
        condition = self.rules.condition(task.condition_id) if task.condition_id else None
        if condition is None:
            return None, "missing_predicate_condition", {}
        target_context = TargetEvaluationContext(
            caster_id=invocation.actor_id,
            effect_owner_id=invocation.actor_id,
            parameter_entity_ids=((primary_target or invocation.actor_id),),
            selected_target_ids=target_resolution.selected,
            current_target_id=primary_target,
            turn_owner_id=committed_turn_owner_id(state),
        )
        result = self.evaluator.evaluate_condition_result(
            condition,
            self.targets.condition_evaluation_context(
                state,
                condition,
                context=target_context,
                target_resolution=target_resolution,
                condition_event_payload={
                    **_formal_event_payload(
                        invocation, primary_target, target_resolution
                    ),
                    "task_id": task.task_id,
                    "hit_index": task.task_index,
                    "rng_decision_index": task.task_index,
                },
                binding_sources=_binding_sources(
                    self.rules,
                    state,
                    invocation.actor_id,
                    primary_target,
                    action_level=invocation.ability_level,
                    current_action_trigger_key=_formal_action_trigger_key(
                        invocation
                    ),
                ),
                transient_condition_provider=_formal_condition_provider(
                    self.rules,
                    state,
                    invocation,
                    target_resolution,
                    task.task_id,
                ),
            ),
        )
        evidence = cast(dict[str, JSONValue], result.to_json())
        if not result.ok or result.result is None:
            return (
                None,
                f"blocked_condition:{condition.condition_id}:{result.reason}",
                evidence,
            )
        return result.result, "", evidence

    def _evaluate_formal_condition(
        self,
        request: TaskGraphHookRequest,
        state: BattleState,
        *,
        invocation: _FormalAbilityInvocation,
    ) -> TaskGraphConditionResult:
        task, reason = self._formal_task_for_request(request)
        if task is None:
            return TaskGraphConditionResult("blocked", blocked_reason=reason)
        condition_refs = tuple(
            reference
            for reference in request.references
            if reference.reference_kind == "condition"
        )
        if (
            len(condition_refs) != 1
            or condition_refs[0].resolution_status != "resolved"
            or condition_refs[0].definition_id != task.condition_id
        ):
            return TaskGraphConditionResult(
                "blocked",
                blocked_reason="ability_task_graph_condition_reference_not_resolved",
            )
        scoped = _task_graph_target_resolution(request, invocation.target_resolution)
        scoped_invocation = replace(invocation, target_resolution=scoped)
        value, blocker, _evidence = self._evaluate_formal_ability_condition(
            state,
            task,
            invocation=scoped_invocation,
            primary_target=scoped.primary,
            target_resolution=scoped,
        )
        if value is None:
            return TaskGraphConditionResult("blocked", blocked_reason=blocker)
        return TaskGraphConditionResult("resolved", value)

    def _resolve_formal_count(
        self,
        request: TaskGraphHookRequest,
        definition: TaskGraphNumericDefinitionIR,
        state: BattleState,
        *,
        invocation: _FormalAbilityInvocation,
    ) -> TaskGraphCountResult:
        task, reason = self._formal_task_for_request(request)
        if task is None:
            return TaskGraphCountResult("blocked", blocked_reason=reason)
        numeric_refs = tuple(
            reference
            for reference in request.references
            if reference.reference_kind == "numeric"
        )
        if (
            len(numeric_refs) != 1
            or numeric_refs[0].resolution_status != "resolved"
            or numeric_refs[0].definition_id != definition.definition_id
        ):
            return TaskGraphCountResult(
                "blocked",
                blocked_reason="ability_task_graph_numeric_reference_not_resolved",
            )
        scoped = _task_graph_target_resolution(request, invocation.target_resolution)
        result = self.evaluator.evaluate_numeric(
            definition.expression,
            NumericEvaluationContext(
                binding_sources=_binding_sources(
                    self.rules,
                    state,
                    invocation.actor_id,
                    scoped.primary,
                    action_level=invocation.ability_level,
                    current_action_trigger_key=_formal_action_trigger_key(invocation),
                ),
                source_trace=definition.source.to_json(),
            ),
        )
        if (
            not result.ok
            or result.value is None
            or not math.isfinite(result.value)
            or result.value < 0
            or not result.value.is_integer()
        ):
            return TaskGraphCountResult(
                "blocked",
                blocked_reason=result.blocked_reason
                or "ability_task_graph_count_not_nonnegative_integer",
            )
        return TaskGraphCountResult("resolved", int(result.value))

    def _resolve_formal_targets(
        self,
        request: TaskGraphHookRequest,
        state: BattleState,
        *,
        invocation: _FormalAbilityInvocation,
    ) -> TaskGraphTargetResult:
        task, reason = self._formal_task_for_request(request)
        if task is None:
            return TaskGraphTargetResult("blocked", blocked_reason=reason)
        target_refs = tuple(
            reference
            for reference in request.references
            if reference.reference_kind == "target"
        )
        if len(target_refs) != 1 or target_refs[0].resolution_status != "resolved":
            return TaskGraphTargetResult(
                "blocked",
                blocked_reason="ability_task_graph_target_reference_not_resolved",
            )
        expression, lookup_reason = self.rules.target_expression_resolution(
            target_refs[0].definition_id
        )
        if expression is None:
            return TaskGraphTargetResult("blocked", blocked_reason=lookup_reason)
        scoped = _task_graph_target_resolution(request, invocation.target_resolution)
        primary = scoped.primary
        target_context = TargetEvaluationContext(
            caster_id=invocation.actor_id,
            effect_owner_id=invocation.actor_id,
            parameter_entity_ids=((primary or invocation.actor_id),),
            selected_target_ids=scoped.selected,
            current_target_id=primary,
            turn_owner_id=committed_turn_owner_id(state),
        )
        result = self.targets.resolve_target_expression(
            state,
            expression,
            context=target_context,
            target_resolution=scoped,
            condition_event_payload={
                **_formal_event_payload(invocation, primary, scoped),
                "task_id": task.task_id,
            },
            binding_sources=_binding_sources(
                self.rules,
                state,
                invocation.actor_id,
                primary,
                action_level=invocation.ability_level,
                current_action_trigger_key=_formal_action_trigger_key(invocation),
            ),
            transient_condition_provider=_formal_condition_provider(
                self.rules, state, invocation, scoped, task.task_id
            ),
        )
        if result.blocked:
            return TaskGraphTargetResult("blocked", blocked_reason=result.blocked_reason)
        if result.rng_events:
            return TaskGraphTargetResult(
                "blocked",
                blocked_reason="ability_task_graph_random_target_requires_hit_sequence",
            )
        return TaskGraphTargetResult("resolved", result.target_ids)

    def _resolve_formal_nested_graph(
        self,
        request: TaskGraphHookRequest,
        _state: BattleState,
    ) -> TaskGraphGraphResult:
        task, reason = self._formal_task_for_request(request)
        if task is None:
            return TaskGraphGraphResult("blocked", blocked_reason=reason)
        callback_kind = task.callback_kind
        ability_refs = tuple(
            reference
            for reference in request.references
            if reference.reference_kind == "ability"
        )
        if len(ability_refs) != 1 or ability_refs[0].resolution_status != "resolved":
            return TaskGraphGraphResult(
                "blocked",
                blocked_reason="ability_task_graph_nested_reference_not_resolved",
            )
        reference = ability_refs[0]
        phase_ids: tuple[str, ...]
        if task.linked_ability_phase_id:
            if reference.definition_id != task.linked_ability_phase_id:
                return TaskGraphGraphResult(
                    "blocked",
                    blocked_reason="ability_task_graph_nested_phase_identity_mismatch",
                )
            phase_ids = (task.linked_ability_phase_id,)
        elif task.linked_standalone_graph_id:
            if reference.definition_id != task.linked_standalone_graph_id:
                return TaskGraphGraphResult(
                    "blocked",
                    blocked_reason="ability_task_graph_nested_standalone_identity_mismatch",
                )
            standalone = self.rules.standalone_ability_graph(
                task.linked_standalone_graph_id
            )
            if standalone is None:
                return TaskGraphGraphResult(
                    "blocked",
                    blocked_reason="ability_task_graph_nested_standalone_missing",
                )
            phase_ids = standalone.phase_ids
        else:
            return TaskGraphGraphResult(
                "blocked",
                blocked_reason="ability_task_graph_nested_target_missing",
            )
        candidates: list[TaskGraphIR] = []
        for phase_id in phase_ids:
            phase = self.rules.ability_phase(phase_id)
            if phase is None or phase.invocation_role != "nested_only":
                continue
            if not any(
                task.callback_kind == callback_kind
                for task in self.rules.ability_tasks_for_phase(phase_id)
            ):
                continue
            entry_result = self.rules.query_task_graph_entry(
                "ability_phase_callback",
                phase_id,
                callback_kind,
            )
            if entry_result.status != "resolved" or entry_result.value is None:
                return TaskGraphGraphResult(
                    "blocked",
                    blocked_reason=entry_result.blocked_reason
                    or "ability_task_graph_nested_entry_missing",
                )
            graph_result = self.rules.query_task_graph(entry_result.value.graph_id)
            if graph_result.status != "resolved" or type(graph_result.value) is not TaskGraphIR:
                return TaskGraphGraphResult(
                    "blocked",
                    blocked_reason=graph_result.blocked_reason
                    or "ability_task_graph_nested_graph_missing",
                )
            candidates.append(graph_result.value)
        if len(candidates) != 1:
            return TaskGraphGraphResult(
                "blocked",
                blocked_reason=(
                    "ability_task_graph_nested_callback_missing"
                    if not candidates
                    else "ability_task_graph_nested_callback_ambiguous"
                ),
            )
        return TaskGraphGraphResult("resolved", reference.definition_id, candidates[0])

    def _formal_task_for_request(
        self,
        request: TaskGraphHookRequest,
    ) -> tuple[AbilityTaskIR | None, str]:
        task = self.rules.ability_task(request.formal_task_id)
        graph_result = self.rules.query_task_graph(request.graph_id)
        graph = graph_result.value
        node_result = self.rules.query_task_graph_node(request.graph_node_id)
        node = node_result.value
        if task is None:
            return None, "ability_task_graph_formal_task_missing"
        if (
            graph_result.status != "resolved"
            or type(graph) is not TaskGraphIR
            or node_result.status != "resolved"
            or node is None
            or node.graph_id != request.graph_id
            or node.formal_task_id != request.formal_task_id
            or task.phase_id != graph.owner_id
            or task.callback_kind != graph.callback_kind
        ):
            return None, "ability_task_graph_formal_task_identity_mismatch"
        return task, ""

    @staticmethod
    def _formal_callback_blocked(
        state: BattleState,
        callback_kind: str,
        invocation: _FormalAbilityInvocation,
        reason: str,
        *,
        node_results: tuple[ExecutionNodeResult, ...] = (),
    ) -> AbilityTaskExecutionResult:
        blocked_node = ExecutionNodeResult(
            node_kind="ability_task_graph_callback",
            node_id=(
                f"ability_task_graph_callback:{state.event_index}:"
                f"{invocation.actor_id}:{invocation.ability_id}:{callback_kind}"
            ),
            status="blocked",
            reason_code=reason,
        )
        return AbilityTaskExecutionResult(
            after_state=state,
            records=(
                SettlementRecord(
                    record_type="ability_task_graph_blocked",
                    source="ability_task_system",
                    process_only=True,
                    payload={
                        "invocation_kind": invocation.invocation_kind,
                        "actor_id": invocation.actor_id,
                        "ability_id": invocation.ability_id,
                        "ability_level": invocation.ability_level,
                        "callback_kind": callback_kind,
                        "reason": reason,
                    },
                    trace={},
                ).to_json(),
            ),
            node_results=(*node_results, blocked_node),
        )

    @staticmethod
    def _formal_action_input_blocked(
        state: BattleState,
        callback_kind: str,
        command: ActionCommand,
        reason: str,
    ) -> AbilityTaskExecutionResult:
        return AbilityTaskExecutionResult(
            after_state=state,
            records=(
                SettlementRecord(
                    record_type="ability_task_graph_blocked",
                    source="ability_task_system",
                    process_only=True,
                    payload={
                        "invocation_kind": "action",
                        "actor_id": command.actor_id,
                        "ability_id": command.action_id,
                        "ability_level": command.action_level,
                        "callback_kind": callback_kind,
                        "reason": reason,
                    },
                    trace={},
                ).to_json(),
            ),
            node_results=(
                ExecutionNodeResult(
                    node_kind="ability_task_graph_callback",
                    node_id=(
                        f"ability_task_graph_callback:{state.event_index}:"
                        f"{command.actor_id}:{command.action_id}:{callback_kind}"
                    ),
                    status="blocked",
                    reason_code=reason,
                ),
            ),
        )

    def _execute_admitted_queue_standalone(
        self,
        state: BattleState,
        *,
        invocation: StandaloneAbilityInvocation,
    ) -> AbilityTaskExecutionResult:
        if type(invocation) is not StandaloneAbilityInvocation:
            raise TypeError("standalone ability execution requires typed invocation")
        resolution = self.rules.queue_resolution(invocation.queue_resolution_id)
        graph = self.rules.standalone_ability_graph(invocation.graph_id)
        resolved_graph_id = (
            str(resolution.resolved_ids.get("standalone_ability_graph_id") or "")
            if resolution is not None
            else ""
        )
        if (
            resolution is None
            or resolution.coverage_status != "executable"
            or resolution.resolved_kind != "standalone_ability_graph"
            or resolution.queue_intent_id != invocation.queue_intent_id
            or resolved_graph_id != invocation.graph_id
        ):
            return self._standalone_invocation_blocked(
                state, invocation, "standalone_queue_resolution_identity_mismatch"
            )
        if graph is None:
            return self._standalone_invocation_blocked(
                state, invocation, "standalone_ability_graph_missing"
            )
        if (
            graph.coverage_status != "executable"
            or graph.blocked_reason
            or resolution.action_or_ability_ref != graph.ability_name
        ):
            return self._standalone_invocation_blocked(
                state, invocation, "standalone_ability_graph_not_admitted"
            )
        resolved_phase_ids = resolution.resolved_ids.get("phase_ids")
        if (
            not isinstance(resolved_phase_ids, (list, tuple))
            or tuple(resolved_phase_ids) != graph.phase_ids
        ):
            return self._standalone_invocation_blocked(
                state, invocation, "standalone_ability_phase_ledger_mismatch"
            )
        phases = tuple(
            phase
            for phase_id in graph.phase_ids
            if (phase := self.rules.ability_phase(phase_id)) is not None
        )
        if (
            len(phases) != len(graph.phase_ids)
            or tuple(phase.phase_id for phase in phases) != graph.phase_ids
            or any(
                phase.invocation_role != "standalone_root"
                or phase.ability_name != graph.ability_name
                for phase in phases
            )
        ):
            return self._standalone_invocation_blocked(
                state, invocation, "standalone_ability_formal_root_mismatch"
            )
        phase_task_ids = tuple(
            task_id for phase in phases for task_id in phase.task_ids
        )
        resolved_task_ids = resolution.resolved_ids.get("task_ids")
        resolved_executable_task_ids = resolution.resolved_ids.get(
            "executable_task_ids"
        )
        if (
            graph.task_ids != phase_task_ids
            or not isinstance(resolved_task_ids, (list, tuple))
            or tuple(resolved_task_ids) != graph.task_ids
            or not isinstance(resolved_executable_task_ids, (list, tuple))
            or tuple(resolved_executable_task_ids) != graph.executable_task_ids
        ):
            return self._standalone_invocation_blocked(
                state, invocation, "standalone_ability_task_ledger_mismatch"
            )
        if invocation.actor_id not in state.units or any(
            target_id not in state.units for target_id in invocation.target_ids
        ):
            return self._standalone_invocation_blocked(
                state, invocation, "standalone_ability_combatant_identity_missing"
            )
        entries: list[tuple[AbilityPhaseIR, str]] = []
        for phase in phases:
            callbacks: set[str] = set()
            for task_id in phase.task_ids:
                task = self.rules.ability_task(task_id)
                if task is None or task.phase_id != phase.phase_id:
                    return self._standalone_invocation_blocked(
                        state, invocation, "standalone_ability_task_ledger_mismatch"
                    )
                callbacks.add(task.callback_kind)
            unknown_callbacks = callbacks - set(_STANDALONE_CALLBACK_ORDER)
            if unknown_callbacks:
                return self._standalone_invocation_blocked(
                    state,
                    invocation,
                    "standalone_ability_callback_lifecycle_not_admitted:"
                    + ",".join(sorted(unknown_callbacks)),
                )
            entries.extend(
                (phase, callback)
                for callback in _STANDALONE_CALLBACK_ORDER
                if callback in callbacks
            )
        if not entries:
            return self._standalone_invocation_blocked(
                state, invocation, "standalone_ability_callback_entry_missing"
            )
        target_resolution = TargetResolution(
            requested=invocation.target_ids,
            legal=invocation.target_ids,
            selected=invocation.target_ids,
            rejected=(),
            reason="queue_standalone_targets_from_admitted_queue",
            source="queue_resolution",
            metadata={
                "queue_entry_id": invocation.queue_entry_id,
                "queue_resolution_id": invocation.queue_resolution_id,
            },
        )
        formal_invocation = _FormalAbilityInvocation(
            "queue_standalone",
            invocation.actor_id,
            invocation.graph_id,
            0,
            target_resolution,
            standalone=invocation,
        )
        result = self._execute_formal_entries(
            state,
            entries=tuple(entries),
            invocation=formal_invocation,
        )
        if any(item.status != "complete" for item in result.node_results):
            return result
        execution_record = SettlementRecord(
            record_type="standalone_ability_execution",
            source="ability_task_system",
            process_only=True,
            payload={
                "invocation": invocation.to_json(),
                "ability_name": graph.ability_name,
                "phase_ids": list(graph.phase_ids),
            },
            trace={"standalone_graph_source": graph.source.to_json()},
        ).to_json()
        return replace(result, records=(execution_record, *result.records))

    @staticmethod
    def _standalone_invocation_blocked(
        state: BattleState,
        invocation: StandaloneAbilityInvocation,
        reason: str,
    ) -> AbilityTaskExecutionResult:
        return AbilityTaskExecutionResult(
            after_state=state,
            records=(
                SettlementRecord(
                    record_type="standalone_ability_blocked",
                    source="ability_task_system",
                    process_only=True,
                    payload={"reason": reason, "invocation": invocation.to_json()},
                    trace={},
                ).to_json(),
            ),
            node_results=(
                ExecutionNodeResult(
                    node_kind="ability_graph",
                    node_id=invocation.graph_id,
                    status="blocked",
                    reason_code=reason,
                ),
            ),
        )

    def _execute_legacy_standalone(
        self,
        state: BattleState,
        *,
        phases: tuple[AbilityPhaseIR, ...],
        actor_id: str,
        target_ids: tuple[str, ...],
        queue_entry: dict[str, JSONValue],
        queue_resolution: dict[str, JSONValue],
        depth: int = 0,
    ) -> AbilityTaskExecutionResult:
        if not phases:
            return AbilityTaskExecutionResult(
                after_state=state,
                records=(
                    SettlementRecord(
                        record_type="standalone_ability_blocked",
                        source="ability_task_system",
                        process_only=True,
                        payload={
                            "reason": "standalone_ability_phases_missing",
                            "queue_entry": queue_entry,
                            "queue_resolution": queue_resolution,
                        },
                        trace={},
                    ).to_json(),
                ),
                node_results=(
                    ExecutionNodeResult(
                        node_kind="ability_graph",
                        node_id=str(queue_entry.get("entry_id") or "standalone_ability"),
                        status="blocked",
                        reason_code="standalone_ability_phases_missing",
                    ),
                ),
            )
        ability_name = phases[0].ability_name
        action_id = f"standalone_ability:{ability_name}"
        action_definition = ActionDefinitionIR(
            definition_id=f"standalone_action_def:{ability_name}",
            action_id=action_id,
            level=0,
            attack_type="StandaloneAbility",
            skill_effect="standalone_ability",
            target_mode="single" if target_ids else "none",
            bp_need=0.0,
            bp_add=0.0,
            sp_base=0.0,
            sp_multiple_ratio=0.0,
            param_list=(),
            show_stance_list=(),
            show_damage_list=(),
            stance_damage_type=None,
            source=phases[0].source if phases else IRSource("", "", ""),
            coverage_status="executable",
            damage_kind="none",
            damage_formula_family="none",
            element_type=None,
            source_mode="queue_standalone",
        )
        command = ActionCommand(
            actor_id=actor_id,
            action_id=action_id,
            action_level=0,
            target_ids=target_ids,
            source="queue",
            queue_name=str(queue_entry.get("queue_name") or ""),
            metadata={
                "parent_queue_entry_id": str(queue_entry.get("entry_id") or ""),
                "queue_intent_id": str(queue_entry.get("queue_intent_id") or ""),
                "queue_resolution_id": str(queue_resolution.get("queue_resolution_id") or ""),
                "standalone_ability_name": ability_name,
                "standalone_depth": depth,
                "is_insert_action": True,
            },
        )
        target_resolution = TargetResolution(
            requested=target_ids,
            legal=target_ids,
            selected=target_ids,
            rejected=(),
            reason="queue_standalone_targets_from_queue_entry",
            source="queue_resolution",
            metadata={
                "queue_entry_id": str(queue_entry.get("entry_id") or ""),
                "queue_resolution_id": str(queue_resolution.get("queue_resolution_id") or ""),
            },
        )
        current = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        records: list[dict[str, JSONValue]] = [
            SettlementRecord(
                record_type="standalone_ability_execution",
                source="ability_task_system",
                process_only=True,
                payload={
                    "ability_name": ability_name,
                    "phase_ids": [phase.phase_id for phase in phases],
                    "queue_entry": queue_entry,
                    "queue_resolution": queue_resolution,
                },
                trace={"standalone_phase_source": phases[0].source.to_json()},
            ).to_json()
        ]
        task_records: list[dict[str, JSONValue]] = []
        node_results: list[ExecutionNodeResult] = []
        for callback_kind in ("OnStart", "OnAttack", "OnHit", "OnEnd"):
            result = self.execute_callback(
                current,
                phases=phases,
                callback_kind=callback_kind,
                command=command,
                action_definition=action_definition,
                target_resolution=target_resolution,
            )
            current = result.after_state
            mutations.extend(result.mutations)
            events.extend(result.events)
            rng_events.extend(result.rng_events)
            records.extend(result.records)
            task_records.extend(result.task_records)
            node_results.extend(result.node_results)
        return AbilityTaskExecutionResult(
            after_state=current,
            mutations=tuple(mutations),
            events=tuple(events),
            rng_events=tuple(rng_events),
            records=tuple(records),
            task_records=tuple(task_records),
            node_results=tuple(node_results),
        )

    def _execute_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        tasks: dict[str, AbilityTaskIR],
        *,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        primary_target: str | None,
        target_resolution: TargetResolution,
    ) -> tuple[BattleState, list[Mutation], list[GameEvent], list[RNGEvent], list[dict[str, JSONValue]]]:
        admission_reason = ability_task_runtime_blocked_reason(self.rules, task)
        if admission_reason:
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason=admission_reason,
                )
            ]
        if is_process_only_ability_task(task):
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=True,
                    blocked_reason="process_only_ability_task",
                    effect_id=task.effect_id,
                    effect_opcode=task.opcode,
                    effect_coverage="process_only",
                )
            ]
        if task.opcode == "PredicateTaskList":
            return self._execute_predicate_task(
                state,
                task,
                tasks,
                command=command,
                action_definition=action_definition,
                primary_target=primary_target,
                target_resolution=target_resolution,
            )
        if task.opcode == "LoopExecuteTaskListWithInterval":
            return self._execute_fixed_task_loop(
                state,
                task,
                tasks,
                command=command,
                action_definition=action_definition,
                primary_target=primary_target,
                target_resolution=target_resolution,
            )
        if task.opcode == "TriggerAbility":
            return self._execute_trigger_ability_task(
                state,
                task,
                command=command,
                action_definition=action_definition,
                primary_target=primary_target,
                target_resolution=target_resolution,
            )
        leaf_result = self._execute_ability_leaf_task(
            state,
            task,
            command=command,
            action_definition=action_definition,
            primary_target=primary_target,
            target_resolution=target_resolution,
        )
        return leaf_result[:5]

    def _execute_ability_leaf_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        *,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        primary_target: str | None,
        target_resolution: TargetResolution,
        task_graph_continuation: TaskGraphContinuation | None = None,
        nested_ability_hooks: TaskGraphExecutionHooks | None = None,
    ) -> tuple[
        BattleState,
        list[Mutation],
        list[GameEvent],
        list[RNGEvent],
        list[dict[str, JSONValue]],
        list[TaskGraphNodeProjection],
    ]:
        admission_reason = ability_task_runtime_blocked_reason(self.rules, task)
        if admission_reason:
            return state, [], [], [], [
                _task_process_record(task, ok=False, blocked_reason=admission_reason)
            ], []
        if is_process_only_ability_task(task):
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=True,
                    blocked_reason="process_only_ability_task",
                    effect_id=task.effect_id,
                    effect_opcode=task.opcode,
                    effect_coverage="process_only",
                )
            ], []
        if task.opcode in {
            "PredicateTaskList",
            "LoopExecuteTaskListWithInterval",
            "TriggerAbility",
        }:
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason="ability_task_graph_structural_node_reached_leaf",
                )
            ], []
        if task.opcode == "SummonMonster":
            result = self.execute_summon_monster_task(
                state,
                task,
                actor_id=command.actor_id,
            )
            return (*result, [])
        if self.rules.damage_emissions_for_task(task.task_id):
            return self._execute_damage_task(
                state,
                task,
                command=command,
                action_definition=action_definition,
                primary_target=primary_target,
                target_resolution=target_resolution,
                task_graph_continuation=task_graph_continuation,
                nested_ability_hooks=nested_ability_hooks,
            )
        iteration = command.metadata.get("ability_task_iteration_index")
        invocation = _FormalAbilityInvocation(
            "action",
            command.actor_id,
            command.action_id,
            command.action_level,
            target_resolution,
            action_command=command,
            action_definition=action_definition,
            execution_path=str(
                command.metadata.get(
                    "ability_task_execution_path", task.task_index
                )
            ),
            iteration_index=(
                iteration if type(iteration) is int and iteration >= 0 else None
            ),
        )
        result = self._execute_effect_leaf_task(
            state,
            task,
            invocation=invocation,
            primary_target=primary_target,
            target_resolution=target_resolution,
            reduce_candidate=True,
        )
        return (*result, [])

    def _execute_fixed_task_loop(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        tasks: dict[str, AbilityTaskIR],
        *,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        primary_target: str | None,
        target_resolution: TargetResolution,
    ) -> tuple[BattleState, list[Mutation], list[GameEvent], list[RNGEvent], list[dict[str, JSONValue]]]:
        if task.coverage_status != "executable" or task.repeat_count <= 0:
            reason = task.blocked_reason or "fixed_positive_loop_count_required"
            return state, [], [], [], [_task_process_record(task, ok=False, blocked_reason=reason)]
        current = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        records: list[dict[str, JSONValue]] = []
        failure_reason = ""
        for iteration_index in range(task.repeat_count):
            parent_path = str(
                command.metadata.get("ability_task_execution_path") or ""
            )
            iteration_path = (
                f"{parent_path}/{task.task_id}[{iteration_index}]"
                if parent_path
                else f"{task.task_id}[{iteration_index}]"
            )
            iteration_command = replace(
                command,
                metadata={
                    **command.metadata,
                    "ability_task_execution_path": iteration_path,
                    "ability_loop_task_id": task.task_id,
                    "ability_loop_iteration": iteration_index,
                },
            )
            for child_id in task.child_task_ids:
                child = tasks.get(child_id)
                if child is None or child.parent_task_id != task.task_id:
                    failure_reason = f"loop_child_missing_or_mismatched:{child_id}"
                    break
                current, child_mutations, child_events, child_rng_events, child_records = self._execute_task(
                    current,
                    child,
                    tasks,
                    command=iteration_command,
                    action_definition=action_definition,
                    primary_target=primary_target,
                    target_resolution=target_resolution,
                )
                mutations.extend(child_mutations)
                events.extend(child_events)
                rng_events.extend(child_rng_events)
                records.extend(child_records)
                if any(
                    isinstance(record.get("payload"), dict)
                    and record["payload"].get("ok") is False
                    for record in child_records
                    if isinstance(record, dict)
                    and record.get("record_type") == "ability_task"
                ):
                    failure_reason = f"loop_child_incomplete:{child_id}"
                    break
            if failure_reason:
                break
        records.insert(
            0,
            _task_process_record(
                task,
                ok=not failure_reason,
                blocked_reason=failure_reason,
                selected_child_ids=task.child_task_ids,
                mutation_count=len(mutations),
                record_count=len(records),
            ),
        )
        return current, mutations, events, rng_events, records

    def execute_summon_monster_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        *,
        actor_id: str,
    ) -> tuple[BattleState, list[Mutation], list[GameEvent], list[RNGEvent], list[dict[str, JSONValue]]]:
        intents = tuple(
            intent
            for intent in self.rules.summon_monster_intents()
            if intent.source_task_id == task.task_id
        )
        if len(intents) != 1:
            reason = "summon_monster_intent_missing" if not intents else "summon_monster_intent_ambiguous"
            return state, [], [], [], [_task_process_record(task, ok=False, blocked_reason=reason)]
        intent = intents[0]
        if intent.coverage_status != "executable":
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason=intent.blocked_reason
                    or f"summon_monster_intent_not_executable:{intent.coverage_status}",
                )
            ]
        if intent.source_task_id != task.task_id or intent.owner_scope != "caster":
            return state, [], [], [], [
                _task_process_record(task, ok=False, blocked_reason="summon_monster_intent_task_binding_mismatch")
            ]
        plan = self.summons.plan_spawn_from_intent(state, intent, owner_id=actor_id)
        result = self.summons.apply_spawn(state, plan)
        if not result.plan.ok:
            return state, [], [], [], [
                *result.records,
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason=result.plan.blocked_reason or "summon_monster_spawn_blocked",
                ),
            ]
        reduction = self.reducer.apply_all_result(state, result.mutations)
        if not reduction.ok:
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason=f"summon_monster_reducer_conflict:{reduction.conflicts[0].code}",
                )
            ]
        records = [
            *result.records,
            _task_process_record(
                task,
                ok=True,
                effect_id=task.effect_id,
                effect_opcode=task.opcode,
                effect_coverage="executable",
                mutation_count=len(result.mutations),
                record_count=len(result.records),
            ),
        ]
        return (
            reduction.after_state,
            list(result.mutations),
            list(result.events),
            list(result.rng_events),
            records,
        )

    def _execute_trigger_ability_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        *,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        primary_target: str | None,
        target_resolution: TargetResolution,
    ) -> tuple[BattleState, list[Mutation], list[GameEvent], list[RNGEvent], list[dict[str, JSONValue]]]:
        if task.coverage_status != "executable":
            return state, [], [], [], [_task_process_record(task, ok=False, blocked_reason=task.blocked_reason or "task_not_executable")]
        effect = self.rules.effect(task.effect_id) if task.effect_id else None
        standard = effect.payload.get("standard") if effect is not None else None
        if effect is None or not isinstance(standard, dict):
            return state, [], [], [], [_task_process_record(task, ok=False, blocked_reason="trigger_ability_effect_missing")]
        ability_name = standard.get("ability_name")
        if not isinstance(ability_name, str) or not ability_name:
            return state, [], [], [], [_task_process_record(task, ok=False, blocked_reason="trigger_ability_name_missing", effect_id=effect.effect_id, effect_opcode=effect.opcode)]
        if not command.action_id.startswith("standalone_ability:"):
            action_phase_names = {
                phase.ability_name
                for phase in self.rules.ability_phases_for_action(command.action_id, command.action_level)
            }
            if ability_name in action_phase_names:
                return state, [], [], [], [
                    _task_process_record(
                        task,
                        ok=True,
                        blocked_reason="trigger_ability_child_already_bound_to_action",
                        effect_id=effect.effect_id,
                        effect_opcode=effect.opcode,
                        effect_coverage="executable",
                    )
                ]
        depth = int(command.metadata.get("standalone_depth") or 0)
        if depth >= 4:
            return state, [], [], [], [_task_process_record(task, ok=False, blocked_reason="trigger_ability_depth_limit", effect_id=effect.effect_id, effect_opcode=effect.opcode)]
        graph = self.rules.standalone_ability_graph(task.linked_standalone_graph_id)
        if graph is None or graph.ability_name != ability_name:
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason="standalone_ability_graph_link_missing_or_mismatched",
                    effect_id=effect.effect_id,
                    effect_opcode=effect.opcode,
                )
            ]
        phases = tuple(
            phase
            for phase_id in graph.phase_ids
            if (phase := self.rules.ability_phase(phase_id)) is not None
        )
        result = self._execute_legacy_standalone(
            state,
            phases=phases,
            actor_id=command.actor_id,
            target_ids=target_resolution.selected,
            queue_entry={
                "entry_id": command.metadata.get("parent_queue_entry_id") or "",
                "queue_name": command.queue_name,
                "queue_intent_id": command.metadata.get("queue_intent_id") or "",
                "trigger_task_id": task.task_id,
            },
            queue_resolution={
                "queue_resolution_id": command.metadata.get("queue_resolution_id") or "",
                "trigger_task_id": task.task_id,
                "trigger_ability_name": ability_name,
            },
            depth=depth + 1,
        )
        records = list(result.records)
        records.append(
            _task_process_record(
                task,
                ok=not result.errors if hasattr(result, "errors") else True,
                effect_id=effect.effect_id,
                effect_opcode=effect.opcode,
                effect_coverage="executable",
                mutation_count=len(result.mutations),
                record_count=len(result.records),
            )
        )
        return result.after_state, list(result.mutations), list(result.events), list(result.rng_events), records

    def _execute_damage_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        *,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        primary_target: str | None,
        target_resolution: TargetResolution,
        task_graph_continuation: TaskGraphContinuation | None,
        nested_ability_hooks: TaskGraphExecutionHooks | None,
    ) -> tuple[
        BattleState,
        list[Mutation],
        list[GameEvent],
        list[RNGEvent],
        list[dict[str, JSONValue]],
        list[TaskGraphNodeProjection],
    ]:
        emissions = tuple(
            emission
            for emission in self.rules.damage_emissions_for_task(task.task_id)
            if emission.action_id == task.action_id and emission.level == task.level
        )
        if not emissions:
            return state, [], [], [], [
                _task_process_record(
                    task, ok=False, blocked_reason="damage_emission_missing"
                )
            ], []
        current = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        records: list[dict[str, JSONValue]] = []
        task_graph_projections: list[TaskGraphNodeProjection] = []
        ledger = DamageWindowLedger()
        sequence_order: list[tuple[str, str]] = []
        sequence_context: dict[
            tuple[str, str],
            dict[str, JSONValue],
        ] = {}

        def dispatch_damage_event(event: GameEvent) -> tuple[str, ...]:
            nonlocal current
            if self.event_dispatcher is None:
                events.append(event)
                return ()
            result: EventDispatchResult = self.event_dispatcher.dispatch_event(
                current,
                event=event,
                damage_window_ledger=ledger,
                task_graph_continuation=task_graph_continuation,
                nested_ability_hooks=nested_ability_hooks,
            )
            current = result.after_state
            mutations.extend(result.mutations)
            events.extend(result.events)
            rng_events.extend(result.rng_events)
            records.extend(result.records)
            task_graph_projections.extend(result.task_graph_projections)
            return result.errors

        for emission in emissions:
            if emission.coverage_status != "executable":
                records.append(
                    _task_process_record(
                        task,
                        ok=False,
                        blocked_reason=emission.blocked_reason or f"damage_emission_not_executable:{emission.coverage_status}",
                    )
                )
                continue
            profile = self.rules.hit_profile(emission.hit_profile_id)
            if profile is None or profile.coverage_status != "executable":
                records.append(
                    _task_process_record(
                        task,
                        ok=False,
                        blocked_reason="hit_profile_missing_or_not_executable",
                    )
                )
                continue
            ratio_eval = self.evaluator.evaluate_numeric(
                emission.scaling_ratio_expr,
                NumericEvaluationContext(
                    binding_sources=(
                        *_binding_sources(
                            self.rules,
                            current,
                            command.actor_id,
                            primary_target,
                            action_level=command.action_level,
                            current_action_trigger_key=_action_trigger_key(action_definition),
                        ),
                        *_expression_binding_sources(emission.scaling_ratio_expr),
                    ),
                    source_trace=emission.source.to_json(),
                ),
            )
            if not ratio_eval.ok or ratio_eval.value is None:
                records.append(
                    _task_process_record(
                        task,
                        ok=False,
                        blocked_reason=f"damage_scaling_ratio_blocked:{ratio_eval.blocked_reason}",
                    )
                )
                continue
            target_ids = _damage_targets_for_emission(emission.target_group, target_resolution)
            if not target_ids:
                optional_group = emission.target_group == "adjacent"
                records.append(
                    _task_process_record(
                        task,
                        ok=optional_group,
                        blocked_reason=(
                            "damage_optional_target_group_empty"
                            if optional_group
                            else "damage_target_missing"
                        ),
                    )
                )
                continue
            for target_id in target_ids:
                toughness_blocked_reason = ""
                for toughness_emission in self.rules.toughness_emissions_for_task(
                    task.task_id
                ):
                    if toughness_emission.hit_profile_id != profile.hit_profile_id:
                        continue
                    binding_sources = (
                        *_binding_sources(
                            self.rules,
                            current,
                            command.actor_id,
                            primary_target,
                            action_level=command.action_level,
                            current_action_trigger_key=_action_trigger_key(
                                action_definition
                            ),
                        ),
                        *_expression_binding_sources(
                            toughness_emission.toughness_amount_expr
                        ),
                    )
                    toughness_packet = ToughnessPacket(
                        attacker_id=command.actor_id,
                        target_id=target_id,
                        toughness_emission_id=(
                            toughness_emission.toughness_emission_id
                        ),
                        source_task_id=task.task_id,
                        hit_profile_id=profile.hit_profile_id,
                        element_type=toughness_emission.element_type,
                        amount=None,
                        amount_expr=toughness_emission.toughness_amount_expr,
                        target_group=toughness_emission.target_group,
                        coverage_status=toughness_emission.coverage_status,
                        source_trace=toughness_emission.source.to_json(),
                        metadata={
                            "primary_action_target_id": primary_target,
                            "value_binding_sources": list(binding_sources),
                            "ability_task_execution_path": command.metadata.get(
                                "ability_task_execution_path",
                                "",
                            ),
                        },
                    )
                    toughness_result = self.toughness.apply_packet(
                        current,
                        toughness_packet,
                    )
                    records.extend(toughness_result.records)
                    if not toughness_result.ok:
                        toughness_blocked_reason = (
                            toughness_result.errors[0]
                            if toughness_result.errors
                            else "ability_task_toughness_blocked"
                        )
                        break
                    if toughness_result.mutations:
                        toughness_blocked_reason = (
                            "ability_task_toughness_pre_mutation_listener_not_admitted"
                        )
                        break
                if toughness_blocked_reason:
                    records.append(
                        _task_process_record(
                            task,
                            ok=False,
                            blocked_reason=toughness_blocked_reason,
                        )
                    )
                    continue
                execution_path = str(
                    command.metadata.get("ability_task_execution_path") or ""
                )
                is_standalone = (
                    action_definition.source_mode == "queue_standalone"
                )
                damage_source_id = (
                    task.task_id
                    if is_standalone
                    else (
                        f"action:{command.action_id}:"
                        f"level:{command.action_level}"
                    )
                )
                damage_source_kind = (
                    "standalone_ability_damage"
                    if is_standalone
                    else "primary_action_damage"
                )
                damage_sequence_id = (
                    f"{command.action_id}:{task.task_id}"
                    if is_standalone
                    else (
                        f"action:{command.actor_id}:{command.action_id}:"
                        f"level:{command.action_level}:task:{task.task_id}"
                    )
                )
                packet = DamagePacket(
                    attacker_id=command.actor_id,
                    target_id=target_id,
                    attack_type=action_definition.attack_type,
                    damage_formula_family=emission.damage_formula_family,
                    damage_kind="hp_damage",
                    element_type=emission.element_type,
                    action_definition=action_definition,
                    damage_emission_id=emission.damage_emission_id,
                    source_task_id=task.task_id,
                    hit_profile_id=profile.hit_profile_id,
                    scaling_ratio=ratio_eval.value,
                    scaling_basis=emission.scaling_basis_expr,
                    hit_source_trace=profile.source.to_json(),
                    source_trace=emission.source.to_json(),
                    source_frame=DamageSourceFrame(
                        owner_id=command.actor_id,
                        source_id=damage_source_id,
                        source_kind=damage_source_kind,
                        sequence_id=damage_sequence_id,
                        target_id=target_id,
                        can_continue_after_lethal=True,
                        source_trace=emission.source.to_json(),
                    ),
                    metadata={
                        **command.metadata,
                        "SkillType": action_definition.skill_effect,
                        "skill_type": action_definition.skill_effect,
                        "attack_type": action_definition.attack_type,
                        "is_current_skill_active": not is_standalone,
                        "is_insert_action": command.source == "queue",
                        "primary_action_target_id": primary_target,
                        "hit_index": profile.hit_index,
                        "target_group": emission.target_group,
                        "numeric_evaluation": ratio_eval.to_json(),
                        "phase_id": task.phase_id,
                        "derived_event_id": (
                            f"{emission.damage_emission_id}:{execution_path}"
                            if execution_path
                            else emission.damage_emission_id
                        ),
                    },
                )
                sequence_id = (
                    f"{task.task_id}:{execution_path}"
                    if execution_path
                    else task.task_id
                )
                sequence_key = (sequence_id, target_id)
                if (
                    self.event_dispatcher is not None
                    and sequence_key not in sequence_context
                ):
                    before_errors = dispatch_damage_event(
                        damage_listener_window_event(
                            current,
                            command,
                            action_definition,
                            event_type="damage.hit_sequence.before",
                            target_id=target_id,
                            selected_target_ids=target_resolution.selected,
                            primary_target_id=primary_target,
                            source_trace=emission.source.to_json(),
                            damage_custom_name=emission.damage_custom_name,
                            damage_tags=emission.damage_tags,
                            sequence_id=sequence_id,
                        )
                    )
                    if before_errors:
                        records.append(
                            _task_process_record(
                                task,
                                ok=False,
                                blocked_reason=(
                                    "ability_task_damage_before_window_blocked:"
                                    + ",".join(before_errors)
                                ),
                            )
                        )
                        return (
                            current,
                            mutations,
                            events,
                            rng_events,
                            records,
                            task_graph_projections,
                        )
                    sequence_order.append(sequence_key)
                    sequence_context[sequence_key] = {
                        "target_id": target_id,
                        "source_trace": emission.source.to_json(),
                        "damage_custom_name": emission.damage_custom_name,
                        "damage_tags": list(emission.damage_tags),
                        "is_critical": False,
                        "final_damage": 0.0,
                    }
                damage_result = self.damage.apply_packet(current, packet, window_ledger=ledger)
                current = self.reducer.apply_all(current, damage_result.mutations)
                mutations.extend(damage_result.mutations)
                rng_events.extend(damage_result.rng_events)
                records.extend(damage_result.records)
                for damage_event in damage_result.events:
                    if damage_event.event_type == "damage.hit":
                        amount = damage_event.payload.get("final_damage")
                        if not isinstance(amount, (int, float)) or isinstance(
                            amount,
                            bool,
                        ):
                            amount = damage_event.payload.get("amount")
                        if isinstance(amount, (int, float)) and not isinstance(
                            amount,
                            bool,
                        ):
                            context = sequence_context.get(sequence_key)
                            if context is not None:
                                context["final_damage"] = float(
                                    context.get("final_damage") or 0.0
                                ) + float(amount)
                                context["is_critical"] = bool(
                                    context.get("is_critical")
                                ) or damage_event.payload.get(
                                    "is_critical"
                                ) is True
                    dispatch_errors = dispatch_damage_event(damage_event)
                    if dispatch_errors:
                        records.append(
                            _task_process_record(
                                task,
                                ok=False,
                                blocked_reason=(
                                    "ability_task_damage_event_blocked:"
                                    + ",".join(dispatch_errors)
                                ),
                            )
                        )
                        return (
                            current,
                            mutations,
                            events,
                            rng_events,
                            records,
                            task_graph_projections,
                        )
                records.append(
                    _task_process_record(
                        task,
                        ok=damage_result.ok,
                        blocked_reason=",".join(damage_result.errors),
                        effect_id=task.effect_id,
                        effect_opcode=task.opcode,
                        effect_coverage="executable",
                        mutation_count=len(damage_result.mutations),
                        record_count=len(damage_result.records),
                    )
                )
        if self.event_dispatcher is not None:
            for sequence_key in sequence_order:
                context = sequence_context[sequence_key]
                sequence_tags = context.get("damage_tags")
                after_errors = dispatch_damage_event(
                    damage_listener_window_event(
                        current,
                        command,
                        action_definition,
                        event_type="damage.hit_sequence.after",
                        target_id=str(context["target_id"]),
                        selected_target_ids=target_resolution.selected,
                        primary_target_id=primary_target,
                        source_trace=(
                            context["source_trace"]
                            if isinstance(context.get("source_trace"), dict)
                            else {}
                        ),
                        is_critical=bool(context.get("is_critical")),
                        final_damage=float(
                            context.get("final_damage") or 0.0
                        ),
                        damage_custom_name=str(
                            context.get("damage_custom_name") or ""
                        ),
                        damage_tags=tuple(
                            tag
                            for tag in (
                                sequence_tags
                                if isinstance(sequence_tags, (list, tuple))
                                else ()
                            )
                            if isinstance(tag, str) and tag
                        ),
                        sequence_id=sequence_key[0],
                    )
                )
                if after_errors:
                    records.append(
                        _task_process_record(
                            task,
                            ok=False,
                            blocked_reason=(
                                "ability_task_damage_after_window_blocked:"
                                + ",".join(after_errors)
                            ),
                        )
                    )
                    return (
                        current,
                        mutations,
                        events,
                        rng_events,
                        records,
                        task_graph_projections,
                    )
        return (
            current,
            mutations,
            events,
            rng_events,
            records,
            task_graph_projections,
        )

    def _evaluate_ability_task_condition(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        *,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        primary_target: str | None,
        target_resolution: TargetResolution,
    ) -> tuple[bool | None, str, dict[str, JSONValue]]:
        invocation = _FormalAbilityInvocation(
            "action",
            command.actor_id,
            command.action_id,
            command.action_level,
            target_resolution,
            action_command=command,
            action_definition=action_definition,
        )
        return self._evaluate_formal_ability_condition(
            state,
            task,
            invocation=invocation,
            primary_target=primary_target,
            target_resolution=target_resolution,
        )

    def _execute_predicate_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        tasks: dict[str, AbilityTaskIR],
        *,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        primary_target: str | None,
        target_resolution: TargetResolution,
    ) -> tuple[BattleState, list[Mutation], list[GameEvent], list[RNGEvent], list[dict[str, JSONValue]]]:
        condition_value, condition_blocker, condition_evidence = (
            self._evaluate_ability_task_condition(
                state,
                task,
                command=command,
                action_definition=action_definition,
                primary_target=primary_target,
                target_resolution=target_resolution,
            )
        )
        if condition_value is None:
            record = _task_process_record(
                task,
                ok=False,
                blocked_reason=condition_blocker,
                condition_result=condition_evidence,
            )
            return state, [], [], [], [record]

        selected_child_ids = task.success_task_ids if condition_value else task.failed_task_ids
        current = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        records: list[dict[str, JSONValue]] = [
            _task_process_record(
                task,
                ok=True,
                condition_result=condition_evidence,
                selected_child_ids=selected_child_ids,
            )
        ]
        for child_id in selected_child_ids:
            child = tasks.get(child_id)
            if child is None:
                records.append(_task_process_record(task, ok=False, blocked_reason=f"missing_child_task:{child_id}"))
                continue
            current, child_mutations, child_events, child_rng_events, child_records = self._execute_task(
                current,
                child,
                tasks,
                command=command,
                action_definition=action_definition,
                primary_target=primary_target,
                target_resolution=target_resolution,
            )
            mutations.extend(child_mutations)
            events.extend(child_events)
            rng_events.extend(child_rng_events)
            records.extend(child_records)
        return current, mutations, events, rng_events, records


def _task_graph_target_resolution(
    request: TaskGraphHookRequest,
    target_resolution: TargetResolution,
) -> TargetResolution:
    if not request.target_ids:
        return target_resolution
    return replace(
        target_resolution,
        requested=request.target_ids,
        selectable=request.target_ids,
        legal=request.target_ids,
        primary=request.target_ids[0],
        impact_group=request.target_ids,
        selected=request.target_ids,
        rejected=(),
        reason="task_graph_target_scope",
        source="task_graph_executor",
        metadata={
            **target_resolution.metadata,
            "ability_task_invocation_id": request.invocation_id,
            "ability_task_scope_node_id": request.graph_node_id,
        },
    )


def _task_graph_execution_path(request: TaskGraphHookRequest) -> str:
    parts = [
        request.invocation_id,
        *request.active_graph_stack,
        request.graph_node_id,
        *(f"frame:{item}" for item in request.frame_ids),
        *(f"target:{item}" for item in request.target_ids),
    ]
    if request.iteration_index is not None:
        parts.append(f"iteration:{request.iteration_index}")
    return "/".join(parts)


def _ability_task_records_blocked_reason(
    records: list[dict[str, JSONValue]],
) -> str:
    for record in records:
        if not isinstance(record, Mapping) or record.get("record_type") != "ability_task":
            continue
        payload = record.get("payload")
        if not isinstance(payload, Mapping) or payload.get("ok") is not False:
            continue
        return str(payload.get("blocked_reason") or "ability_task_graph_leaf_blocked")
    return ""


def _task_graph_settlement_records(
    records: list[dict[str, JSONValue]],
) -> tuple[TaskGraphSettlementRecord, ...]:
    required = {
        "record_type",
        "source",
        "mutation_id",
        "process_only",
        "payload",
        "trace",
    }
    converted: list[TaskGraphSettlementRecord] = []
    for record in records:
        if not isinstance(record, Mapping) or set(record) != required:
            raise ValueError("ability task settlement record shape is invalid")
        payload = record.get("payload")
        trace = record.get("trace")
        if not isinstance(payload, Mapping) or not isinstance(trace, Mapping):
            raise TypeError("ability task settlement payload is invalid")
        converted.append(
            TaskGraphSettlementRecord(
                record_type=cast(str, record["record_type"]),
                source=cast(str, record["source"]),
                mutation_id=cast(str | None, record["mutation_id"]),
                process_only=cast(bool, record["process_only"]),
                payload=dict(payload),
                trace=dict(trace),
            )
        )
    return tuple(converted)


def _task_process_record(
    task: AbilityTaskIR,
    *,
    ok: bool,
    blocked_reason: str = "",
    effect_id: str = "",
    effect_opcode: str = "",
    effect_coverage: str = "",
    condition_result: dict[str, JSONValue] | None = None,
    selected_child_ids: tuple[str, ...] = (),
    mutation_count: int = 0,
    record_count: int = 0,
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="ability_task",
        source="ability_task_system",
        process_only=True,
        payload={
            "task_id": task.task_id,
            "phase_id": task.phase_id,
            "ability_name": task.ability_name,
            "callback_kind": task.callback_kind,
            "task_path": task.task_path,
            "branch": task.branch,
            "opcode": task.opcode,
            "ok": ok,
            "coverage_status": task.coverage_status,
            "blocked_reason": blocked_reason,
            "effect_id": effect_id or task.effect_id,
            "effect_opcode": effect_opcode,
            "effect_coverage": effect_coverage,
            "condition_id": task.condition_id,
            "condition_result": condition_result or {},
            "selected_child_ids": list(selected_child_ids),
            "mutation_count": mutation_count,
            "record_count": record_count,
        },
        trace=task.source.to_json(),
    ).to_json()


def _node_results_from_task_records(
    task_records: list[dict[str, JSONValue]] | tuple[dict[str, JSONValue], ...],
) -> tuple[ExecutionNodeResult, ...]:
    results: list[ExecutionNodeResult] = []
    for index, payload in enumerate(task_records):
        task_id = str(payload.get("task_id") or f"ability_task:{index}")
        ok = payload.get("ok") is True
        reason = str(payload.get("blocked_reason") or "")
        coverage_status = str(payload.get("coverage_status") or "")
        if ok:
            status = "complete"
        elif "partial" in reason or "partial" in coverage_status:
            status = "partial"
        elif coverage_status and coverage_status != "executable":
            status = "unsupported"
        elif "not_executable" in reason or "unsupported" in reason:
            status = "unsupported"
        else:
            status = "blocked"
        results.append(
            ExecutionNodeResult(
                node_kind="ability_task",
                node_id=task_id,
                status=status,
                reason_code=reason or ("" if ok else "ability_task_incomplete"),
            )
        )
    return tuple(results)


def _rng_event_payload_from_command(command: ActionCommand) -> dict[str, JSONValue]:
    payload: dict[str, JSONValue] = {}
    for key in ("rng_choices", "rng_mode", "target_random_choices"):
        value = command.metadata.get(key)
        if isinstance(value, (dict, str)):
            payload[key] = value
    return payload


def _event_payload(
    command: ActionCommand,
    action_definition: ActionDefinitionIR,
    primary_target: str | None,
    target_resolution: TargetResolution,
) -> dict[str, JSONValue]:
    return {
        **_rng_event_payload_from_command(command),
        "SkillType": action_definition.skill_effect,
        "skill_type": action_definition.skill_effect,
        "attack_type": action_definition.attack_type,
        "damage_kind": action_definition.damage_kind,
        "damage_formula_family": action_definition.damage_formula_family,
        "action_id": action_definition.action_id,
        "action_level": action_definition.level,
        "actor_id": command.actor_id,
        "primary_target_id": primary_target,
        "selected_target_ids": list(target_resolution.selected),
    }


def _formal_event_payload(
    invocation: _FormalAbilityInvocation,
    primary_target: str | None,
    target_resolution: TargetResolution,
) -> dict[str, JSONValue]:
    if invocation.invocation_kind == "action":
        return _event_payload(
            cast(ActionCommand, invocation.action_command),
            cast(ActionDefinitionIR, invocation.action_definition),
            primary_target,
            target_resolution,
        )
    payload: dict[str, JSONValue] = {
        "invocation_kind": "queue_standalone",
        "ability_id": invocation.ability_id,
        "ability_level": invocation.ability_level,
        "actor_id": invocation.actor_id,
        "primary_target_id": primary_target,
        "selected_target_ids": list(target_resolution.selected),
    }
    if invocation.standalone is not None:
        payload.update(invocation.standalone.to_json())
    return payload


def _formal_effect_event_payload(
    invocation: _FormalAbilityInvocation,
    primary_target: str | None,
    target_resolution: TargetResolution,
) -> dict[str, JSONValue]:
    if invocation.invocation_kind != "action":
        return _formal_event_payload(invocation, primary_target, target_resolution)
    command = cast(ActionCommand, invocation.action_command)
    return {
        **_rng_event_payload_from_command(command),
        "actor_id": invocation.actor_id,
        "action_id": invocation.ability_id,
        "action_level": invocation.ability_level,
    }


def _formal_action_trigger_key(
    invocation: _FormalAbilityInvocation,
) -> str | None:
    definition = invocation.action_definition
    return definition.skill_trigger_key if definition is not None else None


def _formal_condition_provider(
    rules: RuleBook,
    state: BattleState,
    invocation: _FormalAbilityInvocation,
    target_resolution: TargetResolution,
    task_id: str,
):
    if invocation.invocation_kind != "action":
        return None
    return admitted_action_condition_fact_provider(
        rules,
        state,
        command=cast(ActionCommand, invocation.action_command),
        action_definition=cast(ActionDefinitionIR, invocation.action_definition),
        target_resolution=target_resolution,
        window=f"ability_task_graph:{task_id}",
    )


def _binding_sources(
    rules: RuleBook,
    state: BattleState,
    actor_id: str,
    primary_target: str | None,
    *,
    action_level: int | None = None,
    current_action_trigger_key: str | None = None,
) -> tuple[dict[str, JSONValue], ...]:
    unit_ids = tuple(dict.fromkeys(unit_id for unit_id in (actor_id, primary_target) if unit_id))
    return (
        binding_source_from_store(store_from_state(state)),
        *character_skill_param_binding_sources(
            rules,
            state,
            (actor_id,),
            action_level=action_level,
            current_action_trigger_key=current_action_trigger_key,
        ),
        *status_binding_sources(state, unit_ids),
    )


def _action_trigger_key(action_definition: ActionDefinitionIR) -> str:
    return action_definition.skill_trigger_key


def _damage_targets_for_emission(
    target_group: str,
    target_resolution: TargetResolution,
) -> tuple[str, ...]:
    selected = tuple(target_resolution.selected)
    primary = target_resolution.primary or (selected[0] if selected else None)
    impact_group = tuple(target_resolution.impact_group) or selected
    if target_group in {"selected", "single"}:
        return selected
    if target_group == "primary":
        return (primary,) if primary else ()
    if target_group == "adjacent":
        return tuple(target_id for target_id in impact_group if target_id != primary)
    if target_group in {"aoe", "all_enemy"}:
        return impact_group
    return ()


def _expression_binding_sources(expression: object) -> tuple[dict[str, JSONValue], ...]:
    if not isinstance(expression, dict):
        return ()
    source = expression.get("binding_source")
    return (
        ({**source, "binding_role": "compiled_expression_fallback"},)
        if isinstance(source, dict)
        else ()
    )
