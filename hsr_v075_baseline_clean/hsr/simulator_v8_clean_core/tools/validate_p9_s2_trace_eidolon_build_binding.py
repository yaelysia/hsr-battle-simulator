from __future__ import annotations

import argparse
import importlib
import inspect
import json
import resource
import time
import traceback
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..builds.character_assembler import assemble_character_build, validate_character_build_admission
from ..builds.models import CharacterBuildAssemblyResult, CharacterBuildInput, CharacterInitialConditionInput
from ..equipment.models import EquipmentBuildInput
from ..ir_types import IRSource
from ..rules.ir import CanonicalIR, CharacterBuildBindingIR, CharacterDataCardIR, CharacterEidolonSlotIR, CharacterTraceNodeIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import _formal_character_activation, _plan_formal_character_birth
from ..scenarios.schema import ScenarioSpec, UnitSpec
from ..tbgd.character_cards import (
    CHARACTER_ACTION_DEFINITION_TABLES,
    CharacterCardBuildResult,
    build_character_card_ir,
)
from ..tbgd.lowering import TBGDLowering


WALL_CLOCK_BUDGET_SECONDS = 8 * 60
RSS_BUDGET_BYTES = 1024 * 1024 * 1024
EVIDENCE_BUDGET_BYTES = 5 * 1024 * 1024
VALIDATION_CODE_BUDGET_LINES = 900
SELECTOR_TYPES = {"BySkillPointActivated": "skill_point", "ByRankActivated": "rank"}
PROJECTION_KINDS = frozenset({"static_contribution", "resource_contribution", "skill_level_change", "dynamic_graph_ref", "source_gap"})
DYNAMIC_PAYLOAD_KEYS = frozenset({"effect", "effects", "effect_payload", "payload", "tasks", "param_values", "dynamic_value_bindings", "semantics"})
LEGACY_RESULT_NAMES = ("CharacterMechanismRef", "admitted_dynamic_mechanism_refs")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the P9-S2 final character-build binding contract.")
    parser.add_argument("--tbgd-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def _expect_rejected(operation: Callable[[], object]) -> bool:
    try:
        operation()
    except (AttributeError, KeyError, TypeError, ValueError):
        return True
    return False


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _nonempty_lines(path: Path) -> int:
    return sum(bool(line.strip()) for line in path.read_text(encoding="utf-8").splitlines())


def _short_type(value: object) -> str:
    return str(value or "").rsplit(".", 1)[-1]


def _child_path(path: str, key: object) -> str:
    text = str(key)
    if text and all(character.isalnum() or character == "_" for character in text):
        return f"{path}.{text}"
    return f"{path}[{json.dumps(text, ensure_ascii=True)}]"


def _rows(root: Path, relative_path: str) -> tuple[dict[str, Any], ...]:
    path = root / relative_path
    if not path.exists():
        return ()
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"raw table is not a list:{relative_path}")
    return tuple(item for item in value if isinstance(item, dict))


def _branch_context(path: str, value: Mapping[str, Any]) -> dict[str, str] | None:
    true_path = ""
    false_path = ""
    if "SuccessTaskList" in value:
        true_path = _child_path(path, "SuccessTaskList")
    elif "TaskList" in value:
        true_path = _child_path(path, "TaskList")
    if "FailedTaskList" in value:
        false_path = _child_path(path, "FailedTaskList")
    if true_path or false_path:
        return {
            "branch_kind": "explicit_task_branches",
            "branch_root_path": path,
            "true_subtree_path": true_path,
            "false_subtree_path": false_path,
        }
    substantive = set(value).difference({"$type", "Predicate", "Condition", "Inverse"})
    if not substantive:
        return None
    return {
        "branch_kind": "predicate_gated_object",
        "branch_root_path": path,
        "true_subtree_path": path,
        "false_subtree_path": "",
    }


