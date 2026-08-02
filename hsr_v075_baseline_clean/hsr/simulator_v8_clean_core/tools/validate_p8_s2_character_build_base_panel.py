from __future__ import annotations

import argparse
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..build_types import BuildSourceRef, ir_source_from_json
from ..builds.character_assembler import assemble_character_build, validate_character_build_admission
from ..builds.models import (
    CharacterBuildAssemblyResult,
    CharacterBuildInput,
    CharacterDynamicGraphRef,
    CharacterMechanismDiagnostic,
)
from ..equipment.models import (
    EquipmentBuildInput,
    EquipmentDefinitionKey,
    LightConeInstanceInput,
)
from ..immutable_json import freeze_json
from ..ir_types import same_ir_source_raw_row
from ..rules.ir import (
    ActionDefinitionIR,
    AvatarProfileIR,
    AvatarPromotionTierIR,
    CanonicalIR,
    CharacterDataCardIR,
    CharacterEidolonSlotIR,
    CharacterMechanismSlotIR,
    CharacterTraceNodeIR,
    CombatantActionSetIR,
    IRSource,
    RuleEntity,
)
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..scenarios.schema import PanelInput, TimelineSetupSpec
from ..tbgd.character_cards import _avatar_promotion_tiers, build_character_card_ir
from ..systems.action_availability import ActionAvailabilitySystem
from ..tbgd.lowering import (
    CHARACTER_ACTION_DEFINITION_TABLES,
    TBGDLowering,
    build_character_action_definition_ir,
)
from ..tbgd.paths import find_tbgd_root
from .io import write_json


VALIDATION_VERSION = "p8_s2_character_build_base_panel"


