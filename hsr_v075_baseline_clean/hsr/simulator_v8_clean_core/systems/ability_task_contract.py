from __future__ import annotations

from ..rules.ir import AbilityTaskIR
from ..rules.rulebook import RuleBook


# These tasks synchronize or present an already-selected ability graph.  They
# have no combat-state effect and therefore complete as explicit process-only
# nodes.  Unknown opcodes remain blocked.
PROCESS_ONLY_ABILITY_TASK_OPCODES = frozenset(
    {
        "LookAt",
        "SkillExecutionStart",
        "SkillPerformFinish",
        "TriggerAnimState",
        "VCameraConfigChange",
        "WaitAnimState",
        "WaitSecond",
    }
)


def is_process_only_ability_task(task: AbilityTaskIR) -> bool:
    return task.opcode in PROCESS_ONLY_ABILITY_TASK_OPCODES


def ability_task_runtime_blocked_reason(rules: RuleBook, task: AbilityTaskIR) -> str:
    if is_process_only_ability_task(task):
        return ""
    if task.opcode == "PredicateTaskList":
        condition = rules.condition(task.condition_id) if task.condition_id else None
        if condition is None:
            return "missing_predicate_condition"
        if condition.coverage_status != "executable":
            return condition.blocked_reason or f"condition_not_executable:{condition.coverage_status}:{condition.opcode}"
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
    if task.coverage_status != "executable":
        return task.blocked_reason or f"action_task_not_executable:{task.task_id}:{task.coverage_status}"
    return ""
