from __future__ import annotations

from dataclasses import dataclass

from .ir import CanonicalIR, ConditionIR, EffectIR, FormulaIR, RuleEntity, TriggerIR


@dataclass(frozen=True)
class RuleBook:
    """Read-only view over Canonical IR."""

    ir: CanonicalIR

    def __post_init__(self) -> None:
        object.__setattr__(self, "_entities", {entity.entity_id: entity for entity in self.ir.entities})
        object.__setattr__(self, "_effects", {effect.effect_id: effect for effect in self.ir.effects})
        object.__setattr__(self, "_conditions", {condition.condition_id: condition for condition in self.ir.conditions})
        object.__setattr__(self, "_triggers", {trigger.trigger_id: trigger for trigger in self.ir.triggers})
        object.__setattr__(self, "_formulas", {formula.formula_id: formula for formula in self.ir.formulas})

    def entity(self, entity_id: str) -> RuleEntity | None:
        return self._entities.get(entity_id)

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

    def triggers_for_event(self, event: str) -> tuple[TriggerIR, ...]:
        return tuple(trigger for trigger in self.ir.triggers if trigger.event == event)

