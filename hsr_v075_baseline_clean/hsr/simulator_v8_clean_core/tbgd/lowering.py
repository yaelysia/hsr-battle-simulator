from __future__ import annotations

import json
import base64
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .coverage import classify_opcode
from .character_cards import build_character_card_ir
from .monster_cards import build_monster_card_ir
from .paths import relative_source_path
from .. import BASELINE_VERSION
from ..rules.evaluator import NumericEvaluationContext, RuleEvaluator
from ..rules.ir import (
    AbilityPhaseIR,
    AbilityTaskIR,
    ActionAbilityBindingIR,
    ActionDefinitionIR,
    ActionDelayEmissionIR,
    ActionEventIR,
    ActionPhaseStepIR,
    AssistantAbilityResolutionIR,
    AvatarProfileIR,
    BreakBaseDamageIR,
    BreakDamageEmissionIR,
    BreakStatusEmissionIR,
    BreakTemplateIR,
    BouncePolicyIR,
    CanonicalIR,
    CharacterDataCardIR,
    CharacterMechanismSlotIR,
    CombatantActionSetIR,
    CombatantProfileIR,
    ConditionIR,
    DamageEmissionIR,
    DamageModifierIR,
    EffectIR,
    ExtraActionPolicyIR,
    FormulaIR,
    HitProfileIR,
    IRSource,
    JSONValue,
    MonsterDataCardIR,
    PassiveMechanismSlotIR,
    QueueIntentIR,
    QueueLifecyclePolicyIR,
    QueuePriorityIR,
    QueueResolutionIR,
    QueueWindowIR,
    ResourceRuleIR,
    RuleEntity,
    SkillContinuationIR,
    SkillFormulaBindingIR,
    StandaloneAbilityGraphIR,
    StatusCallbackIR,
    StatusEventFamilyIR,
    StatusCallbackTaskIR,
    StatusDamageEmissionIR,
    ServantDefinitionIR,
    SummonMonsterEntryIR,
    SummonMonsterIntentIR,
    SummonUnitDefinitionIR,
    SuperBreakEmissionIR,
    TargetExpressionIR,
    TimelineRuleIR,
    ToughnessEmissionIR,
    TriggerIR,
    UnitBirthTemplateIR,
    WaveDefinitionIR,
    WaveMonsterEntryIR,
)


ENTITY_TABLES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "ExcelOutput/AvatarConfig.json": ("avatar", "AvatarID", ("DamageType", "SPNeed", "SkillList", "AvatarBaseType", "Rarity", "JsonPath")),
    "ExcelOutput/AvatarConfigLD.json": ("avatar", "AvatarID", ("DamageType", "SPNeed", "SkillList", "AvatarBaseType", "Rarity", "JsonPath")),
    "ExcelOutput/AvatarConfigEnhanced.json": ("avatar", "AvatarID", ("EnhancedID", "SPNeed", "SkillList", "RankIDList", "JsonPath", "AIPath")),
    "ExcelOutput/AvatarSkillConfig.json": (
        "avatar_skill",
        "SkillID",
        ("SkillTriggerKey", "SkillEffect", "AttackType", "MaxLevel", "SkillIcon", "UltraSkillIcon"),
    ),
    "ExcelOutput/AvatarSkillConfigLD.json": (
        "avatar_skill",
        "SkillID",
        ("SkillTriggerKey", "SkillEffect", "AttackType", "MaxLevel", "SkillIcon", "UltraSkillIcon"),
    ),
    "ExcelOutput/AvatarPromotionConfig.json": (
        "avatar_promotion",
        "AvatarID",
        ("Promotion", "MaxLevel", "AttackBase", "AttackAdd", "DefenceBase", "DefenceAdd", "HPBase", "HPAdd", "SpeedBase", "CriticalChance", "CriticalDamage", "BaseAggro"),
    ),
    "ExcelOutput/AvatarPromotionConfigLD.json": (
        "avatar_promotion",
        "AvatarID",
        ("Promotion", "MaxLevel", "AttackBase", "AttackAdd", "DefenceBase", "DefenceAdd", "HPBase", "HPAdd", "SpeedBase", "CriticalChance", "CriticalDamage", "BaseAggro"),
    ),
    "ExcelOutput/CommonAvatarSkillConfig.json": (
        "avatar_skill",
        "SkillID",
        ("SkillTriggerKey", "SkillEffect", "AttackType", "MaxLevel"),
    ),
    "ExcelOutput/CommonActiveSkillConfig.json": (
        "active_skill",
        "SkillID",
        ("SkillTriggerKey", "SkillEffect", "AttackType", "MaxLevel"),
    ),
    "ExcelOutput/StatusConfig.json": (
        "status",
        "StatusID",
        ("ModifierName", "StatusType", "CanDispel", "ReadParamList", "TagList"),
    ),
    "ExcelOutput/AvatarStatusConfig.json": (
        "status",
        "StatusID",
        ("ModifierName", "StatusType", "CanDispel", "ReadParamList", "TagList"),
    ),
    "ExcelOutput/AvatarStatusConfigLD.json": (
        "status",
        "StatusID",
        ("ModifierName", "StatusType", "CanDispel", "ReadParamList", "TagList"),
    ),
    "ExcelOutput/MonsterStatusConfig.json": (
        "status",
        "StatusID",
        ("ModifierName", "StatusType", "CanDispel", "ReadParamList", "TagList"),
    ),
    "ExcelOutput/ILBattleStatusConfig.json": (
        "status",
        "ID",
        ("ModifierName", "StatusType", "CanDispel", "ReadParamList", "TagList", "DisplayPriority"),
    ),
    "ExcelOutput/ILBattleMonsterSkill.json": (
        "ilbattle_monster_skill",
        "ID",
        ("SkillTriggerKey", "AttackType", "InitialCD", "CoolDown", "ParamList"),
    ),
    "ExcelOutput/MonsterSkillConfig.json": (
        "monster_skill",
        "SkillID",
        ("SkillTriggerKey", "DamageType", "AttackType", "SPHitBase", "ParamList", "PhaseList"),
    ),
    "ExcelOutput/MonsterSkillUniqueConfig.json": (
        "monster_skill",
        "SkillID",
        ("SkillTriggerKey", "DamageType", "AttackType", "SPHitBase", "ParamList", "PhaseList"),
    ),
    "ExcelOutput/MonsterConfig.json": (
        "monster",
        "MonsterID",
        ("MonsterTemplateID", "HardLevelGroup", "AttackModifyRatio", "DefenceModifyRatio", "HPModifyRatio", "SpeedModifyRatio", "StanceModifyRatio", "StanceWeakList", "DamageTypeResistance", "SkillList"),
    ),
    "ExcelOutput/MonsterTemplateConfig.json": (
        "monster_template",
        "MonsterTemplateID",
        ("Rank", "AttackBase", "DefenceBase", "HPBase", "SpeedBase", "StanceBase", "CriticalDamageBase", "StatusResistanceBase", "StanceType", "AIPath", "AISkillSequence"),
    ),
    "ExcelOutput/SummonUnitData.json": (
        "summon_unit",
        "ID",
        ("JsonPath", "MaxSummonCount", "UniqueGroup", "DestroyOnEnterBattle"),
    ),
    "ExcelOutput/AvatarServantConfig.json": (
        "servant",
        "ServantID",
        (
            "Config",
            "AIPath",
            "SkillIDList",
            "HPBase",
            "HPInherit",
            "HPSkill",
            "SpeedBase",
            "SpeedInherit",
            "SpeedSkill",
            "Aggro",
        ),
    ),
    "ExcelOutput/AvatarServantSkillConfig.json": (
        "servant_skill",
        "SkillID",
        ("SkillTriggerKey", "SkillEffect", "AttackType", "MaxLevel", "ParamList"),
    ),
    "ExcelOutput/RelicSetSkillConfig.json": (
        "relic_set_skill",
        "SetID",
        ("SkillList", "SetSkillList", "AbilityName", "ParamList"),
    ),
    "ExcelOutput/AvatarBreakDamage.json": (
        "break_damage",
        "Level",
        ("BreakBaseDamage", "HardnessBaseDamage"),
    ),
}


ACTION_DEFINITION_TABLES: tuple[tuple[str, str, str], ...] = (
    ("ExcelOutput/AvatarSkillConfig.json", "avatar_skill", "SkillID"),
    ("ExcelOutput/AvatarSkillConfigLD.json", "avatar_skill", "SkillID"),
    ("ExcelOutput/CommonAvatarSkillConfig.json", "avatar_skill", "SkillID"),
    ("ExcelOutput/CommonActiveSkillConfig.json", "active_skill", "SkillID"),
    ("ExcelOutput/MonsterSkillConfig.json", "monster_skill", "SkillID"),
    ("ExcelOutput/MonsterSkillUniqueConfig.json", "monster_skill", "SkillID"),
    ("ExcelOutput/ILBattleMonsterSkill.json", "ilbattle_monster_skill", "ID"),
    ("ExcelOutput/AvatarServantSkillConfig.json", "servant_skill", "SkillID"),
)

CHARACTER_ACTION_DEFINITION_TABLES: tuple[tuple[str, str, str], ...] = (
    ("ExcelOutput/AvatarSkillConfig.json", "avatar_skill", "SkillID"),
    ("ExcelOutput/AvatarSkillConfigLD.json", "avatar_skill", "SkillID"),
    ("ExcelOutput/CommonAvatarSkillConfig.json", "avatar_skill", "SkillID"),
    ("ExcelOutput/CommonActiveSkillConfig.json", "active_skill", "SkillID"),
)


ELATION_MECHANIC_FILES: tuple[str, ...] = (
    "Config/GlobalConfig/GameCoreConstValue.json",
    "Config/GlobalConfig/PriorityConfig.json",
)


DAMAGE_BEHAVIOR_TEMPLATE_FILE = "Config/GlobalConfig/DamageBehaviorTemplateListConfig.json"

ABILITY_TASK_CALLBACKS = ("OnStart", "OnAttack", "OnHit", "OnEnd")


@dataclass(frozen=True)
class LoweringLimits:
    max_records_per_table: int | None = None
    max_ability_files: int | None = None
    max_callbacks_per_file: int | None = None


class TBGDLowering:
    """Converts TBGD raw files into v8 Canonical IR."""

    def __init__(self, tbgd_root: Path, limits: LoweringLimits | None = None):
        self.tbgd_root = tbgd_root.resolve()
        self.limits = limits or LoweringLimits()

    def build(self) -> CanonicalIR:
        entities: list[RuleEntity] = []
        action_definitions: list[ActionDefinitionIR] = []
        triggers: list[TriggerIR] = []
        effects: list[EffectIR] = []
        conditions: list[ConditionIR] = []
        formulas: list[FormulaIR] = []
        status_callbacks: list[StatusCallbackIR] = []
        status_callback_tasks: list[StatusCallbackTaskIR] = []
        status_damage_emissions: list[StatusDamageEmissionIR] = []
        damage_modifiers: list[DamageModifierIR] = []
        action_delay_emissions: list[ActionDelayEmissionIR] = []
        queue_intents: list[QueueIntentIR] = []
        skill_continuations: list[SkillContinuationIR] = []
        super_break_emissions: list[SuperBreakEmissionIR] = []
        target_expressions: list[TargetExpressionIR] = []
        target_expressions.extend(self._lower_global_target_expressions())
        timeline_rules = self._lower_timeline_rules()
        resource_rules = self._lower_resource_rules()
        queue_priorities = self._lower_queue_priorities()
        queue_priority_lookup = {
            (priority.priority_table, priority.priority_key): priority
            for priority in queue_priorities
            if priority.coverage_status == "executable"
        }

        table_stats: dict[str, dict[str, Any]] = {}
        for relative_path, spec in ENTITY_TABLES.items():
            entities.extend(self._lower_entity_table(relative_path, spec))
            table_stats[relative_path] = self._table_stats(relative_path, spec[1])
        entities = list(_dedupe_entities(entities).values())
        character_cards = build_character_card_ir(
            self.tbgd_root,
            max_records_per_table=self.limits.max_records_per_table,
            skill_tables=CHARACTER_ACTION_DEFINITION_TABLES,
        )
        avatar_profiles = character_cards.avatar_profiles
        character_data_cards = character_cards.character_data_cards
        character_mechanism_slots = list(character_cards.character_mechanism_slots)
        character_trace_nodes = character_cards.character_trace_nodes
        character_eidolon_slots = character_cards.character_eidolon_slots
        skill_formula_bindings = character_cards.skill_formula_bindings
        bounce_policies = character_cards.bounce_policies
        monster_cards = build_monster_card_ir(
            self.tbgd_root,
            max_records_per_table=self.limits.max_records_per_table,
        )
        monster_data_cards = monster_cards.monster_data_cards
        summon_unit_definitions = self._lower_summon_unit_definitions()
        passive_mechanism_slots = list(monster_cards.passive_mechanism_slots)
        skill_formula_bindings = [*skill_formula_bindings, *monster_cards.skill_formula_bindings]
        combatant_profiles = self._lower_combatant_profiles()
        wave_definitions = self._lower_wave_definitions(entities, combatant_profiles, monster_data_cards)
        action_definitions = list(self._lower_action_definitions().values())
        (
            action_ability_bindings,
            ability_phases,
            ability_tasks,
            ability_task_effects,
            ability_task_conditions,
            ability_task_formulas,
            ability_task_target_expressions,
        ) = self._lower_action_ability_bindings(action_definitions)
        target_expressions.extend(ability_task_target_expressions)
        ability_task_effects = _attach_status_formula_bindings_to_add_modifier_effects(
            ability_task_effects,
            ability_tasks,
            skill_formula_bindings,
        )
        effects.extend(ability_task_effects)
        conditions.extend(ability_task_conditions)
        formulas.extend(ability_task_formulas)
        action_events, hit_profiles = _lower_action_execution_ir(
            action_definitions,
            action_ability_bindings,
            ability_phases,
            skill_formula_bindings,
            bounce_policies,
        )
        damage_emissions = _lower_damage_emissions(
            ability_tasks,
            ability_task_effects,
            hit_profiles,
            skill_formula_bindings,
        )
        toughness_emissions = _lower_toughness_emissions(
            ability_tasks,
            ability_task_effects,
            hit_profiles,
        )
        break_base_damage = self._lower_break_base_damage()
        break_templates, break_damage_emissions, break_status_emissions, break_effects = self._lower_break_templates()
        super_break_emissions.extend(self._lower_super_break_emissions())
        effects.extend(break_effects)
        for relative_path, _, id_key in ACTION_DEFINITION_TABLES:
            table_stats[f"action_definitions:{relative_path}"] = self._table_stats(relative_path, id_key)

        ability_files = self._ability_files()
        selected_ability_files = _limit_sequence(ability_files, self.limits.max_ability_files)
        for path in selected_ability_files:
            lowered = self._lower_ability_file(path, queue_priority_lookup)
            entities.extend(lowered.entities)
            triggers.extend(lowered.triggers)
            effects.extend(lowered.effects)
            conditions.extend(lowered.conditions)
            formulas.extend(lowered.formulas)
            target_expressions.extend(lowered.target_expressions)
            status_callbacks.extend(lowered.status_callbacks)
            status_callback_tasks.extend(lowered.status_callback_tasks)
            status_damage_emissions.extend(lowered.status_damage_emissions)
            damage_modifiers.extend(lowered.damage_modifiers)
            action_delay_emissions.extend(lowered.action_delay_emissions)
            queue_intents.extend(lowered.queue_intents)
            skill_continuations.extend(lowered.skill_continuations)
        (
            standalone_ability_graphs,
            standalone_phases,
            standalone_tasks,
            standalone_effects,
            standalone_conditions,
            standalone_formulas,
            standalone_target_expressions,
        ) = self._lower_standalone_ability_graphs(selected_ability_files)
        ability_phases.extend(standalone_phases)
        ability_tasks.extend(standalone_tasks)
        effects.extend(standalone_effects)
        conditions.extend(standalone_conditions)
        formulas.extend(standalone_formulas)
        target_expressions.extend(standalone_target_expressions)
        standalone_hit_profiles = _lower_standalone_hit_profiles(
            standalone_tasks,
            standalone_effects,
            skill_formula_bindings,
        )
        hit_profiles.extend(standalone_hit_profiles)
        damage_emissions.extend(
            _lower_damage_emissions(
                standalone_tasks,
                standalone_effects,
                standalone_hit_profiles,
                skill_formula_bindings,
            )
        )
        toughness_emissions.extend(
            _lower_toughness_emissions(
                standalone_tasks,
                standalone_effects,
                standalone_hit_profiles,
            )
        )
        character_mechanism_slots = _admit_trace_startup_ability_slots(
            character_mechanism_slots,
            standalone_graphs=standalone_ability_graphs,
            ability_tasks=ability_tasks,
            effects=effects,
        )
        passive_mechanism_slots = _admit_passive_startup_slots(
            passive_mechanism_slots,
            standalone_graphs=standalone_ability_graphs,
            ability_tasks=ability_tasks,
            effects=effects,
            triggers=triggers,
        )
        skill_continuations = _skill_continuations_from_ability_tasks(ability_tasks)
        combatant_action_sets = self._lower_combatant_action_sets(action_definitions)
        summon_monster_intents = _lower_summon_monster_intents(
            ability_tasks=ability_tasks,
            effects=effects,
            combatant_profiles=combatant_profiles,
            monster_data_cards=monster_data_cards,
        )
        status_event_families = _lower_status_event_families(status_callbacks, status_callback_tasks)
        status_event_blocked_reasons = _status_event_blocked_reasons(status_event_families)
        status_callbacks = _block_status_callbacks_by_event_family(status_callbacks, status_event_blocked_reasons)
        status_callback_blocked_reasons = {
            callback.callback_id: status_event_blocked_reasons[callback.event]
            for callback in status_callbacks
            if callback.event in status_event_blocked_reasons
        }
        status_callback_tasks = _block_status_callback_tasks_by_callback(
            status_callback_tasks,
            status_callback_blocked_reasons,
        )
        status_damage_emissions = _block_status_callback_derived_by_callback(
            status_damage_emissions,
            status_callback_blocked_reasons,
        )
        damage_modifiers = _block_status_callback_derived_by_callback(
            damage_modifiers,
            status_callback_blocked_reasons,
        )
        action_delay_emissions = _block_status_callback_derived_by_callback(
            action_delay_emissions,
            status_callback_blocked_reasons,
        )
        queue_intents = _block_status_callback_derived_by_callback(
            queue_intents,
            status_callback_blocked_reasons,
        )
        status_event_families = _lower_status_event_families(status_callbacks, status_callback_tasks)
        queue_resolutions = _lower_queue_resolutions(
            queue_intents=queue_intents,
            action_bindings=action_ability_bindings,
            ability_phases=ability_phases,
            standalone_graphs=standalone_ability_graphs,
            combatant_action_sets=combatant_action_sets,
        )
        assistant_ability_resolutions = _lower_assistant_ability_resolutions(queue_intents, queue_resolutions)
        servant_definitions = self._lower_servant_definitions(combatant_action_sets, action_ability_bindings)
        unit_birth_templates = _lower_unit_birth_templates(
            summon_monster_intents=summon_monster_intents,
            servant_definitions=servant_definitions,
            wave_definitions=wave_definitions,
            combatant_profiles=combatant_profiles,
            monster_data_cards=monster_data_cards,
            timeline_rules=timeline_rules,
        )
        extra_turn_source_basis = self._extra_turn_source_basis()
        queue_windows = _lower_queue_windows(queue_intents, queue_resolutions, extra_turn_source_basis)
        queue_lifecycle_policies = _lower_queue_lifecycle_policies(queue_windows, extra_turn_source_basis)
        extra_action_policies = _lower_extra_action_policies(
            queue_intents=queue_intents,
            queue_windows=queue_windows,
            queue_lifecycle_policies=queue_lifecycle_policies,
            skill_continuations=skill_continuations,
            extra_turn_source_basis=extra_turn_source_basis,
        )
        runtime_character_slots = _character_runtime_mechanism_slots(
            character_data_cards=character_data_cards,
            skill_formula_bindings=skill_formula_bindings,
            action_ability_bindings=action_ability_bindings,
            status_callbacks=status_callbacks,
            damage_modifiers=damage_modifiers,
            queue_intents=queue_intents,
            queue_windows=queue_windows,
            extra_action_policies=extra_action_policies,
            skill_continuations=skill_continuations,
        )
        character_mechanism_slots.extend(runtime_character_slots)
        character_data_cards = _attach_character_runtime_mechanism_slots(character_data_cards, runtime_character_slots)
        entities = list(_dedupe_entities(entities).values())
        formulas.extend(self._lower_elation_mechanics())
        formulas.extend(self._lower_damage_behavior_templates())

        return CanonicalIR(
            version=BASELINE_VERSION,
            entities=tuple(entities),
            avatar_profiles=tuple(avatar_profiles),
            character_data_cards=tuple(character_data_cards),
            monster_data_cards=tuple(monster_data_cards),
            summon_unit_definitions=tuple(summon_unit_definitions),
            unit_birth_templates=tuple(unit_birth_templates),
            summon_monster_intents=tuple(summon_monster_intents),
            assistant_ability_resolutions=tuple(assistant_ability_resolutions),
            servant_definitions=tuple(servant_definitions),
            character_mechanism_slots=tuple(character_mechanism_slots),
            passive_mechanism_slots=tuple(passive_mechanism_slots),
            character_trace_nodes=tuple(character_trace_nodes),
            character_eidolon_slots=tuple(character_eidolon_slots),
            bounce_policies=tuple(bounce_policies),
            combatant_profiles=tuple(combatant_profiles),
            action_definitions=tuple(action_definitions),
            action_ability_bindings=tuple(action_ability_bindings),
            ability_phases=tuple(ability_phases),
            ability_tasks=tuple(ability_tasks),
            action_events=tuple(action_events),
            hit_profiles=tuple(hit_profiles),
            skill_formula_bindings=tuple(skill_formula_bindings),
            damage_emissions=tuple(damage_emissions),
            toughness_emissions=tuple(toughness_emissions),
            break_templates=tuple(break_templates),
            break_base_damage=tuple(break_base_damage),
            break_damage_emissions=tuple(break_damage_emissions),
            break_status_emissions=tuple(break_status_emissions),
            status_event_families=tuple(status_event_families),
            status_callbacks=tuple(status_callbacks),
            status_callback_tasks=tuple(status_callback_tasks),
            status_damage_emissions=tuple(status_damage_emissions),
            damage_modifiers=tuple(damage_modifiers),
            action_delay_emissions=tuple(action_delay_emissions),
            queue_intents=tuple(queue_intents),
            queue_resolutions=tuple(queue_resolutions),
            queue_priorities=tuple(queue_priorities),
            queue_windows=tuple(queue_windows),
            queue_lifecycle_policies=tuple(queue_lifecycle_policies),
            extra_action_policies=tuple(extra_action_policies),
            skill_continuations=tuple(skill_continuations),
            standalone_ability_graphs=tuple(standalone_ability_graphs),
            combatant_action_sets=tuple(combatant_action_sets),
            timeline_rules=tuple(timeline_rules),
            resource_rules=tuple(resource_rules),
            super_break_emissions=tuple(super_break_emissions),
            target_expressions=tuple(_dedupe_target_expressions(target_expressions).values()),
            wave_definitions=tuple(wave_definitions),
            triggers=tuple(triggers),
            effects=tuple(effects),
            conditions=tuple(conditions),
            formulas=tuple(formulas),
            metadata={
                "source": "turnbasedgamedata-main",
                "lowering": "tbgd_first_v0_200",
                "limits": {
                    "max_records_per_table": self.limits.max_records_per_table,
                    "max_ability_files": self.limits.max_ability_files,
                    "max_callbacks_per_file": self.limits.max_callbacks_per_file,
                },
                "sampled": {
                    "entity_tables": self.limits.max_records_per_table is not None,
                    "ability_files": self.limits.max_ability_files is not None
                    and len(selected_ability_files) < len(ability_files),
                    "callbacks": self.limits.max_callbacks_per_file is not None,
                },
                "table_status": table_stats,
                "ability_file_status": {
                    "raw_count": len(ability_files),
                    "lowered_count": len(selected_ability_files),
                    "skipped_count": max(0, len(ability_files) - len(selected_ability_files)),
                },
                "action_binding_status": {
                    "lowered_count": len(action_ability_bindings),
                    "ability_phase_count": len(ability_phases),
                    "ability_task_count": len(ability_tasks),
                    "damage_emission_count": len(damage_emissions),
                    "toughness_emission_count": len(toughness_emissions),
                    "break_template_count": len(break_templates),
                    "break_base_damage_count": len(break_base_damage),
                    "break_damage_emission_count": len(break_damage_emissions),
                    "break_status_emission_count": len(break_status_emissions),
                    "status_event_family_count": len(status_event_families),
                    "executable_status_event_family_count": sum(
                        1 for family in status_event_families if family.coverage_status == "executable"
                    ),
                    "status_callback_count": len(status_callbacks),
                    "status_callback_task_count": len(status_callback_tasks),
                    "status_damage_emission_count": len(status_damage_emissions),
                    "action_delay_emission_count": len(action_delay_emissions),
                    "queue_intent_count": len(queue_intents),
                    "queue_resolution_count": len(queue_resolutions),
                    "queue_priority_count": len(queue_priorities),
                    "queue_window_count": len(queue_windows),
                    "standalone_ability_graph_count": len(standalone_ability_graphs),
                    "combatant_action_set_count": len(combatant_action_sets),
                    "timeline_rule_count": len(timeline_rules),
                    "resource_rule_count": len(resource_rules),
                    "super_break_emission_count": len(super_break_emissions),
                    "target_expression_count": len(target_expressions),
                    "executable_target_expression_count": sum(
                        1 for expression in target_expressions if expression.coverage_status == "executable"
                    ),
                    "wave_definition_count": len(wave_definitions),
                    "executable_wave_definition_count": sum(
                        1 for definition in wave_definitions if definition.coverage_status == "executable"
                    ),
                    "skill_formula_binding_count": len(skill_formula_bindings),
                    "bounce_policy_count": len(bounce_policies),
                    "character_mechanism_slot_count": len(character_mechanism_slots),
                    "passive_mechanism_slot_count": len(passive_mechanism_slots),
                    "executable_passive_mechanism_slot_count": sum(
                        1 for slot in passive_mechanism_slots if slot.coverage_status == "executable"
                    ),
                    "character_trace_node_count": len(character_trace_nodes),
                    "character_eidolon_slot_count": len(character_eidolon_slots),
                },
                "avatar_profile_status": {
                    "lowered_count": len(avatar_profiles),
                    "executable_count": sum(1 for profile in avatar_profiles if profile.coverage_status == "executable"),
                    "blocked_count": sum(1 for profile in avatar_profiles if profile.coverage_status == "blocked"),
                },
                "character_data_card_status": {
                    "lowered_count": len(character_data_cards),
                    "executable_count": sum(1 for card in character_data_cards if card.coverage_status == "executable"),
                    "blocked_count": sum(1 for card in character_data_cards if card.coverage_status == "blocked"),
                },
                "monster_data_card_status": {
                    "lowered_count": len(monster_data_cards),
                    "sequence_admitted_count": sum(
                        1
                        for card in monster_data_cards
                        if card.ai_policy.get("admission_status") == "executable"
                    ),
                    "blocked_count": sum(1 for card in monster_data_cards if card.coverage_status == "blocked"),
                },
                "combatant_profile_status": {
                    "lowered_count": len(combatant_profiles),
                    "executable_count": sum(1 for profile in combatant_profiles if profile.coverage_status == "executable"),
                    "blocked_count": sum(1 for profile in combatant_profiles if profile.coverage_status == "blocked"),
                },
            },
        )

    def _lower_timeline_rules(self) -> list[TimelineRuleIR]:
        return [
            TimelineRuleIR(
                timeline_rule_id="timeline_rule:engine_convention:base_action_gauge_10000",
                base_action_gauge=10000.0,
                initial_action_value_rule="base_action_gauge / effective_speed",
                turn_reset_rule="base_action_gauge / effective_speed after regular turn end",
                source_kind="engine_convention",
                source=IRSource(
                    source_path="simulator_v8_clean_core/timeline_engine_convention",
                    raw_type="TimelineEngineConvention",
                    raw_id="base_action_gauge_10000",
                    evidence={
                        "reason": "TBGD raw constant source not admitted yet; recorded as explicit engine convention instead of TBGD source",
                        "formula": "10000 / speed",
                    },
                ),
                coverage_status="executable",
            )
        ]

    def _lower_resource_rules(self) -> list[ResourceRuleIR]:
        return [
            ResourceRuleIR(
                resource_rule_id="resource_rule:engine_convention:ultimate_energy_cost_then_action_spbase",
                rule_kind="ultimate_energy_cost",
                operation="set_actor_energy_to_action_spbase_after_admitted_ultimate_execution",
                source_kind="engine_convention",
                source=IRSource(
                    source_path="simulator_v8_clean_core/resource_engine_convention",
                    raw_type="ResourceEngineConvention",
                    raw_id="ultimate_energy_cost_then_action_spbase",
                    evidence={
                        "reason": "Ultimate preflight consumes full energy, then admitted action SPBase is preserved as post-use energy gain.",
                        "operation": "after an admitted ultimate action executes, set actor energy to ActionDefinitionIR.sp_base",
                    },
                ),
                coverage_status="executable",
            ),
            ResourceRuleIR(
                resource_rule_id="resource_rule:engine_convention:kill_energy_gain_10",
                rule_kind="kill_energy_gain",
                operation="add_10_energy_to_kill_credit_owner_on_unit_defeated",
                source_kind="engine_convention",
                source=IRSource(
                    source_path="simulator_v8_clean_core/resource_engine_convention",
                    raw_type="ResourceEngineConvention",
                    raw_id="kill_energy_gain_10",
                    evidence={
                        "reason": "Common caused-kill energy gain is recorded as an explicit engine convention until a raw TBGD constant source is admitted.",
                        "operation": "when a unit.defeated event credits a living actor, add 10 energy capped by max energy",
                        "energy_gain": 10,
                    },
                ),
                coverage_status="executable",
            )
        ]

    def _lower_global_target_expressions(self) -> list[TargetExpressionIR]:
        alias_relative = "Config/GlobalConfig/TargetAliasConfig.json"
        operation_relative = "Config/GlobalConfig/TargetOperationConfig.json"
        alias_path = self.tbgd_root / alias_relative
        operation_path = self.tbgd_root / operation_relative
        alias_config = _json_object_from_path(alias_path)
        operation_config = _json_object_from_path(operation_path)
        alias_dict = alias_config.get("AliasDict") if isinstance(alias_config.get("AliasDict"), dict) else {}
        operation_dict = (
            operation_config.get("OperationDict") if isinstance(operation_config.get("OperationDict"), dict) else {}
        )
        expressions: list[TargetExpressionIR] = []
        for alias, raw in sorted(alias_dict.items()):
            if not isinstance(alias, str) or not isinstance(raw, dict):
                continue
            source = IRSource(
                source_path=alias_relative,
                raw_type="TargetAliasConfig.AliasDict",
                raw_id=alias,
                evidence={
                    "source_path": alias_relative,
                    "target_config_path": alias_relative,
                    "alias": alias,
                },
            )
            expression = _target_expression_from_raw(
                raw,
                field_name=f"AliasDict.{alias}",
                expression_id=f"target_expression:global_alias:{_safe_id(alias)}",
                source=source,
            )
            if expression is not None:
                expressions.append(expression)
        safe_bases = sorted(alias for alias in P1_6_SAFE_DOT_TARGET_BASE_ALIASES if alias in alias_dict)
        safe_operations = sorted(operation for operation in P1_6_SAFE_DOT_TARGET_OPERATIONS if operation in operation_dict)
        for base_alias in safe_bases:
            for operation in safe_operations:
                raw = {"$type": "RPG.GameCore.TargetAlias", "Alias": f"{base_alias}.{operation}"}
                coverage_status, blocked_reason, admission_batch = _target_expression_admission(
                    "TargetAlias",
                    raw["Alias"],
                    raw,
                )
                expressions.append(
                    TargetExpressionIR(
                        target_expression_id=(
                            "target_expression:global_alias_chain:"
                            f"{_safe_id(base_alias)}:{_safe_id(operation)}"
                        ),
                        expression_kind="TargetAlias",
                        alias=raw["Alias"],
                        payload={
                            "field_name": "TargetAliasConfig.AliasDict + TargetOperationConfig.OperationDict",
                            "node_type": "RPG.GameCore.TargetAlias",
                            "alias": raw["Alias"],
                            "normalized": _target_expression_normalized_payload(raw),
                            "raw": _json_safe(raw),
                        },
                        source=IRSource(
                            source_path=f"{alias_relative}+{operation_relative}",
                            raw_type="TargetAliasOperationChain",
                            raw_id=raw["Alias"],
                            evidence={
                                "source_path": alias_relative,
                                "target_config_path": alias_relative,
                                "operation_config_path": operation_relative,
                                "base_alias": base_alias,
                                "operation": operation,
                                "base_alias_raw_type": _short_gamecore_type(
                                    alias_dict.get(base_alias, {}).get("$type")
                                    if isinstance(alias_dict.get(base_alias), dict)
                                    else ""
                                ),
                                "operation_raw_type": _short_gamecore_type(
                                    operation_dict.get(operation, {}).get("$type")
                                    if isinstance(operation_dict.get(operation), dict)
                                    else ""
                                ),
                            },
                        ),
                        coverage_status=coverage_status,
                        blocked_reason=blocked_reason,
                        admission_batch=admission_batch,
                    )
                )
        return expressions

    def _lower_combatant_profiles(self) -> list[CombatantProfileIR]:
        monster_rows = self._rows_by_id("ExcelOutput/MonsterConfig.json", "MonsterID")
        template_rows = self._rows_by_id("ExcelOutput/MonsterTemplateConfig.json", "MonsterTemplateID")
        unique_monster_rows = self._rows_by_id("ExcelOutput/MonsterUniqueConfig.json", "MonsterID")
        unique_template_rows = self._rows_by_id("ExcelOutput/MonsterTemplateUniqueConfig.json", "MonsterTemplateID")
        profiles: list[CombatantProfileIR] = []
        for monster_id, monster_row in sorted(monster_rows.items()):
            template_id = str(monster_row.get("MonsterTemplateID") or "")
            template_row = template_rows.get(template_id)
            profiles.append(_combatant_profile_from_monster(monster_id, monster_row, template_id, template_row))
        for monster_id, monster_row in sorted(unique_monster_rows.items()):
            template_id = str(monster_row.get("MonsterTemplateID") or "")
            template_row = unique_template_rows.get(template_id)
            profiles.append(
                _combatant_profile_from_monster(
                    monster_id,
                    monster_row,
                    template_id,
                    template_row,
                    source_path="ExcelOutput/MonsterUniqueConfig.json",
                    raw_type="MonsterUniqueConfig",
                    template_source_path="ExcelOutput/MonsterTemplateUniqueConfig.json",
                )
            )
        for template_id, template_row in sorted(template_rows.items()):
            profiles.append(_combatant_profile_from_template(template_id, template_row))
        for template_id, template_row in sorted(unique_template_rows.items()):
            profiles.append(
                _combatant_profile_from_template(
                    template_id,
                    template_row,
                    source_path="ExcelOutput/MonsterTemplateUniqueConfig.json",
                    raw_type="MonsterTemplateUniqueConfig",
                )
            )
        return profiles

    def _lower_wave_definitions(
        self,
        entities: list[RuleEntity],
        combatant_profiles: list[CombatantProfileIR],
        monster_data_cards: tuple[MonsterDataCardIR, ...],
    ) -> list[WaveDefinitionIR]:
        relative = "ExcelOutput/StageConfig.json"
        path = self.tbgd_root / relative
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if not isinstance(raw, list):
            return []
        rows = _limit_sequence(raw, self.limits.max_records_per_table)
        entity_by_id = {entity.entity_id: entity for entity in entities}
        profile_by_entity = {profile.entity_id: profile for profile in combatant_profiles}
        card_by_entity = {card.entity_ref: card for card in monster_data_cards}
        hard_level_profiles = self._hard_level_profiles()
        definitions: list[WaveDefinitionIR] = []
        for row_index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            stage_id = _stage_id(row)
            if not stage_id:
                continue
            monster_list = row.get("MonsterList")
            if not isinstance(monster_list, list) or not monster_list:
                continue
            declared_wave_count = _stage_config_wave_count(row.get("StageConfigData"))
            wave_count = declared_wave_count if declared_wave_count > 0 else len(monster_list)
            level = _positive_int(row.get("Level"))
            hard_level_group = _positive_int(row.get("HardLevelGroup"))
            level_policy = _wave_level_policy(
                stage_id=stage_id,
                stage_row_index=row_index,
                level=level,
                hard_level_group=hard_level_group,
                hard_level_profile=hard_level_profiles.get((hard_level_group, level))
                if hard_level_group is not None and level is not None
                else None,
            )
            entries: list[WaveMonsterEntryIR] = []
            for wave_index, wave in enumerate(monster_list):
                if not isinstance(wave, dict):
                    continue
                for monster_key, raw_monster_id in _stage_monster_items(wave):
                    position = _stage_monster_position(monster_key)
                    monster_raw_id = _stage_monster_raw_id(raw_monster_id)
                    monster_entity_ref = f"monster:{monster_raw_id}" if monster_raw_id else ""
                    coverage_status = "executable"
                    blocked_reason = ""
                    if level_policy.get("admission_status") != "executable":
                        coverage_status = "blocked"
                        blocked_reason = str(level_policy.get("blocked_reason") or "wave_stage_level_source_blocked")
                    elif not monster_raw_id or monster_raw_id == "0":
                        coverage_status = "blocked"
                        blocked_reason = "wave_monster_entry_empty"
                    elif (
                        monster_entity_ref not in entity_by_id
                        or entity_by_id[monster_entity_ref].entity_type not in {"monster", "monster_template"}
                    ):
                        coverage_status = "blocked"
                        blocked_reason = "wave_monster_entity_missing"
                    else:
                        profile = profile_by_entity.get(monster_entity_ref)
                        card = card_by_entity.get(monster_entity_ref)
                        if profile is None or profile.coverage_status != "executable":
                            coverage_status = "blocked"
                            blocked_reason = "combatant_profile_missing_or_blocked"
                        elif card is None:
                            coverage_status = "blocked"
                            blocked_reason = "monster_data_card_missing"
                    entries.append(
                        WaveMonsterEntryIR(
                            entry_id=f"wave_entry:stage:{_safe_id(stage_id)}:w{wave_index}:p{position}:{_safe_id(monster_raw_id or 'empty')}",
                            stage_id=stage_id,
                            wave_index=wave_index,
                            position=position,
                            monster_entity_ref=monster_entity_ref,
                            monster_raw_id=monster_raw_id,
                            source=IRSource(
                                source_path=relative_source_path(self.tbgd_root, path),
                                raw_type="StageConfig.MonsterList",
                                raw_id=f"{stage_id}:{wave_index}:{monster_key}",
                                evidence={
                                    "StageID": stage_id,
                                    "stage_row_index": row_index,
                                    "StageConfigData": row.get("StageConfigData") if isinstance(row.get("StageConfigData"), list) else [],
                                    "declared_wave_count": declared_wave_count,
                                    "MonsterList_wave_index": wave_index,
                                    "MonsterList_key": monster_key,
                                    "monster_id": monster_raw_id,
                                    "level_policy": level_policy,
                                },
                            ),
                            birth_template_id=_wave_birth_template_id(stage_id, wave_index, position, monster_raw_id),
                            coverage_status=coverage_status,  # type: ignore[arg-type]
                            blocked_reason=blocked_reason,
                        )
                    )
            blocked_entries = [entry for entry in entries if entry.coverage_status != "executable"]
            definition_blocked_reason = ""
            definition_status = "executable"
            if level_policy.get("admission_status") != "executable":
                definition_status = "blocked"
                definition_blocked_reason = str(level_policy.get("blocked_reason") or "wave_stage_level_source_blocked")
            elif declared_wave_count <= 0:
                definition_status = "blocked"
                definition_blocked_reason = "stage_wave_count_missing"
            elif wave_count != len(monster_list):
                definition_status = "blocked"
                definition_blocked_reason = "stage_wave_count_monster_list_mismatch"
            elif not entries:
                definition_status = "blocked"
                definition_blocked_reason = "stage_wave_entries_missing"
            elif blocked_entries:
                definition_status = "blocked"
                definition_blocked_reason = "stage_wave_entry_blocked"
            stage_ability_refs = tuple(str(item) for item in row.get("StageAbilityConfig", ()) if str(item))
            definitions.append(
                WaveDefinitionIR(
                    wave_definition_id=f"wave_definition:stage:{_safe_id(stage_id)}",
                    stage_id=stage_id,
                    wave_count=wave_count,
                    entries=tuple(entries),
                    stage_ability_refs=stage_ability_refs,
                    source=IRSource(
                        source_path=relative_source_path(self.tbgd_root, path),
                        raw_type="StageConfig",
                        raw_id=stage_id,
                        evidence={
                            "StageID": stage_id,
                            "stage_row_index": row_index,
                            "declared_wave_count": declared_wave_count,
                            "monster_list_wave_count": len(monster_list),
                            "entry_count": len(entries),
                            "blocked_entry_count": len(blocked_entries),
                            "StageAbilityConfig": list(stage_ability_refs),
                            "Level": level,
                            "HardLevelGroup": hard_level_group,
                            "level_policy": level_policy,
                        },
                    ),
                    level=level,
                    hard_level_group=hard_level_group,
                    level_policy=level_policy,
                    coverage_status=definition_status,  # type: ignore[arg-type]
                    blocked_reason=definition_blocked_reason,
                )
            )
        return definitions

    def _hard_level_profiles(self) -> dict[tuple[int, int], dict[str, Any]]:
        relative = "ExcelOutput/HardLevelGroup.json"
        path = self.tbgd_root / relative
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(raw, list):
            return {}
        result: dict[tuple[int, int], dict[str, Any]] = {}
        for row_index, row in enumerate(_limit_sequence(raw, self.limits.max_records_per_table)):
            if not isinstance(row, dict):
                continue
            group = _positive_int(row.get("HardLevelGroup"))
            level = _positive_int(row.get("Level"))
            if group is None or level is None:
                continue
            result[(group, level)] = {**row, "_v8_source_path": relative, "_v8_row_index": row_index}
        return result

    def _lower_break_base_damage(self) -> list[BreakBaseDamageIR]:
        relative_path = "ExcelOutput/AvatarBreakDamage.json"
        path = self.tbgd_root / relative_path
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        rows: list[BreakBaseDamageIR] = []
        for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
            if not isinstance(row, dict):
                continue
            level_value = row.get("Level")
            break_base = _value_field(row.get("BreakBaseDamage"))
            hardness_base = _value_field(row.get("HardnessBaseDamage"))
            coverage_status = "executable"
            blocked_reason = ""
            if not isinstance(level_value, int):
                coverage_status = "blocked"
                blocked_reason = "break_base_damage_level_missing"
                level_value = -1
            if not isinstance(break_base, (int, float)):
                coverage_status = "blocked"
                blocked_reason = "break_base_damage_value_missing"
                break_base = 0.0
            rows.append(
                BreakBaseDamageIR(
                    level=int(level_value),
                    break_base_damage=float(break_base),
                    hardness_base_damage=float(hardness_base) if isinstance(hardness_base, (int, float)) else None,
                    source=IRSource(
                        source_path=relative_path,
                        raw_type="AvatarBreakDamage",
                        raw_id=str(level_value),
                        evidence={
                            "row_index": row_index,
                            "fields": {
                                "BreakBaseDamage": _json_safe(row.get("BreakBaseDamage")),
                                "HardnessBaseDamage": _json_safe(row.get("HardnessBaseDamage")),
                            },
                        },
                    ),
                    coverage_status=coverage_status,
                    blocked_reason=blocked_reason,
                )
            )
        return rows

    def _lower_break_templates(
        self,
    ) -> tuple[list[BreakTemplateIR], list[BreakDamageEmissionIR], list[BreakStatusEmissionIR], list[EffectIR]]:
        relative_path = "Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json"
        path = self.tbgd_root / relative_path
        if not path.exists():
            return [], [], [], []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return [], [], [], []
        templates = data.get("TaskListTemplate") if isinstance(data, dict) else None
        if not isinstance(templates, list):
            return [], [], [], []
        lowered_templates: list[BreakTemplateIR] = []
        damage_emissions: list[BreakDamageEmissionIR] = []
        status_emissions: list[BreakStatusEmissionIR] = []
        effects: list[EffectIR] = []
        for index, template in enumerate(templates):
            if not isinstance(template, dict):
                continue
            name = str(template.get("Name") or "")
            if not name.startswith("StanceBreak_"):
                continue
            task_list = template.get("TaskList")
            if not isinstance(task_list, list):
                task_list = []
            element = name.removeprefix("StanceBreak_") or None
            source = IRSource(
                source_path=relative_path,
                raw_type="GlobalTaskListTemplate",
                raw_id=name,
                evidence={
                    "row_index": index,
                    "task_count": len(task_list),
                    "purpose": "normal_weakness_break_lifecycle_template",
                },
            )
            lowered_templates.append(
                BreakTemplateIR(
                    template_id=f"break_template:{name}",
                    element_type=element,
                    task_names=tuple(_short_gamecore_type(task.get("$type")) for task in task_list if isinstance(task, dict)),
                    source=source,
                    coverage_status="executable",
                    blocked_reason="",
                )
            )
            for task_index, task in enumerate(task_list):
                if not isinstance(task, dict):
                    continue
                opcode = _short_gamecore_type(task.get("$type"))
                task_id = f"break_template_task:{name}:{task_index}:{opcode}"
                if opcode == "AddModifier":
                    payload = _effect_payload(task, opcode, name)
                    coverage_status = _effect_coverage_status(opcode, payload)
                    blocked_reason = _effect_blocked_reason(opcode, payload, coverage_status) if coverage_status != "executable" else ""
                    effect_id = f"break_effect:{name}:{task_index}:{opcode}"
                    status_emission_id = f"break_status_emission:{name}:{task_index}"
                    source = IRSource(
                        source_path=relative_path,
                        raw_type="GlobalBreakStatusTask",
                        raw_id=name,
                        evidence={
                            "template_id": f"break_template:{name}",
                            "break_status_emission_id": status_emission_id,
                            "task_index": task_index,
                            "task_id": task_id,
                            "opcode": opcode,
                            "task": _json_safe(task),
                        },
                    )
                    effects.append(
                        EffectIR(
                            effect_id=effect_id,
                            opcode=opcode,
                            payload=payload,
                            source=source,
                            coverage_status=coverage_status,
                        )
                    )
                    standard = payload.get("standard") if isinstance(payload.get("standard"), dict) else {}
                    status_emissions.append(
                        BreakStatusEmissionIR(
                            break_status_emission_id=status_emission_id,
                            template_id=f"break_template:{name}",
                            source_task_id=task_id,
                            effect_id=effect_id,
                            opcode=opcode,
                            target_alias=str(standard.get("target_alias") or "") or None,
                            modifier_name=str(standard.get("modifier_name") or "") or None,
                            source=source,
                            coverage_status=coverage_status,
                            blocked_reason=blocked_reason,
                        )
                    )
                    continue
                if opcode != "DamageByAttackProperty":
                    continue
                attack_property = task.get("AttackProperty")
                if not isinstance(attack_property, dict):
                    continue
                formula_type = str(attack_property.get("FormulaType") or "")
                if formula_type != "ByBreakDamage":
                    continue
                scaling_expr = _numeric_expr_summary(attack_property.get("BreakDamagePercentage"))
                coverage_status = "executable" if _numeric_expr_can_be_runtime_bound(scaling_expr) else "blocked"
                damage_emissions.append(
                    BreakDamageEmissionIR(
                        break_damage_emission_id=f"break_damage_emission:{name}:{task_index}",
                        template_id=f"break_template:{name}",
                        source_task_id=task_id,
                        element_type=element,
                        damage_formula_family="break",
                        scaling_expr=scaling_expr,
                        source=IRSource(
                            source_path=relative_path,
                            raw_type="GlobalBreakDamageTask",
                            raw_id=name,
                            evidence={
                                "template_id": f"break_template:{name}",
                                "task_index": task_index,
                                "task_id": task_id,
                                "opcode": opcode,
                                "attack_property": _json_safe(attack_property),
                            },
                        ),
                        coverage_status=coverage_status,
                        blocked_reason="" if coverage_status == "executable" else _break_damage_blocked_reason(scaling_expr),
                    )
                )
        return lowered_templates, damage_emissions, status_emissions, effects

    def _lower_super_break_emissions(self) -> list[SuperBreakEmissionIR]:
        relative_path = "Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json"
        path = self.tbgd_root / relative_path
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        templates = data.get("TaskListTemplate") if isinstance(data, dict) else None
        if not isinstance(templates, list):
            return []
        emissions: list[SuperBreakEmissionIR] = []
        admitted_templates = {"DealSuperBreakDamage", "BeingDealSuperBreakDamage"}
        for template_index, template in enumerate(templates):
            if not isinstance(template, dict):
                continue
            name = str(template.get("Name") or "")
            if name not in admitted_templates:
                continue
            for task_path, task in _iter_task_tree(template.get("TaskList"), prefix="TaskList"):
                opcode = _short_gamecore_type(task.get("$type"))
                if opcode != "DamageByAttackProperty":
                    continue
                attack_property = task.get("AttackProperty")
                if not isinstance(attack_property, dict):
                    continue
                if not _is_super_break_attack_property(attack_property, template_name=name):
                    continue
                scaling_expr = _numeric_expr_summary(attack_property.get("BreakDamagePercentage"))
                coverage_status = "executable" if _numeric_expr_can_be_runtime_bound(scaling_expr) else "blocked"
                blocked_reason = "" if coverage_status == "executable" else _super_break_blocked_reason(scaling_expr)
                source = IRSource(
                    source_path=relative_path,
                    raw_type="GlobalSuperBreakDamageTask",
                    raw_id=name,
                    evidence={
                        "template_id": f"super_break_template:{name}",
                        "template_index": template_index,
                        "task_path": task_path,
                        "opcode": opcode,
                        "attack_property": _json_safe(attack_property),
                    },
                )
                emissions.append(
                    SuperBreakEmissionIR(
                        super_break_emission_id=f"super_break_emission:{name}:{_safe_id(task_path)}",
                        template_id=f"super_break_template:{name}",
                        source_task_id=f"super_break_template_task:{name}:{_safe_id(task_path)}:{opcode}",
                        target_alias=_target_alias(task.get("TargetType")),
                        attack_type=str(attack_property.get("AttackType") or task.get("AttackType") or ""),
                        damage_formula_family="super_break",
                        element_type=_display_element_type(attack_property),
                        scaling_expr=scaling_expr,
                        source=source,
                        coverage_status=coverage_status,
                        blocked_reason=blocked_reason,
                    )
                )
        return emissions

    def _lower_queue_priorities(self) -> list[QueuePriorityIR]:
        relative_path = "Config/GlobalConfig/PriorityConfig.json"
        path = self.tbgd_root / relative_path
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        config = data.get("ConfigList") if isinstance(data, dict) else None
        if not isinstance(config, dict):
            return []
        priorities: list[QueuePriorityIR] = []
        for table_name in ("InsertAbilityPriority", "InsertActionPriority"):
            table = config.get(table_name)
            priority_keys = table.get("PriorityKeys") if isinstance(table, dict) else None
            if not isinstance(priority_keys, dict):
                continue
            for priority_key, priority_value in sorted(priority_keys.items()):
                coverage_status = "executable" if isinstance(priority_value, (int, float)) else "blocked"
                blocked_reason = "" if coverage_status == "executable" else "queue_priority_value_not_numeric"
                priorities.append(
                    QueuePriorityIR(
                        queue_priority_id=f"queue_priority:{table_name}:{priority_key}",
                        priority_table=table_name,
                        priority_key=str(priority_key),
                        priority_value=float(priority_value) if isinstance(priority_value, (int, float)) else 0.0,
                        source=IRSource(
                            source_path=relative_path,
                            raw_type="PriorityConfig",
                            raw_id=f"{table_name}:{priority_key}",
                            evidence={
                                "table": table_name,
                                "priority_key": str(priority_key),
                                "priority_value": _json_safe(priority_value),
                                "raw_path": f"ConfigList.{table_name}.PriorityKeys.{priority_key}",
                            },
                        ),
                        coverage_status=coverage_status,
                        blocked_reason=blocked_reason,
                    )
                )
        return priorities

    def _extra_turn_source_basis(self) -> dict[str, Any]:
        basis: dict[str, Any] = {
            "source_kind": "extra_turn_source_discovery",
            "source_basis_status": "blocked",
            "blocking_dependency": "extra_turn_lifecycle_source_missing",
            "evidence": {},
        }
        enum_path = "Config/GlobalConfig/JsonEnumDefineConfig.json"
        enum_data = _read_json_file(self.tbgd_root / enum_path)
        if isinstance(enum_data, dict):
            modifier_flags = _enum_values(enum_data, "ModifierBehaviorFlag")
            modifier_states = _enum_values(enum_data, "ModifierState")
            enum_evidence: dict[str, Any] = {}
            if "OneMore" in modifier_flags:
                enum_evidence["ModifierBehaviorFlag.OneMore"] = {
                    "value": modifier_flags["OneMore"],
                    "source": IRSource(
                        source_path=enum_path,
                        raw_type="JsonEnumDefineConfig",
                        raw_id="ModifierBehaviorFlag.OneMore",
                        evidence={"enum": "ModifierBehaviorFlag", "key": "OneMore", "value": modifier_flags["OneMore"]},
                    ).to_json(),
                }
            if "OneMoreCount" in modifier_flags:
                enum_evidence["ModifierBehaviorFlag.OneMoreCount"] = {
                    "value": modifier_flags["OneMoreCount"],
                    "source": IRSource(
                        source_path=enum_path,
                        raw_type="JsonEnumDefineConfig",
                        raw_id="ModifierBehaviorFlag.OneMoreCount",
                        evidence={"enum": "ModifierBehaviorFlag", "key": "OneMoreCount", "value": modifier_flags["OneMoreCount"]},
                    ).to_json(),
                }
            if "OneMore" in modifier_states:
                enum_evidence["ModifierState.OneMore"] = {
                    "value": modifier_states["OneMore"],
                    "source": IRSource(
                        source_path=enum_path,
                        raw_type="JsonEnumDefineConfig",
                        raw_id="ModifierState.OneMore",
                        evidence={"enum": "ModifierState", "key": "OneMore", "value": modifier_states["OneMore"]},
                    ).to_json(),
                }
            if enum_evidence:
                basis["evidence"]["enum"] = enum_evidence

        const_path = "Config/GlobalConfig/GameCoreConstValue.json"
        const_data = _read_json_file(self.tbgd_root / const_path)
        custom_switches = const_data.get("CustomSwitchMap") if isinstance(const_data, dict) else None
        if isinstance(custom_switches, dict) and "InsertAbilityAfterUltraSkillEndDontTickAbility" in custom_switches:
            value = custom_switches.get("InsertAbilityAfterUltraSkillEndDontTickAbility")
            basis["evidence"]["insert_ability_after_ultra_skill_end_dont_tick_ability"] = {
                "value": _json_safe(value),
                "source": IRSource(
                    source_path=const_path,
                    raw_type="GameCoreConstValue",
                    raw_id="CustomSwitchMap.InsertAbilityAfterUltraSkillEndDontTickAbility",
                    evidence={
                        "raw_path": "CustomSwitchMap.InsertAbilityAfterUltraSkillEndDontTickAbility",
                        "value": _json_safe(value),
                    },
                ).to_json(),
            }

        modifier_path = "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json"
        modifier_data = _read_json_file(self.tbgd_root / modifier_path)
        modifier_map = modifier_data.get("ModifierMap") if isinstance(modifier_data, dict) else None
        modifier = modifier_map.get("OneMore") if isinstance(modifier_map, dict) else None
        if isinstance(modifier, dict):
            behavior_flags = tuple(str(item) for item in modifier.get("BehaviorFlagList", ()) if isinstance(item, str))
            lifetime = modifier.get("LifeTime")
            life_step_moment = modifier.get("LifeStepMoment")
            lifecycle_admitted = (
                "OneMore" in behavior_flags
                and isinstance(lifetime, (int, float))
                and str(life_step_moment) == "ActionPhaseEnd"
            )
            source = IRSource(
                source_path=modifier_path,
                raw_type="ConfigGlobalModifier",
                raw_id="OneMore",
                evidence={
                    "modifier_name": "OneMore",
                    "raw_path": "ModifierMap.OneMore",
                    "BehaviorFlagList": list(behavior_flags),
                    "LifeTime": _json_safe(lifetime),
                    "LifeStepMoment": _json_safe(life_step_moment),
                    "Stacking": _json_safe(modifier.get("Stacking")),
                },
            )
            basis["evidence"]["one_more_modifier"] = {
                "lifecycle_admitted": lifecycle_admitted,
                "source": source.to_json(),
            }
            if lifecycle_admitted:
                basis["source_basis_status"] = "lifecycle_source_admitted"
                basis["blocking_dependency"] = ""
                basis["lifecycle_policy"] = {
                    "turn_begin_policy": "queue_extra_turn_begin_event",
                    "turn_end_policy": "queue_extra_turn_end_event",
                    "duration_tick_policy": "ActionPhaseEnd_from_OneMore_LifeStepMoment",
                    "av_policy": "queue_child_bypasses_natural_av_advance",
                    "natural_turn_policy": "extra_turn_is_non_natural_queue_turn",
                    "reentry_policy": "append_pending_no_recursive_drain",
                    "remaining_duration": int(lifetime),
                }
            else:
                basis["blocking_dependency"] = "one_more_modifier_lifecycle_not_admitted"
        return basis

    def _lower_combatant_action_sets(
        self,
        definitions: list[ActionDefinitionIR],
    ) -> list[CombatantActionSetIR]:
        definitions_by_action: dict[str, list[ActionDefinitionIR]] = {}
        for definition in definitions:
            definitions_by_action.setdefault(definition.action_id, []).append(definition)
        rows: list[CombatantActionSetIR] = []
        for relative_path, entity_type, id_key, skill_key, config_rows in (
            ("ExcelOutput/AvatarConfig.json", "avatar", "AvatarID", "SkillList", self._avatar_config_rows_prefer_enhanced()),
            ("ExcelOutput/MonsterConfig.json", "monster", "MonsterID", "SkillList", None),
            ("ExcelOutput/MonsterUniqueConfig.json", "monster", "MonsterID", "SkillList", None),
            ("ExcelOutput/AvatarServantConfig.json", "servant", "ServantID", "SkillIDList", None),
        ):
            path = self.tbgd_root / relative_path
            if config_rows is None:
                if not path.exists():
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(data, list):
                    continue
                config_rows = [
                    (relative_path, row_index, row)
                    for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table))
                ]
            for source_relative_path, row_index, row in config_rows:
                if not isinstance(row, dict) or id_key not in row:
                    continue
                raw_id = str(row[id_key])
                skills = row.get(skill_key)
                if not isinstance(skills, list):
                    skills = []
                skill_index_map: dict[str, JSONValue] = {}
                for index, skill_id in enumerate(skills):
                    if entity_type == "avatar":
                        action_ref = f"avatar_skill:{skill_id}"
                    elif entity_type == "servant":
                        action_ref = f"servant_skill:{skill_id}"
                    else:
                        action_ref = f"monster_skill:{skill_id}"
                    candidate_definitions = definitions_by_action.get(action_ref, ())
                    compatible_definitions = _compatible_action_definitions_for_combatant_action_set(
                        entity_type,
                        candidate_definitions,
                    )
                    levels = sorted({definition.level for definition in compatible_definitions})
                    blocked_reason = ""
                    if not levels:
                        blocked_reason = (
                            "action_definition_source_mismatch_for_monster_config_skill"
                            if entity_type == "monster" and candidate_definitions
                            else "action_definition_source_mismatch_for_servant_config_skill"
                            if entity_type == "servant" and candidate_definitions
                            else "action_definition_missing_for_skill"
                        )
                    skill_index_map[str(index)] = {
                        "skill_id": str(skill_id),
                        "action_ref": action_ref,
                        "levels": levels,
                        "default_level": levels[-1] if levels else None,
                        "coverage_status": "executable" if levels else "blocked",
                        "blocked_reason": blocked_reason,
                    }
                coverage_status = "executable" if any(
                    isinstance(item, dict) and item.get("coverage_status") == "executable"
                    for item in skill_index_map.values()
                ) else "blocked"
                rows.append(
                    CombatantActionSetIR(
                        combatant_action_set_id=f"combatant_action_set:{entity_type}:{raw_id}",
                        entity_ref=f"{entity_type}:{raw_id}",
                        skill_index_map=skill_index_map,
                        source=IRSource(
                            source_path=source_relative_path,
                            raw_type=Path(source_relative_path).stem,
                            raw_id=raw_id,
                            evidence={
                                "row_index": row_index,
                                "id_key": id_key,
                                "skill_list": _json_safe(skills),
                                "skill_list_field": skill_key,
                                "version_kind": str(row.get("_v8_version_kind") or "base"),
                                "base_source_path": str(row.get("_v8_base_source_path") or source_relative_path),
                                "base_skill_list": _json_safe(row.get("_v8_base_skill_list") or []),
                                "enhanced_source_path": str(row.get("_v8_enhanced_source_path") or ""),
                                "enhanced_id": _json_safe(row.get("_v8_enhanced_id")),
                                "enhanced_overrides_base": str(row.get("_v8_version_kind") or "base") == "enhanced",
                            },
                        ),
                        coverage_status=coverage_status,
                        blocked_reason="" if coverage_status == "executable" else "combatant_action_set_has_no_executable_actions",
                    )
                )
        return rows

    def _rows_by_id(self, relative_path: str, id_key: str) -> dict[str, dict[str, Any]]:
        path = self.tbgd_root / relative_path
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return {}
        rows: dict[str, dict[str, Any]] = {}
        for row in _limit_sequence(data, self.limits.max_records_per_table):
            if isinstance(row, dict) and id_key in row:
                rows[str(row[id_key])] = row
        return rows

    def _avatar_config_rows_prefer_enhanced(self) -> list[tuple[str, int, dict[str, Any]]]:
        base_rows: list[tuple[str, int, dict[str, Any]]] = []
        for relative_path in ("ExcelOutput/AvatarConfig.json", "ExcelOutput/AvatarConfigLD.json"):
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
                if isinstance(row, dict) and row.get("AvatarID") is not None:
                    copied = dict(row)
                    copied["_v8_version_kind"] = "base"
                    copied["_v8_base_source_path"] = relative_path
                    copied["_v8_base_row_index"] = row_index
                    copied["_v8_base_skill_list"] = _json_safe(row.get("SkillList") or [])
                    base_rows.append((relative_path, row_index, copied))

        enhanced_rows: list[tuple[str, int, dict[str, Any]]] = []
        enhanced_relative = "ExcelOutput/AvatarConfigEnhanced.json"
        enhanced_path = self.tbgd_root / enhanced_relative
        if enhanced_path.exists():
            try:
                enhanced_data = json.loads(enhanced_path.read_text(encoding="utf-8"))
            except Exception:
                enhanced_data = []
            if isinstance(enhanced_data, list):
                for row_index, row in enumerate(_limit_sequence(enhanced_data, self.limits.max_records_per_table)):
                    if isinstance(row, dict) and row.get("AvatarID") is not None:
                        enhanced_rows.append((enhanced_relative, row_index, dict(row)))

        enhanced_by_avatar = {str(row["AvatarID"]): (relative_path, row_index, row) for relative_path, row_index, row in enhanced_rows}
        rows: list[tuple[str, int, dict[str, Any]]] = []
        seen: set[str] = set()
        for base_relative, base_index, base_row in base_rows:
            avatar_id = str(base_row["AvatarID"])
            enhanced = enhanced_by_avatar.get(avatar_id)
            if enhanced is None:
                rows.append((base_relative, base_index, base_row))
                seen.add(avatar_id)
                continue
            enhanced_relative_path, enhanced_index, enhanced_row = enhanced
            merged = {**base_row, **enhanced_row}
            for key in ("DamageType", "AvatarBaseType", "Rarity"):
                if not merged.get(key):
                    merged[key] = base_row.get(key)
            merged["_v8_version_kind"] = "enhanced"
            merged["_v8_base_source_path"] = base_relative
            merged["_v8_base_row_index"] = base_index
            merged["_v8_base_skill_list"] = _json_safe(base_row.get("SkillList") or [])
            merged["_v8_enhanced_source_path"] = enhanced_relative_path
            merged["_v8_enhanced_row_index"] = enhanced_index
            merged["_v8_enhanced_id"] = enhanced_row.get("EnhancedID")
            merged["_v8_enhanced_skill_list"] = _json_safe(enhanced_row.get("SkillList") or [])
            rows.append((enhanced_relative_path, enhanced_index, merged))
            seen.add(avatar_id)

        for enhanced_relative_path, enhanced_index, enhanced_row in enhanced_rows:
            avatar_id = str(enhanced_row["AvatarID"])
            if avatar_id in seen:
                continue
            copied = dict(enhanced_row)
            copied["_v8_version_kind"] = "enhanced"
            copied["_v8_enhanced_source_path"] = enhanced_relative_path
            copied["_v8_enhanced_row_index"] = enhanced_index
            copied["_v8_enhanced_id"] = enhanced_row.get("EnhancedID")
            copied["_v8_enhanced_skill_list"] = _json_safe(enhanced_row.get("SkillList") or [])
            rows.append((enhanced_relative_path, enhanced_index, copied))
        return rows

    def _lower_action_ability_bindings(
        self,
        definitions: list[ActionDefinitionIR],
    ) -> tuple[
        list[ActionAbilityBindingIR],
        list[AbilityPhaseIR],
        list[AbilityTaskIR],
        list[EffectIR],
        list[ConditionIR],
        list[FormulaIR],
        list[TargetExpressionIR],
    ]:
        avatar_skill_rows = self._avatar_skill_rows_by_skill_id()
        avatar_configs = self._avatar_configs_by_skill_id()
        monster_skill_rows = self._monster_skill_rows_by_skill_id()
        monster_configs = self._monster_configs_by_skill_id()
        servant_skill_rows = self._servant_skill_rows_by_skill_id()
        servant_configs = self._servant_configs_by_skill_id()
        monster_ability_file_index: dict[str, tuple[str, ...]] | None = None
        ability_file_cache: dict[str, dict[str, Any] | None] = {}
        bindings: list[ActionAbilityBindingIR] = []
        phases: list[AbilityPhaseIR] = []
        tasks: list[AbilityTaskIR] = []
        effects: list[EffectIR] = []
        conditions: list[ConditionIR] = []
        formulas: list[FormulaIR] = []
        target_expressions: list[TargetExpressionIR] = []
        for definition in definitions:
            if definition.action_id.startswith("avatar_skill:"):
                binding, binding_phases, lowered_tasks = self._avatar_action_binding(
                    definition,
                    avatar_skill_rows.get(definition.source.raw_id, {}),
                    avatar_configs.get(definition.source.raw_id, []),
                    avatar_skill_rows,
                    ability_file_cache,
                )
            elif definition.action_id.startswith("monster_skill:"):
                if monster_ability_file_index is None:
                    monster_ability_file_index = self._monster_ability_file_index()
                binding, binding_phases, lowered_tasks = self._monster_action_binding(
                    definition,
                    monster_skill_rows.get(definition.source.raw_id, {}),
                    monster_configs.get(definition.source.raw_id, []),
                    monster_skill_rows,
                    ability_file_cache,
                    monster_ability_file_index,
                )
            elif definition.action_id.startswith("servant_skill:"):
                binding, binding_phases, lowered_tasks = self._servant_action_binding(
                    definition,
                    servant_skill_rows.get(definition.source.raw_id, {}),
                    servant_configs.get(definition.source.raw_id, []),
                    servant_skill_rows,
                    ability_file_cache,
                )
            else:
                binding, binding_phases, lowered_tasks = _blocked_action_binding(definition, "non_avatar_ability_binding_not_executable")
            bindings.append(binding)
            phases.extend(binding_phases)
            tasks.extend(lowered_tasks.ability_tasks)
            effects.extend(lowered_tasks.effects)
            conditions.extend(lowered_tasks.conditions)
            formulas.extend(lowered_tasks.formulas)
            target_expressions.extend(lowered_tasks.target_expressions)
        return bindings, phases, tasks, effects, conditions, formulas, target_expressions

    def _lower_standalone_ability_graphs(
        self,
        ability_files: list[Path],
    ) -> tuple[
        list[StandaloneAbilityGraphIR],
        list[AbilityPhaseIR],
        list[AbilityTaskIR],
        list[EffectIR],
        list[ConditionIR],
        list[FormulaIR],
        list[TargetExpressionIR],
    ]:
        graphs: list[StandaloneAbilityGraphIR] = []
        phases: list[AbilityPhaseIR] = []
        tasks: list[AbilityTaskIR] = []
        effects: list[EffectIR] = []
        conditions: list[ConditionIR] = []
        formulas: list[FormulaIR] = []
        target_expressions: list[TargetExpressionIR] = []
        for path in ability_files:
            relative = relative_source_path(self.tbgd_root, path)
            if not _standalone_ability_source_admitted(relative):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            ability_map = _ability_map(data)
            source_mode = _standalone_ability_source_mode(relative)
            for ability_index, (ability_name, ability) in enumerate(sorted(ability_map.items())):
                action_id = f"standalone_ability:{ability_name}"
                phase_id = f"standalone_ability_phase:{_safe_id(relative)}:{ability_index}:{_safe_id(ability_name)}"
                graph_id = f"standalone_ability_graph:{_safe_id(relative)}:{_safe_id(ability_name)}"
                definition = _StandaloneActionRef(action_id=action_id, level=0)
                lowered = self._lower_ability_phase_tasks(
                    definition=definition,  # type: ignore[arg-type]
                    phase_id=phase_id,
                    ability_name=ability_name,
                    ability=ability,
                    ability_path=relative,
                )
                tasks.extend(lowered.ability_tasks)
                effects.extend(lowered.effects)
                conditions.extend(lowered.conditions)
                formulas.extend(lowered.formulas)
                target_expressions.extend(lowered.target_expressions)
                task_ids = tuple(task.task_id for task in lowered.ability_tasks)
                executable_task_ids = tuple(
                    task.task_id
                    for task in lowered.ability_tasks
                    if task.coverage_status == "executable" and task.effect_id
                )
                phase = AbilityPhaseIR(
                    phase_id=phase_id,
                    binding_id=graph_id,
                    action_id=action_id,
                    level=0,
                    ability_name=ability_name,
                    phase_index=0,
                    target_info=_json_safe(ability.get("TargetInfo")) if isinstance(ability.get("TargetInfo"), dict) else {},
                    opcode_summary=_ability_opcode_summary(ability),
                    callback_summaries=_ability_callback_summaries(ability),
                    source=IRSource(
                        source_path=relative,
                        raw_type="StandaloneAbilityList",
                        raw_id=ability_name,
                        evidence={
                            "ability_index": ability_index,
                            "ability_name": ability_name,
                            "source_mode": source_mode,
                            "purpose": "queue_insert_ability_resolution",
                        },
                    ),
                    coverage_status="lowered",
                    blocked_reason="",
                    task_ids=task_ids,
                )
                phases.append(phase)
                graphs.append(
                    StandaloneAbilityGraphIR(
                        standalone_ability_graph_id=graph_id,
                        ability_name=ability_name,
                        source_mode=source_mode,
                        phase_ids=(phase_id,),
                        task_ids=task_ids,
                        executable_task_ids=executable_task_ids,
                        source=phase.source,
                        coverage_status="executable" if task_ids else "blocked",
                        blocked_reason="" if task_ids else "standalone_ability_has_no_tasks",
                    )
                )
        return graphs, phases, tasks, effects, conditions, formulas, target_expressions

    def _avatar_skill_rows_by_skill_id(self) -> dict[str, dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        for relative_path, _, id_key in CHARACTER_ACTION_DEFINITION_TABLES:
            if "AvatarSkillConfig" not in relative_path and "CommonAvatarSkillConfig" not in relative_path:
                continue
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                continue
            for row in data:
                if isinstance(row, dict) and id_key in row:
                    rows[str(row[id_key])] = row
        return rows

    def _avatar_configs_by_skill_id(self) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for relative_path, index, row in self._avatar_config_rows_prefer_enhanced():
            if not isinstance(row, dict):
                continue
            for skill_id in row.get("SkillList") or []:
                config = {
                    "relative_path": relative_path,
                    "row_index": index,
                    "avatar_id": row.get("AvatarID"),
                    "json_path": row.get("JsonPath"),
                    "skill_list": row.get("SkillList"),
                    "version_kind": row.get("_v8_version_kind") or "base",
                    "base_source_path": row.get("_v8_base_source_path") or relative_path,
                    "base_skill_list": row.get("_v8_base_skill_list") or [],
                    "enhanced_source_path": row.get("_v8_enhanced_source_path") or "",
                    "enhanced_id": row.get("_v8_enhanced_id"),
                    "enhanced_skill_list": row.get("_v8_enhanced_skill_list") or [],
                }
                result.setdefault(str(skill_id), []).append(config)
        return result

    def _monster_skill_rows_by_skill_id(self) -> dict[str, dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        for relative_path in ("ExcelOutput/MonsterSkillConfig.json", "ExcelOutput/MonsterSkillUniqueConfig.json"):
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
                if isinstance(row, dict) and row.get("SkillID") is not None:
                    copied = dict(row)
                    copied["_v8_source_path"] = relative_path
                    copied["_v8_row_index"] = row_index
                    rows[str(row["SkillID"])] = copied
        return rows

    def _monster_configs_by_skill_id(self) -> dict[str, list[dict[str, Any]]]:
        template_rows: dict[str, dict[str, Any]] = {}
        for relative_path in ("ExcelOutput/MonsterTemplateConfig.json", "ExcelOutput/MonsterTemplateUniqueConfig.json"):
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
                if isinstance(row, dict) and row.get("MonsterTemplateID") is not None:
                    copied = dict(row)
                    copied["_v8_source_path"] = relative_path
                    copied["_v8_row_index"] = row_index
                    template_rows[str(row["MonsterTemplateID"])] = copied

        result: dict[str, list[dict[str, Any]]] = {}
        for relative_path in ("ExcelOutput/MonsterConfig.json", "ExcelOutput/MonsterUniqueConfig.json"):
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
                if not isinstance(row, dict) or row.get("MonsterID") is None:
                    continue
                template_id = str(row.get("MonsterTemplateID") or "")
                template_row = template_rows.get(template_id, {})
                config = {
                    "relative_path": relative_path,
                    "row_index": row_index,
                    "monster_id": row.get("MonsterID"),
                    "template_id": template_id,
                    "json_path": template_row.get("JsonConfig"),
                    "skill_list": row.get("SkillList") or [],
                    "template_source_path": template_row.get("_v8_source_path") or "",
                    "template_row_index": template_row.get("_v8_row_index"),
                    "override_skill_params": _json_safe(row.get("OverrideSkillParams") or []),
                    "custom_values": _json_safe(row.get("CustomValues") or {}),
                    "dynamic_values": _json_safe(row.get("DynamicValues") or {}),
                }
                for skill_id in row.get("SkillList") or []:
                    result.setdefault(str(skill_id), []).append(config)
        return result

    def _servant_skill_rows_by_skill_id(self) -> dict[str, dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        relative_path = "ExcelOutput/AvatarServantSkillConfig.json"
        path = self.tbgd_root / relative_path
        if not path.exists():
            return rows
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return rows
        if not isinstance(data, list):
            return rows
        best_levels: dict[str, int] = {}
        for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
            if not isinstance(row, dict) or row.get("SkillID") is None:
                continue
            skill_id = str(row["SkillID"])
            level = int(_number_value(row.get("Level"), 1.0))
            if skill_id in rows and level < best_levels.get(skill_id, 0):
                continue
            copied = dict(row)
            copied["_v8_source_path"] = relative_path
            copied["_v8_row_index"] = row_index
            best_levels[skill_id] = level
            rows[skill_id] = copied
        return rows

    def _servant_configs_by_skill_id(self) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        relative_path = "ExcelOutput/AvatarServantConfig.json"
        path = self.tbgd_root / relative_path
        if not path.exists():
            return result
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return result
        if not isinstance(data, list):
            return result
        for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
            if not isinstance(row, dict) or row.get("ServantID") is None:
                continue
            skills = row.get("SkillIDList") if isinstance(row.get("SkillIDList"), list) else []
            config = {
                "relative_path": relative_path,
                "row_index": row_index,
                "servant_id": row.get("ServantID"),
                "json_path": row.get("Config"),
                "skill_list": skills,
                "hp_skill": row.get("HPSkill"),
                "speed_skill": row.get("SpeedSkill"),
            }
            for skill_id in skills:
                result.setdefault(str(skill_id), []).append(config)
        return result

    def _servant_stat_skill_rows_by_skill_id(self) -> dict[str, dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        best_levels: dict[str, int] = {}
        for relative_path, _, id_key in (
            *CHARACTER_ACTION_DEFINITION_TABLES,
            ("ExcelOutput/AvatarServantSkillConfig.json", "servant_skill", "SkillID"),
        ):
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
                if not isinstance(row, dict) or row.get(id_key) is None:
                    continue
                skill_id = str(row[id_key])
                level = int(_number_value(row.get("Level"), 1.0))
                if skill_id in rows and level < best_levels.get(skill_id, 0):
                    continue
                copied = dict(row)
                copied["_v8_source_path"] = relative_path
                copied["_v8_row_index"] = row_index
                best_levels[skill_id] = level
                rows[skill_id] = copied
        return rows

    def _monster_ability_file_index(self) -> dict[str, tuple[str, ...]]:
        indexed: dict[str, list[str]] = {}
        roots = (
            self.tbgd_root / "Config/ConfigAbility/Monster",
        )
        for root in roots:
            if not root.exists():
                continue
            for path in sorted(root.rglob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                relative_path = relative_source_path(self.tbgd_root, path)
                for ability_name in _ability_map(data):
                    indexed.setdefault(ability_name, []).append(relative_path)
        return {name: tuple(paths) for name, paths in indexed.items()}

    def _avatar_action_binding(
        self,
        definition: ActionDefinitionIR,
        skill_row: dict[str, Any],
        avatar_configs: list[dict[str, Any]],
        avatar_skill_rows: dict[str, dict[str, Any]],
        ability_file_cache: dict[str, dict[str, Any] | None],
    ) -> tuple[ActionAbilityBindingIR, list[AbilityPhaseIR], "_LoweredAbility"]:
        skill_trigger_key = str(skill_row.get("SkillTriggerKey") or definition.source.evidence.get("skill_trigger_key") or "")
        if not skill_trigger_key:
            return _blocked_action_binding(definition, "missing_skill_trigger_key")
        mainline_configs = [
            config
            for config in avatar_configs
            if isinstance(config.get("json_path"), str)
            and str(config.get("json_path", "")).startswith("Config/ConfigCharacter/Avatar/")
        ]
        if not mainline_configs:
            return _blocked_action_binding(definition, "missing_mainline_avatar_config")
        avatar_config = sorted(mainline_configs, key=lambda item: str(item.get("relative_path")))[0]
        character_path = str(avatar_config.get("json_path") or "")
        character_config = self._read_json_dict(character_path)
        if character_config is None:
            return _blocked_action_binding(definition, "avatar_character_config_not_readable", character_path)
        skill_config = _skill_config_by_name(character_config, skill_trigger_key)
        if not skill_config:
            return _blocked_action_binding(definition, "skill_trigger_key_not_in_character_config", character_path)
        entry_ability = str(skill_config.get("EntryAbility") or "")
        ability_names = _ability_names_for_skill(character_config, skill_trigger_key, entry_ability)
        if not entry_ability or not ability_names:
            return _blocked_action_binding(definition, "missing_entry_ability_or_skill_ability_list", character_path)
        ability_path = _avatar_ability_path_from_character_path(character_path)
        ability_data = ability_file_cache.setdefault(ability_path, self._read_json_dict(ability_path))
        if ability_data is None:
            return _blocked_action_binding(definition, "avatar_ability_file_not_readable", ability_path)
        ability_map = _ability_map(ability_data)
        ability_names = _expand_triggered_ability_names(ability_names, ability_map)
        source_context = _ability_graph_source_context(
            source_mode="mainline_avatar",
            skill_row=skill_row,
            skill_trigger_key=skill_trigger_key,
            character_path=character_path,
            character_config=character_config,
            config_source=avatar_config,
            config_kind="avatar_config",
            ability_paths=(ability_path,),
            skill_rows_by_trigger_key=_skill_rows_by_trigger_key_for_config(avatar_config, avatar_skill_rows, skill_row),
            allowed_dynamic_hashes=_dynamic_hashes_for_ability_names(ability_names, ability_map),
        )
        binding_id = f"action_binding:{definition.action_id}:{definition.level}"
        binding_phases: list[AbilityPhaseIR] = []
        lowered = _LoweredAbility()
        missing_names = [name for name in ability_names if name not in ability_map]
        for phase_index, ability_name in enumerate(ability_names):
            ability = ability_map.get(ability_name)
            if not isinstance(ability, dict):
                continue
            source = IRSource(
                source_path=ability_path,
                raw_type="AbilityList",
                raw_id=ability_name,
                evidence={
                    "action_id": definition.action_id,
                    "level": definition.level,
                    "phase_index": phase_index,
                    "skill_trigger_key": skill_trigger_key,
                    "entry_ability": entry_ability,
                    "ability_source_context": source_context,
                },
            )
            phase_id = f"ability_phase:{definition.action_id}:{definition.level}:{phase_index}:{ability_name}"
            phase_lowered = self._lower_ability_phase_tasks(
                definition=definition,
                phase_id=phase_id,
                ability_name=ability_name,
                ability=ability,
                ability_path=ability_path,
                source_context=source_context,
            )
            lowered.merge(phase_lowered)
            binding_phases.append(
                AbilityPhaseIR(
                    phase_id=phase_id,
                    binding_id=binding_id,
                    action_id=definition.action_id,
                    level=definition.level,
                    ability_name=ability_name,
                    phase_index=phase_index,
                    target_info=_json_safe(ability.get("TargetInfo")) if isinstance(ability.get("TargetInfo"), dict) else {},
                    opcode_summary=_ability_opcode_summary(ability),
                    callback_summaries=_ability_callback_summaries(ability),
                    source=source,
                    coverage_status="lowered",
                    blocked_reason="",
                    task_ids=tuple(task.task_id for task in phase_lowered.ability_tasks),
                )
            )
        blocked_reason = "missing_ability_phase_in_ability_file" if missing_names else ""
        coverage_status = "blocked" if blocked_reason or not binding_phases else "executable"
        source = IRSource(
            source_path=character_path,
            raw_type="AvatarCharacterConfig",
            raw_id=skill_trigger_key,
            evidence={
                "action_id": definition.action_id,
                "level": definition.level,
                "avatar_id": _json_safe(avatar_config.get("avatar_id")),
                "avatar_config": _json_safe(avatar_config),
                "ability_file": ability_path,
                "missing_ability_names": missing_names,
                "trigger_expanded_ability_names": ability_names,
            },
        )
        return (
            ActionAbilityBindingIR(
                binding_id=binding_id,
                action_id=definition.action_id,
                level=definition.level,
                skill_trigger_key=skill_trigger_key,
                skill_name=str(skill_config.get("Name") or skill_trigger_key),
                entry_ability=entry_ability,
                ability_names=tuple(ability_names),
                config_source={
                    "avatar_config": _json_safe(avatar_config),
                    "character_config_path": character_path,
                    "ability_file_path": ability_path,
                },
                phase_ids=tuple(phase.phase_id for phase in binding_phases),
                source_mode="mainline_avatar",
                source=source,
                coverage_status=coverage_status,
                blocked_reason=blocked_reason,
            ),
            binding_phases,
            lowered,
        )

    def _monster_action_binding(
        self,
        definition: ActionDefinitionIR,
        skill_row: dict[str, Any],
        monster_configs: list[dict[str, Any]],
        monster_skill_rows: dict[str, dict[str, Any]],
        ability_file_cache: dict[str, dict[str, Any] | None],
        ability_file_index: dict[str, tuple[str, ...]],
    ) -> tuple[ActionAbilityBindingIR, list[AbilityPhaseIR], "_LoweredAbility"]:
        skill_trigger_key = str(skill_row.get("SkillTriggerKey") or definition.source.evidence.get("skill_trigger_key") or "")
        if not skill_trigger_key:
            return _blocked_action_binding(definition, "missing_monster_skill_trigger_key")
        mainline_configs = [
            config
            for config in monster_configs
            if isinstance(config.get("json_path"), str)
            and str(config.get("json_path") or "").startswith("Config/ConfigCharacter/Monster/")
        ]
        if not mainline_configs:
            return _blocked_action_binding(definition, "missing_mainline_monster_config")
        monster_config = sorted(
            mainline_configs,
            key=lambda item: (str(item.get("json_path") or ""), str(item.get("monster_id") or "")),
        )[0]
        character_path = str(monster_config.get("json_path") or "")
        character_config = self._read_json_dict(character_path)
        if character_config is None:
            return _blocked_action_binding(definition, "monster_character_config_not_readable", character_path)
        skill_config = _skill_config_by_name(character_config, skill_trigger_key)
        if not skill_config:
            return _blocked_action_binding(definition, "monster_skill_trigger_key_not_in_character_config", character_path)
        entry_ability = str(skill_config.get("EntryAbility") or "")
        ability_names = _ability_names_for_skill(character_config, skill_trigger_key, entry_ability)
        if not entry_ability or not ability_names:
            return _blocked_action_binding(definition, "missing_monster_entry_ability_or_skill_ability_list", character_path)

        resolved_paths, missing_names, ambiguous_names = _resolve_monster_ability_paths(ability_names, ability_file_index)
        combined_ability_map: dict[str, dict[str, Any]] = {}
        for ability_path in resolved_paths.values():
            ability_data = ability_file_cache.setdefault(ability_path, self._read_json_dict(ability_path))
            if ability_data is None:
                continue
            combined_ability_map.update(_ability_map(ability_data))
        expanded_names = _expand_triggered_ability_names(ability_names, combined_ability_map)
        if tuple(expanded_names) != tuple(ability_names):
            ability_names = expanded_names
            resolved_paths, missing_names, ambiguous_names = _resolve_monster_ability_paths(ability_names, ability_file_index)

        source_context = _ability_graph_source_context(
            source_mode="mainline_monster",
            skill_row=skill_row,
            skill_trigger_key=skill_trigger_key,
            character_path=character_path,
            character_config=character_config,
            config_source=monster_config,
            config_kind="monster_config",
            ability_paths=tuple(sorted(set(resolved_paths.values()))),
            skill_rows_by_trigger_key=_skill_rows_by_trigger_key_for_config(monster_config, monster_skill_rows, skill_row),
            allowed_dynamic_hashes=_dynamic_hashes_for_ability_names(ability_names, combined_ability_map),
        )
        binding_id = f"action_binding:{definition.action_id}:{definition.level}"
        binding_phases: list[AbilityPhaseIR] = []
        lowered = _LoweredAbility()
        unreadable_paths: list[str] = []
        for phase_index, ability_name in enumerate(ability_names):
            ability_path = resolved_paths.get(ability_name, "")
            if not ability_path:
                continue
            ability_data = ability_file_cache.setdefault(ability_path, self._read_json_dict(ability_path))
            if ability_data is None:
                unreadable_paths.append(ability_path)
                continue
            ability_map = _ability_map(ability_data)
            ability = ability_map.get(ability_name)
            if not isinstance(ability, dict):
                missing_names.append(ability_name)
                continue
            source = IRSource(
                source_path=ability_path,
                raw_type="AbilityList",
                raw_id=ability_name,
                evidence={
                    "action_id": definition.action_id,
                    "level": definition.level,
                    "phase_index": phase_index,
                    "skill_trigger_key": skill_trigger_key,
                    "entry_ability": entry_ability,
                    "monster_id": _json_safe(monster_config.get("monster_id")),
                    "template_id": _json_safe(monster_config.get("template_id")),
                    "character_config_path": character_path,
                    "ability_source_context": source_context,
                },
            )
            phase_id = f"ability_phase:{definition.action_id}:{definition.level}:{phase_index}:{ability_name}"
            phase_lowered = self._lower_ability_phase_tasks(
                definition=definition,
                phase_id=phase_id,
                ability_name=ability_name,
                ability=ability,
                ability_path=ability_path,
                source_context=source_context,
            )
            lowered.merge(phase_lowered)
            binding_phases.append(
                AbilityPhaseIR(
                    phase_id=phase_id,
                    binding_id=binding_id,
                    action_id=definition.action_id,
                    level=definition.level,
                    ability_name=ability_name,
                    phase_index=phase_index,
                    target_info=_json_safe(ability.get("TargetInfo")) if isinstance(ability.get("TargetInfo"), dict) else {},
                    opcode_summary=_ability_opcode_summary(ability),
                    callback_summaries=_ability_callback_summaries(ability),
                    source=source,
                    coverage_status="lowered",
                    blocked_reason="",
                    task_ids=tuple(task.task_id for task in phase_lowered.ability_tasks),
                )
            )
        blocking_reasons = []
        if missing_names:
            blocking_reasons.append("missing_monster_ability_name")
        if ambiguous_names:
            blocking_reasons.append("ambiguous_monster_ability_name")
        if unreadable_paths:
            blocking_reasons.append("monster_ability_file_not_readable")
        if not binding_phases:
            blocking_reasons.append("missing_monster_ability_phase_in_ability_file")
        blocked_reason = ";".join(dict.fromkeys(blocking_reasons))
        coverage_status = "blocked" if blocked_reason else "executable"
        source = IRSource(
            source_path=character_path,
            raw_type="MonsterCharacterConfig",
            raw_id=skill_trigger_key,
            evidence={
                "action_id": definition.action_id,
                "level": definition.level,
                "monster_config": _json_safe(monster_config),
                "skill_trigger_key": skill_trigger_key,
                "entry_ability": entry_ability,
                "ability_file_paths": sorted(set(resolved_paths.values())),
                "missing_ability_names": list(missing_names),
                "ambiguous_ability_names": ambiguous_names,
                "unreadable_ability_paths": unreadable_paths,
                "trigger_expanded_ability_names": ability_names,
            },
        )
        return (
            ActionAbilityBindingIR(
                binding_id=binding_id,
                action_id=definition.action_id,
                level=definition.level,
                skill_trigger_key=skill_trigger_key,
                skill_name=str(skill_config.get("Name") or skill_trigger_key),
                entry_ability=entry_ability,
                ability_names=tuple(ability_names),
                config_source={
                    "monster_config": _json_safe(monster_config),
                    "character_config_path": character_path,
                    "ability_file_paths": sorted(set(resolved_paths.values())),
                },
                phase_ids=tuple(phase.phase_id for phase in binding_phases),
                source_mode="mainline_monster",
                source=source,
                coverage_status=coverage_status,
                blocked_reason=blocked_reason,
            ),
            binding_phases,
            lowered,
        )

    def _servant_action_binding(
        self,
        definition: ActionDefinitionIR,
        skill_row: dict[str, Any],
        servant_configs: list[dict[str, Any]],
        servant_skill_rows: dict[str, dict[str, Any]],
        ability_file_cache: dict[str, dict[str, Any] | None],
    ) -> tuple[ActionAbilityBindingIR, list[AbilityPhaseIR], "_LoweredAbility"]:
        skill_trigger_key = str(skill_row.get("SkillTriggerKey") or definition.source.evidence.get("skill_trigger_key") or "")
        if not skill_trigger_key:
            return _blocked_action_binding(definition, "missing_servant_skill_trigger_key")
        mainline_configs = [
            config
            for config in servant_configs
            if isinstance(config.get("json_path"), str)
            and str(config.get("json_path") or "").startswith("Config/ConfigCharacter/Servant/")
        ]
        if not mainline_configs:
            return _blocked_action_binding(definition, "missing_mainline_servant_config")
        servant_config = sorted(
            mainline_configs,
            key=lambda item: (str(item.get("json_path") or ""), str(item.get("servant_id") or "")),
        )[0]
        character_path = str(servant_config.get("json_path") or "")
        character_config = self._read_json_dict(character_path)
        if character_config is None:
            return _blocked_action_binding(definition, "servant_character_config_not_readable", character_path)
        skill_config = _skill_config_by_name(character_config, skill_trigger_key)
        if not skill_config:
            return _blocked_action_binding(definition, "servant_skill_trigger_key_not_in_character_config", character_path)
        entry_ability = str(skill_config.get("EntryAbility") or "")
        ability_names = _ability_names_for_skill(character_config, skill_trigger_key, entry_ability)
        if not entry_ability or not ability_names:
            return _blocked_action_binding(definition, "missing_servant_entry_ability_or_skill_ability_list", character_path)
        ability_path = _servant_ability_path_from_character_path(character_path)
        ability_data = ability_file_cache.setdefault(ability_path, self._read_json_dict(ability_path))
        if ability_data is None:
            return _blocked_action_binding(definition, "servant_ability_file_not_readable", ability_path)
        ability_map = _ability_map(ability_data)
        ability_names = _expand_triggered_ability_names(ability_names, ability_map)
        source_context = _ability_graph_source_context(
            source_mode="mainline_servant",
            skill_row=skill_row,
            skill_trigger_key=skill_trigger_key,
            character_path=character_path,
            character_config=character_config,
            config_source=servant_config,
            config_kind="servant_config",
            ability_paths=(ability_path,),
            skill_rows_by_trigger_key=_skill_rows_by_trigger_key_for_config(servant_config, servant_skill_rows, skill_row),
            allowed_dynamic_hashes=_dynamic_hashes_for_ability_names(ability_names, ability_map),
        )
        binding_id = f"action_binding:{definition.action_id}:{definition.level}"
        binding_phases: list[AbilityPhaseIR] = []
        lowered = _LoweredAbility()
        missing_names = [name for name in ability_names if name not in ability_map]
        for phase_index, ability_name in enumerate(ability_names):
            ability = ability_map.get(ability_name)
            if not isinstance(ability, dict):
                continue
            source = IRSource(
                source_path=ability_path,
                raw_type="AbilityList",
                raw_id=ability_name,
                evidence={
                    "action_id": definition.action_id,
                    "level": definition.level,
                    "phase_index": phase_index,
                    "skill_trigger_key": skill_trigger_key,
                    "entry_ability": entry_ability,
                    "servant_id": _json_safe(servant_config.get("servant_id")),
                    "character_config_path": character_path,
                    "ability_source_context": source_context,
                },
            )
            phase_id = f"ability_phase:{definition.action_id}:{definition.level}:{phase_index}:{ability_name}"
            phase_lowered = self._lower_ability_phase_tasks(
                definition=definition,
                phase_id=phase_id,
                ability_name=ability_name,
                ability=ability,
                ability_path=ability_path,
                source_context=source_context,
            )
            lowered.merge(phase_lowered)
            binding_phases.append(
                AbilityPhaseIR(
                    phase_id=phase_id,
                    binding_id=binding_id,
                    action_id=definition.action_id,
                    level=definition.level,
                    ability_name=ability_name,
                    phase_index=phase_index,
                    target_info=_json_safe(ability.get("TargetInfo")) if isinstance(ability.get("TargetInfo"), dict) else {},
                    opcode_summary=_ability_opcode_summary(ability),
                    callback_summaries=_ability_callback_summaries(ability),
                    source=source,
                    coverage_status="lowered",
                    blocked_reason="",
                    task_ids=tuple(task.task_id for task in phase_lowered.ability_tasks),
                )
            )
        blocked_reason = "missing_servant_ability_phase_in_ability_file" if missing_names or not binding_phases else ""
        coverage_status = "blocked" if blocked_reason else "executable"
        source = IRSource(
            source_path=character_path,
            raw_type="ServantCharacterConfig",
            raw_id=skill_trigger_key,
            evidence={
                "action_id": definition.action_id,
                "level": definition.level,
                "servant_config": _json_safe(servant_config),
                "skill_trigger_key": skill_trigger_key,
                "entry_ability": entry_ability,
                "ability_file_path": ability_path,
                "missing_ability_names": missing_names,
                "trigger_expanded_ability_names": ability_names,
            },
        )
        return (
            ActionAbilityBindingIR(
                binding_id=binding_id,
                action_id=definition.action_id,
                level=definition.level,
                skill_trigger_key=skill_trigger_key,
                skill_name=str(skill_config.get("Name") or skill_trigger_key),
                entry_ability=entry_ability,
                ability_names=tuple(ability_names),
                config_source={
                    "servant_config": _json_safe(servant_config),
                    "character_config_path": character_path,
                    "ability_file_path": ability_path,
                },
                phase_ids=tuple(phase.phase_id for phase in binding_phases),
                source_mode="mainline_servant",
                source=source,
                coverage_status=coverage_status,
                blocked_reason=blocked_reason,
            ),
            binding_phases,
            lowered,
        )

    def _lower_ability_phase_tasks(
        self,
        *,
        definition: ActionDefinitionIR,
        phase_id: str,
        ability_name: str,
        ability: dict[str, Any],
        ability_path: str,
        source_context: dict[str, Any] | None = None,
    ) -> "_LoweredAbility":
        lowered = _LoweredAbility()
        for callback_kind in ABILITY_TASK_CALLBACKS:
            callback_tasks = ability.get(callback_kind)
            if not isinstance(callback_tasks, list):
                continue
            for task_index, task in enumerate(callback_tasks):
                task_lowered = self._lower_ability_task_tree(
                    task,
                    definition=definition,
                    phase_id=phase_id,
                    ability_name=ability_name,
                    ability_path=ability_path,
                    callback_kind=callback_kind,
                    task_index=task_index,
                    task_path=f"{callback_kind}[{task_index}]",
                    branch="root",
                    parent_task_id="",
                    source_context=source_context,
                )
                lowered.merge(task_lowered)
        return lowered

    def _lower_ability_task_tree(
        self,
        task: Any,
        *,
        definition: ActionDefinitionIR,
        phase_id: str,
        ability_name: str,
        ability_path: str,
        callback_kind: str,
        task_index: int,
        task_path: str,
        branch: str,
        parent_task_id: str,
        source_context: dict[str, Any] | None = None,
    ) -> "_LoweredAbility":
        lowered = _LoweredAbility()
        if not isinstance(task, dict):
            return lowered
        opcode = _short_gamecore_type(task.get("$type"))
        task_id = f"ability_task:{phase_id}:{callback_kind}:{task_path}:{opcode}"
        source = IRSource(
            source_path=ability_path,
            raw_type="AbilityTask",
            raw_id=ability_name,
            evidence={
                "action_id": definition.action_id,
                "level": definition.level,
                "phase_id": phase_id,
                "callback_kind": callback_kind,
                "task_index": task_index,
                "task_path": task_path,
                "branch": branch,
                "parent_task_id": parent_task_id,
                "ability_source_context": _json_safe(source_context or {}),
            },
        )
        self_expression = _target_expression_from_raw(
            task,
            field_name="$self",
            expression_id=f"target_expression:{task_id}:self",
            source=source,
        )
        if self_expression is not None:
            lowered.target_expressions.append(self_expression)
        if opcode == "PredicateTaskList":
            condition = self._lower_ability_task_condition(task.get("Predicate"), source, task_id)
            if condition:
                lowered.conditions.append(condition)
            success_ids: list[str] = []
            failed_ids: list[str] = []
            for child_index, child in enumerate(task.get("SuccessTaskList") or []):
                child_lowered = self._lower_ability_task_tree(
                    child,
                    definition=definition,
                    phase_id=phase_id,
                    ability_name=ability_name,
                    ability_path=ability_path,
                    callback_kind=callback_kind,
                    task_index=child_index,
                    task_path=f"{task_path}.SuccessTaskList[{child_index}]",
                    branch="success",
                    parent_task_id=task_id,
                    source_context=source_context,
                )
                lowered.merge(child_lowered)
                success_ids.extend(
                    item.task_id
                    for item in child_lowered.ability_tasks
                    if item.parent_task_id == task_id
                )
            for child_index, child in enumerate(task.get("FailedTaskList") or []):
                child_lowered = self._lower_ability_task_tree(
                    child,
                    definition=definition,
                    phase_id=phase_id,
                    ability_name=ability_name,
                    ability_path=ability_path,
                    callback_kind=callback_kind,
                    task_index=child_index,
                    task_path=f"{task_path}.FailedTaskList[{child_index}]",
                    branch="failed",
                    parent_task_id=task_id,
                    source_context=source_context,
                )
                lowered.merge(child_lowered)
                failed_ids.extend(
                    item.task_id
                    for item in child_lowered.ability_tasks
                    if item.parent_task_id == task_id
                )
            coverage_status, blocked_reason = _predicate_task_status(condition)
            lowered.ability_tasks.insert(
                0,
                AbilityTaskIR(
                    task_id=task_id,
                    phase_id=phase_id,
                    action_id=definition.action_id,
                    level=definition.level,
                    ability_name=ability_name,
                    callback_kind=callback_kind,
                    task_index=task_index,
                    task_path=task_path,
                    branch=branch,
                    opcode=opcode,
                    condition_id=condition.condition_id if condition else "",
                    parent_task_id=parent_task_id,
                    child_task_ids=tuple(success_ids + failed_ids),
                    success_task_ids=tuple(success_ids),
                    failed_task_ids=tuple(failed_ids),
                    source=source,
                    coverage_status=coverage_status,
                    blocked_reason=blocked_reason,
                ),
            )
            return lowered

        effect_id = f"effect:{task_id}"
        payload = _effect_payload(task, opcode, "")
        payload, task_target_expressions = _attach_target_expressions_to_effect_payload(
            payload,
            task,
            effect_id=effect_id,
            source=source,
        )
        lowered.target_expressions.extend(task_target_expressions)
        coverage_status = _effect_coverage_status(opcode, payload)
        blocked_reason = "" if coverage_status == "executable" else _effect_blocked_reason(opcode, payload, coverage_status)
        lowered.effects.append(
            EffectIR(
                effect_id=effect_id,
                opcode=opcode,
                payload=payload,
                source=source,
                coverage_status=coverage_status,
            )
        )
        lowered.formulas.extend(self._extract_formulas(task, source, effect_id))
        lowered.formulas.extend(_damage_family_evidence(task, opcode, source, effect_id))
        lowered.ability_tasks.append(
            AbilityTaskIR(
                task_id=task_id,
                phase_id=phase_id,
                action_id=definition.action_id,
                level=definition.level,
                ability_name=ability_name,
                callback_kind=callback_kind,
                task_index=task_index,
                task_path=task_path,
                branch=branch,
                opcode=opcode,
                effect_id=effect_id,
                parent_task_id=parent_task_id,
                source=source,
                coverage_status="executable" if coverage_status == "executable" else "blocked",
                blocked_reason=blocked_reason,
            )
        )
        return lowered

    def _lower_ability_task_condition(
        self,
        predicate: Any,
        source: IRSource,
        task_id: str,
    ) -> ConditionIR | None:
        if not isinstance(predicate, dict):
            return None
        opcode = _short_gamecore_type(predicate.get("$type"))
        payload = _compact_payload(predicate)
        status = "executable" if _condition_payload_executable(opcode, payload) else classify_opcode(opcode)
        return ConditionIR(
            condition_id=f"condition:{task_id}:{opcode}",
            opcode=opcode,
            payload=payload,
            source=source,
            coverage_status=status,
        )

    def _read_json_dict(self, relative_path: str) -> dict[str, Any] | None:
        path = self.tbgd_root / relative_path
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _lower_entity_table(
        self,
        relative_path: str,
        spec: tuple[str, str, tuple[str, ...]],
    ) -> list[RuleEntity]:
        entity_type, id_key, field_keys = spec
        path = self.tbgd_root / relative_path
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        entities: list[RuleEntity] = []
        for index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
            if not isinstance(row, dict) or id_key not in row:
                continue
            raw_id = _entity_raw_id(entity_type, id_key, row)
            fields = {key: _json_safe(row.get(key)) for key in field_keys if key in row}
            source = IRSource(
                source_path=relative_path,
                raw_type=Path(relative_path).stem,
                raw_id=raw_id,
                evidence={"row_index": index, "id_key": id_key},
            )
            entities.append(
                RuleEntity(
                    entity_id=f"{entity_type}:{raw_id}",
                    entity_type=entity_type,
                    fields=fields,
                    source=source,
                    coverage_status="audit_only",
                )
            )
        return entities

    def _lower_action_definitions(self) -> dict[tuple[str, int], ActionDefinitionIR]:
        definitions: dict[tuple[str, int], ActionDefinitionIR] = {}
        monster_target_sources = self._monster_skill_target_mode_sources()
        for relative_path, entity_type, id_key in ACTION_DEFINITION_TABLES:
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                continue
            for index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
                if not isinstance(row, dict) or id_key not in row:
                    continue
                raw_id = str(row[id_key])
                definition = _action_definition_from_row(
                    relative_path,
                    entity_type,
                    id_key,
                    index,
                    row,
                    monster_target_source=monster_target_sources.get(raw_id)
                    if entity_type == "monster_skill"
                    else None,
                )
                definitions[(definition.action_id, definition.level)] = definition
        return definitions

    def _monster_skill_target_mode_sources(self) -> dict[str, dict[str, Any]]:
        skill_rows: dict[str, dict[str, Any]] = {}
        for relative_path in ("ExcelOutput/MonsterSkillConfig.json", "ExcelOutput/MonsterSkillUniqueConfig.json"):
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
                if isinstance(row, dict) and row.get("SkillID") is not None:
                    copied = dict(row)
                    copied["_v8_source_path"] = relative_path
                    copied["_v8_row_index"] = row_index
                    skill_rows[str(row["SkillID"])] = copied

        template_rows: dict[str, dict[str, Any]] = {}
        for relative_path in ("ExcelOutput/MonsterTemplateConfig.json", "ExcelOutput/MonsterTemplateUniqueConfig.json"):
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
                if isinstance(row, dict) and row.get("MonsterTemplateID") is not None:
                    copied = dict(row)
                    copied["_v8_source_path"] = relative_path
                    copied["_v8_row_index"] = row_index
                    template_rows[str(row["MonsterTemplateID"])] = copied

        result: dict[str, dict[str, Any]] = {}
        path = self.tbgd_root / "ExcelOutput/MonsterConfig.json"
        if not path.exists():
            return result
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return result
        if not isinstance(data, list):
            return result
        for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
            if not isinstance(row, dict) or row.get("MonsterID") is None:
                continue
            template_id = str(row.get("MonsterTemplateID") or "")
            template_row = template_rows.get(template_id, {})
            json_config = str(template_row.get("JsonConfig") or "")
            if not json_config:
                continue
            character_config = self._read_json_dict(json_config)
            if character_config is None:
                continue
            skill_ids = row.get("SkillList") if isinstance(row.get("SkillList"), list) else []
            for skill_id_value in skill_ids:
                skill_id = str(skill_id_value)
                skill_row = skill_rows.get(skill_id, {})
                trigger_key = str(skill_row.get("SkillTriggerKey") or "")
                if not trigger_key:
                    continue
                skill_config = _skill_config_by_name(character_config, trigger_key)
                if not skill_config:
                    continue
                target_info = skill_config.get("TargetInfo")
                target_type = str(target_info.get("TargetType") or "") if isinstance(target_info, dict) else ""
                target_mode = _monster_target_mode(target_type)
                source = {
                    "target_mode": target_mode,
                    "target_type": target_type,
                    "skill_trigger_key": trigger_key,
                    "monster_id": str(row.get("MonsterID") or ""),
                    "template_id": template_id,
                    "character_config_path": json_config,
                    "target_info": _json_safe(target_info) if isinstance(target_info, dict) else {},
                    "source_trace": {
                        "monster_config": {
                            "source_path": "ExcelOutput/MonsterConfig.json",
                            "raw_type": "MonsterConfig",
                            "raw_id": str(row.get("MonsterID") or ""),
                            "row_index": row_index,
                            "raw_path": "SkillList",
                        },
                        "template_config": {
                            "source_path": str(template_row.get("_v8_source_path") or ""),
                            "raw_type": Path(str(template_row.get("_v8_source_path") or "")).stem,
                            "raw_id": template_id,
                            "row_index": template_row.get("_v8_row_index"),
                            "raw_path": "JsonConfig",
                        },
                        "character_config": {
                            "source_path": json_config,
                            "raw_type": "MonsterCharacterConfig",
                            "raw_id": trigger_key,
                            "raw_path": "SkillList.TargetInfo",
                        },
                    },
                    "coverage_status": "blocked" if target_mode == "unknown" else "lowered",
                    "blocked_reason": "" if target_mode != "unknown" else f"unsupported_monster_target_type:{target_type}",
                    "monster_count": 1,
                }
                existing = result.get(skill_id)
                if existing is not None:
                    if existing.get("target_mode") != target_mode or existing.get("target_type") != target_type:
                        result[skill_id] = {
                            **existing,
                            "target_mode": "unknown",
                            "coverage_status": "blocked",
                            "blocked_reason": "monster_skill_target_mode_conflict",
                            "conflicting_target_source": source,
                            "monster_count": int(existing.get("monster_count") or 1) + 1,
                        }
                    else:
                        existing["monster_count"] = int(existing.get("monster_count") or 1) + 1
                else:
                    result[skill_id] = source
        return result

    def _table_stats(self, relative_path: str, id_key: str) -> dict[str, Any]:
        path = self.tbgd_root / relative_path
        if not path.exists():
            return {"raw_count": 0, "lowered_count": 0, "skipped_count": 0, "missing": True}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return {"raw_count": 0, "lowered_count": 0, "skipped_count": 0, "shape": type(data).__name__}
        selected = _limit_sequence(data, self.limits.max_records_per_table)
        lowered_count = sum(1 for row in selected if isinstance(row, dict) and id_key in row)
        return {
            "raw_count": len(data),
            "lowered_count": lowered_count,
            "skipped_count": max(0, len(data) - len(selected)),
            "sampled": len(selected) < len(data),
            "id_key": id_key,
        }

    def _lower_summon_unit_definitions(self) -> list[SummonUnitDefinitionIR]:
        relative_path = "ExcelOutput/SummonUnitData.json"
        path = self.tbgd_root / relative_path
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        definitions: list[SummonUnitDefinitionIR] = []
        for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
            if not isinstance(row, dict) or row.get("ID") is None:
                continue
            summon_unit_id = str(row.get("ID"))
            config_path = str(row.get("JsonPath") or "")
            config = self._read_json_dict(config_path) if config_path else None
            config_summary = _summon_unit_config_summary(config)
            summon_kind = _summon_unit_kind(row, config_summary)
            blocked_reason = _summon_unit_blocked_reason(row, config_summary)
            raw_flags = _summon_unit_raw_flags(row)
            battle_admission = _summon_unit_battle_admission(row, config_summary, blocked_reason)
            source = IRSource(
                source_path=relative_path,
                raw_type="SummonUnitData",
                raw_id=summon_unit_id,
                evidence={
                    "row_index": row_index,
                    "config_path": config_path,
                    "config_source_exists": config is not None,
                    "config_summary": config_summary,
                    "raw_flags": raw_flags,
                    "source_mode": battle_admission["source_mode"],
                    "source_boundary": "summon_unit_definition_only_not_spawn_trigger",
                    "raw_paths": {
                        "json_path": "JsonPath",
                        "is_client": "IsClient",
                        "is_team_summon": "IsTeamSummon",
                        "destroy_on_enter_battle": "DestroyOnEnterBattle",
                        "max_summon_count": "MaxSummonCount",
                        "unique_group": "UniqueGroup",
                    },
                },
            )
            definitions.append(
                SummonUnitDefinitionIR(
                    summon_definition_id=f"summon_unit_definition:{summon_unit_id}",
                    summon_unit_id=summon_unit_id,
                    summon_kind=summon_kind,
                    config_path=config_path,
                    unique_group=str(row.get("UniqueGroup") or ""),
                    max_summon_count=_optional_int(row.get("MaxSummonCount")),
                    destroy_on_enter_battle=_optional_bool(row.get("DestroyOnEnterBattle")),
                    remove_maze_buff_on_destroy=_optional_bool(row.get("RemoveMazeBuffOnDestroy")),
                    battle_admission=battle_admission,
                    skill_config=config_summary,
                    source=source,
                    coverage_status="blocked",
                    blocked_reason=blocked_reason,
                )
            )
        return definitions

    def _ability_files(self) -> list[Path]:
        roots = [self.tbgd_root / "Config/ConfigAbility", self.tbgd_root / "Config/ConfigGlobalModifier"]
        files: list[Path] = []
        for root in roots:
            if not root.exists():
                continue
            files.extend(path for path in root.rglob("*.json") if not path.name.endswith(".layout.json"))
        return sorted(files)

    def _lower_servant_definitions(
        self,
        combatant_action_sets: list[CombatantActionSetIR],
        action_ability_bindings: list[ActionAbilityBindingIR],
    ) -> list[ServantDefinitionIR]:
        relative_path = "ExcelOutput/AvatarServantConfig.json"
        path = self.tbgd_root / relative_path
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        definitions: list[ServantDefinitionIR] = []
        action_set_by_entity = {item.entity_ref: item for item in combatant_action_sets}
        bindings_by_action = {(item.action_id, item.level): item for item in action_ability_bindings}
        stat_skill_rows = self._servant_stat_skill_rows_by_skill_id()
        avatar_configs = self._avatar_configs_by_skill_id()
        for row_index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
            if not isinstance(row, dict) or row.get("ServantID") is None:
                continue
            servant_id = str(row.get("ServantID"))
            servant_ref = f"servant:{servant_id}"
            config_path = str(row.get("Config") or "")
            ability_path = _servant_ability_path_from_character_path(config_path) if config_path else ""
            ability_data = self._read_json_dict(ability_path) if ability_path else None
            ability_names = tuple(sorted(_ability_map(ability_data))) if isinstance(ability_data, dict) else ()
            action_set_ir = action_set_by_entity.get(servant_ref)
            action_set, binding_ids = _servant_action_set_admission(
                servant_ref,
                action_set_ir,
                bindings_by_action,
            )
            stat_source = _servant_stat_source(row, stat_skill_rows)
            owner_entity_ref, owner_source = _servant_owner_entity_ref(row, avatar_configs)
            if owner_source:
                stat_source["owner_source"] = owner_source
            timeline_source = _servant_timeline_source(row, stat_source)
            lifecycle_source = _servant_lifecycle_source(row)
            action_set_status = str(action_set.get("admission_status") or action_set.get("coverage_status") or "")
            blocked_reason = _servant_definition_blocked_reason(
                owner_entity_ref=owner_entity_ref,
                config_path=config_path,
                ability_path=ability_path,
                ability_data=ability_data,
                action_set_status=action_set_status,
                stat_source=stat_source,
                timeline_source=timeline_source,
                lifecycle_source=lifecycle_source,
            )
            coverage_status = "blocked" if blocked_reason else "executable"
            source = IRSource(
                source_path=relative_path,
                raw_type="AvatarServantConfig",
                raw_id=servant_id,
                evidence={
                    "row_index": row_index,
                    "id_key": "ServantID",
                    "servant_ref": servant_ref,
                    "owner_entity_ref": owner_entity_ref,
                    "config_path": config_path,
                    "ability_path": ability_path,
                    "ability_count": len(ability_names),
                    "ability_names": list(ability_names),
                    "skill_id_list": _json_safe(row.get("SkillIDList") or []),
                    "raw_paths": {
                        "config": "Config",
                        "skill_id_list": "SkillIDList",
                        "hp_base": "HPBase",
                        "hp_inherit": "HPInherit",
                        "hp_skill": "HPSkill",
                        "speed_base": "SpeedBase",
                        "speed_inherit": "SpeedInherit",
                        "speed_skill": "SpeedSkill",
                        "aggro": "Aggro",
                    },
                    "unit_admission": "executable" if coverage_status == "executable" else "blocked",
                    "blocked_reason": blocked_reason,
                },
            )
            definitions.append(
                ServantDefinitionIR(
                    servant_definition_id=f"servant_definition:{servant_id}",
                    servant_ref=servant_ref,
                    owner_entity_ref=owner_entity_ref,
                    representation="unit" if coverage_status == "executable" else "blocked",
                    ability_graph_ids=tuple(binding_ids),
                    action_set=action_set,
                    stat_source=stat_source,
                    timeline_source=timeline_source,
                    lifecycle_source=lifecycle_source,
                    source=source,
                    birth_template_id=_servant_birth_template_id(servant_id),
                    coverage_status=coverage_status,
                    blocked_reason=blocked_reason,
                )
            )
        return definitions

    def _lower_ability_file(
        self,
        path: Path,
        queue_priority_lookup: dict[tuple[str, str], QueuePriorityIR],
    ) -> "_LoweredAbility":
        relative = relative_source_path(self.tbgd_root, path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return _LoweredAbility()
        modifier_maps = self._modifier_maps(data)
        lowered = _LoweredAbility()
        callback_index = 0
        for map_name, modifier_name, modifier in modifier_maps:
            lowered.entities.append(_modifier_definition_entity(relative, map_name, modifier_name, modifier))
            callbacks = modifier.get("_CallbackList") if isinstance(modifier, dict) else None
            if not isinstance(callbacks, list):
                continue
            for callback in callbacks:
                if (
                    self.limits.max_callbacks_per_file is not None
                    and callback_index >= self.limits.max_callbacks_per_file
                ):
                    return lowered
                callback_index += 1
                if not isinstance(callback, dict):
                    continue
                event = str(callback.get("Event") or "UnknownEvent")
                tasks = callback.get("CallbackConfig") or []
                if not isinstance(tasks, list):
                    continue
                trigger_effects: list[str] = []
                trigger_conditions: list[str] = []
                for task_index, task in enumerate(tasks):
                    task_lowered = self._lower_task(
                        task,
                        relative,
                        map_name,
                        modifier_name,
                        callback_index,
                        task_index,
                        branch="callback",
                    )
                    lowered.merge(task_lowered)
                    trigger_effects.extend(effect.effect_id for effect in task_lowered.effects)
                    trigger_conditions.extend(condition.condition_id for condition in task_lowered.conditions)
                callback_id = f"status_callback:{relative}:{modifier_name}:{callback_index}:{event}"
                callback_lowered = self._lower_status_callback_tasks(
                    tasks,
                    relative=relative,
                    map_name=map_name,
                    modifier_name=modifier_name,
                    callback_id=callback_id,
                    event=event,
                    callback_index=callback_index,
                    queue_priority_lookup=queue_priority_lookup,
                )
                lowered.merge(callback_lowered)
                source = IRSource(
                    source_path=relative,
                    raw_type=map_name,
                    raw_id=modifier_name,
                    evidence={"callback_index": callback_index, "event": event},
                )
                callback_task_ids = tuple(
                    task.task_id
                    for task in callback_lowered.status_callback_tasks
                    if not task.parent_task_id
                )
                source_mode = _status_callback_source_mode(relative)
                source_admitted = _status_callback_source_admitted(relative)
                scope_kind = _status_callback_scope_kind(event)
                has_executable_queue_intent = any(
                    intent.coverage_status == "executable"
                    for intent in callback_lowered.queue_intents
                    if intent.callback_id == callback_id
                )
                has_executable_callback_task = any(
                    task.coverage_status == "executable"
                    for task in callback_lowered.status_callback_tasks
                    if task.callback_id == callback_id
                )
                foundational_events = {
                    "OnBeforeSkillUse",
                    "OnBeforeHit",
                    "OnAfterAttack",
                    "OnActionEnd",
                    "OnCreate",
                    "OnDestroy",
                    "OnEnterBattle",
                    "OnListenTurnEnd",
                    "OnBeforeInsertActionPrepare",
                    "OnInsertActionStart",
                    "OnInsertActionFinish",
                    "OnListenInsertAbilityFinish",
                    "OnCustomEvent",
                }
                admitted_event = event in {"OnStack", "OnPhase1"} or (
                    event == "OnListenTurnEnd"
                    and any(task.coverage_status == "executable" for task in callback_lowered.status_callback_tasks)
                ) or has_executable_queue_intent or (
                    event in {
                        "OnTriggerDeath",
                        "OnListenCharacterDie",
                        "OnTriggerDeathrattle",
                        "OnBeforeHitAll",
                        "OnAfterHitAll",
                        "OnAfterBeingAttacked",
                        "OnAfterSkillUse",
                        "OnBeforeDying",
                        "OnListenAllowAction",
                        *foundational_events,
                    }
                    and has_executable_callback_task
                )
                status = (
                    "executable"
                    if admitted_event and (source_admitted or has_executable_queue_intent or has_executable_callback_task)
                    else "blocked"
                )
                if status == "executable":
                    blocked_reason = ""
                elif not source_admitted:
                    blocked_reason = "status_callback_source_mode_not_admitted"
                else:
                    blocked_reason = f"status_callback_event_not_admitted:{event}"
                blocking_dependency = "" if status == "executable" else blocked_reason
                lowered.status_callbacks.append(
                    StatusCallbackIR(
                        callback_id=callback_id,
                        modifier_name=modifier_name,
                        event=event,
                        task_ids=callback_task_ids,
                        source=source,
                        coverage_status=status,
                        blocked_reason=blocked_reason,
                        scope_kind=scope_kind,
                        source_mode=source_mode,
                        admission_status=status,
                        blocking_dependency=blocking_dependency,
                    )
                )
                lowered.triggers.append(
                    TriggerIR(
                        trigger_id=f"trigger:{relative}:{modifier_name}:{callback_index}",
                        event=event,
                        conditions=tuple(trigger_conditions),
                        effects=tuple(trigger_effects),
                        source=source,
                        coverage_status="audit_only",
                    )
                )
        return lowered

    def _lower_status_callback_tasks(
        self,
        tasks: Any,
        *,
        relative: str,
        map_name: str,
        modifier_name: str,
        callback_id: str,
        event: str,
        callback_index: int,
        queue_priority_lookup: dict[tuple[str, str], QueuePriorityIR],
    ) -> "_LoweredAbility":
        lowered = _LoweredAbility()
        if not isinstance(tasks, list):
            return lowered
        for task_index, task in enumerate(tasks):
            task_lowered = self._lower_status_callback_task_tree(
                task,
                relative=relative,
                map_name=map_name,
                modifier_name=modifier_name,
                callback_id=callback_id,
                event=event,
                callback_index=callback_index,
                task_index=task_index,
                task_path=f"CallbackConfig[{task_index}]",
                branch="root",
                parent_task_id="",
                queue_priority_lookup=queue_priority_lookup,
            )
            lowered.merge(task_lowered)
        return lowered

    def _lower_status_callback_task_tree(
        self,
        task: Any,
        *,
        relative: str,
        map_name: str,
        modifier_name: str,
        callback_id: str,
        event: str,
        callback_index: int,
        task_index: int,
        task_path: str,
        branch: str,
        parent_task_id: str,
        queue_priority_lookup: dict[tuple[str, str], QueuePriorityIR],
    ) -> "_LoweredAbility":
        lowered = _LoweredAbility()
        if not isinstance(task, dict):
            return lowered
        opcode = _short_gamecore_type(task.get("$type"))
        task_id = f"status_callback_task:{relative}:{modifier_name}:{callback_index}:{task_path}:{opcode}"
        evidence: dict[str, Any] = {
            "callback_id": callback_id,
            "callback_index": callback_index,
            "event": event,
            "task_index": task_index,
            "task_path": task_path,
            "branch": branch,
            "parent_task_id": parent_task_id,
            "opcode": opcode,
            "task": _json_safe(task),
        }
        if opcode == "Retarget":
            evidence["retarget"] = _retarget_task_evidence(task)
        source = IRSource(
            source_path=relative,
            raw_type=map_name,
            raw_id=modifier_name,
            evidence=evidence,
        )
        self_expression = _target_expression_from_raw(
            task,
            field_name="$self",
            expression_id=f"target_expression:{task_id}:self",
            source=source,
        )
        if self_expression is not None:
            lowered.target_expressions.append(self_expression)
        if opcode == "PredicateTaskList":
            condition = self._lower_condition(task.get("Predicate"), source, task_index)
            if condition:
                lowered.conditions.append(condition)
            success_ids: list[str] = []
            failed_ids: list[str] = []
            for child_index, child in enumerate(task.get("SuccessTaskList") or []):
                child_lowered = self._lower_status_callback_task_tree(
                    child,
                    relative=relative,
                    map_name=map_name,
                    modifier_name=modifier_name,
                    callback_id=callback_id,
                    event=event,
                    callback_index=callback_index,
                    task_index=child_index,
                    task_path=f"{task_path}.SuccessTaskList[{child_index}]",
                    branch="success",
                    parent_task_id=task_id,
                    queue_priority_lookup=queue_priority_lookup,
                )
                lowered.merge(child_lowered)
                success_ids.extend(item.task_id for item in child_lowered.status_callback_tasks if item.parent_task_id == task_id)
            for child_index, child in enumerate(task.get("FailedTaskList") or []):
                child_lowered = self._lower_status_callback_task_tree(
                    child,
                    relative=relative,
                    map_name=map_name,
                    modifier_name=modifier_name,
                    callback_id=callback_id,
                    event=event,
                    callback_index=callback_index,
                    task_index=child_index,
                    task_path=f"{task_path}.FailedTaskList[{child_index}]",
                    branch="failed",
                    parent_task_id=task_id,
                    queue_priority_lookup=queue_priority_lookup,
                )
                lowered.merge(child_lowered)
                failed_ids.extend(item.task_id for item in child_lowered.status_callback_tasks if item.parent_task_id == task_id)
            coverage_status, blocked_reason = _predicate_task_status(condition)
            lowered.status_callback_tasks.insert(
                0,
                StatusCallbackTaskIR(
                    task_id=task_id,
                    callback_id=callback_id,
                    modifier_name=modifier_name,
                    event=event,
                    task_index=task_index,
                    task_path=task_path,
                    branch=branch,
                    opcode=opcode,
                    condition_id=condition.condition_id if condition else "",
                    parent_task_id=parent_task_id,
                    child_task_ids=tuple(success_ids + failed_ids),
                    success_task_ids=tuple(success_ids),
                    failed_task_ids=tuple(failed_ids),
                    source=source,
                    coverage_status=coverage_status,
                    blocked_reason=blocked_reason,
                )
            )
            return lowered

        retarget_condition = self._lower_condition(task.get("Predicate"), source, task_index) if opcode == "Retarget" else None
        if retarget_condition:
            lowered.conditions.append(retarget_condition)

        effect_id = f"effect:{relative}:{modifier_name}:{callback_index}:{branch}:{task_index}:{opcode}"
        child_task_ids: list[str] = []
        success_task_ids: list[str] = []
        failed_task_ids: list[str] = []
        for child_index, child in enumerate(task.get("TaskList") or []):
            child_lowered = self._lower_status_callback_task_tree(
                child,
                relative=relative,
                map_name=map_name,
                modifier_name=modifier_name,
                callback_id=callback_id,
                event=event,
                callback_index=callback_index,
                task_index=child_index,
                task_path=f"{task_path}.TaskList[{child_index}]",
                branch=f"{branch}:task_list",
                parent_task_id=task_id,
                queue_priority_lookup=queue_priority_lookup,
            )
            lowered.merge(child_lowered)
            child_task_ids.extend(item.task_id for item in child_lowered.status_callback_tasks if item.parent_task_id == task_id)
        for child_index, child in enumerate(task.get("SuccessTaskList") or []):
            child_lowered = self._lower_status_callback_task_tree(
                child,
                relative=relative,
                map_name=map_name,
                modifier_name=modifier_name,
                callback_id=callback_id,
                event=event,
                callback_index=callback_index,
                task_index=child_index,
                task_path=f"{task_path}.SuccessTaskList[{child_index}]",
                branch="success",
                parent_task_id=task_id,
                queue_priority_lookup=queue_priority_lookup,
            )
            lowered.merge(child_lowered)
            child_ids = [item.task_id for item in child_lowered.status_callback_tasks if item.parent_task_id == task_id]
            child_task_ids.extend(child_ids)
            success_task_ids.extend(child_ids)
        for child_index, child in enumerate(task.get("FailedTaskList") or []):
            child_lowered = self._lower_status_callback_task_tree(
                child,
                relative=relative,
                map_name=map_name,
                modifier_name=modifier_name,
                callback_id=callback_id,
                event=event,
                callback_index=callback_index,
                task_index=child_index,
                task_path=f"{task_path}.FailedTaskList[{child_index}]",
                branch="failed",
                parent_task_id=task_id,
                queue_priority_lookup=queue_priority_lookup,
            )
            lowered.merge(child_lowered)
            child_ids = [item.task_id for item in child_lowered.status_callback_tasks if item.parent_task_id == task_id]
            child_task_ids.extend(child_ids)
            failed_task_ids.extend(child_ids)
        if opcode == "Retarget":
            coverage_status, blocked_reason = _retarget_task_status(retarget_condition, child_task_ids)
        else:
            coverage_status, blocked_reason = _status_callback_task_admission(event, opcode, task)
        source_admitted = (
            _queue_intent_source_admitted(relative)
            if opcode in QUEUE_INTENT_OPCODES
            else _status_callback_task_source_admitted(relative, event, opcode)
        )
        if coverage_status == "executable" and not source_admitted:
            coverage_status = "blocked"
            blocked_reason = "status_callback_source_mode_not_admitted"
        lowered.status_callback_tasks.append(
            StatusCallbackTaskIR(
                task_id=task_id,
                callback_id=callback_id,
                modifier_name=modifier_name,
                event=event,
                task_index=task_index,
                task_path=task_path,
                branch=branch,
                opcode=opcode,
                effect_id="" if opcode == "Retarget" else effect_id,
                condition_id=retarget_condition.condition_id if retarget_condition else "",
                parent_task_id=parent_task_id,
                child_task_ids=tuple(child_task_ids),
                success_task_ids=tuple(success_task_ids),
                failed_task_ids=tuple(failed_task_ids),
                source=source,
                coverage_status=coverage_status,
                blocked_reason=blocked_reason,
            )
        )
        if opcode not in QUEUE_INTENT_OPCODES and opcode not in {
            "DamageByAttackProperty",
            "ModifyActionDelay",
            "SetActionDelay",
            "Retarget",
            "ModifyDamageData",
        }:
            payload = _effect_payload(task, opcode, modifier_name)
            payload, task_target_expressions = _attach_target_expressions_to_effect_payload(
                payload,
                task,
                effect_id=effect_id,
                source=source,
            )
            lowered.target_expressions.extend(task_target_expressions)
            effect_status = _effect_coverage_status(opcode, payload)
            lowered.effects.append(
                EffectIR(
                    effect_id=effect_id,
                    opcode=opcode,
                    payload=payload,
                    source=source,
                    coverage_status=effect_status,
                )
            )
            lowered.formulas.extend(self._extract_formulas(task, source, effect_id))
            lowered.formulas.extend(_damage_family_evidence(task, opcode, source, effect_id))
        if opcode == "DamageByAttackProperty":
            emission = _status_damage_emission_from_task(
                callback_id=callback_id,
                task_id=task_id,
                modifier_name=modifier_name,
                event=event,
                task=task,
                source=source,
            )
            if emission is not None:
                lowered.status_damage_emissions.append(emission)
        if opcode == "ModifyDamageData":
            lowered.damage_modifiers.append(
                _damage_modifier_from_task(
                    callback_id=callback_id,
                    task_id=task_id,
                    modifier_name=modifier_name,
                    event=event,
                    task=task,
                    source=source,
                )
            )
        if opcode in {"ModifyActionDelay", "SetActionDelay"}:
            lowered.action_delay_emissions.append(
                _action_delay_emission_from_task(
                    callback_id=callback_id,
                    task_id=task_id,
                    modifier_name=modifier_name,
                    event=event,
                    opcode=opcode,
                    task=task,
                    source=source,
                )
            )
        if opcode in QUEUE_INTENT_OPCODES:
            lowered.queue_intents.append(
                _queue_intent_from_task(
                    callback_id=callback_id,
                    task_id=task_id,
                    event=event,
                    opcode=opcode,
                    task=task,
                    source=source,
                    queue_priority_lookup=queue_priority_lookup,
                )
            )
        return lowered

    def _lower_task(
        self,
        task: Any,
        relative: str,
        map_name: str,
        modifier_name: str,
        callback_index: int,
        task_index: int,
        branch: str,
    ) -> "_LoweredAbility":
        lowered = _LoweredAbility()
        if not isinstance(task, dict):
            return lowered
        opcode = _short_gamecore_type(task.get("$type"))
        source = IRSource(
            source_path=relative,
            raw_type=map_name,
            raw_id=modifier_name,
            evidence={"callback_index": callback_index, "task_index": task_index, "branch": branch},
        )
        self_expression = _target_expression_from_raw(
            task,
            field_name="$self",
            expression_id=f"target_expression:{relative}:{modifier_name}:{callback_index}:{branch}:{task_index}:{opcode}:self",
            source=source,
        )
        if self_expression is not None:
            lowered.target_expressions.append(self_expression)
        if opcode == "PredicateTaskList":
            predicate = task.get("Predicate")
            condition = self._lower_condition(predicate, source, task_index)
            if condition:
                lowered.conditions.append(condition)
            for child_index, child in enumerate(task.get("SuccessTaskList") or []):
                child_lowered = self._lower_task(
                    child,
                    relative,
                    map_name,
                    modifier_name,
                    callback_index,
                    child_index,
                    branch="success",
                )
                lowered.merge(child_lowered)
            for child_index, child in enumerate(task.get("FailedTaskList") or []):
                child_lowered = self._lower_task(
                    child,
                    relative,
                    map_name,
                    modifier_name,
                    callback_index,
                    child_index,
                    branch="failed",
                )
                lowered.merge(child_lowered)
            return lowered

        effect_id = f"effect:{relative}:{modifier_name}:{callback_index}:{branch}:{task_index}:{opcode}"
        payload = _effect_payload(task, opcode, modifier_name)
        payload, task_target_expressions = _attach_target_expressions_to_effect_payload(
            payload,
            task,
            effect_id=effect_id,
            source=source,
        )
        lowered.target_expressions.extend(task_target_expressions)
        coverage_status = _effect_coverage_status(opcode, payload)
        lowered.effects.append(
            EffectIR(
                effect_id=effect_id,
                opcode=opcode,
                payload=payload,
                source=source,
                coverage_status=coverage_status,
            )
        )
        lowered.formulas.extend(self._extract_formulas(task, source, effect_id))
        lowered.formulas.extend(_damage_family_evidence(task, opcode, source, effect_id))
        return lowered

    def _lower_condition(self, predicate: Any, source: IRSource, task_index: int) -> ConditionIR | None:
        if not isinstance(predicate, dict):
            return None
        opcode = _short_gamecore_type(predicate.get("$type"))
        payload = _compact_payload(predicate)
        status = "executable" if _condition_payload_executable(opcode, payload) else classify_opcode(opcode)
        condition_path = str(source.evidence.get("task_path", task_index)) if isinstance(source.evidence, dict) else str(task_index)
        return ConditionIR(
            condition_id=f"condition:{source.source_path}:{source.raw_id}:{source.evidence.get('callback_index')}:{condition_path}:{opcode}",
            opcode=opcode,
            payload=payload,
            source=source,
            coverage_status=status,
        )

    def _extract_formulas(self, task: Any, source: IRSource, parent_id: str) -> list[FormulaIR]:
        formulas: list[FormulaIR] = []
        for index, expression in enumerate(_iter_postfix_expr(task)):
            formulas.append(
                FormulaIR(
                    formula_id=f"formula:{parent_id}:{index}",
                    kind="postfix_expr",
                    expression=_json_safe(expression),
                    source=source,
                    coverage_status="audit_only",
                )
            )
        for index, fixed_value in enumerate(_iter_fixed_values(task)):
            formulas.append(
                FormulaIR(
                    formula_id=f"formula:{parent_id}:fixed:{index}",
                    kind="fixed_value",
                    expression=_json_safe(fixed_value),
                    source=source,
                    coverage_status="executable",
                )
            )
        return formulas

    def _lower_elation_mechanics(self) -> list[FormulaIR]:
        formulas: list[FormulaIR] = []
        for relative_path in ELATION_MECHANIC_FILES:
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for index, (raw_path, key, value) in enumerate(_iter_elation_values(data)):
                mechanic = "elation_damage" if key == "ElationDamageAddedRatio" else "elation_runtime"
                coverage_status = "blocked" if key == "ElationDamageAddedRatio" else "discovered_only"
                source = IRSource(
                    source_path=relative_path,
                    raw_type=Path(relative_path).stem,
                    raw_id=raw_path,
                    evidence={
                        "raw_path": raw_path,
                        "key": key,
                        "mechanic": mechanic,
                        "damage_formula_family": "elation",
                    },
                )
                blocked_reason = (
                    "Elation damage property is discovered in TBGD, "
                    "but the complete 4.0 damage formula is not executable in v0_207"
                )
                formulas.append(
                    FormulaIR(
                        formula_id=f"mechanic:{mechanic}:{relative_path}:{index}",
                        kind="mechanic_property",
                        expression={
                            "mechanic": mechanic,
                            "property": key,
                            "raw_path": raw_path,
                            "value": _json_safe(value),
                            "damage_formula_family": "elation",
                            "source_mode": "mainline",
                            "runtime_status": coverage_status,
                            "blocked_reason": blocked_reason
                            if key == "ElationDamageAddedRatio"
                            else "Elation runtime property discovered for taxonomy evidence",
                        },
                        source=source,
                        coverage_status=coverage_status,
                    )
                )
        return formulas

    def _lower_damage_behavior_templates(self) -> list[FormulaIR]:
        path = self.tbgd_root / DAMAGE_BEHAVIOR_TEMPLATE_FILE
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        config = data.get("ConfigList") if isinstance(data, dict) else None
        if not isinstance(config, dict):
            return []
        formulas: list[FormulaIR] = []
        for name, payload in sorted(config.items()):
            family = _damage_behavior_family(str(name))
            if family == "unknown":
                continue
            source = IRSource(
                source_path=DAMAGE_BEHAVIOR_TEMPLATE_FILE,
                raw_type=Path(DAMAGE_BEHAVIOR_TEMPLATE_FILE).stem,
                raw_id=str(name),
                evidence={
                    "template_name": str(name),
                    "damage_formula_family": family,
                    "bypasses_normal_multipliers": family in {"true_damage", "hp_loss"},
                },
            )
            formulas.append(
                FormulaIR(
                    formula_id=f"mechanic:{family}:{DAMAGE_BEHAVIOR_TEMPLATE_FILE}:{name}",
                    kind="mechanic_property",
                    expression={
                        "mechanic": f"{family}_damage",
                        "property": str(name),
                        "value": _json_safe(payload),
                        "damage_formula_family": family,
                        "source_mode": "mainline",
                        "runtime_status": "executable",
                        "bypasses_normal_multipliers": True,
                    },
                    source=source,
                    coverage_status="lowered",
                )
            )
        return formulas

    def _modifier_maps(self, data: Any) -> list[tuple[str, str, dict[str, Any]]]:
        maps: list[tuple[str, str, dict[str, Any]]] = []
        if not isinstance(data, dict):
            return maps
        ability_list = data.get("AbilityList")
        if isinstance(ability_list, list):
            for ability_index, ability in enumerate(ability_list):
                if not isinstance(ability, dict):
                    continue
                modifiers = ability.get("Modifiers")
                if isinstance(modifiers, dict):
                    maps.extend(("Modifiers", name, value) for name, value in modifiers.items() if isinstance(value, dict))
        modifier_map = data.get("ModifierMap")
        if isinstance(modifier_map, dict):
            maps.extend(("ModifierMap", name, value) for name, value in modifier_map.items() if isinstance(value, dict))
        global_modifiers = data.get("GlobalModifiers")
        if isinstance(global_modifiers, dict):
            maps.extend(("GlobalModifiers", name, value) for name, value in global_modifiers.items() if isinstance(value, dict))
        return maps


@dataclass
class _LoweredAbility:
    entities: list[RuleEntity] = field(default_factory=list)
    ability_tasks: list[AbilityTaskIR] = field(default_factory=list)
    status_callbacks: list[StatusCallbackIR] = field(default_factory=list)
    status_callback_tasks: list[StatusCallbackTaskIR] = field(default_factory=list)
    status_damage_emissions: list[StatusDamageEmissionIR] = field(default_factory=list)
    damage_modifiers: list[DamageModifierIR] = field(default_factory=list)
    action_delay_emissions: list[ActionDelayEmissionIR] = field(default_factory=list)
    queue_intents: list[QueueIntentIR] = field(default_factory=list)
    skill_continuations: list[SkillContinuationIR] = field(default_factory=list)
    triggers: list[TriggerIR] = field(default_factory=list)
    effects: list[EffectIR] = field(default_factory=list)
    conditions: list[ConditionIR] = field(default_factory=list)
    formulas: list[FormulaIR] = field(default_factory=list)
    target_expressions: list[TargetExpressionIR] = field(default_factory=list)

    def merge(self, other: "_LoweredAbility") -> None:
        self.entities.extend(other.entities)
        self.ability_tasks.extend(other.ability_tasks)
        self.status_callbacks.extend(other.status_callbacks)
        self.status_callback_tasks.extend(other.status_callback_tasks)
        self.status_damage_emissions.extend(other.status_damage_emissions)
        self.damage_modifiers.extend(other.damage_modifiers)
        self.action_delay_emissions.extend(other.action_delay_emissions)
        self.queue_intents.extend(other.queue_intents)
        self.skill_continuations.extend(other.skill_continuations)
        self.triggers.extend(other.triggers)
        self.effects.extend(other.effects)
        self.conditions.extend(other.conditions)
        self.formulas.extend(other.formulas)
        self.target_expressions.extend(other.target_expressions)


@dataclass(frozen=True)
class _StandaloneActionRef:
    action_id: str
    level: int


def _read_json_file(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _enum_values(data: dict[str, Any], enum_name: str) -> dict[str, Any]:
    enum = data.get(enum_name)
    values = enum.get("Values") if isinstance(enum, dict) else None
    return dict(values) if isinstance(values, dict) else {}


def _short_gamecore_type(raw_type: Any) -> str:
    if not isinstance(raw_type, str):
        return "Unknown"
    return raw_type.removeprefix("RPG.GameCore.")


def _entity_raw_id(entity_type: str, id_key: str, row: dict[str, Any]) -> str:
    if entity_type == "avatar_promotion":
        promotion = row.get("Promotion", 0)
        return f"{row[id_key]}:{promotion}"
    return str(row[id_key])


def _stage_id(row: dict[str, Any]) -> str:
    value = row.get("StageID")
    if isinstance(value, bool) or value is None:
        return ""
    return str(value)


def _stage_config_wave_count(value: Any) -> int:
    if not isinstance(value, list):
        return 0
    for item in value:
        if not isinstance(item, dict):
            continue
        key = item.get("BFLIFKBEOPJ")
        raw_value = item.get("MNDFOPKBHKP")
        if key != "_Wave":
            continue
        try:
            return int(str(raw_value))
        except (TypeError, ValueError):
            return 0
    return 0


def _stage_monster_items(wave: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    items: list[tuple[int, str, Any]] = []
    for key, value in wave.items():
        if not isinstance(key, str) or not key.startswith("Monster"):
            continue
        items.append((_stage_monster_position(key), key, value))
    return tuple((key, value) for _, key, value in sorted(items, key=lambda item: (item[0], item[1])))


def _stage_monster_position(key: str) -> int:
    suffix = key.removeprefix("Monster")
    try:
        return int(suffix)
    except ValueError:
        return 9999


def _stage_monster_raw_id(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return text


STATUS_EVENT_RUNTIME_SOURCES: dict[str, tuple[str, ...]] = {
    "OnListenAllowAction": ("turn.begin",),
    "OnListenTurnEnd": ("turn.end",),
    "OnBeforeSkillUse": ("action.window.before_skill_use",),
    "OnBeforeAttack": ("action.window.before_attack",),
    "OnAfterAttack": ("action.window.after_attack", "action.after_attack"),
    "OnAfterSkillUse": ("action.window.after_skill_use",),
    "OnActionEnd": ("action.end",),
    "OnBeforeInsertActionPrepare": ("queue.action.before",),
    "OnInsertActionStart": ("queue.action.before",),
    "OnInsertActionFinish": ("queue.action.after",),
    "OnListenInsertAbilityFinish": ("queue.action.after",),
    "OnBeforeHit": ("damage.before_hit",),
    "OnBeforeHitAll": ("damage.before_hit",),
    "OnAfterHit": ("damage.hit",),
    "OnAfterHitAll": ("damage.hit",),
    "OnAfterBeingAttacked": ("damage.hit",),
    "OnBeingHit": ("damage.hit",),
    "OnHit": ("damage.hit", "toughness.hit"),
    "OnHPChange": ("hp.change", "heal.after"),
    "OnListenHPChange": ("hp.change", "heal.after"),
    "OnAfterBeingHeal": ("heal.after",),
    "OnAfterDealHeal": ("heal.after",),
    "OnHPOverflow": ("heal.after",),
    "OnShieldChange": ("shield.change",),
    "OnListenShieldChange": ("shield.change",),
    "OnListenInitShield": ("shield.change",),
    "OnSPChange": ("sp.change",),
    "OnBeforeEnergyPointChange": ("energy.before_change",),
    "OnEnergyPointChange": ("energy.change",),
    "OnBeforeBeingStanceDamage": ("toughness.before_hit",),
    "OnBeingStanceDamage": ("toughness.hit",),
    "OnTriggerBreak": ("break.triggered",),
    "OnBeingBreak": ("break.triggered",),
    "OnListenBreak": ("break.triggered",),
    "OnTriggerDeath": ("unit.defeated",),
    "OnListenCharacterDie": ("unit.defeated",),
    "OnTriggerDeathrattle": ("unit.defeated",),
    "OnBeforeDying": ("unit.before_dying",),
    "OnCreate": ("status.lifecycle",),
    "OnDestroy": ("status.lifecycle",),
    "OnPhase1": ("status.lifecycle",),
    "OnStack": ("status.lifecycle",),
    "OnModifierAdd": ("status.lifecycle",),
    "OnModifierRemove": ("status.lifecycle",),
    "OnAddModifierSuc": ("status.lifecycle",),
    "OnListenModifierAdd": ("status.lifecycle",),
    "OnListenModifierRemove": ("status.lifecycle",),
    "OnModifierOnStack": ("status.lifecycle",),
    "OnListenModifierOnStack": ("status.lifecycle",),
    "OnModifierDotAdd": ("status.lifecycle",),
    "OnActionDelayEffect": ("action_delay.changed",),
    "OnActionDelayEffectAll": ("action_delay.changed",),
    "OnListenGlobalActionDelayChanged": ("action_delay.changed",),
    "OnEnterBattle": ("battle.setup",),
    "OnWaveMonster": ("wave.monster",),
}


STATUS_EVENT_BLOCKED_DEPENDENCIES: dict[str, str] = {
    "OnCustomEvent": "event_source_missing:custom_event_source_not_admitted",
}


def _lower_status_event_families(
    status_callbacks: list[StatusCallbackIR],
    status_callback_tasks: list[StatusCallbackTaskIR],
) -> list[StatusEventFamilyIR]:
    callbacks_by_event: dict[str, list[StatusCallbackIR]] = {}
    for callback in status_callbacks:
        callbacks_by_event.setdefault(callback.event, []).append(callback)
    tasks_by_callback: dict[str, list[StatusCallbackTaskIR]] = {}
    for task in status_callback_tasks:
        tasks_by_callback.setdefault(task.callback_id, []).append(task)
    families: list[StatusEventFamilyIR] = []
    for event, callbacks in sorted(callbacks_by_event.items()):
        tasks = [task for callback in callbacks for task in tasks_by_callback.get(callback.callback_id, ())]
        runtime_sources = STATUS_EVENT_RUNTIME_SOURCES.get(event, ())
        blocked_dependency = STATUS_EVENT_BLOCKED_DEPENDENCIES.get(event, "")
        if not runtime_sources and not blocked_dependency:
            blocked_dependency = f"event_source_missing:{event}"
        coverage_status = "blocked" if blocked_dependency else "executable"
        families.append(
            StatusEventFamilyIR(
                status_event_family_id=f"status_event_family:{_safe_id(event)}",
                callback_event=event,
                event_family=_status_event_family_name(event),
                default_scope_kind=_status_callback_scope_kind(event),
                runtime_event_sources=runtime_sources,
                source_basis="StatusCallbackIR.event",
                source=IRSource(
                    source_path="CanonicalIR/status_callbacks",
                    raw_type="StatusCallbackEventFamily",
                    raw_id=event,
                    evidence={
                        "callback_event": event,
                        "callback_count": len(callbacks),
                        "runtime_event_sources": list(runtime_sources),
                        "blocked_dependency": blocked_dependency,
                        "source_basis": "lowered from StatusCallbackIR.event values produced by TBGD ability lowering",
                    },
                ),
                callback_count=len(callbacks),
                executable_callback_count=sum(
                    1
                    for callback in callbacks
                    if callback.coverage_status == "executable" and callback.admission_status == "executable"
                ),
                blocked_callback_count=sum(
                    1
                    for callback in callbacks
                    if callback.coverage_status != "executable" or callback.admission_status != "executable"
                ),
                task_count=len(tasks),
                task_opcode_counts=dict(Counter(task.opcode for task in tasks)),
                source_mode_counts=dict(Counter(callback.source_mode for callback in callbacks)),
                coverage_status=coverage_status,
                blocked_reason=blocked_dependency,
                admission_status=coverage_status,
                blocking_dependency=blocked_dependency,
            )
        )
    return families


def _status_event_blocked_reasons(status_event_families: list[StatusEventFamilyIR]) -> dict[str, str]:
    return {
        family.callback_event: family.blocking_dependency or family.blocked_reason
        for family in status_event_families
        if family.coverage_status != "executable" or family.admission_status != "executable"
    }


def _block_status_callbacks_by_event_family(
    status_callbacks: list[StatusCallbackIR],
    blocked_reasons_by_event: dict[str, str],
) -> list[StatusCallbackIR]:
    blocked_callbacks: list[StatusCallbackIR] = []
    for callback in status_callbacks:
        reason = blocked_reasons_by_event.get(callback.event)
        if not reason:
            blocked_callbacks.append(callback)
            continue
        blocked_callbacks.append(
            replace(
                callback,
                coverage_status="blocked",
                admission_status="blocked",
                blocked_reason=callback.blocked_reason or reason,
                blocking_dependency=callback.blocking_dependency or reason,
            )
        )
    return blocked_callbacks


def _block_status_callback_tasks_by_callback(
    status_callback_tasks: list[StatusCallbackTaskIR],
    blocked_reasons_by_callback: dict[str, str],
) -> list[StatusCallbackTaskIR]:
    blocked_tasks: list[StatusCallbackTaskIR] = []
    for task in status_callback_tasks:
        reason = blocked_reasons_by_callback.get(task.callback_id)
        if not reason:
            blocked_tasks.append(task)
            continue
        blocked_tasks.append(
            replace(
                task,
                coverage_status="blocked",
                blocked_reason=task.blocked_reason or reason,
            )
        )
    return blocked_tasks


def _block_status_callback_derived_by_callback(items: list[Any], blocked_reasons_by_callback: dict[str, str]) -> list[Any]:
    blocked_items: list[Any] = []
    for item in items:
        reason = blocked_reasons_by_callback.get(item.callback_id)
        if not reason:
            blocked_items.append(item)
            continue
        blocked_items.append(
            replace(
                item,
                coverage_status="blocked",
                blocked_reason=item.blocked_reason or reason,
            )
        )
    return blocked_items


def _status_event_family_name(event: str) -> str:
    if event in {"OnCustomEvent"}:
        return "custom_event"
    if event in {"OnWaveMonster"}:
        return "wave"
    if event in {
        "OnCreate",
        "OnDestroy",
        "OnStack",
        "OnModifierAdd",
        "OnModifierRemove",
        "OnPhase1",
        "OnAddModifierSuc",
        "OnListenModifierAdd",
        "OnListenModifierRemove",
        "OnModifierOnStack",
        "OnListenModifierOnStack",
        "OnModifierDotAdd",
    }:
        return "status_lifecycle"
    if "Hit" in event or "Attacked" in event:
        return "hit"
    if "Break" in event:
        return "break"
    if "Death" in event or "Die" in event or "Dying" in event:
        return "death"
    if "Insert" in event or "Action" in event:
        return "action_or_queue"
    if "Turn" in event or event == "OnListenAllowAction":
        return "turn"
    if "HP" in event or "Heal" in event or "Shield" in event or "SP" in event or "Energy" in event:
        return "resource"
    if "Rogue" in event or "Elation" in event or "Evolve" in event or "Chess" in event:
        return "special_mode"
    return "unadmitted"


def _character_runtime_mechanism_slots(
    *,
    character_data_cards: list[CharacterDataCardIR],
    skill_formula_bindings: list[SkillFormulaBindingIR],
    action_ability_bindings: list[ActionAbilityBindingIR],
    status_callbacks: list[StatusCallbackIR],
    damage_modifiers: list[DamageModifierIR],
    queue_intents: list[QueueIntentIR],
    queue_windows: list[QueueWindowIR],
    extra_action_policies: list[ExtraActionPolicyIR],
    skill_continuations: list[SkillContinuationIR],
) -> list[CharacterMechanismSlotIR]:
    valid_card_ids = {card.card_id for card in character_data_cards}
    action_to_card: dict[tuple[str, int], str] = {}
    for binding in skill_formula_bindings:
        if binding.character_data_card_id in valid_card_ids:
            action_to_card[(binding.action_id, binding.level)] = binding.character_data_card_id
    ability_file_to_card: dict[str, str] = {}
    for binding in action_ability_bindings:
        card_id = action_to_card.get((binding.action_id, binding.level))
        if not card_id:
            continue
        ability_file = _ability_file_from_action_binding(binding)
        if ability_file:
            ability_file_to_card[ability_file] = card_id
    callback_to_card: dict[str, str] = {}
    slots: list[CharacterMechanismSlotIR] = []
    for callback in status_callbacks:
        card_id = ability_file_to_card.get(callback.source.source_path, "")
        if not card_id:
            continue
        callback_to_card[callback.callback_id] = card_id
        slots.append(
            CharacterMechanismSlotIR(
                mechanism_slot_id=f"character_mechanism_slot:{card_id}:status_callback:{callback.callback_id}",
                character_data_card_id=card_id,
                mechanism_kind="status_callback",
                runtime_system="event_dispatch_system",
                linked_ir_ids={
                    "status_callback_id": callback.callback_id,
                    "modifier_name": callback.modifier_name,
                    "event": callback.event,
                    "task_ids": list(callback.task_ids),
                },
                activation={
                    "kind": "status_listener",
                    "event": callback.event,
                    "scope_kind": callback.scope_kind,
                    "source_mode": callback.source_mode,
                },
                semantics={
                    "admission_status": callback.admission_status,
                    "blocking_dependency": callback.blocking_dependency,
                    "blocked_reason": callback.blocked_reason,
                },
                source=callback.source,
                coverage_status=callback.coverage_status,
                blocked_reason=callback.blocked_reason,
            )
        )
    for modifier in damage_modifiers:
        card_id = callback_to_card.get(modifier.callback_id) or ability_file_to_card.get(modifier.source.source_path, "")
        if not card_id:
            continue
        slots.append(
            CharacterMechanismSlotIR(
                mechanism_slot_id=f"character_mechanism_slot:{card_id}:damage_modifier:{modifier.damage_modifier_id}",
                character_data_card_id=card_id,
                mechanism_kind="damage_modifier",
                runtime_system="damage_formula",
                linked_ir_ids={
                    "damage_modifier_id": modifier.damage_modifier_id,
                    "callback_id": modifier.callback_id,
                    "source_task_id": modifier.source_task_id,
                    "modifier_name": modifier.modifier_name,
                },
                activation={
                    "kind": "status_callback_task",
                    "event": modifier.event,
                    "target_alias": modifier.target_alias,
                },
                semantics={
                    "modifier_terms": list(modifier.modifier_terms),
                },
                source=modifier.source,
                coverage_status=modifier.coverage_status,
                blocked_reason=modifier.blocked_reason,
            )
        )
    intent_to_card: dict[str, str] = {}
    window_by_intent = {window.queue_intent_id: window for window in queue_windows}
    for intent in queue_intents:
        card_id = callback_to_card.get(intent.callback_id) or ability_file_to_card.get(intent.source.source_path, "")
        if not card_id:
            continue
        intent_to_card[intent.queue_intent_id] = card_id
        window = window_by_intent.get(intent.queue_intent_id)
        slots.append(
            CharacterMechanismSlotIR(
                mechanism_slot_id=f"character_mechanism_slot:{card_id}:queue_intent:{intent.queue_intent_id}",
                character_data_card_id=card_id,
                mechanism_kind="queue_intent",
                runtime_system="queue_system",
                linked_ir_ids={
                    "queue_intent_id": intent.queue_intent_id,
                    "callback_id": intent.callback_id,
                    "source_task_id": intent.source_task_id,
                    "queue_window_id": window.queue_window_id if window else "",
                },
                activation={
                    "kind": "callback_task",
                    "opcode": intent.opcode,
                    "queue_kind": intent.queue_kind,
                },
                semantics={
                    "action_ref_or_ability_name": intent.action_ref_or_ability_name,
                    "skill_index_expr": intent.skill_index_expr,
                    "actor_target_alias": intent.actor_target_alias,
                    "ability_target_alias": intent.ability_target_alias,
                    "window_family": window.window_family if window else "",
                },
                source=intent.source,
                coverage_status=intent.coverage_status,
                blocked_reason=intent.blocked_reason,
            )
        )
    for policy in extra_action_policies:
        card_id = intent_to_card.get(policy.queue_intent_id)
        if not card_id:
            continue
        slots.append(
            CharacterMechanismSlotIR(
                mechanism_slot_id=f"character_mechanism_slot:{card_id}:extra_action_policy:{policy.extra_action_policy_id}",
                character_data_card_id=card_id,
                mechanism_kind="extra_action_policy",
                runtime_system="scheduler",
                linked_ir_ids={
                    "extra_action_policy_id": policy.extra_action_policy_id,
                    "queue_intent_id": policy.queue_intent_id,
                    "queue_window_id": policy.queue_window_id,
                    "lifecycle_policy_id": policy.lifecycle_policy_id,
                },
                activation={
                    "kind": "queue_window",
                    "source_kind": policy.source_kind,
                },
                semantics={
                    "action_selection_kind": policy.action_selection_kind,
                    "allowed_action_kinds": list(policy.allowed_action_kinds),
                    "fixed_action_ref": policy.fixed_action_ref,
                    "source_basis": policy.source_basis,
                },
                source=policy.source,
                coverage_status=policy.coverage_status,
                blocked_reason=policy.blocked_reason,
            )
        )
    for continuation in skill_continuations:
        card_id = action_to_card.get((continuation.action_id, continuation.level))
        if not card_id:
            continue
        slots.append(
            CharacterMechanismSlotIR(
                mechanism_slot_id=f"character_mechanism_slot:{card_id}:skill_continuation:{continuation.continuation_id}",
                character_data_card_id=card_id,
                mechanism_kind="skill_continuation",
                runtime_system="skill_continuation_runner",
                linked_ir_ids={
                    "skill_continuation_id": continuation.continuation_id,
                    "source_task_id": continuation.source_task_id,
                    "action_id": continuation.action_id,
                    "level": continuation.level,
                },
                activation={
                    "kind": "ability_task",
                    "opcode": continuation.opcode,
                },
                semantics={
                    "continuation_kind": continuation.continuation_kind,
                    "fixed_skill_type": continuation.fixed_skill_type,
                    "child_skill_index_expr": continuation.child_skill_index_expr,
                },
                source=continuation.source,
                coverage_status=continuation.coverage_status,
                blocked_reason=continuation.blocked_reason,
            )
        )
    return _dedupe_character_mechanism_slots(slots)


def _admit_trace_startup_ability_slots(
    slots: list[CharacterMechanismSlotIR],
    *,
    standalone_graphs: list[StandaloneAbilityGraphIR],
    ability_tasks: list[AbilityTaskIR],
    effects: list[EffectIR],
) -> list[CharacterMechanismSlotIR]:
    graphs_by_name: dict[str, list[StandaloneAbilityGraphIR]] = {}
    for graph in standalone_graphs:
        graphs_by_name.setdefault(graph.ability_name, []).append(graph)
    tasks_by_phase: dict[str, list[AbilityTaskIR]] = {}
    for task in ability_tasks:
        tasks_by_phase.setdefault(task.phase_id, []).append(task)
    effects_by_id = {effect.effect_id: effect for effect in effects}
    admitted: list[CharacterMechanismSlotIR] = []
    for slot in slots:
        if slot.mechanism_kind != "trace_ability_hook":
            admitted.append(slot)
            continue
        admitted.append(
            _admit_trace_startup_ability_slot(
                slot,
                graphs_by_name=graphs_by_name,
                tasks_by_phase=tasks_by_phase,
                effects_by_id=effects_by_id,
            )
        )
    return admitted


def _admit_trace_startup_ability_slot(
    slot: CharacterMechanismSlotIR,
    *,
    graphs_by_name: dict[str, list[StandaloneAbilityGraphIR]],
    tasks_by_phase: dict[str, list[AbilityTaskIR]],
    effects_by_id: dict[str, EffectIR],
) -> CharacterMechanismSlotIR:
    evidence = slot.source.evidence if isinstance(slot.source.evidence, dict) else {}
    if evidence.get("enhanced_id") is None:
        return slot
    semantics = dict(slot.semantics)
    ability_name = str(semantics.get("ability_name") or slot.linked_ir_ids.get("ability_name") or "")
    if not ability_name:
        return _trace_startup_blocked_slot(slot, "trace_ability_name_missing", semantics)
    graph_candidates = tuple(sorted(graphs_by_name.get(ability_name, ()), key=lambda item: item.standalone_ability_graph_id))
    executable_graphs = tuple(graph for graph in graph_candidates if graph.coverage_status == "executable")
    if len(executable_graphs) != 1:
        reason = "trace_startup_graph_missing_or_ambiguous"
        if graph_candidates and not executable_graphs:
            reason = "trace_startup_graph_not_executable"
        return _trace_startup_blocked_slot(
            slot,
            reason,
            {
                **semantics,
                "startup_admission": {
                    "admission_status": "blocked",
                    "blocked_reason": reason,
                    "ability_name": ability_name,
                    "candidate_graph_ids": [graph.standalone_ability_graph_id for graph in graph_candidates],
                    "candidate_graph_statuses": [graph.coverage_status for graph in graph_candidates],
                },
            },
        )
    graph = executable_graphs[0]
    candidate_tasks = tuple(
        task
        for phase_id in graph.phase_ids
        for task in tasks_by_phase.get(phase_id, ())
        if task.callback_kind == "OnStart"
        and not task.parent_task_id
        and task.opcode == "AddModifier"
        and task.effect_id
    )
    if not candidate_tasks:
        return _trace_startup_blocked_slot(
            slot,
            "trace_startup_on_start_add_modifier_missing",
            {
                **semantics,
                "startup_admission": {
                    "admission_status": "blocked",
                    "blocked_reason": "trace_startup_on_start_add_modifier_missing",
                    "standalone_ability_graph_id": graph.standalone_ability_graph_id,
                },
            },
        )
    admitted_tasks: list[dict[str, JSONValue]] = []
    blocked_tasks: list[dict[str, JSONValue]] = []
    for task in candidate_tasks:
        effect = effects_by_id.get(task.effect_id)
        if effect is None:
            blocked_tasks.append({"task_id": task.task_id, "blocked_reason": "trace_startup_effect_missing"})
            continue
        effect_reason = _trace_startup_effect_blocked_reason(effect)
        if effect_reason:
            blocked_tasks.append(
                {
                    "task_id": task.task_id,
                    "effect_id": effect.effect_id,
                    "blocked_reason": effect_reason,
                    "effect_coverage_status": effect.coverage_status,
                }
            )
            continue
        dynamic_admission = _trace_startup_dynamic_binding_admission(effect.payload.get("standard"), semantics)
        if dynamic_admission.get("admission_status") == "blocked":
            blocked_tasks.append(
                {
                    "task_id": task.task_id,
                    "effect_id": effect.effect_id,
                    "blocked_reason": str(dynamic_admission.get("blocked_reason") or "trace_dynamic_binding_blocked"),
                    "dynamic_value_binding": dynamic_admission,
                }
            )
            continue
        admitted_tasks.append(
            {
                "task_id": task.task_id,
                "effect_id": effect.effect_id,
                "dynamic_value_binding": _json_safe(dynamic_admission),
            }
        )
    if not admitted_tasks:
        return _trace_startup_blocked_slot(
            slot,
            "trace_startup_no_admitted_on_start_add_modifier",
            {
                **semantics,
                "startup_admission": {
                    "admission_status": "blocked",
                    "blocked_reason": "trace_startup_no_admitted_on_start_add_modifier",
                    "standalone_ability_graph_id": graph.standalone_ability_graph_id,
                    "blocked_tasks": blocked_tasks,
                },
            },
        )
    return replace(
        slot,
        semantics={
            **semantics,
            "startup_admission": {
                "admission_status": "executable",
                "startup_kind": "trace_on_start_add_modifier",
                "standalone_ability_graph_id": graph.standalone_ability_graph_id,
                "admitted_tasks": admitted_tasks,
                "blocked_tasks": blocked_tasks,
            },
        },
        coverage_status="executable",
        blocked_reason="",
    )


def _trace_startup_blocked_slot(
    slot: CharacterMechanismSlotIR,
    reason: str,
    semantics: dict[str, JSONValue],
) -> CharacterMechanismSlotIR:
    return replace(
        slot,
        semantics=semantics,
        coverage_status="blocked",
        blocked_reason=reason,
    )


def _trace_startup_effect_blocked_reason(effect: EffectIR) -> str:
    if effect.opcode != "AddModifier":
        return f"trace_startup_effect_opcode_not_add_modifier:{effect.opcode}"
    if effect.coverage_status != "executable":
        return f"trace_startup_effect_not_executable:{effect.coverage_status}"
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return "trace_startup_effect_standard_payload_missing"
    modifier_name = standard.get("modifier_name")
    if not isinstance(modifier_name, str) or not modifier_name:
        return "trace_startup_effect_modifier_name_missing"
    target_alias = standard.get("target_alias")
    if target_alias not in {"Caster", "ModifierOwnerEntity"}:
        return f"trace_startup_effect_target_alias_not_admitted:{target_alias}"
    return ""


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value.is_integer():
        converted = int(value)
        return converted if converted > 0 else None
    return None


def _wave_level_policy(
    *,
    stage_id: str,
    stage_row_index: int,
    level: int | None,
    hard_level_group: int | None,
    hard_level_profile: dict[str, Any] | None,
) -> dict[str, JSONValue]:
    blocked_reasons: list[str] = []
    if level is None:
        blocked_reasons.append("stage_level_missing")
    if hard_level_group is None:
        blocked_reasons.append("stage_hard_level_group_missing")
    if level is not None and hard_level_group is not None and hard_level_profile is None:
        blocked_reasons.append("stage_hard_level_profile_missing")
    ratios: dict[str, JSONValue] = {}
    if hard_level_profile is not None:
        for field_name, raw_key in (
            ("attack", "AttackRatio"),
            ("defense", "DefenceRatio"),
            ("max_hp", "HPRatio"),
            ("speed", "SpeedRatio"),
            ("max_toughness", "StanceRatio"),
        ):
            ratio = _required_number(hard_level_profile, raw_key)
            if ratio is None or ratio <= 0:
                blocked_reasons.append(f"stage_hard_level_ratio_missing:{raw_key}")
            else:
                ratios[field_name] = ratio
    blocked_reason = ";".join(dict.fromkeys(blocked_reasons))
    return {
        "kind": "stage_level_hard_level_group",
        "admission_status": "blocked" if blocked_reason else "executable",
        "blocked_reason": blocked_reason,
        "level": level,
        "hard_level_group": hard_level_group,
        "ratios": ratios,
        "source_trace": {
            "stage": {
                "source_path": "ExcelOutput/StageConfig.json",
                "raw_type": "StageConfig",
                "raw_id": stage_id,
                "evidence": {
                    "row_index": stage_row_index,
                    "level_field": "Level",
                    "hard_level_group_field": "HardLevelGroup",
                    "level": level,
                    "hard_level_group": hard_level_group,
                },
            },
            "hard_level_profile": {
                "source_path": str((hard_level_profile or {}).get("_v8_source_path") or ""),
                "raw_type": "HardLevelGroup",
                "raw_id": f"{hard_level_group}:{level}" if hard_level_group is not None and level is not None else "",
                "evidence": {
                    "row_index": (hard_level_profile or {}).get("_v8_row_index"),
                    "ratios": ratios,
                },
            },
        },
    }


def _wave_birth_template_id(stage_id: str, wave_index: int, position: int, monster_raw_id: str) -> str:
    return f"unit_birth_template:wave:{_safe_id(stage_id)}:{_safe_id(monster_raw_id or 'empty')}"


def _summoned_monster_birth_template_id(task_id: str, entry_index: int) -> str:
    return f"unit_birth_template:summoned_monster:{_safe_id(task_id)}:{entry_index}"


def _servant_birth_template_id(servant_id: str) -> str:
    return f"unit_birth_template:servant:{_safe_id(servant_id)}"


def _lower_unit_birth_templates(
    *,
    summon_monster_intents: list[SummonMonsterIntentIR],
    servant_definitions: list[ServantDefinitionIR],
    wave_definitions: list[WaveDefinitionIR],
    combatant_profiles: list[CombatantProfileIR],
    monster_data_cards: tuple[MonsterDataCardIR, ...] | list[MonsterDataCardIR],
    timeline_rules: list[TimelineRuleIR],
) -> list[UnitBirthTemplateIR]:
    profile_by_entity = {profile.entity_id: profile for profile in combatant_profiles}
    card_by_entity = {card.entity_ref: card for card in monster_data_cards}
    timeline_rule = next((rule for rule in timeline_rules if rule.coverage_status == "executable"), None)
    templates: list[UnitBirthTemplateIR] = []
    for intent in summon_monster_intents:
        for entry in intent.entries:
            templates.append(
                _summoned_monster_birth_template(
                    intent,
                    entry,
                    profile_by_entity.get(entry.monster_entity_ref),
                    card_by_entity.get(entry.monster_entity_ref),
                    timeline_rule,
                )
            )
    for definition in servant_definitions:
        templates.append(_servant_birth_template(definition, timeline_rule))
    for definition in wave_definitions:
        for entry in definition.entries:
            templates.append(
                _wave_enemy_birth_template(
                    definition,
                    entry,
                    profile_by_entity.get(entry.monster_entity_ref),
                    card_by_entity.get(entry.monster_entity_ref),
                    timeline_rule,
                )
            )
    return list({template.birth_template_id: template for template in templates}.values())


def _summoned_monster_birth_template(
    intent: SummonMonsterIntentIR,
    entry: SummonMonsterEntryIR,
    profile: CombatantProfileIR | None,
    card: MonsterDataCardIR | None,
    timeline_rule: TimelineRuleIR | None,
) -> UnitBirthTemplateIR:
    reasons: list[str] = []
    if intent.coverage_status != "executable":
        reasons.append(intent.blocked_reason or f"summon_monster_intent_not_executable:{intent.coverage_status}")
    if entry.coverage_status != "executable":
        reasons.append(entry.blocked_reason or f"summon_monster_entry_not_executable:{entry.coverage_status}")
    if profile is None or profile.coverage_status != "executable":
        reasons.append("summon_monster_combatant_profile_missing_or_blocked")
    if card is None:
        reasons.append("summon_monster_data_card_missing")
    if timeline_rule is None:
        reasons.append("summon_monster_timeline_rule_missing")
    if entry.level_policy.get("admission_status") != "executable" or (
        profile is not None and entry.level_policy.get("profile_id") != profile.profile_id
    ):
        reasons.append("summon_monster_level_policy_source_blocked")
    delay_ratio = _strict_json_number(intent.delay_policy.get("value"))
    if intent.delay_policy.get("admission_status") != "executable" or delay_ratio is None or delay_ratio < 0:
        reasons.append("summon_monster_delay_policy_source_blocked")
        delay_ratio = 0.0
    position_policy = entry.position_policy
    if position_policy.get("admission_status") != "executable":
        reasons.append(str(position_policy.get("blocked_reason") or "summon_monster_position_policy_blocked"))
    profile_values, profile_reasons = _birth_profile_values(profile)
    reasons.extend(profile_reasons)
    stat_resolutions = _birth_profile_stat_resolutions(entry, profile, profile_values)
    source_trace = entry.source.to_json()
    card_source = card.source.to_json() if card is not None else {}
    profile_source = profile.source.to_json() if profile is not None else {}
    timeline_source = timeline_rule.source.to_json() if timeline_rule is not None else {}
    location_type = str(position_policy.get("location_type") or "")
    unit_field_specs: dict[str, JSONValue] = {
        "side": "enemy",
        "template_id": entry.monster_entity_ref,
        "level": {"binding_kind": "owner_field", "field": "level"},
        "max_hp": profile_values.get("max_hp"),
        "hp": {"binding_kind": "copy_unit_field", "field": "max_hp"},
        "attack": profile_values.get("attack"),
        "defense": profile_values.get("defense"),
        "speed": profile_values.get("speed"),
        "energy": 0.0,
        "max_energy": 0.0,
        "toughness": profile_values.get("current_toughness"),
        "max_toughness": profile_values.get("max_toughness"),
        "action_value": {
            "binding_kind": "timeline_action_value",
            "speed_field": "speed",
            "base_action_gauge": timeline_rule.base_action_gauge if timeline_rule is not None else None,
            "multiplier": delay_ratio,
        },
    }
    flag_specs: dict[str, JSONValue] = {
        "position": {
            "binding_kind": "relative_owner_position",
            "location_type": location_type,
            "offset_request_field": "spawn_index",
        },
        "team_side": "enemy",
        "summon_kind": "summoned_monster",
        "wave_member_kind": "enemy_summon",
        "wave_clear_policy": entry.wave_clear_policy,
        "owner_id": {"binding_kind": "request_field", "field": "owner_id"},
        "summoner_id": {"binding_kind": "request_field", "field": "summoner_id"},
        "summon_intent_id": {"binding_kind": "request_field", "field": "source_id"},
        "summon_entry_id": {"binding_kind": "request_field", "field": "entry_id"},
        "summon_entry_index": {"binding_kind": "request_field", "field": "entry_index"},
        "summon_entry_copy_index": {"binding_kind": "request_field", "field": "copy_index"},
        "summon_spawn_index": {"binding_kind": "request_field", "field": "spawn_index"},
        "summon_entry_count": entry.count,
        "summon_source_trace": intent.source.to_json(),
        "summon_entry_source_trace": source_trace,
        "summon_position_policy": entry.position_policy,
        "summon_level_policy": entry.level_policy,
        "summon_value_resolutions": stat_resolutions,
        "summon_level_source_trace": profile_source,
        "summon_delay_policy": intent.delay_policy,
        "combatant_profile_id": profile.profile_id if profile is not None else "",
        "combatant_profile_source_trace": profile_source,
        "combatant_profile_coverage_status": profile.coverage_status if profile is not None else "blocked",
        "monster_data_card_id": card.card_id if card is not None else "",
        "monster_data_card_source_trace": card_source,
        "monster_passive_mechanism_slot_ids": list(card.passive_mechanism_slot_ids) if card is not None else [],
        "weaknesses": list(profile.weaknesses) if profile is not None else [],
        "debuff_resistances": list(profile.debuff_resistances) if profile is not None else [],
        "toughness_profile_source_trace": profile_source,
        "resistance_source_trace": profile_source,
        "status_resistance_source_trace": profile_source,
        "timeline_admitted": timeline_rule is not None,
        "summon_action_admitted": card is not None,
        "summon_action_admission": {
            "coverage_status": "executable" if card is not None else "blocked",
            "source_trace": {
                "summon_intent": intent.source.to_json(),
                "summon_entry": source_trace,
                "monster_data_card": card_source,
                "combatant_profile": profile_source,
            },
            "action_set_kind": "enemy_fixed_sequence",
            "monster_data_card_id": card.card_id if card is not None else "",
            "action_sequence_count": len(card.action_sequence) if card is not None else 0,
            "executable_action_sequence_count": sum(
                1
                for step in (card.action_sequence if card is not None else ())
                if isinstance(step, dict) and step.get("coverage_status") == "executable"
            ),
        },
        "initial_action_value_source_trace": {
            "binding_kind": "timeline_trace",
            "timeline_rule_id": timeline_rule.timeline_rule_id if timeline_rule is not None else "",
            "timeline_rule_source": timeline_source,
            "speed_source": profile_source,
            "formula": timeline_rule.initial_action_value_rule if timeline_rule is not None else "",
            "multiplier": delay_ratio,
            "summon_delay_policy": intent.delay_policy,
            "summon_delay_application": "initial_action_value_full_av_times_delay_ratio",
        },
    }
    blocked_reason = ";".join(dict.fromkeys(reason for reason in reasons if reason))
    return UnitBirthTemplateIR(
        birth_template_id=entry.birth_template_id,
        spawn_kind="summoned_monster",
        entity_ref=entry.monster_entity_ref,
        unit_field_specs=unit_field_specs,
        flag_specs=flag_specs,
        resource_specs=_birth_profile_resources(profile),
        request_contract={
            "spawn_kind": "summoned_monster",
            "entity_ref": entry.monster_entity_ref,
            "source_id": intent.summon_intent_id,
            "entry_id": entry.entry_id,
            "owner_required": True,
            "summoner_matches_owner": True,
            "template_source_role": "entry",
        },
        source=entry.source,
        coverage_status="blocked" if blocked_reason else "executable",
        blocked_reason=blocked_reason,
    )


def _servant_birth_template(
    definition: ServantDefinitionIR,
    timeline_rule: TimelineRuleIR | None,
) -> UnitBirthTemplateIR:
    reasons: list[str] = []
    if definition.coverage_status != "executable" or definition.representation != "unit":
        reasons.append(definition.blocked_reason or f"servant_definition_not_executable:{definition.coverage_status}")
    if timeline_rule is None:
        reasons.append("servant_timeline_rule_missing")
    components = definition.stat_source.get("components") if isinstance(definition.stat_source, dict) else None
    component_values: dict[str, float] = {}
    for key in ("hp_base", "hp_inherit", "speed_base", "speed_inherit"):
        component = components.get(key) if isinstance(components, dict) else None
        value = _strict_json_number(component.get("value")) if isinstance(component, dict) else None
        if value is None:
            reasons.append(f"servant_birth_template_stat_component_missing:{key}")
        else:
            component_values[key] = value
    source_trace = definition.source.to_json()
    timeline_source_trace = _birth_first_source_trace(definition.timeline_source, source_trace)
    lifecycle_source_trace = _birth_first_source_trace(definition.lifecycle_source, source_trace)
    action_set_trace = definition.action_set.get("source_trace") if isinstance(definition.action_set, dict) else None
    unit_field_specs: dict[str, JSONValue] = {
        "side": "summon",
        "template_id": definition.servant_ref,
        "level": {"binding_kind": "owner_field", "field": "level"},
        "max_hp": {
            "binding_kind": "owner_linear",
            "owner_field": "max_hp",
            "scale": component_values.get("hp_inherit"),
            "offset": component_values.get("hp_base"),
            "minimum": 0.0,
        },
        "hp": {"binding_kind": "copy_unit_field", "field": "max_hp"},
        "attack": {"binding_kind": "owner_field", "field": "attack"},
        "defense": {"binding_kind": "owner_field", "field": "defense"},
        "speed": {
            "binding_kind": "owner_linear",
            "owner_field": "speed",
            "scale": component_values.get("speed_inherit"),
            "offset": component_values.get("speed_base"),
            "minimum": 0.0,
        },
        "energy": 0.0,
        "max_energy": 0.0,
        "toughness": 0.0,
        "max_toughness": 0.0,
        "action_value": {
            "binding_kind": "timeline_action_value",
            "speed_field": "speed",
            "base_action_gauge": timeline_rule.base_action_gauge if timeline_rule is not None else None,
            "multiplier": 1.0,
        },
    }
    flag_specs: dict[str, JSONValue] = {
        "position": {"binding_kind": "owner_position"},
        "team_side": {"binding_kind": "owner_team_side"},
        "summon_kind": "servant",
        "owner_id": {"binding_kind": "request_field", "field": "owner_id"},
        "summoner_id": {"binding_kind": "request_field", "field": "summoner_id"},
        "owner_entity_ref": definition.owner_entity_ref,
        "servant_definition_id": {"binding_kind": "request_field", "field": "source_id"},
        "servant_ref": definition.servant_ref,
        "summon_intent_id": {"binding_kind": "request_field", "field": "source_id"},
        "summon_source_trace": source_trace,
        "servant_definition_source_trace": source_trace,
        "stat_source": definition.stat_source,
        "servant_owner_source": definition.stat_source.get("owner_source", {})
        if isinstance(definition.stat_source, dict)
        else {},
        "timeline_source": definition.timeline_source,
        "lifecycle_source": definition.lifecycle_source,
        "servant_runtime_stat_values": {
            "binding_kind": "servant_runtime_stat_values",
            "hp_formula": "owner.max_hp * hp_inherit + hp_base",
            "speed_formula": "owner.speed * speed_inherit + speed_base",
            "attack_source_status": "schema_carry_only",
            "defense_source_status": "schema_carry_only",
        },
        "timeline_admitted": timeline_rule is not None,
        "summon_action_admitted": definition.action_set.get("admission_status") == "executable",
        "summon_action_admission": {
            "coverage_status": definition.action_set.get("admission_status") or definition.action_set.get("coverage_status"),
            "source_trace": {
                "servant_definition": source_trace,
                "action_set_source_trace": list(action_set_trace) if isinstance(action_set_trace, list) else [],
            },
            "action_set": definition.action_set,
            "ability_graph_ids": list(definition.ability_graph_ids),
            "skipped_slots": definition.action_set.get("skipped_slots", [])
            if isinstance(definition.action_set, dict)
            else [],
        },
        "owner_death_policy": "remove",
        "owner_death_policy_admission": {
            "coverage_status": "executable",
            "remove_source_admitted": True,
            "lifecycle_source": definition.lifecycle_source,
        },
        "owner_death_policy_source_trace": lifecycle_source_trace,
        "initial_action_value_source_trace": {
            "binding_kind": "timeline_trace",
            "timeline_rule_id": timeline_rule.timeline_rule_id if timeline_rule is not None else "",
            "timeline_rule_source": timeline_rule.source.to_json() if timeline_rule is not None else {},
            "timeline_source": timeline_source_trace,
            "formula": timeline_rule.initial_action_value_rule if timeline_rule is not None else "",
            "multiplier": 1.0,
        },
        "servant_attack_defense_source_status": {
            "coverage_status": "schema_carry_only",
            "source": "owner_current_unit_state",
            "note": "servant damage stat binding is not admitted by servant spawn",
        },
    }
    blocked_reason = ";".join(dict.fromkeys(reason for reason in reasons if reason))
    return UnitBirthTemplateIR(
        birth_template_id=definition.birth_template_id,
        spawn_kind="servant",
        entity_ref=definition.servant_ref,
        unit_field_specs=unit_field_specs,
        flag_specs=flag_specs,
        resource_specs={},
        request_contract={
            "spawn_kind": "servant",
            "entity_ref": definition.servant_ref,
            "source_id": definition.servant_definition_id,
            "entry_id": definition.servant_definition_id,
            "owner_required": True,
            "summoner_matches_owner": True,
            "owner_entity_ref": definition.owner_entity_ref,
            "template_source_role": "entry",
        },
        source=definition.source,
        coverage_status="blocked" if blocked_reason else "executable",
        blocked_reason=blocked_reason,
    )


def _wave_enemy_birth_template(
    definition: WaveDefinitionIR,
    entry: WaveMonsterEntryIR,
    profile: CombatantProfileIR | None,
    card: MonsterDataCardIR | None,
    timeline_rule: TimelineRuleIR | None,
) -> UnitBirthTemplateIR:
    reasons: list[str] = []
    if definition.coverage_status != "executable":
        reasons.append(definition.blocked_reason or f"wave_definition_not_executable:{definition.coverage_status}")
    if entry.coverage_status != "executable":
        reasons.append(entry.blocked_reason or f"wave_entry_not_executable:{entry.coverage_status}")
    if definition.level_policy.get("admission_status") != "executable":
        reasons.append(str(definition.level_policy.get("blocked_reason") or "wave_stage_level_source_blocked"))
    if definition.level is None or definition.hard_level_group is None:
        reasons.append("wave_stage_level_source_missing")
    if profile is None or profile.coverage_status != "executable":
        reasons.append("wave_combatant_profile_missing_or_blocked")
    if card is None:
        reasons.append("wave_monster_data_card_missing")
    if timeline_rule is None:
        reasons.append("wave_timeline_rule_missing")
    profile_values, profile_reasons = _birth_profile_values(profile)
    reasons.extend(profile_reasons)
    ratios = definition.level_policy.get("ratios") if isinstance(definition.level_policy, dict) else None
    scaled_values: dict[str, float] = {}
    for field_name in ("max_hp", "attack", "defense", "speed", "max_toughness"):
        ratio = _strict_json_number(ratios.get(field_name)) if isinstance(ratios, dict) else None
        source_field = "max_toughness" if field_name == "max_toughness" else field_name
        base_value = _strict_json_number(profile_values.get(source_field))
        if ratio is None or ratio <= 0 or base_value is None:
            reasons.append(f"wave_stage_scaled_stat_source_missing:{field_name}")
        else:
            scaled_values[field_name] = base_value * ratio
    scaled_values["current_toughness"] = scaled_values.get("max_toughness", 0.0)
    profile_source = profile.source.to_json() if profile is not None else {}
    card_source = card.source.to_json() if card is not None else {}
    timeline_source = timeline_rule.source.to_json() if timeline_rule is not None else {}
    level_source_trace = definition.level_policy.get("source_trace") if isinstance(definition.level_policy, dict) else {}
    unit_field_specs: dict[str, JSONValue] = {
        "side": "enemy",
        "template_id": entry.monster_entity_ref,
        "level": definition.level,
        "max_hp": scaled_values.get("max_hp"),
        "hp": {"binding_kind": "copy_unit_field", "field": "max_hp"},
        "attack": scaled_values.get("attack"),
        "defense": scaled_values.get("defense"),
        "speed": scaled_values.get("speed"),
        "energy": 0.0,
        "max_energy": 0.0,
        "toughness": scaled_values.get("current_toughness"),
        "max_toughness": scaled_values.get("max_toughness"),
        "action_value": {
            "binding_kind": "timeline_action_value",
            "speed_field": "speed",
            "base_action_gauge": timeline_rule.base_action_gauge if timeline_rule is not None else None,
            "multiplier": 1.0,
        },
    }
    flag_specs: dict[str, JSONValue] = {
        "position": {"binding_kind": "request_field", "field": "position"},
        "wave_definition_id": {"binding_kind": "request_field", "field": "wave_definition_id"},
        "stage_id": definition.stage_id,
        "wave_index": {"binding_kind": "request_field", "field": "wave_index"},
        "wave_position": {"binding_kind": "request_field", "field": "position"},
        "wave_entry_id": {"binding_kind": "request_field", "field": "entry_id"},
        "wave_member_kind": "stage_wave_enemy",
        "wave_clear_policy": "counts",
        "wave_entry_source_trace": {"binding_kind": "request_field", "field": "entry_source_trace"},
        "wave_definition_source_trace": {"binding_kind": "request_field", "field": "source_trace"},
        "stage_level": definition.level,
        "hard_level_group": definition.hard_level_group,
        "stage_level_policy": definition.level_policy,
        "stage_level_source_trace": level_source_trace if isinstance(level_source_trace, dict) else {},
        "wave_stat_scaling": {
            "kind": "combatant_profile_times_stage_hard_level_ratios",
            "base_profile_values": profile_values,
            "ratios": ratios if isinstance(ratios, dict) else {},
            "resolved_values": scaled_values,
            "source_trace": {
                "combatant_profile": profile_source,
                "stage_level": level_source_trace if isinstance(level_source_trace, dict) else {},
            },
        },
        "combatant_profile_id": profile.profile_id if profile is not None else "",
        "combatant_profile_source_trace": profile_source,
        "combatant_profile_coverage_status": profile.coverage_status if profile is not None else "blocked",
        "monster_data_card_id": card.card_id if card is not None else "",
        "monster_data_card_source_trace": card_source,
        "monster_passive_mechanism_slot_ids": list(card.passive_mechanism_slot_ids) if card is not None else [],
        "weaknesses": list(profile.weaknesses) if profile is not None else [],
        "debuff_resistances": list(profile.debuff_resistances) if profile is not None else [],
        "initial_action_value_source_trace": {
            "binding_kind": "timeline_trace",
            "timeline_rule_id": timeline_rule.timeline_rule_id if timeline_rule is not None else "",
            "timeline_rule_source": timeline_source,
            "speed_source": {
                "combatant_profile": profile_source,
                "stage_level": level_source_trace if isinstance(level_source_trace, dict) else {},
            },
            "formula": timeline_rule.initial_action_value_rule if timeline_rule is not None else "",
            "multiplier": 1.0,
        },
    }
    blocked_reason = ";".join(dict.fromkeys(reason for reason in reasons if reason))
    return UnitBirthTemplateIR(
        birth_template_id=entry.birth_template_id,
        spawn_kind="wave_enemy",
        entity_ref=entry.monster_entity_ref,
        unit_field_specs=unit_field_specs,
        flag_specs=flag_specs,
        resource_specs=_birth_profile_resources(profile),
        request_contract={
            "spawn_kind": "wave_enemy",
            "entity_ref": entry.monster_entity_ref,
            "source_id": definition.wave_definition_id,
            "wave_definition_id": definition.wave_definition_id,
            "stage_id": definition.stage_id,
            "owner_required": False,
            "template_source_role": "source",
        },
        source=definition.source,
        coverage_status="blocked" if blocked_reason else "executable",
        blocked_reason=blocked_reason,
    )


def _birth_profile_values(profile: CombatantProfileIR | None) -> tuple[dict[str, float], list[str]]:
    if profile is None:
        return {}, ["unit_birth_template_combatant_profile_missing"]
    values: dict[str, float] = {}
    reasons: list[str] = []
    for field_name in ("max_hp", "attack", "defense", "speed"):
        value = _strict_json_number(profile.base_stats.get(field_name))
        if value is None:
            reasons.append(f"unit_birth_template_profile_stat_missing:{field_name}")
        else:
            values[field_name] = value
    for field_name in ("current_toughness", "max_toughness"):
        value = _strict_json_number(profile.toughness_profile.get(field_name))
        if value is None:
            reasons.append(f"unit_birth_template_profile_toughness_missing:{field_name}")
        else:
            values[field_name] = value
    return values, reasons


def _birth_profile_resources(profile: CombatantProfileIR | None) -> dict[str, JSONValue]:
    if profile is None:
        return {}
    resources: dict[str, JSONValue] = {
        f"{damage_type}_resistance": float(value)
        for damage_type, value in profile.resistances.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    if isinstance(profile.status_resistance, (int, float)) and not isinstance(profile.status_resistance, bool):
        resources["effect_resistance"] = float(profile.status_resistance)
    return resources


def _birth_profile_stat_resolutions(
    entry: SummonMonsterEntryIR,
    profile: CombatantProfileIR | None,
    values: dict[str, float],
) -> dict[str, JSONValue]:
    profile_source = profile.source.to_json() if profile is not None else {}
    source_trace = {"summon_entry": entry.source.to_json(), "combatant_profile": profile_source}
    result: dict[str, JSONValue] = {}
    for field_name in ("max_hp", "attack", "defense", "speed"):
        value = values.get(field_name)
        result[field_name] = {
            "ok": value is not None,
            "value": value,
            "binding_kind": "combatant_profile_base_stat",
            "source_trace": source_trace,
            "context_trace": {
                "combatant_profile_id": profile.profile_id if profile is not None else "",
                "available_keys": ["combatant_profile"] if profile is not None else [],
            },
            "blocked_reason": "" if value is not None else f"combatant_profile_base_stat_missing:{field_name}",
            "request": {
                "binding_kind": "combatant_profile_base_stat",
                "field_name": field_name,
                "required_context_keys": ["combatant_profile"],
            },
            "delegate_resolution": {
                "value_source": f"CombatantProfileIR.base_stats.{field_name}",
                "profile_id": profile.profile_id if profile is not None else "",
            },
            "context_keys": ["combatant_profile"] if profile is not None else [],
        }
    return result


def _birth_first_source_trace(source: dict[str, JSONValue], fallback: dict[str, JSONValue]) -> dict[str, JSONValue]:
    traces = source.get("source_trace") if isinstance(source, dict) else None
    if isinstance(traces, list) and traces and isinstance(traces[0], dict):
        return dict(traces[0])
    if isinstance(traces, dict):
        return dict(traces)
    return dict(fallback)


def _strict_json_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _trace_startup_dynamic_binding_admission(
    standard: object,
    semantics: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    if not isinstance(standard, dict):
        return {"admission_status": "blocked", "blocked_reason": "trace_startup_standard_payload_missing"}
    requests = standard.get("dynamic_value_requests")
    if not isinstance(requests, dict) or not requests:
        return {"admission_status": "not_applicable", "reason": "no_dynamic_value_requests"}
    configured_bindings = semantics.get("dynamic_value_bindings")
    configured_by_hash = configured_bindings.get("by_hash") if isinstance(configured_bindings, dict) else None
    if not isinstance(configured_by_hash, dict) or not configured_by_hash:
        return {
            "admission_status": "blocked",
            "blocked_reason": "trace_skill_tree_dynamic_value_bindings_missing",
        }
    params = tuple(_number_items(semantics.get("param_values")))
    bindings: list[dict[str, JSONValue]] = []
    for name, request in requests.items():
        if not isinstance(request, dict):
            continue
        raw_hash = request.get("hash")
        if raw_hash is None:
            return {
                "admission_status": "blocked",
                "blocked_reason": "trace_dynamic_value_request_hash_missing",
                "request_name": str(name),
            }
        configured = configured_by_hash.get(str(raw_hash))
        if not isinstance(configured, dict):
            return {
                "admission_status": "blocked",
                "blocked_reason": "trace_dynamic_value_binding_hash_missing",
                "request_name": str(name),
                "hash": str(raw_hash),
            }
        param_index = configured.get("param_index")
        if not isinstance(param_index, int):
            return {
                "admission_status": "blocked",
                "blocked_reason": "trace_dynamic_value_binding_param_index_missing",
                "request_name": str(name),
                "hash": str(raw_hash),
                "binding": _json_safe(configured),
            }
        if param_index < 0 or param_index >= len(params):
            return {
                "admission_status": "blocked",
                "blocked_reason": "trace_dynamic_value_binding_param_index_out_of_range",
                "request_name": str(name),
                "hash": str(raw_hash),
                "param_index": param_index,
                "param_count": len(params),
            }
        bindings.append(
            {
                "name": str(name),
                "hash": str(raw_hash),
                "param_index": param_index,
                "value": float(params[param_index]),
                "binding_source_kind": "character_config_skill_tree_param_read_info",
                "binding_source": _json_safe(configured),
            }
        )
    return {
        "admission_status": "executable",
        "source_kind": "trace_skill_tree_param_to_startup_ability_dynamic_value_request",
        "bindings": bindings,
    }


def _admit_passive_startup_slots(
    slots: list[PassiveMechanismSlotIR],
    *,
    standalone_graphs: list[StandaloneAbilityGraphIR],
    ability_tasks: list[AbilityTaskIR],
    effects: list[EffectIR],
    triggers: list[TriggerIR],
) -> list[PassiveMechanismSlotIR]:
    graphs_by_name: dict[str, list[StandaloneAbilityGraphIR]] = {}
    for graph in standalone_graphs:
        graphs_by_name.setdefault(graph.ability_name, []).append(graph)
    tasks_by_phase: dict[str, list[AbilityTaskIR]] = {}
    for task in ability_tasks:
        tasks_by_phase.setdefault(task.phase_id, []).append(task)
    effects_by_id = {effect.effect_id: effect for effect in effects}
    modifiers_with_triggers = _modifier_names_with_triggers(triggers)
    admitted: list[PassiveMechanismSlotIR] = []
    for slot in slots:
        if slot.mechanism_kind != "monster_ability_list_passive":
            admitted.append(slot)
            continue
        admitted.append(
            _admit_passive_startup_slot(
                slot,
                graphs_by_name=graphs_by_name,
                tasks_by_phase=tasks_by_phase,
                effects_by_id=effects_by_id,
                modifiers_with_triggers=modifiers_with_triggers,
            )
        )
    return admitted


def _admit_passive_startup_slot(
    slot: PassiveMechanismSlotIR,
    *,
    graphs_by_name: dict[str, list[StandaloneAbilityGraphIR]],
    tasks_by_phase: dict[str, list[AbilityTaskIR]],
    effects_by_id: dict[str, EffectIR],
    modifiers_with_triggers: set[str],
) -> PassiveMechanismSlotIR:
    semantics = dict(slot.semantics)
    ability_name = str(semantics.get("ability_name") or slot.linked_ir_ids.get("ability_name") or "")
    if slot.coverage_status == "blocked":
        return _passive_startup_blocked_slot(
            slot,
            slot.blocked_reason or "monster_passive_slot_not_lowered",
            {
                **semantics,
                "startup_admission": {
                    "admission_status": "blocked",
                    "blocked_reason": slot.blocked_reason or "monster_passive_slot_not_lowered",
                    "ability_name": ability_name,
                },
            },
        )
    if not ability_name:
        return _passive_startup_blocked_slot(slot, "monster_passive_ability_name_missing", semantics)

    expected_path = str(slot.linked_ir_ids.get("ability_file_path") or "")
    graph_candidates = tuple(sorted(graphs_by_name.get(ability_name, ()), key=lambda item: item.standalone_ability_graph_id))
    if expected_path:
        graph_candidates = tuple(graph for graph in graph_candidates if graph.source.source_path == expected_path)
    executable_graphs = tuple(
        graph for graph in graph_candidates if graph.coverage_status == "executable" and graph.source_mode == "mainline_monster"
    )
    if len(executable_graphs) != 1:
        reason = "monster_passive_startup_graph_missing_or_ambiguous"
        if graph_candidates and not executable_graphs:
            reason = "monster_passive_startup_graph_not_executable"
        return _passive_startup_blocked_slot(
            slot,
            reason,
            {
                **semantics,
                "startup_admission": {
                    "admission_status": "blocked",
                    "blocked_reason": reason,
                    "ability_name": ability_name,
                    "expected_ability_file_path": expected_path,
                    "candidate_graph_ids": [graph.standalone_ability_graph_id for graph in graph_candidates],
                    "candidate_graph_statuses": [graph.coverage_status for graph in graph_candidates],
                    "candidate_graph_source_modes": [graph.source_mode for graph in graph_candidates],
                },
            },
        )
    graph = executable_graphs[0]
    root_on_start_tasks = tuple(
        task
        for phase_id in graph.phase_ids
        for task in tasks_by_phase.get(phase_id, ())
        if task.callback_kind == "OnStart" and not task.parent_task_id
    )
    unadmitted_root_tasks = tuple(
        task for task in root_on_start_tasks if task.opcode != "AddModifier" or not task.effect_id
    )
    if unadmitted_root_tasks:
        reason = "monster_passive_startup_root_on_start_has_unadmitted_tasks"
        return _passive_startup_blocked_slot(
            slot,
            reason,
            {
                **semantics,
                "startup_admission": {
                    "admission_status": "blocked",
                    "blocked_reason": reason,
                    "standalone_ability_graph_id": graph.standalone_ability_graph_id,
                    "blocked_tasks": [
                        {
                            "task_id": task.task_id,
                            "opcode": task.opcode,
                            "effect_id": task.effect_id,
                            "blocked_reason": f"root_on_start_task_not_admitted:{task.opcode}",
                        }
                        for task in unadmitted_root_tasks
                    ],
                },
            },
        )

    candidate_tasks = tuple(
        task
        for task in root_on_start_tasks
        if task.opcode == "AddModifier" and task.effect_id
    )
    if not candidate_tasks:
        return _passive_startup_blocked_slot(
            slot,
            "monster_passive_startup_on_start_add_modifier_missing",
            {
                **semantics,
                "startup_admission": {
                    "admission_status": "blocked",
                    "blocked_reason": "monster_passive_startup_on_start_add_modifier_missing",
                    "standalone_ability_graph_id": graph.standalone_ability_graph_id,
                },
            },
        )

    admitted_tasks: list[dict[str, JSONValue]] = []
    blocked_tasks: list[dict[str, JSONValue]] = []
    for task in candidate_tasks:
        effect = effects_by_id.get(task.effect_id)
        if effect is None:
            blocked_tasks.append({"task_id": task.task_id, "blocked_reason": "monster_passive_startup_effect_missing"})
            continue
        effect_reason = _passive_startup_effect_blocked_reason(effect, modifiers_with_triggers)
        if effect_reason:
            blocked_tasks.append(
                {
                    "task_id": task.task_id,
                    "effect_id": effect.effect_id,
                    "blocked_reason": effect_reason,
                    "effect_coverage_status": effect.coverage_status,
                }
            )
            continue
        admitted_tasks.append({"task_id": task.task_id, "effect_id": effect.effect_id})
    if not admitted_tasks:
        return _passive_startup_blocked_slot(
            slot,
            "monster_passive_startup_no_admitted_on_start_add_modifier",
            {
                **semantics,
                "startup_admission": {
                    "admission_status": "blocked",
                    "blocked_reason": "monster_passive_startup_no_admitted_on_start_add_modifier",
                    "standalone_ability_graph_id": graph.standalone_ability_graph_id,
                    "blocked_tasks": blocked_tasks,
                },
            },
        )
    return replace(
        slot,
        linked_ir_ids={
            **slot.linked_ir_ids,
            "standalone_ability_graph_id": graph.standalone_ability_graph_id,
            "admitted_task_ids": [str(item["task_id"]) for item in admitted_tasks],
            "admitted_effect_ids": [str(item["effect_id"]) for item in admitted_tasks],
        },
        semantics={
            **semantics,
            "startup_admission": {
                "admission_status": "executable",
                "startup_kind": "monster_passive_on_start_add_modifier",
                "standalone_ability_graph_id": graph.standalone_ability_graph_id,
                "admitted_tasks": admitted_tasks,
                "blocked_tasks": blocked_tasks,
                "event_trigger_execution_admitted": False,
            },
        },
        activation={
            **slot.activation,
            "kind": "monster_passive_startup_ability",
        },
        coverage_status="executable",
        blocked_reason="",
    )


def _passive_startup_blocked_slot(
    slot: PassiveMechanismSlotIR,
    reason: str,
    semantics: dict[str, JSONValue],
) -> PassiveMechanismSlotIR:
    return replace(slot, semantics=semantics, coverage_status="blocked", blocked_reason=reason)


def _passive_startup_effect_blocked_reason(effect: EffectIR, modifiers_with_triggers: set[str]) -> str:
    if effect.opcode != "AddModifier":
        return f"monster_passive_startup_effect_opcode_not_add_modifier:{effect.opcode}"
    if effect.coverage_status != "executable":
        return f"monster_passive_startup_effect_not_executable:{effect.coverage_status}"
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return "monster_passive_startup_effect_standard_payload_missing"
    modifier_name = standard.get("modifier_name")
    if not isinstance(modifier_name, str) or not modifier_name:
        return "monster_passive_startup_effect_modifier_name_missing"
    target_alias = standard.get("target_alias")
    if target_alias not in {"Caster", "ModifierOwnerEntity"}:
        return f"monster_passive_startup_effect_target_alias_not_admitted:{target_alias}"
    requests = standard.get("dynamic_value_requests")
    if requests:
        return "monster_passive_startup_dynamic_value_request_not_admitted"
    if modifier_name in modifiers_with_triggers:
        return "monster_passive_startup_modifier_has_event_triggers"
    return ""


def _modifier_names_with_triggers(triggers: list[TriggerIR]) -> set[str]:
    return {
        str(trigger.source.raw_id)
        for trigger in triggers
        if isinstance(trigger.source.raw_id, str) and trigger.source.raw_id
    }


def _attach_character_runtime_mechanism_slots(
    cards: list[CharacterDataCardIR],
    slots: list[CharacterMechanismSlotIR],
) -> list[CharacterDataCardIR]:
    slot_ids_by_card: dict[str, list[str]] = {}
    for slot in slots:
        slot_ids_by_card.setdefault(slot.character_data_card_id, []).append(slot.mechanism_slot_id)
    updated: list[CharacterDataCardIR] = []
    for card in cards:
        existing = list(card.mechanism_slot_ids)
        existing.extend(slot_ids_by_card.get(card.card_id, ()))
        updated.append(replace(card, mechanism_slot_ids=tuple(sorted(dict.fromkeys(existing)))))
    return updated


def _dedupe_character_mechanism_slots(slots: list[CharacterMechanismSlotIR]) -> list[CharacterMechanismSlotIR]:
    deduped: dict[str, CharacterMechanismSlotIR] = {}
    for slot in slots:
        deduped[slot.mechanism_slot_id] = slot
    return list(deduped.values())


def _ability_file_from_action_binding(binding: ActionAbilityBindingIR) -> str:
    for value in (
        binding.config_source.get("ability_file") if isinstance(binding.config_source, dict) else None,
        binding.config_source.get("ability_file_path") if isinstance(binding.config_source, dict) else None,
        binding.source.evidence.get("ability_file") if isinstance(binding.source.evidence, dict) else None,
        binding.source.evidence.get("ability_file_path") if isinstance(binding.source.evidence, dict) else None,
    ):
        if isinstance(value, str) and value:
            return value
    return ""


def _dedupe_entities(entities: list[RuleEntity]) -> dict[str, RuleEntity]:
    deduped: dict[str, RuleEntity] = {}
    for entity in entities:
        deduped[entity.entity_id] = entity
    return deduped


def _dedupe_target_expressions(expressions: list[TargetExpressionIR]) -> dict[str, TargetExpressionIR]:
    deduped: dict[str, TargetExpressionIR] = {}
    for expression in expressions:
        deduped[expression.target_expression_id] = expression
    return deduped


def _modifier_definition_entity(
    relative_path: str,
    map_name: str,
    modifier_name: str,
    modifier: dict[str, Any],
) -> RuleEntity:
    source = IRSource(
        source_path=relative_path,
        raw_type=map_name,
        raw_id=modifier_name,
        evidence={
            "modifier_name": modifier_name,
            "map_name": map_name,
            "definition_kind": "modifier_definition",
        },
    )
    fields = {
        "modifier_name": modifier_name,
        "map_name": map_name,
        "stacking": _json_safe(modifier.get("Stacking")),
        "lifetime": _json_safe(modifier.get("LifeTime")),
        "lifetime_expr": _numeric_expr_summary(modifier.get("LifeTime")),
        "life_step_moment": _value_field(modifier.get("LifeStepMoment")),
        "duration_admission": _duration_admission_payload(
            _numeric_expr_summary(modifier.get("LifeTime")),
            _value_field(modifier.get("LifeStepMoment")),
        ),
        "behavior_flags": _json_safe(modifier.get("BehaviorFlagList", [])),
        "dynamic_values": _json_safe(modifier.get("DynamicValues", {})),
        "dynamic_value_bindings": _dynamic_value_bindings(modifier.get("DynamicValues")),
        "callback_dynamic_hashes": _callback_dynamic_hashes(modifier),
        "callback_events": _callback_events(modifier),
        "stack_properties": _stack_property_summaries(modifier),
    }
    return RuleEntity(
        entity_id=f"modifier_definition:{modifier_name}:{_safe_id(relative_path)}:{_safe_id(map_name)}",
        entity_type="modifier_definition",
        fields=fields,
        source=source,
        coverage_status="lowered",
    )


def _callback_events(modifier: dict[str, Any]) -> list[str]:
    events: list[str] = []
    callbacks = modifier.get("_CallbackList")
    if not isinstance(callbacks, list):
        return events
    for callback in callbacks:
        if isinstance(callback, dict):
            events.append(str(callback.get("Event") or "UnknownEvent"))
    return events


def _callback_dynamic_hashes(modifier: dict[str, Any]) -> dict[str, Any]:
    callbacks = modifier.get("_CallbackList")
    hashes: dict[str, dict[str, Any]] = {}
    if not isinstance(callbacks, list):
        return {"by_hash": {}}

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            dynamic_hashes = value.get("DynamicHashes")
            if isinstance(dynamic_hashes, list):
                for index, raw_hash in enumerate(dynamic_hashes):
                    if isinstance(raw_hash, int):
                        hashes.setdefault(
                            str(raw_hash),
                            {
                                "hash": str(raw_hash),
                                "raw_path": f"{path}.DynamicHashes[{index}]",
                                "source_kind": "modifier_callback_dynamic_hash",
                            },
                        )
            for key, item in value.items():
                walk(item, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")

    walk(callbacks, "_CallbackList")
    return {"by_hash": hashes}


def _stack_property_summaries(modifier: dict[str, Any]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    callbacks = modifier.get("_CallbackList")
    if not isinstance(callbacks, list):
        return summaries
    for callback_index, callback in enumerate(callbacks):
        if not isinstance(callback, dict):
            continue
        event = str(callback.get("Event") or "UnknownEvent")
        tasks = callback.get("CallbackConfig")
        if not isinstance(tasks, list):
            continue
        for task_index, task in enumerate(tasks):
            if not isinstance(task, dict) or _short_gamecore_type(task.get("$type")) != "StackProperty":
                continue
            summaries.append(
                {
                    "event": event,
                    "callback_index": callback_index,
                    "task_index": task_index,
                    "property": str(task.get("Property") or ""),
                    "target_alias": _target_alias(task.get("TargetType")),
                    "value_expr": _numeric_expr_summary(task.get("PropertyValue")),
                    "is_refresh": bool(task.get("IsRefresh", False)),
                    "raw_path": f"_CallbackList[{callback_index}].CallbackConfig[{task_index}]",
                }
            )
    return summaries


def _combatant_profile_from_monster(
    monster_id: str,
    monster_row: dict[str, Any],
    template_id: str,
    template_row: dict[str, Any] | None,
    *,
    source_path: str = "ExcelOutput/MonsterConfig.json",
    raw_type: str = "MonsterConfig",
    template_source_path: str = "ExcelOutput/MonsterTemplateConfig.json",
) -> CombatantProfileIR:
    source = IRSource(
        source_path=source_path,
        raw_type=raw_type,
        raw_id=monster_id,
        evidence={
            "entity_id": f"monster:{monster_id}",
            "template_id": template_id,
            "template_source_path": template_source_path,
            "raw_paths": {
                "template_id": "MonsterTemplateID",
                "attack_modify_ratio": "AttackModifyRatio",
                "defense_modify_ratio": "DefenceModifyRatio",
                "hp_modify_ratio": "HPModifyRatio",
                "speed_modify_ratio": "SpeedModifyRatio",
                "stance_modify_ratio": "StanceModifyRatio",
                "weaknesses": "StanceWeakList",
                "resistances": "DamageTypeResistance",
            },
        },
    )
    if template_row is None:
        return _blocked_combatant_profile(
            profile_id=f"combatant_profile:monster:{monster_id}",
            entity_id=f"monster:{monster_id}",
            entity_type="monster",
            template_id=template_id,
            source=source,
            reason="monster_template_missing",
        )
    stat_result = _monster_profile_stats(monster_row, template_row)
    blocked_reason = stat_result.get("blocked_reason", "")
    return CombatantProfileIR(
        profile_id=f"combatant_profile:monster:{monster_id}",
        entity_id=f"monster:{monster_id}",
        entity_type="monster",
        template_id=f"monster_template:{template_id}" if template_id else "",
        base_stats=stat_result["base_stats"] if isinstance(stat_result.get("base_stats"), dict) else {},
        toughness_profile=stat_result["toughness_profile"] if isinstance(stat_result.get("toughness_profile"), dict) else {},
        weaknesses=tuple(str(item) for item in monster_row.get("StanceWeakList") or ()),
        resistances=_damage_type_resistances(monster_row.get("DamageTypeResistance")),
        source=source,
        status_resistance=_required_number(template_row, "StatusResistanceBase"),
        debuff_resistances=tuple(_json_safe(item) for item in monster_row.get("DebuffResist") or ()),
        coverage_status="blocked" if blocked_reason else "executable",
        blocked_reason=blocked_reason,
    )


def _compatible_action_definitions_for_combatant_action_set(
    entity_type: str,
    definitions: tuple[ActionDefinitionIR, ...] | list[ActionDefinitionIR],
) -> tuple[ActionDefinitionIR, ...]:
    if entity_type == "monster":
        return tuple(
            definition
            for definition in definitions
            if definition.source.source_path
            in {
                "ExcelOutput/MonsterSkillConfig.json",
                "ExcelOutput/MonsterSkillUniqueConfig.json",
            }
        )
    if entity_type == "servant":
        return tuple(
            definition
            for definition in definitions
            if definition.source.source_path == "ExcelOutput/AvatarServantSkillConfig.json"
        )
    return tuple(definitions)


def _combatant_profile_from_template(
    template_id: str,
    template_row: dict[str, Any],
    *,
    source_path: str = "ExcelOutput/MonsterTemplateConfig.json",
    raw_type: str = "MonsterTemplateConfig",
) -> CombatantProfileIR:
    source = IRSource(
        source_path=source_path,
        raw_type=raw_type,
        raw_id=template_id,
        evidence={
            "entity_id": f"monster_template:{template_id}",
            "raw_paths": {
                "attack": "AttackBase",
                "defense": "DefenceBase",
                "hp": "HPBase",
                "speed": "SpeedBase",
                "stance": "StanceBase",
            },
        },
    )
    stat_result = _monster_template_profile_stats(template_row)
    blocked_reason = stat_result.get("blocked_reason", "")
    return CombatantProfileIR(
        profile_id=f"combatant_profile:monster_template:{template_id}",
        entity_id=f"monster_template:{template_id}",
        entity_type="monster_template",
        template_id=f"monster_template:{template_id}",
        base_stats=stat_result["base_stats"] if isinstance(stat_result.get("base_stats"), dict) else {},
        toughness_profile=stat_result["toughness_profile"] if isinstance(stat_result.get("toughness_profile"), dict) else {},
        weaknesses=(),
        resistances={},
        source=source,
        status_resistance=_required_number(template_row, "StatusResistanceBase"),
        debuff_resistances=(),
        coverage_status="blocked" if blocked_reason else "lowered",
        blocked_reason=blocked_reason or "monster_template_profile_lacks_monster_weakness_and_resistance",
    )


def _monster_profile_stats(monster_row: dict[str, Any], template_row: dict[str, Any]) -> dict[str, Any]:
    template_stats = _monster_template_profile_stats(template_row)
    if template_stats.get("blocked_reason"):
        return template_stats
    required_ratios = {
        "attack": ("AttackModifyRatio", "attack"),
        "defense": ("DefenceModifyRatio", "defense"),
        "max_hp": ("HPModifyRatio", "max_hp"),
        "speed": ("SpeedModifyRatio", "speed"),
        "max_toughness": ("StanceModifyRatio", "max_toughness"),
    }
    missing = [key for key, _ in required_ratios.values() if _required_number(monster_row, key) is None]
    if missing:
        return {"blocked_reason": f"monster_modify_ratio_missing:{','.join(missing)}"}
    base_stats = dict(template_stats["base_stats"])
    toughness_profile = dict(template_stats["toughness_profile"])
    for stat_name, (ratio_key, source_stat) in required_ratios.items():
        ratio = _required_number(monster_row, ratio_key)
        if ratio is None:
            continue
        if stat_name == "max_toughness":
            base_value = float(toughness_profile.get(source_stat, 0.0))
            toughness_profile[stat_name] = base_value * ratio
            toughness_profile["current_toughness"] = toughness_profile[stat_name]
            toughness_profile["stance_modify_ratio"] = ratio
        else:
            base_stats[stat_name] = float(base_stats.get(source_stat, 0.0)) * ratio
    return {
        "base_stats": base_stats,
        "toughness_profile": toughness_profile,
        "blocked_reason": "",
    }


def _monster_template_profile_stats(template_row: dict[str, Any]) -> dict[str, Any]:
    required = {
        "attack": "AttackBase",
        "defense": "DefenceBase",
        "max_hp": "HPBase",
        "speed": "SpeedBase",
        "max_toughness": "StanceBase",
    }
    missing = [key for key in required.values() if _required_number(template_row, key) is None]
    if missing:
        return {"blocked_reason": f"monster_template_base_stat_missing:{','.join(missing)}"}
    base_stats = {
        "attack": _required_number(template_row, "AttackBase") or 0.0,
        "defense": _required_number(template_row, "DefenceBase") or 0.0,
        "max_hp": _required_number(template_row, "HPBase") or 0.0,
        "speed": _required_number(template_row, "SpeedBase") or 0.0,
    }
    max_toughness = _required_number(template_row, "StanceBase") or 0.0
    return {
        "base_stats": base_stats,
        "toughness_profile": {
            "max_toughness": max_toughness,
            "current_toughness": max_toughness,
            "stance_base": max_toughness,
            "stance_type": str(template_row.get("StanceType") or ""),
        },
        "blocked_reason": "",
    }


def _damage_type_resistances(value: Any) -> dict[str, Any]:
    if not isinstance(value, list):
        return {}
    result: dict[str, Any] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        damage_type = item.get("DamageType")
        if not isinstance(damage_type, str) or not damage_type:
            continue
        resistance = _required_number(item, "Value")
        if resistance is not None:
            result[damage_type] = resistance
    return result


def _blocked_combatant_profile(
    *,
    profile_id: str,
    entity_id: str,
    entity_type: str,
    template_id: str,
    source: IRSource,
    reason: str,
) -> CombatantProfileIR:
    return CombatantProfileIR(
        profile_id=profile_id,
        entity_id=entity_id,
        entity_type=entity_type,
        template_id=template_id,
        base_stats={},
        toughness_profile={},
        weaknesses=(),
        resistances={},
        source=source,
        status_resistance=None,
        debuff_resistances=(),
        coverage_status="blocked",
        blocked_reason=reason,
    )


def _action_definition_from_row(
    relative_path: str,
    entity_type: str,
    id_key: str,
    row_index: int,
    row: dict[str, Any],
    *,
    monster_target_source: dict[str, Any] | None = None,
) -> ActionDefinitionIR:
    raw_id = str(row[id_key])
    action_id = f"{entity_type}:{raw_id}"
    level = int(_number_value(row.get("Level"), 1.0))
    monster_target_mode = str((monster_target_source or {}).get("target_mode") or "")
    skill_effect = (
        _skill_effect_from_target_mode(monster_target_mode)
        if entity_type == "monster_skill"
        else str(row.get("SkillEffect") or row.get("AttackType") or "Unknown")
    )
    attack_type = str(row.get("AttackType") or "Unknown")
    element_type = (
        str(row["StanceDamageType"])
        if row.get("StanceDamageType") is not None
        else str(row["DamageType"])
        if row.get("DamageType") is not None
        else None
    )
    target_mode = monster_target_mode or _target_mode(skill_effect)
    source_mode = "mainline_monster" if entity_type == "monster_skill" else _source_mode(attack_type)
    source = IRSource(
        source_path=relative_path,
        raw_type=Path(relative_path).stem,
        raw_id=raw_id,
        evidence={
            "row_index": row_index,
            "id_key": id_key,
            "level": level,
            "skill_desc_hash": _hash_ref(row.get("SkillDesc")),
            "skill_trigger_key": str(row.get("SkillTriggerKey") or ""),
            "damage_type": str(row.get("DamageType") or ""),
            "sp_hit_base": _json_safe(row.get("SPHitBase")),
            "monster_target_source": _json_safe(monster_target_source or {}),
            "resource_mapping": {
                "BPNeed": "skill_point_cost_if_positive",
                "BPAdd": "skill_point_gain_if_positive",
                "SPBase": "energy_gain",
            },
            "taxonomy": {
                "attack_type": "raw TBGD AttackType; follow-up is an attack type axis",
                "damage_formula_family": "formula family axis; follow-up is not a damage family",
                "element_type": "raw TBGD StanceDamageType when present",
            },
        },
    )
    return ActionDefinitionIR(
        definition_id=f"action_def:{action_id}:{level}",
        action_id=action_id,
        level=level,
        attack_type=attack_type,
        skill_effect=skill_effect,
        target_mode=target_mode,
        bp_need=_number_value(row.get("BPNeed"), 0.0),
        bp_add=_number_value(row.get("BPAdd"), 0.0),
        sp_base=_number_value(row.get("SPBase"), 0.0),
        sp_multiple_ratio=_number_value(row.get("SPMultipleRatio"), 0.0),
        param_list=tuple(_list_json_values(row.get("ParamList"))),
        show_stance_list=tuple(_list_json_values(row.get("ShowStanceList"))),
        show_damage_list=tuple(_list_json_values(row.get("ShowDamageList"))),
        stance_damage_type=element_type,
        source=source,
        coverage_status="executable",
        damage_kind=_damage_kind(skill_effect),
        damage_formula_family=_damage_formula_family(attack_type, skill_effect),
        element_type=element_type,
        source_mode=source_mode,
    )


def _hash_ref(value: Any) -> str:
    if isinstance(value, dict) and value.get("Hash") is not None:
        return str(value["Hash"])
    return ""


def _blocked_action_binding(
    definition: ActionDefinitionIR,
    reason: str,
    source_path: str = "",
) -> tuple[ActionAbilityBindingIR, list[AbilityPhaseIR], _LoweredAbility]:
    source = IRSource(
        source_path=source_path or definition.source.source_path,
        raw_type="ActionAbilityBinding",
        raw_id=f"{definition.action_id}:{definition.level}",
        evidence={
            "action_id": definition.action_id,
            "level": definition.level,
            "definition_source": definition.source.to_json(),
            "blocked_reason": reason,
        },
    )
    source_mode = "mainline_avatar_blocked" if definition.action_id.startswith("avatar_skill:") else "non_avatar_blocked"
    return (
        ActionAbilityBindingIR(
            binding_id=f"action_binding:{definition.action_id}:{definition.level}",
            action_id=definition.action_id,
            level=definition.level,
            skill_trigger_key=str(definition.source.evidence.get("skill_trigger_key") or ""),
            skill_name="",
            entry_ability="",
            ability_names=(),
            config_source={},
            phase_ids=(),
            source_mode=source_mode,
            source=source,
            coverage_status="blocked",
            blocked_reason=reason,
        ),
        [],
        _LoweredAbility(),
    )


def _skill_config_by_name(character_config: dict[str, Any], skill_trigger_key: str) -> dict[str, Any] | None:
    skill_list = character_config.get("SkillList")
    if isinstance(skill_list, list):
        for item in skill_list:
            if not isinstance(item, dict):
                continue
            names = {
                str(item.get("Name") or ""),
                str(item.get("SkillName") or ""),
                str(item.get("Skill") or ""),
                str(item.get("SkillTriggerKey") or ""),
            }
            if skill_trigger_key in names:
                return item
    if isinstance(skill_list, dict):
        item = skill_list.get(skill_trigger_key)
        if isinstance(item, dict):
            return item
        for key, value in skill_list.items():
            if str(key) == skill_trigger_key and isinstance(value, dict):
                return value
    return None


def _ability_names_for_skill(
    character_config: dict[str, Any],
    skill_trigger_key: str,
    entry_ability: str,
) -> list[str]:
    ability_names: list[str] = []
    if entry_ability:
        ability_names.append(entry_ability)
    skill_ability_list = character_config.get("SkillAbilityList")
    matched: Any = None
    if isinstance(skill_ability_list, dict):
        matched = skill_ability_list.get(skill_trigger_key)
        if matched is None:
            for key, value in skill_ability_list.items():
                if str(key) == skill_trigger_key:
                    matched = value
                    break
    elif isinstance(skill_ability_list, list):
        for item in skill_ability_list:
            if not isinstance(item, dict):
                continue
            names = {
                str(item.get("Name") or ""),
                str(item.get("SkillName") or ""),
                str(item.get("Skill") or ""),
                str(item.get("SkillTriggerKey") or ""),
            }
            if skill_trigger_key in names:
                matched = item
                break
    ability_names.extend(_ability_names_from_value(matched))
    return list(dict.fromkeys(name for name in ability_names if name))


def _expand_triggered_ability_names(
    ability_names: list[str],
    ability_map: dict[str, dict[str, Any]],
    *,
    max_depth: int = 3,
) -> list[str]:
    expanded: list[str] = []
    seen: set[str] = set()
    queue: list[tuple[str, int]] = [(name, 0) for name in ability_names]
    while queue:
        ability_name, depth = queue.pop(0)
        if not ability_name or ability_name in seen:
            continue
        seen.add(ability_name)
        expanded.append(ability_name)
        if depth >= max_depth:
            continue
        ability = ability_map.get(ability_name)
        if not isinstance(ability, dict):
            continue
        for child_name in _trigger_ability_names_from_value(ability):
            if child_name in ability_map and child_name not in seen:
                queue.append((child_name, depth + 1))
    return expanded


def _trigger_ability_names_from_value(value: Any) -> list[str]:
    names: list[str] = []
    if isinstance(value, list):
        for item in value:
            names.extend(_trigger_ability_names_from_value(item))
    elif isinstance(value, dict):
        raw_type = str(value.get("$type") or "")
        if raw_type.endswith("TriggerAbility"):
            ability_name = value.get("AbilityName")
            if isinstance(ability_name, dict) and isinstance(ability_name.get("Value"), str):
                names.append(str(ability_name["Value"]))
            elif isinstance(ability_name, str):
                names.append(ability_name)
        for item in value.values():
            names.extend(_trigger_ability_names_from_value(item))
    return list(dict.fromkeys(name for name in names if name))


def _ability_names_from_value(value: Any) -> list[str]:
    names: list[str] = []
    if isinstance(value, str):
        names.append(value)
    elif isinstance(value, list):
        for item in value:
            names.extend(_ability_names_from_value(item))
    elif isinstance(value, dict):
        for key in ("AbilityName", "Name", "PhaseAbility", "PhaseAbilityName", "EntryAbility"):
            item = value.get(key)
            if isinstance(item, str):
                names.append(item)
        for key in ("AbilityList", "AbilityNameList", "PhaseList", "PhaseAbilityList"):
            names.extend(_ability_names_from_value(value.get(key)))
        if not names:
            for item in value.values():
                names.extend(_ability_names_from_value(item))
    return names


def _resolve_monster_ability_paths(
    ability_names: list[str],
    ability_file_index: dict[str, tuple[str, ...]],
) -> tuple[dict[str, str], list[str], dict[str, list[str]]]:
    resolved: dict[str, str] = {}
    missing: list[str] = []
    ambiguous: dict[str, list[str]] = {}
    for ability_name in ability_names:
        paths = tuple(ability_file_index.get(ability_name, ()))
        if not paths:
            missing.append(ability_name)
            continue
        if len(paths) > 1:
            ambiguous[ability_name] = list(paths)
            continue
        resolved[ability_name] = paths[0]
    return resolved, missing, ambiguous


def _avatar_ability_path_from_character_path(character_path: str) -> str:
    path = Path(character_path)
    name = path.name
    if name.endswith("_Config.json"):
        ability_name = name.replace("_Config.json", "_Ability.json")
    else:
        ability_name = f"{path.stem}_Ability.json"
    if "Advanced" in path.parts:
        return f"Config/ConfigAbility/Avatar/Advanced/{ability_name}"
    return f"Config/ConfigAbility/Avatar/{ability_name}"


def _servant_ability_path_from_character_path(character_path: str) -> str:
    path = Path(character_path)
    name = path.name
    if name.endswith("_Config.json"):
        ability_name = name.replace("_Config.json", "_Ability.json")
    else:
        ability_name = f"{path.stem}_Ability.json"
    return f"Config/ConfigAbility/Servant/{ability_name}"


def _servant_action_set_admission(
    servant_ref: str,
    action_set: CombatantActionSetIR | None,
    bindings_by_action: dict[tuple[str, int], ActionAbilityBindingIR],
) -> tuple[dict[str, Any], list[str]]:
    if action_set is None:
        return (
            {
                "admission_status": "blocked",
                "coverage_status": "blocked",
                "blocked_reason": "servant_action_set_missing",
                "entity_ref": servant_ref,
                "skill_index_map": {},
                "executable_binding_ids": [],
                "source_trace": [],
            },
            [],
        )
    source_trace = [action_set.source.to_json()]
    executable_binding_ids: list[str] = []
    skipped_slots: list[dict[str, Any]] = []
    blocking_reasons: list[str] = []
    skill_index_map = _json_safe(action_set.skill_index_map)
    for slot, entry in sorted(action_set.skill_index_map.items()):
        if not isinstance(entry, dict):
            skipped_slots.append({"slot": slot, "blocked_reason": "servant_action_slot_not_structured"})
            continue
        if entry.get("coverage_status") != "executable":
            reason = str(entry.get("blocked_reason") or "servant_action_slot_blocked")
            skipped_slots.append({"slot": slot, "blocked_reason": reason})
            continue
        action_ref = str(entry.get("action_ref") or "")
        level = _optional_int(entry.get("default_level"))
        if not action_ref or level is None:
            skipped_slots.append({"slot": slot, "blocked_reason": "servant_action_ref_or_level_missing"})
            continue
        binding = bindings_by_action.get((action_ref, level))
        if binding is None:
            skipped_slots.append({"slot": slot, "action_ref": action_ref, "level": level, "blocked_reason": "servant_action_binding_missing"})
            continue
        source_trace.append(binding.source.to_json())
        if binding.coverage_status != "executable":
            skipped_slots.append(
                {
                    "slot": slot,
                    "action_ref": action_ref,
                    "level": level,
                    "binding_id": binding.binding_id,
                    "blocked_reason": binding.blocked_reason or "servant_action_binding_blocked",
                }
            )
            continue
        executable_binding_ids.append(binding.binding_id)
    if action_set.coverage_status != "executable":
        blocking_reasons.append(action_set.blocked_reason or "servant_combatant_action_set_blocked")
    if not executable_binding_ids:
        blocking_reasons.append("servant_has_no_executable_action_binding")
    blocked_reason = ";".join(dict.fromkeys(reason for reason in blocking_reasons if reason))
    status = "blocked" if blocked_reason else "executable"
    return (
        {
            "admission_status": status,
            "coverage_status": status,
            "blocked_reason": blocked_reason,
            "combatant_action_set_id": action_set.combatant_action_set_id,
            "entity_ref": action_set.entity_ref,
            "skill_index_map": skill_index_map,
            "executable_binding_ids": executable_binding_ids,
            "skipped_slots": _json_safe(skipped_slots),
            "source_trace": source_trace,
        },
        executable_binding_ids,
    )


def _servant_stat_source(
    row: dict[str, Any],
    stat_skill_rows: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    hp_skill = str(row.get("HPSkill") or "")
    speed_skill = str(row.get("SpeedSkill") or "")
    hp_base = _servant_stat_component(row.get("HPBase"), hp_skill, stat_skill_rows, "HPBase")
    hp_inherit = _servant_stat_component(row.get("HPInherit"), hp_skill, stat_skill_rows, "HPInherit")
    speed_base = _servant_stat_component(row.get("SpeedBase"), speed_skill, stat_skill_rows, "SpeedBase")
    speed_inherit = _servant_stat_component(row.get("SpeedInherit"), speed_skill, stat_skill_rows, "SpeedInherit")
    components = {
        "hp_base": hp_base,
        "hp_inherit": hp_inherit,
        "speed_base": speed_base,
        "speed_inherit": speed_inherit,
    }
    for component_key, field_name in (
        ("hp_base", "HPBase"),
        ("hp_inherit", "HPInherit"),
        ("speed_base", "SpeedBase"),
        ("speed_inherit", "SpeedInherit"),
    ):
        component = components[component_key]
        if not component.get("source_trace"):
            component["source_trace"] = [_servant_config_stat_field_source(row, field_name)]
    blocking_reasons = [
        str(component.get("blocked_reason") or "")
        for component in components.values()
        if component.get("admission_status") != "executable"
    ]
    blocked_reason = ";".join(dict.fromkeys(reason for reason in blocking_reasons if reason))
    status = "blocked" if blocked_reason else "executable"
    return {
        "admission_status": status,
        "coverage_status": status,
        "blocked_reason": blocked_reason,
        "hp_skill": hp_skill,
        "speed_skill": speed_skill,
        "components": components,
        "formula": {
            "max_hp": "owner.max_hp * hp_inherit + hp_base",
            "speed": "owner.speed * speed_inherit + speed_base",
        },
        "runtime_required_owner_fields": ["max_hp", "speed"],
        "schema_carry_fields": {
            "attack": {
                "source_status": "schema_carry_only",
                "note": "keeps UnitState schema usable; servant damage stat admission is not declared here",
            },
            "defense": {
                "source_status": "schema_carry_only",
                "note": "keeps UnitState schema usable; servant damage stat admission is not declared here",
            },
        },
        "source_trace": _servant_component_source_trace(components),
    }


def _servant_stat_component(
    raw_value: Any,
    skill_id: str,
    stat_skill_rows: dict[str, dict[str, Any]],
    field_name: str,
) -> dict[str, Any]:
    direct = _servant_direct_number(raw_value)
    if direct is not None:
        return {
            "admission_status": "executable",
            "source_kind": "literal",
            "raw": _json_safe(raw_value),
            "value": direct,
            "source_trace": [],
        }
    if isinstance(raw_value, dict):
        return _servant_stat_component(raw_value.get("Value"), skill_id, stat_skill_rows, field_name)
    if not isinstance(raw_value, str) or not raw_value.startswith("#"):
        return {
            "admission_status": "blocked",
            "source_kind": "unsupported",
            "raw": _json_safe(raw_value),
            "value": None,
            "blocked_reason": f"servant_{field_name}_unsupported_value",
            "source_trace": [],
        }
    index_raw = raw_value[1:]
    if not index_raw.isdigit():
        return {
            "admission_status": "blocked",
            "source_kind": "param_ref",
            "raw": raw_value,
            "value": None,
            "blocked_reason": f"servant_{field_name}_invalid_param_ref",
            "source_trace": [],
        }
    if not skill_id:
        return {
            "admission_status": "blocked",
            "source_kind": "param_ref",
            "raw": raw_value,
            "value": None,
            "blocked_reason": f"servant_{field_name}_param_skill_missing",
            "source_trace": [],
        }
    skill_row = stat_skill_rows.get(skill_id)
    if not isinstance(skill_row, dict):
        return {
            "admission_status": "blocked",
            "source_kind": "param_ref",
            "raw": raw_value,
            "value": None,
            "skill_id": skill_id,
            "blocked_reason": f"servant_{field_name}_param_skill_not_found",
            "source_trace": [],
        }
    param_index = int(index_raw) - 1
    params = skill_row.get("ParamList")
    if not isinstance(params, list) or param_index < 0 or param_index >= len(params):
        return {
            "admission_status": "blocked",
            "source_kind": "param_ref",
            "raw": raw_value,
            "value": None,
            "skill_id": skill_id,
            "param_index": param_index,
            "blocked_reason": f"servant_{field_name}_param_index_out_of_range",
            "source_trace": [_servant_skill_row_source(skill_id, skill_row)],
        }
    resolved = _servant_direct_number(params[param_index])
    if resolved is None:
        return {
            "admission_status": "blocked",
            "source_kind": "param_ref",
            "raw": raw_value,
            "value": None,
            "skill_id": skill_id,
            "param_index": param_index,
            "param_raw": _json_safe(params[param_index]),
            "blocked_reason": f"servant_{field_name}_param_value_not_numeric",
            "source_trace": [_servant_skill_row_source(skill_id, skill_row)],
        }
    return {
        "admission_status": "executable",
        "source_kind": "param_ref",
        "raw": raw_value,
        "value": resolved,
        "skill_id": skill_id,
        "param_index": param_index,
        "param_raw": _json_safe(params[param_index]),
        "source_trace": [_servant_skill_row_source(skill_id, skill_row)],
    }


def _servant_direct_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        return _servant_direct_number(value.get("Value"))
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("#") or not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _servant_skill_row_source(skill_id: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_path": str(row.get("_v8_source_path") or ""),
        "raw_type": "SkillConfig",
        "raw_id": skill_id,
        "evidence": {
            "row_index": _json_safe(row.get("_v8_row_index")),
            "level": _json_safe(row.get("Level")),
            "param_list": _json_safe(row.get("ParamList") or []),
        },
    }


def _servant_config_stat_field_source(row: dict[str, Any], field_name: str) -> dict[str, Any]:
    return {
        "source_path": str(row.get("_v8_source_path") or "ExcelOutput/AvatarServantConfig.json"),
        "raw_type": "AvatarServantConfig",
        "raw_id": str(row.get("ServantID") or ""),
        "evidence": {
            "row_index": _json_safe(row.get("_v8_row_index")),
            "field_name": field_name,
            "raw_value": _json_safe(row.get(field_name)),
        },
    }


def _servant_component_source_trace(components: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for component in components.values():
        for trace in component.get("source_trace") or []:
            if not isinstance(trace, dict):
                continue
            key = (str(trace.get("source_path") or ""), str(trace.get("raw_id") or ""))
            if key in seen:
                continue
            seen.add(key)
            traces.append(trace)
    return traces


def _servant_owner_entity_ref(
    row: dict[str, Any],
    avatar_configs_by_skill_id: dict[str, list[dict[str, Any]]],
) -> tuple[str, dict[str, Any]]:
    skill_ids = [str(value) for value in (row.get("HPSkill"), row.get("SpeedSkill")) if value]
    candidates: dict[str, list[dict[str, Any]]] = {}
    for skill_id in skill_ids:
        for config in avatar_configs_by_skill_id.get(skill_id, []):
            avatar_id = config.get("avatar_id")
            if avatar_id is None:
                continue
            candidates.setdefault(str(avatar_id), []).append(config)
    source = {
        "admission_status": "blocked",
        "blocked_reason": "",
        "skill_ids": skill_ids,
        "candidate_owner_entity_refs": [f"avatar:{avatar_id}" for avatar_id in sorted(candidates)],
        "source_trace": [],
    }
    for avatar_id, configs in sorted(candidates.items()):
        for config in configs:
            source["source_trace"].append(
                {
                    "source_path": str(config.get("relative_path") or ""),
                    "raw_type": "AvatarConfig",
                    "raw_id": avatar_id,
                    "evidence": {
                        "row_index": _json_safe(config.get("row_index")),
                        "skill_list": _json_safe(config.get("skill_list") or []),
                        "matched_stat_skill_ids": [
                            skill_id
                            for skill_id in skill_ids
                            if any(str(item) == skill_id for item in (config.get("skill_list") or []))
                        ],
                    },
                }
            )
    if not skill_ids:
        source["blocked_reason"] = "servant_owner_stat_skill_missing"
        return "", source
    if not candidates:
        source["blocked_reason"] = "servant_owner_avatar_config_not_found"
        return "", source
    if len(candidates) != 1:
        source["blocked_reason"] = "servant_owner_avatar_config_ambiguous"
        return "", source
    owner_id = next(iter(candidates))
    source["admission_status"] = "executable"
    source["blocked_reason"] = ""
    source["owner_entity_ref"] = f"avatar:{owner_id}"
    return f"avatar:{owner_id}", source


def _servant_timeline_source(row: dict[str, Any], stat_source: dict[str, Any]) -> dict[str, Any]:
    if stat_source.get("admission_status") != "executable":
        return {
            "admission_status": "blocked",
            "coverage_status": "blocked",
            "blocked_reason": "servant_timeline_stat_source_blocked",
            "source_trace": stat_source.get("source_trace") or [],
        }
    speed_components = {
        "speed_base": ((stat_source.get("components") or {}).get("speed_base") or {}),
        "speed_inherit": ((stat_source.get("components") or {}).get("speed_inherit") or {}),
    }
    return {
        "admission_status": "executable",
        "coverage_status": "executable",
        "blocked_reason": "",
        "formula": "timeline.action_value = 10000 / servant.speed",
        "speed_formula": "owner.speed * speed_inherit + speed_base",
        "speed_components": _json_safe(speed_components),
        "timeline_rule_source": "TimelineRuleIR.default_v8_timeline_rule",
        "source_trace": _servant_component_source_trace(speed_components),
    }


def _servant_lifecycle_source(row: dict[str, Any]) -> dict[str, Any]:
    servant_id = str(row.get("ServantID") or "")
    config_path = str(row.get("Config") or "")
    if not config_path:
        return {
            "admission_status": "blocked",
            "coverage_status": "blocked",
            "blocked_reason": "servant_lifecycle_config_missing",
            "source_trace": [],
        }
    return {
        "admission_status": "executable",
        "coverage_status": "executable",
        "blocked_reason": "",
        "summon_kind": "servant",
        "representation": "unit",
        "targetable": True,
        "team_side_policy": "inherit_owner_combat_team",
        "lifetime_policy": "permanent_until_removed_or_owner_removed",
        "owner_removed_policy": "remove",
        "source_trace": [
            {
                "source_path": "ExcelOutput/AvatarServantConfig.json",
                "raw_type": "AvatarServantConfig",
                "raw_id": servant_id,
                "evidence": {
                    "config_path": config_path,
                    "lifecycle_admission": "servant_unit_catalog",
                },
            }
        ],
    }


def _servant_definition_blocked_reason(
    *,
    owner_entity_ref: str,
    config_path: str,
    ability_path: str,
    ability_data: dict[str, Any] | None,
    action_set_status: str,
    stat_source: dict[str, Any],
    timeline_source: dict[str, Any],
    lifecycle_source: dict[str, Any],
) -> str:
    reasons: list[str] = []
    if not owner_entity_ref:
        owner_source = stat_source.get("owner_source") if isinstance(stat_source, dict) else None
        if isinstance(owner_source, dict) and owner_source.get("blocked_reason"):
            reasons.append(str(owner_source["blocked_reason"]))
        else:
            reasons.append("servant_owner_entity_ref_missing")
    if not config_path:
        reasons.append("servant_character_config_path_missing")
    if not ability_path or not isinstance(ability_data, dict):
        reasons.append("servant_ability_file_missing_or_unreadable")
    if action_set_status != "executable":
        reasons.append("servant_action_set_not_executable")
    for label, source in (
        ("stat", stat_source),
        ("timeline", timeline_source),
        ("lifecycle", lifecycle_source),
    ):
        if source.get("admission_status") != "executable":
            reasons.append(str(source.get("blocked_reason") or f"servant_{label}_source_blocked"))
    return ";".join(dict.fromkeys(reason for reason in reasons if reason))


def _ability_map(ability_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    ability_list = ability_data.get("AbilityList")
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(ability_list, list):
        return result
    for ability in ability_list:
        if not isinstance(ability, dict):
            continue
        name = ability.get("Name") or ability.get("AbilityName")
        if isinstance(name, str) and name:
            result[name] = ability
    return result


def _ability_opcode_summary(ability: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for opcode in _iter_gamecore_opcodes(ability):
        counts[opcode] = counts.get(opcode, 0) + 1
    return {
        "opcode_counts": dict(sorted(counts.items())),
        "task_count": sum(counts.values()),
        "raw_task_summary_only": True,
    }


def _ability_callback_summaries(ability: dict[str, Any]) -> dict[str, Any]:
    return {
        "on_start": _callback_summary(ability.get("OnStart")),
        "on_attack": _callback_summary(ability.get("OnAttack")),
        "on_hit": _callback_summary(ability.get("OnHit")),
        "on_end": _callback_summary(ability.get("OnEnd")),
    }


def _callback_summary(value: Any) -> dict[str, Any]:
    opcodes = _iter_gamecore_opcodes(value)
    counts: dict[str, int] = {}
    for opcode in opcodes:
        counts[opcode] = counts.get(opcode, 0) + 1
    return {"opcode_counts": dict(sorted(counts.items())), "task_count": len(opcodes)}


def _iter_gamecore_opcodes(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        raw_type = value.get("$type")
        if isinstance(raw_type, str):
            found.append(_short_gamecore_type(raw_type))
        for nested in value.values():
            found.extend(_iter_gamecore_opcodes(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_iter_gamecore_opcodes(nested))
    return found


def _binding_blocked_reason(
    binding: ActionAbilityBindingIR | None,
    phases: tuple[AbilityPhaseIR, ...],
) -> str:
    if binding is None:
        return "action_ability_binding_missing"
    if binding.coverage_status != "executable":
        return binding.blocked_reason or f"action_ability_binding_{binding.coverage_status}"
    if not phases:
        return "ability_phase_graph_missing"
    return ""


def _lower_action_execution_ir(
    definitions: list[ActionDefinitionIR],
    bindings: list[ActionAbilityBindingIR],
    phases: list[AbilityPhaseIR],
    skill_formula_bindings: list[SkillFormulaBindingIR],
    bounce_policies: list[BouncePolicyIR],
) -> tuple[list[ActionEventIR], list[HitProfileIR]]:
    binding_by_action = {(binding.action_id, binding.level): binding for binding in bindings}
    formula_bindings_by_action: dict[tuple[str, int], list[SkillFormulaBindingIR]] = {}
    for formula_binding in skill_formula_bindings:
        formula_bindings_by_action.setdefault((formula_binding.action_id, formula_binding.level), []).append(formula_binding)
    bounce_policy_by_action = {(policy.action_id, policy.level): policy for policy in bounce_policies}
    phases_by_binding: dict[str, list[AbilityPhaseIR]] = {}
    for phase in phases:
        phases_by_binding.setdefault(phase.binding_id, []).append(phase)
    events: list[ActionEventIR] = []
    profiles: list[HitProfileIR] = []
    for definition in definitions:
        action_profiles = _hit_profiles_from_definition(
            definition,
            tuple(formula_bindings_by_action.get((definition.action_id, definition.level), ())),
            bounce_policy_by_action.get((definition.action_id, definition.level)),
        )
        profiles.extend(action_profiles)
        binding = binding_by_action.get((definition.action_id, definition.level))
        binding_phases = tuple(sorted(
            phases_by_binding.get(binding.binding_id if binding else "", []),
            key=lambda phase: (phase.phase_index, phase.phase_id),
        ))
        events.append(_action_event_from_definition(definition, action_profiles, binding, binding_phases))
    return events, profiles


def _lower_damage_emissions(
    tasks: list[AbilityTaskIR],
    effects: list[EffectIR],
    hit_profiles: list[HitProfileIR],
    skill_formula_bindings: list[SkillFormulaBindingIR],
) -> list[DamageEmissionIR]:
    effect_by_id = {effect.effect_id: effect for effect in effects}
    direct_basis_bindings = _direct_damage_binding_lookup(skill_formula_bindings)
    profiles_by_action: dict[tuple[str, int], list[HitProfileIR]] = {}
    tasks_by_action: dict[tuple[str, int], list[AbilityTaskIR]] = {}
    for profile in hit_profiles:
        profiles_by_action.setdefault((profile.action_id, profile.level), []).append(profile)
    for task in tasks:
        if task.opcode in DAMAGE_EMISSION_OPCODES:
            tasks_by_action.setdefault((task.action_id, task.level), []).append(task)

    emissions: list[DamageEmissionIR] = []
    for action_key, action_tasks in tasks_by_action.items():
        action_profiles = tuple(sorted(
            profiles_by_action.get(action_key, ()),
            key=lambda profile: (profile.hit_index, profile.target_group, profile.hit_profile_id),
        ))
        for task in sorted(action_tasks, key=lambda item: (item.phase_id, item.callback_kind, item.task_path, item.task_id)):
            effect = effect_by_id.get(task.effect_id)
            target_profiles = _target_profiles_for_damage_task(action_profiles, task)
            for profile in target_profiles:
                scaling_basis_expr = _damage_scaling_basis_expr(task, effect, profile, direct_basis_bindings)
                blocked_reason = _damage_emission_blocked_reason(task, effect, profile, scaling_basis_expr)
                source = _damage_emission_source(task, effect, profile)
                emissions.append(
                    DamageEmissionIR(
                        damage_emission_id=_damage_emission_id(task, profile),
                        action_id=task.action_id,
                        level=task.level,
                        phase_id=task.phase_id,
                        source_task_id=task.task_id,
                        hit_profile_id=profile.hit_profile_id if profile else "",
                        target_group=profile.target_group if profile else "unknown",
                        damage_formula_family=profile.damage_formula_family if profile else "unknown",
                        element_type=profile.element_type if profile else None,
                        scaling_ratio_expr=profile.multiplier_expr if profile else {"kind": "missing", "blocked_reason": "missing_hit_profile"},
                        scaling_basis_expr=scaling_basis_expr,
                        source=source,
                        coverage_status="blocked" if blocked_reason else "executable",
                        blocked_reason=blocked_reason,
                    )
                )
    return emissions


def _attach_status_formula_bindings_to_add_modifier_effects(
    effects: list[EffectIR],
    tasks: list[AbilityTaskIR],
    skill_formula_bindings: list[SkillFormulaBindingIR],
) -> list[EffectIR]:
    dot_bindings_by_action: dict[tuple[str, int], list[SkillFormulaBindingIR]] = {}
    for binding in skill_formula_bindings:
        if binding.formula_role != "dot_damage":
            continue
        if binding.coverage_status != "executable":
            continue
        dot_bindings_by_action.setdefault((binding.action_id, binding.level), []).append(binding)
    if not dot_bindings_by_action:
        return effects

    task_by_effect_id = {task.effect_id: task for task in tasks if task.effect_id}
    updated: list[EffectIR] = []
    for effect in effects:
        if effect.opcode != "AddModifier":
            updated.append(effect)
            continue
        task = task_by_effect_id.get(effect.effect_id)
        if task is None:
            updated.append(effect)
            continue
        bindings = tuple(sorted(
            dot_bindings_by_action.get((task.action_id, task.level), ()),
            key=lambda item: (item.sequence_order, item.param_index, item.binding_id),
        ))
        if not bindings:
            updated.append(effect)
            continue
        payload = dict(effect.payload)
        standard = dict(payload.get("standard")) if isinstance(payload.get("standard"), dict) else {}
        standard["status_formula_bindings"] = [binding.to_json() for binding in bindings]
        standard["status_formula_binding_source"] = {
            "source_kind": "character_data_card_status_formula_slots",
            "action_id": task.action_id,
            "action_level": task.level,
            "task_id": task.task_id,
            "binding_count": len(bindings),
        }
        payload["standard"] = standard
        updated.append(
            EffectIR(
                effect_id=effect.effect_id,
                opcode=effect.opcode,
                payload=payload,
                source=effect.source,
                coverage_status=effect.coverage_status,
            )
        )
    return updated


def _lower_toughness_emissions(
    tasks: list[AbilityTaskIR],
    effects: list[EffectIR],
    hit_profiles: list[HitProfileIR],
) -> list[ToughnessEmissionIR]:
    effect_by_id = {effect.effect_id: effect for effect in effects}
    profiles_by_action: dict[tuple[str, int], list[HitProfileIR]] = {}
    tasks_by_action: dict[tuple[str, int], list[AbilityTaskIR]] = {}
    for profile in hit_profiles:
        profiles_by_action.setdefault((profile.action_id, profile.level), []).append(profile)
    for task in tasks:
        if task.opcode in DAMAGE_EMISSION_OPCODES:
            tasks_by_action.setdefault((task.action_id, task.level), []).append(task)

    emissions: list[ToughnessEmissionIR] = []
    for action_key, action_tasks in tasks_by_action.items():
        action_profiles = tuple(sorted(
            profiles_by_action.get(action_key, ()),
            key=lambda profile: (profile.hit_index, profile.target_group, profile.hit_profile_id),
        ))
        for task in sorted(action_tasks, key=lambda item: (item.phase_id, item.callback_kind, item.task_path, item.task_id)):
            effect = effect_by_id.get(task.effect_id)
            target_profiles = _target_profiles_for_damage_task(action_profiles, task)
            for profile in target_profiles:
                blocked_reason = _toughness_emission_blocked_reason(task, effect, profile)
                emissions.append(
                    ToughnessEmissionIR(
                        toughness_emission_id=_toughness_emission_id(task, profile),
                        action_id=task.action_id,
                        level=task.level,
                        phase_id=task.phase_id,
                        source_task_id=task.task_id,
                        hit_profile_id=profile.hit_profile_id if profile else "",
                        target_group=profile.target_group if profile else "unknown",
                        element_type=profile.element_type if profile else None,
                        toughness_amount_expr=_toughness_amount_expr(effect, profile),
                        source=_toughness_emission_source(task, effect, profile),
                        coverage_status="blocked" if blocked_reason else "executable",
                        blocked_reason=blocked_reason,
                    )
                )
    return emissions


def _target_profiles_for_damage_task(
    action_profiles: tuple[HitProfileIR, ...],
    task: AbilityTaskIR,
) -> tuple[HitProfileIR | None, ...]:
    if not action_profiles:
        return (None,)
    task_scoped_profiles = tuple(
        profile
        for profile in action_profiles
        if isinstance(profile.target_selection_policy, dict)
        and bool(profile.target_selection_policy.get("task_id"))
    )
    if not task_scoped_profiles:
        return action_profiles
    matching = tuple(
        profile
        for profile in task_scoped_profiles
        if profile.target_selection_policy.get("task_id") == task.task_id
    )
    return matching or (None,)


def _lower_standalone_hit_profiles(
    tasks: list[AbilityTaskIR],
    effects: list[EffectIR],
    skill_formula_bindings: list[SkillFormulaBindingIR],
) -> list[HitProfileIR]:
    effect_by_id = {effect.effect_id: effect for effect in effects}
    bindings_by_action: dict[tuple[str, int], list[SkillFormulaBindingIR]] = {}
    for binding in skill_formula_bindings:
        if binding.formula_role != "direct_damage":
            continue
        if not binding.action_id.startswith("standalone_ability:"):
            continue
        bindings_by_action.setdefault((binding.action_id, binding.level), []).append(binding)
    profiles: list[HitProfileIR] = []
    for task in sorted(tasks, key=lambda item: (item.action_id, item.phase_id, item.callback_kind, item.task_path, item.task_id)):
        if task.opcode != "DamageByAttackProperty":
            continue
        effect = effect_by_id.get(task.effect_id)
        payload = effect.payload if effect is not None else {}
        target_alias = _target_alias(payload.get("TargetType")) if isinstance(payload, dict) else None
        target_group = _standalone_target_group(target_alias)
        binding = _standalone_binding_for_damage_task(
            tuple(bindings_by_action.get((task.action_id, task.level), ())),
            effect,
        )
        blocked_reason = ""
        if target_group == "unknown":
            blocked_reason = f"standalone_damage_target_alias_not_admitted:{target_alias or 'missing'}"
        elif binding is None:
            blocked_reason = "standalone_damage_skill_formula_binding_missing"
        elif binding.coverage_status != "executable":
            blocked_reason = binding.blocked_reason or f"skill_formula_binding_not_executable:{binding.coverage_status}"
        multiplier_expr = _binding_param_multiplier_expr(binding, effect) if binding is not None else {"kind": "missing", "blocked_reason": "standalone_damage_skill_formula_binding_missing"}
        profiles.append(
            HitProfileIR(
                hit_profile_id=(
                    f"hit_profile:{task.action_id}:{task.level}:"
                    f"{len(profiles)}:{target_group}:task:{_safe_id(task.task_path)}"
                ),
                action_id=task.action_id,
                level=task.level,
                hit_index=len(profiles),
                target_group=target_group,
                multiplier_expr=multiplier_expr,
                multiplier_source=_standalone_multiplier_source(task, effect, binding),
                stance_expr={"kind": "missing", "blocked_reason": "standalone_show_stance_not_present"},
                stance_source={"source_kind": "standalone_ability_damage_task", "task_source": task.source.to_json()},
                damage_formula_family="direct",
                element_type=_attack_property_element_type(payload.get("AttackProperty")) if isinstance(payload.get("AttackProperty"), dict) else None,
                source=binding.source if binding is not None else task.source,
                coverage_status="blocked" if blocked_reason else "executable",
                blocked_reason=blocked_reason,
                numeric_fidelity_status="trusted_for_current_scope" if not blocked_reason else "blocked",
                target_selection_policy={
                    "target_alias": target_alias or "",
                    "source_kind": "standalone_ability_damage_task",
                    "task_id": task.task_id,
                },
            )
        )
    return profiles


def _standalone_target_group(target_alias: str | None) -> str:
    if target_alias in {"AbilityTargetEntity", "CurrentActionTarget"}:
        return "selected"
    if target_alias == "AllEnemy":
        return "selected"
    return "unknown"


def _standalone_binding_for_damage_task(
    bindings: tuple[SkillFormulaBindingIR, ...],
    effect: EffectIR | None,
) -> SkillFormulaBindingIR | None:
    if not bindings:
        return None
    effect_hash = _damage_percentage_dynamic_hash(effect)
    candidates = tuple(binding for binding in bindings if str(binding.scaling_basis_expr.get("dynamic_hash")) == str(effect_hash))
    if candidates:
        return sorted(candidates, key=lambda item: item.binding_id)[0]
    return sorted(bindings, key=lambda item: item.binding_id)[0] if effect_hash is None and len(bindings) == 1 else None


def _binding_param_multiplier_expr(binding: SkillFormulaBindingIR | None, effect: EffectIR | None = None) -> dict[str, Any]:
    if binding is None:
        return {"kind": "missing", "blocked_reason": "skill_formula_binding_missing"}
    value = _value_field(binding.param_value)
    attack_property = effect.payload.get("AttackProperty") if effect is not None and isinstance(effect.payload, dict) else None
    damage_percentage = attack_property.get("DamagePercentage") if isinstance(attack_property, dict) else None
    expr = _numeric_expr_summary(damage_percentage)
    dynamic_hash = _damage_percentage_dynamic_hash(effect)
    if expr.get("kind") in {"dynamic_hash", "postfix_expr"} and dynamic_hash is not None and isinstance(value, (int, float)):
        expr = dict(expr)
        expr["binding_source"] = _skill_formula_binding_runtime_source(binding, dynamic_hash, float(value))
        expr["source_kind"] = "monster_damage_percentage_expr_with_skill_param_binding"
        return expr
    if isinstance(value, (int, float)):
        return {"kind": "fixed", "value": float(value)}
    return {"kind": "missing", "blocked_reason": "skill_formula_binding_param_value_not_numeric"}


def _skill_formula_binding_runtime_source(
    binding: SkillFormulaBindingIR,
    dynamic_hash: str,
    value: float,
) -> dict[str, Any]:
    entry_key = f"skill_formula_binding:{binding.binding_id}"
    entry = {
        "scope": "skill_formula_binding",
        "owner_id": binding.owner_entity_ref,
        "status_id": None,
        "status_instance_id": None,
        "effect_id": None,
        "name": None,
        "hash": str(dynamic_hash),
        "value": float(value),
        "source_trace": binding.source.to_json(),
    }
    return {
        "source_type": "skill_formula_binding",
        "entries": {entry_key: entry},
        "by_hash": {str(dynamic_hash): entry_key},
        "by_name": {},
    }


def _standalone_multiplier_source(
    task: AbilityTaskIR,
    effect: EffectIR | None,
    binding: SkillFormulaBindingIR | None,
) -> dict[str, Any]:
    source = {
        "source_kind": _skill_formula_source_kind(binding) if binding else "standalone_ability_missing_formula_binding",
        "task_id": task.task_id,
        "task_source": task.source.to_json(),
        "effect_id": effect.effect_id if effect is not None else "",
        "effect_source": effect.source.to_json() if effect is not None else {},
    }
    if binding is not None:
        source.update(
            {
                "raw_path": f"ParamList[{binding.param_index}]",
                "raw_value": _json_safe(binding.param_value),
                "param_index": binding.param_index,
                "skill_formula_binding_id": binding.binding_id,
                "formula_slot_id": binding.formula_slot_id,
                "sequence_order": binding.sequence_order,
                "target_group_hint": binding.target_group_hint,
                "character_data_card_id": binding.character_data_card_id,
                "data_card_id": _formula_binding_data_card_id(binding),
                "data_card_kind": binding.data_card_kind,
                "owner_entity_ref": binding.owner_entity_ref,
                "skill_formula_binding_source": binding.source.to_json(),
            }
        )
    return source


def _damage_emission_id(task: AbilityTaskIR, profile: HitProfileIR | None) -> str:
    hit_id = profile.hit_profile_id if profile else "missing_hit_profile"
    return f"damage_emission:{task.task_id}:{hit_id}"


def _direct_damage_binding_lookup(
    bindings: list[SkillFormulaBindingIR],
) -> dict[tuple[str, int, int], SkillFormulaBindingIR]:
    lookup: dict[tuple[str, int, int], SkillFormulaBindingIR] = {}
    for binding in sorted(bindings, key=lambda item: item.binding_id):
        if binding.formula_role != "direct_damage":
            continue
        if not _formula_binding_data_card_id(binding):
            continue
        key = (binding.action_id, binding.level, binding.param_index)
        existing = lookup.get(key)
        if existing is None or (
            existing.coverage_status != "executable" and binding.coverage_status == "executable"
        ):
            lookup[key] = binding
    return lookup


def _formula_binding_data_card_id(binding: SkillFormulaBindingIR) -> str:
    return binding.data_card_id or binding.character_data_card_id


def _skill_formula_source_kind(binding: SkillFormulaBindingIR | None) -> str:
    if binding is None:
        return "action_definition_param_list"
    if binding.data_card_kind == "monster":
        return "monster_data_card_skill_formula"
    return "character_data_card_skill_formula"


def _monster_damage_percentage_hash_mismatch(
    effect: EffectIR | None,
    binding: SkillFormulaBindingIR,
) -> str:
    if (binding.data_card_kind or "") != "monster":
        return ""
    effect_hash = _damage_percentage_dynamic_hash(effect)
    if effect_hash is None:
        return "monster_damage_percentage_dynamic_hash_missing"
    binding_hash = binding.scaling_basis_expr.get("dynamic_hash")
    if binding_hash is None:
        binding_hash = binding.source.evidence.get("dynamic_hash")
    if str(binding_hash) != str(effect_hash):
        return "monster_damage_percentage_dynamic_hash_mismatch"
    return ""


def _damage_percentage_dynamic_hash(effect: EffectIR | None) -> str | None:
    if effect is None:
        return None
    attack_property = effect.payload.get("AttackProperty") if isinstance(effect.payload, dict) else None
    if not isinstance(attack_property, dict):
        return None
    expr = _numeric_expr_summary(attack_property.get("DamagePercentage"))
    if expr.get("kind") == "dynamic_hash" and expr.get("hash") is not None:
        return str(expr["hash"])
    raw = expr.get("raw")
    if isinstance(raw, dict):
        postfix = raw.get("PostfixExpr")
        if isinstance(postfix, dict):
            hashes = postfix.get("DynamicHashes")
            if isinstance(hashes, list) and len(hashes) == 1 and hashes[0] is not None:
                return str(hashes[0])
    return None


def _damage_emission_source(
    task: AbilityTaskIR,
    effect: EffectIR | None,
    profile: HitProfileIR | None,
) -> IRSource:
    payload = effect.payload if effect else {}
    return IRSource(
        source_path=task.source.source_path,
        raw_type="AbilityDamageEmission",
        raw_id=task.opcode,
        evidence={
            **task.source.evidence,
            "task_id": task.task_id,
            "effect_id": task.effect_id,
            "target_alias": _target_alias(payload.get("TargetType")),
            "damage_custom_name": _attack_property_custom_name(payload),
            "hit_profile_id": profile.hit_profile_id if profile else "",
            "hit_profile_source": profile.source.to_json() if profile else None,
        },
    )


def _damage_scaling_basis_expr(
    task: AbilityTaskIR,
    effect: EffectIR | None,
    profile: HitProfileIR | None,
    direct_basis_bindings: dict[tuple[str, int, int], SkillFormulaBindingIR],
) -> dict[str, Any]:
    if profile is None or profile.damage_formula_family != "direct":
        return {
            "kind": "missing",
            "supported": False,
            "reason": "damage_scaling_basis_not_applicable",
        }
    payload = effect.payload if effect else {}
    param_index = _hit_profile_param_index(profile)
    binding = direct_basis_bindings.get((task.action_id, task.level, param_index))
    if binding is None:
        return {
            "kind": "missing",
            "supported": False,
            "reason": "character_data_card_skill_formula_missing",
            "param_index": param_index,
            "source_trace": {
                "task_source": task.source.to_json(),
                "effect_id": task.effect_id,
                "target_alias": _target_alias(payload.get("TargetType")),
                "hit_profile_id": profile.hit_profile_id,
                "hit_profile_source": profile.source.to_json(),
            },
        }
    if binding.coverage_status != "executable":
        return {
            "kind": "missing",
            "supported": False,
            "reason": binding.blocked_reason or f"character_data_card_skill_formula_{binding.coverage_status}",
            "param_index": param_index,
            "source_trace": {
                "task_source": task.source.to_json(),
                "effect_id": task.effect_id,
                "target_alias": _target_alias(payload.get("TargetType")),
                "hit_profile_id": profile.hit_profile_id,
                "hit_profile_source": profile.source.to_json(),
                "skill_formula_binding": binding.to_json(),
                "character_data_card_id": binding.character_data_card_id,
                "data_card_id": _formula_binding_data_card_id(binding),
            },
        }
    hash_mismatch = _monster_damage_percentage_hash_mismatch(effect, binding)
    if hash_mismatch:
        return {
            "kind": "missing",
            "supported": False,
            "reason": hash_mismatch,
            "param_index": param_index,
            "source_trace": {
                "task_source": task.source.to_json(),
                "effect_id": task.effect_id,
                "target_alias": _target_alias(payload.get("TargetType")),
                "hit_profile_id": profile.hit_profile_id,
                "hit_profile_source": profile.source.to_json(),
                "skill_formula_binding": binding.to_json(),
                "data_card_id": _formula_binding_data_card_id(binding),
            },
        }
    basis_expr = dict(binding.scaling_basis_expr)
    source_trace = basis_expr.get("source_trace")
    if not isinstance(source_trace, dict):
        source_trace = {}
    basis_expr["source_trace"] = {
        **source_trace,
        "task_source": task.source.to_json(),
        "effect_id": task.effect_id,
        "target_alias": _target_alias(payload.get("TargetType")),
        "hit_profile_id": profile.hit_profile_id,
        "hit_profile_source": profile.source.to_json(),
        "skill_formula_binding": binding.to_json(),
        "character_data_card_id": binding.character_data_card_id,
        "data_card_id": _formula_binding_data_card_id(binding),
    }
    return basis_expr


def _hit_profile_param_index(profile: HitProfileIR) -> int:
    source = profile.multiplier_source
    raw_path = str(source.get("raw_path") or "")
    match = re.search(r"ParamList\[(\d+)\]", raw_path)
    if match:
        return int(match.group(1))
    return 0


def _damage_emission_blocked_reason(
    task: AbilityTaskIR,
    effect: EffectIR | None,
    profile: HitProfileIR | None,
    scaling_basis_expr: dict[str, Any],
) -> str:
    if effect is None:
        return "damage_emission_effect_missing"
    payload = effect.payload
    target_alias = _target_alias(payload.get("TargetType"))
    if target_alias not in DAMAGE_EMISSION_TARGET_ALIASES:
        return f"unsupported_damage_target_alias:{target_alias}"
    if not isinstance(payload.get("AttackProperty"), dict):
        return "damage_emission_attack_property_missing"
    if profile is None:
        return "damage_emission_hit_profile_missing"
    target_group_reason = _damage_emission_target_group_blocked_reason(target_alias, profile.target_group)
    if target_group_reason:
        return target_group_reason
    if profile.coverage_status != "executable":
        return f"hit_profile_not_executable:{profile.blocked_reason or profile.coverage_status}"
    if profile.damage_formula_family != "direct":
        return f"damage_emission_family_not_executable:{profile.damage_formula_family}"
    if not _numeric_expr_can_be_runtime_bound(profile.multiplier_expr):
        return "damage_emission_scaling_ratio_not_runtime_bound"
    if scaling_basis_expr.get("kind") != "unit_stat" or scaling_basis_expr.get("admission_status") != "executable":
        reason = str(scaling_basis_expr.get("reason") or "character_data_card_skill_formula_missing")
        return f"damage_scaling_basis_not_admitted:{reason}"
    return ""


def _damage_emission_target_group_blocked_reason(target_alias: str | None, target_group: str) -> str:
    if target_alias in {"AbilityTargetEntity", "CurrentActionTarget"}:
        if target_group in {"primary", "selected"} or target_group.startswith("bounce:"):
            return ""
        return f"damage_target_group_mismatch:{target_alias}:{target_group}"
    if target_alias == "AbilityTargetAdjoinEntity":
        return "" if target_group == "adjacent" else f"damage_target_group_mismatch:{target_alias}:{target_group}"
    if target_alias == "AllEnemy":
        return "" if target_group == "selected" else f"damage_target_group_mismatch:{target_alias}:{target_group}"
    return f"unsupported_damage_target_alias:{target_alias}"


def _toughness_emission_id(task: AbilityTaskIR, profile: HitProfileIR | None) -> str:
    hit_id = profile.hit_profile_id if profile else "missing_hit_profile"
    return f"toughness_emission:{task.task_id}:{hit_id}"


def _toughness_emission_source(
    task: AbilityTaskIR,
    effect: EffectIR | None,
    profile: HitProfileIR | None,
) -> IRSource:
    payload = effect.payload if effect else {}
    return IRSource(
        source_path=task.source.source_path,
        raw_type="AbilityToughnessEmission",
        raw_id=task.opcode,
        evidence={
            **task.source.evidence,
            "task_id": task.task_id,
            "effect_id": task.effect_id,
            "target_alias": _target_alias(payload.get("TargetType")),
            "hit_profile_id": profile.hit_profile_id if profile else "",
            "hit_profile_source": profile.source.to_json() if profile else None,
            "stance_source": profile.stance_source if profile else {},
            "toughness_amount_source": _toughness_amount_expr(effect, profile),
            "attack_property": _json_safe(payload.get("AttackProperty")) if isinstance(payload, dict) else {},
        },
    )


def _toughness_emission_blocked_reason(
    task: AbilityTaskIR,
    effect: EffectIR | None,
    profile: HitProfileIR | None,
) -> str:
    if effect is None:
        return "toughness_emission_effect_missing"
    payload = effect.payload
    target_alias = _target_alias(payload.get("TargetType"))
    if target_alias not in DAMAGE_EMISSION_TARGET_ALIASES:
        return f"unsupported_toughness_target_alias:{target_alias}"
    if not isinstance(payload.get("AttackProperty"), dict):
        return "toughness_emission_attack_property_missing"
    if profile is None:
        return "toughness_emission_hit_profile_missing"
    target_group_reason = _damage_emission_target_group_blocked_reason(target_alias, profile.target_group)
    if target_group_reason:
        return target_group_reason.replace("damage_", "toughness_", 1)
    if profile.coverage_status != "executable":
        return f"hit_profile_not_executable:{profile.blocked_reason or profile.coverage_status}"
    amount_expr = _toughness_amount_expr(effect, profile)
    if not _numeric_expr_can_be_runtime_bound(amount_expr):
        return amount_expr.get("reason") or amount_expr.get("blocked_reason") or "toughness_amount_not_executable"
    return ""


def _toughness_amount_expr(effect: EffectIR | None, profile: HitProfileIR | None = None) -> dict[str, Any]:
    if effect is None:
        return {"kind": "missing", "reason": "toughness_emission_effect_missing"}
    attack_property = effect.payload.get("AttackProperty") if isinstance(effect.payload, dict) else None
    if not isinstance(attack_property, dict):
        return {"kind": "missing", "reason": "toughness_emission_attack_property_missing"}
    if "StanceValue" not in attack_property:
        return _monster_sp_hit_toughness_amount_expr(effect, profile, attack_property)
    expr = _numeric_expr_summary(attack_property.get("StanceValue"))
    return {
        **expr,
        "raw_path": "AttackProperty.StanceValue",
        "source_kind": "ability_task_attack_property_stance_value",
    }


def _monster_sp_hit_toughness_amount_expr(
    effect: EffectIR,
    profile: HitProfileIR | None,
    attack_property: dict[str, Any],
) -> dict[str, Any]:
    if profile is None:
        return {"kind": "missing", "reason": "attack_property_stance_value_missing"}
    action_source = profile.stance_source.get("source") if isinstance(profile.stance_source, dict) else None
    if not isinstance(action_source, dict):
        action_source = profile.source.to_json()
    action_evidence = action_source.get("evidence") if isinstance(action_source, dict) else {}
    sp_hit_base_raw = action_evidence.get("sp_hit_base") if isinstance(action_evidence, dict) else None
    sp_hit_base = _number_value(sp_hit_base_raw, float("nan"))
    sp_hit_ratio_expr = _numeric_expr_summary(attack_property.get("SPHitRatio"))
    sp_hit_ratio = _fixed_expr_value(sp_hit_ratio_expr)
    if not isinstance(sp_hit_base, float) or sp_hit_base != sp_hit_base:
        return {
            "kind": "missing",
            "reason": "attack_property_stance_value_missing",
            "secondary_reason": "monster_sp_hit_base_missing",
            "raw_path": "ActionDefinition.source.evidence.sp_hit_base",
            "source_kind": "monster_skill_sp_hit_base",
            "source_trace": action_source,
        }
    if sp_hit_ratio is None:
        return {
            "kind": "missing",
            "reason": "monster_sp_hit_ratio_not_fixed",
            "raw_path": "AttackProperty.SPHitRatio",
            "source_kind": "monster_skill_sp_hit_ratio",
            "sp_hit_ratio_expr": sp_hit_ratio_expr,
            "source_trace": effect.source.to_json(),
        }
    return {
        "kind": "fixed",
        "value": sp_hit_base * sp_hit_ratio,
        "source_kind": "monster_skill_sp_hit_base_times_attack_property_sp_hit_ratio",
        "raw_path": "MonsterSkillConfig.SPHitBase * AttackProperty.SPHitRatio",
        "sp_hit_base": sp_hit_base,
        "sp_hit_base_raw": _json_safe(sp_hit_base_raw),
        "sp_hit_ratio": sp_hit_ratio,
        "sp_hit_ratio_expr": sp_hit_ratio_expr,
        "source_trace": {
            "action_definition": action_source,
            "effect": effect.source.to_json(),
        },
    }


def _action_event_from_definition(
    definition: ActionDefinitionIR,
    hit_profiles: list[HitProfileIR],
    binding: ActionAbilityBindingIR | None,
    phases: tuple[AbilityPhaseIR, ...],
) -> ActionEventIR:
    has_damage = definition.damage_kind == "hp_damage" and any(
        profile.coverage_status != "blocked" for profile in hit_profiles
    )
    has_attack_windows = _action_definition_is_attack(definition)
    binding_blocked_reason = _binding_blocked_reason(binding, phases)
    target_blocked_reason = _action_event_target_blocked_reason(definition, hit_profiles)
    blocked_reason = ",".join(reason for reason in (binding_blocked_reason, target_blocked_reason) if reason)
    status = "blocked" if blocked_reason else "lowered"
    source = binding.source if binding and binding.coverage_status == "executable" else definition.source
    binding_id = binding.binding_id if binding else ""
    phase_ids = tuple(phase.phase_id for phase in phases)
    source_mode = binding.source_mode if binding else "missing_binding"
    event_source_status = "ability_phase_graph_bound" if binding and binding.coverage_status == "executable" else "blocked_missing_or_incomplete_ability_binding"
    steps: list[ActionPhaseStepIR] = [
        ActionPhaseStepIR(
            kind="trigger_window",
            phase="before_skill_use",
            canonical_window="before_skill_use",
            tbgd_event="OnBeforeSkillUse",
            coverage_status=status,
            blocked_reason=blocked_reason,
            source=source,
        )
    ]
    if has_attack_windows and not blocked_reason:
        steps.append(
            ActionPhaseStepIR(
                kind="trigger_window",
                phase="before_attack",
                canonical_window="before_attack",
                tbgd_event="OnBeforeAttack",
                coverage_status="lowered",
                source=source,
            )
        )
    if has_damage and not blocked_reason:
        steps.append(
            ActionPhaseStepIR(
                kind="damage",
                phase="damage",
                coverage_status="lowered",
                source=source,
            )
        )
    if has_attack_windows and not blocked_reason:
        steps.append(
            ActionPhaseStepIR(
                kind="trigger_window",
                phase="after_attack",
                canonical_window="after_attack",
                tbgd_event="OnAfterAttack",
                coverage_status="lowered",
                source=source,
            )
        )
    steps.append(
        ActionPhaseStepIR(
            kind="trigger_window",
            phase="after_skill_use",
            canonical_window="after_skill_use",
            tbgd_event="OnAfterSkillUse",
            coverage_status=status,
            blocked_reason=blocked_reason,
            source=source,
        )
    )
    return ActionEventIR(
        action_event_id=f"action_event:{definition.action_id}:{definition.level}",
        action_id=definition.action_id,
        level=definition.level,
        target_mode=definition.target_mode,
        selection_mode=_selection_mode(definition.target_mode),
        phase_steps=tuple(steps),
        hit_profile_ids=tuple(profile.hit_profile_id for profile in hit_profiles),
        derived_status="derived_from_ability_phase_graph" if not blocked_reason else "blocked_action_ability_binding",
        derived_reason=(
            "phase windows are projected from ActionAbilityBindingIR/AbilityPhaseIR evidence; "
            "individual Ability task execution is not implemented in v0_221"
        ),
        source=source,
        coverage_status=status,
        blocked_reason=blocked_reason,
        binding_id=binding_id,
        phase_ids=phase_ids,
        source_mode=source_mode,
        event_source_status=event_source_status,
    )


def _action_event_target_blocked_reason(definition: ActionDefinitionIR, hit_profiles: list[HitProfileIR]) -> str:
    if definition.target_mode == "bounce" and any(
        profile.coverage_status == "executable" and profile.bounce_policy_id for profile in hit_profiles
    ):
        return ""
    return _target_blocked_reason(definition.target_mode)


def _hit_profiles_from_definition(
    definition: ActionDefinitionIR,
    skill_formula_bindings: tuple[SkillFormulaBindingIR, ...] = (),
    bounce_policy: BouncePolicyIR | None = None,
) -> list[HitProfileIR]:
    if definition.damage_kind != "hp_damage":
        return []
    formula_hit_profiles = _hit_profiles_from_skill_formula_bindings(definition, skill_formula_bindings, bounce_policy)
    if formula_hit_profiles:
        return formula_hit_profiles
    groups = _hit_target_groups(definition.target_mode)
    if not groups:
        groups = (definition.target_mode or "unknown",)
    profiles: list[HitProfileIR] = []
    for hit_index, target_group in enumerate(groups):
        blocked_reason = _hit_profile_blocked_reason(definition, target_group)
        if (
            not blocked_reason
            and definition.action_id.startswith("avatar_skill:")
            and definition.damage_formula_family == "direct"
        ):
            blocked_reason = "skill_text_scaling_basis_binding_missing"
        profiles.append(
            HitProfileIR(
                hit_profile_id=f"hit_profile:{definition.action_id}:{definition.level}:{hit_index}:{target_group}",
                action_id=definition.action_id,
                level=definition.level,
                hit_index=hit_index,
                target_group=target_group,
                multiplier_expr=_param_multiplier_expr(definition.param_list, 0),
                multiplier_source=_param_multiplier_source(definition, 0),
                stance_expr=_stance_expr(definition.show_stance_list),
                stance_source=_stance_source(definition),
                damage_formula_family=definition.damage_formula_family,
                element_type=definition.element_type,
                source=definition.source,
                coverage_status="blocked" if blocked_reason else "executable",
                blocked_reason=blocked_reason,
                numeric_fidelity_status=_numeric_fidelity_status(definition, target_group),
            )
        )
    return profiles


def _hit_profiles_from_skill_formula_bindings(
    definition: ActionDefinitionIR,
    skill_formula_bindings: tuple[SkillFormulaBindingIR, ...],
    bounce_policy: BouncePolicyIR | None = None,
) -> list[HitProfileIR]:
    if definition.damage_formula_family != "direct":
        return []
    if definition.target_mode == "bounce":
        return _bounce_hit_profiles_from_skill_formula_bindings(definition, skill_formula_bindings, bounce_policy)
    selected: list[SkillFormulaBindingIR] = []
    seen: set[tuple[int, str]] = set()
    for binding in sorted(skill_formula_bindings, key=lambda item: (item.sequence_order, item.param_index, item.binding_id)):
        if binding.formula_role != "direct_damage":
            continue
        target_group = _target_group_from_formula_binding(definition, binding)
        key = (binding.param_index, target_group)
        if key in seen:
            continue
        seen.add(key)
        selected.append(binding)
    profiles: list[HitProfileIR] = []
    for hit_index, binding in enumerate(selected):
        target_group = _target_group_from_formula_binding(definition, binding)
        blocked_reason = _hit_profile_blocked_reason(definition, target_group)
        if binding.coverage_status != "executable":
            blocked_reason = binding.blocked_reason or f"skill_formula_binding_not_executable:{binding.coverage_status}"
        param_reason = _param_index_blocked_reason(definition.param_list, binding.param_index)
        if param_reason and not blocked_reason:
            blocked_reason = param_reason
        profiles.append(
            HitProfileIR(
                hit_profile_id=(
                    f"hit_profile:{definition.action_id}:{definition.level}:"
                    f"{hit_index}:{target_group}:slot:{binding.sequence_order}"
                ),
                action_id=definition.action_id,
                level=definition.level,
                hit_index=hit_index,
                target_group=target_group,
                multiplier_expr=_param_multiplier_expr(definition.param_list, binding.param_index),
                multiplier_source=_param_multiplier_source(definition, binding.param_index, binding),
                stance_expr=_stance_expr(definition.show_stance_list),
                stance_source=_stance_source(definition),
                damage_formula_family=definition.damage_formula_family,
                element_type=definition.element_type,
                source=binding.source,
                coverage_status="blocked" if blocked_reason else "executable",
                blocked_reason=blocked_reason,
                numeric_fidelity_status=_numeric_fidelity_status(definition, target_group),
            )
        )
    return profiles


def _bounce_hit_profiles_from_skill_formula_bindings(
    definition: ActionDefinitionIR,
    skill_formula_bindings: tuple[SkillFormulaBindingIR, ...],
    bounce_policy: BouncePolicyIR | None,
) -> list[HitProfileIR]:
    direct_bindings = [
        binding
        for binding in sorted(skill_formula_bindings, key=lambda item: (item.sequence_order, item.param_index, item.binding_id))
        if binding.formula_role == "direct_damage"
    ]
    primary_binding = next((binding for binding in direct_bindings if binding.target_group_hint != "random"), None)
    bounce_binding = next((binding for binding in direct_bindings if binding.target_group_hint == "random"), primary_binding)
    if primary_binding is None and bounce_binding is None:
        return []
    policy_blocked_reason = _bounce_policy_blocked_reason(bounce_policy)
    entries: list[tuple[str, SkillFormulaBindingIR | None, int]] = []
    entries.append(("primary", primary_binding or bounce_binding, 0))
    bounce_count = bounce_policy.bounce_count if bounce_policy and bounce_policy.coverage_status == "executable" else 0
    for index in range(bounce_count):
        entries.append((f"bounce:{index}", bounce_binding, index + 1))
    if not bounce_count and bounce_binding is not None:
        entries.append(("bounce:0", bounce_binding, 1))
    profiles: list[HitProfileIR] = []
    for hit_index, (target_group, binding, sequence_order) in enumerate(entries):
        blocked_reason = policy_blocked_reason if target_group.startswith("bounce:") else ""
        if binding is None:
            blocked_reason = blocked_reason or "bounce_skill_formula_binding_missing"
            source = definition.source
            multiplier_expr = _param_multiplier_expr(definition.param_list, 0)
            multiplier_source = _param_multiplier_source(definition, 0)
            target_selection_policy: dict[str, Any] = {}
        else:
            if binding.coverage_status != "executable":
                blocked_reason = blocked_reason or binding.blocked_reason or f"skill_formula_binding_not_executable:{binding.coverage_status}"
            param_reason = _param_index_blocked_reason(definition.param_list, binding.param_index)
            if param_reason and not blocked_reason:
                blocked_reason = param_reason
            source = binding.source
            multiplier_expr = _param_multiplier_expr(definition.param_list, binding.param_index)
            multiplier_source = _param_multiplier_source(definition, binding.param_index, binding)
            target_selection_policy = {
                "target_group_hint": binding.target_group_hint,
                "formula_slot_id": binding.formula_slot_id,
                "skill_formula_binding_id": binding.binding_id,
            }
        if bounce_policy is not None:
            target_selection_policy = {
                **target_selection_policy,
                "bounce_policy": bounce_policy.to_json(),
            }
        profiles.append(
            HitProfileIR(
                hit_profile_id=(
                    f"hit_profile:{definition.action_id}:{definition.level}:"
                    f"{hit_index}:{target_group}:slot:{sequence_order}"
                ),
                action_id=definition.action_id,
                level=definition.level,
                hit_index=hit_index,
                target_group=target_group,
                multiplier_expr=multiplier_expr,
                multiplier_source=multiplier_source,
                stance_expr=_stance_expr(definition.show_stance_list),
                stance_source=_stance_source(definition),
                damage_formula_family=definition.damage_formula_family,
                element_type=definition.element_type,
                source=source,
                coverage_status="blocked" if blocked_reason else "executable",
                blocked_reason=blocked_reason,
                numeric_fidelity_status="trusted_for_current_scope" if not blocked_reason else "blocked",
                bounce_policy_id=bounce_policy.bounce_policy_id if bounce_policy is not None else "",
                target_selection_policy=target_selection_policy,
            )
        )
    return profiles


def _target_group_from_formula_binding(
    definition: ActionDefinitionIR,
    binding: SkillFormulaBindingIR,
) -> str:
    hint = binding.target_group_hint
    if definition.target_mode == "blast":
        return "adjacent" if hint == "adjacent" else "primary"
    if definition.target_mode in {"single", "aoe"}:
        return "selected"
    if definition.target_mode in {"bounce", "unknown"}:
        return "bounce" if hint == "random" else "primary"
    return "selected"


def _hit_target_groups(target_mode: str) -> tuple[str, ...]:
    if target_mode == "blast":
        return ("primary", "adjacent")
    if target_mode in {"single", "aoe"}:
        return ("selected",)
    if target_mode in {"bounce", "unknown"}:
        return (target_mode,)
    return ()


def _bounce_policy_blocked_reason(policy: BouncePolicyIR | None) -> str:
    if policy is None:
        return "bounce_policy_missing_from_character_data_card"
    if policy.coverage_status != "executable":
        return policy.blocked_reason or f"bounce_policy_not_executable:{policy.coverage_status}"
    return ""


def _hit_profile_blocked_reason(definition: ActionDefinitionIR, target_group: str) -> str:
    target_reason = _target_blocked_reason(definition.target_mode)
    if target_reason:
        return target_reason
    if definition.damage_formula_family not in {"direct", "true_damage", "hp_loss", "elation"}:
        return f"damage_formula_family_not_executable:{definition.damage_formula_family}"
    if target_group in {"adjacent", "selected"} and definition.target_mode in {"aoe", "blast"}:
        return ""
    return ""


def _param_multiplier_expr(param_list: tuple[Any, ...], param_index: int = 0) -> dict[str, Any]:
    if not param_list:
        return {"kind": "missing", "blocked_reason": "missing_param_list"}
    if param_index < 0 or param_index >= len(param_list):
        return {"kind": "missing", "blocked_reason": "param_list_index_out_of_range", "param_index": param_index}
    item = param_list[param_index]
    value = _number_value(item, 0.0)
    if _param_value_is_fixed(item):
        return {"kind": "fixed", "value": value}
    return {"kind": "unsupported", "raw": _json_safe(item), "blocked_reason": "param_list_multiplier_not_fixed"}


def _param_multiplier_source(
    definition: ActionDefinitionIR,
    param_index: int = 0,
    binding: SkillFormulaBindingIR | None = None,
) -> dict[str, Any]:
    item = definition.param_list[param_index] if 0 <= param_index < len(definition.param_list) else None
    source = {
        "raw_path": f"ParamList[{param_index}]",
        "raw_value": _json_safe(item),
        "param_index": param_index,
        "param_list_count": len(definition.param_list),
        "multi_param_list_not_implemented": False,
        "show_damage_count": len(definition.show_damage_list),
        "show_damage_audit_only": bool(definition.show_damage_list),
        "source_kind": _skill_formula_source_kind(binding) if binding else "action_definition_param_list",
        "source": definition.source.to_json(),
    }
    if binding is not None:
        source.update(
            {
                "skill_formula_binding_id": binding.binding_id,
                "formula_slot_id": binding.formula_slot_id,
                "sequence_order": binding.sequence_order,
                "target_group_hint": binding.target_group_hint,
                "character_data_card_id": binding.character_data_card_id,
                "data_card_id": _formula_binding_data_card_id(binding),
                "data_card_kind": binding.data_card_kind,
                "owner_entity_ref": binding.owner_entity_ref,
                "skill_formula_binding_source": binding.source.to_json(),
            }
        )
    return source


def _stance_expr(show_stance_list: tuple[Any, ...]) -> dict[str, Any]:
    if not show_stance_list:
        return {"kind": "missing", "blocked_reason": "show_stance_not_present"}
    first = show_stance_list[0]
    return {
        "kind": "audit_only",
        "raw": _json_safe(first),
        "blocked_reason": "show_stance_semantics_not_confirmed",
    }


def _stance_source(definition: ActionDefinitionIR) -> dict[str, Any]:
    first = definition.show_stance_list[0] if definition.show_stance_list else None
    return {
        "raw_path": "ShowStanceList[0]",
        "raw_value": _json_safe(first),
        "show_stance_count": len(definition.show_stance_list),
        "show_stance_audit_only": bool(definition.show_stance_list),
        "stance_damage_type": definition.stance_damage_type,
        "source": definition.source.to_json(),
    }


def _param_multiplier_is_fixed(param_list: tuple[Any, ...]) -> bool:
    if not param_list:
        return False
    first = param_list[0]
    return _param_value_is_fixed(first)


def _param_value_is_fixed(value: Any) -> bool:
    if isinstance(value, dict):
        return isinstance(value.get("Value"), (int, float))
    return isinstance(value, (int, float))


def _param_index_blocked_reason(param_list: tuple[Any, ...], param_index: int) -> str:
    if param_index < 0:
        return "param_list_index_invalid"
    if param_index >= len(param_list):
        return "param_list_index_out_of_range"
    if not _param_value_is_fixed(param_list[param_index]):
        return "param_list_multiplier_not_fixed"
    return ""


def _numeric_fidelity_status(definition: ActionDefinitionIR, target_group: str) -> str:
    if definition.target_mode in {"aoe", "blast"}:
        return "structural_only"
    if len(definition.param_list) > 1 or definition.show_damage_list or definition.show_stance_list:
        return "structural_only"
    if target_group in {"bounce", "unknown"}:
        return "blocked"
    return "single_hit_ratio"


def _target_blocked_reason(target_mode: str) -> str:
    if target_mode == "bounce":
        return "bounce_not_executable"
    if target_mode == "unknown":
        return "unknown_target_mode_not_executable"
    if target_mode not in {"single", "aoe", "blast", "self_or_team"}:
        return f"unsupported_target_mode:{target_mode}"
    return ""


def _selection_mode(target_mode: str) -> str:
    if target_mode == "single":
        return "primary"
    if target_mode == "aoe":
        return "all_enemies"
    if target_mode == "blast":
        return "primary_plus_adjacent"
    if target_mode == "bounce":
        return "blocked_random_bounce"
    if target_mode == "self_or_team":
        return "explicit_ally_or_self"
    return "unknown"


def _action_definition_is_attack(definition: ActionDefinitionIR) -> bool:
    skill_effect = definition.skill_effect.lower()
    attack_type = definition.attack_type.lower()
    if definition.target_mode in {"single", "blast", "aoe", "bounce"}:
        return True
    return "attack" in skill_effect or "attack" in attack_type


def _target_mode(skill_effect: str) -> str:
    normalized = skill_effect.lower()
    if normalized in {"singleattack", "mazeattack"}:
        return "single"
    if normalized == "blast":
        return "blast"
    if normalized in {"aoeattack", "aoe"}:
        return "aoe"
    if normalized == "bounce":
        return "bounce"
    if normalized == "enhance":
        return "self_or_team"
    return "unknown"


def _monster_target_mode(target_type: str) -> str:
    if target_type == "AllEnemy":
        return "aoe"
    if target_type == "EnemySelect":
        return "single"
    if target_type in {"Caster", "FriendSelect", "AllTeamMember"}:
        return "self_or_team"
    return "unknown"


def _skill_effect_from_target_mode(target_mode: str) -> str:
    if target_mode == "aoe":
        return "AoeAttack"
    if target_mode == "single":
        return "SingleAttack"
    if target_mode == "blast":
        return "Blast"
    if target_mode == "bounce":
        return "Bounce"
    if target_mode == "self_or_team":
        return "Enhance"
    return "Unknown"


def _damage_kind(skill_effect: str) -> str:
    return "hp_damage" if _target_mode(skill_effect) in {"single", "blast", "aoe", "bounce"} else "non_damage"


def _damage_formula_family(attack_type: str, skill_effect: str) -> str:
    normalized_attack = attack_type.lower()
    normalized_effect = skill_effect.lower()
    if normalized_attack == "elationdamage" or normalized_effect == "byelationdamage":
        return "elation"
    if normalized_attack == "truedamage":
        return "true_damage"
    if normalized_attack == "dot" or normalized_effect == "dot":
        return "dot"
    if normalized_attack == "elementdamage":
        return "direct"
    if _target_mode(skill_effect) in {"single", "blast", "aoe", "bounce"}:
        return "direct"
    return "none"


def _source_mode(attack_type: str) -> str:
    return "maze" if attack_type.lower().startswith("maze") else "mainline"


def _limit_sequence(items: list[Any], limit: int | None) -> list[Any]:
    if limit is None:
        return items
    return items[:limit]


def _number_value(value: Any, default: float) -> float:
    if isinstance(value, dict):
        nested = value.get("Value")
        return _number_value(nested, default)
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _number_items(value: Any) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[float] = []
    for item in value:
        number = _number_value(item, default=float("nan"))
        if number == number:
            result.append(number)
    return tuple(result)


def _required_number(row: dict[str, Any], key: str) -> float | None:
    if key not in row:
        return None
    value = row.get(key)
    if isinstance(value, dict):
        return _required_number(value, "Value")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _list_json_values(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    return [_json_safe(item) for item in value]


def _json_object_from_path(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _compact_payload(value: dict[str, Any]) -> dict[str, Any]:
    ignored = {"SuccessTaskList", "FailedTaskList", "CallbackConfig"}
    return {key: _json_safe(item) for key, item in value.items() if key not in ignored and key != "$type"}


REMOVE_MODIFIER_OPCODES = {"RemoveModifier", "RemoveSelfModifier"}
HEAL_OPCODES = {"HealHP"}
SHIELD_OPCODES = {"InitShield", "StackShield", "ModifyShield"}
MECHANISM_BAR_OPCODES = {"SetEnergyBarState", "SetMonsterEnergyBarState", "SetSummonerEnergyBarState"}
RESOURCE_DELTA_OPCODES = {"ModifySPNew"}
DYNAMIC_VALUE_OPCODES = {"DefineDynamicValue", "SetDynamicValue", "SetDynamicValueByAddValue", "SetDynamicValueByModifierValue"}
DAMAGE_EMISSION_OPCODES = {"DamageByAttackProperty"}
HP_LOSS_OPCODES = {"LoseHPByRatio"}
DISPEL_STATUS_OPCODES = {"DispelStatus"}
EXECUTABLE_TARGET_ALIASES = {"Caster", "ModifierOwnerEntity", "ParamEntity", "CurrentActionTarget"}
ADD_MODIFIER_TARGET_ALIASES = EXECUTABLE_TARGET_ALIASES | {
    "AbilityTargetEntity",
    "AllEnemy",
    "AllTeamMember",
    "AllLightTeam",
    "AllTeammate",
}
STATUS_CALLBACK_LIST_TARGET_ALIASES = {"ParamEntitySkillTargetEntityList", "AllEnemyWithUnSelectable"}
TARGET_EXPRESSION_CONTEXT_ALIASES = {
    "AllDarkTeam",
    "CasterServant",
    "CasterSummonedMinions",
    "FriendServantSelect",
    "LastSummonMonsters",
    "SkillTargetEntityList",
    "ParamEntityList",
    "ServantEntityList",
    "BattleEventEntityList",
    "TeamFormation",
    "GridFight_AllBackEnd",
    "GridFight_AllBackEndRoleOnly",
    "GridFight_AllBackEndActivedRoleOnly",
}
P1_6_SAFE_TARGET_FETCH_KINDS = {
    "TargetFetchAbilityTarget",
    "TargetFetchCaster",
    "TargetFetchCurrentActionTarget",
    "TargetFetchModifierOwner",
    "TargetFetchOwner",
    "TargetFetchParamEntityList",
    "TargetFetchPartner",
    "TargetFetchUniqueNameEntity",
}
P1_6_SAFE_TARGET_PROPERTY_SORTS = {"CurrentHP", "MaxHP", "CurrentStance", "MaxStance"}
P1_6_SAFE_TARGET_RATIO_SORTS = {"HPRatio", "StanceRatio"}
P1_6_SAFE_DIRECT_TARGET_ALIASES = {
    "AbilityTargetAdjoinEntity",
    "AbilityTargetAndAdjoinEntity",
    "AbilityTargetLeftEntity",
    "AbilityTargetRightEntity",
    "AbilityTargetServantOrSummoner",
    "AllEnemyIgnoreServant",
    "AllLightTeamIgnoreServant",
    "AllLightTeamOnlyAddSPOnceForServant",
    "AllLightTeamWithAllLightTeamUnselectable",
    "AllLightTeamWithAllUnselectableLightTeam",
    "AllTeamMemberWithUnselectable",
    "AllTeammateOnlyAddSPOnceForServant",
    "AllTeammateWithUnselectable",
    "CasterServantOrSummoner",
    "CasterBEServant",
    "CasterSummoner",
    "CurrentAimAtTarget",
    "CasterAdjoinEntity",
    "CasterWithAbilityTargetAndAdjoinEntity",
    "LeftToRightLightTeamTarget",
    "LightTeamLeftWithoutServant",
    "LightTeamRightWithoutServant",
    "ModifierOwnerSummoner",
    "ModifierOwnerEntityAdjoinEntity",
    "ModifierOwnerSummonedMinions",
    "ParamEntityAdjoinEntity",
    "ParamEntitySummoner",
}
P1_6_SAFE_DOT_TARGET_BASE_ALIASES = ADD_MODIFIER_TARGET_ALIASES | STATUS_CALLBACK_LIST_TARGET_ALIASES | TARGET_EXPRESSION_CONTEXT_ALIASES
P1_6_SAFE_DOT_TARGET_OPERATIONS = {
    "GetAdjoinEntity",
    "GetAliveOnly",
    "Reverse",
    "Select1",
    "Select2",
    "Select3",
    "Select4",
    "SelectLast",
    "Shuffle",
    "SortByFormation",
    "SortByHP",
    "SortByHPRatio",
    "SortByMaxHP",
    "SortByStance",
    "SortByStanceRatio",
    "SortByBreakDamageAddedRatio",
    "GetServant",
    "GetServantAndDummyCharacter",
    "GetDummyCharacter",
    "GetBEServant",
    "GetSummonedMinions",
    "WithServant",
    "WithBEServant",
    "WithServantAndDummyCharacter",
    "RemoveBattleEvent",
    "RemoveBEServant",
    "RemoveCharacterChangeTarget",
    "RemoveNonSelfCreateBattleEvent",
    "RemoveServant",
    "RemoveUnselectable",
    "GetSummoner",
    "WithSummoner",
}
DAMAGE_EMISSION_TARGET_ALIASES = {
    "AbilityTargetEntity",
    "AbilityTargetAdjoinEntity",
    "AllEnemy",
    "CurrentActionTarget",
}
SUPPORTED_MODIFIER_VALUE_TYPES = {"Layer", "LifeTime"}
EXECUTABLE_CONDITION_OPCODES = {
    "AlwaysTrue",
    "ByAnd",
    "ByAny",
    "ByAttackType",
    "ByCompareDynamicValue",
    "ByCompareHPRatio",
    "ByCompareModifierValue",
    "ByCompareMonsterID",
    "ByCompareDamageCustomName",
    "ByCompareTarget",
    "ByContainBehaviorFlag",
    "ByContainsParamFlag",
    "ByCurrentSkillType",
    "ByIsContainModifier",
    "ByHaveEnemyAlive",
    "ByIsCurrentSkillActive",
    "ByIsInsertAction",
    "ByNot",
    "ByTargetListIntersects",
    "ByTargetEntityType",
    "ByTargetTeam",
}


def _effect_payload(value: dict[str, Any], opcode: str, source_modifier_name: str) -> dict[str, Any]:
    payload = _compact_payload(value)
    if opcode == "AddModifier":
        payload["standard"] = _standard_add_modifier_payload(value)
    elif opcode in REMOVE_MODIFIER_OPCODES:
        payload["standard"] = _standard_remove_modifier_payload(value, opcode, source_modifier_name)
    elif opcode in DISPEL_STATUS_OPCODES:
        payload["standard"] = _standard_dispel_status_payload(value)
    elif opcode in HEAL_OPCODES:
        payload["standard"] = _standard_heal_payload(value)
    elif opcode in SHIELD_OPCODES:
        payload["standard"] = _standard_shield_payload(value, opcode)
    elif opcode in MECHANISM_BAR_OPCODES:
        payload["standard"] = _standard_mechanism_bar_payload(value, opcode)
    elif opcode in RESOURCE_DELTA_OPCODES:
        payload["standard"] = _standard_resource_delta_payload(value, opcode)
    elif opcode in HP_LOSS_OPCODES:
        payload["standard"] = _standard_hp_loss_ratio_payload(value)
    elif opcode == "TriggerAbility":
        payload["standard"] = _standard_trigger_ability_payload(value)
    elif opcode == "DefineDynamicValue":
        payload["standard"] = _standard_define_dynamic_value_payload(value)
    elif opcode == "SetDynamicValue":
        payload["standard"] = _standard_set_dynamic_value_payload(value)
    elif opcode == "SetDynamicValueByAddValue":
        payload["standard"] = _standard_set_dynamic_value_by_add_value_payload(value)
    elif opcode == "SetDynamicValueByModifierValue":
        payload["standard"] = _standard_set_dynamic_value_by_modifier_value_payload(value, source_modifier_name)
    family = _task_damage_family(value, opcode)
    if family != "unknown":
        payload["damage_formula_family"] = family
        payload["bypasses_normal_multipliers"] = family in {"true_damage", "hp_loss"}
    return payload


TARGET_EXPRESSION_FIELD_NAMES = {
    "TargetType",
    "TargetInfo",
    "AbilityTarget",
    "AutoCastTargetType",
    "AbilityInherentTargetType",
    "ReadTargetType",
    "CompareType",
    "FirstTargetType",
    "SecondTargetType",
}


def _attach_target_expressions_to_effect_payload(
    payload: dict[str, Any],
    task: dict[str, Any],
    *,
    effect_id: str,
    source: IRSource,
) -> tuple[dict[str, Any], list[TargetExpressionIR]]:
    expressions: list[TargetExpressionIR] = []
    refs_by_field: dict[str, Any] = {}
    for field_name, raw_value in _iter_target_expression_fields(task):
        expression = _target_expression_from_raw(
            raw_value,
            field_name=field_name,
            expression_id=f"target_expression:{effect_id}:{field_name}",
            source=source,
        )
        if expression is None:
            continue
        expressions.append(expression)
        refs_by_field[field_name] = {
            "target_expression_id": expression.target_expression_id,
            "expression_kind": expression.expression_kind,
            "alias": expression.alias,
            "coverage_status": expression.coverage_status,
            "blocked_reason": expression.blocked_reason,
            "admission_batch": expression.admission_batch,
            "source": expression.source.to_json(),
        }
    if not expressions:
        return payload, []
    updated = dict(payload)
    updated["target_expression_refs"] = refs_by_field
    standard = updated.get("standard")
    if isinstance(standard, dict):
        standard = dict(standard)
        target_ref = refs_by_field.get("TargetType")
        if isinstance(target_ref, dict):
            standard["target_expression_id"] = target_ref["target_expression_id"]
            standard["target_expression_kind"] = target_ref["expression_kind"]
            standard["target_expression_coverage_status"] = target_ref["coverage_status"]
            standard["target_expression_blocked_reason"] = target_ref["blocked_reason"]
            standard["target_expression_source"] = target_ref["source"]
        standard["target_expression_refs"] = refs_by_field
        updated["standard"] = standard
    return updated, expressions


def _iter_target_expression_fields(task: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    pairs: list[tuple[str, Any]] = []
    for field_name in sorted(TARGET_EXPRESSION_FIELD_NAMES):
        value = task.get(field_name)
        if _is_target_expression_node(value):
            pairs.append((field_name, value))
        elif field_name == "TargetInfo":
            pairs.extend(_target_info_expression_fields(value))
    return tuple(pairs)


def _target_info_expression_fields(value: Any) -> tuple[tuple[str, dict[str, Any]], ...]:
    if isinstance(value, str) and _target_alias_admitted(value):
        return (("TargetInfo", {"$type": "RPG.GameCore.TargetAlias", "Alias": value}),)
    if not isinstance(value, dict):
        return ()
    target_type = value.get("TargetType")
    if _is_target_expression_node(target_type):
        assert isinstance(target_type, dict)
        return (("TargetInfo.TargetType", target_type),)
    if isinstance(target_type, str) and _target_alias_admitted(target_type):
        return (("TargetInfo.TargetType", {"$type": "RPG.GameCore.TargetAlias", "Alias": target_type}),)
    return ()


def _is_target_expression_node(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    node_type = str(value.get("$type") or "")
    return node_type.startswith("RPG.GameCore.Target") or node_type == "RPG.GameCore.Retarget"


def _target_expression_from_raw(
    value: Any,
    *,
    field_name: str,
    expression_id: str,
    source: IRSource,
) -> TargetExpressionIR | None:
    if not _is_target_expression_node(value):
        return None
    assert isinstance(value, dict)
    node_type = str(value.get("$type") or "")
    expression_kind = _target_expression_kind(node_type, value)
    alias = _target_alias(value) or ""
    coverage_status, blocked_reason, admission_batch = _target_expression_admission(expression_kind, alias, value)
    return TargetExpressionIR(
        target_expression_id=expression_id,
        expression_kind=expression_kind,
        alias=alias,
        payload={
            "field_name": field_name,
            "node_type": node_type,
            "alias": alias,
            "normalized": _target_expression_normalized_payload(value),
            "raw": _json_safe(value),
        },
        source=IRSource(
            source_path=source.source_path,
            raw_type="TargetExpression",
            raw_id=expression_id,
            evidence={
                **source.evidence,
                "target_expression_field": field_name,
                "target_expression_kind": expression_kind,
                "target_alias": alias,
                "source_raw_type": source.raw_type,
                "source_raw_id": source.raw_id,
            },
        ),
        coverage_status=coverage_status,
        blocked_reason=blocked_reason,
        admission_batch=admission_batch,
    )


def _target_expression_kind(node_type: str, value: dict[str, Any]) -> str:
    if node_type.startswith("RPG.GameCore."):
        return node_type.removeprefix("RPG.GameCore.")
    if value.get("Alias") is not None:
        return "TargetAlias"
    return "UnknownTargetExpression"


def _target_expression_admission(kind: str, alias: str, raw: dict[str, Any]) -> tuple[str, str, str]:
    if kind == "TargetAlias" and _target_alias_admitted(alias):
        return "executable", "", "p1_6_target_pipeline" if _target_alias_chain_admitted(alias) else "v0_288_target_alias_core"
    if kind in {"TargetConcat", "TargetSequence", "TargetFilter", "Retarget"}:
        reason = _target_expression_runtime_blocked_reason(raw)
        if not reason:
            return "executable", "", "p1_6_target_pipeline" if _target_expression_uses_p1_6_node(raw) else "v0_289_target_sequence_filter_retarget"
        return "blocked", reason, "p1_6_target_pipeline" if _target_expression_uses_p1_6_node(raw) else "v0_289_target_sequence_filter_retarget"
    reason = _target_expression_runtime_blocked_reason(raw)
    if not reason and _target_expression_kind_admitted(kind, raw):
        return "executable", "", "p1_6_target_pipeline"
    if kind.startswith("TargetSort"):
        return "blocked", f"target_sort_not_admitted:{kind}", "after_target_sequence_sorting"
    if kind.startswith("TargetFetch"):
        return "blocked", f"target_fetch_not_admitted:{kind}", "after_summon_or_unique_entity_system"
    if kind == "TargetAlias" and alias:
        return "blocked", f"target_alias_not_admitted:{alias}", "later_target_expression_admission"
    return "blocked", f"target_expression_not_admitted:{kind or 'missing'}", "later_target_expression_admission"


def _target_alias_admitted(alias: str) -> bool:
    return alias in (
        ADD_MODIFIER_TARGET_ALIASES
        | STATUS_CALLBACK_LIST_TARGET_ALIASES
        | TARGET_EXPRESSION_CONTEXT_ALIASES
        | P1_6_SAFE_DIRECT_TARGET_ALIASES
    ) or _target_alias_chain_admitted(alias)


def _target_expression_runtime_blocked_reason(raw: dict[str, Any]) -> str:
    kind = _target_expression_kind(str(raw.get("$type") or ""), raw)
    if kind == "TargetAlias":
        alias = _target_alias(raw) or ""
        return "" if _target_alias_admitted(alias) else f"target_alias_not_admitted:{alias or 'missing'}"
    if kind == "TargetConcat":
        targets = raw.get("Targets")
        if not isinstance(targets, list) or not targets:
            return "target_concat_children_missing"
        return _first_target_expression_child_blocked_reason(targets)
    if kind == "TargetSequence":
        sequence = raw.get("Sequence")
        if not isinstance(sequence, list) or not sequence:
            return "target_sequence_children_missing"
        return _first_target_expression_child_blocked_reason(sequence)
    if kind == "TargetFilter":
        predicate = raw.get("Predicate")
        if not isinstance(predicate, dict):
            return "target_filter_predicate_missing"
        opcode = _short_gamecore_type(predicate.get("$type"))
        payload = _compact_payload(predicate)
        if not _condition_payload_executable(opcode, payload):
            return f"target_filter_condition_not_admitted:{opcode or 'missing'}"
        target = raw.get("TargetType") or raw.get("Target") or raw.get("Targets")
        if isinstance(target, dict):
            return _target_expression_runtime_blocked_reason(target)
        return ""
    if kind == "Retarget":
        target = raw.get("TargetType")
        if not isinstance(target, dict):
            return "retarget_target_type_missing"
        reason = _target_expression_runtime_blocked_reason(target)
        if reason:
            return reason
        predicate = raw.get("Predicate")
        if isinstance(predicate, dict):
            opcode = _short_gamecore_type(predicate.get("$type"))
            payload = _compact_payload(predicate)
            if not _condition_payload_executable(opcode, payload):
                return f"retarget_condition_not_admitted:{opcode or 'missing'}"
        max_number = raw.get("MaxNumber")
        if max_number is not None and not _numeric_expr_can_be_runtime_bound(_numeric_expr_summary(max_number)):
            return "retarget_max_number_not_executable"
        return ""
    if kind == "TargetQuery":
        return _target_query_blocked_reason(raw)
    reason = _target_pipeline_node_blocked_reason(kind, raw)
    if reason != "target_pipeline_node_not_matched":
        return reason
    if kind.startswith("TargetSort"):
        return f"target_sort_not_admitted:{kind}"
    if kind.startswith("TargetFetch"):
        return f"target_fetch_not_admitted:{kind}"
    return f"target_expression_kind_not_admitted:{kind or 'missing'}"


def _first_target_expression_child_blocked_reason(children: list[Any]) -> str:
    for child in children:
        if not isinstance(child, dict):
            return "target_expression_child_not_object"
        reason = _target_expression_runtime_blocked_reason(child)
        if reason:
            return reason
    return ""


def _target_expression_kind_admitted(kind: str, raw: dict[str, Any]) -> bool:
    return _target_pipeline_node_blocked_reason(kind, raw) == ""


def _target_pipeline_node_blocked_reason(kind: str, raw: dict[str, Any]) -> str:
    if kind in P1_6_SAFE_TARGET_FETCH_KINDS:
        if kind == "TargetFetchUniqueNameEntity" and not raw.get("UniqueName"):
            return "unique_entity_key_missing"
        return ""
    if kind == "TargetMapAdjoinEntity":
        side = str(raw.get("SideType") or "")
        return "" if side in {"", "Both", "Left", "Right"} else f"target_adjacent_side_not_admitted:{side}"
    if kind in {"TargetMapSummoner", "TargetMapSummonedMinions"}:
        return ""
    if kind == "TargetReverse":
        return ""
    if kind == "TargetShuffle":
        return ""
    if kind == "TargetTake":
        count = raw.get("Count")
        if count is None:
            return "target_take_count_missing"
        if not _numeric_expr_can_be_runtime_bound(_numeric_expr_summary(count)):
            return "target_take_count_not_executable"
        return ""
    if kind == "TargetIndex":
        index_type = str(raw.get("IndexType") or "IndexStrict")
        if index_type not in {"First", "IndexStrict", "Last"}:
            return f"target_index_type_not_admitted:{index_type or 'missing'}"
        index_value = raw.get("IndexValue")
        if index_value is not None and not _numeric_expr_can_be_runtime_bound(_numeric_expr_summary(index_value)):
            return "target_index_value_not_executable"
        return ""
    if kind == "TargetSortByProperty":
        property_type = str(raw.get("PropertyType") or "")
        return "" if property_type in P1_6_SAFE_TARGET_PROPERTY_SORTS else f"target_sort_property_not_admitted:{property_type or 'missing'}"
    if kind == "TargetSortByPropertyRatio":
        property_type = str(raw.get("PropertyRatioType") or "")
        return "" if property_type in P1_6_SAFE_TARGET_RATIO_SORTS else f"target_sort_ratio_not_admitted:{property_type or 'missing'}"
    if kind == "TargetSortByFormation":
        return ""
    return "target_pipeline_node_not_matched"


def _target_query_blocked_reason(raw: dict[str, Any]) -> str:
    entity_type = str(raw.get("EntityTypeMask") or "")
    if entity_type != "Servant":
        return f"target_query_entity_type_not_admitted:{entity_type or 'missing'}"
    predicate = raw.get("Predicate")
    if predicate is None:
        return ""
    if not isinstance(predicate, dict):
        return "target_query_predicate_missing"
    opcode = _short_gamecore_type(predicate.get("$type"))
    if opcode != "ByCompareTarget":
        return f"target_query_predicate_not_admitted:{opcode or 'missing'}"
    target = predicate.get("TargetType")
    compare = predicate.get("CompareType")
    if not isinstance(target, dict) or not isinstance(compare, dict):
        return "target_query_compare_target_missing"
    target_reason = _target_expression_runtime_blocked_reason(target)
    if target_reason:
        return f"target_query_target_type_blocked:{target_reason}"
    compare_reason = _target_expression_runtime_blocked_reason(compare)
    if compare_reason:
        return f"target_query_compare_type_blocked:{compare_reason}"
    return ""


def _target_expression_uses_p1_6_node(raw: dict[str, Any]) -> bool:
    kind = _target_expression_kind(str(raw.get("$type") or ""), raw)
    if _target_pipeline_node_blocked_reason(kind, raw) != "target_pipeline_node_not_matched":
        return True
    if kind == "TargetQuery" and not _target_query_blocked_reason(raw):
        return True
    if kind == "TargetAlias" and _target_alias_chain_admitted(_target_alias(raw) or ""):
        return True
    children = raw.get("Targets") if kind == "TargetConcat" else raw.get("Sequence")
    if isinstance(children, list):
        return any(isinstance(child, dict) and _target_expression_uses_p1_6_node(child) for child in children)
    target = raw.get("TargetType") or raw.get("Target") or raw.get("Targets")
    return isinstance(target, dict) and _target_expression_uses_p1_6_node(target)


def _target_alias_chain_admitted(alias: str) -> bool:
    if alias in P1_6_SAFE_DIRECT_TARGET_ALIASES:
        return True
    if _target_alias_set_admitted(alias):
        return True
    return _target_alias_dot_chain_admitted(alias)


def _target_alias_set_admitted(alias: str) -> bool:
    parsed = _parse_target_alias_set(alias)
    if len(parsed) < 2:
        return False
    for _, token in parsed:
        if token in P1_6_SAFE_DIRECT_TARGET_ALIASES:
            continue
        if _target_alias_dot_chain_admitted(token):
            continue
        if token in (
            ADD_MODIFIER_TARGET_ALIASES
            | STATUS_CALLBACK_LIST_TARGET_ALIASES
            | TARGET_EXPRESSION_CONTEXT_ALIASES
        ):
            continue
        return False
    return True


def _parse_target_alias_set(alias: str) -> tuple[tuple[str, str], ...]:
    parsed: list[tuple[str, str]] = []
    operator = "+"
    current: list[str] = []
    for ch in alias:
        if ch in {"+", "|", "-"}:
            operand = "".join(current).strip()
            if not operand:
                return ()
            parsed.append((operator, operand))
            operator = ch
            current = []
            continue
        current.append(ch)
    operand = "".join(current).strip()
    if not operand:
        return ()
    parsed.append((operator, operand))
    return tuple(parsed) if len(parsed) >= 2 else ()


def _target_alias_dot_chain_admitted(alias: str) -> bool:
    if "." not in alias or any(token in alias for token in (" ", "+", "-", "|", "(", ")")):
        return False
    parts = tuple(part for part in alias.split(".") if part)
    if len(parts) < 2:
        return False
    if parts[0] not in P1_6_SAFE_DOT_TARGET_BASE_ALIASES and parts[0] not in P1_6_SAFE_DIRECT_TARGET_ALIASES:
        return False
    return all(part in P1_6_SAFE_DOT_TARGET_OPERATIONS for part in parts[1:])


def _target_expression_normalized_payload(raw: dict[str, Any]) -> dict[str, Any]:
    kind = _target_expression_kind(str(raw.get("$type") or ""), raw)
    payload: dict[str, Any] = {"expression_kind": kind, "alias": _target_alias(raw) or ""}
    if kind == "TargetAlias" and _target_alias_chain_admitted(payload["alias"]):
        payload["alias_admission"] = {
            "admission_batch": "p1_6_target_pipeline",
            "source_paths": [
                "Config/GlobalConfig/TargetAliasConfig.json",
                "Config/GlobalConfig/TargetOperationConfig.json",
            ],
            "mode": "safe_global_alias_or_dot_chain",
        }
    if kind == "TargetConcat":
        payload["children"] = [_target_expression_normalized_payload(item) for item in raw.get("Targets") or [] if isinstance(item, dict)]
    elif kind == "TargetSequence":
        payload["children"] = [_target_expression_normalized_payload(item) for item in raw.get("Sequence") or [] if isinstance(item, dict)]
    elif kind == "TargetFilter":
        predicate = raw.get("Predicate")
        if isinstance(predicate, dict):
            opcode = _short_gamecore_type(predicate.get("$type"))
            predicate_payload = _compact_payload(predicate)
            payload["predicate"] = {
                "opcode": opcode,
                "payload": _json_safe(predicate_payload),
                "coverage_status": "executable" if _condition_payload_executable(opcode, predicate_payload) else classify_opcode(opcode),
            }
    elif kind == "Retarget":
        target = raw.get("TargetType")
        if isinstance(target, dict):
            payload["target"] = _target_expression_normalized_payload(target)
        payload["by_random"] = bool(raw.get("ByRandom"))
        payload["max_number"] = _numeric_expr_summary(raw.get("MaxNumber"))
    elif kind == "TargetQuery":
        predicate = raw.get("Predicate")
        normalized_predicate: dict[str, Any] = {}
        if isinstance(predicate, dict):
            normalized_predicate = {
                "opcode": _short_gamecore_type(predicate.get("$type")),
                "target": _target_expression_normalized_payload(predicate.get("TargetType"))
                if isinstance(predicate.get("TargetType"), dict)
                else {},
                "compare": _target_expression_normalized_payload(predicate.get("CompareType"))
                if isinstance(predicate.get("CompareType"), dict)
                else {},
            }
        payload["query"] = {
            "entity_type_mask": str(raw.get("EntityTypeMask") or ""),
            "alive_state_mask": str(raw.get("AliveStateMask") or ""),
            "predicate": normalized_predicate,
            "admission_batch": "p1_6_target_pipeline",
        }
    elif kind in P1_6_SAFE_TARGET_FETCH_KINDS:
        payload["fetch"] = {
            "fetch_kind": kind,
            "unique_name": str(raw.get("UniqueName") or ""),
            "name": str(raw.get("Name") or ""),
            "source_path": "Config/GlobalConfig/TargetAliasConfig.json"
            if kind
            in {
                "TargetFetchCaster",
                "TargetFetchModifierOwner",
                "TargetFetchPartner",
                "TargetFetchParamEntityList",
            }
            else "",
        }
    elif kind == "TargetMapAdjoinEntity":
        payload["adjacent"] = {"side_type": str(raw.get("SideType") or "Both"), "position_source": "UnitState.flags.position"}
    elif kind == "TargetShuffle":
        payload["random"] = {"choice_source": "event_payload.target_random_choices", "rng_type": "target_random"}
    elif kind == "TargetTake":
        payload["take"] = {"count": _numeric_expr_summary(raw.get("Count"))}
    elif kind == "TargetIndex":
        payload["index"] = {"index_type": str(raw.get("IndexType") or "IndexStrict"), "index_value": _numeric_expr_summary(raw.get("IndexValue"))}
    elif kind == "TargetReverse":
        payload["reverse"] = {"operation": "reverse"}
    elif kind == "TargetSortByProperty":
        payload["sort"] = {
            "sort_key": str(raw.get("PropertyType") or ""),
            "sort_kind": kind,
            "highest_first": bool(raw.get("HighestFirst")),
            "direction_source": "raw.HighestFirst" if "HighestFirst" in raw else "tbgd_target_operation_default_lowest_first",
        }
    elif kind == "TargetSortByPropertyRatio":
        payload["sort"] = {
            "sort_key": str(raw.get("PropertyRatioType") or ""),
            "sort_kind": kind,
            "highest_first": bool(raw.get("HighestFirst")),
            "direction_source": "raw.HighestFirst" if "HighestFirst" in raw else "tbgd_target_operation_default_lowest_first",
        }
    elif kind == "TargetSortByFormation":
        payload["sort"] = {"sort_key": "formation_position", "sort_kind": kind, "position_source": "UnitState.flags.position"}
    return payload


def _effect_coverage_status(opcode: str, payload: dict[str, Any]) -> str:
    if opcode == "AddModifier":
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if not standard.get("modifier_name"):
            return "blocked"
        if standard.get("target_expression_coverage_status") == "executable":
            return "executable"
        if standard.get("target_alias") in ADD_MODIFIER_TARGET_ALIASES | STATUS_CALLBACK_LIST_TARGET_ALIASES:
            return "executable"
        return "blocked"
    if opcode in REMOVE_MODIFIER_OPCODES:
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        has_modifier = isinstance(standard.get("modifier_name"), str) and bool(standard.get("modifier_name"))
        has_status = isinstance(standard.get("status_id"), str) and bool(standard.get("status_id"))
        if (has_modifier or has_status) and standard.get("target_alias") in EXECUTABLE_TARGET_ALIASES | STATUS_CALLBACK_LIST_TARGET_ALIASES:
            return "executable"
        return "blocked"
    if opcode in DISPEL_STATUS_OPCODES:
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if standard.get("blocked_reason"):
            return "blocked"
        if standard.get("target_expression_coverage_status") == "executable":
            return "executable"
        if standard.get("target_alias") in ADD_MODIFIER_TARGET_ALIASES | STATUS_CALLBACK_LIST_TARGET_ALIASES:
            return "executable"
        return "blocked"
    if opcode in HEAL_OPCODES | SHIELD_OPCODES:
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if standard.get("blocked_reason"):
            return "blocked"
        if standard.get("target_alias") not in EXECUTABLE_TARGET_ALIASES:
            return "blocked"
        if not _numeric_expr_can_be_runtime_bound(standard.get("amount")):
            return "blocked"
        return "executable"
    if opcode in MECHANISM_BAR_OPCODES:
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if _mechanism_bar_has_runtime_payload(standard):
            return "executable"
        return "blocked"
    if opcode in RESOURCE_DELTA_OPCODES:
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if standard.get("blocked_reason"):
            return "blocked"
        if standard.get("target_alias") not in EXECUTABLE_TARGET_ALIASES:
            return "blocked"
        if not isinstance(standard.get("resource"), str):
            return "blocked"
        if not _numeric_expr_can_be_runtime_bound(standard.get("amount")):
            return "blocked"
        return "executable"
    if opcode in HP_LOSS_OPCODES:
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if standard.get("blocked_reason"):
            return "blocked"
        if standard.get("target_alias") not in EXECUTABLE_TARGET_ALIASES:
            return "blocked"
        if standard.get("ratio_type") not in {"MaxHP", "CurrentHP"}:
            return "blocked"
        if not _numeric_expr_can_be_runtime_bound(standard.get("ratio")):
            return "blocked"
        return "executable"
    if opcode == "TriggerAbility":
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if not isinstance(standard.get("ability_name"), str) or not standard.get("ability_name"):
            return "blocked"
        if standard.get("target_alias") not in EXECUTABLE_TARGET_ALIASES:
            return "blocked"
        return "executable"
    if opcode == "DefineDynamicValue":
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if standard.get("target_alias") not in EXECUTABLE_TARGET_ALIASES | {"LevelEntity"}:
            return "blocked"
        if not isinstance(standard.get("value_name"), str) or not standard.get("value_name"):
            return "blocked"
        if not _numeric_expr_can_be_runtime_bound(standard.get("value_expr")):
            return "blocked"
        return "executable"
    if opcode == "SetDynamicValue":
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if standard.get("target_alias") not in EXECUTABLE_TARGET_ALIASES | {"LevelEntity"}:
            return "blocked"
        if not isinstance(standard.get("value_name"), str) or not standard.get("value_name"):
            return "blocked"
        if not _numeric_expr_can_be_runtime_bound(standard.get("value_expr")):
            return "blocked"
        return "executable"
    if opcode == "SetDynamicValueByAddValue":
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if standard.get("target_alias") not in EXECUTABLE_TARGET_ALIASES | {"LevelEntity"}:
            return "blocked"
        if not isinstance(standard.get("value_name"), str) or not standard.get("value_name"):
            return "blocked"
        if not _numeric_expr_can_be_runtime_bound(standard.get("add_value")):
            return "blocked"
        return "executable"
    if opcode == "SetDynamicValueByModifierValue":
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if standard.get("target_alias") not in EXECUTABLE_TARGET_ALIASES:
            return "blocked"
        if standard.get("source_target_alias") not in EXECUTABLE_TARGET_ALIASES:
            return "blocked"
        if not isinstance(standard.get("source_modifier"), str) or not standard.get("source_modifier"):
            return "blocked"
        if not isinstance(standard.get("target_value_name"), str) or not standard.get("target_value_name"):
            return "blocked"
        if standard.get("source_value_name") not in SUPPORTED_MODIFIER_VALUE_TYPES:
            return "blocked"
        if not _numeric_expr_can_be_runtime_bound(standard.get("multiplier")):
            return "blocked"
        return "executable"
    return classify_opcode(opcode)


def _predicate_task_status(condition: ConditionIR | None) -> tuple[str, str]:
    if condition is None:
        return "blocked", "missing_predicate_condition"
    if condition.coverage_status != "executable":
        return "blocked", f"condition_not_executable:{condition.coverage_status}:{condition.opcode}"
    return "lowered", ""


def _retarget_task_evidence(task: dict[str, Any]) -> dict[str, Any]:
    target_alias = _target_alias(task.get("TargetType")) or ""
    return {
        "target_alias": target_alias,
        "include_limbo": bool(task.get("IncludeLimbo")) if isinstance(task.get("IncludeLimbo"), bool) else False,
        "max_number_expr": _numeric_expr_summary(task.get("MaxNumber")),
        "candidate_policy": _retarget_candidate_policy(target_alias),
    }


def _retarget_candidate_policy(target_alias: str) -> dict[str, Any]:
    if target_alias == "ParamEntityAttackTargetList.SortByHP":
        return {
            "candidate_source": "event.param_entity_attack_target_ids_or_action_targets",
            "sort": "hp_ascending",
            "alive_targets_first": True,
            "fallback": "lowest_hp_alive_enemy_of_status_owner",
            "admission_status": "executable",
        }
    return {
        "candidate_source": target_alias,
        "admission_status": "blocked",
        "blocked_reason": f"retarget_alias_not_admitted:{target_alias or 'missing'}",
    }


def _retarget_task_status(condition: ConditionIR | None, child_task_ids: list[str]) -> tuple[str, str]:
    if condition is None:
        return "blocked", "missing_retarget_condition"
    if condition.coverage_status != "executable":
        return "blocked", f"condition_not_executable:{condition.coverage_status}:{condition.opcode}"
    if not child_task_ids:
        return "blocked", "retarget_child_task_missing"
    return "executable", ""


def _status_callback_task_admission(event: str, opcode: str, task: dict[str, Any]) -> tuple[str, str]:
    foundational_effect_events = {
        "OnBeforeSkillUse",
        "OnBeforeAttack",
        "OnAfterAttack",
        "OnAfterSkillUse",
        "OnActionEnd",
        "OnCreate",
        "OnDestroy",
        "OnEnterBattle",
        "OnListenTurnEnd",
        "OnBeforeInsertActionPrepare",
        "OnInsertActionStart",
        "OnInsertActionFinish",
        "OnListenInsertAbilityFinish",
        "OnCustomEvent",
        "OnAfterBeingAttacked",
        "OnListenBeforeSkillUse",
        "OnBeingBreak",
    }
    if opcode in QUEUE_INTENT_OPCODES:
        actor_target_alias = _queue_actor_target_alias(task, opcode)
        ability_target_alias = _queue_ability_target_alias(task, opcode)
        skill_index_expr = _queue_skill_index_expr(task, opcode)
        coverage_status, blocked_reason = _queue_intent_admission(
            task=task,
            opcode=opcode,
            source=IRSource(source_path="Config/ConfigGlobalModifier/_admission_probe.json", raw_type="QueueIntentAdmissionProbe", raw_id=opcode),
            actor_target_alias=actor_target_alias,
            ability_target_alias=ability_target_alias,
            ability_name=_queue_action_ref_or_ability_name(task, opcode),
            skill_index_expr=skill_index_expr,
            priority_source={"priority_ordering_admitted": True},
            abort_policy=_queue_abort_policy(task),
        )
        if blocked_reason == "queue_intent_source_mode_not_admitted":
            return "executable", ""
        return coverage_status, blocked_reason
    if event in {"OnTriggerDeath", "OnTriggerDeathrattle"} and opcode == "ModifySPNew":
        payload = _effect_payload(task, opcode, "")
        coverage = _effect_coverage_status(opcode, payload)
        if coverage == "executable":
            return "executable", ""
        return "blocked", _effect_blocked_reason(opcode, payload, coverage)
    if (
        event in {
            "OnTriggerDeath",
            "OnTriggerDeathrattle",
            "OnAfterSkillUse",
            "OnAfterBeingAttacked",
            "OnListenBeforeSkillUse",
            "OnBeingBreak",
            "OnListenAfterAttack",
            *foundational_effect_events,
        }
        and opcode in {"DefineDynamicValue", "SetDynamicValue", "SetDynamicValueByAddValue", "AddModifier", "RemoveModifier", "RemoveSelfModifier"}
    ):
        payload = _effect_payload(task, opcode, "")
        coverage = _effect_coverage_status(opcode, payload)
        if coverage == "executable":
            return "executable", ""
        return "blocked", _effect_blocked_reason(opcode, payload, coverage)
    if event in {"OnBeforeHitAll", "OnBeforeHit"} and opcode == "ModifyDamageData":
        terms = _damage_modifier_terms(task)
        unsupported = [term for term in terms if term.get("coverage_status") != "executable"]
        if unsupported:
            reason = str(unsupported[0].get("blocked_reason") or "modify_damage_data_term_not_executable")
            return "blocked", reason
        if not terms:
            return "blocked", "modify_damage_data_fields_missing"
        return "executable", ""
    if event in {"OnAfterHitAll", "OnAfterHit"} and opcode in {"SetDynamicValue", "SetDynamicValueByDamageDataProperty"}:
        if opcode == "SetDynamicValueByDamageDataProperty":
            dynamic_key = _value_field(task.get("DynamicKey"))
            property_name = _value_field(task.get("Property"))
            if not isinstance(dynamic_key, str) or not dynamic_key:
                return "blocked", "dynamic_value_name_required"
            if property_name not in {"Result_FinalDamageBase", "Result_FinalDamage"}:
                return "blocked", f"damage_data_property_not_admitted:{property_name}"
            return "executable", ""
        payload = _effect_payload(task, opcode, "")
        coverage = _effect_coverage_status(opcode, payload)
        if coverage == "executable":
            return "executable", ""
        return "blocked", _effect_blocked_reason(opcode, payload, coverage)
    if event == "OnAfterBeingAttacked" and opcode == "DamageByAttackProperty":
        attack_property = task.get("AttackProperty")
        if not isinstance(attack_property, dict):
            return "blocked", "attack_property_missing"
        attack_type = str(attack_property.get("AttackType") or task.get("AttackType") or "")
        if attack_type != "TrueDamage":
            return "blocked", f"being_attacked_damage_attack_type_not_admitted:{attack_type}"
        damage_value = _numeric_expr_summary(attack_property.get("DamageValue"))
        if not _numeric_expr_can_be_runtime_bound(damage_value):
            return "blocked", f"true_damage_value_not_executable:{damage_value.get('reason') or damage_value.get('kind')}"
        return "executable", ""
    if event == "OnBeforeDying" and opcode == "RemoveModifier":
        payload = _effect_payload(task, opcode, "")
        coverage = _effect_coverage_status(opcode, payload)
        if coverage == "executable":
            return "executable", ""
        return "blocked", _effect_blocked_reason(opcode, payload, coverage)
    if event == "OnListenAllowAction" and opcode == "RemoveSelfModifier":
        return "executable", ""
    if event not in {"OnStack", "OnPhase1", "OnListenTurnEnd"}:
        return "blocked", f"status_callback_event_not_admitted:{event}"
    if opcode == "DamageByAttackProperty":
        attack_property = task.get("AttackProperty")
        if not isinstance(attack_property, dict):
            return "blocked", "attack_property_missing"
        formula_type = str(attack_property.get("FormulaType") or "")
        attack_type = str(attack_property.get("AttackType") or task.get("AttackType") or "")
        if event != "OnPhase1":
            return "blocked", f"status_damage_event_not_admitted:{event}"
        if attack_type == "DOT" and formula_type != "ByBreakDamage":
            damage_value = _numeric_expr_summary(attack_property.get("DamageValue"))
            damage_percentage = _numeric_expr_summary(attack_property.get("DamagePercentage"))
            extra_formula_type = str(attack_property.get("ExtraFormulaType") or "")
            extra_damage_percentage = _numeric_expr_summary(attack_property.get("ExtraDamagePercentage"))
            if not _numeric_expr_can_be_runtime_bound(damage_value):
                if _numeric_expr_can_be_runtime_bound(damage_percentage):
                    if extra_formula_type and extra_formula_type != "ByDefence":
                        return "blocked", f"dot_extra_formula_type_not_admitted:{extra_formula_type}"
                    if extra_formula_type == "ByDefence" and not _numeric_expr_can_be_runtime_bound(extra_damage_percentage):
                        return "blocked", f"dot_extra_damage_percentage_not_executable:{extra_damage_percentage.get('reason') or extra_damage_percentage.get('kind')}"
                    return "executable", ""
                return "blocked", f"dot_damage_value_not_executable:{damage_value.get('reason') or damage_value.get('kind')}"
            if extra_formula_type and extra_formula_type != "ByDefence":
                return "blocked", f"dot_extra_formula_type_not_admitted:{extra_formula_type}"
            if extra_formula_type == "ByDefence" and not _numeric_expr_can_be_runtime_bound(extra_damage_percentage):
                return "blocked", f"dot_extra_damage_percentage_not_executable:{extra_damage_percentage.get('reason') or extra_damage_percentage.get('kind')}"
            return "executable", ""
        if formula_type != "ByBreakDamage":
            return "blocked", f"status_damage_formula_not_admitted:{formula_type}"
        if attack_type != "DOT":
            return "blocked", f"status_damage_attack_type_not_admitted:{attack_type}"
        scaling_expr = _numeric_expr_summary(attack_property.get("BreakDamagePercentage"))
        if not _numeric_expr_can_be_runtime_bound(scaling_expr):
            return "blocked", f"status_damage_scaling_not_executable:{scaling_expr.get('reason') or scaling_expr.get('kind')}"
        return "executable", ""
    if opcode in {"ModifyActionDelay", "SetActionDelay"}:
        if event not in {"OnStack", "OnListenTurnEnd"}:
            return "blocked", f"action_delay_event_not_admitted:{event}"
        if opcode == "ModifyActionDelay":
            return "blocked", "normalized_action_delay_scale_not_admitted"
        delay_expr = _action_delay_expr(task, opcode)
        if _numeric_expr_can_be_runtime_bound(delay_expr):
            return "executable", ""
        return "blocked", f"action_delay_numeric_not_executable:{delay_expr.get('reason') or delay_expr.get('kind')}"
    return "blocked", f"status_callback_task_opcode_not_admitted:{opcode}"


def _status_callback_source_admitted(relative_path: str) -> bool:
    return (
        relative_path == "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json"
        or _mainline_avatar_ability_source(relative_path)
        or _mainline_monster_ability_source(relative_path)
        or (_queue_source_candidate(relative_path) and not _queue_source_blocked(relative_path))
    )


def _status_callback_task_source_admitted(relative_path: str, event: str, opcode: str) -> bool:
    if _status_callback_source_admitted(relative_path):
        return True
    if (
        _queue_source_candidate(relative_path)
        and not _queue_source_blocked(relative_path)
        and event in {"OnTriggerDeath", "OnTriggerDeathrattle", "OnAfterSkillUse"}
        and opcode in {"SetDynamicValue", "AddModifier", "ModifySPNew"}
    ):
        return True
    return False


def _status_callback_source_mode(relative_path: str) -> str:
    if _status_callback_source_admitted(relative_path):
        if _mainline_avatar_ability_source(relative_path):
            return "mainline_avatar_ability"
        if _mainline_monster_ability_source(relative_path):
            return "mainline_monster_ability"
        return "mainline_global_modifier"
    if "Rogue" in relative_path or "Activity" in relative_path or "GridFight" in relative_path:
        return "special_mode_audit_only"
    return "mainline_unadmitted"


def _status_callback_scope_kind(event: str) -> str:
    if event in {"OnListenCharacterDie", "OnListenAllowAction"}:
        return "owner_local"
    if event in {"OnAfterDealHeal", "OnBeforeDealHeal"}:
        return "actor_local"
    if event in {
        "OnHPChange",
        "OnHPOverflow",
        "OnAfterBeingHeal",
        "OnBeforeBeingHeal",
        "OnShieldChange",
        "OnSPChange",
        "OnEnergyPointChange",
        "OnBeforeEnergyPointChange",
        "OnBeforeBeingStanceDamage",
        "OnBeingStanceDamage",
        "OnActionDelayEffect",
        "OnActionDelayEffectAll",
    }:
        return "being_hit_target_local"
    if event in {
        "OnBeforeHitAll",
        "OnAfterHitAll",
        "OnAfterSkillUse",
        "OnBeforeSkillUse",
        "OnBeforeAttack",
        "OnAfterAttack",
        "OnActionEnd",
        "OnBeforeInsertActionPrepare",
        "OnInsertActionStart",
        "OnInsertActionFinish",
        "OnListenInsertAbilityFinish",
    }:
        return "actor_local"
    if event in {
        "OnCreate",
        "OnDestroy",
        "OnStack",
        "OnPhase1",
        "OnModifierAdd",
        "OnModifierRemove",
        "OnAddModifierSuc",
        "OnModifierOnStack",
        "OnModifierDotAdd",
    }:
        return "status_local"
    if event.startswith("OnListen"):
        return "global_listener"
    if event.startswith("OnBeing") or "BeingHit" in event or "BeingAttacked" in event:
        return "being_hit_target_local"
    if "Hit" in event:
        return "per_hit_target_local"
    return "owner_local"


def _mainline_avatar_ability_source(relative_path: str) -> bool:
    if not relative_path.startswith("Config/ConfigAbility/Avatar/"):
        return False
    blocked_tokens = (
        "/Activity/",
        "/Rogue/",
        "/GridFight/",
        "/ElationBattle/",
        "/Fate/",
        "/Story/",
        "/Level/",
        "/SubLevelGraph/",
        "/TrialPlayer/",
    )
    return not any(token in relative_path for token in blocked_tokens)


def _mainline_monster_ability_source(relative_path: str) -> bool:
    if not relative_path.startswith("Config/ConfigAbility/Monster/"):
        return False
    return not _queue_source_blocked(relative_path)


def _status_damage_emission_from_task(
    *,
    callback_id: str,
    task_id: str,
    modifier_name: str,
    event: str,
    task: dict[str, Any],
    source: IRSource,
) -> StatusDamageEmissionIR | None:
    attack_property = task.get("AttackProperty")
    if not isinstance(attack_property, dict):
        return None
    formula_type = str(attack_property.get("FormulaType") or "")
    attack_type = str(attack_property.get("AttackType") or task.get("AttackType") or "")
    if formula_type == "ByBreakDamage":
        damage_formula_family = "break"
        scaling_expr = _numeric_expr_summary(attack_property.get("BreakDamagePercentage"))
        element_type = None
    elif attack_type == "TrueDamage":
        damage_formula_family = "true_damage"
        scaling_expr = _numeric_expr_summary(attack_property.get("DamageValue"))
        element_type = _attack_property_element_type(attack_property)
    elif attack_type == "DOT":
        damage_formula_family = "dot"
        scaling_expr = {
            "kind": "dot_attack_property",
            "damage_percentage": _numeric_expr_summary(attack_property.get("DamagePercentage")),
            "damage_percentage_basis": {
                "kind": "status_formula_binding",
                "supported": True,
                "formula_role": "dot_damage",
                "reason": "resolved_from_status_instance_formula_bindings",
            },
            "damage_value": _numeric_expr_summary(attack_property.get("DamageValue")),
            "formula_type": str(attack_property.get("FormulaType") or ""),
            "extra_formula_type": str(attack_property.get("ExtraFormulaType") or ""),
            "extra_damage_percentage": _numeric_expr_summary(attack_property.get("ExtraDamagePercentage")),
        }
        element_type = _attack_property_element_type(attack_property)
    else:
        return None
    coverage_status, blocked_reason = _status_callback_task_admission(event, "DamageByAttackProperty", task)
    if coverage_status == "executable" and not _status_callback_source_admitted(source.source_path):
        coverage_status = "blocked"
        blocked_reason = "status_callback_source_mode_not_admitted"
    return StatusDamageEmissionIR(
        status_damage_emission_id=f"status_damage_emission:{callback_id}:{task_id}",
        callback_id=callback_id,
        source_task_id=task_id,
        modifier_name=modifier_name,
        event=event,
        attack_type=attack_type,
        damage_formula_family=damage_formula_family,
        element_type=element_type,
        scaling_expr=scaling_expr,
        source=source,
        coverage_status=coverage_status,
        blocked_reason=blocked_reason,
    )


def _damage_modifier_from_task(
    *,
    callback_id: str,
    task_id: str,
    modifier_name: str,
    event: str,
    task: dict[str, Any],
    source: IRSource,
) -> DamageModifierIR:
    terms = tuple(_damage_modifier_terms(task))
    coverage_status, blocked_reason = _status_callback_task_admission(event, "ModifyDamageData", task)
    if coverage_status == "executable" and not _status_callback_source_admitted(source.source_path):
        coverage_status = "blocked"
        blocked_reason = "status_callback_source_mode_not_admitted"
    return DamageModifierIR(
        damage_modifier_id=f"damage_modifier:{callback_id}:{task_id}",
        callback_id=callback_id,
        source_task_id=task_id,
        modifier_name=modifier_name,
        event=event,
        target_alias="ParamEntity",
        modifier_terms=terms,
        source=source,
        coverage_status=coverage_status,
        blocked_reason=blocked_reason,
    )


def _damage_modifier_terms(task: dict[str, Any]) -> list[dict[str, Any]]:
    terms: list[dict[str, Any]] = []
    supported_fields = {
        "Attacker_CriticalChance": ("crit", "critical_chance", "attacker"),
        "Defender_DefenceAddedRatio": ("defense", "defender_defence_added_ratio", "defender"),
    }
    ignored = {"$type", "TaskList", "SuccessTaskList", "FailedTaskList", "CallbackConfig"}
    for field, value in task.items():
        if field in ignored:
            continue
        bucket_info = supported_fields.get(field)
        expr = _numeric_expr_summary(value)
        if bucket_info is None:
            terms.append(
                {
                    "field": field,
                    "bucket": "unknown",
                    "key": field,
                    "scope": "unknown",
                    "numeric_expr": expr,
                    "coverage_status": "blocked",
                    "blocked_reason": f"modify_damage_data_field_not_admitted:{field}",
                }
            )
            continue
        bucket, key, scope = bucket_info
        if not _numeric_expr_can_be_runtime_bound(expr):
            terms.append(
                {
                    "field": field,
                    "bucket": bucket,
                    "key": key,
                    "scope": scope,
                    "numeric_expr": expr,
                    "coverage_status": "blocked",
                    "blocked_reason": str(expr.get("reason") or f"modify_damage_data_value_not_executable:{field}"),
                }
            )
            continue
        terms.append(
            {
                "field": field,
                "bucket": bucket,
                "key": key,
                "scope": scope,
                "target_alias": "ParamEntity",
                "numeric_expr": expr,
                "coverage_status": "executable",
                "blocked_reason": "",
            }
        )
    return terms


def _action_delay_emission_from_task(
    *,
    callback_id: str,
    task_id: str,
    modifier_name: str,
    event: str,
    opcode: str,
    task: dict[str, Any],
    source: IRSource,
) -> ActionDelayEmissionIR:
    delay_mode = _value_field(task.get("DelayType")) or _value_field(task.get("ActionDelayType")) or _first_present_key(
        task,
        ("AddNormalizedValue", "SetNormalizedValue", "FixedValue", "Value"),
    )
    delay_expr = _action_delay_expr(task, opcode)
    coverage_status, blocked_reason = _status_callback_task_admission(event, opcode, task)
    if coverage_status == "executable" and not _status_callback_source_admitted(source.source_path):
        coverage_status = "blocked"
        blocked_reason = "status_callback_source_mode_not_admitted"
    return ActionDelayEmissionIR(
        action_delay_emission_id=f"action_delay_emission:{callback_id}:{task_id}",
        callback_id=callback_id,
        source_task_id=task_id,
        modifier_name=modifier_name,
        event=event,
        opcode=opcode,
        target_alias=_target_alias(task.get("TargetType")) or "ModifierOwnerEntity",
        delay_mode=str(delay_mode or opcode),
        delay_expr=delay_expr,
        source=source,
        coverage_status=coverage_status,
        blocked_reason=blocked_reason,
    )


def _action_delay_expr(task: dict[str, Any], opcode: str) -> dict[str, Any]:
    key = _first_present_key(
        task,
        (
            "AddNormalizedValue",
            "SetNormalizedValue",
            "FixedAddNormalizedValue",
            "FixedSetNormalizedValue",
            "DelayValue",
            "Value",
        ),
    )
    if not key:
        return {"kind": "missing", "value": None, "supported": False, "reason": "action_delay_value_missing"}
    expr = _numeric_expr_summary(task.get(key))
    expr["source_field"] = key
    expr["opcode"] = opcode
    return expr


def _lower_summon_monster_intents(
    *,
    ability_tasks: list[AbilityTaskIR],
    effects: list[EffectIR],
    combatant_profiles: list[CombatantProfileIR],
    monster_data_cards: list[MonsterDataCardIR],
) -> list[SummonMonsterIntentIR]:
    effect_by_id = {effect.effect_id: effect for effect in effects}
    profile_by_entity = {profile.entity_id: profile for profile in combatant_profiles}
    card_by_entity = {card.entity_ref: card for card in monster_data_cards}
    intents: list[SummonMonsterIntentIR] = []
    for task in sorted(ability_tasks, key=lambda item: item.task_id):
        if task.opcode != "SummonMonster":
            continue
        if task.action_id.startswith("standalone_ability:"):
            continue
        effect = effect_by_id.get(task.effect_id)
        payload = effect.payload if effect is not None else {}
        entries_raw = payload.get("SummonMonsterDataList") if isinstance(payload, dict) else None
        delay_policy = _summon_monster_delay_policy(payload if isinstance(payload, dict) else {}, task)
        entries: list[SummonMonsterEntryIR] = []
        if isinstance(entries_raw, list):
            for entry_index, raw_entry in enumerate(entries_raw):
                if not isinstance(raw_entry, dict):
                    continue
                entries.append(
                    _summon_monster_entry_from_raw(
                        task,
                        raw_entry,
                        entry_index,
                        profile_by_entity=profile_by_entity,
                        card_by_entity=card_by_entity,
                    )
                )
        source_admitted = _mainline_monster_ability_source(task.source.source_path)
        blocked_reasons: list[str] = []
        if not source_admitted:
            blocked_reasons.append("summon_monster_source_mode_not_admitted")
        if not entries:
            blocked_reasons.append("summon_monster_entries_missing")
        if delay_policy.get("admission_status") != "executable":
            blocked_reasons.append(str(delay_policy.get("blocked_reason") or "summon_monster_delay_ratio_not_admitted"))
        for entry in entries:
            if entry.coverage_status != "executable":
                blocked_reasons.append(entry.blocked_reason or f"summon_monster_entry_not_executable:{entry.coverage_status}")
        blocked_reason = ";".join(dict.fromkeys(reason for reason in blocked_reasons if reason))
        source = IRSource(
            source_path=task.source.source_path,
            raw_type="SummonMonsterIntent",
            raw_id=task.task_id,
            evidence={
                "source_task": task.to_json(),
                "effect": effect.to_json() if effect is not None else {},
                "entry_count": len(entries),
                "delay_policy": delay_policy,
                "source_admitted": source_admitted,
                "admission_policy": "mainline_monster_ability_fixed_monster_id_profile_card_zero_or_missing_delay_ratio",
            },
        )
        intents.append(
            SummonMonsterIntentIR(
                summon_intent_id=f"summon_monster_intent:{task.task_id}",
                source_task_id=task.task_id,
                owner_scope="caster",
                target_scope="summoned_monster_entries",
                delay_policy=delay_policy,
                entries=tuple(entries),
                source_event=task.callback_kind,
                source=source,
                coverage_status="blocked" if blocked_reason else "executable",
                blocked_reason=blocked_reason,
            )
        )
    return intents


def _summon_monster_delay_policy(payload: dict[str, Any], task: AbilityTaskIR) -> dict[str, Any]:
    if "DelayRatio" not in payload:
        return {
            "kind": "missing",
            "source_field": "SummonMonster.DelayRatio",
            "admission_status": "executable",
            "runtime_policy": "initial_action_value_full_av_times_delay_ratio",
            "value": 1.0,
            "reason": "DelayRatio field absent; current runtime uses the default full action value, equivalent to ratio 1.",
        }
    expr = _numeric_expr_summary(payload.get("DelayRatio"))
    resolution = _resolve_summon_numeric_expr(
        task,
        expr,
        source_kind="summon_monster_delay_ratio",
        binding_missing_reason="summon_monster_delay_ratio_dynamic_binding_source_missing",
    )
    policy: dict[str, Any] = {
        "kind": str(expr.get("kind") or "unknown"),
        "source_field": "SummonMonster.DelayRatio",
        "expr": expr,
        "raw": _json_safe(payload.get("DelayRatio")),
        "resolution": resolution,
    }
    if resolution.get("ok") is not True or not isinstance(resolution.get("value"), (int, float)):
        return {
            **policy,
            "admission_status": "blocked",
            "blocked_reason": str(resolution.get("blocked_reason") or "summon_monster_delay_ratio_dynamic_not_admitted"),
            "runtime_policy": "blocked_until_delay_ratio_timeline_semantics_admitted",
        }
    value = float(resolution["value"])
    policy["value"] = value
    if value < 0:
        return {
            **policy,
            "admission_status": "blocked",
            "blocked_reason": "summon_monster_delay_ratio_negative_not_admitted",
            "runtime_policy": "blocked_until_negative_delay_ratio_semantics_admitted",
        }
    return {
        **policy,
        "admission_status": "executable",
        "runtime_policy": "initial_action_value_full_av_times_delay_ratio",
        "reason": "DelayRatio is admitted as a non-negative multiplier over the default full action value.",
    }


def _summon_monster_entry_from_raw(
    task: AbilityTaskIR,
    raw_entry: dict[str, Any],
    entry_index: int,
    *,
    profile_by_entity: dict[str, CombatantProfileIR],
    card_by_entity: dict[str, MonsterDataCardIR],
) -> SummonMonsterEntryIR:
    monster_expr = _summon_monster_id_expr(raw_entry)
    monster_resolution = _resolve_summon_monster_id_expr(task, monster_expr)
    monster_value = monster_resolution.get("value") if monster_resolution.get("ok") is True else None
    blocked_reasons: list[str] = []
    if monster_value is None:
        if raw_entry.get("MonsterIDFromCustomValue") is not None:
            blocked_reasons.append(
                _summon_monster_id_unbound_reason(
                    monster_expr,
                    str(monster_resolution.get("blocked_reason") or "summon_monster_id_from_custom_value_not_admitted"),
                )
            )
        elif monster_expr.get("kind") == "dynamic_hash":
            blocked_reasons.append(
                _summon_monster_id_unbound_reason(
                    monster_expr,
                    str(monster_resolution.get("blocked_reason") or "summon_monster_dynamic_monster_id_not_admitted"),
                )
            )
        elif monster_expr.get("kind") == "postfix_expr":
            blocked_reasons.append(
                _summon_monster_id_unbound_reason(
                    monster_expr,
                    str(
                        monster_resolution.get("blocked_reason")
                        or f"summon_monster_monster_id_expr_not_admitted:{monster_expr.get('reason') or 'postfix_expr'}"
                    ),
                )
            )
        elif monster_expr.get("kind") == "missing":
            blocked_reasons.append("summon_monster_monster_id_missing")
        else:
            blocked_reasons.append("summon_monster_fixed_monster_id_missing")
    monster_raw_id = str(int(monster_value)) if monster_value is not None else ""
    monster_entity_ref = f"monster:{monster_raw_id}" if monster_raw_id else ""
    profile = profile_by_entity.get(monster_entity_ref)
    card = card_by_entity.get(monster_entity_ref)
    id_normalization = _summon_monster_fixed_id_normalization(
        monster_raw_id,
        profile_by_entity=profile_by_entity,
        card_by_entity=card_by_entity,
    )
    if (profile is None or card is None) and id_normalization.get("admission_status") == "executable":
        monster_raw_id = str(id_normalization["normalized_monster_id"])
        monster_entity_ref = f"monster:{monster_raw_id}"
        profile = profile_by_entity.get(monster_entity_ref)
        card = card_by_entity.get(monster_entity_ref)
    if monster_entity_ref:
        if profile is None:
            blocked_reasons.append("summon_monster_profile_source_missing")
        elif profile.coverage_status != "executable":
            blocked_reasons.append(
                f"summon_monster_profile_source_blocked:{profile.blocked_reason or 'combatant_profile_blocked'}"
            )
        if card is None:
            blocked_reasons.append("summon_monster_data_card_source_missing")
    location_type = str(raw_entry.get("LocationType") or "")
    supported_location_types = {"BeforeCaster", "AfterCaster", "First", "Last", "KeepOnFirst", "KeepOnLast"}
    if not location_type:
        blocked_reasons.append("summon_monster_location_type_missing")
    elif location_type not in supported_location_types:
        blocked_reasons.append(f"summon_monster_location_type_not_admitted:{location_type}")
    position_policy = {
        "kind": "relative_location_type",
        "location_type": location_type,
        "init_anim_state_name": str(raw_entry.get("InitAnimStateName") or ""),
        "source_field": "SummonMonsterDataList.LocationType",
        "admission_status": "executable" if location_type in supported_location_types else "blocked",
        "blocked_reason": "" if location_type in supported_location_types else f"summon_monster_location_type_not_admitted:{location_type or 'missing'}",
    }
    count_policy = {
        "kind": "implicit_single_entry",
        "source_field": "SummonMonsterDataList",
        "admission_status": "executable",
        "value": 1,
        "reason": "current raw SummonMonsterDataList entries have no Count field; each list item lowers to one spawn instance.",
    }
    level_policy = {
        "kind": "profile_base_stats_no_runtime_level_scaling",
        "admission_status": "executable" if profile is not None and profile.coverage_status == "executable" else "blocked",
        "source_basis": "CombatantProfileIR.base_stats",
        "profile_id": profile.profile_id if profile is not None else "",
    }
    if level_policy["admission_status"] != "executable":
        if monster_entity_ref:
            if profile is None:
                blocked_reasons.append("summon_monster_level_policy_profile_source_missing")
            else:
                blocked_reasons.append(
                    f"summon_monster_level_policy_profile_source_blocked:{profile.blocked_reason or 'combatant_profile_blocked'}"
                )
        else:
            blocked_reasons.append("summon_monster_level_policy_monster_id_unresolved")
    blocked_reason = ";".join(dict.fromkeys(reason for reason in blocked_reasons if reason))
    source = IRSource(
        source_path=task.source.source_path,
        raw_type="SummonMonsterDataList",
        raw_id=f"{task.task_id}:{entry_index}",
        evidence={
            "source_task_id": task.task_id,
            "entry_index": entry_index,
            "raw_entry": _json_safe(raw_entry),
            "monster_id_expr": monster_expr,
            "monster_id_resolution": monster_resolution,
            "monster_id_normalization": id_normalization,
            "position_policy": position_policy,
            "count_policy": count_policy,
            "level_policy": level_policy,
            "wave_clear_policy_basis": "p1_3_conservative_enemy_summon_counts",
        },
    )
    return SummonMonsterEntryIR(
        entry_id=f"summon_monster_entry:{task.task_id}:{entry_index}",
        monster_entity_ref=monster_entity_ref,
        monster_raw_id=monster_raw_id,
        position_policy=position_policy,
        count=1,
        level_policy=level_policy,
        wave_clear_policy="blocked" if blocked_reason else "counts",
        source=source,
        birth_template_id=_summoned_monster_birth_template_id(task.task_id, entry_index),
        coverage_status="blocked" if blocked_reason else "executable",
        blocked_reason=blocked_reason,
    )


def _summon_monster_fixed_id_normalization(
    monster_raw_id: str,
    *,
    profile_by_entity: dict[str, CombatantProfileIR],
    card_by_entity: dict[str, MonsterDataCardIR],
) -> dict[str, Any]:
    if not monster_raw_id or not monster_raw_id.endswith("00") or not monster_raw_id[:-2].isdigit():
        return {"admission_status": "not_applicable"}
    normalized = str(int(monster_raw_id) // 100)
    if normalized == monster_raw_id:
        return {"admission_status": "not_applicable"}
    normalized_ref = f"monster:{normalized}"
    profile = profile_by_entity.get(normalized_ref)
    card = card_by_entity.get(normalized_ref)
    if profile is None or profile.coverage_status != "executable" or card is None:
        return {
            "admission_status": "blocked",
            "blocked_reason": "summon_monster_fixed_id_x100_candidate_missing_profile_or_card",
            "raw_monster_id": monster_raw_id,
            "normalized_monster_id": normalized,
        }
    return {
        "admission_status": "executable",
        "normalization": "fixed_monster_id_x100_to_monster_config_id",
        "raw_monster_id": monster_raw_id,
        "normalized_monster_id": normalized,
        "normalized_entity_ref": normalized_ref,
        "profile_id": profile.profile_id,
        "card_id": card.card_id,
    }


def _summon_monster_id_expr(raw_entry: dict[str, Any]) -> dict[str, Any]:
    if raw_entry.get("MonsterID") is not None:
        expr = _numeric_expr_summary(raw_entry.get("MonsterID"))
        expr["source_field"] = "SummonMonsterDataList.MonsterID"
        return expr
    custom_value = raw_entry.get("MonsterIDFromCustomValue")
    if isinstance(custom_value, dict) and isinstance(custom_value.get("Hash"), int):
        return {
            "kind": "dynamic_hash",
            "hash": int(custom_value["Hash"]),
            "supported": True,
            "source_field": "SummonMonsterDataList.MonsterIDFromCustomValue.Hash",
            "raw": _json_safe(custom_value),
        }
    expr = _numeric_expr_summary(custom_value)
    expr["source_field"] = "SummonMonsterDataList.MonsterIDFromCustomValue"
    return expr


def _resolve_summon_monster_id_expr(task: AbilityTaskIR, monster_expr: dict[str, Any]) -> dict[str, Any]:
    result = _resolve_summon_numeric_expr(
        task,
        monster_expr,
        source_kind="dynamic_monster_id",
        binding_missing_reason="summon_monster_dynamic_binding_source_missing",
        fixed_source_kind="fixed_monster_id",
    )
    source_field = str(monster_expr.get("source_field") or "")
    if result.get("ok") is not True and source_field.endswith("MonsterIDFromCustomValue.Hash"):
        reason = str(result.get("blocked_reason") or "")
        if reason == "summon_monster_dynamic_binding_source_missing":
            result["blocked_reason"] = "custom_value_hash_to_name_binding_missing"
        elif reason.startswith("dynamic_hash_unbound:"):
            result["blocked_reason"] = f"custom_value_hash_unbound:{reason.removeprefix('dynamic_hash_unbound:')}"
        result["custom_value_binding_candidates"] = _custom_value_binding_candidates_from_task(task)
    return result


def _resolve_summon_numeric_expr(
    task: AbilityTaskIR,
    numeric_expr: dict[str, Any],
    *,
    source_kind: str,
    binding_missing_reason: str,
    fixed_source_kind: str | None = None,
) -> dict[str, Any]:
    fixed_value = _fixed_expr_value(numeric_expr)
    if fixed_value is not None:
        return {
            "ok": True,
            "value": float(fixed_value),
            "source_kind": fixed_source_kind or source_kind,
            "expr": numeric_expr,
            "source_trace": task.source.to_json(),
        }
    binding_sources = _numeric_binding_sources_from_task(task)
    if not binding_sources:
        return {
            "ok": False,
            "value": None,
            "source_kind": source_kind,
            "expr": numeric_expr,
            "blocked_reason": binding_missing_reason,
            "source_trace": task.source.to_json(),
        }
    result = RuleEvaluator().evaluate_numeric(
        numeric_expr,
        NumericEvaluationContext(
            binding_sources=binding_sources,
            source_trace=task.source.to_json(),
        ),
    )
    if result.ok and result.value is not None:
        return {
            "ok": True,
            "value": float(result.value),
            "source_kind": source_kind,
            "expr": numeric_expr,
            "bindings": result.bindings,
            "source_trace": result.source_trace,
        }
    return {
        "ok": False,
        "value": None,
        "source_kind": source_kind,
        "expr": numeric_expr,
        "bindings": result.bindings,
        "blocked_reason": result.blocked_reason or binding_missing_reason,
        "source_trace": result.source_trace,
    }


def _numeric_binding_sources_from_task(task: AbilityTaskIR) -> tuple[dict[str, Any], ...]:
    source_context = task.source.evidence.get("ability_source_context")
    if not isinstance(source_context, dict):
        return ()
    raw_sources = source_context.get("numeric_binding_sources")
    if not isinstance(raw_sources, list):
        return ()
    return tuple(source for source in raw_sources if isinstance(source, dict))


def _custom_value_binding_candidates_from_task(task: AbilityTaskIR) -> dict[str, Any]:
    source_context = task.source.evidence.get("ability_source_context")
    if not isinstance(source_context, dict):
        return {}
    candidates = source_context.get("custom_value_bindings")
    return dict(candidates) if isinstance(candidates, dict) else {}


def _summon_monster_id_unbound_reason(monster_expr: dict[str, Any], reason: str) -> str:
    source_field = str(monster_expr.get("source_field") or "")
    if source_field.endswith("MonsterIDFromCustomValue.Hash"):
        return f"summon_monster_id_from_custom_value_not_admitted:{reason}"
    if monster_expr.get("kind") == "dynamic_hash":
        return f"summon_monster_dynamic_monster_id_not_admitted:{reason}"
    if monster_expr.get("kind") == "postfix_expr":
        return f"summon_monster_monster_id_expr_not_admitted:{reason or 'postfix_expr'}"
    return reason or "summon_monster_fixed_monster_id_missing"


def _lower_assistant_ability_resolutions(
    queue_intents: list[QueueIntentIR],
    queue_resolutions: list[QueueResolutionIR],
) -> list[AssistantAbilityResolutionIR]:
    resolutions_by_intent = {resolution.queue_intent_id: resolution for resolution in queue_resolutions}
    assistant_resolutions: list[AssistantAbilityResolutionIR] = []
    for intent in sorted(queue_intents, key=lambda item: item.queue_intent_id):
        if intent.opcode != "TurnInsertAssistantAbility":
            continue
        resolution = resolutions_by_intent.get(intent.queue_intent_id)
        ability_id = ""
        value = _fixed_expr_value(intent.skill_index_expr)
        if value is not None:
            ability_id = str(int(value))
        blocked_reasons: list[str] = []
        if not ability_id:
            blocked_reasons.append("assistant_ability_id_missing_or_dynamic")
        if not intent.actor_target_alias:
            blocked_reasons.append("assistant_owner_alias_missing")
        if not intent.ability_target_alias:
            blocked_reasons.append("assistant_target_alias_missing")
        blocked_reasons.extend(
            (
                "assistant_actor_source_not_admitted",
                "assistant_stats_source_not_admitted",
                "assistant_action_graph_source_not_admitted",
            )
        )
        source = IRSource(
            source_path=intent.source.source_path,
            raw_type="AssistantAbilityResolution",
            raw_id=intent.queue_intent_id,
            evidence={
                "queue_intent": intent.to_json(),
                "queue_resolution": resolution.to_json() if resolution is not None else {},
                "admission_policy": "p1_3_assistant_requires_owner_target_graph_and_stats",
            },
        )
        assistant_resolutions.append(
            AssistantAbilityResolutionIR(
                assistant_resolution_id=f"assistant_ability_resolution:{intent.queue_intent_id}",
                queue_intent_id=intent.queue_intent_id,
                assistant_ability_id=ability_id,
                owner_alias=intent.actor_target_alias or "",
                target_alias=intent.ability_target_alias or "",
                resolved_graph_id="",
                attribution_policy={
                    "kind": "blocked",
                    "blocked_reason": "assistant_actor_source_not_admitted;assistant_stats_source_not_admitted;assistant_action_graph_source_not_admitted",
                    "actor_source": {
                        "coverage_status": "blocked",
                        "blocked_reason": "assistant_actor_source_not_admitted",
                    },
                    "stat_source": {
                        "coverage_status": "blocked",
                        "blocked_reason": "assistant_stats_source_not_admitted",
                    },
                    "action_graph_source": {
                        "coverage_status": "blocked",
                        "blocked_reason": "assistant_action_graph_source_not_admitted",
                        "assistant_ability_id": ability_id,
                    },
                    "source_queue_intent_id": intent.queue_intent_id,
                },
                source=source,
                coverage_status="blocked",
                blocked_reason=";".join(dict.fromkeys(blocked_reasons)),
            )
        )
    return assistant_resolutions


QUEUE_INTENT_OPCODES = {"TurnInsertAbility", "TurnInsertAction", "TurnInsertAssistantAbility"}
SKILL_CONTINUATION_OPCODES = {"UseSkillOneMore"}
QUEUE_TARGET_ALIASES = {
    "Caster",
    "ModifierOwnerEntity",
    "ParamEntity",
    "CurrentActionTarget",
    "DamageAttackerEntity",
    "AbilityTargetEntity",
    "ModifierOwnerSkillTargetEntityList",
    "ParamEntitySkillTargetEntityList",
    "AllEnemy",
    "AllTeamMember",
    "AllLightTeam",
}


def _queue_intent_from_task(
    *,
    callback_id: str,
    task_id: str,
    event: str,
    opcode: str,
    task: dict[str, Any],
    source: IRSource,
    queue_priority_lookup: dict[tuple[str, str], QueuePriorityIR],
) -> QueueIntentIR:
    queue_kind = {
        "TurnInsertAbility": "turn_insert_ability",
        "TurnInsertAction": "turn_insert_action",
        "TurnInsertAssistantAbility": "turn_insert_assistant_ability",
    }.get(opcode, "unknown")
    actor_target_alias = _queue_actor_target_alias(task, opcode)
    ability_target_alias = _queue_ability_target_alias(task, opcode)
    ability_name = _queue_action_ref_or_ability_name(task, opcode)
    skill_index_expr = _queue_skill_index_expr(task, opcode)
    priority_source = _queue_priority_source(task, opcode, queue_priority_lookup)
    abort_policy = _queue_abort_policy(task)
    coverage_status, blocked_reason = _queue_intent_admission(
        task=task,
        opcode=opcode,
        source=source,
        actor_target_alias=actor_target_alias,
        ability_target_alias=ability_target_alias,
        ability_name=ability_name,
        skill_index_expr=skill_index_expr,
        priority_source=priority_source,
        abort_policy=abort_policy,
    )
    return QueueIntentIR(
        queue_intent_id=f"queue_intent:{callback_id}:{task_id}",
        source_task_id=task_id,
        callback_id=callback_id,
        phase_id="",
        opcode=opcode,
        queue_kind=queue_kind,
        priority_source=priority_source,
        actor_target_alias=actor_target_alias,
        action_ref_or_ability_name=str(ability_name or ""),
        skill_index_expr=skill_index_expr,
        ability_target_alias=ability_target_alias,
        auto_cast=bool(task.get("AutoCast")) if isinstance(task.get("AutoCast"), bool) else False,
        abort_policy=abort_policy,
        source=source,
        coverage_status=coverage_status,
        blocked_reason=blocked_reason,
    )


def _skill_continuation_from_task(task: AbilityTaskIR) -> SkillContinuationIR:
    raw_task = task.source.evidence.get("task") if isinstance(task.source.evidence, dict) else None
    task_payload = raw_task if isinstance(raw_task, dict) else {}
    skill_type = _value_field(task_payload.get("SkillType"))
    child_index = _numeric_expr_summary(task_payload.get("ChildSkillIndex"))
    child_index["source_field"] = "ChildSkillIndex"
    child_index["opcode"] = task.opcode
    return SkillContinuationIR(
        continuation_id=f"skill_continuation:{task.task_id}",
        source_task_id=task.task_id,
        phase_id=task.phase_id,
        action_id=task.action_id,
        level=task.level,
        ability_name=task.ability_name,
        opcode=task.opcode,
        continuation_kind="ultimate_or_skill_internal_sequence",
        fixed_skill_type=str(skill_type or ""),
        child_skill_index_expr=child_index,
        source=task.source,
        coverage_status="blocked",
        blocked_reason=(
            "skill_continuation_not_queue_extra_turn:"
            "requires source-specific continuation runner and fixed action segment admission"
        ),
    )


def _skill_continuations_from_ability_tasks(tasks: list[AbilityTaskIR]) -> list[SkillContinuationIR]:
    continuations: list[SkillContinuationIR] = []
    seen: set[str] = set()
    for task in tasks:
        if task.opcode not in SKILL_CONTINUATION_OPCODES:
            continue
        continuation = _skill_continuation_from_task(task)
        if continuation.continuation_id in seen:
            continue
        seen.add(continuation.continuation_id)
        continuations.append(continuation)
    return continuations


def _queue_skill_index_expr(task: dict[str, Any], opcode: str) -> dict[str, Any]:
    if opcode == "TurnInsertAction":
        if _queue_prepare_ability_name(task):
            return {
                "kind": "none",
                "value": None,
                "supported": True,
                "source_field": "PrepareAbilityName",
                "opcode": opcode,
                "action_selection": "route_or_source_selected_action",
            }
        skill_type = _queue_skill_type_action_selection(task)
        if skill_type:
            return {
                "kind": "skill_type",
                "value": skill_type["skill_type"],
                "supported": skill_type["skill_index"] is not None,
                "source_field": "SkillType",
                "opcode": opcode,
                "skill_index": skill_type["skill_index"],
                "action_kind": skill_type["action_kind"],
                "source_basis": skill_type["source_basis"],
            }
        expr = _numeric_expr_summary(task.get("SkillIndex"))
        expr["source_field"] = "SkillIndex"
        expr["opcode"] = opcode
        return expr
    if opcode == "TurnInsertAssistantAbility":
        expr = _numeric_expr_summary(task.get("AssistantAbilityID"))
        expr["source_field"] = "AssistantAbilityID"
        expr["opcode"] = opcode
        return expr
    return {"kind": "none", "value": None, "supported": True, "source_field": "", "opcode": opcode}


def _queue_priority_source(
    task: dict[str, Any],
    opcode: str,
    queue_priority_lookup: dict[tuple[str, str], QueuePriorityIR],
) -> dict[str, Any]:
    key = {
        "TurnInsertAbility": "InsertAbilityPriority",
        "TurnInsertAction": "InsertActionPriority",
        "TurnInsertAssistantAbility": "InsertAbilityPriority",
    }.get(opcode, "InsertPriority")
    priority_table = "InsertActionPriority" if opcode == "TurnInsertAction" else "InsertAbilityPriority"
    priority_key = task.get(key)
    if priority_key is None and opcode == "TurnInsertAction" and (
        _queue_prepare_ability_name(task) or _queue_skill_type_action_selection(task)
    ):
        priority_key = "PROG_Default"
    priority = queue_priority_lookup.get((priority_table, str(priority_key))) if priority_key is not None else None
    if priority is not None:
        return {
            "field": key,
            "priority_table": priority_table,
            "priority_key": priority.priority_key,
            "priority_value": priority.priority_value,
            "queue_priority_id": priority.queue_priority_id,
            "priority_ordering_admitted": True,
            "source_trace": priority.source.to_json(),
        }
    return {
        "field": key,
        "priority_table": priority_table,
        "priority_key": str(priority_key or ""),
        "value": _json_safe(priority_key),
        "priority_ordering_admitted": False,
        "reason": f"queue_priority_key_not_admitted:{priority_table}:{priority_key or 'missing'}",
    }


def _queue_abort_policy(task: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "OnInsertAbort": _json_safe(task.get("OnInsertAbort")),
        "AbortBehaviorFlags": _json_safe(task.get("AbortBehaviorFlags")),
        "OwnerAliveState": _json_safe(task.get("OwnerAliveState")),
        "TargetAliveState": _json_safe(task.get("TargetAliveState")),
        "CanRunOnUnselectableTarget": _json_safe(task.get("CanRunOnUnselectableTarget")),
        "ShowInActionBar": _json_safe(task.get("ShowInActionBar")),
        "IgnoreBPDec": _json_safe(task.get("IgnoreBPDec")),
        "CustomTag": _json_safe(task.get("CustomTag")),
        "PreCheck": _json_safe(task.get("PreCheck")),
    }
    policy = {key: value for key, value in fields.items() if value not in (None, [], {})}
    if policy.get("IgnoreBPDec") is True:
        policy["resource_policy"] = {
            "ignore_skill_point_delta": True,
            "ignore_energy_gain": True,
            "source_field": "IgnoreBPDec",
            "source_basis": "tbgd_turn_insert_action_ignore_bp_dec",
        }
    insert_once_policy = _queue_insert_once_policy(task)
    if insert_once_policy:
        policy["insert_once_policy"] = insert_once_policy
    return policy


def _queue_prepare_ability_name(task: dict[str, Any]) -> str:
    value = _value_field(task.get("PrepareAbilityName"))
    return value if isinstance(value, str) and value else ""


def _queue_insert_once_policy(task: dict[str, Any]) -> dict[str, Any]:
    precheck = task.get("PreCheck")
    if not isinstance(precheck, dict):
        return {}
    if precheck.get("GMPGDEINODK") != "SameTagInsertUnusedCount":
        return {}
    max_count = _numeric_expr_summary(precheck.get("HOCMHABKLGJ"))
    custom_tag = _value_field(task.get("CustomTag"))
    used_modifiers: list[str] = []
    for abort_task in task.get("OnInsertAbort", ()) if isinstance(task.get("OnInsertAbort"), list) else ():
        if not isinstance(abort_task, dict):
            continue
        opcode = str(abort_task.get("$type") or "").rsplit(".", 1)[-1]
        if opcode != "AddModifier":
            continue
        modifier_name = _value_field(abort_task.get("ModifierName"))
        if isinstance(modifier_name, str) and modifier_name:
            used_modifiers.append(modifier_name)
    return {
        "kind": "same_tag_insert_unused_count",
        "max_count_expr": max_count,
        "custom_tag": custom_tag if isinstance(custom_tag, str) else "",
        "used_modifier_names": used_modifiers,
        "source_field": "PreCheck",
        "source_basis": "tbgd_turn_insert_action_same_tag_insert_unused_count",
    }


def _queue_skill_type_action_selection(task: dict[str, Any]) -> dict[str, Any] | None:
    value = _value_field(task.get("SkillType"))
    if not isinstance(value, str) or not value:
        return None
    normalized = value.lower()
    if normalized in {"normal", "controlskill01"}:
        return {
            "skill_type": value,
            "skill_index": 0,
            "action_kind": "basic",
            "source_basis": "tbgd_turn_insert_action_skill_type",
        }
    if normalized in {"skill", "controlskill02"}:
        return {
            "skill_type": value,
            "skill_index": 1,
            "action_kind": "skill",
            "source_basis": "tbgd_turn_insert_action_skill_type",
        }
    if normalized in {"ultra", "ultimate", "controlskill03"}:
        return {
            "skill_type": value,
            "skill_index": 2,
            "action_kind": "ultimate",
            "source_basis": "tbgd_turn_insert_action_skill_type",
        }
    return {
        "skill_type": value,
        "skill_index": None,
        "action_kind": "unknown",
        "source_basis": "tbgd_turn_insert_action_skill_type_not_admitted",
    }


def _queue_action_ref_or_ability_name(task: dict[str, Any], opcode: str) -> Any:
    if opcode == "TurnInsertAction":
        prepared = _queue_prepare_ability_name(task)
        if prepared:
            return prepared
        skill_type = _queue_skill_type_action_selection(task)
        if skill_type:
            return f"skill_type:{skill_type['skill_type']}"
    return _value_field(task.get("AbilityName"))


def _queue_actor_target_alias(task: dict[str, Any], opcode: str) -> str | None:
    alias = _target_alias(task.get("TargetType"))
    if alias:
        return alias
    if opcode == "TurnInsertAbility":
        return "ModifierOwnerEntity"
    if opcode == "TurnInsertAction" and (_queue_prepare_ability_name(task) or _queue_skill_type_action_selection(task)):
        return "ModifierOwnerEntity"
    return None


def _queue_ability_target_alias(task: dict[str, Any], opcode: str) -> str | None:
    alias = _target_alias(task.get("AbilityTarget")) or _target_alias(task.get("AutoCastTargetType"))
    if alias:
        return alias
    if opcode == "TurnInsertAction" and _queue_prepare_ability_name(task):
        return None
    return None


def _queue_intent_admission(
    *,
    task: dict[str, Any],
    opcode: str,
    source: IRSource,
    actor_target_alias: str | None,
    ability_target_alias: str | None,
    ability_name: Any,
    skill_index_expr: dict[str, Any],
    priority_source: dict[str, Any],
    abort_policy: dict[str, Any],
) -> tuple[str, str]:
    if not _queue_intent_source_admitted(source.source_path):
        return "blocked", "queue_intent_source_mode_not_admitted"
    if actor_target_alias not in QUEUE_TARGET_ALIASES:
        return "blocked", f"queue_actor_target_alias_not_admitted:{actor_target_alias or 'missing'}"
    if ability_target_alias and ability_target_alias not in QUEUE_TARGET_ALIASES:
        return "blocked", f"queue_ability_target_alias_not_admitted:{ability_target_alias}"
    if priority_source.get("priority_ordering_admitted") is not True:
        return "blocked", str(priority_source.get("reason") or "queue_priority_not_admitted")
    if abort_policy.get("OnInsertAbort"):
        if not (
            opcode == "TurnInsertAction"
            and (_queue_prepare_ability_name(task) or _queue_skill_type_action_selection(task))
        ):
            return "blocked", "queue_abort_policy_not_admitted"
    if opcode == "TurnInsertAbility":
        if not isinstance(ability_name, str) or not ability_name:
            return "blocked", "queue_insert_ability_name_missing"
        return "executable", ""
    if opcode == "TurnInsertAction":
        if _queue_prepare_ability_name(task):
            return "executable", ""
        if skill_index_expr.get("kind") == "skill_type":
            if isinstance(skill_index_expr.get("skill_index"), int):
                return "executable", ""
            return "blocked", f"queue_insert_action_skill_type_not_admitted:{skill_index_expr.get('value') or 'missing'}"
        if skill_index_expr.get("kind") != "fixed":
            return "blocked", f"queue_insert_action_skill_index_not_admitted:{skill_index_expr.get('kind') or 'missing'}"
        return "executable", ""
    if opcode == "TurnInsertAssistantAbility":
        return "blocked", "queue_insert_assistant_ability_not_admitted"
    return "blocked", f"queue_opcode_not_admitted:{opcode}"


def _queue_intent_source_admitted(relative_path: str) -> bool:
    if not _queue_source_candidate(relative_path):
        return False
    return not _queue_source_blocked(relative_path)


def _standalone_ability_source_admitted(relative_path: str) -> bool:
    return relative_path.startswith("Config/ConfigAbility/") and _queue_source_candidate(relative_path) and not _queue_source_blocked(relative_path)


def _standalone_ability_source_mode(relative_path: str) -> str:
    if relative_path.startswith("Config/ConfigAbility/Avatar/"):
        return "mainline_avatar"
    if relative_path.startswith("Config/ConfigAbility/Monster/"):
        return "mainline_monster"
    if relative_path.startswith("Config/ConfigAbility/BattleEventAbility"):
        return "mainline_battle_event"
    if relative_path.endswith("Config/ConfigAbility/Common_Additional_Ability.json"):
        return "mainline_common_additional"
    return "blocked_or_unknown"


def _queue_source_candidate(relative_path: str) -> bool:
    return (
        relative_path.startswith("Config/ConfigGlobalModifier/")
        or relative_path.startswith("Config/ConfigAbility/Avatar/")
        or relative_path.startswith("Config/ConfigAbility/Monster/")
        or relative_path.startswith("Config/ConfigAbility/BattleEventAbility")
        or relative_path == "Config/ConfigAbility/Common_Additional_Ability.json"
    )


def _queue_source_blocked(relative_path: str) -> bool:
    blocked_markers = ("Rogue", "Activity", "GridFight", "ElationBattle", "Fate", "Story", "Level/", "SubLevelGraph", "Chess")
    return any(marker in relative_path for marker in blocked_markers)


def _lower_queue_resolutions(
    *,
    queue_intents: list[QueueIntentIR],
    action_bindings: list[ActionAbilityBindingIR],
    ability_phases: list[AbilityPhaseIR],
    standalone_graphs: list[StandaloneAbilityGraphIR],
    combatant_action_sets: list[CombatantActionSetIR],
) -> list[QueueResolutionIR]:
    phases_by_ability: dict[str, list[AbilityPhaseIR]] = {}
    for phase in ability_phases:
        phases_by_ability.setdefault(phase.ability_name, []).append(phase)
    bindings_by_action: dict[tuple[str, int], ActionAbilityBindingIR] = {
        (binding.action_id, binding.level): binding for binding in action_bindings
    }
    standalone_by_ability: dict[str, list[StandaloneAbilityGraphIR]] = {}
    for graph in standalone_graphs:
        standalone_by_ability.setdefault(graph.ability_name, []).append(graph)
    resolutions: list[QueueResolutionIR] = []
    for intent in queue_intents:
        resolutions.append(
            _queue_resolution_from_intent(
                intent,
                phases_by_ability=phases_by_ability,
                bindings_by_action=bindings_by_action,
                standalone_by_ability=standalone_by_ability,
                combatant_action_sets=combatant_action_sets,
            )
        )
    return resolutions


def _queue_resolution_from_intent(
    intent: QueueIntentIR,
    *,
    phases_by_ability: dict[str, list[AbilityPhaseIR]],
    bindings_by_action: dict[tuple[str, int], ActionAbilityBindingIR],
    standalone_by_ability: dict[str, list[StandaloneAbilityGraphIR]],
    combatant_action_sets: list[CombatantActionSetIR],
) -> QueueResolutionIR:
    source = IRSource(
        source_path=intent.source.source_path,
        raw_type="QueueResolution",
        raw_id=intent.queue_intent_id,
        evidence={
            "queue_intent_id": intent.queue_intent_id,
            "queue_intent_source": intent.source.to_json(),
            "opcode": intent.opcode,
            "queue_kind": intent.queue_kind,
        },
    )
    resolution_id = f"queue_resolution:{intent.queue_intent_id}"
    if intent.coverage_status != "executable":
        reason = intent.blocked_reason or f"queue_intent_not_executable:{intent.coverage_status}"
        return QueueResolutionIR(
            queue_resolution_id=resolution_id,
            queue_intent_id=intent.queue_intent_id,
            action_or_ability_ref=intent.action_ref_or_ability_name,
            resolved_kind="blocked_intent",
            resolved_ids={},
            source=source,
            coverage_status="blocked",
            blocked_reason=f"queue_intent_not_executable:{reason}",
        )
    if intent.opcode == "TurnInsertAbility":
        ability_name = intent.action_ref_or_ability_name
        if not ability_name:
            return QueueResolutionIR(
                queue_resolution_id=resolution_id,
                queue_intent_id=intent.queue_intent_id,
                action_or_ability_ref=ability_name,
                resolved_kind="missing_ability_name",
                resolved_ids={},
                source=source,
                coverage_status="blocked",
                blocked_reason="queue_ability_name_missing",
            )
        graph_candidates = tuple(sorted(standalone_by_ability.get(ability_name, ()), key=lambda item: item.standalone_ability_graph_id))
        same_source_graphs = tuple(graph for graph in graph_candidates if graph.source.source_path == intent.source.source_path)
        selected_graphs = same_source_graphs or graph_candidates
        if len(selected_graphs) > 1:
            return QueueResolutionIR(
                queue_resolution_id=resolution_id,
                queue_intent_id=intent.queue_intent_id,
                action_or_ability_ref=ability_name,
                resolved_kind="ambiguous_standalone_ability_graph",
                resolved_ids={
                    "candidate_graph_ids": [graph.standalone_ability_graph_id for graph in selected_graphs],
                    "candidate_source_paths": [graph.source.source_path for graph in selected_graphs],
                },
                source=source,
                coverage_status="blocked",
                blocked_reason=f"queue_ability_graph_ambiguous:{ability_name}",
            )
        if len(selected_graphs) == 1:
            graph = selected_graphs[0]
            if graph.coverage_status != "executable":
                return QueueResolutionIR(
                    queue_resolution_id=resolution_id,
                    queue_intent_id=intent.queue_intent_id,
                    action_or_ability_ref=ability_name,
                    resolved_kind="standalone_ability_graph_blocked",
                    resolved_ids={"standalone_ability_graph_id": graph.standalone_ability_graph_id},
                    source=source,
                    coverage_status="blocked",
                    blocked_reason=graph.blocked_reason or f"standalone_ability_graph_not_executable:{graph.coverage_status}",
                )
            return QueueResolutionIR(
                queue_resolution_id=resolution_id,
                queue_intent_id=intent.queue_intent_id,
                action_or_ability_ref=ability_name,
                resolved_kind="standalone_ability_graph",
                resolved_ids={
                    "standalone_ability_graph_id": graph.standalone_ability_graph_id,
                    "phase_ids": list(graph.phase_ids),
                    "task_ids": list(graph.task_ids),
                    "executable_task_ids": list(graph.executable_task_ids),
                    "source_mode": graph.source_mode,
                },
                source=source,
                coverage_status="executable",
                blocked_reason="",
            )
        phases = tuple(sorted(phases_by_ability.get(ability_name, ()), key=lambda item: item.phase_id))
        if not phases:
            return QueueResolutionIR(
                queue_resolution_id=resolution_id,
                queue_intent_id=intent.queue_intent_id,
                action_or_ability_ref=ability_name,
                resolved_kind="unresolved_ability_name",
                resolved_ids={},
                source=source,
                coverage_status="blocked",
                blocked_reason=f"queue_ability_graph_not_lowered_or_missing:{ability_name}",
            )
        action_keys = tuple(sorted({(phase.action_id, phase.level) for phase in phases}))
        binding_ids = tuple(
            binding.binding_id
            for key in action_keys
            for binding in (bindings_by_action.get(key),)
            if binding is not None
        )
        return QueueResolutionIR(
            queue_resolution_id=resolution_id,
            queue_intent_id=intent.queue_intent_id,
            action_or_ability_ref=ability_name,
            resolved_kind="ability_phase_graph",
            resolved_ids={
                "phase_ids": [phase.phase_id for phase in phases],
                "task_ids": [task_id for phase in phases for task_id in phase.task_ids],
                "action_keys": [f"{action_id}:{level}" for action_id, level in action_keys],
                "binding_ids": list(binding_ids),
            },
            source=source,
            coverage_status="executable",
            blocked_reason="",
        )
    if intent.opcode == "TurnInsertAction":
        if intent.action_ref_or_ability_name and intent.skill_index_expr.get("source_field") == "PrepareAbilityName":
            return QueueResolutionIR(
                queue_resolution_id=resolution_id,
                queue_intent_id=intent.queue_intent_id,
                action_or_ability_ref=intent.action_ref_or_ability_name,
                resolved_kind="extra_turn_action_choice",
                resolved_ids={
                    "prepare_ability_name": intent.action_ref_or_ability_name,
                    "action_selection": "route_or_source_selected_action",
                    "skill_index_expr": _json_safe(intent.skill_index_expr),
                },
                source=source,
                coverage_status="executable",
                blocked_reason="",
            )
        if intent.skill_index_expr.get("kind") == "skill_type":
            skill_index = intent.skill_index_expr.get("skill_index")
            if not isinstance(skill_index, int):
                reason = f"queue_insert_action_skill_type_not_admitted:{intent.skill_index_expr.get('value') or 'missing'}"
                return QueueResolutionIR(
                    queue_resolution_id=resolution_id,
                    queue_intent_id=intent.queue_intent_id,
                    action_or_ability_ref=intent.action_ref_or_ability_name,
                    resolved_kind="insert_action_not_admitted",
                    resolved_ids={"skill_index_expr": _json_safe(intent.skill_index_expr)},
                    source=source,
                    coverage_status="blocked",
                    blocked_reason=reason,
                )
            return _queue_action_definition_resolution(
                intent,
                source,
                resolution_id,
                str(skill_index),
                combatant_action_sets,
            )
        if intent.skill_index_expr.get("kind") != "fixed":
            reason = f"queue_insert_action_skill_index_not_admitted:{intent.skill_index_expr.get('kind') or 'missing'}"
            return QueueResolutionIR(
                queue_resolution_id=resolution_id,
                queue_intent_id=intent.queue_intent_id,
                action_or_ability_ref=intent.action_ref_or_ability_name,
                resolved_kind="insert_action_not_admitted",
                resolved_ids={"skill_index_expr": _json_safe(intent.skill_index_expr)},
                source=source,
                coverage_status="blocked",
                blocked_reason=reason,
            )
        skill_index_value = intent.skill_index_expr.get("value")
        if not isinstance(skill_index_value, (int, float)):
            return QueueResolutionIR(
                queue_resolution_id=resolution_id,
                queue_intent_id=intent.queue_intent_id,
                action_or_ability_ref=intent.action_ref_or_ability_name,
                resolved_kind="insert_action_not_admitted",
                resolved_ids={"skill_index_expr": _json_safe(intent.skill_index_expr)},
                source=source,
                coverage_status="blocked",
                blocked_reason="queue_insert_action_skill_index_value_missing",
            )
        skill_index_key = str(int(skill_index_value))
        return _queue_action_definition_resolution(
            intent,
            source,
            resolution_id,
            skill_index_key,
            combatant_action_sets,
        )
    if intent.opcode == "TurnInsertAssistantAbility":
        return QueueResolutionIR(
            queue_resolution_id=resolution_id,
            queue_intent_id=intent.queue_intent_id,
            action_or_ability_ref=intent.action_ref_or_ability_name,
            resolved_kind="assistant_ability_not_admitted",
            resolved_ids={"assistant_ability_expr": _json_safe(intent.skill_index_expr)},
            source=source,
            coverage_status="blocked",
            blocked_reason="queue_insert_assistant_ability_not_admitted",
        )
    return QueueResolutionIR(
        queue_resolution_id=resolution_id,
        queue_intent_id=intent.queue_intent_id,
        action_or_ability_ref=intent.action_ref_or_ability_name,
        resolved_kind="queue_opcode_not_admitted",
        resolved_ids={},
        source=source,
        coverage_status="blocked",
        blocked_reason=f"queue_opcode_not_admitted:{intent.opcode}",
    )


def _queue_action_definition_resolution(
    intent: QueueIntentIR,
    source: IRSource,
    resolution_id: str,
    skill_index_key: str,
    combatant_action_sets: list[CombatantActionSetIR],
) -> QueueResolutionIR:
    candidates: list[dict[str, Any]] = []
    for action_set in sorted(combatant_action_sets, key=lambda item: item.combatant_action_set_id):
        if action_set.coverage_status != "executable":
            continue
        entry = action_set.skill_index_map.get(skill_index_key)
        if not isinstance(entry, dict) or entry.get("coverage_status") != "executable":
            continue
        action_ref = entry.get("action_ref")
        default_level = entry.get("default_level")
        if not isinstance(action_ref, str) or not isinstance(default_level, int):
            continue
        candidates.append(
            {
                "combatant_action_set_id": action_set.combatant_action_set_id,
                "entity_ref": action_set.entity_ref,
                "skill_index": skill_index_key,
                "action_ref": action_ref,
                "action_level": default_level,
                "skill_id": entry.get("skill_id"),
                "source": action_set.source.to_json(),
            }
        )
    action_set_count = sum(1 for action_set in combatant_action_sets if action_set.coverage_status == "executable")
    if not candidates:
        return QueueResolutionIR(
            queue_resolution_id=resolution_id,
            queue_intent_id=intent.queue_intent_id,
            action_or_ability_ref=f"skill_index:{skill_index_key}",
            resolved_kind="insert_action_not_admitted",
            resolved_ids={
                "skill_index_expr": _json_safe(intent.skill_index_expr),
                "skill_index": skill_index_key,
                "executable_action_set_count": action_set_count,
            },
            source=source,
            coverage_status="blocked",
            blocked_reason=f"queue_insert_action_no_action_set_candidate:{skill_index_key}",
        )
    return QueueResolutionIR(
        queue_resolution_id=resolution_id,
        queue_intent_id=intent.queue_intent_id,
        action_or_ability_ref=f"skill_index:{skill_index_key}",
        resolved_kind="action_definition",
        resolved_ids={
            "skill_index_expr": _json_safe(intent.skill_index_expr),
            "skill_index": skill_index_key,
            "action_set_candidates": candidates,
            "executable_action_set_count": action_set_count,
        },
        source=source,
        coverage_status="executable",
        blocked_reason="",
    )


def _lower_queue_windows(
    queue_intents: list[QueueIntentIR],
    queue_resolutions: list[QueueResolutionIR],
    extra_turn_source_basis: dict[str, Any],
) -> list[QueueWindowIR]:
    resolutions_by_intent = {resolution.queue_intent_id: resolution for resolution in queue_resolutions}
    return [
        _queue_window_from_intent(intent, resolutions_by_intent.get(intent.queue_intent_id), extra_turn_source_basis)
        for intent in queue_intents
    ]


def _lower_queue_lifecycle_policies(
    queue_windows: list[QueueWindowIR],
    extra_turn_source_basis: dict[str, Any],
) -> list[QueueLifecyclePolicyIR]:
    policies: list[QueueLifecyclePolicyIR] = []
    source_evidence = extra_turn_source_basis.get("evidence") if isinstance(extra_turn_source_basis.get("evidence"), dict) else {}
    source_policy = extra_turn_source_basis.get("lifecycle_policy") if isinstance(extra_turn_source_basis.get("lifecycle_policy"), dict) else {}
    one_more_source = _first_source_from_extra_turn_basis(extra_turn_source_basis)
    policies.append(
        QueueLifecyclePolicyIR(
            queue_lifecycle_policy_id="queue_lifecycle_policy:extra_turn_source:OneMore",
            queue_window_id="",
            queue_intent_id="",
            window_family="extra_turn",
            lifecycle_policy=_json_safe(source_policy) if source_policy else {},
            source_basis=_json_safe(extra_turn_source_basis),
            source=one_more_source,
            coverage_status="discovered_only"
            if extra_turn_source_basis.get("source_basis_status") == "lifecycle_source_admitted"
            else "blocked",
            blocked_reason=""
            if extra_turn_source_basis.get("source_basis_status") == "lifecycle_source_admitted"
            else str(extra_turn_source_basis.get("blocking_dependency") or "extra_turn_lifecycle_source_missing"),
        )
    )
    for window in queue_windows:
        if window.window_family != "extra_turn":
            continue
        window_policy = window.window_policy if isinstance(window.window_policy, dict) else {}
        policy_id = str(window_policy.get("queue_lifecycle_policy_id") or f"queue_lifecycle_policy:queue_window:{window.queue_intent_id}")
        admitted = window.coverage_status == "executable" and window_policy.get("lifecycle_policy_admitted") is True
        lifecycle_policy = _json_safe(source_policy) if source_policy else {}
        if isinstance(lifecycle_policy, dict):
            lifecycle_policy = {
                **lifecycle_policy,
                "queue_window_id": window.queue_window_id,
                "queue_intent_id": window.queue_intent_id,
                "window_family": window.window_family,
                "window_policy": window_policy,
            }
        blocked_reason = ""
        if not admitted:
            blocked_reason = (
                window.blocked_reason
                or str(window_policy.get("blocking_dependency") or "")
                or "extra_turn_window_or_lifecycle_not_admitted"
            )
        policies.append(
            QueueLifecyclePolicyIR(
                queue_lifecycle_policy_id=policy_id,
                queue_window_id=window.queue_window_id,
                queue_intent_id=window.queue_intent_id,
                window_family=window.window_family,
                lifecycle_policy=lifecycle_policy if isinstance(lifecycle_policy, dict) else {},
                source_basis={
                    "extra_turn_source_basis": _json_safe(extra_turn_source_basis),
                    "queue_window_source": window.source.to_json(),
                    "source_evidence_keys": sorted(str(key) for key in source_evidence),
                },
                source=IRSource(
                    source_path=window.source.source_path,
                    raw_type="QueueLifecyclePolicy",
                    raw_id=policy_id,
                    evidence={
                        "queue_window_id": window.queue_window_id,
                        "queue_intent_id": window.queue_intent_id,
                        "queue_window_source": window.source.to_json(),
                        "extra_turn_source_basis": _json_safe(extra_turn_source_basis),
                    },
                ),
                coverage_status="executable" if admitted else "blocked",
                blocked_reason=blocked_reason,
            )
        )
    return policies


def _lower_extra_action_policies(
    *,
    queue_intents: list[QueueIntentIR],
    queue_windows: list[QueueWindowIR],
    queue_lifecycle_policies: list[QueueLifecyclePolicyIR],
    skill_continuations: list[SkillContinuationIR],
    extra_turn_source_basis: dict[str, Any],
) -> list[ExtraActionPolicyIR]:
    policies: list[ExtraActionPolicyIR] = []
    lifecycle_by_window = {policy.queue_window_id: policy for policy in queue_lifecycle_policies if policy.queue_window_id}
    intent_by_id = {intent.queue_intent_id: intent for intent in queue_intents}
    for window in queue_windows:
        if window.window_family != "extra_turn":
            continue
        intent = intent_by_id.get(window.queue_intent_id)
        lifecycle = lifecycle_by_window.get(window.queue_window_id)
        lifecycle_ok = lifecycle is not None and lifecycle.coverage_status == "executable"
        window_ok = window.coverage_status == "executable"
        policy_id = f"extra_action_policy:queue_window:{window.queue_intent_id}"
        source_basis = {
            "queue_window_source": window.source.to_json(),
            "queue_intent_source": intent.source.to_json() if intent is not None else {},
            "queue_lifecycle_policy": lifecycle.to_json() if lifecycle is not None else {},
            "extra_turn_source_basis": _json_safe(extra_turn_source_basis),
        }
        blocked_reason = ""
        if not window_ok:
            blocked_reason = window.blocked_reason or f"queue_window_not_executable:{window.coverage_status}"
        elif not lifecycle_ok:
            blocked_reason = "extra_turn_lifecycle_policy_not_admitted"
        policies.append(
            ExtraActionPolicyIR(
                extra_action_policy_id=policy_id,
                queue_intent_id=window.queue_intent_id,
                queue_window_id=window.queue_window_id,
                source_kind="true_extra_turn",
                action_selection_kind="route_or_source_selected_action",
                allowed_action_kinds=("basic", "skill", "ultimate"),
                fixed_action_ref="",
                lifecycle_policy_id=lifecycle.queue_lifecycle_policy_id if lifecycle is not None else "",
                source_basis=source_basis,
                source=IRSource(
                    source_path=window.source.source_path,
                    raw_type="ExtraActionPolicy",
                    raw_id=policy_id,
                    evidence=source_basis,
                ),
                coverage_status="executable" if window_ok and lifecycle_ok else "blocked",
                blocked_reason=blocked_reason,
            )
        )
    for continuation in skill_continuations:
        policy_id = f"extra_action_policy:skill_continuation:{continuation.continuation_id}"
        source_basis = {
            "skill_continuation": continuation.to_json(),
            "reason": "UseSkillOneMore is a skill or ultimate internal continuation, not a true extra turn",
        }
        policies.append(
            ExtraActionPolicyIR(
                extra_action_policy_id=policy_id,
                queue_intent_id="",
                queue_window_id="",
                source_kind="skill_or_ultimate_internal_continuation",
                action_selection_kind="fixed_internal_segment",
                allowed_action_kinds=(),
                fixed_action_ref=continuation.fixed_skill_type,
                lifecycle_policy_id="",
                source_basis=source_basis,
                source=IRSource(
                    source_path=continuation.source.source_path,
                    raw_type="SkillContinuationPolicy",
                    raw_id=policy_id,
                    evidence=source_basis,
                ),
                coverage_status="blocked",
                blocked_reason=(
                    "skill_continuation_runner_not_admitted:"
                    "requires source-specific mapping from continuation segment to executable action or ability"
                ),
            )
        )
    return policies


def _first_source_from_extra_turn_basis(extra_turn_source_basis: dict[str, Any]) -> IRSource:
    evidence = extra_turn_source_basis.get("evidence") if isinstance(extra_turn_source_basis.get("evidence"), dict) else {}
    modifier = evidence.get("one_more_modifier") if isinstance(evidence.get("one_more_modifier"), dict) else {}
    source = modifier.get("source") if isinstance(modifier.get("source"), dict) else None
    if isinstance(source, dict):
        return IRSource(
            source_path=str(source.get("source_path") or "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json"),
            raw_type=str(source.get("raw_type") or "ConfigGlobalModifier"),
            raw_id=str(source.get("raw_id") or "OneMore"),
            evidence=_json_safe(source.get("evidence") or {}),
        )
    return IRSource(
        source_path="Config/GlobalConfig/JsonEnumDefineConfig.json",
        raw_type="ExtraTurnSourceDiscovery",
        raw_id="OneMore",
        evidence=_json_safe(extra_turn_source_basis),
    )


def _queue_window_from_intent(
    intent: QueueIntentIR,
    resolution: QueueResolutionIR | None,
    extra_turn_source_basis: dict[str, Any],
) -> QueueWindowIR:
    family, basis = _queue_window_family(intent)
    policy = _queue_window_policy(intent, resolution, family, basis, extra_turn_source_basis)
    source = IRSource(
        source_path=intent.source.source_path,
        raw_type="QueueWindow",
        raw_id=intent.queue_intent_id,
        evidence={
            "queue_intent_id": intent.queue_intent_id,
            "queue_intent_source": intent.source.to_json(),
            "queue_kind": intent.queue_kind,
            "opcode": intent.opcode,
            "priority_source": _json_safe(intent.priority_source),
            "family_basis": basis,
            "resolution": resolution.to_json() if resolution is not None else {},
        },
    )
    if intent.coverage_status != "executable":
        status = "blocked"
        reason = intent.blocked_reason or f"queue_intent_not_executable:{intent.coverage_status}"
    elif resolution is None:
        status = "blocked"
        reason = "queue_resolution_missing_for_window"
    elif resolution.coverage_status != "executable":
        status = "blocked"
        reason = resolution.blocked_reason or f"queue_resolution_not_executable:{resolution.coverage_status}"
    elif not policy.get("priority_ordering_admitted"):
        status = "blocked"
        reason = str(policy.get("blocking_dependency") or "queue_window_ordering_not_admitted")
    elif policy.get("lifecycle_policy_admitted") is False:
        status = "blocked"
        reason = str(policy.get("blocking_dependency") or "queue_window_lifecycle_policy_not_admitted")
    elif family in {"assistant", "unknown"}:
        status = "blocked"
        reason = f"queue_window_family_not_admitted:{family}"
    else:
        status = "executable"
        reason = ""
    return QueueWindowIR(
        queue_window_id=f"queue_window:{intent.queue_intent_id}",
        queue_intent_id=intent.queue_intent_id,
        queue_kind=intent.queue_kind,
        window_family=family,
        priority_key=str(intent.priority_source.get("priority_key") or ""),
        priority_value=_json_float(intent.priority_source.get("priority_value")),
        window_policy=policy,
        source=source,
        coverage_status=status,
        blocked_reason=reason,
    )


def _queue_window_family(intent: QueueIntentIR) -> tuple[str, dict[str, Any]]:
    priority_key = str(intent.priority_source.get("priority_key") or "")
    ref = intent.action_ref_or_ability_name
    text = " ".join(
        (
            intent.opcode,
            intent.queue_kind,
            priority_key,
            ref,
            intent.source.source_path,
            str(intent.source.raw_id),
        )
    )
    lowered = text.lower()
    text_hints = _queue_window_text_hints(lowered)
    basis = {
        "opcode": intent.opcode,
        "queue_kind": intent.queue_kind,
        "priority_key": priority_key,
        "action_or_ability_ref": ref,
        "source_path": intent.source.source_path,
        "text_hints": text_hints,
        "text_hint_status": "discovered_only" if text_hints else "",
    }
    if intent.opcode == "TurnInsertAssistantAbility":
        return "assistant", basis
    if intent.queue_kind == "extra_turn":
        return "extra_turn", {
            **basis,
            "extra_turn_basis_status": "discovered_only",
            "source_basis": "structured_extra_turn_source_task",
            "blocking_dependency": (
                intent.blocked_reason
                or "extra_turn_source_task_not_admitted_without_priority_target_action_resolution"
            ),
        }
    if intent.queue_kind == "turn_insert_action" and intent.skill_index_expr.get("source_field") == "PrepareAbilityName":
        return "extra_turn", {
            **basis,
            "extra_turn_basis_status": "admitted",
            "source_basis": "structured_turn_insert_action_prepare_ability",
            "prepare_ability_name": intent.action_ref_or_ability_name,
            "action_selection_policy": "route_or_source_selected_action",
        }
    if intent.queue_kind == "turn_insert_action":
        return "insert_action", basis
    if intent.queue_kind == "turn_insert_ability":
        return "insert_ability", basis
    if text_hints:
        return "unknown", {
            **basis,
            "source_basis": "text_only_queue_window_hint",
            "blocking_dependency": "queue_window_text_hint_not_admitted_without_structured_source",
        }
    return "unknown", basis


def _queue_window_text_hints(lowered_text: str) -> list[str]:
    hints: list[str] = []
    if any(token in lowered_text for token in ("counter", "反击")):
        hints.append("counter")
    if any(token in lowered_text for token in ("follow", "followup", "follow_up", "追加", "追击")):
        hints.append("follow_up")
    if any(token in lowered_text for token in ("onemore", "one_more", "extra_turn", "extraturn", "additionalturn")):
        hints.append("extra_turn")
    if any(token in lowered_text for token in ("ultra", "ultimate", "ultimateskill")):
        hints.append("ultimate")
    if "interrupt" in lowered_text:
        hints.append("interrupt")
    if "immediate" in lowered_text:
        hints.append("immediate")
    return hints


def _queue_window_policy(
    intent: QueueIntentIR,
    resolution: QueueResolutionIR | None,
    family: str,
    basis: dict[str, Any],
    extra_turn_source_basis: dict[str, Any],
) -> dict[str, Any]:
    priority_value = _json_float(intent.priority_source.get("priority_value"))
    ordering_admitted = intent.priority_source.get("priority_ordering_admitted") is True and priority_value is not None
    policy: dict[str, Any] = {
        "window_family": family,
        "source_basis": basis,
        "text_hints": _json_safe(basis.get("text_hints") or []),
        "text_hint_status": str(basis.get("text_hint_status") or ""),
        "priority_ordering_admitted": ordering_admitted,
        "priority_value": priority_value,
        "dequeue_before_execute": True,
        "drain_via_scheduler": True,
        "reentrant_drain_allowed": False,
    }
    if not ordering_admitted:
        policy["blocking_dependency"] = str(intent.priority_source.get("reason") or "queue_priority_not_admitted")
    if resolution is None:
        policy["blocking_dependency"] = "queue_resolution_missing_for_window"
    elif resolution.coverage_status != "executable":
        policy["blocking_dependency"] = resolution.blocked_reason or f"queue_resolution_not_executable:{resolution.coverage_status}"
    if family == "extra_turn":
        lifecycle_admitted = (
            basis.get("extra_turn_basis_status") == "admitted"
            and extra_turn_source_basis.get("source_basis_status") == "lifecycle_source_admitted"
        )
        lifecycle_policy_id = f"queue_lifecycle_policy:queue_window:{intent.queue_intent_id}"
        policy.update(
            {
                "natural_av_advance": "bypassed_for_queue_child",
                "queue_lifecycle_policy_id": lifecycle_policy_id,
                "extra_action_policy_id": f"extra_action_policy:queue_window:{intent.queue_intent_id}",
                "lifecycle_policy_admitted": lifecycle_admitted,
                "turn_lifecycle_policy": "admitted_from_queue_lifecycle_policy" if lifecycle_admitted else "blocked_until_extra_turn_lifecycle_source_admitted",
                "duration_tick_policy": "ActionPhaseEnd_from_OneMore_LifeStepMoment" if lifecycle_admitted else "blocked_until_extra_turn_lifecycle_source_admitted",
                "action_selection_policy": "source_or_route_selected_action_required",
                "action_selection_admitted": lifecycle_admitted and resolution is not None and resolution.coverage_status == "executable",
                "extra_turn_source_basis": _json_safe(extra_turn_source_basis),
            }
        )
        if not lifecycle_admitted:
            policy["blocking_dependency"] = (
                str(basis.get("blocking_dependency") or "")
                or str(extra_turn_source_basis.get("blocking_dependency") or "")
                or "extra_turn_lifecycle_source_not_admitted"
            )
    elif family == "ultimate":
        policy.update(
            {
                "interrupts_current_action": "not_admitted",
                "energy_cost_policy": "manual_preflight_only_until_ultimate_cost_source_admitted",
            }
        )
    elif family in {"follow_up", "counter"}:
        policy.update({"attack_semantics": "queue_window_only_not_damage_family"})
    elif family == "assistant":
        policy["blocking_dependency"] = "assistant_actor_resolution_not_admitted"
    elif family == "unknown":
        policy["blocking_dependency"] = "queue_window_family_unknown"
    return policy


def _effect_blocked_reason(opcode: str, payload: dict[str, Any], coverage_status: str) -> str:
    standard = payload.get("standard")
    if isinstance(standard, dict) and standard.get("blocked_reason"):
        return str(standard["blocked_reason"])
    if coverage_status == "blocked":
        if not isinstance(standard, dict):
            return f"effect_payload_not_standardized:{opcode}"
        target_expression_reason = standard.get("target_expression_blocked_reason")
        if isinstance(target_expression_reason, str) and target_expression_reason:
            return target_expression_reason
        target_alias = standard.get("target_alias")
        if target_alias is not None and target_alias not in EXECUTABLE_TARGET_ALIASES | ADD_MODIFIER_TARGET_ALIASES | STATUS_CALLBACK_LIST_TARGET_ALIASES:
            return f"unsupported_target_alias:{target_alias}"
        return f"effect_not_executable:{opcode}"
    return f"effect_coverage_status:{coverage_status}:{opcode}"


def _condition_payload_executable(opcode: str, payload: dict[str, Any]) -> bool:
    if opcode not in EXECUTABLE_CONDITION_OPCODES:
        return False
    if opcode == "AlwaysTrue":
        return True
    if opcode == "ByCurrentSkillType":
        value = payload.get("SkillType")
        return value is None or isinstance(value, str)
    if opcode == "ByAttackType":
        return isinstance(payload.get("AttackTypes"), list)
    if opcode == "ByTargetTeam":
        return _target_alias(payload.get("TargetType")) in EXECUTABLE_TARGET_ALIASES and payload.get("Team") in {"TeamLight", "TeamDark"}
    if opcode == "ByCompareMonsterID":
        return (
            _target_alias(payload.get("TargetType")) in EXECUTABLE_TARGET_ALIASES
            and _numeric_expr_can_be_runtime_bound(_numeric_expr_summary(payload.get("TargetMonsterID")))
        )
    if opcode == "ByContainBehaviorFlag":
        return _target_alias(payload.get("TargetType")) in EXECUTABLE_TARGET_ALIASES and isinstance(payload.get("Flag"), str)
    if opcode == "ByContainsParamFlag":
        return isinstance(payload.get("Flag"), str)
    if opcode == "ByTargetListIntersects":
        first = _target_alias(payload.get("FirstTargetType"))
        second = _target_alias(payload.get("SecondTargetType"))
        return first in EXECUTABLE_TARGET_ALIASES and second in {"GridFight_AllBackEnd"}
    if opcode == "ByIsContainModifier":
        return _target_alias(payload.get("TargetType")) in EXECUTABLE_TARGET_ALIASES and isinstance(_value_field(payload.get("ModifierName")), str)
    if opcode == "ByIsInsertAction":
        return True
    if opcode in {"ByIsCurrentSkillActive", "ByHaveEnemyAlive"}:
        return _target_alias(payload.get("TargetType")) in EXECUTABLE_TARGET_ALIASES
    if opcode == "ByCompareHPRatio":
        return (
            _target_alias(payload.get("TargetType")) in EXECUTABLE_TARGET_ALIASES
            and _numeric_expr_can_be_runtime_bound(_numeric_expr_summary(payload.get("CompareValue")))
        )
    if opcode == "ByCompareDynamicValue":
        return (
            isinstance(_value_field(payload.get("DynamicKey")), str)
            and _numeric_expr_can_be_runtime_bound(_numeric_expr_summary(payload.get("CompareValue")))
        )
    if opcode == "ByCompareModifierValue":
        return (
            _target_alias(payload.get("TargetType")) in EXECUTABLE_TARGET_ALIASES
            and payload.get("ValueType") in SUPPORTED_MODIFIER_VALUE_TYPES
            and _numeric_expr_can_be_runtime_bound(_numeric_expr_summary(payload.get("CompareValue")))
        )
    if opcode == "ByCompareTarget":
        return _target_alias(payload.get("TargetType")) in EXECUTABLE_TARGET_ALIASES and _target_alias(payload.get("CompareType")) in EXECUTABLE_TARGET_ALIASES
    if opcode == "ByTargetEntityType":
        return _target_alias(payload.get("TargetType")) in EXECUTABLE_TARGET_ALIASES and payload.get("EntityTypeMask") == "Servant"
    if opcode == "ByCompareDamageCustomName":
        return isinstance(_value_field(payload.get("CustomName")), str)
    if opcode in {"ByAnd", "ByAny"}:
        predicates = payload.get("PredicateList")
        return isinstance(predicates, list) and all(_raw_condition_payload_executable(item) for item in predicates)
    if opcode == "ByNot":
        return _raw_condition_payload_executable(payload.get("Predicate"))
    return False


def _raw_condition_payload_executable(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    opcode = _short_gamecore_type(value.get("$type"))
    payload = _compact_payload(value)
    return _condition_payload_executable(opcode, payload)


def _standard_add_modifier_payload(value: dict[str, Any]) -> dict[str, Any]:
    dynamic_values = {
        str(key): _numeric_expr_summary(item)
        for key, item in (value.get("DynamicValues") or {}).items()
        if isinstance(value.get("DynamicValues"), dict)
    }
    lifetime = _numeric_expr_summary(value.get("LifeTime"))
    life_step_moment = _value_field(value.get("LifeStepMoment"))
    return {
        "modifier_name": _value_field(value.get("ModifierName")),
        "target_alias": _target_alias(value.get("TargetType")),
        "dynamic_values": dynamic_values,
        "dynamic_value_requests": _dynamic_value_requests(dynamic_values),
        "lifetime": lifetime,
        "life_step_moment": life_step_moment,
        "duration_admission": _duration_admission_payload(lifetime, life_step_moment),
        "layer_add_when_stack": _numeric_expr_summary(value.get("LayerAddWhenStack")),
        "max_layer": _numeric_expr_summary(value.get("MaxLayer")),
        "chance": _numeric_expr_summary(value.get("Chance")),
    }


SUPPORTED_DURATION_LIFE_STEP_MOMENTS = {"ModifierPhase1End", "ActionPhaseEnd"}


def _duration_admission_payload(lifetime_expr: dict[str, Any], life_step_moment: object) -> dict[str, Any]:
    moment = str(life_step_moment or "")
    if lifetime_expr.get("kind") == "missing":
        return {
            "admission_status": "not_applicable",
            "blocked_reason": "lifetime_missing",
            "life_step_moment": moment,
            "lifetime_expr": lifetime_expr,
        }
    if lifetime_expr.get("kind") != "fixed":
        return {
            "admission_status": "blocked",
            "blocked_reason": f"lifetime_not_fixed:{lifetime_expr.get('kind') or 'unknown'}",
            "life_step_moment": moment,
            "lifetime_expr": lifetime_expr,
        }
    value = lifetime_expr.get("value")
    if not isinstance(value, (int, float)) or float(value) <= 0:
        return {
            "admission_status": "blocked",
            "blocked_reason": "lifetime_non_positive_or_missing",
            "life_step_moment": moment,
            "lifetime_expr": lifetime_expr,
        }
    if moment not in SUPPORTED_DURATION_LIFE_STEP_MOMENTS:
        reason = "life_step_moment_missing" if not moment else f"unsupported_life_step_moment:{moment}"
        return {
            "admission_status": "blocked",
            "blocked_reason": reason,
            "life_step_moment": moment,
            "lifetime_expr": lifetime_expr,
        }
    return {
        "admission_status": "executable",
        "blocked_reason": "",
        "life_step_moment": moment,
        "remaining_duration": float(value),
        "lifetime_expr": lifetime_expr,
    }


def _standard_remove_modifier_payload(value: dict[str, Any], opcode: str, source_modifier_name: str) -> dict[str, Any]:
    if opcode == "RemoveSelfModifier":
        modifier_name = source_modifier_name
        target_alias = "ModifierOwnerEntity"
    else:
        modifier_name = _value_field(value.get("ModifierName"))
        target_alias = _target_alias(value.get("TargetType"))
    status_id = f"modifier:{modifier_name}" if isinstance(modifier_name, str) and modifier_name else None
    return {
        "kind": "status_remove",
        "target_alias": target_alias,
        "modifier_name": modifier_name,
        "status_id": status_id,
    }


def _standard_dispel_status_payload(value: dict[str, Any]) -> dict[str, Any]:
    count_expr = _numeric_expr_summary(value.get("Numbers"))
    order = _value_field(value.get("Order"))
    payload = {
        "kind": "status_dispel",
        "target_alias": _target_alias(value.get("TargetType")),
        "buff_type": _value_field(value.get("BuffType")),
        "numbers": count_expr,
        "order": order,
        "only_alive": value.get("OnlyAlive") if isinstance(value.get("OnlyAlive"), bool) else None,
        "only_can_dispel": value.get("OnlyCanDispel") if isinstance(value.get("OnlyCanDispel"), bool) else True,
        "is_silent_dispel": value.get("IsSilentDispel") if isinstance(value.get("IsSilentDispel"), bool) else None,
        "mute_all_visual_effect": value.get("MuteAllVisualEffect") if isinstance(value.get("MuteAllVisualEffect"), bool) else None,
        "behavior_flags": _list_json_values(value.get("BehaviorFlags")),
        "dispel_count_key": _value_field(value.get("DispelCountKey")),
    }
    if not _numeric_expr_can_be_runtime_bound(count_expr):
        payload["blocked_reason"] = f"dispel_count_not_executable:{count_expr.get('kind') or 'unknown'}"
    elif order not in {"LastAdded", "Random"}:
        payload["blocked_reason"] = f"dispel_order_not_admitted:{order or 'missing'}"
    return payload


def _standard_heal_payload(value: dict[str, Any]) -> dict[str, Any]:
    modify_value = _numeric_expr_summary(value.get("ModifyValue"))
    percentage = _numeric_expr_summary(value.get("HealPercentage"))
    formula_type = _value_field(value.get("FormulaType"))
    ratio_formula_types = {"HealByTargetMaxHP", "HealByHealerMaxHP"}
    amount = percentage if formula_type in ratio_formula_types else modify_value
    payload = {
        "kind": "heal",
        "target_alias": _target_alias(value.get("TargetType")),
        "formula_type": formula_type,
        "amount": amount,
        "amount_role": "ratio" if formula_type in ratio_formula_types else "flat",
        "formula_base": _heal_formula_base(formula_type),
        "percentage": percentage,
        "modify_value": modify_value,
        "raw_formula_fields": {
            "ModifyValue": _json_safe(value.get("ModifyValue")),
            "HealPercentage": _json_safe(value.get("HealPercentage")),
            "FormulaType": _json_safe(value.get("FormulaType")),
        },
    }
    if formula_type not in {None, "", "HealByBaseValue", *ratio_formula_types}:
        payload["blocked_reason"] = f"formula_type_not_supported:{formula_type}"
    elif not _numeric_expr_can_be_runtime_bound(amount):
        payload["blocked_reason"] = "fixed_or_bound_heal_percentage_required" if formula_type in ratio_formula_types else "fixed_or_bound_modify_value_required"
    return payload


def _standard_shield_payload(value: dict[str, Any], opcode: str) -> dict[str, Any]:
    shield_value = _numeric_expr_summary(value.get("ShieldValue"))
    percentage = _numeric_expr_summary(value.get("ShieldPercentage"))
    formula_type = _value_field(value.get("FormulaType"))
    ratio_formula_types = {"ShieldByCasterMaxHP", "ShieldByCasterDefence", "ShieldByTargetMaxHP"}
    amount = percentage if formula_type in ratio_formula_types else shield_value
    payload = {
        "kind": "shield",
        "shield_opcode": opcode,
        "target_alias": _target_alias(value.get("TargetType")),
        "formula_type": formula_type,
        "amount": amount,
        "amount_role": "ratio" if formula_type in ratio_formula_types else "flat",
        "formula_base": _shield_formula_base(formula_type),
        "percentage": percentage,
        "shield_value": shield_value,
        "raw_formula_fields": {
            "ShieldValue": _json_safe(value.get("ShieldValue")),
            "ShieldPercentage": _json_safe(value.get("ShieldPercentage")),
            "FormulaType": _json_safe(value.get("FormulaType")),
        },
    }
    if formula_type not in {None, "", "ShieldByBaseValue", *ratio_formula_types}:
        payload["blocked_reason"] = f"formula_type_not_supported:{formula_type}"
    elif not _numeric_expr_can_be_runtime_bound(amount):
        payload["blocked_reason"] = "fixed_or_bound_shield_percentage_required" if formula_type in ratio_formula_types else "fixed_or_bound_shield_value_required"
    return payload


def _standard_mechanism_bar_payload(value: dict[str, Any], opcode: str) -> dict[str, Any]:
    current_count = _numeric_expr_summary(value.get("CurrentCount"))
    max_count = _numeric_expr_summary(value.get("MaxCount"))
    payload = {
        "kind": "mechanism_bar_state",
        "opcode": opcode,
        "target_alias": _target_alias(value.get("TargetType")),
        "bar_type": _value_field(value.get("BarType")),
        "active": _value_field(value.get("Active")),
        "state": _value_field(value.get("CurrentState", value.get("State"))),
        "current_count": current_count,
        "max_count": max_count,
        "raw_formula_fields": {
            "Active": _json_safe(value.get("Active")),
            "BarType": _json_safe(value.get("BarType")),
            "CurrentState": _json_safe(value.get("CurrentState")),
            "State": _json_safe(value.get("State")),
            "CurrentCount": _json_safe(value.get("CurrentCount")),
            "MaxCount": _json_safe(value.get("MaxCount")),
        },
    }
    if not _mechanism_bar_has_runtime_payload(payload):
        payload["blocked_reason"] = "fixed_or_bound_mechanism_bar_state_or_count_required"
    return payload


def _standard_resource_delta_payload(value: dict[str, Any], opcode: str) -> dict[str, Any]:
    admitted_fields = (
        "AddValue",
        "ModifyValue",
        "FixedAddValue",
        "SetValue",
        "FixedSetValue",
        "AddMaxSPRatio",
        "FixedAddMaxSPRatio",
        "SetMaxSPRatio",
        "FixedSetMaxSPRatio",
    )
    amount_field = _first_present_key(value, admitted_fields)
    unsupported_field = "" if amount_field else _first_present_key(
        value,
        (
            "AddRatio",
            "FixedAddRatio",
        ),
    )
    formula_field = amount_field or unsupported_field
    amount = _numeric_expr_summary(value.get(formula_field) if formula_field else None)
    operation = "set" if formula_field in {"SetValue", "FixedSetValue", "SetMaxSPRatio", "FixedSetMaxSPRatio"} else "add"
    scale_basis = "max_energy" if formula_field in {"AddMaxSPRatio", "FixedAddMaxSPRatio", "SetMaxSPRatio", "FixedSetMaxSPRatio"} else "flat"
    payload = {
        "kind": "resource_delta",
        "resource": "energy" if opcode == "ModifySPNew" else opcode,
        "target_alias": _target_alias(value.get("TargetType")),
        "formula_type": formula_field or "missing",
        "amount": amount,
        "operation": operation,
        "scale_basis": scale_basis,
        "raw_formula_fields": {
            "AddValue": _json_safe(value.get("AddValue")),
            "ModifyValue": _json_safe(value.get("ModifyValue")),
            "FixedAddValue": _json_safe(value.get("FixedAddValue")),
            "AddRatio": _json_safe(value.get("AddRatio")),
            "FixedAddRatio": _json_safe(value.get("FixedAddRatio")),
            "AddMaxSPRatio": _json_safe(value.get("AddMaxSPRatio")),
            "FixedAddMaxSPRatio": _json_safe(value.get("FixedAddMaxSPRatio")),
            "SetValue": _json_safe(value.get("SetValue")),
            "SetMaxSPRatio": _json_safe(value.get("SetMaxSPRatio")),
            "FixedSetValue": _json_safe(value.get("FixedSetValue")),
            "FixedSetMaxSPRatio": _json_safe(value.get("FixedSetMaxSPRatio")),
        },
    }
    if unsupported_field:
        payload["blocked_reason"] = f"resource_formula_type_not_supported:{unsupported_field}"
    elif not _numeric_expr_can_be_runtime_bound(amount):
        payload["blocked_reason"] = "fixed_or_bound_resource_delta_required"
    return payload


def _standard_hp_loss_ratio_payload(value: dict[str, Any]) -> dict[str, Any]:
    ratio = _numeric_expr_summary(value.get("Ratio"))
    ratio_type = _value_field(value.get("RatioType"))
    floor = bool(value.get("Floor")) if value.get("Floor") is not None else False
    payload = {
        "kind": "hp_loss_ratio",
        "target_alias": _target_alias(value.get("TargetType")),
        "ratio": ratio,
        "ratio_type": ratio_type,
        "floor": floor,
        "attack_type": _value_field(value.get("AttackType")),
        "damage_type": _value_field(value.get("DamageType")),
        "raw_formula_fields": {
            "Ratio": _json_safe(value.get("Ratio")),
            "RatioType": _json_safe(value.get("RatioType")),
            "Floor": _json_safe(value.get("Floor")),
            "AttackType": _json_safe(value.get("AttackType")),
            "DamageType": _json_safe(value.get("DamageType")),
            "TargetType": _json_safe(value.get("TargetType")),
        },
    }
    if floor:
        payload["rounding_policy"] = "floor_from_tbgd_flag"
    if ratio_type not in {"MaxHP", "CurrentHP"}:
        payload["blocked_reason"] = f"hp_loss_ratio_type_not_supported:{ratio_type}"
    elif not _numeric_expr_can_be_runtime_bound(ratio):
        payload["blocked_reason"] = str(ratio.get("reason") or "fixed_or_bound_hp_loss_ratio_required")
    return payload


def _heal_formula_base(formula_type: Any) -> str:
    if formula_type == "HealByTargetMaxHP":
        return "target.max_hp"
    if formula_type == "HealByHealerMaxHP":
        return "caster.max_hp"
    return "flat"


def _shield_formula_base(formula_type: Any) -> str:
    if formula_type == "ShieldByCasterMaxHP":
        return "caster.max_hp"
    if formula_type == "ShieldByCasterDefence":
        return "caster.defense"
    if formula_type == "ShieldByTargetMaxHP":
        return "target.max_hp"
    return "flat"


def _standard_set_dynamic_value_payload(value: dict[str, Any]) -> dict[str, Any]:
    value_expr = _numeric_expr_summary(value.get("Value"))
    value_name = _value_field(value.get("DynamicKey"))
    target_alias = _target_alias(value.get("TargetType")) or "ModifierOwnerEntity"
    payload = {
        "kind": "dynamic_value_store",
        "opcode": "SetDynamicValue",
        "target_alias": target_alias,
        "status_scope": _value_field(value.get("ContextScope")) or "modifier_local",
        "value_name": value_name,
        "hash": None,
        "value_expr": value_expr,
        "raw_formula_fields": {
            "DynamicKey": _json_safe(value.get("DynamicKey")),
            "Value": _json_safe(value.get("Value")),
            "TargetType": _json_safe(value.get("TargetType")),
            "ContextScope": _json_safe(value.get("ContextScope")),
        },
    }
    if not isinstance(value_name, str) or not value_name:
        payload["blocked_reason"] = "dynamic_value_name_required"
    elif target_alias not in EXECUTABLE_TARGET_ALIASES | {"LevelEntity"}:
        payload["blocked_reason"] = f"unsupported_target_alias:{target_alias}"
    elif not _numeric_expr_can_be_runtime_bound(value_expr):
        payload["blocked_reason"] = str(value_expr.get("reason") or "fixed_or_bound_dynamic_value_required")
    return payload


def _standard_trigger_ability_payload(value: dict[str, Any]) -> dict[str, Any]:
    ability_name = _value_field(value.get("AbilityName"))
    target_alias = _target_alias(value.get("TargetType")) or "Caster"
    inherent_target_alias = _target_alias(value.get("AbilityInherentTargetType"))
    payload = {
        "kind": "standalone_ability_trigger",
        "opcode": "TriggerAbility",
        "ability_name": ability_name,
        "target_alias": target_alias,
        "inherent_target_alias": inherent_target_alias or "",
        "raw_fields": {
            "AbilityName": _json_safe(value.get("AbilityName")),
            "TargetType": _json_safe(value.get("TargetType")),
            "AbilityInherentTargetType": _json_safe(value.get("AbilityInherentTargetType")),
        },
    }
    if not isinstance(ability_name, str) or not ability_name:
        payload["blocked_reason"] = "trigger_ability_name_required"
    elif target_alias not in EXECUTABLE_TARGET_ALIASES:
        payload["blocked_reason"] = f"unsupported_target_alias:{target_alias}"
    return payload


def _standard_define_dynamic_value_payload(value: dict[str, Any]) -> dict[str, Any]:
    value_expr = _numeric_expr_summary(value.get("ResetValue"))
    if value_expr.get("kind") == "missing":
        value_expr = {"kind": "fixed", "value": 0.0, "source_basis": "tbgd_define_dynamic_value_missing_reset_defaults_to_zero"}
    value_name = _value_field(value.get("DynamicKey"))
    target_alias = _target_alias(value.get("TargetType")) or "ModifierOwnerEntity"
    payload = {
        "kind": "dynamic_value_store",
        "opcode": "DefineDynamicValue",
        "target_alias": target_alias,
        "status_scope": _value_field(value.get("ContextScope")) or "modifier_local",
        "value_name": value_name,
        "hash": None,
        "value_expr": value_expr,
        "raw_formula_fields": {
            "DynamicKey": _json_safe(value.get("DynamicKey")),
            "ResetValue": _json_safe(value.get("ResetValue")),
            "TargetType": _json_safe(value.get("TargetType")),
            "ContextScope": _json_safe(value.get("ContextScope")),
        },
    }
    if not isinstance(value_name, str) or not value_name:
        payload["blocked_reason"] = "dynamic_value_name_required"
    elif target_alias not in EXECUTABLE_TARGET_ALIASES | {"LevelEntity"}:
        payload["blocked_reason"] = f"unsupported_target_alias:{target_alias}"
    elif not _numeric_expr_can_be_runtime_bound(value_expr):
        payload["blocked_reason"] = str(value_expr.get("reason") or "fixed_or_bound_dynamic_value_required")
    return payload


def _standard_set_dynamic_value_by_add_value_payload(value: dict[str, Any]) -> dict[str, Any]:
    add_value = _numeric_expr_summary(value.get("AddValue"))
    min_value = _numeric_expr_summary(value.get("Min"))
    max_value = _numeric_expr_summary(value.get("Max"))
    value_name = _value_field(value.get("Key") or value.get("DynamicKey"))
    target_alias = _target_alias(value.get("TargetType")) or "ModifierOwnerEntity"
    payload = {
        "kind": "dynamic_value_store",
        "opcode": "SetDynamicValueByAddValue",
        "target_alias": target_alias,
        "status_scope": _value_field(value.get("ContextScope")) or "modifier_local",
        "value_name": value_name,
        "add_value": add_value,
        "min_value": min_value,
        "max_value": max_value,
        "raw_formula_fields": {
            "Key": _json_safe(value.get("Key")),
            "DynamicKey": _json_safe(value.get("DynamicKey")),
            "AddValue": _json_safe(value.get("AddValue")),
            "Min": _json_safe(value.get("Min")),
            "Max": _json_safe(value.get("Max")),
            "TargetType": _json_safe(value.get("TargetType")),
            "ContextScope": _json_safe(value.get("ContextScope")),
        },
    }
    if not isinstance(value_name, str) or not value_name:
        payload["blocked_reason"] = "dynamic_value_name_required"
    elif target_alias not in EXECUTABLE_TARGET_ALIASES | {"LevelEntity"}:
        payload["blocked_reason"] = f"unsupported_target_alias:{target_alias}"
    elif not _numeric_expr_can_be_runtime_bound(add_value):
        payload["blocked_reason"] = str(add_value.get("reason") or "fixed_or_bound_dynamic_add_value_required")
    return payload


def _standard_set_dynamic_value_by_modifier_value_payload(
    value: dict[str, Any],
    source_modifier_name: str,
) -> dict[str, Any]:
    source_modifier = _value_field(value.get("ModifierName")) or source_modifier_name
    source_value_name = _value_field(value.get("ValueType"))
    target_value_name = _value_field(value.get("DynamicKey"))
    multiplier = _numeric_expr_summary(value.get("Multiplier"))
    source_target_alias = _target_alias(value.get("ReadTargetType")) or "ModifierOwnerEntity"
    target_alias = _target_alias(value.get("TargetType")) or "ModifierOwnerEntity"
    payload = {
        "kind": "dynamic_value_store",
        "opcode": "SetDynamicValueByModifierValue",
        "source_modifier": source_modifier,
        "source_value_name": source_value_name,
        "source_hash": None,
        "target_value_name": target_value_name,
        "target_hash": None,
        "target_alias": target_alias,
        "source_target_alias": source_target_alias,
        "multiplier": multiplier,
        "raw_formula_fields": {
            "ModifierName": _json_safe(value.get("ModifierName")),
            "ValueType": _json_safe(value.get("ValueType")),
            "Multiplier": _json_safe(value.get("Multiplier")),
            "DynamicKey": _json_safe(value.get("DynamicKey")),
            "ReadTargetType": _json_safe(value.get("ReadTargetType")),
            "TargetType": _json_safe(value.get("TargetType")),
            "ContextScope": _json_safe(value.get("ContextScope")),
        },
    }
    if not isinstance(source_modifier, str) or not source_modifier:
        payload["blocked_reason"] = "source_modifier_required"
    elif source_target_alias not in EXECUTABLE_TARGET_ALIASES:
        payload["blocked_reason"] = f"unsupported_source_target_alias:{source_target_alias}"
    elif target_alias not in EXECUTABLE_TARGET_ALIASES:
        payload["blocked_reason"] = f"unsupported_target_alias:{target_alias}"
    elif source_value_name not in SUPPORTED_MODIFIER_VALUE_TYPES:
        payload["blocked_reason"] = f"unsupported_modifier_value_type:{source_value_name}"
    elif not isinstance(target_value_name, str) or not target_value_name:
        payload["blocked_reason"] = "target_value_name_required"
    elif not _numeric_expr_can_be_runtime_bound(multiplier):
        payload["blocked_reason"] = str(multiplier.get("reason") or "fixed_or_bound_multiplier_required")
    return payload


def _dynamic_value_bindings(value: Any) -> dict[str, Any]:
    floats = value.get("Floats") if isinstance(value, dict) else None
    if not isinstance(floats, dict):
        return {"by_hash": {}, "raw": _json_safe(value)}
    by_hash: dict[str, Any] = {}
    for key, item in floats.items():
        by_hash[str(key)] = {
            "hash": str(key),
            "value_type": "float",
            "read_info": _json_safe(item.get("ReadInfo")) if isinstance(item, dict) else None,
            "raw": _json_safe(item),
            "raw_path": f"DynamicValues.Floats[{key}]",
        }
    return {"by_hash": by_hash, "raw": _json_safe(value)}


def _ability_graph_source_context(
    *,
    source_mode: str,
    skill_row: dict[str, Any],
    skill_trigger_key: str,
    character_path: str,
    character_config: dict[str, Any],
    config_source: dict[str, Any],
    config_kind: str,
    ability_paths: tuple[str, ...],
    skill_rows_by_trigger_key: dict[str, dict[str, Any]] | None = None,
    allowed_dynamic_hashes: set[str] | None = None,
) -> dict[str, Any]:
    skill_param_binding_source, skill_param_summary = _skill_param_numeric_binding_source(
        character_config=character_config,
        skill_row=skill_row,
        skill_trigger_key=skill_trigger_key,
        character_path=character_path,
        skill_rows_by_trigger_key=skill_rows_by_trigger_key,
        allowed_dynamic_hashes=allowed_dynamic_hashes,
    )
    custom_values = character_config.get("CustomValues")
    context: dict[str, Any] = {
        "source_mode": source_mode,
        "skill_id": _json_safe(skill_row.get("SkillID")),
        "skill_trigger_key": skill_trigger_key,
        "skill_source_path": str(skill_row.get("_v8_source_path") or ""),
        "skill_row_index": _json_safe(skill_row.get("_v8_row_index")),
        "param_list": _json_safe(skill_row.get("ParamList") if isinstance(skill_row.get("ParamList"), list) else []),
        "character_config_path": character_path,
        "config_kind": config_kind,
        "config_source": _compact_ability_config_source(config_source),
        "ability_paths": [path for path in ability_paths if path],
        "skill_param_dynamic_bindings": skill_param_summary,
        "numeric_binding_sources": [skill_param_binding_source] if skill_param_binding_source.get("by_hash") else [],
        "custom_value_keys": sorted(str(key) for key in custom_values.keys())[:80] if isinstance(custom_values, dict) else [],
        "custom_value_bindings": _custom_value_binding_summary(config_source, character_config),
        "override_skill_params": _json_safe(config_source.get("override_skill_params") or []),
    }
    return _json_safe(context)


def _compact_ability_config_source(config_source: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "relative_path",
        "row_index",
        "avatar_id",
        "monster_id",
        "servant_id",
        "template_id",
        "json_path",
        "template_source_path",
        "template_row_index",
        "version_kind",
        "enhanced_id",
    )
    return {key: _json_safe(config_source.get(key)) for key in keys if key in config_source}


def _custom_value_binding_summary(config_source: dict[str, Any], character_config: dict[str, Any]) -> dict[str, Any]:
    raw_custom_values = config_source.get("custom_values")
    character_values = character_config.get("CustomValues") if isinstance(character_config, dict) else None
    character_values = character_values if isinstance(character_values, dict) else {}
    entries: list[dict[str, Any]] = []
    if isinstance(raw_custom_values, list):
        for index, item in enumerate(raw_custom_values):
            if not isinstance(item, dict):
                continue
            name = item.get("BFLIFKBEOPJ") or item.get("Name") or item.get("Key")
            raw_value = item.get("MNDFOPKBHKP", item.get("Value"))
            entry: dict[str, Any] = {
                "index": index,
                "name": str(name or ""),
                "raw_path": f"CustomValues[{index}]",
                "raw_name_field": "BFLIFKBEOPJ" if "BFLIFKBEOPJ" in item else "",
                "raw_value_field": "MNDFOPKBHKP" if "MNDFOPKBHKP" in item else ("Value" if "Value" in item else ""),
                "value": _json_safe(raw_value),
                "character_config_value": _json_safe(character_values.get(str(name))) if name is not None else None,
                "character_config_hit": str(name) in character_values if name is not None else False,
            }
            entries.append(entry)
    elif isinstance(raw_custom_values, dict):
        for index, (name, raw_value) in enumerate(sorted(raw_custom_values.items(), key=lambda pair: str(pair[0]))):
            entries.append(
                {
                    "index": index,
                    "name": str(name),
                    "raw_path": f"CustomValues[{name}]",
                    "raw_name_field": "dict_key",
                    "raw_value_field": "dict_value",
                    "value": _json_safe(raw_value),
                    "character_config_value": _json_safe(character_values.get(str(name))),
                    "character_config_hit": str(name) in character_values,
                }
            )
    return {
        "source_type": "monster_config_custom_values",
        "entry_count": len(entries),
        "entries": _json_safe(entries[:24]),
        "hash_to_name_admitted": False,
        "blocked_reason": "custom_value_hash_to_name_binding_missing",
    }


def _skill_param_numeric_binding_source(
    *,
    character_config: dict[str, Any],
    skill_row: dict[str, Any],
    skill_trigger_key: str,
    character_path: str,
    skill_rows_by_trigger_key: dict[str, dict[str, Any]] | None = None,
    allowed_dynamic_hashes: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    floats = character_config.get("DynamicValues", {}).get("Floats") if isinstance(character_config, dict) else None
    rows_by_trigger: dict[str, dict[str, Any]] = dict(skill_rows_by_trigger_key or {})
    if skill_trigger_key and skill_trigger_key not in rows_by_trigger:
        rows_by_trigger[skill_trigger_key] = skill_row
    by_hash: dict[str, Any] = {}
    summary_entries: list[dict[str, Any]] = []
    if isinstance(floats, dict):
        for raw_hash, item in sorted(floats.items(), key=lambda pair: str(pair[0])):
            hash_key = str(raw_hash)
            if allowed_dynamic_hashes is not None and hash_key not in allowed_dynamic_hashes:
                continue
            if not isinstance(item, dict):
                continue
            read_info = item.get("ReadInfo")
            if not isinstance(read_info, dict):
                continue
            if read_info.get("Type") != "SkillParam":
                continue
            trigger_key = str(read_info.get("TriggerKey") or "")
            binding_skill_row = rows_by_trigger.get(trigger_key)
            if binding_skill_row is None:
                continue
            param_list = binding_skill_row.get("ParamList") if isinstance(binding_skill_row.get("ParamList"), list) else []
            param_index_raw = read_info.get("Index")
            entry_summary: dict[str, Any] = {
                "hash": str(raw_hash),
                "trigger_key": trigger_key,
                "current_skill_trigger_key": skill_trigger_key,
                "skill_id": _json_safe(binding_skill_row.get("SkillID")),
                "skill_source_path": str(binding_skill_row.get("_v8_source_path") or ""),
                "skill_row_index": _json_safe(binding_skill_row.get("_v8_row_index")),
                "param_index": _json_safe(param_index_raw),
                "read_info": _json_safe(read_info),
                "source_path": character_path,
                "raw_path": f"DynamicValues.Floats[{raw_hash}].ReadInfo",
            }
            if not isinstance(param_index_raw, int):
                summary_entries.append({**entry_summary, "admission_status": "blocked", "blocked_reason": "skill_param_index_not_integer"})
                continue
            if param_index_raw < 0 or param_index_raw >= len(param_list):
                summary_entries.append(
                    {
                        **entry_summary,
                        "admission_status": "blocked",
                        "blocked_reason": "skill_param_index_out_of_range",
                        "param_count": len(param_list),
                    }
                )
                continue
            param_raw = param_list[param_index_raw]
            value = _numeric_param_value(param_raw)
            if value is None:
                summary_entries.append(
                    {
                        **entry_summary,
                        "admission_status": "blocked",
                        "blocked_reason": "skill_param_value_not_numeric",
                        "param_raw": _json_safe(param_raw),
                    }
                )
                continue
            entry = {
                "hash": str(raw_hash),
                "trigger_key": trigger_key,
                "current_skill_trigger_key": skill_trigger_key,
                "skill_id": _json_safe(binding_skill_row.get("SkillID")),
                "skill_source_path": str(binding_skill_row.get("_v8_source_path") or ""),
                "skill_row_index": _json_safe(binding_skill_row.get("_v8_row_index")),
                "param_index": _json_safe(param_index_raw),
                "source_path": character_path,
                "raw_path": f"DynamicValues.Floats[{raw_hash}].ReadInfo",
                "admission_status": "executable",
                "param_raw": _json_safe(param_raw),
                "value": float(value),
                "source_trace": {
                    "source_path": character_path,
                    "raw_type": "CharacterConfig.DynamicValues.SkillParam",
                    "raw_id": str(raw_hash),
                    "evidence": {
                        "skill_source_path": str(skill_row.get("_v8_source_path") or ""),
                        "current_skill_id": _json_safe(skill_row.get("SkillID")),
                        "current_skill_trigger_key": skill_trigger_key,
                        "binding_skill_source_path": str(binding_skill_row.get("_v8_source_path") or ""),
                        "binding_skill_id": _json_safe(binding_skill_row.get("SkillID")),
                        "binding_skill_trigger_key": trigger_key,
                        "param_ref": f"ParamList[{param_index_raw}]",
                        "param_value": _json_safe(param_raw),
                    },
                },
            }
            by_hash[str(raw_hash)] = entry
            summary_entries.append(entry)
    binding_source = {
        "source_type": "character_config_skill_param",
        "by_hash": by_hash,
        "by_name": {},
    }
    summary = {
        "source_type": "character_config_skill_param",
        "entry_count": len(by_hash),
        "blocked_count": sum(1 for item in summary_entries if item.get("admission_status") == "blocked"),
        "allowed_dynamic_hash_count": len(allowed_dynamic_hashes or ()),
        "entries": summary_entries[:12],
    }
    return binding_source, summary


def _dynamic_hashes_for_ability_names(ability_names: list[str], ability_map: dict[str, dict[str, Any]]) -> set[str]:
    hashes: set[str] = set()
    for ability_name in ability_names:
        ability = ability_map.get(ability_name)
        if isinstance(ability, dict):
            _collect_dynamic_hashes(ability, hashes)
    return hashes


def _collect_dynamic_hashes(value: Any, result: set[str]) -> None:
    if isinstance(value, dict):
        dynamic_hashes = value.get("DynamicHashes")
        if isinstance(dynamic_hashes, list):
            for item in dynamic_hashes:
                if isinstance(item, int):
                    result.add(str(item))
        for item in value.values():
            _collect_dynamic_hashes(item, result)
    elif isinstance(value, list):
        for item in value:
            _collect_dynamic_hashes(item, result)


def _skill_rows_by_trigger_key_for_config(
    config_source: dict[str, Any],
    skill_rows_by_id: dict[str, dict[str, Any]],
    current_skill_row: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}

    def add(row: Any) -> None:
        if not isinstance(row, dict):
            return
        trigger_key = str(row.get("SkillTriggerKey") or "")
        if trigger_key:
            rows.setdefault(trigger_key, row)

    add(current_skill_row)
    for key in ("skill_list", "base_skill_list", "enhanced_skill_list"):
        raw_skill_ids = config_source.get(key)
        if not isinstance(raw_skill_ids, list):
            continue
        for skill_id in raw_skill_ids:
            add(skill_rows_by_id.get(str(skill_id)))
    return rows


def _numeric_param_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        return _numeric_param_value(value.get("Value"))
    return None


def _dynamic_value_requests(dynamic_values: dict[str, Any]) -> dict[str, Any]:
    requests: dict[str, Any] = {}
    for key, expr in dynamic_values.items():
        request: dict[str, Any] = {"name": key, "expr": _json_safe(expr)}
        if isinstance(expr, dict) and expr.get("kind") == "dynamic_hash":
            request["hash"] = expr.get("hash")
        requests[key] = request
    return requests


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _summon_unit_config_summary(config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {"config_readable": False}
    on_create_opcodes = _iter_gamecore_opcodes(config.get("OnCreate"))[:40]
    on_destroy_opcodes = _iter_gamecore_opcodes(config.get("OnDestroy"))[:40]
    trigger_opcodes = _iter_gamecore_opcodes(config.get("TriggerConfig"))[:80]
    adventure_or_maze_markers = _summon_unit_adventure_or_maze_markers(
        group_name=str(config.get("GroupConfigName") or ""),
        opcodes=(*on_create_opcodes, *on_destroy_opcodes, *trigger_opcodes),
    )
    return {
        "config_readable": True,
        "group_config_name": str(config.get("GroupConfigName") or ""),
        "config_entity_path": str(config.get("ConfigEntityPath") or ""),
        "has_skill_config": isinstance(config.get("SkillConfig"), dict),
        "has_ai_config": isinstance(config.get("AIConfig"), dict),
        "has_trigger_config": isinstance(config.get("TriggerConfig"), dict),
        "has_resident_effects": isinstance(config.get("ResidentEffects"), list) and bool(config.get("ResidentEffects")),
        "on_create_opcodes": on_create_opcodes,
        "on_destroy_opcodes": on_destroy_opcodes,
        "trigger_opcodes": trigger_opcodes,
        "adventure_or_maze_markers": adventure_or_maze_markers,
        "raw_config_keys": sorted(str(key) for key in config.keys())[:80],
    }


def _summon_unit_kind(row: dict[str, Any], config_summary: dict[str, Any]) -> str:
    source_mode = _summon_unit_source_mode(row, config_summary)
    if source_mode == "client_or_visual":
        return "client_or_visual_summon"
    if source_mode == "destroy_on_enter_battle":
        return "destroy_on_enter_battle_summon"
    if source_mode == "adventure_or_maze":
        return "adventure_or_maze_summon"
    if source_mode == "battle_runtime_candidate":
        return "battle_runtime_candidate"
    if source_mode == "config_missing":
        return "config_missing"
    return "catalog_or_scene_summon"


def _summon_unit_source_mode(row: dict[str, Any], config_summary: dict[str, Any]) -> str:
    if row.get("IsClient") is True:
        return "client_or_visual"
    if row.get("DestroyOnEnterBattle") is True:
        return "destroy_on_enter_battle"
    if config_summary.get("config_readable") is not True:
        return "config_missing"
    group_name = str(config_summary.get("group_config_name") or "")
    markers = config_summary.get("adventure_or_maze_markers")
    if group_name in {"FollowUnit", "FollowField", "Field"} or (isinstance(markers, list) and markers):
        return "adventure_or_maze"
    if row.get("IsTeamSummon") is True or config_summary.get("has_skill_config") is True:
        return "battle_runtime_candidate"
    return "catalog_or_scene"


def _summon_unit_blocked_reason(row: dict[str, Any], config_summary: dict[str, Any]) -> str:
    source_mode = _summon_unit_source_mode(row, config_summary)
    if source_mode == "client_or_visual":
        return "summon_unit_client_only_not_combat_runtime"
    if source_mode == "destroy_on_enter_battle":
        return "summon_unit_destroy_on_enter_battle_not_battle_spawn"
    if source_mode == "config_missing":
        return "summon_unit_config_missing"
    if source_mode == "adventure_or_maze":
        return "summon_unit_adventure_or_maze_not_combat_runtime"
    if source_mode == "catalog_or_scene":
        return "summon_unit_catalog_or_scene_not_battle_trigger"
    return "summon_unit_battle_admission_source_missing"


def _summon_unit_battle_admission(
    row: dict[str, Any],
    config_summary: dict[str, Any],
    blocked_reason: str,
) -> dict[str, Any]:
    source_mode = _summon_unit_source_mode(row, config_summary)
    return {
        "admission_status": "blocked",
        "blocked_reason": blocked_reason,
        "source_mode": source_mode,
        "catalog_not_trigger": source_mode in {"catalog_or_scene", "client_or_visual", "destroy_on_enter_battle", "adventure_or_maze"},
        "runtime_spawn_requires_explicit_intent": True,
        "raw_flags": _summon_unit_raw_flags(row),
        "config_markers": {
            "group_config_name": str(config_summary.get("group_config_name") or ""),
            "config_entity_path": str(config_summary.get("config_entity_path") or ""),
            "has_skill_config": config_summary.get("has_skill_config") is True,
            "has_ai_config": config_summary.get("has_ai_config") is True,
            "has_trigger_config": config_summary.get("has_trigger_config") is True,
            "has_resident_effects": config_summary.get("has_resident_effects") is True,
            "adventure_or_maze_markers": list(config_summary.get("adventure_or_maze_markers") or []),
        },
        "required_runtime_sources": {
            "battle_trigger": {
                "admission_status": "blocked",
                "blocked_reason": "summon_unit_battle_trigger_source_absent",
            },
            "unit_profile": {
                "admission_status": "blocked",
                "blocked_reason": "summon_unit_profile_source_absent",
            },
            "stats": {
                "admission_status": "blocked",
                "blocked_reason": "summon_unit_stats_source_absent",
            },
            "position": {
                "admission_status": "blocked",
                "blocked_reason": "summon_unit_position_source_absent",
            },
            "lifetime": {
                "admission_status": "blocked",
                "blocked_reason": "summon_unit_lifetime_source_absent",
            },
            "targetability": {
                "admission_status": "blocked",
                "blocked_reason": "summon_unit_targetability_source_absent",
            },
            "actionability": {
                "admission_status": "blocked",
                "blocked_reason": "summon_unit_actionability_source_absent",
            },
        },
    }


def _summon_unit_raw_flags(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "is_client": row.get("IsClient") is True,
        "is_team_summon": row.get("IsTeamSummon") is True,
        "destroy_on_enter_battle": row.get("DestroyOnEnterBattle") is True,
        "remove_maze_buff_on_destroy": row.get("RemoveMazeBuffOnDestroy") is True,
        "max_summon_count": _optional_int(row.get("MaxSummonCount")),
        "unique_group": str(row.get("UniqueGroup") or ""),
    }


def _summon_unit_adventure_or_maze_markers(*, group_name: str, opcodes: tuple[str, ...]) -> list[str]:
    markers: list[str] = []
    if group_name in {"FollowUnit", "FollowField", "Field"}:
        markers.append(f"group_config:{group_name}")
    adventure_opcodes = {
        "AddMazeBuff",
        "RefreshMazeBuffTime",
        "AddAdventureModifier",
        "TriggerHitProp",
        "PropDestructReset",
        "RemoveEffect",
        "TriggerEffect",
    }
    for opcode in opcodes:
        if opcode in adventure_opcodes:
            markers.append(f"opcode:{opcode}")
    return list(dict.fromkeys(markers))


def _target_alias(value: Any) -> str | None:
    if isinstance(value, dict):
        alias = value.get("Alias")
        if isinstance(alias, str):
            return alias
    return None


def _value_field(value: Any) -> Any:
    if isinstance(value, dict) and "Value" in value:
        return _json_safe(value.get("Value"))
    return _json_safe(value)


def _first_present_key(value: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        if key in value:
            return key
    return ""


def _numeric_expr_summary(value: Any) -> dict[str, Any]:
    if value is None:
        return {"kind": "missing", "value": None, "supported": False, "reason": "missing"}
    if isinstance(value, (int, float)):
        return {"kind": "fixed", "value": float(value), "supported": True}
    if isinstance(value, dict):
        fixed = value.get("FixedValue")
        if isinstance(fixed, dict) and isinstance(fixed.get("Value"), (int, float)):
            return {"kind": "fixed", "value": float(fixed["Value"]), "supported": True}
        if isinstance(value.get("Value"), (int, float)):
            return {"kind": "fixed", "value": float(value["Value"]), "supported": True}
        postfix = value.get("PostfixExpr")
        if isinstance(postfix, dict):
            postfix_fixed = _postfix_expr_fixed_value(postfix)
            if postfix_fixed is not None:
                return {
                    "kind": "fixed",
                    "value": postfix_fixed,
                    "supported": True,
                    "raw": _json_safe(value),
                    "admission": "postfix_fixed_arithmetic",
                }
            hashes = postfix.get("DynamicHashes")
            fixed_values = postfix.get("FixedValues")
            opcodes = postfix.get("OpCodes")
            if (
                opcodes == "AQAR"
                and isinstance(hashes, list)
                and len(hashes) == 1
                and isinstance(hashes[0], int)
                and (not fixed_values)
            ):
                return {
                    "kind": "dynamic_hash",
                    "hash": int(hashes[0]),
                    "supported": True,
                    "raw": _json_safe(value),
                }
            if _postfix_expr_is_admitted(postfix):
                return {
                    "kind": "postfix_expr",
                    "supported": True,
                    "raw": _json_safe(value),
                    "admission": "postfix_add_sub_mul_div",
                }
            return {
                "kind": "postfix_expr",
                "supported": False,
                "reason": "unsupported_postfix_expr",
                "raw": _json_safe(value),
            }
    return {"kind": "unsupported", "supported": False, "reason": "unsupported_numeric_expression", "raw": _json_safe(value)}


def _fixed_expr_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict) and value.get("kind") == "fixed" and isinstance(value.get("value"), (int, float)):
        return float(value["value"])
    return None


def _postfix_expr_fixed_value(postfix: dict[str, Any]) -> float | None:
    dynamic_hashes = postfix.get("DynamicHashes")
    if isinstance(dynamic_hashes, list) and dynamic_hashes:
        return None
    fixed_values = postfix.get("FixedValues")
    if not isinstance(fixed_values, list):
        return None
    opcodes = postfix.get("OpCodes")
    if not isinstance(opcodes, str) or not opcodes:
        return None
    try:
        decoded = list(base64.b64decode(opcodes))
    except Exception:
        return None
    stack: list[float] = []
    index = 0
    ended = False
    while index < len(decoded):
        opcode = decoded[index]
        if opcode == 17:
            ended = True
            index += 1
            continue
        if opcode == 0:
            if index + 1 >= len(decoded):
                return None
            fixed_index = decoded[index + 1]
            if fixed_index >= len(fixed_values):
                return None
            value = _numeric_fixed_value_item(fixed_values[fixed_index])
            if value is None:
                return None
            stack.append(value)
            index += 2
            continue
        if opcode in {2, 3, 4, 5}:
            if len(stack) < 2:
                return None
            right = stack.pop()
            left = stack.pop()
            if opcode == 2:
                stack.append(left + right)
            elif opcode == 3:
                stack.append(left - right)
            elif opcode == 4:
                stack.append(left * right)
            elif opcode == 5:
                if right == 0:
                    return None
                stack.append(left / right)
            index += 1
            continue
        return None
    return stack[0] if ended and len(stack) == 1 else None


def _numeric_fixed_value_item(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict) and isinstance(value.get("Value"), (int, float)):
        return float(value["Value"])
    return None


def _numeric_expr_can_be_runtime_bound(value: Any) -> bool:
    if _fixed_expr_value(value) is not None:
        return True
    if isinstance(value, dict) and value.get("kind") == "dynamic_hash" and value.get("hash") is not None:
        return True
    if isinstance(value, dict) and value.get("kind") == "postfix_expr" and value.get("supported") is True:
        return True
    return False


def _break_damage_blocked_reason(scaling_expr: dict[str, Any]) -> str:
    reason = scaling_expr.get("reason")
    kind = scaling_expr.get("kind")
    if isinstance(reason, str) and reason:
        return f"break_damage_percentage_not_executable:{kind}:{reason}"
    if kind == "dynamic_hash":
        return "break_damage_formula_not_admitted:break_base_damage_inputs_missing"
    if kind == "fixed":
        return "break_damage_formula_not_admitted:break_base_damage_formula_missing"
    return f"break_damage_percentage_not_executable:{kind or 'unknown'}"


def _super_break_blocked_reason(scaling_expr: dict[str, Any]) -> str:
    reason = scaling_expr.get("reason")
    kind = scaling_expr.get("kind")
    if isinstance(reason, str) and reason:
        return f"super_break_percentage_not_executable:{kind}:{reason}"
    return f"super_break_percentage_not_executable:{kind or 'unknown'}"


def _is_super_break_attack_property(attack_property: dict[str, Any], *, template_name: str) -> bool:
    formula_type = str(attack_property.get("FormulaType") or "")
    final_formula_type = str(attack_property.get("FinalFormulaType") or "")
    display = attack_property.get("DisplayData")
    display_element = str(display.get("ElementDamageType") or "") if isinstance(display, dict) else ""
    return (
        template_name in {"DealSuperBreakDamage", "BeingDealSuperBreakDamage"}
        and formula_type == "ByBreakDamage"
        and (final_formula_type == "ByPureDamage" or display_element == "Super")
    )


def _display_element_type(attack_property: dict[str, Any]) -> str | None:
    display = attack_property.get("DisplayData")
    if not isinstance(display, dict):
        return None
    element = display.get("ElementDamageType")
    return str(element) if isinstance(element, str) and element else None


def _attack_property_element_type(attack_property: dict[str, Any]) -> str | None:
    damage_type = attack_property.get("DamageType")
    if isinstance(damage_type, dict):
        element = damage_type.get("DamageType")
        if isinstance(element, str) and element:
            return element
    return _display_element_type(attack_property)


def _attack_property_custom_name(payload: dict[str, Any]) -> str:
    attack_property = payload.get("AttackProperty")
    if not isinstance(attack_property, dict):
        return ""
    value = _value_field(attack_property.get("CustomName"))
    return value if isinstance(value, str) else ""


def _iter_task_tree(value: Any, *, prefix: str) -> list[tuple[str, dict[str, Any]]]:
    result: list[tuple[str, dict[str, Any]]] = []
    if not isinstance(value, list):
        return result
    for index, task in enumerate(value):
        if not isinstance(task, dict):
            continue
        path = f"{prefix}[{index}]"
        result.append((path, task))
        for child_key in ("TaskList", "SuccessTaskList", "FailedTaskList"):
            child = task.get(child_key)
            if isinstance(child, list):
                result.extend(_iter_task_tree(child, prefix=f"{path}.{child_key}"))
    return result


def _safe_id(value: str) -> str:
    return (
        value.replace("[", "_")
        .replace("]", "")
        .replace(".", "_")
        .replace(":", "_")
        .replace("/", "_")
    )


def _postfix_expr_is_admitted(postfix: dict[str, Any]) -> bool:
    opcodes = postfix.get("OpCodes")
    if not isinstance(opcodes, str) or not opcodes:
        return False
    try:
        decoded = list(base64.b64decode(opcodes))
    except Exception:
        return False
    fixed_values = postfix.get("FixedValues")
    dynamic_hashes = postfix.get("DynamicHashes")
    fixed_count = len(fixed_values) if isinstance(fixed_values, list) else 0
    dynamic_count = len(dynamic_hashes) if isinstance(dynamic_hashes, list) else 0
    stack_size = 0
    index = 0
    ended = False
    while index < len(decoded):
        opcode = decoded[index]
        if opcode == 17:
            ended = True
            index += 1
            continue
        if opcode == 0:
            if index + 1 >= len(decoded) or decoded[index + 1] >= fixed_count:
                return False
            stack_size += 1
            index += 2
            continue
        if opcode == 1:
            if index + 1 >= len(decoded) or decoded[index + 1] >= dynamic_count:
                return False
            stack_size += 1
            index += 2
            continue
        if opcode in {2, 3, 4, 5}:
            if stack_size < 2:
                return False
            stack_size -= 1
            index += 1
            continue
        return False
    return ended and stack_size == 1


def _mechanism_bar_has_fixed_payload(standard: dict[str, Any]) -> bool:
    if standard.get("state") is not None or standard.get("active") is not None:
        return True
    return _fixed_expr_value(standard.get("current_count")) is not None or _fixed_expr_value(standard.get("max_count")) is not None


def _mechanism_bar_has_runtime_payload(standard: dict[str, Any]) -> bool:
    if standard.get("state") is not None or standard.get("active") is not None:
        return True
    return _numeric_expr_can_be_runtime_bound(standard.get("current_count")) or _numeric_expr_can_be_runtime_bound(standard.get("max_count"))


def _task_damage_family(value: dict[str, Any], opcode: str) -> str:
    attack_type = str(value.get("AttackType") or "")
    formula_type = str(value.get("FormulaType") or "")
    if attack_type == "ElationDamage" or formula_type == "ByElationDamage":
        return "elation"
    if attack_type == "TrueDamage":
        return "true_damage"
    if opcode in {"LoseHPByRatio", "DirectlyLoseHp", "DirectlyLoseHpHit"}:
        return "hp_loss"
    return "unknown"


def _damage_behavior_family(template_name: str) -> str:
    if template_name == "TrueDamage":
        return "true_damage"
    if template_name in {"DirectlyLoseHp", "DirectlyLoseHpHit"}:
        return "hp_loss"
    return "unknown"


def _damage_family_evidence(
    task: dict[str, Any],
    opcode: str,
    source: IRSource,
    parent_id: str,
) -> list[FormulaIR]:
    family = _task_damage_family(task, opcode)
    if family == "unknown":
        return []
    property_name = {
        "elation": "ElationDamage",
        "true_damage": "TrueDamage",
        "hp_loss": opcode,
    }[family]
    return [
        FormulaIR(
            formula_id=f"formula:{parent_id}:damage_family:{family}",
            kind="mechanic_property",
            expression={
                "mechanic": f"{family}_damage",
                "property": property_name,
                "damage_formula_family": family,
                "source_mode": "mainline",
                "bypasses_normal_multipliers": family in {"true_damage", "hp_loss"},
                "runtime_status": "executable" if family in {"true_damage", "hp_loss"} else "blocked",
                "blocked_reason": "Elation damage formula is not executable in v0_208"
                if family == "elation"
                else "",
            },
            source=source,
            coverage_status="blocked" if family == "elation" else "lowered",
        )
    ]


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _json_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _iter_postfix_expr(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        expr = value.get("PostfixExpr")
        if isinstance(expr, dict):
            found.append(expr)
        for nested in value.values():
            found.extend(_iter_postfix_expr(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_iter_postfix_expr(nested))
    return found


def _iter_fixed_values(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        fixed = value.get("FixedValue")
        if isinstance(fixed, dict) and "Value" in fixed:
            found.append(fixed)
        for nested in value.values():
            found.extend(_iter_fixed_values(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_iter_fixed_values(nested))
    return found


def _iter_elation_values(value: Any, path: tuple[str, ...] = ()) -> list[tuple[str, str, Any]]:
    found: list[tuple[str, str, Any]] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            child_path = (*path, str(key))
            if _is_elation_key(str(key)):
                found.append((".".join(child_path), str(key), nested))
            found.extend(_iter_elation_values(nested, child_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(_iter_elation_values(nested, (*path, str(index))))
    return found


def _is_elation_key(key: str) -> bool:
    return key.startswith("Elation") or "ElationTime" in key
