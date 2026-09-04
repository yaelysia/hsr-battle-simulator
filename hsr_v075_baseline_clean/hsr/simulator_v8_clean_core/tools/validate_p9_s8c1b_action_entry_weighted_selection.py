from __future__ import annotations

import argparse
import json
import resource
import time
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, cast

from ..ir_types import IRSource
from ..rules.ir import ActionDefinitionIR, CanonicalIR
from ..rules.task_graph import (
    TaskGraphBranchIR,
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
)
from ..tbgd.character_ability_scope import CharacterAbilityRawSnapshot
from ..tbgd.expression_lowering import lower_numeric_expression
from ..tbgd.lowering import TBGDLowering, build_character_action_definition_ir
from ..tbgd.task_graph_materializer import (
    _materialize_weighted_selection,
    materialize_ability_phase_task_graph,
    materialize_ability_task_graph_catalog,
    materialize_status_callback_task_graph,
)


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TBGD = ROOT / "turnbasedgamedata-main"
_FAST_HARD_SECONDS = 30.0
_DIRECT_HARD_SECONDS = 120.0
_DIRECT_DISCOVERY_GUARD_SECONDS = 80.0


@dataclass(frozen=True)
class _FixtureSnapshot:
    source_bytes: Mapping[str, bytes]


def _expect_rejected(action: Callable[[], object], subject: str) -> None:
    try:
        action()
    except (TypeError, ValueError, RuntimeError):
        return
    raise AssertionError(f"{subject} was accepted")


def _fixture_source(raw_parent: object) -> tuple[_FixtureSnapshot, IRSource]:
    payload = json.dumps({"Task": raw_parent}, sort_keys=True, separators=(",", ":")).encode()
    source = IRSource(
        "validation_fixture/p9_s8c1b.json",
        "RandomConfig",
        "fixture_random_config",
        {
            "json_path": "$.Task",
            "content_sha256": sha256(payload).hexdigest(),
            "source_opcode": "RandomConfig",
            "task_path": "OnStart[0]",
        },
    )
    return _FixtureSnapshot({source.source_path: payload}), source


def _fixture_branches(graph_node_id: str, source: IRSource) -> tuple[TaskGraphBranchIR, ...]:
    return tuple(
        TaskGraphBranchIR(
            branch_id=task_graph_branch_id(
                graph_node_id, "config", ordinal, f"choice_{ordinal}", ()
            ),
            graph_node_id=graph_node_id,
            branch_kind="config",
            ordinal=ordinal,
            label=f"choice_{ordinal}",
            child_node_ids=(),
            source=source,
        )
        for ordinal in range(2)
    )


