from __future__ import annotations

import argparse
import json
import resource
import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from ..ir_types import IRSource
from ..rules.control_flow_contract import (
    CharacterControlFlowContractCatalog,
    ControlFlowContractIssueIR,
    ControlFlowTemplateReferenceIR,
)
from ..tbgd.character_ability_scope import (
    build_character_ability_raw_snapshot,
    build_character_ability_scope_projection,
)
from ..tbgd.character_control_flow_contracts import (
    _TemplateDraft,
    _branch_specs,
    _cycle_reference_ids,
    classify_control_flow_peer_fields,
)
from ..tbgd.lowering import TBGDLowering


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TBGD = ROOT / "turnbasedgamedata-main"
SEMANTIC_KINDS = {"combat_control_flow", "simulation_sequence"}
COMPLETED_STAGES = {"excluded", "p9_s4", "p9_s5b", "p9_s6b", "p9_s8a"}
ALLOWED_STAGES = COMPLETED_STAGES | {
    "p9_s8b",
    "p9_s8c",
    "p9_s9",
    "p9_s11",
    "p9_s13",
    "p9_s14",
}
ROLE_OWNER = {
    "conditional_loop": "p9_s8b",
    "counted_loop": "p9_s8b",
    "target_loop": "p9_s8b",
    "wrapped_task": "p9_s8b",
    "predicate_branch": "p9_s8b",
    "switch_branch": "p9_s8b",
    "ability_trigger": "p9_s8b",
    "condition_barrier": "p9_s8b",
    "projectile_sequence": "p9_s8c",
    "random_branch": "p9_s8c",
    "parallel_templates": "p9_s8c",
    "target_cursor": "p9_s8c",
    "presentation_barrier": "p9_s8c",
    "settlement_barrier": "p9_s11",
    "event_switch": "p9_s9",
    "death_barrier": "p9_s14",
    "queue_condition": "p9_s13",
}


def _at_path(document: Mapping[str, Any], path: str) -> Any:
    if not path.startswith("$"):
        raise ValueError("source path must start at root")
    value: Any = document
    cursor = 1
    while cursor < len(path):
        if path[cursor] == ".":
            cursor += 1
            end = cursor
            while end < len(path) and path[end] not in ".[":
                end += 1
            value = value[path[cursor:end]]
            cursor = end
        else:
            end = path.index("]", cursor)
            token = path[cursor + 1 : end]
            key: Any = json.loads(token) if token.startswith('"') else int(token)
            value = value[key]
            cursor = end + 1
    return value


def _short_type(value: object) -> str:
    return str(value or "").rsplit(".", 1)[-1]


def _expect_raises(action: Callable[[], object], expected: type[BaseException] = (TypeError, ValueError)) -> bool:
    try:
        action()
    except expected:
        return True
    return False


def _source_hashes(snapshot: Any) -> dict[str, str]:
    return {item.source.source_path: item.content_sha256 for item in snapshot.sources}


def _load_documents(root: Path, snapshot: Any, catalog: CharacterControlFlowContractCatalog) -> tuple[dict[str, Mapping[str, Any]], dict[str, str]]:
    documents = dict(snapshot.documents)
    hashes = _source_hashes(snapshot)
    external_paths = {
        item.source.source_path
        for item in catalog.template_definitions
        if item.source.source_path not in documents
    }
    for source_path in sorted(external_paths):
        raw_bytes = (root / source_path).read_bytes()
        document = json.loads(raw_bytes)
        if not isinstance(document, Mapping):
            raise AssertionError(f"template source is not an object:{source_path}")
        documents[source_path] = document
        hashes[source_path] = sha256(raw_bytes).hexdigest()
    return documents, hashes


