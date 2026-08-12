from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, cast

from ..core.model import BattleState, GameEvent, JSONValue, Mutation, RNGEvent
from ..core.reducer import MutationReducer
from ..core.transition_outcome import ExecutionNodeResult, TransitionOutcome
from ..immutable_json import freeze_json, thaw_json
from ..rules.task_graph import (
    TaskGraphDefinitionReferenceIR,
    TaskGraphIR,
    TaskGraphNodeIR,
    TaskGraphNumericDefinitionIR,
)


HookStatus = Literal["resolved", "blocked"]
ProjectionStatus = Literal["complete", "blocked"]
_RESERVED_IDENTITY_FIELDS = frozenset(
    {"task_graph_graph_id", "task_graph_node_id", "task_graph_execution_id"}
)


def _stable_id(prefix: str, *values: object) -> str:
    raw = json.dumps(values, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _strings(values: object, subject: str, *, unique: bool = True) -> tuple[str, ...]:
    if isinstance(values, str) or not isinstance(values, (list, tuple)):
        raise TypeError(f"{subject} must be a sequence")
    result = tuple(values)
    if any(not isinstance(item, str) or not item for item in result):
        raise ValueError(f"{subject} contains an invalid identity")
    if unique and len(result) != len(set(result)):
        raise ValueError(f"{subject} contains duplicate identities")
    return result


def _frozen_object(value: object, subject: str) -> Mapping[str, JSONValue]:
    frozen = freeze_json(value)
    if not isinstance(frozen, Mapping):
        raise TypeError(f"{subject} must be a JSON object")
    return cast(Mapping[str, JSONValue], frozen)


@dataclass(frozen=True)
class TaskGraphExecutionContext:
    invocation_id: str
    values: Mapping[str, JSONValue] = field(default_factory=dict)
    active_graph_stack: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphExecutionContext:
            raise TypeError("task graph execution context must not be subclassed")
        if not isinstance(self.invocation_id, str) or not self.invocation_id:
            raise ValueError("task graph invocation identity is required")
        stack = _strings(self.active_graph_stack, "task graph active stack")
        object.__setattr__(self, "active_graph_stack", stack)
        object.__setattr__(self, "values", _frozen_object(self.values, "task graph context"))


@dataclass(frozen=True)
class TaskGraphHookRequest:
    invocation_id: str
    graph_id: str
    graph_node_id: str
    formal_task_id: str
    opcode: str
    source_family: str
    references: tuple[TaskGraphDefinitionReferenceIR, ...]
    context_values: Mapping[str, JSONValue]
    active_graph_stack: tuple[str, ...]
    frame_ids: tuple[str, ...]
    target_ids: tuple[str, ...]
    iteration_index: int | None

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphHookRequest:
            raise TypeError("task graph hook request must not be subclassed")
        for value in (
            self.invocation_id,
            self.graph_id,
            self.graph_node_id,
            self.formal_task_id,
            self.opcode,
            self.source_family,
        ):
            if not isinstance(value, str) or not value:
                raise ValueError("task graph hook request identity is incomplete")
        references = tuple(self.references)
        if any(type(item) is not TaskGraphDefinitionReferenceIR for item in references):
            raise TypeError("task graph hook references are invalid")
        if self.iteration_index is not None and (
            type(self.iteration_index) is not int or self.iteration_index < 0
        ):
            raise ValueError("task graph hook iteration index is invalid")
        object.__setattr__(self, "references", references)
        object.__setattr__(
            self, "context_values", _frozen_object(self.context_values, "task graph hook context")
        )
        object.__setattr__(
            self, "active_graph_stack", _strings(self.active_graph_stack, "task graph hook stack")
        )
        object.__setattr__(self, "frame_ids", _strings(self.frame_ids, "task graph frame identities"))
        object.__setattr__(self, "target_ids", _strings(self.target_ids, "task graph hook targets"))


@dataclass(frozen=True)
class TaskGraphConditionResult:
    status: HookStatus
    value: bool | None = None
    progress_remaining: int | None = None
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphConditionResult:
            raise TypeError("task graph condition result must not be subclassed")
        if not isinstance(self.blocked_reason, str):
            raise TypeError("task graph condition blocker must be a string")
        if self.status == "resolved":
            if type(self.value) is not bool or self.blocked_reason:
                raise ValueError("resolved task graph condition is inconsistent")
            if self.progress_remaining is not None and (
                type(self.progress_remaining) is not int or self.progress_remaining < 0
            ):
                raise ValueError("task graph progress measure is invalid")
        elif self.status == "blocked":
            if self.value is not None or self.progress_remaining is not None or not self.blocked_reason:
                raise ValueError("blocked task graph condition is inconsistent")
        else:
            raise ValueError("task graph condition status is invalid")


@dataclass(frozen=True)
class TaskGraphBranchResult:
    status: HookStatus
    branch_kind: str = ""
    label: str = ""
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphBranchResult:
            raise TypeError("task graph branch result must not be subclassed")
        if not all(
            isinstance(item, str)
            for item in (self.branch_kind, self.label, self.blocked_reason)
        ):
            raise TypeError("task graph branch fields must be strings")
        if self.status == "resolved":
            if not self.branch_kind or self.blocked_reason:
                raise ValueError("resolved task graph branch is inconsistent")
        elif self.status == "blocked":
            if self.branch_kind or self.label or not self.blocked_reason:
                raise ValueError("blocked task graph branch is inconsistent")
        else:
            raise ValueError("task graph branch status is invalid")


@dataclass(frozen=True)
class TaskGraphCountResult:
    status: HookStatus
    count: int | None = None
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphCountResult:
            raise TypeError("task graph count result must not be subclassed")
        if not isinstance(self.blocked_reason, str):
            raise TypeError("task graph count blocker must be a string")
        if self.status == "resolved":
            if type(self.count) is not int or self.count < 0 or self.blocked_reason:
                raise ValueError("resolved task graph count is inconsistent")
        elif self.status == "blocked":
            if self.count is not None or not self.blocked_reason:
                raise ValueError("blocked task graph count is inconsistent")
        else:
            raise ValueError("task graph count status is invalid")


@dataclass(frozen=True)
class TaskGraphTargetResult:
    status: HookStatus
    target_ids: tuple[str, ...] = ()
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphTargetResult:
            raise TypeError("task graph target result must not be subclassed")
        if not isinstance(self.blocked_reason, str):
            raise TypeError("task graph target blocker must be a string")
        targets = _strings(self.target_ids, "task graph resolved targets")
        if self.status == "resolved":
            if self.blocked_reason:
                raise ValueError("resolved task graph targets carry a blocker")
        elif self.status == "blocked":
            if targets or not self.blocked_reason:
                raise ValueError("blocked task graph targets are inconsistent")
        else:
            raise ValueError("task graph target status is invalid")
        object.__setattr__(self, "target_ids", targets)


@dataclass(frozen=True)
class TaskGraphSettlementRecord:
    record_type: str
    source: str
    mutation_id: str | None = None
    process_only: bool = False
    payload: Mapping[str, JSONValue] = field(default_factory=dict)
    trace: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphSettlementRecord:
            raise TypeError("task graph settlement record must not be subclassed")
        if (
            not isinstance(self.record_type, str)
            or not self.record_type
            or not isinstance(self.source, str)
            or not self.source
        ):
            raise ValueError("task graph settlement identity is incomplete")
        if type(self.process_only) is not bool:
            raise TypeError("task graph settlement process marker must be bool")
        if self.mutation_id is not None and (
            not isinstance(self.mutation_id, str) or not self.mutation_id
        ):
            raise ValueError("task graph settlement mutation identity is invalid")
        if not self.process_only and self.mutation_id is None:
            raise ValueError("task graph settlement must link a mutation or be process-only")
        object.__setattr__(self, "payload", _frozen_object(self.payload, "task graph settlement payload"))
        object.__setattr__(self, "trace", _frozen_object(self.trace, "task graph settlement trace"))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "record_type": self.record_type,
            "source": self.source,
            "mutation_id": self.mutation_id,
            "process_only": self.process_only,
            "payload": cast(JSONValue, thaw_json(self.payload)),
            "trace": cast(JSONValue, thaw_json(self.trace)),
        }


