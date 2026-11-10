from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, cast

from ..immutable_json import thaw_json
from ..dynamic_key_hash import tbgd_dynamic_key_hash
from ..ir_types import IRSource
from ..rules.control_flow_contract import (
    CharacterControlFlowContractCatalog,
    CharacterControlFlowNodeIR,
    ControlFlowTemplateDefinitionIR,
    ControlFlowTemplateReferenceIR,
)
from ..rules.ir import (
    AbilityPhaseIR,
    AbilityTaskIR,
    CanonicalIR,
    ConditionIR,
    EffectIR,
    StandaloneAbilityGraphIR,
    StatusCallbackIR,
    StatusCallbackTaskIR,
    TargetExpressionIR,
    build_external_task_topology_dependency_ledger,
)
from ..rules.task_graph import (
    single_projectile_impact_contract_admitted,
    EntryKind,
    TaskGraphBranchIR,
    TaskGraphCatalogIR,
    TaskGraphDefinitionReferenceIR,
    TaskGraphEntryMaterializationIR,
    TaskGraphIR,
    TaskGraphNodeIR,
    TaskGraphNumericDefinitionIR,
    TaskGraphTemplateParameterIR,
    TaskGraphSourceDispositionIR,
    TaskGraphWeightedChoiceIR,
    TaskGraphWeightedSelectionIR,
    task_graph_branch_id,
    task_graph_entry_id,
    task_graph_id,
    task_graph_materialization_id,
    task_graph_node_id,
    task_graph_numeric_id,
    task_graph_reference_id,
    task_graph_source_occurrence_id,
    task_graph_source_record_fingerprint,
    task_graph_weighted_choice_id,
    task_graph_weighted_selection_id,
)
from .character_ability_scope import CharacterAbilityRawSnapshot
from .character_control_flow_contracts import _typed_subtree_is_non_gameplay
from .expression_lowering import lower_numeric_expression


_OWNER_DOMAIN_BY_STAGE = {
    "excluded": "non_gameplay_excluded",
    "p9_s4": "numeric_expression",
    "p9_s5a": "target_resolution",
    "p9_s5b": "target_resolution",
    "p9_s5c": "target_resolution",
    "p9_s5d": "target_random_selection",
    "p9_s6a": "condition_evaluation",
    "p9_s6b": "condition_evaluation",
    "p9_s7": "transient_condition_evaluation",
    "p9_s8a": "control_flow_source_contract",
    "p9_s8b": "task_graph_execution",
    "p9_s8c": "hit_random_sequence",
    "p9_s9": "event_dispatch",
    "p9_s10": "status_lifecycle",
    "p9_s11": "damage_heal_shield",
    "p9_s12": "resource_resolution",
    "p9_s13": "timeline_queue",
    "p9_s14": "unit_lifecycle",
    "p9_s15": "toughness_break",
    "p9_s16": "action_form_phase",
    "p9_s17": "combat_entity_event",
}
_ALREADY_CLOSED_DOMAINS = frozenset({
    "non_gameplay_excluded",
    "numeric_expression",
    "target_resolution",
    "target_random_selection",
    "condition_evaluation",
    "transient_condition_evaluation",
    "control_flow_source_contract",
})
_NODE_KIND_BY_ROLE = {
    "predicate_branch": "branch",
    "switch_branch": "branch",
    "event_switch": "branch",
    "counted_loop": "loop",
    "conditional_loop": "loop",
    "target_loop": "loop",
    "target_scope": "target_scope",
    "status_scope": "target_scope",
    "ordered_target_scope": "target_scope",
    "status_scope": "target_scope",
    "template_include": "template_call",
    "template_parameter_fetch": "template_parameter",
    "ability_trigger": "ability_call",
    "parallel_abilities": "leaf",
    "parallel_time_barrier": "leaf",
    "parallel_templates": "parallel_templates",
    "action_abort_continuation": "sequence",
    "condition_delegate": "leaf",
    "effect_continuation": "sequence",
    "wrapped_task": "sequence",
    "event_creation_continuation": "sequence",
}


class _Blocked(RuntimeError):
    pass


@dataclass(frozen=True)
class _FormalTask:
    task_id: str
    graph_task_path: str
    opcode: str
    family: str
    condition_id: str
    target_expression_id: str
    effect_id: str
    ability_definition_id: str
    ability_definition_kind: str
    execution_mode: str
    coverage_status: str
    source: IRSource
    consumed_template_id: str = ""
    action_id: str = ""



@dataclass(frozen=True)
class _SourceBranch:
    branch_kind: str
    label: str
    child_task_ids: tuple[str, ...]
    source: IRSource


@dataclass(frozen=True)
class _DefinitionIndexes:
    conditions: Mapping[str, tuple[ConditionIR, ...]]
    targets: Mapping[str, tuple[TargetExpressionIR, ...]]
    effects: Mapping[str, tuple[EffectIR, ...]]
    abilities: Mapping[
        str, tuple[AbilityPhaseIR | StandaloneAbilityGraphIR, ...]
    ]


@dataclass(frozen=True)
class _MaterializationContext:
    source_catalog: CharacterControlFlowContractCatalog
    base: TaskGraphCatalogIR
    source_snapshot: CharacterAbilityRawSnapshot
    digest_by_path: Mapping[str, str]
    control_by_location: Mapping[
        tuple[str, object, str], CharacterControlFlowNodeIR
    ]
    template_by_id: Mapping[str, ControlFlowTemplateDefinitionIR]
    template_refs_by_node: Mapping[str, tuple[ControlFlowTemplateReferenceIR, ...]]
    definitions: _DefinitionIndexes
    admitted_insert_action_task_ids: frozenset[str]


def _admitted_insert_action_task_ids(canonical: CanonicalIR) -> frozenset[str]:
    """Source tasks whose TurnInsertAction intent is admitted end to end.

    A queue node is only materialized when the formal QueueIntent, QueueWindow
    and QueueResolution all admit the entry itself; the abort branch stays in
    the graph as the delayed cancellation path.
    """

    if type(canonical) is not CanonicalIR:
        raise TypeError("insert-action admission requires exact CanonicalIR")
    windows_by_intent: dict[str, list[Any]] = defaultdict(list)
    for window in canonical.queue_windows:
        windows_by_intent[window.queue_intent_id].append(window)
    resolutions_by_intent: dict[str, list[Any]] = defaultdict(list)
    for resolution in canonical.queue_resolutions:
        resolutions_by_intent[resolution.queue_intent_id].append(resolution)
    admitted: set[str] = set()
    for intent in canonical.queue_intents:
        if intent.opcode != "TurnInsertAction" or intent.coverage_status != "executable":
            continue
        windows = windows_by_intent.get(intent.queue_intent_id, ())
        resolutions = resolutions_by_intent.get(intent.queue_intent_id, ())
        if (
            len(windows) != 1
            or len(resolutions) != 1
            or windows[0].coverage_status != "executable"
            or windows[0].window_family != "insert_action"
            or resolutions[0].coverage_status != "executable"
            or resolutions[0].resolved_kind != "action_definition"
            or not intent.source_task_id
        ):
            continue
        admitted.add(intent.source_task_id)
    return frozenset(admitted)


def _insert_action_queue_shape(
    control: CharacterControlFlowNodeIR | None,
    task: _FormalTask,
    branches: Sequence[TaskGraphBranchIR],
) -> bool:
    """Return whether this control node keeps its formal abort branch."""

    if (
        control is None
        or control.family != task.opcode
        or task.family != "TurnInsertAction"
        or control.control_role != "action_abort_continuation"
        or control.coverage_status == "blocked"
        or control.blocked_reason
        or task.coverage_status != "executable"
    ):
        return False
    abort_branches = tuple(
        branch for branch in branches if branch.branch_kind == "insert_abort"
    )
    return (
        len(abort_branches) == 1
        and bool(abort_branches[0].child_node_ids)
        and len(branches) == 1
    )


def build_complete_task_graph_catalog(
    source_catalog: CharacterControlFlowContractCatalog,
    source_snapshot: CharacterAbilityRawSnapshot,
) -> TaskGraphCatalogIR:
    if type(source_catalog) is not CharacterControlFlowContractCatalog:
        raise TypeError("task graph source catalog requires the exact S8A catalog")
    _validate_source_snapshot(source_catalog, source_snapshot, require_complete=True)
    # Source issues remain in the control-flow catalog and blocked dispositions;
    # they must not prevent unrelated content from compiling.
    dispositions: list[TaskGraphSourceDispositionIR] = []
    for node in source_catalog.nodes:
        domains = tuple(sorted({
            _owner_domain(stage)
            for stage in node.downstream_stages
            if _owner_domain(stage) not in _ALREADY_CLOSED_DOMAINS
        }))
        status = "blocked" if node.coverage_status == "blocked" else "deferred" if domains else "materialized"
        dispositions.append(_disposition(
            node.node_id,
            "control_node",
            node.family,
            node.source,
            cast(Any, status),
            domains,
            node.blocked_reason,
        ))
    for template in source_catalog.template_definitions:
        dispositions.append(_disposition(
            template.template_id,
            "template_definition",
            template.source.raw_type,
            template.source,
            "materialized",
            (),
            "",
        ))
    for reference in source_catalog.template_references:
        if reference.coverage_status == "blocked":
            status, domains, reason = "blocked", (), reference.blocked_reason
        elif reference.reference_kind == "parallel_local":
            status, domains, reason = "deferred", ("hit_random_sequence",), ""
        else:
            status, domains, reason = "materialized", (), ""
        dispositions.append(_disposition(
            reference.reference_id,
            "template_reference",
            reference.source.raw_type,
            reference.source,
            cast(Any, status),
            domains,
            reason,
        ))
    expected = {
        *(item.node_id for item in source_catalog.nodes),
        *(item.template_id for item in source_catalog.template_definitions),
        *(item.reference_id for item in source_catalog.template_references),
    }
    if {item.source_record_id for item in dispositions} != expected:
        raise ValueError("task graph source disposition ledger is incomplete")
    return _catalog(source_catalog, "complete_catalog", tuple(dispositions), (), ())


_FORMAL_ABILITY_INVOCATION_ROLES = frozenset(
    {"action_root", "nested_only", "standalone_root", "build_startup"}
)


def materialize_ability_task_graph_catalog(
    source_catalog: CharacterControlFlowContractCatalog,
    canonical: CanonicalIR,
    *,
    source_snapshot: CharacterAbilityRawSnapshot,
) -> TaskGraphCatalogIR:
    """Materialize every formally admitted ability entry with one prepared source context."""

    if type(canonical) is not CanonicalIR:
        raise TypeError("ability task graph catalog requires exact CanonicalIR")
    context = _prepare_materialization(
        source_catalog,
        canonical,
        source_snapshot,
    )
    entries, graphs = _materialize_ability_entries(context, canonical)
    dispositions = _materialization_dispositions(
        context.base.source_dispositions,
        entries,
        graphs,
        context.admitted_insert_action_task_ids,
    )
    return _catalog(
        source_catalog,
        "formal_catalog",
        dispositions,
        entries,
        graphs,
    )


def materialize_character_runtime_task_graph_catalog(
    source_catalog: CharacterControlFlowContractCatalog,
    canonical: CanonicalIR,
    *,
    source_snapshot: CharacterAbilityRawSnapshot,
    definition_scope_complete: bool,
) -> TaskGraphCatalogIR:
    """Install ability and character-status entries under one source authority."""

    if type(canonical) is not CanonicalIR:
        raise TypeError("character runtime task graph catalog requires exact CanonicalIR")
    if type(definition_scope_complete) is not bool:
        raise TypeError("character task graph completeness marker must be bool")
    if not definition_scope_complete:
        raise ValueError("limited character task graph catalog cannot be complete")
    context = _prepare_materialization(source_catalog, canonical, source_snapshot)
    ability_entries, ability_graphs = _materialize_ability_entries(
        context,
        canonical,
    )
    status_entries, status_graphs = _materialize_status_entries(
        context,
        canonical,
        source_snapshot,
    )
    entries = (*ability_entries, *status_entries)
    graphs = (*ability_graphs, *status_graphs)
    if len({item.entry_id for item in entries}) != len(entries):
        raise ValueError("character task graph entries contain duplicate identities")
    if len({item.graph_id for item in graphs}) != len(graphs):
        raise ValueError("character task graphs contain duplicate identities")
    dispositions = _materialization_dispositions(
        context.base.source_dispositions,
        entries,
        graphs,
        context.admitted_insert_action_task_ids,
    )
    return _catalog(
        source_catalog,
        "formal_catalog",
        dispositions,
        entries,
        graphs,
    )


