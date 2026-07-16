from __future__ import annotations

from collections import Counter

from ..build_types import BuildSourceRef, StatCalculation, StaticStatContribution
from ..ir_types import IRSource
from ..equipment.models import (
    CharacterEquipmentEligibilityIR,
    EquipmentActivationBasis,
    EquipmentActivationDecision,
    EquipmentAssemblyDiagnostic,
    EquipmentAssemblyResult,
    EquipmentBattleAdmissionBlocker,
    EquipmentBuildInput,
    EquipmentDefinitionResolution,
    EquipmentSourceLedgerEntry,
    LightConeAssemblySelection,
    LightConeDefinitionIR,
    LightConeInstanceInput,
    LightConePromotionTierIR,
    LightConeSuperimpositionLevelIR,
)
from ..rules.rulebook import RuleBook


def assemble_equipment_build(
    rules: RuleBook,
    build: EquipmentBuildInput,
) -> EquipmentAssemblyResult:
    if not isinstance(rules, RuleBook):
        raise TypeError("rules must be a RuleBook")
    if not isinstance(build, EquipmentBuildInput):
        raise TypeError("build must be EquipmentBuildInput")
    if build.relics:
        return _blocked(
            build,
            EquipmentAssemblyDiagnostic(
                diagnostic_id=f"equipment_assembly:{build.build_id}:relics_not_admitted",
                reason="p8_s4_relic_instances_not_admitted",
            ),
        )
    if build.light_cone is None:
        return EquipmentAssemblyResult(
            assembly_id=f"equipment_assembly:{build.build_id}",
            build_fingerprint=build.build_fingerprint,
            assembly_status="assembled",
            battle_admission_status="admitted",
        )

    instance = build.light_cone
    definition_resolution = rules.light_cone_definition(
        instance.definition_key.definition_identity
    )
    if (
        definition_resolution.resolution_status != "resolved"
        or definition_resolution.value is None
    ):
        return _blocked_resolution(build, definition_resolution)
    definition = definition_resolution.value
    if definition.publication_status != "published":
        return _blocked(
            build,
            EquipmentAssemblyDiagnostic(
                diagnostic_id=(
                    f"equipment_assembly:{build.build_id}:light_cone_not_published"
                ),
                reason=f"light_cone_publication_status_not_admitted:{definition.publication_status}",
                requested_key=instance.definition_key,
                candidates=definition_resolution.candidates,
            ),
        )

    eligibility_resolution = rules.character_equipment_eligibility_for_card(
        build.character_card_id
    )
    if (
        eligibility_resolution.resolution_status != "resolved"
        or eligibility_resolution.value is None
    ):
        return _blocked_resolution(build, eligibility_resolution)
    eligibility = eligibility_resolution.value

    tier, tier_errors = _select_promotion_tier(definition, instance)
    rank, rank_errors = _select_superimposition_level(definition, instance)
    progression_errors = tuple(sorted({*tier_errors, *rank_errors}))
    if progression_errors or tier is None or rank is None:
        return _blocked(
            build,
            *(
                EquipmentAssemblyDiagnostic(
                    diagnostic_id=f"equipment_assembly:{build.build_id}:{reason}",
                    reason=reason,
                    requested_key=instance.definition_key,
                    candidates=definition_resolution.candidates,
                )
                for reason in progression_errors
            ),
        )
    if definition.ability_source is None:
        return _blocked(
            build,
            EquipmentAssemblyDiagnostic(
                diagnostic_id=f"equipment_assembly:{build.build_id}:ability_source_missing",
                reason="light_cone_ability_source_missing",
                requested_key=instance.definition_key,
                candidates=definition_resolution.candidates,
            ),
        )
    source_binding_errors = _selected_source_binding_errors(
        definition,
        tier,
        rank,
    )
    if source_binding_errors:
        return _blocked(
            build,
            *(
                EquipmentAssemblyDiagnostic(
                    diagnostic_id=f"equipment_assembly:{build.build_id}:{reason}",
                    reason=reason,
                    requested_key=instance.definition_key,
                    candidates=definition_resolution.candidates,
                )
                for reason in source_binding_errors
            ),
        )

    contributions = _light_cone_base_contributions(instance, tier)
    basis = EquipmentActivationBasis(
        basis_kind="light_cone_path_equality",
        comparison_policy="exact_internal_path_identity_equality",
        policy_origin="build_assembly_rule",
        character_eligibility_key=eligibility.definition_key,
        light_cone_definition_key=definition.definition_key,
        character_path_type=eligibility.character_path_type,
        light_cone_path_type=definition.path_type,
        character_path_source=eligibility.source,
        light_cone_path_source=definition.source,
    )
    active = basis.values_match
    activation = EquipmentActivationDecision(
        decision_id=(
            f"equipment_activation:{instance.instance_id}:light_cone_path_equality"
        ),
        definition_key=definition.definition_key,
        activation_status="active" if active else "inactive",
        reason_code="light_cone_path_match" if active else "light_cone_path_mismatch",
        basis=basis,
    )
    blockers = _active_passive_blockers(rules, definition, rank) if active else ()
    contribution_ids = tuple(item.contribution_id for item in contributions)
    selection = LightConeAssemblySelection(
        instance_id=instance.instance_id,
        instance_fingerprint=instance.instance_fingerprint,
        definition_key=definition.definition_key,
        level=instance.level,
        promotion_stage=tier.promotion_stage,
        superimposition_level=rank.level,
        skill_id=rank.skill_id,
        parameter_indices=tuple(item.parameter_index for item in rank.parameters),
        static_property_indices=tuple(
            item.property_index for item in rank.static_properties
        ),
        ability_name=definition.ability_source.ability_name,
        ability_record_index=definition.ability_source.record_index,
        promotion_source=tier.source,
        superimposition_source=rank.source,
        ability_source=definition.ability_source.source,
        base_contribution_ids=contribution_ids,
    )
    source_ledger = tuple(
        EquipmentSourceLedgerEntry(
            ledger_entry_id=f"equipment_source:{item.contribution_id}",
            channel="static",
            definition_key=definition.definition_key,
            source=item.source,
        )
        for item in contributions
    ) + (
        EquipmentSourceLedgerEntry(
            ledger_entry_id=f"equipment_source:{activation.decision_id}",
            channel="activation",
            definition_key=definition.definition_key,
            source=definition.source,
        ),
        EquipmentSourceLedgerEntry(
            ledger_entry_id=f"equipment_source:{instance.instance_id}:ability_selection",
            channel="dynamic",
            definition_key=definition.definition_key,
            source=definition.ability_source.source,
        ),
    )
    return EquipmentAssemblyResult(
        assembly_id=f"equipment_assembly:{build.build_id}",
        build_fingerprint=build.build_fingerprint,
        assembly_status="assembled",
        battle_admission_status="blocked" if blockers else "admitted",
        light_cone_selection=selection,
        static_contributions=contributions,
        dynamic_mechanisms=(),
        activation_decisions=(activation,),
        battle_admission_blockers=blockers,
        source_ledger=source_ledger,
    )


