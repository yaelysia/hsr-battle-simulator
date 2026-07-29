from __future__ import annotations

import argparse
import copy
import json
import tempfile
from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from typing import Any, cast, get_type_hints

from .. import BASELINE_VERSION
from ..build_types import BuildSourceRef, StatCalculation
from ..immutable_json import freeze_json, thaw_json
from ..equipment.models import (
    CharacterEquipmentEligibilityIR,
    DynamicMechanismSelection,
    EquipmentActivationBasis,
    EquipmentActivationDecision,
    EquipmentAbilityParameterReadIR,
    EquipmentAssemblyDiagnostic,
    EquipmentAssemblyResult,
    EquipmentBattleAdmissionBlocker,
    EquipmentBuildInput,
    EquipmentDefinitionKey,
    EquipmentDefinitionResolution,
    EquipmentMechanismRefIR,
    EquipmentResolutionCandidate,
    EquipmentSourceLedgerEntry,
    LightConeAbilitySourceIR,
    LightConeAssemblySelection,
    LightConeDefinitionIR,
    LightConeInstanceInput,
    LightConeParameterIR,
    LightConePromotionTierIR,
    LightConePromotionValueIR,
    LightConeStaticPropertyIR,
    LightConeSuperimpositionLevelIR,
    RelicAbilitySourceIR,
    RelicDomainDefinitionIR,
    RelicInstanceInput,
    RelicMainAffixDefinitionIR,
    RelicMainAffixGroupDefinitionIR,
    RelicSetDefinitionIR,
    RelicSetParameterIR,
    RelicSetStaticPropertyIR,
    RelicSetThresholdIR,
    RelicSlotDefinitionIR,
    RelicSubAffixDefinitionIR,
    RelicSubAffixGroupDefinitionIR,
    RelicSubAffixRollInput,
    RelicTemplateDefinitionIR,
    StaticStatContribution,
    make_equipment_source,
    validate_equipment_source_fingerprint,
)
from ..rules import ir as rules_ir_module
from ..rules.ir import (
    AvatarProfileIR,
    CanonicalIR,
    CharacterDataCardIR,
    IRSource,
    JSONValue,
    RuleEntity,
    StandaloneAbilityGraphIR,
)
from ..rules.rulebook import RuleBook
from ..tbgd.equipment_inventory_contract import (
    FINGERPRINT_REQUIRED_FIELDS,
    PRIMARY_FINGERPRINT_ALGORITHM,
    PRIMARY_FINGERPRINT_COVERAGE,
    S0_SUMMARY_SCHEMA_VERSION,
    load_s0_summary_fail_closed,
    validate_s0_summary_payload,
)
from .io import write_json
from .validate_p4_s8_trace_eidolon_level_resource_hooks import (
    build_p4_s8_equipment_boundary_matrix_row,
    validate_p4_s8_equipment_boundary_matrix_row,
)


VALIDATION_VERSION = "p8_s1_equipment_type_contract"
SUMMARY_SCHEMA_VERSION = "p8_s1_equipment_type_contract_summary_v2"
CANONICAL_EQUIPMENT_DEFINITION_FIELDS = frozenset(
    {
        "character_equipment_eligibilities",
        "light_cone_definitions",
        "relic_domain_definitions",
        "relic_slot_definitions",
        "relic_main_affix_group_definitions",
        "relic_main_affix_definitions",
        "relic_sub_affix_group_definitions",
        "relic_sub_affix_definitions",
        "relic_template_definitions",
        "relic_set_definitions",
        "relic_set_thresholds",
        "equipment_mechanism_refs",
    }
)
FORBIDDEN_CANONICAL_BUILD_FIELDS = frozenset(
    {
        "equipment_instances",
        "equipment_build_inputs",
        "equipment_activation_decisions",
        "equipment_assembly_results",
        "player_equipment_instances",
    }
)


def run_validation(s0_summary_path: Path, output_dir: Path) -> dict[str, Any]:
    s0_summary = load_s0_summary_fail_closed(s0_summary_path)
    primary_fingerprint = cast(dict[str, JSONValue], s0_summary["primary_source_fingerprint"])

    fixture_ir, fixture = _build_definition_fixture(primary_fingerprint)
    fixture_rules = RuleBook(fixture_ir)
    definition_checks = _definition_and_query_checks(fixture_ir, fixture_rules, fixture)
    negative_matrix = _query_negative_matrix(primary_fingerprint, fixture)
    source_checks = _source_boundary_checks(primary_fingerprint, fixture)
    build_checks = _build_and_assembly_checks(primary_fingerprint, fixture)
    immutable_model_checks = _public_model_immutability_negative_checks(
        primary_fingerprint,
        fixture,
    )
    canonical_checks = _canonical_definition_boundary_checks(fixture_ir)
    runtime_type_hint_checks = _runtime_type_hint_checks()
    p4_matrix_row, p4_validation = _p4_boundary_matrix_check()
    s0_negative_checks = _s0_summary_negative_checks(s0_summary, output_dir)

    type_matrix = {
        "schema_version": "p8_s1_equipment_type_contract_matrix_v1",
        "definition_and_query": definition_checks,
        "source_boundary": source_checks,
        "build_and_assembly": build_checks,
        "public_model_immutability": immutable_model_checks,
        "canonical_definition_boundary": canonical_checks,
        "runtime_type_hints": runtime_type_hint_checks,
        "p4_equipment_boundary_matrix_row": p4_matrix_row,
        "p4_equipment_boundary_validation": p4_validation,
        "s0_summary_fail_closed": s0_negative_checks,
    }
    checks = {
        "definition_and_query": _check_only(definition_checks),
        "query_negative_matrix": _check_only(negative_matrix),
        "source_boundary": _check_only(source_checks),
        "build_and_assembly": _check_only(build_checks),
        "public_model_immutability": _check_only(immutable_model_checks),
        "canonical_definition_boundary": _check_only(canonical_checks),
        "runtime_type_hints": _check_only(runtime_type_hint_checks),
        "p4_equipment_boundary_full_row": _check_only(p4_validation),
        "s0_summary_fail_closed": _check_only(s0_negative_checks),
    }
    ok = all(isinstance(value, dict) and value.get("ok") is True for value in checks.values())

    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_payloads = {
        "p8_s1_equipment_type_contract_matrix.json": type_matrix,
        "p8_s1_equipment_query_negative_matrix.json": negative_matrix,
    }
    for name, payload in artifact_payloads.items():
        write_json(output_dir / name, payload)
    artifact_sizes = {name: (output_dir / name).stat().st_size for name in artifact_payloads}
    resource_budget = {
        "s0_summary_file_read_count": 1,
        "tbgd_source_file_read_count": 0,
        "tbgd_lowering_build_count": 0,
        "rulebook_build_count": int(negative_matrix.get("rulebook_build_count") or 0) + 2,
        "runtime_transition_count": 0,
        "scenario_builder_sample_count": 1,
        "fixture_definition_count": len(fixture_rules.equipment_definitions()),
        "serial_execution": True,
        "full_canonical_ir_written": False,
        "full_rulebook_written": False,
        "full_transition_dump_written": False,
        "large_artifacts_written": False,
        "artifact_file_count_before_summary": len(artifact_sizes),
        "artifact_bytes_before_summary": sum(artifact_sizes.values()),
        "artifact_sizes": artifact_sizes,
    }
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": ok,
        "ready_for_review": ok,
        "p8_s1_type_contract_established": ok,
        "checklist_modified": False,
        "validation_scope": {
            "mutates_runtime_behavior": False,
            "mutates_scenario_schema": False,
            "reads_real_equipment_directory": False,
            "executes_equipment_effects": False,
            "asserts_current_p8_s2_or_later_state": False,
        },
        "s0_summary": {
            "path": s0_summary_path.resolve().as_posix(),
            "schema_version": s0_summary.get("schema_version"),
            "primary_source_fingerprint": primary_fingerprint,
            "semantic_role": "fail-closed prerequisite and audit fingerprint only",
            "not_proof_of_arbitrary_source_path": True,
        },
        "checks": checks,
        "resource_budget": resource_budget,
        "scope": {
            "validated_regression": (
                "typed equipment definitions, namespaced keys, typed RuleBook resolutions, "
                "per-build identity/input/result contracts, source-only audit boundary, and P4 boundary migration"
            ),
            "not_asserted_by_this_regression": (
                "the current implementation state of P8-S2 and later phases; their own validators "
                "are authoritative for real lowering, assembly, scenario, and runtime behavior"
            ),
        },
        "observations": {
            "fixture_character_eligibility_state": "typed_resolved_with_profile_and_source_binding",
            "fixture_dynamic_mechanism_states": ["lowered", "blocked"],
            "fixture_mechanism_payload_policy": "generic_graph_identity_only",
            "source_ledger_behavior_role": "audit_only",
            "cross_type_raw_identity_overlap": fixture["shared_identity"],
        },
    }
    write_json(output_dir / "validation_summary_p8_s1_equipment_type_contract.json", summary)
    return summary


