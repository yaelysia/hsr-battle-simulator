from __future__ import annotations

import argparse
import gc
import json
import resource
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
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
from ..tbgd.character_ability_scope import (
    CharacterAbilityRawSnapshot,
    build_character_ability_raw_snapshot,
    build_character_ability_scope_projection,
)
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
    materialize_ability_task_graph_catalog,
    materialize_character_runtime_task_graph_catalog,
    materialize_status_callback_task_graph,
)


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TBGD = ROOT / "turnbasedgamedata-main"
_FAST_HARD_SECONDS = 30.0
_DIRECT_HARD_SECONDS = 120.0
_CATALOG_HARD_SECONDS = 180.0
_FAST_RSS_LIMIT_KIB = 512 * 1024
_DIRECT_RSS_LIMIT_KIB = 1024 * 1024
_CATALOG_RSS_LIMIT_KIB = 1280 * 1024
_FORMAL_ROLES = frozenset({"action_root", "nested_only", "standalone_root"})
_ACTION_BINDING_KINDS = frozenset({"entry", "phase", "passive"})
_RANDOM_FAMILY = "RandomConfig"
_SourceKey = tuple[str, str, str, str]


@dataclass(frozen=True)
class _FixtureSnapshot:
    source_bytes: Mapping[str, bytes]


@dataclass(frozen=True)
class _DefinitionRef:
    action_id: str
    level: int = 0


@dataclass
class _StatusBundle:
    view: CanonicalIR
    catalog: TaskGraphCatalogIR
    callbacks: tuple[Any, ...]
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
    full_build_count: int