def _fixture_graph() -> tuple[TaskGraphIR, TaskGraphWeightedSelectionIR]:
    snapshot, source = _fixture_source(
        {"$type": "RandomConfig", "OddsList": [2, 3], "ConfigList": [{}, {}]}
    )
    occurrence_id = task_graph_source_occurrence_id(source, "RandomConfig")
    entry_id = task_graph_entry_id(
        "ability_phase_callback", "fixture:phase", "OnStart"
    )
    graph_id = task_graph_id("fixture:source_catalog", entry_id, source.evidence["content_sha256"])
    node_id = task_graph_node_id(graph_id, "fixture:task", occurrence_id)
    branches = _fixture_branches(node_id, source)
    selection = _materialize_weighted_selection(
        cast(Any, snapshot), node_id, source, occurrence_id, branches
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
        entry_kind="ability_phase_callback",
        owner_id="fixture:phase",
        callback_kind="OnStart",
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


def _helper_rejects_bad_odds(raw_parent: object) -> None:
    snapshot, source = _fixture_source(raw_parent)
    occurrence_id = task_graph_source_occurrence_id(source, "RandomConfig")
    entry_id = task_graph_entry_id(
        "ability_phase_callback", "fixture:phase", "OnStart"
    )
    graph_id = task_graph_id("fixture:source_catalog", entry_id, source.evidence["content_sha256"])
    node_id = task_graph_node_id(graph_id, "fixture:task", occurrence_id)
    _materialize_weighted_selection(
        cast(Any, snapshot),
        node_id,
        source,
        occurrence_id,
        _fixture_branches(node_id, source),
    )


def _run_fast() -> dict[str, Any]:
    started = time.perf_counter()
    graph, selection = _fixture_graph()
    payload = graph.to_json()
    if TaskGraphIR.from_json(payload).to_json() != payload:
        raise AssertionError("TaskGraphIR weighted attachment round-trip is unstable")

    _expect_rejected(
        lambda: _helper_rejects_bad_odds(
            {"$type": "RandomConfig", "OddsList": "invalid", "ConfigList": [{}, {}]}
        ),
        "invalid OddsList type",
    )
    _expect_rejected(
        lambda: _helper_rejects_bad_odds(
            {"$type": "RandomConfig", "OddsList": [1], "ConfigList": [{}, {}]}
        ),
        "OddsList/branch length mismatch",
    )

    first = selection.choices[0]
    wrong_branch = graph.nodes[0].branches[1].branch_id
    wrong_choice = replace(
        first,
        branch_id=wrong_branch,
        choice_id=task_graph_weighted_choice_id(
            first.graph_node_id,
            first.ordinal,
            wrong_branch,
            first.weight_definition_id,
        ),
    )
    wrong_selection = replace(
        selection,
        choices=(wrong_choice, *selection.choices[1:]),
    )
    _expect_rejected(
        lambda: replace(graph, weighted_selections=(wrong_selection,)),
        "weighted selection pointing at the wrong branch",
    )

    forged = selection.to_json()
    forged["choices"][0]["source"]["evidence"]["content_sha256"] = "f" * 64
    _expect_rejected(
        lambda: TaskGraphWeightedSelectionIR.from_json(forged),
        "forged weighted choice source identity",
    )

    unknown = graph.to_json()
    unknown["unexpected"] = True
    _expect_rejected(
        lambda: TaskGraphIR.from_json(unknown),
        "TaskGraphIR strict codec unknown field",
    )

    if (
        graph.nodes[0].materialization_status != "deferred"
        or graph.nodes[0].owner_domains != ("hit_random_sequence",)
    ):
        raise AssertionError("fixture RandomConfig runtime ownership changed")

    elapsed = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "ok": elapsed <= _FAST_HARD_SECONDS and peak <= 512 * 1024,
        "mode": "fast",
        "cases": 6,
        "predicates": {
            "weighted_attachment_and_codec": True,
            "bad_odds_fail_closed": True,
            "wrong_branch_fail_closed": True,
            "forged_source_identity_fail_closed": True,
            "unknown_field_fail_closed": True,
            "runtime_behavior_changed": False,
        },
        "resource": {
            "wall_seconds": round(elapsed, 6),
            "peak_rss_kib": peak,
        },
    }


def _family(task: Any) -> str:
    value = task.source.evidence.get("source_opcode")
    return value if isinstance(value, str) and value else task.opcode


def _candidate_action_ids(source_graph: Any, source_catalog: Any) -> tuple[str, ...]:
    definitions = {item.definition_id: item for item in source_graph.definitions}
    actions = {item.action_source_id: item for item in source_graph.action_sources}
    random_by_path: dict[str, list[Any]] = defaultdict(list)
    for node in source_catalog.nodes:
        if node.family == "RandomConfig" and node.coverage_status != "blocked":
            random_by_path[node.source.source_path].append(node)

    scores: dict[str, int] = {}
    for binding in source_graph.bindings:
        definition = definitions.get(binding.ability_definition_id)
        action = actions.get(binding.action_source_id)
        if definition is None or action is None or action.action_kind == "maze":
            continue
        prefix = definition.source.evidence.get("json_path")
        if not isinstance(prefix, str) or not prefix:
            continue
        hits = sum(
            str(node.source.evidence.get("json_path") or "").startswith(prefix)
            for node in random_by_path.get(definition.source.source_path, ())
        )
        if hits:
            scores[action.action_id] = max(scores.get(action.action_id, 0), hits)
    return tuple(sorted(scores, key=lambda value: (-scores[value], value)))


