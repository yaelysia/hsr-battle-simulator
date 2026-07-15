from __future__ import annotations

from collections.abc import Mapping

from .schema import ScenarioSpec, ScenarioValidationResult
from ..builds.character_assembler import assemble_character_build
from ..rules.rulebook import RuleBook


ALLY_ENTITY_TYPES = {"avatar"}
ENEMY_ENTITY_TYPES = {"monster", "monster_template"}
SUMMON_ENTITY_TYPES = {"summon_unit"}
ACTION_ENTITY_TYPES = {"avatar_skill", "monster_skill", "active_skill", "servant_skill"}


class IdentityResolver:
    def __init__(self, rules: RuleBook):
        self.rules = rules

    def validate(self, scenario: ScenarioSpec) -> ScenarioValidationResult:
        errors: list[str] = []
        traces: list[dict[str, object]] = []
        formal_action_ids_by_unit: dict[str, set[str]] = {}
        formal_skill_levels_by_unit: dict[str, dict[str, int]] = {}
        unit_ids = {unit.unit_id for unit in scenario.units}
        units_by_id = {unit.unit_id: unit for unit in scenario.units}
        if len(unit_ids) != len(scenario.units):
            errors.append("unit_id values must be unique")

        for unit in scenario.units:
            if unit.build_mode == "assembled_character_build":
                if unit.side != "ally":
                    errors.append(f"unit {unit.unit_id}: formal character build mode requires ally side")
                if unit.panel is not None:
                    errors.append(f"unit {unit.unit_id}: formal character build requires panel=None")
                if unit.character_build is None:
                    errors.append(f"unit {unit.unit_id}: formal character_build is missing")
                if unit.initial_condition is None:
                    errors.append(f"unit {unit.unit_id}: formal initial_condition is missing")
                if unit.character_build is not None:
                    build = unit.character_build
                    card = self.rules.character_data_card(build.character_card_id)
                    if card is None:
                        errors.append(
                            f"unit {unit.unit_id}: unknown character card {build.character_card_id!r}"
                        )
                    elif card.entity_ref != unit.entity_ref:
                        errors.append(
                            f"unit {unit.unit_id}: entity_ref {unit.entity_ref!r} does not match "
                            f"character card entity_ref {card.entity_ref!r}"
                        )
                    if card is not None:
                        raw_actions = card.action_set.get("actions")
                        formal_action_ids_by_unit[unit.unit_id] = {
                            str(action.get("action_id"))
                            for action in raw_actions
                            if isinstance(action, Mapping) and action.get("action_id")
                        } if isinstance(raw_actions, (list, tuple)) else set()
                        assembly = assemble_character_build(self.rules, build)
                        if assembly.assembly_status == "assembled":
                            formal_skill_levels_by_unit[unit.unit_id] = {
                                item.action_id: item.effective_level
                                for item in assembly.effective_skill_levels
                            }
                    if build.level != unit.level:
                        errors.append(f"unit {unit.unit_id}: outer level does not match character build")
                    if build.eidolon_level != unit.eidolon_level:
                        errors.append(
                            f"unit {unit.unit_id}: outer eidolon_level does not match character build"
                        )
                    if build.equipment_build.character_card_id != build.character_card_id:
                        errors.append(
                            f"unit {unit.unit_id}: embedded equipment build character identity mismatch"
                        )
                    if build.equipment_build.light_cone is not None or build.equipment_build.relics:
                        errors.append(f"unit {unit.unit_id}: P8-S2 formal equipment build must be empty")
            elif unit.build_mode == "kernel_fixture":
                if unit.panel is None:
                    errors.append(f"unit {unit.unit_id}: kernel_fixture requires panel input")
                if unit.character_build is not None or unit.initial_condition is not None:
                    errors.append(f"unit {unit.unit_id}: kernel_fixture cannot carry formal build fields")
                if unit.panel is not None:
                    enabled = unit.panel.flags.get("enabled_trace_node_ids")
                    disabled = unit.panel.flags.get("disabled_trace_node_ids")
                    for field_name, raw_ids in (
                        ("enabled_trace_node_ids", enabled),
                        ("disabled_trace_node_ids", disabled),
                    ):
                        if raw_ids is not None and (
                            not isinstance(raw_ids, (list, tuple))
                            or not all(isinstance(item, str) and item for item in raw_ids)
                        ):
                            errors.append(
                                f"unit {unit.unit_id}: panel.flags.{field_name} must be a string sequence"
                            )
                        elif isinstance(raw_ids, (list, tuple)) and len(set(raw_ids)) != len(raw_ids):
                            errors.append(
                                f"unit {unit.unit_id}: panel.flags.{field_name} contains duplicates"
                            )
                    enabled_ids = set(enabled) if isinstance(enabled, (list, tuple)) else set()
                    disabled_ids = set(disabled) if isinstance(disabled, (list, tuple)) else set()
                    overlap = sorted(enabled_ids.intersection(disabled_ids))
                    if overlap:
                        errors.append(
                            f"unit {unit.unit_id}: trace nodes cannot be enabled and disabled together: {overlap}"
                        )
                    card = self.rules.character_data_card_for_entity(unit.entity_ref)
                    if card is not None:
                        selected_nodes = [
                            self.rules.character_trace_node(node_id)
                            for node_id in sorted(enabled_ids.union(disabled_ids))
                        ]
                        if any(
                            node is None or node.character_data_card_id != card.card_id
                            for node in selected_nodes
                        ):
                            errors.append(
                                f"unit {unit.unit_id}: kernel trace flags contain unknown or cross-character nodes"
                            )
                        enabled_nodes = [
                            node
                            for node_id in enabled_ids
                            if (node := self.rules.character_trace_node(node_id)) is not None
                            and node.character_data_card_id == card.card_id
                        ]
                        if len({node.trace_id for node in enabled_nodes}) != len(enabled_nodes):
                            errors.append(
                                f"unit {unit.unit_id}: kernel trace flags select conflicting levels"
                            )
            else:
                errors.append(f"unit {unit.unit_id}: unsupported build_mode {unit.build_mode!r}")
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

        setup = scenario.battle_setup
        route_may_reference_setup_units = bool(setup.initial_summons)
        for index, step in enumerate(scenario.route):
            if step.actor_id not in unit_ids and not route_may_reference_setup_units:
                errors.append(f"route[{index}]: unknown actor_id {step.actor_id!r}")
            for target_id in step.target_ids:
                if target_id not in unit_ids and not route_may_reference_setup_units:
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
            actor = units_by_id.get(step.actor_id)
            if actor is not None and actor.build_mode == "assembled_character_build":
                owned_actions = formal_action_ids_by_unit.get(step.actor_id, set())
                effective_levels = formal_skill_levels_by_unit.get(step.actor_id, {})
                if step.action_ref not in owned_actions:
                    errors.append(
                        f"route[{index}]: formal character action {step.action_ref!r} "
                        "is not owned by the assembled character card"
                    )
                elif step.action_ref not in effective_levels:
                    errors.append(
                        f"route[{index}]: formal character action {step.action_ref!r} "
                        "has no admitted effective skill level"
                    )
                elif step.action_level != effective_levels[step.action_ref]:
                    errors.append(
                        f"route[{index}]: action level {step.action_level} does not match "
                        f"assembled effective level {effective_levels[step.action_ref]}"
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

        wave = setup.wave
        if wave is not None:
            if wave.kind == "stage":
                if not wave.stage_ref:
                    errors.append("battle_setup.wave.stage_ref must be set when kind is 'stage'")
                elif self.rules.wave_definition_for_stage(wave.stage_ref) is None:
                    errors.append(f"battle_setup.wave: unknown stage_ref {wave.stage_ref!r}")
            elif wave.kind == "wave_definition":
                if not wave.wave_definition_ref:
                    errors.append("battle_setup.wave.wave_definition_ref must be set when kind is 'wave_definition'")
                elif self.rules.wave_definition(wave.wave_definition_ref) is None:
                    errors.append(f"battle_setup.wave: unknown wave_definition_ref {wave.wave_definition_ref!r}")

        for index, status in enumerate(setup.initial_statuses):
            prefix = f"battle_setup.initial_statuses[{index}]"
            for field_name, unit_id in (
                ("target_id", status.target_id),
                ("source_id", status.source_id),
                ("owner_id", status.owner_id),
                ("caster_id", status.caster_id),
                ("param_entity_id", status.param_entity_id),
                ("current_action_target_id", status.current_action_target_id),
            ):
                if unit_id is not None and unit_id not in unit_ids:
                    errors.append(f"{prefix}: unknown {field_name} {unit_id!r}")
            if not status.effect_ref:
                errors.append(f"{prefix}.effect_ref must be set")
            else:
                effect = self.rules.effect(status.effect_ref)
                if effect is None:
                    errors.append(f"{prefix}: unknown effect_ref {status.effect_ref!r}")
                elif effect.opcode != "AddModifier":
                    errors.append(
                        f"{prefix}: effect_ref {status.effect_ref!r} opcode is "
                        f"{effect.opcode!r}, expected 'AddModifier'"
                    )
                else:
                    traces.append(effect.source.to_json())

        for index, summon in enumerate(setup.initial_summons):
            prefix = f"battle_setup.initial_summons[{index}]"
            if summon.owner_id not in unit_ids:
                errors.append(f"{prefix}: unknown owner_id {summon.owner_id!r}")
            if summon.kind == "summoned_monster":
                if not summon.summon_intent_ref:
                    errors.append(f"{prefix}.summon_intent_ref must be set for summoned_monster")
                else:
                    intent = self.rules.summon_monster_intent(summon.summon_intent_ref)
                    if intent is None:
                        errors.append(f"{prefix}: unknown summon_intent_ref {summon.summon_intent_ref!r}")
                    else:
                        traces.append(intent.source.to_json())
            elif summon.kind == "battle_unit_summon":
                if summon.summon_intent_ref:
                    definition = self.rules.summon_unit_definition(summon.summon_intent_ref)
                    if definition is None:
                        errors.append(f"{prefix}: unknown summon_unit_definition {summon.summon_intent_ref!r}")
                    else:
                        traces.append(definition.source.to_json())
                if summon.entity_ref:
                    definition = self.rules.summon_unit_definition_for_unit_id(summon.entity_ref)
                    entity = self.rules.entity(summon.entity_ref)
                    if definition is None and entity is None:
                        errors.append(f"{prefix}: unknown entity_ref {summon.entity_ref!r}")
            elif summon.kind == "servant":
                servant_ref = summon.summon_intent_ref or summon.entity_ref
                if not servant_ref:
                    errors.append(f"{prefix}.summon_intent_ref or entity_ref must be set for servant")
                else:
                    definition = self.rules.servant_definition(servant_ref)
                    if definition is None:
                        errors.append(f"{prefix}: unknown servant definition/ref {servant_ref!r}")
                    elif definition.coverage_status != "executable":
                        errors.append(
                            f"{prefix}: servant definition {servant_ref!r} is not executable: "
                            f"{definition.blocked_reason or definition.coverage_status}"
                        )
                    else:
                        owner = units_by_id.get(summon.owner_id)
                        if owner is not None and definition.owner_entity_ref and owner.entity_ref != definition.owner_entity_ref:
                            errors.append(
                                f"{prefix}: servant owner {summon.owner_id!r} entity_ref {owner.entity_ref!r} "
                                f"does not match {definition.owner_entity_ref!r}"
                            )
                        traces.append(definition.source.to_json())

        timeline = setup.timeline
        if any(unit.build_mode == "assembled_character_build" for unit in scenario.units):
            if timeline is None or timeline.mode != "runtime_initialize":
                errors.append(
                    "formal character builds require battle_setup.timeline.mode='runtime_initialize'"
                )
            elif timeline.action_values or timeline.explicit_overrides:
                errors.append(
                    "formal character builds cannot carry runtime_initialize action_values "
                    "or explicit_overrides"
                )
        if timeline is not None:
            may_reference_setup_units = bool(setup.initial_summons)
            if timeline.turn_owner_id is not None and timeline.turn_owner_id not in unit_ids and not may_reference_setup_units:
                errors.append(f"battle_setup.timeline: unknown turn_owner_id {timeline.turn_owner_id!r}")
            for unit_id in timeline.action_values:
                if unit_id not in unit_ids and not may_reference_setup_units:
                    errors.append(f"battle_setup.timeline.action_values: unknown unit_id {unit_id!r}")
            for unit_id in timeline.explicit_overrides:
                if unit_id not in unit_ids and not may_reference_setup_units:
                    errors.append(f"battle_setup.timeline.explicit_overrides: unknown unit_id {unit_id!r}")

        return ScenarioValidationResult(ok=not errors, errors=tuple(errors), source_traces=tuple(traces))


def _expected_unit_types(side: str) -> set[str]:
    if side == "ally":
        return set(ALLY_ENTITY_TYPES)
    if side == "enemy":
        return set(ENEMY_ENTITY_TYPES)
    if side == "summon":
        return set(SUMMON_ENTITY_TYPES)
    return set()
