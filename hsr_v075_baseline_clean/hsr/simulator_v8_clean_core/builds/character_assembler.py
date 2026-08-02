from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from ..build_types import (
    BuildSourceRef,
    StatCalculation,
    StaticStatAggregate,
    StaticStatContribution,
    aggregate_static_stat_contributions,
    canonical_decimal,
    canonical_json_fingerprint,
    contribution_channel_for_application_kind,
    ir_source_from_json,
)
from ..equipment.models import EquipmentAssemblyResult
from ..ir_types import IRSource, same_ir_source_raw_row
from ..rules.ir import (
    AvatarProfileIR,
    AvatarPromotionTierIR,
    CharacterBuildBindingIR,
    CharacterBuildSelectorRelationIR,
    CharacterDataCardIR,
    CharacterEidolonSlotIR,
    CharacterTraceNodeIR,
    ServantDefinitionIR,
)
from ..rules.engine_rule_registry import (
    special_resource_initializer_numeric_binding_source,
)
from ..rules.rulebook import RuleBook
from .models import (
    CharacterBasePanel,
    CharacterBuildAssemblyResult,
    CharacterBuildInput,
    CharacterDynamicGraphRef,
    CharacterMechanismDiagnostic,
    CharacterPanelResource,
    CharacterResourceBinding,
    CharacterResourceInitializerBinding,
    CharacterSelectorSpecialization,
    CharacterSkillLevelResolution,
    CharacterSkillLevelSource,
    OwnedCombatantActionBinding,
    OwnedCombatantBuildAssemblyResult,
    OwnedCombatantLifecycleAdmission,
    OwnedCombatantStatBinding,
)
from .equipment_assembler import (
    assemble_equipment_build,
    validate_equipment_assembly_admission,
)


_PANEL_PRIMARY_PROPERTIES = {
    "max_hp",
    "attack",
    "defense",
    "speed",
    "max_energy",
    "critical_chance",
    "critical_damage",
    "base_aggro",
}
def assemble_character_build(
    rules: RuleBook,
    build: CharacterBuildInput,
) -> CharacterBuildAssemblyResult:
    if not isinstance(rules, RuleBook):
        raise TypeError("rules must be a RuleBook")
    if not isinstance(build, CharacterBuildInput):
        raise TypeError("build must be CharacterBuildInput")
    static_errors: list[str] = []
    card = rules.character_data_card(build.character_card_id)
    if card is None:
        return _blocked(build, "character_data_card_missing")
    if card.coverage_status != "executable":
        static_errors.append(card.blocked_reason or "character_data_card_not_executable")
    expected_entity_ref = f"avatar:{card.entity_ref.removeprefix('avatar:')}"
    if card.entity_ref != expected_entity_ref:
        static_errors.append("character_data_card_entity_ref_not_canonical")
    profile = rules.avatar_profile_by_profile_id(card.profile_id)
    if profile is None:
        static_errors.append("avatar_profile_missing")
    elif profile.avatar_id != card.entity_ref.removeprefix("avatar:"):
        static_errors.append("avatar_profile_character_identity_mismatch")
    elif profile.coverage_status != "executable":
        static_errors.append(profile.blocked_reason or "avatar_profile_not_executable")
    if static_errors or profile is None:
        return _blocked(build, *static_errors)

    equipment_result = assemble_equipment_build(rules, build.equipment_build)
    if equipment_result.assembly_status != "assembled":
        return _blocked(
            build,
            *(diagnostic.reason for diagnostic in equipment_result.diagnostics),
            equipment_result=equipment_result,
        )

    tier, tier_errors = _promotion_tier(profile.promotion_tiers, build.promotion, build.level)
    if tier_errors or tier is None:
        return _blocked(build, *tier_errors)
    resource_bindings, resource_errors = _character_resource_bindings(profile)
    if resource_errors:
        return _blocked(build, *resource_errors)

    selected_nodes, trace_errors = _selected_trace_nodes(rules, build)
    if trace_errors:
        return _blocked(build, *trace_errors)
    selected_eidolons, eidolon_errors = _selected_eidolon_slots(
        rules,
        card,
        build,
    )
    if eidolon_errors:
        return _blocked(build, *eidolon_errors)
    selected_bindings, binding_errors = _selected_build_bindings(
        rules,
        build,
        selected_nodes,
        selected_eidolons,
    )
    if binding_errors:
        return _blocked(build, *binding_errors)
    skill_levels, skill_level_diagnostics, skill_level_errors = _resolve_effective_skill_levels(
        rules,
        card,
        build,
        selected_nodes,
        selected_eidolons,
        selected_bindings,
    )
    if skill_level_errors:
        return _blocked(build, *skill_level_errors)

    contributions = _base_contributions(tier, build.level)
    if profile.resource_mode == "standard_energy":
        if profile.max_energy is None or profile.max_energy_source is None:
            return _blocked(build, "avatar_max_energy_source_missing")
        contributions.append(
            StaticStatContribution(
                contribution_id=f"character_resource:{profile.avatar_profile_id}:max_energy",
                contribution_pool="base",
                property_type="max_energy",
                exact_value=profile.max_energy,
                source_ref=BuildSourceRef("avatar_profile", profile.avatar_profile_id),
                calculation=StatCalculation("constant", profile.max_energy),
                source=profile.max_energy_source,
            )
        )
    contributions.extend(equipment_result.static_contributions)
    diagnostics: list[CharacterMechanismDiagnostic] = list(skill_level_diagnostics)
    diagnostics.extend(
        CharacterMechanismDiagnostic(
            diagnostic_id=(
                f"character_mechanism_diagnostic:{gap.selector_gap_id}"
            ),
            mechanism_kind="build_selector_source_gap",
            target_ref_id=gap.selector_gap_id,
            reason=gap.blocked_reason,
            source=gap.selector_source,
        )
        for gap in rules.character_build_selector_gaps_for_card(card.card_id)
    )
    direct_dynamic_bindings: list[CharacterBuildBindingIR] = []
    for binding in selected_bindings:
        if binding.projection_kind in {
            "static_contribution",
            "resource_contribution",
        }:
            contribution, error = _character_build_binding_contribution(binding)
            if error or contribution is None:
                return _blocked(
                    build,
                    error or "character_build_contribution_projection_missing",
                )
            contributions.append(contribution)
        elif binding.projection_kind == "dynamic_graph_ref":
            direct_dynamic_bindings.append(binding)
        elif binding.projection_kind == "source_gap":
            diagnostics.append(
                CharacterMechanismDiagnostic(
                    diagnostic_id=(
                        f"character_mechanism_diagnostic:"
                        f"{binding.build_binding_id}"
                    ),
                    mechanism_kind=(
                        f"{binding.selection_kind}_source_gap"
                    ),
                    target_ref_id=binding.target_ref_id,
                    reason=binding.blocked_reason,
                    source=binding.source,
                )
            )
        elif binding.projection_kind != "skill_level_change":
            return _blocked(
                build,
                f"character_build_projection_kind_unknown:{binding.build_binding_id}",
            )
    (
        dynamic_graph_refs,
        selector_specializations,
        dynamic_errors,
    ) = _assemble_character_dynamic_roots(
        rules,
        card,
        selected_nodes,
        selected_eidolons,
        tuple(direct_dynamic_bindings),
    )
    if dynamic_errors:
        return _blocked(build, *dynamic_errors)
    diagnostics.extend(
        CharacterMechanismDiagnostic(
            diagnostic_id=(
                f"character_mechanism_diagnostic:{root.dynamic_graph_ref_id}"
            ),
            mechanism_kind="character_dynamic_graph_root",
            target_ref_id=root.dynamic_graph_ref_id,
            reason=root.blocked_reason,
            source=root.root_source,
        )
        for root in dynamic_graph_refs
    )
    owned_combatants, owned_diagnostics = _assemble_owned_combatants(
        rules,
        card,
        build,
        selected_nodes,
        selected_bindings,
    )
    diagnostics.extend(owned_diagnostics)
    try:
        aggregates = aggregate_static_stat_contributions(contributions)
        panel = _panel_from_aggregates(
            aggregates,
            resource_mode=profile.resource_mode,
            resource_bindings=resource_bindings,
        )
        return CharacterBuildAssemblyResult(
            assembly_status="assembled",
            battle_admission_status=(
                "blocked"
                if diagnostics
                or equipment_result.battle_admission_status == "blocked"
                or any(
                    item.battle_admission_status != "admitted"
                    for item in owned_combatants
                )
                else "admitted"
            ),
            input_fingerprint=build.input_fingerprint,
            build_id=build.build_id,
            equipment_assembly_result=equipment_result,
            base_panel=panel,
            contribution_ledger=tuple(contributions),
            effective_skill_levels=tuple(skill_levels),
            selected_trace_node_ids=tuple(
                node.trace_node_id for node in selected_nodes
            ),
            selected_eidolon_slot_ids=tuple(
                slot.eidolon_slot_id for slot in selected_eidolons
            ),
            dynamic_graph_refs=tuple(dynamic_graph_refs),
            selector_specializations=selector_specializations,
            resource_bindings=resource_bindings,
            owned_combatant_results=owned_combatants,
            unadmitted_mechanism_diagnostics=tuple(diagnostics),
        )
    except (TypeError, ValueError) as exc:
        return _blocked(build, f"character_contribution_ledger_invalid:{exc}")