def _raw_selector_records(snapshot: object) -> tuple[tuple[dict[str, object], ...], dict[str, frozenset[str]]]:
    sources = {source.source.source_path: source for source in snapshot.sources}
    records: list[dict[str, object]] = []
    paths_by_source: dict[str, set[str]] = defaultdict(set)

    def walk(
        source_path: str,
        value: object,
        path: str,
        parent_marker: str,
        inherited_gate: dict[str, str] | None,
    ) -> None:
        paths_by_source[source_path].add(path)
        if isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                walk(source_path, item, f"{path}[{index}]", parent_marker, inherited_gate)
            return
        if not isinstance(value, Mapping):
            return
        opcode = _short_type(value.get("$type"))
        if opcode in SELECTOR_TYPES:
            inverse = value.get("Inverse", False)
            if not isinstance(inverse, bool):
                raise ValueError(f"raw selector inverse is not boolean:{source_path}:{path}")
            selector_key = ""
            selector_hash: int | None = None
            if opcode == "BySkillPointActivated":
                raw_key = value.get("PointTriggerKey")
                if not isinstance(raw_key, str) or not raw_key:
                    raise ValueError(f"raw skill-point selector key missing:{source_path}:{path}")
                selector_key = raw_key
            else:
                trigger = value.get("TriggerKey")
                raw_hash = trigger.get("Hash") if isinstance(trigger, Mapping) else None
                if not isinstance(raw_hash, int) or isinstance(raw_hash, bool):
                    raise ValueError(f"raw rank selector hash missing:{source_path}:{path}")
                selector_hash = raw_hash
            source = sources[source_path]
            gate = inherited_gate or {
                "branch_kind": "predicate_context",
                "branch_root_path": parent_marker.removesuffix(".$type"),
                "true_subtree_path": "",
                "false_subtree_path": "",
            }
            records.append(
                {
                    "source_path": source_path,
                    "owner_avatar_id": source.avatar_id,
                    "source_kind": source.source_kind,
                    "selector_kind": SELECTOR_TYPES[opcode],
                    "selector_key": selector_key,
                    "selector_hash": selector_hash,
                    "inverse": inverse,
                    "selector_json_path": path,
                    **gate,
                }
            )
        marker = parent_marker
        if isinstance(value.get("$type"), str):
            marker = f"{path}.$type"
        elif isinstance(value.get("Event"), str):
            marker = f"{path}.Event"
        for key, child in value.items():
            child_gate = inherited_gate
            if key in {"Predicate", "Condition"} and isinstance(
                child, (Mapping, list, tuple)
            ):
                child_gate = _branch_context(path, value)
            walk(source_path, child, _child_path(path, key), marker, child_gate)

    for source_path, document in snapshot.documents.items():
        source = sources[source_path]
        if source.source_kind != "character_main" or not source.avatar_id:
            continue
        walk(source_path, document, "$", "$", None)
    records.sort(
        key=lambda row: (
            str(row["source_path"]),
            str(row["selector_json_path"]),
        )
    )
    identities = {
        (row["source_path"], row["selector_json_path"]) for row in records
    }
    if len(identities) != len(records):
        raise ValueError("raw selector identities are not unique")
    return tuple(records), {key: frozenset(value) for key, value in paths_by_source.items()}