def _materialize_ability_entries(
    context: _MaterializationContext,
    canonical: CanonicalIR,
) -> tuple[tuple[TaskGraphEntryMaterializationIR, ...], tuple[TaskGraphIR, ...]]:
    phases = tuple(
        phase
        for phase in canonical.ability_phases
        if phase.invocation_role in _FORMAL_ABILITY_INVOCATION_ROLES
    )
    if not phases:
        raise ValueError("formal ability task graph phase selection is empty")
    phase_ids = {item.phase_id for item in phases}
    if len(phase_ids) != len(phases):
        raise ValueError("formal ability task graph phases contain duplicate identities")
    tasks_by_id = {item.task_id: item for item in canonical.ability_tasks}
    if len(tasks_by_id) != len(canonical.ability_tasks):
        raise ValueError("formal ability task graph tasks contain duplicate identities")
    entries: list[TaskGraphEntryMaterializationIR] = []
    graphs: list[TaskGraphIR] = []
    selected_task_ids: set[str] = set()
    for phase in sorted(phases, key=lambda item: item.phase_id):
        phase_tasks = tuple(
            tasks_by_id[task_id]
            for task_id in phase.task_ids
            if task_id in tasks_by_id
        )
        if (
            not phase_tasks
            or len(phase_tasks) != len(phase.task_ids)
            or any(item.phase_id != phase.phase_id for item in phase_tasks)
        ):
            raise ValueError("formal ability phase task ledger is incomplete")
        callback_kinds = tuple(
            dict.fromkeys(item.callback_kind for item in phase_tasks)
        )
        if not callback_kinds or any(not value for value in callback_kinds):
            raise ValueError("formal ability phase callback denominator is invalid")
        selected_task_ids.update(item.task_id for item in phase_tasks)
        for callback_kind in callback_kinds:
            callback_tasks = tuple(
                item for item in phase_tasks if item.callback_kind == callback_kind
            )
            entry, graph = _materialize_entry(
                context,
                "ability_phase_callback",
                phase.phase_id,
                callback_kind,
                tuple(item.task_id for item in callback_tasks),
                tuple(_ability_task(item) for item in callback_tasks),
            )
            entries.append(entry)
            if graph is not None:
                graphs.append(graph)
    formal_task_ids = {
        item.task_id
        for item in canonical.ability_tasks
        if item.phase_id in phase_ids
    }
    if selected_task_ids != formal_task_ids:
        raise ValueError("formal ability task graph phase denominator is incomplete")
    if len({item.entry_id for item in entries}) != len(entries):
        raise ValueError("formal ability task graph entries contain duplicate identities")
    return tuple(entries), tuple(graphs)


def _materialize_status_entries(
    context: _MaterializationContext,
    canonical: CanonicalIR,
    source_snapshot: CharacterAbilityRawSnapshot,
) -> tuple[tuple[TaskGraphEntryMaterializationIR, ...], tuple[TaskGraphIR, ...]]:
    root_source_paths = {
        item.source.source_path for item in source_snapshot.sources
    }
    callbacks = tuple(
        item
        for item in canonical.status_callbacks
        if item.source.source_path in root_source_paths
    )
    _validate_status_callback_denominator(source_snapshot, callbacks)
    callback_ids = tuple(item.callback_id for item in callbacks)
    if len(callback_ids) != len(set(callback_ids)):
        raise ValueError("formal status callbacks contain duplicate identities")
    callback_by_id = {item.callback_id: item for item in callbacks}
    tasks_by_callback: dict[str, list[StatusCallbackTaskIR]] = defaultdict(list)
    task_ids: set[str] = set()
    for task in canonical.status_callback_tasks:
        if task.callback_id not in callback_by_id:
            if task.source.evidence.get("admission_source_path") in root_source_paths:
                raise ValueError("formal status task callback owner is missing")
            continue
        if task.task_id in task_ids:
            raise ValueError("formal status tasks contain duplicate identities")
        task_ids.add(task.task_id)
        tasks_by_callback[task.callback_id].append(task)

    entries: list[TaskGraphEntryMaterializationIR] = []
    graphs: list[TaskGraphIR] = []
    for callback in sorted(callbacks, key=lambda item: item.callback_id):
        tasks = tuple(tasks_by_callback.get(callback.callback_id, ()))
        if not tasks:
            if callback.task_ids:
                raise ValueError("taskless status callback carries root task identities")
            continue
        ordered = _ordered_status_task_ids(callback, tasks)
        entry, graph = _materialize_entry(
            context,
            "status_callback",
            callback.callback_id,
            callback.event,
            ordered,
            tuple(_status_task(item) for item in tasks),
        )
        entries.append(entry)
        if graph is not None:
            graphs.append(graph)
    if len({item.entry_id for item in entries}) != len(entries):
        raise ValueError("formal status entries contain duplicate identities")
    return tuple(entries), tuple(graphs)


def _validate_status_callback_denominator(
    source_snapshot: CharacterAbilityRawSnapshot,
    callbacks: tuple[StatusCallbackIR, ...],
    *,
    source_paths: frozenset[str] | None = None,
) -> None:
    expected: set[tuple[str, str]] = set()

    def visit(value: object, path: str, source_path: str) -> None:
        if isinstance(value, Mapping):
            callback_list = value.get("_CallbackList")
            if "_CallbackList" in value:
                if not isinstance(callback_list, Sequence) or isinstance(
                    callback_list, str
                ):
                    raise ValueError("status callback source list is invalid")
                for index, callback in enumerate(callback_list):
                    if not isinstance(callback, Mapping):
                        raise ValueError("status callback source record is invalid")
                    expected.add((source_path, f"{path}._CallbackList[{index}]"))
            watchers = value.get("OnAbilityPropertyChange")
            if isinstance(watchers, Sequence) and not isinstance(watchers, str):
                for watcher_index, watcher in enumerate(watchers):
                    ranges = watcher.get("Ranges") if isinstance(watcher, Mapping) else None
                    if not isinstance(ranges, Sequence) or isinstance(ranges, str):
                        continue
                    for range_index, item in enumerate(ranges):
                        if not isinstance(item, Mapping):
                            continue
                        base = f"{path}.OnAbilityPropertyChange[{watcher_index}].Ranges[{range_index}]"
                        for branch in (
                            "OnEnterRange",
                            "OnExitRange",
                            "OnChange",
                        ):
                            tasks = item.get(branch)
                            if isinstance(tasks, Sequence) and not isinstance(tasks, str) and tasks:
                                expected.add((source_path, f"{base}.{branch}"))
            point_callbacks = value.get("OnElationPointChange")
            if point_callbacks is not None:
                point_rows = point_callbacks if isinstance(point_callbacks, (list, tuple)) else (point_callbacks,)
                for index, _ in enumerate(point_rows):
                    expected.add((source_path, f"{path}.OnElationPointChange[{index}]"))
            for key, child in value.items():
                visit(child, f"{path}.{key}", source_path)
        elif isinstance(value, Sequence) and not isinstance(value, str):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]", source_path)

    for source in source_snapshot.sources:
        source_path = source.source.source_path
        if source_paths is not None and source_path not in source_paths:
            continue
        visit(source_snapshot.documents[source_path], "$", source_path)
    actual = tuple(
        (
            callback.source.source_path,
            callback.source.evidence.get("callback_json_path"),
        )
        for callback in callbacks
    )
    if (
        any(not isinstance(path, str) or not path for _, path in actual)
        or len(actual) != len(set(actual))
        or set(actual) != expected
    ):
        raise ValueError("formal status callback source denominator is incomplete")


def _ordered_status_task_ids(
    callback: StatusCallbackIR,
    tasks: tuple[StatusCallbackTaskIR, ...],
) -> tuple[str, ...]:
    if any(
        task.callback_id != callback.callback_id
        or task.modifier_name != callback.modifier_name
        or task.event != callback.event
        or task.source.evidence.get("callback_id") != callback.callback_id
        or task.source.evidence.get("admission_source_path")
        != callback.source.source_path
        or task.source.evidence.get("graph_task_path") != task.task_path
        for task in tasks
    ):
        raise ValueError("status callback task owner identity is inconsistent")
    task_paths = tuple(task.task_path for task in tasks)
    if len(task_paths) != len(set(task_paths)):
        raise ValueError("status callback graph positions contain duplicates")
    root_ids = tuple(callback.task_ids)
    if (
        len(callback.task_ids) != len(set(callback.task_ids))
        or len(root_ids) != len(set(root_ids))
        or not root_ids
        or set(root_ids) - set(task.task_id for task in tasks)
    ):
        raise ValueError("status callback root task ledger is incomplete")
    non_roots = tuple(
        sorted(
            (task for task in tasks if task.task_id not in set(root_ids)),
            key=lambda item: (item.task_path, item.task_id),
        )
    )
    return (*callback.task_ids, *(item.task_id for item in non_roots))


def materialize_selected_character_task_graphs(
    source_catalog: CharacterControlFlowContractCatalog,
    canonical: CanonicalIR,
    *,
    source_snapshot: CharacterAbilityRawSnapshot,
    selected_source_paths: frozenset[str],
) -> TaskGraphCatalogIR:
    """Merge full selected-character slices against the unchanged complete source ledger."""
    if type(canonical) is not CanonicalIR:
        raise TypeError("selected character materialization requires exact CanonicalIR")
    source_paths = selected_source_paths
    if (type(source_paths) is not frozenset
            or not all(isinstance(path, str) and path for path in source_paths)
            or not source_paths.issubset(source_snapshot.documents)):
        raise ValueError("selected character snapshot source closure missing")
    callbacks = tuple(callback for callback in canonical.status_callbacks if callback.source.source_path in source_paths)
    _validate_status_callback_denominator(source_snapshot, callbacks, source_paths=frozenset(source_paths))
    callback_ids = {callback.callback_id for callback in callbacks}
    if len(callback_ids) != len(callbacks):
        raise ValueError("selected character status callback identities duplicated")
    if any(task.callback_id not in callback_ids for task in canonical.status_callback_tasks
           if task.source.evidence.get("admission_source_path") in source_paths):
        raise ValueError("selected character status task owner missing")
    context = _prepare_materialization(source_catalog, canonical, source_snapshot)
    complete = context.base
    entries = []
    graphs = []

    def append_entry(entry_kind, owner_id, callback_kind, ordered, tasks):
        entry, graph = _materialize_entry(context, entry_kind, owner_id, callback_kind, ordered, tasks)
        entries.append(entry)
        if graph is not None:
            graphs.append(graph)

    if len({phase.phase_id for phase in canonical.ability_phases}) != len(canonical.ability_phases):
        raise ValueError("selected character phase identities duplicated")
    if len({task.task_id for task in canonical.ability_tasks}) != len(canonical.ability_tasks):
        raise ValueError("selected character task identities duplicated")
    tasks_by_phase = defaultdict(list)
    for task in canonical.ability_tasks:
        tasks_by_phase[task.phase_id].append(task)
    tasks_by_callback = defaultdict(list)
    for task in canonical.status_callback_tasks:
        tasks_by_callback[task.callback_id].append(task)
    for phase in canonical.ability_phases:
        if phase.invocation_role not in _FORMAL_ABILITY_INVOCATION_ROLES:
            continue
        if phase.source.source_path not in source_paths:
            raise ValueError("selected character formal phase outside selected source closure")
        phase_tasks = tuple(tasks_by_phase[phase.phase_id])
        if (not phase_tasks or len(phase.task_ids) != len(phase_tasks)
                or set(phase.task_ids) != {task.task_id for task in phase_tasks}):
            raise ValueError("selected character ability phase task ledger incomplete")
        for callback_kind in sorted({task.callback_kind for task in phase_tasks}):
            if not callback_kind:
                raise ValueError("selected character ability callback kind missing")
            tasks = tuple(task for task in phase_tasks if task.callback_kind == callback_kind)
            selected = {task.task_id for task in tasks}
            ordered = tuple(task_id for task_id in phase.task_ids if task_id in selected)
            append_entry("ability_phase_callback", phase.phase_id, callback_kind, ordered,
                         tuple(_ability_task(task) for task in tasks))
    for callback in callbacks:
        tasks = tuple(tasks_by_callback[callback.callback_id])
        if not tasks:
            if callback.task_ids:
                raise ValueError("selected character taskless callback has root identities")
            continue
        append_entry("status_callback", callback.callback_id, callback.event,
                     _ordered_status_task_ids(callback, tasks), tuple(_status_task(task) for task in tasks))
    if not entries:
        return complete
    dispositions = _materialization_dispositions(
        complete.source_dispositions,
        tuple(entries),
        tuple(graphs),
        context.admitted_insert_action_task_ids,
    )
    return _catalog(source_catalog, "formal_slice" if len(entries) == 1 else "formal_catalog",
                    dispositions, tuple(entries), tuple(graphs))


