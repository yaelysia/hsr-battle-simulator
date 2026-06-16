from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
CoverageStatus = Literal[
    "discovered_only",
    "lowered",
    "executable",
    "validated",
    "blocked",
    "supported_alias",
    "audit_only",
    "unsupported",
    "skipped_with_reason",
]


@dataclass(frozen=True)
class IRSource:
    source_path: str
    raw_type: str
    raw_id: str
    evidence: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "source_path": self.source_path,
            "raw_type": self.raw_type,
            "raw_id": self.raw_id,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class FormulaIR:
    formula_id: str
    kind: str
    expression: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "audit_only"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "formula_id": self.formula_id,
            "kind": self.kind,
            "expression": self.expression,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
        }


@dataclass(frozen=True)
class ConditionIR:
    condition_id: str
    opcode: str
    payload: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "unsupported"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "condition_id": self.condition_id,
            "opcode": self.opcode,
            "payload": self.payload,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
        }


@dataclass(frozen=True)
class EffectIR:
    effect_id: str
    opcode: str
    payload: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "unsupported"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "effect_id": self.effect_id,
            "opcode": self.opcode,
            "payload": self.payload,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
        }


@dataclass(frozen=True)
class TriggerIR:
    trigger_id: str
    event: str
    conditions: tuple[str, ...]
    effects: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "audit_only"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "trigger_id": self.trigger_id,
            "event": self.event,
            "conditions": list(self.conditions),
            "effects": list(self.effects),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
        }


@dataclass(frozen=True)
class RuleEntity:
    entity_id: str
    entity_type: str
    fields: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "audit_only"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "fields": self.fields,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
        }


@dataclass(frozen=True)
class ActionDefinitionIR:
    definition_id: str
    action_id: str
    level: int
    attack_type: str
    skill_effect: str
    target_mode: str
    bp_need: float
    bp_add: float
    sp_base: float
    sp_multiple_ratio: float
    param_list: tuple[JSONValue, ...]
    show_stance_list: tuple[JSONValue, ...]
    show_damage_list: tuple[JSONValue, ...]
    stance_damage_type: str | None
    source: IRSource
    coverage_status: CoverageStatus = "audit_only"
    damage_kind: str = "unknown"
    damage_formula_family: str = "unknown"
    element_type: str | None = None
    source_mode: str = "mainline"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "definition_id": self.definition_id,
            "action_id": self.action_id,
            "level": self.level,
            "attack_type": self.attack_type,
            "skill_effect": self.skill_effect,
            "target_mode": self.target_mode,
            "bp_need": self.bp_need,
            "bp_add": self.bp_add,
            "sp_base": self.sp_base,
            "sp_multiple_ratio": self.sp_multiple_ratio,
            "param_list": list(self.param_list),
            "show_stance_list": list(self.show_stance_list),
            "show_damage_list": list(self.show_damage_list),
            "stance_damage_type": self.stance_damage_type,
            "damage_kind": self.damage_kind,
            "damage_formula_family": self.damage_formula_family,
            "element_type": self.element_type,
            "source_mode": self.source_mode,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
        }


@dataclass(frozen=True)
class CanonicalIR:
    version: str
    entities: tuple[RuleEntity, ...] = ()
    action_definitions: tuple[ActionDefinitionIR, ...] = ()
    triggers: tuple[TriggerIR, ...] = ()
    effects: tuple[EffectIR, ...] = ()
    conditions: tuple[ConditionIR, ...] = ()
    formulas: tuple[FormulaIR, ...] = ()
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "version": self.version,
            "metadata": self.metadata,
            "entities": [entity.to_json() for entity in self.entities],
            "action_definitions": [definition.to_json() for definition in self.action_definitions],
            "triggers": [trigger.to_json() for trigger in self.triggers],
            "effects": [effect.to_json() for effect in self.effects],
            "conditions": [condition.to_json() for condition in self.conditions],
            "formulas": [formula.to_json() for formula in self.formulas],
        }