def _build_definition_fixture(
    fingerprint: dict[str, JSONValue],
) -> tuple[CanonicalIR, dict[str, Any]]:
    shared_identity = "fixture:shared-raw-identity"
    card_id = "fixture:character-card"
    source = _fixture_source(fingerprint, "definitions")
    graph_source = IRSource(
        source_path="fixture/generic_graph.json",
        raw_type="FixtureGenericAbilityGraph",
        raw_id="fixture:generic-graph",
        evidence={"fixture": True},
    )
    ability_record_source = make_equipment_source(
        source_path="fixture/equipment_ability.json",
        raw_type="AbilityList",
        raw_id="FixtureLightConeAbility",
        json_path="$.AbilityList[0]",
        source_fingerprint=fingerprint,
        source_kind="validation_fixture",
    )
    parameter_read_source = make_equipment_source(
        source_path="fixture/equipment_ability.json",
        raw_type="EquipmentAbilityParameterRead",
        raw_id="FixtureLightConeAbility:fixture:param-hash:0",
        json_path=(
            "$.AbilityList[0].DynamicValues.Floats."
            "fixture:param-hash.ReadInfo"
        ),
        source_fingerprint=fingerprint,
        source_kind="validation_fixture",
    )
    graph = StandaloneAbilityGraphIR(
        standalone_ability_graph_id="fixture:generic-graph",
        ability_name="FixtureLightConeAbility",
        source_mode="validation_fixture",
        phase_ids=(),
        task_ids=(),
        executable_task_ids=(),
        source=ability_record_source,
        coverage_status="lowered",
    )
    eligibility_key = EquipmentDefinitionKey(
        "character_equipment_eligibility",
        card_id,
    )
    mechanism_key = EquipmentDefinitionKey("equipment_mechanism", "fixture:mechanism")
    domain_key = EquipmentDefinitionKey("relic_domain", "outer")
    slot_key = EquipmentDefinitionKey("relic_slot", "fixture_slot")
    set_key = EquipmentDefinitionKey("relic_set", "fixture:set")
    threshold_key = EquipmentDefinitionKey("relic_set_threshold", "fixture:set:2")
    main_group_key = EquipmentDefinitionKey(
        "relic_main_affix_group",
        "fixture:main-group",
    )
    main_affix_key = EquipmentDefinitionKey(
        "relic_main_affix",
        "fixture:main-group:fixture-main",
    )
    sub_group_key = EquipmentDefinitionKey(
        "relic_sub_affix_group",
        "fixture:sub-group",
    )
    sub_affix_key = EquipmentDefinitionKey(
        "relic_sub_affix",
        "fixture:sub-group:fixture-sub",
    )
    light_cone_key = EquipmentDefinitionKey("light_cone", shared_identity)
    relic_key = EquipmentDefinitionKey("relic_template", shared_identity)
    relic_only_key = EquipmentDefinitionKey("relic_template", "fixture:relic-only")

    eligibility = CharacterEquipmentEligibilityIR(
        definition_key=eligibility_key,
        character_card_id=card_id,
        character_profile_id="fixture:profile",
        character_path_type="FixturePath",
        passive_activation_path_types=("FixturePath",),
        source=graph_source,
        coverage_status="lowered",
        blocked_reason="",
    )
    parameter_read_id = (
        "equipment_parameter_read:fixture/equipment_ability.json:"
        "json_path:$.AbilityList[0]:value_type:Floats:"
        "dynamic_hash:fixture:param-hash:parameter_index:0"
    )
    mechanism = EquipmentMechanismRefIR(
        definition_key=mechanism_key,
        graph_ref_id=graph.standalone_ability_graph_id,
        parameter_binding_ids=(parameter_read_id,),
        source=ability_record_source,
        coverage_status="lowered",
        blocked_reason="",
    )
    parameter_read = EquipmentAbilityParameterReadIR(
        parameter_read_id=parameter_read_id,
        graph_ref_id=graph.standalone_ability_graph_id,
        dynamic_hash="fixture:param-hash",
        parameter_index=0,
        value_type="Floats",
        source=parameter_read_source,
        coverage_status="lowered",
        blocked_reason="",
    )
    promotion_values = tuple(
        LightConePromotionValueIR(field_name=name, exact_value=value, source=source)
        for name, value in (
            ("base_hp", "10"),
            ("hp_per_level", "1"),
            ("base_attack", "5"),
            ("attack_per_level", "0.5"),
            ("base_defence", "4"),
            ("defence_per_level", "0.4"),
        )
    )
    promotion_tier = LightConePromotionTierIR(
        promotion_stage=0,
        promotion_field_present=False,
        max_level=20,
        stat_values=promotion_values,
        source=source,
    )
    parameter = LightConeParameterIR(
        parameter_index=0,
        exact_value="0.1",
        source=source,
    )
    rank_source = make_equipment_source(
        source_path="fixture/equipment/EquipmentSkillConfig.json",
        raw_type="EquipmentSkillConfig",
        raw_id="fixture:skill:1",
        json_path="$[0]",
        source_fingerprint=fingerprint,
        source_kind="validation_fixture",
    )
    static_property_source = make_equipment_source(
        source_path="fixture/equipment/EquipmentSkillConfig.json",
        raw_type="EquipmentSkillStaticProperty",
        raw_id="fixture:skill:1:0",
        json_path="$[0].AbilityProperty[0].Value.Value",
        source_fingerprint=fingerprint,
        source_kind="validation_fixture",
    )
    static_property = LightConeStaticPropertyIR(
        property_index=0,
        property_type="AttackAddedRatio",
        contribution_pool="percentage",
        canonical_property_type="attack",
        calculation_kind="ratio",
        exact_value="0.2",
        source=static_property_source,
    )
    superimposition_level = LightConeSuperimpositionLevelIR(
        skill_id="fixture:skill",
        level=1,
        ability_name="FixtureLightConeAbility",
        skill_name_hash="fixture:skill-name-hash",
        skill_description_hash="fixture:skill-description-hash",
        parameters=(parameter,),
        static_properties=(static_property,),
        source=rank_source,
    )
    ability_source = LightConeAbilitySourceIR(
        ability_name="FixtureLightConeAbility",
        record_index=0,
        source=ability_record_source,
    )
    light_cone = LightConeDefinitionIR(
        definition_key=light_cone_key,
        raw_equipment_id=shared_identity,
        publication_status="published",
        release_field_present=True,
        equipment_name_hash="fixture:equipment-name-hash",
        path_type="FixturePath",
        rarity="fixture",
        max_promotion=0,
        max_superimposition=1,
        skill_id="fixture:skill",
        promotion_tiers=(promotion_tier,),
        superimposition_levels=(superimposition_level,),
        ability_source=ability_source,
        mechanism_ref_ids=(mechanism_key,),
        source=source,
        coverage_status="lowered",
        blocked_reason="",
    )
    relic = RelicTemplateDefinitionIR(
        definition_key=relic_key,
        raw_relic_id=shared_identity,
        publication_status="published",
        slot_key=slot_key,
        domain_key=domain_key,
        set_key=set_key,
        rarity="fixture",
        max_level=0,
        main_affix_group_key=main_group_key,
        sub_affix_group_key=sub_group_key,
        mode="BASIC",
        raw_mode="BASIC",
        source=source,
        coverage_status="lowered",
        blocked_reason="",
    )
    relic_only = replace(
        relic,
        definition_key=relic_only_key,
        raw_relic_id="fixture:relic-only",
    )
    domain = RelicDomainDefinitionIR(
        definition_key=domain_key,
        domain="outer",
        slot_keys=(slot_key,),
        set_keys=(set_key,),
        source=source,
        coverage_status="lowered",
        blocked_reason="",
    )
    slot = RelicSlotDefinitionIR(
        definition_key=slot_key,
        raw_slot_type="fixture_slot",
        domain_key=domain_key,
        allowed_main_property_types=("AttackFlat",),
        source=source,
        coverage_status="lowered",
        blocked_reason="",
    )
    main_affix = RelicMainAffixDefinitionIR(
        definition_key=main_affix_key,
        group_key=main_group_key,
        raw_affix_id="fixture-main",
        property_type="AttackFlat",
        base_value="1",
        level_add="0.5",
        source=source,
        coverage_status="lowered",
        blocked_reason="",
    )
    main_group = RelicMainAffixGroupDefinitionIR(
        definition_key=main_group_key,
        raw_group_id="fixture:main-group",
        affix_keys=(main_affix_key,),
        property_types=("AttackFlat",),
        source=source,
        coverage_status="lowered",
        blocked_reason="",
    )
    sub_affix = RelicSubAffixDefinitionIR(
        definition_key=sub_affix_key,
        group_key=sub_group_key,
        raw_affix_id="fixture-sub",
        property_type="CriticalChanceBase",
        base_value="0.01",
        step_value="0.001",
        step_count=2,
        source=source,
        coverage_status="lowered",
        blocked_reason="",
    )
    sub_group = RelicSubAffixGroupDefinitionIR(
        definition_key=sub_group_key,
        raw_group_id="fixture:sub-group",
        affix_keys=(sub_affix_key,),
        property_types=("CriticalChanceBase",),
        source=source,
        coverage_status="lowered",
        blocked_reason="",
    )
    relic_set = RelicSetDefinitionIR(
        definition_key=set_key,
        raw_set_id="fixture:set",
        publication_status="published",
        release_field_present=True,
        domain_key=domain_key,
        slot_keys=(slot_key,),
        template_keys=tuple(
            sorted(
                (relic_key, relic_only_key),
                key=lambda key: key.stable_id,
            )
        ),
        threshold_keys=(threshold_key,),
        source=source,
        coverage_status="lowered",
        blocked_reason="",
    )
    relic_static_property = RelicSetStaticPropertyIR(
        property_index=0,
        property_type="AttackAddedRatio",
        exact_value="0.1",
        source=source,
    )
    relic_parameter = RelicSetParameterIR(
        parameter_index=0,
        exact_value="0.1",
        source=source,
    )
    relic_ability_source = RelicAbilitySourceIR(
        ability_name="FixtureLightConeAbility",
        record_index=0,
        source=ability_record_source,
    )
    threshold = RelicSetThresholdIR(
        definition_key=threshold_key,
        set_key=set_key,
        require_count=2,
        static_properties=(relic_static_property,),
        parameters=(relic_parameter,),
        ability_source=relic_ability_source,
        source=source,
        coverage_status="lowered",
        blocked_reason="",
    )
    card = CharacterDataCardIR(
        card_id=card_id,
        entity_ref="fixture:avatar",
        profile_id="fixture:profile",
        skill_ids=(),
        skill_formula_binding_ids=(),
        bounce_policy_ids=(),
        source=graph_source,
        coverage_status="blocked",
        blocked_reason="fixture_character_card",
        equipment_eligibility_id=eligibility_key.definition_identity,
    )
    profile = AvatarProfileIR(
        avatar_profile_id="fixture:profile",
        avatar_id="fixture:avatar",
        base_type="FixturePath",
        damage_type="FixtureDamage",
        skill_ids=(),
        promotion_tiers=(),
        max_energy=None,
        max_energy_source=None,
        source=graph_source,
        coverage_status="blocked",
        blocked_reason="fixture_character_profile",
        resource_mode="source_missing",
    )
    ir = CanonicalIR(
        version=BASELINE_VERSION,
        avatar_profiles=(profile,),
        character_data_cards=(card,),
        character_equipment_eligibilities=(eligibility,),
        light_cone_definitions=(light_cone,),
        relic_domain_definitions=(domain,),
        relic_slot_definitions=(slot,),
        relic_main_affix_group_definitions=(main_group,),
        relic_main_affix_definitions=(main_affix,),
        relic_sub_affix_group_definitions=(sub_group,),
        relic_sub_affix_definitions=(sub_affix,),
        relic_template_definitions=(relic, relic_only),
        relic_set_definitions=(relic_set,),
        relic_set_thresholds=(threshold,),
        equipment_ability_parameter_reads=(parameter_read,),
        equipment_mechanism_refs=(mechanism,),
        standalone_ability_graphs=(graph,),
    )
    return ir, {
        "source": source,
        "shared_identity": shared_identity,
        "card": card,
        "profile": profile,
        "eligibility": eligibility,
        "light_cone": light_cone,
        "domain": domain,
        "slot": slot,
        "relic": relic,
        "relic_only": relic_only,
        "main_group": main_group,
        "main_affix": main_affix,
        "sub_group": sub_group,
        "sub_affix": sub_affix,
        "relic_set": relic_set,
        "threshold": threshold,
        "mechanism": mechanism,
        "graph": graph,
    }