def materialize_ability_phase_task_graph(
    source_catalog: CharacterControlFlowContractCatalog,
    canonical: CanonicalIR,
    *,
    phase_id: str,
    callback_kind: str,
    source_snapshot: CharacterAbilityRawSnapshot,
) -> TaskGraphCatalogIR:
    if type(canonical) is not CanonicalIR:
        raise TypeError("ability task graph materialization requires exact CanonicalIR")
    phases = tuple(item for item in canonical.ability_phases if item.phase_id == phase_id)
    if len(phases) != 1:
        raise ValueError("ability task graph phase is missing or ambiguous")
    tasks = tuple(
        item for item in canonical.ability_tasks
        if item.phase_id == phase_id and item.callback_kind == callback_kind
    )
    if not tasks:
        raise ValueError("ability task graph callback selection is empty")
    selected = {item.task_id for item in tasks}
    ordered = tuple(item for item in phases[0].task_ids if item in selected)
    if len(ordered) != len(tasks) or set(ordered) != selected:
        raise ValueError("ability phase task ledger is incomplete")
    return _materialize(
        source_catalog,
        canonical,
        "ability_phase_callback",
        phase_id,
        callback_kind,
        ordered,
        tuple(_ability_task(item) for item in tasks),
        source_snapshot,
    )


def materialize_status_callback_task_graph(
    source_catalog: CharacterControlFlowContractCatalog,
    canonical: CanonicalIR,
    *,
    callback_id: str,
    source_snapshot: CharacterAbilityRawSnapshot,
) -> TaskGraphCatalogIR:
    if type(canonical) is not CanonicalIR:
        raise TypeError("status task graph materialization requires exact CanonicalIR")
    callbacks = tuple(item for item in canonical.status_callbacks if item.callback_id == callback_id)
    if len(callbacks) != 1:
        raise ValueError("status task graph callback is missing or ambiguous")
    tasks = tuple(item for item in canonical.status_callback_tasks if item.callback_id == callback_id)
    if not tasks:
        raise ValueError("status task graph callback selection is empty")
    ordered = _ordered_status_task_ids(callbacks[0], tasks)
    return _materialize(
        source_catalog,
        canonical,
        "status_callback",
        callback_id,
        callbacks[0].event,
        ordered,
        tuple(_status_task(item) for item in tasks),
        source_snapshot,
    )


def attach_task_graph_catalog(canonical: CanonicalIR, catalog: TaskGraphCatalogIR) -> CanonicalIR:
    if type(canonical) is not CanonicalIR or type(catalog) is not TaskGraphCatalogIR:
        raise TypeError("task graph attachment requires exact production types")
    dependencies = build_external_task_topology_dependency_ledger(
        action_ability_bindings=canonical.action_ability_bindings,
        ability_phases=canonical.ability_phases,
        ability_tasks=canonical.ability_tasks,
        standalone_ability_graphs=canonical.standalone_ability_graphs,
        status_callbacks=canonical.status_callbacks,
        status_callback_tasks=canonical.status_callback_tasks,
    )
    return replace(
        canonical,
        task_graph_catalog=catalog,
        external_task_topology_dependencies=dependencies,
    )


def merge_task_graph_slices(
    complete_catalog: TaskGraphCatalogIR,
    slices: Iterable[TaskGraphCatalogIR],
    *,
    admitted_insert_action_task_ids: frozenset[str] = frozenset(),
) -> TaskGraphCatalogIR:
    """Merge source-closed formal slices for installation in one production RuleBook."""

    if type(complete_catalog) is not TaskGraphCatalogIR:
        raise TypeError("task graph merge requires the exact complete catalog")
    if complete_catalog.scope_mode != "complete_catalog":
        raise ValueError("task graph merge base must be the complete source catalog")
    authority = (
        complete_catalog.source_catalog_id,
        complete_catalog.snapshot_id,
        complete_catalog.scope_catalog_id,
        complete_catalog.source_fingerprint,
        complete_catalog.dependency_fingerprint,
        complete_catalog.source_record_count,
        complete_catalog.source_record_fingerprint,
    )
    entries: list[TaskGraphEntryMaterializationIR] = []
    graphs: list[TaskGraphIR] = []
    selected_any = False
    for item in slices:
        selected_any = True
        if type(item) is not TaskGraphCatalogIR:
            raise TypeError("task graph merge requires exact formal slices")
        if item.scope_mode != "formal_slice" or (
            item.source_catalog_id,
            item.snapshot_id,
            item.scope_catalog_id,
            item.source_fingerprint,
            item.dependency_fingerprint,
            item.source_record_count,
            item.source_record_fingerprint,
        ) != authority:
            raise ValueError("task graph slice is outside the complete source authority")
        expected = _materialization_dispositions(
            complete_catalog.source_dispositions,
            item.entry_materializations,
            item.graphs,
            admitted_insert_action_task_ids,
        )
        if item.source_dispositions != expected:
            raise ValueError("task graph slice source ledger is inconsistent with its base")
        entries.extend(item.entry_materializations)
        graphs.extend(item.graphs)
    if not selected_any:
        raise TypeError("task graph merge requires non-empty formal slices")
    if len({item.entry_id for item in entries}) != len(entries):
        raise ValueError("task graph merge contains duplicate formal entries")
    if len({item.graph_id for item in graphs}) != len(graphs):
        raise ValueError("task graph merge contains duplicate formal graphs")
    dispositions = _materialization_dispositions(
        complete_catalog.source_dispositions,
        tuple(entries),
        tuple(graphs),
        admitted_insert_action_task_ids,
    )
    return TaskGraphCatalogIR(
        scope_mode=("formal_slice" if len(entries) == 1 else "formal_catalog"),
        source_catalog_id=complete_catalog.source_catalog_id,
        snapshot_id=complete_catalog.snapshot_id,
        scope_catalog_id=complete_catalog.scope_catalog_id,
        source_fingerprint=complete_catalog.source_fingerprint,
        dependency_fingerprint=complete_catalog.dependency_fingerprint,
        source_record_count=complete_catalog.source_record_count,
        source_record_fingerprint=complete_catalog.source_record_fingerprint,
        source_dispositions=dispositions,
        entry_materializations=tuple(entries),
        graphs=tuple(graphs),
        selected_entry_ids=tuple(sorted(item.entry_id for item in entries)),
        source_ledger_complete=True,
    )


def _disposition(
    record_id: str,
    kind: str,
    family: str,
    source: IRSource,
    status: str,
    domains: Iterable[str],
    reason: str,
    materialization_ids: Iterable[str] = (),
) -> TaskGraphSourceDispositionIR:
    return TaskGraphSourceDispositionIR(
        source_record_id=record_id,
        source_kind=cast(Any, kind),
        source_occurrence_id=task_graph_source_occurrence_id(source, family),
        family=family,
        disposition=cast(Any, status),
        owner_domains=tuple(sorted(set(domains))),
        formal_materialization_ids=tuple(sorted(set(materialization_ids))),
        source=source,
        blocked_reason=reason,
    )


def _ability_task(task: AbilityTaskIR) -> _FormalTask:
    if type(task) is not AbilityTaskIR:
        raise TypeError("ability graph requires exact AbilityTaskIR values")
    if task.source.evidence.get("task_path") != task.task_path:
        raise ValueError("ability graph task position source is inconsistent")
    family = task.source.evidence.get("source_opcode")
    if task.linked_ability_phase_id and task.linked_standalone_graph_id:
        raise ValueError("ability task call target is ambiguous")
    return _FormalTask(
        task.task_id,
        task.task_path,
        task.opcode,
        family if isinstance(family, str) and family else task.opcode,
        task.condition_id,
        task.target_expression_id,
        task.effect_id,
        task.linked_ability_phase_id or task.linked_standalone_graph_id,
        (
            "ability_phase"
            if task.linked_ability_phase_id
            else "standalone_ability"
            if task.linked_standalone_graph_id
            else ""
        ),
        task.execution_mode,
        task.coverage_status,
        task.source,
        action_id=str(getattr(task, "action_id", "") or ""),
    )


def _status_task(task: StatusCallbackTaskIR) -> _FormalTask:
    if type(task) is not StatusCallbackTaskIR:
        raise TypeError("status graph requires exact StatusCallbackTaskIR values")
    if (
        task.source.evidence.get("graph_task_path") != task.task_path
        or task.source.evidence.get("task_path") != task.task_path
    ):
        raise ValueError("status graph task position source is inconsistent")
    family = task.source.evidence.get("raw_opcode")
    return _FormalTask(
        task.task_id,
        task.task_path,
        task.opcode,
        family if isinstance(family, str) and family else task.opcode,
        task.condition_id,
        task.target_expression_id,
        task.effect_id,
        task.linked_ability_phase_id or task.linked_standalone_graph_id,
        (
            "ability_phase"
            if task.linked_ability_phase_id
            else "standalone_ability"
            if task.linked_standalone_graph_id
            else ""
        ),
        "process_only" if task.blocked_reason == "source_proven_presentation_only" else "runtime_effect",
        "audit_only" if task.blocked_reason == "source_proven_presentation_only" else task.coverage_status,
        task.source,
        (str(task.task_payload.get("committed_break_template_id") or "")
         if task.opcode == "IncludeTaskListTemplate" and task.event == "OnTriggerStanceCountDown" else ""),
    )


def _materialize(
    source_catalog: CharacterControlFlowContractCatalog,
    canonical: CanonicalIR,
    entry_kind: EntryKind,
    owner_id: str,
    callback_kind: str,
    ordered_task_ids: tuple[str, ...],
    tasks: tuple[_FormalTask, ...],
    source_snapshot: CharacterAbilityRawSnapshot,
) -> TaskGraphCatalogIR:
    context = _prepare_materialization(source_catalog, canonical, source_snapshot)
    entry, graph = _materialize_entry(
        context,
        entry_kind,
        owner_id,
        callback_kind,
        ordered_task_ids,
        tasks,
    )
    graphs = (graph,) if graph is not None else ()
    dispositions = _materialization_dispositions(
        context.base.source_dispositions,
        (entry,),
        graphs,
        context.admitted_insert_action_task_ids,
    )
    return _catalog(
        source_catalog,
        "formal_slice",
        dispositions,
        (entry,),
        graphs,
    )


