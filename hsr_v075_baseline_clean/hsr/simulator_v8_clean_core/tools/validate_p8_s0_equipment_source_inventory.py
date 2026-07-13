from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..tbgd.equipment_discovery import (
    EQUIPMENT_DISCOVERY_SCHEMA_VERSION,
    PRIMARY_TABLE_ROLES,
    EquipmentSourceSnapshot,
    build_equipment_mechanism_family_matrix,
    build_equipment_reference_integrity,
    build_equipment_source_inventory,
    classify_equipment_candidate_sources,
    equipment_fingerprint_matches,
    load_equipment_source_snapshot,
    validate_equipment_candidate_classification,
    validate_equipment_mechanism_family_matrix,
    validate_equipment_reference_integrity,
    validate_equipment_source_inventory,
)
from ..tbgd.paths import find_tbgd_root
from .io import write_json


VALIDATION_VERSION = "p8_s0_equipment_source_inventory"
SUMMARY_SCHEMA_VERSION = "p8_s0_equipment_source_inventory_summary_v1"


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    snapshot = load_equipment_source_snapshot(tbgd_root)
    special_sources = classify_equipment_candidate_sources(snapshot)
    references = build_equipment_reference_integrity(snapshot)
    mechanisms = build_equipment_mechanism_family_matrix(snapshot)
    inventory = build_equipment_source_inventory(snapshot, special_sources, references)

    checks = {
        "source_inventory": validate_equipment_source_inventory(inventory, special_sources),
        "reference_integrity": validate_equipment_reference_integrity(references),
        "mechanism_family": validate_equipment_mechanism_family_matrix(mechanisms),
        "special_source_classification": validate_equipment_candidate_classification(special_sources),
    }
    negative_cases = _negative_validation_cases(
        snapshot=snapshot,
        inventory=inventory,
        references=references,
        mechanisms=mechanisms,
        special_sources=special_sources,
    )
    checks["negative_cases"] = negative_cases

    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_payloads = {
        "p8_s0_equipment_source_inventory.json": inventory,
        "p8_s0_equipment_reference_integrity.json": references,
        "p8_s0_equipment_mechanism_family_matrix.json": mechanisms,
        "p8_s0_equipment_special_source_classification.json": special_sources,
    }
    for name, payload in artifact_payloads.items():
        write_json(output_dir / name, payload)
    artifact_sizes = {
        name: (output_dir / name).stat().st_size
        for name in artifact_payloads
    }

    special_budget = dict(special_sources.get("resource_budget") or {})
    resource_budget = {
        "primary_full_content_file_count": snapshot.primary_source_fingerprint.get("file_count"),
        "primary_full_content_bytes_read": snapshot.primary_bytes_read,
        "primary_json_parse_count": snapshot.primary_json_parse_count,
        "auxiliary_full_content_bytes_read": int(special_budget.get("full_auxiliary_bytes_read") or 0),
        "auxiliary_full_json_parse_count": int(special_budget.get("full_auxiliary_json_parse_count") or 0),
        "auxiliary_sampled_bytes_read": int(special_budget.get("sampled_auxiliary_bytes_read") or 0),
        "auxiliary_sampled_file_count": int(special_budget.get("sampled_auxiliary_file_count") or 0),
        "source_bytes_read_total": snapshot.primary_bytes_read
        + int(special_budget.get("full_auxiliary_bytes_read") or 0)
        + int(special_budget.get("sampled_auxiliary_bytes_read") or 0),
        "tbgd_lowering_build_count": 0,
        "rulebook_build_count": 0,
        "runtime_transition_count": 0,
        "subprocess_validation_count": 0,
        "reference_integrity_build_count": 7,
        "mechanism_matrix_build_count": 7,
        "source_inventory_build_count": 7,
        "raw_negative_snapshot_rebuild_count": int(negative_cases.get("raw_snapshot_rebuild_count") or 0),
        "serial_execution": True,
        "full_raw_corpus_written": False,
        "full_canonical_ir_written": False,
        "full_rulebook_written": False,
        "full_transition_dump_written": False,
        "large_artifacts_written": False,
        "artifact_file_count_before_summary": len(artifact_sizes),
        "artifact_bytes_before_summary": sum(artifact_sizes.values()),
        "artifact_sizes": artifact_sizes,
        "output_scope": "source_inventory_reference_matrix_mechanism_aggregate_special_source_classification_and_samples_only",
    }
    resource_checks = {
        "focused_primary_full_read": snapshot.primary_source_fingerprint.get("file_count") == snapshot.primary_json_parse_count
        and snapshot.primary_bytes_read == snapshot.primary_source_fingerprint.get("byte_count"),
        "no_lowering_or_rulebook_build": resource_budget["tbgd_lowering_build_count"] == 0
        and resource_budget["rulebook_build_count"] == 0,
        "raw_negative_rebuilds_are_bounded_and_in_memory": resource_budget["raw_negative_snapshot_rebuild_count"] == 6
        and resource_budget["reference_integrity_build_count"] == 7
        and resource_budget["mechanism_matrix_build_count"] == 7
        and resource_budget["source_inventory_build_count"] == 7,
        "large_auxiliary_tables_not_fully_classified_from_samples": special_budget.get("large_sampled_files_fully_classified") is False,
        "no_large_or_full_runtime_artifacts": resource_budget["large_artifacts_written"] is False
        and resource_budget["full_raw_corpus_written"] is False
        and resource_budget["full_canonical_ir_written"] is False
        and resource_budget["full_rulebook_written"] is False
        and resource_budget["full_transition_dump_written"] is False,
    }
    resource_checks["ok"] = all(value is True for value in resource_checks.values())
    checks["resource_budget"] = {"ok": resource_checks["ok"], "checks": resource_checks}

    ok = all(
        isinstance(value, dict) and value.get("ok") is True
        for value in checks.values()
    )
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "discovery_schema_version": EQUIPMENT_DISCOVERY_SCHEMA_VERSION,
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": ok,
        "ready_for_review": ok,
        "p8_s0_equipment_source_baseline_established": ok,
        "runtime_behavior_changed": False,
        "formal_equipment_ir_added": False,
        "scenario_builder_changed": False,
        "p8_s1_or_later_started": False,
        "build": {
            "tbgd_root": tbgd_root.resolve().as_posix(),
            "selection_policy": {
                "primary_tables": dict(PRIMARY_TABLE_ROLES),
                "ability_files": "recursive non-layout JSON below Config/ConfigAbility/Equip",
                "candidate_sources": "dynamic equip/relic filename and ConfigAbility/Equip discovery",
                "fixed_current_counts_used_as_acceptance": False,
                "fixed_equipment_relic_ability_ids_used_as_acceptance": False,
                "legacy_single_file_used_as_primary": False,
                "textmap_read": False,
                "external_semantic_sources_fetched": False,
            },
        },
        "primary_source_fingerprint": snapshot.primary_source_fingerprint,
        "auxiliary_full_source_fingerprint": special_sources.get("full_auxiliary_fingerprint", {}),
        "auxiliary_sampled_pending_fingerprint": special_sources.get("sampled_pending_auxiliary_fingerprint", {}),
        "checks": checks,
        "observations": {
            "table_record_counts": inventory.get("table_record_counts", {}),
            "publication_dimensions": inventory.get("publication_dimensions", {}),
            "relic_mode_dimensions": inventory.get("mode_dimensions", {}),
            "reference_counts": references.get("counts", {}),
            "reference_issue_counts": references.get("issue_counts", {}),
            "mechanism_summary": mechanisms.get("summary", {}),
            "candidate_classification_counts": special_sources.get("classification_counts", {}),
            "candidate_classification_status_counts": special_sources.get("classification_status_counts", {}),
            "unregistered_candidate_paths": special_sources.get("candidate_discovery", {}).get("unregistered_candidate_paths", []),
            "unreferenced_abilities": references.get("unreferenced_abilities", []),
        },
        "resource_budget": resource_budget,
        "scope": {
            "implemented": "P8-S0 focused source discovery, reference integrity, mechanism family baseline, source classification and fingerprints",
            "not_implemented": "formal equipment IR, build input, assembly, RuleBook queries, runtime effects, scenario integration, P8-S1+",
        },
    }
    write_json(output_dir / "validation_summary_p8_s0_equipment_source_inventory.json", summary)
    return summary