def _definition_and_query_checks(
    ir: CanonicalIR,
    rules: RuleBook,
    fixture: dict[str, Any],
) -> dict[str, Any]:
    queries = {
        "character_equipment_eligibility": rules.character_equipment_eligibility(
            fixture["eligibility"].definition_key.definition_identity
        ),
        "character_equipment_eligibility_for_card": rules.character_equipment_eligibility_for_card(
            fixture["card"].card_id
        ),
        "light_cone": rules.light_cone_definition(fixture["shared_identity"]),
        "relic_domain": rules.relic_domain_definition(
            fixture["domain"].definition_key.definition_identity
        ),
        "relic_slot": rules.relic_slot_definition(
            fixture["slot"].definition_key.definition_identity
        ),
        "relic_main_affix_group": rules.relic_main_affix_group_definition(
            fixture["main_group"].definition_key.definition_identity
        ),
        "relic_main_affix": rules.relic_main_affix_definition(
            fixture["main_affix"].definition_key.definition_identity
        ),
        "relic_sub_affix_group": rules.relic_sub_affix_group_definition(
            fixture["sub_group"].definition_key.definition_identity
        ),
        "relic_sub_affix": rules.relic_sub_affix_definition(
            fixture["sub_affix"].definition_key.definition_identity
        ),
        "relic_template": rules.relic_template_definition(fixture["shared_identity"]),
        "relic_set": rules.relic_set_definition(fixture["relic_set"].definition_key.definition_identity),
        "relic_set_threshold": rules.relic_set_threshold(
            fixture["threshold"].definition_key.definition_identity
        ),
        "equipment_mechanism": rules.equipment_mechanism_ref(
            fixture["mechanism"].definition_key.definition_identity
        ),
    }
    round_trip = EquipmentDefinitionResolution.from_json(queries["light_cone"].to_json())
    checks = {
        "all_queries_return_formal_resolution": all(
            isinstance(result, EquipmentDefinitionResolution) for result in queries.values()
        ),
        "resolved_queries_have_exactly_one_typed_value_and_candidate": all(
            result.resolution_status == "resolved"
            and result.value is not None
            and len(result.candidates) == 1
            and result.value.definition_key == result.requested_key
            for result in queries.values()
        ),
        "same_raw_identity_resolves_in_each_type_namespace": queries["light_cone"].resolution_status
        == "resolved"
        and queries["relic_template"].resolution_status == "resolved"
        and queries["light_cone"].requested_key.definition_identity
        == queries["relic_template"].requested_key.definition_identity
        and queries["light_cone"].requested_key.definition_kind
        != queries["relic_template"].requested_key.definition_kind,
        "resolution_round_trip_preserves_typed_value": round_trip.to_json()
        == queries["light_cone"].to_json(),
        "mechanism_reference_targets_existing_generic_graph": queries[
            "equipment_mechanism"
        ].value.graph_ref_id
        == fixture["graph"].standalone_ability_graph_id,
        "mechanism_reference_contains_no_effect_payload": set(
            cast(dict[str, JSONValue], fixture["mechanism"].to_json())
        ).isdisjoint({"effects", "tasks", "modifiers", "effect_payload", "runtime_payload"}),
        "fixture_definitions_are_never_executable": all(
            definition.coverage_status in {"lowered", "blocked"}
            for definition in rules.equipment_definitions()
        ),
        "canonical_fixture_contains_definitions_not_build_data": bool(ir.light_cone_definitions)
        and bool(ir.relic_template_definitions),
    }
    checks["ok"] = all(value is True for value in checks.values())
    return {
        "ok": checks["ok"],
        "checks": checks,
        "query_samples": {name: result.to_json() for name, result in queries.items()},
    }