def validate_character_build_admission(
    rules: RuleBook,
    build: CharacterBuildInput,
    result: CharacterBuildAssemblyResult,
) -> tuple[str, ...]:
    errors: list[str] = []
    canonical_result = assemble_character_build(rules, build)
    if canonical_result.to_json() != result.to_json():
        errors.append("assembly_result_does_not_match_canonical_rulebook_rebuild")
    if result.input_fingerprint != build.input_fingerprint:
        errors.append("assembly_input_fingerprint_mismatch")
    if result.build_id != build.build_id:
        errors.append("assembly_build_identity_mismatch")
    if result.equipment_assembly_result is None:
        errors.append("equipment_assembly_result_missing")
    else:
        errors.extend(
            validate_equipment_assembly_admission(
                rules,
                build.equipment_build,
                result.equipment_assembly_result,
            )
        )
        if result.equipment_assembly_result.battle_admission_status != "admitted":
            errors.append("equipment_build_not_admitted_for_battle")
    if result.assembly_status != "assembled" or result.battle_admission_status != "admitted":
        errors.append("character_build_not_admitted_for_battle")
    if result.unadmitted_mechanism_diagnostics:
        errors.append("character_build_has_unadmitted_mechanisms")
    card = rules.character_data_card(build.character_card_id)
    if card is None:
        errors.append("character_data_card_missing_during_admission")
    for contribution in result.contribution_ledger:
        if contribution.source_ref.definition_kind == "avatar_promotion_tier":
            profile = rules.avatar_profile_by_profile_id(
                card.profile_id
            ) if card is not None else None
            candidates = profile.promotion_tiers if profile is not None else ()
            matched = tuple(
                tier
                for tier in candidates
                if tier.promotion_tier_id == contribution.source_ref.definition_identity
            )
            if len(matched) != 1 or matched[0].source != contribution.source:
                errors.append(f"contribution_source_not_resolvable:{contribution.contribution_id}")
        elif contribution.source_ref.definition_kind == "avatar_profile":
            profile = rules.avatar_profile_by_profile_id(contribution.source_ref.definition_identity)
            if profile is None or profile.max_energy_source != contribution.source:
                errors.append(f"contribution_source_not_resolvable:{contribution.contribution_id}")
        elif contribution.source_ref.definition_kind == "character_mechanism_slot":
            slot = rules.character_mechanism_slot(contribution.source_ref.definition_identity)
            if slot is None or slot.source != contribution.source:
                errors.append(f"contribution_source_not_resolvable:{contribution.contribution_id}")
        elif contribution.source_ref.definition_kind == "light_cone":
            resolution = rules.light_cone_definition(
                contribution.source_ref.definition_identity
            )
            instance = build.equipment_build.light_cone
            selected_light_cone_sources = (
                tuple(
                    value.source
                    for tier in resolution.value.promotion_tiers
                    if instance is not None
                    and tier.promotion_stage == instance.promotion
                    for value in tier.stat_values
                )
                + tuple(
                    value.source
                    for rank in resolution.value.superimposition_levels
                    if instance is not None
                    and rank.level == instance.superimposition
                    for value in rank.static_properties
                )
                if resolution.resolution_status == "resolved"
                and resolution.value is not None
                else ()
            )
            if (
                instance is None
                or instance.definition_key.definition_identity
                != contribution.source_ref.definition_identity
                or contribution.source not in selected_light_cone_sources
            ):
                errors.append(
                    f"contribution_source_not_resolvable:{contribution.contribution_id}"
                )
        elif contribution.source_ref.definition_kind == "relic_main_affix":
            resolution = rules.relic_main_affix_definition(
                contribution.source_ref.definition_identity
            )
            if (
                resolution.resolution_status != "resolved"
                or resolution.value is None
                or resolution.value.source != contribution.source
            ):
                errors.append(
                    f"contribution_source_not_resolvable:{contribution.contribution_id}"
                )
        elif contribution.source_ref.definition_kind == "relic_sub_affix":
            resolution = rules.relic_sub_affix_definition(
                contribution.source_ref.definition_identity
            )
            if (
                resolution.resolution_status != "resolved"
                or resolution.value is None
                or resolution.value.source != contribution.source
            ):
                errors.append(
                    f"contribution_source_not_resolvable:{contribution.contribution_id}"
                )
        elif contribution.source_ref.definition_kind == "relic_set_threshold":
            resolution = rules.relic_set_threshold(
                contribution.source_ref.definition_identity
            )
            if (
                resolution.resolution_status != "resolved"
                or resolution.value is None
                or contribution.source
                not in tuple(
                    item.source
                    for item in resolution.value.static_properties
                )
            ):
                errors.append(
                    f"contribution_source_not_resolvable:{contribution.contribution_id}"
                )
        else:
            errors.append(f"contribution_source_kind_not_admitted:{contribution.contribution_id}")
    card_actions = card.action_set.get("actions") if card is not None else None
    action_entries = tuple(card_actions) if isinstance(card_actions, (list, tuple)) else ()
    for skill_level in result.effective_skill_levels:
        if card is None or skill_level.skill_id not in card.skill_ids:
            errors.append(f"skill_level_character_identity_mismatch:{skill_level.skill_id}")
            continue
        matching_effective_actions = tuple(
            entry
            for entry in action_entries
            if isinstance(entry, Mapping)
            and entry.get("action_id") == skill_level.action_id
            and entry.get("raw_skill_id") == skill_level.skill_id
            and entry.get("level") == skill_level.effective_level
        )
        if len(matching_effective_actions) != 1:
            errors.append(f"effective_skill_level_definition_not_unique:{skill_level.action_id}")
            action_record_source = None
        else:
            try:
                action_record_source = ir_source_from_json(
                    matching_effective_actions[0].get("source_trace"),
                    "effective_skill_level_action_record_source",
                )
            except (TypeError, ValueError):
                action_record_source = None
                errors.append(
                    f"effective_skill_level_action_record_source_invalid:"
                    f"{skill_level.action_id}:{skill_level.effective_level}"
                )
            else:
                if action_record_source != skill_level.action_record_source:
                    errors.append(
                        f"effective_skill_level_action_record_source_not_canonical:"
                        f"{skill_level.action_id}:{skill_level.effective_level}"
                    )
        definition_candidates = rules.action_definition_candidates(
            skill_level.action_id,
            skill_level.effective_level,
        )
        if len(definition_candidates) != 1:
            errors.append(
                f"effective_skill_level_action_definition_not_unique:"
                f"{skill_level.action_id}:{skill_level.effective_level}"
            )
        else:
            definition = definition_candidates[0]
            if (
                definition.coverage_status != "executable"
                or definition.definition_id != skill_level.action_definition_id
                or definition.source != skill_level.action_definition_source
            ):
                errors.append(
                    f"effective_skill_level_action_definition_not_admitted:"
                    f"{skill_level.action_id}:{skill_level.effective_level}"
                )
            if action_record_source is not None:
                try:
                    same_raw_row = same_ir_source_raw_row(
                        action_record_source,
                        definition.source,
                        expected_level=skill_level.effective_level,
                    )
                except (TypeError, ValueError):
                    errors.append(
                        f"effective_skill_level_action_raw_row_identity_invalid:"
                        f"{skill_level.action_id}:{skill_level.effective_level}"
                    )
                else:
                    if not same_raw_row:
                        errors.append(
                            f"effective_skill_level_action_definition_raw_row_mismatch:"
                            f"{skill_level.action_id}:{skill_level.effective_level}"
                        )
        for level_source in skill_level.sources:
            if level_source.source_ref.definition_kind == "character_mechanism_slot":
                slot = rules.character_mechanism_slot(
                    level_source.source_ref.definition_identity
                )
                if (
                    slot is None
                    or slot.character_data_card_id != build.character_card_id
                    or slot.source != level_source.source
                    or slot.coverage_status != "executable"
                ):
                    errors.append(
                        f"skill_level_source_not_resolvable:{level_source.source_ref.stable_id}"
                    )
            elif level_source.source_ref.definition_kind == "character_action_definition":
                matching_source_actions = tuple(
                    entry
                    for entry in action_entries
                    if isinstance(entry, Mapping)
                    and f"{entry.get('action_id')}:{entry.get('level')}"
                    == level_source.source_ref.definition_identity
                )
                try:
                    source = (
                        ir_source_from_json(
                            matching_source_actions[0].get("source_trace"),
                            "action_source_trace",
                        )
                        if len(matching_source_actions) == 1
                        else None
                    )
                except (TypeError, ValueError):
                    source = None
                if source != level_source.source:
                    errors.append(
                        f"skill_level_source_not_resolvable:{level_source.source_ref.stable_id}"
                    )
            else:
                errors.append(
                    f"skill_level_source_kind_not_admitted:{level_source.source_ref.stable_id}"
                )
    selected_trace_ids = set(result.selected_trace_node_ids)
    selected_eidolon_ids = set(result.selected_eidolon_slot_ids)
    for node_id in selected_trace_ids:
        node = rules.character_trace_node(node_id)
        if node is None or node.character_data_card_id != build.character_card_id:
            errors.append(f"selected_trace_node_not_resolvable:{node_id}")
    for slot_id in selected_eidolon_ids:
        slot = rules.character_eidolon_slot(slot_id)
        if slot is None or slot.character_data_card_id != build.character_card_id:
            errors.append(f"selected_eidolon_slot_not_resolvable:{slot_id}")
    canonical_roots = {
        item.dynamic_graph_ref_id: item
        for item in canonical_result.dynamic_graph_refs
    }
    for dynamic_ref in result.dynamic_graph_refs:
        graph = rules.character_ability_source_graph(dynamic_ref.source_graph_id)
        graph_ref = next(
            (
                ref
                for ref in card.ability_source_graph_refs
                if ref.graph_ref_id == dynamic_ref.source_graph_ref_id
            ),
            None,
        ) if card is not None else None
        direct_bindings = tuple(
            rules.character_build_binding(binding_id)
            for binding_id in dynamic_ref.build_binding_ids
        )
        definition = (
            rules.character_ability_definition(dynamic_ref.ability_definition_id)
            if dynamic_ref.root_kind == "ability_definition"
            else None
        )
        if (
            canonical_roots.get(dynamic_ref.dynamic_graph_ref_id) != dynamic_ref
            or graph is None
            or graph_ref is None
            or graph_ref.graph_id != graph.graph_id
            or any(
                binding is None
                or binding.dynamic_ref_kind != "direct_ability"
                or binding.selection_ref_id
                not in selected_trace_ids.union(selected_eidolon_ids)
                for binding in direct_bindings
            )
            or (
                dynamic_ref.root_kind == "ability_definition"
                and (
                    definition is None
                    or definition.definition_id != dynamic_ref.root_ref_id
                    or definition.source != dynamic_ref.root_source
                )
            )
            or (
                dynamic_ref.root_kind == "source_graph"
                and (
                    (source := rules.character_ability_source(
                        dynamic_ref.root_ref_id
                    )) is None
                    or source.source != dynamic_ref.root_source
                    or graph.source_id != source.source_id
                )
            )
        ):
            errors.append(
                f"dynamic_graph_ref_not_resolvable:{dynamic_ref.dynamic_graph_ref_id}"
            )
    canonical_specializations = {
        item.specialization_id: item
        for item in canonical_result.selector_specializations
    }
    selected_ids = selected_trace_ids.union(selected_eidolon_ids)
    for specialization in result.selector_specializations:
        relation = rules.character_build_selector_relation(
            specialization.selector_relation_id
        )
        selection_matched = bool(
            relation is not None
            and selected_ids.intersection(relation.selection_ref_ids)
        )
        predicate_value = (
            relation.selector_value_when_selected
            if relation is not None and selection_matched
            else not relation.selector_value_when_selected
            if relation is not None
            else False
        )
        subtree_path = (
            relation.true_subtree_path
            if relation is not None and predicate_value
            else relation.false_subtree_path
            if relation is not None
            else ""
        )
        if (
            canonical_specializations.get(specialization.specialization_id)
            != specialization
            or relation is None
            or relation.character_data_card_id != build.character_card_id
            or specialization.selection_matched != selection_matched
            or specialization.predicate_value != predicate_value
            or specialization.selected_subtree_path != subtree_path
            or specialization.selector_source != relation.selector_source
        ):
            errors.append(
                "selector_specialization_not_resolvable:"
                f"{specialization.specialization_id}"
            )
    profile = (
        rules.avatar_profile_by_profile_id(card.profile_id)
        if card is not None
        else None
    )
    if profile is not None and profile.resource_mode == "special_resource":
        definition = profile.special_resource_definition
        if (
            definition is None
            or definition.coverage_status != "executable"
            or len(result.resource_bindings) != 1
            or result.resource_bindings[0].resource_definition_id
            != definition.resource_definition_id
            or result.resource_bindings[0].source != definition.source
        ):
            errors.append("special_resource_binding_not_canonical")
    elif result.resource_bindings:
        errors.append("standard_energy_build_has_special_resource_binding")
    owner_skill_ids = {item.skill_id for item in result.effective_skill_levels}
    canonical_owned_by_definition = {
        item.servant_definition_id: item
        for item in canonical_result.owned_combatant_results
    }
    actual_owned_definition_ids = {
        item.servant_definition_id for item in result.owned_combatant_results
    }
    if (
        canonical_result.assembly_status == "assembled"
        and actual_owned_definition_ids != set(canonical_owned_by_definition)
    ):
        errors.append("owned_combatant_result_set_not_canonical")
    for owned in result.owned_combatant_results:
        definition = rules.servant_definition(owned.servant_definition_id)
        relation = (
            definition.owner_relation_for(owned.owner_entity_ref)
            if definition is not None
            else None
        )
        if (
            definition is None
            or definition.servant_ref != owned.servant_ref
            or relation is None
            or relation.owner_relation_id != owned.owner_relation_id
            or relation.owner_character_card_id != build.character_card_id
        ):
            errors.append(
                f"owned_combatant_definition_or_relation_not_canonical:{owned.owned_build_id}"
            )
            continue
        if owned.parent_build_id != build.build_id or (
            owned.parent_input_fingerprint != build.input_fingerprint
        ):
            errors.append(f"owned_combatant_parent_identity_mismatch:{owned.owned_build_id}")
        if owned.classified_skill_ids != tuple(sorted(definition.skill_ids)):
            errors.append(
                f"owned_combatant_classified_skill_set_not_canonical:{owned.owned_build_id}"
            )
        if owner_skill_ids.intersection(
            item.skill_id for item in owned.effective_skill_levels
        ):
            errors.append(f"owned_combatant_skill_double_applied:{owned.owned_build_id}")
        if owned.battle_admission_status != "admitted":
            errors.append(f"owned_combatant_build_not_admitted:{owned.owned_build_id}")
        expected_stat_bindings, stat_binding_errors = _owned_combatant_stat_bindings(
            definition
        )
        normalized_stat_bindings = tuple(
            sorted(expected_stat_bindings, key=lambda item: item.property_type)
        )
        if owned.stat_bindings != normalized_stat_bindings:
            errors.append(
                f"owned_combatant_stat_binding_not_canonical:{owned.owned_build_id}"
            )
        if stat_binding_errors and owned.battle_admission_status == "admitted":
            errors.append(
                f"owned_combatant_stat_source_not_admitted:{owned.owned_build_id}"
            )
        if owned.mechanism_binding_ids != tuple(sorted(definition.ability_graph_ids)):
            errors.append(
                f"owned_combatant_mechanism_binding_set_not_canonical:{owned.owned_build_id}"
            )
        lifecycle_sources, lifecycle_source_errors = _ir_sources_from_json_rows(
            definition.lifecycle_source.get("source_trace")
            if isinstance(definition.lifecycle_source, Mapping)
            else None,
            "owned_combatant_lifecycle_source",
        )
        lifecycle = owned.lifecycle_admission
        source_sort_key = lambda item: (
            item.source_path,
            item.raw_type,
            item.raw_id,
        )
        expected_spawn_sources = tuple(
            sorted(definition.spawn_sources, key=source_sort_key)
        )
        expected_lifecycle_sources = tuple(
            sorted(lifecycle_sources, key=source_sort_key)
        )
        if (
            lifecycle_source_errors
            or lifecycle.owner_relation_id != relation.owner_relation_id
            or lifecycle.birth_template_id != definition.birth_template_id
            or lifecycle.spawn_sources != expected_spawn_sources
            or lifecycle.lifecycle_sources != expected_lifecycle_sources
        ):
            errors.append(
                f"owned_combatant_lifecycle_not_canonical:{owned.owned_build_id}"
            )
        if (
            lifecycle.admission_status != "admitted"
            and owned.battle_admission_status == "admitted"
        ):
            errors.append(
                f"owned_combatant_lifecycle_not_admitted:{owned.owned_build_id}"
            )
        if rules.unit_birth_template(definition.birth_template_id) is None:
            errors.append(
                f"owned_combatant_birth_template_not_resolvable:{owned.owned_build_id}"
            )
        canonical_owned = canonical_owned_by_definition.get(
            owned.servant_definition_id
        )
        if canonical_owned is None:
            errors.append(
                f"owned_combatant_canonical_result_missing:{owned.owned_build_id}"
            )
        else:
            for channel_name in (
                "effective_skill_levels",
                "action_bindings",
                "stat_bindings",
                "mechanism_binding_ids",
                "lifecycle_admission",
            ):
                if getattr(owned, channel_name) != getattr(
                    canonical_owned,
                    channel_name,
                ):
                    errors.append(
                        f"owned_combatant_{channel_name}_not_canonical:"
                        f"{owned.owned_build_id}"
                    )
        skill_levels_by_id = {
            item.skill_id: item for item in owned.effective_skill_levels
        }
        for action in owned.action_bindings:
            action_definition = rules.action_definition_candidates(
                action.action_id,
                action.effective_level,
            )
            admissions = rules.action_admissions_for(
                definition.servant_ref,
                action.action_id,
                action.effective_level,
            )
            binding = rules.action_ability_binding(
                action.action_id,
                action.effective_level,
            )
            skill_level = skill_levels_by_id.get(action.skill_id)
            if (
                len(action_definition) != 1
                or action_definition[0].coverage_status != "executable"
                or action_definition[0].definition_id != action.action_definition_id
                or action_definition[0].source != action.action_source
                or len(admissions) != 1
                or admissions[0].coverage_status != "executable"
                or admissions[0].action_role != "turn_action"
                or binding is None
                or binding.coverage_status != "executable"
                or binding.binding_id != action.ability_binding_id
                or binding.source != action.ability_binding_source
                or skill_level is None
                or skill_level.action_id != action.action_id
                or skill_level.effective_level != action.effective_level
            ):
                errors.append(
                    f"owned_combatant_action_binding_not_canonical:{action.action_id}"
                )
    return tuple(sorted(set(errors)))


