from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal, cast

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
    StatusCallbackTaskIR,
    TargetExpressionIR,
)
from ..rules.task_graph import (
    EntryKind,
    TaskGraphBranchIR,
    TaskGraphCatalogIR,
    TaskGraphDefinitionReferenceIR,
    TaskGraphEntryMaterializationIR,
    TaskGraphIR,
    TaskGraphNodeIR,
    TaskGraphNumericDefinitionIR,
    TaskGraphSourceDispositionIR,
    task_graph_branch_id,
    task_graph_entry_id,
    task_graph_id,
    task_graph_materialization_id,
    task_graph_node_id,
    task_graph_numeric_id,
    task_graph_reference_id,
    task_graph_source_occurrence_id,
    task_graph_source_record_fingerprint,
)
from .character_ability_scope import CharacterAbilityRawSnapshot


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
    opcode: str
    family: str
    parent_task_id: str
    child_task_ids: tuple[str, ...]
    success_task_ids: tuple[str, ...]
    failed_task_ids: tuple[str, ...]
    condition_id: str
    target_expression_id: str
    effect_id: str
    ability_definition_id: str
    ability_definition_kind: str
    execution_mode: str
    coverage_status: str
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
    digest_by_path: Mapping[str, str]
    control_by_location: Mapping[
        tuple[str, object, str], CharacterControlFlowNodeIR
    ]
    template_by_id: Mapping[str, ControlFlowTemplateDefinitionIR]
    template_refs_by_node: Mapping[str, tuple[ControlFlowTemplateReferenceIR, ...]]
    definitions: _DefinitionIndexes


def build_complete_task_graph_catalog(
    source_catalog: CharacterControlFlowContractCatalog,
    source_snapshot: CharacterAbilityRawSnapshot,
) -> TaskGraphCatalogIR:
    if type(source_catalog) is not CharacterControlFlowContractCatalog:
        raise TypeError("task graph source catalog requires the exact S8A catalog")
    _validate_source_snapshot(source_catalog, source_snapshot, require_complete=True)
    if source_catalog.issues:
        raise ValueError("complete task graph catalog cannot admit unresolved source issues")
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
    {"action_root", "nested_only", "standalone_root"}
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
    phases = tuple(
        phase
        for phase in canonical.ability_phases
        if phase.invocation_role in _FORMAL_ABILITY_INVOCATION_ROLES
    )
    if not phases:
        raise ValueError("formal ability task graph phase selection is empty")
    if len({item.phase_id for item in phases}) != len(phases):
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
            if entry.status != "materialized" or graph is None:
                raise ValueError(
                    "formal ability catalog entry is not materializable:"
                    f"{entry.entry_id}:{entry.blocked_reason or 'graph_missing'}"
                )
            entries.append(entry)
            graphs.append(graph)
    formal_task_ids = {
        item.task_id
        for item in canonical.ability_tasks
        if item.phase_id in {phase.phase_id for phase in phases}
    }
    if selected_task_ids != formal_task_ids:
        raise ValueError("formal ability task graph phase denominator is incomplete")
    if len({item.entry_id for item in entries}) != len(entries):
        raise ValueError("formal ability task graph entries contain duplicate identities")
    dispositions = _materialization_dispositions(
        context.base.source_dispositions,
        tuple(entries),
        tuple(graphs),
    )
    return _catalog(
        source_catalog,
        "formal_catalog",
        dispositions,
        tuple(entries),
        tuple(graphs),
    )


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
    selected = {item.task_id for item in tasks}
    ordered = tuple(item for item in callbacks[0].task_ids if item in selected)
    if len(ordered) != len(tasks) or set(ordered) != selected:
        raise ValueError("status callback task ledger is incomplete")
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
    return replace(canonical, task_graph_catalog=catalog)