def _document_value(document: Mapping[str, Any], json_path: str) -> object:
    if not json_path.startswith("$"):
        raise AssertionError("source json path is not absolute")
    current: object = document
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
                raise AssertionError(f"source json path is missing:{json_path}")
            current = current[key]
            cursor = end
            continue
        if marker == "[":
            end = json_path.find("]", cursor + 1)
            raw_index = json_path[cursor + 1 : end] if end >= 0 else ""
            if (
                end < 0
                or not raw_index.isdigit()
                or type(current) is not list
                or int(raw_index) >= len(current)
            ):
                raise AssertionError(f"source json path is invalid:{json_path}")
            current = current[int(raw_index)]
            cursor = end + 1
            continue
        raise AssertionError(f"source json path is invalid:{json_path}")
    return current


def _verify_selection(snapshot: CharacterAbilityRawSnapshot, graph: TaskGraphIR) -> dict[str, Any]:
    if not graph.weighted_selections:
        raise AssertionError("representative graph does not contain a weighted selection")
    selection = graph.weighted_selections[0]
    node = next(
        (item for item in graph.nodes if item.graph_node_id == selection.graph_node_id),
        None,
    )
    if node is None or node.source_family != "RandomConfig":
        raise AssertionError("weighted selection is not attached to RandomConfig")
    if (
        node.materialization_status != "deferred"
        or node.owner_domains != ("hit_random_sequence",)
    ):
        raise AssertionError("RandomConfig node no longer defers to hit_random_sequence")
    path = node.source.evidence.get("json_path")
    if not isinstance(path, str):
        raise AssertionError("RandomConfig source path is missing")
    document = snapshot.documents.get(node.source.source_path)
    if not isinstance(document, Mapping):
        raise AssertionError("RandomConfig signed snapshot document is missing")
    raw_parent = _document_value(document, path)
    if not isinstance(raw_parent, Mapping) or type(raw_parent.get("OddsList")) is not list:
        raise AssertionError("RandomConfig raw OddsList is invalid")
    odds = cast(list[object], raw_parent["OddsList"])
    if len(odds) != len(node.branches) or len(odds) != len(selection.choices):
        raise AssertionError("RandomConfig branch/weight denominator mismatch")

    rows: list[dict[str, Any]] = []
    definitions = {item.definition_id: item for item in selection.numeric_definitions}
    for index, (raw_weight, choice, branch) in enumerate(
        zip(odds, selection.choices, node.branches, strict=True)
    ):
        evidence = dict(node.source.evidence)
        evidence["json_path"] = f"{path}.OddsList[{index}]"
        child_source = IRSource(
            node.source.source_path,
            node.source.raw_type,
            node.source.raw_id,
            evidence,
        )
        occurrence_id = task_graph_source_occurrence_id(child_source, "RandomConfig")
        expression = lower_numeric_expression(raw_weight)
        definition_id = task_graph_numeric_id(occurrence_id, expression)
        expected_choice_id = task_graph_weighted_choice_id(
            node.graph_node_id, index, branch.branch_id, definition_id
        )
        definition = definitions.get(definition_id)
        if (
            choice.ordinal != index
            or choice.branch_id != branch.branch_id
            or choice.weight_source_occurrence_id != occurrence_id
            or choice.weight_definition_id != definition_id
            or choice.choice_id != expected_choice_id
            or choice.source != child_source
            or definition is None
            or definition.source_occurrence_id != occurrence_id
            or definition.expression != expression
            or definition.source != child_source
        ):
            raise AssertionError(f"weighted choice closure failed at ordinal {index}")
        rows.append(
            {
                "ordinal": index,
                "branch_id": branch.branch_id,
                "weight_source_occurrence_id": occurrence_id,
                "definition_id": definition_id,
                "choice_id": choice.choice_id,
                "json_path": child_source.evidence["json_path"],
            }
        )
    return {
        "entry_kind": graph.entry_kind,
        "phase_id": graph.owner_id,
        "callback_kind": graph.callback_kind,
        "source_path": node.source.source_path,
        "json_path": path,
        "source_occurrence_id": node.source_occurrence_id,
        "selection_id": selection.selection_id,
        "choices": rows,
    }


def _build_slice(
    lowering: TBGDLowering,
    definition: ActionDefinitionIR,
    snapshot: CharacterAbilityRawSnapshot,
    scope: Any,
    source_graph: Any,
) -> CanonicalIR:
    return lowering.build_character_action_ability_slice(
        definition,
        snapshot=snapshot,
        scope_catalog=scope,
        source_graph_catalog=source_graph,
    )