def _freeze_event(event: GameEvent) -> GameEvent:
    if type(event) is not GameEvent:
        raise TypeError("task graph leaf events must use exact GameEvent values")
    if not isinstance(event.event_type, str) or not event.event_type:
        raise ValueError("task graph leaf event type is invalid")
    if type(event.process_only) is not bool:
        raise TypeError("task graph leaf event process marker must be bool")
    if not isinstance(event.event_id, str) or not isinstance(event.window, str):
        raise TypeError("task graph leaf event identity is invalid")
    if event.source_id is not None and not isinstance(event.source_id, str):
        raise TypeError("task graph leaf event source is invalid")
    if event.target_id is not None and not isinstance(event.target_id, str):
        raise TypeError("task graph leaf event target is invalid")
    return GameEvent(
        event_type=event.event_type,
        source_id=event.source_id,
        target_id=event.target_id,
        event_id=event.event_id,
        window=event.window,
        process_only=event.process_only,
        payload=cast(
            dict[str, JSONValue], _frozen_object(event.payload, "task graph event payload")
        ),
    )


def _freeze_rng_event(event: RNGEvent) -> RNGEvent:
    if type(event) is not RNGEvent:
        raise TypeError("task graph leaf RNG events must use exact RNGEvent values")
    if (
        not isinstance(event.rng_type, str)
        or not event.rng_type
        or not isinstance(event.source, str)
        or not event.source
    ):
        raise ValueError("task graph leaf RNG event identity is invalid")
    if not isinstance(event.event_id, str):
        raise TypeError("task graph leaf RNG identity is invalid")
    if event.before_state is not None and not isinstance(event.before_state, str):
        raise TypeError("task graph leaf RNG before state is invalid")
    if event.after_state is not None and not isinstance(event.after_state, str):
        raise TypeError("task graph leaf RNG after state is invalid")
    return RNGEvent(
        rng_type=event.rng_type,
        source=event.source,
        result=cast(JSONValue, freeze_json(event.result)),
        event_id=event.event_id,
        before_state=event.before_state,
        after_state=event.after_state,
        metadata=cast(
            dict[str, JSONValue], _frozen_object(event.metadata, "task graph RNG metadata")
        ),
    )