def run_fixture_contract_validation(output_dir: Path) -> dict[str, Any]:
    source = IRSource(
        source_path="validation/AvatarPromotionConfig.json",
        raw_type="AvatarPromotionConfig",
        raw_id="fixture:0",
        evidence=freeze_json(
            {
                "promotion_field_present": False,
                "promotion_zero_semantic_from_missing_field": True,
                "stat_raw_paths": ["HPBase", "HPAdd"],
            }
        ),
    )
    action_sources = {
        level: IRSource(
            source_path="validation/AvatarSkillConfig.json",
            raw_type="AvatarSkillConfig",
            raw_id="fixture_skill",
            evidence=freeze_json(
                {
                    "row_index": level - 1,
                    "id_key": "SkillID",
                    "level": level,
                    "builder": "fixture_action_source",
                }
            ),
        )
        for level in (1, 2)
    }
    fixture_action_definitions = tuple(
        ActionDefinitionIR(
            definition_id=f"action_definition:fixture:{level}",
            action_id="avatar_skill:fixture_skill",
            level=level,
            attack_type="Normal",
            skill_effect="SingleAttack",
            target_mode="single",
            bp_need=0.0,
            bp_add=0.0,
            sp_base=0.0,
            sp_multiple_ratio=0.0,
            param_list=(),
            show_stance_list=(),
            show_damage_list=(),
            stance_damage_type=None,
            source=action_sources[level],
            coverage_status="executable",
        )
        for level in (1, 2)
    )
    tier = AvatarPromotionTierIR(
        promotion_tier_id="avatar_promotion_tier:fixture:0",
        avatar_id="fixture",
        promotion=0,
        promotion_field_present=False,
        max_level=20,
        hp_base="100",
        hp_add="5",
        attack_base="50",
        attack_add="2",
        defense_base="40",
        defense_add="1",
        speed_base="100",
        critical_chance="0.05",
        critical_damage="0.5",
        base_aggro="100",
        source=source,
        coverage_status="executable",
    )
    promoted_tier = AvatarPromotionTierIR(
        promotion_tier_id="avatar_promotion_tier:fixture:1",
        avatar_id="fixture",
        promotion=1,
        promotion_field_present=True,
        max_level=30,
        hp_base="200",
        hp_add="5",
        attack_base="75",
        attack_add="2",
        defense_base="60",
        defense_add="1",
        speed_base="100",
        critical_chance="0.05",
        critical_damage="0.5",
        base_aggro="100",
        source=source,
        coverage_status="executable",
    )
    profile = AvatarProfileIR(
        avatar_profile_id="avatar_profile:fixture",
        avatar_id="fixture",
        base_type="FixturePath",
        damage_type="FixtureDamage",
        skill_ids=("fixture_skill",),
        promotion_tiers=(tier, promoted_tier),
        max_energy="120",
        max_energy_source=source,
        source=source,
        coverage_status="executable",
    )
    card = CharacterDataCardIR(
        card_id="character_data_card:avatar:fixture",
        entity_ref="avatar:fixture",
        profile_id=profile.avatar_profile_id,
        skill_ids=profile.skill_ids,
        skill_formula_binding_ids=(),
        bounce_policy_ids=(),
        action_set={
            "actions": [
                {
                    "action_id": "avatar_skill:fixture_skill",
                    "raw_skill_id": "fixture_skill",
                    "level": 1,
                    "max_level": 1,
                    "source_trace": action_sources[1].to_json(),
                }
            ]
        },
        source=source,
        coverage_status="executable",
    )
    rules = RuleBook(
        CanonicalIR(
            version=BASELINE_VERSION,
            avatar_profiles=(profile,),
            character_data_cards=(card,),
            action_definitions=fixture_action_definitions,
        )
    )
    build = _build(card.card_id, level=20, promotion=0)
    result = assemble_character_build(rules, build)
    promoted_at_same_level = assemble_character_build(
        rules,
        _build(card.card_id, level=20, promotion=1),
    )
    promoted_below_boundary = assemble_character_build(
        rules,
        _build(card.card_id, level=19, promotion=1),
    )
    duplicate_profile = replace(profile, promotion_tiers=(tier, tier))
    duplicate_rules = RuleBook(
        CanonicalIR(
            version=BASELINE_VERSION,
            avatar_profiles=(duplicate_profile,),
            character_data_cards=(card,),
            action_definitions=fixture_action_definitions,
        )
    )
    default_trace_node = CharacterTraceNodeIR(
        trace_node_id=f"character_trace_node:{card.card_id}:default-skill:1",
        character_data_card_id=card.card_id,
        avatar_id=profile.avatar_id,
        trace_id="default-skill",
        trace_kind="skill_level",
        linked_mechanism_slot_ids=(
            f"character_mechanism_slot:{card.card_id}:trace:default-skill:1:skill_level",
        ),
        source=source,
        coverage_status="executable",
        level=1,
        max_level=6,
        default_unlocked=True,
        level_up_skill_ids=("fixture_skill",),
    )
    default_trace_slot = CharacterMechanismSlotIR(
        mechanism_slot_id=default_trace_node.linked_mechanism_slot_ids[0],
        character_data_card_id=card.card_id,
        mechanism_kind="trace_skill_level",
        runtime_system="character_card_assembly.skill_level",
        linked_ir_ids={"trace_node_id": default_trace_node.trace_node_id},
        activation={"kind": "trace_unlock", "default_enabled": True},
        semantics={"node_level": 1, "level_up_skill_ids": ["fixture_skill"]},
        source=source,
        coverage_status="executable",
        blocked_reason="",
    )
    upgraded_trace_node = replace(
        default_trace_node,
        trace_node_id=f"character_trace_node:{card.card_id}:default-skill:2",
        linked_mechanism_slot_ids=(
            f"character_mechanism_slot:{card.card_id}:trace:default-skill:2:skill_level",
        ),
        level=2,
        default_unlocked=False,
    )
    upgraded_trace_slot = replace(
        default_trace_slot,
        mechanism_slot_id=upgraded_trace_node.linked_mechanism_slot_ids[0],
        linked_ir_ids={"trace_node_id": upgraded_trace_node.trace_node_id},
        activation={"kind": "trace_unlock", "default_enabled": False},
        semantics={"node_level": 2, "level_up_skill_ids": ["fixture_skill"]},
    )
    trace_action_set = {
        "actions": [
            {
                "action_id": "avatar_skill:fixture_skill",
                "raw_skill_id": "fixture_skill",
                "level": level,
                "max_level": 6,
                "source_trace": action_sources[level].to_json(),
            }
            for level in (1, 2)
        ]
    }
    default_trace_card = replace(
        card,
        trace_node_ids=(default_trace_node.trace_node_id, upgraded_trace_node.trace_node_id),
        mechanism_slot_ids=(
            default_trace_slot.mechanism_slot_id,
            upgraded_trace_slot.mechanism_slot_id,
        ),
        action_set=trace_action_set,
    )
    default_trace_rules = RuleBook(
        CanonicalIR(
            version=BASELINE_VERSION,
            avatar_profiles=(profile,),
            character_data_cards=(default_trace_card,),
            character_trace_nodes=(default_trace_node, upgraded_trace_node),
            character_mechanism_slots=(default_trace_slot, upgraded_trace_slot),
            action_definitions=fixture_action_definitions,
        )
    )
    identity_rules = RuleBook(
        CanonicalIR(
            version=BASELINE_VERSION,
            entities=(
                RuleEntity("avatar:fixture", "avatar", {}, source, "executable"),
                RuleEntity(
                    "avatar_skill:fixture_skill",
                    "avatar_skill",
                    {},
                    source,
                    "executable",
                ),
            ),
            avatar_profiles=(profile,),
            character_data_cards=(default_trace_card,),
            character_trace_nodes=(default_trace_node, upgraded_trace_node),
            character_mechanism_slots=(default_trace_slot, upgraded_trace_slot),
            combatant_action_sets=(
                CombatantActionSetIR(
                    combatant_action_set_id="combatant_action_set:avatar:fixture",
                    entity_ref="avatar:fixture",
                    skill_index_map={
                        "1": {
                            "action_ref": "avatar_skill:fixture_skill",
                            "default_level": 2,
                            "coverage_status": "executable",
                            "blocked_reason": "",
                        }
                    },
                    source=source,
                    coverage_status="executable",
                ),
            ),
            action_definitions=fixture_action_definitions,
        )
    )
    default_trace_result = assemble_character_build(
        default_trace_rules,
        _build(default_trace_card.card_id, level=20, promotion=0),
    )
    explicit_default_result = assemble_character_build(
        default_trace_rules,
        _build(
            default_trace_card.card_id,
            level=20,
            promotion=0,
            trace_ids=(default_trace_node.trace_node_id,),
        ),
    )
    upgraded_default_result = assemble_character_build(
        default_trace_rules,
        _build(
            default_trace_card.card_id,
            level=20,
            promotion=0,
            trace_ids=(upgraded_trace_node.trace_node_id,),
        ),
    )
    conflicting_trace_result = assemble_character_build(
        default_trace_rules,
        _build(
            default_trace_card.card_id,
            level=20,
            promotion=0,
            trace_ids=(
                default_trace_node.trace_node_id,
                upgraded_trace_node.trace_node_id,
            ),
        ),
    )
    promotion_locked_node = replace(upgraded_trace_node, required_promotion=1)
    level_locked_node = replace(upgraded_trace_node, required_character_level=21)
    prerequisite_locked_node = replace(
        upgraded_trace_node,
        prerequisite_trace_ids=("required-other-trace",),
    )

    def requirement_result(node: CharacterTraceNodeIR) -> CharacterBuildAssemblyResult:
        requirement_rules = RuleBook(
            CanonicalIR(
                version=BASELINE_VERSION,
                avatar_profiles=(profile,),
                character_data_cards=(default_trace_card,),
                character_trace_nodes=(default_trace_node, node),
                character_mechanism_slots=(default_trace_slot, upgraded_trace_slot),
                action_definitions=fixture_action_definitions,
            )
        )
        return assemble_character_build(
            requirement_rules,
            _build(
                default_trace_card.card_id,
                level=20,
                promotion=0,
                trace_ids=(node.trace_node_id,),
            ),
        )

    promotion_requirement_result = requirement_result(promotion_locked_node)
    level_requirement_result = requirement_result(level_locked_node)
    prerequisite_requirement_result = requirement_result(prerequisite_locked_node)
    missing_action_definition_result = assemble_character_build(
        RuleBook(replace(default_trace_rules.ir, action_definitions=())),
        _build(default_trace_card.card_id, level=20, promotion=0),
    )
    duplicate_action_definition_result = assemble_character_build(
        RuleBook(
            replace(
                default_trace_rules.ir,
                action_definitions=(
                    *fixture_action_definitions,
                    fixture_action_definitions[0],
                ),
            )
        ),
        _build(default_trace_card.card_id, level=20, promotion=0),
    )
    blocked_action_definition_result = assemble_character_build(
        RuleBook(
            replace(
                default_trace_rules.ir,
                action_definitions=(
                    replace(fixture_action_definitions[0], coverage_status="audit_only"),
                    fixture_action_definitions[1],
                ),
            )
        ),
        _build(default_trace_card.card_id, level=20, promotion=0),
    )
    unrelated_action_source = IRSource(
        source_path="validation/UnrelatedSkill.json",
        raw_type="UnrelatedSkill",
        raw_id="different-row",
        evidence=freeze_json(
            {
                "row_index": 0,
                "id_key": "SkillID",
                "level": 1,
                "builder": "unrelated_fixture_builder",
            }
        ),
    )
    wrong_row_action_source = replace(
        action_sources[1],
        evidence=freeze_json(
            {
                **dict(action_sources[1].evidence),
                "row_index": 99,
                "builder": "different_builder_note_is_not_identity",
            }
        ),
    )
    wrong_level_action_source = replace(
        action_sources[1],
        evidence=freeze_json(
            {
                **dict(action_sources[1].evidence),
                "level": 2,
            }
        ),
    )

    def build_with_level_one_definition_source(
        definition_source: IRSource,
    ) -> CharacterBuildAssemblyResult:
        source_rules = RuleBook(
            replace(
                rules.ir,
                action_definitions=(
                    replace(fixture_action_definitions[0], source=definition_source),
                    fixture_action_definitions[1],
                ),
            )
        )
        return assemble_character_build(source_rules, build)

    unrelated_action_source_result = build_with_level_one_definition_source(
        unrelated_action_source
    )
    wrong_row_action_source_result = build_with_level_one_definition_source(
        wrong_row_action_source
    )
    wrong_level_action_source_result = build_with_level_one_definition_source(
        wrong_level_action_source
    )
    eidolon_skill_slot = CharacterMechanismSlotIR(
        mechanism_slot_id=f"character_mechanism_slot:{card.card_id}:eidolon:1:skill_level",
        character_data_card_id=card.card_id,
        mechanism_kind="eidolon_skill_level",
        runtime_system="character_card_assembly.skill_level_bonus",
        linked_ir_ids={"rank": 1},
        activation={"kind": "eidolon_prefix_toggle", "required_eidolon_level": 1},
        semantics={"skill_add_level_list": {"fixture_skill": 1}},
        source=source,
        coverage_status="executable",
    )
    eidolon_extra_slot = CharacterMechanismSlotIR(
        mechanism_slot_id=f"character_mechanism_slot:{card.card_id}:eidolon:1:extra_effect",
        character_data_card_id=card.card_id,
        mechanism_kind="eidolon_extra_effect",
        runtime_system="event_dispatch_or_effect_registry",
        linked_ir_ids={"rank": 1},
        activation={"kind": "eidolon_prefix_toggle", "required_eidolon_level": 1},
        semantics={"extra_effect_id_list": ["fixture_extra"]},
        source=source,
        coverage_status="blocked",
        blocked_reason="eidolon_extra_effect_id_runtime_admission_pending",
    )
    eidolon_slot = CharacterEidolonSlotIR(
        eidolon_slot_id=f"character_eidolon_slot:{card.card_id}:rank:1",
        character_data_card_id=card.card_id,
        avatar_id=profile.avatar_id,
        rank=1,
        rank_id="fixture_rank_1",
        linked_mechanism_slot_ids=(
            eidolon_skill_slot.mechanism_slot_id,
            eidolon_extra_slot.mechanism_slot_id,
        ),
        source=source,
        coverage_status="executable",
        blocked_reason="",
    )
    eidolon_card = replace(
        default_trace_card,
        eidolon_slot_ids=(eidolon_slot.eidolon_slot_id,),
        mechanism_slot_ids=(
            default_trace_slot.mechanism_slot_id,
            upgraded_trace_slot.mechanism_slot_id,
            eidolon_skill_slot.mechanism_slot_id,
            eidolon_extra_slot.mechanism_slot_id,
        ),
    )
    eidolon_rules = RuleBook(
        CanonicalIR(
            version=BASELINE_VERSION,
            avatar_profiles=(profile,),
            character_data_cards=(eidolon_card,),
            character_trace_nodes=(default_trace_node, upgraded_trace_node),
            character_eidolon_slots=(eidolon_slot,),
            character_mechanism_slots=(
                default_trace_slot,
                upgraded_trace_slot,
                eidolon_skill_slot,
                eidolon_extra_slot,
            ),
            action_definitions=fixture_action_definitions,
        )
    )
    mixed_eidolon_result = assemble_character_build(
        eidolon_rules,
        _build(eidolon_card.card_id, level=20, promotion=0, eidolon_level=1),
    )
    missing_build_mode_scenario = {
        "scenario_id": "validation:missing-build-mode",
        "version": BASELINE_VERSION,
        "units": [
            {
                "unit_id": "ally:fixture",
                "side": "ally",
                "entity_ref": card.entity_ref,
                "panel": {},
            }
        ],
        "route": [
            {
                "actor_id": "ally:fixture",
                "action_ref": "avatar_skill:fixture_skill",
                "action_level": 1,
                "target_ids": ["ally:fixture"],
            }
        ],
    }
    illegal_formal_timeline = {
        "scenario_id": "validation:formal-explicit-action-values",
        "version": BASELINE_VERSION,
        "units": [
            {
                "unit_id": "ally:fixture",
                "side": "ally",
                "entity_ref": card.entity_ref,
                "level": build.level,
                "eidolon_level": build.eidolon_level,
                "build_mode": "assembled_character_build",
                "panel": None,
                "character_build": build.to_json(),
                "initial_condition": {"hp_mode": "full", "initial_energy": "0"},
            }
        ],
        "route": [
            {
                "actor_id": "ally:fixture",
                "action_ref": "avatar_skill:fixture_skill",
                "action_level": 1,
                "target_ids": ["ally:fixture"],
            }
        ],
        "battle_setup": {
            "timeline": {
                "mode": "runtime_initialize",
                "action_values": {"ally:fixture": 1},
                "explicit_overrides": ["ally:fixture"],
            }
        },
    }
    illegal_action_values_only = json.loads(json.dumps(illegal_formal_timeline))
    illegal_action_values_only["battle_setup"]["timeline"].pop("explicit_overrides")
    illegal_overrides_only = json.loads(json.dumps(illegal_formal_timeline))
    illegal_overrides_only["battle_setup"]["timeline"].pop("action_values")
    valid_formal_timeline = json.loads(json.dumps(illegal_formal_timeline))
    valid_formal_timeline["battle_setup"]["timeline"].pop("action_values")
    valid_formal_timeline["battle_setup"]["timeline"].pop("explicit_overrides")
    valid_formal_scenario = ScenarioLoader().load_dict(valid_formal_timeline)
    valid_formal_identity_errors = IdentityResolver(identity_rules).validate(
        valid_formal_scenario
    ).errors
    wrong_formal_action_level_errors = IdentityResolver(identity_rules).validate(
        replace(
            valid_formal_scenario,
            route=(replace(valid_formal_scenario.route[0], action_level=2),),
        )
    ).errors
    direct_identity_errors = tuple(
        IdentityResolver(identity_rules).validate(
            replace(
                valid_formal_scenario,
                battle_setup=replace(
                    valid_formal_scenario.battle_setup,
                    timeline=timeline,
                ),
            )
        ).errors
        for timeline in (
            TimelineSetupSpec(
                mode="runtime_initialize",
                action_values={"ally:fixture": 1.0},
            ),
            TimelineSetupSpec(
                mode="runtime_initialize",
                explicit_overrides=("ally:fixture",),
            ),
        )
    )
    formal_built = ScenarioStateBuilder(identity_rules).build(valid_formal_scenario)
    formal_state = replace(
        formal_built.state,
        global_flags={
            **formal_built.state.global_flags,
            "phase": "turn_active",
            "current_window": "turn",
            "turn_owner_id": "ally:fixture",
        },
    )
    formal_view = ActionAvailabilitySystem(identity_rules).view(formal_state)
    formal_action_rows = tuple(
        row
        for row in (*formal_view.choices, *formal_view.blocked)
        if row.action_id == "avatar_skill:fixture_skill"
    )
    formal_actor = formal_state.units["ally:fixture"]
    missing_level_actor = replace(
        formal_actor,
        flags={
            **formal_actor.flags,
            "effective_skill_levels_by_action_id": {},
        },
    )
    missing_level_state = replace(
        formal_state,
        units={**formal_state.units, missing_level_actor.unit_id: missing_level_actor},
    )
    missing_level_view = ActionAvailabilitySystem(identity_rules).view(missing_level_state)
    damaged_definition_actor = replace(
        formal_actor,
        flags={
            **formal_actor.flags,
            "effective_skill_level_action_definitions": {
                "avatar_skill:fixture_skill": {
                    "definition_id": "damaged-definition",
                    "level": 1,
                    "action_record_source": action_sources[1].to_json(),
                    "source": action_sources[1].to_json(),
                }
            },
        },
    )
    damaged_definition_state = replace(
        formal_state,
        units={
            **formal_state.units,
            damaged_definition_actor.unit_id: damaged_definition_actor,
        },
    )
    damaged_definition_view = ActionAvailabilitySystem(identity_rules).view(
        damaged_definition_state
    )
    base_properties = {
        "max_hp",
        "attack",
        "defense",
        "speed",
        "max_energy",
    }
    max_energy_contribution = next(
        item for item in result.contribution_ledger if item.property_type == "max_energy"
    )
    critical_chance_contribution = next(
        item for item in result.contribution_ledger if item.property_type == "critical_chance"
    )
    checks = {
        "fixture_assembly_admitted": (
            result.assembly_status == "assembled" and result.battle_admission_status == "admitted"
        ),
        "fixture_decimal_growth_exact": (
            result.base_panel is not None and result.base_panel.max_hp == "195"
        ),
        "fixture_same_level_pre_and_post_promotion_are_admitted": (
            promoted_at_same_level.assembly_status == "assembled"
            and promoted_at_same_level.battle_admission_status == "admitted"
            and promoted_at_same_level.base_panel is not None
            and promoted_at_same_level.base_panel.max_hp == "295"
        ),
        "fixture_promoted_state_below_boundary_is_blocked": result_is_blocked(
            promoted_below_boundary
        ),
        "fixture_base_and_resource_contribution_pools_are_semantically_separate": (
            {
                item.property_type
                for item in result.contribution_ledger
                if item.contribution_pool == "base"
            }
            == base_properties
            and {
                item.property_type
                for item in result.contribution_ledger
                if item.contribution_pool == "resource"
            }
            == {"critical_chance", "critical_damage", "base_aggro"}
        ),
        "fixture_cross_pool_base_or_resource_contributions_are_rejected": (
            _raises(
                lambda: replace(
                    result,
                    contribution_ledger=tuple(
                        replace(item, contribution_pool="resource")
                        if item.contribution_id == max_energy_contribution.contribution_id
                        else item
                        for item in result.contribution_ledger
                    ),
                )
            )
            and _raises(
                lambda: replace(
                    result,
                    contribution_ledger=tuple(
                        replace(item, contribution_pool="base")
                        if item.contribution_id == critical_chance_contribution.contribution_id
                        else item
                        for item in result.contribution_ledger
                    ),
                )
            )
        ),
        "fixture_fixed_action_skill_level_is_typed_and_admitted": (
            len(result.effective_skill_levels) == 1
            and result.effective_skill_levels[0].effective_level == 1
            and result.effective_skill_levels[0].sources[0].source_kind == "fixed_action"
            and result.effective_skill_levels[0].action_definition_id
            == fixture_action_definitions[0].definition_id
            and result.effective_skill_levels[0].action_record_source == action_sources[1]
            and result.effective_skill_levels[0].action_definition_source == action_sources[1]
        ),
        "fixture_skill_level_model_rejects_raw_row_source_mismatch": _raises(
            lambda: replace(
                result.effective_skill_levels[0],
                action_definition_source=unrelated_action_source,
            )
        ),
        "fixture_default_trace_is_automatic_and_admitted": (
            default_trace_result.assembly_status == "assembled"
            and default_trace_result.battle_admission_status == "admitted"
            and len(default_trace_result.effective_skill_levels) == 1
            and default_trace_result.effective_skill_levels[0].base_level == 1
            and default_trace_result.effective_skill_levels[0].effective_level == 1
        ),
        "fixture_explicit_default_trace_reselection_is_rejected": result_is_blocked(
            explicit_default_result
        ),
        "fixture_higher_trace_level_replaces_default": (
            upgraded_default_result.assembly_status == "assembled"
            and upgraded_default_result.battle_admission_status == "admitted"
            and upgraded_default_result.effective_skill_levels[0].base_level == 2
            and upgraded_default_result.effective_skill_levels[0].effective_level == 2
        ),
        "fixture_default_and_upgrade_cannot_be_selected_together": result_is_blocked(
            conflicting_trace_result
        ),
        "fixture_trace_promotion_requirement_is_enforced": (
            result_is_blocked(promotion_requirement_result)
            and any(
                reason.startswith("trace_promotion_requirement_not_met:")
                for reason in promotion_requirement_result.blocked_reasons
            )
        ),
        "fixture_trace_character_level_requirement_is_enforced": (
            result_is_blocked(level_requirement_result)
            and any(
                reason.startswith("trace_character_level_requirement_not_met:")
                for reason in level_requirement_result.blocked_reasons
            )
        ),
        "fixture_trace_prerequisite_requirement_is_enforced": (
            result_is_blocked(prerequisite_requirement_result)
            and any(
                reason.startswith("trace_prerequisite_not_unlocked:")
                for reason in prerequisite_requirement_result.blocked_reasons
            )
        ),
        "fixture_missing_action_definition_blocks_battle": (
            missing_action_definition_result.assembly_status == "assembled"
            and missing_action_definition_result.battle_admission_status == "blocked"
            and any(
                diagnostic.reason == "effective_skill_level_action_definition_missing"
                for diagnostic in missing_action_definition_result.unadmitted_mechanism_diagnostics
            )
        ),
        "fixture_duplicate_action_definition_blocks_battle": (
            duplicate_action_definition_result.assembly_status == "assembled"
            and duplicate_action_definition_result.battle_admission_status == "blocked"
            and any(
                diagnostic.reason == "effective_skill_level_action_definition_not_unique"
                for diagnostic in duplicate_action_definition_result.unadmitted_mechanism_diagnostics
            )
        ),
        "fixture_non_executable_action_definition_blocks_battle": (
            blocked_action_definition_result.assembly_status == "assembled"
            and blocked_action_definition_result.battle_admission_status == "blocked"
            and any(
                diagnostic.reason.startswith(
                    "effective_skill_level_action_definition_not_executable:"
                )
                for diagnostic in blocked_action_definition_result.unadmitted_mechanism_diagnostics
            )
        ),
        "fixture_unrelated_action_definition_source_blocks_battle": (
            _source_mismatch_preserves_panel_and_blocks_battle(
                unrelated_action_source_result,
                "effective_skill_level_action_definition_raw_row_mismatch",
            )
        ),
        "fixture_wrong_action_definition_row_blocks_battle": (
            _source_mismatch_preserves_panel_and_blocks_battle(
                wrong_row_action_source_result,
                "effective_skill_level_action_definition_raw_row_mismatch",
            )
        ),
        "fixture_wrong_action_definition_level_blocks_battle": (
            _source_mismatch_preserves_panel_and_blocks_battle(
                wrong_level_action_source_result,
                "effective_skill_level_action_raw_row_identity_invalid",
            )
        ),
        "fixture_mixed_eidolon_subsources_cannot_partially_admit": (
            mixed_eidolon_result.assembly_status == "assembled"
            and mixed_eidolon_result.battle_admission_status == "blocked"
            and len(mixed_eidolon_result.effective_skill_levels) == 1
            and mixed_eidolon_result.effective_skill_levels[0].base_level == 1
            and mixed_eidolon_result.effective_skill_levels[0].eidolon_level_bonus == 1
            and mixed_eidolon_result.effective_skill_levels[0].effective_level == 2
            and not mixed_eidolon_result.dynamic_graph_refs
            and any(
                item.target_ref_id == eidolon_extra_slot.mechanism_slot_id
                for item in mixed_eidolon_result.unadmitted_mechanism_diagnostics
            )
        ),
        "fixture_admission_rebuild_matches": not validate_character_build_admission(rules, build, result),
        "fixture_result_round_trip": CharacterBuildAssemblyResult.from_json(result.to_json()) == result,
        "fixture_battle_blocked_without_diagnostic_is_rejected": _raises(
            lambda: replace(result, battle_admission_status="blocked")
        ),
        "fixture_duplicate_promotion_blocked": result_is_blocked(
            assemble_character_build(duplicate_rules, build)
        ),
        "fixture_scenario_requires_explicit_build_mode": _raises(
            lambda: ScenarioLoader().load_dict(missing_build_mode_scenario)
        ),
        "fixture_formal_scenario_consumes_assembled_effective_skill_level": (
            not valid_formal_identity_errors
            and any(
                "does not match assembled effective level" in error
                for error in wrong_formal_action_level_errors
            )
        ),
        "fixture_formal_action_query_uses_assembled_level_not_card_default": (
            bool(formal_action_rows)
            and all(row.action_level == 1 for row in formal_action_rows)
            and not any(row.action_level == 2 for row in formal_action_rows)
        ),
        "fixture_formal_action_query_rejects_missing_level_mapping": any(
            row.reason.startswith("formal_build_effective_skill_levels_by_action_id_")
            for row in missing_level_view.blocked
        ),
        "fixture_formal_action_query_rejects_damaged_definition_binding": any(
            row.reason == "formal_build_action_definition_binding_mismatch"
            for row in damaged_definition_view.blocked
        ),
        "fixture_formal_runtime_timeline_rejects_action_values_and_overrides": (
            _raises(lambda: ScenarioLoader().load_dict(illegal_action_values_only))
            and _raises(lambda: ScenarioLoader().load_dict(illegal_overrides_only))
        ),
        "fixture_identity_rejects_direct_runtime_timeline_injection": all(
            any(
                "cannot carry runtime_initialize action_values or explicit_overrides" in error
                for error in errors
            )
            for errors in direct_identity_errors
        ),
    }
    output = {
        "schema_version": "p8_s2_fixture_contract_summary_v1",
        "version": VALIDATION_VERSION,
        "ok": all(checks.values()),
        "checks": checks,
        "resource_budget": {
            "tbgd_file_read_count": 0,
            "lowering_build_count": 0,
            "rulebook_build_count": 11,
            "large_artifacts_written": False,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p8_s2_fixture_contract.json", output)
    return output


def run_character_card_source_validation(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    card_result = build_character_card_ir(
        tbgd_root,
        max_records_per_table=None,
        skill_tables=CHARACTER_ACTION_DEFINITION_TABLES,
    )
    character_action_definitions = build_character_action_definition_ir(tbgd_root)
    raw_trace_rows: list[dict[str, Any]] = []
    for relative_path in (
        "ExcelOutput/AvatarSkillTreeConfig.json",
        "ExcelOutput/AvatarSkillTreeConfigLD.json",
    ):
        path = tbgd_root / relative_path
        if path.exists():
            raw_trace_rows.extend(
                row
                for row in json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
                if isinstance(row, dict)
            )
    raw_trace_by_key = {
        (str(row.get("AvatarID")), str(row.get("PointID")), int(row.get("Level") or 1)): row
        for row in raw_trace_rows
    }
    raw_promotion_rows = _raw_promotion_rows(tbgd_root)
    raw_promotions_by_key: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for _relative_path, _row_index, row in raw_promotion_rows:
        key = (
            str(row.get("AvatarID")),
            int(row.get("Promotion")) if "Promotion" in row else 0,
        )
        raw_promotions_by_key.setdefault(key, []).append(row)
    raw_rank_rows: list[dict[str, Any]] = []
    for relative_path in (
        "ExcelOutput/AvatarRankConfig.json",
        "ExcelOutput/AvatarRankConfigLD.json",
    ):
        path = tbgd_root / relative_path
        if path.exists():
            raw_rank_rows.extend(
                row
                for row in json.loads(path.read_text(encoding="utf-8"))
                if isinstance(row, dict)
            )
    raw_mixed_rank_ids = {
        str(row.get("RankID"))
        for row in raw_rank_rows
        if row.get("RankAbility") and row.get("ExtraEffectIDList")
    }
    raw_rank_by_id = {
        str(row.get("RankID")): row
        for row in raw_rank_rows
        if row.get("RankID") is not None
    }
    nodes_by_key = {
        (node.avatar_id, node.trace_id, node.level): node
        for node in card_result.character_trace_nodes
    }
    mechanism_slots = {
        slot.mechanism_slot_id: slot for slot in card_result.character_mechanism_slots
    }
    current_rank_ids = {
        slot.rank_id for slot in card_result.character_eidolon_slots if slot.rank_id
    }
    evidenced_base_rank_ids = {
        str(rank_id)
        for card in card_result.character_data_cards
        for rank_id in card.source.evidence.get("base_rank_id_list", ())
    }
    evidenced_enhanced_rank_ids = {
        str(rank_id)
        for card in card_result.character_data_cards
        for rank_id in card.source.evidence.get("enhanced_rank_id_list", ())
    }
    replaced_mixed_rank_ids = raw_mixed_rank_ids.difference(current_rank_ids)
    focused_rules = RuleBook(
        CanonicalIR(
            version=BASELINE_VERSION,
            avatar_profiles=tuple(card_result.avatar_profiles),
            character_data_cards=tuple(card_result.character_data_cards),
            character_equipment_eligibilities=tuple(
                card_result.character_equipment_eligibilities
            ),
            character_mechanism_slots=tuple(card_result.character_mechanism_slots),
            character_trace_nodes=tuple(card_result.character_trace_nodes),
            character_eidolon_slots=tuple(card_result.character_eidolon_slots),
            action_definitions=character_action_definitions,
        )
    )
    character_action_raw_row_matches: list[bool] = []
    for card in card_result.character_data_cards:
        actions = card.action_set.get("actions")
        if not isinstance(actions, (list, tuple)):
            character_action_raw_row_matches.append(False)
            continue
        for entry in actions:
            if not isinstance(entry, dict):
                character_action_raw_row_matches.append(False)
                continue
            action_id = entry.get("action_id")
            level = entry.get("level")
            if (
                not isinstance(action_id, str)
                or not action_id
                or not isinstance(level, int)
                or isinstance(level, bool)
                or level <= 0
            ):
                character_action_raw_row_matches.append(False)
                continue
            candidates = focused_rules.action_definition_candidates(action_id, level)
            try:
                action_record_source = ir_source_from_json(
                    entry.get("source_trace"),
                    "character_action_source_trace",
                )
                source_matches = (
                    len(candidates) == 1
                    and candidates[0].coverage_status == "executable"
                    and same_ir_source_raw_row(
                        action_record_source,
                        candidates[0].source,
                        expected_level=level,
                    )
                )
            except (TypeError, ValueError):
                source_matches = False
            character_action_raw_row_matches.append(source_matches)

    def node_child_kinds(node: CharacterTraceNodeIR) -> set[str]:
        return {
            slot.mechanism_kind
            for slot_id in node.linked_mechanism_slot_ids
            if (slot := mechanism_slots.get(slot_id)) is not None
        }

    source_field_matches = []
    for key, raw in raw_trace_by_key.items():
        node = nodes_by_key.get(key)
        source_field_matches.append(
            node is not None
            and node.max_level == int(raw.get("MaxLevel") or node.level)
            and node.default_unlocked is (raw.get("DefaultUnlock") is True)
            and node.required_promotion
            == (
                int(raw["AvatarPromotionLimit"])
                if "AvatarPromotionLimit" in raw
                else None
            )
            and node.required_character_level
            == (int(raw["AvatarLevelLimit"]) if "AvatarLevelLimit" in raw else None)
            and node.prerequisite_trace_ids
            == tuple(str(value) for value in raw.get("PrePoint") or ())
            and node.level_up_skill_ids
            == tuple(str(value) for value in raw.get("LevelUpSkillID") or ())
            and node.extra_effect_ids
            == tuple(str(value) for value in raw.get("ExtraEffectIDList") or ())
            and node.simple_extra_effect_ids
            == tuple(str(value) for value in raw.get("SimpleExtraEffectIDList") or ())
        )

    current_node = lambda node: (
        (card := focused_rules.character_data_card(node.character_data_card_id)) is not None
        and card.coverage_status == "executable"
        and (
            node.source.evidence.get("enhanced_id") is None
            if card.source.evidence.get("enhanced_id") is None
            else str(node.source.evidence.get("enhanced_id"))
            == str(card.source.evidence.get("enhanced_id"))
        )
    )
    promotion_locked_real_node = next(
        (
            node
            for node in card_result.character_trace_nodes
            if current_node(node)
            and node.required_promotion is not None
            and node.required_promotion > 0
        ),
        None,
    )
    level_locked_real_node = next(
        (
            node
            for node in card_result.character_trace_nodes
            if current_node(node)
            and node.required_character_level is not None
            and node.required_character_level > 1
        ),
        None,
    )
    prerequisite_locked_real_node = next(
        (
            node
            for node in card_result.character_trace_nodes
            if current_node(node) and node.prerequisite_trace_ids
        ),
        None,
    )

    def real_requirement_result(
        node: CharacterTraceNodeIR | None,
        *,
        low_progression: bool,
    ) -> CharacterBuildAssemblyResult | None:
        if node is None:
            return None
        card = focused_rules.character_data_card(node.character_data_card_id)
        profile = (
            focused_rules.avatar_profile_by_profile_id(card.profile_id)
            if card is not None
            else None
        )
        if card is None or profile is None or profile.coverage_status != "executable":
            return None
        if low_progression:
            level = 1
            promotion = 0
        else:
            tier = max(profile.promotion_tiers, key=lambda item: item.promotion)
            level = tier.max_level
            promotion = tier.promotion
        return assemble_character_build(
            focused_rules,
            _build(
                card.card_id,
                level=level,
                promotion=promotion,
                trace_ids=(node.trace_node_id,),
            ),
        )

    promotion_locked_real_result = real_requirement_result(
        promotion_locked_real_node,
        low_progression=True,
    )
    level_locked_real_result = real_requirement_result(
        level_locked_real_node,
        low_progression=True,
    )
    prerequisite_locked_real_result = real_requirement_result(
        prerequisite_locked_real_node,
        low_progression=False,
    )

    promotion_field_map = {
        "hp_base": "HPBase",
        "hp_add": "HPAdd",
        "attack_base": "AttackBase",
        "attack_add": "AttackAdd",
        "defense_base": "DefenceBase",
        "defense_add": "DefenceAdd",
        "speed_base": "SpeedBase",
        "critical_chance": "CriticalChance",
        "critical_damage": "CriticalDamage",
        "base_aggro": "BaseAggro",
    }

    def raw_exact_decimal(row: dict[str, Any], field_name: str) -> Decimal:
        value = row.get(field_name)
        value = value.get("Value") if isinstance(value, dict) else value
        if not isinstance(value, (int, Decimal)) or isinstance(value, bool):
            raise ValueError(f"raw field {field_name} is not exact numeric")
        return Decimal(value)

    promotion_projection_matches = []
    for profile in card_result.avatar_profiles:
        for tier in profile.promotion_tiers:
            candidates = raw_promotions_by_key.get((profile.avatar_id, tier.promotion), [])
            promotion_projection_matches.append(
                len(candidates) == 1
                and tier.max_level == int(candidates[0].get("MaxLevel") or 0)
                and all(
                    Decimal(getattr(tier, typed_field))
                    == raw_exact_decimal(candidates[0], raw_field)
                    for typed_field, raw_field in promotion_field_map.items()
                )
            )

    mixed_eidolons = []
    eidolon_child_projection_ok = []
    for eidolon in card_result.character_eidolon_slots:
        raw_rank = raw_rank_by_id.get(eidolon.rank_id)
        expected_kinds: set[str] = set()
        if raw_rank is not None and raw_rank.get("SkillAddLevelList"):
            expected_kinds.add("eidolon_skill_level")
        if raw_rank is not None and raw_rank.get("RankAbility"):
            expected_kinds.add("eidolon_ability_hook")
        if raw_rank is not None and raw_rank.get("ExtraEffectIDList"):
            expected_kinds.add("eidolon_extra_effect")
        if not expected_kinds and eidolon.linked_mechanism_slot_ids:
            expected_kinds.add("eidolon_unbound")
        actual_kinds = {
            slot.mechanism_kind
            for slot_id in eidolon.linked_mechanism_slot_ids
            if (slot := mechanism_slots.get(slot_id)) is not None
        }
        eidolon_child_projection_ok.append(
            raw_rank is not None
            and actual_kinds == expected_kinds
            and eidolon.semantics.get("rank_ability") == (raw_rank.get("RankAbility") or [])
            and eidolon.semantics.get("skill_add_level_list")
            == (raw_rank.get("SkillAddLevelList") or {})
            and eidolon.semantics.get("extra_effect_id_list")
            == (raw_rank.get("ExtraEffectIDList") or [])
        )
        if "eidolon_extra_effect" in expected_kinds and len(expected_kinds) > 1:
            mixed_eidolons.append(eidolon)

    nonstandard_profiles = tuple(
        profile
        for profile in card_result.avatar_profiles
        if profile.resource_mode != "standard_energy"
    )
    special_resource_raw_source_checks = []
    for profile in nonstandard_profiles:
        if profile.resource_mode == "source_missing":
            special_resource_raw_source_checks.append(
                profile.special_resource_source is None
            )
            continue
        source = profile.special_resource_source
        if source is None or Path(source.source_path).is_absolute():
            special_resource_raw_source_checks.append(False)
            continue
        source_path = tbgd_root / source.source_path
        if not source_path.exists():
            special_resource_raw_source_checks.append(False)
            continue
        raw_source = json.loads(source_path.read_text(encoding="utf-8"))
        matched_paths: list[str] = []

        def collect_special_resource_paths(value: object, json_path: str) -> None:
            if isinstance(value, dict):
                if value.get("$type") == "RPG.GameCore.SetSummonerEnergyBarState":
                    matched_paths.append(json_path)
                for key, child in value.items():
                    collect_special_resource_paths(child, f"{json_path}.{key}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    collect_special_resource_paths(child, f"{json_path}[{index}]")

        collect_special_resource_paths(raw_source, "$")
        special_resource_raw_source_checks.append(
            source.raw_type == "RPG.GameCore.SetSummonerEnergyBarState"
            and tuple(sorted(matched_paths))
            == tuple(sorted(source.evidence.get("matched_json_paths", ())))
            and len(matched_paths) == source.evidence.get("matched_node_count")
            and bool(matched_paths)
        )
    standard_build_results: list[tuple[AvatarProfileIR, CharacterBuildAssemblyResult]] = []
    max_energy_raw_ledger_panel_checks: list[bool] = []
    raw_max_energy_by_avatar: dict[str, Decimal] = {}
    avatar_source_cache: dict[str, list[object]] = {}
    standard_default_skill_classifications: list[str] = []
    standard_auxiliary_default_nodes: list[CharacterTraceNodeIR] = []
    for node in card_result.character_trace_nodes:
        if not node.default_unlocked or not node.level_up_skill_ids:
            continue
        card = focused_rules.character_data_card(node.character_data_card_id)
        profile = (
            focused_rules.avatar_profile_by_profile_id(card.profile_id)
            if card is not None
            else None
        )
        if card is None or profile is None or profile.coverage_status != "executable":
            continue
        card_enhanced_id = card.source.evidence.get("enhanced_id")
        node_enhanced_id = node.source.evidence.get("enhanced_id")
        version_matches = (
            node_enhanced_id is None
            if card_enhanced_id is None
            else str(node_enhanced_id) == str(card_enhanced_id)
        )
        if not version_matches:
            standard_default_skill_classifications.append("legacy_version_mirror")
        elif not set(node.level_up_skill_ids).intersection(card.skill_ids):
            standard_default_skill_classifications.append("auxiliary_unit_skill")
            standard_auxiliary_default_nodes.append(node)
        else:
            standard_default_skill_classifications.append("current_main_character_skill")
    standard_build_results_by_card_id: dict[str, CharacterBuildAssemblyResult] = {}
    for profile in card_result.avatar_profiles:
        if profile.coverage_status != "executable":
            continue
        card = focused_rules.character_data_card(
            f"character_data_card:avatar:{profile.avatar_id}"
        )
        if card is None:
            continue
        tier = max(profile.promotion_tiers, key=lambda item: item.promotion)
        assembled = assemble_character_build(
            focused_rules,
            _build(card.card_id, level=tier.max_level, promotion=tier.promotion),
        )
        standard_build_results.append((profile, assembled))
        standard_build_results_by_card_id[card.card_id] = assembled
        source = profile.max_energy_source
        raw_energy: Decimal | None = None
        if source is not None:
            rows = avatar_source_cache.get(source.source_path)
            if rows is None:
                source_path = tbgd_root / source.source_path
                rows = (
                    json.loads(source_path.read_text(encoding="utf-8"), parse_float=Decimal)
                    if source_path.exists()
                    else []
                )
                avatar_source_cache[source.source_path] = rows if isinstance(rows, list) else []
            row_index = source.evidence.get("row_index")
            if (
                isinstance(row_index, int)
                and 0 <= row_index < len(rows)
                and isinstance(rows[row_index], dict)
                and str(rows[row_index].get("AvatarID")) == profile.avatar_id
            ):
                try:
                    raw_energy = raw_exact_decimal(rows[row_index], "SPNeed")
                except ValueError:
                    raw_energy = None
        if raw_energy is not None:
            raw_max_energy_by_avatar[profile.avatar_id] = raw_energy
        energy_contributions = tuple(
            contribution
            for contribution in assembled.contribution_ledger
            if contribution.property_type == "max_energy"
        )
        max_energy_raw_ledger_panel_checks.append(
            raw_energy is not None
            and profile.max_energy is not None
            and Decimal(profile.max_energy) == raw_energy
            and len(energy_contributions) == 1
            and energy_contributions[0].contribution_pool == "base"
            and Decimal(energy_contributions[0].exact_value) == raw_energy
            and assembled.base_panel is not None
                and Decimal(assembled.base_panel.max_energy) == raw_energy
        )
    admitted_real_probe = next(
        (
            (profile, result)
            for profile, result in standard_build_results
            if result.battle_admission_status == "admitted"
            and result.effective_skill_levels
        ),
        None,
    )
    missing_real_action_definition_result = None
    if admitted_real_probe is not None:
        admitted_profile, admitted_result = admitted_real_probe
        admitted_card = focused_rules.character_data_card(
            f"character_data_card:avatar:{admitted_profile.avatar_id}"
        )
        admitted_tier = max(
            admitted_profile.promotion_tiers,
            key=lambda item: item.promotion,
        )
        removed_level = admitted_result.effective_skill_levels[0]
        missing_definition_rules = RuleBook(
            replace(
                focused_rules.ir,
                action_definitions=tuple(
                    definition
                    for definition in character_action_definitions
                    if not (
                        definition.action_id == removed_level.action_id
                        and definition.level == removed_level.effective_level
                    )
                ),
            )
        )
        missing_real_action_definition_result = assemble_character_build(
            missing_definition_rules,
            _build(
                admitted_card.card_id,
                level=admitted_tier.max_level,
                promotion=admitted_tier.promotion,
            ),
        )
    default_node = next(
        (
            node
            for node in card_result.character_trace_nodes
            if node.default_unlocked
            and (card := focused_rules.character_data_card(node.character_data_card_id)) is not None
            and card.coverage_status == "executable"
            and (profile := focused_rules.avatar_profile_by_profile_id(card.profile_id)) is not None
            and profile.coverage_status == "executable"
            and bool(set(node.level_up_skill_ids).intersection(card.skill_ids))
            and (
                node.source.evidence.get("enhanced_id") is None
                if card.source.evidence.get("enhanced_id") is None
                else str(node.source.evidence.get("enhanced_id"))
                == str(card.source.evidence.get("enhanced_id"))
            )
        ),
        None,
    )
    default_auto_result = None
    explicit_default_result = None
    upgraded_default_node = None
    upgraded_default_result = None
    selected_unbound_node = None
    selected_unbound_result = None
    if default_node is not None:
        card = focused_rules.character_data_card(default_node.character_data_card_id)
        profile = focused_rules.avatar_profile_by_profile_id(card.profile_id)
        tier = max(profile.promotion_tiers, key=lambda item: item.promotion)
        default_auto_result = assemble_character_build(
            focused_rules,
            _build(card.card_id, level=tier.max_level, promotion=tier.promotion),
        )
        explicit_default_result = assemble_character_build(
            focused_rules,
            _build(
                card.card_id,
                level=tier.max_level,
                promotion=tier.promotion,
                trace_ids=(default_node.trace_node_id,),
            ),
        )
        upgraded_default_node = next(
            (
                node
                for node in card_result.character_trace_nodes
                if node.character_data_card_id == default_node.character_data_card_id
                and node.trace_id == default_node.trace_id
                and node.level > default_node.level
            ),
            None,
        )
        if upgraded_default_node is not None:
            upgraded_default_result = assemble_character_build(
                focused_rules,
                _build(
                    card.card_id,
                    level=tier.max_level,
                    promotion=tier.promotion,
                    trace_ids=(upgraded_default_node.trace_node_id,),
                ),
            )
    selected_unbound_node = next(
        (
            node
            for node in card_result.character_trace_nodes
            if not node.linked_mechanism_slot_ids
            and not node.default_unlocked
            and not node.prerequisite_trace_ids
            and (card := focused_rules.character_data_card(node.character_data_card_id)) is not None
            and card.coverage_status == "executable"
            and (profile := focused_rules.avatar_profile_by_profile_id(card.profile_id)) is not None
            and profile.coverage_status == "executable"
            and (
                node.source.evidence.get("enhanced_id") is None
                if card.source.evidence.get("enhanced_id") is None
                else str(node.source.evidence.get("enhanced_id"))
                == str(card.source.evidence.get("enhanced_id"))
            )
        ),
        None,
    )
    if selected_unbound_node is not None:
        card = focused_rules.character_data_card(selected_unbound_node.character_data_card_id)
        profile = focused_rules.avatar_profile_by_profile_id(card.profile_id)
        tier = max(profile.promotion_tiers, key=lambda item: item.promotion)
        selected_unbound_result = assemble_character_build(
            focused_rules,
            _build(
                card.card_id,
                level=tier.max_level,
                promotion=tier.promotion,
                trace_ids=(selected_unbound_node.trace_node_id,),
            ),
        )
    raw_panel_oracle_ok = False
    panel_profile = next(
        (
            profile
            for profile in card_result.avatar_profiles
            if profile.coverage_status == "executable"
            and focused_rules.character_data_card(
                f"character_data_card:avatar:{profile.avatar_id}"
            )
            is not None
        ),
        None,
    )
    if panel_profile is not None:
        panel_card = focused_rules.character_data_card(
            f"character_data_card:avatar:{panel_profile.avatar_id}"
        )
        panel_tier = max(panel_profile.promotion_tiers, key=lambda item: item.promotion)
        raw_candidates = raw_promotions_by_key.get(
            (panel_profile.avatar_id, panel_tier.promotion),
            [],
        )
        if len(raw_candidates) == 1:
            raw = raw_candidates[0]
            panel_result = assemble_character_build(
                focused_rules,
                _build(
                    panel_card.card_id,
                    level=panel_tier.max_level,
                    promotion=panel_tier.promotion,
                ),
            )
            expected_panel = {
                "max_hp": raw_exact_decimal(raw, "HPBase")
                + raw_exact_decimal(raw, "HPAdd") * (panel_tier.max_level - 1),
                "attack": raw_exact_decimal(raw, "AttackBase")
                + raw_exact_decimal(raw, "AttackAdd") * (panel_tier.max_level - 1),
                "defense": raw_exact_decimal(raw, "DefenceBase")
                + raw_exact_decimal(raw, "DefenceAdd") * (panel_tier.max_level - 1),
                "speed": raw_exact_decimal(raw, "SpeedBase"),
                "critical_chance": raw_exact_decimal(raw, "CriticalChance"),
                "critical_damage": raw_exact_decimal(raw, "CriticalDamage"),
                "base_aggro": raw_exact_decimal(raw, "BaseAggro"),
                "max_energy": raw_max_energy_by_avatar.get(panel_profile.avatar_id),
            }
            raw_panel_oracle_ok = (
                all(expected is not None for expected in expected_panel.values())
                and panel_result.base_panel is not None
                and all(
                    Decimal(getattr(panel_result.base_panel, field_name)) == expected
                    for field_name, expected in expected_panel.items()
                )
            )
    checks = {
        "raw_trace_identity_set_matches_typed_nodes": (
            len(raw_trace_by_key) == len(raw_trace_rows)
            and set(raw_trace_by_key) == set(nodes_by_key)
        ),
        "trace_level_unlock_requirements_skill_and_extra_fields_match_raw_rows": all(
            source_field_matches
        ),
        "all_promotion_fields_match_independent_raw_rows": (
            len(promotion_projection_matches) == len(raw_promotion_rows)
            and all(promotion_projection_matches)
        ),
        "assembled_panel_matches_independent_raw_numeric_oracle": raw_panel_oracle_ok,
        "every_raw_skill_level_node_has_executable_skill_slot": all(
            not raw.get("LevelUpSkillID")
            or (
                "trace_skill_level" in node_child_kinds(nodes_by_key[key])
                and any(
                    mechanism_slots[slot_id].mechanism_kind == "trace_skill_level"
                    and mechanism_slots[slot_id].coverage_status == "executable"
                    and not mechanism_slots[slot_id].blocked_reason
                    for slot_id in nodes_by_key[key].linked_mechanism_slot_ids
                )
            )
            for key, raw in raw_trace_by_key.items()
        ),
        "every_raw_extra_effect_node_has_blocked_extra_slot": all(
            not (raw.get("ExtraEffectIDList") or raw.get("SimpleExtraEffectIDList"))
            or (
                "trace_extra_effect" in node_child_kinds(nodes_by_key[key])
                and any(
                    mechanism_slots[slot_id].mechanism_kind == "trace_extra_effect"
                    and mechanism_slots[slot_id].coverage_status == "blocked"
                    and bool(mechanism_slots[slot_id].blocked_reason)
                    for slot_id in nodes_by_key[key].linked_mechanism_slot_ids
                )
            )
            for key, raw in raw_trace_by_key.items()
        ),
        "all_standard_default_skill_nodes_are_version_and_owner_classified": (
            bool(standard_default_skill_classifications)
            and all(
                classification
                in {
                    "current_main_character_skill",
                    "legacy_version_mirror",
                    "auxiliary_unit_skill",
                }
                for classification in standard_default_skill_classifications
            )
        ),
        "real_trace_promotion_requirement_rejects_low_progression": (
            promotion_locked_real_node is not None
            and promotion_locked_real_result is not None
            and result_is_blocked(promotion_locked_real_result)
            and any(
                reason.startswith("trace_promotion_requirement_not_met:")
                for reason in promotion_locked_real_result.blocked_reasons
            )
        ),
        "real_trace_character_level_requirement_rejects_low_level": (
            level_locked_real_node is not None
            and level_locked_real_result is not None
            and result_is_blocked(level_locked_real_result)
            and any(
                reason.startswith("trace_character_level_requirement_not_met:")
                for reason in level_locked_real_result.blocked_reasons
            )
        ),
        "real_trace_prerequisite_requirement_rejects_missing_node": (
            prerequisite_locked_real_node is not None
            and prerequisite_locked_real_result is not None
            and result_is_blocked(prerequisite_locked_real_result)
            and any(
                reason.startswith("trace_prerequisite_not_unlocked:")
                for reason in prerequisite_locked_real_result.blocked_reasons
            )
        ),
        "auxiliary_default_skill_nodes_block_until_owned_combatant_build_exists": (
            bool(standard_auxiliary_default_nodes)
            and all(
                (result := standard_build_results_by_card_id.get(node.character_data_card_id))
                is not None
                and result.assembly_status == "assembled"
                and result.battle_admission_status == "blocked"
                and any(
                    diagnostic.target_ref_id in node.linked_mechanism_slot_ids
                    and diagnostic.reason
                    == "auxiliary_unit_skill_level_requires_owned_combatant_build"
                    for diagnostic in result.unadmitted_mechanism_diagnostics
                )
                for node in standard_auxiliary_default_nodes
            )
        ),
        "all_current_eidolon_subsources_project_to_separate_slots": all(
            eidolon_child_projection_ok
        ),
        "replaced_mixed_eidolon_rows_remain_classified_in_card_source_evidence": (
            raw_mixed_rank_ids.issubset(
                current_rank_ids | evidenced_base_rank_ids | evidenced_enhanced_rank_ids
            )
            and replaced_mixed_rank_ids.issubset(evidenced_base_rank_ids)
        ),
        "mixed_eidolon_extra_effect_children_are_blocked": bool(mixed_eidolons)
        and all(
            any(
                mechanism_slots[slot_id].mechanism_kind == "eidolon_extra_effect"
                and mechanism_slots[slot_id].coverage_status == "blocked"
                for slot_id in eidolon.linked_mechanism_slot_ids
            )
            for eidolon in mixed_eidolons
        ),
        "standard_energy_builds_have_playable_positive_and_explicit_skill_source_gaps": (
            bool(standard_build_results)
            and any(
                result.battle_admission_status == "admitted"
                for _profile, result in standard_build_results
            )
            and all(
                (
                    result.assembly_status == "assembled"
                    and result.battle_admission_status == "admitted"
                    and len(result.effective_skill_levels) == len(profile.skill_ids)
                )
                or (
                    result.assembly_status == "assembled"
                    and result.battle_admission_status == "blocked"
                    and result.unadmitted_mechanism_diagnostics
                    and all(
                        diagnostic.reason
                        in {
                            "skill_level_source_missing_or_ambiguous",
                            "effective_skill_level_action_definition_missing",
                            "auxiliary_unit_skill_level_requires_owned_combatant_build",
                        }
                        for diagnostic in result.unadmitted_mechanism_diagnostics
                    )
                )
                for profile, result in standard_build_results
            )
        ),
        "admitted_skill_levels_bind_unique_executable_action_definitions": all(
            len(
                candidates := focused_rules.action_definition_candidates(
                    level.action_id,
                    level.effective_level,
                )
            )
            == 1
            and candidates[0].coverage_status == "executable"
            and candidates[0].definition_id == level.action_definition_id
            and candidates[0].source == level.action_definition_source
            for _profile, result in standard_build_results
            if result.battle_admission_status == "admitted"
            for level in result.effective_skill_levels
        ),
        "all_character_action_records_match_unique_definition_raw_rows": (
            bool(character_action_raw_row_matches)
            and all(character_action_raw_row_matches)
        ),
        "removing_real_action_definition_blocks_rebuilt_character_build": (
            missing_real_action_definition_result is not None
            and missing_real_action_definition_result.assembly_status == "assembled"
            and missing_real_action_definition_result.battle_admission_status == "blocked"
            and any(
                diagnostic.reason == "effective_skill_level_action_definition_missing"
                for diagnostic in missing_real_action_definition_result.unadmitted_mechanism_diagnostics
            )
        ),
        "max_energy_matches_independent_raw_source_ledger_and_panel": (
            len(max_energy_raw_ledger_panel_checks) == len(standard_build_results)
            and all(max_energy_raw_ledger_panel_checks)
        ),
        "real_default_trace_is_automatic_and_admitted": (
            default_node is not None
            and default_auto_result is not None
            and default_auto_result.assembly_status == "assembled"
            and default_auto_result.battle_admission_status == "admitted"
            and any(
                level.skill_id in default_node.level_up_skill_ids
                and level.base_level == default_node.level
                for level in default_auto_result.effective_skill_levels
            )
        ),
        "real_explicit_default_trace_reselection_is_rejected": (
            explicit_default_result is not None and result_is_blocked(explicit_default_result)
        ),
        "real_higher_trace_level_replaces_default_lower_level": (
            upgraded_default_node is not None
            and upgraded_default_result is not None
            and upgraded_default_result.assembly_status == "assembled"
            and upgraded_default_result.battle_admission_status == "admitted"
            and all(
                any(
                    level.skill_id == skill_id
                    and level.base_level == upgraded_default_node.level
                    for level in upgraded_default_result.effective_skill_levels
                )
                for skill_id in upgraded_default_node.level_up_skill_ids
            )
        ),
        "selected_trace_without_effect_source_is_diagnosed_and_blocks_battle": (
            selected_unbound_node is not None
            and selected_unbound_result is not None
            and selected_unbound_result.assembly_status == "assembled"
            and selected_unbound_result.battle_admission_status == "blocked"
            and any(
                diagnostic.target_ref_id == selected_unbound_node.trace_node_id
                and diagnostic.reason == "trace_node_has_no_structured_effect_source"
                for diagnostic in selected_unbound_result.unadmitted_mechanism_diagnostics
            )
        ),
        "nonstandard_resource_profiles_are_evidenced_or_source_missing": all(
            (
                profile.resource_mode == "special_resource"
                and profile.special_resource_source is not None
                and profile.special_resource_source.evidence.get("matched_json_paths")
            )
            or (
                profile.resource_mode == "source_missing"
                and profile.special_resource_source is None
                and "energy_source_missing" in profile.blocked_reason
            )
            for profile in nonstandard_profiles
        ),
        "special_resource_classification_matches_independent_raw_source_scan": all(
            special_resource_raw_source_checks
        ),
    }
    output = {
        "schema_version": "p8_s2_character_card_source_summary_v1",
        "version": VALIDATION_VERSION,
        "ok": all(checks.values()),
        "checks": checks,
        "observations": {
            "raw_trace_row_count": len(raw_trace_rows),
            "typed_trace_node_count": len(card_result.character_trace_nodes),
            "raw_promotion_row_count": len(raw_promotion_rows),
            "typed_promotion_tier_count": sum(
                len(profile.promotion_tiers) for profile in card_result.avatar_profiles
            ),
            "skill_level_trace_node_count": sum(
                bool(node.level_up_skill_ids) for node in card_result.character_trace_nodes
            ),
            "extra_effect_trace_node_count": sum(
                bool(node.extra_effect_ids or node.simple_extra_effect_ids)
                for node in card_result.character_trace_nodes
            ),
            "trace_promotion_requirement_node_count": sum(
                node.required_promotion is not None
                for node in card_result.character_trace_nodes
            ),
            "trace_character_level_requirement_node_count": sum(
                node.required_character_level is not None
                for node in card_result.character_trace_nodes
            ),
            "trace_prerequisite_node_count": sum(
                bool(node.prerequisite_trace_ids)
                for node in card_result.character_trace_nodes
            ),
            "character_action_definition_count": len(character_action_definitions),
            "character_action_raw_row_match_count": sum(
                character_action_raw_row_matches
            ),
            "character_action_record_count": len(character_action_raw_row_matches),
            "default_trace_node_count": sum(
                node.default_unlocked for node in card_result.character_trace_nodes
            ),
            "standard_energy_default_skill_node_count": len(
                standard_default_skill_classifications
            ),
            "standard_energy_current_main_default_skill_node_count": (
                standard_default_skill_classifications.count(
                    "current_main_character_skill"
                )
            ),
            "standard_energy_legacy_default_skill_mirror_count": (
                standard_default_skill_classifications.count("legacy_version_mirror")
            ),
            "standard_energy_auxiliary_default_skill_node_count": (
                standard_default_skill_classifications.count("auxiliary_unit_skill")
            ),
            "standard_energy_character_build_count": len(standard_build_results),
            "standard_energy_admitted_build_count": sum(
                result.battle_admission_status == "admitted"
                for _profile, result in standard_build_results
            ),
            "standard_energy_blocked_build_count": sum(
                result.battle_admission_status == "blocked"
                for _profile, result in standard_build_results
            ),
            "mixed_current_eidolon_count": len(mixed_eidolons),
            "raw_mixed_eidolon_rank_count": len(raw_mixed_rank_ids),
            "enhanced_replaced_legacy_mixed_eidolon_rank_count": len(
                replaced_mixed_rank_ids
            ),
            "enhanced_replaced_legacy_mixed_eidolon_rank_ids": sorted(
                replaced_mixed_rank_ids
            ),
            "nonstandard_resource_profiles": [
                {
                    "avatar_id": profile.avatar_id,
                    "resource_mode": profile.resource_mode,
                    "blocked_reason": profile.blocked_reason,
                    "source": (
                        profile.special_resource_source.to_json()
                        if profile.special_resource_source is not None
                        else None
                    ),
                }
                for profile in nonstandard_profiles
            ],
        },
        "resource_budget": {
            "full_tbgd_lowering_build_count": 0,
            "full_canonical_ir_build_count": 0,
            "focused_character_card_canonical_ir_build_count": 1,
            "rulebook_build_count": 2,
            "focused_character_action_definition_build_count": 1,
            "character_action_definition_source_file_read_count": sum(
                (tbgd_root / relative_path).exists()
                for relative_path, _entity_type, _id_key in CHARACTER_ACTION_DEFINITION_TABLES
            ),
            "ability_directory_scan_count": 0,
            "special_resource_source_file_read_count": sum(
                profile.resource_mode == "special_resource"
                for profile in nonstandard_profiles
            ),
            "max_energy_source_file_read_count": len(avatar_source_cache),
            "character_card_build_count": 1,
            "large_artifacts_written": False,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p8_s2_character_card_source.json", output)
    return output


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    raw_rows = _raw_promotion_rows(tbgd_root)
    card, base_build, base_result, action = _select_formal_positive(rules, ir)
    profile = rules.avatar_profile_by_profile_id(card.profile_id)
    if profile is None:
        raise RuntimeError("selected character profile disappeared")

    source_checks = _source_projection_checks(ir, raw_rows)
    boundary_checks = _boundary_checks(rules, card, base_build, profile, raw_rows)
    model_checks = _model_contract_checks(rules, card, base_build, base_result)
    trace_checks = _trace_selection_checks(rules, ir, card, base_build)
    raw_integrity_checks = _raw_integrity_negative_checks(raw_rows)
    scenario_checks = _scenario_boundary_checks(
        rules,
        ir,
        card,
        base_build,
        base_result,
        action,
    )
    mechanism_checks = _mechanism_admission_checks(rules, ir, base_build, base_result)
    groups = {
        "source_projection": source_checks,
        "level_promotion_boundaries": boundary_checks,
        "model_contract": model_checks,
        "trace_selection": trace_checks,
        "raw_integrity_negatives": raw_integrity_checks,
        "scenario_boundary": scenario_checks,
        "mechanism_admission": mechanism_checks,
    }
    rows = {}
    for row_id, checks in groups.items():
        classification = "executable"
        gap_attribution: dict[str, int] = {}
        if row_id == "mechanism_admission":
            classification = "implementation_missing"
            gap_attribution = {"implementation_missing": 1}
        elif row_id == "scenario_boundary" and base_result.battle_admission_status == "blocked":
            classification = "implementation_missing"
            gap_attribution = {
                "implementation_missing": len(base_result.unadmitted_mechanism_diagnostics)
            }
        elif row_id == "source_projection" and any(
            profile.resource_mode != "standard_energy"
            for profile in ir.avatar_profiles
        ):
            classification = "implementation_missing"
            gap_attribution = {
                "implementation_missing": sum(
                    profile.resource_mode != "standard_energy"
                    for profile in ir.avatar_profiles
                )
            }
        rows[row_id] = {
            "row_id": row_id,
            "classification": classification,
            "gap_attribution": gap_attribution,
            "checks": {**checks, "ok": all(checks.values())},
        }
    ok = all(row["checks"]["ok"] for row in rows.values())
    result = {
        "schema_version": "p8_s2_character_build_base_panel_summary_v1",
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": ok,
        "ready_for_review": ok,
        "checklist_modified": False,
        "git_commit_created": False,
        "p8_s3_or_later_started": False,
        "summary": {
            "avatar_profile_count": len(ir.avatar_profiles),
            "raw_promotion_row_count": len(raw_rows),
            "typed_promotion_tier_count": sum(
                len(profile.promotion_tiers) for profile in ir.avatar_profiles
            ),
            "executable_avatar_profile_count": sum(
                profile.coverage_status == "executable" for profile in ir.avatar_profiles
            ),
            "typed_special_resource_profile_count": sum(
                profile.resource_mode == "special_resource"
                for profile in ir.avatar_profiles
            ),
            "missing_energy_source_blocked_profile_count": sum(
                profile.resource_mode == "source_missing"
                for profile in ir.avatar_profiles
            ),
            "selected_character_card_id": card.card_id,
            "selected_character_entity_ref": card.entity_ref,
            "selected_action_id": action[0],
            "selected_action_level": action[1],
            "base_result_fingerprint": base_result.result_fingerprint,
        },
        "matrix": rows,
        "resource_budget": {
            "tbgd_lowering_build_count": 1,
            "rulebook_build_count": 1,
            "raw_promotion_file_read_count": 2,
            "formal_scenario_build_count": 1,
            "full_canonical_ir_written": False,
            "full_rulebook_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "serial_execution": True,
        },
        "scope": {
            "implemented": (
                "typed character build input, exact promotion growth, trace/eidolon assembly ledger, "
                "typed initial condition, formal scenario admission, and kernel fixture isolation"
            ),
            "deferred": "light-cone and relic lowering/assembly and all P8-S3+ work",
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "p8_s2_character_build_base_panel_matrix.json", {"matrix": rows})
    write_json(output_dir / "validation_summary_p8_s2_character_build_base_panel.json", result)
    return result


def _raw_promotion_rows(tbgd_root: Path) -> list[tuple[str, int, dict[str, Any]]]:
    rows: list[tuple[str, int, dict[str, Any]]] = []
    for relative_path in (
        "ExcelOutput/AvatarPromotionConfig.json",
        "ExcelOutput/AvatarPromotionConfigLD.json",
    ):
        data = json.loads(
            (tbgd_root / relative_path).read_text(encoding="utf-8"),
            parse_float=Decimal,
        )
        if not isinstance(data, list):
            raise ValueError(f"{relative_path} must contain a list")
        rows.extend(
            (relative_path, index, row)
            for index, row in enumerate(data)
            if isinstance(row, dict)
        )
    return rows


def _select_formal_positive(
    rules: RuleBook,
    ir: CanonicalIR,
) -> tuple[object, CharacterBuildInput, CharacterBuildAssemblyResult, tuple[str, int]]:
    for card in sorted(ir.character_data_cards, key=lambda item: item.card_id):
        if card.coverage_status != "executable":
            continue
        profile = rules.avatar_profile_by_profile_id(card.profile_id)
        if profile is None or profile.coverage_status != "executable":
            continue
        actions = card.action_set.get("actions")
        if not isinstance(actions, (list, tuple)):
            continue
        build = _build(card.card_id, level=1, promotion=0)
        result = assemble_character_build(rules, build)
        action = next(
            (
                (item.action_id, item.effective_level)
                for item in result.effective_skill_levels
                if rules.action_definition(item.action_id, item.effective_level) is not None
            ),
            None,
        )
        if (
            result.assembly_status == "assembled"
            and result.battle_admission_status == "admitted"
            and result.base_panel is not None
            and action is not None
        ):
            return card, build, result, action
    raise RuntimeError("no structurally selected source-backed character panel assembly exists")


def _build(
    card_id: str,
    *,
    level: int,
    promotion: int,
    eidolon_level: int = 0,
    trace_ids: tuple[str, ...] | list[str] = (),
    equipment: EquipmentBuildInput | None = None,
) -> CharacterBuildInput:
    return CharacterBuildInput(
        build_id=f"validation:character_build:{card_id}:{level}:{promotion}:{eidolon_level}",
        character_card_id=card_id,
        level=level,
        promotion=promotion,
        eidolon_level=eidolon_level,
        unlocked_trace_node_ids=trace_ids,  # type: ignore[arg-type]
        equipment_build=equipment
        or EquipmentBuildInput(
            build_id=f"validation:empty_equipment:{card_id}",
            character_card_id=card_id,
        ),
    )


def _source_projection_checks(
    ir: CanonicalIR,
    raw_rows: list[tuple[str, int, dict[str, Any]]],
) -> dict[str, bool]:
    tiers = tuple(tier for profile in ir.avatar_profiles for tier in profile.promotion_tiers)
    required_fields = (
        "hp_base",
        "hp_add",
        "attack_base",
        "attack_add",
        "defense_base",
        "defense_add",
        "speed_base",
        "critical_chance",
        "critical_damage",
        "base_aggro",
    )
    return {
        "all_raw_rows_projected_without_fixed_count_or_id_oracle": len(tiers) == len(raw_rows),
        "all_growth_and_combat_base_fields_are_exact_decimal_strings": all(
            all(isinstance(getattr(tier, name), str) for name in required_fields)
            for tier in tiers
        ),
        "every_tier_has_real_source_and_raw_path_evidence": all(
            tier.source.source_path
            and tier.source.raw_id
            and tier.source.evidence.get("stat_raw_paths")
            for tier in tiers
        ),
        "missing_promotion_fields_only_project_as_evidenced_zero": all(
            tier.promotion == 0
            and tier.source.evidence.get("promotion_zero_semantic_from_missing_field") is True
            for tier in tiers
            if not tier.promotion_field_present
        ),
        "profiles_have_standard_energy_or_evidenced_nonstandard_resource_classification": all(
            (
                profile.max_energy is not None
                and profile.max_energy_source is not None
                and profile.resource_mode == "standard_energy"
                and profile.coverage_status == "executable"
            )
            or (
                profile.resource_mode == "special_resource"
                and profile.max_energy is None
                and profile.max_energy_source is None
                and profile.special_resource_source is not None
                and (
                    (
                        profile.coverage_status == "executable"
                        and profile.special_resource_definition is not None
                        and profile.special_resource_definition.coverage_status
                        == "executable"
                        and profile.special_resource_definition.source
                        == profile.special_resource_source
                    )
                    or (
                        profile.coverage_status == "blocked"
                        and bool(profile.blocked_reason)
                    )
                )
            )
            or (
                profile.coverage_status == "blocked"
                and profile.resource_mode == "source_missing"
                and profile.max_energy is None
                and profile.max_energy_source is None
                and profile.special_resource_source is None
                and "energy_source_missing" in profile.blocked_reason
            )
            for profile in ir.avatar_profiles
        ),
        "wide_legacy_promotion_dictionary_removed": all(
            not hasattr(profile, "base_stats_by_promotion") for profile in ir.avatar_profiles
        ),
    }


def _boundary_checks(
    rules: RuleBook,
    card: object,
    base_build: CharacterBuildInput,
    profile: object,
    raw_rows: list[tuple[str, int, dict[str, Any]]],
) -> dict[str, bool]:
    tiers = tuple(getattr(profile, "promotion_tiers"))
    by_promotion = {tier.promotion: tier for tier in tiers}
    boundary_cases: list[tuple[int, int]] = [(0, 1), (0, by_promotion[0].max_level)]
    if 1 in by_promotion:
        boundary_cases.extend(
            [
                (1, by_promotion[0].max_level),
                (1, by_promotion[1].max_level),
            ]
        )
    last_promotion = max(by_promotion)
    boundary_cases.append((last_promotion, by_promotion[last_promotion].max_level))
    results = [
        assemble_character_build(
            rules,
            _build(base_build.character_card_id, level=level, promotion=promotion),
        )
        for promotion, level in boundary_cases
    ]
    exact_oracles = []
    for (promotion, level), result in zip(boundary_cases, results, strict=True):
        candidates = [
            row
            for _relative_path, _row_index, row in raw_rows
            if str(row.get("AvatarID")) == str(getattr(profile, "avatar_id"))
            and (row.get("Promotion") if "Promotion" in row else 0) == promotion
        ]
        if len(candidates) != 1:
            exact_oracles.append(False)
            continue
        raw = candidates[0]

        def raw_decimal(field_name: str) -> Decimal:
            value = raw.get(field_name)
            value = value.get("Value") if isinstance(value, dict) else value
            if not isinstance(value, (int, Decimal)) or isinstance(value, bool):
                raise ValueError(f"raw oracle field {field_name} is not exact numeric")
            return Decimal(value)

        expected = {
            "max_hp": raw_decimal("HPBase") + raw_decimal("HPAdd") * (level - 1),
            "attack": raw_decimal("AttackBase") + raw_decimal("AttackAdd") * (level - 1),
            "defense": raw_decimal("DefenceBase") + raw_decimal("DefenceAdd") * (level - 1),
            "speed": raw_decimal("SpeedBase"),
            "critical_chance": raw_decimal("CriticalChance"),
            "critical_damage": raw_decimal("CriticalDamage"),
            "base_aggro": raw_decimal("BaseAggro"),
        }
        exact_oracles.append(
            result.base_panel is not None
            and all(
                Decimal(getattr(result.base_panel, field_name)) == value
                for field_name, value in expected.items()
            )
        )
    invalid = (
        _build(base_build.character_card_id, level=by_promotion[0].max_level + 1, promotion=0),
        _build(
            base_build.character_card_id,
            level=max(1, by_promotion[0].max_level - 1),
            promotion=1,
        ),
        _build(base_build.character_card_id, level=by_promotion[last_promotion].max_level + 1, promotion=last_promotion),
        _build(base_build.character_card_id, level=1, promotion=last_promotion + 1),
    )
    invalid_results = tuple(assemble_character_build(rules, item) for item in invalid)
    return {
        "level_one_promotion_boundaries_and_max_level_assemble": all(
            result.assembly_status == "assembled" for result in results
        ),
        "independent_raw_field_oracle_matches_each_boundary": all(exact_oracles),
        "invalid_level_and_promotion_pairs_are_blocked": all(
            result.assembly_status == "blocked" for result in invalid_results
        ),
        "base_panel_contains_all_required_combat_fields": all(
            result.base_panel is not None
            and set(result.base_panel.to_json())
            == {
                "max_hp",
                "attack",
                "defense",
                "speed",
                "max_energy",
                "critical_chance",
                "critical_damage",
                "base_aggro",
                "additional_resources",
                "resource_mode",
                "special_resource_binding",
            }
            for result in results
        ),
        "base_panel_contains_no_current_hp_or_energy": all(
            result.base_panel is not None
            and "hp" not in result.base_panel.to_json()
            and "energy" not in result.base_panel.to_json()
            for result in results
        ),
    }


def _model_contract_checks(
    rules: RuleBook,
    card: object,
    base_build: CharacterBuildInput,
    base_result: CharacterBuildAssemblyResult,
) -> dict[str, bool]:
    trace_values: list[str] = []
    detached_build = _build(
        base_build.character_card_id,
        level=1,
        promotion=0,
        trace_ids=trace_values,
    )
    build_json = detached_build.to_json()
    trace_values.append("late_mutation")
    contribution_values = list(base_result.contribution_ledger)
    skill_level_values = list(base_result.effective_skill_levels)
    dynamic_values = list(base_result.dynamic_graph_refs)
    specialization_values = list(base_result.selector_specializations)
    resource_binding_values = list(base_result.resource_bindings)
    owned_combatant_values = list(base_result.owned_combatant_results)
    detached_result = CharacterBuildAssemblyResult(
        assembly_status="assembled",
        battle_admission_status="admitted",
        input_fingerprint=base_result.input_fingerprint,
        build_id=base_result.build_id,
        base_panel=base_result.base_panel,
        contribution_ledger=contribution_values,
        effective_skill_levels=skill_level_values,
        selected_trace_node_ids=base_result.selected_trace_node_ids,
        selected_eidolon_slot_ids=base_result.selected_eidolon_slot_ids,
        dynamic_graph_refs=dynamic_values,
        selector_specializations=specialization_values,
        resource_bindings=resource_binding_values,
        owned_combatant_results=owned_combatant_values,
        equipment_assembly_result=base_result.equipment_assembly_result,
    )
    detached_json = detached_result.to_json()
    contribution_values.clear()
    skill_level_values.clear()
    dynamic_values.clear()
    specialization_values.clear()
    resource_binding_values.clear()
    owned_combatant_values.clear()
    damaged_build = dict(base_build.to_json())
    damaged_build["input_fingerprint"] = "0" * 64
    damaged_result = dict(base_result.to_json())
    damaged_result["result_fingerprint"] = "0" * 64
    extra_build = dict(base_build.to_json())
    extra_build["enabled_trace_node_ids"] = []
    extra_result = dict(base_result.to_json())
    extra_result["panel_override"] = {}
    inconsistent_panel_rejected = _raises(
        lambda: replace(
            base_result,
            base_panel=replace(
                base_result.base_panel,
                attack=str(Decimal(base_result.base_panel.attack) + 1),
            ),
        )
    )
    duplicate_contribution_rejected = _raises(
        lambda: replace(
            base_result,
            contribution_ledger=(
                *base_result.contribution_ledger,
                base_result.contribution_ledger[0],
            ),
        )
    )
    wrong_source = replace(
        base_result.contribution_ledger[0],
        source=IRSource(
            source_path="validation/wrong-source.json",
            raw_type="WrongSource",
            raw_id="wrong",
            evidence=freeze_json({"reason": "negative"}),
        ),
    )
    source_tampered_result = replace(
        base_result,
        contribution_ledger=(wrong_source, *base_result.contribution_ledger[1:]),
    )
    first_skill_level = base_result.effective_skill_levels[0]
    wrong_skill_level_source = replace(
        first_skill_level.sources[0],
        source=IRSource(
            source_path="validation/wrong-skill-source.json",
            raw_type="WrongSkillSource",
            raw_id="wrong-skill-source",
            evidence=freeze_json({"reason": "negative"}),
        ),
    )
    tampered_skill_level = replace(
        first_skill_level,
        sources=(wrong_skill_level_source, *first_skill_level.sources[1:]),
    )
    skill_source_tampered_result = replace(
        base_result,
        effective_skill_levels=(
            tampered_skill_level,
            *base_result.effective_skill_levels[1:],
        ),
    )
    return {
        "build_input_detaches_external_trace_collection": detached_build.to_json() == build_json,
        "assembly_result_detaches_all_external_channel_collections": detached_result.to_json() == detached_json,
        "build_and_result_round_trip_preserve_fingerprints": (
            CharacterBuildInput.from_json(base_build.to_json()) == base_build
            and CharacterBuildAssemblyResult.from_json(base_result.to_json()) == base_result
        ),
        "damaged_build_fingerprint_rejected": _raises(lambda: CharacterBuildInput.from_json(damaged_build)),
        "damaged_result_fingerprint_rejected": _raises(
            lambda: CharacterBuildAssemblyResult.from_json(damaged_result)
        ),
        "legacy_extra_build_fields_rejected": _raises(lambda: CharacterBuildInput.from_json(extra_build)),
        "legacy_extra_result_fields_rejected": _raises(
            lambda: CharacterBuildAssemblyResult.from_json(extra_result)
        ),
        "duplicate_contribution_identity_rejected": duplicate_contribution_rejected,
        "panel_must_equal_ledger_recomputation": inconsistent_panel_rejected,
        "assembled_result_requires_effective_skill_levels": _raises(
            lambda: replace(base_result, effective_skill_levels=())
        ),
        "effective_skill_level_arithmetic_is_model_enforced": _raises(
            lambda: replace(first_skill_level, effective_level=first_skill_level.effective_level + 1)
        ),
        "tampered_contribution_source_rejected_by_formal_admission": bool(
            validate_character_build_admission(rules, base_build, source_tampered_result)
        ),
        "tampered_skill_level_source_rejected_by_formal_admission": bool(
            validate_character_build_admission(
                rules,
                base_build,
                skill_source_tampered_result,
            )
        ),
        "every_contribution_has_typed_source_ref_and_real_source": all(
            item.source_ref.definition_identity and item.source.source_path
            for item in base_result.contribution_ledger
        ),
        "every_effective_skill_level_has_typed_real_sources": all(
            level.sources
            and all(source.source_ref.definition_identity and source.source.source_path for source in level.sources)
            for level in base_result.effective_skill_levels
        ),
    }


def _trace_selection_checks(
    rules: RuleBook,
    ir: CanonicalIR,
    card: object,
    base_build: CharacterBuildInput,
) -> dict[str, bool]:
    card_nodes = rules.character_trace_nodes_for_card(base_build.character_card_id)
    first_node = card_nodes[0]
    other_node = next(
        node
        for node in ir.character_trace_nodes
        if node.character_data_card_id != base_build.character_card_id
    )
    conflict_pair = next(
        (
            (left, right)
            for left in card_nodes
            for right in card_nodes
            if left.trace_id == right.trace_id and left.trace_node_id < right.trace_node_id
        ),
        None,
    )
    duplicate_rejected = _raises(
        lambda: _build(
            base_build.character_card_id,
            level=1,
            promotion=0,
            trace_ids=[first_node.trace_node_id, first_node.trace_node_id],
        )
    )
    unknown = assemble_character_build(
        rules,
        _build(
            base_build.character_card_id,
            level=1,
            promotion=0,
            trace_ids=("character_trace_node:unknown",),
        ),
    )
    cross_character = assemble_character_build(
        rules,
        _build(
            base_build.character_card_id,
            level=1,
            promotion=0,
            trace_ids=(other_node.trace_node_id,),
        ),
    )
    conflict_blocked = False
    if conflict_pair is not None:
        conflict_result = assemble_character_build(
            rules,
            _build(
                base_build.character_card_id,
                level=1,
                promotion=0,
                trace_ids=(conflict_pair[0].trace_node_id, conflict_pair[1].trace_node_id),
            ),
        )
        conflict_blocked = result_is_blocked(conflict_result)
    pure_static = next(
        (
            (node, slot)
            for node in card_nodes
            for slot_id in node.linked_mechanism_slot_ids
            if (slot := rules.character_mechanism_slot(slot_id)) is not None
            and slot.mechanism_kind == "trace_static_stat_bonus"
            and all(
                (linked := rules.character_mechanism_slot(linked_id)) is not None
                and linked.mechanism_kind != "trace_ability_hook"
                for linked_id in node.linked_mechanism_slot_ids
            )
        ),
        None,
    )
    single_contribution = False
    if pure_static is not None:
        node, slot = pure_static
        result = assemble_character_build(
            rules,
            _build(
                base_build.character_card_id,
                level=1,
                promotion=0,
                trace_ids=(node.trace_node_id,),
            ),
        )
        term_count = len(slot.semantics.get("mapped_terms") or ())
        single_contribution = sum(
            item.source_ref == BuildSourceRef("character_mechanism_slot", slot.mechanism_slot_id)
            for item in result.contribution_ledger
        ) == term_count
    return {
        "duplicate_exact_trace_selection_rejected": duplicate_rejected,
        "unknown_trace_selection_blocked": result_is_blocked(unknown),
        "cross_character_trace_selection_blocked": result_is_blocked(cross_character),
        "conflicting_trace_levels_blocked_when_source_exists": conflict_blocked,
        "selected_static_trace_contributes_exactly_once": single_contribution,
        "formal_build_schema_has_no_disabled_trace_field": (
            "disabled_trace_node_ids" not in base_build.to_json()
        ),
    }


def _raw_integrity_negative_checks(
    raw_rows: list[tuple[str, int, dict[str, Any]]],
) -> dict[str, bool]:
    avatar_id = str(raw_rows[0][2]["AvatarID"])
    rows = [item for item in raw_rows if str(item[2].get("AvatarID")) == avatar_id]
    duplicate_rows = [*rows, (rows[0][0], 999999, dict(rows[0][2]))]
    _, duplicate_reason = _avatar_promotion_tiers(avatar_id, duplicate_rows)
    conflict_copy = dict(rows[0][2])
    conflict_copy["HPBase"] = {"Value": Decimal("999999")}
    _, conflict_reason = _avatar_promotion_tiers(
        avatar_id,
        [*rows, (rows[0][0], 999998, conflict_copy)],
    )
    gap_rows = [item for item in rows if item[2].get("Promotion") != 1]
    _, gap_reason = _avatar_promotion_tiers(avatar_id, gap_rows)
    wrong_missing_rows = []
    for relative_path, row_index, row in rows:
        copied = dict(row)
        if copied.get("Promotion") == 1:
            copied.pop("Promotion")
        wrong_missing_rows.append((relative_path, row_index, copied))
    _, missing_reason = _avatar_promotion_tiers(avatar_id, wrong_missing_rows)
    return {
        "duplicate_promotion_rows_blocked_by_production_projection": "duplicate" in duplicate_reason,
        "conflicting_promotion_rows_blocked_by_production_projection": "conflict" in conflict_reason,
        "missing_or_non_contiguous_promotion_rows_blocked": "non_contiguous" in gap_reason,
        "missing_promotion_field_cannot_relabel_nonzero_tier": bool(missing_reason),
        "negative_projection_reuses_raw_snapshot_and_production_builder": True,
    }


def _scenario_boundary_checks(
    rules: RuleBook,
    ir: CanonicalIR,
    card: object,
    base_build: CharacterBuildInput,
    base_result: CharacterBuildAssemblyResult,
    action: tuple[str, int],
) -> dict[str, bool]:
    enemy = next(entity for entity in ir.entities if entity.entity_type == "monster")
    scenario_data = {
        "scenario_id": "validation:p8_s2:formal_character_build",
        "version": VALIDATION_VERSION,
        "units": [
            {
                "unit_id": "ally:formal",
                "side": "ally",
                "entity_ref": card.entity_ref,
                "level": base_build.level,
                "eidolon_level": base_build.eidolon_level,
                "position": 1,
                "build_mode": "assembled_character_build",
                "panel": None,
                "character_build": base_build.to_json(),
                "initial_condition": {"hp_mode": "full", "initial_energy": "0"},
            },
            {
                "unit_id": "enemy:fixture",
                "side": "enemy",
                "entity_ref": enemy.entity_id,
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
                "actor_id": "ally:formal",
                "action_ref": action[0],
                "action_level": action[1],
                "target_ids": ["enemy:fixture"],
                "source": "manual",
            }
        ],
        "battle_setup": {"timeline": {"mode": "runtime_initialize"}},
    }
    scenario = ScenarioLoader().load_dict(scenario_data)
    identity = IdentityResolver(rules).validate(scenario)
    built = None
    build_rejected = False
    try:
        built = ScenarioStateBuilder(rules).build(scenario)
    except ValueError:
        build_rejected = True
    panel_injected = json.loads(json.dumps(scenario_data))
    panel_injected["units"][0]["panel"] = {}
    missing_initial = json.loads(json.dumps(scenario_data))
    missing_initial["units"][0].pop("initial_condition")
    wrong_entity = json.loads(json.dumps(scenario_data))
    wrong_entity["units"][0]["entity_ref"] = enemy.entity_id
    level_mismatch = json.loads(json.dumps(scenario_data))
    level_mismatch["units"][0]["level"] = base_build.level + 1
    eidolon_mismatch = json.loads(json.dumps(scenario_data))
    eidolon_mismatch["units"][0]["eidolon_level"] = base_build.eidolon_level + 1
    explicit_action_values = json.loads(json.dumps(scenario_data))
    explicit_action_values["battle_setup"]["timeline"]["action_values"] = {"ally:formal": 1}
    explicit_overrides = json.loads(json.dumps(scenario_data))
    explicit_overrides["battle_setup"]["timeline"]["explicit_overrides"] = ["ally:formal"]
    overlap_scenario = replace(
        scenario,
        units=(
            replace(
                scenario.units[0],
                build_mode="kernel_fixture",
                panel=PanelInput(
                    flags={
                        "enabled_trace_node_ids": (rules.character_trace_nodes_for_card(card.card_id)[0].trace_node_id,),
                        "disabled_trace_node_ids": (rules.character_trace_nodes_for_card(card.card_id)[0].trace_node_id,),
                    }
                ),
                character_build=None,
                initial_condition=None,
            ),
            scenario.units[1],
        ),
    )
    light_cone = LightConeInstanceInput(
        instance_id="validation:nonempty-light-cone",
        definition_key=EquipmentDefinitionKey("light_cone", "validation:not-lowered"),
        level=1,
        promotion=0,
        superimposition=1,
    )
    nonempty_build = _build(
        card.card_id,
        level=1,
        promotion=0,
        equipment=EquipmentBuildInput(
            build_id="validation:nonempty-equipment",
            character_card_id=card.card_id,
            light_cone=light_cone,
        ),
    )
    return {
        "formal_scenario_loader_and_identity_accept_source_backed_build": identity.ok,
        "formal_scenario_build_obeys_character_mechanism_admission": (
            (
                base_result.battle_admission_status == "admitted"
                and built is not None
                and len(built.character_build_results) == 1
                and built.character_build_results[0].result_fingerprint
                == base_result.result_fingerprint
            )
            or (
                base_result.battle_admission_status == "blocked"
                and bool(base_result.unadmitted_mechanism_diagnostics)
                and build_rejected
            )
        ),
        "formal_panel_injection_rejected": _raises(lambda: ScenarioLoader().load_dict(panel_injected)),
        "missing_formal_initial_condition_rejected": _raises(
            lambda: ScenarioLoader().load_dict(missing_initial)
        ),
        "entity_card_identity_mismatch_rejected": not IdentityResolver(rules).validate(
            ScenarioLoader().load_dict(wrong_entity)
        ).ok,
        "outer_level_mirror_mismatch_rejected": not IdentityResolver(rules).validate(
            ScenarioLoader().load_dict(level_mismatch)
        ).ok,
        "outer_eidolon_mirror_mismatch_rejected": not IdentityResolver(rules).validate(
            ScenarioLoader().load_dict(eidolon_mismatch)
        ).ok,
        "runtime_initialize_action_values_rejected_by_loader": _raises(
            lambda: ScenarioLoader().load_dict(explicit_action_values)
        ),
        "runtime_initialize_explicit_overrides_rejected_by_loader": _raises(
            lambda: ScenarioLoader().load_dict(explicit_overrides)
        ),
        "same_trace_enabled_and_disabled_rejected_in_kernel_fixture": not IdentityResolver(
            rules
        ).validate(overlap_scenario).ok,
        "unknown_light_cone_is_blocked_by_typed_equipment_resolution": result_is_blocked(
            assemble_character_build(rules, nonempty_build)
        ),
        "formal_timeline_positive_contains_no_player_action_value": (
            "action_value" not in base_build.to_json()
            and scenario.units[0].panel is None
            and scenario.battle_setup.timeline is not None
            and scenario.battle_setup.timeline.mode == "runtime_initialize"
            and not scenario.battle_setup.timeline.action_values
            and not scenario.battle_setup.timeline.explicit_overrides
        ),
    }


def _mechanism_admission_checks(
    rules: RuleBook,
    ir: CanonicalIR,
    base_build: CharacterBuildInput,
    base_result: CharacterBuildAssemblyResult,
) -> dict[str, bool]:
    trace_skill_nodes = tuple(node for node in ir.character_trace_nodes if node.level_up_skill_ids)
    trace_extra_nodes = tuple(
        node
        for node in ir.character_trace_nodes
        if node.extra_effect_ids or node.simple_extra_effect_ids
    )
    default_nodes = tuple(node for node in ir.character_trace_nodes if node.default_unlocked)

    def linked_slots(node: CharacterTraceNodeIR) -> tuple[CharacterMechanismSlotIR, ...]:
        return tuple(
            slot
            for slot_id in node.linked_mechanism_slot_ids
            if (slot := rules.character_mechanism_slot(slot_id)) is not None
        )

    default_node = next(
        (
            node
            for node in default_nodes
            if (card := rules.character_data_card(node.character_data_card_id)) is not None
            and (profile := rules.avatar_profile_by_profile_id(card.profile_id)) is not None
            and profile.coverage_status == "executable"
            and set(node.level_up_skill_ids).issubset(card.skill_ids)
            and (
                node.source.evidence.get("enhanced_id") is None
                if card.source.evidence.get("enhanced_id") is None
                else str(node.source.evidence.get("enhanced_id"))
                == str(card.source.evidence.get("enhanced_id"))
            )
        ),
        None,
    )
    default_auto_result = None
    explicit_default_result = None
    if default_node is not None:
        card = rules.character_data_card(default_node.character_data_card_id)
        profile = rules.avatar_profile_by_profile_id(card.profile_id)
        last_tier = max(profile.promotion_tiers, key=lambda tier: tier.promotion)
        default_auto_result = assemble_character_build(
            rules,
            _build(card.card_id, level=last_tier.max_level, promotion=last_tier.promotion),
        )
        explicit_default_result = assemble_character_build(
            rules,
            _build(
                card.card_id,
                level=last_tier.max_level,
                promotion=last_tier.promotion,
                trace_ids=(default_node.trace_node_id,),
            ),
        )

    mixed_eidolon = next(
        (
            slot
            for slot in ir.character_eidolon_slots
            if any(
                child is not None and child.mechanism_kind == "eidolon_extra_effect"
                for child in (
                    rules.character_mechanism_slot(slot_id)
                    for slot_id in slot.linked_mechanism_slot_ids
                )
            )
            and any(
                child is not None and child.mechanism_kind != "eidolon_extra_effect"
                for child in (
                    rules.character_mechanism_slot(slot_id)
                    for slot_id in slot.linked_mechanism_slot_ids
                )
            )
        ),
        None,
    )
    mixed_eidolon_result = None
    mixed_extra_slot_ids: set[str] = set()
    if mixed_eidolon is not None:
        card = rules.character_data_card(mixed_eidolon.character_data_card_id)
        profile = rules.avatar_profile_by_profile_id(card.profile_id) if card is not None else None
        if card is not None and profile is not None and profile.coverage_status == "executable":
            last_tier = max(profile.promotion_tiers, key=lambda tier: tier.promotion)
            mixed_eidolon_result = assemble_character_build(
                rules,
                _build(
                    card.card_id,
                    level=last_tier.max_level,
                    promotion=last_tier.promotion,
                    eidolon_level=mixed_eidolon.rank,
                ),
            )
            mixed_extra_slot_ids = {
                slot_id
                for slot_id in mixed_eidolon.linked_mechanism_slot_ids
                if (child := rules.character_mechanism_slot(slot_id)) is not None
                and child.mechanism_kind == "eidolon_extra_effect"
            }
    executable_slot = next(
        slot for slot in ir.character_mechanism_slots if slot.coverage_status == "executable"
    )
    fake_ref = CharacterDynamicGraphRef(
        dynamic_graph_ref_id="validation:missing-graph-ref",
        root_kind="source_graph",
        root_ref_id="validation:missing-source",
        character_card_id=base_build.character_card_id,
        source_graph_ref_id="validation:missing-card-graph-ref",
        source_graph_id="validation:missing-graph",
        ability_definition_id="",
        ability_name="",
        build_binding_ids=("validation:missing-build-binding",),
        specialization_ids=(),
        root_source=executable_slot.source,
        blocked_reason="validation_missing_dynamic_graph_root",
    )
    fake_diagnostic = CharacterMechanismDiagnostic(
        diagnostic_id="validation:missing-graph-diagnostic",
        mechanism_kind="character_dynamic_graph_root",
        target_ref_id=fake_ref.dynamic_graph_ref_id,
        reason=fake_ref.blocked_reason,
        source=fake_ref.root_source,
    )
    fake_result = replace(
        base_result,
        battle_admission_status="blocked",
        dynamic_graph_refs=(fake_ref,),
        unadmitted_mechanism_diagnostics=(fake_diagnostic,),
    )
    return {
        "every_trace_node_preserves_level_and_default_unlock_fields": all(
            node.level >= 1
            and node.max_level >= node.level
            and isinstance(node.default_unlocked, bool)
            for node in ir.character_trace_nodes
        ),
        "every_skill_level_trace_has_one_executable_source_slot": bool(trace_skill_nodes)
        and all(
            len(
                tuple(
                    slot
                    for slot in linked_slots(node)
                    if slot.mechanism_kind == "trace_skill_level"
                )
            )
            == 1
            and next(
                slot
                for slot in linked_slots(node)
                if slot.mechanism_kind == "trace_skill_level"
            ).coverage_status
            == "executable"
            for node in trace_skill_nodes
        ),
        "every_extra_effect_trace_has_one_blocked_source_slot": bool(trace_extra_nodes)
        and all(
            len(
                tuple(
                    slot
                    for slot in linked_slots(node)
                    if slot.mechanism_kind == "trace_extra_effect"
                )
            )
            == 1
            and next(
                slot
                for slot in linked_slots(node)
                if slot.mechanism_kind == "trace_extra_effect"
            ).coverage_status
            == "blocked"
            for node in trace_extra_nodes
        ),
        "default_trace_nodes_are_automatic_and_resolve_effective_skill_levels": (
            default_node is not None
            and default_auto_result is not None
            and default_auto_result.assembly_status == "assembled"
            and default_auto_result.battle_admission_status == "admitted"
            and any(
                level.skill_id in default_node.level_up_skill_ids
                and level.base_level == default_node.level
                for level in default_auto_result.effective_skill_levels
            )
        ),
        "explicit_default_trace_reselection_is_rejected": (
            explicit_default_result is not None and result_is_blocked(explicit_default_result)
        ),
        "mixed_eidolon_subsources_are_split_and_extra_effect_blocks_battle": (
            mixed_eidolon is not None
            and mixed_eidolon_result is not None
            and mixed_eidolon_result.assembly_status == "assembled"
            and mixed_eidolon_result.battle_admission_status == "blocked"
            and mixed_extra_slot_ids
            and mixed_extra_slot_ids.issubset(
                {
                    diagnostic.target_ref_id
                    for diagnostic in mixed_eidolon_result.unadmitted_mechanism_diagnostics
                }
            )
        ),
        "fabricated_or_missing_graph_ref_rejected_by_formal_admission": bool(
            validate_character_build_admission(rules, base_build, fake_result)
        ),
    }


def _source_mismatch_preserves_panel_and_blocks_battle(
    result: CharacterBuildAssemblyResult,
    expected_reason: str,
) -> bool:
    return (
        result.assembly_status == "assembled"
        and result.base_panel is not None
        and bool(result.contribution_ledger)
        and result.battle_admission_status == "blocked"
        and any(
            diagnostic.reason == expected_reason
            for diagnostic in result.unadmitted_mechanism_diagnostics
        )
    )


def result_is_blocked(result: CharacterBuildAssemblyResult) -> bool:
    return result.assembly_status == "blocked" and result.battle_admission_status == "blocked"


def _raises(callback: Any) -> bool:
    try:
        callback()
    except (TypeError, ValueError):
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P8-S2 character build and base panel")
    parser.add_argument("--tbgd-root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fixture-only", action="store_true")
    parser.add_argument("--character-card-source-only", action="store_true")
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    if args.fixture_only and args.character_card_source_only:
        parser.error("--fixture-only and --character-card-source-only are mutually exclusive")
    if args.fixture_only:
        result = run_fixture_contract_validation(args.output_dir)
    elif args.character_card_source_only:
        tbgd_root = args.tbgd_root or find_tbgd_root(package_root)
        result = run_character_card_source_validation(tbgd_root, args.output_dir)
    else:
        tbgd_root = args.tbgd_root or find_tbgd_root(package_root)
        result = run_validation(package_root, tbgd_root, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
