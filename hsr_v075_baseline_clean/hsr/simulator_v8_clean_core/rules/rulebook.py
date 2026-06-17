from __future__ import annotations

from dataclasses import dataclass

from .ir import (
    ActionDefinitionIR,
    ActionEventIR,
    CanonicalIR,
    ConditionIR,
    EffectIR,
    FormulaIR,
    HitProfileIR,
    RuleEntity,
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
            "_action_definitions",
            {(definition.action_id, definition.level): definition for definition in self.ir.action_definitions},
        )
        object.__setattr__(
            self,
            "_action_events",
            {(event.action_id, event.level): event for event in self.ir.action_events},
        )
        hit_profiles_by_action: dict[tuple[str, int], list[HitProfileIR]] = {}
        for profile in self.ir.hit_profiles:
            hit_profiles_by_action.setdefault((profile.action_id, profile.level), []).append(profile)
        object.__setattr__(
            self,
            "_hit_profiles_by_action",
            {
                key: tuple(sorted(value, key=lambda item: (item.hit_index, item.target_group, item.hit_profile_id)))
                for key, value in hit_profiles_by_action.items()
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