def _blocked(
    build: CharacterBuildInput,
    *reasons: str,
    equipment_result: EquipmentAssemblyResult | None = None,
) -> CharacterBuildAssemblyResult:
    if equipment_result is not None and not isinstance(
        equipment_result,
        EquipmentAssemblyResult,
    ):
        raise TypeError("equipment_result must be EquipmentAssemblyResult or None")
    normalized = tuple(sorted(set(reason for reason in reasons if reason)))
    return CharacterBuildAssemblyResult(
        assembly_status="blocked",
        battle_admission_status="blocked",
        input_fingerprint=build.input_fingerprint,
        build_id=build.build_id,
        equipment_assembly_result=equipment_result,
        blocked_reasons=normalized or ("character_build_blocked_without_reason",),
    )


def _character_resource_bindings(
    profile: AvatarProfileIR,
) -> tuple[tuple[CharacterResourceBinding, ...], tuple[str, ...]]:
    if profile.resource_mode == "standard_energy":
        if profile.max_energy is None or profile.max_energy_source is None:
            return (), ("avatar_max_energy_source_missing",)
        if profile.special_resource_definition is not None:
            return (), ("standard_energy_profile_has_special_resource_definition",)
        return (), ()
    if profile.resource_mode != "special_resource":
        return (), (profile.blocked_reason or "avatar_resource_source_missing",)
    definition = profile.special_resource_definition
    if definition is None:
        return (), ("avatar_special_resource_definition_missing",)
    if definition.coverage_status != "executable":
        return (), (
            definition.blocked_reason or "avatar_special_resource_definition_not_executable",
        )
    if profile.max_energy is not None or profile.max_energy_source is not None:
        return (), ("special_resource_profile_cannot_carry_ordinary_energy",)
    if profile.special_resource_source != definition.source:
        return (), ("avatar_special_resource_source_definition_mismatch",)
    initializer = definition.initializer
    if initializer is None or initializer.coverage_status != "executable":
        return (), (
            initializer.blocked_reason
            if initializer is not None and initializer.blocked_reason
            else "avatar_special_resource_initializer_not_executable",
        )
    engine_bindings = tuple(
        special_resource_initializer_numeric_binding_source(
            expression,
            initializer.zero_floor_dynamic_hash,
        )
        for expression in (
            initializer.low_world_level_expression,
            initializer.high_world_level_expression,
        )
    )
    engine_errors = tuple(reason for source, reason in engine_bindings if source is None)
    if engine_errors:
        return (), tuple(sorted(set(engine_errors)))
    if engine_bindings[0][0] != engine_bindings[1][0]:
        return (), ("special_resource_initializer_engine_binding_conflict",)
    return (
        (
            CharacterResourceBinding(
                resource_definition_id=definition.resource_definition_id,
                current_property=definition.current_property,
                maximum_property=definition.maximum_property,
                current_resource_key=definition.current_resource_key,
                maximum_resource_key=definition.maximum_resource_key,
                initial_current_mode=definition.initial_current_mode,
                maximum_initialization_mode=definition.maximum_initialization_mode,
                initializer_task_names=definition.initializer_task_names,
                initializer=CharacterResourceInitializerBinding(
                    initializer_id=initializer.initializer_id,
                    maximum_value_dynamic_key=initializer.maximum_value_dynamic_key,
                    maximum_value_dynamic_hash=initializer.maximum_value_dynamic_hash,
                    level_dynamic_key=initializer.level_dynamic_key,
                    level_dynamic_hash=initializer.level_dynamic_hash,
                    zero_floor_dynamic_hash=initializer.zero_floor_dynamic_hash,
                    world_level_threshold=initializer.world_level_threshold,
                    low_world_level_expression=initializer.low_world_level_expression,
                    high_world_level_expression=initializer.high_world_level_expression,
                    minimum_expression=initializer.minimum_expression,
                    initial_current_expression=initializer.initial_current_expression,
                    initial_current_binding_hash=initializer.initial_current_binding_hash,
                    initial_current_binding_value=initializer.initial_current_binding_value,
                    level_source=initializer.level_source,
                    initial_current_trigger=initializer.initial_current_trigger,
                    sources=initializer.sources,
                    source=initializer.source,
                ),
                source=definition.source,
                supporting_sources=definition.supporting_sources,
            ),
        ),
        (),
    )