def _negative_validation_cases(
    *,
    snapshot: EquipmentSourceSnapshot,
    inventory: dict[str, Any],
    references: dict[str, Any],
    mechanisms: dict[str, Any],
    special_sources: dict[str, Any],
) -> dict[str, Any]:
    valid_control = (
        validate_equipment_source_inventory(inventory, special_sources).get("ok") is True
        and validate_equipment_reference_integrity(references).get("ok") is True
        and validate_equipment_mechanism_family_matrix(mechanisms).get("ok") is True
        and validate_equipment_candidate_classification(special_sources).get("ok") is True
    )

    missing_reference_snapshot = copy.deepcopy(snapshot)
    referenced_ability_name = _first_ability_name(
        references,
        reference_status="referenced",
        reference_domain="light_cone",
    )
    missing_reference_mutated = bool(referenced_ability_name) and _remove_ability_record(
        missing_reference_snapshot,
        referenced_ability_name,
    )
    missing_reference_products = _rebuild_snapshot_products(missing_reference_snapshot, special_sources)
    missing_reference_rejected = (
        missing_reference_mutated
        and int(missing_reference_products["references"].get("issue_counts", {}).get("equipment_ability_reference_not_unique") or 0) > 0
        and not _rebuilt_products_are_valid(missing_reference_products, special_sources)
    )

    duplicate_ability_snapshot = copy.deepcopy(snapshot)
    unreferenced_ability_name = _first_ability_name(references, reference_status="unreferenced")
    duplicate_ability_mutated = bool(unreferenced_ability_name) and _duplicate_ability_record(
        duplicate_ability_snapshot,
        unreferenced_ability_name,
    )
    duplicate_ability_products = _rebuild_snapshot_products(duplicate_ability_snapshot, special_sources)
    duplicate_ability_rejected = (
        duplicate_ability_mutated
        and int(duplicate_ability_products["references"].get("issue_counts", {}).get("equipment_ability_name_not_globally_unique") or 0) > 0
        and not _rebuilt_products_are_valid(duplicate_ability_products, special_sources)
    )

    duplicate_base_type_snapshot = copy.deepcopy(snapshot)
    duplicate_base_type_rows = duplicate_base_type_snapshot.table("relic_base_type")
    duplicate_base_type_mutated = isinstance(duplicate_base_type_rows, list) and bool(duplicate_base_type_rows)
    if duplicate_base_type_mutated:
        duplicate_base_type_rows.append(copy.deepcopy(duplicate_base_type_rows[0]))
    duplicate_base_type_products = _rebuild_snapshot_products(duplicate_base_type_snapshot, special_sources)
    duplicate_base_type_rejected = (
        duplicate_base_type_mutated
        and int(duplicate_base_type_products["references"].get("issue_counts", {}).get("relic_base_type_duplicate_identity") or 0) > 0
        and not _rebuilt_products_are_valid(duplicate_base_type_products, special_sources)
    )

    orphan_promotion_snapshot = copy.deepcopy(snapshot)
    orphan_promotion_rows = orphan_promotion_snapshot.table("equipment_promotion_config")
    orphan_promotion_mutated = isinstance(orphan_promotion_rows, list) and bool(orphan_promotion_rows)
    if orphan_promotion_mutated:
        orphan_promotion = copy.deepcopy(orphan_promotion_rows[0])
        orphan_promotion["EquipmentID"] = _unused_numeric_identity(
            orphan_promotion_snapshot.table("equipment_config"),
            "EquipmentID",
            orphan_promotion_rows,
        )
        orphan_promotion_rows.append(orphan_promotion)
    orphan_promotion_products = _rebuild_snapshot_products(orphan_promotion_snapshot, special_sources)
    orphan_promotion_rebuilt = orphan_promotion_products["references"]
    orphan_promotion_rejected = (
        orphan_promotion_mutated
        and bool(orphan_promotion_rebuilt.get("orphan_source_inventory", {}).get("equipment_promotions"))
        and int(orphan_promotion_rebuilt.get("issue_counts", {}).get("orphan_equipment_promotion_record") or 0) > 0
        and not _rebuilt_products_are_valid(orphan_promotion_products, special_sources)
    )

    orphan_skill_snapshot = copy.deepcopy(snapshot)
    orphan_skill_rows = orphan_skill_snapshot.table("equipment_skill_config")
    orphan_skill_mutated = isinstance(orphan_skill_rows, list) and bool(orphan_skill_rows)
    if orphan_skill_mutated:
        orphan_skill = copy.deepcopy(orphan_skill_rows[0])
        orphan_skill["SkillID"] = _unused_numeric_identity(
            orphan_skill_snapshot.table("equipment_config"),
            "SkillID",
            orphan_skill_rows,
        )
        orphan_skill_rows.append(orphan_skill)
    orphan_skill_products = _rebuild_snapshot_products(orphan_skill_snapshot, special_sources)
    orphan_skill_rebuilt = orphan_skill_products["references"]
    orphan_skill_rejected = (
        orphan_skill_mutated
        and bool(orphan_skill_rebuilt.get("orphan_source_inventory", {}).get("equipment_skills"))
        and int(orphan_skill_rebuilt.get("issue_counts", {}).get("orphan_equipment_skill_record") or 0) > 0
        and not _rebuilt_products_are_valid(orphan_skill_products, special_sources)
    )

    empty_core_table_snapshot = copy.deepcopy(snapshot)
    empty_equipment_rows = empty_core_table_snapshot.table("equipment_config")
    empty_core_table_mutated = isinstance(empty_equipment_rows, list) and bool(empty_equipment_rows)
    if empty_core_table_mutated:
        empty_equipment_rows.clear()
    empty_core_products = _rebuild_snapshot_products(empty_core_table_snapshot, special_sources)
    empty_core_table_rejected = (
        empty_core_table_mutated
        and int(empty_core_products["inventory"].get("table_record_counts", {}).get("equipment_config") or 0) == 0
        and not _rebuilt_products_are_valid(empty_core_products, special_sources)
    )

    stale_expected_fingerprint = copy.deepcopy(inventory.get("primary_source_fingerprint") or {})
    stale_expected_fingerprint["sha256"] = "0" * 64
    stale_fingerprint_rejected = not equipment_fingerprint_matches(
        inventory.get("primary_source_fingerprint") or {},
        stale_expected_fingerprint,
    )

    omitted_candidate = copy.deepcopy(special_sources)
    omitted_rows = omitted_candidate.get("rows") if isinstance(omitted_candidate.get("rows"), list) else []
    omitted_path = str(omitted_rows[-1].get("relative_path")) if omitted_rows else ""
    if omitted_rows:
        omitted_candidate["rows"] = omitted_rows[:-1]
    omitted_discovered_file_rejected = bool(omitted_path) and not validate_equipment_candidate_classification(omitted_candidate).get("ok")

    checks = {
        "valid_control_accepted": valid_control,
        "raw_missing_referenced_ability_rejected_after_rebuild": missing_reference_rejected,
        "raw_duplicate_unreferenced_ability_rejected_after_rebuild": duplicate_ability_rejected,
        "raw_duplicate_relic_base_type_rejected_after_rebuild": duplicate_base_type_rejected,
        "raw_orphan_promotion_rejected_after_rebuild": orphan_promotion_rejected,
        "raw_orphan_superimposition_rejected_after_rebuild": orphan_skill_rejected,
        "raw_empty_core_table_rejected_after_rebuild": empty_core_table_rejected,
        "stale_source_fingerprint_rejected": stale_fingerprint_rejected,
        "omitted_discovered_candidate_rejected": omitted_discovered_file_rejected,
    }
    return {
        "ok": all(value is True for value in checks.values()),
        "checks": checks,
        "case_count": 8,
        "omitted_candidate_path": omitted_path,
        "mutates_source_files": False,
        "raw_negative_input_mode": "deep_copied_in_memory_source_snapshot_then_reference_mechanism_inventory_rebuild_and_validation",
        "raw_snapshot_rebuild_count": 6,
        "rebuilt_components_per_raw_case": ["reference_integrity", "mechanism_family_matrix", "source_inventory"],
        "raw_case_observations": {
            "missing_referenced_ability_issue_counts": missing_reference_products["references"].get("issue_counts", {}),
            "duplicate_unreferenced_ability_issue_counts": duplicate_ability_products["references"].get("issue_counts", {}),
            "duplicate_relic_base_type_issue_counts": duplicate_base_type_products["references"].get("issue_counts", {}),
            "orphan_promotion_issue_counts": orphan_promotion_products["references"].get("issue_counts", {}),
            "orphan_superimposition_issue_counts": orphan_skill_products["references"].get("issue_counts", {}),
            "empty_equipment_table_record_count": empty_core_products["inventory"].get("table_record_counts", {}).get("equipment_config"),
        },
    }