@dataclass(frozen=True)
class TaskGraphLeafResult:
    status: HookStatus
    mutations: tuple[Mutation, ...] = ()
    events: tuple[GameEvent, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    settlement_records: tuple[TaskGraphSettlementRecord, ...] = ()
    outcome_kind: str = "success"
    outcome_label: str = ""
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphLeafResult:
            raise TypeError("task graph leaf result must not be subclassed")
        if not all(
            isinstance(item, str)
            for item in (self.outcome_kind, self.outcome_label, self.blocked_reason)
        ):
            raise TypeError("task graph leaf outcome fields must be strings")
        mutations = tuple(self.mutations)
        if any(type(item) is not Mutation for item in mutations):
            raise TypeError("task graph leaf mutations are invalid")
        if len({item.stable_id() for item in mutations}) != len(mutations):
            raise ValueError("task graph leaf mutations contain duplicate identities")
        events = tuple(_freeze_event(item) for item in self.events)
        rng_events = tuple(_freeze_rng_event(item) for item in self.rng_events)
        event_ids = tuple(cast(str, item.to_json()["event_id"]) for item in events)
        rng_ids = tuple(cast(str, item.to_json()["event_id"]) for item in rng_events)
        if len(event_ids) != len(set(event_ids)) or len(rng_ids) != len(set(rng_ids)):
            raise ValueError("task graph leaf events contain duplicate identities")
        records = tuple(self.settlement_records)
        if any(type(item) is not TaskGraphSettlementRecord for item in records):
            raise TypeError("task graph leaf settlement records are invalid")
        mutation_ids = {item.stable_id() for item in mutations}
        if any(
            not item.process_only and item.mutation_id not in mutation_ids
            for item in records
        ):
            raise ValueError("task graph leaf settlement is not linked to its mutation")
        if self.status == "resolved":
            if not self.outcome_kind or self.blocked_reason:
                raise ValueError("resolved task graph leaf result is inconsistent")
        elif self.status == "blocked":
            if (
                mutations
                or events
                or rng_events
                or records
                or self.outcome_kind
                or self.outcome_label
                or not self.blocked_reason
            ):
                raise ValueError("blocked task graph leaf result leaks formal channels")
        else:
            raise ValueError("task graph leaf result status is invalid")
        object.__setattr__(self, "mutations", mutations)
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "rng_events", rng_events)
        object.__setattr__(self, "settlement_records", records)


@dataclass(frozen=True)
class TaskGraphGraphResult:
    status: HookStatus
    definition_id: str = ""
    graph: TaskGraphIR | None = None
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphGraphResult:
            raise TypeError("task graph resolver result must not be subclassed")
        if not isinstance(self.definition_id, str) or not isinstance(
            self.blocked_reason, str
        ):
            raise TypeError("task graph resolver fields must be strings")
        if self.status == "resolved":
            if (
                not self.definition_id
                or type(self.graph) is not TaskGraphIR
                or self.blocked_reason
            ):
                raise ValueError("resolved nested task graph is inconsistent")
        elif self.status == "blocked":
            if self.definition_id or self.graph is not None or not self.blocked_reason:
                raise ValueError("blocked nested task graph is inconsistent")
        else:
            raise ValueError("nested task graph status is invalid")


@dataclass(frozen=True)
class TaskGraphExecutionHooks:
    leaf: Callable[[TaskGraphHookRequest, BattleState], TaskGraphLeafResult] | None = None
    condition: Callable[[TaskGraphHookRequest, BattleState], TaskGraphConditionResult] | None = None
    branch: Callable[[TaskGraphHookRequest, BattleState], TaskGraphBranchResult] | None = None
    count: Callable[
        [TaskGraphHookRequest, TaskGraphNumericDefinitionIR, BattleState],
        TaskGraphCountResult,
    ] | None = None
    targets: Callable[[TaskGraphHookRequest, BattleState], TaskGraphTargetResult] | None = None
    graph: Callable[[TaskGraphHookRequest, BattleState], TaskGraphGraphResult] | None = None

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphExecutionHooks:
            raise TypeError("task graph hooks must not be subclassed")
        for name in ("leaf", "condition", "branch", "count", "targets", "graph"):
            value = getattr(self, name)
            if value is not None and not callable(value):
                raise TypeError(f"task graph {name} hook must be callable")


@dataclass(frozen=True)
class TaskGraphNodeProjection:
    execution_id: str
    graph_id: str
    graph_node_id: str
    formal_task_id: str
    path: tuple[str, ...]
    status: ProjectionStatus
    reason_code: str = ""

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphNodeProjection:
            raise TypeError("task graph node projection must not be subclassed")
        if not all(
            isinstance(item, str)
            for item in (
                self.execution_id,
                self.graph_id,
                self.graph_node_id,
                self.formal_task_id,
                self.reason_code,
            )
        ):
            raise TypeError("task graph node projection fields must be strings")
        path = _strings(self.path, "task graph execution path", unique=False)
        expected = _stable_id(
            "task_graph_execution", self.graph_id, self.graph_node_id, *path
        )
        if self.execution_id != expected or not self.formal_task_id:
            raise ValueError("task graph node projection identity is inconsistent")
        if self.status == "complete":
            if self.reason_code:
                raise ValueError("complete task graph projection carries a blocker")
        elif self.status == "blocked":
            if not self.reason_code:
                raise ValueError("blocked task graph projection lacks a reason")
        else:
            raise ValueError("task graph projection status is invalid")
        object.__setattr__(self, "path", path)

    def to_node_result(self) -> ExecutionNodeResult:
        return ExecutionNodeResult(
            node_kind="task_graph_node",
            node_id=self.execution_id,
            status=self.status,
            reason_code=self.reason_code,
        )


