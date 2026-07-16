from __future__ import annotations

import argparse
import copy
import inspect
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, get_type_hints

from .. import BASELINE_VERSION
from ..equipment.models import EquipmentDefinitionKey, LightConeDefinitionIR
from ..immutable_json import thaw_json
from ..rules.ir import CanonicalIR
from ..rules.rulebook import RuleBook
from ..tbgd.equipment_discovery import build_primary_equipment_source_fingerprint
from ..tbgd.equipment_inventory_contract import (
    fingerprint_contract_matches,
    load_s0_summary_fail_closed,
    validate_s0_summary_payload,
)
from ..tbgd.light_cone_cards import (
    LIGHT_CONE_CATALOG_FINGERPRINT_ALGORITHM,
    LightConeCatalogBuildError,
    LightConeCatalogBuildResult,
    LightConeCatalogSourceBundle,
    build_light_cone_catalog_from_documents,
    load_light_cone_catalog_sources,
    require_complete_light_cone_catalog,
)
from ..tbgd.lowering import LoweringLimits, TBGDLowering
from .io import write_json


VALIDATION_VERSION = "p8_s3_light_cone_data_cards"
SUMMARY_SCHEMA_VERSION = "p8_s3_light_cone_data_cards_summary_v2"


def run_validation(
    tbgd_root: Path,
    s0_summary_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    sources = load_light_cone_catalog_sources(tbgd_root)
    catalog = _build(sources)
    s0_summary = load_s0_summary_fail_closed(s0_summary_path)
    s0_fingerprint = dict(s0_summary["primary_source_fingerprint"])
    live_fingerprint = dict(sources.source_content_fingerprint)

    positive = _positive_checks(catalog, sources, live_fingerprint, s0_fingerprint)
    raw_oracle = _raw_oracle_checks(catalog, sources)
    model_contract = _model_contract_checks(catalog)
    deterministic = _determinism_checks(catalog, sources)
    negative_matrix = _negative_matrix(catalog, sources, s0_summary)
    checks = {
        "positive_catalog": _section_ok(positive),
        "independent_raw_oracle": _section_ok(raw_oracle),
        "model_contract": _section_ok(model_contract),
        "determinism_and_fingerprints": _section_ok(deterministic),
        "raw_snapshot_negatives": _section_ok(negative_matrix),
    }
    ok = all(section["ok"] is True for section in checks.values())

    matrix = {
        "schema_version": "p8_s3_light_cone_data_cards_matrix_v1",
        "positive_catalog": positive,
        "independent_raw_oracle": raw_oracle,
        "model_contract": model_contract,
        "determinism_and_fingerprints": deterministic,
        "raw_snapshot_negatives": negative_matrix,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "p8_s3_light_cone_data_cards_matrix.json", matrix)
    artifact_size = (output_dir / "p8_s3_light_cone_data_cards_matrix.json").stat().st_size
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": ok,
        "ready_for_review": ok,
        "checklist_modified": False,
        "git_commit_created": False,
        "validation_scope": {
            "asserts_current_p8_s4_or_later_state": False,
            "builds_light_cone_instances": False,
            "assembles_character_panels": False,
        },
        "published_cards_all_lowered": positive["published_cards_all_lowered"],
        "published_card_blocked_count": catalog.published_blocked_count,
        "numeric_values_never_pass_through_float": positive[
            "numeric_values_never_pass_through_float"
        ],
        "production_does_not_depend_on_validation_artifact": positive[
            "production_does_not_depend_on_validation_artifact"
        ],
        "ability_source_record_unique": positive["ability_source_record_unique"],
        "equipment_graph_reference_created": False,
        "limited_catalog_cannot_masquerade_as_complete": negative_matrix[
            "limited_catalog_cannot_masquerade_as_complete"
        ],
        "source_content_fingerprint": live_fingerprint,
        "catalog_definition_fingerprint": thaw_json(
            catalog.catalog_definition_fingerprint
        ),
        "checks": checks,
        "resource_budget": {
            "primary_source_scan_count": 1,
            "semantic_table_parse_count": catalog.semantic_table_parse_count,
            "ability_file_parse_count": catalog.ability_file_parse_count,
            "full_tbgd_lowering_build_count": 0,
            "minimal_rulebook_build_count": 2,
            "runtime_transition_count": 0,
            "full_canonical_ir_written": False,
            "full_rulebook_written": False,
            "large_artifacts_written": False,
            "artifact_bytes_before_summary": artifact_size,
            "serial_execution": True,
        },
        "scope": {
            "validated_regression": (
                "full published light-cone definition catalog, exact Decimal-derived growth and rank data, "
                "unique raw ability-record binding, atomic CanonicalIR admission, and typed RuleBook lookup"
            ),
            "not_asserted_by_this_regression": (
                "the current implementation state of P8-S4 and later phases; their own validators "
                "are authoritative for instances, selected-level assembly, activation, scenario, and runtime"
            ),
        },
    }
    write_json(output_dir / "validation_summary_p8_s3_light_cone_data_cards.json", summary)
    return summary


def _build(sources: LightConeCatalogSourceBundle) -> LightConeCatalogBuildResult:
    return build_light_cone_catalog_from_documents(
        equipment_rows=sources.equipment_rows,
        promotion_rows=sources.promotion_rows,
        skill_rows=sources.skill_rows,
        ability_documents=sources.ability_documents,
        source_content_fingerprint=sources.source_content_fingerprint,
        source_kind="tbgd",
        prerequisite_issues=sources.prerequisite_issues,
        source_integrity_ok=sources.source_integrity_ok,
        semantic_table_parse_count=3,
        ability_file_parse_count=len(sources.ability_documents),
    )