def _prepare_materialization(
    source_catalog: CharacterControlFlowContractCatalog,
    canonical: CanonicalIR,
    source_snapshot: CharacterAbilityRawSnapshot,
) -> _MaterializationContext:
    base = build_complete_task_graph_catalog(source_catalog, source_snapshot)
    digest_by_path = _source_digest_by_path(source_catalog)
    for item in source_snapshot.sources:
        path, digest = item.source.source_path, item.content_sha256
        existing = digest_by_path.get(path)
        if existing is not None and existing != digest:
            raise ValueError("task graph source file fingerprint conflicts with S8A")
        digest_by_path[path] = digest
    controls_by_location: dict[
        tuple[str, object, str], list[CharacterControlFlowNodeIR]
    ] = defaultdict(list)
    for item in source_catalog.nodes:
        controls_by_location[
            (item.source.source_path, item.source.evidence["json_path"], item.family)
        ].append(item)
    if any(len(items) != 1 for items in controls_by_location.values()):
        raise ValueError("task graph source catalog contains ambiguous source occurrences")
    templates: dict[str, list[ControlFlowTemplateDefinitionIR]] = defaultdict(list)
    for item in source_catalog.template_definitions:
        templates[item.template_id].append(item)
    if any(len(items) != 1 for items in templates.values()):
        raise ValueError("task graph template definition identity is ambiguous")
    refs_by_node: dict[str, list[ControlFlowTemplateReferenceIR]] = defaultdict(list)
    for item in source_catalog.template_references:
        refs_by_node[item.node_id].append(item)
    return _MaterializationContext(
        source_catalog,
        base,
        source_snapshot,
        digest_by_path,
        {key: values[0] for key, values in controls_by_location.items()},
        {key: values[0] for key, values in templates.items()},
        {key: tuple(values) for key, values in refs_by_node.items()},
        _DefinitionIndexes(
            _definition_multimap(canonical.conditions, ConditionIR, "condition_id"),
            _definition_multimap(
                canonical.target_expressions,
                TargetExpressionIR,
                "target_expression_id",
            ),
            _definition_multimap(canonical.effects, EffectIR, "effect_id"),
            _definition_multimap(
                (*canonical.ability_phases, *canonical.standalone_ability_graphs),
                (AbilityPhaseIR, StandaloneAbilityGraphIR),
                ("phase_id", "standalone_ability_graph_id"),
            ),
        ),
        _admitted_insert_action_task_ids(canonical),
    )


def _definition_multimap(
    values: Iterable[object],
    expected_type: type[object] | tuple[type[object], ...],
    identity_field: str | tuple[str, ...],
) -> dict[str, tuple[Any, ...]]:
    result: dict[str, list[Any]] = defaultdict(list)
    fields = (identity_field,) if isinstance(identity_field, str) else identity_field
    for value in values:
        if not isinstance(value, expected_type) or type(value) not in (
            expected_type if isinstance(expected_type, tuple) else (expected_type,)
        ):
            raise TypeError("task graph definition catalog contains an invalid type")
        identity = next(
            (
                candidate
                for field_name in fields
                if isinstance((candidate := getattr(value, field_name, None)), str)
                and candidate
            ),
            "",
        )
        if not identity:
            raise ValueError("task graph definition identity is missing")
        result[identity].append(value)
    return {key: tuple(items) for key, items in result.items()}


def _materialize_entry(
    context: _MaterializationContext,
    entry_kind: EntryKind,
    owner_id: str,
    callback_kind: str,
    ordered_task_ids: tuple[str, ...],
    tasks: tuple[_FormalTask, ...],
) -> tuple[TaskGraphEntryMaterializationIR, TaskGraphIR | None]:
    if not ordered_task_ids or len({item.task_id for item in tasks}) != len(tasks):
        raise ValueError("formal task graph contains empty or duplicate task identities")
    entry_id = task_graph_entry_id(entry_kind, owner_id, callback_kind)
    graph_id = task_graph_id(
        context.base.source_catalog_id,
        entry_id,
        context.base.source_fingerprint,
    )
    source_by_task: dict[str, IRSource] = {}
    occurrence_by_task: dict[str, str] = {}
    control_by_task: dict[str, CharacterControlFlowNodeIR] = {}
    for task in tasks:
        source = _formal_source(task, context.digest_by_path)
        source_by_task[task.task_id] = source
        location = (source.source_path, source.evidence["json_path"], task.family)
        control = context.control_by_location.get(location)
        if control is not None:
            control_by_task[task.task_id] = control
        occurrence_by_task[task.task_id] = task_graph_source_occurrence_id(source, task.family)
    occurrence_ids = tuple(occurrence_by_task[task_id] for task_id in ordered_task_ids)
    materialization_id = task_graph_materialization_id(
        entry_id,
        ordered_task_ids,
        occurrence_ids,
    )
    entry_source = source_by_task[ordered_task_ids[0]]
    try:
        graph = _build_graph(
            context.source_catalog,
            context.source_snapshot,
            graph_id,
            entry_id,
            entry_kind,
            owner_id,
            callback_kind,
            ordered_task_ids,
            tasks,
            source_by_task,
            occurrence_by_task,
            control_by_task,
            context.template_by_id,
            context.template_refs_by_node,
            context.definitions,
            context.admitted_insert_action_task_ids,
        )
    except _Blocked as exc:
        entry = TaskGraphEntryMaterializationIR(
            materialization_id,
            entry_id,
            entry_kind,
            owner_id,
            callback_kind,
            "",
            ordered_task_ids,
            occurrence_ids,
            "blocked",
            entry_source,
            str(exc),
        )
        return entry, None
    entry = TaskGraphEntryMaterializationIR(
        materialization_id,
        entry_id,
        entry_kind,
        owner_id,
        callback_kind,
        graph.graph_id,
        ordered_task_ids,
        occurrence_ids,
        "materialized",
        entry_source,
    )
    return entry, graph


def _build_graph(
    source_catalog: CharacterControlFlowContractCatalog,
    source_snapshot: CharacterAbilityRawSnapshot,
    graph_id: str,
    entry_id: str,
    entry_kind: EntryKind,
    owner_id: str,
    callback_kind: str,
    ordered_task_ids: tuple[str, ...],
    tasks: tuple[_FormalTask, ...],
    sources: Mapping[str, IRSource],
    occurrences: Mapping[str, str],
    controls: Mapping[str, CharacterControlFlowNodeIR],
    template_by_id: Mapping[str, ControlFlowTemplateDefinitionIR],
    refs_by_node: Mapping[str, tuple[ControlFlowTemplateReferenceIR, ...]],
    definitions: _DefinitionIndexes,
    admitted_insert_action_task_ids: frozenset[str],
) -> TaskGraphIR:
    task_by_id = {item.task_id: item for item in tasks}
    if set(ordered_task_ids) != set(task_by_id):
        raise _Blocked("formal_entry_task_set_mismatch")
    source_topology, root_task_ids = _source_topology(
        task_by_id,
        ordered_task_ids,
        sources,
        controls,
        refs_by_node,
        template_by_id,
    )
    node_ids = {
        task_id: task_graph_node_id(graph_id, task_id, occurrences[task_id])
        for task_id in task_by_id
    }
    roots = tuple(node_ids[task_id] for task_id in root_task_ids)
    # A status-callback graph is executed by the event dispatch system itself,
    # so controls whose downstream work lives in that domain are already closed.
    closed_domains = (
        _ALREADY_CLOSED_DOMAINS | {"event_dispatch"}
        if entry_kind == "status_callback"
        else _ALREADY_CLOSED_DOMAINS
    )
    numeric: list[TaskGraphNumericDefinitionIR] = []
    weighted: list[TaskGraphWeightedSelectionIR] = []
    nodes: list[TaskGraphNodeIR] = []
    skipped_node_ids: set[str] = set()
    for task in tasks:
        control = controls.get(task.task_id)
        if control is not None and control.coverage_status == "blocked":
            raise _Blocked(
                f"task_graph_source_contract_blocked:{control.node_id}:"
                f"{control.blocked_reason}"
            )
        if _presentation_only_template_task(
            control,
            template_by_id,
            refs_by_node,
            source_snapshot,
        ):
            skipped_node_ids.add(node_ids[task.task_id])
            continue
        branches = _branches(
            task,
            source_topology[task.task_id],
            node_ids,
        )
        weighted_selection = None
        if control is not None and control.family == "RandomConfig":
            weighted_selection = _materialize_weighted_selection(
                source_snapshot,
                node_ids[task.task_id],
                sources[task.task_id],
                occurrences[task.task_id],
                branches,
            )
            weighted.append(weighted_selection)
        references = list(_references(
            task,
            control,
            node_ids[task.task_id],
            sources[task.task_id],
            definitions,
            refs_by_node,
        ))
        termination_kind = "not_applicable"
        termination_status = "not_applicable"
        termination_numeric_definition_id = ""
        if control is not None:
            termination_kind = control.termination.termination_kind
            termination_status = control.termination.status
        if control is not None and control.termination.expression is not None:
            definition_id = task_graph_numeric_id(occurrences[task.task_id], control.termination.expression)
            termination_numeric_definition_id = definition_id
            numeric.append(TaskGraphNumericDefinitionIR(
                definition_id,
                occurrences[task.task_id],
                control.termination.expression,
                control.termination.source,
            ))
            references.append(TaskGraphDefinitionReferenceIR(
                task_graph_reference_id(node_ids[task.task_id], "numeric", definition_id),
                node_ids[task.task_id],
                "numeric",
                definition_id,
                "",
                "resolved",
                "task_graph_execution",
                control.termination.source,
            ))
        node_kind, status, owner_domains, reason = _node_status(
            control, task, references, closed_domains=closed_domains,
        )
        if (
            task.task_id in admitted_insert_action_task_ids
            and _insert_action_queue_shape(control, task, branches)
        ):
            # The formal queue intent, window and resolution admit this
            # insertion; its OnInsertAbort children stay in the graph as the
            # delayed cancellation branch and are retired by the source
            # disposition once the runtime cancellation path is proven.
            node_kind, status, owner_domains, reason = (
                "sequence", "materialized", ("task_graph_execution",), ""
            )
        template_parameters = ()
        if node_kind == "template_call" and control is not None:
            template_refs = refs_by_node.get(control.node_id, ())
            if len(template_refs) != 1:
                raise _Blocked("template_parameter_reference_not_unique")
            template = template_by_id.get(template_refs[0].resolved_template_id)
            if template is None:
                raise _Blocked("template_parameter_definition_missing")
            if task.consumed_template_id:
                raw = _raw_source_value(source_snapshot, sources[task.task_id].source_path,
                                        str(sources[task.task_id].evidence["json_path"]))
                values = raw.get("DynamicValues", {}) if isinstance(raw, Mapping) else None
                if (not isinstance(values, Mapping) or raw.get("DynamicStrings")
                        or set(values) - {"DitherRangeX", "DitherRangeY", "UIMessageHeight"}):
                    raise _Blocked("consumed_template_parameters_not_admitted")
                # L0 closed this include against the domain-applied template.
                # Its remaining supplied values feed only excluded presentation.
            else:
                template_parameters = _materialize_template_parameters(
                    source_snapshot,
                    sources[task.task_id],
                    template,
                    allow_unused_presentation=task.action_id.startswith("servant_skill:"),
                )
        if (
            control is not None
            and control.family == task.family == "RandomConfig"
            and control.control_role == "random_branch"
            and control.coverage_status == "lowered_with_obligation"
            and task.execution_mode != "process_only"
            and node_kind == "deferred"
            and status == "deferred"
            and owner_domains == ("hit_random_sequence",)
            and _random_config_control_references_are_source_owned(
                task, references, definitions
            )
            and type(weighted_selection) is TaskGraphWeightedSelectionIR
        ):
            # The source-validated selection can use the shared weighted hook.
            # The caller still owns weight evaluation/RNG and may block; other
            # domain obligations and child/reference admission remain unchanged.
            node_kind, status, owner_domains, reason = (
                "branch", "materialized", ("task_graph_execution",), ""
            )
        nodes.append(TaskGraphNodeIR(
            node_ids[task.task_id],
            graph_id,
            occurrences[task.task_id],
            control.node_id if control is not None else "",
            task.task_id,
            task.opcode,
            task.family,
            cast(Any, node_kind),
            branches,
            tuple(references),
            cast(Any, termination_kind),
            cast(Any, termination_status),
            termination_numeric_definition_id,
            cast(Any, status),
            owner_domains,
            sources[task.task_id],
            reason,
            template_parameters,
        ))
    roots = tuple(node_id for node_id in roots if node_id not in skipped_node_ids)
    if not roots:
        raise _Blocked("formal_entry_root_missing")
    has_obligation = any(item.materialization_status == "deferred" for item in nodes) or any(
        ref.resolution_status != "resolved" for node in nodes for ref in node.references
    )
    numeric_by_id: dict[str, TaskGraphNumericDefinitionIR] = {}
    for definition in numeric:
        existing = numeric_by_id.get(definition.definition_id)
        if existing is not None and existing != definition:
            raise _Blocked(f"task_graph_numeric_definition_conflict:{definition.definition_id}")
        numeric_by_id[definition.definition_id] = definition
    return TaskGraphIR(
        graph_id,
        entry_id,
        entry_kind,
        owner_id,
        callback_kind,
        roots,
        tuple(nodes),
        tuple(numeric_by_id.values()),
        source_catalog.catalog_id,
        source_catalog.source_fingerprint,
        sources[ordered_task_ids[0]],
        "lowered_with_obligation" if has_obligation else "lowered",
        tuple(weighted),
    )


