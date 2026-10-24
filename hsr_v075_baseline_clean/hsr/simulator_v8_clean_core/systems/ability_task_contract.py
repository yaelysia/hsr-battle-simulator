from __future__ import annotations

from typing import Literal

from ..rules.ir import AbilityTaskIR
from ..rules.rulebook import RuleBook
from ..rules.task_graph import TaskGraphDefinitionReferenceIR, TaskGraphNodeIR


def is_process_only_ability_task(task: AbilityTaskIR) -> bool:
    return task.execution_mode == "process_only"


def emission_backed_damage_audit_reference_admitted(
    rules: RuleBook,
    task: AbilityTaskIR,
    node: TaskGraphNodeIR,
    unresolved: tuple[TaskGraphDefinitionReferenceIR, ...],
) -> bool:
    if (
        task.opcode != "DamageByAttackProperty"
        or task.execution_mode != "runtime_effect"
        or task.coverage_status != "executable"
        or task.blocked_reason
        or task.parent_task_id
        or node.node_kind != "leaf"
        or node.materialization_status != "materialized"
        or node.owner_domains != ("task_graph_execution",)
        or len(unresolved) != 1
        or not task.effect_id
        or not rules.damage_emissions_for_task(task.task_id)
    ):
        return False
    reference = unresolved[0]
    if (
        reference.reference_kind != "effect"
        or reference.definition_id != task.effect_id
        or reference.resolution_status != "deferred"
        or reference.blocked_reason
        != "task_graph_definition_not_admitted:effect:audit_only"
    ):
        return False
    effect = rules.effect(task.effect_id)
    task_evidence = task.source.evidence
    if (
        effect is None
        or effect.opcode != task.opcode
        or effect.coverage_status != "audit_only"
        or "parent_task_id" in task_evidence
        or "child_task_count" in task_evidence
        or effect.source.source_path != task.source.source_path
        or effect.source.raw_type != task.source.raw_type
        or effect.source.raw_id != task.source.raw_id
    ):
        return False
    return effect.source.evidence == {
        **task_evidence,
        "parent_task_id": "",
    }


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


def _anim_wrapper_task_blocked_reason(rules: RuleBook, task: AbilityTaskIR) -> str:
    """Prove the shared animation wrapper unit before any child executes.

    The parent's standard EffectIR contract and its complete, ordered direct
    child ledger must agree with the formal phase topology. Missing, blocked or
    unknown children keep the whole unit fail-closed.
    """
    effect = rules.effect(task.effect_id)
    if effect is None:
        return "anim_wrapper_effect_missing"
    if effect.opcode != task.opcode:
        return "anim_wrapper_effect_opcode_mismatch"
    if effect.source != task.source:
        return "anim_wrapper_effect_source_mismatch"
    if effect.coverage_status != "executable":
        return f"anim_wrapper_effect_not_executable:{effect.coverage_status}"
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return "anim_wrapper_standard_contract_missing"
    if standard.get("operation") != "anim_wrapper_task_list":
        return "anim_wrapper_operation_not_admitted"
    if standard.get("source_shape") != "animation_timeline_with_gameplay_leaves":
        return "anim_wrapper_source_shape_not_admitted"
    if standard.get("blocked_reason"):
        return f"anim_wrapper_source_shape_blocked:{standard['blocked_reason']}"
    ledger = tuple(getattr(task, "child_task_ids", ()) or ())
    if not ledger:
        return "anim_wrapper_child_ledger_missing"
    if len(set(ledger)) != len(ledger):
        return "anim_wrapper_child_ledger_duplicated"
    if standard.get("event_list_child_count") != len(ledger):
        return "anim_wrapper_child_ledger_count_mismatch"
    direct_children = tuple(
        child
        for child in rules.ability_tasks_for_phase(task.phase_id)
        if child.parent_task_id == task.task_id
    )
    if len(direct_children) != len(ledger) or {
        child.task_id for child in direct_children
    } != set(ledger):
        return "anim_wrapper_child_ledger_incomplete"
    by_id = {child.task_id: child for child in direct_children}
    gameplay_child_count = 0
    for child_task_id in ledger:
        child = by_id.get(child_task_id)
        if child is None:
            return f"anim_wrapper_child_task_missing:{child_task_id}"
        if child.parent_task_id != task.task_id:
            return f"anim_wrapper_child_parent_mismatch:{child_task_id}"
        if child.phase_id != task.phase_id or child.callback_kind != task.callback_kind:
            return f"anim_wrapper_child_callback_mismatch:{child_task_id}"
        if child.execution_mode != "process_only":
            gameplay_child_count += 1
    if standard.get("gameplay_child_count") != gameplay_child_count:
        return "anim_wrapper_gameplay_child_count_mismatch"
    if gameplay_child_count <= 0:
        return "anim_wrapper_gameplay_child_missing"
    return ""