def merge_task_graph_slices(
    complete_catalog: TaskGraphCatalogIR,
    slices: Iterable[TaskGraphCatalogIR],
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
    family = task.source.evidence.get("source_opcode")
    if task.linked_ability_phase_id and task.linked_standalone_graph_id:
        raise ValueError("ability task call target is ambiguous")
    return _FormalTask(
        task.task_id,
        task.opcode,
        family if isinstance(family, str) and family else task.opcode,
        task.parent_task_id,
        tuple(task.child_task_ids),
        tuple(task.success_task_ids),
        tuple(task.failed_task_ids),
        task.condition_id,
        "",
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
    )


def _status_task(task: StatusCallbackTaskIR) -> _FormalTask:
    if type(task) is not StatusCallbackTaskIR:
        raise TypeError("status graph requires exact StatusCallbackTaskIR values")
    family = task.source.evidence.get("raw_opcode")
    return _FormalTask(
        task.task_id,
        task.opcode,
        family if isinstance(family, str) and family else task.opcode,
        task.parent_task_id,
        tuple(task.child_task_ids),
        tuple(task.success_task_ids),
        tuple(task.failed_task_ids),
        task.condition_id,
        task.target_expression_id,
        task.effect_id,
        "",
        "",
        "runtime_effect",
        task.coverage_status,
        task.source,
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
) -> TaskGraphIR:
    task_by_id = {item.task_id: item for item in tasks}
    if set(ordered_task_ids) != set(task_by_id):
        raise _Blocked("formal_entry_task_set_mismatch")
    _validate_formal_topology(task_by_id, ordered_task_ids)
    node_ids = {
        task_id: task_graph_node_id(graph_id, task_id, occurrences[task_id])
        for task_id in task_by_id
    }
    roots = tuple(node_ids[task_id] for task_id in ordered_task_ids if not task_by_id[task_id].parent_task_id)
    if not roots:
        raise _Blocked("formal_entry_root_missing")
    numeric: list[TaskGraphNumericDefinitionIR] = []
    nodes: list[TaskGraphNodeIR] = []
    for task in tasks:
        control = controls.get(task.task_id)
        if control is not None and control.coverage_status == "blocked":
            raise _Blocked(
                f"task_graph_source_contract_blocked:{control.node_id}:"
                f"{control.blocked_reason}"
            )
        branches = _branches(
            task,
            control,
            refs_by_node,
            template_by_id,
            task_by_id,
            node_ids,
        )
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
        node_kind, status, owner_domains, reason = _node_status(control, task)
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
        ))
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
    )


def _validate_formal_topology(
    task_by_id: Mapping[str, _FormalTask],
    ordered_task_ids: tuple[str, ...],
) -> None:
    roots = tuple(task_id for task_id in ordered_task_ids if not task_by_id[task_id].parent_task_id)
    if not roots:
        raise _Blocked("formal_entry_root_missing")
    parent_counts = {task_id: 0 for task_id in task_by_id}
    adjacency: dict[str, tuple[str, ...]] = {}
    for task in task_by_id.values():
        children = task.child_task_ids
        if len(children) != len(set(children)) or task.task_id in children:
            raise _Blocked(f"formal_child_identity_invalid:{task.task_id}")
        if set(children) - set(task_by_id):
            raise _Blocked(f"formal_child_missing:{task.task_id}")
        adjacency[task.task_id] = children
        for child_id in children:
            if task_by_id[child_id].parent_task_id != task.task_id:
                raise _Blocked(f"formal_parent_child_mismatch:{task.task_id}")
            parent_counts[child_id] += 1
    root_set = set(roots)
    if any(count != (0 if task_id in root_set else 1) for task_id, count in parent_counts.items()):
        raise _Blocked("formal_parent_ownership_ambiguous")
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