def _rebuild(
    sources: LightConeCatalogSourceBundle,
    *,
    equipment_rows: object | None = None,
    promotion_rows: object | None = None,
    skill_rows: object | None = None,
    ability_documents: Sequence[tuple[str, object]] | None = None,
    source_integrity_ok: bool = True,
) -> LightConeCatalogBuildResult:
    return build_light_cone_catalog_from_documents(
        equipment_rows=sources.equipment_rows if equipment_rows is None else equipment_rows,
        promotion_rows=sources.promotion_rows if promotion_rows is None else promotion_rows,
        skill_rows=sources.skill_rows if skill_rows is None else skill_rows,
        ability_documents=sources.ability_documents
        if ability_documents is None
        else ability_documents,
        source_content_fingerprint=sources.source_content_fingerprint,
        source_kind="validation_fixture",
        source_integrity_ok=source_integrity_ok,
    )


def _positive_checks(
    catalog: LightConeCatalogBuildResult,
    sources: LightConeCatalogSourceBundle,
    live_fingerprint: dict[str, Any],
    s0_fingerprint: dict[str, Any],
) -> dict[str, Any]:
    definitions = catalog.canonical_definitions
    minimal_ir = CanonicalIR(
        version=BASELINE_VERSION,
        light_cone_definitions=definitions,
    )
    rulebook = RuleBook(minimal_ir)
    ability_counts = _ability_name_counts(sources.ability_documents)
    fingerprinted_ability_paths = {
        path
        for path in live_fingerprint["paths"]
        if path.startswith("Config/ConfigAbility/Equip/")
        and path.endswith(".json")
        and not path.endswith(".layout.json")
    }
    observed_ability_paths = [path for path, _ in sources.ability_documents]
    resolutions = [
        rulebook.light_cone_definition(definition.raw_equipment_id)
        for definition in definitions
    ]
    source_paths_real = all(
        (sources_path := source.source_path)
        and (sources.source_content_fingerprint is not None)
        and sources_path in live_fingerprint["paths"]
        for definition in definitions
        for source in _definition_sources(definition)
    )
    exact_values = [
        value.exact_value
        for definition in definitions
        for tier in definition.promotion_tiers
        for value in tier.stat_values
    ] + [
        value.exact_value
        for definition in definitions
        for level in definition.superimposition_levels
        for value in (*level.parameters, *level.static_properties)
    ]
    build_signature = inspect.signature(
        __import__(
            "simulator_v8_clean_core.tbgd.light_cone_cards",
            fromlist=["build_light_cone_catalog"],
        ).build_light_cone_catalog
    )
    checks = {
        "catalog_complete": catalog.catalog_complete is True,
        "published_card_set_nonempty": catalog.published_source_count > 0,
        "published_cards_all_lowered": catalog.published_lowered_count
        == catalog.published_source_count,
        "published_card_blocked_count_zero": catalog.published_blocked_count == 0,
        "canonical_directory_is_atomic_and_nonpartial": len(definitions)
        == len(catalog.diagnostic_definitions),
        "all_canonical_cards_lowered": all(
            item.coverage_status == "lowered" and not item.blocked_reason
            for item in definitions
        ),
        "promotion_stage_sets_complete": all(
            tuple(tier.promotion_stage for tier in definition.promotion_tiers)
            == tuple(range(definition.max_promotion + 1))
            for definition in definitions
        ),
        "missing_promotion_field_is_explicit_zero_only": all(
            tier.promotion_field_present or tier.promotion_stage == 0
            for definition in definitions
            for tier in definition.promotion_tiers
        ),
        "superimposition_level_sets_complete": all(
            tuple(level.level for level in definition.superimposition_levels)
            == tuple(range(1, definition.max_superimposition + 1))
            for definition in definitions
        ),
        "parameter_and_property_indices_preserved": all(
            tuple(item.parameter_index for item in level.parameters)
            == tuple(range(len(level.parameters)))
            and tuple(item.property_index for item in level.static_properties)
            == tuple(range(len(level.static_properties)))
            for definition in definitions
            for level in definition.superimposition_levels
        ),
        "skill_text_hashes_preserved": all(
            level.skill_name_hash and level.skill_description_hash
            for definition in definitions
            for level in definition.superimposition_levels
        ),
        "ability_source_record_unique": all(
            definition.ability_source is not None
            and ability_counts[definition.ability_source.ability_name] == 1
            for definition in definitions
        ),
        "ability_document_paths_unique_and_exactly_fingerprinted": len(
            observed_ability_paths
        )
        == len(set(observed_ability_paths))
        and set(observed_ability_paths) == fingerprinted_ability_paths,
        "ability_source_has_file_and_record_path": all(
            definition.ability_source is not None
            and definition.ability_source.source.source_path in live_fingerprint["paths"]
            and str(definition.ability_source.source.evidence.get("json_path", "")).startswith(
                "$.AbilityList["
            )
            for definition in definitions
        ),
        "numeric_values_never_pass_through_float": catalog.numeric_values_never_pass_through_float
        and not _contains_float(sources.equipment_rows)
        and not _contains_float(sources.promotion_rows)
        and not _contains_float(sources.skill_rows)
        and all(isinstance(value, str) for value in exact_values),
        "all_definition_sources_use_live_source_fingerprint": all(
            source.evidence.get("source_fingerprint") == live_fingerprint
            for definition in definitions
            for source in _definition_sources(definition)
        ),
        "all_source_paths_are_primary_real_paths": source_paths_real,
        "source_fingerprint_matches_s0": fingerprint_contract_matches(
            live_fingerprint, s0_fingerprint
        ),
        "production_does_not_depend_on_validation_artifact": tuple(build_signature.parameters)
        == ("tbgd_root",)
        and catalog.production_validation_artifact_read_count == 0,
        "equipment_graph_reference_created_false": all(
            not definition.mechanism_ref_ids for definition in definitions
        )
        and not minimal_ir.equipment_mechanism_refs
        and all("graph_ref_id" not in json.dumps(definition.to_json()) for definition in definitions),
        "rulebook_resolves_every_card_uniquely": all(
            resolution.resolution_status == "resolved"
            and isinstance(resolution.value, LightConeDefinitionIR)
            and len(resolution.candidates) == 1
            for resolution in resolutions
        ),
        "canonical_ir_contains_definitions_only": not minimal_ir.character_data_cards
        and not minimal_ir.character_equipment_eligibilities,
        "production_lowering_uses_atomic_catalog_gate": "require_complete_light_cone_catalog"
        in inspect.getsource(TBGDLowering.build)
        and "light_cone_definitions=tuple(light_cone_definitions)"
        in inspect.getsource(TBGDLowering.build),
        "generic_lowering_limits_have_no_light_cone_limit": "light_cone"
        not in " ".join(LoweringLimits.__dataclass_fields__),
    }
    checks["ok"] = all(value is True for value in checks.values())
    return checks


