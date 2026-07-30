from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from .. import BASELINE_VERSION
from ..builds.character_assembler import assemble_character_build
from ..builds.equipment_assembler import (
    assemble_equipment_build,
    validate_equipment_instance_uniqueness,
)
from ..builds.models import CharacterBuildInput
from ..equipment.models import (
    EquipmentAssemblyResult,
    EquipmentBuildInput,
    EquipmentDefinitionKey,
    RELIC_ASSEMBLY_NOT_ASSEMBLED_REASON,
    RelicInstanceInput,
    RelicSubAffixRollInput,
    RelicTemplateDefinitionIR,
    make_equipment_source,
)
from ..ir_types import IRSource, JSONValue
from ..rules.ir import (
    ActionDefinitionIR,
    AvatarProfileIR,
    AvatarPromotionTierIR,
    CanonicalIR,
    CharacterDataCardIR,
    RuleEntity,
)
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..tbgd.relic_cards import (
    RelicCanonicalCatalog,
    build_relic_catalog,
    require_complete_relic_catalog,
)
from .io import write_json


VALIDATION_VERSION = "p8_s10_relic_instance_legality_v1"
SCENARIO_PROJECTION_FILE = "p8_s10_scenario_direct_catalog.json"
MODE_FIXTURE_PROJECTION_FILE = "p8_s10_mode_fixture_catalog.json"
UNKNOWN_FIXTURE_SOURCE_PATH = (
    "validation/p8_s10/fixtures/RelicConfig.UNKNOWN.json"
)
UNKNOWN_FIXTURE_JSON_PATH = "$[0]"
UNKNOWN_FIXTURE_RAW_MODE = "VALIDATION_UNKNOWN"