def _promotion_tier(
    tiers: tuple[AvatarPromotionTierIR, ...],
    requested_promotion: int,
    level: int,
) -> tuple[AvatarPromotionTierIR | None, tuple[str, ...]]:
    errors: list[str] = []
    promotions = [tier.promotion for tier in tiers]
    if len(set(promotions)) != len(promotions):
        errors.append("promotion_tier_duplicate_or_conflict")
    if not promotions or sorted(promotions) != list(range(max(promotions) + 1)):
        errors.append("promotion_tier_missing_or_non_contiguous")
    if any(tier.coverage_status != "executable" for tier in tiers):
        errors.append("promotion_tier_not_executable")
    if any(
        not tier.promotion_field_present
        and (
            tier.promotion != 0
            or tier.source.evidence.get("promotion_zero_semantic_from_missing_field") is not True
        )
        for tier in tiers
    ):
        errors.append("missing_promotion_field_without_zero_semantic_evidence")
    ordered = tuple(sorted(tiers, key=lambda tier: tier.promotion))
    if any(
        ordered[index].max_level >= ordered[index + 1].max_level
        for index in range(max(0, len(ordered) - 1))
    ):
        errors.append("promotion_max_levels_not_strictly_increasing")
    matched = tuple(tier for tier in tiers if tier.promotion == requested_promotion)
    if len(matched) != 1:
        errors.append("requested_promotion_tier_not_unique")
        return None, tuple(sorted(set(errors)))
    if errors:
        return None, tuple(sorted(set(errors)))
    tier = matched[0]
    # Promotion happens at the previous tier's level cap.  Both the capped
    # pre-promotion state and the promoted state therefore have the same
    # character level, but use different source-backed tier rows.
    minimum_level = 1 if requested_promotion == 0 else ordered[requested_promotion - 1].max_level
    if level < minimum_level or level > tier.max_level:
        errors.append("character_level_outside_promotion_tier")
    return tier, tuple(sorted(set(errors)))


def _selected_trace_nodes(
    rules: RuleBook,
    build: CharacterBuildInput,
) -> tuple[tuple[CharacterTraceNodeIR, ...], tuple[str, ...]]:
    card = rules.character_data_card(build.character_card_id)
    if card is None:
        return (), ("character_data_card_missing_during_trace_selection",)
    card_nodes = _current_card_trace_nodes(rules, card)
    by_id = {node.trace_node_id: node for node in card_nodes}
    errors: list[str] = []
    explicit: list[CharacterTraceNodeIR] = []
    for node_id in build.unlocked_trace_node_ids:
        node = rules.character_trace_node(node_id)
        if node is None:
            errors.append(f"unknown_trace_node:{node_id}")
        elif node.character_data_card_id != build.character_card_id:
            errors.append(f"trace_node_character_mismatch:{node_id}")
        elif by_id.get(node_id) is not node:
            errors.append(f"trace_node_version_or_rulebook_identity_mismatch:{node_id}")
        else:
            explicit.append(node)
    explicit_by_trace: dict[str, list[CharacterTraceNodeIR]] = {}
    for node in explicit:
        explicit_by_trace.setdefault(node.trace_id, []).append(node)
    if any(len(nodes) > 1 for nodes in explicit_by_trace.values()):
        errors.append("conflicting_trace_levels_selected")
    defaults: dict[str, CharacterTraceNodeIR] = {}
    for node in card_nodes:
        if node.default_unlocked:
            if node.trace_id in defaults and defaults[node.trace_id].trace_node_id != node.trace_node_id:
                errors.append("conflicting_default_trace_levels")
            defaults[node.trace_id] = node
    for trace_id, nodes in explicit_by_trace.items():
        default = defaults.get(trace_id)
        if default is None or len(nodes) != 1:
            continue
        selected = nodes[0]
        if selected.trace_node_id == default.trace_node_id:
            errors.append("default_trace_node_reselected")
        elif selected.level <= default.level:
            errors.append("explicit_trace_level_must_upgrade_default")
        elif selected.max_level != default.max_level or selected.level > selected.max_level:
            errors.append("explicit_trace_level_outside_logical_trace_range")
    selected = dict(defaults)
    for trace_id, nodes in explicit_by_trace.items():
        if len(nodes) == 1:
            selected[trace_id] = nodes[0]
    selected_trace_ids = set(selected)
    for node in selected.values():
        if node.coverage_status != "executable":
            errors.append(
                f"trace_node_not_executable:{node.trace_node_id}:"
                f"{node.blocked_reason or node.coverage_status}"
            )
        if (
            node.required_promotion is not None
            and build.promotion < node.required_promotion
        ):
            errors.append(
                f"trace_promotion_requirement_not_met:{node.trace_node_id}:"
                f"required:{node.required_promotion}:actual:{build.promotion}"
            )
        if (
            node.required_character_level is not None
            and build.level < node.required_character_level
        ):
            errors.append(
                f"trace_character_level_requirement_not_met:{node.trace_node_id}:"
                f"required:{node.required_character_level}:actual:{build.level}"
            )
        for prerequisite_trace_id in node.prerequisite_trace_ids:
            if prerequisite_trace_id not in selected_trace_ids:
                errors.append(
                    f"trace_prerequisite_not_unlocked:{node.trace_node_id}:"
                    f"required:{prerequisite_trace_id}"
                )
    return tuple(sorted(selected.values(), key=lambda node: node.trace_node_id)), tuple(sorted(set(errors)))


def _current_card_trace_nodes(
    rules: RuleBook,
    card: CharacterDataCardIR,
) -> tuple[CharacterTraceNodeIR, ...]:
    card_enhanced_id = card.source.evidence.get("enhanced_id")
    return tuple(
        node
        for node in rules.character_trace_nodes_for_card(card.card_id)
        if (
            node.source.evidence.get("enhanced_id") is None
            if card_enhanced_id is None
            else str(node.source.evidence.get("enhanced_id")) == str(card_enhanced_id)
        )
    )


def _selected_eidolon_slots(
    rules: RuleBook,
    card: CharacterDataCardIR,
    build: CharacterBuildInput,
) -> tuple[tuple[CharacterEidolonSlotIR, ...], tuple[str, ...]]:
    errors: list[str] = []
    if build.eidolon_level < 0 or build.eidolon_level > 6:
        return (), ("eidolon_level_outside_prefix_closed_range",)
    slots = rules.character_eidolon_slots_for_card(card.card_id)
    by_rank: dict[int, list[CharacterEidolonSlotIR]] = {}
    expected_avatar_id = card.entity_ref.removeprefix("avatar:")
    for slot in slots:
        by_rank.setdefault(slot.rank, []).append(slot)
        if (
            slot.character_data_card_id != build.character_card_id
            or slot.avatar_id != expected_avatar_id
        ):
            errors.append(
                f"eidolon_slot_character_identity_mismatch:{slot.eidolon_slot_id}"
            )
    if set(by_rank) != set(range(1, 7)):
        errors.append("eidolon_rank_catalog_not_prefix_complete")
    if any(len(values) != 1 for values in by_rank.values()):
        errors.append("eidolon_rank_catalog_duplicate_or_ambiguous")
    selected = tuple(
        by_rank[rank][0]
        for rank in range(1, build.eidolon_level + 1)
        if len(by_rank.get(rank, ())) == 1
    )
    if len(selected) != build.eidolon_level:
        errors.append("eidolon_prefix_selection_incomplete")
    if any(
        not slot.build_bindings
        and not rules.character_build_selector_relations_for_selection(
            slot.eidolon_slot_id
        )
        for slot in selected
    ):
        errors.append("selected_eidolon_slot_has_no_build_binding")
    return selected, tuple(sorted(set(errors)))


def _selected_build_bindings(
    rules: RuleBook,
    build: CharacterBuildInput,
    selected_nodes: tuple[CharacterTraceNodeIR, ...],
    selected_eidolons: tuple[CharacterEidolonSlotIR, ...],
) -> tuple[tuple[CharacterBuildBindingIR, ...], tuple[str, ...]]:
    errors: list[str] = []
    selections = (*selected_nodes, *selected_eidolons)
    bindings = tuple(
        binding
        for selection in selections
        for binding in selection.build_bindings
    )
    if any(
        not selection.build_bindings
        and not rules.character_build_selector_relations_for_selection(
            selection.trace_node_id
            if isinstance(selection, CharacterTraceNodeIR)
            else selection.eidolon_slot_id
        )
        for selection in selections
    ):
        errors.append("selected_character_content_has_no_build_binding")
    binding_ids = tuple(binding.build_binding_id for binding in bindings)
    if len(binding_ids) != len(set(binding_ids)):
        errors.append("selected_character_build_bindings_duplicate")
    selected_ids = {
        *(node.trace_node_id for node in selected_nodes),
        *(slot.eidolon_slot_id for slot in selected_eidolons),
    }
    for binding in bindings:
        canonical = rules.character_build_binding(binding.build_binding_id)
        mechanism_slot = rules.character_mechanism_slot(
            binding.mechanism_slot_id
        )
        if canonical is not binding:
            errors.append(
                f"character_build_binding_not_canonical:{binding.build_binding_id}"
            )
        if (
            binding.character_data_card_id != build.character_card_id
            or binding.selection_ref_id not in selected_ids
        ):
            errors.append(
                f"character_build_binding_selection_mismatch:{binding.build_binding_id}"
            )
        if (
            mechanism_slot is None
            or mechanism_slot.character_data_card_id != build.character_card_id
            or mechanism_slot.source != binding.source
        ):
            errors.append(
                f"character_build_binding_slot_mismatch:{binding.build_binding_id}"
            )
    return (
        tuple(sorted(bindings, key=lambda item: item.build_binding_id)),
        tuple(sorted(set(errors))),
    )


def _assemble_owned_combatants(
    rules: RuleBook,
    card: CharacterDataCardIR,
    build: CharacterBuildInput,
    selected_nodes: tuple[CharacterTraceNodeIR, ...],
    selected_bindings: tuple[CharacterBuildBindingIR, ...],
) -> tuple[
    tuple[OwnedCombatantBuildAssemblyResult, ...],
    tuple[CharacterMechanismDiagnostic, ...],
]:
    all_nodes = _current_card_trace_nodes(rules, card)
    auxiliary_skill_ids = tuple(
        sorted(
            {
                skill_id
                for node in all_nodes
                for skill_id in node.level_up_skill_ids
                if skill_id not in card.skill_ids
            }
        )
    )
    diagnostics: list[CharacterMechanismDiagnostic] = []
    definitions_by_id = {
        definition.servant_definition_id: definition
        for definition in rules.servant_definitions_for_owner(card.entity_ref)
    }
    for skill_id in auxiliary_skill_ids:
        candidates = rules.servant_definitions_for_owned_skill(card.entity_ref, skill_id)
        if len(candidates) != 1:
            diagnostics.append(
                CharacterMechanismDiagnostic(
                    diagnostic_id=(
                        "character_mechanism_diagnostic:owned_combatant_skill_owner:"
                        f"{skill_id}"
                    ),
                    mechanism_kind="owned_combatant_skill_ownership",
                    target_ref_id=skill_id,
                    reason=(
                        "owned_combatant_skill_owner_missing"
                        if not candidates
                        else "owned_combatant_skill_owner_ambiguous"
                    ),
                    source=card.source,
                )
            )
            continue
        definitions_by_id[candidates[0].servant_definition_id] = candidates[0]
    results = tuple(
        _assemble_owned_combatant_definition(
            rules,
            card,
            build,
            selected_bindings,
            definition,
        )
        for definition in sorted(
            definitions_by_id.values(),
            key=lambda item: item.servant_definition_id,
        )
    )
    return results, tuple(sorted(diagnostics, key=lambda item: item.diagnostic_id))


