from __future__ import annotations

from dataclasses import dataclass

from .ir import (
    AbilityPhaseIR,
    AbilityTaskIR,
    ActionAbilityBindingIR,
    ActionDefinitionIR,
    ActionDelayEmissionIR,
    ActionEventIR,
    AvatarProfileIR,
    CharacterEidolonSlotIR,
    CharacterMechanismSlotIR,
    CharacterTraceNodeIR,
    CharacterDataCardIR,
    MonsterDataCardIR,
    PassiveMechanismSlotIR,
    BreakBaseDamageIR,
    BreakDamageEmissionIR,
    BreakStatusEmissionIR,
    BreakTemplateIR,
    BouncePolicyIR,
    CanonicalIR,
    CombatantActionSetIR,
    CombatantProfileIR,
    ConditionIR,
    DamageEmissionIR,
    DamageModifierIR,
    EffectIR,
    ExtraActionPolicyIR,
    FormulaIR,
    HitProfileIR,
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
    StatusCallbackTaskIR,
    StatusDamageEmissionIR,
    StatusEventFamilyIR,
    SuperBreakEmissionIR,
    TargetExpressionIR,
    TimelineRuleIR,
    ToughnessEmissionIR,
    TriggerIR,
    WaveDefinitionIR,
    WaveMonsterEntryIR,
)