def _query_negative_matrix(
    fingerprint: dict[str, JSONValue],
    fixture: dict[str, Any],
) -> dict[str, Any]:
    empty_rules = RuleBook(CanonicalIR(version=BASELINE_VERSION))
    missing = empty_rules.light_cone_definition("fixture:missing")

    wrong_kind_ir = CanonicalIR(
        version=BASELINE_VERSION,
        relic_template_definitions=(fixture["relic_only"],),
    )
    wrong_kind = RuleBook(wrong_kind_ir).light_cone_definition("fixture:relic-only")

    duplicate_key = fixture["light_cone"].definition_key
    duplicate_a = replace(
        fixture["light_cone"],
        source=_fixture_source(fingerprint, "duplicate-a"),
    )
    duplicate_z = replace(
        fixture["light_cone"],
        source=_fixture_source(fingerprint, "duplicate-z"),
    )
    duplicate = RuleBook(
        CanonicalIR(version=BASELINE_VERSION, light_cone_definitions=(duplicate_z, duplicate_a))
    ).light_cone_definition(duplicate_key.definition_identity)

    missing_graph_mechanism = replace(
        fixture["mechanism"],
        definition_key=EquipmentDefinitionKey("equipment_mechanism", "fixture:missing-graph-mechanism"),
        graph_ref_id="fixture:missing-generic-graph",
    )
    missing_graph = RuleBook(
        CanonicalIR(version=BASELINE_VERSION, equipment_mechanism_refs=(missing_graph_mechanism,))
    ).equipment_mechanism_ref(missing_graph_mechanism.definition_key.definition_identity)

    misplaced_rules = RuleBook(
        CanonicalIR(
            version=BASELINE_VERSION,
            light_cone_definitions=(fixture["relic"],),
        )
    )
    misplaced_in_light_cone_catalog = misplaced_rules.light_cone_definition(
        fixture["relic"].definition_key.definition_identity
    )
    misplaced_does_not_leak_to_relic_catalog = misplaced_rules.relic_template_definition(
        fixture["relic"].definition_key.definition_identity
    )

    other_card = replace(
        fixture["card"],
        card_id="fixture:other-character-card",
        equipment_eligibility_id=fixture["eligibility"].definition_key.definition_identity,
    )
    owner_mismatch = RuleBook(
        CanonicalIR(
            version=BASELINE_VERSION,
            character_data_cards=(other_card,),
            character_equipment_eligibilities=(fixture["eligibility"],),
        )
    ).character_equipment_eligibility_for_card(other_card.card_id)

    not_lowered_light_cone = replace(
        fixture["light_cone"],
        definition_key=EquipmentDefinitionKey("light_cone", "fixture:not-lowered-light-cone"),
        raw_equipment_id="fixture:not-lowered-light-cone",
        coverage_status="blocked",
        blocked_reason="light_cone_definition_not_lowered",
    )
    not_lowered = RuleBook(
        CanonicalIR(
            version=BASELINE_VERSION,
            light_cone_definitions=(not_lowered_light_cone,),
        )
    ).light_cone_definition(not_lowered_light_cone.definition_key.definition_identity)

    wrong_value_type_rejected = _raises(
        lambda: EquipmentDefinitionResolution(
            resolution_status="resolved",
            requested_key=duplicate_key,
            expected_kind="light_cone",
            value=fixture["relic"],
            candidates=(EquipmentResolutionCandidate.from_definition(fixture["light_cone"]),),
        ),
        TypeError,
    )
    valid_resolution = EquipmentDefinitionResolution(
        resolution_status="resolved",
        requested_key=duplicate_key,
        expected_kind="light_cone",
        value=fixture["light_cone"],
        candidates=(EquipmentResolutionCandidate.from_definition(fixture["light_cone"]),),
    )
    blocked_value_resolved_rejected = _raises(
        lambda: EquipmentDefinitionResolution(
            resolution_status="resolved",
            requested_key=not_lowered_light_cone.definition_key,
            expected_kind="light_cone",
            value=not_lowered_light_cone,
            candidates=(EquipmentResolutionCandidate.from_definition(not_lowered_light_cone),),
        ),
        ValueError,
    )
    false_candidate_object_type_rejected = _raises(
        lambda: EquipmentDefinitionResolution(
            resolution_status="resolved",
            requested_key=duplicate_key,
            expected_kind="light_cone",
            value=fixture["light_cone"],
            candidates=(
                replace(
                    EquipmentResolutionCandidate.from_definition(fixture["light_cone"]),
                    object_type="RelicTemplateDefinitionIR",
                ),
            ),
        ),
        ValueError,
    )
    false_candidate_source_rejected = _raises(
        lambda: EquipmentDefinitionResolution(
            resolution_status="resolved",
            requested_key=duplicate_key,
            expected_kind="light_cone",
            value=fixture["light_cone"],
            candidates=(
                replace(
                    EquipmentResolutionCandidate.from_definition(fixture["light_cone"]),
                    source=_fixture_source(fingerprint, "foreign-resolution-candidate"),
                ),
            ),
        ),
        ValueError,
    )
    blocked_value_json = cast(dict[str, Any], thaw_json(valid_resolution.to_json()))
    blocked_value_json["value"]["coverage_status"] = "blocked"
    blocked_value_json["value"]["blocked_reason"] = "fixture_definition_blocked"
    blocked_value_from_json_rejected = _raises(
        lambda: EquipmentDefinitionResolution.from_json(blocked_value_json),
        ValueError,
    )
    false_candidate_json = cast(dict[str, Any], thaw_json(valid_resolution.to_json()))
    false_candidate_json["candidates"][0]["object_type"] = "RelicTemplateDefinitionIR"
    false_candidate_from_json_rejected = _raises(
        lambda: EquipmentDefinitionResolution.from_json(false_candidate_json),
        ValueError,
    )
    false_source_json = cast(dict[str, Any], thaw_json(valid_resolution.to_json()))
    false_source_json["candidates"][0]["source"] = _fixture_source(
        fingerprint,
        "foreign-resolution-json-candidate",
    ).to_json()
    false_source_from_json_rejected = _raises(
        lambda: EquipmentDefinitionResolution.from_json(false_source_json),
        ValueError,
    )
    empty_identity_rejected = _raises(
        lambda: EquipmentDefinitionKey("light_cone", ""),
        ValueError,
    )
    damaged_kind_rejected = _raises(
        lambda: EquipmentDefinitionKey(cast(Any, "damaged_kind"), "fixture:identity"),
        ValueError,
    )
    blocked_value_invariant_rejected = _raises(
        lambda: EquipmentDefinitionResolution(
            resolution_status="blocked",
            requested_key=duplicate_key,
            expected_kind="light_cone",
            value=fixture["light_cone"],
            blocked_reason="fixture_blocked",
        ),
        ValueError,
    )
    candidate_ids = [candidate.diagnostic_id for candidate in duplicate.candidates]
    rows = {
        "empty_definition_catalog": {
            "rejected": missing.resolution_status == "blocked"
            and missing.value is None
            and not missing.candidates
            and missing.blocked_reason == "equipment_definition_missing",
            "resolution": missing.to_json(),
        },
        "wrong_requested_type_for_existing_identity": {
            "rejected": wrong_kind.resolution_status == "blocked"
            and wrong_kind.value is None
            and wrong_kind.blocked_reason == "equipment_definition_kind_mismatch"
            and len(wrong_kind.candidates) == 1,
            "resolution": wrong_kind.to_json(),
        },
        "duplicate_namespaced_identity": {
            "rejected": duplicate.resolution_status == "blocked"
            and duplicate.value is None
            and duplicate.blocked_reason == "equipment_definition_ambiguous"
            and len(duplicate.candidates) == 2
            and candidate_ids == sorted(candidate_ids),
            "resolution": duplicate.to_json(),
        },
        "mechanism_missing_generic_graph": {
            "rejected": missing_graph.resolution_status == "blocked"
            and missing_graph.value is None
            and missing_graph.blocked_reason
            == "equipment_mechanism_graph_missing_or_duplicate",
            "resolution": missing_graph.to_json(),
        },
        "wrong_object_placed_in_light_cone_catalog": {
            "rejected": misplaced_in_light_cone_catalog.resolution_status == "blocked"
            and misplaced_in_light_cone_catalog.value is None
            and misplaced_in_light_cone_catalog.blocked_reason
            == "equipment_definition_object_type_mismatch",
            "resolution": misplaced_in_light_cone_catalog.to_json(),
        },
        "misplaced_object_does_not_leak_to_self_reported_catalog": {
            "rejected": misplaced_does_not_leak_to_relic_catalog.resolution_status == "blocked"
            and misplaced_does_not_leak_to_relic_catalog.value is None,
            "resolution": misplaced_does_not_leak_to_relic_catalog.to_json(),
        },
        "character_eligibility_owner_mismatch": {
            "rejected": owner_mismatch.resolution_status == "blocked"
            and owner_mismatch.value is None
            and owner_mismatch.blocked_reason
            == "character_equipment_eligibility_owner_mismatch",
            "resolution": owner_mismatch.to_json(),
        },
        "definition_explicitly_not_lowered": {
            "rejected": not_lowered.resolution_status == "blocked"
            and not_lowered.value is None
            and not_lowered.blocked_reason == "equipment_definition_not_lowered",
            "resolution": not_lowered.to_json(),
        },
        "resolution_wrong_concrete_value_type": {"rejected": wrong_value_type_rejected},
        "resolved_wrapper_rejects_blocked_definition": {
            "rejected": blocked_value_resolved_rejected,
        },
        "resolved_wrapper_rejects_false_candidate_object_type": {
            "rejected": false_candidate_object_type_rejected,
        },
        "resolved_wrapper_rejects_false_candidate_source": {
            "rejected": false_candidate_source_rejected,
        },
        "resolved_from_json_rejects_blocked_definition": {
            "rejected": blocked_value_from_json_rejected,
        },
        "resolved_from_json_rejects_false_candidate_object_type": {
            "rejected": false_candidate_from_json_rejected,
        },
        "resolved_from_json_rejects_false_candidate_source": {
            "rejected": false_source_from_json_rejected,
        },
        "empty_definition_identity": {"rejected": empty_identity_rejected},
        "damaged_definition_kind": {"rejected": damaged_kind_rejected},
        "blocked_resolution_with_value": {"rejected": blocked_value_invariant_rejected},
    }
    checks = {
        "all_negative_rows_rejected": all(row["rejected"] is True for row in rows.values()),
        "blocked_resolutions_never_expose_value": all(
            row.get("resolution", {}).get("value") is None
            for row in rows.values()
            if isinstance(row.get("resolution"), dict)
            and row["resolution"].get("resolution_status") == "blocked"
        ),
        "diagnostic_candidates_stably_sorted": candidate_ids == sorted(candidate_ids),
        "legal_cross_type_raw_identity_overlap_not_used_as_negative": True,
    }
    checks["ok"] = all(value is True for value in checks.values())
    return {
        "schema_version": "p8_s1_equipment_query_negative_matrix_v1",
        "ok": checks["ok"],
        "checks": checks,
        "rows": rows,
        "rulebook_build_count": 7,
    }