def _assemble_owned_combatant_definition(
    rules: RuleBook,
    card: CharacterDataCardIR,
    build: CharacterBuildInput,
    selected_bindings: tuple[CharacterBuildBindingIR, ...],
    definition: ServantDefinitionIR,
) -> OwnedCombatantBuildAssemblyResult:
    reasons: list[str] = []
    relation = definition.owner_relation_for(card.entity_ref)
    if relation is None or relation.owner_character_card_id != card.card_id:
        reasons.append("owned_combatant_owner_relation_missing_or_ambiguous")
        relation_id = f"unresolved:{definition.servant_definition_id}:{card.entity_ref}"
    else:
        relation_id = relation.owner_relation_id
    if definition.coverage_status != "executable":
        reasons.append(
            definition.blocked_reason
            or f"owned_combatant_definition_not_executable:{definition.coverage_status}"
        )

    stat_bindings, stat_reasons = _owned_combatant_stat_bindings(definition)
    reasons.extend(stat_reasons)
    skill_levels, action_bindings, skill_reasons = _owned_combatant_skill_levels(
        rules,
        card,
        selected_bindings,
        definition,
    )
    reasons.extend(skill_reasons)
    lifecycle_sources, lifecycle_source_reasons = _ir_sources_from_json_rows(
        definition.lifecycle_source.get("source_trace")
        if isinstance(definition.lifecycle_source, Mapping)
        else None,
        "owned_combatant_lifecycle_source",
    )
    reasons.extend(lifecycle_source_reasons)
    lifecycle_reasons: list[str] = []
    if relation is None:
        lifecycle_reasons.append("owned_combatant_owner_relation_missing_or_ambiguous")
    if not definition.spawn_sources:
        lifecycle_reasons.append("owned_combatant_spawn_source_missing")
    if definition.lifecycle_source.get("admission_status") != "executable":
        lifecycle_reasons.append(
            str(
                definition.lifecycle_source.get("blocked_reason")
                or "owned_combatant_lifecycle_source_blocked"
            )
        )
    if not lifecycle_sources:
        lifecycle_reasons.append("owned_combatant_lifecycle_source_missing")
    if not definition.birth_template_id:
        lifecycle_reasons.append("owned_combatant_birth_template_missing")
    lifecycle_reasons = list(dict.fromkeys(lifecycle_reasons))
    lifecycle = OwnedCombatantLifecycleAdmission(
        owner_relation_id=relation_id,
        birth_template_id=definition.birth_template_id
        or f"missing:{definition.servant_definition_id}",
        spawn_sources=definition.spawn_sources,
        lifecycle_sources=lifecycle_sources,
        admission_status="blocked" if lifecycle_reasons else "admitted",
        blocked_reason=";".join(lifecycle_reasons),
    )
    reasons.extend(lifecycle_reasons)
    reasons = list(dict.fromkeys(reason for reason in reasons if reason))
    admitted = not reasons
    return OwnedCombatantBuildAssemblyResult(
        assembly_status="assembled" if admitted else "blocked",
        battle_admission_status="admitted" if admitted else "blocked",
        owned_build_id=(
            f"owned_combatant_build:{build.build_id}:{definition.servant_definition_id}"
        ),
        parent_build_id=build.build_id,
        parent_input_fingerprint=build.input_fingerprint,
        owner_character_card_id=card.card_id,
        owner_entity_ref=card.entity_ref,
        servant_definition_id=definition.servant_definition_id,
        servant_ref=definition.servant_ref,
        owner_relation_id=relation_id,
        classified_skill_ids=definition.skill_ids,
        stat_bindings=stat_bindings,
        effective_skill_levels=skill_levels,
        action_bindings=action_bindings,
        mechanism_binding_ids=definition.ability_graph_ids,
        lifecycle_admission=lifecycle,
        blocked_reasons=tuple(reasons),
    )


def _owned_combatant_stat_bindings(
    definition: ServantDefinitionIR,
) -> tuple[tuple[OwnedCombatantStatBinding, ...], tuple[str, ...]]:
    components = definition.stat_source.get("components")
    if not isinstance(components, Mapping):
        return (), ("owned_combatant_stat_components_missing",)
    reasons: list[str] = []
    bindings: list[OwnedCombatantStatBinding] = []
    for property_type, owner_field, base_key, inherit_key in (
        ("max_hp", "max_hp", "hp_base", "hp_inherit"),
        ("speed", "speed", "speed_base", "speed_inherit"),
    ):
        base_component = components.get(base_key)
        inherit_component = components.get(inherit_key)
        if not isinstance(base_component, Mapping) or not isinstance(
            inherit_component,
            Mapping,
        ):
            reasons.append(f"owned_combatant_stat_component_missing:{property_type}")
            continue
        if (
            base_component.get("admission_status") != "executable"
            or inherit_component.get("admission_status") != "executable"
        ):
            reasons.append(f"owned_combatant_stat_component_blocked:{property_type}")
            continue
        try:
            offset = canonical_decimal(str(base_component.get("value")), base_key)
            scale = canonical_decimal(str(inherit_component.get("value")), inherit_key)
        except (TypeError, ValueError):
            reasons.append(f"owned_combatant_stat_value_invalid:{property_type}")
            continue
        sources, source_reasons = _ir_sources_from_json_rows(
            [
                *(base_component.get("source_trace") or ()),
                *(inherit_component.get("source_trace") or ()),
            ],
            f"owned_combatant_stat_source:{property_type}",
        )
        reasons.extend(source_reasons)
        if Decimal(offset) <= 0 and Decimal(scale) <= 0:
            reasons.append(f"owned_combatant_stat_formula_nonpositive:{property_type}")
        try:
            bindings.append(
                OwnedCombatantStatBinding(
                    property_type=property_type,
                    binding_kind="owner_linear",
                    owner_field=owner_field,
                    scale=scale,
                    offset=offset,
                    sources=sources,
                )
            )
        except (TypeError, ValueError) as exc:
            reasons.append(f"owned_combatant_stat_binding_invalid:{property_type}:{exc}")

    owner_sync_fields = definition.stat_source.get("owner_sync_fields")
    if not isinstance(owner_sync_fields, Mapping):
        reasons.append("owned_combatant_owner_sync_fields_missing")
        owner_sync_fields = {}
    for property_type, expected_kind, expected_owner_field in (
        ("attack", "owner_field", "attack"),
        ("defense", "owner_field", "defense"),
        ("critical_chance", "owner_resource", "critical_chance"),
        ("critical_damage", "owner_resource", "critical_damage"),
    ):
        source = owner_sync_fields.get(property_type)
        if not isinstance(source, Mapping):
            reasons.append(f"owned_combatant_owner_sync_source_missing:{property_type}")
            continue
        if (
            source.get("admission_status") != "executable"
            or source.get("binding_kind") != expected_kind
            or source.get("owner_field") != expected_owner_field
        ):
            reasons.append(
                str(
                    source.get("blocked_reason")
                    or f"owned_combatant_owner_sync_source_blocked:{property_type}"
                )
            )
            continue
        sources, source_reasons = _ir_sources_from_json_rows(
            source.get("source_trace"),
            f"owned_combatant_owner_sync_source:{property_type}",
        )
        reasons.extend(source_reasons)
        try:
            bindings.append(
                OwnedCombatantStatBinding(
                    property_type=property_type,
                    binding_kind=expected_kind,
                    owner_field=expected_owner_field,
                    scale=None,
                    offset=None,
                    sources=sources,
                )
            )
        except (TypeError, ValueError) as exc:
            reasons.append(f"owned_combatant_stat_binding_invalid:{property_type}:{exc}")

    aggro_component = components.get("base_aggro")
    if not isinstance(aggro_component, Mapping):
        reasons.append("owned_combatant_stat_component_missing:base_aggro")
    elif aggro_component.get("admission_status") != "executable":
        reasons.append("owned_combatant_stat_component_blocked:base_aggro")
    else:
        try:
            aggro_value = canonical_decimal(
                str(aggro_component.get("value")),
                "base_aggro",
            )
            aggro_sources, aggro_source_reasons = _ir_sources_from_json_rows(
                aggro_component.get("source_trace"),
                "owned_combatant_stat_source:base_aggro",
            )
            reasons.extend(aggro_source_reasons)
            if Decimal(aggro_value) <= 0:
                reasons.append("owned_combatant_stat_value_nonpositive:base_aggro")
            bindings.append(
                OwnedCombatantStatBinding(
                    property_type="base_aggro",
                    binding_kind="fixed",
                    owner_field="",
                    scale=None,
                    offset=None,
                    sources=aggro_sources,
                    exact_value=aggro_value,
                )
            )
        except (TypeError, ValueError) as exc:
            reasons.append(f"owned_combatant_stat_binding_invalid:base_aggro:{exc}")

    for property_type in ("energy", "max_energy"):
        bindings.append(
            OwnedCombatantStatBinding(
                property_type=property_type,
                binding_kind="inactive_schema_slot",
                owner_field="",
                scale=None,
                offset=None,
                sources=(),
            )
        )
    return tuple(bindings), tuple(dict.fromkeys(reasons))