def _selection_oracle(root: Path, built: CharacterCardBuildResult) -> tuple[dict[tuple[str, str], dict[str, set[str]]], dict[tuple[str, int], dict[str, set[str]]], bool]:
    traces: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    ranks: dict[tuple[str, int], dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    table_cache: dict[str, tuple[dict[str, Any], ...]] = {}
    source_rows_valid = True

    def source_row(path: str, index: object) -> Mapping[str, Any] | None:
        nonlocal source_rows_valid
        if path not in table_cache:
            table_cache[path] = _rows(root, path)
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(table_cache[path]):
            source_rows_valid = False
            return None
        return table_cache[path][index]

    for node in built.character_trace_nodes:
        raw = source_row(node.source.source_path, node.source.evidence.get("row_index"))
        key = raw.get("PointTriggerKey") if raw is not None else None
        level = raw.get("Level") if raw is not None else None
        raw_enhanced_id = str(raw.get("EnhancedID")) if raw is not None and raw.get("EnhancedID") is not None else ""
        projected_enhanced_id = node.source.evidence.get("enhanced_id")
        projected_enhanced_id = str(projected_enhanced_id) if projected_enhanced_id is not None else ""
        source_rows_valid &= bool(
            raw is not None
            and str(raw.get("AvatarID") or "") == node.avatar_id
            and str(raw.get("PointID") or "") == node.trace_id
            and int(level or 1) == node.level
            and raw_enhanced_id == projected_enhanced_id
        )
        if isinstance(key, str) and key:
            traces[(node.avatar_id, key)][node.trace_id].add(node.trace_node_id)

    for slot in built.character_eidolon_slots:
        evidence = slot.source.evidence
        path = evidence.get("rank_config_source_path")
        raw = source_row(path, evidence.get("rank_config_row_index")) if isinstance(path, str) and path else None
        trigger = raw.get("Trigger") if raw is not None else None
        raw_hash = trigger.get("Hash") if isinstance(trigger, Mapping) else None
        source_rows_valid &= bool(
            raw is not None
            and str(raw.get("RankID") or "") == slot.rank_id
            and raw.get("Rank") == slot.rank
            and isinstance(raw_hash, int)
            and not isinstance(raw_hash, bool)
            and raw_hash == slot.semantics.get("trigger_hash")
        )
        if isinstance(raw_hash, int) and not isinstance(raw_hash, bool):
            ranks[(slot.avatar_id, raw_hash)][str(slot.rank)].add(slot.eidolon_slot_id)
    return traces, ranks, source_rows_valid


def _selector_oracle(root: Path, lowerer: TBGDLowering, catalog: object, scope: object, built: CharacterCardBuildResult) -> dict[str, object]:
    snapshot = lowerer._character_ability_raw_snapshot
    all_raw_records, _ = _raw_selector_records(snapshot)
    raw_by_identity = {
        (str(row["source_path"]), str(row["selector_json_path"])): row
        for row in all_raw_records
    }
    selected_scope_records = {
        record.record_id: record
        for record in scope.scope_records
        if record.materialization_role == "selected"
        and record.effective_scope == "build_resolution"
        and record.family in SELECTOR_TYPES
    }
    selected_projections = {
        projection.scope_record_id: projection
        for projection in scope.projections
        if projection.projection_scope == "build_resolution"
        and projection.projection_kind == "build_selector"
    }
    raw_records: list[dict[str, object]] = []
    scope_projection_matches_raw = set(selected_scope_records) == set(selected_projections)
    for record_id, record in selected_scope_records.items():
        projection = selected_projections.get(record_id)
        payload = projection.payload if projection is not None else {}
        path = payload.get("selector_json_path")
        raw = raw_by_identity.get((record.source.source_path, str(path or "")))
        if raw is None:
            scope_projection_matches_raw = False
            continue
        expected_kind = "skill_point" if record.family == "BySkillPointActivated" else "rank"
        scope_projection_matches_raw &= all(
            (
                raw["owner_avatar_id"] == record.source.evidence.get("avatar_id"),
                raw["selector_kind"] == expected_kind == payload.get("selector_kind"),
                raw["selector_key"] == str(payload.get("selector_key") or ""),
                raw["selector_hash"] == payload.get("selector_hash"),
                raw["inverse"] == payload.get("inverse"),
                raw["branch_kind"] == payload.get("branch_kind"),
                raw["branch_root_path"] == payload.get("branch_root_path"),
                raw["true_subtree_path"] == str(payload.get("true_subtree_path") or ""),
                raw["false_subtree_path"] == str(payload.get("false_subtree_path") or ""),
            )
        )
        raw_records.append(raw)
    traces, ranks, selection_sources_valid = _selection_oracle(root, built)
    sources_by_path: dict[str, list[object]] = defaultdict(list)
    graphs_by_source: dict[str, list[object]] = defaultdict(list)
    definitions_by_source: dict[str, list[object]] = defaultdict(list)
    for source in catalog.sources:
        sources_by_path[source.source.source_path].append(source)
    for graph in catalog.graphs:
        graphs_by_source[graph.source_id].append(graph)
    for definition in catalog.definitions:
        definitions_by_source[definition.source_id].append(definition)

    expected: dict[tuple[object, ...], dict[str, object]] = {}
    foreign_trace_keys = {(owner, key) for owner, key in traces}
    foreign_rank_keys = {(owner, key) for owner, key in ranks}
    for row in raw_records:
        source_path = str(row["source_path"])
        owner = str(row["owner_avatar_id"])
        kind = str(row["selector_kind"])
        selector_key = str(row["selector_key"])
        selector_hash = row["selector_hash"]
        identity = (
            source_path,
            row["selector_json_path"],
            owner,
            kind,
            selector_key,
            selector_hash,
        )
        candidates = (
            traces.get((owner, selector_key), {})
            if kind == "skill_point"
            else ranks.get((owner, int(selector_hash)), {})
        )
        source_candidates = [
            source
            for source in sources_by_path.get(source_path, ())
            if source.source_kind == "character_main" and source.avatar_id == owner
        ]
        gap_kind = ""
        graph = None
        definition = None
        if len(source_candidates) != 1:
            gap_kind = "source_closure_mismatch"
        else:
            graphs = graphs_by_source.get(source_candidates[0].source_id, ())
            if len(graphs) != 1:
                gap_kind = "source_graph_missing"
            else:
                graph = graphs[0]
                matching_definitions = [
                    item
                    for item in definitions_by_source.get(source_candidates[0].source_id, ())
                    if item.source.source_path == source_path
                    if isinstance(item.source.evidence.get("json_path"), str)
                    and (
                        row["selector_json_path"] == item.source.evidence["json_path"]
                        or str(row["selector_json_path"]).startswith(
                            str(item.source.evidence["json_path"]) + "."
                        )
                    )
                ]
                if len(matching_definitions) > 1:
                    gap_kind = "ability_definition_ambiguous"
                elif matching_definitions:
                    definition = matching_definitions[0]
        if not gap_kind and len(candidates) != 1:
            if len(candidates) > 1:
                gap_kind = "selection_ambiguous"
            else:
                foreign = (
                    any(other_owner != owner and key == selector_key for other_owner, key in foreign_trace_keys)
                    if kind == "skill_point"
                    else any(other_owner != owner and key == selector_hash for other_owner, key in foreign_rank_keys)
                )
                gap_kind = "cross_character" if foreign else "selection_missing"
        logical_id = next(iter(candidates)) if len(candidates) == 1 else ""
        expected[identity] = {
            **row,
            "classification": "gap" if gap_kind else "relation",
            "gap_kind": gap_kind,
            "logical_selection_id": logical_id,
            "source_id": source_candidates[0].source_id if len(source_candidates) == 1 else "",
            "source_graph_id": graph.graph_id if graph is not None else "",
            "ability_definition_id": definition.definition_id if definition is not None else "",
            "source_content_sha256": sha256(snapshot.source_bytes[source_path]).hexdigest(),
        }

    relation_by_identity = {
        (
            item.selector_source.source_path,
            item.selector_json_path,
            item.owner_avatar_id,
            item.selector_kind,
            item.selector_key,
            item.selector_hash,
        ): item
        for item in built.character_build_selector_relations
    }
    gap_by_identity = {
        (
            item.selector_source.source_path,
            item.selector_json_path,
            item.owner_avatar_id,
            item.selector_kind,
            item.selector_key,
            item.selector_hash,
        ): item
        for item in built.character_build_selector_gaps
    }
    expected_relations = {key for key, row in expected.items() if row["classification"] == "relation"}
    expected_gaps = set(expected).difference(expected_relations)
    exact_partition = (
        set(relation_by_identity) == expected_relations
        and set(gap_by_identity) == expected_gaps
        and not set(relation_by_identity).intersection(gap_by_identity)
    )

    trace_nodes = tuple(built.character_trace_nodes)
    eidolon_slots = tuple(built.character_eidolon_slots)
    target_alias_records = tuple(record for record in scope.scope_records if record.materialization_role == "selected" and record.family == "TargetAlias")
    target_alias_by_id = {record.record_id: record for record in target_alias_records}
    relation_checks: list[bool] = []
    rows: list[dict[str, object]] = []
    for identity, expected_row in sorted(expected.items(), key=lambda item: str(item[0])):
        if expected_row["classification"] == "gap":
            gap = gap_by_identity.get(identity)
            passed = gap is not None and gap.gap_kind == expected_row["gap_kind"]
            relation_checks.append(passed)
            rows.append({"identity": list(identity), "classification": "gap", "gap_kind": expected_row["gap_kind"], "passed": passed})
            continue
        relation = relation_by_identity.get(identity)
        expected_refs: set[str] = set()
        if relation is not None and relation.selection_kind == "trace":
            expected_refs = {
                node.trace_node_id
                for node in trace_nodes
                if node.avatar_id == relation.owner_avatar_id
                and node.trace_id == expected_row["logical_selection_id"]
            }
        elif relation is not None:
            expected_refs = {
                slot.eidolon_slot_id
                for slot in eidolon_slots
                if slot.avatar_id == relation.owner_avatar_id
                and str(slot.rank) == expected_row["logical_selection_id"]
            }
        context_ids = {item.scope_record_id for item in relation.context_refs} if relation else set()
        branch_paths = tuple(path for path in (relation.true_subtree_path, relation.false_subtree_path) if path) if relation else ()
        expected_context_ids = {
            record.record_id
            for record in target_alias_records
            if relation is not None and record.source.source_path == relation.selector_source.source_path
            if isinstance(record.source.evidence.get("json_path"), str)
            and any(record.source.evidence["json_path"] == branch or str(record.source.evidence["json_path"]).startswith(branch + ".") or str(record.source.evidence["json_path"]).startswith(branch + "[") for branch in branch_paths)
        }
        raw_contexts_ok = bool(relation) and all(
            item.scope_record_id in target_alias_by_id
            and target_alias_by_id[item.scope_record_id].source.source_path == item.source.source_path
            and target_alias_by_id[item.scope_record_id].source.evidence.get("json_path") == item.json_path
            and item.source.evidence.get("inherited_scope_record_id") == relation.selector_scope_record_id
            for item in relation.context_refs
        )
        passed = bool(relation) and all(
            (
                relation.logical_selection_id == expected_row["logical_selection_id"],
                set(relation.selection_ref_ids) == expected_refs and bool(expected_refs),
                relation.source_id == expected_row["source_id"],
                relation.source_graph_id == expected_row["source_graph_id"],
                relation.ability_definition_id == expected_row["ability_definition_id"],
                relation.source_content_sha256 == expected_row["source_content_sha256"],
                relation.branch_kind == expected_row["branch_kind"],
                relation.branch_root_path == expected_row["branch_root_path"],
                relation.true_subtree_path == expected_row["true_subtree_path"],
                relation.false_subtree_path == expected_row["false_subtree_path"],
                relation.selector_value_when_selected is (not expected_row["inverse"]),
                context_ids == expected_context_ids,
                raw_contexts_ok,
            )
        )
        relation_checks.append(passed)
        rows.append({"identity": list(identity), "classification": "relation", "logical_selection_id": expected_row["logical_selection_id"], "passed": passed})
    return {
        "raw_selector_count": len(all_raw_records),
        "selected_build_selector_count": len(raw_records),
        "excluded_non_build_selector_count": len(all_raw_records) - len(raw_records),
        "raw_selector_kind_counts": dict(sorted(Counter(str(row["selector_kind"]) for row in raw_records).items())),
        "raw_inverse_count": sum(bool(row["inverse"]) for row in raw_records),
        "expected_relation_count": len(expected_relations),
        "expected_gap_count": len(expected_gaps),
        "actual_relation_count": len(relation_by_identity),
        "actual_gap_count": len(gap_by_identity),
        "target_alias_context_count": sum(len(item.context_refs) for item in built.character_build_selector_relations),
        "exact_partition": exact_partition,
        "scope_projection_matches_raw": scope_projection_matches_raw,
        "selection_sources_match_raw": selection_sources_valid,
        "all_rows_passed": bool(rows) and all(relation_checks) and scope_projection_matches_raw and selection_sources_valid,
        "rows": rows,
    }


def _catalog_and_rules(
    root: Path,
) -> tuple[TBGDLowering, object, object, CharacterCardBuildResult, CanonicalIR, RuleBook, dict[str, object]]:
    lowerer = TBGDLowering(root)
    catalog = lowerer.build_character_ability_source_graph_catalog()
    scope = lowerer._character_ability_scope_catalog
    owners = frozenset(
        graph.owner_avatar_id
        for graph in catalog.graphs
        if graph.source_kind == "character_main"
    )
    built = build_character_card_ir(
        root,
        max_records_per_table=None,
        skill_tables=CHARACTER_ACTION_DEFINITION_TABLES,
        avatar_ids=owners,
        ability_source_graph_catalog=catalog,
        ability_scope_catalog=scope,
    )
    action_ids = frozenset(
        str(action.get("action_id"))
        for card in built.character_data_cards
        for action in card.action_set.get("actions", ())
        if isinstance(action, Mapping) and action.get("action_id")
    )
    entity_types = frozenset(action_id.split(":", 1)[0] for action_id in action_ids)
    action_definitions = tuple(
        lowerer._lower_action_definitions(action_ids=action_ids, entity_types=entity_types)
    )
    ir = CanonicalIR(
        version="p9_s2_validation_projection",
        avatar_profiles=tuple(built.avatar_profiles),
        character_data_cards=tuple(built.character_data_cards),
        character_equipment_eligibilities=tuple(built.character_equipment_eligibilities),
        character_mechanism_slots=tuple(built.character_mechanism_slots),
        character_trace_nodes=tuple(built.character_trace_nodes),
        character_eidolon_slots=tuple(built.character_eidolon_slots),
        character_build_selector_relations=tuple(built.character_build_selector_relations),
        character_build_selector_gaps=tuple(built.character_build_selector_gaps),
        bounce_policies=tuple(built.bounce_policies),
        action_definitions=action_definitions,
        skill_formula_bindings=tuple(built.skill_formula_bindings),
        character_ability_source_graph_catalog=catalog,
        metadata={"validation_scope": "p9_s2_narrow_projection"},
    )
    return lowerer, catalog, scope, built, ir, RuleBook(ir), {
        "owner_count": len(owners),
        "action_definition_count": len(action_definitions),
        "full_lowering_build_count": 0,
        "scope_projection_build_count": 1,
        "source_graph_build_count": 1,
        "character_card_build_count": 1,
        "rulebook_build_count": 1,
    }


def _all_trace_unlocks(
    card: CharacterDataCardIR,
    trace_by_id: Mapping[str, CharacterTraceNodeIR],
) -> tuple[str, ...]:
    groups: dict[str, list[CharacterTraceNodeIR]] = defaultdict(list)
    for node_id in card.trace_node_ids:
        groups[trace_by_id[node_id].trace_id].append(trace_by_id[node_id])
    result: list[str] = []
    for nodes in groups.values():
        selected = max(nodes, key=lambda item: (item.level, item.trace_node_id))
        defaults = [node for node in nodes if node.default_unlocked]
        if len(defaults) == 1 and defaults[0].trace_node_id == selected.trace_node_id:
            continue
        result.append(selected.trace_node_id)
    return tuple(sorted(result))


def _build_input(
    card: CharacterDataCardIR,
    profile: object,
    *,
    suffix: str,
    trace_ids: tuple[str, ...],
    eidolon_level: int,
) -> CharacterBuildInput:
    tier = max(profile.promotion_tiers, key=lambda item: (item.promotion, item.max_level))
    build_id = f"p9_s2:{card.card_id}:{suffix}"
    return CharacterBuildInput(
        build_id=build_id,
        character_card_id=card.card_id,
        level=tier.max_level,
        promotion=tier.promotion,
        eidolon_level=eidolon_level,
        unlocked_trace_node_ids=trace_ids,
        equipment_build=EquipmentBuildInput(
            build_id=f"{build_id}:equipment",
            character_card_id=card.card_id,
            identity_labels={"validation_scope": "p9_s2"},
        ),
    )


def _assembly_matrix(
    rules: RuleBook,
    built: CharacterCardBuildResult,
) -> tuple[tuple[dict[str, object], ...], tuple[CharacterBuildInput, CharacterBuildAssemblyResult] | None]:
    trace_by_id = {node.trace_node_id: node for node in built.character_trace_nodes}
    profiles = {profile.avatar_profile_id: profile for profile in built.avatar_profiles}
    rows: list[dict[str, object]] = []
    sample: tuple[CharacterBuildInput, CharacterBuildAssemblyResult] | None = None
    for card in sorted(built.character_data_cards, key=lambda item: item.card_id):
        variants = {
            "defaults_e0": ((), 0),
            "defaults_e6": ((), 6),
            "all_traces_e0": (_all_trace_unlocks(card, trace_by_id), 0),
            "all_traces_e6": (_all_trace_unlocks(card, trace_by_id), 6),
        }
        for variant, (trace_ids, eidolon_level) in variants.items():
            build = _build_input(
                card,
                profiles[card.profile_id],
                suffix=variant,
                trace_ids=trace_ids,
                eidolon_level=eidolon_level,
            )
            result = assemble_character_build(rules, build)
            specialization_rows = {
                item.selector_relation_id: (
                    item.selection_matched,
                    item.predicate_value,
                    item.selected_subtree_path,
                    item.parent_dynamic_graph_ref_id,
                )
                for item in result.selector_specializations
            }
            selected_bindings = tuple(
                binding
                for selection_id in (*result.selected_trace_node_ids, *result.selected_eidolon_slot_ids)
                for binding in rules.character_build_bindings_for_selection(selection_id)
            )
            expected_contribution_ids = {
                f"character_build:{binding.build_binding_id}"
                for binding in selected_bindings
                if binding.projection_kind in {"static_contribution", "resource_contribution"}
            }
            actual_contribution_ids = {
                item.contribution_id
                for item in result.contribution_ledger
                if item.contribution_id.startswith("character_build:")
            }
            rows.append(
                {
                    "card_id": card.card_id,
                    "variant": variant,
                    "assembly_status": result.assembly_status,
                    "battle_admission_status": result.battle_admission_status,
                    "dynamic_root_count": len(result.dynamic_graph_refs),
                    "selector_specialization_count": len(result.selector_specializations),
                    "selector_decisions": specialization_rows,
                    "dynamic_roots_unique": len({item.dynamic_graph_ref_id for item in result.dynamic_graph_refs}) == len(result.dynamic_graph_refs),
                    "root_and_specialization_coexist": any(item.build_binding_ids and item.specialization_ids for item in result.dynamic_graph_refs),
                    "dynamic_payload_clean": all(not DYNAMIC_PAYLOAD_KEYS.intersection(item.to_json()) for item in (*result.dynamic_graph_refs, *result.selector_specializations)),
                    "static_channel_exact": expected_contribution_ids == actual_contribution_ids,
                    "blocked_reasons": list(result.blocked_reasons),
                }
            )
            if result.assembly_status == "assembled" and result.dynamic_graph_refs and sample is None:
                sample = (build, result)
    return tuple(rows), sample


def _formal_birth_blocked(
    rules: RuleBook,
    card: CharacterDataCardIR,
    build: CharacterBuildInput,
    result: CharacterBuildAssemblyResult,
) -> bool:
    unit = UnitSpec(
        unit_id="p9_s2_formal",
        side="ally",
        entity_ref=card.entity_ref,
        build_mode="assembled_character_build",
        level=build.level,
        eidolon_level=build.eidolon_level,
        panel=None,
        character_build=build,
        initial_condition=CharacterInitialConditionInput(
            hp_mode="full",
            initial_energy="0",
        ),
    )
    scenario = ScenarioSpec(
        scenario_id="p9_s2_admission",
        version="p9_s2",
        units=(unit,),
        route=(),
    )
    try:
        _plan_formal_character_birth(rules, scenario, unit, result)
    except ValueError as exc:
        return "character_build_not_admitted_for_battle" in str(exc)
    return False


def _negative_matrix(
    ir: CanonicalIR,
    rules: RuleBook,
    built: CharacterCardBuildResult,
    sample: tuple[CharacterBuildInput, CharacterBuildAssemblyResult],
) -> dict[str, bool]:
    build, result = sample
    card = rules.character_data_card(build.character_card_id)
    profile = rules.avatar_profile_by_profile_id(card.profile_id)
    trace_nodes = rules.character_trace_nodes_for_card(card.card_id)
    default = next((node for node in trace_nodes if node.default_unlocked), None)
    default_blocked = (
        assemble_character_build(
            rules,
            _build_input(card, profile, suffix="default_reselected", trace_ids=(default.trace_node_id,), eidolon_level=0),
        )
        if default is not None
        else None
    )
    groups: dict[str, list[CharacterTraceNodeIR]] = defaultdict(list)
    for node in trace_nodes:
        groups[node.trace_id].append(node)
    conflict = next((nodes[:2] for nodes in groups.values() if len(nodes) >= 2), ())
    conflict_blocked = (
        assemble_character_build(
            rules,
            _build_input(card, profile, suffix="trace_conflict", trace_ids=tuple(node.trace_node_id for node in conflict), eidolon_level=0),
        )
        if conflict
        else None
    )
    foreign = next(node for node in built.character_trace_nodes if node.character_data_card_id != card.card_id)
    cross_blocked = assemble_character_build(
        rules,
        _build_input(card, profile, suffix="cross_character", trace_ids=(foreign.trace_node_id,), eidolon_level=0),
    )

    input_payload = build.to_json()
    mutable_ids = list(input_payload["unlocked_trace_node_ids"])
    input_payload["unlocked_trace_node_ids"] = mutable_ids
    isolated = CharacterBuildInput.from_json(input_payload)
    fingerprint = isolated.input_fingerprint
    mutable_ids.append("forged:after-construction")

    result_payload = result.to_json()
    specialization_tamper = False
    if result_payload["selector_specializations"]:
        result_payload["selector_specializations"][0]["predicate_value"] = not result_payload["selector_specializations"][0]["predicate_value"]
        specialization_tamper = _expect_rejected(lambda: CharacterBuildAssemblyResult.from_json(result_payload))
    legacy_payload = build.to_json()
    legacy_payload["enabled_trace_node_ids"] = []
    legacy_result = result.to_json()
    legacy_result["admitted_dynamic_mechanism_refs"] = []

    relation = built.character_build_selector_relations[0]
    bad_source = IRSource(
        source_path=relation.selector_source.source_path + ".forged",
        raw_type=relation.selector_source.raw_type,
        raw_id=relation.selector_source.raw_id,
        evidence=relation.selector_source.evidence,
    )
    return {
        "eidolon_out_of_range_rejected": _expect_rejected(lambda: replace(build, eidolon_level=7)),
        "default_trace_reselection_blocked": default_blocked is not None and default_blocked.assembly_status == "blocked",
        "trace_level_conflict_blocked": conflict_blocked is not None and conflict_blocked.assembly_status == "blocked",
        "cross_character_trace_blocked": cross_blocked.assembly_status == "blocked",
        "input_container_isolated": isolated.input_fingerprint == fingerprint and "forged:after-construction" not in isolated.unlocked_trace_node_ids,
        "specialization_tamper_rejected": specialization_tamper,
        "legacy_input_fields_rejected": _expect_rejected(lambda: CharacterBuildInput.from_json(legacy_payload)),
        "legacy_result_fields_rejected": _expect_rejected(lambda: CharacterBuildAssemblyResult.from_json(legacy_result)),
        "duplicate_relation_identity_rejected": _expect_rejected(lambda: replace(ir, character_build_selector_relations=(relation, *ir.character_build_selector_relations))),
        "selector_owner_tamper_rejected": _expect_rejected(lambda: replace(relation, owner_avatar_id="forged")),
        "selector_source_tamper_rejected": _expect_rejected(lambda: replace(relation, selector_source=bad_source)),
        "blocked_channels_empty": default_blocked is not None and default_blocked.base_panel is None and not default_blocked.contribution_ledger and not default_blocked.dynamic_graph_refs and not default_blocked.selector_specializations,
    }


def _runtime_boundary() -> dict[str, bool]:
    assembler_source = inspect.getsource(assemble_character_build)
    formal_sources = inspect.getsource(_formal_character_activation) + inspect.getsource(_plan_formal_character_birth)
    production_modules = (
        "simulator_v8_clean_core.builds.models",
        "simulator_v8_clean_core.builds.character_assembler",
        "simulator_v8_clean_core.scenarios.build_state",
        "simulator_v8_clean_core.queries.equipment",
    )
    importable = all(importlib.import_module(name) is not None for name in production_modules)
    return {
        "formal_helpers_do_not_read_legacy_selectors": not any(
            name in formal_sources
            for name in ("enabled_trace_node_ids", "disabled_trace_node_ids", "rank_ability", "skill_add_level_list")
        ),
        "assembler_is_only_formal_selector_consumer": "character_build_selector_relations_for_card" in inspect.getsource(importlib.import_module("simulator_v8_clean_core.builds.character_assembler")) and "enabled_trace_node_ids" not in assembler_source,
        "legacy_result_types_absent": all(
            name not in inspect.getsource(importlib.import_module(module))
            for module in production_modules
            for name in LEGACY_RESULT_NAMES
        ),
        "direct_consumers_importable": importable,
    }


def _run(root: Path) -> tuple[dict[str, object], dict[str, object]]:
    lowerer, catalog, scope, built, ir, rules, counters = _catalog_and_rules(root)
    oracle = _selector_oracle(root, lowerer, catalog, scope, built)
    assembly_rows, sample = _assembly_matrix(rules, built)
    if sample is None:
        raise ValueError("no assembled character build with a dynamic root was found")
    build, result = sample
    card = rules.character_data_card(build.character_card_id)
    negatives = _negative_matrix(ir, rules, built, sample)
    runtime = _runtime_boundary()

    assembled_rows = [row for row in assembly_rows if row["assembly_status"] == "assembled"]
    observations: dict[str, set[tuple[object, ...]]] = defaultdict(set)
    for row in assembled_rows:
        for relation_id, decision in row["selector_decisions"].items():
            observations[relation_id].add(tuple(decision))
    relation_by_id = {item.selector_relation_id: item for item in built.character_build_selector_relations}
    both_values = any(
        {bool(item[0]) for item in values} == {False, True}
        for values in observations.values()
    )
    both_branches = any(
        relation.true_subtree_path
        and relation.false_subtree_path
        and {str(item[2]) for item in observations.get(relation_id, ())}
        >= {relation.true_subtree_path, relation.false_subtree_path}
        for relation_id, relation in relation_by_id.items()
    )
    inverse_ids = {
        item.selector_relation_id
        for item in built.character_build_selector_relations
        if item.selector_value_when_selected is False
    }
    inverse_observed = not inverse_ids or any(observations.get(item) for item in inverse_ids)
    empty_branch_observed = any(not str(item[2]) and not str(item[3]) for values in observations.values() for item in values)
    roots_unique = all(bool(row["dynamic_roots_unique"]) for row in assembled_rows)
    root_and_specialization = any(bool(row["root_and_specialization_coexist"]) for row in assembled_rows)
    dynamic_payload_clean = all(bool(row["dynamic_payload_clean"]) for row in assembled_rows)
    static_channels_exact = all(bool(row["static_channel_exact"]) for row in assembled_rows)
    bindings_classified = all(
        binding.projection_kind in PROJECTION_KINDS
        for item in (*built.character_trace_nodes, *built.character_eidolon_slots)
        for binding in item.build_bindings
    )
    relation_selection_refs = {
        ref_id
        for relation in built.character_build_selector_relations
        for ref_id in relation.selection_ref_ids
    }
    content_classified = all(
        item.build_bindings
        or (
            item.trace_node_id if isinstance(item, CharacterTraceNodeIR) else item.eidolon_slot_id
        ) in relation_selection_refs
        for item in (*built.character_trace_nodes, *built.character_eidolon_slots)
    )
    admission_errors = validate_character_build_admission(rules, build, result)
    formal_blocked = _formal_birth_blocked(rules, card, build, result)

    predicates = {
        "final_build_selection_recursively_immutable": negatives["input_container_isolated"],
        "default_and_explicit_trace_not_double_applied": negatives["default_trace_reselection_blocked"],
        "trace_level_conflicts_rejected": negatives["trace_level_conflict_blocked"],
        "cross_character_content_rejected": negatives["cross_character_trace_blocked"],
        "static_and_dynamic_sources_separated": static_channels_exact and dynamic_payload_clean and roots_unique and root_and_specialization,
        "trace_and_eidolon_bindings_fully_classified": oracle["exact_partition"] is True and oracle["all_rows_passed"] is True and bindings_classified and content_classified,
        "unadmitted_dynamic_effect_blocks_battle": result.battle_admission_status == "blocked" and bool(result.dynamic_graph_refs) and formal_blocked,
        "blocked_result_has_no_executable_channels": negatives["blocked_channels_empty"],
        "runtime_build_selector_fallback_absent": all(runtime.values()),
        "assembly_fingerprint_covers_diagnostics": negatives["specialization_tamper_rejected"] and "assembly_result_does_not_match_canonical_rulebook_rebuild" not in admission_errors,
    }
    extra_checks = {
        "selector_match_true_and_false_observed": both_values,
        "both_raw_branches_specialized": both_branches,
        "inverse_selector_observed_or_real_source_absent": inverse_observed,
        "empty_branch_has_no_fake_root": empty_branch_observed,
        "all_negative_rows_passed": all(negatives.values()),
        "selector_oracle_nonempty": int(oracle["raw_selector_count"]) > 0,
        "no_full_lowering": counters["full_lowering_build_count"] == 0,
    }
    summary = {
        "schema_version": "p9_s2_validation_summary_v2",
        "ok": all(predicates.values()) and all(extra_checks.values()),
        "predicates": predicates,
        "extra_checks": extra_checks,
        "counts": {
            **counters,
            "character_card_count": len(built.character_data_cards),
            "trace_node_count": len(built.character_trace_nodes),
            "eidolon_slot_count": len(built.character_eidolon_slots),
            "assembled_variant_count": len(assembled_rows),
            "dynamic_root_count_in_sample": len(result.dynamic_graph_refs),
            "selector_specialization_count_in_sample": len(result.selector_specializations),
        },
        "selector_oracle": {key: value for key, value in oracle.items() if key != "rows"},
        "negative_matrix": negatives,
        "runtime_boundary": runtime,
        "sample": {
            "card_id": card.card_id,
            "build_id": build.build_id,
            "assembly_status": result.assembly_status,
            "battle_admission_status": result.battle_admission_status,
            "result_fingerprint": result.result_fingerprint,
        },
    }
    evidence = {
        "schema_version": "p9_s2_content_binding_evidence_v2",
        "selector_oracle_rows": oracle["rows"],
        "assembly_rows": assembly_rows,
    }
    return summary, evidence


def main() -> int:
    args = _parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    try:
        summary, evidence = _run(args.tbgd_root.resolve())
    except Exception as exc:  # pragma: no cover - CLI fail-closed evidence
        summary = {
            "schema_version": "p9_s2_validation_summary_v2",
            "ok": False,
            "fatal_error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc().splitlines(),
        }
        evidence = {"schema_version": "p9_s2_content_binding_evidence_v2", "rows": []}
    evidence_path = output_dir / "content_binding_evidence.json"
    summary_path = output_dir / "summary.json"
    _write_json(evidence_path, evidence)
    elapsed = time.perf_counter() - started
    rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    line_count = _nonempty_lines(Path(__file__))
    evidence_bytes = evidence_path.stat().st_size
    resources = {
        "wall_clock_seconds": round(elapsed, 3),
        "wall_clock_budget_seconds": WALL_CLOCK_BUDGET_SECONDS,
        "maximum_rss_bytes": rss_bytes,
        "maximum_rss_budget_bytes": RSS_BUDGET_BYTES,
        "evidence_bytes": evidence_bytes,
        "evidence_budget_bytes": EVIDENCE_BUDGET_BYTES,
        "validation_nonempty_lines": line_count,
        "validation_line_budget": VALIDATION_CODE_BUDGET_LINES,
    }
    resources["within_budget"] = (
        elapsed <= WALL_CLOCK_BUDGET_SECONDS
        and rss_bytes <= RSS_BUDGET_BYTES
        and evidence_bytes <= EVIDENCE_BUDGET_BYTES
        and line_count <= VALIDATION_CODE_BUDGET_LINES
    )
    summary["resources"] = resources
    summary["ok"] = bool(summary.get("ok")) and bool(resources["within_budget"])
    _write_json(summary_path, summary)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