def run_validation(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    catalog_build_count = 1
    catalog_result = build_relic_catalog(tbgd_root)
    catalog = require_complete_relic_catalog(catalog_result)
    rules = RuleBook(_catalog_ir(catalog))
    slots = tuple(
        sorted(
            catalog.slot_definitions,
            key=lambda item: item.definition_key.stable_id,
        )
    )
    basic_templates = tuple(
        item
        for item in catalog.template_definitions
        if item.publication_status == "published"
        and item.mode == "BASIC"
    )
    templates_by_slot = {
        slot.definition_key: tuple(
            item
            for item in basic_templates
            if item.slot_key == slot.definition_key
        )
        for slot in slots
    }
    if (
        len(slots) != 6
        or any(not candidates for candidates in templates_by_slot.values())
    ):
        raise RuntimeError(
            "P8-S9 source-driven six-slot template closure is unavailable"
        )
    slot_templates = tuple(
        templates_by_slot[slot.definition_key][0]
        for slot in slots
    )
    custom_template = next(
        (
            item
            for item in catalog.template_definitions
            if item.publication_status == "published"
            and item.mode == "CUSTOM"
        ),
        None,
    )
    if custom_template is None:
        raise RuntimeError("P8-S9 CUSTOM template catalog evidence is unavailable")

    positive_rows = _positive_slot_matrix(
        rules,
        catalog,
        slot_templates,
    )
    level_mode_rows = _level_mode_matrix(
        rules,
        catalog,
        slot_templates[0],
        custom_template,
    )
    negative_rows = _negative_matrix(
        rules,
        catalog,
        slots,
        templates_by_slot,
        slot_templates,
    )
    team_rows = _team_occupancy_matrix(catalog, slot_templates[0])
    codec_rows = _codec_fingerprint_matrix(catalog, slot_templates)
    future_effects_row = _future_effects_matrix(
        rules,
        catalog,
        slot_templates[0],
    )

    invalid_results = tuple(
        row["result"]
        for row in (*negative_rows.values(), *level_mode_rows.values())
        if isinstance(row.get("result"), EquipmentAssemblyResult)
        and row["result"].assembly_status == "blocked"
    )
    checks = {
        "empty_relic_build_valid": positive_rows["0"]["assembly_valid"],
        "partial_relic_build_valid": all(
            positive_rows[str(count)]["assembly_valid"]
            for count in range(1, 6)
        ),
        "six_distinct_slots_valid":
            positive_rows["6"]["assembly_valid"]
            and positive_rows["6"]["selection_count"] == 6,
        "slot_identity_source_driven": all(
            row["slot_identity_source_driven"]
            for row in positive_rows.values()
        ),
        "wrong_slot_rejected":
            negative_rows["wrong_slot"]["blocked"],
        "duplicate_slot_rejected":
            negative_rows["duplicate_slot"]["blocked"],
        "unknown_template_rejected":
            negative_rows["unknown_template"]["blocked"],
        "level_bounds_enforced": all(
            level_mode_rows[row_id]["passed"]
            for row_id in (
                "level_zero",
                "level_maximum",
                "level_below_zero",
                "level_above_maximum",
            )
        ),
        "unknown_mode_rejected":
            level_mode_rows["unknown_mode"]["passed"],
        "custom_mode_excluded":
            level_mode_rows["custom_mode"]["passed"],
        "team_duplicate_instance_rejected":
            team_rows["duplicate_reuse_rejected"]
            and team_rows["distinct_instances_accepted"],
        "same_identity_conflicting_payload_rejected":
            team_rows["conflicting_payload_rejected"],
        "invalid_relic_contributes_nothing":
            bool(invalid_results)
            and all(row["blocked"] for row in negative_rows.values())
            and all(_invalid_result_is_empty(item) for item in invalid_results),
        "relic_effects_deferred_after_affix_validation":
            future_effects_row["passed"],
        "instance_fingerprint_stable": all(
            codec_rows["checks"].values()
        ),
        "legacy_all_relics_blocker_absent": all(
            diagnostic.reason != "p8_s4_relic_instances_not_admitted"
            for row in positive_rows.values()
            for diagnostic in cast(
                EquipmentAssemblyResult,
                row["result"],
            ).diagnostics
        )
        and positive_rows["1"]["assembly_valid"],
    }
    checks["ok"] = all(checks.values())

    projection = _scenario_catalog_projection(catalog, slot_templates[0])
    output_dir.mkdir(parents=True, exist_ok=True)
    projection_path = output_dir / SCENARIO_PROJECTION_FILE
    write_json(projection_path, projection.to_json())
    write_json(
        output_dir / "positive_slot_matrix.json",
        _json_safe_rows(positive_rows),
    )
    write_json(
        output_dir / "level_mode_matrix.json",
        _json_safe_rows(level_mode_rows),
    )
    write_json(
        output_dir / "negative_matrix.json",
        _json_safe_rows(negative_rows),
    )
    write_json(output_dir / "team_occupancy_matrix.json", team_rows)
    write_json(output_dir / "codec_fingerprint_matrix.json", codec_rows)
    write_json(
        output_dir / "future_relic_effects_matrix.json",
        future_effects_row,
    )

    summary = {
        "schema_version": VALIDATION_VERSION,
        "ok": checks["ok"],
        "ready_for_review": checks["ok"],
        "checks": checks,
        "metrics": {
            "relic_catalog_build_count": catalog_build_count,
            "full_lowering_build_count": 0,
            "slot_count": len(slots),
            "positive_slot_case_count": len(positive_rows),
            "negative_case_count": len(negative_rows),
            "team_occupancy_case_count": 3,
            "catalog_template_count": len(catalog.template_definitions),
            "catalog_custom_template_count": sum(
                item.mode == "CUSTOM"
                for item in catalog.template_definitions
            ),
        },
        "scope": {
            "affix_values_calculated": True,
            "set_counts_calculated": False,
            "static_relic_contributions_created": False,
            "dynamic_relic_mechanisms_created": False,
            "battle_state_built": False,
            "historical_validator_run": False,
            "full_ir_written": False,
        },
        "deferred": {
            "status": "relic_assembly_not_assembled",
            "battle_admission": "blocked",
            "reason_code": RELIC_ASSEMBLY_NOT_ASSEMBLED_REASON,
        },
        "scenario_direct_catalog": projection_path.as_posix(),
    }
    write_json(output_dir / "validation_summary.json", summary)
    return summary


def run_level_mode_slice(
    tbgd_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    catalog = require_complete_relic_catalog(build_relic_catalog(tbgd_root))
    basic_template = next(
        (
            item
            for item in catalog.template_definitions
            if item.publication_status == "published"
            and item.mode == "BASIC"
        ),
        None,
    )
    custom_template = next(
        (
            item
            for item in catalog.template_definitions
            if item.publication_status == "published"
            and item.mode == "CUSTOM"
        ),
        None,
    )
    if basic_template is None or custom_template is None:
        raise RuntimeError(
            "P8-S9 BASIC/CUSTOM level-mode representatives are unavailable"
        )
    rows = _level_mode_matrix(
        RuleBook(_catalog_ir(catalog)),
        catalog,
        basic_template,
        custom_template,
    )
    checks = {
        "basic_level_bounds": all(
            rows[row_id]["passed"]
            for row_id in (
                "level_zero",
                "level_maximum",
                "level_below_zero",
                "level_above_maximum",
            )
        ),
        "custom_mode_excluded": rows["custom_mode"]["passed"],
        "unknown_mode_fixture_blocked": rows["unknown_mode"]["passed"],
    }
    projection = _scenario_catalog_projection(catalog, basic_template)
    output_dir.mkdir(parents=True, exist_ok=True)
    projection_path = output_dir / MODE_FIXTURE_PROJECTION_FILE
    write_json(projection_path, projection.to_json())
    write_json(
        output_dir / "level_mode_slice.json",
        _json_safe_rows(rows),
    )
    summary = {
        "schema_version": f"{VALIDATION_VERSION}:level_mode_slice",
        "ok": all(checks.values()),
        "checks": checks,
        "metrics": {
            "relic_catalog_build_count": 1,
            "full_lowering_build_count": 0,
            "catalog_custom_template_count": sum(
                item.mode == "CUSTOM"
                for item in catalog.template_definitions
            ),
            "level_mode_case_count": len(rows),
        },
        "catalog_projection": projection_path.as_posix(),
    }
    write_json(output_dir / "level_mode_slice_summary.json", summary)
    return summary


def run_mode_fixture_probe(
    catalog_projection_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    catalog = RelicCanonicalCatalog.from_json(
        json.loads(catalog_projection_path.read_text(encoding="utf-8"))
    )
    basic_template = next(
        (
            item
            for item in catalog.template_definitions
            if item.mode == "BASIC"
        ),
        None,
    )
    if basic_template is None:
        raise RuntimeError("mode fixture projection lacks a BASIC template")
    case = _unknown_mode_case(catalog, basic_template)
    fixture = cast(dict[str, Any], case["fixture"])
    checks = {
        "fixture_source_kind_explicit":
            fixture["source_kind"] == "validation_fixture",
        "fixture_path_not_tbgd":
            fixture["source_path"] == UNKNOWN_FIXTURE_SOURCE_PATH
            and fixture["source_path"] != "ExcelOutput/RelicConfig.json",
        "fixture_identity_self_consistent":
            fixture["identity_consistent"],
        "fixture_fingerprint_self_consistent":
            fixture["fingerprint_consistent"],
        "rulebook_block_reason_exact":
            case["rulebook_block_reason_exact"],
        "assembly_diagnostic_reason_exact":
            case["assembly_diagnostic_reason_exact"],
        "diagnostic_uses_fixture_source":
            case["diagnostic_uses_fixture_source"],
        "blocked_formal_channels_empty":
            case["formal_channels_empty"],
    }
    summary = {
        "schema_version": f"{VALIDATION_VERSION}:mode_fixture_probe",
        "ok": all(checks.values()),
        "checks": checks,
        "tbgd_read_count": 0,
        "full_lowering_build_count": 0,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        output_dir / "unknown_mode_fixture_evidence.json",
        _json_safe_rows({"unknown_mode": case})["unknown_mode"],
    )
    write_json(
        output_dir / "mode_fixture_probe_summary.json",
        summary,
    )
    return summary


def run_codec_direct(output_dir: Path) -> dict[str, Any]:
    template_key = EquipmentDefinitionKey(
        "relic_template",
        "validation:p8_s10:template",
    )
    slot_a = EquipmentDefinitionKey("relic_slot", "validation:p8_s10:slot-a")
    slot_b = EquipmentDefinitionKey("relic_slot", "validation:p8_s10:slot-b")
    main_key = EquipmentDefinitionKey(
        "relic_main_affix",
        "validation:p8_s10:main",
    )
    rolls = [
        RelicSubAffixRollInput(
            EquipmentDefinitionKey(
                "relic_sub_affix",
                "validation:p8_s10:sub-b",
            ),
            1,
            2,
        ),
        RelicSubAffixRollInput(
            EquipmentDefinitionKey(
                "relic_sub_affix",
                "validation:p8_s10:sub-a",
            ),
            2,
            1,
        ),
    ]
    instance_a = RelicInstanceInput(
        instance_id="validation:p8_s10:instance-a",
        template_key=template_key,
        slot_key=slot_a,
        level=0,
        main_affix_key=main_key,
        sub_affix_rolls=cast(Any, rolls),
    )
    instance_a_reordered = RelicInstanceInput(
        instance_id=instance_a.instance_id,
        template_key=template_key,
        slot_key=slot_a,
        level=0,
        main_affix_key=main_key,
        sub_affix_rolls=tuple(reversed(rolls)),
    )
    instance_b = RelicInstanceInput(
        instance_id="validation:p8_s10:instance-b",
        template_key=template_key,
        slot_key=slot_b,
        level=0,
        main_affix_key=main_key,
    )
    encoded_instance = instance_a.to_json()
    instance_round_trip = RelicInstanceInput.from_json(encoded_instance)
    damaged_instance = dict(encoded_instance)
    damaged_instance["instance_fingerprint"] = "0" * 64
    damaged_fingerprint_rejected = _raises(
        lambda: RelicInstanceInput.from_json(damaged_instance)
    )
    unknown_field_instance = dict(encoded_instance)
    unknown_field_instance["display_score"] = 100
    unknown_field_rejected = _raises(
        lambda: RelicInstanceInput.from_json(unknown_field_instance)
    )

    build_a = EquipmentBuildInput(
        build_id="validation:p8_s10:codec-build",
        character_card_id="validation:p8_s10:card",
        relics=(instance_b, instance_a),
        identity_labels={"display_name": "before"},
    )
    build_b = EquipmentBuildInput(
        build_id=build_a.build_id,
        character_card_id=build_a.character_card_id,
        relics=(instance_a_reordered, instance_b),
        identity_labels={"display_name": "after"},
    )
    build_round_trip = EquipmentBuildInput.from_json(build_a.to_json())
    before_external_mutation = instance_a.to_json()
    rolls.append(rolls[0])
    checks = {
        "instance_codec_round_trip":
            instance_round_trip.to_json() == encoded_instance,
        "build_codec_round_trip":
            build_round_trip.to_json() == build_a.to_json(),
        "sub_affix_order_canonicalized":
            instance_a.instance_fingerprint
            == instance_a_reordered.instance_fingerprint,
        "build_relic_order_canonicalized":
            build_a.build_fingerprint == build_b.build_fingerprint,
        "display_labels_excluded_from_fingerprint":
            build_a.build_fingerprint == build_b.build_fingerprint
            and build_a.identity_labels != build_b.identity_labels,
        "external_roll_list_detached":
            instance_a.to_json() == before_external_mutation,
        "damaged_fingerprint_rejected": damaged_fingerprint_rejected,
        "unknown_ui_field_rejected": unknown_field_rejected,
    }
    summary = {
        "schema_version": f"{VALIDATION_VERSION}:codec_direct",
        "ok": all(checks.values()),
        "checks": checks,
        "tbgd_read_count": 0,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "codec_direct_summary.json", summary)
    return summary


def run_scenario_direct(
    catalog_projection_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    payload = json.loads(catalog_projection_path.read_text(encoding="utf-8"))
    catalog = RelicCanonicalCatalog.from_json(payload)
    template = catalog.template_definitions[0]
    source = IRSource(
        source_path="validation/p8_s10/scenario_character.json",
        raw_type="P8S10ScenarioCharacterFixture",
        raw_id="p8_s10_avatar",
        evidence={"fixture": True, "scope": "scenario_admission_only"},
    )
    avatar_id = "p8_s10_avatar"
    entity_ref = f"avatar:{avatar_id}"
    enemy_entity_ref = "monster:validation:p8_s10:scenario-enemy"
    action_id = "monster_skill:validation:p8_s10:scenario-action"
    card_id = "validation:p8_s10:scenario-card"
    profile_id = "validation:p8_s10:scenario-profile"
    tier = AvatarPromotionTierIR(
        promotion_tier_id="validation:p8_s10:promotion:0",
        avatar_id=avatar_id,
        promotion=0,
        promotion_field_present=True,
        max_level=1,
        hp_base="1000",
        hp_add="0",
        attack_base="500",
        attack_add="0",
        defense_base="300",
        defense_add="0",
        speed_base="100",
        critical_chance="0.05",
        critical_damage="0.5",
        base_aggro="100",
        source=source,
        coverage_status="executable",
    )
    profile = AvatarProfileIR(
        avatar_profile_id=profile_id,
        avatar_id=avatar_id,
        base_type="ValidationPath",
        damage_type="Physical",
        skill_ids=(),
        promotion_tiers=(tier,),
        max_energy="100",
        max_energy_source=source,
        source=source,
        coverage_status="executable",
    )
    card = CharacterDataCardIR(
        card_id=card_id,
        entity_ref=entity_ref,
        profile_id=profile_id,
        skill_ids=(),
        skill_formula_binding_ids=(),
        bounce_policy_ids=(),
        source=source,
        coverage_status="executable",
        action_set={"actions": []},
    )
    ir = CanonicalIR(
        version=BASELINE_VERSION,
        entities=(
            RuleEntity(
                entity_id=entity_ref,
                entity_type="avatar",
                fields={},
                source=source,
                coverage_status="executable",
            ),
            RuleEntity(
                entity_id=enemy_entity_ref,
                entity_type="monster",
                fields={},
                source=source,
                coverage_status="executable",
            ),
            RuleEntity(
                entity_id=action_id,
                entity_type="monster_skill",
                fields={},
                source=source,
                coverage_status="executable",
            ),
        ),
        action_definitions=(
            ActionDefinitionIR(
                definition_id=(
                    "action_definition:validation:p8_s10:"
                    "scenario-action:1"
                ),
                action_id=action_id,
                level=1,
                attack_type="Normal",
                skill_effect="SingleAttack",
                target_mode="Enemy",
                bp_need=0.0,
                bp_add=0.0,
                sp_base=0.0,
                sp_multiple_ratio=0.0,
                param_list=(),
                show_stance_list=(),
                show_damage_list=(),
                stance_damage_type=None,
                source=source,
                coverage_status="executable",
            ),
        ),
        avatar_profiles=(profile,),
        character_data_cards=(card,),
        **cast(Any, _catalog_fields(catalog)),
    )
    rules = RuleBook(ir)
    relic = _instance(
        catalog,
        template,
        instance_id="validation:p8_s10:scenario-relic",
        level=0,
    )
    character_a = _character_build(card_id, "a", relic)
    single_scenario = ScenarioLoader().load_dict(
        _scenario_payload(
            entity_ref,
            enemy_entity_ref,
            action_id,
            (("ally:a", character_a),),
        )
    )
    single_identity = IdentityResolver(rules).validate(single_scenario)
    character_result = assemble_character_build(rules, character_a)
    state_build_error = ""
    try:
        ScenarioStateBuilder(rules).build(single_scenario)
    except ValueError as exc:
        state_build_error = str(exc)

    character_b = _character_build(card_id, "b", relic)
    duplicate_scenario = ScenarioLoader().load_dict(
        _scenario_payload(
            entity_ref,
            enemy_entity_ref,
            action_id,
            (("ally:a", character_a), ("ally:b", character_b)),
        )
    )
    duplicate_identity = IdentityResolver(rules).validate(duplicate_scenario)

    conflicting_relic = replace(
        relic,
        level=1 if template.max_level >= 1 else template.max_level + 1,
    )
    character_conflict = _character_build(
        card_id,
        "conflict",
        conflicting_relic,
    )
    conflict_scenario = ScenarioLoader().load_dict(
        _scenario_payload(
            entity_ref,
            enemy_entity_ref,
            action_id,
            (
                ("ally:a", character_a),
                ("ally:conflict", character_conflict),
            ),
        )
    )
    conflict_identity = IdentityResolver(rules).validate(conflict_scenario)
    equipment_result = character_result.equipment_assembly_result
    checks = {
        "structural_relic_passes_scenario_identity":
            single_identity.ok,
        "legacy_s4_identity_blocker_absent": all(
            "P8-S4 formal relic instances are not admitted" not in error
            for error in single_identity.errors
        ),
        "deferred_relic_effects_block_formal_battle_admission":
            character_result.assembly_status == "assembled"
            and character_result.battle_admission_status == "blocked"
            and equipment_result is not None
            and equipment_result.battle_admission_status == "blocked"
            and state_build_error != ""
            and "equipment_build_not_admitted_for_battle" in state_build_error,
        "team_duplicate_rejected_before_state_build":
            f"equipment_instance_id_reused:{relic.instance_id}"
            in duplicate_identity.errors,
        "team_conflicting_payload_rejected_before_state_build":
            f"equipment_instance_identity_conflict:{relic.instance_id}"
            in conflict_identity.errors,
    }
    summary = {
        "schema_version": f"{VALIDATION_VERSION}:scenario_direct",
        "ok": all(checks.values()),
        "checks": checks,
        "single_identity_errors": list(single_identity.errors),
        "state_build_error": state_build_error,
        "duplicate_identity_errors": list(duplicate_identity.errors),
        "conflict_identity_errors": list(conflict_identity.errors),
        "battle_state_returned": False,
        "tbgd_read_count": 0,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "scenario_direct_summary.json", summary)
    return summary


def _positive_slot_matrix(
    rules: RuleBook,
    catalog: RelicCanonicalCatalog,
    templates: tuple[RelicTemplateDefinitionIR, ...],
) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for count in range(7):
        relics = tuple(
            _instance(
                catalog,
                template,
                instance_id=f"validation:p8_s10:slot:{index}",
                level=0,
            )
            for index, template in enumerate(templates[:count])
        )
        result = assemble_equipment_build(
            rules,
            _equipment_build(f"positive-{count}", relics),
        )
        rows[str(count)] = {
            "assembly_valid":
                result.assembly_status == "assembled"
                and (
                    result.battle_admission_status == "admitted"
                    if count == 0
                    else result.battle_admission_status == "blocked"
                )
                and len(result.relic_selections) == count
                and len(result.battle_admission_blockers) == count
                and all(
                    blocker.channel == "relic_assembly"
                    and blocker.gap_classification == "implementation_missing"
                    and blocker.reason_code == RELIC_ASSEMBLY_NOT_ASSEMBLED_REASON
                    for blocker in result.battle_admission_blockers
                )
                and not result.static_contributions
                and not result.dynamic_mechanisms,
            "slot_identity_source_driven": all(
                selection.slot_key == relic.slot_key
                and selection.slot_source
                == rules.relic_slot_definition(
                    relic.slot_key.definition_identity
                ).value.source
                for relic, selection in zip(
                    relics,
                    result.relic_selections,
                    strict=True,
                )
            ) if len(result.relic_selections) == len(relics) else False,
            "selection_count": len(result.relic_selections),
            "battle_admission_status": result.battle_admission_status,
            "result": result,
        }
    return rows


def _unknown_fixture_payload(
    template: RelicTemplateDefinitionIR,
) -> dict[str, JSONValue]:
    return {
        "fixture_schema_version": "p8_s10_unknown_relic_template_v1",
        "raw_relic_id": template.raw_relic_id,
        "raw_mode": UNKNOWN_FIXTURE_RAW_MODE,
        "slot_key": template.slot_key.to_json(),
        "domain_key": template.domain_key.to_json(),
        "set_key": template.set_key.to_json(),
        "max_level": template.max_level,
        "main_affix_group_key": template.main_affix_group_key.to_json(),
        "sub_affix_group_key": template.sub_affix_group_key.to_json(),
    }


def _unknown_fixture_fingerprint(
    payload: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    payload_bytes = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    fingerprint_material = (
        UNKNOWN_FIXTURE_SOURCE_PATH.encode("utf-8")
        + b"\0"
        + payload_bytes
    )
    return {
        "schema_version": "p8_s10_validation_fixture_fingerprint_v1",
        "algorithm": "sha256-validation-fixture-path-and-payload-v1",
        "sha256": hashlib.sha256(fingerprint_material).hexdigest(),
        "file_count": 1,
        "byte_count": len(payload_bytes),
        "paths": [UNKNOWN_FIXTURE_SOURCE_PATH],
        "coverage": "complete_validation_fixture_payload",
    }


def _unknown_mode_case(
    catalog: RelicCanonicalCatalog,
    template: RelicTemplateDefinitionIR,
) -> dict[str, Any]:
    fixture_payload = _unknown_fixture_payload(template)
    fixture_fingerprint = _unknown_fixture_fingerprint(fixture_payload)
    fixture_source = make_equipment_source(
        source_path=UNKNOWN_FIXTURE_SOURCE_PATH,
        raw_type="RelicConfig",
        raw_id=template.raw_relic_id,
        json_path=UNKNOWN_FIXTURE_JSON_PATH,
        source_fingerprint=fixture_fingerprint,
        source_kind="validation_fixture",
    )
    unknown_template = replace(
        template,
        mode="UNKNOWN",
        raw_mode=UNKNOWN_FIXTURE_RAW_MODE,
        source=fixture_source,
        coverage_status="blocked",
        blocked_reason="relic_template_mode_unknown",
    )
    fields = _catalog_fields(catalog)
    fields["relic_template_definitions"] = tuple(
        unknown_template
        if item.definition_key == template.definition_key
        else item
        for item in catalog.template_definitions
    )
    unknown_rules = RuleBook(
        CanonicalIR(version=BASELINE_VERSION, **cast(Any, fields))
    )
    resolution = unknown_rules.relic_template_definition(
        unknown_template.definition_key.definition_identity
    )
    result = assemble_equipment_build(
        unknown_rules,
        _equipment_build(
            "unknown-mode",
            (
                _instance(
                    catalog,
                    unknown_template,
                    "validation:p8_s10:unknown-mode",
                    0,
                ),
            ),
        ),
    )
    resolution_candidates_use_fixture = (
        len(resolution.candidates) == 1
        and resolution.candidates[0].source == fixture_source
    )
    diagnostic_candidates = tuple(
        candidate
        for diagnostic in result.diagnostics
        for candidate in diagnostic.candidates
    )
    diagnostic_uses_fixture_source = (
        bool(diagnostic_candidates)
        and all(
            candidate.source == fixture_source
            for candidate in diagnostic_candidates
        )
    )
    identity_consistent = (
        fixture_payload["raw_relic_id"]
        == unknown_template.definition_key.definition_identity
        == unknown_template.raw_relic_id
        == fixture_source.raw_id
        and fixture_source.raw_type == "RelicConfig"
        and fixture_source.evidence.get("json_path")
        == UNKNOWN_FIXTURE_JSON_PATH
    )
    fingerprint_consistent = (
        fixture_source.evidence.get("source_fingerprint")
        == fixture_fingerprint
        and fixture_fingerprint["paths"]
        == [UNKNOWN_FIXTURE_SOURCE_PATH]
    )
    rulebook_block_reason_exact = (
        resolution.resolution_status == "blocked"
        and resolution.blocked_reason == "equipment_definition_not_lowered"
        and resolution.value is None
        and resolution_candidates_use_fixture
    )
    assembly_diagnostic_reason_exact = _blocked_for(
        result,
        "equipment_definition_not_lowered",
    )
    formal_channels_empty = _invalid_result_is_empty(result)
    passed = all(
        (
            fixture_source.evidence.get("source_kind")
            == "validation_fixture",
            fixture_source.source_path == UNKNOWN_FIXTURE_SOURCE_PATH,
            fixture_source.source_path != "ExcelOutput/RelicConfig.json",
            identity_consistent,
            fingerprint_consistent,
            rulebook_block_reason_exact,
            assembly_diagnostic_reason_exact,
            diagnostic_uses_fixture_source,
            formal_channels_empty,
        )
    )
    return {
        "passed": passed,
        "result": result,
        "rulebook_resolution": resolution.to_json(),
        "rulebook_block_reason_exact": rulebook_block_reason_exact,
        "assembly_diagnostic_reason_exact": assembly_diagnostic_reason_exact,
        "diagnostic_uses_fixture_source": diagnostic_uses_fixture_source,
        "formal_channels_empty": formal_channels_empty,
        "fixture": {
            "payload": fixture_payload,
            "source": fixture_source.to_json(),
            "source_kind": fixture_source.evidence.get("source_kind"),
            "source_path": fixture_source.source_path,
            "identity_consistent": identity_consistent,
            "fingerprint_consistent": fingerprint_consistent,
        },
    }


def _level_mode_matrix(
    rules: RuleBook,
    catalog: RelicCanonicalCatalog,
    template: RelicTemplateDefinitionIR,
    custom_template: RelicTemplateDefinitionIR,
) -> dict[str, dict[str, Any]]:
    zero = assemble_equipment_build(
        rules,
        _equipment_build(
            "level-zero",
            (_instance(catalog, template, "validation:p8_s10:level-zero", 0),),
        ),
    )
    maximum = assemble_equipment_build(
        rules,
        _equipment_build(
            "level-max",
            (
                _instance(
                    catalog,
                    template,
                    "validation:p8_s10:level-max",
                    template.max_level,
                ),
            ),
        ),
    )
    below = assemble_equipment_build(
        rules,
        _equipment_build(
            "level-below",
            (_instance(catalog, template, "validation:p8_s10:level-below", -1),),
        ),
    )
    above = assemble_equipment_build(
        rules,
        _equipment_build(
            "level-above",
            (
                _instance(
                    catalog,
                    template,
                    "validation:p8_s10:level-above",
                    template.max_level + 1,
                ),
            ),
        ),
    )
    custom = assemble_equipment_build(
        rules,
        _equipment_build(
            "custom-mode",
            (
                _instance(
                    catalog,
                    custom_template,
                    "validation:p8_s10:custom-mode",
                    0,
                ),
            ),
        ),
    )
    unknown = _unknown_mode_case(catalog, template)
    return {
        "level_zero": {
            "passed": zero.assembly_status == "assembled",
            "result": zero,
        },
        "level_maximum": {
            "passed": maximum.assembly_status == "assembled",
            "result": maximum,
        },
        "level_below_zero": {
            "passed": _blocked_for(below, "relic_level_outside_template_bounds"),
            "result": below,
        },
        "level_above_maximum": {
            "passed": _blocked_for(above, "relic_level_outside_template_bounds"),
            "result": above,
        },
        "custom_mode": {
            "passed":
                _blocked_for(
                    custom,
                    "relic_template_mode_not_admitted:CUSTOM",
                )
                and _invalid_result_is_empty(custom),
            "result": custom,
        },
        "unknown_mode": unknown,
    }


def _negative_matrix(
    rules: RuleBook,
    catalog: RelicCanonicalCatalog,
    slots: tuple[Any, ...],
    templates_by_slot: dict[EquipmentDefinitionKey, tuple[RelicTemplateDefinitionIR, ...]],
    slot_templates: tuple[RelicTemplateDefinitionIR, ...],
) -> dict[str, dict[str, Any]]:
    template = slot_templates[0]
    base = _instance(
        catalog,
        template,
        "validation:p8_s10:negative-base",
        0,
    )
    wrong_slot_result = assemble_equipment_build(
        rules,
        _equipment_build(
            "wrong-slot",
            (
                replace(
                    base,
                    instance_id="validation:p8_s10:wrong-slot",
                    slot_key=slots[1].definition_key,
                ),
            ),
        ),
    )
    duplicate_candidates = templates_by_slot[template.slot_key]
    if len(duplicate_candidates) < 2:
        raise RuntimeError(
            "P8-S9 does not expose two templates for duplicate-slot validation"
        )
    duplicate_slot_result = assemble_equipment_build(
        rules,
        _equipment_build(
            "duplicate-slot",
            (
                _instance(
                    catalog,
                    duplicate_candidates[0],
                    "validation:p8_s10:duplicate-slot-a",
                    0,
                ),
                _instance(
                    catalog,
                    duplicate_candidates[1],
                    "validation:p8_s10:duplicate-slot-b",
                    0,
                ),
            ),
        ),
    )
    unknown_template_result = assemble_equipment_build(
        rules,
        _equipment_build(
            "unknown-template",
            (
                replace(
                    base,
                    instance_id="validation:p8_s10:unknown-template",
                    template_key=EquipmentDefinitionKey(
                        "relic_template",
                        "validation:p8_s10:missing-template",
                    ),
                ),
            ),
        ),
    )
    duplicate_identity_result = assemble_equipment_build(
        rules,
        _equipment_build("duplicate-identity", (base, base)),
    )
    unpublished_template = replace(
        template,
        publication_status="unpublished",
    )
    unpublished_rules = RuleBook(
        _catalog_ir(_replace_template(catalog, unpublished_template))
    )
    unpublished_result = assemble_equipment_build(
        unpublished_rules,
        _equipment_build(
            "unpublished",
            (
                replace(
                    base,
                    instance_id="validation:p8_s10:unpublished",
                ),
            ),
        ),
    )
    blocked_template = replace(
        template,
        coverage_status="blocked",
        blocked_reason="validation_relic_template_not_lowered",
    )
    blocked_template_result = assemble_equipment_build(
        RuleBook(_catalog_ir(_replace_template(catalog, blocked_template))),
        _equipment_build(
            "blocked-template",
            (
                replace(
                    base,
                    instance_id="validation:p8_s10:blocked-template",
                ),
            ),
        ),
    )
    return {
        "wrong_slot": {
            "blocked": _blocked_for(
                wrong_slot_result,
                "relic_template_slot_mismatch",
            ),
            "result": wrong_slot_result,
        },
        "duplicate_slot": {
            "blocked": _blocked_for(
                duplicate_slot_result,
                "relic_slot_reused",
            ),
            "result": duplicate_slot_result,
        },
        "unknown_template": {
            "blocked": _blocked_for(
                unknown_template_result,
                "equipment_definition_missing",
            ),
            "result": unknown_template_result,
        },
        "duplicate_identity": {
            "blocked":
                duplicate_identity_result.assembly_status == "blocked"
                and any(
                    diagnostic.reason.startswith(
                        "equipment_instance_id_reused:"
                    )
                    for diagnostic in duplicate_identity_result.diagnostics
                ),
            "result": duplicate_identity_result,
        },
        "unpublished_template": {
            "blocked":
                unpublished_result.assembly_status == "blocked"
                and any(
                    diagnostic.reason.startswith(
                        "relic_template_publication_status_not_admitted:"
                    )
                    for diagnostic in unpublished_result.diagnostics
                ),
            "result": unpublished_result,
        },
        "blocked_template": {
            "blocked": _blocked_for(
                blocked_template_result,
                "equipment_definition_not_lowered",
            ),
            "result": blocked_template_result,
        },
    }


def _team_occupancy_matrix(
    catalog: RelicCanonicalCatalog,
    template: RelicTemplateDefinitionIR,
) -> dict[str, Any]:
    shared = _instance(
        catalog,
        template,
        "validation:p8_s10:team-shared",
        0,
    )
    build_a = _equipment_build(
        "team-a",
        (shared,),
        character_card_id="validation:p8_s10:team-card-a",
    )
    build_b = _equipment_build(
        "team-b",
        (shared,),
        character_card_id="validation:p8_s10:team-card-b",
    )
    reused_errors = validate_equipment_instance_uniqueness(
        (build_a, build_b)
    )
    conflicting = replace(
        shared,
        level=1 if template.max_level >= 1 else template.max_level + 1,
    )
    conflict_errors = validate_equipment_instance_uniqueness(
        (
            build_a,
            _equipment_build(
                "team-conflict",
                (conflicting,),
                character_card_id="validation:p8_s10:team-card-c",
            ),
        )
    )
    distinct = replace(
        shared,
        instance_id="validation:p8_s10:team-distinct",
    )
    distinct_errors = validate_equipment_instance_uniqueness(
        (
            build_a,
            _equipment_build(
                "team-distinct",
                (distinct,),
                character_card_id="validation:p8_s10:team-card-b",
            ),
        )
    )
    return {
        "duplicate_reuse_rejected":
            f"equipment_instance_id_reused:{shared.instance_id}"
            in reused_errors,
        "conflicting_payload_rejected":
            f"equipment_instance_identity_conflict:{shared.instance_id}"
            in conflict_errors,
        "distinct_instances_accepted": not distinct_errors,
        "duplicate_errors": list(reused_errors),
        "conflict_errors": list(conflict_errors),
        "distinct_errors": list(distinct_errors),
    }


def _codec_fingerprint_matrix(
    catalog: RelicCanonicalCatalog,
    templates: tuple[RelicTemplateDefinitionIR, ...],
) -> dict[str, Any]:
    template = templates[0]
    sub_affixes = tuple(
        item
        for item in catalog.sub_affix_definitions
        if item.group_key == template.sub_affix_group_key
    )
    if len(sub_affixes) < 2:
        raise RuntimeError(
            "P8-S9 sub-affix group lacks two codec order representatives"
        )
    rolls = (
        RelicSubAffixRollInput(sub_affixes[1].definition_key, 1, 2),
        RelicSubAffixRollInput(sub_affixes[0].definition_key, 2, 1),
    )
    canonical = _instance(
        catalog,
        template,
        "validation:p8_s10:fingerprint",
        0,
        sub_affix_rolls=rolls,
    )
    reordered = _instance(
        catalog,
        template,
        canonical.instance_id,
        0,
        sub_affix_rolls=tuple(reversed(rolls)),
    )
    changed = replace(
        canonical,
        main_affix_key=EquipmentDefinitionKey(
            "relic_main_affix",
            "validation:p8_s10:changed-affix-payload",
        ),
    )
    second = _instance(
        catalog,
        templates[1],
        "validation:p8_s10:fingerprint-second",
        0,
    )
    build_forward = EquipmentBuildInput(
        build_id="validation:p8_s10:fingerprint-build",
        character_card_id="validation:p8_s10:card",
        relics=(canonical, second),
        identity_labels={"display_name": "forward"},
    )
    build_reverse = EquipmentBuildInput(
        build_id=build_forward.build_id,
        character_card_id=build_forward.character_card_id,
        relics=(second, reordered),
        identity_labels={"display_name": "reverse"},
    )
    relic_list = [canonical, second]
    labels = {"display_name": "detached"}
    detached_build = EquipmentBuildInput(
        build_id="validation:p8_s10:detached-build",
        character_card_id="validation:p8_s10:card",
        relics=cast(Any, relic_list),
        identity_labels=labels,
    )
    detached_before = detached_build.to_json()
    relic_list.append(canonical)
    labels["display_name"] = "mutated"
    encoded = canonical.to_json()
    damaged = dict(encoded)
    damaged["instance_fingerprint"] = "f" * 64
    checks = {
        "sub_affix_order_normalized":
            canonical.instance_fingerprint == reordered.instance_fingerprint,
        "relic_order_normalized":
            build_forward.build_fingerprint
            == build_reverse.build_fingerprint,
        "payload_change_detected":
            canonical.instance_fingerprint != changed.instance_fingerprint,
        "display_fields_excluded":
            build_forward.build_fingerprint
            == build_reverse.build_fingerprint
            and build_forward.identity_labels
            != build_reverse.identity_labels,
        "external_mutation_detached":
            detached_build.to_json() == detached_before,
        "instance_round_trip":
            RelicInstanceInput.from_json(encoded).to_json() == encoded,
        "build_round_trip":
            EquipmentBuildInput.from_json(build_forward.to_json()).to_json()
            == build_forward.to_json(),
        "damaged_instance_fingerprint_rejected":
            _raises(lambda: RelicInstanceInput.from_json(damaged)),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "instance_fingerprint": canonical.instance_fingerprint,
        "build_fingerprint": build_forward.build_fingerprint,
    }


def _future_effects_matrix(
    rules: RuleBook,
    catalog: RelicCanonicalCatalog,
    template: RelicTemplateDefinitionIR,
) -> dict[str, Any]:
    instance = _instance(
        catalog,
        template,
        "validation:p8_s10:future-effects",
        0,
    )
    result = assemble_equipment_build(
        rules,
        _equipment_build("future-effects", (instance,)),
    )
    encoded = result.to_json()
    passed = (
        result.assembly_status == "assembled"
        and result.battle_admission_status == "blocked"
        and len(result.relic_selections) == 1
        and result.relic_selections[0].affix_validation_status
        == "main_and_sub_affixes_validated"
        and tuple(
            (
                blocker.channel,
                blocker.gap_classification,
                blocker.reason_code,
            )
            for blocker in result.battle_admission_blockers
        )
        == (
            (
                "relic_assembly",
                "implementation_missing",
                RELIC_ASSEMBLY_NOT_ASSEMBLED_REASON,
            ),
        )
        and not result.static_contributions
        and not result.dynamic_mechanisms
        and not result.activation_decisions
        and not result.source_ledger
        and "set_counts" not in encoded
        and "set_thresholds" not in encoded
    )
    return {
        "passed": passed,
        "assembly_status": result.assembly_status,
        "battle_admission_status": result.battle_admission_status,
        "affix_validation_status": (
            result.relic_selections[0].affix_validation_status
            if result.relic_selections
            else "missing"
        ),
        "blocker_reason_codes": [
            blocker.reason_code
            for blocker in result.battle_admission_blockers
        ],
        "formal_contribution_counts": {
            "static": len(result.static_contributions),
            "dynamic": len(result.dynamic_mechanisms),
            "activation": len(result.activation_decisions),
            "source_ledger": len(result.source_ledger),
        },
    }


def _instance(
    catalog: RelicCanonicalCatalog,
    template: RelicTemplateDefinitionIR,
    instance_id: str,
    level: int,
    *,
    sub_affix_rolls: tuple[RelicSubAffixRollInput, ...] | None = None,
) -> RelicInstanceInput:
    main_affix = next(
        item
        for item in catalog.main_affix_definitions
        if item.group_key == template.main_affix_group_key
    )
    if sub_affix_rolls is None:
        sub_affix = next(
            item
            for item in catalog.sub_affix_definitions
            if item.group_key == template.sub_affix_group_key
        )
        sub_affix_rolls = (
            RelicSubAffixRollInput(
                affix_key=sub_affix.definition_key,
                count=1,
                step=0,
            ),
        )
    return RelicInstanceInput(
        instance_id=instance_id,
        template_key=template.definition_key,
        slot_key=template.slot_key,
        level=level,
        main_affix_key=main_affix.definition_key,
        sub_affix_rolls=sub_affix_rolls,
    )


def _equipment_build(
    suffix: str,
    relics: tuple[RelicInstanceInput, ...],
    *,
    character_card_id: str = "validation:p8_s10:card",
) -> EquipmentBuildInput:
    return EquipmentBuildInput(
        build_id=f"validation:p8_s10:equipment:{suffix}",
        character_card_id=character_card_id,
        relics=relics,
    )


def _character_build(
    card_id: str,
    suffix: str,
    relic: RelicInstanceInput,
) -> CharacterBuildInput:
    return CharacterBuildInput(
        build_id=f"validation:p8_s10:character:{suffix}",
        character_card_id=card_id,
        level=1,
        promotion=0,
        eidolon_level=0,
        unlocked_trace_node_ids=(),
        equipment_build=EquipmentBuildInput(
            build_id=f"validation:p8_s10:scenario-equipment:{suffix}",
            character_card_id=card_id,
            relics=(relic,),
        ),
    )


def _scenario_payload(
    entity_ref: str,
    enemy_entity_ref: str,
    action_id: str,
    allies: tuple[tuple[str, CharacterBuildInput], ...],
) -> dict[str, Any]:
    enemy_unit_id = "enemy:p8_s10:fixture"
    return {
        "scenario_id": f"validation:p8_s10:{allies[-1][0]}",
        "version": VALIDATION_VERSION,
        "units": [
            {
                "unit_id": unit_id,
                "side": "ally",
                "entity_ref": entity_ref,
                "level": build.level,
                "eidolon_level": build.eidolon_level,
                "position": index + 1,
                "build_mode": "assembled_character_build",
                "panel": None,
                "character_build": build.to_json(),
                "initial_condition": {
                    "hp_mode": "full",
                    "initial_energy": "0",
                },
            }
            for index, (unit_id, build) in enumerate(allies)
        ] + [
            {
                "unit_id": enemy_unit_id,
                "side": "enemy",
                "entity_ref": enemy_entity_ref,
                "level": 1,
                "position": 1,
                "build_mode": "kernel_fixture",
                "panel": {
                    "max_hp": 1000,
                    "hp": 1000,
                    "attack": 100,
                    "defense": 100,
                    "speed": 100,
                    "toughness": 60,
                    "max_toughness": 60,
                },
            },
        ],
        "route": [
            {
                "actor_id": enemy_unit_id,
                "action_ref": action_id,
                "action_level": 1,
                "target_ids": [allies[0][0]],
                "source": "manual",
            },
        ],
        "battle_setup": {
            "timeline": {"mode": "runtime_initialize"},
        },
    }


def _catalog_fields(catalog: RelicCanonicalCatalog) -> dict[str, object]:
    return {
        "relic_domain_definitions": catalog.domain_definitions,
        "relic_slot_definitions": catalog.slot_definitions,
        "relic_main_affix_group_definitions":
            catalog.main_affix_group_definitions,
        "relic_main_affix_definitions": catalog.main_affix_definitions,
        "relic_sub_affix_group_definitions":
            catalog.sub_affix_group_definitions,
        "relic_sub_affix_definitions": catalog.sub_affix_definitions,
        "relic_template_definitions": catalog.template_definitions,
        "relic_set_definitions": catalog.set_definitions,
        "relic_set_thresholds": catalog.set_thresholds,
    }


def _catalog_ir(catalog: RelicCanonicalCatalog) -> CanonicalIR:
    return CanonicalIR(
        version=BASELINE_VERSION,
        **cast(Any, _catalog_fields(catalog)),
    )


def _replace_template(
    catalog: RelicCanonicalCatalog,
    replacement: RelicTemplateDefinitionIR,
) -> RelicCanonicalCatalog:
    return replace(
        catalog,
        template_definitions=tuple(
            replacement
            if item.definition_key == replacement.definition_key
            else item
            for item in catalog.template_definitions
        ),
    )


def _scenario_catalog_projection(
    catalog: RelicCanonicalCatalog,
    template: RelicTemplateDefinitionIR,
) -> RelicCanonicalCatalog:
    return RelicCanonicalCatalog(
        domain_definitions=tuple(
            item
            for item in catalog.domain_definitions
            if item.definition_key == template.domain_key
        ),
        slot_definitions=tuple(
            item
            for item in catalog.slot_definitions
            if item.domain_key == template.domain_key
        ),
        main_affix_group_definitions=tuple(
            item
            for item in catalog.main_affix_group_definitions
            if item.definition_key == template.main_affix_group_key
        ),
        main_affix_definitions=tuple(
            item
            for item in catalog.main_affix_definitions
            if item.group_key == template.main_affix_group_key
        ),
        sub_affix_group_definitions=tuple(
            item
            for item in catalog.sub_affix_group_definitions
            if item.definition_key == template.sub_affix_group_key
        ),
        sub_affix_definitions=tuple(
            item
            for item in catalog.sub_affix_definitions
            if item.group_key == template.sub_affix_group_key
        ),
        template_definitions=(template,),
        set_definitions=tuple(
            item
            for item in catalog.set_definitions
            if item.definition_key == template.set_key
        ),
        set_thresholds=tuple(
            item
            for item in catalog.set_thresholds
            if item.set_key == template.set_key
        ),
    )


def _blocked_for(
    result: EquipmentAssemblyResult,
    reason: str,
) -> bool:
    return (
        result.assembly_status == "blocked"
        and result.battle_admission_status == "blocked"
        and any(diagnostic.reason == reason for diagnostic in result.diagnostics)
    )


def _invalid_result_is_empty(result: EquipmentAssemblyResult) -> bool:
    return (
        result.assembly_status == "blocked"
        and not result.relic_selections
        and not result.static_contributions
        and not result.dynamic_mechanisms
        and not result.activation_decisions
        and not result.battle_admission_blockers
        and not result.source_ledger
    )


def _json_safe_rows(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        row_id: {
            key: (
                value.to_json()
                if isinstance(value, EquipmentAssemblyResult)
                else value
            )
            for key, value in row.items()
        }
        for row_id, row in rows.items()
    }


def _raises(callback: Any) -> bool:
    try:
        callback()
    except (TypeError, ValueError):
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate P8-S10 relic instance legality",
    )
    parser.add_argument("--tbgd-root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--codec-direct", action="store_true")
    modes.add_argument("--scenario-direct", action="store_true")
    modes.add_argument("--level-mode-slice", action="store_true")
    modes.add_argument("--mode-fixture-probe", action="store_true")
    parser.add_argument("--catalog-projection", type=Path)
    args = parser.parse_args()
    try:
        if args.codec_direct:
            summary = run_codec_direct(args.output_dir)
        elif args.scenario_direct:
            if args.catalog_projection is None:
                parser.error("--scenario-direct requires --catalog-projection")
            summary = run_scenario_direct(
                args.catalog_projection,
                args.output_dir,
            )
        elif args.level_mode_slice:
            if args.tbgd_root is None:
                parser.error("--level-mode-slice requires --tbgd-root")
            summary = run_level_mode_slice(
                args.tbgd_root,
                args.output_dir,
            )
        elif args.mode_fixture_probe:
            if args.catalog_projection is None:
                parser.error(
                    "--mode-fixture-probe requires --catalog-projection"
                )
            summary = run_mode_fixture_probe(
                args.catalog_projection,
                args.output_dir,
            )
        else:
            if args.tbgd_root is None:
                parser.error("main validation requires --tbgd-root")
            summary = run_validation(args.tbgd_root, args.output_dir)
    except (OSError, TypeError, ValueError, RuntimeError, StopIteration) as exc:
        print(
            json.dumps(
                {"ok": False, "reason": str(exc)},
                ensure_ascii=False,
            )
        )
        return 1
    mode = (
        "codec_direct"
        if args.codec_direct
        else "scenario_direct"
        if args.scenario_direct
        else "level_mode_slice"
        if args.level_mode_slice
        else "mode_fixture_probe"
        if args.mode_fixture_probe
        else "main"
    )
    print(f"v8 {VALIDATION_VERSION} ok={summary['ok']} mode={mode}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