def _source_topology(
    task_by_id: Mapping[str, _FormalTask],
    ordered_task_ids: tuple[str, ...],
    sources: Mapping[str, IRSource],
    controls: Mapping[str, CharacterControlFlowNodeIR],
    refs_by_node: Mapping[str, tuple[ControlFlowTemplateReferenceIR, ...]],
    templates: Mapping[str, ControlFlowTemplateDefinitionIR],
) -> tuple[dict[str, tuple[_SourceBranch, ...]], tuple[str, ...]]:
    tasks_by_location: dict[tuple[str, str, str, str], list[str]] = defaultdict(
        list
    )
    for task_id, task in task_by_id.items():
        source = sources[task_id]
        path = source.evidence.get("json_path")
        if not isinstance(path, str) or not path.startswith("$"):
            raise _Blocked(f"formal_task_source_path_invalid:{task_id}")
        tasks_by_location[
            (source.source_path, path, task.family, task.graph_task_path)
        ].append(task_id)
    if any(len(values) != 1 for values in tasks_by_location.values()):
        raise _Blocked("formal_task_source_occurrence_ambiguous")

    def resolve_child(
        parent: _FormalTask,
        source: IRSource,
        family: str,
        branch_position: int,
        child_ordinal: int,
    ) -> str:
        path = str(source.evidence.get("json_path") or "").removesuffix(".$type")
        graph_path = (
            f"{parent.graph_task_path}.formal_branch[{branch_position}]"
            f".child[{child_ordinal}]"
        )
        values = tasks_by_location.get(
            (source.source_path, path, family, graph_path), ()
        )
        if len(values) != 1:
            raise _Blocked(
                f"formal_branch_child_{'missing' if not values else 'ambiguous'}:"
                f"{source.source_path}:{path}:{family}"
            )
        child_id = values[0]
        child_source = sources[child_id]
        if (
            child_source.evidence.get("content_sha256")
            != source.evidence.get("content_sha256")
        ):
            raise _Blocked(f"formal_branch_child_source_mismatch:{child_id}")
        return child_id

    topology: dict[str, tuple[_SourceBranch, ...]] = {}
    parent_counts = {task_id: 0 for task_id in task_by_id}
    adjacency: dict[str, tuple[str, ...]] = {}
    for task_id, task in task_by_id.items():
        control = controls.get(task_id)
        rows: list[_SourceBranch] = []
        child_position = 0
        if control is not None:
            for branch in control.branches:
                child_ids: list[str] = []
                for child in branch.children:
                    child_ids.append(
                        resolve_child(
                            task,
                            child.source,
                            child.family,
                            child_position,
                            child.ordinal,
                        )
                    )
                    child_position += 1
                rows.append(
                    _SourceBranch(
                        branch.branch_kind,
                        branch.label,
                        tuple(child_ids),
                        branch.source,
                    )
                )
            if control.control_role == "template_include":
                references = tuple(refs_by_node.get(control.node_id, ()))
                if len(references) != 1 or references[0].coverage_status != "lowered":
                    raise _Blocked(
                        f"formal_template_reference_not_resolved:{control.node_id}"
                    )
                template = templates.get(references[0].resolved_template_id)
                if template is None:
                    raise _Blocked(
                        "formal_template_definition_missing:"
                        f"{references[0].resolved_template_id}"
                    )
                child_ids = []
                for child in template.children:
                    child_ids.append(
                        resolve_child(
                            task,
                            child.source,
                            child.family,
                            child_position,
                            child.ordinal,
                        )
                    )
                    child_position += 1
                rows.append(
                    _SourceBranch(
                        "template_body",
                        template.template_id,
                        tuple(child_ids),
                        template.source,
                    )
                )
            if control.control_role == "parallel_templates":
                references = tuple(refs_by_node.get(control.node_id, ()))
                if not references or any(
                    reference.coverage_status != "lowered"
                    or not reference.resolved_template_id
                    for reference in references
                ):
                    raise _Blocked(
                        f"formal_template_reference_not_resolved:{control.node_id}"
                    )
                for reference in references:
                    template = templates.get(reference.resolved_template_id)
                    if template is None:
                        raise _Blocked(
                            "formal_template_definition_missing:"
                            f"{reference.resolved_template_id}"
                        )
                    child_ids = []
                    for child in template.children:
                        child_ids.append(
                            resolve_child(
                                task,
                                child.source,
                                child.family,
                                child_position,
                                child.ordinal,
                            )
                        )
                        child_position += 1
                    rows.append(
                        _SourceBranch(
                            "template_body",
                            template.template_id,
                            tuple(child_ids),
                            template.source,
                        )
                    )
        children = tuple(
            child_id for row in rows for child_id in row.child_task_ids
        )
        if len(children) != len(set(children)) or task_id in children:
            raise _Blocked(f"formal_child_identity_invalid:{task_id}")
        topology[task_id] = tuple(rows)
        adjacency[task_id] = children
        for child_id in children:
            parent_counts[child_id] += 1
    if any(count > 1 for count in parent_counts.values()):
        raise _Blocked("formal_parent_ownership_ambiguous")
    roots = tuple(task_id for task_id in ordered_task_ids if parent_counts[task_id] == 0)
    if not roots:
        raise _Blocked("formal_entry_root_missing")
    reached: set[str] = set()
    pending = list(roots)
    while pending:
        task_id = pending.pop()
        if task_id in reached:
            continue
        reached.add(task_id)
        pending.extend(adjacency[task_id])
    if reached != set(task_by_id):
        raise _Blocked("formal_task_cycle_or_unreachable_node")
    return topology, roots


def _branches(
    task: _FormalTask,
    source_branches: tuple[_SourceBranch, ...],
    node_ids: Mapping[str, str],
) -> tuple[TaskGraphBranchIR, ...]:
    result: list[TaskGraphBranchIR] = []
    for ordinal, branch in enumerate(source_branches):
        child_ids = tuple(node_ids[item] for item in branch.child_task_ids)
        result.append(TaskGraphBranchIR(
            task_graph_branch_id(
                node_ids[task.task_id],
                branch.branch_kind,
                ordinal,
                branch.label,
                child_ids,
            ),
            node_ids[task.task_id],
            branch.branch_kind,
            ordinal,
            branch.label,
            child_ids,
            branch.source,
        ))
    return tuple(result)


def _materialize_weighted_selection(
    source_snapshot: CharacterAbilityRawSnapshot,
    graph_node_id: str,
    parent_source: IRSource,
    parent_source_occurrence_id: str,
    branches: tuple[TaskGraphBranchIR, ...],
) -> TaskGraphWeightedSelectionIR:
    parent_path = parent_source.evidence.get("json_path")
    if not isinstance(parent_path, str) or not parent_path.startswith("$"):
        raise _Blocked("random_config_parent_source_path_invalid")
    raw_parent = _raw_source_value(source_snapshot, parent_source.source_path, parent_path)
    if not isinstance(raw_parent, Mapping):
        raise _Blocked("random_config_parent_source_not_object")
    odds_list = raw_parent.get("OddsList")
    if type(odds_list) is not list:
        raise _Blocked("random_config_odds_list_invalid")
    if not odds_list or len(odds_list) != len(branches):
        raise _Blocked("random_config_odds_list_branch_length_mismatch")
    choices: list[TaskGraphWeightedChoiceIR] = []
    definitions: list[TaskGraphNumericDefinitionIR] = []
    for index, (raw_weight, branch) in enumerate(zip(odds_list, branches, strict=True)):
        child_path = f"{parent_path}.OddsList[{index}]"
        evidence = thaw_json(parent_source.evidence)
        if not isinstance(evidence, dict):
            raise _Blocked("random_config_parent_source_evidence_invalid")
        evidence["json_path"] = child_path
        child_source = IRSource(
            parent_source.source_path,
            parent_source.raw_type,
            parent_source.raw_id,
            evidence,
        )
        occurrence_id = task_graph_source_occurrence_id(child_source, "RandomConfig")
        expression = lower_numeric_expression(raw_weight)
        definition_id = task_graph_numeric_id(occurrence_id, expression)
        definition = TaskGraphNumericDefinitionIR(
            definition_id,
            occurrence_id,
            expression,
            child_source,
        )
        choice = TaskGraphWeightedChoiceIR(
            task_graph_weighted_choice_id(
                graph_node_id,
                index,
                branch.branch_id,
                definition_id,
            ),
            graph_node_id,
            "RandomConfig",
            index,
            branch.branch_id,
            definition_id,
            occurrence_id,
            child_source,
        )
        definitions.append(definition)
        choices.append(choice)
    return TaskGraphWeightedSelectionIR(
        task_graph_weighted_selection_id(
            graph_node_id,
            parent_source_occurrence_id,
        ),
        graph_node_id,
        parent_source_occurrence_id,
        "RandomConfig",
        "weighted_single",
        tuple(choices),
        tuple(definitions),
        parent_source,
    )


def _materialize_template_parameters(
    snapshot: CharacterAbilityRawSnapshot,
    source: IRSource,
    template: ControlFlowTemplateDefinitionIR,
    *,
    allow_unused_presentation: bool = False,
) -> tuple[TaskGraphTemplateParameterIR, ...]:
    raw = _raw_source_value(snapshot, source.source_path, str(source.evidence["json_path"]))
    if not isinstance(raw, Mapping):
        raise _Blocked("template_parameter_call_source_invalid")
    if raw.get("DynamicStrings"):
        raise _Blocked("template_dynamic_string_parameters_not_admitted")
    values = raw.get("DynamicValues", {})
    if not isinstance(values, Mapping):
        raise _Blocked("template_dynamic_values_invalid")
    declared = {item.key: item for item in template.parameters if item.parameter_kind == "dynamic_float"}
    result = []
    for name, value in sorted(values.items()):
        if not isinstance(name, str) or not name:
            raise _Blocked("template_dynamic_parameter_name_invalid")
        destination_hash = str(tbgd_dynamic_key_hash(name))
        declaration = declared.get(destination_hash)
        implicit_parameter_source: dict[str, Any] | None = None
        if declaration is None:
            consumes_parameter = _template_consumes_parameter(
                snapshot, template, name, destination_hash
            )
            # An unused caller-supplied parameter never enters the formal body:
            # the value stays in the frame binding ledger with an explicit
            # presentation provenance instead of blocking the executable body.
            # Consumed-but-undeclared parameters still fail closed below.
            implicit_parameter_source = {
                "parameter_declaration_source": (
                    "template_task_list_consumes_named_parameter"
                    if consumes_parameter
                    else "template_call_parameter_unused_presentation"
                ),
                "parameter_name": name,
                "parameter_hash": destination_hash,
            }
        elif declaration.read_type != "None" or declaration.index != 0:
            raise _Blocked(f"template_dynamic_parameter_not_declared:{name}")
        expression = lower_numeric_expression(value)
        if expression.get("supported") is not True:
            raise _Blocked(f"template_dynamic_parameter_expression_not_admitted:{name}")
        parameter_source = IRSource(source.source_path, source.raw_type, source.raw_id,
            {**dict(source.evidence), "json_path": f"{source.evidence['json_path']}.DynamicValues[{json.dumps(name, ensure_ascii=True)}]",
             **(
                 implicit_parameter_source
                 if implicit_parameter_source is not None
                 else {"parameter_declaration_source": declaration.source.to_json()}
             )})
        result.append(TaskGraphTemplateParameterIR(
            name,
            destination_hash if implicit_parameter_source is not None else declaration.key,
            expression,
            parameter_source,
        ))
    return tuple(result)