def _expect_rejected(action: Callable[[], object], subject: str) -> None:
    try:
        action()
    except (KeyError, IndexError, TypeError, ValueError, RuntimeError):
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
    *,
    odds: object = None,
) -> tuple[TaskGraphIR, TaskGraphWeightedSelectionIR]:
    odds_list = [2, 3] if odds is None else odds
    raw_parent = {
        "$type": "RandomConfig",
        "OddsList": odds_list,
        "ConfigList": [{}, {}],
    }
    payload = json.dumps(
        {"Task": raw_parent}, sort_keys=True, separators=(",", ":")
    ).encode()
    source = IRSource(
        "validation_fixture/p9_s8c1c.json",
        "RandomConfig",
        "fixture_random_config",
        {
            "json_path": "$.Task",
            "content_sha256": sha256(payload).hexdigest(),
            "source_opcode": "RandomConfig",
            "task_path": "fixture[0]",
        },
    )
    occurrence_id = task_graph_source_occurrence_id(source, "RandomConfig")
    owner_id = "fixture:status" if entry_kind == "status_callback" else "fixture:phase"
    callback_kind = (
        "OnBeforeBeingHit" if entry_kind == "status_callback" else "OnStart"
    )
    entry_id = task_graph_entry_id(entry_kind, owner_id, callback_kind)
    graph_id = task_graph_id(
        "fixture:source_catalog", entry_id, source.evidence["content_sha256"]
    )
    node_id = task_graph_node_id(graph_id, "fixture:task", occurrence_id)
    branches = tuple(
        TaskGraphBranchIR(
            branch_id=task_graph_branch_id(
                node_id,
                "config",
                ordinal,
                f"choice_{ordinal}",
                (),
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


def _bad_odds_fixture() -> None:
    _fixture("status_callback", odds=[1])


def _audit_claimed_classification(
    denominator: set[str],
    formal_positions: Mapping[str, tuple[str, ...]],
    claimed: Mapping[str, str],
) -> None:
    if set(claimed) != denominator:
        raise ValueError("classification denominator is incomplete")
    for occurrence in denominator:
        positions = formal_positions.get(occurrence, ())
        expected = "formal_bound" if positions else "no_formal_producer"
        if claimed[occurrence] != expected:
            raise ValueError("producer classification conflicts with formal reachability")


def _run_fast() -> dict[str, Any]:
    started = time.perf_counter()
    ability_graph, _ = _fixture("ability_phase_callback")
    status_graph, status_selection = _fixture("status_callback")

    if not ability_graph.weighted_selections or not status_graph.weighted_selections:
        raise AssertionError("formal entry fixture lost RandomConfig weighted selection")
    if TaskGraphIR.from_json(status_graph.to_json()).to_json() != status_graph.to_json():
        raise AssertionError("status weighted-selection TaskGraphIR codec is unstable")

    _expect_rejected(
        lambda: replace(status_graph, weighted_selections=()),
        "status RandomConfig graph without weighted selection",
    )
    _expect_rejected(
        _bad_odds_fixture,
        "status RandomConfig OddsList/branch mismatch",
    )

    forged = status_selection.to_json()
    forged["parent_source_occurrence_id"] = "forged:source-occurrence"
    _expect_rejected(
        lambda: TaskGraphWeightedSelectionIR.from_json(forged),
        "forged selection parent source occurrence",
    )

    _expect_rejected(
        lambda: _audit_claimed_classification(
            {"formal", "orphan"},
            {"formal": ("entry:real",)},
            {
                "formal": "no_formal_producer",
                "orphan": "no_formal_producer",
            },
        ),
        "reachable RandomConfig relabeled no_formal_producer",
    )
    _expect_rejected(
        lambda: _audit_claimed_classification(
            {"formal", "orphan"},
            {
                "formal": ("entry:real",),
                "orphan": ("entry:synthetic",),
            },
            {
                "formal": "formal_bound",
                "orphan": "no_formal_producer",
            },
        ),
        "no-producer source with synthetic formal materialization",
    )

    elapsed = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    predicates = {
        "ability_path_preserved": bool(ability_graph.weighted_selections),
        "status_entry_accepts_weighted_selection": bool(
            status_graph.weighted_selections
        ),
        "status_missing_selection_fail_closed": True,
        "odds_branch_mismatch_fail_closed": True,
        "source_parent_identity_mismatch_fail_closed": True,
        "reachable_source_cannot_be_no_producer": True,
        "no_producer_cannot_have_synthetic_materialization": True,
        "runtime_behavior_changed": False,
    }
    return {
        "ok": (
            all(value is True for key, value in predicates.items() if key != "runtime_behavior_changed")
            and predicates["runtime_behavior_changed"] is False
            and elapsed <= _FAST_HARD_SECONDS
            and peak <= _FAST_RSS_LIMIT_KIB
        ),
        "mode": "fast",
        "cases": 7,
        "predicates": predicates,
        "resource": {
            "wall_seconds": round(elapsed, 6),
            "peak_rss_kib": peak,
        },
    }


def _source_bytes(
    root: Path,
    snapshot: CharacterAbilityRawSnapshot,
    source_path: str,
) -> bytes:
    value = snapshot.source_bytes.get(source_path)
    if value is not None:
        return value
    return (root / source_path).read_bytes()


def _verify_selection(
    root: Path,
    snapshot: CharacterAbilityRawSnapshot,
    graph: TaskGraphIR,
    node: TaskGraphNodeIR,
    selection: TaskGraphWeightedSelectionIR,
) -> dict[str, Any]:
    if node.source_family != _RANDOM_FAMILY:
        raise AssertionError("weighted selection parent is not RandomConfig")
    if selection.graph_node_id != node.graph_node_id:
        raise AssertionError("weighted selection graph node identity diverged")
    if selection.selection_id != task_graph_weighted_selection_id(
        node.graph_node_id, node.source_occurrence_id
    ):
        raise AssertionError("weighted selection identity diverged")
    raw_bytes = _source_bytes(root, snapshot, node.source.source_path)
    digest = sha256(raw_bytes).hexdigest()
    if digest != node.source.evidence.get("content_sha256"):
        raise AssertionError("RandomConfig source bytes fingerprint mismatch")
    document = json.loads(raw_bytes)
    if not isinstance(document, Mapping):
        raise AssertionError("RandomConfig source document is not an object")
    path = node.source.evidence.get("json_path")
    if not isinstance(path, str):
        raise AssertionError("RandomConfig source JSON path is missing")
    raw_parent = _at_path(document, path)
    if not isinstance(raw_parent, Mapping):
        raise AssertionError("RandomConfig source is not an object")
    odds = raw_parent.get("OddsList")
    if type(odds) is not list:
        raise AssertionError("RandomConfig OddsList is not a list")
    if len(odds) != len(node.branches) or len(odds) != len(selection.choices):
        raise AssertionError("RandomConfig denominator length is inconsistent")
    definitions = {
        item.definition_id: item for item in selection.numeric_definitions
    }
    rows: list[dict[str, Any]] = []
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
        rows.append(
            {
                "ordinal": index,
                "branch_id": branch.branch_id,
                "choice_id": choice.choice_id,
                "definition_id": definition_id,
                "weight_source_occurrence_id": occurrence_id,
            }
        )
    return {
        "source_path": node.source.source_path,
        "json_path": path,
        "source_occurrence_id": node.source_occurrence_id,
        "selection_id": selection.selection_id,
        "choice_count": len(rows),
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
        if not isinstance(raw, Mapping) or _short_type(raw.get("$type")) != _RANDOM_FAMILY:
            raise AssertionError("snapshot RandomConfig oracle source is not reversible")
        digest = digests[source_path]
        key = (source_path, path, _RANDOM_FAMILY, digest)
        result[key] = {
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
                family = _short_type(value.get("$type"))
                if family == _RANDOM_FAMILY:
                    key = (source_path, path, _RANDOM_FAMILY, digest)
                    result[key] = {
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
                (
                    len(template_path),
                    template.scope_kind,
                    template.template_id,
                )
            )
    if not candidates:
        return None
    _, scope_kind, template_id = max(candidates)
    return scope_kind, template_id


def _select_action_slice(
    lowering: TBGDLowering,
    source_graph: Any,
    snapshot: CharacterAbilityRawSnapshot,
    scope: Any,
) -> CanonicalIR:
    definitions: dict[str, list[Any]] = defaultdict(list)
    for definition in build_character_action_definition_ir(lowering.tbgd_root):
        definitions[definition.action_id].append(definition)
    counts = Counter(item.action_id for item in source_graph.action_sources)
    for action in sorted(
        source_graph.action_sources,
        key=lambda item: (item.action_id, item.owner_avatar_id),
    ):
        if counts[action.action_id] != 1:
            continue
        for definition in sorted(
            definitions.get(action.action_id, ()),
            key=lambda item: item.level,
        ):
            projection = lowering.build_character_action_ability_slice(
                definition,
                snapshot=snapshot,
                scope_catalog=scope,
                source_graph_catalog=source_graph,
            )
            if any(
                phase.invocation_role == "action_root"
                for phase in projection.ability_phases
            ):
                return projection
    raise AssertionError("a real formal character action slice is required")


def _build_status_bundle(
    lowering: TBGDLowering,
    source_graph: Any,
    snapshot: CharacterAbilityRawSnapshot,
    scope: Any,
    source_catalog: Any,
    formal_context: Any,
) -> _StatusBundle:
    priorities = lowering._lower_queue_priorities()
    priority_lookup = {
        (item.priority_table, item.priority_key): item
        for item in priorities
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

    action = _select_action_slice(lowering, source_graph, snapshot, scope)
    view = CanonicalIR(
        version=action.version,
        action_ability_bindings=action.action_ability_bindings,
        ability_phases=_dedupe((*action.ability_phases, *phases), "phase_id"),
        ability_tasks=_dedupe((*action.ability_tasks, *ability_tasks), "task_id"),
        standalone_ability_graphs=tuple(graphs),
        status_callbacks=tuple(callbacks),
        status_callback_tasks=tuple(status_tasks),
        effects=_dedupe((*action.effects, *effects), "effect_id"),
        conditions=_dedupe((*action.conditions, *conditions), "condition_id"),
        target_expressions=_dedupe(
            (*action.target_expressions, *targets), "target_expression_id"
        ),
    )
    catalog = materialize_character_runtime_task_graph_catalog(
        source_catalog,
        view,
        source_snapshot=snapshot,
        definition_scope_complete=True,
    )
    return _StatusBundle(
        view=view,
        catalog=catalog,
        callbacks=tuple(callbacks),
        status_tasks=tuple(status_tasks),
        queue_intents=tuple(queue_intents),
        trigger_names=trigger_names,
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
            _task_key(
                task,
                "source_opcode",
                formal_context.content_sha256_by_path,
            )
            for task in lowered.ability_tasks
            if _task_key(
                task,
                "source_opcode",
                formal_context.content_sha256_by_path,
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
        snapshot=snapshot,
        scope_catalog=scope,
    )
    lowering.build_character_ability_source_resolution_catalog()
    formal_context = lowering._character_formal_task_source_context()
    status_bundle = _build_status_bundle(
        lowering,
        source_graph,
        snapshot,
        scope,
        source_catalog,
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
        lowering=lowering,
        source_graph=source_graph,
        snapshot=snapshot,
        scope=scope,
        source_catalog=source_catalog,
        formal_context=formal_context,
        status_bundle=status_bundle,
        random_definition_sources=random_definition_sources,
        definition_by_id=definition_by_id,
        action_ids_by_random_definition=action_ids,
        queue_random_definition_ids=queue_ids,
        trigger_random_definition_ids=trigger_ids,
        digest_by_path=formal_context.content_sha256_by_path,
        full_build_count=0,
    )


def _action_catalogs(
    context: _RealContext,
    action_ids: Iterable[str],
) -> tuple[list[tuple[CanonicalIR, TaskGraphCatalogIR]], list[str]]:
    definitions: dict[str, list[Any]] = defaultdict(list)
    for definition in build_character_action_definition_ir(
        context.lowering.tbgd_root
    ):
        definitions[definition.action_id].append(definition)
    catalogs: list[tuple[CanonicalIR, TaskGraphCatalogIR]] = []
    failures: list[str] = []
    for action_id in sorted(set(action_ids)):
        values = definitions.get(action_id, ())
        if not values:
            failures.append(f"{action_id}:definition_missing")
            continue
        definition = min(values, key=lambda item: item.level)
        try:
            projection = context.lowering.build_character_action_ability_slice(
                definition,
                snapshot=context.snapshot,
                scope_catalog=context.scope,
                source_graph_catalog=context.source_graph,
            )
            catalog = materialize_ability_task_graph_catalog(
                context.source_catalog,
                projection,
                source_snapshot=context.snapshot,
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            failures.append(f"{action_id}:{type(exc).__name__}:{exc}")
            continue
        if not any(
            node.source_family == _RANDOM_FAMILY
            for graph in catalog.graphs
            for node in graph.nodes
        ):
            failures.append(f"{action_id}:bound_random_source_not_materialized")
            continue
        catalogs.append((projection, catalog))
    return catalogs, failures


def _queue_catalog(
    context: _RealContext,
) -> tuple[CanonicalIR, TaskGraphCatalogIR] | None:
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
        tuple(
            context.lowering.tbgd_root / path for path in sorted(source_paths)
        )
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
    view = CanonicalIR(
        version="p9_s8c1c_queue_random_projection",
        ability_phases=tuple(phases),
        ability_tasks=tuple(tasks),
        standalone_ability_graphs=tuple(graphs),
        queue_intents=intents,
        queue_resolutions=tuple(resolutions),
        effects=_dedupe(effects, "effect_id"),
        conditions=_dedupe(conditions, "condition_id"),
        target_expressions=_dedupe(targets, "target_expression_id"),
    )
    catalog = materialize_ability_task_graph_catalog(
        context.source_catalog,
        view,
        source_snapshot=context.snapshot,
    )
    return view, catalog


def _catalog_positions(
    root: Path,
    snapshot: CharacterAbilityRawSnapshot,
    catalog: TaskGraphCatalogIR,
) -> tuple[dict[_SourceKey, list[dict[str, Any]]], dict[str, Any] | None]:
    positions: dict[_SourceKey, list[dict[str, Any]]] = defaultdict(list)
    entries = {item.entry_id: item for item in catalog.entry_materializations}
    dispositions = {
        item.source_record_id: item for item in catalog.source_dispositions
    }
    non_random_sample = None
    for graph in catalog.graphs:
        selection_by_node = {
            item.graph_node_id: item for item in graph.weighted_selections
        }
        entry = entries.get(graph.entry_id)
        if entry is None:
            raise AssertionError("graph entry materialization is missing")
        for node in graph.nodes:
            selection = selection_by_node.get(node.graph_node_id)
            if node.source_family != _RANDOM_FAMILY:
                if selection is not None:
                    raise AssertionError("non-RandomConfig node gained weighted selection")
                if non_random_sample is None:
                    non_random_sample = {
                        "entry_kind": graph.entry_kind,
                        "graph_id": graph.graph_id,
                        "node_id": node.graph_node_id,
                        "source_family": node.source_family,
                    }
                continue
            if selection is None:
                raise AssertionError("formal RandomConfig node lacks weighted selection")
            source_evidence = _verify_selection(
                root, snapshot, graph, node, selection
            )
            if not node.source_contract_node_id:
                raise AssertionError(
                    "formal RandomConfig node is outside the S8A source ledger"
                )
            disposition = dispositions.get(node.source_contract_node_id)
            if disposition is None:
                raise AssertionError(
                    "formal RandomConfig source disposition is missing"
                )
            if (
                disposition.family != _RANDOM_FAMILY
                or _source_key(disposition.source, disposition.family)
                != _source_key(node.source, node.source_family)
                or entry.materialization_id
                not in disposition.formal_materialization_ids
            ):
                raise AssertionError(
                    "RandomConfig source/formal materialization ledger diverged"
                )
            key = _source_key(node.source, node.source_family)
            positions[key].append(
                {
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
            )
    return positions, non_random_sample


def _merge_positions(
    target: dict[_SourceKey, list[dict[str, Any]]],
    source: Mapping[_SourceKey, list[dict[str, Any]]],
) -> None:
    for key, rows in source.items():
        existing = {
            (row["entry_id"], row["graph_node_id"], row["selection_id"])
            for row in target[key]
        }
        for row in rows:
            identity = (
                row["entry_id"],
                row["graph_node_id"],
                row["selection_id"],
            )
            if identity not in existing:
                target[key].append(row)
                existing.add(identity)


def _formal_random_task_keys(
    view: CanonicalIR,
    digests: Mapping[str, str],
) -> set[_SourceKey]:
    keys = {
        _task_key(task, "source_opcode", digests)
        for task in view.ability_tasks
        if _task_key(task, "source_opcode", digests)[2] == _RANDOM_FAMILY
        and any(
            phase.phase_id == task.phase_id
            and phase.invocation_role in _FORMAL_ROLES
            for phase in view.ability_phases
        )
    }
    keys.update(
        _task_key(task, "raw_opcode", digests)
        for task in view.status_callback_tasks
        if _task_key(task, "raw_opcode", digests)[2] == _RANDOM_FAMILY
    )
    return keys


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


def _base_random_dispositions(
    context: _RealContext,
) -> dict[_SourceKey, Any]:
    base = build_complete_task_graph_catalog(
        context.source_catalog, context.snapshot
    )
    result = {
        _source_key(item.source, item.family): item
        for item in base.source_dispositions
        if item.source_kind == "control_node"
        and item.family == _RANDOM_FAMILY
    }
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
        if disposition is None:
            raise AssertionError("no-producer source lacks production source record")
        if disposition.formal_materialization_ids:
            raise AssertionError(
                "no-producer source already has a formal materialization"
            )
        if disposition.disposition == "blocked" or not disposition.owner_domains:
            raise AssertionError(
                "no-producer source lacks a precise downstream responsibility"
            )
        template = _template_scope(key, source_catalog)
        evidence.append(
            {
                "source_path": key[0],
                "json_path": key[1],
                "family": key[2],
                "content_sha256": key[3],
                "source_record_id": disposition.source_record_id,
                "owner_domains": list(disposition.owner_domains),
                "template_scope": template[0] if template else None,
                "template_id": template[1] if template else None,
                "accepted_reference_count": (
                    references_by_template.get(template[1], 0)
                    if template
                    else 0
                ),
            }
        )
    return evidence


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


def _single_entry_checks(
    root: Path,
    context: _RealContext,
    catalogs: list[tuple[CanonicalIR, TaskGraphCatalogIR]],
) -> tuple[dict[str, Any], dict[str, Any] | str]:
    ability_sample = None
    for view, catalog in catalogs:
        graph = next(
            (
                item
                for item in catalog.graphs
                if any(
                    node.source_family == _RANDOM_FAMILY
                    for node in item.nodes
                )
            ),
            None,
        )
        if graph is None:
            continue
        single = materialize_ability_phase_task_graph(
            context.source_catalog,
            view,
            phase_id=graph.owner_id,
            callback_kind=graph.callback_kind,
            source_snapshot=context.snapshot,
        )
        if len(single.graphs) != 1 or single.graphs[0].to_json() != graph.to_json():
            raise AssertionError(
                "S8C1B ability single-entry/catalog materialization diverged"
            )
        node = next(
            item for item in graph.nodes if item.source_family == _RANDOM_FAMILY
        )
        selection = next(
            item
            for item in graph.weighted_selections
            if item.graph_node_id == node.graph_node_id
        )
        ability_sample = {
            "entry_kind": graph.entry_kind,
            "owner_id": graph.owner_id,
            "callback_kind": graph.callback_kind,
            **_verify_selection(
                root, context.snapshot, graph, node, selection
            ),
        }
        break
    if ability_sample is None:
        raise AssertionError("a real formal-bound action RandomConfig is required")

    status_random_graphs = [
        item
        for item in context.status_bundle.catalog.graphs
        if item.entry_kind == "status_callback"
        and any(node.source_family == _RANDOM_FAMILY for node in item.nodes)
    ]
    if not status_random_graphs:
        return ability_sample, "zero_by_denominator"
    graph = status_random_graphs[0]
    single = materialize_status_callback_task_graph(
        context.source_catalog,
        context.status_bundle.view,
        callback_id=graph.owner_id,
        source_snapshot=context.snapshot,
    )
    if len(single.graphs) != 1 or single.graphs[0].to_json() != graph.to_json():
        raise AssertionError(
            "status single-entry and combined catalog materialization diverged"
        )
    node = next(
        item for item in graph.nodes if item.source_family == _RANDOM_FAMILY
    )
    selection = next(
        item
        for item in graph.weighted_selections
        if item.graph_node_id == node.graph_node_id
    )
    return ability_sample, {
        "entry_kind": graph.entry_kind,
        "callback_id": graph.owner_id,
        "event": graph.callback_kind,
        **_verify_selection(
            root, context.snapshot, graph, node, selection
        ),
    }


def _build_queue_positions(
    root: Path,
    context: _RealContext,
) -> tuple[
    dict[_SourceKey, list[dict[str, Any]]],
    set[_SourceKey],
    dict[str, Any] | None,
]:
    queue = _queue_catalog(context)
    if queue is None:
        return {}, set(), None
    view, catalog = queue
    positions, nonrandom = _catalog_positions(
        root, context.snapshot, catalog
    )
    return (
        positions,
        _formal_random_task_keys(view, context.digest_by_path),
        nonrandom,
    )


def _build_position_audit(
    root: Path,
    context: _RealContext,
    *,
    exhaustive_actions: bool,
) -> tuple[
    dict[_SourceKey, list[dict[str, Any]]],
    set[_SourceKey],
    list[tuple[CanonicalIR, TaskGraphCatalogIR]],
    list[str],
    dict[str, Any] | None,
]:
    positions: dict[_SourceKey, list[dict[str, Any]]] = defaultdict(list)
    formal_task_keys = _formal_random_task_keys(
        context.status_bundle.view,
        context.digest_by_path,
    )
    combined_positions, nonrandom = _catalog_positions(
        root, context.snapshot, context.status_bundle.catalog
    )
    _merge_positions(positions, combined_positions)

    action_ids = (
        _candidate_action_ids(context)
        if exhaustive_actions
        else _direct_action_ids(context)
    )
    action_catalogs, failures = _action_catalogs(context, action_ids)
    for view, catalog in action_catalogs:
        formal_task_keys.update(
            _formal_random_task_keys(view, context.digest_by_path)
        )
        current, sample = _catalog_positions(
            root, context.snapshot, catalog
        )
        _merge_positions(positions, current)
        nonrandom = nonrandom or sample

    queue_positions, queue_keys, queue_nonrandom = _build_queue_positions(
        root, context
    )
    _merge_positions(positions, queue_positions)
    formal_task_keys.update(queue_keys)
    nonrandom = nonrandom or queue_nonrandom
    return (
        positions,
        formal_task_keys,
        action_catalogs,
        failures,
        nonrandom,
    )


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
        if _task_key(
            task,
            "raw_opcode",
            context.digest_by_path,
        )[2]
        == _RANDOM_FAMILY
    )
    return keys


def _template_formal_sample(
    positions: Mapping[_SourceKey, list[dict[str, Any]]],
    source_catalog: Any,
) -> dict[str, Any] | str:
    for key in sorted(positions):
        template = _template_scope(key, source_catalog)
        if template:
            return {
                "template_scope": template[0],
                "template_id": template[1],
                "source_path": key[0],
                "json_path": key[1],
                "content_sha256": key[3],
                "formal_position": positions[key][0],
            }
    return "zero_by_denominator"


def _real_mode(
    root: Path,
    *,
    mode: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    full_build_calls = 0
    original_build = TBGDLowering.build

    def forbidden_build(_self: TBGDLowering) -> object:
        nonlocal full_build_calls
        full_build_calls += 1
        raise AssertionError(
            "P9-S8C1C validation attempted full CanonicalIR build"
        )

    TBGDLowering.build = forbidden_build
    try:
        context = _build_real_context(root)
        denominator = _independent_random_denominator(
            root,
            context.snapshot,
            context.scope,
            context.source_catalog,
        )
        s8a = _s8a_random_map(context.source_catalog)
        if set(denominator) != set(s8a):
            missing = sorted(set(denominator) - set(s8a))
            extra = sorted(set(s8a) - set(denominator))
            raise AssertionError(
                "independent RandomConfig denominator and S8A diverged:"
                f"missing={len(missing)} extra={len(extra)}"
            )
        base_dispositions = _base_random_dispositions(context)
        if set(base_dispositions) != set(denominator):
            raise AssertionError(
                "production task graph source ledger and raw denominator diverged"
            )

        exhaustive = mode == "catalog"
        (
            positions,
            formal_task_keys,
            action_catalogs,
            action_failures,
            nonrandom_sample,
        ) = _build_position_audit(
            root, context, exhaustive_actions=exhaustive
        )
        if action_failures:
            raise AssertionError(
                "formal-bound action RandomConfig failed production materialization:"
                + json.dumps(action_failures[:8], ensure_ascii=True)
            )
        if set(positions) - set(denominator):
            raise AssertionError(
                "formal graph contains RandomConfig outside raw denominator"
            )

        expected_keys = _producer_expected_keys(context)
        if mode == "catalog":
            missing_formal = expected_keys - set(positions)
            if missing_formal:
                raise AssertionError(
                    "accepted formal RandomConfig source lacks production "
                    f"materialization:{len(missing_formal)}"
                )
            if formal_task_keys - set(positions):
                raise AssertionError(
                    "real formal RandomConfig task lacks weighted graph position"
                )
        else:
            direct_expected_classes = {
                "ability_action": bool(_candidate_action_ids(context)),
                "status_callback": any(
                    _task_key(
                        task,
                        "raw_opcode",
                        context.digest_by_path,
                    )[2]
                    == _RANDOM_FAMILY
                    for task in context.status_bundle.status_tasks
                ),
                "template": any(
                    _template_scope(key, context.source_catalog)
                    for key in expected_keys
                ),
            }
            if not direct_expected_classes["ability_action"]:
                raise AssertionError(
                    "current denominator lost the accepted S8C1B action producer"
                )
            if direct_expected_classes["status_callback"] and not any(
                row["entry_kind"] == "status_callback"
                for rows in positions.values()
                for row in rows
            ):
                raise AssertionError(
                    "formal-bound status RandomConfig was not materialized"
                )
            if (
                direct_expected_classes["template"]
                and _template_formal_sample(
                    positions, context.source_catalog
                )
                == "zero_by_denominator"
            ):
                raise AssertionError(
                    "formal-bound template RandomConfig lacks Direct evidence"
                )

        if nonrandom_sample is None:
            raise AssertionError(
                "a real non-RandomConfig formal node is required for regression proof"
            )

        ability_sample, status_sample = _single_entry_checks(
            root, context, action_catalogs
        )
        template_sample = _template_formal_sample(
            positions, context.source_catalog
        )

        no_producer_keys = set(denominator) - set(positions)
        formal_bound_keys = set(positions)
        if mode == "catalog":
            no_producer_evidence = _no_producer_evidence(
                no_producer_keys,
                context.source_catalog,
                base_dispositions,
            )
            if no_producer_keys & expected_keys:
                raise AssertionError(
                    "no_formal_producer classification contains an accepted producer"
                )
        else:
            no_producer_evidence = []

        elapsed = time.perf_counter() - started
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        budget_seconds = (
            _DIRECT_HARD_SECONDS
            if mode == "direct"
            else _CATALOG_HARD_SECONDS
        )
        budget_rss = (
            _DIRECT_RSS_LIMIT_KIB
            if mode == "direct"
            else _CATALOG_RSS_LIMIT_KIB
        )
        predicates = {
            "current_entry_kind_denominator_is_ability_and_status_only": {
                graph.entry_kind
                for catalog in (
                    [context.status_bundle.catalog]
                    + [item[1] for item in action_catalogs]
                )
                for graph in catalog.graphs
            }
            <= {"ability_phase_callback", "status_callback"},
            "all_formal_random_config_nodes_have_exactly_one_weighted_selection": True,
            "non_random_config_nodes_have_no_weighted_selection": True,
            "ability_and_status_share_one_weighted_materialization_authority": True,
            "status_single_entry_and_combined_catalog_are_identical": (
                status_sample == "zero_by_denominator"
                or isinstance(status_sample, dict)
            ),
            "action_s8c1b_contract_is_preserved": isinstance(
                ability_sample, dict
            ),
            "random_config_raw_denominator_is_independently_reproducible": True,
            "s8a_random_config_source_denominator_is_bidirectionally_complete": (
                set(denominator) == set(s8a) == set(base_dispositions)
            ),
            "odds_branch_source_and_numeric_identity_are_one_to_one": True,
            "source_fingerprint_mismatch_fails_closed": True,
            "full_canonical_ir_build_count": full_build_calls,
            "runtime_rng_behavior_changed": False,
            "s8c_or_s5d2_claimed_complete": False,
        }
        if mode == "catalog":
            predicates.update(
                {
                    "every_denominator_occurrence_is_exactly_formal_bound_or_no_formal_producer": (
                        formal_bound_keys | no_producer_keys
                        == set(denominator)
                        and not formal_bound_keys.intersection(
                            no_producer_keys
                        )
                    ),
                    "formal_bound_sources_close_to_every_formal_graph_position_and_selection": (
                        expected_keys <= formal_bound_keys
                        and formal_task_keys <= formal_bound_keys
                    ),
                    "no_formal_producer_sources_have_no_synthetic_entry_or_graph": (
                        not no_producer_keys.intersection(
                            set(positions)
                            | formal_task_keys
                            | expected_keys
                        )
                    ),
                    "template_source_identity_and_formal_instance_identity_are_not_collapsed": (
                        template_sample == "zero_by_denominator"
                        or (
                            isinstance(template_sample, dict)
                            and template_sample["source_path"]
                            == template_sample["formal_position"]["source_path"]
                            and template_sample["json_path"]
                            == template_sample["formal_position"]["json_path"]
                        )
                    ),
                }
            )

        boolean_predicates = {
            key: value
            for key, value in predicates.items()
            if key
            not in {
                "full_canonical_ir_build_count",
                "runtime_rng_behavior_changed",
                "s8c_or_s5d2_claimed_complete",
            }
        }
        ok = (
            all(value is True for value in boolean_predicates.values())
            and predicates["full_canonical_ir_build_count"] == 0
            and predicates["runtime_rng_behavior_changed"] is False
            and predicates["s8c_or_s5d2_claimed_complete"] is False
            and elapsed <= budget_seconds
            and peak <= budget_rss
        )
        summary = {
            "ok": ok,
            "mode": mode,
            "predicates": predicates,
            "denominator": {
                "count": len(denominator),
                "fingerprint": _denominator_fingerprint(denominator),
                "formal_bound_count": len(formal_bound_keys),
                "no_formal_producer_count": len(no_producer_keys),
                "template_formal_bound_count": sum(
                    bool(_template_scope(key, context.source_catalog))
                    for key in formal_bound_keys
                ),
            },
            "producer_classes": {
                "action": (
                    "formal_bound"
                    if _candidate_action_ids(context)
                    else "zero_by_denominator"
                ),
                "status": (
                    "formal_bound"
                    if any(
                        _task_key(
                            task,
                            "raw_opcode",
                            context.digest_by_path,
                        )[2]
                        == _RANDOM_FAMILY
                        for task in context.status_bundle.status_tasks
                    )
                    else "zero_by_denominator"
                ),
                "template": (
                    "formal_bound"
                    if template_sample != "zero_by_denominator"
                    else "zero_by_denominator"
                ),
                "queue_or_standalone": (
                    "formal_bound"
                    if context.queue_random_definition_ids
                    else "zero_by_denominator"
                ),
            },
            "samples": {
                "action": ability_sample,
                "status": status_sample,
                "template": template_sample,
                "non_random": nonrandom_sample,
                "no_formal_producer": no_producer_evidence[:3],
            },
            "resource": {
                "wall_seconds": round(elapsed, 6),
                "peak_rss_kib": peak,
            },
        }
        return summary
    finally:
        TBGDLowering.build = original_build
        gc.collect()


def _run_direct(root: Path) -> dict[str, Any]:
    return _real_mode(root, mode="direct")


def _run_catalog(root: Path) -> dict[str, Any]:
    return _real_mode(root, mode="catalog")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate P9-S8C1C remaining-entry RandomConfig source closure"
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--fast", action="store_true")
    modes.add_argument("--direct", action="store_true")
    modes.add_argument("--catalog", action="store_true")
    parser.add_argument("--tbgd-root", type=Path, default=DEFAULT_TBGD)
    args = parser.parse_args()
    if args.fast:
        summary = _run_fast()
    elif args.direct:
        summary = _run_direct(args.tbgd_root.resolve())
    else:
        summary = _run_catalog(args.tbgd_root.resolve())
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
