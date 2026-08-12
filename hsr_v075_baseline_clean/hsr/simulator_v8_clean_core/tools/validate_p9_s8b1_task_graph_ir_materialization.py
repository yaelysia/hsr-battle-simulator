from __future__ import annotations

import argparse
import json
import resource
import time
from collections import defaultdict
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from ..rules.ir import CanonicalIR
from ..rules.rulebook import RuleBook
from ..rules.task_graph import TaskGraphCatalogIR
from ..tbgd.lowering import TBGDLowering
from ..tbgd.task_graph_materializer import (
    attach_task_graph_catalog,
    materialize_ability_phase_task_graph,
    merge_task_graph_slices,
)


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TBGD = ROOT / "turnbasedgamedata-main"
MAX_VALIDATOR_LINES = 350


def _raises(action: Callable[[], object]) -> bool:
    try:
        action()
    except (TypeError, ValueError):
        return True
    return False


def _occurrence(source: Any, family: str) -> str:
    payload = json.dumps([
        source.source_path, source.evidence["json_path"], family,
        source.evidence["content_sha256"],
    ], ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return f"task_graph_source:{sha256(payload).hexdigest()}"


def _independent_source_records(source_catalog: Any) -> dict[str, tuple[str, Any]]:
    records = {
        item.node_id: (item.family, item.source) for item in source_catalog.nodes
    }
    records.update(
        (item.template_id, (item.source.raw_type, item.source))
        for item in source_catalog.template_definitions
    )
    records.update(
        (item.reference_id, (item.source.raw_type, item.source))
        for item in source_catalog.template_references
    )
    return records


def _complete_checks(source_catalog: Any, catalog: TaskGraphCatalogIR) -> dict[str, bool]:
    records = _independent_source_records(source_catalog)
    actual = {item.source_record_id: item for item in catalog.source_dispositions}
    source_closed = set(records) == set(actual) and all(
        item.family == records[record_id][0]
        and item.source == records[record_id][1]
        and item.source_occurrence_id
        == _occurrence(records[record_id][1], records[record_id][0])
        for record_id, item in actual.items()
    )
    blocked_nodes = {
        item.node_id for item in source_catalog.nodes if item.coverage_status == "blocked"
    }
    blocked_refs = {
        item.reference_id
        for item in source_catalog.template_references
        if item.coverage_status == "blocked"
    }
    return {
        "complete_s8a_denominator_has_exactly_one_materialization_disposition": (
            source_closed
            and catalog.source_record_count == len(records)
            and len(actual) == len(catalog.source_dispositions)
            and {
                item.source_record_id
                for item in catalog.source_dispositions
                if item.disposition == "blocked"
            }
            == blocked_nodes | blocked_refs
            and catalog.scope_mode == "complete_catalog"
            and not catalog.entry_materializations
            and not catalog.graphs
            and TaskGraphCatalogIR.from_json(catalog.to_json()).to_json()
            == catalog.to_json()
        )
    }


def _select_formal_slice(lowering: TBGDLowering, source_graph: Any, snapshot: Any, scope: Any,
                         source_catalog: Any) -> tuple[CanonicalIR, TaskGraphCatalogIR]:
    nodes_by_path: dict[str, list[Any]] = defaultdict(list)
    for node in source_catalog.nodes:
        nodes_by_path[node.source.source_path].append(node)
    definitions = {item.definition_id: item for item in source_graph.definitions}
    actions = {item.action_source_id: item for item in source_graph.action_sources}
    candidates: list[tuple[int, int, int, int, str, str]] = []
    for binding in source_graph.bindings:
        definition = definitions.get(binding.ability_definition_id)
        action = actions.get(binding.action_source_id)
        if definition is None or action is None:
            continue
        prefix = str(definition.source.evidence.get("json_path") or "")
        nodes = tuple(
            item for item in nodes_by_path[definition.source.source_path]
            if str(item.source.evidence.get("json_path") or "").startswith(prefix)
            and item.coverage_status != "blocked"
        )
        roles = {item.control_role for item in nodes}
        s8b = sum("p9_s8b" in item.downstream_stages for item in nodes)
        s8c = sum("p9_s8c" in item.downstream_stages for item in nodes)
        if (
            s8b and s8c and action.action_kind != "maze"
            and "predicate_branch" in roles and "ability_trigger" not in roles
            and roles.intersection({"counted_loop", "conditional_loop", "target_loop"})
        ):
            candidates.append((
                s8b, s8c, sum(bool(item.branches) for item in nodes), len(nodes),
                action.action_id, binding.ability_name,
            ))
    for selected in sorted(candidates):
        definitions_ir = lowering._lower_action_definitions(
            action_ids=frozenset({selected[4]}), entity_types=frozenset({"avatar_skill"})
        )
        canonical = lowering.build_character_action_ability_slice(
            min(definitions_ir, key=lambda item: item.level), snapshot=snapshot,
            scope_catalog=scope, source_graph_catalog=source_graph,
        )
        phases = tuple(item for item in canonical.ability_phases if item.ability_name == selected[5])
        if len(phases) != 1:
            continue
        for callback in sorted({
            item.callback_kind for item in canonical.ability_tasks
            if item.phase_id == phases[0].phase_id
        }):
            catalog = materialize_ability_phase_task_graph(
                source_catalog, canonical, phase_id=phases[0].phase_id,
                callback_kind=callback, source_snapshot=snapshot,
            )
            if catalog.entry_materializations[0].status == "blocked":
                continue
            graph = catalog.graphs[0]
            if any(item.termination_kind != "not_applicable" for item in graph.nodes) and any(
                item.materialization_status == "deferred" for item in graph.nodes
            ):
                return canonical, catalog
    raise AssertionError("no formal loop graph closes the selected source shape")


def _formal_checks(source_catalog: Any, canonical: CanonicalIR,
                   catalog: TaskGraphCatalogIR, complete: TaskGraphCatalogIR,
                   snapshot: Any) -> tuple[dict[str, bool], dict[str, Any]]:
    entry = catalog.entry_materializations[0]
    graph = catalog.graphs[0]
    deferred = tuple(node for node in graph.nodes if node.materialization_status == "deferred")
    controls = {item.node_id: item for item in source_catalog.nodes}
    numeric = {item.definition_id: item for item in graph.numeric_definitions}
    termination_closed = all(
        (
            node.termination_kind == "not_applicable"
            and not node.termination_numeric_definition_id
        )
        if not node.source_contract_node_id
        else (
            node.source_contract_node_id in controls
            and node.termination_kind
            == controls[node.source_contract_node_id].termination.termination_kind
            and node.termination_status
            == controls[node.source_contract_node_id].termination.status
            and (
                not node.termination_numeric_definition_id
                or numeric[node.termination_numeric_definition_id].expression
                == controls[node.source_contract_node_id].termination.expression
            )
        )
        for node in graph.nodes
    )
    attached = attach_task_graph_catalog(canonical, catalog)
    rules = RuleBook(attached)
    encoded = catalog.to_json()
    decoded = TaskGraphCatalogIR.from_json(encoded)
    decoded_json = decoded.to_json()
    encoded["source_dispositions"][0]["family"] = "tampered"
    deferred_node = next(node for node in deferred if "hit_random_sequence" in node.owner_domains)
    forged_node = replace(
        deferred_node, materialization_status="materialized", node_kind="leaf",
        owner_domains=("task_graph_execution",), status_reason="",
    )
    forged_nodes = tuple(
        forged_node if item.graph_node_id == forged_node.graph_node_id else item
        for item in graph.nodes
    )
    has_obligation = any(
        item.materialization_status == "deferred"
        or any(ref.resolution_status != "resolved" for ref in item.references)
        for item in forged_nodes
    )
    forged_graph = replace(
        graph, nodes=forged_nodes,
        coverage_status="lowered_with_obligation" if has_obligation else "lowered",
    )
    reference = next(
        item for node in graph.nodes for item in node.references
        if item.reference_kind in {"condition", "target", "effect", "ability"}
    )
    field_name, identity_name = {
        "condition": ("conditions", "condition_id"),
        "target": ("target_expressions", "target_expression_id"),
        "effect": ("effects", "effect_id"),
        "ability": ("standalone_ability_graphs", "standalone_ability_graph_id"),
    }[reference.reference_kind]
    broken_canonical = replace(canonical, **{
        field_name: tuple(
            item for item in getattr(canonical, field_name)
            if getattr(item, identity_name) != reference.definition_id
        )
    })
    blocked = materialize_ability_phase_task_graph(
        source_catalog, broken_canonical, phase_id=entry.owner_id,
        callback_kind=entry.callback_kind, source_snapshot=snapshot,
    )
    negatives = {
        "truncated_denominator": _raises(lambda: replace(
            catalog, source_dispositions=catalog.source_dispositions[:-1]
        )),
        "formal_slice_as_complete": _raises(lambda: replace(
            catalog, scope_mode="complete_catalog"
        )),
        "s8c_node_as_s8b": _raises(lambda: replace(catalog, graphs=(forged_graph,))),
        "tampered_nested_content": _raises(lambda: TaskGraphCatalogIR.from_json(encoded)),
        "source_snapshot_type_mismatch": _raises(lambda: materialize_ability_phase_task_graph(
            source_catalog, canonical, phase_id=entry.owner_id, callback_kind=entry.callback_kind,
            source_snapshot=object(),
        )),
        "duplicate_formal_slice": _raises(lambda: merge_task_graph_slices(complete, (catalog, catalog))),
    }
    blocked_rules = RuleBook(attach_task_graph_catalog(broken_canonical, blocked))
    predicates = {
        "source_occurrence_and_formal_materialization_identity_are_distinct": (
            entry.materialization_id not in entry.source_occurrence_ids
            and entry.formal_task_ids
            and len(entry.formal_task_ids) == len(entry.source_occurrence_ids)
        ),
        "formal_slice_cannot_masquerade_as_complete_catalog": negatives["formal_slice_as_complete"],
        "task_graph_models_are_typed_and_recursively_immutable": (
            decoded_json == catalog.to_json()
            and decoded_json != encoded
            and negatives["tampered_nested_content"]
            and termination_closed
        ),
        "graph_and_reference_conflicts_fail_closed": (
            all(negatives.values())
            and blocked.entry_materializations[0].status == "blocked"
            and not blocked.graphs
            and not any(item.formal_materialization_ids for item in blocked.source_dispositions)
            and blocked_rules.query_task_graph_entry(entry.entry_kind, entry.owner_id, entry.callback_kind).status == "blocked"
        ),
        "s8c_nodes_remain_precisely_deferred": (
            any("hit_random_sequence" in item.owner_domains for item in deferred)
            and all(item.owner_domains for item in deferred)
            and negatives["s8c_node_as_s8b"]
        ),
        "canonical_ir_round_trip_preserves_task_graphs": (
            attached.to_json()["task_graph_catalog"] == catalog.to_json()
            and decoded_json == catalog.to_json()
        ),
        "rulebook_queries_are_unique_and_type_safe": (
            rules.query_task_graph(graph.graph_id).value is graph
            and rules.query_task_graph_entry(entry.entry_kind, entry.owner_id, entry.callback_kind).value is entry
            and all(
                rules.query_task_graph_node(item.graph_node_id).value is item
                for item in graph.nodes
            )
            and RuleBook(canonical).query_task_graph(graph.graph_id).status == "blocked"
            and rules.query_task_graph("").status == "blocked"
        ),
    }
    return predicates, {"negative_matrix": negatives}


def validate(root: Path, output_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    full_build_calls = 0
    original_build = TBGDLowering.build

    def forbidden_full_build(_self: TBGDLowering) -> CanonicalIR:
        nonlocal full_build_calls
        full_build_calls += 1
        raise AssertionError("focused validation attempted full CanonicalIR lowering")

    TBGDLowering.build = forbidden_full_build
    try:
        lowering = TBGDLowering(root)
        source_graph = lowering.build_character_ability_source_graph_catalog()
        snapshot = lowering._character_ability_raw_snapshot
        scope = lowering._character_ability_scope_catalog
        source_catalog = lowering.build_character_control_flow_contract_catalog(
            snapshot=snapshot, scope_catalog=scope
        )
        complete = lowering.build_character_task_graph_catalog(source_catalog=source_catalog)
        canonical, formal = _select_formal_slice(
            lowering, source_graph, snapshot, scope, source_catalog
        )
        formal = merge_task_graph_slices(complete, (formal,))
        formal_predicates, formal_facts = _formal_checks(
            source_catalog, canonical, formal, complete, snapshot
        )
    finally:
        TBGDLowering.build = original_build
    predicates = {
        **_complete_checks(source_catalog, complete),
        **formal_predicates,
        "runtime_behavior_changed": False,
        "full_canonical_ir_build_count": full_build_calls,
    }
    elapsed = time.perf_counter() - started
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    line_count = sum(
        bool(line.strip()) for line in Path(__file__).read_text(encoding="utf-8").splitlines()
    )
    business = {key: value for key, value in predicates.items() if key not in {"runtime_behavior_changed", "full_canonical_ir_build_count"}}
    summary = {
        "ok": (
            all(value is True for value in business.values())
            and predicates["runtime_behavior_changed"] is False
            and full_build_calls == 0
            and elapsed <= 75
            and peak_rss <= 640 * 1024
            and line_count <= MAX_VALIDATOR_LINES
        ),
        "predicates": predicates,
        "manual_review_required": {"runtime_behavior_changed": "git_diff_scope_review"},
        "source_facts": {
            "source_record_count": complete.source_record_count,
            **formal_facts,
        },
        "resource": {
            "wall_seconds": round(elapsed, 6),
            "peak_rss_kib": peak_rss,
            "validator_nonblank_lines": line_count,
            "evidence_bytes": 0,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "validation_summary_p9_s8b1_task_graph_ir_materialization.json"
    for _ in range(2):
        blob = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        summary["resource"]["evidence_bytes"] = len(blob.encode("utf-8"))
    if summary["resource"]["evidence_bytes"] > 512 * 1024:
        summary["ok"] = False
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate P9-S8B1 task graph IR")
    parser.add_argument("--tbgd-root", type=Path, default=DEFAULT_TBGD)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = validate(args.tbgd_root.resolve(), args.output_dir.resolve())
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