def _raw_oracle_checks(
    catalog: LightConeCatalogBuildResult,
    sources: LightConeCatalogSourceBundle,
) -> dict[str, Any]:
    equipment_rows = sources.equipment_rows
    promotion_rows = sources.promotion_rows
    skill_rows = sources.skill_rows
    if not all(isinstance(rows, list) for rows in (equipment_rows, promotion_rows, skill_rows)):
        return {"raw_sources_are_arrays": False, "ok": False}

    differences: list[dict[str, Any]] = []
    comparison_count = 0

    def compare(label: str, actual: object, expected: object) -> None:
        nonlocal comparison_count
        comparison_count += 1
        if actual != expected and len(differences) < 12:
            differences.append(
                {"label": label, "actual": actual, "expected": expected}
            )

    equipment_index: dict[str, list[tuple[int, Mapping[str, object]]]] = {}
    for index, row in enumerate(equipment_rows):
        if isinstance(row, Mapping) and _oracle_int(row.get("EquipmentID")) is not None:
            equipment_index.setdefault(str(row["EquipmentID"]), []).append((index, row))
    promotion_index: dict[tuple[str, int], list[tuple[int, Mapping[str, object]]]] = {}
    for index, row in enumerate(promotion_rows):
        if not isinstance(row, Mapping):
            continue
        equipment_id = _oracle_int(row.get("EquipmentID"))
        stage = _oracle_int(row.get("Promotion")) if "Promotion" in row else 0
        if equipment_id is not None and stage is not None:
            promotion_index.setdefault((str(equipment_id), stage), []).append((index, row))
    skill_index: dict[tuple[str, int], list[tuple[int, Mapping[str, object]]]] = {}
    for index, row in enumerate(skill_rows):
        if not isinstance(row, Mapping):
            continue
        skill_id = _oracle_int(row.get("SkillID"))
        level = _oracle_int(row.get("Level"))
        if skill_id is not None and level is not None:
            skill_index.setdefault((str(skill_id), level), []).append((index, row))
    ability_index: dict[str, list[tuple[str, int, Mapping[str, object]]]] = {}
    for path, document in sources.ability_documents:
        ability_list = document.get("AbilityList") if isinstance(document, Mapping) else None
        if not isinstance(ability_list, list):
            continue
        for index, row in enumerate(ability_list):
            name = row.get("Name") if isinstance(row, Mapping) else None
            if isinstance(name, str) and name:
                ability_index.setdefault(name, []).append((path, index, row))

    promotion_fields = (
        ("base_hp", "BaseHP"),
        ("hp_per_level", "BaseHPAdd"),
        ("base_attack", "BaseAttack"),
        ("attack_per_level", "BaseAttackAdd"),
        ("base_defence", "BaseDefence"),
        ("defence_per_level", "BaseDefenceAdd"),
    )
    for definition in catalog.canonical_definitions:
        equipment_candidates = equipment_index.get(definition.raw_equipment_id, [])
        compare(
            f"{definition.raw_equipment_id}:equipment_row_count",
            len(equipment_candidates),
            1,
        )
        if len(equipment_candidates) != 1:
            continue
        equipment_row_index, equipment_row = equipment_candidates[0]
        expected_publication = (
            "published"
            if equipment_row.get("Release") is True
            else "unpublished"
            if equipment_row.get("Release") is False
            else "status_unknown"
        )
        compare("publication_status", definition.publication_status, expected_publication)
        compare("release_field_present", definition.release_field_present, "Release" in equipment_row)
        compare("path_type", definition.path_type, equipment_row.get("AvatarBaseType"))
        compare("rarity", definition.rarity, equipment_row.get("Rarity"))
        compare("max_promotion", definition.max_promotion, equipment_row.get("MaxPromotion"))
        compare(
            "max_superimposition",
            definition.max_superimposition,
            equipment_row.get("MaxRank"),
        )
        compare("skill_id", definition.skill_id, str(equipment_row.get("SkillID")))
        compare(
            "equipment_name_hash",
            definition.equipment_name_hash,
            _oracle_hash(equipment_row.get("EquipmentName")),
        )
        compare(
            "equipment_source_json_path",
            definition.source.evidence.get("json_path"),
            f"$[{equipment_row_index}]",
        )

        for tier in definition.promotion_tiers:
            candidates = promotion_index.get(
                (definition.raw_equipment_id, tier.promotion_stage), []
            )
            compare("promotion_row_count", len(candidates), 1)
            if len(candidates) != 1:
                continue
            row_index, row = candidates[0]
            compare("promotion_field_present", tier.promotion_field_present, "Promotion" in row)
            compare("promotion_max_level", tier.max_level, row.get("MaxLevel"))
            compare(
                "promotion_source_json_path",
                tier.source.evidence.get("json_path"),
                f"$[{row_index}]",
            )
            for value, (field_name, raw_field) in zip(
                tier.stat_values, promotion_fields, strict=True
            ):
                raw_container = row.get(raw_field)
                raw_value = (
                    raw_container.get("Value")
                    if isinstance(raw_container, Mapping)
                    else None
                )
                compare("promotion_field_name", value.field_name, field_name)
                compare("promotion_exact_value", value.exact_value, _oracle_decimal(raw_value))
                compare(
                    "promotion_value_json_path",
                    value.source.evidence.get("json_path"),
                    f"$[{row_index}].{raw_field}.Value",
                )

        for level in definition.superimposition_levels:
            candidates = skill_index.get((definition.skill_id, level.level), [])
            compare("skill_row_count", len(candidates), 1)
            if len(candidates) != 1:
                continue
            row_index, row = candidates[0]
            compare("skill_ability_name", level.ability_name, row.get("AbilityName"))
            compare("skill_name_hash", level.skill_name_hash, _oracle_hash(row.get("SkillName")))
            compare(
                "skill_description_hash",
                level.skill_description_hash,
                _oracle_hash(row.get("SkillDesc")),
            )
            raw_parameters = row.get("ParamList")
            compare(
                "parameter_count",
                len(level.parameters),
                len(raw_parameters) if isinstance(raw_parameters, list) else None,
            )
            if isinstance(raw_parameters, list):
                for parameter_index, (parameter, raw_parameter) in enumerate(
                    zip(level.parameters, raw_parameters, strict=True)
                ):
                    raw_value = (
                        raw_parameter.get("Value")
                        if isinstance(raw_parameter, Mapping)
                        else None
                    )
                    compare("parameter_index", parameter.parameter_index, parameter_index)
                    compare("parameter_value", parameter.exact_value, _oracle_decimal(raw_value))
                    compare(
                        "parameter_json_path",
                        parameter.source.evidence.get("json_path"),
                        f"$[{row_index}].ParamList[{parameter_index}].Value",
                    )
            raw_properties = row.get("AbilityProperty")
            compare(
                "property_count",
                len(level.static_properties),
                len(raw_properties) if isinstance(raw_properties, list) else None,
            )
            if isinstance(raw_properties, list):
                for property_index, (property_ir, raw_property) in enumerate(
                    zip(level.static_properties, raw_properties, strict=True)
                ):
                    raw_container = (
                        raw_property.get("Value")
                        if isinstance(raw_property, Mapping)
                        else None
                    )
                    raw_value = (
                        raw_container.get("Value")
                        if isinstance(raw_container, Mapping)
                        else None
                    )
                    compare("property_index", property_ir.property_index, property_index)
                    compare(
                        "property_type",
                        property_ir.property_type,
                        raw_property.get("PropertyType")
                        if isinstance(raw_property, Mapping)
                        else None,
                    )
                    compare("property_value", property_ir.exact_value, _oracle_decimal(raw_value))
                    compare(
                        "property_json_path",
                        property_ir.source.evidence.get("json_path"),
                        f"$[{row_index}].AbilityProperty[{property_index}].Value.Value",
                    )
            compare(
                "skill_source_json_path",
                level.source.evidence.get("json_path"),
                f"$[{row_index}]",
            )

        if definition.ability_source is not None:
            ability_candidates = ability_index.get(definition.ability_source.ability_name, [])
            compare("ability_candidate_count", len(ability_candidates), 1)
            if len(ability_candidates) == 1:
                path, record_index, _ = ability_candidates[0]
                compare("ability_source_path", definition.ability_source.source.source_path, path)
                compare("ability_record_index", definition.ability_source.record_index, record_index)
                compare(
                    "ability_source_json_path",
                    definition.ability_source.source.evidence.get("json_path"),
                    f"$.AbilityList[{record_index}]",
                )

    checks = {
        "raw_sources_are_arrays": True,
        "comparison_count_positive": comparison_count > 0,
        "raw_projection_difference_count_zero": len(differences) == 0,
        "comparison_count": comparison_count,
        "difference_count": len(differences),
        "raw_projection_difference_samples": differences,
    }
    checks["ok"] = all(
        value is True
        for key, value in checks.items()
        if key
        in {
            "raw_sources_are_arrays",
            "comparison_count_positive",
            "raw_projection_difference_count_zero",
        }
    )
    return checks