def validate_equipment_assembly_admission(
    rules: RuleBook,
    build: EquipmentBuildInput,
    result: EquipmentAssemblyResult,
) -> tuple[str, ...]:
    if not isinstance(result, EquipmentAssemblyResult):
        return ("equipment_assembly_result_type_invalid",)
    canonical = assemble_equipment_build(rules, build)
    errors: list[str] = []
    if result.to_json() != canonical.to_json():
        errors.append("equipment_assembly_result_does_not_match_canonical_rebuild")
    if result.build_fingerprint != build.build_fingerprint:
        errors.append("equipment_assembly_build_fingerprint_mismatch")
    if result.assembly_status != "assembled":
        errors.append("equipment_build_not_assembled")
    return tuple(sorted(set(errors)))


def validate_equipment_instance_uniqueness(
    builds: tuple[EquipmentBuildInput, ...] | list[EquipmentBuildInput],
) -> tuple[str, ...]:
    if not isinstance(builds, (list, tuple)) or not all(
        isinstance(build, EquipmentBuildInput) for build in builds
    ):
        raise TypeError("equipment instance uniqueness requires equipment build inputs")
    instance_ids = tuple(
        build.light_cone.instance_id
        for build in builds
        if build.light_cone is not None
    )
    duplicates = tuple(
        sorted(
            instance_id
            for instance_id, count in Counter(instance_ids).items()
            if count > 1
        )
    )
    return tuple(
        f"equipment_instance_id_reused:{instance_id}" for instance_id in duplicates
    )


def _blocked_resolution(
    build: EquipmentBuildInput,
    resolution: EquipmentDefinitionResolution[object],
) -> EquipmentAssemblyResult:
    return _blocked(
        build,
        EquipmentAssemblyDiagnostic(
            diagnostic_id=(
                f"equipment_assembly:{build.build_id}:{resolution.blocked_reason}"
            ),
            reason=resolution.blocked_reason,
            requested_key=resolution.requested_key,
            candidates=resolution.candidates,
        ),
    )


def _blocked(
    build: EquipmentBuildInput,
    *diagnostics: EquipmentAssemblyDiagnostic,
) -> EquipmentAssemblyResult:
    return EquipmentAssemblyResult(
        assembly_id=f"equipment_assembly:{build.build_id}",
        build_fingerprint=build.build_fingerprint,
        assembly_status="blocked",
        battle_admission_status="blocked",
        diagnostics=diagnostics
        or (
            EquipmentAssemblyDiagnostic(
                diagnostic_id=f"equipment_assembly:{build.build_id}:blocked",
                reason="equipment_assembly_blocked_without_reason",
            ),
        ),
    )