@dataclass(frozen=True)
class TaskGraphExecutionResult:
    ok: bool
    before_state: BattleState
    after_state: BattleState
    mutations: tuple[Mutation, ...] = ()
    events: tuple[GameEvent, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    settlement_records: tuple[TaskGraphSettlementRecord, ...] = ()
    node_projections: tuple[TaskGraphNodeProjection, ...] = ()
    outcome: TransitionOutcome = field(
        default_factory=lambda: TransitionOutcome("blocked", ("task_graph_unclassified",))
    )
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphExecutionResult or type(self.ok) is not bool:
            raise TypeError("task graph execution result uses an invalid type")
        if type(self.before_state) is not BattleState or type(self.after_state) is not BattleState:
            raise TypeError("task graph result states must use exact BattleState values")
        mutations = tuple(self.mutations)
        events = tuple(_freeze_event(item) for item in self.events)
        rng_events = tuple(_freeze_rng_event(item) for item in self.rng_events)
        records = tuple(self.settlement_records)
        projections = tuple(self.node_projections)
        errors = _strings(self.errors, "task graph execution errors")
        if any(type(item) is not Mutation for item in mutations):
            raise TypeError("task graph result mutations are invalid")
        mutation_ids = tuple(item.stable_id() for item in mutations)
        event_ids = tuple(cast(str, item.to_json()["event_id"]) for item in events)
        rng_ids = tuple(cast(str, item.to_json()["event_id"]) for item in rng_events)
        if (
            len(mutation_ids) != len(set(mutation_ids))
            or len(event_ids) != len(set(event_ids))
            or len(rng_ids) != len(set(rng_ids))
        ):
            raise ValueError("task graph result contains duplicate channel identities")
        if any(type(item) is not TaskGraphSettlementRecord for item in records) or any(
            type(item) is not TaskGraphNodeProjection for item in projections
        ):
            raise TypeError("task graph result records or projections are invalid")
        if type(self.outcome) is not TransitionOutcome:
            raise TypeError("task graph result outcome is invalid")
        if type(self.outcome.reason_codes) is not tuple or type(
            self.outcome.node_results
        ) is not tuple or any(
            type(item) is not ExecutionNodeResult for item in self.outcome.node_results
        ):
            raise TypeError("task graph result outcome is not recursively immutable")
        if any(
            not item.process_only and item.mutation_id not in set(mutation_ids)
            for item in records
        ):
            raise ValueError("task graph result settlement is not linked to a mutation")
        if len({item.execution_id for item in projections}) != len(projections):
            raise ValueError("task graph result contains duplicate execution identities")
        expected_nodes = tuple(item.to_node_result() for item in projections)
        if self.outcome.node_results != expected_nodes:
            raise ValueError("task graph result outcome does not match node projections")
        if self.ok:
            if (
                errors
                or not projections
                or self.outcome.category != "committed"
                or self.outcome.reason_codes
                or any(item.status != "complete" for item in projections)
            ):
                raise ValueError("successful task graph result is inconsistent")
            reduction = MutationReducer().apply_all_result(self.before_state, mutations)
            if not reduction.ok or reduction.after_state != self.after_state:
                raise ValueError("task graph result state is inconsistent with mutations")
        elif (
            self.after_state is not self.before_state
            or mutations
            or events
            or rng_events
            or records
            or not errors
            or self.outcome.category != "blocked"
            or self.outcome.reason_codes != errors
        ):
            raise ValueError("blocked task graph result leaks formal execution channels")
        object.__setattr__(self, "mutations", mutations)
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "rng_events", rng_events)
        object.__setattr__(self, "settlement_records", records)
        object.__setattr__(self, "node_projections", projections)
        object.__setattr__(self, "errors", errors)


@dataclass(frozen=True)
class _TemplateFrame:
    frame_id: str
    graph_id: str
    sequences: Mapping[str, tuple[str, ...]]


class _ExecutionBlocked(RuntimeError):
    pass


