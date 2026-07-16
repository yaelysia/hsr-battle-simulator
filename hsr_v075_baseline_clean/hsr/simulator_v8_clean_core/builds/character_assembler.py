from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from ..build_types import (
    BuildSourceRef,
    StatCalculation,
    StaticStatContribution,
    ir_source_from_json,
)
from ..equipment.models import EquipmentAssemblyResult
from ..ir_types import same_ir_source_raw_row
from ..rules.ir import (
    AvatarPromotionTierIR,
    CharacterDataCardIR,
    CharacterMechanismSlotIR,
    CharacterTraceNodeIR,
)
from ..rules.rulebook import RuleBook
from .models import (
    CharacterBasePanel,
    CharacterBuildAssemblyResult,
    CharacterBuildInput,
    CharacterMechanismDiagnostic,
    CharacterMechanismRef,
    CharacterPanelResource,
    CharacterSkillLevelResolution,
    CharacterSkillLevelSource,
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
_BASE_POOL_PROPERTIES = {"max_hp", "attack", "defense", "speed", "max_energy"}
_RESOURCE_POOL_PROPERTIES = {"critical_chance", "critical_damage", "base_aggro"}


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
    if profile.max_energy is None or profile.max_energy_source is None:
        return _blocked(build, profile.blocked_reason or "avatar_max_energy_source_missing")

    selected_nodes, trace_errors = _selected_trace_nodes(rules, build)
    if trace_errors:
        return _blocked(build, *trace_errors)
    skill_levels, skill_level_diagnostics, skill_level_errors = _resolve_effective_skill_levels(
        rules,
        card,
        build,
        selected_nodes,
    )
    if skill_level_errors:
        return _blocked(build, *skill_level_errors)

    contributions = _base_contributions(tier, build.level)
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
    admitted_refs: list[CharacterMechanismRef] = []
    for node in selected_nodes:
        if not node.linked_mechanism_slot_ids:
            diagnostics.append(
                CharacterMechanismDiagnostic(
                    diagnostic_id=f"character_mechanism_diagnostic:{node.trace_node_id}:unbound",
                    mechanism_kind="trace_node_unbound",
                    target_ref_id=node.trace_node_id,
                    reason="trace_node_has_no_structured_effect_source",
                    source=node.source,
                )
            )
        for slot_id in node.linked_mechanism_slot_ids:
            slot = rules.character_mechanism_slot(slot_id)
            if slot is None or slot.character_data_card_id != build.character_card_id:
                return _blocked(build, f"trace_linked_mechanism_slot_missing_or_wrong_card:{slot_id}")
            if slot.mechanism_kind == "trace_static_stat_bonus":
                contribution_result, error = _trace_static_contributions(node, slot)
                if error:
                    return _blocked(build, error)
                contributions.extend(contribution_result)
            elif slot.mechanism_kind == "trace_ability_hook":
                mechanism_ref, diagnostic = _trace_dynamic_ref(rules, build, node, slot)
                if mechanism_ref is not None:
                    admitted_refs.append(mechanism_ref)
                if diagnostic is not None:
                    diagnostics.append(diagnostic)
            elif slot.mechanism_kind == "trace_skill_level":
                # The typed effective-skill-level channel above is the sole
                # consumer.  It is not a dynamic mechanism payload.
                continue
            else:
                diagnostics.append(
                    CharacterMechanismDiagnostic(
                        diagnostic_id=f"character_mechanism_diagnostic:{slot.mechanism_slot_id}",
                        mechanism_kind=slot.mechanism_kind,
                        target_ref_id=slot.mechanism_slot_id,
                        reason=slot.blocked_reason or "trace_mechanism_kind_not_admitted",
                        source=slot.source,
                    )
                )

    eidolon_refs, eidolon_diagnostics = _eidolon_mechanisms(rules, build)
    admitted_refs.extend(eidolon_refs)
    diagnostics.extend(eidolon_diagnostics)
    try:
        panel = _panel_from_ledger(contributions)
        return CharacterBuildAssemblyResult(
            assembly_status="assembled",
            battle_admission_status=(
                "blocked"
                if diagnostics
                or equipment_result.battle_admission_status == "blocked"
                else "admitted"
            ),
            input_fingerprint=build.input_fingerprint,
            equipment_assembly_result=equipment_result,
            base_panel=panel,
            contribution_ledger=tuple(contributions),
            effective_skill_levels=tuple(skill_levels),
            admitted_dynamic_mechanism_refs=tuple(admitted_refs),
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
            tier_sources = (
                tuple(
                    value.source
                    for tier in resolution.value.promotion_tiers
                    if instance is not None
                    and tier.promotion_stage == instance.promotion
                    for value in tier.stat_values
                )
                if resolution.resolution_status == "resolved"
                and resolution.value is not None
                else ()
            )
            if (
                instance is None
                or instance.definition_key.definition_identity
                != contribution.source_ref.definition_identity
                or contribution.source not in tier_sources
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
    for mechanism in result.admitted_dynamic_mechanism_refs:
        slot = rules.character_mechanism_slot(mechanism.source_ref.definition_identity)
        if (
            slot is None
            or slot.character_data_card_id != build.character_card_id
            or slot.source != mechanism.source
            or slot.coverage_status != "executable"
        ):
            errors.append(f"mechanism_source_not_resolvable:{mechanism.mechanism_ref_id}")
            continue
        if mechanism.mechanism_kind in {"trace_ability", "eidolon_ability"}:
            graph = rules.standalone_ability_graph(mechanism.target_ref_id)
            if graph is None or graph.coverage_status != "executable":
                errors.append(f"mechanism_target_graph_not_executable:{mechanism.mechanism_ref_id}")
        else:
            errors.append(f"mechanism_kind_not_admitted:{mechanism.mechanism_ref_id}")
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
        equipment_assembly_result=equipment_result,
        blocked_reasons=normalized or ("character_build_blocked_without_reason",),
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


def _resolve_effective_skill_levels(
    rules: RuleBook,
    card: CharacterDataCardIR,
    build: CharacterBuildInput,
    selected_nodes: tuple[CharacterTraceNodeIR, ...],
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
        skill_id
        for node in all_nodes
        for skill_id in node.level_up_skill_ids
        if skill_id in card_skill_ids
    }
    selected_by_skill: dict[str, tuple[CharacterTraceNodeIR, CharacterMechanismSlotIR]] = {}
    for node in selected_nodes:
        if not node.level_up_skill_ids:
            continue
        skill_slots = tuple(
            slot
            for slot_id in node.linked_mechanism_slot_ids
            if (slot := rules.character_mechanism_slot(slot_id)) is not None
            and slot.mechanism_kind == "trace_skill_level"
        )
        if len(skill_slots) != 1:
            errors.append(f"trace_skill_level_slot_not_unique:{node.trace_node_id}")
            continue
        slot = skill_slots[0]
        if (
            slot.character_data_card_id != build.character_card_id
            or slot.coverage_status != "executable"
        ):
            errors.append(f"trace_skill_level_slot_not_executable:{slot.mechanism_slot_id}")
            continue
        slot_skill_ids = slot.semantics.get("level_up_skill_ids")
        if not isinstance(slot_skill_ids, (list, tuple)) or tuple(slot_skill_ids) != node.level_up_skill_ids:
            errors.append(f"trace_skill_level_slot_source_mismatch:{slot.mechanism_slot_id}")
            continue
        if node.level <= 0 or node.level > node.max_level:
            errors.append(f"trace_skill_level_outside_node_range:{node.trace_node_id}")
            continue
        auxiliary_skill_ids = tuple(
            skill_id for skill_id in node.level_up_skill_ids if skill_id not in card_skill_ids
        )
        if auxiliary_skill_ids:
            diagnostics.append(
                CharacterMechanismDiagnostic(
                    diagnostic_id=(
                        "character_mechanism_diagnostic:auxiliary_skill_level:"
                        f"{node.trace_node_id}"
                    ),
                    mechanism_kind="skill_level",
                    target_ref_id=slot.mechanism_slot_id,
                    reason="auxiliary_unit_skill_level_requires_owned_combatant_build",
                    source=slot.source,
                )
            )
        for skill_id in (
            skill_id for skill_id in node.level_up_skill_ids if skill_id in card_skill_ids
        ):
            if skill_id in selected_by_skill:
                errors.append(f"skill_level_resolved_by_multiple_trace_nodes:{skill_id}")
            else:
                selected_by_skill[skill_id] = (node, slot)

    bonus_sources_by_skill: dict[str, list[CharacterSkillLevelSource]] = {}
    try:
        eidolon_slots = rules.character_eidolon_slots_for_level(
            build.character_card_id,
            build.eidolon_level,
        )
    except ValueError as exc:
        errors.append(str(exc))
        eidolon_slots = ()
    for eidolon_slot in eidolon_slots:
        for mechanism_slot_id in eidolon_slot.linked_mechanism_slot_ids:
            slot = rules.character_mechanism_slot(mechanism_slot_id)
            if slot is None or slot.mechanism_kind != "eidolon_skill_level":
                continue
            if (
                slot.character_data_card_id != build.character_card_id
                or slot.coverage_status != "executable"
            ):
                errors.append(f"eidolon_skill_level_slot_not_executable:{mechanism_slot_id}")
                continue
            raw_bonuses = slot.semantics.get("skill_add_level_list")
            if not isinstance(raw_bonuses, Mapping) or not raw_bonuses:
                errors.append(f"eidolon_skill_level_source_missing:{mechanism_slot_id}")
                continue
            for raw_skill_id, raw_bonus in raw_bonuses.items():
                skill_id = str(raw_skill_id)
                bonus = raw_bonus.get("Value") if isinstance(raw_bonus, Mapping) else raw_bonus
                if skill_id not in card_skill_ids:
                    errors.append(f"eidolon_skill_identity_not_owned_by_character:{skill_id}")
                elif not isinstance(bonus, int) or isinstance(bonus, bool) or bonus <= 0:
                    errors.append(f"eidolon_skill_level_bonus_invalid:{skill_id}")
                else:
                    bonus_sources_by_skill.setdefault(skill_id, []).append(
                        CharacterSkillLevelSource(
                            source_kind="eidolon_bonus",
                            level_value=bonus,
                            source_ref=BuildSourceRef(
                                "character_mechanism_slot",
                                slot.mechanism_slot_id,
                            ),
                            source=slot.source,
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
            node, slot = selected
            base_level = node.level
            base_source = CharacterSkillLevelSource(
                source_kind="trace_base",
                level_value=base_level,
                source_ref=BuildSourceRef("character_mechanism_slot", slot.mechanism_slot_id),
                source=slot.source,
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


def _trace_static_contributions(
    node: CharacterTraceNodeIR,
    slot: CharacterMechanismSlotIR,
) -> tuple[list[StaticStatContribution], str]:
    if slot.coverage_status != "executable":
        return [], slot.blocked_reason or f"trace_static_slot_not_executable:{slot.mechanism_slot_id}"
    raw_terms = slot.semantics.get("mapped_terms")
    if not isinstance(raw_terms, (list, tuple)):
        return [], f"trace_static_terms_missing:{slot.mechanism_slot_id}"
    result: list[StaticStatContribution] = []
    for position, raw_term in enumerate(raw_terms):
        if not isinstance(raw_term, Mapping):
            return [], f"trace_static_term_not_object:{slot.mechanism_slot_id}:{position}"
        application_kind = raw_term.get("application_kind")
        property_type = raw_term.get("target_key")
        exact_value = raw_term.get("value")
        if not isinstance(property_type, str) or not property_type:
            return [], f"trace_static_property_missing:{slot.mechanism_slot_id}:{position}"
        if not isinstance(exact_value, str):
            return [], f"trace_static_value_not_exact_decimal:{slot.mechanism_slot_id}:{position}"
        if application_kind == "base_stat_ratio":
            pool, calculation_kind = "percentage", "ratio"
        elif application_kind == "base_stat_delta":
            pool, calculation_kind = "flat", "flat"
        elif application_kind == "resource_delta":
            pool, calculation_kind = "resource", "resource"
        else:
            return [], f"trace_static_application_kind_not_admitted:{slot.mechanism_slot_id}:{position}"
        calculation = StatCalculation(calculation_kind, exact_value)  # type: ignore[arg-type]
        result.append(
            StaticStatContribution(
                contribution_id=f"character_trace:{node.trace_node_id}:{slot.mechanism_slot_id}:{position}",
                contribution_pool=pool,  # type: ignore[arg-type]
                property_type=property_type,
                exact_value=calculation.exact_value,
                source_ref=BuildSourceRef("character_mechanism_slot", slot.mechanism_slot_id),
                calculation=calculation,
                source=slot.source,
            )
        )
    if not result:
        return [], f"trace_static_terms_empty:{slot.mechanism_slot_id}"
    return result, ""


def _trace_dynamic_ref(
    rules: RuleBook,
    build: CharacterBuildInput,
    node: CharacterTraceNodeIR,
    slot: CharacterMechanismSlotIR,
) -> tuple[CharacterMechanismRef | None, CharacterMechanismDiagnostic | None]:
    admission = slot.semantics.get("startup_admission")
    graph_id = admission.get("standalone_ability_graph_id") if isinstance(admission, Mapping) else None
    graph = rules.standalone_ability_graph(graph_id) if isinstance(graph_id, str) else None
    if slot.coverage_status != "executable" or graph is None or graph.coverage_status != "executable":
        reason = slot.blocked_reason or "trace_dynamic_graph_missing_or_not_executable"
        return None, CharacterMechanismDiagnostic(
            diagnostic_id=f"character_mechanism_diagnostic:{slot.mechanism_slot_id}",
            mechanism_kind="trace_ability",
            target_ref_id=str(graph_id or slot.linked_ir_ids.get("ability_name") or slot.mechanism_slot_id),
            reason=reason,
            source=slot.source,
        )
    return CharacterMechanismRef(
        mechanism_ref_id=f"character_mechanism_ref:{slot.mechanism_slot_id}",
        mechanism_kind="trace_ability",
        character_card_id=build.character_card_id,
        target_ref_id=graph.standalone_ability_graph_id,
        source_ref=BuildSourceRef("character_mechanism_slot", slot.mechanism_slot_id),
        source=slot.source,
    ), None


def _eidolon_mechanisms(
    rules: RuleBook,
    build: CharacterBuildInput,
) -> tuple[list[CharacterMechanismRef], list[CharacterMechanismDiagnostic]]:
    refs: list[CharacterMechanismRef] = []
    diagnostics: list[CharacterMechanismDiagnostic] = []
    try:
        eidolon_slots = rules.character_eidolon_slots_for_level(
            build.character_card_id,
            build.eidolon_level,
        )
    except ValueError as exc:
        return refs, [
            CharacterMechanismDiagnostic(
                diagnostic_id=f"character_mechanism_diagnostic:eidolon_level:{build.eidolon_level}",
                mechanism_kind="eidolon",
                target_ref_id=str(build.eidolon_level),
                reason=str(exc),
            )
        ]
    for eidolon_slot in eidolon_slots:
        if eidolon_slot.coverage_status != "executable" or not eidolon_slot.linked_mechanism_slot_ids:
            diagnostics.append(
                CharacterMechanismDiagnostic(
                    diagnostic_id=f"character_mechanism_diagnostic:{eidolon_slot.eidolon_slot_id}",
                    mechanism_kind="eidolon",
                    target_ref_id=eidolon_slot.eidolon_slot_id,
                    reason=eidolon_slot.blocked_reason or "eidolon_mechanism_slot_missing",
                    source=eidolon_slot.source,
                )
            )
            continue
        for mechanism_slot_id in eidolon_slot.linked_mechanism_slot_ids:
            slot = rules.character_mechanism_slot(mechanism_slot_id)
            if slot is None or slot.character_data_card_id != build.character_card_id:
                diagnostics.append(
                    CharacterMechanismDiagnostic(
                        diagnostic_id=f"character_mechanism_diagnostic:{mechanism_slot_id}",
                        mechanism_kind="eidolon",
                        target_ref_id=mechanism_slot_id,
                        reason="eidolon_linked_mechanism_slot_missing_or_wrong_card",
                        source=eidolon_slot.source,
                    )
                )
                continue
            if slot.coverage_status != "executable":
                diagnostics.append(
                    CharacterMechanismDiagnostic(
                        diagnostic_id=f"character_mechanism_diagnostic:{slot.mechanism_slot_id}",
                        mechanism_kind="eidolon",
                        target_ref_id=slot.mechanism_slot_id,
                        reason=slot.blocked_reason or "eidolon_mechanism_not_executable",
                        source=slot.source,
                    )
                )
                continue
            if slot.mechanism_kind == "eidolon_skill_level":
                # Skill-level bonuses are resolved into the static typed
                # effective_skill_levels channel, never a dynamic mechanism.
                continue
            elif slot.mechanism_kind == "eidolon_ability_hook":
                rank_abilities = slot.semantics.get("rank_ability")
                if not isinstance(rank_abilities, (list, tuple)) or not rank_abilities:
                    diagnostics.append(
                        CharacterMechanismDiagnostic(
                            diagnostic_id=f"character_mechanism_diagnostic:{slot.mechanism_slot_id}:ability",
                            mechanism_kind="eidolon_ability",
                            target_ref_id=slot.mechanism_slot_id,
                            reason="eidolon_ability_source_missing",
                            source=slot.source,
                        )
                    )
                    continue
                for index, ability_name in enumerate(rank_abilities):
                    graph_candidates = tuple(
                        graph
                        for graph in rules.standalone_ability_graphs_by_name(str(ability_name))
                        if graph.coverage_status == "executable"
                    )
                    if len(graph_candidates) != 1:
                        diagnostics.append(
                            CharacterMechanismDiagnostic(
                                diagnostic_id=f"character_mechanism_diagnostic:{slot.mechanism_slot_id}:ability:{index}",
                                mechanism_kind="eidolon_ability",
                                target_ref_id=str(ability_name),
                                reason="eidolon_ability_graph_missing_or_ambiguous",
                                source=slot.source,
                            )
                        )
                    else:
                        refs.append(
                            CharacterMechanismRef(
                                mechanism_ref_id=f"character_mechanism_ref:{slot.mechanism_slot_id}:ability:{index}",
                                mechanism_kind="eidolon_ability",
                                character_card_id=build.character_card_id,
                                target_ref_id=graph_candidates[0].standalone_ability_graph_id,
                                source_ref=BuildSourceRef("character_mechanism_slot", slot.mechanism_slot_id),
                                source=slot.source,
                            )
                        )
            else:
                diagnostics.append(
                    CharacterMechanismDiagnostic(
                        diagnostic_id=f"character_mechanism_diagnostic:{slot.mechanism_slot_id}:unsupported",
                        mechanism_kind=slot.mechanism_kind,
                        target_ref_id=slot.mechanism_slot_id,
                        reason="eidolon_subsource_kind_not_admitted",
                        source=slot.source,
                    )
                )
    return refs, diagnostics


def _panel_from_ledger(contributions: list[StaticStatContribution]) -> CharacterBasePanel:
    by_pool: dict[str, dict[str, Decimal]] = {
        "base": {},
        "percentage": {},
        "flat": {},
        "resource": {},
    }
    for contribution in sorted(contributions, key=lambda item: item.sort_key):
        pool = by_pool[contribution.contribution_pool]
        pool[contribution.property_type] = pool.get(contribution.property_type, Decimal(0)) + Decimal(
            contribution.exact_value
        )
    final: dict[str, Decimal] = {}
    properties = set().union(*(pool.keys() for pool in by_pool.values()))
    for property_type in sorted(properties):
        base_value = by_pool["base"].get(property_type, Decimal(0))
        percentage = by_pool["percentage"].get(property_type, Decimal(0))
        flat = by_pool["flat"].get(property_type, Decimal(0))
        resource = by_pool["resource"].get(property_type, Decimal(0))
        if property_type in _BASE_POOL_PROPERTIES:
            if resource:
                raise ValueError(f"base panel property {property_type} cannot use resource pool")
            final[property_type] = base_value * (Decimal(1) + percentage) + flat
        else:
            if base_value or percentage or flat:
                raise ValueError(f"resource property {property_type} cannot use base stat pools")
            final[property_type] = resource
    missing = sorted(_PANEL_PRIMARY_PROPERTIES.difference(final))
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
        max_energy=str(final["max_energy"]),
        critical_chance=str(final["critical_chance"]),
        critical_damage=str(final["critical_damage"]),
        base_aggro=str(final["base_aggro"]),
        additional_resources=additional,
    )