def _presentation_only_template_task(
    control: CharacterControlFlowNodeIR | None,
    template_by_id: Mapping[str, ControlFlowTemplateDefinitionIR],
    refs_by_node: Mapping[str, tuple[ControlFlowTemplateReferenceIR, ...]],
    source_snapshot: CharacterAbilityRawSnapshot,
) -> bool:
    """A template call whose every referenced template body is non-gameplay.

    These nodes carry no battle mechanics: excluding them from the formal graph
    keeps presentation-only servant view/group templates out of execution,
    while any gameplay body stays materialized and blocks on its own gaps.
    """

    if control is None or control.coverage_status == "blocked":
        return False
    if control.control_role not in {"template_include", "parallel_templates"}:
        return False
    refs = tuple(refs_by_node.get(control.node_id, ()))
    if not refs or any(
        ref.coverage_status != "lowered" or not ref.resolved_template_id
        for ref in refs
    ):
        return False
    for ref in refs:
        template = template_by_id.get(ref.resolved_template_id)
        if template is None or not _template_body_is_non_gameplay(
            source_snapshot, template,
        ):
            return False
    return True


def _template_body_is_non_gameplay(
    source_snapshot: CharacterAbilityRawSnapshot,
    template: ControlFlowTemplateDefinitionIR,
) -> bool:
    json_path = template.source.evidence.get("json_path")
    if not isinstance(json_path, str) or not json_path:
        return False
    try:
        raw = _raw_source_value(
            source_snapshot,
            template.source.source_path,
            f"{json_path}.TaskList",
        )
    except _Blocked:
        return False
    found, safe = _typed_subtree_is_non_gameplay(raw)
    return bool(found and safe)


def _template_consumes_parameter(
    snapshot: CharacterAbilityRawSnapshot,
    template: ControlFlowTemplateDefinitionIR,
    name: str,
    parameter_hash: str,
) -> bool:
    """Admit an include value only when the template body consumes it.

    Some source templates omit an explicit DynamicValues declaration and instead
    read the named parameter inside their task list. The include value is then
    declared by actual consumption: the template body must reference either the
    name hash in a numeric dynamic expression or the name in a dynamic-key
    slot. A template that never reads the value stays fail-closed.
    """

    json_path = template.source.evidence.get("json_path")
    if not isinstance(json_path, str) or not json_path:
        return False
    try:
        raw = _raw_source_value(
            snapshot,
            template.source.source_path,
            f"{json_path}.TaskList",
        )
    except _Blocked:
        return False

    def consumes(node: object, parent_key: str = "") -> bool:
        if isinstance(node, Mapping):
            hashes = node.get("DynamicHashes")
            if isinstance(hashes, (list, tuple)) and any(
                str(item) == parameter_hash for item in hashes
            ):
                return True
            if parent_key in {"DynamicKey", "Key"}:
                value = node.get("Value")
                if isinstance(value, str) and value == name:
                    return True
            return any(
                consumes(child, str(key))
                for key, child in node.items()
                if key != "TaskList" or True
            )
        if isinstance(node, (list, tuple)):
            return any(consumes(child, parent_key) for child in node)
        return False

    return consumes(raw)