def _branches(
    task: _FormalTask,
    control: CharacterControlFlowNodeIR | None,
    refs_by_node: Mapping[str, list[ControlFlowTemplateReferenceIR]],
    templates: Mapping[str, ControlFlowTemplateDefinitionIR],
    task_by_id: Mapping[str, _FormalTask],
    node_ids: Mapping[str, str],
) -> tuple[TaskGraphBranchIR, ...]:
    if control is None:
        if task.child_task_ids:
            raise _Blocked(f"formal_topology_missing_source_contract:{task.task_id}")
        return ()
    remaining_children = [task_by_id[item] for item in task.child_task_ids]

    def take_child(source: IRSource, family: str) -> _FormalTask:
        path = str(source.evidence["json_path"]).removesuffix(".$type")
        for index, candidate in enumerate(remaining_children):
            candidate_path = candidate.source.evidence.get("json_path")
            if (
                candidate.source.source_path == source.source_path
                and candidate_path == path
                and candidate.family == family
            ):
                return remaining_children.pop(index)
        raise _Blocked(
            f"formal_branch_child_missing:{source.source_path}:{path}:{family}"
        )

    rows: list[tuple[str, str, tuple[_FormalTask, ...], IRSource]] = []
    for branch in control.branches:
        children = tuple(take_child(item.source, item.family) for item in branch.children)
        rows.append((branch.branch_kind, branch.label, children, branch.source))
    if control.control_role == "template_include":
        references = tuple(refs_by_node.get(control.node_id, ()))
        if len(references) != 1 or references[0].coverage_status != "lowered":
            raise _Blocked(f"formal_template_reference_not_resolved:{control.node_id}")
        template = templates.get(references[0].resolved_template_id)
        if template is None:
            raise _Blocked(f"formal_template_definition_missing:{references[0].resolved_template_id}")
        children = tuple(take_child(item.source, item.family) for item in template.children)
        rows.append(("template_body", template.template_id, children, template.source))
    if remaining_children:
        raise _Blocked(f"formal_branch_child_unclaimed:{task.task_id}")
    flattened = tuple(item.task_id for _kind, _label, children, _source in rows for item in children)
    if flattened != task.child_task_ids:
        raise _Blocked(f"formal_child_topology_mismatch:{task.task_id}")
    success = tuple(item.task_id for kind, _label, children, _source in rows if kind == "success" for item in children)
    failed = tuple(item.task_id for kind, _label, children, _source in rows if kind == "failed" for item in children)
    if success != task.success_task_ids or failed != task.failed_task_ids:
        raise _Blocked(f"formal_branch_topology_mismatch:{task.task_id}")
    for child_id in task.child_task_ids:
        child = task_by_id.get(child_id)
        if child is None or child.parent_task_id != task.task_id:
            raise _Blocked(f"formal_parent_child_mismatch:{task.task_id}")
    result: list[TaskGraphBranchIR] = []
    for ordinal, (kind, label, children, source) in enumerate(rows):
        child_ids = tuple(node_ids[item.task_id] for item in children)
        result.append(TaskGraphBranchIR(
            task_graph_branch_id(node_ids[task.task_id], kind, ordinal, label, child_ids),
            node_ids[task.task_id],
            kind,
            ordinal,
            label,
            child_ids,
            source,
        ))
    return tuple(result)


def _references(
    task: _FormalTask,
    control: CharacterControlFlowNodeIR | None,
    node_id: str,
    source: IRSource,
    indexes: _DefinitionIndexes,
    template_refs: Mapping[str, tuple[ControlFlowTemplateReferenceIR, ...]],
) -> tuple[TaskGraphDefinitionReferenceIR, ...]:
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


def _node_status(
    control: CharacterControlFlowNodeIR | None,
    task: _FormalTask,
) -> tuple[str, str, tuple[str, ...], str]:
    if control is None:
        return "leaf", "materialized", ("task_graph_execution",), ""
    open_domains = tuple(sorted({
        _owner_domain(stage)
        for stage in control.downstream_stages
        if _owner_domain(stage) not in _ALREADY_CLOSED_DOMAINS
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
) -> tuple[TaskGraphSourceDispositionIR, ...]:
    if any(item.formal_materialization_ids for item in base):
        raise ValueError("task graph materialization base already contains formal links")
    graph_by_id = {item.graph_id: item for item in graphs}
    linked_by_materialization: dict[str, set[str]] = {}
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
    for item in base:
        materialization_ids = tuple(
            sorted(materializations_by_record.get(item.source_record_id, ()))
        )
        if not materialization_ids:
            result.append(item)
            continue
        if item.disposition == "blocked":
            raise ValueError("blocked task graph source cannot enter a formal graph")
        remaining_domains = tuple(
            domain for domain in item.owner_domains if domain != "task_graph_execution"
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