def _model_contract_checks(catalog: LightConeCatalogBuildResult) -> dict[str, Any]:
    definition = catalog.canonical_definitions[0]
    payload = definition.to_json()
    parsed = LightConeDefinitionIR.from_json(payload)
    before = parsed.to_json()
    payload["path_type"] = "mutated-after-parse"
    promotion_rows = payload["promotion_tiers"]
    if isinstance(promotion_rows, list) and promotion_rows:
        promotion_rows[0]["max_level"] = 999999
    unknown = definition.to_json()
    unknown["legacy_extra_field"] = True
    legacy = definition.to_json()
    legacy["promotion_ref_ids"] = ["legacy"]
    wrong_decimal = definition.to_json()
    wrong_decimal["promotion_tiers"][0]["stat_values"][0]["exact_value"] = "1.0"
    wrong_ability_path = thaw_json(definition.to_json())
    wrong_ability_path["ability_source"]["source"]["evidence"]["json_path"] = (
        "$.AbilityList[999999]"
    )
    unknown_definition_key = thaw_json(definition.to_json())
    unknown_definition_key["definition_key"]["unexpected"] = True
    unknown_source = thaw_json(definition.to_json())
    unknown_source["source"]["unexpected"] = True
    unknown_source_evidence = thaw_json(definition.to_json())
    unknown_source_evidence["source"]["evidence"]["unexpected"] = True
    unknown_source_fingerprint = thaw_json(definition.to_json())
    unknown_source_fingerprint["source"]["evidence"]["source_fingerprint"][
        "unexpected"
    ] = True
    damaged_stable_id = thaw_json(definition.to_json())
    damaged_stable_id["definition_key"]["stable_id"] = "light_cone::damaged"
    contradictory_publication = thaw_json(definition.to_json())
    contradictory_publication["release_field_present"] = False
    reordered_promotion_values = thaw_json(definition.to_json())
    reordered_promotion_values["promotion_tiers"][0]["stat_values"].reverse()
    forged_ability_file = thaw_json(definition.to_json())
    forged_ability_file["ability_source"]["source"]["source_path"] = (
        "ExcelOutput/EquipmentConfig.json"
    )
    missing_mechanism_key = EquipmentDefinitionKey(
        "equipment_mechanism", "validation:missing-mechanism"
    )
    forged_mechanism_definition = replace(
        definition,
        mechanism_ref_ids=(missing_mechanism_key,),
    )
    forged_mechanism_resolution = RuleBook(
        CanonicalIR(
            version=BASELINE_VERSION,
            light_cone_definitions=(forged_mechanism_definition,),
        )
    ).light_cone_definition(definition.raw_equipment_id)
    definition_input = [definition]
    issue_input = list(catalog.issues)
    detached_result = replace(
        catalog,
        diagnostic_definitions=definition_input,
        issues=issue_input,
    )
    detached_result_before = detached_result.to_summary_json()
    definition_input.append(definition)
    issue_input.append("late-invalid-value")
    checks = {
        "round_trip_exact": LightConeDefinitionIR.from_json(definition.to_json()).to_json()
        == definition.to_json(),
        "ordinary_json_dict_and_lists_are_accepted": parsed == definition,
        "parsed_object_detached_from_input": parsed.to_json() == before,
        "unknown_field_rejected": _raises(
            lambda: LightConeDefinitionIR.from_json(unknown), ValueError
        ),
        "old_placeholder_field_rejected": _raises(
            lambda: LightConeDefinitionIR.from_json(legacy), ValueError
        ),
        "noncanonical_decimal_rejected": _raises(
            lambda: LightConeDefinitionIR.from_json(wrong_decimal), ValueError
        ),
        "ability_record_index_and_json_path_mismatch_rejected": _raises(
            lambda: LightConeDefinitionIR.from_json(wrong_ability_path), ValueError
        ),
        "unknown_definition_key_field_rejected": _raises(
            lambda: LightConeDefinitionIR.from_json(unknown_definition_key), ValueError
        ),
        "unknown_source_field_rejected": _raises(
            lambda: LightConeDefinitionIR.from_json(unknown_source), ValueError
        ),
        "unknown_source_evidence_field_rejected": _raises(
            lambda: LightConeDefinitionIR.from_json(unknown_source_evidence), ValueError
        ),
        "unknown_source_fingerprint_field_rejected": _raises(
            lambda: LightConeDefinitionIR.from_json(unknown_source_fingerprint), ValueError
        ),
        "damaged_definition_stable_id_rejected": _raises(
            lambda: LightConeDefinitionIR.from_json(damaged_stable_id), ValueError
        ),
        "publication_status_missing_release_contradiction_rejected": _raises(
            lambda: LightConeDefinitionIR.from_json(contradictory_publication), ValueError
        ),
        "promotion_stat_value_order_change_rejected": _raises(
            lambda: LightConeDefinitionIR.from_json(reordered_promotion_values), ValueError
        ),
        "forged_tbgd_ability_file_namespace_rejected": _raises(
            lambda: LightConeDefinitionIR.from_json(forged_ability_file), ValueError
        ),
        "rulebook_blocks_missing_light_cone_mechanism_reference": (
            forged_mechanism_resolution.resolution_status == "blocked"
            and forged_mechanism_resolution.value is None
            and forged_mechanism_resolution.blocked_reason
            == "equipment_mechanism_reference_unresolved"
        ),
        "catalog_result_detaches_external_collections": detached_result.to_summary_json()
        == detached_result_before,
        "all_public_type_hints_resolve": all(
            bool(get_type_hints(model))
            for model in (
                type(definition),
                type(definition.promotion_tiers[0]),
                type(definition.promotion_tiers[0].stat_values[0]),
                type(definition.superimposition_levels[0]),
                type(definition.superimposition_levels[0].parameters[0])
                if definition.superimposition_levels[0].parameters
                else type(definition.superimposition_levels[0].static_properties[0]),
                type(definition.ability_source),
            )
        ),
        "nested_members_are_tuples": all(
            isinstance(definition.promotion_tiers, tuple)
            and isinstance(definition.superimposition_levels, tuple)
            and all(isinstance(tier.stat_values, tuple) for tier in definition.promotion_tiers)
            and all(
                isinstance(level.parameters, tuple)
                and isinstance(level.static_properties, tuple)
                for level in definition.superimposition_levels
            )
            for definition in catalog.canonical_definitions
        ),
    }
    checks["ok"] = all(value is True for value in checks.values())
    return checks