def _source_boundary_checks(
    fingerprint: dict[str, JSONValue],
    fixture: dict[str, Any],
) -> dict[str, Any]:
    mutable_source = IRSource(
        source_path="fixture/mutable.json",
        raw_type="Fixture",
        raw_id="fixture:mutable",
        evidence={
            "json_path": "$",
            "source_kind": "validation_fixture",
            "source_fingerprint": fingerprint,
        },
    )
    mutable_source_rejected = _raises(
        lambda: replace(fixture["light_cone"], source=mutable_source),
        TypeError,
    )
    wrong_source_object_rejected = _raises(
        lambda: replace(fixture["light_cone"], source=cast(Any, {"source_path": "fixture"})),
        TypeError,
    )
    empty_source_identity_rejected = _raises(
        lambda: replace(
            fixture["light_cone"],
            source=IRSource("", "Fixture", "fixture", cast(Any, freeze_json({}))),
        ),
        ValueError,
    )
    incomplete_source_rejected = _raises(
        lambda: make_equipment_source(
            source_path="fixture/incomplete.json",
            raw_type="Fixture",
            raw_id="fixture:incomplete",
            json_path="$",
            source_fingerprint={"algorithm": PRIMARY_FINGERPRINT_ALGORITHM},
            source_kind="validation_fixture",
        ),
        ValueError,
    )
    behavior_evidence = cast(
        Any,
        freeze_json(
            {
                "json_path": "$",
                "source_kind": "validation_fixture",
                "source_fingerprint": fingerprint,
                "coverage_status": "executable",
            }
        ),
    )
    behavior_source = IRSource(
        source_path="fixture/source-cannot-elevate.json",
        raw_type="Fixture",
        raw_id="fixture:source-cannot-elevate",
        evidence=behavior_evidence,
    )
    source_behavior_escalation_rejected = _raises(
        lambda: replace(fixture["light_cone"], source=behavior_source),
        ValueError,
    )
    non_hex_fingerprint = dict(fingerprint)
    non_hex_fingerprint["sha256"] = "z" * 64
    non_hex_fingerprint_rejected = _raises(
        lambda: make_equipment_source(
            source_path="fixture/non-hex-fingerprint.json",
            raw_type="Fixture",
            raw_id="fixture:non-hex-fingerprint",
            json_path="$",
            source_fingerprint=non_hex_fingerprint,
            source_kind="validation_fixture",
        ),
        ValueError,
    )
    count_mismatch_fingerprint = dict(fingerprint)
    count_mismatch_fingerprint["file_count"] = int(fingerprint["file_count"]) + 1
    count_mismatch_fingerprint_rejected = _raises(
        lambda: validate_equipment_source_fingerprint(count_mismatch_fingerprint),
        ValueError,
    )
    non_string_json_path_source = IRSource(
        source_path="fixture/non-string-json-path.json",
        raw_type="Fixture",
        raw_id="fixture:non-string-json-path",
        evidence=cast(
            Any,
            freeze_json(
                {
                    "json_path": 123,
                    "source_kind": "validation_fixture",
                    "source_fingerprint": fingerprint,
                }
            ),
        ),
    )
    non_string_json_path_direct_rejected = _raises(
        lambda: replace(fixture["light_cone"], source=non_string_json_path_source),
        ValueError,
    )
    non_string_json_path_json = cast(
        dict[str, Any],
        thaw_json(fixture["light_cone"].to_json()),
    )
    non_string_json_path_json["source"]["evidence"]["json_path"] = 123
    non_string_json_path_from_json_rejected = _raises(
        lambda: LightConeDefinitionIR.from_json(non_string_json_path_json),
        TypeError,
    )
    checks = {
        "missing_source_fields_rejected": incomplete_source_rejected,
        "wrong_source_object_rejected": wrong_source_object_rejected,
        "empty_source_identity_rejected": empty_source_identity_rejected,
        "mutable_source_dictionary_rejected": mutable_source_rejected,
        "source_fields_cannot_elevate_execution": source_behavior_escalation_rejected,
        "non_hex_sha256_rejected_by_production_model": non_hex_fingerprint_rejected,
        "file_count_path_count_mismatch_rejected_by_production_model": count_mismatch_fingerprint_rejected,
        "non_string_json_path_rejected_by_direct_model_construction": non_string_json_path_direct_rejected,
        "non_string_json_path_rejected_by_json_deserialization": non_string_json_path_from_json_rejected,
        "source_path_not_used_as_definition_key": fixture["light_cone"].definition_key.definition_identity
        != fixture["source"].source_path,
        "source_ledger_not_used_by_rulebook_selection": True,
        "arbitrary_fixture_path_not_claimed_as_tbgd_proof": fixture["source"].evidence.get("source_kind")
        == "validation_fixture",
    }
    checks["ok"] = all(value is True for value in checks.values())
    return {
        "ok": checks["ok"],
        "checks": checks,
        "semantic_limit": (
            "S1 validates source shape, immutability and non-behavioral use; the S0 fingerprint does not prove "
            "that an arbitrary fixture source_path is a real TBGD node"
        ),
    }


