from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
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
    TaskGraphTemplateParameterIR,
    TaskGraphWeightedSelectionIR,
)
from .rng import RNGOutcome, RNGRequest, choice_key_for_identity, event_id_for_identity, resolve_rng_request


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
class TaskGraphStatusScope:
    owner_id: str
    instance_id: str

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphStatusScope:
            raise TypeError("task graph status scope must not be subclassed")
        if any(not isinstance(value, str) or not value for value in (self.owner_id, self.instance_id)):
            raise ValueError("task graph status scope identity is incomplete")


@dataclass(frozen=True)
class TaskGraphExecutionContext:
    invocation_id: str
    values: Mapping[str, JSONValue] = field(default_factory=dict)
    active_graph_stack: tuple[str, ...] = ()
    parent_execution_path: tuple[str, ...] = ()
    status_scope: TaskGraphStatusScope | None = None
    template_target_ids: tuple[str, ...] | None = None
    template_binding_sources: tuple[Mapping[str, JSONValue], ...] = ()
    trigger_event: GameEvent | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphExecutionContext:
            raise TypeError("task graph execution context must not be subclassed")
        if not isinstance(self.invocation_id, str) or not self.invocation_id:
            raise ValueError("task graph invocation identity is required")
        stack = _strings(self.active_graph_stack, "task graph active stack")
        object.__setattr__(self, "active_graph_stack", stack)
        object.__setattr__(self, "values", _frozen_object(self.values, "task graph context"))
        object.__setattr__(self, "parent_execution_path", _strings(
            self.parent_execution_path, "task graph parent execution path", unique=False))
        if self.trigger_event is not None and type(self.trigger_event) is not GameEvent:
            raise TypeError("task graph trigger event must retain the native GameEvent")
        if self.status_scope is not None and type(self.status_scope) is not TaskGraphStatusScope:
            raise TypeError("task graph context status scope is invalid")
        if self.template_target_ids is not None:
            object.__setattr__(self, "template_target_ids", _strings(
                self.template_target_ids, "task graph context template targets"))
        object.__setattr__(self, "template_binding_sources", tuple(
            _frozen_object(item, "task graph template bindings") for item in self.template_binding_sources))


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
    execution_path: tuple[str, ...]
    status_scope: TaskGraphStatusScope | None = None
    template_target_ids: tuple[str, ...] | None = None
    template_binding_sources: tuple[Mapping[str, JSONValue], ...] = ()
    trigger_event: GameEvent | None = field(default=None, repr=False, compare=False)

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
        active_graph_stack = _strings(self.active_graph_stack, "task graph hook stack")
        if not active_graph_stack or active_graph_stack[-1] != self.graph_id:
            raise ValueError("task graph hook stack does not end at the current graph")
        object.__setattr__(self, "active_graph_stack", active_graph_stack)
        object.__setattr__(self, "frame_ids", _strings(self.frame_ids, "task graph frame identities"))
        object.__setattr__(self, "target_ids", _strings(self.target_ids, "task graph hook targets"))
        path = _strings(self.execution_path, "task graph hook execution path", unique=False)
        if not path:
            raise ValueError("task graph hook execution path is missing")
        object.__setattr__(self, "execution_path", path)
        if self.trigger_event is not None and type(self.trigger_event) is not GameEvent:
            raise TypeError("task graph trigger event must retain the native GameEvent")
        if self.status_scope is not None and type(self.status_scope) is not TaskGraphStatusScope:
            raise TypeError("task graph hook status scope is invalid")
        if self.template_target_ids is not None:
            object.__setattr__(self, "template_target_ids", _strings(
                self.template_target_ids, "task graph hook template targets"))
        object.__setattr__(self, "template_binding_sources", tuple(
            _frozen_object(item, "task graph hook template bindings") for item in self.template_binding_sources))


