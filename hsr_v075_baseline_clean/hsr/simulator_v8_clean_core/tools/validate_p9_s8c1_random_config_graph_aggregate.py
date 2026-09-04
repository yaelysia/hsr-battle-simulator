from __future__ import annotations

import argparse
import gc
import json
import resource
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, cast

from ..ir_types import IRSource
from ..rules.ir import CanonicalIR
from ..rules.task_graph import (
    EntryKind,
    TaskGraphBranchIR,
    TaskGraphCatalogIR,
    TaskGraphIR,
    TaskGraphNodeIR,
    TaskGraphWeightedSelectionIR,
    task_graph_branch_id,
    task_graph_entry_id,
    task_graph_id,
    task_graph_node_id,
    task_graph_numeric_id,
    task_graph_source_occurrence_id,
    task_graph_weighted_choice_id,
    task_graph_weighted_selection_id,
)
from ..tbgd.character_ability_scope import CharacterAbilityRawSnapshot
from ..tbgd.character_control_flow_contracts import _at_path
from ..tbgd.expression_lowering import lower_numeric_expression
from ..tbgd.lowering import (
    TBGDLowering,
    _assign_character_ability_invocation_roles,
    _link_status_trigger_ability_graphs,
    _link_trigger_ability_graphs,
    _lower_queue_resolutions,
    build_character_action_definition_ir,
)
from ..tbgd.task_graph_materializer import (
    _materialize_weighted_selection,
    build_complete_task_graph_catalog,
    materialize_ability_phase_task_graph,
    materialize_character_runtime_task_graph_catalog,
    materialize_status_callback_task_graph,
)


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TBGD = ROOT / "turnbasedgamedata-main"
_FAST_HARD_SECONDS = 30.0
_DIRECT_HARD_SECONDS = 120.0
_CATALOG_HARD_SECONDS = 180.0
_FAST_RSS_LIMIT_KIB = 256 * 1024
_DIRECT_RSS_LIMIT_KIB = 1024 * 1024
_CATALOG_RSS_LIMIT_KIB = 1280 * 1024
_FORMAL_ROLES = frozenset({"action_root", "nested_only", "standalone_root"})
_ACTION_BINDING_KINDS = frozenset({"entry", "phase", "passive"})
_RANDOM_FAMILY = "RandomConfig"
_SourceKey = tuple[str, str, str, str]


@dataclass(frozen=True, order=True)
class _FormalPositionKey:
    producer_kind: str
    producer_instance_id: str
    entry_kind: str
    owner_id: str
    callback_kind: str
    formal_task_id: str
    source_path: str
    json_path: str
    family: str
    content_sha256: str


@dataclass(frozen=True)
class _FixtureSnapshot:
    source_bytes: Mapping[str, bytes]


@dataclass(frozen=True)
class _DefinitionRef:
    action_id: str
    level: int = 0


@dataclass(frozen=True)
class _ActionBatch:
    definitions: tuple[Any, ...]
    view: CanonicalIR
    producer_by_owner: Mapping[str, str]


@dataclass
class _StatusBundle:
    view: CanonicalIR
    status_tasks: tuple[Any, ...]
    queue_intents: tuple[Any, ...]
    trigger_names: frozenset[str]


@dataclass
class _RealContext:
    lowering: TBGDLowering
    source_graph: Any
    snapshot: CharacterAbilityRawSnapshot
    scope: Any
    source_catalog: Any
    formal_context: Any
    status_bundle: _StatusBundle
    random_definition_sources: dict[str, frozenset[_SourceKey]]
    definition_by_id: dict[str, Any]
    action_ids_by_random_definition: dict[str, frozenset[str]]
    queue_random_definition_ids: frozenset[str]
    trigger_random_definition_ids: frozenset[str]
    digest_by_path: Mapping[str, str]


def _expect_rejected(action: Callable[[], object], subject: str) -> None:
    try:
        action()
    except (AssertionError, KeyError, IndexError, TypeError, ValueError, RuntimeError):
        return
    raise AssertionError(f"{subject} was accepted")


def _short_type(value: object) -> str:
    return str(value or "").rsplit(".", 1)[-1]


def _source_key(source: IRSource, family: str) -> _SourceKey:
    path = source.evidence.get("json_path")
    digest = source.evidence.get("content_sha256")
    if not isinstance(path, str) or not path.startswith("$"):
        raise AssertionError("source JSON path is invalid")
    if not isinstance(digest, str) or len(digest) != 64:
        raise AssertionError("source content fingerprint is invalid")
    return source.source_path, path, family, digest


def _task_key(
    task: Any,
    field: str,
    digests: Mapping[str, str] | None = None,
) -> _SourceKey:
    family = task.source.evidence.get(field)
    if not isinstance(family, str) or not family:
        family = task.opcode
    digest = task.source.evidence.get("content_sha256")
    if (not isinstance(digest, str) or len(digest) != 64) and digests is not None:
        digest = digests.get(task.source.source_path)
    if not isinstance(digest, str) or len(digest) != 64:
        raise AssertionError("formal task content fingerprint is missing")
    path = task.source.evidence.get("json_path")
    if not isinstance(path, str) or not path.startswith("$"):
        raise AssertionError("formal task source path is invalid")
    return task.source.source_path, path, family, digest


def _key_text(key: _SourceKey) -> str:
    return json.dumps(key, ensure_ascii=True, separators=(",", ":"))