def _probe_nonrandom(
    source_catalog: Any,
    snapshot: CharacterAbilityRawSnapshot,
    canonical: CanonicalIR,
    ability_catalog: Any,
) -> dict[str, Any] | None:
    for graph in ability_catalog.graphs:
        if any(node.source_family == "RandomConfig" for node in graph.nodes):
            continue
        single = materialize_ability_phase_task_graph(
            source_catalog,
            canonical,
            phase_id=graph.owner_id,
            callback_kind=graph.callback_kind,
            source_snapshot=snapshot,
        )
        if len(single.graphs) != 1 or single.graphs[0].to_json() != graph.to_json():
            raise AssertionError("non-RandomConfig single/catalog action graph diverged")
        if single.graphs[0].weighted_selections:
            raise AssertionError("non-RandomConfig action graph gained weighted selections")
        return {
            "phase_id": graph.owner_id,
            "callback_kind": graph.callback_kind,
            "graph_id": graph.graph_id,
        }
    return None


def _probe_status(
    source_catalog: Any,
    snapshot: CharacterAbilityRawSnapshot,
    canonical: CanonicalIR,
) -> dict[str, Any] | None:
    task_callbacks = {item.callback_id for item in canonical.status_callback_tasks}
    root_paths = {item.source.source_path for item in snapshot.sources}
    for callback in sorted(canonical.status_callbacks, key=lambda item: item.callback_id):
        if callback.callback_id not in task_callbacks or callback.source.source_path not in root_paths:
            continue
        try:
            first = materialize_status_callback_task_graph(
                source_catalog,
                canonical,
                callback_id=callback.callback_id,
                source_snapshot=snapshot,
            )
            second = materialize_status_callback_task_graph(
                source_catalog,
                canonical,
                callback_id=callback.callback_id,
                source_snapshot=snapshot,
            )
        except (TypeError, ValueError):
            continue
        if first.to_json() != second.to_json():
            raise AssertionError("status materialization is not stable")
        if any(graph.weighted_selections for graph in first.graphs):
            raise AssertionError("status callback gained S8C1B weighted selections")
        if first.entry_materializations and first.graphs:
            return {
                "callback_id": callback.callback_id,
                "event": callback.event,
                "graph_id": first.graphs[0].graph_id,
            }
    return None