@dataclass(frozen=True, init=False)
class TaskGraphContinuation:
    parent_invocation_id: str
    parent_graph_id: str
    parent_graph_node_id: str
    parent_formal_task_id: str
    context_values: Mapping[str, JSONValue]
    active_graph_stack: tuple[str, ...]
    parent_execution_path: tuple[str, ...]
    status_scope: TaskGraphStatusScope | None
    template_target_ids: tuple[str, ...] | None
    template_binding_sources: tuple[Mapping[str, JSONValue], ...]
    trigger_event: GameEvent | None

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("task graph continuation must be derived from a hook request")

    @classmethod
    def from_hook_request(cls, request: TaskGraphHookRequest) -> "TaskGraphContinuation":
        if cls is not TaskGraphContinuation or type(request) is not TaskGraphHookRequest:
            raise TypeError("task graph continuation requires an exact hook request")
        value = object.__new__(cls)
        object.__setattr__(value, "parent_invocation_id", request.invocation_id)
        object.__setattr__(value, "parent_graph_id", request.graph_id)
        object.__setattr__(value, "parent_graph_node_id", request.graph_node_id)
        object.__setattr__(value, "parent_formal_task_id", request.formal_task_id)
        object.__setattr__(value, "context_values", request.context_values)
        object.__setattr__(value, "active_graph_stack", request.active_graph_stack)
        object.__setattr__(value, "parent_execution_path", request.execution_path)
        object.__setattr__(value, "status_scope", request.status_scope)
        object.__setattr__(value, "template_target_ids", request.template_target_ids)
        object.__setattr__(value, "template_binding_sources", request.template_binding_sources)
        object.__setattr__(value, "trigger_event", request.trigger_event)
        return value

    def child_context(
        self,
        invocation_id: str,
        context_values: Mapping[str, JSONValue] | None = None,
    ) -> TaskGraphExecutionContext:
        if type(self) is not TaskGraphContinuation:
            raise TypeError("task graph continuation must use the exact runtime type")
        return TaskGraphExecutionContext(
            invocation_id,
            self.context_values if context_values is None else context_values,
            self.active_graph_stack,
            self.parent_execution_path,
            self.status_scope,
            self.template_target_ids,
            self.template_binding_sources,
            self.trigger_event,
        )


def with_template_binding_sources(sources, template_sources):
    """Lexical template arguments shadow outer hash/name slots, never peers."""
    if not template_sources:
        return tuple(sources)
    keys = {str(key) for source in template_sources for field in ("by_hash", "by_name", "values")
            for key in source.get(field, {})}
    outer = tuple({
        **{key: value for key, value in source.items() if key not in keys},
        **{field: {key: value for key, value in source.get(field, {}).items() if str(key) not in keys}
           for field in ("by_hash", "by_name", "values") if isinstance(source.get(field), Mapping)},
        **({"entries": {key: entry for key, entry in source["entries"].items()
            if str(key) not in keys and (not isinstance(entry, Mapping) or not {
                str(entry.get("hash")), str(entry.get("name")),
            }.intersection(keys))}} if isinstance(source.get("entries"), Mapping) else {}),
    } for source in sources)
    return (*template_sources, *outer)


@dataclass(frozen=True)
class TaskGraphTemplateBindingsResult:
    status: HookStatus
    binding_source: Mapping[str, JSONValue] = field(default_factory=dict)
    blocked_reason: str = ""
    body_consumption_record: TaskGraphSettlementRecord | None = None

    def __post_init__(self):
        if type(self) is not TaskGraphTemplateBindingsResult:
            raise TypeError("task graph template binding result type is invalid")
        if ((self.status == "resolved" and self.blocked_reason)
                or (self.status == "blocked" and (not self.blocked_reason or self.binding_source))
                or self.status not in {"resolved", "blocked"}):
            raise ValueError("task graph template binding result is inconsistent")
        object.__setattr__(self, "binding_source", _frozen_object(self.binding_source, "template binding result"))
        if self.body_consumption_record is not None and (
            self.status != "resolved" or self.binding_source
            or type(self.body_consumption_record) is not TaskGraphSettlementRecord
            or not self.body_consumption_record.process_only
        ):
            raise ValueError("consumed template body requires a resolved domain acknowledgement")


def evaluate_task_graph_template_bindings(request, parameters, state, *, binding_sources):
    from ..rules.value_binding import resolve_runtime_numeric_expression

    by_hash, by_name = {}, {}
    for parameter in parameters:
        if type(parameter) is not TaskGraphTemplateParameterIR:
            return TaskGraphTemplateBindingsResult("blocked", blocked_reason="template_parameter_type_invalid")
        evaluated = resolve_runtime_numeric_expression(parameter.expression,
            binding_sources=tuple(binding_sources), source_trace=parameter.source.to_json())
        if not evaluated.ok or evaluated.value is None or not math.isfinite(evaluated.value):
            return TaskGraphTemplateBindingsResult("blocked", blocked_reason=
                evaluated.blocked_reason or "template_parameter_value_unresolved")
        entry = {"value": float(evaluated.value), "source_trace": {
            "parameter_source": parameter.source.to_json(), "numeric_evaluation": evaluated.to_json(),
        }, "parameter_name": parameter.parameter_name, "frame_invocation_id": request.invocation_id,
            "graph_node_id": request.graph_node_id}
        if parameter.destination_hash in by_hash or parameter.parameter_name in by_name:
            return TaskGraphTemplateBindingsResult("blocked", blocked_reason="template_parameter_duplicate_slot")
        by_hash[parameter.destination_hash] = entry
        by_name[parameter.parameter_name] = entry
    return TaskGraphTemplateBindingsResult("resolved", {
        "source_type": "task_template_parameter", "by_hash": by_hash, "by_name": by_name,
    })