def _denominator_fingerprint(keys: Iterable[_SourceKey]) -> str:
    payload = json.dumps(
        sorted(_key_text(key) for key in keys),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _formal_position_text(position: _FormalPositionKey) -> str:
    return json.dumps(
        [
            position.producer_kind,
            position.producer_instance_id,
            position.entry_kind,
            position.owner_id,
            position.callback_kind,
            position.formal_task_id,
            position.source_path,
            position.json_path,
            position.family,
            position.content_sha256,
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    )


def _formal_position_fingerprint(positions: Iterable[_FormalPositionKey]) -> str:
    payload = json.dumps(
        sorted(_formal_position_text(item) for item in positions),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _formal_position(
    *,
    producer_kind: str,
    producer_instance_id: str,
    entry_kind: str,
    owner_id: str,
    callback_kind: str,
    formal_task_id: str,
    source_key: _SourceKey,
) -> _FormalPositionKey:
    if (
        not producer_kind
        or not producer_instance_id
        or entry_kind not in {"ability_phase_callback", "status_callback"}
        or not owner_id
        or not callback_kind
        or not formal_task_id
    ):
        raise ValueError("formal position identity is incomplete")
    return _FormalPositionKey(
        producer_kind,
        producer_instance_id,
        entry_kind,
        owner_id,
        callback_kind,
        formal_task_id,
        *source_key,
    )


def _audit_exact_positions(
    expected: set[_FormalPositionKey],
    actual: set[_FormalPositionKey],
) -> None:
    if expected != actual:
        raise ValueError(
            "formal position denominator is incomplete:"
            f"missing={len(expected - actual)} extra={len(actual - expected)}"
        )


def _audit_classification(
    denominator: set[_SourceKey],
    formal_bound: set[_SourceKey],
    no_formal_producer: set[_SourceKey],
) -> None:
    if formal_bound & no_formal_producer:
        raise ValueError("RandomConfig producer classification overlaps")
    if formal_bound | no_formal_producer != denominator:
        raise ValueError("RandomConfig producer classification is incomplete")


def _dedupe(values: Iterable[Any], field: str) -> tuple[Any, ...]:
    result: dict[str, Any] = {}
    for value in values:
        identity = getattr(value, field)
        previous = result.get(identity)
        if previous is not None and previous != value:
            raise ValueError(f"focused definition conflict:{field}:{identity}")
        result[identity] = value
    return tuple(result[key] for key in sorted(result))


def _fixture(
    entry_kind: EntryKind,
) -> tuple[TaskGraphIR, TaskGraphWeightedSelectionIR]:
    raw_parent = {
        "$type": "RandomConfig",
        "OddsList": [2, 3],
        "ConfigList": [{}, {}],
    }
    payload = json.dumps(
        {"Task": raw_parent}, sort_keys=True, separators=(",", ":")
    ).encode()
    source = IRSource(
        "validation_fixture/p9_s8c1.json",
        "RandomConfig",
        "fixture_random_config",
        {
            "json_path": "$.Task",
            "content_sha256": sha256(payload).hexdigest(),
            "source_opcode": "RandomConfig",
            "task_path": "fixture[0]",
        },
    )
    occurrence_id = task_graph_source_occurrence_id(source, _RANDOM_FAMILY)
    owner_id = "fixture:status" if entry_kind == "status_callback" else "fixture:phase"
    callback_kind = "OnBeforeBeingHit" if entry_kind == "status_callback" else "OnStart"
    entry_id = task_graph_entry_id(entry_kind, owner_id, callback_kind)
    graph_id = task_graph_id(
        "fixture:source_catalog", entry_id, source.evidence["content_sha256"]
    )
    node_id = task_graph_node_id(graph_id, "fixture:task", occurrence_id)
    branches = tuple(
        TaskGraphBranchIR(
            branch_id=task_graph_branch_id(
                node_id, "config", ordinal, f"choice_{ordinal}", ()
            ),
            graph_node_id=node_id,
            branch_kind="config",
            ordinal=ordinal,
            label=f"choice_{ordinal}",
            child_node_ids=(),
            source=source,
        )
        for ordinal in range(2)
    )
    selection = _materialize_weighted_selection(
        cast(Any, _FixtureSnapshot({source.source_path: payload})),
        node_id,
        source,
        occurrence_id,
        branches,
    )
    node = TaskGraphNodeIR(
        graph_node_id=node_id,
        graph_id=graph_id,
        source_occurrence_id=occurrence_id,
        source_contract_node_id="fixture:control",
        formal_task_id="fixture:task",
        opcode="RandomConfig",
        source_family="RandomConfig",
        node_kind="deferred",
        branches=branches,
        references=(),
        termination_kind="not_applicable",
        termination_status="not_applicable",
        termination_numeric_definition_id="",
        materialization_status="deferred",
        owner_domains=("hit_random_sequence",),
        source=source,
        status_reason="fixture_random_config_deferred",
    )
    graph = TaskGraphIR(
        graph_id=graph_id,
        entry_id=entry_id,
        entry_kind=entry_kind,
        owner_id=owner_id,
        callback_kind=callback_kind,
        root_node_ids=(node_id,),
        nodes=(node,),
        numeric_definitions=(),
        source_catalog_id="fixture:source_catalog",
        source_fingerprint=source.evidence["content_sha256"],
        source=source,
        coverage_status="lowered_with_obligation",
        weighted_selections=(selection,),
    )
    return graph, selection


def _audit_graph_selection_structure(graph: TaskGraphIR) -> None:
    nodes = {node.graph_node_id: node for node in graph.nodes}
    if len(nodes) != len(graph.nodes):
        raise ValueError("graph contains duplicate node identities")
    if len({item.selection_id for item in graph.weighted_selections}) != len(
        graph.weighted_selections
    ):
        raise ValueError("graph contains duplicate weighted-selection identities")
    by_node: dict[str, list[TaskGraphWeightedSelectionIR]] = defaultdict(list)
    for selection in graph.weighted_selections:
        if selection.graph_node_id not in nodes:
            raise ValueError("graph contains orphan weighted selection")
        by_node[selection.graph_node_id].append(selection)
    for node in graph.nodes:
        selections = by_node.get(node.graph_node_id, ())
        if node.source_family == _RANDOM_FAMILY:
            if len(selections) != 1:
                raise ValueError("RandomConfig node does not have exactly one selection")
        elif selections:
            raise ValueError("non-RandomConfig node carries weighted selection")


def _audit_parent_fingerprint_and_ordinals(
    node: TaskGraphNodeIR,
    selection: TaskGraphWeightedSelectionIR,
) -> None:
    digest = node.source.evidence.get("content_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("parent source fingerprint is invalid")
    if tuple(item.ordinal for item in selection.choices) != tuple(
        range(len(selection.choices))
    ):
        raise ValueError("weighted choice ordinals are not contiguous")
    for choice in selection.choices:
        if choice.source.evidence.get("content_sha256") != digest:
            raise ValueError("weighted choice source fingerprint diverged")
        if choice.source.evidence.get("json_path") != (
            f"{node.source.evidence.get('json_path')}.OddsList[{choice.ordinal}]"
        ):
            raise ValueError("weighted choice OddsList ordinal path diverged")


def _fast_missing_instance() -> None:
    source_key: _SourceKey = (
        "validation_fixture/shared.json",
        "$.Task",
        _RANDOM_FAMILY,
        "0" * 64,
    )
    first = _formal_position(
        producer_kind="action_definition",
        producer_instance_id="definition:1",
        entry_kind="ability_phase_callback",
        owner_id="phase:1",
        callback_kind="OnStart",
        formal_task_id="task:1",
        source_key=source_key,
    )
    second = _formal_position(
        producer_kind="action_definition",
        producer_instance_id="definition:2",
        entry_kind="ability_phase_callback",
        owner_id="phase:2",
        callback_kind="OnStart",
        formal_task_id="task:2",
        source_key=source_key,
    )
    _audit_exact_positions({first, second}, {first})


def _fast_source_key_collapse() -> None:
    source_key: _SourceKey = (
        "validation_fixture/shared.json",
        "$.Task",
        _RANDOM_FAMILY,
        "1" * 64,
    )
    expected = {
        _formal_position(
            producer_kind="action_definition",
            producer_instance_id=f"definition:{index}",
            entry_kind="ability_phase_callback",
            owner_id=f"phase:{index}",
            callback_kind="OnStart",
            formal_task_id=f"task:{index}",
            source_key=source_key,
        )
        for index in (1, 2)
    }
    collapsed_actual = {min(expected)}
    if len({item.source_path + item.json_path for item in expected}) != 1:
        raise AssertionError("source-collapse fixture is invalid")
    _audit_exact_positions(expected, collapsed_actual)


def _fast_fingerprint_tamper() -> None:
    graph, selection = _fixture("status_callback")
    node = graph.nodes[0]
    evidence = dict(node.source.evidence)
    evidence["content_sha256"] = "f" * 64
    bad_node = replace(
        node,
        source=IRSource(
            node.source.source_path,
            node.source.raw_type,
            node.source.raw_id,
            evidence,
        ),
    )
    _audit_parent_fingerprint_and_ordinals(bad_node, selection)


def _fast_ordinal_tamper() -> None:
    graph, selection = _fixture("status_callback")
    bad_choice = replace(selection.choices[0], ordinal=1)
    bad_selection = replace(
        selection,
        choices=(bad_choice, *selection.choices[1:]),
    )
    _audit_parent_fingerprint_and_ordinals(graph.nodes[0], bad_selection)


def _run_fast() -> dict[str, Any]:
    started = time.perf_counter()
    ability_graph, _ = _fixture("ability_phase_callback")
    status_graph, status_selection = _fixture("status_callback")
    _audit_graph_selection_structure(ability_graph)
    _audit_graph_selection_structure(status_graph)
    _expect_rejected(
        _fast_missing_instance,
        "missing formal producer instance",
    )
    _expect_rejected(
        _fast_source_key_collapse,
        "source-key collapsed producer multiplicity",
    )
    source_key: _SourceKey = (
        "validation_fixture/overlap.json",
        "$.Task",
        _RANDOM_FAMILY,
        "2" * 64,
    )
    _expect_rejected(
        lambda: _audit_classification({source_key}, {source_key}, {source_key}),
        "overlapping formal/no-producer classification",
    )
    _expect_rejected(
        lambda: _audit_graph_selection_structure(
            replace(ability_graph, weighted_selections=(status_selection,))
        ),
        "orphan weighted selection",
    )
    _expect_rejected(
        lambda: _audit_graph_selection_structure(
            replace(
                status_graph,
                weighted_selections=(status_selection, status_selection),
            )
        ),
        "duplicate weighted selection",
    )
    _expect_rejected(_fast_fingerprint_tamper, "source fingerprint tamper")
    _expect_rejected(_fast_ordinal_tamper, "OddsList ordinal tamper")
    elapsed = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    predicates = {
        "missing_producer_multiplicity_fails_closed": True,
        "source_key_collapse_fails_closed": True,
        "classification_overlap_fails_closed": True,
        "orphan_selection_fails_closed": True,
        "duplicate_selection_fails_closed": True,
        "source_fingerprint_tamper_fails_closed": True,
        "odds_ordinal_tamper_fails_closed": True,
        "runtime_behavior_changed": False,
    }
    return {
        "ok": (
            all(
                value is True
                for key, value in predicates.items()
                if key != "runtime_behavior_changed"
            )
            and predicates["runtime_behavior_changed"] is False
            and elapsed <= _FAST_HARD_SECONDS
            and peak <= _FAST_RSS_LIMIT_KIB
        ),
        "mode": "fast",
        "cases": 7,
        "predicates": predicates,
        "resource": {"wall_seconds": round(elapsed, 6), "peak_rss_kib": peak},
    }


def _source_bytes(
    root: Path,
    snapshot: CharacterAbilityRawSnapshot,
    source_path: str,
) -> bytes:
    value = snapshot.source_bytes.get(source_path)
    return value if value is not None else (root / source_path).read_bytes()


def _verify_selection(
    root: Path,
    snapshot: CharacterAbilityRawSnapshot,
    graph: TaskGraphIR,
    node: TaskGraphNodeIR,
    selection: TaskGraphWeightedSelectionIR,
) -> dict[str, Any]:
    if (
        node.source_family != _RANDOM_FAMILY
        or selection.graph_node_id != node.graph_node_id
        or selection.parent_source_occurrence_id != node.source_occurrence_id
    ):
        raise AssertionError("weighted selection parent identity diverged")
    if selection.selection_id != task_graph_weighted_selection_id(
        node.graph_node_id, node.source_occurrence_id
    ):
        raise AssertionError("weighted selection identity diverged")
    raw_bytes = _source_bytes(root, snapshot, node.source.source_path)
    digest = sha256(raw_bytes).hexdigest()
    if digest != node.source.evidence.get("content_sha256"):
        raise AssertionError("RandomConfig source bytes fingerprint mismatch")
    document = json.loads(raw_bytes)
    path = node.source.evidence.get("json_path")
    if not isinstance(document, Mapping) or not isinstance(path, str):
        raise AssertionError("RandomConfig source document/path is invalid")
    raw_parent = _at_path(document, path)
    odds = raw_parent.get("OddsList") if isinstance(raw_parent, Mapping) else None
    if (
        type(odds) is not list
        or len(odds) != len(node.branches)
        or len(odds) != len(selection.choices)
    ):
        raise AssertionError("RandomConfig denominator length is inconsistent")
    definitions = {
        item.definition_id: item for item in selection.numeric_definitions
    }
    if len(definitions) != len(selection.numeric_definitions):
        raise AssertionError("weighted numeric definitions contain duplicates")
    seen_choice_ids: set[str] = set()
    seen_weight_occurrences: set[str] = set()
    for index, (raw_weight, branch, choice) in enumerate(
        zip(odds, node.branches, selection.choices, strict=True)
    ):
        evidence = dict(node.source.evidence)
        evidence["json_path"] = f"{path}.OddsList[{index}]"
        child_source = IRSource(
            node.source.source_path,
            node.source.raw_type,
            node.source.raw_id,
            evidence,
        )
        occurrence_id = task_graph_source_occurrence_id(
            child_source, _RANDOM_FAMILY
        )
        expression = lower_numeric_expression(raw_weight)
        definition_id = task_graph_numeric_id(occurrence_id, expression)
        definition = definitions.get(definition_id)
        expected_choice_id = task_graph_weighted_choice_id(
            node.graph_node_id,
            index,
            branch.branch_id,
            definition_id,
        )
        if (
            choice.ordinal != index
            or choice.branch_id != branch.branch_id
            or choice.choice_id != expected_choice_id
            or choice.weight_definition_id != definition_id
            or choice.weight_source_occurrence_id != occurrence_id
            or choice.source != child_source
            or definition is None
            or definition.source_occurrence_id != occurrence_id
            or definition.expression != expression
            or definition.source != child_source
        ):
            raise AssertionError(
                f"RandomConfig branch/Odds/source closure failed:{index}"
            )
        if choice.choice_id in seen_choice_ids:
            raise AssertionError("weighted choice identity is duplicated")
        if occurrence_id in seen_weight_occurrences:
            raise AssertionError("weighted source occurrence collapsed across ordinals")
        seen_choice_ids.add(choice.choice_id)
        seen_weight_occurrences.add(occurrence_id)
    return {
        "source_path": node.source.source_path,
        "json_path": path,
        "source_occurrence_id": node.source_occurrence_id,
        "selection_id": selection.selection_id,
        "choice_count": len(selection.choices),
    }


def _independent_random_denominator(
    root: Path,
    snapshot: CharacterAbilityRawSnapshot,
    scope: Any,
    source_catalog: Any,
) -> dict[_SourceKey, dict[str, Any]]:
    digests = {
        item.source.source_path: item.content_sha256 for item in snapshot.sources
    }
    result: dict[_SourceKey, dict[str, Any]] = {}
    for record in scope.scope_records:
        if (
            record.materialization_role != "selected"
            or record.occurrence_kind != "typed_node"
            or record.family != _RANDOM_FAMILY
        ):
            continue
        source_path = record.source.source_path
        path = str(record.source.evidence["json_path"]).removesuffix(".$type")
        raw = _at_path(snapshot.documents[source_path], path)
        if (
            not isinstance(raw, Mapping)
            or _short_type(raw.get("$type")) != _RANDOM_FAMILY
        ):
            raise AssertionError("snapshot RandomConfig source is not reversible")
        result[(source_path, path, _RANDOM_FAMILY, digests[source_path])] = {
            "source_kind": "character_snapshot",
            "scope_record_id": record.record_id,
        }
    shared_paths = {
        item.source.source_path
        for item in source_catalog.template_definitions
        if getattr(item, "scope_kind", "") == "shared_global"
    }
    for source_path in sorted(shared_paths):
        raw_bytes = (root / source_path).read_bytes()
        digest = sha256(raw_bytes).hexdigest()
        document = json.loads(raw_bytes)
        if not isinstance(document, Mapping):
            raise AssertionError("accepted shared template source is not an object")

        def walk(value: object, path: str) -> None:
            if isinstance(value, Mapping):
                if _short_type(value.get("$type")) == _RANDOM_FAMILY:
                    result[(source_path, path, _RANDOM_FAMILY, digest)] = {
                        "source_kind": "shared_template",
                        "scope_record_id": "",
                    }
                for field, child in value.items():
                    walk(child, f"{path}.{field}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    walk(child, f"{path}[{index}]")

        walk(document, "$")
    if not result:
        raise AssertionError("current RandomConfig denominator is empty")
    return result


def _template_scope(
    key: _SourceKey,
    source_catalog: Any,
) -> tuple[str, str] | None:
    source_path, json_path, _, _ = key
    candidates = []
    for template in source_catalog.template_definitions:
        template_path = str(template.source.evidence.get("json_path") or "")
        if (
            template.source.source_path == source_path
            and template_path
            and json_path.startswith(f"{template_path}.TaskList")
        ):
            candidates.append(
                (len(template_path), template.scope_kind, template.template_id)
            )
    if not candidates:
        return None
    _, scope_kind, template_id = max(candidates)
    return scope_kind, template_id


def _build_status_bundle(
    lowering: TBGDLowering,
    source_graph: Any,
    snapshot: CharacterAbilityRawSnapshot,
    formal_context: Any,
) -> _StatusBundle:
    priority_lookup = {
        (item.priority_table, item.priority_key): item
        for item in lowering._lower_queue_priorities()
        if item.coverage_status == "executable"
    }
    callbacks: list[Any] = []
    status_tasks: list[Any] = []
    effects: list[Any] = []
    conditions: list[Any] = []
    targets: list[Any] = []
    queue_intents: list[Any] = []
    for order, source in enumerate(snapshot.sources):
        relative = source.source.source_path
        lowered = lowering._lower_ability_file(
            lowering.tbgd_root / relative,
            priority_lookup,
            ability_file_order=order,
            raw_document=snapshot.documents[relative],
            formal_status_source_context=formal_context,
        )
        callbacks.extend(lowered.status_callbacks)
        status_tasks.extend(lowered.status_callback_tasks)
        effects.extend(lowered.effects)
        conditions.extend(lowered.conditions)
        targets.extend(lowered.target_expressions)
        queue_intents.extend(lowered.queue_intents)
    effects_by_id = {item.effect_id: item for item in effects}
    trigger_names = frozenset(
        standard.get("ability_name")
        for task in status_tasks
        if task.opcode == "TriggerAbility"
        and (effect := effects_by_id.get(task.effect_id)) is not None
        and isinstance((standard := effect.payload.get("standard")), Mapping)
        and isinstance(standard.get("ability_name"), str)
    )
    trigger_paths = {
        item.source.source_path
        for item in source_graph.definitions
        if item.ability_name in trigger_names
    }
    if trigger_paths:
        parts = lowering._lower_standalone_ability_graphs(
            tuple(lowering.tbgd_root / path for path in sorted(trigger_paths))
        )
        graphs, phases, ability_tasks, extra_effects, extra_conditions, *extras = parts
        extra_targets = [
            item
            for values in extras
            for item in values
            if hasattr(item, "target_expression_id")
        ]
        effects.extend(extra_effects)
        conditions.extend(extra_conditions)
        targets.extend(extra_targets)
        status_tasks = list(
            _link_status_trigger_ability_graphs(
                status_tasks, callbacks, effects, graphs
            )
        )
    else:
        graphs = ()
        phases = ()
        ability_tasks = ()
    view = CanonicalIR(
        version="p9_s8c1_status_projection",
        ability_phases=tuple(phases),
        ability_tasks=tuple(ability_tasks),
        standalone_ability_graphs=tuple(graphs),
        status_callbacks=tuple(callbacks),
        status_callback_tasks=tuple(status_tasks),
        effects=_dedupe(effects, "effect_id"),
        conditions=_dedupe(conditions, "condition_id"),
        target_expressions=_dedupe(targets, "target_expression_id"),
    )
    return _StatusBundle(
        view,
        tuple(status_tasks),
        tuple(queue_intents),
        trigger_names,
    )


def _definition_random_sources(
    lowering: TBGDLowering,
    source_graph: Any,
    formal_context: Any,
) -> tuple[dict[str, frozenset[_SourceKey]], dict[str, Any]]:
    result: dict[str, frozenset[_SourceKey]] = {}
    definitions_by_id = {
        item.definition_id: item for item in source_graph.definitions
    }
    if len(definitions_by_id) != len(source_graph.definitions):
        raise AssertionError("ability source definitions contain duplicate identities")
    for definition in source_graph.definitions:
        if definition.definition_kind == "presentation":
            continue
        raw, document = lowering._character_ability_definition_record(definition)
        ability_index = definition.source.evidence.get("ability_index")
        if type(ability_index) is not int:
            raise AssertionError("gameplay ability definition index is missing")
        lowered = lowering._lower_ability_phase_tasks(
            definition=_DefinitionRef(f"audit:{definition.definition_id}"),
            phase_id=f"audit_phase:{definition.definition_id}",
            ability_name=definition.ability_name,
            ability=raw,
            ability_path=definition.source.source_path,
            ability_index=ability_index,
            target_alias_registry=(
                document.get("GlobalTargetAlias")
                if isinstance(document.get("GlobalTargetAlias"), dict)
                else {}
            ),
            formal_source_context=formal_context,
        )
        keys = frozenset(
            _task_key(task, "source_opcode", formal_context.content_sha256_by_path)
            for task in lowered.ability_tasks
            if _task_key(
                task, "source_opcode", formal_context.content_sha256_by_path
            )[2]
            == _RANDOM_FAMILY
        )
        if keys:
            result[definition.definition_id] = keys
    return result, definitions_by_id


def _action_ids_by_random_definition(
    source_graph: Any,
    random_definition_sources: Mapping[str, frozenset[_SourceKey]],
) -> dict[str, frozenset[str]]:
    actions = {item.action_source_id: item for item in source_graph.action_sources}
    result: dict[str, set[str]] = defaultdict(set)
    for binding in source_graph.bindings:
        if (
            binding.ability_definition_id not in random_definition_sources
            or not binding.action_source_id
            or binding.binding_kind not in _ACTION_BINDING_KINDS
        ):
            continue
        action = actions.get(binding.action_source_id)
        if action is not None and action.action_kind != "maze":
            result[binding.ability_definition_id].add(action.action_id)
    return {
        definition_id: frozenset(values)
        for definition_id, values in result.items()
    }


def _matching_random_definition_ids(
    names: Iterable[str],
    random_definition_sources: Mapping[str, frozenset[_SourceKey]],
    definition_by_id: Mapping[str, Any],
) -> frozenset[str]:
    wanted = set(names)
    return frozenset(
        definition_id
        for definition_id in random_definition_sources
        if definition_by_id[definition_id].ability_name in wanted
    )


def _build_real_context(root: Path) -> _RealContext:
    lowering = TBGDLowering(root)
    source_graph = lowering.build_character_ability_source_graph_catalog()
    snapshot = lowering._character_ability_raw_snapshot
    scope = lowering._character_ability_scope_catalog
    if type(snapshot) is not CharacterAbilityRawSnapshot:
        raise AssertionError("production CharacterAbilityRawSnapshot is unavailable")
    source_catalog = lowering.build_character_control_flow_contract_catalog(
        snapshot=snapshot, scope_catalog=scope
    )
    lowering.build_character_ability_source_resolution_catalog()
    formal_context = lowering._character_formal_task_source_context()
    status_bundle = _build_status_bundle(
        lowering,
        source_graph,
        snapshot,
        formal_context,
    )
    random_definition_sources, definition_by_id = _definition_random_sources(
        lowering, source_graph, formal_context
    )
    action_ids = _action_ids_by_random_definition(
        source_graph, random_definition_sources
    )
    trigger_ids = _matching_random_definition_ids(
        status_bundle.trigger_names,
        random_definition_sources,
        definition_by_id,
    )
    queue_names = {
        item.action_ref_or_ability_name
        for item in status_bundle.queue_intents
        if item.coverage_status == "executable"
        and isinstance(item.action_ref_or_ability_name, str)
        and item.action_ref_or_ability_name
    }
    queue_ids = _matching_random_definition_ids(
        queue_names,
        random_definition_sources,
        definition_by_id,
    )
    return _RealContext(
        lowering,
        source_graph,
        snapshot,
        scope,
        source_catalog,
        formal_context,
        status_bundle,
        random_definition_sources,
        definition_by_id,
        action_ids,
        queue_ids,
        trigger_ids,
        formal_context.content_sha256_by_path,
    )


def _candidate_action_ids(context: _RealContext) -> set[str]:
    return {
        action_id
        for values in context.action_ids_by_random_definition.values()
        for action_id in values
    }


def _direct_action_ids(context: _RealContext) -> set[str]:
    all_ids = sorted(_candidate_action_ids(context))
    if not all_ids:
        return set()
    selected = {all_ids[0]}
    template_ids = {
        definition_id
        for definition_id, keys in context.random_definition_sources.items()
        if context.action_ids_by_random_definition.get(definition_id)
        and any(_template_scope(key, context.source_catalog) for key in keys)
    }
    for definition_id in sorted(template_ids):
        values = sorted(context.action_ids_by_random_definition[definition_id])
        if values:
            selected.add(values[0])
            break
    return selected


def _action_batch(
    context: _RealContext,
    action_ids: Iterable[str],
) -> tuple[_ActionBatch | None, list[str]]:
    wanted_action_ids = set(action_ids)
    definitions = tuple(
        sorted(
            (
                definition
                for definition in build_character_action_definition_ir(
                    context.lowering.tbgd_root
                )
                if definition.action_id in wanted_action_ids
            ),
            key=lambda item: (item.action_id, item.level, item.definition_id),
        )
    )
    found_action_ids = {item.action_id for item in definitions}
    failures = [
        f"{action_id}:definition_missing"
        for action_id in sorted(wanted_action_ids - found_action_ids)
    ]
    if not definitions:
        return None, failures
    try:
        (
            bindings,
            phases,
            tasks,
            effects,
            conditions,
            _formulas,
            targets,
        ) = context.lowering._lower_action_ability_bindings(list(definitions))
        tasks = _link_trigger_ability_graphs(tasks, effects, [], phases)
        view = CanonicalIR(
            version="p9_s8c1_action_projection",
            action_ability_bindings=tuple(bindings),
            ability_phases=tuple(phases),
            ability_tasks=tuple(tasks),
            effects=_dedupe(effects, "effect_id"),
            conditions=_dedupe(conditions, "condition_id"),
            target_expressions=_dedupe(targets, "target_expression_id"),
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        failures.append(f"action_batch:{type(exc).__name__}:{exc}")
        return None, failures
    definition_by_key = {
        (item.action_id, item.level): item for item in definitions
    }
    if len(definition_by_key) != len(definitions):
        failures.append("action_batch:duplicate_action_level_definition")
        return None, failures
    binding_by_id = {item.binding_id: item for item in bindings}
    producer_by_owner: dict[str, str] = {}
    for phase in phases:
        if phase.invocation_role not in _FORMAL_ROLES:
            continue
        binding = binding_by_id.get(phase.binding_id)
        if binding is None:
            failures.append(f"{phase.phase_id}:binding_missing")
            continue
        definition = definition_by_key.get((binding.action_id, binding.level))
        if definition is None:
            failures.append(f"{phase.phase_id}:action_definition_missing")
            continue
        producer_by_owner[phase.phase_id] = definition.definition_id
    if failures:
        return None, failures
    return _ActionBatch(definitions, view, producer_by_owner), []


def _queue_view(context: _RealContext) -> CanonicalIR | None:
    if not context.queue_random_definition_ids:
        return None
    names = {
        context.definition_by_id[item].ability_name
        for item in context.queue_random_definition_ids
    }
    intents = tuple(
        item
        for item in context.status_bundle.queue_intents
        if item.coverage_status == "executable"
        and item.action_ref_or_ability_name in names
    )
    if not intents:
        return None
    source_paths = {
        context.definition_by_id[item].source.source_path
        for item in context.queue_random_definition_ids
    }
    parts = context.lowering._lower_standalone_ability_graphs(
        tuple(context.lowering.tbgd_root / path for path in sorted(source_paths))
    )
    graphs, phases, tasks, effects, conditions, *extras = parts
    targets = [
        item
        for values in extras
        for item in values
        if hasattr(item, "target_expression_id")
    ]
    tasks = _link_trigger_ability_graphs(tasks, effects, graphs, phases)
    resolutions = _lower_queue_resolutions(
        queue_intents=intents,
        action_bindings=[],
        ability_phases=phases,
        standalone_graphs=graphs,
        combatant_action_sets=[],
    )
    phases = _assign_character_ability_invocation_roles(
        phases, tasks, graphs, resolutions
    )
    if not any(item.invocation_role in _FORMAL_ROLES for item in phases):
        return None
    return CanonicalIR(
        version="p9_s8c1_queue_projection",
        ability_phases=tuple(phases),
        ability_tasks=tuple(tasks),
        standalone_ability_graphs=tuple(graphs),
        effects=_dedupe(effects, "effect_id"),
        conditions=_dedupe(conditions, "condition_id"),
        target_expressions=_dedupe(targets, "target_expression_id"),
    )


def _combined_view(
    context: _RealContext,
    action: _ActionBatch | None,
    queue: CanonicalIR | None,
) -> CanonicalIR:
    views = [context.status_bundle.view]
    if action is not None:
        views.append(action.view)
    if queue is not None:
        views.append(queue)
    bindings = _dedupe(
        (item for view in views for item in view.action_ability_bindings),
        "binding_id",
    )
    phases = _dedupe(
        (item for view in views for item in view.ability_phases),
        "phase_id",
    )
    tasks = _dedupe(
        (item for view in views for item in view.ability_tasks),
        "task_id",
    )
    graphs = _dedupe(
        (item for view in views for item in view.standalone_ability_graphs),
        "graph_id",
    )
    callbacks = _dedupe(
        (item for view in views for item in view.status_callbacks),
        "callback_id",
    )
    status_tasks = _dedupe(
        (item for view in views for item in view.status_callback_tasks),
        "task_id",
    )
    effects = _dedupe(
        (item for view in views for item in view.effects),
        "effect_id",
    )
    conditions = _dedupe(
        (item for view in views for item in view.conditions),
        "condition_id",
    )
    targets = _dedupe(
        (item for view in views for item in view.target_expressions),
        "target_expression_id",
    )
    if not any(item.invocation_role in _FORMAL_ROLES for item in phases):
        raise AssertionError("combined public catalog projection has no formal ability phase")
    return CanonicalIR(
        version="p9_s8c1_random_config_aggregate_projection",
        action_ability_bindings=bindings,
        ability_phases=phases,
        ability_tasks=tasks,
        standalone_ability_graphs=graphs,
        status_callbacks=callbacks,
        status_callback_tasks=status_tasks,
        effects=effects,
        conditions=conditions,
        target_expressions=targets,
    )


def _producer_identity(
    entry_kind: str,
    owner_id: str,
    action_producer_by_owner: Mapping[str, str],
) -> tuple[str, str]:
    if entry_kind == "status_callback":
        return "status_callback", owner_id
    action_definition = action_producer_by_owner.get(owner_id)
    if action_definition:
        return "action_definition", action_definition
    return "ability_phase", owner_id


def _expected_formal_positions(
    view: CanonicalIR,
    digests: Mapping[str, str],
    action_producer_by_owner: Mapping[str, str],
) -> set[_FormalPositionKey]:
    phase_by_id = {
        phase.phase_id: phase
        for phase in view.ability_phases
        if phase.invocation_role in _FORMAL_ROLES
    }
    callback_event = {
        callback.callback_id: callback.event for callback in view.status_callbacks
    }
    expected: set[_FormalPositionKey] = set()
    for task in view.ability_tasks:
        if task.phase_id not in phase_by_id:
            continue
        key = _task_key(task, "source_opcode", digests)
        if key[2] != _RANDOM_FAMILY:
            continue
        producer_kind, producer_instance_id = _producer_identity(
            "ability_phase_callback",
            task.phase_id,
            action_producer_by_owner,
        )
        expected.add(
            _formal_position(
                producer_kind=producer_kind,
                producer_instance_id=producer_instance_id,
                entry_kind="ability_phase_callback",
                owner_id=task.phase_id,
                callback_kind=task.callback_kind,
                formal_task_id=task.task_id,
                source_key=key,
            )
        )
    for task in view.status_callback_tasks:
        key = _task_key(task, "raw_opcode", digests)
        if key[2] != _RANDOM_FAMILY:
            continue
        event = callback_event.get(task.callback_id)
        if not event:
            raise AssertionError("formal status RandomConfig callback owner is missing")
        expected.add(
            _formal_position(
                producer_kind="status_callback",
                producer_instance_id=task.callback_id,
                entry_kind="status_callback",
                owner_id=task.callback_id,
                callback_kind=event,
                formal_task_id=task.task_id,
                source_key=key,
            )
        )
    return expected


def _formal_random_task_keys(
    view: CanonicalIR,
    digests: Mapping[str, str],
) -> set[_SourceKey]:
    formal_phase_ids = {
        phase.phase_id
        for phase in view.ability_phases
        if phase.invocation_role in _FORMAL_ROLES
    }
    keys = {
        _task_key(task, "source_opcode", digests)
        for task in view.ability_tasks
        if task.phase_id in formal_phase_ids
        and _task_key(task, "source_opcode", digests)[2] == _RANDOM_FAMILY
    }
    keys.update(
        _task_key(task, "raw_opcode", digests)
        for task in view.status_callback_tasks
        if _task_key(task, "raw_opcode", digests)[2] == _RANDOM_FAMILY
    )
    return keys


def _catalog_positions(
    root: Path,
    snapshot: CharacterAbilityRawSnapshot,
    catalog: TaskGraphCatalogIR,
    action_producer_by_owner: Mapping[str, str],
) -> tuple[
    dict[_SourceKey, list[dict[str, Any]]],
    set[_FormalPositionKey],
    dict[str, Any] | None,
]:
    positions: dict[_SourceKey, list[dict[str, Any]]] = defaultdict(list)
    formal_positions: set[_FormalPositionKey] = set()
    entries = {item.entry_id: item for item in catalog.entry_materializations}
    dispositions = {
        item.source_record_id: item for item in catalog.source_dispositions
    }
    non_random_sample = None
    for graph in catalog.graphs:
        _audit_graph_selection_structure(graph)
        selections_by_node: dict[str, list[TaskGraphWeightedSelectionIR]] = defaultdict(list)
        for selection in graph.weighted_selections:
            selections_by_node[selection.graph_node_id].append(selection)
        entry = entries.get(graph.entry_id)
        if entry is None:
            raise AssertionError("graph entry materialization is missing")
        producer_kind, producer_instance_id = _producer_identity(
            graph.entry_kind,
            graph.owner_id,
            action_producer_by_owner,
        )
        for node in graph.nodes:
            selections = selections_by_node.get(node.graph_node_id, ())
            if node.source_family != _RANDOM_FAMILY:
                if selections:
                    raise AssertionError("non-RandomConfig node gained weighted selection")
                if non_random_sample is None:
                    non_random_sample = {
                        "entry_kind": graph.entry_kind,
                        "graph_id": graph.graph_id,
                        "node_id": node.graph_node_id,
                        "source_family": node.source_family,
                    }
                continue
            if len(selections) != 1:
                raise AssertionError("formal RandomConfig node lacks a unique selection")
            selection = selections[0]
            source_evidence = _verify_selection(
                root, snapshot, graph, node, selection
            )
            if not node.source_contract_node_id:
                raise AssertionError("formal RandomConfig node is outside S8A source ledger")
            disposition = dispositions.get(node.source_contract_node_id)
            if disposition is None:
                raise AssertionError("RandomConfig source disposition is missing")
            if (
                disposition.family != _RANDOM_FAMILY
                or _source_key(disposition.source, disposition.family)
                != _source_key(node.source, node.source_family)
                or entry.materialization_id
                not in disposition.formal_materialization_ids
            ):
                raise AssertionError("RandomConfig source/materialization ledger diverged")
            key = _source_key(node.source, node.source_family)
            row = {
                "producer_kind": producer_kind,
                "producer_instance_id": producer_instance_id,
                "entry_kind": graph.entry_kind,
                "owner_id": graph.owner_id,
                "callback_kind": graph.callback_kind,
                "entry_id": graph.entry_id,
                "materialization_id": entry.materialization_id,
                "graph_id": graph.graph_id,
                "graph_node_id": node.graph_node_id,
                "formal_task_id": node.formal_task_id,
                "source_record_id": node.source_contract_node_id,
                **source_evidence,
            }
            positions[key].append(row)
            formal_positions.add(
                _formal_position(
                    producer_kind=producer_kind,
                    producer_instance_id=producer_instance_id,
                    entry_kind=graph.entry_kind,
                    owner_id=graph.owner_id,
                    callback_kind=graph.callback_kind,
                    formal_task_id=node.formal_task_id,
                    source_key=key,
                )
            )
    return positions, formal_positions, non_random_sample


def _s8a_random_map(source_catalog: Any) -> dict[_SourceKey, Any]:
    result = {
        _source_key(item.source, item.family): item
        for item in source_catalog.nodes
        if item.family == _RANDOM_FAMILY
    }
    if len(result) != sum(
        item.family == _RANDOM_FAMILY for item in source_catalog.nodes
    ):
        raise AssertionError("S8A RandomConfig source identities are duplicated")
    return result


def _base_random_dispositions(context: _RealContext) -> dict[_SourceKey, Any]:
    base = build_complete_task_graph_catalog(
        context.source_catalog, context.snapshot
    )
    result = {
        _source_key(item.source, item.family): item
        for item in base.source_dispositions
        if item.source_kind == "control_node" and item.family == _RANDOM_FAMILY
    }
    if len(result) != sum(
        item.source_kind == "control_node" and item.family == _RANDOM_FAMILY
        for item in base.source_dispositions
    ):
        raise AssertionError("task-graph RandomConfig source ledger contains duplicates")
    return result


def _no_producer_evidence(
    keys: Iterable[_SourceKey],
    source_catalog: Any,
    base_dispositions: Mapping[_SourceKey, Any],
) -> list[dict[str, Any]]:
    references_by_template: dict[str, int] = Counter(
        item.resolved_template_id
        for item in source_catalog.template_references
        if item.coverage_status == "lowered"
    )
    evidence: list[dict[str, Any]] = []
    for key in sorted(keys):
        disposition = base_dispositions.get(key)
        if disposition is None or disposition.formal_materialization_ids:
            raise AssertionError("no-producer source ledger is inconsistent")
        if (
            disposition.disposition == "blocked"
            or len(disposition.owner_domains) != 1
        ):
            raise AssertionError("no-producer source lacks one deferred owner")
        template = _template_scope(key, source_catalog)
        evidence.append(
            {
                "source_path": key[0],
                "json_path": key[1],
                "family": key[2],
                "content_sha256": key[3],
                "source_record_id": disposition.source_record_id,
                "deferred_owner": disposition.owner_domains[0],
                "ancestor_template_scope": template[0] if template else None,
                "ancestor_template_id": template[1] if template else None,
                "accepted_reference_count": (
                    references_by_template.get(template[1], 0) if template else 0
                ),
            }
        )
    return evidence


def _producer_expected_keys(context: _RealContext) -> set[_SourceKey]:
    action_definition_ids = {
        definition_id
        for definition_id, values in context.action_ids_by_random_definition.items()
        if values
    }
    expected_ids = (
        action_definition_ids
        | set(context.trigger_random_definition_ids)
        | set(context.queue_random_definition_ids)
    )
    keys = {
        key
        for definition_id in expected_ids
        for key in context.random_definition_sources[definition_id]
    }
    keys.update(
        _task_key(task, "raw_opcode", context.digest_by_path)
        for task in context.status_bundle.status_tasks
        if _task_key(task, "raw_opcode", context.digest_by_path)[2]
        == _RANDOM_FAMILY
    )
    return keys


def _single_entry_checks(
    root: Path,
    context: _RealContext,
    view: CanonicalIR,
    catalog: TaskGraphCatalogIR,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    ability_graph = next(
        (
            graph
            for graph in catalog.graphs
            if graph.entry_kind == "ability_phase_callback"
            and any(node.source_family == _RANDOM_FAMILY for node in graph.nodes)
        ),
        None,
    )
    if ability_graph is not None:
        single = materialize_ability_phase_task_graph(
            context.source_catalog,
            view,
            phase_id=ability_graph.owner_id,
            callback_kind=ability_graph.callback_kind,
            source_snapshot=context.snapshot,
        )
        if len(single.graphs) != 1 or single.graphs[0].to_json() != ability_graph.to_json():
            raise AssertionError("ability single-entry/combined catalog diverged")
        node = next(
            item for item in ability_graph.nodes if item.source_family == _RANDOM_FAMILY
        )
        selection = next(
            item
            for item in ability_graph.weighted_selections
            if item.graph_node_id == node.graph_node_id
        )
        result["ability_phase_callback"] = {
            "owner_id": ability_graph.owner_id,
            "callback_kind": ability_graph.callback_kind,
            **_verify_selection(root, context.snapshot, ability_graph, node, selection),
        }
    else:
        result["ability_phase_callback"] = "zero_by_denominator"
    status_graph = next(
        (
            graph
            for graph in catalog.graphs
            if graph.entry_kind == "status_callback"
            and any(node.source_family == _RANDOM_FAMILY for node in graph.nodes)
        ),
        None,
    )
    if status_graph is not None:
        single = materialize_status_callback_task_graph(
            context.source_catalog,
            view,
            callback_id=status_graph.owner_id,
            source_snapshot=context.snapshot,
        )
        if len(single.graphs) != 1 or single.graphs[0].to_json() != status_graph.to_json():
            raise AssertionError("status single-entry/combined catalog diverged")
        node = next(
            item for item in status_graph.nodes if item.source_family == _RANDOM_FAMILY
        )
        selection = next(
            item
            for item in status_graph.weighted_selections
            if item.graph_node_id == node.graph_node_id
        )
        result["status_callback"] = {
            "callback_id": status_graph.owner_id,
            "event": status_graph.callback_kind,
            **_verify_selection(root, context.snapshot, status_graph, node, selection),
        }
    else:
        result["status_callback"] = "zero_by_denominator"
    return result


def _sample_by_producer(
    positions: Mapping[_SourceKey, list[dict[str, Any]]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in sorted(positions):
        for row in sorted(
            positions[key],
            key=lambda item: (
                item["producer_kind"],
                item["producer_instance_id"],
                item["entry_id"],
                item["graph_node_id"],
            ),
        ):
            result.setdefault(row["producer_kind"], row)
    return result


def _real_mode(root: Path, *, mode: str) -> dict[str, Any]:
    started = time.perf_counter()
    full_build_calls = 0
    original_build = TBGDLowering.build

    def forbidden_build(_self: TBGDLowering) -> object:
        nonlocal full_build_calls
        full_build_calls += 1
        raise AssertionError("P9-S8C1 aggregate attempted full CanonicalIR build")

    TBGDLowering.build = forbidden_build
    try:
        context = _build_real_context(root)
        denominator = _independent_random_denominator(
            root, context.snapshot, context.scope, context.source_catalog
        )
        s8a = _s8a_random_map(context.source_catalog)
        source_ledger = _base_random_dispositions(context)
        if set(denominator) != set(s8a) or set(denominator) != set(source_ledger):
            raise AssertionError(
                "raw/S8A/task-graph source denominators diverged:"
                f"raw={len(denominator)} s8a={len(s8a)} ledger={len(source_ledger)}"
            )
        action_ids = (
            _candidate_action_ids(context)
            if mode == "catalog"
            else _direct_action_ids(context)
        )
        action, action_failures = _action_batch(context, action_ids)
        if action_failures:
            raise AssertionError(
                "formal action RandomConfig projection failed:"
                + json.dumps(action_failures[:8], ensure_ascii=True)
            )
        if _candidate_action_ids(context) and action is None:
            raise AssertionError("current action RandomConfig producer class has no Direct/Catalog sample")
        queue = _queue_view(context)
        view = _combined_view(context, action, queue)
        action_producer_by_owner = action.producer_by_owner if action else {}
        expected_positions = _expected_formal_positions(
            view,
            context.digest_by_path,
            action_producer_by_owner,
        )
        if not expected_positions:
            raise AssertionError("combined formal RandomConfig position denominator is empty")
        formal_task_keys = _formal_random_task_keys(view, context.digest_by_path)
        catalog = materialize_character_runtime_task_graph_catalog(
            context.source_catalog,
            view,
            source_snapshot=context.snapshot,
            definition_scope_complete=True,
        )
        positions, actual_positions, nonrandom_sample = _catalog_positions(
            root,
            context.snapshot,
            catalog,
            action_producer_by_owner,
        )
        _audit_exact_positions(expected_positions, actual_positions)
        expected_source_keys = {
            (
                item.source_path,
                item.json_path,
                item.family,
                item.content_sha256,
            )
            for item in expected_positions
        }
        if set(positions) != expected_source_keys or formal_task_keys != expected_source_keys:
            raise AssertionError("formal task/source/graph RandomConfig positions diverged")
        if set(positions) - set(denominator):
            raise AssertionError("formal graph contains RandomConfig outside raw denominator")
        producer_expected = _producer_expected_keys(context)
        if mode == "catalog" and producer_expected - expected_source_keys:
            raise AssertionError(
                "accepted formal RandomConfig source lacks a combined public-catalog producer:"
                f"{len(producer_expected - expected_source_keys)}"
            )
        no_producer_keys = set(denominator) - expected_source_keys
        _audit_classification(set(denominator), expected_source_keys, no_producer_keys)
        if mode == "catalog":
            no_producer_evidence = _no_producer_evidence(
                no_producer_keys,
                context.source_catalog,
                source_ledger,
            )
            if no_producer_keys & (set(positions) | formal_task_keys | producer_expected):
                raise AssertionError("no_formal_producer source gained a synthetic producer")
        else:
            no_producer_evidence = []
        if nonrandom_sample is None:
            raise AssertionError("a real non-RandomConfig formal node is required")
        single_entry = _single_entry_checks(root, context, view, catalog)
        producer_samples = _sample_by_producer(positions)
        expected_classes = {item.producer_kind for item in expected_positions}
        if expected_classes != set(producer_samples):
            raise AssertionError("Direct/Catalog producer-class sampling is incomplete")
        if mode == "direct" and _candidate_action_ids(context):
            if "action_definition" not in producer_samples:
                raise AssertionError("Direct lost the real action-definition producer class")
        elapsed = time.perf_counter() - started
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        budget_seconds = (
            _DIRECT_HARD_SECONDS if mode == "direct" else _CATALOG_HARD_SECONDS
        )
        budget_rss = (
            _DIRECT_RSS_LIMIT_KIB if mode == "direct" else _CATALOG_RSS_LIMIT_KIB
        )
        predicates: dict[str, Any] = {
            "raw_s8a_source_ledger_exact_equal": (
                set(denominator) == set(s8a) == set(source_ledger)
            ),
            "expected_actual_formal_positions_exact_equal": (
                expected_positions == actual_positions
            ),
            "formal_task_source_and_actual_graph_source_exact_equal": (
                formal_task_keys == expected_source_keys == set(positions)
            ),
            "all_formal_random_config_nodes_have_exactly_one_selection": True,
            "weighted_choice_ordinal_branch_numeric_source_contract_closed": True,
            "non_random_config_nodes_have_no_weighted_selection": True,
            "combined_public_character_runtime_catalog_used": True,
            "producer_classes_dynamically_sampled": (
                expected_classes == set(producer_samples)
            ),
            "single_entry_matches_combined_catalog": all(
                value == "zero_by_denominator" or isinstance(value, dict)
                for value in single_entry.values()
            ),
            "full_canonical_ir_build_count": full_build_calls,
            "runtime_rng_executed": False,
            "mutation_event_settlement_replay_executed": False,
        }
        if mode == "catalog":
            predicates.update(
                {
                    "every_denominator_occurrence_is_exactly_formal_bound_or_no_formal_producer": (
                        expected_source_keys | no_producer_keys == set(denominator)
                        and not expected_source_keys.intersection(no_producer_keys)
                    ),
                    "producer_expected_sources_are_formal_bound": (
                        producer_expected <= expected_source_keys
                    ),
                    "no_formal_producer_has_no_synthetic_graph": not no_producer_keys.intersection(
                        set(positions) | formal_task_keys | producer_expected
                    ),
                    "no_formal_producer_has_unique_deferred_owner": all(
                        isinstance(item.get("deferred_owner"), str)
                        and bool(item["deferred_owner"])
                        for item in no_producer_evidence
                    ),
                }
            )
        boolean_predicates = {
            key: value
            for key, value in predicates.items()
            if key
            not in {
                "full_canonical_ir_build_count",
                "runtime_rng_executed",
                "mutation_event_settlement_replay_executed",
            }
        }
        ok = (
            all(value is True for value in boolean_predicates.values())
            and predicates["full_canonical_ir_build_count"] == 0
            and predicates["runtime_rng_executed"] is False
            and predicates["mutation_event_settlement_replay_executed"] is False
            and elapsed <= budget_seconds
            and peak <= budget_rss
        )
        definitions = action.definitions if action is not None else ()
        return {
            "ok": ok,
            "mode": mode,
            "predicates": predicates,
            "denominator": {
                "count": len(denominator),
                "fingerprint": _denominator_fingerprint(denominator),
                "formal_bound_count": len(expected_source_keys),
                "no_formal_producer_count": len(no_producer_keys),
            },
            "formal_position_denominator": {
                "expected_count": len(expected_positions),
                "actual_count": len(actual_positions),
                "fingerprint": _formal_position_fingerprint(expected_positions),
                "enumerated_action_definition_count": len(definitions),
                "action_definition_levels": [
                    {
                        "action_id": item.action_id,
                        "level": item.level,
                        "definition_id": item.definition_id,
                    }
                    for item in definitions
                ],
            },
            "producer_classes": {
                key: "formal_bound" for key in sorted(expected_classes)
            },
            "samples": {
                "producer_classes": producer_samples,
                "single_entry": single_entry,
                "non_random": nonrandom_sample,
                "no_formal_producer": no_producer_evidence[:3],
            },
            "resource": {
                "wall_seconds": round(elapsed, 6),
                "peak_rss_kib": peak,
            },
        }
    finally:
        TBGDLowering.build = original_build
        gc.collect()


def _run_direct(root: Path) -> dict[str, Any]:
    return _real_mode(root, mode="direct")


def _run_catalog(root: Path) -> dict[str, Any]:
    return _real_mode(root, mode="catalog")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate P9-S8C1 aggregate RandomConfig graph contract"
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--fast", action="store_true")
    modes.add_argument("--direct", action="store_true")
    modes.add_argument("--catalog", action="store_true")
    parser.add_argument("--tbgd-root", type=Path, default=DEFAULT_TBGD)
    args = parser.parse_args()
    summary = (
        _run_fast()
        if args.fast
        else _run_direct(args.tbgd_root.resolve())
        if args.direct
        else _run_catalog(args.tbgd_root.resolve())
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