class _TaskGraphRun:
    def __init__(
        self,
        state: BattleState,
        context: TaskGraphExecutionContext,
        hooks: TaskGraphExecutionHooks,
    ) -> None:
        self.before_state = state
        self.state = state
        self.context = context
        self.hooks = hooks
        self.active_graphs = list(context.active_graph_stack)
        self.frames: list[_TemplateFrame] = []
        self.target_stack: list[tuple[str, ...]] = []
        self.iteration_stack: list[int] = []
        self.mutations: list[Mutation] = []
        self.events: list[GameEvent] = []
        self.rng_events: list[RNGEvent] = []
        self.records: list[TaskGraphSettlementRecord] = []
        self.projections: list[TaskGraphNodeProjection] = []
        self.execution_ids: set[str] = set()
        self.mutation_ids: set[str] = set()
        self.event_ids: set[str] = set()
        self.rng_event_ids: set[str] = set()

    def execute_graph(self, graph: TaskGraphIR, path: tuple[str, ...]) -> None:
        if graph.graph_id in self.active_graphs:
            raise _ExecutionBlocked(f"task_graph_active_cycle:{graph.graph_id}")
        self.active_graphs.append(graph.graph_id)
        try:
            node_by_id = {item.graph_node_id: item for item in graph.nodes}
            for ordinal, root_id in enumerate(graph.root_node_ids):
                node = node_by_id.get(root_id)
                if node is None:
                    raise _ExecutionBlocked(f"task_graph_root_missing:{root_id}")
                self.execute_node(
                    graph,
                    node,
                    node_by_id,
                    (*path, f"root:{ordinal}"),
                )
        finally:
            self.active_graphs.pop()

    def execute_node(
        self,
        graph: TaskGraphIR,
        node: TaskGraphNodeIR,
        node_by_id: Mapping[str, TaskGraphNodeIR],
        path: tuple[str, ...],
    ) -> None:
        execution_id = _stable_id(
            "task_graph_execution", graph.graph_id, node.graph_node_id, *path
        )
        if execution_id in self.execution_ids:
            raise _ExecutionBlocked(f"task_graph_duplicate_execution_identity:{execution_id}")
        self.execution_ids.add(execution_id)
        projection_index = len(self.projections)
        try:
            if node.materialization_status != "materialized" or node.node_kind == "deferred":
                raise _ExecutionBlocked(
                    node.status_reason or f"task_graph_selected_node_not_materialized:{node.graph_node_id}"
                )
            dispatch = {
                "leaf": self._execute_leaf_or_sequence,
                "sequence": self._execute_leaf_or_sequence,
                "branch": self._execute_branch,
                "loop": self._execute_loop,
                "target_scope": self._execute_target_scope,
                "template_call": self._execute_template_call,
                "template_parameter": self._execute_template_parameter,
                "ability_call": self._execute_ability_call,
            }.get(node.node_kind)
            if dispatch is None:
                raise _ExecutionBlocked(f"task_graph_node_kind_not_executable:{node.node_kind}")
            dispatch(graph, node, node_by_id, path)
        except _ExecutionBlocked as exc:
            self.projections.insert(
                projection_index,
                TaskGraphNodeProjection(
                    execution_id,
                    graph.graph_id,
                    node.graph_node_id,
                    node.formal_task_id,
                    path,
                    "blocked",
                    str(exc),
                ),
            )
            raise
        self.projections.insert(
            projection_index,
            TaskGraphNodeProjection(
                execution_id,
                graph.graph_id,
                node.graph_node_id,
                node.formal_task_id,
                path,
                "complete",
            ),
        )

    def request(self, graph: TaskGraphIR, node: TaskGraphNodeIR) -> TaskGraphHookRequest:
        return TaskGraphHookRequest(
            self.context.invocation_id,
            graph.graph_id,
            node.graph_node_id,
            node.formal_task_id,
            node.opcode,
            node.source_family,
            node.references,
            self.context.values,
            tuple(self.active_graphs),
            tuple(item.frame_id for item in self.frames),
            self.target_stack[-1] if self.target_stack else (),
            self.iteration_stack[-1] if self.iteration_stack else None,
        )

    def call_hook(self, name: str, *args: object) -> object:
        hook = getattr(self.hooks, name)
        if hook is None:
            raise _ExecutionBlocked(f"task_graph_hook_missing:{name}")
        try:
            return hook(*args)
        except _ExecutionBlocked:
            raise
        except Exception as exc:
            raise _ExecutionBlocked(
                f"task_graph_hook_raised:{name}:{type(exc).__name__}"
            ) from exc

    def _children(
        self,
        graph: TaskGraphIR,
        node_by_id: Mapping[str, TaskGraphNodeIR],
        child_ids: tuple[str, ...],
        path: tuple[str, ...],
    ) -> None:
        for ordinal, child_id in enumerate(child_ids):
            child = node_by_id.get(child_id)
            if child is None:
                raise _ExecutionBlocked(f"task_graph_child_missing:{child_id}")
            self.execute_node(graph, child, node_by_id, (*path, f"child:{ordinal}"))

    def _branch_children(
        self,
        node: TaskGraphNodeIR,
        branch_kind: str,
        label: str = "",
        *,
        allow_absent: bool = False,
    ) -> tuple[str, ...]:
        matches = tuple(
            item
            for item in node.branches
            if item.branch_kind == branch_kind and (not label or item.label == label)
        )
        if len(matches) > 1:
            raise _ExecutionBlocked(
                f"task_graph_branch_ambiguous:{node.graph_node_id}:{branch_kind}:{label}"
            )
        if not matches:
            if allow_absent:
                return ()
            raise _ExecutionBlocked(
                f"task_graph_branch_missing:{node.graph_node_id}:{branch_kind}:{label}"
            )
        return matches[0].child_node_ids

    def _execute_leaf_or_sequence(
        self,
        graph: TaskGraphIR,
        node: TaskGraphNodeIR,
        node_by_id: Mapping[str, TaskGraphNodeIR],
        path: tuple[str, ...],
    ) -> None:
        result = self.call_hook("leaf", self.request(graph, node), self.state)
        if type(result) is not TaskGraphLeafResult:
            raise _ExecutionBlocked("task_graph_leaf_hook_result_type_invalid")
        if result.status == "blocked":
            raise _ExecutionBlocked(result.blocked_reason)
        self._admit_leaf(result)
        if not node.branches:
            return
        exact = tuple(
            item for item in node.branches
            if item.branch_kind == result.outcome_kind
            and (not result.outcome_label or item.label == result.outcome_label)
        )
        if len(exact) == 1:
            children = exact[0].child_node_ids
        elif not exact and result.outcome_kind in {"success", "failed"}:
            children = ()
        else:
            raise _ExecutionBlocked(
                f"task_graph_leaf_outcome_not_admitted:{result.outcome_kind}:{result.outcome_label}"
            )
        self._children(graph, node_by_id, children, (*path, "continuation"))

    def _admit_leaf(self, result: TaskGraphLeafResult) -> None:
        for mutation in result.mutations:
            if _RESERVED_IDENTITY_FIELDS.intersection(mutation.metadata):
                raise _ExecutionBlocked("task_graph_leaf_forged_execution_identity")
            if mutation.stable_id() in self.mutation_ids:
                raise _ExecutionBlocked(f"task_graph_duplicate_mutation_identity:{mutation.stable_id()}")
        for event in result.events:
            if _RESERVED_IDENTITY_FIELDS.intersection(event.payload):
                raise _ExecutionBlocked("task_graph_leaf_forged_execution_identity")
            event_id = cast(str, event.to_json()["event_id"])
            if event_id in self.event_ids:
                raise _ExecutionBlocked(f"task_graph_duplicate_event_identity:{event_id}")
        for event in result.rng_events:
            if _RESERVED_IDENTITY_FIELDS.intersection(event.metadata):
                raise _ExecutionBlocked("task_graph_leaf_forged_execution_identity")
            if isinstance(event.result, Mapping) and _RESERVED_IDENTITY_FIELDS.intersection(
                event.result
            ):
                raise _ExecutionBlocked("task_graph_leaf_forged_execution_identity")
            event_id = cast(str, event.to_json()["event_id"])
            if event_id in self.rng_event_ids:
                raise _ExecutionBlocked(f"task_graph_duplicate_rng_identity:{event_id}")
        if any(
            _RESERVED_IDENTITY_FIELDS.intersection(item.payload)
            or _RESERVED_IDENTITY_FIELDS.intersection(item.trace)
            for item in result.settlement_records
        ):
            raise _ExecutionBlocked("task_graph_leaf_forged_execution_identity")
        reduction = MutationReducer().apply_all_result(self.state, result.mutations)
        if not reduction.ok:
            code = reduction.conflicts[0].code if reduction.conflicts else "unknown"
            raise _ExecutionBlocked(f"task_graph_leaf_mutation_conflict:{code}")
        self.state = reduction.after_state
        self.mutations.extend(result.mutations)
        self.events.extend(result.events)
        self.rng_events.extend(result.rng_events)
        self.records.extend(result.settlement_records)
        self.mutation_ids.update(item.stable_id() for item in result.mutations)
        self.event_ids.update(cast(str, item.to_json()["event_id"]) for item in result.events)
        self.rng_event_ids.update(cast(str, item.to_json()["event_id"]) for item in result.rng_events)

    def _execute_branch(
        self,
        graph: TaskGraphIR,
        node: TaskGraphNodeIR,
        node_by_id: Mapping[str, TaskGraphNodeIR],
        path: tuple[str, ...],
    ) -> None:
        kinds = {item.branch_kind for item in node.branches}
        if kinds <= {"success", "failed"}:
            result = self.call_hook("condition", self.request(graph, node), self.state)
            if type(result) is not TaskGraphConditionResult:
                raise _ExecutionBlocked("task_graph_condition_hook_result_type_invalid")
            if result.status == "blocked":
                raise _ExecutionBlocked(result.blocked_reason)
            kind, label = ("success" if result.value else "failed"), ""
            children = self._branch_children(node, kind, allow_absent=True)
        else:
            result = self.call_hook("branch", self.request(graph, node), self.state)
            if type(result) is not TaskGraphBranchResult:
                raise _ExecutionBlocked("task_graph_branch_hook_result_type_invalid")
            if result.status == "blocked":
                raise _ExecutionBlocked(result.blocked_reason)
            kind, label = result.branch_kind, result.label
            children = self._branch_children(
                node,
                kind,
                label,
                allow_absent=(kind == "default"),
            )
        self._children(graph, node_by_id, children, (*path, f"branch:{kind}:{label}"))

    def _execute_loop(
        self,
        graph: TaskGraphIR,
        node: TaskGraphNodeIR,
        node_by_id: Mapping[str, TaskGraphNodeIR],
        path: tuple[str, ...],
    ) -> None:
        body = self._branch_children(node, "task_list", allow_absent=True)
        if node.termination_kind == "count_expression":
            count = self._resolve_count(graph, node)
            if count and not body:
                raise _ExecutionBlocked("task_graph_loop_body_empty")
            for index in range(count):
                self._loop_body(graph, node_by_id, body, path, index)
            return
        if node.termination_kind == "condition_with_source_cap":
            count = self._resolve_count(graph, node)
            if count and not body:
                raise _ExecutionBlocked("task_graph_loop_body_empty")
            for index in range(count):
                condition = self._resolve_condition(graph, node)
                if not condition.value:
                    break
                self._loop_body(graph, node_by_id, body, path, index)
            return
        if node.termination_kind == "condition_progress_required":
            if not body:
                raise _ExecutionBlocked("task_graph_loop_body_empty")
            prior: int | None = None
            index = 0
            while True:
                condition = self._resolve_condition(graph, node)
                if not condition.value:
                    return
                remaining = condition.progress_remaining
                if remaining is None or remaining <= 0 or (
                    prior is not None and remaining >= prior
                ):
                    raise _ExecutionBlocked("task_graph_loop_progress_not_proven")
                prior = remaining
                self._loop_body(graph, node_by_id, body, path, index)
                index += 1
        elif node.termination_kind == "finite_target_collection":
            targets = self._resolve_targets(graph, node)
            if targets and not body:
                raise _ExecutionBlocked("task_graph_loop_body_empty")
            for index, target_id in enumerate(targets):
                self.target_stack.append((target_id,))
                try:
                    self._loop_body(graph, node_by_id, body, path, index)
                finally:
                    self.target_stack.pop()
        else:
            raise _ExecutionBlocked(
                f"task_graph_loop_termination_not_admitted:{node.termination_kind}"
            )

    def _loop_body(
        self,
        graph: TaskGraphIR,
        node_by_id: Mapping[str, TaskGraphNodeIR],
        body: tuple[str, ...],
        path: tuple[str, ...],
        index: int,
    ) -> None:
        self.iteration_stack.append(index)
        try:
            self._children(graph, node_by_id, body, (*path, f"iteration:{index}"))
        finally:
            self.iteration_stack.pop()

    def _resolve_condition(
        self, graph: TaskGraphIR, node: TaskGraphNodeIR
    ) -> TaskGraphConditionResult:
        result = self.call_hook("condition", self.request(graph, node), self.state)
        if type(result) is not TaskGraphConditionResult:
            raise _ExecutionBlocked("task_graph_condition_hook_result_type_invalid")
        if result.status == "blocked":
            raise _ExecutionBlocked(result.blocked_reason)
        return result

    def _resolve_count(self, graph: TaskGraphIR, node: TaskGraphNodeIR) -> int:
        definitions = tuple(
            item
            for item in graph.numeric_definitions
            if item.definition_id == node.termination_numeric_definition_id
        )
        if len(definitions) != 1:
            raise _ExecutionBlocked("task_graph_loop_numeric_definition_not_unique")
        result = self.call_hook(
            "count", self.request(graph, node), definitions[0], self.state
        )
        if type(result) is not TaskGraphCountResult:
            raise _ExecutionBlocked("task_graph_count_hook_result_type_invalid")
        if result.status == "blocked":
            raise _ExecutionBlocked(result.blocked_reason)
        return cast(int, result.count)

    def _resolve_targets(
        self, graph: TaskGraphIR, node: TaskGraphNodeIR
    ) -> tuple[str, ...]:
        result = self.call_hook("targets", self.request(graph, node), self.state)
        if type(result) is not TaskGraphTargetResult:
            raise _ExecutionBlocked("task_graph_target_hook_result_type_invalid")
        if result.status == "blocked":
            raise _ExecutionBlocked(result.blocked_reason)
        return result.target_ids

    def _execute_target_scope(
        self,
        graph: TaskGraphIR,
        node: TaskGraphNodeIR,
        node_by_id: Mapping[str, TaskGraphNodeIR],
        path: tuple[str, ...],
    ) -> None:
        targets = self._resolve_targets(graph, node)
        if not targets:
            children = self._branch_children(
                node, "target_scope_failed", allow_absent=True
            )
            self._children(graph, node_by_id, children, (*path, "target_scope_failed"))
            return
        candidates = tuple(
            item
            for item in node.branches
            if item.branch_kind in {"target_scope", "status_scope", "ordered_target_scope"}
        )
        if len(candidates) != 1:
            raise _ExecutionBlocked("task_graph_target_scope_branch_not_unique")
        self.target_stack.append(targets)
        try:
            self._children(
                graph,
                node_by_id,
                candidates[0].child_node_ids,
                (*path, f"target_scope:{candidates[0].branch_kind}"),
            )
        finally:
            self.target_stack.pop()

    def _execute_template_call(
        self,
        graph: TaskGraphIR,
        node: TaskGraphNodeIR,
        node_by_id: Mapping[str, TaskGraphNodeIR],
        path: tuple[str, ...],
    ) -> None:
        refs = tuple(item for item in node.references if item.reference_kind == "template")
        if len(refs) != 1 or refs[0].resolution_status != "resolved":
            raise _ExecutionBlocked("task_graph_template_reference_not_resolved")
        sequences: dict[str, tuple[str, ...]] = {}
        bodies = []
        for branch in node.branches:
            if branch.branch_kind == "template_parameter_sequence":
                if not branch.label or branch.label in sequences:
                    raise _ExecutionBlocked("task_graph_template_parameter_frame_ambiguous")
                sequences[branch.label] = branch.child_node_ids
            elif branch.branch_kind == "template_body":
                bodies.append(branch)
        if len(bodies) != 1:
            raise _ExecutionBlocked("task_graph_template_body_not_unique")
        frame = _TemplateFrame(
            _stable_id(
                "task_graph_template_frame",
                self.context.invocation_id,
                graph.graph_id,
                node.graph_node_id,
                *path,
            ),
            graph.graph_id,
            MappingProxyType(dict(sequences)),
        )
        self.frames.append(frame)
        try:
            self._children(
                graph, node_by_id, bodies[0].child_node_ids, (*path, "template_body")
            )
        finally:
            self.frames.pop()

    def _execute_template_parameter(
        self,
        graph: TaskGraphIR,
        node: TaskGraphNodeIR,
        node_by_id: Mapping[str, TaskGraphNodeIR],
        path: tuple[str, ...],
    ) -> None:
        fetches = tuple(
            item for item in node.branches if item.branch_kind == "template_parameter_fetch"
        )
        if len(fetches) != 1 or fetches[0].child_node_ids or not fetches[0].label:
            raise _ExecutionBlocked("task_graph_template_parameter_fetch_invalid")
        for frame in reversed(self.frames):
            children = frame.sequences.get(fetches[0].label)
            if children is not None:
                self._children(
                    graph,
                    node_by_id,
                    children,
                    (*path, f"template_parameter:{fetches[0].label}"),
                )
                return
        raise _ExecutionBlocked(
            f"task_graph_template_parameter_unbound:{fetches[0].label}"
        )

    def _execute_ability_call(
        self,
        graph: TaskGraphIR,
        node: TaskGraphNodeIR,
        node_by_id: Mapping[str, TaskGraphNodeIR],
        path: tuple[str, ...],
    ) -> None:
        refs = tuple(item for item in node.references if item.reference_kind == "ability")
        if len(refs) != 1 or refs[0].resolution_status != "resolved":
            raise _ExecutionBlocked("task_graph_ability_reference_not_resolved")
        result = self.call_hook("graph", self.request(graph, node), self.state)
        if type(result) is not TaskGraphGraphResult:
            raise _ExecutionBlocked("task_graph_graph_hook_result_type_invalid")
        if result.status == "blocked":
            raise _ExecutionBlocked(result.blocked_reason)
        nested = cast(TaskGraphIR, result.graph)
        if result.definition_id != refs[0].definition_id:
            raise _ExecutionBlocked("task_graph_nested_definition_identity_mismatch")
        if (
            nested.source_catalog_id != graph.source_catalog_id
            or nested.source_fingerprint != graph.source_fingerprint
        ):
            raise _ExecutionBlocked("task_graph_nested_graph_authority_mismatch")
        structure_reason = TaskGraphExecutor._graph_structure_reason(nested)
        if structure_reason:
            raise _ExecutionBlocked(structure_reason)
        self.execute_graph(nested, (*path, f"ability:{refs[0].definition_id}"))
        if node.branches:
            children = self._branch_children(node, "success", allow_absent=True)
            self._children(graph, node_by_id, children, (*path, "ability_continuation"))