def _owned_combatant_skill_levels(
    rules: RuleBook,
    card: CharacterDataCardIR,
    selected_bindings: tuple[CharacterBuildBindingIR, ...],
    definition: ServantDefinitionIR,
) -> tuple[
    tuple[CharacterSkillLevelResolution, ...],
    tuple[OwnedCombatantActionBinding, ...],
    tuple[str, ...],
]:
    reasons: list[str] = []
    selected_by_skill: dict[str, CharacterBuildBindingIR] = {}
    servant_skill_ids = set(definition.skill_ids)
    for binding in selected_bindings:
        if (
            binding.projection_kind != "skill_level_change"
            or binding.skill_level_change_kind != "base"
            or binding.target_ref_id not in servant_skill_ids
        ):
            continue
        skill_id = binding.target_ref_id
        if skill_id in selected_by_skill:
            reasons.append(f"owned_combatant_skill_level_source_not_unique:{skill_id}")
        else:
            selected_by_skill[skill_id] = binding

    bonus_sources_by_skill: dict[str, list[CharacterSkillLevelSource]] = {}
    for binding in selected_bindings:
        if (
            binding.projection_kind != "skill_level_change"
            or binding.skill_level_change_kind != "bonus"
            or binding.target_ref_id not in servant_skill_ids
        ):
            continue
        bonus_sources_by_skill.setdefault(binding.target_ref_id, []).append(
            CharacterSkillLevelSource(
                source_kind="eidolon_bonus",
                level_value=binding.skill_level_value,
                source_ref=BuildSourceRef(
                    "character_mechanism_slot",
                    binding.mechanism_slot_id,
                ),
                source=binding.source,
            )
        )

    action_entries: dict[str, Mapping[str, object]] = {}
    classified_required_action_skill_ids: set[str] = set()
    raw_skill_index_map = definition.action_set.get("skill_index_map")
    if isinstance(raw_skill_index_map, Mapping):
        for raw_entry in raw_skill_index_map.values():
            if not isinstance(raw_entry, Mapping):
                continue
            skill_id = str(raw_entry.get("skill_id") or "")
            action_id = str(raw_entry.get("action_ref") or "")
            if skill_id and action_id == f"servant_skill:{skill_id}":
                if skill_id in action_entries:
                    reasons.append(f"owned_combatant_action_entry_not_unique:{skill_id}")
                else:
                    action_entries[skill_id] = raw_entry
                    if raw_entry.get("servant_action_role") == "required_action":
                        classified_required_action_skill_ids.add(skill_id)
    raw_required_action_skill_ids = definition.action_set.get(
        "required_action_skill_ids"
    )
    if (
        not isinstance(raw_required_action_skill_ids, (list, tuple))
        or not all(
            isinstance(item, str) and item
            for item in raw_required_action_skill_ids
        )
    ):
        reasons.append("owned_combatant_required_action_skill_ids_missing_or_invalid")
        required_action_skill_ids = classified_required_action_skill_ids
    else:
        required_action_skill_ids = set(raw_required_action_skill_ids)
        if len(required_action_skill_ids) != len(raw_required_action_skill_ids):
            reasons.append("owned_combatant_required_action_skill_ids_duplicate")
        if required_action_skill_ids != classified_required_action_skill_ids:
            reasons.append("owned_combatant_required_action_classification_mismatch")
            required_action_skill_ids.update(classified_required_action_skill_ids)
    if not required_action_skill_ids:
        reasons.append("owned_combatant_required_action_slots_missing")

    resolutions: list[CharacterSkillLevelResolution] = []
    action_bindings: list[OwnedCombatantActionBinding] = []
    for skill_id in definition.skill_ids:
        action_id = f"servant_skill:{skill_id}"
        selected = selected_by_skill.get(skill_id)
        if selected is None:
            entry = action_entries.get(skill_id)
            raw_level = entry.get("default_level") if entry is not None else None
            if not isinstance(raw_level, int) or isinstance(raw_level, bool) or raw_level <= 0:
                reasons.append(f"owned_combatant_skill_level_source_missing:{skill_id}")
                continue
            base_level = raw_level
            base_definition_candidates = rules.action_definition_candidates(
                action_id,
                base_level,
            )
            if len(base_definition_candidates) != 1:
                reasons.append(f"owned_combatant_fixed_action_source_not_unique:{skill_id}")
                continue
            base_source = CharacterSkillLevelSource(
                source_kind="fixed_action",
                level_value=base_level,
                source_ref=BuildSourceRef(
                    "character_action_definition",
                    f"{action_id}:{base_level}",
                ),
                source=base_definition_candidates[0].source,
            )
        else:
            base_level = selected.skill_level_value
            base_source = CharacterSkillLevelSource(
                source_kind="trace_base",
                level_value=base_level,
                source_ref=BuildSourceRef(
                    "character_mechanism_slot",
                    selected.mechanism_slot_id,
                ),
                source=selected.source,
            )
        bonus_sources = tuple(bonus_sources_by_skill.get(skill_id, ()))
        bonus = sum(source.level_value for source in bonus_sources)
        effective_level = base_level + bonus
        definition_candidates = rules.action_definition_candidates(
            action_id,
            effective_level,
        )
        if len(definition_candidates) != 1:
            reasons.append(f"owned_combatant_action_definition_not_unique:{skill_id}:{effective_level}")
            continue
        action_definition = definition_candidates[0]
        if action_definition.coverage_status != "executable":
            reasons.append(f"owned_combatant_action_definition_not_executable:{skill_id}:{effective_level}")
            continue
        try:
            resolution = CharacterSkillLevelResolution(
                skill_id=skill_id,
                action_id=action_id,
                action_definition_id=action_definition.definition_id,
                action_record_source=action_definition.source,
                action_definition_source=action_definition.source,
                base_level=base_level,
                eidolon_level_bonus=bonus,
                effective_level=effective_level,
                sources=(base_source, *bonus_sources),
            )
        except (TypeError, ValueError) as exc:
            reasons.append(f"owned_combatant_skill_resolution_invalid:{skill_id}:{exc}")
            continue
        resolutions.append(resolution)
        if skill_id not in required_action_skill_ids:
            continue
        admissions = rules.action_admissions_for(
            definition.servant_ref,
            action_id,
            effective_level,
        )
        if len(admissions) != 1:
            reasons.append(
                f"owned_combatant_action_admission_not_unique:{skill_id}:{effective_level}"
            )
            continue
        admission = admissions[0]
        if admission.coverage_status != "executable":
            reasons.append(
                f"owned_combatant_action_admission_not_executable:{skill_id}:{effective_level}"
            )
            continue
        if admission.action_role != "turn_action":
            reasons.append(
                f"owned_combatant_required_action_role_mismatch:{skill_id}:{admission.action_role}"
            )
            continue
        ability_binding = rules.action_ability_binding(action_id, effective_level)
        if ability_binding is None or ability_binding.coverage_status != "executable":
            reasons.append(
                f"owned_combatant_action_ability_binding_not_executable:{skill_id}:{effective_level}"
            )
            continue
        action_bindings.append(
            OwnedCombatantActionBinding(
                skill_id=skill_id,
                action_id=action_id,
                effective_level=effective_level,
                action_definition_id=action_definition.definition_id,
                ability_binding_id=ability_binding.binding_id,
                action_source=action_definition.source,
                ability_binding_source=ability_binding.source,
            )
        )
    bound_required_skill_ids = {binding.skill_id for binding in action_bindings}
    missing_required_skill_ids = sorted(
        required_action_skill_ids.difference(bound_required_skill_ids)
    )
    if missing_required_skill_ids:
        reasons.append(
            "owned_combatant_required_action_bindings_incomplete:"
            + ",".join(missing_required_skill_ids)
        )
    return (
        tuple(resolutions),
        tuple(action_bindings),
        tuple(dict.fromkeys(reasons)),
    )


def _ir_sources_from_json_rows(
    raw_sources: object,
    field_name: str,
) -> tuple[tuple[IRSource, ...], tuple[str, ...]]:
    if not isinstance(raw_sources, (list, tuple)):
        return (), (f"{field_name}_missing",)
    sources = []
    reasons: list[str] = []
    for index, raw_source in enumerate(raw_sources):
        try:
            sources.append(ir_source_from_json(raw_source, f"{field_name}[{index}]"))
        except (TypeError, ValueError):
            reasons.append(f"{field_name}_invalid:{index}")
    return tuple(sources), tuple(reasons)