@dataclass(frozen=True)
class RuleBook:
    """Read-only view over Canonical IR."""

    ir: CanonicalIR

    def __post_init__(self) -> None:
        object.__setattr__(self, "_entities", {entity.entity_id: entity for entity in self.ir.entities})
        modifier_definitions_by_name: dict[str, list[RuleEntity]] = {}
        status_entities_by_modifier: dict[str, list[RuleEntity]] = {}
        for entity in self.ir.entities:
            modifier_name = entity.fields.get("modifier_name")
            if not isinstance(modifier_name, str) or not modifier_name:
                modifier_name = entity.fields.get("ModifierName")
            if not isinstance(modifier_name, str) or not modifier_name:
                continue
            if entity.entity_type == "modifier_definition":
                modifier_definitions_by_name.setdefault(modifier_name, []).append(entity)
            elif entity.entity_type == "status":
                status_entities_by_modifier.setdefault(modifier_name, []).append(entity)
        object.__setattr__(
            self,
            "_modifier_definitions_by_name",
            {
                key: tuple(sorted(value, key=lambda item: (item.source.source_path, item.entity_id)))
                for key, value in modifier_definitions_by_name.items()
            },
        )
        object.__setattr__(
            self,
            "_status_entities_by_modifier",
            {
                key: tuple(sorted(value, key=lambda item: (item.source.source_path, item.entity_id)))
                for key, value in status_entities_by_modifier.items()
            },
        )
        object.__setattr__(
            self,
            "_avatar_profiles",
            {profile.avatar_id: profile for profile in self.ir.avatar_profiles},
        )
        object.__setattr__(
            self,
            "_character_data_cards",
            {card.card_id: card for card in self.ir.character_data_cards},
        )
        object.__setattr__(
            self,
            "_character_data_cards_by_entity_ref",
            {card.entity_ref: card for card in self.ir.character_data_cards},
        )
        object.__setattr__(
            self,
            "_monster_data_cards",
            {card.card_id: card for card in self.ir.monster_data_cards},
        )
        object.__setattr__(
            self,
            "_monster_data_cards_by_entity_ref",
            {card.entity_ref: card for card in self.ir.monster_data_cards},
        )
        mechanism_slots_by_card: dict[str, list[CharacterMechanismSlotIR]] = {}
        for slot in self.ir.character_mechanism_slots:
            mechanism_slots_by_card.setdefault(slot.character_data_card_id, []).append(slot)
        object.__setattr__(
            self,
            "_character_mechanism_slots",
            {slot.mechanism_slot_id: slot for slot in self.ir.character_mechanism_slots},
        )
        object.__setattr__(
            self,
            "_character_mechanism_slots_by_card",
            {
                key: tuple(sorted(value, key=lambda item: item.mechanism_slot_id))
                for key, value in mechanism_slots_by_card.items()
            },
        )
        passive_slots_by_card: dict[str, list[PassiveMechanismSlotIR]] = {}
        passive_slots_by_owner: dict[str, list[PassiveMechanismSlotIR]] = {}
        for slot in self.ir.passive_mechanism_slots:
            passive_slots_by_card.setdefault(slot.data_card_id, []).append(slot)
            passive_slots_by_owner.setdefault(slot.owner_entity_ref, []).append(slot)
        object.__setattr__(
            self,
            "_passive_mechanism_slots",
            {slot.passive_slot_id: slot for slot in self.ir.passive_mechanism_slots},
        )
        object.__setattr__(
            self,
            "_passive_mechanism_slots_by_card",
            {
                key: tuple(sorted(value, key=lambda item: item.passive_slot_id))
                for key, value in passive_slots_by_card.items()
            },
        )
        object.__setattr__(
            self,
            "_passive_mechanism_slots_by_owner",
            {
                key: tuple(sorted(value, key=lambda item: item.passive_slot_id))
                for key, value in passive_slots_by_owner.items()
            },
        )
        trace_nodes_by_card: dict[str, list[CharacterTraceNodeIR]] = {}
        for node in self.ir.character_trace_nodes:
            trace_nodes_by_card.setdefault(node.character_data_card_id, []).append(node)
        object.__setattr__(
            self,
            "_character_trace_nodes",
            {node.trace_node_id: node for node in self.ir.character_trace_nodes},
        )
        object.__setattr__(
            self,
            "_character_trace_nodes_by_card",
            {
                key: tuple(sorted(value, key=lambda item: (item.trace_id, item.trace_node_id)))
                for key, value in trace_nodes_by_card.items()
            },
        )
        eidolon_slots_by_card: dict[str, list[CharacterEidolonSlotIR]] = {}
        for slot in self.ir.character_eidolon_slots:
            eidolon_slots_by_card.setdefault(slot.character_data_card_id, []).append(slot)
        object.__setattr__(
            self,
            "_character_eidolon_slots",
            {slot.eidolon_slot_id: slot for slot in self.ir.character_eidolon_slots},
        )
        object.__setattr__(
            self,
            "_character_eidolon_slots_by_card",
            {
                key: tuple(sorted(value, key=lambda item: (item.rank, item.eidolon_slot_id)))
                for key, value in eidolon_slots_by_card.items()
            },
        )
        bounce_policies_by_action: dict[tuple[str, int], list[BouncePolicyIR]] = {}
        for policy in self.ir.bounce_policies:
            bounce_policies_by_action.setdefault((policy.action_id, policy.level), []).append(policy)
        object.__setattr__(
            self,
            "_bounce_policies",
            {policy.bounce_policy_id: policy for policy in self.ir.bounce_policies},
        )
        object.__setattr__(
            self,
            "_bounce_policies_by_action",
            {
                key: tuple(sorted(value, key=lambda item: item.bounce_policy_id))
                for key, value in bounce_policies_by_action.items()
            },
        )
        object.__setattr__(
            self,
            "_combatant_profiles",
            {profile.entity_id: profile for profile in self.ir.combatant_profiles},
        )
        object.__setattr__(
            self,
            "_action_definitions",
            {(definition.action_id, definition.level): definition for definition in self.ir.action_definitions},
        )
        damage_modifiers_by_callback: dict[str, list[DamageModifierIR]] = {}
        for modifier in self.ir.damage_modifiers:
            damage_modifiers_by_callback.setdefault(modifier.callback_id, []).append(modifier)
        object.__setattr__(
            self,
            "_damage_modifiers",
            {modifier.damage_modifier_id: modifier for modifier in self.ir.damage_modifiers},
        )
        object.__setattr__(
            self,
            "_damage_modifiers_by_callback",
            {
                key: tuple(sorted(value, key=lambda item: (item.source_task_id, item.damage_modifier_id)))
                for key, value in damage_modifiers_by_callback.items()
            },
        )
        object.__setattr__(
            self,
            "_action_events",
            {(event.action_id, event.level): event for event in self.ir.action_events},
        )
        object.__setattr__(
            self,
            "_action_ability_bindings",
            {(binding.action_id, binding.level): binding for binding in self.ir.action_ability_bindings},
        )
        ability_phases_by_binding: dict[str, list[AbilityPhaseIR]] = {}
        ability_phases_by_action: dict[tuple[str, int], list[AbilityPhaseIR]] = {}
        for phase in self.ir.ability_phases:
            ability_phases_by_binding.setdefault(phase.binding_id, []).append(phase)
            ability_phases_by_action.setdefault((phase.action_id, phase.level), []).append(phase)
        object.__setattr__(self, "_ability_phases", {phase.phase_id: phase for phase in self.ir.ability_phases})
        object.__setattr__(
            self,
            "_ability_phases_by_binding",
            {
                key: tuple(sorted(value, key=lambda item: (item.phase_index, item.phase_id)))
                for key, value in ability_phases_by_binding.items()
            },
        )
        object.__setattr__(
            self,
            "_ability_phases_by_action",
            {
                key: tuple(sorted(value, key=lambda item: (item.phase_index, item.phase_id)))
                for key, value in ability_phases_by_action.items()
            },
        )
        ability_tasks_by_phase: dict[str, list[AbilityTaskIR]] = {}
        ability_tasks_by_action: dict[tuple[str, int], list[AbilityTaskIR]] = {}
        for task in self.ir.ability_tasks:
            ability_tasks_by_phase.setdefault(task.phase_id, []).append(task)
            ability_tasks_by_action.setdefault((task.action_id, task.level), []).append(task)
        object.__setattr__(self, "_ability_tasks", {task.task_id: task for task in self.ir.ability_tasks})
        object.__setattr__(
            self,
            "_ability_tasks_by_phase",
            {
                key: tuple(sorted(value, key=lambda item: (item.callback_kind, item.task_path, item.task_id)))
                for key, value in ability_tasks_by_phase.items()
            },
        )
        object.__setattr__(
            self,
            "_ability_tasks_by_action",
            {
                key: tuple(sorted(value, key=lambda item: (item.phase_id, item.callback_kind, item.task_path, item.task_id)))
                for key, value in ability_tasks_by_action.items()
            },
        )
        hit_profiles_by_action: dict[tuple[str, int], list[HitProfileIR]] = {}
        for profile in self.ir.hit_profiles:
            hit_profiles_by_action.setdefault((profile.action_id, profile.level), []).append(profile)
        object.__setattr__(self, "_hit_profiles", {profile.hit_profile_id: profile for profile in self.ir.hit_profiles})
        object.__setattr__(
            self,
            "_hit_profiles_by_action",
            {
                key: tuple(sorted(value, key=lambda item: (item.hit_index, item.target_group, item.hit_profile_id)))
                for key, value in hit_profiles_by_action.items()
            },
        )
        skill_formula_bindings_by_action_param_role: dict[tuple[str, int, int, str], list[SkillFormulaBindingIR]] = {}
        for binding in self.ir.skill_formula_bindings:
            skill_formula_bindings_by_action_param_role.setdefault(
                (binding.action_id, binding.level, binding.param_index, binding.formula_role),
                [],
            ).append(binding)
        object.__setattr__(
            self,
            "_skill_formula_bindings",
            {binding.binding_id: binding for binding in self.ir.skill_formula_bindings},
        )
        object.__setattr__(
            self,
            "_skill_formula_bindings_by_action_param_role",
            {
                key: tuple(sorted(value, key=lambda item: item.binding_id))
                for key, value in skill_formula_bindings_by_action_param_role.items()
            },
        )
        damage_emissions_by_action: dict[tuple[str, int], list[DamageEmissionIR]] = {}
        damage_emissions_by_task: dict[str, list[DamageEmissionIR]] = {}
        for emission in self.ir.damage_emissions:
            damage_emissions_by_action.setdefault((emission.action_id, emission.level), []).append(emission)
            damage_emissions_by_task.setdefault(emission.source_task_id, []).append(emission)
        object.__setattr__(self, "_damage_emissions", {emission.damage_emission_id: emission for emission in self.ir.damage_emissions})
        object.__setattr__(
            self,
            "_damage_emissions_by_action",
            {
                key: tuple(sorted(value, key=lambda item: (item.source_task_id, item.hit_profile_id, item.damage_emission_id)))
                for key, value in damage_emissions_by_action.items()
            },
        )
        object.__setattr__(
            self,
            "_damage_emissions_by_task",
            {
                key: tuple(sorted(value, key=lambda item: (item.hit_profile_id, item.damage_emission_id)))
                for key, value in damage_emissions_by_task.items()
            },
        )
        toughness_emissions_by_action: dict[tuple[str, int], list[ToughnessEmissionIR]] = {}
        toughness_emissions_by_task: dict[str, list[ToughnessEmissionIR]] = {}
        for emission in self.ir.toughness_emissions:
            toughness_emissions_by_action.setdefault((emission.action_id, emission.level), []).append(emission)
            toughness_emissions_by_task.setdefault(emission.source_task_id, []).append(emission)
        object.__setattr__(
            self,
            "_toughness_emissions",
            {emission.toughness_emission_id: emission for emission in self.ir.toughness_emissions},
        )
        object.__setattr__(
            self,
            "_toughness_emissions_by_action",
            {
                key: tuple(sorted(value, key=lambda item: (item.source_task_id, item.hit_profile_id, item.toughness_emission_id)))
                for key, value in toughness_emissions_by_action.items()
            },
        )
        object.__setattr__(
            self,
            "_toughness_emissions_by_task",
            {
                key: tuple(sorted(value, key=lambda item: (item.hit_profile_id, item.toughness_emission_id)))
                for key, value in toughness_emissions_by_task.items()
            },
        )
        object.__setattr__(
            self,
            "_break_templates",
            {template.template_id: template for template in self.ir.break_templates},
        )
        object.__setattr__(
            self,
            "_break_templates_by_element",
            {
                str(template.element_type): template
                for template in self.ir.break_templates
                if template.element_type
            },
        )
        object.__setattr__(
            self,
            "_break_damage_emissions",
            {emission.break_damage_emission_id: emission for emission in self.ir.break_damage_emissions},
        )
        object.__setattr__(
            self,
            "_break_base_damage_by_level",
            {row.level: row for row in self.ir.break_base_damage},
        )
        break_damage_emissions_by_template: dict[str, list[BreakDamageEmissionIR]] = {}
        for emission in self.ir.break_damage_emissions:
            break_damage_emissions_by_template.setdefault(emission.template_id, []).append(emission)
        object.__setattr__(
            self,
            "_break_damage_emissions_by_template",
            {
                key: tuple(sorted(value, key=lambda item: item.break_damage_emission_id))
                for key, value in break_damage_emissions_by_template.items()
            },
        )
        object.__setattr__(
            self,
            "_break_status_emissions",
            {emission.break_status_emission_id: emission for emission in self.ir.break_status_emissions},
        )
        break_status_emissions_by_template: dict[str, list[BreakStatusEmissionIR]] = {}
        for emission in self.ir.break_status_emissions:
            break_status_emissions_by_template.setdefault(emission.template_id, []).append(emission)
        object.__setattr__(
            self,
            "_break_status_emissions_by_template",
            {
                key: tuple(sorted(value, key=lambda item: item.break_status_emission_id))
                for key, value in break_status_emissions_by_template.items()
            },
        )
        object.__setattr__(
            self,
            "_status_callbacks",
            {callback.callback_id: callback for callback in self.ir.status_callbacks},
        )
        object.__setattr__(
            self,
            "_status_event_families",
            {family.callback_event: family for family in self.ir.status_event_families},
        )
        status_event_families_by_runtime_event: dict[str, list[StatusEventFamilyIR]] = {}
        for family in self.ir.status_event_families:
            for runtime_event in family.runtime_event_sources:
                status_event_families_by_runtime_event.setdefault(runtime_event, []).append(family)
        object.__setattr__(
            self,
            "_status_event_families_by_runtime_event",
            {
                key: tuple(sorted(value, key=lambda item: item.callback_event))
                for key, value in status_event_families_by_runtime_event.items()
            },
        )
        status_callbacks_by_modifier_event: dict[tuple[str, str], list[StatusCallbackIR]] = {}
        status_callbacks_by_event: dict[str, list[StatusCallbackIR]] = {}
        status_callbacks_by_event_scope: dict[tuple[str, str], list[StatusCallbackIR]] = {}
        status_callbacks_by_modifier_event_scope: dict[tuple[str, str, str], list[StatusCallbackIR]] = {}
        for callback in self.ir.status_callbacks:
            status_callbacks_by_modifier_event.setdefault((callback.modifier_name, callback.event), []).append(callback)
            status_callbacks_by_event.setdefault(callback.event, []).append(callback)
            status_callbacks_by_event_scope.setdefault((callback.event, callback.scope_kind), []).append(callback)
            status_callbacks_by_modifier_event_scope.setdefault(
                (callback.modifier_name, callback.event, callback.scope_kind),
                [],
            ).append(callback)
        object.__setattr__(
            self,
            "_status_callbacks_by_modifier_event",
            {
                key: tuple(sorted(value, key=lambda item: item.callback_id))
                for key, value in status_callbacks_by_modifier_event.items()
            },
        )
        object.__setattr__(
            self,
            "_status_callbacks_by_event",
            {
                key: tuple(sorted(value, key=lambda item: (item.modifier_name, item.callback_id)))
                for key, value in status_callbacks_by_event.items()
            },
        )
        object.__setattr__(
            self,
            "_status_callbacks_by_event_scope",
            {
                key: tuple(sorted(value, key=lambda item: (item.modifier_name, item.callback_id)))
                for key, value in status_callbacks_by_event_scope.items()
            },
        )
        object.__setattr__(
            self,
            "_status_callbacks_by_modifier_event_scope",
            {
                key: tuple(sorted(value, key=lambda item: item.callback_id))
                for key, value in status_callbacks_by_modifier_event_scope.items()
            },
        )
        object.__setattr__(
            self,
            "_status_callback_tasks",
            {task.task_id: task for task in self.ir.status_callback_tasks},
        )
        status_callback_tasks_by_callback: dict[str, list[StatusCallbackTaskIR]] = {}
        for task in self.ir.status_callback_tasks:
            status_callback_tasks_by_callback.setdefault(task.callback_id, []).append(task)
        object.__setattr__(
            self,
            "_status_callback_tasks_by_callback",
            {
                key: tuple(sorted(value, key=lambda item: (item.task_path, item.task_id)))
                for key, value in status_callback_tasks_by_callback.items()
            },
        )
        object.__setattr__(
            self,
            "_status_damage_emissions",
            {emission.status_damage_emission_id: emission for emission in self.ir.status_damage_emissions},
        )
        status_damage_emissions_by_callback: dict[str, list[StatusDamageEmissionIR]] = {}
        for emission in self.ir.status_damage_emissions:
            status_damage_emissions_by_callback.setdefault(emission.callback_id, []).append(emission)
        object.__setattr__(
            self,
            "_status_damage_emissions_by_callback",
            {
                key: tuple(sorted(value, key=lambda item: item.status_damage_emission_id))
                for key, value in status_damage_emissions_by_callback.items()
            },
        )
        object.__setattr__(
            self,
            "_action_delay_emissions",
            {emission.action_delay_emission_id: emission for emission in self.ir.action_delay_emissions},
        )
        action_delay_emissions_by_callback: dict[str, list[ActionDelayEmissionIR]] = {}
        for emission in self.ir.action_delay_emissions:
            action_delay_emissions_by_callback.setdefault(emission.callback_id, []).append(emission)
        object.__setattr__(
            self,
            "_action_delay_emissions_by_callback",
            {
                key: tuple(sorted(value, key=lambda item: item.action_delay_emission_id))
                for key, value in action_delay_emissions_by_callback.items()
            },
        )
        object.__setattr__(
            self,
            "_queue_intents",
            {intent.queue_intent_id: intent for intent in self.ir.queue_intents},
        )
        queue_intents_by_callback: dict[str, list[QueueIntentIR]] = {}
        for intent in self.ir.queue_intents:
            queue_intents_by_callback.setdefault(intent.callback_id, []).append(intent)
        object.__setattr__(
            self,
            "_queue_intents_by_callback",
            {
                key: tuple(sorted(value, key=lambda item: item.queue_intent_id))
                for key, value in queue_intents_by_callback.items()
            },
        )
        object.__setattr__(
            self,
            "_queue_resolutions",
            {resolution.queue_resolution_id: resolution for resolution in self.ir.queue_resolutions},
        )
        object.__setattr__(
            self,
            "_queue_resolution_by_intent",
            {resolution.queue_intent_id: resolution for resolution in self.ir.queue_resolutions},
        )
        object.__setattr__(
            self,
            "_queue_priorities",
            {priority.queue_priority_id: priority for priority in self.ir.queue_priorities},
        )
        object.__setattr__(
            self,
            "_queue_priority_by_table_key",
            {(priority.priority_table, priority.priority_key): priority for priority in self.ir.queue_priorities},
        )
        object.__setattr__(
            self,
            "_queue_windows",
            {window.queue_window_id: window for window in self.ir.queue_windows},
        )
        object.__setattr__(
            self,
            "_queue_window_by_intent",
            {window.queue_intent_id: window for window in self.ir.queue_windows},
        )
        object.__setattr__(
            self,
            "_queue_lifecycle_policies",
            {policy.queue_lifecycle_policy_id: policy for policy in self.ir.queue_lifecycle_policies},
        )
        object.__setattr__(
            self,
            "_queue_lifecycle_policy_by_window",
            {
                policy.queue_window_id: policy
                for policy in self.ir.queue_lifecycle_policies
                if policy.queue_window_id
            },
        )
        object.__setattr__(
            self,
            "_queue_lifecycle_policy_by_intent",
            {
                policy.queue_intent_id: policy
                for policy in self.ir.queue_lifecycle_policies
                if policy.queue_intent_id
            },
        )
        object.__setattr__(
            self,
            "_extra_action_policies",
            {policy.extra_action_policy_id: policy for policy in self.ir.extra_action_policies},
        )
        object.__setattr__(
            self,
            "_extra_action_policy_by_window",
            {
                policy.queue_window_id: policy
                for policy in self.ir.extra_action_policies
                if policy.queue_window_id
            },
        )
        object.__setattr__(
            self,
            "_extra_action_policy_by_intent",
            {
                policy.queue_intent_id: policy
                for policy in self.ir.extra_action_policies
                if policy.queue_intent_id
            },
        )
        object.__setattr__(
            self,
            "_skill_continuations",
            {continuation.continuation_id: continuation for continuation in self.ir.skill_continuations},
        )
        standalone_ability_graphs_by_name: dict[str, list[StandaloneAbilityGraphIR]] = {}
        for graph in self.ir.standalone_ability_graphs:
            standalone_ability_graphs_by_name.setdefault(graph.ability_name, []).append(graph)
        object.__setattr__(
            self,
            "_standalone_ability_graphs",
            {graph.standalone_ability_graph_id: graph for graph in self.ir.standalone_ability_graphs},
        )
        object.__setattr__(
            self,
            "_standalone_ability_graphs_by_name",
            {
                key: tuple(sorted(value, key=lambda item: (item.source.source_path, item.standalone_ability_graph_id)))
                for key, value in standalone_ability_graphs_by_name.items()
            },
        )
        object.__setattr__(
            self,
            "_combatant_action_sets",
            {action_set.entity_ref: action_set for action_set in self.ir.combatant_action_sets},
        )
        object.__setattr__(
            self,
            "_timeline_rules",
            {rule.timeline_rule_id: rule for rule in self.ir.timeline_rules},
        )
        object.__setattr__(
            self,
            "_resource_rules",
            {rule.resource_rule_id: rule for rule in self.ir.resource_rules},
        )
        object.__setattr__(
            self,
            "_super_break_emissions",
            {emission.super_break_emission_id: emission for emission in self.ir.super_break_emissions},
        )
        super_break_emissions_by_template: dict[str, list[SuperBreakEmissionIR]] = {}
        for emission in self.ir.super_break_emissions:
            super_break_emissions_by_template.setdefault(emission.template_id, []).append(emission)
        object.__setattr__(
            self,
            "_super_break_emissions_by_template",
            {
                key: tuple(sorted(value, key=lambda item: item.super_break_emission_id))
                for key, value in super_break_emissions_by_template.items()
            },
        )
        object.__setattr__(
            self,
            "_target_expressions",
            {expression.target_expression_id: expression for expression in self.ir.target_expressions},
        )
        wave_definitions_by_stage: dict[str, list[WaveDefinitionIR]] = {}
        wave_entries_by_definition_wave: dict[tuple[str, int], list[WaveMonsterEntryIR]] = {}
        for definition in self.ir.wave_definitions:
            wave_definitions_by_stage.setdefault(definition.stage_id, []).append(definition)
            for entry in definition.entries:
                wave_entries_by_definition_wave.setdefault(
                    (definition.wave_definition_id, entry.wave_index),
                    [],
                ).append(entry)
        object.__setattr__(
            self,
            "_wave_definitions",
            {definition.wave_definition_id: definition for definition in self.ir.wave_definitions},
        )
        object.__setattr__(
            self,
            "_wave_definitions_by_stage",
            {
                stage_id: tuple(sorted(definitions, key=lambda item: item.wave_definition_id))
                for stage_id, definitions in wave_definitions_by_stage.items()
            },
        )
        object.__setattr__(
            self,
            "_wave_entries_by_definition_wave",
            {
                key: tuple(sorted(entries, key=lambda item: (item.position, item.entry_id)))
                for key, entries in wave_entries_by_definition_wave.items()
            },
        )
        object.__setattr__(self, "_effects", {effect.effect_id: effect for effect in self.ir.effects})
        object.__setattr__(self, "_conditions", {condition.condition_id: condition for condition in self.ir.conditions})
        object.__setattr__(self, "_triggers", {trigger.trigger_id: trigger for trigger in self.ir.triggers})
        object.__setattr__(self, "_formulas", {formula.formula_id: formula for formula in self.ir.formulas})
        triggers_by_modifier: dict[str, list[TriggerIR]] = {}
        triggers_by_modifier_event: dict[tuple[str, str], list[TriggerIR]] = {}
        for trigger in self.ir.triggers:
            modifier_name = trigger.source.raw_id
            triggers_by_modifier.setdefault(modifier_name, []).append(trigger)
            triggers_by_modifier_event.setdefault((modifier_name, trigger.event), []).append(trigger)
        object.__setattr__(
            self,
            "_triggers_by_modifier",
            {key: tuple(value) for key, value in triggers_by_modifier.items()},
        )
        object.__setattr__(
            self,
            "_triggers_by_modifier_event",
            {key: tuple(value) for key, value in triggers_by_modifier_event.items()},
        )

    def entity(self, entity_id: str) -> RuleEntity | None:
        return self._entities.get(entity_id)

    def require_entity(self, entity_id: str, expected_types: set[str] | tuple[str, ...] | None = None) -> RuleEntity:
        entity = self.entity(entity_id)
        if entity is None:
            raise KeyError(f"unknown rule entity {entity_id!r}")
        if expected_types is not None and entity.entity_type not in set(expected_types):
            raise TypeError(
                f"rule entity {entity_id!r} has type {entity.entity_type!r}, "
                f"expected one of {sorted(set(expected_types))}"
            )
        return entity

    def entities_by_type(self, entity_type: str) -> tuple[RuleEntity, ...]:
        return tuple(entity for entity in self.ir.entities if entity.entity_type == entity_type)

    def is_entity_type(self, entity_id: str, expected_types: set[str] | tuple[str, ...]) -> bool:
        entity = self.entity(entity_id)
        return bool(entity and entity.entity_type in set(expected_types))

    def source_trace(self, entity_id: str) -> dict[str, object] | None:
        entity = self.entity(entity_id)
        if not entity:
            return None
        return {
            "entity_id": entity.entity_id,
            "entity_type": entity.entity_type,
            "coverage_status": entity.coverage_status,
            "source": entity.source.to_json(),
        }

    def combatant_profile(self, entity_id: str) -> CombatantProfileIR | None:
        return self._combatant_profiles.get(entity_id)

    def avatar_profile(self, avatar_id: str) -> AvatarProfileIR | None:
        return self._avatar_profiles.get(avatar_id)

    def character_data_card(self, card_id: str) -> CharacterDataCardIR | None:
        return self._character_data_cards.get(card_id)

    def character_data_card_for_entity(self, entity_ref: str) -> CharacterDataCardIR | None:
        return self._character_data_cards_by_entity_ref.get(entity_ref)

    def monster_data_card(self, card_id: str) -> MonsterDataCardIR | None:
        return self._monster_data_cards.get(card_id)

    def monster_data_card_for_entity(self, entity_ref: str) -> MonsterDataCardIR | None:
        return self._monster_data_cards_by_entity_ref.get(entity_ref)

    def character_mechanism_slot(self, mechanism_slot_id: str) -> CharacterMechanismSlotIR | None:
        return self._character_mechanism_slots.get(mechanism_slot_id)

    def character_mechanism_slots_for_card(self, card_id: str) -> tuple[CharacterMechanismSlotIR, ...]:
        return self._character_mechanism_slots_by_card.get(card_id, ())

    def passive_mechanism_slot(self, passive_slot_id: str) -> PassiveMechanismSlotIR | None:
        return self._passive_mechanism_slots.get(passive_slot_id)

    def passive_mechanism_slots_for_card(self, data_card_id: str) -> tuple[PassiveMechanismSlotIR, ...]:
        return self._passive_mechanism_slots_by_card.get(data_card_id, ())

    def passive_mechanism_slots_for_owner(self, owner_entity_ref: str) -> tuple[PassiveMechanismSlotIR, ...]:
        return self._passive_mechanism_slots_by_owner.get(owner_entity_ref, ())

    def character_trace_node(self, trace_node_id: str) -> CharacterTraceNodeIR | None:
        return self._character_trace_nodes.get(trace_node_id)

    def character_trace_nodes_for_card(self, card_id: str) -> tuple[CharacterTraceNodeIR, ...]:
        return self._character_trace_nodes_by_card.get(card_id, ())

    def character_eidolon_slot(self, eidolon_slot_id: str) -> CharacterEidolonSlotIR | None:
        return self._character_eidolon_slots.get(eidolon_slot_id)

    def character_eidolon_slots_for_card(self, card_id: str) -> tuple[CharacterEidolonSlotIR, ...]:
        return self._character_eidolon_slots_by_card.get(card_id, ())

    def character_eidolon_slots_for_level(self, card_id: str, eidolon_level: int) -> tuple[CharacterEidolonSlotIR, ...]:
        if eidolon_level < 0 or eidolon_level > 6:
            raise ValueError(f"eidolon_level must be between 0 and 6, got {eidolon_level!r}")
        return tuple(slot for slot in self.character_eidolon_slots_for_card(card_id) if slot.rank <= eidolon_level)

    def require_combatant_profile(self, entity_id: str) -> CombatantProfileIR:
        profile = self.combatant_profile(entity_id)
        if profile is None:
            raise KeyError(f"unknown combatant profile {entity_id!r}")
        return profile

    def effect(self, effect_id: str) -> EffectIR | None:
        return self._effects.get(effect_id)

    def condition(self, condition_id: str) -> ConditionIR | None:
        return self._conditions.get(condition_id)

    def trigger(self, trigger_id: str) -> TriggerIR | None:
        return self._triggers.get(trigger_id)

    def formula(self, formula_id: str) -> FormulaIR | None:
        return self._formulas.get(formula_id)

    def target_expression(self, target_expression_id: str) -> TargetExpressionIR | None:
        return self._target_expressions.get(target_expression_id)

    def target_expressions(self) -> tuple[TargetExpressionIR, ...]:
        return self.ir.target_expressions

    def wave_definition(self, wave_definition_id: str) -> WaveDefinitionIR | None:
        return self._wave_definitions.get(wave_definition_id)

    def wave_definitions(self) -> tuple[WaveDefinitionIR, ...]:
        return tuple(sorted(self.ir.wave_definitions, key=lambda item: item.wave_definition_id))

    def wave_definition_for_stage(self, stage_id: str) -> WaveDefinitionIR | None:
        definitions = self._wave_definitions_by_stage.get(stage_id, ())
        return definitions[0] if definitions else None

    def wave_entries_for_wave(self, wave_definition_id: str, wave_index: int) -> tuple[WaveMonsterEntryIR, ...]:
        return self._wave_entries_by_definition_wave.get((wave_definition_id, int(wave_index)), ())

    def has_action(self, action_id: str) -> bool:
        entity = self._entities.get(action_id)
        return bool(entity and entity.entity_type in {"avatar_skill", "monster_skill", "active_skill"})

    def action_definition(self, action_id: str, level: int) -> ActionDefinitionIR | None:
        return self._action_definitions.get((action_id, level))

    def require_action_definition(self, action_id: str, level: int) -> ActionDefinitionIR:
        definition = self.action_definition(action_id, level)
        if definition is None:
            levels = self.action_levels(action_id)
            if levels:
                raise KeyError(f"unknown action definition {action_id!r} level {level}; known levels: {list(levels)}")
            raise KeyError(f"unknown action definition {action_id!r} level {level}")
        return definition

    def action_levels(self, action_id: str) -> tuple[int, ...]:
        return tuple(
            sorted(definition.level for definition in self.ir.action_definitions if definition.action_id == action_id)
        )

    def action_definition_source_trace(self, action_id: str, level: int) -> dict[str, object] | None:
        definition = self.action_definition(action_id, level)
        if not definition:
            return None
        return {
            "definition_id": definition.definition_id,
            "action_id": definition.action_id,
            "level": definition.level,
            "coverage_status": definition.coverage_status,
            "source": definition.source.to_json(),
        }

    def action_event(self, action_id: str, level: int) -> ActionEventIR | None:
        return self._action_events.get((action_id, level))

    def require_action_event(self, action_id: str, level: int) -> ActionEventIR:
        event = self.action_event(action_id, level)
        if event is None:
            raise KeyError(f"unknown action event {action_id!r} level {level}")
        return event

    def hit_profiles_for_action(self, action_id: str, level: int) -> tuple[HitProfileIR, ...]:
        return self._hit_profiles_by_action.get((action_id, level), ())

    def hit_profile(self, hit_profile_id: str) -> HitProfileIR | None:
        return self._hit_profiles.get(hit_profile_id)

    def bounce_policy(self, bounce_policy_id: str) -> BouncePolicyIR | None:
        return self._bounce_policies.get(bounce_policy_id)

    def bounce_policies_for_action(self, action_id: str, level: int) -> tuple[BouncePolicyIR, ...]:
        return self._bounce_policies_by_action.get((action_id, level), ())

    def skill_formula_binding(self, binding_id: str) -> SkillFormulaBindingIR | None:
        return self._skill_formula_bindings.get(binding_id)

    def skill_formula_bindings_for_action_param(
        self,
        action_id: str,
        level: int,
        param_index: int,
        formula_role: str,
    ) -> tuple[SkillFormulaBindingIR, ...]:
        return self._skill_formula_bindings_by_action_param_role.get(
            (action_id, level, param_index, formula_role),
            (),
        )

    def damage_emission(self, damage_emission_id: str) -> DamageEmissionIR | None:
        return self._damage_emissions.get(damage_emission_id)

    def damage_emissions_for_action(self, action_id: str, level: int) -> tuple[DamageEmissionIR, ...]:
        return self._damage_emissions_by_action.get((action_id, level), ())

    def damage_emissions_for_task(self, task_id: str) -> tuple[DamageEmissionIR, ...]:
        return self._damage_emissions_by_task.get(task_id, ())

    def toughness_emission(self, toughness_emission_id: str) -> ToughnessEmissionIR | None:
        return self._toughness_emissions.get(toughness_emission_id)

    def toughness_emissions_for_action(self, action_id: str, level: int) -> tuple[ToughnessEmissionIR, ...]:
        return self._toughness_emissions_by_action.get((action_id, level), ())

    def toughness_emissions_for_task(self, task_id: str) -> tuple[ToughnessEmissionIR, ...]:
        return self._toughness_emissions_by_task.get(task_id, ())

    def break_template(self, template_id: str) -> BreakTemplateIR | None:
        return self._break_templates.get(template_id)

    def break_templates(self) -> tuple[BreakTemplateIR, ...]:
        return self.ir.break_templates

    def break_template_for_element(self, element_type: str | None) -> BreakTemplateIR | None:
        if not element_type:
            return None
        return self._break_templates_by_element.get(str(element_type))

    def break_damage_emission(self, emission_id: str) -> BreakDamageEmissionIR | None:
        return self._break_damage_emissions.get(emission_id)

    def break_base_damage(self, level: int) -> BreakBaseDamageIR | None:
        return self._break_base_damage_by_level.get(level)

    def break_base_damage_rows(self) -> tuple[BreakBaseDamageIR, ...]:
        return self.ir.break_base_damage

    def break_damage_emissions(self) -> tuple[BreakDamageEmissionIR, ...]:
        return self.ir.break_damage_emissions

    def break_damage_emissions_for_template(self, template_id: str) -> tuple[BreakDamageEmissionIR, ...]:
        return self._break_damage_emissions_by_template.get(template_id, ())

    def break_status_emission(self, emission_id: str) -> BreakStatusEmissionIR | None:
        return self._break_status_emissions.get(emission_id)

    def break_status_emissions(self) -> tuple[BreakStatusEmissionIR, ...]:
        return self.ir.break_status_emissions

    def break_status_emissions_for_template(self, template_id: str) -> tuple[BreakStatusEmissionIR, ...]:
        return self._break_status_emissions_by_template.get(template_id, ())

    def status_event_family(self, callback_event: str) -> StatusEventFamilyIR | None:
        return self._status_event_families.get(callback_event)

    def status_event_families(self) -> tuple[StatusEventFamilyIR, ...]:
        return self.ir.status_event_families

    def status_event_families_for_runtime_event(self, runtime_event: str) -> tuple[StatusEventFamilyIR, ...]:
        return self._status_event_families_by_runtime_event.get(runtime_event, ())

    def status_callback(self, callback_id: str) -> StatusCallbackIR | None:
        return self._status_callbacks.get(callback_id)

    def status_callbacks_for_modifier_event(self, modifier_name: str, event: str) -> tuple[StatusCallbackIR, ...]:
        return self._status_callbacks_by_modifier_event.get((modifier_name, event), ())

    def status_callbacks_for_event(self, event: str) -> tuple[StatusCallbackIR, ...]:
        return self._status_callbacks_by_event.get(event, ())

    def status_callbacks_for_event_scope(self, event: str, scope_kind: str) -> tuple[StatusCallbackIR, ...]:
        return self._status_callbacks_by_event_scope.get((event, scope_kind), ())

    def status_callbacks_for_modifier_event_scope(
        self,
        modifier_name: str,
        event: str,
        scope_kind: str,
    ) -> tuple[StatusCallbackIR, ...]:
        return self._status_callbacks_by_modifier_event_scope.get((modifier_name, event, scope_kind), ())

    def status_callback_task(self, task_id: str) -> StatusCallbackTaskIR | None:
        return self._status_callback_tasks.get(task_id)

    def status_callback_tasks_for_callback(self, callback_id: str) -> tuple[StatusCallbackTaskIR, ...]:
        return self._status_callback_tasks_by_callback.get(callback_id, ())

    def status_damage_emission(self, emission_id: str) -> StatusDamageEmissionIR | None:
        return self._status_damage_emissions.get(emission_id)

    def status_damage_emissions_for_callback(self, callback_id: str) -> tuple[StatusDamageEmissionIR, ...]:
        return self._status_damage_emissions_by_callback.get(callback_id, ())

    def damage_modifier(self, damage_modifier_id: str) -> DamageModifierIR | None:
        return self._damage_modifiers.get(damage_modifier_id)

    def damage_modifiers_for_callback(self, callback_id: str) -> tuple[DamageModifierIR, ...]:
        return self._damage_modifiers_by_callback.get(callback_id, ())

    def action_delay_emission(self, emission_id: str) -> ActionDelayEmissionIR | None:
        return self._action_delay_emissions.get(emission_id)

    def action_delay_emissions_for_callback(self, callback_id: str) -> tuple[ActionDelayEmissionIR, ...]:
        return self._action_delay_emissions_by_callback.get(callback_id, ())

    def queue_intent(self, queue_intent_id: str) -> QueueIntentIR | None:
        return self._queue_intents.get(queue_intent_id)

    def queue_intents_for_callback(self, callback_id: str) -> tuple[QueueIntentIR, ...]:
        return self._queue_intents_by_callback.get(callback_id, ())

    def queue_resolution(self, queue_resolution_id: str) -> QueueResolutionIR | None:
        return self._queue_resolutions.get(queue_resolution_id)

    def queue_resolution_for_intent(self, queue_intent_id: str) -> QueueResolutionIR | None:
        return self._queue_resolution_by_intent.get(queue_intent_id)

    def queue_priority(self, queue_priority_id: str) -> QueuePriorityIR | None:
        return self._queue_priorities.get(queue_priority_id)

    def queue_priority_by_key(self, priority_table: str, priority_key: str) -> QueuePriorityIR | None:
        return self._queue_priority_by_table_key.get((priority_table, priority_key))

    def queue_window(self, queue_window_id: str) -> QueueWindowIR | None:
        return self._queue_windows.get(queue_window_id)

    def queue_window_for_intent(self, queue_intent_id: str) -> QueueWindowIR | None:
        return self._queue_window_by_intent.get(queue_intent_id)

    def queue_lifecycle_policy(self, policy_id: str) -> QueueLifecyclePolicyIR | None:
        return self._queue_lifecycle_policies.get(policy_id)

    def queue_lifecycle_policy_for_window(self, queue_window_id: str) -> QueueLifecyclePolicyIR | None:
        return self._queue_lifecycle_policy_by_window.get(queue_window_id)

    def queue_lifecycle_policy_for_intent(self, queue_intent_id: str) -> QueueLifecyclePolicyIR | None:
        return self._queue_lifecycle_policy_by_intent.get(queue_intent_id)

    def extra_action_policy(self, policy_id: str) -> ExtraActionPolicyIR | None:
        return self._extra_action_policies.get(policy_id)

    def extra_action_policy_for_window(self, queue_window_id: str) -> ExtraActionPolicyIR | None:
        return self._extra_action_policy_by_window.get(queue_window_id)

    def extra_action_policy_for_intent(self, queue_intent_id: str) -> ExtraActionPolicyIR | None:
        return self._extra_action_policy_by_intent.get(queue_intent_id)

    def skill_continuation(self, continuation_id: str) -> SkillContinuationIR | None:
        return self._skill_continuations.get(continuation_id)

    def skill_continuations(self) -> tuple[SkillContinuationIR, ...]:
        return tuple(sorted(self.ir.skill_continuations, key=lambda item: item.continuation_id))

    def standalone_ability_graph(self, graph_id: str) -> StandaloneAbilityGraphIR | None:
        return self._standalone_ability_graphs.get(graph_id)

    def standalone_ability_graphs_by_name(self, ability_name: str) -> tuple[StandaloneAbilityGraphIR, ...]:
        return self._standalone_ability_graphs_by_name.get(ability_name, ())

    def combatant_action_set(self, entity_ref: str) -> CombatantActionSetIR | None:
        return self._combatant_action_sets.get(entity_ref)

    def timeline_rule(self, timeline_rule_id: str) -> TimelineRuleIR | None:
        return self._timeline_rules.get(timeline_rule_id)

    def default_timeline_rule(self) -> TimelineRuleIR:
        rules = sorted(self.ir.timeline_rules, key=lambda item: item.timeline_rule_id)
        if not rules:
            raise KeyError("missing timeline rule")
        return rules[0]

    def resource_rule(self, resource_rule_id: str) -> ResourceRuleIR | None:
        return self._resource_rules.get(resource_rule_id)

    def resource_rules_by_kind(self, rule_kind: str) -> tuple[ResourceRuleIR, ...]:
        return tuple(
            sorted(
                (rule for rule in self.ir.resource_rules if rule.rule_kind == rule_kind),
                key=lambda item: item.resource_rule_id,
            )
        )

    def default_ultimate_energy_cost_rule(self) -> ResourceRuleIR:
        rules = self.resource_rules_by_kind("ultimate_energy_cost")
        if not rules:
            raise KeyError("missing ultimate energy cost resource rule")
        return rules[0]

    def default_kill_energy_gain_rule(self) -> ResourceRuleIR:
        rules = self.resource_rules_by_kind("kill_energy_gain")
        if not rules:
            raise KeyError("missing kill energy gain resource rule")
        return rules[0]

    def super_break_emission(self, emission_id: str) -> SuperBreakEmissionIR | None:
        return self._super_break_emissions.get(emission_id)

    def super_break_emissions(self) -> tuple[SuperBreakEmissionIR, ...]:
        return self.ir.super_break_emissions

    def super_break_emissions_for_template(self, template_id: str) -> tuple[SuperBreakEmissionIR, ...]:
        return self._super_break_emissions_by_template.get(template_id, ())

    def action_ability_binding(self, action_id: str, level: int) -> ActionAbilityBindingIR | None:
        return self._action_ability_bindings.get((action_id, level))

    def ability_phases_for_action(self, action_id: str, level: int) -> tuple[AbilityPhaseIR, ...]:
        return self._ability_phases_by_action.get((action_id, level), ())

    def ability_phases_for_binding(self, binding_id: str) -> tuple[AbilityPhaseIR, ...]:
        return self._ability_phases_by_binding.get(binding_id, ())

    def ability_phase(self, phase_id: str) -> AbilityPhaseIR | None:
        return self._ability_phases.get(phase_id)

    def ability_task(self, task_id: str) -> AbilityTaskIR | None:
        return self._ability_tasks.get(task_id)

    def ability_tasks_for_phase(self, phase_id: str) -> tuple[AbilityTaskIR, ...]:
        return self._ability_tasks_by_phase.get(phase_id, ())

    def ability_tasks_for_action(self, action_id: str, level: int) -> tuple[AbilityTaskIR, ...]:
        return self._ability_tasks_by_action.get((action_id, level), ())

    def triggers_for_event(self, event: str) -> tuple[TriggerIR, ...]:
        return tuple(trigger for trigger in self.ir.triggers if trigger.event == event)

    def triggers_for_modifier(self, modifier_name: str) -> tuple[TriggerIR, ...]:
        return self._triggers_by_modifier.get(modifier_name, ())

    def triggers_for_modifier_event(self, modifier_name: str, event: str) -> tuple[TriggerIR, ...]:
        return self._triggers_by_modifier_event.get((modifier_name, event), ())

    def modifier_definitions(self, modifier_name: str) -> tuple[RuleEntity, ...]:
        return self._modifier_definitions_by_name.get(modifier_name, ())

    def modifier_definition(self, modifier_name: str) -> RuleEntity | None:
        definitions = self.modifier_definitions(modifier_name)
        if definitions:
            return definitions[0]
        return self.entity(f"modifier_definition:{modifier_name}")

    def require_modifier_definition(self, modifier_name: str) -> RuleEntity:
        return self.require_entity(f"modifier_definition:{modifier_name}", {"modifier_definition"})

    def status_entities_for_modifier(self, modifier_name: str) -> tuple[RuleEntity, ...]:
        return self._status_entities_by_modifier.get(modifier_name, ())

    def status_entity_for_modifier(self, modifier_name: str) -> RuleEntity | None:
        entities = self.status_entities_for_modifier(modifier_name)
        if entities:
            return entities[0]
        return None