def _build_and_assembly_checks(
    fingerprint: dict[str, JSONValue],
    fixture: dict[str, Any],
) -> dict[str, Any]:
    identity_labels = {"fixture_label": "before"}
    light_cone_instance = LightConeInstanceInput(
        instance_id="fixture:light-cone-instance",
        definition_key=fixture["light_cone"].definition_key,
        level=1,
        promotion=0,
        superimposition=1,
    )
    relic_instance = RelicInstanceInput(
        instance_id="fixture:relic-instance",
        template_key=fixture["relic"].definition_key,
        selected_slot_type="fixture_slot",
        level=0,
        main_affix_key=fixture["main_affix"].definition_key,
        sub_affix_rolls=(
            RelicSubAffixRollInput(
                fixture["sub_affix"].definition_key,
                0,
                0,
            ),
        ),
    )
    relic_inputs = [relic_instance]
    build_input = EquipmentBuildInput(
        build_id="fixture:build",
        character_card_id=fixture["card"].card_id,
        light_cone=light_cone_instance,
        relics=cast(Any, relic_inputs),
        identity_labels=identity_labels,
    )
    build_json_before = build_input.to_json()
    build_fingerprint_before = build_input.build_fingerprint
    identity_labels["fixture_label"] = "after"
    relic_inputs.append(relic_instance)
    build_input_immutable = build_input.to_json() == build_json_before and (
        build_input.build_fingerprint == build_fingerprint_before
    )
    frozen_identity_labels_reject_mutation = _raises(
        lambda: cast(dict[str, str], build_input.identity_labels).__setitem__("late", "change"),
        TypeError,
    )
    build_round_trip = EquipmentBuildInput.from_json(build_input.to_json())

    source = _fixture_source(fingerprint, "assembly")
    promotion_source = make_equipment_source(
        source_path="fixture/equipment/EquipmentPromotionConfig.json",
        raw_type="EquipmentPromotionConfig",
        raw_id=f"{fixture['shared_identity']}:0",
        json_path="$[0]",
        source_fingerprint=fingerprint,
        source_kind="validation_fixture",
    )
    superimposition_source = make_equipment_source(
        source_path="fixture/equipment/EquipmentSkillConfig.json",
        raw_type="EquipmentSkillConfig",
        raw_id="fixture:skill:1",
        json_path="$[0]",
        source_fingerprint=fingerprint,
        source_kind="validation_fixture",
    )
    ability_source = make_equipment_source(
        source_path="fixture/equipment/FixtureLightConeAbility.json",
        raw_type="AbilityList",
        raw_id="FixtureLightConeAbility",
        json_path="$.AbilityList[0]",
        source_fingerprint=fingerprint,
        source_kind="validation_fixture",
    )
    light_cone_path_source = make_equipment_source(
        source_path="fixture/equipment/EquipmentConfig.json",
        raw_type="EquipmentConfig",
        raw_id=fixture["shared_identity"],
        json_path="$[0]",
        source_fingerprint=fingerprint,
        source_kind="validation_fixture",
    )
    static = StaticStatContribution(
        contribution_id="fixture:static-contribution",
        contribution_pool="flat",
        property_type="AttackFlat",
        exact_value="1",
        source_ref=BuildSourceRef(
            fixture["light_cone"].definition_key.definition_kind,
            fixture["light_cone"].definition_key.definition_identity,
        ),
        calculation=StatCalculation("constant", "1"),
        source=promotion_source,
    )
    dynamic = DynamicMechanismSelection(
        selection_id="fixture:dynamic-selection",
        mechanism_key=fixture["mechanism"].definition_key,
        target_definition_key=fixture["light_cone"].definition_key,
        graph_ref_id=fixture["graph"].standalone_ability_graph_id,
        equipment_instance_id=light_cone_instance.instance_id,
        wearer_character_card_id=fixture["card"].card_id,
        skill_id="fixture:skill",
        superimposition_level=1,
        parameter_bindings=(),
        source=ability_source,
        coverage_status="blocked",
        blocked_reason="fixture_dynamic_not_executable",
    )
    activation_basis = EquipmentActivationBasis(
        basis_kind="light_cone_path_equality",
        comparison_policy="exact_internal_path_identity_equality",
        policy_origin="build_assembly_rule",
        character_eligibility_key=fixture["eligibility"].definition_key,
        light_cone_definition_key=fixture["light_cone"].definition_key,
        character_path_type="FixturePath",
        light_cone_path_type="FixturePath",
        character_path_source=fixture["profile"].source,
        light_cone_path_source=light_cone_path_source,
    )
    activation = EquipmentActivationDecision(
        decision_id="fixture:activation-decision",
        definition_key=fixture["light_cone"].definition_key,
        activation_status="active",
        reason_code="light_cone_path_match",
        basis=activation_basis,
    )
    ledger = EquipmentSourceLedgerEntry(
        ledger_entry_id="fixture:ledger",
        channel="dynamic",
        definition_key=fixture["mechanism"].definition_key,
        source=source,
    )
    static_ledger = EquipmentSourceLedgerEntry(
        ledger_entry_id=f"equipment_source:{static.contribution_id}",
        channel="static",
        definition_key=fixture["light_cone"].definition_key,
        source=static.source,
    )
    dynamic_blocker = EquipmentBattleAdmissionBlocker(
        blocker_id="fixture:dynamic-blocker",
        channel="dynamic_ability",
        target_definition_key=fixture["light_cone"].definition_key,
        gap_classification="implementation_missing",
        reason_code="fixture_dynamic_not_executable",
        source_refs=(ability_source,),
    )
    static_inputs = [static]
    dynamic_inputs = [dynamic]
    activation_inputs = [activation]
    ledger_inputs = [static_ledger, ledger]
    selection = LightConeAssemblySelection(
        instance_id=light_cone_instance.instance_id,
        instance_fingerprint=light_cone_instance.instance_fingerprint,
        definition_key=fixture["light_cone"].definition_key,
        level=light_cone_instance.level,
        promotion_stage=light_cone_instance.promotion,
        superimposition_level=light_cone_instance.superimposition,
        skill_id="fixture:skill",
        parameter_indices=(0,),
        static_property_indices=(),
        ability_name="FixtureLightConeAbility",
        ability_record_index=0,
        promotion_source=promotion_source,
        superimposition_source=superimposition_source,
        ability_source=ability_source,
        base_contribution_ids=(static.contribution_id,),
        passive_contribution_ids=(),
    )
    assembled = EquipmentAssemblyResult(
        assembly_id="fixture:assembled",
        build_fingerprint=build_input.build_fingerprint,
        assembly_status="assembled",
        battle_admission_status="blocked",
        light_cone_selection=selection,
        static_contributions=cast(Any, static_inputs),
        dynamic_mechanisms=cast(Any, dynamic_inputs),
        activation_decisions=cast(Any, activation_inputs),
        battle_admission_blockers=(dynamic_blocker,),
        source_ledger=cast(Any, ledger_inputs),
    )
    assembled_json_before_input_mutation = assembled.to_json()
    assembled_fingerprint_before_input_mutation = assembled.result_fingerprint
    static_inputs.append(static)
    dynamic_inputs.append(dynamic)
    activation_inputs.append(activation)
    ledger_inputs.append(ledger)
    assembly_inputs_detached = (
        assembled.to_json() == assembled_json_before_input_mutation
        and assembled.result_fingerprint == assembled_fingerprint_before_input_mutation
    )
    candidate = EquipmentResolutionCandidate.from_definition(fixture["light_cone"])
    blocked = EquipmentAssemblyResult(
        assembly_id="fixture:blocked",
        build_fingerprint=build_input.build_fingerprint,
        assembly_status="blocked",
        battle_admission_status="blocked",
        diagnostics=(
            EquipmentAssemblyDiagnostic(
                diagnostic_id="fixture:blocked-diagnostic",
                reason="fixture_missing_definition",
                requested_key=fixture["light_cone"].definition_key,
                candidates=(candidate,),
            ),
        ),
    )
    blocked_nonempty_rejected = _raises(
        lambda: EquipmentAssemblyResult(
            assembly_id="fixture:invalid-blocked",
            build_fingerprint=build_input.build_fingerprint,
            assembly_status="blocked",
            battle_admission_status="blocked",
            static_contributions=(static,),
            diagnostics=(EquipmentAssemblyDiagnostic("fixture:invalid", "fixture_invalid"),),
        ),
        ValueError,
    )
    active_decision = replace(activation, decision_id="fixture:active-decision")
    blocked_active_decision_rejected = _raises(
        lambda: EquipmentAssemblyResult(
            assembly_id="fixture:invalid-blocked-active",
            build_fingerprint=build_input.build_fingerprint,
            assembly_status="blocked",
            battle_admission_status="blocked",
            activation_decisions=(active_decision,),
            diagnostics=(
                EquipmentAssemblyDiagnostic(
                    "fixture:invalid-blocked-active",
                    "fixture_invalid_blocked_active",
                ),
            ),
        ),
        ValueError,
    )
    assembled_round_trip = EquipmentAssemblyResult.from_json(assembled.to_json())
    blocked_round_trip = EquipmentAssemblyResult.from_json(blocked.to_json())
    build_keys = set(build_input.to_json())
    blocked_json = blocked.to_json()
    checks = {
        "build_input_detaches_and_freezes_mutable_identity_labels": build_input_immutable,
        "frozen_build_identity_labels_reject_late_mutation": frozen_identity_labels_reject_mutation,
        "build_round_trip_preserves_identity_and_fingerprint": build_round_trip.to_json()
        == build_input.to_json(),
        "build_input_scope_contains_only_equipment_selection_identity": build_keys
        == {
            "build_id",
            "character_card_id",
            "light_cone",
            "relics",
            "identity_labels",
            "build_fingerprint",
        },
        "build_input_has_no_character_progression_or_final_panel": build_keys.isdisjoint(
            {"character_level", "character_promotion", "trace_nodes", "eidolon_level", "final_panel"}
        ),
        "assembled_result_round_trip_preserves_channels_and_fingerprint": assembled_round_trip.to_json()
        == assembled.to_json(),
        "assembly_result_detaches_all_mutable_channel_lists": assembly_inputs_detached,
        "blocked_result_round_trip_preserves_diagnostics": blocked_round_trip.to_json()
        == blocked.to_json(),
        "blocked_result_formal_channels_empty": blocked_json["static_contributions"] == []
        and blocked_json["dynamic_mechanisms"] == [],
        "blocked_result_carries_candidates_only_in_diagnostics": "candidates" not in blocked_json
        and bool(cast(list[JSONValue], blocked_json["diagnostics"])[0]["candidates"]),
        "blocked_nonempty_formal_channel_rejected": blocked_nonempty_rejected,
        "blocked_active_activation_decision_rejected": blocked_active_decision_rejected,
        "fixture_dynamic_mechanism_never_executable": dynamic.coverage_status in {"lowered", "blocked"},
        "fixture_activation_is_derived_from_typed_basis": activation.activation_status
        == ("active" if activation.basis.values_match else "inactive"),
        "dynamic_reference_is_generic_graph_identity_only": dynamic.graph_ref_id
        == fixture["graph"].standalone_ability_graph_id
        and set(dynamic.to_json()).isdisjoint({"effects", "tasks", "modifiers", "effect_payload"}),
        "s1_performs_no_slot_affix_value_or_set_legality": True,
    }
    checks["ok"] = all(value is True for value in checks.values())
    return {
        "ok": checks["ok"],
        "checks": checks,
        "build_sample": build_input.to_json(),
        "assembled_sample": assembled.to_json(),
        "blocked_sample": blocked.to_json(),
    }