def _resolve_effective_skill_levels(
    rules: RuleBook,
    card: CharacterDataCardIR,
    build: CharacterBuildInput,
    selected_nodes: tuple[CharacterTraceNodeIR, ...],
    selected_eidolons: tuple[CharacterEidolonSlotIR, ...],
    selected_bindings: tuple[CharacterBuildBindingIR, ...],
) -> tuple[
    tuple[CharacterSkillLevelResolution, ...],
    tuple[CharacterMechanismDiagnostic, ...],
    tuple[str, ...],
]:
    errors: list[str] = []
    diagnostics: list[CharacterMechanismDiagnostic] = []
    if len(set(card.skill_ids)) != len(card.skill_ids):
        errors.append("character_card_skill_ids_duplicate")
    card_skill_ids = set(card.skill_ids)
    raw_actions = card.action_set.get("actions")
    if not isinstance(raw_actions, (list, tuple)):
        return (), (), ("character_card_action_set_missing",)
    actions_by_skill: dict[str, list[Mapping[str, object]]] = {}
    for position, raw_action in enumerate(raw_actions):
        if not isinstance(raw_action, Mapping):
            errors.append(f"character_card_action_entry_not_object:{position}")
            continue
        skill_id = raw_action.get("raw_skill_id")
        action_id = raw_action.get("action_id")
        level = raw_action.get("level")
        if (
            not isinstance(skill_id, str)
            or not skill_id
            or not isinstance(action_id, str)
            or action_id != f"avatar_skill:{skill_id}"
            or not isinstance(level, int)
            or isinstance(level, bool)
            or level <= 0
        ):
            errors.append(f"character_card_action_entry_invalid:{position}")
            continue
        if skill_id not in card_skill_ids:
            errors.append(f"character_card_action_skill_identity_mismatch:{skill_id}")
            continue
        actions_by_skill.setdefault(skill_id, []).append(raw_action)

    all_nodes = _current_card_trace_nodes(rules, card)
    traced_skill_ids = {
        binding.target_ref_id
        for node in all_nodes
        for binding in node.build_bindings
        if binding.projection_kind == "skill_level_change"
        and binding.skill_level_change_kind == "base"
        and binding.target_ref_id in card_skill_ids
    }
    selected_trace_ids = {node.trace_node_id for node in selected_nodes}
    selected_eidolon_ids = {
        slot.eidolon_slot_id for slot in selected_eidolons
    }
    selected_by_skill: dict[str, CharacterBuildBindingIR] = {}
    for binding in selected_bindings:
        if (
            binding.projection_kind != "skill_level_change"
            or binding.skill_level_change_kind != "base"
        ):
            continue
        if (
            binding.selection_kind != "trace"
            or binding.selection_ref_id not in selected_trace_ids
        ):
            errors.append(
                f"trace_skill_level_binding_selection_mismatch:{binding.build_binding_id}"
            )
            continue
        skill_id = binding.target_ref_id
        if skill_id not in card_skill_ids:
            continue
        if skill_id in selected_by_skill:
            errors.append(f"skill_level_resolved_by_multiple_trace_nodes:{skill_id}")
        else:
            selected_by_skill[skill_id] = binding

    bonus_sources_by_skill: dict[str, list[CharacterSkillLevelSource]] = {}
    for binding in selected_bindings:
        if (
            binding.projection_kind != "skill_level_change"
            or binding.skill_level_change_kind != "bonus"
        ):
            continue
        if (
            binding.selection_kind != "eidolon"
            or binding.selection_ref_id not in selected_eidolon_ids
        ):
            errors.append(
                f"eidolon_skill_level_binding_selection_mismatch:{binding.build_binding_id}"
            )
            continue
        skill_id = binding.target_ref_id
        if skill_id not in card_skill_ids:
            continue
        bonus_sources_by_skill.setdefault(skill_id, []).append(
            CharacterSkillLevelSource(
                source_kind="eidolon_bonus",
                level_value=binding.skill_level_value,
                source_ref=BuildSourceRef(
                    "character_mechanism_slot",
                    binding.mechanism_slot_id,
                ),
                source=binding.source,
            )
        )

    resolutions: list[CharacterSkillLevelResolution] = []
    for skill_id in card.skill_ids:
        action_id = f"avatar_skill:{skill_id}"
        action_entries = actions_by_skill.get(skill_id, [])
        action_entry_levels = [
            entry.get("level")
            for entry in action_entries
            if isinstance(entry.get("level"), int)
            and not isinstance(entry.get("level"), bool)
        ]
        if len(set(action_entry_levels)) != len(action_entry_levels):
            errors.append(f"character_card_action_level_duplicate_or_conflict:{action_id}")
            continue
        known_levels = {
            entry["level"]
            for entry in action_entries
            if isinstance(entry.get("level"), int) and not isinstance(entry.get("level"), bool)
        }
        base_source: CharacterSkillLevelSource | None = None
        selected = selected_by_skill.get(skill_id)
        if selected is not None:
            base_level = selected.skill_level_value
            base_source = CharacterSkillLevelSource(
                source_kind="trace_base",
                level_value=base_level,
                source_ref=BuildSourceRef(
                    "character_mechanism_slot",
                    selected.mechanism_slot_id,
                ),
                source=selected.source,
            )
        elif skill_id in traced_skill_ids:
            errors.append(f"trace_skill_level_not_selected:{skill_id}")
            continue
        elif len(known_levels) == 1:
            base_level = next(iter(known_levels))
            matching_entries = tuple(
                entry for entry in action_entries if entry.get("level") == base_level
            )
            source_trace = matching_entries[0].get("source_trace") if len(matching_entries) == 1 else None
            try:
                source = ir_source_from_json(source_trace, "action_source_trace")
            except (TypeError, ValueError):
                errors.append(f"fixed_action_level_source_invalid:{action_id}:{base_level}")
                continue
            base_source = CharacterSkillLevelSource(
                source_kind="fixed_action",
                level_value=base_level,
                source_ref=BuildSourceRef(
                    "character_action_definition",
                    f"{action_id}:{base_level}",
                ),
                source=source,
            )
        else:
            diagnostics.append(
                CharacterMechanismDiagnostic(
                    diagnostic_id=f"character_mechanism_diagnostic:skill_level_source:{skill_id}",
                    mechanism_kind="skill_level",
                    target_ref_id=action_id,
                    reason="skill_level_source_missing_or_ambiguous",
                    source=card.source,
                )
            )
            continue
        bonus_sources = tuple(bonus_sources_by_skill.get(skill_id, ()))
        bonus = sum(item.level_value for item in bonus_sources)
        effective_level = base_level + bonus
        if effective_level not in known_levels:
            diagnostics.append(
                CharacterMechanismDiagnostic(
                    diagnostic_id=f"character_mechanism_diagnostic:skill_level:{skill_id}",
                    mechanism_kind="skill_level",
                    target_ref_id=action_id,
                    reason="effective_skill_level_action_definition_missing",
                    source=base_source.source,
                )
            )
            continue
        definition_candidates = rules.action_definition_candidates(action_id, effective_level)
        if len(definition_candidates) != 1:
            diagnostics.append(
                CharacterMechanismDiagnostic(
                    diagnostic_id=f"character_mechanism_diagnostic:action_definition:{skill_id}",
                    mechanism_kind="skill_level",
                    target_ref_id=f"{action_id}:{effective_level}",
                    reason=(
                        "effective_skill_level_action_definition_missing"
                        if not definition_candidates
                        else "effective_skill_level_action_definition_not_unique"
                    ),
                    source=base_source.source,
                )
            )
            continue
        definition = definition_candidates[0]
        if definition.coverage_status != "executable":
            diagnostics.append(
                CharacterMechanismDiagnostic(
                    diagnostic_id=f"character_mechanism_diagnostic:action_definition:{skill_id}",
                    mechanism_kind="skill_level",
                    target_ref_id=definition.definition_id,
                    reason=(
                        "effective_skill_level_action_definition_not_executable:"
                        f"{definition.coverage_status}"
                    ),
                    source=definition.source,
                )
            )
            continue
        matching_effective_entries = tuple(
            entry for entry in action_entries if entry.get("level") == effective_level
        )
        if len(matching_effective_entries) != 1:
            diagnostics.append(
                CharacterMechanismDiagnostic(
                    diagnostic_id=f"character_mechanism_diagnostic:action_record:{skill_id}",
                    mechanism_kind="skill_level",
                    target_ref_id=f"{action_id}:{effective_level}",
                    reason="effective_skill_level_action_record_not_unique",
                    source=base_source.source,
                )
            )
            continue
        try:
            action_record_source = ir_source_from_json(
                matching_effective_entries[0].get("source_trace"),
                "effective_skill_level_action_record_source",
            )
        except (TypeError, ValueError):
            diagnostics.append(
                CharacterMechanismDiagnostic(
                    diagnostic_id=f"character_mechanism_diagnostic:action_record:{skill_id}",
                    mechanism_kind="skill_level",
                    target_ref_id=f"{action_id}:{effective_level}",
                    reason="effective_skill_level_action_record_source_invalid",
                    source=base_source.source,
                )
            )
            continue
        try:
            same_raw_row = same_ir_source_raw_row(
                action_record_source,
                definition.source,
                expected_level=effective_level,
            )
        except (TypeError, ValueError):
            diagnostics.append(
                CharacterMechanismDiagnostic(
                    diagnostic_id=f"character_mechanism_diagnostic:action_definition:{skill_id}",
                    mechanism_kind="skill_level",
                    target_ref_id=definition.definition_id,
                    reason="effective_skill_level_action_raw_row_identity_invalid",
                    source=definition.source,
                )
            )
            continue
        if not same_raw_row:
            diagnostics.append(
                CharacterMechanismDiagnostic(
                    diagnostic_id=f"character_mechanism_diagnostic:action_definition:{skill_id}",
                    mechanism_kind="skill_level",
                    target_ref_id=definition.definition_id,
                    reason="effective_skill_level_action_definition_raw_row_mismatch",
                    source=definition.source,
                )
            )
            continue
        try:
            resolution = CharacterSkillLevelResolution(
                skill_id=skill_id,
                action_id=action_id,
                action_definition_id=definition.definition_id,
                action_record_source=action_record_source,
                action_definition_source=definition.source,
                base_level=base_level,
                eidolon_level_bonus=bonus,
                effective_level=effective_level,
                sources=(base_source, *bonus_sources),
            )
        except (TypeError, ValueError):
            diagnostics.append(
                CharacterMechanismDiagnostic(
                    diagnostic_id=f"character_mechanism_diagnostic:action_definition:{skill_id}",
                    mechanism_kind="skill_level",
                    target_ref_id=f"{action_id}:{effective_level}",
                    reason="effective_skill_level_action_definition_source_invalid",
                    source=base_source.source,
                )
            )
            continue
        resolutions.append(resolution)
    return (
        tuple(sorted(resolutions, key=lambda item: item.action_id)),
        tuple(sorted(diagnostics, key=lambda item: item.diagnostic_id)),
        tuple(sorted(set(errors))),
    )


def _base_contributions(tier: AvatarPromotionTierIR, level: int) -> list[StaticStatContribution]:
    contributions: list[StaticStatContribution] = []
    source_ref = BuildSourceRef("avatar_promotion_tier", tier.promotion_tier_id)
    linear_fields = (
        ("max_hp", tier.hp_base, tier.hp_add),
        ("attack", tier.attack_base, tier.attack_add),
        ("defense", tier.defense_base, tier.defense_add),
    )
    for property_type, base_value, per_level in linear_fields:
        calculation = StatCalculation("linear_growth", base_value, per_level, level - 1)
        contributions.append(
            StaticStatContribution(
                contribution_id=f"character_base:{tier.promotion_tier_id}:{property_type}",
                contribution_pool="base",
                property_type=property_type,
                exact_value=calculation.exact_value,
                source_ref=source_ref,
                calculation=calculation,
                source=tier.source,
            )
        )
    for property_type, exact_value, pool, calculation_kind in (
        ("speed", tier.speed_base, "base", "constant"),
        ("critical_chance", tier.critical_chance, "resource", "resource"),
        ("critical_damage", tier.critical_damage, "resource", "resource"),
        ("base_aggro", tier.base_aggro, "resource", "resource"),
    ):
        calculation = StatCalculation(calculation_kind, exact_value)  # type: ignore[arg-type]
        contributions.append(
            StaticStatContribution(
                contribution_id=f"character_base:{tier.promotion_tier_id}:{property_type}",
                contribution_pool=pool,  # type: ignore[arg-type]
                property_type=property_type,
                exact_value=calculation.exact_value,
                source_ref=source_ref,
                calculation=calculation,
                source=tier.source,
            )
        )
    return contributions


def _character_build_binding_contribution(
    binding: CharacterBuildBindingIR,
) -> tuple[StaticStatContribution | None, str]:
    if binding.projection_kind not in {
        "static_contribution",
        "resource_contribution",
    }:
        return None, (
            f"character_build_binding_not_contribution:{binding.build_binding_id}"
        )
    channel = contribution_channel_for_application_kind(binding.application_kind)
    if channel is None:
        return None, (
            f"character_build_contribution_channel_missing:{binding.build_binding_id}"
        )
    pool, calculation_kind = channel
    if (pool == "resource") != (
        binding.projection_kind == "resource_contribution"
    ):
        return None, (
            f"character_build_contribution_channel_mismatch:{binding.build_binding_id}"
        )
    calculation = StatCalculation(calculation_kind, binding.exact_value)
    return (
        StaticStatContribution(
            contribution_id=f"character_build:{binding.build_binding_id}",
            contribution_pool=pool,
            property_type=binding.property_type,
            exact_value=calculation.exact_value,
            source_ref=BuildSourceRef(
                "character_mechanism_slot",
                binding.mechanism_slot_id,
            ),
            calculation=calculation,
            source=binding.source,
        ),
        "",
    )


