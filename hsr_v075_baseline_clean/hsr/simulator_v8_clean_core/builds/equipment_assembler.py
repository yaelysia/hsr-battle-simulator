from __future__ import annotations

from collections import Counter

from ..build_types import (
    BuildSourceRef,
    StatCalculation,
    StaticStatContribution,
    static_property_binding,
)
from ..ir_types import IRSource
from ..equipment.models import (
    CharacterEquipmentEligibilityIR,
    EquipmentActivationBasis,
    EquipmentActivationDecision,
    EquipmentAssemblyDiagnostic,
    EquipmentAssemblyResult,
    EquipmentBattleAdmissionBlocker,
    EquipmentBuildInput,
    EquipmentDefinitionKey,
    EquipmentDefinitionResolution,
    EquipmentDynamicParameterBinding,
    EquipmentSourceLedgerEntry,
    DynamicMechanismSelection,
    LightConeAssemblySelection,
    LightConeDefinitionIR,
    LightConeInstanceInput,
    LightConePromotionTierIR,
    LightConeSuperimpositionLevelIR,
    RELIC_SET_DYNAMIC_ABILITY_NOT_ASSEMBLED_REASON,
    RelicAssemblySelection,
    RelicSetActivationDecision,
)
from ..rules.value_binding import ExactEquipmentValueBindingRequest, ValueResolver
from ..rules.rulebook import RuleBook
from .relic_affix_calculator import (
    admit_relic_main_affix,
    admit_relic_sub_affixes,
)
from .relic_set_assembler import assemble_relic_set_activations


