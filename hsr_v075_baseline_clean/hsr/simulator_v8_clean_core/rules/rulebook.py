from __future__ import annotations

from dataclasses import dataclass

from .ir import (
    AbilityPhaseIR,
    AbilityTaskIR,
    ActionAbilityBindingIR,
    ActionDefinitionIR,
    ActionDelayEmissionIR,
    ActionEventIR,
    BreakBaseDamageIR,
    BreakDamageEmissionIR,
    BreakStatusEmissionIR,
    BreakTemplateIR,
    CanonicalIR,
    CombatantProfileIR,
    ConditionIR,
    DamageEmissionIR,
    EffectIR,
    FormulaIR,
    HitProfileIR,
    QueueIntentIR,
    RuleEntity,
    StatusCallbackIR,
    StatusCallbackTaskIR,
    StatusDamageEmissionIR,
    SuperBreakEmissionIR,
    ToughnessEmissionIR,
    TriggerIR,
)


@dataclass(frozen=True)
class RuleBook:
    """Read-only view over Canonical IR."""

    ir: CanonicalIR

    def __post_init__(self) -> None:
        object.__setattr__(self, "_entities", {entity.entity_id: entity for entity in self.ir.entities})
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

    def action_delay_emission(self, emission_id: str) -> ActionDelayEmissionIR | None:
        return self._action_delay_emissions.get(emission_id)

    def action_delay_emissions_for_callback(self, callback_id: str) -> tuple[ActionDelayEmissionIR, ...]:
        return self._action_delay_emissions_by_callback.get(callback_id, ())

    def queue_intent(self, queue_intent_id: str) -> QueueIntentIR | None:
        return self._queue_intents.get(queue_intent_id)

    def queue_intents_for_callback(self, callback_id: str) -> tuple[QueueIntentIR, ...]:
        return self._queue_intents_by_callback.get(callback_id, ())

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

    def modifier_definition(self, modifier_name: str) -> RuleEntity | None:
        return self.entity(f"modifier_definition:{modifier_name}")

    def require_modifier_definition(self, modifier_name: str) -> RuleEntity:
        return self.require_entity(f"modifier_definition:{modifier_name}", {"modifier_definition"})