@dataclass
class _CharacterDynamicRootDraft:
    root_kind: str
    root_ref_id: str
    character_card_id: str
    source_graph_ref_id: str
    source_graph_id: str
    ability_definition_id: str
    ability_name: str
    root_source: IRSource
    source_fingerprint: str
    build_binding_ids: set[str] = field(default_factory=set)
    specialization_ids: set[str] = field(default_factory=set)

    @property
    def identity(self) -> tuple[str, ...]:
        return (
            self.character_card_id,
            self.source_graph_ref_id,
            self.source_graph_id,
            self.root_kind,
            self.root_ref_id,
            self.ability_definition_id,
            self.source_fingerprint,
        )

    @property
    def dynamic_graph_ref_id(self) -> str:
        return (
            f"character_dynamic_graph_ref:{self.character_card_id}:"
            f"{self.source_graph_id}:{self.root_kind}:{self.root_ref_id}:"
            f"{self.source_fingerprint}"
        )

    def materialize(self) -> CharacterDynamicGraphRef:
        return CharacterDynamicGraphRef(
            dynamic_graph_ref_id=self.dynamic_graph_ref_id,
            root_kind=self.root_kind,  # type: ignore[arg-type]
            root_ref_id=self.root_ref_id,
            character_card_id=self.character_card_id,
            source_graph_ref_id=self.source_graph_ref_id,
            source_graph_id=self.source_graph_id,
            ability_definition_id=self.ability_definition_id,
            ability_name=self.ability_name,
            build_binding_ids=tuple(sorted(self.build_binding_ids)),
            specialization_ids=tuple(sorted(self.specialization_ids)),
            root_source=self.root_source,
            blocked_reason=(
                "character_dynamic_graph_runtime_semantics_pending_p9_s4_s17"
            ),
        )


def _dynamic_root_draft(
    *,
    root_kind: str,
    root_ref_id: str,
    character_card_id: str,
    source_graph_ref_id: str,
    source_graph_id: str,
    ability_definition_id: str,
    ability_name: str,
    root_source: IRSource,
) -> _CharacterDynamicRootDraft:
    return _CharacterDynamicRootDraft(
        root_kind=root_kind,
        root_ref_id=root_ref_id,
        character_card_id=character_card_id,
        source_graph_ref_id=source_graph_ref_id,
        source_graph_id=source_graph_id,
        ability_definition_id=ability_definition_id,
        ability_name=ability_name,
        root_source=root_source,
        source_fingerprint=canonical_json_fingerprint(root_source.to_json()),
    )


def _direct_dynamic_root_draft(
    rules: RuleBook,
    binding: CharacterBuildBindingIR,
) -> tuple[_CharacterDynamicRootDraft | None, str]:
    card = rules.character_data_card(binding.character_data_card_id)
    graph_ref = next(
        (
            ref
            for ref in card.ability_source_graph_refs
            if ref.graph_ref_id == binding.source_graph_ref_id
        ),
        None,
    ) if card is not None else None
    source_graph = rules.character_ability_source_graph(binding.source_graph_id)
    ability_binding = rules.character_ability_binding(binding.ability_binding_id)
    definition = rules.character_ability_definition(binding.ability_definition_id)
    if (
        binding.projection_kind != "dynamic_graph_ref"
        or binding.dynamic_ref_kind != "direct_ability"
        or card is None
        or graph_ref is None
        or graph_ref.graph_id != binding.source_graph_id
        or source_graph is None
        or ability_binding is None
        or definition is None
        or binding.relation_source is None
        or binding.definition_source is None
        or ability_binding.graph_id != source_graph.graph_id
        or ability_binding.ability_definition_id != definition.definition_id
        or ability_binding.ability_name != binding.target_ref_id
        or definition.ability_name != binding.target_ref_id
        or ability_binding.relation_source != binding.relation_source
        or definition.source != binding.definition_source
    ):
        return None, (
            f"direct_character_dynamic_graph_not_source_closed:"
            f"{binding.build_binding_id}"
        )
    draft = _dynamic_root_draft(
        root_kind="ability_definition",
        root_ref_id=definition.definition_id,
        character_card_id=binding.character_data_card_id,
        source_graph_ref_id=binding.source_graph_ref_id,
        source_graph_id=binding.source_graph_id,
        ability_definition_id=definition.definition_id,
        ability_name=definition.ability_name,
        root_source=definition.source,
    )
    draft.build_binding_ids.add(binding.build_binding_id)
    return draft, ""


def _selector_dynamic_root_draft(
    rules: RuleBook,
    relation: CharacterBuildSelectorRelationIR,
) -> tuple[_CharacterDynamicRootDraft | None, str]:
    card = rules.character_data_card(relation.character_data_card_id)
    graph_ref = next(
        (
            ref
            for ref in card.ability_source_graph_refs
            if ref.graph_ref_id == relation.source_graph_ref_id
        ),
        None,
    ) if card is not None else None
    source_graph = rules.character_ability_source_graph(relation.source_graph_id)
    source = rules.character_ability_source(relation.source_id)
    if (
        card is None
        or graph_ref is None
        or graph_ref.graph_id != relation.source_graph_id
        or source_graph is None
        or source_graph.source_id != relation.source_id
        or source is None
        or source.source.source_path != relation.selector_source.source_path
        or source.content_sha256 != relation.source_content_sha256
    ):
        return None, (
            f"selector_dynamic_graph_not_source_closed:"
            f"{relation.selector_relation_id}"
        )
    if relation.location_kind == "ability_definition":
        definition = rules.character_ability_definition(
            relation.ability_definition_id
        )
        if (
            definition is None
            or definition.definition_id not in source_graph.definition_ids
            or definition.source_id != relation.source_id
            or definition.ability_name != relation.ability_name
            or definition.source != relation.ability_definition_source
        ):
            return None, (
                f"selector_dynamic_definition_not_source_closed:"
                f"{relation.selector_relation_id}"
            )
        return (
            _dynamic_root_draft(
                root_kind="ability_definition",
                root_ref_id=definition.definition_id,
                character_card_id=relation.character_data_card_id,
                source_graph_ref_id=relation.source_graph_ref_id,
                source_graph_id=relation.source_graph_id,
                ability_definition_id=definition.definition_id,
                ability_name=definition.ability_name,
                root_source=definition.source,
            ),
            "",
        )
    return (
        _dynamic_root_draft(
            root_kind="source_graph",
            root_ref_id=source.source_id,
            character_card_id=relation.character_data_card_id,
            source_graph_ref_id=relation.source_graph_ref_id,
            source_graph_id=relation.source_graph_id,
            ability_definition_id="",
            ability_name="",
            root_source=source.source,
        ),
        "",
    )


def _assemble_character_dynamic_roots(
    rules: RuleBook,
    card: CharacterDataCardIR,
    selected_nodes: tuple[CharacterTraceNodeIR, ...],
    selected_eidolons: tuple[CharacterEidolonSlotIR, ...],
    direct_bindings: tuple[CharacterBuildBindingIR, ...],
) -> tuple[
    tuple[CharacterDynamicGraphRef, ...],
    tuple[CharacterSelectorSpecialization, ...],
    tuple[str, ...],
]:
    roots: dict[tuple[str, ...], _CharacterDynamicRootDraft] = {}
    errors: list[str] = []
    for binding in direct_bindings:
        draft, error = _direct_dynamic_root_draft(rules, binding)
        if draft is None:
            errors.append(error or "direct_character_dynamic_root_missing")
            continue
        existing = roots.setdefault(draft.identity, draft)
        existing.build_binding_ids.update(draft.build_binding_ids)

    selected_ids = {
        *(node.trace_node_id for node in selected_nodes),
        *(slot.eidolon_slot_id for slot in selected_eidolons),
    }
    decisions: list[
        tuple[
            CharacterBuildSelectorRelationIR,
            _CharacterDynamicRootDraft,
            bool,
            bool,
            str,
        ]
    ] = []
    for relation in rules.character_build_selector_relations_for_card(card.card_id):
        draft, error = _selector_dynamic_root_draft(rules, relation)
        if draft is None:
            errors.append(error or "selector_dynamic_root_missing")
            continue
        selection_matched = bool(
            selected_ids.intersection(relation.selection_ref_ids)
        )
        predicate_value = (
            relation.selector_value_when_selected
            if selection_matched
            else not relation.selector_value_when_selected
        )
        selected_subtree_path = (
            relation.true_subtree_path
            if predicate_value
            else relation.false_subtree_path
        )
        if selected_subtree_path:
            roots.setdefault(draft.identity, draft)
        decisions.append(
            (
                relation,
                draft,
                selection_matched,
                predicate_value,
                selected_subtree_path,
            )
        )
    if errors:
        return (), (), tuple(sorted(set(errors)))

    specializations: list[CharacterSelectorSpecialization] = []
    for relation, draft, selection_matched, predicate_value, subtree_path in decisions:
        parent = roots.get(draft.identity)
        specialization_id = (
            f"character_selector_specialization:{relation.selector_relation_id}"
        )
        specialization = CharacterSelectorSpecialization(
            specialization_id=specialization_id,
            selector_relation_id=relation.selector_relation_id,
            character_card_id=relation.character_data_card_id,
            selection_kind=relation.selection_kind,
            logical_selection_id=relation.logical_selection_id,
            selection_ref_ids=relation.selection_ref_ids,
            selection_matched=selection_matched,
            predicate_value=predicate_value,
            branch_kind=relation.branch_kind,
            branch_root_path=relation.branch_root_path,
            selected_subtree_path=subtree_path,
            parent_dynamic_graph_ref_id=(
                parent.dynamic_graph_ref_id if parent is not None else ""
            ),
            context_scope_record_ids=tuple(
                context.scope_record_id for context in relation.context_refs
            ),
            selector_source=relation.selector_source,
        )
        specializations.append(specialization)
        if parent is not None:
            parent.specialization_ids.add(specialization_id)
    return (
        tuple(
            roots[key].materialize()
            for key in sorted(roots)
        ),
        tuple(sorted(specializations, key=lambda item: item.specialization_id)),
        (),
    )


def _panel_from_aggregates(
    aggregates: tuple[StaticStatAggregate, ...],
    *,
    resource_mode: str,
    resource_bindings: tuple[CharacterResourceBinding, ...],
) -> CharacterBasePanel:
    final = {
        aggregate.property_type: Decimal(aggregate.final_value)
        for aggregate in aggregates
    }
    required = set(_PANEL_PRIMARY_PROPERTIES)
    if resource_mode == "special_resource":
        required.remove("max_energy")
        if "max_energy" in final:
            raise ValueError("special-resource panel cannot include ordinary max_energy")
    missing = sorted(required.difference(final))
    if missing:
        raise ValueError(f"character base panel properties missing: {missing}")
    additional = tuple(
        CharacterPanelResource(property_type, str(value))
        for property_type, value in sorted(final.items())
        if property_type not in _PANEL_PRIMARY_PROPERTIES
    )
    return CharacterBasePanel(
        max_hp=str(final["max_hp"]),
        attack=str(final["attack"]),
        defense=str(final["defense"]),
        speed=str(final["speed"]),
        max_energy=(
            str(final["max_energy"])
            if resource_mode == "standard_energy"
            else None
        ),
        critical_chance=str(final["critical_chance"]),
        critical_damage=str(final["critical_damage"]),
        base_aggro=str(final["base_aggro"]),
        additional_resources=additional,
        resource_mode=resource_mode,  # type: ignore[arg-type]
        special_resource_binding=(
            resource_bindings[0]
            if resource_mode == "special_resource" and len(resource_bindings) == 1
            else None
        ),
    )