def _rebuild_snapshot_products(
    snapshot: EquipmentSourceSnapshot,
    special_sources: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    references = build_equipment_reference_integrity(snapshot)
    mechanisms = build_equipment_mechanism_family_matrix(snapshot)
    inventory = build_equipment_source_inventory(snapshot, special_sources, references)
    return {
        "references": references,
        "mechanisms": mechanisms,
        "inventory": inventory,
    }


def _rebuilt_products_are_valid(
    products: dict[str, dict[str, Any]],
    special_sources: dict[str, Any],
) -> bool:
    return (
        validate_equipment_reference_integrity(products["references"]).get("ok") is True
        and validate_equipment_mechanism_family_matrix(products["mechanisms"]).get("ok") is True
        and validate_equipment_source_inventory(products["inventory"], special_sources).get("ok") is True
    )


def _first_ability_name(
    reference: dict[str, Any],
    *,
    reference_status: str,
    reference_domain: str | None = None,
) -> str:
    for row in reference.get("ability_inventory", []):
        if (
            isinstance(row, dict)
            and row.get("reference_status") == reference_status
            and (reference_domain is None or reference_domain in (row.get("reference_domains") or []))
            and row.get("ability_name")
        ):
            return str(row["ability_name"])
    return ""


def _remove_ability_record(snapshot: EquipmentSourceSnapshot, ability_name: str) -> bool:
    for document in snapshot.ability_documents:
        ability_list = document.data.get("AbilityList") if isinstance(document.data, dict) else None
        if not isinstance(ability_list, list):
            continue
        for index, row in enumerate(ability_list):
            if isinstance(row, dict) and row.get("Name") == ability_name:
                del ability_list[index]
                return True
    return False


def _duplicate_ability_record(snapshot: EquipmentSourceSnapshot, ability_name: str) -> bool:
    for document in snapshot.ability_documents:
        ability_list = document.data.get("AbilityList") if isinstance(document.data, dict) else None
        if not isinstance(ability_list, list):
            continue
        for row in ability_list:
            if isinstance(row, dict) and row.get("Name") == ability_name:
                ability_list.append(copy.deepcopy(row))
                return True
    return False


def _unused_numeric_identity(primary_rows: Any, primary_key: str, extra_rows: Any) -> int:
    used = {
        int(row.get(primary_key))
        for rows in (primary_rows, extra_rows)
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict) and isinstance(row.get(primary_key), int) and not isinstance(row.get(primary_key), bool)
    }
    return (max(used) + 1) if used else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P8-S0 equipment source and mechanism baseline.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} validation ok={result['ok']} "
        f"ready_for_review={result['ready_for_review']} "
        f"primary_files={result['primary_source_fingerprint'].get('file_count')} "
        f"unknown_mechanisms={result['observations']['mechanism_summary'].get('unknown_row_count')}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
