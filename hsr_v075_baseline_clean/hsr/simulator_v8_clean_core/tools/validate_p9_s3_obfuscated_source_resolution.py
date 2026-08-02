from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from ..immutable_json import thaw_json
from ..rules.expression_ir import NUMERIC_EXPRESSION_SCHEMA
from ..rules.ir import (
    CharacterAbilitySourceResolutionCatalogIR,
    CharacterDecodedSourceIR,
    CharacterEquivalentStructureEvidenceIR,
    character_ability_stable_id,
)
from ..tbgd.character_ability_scope import (
    build_character_ability_raw_snapshot,
    build_character_ability_scope_projection,
)
from ..tbgd.character_source_resolution import _family_resolutions
from ..tbgd.lowering import TBGDLowering


WALL_CLOCK_BUDGET_SECONDS = 8 * 60
RSS_BUDGET_BYTES = 1024 * 1024 * 1024
EVIDENCE_BUDGET_BYTES = 5 * 1024 * 1024
VALIDATION_CODE_BUDGET_LINES = 900


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the focused P9-S3 source-resolution contract."
    )
    parser.add_argument("--tbgd-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _nonempty_lines(path: Path) -> int:
    return sum(
        bool(line.strip()) for line in path.read_text(encoding="utf-8").splitlines()
    )


def _evidence_size(output_dir: Path) -> int:
    return sum(path.stat().st_size for path in output_dir.iterdir() if path.is_file())


def _expect_rejected(operation: Callable[[], object]) -> bool:
    try:
        operation()
    except (AttributeError, KeyError, TypeError, ValueError):
        return True
    return False


def _manifest_fingerprint(catalog: CharacterAbilitySourceResolutionCatalogIR) -> str:
    payload = [
        [path, catalog.package_manifest_digests[path], catalog.package_manifest_sizes[path]]
        for path in sorted(catalog.package_manifest_digests)
    ]
    return sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _runtime_handler_count(
    project_root: Path,
    obfuscated_families: frozenset[str],
) -> tuple[int, list[str]]:
    matches: list[str] = []
    for relative_root in ("core", "systems", "actions", "scenarios"):
        source_root = project_root / relative_root
        if not source_root.is_dir():
            continue
        for path in sorted(source_root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for family in sorted(obfuscated_families):
                if family in text:
                    matches.append(f"{path.relative_to(project_root).as_posix()}:{family}")
    return len(matches), matches


def _construction_matrix(
    catalog: CharacterAbilitySourceResolutionCatalogIR,
    scope_catalog: object,
) -> dict[str, bool]:
    first_item = catalog.decoded_items[0]
    first_reference = catalog.reference_resolutions[0]
    decoded_write = next(
        item for item in catalog.decoded_items if item.decoded_kind == "dynamic_value_write"
    )
    resolved_reference = next(
        item
        for item in catalog.reference_resolutions
        if item.outcome == "decoded_to_package"
    )
    task_reference = next(
        item
        for item in catalog.reference_resolutions
        if item.subject_kind == "ability_task_reference"
    )
    graph_gap_reference = next(
        item
        for item in catalog.reference_resolutions
        if item.subject_kind == "source_graph_gap"
    )
    candidate = catalog.definition_candidates[0]
    family_with_evidence = next(
        item for item in catalog.family_resolutions if item.candidate_evidence
    )
    equivalent = family_with_evidence.candidate_evidence[0]

    def source_evidence(source: object, **updates: object) -> object:
        evidence = dict(getattr(source, "evidence"))
        evidence.update(updates)
        return replace(source, evidence=evidence)

    def replace_reference_in_catalog(reference: object) -> object:
        return replace(
            catalog,
            reference_resolutions=tuple(
                reference
                if item.resolution_id == getattr(reference, "resolution_id")
                else item
                for item in catalog.reference_resolutions
            ),
        )

    def incompatible_evidence(
        item: CharacterEquivalentStructureEvidenceIR,
    ) -> CharacterEquivalentStructureEvidenceIR:
        field_name = next(iter(item.field_role_mapping))
        roles = {field_name: item.field_role_mapping[field_name]}
        evidence = item.source.evidence
        evidence_id = character_ability_stable_id(
            "character_equivalent_structure_evidence",
            item.raw_type,
            item.source.source_path,
            evidence["json_path"],
            evidence["content_sha256"],
            *item.observed_fields,
            *(f"{key}:{roles[key]}" for key in sorted(roles)),
        )
        return replace(
            item,
            evidence_id=evidence_id,
            field_role_mapping=roles,
            source=replace(item.source, raw_id=evidence_id),
        )

    evidence_by_type = {
        raw_type: tuple(
            evidence
            for family in catalog.family_resolutions
            for evidence in family.candidate_evidence
            if evidence.raw_type == raw_type
        )
        for raw_type in (
            "RPG.GameCore.DefineDynamicValue",
            "RPG.GameCore.SetDynamicValue",
            "RPG.GameCore.TargetAlias",
        )
    }

    def family_outcome(
        family: str,
        scope_records: tuple[object, ...],
        evidence: dict[str, tuple[CharacterEquivalentStructureEvidenceIR, ...]],
    ) -> str:
        rows, _ = _family_resolutions(
            SimpleNamespace(scope_records=scope_records),  # type: ignore[arg-type]
            evidence,
        )
        return next(item.outcome for item in rows if item.family == family)

    dynamic_incompatible = dict(evidence_by_type)
    for raw_type in (
        "RPG.GameCore.DefineDynamicValue",
        "RPG.GameCore.SetDynamicValue",
    ):
        dynamic_incompatible[raw_type] = (
            incompatible_evidence(evidence_by_type[raw_type][0]),
        )
    scope_records = tuple(getattr(scope_catalog, "scope_records"))
    ik_record = next(item for item in scope_records if item.family == "IKDAKCBKFAB")
    metric_records = tuple(
        replace(
            item,
            raw_fields={
                **thaw_json(item.raw_fields),
                "GMPGDEINODK": "forged_metric",
            },
        )
        if item.record_id == ik_record.record_id
        else item
        for item in scope_records
    )
    foreign_parent = next(
        item
        for item in scope_records
        if item.family not in {"IKDAKCBKFAB", "TurnInsertAction"}
    )
    context_records = tuple(
        replace(item, parent_record_id=foreign_parent.record_id)
        if item.record_id == ik_record.record_id
        else item
        for item in scope_records
    )
    write_payload = thaw_json(decoded_write.payload)
    write_expression = dict(write_payload["value_expression"])
    write_expression["forged_extra"] = True
    forged_expression_payload = {
        **write_payload,
        "value_expression": write_expression,
    }
    forged_instruction_payload = {
        **write_payload,
        "value_expression": {
            "schema_version": NUMERIC_EXPRESSION_SCHEMA,
            "kind": "program",
            "supported": True,
            "instructions": [
                {"opcode": "push_fixed", "value": 1.0, "forged_extra": True},
                {"opcode": "end"},
            ],
        },
    }
    alternate_owner = next(
        owner
        for owner in (
            "character_presentation_ability",
            "character_ability",
            "shared_activity_ability",
            "shared_ability_package",
        )
        if owner != resolved_reference.package_owner
    )
    valid_owner_mismatch = replace(
        resolved_reference,
        package_owner=alternate_owner,
    )
    checks = {
        "decoded_payload_recursively_immutable": _expect_rejected(
            lambda: first_item.payload.__setitem__("forged", True)  # type: ignore[attr-defined]
        ),
        "runtime_admission_cannot_be_enabled": _expect_rejected(
            lambda: replace(first_item, runtime_admission="admitted")  # type: ignore[arg-type]
        ),
        "decode_coverage_cannot_drop_record": _expect_rejected(
            lambda: replace(
                catalog,
                decode_required_record_ids=catalog.decode_required_record_ids[:-1],
            )
        ),
        "resolved_reference_requires_candidate": _expect_rejected(
            lambda: replace(first_reference, candidate_ids=())
            if first_reference.outcome != "source_gap_blocked"
            else replace(
                next(
                    item
                    for item in catalog.reference_resolutions
                    if item.outcome == "decoded_to_package"
                ),
                candidate_ids=(),
            )
        ),
        "definition_candidate_forged_json_path_rejected": _expect_rejected(
            lambda: replace(
                candidate,
                source=source_evidence(candidate.source, json_path="$.forged"),
            )
        ),
        "decoded_forged_source_path_rejected": _expect_rejected(
            lambda: replace(
                first_item,
                source=replace(
                    first_item.source,
                    source_path="Config/ConfigAbility/forged.json",
                ),
            )
        ),
        "reference_arbitrary_package_owner_rejected": _expect_rejected(
            lambda: replace(resolved_reference, package_owner="forged_package")
        ),
        "decoded_arbitrary_package_owner_rejected": _expect_rejected(
            lambda: replace(first_item, package_owner="forged_package")
        ),
        "decoded_valid_but_wrong_package_owner_rejected": _expect_rejected(
            lambda: replace(
                first_item,
                package_owner=(
                    "character_action_queue"
                    if first_item.package_owner != "character_action_queue"
                    else "character_target_expression"
                ),
            )
        ),
        "valid_but_mismatched_reference_owner_rejected_by_catalog": _expect_rejected(
            lambda: replace_reference_in_catalog(valid_owner_mismatch)
        ),
        "numeric_expression_extra_field_rejected": _expect_rejected(
            lambda: replace(decoded_write, payload=forged_expression_payload)
        ),
        "numeric_instruction_extra_field_rejected": _expect_rejected(
            lambda: replace(decoded_write, payload=forged_instruction_payload)
        ),
        "string_equivalent_evidence_rejected": _expect_rejected(
            lambda: replace(
                family_with_evidence,
                candidate_evidence=("Config/ConfigAbility/forged.json:$.forged",),
            )
        ),
        "equivalent_forged_source_path_rejected": _expect_rejected(
            lambda: replace(
                equivalent,
                source=replace(
                    equivalent.source,
                    source_path="Config/ConfigAbility/forged.json",
                ),
            )
        ),
        "equivalent_forged_json_path_rejected": _expect_rejected(
            lambda: replace(
                equivalent,
                source=source_evidence(equivalent.source, json_path="$.forged"),
            )
        ),
        "equivalent_forged_digest_rejected": _expect_rejected(
            lambda: replace(
                equivalent,
                source=source_evidence(
                    equivalent.source,
                    content_sha256="0" * 64,
                ),
            )
        ),
        "equivalent_forged_field_role_rejected": _expect_rejected(
            lambda: replace(
                equivalent,
                field_role_mapping={
                    next(iter(equivalent.field_role_mapping)): "forged_role"
                },
            )
        ),
        "ability_task_reference_identity_recomputed": _expect_rejected(
            lambda: replace(
                task_reference,
                source=source_evidence(task_reference.source, json_path="$.forged"),
            )
        ),
        "source_graph_gap_identity_recomputed": _expect_rejected(
            lambda: replace(
                graph_gap_reference,
                source_graph_gap_kind=(
                    "lowering_gap"
                    if graph_gap_reference.source_graph_gap_kind != "lowering_gap"
                    else "source_gap_blocked"
                ),
            )
        ),
        "dynamic_value_incompatible_candidate_blocks_family": (
            family_outcome("LAJIKDENEOO", scope_records, dynamic_incompatible)
            == "source_gap_blocked"
            and family_outcome("NKLOMENKLHK", scope_records, dynamic_incompatible)
            == "source_gap_blocked"
        ),
        "queue_precheck_metric_change_blocks_family": family_outcome(
            "IKDAKCBKFAB", metric_records, evidence_by_type
        )
        == "source_gap_blocked",
        "queue_precheck_context_change_blocks_family": family_outcome(
            "IKDAKCBKFAB", context_records, evidence_by_type
        )
        == "source_gap_blocked",
        "catalog_json_is_deterministic": catalog.to_json() == catalog.to_json(),
    }
    return checks


def main() -> int:
    args = _parse_args()
    started = time.perf_counter()
    root = args.tbgd_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    full_lowering_calls: list[str] = []
    original_full_build = TBGDLowering.build

    def forbidden_full_build(*_args: Any, **_kwargs: Any) -> Any:
        full_lowering_calls.append("TBGDLowering.build")
        raise AssertionError("P9-S3 focused validation invoked full lowering")

    TBGDLowering.build = forbidden_full_build  # type: ignore[assignment]
    try:
        snapshot = build_character_ability_raw_snapshot(root)
        scope_catalog = build_character_ability_scope_projection(root, snapshot=snapshot)
        lowering = TBGDLowering(root)
        source_graph = lowering.build_character_ability_source_graph_catalog(
            snapshot=snapshot,
            scope_catalog=scope_catalog,
        )
        catalog = lowering.build_character_ability_source_resolution_catalog(
            snapshot=snapshot,
            scope_catalog=scope_catalog,
            source_graph_catalog=source_graph,
        )
        cached_catalog = lowering.build_character_ability_source_resolution_catalog()
    finally:
        TBGDLowering.build = original_full_build  # type: ignore[assignment]

    current_decode_records = tuple(
        record
        for record in scope_catalog.scope_records
        if record.effective_scope == "decode_required"
        and record.materialization_role == "selected"
    )
    current_decode_ids = {record.record_id for record in current_decode_records}
    current_families = {record.family for record in current_decode_records}
    resolved_record_ids = {
        record_id
        for resolution in catalog.family_resolutions
        for record_id in resolution.scope_record_ids
    }
    decoded_family_rows = tuple(
        resolution
        for resolution in catalog.family_resolutions
        if resolution.outcome == "decoded_to_package"
    )
    blocked_family_rows = tuple(
        resolution
        for resolution in catalog.family_resolutions
        if resolution.outcome == "source_gap_blocked"
    )
    decoded_ids = {item.decoded_id for item in catalog.decoded_items}
    published_decoded_ids = {
        decoded_id
        for resolution in decoded_family_rows
        for decoded_id in resolution.decoded_item_ids
    }
    decoded_record_ids = {item.scope_record_id for item in catalog.decoded_items}
    blocked_record_ids = {
        record_id
        for resolution in blocked_family_rows
        for record_id in resolution.scope_record_ids
    }
    typed_owner_ok = all(
        type(item) is CharacterDecodedSourceIR
        and item.package_owner
        and item.runtime_admission == "not_admitted"
        and item.to_json()["coverage_status"] == "lowered"
        for item in catalog.decoded_items
    )
    blocked_families_ok = all(
        not resolution.decoded_item_ids
        and not resolution.package_owner
        and bool(resolution.blocked_reason)
        for resolution in blocked_family_rows
    )

    manifest_paths = set(catalog.package_manifest_digests)
    current_package_paths = {
        path.relative_to(root).as_posix()
        for path in (root / catalog.package_search_root).rglob("*.json")
        if path.is_file()
    }
    reference_subjects = {
        (resolution.subject_kind, resolution.subject_id)
        for resolution in catalog.reference_resolutions
    }
    expected_reference_subjects = {
        ("source_graph_gap", gap_id) for gap_id in catalog.source_graph_gap_ids
    } | {
        ("ability_task_reference", reference_id)
        for reference_id in catalog.unresolved_reference_ids
    }
    candidate_ids = {
        candidate.candidate_id for candidate in catalog.definition_candidates
    }
    reference_candidate_ids = {
        candidate_id
        for resolution in catalog.reference_resolutions
        for candidate_id in resolution.candidate_ids
    }
    reference_outcomes_ok = all(
        (
            resolution.outcome in {"decoded_to_package", "non_gameplay"}
            and len(resolution.candidate_ids) == 1
            and bool(resolution.package_owner)
            and not resolution.blocked_reason
        )
        or (
            resolution.outcome == "source_gap_blocked"
            and not resolution.package_owner
            and bool(resolution.blocked_reason)
        )
        for resolution in catalog.reference_resolutions
    )
    true_missing = tuple(
        resolution
        for resolution in catalog.reference_resolutions
        if resolution.blocked_reason
        == "ability_definition_absent_after_complete_package_search"
    )
    relationship_gaps = tuple(
        resolution
        for resolution in catalog.reference_resolutions
        if resolution.blocked_reason.startswith("s1_relationship_gap:")
    )

    implementation_path = (
        Path(__file__).resolve().parents[1] / "tbgd" / "character_source_resolution.py"
    )
    implementation_text = implementation_path.read_text(encoding="utf-8")
    forbidden_rule_sources = (
        "simulator_v7",
        "model_pack_v3_0",
        "TextMap",
        "observed_damage",
        "observation_answer",
    )
    text_or_observation_used = any(
        token in implementation_text for token in forbidden_rule_sources
    )
    obfuscated_families = frozenset(
        record.family
        for record in current_decode_records
        if record.source.evidence.get("nominal_semantic_kind")
        == "combat_decode_required"
    )
    runtime_handler_count, runtime_handler_matches = _runtime_handler_count(
        Path(__file__).resolve().parents[1], obfuscated_families
    )
    construction = _construction_matrix(catalog, scope_catalog)

    predicates: dict[str, object] = {
        "decode_required_set_current": (
            bool(current_decode_ids)
            and current_decode_ids == set(catalog.decode_required_record_ids)
            and current_families
            == {resolution.family for resolution in catalog.family_resolutions}
            and snapshot.source_fingerprint == catalog.source_fingerprint
        ),
        "all_decode_items_have_structured_resolution": (
            catalog.all_decode_items_have_structured_resolution
            and resolved_record_ids == current_decode_ids
        ),
        "decoded_items_have_typed_ir_and_package_owner": (
            bool(decoded_family_rows)
            and typed_owner_ok
            and decoded_ids == published_decoded_ids
            and all(
                len(resolution.scope_record_ids)
                == len(resolution.decoded_item_ids)
                for resolution in decoded_family_rows
            )
        ),
        "undecoded_items_remain_blocked": (
            bool(blocked_family_rows)
            and blocked_families_ok
            and decoded_record_ids.isdisjoint(blocked_record_ids)
            and decoded_record_ids | blocked_record_ids == current_decode_ids
        ),
        "missing_ability_search_closure_complete": (
            catalog.missing_ability_search_closure_complete
            and manifest_paths == current_package_paths
            and reference_subjects == expected_reference_subjects
            and candidate_ids == reference_candidate_ids
            and reference_outcomes_ok
        ),
        "source_gap_not_caused_by_scan_or_lowering": (
            catalog.build_counters["package_file_read_count"] == len(manifest_paths)
            and catalog.build_counters["package_file_parse_count"]
            == len(manifest_paths)
            and catalog.build_counters["package_scan_error_count"] == 0
            and catalog.build_counters["lowering_gap_count"] == 0
            and source_graph.current_bindings_fully_classified
            and not full_lowering_calls
            and cached_catalog is catalog
        ),
        "text_or_observation_used_as_rule_source": text_or_observation_used,
        "obfuscated_specific_runtime_handlers": runtime_handler_count,
    }
    business_ok = (
        all(
            predicates[key] is True
            for key in (
                "decode_required_set_current",
                "all_decode_items_have_structured_resolution",
                "decoded_items_have_typed_ir_and_package_owner",
                "undecoded_items_remain_blocked",
                "missing_ability_search_closure_complete",
                "source_gap_not_caused_by_scan_or_lowering",
            )
        )
        and predicates["text_or_observation_used_as_rule_source"] is False
        and predicates["obfuscated_specific_runtime_handlers"] == 0
        and all(construction.values())
    )

    family_evidence = [resolution.to_json() for resolution in catalog.family_resolutions]
    reference_evidence = [
        resolution.to_json() for resolution in catalog.reference_resolutions
    ]
    search_evidence = {
        "search_root": catalog.package_search_root,
        "manifest_file_count": len(manifest_paths),
        "manifest_byte_count": sum(catalog.package_manifest_sizes.values()),
        "manifest_fingerprint": _manifest_fingerprint(catalog),
        "requested_name_count": catalog.build_counters["requested_ability_name_count"],
        "definition_candidate_count": len(catalog.definition_candidates),
        "source_graph_gap_count": len(catalog.source_graph_gap_ids),
        "unresolved_task_reference_count": len(catalog.unresolved_reference_ids),
        "true_missing_references": [
            {
                "ability_name": item.ability_name,
                "source_path": item.source.source_path,
                "json_path": item.source.evidence.get("json_path"),
                "subject_kind": item.subject_kind,
            }
            for item in true_missing
        ],
        "relationship_gaps": [
            {
                "ability_name": item.ability_name,
                "blocked_reason": item.blocked_reason,
                "candidate_count": len(item.candidate_ids),
            }
            for item in relationship_gaps
        ],
    }
    _write_json(output_dir / "family_resolution.json", family_evidence)
    _write_json(output_dir / "ability_reference_resolution.json", reference_evidence)
    _write_json(output_dir / "source_search_summary.json", search_evidence)
    _write_json(
        output_dir / "negative_matrix.json",
        {
            "construction": construction,
            "runtime_handler_matches": runtime_handler_matches,
            "forbidden_rule_source_tokens": list(forbidden_rule_sources),
        },
    )

    wall_seconds = time.perf_counter() - started
    max_rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    validation_code_lines = _nonempty_lines(Path(__file__))
    evidence_before_summary = _evidence_size(output_dir)
    resource_checks = {
        "wall_clock_within_budget": wall_seconds < WALL_CLOCK_BUDGET_SECONDS,
        "rss_within_budget": max_rss_bytes < RSS_BUDGET_BYTES,
        "evidence_within_budget": evidence_before_summary < EVIDENCE_BUDGET_BYTES,
        "validation_code_within_budget": validation_code_lines
        <= VALIDATION_CODE_BUDGET_LINES,
    }
    ok = business_ok and all(resource_checks.values())
    summary: dict[str, Any] = {
        "ok": ok,
        "business_ok": business_ok,
        "ready_for_review": ok,
        "predicates": predicates,
        "counts": {
            "decode_required_families": len(current_families),
            "decode_required_records": len(current_decode_ids),
            "decoded_families": len(decoded_family_rows),
            "decoded_records": len(decoded_record_ids),
            "blocked_families": len(blocked_family_rows),
            "blocked_records": len(blocked_record_ids),
            "source_graph_gaps": len(catalog.source_graph_gap_ids),
            "unresolved_task_references": len(catalog.unresolved_reference_ids),
            "true_missing_references": len(true_missing),
            "relationship_gaps": len(relationship_gaps),
            "non_gameplay_resolutions": sum(
                resolution.outcome == "non_gameplay"
                for resolution in catalog.reference_resolutions
            ),
        },
        "catalog_id": catalog.catalog_id,
        "source_fingerprint": catalog.source_fingerprint,
        "construction_checks": construction,
        "build_counters": dict(catalog.build_counters),
        "resources": {
            "wall_seconds": round(wall_seconds, 6),
            "max_rss_bytes": max_rss_bytes,
            "evidence_bytes_before_summary": evidence_before_summary,
            "validation_code_lines": validation_code_lines,
            "budgets": {
                "wall_seconds": WALL_CLOCK_BUDGET_SECONDS,
                "max_rss_bytes": RSS_BUDGET_BYTES,
                "evidence_bytes": EVIDENCE_BUDGET_BYTES,
                "validation_code_lines": VALIDATION_CODE_BUDGET_LINES,
            },
            "checks": resource_checks,
        },
        "evidence_files": sorted(path.name for path in output_dir.iterdir()),
    }
    _write_json(output_dir / "summary.json", summary)
    summary["resources"]["evidence_bytes"] = _evidence_size(output_dir)
    summary["evidence_files"] = sorted(path.name for path in output_dir.iterdir())
    _write_json(output_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
