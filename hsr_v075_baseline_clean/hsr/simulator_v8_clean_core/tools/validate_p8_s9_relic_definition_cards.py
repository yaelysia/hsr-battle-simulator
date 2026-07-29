from __future__ import annotations

import argparse
import json
import resource
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from .. import BASELINE_VERSION
from ..equipment.models import (
    EquipmentDefinitionKey,
    LightConeAbilitySourceIR,
    RelicAbilitySourceIR,
    RelicDomainDefinitionIR,
    RelicSetThresholdIR,
    RelicSlotDefinitionIR,
    make_equipment_source,
)
from ..immutable_json import thaw_json
from ..rules.ir import CanonicalIR
from ..rules.rulebook import RuleBook
from ..tbgd.equipment_discovery import PRIMARY_ABILITY_ROOT, PRIMARY_TABLE_ROLES
from ..tbgd.lowering import _equipment_catalog_fingerprint_metadata
from ..tbgd.relic_cards import (
    RELIC_TABLE_ROLES,
    RelicCanonicalCatalog,
    RelicCatalogBuildResult,
    RelicCatalogSourceBundle,
    build_relic_catalog_from_documents,
    load_relic_catalog_sources,
    require_complete_relic_catalog,
)
from .io import write_json


VALIDATION_VERSION = "p8_s9_relic_definition_cards"
SUMMARY_SCHEMA_VERSION = "p8_s9_relic_definition_cards_summary_v1"
RELIC_CATALOG_BINDINGS = (
    ("relic_domain_definitions", "domain_definitions", "domain", "relic_domain_definition"),
    ("relic_slot_definitions", "slot_definitions", "slot", "relic_slot_definition"),
    ("relic_main_affix_group_definitions", "main_affix_group_definitions", "main_group", "relic_main_affix_group_definition"),
    ("relic_main_affix_definitions", "main_affix_definitions", "main_affix", "relic_main_affix_definition"),
    ("relic_sub_affix_group_definitions", "sub_affix_group_definitions", "sub_group", "relic_sub_affix_group_definition"),
    ("relic_sub_affix_definitions", "sub_affix_definitions", "sub_affix", "relic_sub_affix_definition"),
    ("relic_template_definitions", "template_definitions", "template", "relic_template_definition"),
    ("relic_set_definitions", "set_definitions", "set", "relic_set_definition"),
    ("relic_set_thresholds", "set_thresholds", "threshold", "relic_set_threshold"),
)