def ability_task_runtime_blocked_reason(
    rules: RuleBook,
    task: AbilityTaskIR,
    *,
    topology_authority: Literal["task_graph", "external_legacy"],
) -> str:
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
    if task.opcode == "Retarget":
        if topology_authority == "task_graph":
            expression, reason = rules.target_expression_resolution(
                task.target_expression_id
            )
            return reason if expression is None else ""
        effect = rules.effect(task.effect_id)
        standard = effect.payload.get("standard") if effect is not None else None
        expression_id = (
            standard.get("target_expression_id")
            if isinstance(standard, dict) else None
        )
        if (
            effect is None
            or effect.coverage_status != "executable"
            or not isinstance(standard, dict)
            or standard.get("operation") != "retarget_task_list"
            or standard.get("blocked_reason")
            or not isinstance(expression_id, str)
            or not expression_id
        ):
            return "retarget_effect_contract_not_admitted"
        expression, reason = rules.target_expression_resolution(expression_id)
        if expression is None:
            return reason or "retarget_target_expression_missing"
        if not task.child_task_ids:
            return "retarget_task_list_missing_or_empty"
        for child_task_id in task.child_task_ids:
            child = rules.ability_task(child_task_id)
            if child is None:
                return "retarget_child_task_missing"
            if child.parent_task_id != task.task_id:
                return "retarget_child_parent_mismatch"
        return ""
    if task.opcode == "LoopExecuteTaskListWithInterval":
        if task.repeat_count <= 0:
            return "fixed_positive_loop_count_required"
        if topology_authority == "task_graph":
            return ""
        if not task.child_task_ids:
            return "loop_task_list_missing_or_empty"
        for child_task_id in task.child_task_ids:
            child = rules.ability_task(child_task_id)
            if child is None:
                return "loop_child_task_missing"
            if child.parent_task_id != task.task_id:
                return "loop_child_parent_mismatch"
        return ""
    if (
        task.opcode == "TriggerAnimStateWithMove"
        and topology_authority == "external_legacy"
    ):
        return _anim_wrapper_task_blocked_reason(rules, task)
    if task.opcode == "FireProjectile":
        effect = rules.effect(task.effect_id)
        standard = effect.payload.get("standard") if effect is not None else None
        contract = {key: value for key, value in standard.items() if key != "target_expression_refs"} if isinstance(standard, dict) else None
        if topology_authority != "task_graph":
            return "projectile_requires_formal_task_graph"
        if effect is None or effect.coverage_status != "executable" or contract != {
            "operation": "selected_single_projectile_impact", "target_count": 1,
            "wait_for_finish": True, "completion_branch": "projectile_hit",
        }:
            return "projectile_impact_contract_not_admitted"
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
        required_toughness_profiles = {
            emission.hit_profile_id for emission in damage_emissions
            if emission.toughness_emission_required
        }
        if required_toughness_profiles != set(toughness_profile_ids):
            return "damage_toughness_hit_profile_set_mismatch"
        return ""
    return ""