def _determinism_checks(
    catalog: LightConeCatalogBuildResult,
    sources: LightConeCatalogSourceBundle,
) -> dict[str, Any]:
    reordered_equipment = list(reversed(sources.equipment_rows))
    reordered_promotions = list(reversed(sources.promotion_rows))
    reordered_skills = list(reversed(sources.skill_rows))
    reordered_abilities: list[tuple[str, object]] = []
    for path, document in reversed(sources.ability_documents):
        if isinstance(document, Mapping) and isinstance(document.get("AbilityList"), list):
            cloned = dict(document)
            cloned["AbilityList"] = list(reversed(document["AbilityList"]))
            reordered_abilities.append((path, cloned))
        else:
            reordered_abilities.append((path, document))
    reordered = _rebuild(
        sources,
        equipment_rows=reordered_equipment,
        promotion_rows=reordered_promotions,
        skill_rows=reordered_skills,
        ability_documents=reordered_abilities,
    )
    source_a = build_primary_equipment_source_fingerprint(
        [("fixture/table.json", b'[{"id":1},{"id":2}]')]
    )
    source_b = build_primary_equipment_source_fingerprint(
        [("fixture/table.json", b'[{"id":2},{"id":1}]')]
    )
    catalog_fingerprint = dict(thaw_json(catalog.catalog_definition_fingerprint))
    reordered_fingerprint = dict(thaw_json(reordered.catalog_definition_fingerprint))
    checks = {
        "source_and_catalog_fingerprint_field_names_distinct": (
            catalog.source_content_fingerprint is not catalog.catalog_definition_fingerprint
            and "coverage" in catalog.source_content_fingerprint
            and "catalog_complete" in catalog.catalog_definition_fingerprint
        ),
        "source_fingerprint_changes_when_raw_row_order_changes": source_a["sha256"]
        != source_b["sha256"],
        "catalog_rebuild_after_traversal_reordering_complete": reordered.catalog_complete,
        "catalog_fingerprint_stable_under_input_traversal_order": catalog_fingerprint["sha256"]
        == reordered_fingerprint["sha256"],
        "catalog_fingerprint_algorithm_exact": catalog_fingerprint["algorithm"]
        == LIGHT_CONE_CATALOG_FINGERPRINT_ALGORITHM,
        "stable_definition_id_order": tuple(
            item.definition_key.stable_id for item in catalog.canonical_definitions
        )
        == tuple(
            sorted(item.definition_key.stable_id for item in catalog.canonical_definitions)
        ),
    }
    checks["ok"] = all(value is True for value in checks.values())
    return checks