def _select_promotion_tier(
    definition: LightConeDefinitionIR,
    instance: LightConeInstanceInput,
) -> tuple[LightConePromotionTierIR | None, tuple[str, ...]]:
    tiers = tuple(sorted(definition.promotion_tiers, key=lambda item: item.promotion_stage))
    errors: list[str] = []
    if tuple(item.promotion_stage for item in tiers) != tuple(
        range(definition.max_promotion + 1)
    ):
        errors.append("light_cone_promotion_tiers_not_complete")
    matched = tuple(
        tier for tier in tiers if tier.promotion_stage == instance.promotion
    )
    if len(matched) != 1:
        errors.append("light_cone_requested_promotion_not_unique")
        return None, tuple(sorted(set(errors)))
    tier = matched[0]
    minimum_level = (
        1
        if instance.promotion == 0
        else tiers[instance.promotion - 1].max_level
        if instance.promotion < len(tiers)
        else tier.max_level + 1
    )
    if instance.level < minimum_level or instance.level > tier.max_level:
        errors.append("light_cone_level_outside_promotion_tier")
    return tier, tuple(sorted(set(errors)))


def _select_superimposition_level(
    definition: LightConeDefinitionIR,
    instance: LightConeInstanceInput,
) -> tuple[LightConeSuperimpositionLevelIR | None, tuple[str, ...]]:
    levels = tuple(
        sorted(definition.superimposition_levels, key=lambda item: item.level)
    )
    errors: list[str] = []
    if tuple(item.level for item in levels) != tuple(
        range(1, definition.max_superimposition + 1)
    ):
        errors.append("light_cone_superimposition_levels_not_complete")
    matched = tuple(
        level for level in levels if level.level == instance.superimposition
    )
    if len(matched) != 1:
        errors.append("light_cone_requested_superimposition_not_unique")
        return None, tuple(sorted(set(errors)))
    return matched[0], tuple(sorted(set(errors)))


def _selected_source_binding_errors(
    definition: LightConeDefinitionIR,
    tier: LightConePromotionTierIR,
    rank: LightConeSuperimpositionLevelIR,
) -> tuple[str, ...]:
    if definition.ability_source is None:
        return ("light_cone_ability_source_missing",)
    errors: list[str] = []
    if not _source_matches_identity(
        definition.source,
        "EquipmentConfig",
        definition.definition_key.definition_identity,
    ):
        errors.append("light_cone_definition_source_binding_mismatch")
    expected_promotion_id = (
        f"{definition.definition_key.definition_identity}:{tier.promotion_stage}"
    )
    promotion_sources = (tier.source, *(item.source for item in tier.stat_values))
    if not _source_matches_identity(
        tier.source,
        "EquipmentPromotionConfig",
        expected_promotion_id,
    ) or any(
        not _source_matches_identity(
            item.source,
            "EquipmentPromotionConfigValue",
            f"{expected_promotion_id}:{item.field_name}",
        )
        or item.source.source_path != tier.source.source_path
        for item in tier.stat_values
    ):
        errors.append("light_cone_promotion_source_binding_mismatch")
    expected_rank_id = f"{rank.skill_id}:{rank.level}"
    rank_sources = (
        rank.source,
        *(item.source for item in rank.parameters),
        *(item.source for item in rank.static_properties),
    )
    if (
        not _source_matches_identity(
            rank.source,
            "EquipmentSkillConfig",
            expected_rank_id,
        )
        or any(
            not _source_matches_identity(
                item.source,
                "EquipmentSkillParameter",
                f"{expected_rank_id}:{item.parameter_index}",
            )
            or item.source.source_path != rank.source.source_path
            for item in rank.parameters
        )
        or any(
            not _source_matches_identity(
                item.source,
                "EquipmentSkillStaticProperty",
                f"{expected_rank_id}:{item.property_index}",
            )
            or item.source.source_path != rank.source.source_path
            for item in rank.static_properties
        )
    ):
        errors.append("light_cone_superimposition_source_binding_mismatch")
    selected_sources = (
        definition.source,
        *promotion_sources,
        *rank_sources,
        definition.ability_source.source,
    )
    fingerprints = tuple(
        source.evidence.get("source_fingerprint") for source in selected_sources
    )
    if any(fingerprint != fingerprints[0] for fingerprint in fingerprints[1:]):
        errors.append("light_cone_selected_source_fingerprint_mismatch")
    return tuple(sorted(set(errors)))


def _source_matches_identity(
    source: IRSource,
    raw_type: str,
    raw_id: str,
) -> bool:
    return bool(
        isinstance(source, IRSource)
        and source.raw_type == raw_type
        and source.raw_id == raw_id
    )