@dataclass(frozen=True)
class TaskGraphConditionResult:
    status: HookStatus
    value: bool | None = None
    progress_remaining: int | None = None
    blocked_reason: str = ""
    rng_events: tuple[RNGEvent, ...] = ()

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
            if self.value is not None or self.progress_remaining is not None or self.rng_events or not self.blocked_reason:
                raise ValueError("blocked task graph condition is inconsistent")
        else:
            raise ValueError("task graph condition status is invalid")
        object.__setattr__(self, "rng_events", tuple(_freeze_rng_event(item) for item in self.rng_events))


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
    rng_events: tuple[RNGEvent, ...] = ()
    status_scopes: tuple[TaskGraphStatusScope, ...] = ()

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphTargetResult:
            raise TypeError("task graph target result must not be subclassed")
        if not isinstance(self.blocked_reason, str):
            raise TypeError("task graph target blocker must be a string")
        targets = _strings(self.target_ids, "task graph resolved targets")
        scopes = tuple(self.status_scopes)
        if any(type(item) is not TaskGraphStatusScope for item in scopes) or len(scopes) != len(set(scopes)):
            raise ValueError("task graph resolved status scopes are invalid")
        if targets and scopes:
            raise ValueError("task graph target and status scopes cannot be mixed")
        if self.status == "resolved":
            if self.blocked_reason:
                raise ValueError("resolved task graph targets carry a blocker")
        elif self.status == "blocked":
            if targets or scopes or self.rng_events or not self.blocked_reason:
                raise ValueError("blocked task graph targets are inconsistent")
        else:
            raise ValueError("task graph target status is invalid")
        object.__setattr__(self, "target_ids", targets)
        object.__setattr__(self, "status_scopes", scopes)
        object.__setattr__(self, "rng_events", tuple(_freeze_rng_event(item) for item in self.rng_events))


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
    return replace(
        event,
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
    child_projections: tuple[TaskGraphNodeProjection, ...] = ()
    continuation_target_ids: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphLeafResult:
            raise TypeError("task graph leaf result must not be subclassed")
        targets = (None if self.continuation_target_ids is None else
                   _strings(self.continuation_target_ids, "task graph continuation targets"))
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
        projections: list[TaskGraphNodeProjection] = []
        projection_by_id: dict[str, TaskGraphNodeProjection] = {}
        for item in tuple(self.child_projections):
            if type(item) is not TaskGraphNodeProjection:
                raise TypeError("task graph child projections are invalid")
            if item.status != "complete":
                raise ValueError("task graph child projection is not complete")
            previous = projection_by_id.get(item.execution_id)
            if previous is not None:
                if previous != item:
                    raise ValueError("task graph child projection identity conflicts")
                continue
            projection_by_id[item.execution_id] = item
            projections.append(item)
        if self.status == "resolved":
            if not self.outcome_kind or self.blocked_reason:
                raise ValueError("resolved task graph leaf result is inconsistent")
        elif self.status == "blocked":
            if (
                mutations
                or events
                or rng_events
                or records
                or projections
                or targets is not None
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
        object.__setattr__(self, "child_projections", tuple(projections))
        object.__setattr__(self, "continuation_target_ids", targets)


@dataclass(frozen=True)
class TaskGraphGraphResult:
    status: HookStatus
    definition_id: str = ""
    graph: TaskGraphIR | None = None
    blocked_reason: str = ""
    # Hooks of the nested invocation when the source call changes its caster.
    hooks: "TaskGraphExecutionHooks | None" = field(default=None, repr=False, compare=False)
    # The callee is a formal no-gameplay definition; nothing runs.
    noop: bool = False

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
                or (type(self.graph) is not TaskGraphIR) is not self.noop
                or self.blocked_reason
            ):
                raise ValueError("resolved nested task graph is inconsistent")
        elif self.status == "blocked":
            if self.definition_id or self.graph is not None or not self.blocked_reason:
                raise ValueError("blocked nested task graph is inconsistent")
        else:
            raise ValueError("nested task graph status is invalid")


@dataclass(frozen=True)
class TaskGraphWeightedSelectionResult:
    status: HookStatus
    selection_id: str = ""
    graph_node_id: str = ""
    choice_id: str = ""
    ordinal: int | None = None
    branch_id: str = ""
    rng_event: RNGEvent | None = None
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphWeightedSelectionResult:
            raise TypeError("task graph weighted selection result must not be subclassed")
        for value in (
            self.selection_id,
            self.graph_node_id,
            self.choice_id,
            self.branch_id,
            self.blocked_reason,
        ):
            if not isinstance(value, str):
                raise TypeError("task graph weighted selection fields must be strings")
        if self.status == "resolved":
            if (
                not self.selection_id
                or not self.graph_node_id
                or not self.choice_id
                or type(self.ordinal) is not int
                or self.ordinal < 0
                or not self.branch_id
                or type(self.rng_event) is not RNGEvent
                or self.blocked_reason
            ):
                raise ValueError("resolved task graph weighted selection is inconsistent")
            object.__setattr__(
                self,
                "rng_event",
                _freeze_rng_event(cast(RNGEvent, self.rng_event)),
            )
        elif self.status == "blocked":
            if (
                self.selection_id
                or self.graph_node_id
                or self.choice_id
                or self.ordinal is not None
                or self.branch_id
                or self.rng_event is not None
                or not self.blocked_reason
            ):
                raise ValueError("blocked task graph weighted selection leaks resolved payload")
        else:
            raise ValueError("task graph weighted selection status is invalid")


def resolve_task_graph_weighted_selection(
    request: TaskGraphHookRequest,
    selection: TaskGraphWeightedSelectionIR,
    state: BattleState,
    weights: tuple[float, ...],
    *,
    rng_choices: Mapping[str, JSONValue] | None = None,
    rng_mode: str = "deterministic_seed",
) -> TaskGraphWeightedSelectionResult:
    if (
        len(weights) != len(selection.choices)
        or any(not math.isfinite(weight) or weight < 0 for weight in weights)
        or not math.isfinite(sum(weights))
        or sum(weights) <= 0
    ):
        return TaskGraphWeightedSelectionResult("blocked", blocked_reason="task_graph_weighted_selection_weights_invalid")
    identity: dict[str, JSONValue] = {
        "decision_scope": request.invocation_id,
        "decision_index": request.iteration_index or 0,
        "task_id": request.formal_task_id,
        "execution_path": list(request.execution_path),
        "target_ids": list(request.target_ids),
    }
    rng_type = "task_graph_weighted_selection"
    rng_request = RNGRequest(
        rng_type=rng_type,
        purpose="select exactly one RandomConfig branch",
        event_id=event_id_for_identity(rng_type, identity, event_index=state.event_index),
        choice_key=choice_key_for_identity(rng_type, identity),
        source=selection.selection_id,
        before_state=state.rng_state,
        decision_kind="weighted",
        outcomes=tuple(
            RNGOutcome(choice.choice_id, {"branch_id": choice.branch_id}, weight=weight)
            for choice, weight in zip(selection.choices, weights, strict=True)
        ),
        source_trace={"selection_source": selection.source.to_json()},
        identity=identity,
    )
    resolution = resolve_rng_request(
        rng_request, rng_choices=dict(rng_choices or {}), rng_mode=rng_mode,
    )
    if not resolution.ok or resolution.selected_outcome is None or resolution.event is None:
        return TaskGraphWeightedSelectionResult(
            "blocked", blocked_reason=resolution.blocked_reason or "task_graph_weighted_selection_unresolved",
        )
    choice = next(
        (item for item in selection.choices if item.choice_id == resolution.selected_outcome.outcome_id),
        None,
    )
    if choice is None:
        return TaskGraphWeightedSelectionResult("blocked", blocked_reason="task_graph_weighted_selection_choice_missing")
    return TaskGraphWeightedSelectionResult(
        "resolved", selection.selection_id, selection.graph_node_id,
        choice.choice_id, choice.ordinal, choice.branch_id, resolution.event,
    )


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
    weighted_selection: Callable[
        [TaskGraphHookRequest, TaskGraphWeightedSelectionIR, BattleState],
        TaskGraphWeightedSelectionResult,
    ] | None = None
    template_bindings: Callable[..., TaskGraphTemplateBindingsResult] | None = None

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphExecutionHooks:
            raise TypeError("task graph hooks must not be subclassed")
        for name in (
            "leaf",
            "condition",
            "branch",
            "count",
            "targets",
            "graph",
            "weighted_selection",
            "template_bindings",
        ):
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
    parameter_target_ids: tuple[str, ...] | None
    parameter_binding_sources: tuple[Mapping[str, JSONValue], ...]


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
        self.status_stack: list[TaskGraphStatusScope] = []
        self.iteration_stack: list[int] = []
        self.mutations: list[Mutation] = []
        self.events: list[GameEvent] = []
        self.rng_events: list[RNGEvent] = []
        self.records: list[TaskGraphSettlementRecord] = []
        self.projections: list[TaskGraphNodeProjection] = []
        self.child_projections: list[TaskGraphNodeProjection] = []
        self.child_projection_by_id: dict[str, TaskGraphNodeProjection] = {}
        self.execution_ids: set[str] = set()
        self.mutation_ids: set[str] = set()
        self.event_ids: set[str] = set()
        self.rng_event_ids: set[str] = set()
        self.execution_path: tuple[str, ...] = ()

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
        previous_path = self.execution_path
        self.execution_path = path
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
                "parallel_templates": self._execute_parallel_templates,
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
        finally:
            self.execution_path = previous_path
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
            self.execution_path,
            self.status_stack[-1] if self.status_stack else self.context.status_scope,
            self.frames[-1].parameter_target_ids if self.frames else self.context.template_target_ids,
            self.frames[-1].parameter_binding_sources if self.frames else self.context.template_binding_sources,
            self.context.trigger_event,
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
        if result.continuation_target_ids is None:
            self._children(graph, node_by_id, children, (*path, "continuation"))
            return
        if any(unit_id not in self.state.units for unit_id in result.continuation_target_ids):
            raise _ExecutionBlocked("task_graph_continuation_target_missing")
        self.target_stack.append(result.continuation_target_ids)
        try:
            self._children(graph, node_by_id, children, (*path, "continuation"))
        finally:
            self.target_stack.pop()

    def _admit_leaf(self, result: TaskGraphLeafResult) -> None:
        own_projection_by_id = {item.execution_id: item for item in self.projections}
        accepted_child_projections: list[TaskGraphNodeProjection] = []
        for projection in result.child_projections:
            previous = self.child_projection_by_id.get(projection.execution_id)
            if previous is None:
                previous = own_projection_by_id.get(projection.execution_id)
            if previous is not None:
                if previous != projection:
                    raise _ExecutionBlocked(
                        f"task_graph_child_projection_identity_conflict:{projection.execution_id}"
                    )
                continue
            if projection.execution_id in self.execution_ids:
                raise _ExecutionBlocked(
                    f"task_graph_child_projection_identity_conflict:{projection.execution_id}"
                )
            accepted_child_projections.append(projection)
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
        for projection in accepted_child_projections:
            self.child_projections.append(projection)
            self.child_projection_by_id[projection.execution_id] = projection
            self.execution_ids.add(projection.execution_id)
        self.mutation_ids.update(item.stable_id() for item in result.mutations)
        self.event_ids.update(cast(str, item.to_json()["event_id"]) for item in result.events)
        self.rng_event_ids.update(cast(str, item.to_json()["event_id"]) for item in result.rng_events)

    def _admit_weighted_selection_rng_event(self, event: RNGEvent) -> None:
        if _RESERVED_IDENTITY_FIELDS.intersection(event.metadata):
            raise _ExecutionBlocked("task_graph_weighted_selection_forged_execution_identity")
        if isinstance(event.result, Mapping) and _RESERVED_IDENTITY_FIELDS.intersection(
            event.result
        ):
            raise _ExecutionBlocked("task_graph_weighted_selection_forged_execution_identity")
        event_id = cast(str, event.to_json()["event_id"])
        if event_id in self.rng_event_ids:
            raise _ExecutionBlocked(f"task_graph_duplicate_rng_identity:{event_id}")
        self.rng_events.append(event)
        self.rng_event_ids.add(event_id)

    def _admit_control_rng_events(self, events: tuple[RNGEvent, ...]) -> None:
        if len({event.event_id for event in events}) != len(events):
            raise _ExecutionBlocked("task_graph_duplicate_rng_identity")
        for event in events:
            self._admit_weighted_selection_rng_event(event)

    def _execute_weighted_selection(
        self,
        graph: TaskGraphIR,
        node: TaskGraphNodeIR,
        node_by_id: Mapping[str, TaskGraphNodeIR],
        path: tuple[str, ...],
    ) -> None:
        selections = tuple(
            item
            for item in graph.weighted_selections
            if item.graph_node_id == node.graph_node_id
        )
        if len(selections) != 1:
            raise _ExecutionBlocked(
                f"task_graph_weighted_selection_not_unique:{node.graph_node_id}"
            )
        selection = selections[0]
        if (
            selection.graph_node_id != node.graph_node_id
            or selection.family != "RandomConfig"
            or selection.selection_kind != "weighted_single"
        ):
            raise _ExecutionBlocked("task_graph_weighted_selection_contract_mismatch")
        result = self.call_hook(
            "weighted_selection",
            self.request(graph, node),
            selection,
            self.state,
        )
        if type(result) is not TaskGraphWeightedSelectionResult:
            raise _ExecutionBlocked("task_graph_weighted_selection_hook_result_type_invalid")
        if result.status == "blocked":
            raise _ExecutionBlocked(result.blocked_reason)
        if (
            result.selection_id != selection.selection_id
            or result.graph_node_id != node.graph_node_id
        ):
            raise _ExecutionBlocked("task_graph_weighted_selection_identity_mismatch")
        choices = tuple(
            item for item in selection.choices if item.choice_id == result.choice_id
        )
        if len(choices) != 1:
            raise _ExecutionBlocked("task_graph_weighted_selection_choice_not_unique")
        choice = choices[0]
        if (
            choice.graph_node_id != node.graph_node_id
            or choice.family != "RandomConfig"
            or result.ordinal != choice.ordinal
            or result.branch_id != choice.branch_id
        ):
            raise _ExecutionBlocked("task_graph_weighted_selection_choice_identity_mismatch")
        branches = tuple(
            item
            for item in node.branches
            if item.ordinal == choice.ordinal and item.branch_id == choice.branch_id
        )
        if len(branches) != 1:
            raise _ExecutionBlocked("task_graph_weighted_selection_branch_not_unique")
        rng_event = cast(RNGEvent, result.rng_event)
        self._admit_weighted_selection_rng_event(rng_event)
        branch = branches[0]
        self._children(
            graph,
            node_by_id,
            branch.child_node_ids,
            (
                *path,
                f"choice:{choice.ordinal}",
                f"branch:weighted_choice:{branch.ordinal}",
            ),
        )

    def _execute_branch(
        self,
        graph: TaskGraphIR,
        node: TaskGraphNodeIR,
        node_by_id: Mapping[str, TaskGraphNodeIR],
        path: tuple[str, ...],
    ) -> None:
        if node.source_family == "RandomConfig":
            self._execute_weighted_selection(graph, node, node_by_id, path)
            return
        kinds = {item.branch_kind for item in node.branches}
        if kinds <= {"success", "failed"}:
            result = self.call_hook("condition", self.request(graph, node), self.state)
            if type(result) is not TaskGraphConditionResult:
                raise _ExecutionBlocked("task_graph_condition_hook_result_type_invalid")
            if result.status == "blocked":
                raise _ExecutionBlocked(result.blocked_reason)
            self._admit_control_rng_events(result.rng_events)
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
        self._admit_control_rng_events(result.rng_events)
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
    ) -> TaskGraphTargetResult:
        result = self.call_hook("targets", self.request(graph, node), self.state)
        if type(result) is not TaskGraphTargetResult:
            raise _ExecutionBlocked("task_graph_target_hook_result_type_invalid")
        if result.status == "blocked":
            raise _ExecutionBlocked(result.blocked_reason)
        self._admit_control_rng_events(result.rng_events)
        return result

    def _execute_target_scope(
        self,
        graph: TaskGraphIR,
        node: TaskGraphNodeIR,
        node_by_id: Mapping[str, TaskGraphNodeIR],
        path: tuple[str, ...],
    ) -> None:
        resolution = self._resolve_targets(graph, node)
        if not resolution.target_ids and not resolution.status_scopes:
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
        if candidates[0].branch_kind == "status_scope":
            if not resolution.status_scopes:
                raise _ExecutionBlocked("task_graph_status_scope_identity_missing")
            for scope in resolution.status_scopes:
                self.status_stack.append(scope)
                try:
                    self._children(graph, node_by_id, candidates[0].child_node_ids,
                        (*path, _stable_id("status_scope", scope.owner_id, scope.instance_id)))
                finally:
                    self.status_stack.pop()
            return
        if resolution.status_scopes:
            raise _ExecutionBlocked("task_graph_status_scope_branch_mismatch")
        self.target_stack.append(resolution.target_ids)
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
        parameter_sources = self.frames[-1].parameter_binding_sources if self.frames else self.context.template_binding_sources
        if node.template_parameters or self.hooks.template_bindings is not None:
            result = self.call_hook("template_bindings", self.request(graph, node), node.template_parameters, self.state)
            if type(result) is not TaskGraphTemplateBindingsResult:
                raise _ExecutionBlocked("task_graph_template_binding_hook_result_type_invalid")
            if result.status == "blocked":
                raise _ExecutionBlocked(result.blocked_reason)
            if result.body_consumption_record is not None:
                self.records.append(result.body_consumption_record)
                return
            if result.binding_source:
                parameter_sources = with_template_binding_sources(parameter_sources, (result.binding_source,))
        parameter_targets = self.frames[-1].parameter_target_ids if self.frames else self.context.template_target_ids
        if any(item.reference_kind == "target" for item in node.references):
            resolution = self._resolve_targets(graph, node)
            if resolution.status_scopes:
                raise _ExecutionBlocked("task_graph_template_parameter_requires_unit_targets")
            parameter_targets = resolution.target_ids
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
            parameter_targets,
            parameter_sources,
        )
        self.frames.append(frame)
        try:
            self._children(
                graph, node_by_id, bodies[0].child_node_ids, (*path, "template_body")
            )
        finally:
            self.frames.pop()

    def _execute_parallel_templates(
        self,
        graph: TaskGraphIR,
        node: TaskGraphNodeIR,
        node_by_id: Mapping[str, TaskGraphNodeIR],
        path: tuple[str, ...],
    ) -> None:
        refs = tuple(item for item in node.references if item.reference_kind == "template")
        if not refs or any(item.resolution_status != "resolved" for item in refs):
            raise _ExecutionBlocked("task_graph_parallel_template_reference_not_resolved")
        bodies = tuple(
            item for item in node.branches if item.branch_kind == "template_body"
        )
        if len(bodies) != len(refs):
            raise _ExecutionBlocked("task_graph_parallel_template_body_count_mismatch")
        if {item.label for item in bodies} != {item.definition_id for item in refs}:
            raise _ExecutionBlocked("task_graph_parallel_template_body_identity_mismatch")
        parameter_sources = (
            self.frames[-1].parameter_binding_sources
            if self.frames
            else self.context.template_binding_sources
        )
        parameter_targets = (
            self.frames[-1].parameter_target_ids
            if self.frames
            else self.context.template_target_ids
        )
        # TBGD fires every listed template concurrently. The kernel executes the
        # same bodies in source order: all effects still run exactly once, while
        # a deterministic single-threaded order replaces host scheduling.
        for body in bodies:
            frame = _TemplateFrame(
                _stable_id(
                    "task_graph_template_frame",
                    self.context.invocation_id,
                    graph.graph_id,
                    node.graph_node_id,
                    *path,
                    body.label,
                ),
                graph.graph_id,
                MappingProxyType({}),
                parameter_targets,
                parameter_sources,
            )
            self.frames.append(frame)
            try:
                self._children(
                    graph,
                    node_by_id,
                    body.child_node_ids,
                    (*path, "parallel_template_body", body.label),
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
        if result.definition_id != refs[0].definition_id:
            raise _ExecutionBlocked("task_graph_nested_definition_identity_mismatch")
        if result.noop:
            if node.branches:
                children = self._branch_children(node, "success", allow_absent=True)
                self._children(graph, node_by_id, children, (*path, "ability_continuation"))
            return
        nested = cast(TaskGraphIR, result.graph)
        if (
            nested.source_catalog_id != graph.source_catalog_id
            or nested.source_fingerprint != graph.source_fingerprint
        ):
            raise _ExecutionBlocked("task_graph_nested_graph_authority_mismatch")
        structure_reason = TaskGraphExecutor._graph_structure_reason(nested)
        if structure_reason:
            raise _ExecutionBlocked(structure_reason)
        outer_hooks = self.hooks
        if result.hooks is not None:
            self.hooks = result.hooks
        try:
            self.execute_graph(nested, (*path, f"ability:{refs[0].definition_id}"))
        finally:
            self.hooks = outer_hooks
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
            run.execute_graph(graph, (*context.parent_execution_path, f"invocation:{context.invocation_id}"))
        except _ExecutionBlocked as exc:
            return self._blocked(state, tuple(run.projections), str(exc))
        return self._committed(run)

    def execute_selected_nodes(
        self,
        state: BattleState,
        graph: TaskGraphIR,
        context: TaskGraphExecutionContext,
        hooks: TaskGraphExecutionHooks,
        node_ids: tuple[str, ...],
    ) -> TaskGraphExecutionResult:
        """Execute one source-predeclared branch selection atomically.

        The selected nodes stay part of their materialized graph (identity,
        projections and hooks are unchanged); only the entry roots are replaced
        by the caller's formal branch children.
        """

        if type(state) is not BattleState:
            raise TypeError("task graph executor requires exact BattleState")
        if not isinstance(node_ids, tuple) or not node_ids or any(
            not isinstance(item, str) or not item for item in node_ids
        ) or len(node_ids) != len(set(node_ids)):
            return self._blocked(state, (), "task_graph_selected_nodes_invalid")
        reason = self._preflight(graph, context, hooks)
        if reason:
            return self._blocked(state, (), reason)
        node_by_id = {item.graph_node_id: item for item in graph.nodes}
        selected = []
        for node_id in node_ids:
            node = node_by_id.get(node_id)
            if node is None:
                return self._blocked(state, (), f"task_graph_selected_node_missing:{node_id}")
            if node.materialization_status != "materialized":
                return self._blocked(
                    state, (), node.status_reason or f"task_graph_selected_node_not_materialized:{node_id}"
                )
            selected.append(node)
        run = _TaskGraphRun(state, context, hooks)
        run.active_graphs = [*context.active_graph_stack, graph.graph_id]
        try:
            for ordinal, node in enumerate(selected):
                run.execute_node(
                    graph,
                    node,
                    node_by_id,
                    (
                        *context.parent_execution_path,
                        f"invocation:{context.invocation_id}",
                        f"selected:{ordinal}",
                    ),
                )
        except _ExecutionBlocked as exc:
            return self._blocked(state, tuple(run.projections), str(exc))
        return self._committed(run)

    def execute_interleaved(
        self,
        state: BattleState,
        entries: tuple[tuple[TaskGraphIR, TaskGraphExecutionContext, TaskGraphExecutionHooks, tuple[float, ...]], ...],
    ) -> TaskGraphExecutionResult:
        """Execute source-ordered roots on one shared, atomic state timeline."""
        if type(state) is not BattleState:
            raise TypeError("task graph executor requires exact BattleState")
        if not entries:
            return self._blocked(state, (), "parallel_task_graph_entries_missing")
        schedule = []
        authority = None
        for ordinal, (graph, context, hooks, times) in enumerate(entries):
            reason = self._preflight(graph, context, hooks)
            if reason:
                return self._blocked(state, (), reason)
            identity = (graph.source_catalog_id, graph.source_fingerprint)
            if authority is not None and identity != authority:
                return self._blocked(state, (), "parallel_task_graph_authority_mismatch")
            authority = identity
            if (len(times) != len(graph.root_node_ids)
                    or any(type(time) not in (int, float) or not math.isfinite(time) or time < 0 for time in times)
                    or any(left > right for left, right in zip(times, times[1:]))):
                return self._blocked(state, (), "parallel_task_graph_time_order_invalid")
            # ponytail: barriers between roots only. Nested/dynamic barriers
            # need resumable control frames before this ceiling can be lifted.
            if any(node.opcode == "WaitParallelTimeStamp" and node.graph_node_id not in graph.root_node_ids
                   for node in graph.nodes):
                return self._blocked(state, (), "parallel_task_graph_nested_barrier_not_supported")
            schedule.extend((time, ordinal, root_ordinal) for root_ordinal, time in enumerate(times))
        run = _TaskGraphRun(state, entries[0][1], entries[0][2])
        try:
            for _, ordinal, root_ordinal in sorted(schedule):
                graph, context, hooks, _ = entries[ordinal]
                run.context, run.hooks = context, hooks
                run.active_graphs = [*context.active_graph_stack, graph.graph_id]
                node_by_id = {node.graph_node_id: node for node in graph.nodes}
                run.execute_node(
                    graph, node_by_id[graph.root_node_ids[root_ordinal]], node_by_id,
                    (*context.parent_execution_path, f"invocation:{context.invocation_id}", f"root:{root_ordinal}"),
                )
        except _ExecutionBlocked as exc:
            return self._blocked(state, tuple(run.projections), str(exc))
        return self._committed(run)

    @staticmethod
    def _committed(run: _TaskGraphRun) -> TaskGraphExecutionResult:
        projections = (*run.projections, *run.child_projections)
        node_results = tuple(item.to_node_result() for item in projections)
        outcome = TransitionOutcome("committed", (), node_results)
        return TaskGraphExecutionResult(
            True,
            run.before_state,
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