def run_validation(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    sources = load_relic_catalog_sources(tbgd_root)
    result = _build(sources)
    catalog = require_complete_relic_catalog(result)
    ir = _canonical_ir(catalog, result)
    rules = RuleBook(ir)

    source_evidence = _source_evidence(result, sources)
    definition_matrices = _definition_matrices(result, catalog, ir)
    negative_matrix = _negative_matrix(sources, result, catalog)
    query_codec_matrix = _query_codec_matrix(ir, rules, catalog, result)
    checks = _checks(
        result,
        catalog,
        source_evidence,
        definition_matrices,
        negative_matrix,
        query_codec_matrix,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_files = {
        "p8_s9_source_inventory.json": source_evidence,
        "p8_s9_definition_matrices.json": definition_matrices,
        "p8_s9_negative_matrix.json": negative_matrix,
        "p8_s9_query_codec_matrix.json": query_codec_matrix,
    }
    for filename, payload in evidence_files.items():
        write_json(output_dir / filename, payload)
    output_sizes = {
        name: (output_dir / name).stat().st_size for name in evidence_files
    }
    elapsed = time.perf_counter() - started
    summary_path = output_dir / "validation_summary_p8_s9_relic_definition_cards.json"
    summary: dict[str, Any] = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": checks["ok"],
        "ready_for_review": checks["ok"],
        "checks": checks,
        "catalog_summary": result.to_summary_json(),
        "matrix_summary": definition_matrices["summary"],
        "negative_summary": negative_matrix["summary"],
        "query_codec_summary": query_codec_matrix["summary"],
        "resource_budget": {
            "source_snapshot_load_count": 1,
            "relic_catalog_build_count": 1,
            "rulebook_build_count": 1,
            "semantic_table_parse_count": result.semantic_table_parse_count,
            "ability_file_parse_count": result.ability_file_parse_count,
            "ability_index_build_count": result.ability_index_build_count,
            "case_build_count": negative_matrix["summary"]["case_build_count"],
            "fail_closed_build_count": negative_matrix["summary"]["fail_closed_build_count"],
            "metamorphic_build_count": negative_matrix["summary"]["metamorphic_build_count"],
            "wall_seconds": round(elapsed, 6),
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "full_canonical_ir_written": False,
            "full_rulebook_written": False,
            "ability_payload_written": False,
            "runtime_executed": False,
            "output_file_sizes": output_sizes,
            "output_total_bytes_without_summary": sum(output_sizes.values()),
        },
        "artifacts": sorted([*evidence_files, summary_path.name]),
    }
    write_json(summary_path, summary)
    return summary


def _build(
    sources: RelicCatalogSourceBundle,
    *,
    tables: dict[str, object] | None = None,
    ability_documents: tuple[tuple[str, object], ...] | None = None,
    fingerprint: dict[str, Any] | None = None,
    source_row_indexes: dict[str, tuple[int, ...]] | None = None,
    source_kind: str = "tbgd",
) -> RelicCatalogBuildResult:
    values = _tables(sources) if tables is None else tables
    return build_relic_catalog_from_documents(
        relic_rows=values["relic_config"],
        base_type_rows=values["relic_base_type"],
        main_affix_rows=values["relic_main_affix_config"],
        sub_affix_rows=values["relic_sub_affix_config"],
        set_rows=values["relic_set_config"],
        set_skill_rows=values["relic_set_skill_config"],
        ability_documents=(
            sources.ability_documents
            if ability_documents is None
            else ability_documents
        ),
        ability_source_index=sources.ability_source_index,
        source_content_fingerprint=cast(
            Any,
            sources.source_content_fingerprint
            if fingerprint is None
            else fingerprint,
        ),
        expected_source_content_fingerprint=sources.source_content_fingerprint,
        source_inventory=sources.source_inventory,
        source_kind=cast(Any, source_kind),
        prerequisite_issues=sources.prerequisite_issues,
        source_integrity_ok=sources.source_integrity_ok,
        source_row_indexes=source_row_indexes,
        semantic_table_parse_count=len(RELIC_TABLE_ROLES),
        ability_file_parse_count=len(sources.ability_documents),
    )


def _tables(sources: RelicCatalogSourceBundle) -> dict[str, object]:
    return {
        "relic_config": sources.relic_rows,
        "relic_base_type": sources.base_type_rows,
        "relic_main_affix_config": sources.main_affix_rows,
        "relic_sub_affix_config": sources.sub_affix_rows,
        "relic_set_config": sources.set_rows,
        "relic_set_skill_config": sources.set_skill_rows,
    }


def _canonical_ir(
    catalog: RelicCanonicalCatalog,
    result: RelicCatalogBuildResult,
) -> CanonicalIR:
    metadata = {
        "relic_source_content_fingerprint": thaw_json(result.source_content_fingerprint),
        "relic_catalog_definition_fingerprint": thaw_json(result.catalog_definition_fingerprint),
    }
    return CanonicalIR(
        version=BASELINE_VERSION,
        metadata=metadata,
        **cast(Any, _relic_ir_fields(catalog)),
    )


def _relic_ir_fields(
    catalog: RelicCanonicalCatalog,
) -> dict[str, object]:
    return {
        ir_field: getattr(catalog, catalog_field)
        for ir_field, catalog_field, _, _ in RELIC_CATALOG_BINDINGS
    }


def _source_evidence(
    result: RelicCatalogBuildResult,
    sources: RelicCatalogSourceBundle,
) -> dict[str, Any]:
    fingerprint = dict(result.to_summary_json()["source_content_fingerprint"])
    expected_table_paths = {
        PRIMARY_TABLE_ROLES[role] for role in RELIC_TABLE_ROLES
    }
    paths = set(cast(list[str], fingerprint["paths"]))
    ability_paths = sorted(
        item.relative_path
        for item in result.source_inventory
        if item.source_role == "equipment_ability_file"
    )
    return {
        "schema_version": "p8_s9_source_inventory_v1",
        "source_content_fingerprint": fingerprint,
        "inventory": [item.to_json() for item in result.source_inventory],
        "checks": {
            "six_relic_tables_fingerprinted": expected_table_paths.issubset(paths),
            "all_loaded_ability_paths_fingerprinted": bool(ability_paths)
            and set(ability_paths).issubset(paths)
            and all(path.startswith(f"{PRIMARY_ABILITY_ROOT}/") for path in ability_paths),
            "source_inventory_matches_fingerprint": paths
            == {item.relative_path for item in result.source_inventory}
            and sum(item.byte_count for item in result.source_inventory)
            == fingerprint["byte_count"],
            "numeric_values_never_pass_through_float":
                result.numeric_values_never_pass_through_float,
            "production_validation_artifact_read_count_zero":
                result.production_validation_artifact_read_count == 0,
            "ability_identity_index_built_once":
                result.ability_index_build_count == 1
                and not sources.ability_source_index.issues,
        },
        "summary": {
            "source_file_count": len(paths),
            "relic_table_count": len(expected_table_paths),
            "ability_file_count": len(ability_paths),
            "ability_identity_count": len(sources.ability_source_index.entries),
            "source_byte_count": fingerprint["byte_count"],
        },
    }


def _contains_json_key(value: object, keys: set[str]) -> bool:
    if isinstance(value, dict):
        return bool(keys.intersection(value)) or any(
            _contains_json_key(item, keys)
            for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_json_key(item, keys) for item in value)
    return False


def _definition_matrices(
    result: RelicCatalogBuildResult,
    catalog: RelicCanonicalCatalog,
    ir: CanonicalIR,
) -> dict[str, Any]:
    slots = [
        {
            "slot": item.raw_slot_type,
            "domain": item.domain_key.definition_identity,
            "allowed_main_property_count": len(item.allowed_main_property_types),
            "coverage_status": item.coverage_status,
        }
        for item in catalog.slot_definitions
    ]
    domains = [
        {
            "domain": item.domain,
            "slots": [key.definition_identity for key in item.slot_keys],
            "set_count": len(item.set_keys),
            "coverage_status": item.coverage_status,
        }
        for item in catalog.domain_definitions
    ]
    templates = [
        {
            "template_id": item.raw_relic_id,
            "set_id": item.set_key.definition_identity,
            "slot": item.slot_key.definition_identity,
            "domain": item.domain_key.definition_identity,
            "main_group": item.main_affix_group_key.definition_identity,
            "sub_group": item.sub_affix_group_key.definition_identity,
            "mode": item.mode,
            "publication_status": item.publication_status,
            "coverage_status": item.coverage_status,
        }
        for item in catalog.template_definitions
    ]
    groups = {
        "main": [
            {
                "group_id": item.raw_group_id,
                "affix_count": len(item.affix_keys),
                "property_types": list(item.property_types),
            }
            for item in catalog.main_affix_group_definitions
        ],
        "sub": [
            {
                "group_id": item.raw_group_id,
                "affix_count": len(item.affix_keys),
                "property_types": list(item.property_types),
            }
            for item in catalog.sub_affix_group_definitions
        ],
    }
    sets = [
        {
            "set_id": item.raw_set_id,
            "domain": item.domain_key.definition_identity,
            "slots": [key.definition_identity for key in item.slot_keys],
            "template_count": len(item.template_keys),
            "thresholds": [key.definition_identity for key in item.threshold_keys],
            "publication_status": item.publication_status,
            "coverage_status": item.coverage_status,
        }
        for item in catalog.set_definitions
    ]
    thresholds = [
        {
            "threshold_id": item.definition_key.definition_identity,
            "set_id": item.set_key.definition_identity,
            "require_count": item.require_count,
            "static_property_count": len(item.static_properties),
            "parameter_count": len(item.parameters),
            "ability_name": item.ability_source.ability_name
            if item.ability_source is not None else "",
            "ability_source_path": item.ability_source.source.source_path
            if item.ability_source is not None else "",
            "coverage_status": item.coverage_status,
        }
        for item in catalog.set_thresholds
    ]
    mode_counts = Counter(item.mode for item in catalog.template_definitions)
    publication_counts = Counter(
        item.publication_status for item in catalog.template_definitions)
    definitions = catalog.definitions()
    reference_issues = catalog.reference_issues()
    definition_payload = [definition.to_json() for definition in definitions]
    source_kind_counts = Counter(
        (
            definition.definition_key.definition_kind,
            definition.source.evidence.get("source_kind"),
        )
        for definition in definitions
    )
    source_kind_totals = Counter(
        definition.source.evidence.get("source_kind")
        for definition in definitions
    )
    ability_source_issue_count = sum(
        "ability" in issue.issue_code
        and any(
            marker in issue.issue_code
            for marker in ("missing", "ambiguous", "not_unique")
        )
        for issue in result.issues
    )
    return {
        "schema_version": "p8_s9_definition_matrices_v1",
        "slot_matrix": slots,
        "slot_filter_matrix": [
            {
                "filter_identity": item.filter_identity,
                "property_count": len(item.allowed_property_types),
                "classified_as_slot": False,
            }
            for item in result.slot_filters
        ],
        "domain_matrix": domains,
        "template_closure_matrix": templates,
        "affix_group_matrix": groups,
        "set_matrix": sets,
        "threshold_matrix": thresholds,
        "mode_matrix": dict(sorted(mode_counts.items())),
        "publication_matrix": dict(sorted(publication_counts.items())),
        "reference_matrix": {
            "template_reference_count": sum(
                len(
                    (
                        item.slot_key,
                        item.domain_key,
                        item.set_key,
                        item.main_affix_group_key,
                        item.sub_affix_group_key,
                    )
                )
                for item in catalog.template_definitions
            ),
            "template_missing_reference_count": sum(
                issue.definition_key.definition_kind == "relic_template"
                and issue.issue_code.endswith("_missing")
                for issue in reference_issues
            ),
            "template_reference_issue_count": sum(
                issue.definition_key.definition_kind == "relic_template"
                for issue in reference_issues
            ),
            "set_threshold_reference_count": sum(
                len(item.threshold_keys) for item in catalog.set_definitions),
            "set_threshold_missing_reference_count": sum(
                issue.issue_code
                in {
                    "relic_set_threshold_reference_missing",
                    "relic_threshold_set_reference_missing",
                }
                for issue in reference_issues
            ),
            "ability_source_reference_count": sum(
                item.ability_source is not None
                for item in catalog.set_thresholds),
            "ability_source_missing_or_ambiguous_count":
                ability_source_issue_count,
            "reference_issue_count": len(reference_issues),
            "issues": [issue.to_json() for issue in reference_issues],
        },
        "source_provenance_matrix": {
            "kind_counts": {
                f"{definition_kind}:{source_kind}": count
                for (definition_kind, source_kind), count
                in sorted(source_kind_counts.items())
            },
            "derived_definition_count": source_kind_totals["derived"],
            "raw_definition_count": source_kind_totals["tbgd"],
            "validation_fixture_definition_count": source_kind_totals[
                "validation_fixture"
            ],
        },
        "boundary_probe": {
            "equipment_graph_reference_created": bool(
                ir.equipment_mechanism_refs
            )
            or _contains_json_key(
                definition_payload,
                {"graph_ref", "graph_ref_id"},
            ),
            "relic_mechanism_reference_created": _contains_json_key(
                definition_payload,
                {"mechanism_ref", "mechanism_ref_id", "mechanism_ref_ids"},
            ),
            "runtime_mutation_created": _contains_json_key(
                definition_payload,
                {"mutation", "mutations", "state_before", "state_after"},
            ),
            "relic_instance_created": _contains_json_key(
                definition_payload,
                {"relic_instance", "relic_instance_id"},
            ),
        },
        "summary": {
            "mode_counts": dict(sorted(mode_counts.items())),
            "publication_counts": dict(sorted(publication_counts.items())),
            "slot_count": len(slots),
            "filter_row_count": len(result.slot_filters),
            "domain_count": len(domains),
            "template_count": len(templates),
            "set_count": len(sets),
            "threshold_count": len(thresholds),
            "static_threshold_count": sum(
                row["static_property_count"] > 0 for row in thresholds),
            "dynamic_threshold_count": sum(
                bool(row["ability_name"]) for row in thresholds),
            "static_and_dynamic_threshold_count": sum(
                row["static_property_count"] > 0 and bool(row["ability_name"])
                for row in thresholds),
        },
    }


def _negative_matrix(
    sources: RelicCatalogSourceBundle,
    positive: RelicCatalogBuildResult,
    catalog: RelicCanonicalCatalog,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []

    def add(
        row_id: str,
        result: RelicCatalogBuildResult,
        expected: str = "",
        *,
        passed: bool | None = None,
    ) -> None:
        codes = sorted({item.issue_code for item in result.issues})
        if passed is None:
            passed = (
                not result.catalog_complete
                and result.canonical_catalog is None
                and expected in codes
            )
        rows.append(
            {
                "row_id": row_id,
                "catalog_complete": result.catalog_complete,
                "canonical_catalog_exposed": result.canonical_catalog is not None,
                "issue_codes": codes,
                "expected_issue": expected,
                "passed": passed,
            }
        )

    def fixture(
        tables: dict[str, list[dict[str, Any]]],
    ) -> RelicCatalogBuildResult:
        return _build(
            sources,
            tables=cast(Any, tables),
            source_kind="validation_fixture",
        )

    def mutated_fixture(
        role: str,
        updates: dict[str, Any],
    ) -> RelicCatalogBuildResult:
        tables = _table_lists(sources)
        tables[role][0] = {**tables[role][0], **updates}
        return fixture(tables)

    duplicate = _table_lists(sources)
    duplicate["relic_config"].append(dict(duplicate["relic_config"][0]))
    add(
        "duplicate_template_identity",
        fixture(duplicate),
        "relic_template_duplicate_identity",
    )
    add(
        "missing_main_group_reference",
        mutated_fixture("relic_config", {"MainAffixGroup": 999999991}),
        "relic_template_main_group_missing",
    )

    unknown_slot = _table_lists(sources)
    unknown_slot["relic_config"][0] = {
        **unknown_slot["relic_config"][0],
        "Type": "FUTURE_SLOT_WITHOUT_DOMAIN",
    }
    unknown_slot_result = fixture(unknown_slot)
    unknown_template_id = str(unknown_slot["relic_config"][0]["ID"])
    add(
        "unknown_slot_has_no_invented_domain",
        unknown_slot_result,
        "relic_template_slot_reference_missing",
        passed=(
            not unknown_slot_result.catalog_complete
            and unknown_slot_result.canonical_catalog is None
            and all(
                item.definition_key.definition_identity != unknown_template_id
                for item in unknown_slot_result.diagnostic_catalog.template_definitions
            )
        ),
    )

    add(
        "unknown_mode",
        mutated_fixture("relic_config", {"Mode": "FUTURE_MODE"}),
        "relic_template_mode_unknown",
    )
    add(
        "invalid_template_payload",
        mutated_fixture("relic_config", {"Rarity": None}),
        "relic_template_rarity_invalid",
    )
    add(
        "invalid_threshold_identity",
        mutated_fixture("relic_set_skill_config", {"RequireNum": 0}),
        "relic_threshold_identity_invalid",
    )

    cross_domain = _table_lists(sources)
    outer_set = next(
        row["SetID"]
        for row in cross_domain["relic_set_config"]
        if row.get("IsPlanarSuit") is not True
    )
    planar_index = next(
        index
        for index, row in enumerate(cross_domain["relic_config"])
        if row.get("Type") in {
            slot.raw_slot_type
            for slot in catalog.slot_definitions
            if slot.domain_key.definition_identity == "planar"
        }
    )
    cross_domain["relic_config"][planar_index] = {
        **cross_domain["relic_config"][planar_index],
        "SetID": outer_set,
    }
    cross_result = fixture(cross_domain)
    cross_codes = {item.issue_code for item in cross_result.issues}
    add(
        "cross_domain_membership",
        cross_result,
        "cross_domain_membership",
        passed=not cross_result.catalog_complete
        and cross_result.canonical_catalog is None
        and bool({
            "relic_slot_cross_domain_membership",
            "relic_set_cross_domain_membership",
        }.intersection(cross_codes)),
    )

    fake_ability = _table_lists(sources)
    ability_row_index = next(
        index
        for index, row in enumerate(fake_ability["relic_set_skill_config"])
        if isinstance(row.get("AbilityName"), str) and row["AbilityName"]
    )
    fake_ability["relic_set_skill_config"][ability_row_index] = {
        **fake_ability["relic_set_skill_config"][ability_row_index],
        "AbilityName": "__p8_s9_missing_ability__",
    }
    add(
        "missing_fake_ability",
        fixture(fake_ability),
        "relic_threshold_ability_source_not_unique",
    )

    stale = dict(sources.source_content_fingerprint)
    stale["sha256"] = "0" * 64
    add("stale_source_fingerprint", _build(
        sources, fingerprint=stale,
        source_kind="validation_fixture"),
        "relic_source_fingerprint_stale_or_incomplete")

    duplicate_threshold = _table_lists(sources)
    duplicate_threshold["relic_set_skill_config"].append(
        dict(duplicate_threshold["relic_set_skill_config"][0]))
    add(
        "duplicate_set_threshold",
        fixture(duplicate_threshold),
        "relic_set_threshold_duplicate_identity",
    )

    reversed_tables = {
        role: list(reversed(rows))
        for role, rows in _table_lists(sources).items()
    }
    source_indexes = {
        role: tuple(reversed(range(len(rows))))
        for role, rows in _table_lists(sources).items()
    }
    reordered = _build(
        sources,
        tables=cast(Any, reversed_tables),
        ability_documents=tuple(reversed(sources.ability_documents)),
        source_row_indexes=source_indexes,
    )
    add(
        "input_order_invariance",
        reordered,
        passed=reordered.catalog_complete
        and reordered.diagnostic_catalog.to_json()
        == positive.diagnostic_catalog.to_json()
        and reordered.catalog_definition_fingerprint
        == positive.catalog_definition_fingerprint,
    )

    renumbered = _renumber_sets(sources)
    renumbered_result = fixture(renumbered)
    add(
        "set_id_renumber_does_not_change_domain_partition",
        renumbered_result,
        passed=renumbered_result.catalog_complete
        and _domain_slots(renumbered_result.diagnostic_catalog)
        == _domain_slots(positive.diagnostic_catalog),
    )
    return {
        "schema_version": "p8_s9_negative_matrix_v1",
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "passed_count": sum(row["passed"] for row in rows),
            "case_build_count": len(rows),
            "fail_closed_build_count": sum(
                bool(row["expected_issue"]) for row in rows
            ),
            "metamorphic_build_count": sum(
                not row["expected_issue"] for row in rows
            ),
            "all_passed": all(row["passed"] for row in rows),
        },
    }


def _query_codec_matrix(
    ir: CanonicalIR,
    rules: RuleBook,
    catalog: RelicCanonicalCatalog,
    result: RelicCatalogBuildResult,
) -> dict[str, Any]:
    query_specs = {
        label: (
            getattr(rules, query_name),
            getattr(catalog, catalog_field)[0],
        )
        for _, catalog_field, label, query_name in RELIC_CATALOG_BINDINGS
    }
    samples = {
        name: query(definition.definition_key.definition_identity)
        for name, (query, definition) in query_specs.items()
    }

    def rules_with(**overrides: object) -> RuleBook:
        fields = _relic_ir_fields(catalog)
        fields.update(overrides)
        return RuleBook(
            CanonicalIR(version=BASELINE_VERSION, **cast(Any, fields))
        )

    def with_derived_source(value: object, *path: str) -> dict[str, Any]:
        payload = cast(dict[str, Any], thaw_json(value))
        node = payload
        for field in path:
            node = cast(dict[str, Any], node[field])
        source = cast(dict[str, Any], node["source"])
        cast(dict[str, Any], source["evidence"])["source_kind"] = "derived"
        return payload

    def blocked(value: Any, reason: str) -> bool:
        return value.resolution_status == "blocked" and value.blocked_reason == reason

    def all_source_kind(values: object, source_kind: str) -> bool:
        return all(
            item.source.evidence.get("source_kind") == source_kind
            for item in cast(Any, values)
        )

    duplicate_template = catalog.template_definitions[0]
    duplicate_resolution = rules_with(
        relic_template_definitions=(duplicate_template, duplicate_template)
    ).relic_template_definition(
        duplicate_template.definition_key.definition_identity
    )
    domain = catalog.domain_definitions[0]
    fixture_fingerprint = cast(
        dict[str, Any],
        thaw_json(domain.source.evidence.get("source_fingerprint")),
    )
    same_identity_slot = RelicSlotDefinitionIR(
        definition_key=EquipmentDefinitionKey(
            "relic_slot",
            domain.definition_key.definition_identity,
        ),
        raw_slot_type=domain.definition_key.definition_identity,
        domain_key=domain.definition_key,
        allowed_main_property_types=("FixtureProperty",),
        source=make_equipment_source(
            source_path="fixture/relic/RelicBaseType.json",
            raw_type="RelicBaseType",
            raw_id=domain.definition_key.definition_identity,
            json_path="$[0]",
            source_fingerprint=fixture_fingerprint,
            source_kind="validation_fixture",
        ),
        coverage_status="lowered",
        blocked_reason="",
    )
    expanded_domain = replace(
        domain,
        slot_keys=tuple(sorted(
            (*domain.slot_keys, same_identity_slot.definition_key),
            key=lambda key: key.stable_id,
        )),
    )
    namespace_rules = rules_with(
        relic_domain_definitions=tuple(
            expanded_domain if item.definition_key == domain.definition_key else item
            for item in catalog.domain_definitions
        ),
        relic_slot_definitions=tuple(sorted(
            (*catalog.slot_definitions, same_identity_slot),
            key=lambda item: item.definition_key.stable_id,
        )),
    )
    domain_resolution = namespace_rules.relic_domain_definition(
        domain.definition_key.definition_identity
    )
    slot_resolution = namespace_rules.relic_slot_definition(
        domain.definition_key.definition_identity
    )
    wrong_kind = namespace_rules.relic_main_affix_definition(
        domain.definition_key.definition_identity
    )
    forged_tbgd_record_rejected = _raises(lambda: RelicSlotDefinitionIR(
        definition_key=same_identity_slot.definition_key,
        raw_slot_type=same_identity_slot.raw_slot_type,
        domain_key=domain.definition_key,
        allowed_main_property_types=("FixtureProperty",),
        source=catalog.slot_definitions[0].source,
        coverage_status="lowered",
        blocked_reason="",
    ))
    forged_aggregate_source_rejected = _raises(
        lambda: replace(domain, source=catalog.slot_definitions[0].source)
    )
    ability_threshold = next(
        item for item in catalog.set_thresholds if item.ability_source is not None
    )
    real_ability_source = cast(RelicAbilitySourceIR, ability_threshold.ability_source)
    real_source = real_ability_source.source
    derived_ability_source = make_equipment_source(
        source_path=real_source.source_path,
        raw_type=real_source.raw_type,
        raw_id=real_source.raw_id,
        json_path=cast(str, real_source.evidence.get("json_path")),
        source_fingerprint=cast(
            dict[str, Any],
            thaw_json(real_source.evidence.get("source_fingerprint")),
        ),
        source_kind="derived",
    )

    def rejects_derived_ability(model: Any) -> bool:
        return _raises(lambda: model(
            ability_name=real_ability_source.ability_name,
            record_index=real_ability_source.record_index,
            source=derived_ability_source,
        ))

    derived_relic_ability_constructor_rejected = rejects_derived_ability(
        RelicAbilitySourceIR
    )
    derived_light_cone_ability_constructor_rejected = rejects_derived_ability(
        LightConeAbilitySourceIR
    )
    derived_relic_ability_json_rejected = _raises(
        lambda: RelicAbilitySourceIR.from_json(
            with_derived_source(real_ability_source.to_json())
        )
    )
    derived_relic_threshold_json_rejected = _raises(
        lambda: RelicSetThresholdIR.from_json(
            with_derived_source(ability_threshold.to_json(), "ability_source")
        )
    )
    missing_set_key = EquipmentDefinitionKey(
        "relic_set", "__p8_s9_missing_set__"
    )
    broken_template = replace(
        catalog.template_definitions[0], set_key=missing_set_key
    )
    broken_reference_rules = rules_with(
        relic_template_definitions=(
            broken_template,
            *catalog.template_definitions[1:],
        )
    )
    broken_reference_resolution = broken_reference_rules.relic_template_definition(
        broken_template.definition_key.definition_identity
    )
    bidirectional_set = next(
        item for item in catalog.set_definitions if len(item.template_keys) > 1
    )
    removed_template_key = bidirectional_set.template_keys[0]
    broken_set = replace(
        bidirectional_set, template_keys=bidirectional_set.template_keys[1:]
    )
    bidirectional_rules = rules_with(
        relic_set_definitions=tuple(
            broken_set if item.definition_key == bidirectional_set.definition_key else item
            for item in catalog.set_definitions
        )
    )
    bidirectional_set_resolution = bidirectional_rules.relic_set_definition(
        bidirectional_set.definition_key.definition_identity
    )
    bidirectional_template_resolution = (
        bidirectional_rules.relic_template_definition(
            removed_template_key.definition_identity
        )
    )
    round_trip = RelicCanonicalCatalog.from_json(catalog.to_json())
    unknown_field = catalog.domain_definitions[0].to_json()
    unknown_field["unexpected"] = True
    unknown_field_rejected = _raises(
        lambda: RelicDomainDefinitionIR.from_json(unknown_field)
    )
    affix_keys = list(
        catalog.main_affix_group_definitions[0].affix_keys
    )
    detached_group = replace(
        catalog.main_affix_group_definitions[0],
        affix_keys=cast(Any, affix_keys),
    )
    before = detached_group.to_json()
    affix_keys.append(affix_keys[0])
    encoded_ir = ir.to_json()
    metadata_probe = _equipment_catalog_fingerprint_metadata(
        light_cone_source_content_fingerprint={"probe": "light_cone_source"},
        relic_source_content_fingerprint=result.source_content_fingerprint,
        light_cone_catalog_definition_fingerprint={"probe": "light_cone_catalog"},
        relic_catalog_definition_fingerprint=result.catalog_definition_fingerprint,
    )
    expected_metadata_keys = {
        "light_cone_source_content_fingerprint",
        "relic_source_content_fingerprint",
        "light_cone_catalog_definition_fingerprint",
        "relic_catalog_definition_fingerprint",
    }
    aggregate_definitions = (
        *catalog.domain_definitions,
        *catalog.main_affix_group_definitions,
        *catalog.sub_affix_group_definitions,
    )
    raw_definitions = (
        *catalog.slot_definitions,
        *catalog.main_affix_definitions,
        *catalog.sub_affix_definitions,
        *catalog.template_definitions,
        *catalog.set_definitions,
        *catalog.set_thresholds,
    )
    checks = {
        "all_typed_queries_resolved": all(
            item.resolution_status == "resolved" and item.value is not None
            for item in samples.values()
        ),
        "duplicate_query_blocked": blocked(
            duplicate_resolution, "equipment_definition_ambiguous"
        ),
        "same_identity_resolves_per_namespace": domain_resolution.resolution_status
        == "resolved"
        and slot_resolution.resolution_status == "resolved",
        "wrong_kind_query_fails_closed": blocked(
            wrong_kind, "equipment_definition_kind_mismatch"
        ),
        "missing_reference_query_fails_closed": blocked(
            broken_reference_resolution,
            "equipment_definition_reference_closure_invalid",
        ),
        "bidirectional_reference_mismatch_fails_closed":
            blocked(
                bidirectional_set_resolution,
                "equipment_definition_reference_closure_invalid",
            )
            and blocked(
                bidirectional_template_resolution,
                "equipment_definition_reference_closure_invalid",
            ),
        "canonical_round_trip_deterministic": round_trip.to_json()
        == catalog.to_json(),
        "unknown_codec_field_rejected": unknown_field_rejected,
        "external_container_detached": detached_group.to_json() == before,
        "real_tbgd_record_identity_enforced":
            forged_tbgd_record_rejected
            and all_source_kind(
                (*result.slot_filters, *raw_definitions), "tbgd"
            ),
        "real_relic_ability_sources_are_tbgd": all(
            item.ability_source is None
            or item.ability_source.source.evidence.get("source_kind")
            == "tbgd"
            for item in catalog.set_thresholds
        ),
        "derived_relic_ability_constructor_rejected":
            derived_relic_ability_constructor_rejected,
        "derived_relic_ability_json_rejected":
            derived_relic_ability_json_rejected,
        "derived_relic_threshold_json_rejected":
            derived_relic_threshold_json_rejected,
        "light_cone_and_relic_share_strict_ability_source_boundary":
            derived_light_cone_ability_constructor_rejected
            and derived_relic_ability_constructor_rejected,
        "aggregate_provenance_is_derived":
            all_source_kind(aggregate_definitions, "derived")
            and forged_aggregate_source_rejected,
        "positive_reference_closure_has_no_issues": not catalog.reference_issues(),
        "canonical_ir_contains_all_relic_catalogs": all(
            encoded_ir.get(field)
            for field, _, _, _ in RELIC_CATALOG_BINDINGS
        ),
        "canonical_ir_relic_fingerprints_preserved":
            ir.metadata.get("relic_source_content_fingerprint")
            == result.source_content_fingerprint
            and ir.metadata.get("relic_catalog_definition_fingerprint")
            == result.catalog_definition_fingerprint,
        "equipment_fingerprint_metadata_split_atomically":
            set(metadata_probe) == expected_metadata_keys
            and metadata_probe["relic_source_content_fingerprint"]
            == thaw_json(result.source_content_fingerprint)
            and metadata_probe["relic_catalog_definition_fingerprint"]
            == thaw_json(result.catalog_definition_fingerprint)
            and "equipment_source_content_fingerprint"
            not in metadata_probe
            and "equipment_source_content_fingerprint"
            not in ir.metadata,
        "no_relic_mechanism_or_graph_refs": not ir.equipment_mechanism_refs
        and all(
            "mechanism_ref" not in json.dumps(item.to_json())
            and "graph_ref" not in json.dumps(item.to_json())
            for item in catalog.set_thresholds
        ),
    }
    return {
        "schema_version": "p8_s9_query_codec_matrix_v1",
        "checks": checks,
        "query_samples": {
            name: {
                "resolution_status": item.resolution_status,
                "requested_key": item.requested_key.to_json(),
                "blocked_reason": item.blocked_reason,
            }
            for name, item in samples.items()
        },
        "negative_samples": {
            "duplicate": duplicate_resolution.to_json(),
            "wrong_kind": wrong_kind.to_json(),
            "missing_reference": broken_reference_resolution.to_json(),
            "bidirectional_set": bidirectional_set_resolution.to_json(),
            "bidirectional_template": bidirectional_template_resolution.to_json(),
            "forged_tbgd_record_rejected": forged_tbgd_record_rejected,
            "forged_aggregate_source_rejected": forged_aggregate_source_rejected,
            "forged_derived_ability_source_accepted":
                not derived_relic_ability_constructor_rejected,
            "forged_derived_ability_json_accepted":
                not derived_relic_ability_json_rejected,
            "forged_derived_threshold_json_accepted":
                not derived_relic_threshold_json_rejected,
            "forged_derived_light_cone_ability_source_accepted":
                not derived_light_cone_ability_constructor_rejected,
        },
        "summary": {
            "query_count": len(samples),
            "resolved_query_count": sum(
                item.resolution_status == "resolved"
                for item in samples.values()
            ),
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "all_passed": all(checks.values()),
        },
    }


def _checks(
    result: RelicCatalogBuildResult,
    catalog: RelicCanonicalCatalog,
    source: dict[str, Any],
    matrices: dict[str, Any],
    negatives: dict[str, Any],
    query_codec: dict[str, Any],
) -> dict[str, bool]:
    summary = matrices["summary"]
    threshold_rows = matrices["threshold_matrix"]
    reference = matrices["reference_matrix"]
    negative_passed = {
        row["row_id"]: row["passed"] for row in negatives["rows"]
    }
    checks = {
        "current_relic_sources_fingerprinted": all(source["checks"].values()),
        "published_relic_templates_all_lowered":
            result.published_template_lowered_count
            == result.published_template_source_count,
        "published_relic_template_blocked_count":
            result.published_template_blocked_count == 0,
        "real_slot_count_derived_from_source": summary["slot_count"] == 6,
        "filter_row_is_not_slot": summary["filter_row_count"] >= 1
        and all(
            not row["classified_as_slot"]
            for row in matrices["slot_filter_matrix"]
        ),
        "template_references_unique":
            reference["template_missing_reference_count"] == 0
            and reference["reference_issue_count"] == 0,
        "set_domain_derived_from_membership": summary["domain_count"] == 2
        and all(row["slots"] for row in matrices["domain_matrix"]),
        "set_domain_does_not_use_numeric_id_range":
            negative_passed["set_id_renumber_does_not_change_domain_partition"],
        "set_thresholds_data_driven": bool(threshold_rows)
        and len(threshold_rows)
        == sum(len(row["thresholds"]) for row in matrices["set_matrix"])
        and all(row["require_count"] > 0 for row in threshold_rows),
        "static_and_dynamic_threshold_payloads_both_preserved":
            summary["static_and_dynamic_threshold_count"] > 0,
        "basic_custom_unknown_modes_classified":
            set(matrices["mode_matrix"]) == {"BASIC", "CUSTOM"},
        "unknown_mode_fails_closed": negative_passed["unknown_mode"],
        "ability_source_unique":
            reference["ability_source_missing_or_ambiguous_count"] == 0,
        "equipment_graph_reference_created":
            matrices["boundary_probe"]["equipment_graph_reference_created"],
        "canonical_round_trip_deterministic":
            query_codec["checks"]["canonical_round_trip_deterministic"],
        "rulebook_queries_fail_closed": query_codec["summary"]["all_passed"],
        "numeric_values_never_pass_through_float":
            result.numeric_values_never_pass_through_float,
        "catalog_complete": result.catalog_complete
        and len(catalog.template_definitions)
        == result.published_template_source_count,
        "negative_matrix_all_passed": negatives["summary"]["all_passed"],
    }
    checks["ok"] = all(
        not value if key == "equipment_graph_reference_created" else value
        for key, value in checks.items()
    )
    return checks


def _table_lists(
    sources: RelicCatalogSourceBundle,
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for role, value in _tables(sources).items():
        if not isinstance(value, list):
            raise TypeError(f"{role} must be an array")
        result[role] = [
            cast(dict[str, Any], row)
            for row in value
            if isinstance(row, dict)
        ]
    return {role: list(rows) for role, rows in result.items()}


def _renumber_sets(
    sources: RelicCatalogSourceBundle,
) -> dict[str, list[dict[str, Any]]]:
    tables = _table_lists(sources)
    set_ids = sorted(
        int(row["SetID"]) for row in tables["relic_set_config"]
    )
    mapping = {
        set_id: 900000 + index * 17
        for index, set_id in enumerate(reversed(set_ids), start=1)
    }
    for role in (
        "relic_config",
        "relic_set_config",
        "relic_set_skill_config",
    ):
        tables[role] = [
            {
                **row,
                "SetID": mapping[int(row["SetID"])],
            }
            for row in tables[role]
        ]
    return tables


def _domain_slots(
    catalog: RelicCanonicalCatalog,
) -> dict[str, tuple[str, ...]]:
    return {
        item.domain: tuple(
            key.definition_identity for key in item.slot_keys
        )
        for item in catalog.domain_definitions
    }


def _raises(callable_value: Any) -> bool:
    try:
        callable_value()
    except (TypeError, ValueError, KeyError):
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate P8-S9 typed relic definition cards",
    )
    parser.add_argument("--tbgd-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_validation(
        args.tbgd_root.resolve(),
        args.output_dir.resolve(),
    )
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} "
        f"templates={result['matrix_summary']['template_count']} "
        f"sets={result['matrix_summary']['set_count']} "
        f"thresholds={result['matrix_summary']['threshold_count']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