def _source_scope_checks(snapshot: Any, scope: Any, catalog: CharacterControlFlowContractCatalog) -> dict[str, bool]:
    direct = tuple(
        item
        for item in scope.scope_records
        if item.materialization_role == "selected"
        and item.occurrence_kind == "typed_node"
        and item.semantic_kind in SEMANTIC_KINDS
    )
    structural = tuple(
        item
        for item in scope.scope_records
        if item.materialization_role == "selected"
        and item.occurrence_kind != "typed_node"
        and item.semantic_kind in SEMANTIC_KINDS
    )
    direct_ids = {item.record_id for item in direct}
    node_ids = {item.scope_record_id for item in catalog.nodes}
    return {
        "denominator_derived_from_complete_current_scope": bool(direct)
        and snapshot.source_catalog_complete
        and scope.fingerprint_kind == "complete"
        and not scope.source_filter
        and not scope.family_filter
        and direct_ids == node_ids
        and catalog.direct_record_count == len(direct),
        "typed_nodes_and_structural_containers_separated": bool(structural)
        and not ({item.record_id for item in structural} & node_ids),
        "direct_nodes_and_ancestor_context_separated": catalog.ancestor_context_count == 0
        and all(item.materialization_role == "selected" for item in scope.scope_records),
    }


def _node_source_checks(snapshot: Any, scope: Any, catalog: CharacterControlFlowContractCatalog) -> dict[str, bool]:
    hashes = _source_hashes(snapshot)
    records = {item.record_id: item for item in scope.scope_records}
    reversible = True
    fields_closed = True
    branches_closed = True
    for node in catalog.nodes:
        record = records[node.scope_record_id]
        node_path = str(node.source.evidence["json_path"])
        raw = _at_path(snapshot.documents[node.source.source_path], node_path)
        reversible &= (
            isinstance(raw, Mapping)
            and _short_type(raw.get("$type")) == node.family == record.family
            and node.source.source_path == record.source.source_path
            and node.source.evidence.get("content_sha256") == hashes[node.source.source_path]
            and node.source.evidence.get("scope_record_id") == record.record_id
        )
        raw_fields = {key for key in raw if key != "$type"} if isinstance(raw, Mapping) else set()
        responsibilities = {item.field_name: item for item in node.field_responsibilities}
        fields_closed &= (
            raw_fields == set(node.peer_field_names) == set(responsibilities)
            and all(
                item.responsibility != "unclassified"
                and item.owner_stage in ALLOWED_STAGES
                and item.covers_subtree
                and _at_path(snapshot.documents[item.source.source_path], str(item.source.evidence["json_path"]))
                == raw[item.field_name]
                for item in responsibilities.values()
            )
        )
        for branch in node.branches:
            try:
                _at_path(snapshot.documents[branch.source.source_path], str(branch.source.evidence["json_path"]))
                for child in branch.children:
                    child_type = _at_path(snapshot.documents[child.source.source_path], str(child.source.evidence["json_path"]))
                    branches_closed &= _short_type(child_type) == child.family
            except (KeyError, IndexError, TypeError, ValueError):
                branches_closed = False
    return {
        "every_direct_node_reverses_to_exact_raw_object": reversible,
        "every_peer_field_has_exactly_one_responsibility": fields_closed,
        "branch_children_reverse_to_exact_source": branches_closed,
        "all_control_roles_are_typed": bool(catalog.nodes)
        and all(node.control_role in ROLE_OWNER or node.control_role in {"condition_delegate", "template_include"} for node in catalog.nodes),
    }