def _negative_matrix(
    catalog: LightConeCatalogBuildResult,
    sources: LightConeCatalogSourceBundle,
    s0_summary: dict[str, Any],
) -> dict[str, Any]:
    equipment_rows = list(sources.equipment_rows)
    promotions = list(sources.promotion_rows)
    skills = list(sources.skill_rows)
    assert isinstance(equipment_rows, list) and isinstance(promotions, list) and isinstance(skills, list)
    sample_equipment = next(row for row in equipment_rows if row.get("Release") is True)
    equipment_id = sample_equipment["EquipmentID"]
    skill_id = sample_equipment["SkillID"]

    duplicate_equipment_rows = list(equipment_rows)
    duplicate_equipment_rows.append(copy.deepcopy(sample_equipment))
    duplicate_equipment = _rebuild(sources, equipment_rows=duplicate_equipment_rows)

    missing_promotion_rows = [
        row
        for row in promotions
        if not (
            row.get("EquipmentID") == equipment_id
            and row.get("Promotion", 0) == 1
        )
    ]
    missing_promotion = _rebuild(sources, promotion_rows=missing_promotion_rows)

    duplicate_rank_rows = list(skills)
    duplicate_rank_rows.append(
        copy.deepcopy(next(row for row in skills if row.get("SkillID") == skill_id))
    )
    duplicate_rank = _rebuild(sources, skill_rows=duplicate_rank_rows)

    def rebuild_with_raw_parameter(value: object) -> LightConeCatalogBuildResult:
        rows, row = _clone_matching_row(
            skills,
            lambda candidate: candidate.get("SkillID") == skill_id
            and bool(candidate.get("ParamList")),
        )
        row["ParamList"] = copy.deepcopy(row["ParamList"])
        row["ParamList"][0]["Value"] = value
        return _rebuild(sources, skill_rows=rows)

    float_parameter = rebuild_with_raw_parameter(0.125)
    string_parameter = rebuild_with_raw_parameter("0.125")
    boolean_parameter = rebuild_with_raw_parameter(True)
    object_parameter = rebuild_with_raw_parameter({"unexpected": 1})
    nan_parameter = rebuild_with_raw_parameter(Decimal("NaN"))
    infinity_parameter = rebuild_with_raw_parameter(Decimal("Infinity"))

    bad_property_rows, property_row = _clone_matching_row(
        skills, lambda row: bool(row.get("AbilityProperty"))
    )
    property_row["AbilityProperty"] = copy.deepcopy(property_row["AbilityProperty"])
    property_row["AbilityProperty"][0]["PropertyType"] = 123
    bad_property = _rebuild(sources, skill_rows=bad_property_rows)

    ability_name = catalog.canonical_definitions[0].ability_source.ability_name
    missing_ability_documents = _clone_ability_lists(sources.ability_documents)
    _remove_ability(missing_ability_documents, ability_name)
    missing_ability = _rebuild(sources, ability_documents=missing_ability_documents)

    duplicate_ability_documents = _clone_ability_lists(sources.ability_documents)
    duplicate_record = _find_ability_record(duplicate_ability_documents, ability_name)
    duplicate_ability_documents[0][1]["AbilityList"].append(copy.deepcopy(duplicate_record))
    duplicate_ability = _rebuild(sources, ability_documents=duplicate_ability_documents)

    invalid_promotion_rows = list(promotions)
    invalid_promotion_rows.append({"EquipmentID": "invalid-unowned-row"})
    invalid_promotion_identity = _rebuild(
        sources, promotion_rows=invalid_promotion_rows
    )

    invalid_skill_rows = list(skills)
    invalid_skill_rows.append({"SkillID": "invalid-unowned-row"})
    invalid_skill_identity = _rebuild(sources, skill_rows=invalid_skill_rows)

    unnamed_ability_documents = _clone_ability_lists(sources.ability_documents)
    unnamed_ability_documents[0][1]["AbilityList"].append({"Modifiers": {}})
    unnamed_ability_record = _rebuild(
        sources, ability_documents=unnamed_ability_documents
    )

    forged_path_ability_documents = [
        ("ExcelOutput/EquipmentConfig.json", document)
        for _, document in sources.ability_documents
    ]
    forged_ability_paths = _rebuild(
        sources, ability_documents=forged_path_ability_documents
    )
    unfingerprinted_ability_documents = list(sources.ability_documents)
    unfingerprinted_ability_documents[0] = (
        "Config/ConfigAbility/Equip/Unfingerprinted.json",
        unfingerprinted_ability_documents[0][1],
    )
    unfingerprinted_ability_path = _rebuild(
        sources, ability_documents=unfingerprinted_ability_documents
    )

    repeated_property_rows, repeated_row = _clone_matching_row(
        skills, lambda row: bool(row.get("AbilityProperty"))
    )
    repeated_row["AbilityProperty"] = copy.deepcopy(repeated_row["AbilityProperty"])
    repeated_row["AbilityProperty"].append(copy.deepcopy(repeated_row["AbilityProperty"][0]))
    repeated_property = _rebuild(sources, skill_rows=repeated_property_rows)
    repeated_skill_id = str(repeated_row["SkillID"])
    repeated_level = repeated_row["Level"]
    repeated_card = next(
        item for item in repeated_property.canonical_definitions if item.skill_id == repeated_skill_id
    )
    repeated_level_row = next(
        item for item in repeated_card.superimposition_levels if item.level == repeated_level
    )

    limited_equipment_rows = [copy.deepcopy(sample_equipment)]
    limited_catalog = _rebuild(sources, equipment_rows=limited_equipment_rows)

    broken_atomic_rows, broken_atomic_row = _clone_matching_row(
        skills, lambda row: row.get("SkillID") == skill_id and bool(row.get("ParamList"))
    )
    broken_atomic_row["ParamList"] = copy.deepcopy(broken_atomic_row["ParamList"])
    broken_atomic_row["ParamList"][0]["Value"] = []
    broken_atomic = _rebuild(sources, skill_rows=broken_atomic_rows)

    stale_summary = copy.deepcopy(s0_summary)
    stale_summary["primary_source_fingerprint"]["sha256"] = "0" * 64
    malformed_summary = copy.deepcopy(s0_summary)
    malformed_summary["primary_source_fingerprint"].pop("paths", None)

    checks = {
        "duplicate_equipment_identity_rejected_by_full_build_chain": _blocked_with(
            duplicate_equipment, "equipment_duplicate_identity"
        ),
        "promotion_gap_rejected_by_full_build_chain": _blocked_with(
            missing_promotion, "equipment_promotion_stage_set_incomplete"
        ),
        "duplicate_rank_rejected_by_full_build_chain": _blocked_with(
            duplicate_rank, "equipment_skill_level_duplicate"
        ),
        "float_numeric_value_rejected_before_projection": _blocked_with(
            float_parameter, "equipment_skill_parameter_invalid"
        ),
        "raw_numeric_string_rejected_before_projection": _blocked_with(
            string_parameter, "equipment_skill_parameter_invalid"
        ),
        "raw_numeric_boolean_rejected_before_projection": _blocked_with(
            boolean_parameter, "equipment_skill_parameter_invalid"
        ),
        "raw_numeric_object_rejected_before_projection": _blocked_with(
            object_parameter, "equipment_skill_parameter_invalid"
        ),
        "raw_numeric_nan_rejected_before_projection": _blocked_with(
            nan_parameter, "equipment_skill_parameter_invalid"
        ),
        "raw_numeric_infinity_rejected_before_projection": _blocked_with(
            infinity_parameter, "equipment_skill_parameter_invalid"
        ),
        "invalid_static_property_type_rejected": _blocked_with(
            bad_property, "equipment_skill_property_type_invalid"
        ),
        "missing_ability_record_rejected": _blocked_with(
            missing_ability, "light_cone_ability_source_not_unique"
        ),
        "duplicate_ability_record_rejected": _blocked_with(
            duplicate_ability, "light_cone_ability_source_not_unique"
        ),
        "unowned_invalid_promotion_identity_blocks_catalog": _blocked_with(
            invalid_promotion_identity, "equipment_promotion_identity_invalid"
        ),
        "unowned_invalid_skill_identity_blocks_catalog": _blocked_with(
            invalid_skill_identity, "equipment_skill_identity_invalid"
        ),
        "unnamed_ability_record_blocks_catalog": _blocked_with(
            unnamed_ability_record, "equipment_ability_identity_missing"
        ),
        "forged_ability_path_namespace_blocks_catalog": _blocked_with(
            forged_ability_paths,
            "equipment_ability_source_path_namespace_invalid",
        ),
        "duplicate_ability_paths_block_catalog": _has_issue(
            forged_ability_paths, "equipment_ability_source_path_duplicate"
        )
        and not forged_ability_paths.catalog_complete,
        "ability_path_must_be_source_fingerprint_member": _has_issue(
            unfingerprinted_ability_path,
            "equipment_ability_source_path_not_fingerprinted",
        )
        and not unfingerprinted_ability_path.catalog_complete,
        "duplicate_property_type_preserved_as_separate_items": repeated_property.catalog_complete
        and len(repeated_level_row.static_properties) == len(repeated_row["AbilityProperty"])
        and tuple(item.property_index for item in repeated_level_row.static_properties)
        == tuple(range(len(repeated_row["AbilityProperty"]))),
        "limited_catalog_cannot_masquerade_as_complete": not limited_catalog.catalog_complete
        and not limited_catalog.canonical_definitions
        and _has_issue(limited_catalog, "orphan_equipment_promotion_record"),
        "published_failure_keeps_canonical_directory_empty": not broken_atomic.catalog_complete
        and not broken_atomic.canonical_definitions
        and bool(broken_atomic.diagnostic_definitions),
        "incomplete_catalog_gate_raises_with_issue_result": _raises_catalog_error(
            broken_atomic
        ),
        "stale_s0_fingerprint_rejected": not fingerprint_contract_matches(
            sources.source_content_fingerprint,
            stale_summary["primary_source_fingerprint"],
        ),
        "malformed_s0_summary_rejected_fail_closed": validate_s0_summary_payload(
            malformed_summary
        )["ok"]
        is False,
    }
    checks["ok"] = all(value is True for value in checks.values())
    return checks