def _light_cone_base_contributions(
    instance: LightConeInstanceInput,
    tier: LightConePromotionTierIR,
) -> tuple[StaticStatContribution, ...]:
    values = {item.field_name: item for item in tier.stat_values}
    fields = (
        ("max_hp", "base_hp", "hp_per_level"),
        ("attack", "base_attack", "attack_per_level"),
        ("defense", "base_defence", "defence_per_level"),
    )
    result: list[StaticStatContribution] = []
    source_ref = BuildSourceRef(
        "light_cone",
        instance.definition_key.definition_identity,
    )
    for property_type, base_field, growth_field in fields:
        base = values[base_field]
        growth = values[growth_field]
        base_calculation = StatCalculation("constant", base.exact_value)
        growth_calculation = StatCalculation(
            "linear_growth",
            "0",
            growth.exact_value,
            instance.level - 1,
        )
        result.extend(
            (
                StaticStatContribution(
                    contribution_id=(
                        f"light_cone_base:{instance.instance_id}:"
                        f"promotion:{tier.promotion_stage}:{property_type}:base"
                    ),
                    contribution_pool="base",
                    property_type=property_type,
                    exact_value=base_calculation.exact_value,
                    source_ref=source_ref,
                    calculation=base_calculation,
                    source=base.source,
                ),
                StaticStatContribution(
                    contribution_id=(
                        f"light_cone_base:{instance.instance_id}:"
                        f"promotion:{tier.promotion_stage}:{property_type}:growth"
                    ),
                    contribution_pool="base",
                    property_type=property_type,
                    exact_value=growth_calculation.exact_value,
                    source_ref=source_ref,
                    calculation=growth_calculation,
                    source=growth.source,
                ),
            )
        )
    return tuple(result)


def _active_passive_blockers(
    rules: RuleBook,
    definition: LightConeDefinitionIR,
    rank: LightConeSuperimpositionLevelIR,
) -> tuple[EquipmentBattleAdmissionBlocker, ...]:
    blockers: list[EquipmentBattleAdmissionBlocker] = []
    if rank.static_properties:
        blockers.append(
            EquipmentBattleAdmissionBlocker(
                blocker_id=(
                    f"equipment_battle_blocker:{definition.definition_key.stable_id}:"
                    f"rank:{rank.level}:static_passive"
                ),
                channel="static_passive",
                target_definition_key=definition.definition_key,
                gap_classification="implementation_missing",
                reason_code="light_cone_static_passive_consumer_missing",
                source_refs=tuple(item.source for item in rank.static_properties),
            )
        )
    classification, reason = _dynamic_ability_gap(rules, definition)
    blockers.append(
        EquipmentBattleAdmissionBlocker(
            blocker_id=(
                f"equipment_battle_blocker:{definition.definition_key.stable_id}:"
                "dynamic_ability"
            ),
            channel="dynamic_ability",
            target_definition_key=definition.definition_key,
            gap_classification=classification,
            reason_code=reason,
            source_refs=(definition.ability_source.source,),
        )
    )
    return tuple(blockers)


def _dynamic_ability_gap(
    rules: RuleBook,
    definition: LightConeDefinitionIR,
) -> tuple[str, str]:
    if definition.ability_source is None:
        return "lowering_gap", "light_cone_dynamic_ability_source_missing"
    graphs = rules.standalone_ability_graphs_by_name(
        definition.ability_source.ability_name
    )
    matching_graphs = tuple(
        graph
        for graph in graphs
        if _same_ability_source_record(
            graph.source,
            definition.ability_source.source,
            definition.ability_source.ability_name,
            definition.ability_source.record_index,
        )
    )
    if not matching_graphs:
        return "lowering_gap", "light_cone_dynamic_ability_graph_not_lowered"
    if len(matching_graphs) != 1 or not definition.mechanism_ref_ids:
        return "admission_gap", "light_cone_dynamic_ability_binding_not_admitted"
    resolved = tuple(
        rules.equipment_mechanism_ref(key.definition_identity)
        for key in definition.mechanism_ref_ids
    )
    if any(
        item.resolution_status != "resolved"
        or item.value is None
        or item.value.graph_ref_id
        != matching_graphs[0].standalone_ability_graph_id
        for item in resolved
    ):
        return "admission_gap", "light_cone_dynamic_ability_binding_not_admitted"
    return "implementation_missing", "light_cone_dynamic_ability_consumer_missing"


def _same_ability_source_record(
    graph_source: IRSource,
    equipment_source: IRSource,
    ability_name: str,
    record_index: int,
) -> bool:
    if not isinstance(graph_source, IRSource) or not isinstance(
        equipment_source, IRSource
    ):
        return False
    return bool(
        graph_source.source_path == equipment_source.source_path
        and graph_source.raw_id == ability_name
        and graph_source.evidence.get("ability_index") == record_index
    )