class TaskGraphExecutor:
    """Execute one admitted task graph as an all-or-nothing transaction."""

    def execute(
        self,
        state: BattleState,
        graph: TaskGraphIR,
        context: TaskGraphExecutionContext,
        hooks: TaskGraphExecutionHooks,
    ) -> TaskGraphExecutionResult:
        if type(state) is not BattleState:
            raise TypeError("task graph executor requires exact BattleState")
        reason = self._preflight(graph, context, hooks)
        if reason:
            return self._blocked(state, (), reason)
        run = _TaskGraphRun(state, context, hooks)
        try:
            run.execute_graph(graph, (f"invocation:{context.invocation_id}",))
        except _ExecutionBlocked as exc:
            return self._blocked(state, tuple(run.projections), str(exc))
        projections = tuple(run.projections)
        node_results = tuple(item.to_node_result() for item in projections)
        outcome = TransitionOutcome("committed", (), node_results)
        return TaskGraphExecutionResult(
            True,
            state,
            run.state,
            tuple(run.mutations),
            tuple(run.events),
            tuple(run.rng_events),
            tuple(run.records),
            projections,
            outcome,
            (),
        )

    @staticmethod
    def _preflight(
        graph: object, context: object, hooks: object
    ) -> str:
        if type(graph) is not TaskGraphIR:
            return "task_graph_input_type_invalid"
        if type(context) is not TaskGraphExecutionContext:
            return "task_graph_context_type_invalid"
        if type(hooks) is not TaskGraphExecutionHooks:
            return "task_graph_hooks_type_invalid"
        reason = TaskGraphExecutor._graph_structure_reason(graph)
        if reason:
            return reason
        if graph.graph_id in context.active_graph_stack:
            return f"task_graph_active_cycle:{graph.graph_id}"
        return ""

    @staticmethod
    def _graph_structure_reason(graph: TaskGraphIR) -> str:
        try:
            if TaskGraphIR.from_json(graph.to_json()) != graph:
                return "task_graph_canonical_round_trip_mismatch"
        except (AttributeError, TypeError, ValueError, KeyError):
            return "task_graph_structure_invalid"
        return ""

    @staticmethod
    def _blocked(
        state: BattleState,
        projections: tuple[TaskGraphNodeProjection, ...],
        reason: str,
    ) -> TaskGraphExecutionResult:
        node_results = tuple(item.to_node_result() for item in projections)
        outcome = TransitionOutcome("blocked", (reason,), node_results)
        return TaskGraphExecutionResult(
            False,
            state,
            state,
            node_projections=projections,
            outcome=outcome,
            errors=(reason,),
        )