def _template_checks(root: Path, snapshot: Any, catalog: CharacterControlFlowContractCatalog) -> dict[str, bool]:
    documents, hashes = _load_documents(root, snapshot, catalog)
    definitions = {item.template_id: item for item in catalog.template_definitions}
    definitions_ok = bool(definitions)
    parameter_count = 0
    parameters_ok = True
    for item in definitions.values():
        raw = _at_path(documents[item.source.source_path], str(item.source.evidence["json_path"]))
        tasks = raw.get("TaskList") if isinstance(raw, Mapping) else None
        expected_parameters: dict[tuple[str, str], tuple[int | None, str, str]] = {}
        dynamic_values = raw.get("DynamicValues") if isinstance(raw, Mapping) else None
        floats = dynamic_values.get("Floats") if isinstance(dynamic_values, Mapping) else {}
        if isinstance(floats, Mapping):
            for key, value in floats.items():
                read_info = value.get("ReadInfo") if isinstance(value, Mapping) else None
                if isinstance(key, str) and isinstance(read_info, Mapping):
                    expected_parameters[("dynamic_float", key)] = (
                        read_info.get("Index"),
                        read_info.get("Type"),
                        "",
                    )
        dynamic_strings = raw.get("DynamicStrings") if isinstance(raw, Mapping) else None
        if isinstance(dynamic_strings, Mapping):
            for key, value in dynamic_strings.items():
                if isinstance(key, str) and isinstance(value, str):
                    expected_parameters[("dynamic_string", key)] = (None, "", value)
        actual_parameters = {
            (parameter.parameter_kind, parameter.key): (
                parameter.index,
                parameter.read_type,
                parameter.declared_value,
            )
            for parameter in item.parameters
        }
        parameter_count += len(actual_parameters)
        parameters_ok &= expected_parameters == actual_parameters
        definitions_ok &= (
            isinstance(raw, Mapping)
            and raw.get("Name") == item.name
            and isinstance(tasks, list)
            and len(tasks) == len(item.children)
            and set(raw) <= {"Name", "TaskList", "DynamicStrings", "DynamicValues"}
            and expected_parameters == actual_parameters
            and item.source.evidence.get("content_sha256") == hashes[item.source.source_path]
        )
        definitions_ok &= all(
            _at_path(documents[parameter.source.source_path], str(parameter.source.evidence["json_path"]))
            is not None
            for parameter in item.parameters
        )
        if isinstance(tasks, list):
            definitions_ok &= all(
                _short_type(tasks[index].get("$type")) == child.family
                and child.ordinal == index
                and child.source.evidence.get("content_sha256") == hashes[item.source.source_path]
                for index, child in enumerate(item.children)
            )
    references_ok = bool(catalog.template_references)
    for item in catalog.template_references:
        raw_name = _at_path(documents[item.source.source_path], str(item.source.evidence["json_path"]))
        resolved = definitions.get(item.resolved_template_id)
        references_ok &= (
            item.coverage_status == "lowered"
            and len(item.candidate_template_ids) == 1
            and raw_name == item.name
            and resolved is not None
            and resolved.name == item.name
            and item.source.evidence.get("content_sha256") == hashes[item.source.source_path]
        )
    return {
        "template_definitions_reverse_to_source": definitions_ok,
        "template_parameter_declarations_are_typed": parameter_count > 0 and parameters_ok,
        "template_definitions_and_references_are_source_closed": references_ok
        and not catalog.issues
        and catalog.complete,
    }


def _termination_and_obligation_checks(snapshot: Any, catalog: CharacterControlFlowContractCatalog) -> dict[str, bool]:
    loop_families = {
        "LoopExecuteTaskList",
        "LoopExecuteTaskListWithInterval",
        "ConditionLoopExecuteTaskList",
        "ConditionLoopExecuteTaskListWithInterval",
        "LoopTargetList",
    }
    loop_nodes = [item for item in catalog.nodes if item.family in loop_families]
    termination_ok = bool(loop_nodes)
    obligations_ok = True
    for node in catalog.nodes:
        raw = _at_path(snapshot.documents[node.source.source_path], str(node.source.evidence["json_path"]))
        if node in loop_nodes:
            if node.family == "LoopTargetList":
                termination_ok &= node.termination.termination_kind == "finite_target_collection" and node.termination.status == "source_backed"
            elif node.family.startswith("ConditionLoop") and "MaxLoopCount" not in raw:
                termination_ok &= node.termination.termination_kind == "condition_progress_required" and node.termination.status == "runtime_proof_required"
            else:
                termination_ok &= "MaxLoopCount" in raw and node.termination.status == "source_backed"
        expected = {
            item.owner_stage
            for item in node.field_responsibilities
            if item.owner_stage not in COMPLETED_STAGES
        }
        role_owner = ROLE_OWNER.get(node.control_role)
        if role_owner and role_owner not in COMPLETED_STAGES:
            expected.add(role_owner)
        if node.termination.status == "runtime_proof_required":
            expected.add(node.termination.owner_stage)
        obligations_ok &= set(node.downstream_stages) == expected and expected <= ALLOWED_STAGES
    return {
        "loop_termination_basis_is_source_backed_or_precisely_blocked": termination_ok,
        "downstream_obligations_have_exact_stage_owner": obligations_ok,
    }