def _raw_source_value(
    source_snapshot: CharacterAbilityRawSnapshot,
    source_path: str,
    json_path: str,
) -> object:
    raw_bytes = source_snapshot.source_bytes.get(source_path)
    if raw_bytes is None:
        raise _Blocked(f"random_config_source_bytes_missing:{source_path}")
    try:
        current: object = json.loads(raw_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _Blocked(f"random_config_source_bytes_unreadable:{source_path}") from exc
    if not json_path.startswith("$"):
        raise _Blocked("random_config_source_path_invalid")
    cursor = 1
    while cursor < len(json_path):
        marker = json_path[cursor]
        if marker == ".":
            cursor += 1
            end = cursor
            while end < len(json_path) and json_path[end] not in ".[":
                end += 1
            key = json_path[cursor:end]
            if not key or not isinstance(current, Mapping) or key not in current:
                raise _Blocked(f"random_config_source_path_missing:{json_path}")
            current = current[key]
            cursor = end
            continue
        if marker == "[":
            end = json_path.find("]", cursor + 1)
            if end < 0:
                raise _Blocked(f"random_config_source_path_invalid:{json_path}")
            raw_index = json_path[cursor + 1 : end]
            if not raw_index.isdigit() or type(current) is not list:
                raise _Blocked(f"random_config_source_path_invalid:{json_path}")
            index = int(raw_index)
            if index >= len(current):
                raise _Blocked(f"random_config_source_path_missing:{json_path}")
            current = current[index]
            cursor = end + 1
            continue
        raise _Blocked(f"random_config_source_path_invalid:{json_path}")
    return current


def _is_wait_anim_state_process_only_presentation_shape(
    control: CharacterControlFlowNodeIR | None,
    task: _FormalTask,
) -> bool:
    if control is None:
        return False
    return (
        control.family in {"WaitAnimState", "WaitTimelineFinish", "WaitSecond"}
        and control.control_role == "presentation_barrier"
        and control.coverage_status != "blocked"
        and task.family == control.family
        and task.opcode == control.family
        and task.execution_mode == "process_only"
        and task.coverage_status == "audit_only"
        and bool(task.effect_id)
        and not task.condition_id
        and not task.target_expression_id
        and not task.ability_definition_id
        and not control.branches
        and not control.template_reference_ids
        and control.termination.termination_kind == "not_applicable"
        and control.termination.status == "not_applicable"
        and control.downstream_stages == ("p9_s8c",)
        and all(
            item.responsibility == "presentation_excluded"
            and item.owner_stage == "excluded"
            for item in control.field_responsibilities
        )
    )


def _wait_anim_state_process_only_effect(
    task: _FormalTask,
    indexes: _DefinitionIndexes,
) -> EffectIR:
    matches = indexes.effects.get(task.effect_id, ())
    if len(matches) != 1:
        raise _Blocked(
            "task_graph_wait_anim_state_process_only_effect_"
            + ("missing" if not matches else "ambiguous")
        )
    effect = matches[0]
    contract = effect.payload.get("process_only_contract")
    source_fields = (
        contract.get("source_fields") if isinstance(contract, Mapping) else None
    )
    source_field_types = (
        contract.get("source_field_types") if isinstance(contract, Mapping) else None
    )
    if (
        effect.opcode != task.opcode
        or effect.coverage_status != "audit_only"
        or effect.source != task.source
        or not isinstance(contract, Mapping)
        or contract.get("schema_version") != "ability_process_only_source_shape_v1"
        or contract.get("opcode") != task.opcode
        or contract.get("source_shape_status") != "admitted"
        or bool(contract.get("blocked_reason"))
        or not isinstance(source_fields, (list, tuple))
        or "$type" not in source_fields
        or len(source_fields) != len(set(source_fields))
        or not isinstance(source_field_types, Mapping)
        or set(source_field_types) != set(source_fields)
        or not all(
            isinstance(field_name, str)
            and field_name
            and isinstance(field_type, str)
            and field_type
            for field_name, field_type in source_field_types.items()
        )
    ):
        raise _Blocked(
            "task_graph_wait_anim_state_process_only_effect_contract_invalid"
        )
    return effect


def _is_death_settlement_barrier_shape(control, task) -> bool:
    return bool(
        control is not None and control.family == task.family == task.opcode == "TriggerSkipDeadHandler"
        and control.control_role == "death_barrier" and control.coverage_status != "blocked"
        and not control.blocked_reason and not control.peer_field_names and not control.field_responsibilities
        and not control.branches and not control.template_reference_ids
        and control.termination.termination_kind == control.termination.status == "not_applicable"
        and control.downstream_stages == ("p9_s14",)
        and task.execution_mode == "runtime_effect" and task.coverage_status == "executable"
        and task.effect_id and not task.condition_id and not task.target_expression_id
        and not task.ability_definition_id
    )


def _is_process_only_settlement_barrier_shape(
    control: CharacterControlFlowNodeIR | None,
    task: _FormalTask,
) -> bool:
    if control is None:
        return False
    return (
        control.family in {"DamagePerformFinish", "SkillPerformFinish"}
        and control.control_role == "settlement_barrier"
        and control.coverage_status != "blocked"
        and not control.blocked_reason
        and (
            (not control.peer_field_names and not control.field_responsibilities)
            or (
                control.family == "DamagePerformFinish"
                and control.peer_field_names in {
                    ("SkipDeathSettlement",),
                    ("IsFakeAvatarAttack",),
                    ("IsFakeAvatarAttack", "SkipDeathSettlement"),
                }
                and all(
                    responsibility.responsibility == "downstream_gameplay"
                    and responsibility.owner_stage == "p9_s11"
                    for responsibility in control.field_responsibilities
                )
            )
        )
        and not control.branches
        and not control.template_reference_ids
        and control.termination.termination_kind == "not_applicable"
        and control.termination.status == "not_applicable"
        and control.downstream_stages == ("p9_s11",)
        and task.family == control.family
        and task.opcode == control.family
        and task.execution_mode == "process_only"
        and task.coverage_status == "audit_only"
        and bool(task.effect_id)
        and not task.condition_id
        and not task.target_expression_id
        and not task.ability_definition_id
    )


def _process_only_settlement_barrier_effect(
    task: _FormalTask,
    indexes: _DefinitionIndexes,
) -> EffectIR:
    matches = indexes.effects.get(task.effect_id, ())
    if len(matches) != 1:
        raise _Blocked(
            "task_graph_process_only_settlement_barrier_effect_"
            + ("missing" if not matches else "ambiguous")
        )
    effect = matches[0]
    contract = effect.payload.get("process_only_contract")
    source_fields = (
        contract.get("source_fields") if isinstance(contract, Mapping) else None
    )
    source_field_types = (
        contract.get("source_field_types") if isinstance(contract, Mapping) else None
    )
    if (
        effect.opcode != task.opcode
        or effect.coverage_status != "audit_only"
        or effect.source != task.source
        or not isinstance(contract, Mapping)
        or contract.get("schema_version") != "ability_process_only_source_shape_v1"
        or contract.get("opcode") != task.opcode
        or contract.get("source_shape_status") != "admitted"
        or bool(contract.get("blocked_reason"))
        or not isinstance(source_fields, list)
        or set(source_fields) - {"$type", "SkipDeathSettlement", "IsFakeAvatarAttack"}
        or "$type" not in source_fields
        or not isinstance(source_field_types, Mapping)
        or dict(source_field_types) != {
            key: "bool" if key != "$type" else "str"
            for key in source_fields
        }
        or any(
            (
                task.opcode != "DamagePerformFinish"
                or effect.payload.get(flag) is not True
            )
            for flag in ("SkipDeathSettlement", "IsFakeAvatarAttack")
            if flag in source_fields
        )
    ):
        raise _Blocked(
            "task_graph_process_only_settlement_barrier_effect_contract_invalid"
        )
    return effect


def _random_config_control_references_are_source_owned(
    task: _FormalTask,
    references: Sequence[TaskGraphDefinitionReferenceIR],
    indexes: _DefinitionIndexes,
) -> bool:
    """A generic lowering control-effect is evidence, not a second effect to run."""
    if not references:
        return not task.effect_id
    if (
        not task.effect_id
        or len(references) != 1
        or references[0].reference_kind != "effect"
        or references[0].definition_id != task.effect_id
    ):
        return False
    matches = indexes.effects.get(task.effect_id, ())
    if len(matches) != 1 or type(matches[0]) is not EffectIR:
        return False
    effect = matches[0]
    if effect.opcode != "RandomConfig":
        return False
    # Formal topology owns these two legacy fields. Compare every remaining
    # source field; do not promote/drop the EffectIR or its deferred reference.
    sources = tuple(
        replace(source, evidence={
            key: value for key, value in source.evidence.items()
            if key not in {"parent_task_id", "child_task_count"}
        })
        for source in (effect.source, task.source)
    )
    return sources[0] == sources[1]


def _references(
    task: _FormalTask,
    control: CharacterControlFlowNodeIR | None,
    node_id: str,
    source: IRSource,
    indexes: _DefinitionIndexes,
    template_refs: Mapping[str, tuple[ControlFlowTemplateReferenceIR, ...]],
) -> tuple[TaskGraphDefinitionReferenceIR, ...]:
    if (task.opcode == "Remodifier" and control is not None
            and any(field.field_name == "PredicateFilter" for field in control.field_responsibilities)):
        conditions = indexes.conditions.get(task.condition_id, ())
        if not task.condition_id:
            raise _Blocked("task_graph_remodifier_predicate_definition_missing")
        if len(conditions) == 1 and (
            conditions[0].source.source_path != task.source.source_path
            or conditions[0].source.evidence.get("json_path")
            != str(task.source.evidence.get("json_path") or "") + ".PredicateFilter"
        ):
            raise _Blocked("task_graph_remodifier_predicate_source_mismatch")
    definitions: tuple[
        tuple[str, str, Mapping[str, tuple[Any, ...]], str], ...
    ] = (
        ("condition", task.condition_id, indexes.conditions, "condition_evaluation"),
        ("target", task.target_expression_id, indexes.targets, "target_resolution"),
        ("effect", task.effect_id, indexes.effects, "event_effect_execution"),
        (
            "ability",
            task.ability_definition_id,
            indexes.abilities,
            "ability_graph_resolution",
        ),
    )
    if _is_wait_anim_state_process_only_presentation_shape(control, task):
        _wait_anim_state_process_only_effect(task, indexes)
    if _is_process_only_settlement_barrier_shape(control, task):
        _process_only_settlement_barrier_effect(task, indexes)
    if task.opcode == "Retarget" and task.execution_mode == "process_only":
        _wait_anim_state_process_only_effect(task, indexes)
    if _is_single_projectile_impact_shape(control, task):
        effects = indexes.effects.get(task.effect_id, ())
        standard = effects[0].payload.get("standard") if len(effects) == 1 else None
        if (len(effects) != 1 or effects[0].source != task.source
                or effects[0].coverage_status != "executable"
                or not single_projectile_impact_contract_admitted(standard)):
            raise _Blocked("task_graph_projectile_impact_effect_contract_invalid")
    if _is_death_settlement_barrier_shape(control, task):
        effects = indexes.effects.get(task.effect_id, ())
        sources = tuple(replace(item, evidence={key: value for key, value in item.evidence.items()
                                               if key not in {"parent_task_id", "child_task_count"}})
                        for item in ((effects[0].source, task.source) if len(effects) == 1 else ()))
        if (len(effects) != 1 or sources[0] != sources[1]
                or effects[0].coverage_status != "executable"
                or effects[0].payload.get("standard") != {
                    "operation": "verify_death_settlement", "source_shape_admitted": True,
                }):
            raise _Blocked("task_graph_death_settlement_effect_contract_invalid")
    result: list[TaskGraphDefinitionReferenceIR] = []
    for kind, definition_id, values, default_owner in definitions:
        if not definition_id:
            continue
        matches = values.get(definition_id, ())
        if len(matches) != 1:
            raise _Blocked(f"task_graph_definition_{'missing' if not matches else 'ambiguous'}:{kind}:{definition_id}")
        if kind == "ability" and type(matches[0]) is not (
            AbilityPhaseIR
            if task.ability_definition_kind == "ability_phase"
            else StandaloneAbilityGraphIR
            if task.ability_definition_kind == "standalone_ability"
            else object
        ):
            raise _Blocked(
                f"task_graph_ability_definition_kind_mismatch:{definition_id}"
            )
        coverage = getattr(matches[0], "coverage_status", "blocked")
        status = "resolved" if coverage in {"executable", "lowered"} else "deferred"
        owner = _reference_owner(control, cast(Any, kind), default_owner)
        reason = "" if status == "resolved" else f"task_graph_definition_not_admitted:{kind}:{coverage}"
        result.append(TaskGraphDefinitionReferenceIR(
            task_graph_reference_id(node_id, cast(Any, kind), definition_id),
            node_id,
            cast(Any, kind),
            definition_id,
            "",
            cast(Any, status),
            owner,
            source,
            reason,
        ))
    if control is not None and control.control_role == "parallel_templates":
        refs = tuple(template_refs.get(control.node_id, ()))
        if not refs or any(ref.coverage_status != "lowered" for ref in refs):
            raise _Blocked(f"task_graph_template_reference_not_resolved:{control.node_id}")
        for ref in refs:
            result.append(TaskGraphDefinitionReferenceIR(
                task_graph_reference_id(node_id, "template", ref.resolved_template_id),
                node_id,
                "template",
                ref.resolved_template_id,
                ref.reference_id,
                "resolved",
                "task_graph_execution",
                ref.source,
                "",
            ))
    if control is not None and control.control_role == "template_include":
        refs = tuple(template_refs.get(control.node_id, ()))
        if len(refs) != 1 or refs[0].coverage_status != "lowered":
            raise _Blocked(f"task_graph_template_reference_not_resolved:{control.node_id}")
        ref = refs[0]
        status = "deferred" if ref.reference_kind == "parallel_local" else "resolved"
        result.append(TaskGraphDefinitionReferenceIR(
            task_graph_reference_id(node_id, "template", ref.resolved_template_id),
            node_id,
            "template",
            ref.resolved_template_id,
            ref.reference_id,
            status,
            "hit_random_sequence" if status == "deferred" else "task_graph_execution",
            ref.source,
            "task_graph_parallel_template_requires_hit_random_sequence" if status == "deferred" else "",
        ))
    if (
        control is not None
        and control.control_role == "ability_trigger"
        and task.execution_mode != "process_only"
        and not task.ability_definition_id
    ):
        raise _Blocked(f"task_graph_ability_reference_not_lowered:{control.node_id}")
    return tuple(result)


def _reference_owner(control: CharacterControlFlowNodeIR | None, kind: str, default: str) -> str:
    if control is not None and control.family == "TriggerSkipDeadHandler" and kind == "effect":
        return "unit_lifecycle"
    responsibilities = {
        "condition": "condition_contract",
        "target": "target_contract",
        "numeric": "numeric_contract",
        "ability": "ability_source_contract",
        "effect": "downstream_gameplay",
    }
    expected = responsibilities.get(kind)
    if control is not None and expected:
        owners = sorted({_owner_domain(item.owner_stage) for item in control.field_responsibilities if item.responsibility == expected})
        if len(owners) == 1:
            return owners[0]
    return default


def _is_single_projectile_impact_shape(
    control: CharacterControlFlowNodeIR | None, task: _FormalTask,
) -> bool:
    return (
        control is not None and control.family == task.opcode == task.family
        and task.family in {"FireProjectile", "NewFireProjectile"}
        and control.control_role == "projectile_sequence"
        and task.execution_mode == "runtime_effect" and task.coverage_status == "executable"
    )


def _node_status(
    control: CharacterControlFlowNodeIR | None,
    task: _FormalTask,
    references: Sequence[TaskGraphDefinitionReferenceIR] = (),
    *,
    closed_domains: frozenset[str] | set[str] = _ALREADY_CLOSED_DOMAINS,
) -> tuple[str, str, tuple[str, ...], str]:
    if (
        control is not None
        and control.family == task.opcode == task.family
        == "WaitSkillPerformAbilityFinish"
        and control.control_role == "presentation_barrier"
        and control.coverage_status != "blocked"
        and task.execution_mode == "process_only"
        and task.coverage_status == "audit_only"
        and task.effect_id
        and not task.condition_id
        and not task.target_expression_id
        and not task.ability_definition_id
        and not control.branches
        and not control.template_reference_ids
        and control.termination.termination_kind == "not_applicable"
        and control.termination.status == "not_applicable"
    ):
        return "leaf", "materialized", ("task_graph_execution",), ""
    if control is None:
        if task.family in {"WaitAnimState", "WaitTimelineFinish", "WaitSecond"} and task.execution_mode == "process_only":
            raise _Blocked("task_graph_wait_anim_state_source_contract_missing")
        return "leaf", "materialized", ("task_graph_execution",), ""
    if _is_single_projectile_impact_shape(control, task):
        return "sequence", "materialized", ("task_graph_execution",), ""
    if _is_wait_anim_state_process_only_presentation_shape(control, task):
        return "leaf", "materialized", ("task_graph_execution",), ""
    if _is_process_only_settlement_barrier_shape(control, task):
        return "leaf", "materialized", ("task_graph_execution",), ""
    if _is_death_settlement_barrier_shape(control, task):
        return "leaf", "materialized", ("task_graph_execution",), ""
    if (
        control.family == task.opcode == task.family == "CreateServant"
        and control.control_role == "servant_creation_continuation"
        and control.coverage_status != "blocked" and not control.blocked_reason
        and task.execution_mode == "runtime_effect" and task.coverage_status == "executable"
        and task.effect_id and not task.condition_id and not task.target_expression_id
        and not task.ability_definition_id and not control.template_reference_ids
        and len(control.branches) == 1 and control.branches[0].branch_kind == "servant_created"
        and control.termination.termination_kind == control.termination.status == "not_applicable"
        and control.downstream_stages == ("p9_s8b",)
        and len(references) == 1 and references[0].reference_kind == "effect"
        and references[0].definition_id == task.effect_id and references[0].resolution_status == "resolved"
    ):
        return "sequence", "materialized", ("task_graph_execution",), ""
    if control.family == task.opcode == task.family == "Retarget" and task.execution_mode == "process_only" and task.coverage_status == "audit_only":
        return "leaf", "materialized", ("task_graph_execution",), ""
    if (control.family == task.opcode == task.family and task.family in {"Retarget", "GLOABNLLLEL"}
            and control.control_role == "target_scope" and control.coverage_status != "blocked"
            and not control.blocked_reason and task.coverage_status == "executable"
            and task.target_expression_id
            and any(ref.reference_kind == "target" and ref.resolution_status == "resolved"
                    for ref in references)
            and {_owner_domain(stage) for stage in control.downstream_stages}
            == {"task_graph_execution", "hit_random_sequence"}):
        return "target_scope", "materialized", ("task_graph_execution",), ""
    if (control.family == task.opcode == task.family == "Remodifier"
            and control.control_role == "status_scope" and control.coverage_status != "blocked"
            and not control.blocked_reason and task.coverage_status == "executable"
            and task.target_expression_id
            and any(ref.reference_kind == "target" and ref.resolution_status == "resolved"
                    for ref in references)):
        return "target_scope", "materialized", ("task_graph_execution",), ""
    open_domains = tuple(sorted({
        _owner_domain(stage)
        for stage in control.downstream_stages
        if _owner_domain(stage) not in closed_domains
        and _owner_domain(stage) != "task_graph_execution"
    }))
    if open_domains:
        return (
            "deferred",
            "deferred",
            open_domains,
            f"task_graph_control_requires_domains:{','.join(open_domains)}",
        )
    if task.execution_mode == "process_only":
        return "leaf", "materialized", ("task_graph_execution",), ""
    node_kind = _NODE_KIND_BY_ROLE.get(control.control_role)
    if node_kind is None:
        raise _Blocked(f"task_graph_control_role_not_materializable:{control.control_role}")
    return node_kind, "materialized", ("task_graph_execution",), ""


def _owner_domain(stage: str) -> str:
    try:
        return _OWNER_DOMAIN_BY_STAGE[stage]
    except KeyError as exc:
        raise ValueError(f"task graph owner stage is not mapped to a domain:{stage}") from exc


def _formal_source(
    task: _FormalTask,
    digests: Mapping[str, str],
) -> IRSource:
    if not isinstance(task.source.evidence, Mapping):
        raise ValueError("formal task source evidence is invalid")
    path = task.source.evidence.get("json_path")
    digest = digests.get(task.source.source_path)
    if not isinstance(path, str) or not path.startswith("$"):
        raise ValueError("formal task source is outside the S8A source closure")
    if digest is None:
        raise ValueError("formal task source file fingerprint is missing")
    return IRSource(
        task.source.source_path,
        task.source.raw_type,
        task.source.raw_id,
        {
            **dict(task.source.evidence),
            "content_sha256": digest,
            "content_fingerprint_scope": "source_file",
        },
    )


def _source_digest_by_path(catalog: CharacterControlFlowContractCatalog) -> dict[str, str]:
    result: dict[str, set[str]] = defaultdict(set)
    for source in (
        *(item.source for item in catalog.nodes),
        *(item.source for item in catalog.template_definitions),
        *(item.source for item in catalog.template_references),
    ):
        digest = source.evidence.get("content_sha256")
        if isinstance(digest, str):
            result[source.source_path].add(digest)
    if any(len(values) != 1 for values in result.values()):
        raise ValueError("S8A source path has conflicting content fingerprints")
    return {path: next(iter(values)) for path, values in result.items()}


def _validate_source_snapshot(
    catalog: CharacterControlFlowContractCatalog,
    snapshot: CharacterAbilityRawSnapshot,
    *,
    require_complete: bool,
) -> None:
    if type(snapshot) is not CharacterAbilityRawSnapshot:
        raise TypeError("task graph materialization requires the exact raw snapshot")
    if (
        snapshot.snapshot_id != catalog.snapshot_id
        or snapshot.source_fingerprint != catalog.source_fingerprint
    ):
        raise ValueError("task graph materialization source snapshot is inconsistent")
    if require_complete and not snapshot.source_catalog_complete:
        raise ValueError("complete task graph catalog requires a complete source snapshot")


def _materialization_dispositions(
    base: tuple[TaskGraphSourceDispositionIR, ...],
    entries: tuple[TaskGraphEntryMaterializationIR, ...],
    graphs: tuple[TaskGraphIR, ...],
    admitted_insert_action_task_ids: frozenset[str] = frozenset(),
) -> tuple[TaskGraphSourceDispositionIR, ...]:
    if any(item.formal_materialization_ids for item in base):
        raise ValueError("task graph materialization base already contains formal links")
    graph_by_id = {item.graph_id: item for item in graphs}
    graph_node_by_id = {
        node.graph_node_id: (graph, node)
        for graph in graphs
        for node in graph.nodes
    }
    weighted_node_ids = {
        selection.graph_node_id
        for graph in graphs
        for selection in graph.weighted_selections
    }
    linked_by_materialization: dict[str, set[str]] = {}
    linked_nodes_by_record: dict[str, list[TaskGraphNodeIR]] = defaultdict(list)
    for entry in entries:
        if entry.status == "blocked":
            linked_by_materialization[entry.materialization_id] = set()
            continue
        graph = graph_by_id.get(entry.graph_id)
        if graph is None:
            raise ValueError("task graph materialization graph is missing")
        linked = {
            node.source_contract_node_id
            for node in graph.nodes
            if node.source_contract_node_id
        }
        for node in graph.nodes:
            if node.source_contract_node_id:
                linked_nodes_by_record[node.source_contract_node_id].append(node)
        linked.update(
            reference.definition_id
            for node in graph.nodes
            for reference in node.references
            if reference.reference_kind == "template"
        )
        linked.update(
            reference.source_contract_record_id
            for node in graph.nodes
            for reference in node.references
            if reference.source_contract_record_id
        )
        linked_by_materialization[entry.materialization_id] = linked
    materializations_by_record: dict[str, list[str]] = defaultdict(list)
    for materialization_id, linked in linked_by_materialization.items():
        for record_id in linked:
            materializations_by_record[record_id].append(materialization_id)
    result: list[TaskGraphSourceDispositionIR] = []

    def insert_action_abort_branch_materialized(node: TaskGraphNodeIR) -> bool:
        _graph, owner = graph_node_by_id.get(node.graph_node_id, (None, None))
        if owner is None:
            return False
        abort_branches = tuple(
            branch for branch in owner.branches if branch.branch_kind == "insert_abort"
        )
        if len(abort_branches) != 1 or not abort_branches[0].child_node_ids:
            return False
        return all(
            (child := graph_node_by_id.get(child_id)) is not None
            and child[1].materialization_status == "materialized"
            for child_id in abort_branches[0].child_node_ids
        )

    for item in base:
        materialization_ids = tuple(
            sorted(materializations_by_record.get(item.source_record_id, ()))
        )
        if not materialization_ids:
            result.append(item)
            continue
        if item.disposition == "blocked":
            raise ValueError("blocked task graph source cannot enter a formal graph")
        linked_nodes = tuple(linked_nodes_by_record.get(item.source_record_id, ()))
        retire_wait_anim_state_barrier = (
            item.source_kind == "control_node"
            and item.family in {
                "WaitAnimState",
                "WaitTimelineFinish",
                "WaitSecond",
                "WaitSkillPerformAbilityFinish",
            }
            and bool(linked_nodes)
            and all(
                node.source_family == item.family
                and node.opcode == item.family
                and node.node_kind == "leaf"
                and node.materialization_status == "materialized"
                and node.owner_domains == ("task_graph_execution",)
                and not node.branches
                and len(node.references) == 1
                and node.references[0].reference_kind == "effect"
                and node.references[0].resolution_status == "deferred"
                and node.references[0].blocked_reason
                == "task_graph_definition_not_admitted:effect:audit_only"
                and node.references[0].source == node.source
                and node.termination_kind == "not_applicable"
                and node.termination_status == "not_applicable"
                for node in linked_nodes
            )
        )
        retire_settlement_barrier = (
            item.source_kind == "control_node"
            and item.family in {"DamagePerformFinish", "SkillPerformFinish"}
            and bool(linked_nodes)
            and all(
                node.source_contract_node_id == item.source_record_id
                and node.source_family == item.family
                and node.opcode == item.family
                and node.node_kind == "leaf"
                and node.materialization_status == "materialized"
                and node.owner_domains == ("task_graph_execution",)
                and not node.branches
                and len(node.references) == 1
                and node.references[0].reference_kind == "effect"
                and node.references[0].resolution_status == "deferred"
                and node.references[0].blocked_reason
                == "task_graph_definition_not_admitted:effect:audit_only"
                and node.references[0].source == node.source
                and node.termination_kind == "not_applicable"
                and node.termination_status == "not_applicable"
                for node in linked_nodes
            )
        )
        retire_random_config_control = (
            item.source_kind == "control_node"
            and item.family == "RandomConfig"
            and bool(linked_nodes)
            and all(
                node.source_contract_node_id == item.source_record_id
                and node.source_family == "RandomConfig"
                and node.opcode == "RandomConfig"
                and node.node_kind == "branch"
                and node.materialization_status == "materialized"
                and node.owner_domains == ("task_graph_execution",)
                and node.graph_node_id in weighted_node_ids
                for node in linked_nodes
            )
        )
        retire_presentation_retarget = (
            item.source_kind == "control_node" and item.family == "Retarget"
            and bool(linked_nodes) and all(
                node.source_family == node.opcode == item.family and node.node_kind == "leaf"
                and node.materialization_status == "materialized"
                and node.owner_domains == ("task_graph_execution",)
                and len(node.references) == 1
                and node.references[0].reference_kind == "effect"
                and node.references[0].blocked_reason == "task_graph_definition_not_admitted:effect:audit_only"
                and node.references[0].source == node.source
                for node in linked_nodes
            )
        )
        retire_runtime_retarget = (
            item.source_kind == "control_node" and item.family in {"Retarget", "GLOABNLLLEL"}
            and bool(linked_nodes) and all(
                node.source_family == node.opcode == item.family and node.node_kind == "target_scope"
                and node.materialization_status == "materialized"
                and node.owner_domains == ("task_graph_execution",)
                and any(ref.reference_kind == "target" and ref.resolution_status == "resolved"
                        for ref in node.references)
                for node in linked_nodes
            )
        )
        retire_runtime_remodifier = (
            item.source_kind == "control_node" and item.family == "Remodifier"
            and bool(linked_nodes) and all(
                node.source_family == node.opcode == item.family and node.node_kind == "target_scope"
                and node.materialization_status == "materialized"
                and node.owner_domains == ("task_graph_execution",)
                and any(ref.reference_kind == "target" and ref.resolution_status == "resolved"
                        for ref in node.references)
                for node in linked_nodes
            )
        )
        retire_death_barrier = (
            item.source_kind == "control_node" and item.family == "TriggerSkipDeadHandler"
            and bool(linked_nodes) and all(
                node.source_family == node.opcode == item.family and node.node_kind == "leaf"
                and node.materialization_status == "materialized" and not node.branches
                and node.owner_domains == ("task_graph_execution",) and len(node.references) == 1
                and node.references[0].reference_kind == "effect"
                and node.references[0].resolution_status == "resolved"
                and node.references[0].owner_domain == "unit_lifecycle"
                and node.references[0].source == node.source
                for node in linked_nodes
            )
        )
        retire_single_projectile = (
            item.source_kind == "control_node" and item.family in {"FireProjectile", "NewFireProjectile"}
            and bool(linked_nodes) and all(
                node.source_family == node.opcode == item.family and node.node_kind == "sequence"
                and node.materialization_status == "materialized"
                and len(node.branches) == 1 and node.branches[0].branch_kind == "projectile_hit"
                and bool(node.branches[0].child_node_ids)
                and node.owner_domains == ("task_graph_execution",) and len(node.references) == 1
                and node.references[0].reference_kind == "effect"
                and node.references[0].resolution_status == "resolved"
                and node.references[0].source == node.source
                for node in linked_nodes
            )
        )
        retire_event_dispatch_control = (
            item.source_kind == "control_node"
            and bool(linked_nodes)
            and all(
                (owner_graph := graph_node_by_id.get(node.graph_node_id, (None, None))[0]) is not None
                and owner_graph.entry_kind == "status_callback"
                and node.materialization_status == "materialized"
                and node.owner_domains == ("task_graph_execution",)
                for node in linked_nodes
            )
        )
        retire_insert_action_queue = (
            item.source_kind == "control_node"
            and item.family == "TurnInsertAction"
            and bool(linked_nodes)
            and all(
                node.source_family == node.opcode == item.family
                and node.node_kind == "sequence"
                and node.materialization_status == "materialized"
                and node.owner_domains == ("task_graph_execution",)
                and node.formal_task_id in admitted_insert_action_task_ids
                and len(node.branches) == 1
                and node.branches[0].branch_kind == "insert_abort"
                and bool(node.branches[0].child_node_ids)
                and insert_action_abort_branch_materialized(node)
                for node in linked_nodes
            )
        )
        remaining_domains = tuple(
            domain
            for domain in item.owner_domains
            if domain != "task_graph_execution"
            and not (
                retire_wait_anim_state_barrier
                and domain == "hit_random_sequence"
            )
            and not (
                retire_settlement_barrier
                and domain == "damage_heal_shield"
            )
            and not (
                retire_random_config_control
                and domain == "hit_random_sequence"
            )
            and not (retire_death_barrier and domain == "unit_lifecycle")
            and not (retire_presentation_retarget and domain == "hit_random_sequence")
            and not (retire_runtime_retarget and domain == "hit_random_sequence")
            and not (retire_runtime_remodifier and domain == "status_lifecycle")
            and not (retire_single_projectile and domain == "hit_random_sequence")
            and not (retire_insert_action_queue and domain == "timeline_queue")
            and not (retire_event_dispatch_control and domain == "event_dispatch")
        )
        result.append(replace(
            item,
            disposition="deferred" if remaining_domains else "materialized",
            owner_domains=remaining_domains,
            formal_materialization_ids=materialization_ids,
        ))
    return tuple(result)


def _catalog(
    source: CharacterControlFlowContractCatalog,
    scope_mode: str,
    dispositions: tuple[TaskGraphSourceDispositionIR, ...],
    entries: tuple[TaskGraphEntryMaterializationIR, ...],
    graphs: tuple[TaskGraphIR, ...],
) -> TaskGraphCatalogIR:
    record_ids = tuple(sorted(item.source_record_id for item in dispositions))
    return TaskGraphCatalogIR(
        scope_mode=cast(Any, scope_mode),
        source_catalog_id=source.catalog_id,
        snapshot_id=source.snapshot_id,
        scope_catalog_id=source.scope_catalog_id,
        source_fingerprint=source.source_fingerprint,
        dependency_fingerprint=source.dependency_fingerprint,
        source_record_count=len(record_ids),
        source_record_fingerprint=task_graph_source_record_fingerprint(record_ids),
        source_dispositions=dispositions,
        entry_materializations=entries,
        graphs=graphs,
        selected_entry_ids=tuple(sorted(item.entry_id for item in entries)),
        source_ledger_complete=True,
    )
