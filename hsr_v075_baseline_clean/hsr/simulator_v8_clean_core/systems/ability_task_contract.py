from __future__ import annotations

from ..rules.ir import AbilityTaskIR
from ..rules.rulebook import RuleBook


def is_process_only_ability_task(task: AbilityTaskIR) -> bool:
    return task.execution_mode == "process_only"


def _process_only_task_blocked_reason(rules: RuleBook, task: AbilityTaskIR) -> str:
    if task.coverage_status != "audit_only":
        return f"process_only_task_coverage_mismatch:{task.coverage_status}"
    if task.blocked_reason:
        return task.blocked_reason
    if not task.effect_id:
        return "process_only_task_effect_missing"
    effect = rules.effect(task.effect_id)
    if effect is None:
        return "process_only_task_effect_missing"
    if effect.opcode != task.opcode:
        return "process_only_task_effect_opcode_mismatch"
    if effect.coverage_status != "audit_only":
        return f"process_only_effect_coverage_mismatch:{effect.coverage_status}"
    if effect.source != task.source:
        return "process_only_task_effect_source_mismatch"
    contract = effect.payload.get("process_only_contract")
    if not isinstance(contract, dict):
        return "process_only_task_source_contract_missing"
    if contract.get("schema_version") != "ability_process_only_source_shape_v1":
        return "process_only_task_source_contract_version_mismatch"
    if contract.get("opcode") != task.opcode:
        return "process_only_task_source_contract_opcode_mismatch"
    source_fields = contract.get("source_fields")
    source_field_types = contract.get("source_field_types")
    if (
        not isinstance(source_fields, list)
        or "$type" not in source_fields
        or len(source_fields) != len(set(source_fields))
        or not isinstance(source_field_types, dict)
        or set(source_field_types) != set(source_fields)
        or not all(
            isinstance(field_name, str)
            and field_name
            and isinstance(field_type, str)
            and field_type
            for field_name, field_type in source_field_types.items()
        )
    ):
        return "process_only_task_source_contract_shape_invalid"
    if contract.get("source_shape_status") != "admitted" or contract.get(
        "blocked_reason"
    ):
        return "process_only_task_source_shape_not_admitted"
    return ""


def ability_task_runtime_blocked_reason(rules: RuleBook, task: AbilityTaskIR) -> str:
    if is_process_only_ability_task(task):
        return _process_only_task_blocked_reason(rules, task)
    if task.execution_mode != "runtime_effect":
        return f"ability_task_execution_mode_not_admitted:{task.execution_mode}"
    if task.coverage_status != "executable":
        return task.blocked_reason or (
            f"action_task_not_executable:{task.task_id}:{task.coverage_status}"
        )
    if task.opcode == "PredicateTaskList":
        condition = rules.condition(task.condition_id) if task.condition_id else None
        if condition is None:
            return "missing_predicate_condition"
        if condition.coverage_status != "executable":
            return condition.blocked_reason or f"condition_not_executable:{condition.coverage_status}:{condition.opcode}"
        return ""
    if task.opcode == "LoopExecuteTaskListWithInterval":
        if task.repeat_count <= 0:
            return "fixed_positive_loop_count_required"
        if not task.child_task_ids:
            return "loop_task_list_missing_or_empty"
        for child_task_id in task.child_task_ids:
            child = rules.ability_task(child_task_id)
            if child is None:
                return "loop_child_task_missing"
            if child.parent_task_id != task.task_id:
                return "loop_child_parent_mismatch"
        return ""
    if task.opcode == "SummonMonster":
        intents = tuple(
            intent
            for intent in rules.summon_monster_intents()
            if intent.source_task_id == task.task_id
        )
        if len(intents) != 1:
            return "summon_monster_intent_missing" if not intents else "summon_monster_intent_ambiguous"
        intent = intents[0]
        if intent.coverage_status != "executable":
            return intent.blocked_reason or f"summon_monster_intent_not_executable:{intent.coverage_status}"
        for entry in intent.entries:
            template = rules.unit_birth_template(entry.birth_template_id)
            if template is None:
                return "summon_monster_birth_template_missing"
            if template.coverage_status != "executable":
                return template.blocked_reason or f"summon_monster_birth_template_not_executable:{template.coverage_status}"
        return ""
    damage_emissions = rules.damage_emissions_for_task(task.task_id)
    if damage_emissions:
        damage_profile_ids: list[str] = []
        for emission in damage_emissions:
            if emission.action_id != task.action_id or emission.level != task.level:
                return "damage_emission_action_binding_mismatch"
            if emission.phase_id != task.phase_id:
                return "damage_emission_phase_binding_mismatch"
            if emission.coverage_status != "executable":
                return emission.blocked_reason or (
                    f"damage_emission_not_executable:{emission.coverage_status}"
                )
            if emission.hit_profile_id in damage_profile_ids:
                return "damage_emission_hit_profile_ambiguous"
            damage_profile_ids.append(emission.hit_profile_id)
            profile = rules.hit_profile(emission.hit_profile_id)
            if profile is None or profile.coverage_status != "executable":
                return "hit_profile_missing_or_not_executable"
            if profile.action_id != task.action_id or profile.level != task.level:
                return "damage_hit_profile_action_binding_mismatch"

        toughness_emissions = rules.toughness_emissions_for_task(task.task_id)
        toughness_profile_ids: list[str] = []
        for emission in toughness_emissions:
            if emission.action_id != task.action_id or emission.level != task.level:
                return "toughness_emission_action_binding_mismatch"
            if emission.phase_id != task.phase_id:
                return "toughness_emission_phase_binding_mismatch"
            if emission.coverage_status != "executable":
                return emission.blocked_reason or (
                    f"toughness_emission_not_executable:{emission.coverage_status}"
                )
            if emission.hit_profile_id in toughness_profile_ids:
                return "toughness_emission_hit_profile_ambiguous"
            toughness_profile_ids.append(emission.hit_profile_id)
            profile = rules.hit_profile(emission.hit_profile_id)
            if profile is None or profile.coverage_status != "executable":
                return "toughness_hit_profile_missing_or_not_executable"
        if set(damage_profile_ids) != set(toughness_profile_ids):
            return "damage_toughness_hit_profile_set_mismatch"
        return ""
    return ""
