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

from ..rules.control_flow_contract import (
    CharacterControlFlowContractCatalog,
)
from ..tbgd.character_ability_scope import (
    build_character_ability_raw_snapshot,
    build_character_ability_scope_projection,
    character_ability_semantic_kind,
)
from ..rules.ir import character_ability_scope_record_id
from ..tbgd.character_control_flow_contracts import (
    _branch_specs,
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
    "p9_s10",
    "p9_s11",
    "p9_s12",
    "p9_s13",
    "p9_s14",
}
ROLE_OWNER = {
    "effect_continuation": "p9_s8b",
    "status_scope": "p9_s8b",
    "target_scope": "p9_s8b",
    "ordered_target_scope": "p9_s8b",
    "action_abort_continuation": "p9_s8b",
    "event_creation_continuation": "p9_s8b",
    "template_parameter_fetch": "p9_s8b",
    "conditional_loop": "p9_s8b",
    "counted_loop": "p9_s8b",
    "target_loop": "p9_s8b",
    "wrapped_task": "p9_s8b",
    "predicate_branch": "p9_s8b",
    "switch_branch": "p9_s8b",
    "ability_trigger": "p9_s8b",
    "condition_barrier": "p9_s8b",
    "delayed_sequence": "p9_s8c",
    "custom_sync_barrier": "p9_s8c",
    "server_sync_barrier": "p9_s8c",
    "projectile_sequence": "p9_s8c",
    "random_branch": "p9_s8c",
    "parallel_templates": "p9_s8c",
    "target_cursor": "p9_s8c",
    "presentation_barrier": "p9_s8c",
    "presentation_child_wrapper": "excluded",
    "settlement_barrier": "p9_s11",
    "event_switch": "p9_s9",
    "death_barrier": "p9_s14",
    "queue_condition": "p9_s13",
    "turn_barrier": "p9_s13",
}
TASK_CHILD_FIELDS = frozenset(
    {
        "TaskList", "SuccessTaskList", "FailedTaskList", "FailTaskList",
        "OnNoNewWeak", "OnInsertAbort", "OnSuccess", "OnBattleEventCreate",
        "PerformTaskList", "TemplateParamSequences",
    }
)
NON_GAMEPLAY_SEMANTICS = {
    "presentation_only", "client_only_excluded", "ai_excluded", "telemetry_excluded"
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


def _has_task_materialization(raw: Mapping[str, Any]) -> bool:
    return any(field in raw for field in TASK_CHILD_FIELDS)


def _independent_denominator(root: Path, snapshot: Any, scope: Any) -> tuple[dict[str, tuple[str, str, str]], set[str]]:
    expected: dict[str, tuple[str, str, str]] = {}
    ordinary: list[tuple[str, str]] = []
    for record in scope.scope_records:
        if record.materialization_role != "selected" or record.occurrence_kind != "typed_node":
            continue
        path = str(record.source.evidence["json_path"]).removesuffix(".$type")
        raw = _at_path(snapshot.documents[record.source.source_path], path)
        if not isinstance(raw, Mapping):
            continue
        semantic = record.semantic_kind in SEMANTIC_KINDS
        family_semantic = character_ability_semantic_kind(record.family)
        hybrid = family_semantic not in SEMANTIC_KINDS and _has_task_materialization(raw)
        if semantic or hybrid:
            expected[record.record_id] = (
                record.source.source_path,
                path,
                "semantic" if semantic else "hybrid",
            )
        else:
            ordinary.append((record.record_id, record.family))

    directory = root / "Config/ConfigGlobalTaskListTemplate"
    for file in sorted(directory.glob("*.json")):
        if file.name.endswith(".layout.json"):
            continue
        source_path = file.relative_to(root).as_posix()
        document = json.loads(file.read_bytes())
        templates = document.get("TaskListTemplate") if isinstance(document, Mapping) else None
        if not isinstance(templates, list):
            continue

        def walk(value: object, path: str) -> None:
            if isinstance(value, Mapping):
                family = _short_type(value.get("$type"))
                semantic = character_ability_semantic_kind(family) if family else None
                if family and (semantic in SEMANTIC_KINDS or _has_task_materialization(value)):
                    occurrence_id = character_ability_scope_record_id(
                        "typed_node", source_path, f"{path}.$type", family
                    )
                    expected[occurrence_id] = (
                        source_path,
                        path,
                        "shared_semantic" if semantic in SEMANTIC_KINDS else "shared_hybrid",
                    )
                for field, child in value.items():
                    walk(child, f"{path}.{field}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    walk(child, f"{path}[{index}]")

        for index, template in enumerate(templates):
            if isinstance(template, Mapping):
                walk(template.get("TaskList"), f"$.TaskListTemplate[{index}].TaskList")
    hybrid_families = {
        _short_type(_at_path(snapshot.documents[source], path).get("$type"))
        for source, path, kind in expected.values()
        if kind == "hybrid"
    }
    ordinary_ids = {record_id for record_id, family in ordinary if family in hybrid_families}
    return expected, ordinary_ids


def _source_scope_checks(root: Path, snapshot: Any, scope: Any, catalog: CharacterControlFlowContractCatalog) -> tuple[dict[str, bool], dict[str, tuple[str, str, str]]]:
    expected, ordinary_ids = _independent_denominator(root, snapshot, scope)
    expected_ids = set(expected)
    node_ids = {item.scope_record_id for item in catalog.nodes}
    hybrid_ids = {key for key, value in expected.items() if value[2] in {"hybrid", "shared_hybrid"}}
    shared_ids = {key for key, value in expected.items() if value[2].startswith("shared_")}
    semantic_ids = expected_ids - hybrid_ids
    predicates = {
        "denominator_uses_semantic_kind_and_materialization_role": bool(semantic_ids) and bool(hybrid_ids),
        "hybrid_child_bearing_occurrences_are_not_omitted": bool(hybrid_ids) and hybrid_ids <= node_ids,
        "ordinary_non_control_occurrences_are_not_promoted": bool(ordinary_ids) and not (ordinary_ids & node_ids),
        "shared_template_internal_control_nodes_are_recursive": bool(shared_ids)
        and shared_ids <= node_ids
        and any(expected[item][1].count(".TaskList[") > 1 for item in shared_ids),
        "every_selected_occurrence_has_one_node_disposition": expected_ids == node_ids
        == set(catalog.denominator_record_ids)
        and catalog.direct_record_count == len(expected_ids),
        "complete_current_source_closure_used": snapshot.source_catalog_complete
        and scope.fingerprint_kind == "complete"
        and not scope.source_filter
        and not scope.family_filter,
    }
    return predicates, expected


def _node_source_checks(root: Path, snapshot: Any, scope: Any, catalog: CharacterControlFlowContractCatalog, expected: Mapping[str, tuple[str, str, str]]) -> dict[str, bool]:
    documents, hashes = _load_documents(root, snapshot, catalog)
    records = {item.record_id: item for item in scope.scope_records}
    reversible = True
    fields_closed = True
    branches_closed = True
    structural_branches_closed = True
    for node in catalog.nodes:
        expected_source, expected_path, expected_kind = expected[node.scope_record_id]
        node_path = str(node.source.evidence["json_path"])
        raw = _at_path(documents[node.source.source_path], node_path)
        record = records.get(node.scope_record_id)
        reversible &= (
            isinstance(raw, Mapping)
            and _short_type(raw.get("$type")) == node.family
            and node.source.source_path == expected_source
            and node_path == expected_path
            and node.source.evidence.get("content_sha256") == hashes[node.source.source_path]
            and node.source.evidence.get("scope_record_id") == node.scope_record_id
            and node.source.evidence.get("source_kind")
            == ("shared_template" if expected_kind.startswith("shared_") else "character_scope")
            and (
                expected_kind.startswith("shared_")
                or (record is not None and node.family == record.family)
            )
        )
        raw_fields = {key for key in raw if key != "$type"} if isinstance(raw, Mapping) else set()
        responsibilities = {item.field_name: item for item in node.field_responsibilities}
        fields_closed &= (
            raw_fields == set(node.peer_field_names) == set(responsibilities)
            and all(
                item.responsibility != "unclassified"
                and item.owner_stage in ALLOWED_STAGES
                and item.covers_subtree
                and _at_path(documents[item.source.source_path], str(item.source.evidence["json_path"]))
                == raw[item.field_name]
                for item in responsibilities.values()
            )
        )
        for branch in node.branches:
            try:
                _at_path(documents[branch.source.source_path], str(branch.source.evidence["json_path"]))
                for child in branch.children:
                    child_type = _at_path(documents[child.source.source_path], str(child.source.evidence["json_path"]))
                    branches_closed &= _short_type(child_type) == child.family
            except (KeyError, IndexError, TypeError, ValueError):
                branches_closed = False
        actual_child_paths = {
            str(child.source.evidence["json_path"])
            for branch in node.branches
            for child in branch.children
        }
        actual_branch_paths = {
            str(branch.source.evidence["json_path"])
            for branch in node.branches
        }
        for field in TASK_CHILD_FIELDS & set(raw):
            value = raw[field]
            expected_children: set[str] = set()
            expected_branches: set[str] = set()
            if field == "TemplateParamSequences" and isinstance(value, Mapping):
                for name, sequence in value.items():
                    entry = f"{node_path}.TemplateParamSequences.{name}"
                    expected_branches.add(entry)
                    tasks = sequence.get("TaskList") if isinstance(sequence, Mapping) else None
                    if isinstance(tasks, (list, tuple)):
                        expected_children.update(f"{entry}.TaskList[{index}].$type" for index, child in enumerate(tasks) if isinstance(child, Mapping))
            elif isinstance(value, (list, tuple)):
                expected_branches.add(f"{node_path}.{field}")
                expected_children.update(f"{node_path}.{field}[{index}].$type" for index, child in enumerate(value) if isinstance(child, Mapping))
            field_prefix = f"{node_path}.{field}"
            actual_for_field = {path for path in actual_child_paths if path.startswith(field_prefix)}
            structural_branches_closed &= expected_children == actual_for_field
            if not (node.family == "RandomConfig" and field == "TaskList"):
                structural_branches_closed &= expected_branches <= actual_branch_paths
    return {
        "every_selected_node_reverses_to_exact_raw_object": reversible,
        "every_peer_field_has_exactly_one_responsibility": fields_closed,
        "branch_children_reverse_to_exact_source": branches_closed,
        "materialized_subgraphs_have_exact_source_branches": structural_branches_closed,
        "all_control_roles_are_typed": bool(catalog.nodes)
        and all(node.control_role in ROLE_OWNER or node.control_role in {"condition_delegate", "template_include"} for node in catalog.nodes),
        "every_child_source_has_one_parent_branch": len(
            [
                child.record_id
                for node in catalog.nodes
                for branch in node.branches
                for child in branch.children
                if child.record_id in expected
            ]
        )
        == len(
            {
                child.record_id
                for node in catalog.nodes
                for branch in node.branches
                for child in branch.children
                if child.record_id in expected
            }
        ),
    }


def _template_checks(root: Path, snapshot: Any, catalog: CharacterControlFlowContractCatalog) -> dict[str, bool]:
    documents, hashes = _load_documents(root, snapshot, catalog)
    definitions = {item.template_id: item for item in catalog.template_definitions}
    shared_expected: set[tuple[str, str, str]] = set()
    for file in sorted((root / "Config/ConfigGlobalTaskListTemplate").glob("*.json")):
        if file.name.endswith(".layout.json"):
            continue
        document = json.loads(file.read_bytes())
        for index, raw in enumerate(document.get("TaskListTemplate", ()) if isinstance(document, Mapping) else ()):
            if isinstance(raw, Mapping) and isinstance(raw.get("Name"), str):
                shared_expected.add((file.relative_to(root).as_posix(), f"$.TaskListTemplate[{index}]", raw["Name"]))
    shared_actual = {
        (item.source.source_path, str(item.source.evidence["json_path"]), item.name)
        for item in definitions.values()
        if item.scope_kind == "shared_global"
    }
    definitions_ok = bool(definitions) and bool(shared_expected) and shared_expected == shared_actual
    parameter_count = 0
    parameters_ok = True
    for item in definitions.values():
        raw = _at_path(documents[item.source.source_path], str(item.source.evidence["json_path"]))
        tasks = raw.get("TaskList") if isinstance(raw, Mapping) else None
        parameter_count += len(item.parameters)
        parameters_ok &= all(
            parameter.source.evidence.get("content_sha256") == hashes[item.source.source_path]
            and _at_path(documents[parameter.source.source_path], str(parameter.source.evidence["json_path"])) is not None
            for parameter in item.parameters
        )
        definitions_ok &= (
            isinstance(raw, Mapping)
            and raw.get("Name") == item.name
            and isinstance(tasks, list)
            and len(tasks) == len(item.children)
            and set(raw) <= {"Name", "TaskList", "DynamicStrings", "DynamicValues"}
            and item.source.evidence.get("content_sha256") == hashes[item.source.source_path]
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
    sequence_branches = [
        branch
        for node in catalog.nodes
        for branch in node.branches
        if branch.branch_kind == "template_parameter_sequence"
    ]
    sequences_ok = bool(sequence_branches) and all(
        isinstance(
            raw := _at_path(documents[branch.source.source_path], str(branch.source.evidence["json_path"])),
            Mapping,
        )
        and set(raw) == {"TaskList"}
        and isinstance(raw.get("TaskList"), (list, tuple))
        and len(raw["TaskList"]) == len(branch.children)
        and all(child.ordinal == index for index, child in enumerate(branch.children))
        for branch in sequence_branches
    )
    sequences_ok &= all(
        tuple(
            branch.label
            for branch in node.branches
            if branch.branch_kind == "template_parameter_sequence"
        )
        == tuple(raw_sequences)
        for node in catalog.nodes
        if isinstance(
            raw_sequences := _at_path(
                documents[node.source.source_path],
                str(node.source.evidence["json_path"]),
            ).get("TemplateParamSequences"),
            Mapping,
        )
    )
    fetch_branches = [
        (node, branch)
        for node in catalog.nodes
        for branch in node.branches
        if branch.branch_kind == "template_parameter_fetch"
    ]
    fetch_nodes = [item for item in catalog.nodes if item.family == "TaskTemplateFetchParamSequence"]
    fetch_ok = bool(fetch_branches) and len(fetch_branches) == len(fetch_nodes) and all(
        _at_path(documents[branch.source.source_path], str(branch.source.evidence["json_path"]))
        == branch.label
        for _, branch in fetch_branches
    )
    fetch_names_by_template = {key: set() for key in definitions}
    for node, branch in fetch_branches:
        owners = [
            item
            for item in definitions.values()
            if item.source.source_path == node.source.source_path
            and str(node.source.evidence["json_path"]).startswith(
                f'{item.source.evidence["json_path"]}.TaskList['
            )
        ]
        if owners:
            owner = max(owners, key=lambda item: len(str(item.source.evidence["json_path"])))
            fetch_names_by_template[owner.template_id].add(branch.label)
    node_by_id = {item.node_id: item for item in catalog.nodes}
    fetch_ok &= all(
        {
            branch.label
            for branch in node_by_id[reference.node_id].branches
            if branch.branch_kind == "template_parameter_sequence"
        }
        == fetch_names_by_template[reference.resolved_template_id]
        for reference in catalog.template_references
        if reference.coverage_status == "lowered"
    )
    return {
        "template_definitions_reverse_to_source": definitions_ok,
        "template_parameter_declarations_are_typed": parameter_count > 0 and parameters_ok,
        "template_definitions_and_references_are_source_closed": references_ok
        and not catalog.issues
        and catalog.complete,
        "template_param_sequences_are_ordered_source_branches": sequences_ok,
        "template_param_fetch_is_typed_and_source_closed": fetch_ok,
    }


def _termination_and_obligation_checks(root: Path, snapshot: Any, catalog: CharacterControlFlowContractCatalog) -> dict[str, bool]:
    documents, _ = _load_documents(root, snapshot, catalog)
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
        raw = _at_path(documents[node.source.source_path], str(node.source.evidence["json_path"]))
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


def _presentation_exclusion_checks(root: Path, snapshot: Any, catalog: CharacterControlFlowContractCatalog) -> bool:
    documents, _ = _load_documents(root, snapshot, catalog)
    checked = 0

    def closed(value: object) -> bool:
        nonlocal checked
        if isinstance(value, Mapping):
            family = _short_type(value.get("$type"))
            if family:
                checked += 1
                if character_ability_semantic_kind(family) not in NON_GAMEPLAY_SEMANTICS:
                    return False
            return all(closed(child) for child in value.values())
        if isinstance(value, (list, tuple)):
            return all(closed(child) for child in value)
        return True

    for node in catalog.nodes:
        raw = _at_path(documents[node.source.source_path], str(node.source.evidence["json_path"]))
        for field in node.field_responsibilities:
            if (
                field.responsibility == "presentation_excluded"
                and field.field_name in TASK_CHILD_FIELDS | {"OnProjectileHitClientOnly"}
                and not closed(raw[field.field_name])
            ):
                return False
    return checked > 0


def _negative_checks(catalog: CharacterControlFlowContractCatalog) -> dict[str, bool]:
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
    reduced_counts = dict(catalog.family_counts)
    reduced_counts[sample_node.family] -= 1
    parameter_node = next(
        node
        for node in catalog.nodes
        if any(branch.branch_kind == "template_parameter_sequence" for branch in node.branches)
    )
    parameter_branches = tuple(
        replace(branch, label=f"{branch.label}:forged")
        if branch.branch_kind == "template_parameter_sequence"
        else branch
        for branch in parameter_node.branches
    )
    child_parent = next(
        (node, branch)
        for node in catalog.nodes
        for branch in node.branches
        if any(child.record_id in catalog.denominator_record_ids for child in branch.children)
    )
    parent_node, parent_branch = child_parent
    selected_child = next(
        child
        for child in parent_branch.children
        if child.record_id in catalog.denominator_record_ids
    )
    duplicated_child = replace(selected_child, ordinal=len(parent_branch.children))
    duplicated_branch = replace(parent_branch, children=(*parent_branch.children, duplicated_child))
    return {
        "unknown_peer_field_blocked": len(responsibilities) == 1
        and responsibilities[0].responsibility == "unclassified"
        and bool(blockers),
        "malformed_branch_child_blocked": bool(branch_blockers),
        "denominator_omission_rejected": _expect_raises(
            lambda: replace(
                catalog,
                nodes=tuple(item for item in catalog.nodes if item.node_id != sample_node.node_id),
                direct_record_count=catalog.direct_record_count - 1,
                family_counts=reduced_counts,
            )
        ),
        "template_parameter_name_mismatch_rejected": _expect_raises(
            lambda: replace(
                catalog,
                nodes=tuple(
                    replace(item, branches=parameter_branches)
                    if item.node_id == parameter_node.node_id
                    else item
                    for item in catalog.nodes
                ),
            )
        ),
        "multiple_parent_materialization_rejected": _expect_raises(
            lambda: replace(
                catalog,
                nodes=tuple(
                    replace(
                        item,
                        branches=tuple(
                            duplicated_branch if branch.branch_id == parent_branch.branch_id else branch
                            for branch in item.branches
                        ),
                    )
                    if item.node_id == parent_node.node_id
                    else item
                    for item in catalog.nodes
                ),
            )
        ),
    }


def validate(root: Path, output_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    snapshot = build_character_ability_raw_snapshot(root)
    scope = build_character_ability_scope_projection(root, snapshot=snapshot)
    lowering = TBGDLowering(root)
    catalog = lowering.build_character_control_flow_contract_catalog(snapshot=snapshot, scope_catalog=scope)
    negative_matrix = _negative_checks(catalog)
    source_predicates, denominator = _source_scope_checks(root, snapshot, scope, catalog)
    predicates = {
        **source_predicates,
        **_node_source_checks(root, snapshot, scope, catalog, denominator),
        **_template_checks(root, snapshot, catalog),
        **_termination_and_obligation_checks(root, snapshot, catalog),
        "presentation_exclusion_requires_descendant_closure": _presentation_exclusion_checks(root, snapshot, catalog),
        "unknown_shape_fails_at_catalog_construction": all(negative_matrix.values()),
        "unknown_or_forged_shapes_fail_closed": all(negative_matrix.values()),
        "runtime_behavior_changed": False,
        "full_canonical_ir_build_count": catalog.build_counters.get("full_canonical_ir_build_count", -1),
    }
    business_predicates = {
        key: value
        for key, value in predicates.items()
        if key not in {"full_canonical_ir_build_count", "runtime_behavior_changed"}
    }
    ok = (
        all(value is True for value in business_predicates.values())
        and predicates["runtime_behavior_changed"] is False
        and predicates["full_canonical_ir_build_count"] == 0
        and all(value is True for value in negative_matrix.values())
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "stage": "P9-S8A-R1",
        "ok": ok,
        "predicates": predicates,
        "negative_matrix": negative_matrix,
        "manual_review_required": {"runtime_behavior_changed": "git_diff_scope_review"},
        "source_facts": {
            "snapshot_id": snapshot.snapshot_id,
            "scope_catalog_id": scope.catalog_id,
            "catalog_id": catalog.catalog_id,
            "direct_record_count": catalog.direct_record_count,
            "independent_denominator_count": len(denominator),
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
            "source_kind_counts": dict(sorted(Counter(str(item.source.evidence["source_kind"]) for item in catalog.nodes).items())),
            "materialization_role_counts": dict(sorted(Counter(str(item.source.evidence["materialization_role"]) for item in catalog.nodes).items())),
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