def _projectile_checks(snapshot: Any, scope: Any, catalog: CharacterControlFlowContractCatalog) -> bool:
    projectile_nodes = [item for item in catalog.nodes if item.control_role == "projectile_sequence"]
    if not projectile_nodes:
        return False
    scope_rows = tuple(scope.scope_records)
    for node in projectile_nodes:
        raw = _at_path(snapshot.documents[node.source.source_path], str(node.source.evidence["json_path"]))
        fields = {item.field_name: item for item in node.field_responsibilities}
        if any(item.responsibility == "unclassified" for item in fields.values()):
            return False
        for field in ("OnProjectileHitClientOnly", "DisplayData"):
            item = fields.get(field)
            if item is None:
                continue
            if item.responsibility != "presentation_excluded" or item.owner_stage != "excluded":
                return False
            prefix = str(item.source.evidence["json_path"])
            descendants = [
                row
                for row in scope_rows
                if row.source.source_path == node.source.source_path
                and str(row.source.evidence.get("json_path", "")).startswith(prefix)
                and row.occurrence_kind == "typed_node"
            ]
            if any(row.effective_scope != "non_gameplay" for row in descendants):
                return False
            _at_path(snapshot.documents[node.source.source_path], prefix)
        if node.family == "FireWaveProjectile" and "PerProjectileDamage" in raw:
            if fields["PerProjectileDamage"].owner_stage != "p9_s11":
                return False
    return True


def _negative_checks(catalog: CharacterControlFlowContractCatalog, lowering: TBGDLowering) -> dict[str, bool]:
    fixture_hash = "0" * 64
    responsibilities, blockers = classify_control_flow_peer_fields(
        "PredicateTaskList",
        {"$type": "RPG.GameCore.PredicateTaskList", "UnknownPeer": True},
        node_id="validation:node",
        source_path="validation_fixture",
        json_path="$.Node",
        content_sha256=fixture_hash,
    )
    _, branch_blockers = _branch_specs(
        "PredicateTaskList",
        {"SuccessTaskList": [42]},
        "$.Node",
    )
    sample_node = catalog.nodes[0]
    sample_ref = catalog.template_references[0]
    duplicate_counts = dict(catalog.family_counts)
    duplicate_counts[sample_node.family] += 1
    source_payload: dict[str, Any] = {
        "json_path": "$.Issue",
        "content_sha256": fixture_hash,
        "nested": {"value": 1},
    }
    frozen_issue = ControlFlowContractIssueIR(
        "validation_issue",
        "validation:subject",
        "p9_s8a",
        "",
        IRSource("validation_fixture", "ValidationIssue", "validation:issue", source_payload),
    )
    source_payload["nested"]["value"] = 2

    drafts = tuple(
        _TemplateDraft(
            f"template:{name}",
            name,
            "local",
            "$",
            f"$.Templates[{index}].TaskList",
            "validation_fixture",
            (),
            (),
            fixture_hash,
        )
        for index, name in enumerate(("A", "B", "C"))
    )

    def ref(owner: int, target: int, identity: str) -> ControlFlowTemplateReferenceIR:
        return ControlFlowTemplateReferenceIR(
            identity,
            f"node:{identity}",
            drafts[target].name,
            "local_document_or_shared_global",
            (drafts[target].template_id,),
            drafts[target].template_id,
            IRSource(
                "validation_fixture",
                "IncludeTaskListTemplate",
                identity,
                {
                    "json_path": f"$.Templates[{owner}].TaskList[0].Name",
                    "content_sha256": fixture_hash,
                },
            ),
            "lowered",
            "",
        )

    refs = (ref(0, 1, "ref:ab"), ref(1, 2, "ref:bc"), ref(2, 1, "ref:cb"))
    return {
        "unknown_peer_field_blocked": len(responsibilities) == 1
        and responsibilities[0].responsibility == "unclassified"
        and bool(blockers),
        "malformed_branch_child_blocked": bool(branch_blockers),
        "duplicate_source_record_rejected": _expect_raises(
            lambda: replace(
                catalog,
                nodes=(*catalog.nodes, sample_node),
                direct_record_count=catalog.direct_record_count + 1,
                family_counts=duplicate_counts,
            )
        ),
        "one_way_template_reference_rejected": _expect_raises(
            lambda: replace(
                catalog,
                nodes=tuple(
                    replace(item, template_reference_ids=()) if item.node_id == sample_ref.node_id else item
                    for item in catalog.nodes
                ),
            )
        ),
        "forged_lowered_reference_rejected": _expect_raises(
            lambda: replace(sample_ref, candidate_template_ids=(), resolved_template_id="")
        ),
        "invalid_termination_pair_rejected": _expect_raises(
            lambda: replace(sample_node.termination, status="source_backed")
        ),
        "source_evidence_is_input_isolated": frozen_issue.source.evidence["nested"]["value"] == 1,
        "cycle_detection_does_not_block_upstream_edge": _cycle_reference_ids(refs, drafts)
        == frozenset({"ref:bc", "ref:cb"}),
        "cached_wrong_source_type_rejected": _expect_raises(
            lambda: lowering.build_character_control_flow_contract_catalog(snapshot=object())
        ),
    }