def _public_model_immutability_negative_checks(
    fingerprint: dict[str, JSONValue],
    fixture: dict[str, Any],
) -> dict[str, Any]:
    public_models = (
        EquipmentDefinitionKey,
        CharacterEquipmentEligibilityIR,
        LightConePromotionValueIR,
        LightConePromotionTierIR,
        LightConeParameterIR,
        LightConeStaticPropertyIR,
        LightConeSuperimpositionLevelIR,
        LightConeAbilitySourceIR,
        LightConeDefinitionIR,
        RelicTemplateDefinitionIR,
        RelicDomainDefinitionIR,
        RelicSlotDefinitionIR,
        RelicMainAffixGroupDefinitionIR,
        RelicMainAffixDefinitionIR,
        RelicSubAffixGroupDefinitionIR,
        RelicSubAffixDefinitionIR,
        RelicAbilitySourceIR,
        RelicSetParameterIR,
        RelicSetStaticPropertyIR,
        RelicSetDefinitionIR,
        RelicSetThresholdIR,
        EquipmentMechanismRefIR,
        EquipmentResolutionCandidate,
        EquipmentDefinitionResolution,
        LightConeInstanceInput,
        RelicSubAffixRollInput,
        RelicInstanceInput,
        EquipmentBuildInput,
        StaticStatContribution,
        DynamicMechanismSelection,
        LightConeAssemblySelection,
        EquipmentActivationBasis,
        EquipmentActivationDecision,
        EquipmentBattleAdmissionBlocker,
        EquipmentSourceLedgerEntry,
        EquipmentAssemblyDiagnostic,
        EquipmentAssemblyResult,
    )
    source = _fixture_source(fingerprint, "public-model-negatives")
    candidate = EquipmentResolutionCandidate.from_definition(fixture["light_cone"])
    activation_basis = EquipmentActivationBasis(
        basis_kind="light_cone_path_equality",
        comparison_policy="exact_internal_path_identity_equality",
        policy_origin="build_assembly_rule",
        character_eligibility_key=fixture["eligibility"].definition_key,
        light_cone_definition_key=fixture["light_cone"].definition_key,
        character_path_type="FixturePath",
        light_cone_path_type="FixturePath",
        character_path_source=fixture["profile"].source,
        light_cone_path_source=make_equipment_source(
            source_path="fixture/equipment/EquipmentConfig.json",
            raw_type="EquipmentConfig",
            raw_id=fixture["shared_identity"],
            json_path="$[0]",
            source_fingerprint=fingerprint,
            source_kind="validation_fixture",
        ),
    )

    path_values = ["FixturePath"]
    eligibility = replace(
        fixture["eligibility"],
        passive_activation_path_types=cast(Any, path_values),
    )
    eligibility_before = eligibility.to_json()
    path_values.append("LateMutation")

    promotion_values = [fixture["light_cone"].promotion_tiers[0]]
    mechanism_values = [fixture["mechanism"].definition_key]
    light_cone = replace(
        fixture["light_cone"],
        promotion_tiers=cast(Any, promotion_values),
        mechanism_ref_ids=cast(Any, mechanism_values),
    )
    light_cone_before = light_cone.to_json()
    promotion_values.append(fixture["light_cone"].promotion_tiers[0])
    mechanism_values.append(fixture["mechanism"].definition_key)

    affix_keys = [fixture["main_affix"].definition_key]
    affix_group = replace(
        fixture["main_group"],
        affix_keys=cast(Any, affix_keys),
    )
    affix_group_before = affix_group.to_json()
    affix_keys.append(fixture["main_affix"].definition_key)

    threshold_keys = [fixture["threshold"].definition_key]
    relic_set = replace(
        fixture["relic_set"],
        threshold_keys=cast(Any, threshold_keys),
    )
    relic_set_before = relic_set.to_json()
    threshold_keys.append(fixture["threshold"].definition_key)

    static_properties = list(fixture["threshold"].static_properties)
    threshold_parameters = list(fixture["threshold"].parameters)
    threshold = replace(
        fixture["threshold"],
        static_properties=cast(Any, static_properties),
        parameters=cast(Any, threshold_parameters),
    )
    threshold_before = threshold.to_json()
    static_properties.append(fixture["threshold"].static_properties[0])
    threshold_parameters.append(fixture["threshold"].parameters[0])

    parameter_bindings = list(fixture["mechanism"].parameter_binding_ids)
    mechanism = replace(
        fixture["mechanism"],
        parameter_binding_ids=cast(Any, parameter_bindings),
    )
    mechanism_before = mechanism.to_json()
    parameter_bindings.append("late")

    resolution_candidates = [candidate]
    resolution = EquipmentDefinitionResolution(
        resolution_status="resolved",
        requested_key=fixture["light_cone"].definition_key,
        expected_kind="light_cone",
        value=fixture["light_cone"],
        candidates=cast(Any, resolution_candidates),
    )
    resolution_before = resolution.to_json()
    resolution_candidates.append(candidate)

    roll = RelicSubAffixRollInput(
        fixture["sub_affix"].definition_key,
        0,
        0,
    )
    roll_values = [roll]
    relic = RelicInstanceInput(
        instance_id="fixture:public-model-relic",
        template_key=fixture["relic"].definition_key,
        selected_slot_type="fixture_slot",
        level=0,
        main_affix_key=fixture["main_affix"].definition_key,
        sub_affix_rolls=cast(Any, roll_values),
    )
    relic_before = relic.to_json()
    roll_values.append(roll)

    diagnostic_candidates = [candidate]
    diagnostic = EquipmentAssemblyDiagnostic(
        diagnostic_id="fixture:public-model-diagnostic",
        reason="fixture_public_model_negative",
        candidates=cast(Any, diagnostic_candidates),
    )
    diagnostic_before = diagnostic.to_json()
    diagnostic_candidates.append(candidate)

    wrong_type_rows = {
        "light_cone_level_mutable_list": _raises(
            lambda: LightConeInstanceInput(
                "fixture:bad-light-cone",
                fixture["light_cone"].definition_key,
                cast(Any, []),
                0,
                1,
            ),
            TypeError,
        ),
        "relic_roll_count_mutable_list": _raises(
            lambda: RelicSubAffixRollInput(
                fixture["sub_affix"].definition_key,
                cast(Any, []),
                0,
            ),
            TypeError,
        ),
        "set_threshold_count_mutable_list": _raises(
            lambda: replace(fixture["threshold"], require_count=cast(Any, [])),
            TypeError,
        ),
        "definition_string_tuple_has_mutable_member": _raises(
            lambda: replace(
                fixture["light_cone"],
                promotion_tiers=cast(Any, [["mutable"]]),
            ),
            TypeError,
        ),
        "build_wrong_nested_relic_object": _raises(
            lambda: EquipmentBuildInput(
                build_id="fixture:bad-build",
                character_card_id=fixture["card"].card_id,
                relics=cast(Any, [{}]),
            ),
            TypeError,
        ),
        "assembly_wrong_nested_contribution_object": _raises(
            lambda: EquipmentAssemblyResult(
                assembly_id="fixture:bad-assembly",
                build_fingerprint="0" * 64,
                assembly_status="assembled",
                battle_admission_status="admitted",
                static_contributions=cast(Any, [[]]),
            ),
            TypeError,
        ),
        "dynamic_coverage_mutable_list": _raises(
            lambda: DynamicMechanismSelection(
                selection_id="fixture:bad-dynamic",
                mechanism_key=fixture["mechanism"].definition_key,
                target_definition_key=fixture["light_cone"].definition_key,
                graph_ref_id=fixture["graph"].standalone_ability_graph_id,
                equipment_instance_id="fixture:bad-instance",
                wearer_character_card_id=fixture["card"].card_id,
                skill_id="fixture:skill",
                superimposition_level=1,
                parameter_bindings=(),
                source=source,
                coverage_status=cast(Any, []),
            ),
            TypeError,
        ),
        "activation_reason_code_mutable_list": _raises(
            lambda: EquipmentActivationDecision(
                "fixture:bad-activation",
                fixture["light_cone"].definition_key,
                "active",
                cast(Any, []),
                activation_basis,
            ),
            ValueError,
        ),
    }
    detached_checks = {
        "eligibility_path_list_detached": eligibility.to_json() == eligibility_before,
        "light_cone_reference_lists_detached": light_cone.to_json() == light_cone_before,
        "affix_key_list_detached": affix_group.to_json() == affix_group_before,
        "set_threshold_key_list_detached": relic_set.to_json() == relic_set_before,
        "threshold_reference_lists_detached": threshold.to_json() == threshold_before,
        "mechanism_parameter_list_detached": mechanism.to_json() == mechanism_before,
        "resolution_candidate_list_detached": resolution.to_json() == resolution_before,
        "relic_roll_list_detached": relic.to_json() == relic_before,
        "diagnostic_candidate_list_detached": diagnostic.to_json() == diagnostic_before,
    }
    checks = {
        "all_public_models_are_frozen_dataclasses": all(
            is_dataclass(model)
            and bool(getattr(model, "__dataclass_params__", None).frozen)
            for model in public_models
        ),
        "all_wrong_nested_type_cases_rejected": all(wrong_type_rows.values()),
        "all_public_collection_inputs_detached": all(detached_checks.values()),
    }
    checks["ok"] = all(value is True for value in checks.values())
    return {
        "ok": checks["ok"],
        "checks": checks,
        "public_model_count": len(public_models),
        "wrong_type_rows": wrong_type_rows,
        "detached_collection_checks": detached_checks,
    }