def _definition_sources(definition: LightConeDefinitionIR) -> tuple[Any, ...]:
    result = [definition.source]
    for tier in definition.promotion_tiers:
        result.append(tier.source)
        result.extend(item.source for item in tier.stat_values)
    for level in definition.superimposition_levels:
        result.append(level.source)
        result.extend(item.source for item in level.parameters)
        result.extend(item.source for item in level.static_properties)
    if definition.ability_source is not None:
        result.append(definition.ability_source.source)
    return tuple(result)


def _ability_name_counts(
    documents: Sequence[tuple[str, object]],
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for _, document in documents:
        ability_list = document.get("AbilityList") if isinstance(document, Mapping) else None
        if not isinstance(ability_list, list):
            continue
        for row in ability_list:
            name = row.get("Name") if isinstance(row, Mapping) else None
            if isinstance(name, str) and name:
                counts[name] += 1
    return counts


def _contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, Mapping):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_float(item) for item in value)
    return False


def _oracle_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _oracle_hash(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    raw_hash = value.get("Hash")
    if isinstance(raw_hash, bool) or not isinstance(raw_hash, (int, str)):
        return None
    return str(raw_hash)


def _oracle_decimal(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        return None
    decimal_value = Decimal(value)
    if not decimal_value.is_finite():
        return None
    if decimal_value == 0:
        return "0"
    text = format(decimal_value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _clone_matching_row(
    rows: Sequence[Mapping[str, object]],
    predicate: Any,
) -> tuple[list[Mapping[str, object]], dict[str, Any]]:
    cloned_rows = list(rows)
    for index, row in enumerate(rows):
        if predicate(row):
            cloned = dict(row)
            cloned_rows[index] = cloned
            return cloned_rows, cloned
    raise AssertionError("structural light-cone validation sample not found")


def _clone_ability_lists(
    documents: Sequence[tuple[str, object]],
) -> list[tuple[str, object]]:
    cloned_documents: list[tuple[str, object]] = []
    for path, document in documents:
        if isinstance(document, Mapping) and isinstance(document.get("AbilityList"), list):
            cloned = dict(document)
            cloned["AbilityList"] = list(document["AbilityList"])
            cloned_documents.append((path, cloned))
        else:
            cloned_documents.append((path, document))
    return cloned_documents


def _remove_ability(documents: list[tuple[str, object]], ability_name: str) -> None:
    for _, document in documents:
        if not isinstance(document, dict) or not isinstance(document.get("AbilityList"), list):
            continue
        document["AbilityList"] = [
            row
            for row in document["AbilityList"]
            if not isinstance(row, Mapping) or row.get("Name") != ability_name
        ]


def _find_ability_record(
    documents: Sequence[tuple[str, object]], ability_name: str
) -> dict[str, Any]:
    for _, document in documents:
        ability_list = document.get("AbilityList") if isinstance(document, Mapping) else None
        if not isinstance(ability_list, list):
            continue
        for row in ability_list:
            if isinstance(row, dict) and row.get("Name") == ability_name:
                return row
    raise AssertionError("ability fixture record not found")


def _has_issue(result: LightConeCatalogBuildResult, issue_code: str) -> bool:
    return any(issue.issue_code == issue_code for issue in result.issues)


def _blocked_with(result: LightConeCatalogBuildResult, issue_code: str) -> bool:
    return not result.catalog_complete and not result.canonical_definitions and _has_issue(
        result, issue_code
    )


def _raises_catalog_error(result: LightConeCatalogBuildResult) -> bool:
    try:
        require_complete_light_cone_catalog(result)
    except LightConeCatalogBuildError as exc:
        return exc.result is result and bool(exc.result.issues)
    return False


def _raises(call: Any, expected: type[BaseException]) -> bool:
    try:
        call()
    except expected:
        return True
    return False


def _section_ok(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": value.get("ok") is True,
        "failed": sorted(
            key
            for key, item in value.items()
            if key != "ok" and isinstance(item, bool) and item is not True
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate P8-S3 light-cone data cards")
    parser.add_argument("--tbgd-root", type=Path, required=True)
    parser.add_argument("--s0-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = run_validation(args.tbgd_root, args.s0_summary, args.output_dir)
    except (OSError, TypeError, ValueError) as exc:
        print(json.dumps({"ok": False, "reason": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
