from __future__ import annotations

from .schema import ScenarioSpec, ScenarioValidationResult
from ..rules.rulebook import RuleBook


ALLY_ENTITY_TYPES = {"avatar"}
ENEMY_ENTITY_TYPES = {"monster", "monster_template"}
SUMMON_ENTITY_TYPES = {"summon_unit"}
ACTION_ENTITY_TYPES = {"avatar_skill", "monster_skill", "active_skill"}


class IdentityResolver:
    def __init__(self, rules: RuleBook):
        self.rules = rules

    def validate(self, scenario: ScenarioSpec) -> ScenarioValidationResult:
        errors: list[str] = []
        traces: list[dict[str, object]] = []
        unit_ids = {unit.unit_id for unit in scenario.units}
        if len(unit_ids) != len(scenario.units):
            errors.append("unit_id values must be unique")

        for unit in scenario.units:
            expected_types = _expected_unit_types(unit.side)
            entity = self.rules.entity(unit.entity_ref)
            if entity is None:
                errors.append(f"unit {unit.unit_id}: unknown entity_ref {unit.entity_ref!r}")
                continue
            if entity.entity_type not in expected_types:
                errors.append(
                    f"unit {unit.unit_id}: entity_ref {unit.entity_ref!r} has type "
                    f"{entity.entity_type!r}, expected one of {sorted(expected_types)}"
                )
            trace = self.rules.source_trace(unit.entity_ref)
            if trace:
                traces.append(trace)

        for index, step in enumerate(scenario.route):
            if step.actor_id not in unit_ids:
                errors.append(f"route[{index}]: unknown actor_id {step.actor_id!r}")
            for target_id in step.target_ids:
                if target_id not in unit_ids:
                    errors.append(f"route[{index}]: unknown target_id {target_id!r}")
            action = self.rules.entity(step.action_ref)
            if action is None:
                errors.append(f"route[{index}]: unknown action_ref {step.action_ref!r}")
                continue
            if action.entity_type not in ACTION_ENTITY_TYPES:
                errors.append(
                    f"route[{index}]: action_ref {step.action_ref!r} has type "
                    f"{action.entity_type!r}, expected one of {sorted(ACTION_ENTITY_TYPES)}"
                )
            definition = self.rules.action_definition(step.action_ref, step.action_level)
            if definition is None:
                errors.append(
                    f"route[{index}]: unknown action definition {step.action_ref!r} "
                    f"level {step.action_level}; known levels: {list(self.rules.action_levels(step.action_ref))}"
                )
            trace = self.rules.source_trace(step.action_ref)
            if trace:
                traces.append(trace)
            definition_trace = self.rules.action_definition_source_trace(step.action_ref, step.action_level)
            if definition_trace:
                traces.append(definition_trace)

        return ScenarioValidationResult(ok=not errors, errors=tuple(errors), source_traces=tuple(traces))


def _expected_unit_types(side: str) -> set[str]:
    if side == "ally":
        return set(ALLY_ENTITY_TYPES)
    if side == "enemy":
        return set(ENEMY_ENTITY_TYPES)
    if side == "summon":
        return set(SUMMON_ENTITY_TYPES)
    return set()