def _run_direct(root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    lowering = TBGDLowering(root)
    original_build = TBGDLowering.build

    def forbidden_full_build(_self: TBGDLowering) -> CanonicalIR:
        raise AssertionError("S8C1B Direct attempted full CanonicalIR build")

    TBGDLowering.build = forbidden_full_build
    try:
        source_graph = lowering.build_character_ability_source_graph_catalog()
        snapshot = lowering._character_ability_raw_snapshot
        scope = lowering._character_ability_scope_catalog
        if type(snapshot) is not CharacterAbilityRawSnapshot:
            raise AssertionError("production signed CharacterAbilityRawSnapshot is unavailable")
        source_catalog = lowering.build_character_control_flow_contract_catalog(
            snapshot=snapshot,
            scope_catalog=scope,
        )
        candidate_ids = _candidate_action_ids(source_graph, source_catalog)
        if not candidate_ids:
            raise AssertionError(
                "no formal ability_phase_callback RandomConfig candidate exists"
            )
        definitions_by_action: dict[str, list[ActionDefinitionIR]] = defaultdict(list)
        for definition in build_character_action_definition_ir(root):
            definitions_by_action[definition.action_id].append(definition)

        selected: tuple[CanonicalIR, Any, TaskGraphIR] | None = None
        failures: list[str] = []
        for action_id in candidate_ids:
            if time.perf_counter() - started > _DIRECT_DISCOVERY_GUARD_SECONDS:
                raise AssertionError("Direct representative discovery reached budget guard")
            definitions = definitions_by_action.get(action_id, ())
            if not definitions:
                continue
            definition = min(definitions, key=lambda item: item.level)
            try:
                canonical = _build_slice(
                    lowering, definition, snapshot, scope, source_graph
                )
                ability_catalog = materialize_ability_task_graph_catalog(
                    source_catalog,
                    canonical,
                    source_snapshot=snapshot,
                )
            except (TypeError, ValueError) as exc:
                failures.append(f"{action_id}:{type(exc).__name__}:{exc}")
                continue
            random_keys = sorted(
                {
                    (task.phase_id, task.callback_kind)
                    for task in canonical.ability_tasks
                    if _family(task) == "RandomConfig"
                }
            )
            for phase_id, callback_kind in random_keys:
                try:
                    single = materialize_ability_phase_task_graph(
                        source_catalog,
                        canonical,
                        phase_id=phase_id,
                        callback_kind=callback_kind,
                        source_snapshot=snapshot,
                    )
                except (TypeError, ValueError) as exc:
                    failures.append(
                        f"{action_id}:{phase_id}:{callback_kind}:{type(exc).__name__}:{exc}"
                    )
                    continue
                if len(single.graphs) != 1 or not single.graphs[0].weighted_selections:
                    continue
                graph = single.graphs[0]
                catalog_graph = next(
                    (
                        item
                        for item in ability_catalog.graphs
                        if item.entry_id == graph.entry_id
                    ),
                    None,
                )
                if catalog_graph is None or catalog_graph.to_json() != graph.to_json():
                    raise AssertionError(
                        "single-entry and ability-catalog weighted materialization diverged"
                    )
                selected = canonical, ability_catalog, graph
                break
            if selected is not None:
                break

        if selected is None:
            detail = failures[-3:] if failures else ["no materialized weighted graph"]
            raise AssertionError(
                "no formal action RandomConfig representative materialized:"
                + json.dumps(detail, ensure_ascii=False)
            )

        canonical, ability_catalog, graph = selected
        source_evidence = _verify_selection(snapshot, graph)
        if (
            source_catalog.source_fingerprint != snapshot.source_fingerprint
            or graph.source_fingerprint != snapshot.source_fingerprint
        ):
            raise AssertionError("weighted graph escaped the signed snapshot fingerprint")

        nonrandom = _probe_nonrandom(
            source_catalog, snapshot, canonical, ability_catalog
        )
        status = _probe_status(source_catalog, snapshot, canonical)

        if nonrandom is None or status is None:
            fallback_ids = tuple(
                action_id
                for action_id in sorted(definitions_by_action)
                if action_id not in candidate_ids
            )[:12]
            for action_id in fallback_ids:
                if time.perf_counter() - started > _DIRECT_DISCOVERY_GUARD_SECONDS:
                    break
                definitions = definitions_by_action[action_id]
                definition = min(definitions, key=lambda item: item.level)
                try:
                    other = _build_slice(
                        lowering, definition, snapshot, scope, source_graph
                    )
                    other_catalog = materialize_ability_task_graph_catalog(
                        source_catalog,
                        other,
                        source_snapshot=snapshot,
                    )
                except (TypeError, ValueError):
                    continue
                if nonrandom is None:
                    nonrandom = _probe_nonrandom(
                        source_catalog, snapshot, other, other_catalog
                    )
                if status is None:
                    status = _probe_status(source_catalog, snapshot, other)
                if nonrandom is not None and status is not None:
                    break

        if nonrandom is None:
            raise AssertionError("no minimal non-RandomConfig action graph was found")
        if status is None:
            raise AssertionError("no minimal status callback comparison was found")
    finally:
        TBGDLowering.build = original_build

    elapsed = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "ok": elapsed <= _DIRECT_HARD_SECONDS and peak <= 1024 * 1024,
        "mode": "direct",
        "predicates": {
            "real_signed_snapshot_source": True,
            "single_and_catalog_share_materialization": True,
            "odds_definition_choice_branch_selection_closure": True,
            "non_random_action_unchanged": True,
            "status_callback_unchanged": True,
            "random_config_still_deferred": True,
            "runtime_behavior_changed": False,
            "full_canonical_ir_build_count": 0,
        },
        "source": source_evidence,
        "non_random_action": nonrandom,
        "status_callback": status,
        "resource": {
            "wall_seconds": round(elapsed, 6),
            "peak_rss_kib": peak,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate P9-S8C1B action-entry weighted selection materialization"
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--fast", action="store_true")
    modes.add_argument("--direct", action="store_true")
    parser.add_argument("--tbgd-root", type=Path, default=DEFAULT_TBGD)
    args = parser.parse_args()

    summary = _run_fast() if args.fast else _run_direct(args.tbgd_root.resolve())
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