def assemble_equipment_build(
    rules: RuleBook,
    build: EquipmentBuildInput,
) -> EquipmentAssemblyResult:
    if not isinstance(rules, RuleBook):
        raise TypeError("rules must be a RuleBook")
    if not isinstance(build, EquipmentBuildInput):
        raise TypeError("build must be EquipmentBuildInput")
    identity_diagnostics = _equipment_instance_identity_diagnostics(build)
    if identity_diagnostics:
        return _blocked(
            build,
            *identity_diagnostics,
        )
    relic_selections, relic_diagnostics = _admit_relic_instances(rules, build)
    if relic_diagnostics:
        return _blocked(build, *relic_diagnostics)
    relic_set_activation_decisions, relic_set_diagnostics = (
        assemble_relic_set_activations(rules, relic_selections)
    )
    if relic_set_diagnostics:
        return _blocked(build, *relic_set_diagnostics)
    (
        relic_contributions,
        relic_source_ledger,
        relic_static_diagnostics,
    ) = _relic_static_channels(
        rules,
        build,
        relic_selections,
        relic_set_activation_decisions,
    )
    if relic_static_diagnostics:
        return _blocked(build, *relic_static_diagnostics)
    relic_blockers = _relic_dynamic_ability_blockers(
        build,
        relic_set_activation_decisions,
    )
    if build.light_cone is None:
        return EquipmentAssemblyResult(
            assembly_id=f"equipment_assembly:{build.build_id}",
            build_fingerprint=build.build_fingerprint,
            assembly_status="assembled",
            battle_admission_status=(
                "blocked" if relic_blockers else "admitted"
            ),
            relic_selections=relic_selections,
            relic_set_activation_decisions=relic_set_activation_decisions,
            static_contributions=relic_contributions,
            battle_admission_blockers=relic_blockers,
            source_ledger=relic_source_ledger,
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

    base_contributions = _light_cone_base_contributions(instance, tier)
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
    passive_contributions = (
        _light_cone_passive_contributions(instance, rank) if active else ()
    )
    light_cone_contributions = (*base_contributions, *passive_contributions)
    contributions = (*light_cone_contributions, *relic_contributions)
    dynamic_mechanisms, light_cone_blockers = (
        _active_dynamic_mechanisms(
            rules,
            build,
            instance,
            definition,
            rank,
        )
        if active
        else ((), ())
    )
    blockers = (*light_cone_blockers, *relic_blockers)
    base_contribution_ids = tuple(
        item.contribution_id for item in base_contributions
    )
    passive_contribution_ids = tuple(
        item.contribution_id for item in passive_contributions
    )
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
        base_contribution_ids=base_contribution_ids,
        passive_contribution_ids=passive_contribution_ids,
    )
    source_ledger = tuple(
        EquipmentSourceLedgerEntry(
            ledger_entry_id=f"equipment_source:{item.contribution_id}",
            channel="static",
            definition_key=definition.definition_key,
            source=item.source,
        )
        for item in light_cone_contributions
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
    ) + relic_source_ledger
    return EquipmentAssemblyResult(
        assembly_id=f"equipment_assembly:{build.build_id}",
        build_fingerprint=build.build_fingerprint,
        assembly_status="assembled",
        battle_admission_status="blocked" if blockers else "admitted",
        light_cone_selection=selection,
        relic_selections=relic_selections,
        relic_set_activation_decisions=relic_set_activation_decisions,
        static_contributions=contributions,
        dynamic_mechanisms=dynamic_mechanisms,
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


def _admit_relic_instances(
    rules: RuleBook,
    build: EquipmentBuildInput,
) -> tuple[
    tuple[RelicAssemblySelection, ...],
    tuple[EquipmentAssemblyDiagnostic, ...],
]:
    selections: list[RelicAssemblySelection] = []
    diagnostics: list[EquipmentAssemblyDiagnostic] = []
    for instance in build.relics:
        diagnostic_count = len(diagnostics)
        template_resolution = rules.relic_template_definition(
            instance.template_key.definition_identity
        )
        if (
            template_resolution.resolution_status != "resolved"
            or template_resolution.value is None
        ):
            diagnostics.append(
                EquipmentAssemblyDiagnostic(
                    diagnostic_id=(
                        f"equipment_assembly:{build.build_id}:"
                        f"{instance.instance_id}:{template_resolution.blocked_reason}"
                    ),
                    reason=template_resolution.blocked_reason,
                    requested_key=template_resolution.requested_key,
                    candidates=template_resolution.candidates,
                )
            )
            continue
        template = template_resolution.value
        if template.publication_status != "published":
            diagnostics.append(
                EquipmentAssemblyDiagnostic(
                    diagnostic_id=(
                        f"equipment_assembly:{build.build_id}:"
                        f"{instance.instance_id}:relic_template_not_published"
                    ),
                    reason=(
                        "relic_template_publication_status_not_admitted:"
                        f"{template.publication_status}"
                    ),
                    requested_key=instance.template_key,
                    candidates=template_resolution.candidates,
                )
            )
        if template.mode != "BASIC":
            diagnostics.append(
                EquipmentAssemblyDiagnostic(
                    diagnostic_id=(
                        f"equipment_assembly:{build.build_id}:"
                        f"{instance.instance_id}:relic_template_mode_not_admitted"
                    ),
                    reason=f"relic_template_mode_not_admitted:{template.mode}",
                    requested_key=instance.template_key,
                    candidates=template_resolution.candidates,
                )
            )
        slot_resolution = rules.relic_slot_definition(
            template.slot_key.definition_identity
        )
        slot_definition = slot_resolution.value
        if (
            slot_resolution.resolution_status != "resolved"
            or slot_definition is None
        ):
            diagnostics.append(
                EquipmentAssemblyDiagnostic(
                    diagnostic_id=(
                        f"equipment_assembly:{build.build_id}:"
                        f"{instance.instance_id}:{slot_resolution.blocked_reason}"
                    ),
                    reason=slot_resolution.blocked_reason,
                    requested_key=slot_resolution.requested_key,
                    candidates=slot_resolution.candidates,
                )
            )
        if instance.slot_key != template.slot_key:
            diagnostics.append(
                EquipmentAssemblyDiagnostic(
                    diagnostic_id=(
                        f"equipment_assembly:{build.build_id}:"
                        f"{instance.instance_id}:relic_template_slot_mismatch"
                    ),
                    reason="relic_template_slot_mismatch",
                    requested_key=instance.slot_key,
                    candidates=slot_resolution.candidates,
                )
            )
        if instance.level < 0 or instance.level > template.max_level:
            diagnostics.append(
                EquipmentAssemblyDiagnostic(
                    diagnostic_id=(
                        f"equipment_assembly:{build.build_id}:"
                        f"{instance.instance_id}:relic_level_outside_template_bounds"
                    ),
                    reason="relic_level_outside_template_bounds",
                    requested_key=instance.template_key,
                    candidates=template_resolution.candidates,
                )
            )
        if len(diagnostics) != diagnostic_count or slot_definition is None:
            continue
        main_affix, main_affix_issues = admit_relic_main_affix(
            rules,
            template,
            slot_definition,
            instance,
        )
        if main_affix_issues:
            diagnostics.extend(
                EquipmentAssemblyDiagnostic(
                    diagnostic_id=(
                        f"equipment_assembly:{build.build_id}:"
                        f"{instance.instance_id}:{issue.reason}"
                    ),
                    reason=issue.reason,
                    requested_key=issue.requested_key,
                    candidates=issue.candidates,
                )
                for issue in main_affix_issues
            )
            continue
        if main_affix is None:
            diagnostics.append(
                EquipmentAssemblyDiagnostic(
                    diagnostic_id=(
                        f"equipment_assembly:{build.build_id}:"
                        f"{instance.instance_id}:relic_main_affix_not_admitted"
                    ),
                    reason="relic_main_affix_not_admitted",
                    requested_key=instance.main_affix_key,
                )
            )
            continue
        sub_affixes, sub_affix_issues = admit_relic_sub_affixes(
            rules,
            template,
            instance,
            main_affix,
        )
        if sub_affix_issues:
            diagnostics.extend(
                EquipmentAssemblyDiagnostic(
                    diagnostic_id=(
                        f"equipment_assembly:{build.build_id}:"
                        f"{instance.instance_id}:{issue.reason}"
                    ),
                    reason=issue.reason,
                    requested_key=issue.requested_key,
                    candidates=issue.candidates,
                )
                for issue in sub_affix_issues
            )
            continue
        if sub_affixes is None:
            diagnostics.append(
                EquipmentAssemblyDiagnostic(
                    diagnostic_id=(
                        f"equipment_assembly:{build.build_id}:"
                        f"{instance.instance_id}:relic_sub_affixes_not_admitted"
                    ),
                    reason="relic_sub_affixes_not_admitted",
                    requested_key=template.sub_affix_group_key,
                )
            )
            continue
        selection = RelicAssemblySelection(
            instance_id=instance.instance_id,
            instance_fingerprint=instance.instance_fingerprint,
            template_key=template.definition_key,
            slot_key=slot_definition.definition_key,
            level=instance.level,
            publication_status=template.publication_status,
            template_mode=template.mode,
            affix_validation_status="main_and_sub_affixes_validated",
            template_source=template.source,
            slot_source=slot_definition.source,
            main_affix=main_affix,
            sub_affixes=sub_affixes,
        )
        selections.append(selection)

    slot_counts = Counter(selection.slot_key for selection in selections)
    for slot_key, count in sorted(
        slot_counts.items(),
        key=lambda item: item[0].stable_id,
    ):
        if count > 1:
            diagnostics.append(
                EquipmentAssemblyDiagnostic(
                    diagnostic_id=(
                        f"equipment_assembly:{build.build_id}:"
                        f"relic_slot_reused:{slot_key.stable_id}"
                    ),
                    reason="relic_slot_reused",
                    requested_key=slot_key,
                )
            )
    if diagnostics:
        return (), tuple(diagnostics)
    return tuple(selections), ()


def _relic_static_channels(
    rules: RuleBook,
    build: EquipmentBuildInput,
    selections: tuple[RelicAssemblySelection, ...],
    decisions: tuple[RelicSetActivationDecision, ...],
) -> tuple[
    tuple[StaticStatContribution, ...],
    tuple[EquipmentSourceLedgerEntry, ...],
    tuple[EquipmentAssemblyDiagnostic, ...],
]:
    contributions: list[StaticStatContribution] = []
    ledger: list[EquipmentSourceLedgerEntry] = []
    diagnostics: list[EquipmentAssemblyDiagnostic] = []

    def append_term(
        *,
        contribution_id: str,
        raw_property_type: str,
        exact_value: str,
        definition_key: EquipmentDefinitionKey,
        source: IRSource,
    ) -> None:
        binding = static_property_binding(raw_property_type)
        if binding is None:
            diagnostics.append(
                EquipmentAssemblyDiagnostic(
                    diagnostic_id=(
                        f"equipment_assembly:{build.build_id}:"
                        f"{contribution_id}:property_type_not_admitted"
                    ),
                    reason=(
                        "relic_static_property_type_not_admitted:"
                        f"{raw_property_type}"
                    ),
                    requested_key=definition_key,
                )
            )
            return
        contribution = StaticStatContribution(
            contribution_id=contribution_id,
            contribution_pool=binding.contribution_pool,
            property_type=binding.canonical_property_type,
            exact_value=exact_value,
            source_ref=BuildSourceRef(
                definition_key.definition_kind,
                definition_key.definition_identity,
            ),
            calculation=StatCalculation(
                binding.calculation_kind,
                exact_value,
            ),
            source=source,
        )
        contributions.append(contribution)
        ledger.append(
            EquipmentSourceLedgerEntry(
                ledger_entry_id=f"equipment_source:{contribution_id}",
                channel="static",
                definition_key=definition_key,
                source=source,
            )
        )

    for selection in selections:
        main = selection.main_affix
        append_term(
            contribution_id=(
                f"relic_main_affix:{selection.instance_id}:"
                f"affix:{main.affix_key.definition_identity}"
            ),
            raw_property_type=main.property_type,
            exact_value=main.exact_value,
            definition_key=main.affix_key,
            source=main.affix_source,
        )
        for sub_affix in selection.sub_affixes:
            append_term(
                contribution_id=(
                    f"relic_sub_affix:{selection.instance_id}:"
                    f"affix:{sub_affix.affix_key.definition_identity}"
                ),
                raw_property_type=sub_affix.property_type,
                exact_value=sub_affix.exact_value,
                definition_key=sub_affix.affix_key,
                source=sub_affix.affix_source,
            )

    for decision in decisions:
        resolution = rules.relic_set_threshold(
            decision.threshold_key.definition_identity
        )
        threshold = resolution.value
        if resolution.resolution_status != "resolved" or threshold is None:
            diagnostics.append(
                EquipmentAssemblyDiagnostic(
                    diagnostic_id=(
                        f"equipment_assembly:{build.build_id}:"
                        f"{decision.decision_id}:threshold_not_resolved"
                    ),
                    reason=(
                        resolution.blocked_reason
                        or "relic_set_threshold_not_resolved"
                    ),
                    requested_key=decision.threshold_key,
                    candidates=resolution.candidates,
                )
            )
            continue
        if (
            threshold.definition_key != decision.threshold_key
            or threshold.set_key != decision.set_key
            or threshold.require_count != decision.required_count
            or threshold.source != decision.threshold_source
            or tuple(
                item.property_index
                for item in threshold.static_properties
            )
            != decision.static_property_indices
            or threshold.ability_source != decision.ability_source
        ):
            diagnostics.append(
                EquipmentAssemblyDiagnostic(
                    diagnostic_id=(
                        f"equipment_assembly:{build.build_id}:"
                        f"{decision.decision_id}:threshold_identity_mismatch"
                    ),
                    reason="relic_set_threshold_activation_identity_mismatch",
                    requested_key=decision.threshold_key,
                )
            )
            continue
        if decision.activation_status != "active":
            continue
        for item in threshold.static_properties:
            append_term(
                contribution_id=(
                    f"relic_set_static:{decision.decision_id}:"
                    f"property:{item.property_index}"
                ),
                raw_property_type=item.property_type,
                exact_value=item.exact_value,
                definition_key=threshold.definition_key,
                source=item.source,
            )

    if diagnostics:
        return (), (), tuple(
            sorted(diagnostics, key=lambda item: item.diagnostic_id)
        )
    return (
        tuple(sorted(contributions, key=lambda item: item.sort_key)),
        tuple(sorted(ledger, key=lambda item: item.ledger_entry_id)),
        (),
    )


def _relic_dynamic_ability_blockers(
    build: EquipmentBuildInput,
    decisions: tuple[RelicSetActivationDecision, ...],
) -> tuple[EquipmentBattleAdmissionBlocker, ...]:
    return tuple(
        EquipmentBattleAdmissionBlocker(
            blocker_id=(
                f"equipment_assembly:{build.build_id}:"
                f"{decision.decision_id}:dynamic_ability"
            ),
            channel="dynamic_ability",
            target_definition_key=decision.threshold_key,
            gap_classification="implementation_missing",
            reason_code=RELIC_SET_DYNAMIC_ABILITY_NOT_ASSEMBLED_REASON,
            source_refs=(
                decision.threshold_source,
                decision.ability_source.source,
            ),
        )
        for decision in decisions
        if decision.activation_status == "active"
        and decision.ability_source is not None
    )


def _equipment_instance_identity_diagnostics(
    build: EquipmentBuildInput,
) -> tuple[EquipmentAssemblyDiagnostic, ...]:
    return tuple(
        EquipmentAssemblyDiagnostic(
            diagnostic_id=(
                f"equipment_assembly:{build.build_id}:{reason}"
            ),
            reason=reason,
        )
        for reason in _equipment_instance_uniqueness_errors((build,))
    )


def validate_equipment_instance_uniqueness(
    builds: tuple[EquipmentBuildInput, ...] | list[EquipmentBuildInput],
) -> tuple[str, ...]:
    if not isinstance(builds, (list, tuple)) or not all(
        isinstance(build, EquipmentBuildInput) for build in builds
    ):
        raise TypeError("equipment instance uniqueness requires equipment build inputs")
    return _equipment_instance_uniqueness_errors(tuple(builds))


def _equipment_instance_uniqueness_errors(
    builds: tuple[EquipmentBuildInput, ...],
) -> tuple[str, ...]:
    fingerprints_by_instance_id: dict[str, list[str]] = {}
    for build in builds:
        instances = (
            *((build.light_cone,) if build.light_cone is not None else ()),
            *build.relics,
        )
        for instance in instances:
            fingerprints_by_instance_id.setdefault(
                instance.instance_id,
                [],
            ).append(instance.instance_fingerprint)
    errors = []
    for instance_id, fingerprints in sorted(
        fingerprints_by_instance_id.items()
    ):
        if len(fingerprints) <= 1:
            continue
        reason = (
            "equipment_instance_identity_conflict"
            if len(set(fingerprints)) > 1
            else "equipment_instance_id_reused"
        )
        errors.append(f"{reason}:{instance_id}")
    return tuple(errors)


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


def _light_cone_passive_contributions(
    instance: LightConeInstanceInput,
    rank: LightConeSuperimpositionLevelIR,
) -> tuple[StaticStatContribution, ...]:
    source_ref = BuildSourceRef(
        "light_cone",
        instance.definition_key.definition_identity,
    )
    return tuple(
        StaticStatContribution(
            contribution_id=(
                f"light_cone_passive:{instance.instance_id}:"
                f"rank:{rank.level}:property:{item.property_index}"
            ),
            contribution_pool=item.contribution_pool,
            property_type=item.canonical_property_type,
            exact_value=item.exact_value,
            source_ref=source_ref,
            calculation=StatCalculation(
                item.calculation_kind,
                item.exact_value,
            ),
            source=item.source,
        )
        for item in rank.static_properties
    )


def _active_dynamic_mechanisms(
    rules: RuleBook,
    build: EquipmentBuildInput,
    instance: LightConeInstanceInput,
    definition: LightConeDefinitionIR,
    rank: LightConeSuperimpositionLevelIR,
) -> tuple[
    tuple[DynamicMechanismSelection, ...],
    tuple[EquipmentBattleAdmissionBlocker, ...],
]:
    classification, reason = _dynamic_ability_gap(rules, definition)
    if classification != "executable":
        return (), (_dynamic_ability_blocker(definition, classification, reason),)
    if len(definition.mechanism_ref_ids) != 1:
        return (), (
            _dynamic_ability_blocker(
                definition,
                "admission_gap",
                "light_cone_dynamic_ability_binding_not_unique",
            ),
        )
    mechanism_resolution = rules.equipment_mechanism_ref(
        definition.mechanism_ref_ids[0].definition_identity
    )
    if (
        mechanism_resolution.resolution_status != "resolved"
        or mechanism_resolution.value is None
    ):
        return (), (
            _dynamic_ability_blocker(
                definition,
                "admission_gap",
                mechanism_resolution.blocked_reason
                or "light_cone_dynamic_ability_binding_not_admitted",
            ),
        )
    mechanism = mechanism_resolution.value
    graph = rules.standalone_ability_graph(mechanism.graph_ref_id)
    if graph is None or graph.source != definition.ability_source.source:
        return (), (
            _dynamic_ability_blocker(
                definition,
                "admission_gap",
                "light_cone_dynamic_ability_graph_source_mismatch",
            ),
        )

    resolver = ValueResolver(rules)
    bindings: list[EquipmentDynamicParameterBinding] = []
    for parameter_read_id in mechanism.parameter_binding_ids:
        parameter_read = rules.equipment_ability_parameter_read(parameter_read_id)
        if parameter_read is None:
            return (), (
                _dynamic_ability_blocker(
                    definition,
                    "admission_gap",
                    "light_cone_dynamic_parameter_read_missing_or_duplicate",
                ),
            )
        if parameter_read.parameter_index >= len(rank.parameters):
            return (), (
                _dynamic_ability_blocker(
                    definition,
                    "admission_gap",
                    "light_cone_dynamic_parameter_index_out_of_range",
                ),
            )
        parameter = rank.parameters[parameter_read.parameter_index]
        binding_id = (
            f"equipment_rank_parameter:{instance.instance_id}:rank:{rank.level}:"
            f"read:{parameter_read.parameter_read_id}"
        )
        resolution = resolver.resolve_equipment_rank_parameter(
            ExactEquipmentValueBindingRequest(
                binding_kind="equipment_rank_parameter",
                binding_id=binding_id,
                target_definition_identity=(
                    definition.definition_key.definition_identity
                ),
                graph_ref_id=graph.standalone_ability_graph_id,
                parameter_read_id=parameter_read.parameter_read_id,
                value_type=parameter_read.value_type,
                dynamic_hash=parameter_read.dynamic_hash,
                parameter_index=parameter_read.parameter_index,
                skill_id=rank.skill_id,
                superimposition_level=rank.level,
                exact_value=parameter.exact_value,
                value_source=parameter.source,
            )
        )
        if (
            not resolution.ok
            or resolution.exact_value is None
            or resolution.read_source is None
        ):
            return (), (
                _dynamic_ability_blocker(
                    definition,
                    "admission_gap",
                    resolution.blocked_reason
                    or "light_cone_dynamic_parameter_binding_blocked",
                ),
            )
        bindings.append(
            EquipmentDynamicParameterBinding(
                binding_id=binding_id,
                parameter_read_id=parameter_read.parameter_read_id,
                graph_ref_id=graph.standalone_ability_graph_id,
                value_type=parameter_read.value_type,
                dynamic_hash=parameter_read.dynamic_hash,
                parameter_index=parameter_read.parameter_index,
                exact_value=resolution.exact_value,
                read_source=resolution.read_source,
                value_source=resolution.value_source,
            )
        )

    graph_executable = graph.coverage_status == "executable"
    selection = DynamicMechanismSelection(
        selection_id=(
            f"equipment_dynamic_selection:{instance.instance_id}:"
            f"rank:{rank.level}:{mechanism.definition_key.stable_id}"
        ),
        mechanism_key=mechanism.definition_key,
        target_definition_key=definition.definition_key,
        graph_ref_id=graph.standalone_ability_graph_id,
        equipment_instance_id=instance.instance_id,
        wearer_character_card_id=build.character_card_id,
        skill_id=rank.skill_id,
        superimposition_level=rank.level,
        parameter_bindings=tuple(bindings),
        source=definition.ability_source.source,
        coverage_status="executable" if graph_executable else "blocked",
        blocked_reason="" if graph_executable else (
            graph.blocked_reason or "light_cone_dynamic_ability_graph_partial"
        ),
    )
    if graph_executable:
        return (selection,), ()
    return (selection,), (
        _dynamic_ability_blocker(
            definition,
            "implementation_missing",
            selection.blocked_reason,
        ),
    )


def _dynamic_ability_blocker(
    definition: LightConeDefinitionIR,
    classification: str,
    reason: str,
) -> EquipmentBattleAdmissionBlocker:
    return EquipmentBattleAdmissionBlocker(
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
    graph = matching_graphs[0]
    if graph.coverage_status != "executable":
        return (
            "implementation_missing",
            graph.blocked_reason or "light_cone_dynamic_ability_consumer_missing",
        )
    return "executable", ""


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
        and graph_source.raw_type == equipment_source.raw_type == "AbilityList"
        and graph_source.raw_id == ability_name
        and equipment_source.raw_id == ability_name
        and graph_source.evidence.get("json_path")
        == f"$.AbilityList[{record_index}]"
        and equipment_source.evidence.get("json_path")
        == f"$.AbilityList[{record_index}]"
        and graph_source.evidence.get("source_fingerprint")
        == equipment_source.evidence.get("source_fingerprint")
    )