def validate(root: Path, output_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    snapshot = build_character_ability_raw_snapshot(root)
    scope = build_character_ability_scope_projection(root, snapshot=snapshot)
    lowering = TBGDLowering(root)
    catalog = lowering.build_character_control_flow_contract_catalog(snapshot=snapshot, scope_catalog=scope)
    negative_matrix = _negative_checks(catalog, lowering)
    predicates = {
        **_source_scope_checks(snapshot, scope, catalog),
        **_node_source_checks(snapshot, scope, catalog),
        **_template_checks(root, snapshot, catalog),
        **_termination_and_obligation_checks(snapshot, catalog),
        "projectile_gameplay_fields_separated_from_physics": _projectile_checks(snapshot, scope, catalog),
        "unknown_or_forged_shapes_fail_closed": all(negative_matrix.values()),
        "full_canonical_ir_build_count": catalog.build_counters.get("full_canonical_ir_build_count", -1),
    }
    business_predicates = {
        key: value
        for key, value in predicates.items()
        if key != "full_canonical_ir_build_count"
    }
    ok = (
        all(value is True for value in business_predicates.values())
        and predicates["full_canonical_ir_build_count"] == 0
        and all(value is True for value in negative_matrix.values())
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "stage": "P9-S8A",
        "ok": ok,
        "predicates": predicates,
        "negative_matrix": negative_matrix,
        "manual_review_required": {"runtime_behavior_changed": "git_diff_scope_review"},
        "source_facts": {
            "snapshot_id": snapshot.snapshot_id,
            "scope_catalog_id": scope.catalog_id,
            "catalog_id": catalog.catalog_id,
            "direct_record_count": catalog.direct_record_count,
            "structural_container_count": sum(
                item.materialization_role == "selected"
                and item.occurrence_kind != "typed_node"
                and item.semantic_kind in SEMANTIC_KINDS
                for item in scope.scope_records
            ),
            "family_counts": dict(catalog.family_counts),
            "role_counts": dict(sorted(Counter(item.control_role for item in catalog.nodes).items())),
            "coverage_counts": dict(sorted(Counter(item.coverage_status for item in catalog.nodes).items())),
            "template_definition_count": len(catalog.template_definitions),
            "template_parameter_count": sum(len(item.parameters) for item in catalog.template_definitions),
            "template_reference_count": len(catalog.template_references),
            "branch_count": sum(len(item.branches) for item in catalog.nodes),
            "branch_child_count": sum(len(branch.children) for item in catalog.nodes for branch in item.branches),
            "issue_count": len(catalog.issues),
            "build_counters": dict(catalog.build_counters),
        },
        "resource": {
            "wall_seconds": round(time.perf_counter() - started, 6),
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
    }
    (output_dir / "validation_summary_p9_s8a_control_flow_source_contract.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate P9-S8A control-flow source contracts")
    parser.add_argument("--tbgd-root", type=Path, default=DEFAULT_TBGD)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = validate(args.tbgd_root.resolve(), args.output_dir.resolve())
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