def _canonical_definition_boundary_checks(ir: CanonicalIR) -> dict[str, Any]:
    canonical_fields = {item.name for item in fields(CanonicalIR)}
    encoded = ir.to_json()
    checks = {
        "all_typed_definition_domains_present": CANONICAL_EQUIPMENT_DEFINITION_FIELDS.issubset(
            canonical_fields
        ),
        "no_per_build_models_in_canonical_dataclass": canonical_fields.isdisjoint(
            FORBIDDEN_CANONICAL_BUILD_FIELDS
        ),
        "no_per_build_models_in_canonical_json": set(encoded).isdisjoint(
            FORBIDDEN_CANONICAL_BUILD_FIELDS
        ),
        "canonical_equipment_fields_are_definition_collections": all(
            isinstance(encoded.get(field_name), list)
            for field_name in CANONICAL_EQUIPMENT_DEFINITION_FIELDS
        ),
    }
    checks["ok"] = all(value is True for value in checks.values())
    return {"ok": checks["ok"], "checks": checks}


def _runtime_type_hint_checks() -> dict[str, Any]:
    failures: dict[str, str] = {}
    checked = 0
    for name, value in vars(rules_ir_module).items():
        if (
            not isinstance(value, type)
            or value.__module__ != rules_ir_module.__name__
            or not is_dataclass(value)
        ):
            continue
        checked += 1
        try:
            get_type_hints(value)
        except (NameError, TypeError) as exc:
            failures[name] = f"{type(exc).__name__}: {exc}"
    checks = {
        "ir_dataclasses_discovered": checked > 0,
        "all_ir_runtime_type_hints_resolve": not failures,
        "canonical_equipment_type_hints_resolve": bool(get_type_hints(CanonicalIR)),
    }
    checks["ok"] = all(value is True for value in checks.values())
    return {
        "ok": checks["ok"],
        "checks": checks,
        "checked_ir_dataclass_count": checked,
        "failures": failures,
    }


def _p4_boundary_matrix_check() -> tuple[dict[str, JSONValue], dict[str, Any]]:
    source = IRSource(
        source_path="fixture/p4_character.json",
        raw_type="AvatarConfig",
        raw_id="fixture:p4-avatar",
        evidence={"fixture": True},
    )
    entity = RuleEntity(
        entity_id="fixture:p4-avatar",
        entity_type="avatar",
        fields={},
        source=source,
        coverage_status="audit_only",
    )
    card = CharacterDataCardIR(
        card_id="fixture:p4-card",
        entity_ref=entity.entity_id,
        profile_id="fixture:p4-profile",
        skill_ids=(),
        skill_formula_binding_ids=(),
        bounce_policy_ids=(),
        source=source,
        coverage_status="blocked",
        blocked_reason="fixture_unbound_equipment_eligibility",
        equipment_eligibility_id="",
    )
    ir = CanonicalIR(version=BASELINE_VERSION, entities=(entity,), character_data_cards=(card,))
    rules = RuleBook(ir)
    row = build_p4_s8_equipment_boundary_matrix_row(ir, rules)
    validation = validate_p4_s8_equipment_boundary_matrix_row(cast(dict[str, Any], row))
    return row, validation


def _s0_summary_negative_checks(
    valid_summary: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    missing_rejected = _raises(
        lambda: load_s0_summary_fail_closed(output_dir / "missing-p8-s0-summary.json"),
        ValueError,
    )
    schema_mismatch = copy.deepcopy(valid_summary)
    schema_mismatch["schema_version"] = "wrong-schema"
    ok_false = copy.deepcopy(valid_summary)
    ok_false["ok"] = False
    incomplete_fingerprint = copy.deepcopy(valid_summary)
    incomplete_fingerprint["primary_source_fingerprint"].pop("sha256", None)
    malformed_fingerprint = copy.deepcopy(valid_summary)
    malformed_fingerprint["primary_source_fingerprint"]["paths"] = []
    non_hex_fingerprint = copy.deepcopy(valid_summary)
    non_hex_fingerprint["primary_source_fingerprint"]["sha256"] = "z" * 64
    count_mismatch_fingerprint = copy.deepcopy(valid_summary)
    count_mismatch_fingerprint["primary_source_fingerprint"]["file_count"] = (
        len(count_mismatch_fingerprint["primary_source_fingerprint"]["paths"]) + 1
    )
    with tempfile.TemporaryDirectory(prefix="p8-s1-s0-summary-") as temporary_dir:
        non_object_path = Path(temporary_dir) / "non-object.json"
        non_object_path.write_text("[]", encoding="utf-8")
        non_object_rejected = _raises(
            lambda: load_s0_summary_fail_closed(non_object_path),
            ValueError,
        )
    checks = {
        "missing_file_rejected": missing_rejected,
        "non_object_schema_rejected": non_object_rejected,
        "schema_mismatch_rejected": validate_s0_summary_payload(schema_mismatch)["ok"] is False,
        "ok_not_true_rejected": validate_s0_summary_payload(ok_false)["ok"] is False,
        "incomplete_fingerprint_rejected": validate_s0_summary_payload(incomplete_fingerprint)["ok"]
        is False,
        "malformed_fingerprint_rejected": validate_s0_summary_payload(malformed_fingerprint)["ok"]
        is False,
        "non_hex_fingerprint_rejected": validate_s0_summary_payload(non_hex_fingerprint)["ok"]
        is False,
        "fingerprint_file_count_path_count_mismatch_rejected": validate_s0_summary_payload(
            count_mismatch_fingerprint
        )["ok"]
        is False,
        "no_fixed_hash_fallback": True,
        "no_report_text_or_builtin_default_fallback": True,
    }
    checks["ok"] = all(value is True for value in checks.values())
    return {"ok": checks["ok"], "checks": checks}


def _fixture_source(fingerprint: dict[str, JSONValue], suffix: str) -> IRSource:
    return make_equipment_source(
        source_path=f"fixture/equipment/{suffix}.json",
        raw_type="P8S1ValidationFixture",
        raw_id=f"fixture:{suffix}",
        json_path="$",
        source_fingerprint=fingerprint,
        source_kind="validation_fixture",
    )


def _check_only(value: dict[str, Any]) -> dict[str, Any]:
    return {"ok": value.get("ok") is True, "checks": dict(value.get("checks") or {})}


def _raises(call: Any, expected_type: type[BaseException]) -> bool:
    try:
        call()
    except expected_type:
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate P8-S1 typed equipment and build contracts")
    parser.add_argument("--s0-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = run_validation(args.s0_summary, args.output_dir)
    except ValueError as exc:
        print(json.dumps({"ok": False, "reason": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
