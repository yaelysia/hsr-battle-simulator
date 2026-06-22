from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from .discovery import DiscoveryReport
from ..rules.ir import CanonicalIR


KNOWN_AUDIT_EFFECTS = {
    "AddModifier",
    "RemoveModifier",
    "RemoveSelfModifier",
    "ModifySPNew",
    "ModifyHP",
    "HealHP",
    "InitShield",
    "StackShield",
    "ModifyShield",
    "LoseHPByRatio",
    "DamageByAttackProperty",
    "ModifyDamageData",
    "SetDynamicValue",
    "SetDynamicValueByModifierValue",
    "StackProperty",
    "DispelStatus",
    "SetActionDelay",
    "ModifyActionDelay",
    "SetEnergyBarState",
    "SetMonsterEnergyBarState",
    "SetSummonerEnergyBarState",
    "SummonUnit",
    "SummonMonster",
    "ForceKill",
    "PredicateTaskList",
}

KNOWN_AUDIT_CONDITIONS = {
    "ByAnd",
    "ByAny",
    "ByAttackType",
    "ByCurrentSkillType",
    "ByCompareDynamicValue",
    "ByCompareHPRatio",
    "ByCompareModifierValue",
    "ByCompareTarget",
    "ByIsContainModifier",
    "ByNot",
    "ByTargetTeam",
    "ByTargetHasModifier",
    "ByTargetHasStatus",
    "ByCheckTargetCamp",
    "ByCompareProperty",
}


@dataclass(frozen=True)
class CoverageMatrix:
    discovery_summary: dict[str, Any]
    ir_summary: dict[str, Any]
    opcode_status: dict[str, dict[str, Any]]
    event_status: dict[str, dict[str, Any]]
    formula_status: dict[str, dict[str, Any]]
    table_status: dict[str, dict[str, Any]]
    modifier_status: dict[str, Any]
    combatant_profile_status: dict[str, Any]
    action_execution_status: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "discovery_summary": self.discovery_summary,
            "ir_summary": self.ir_summary,
            "opcode_status": self.opcode_status,
            "event_status": self.event_status,
            "formula_status": self.formula_status,
            "table_status": self.table_status,
            "modifier_status": self.modifier_status,
            "combatant_profile_status": self.combatant_profile_status,
            "action_execution_status": self.action_execution_status,
        }


def build_coverage_matrix(report: DiscoveryReport, ir: CanonicalIR) -> CoverageMatrix:
    lowered_opcodes: Counter[str] = Counter()
    executable_opcodes: Counter[str] = Counter()
    for effect in ir.effects:
        lowered_opcodes[effect.opcode] += 1
        if effect.coverage_status == "executable":
            executable_opcodes[effect.opcode] += 1
    for condition in ir.conditions:
        lowered_opcodes[condition.opcode] += 1
        if condition.coverage_status == "executable":
            executable_opcodes[condition.opcode] += 1

    opcode_status: dict[str, dict[str, Any]] = {}
    for opcode, count in sorted(report.gamecore_type_counts.items()):
        status = classify_opcode(opcode)
        fidelity_status = _fidelity_status(
            support_status=status,
            lowered=lowered_opcodes[opcode],
            executable=executable_opcodes[opcode],
        )
        opcode_status[opcode] = {
            "count": count,
            "status": status,
            "fidelity_status": fidelity_status,
            "lowered": lowered_opcodes[opcode],
            "executable": executable_opcodes[opcode],
            "validated": 0,
            "reason": explain_opcode_status(opcode, status, fidelity_status),
        }

    lowered_events = Counter(trigger.event for trigger in ir.triggers)
    event_status = {
        event: {
            "count": count,
            "status": "audit_only",
            "fidelity_status": "lowered" if lowered_events[event] else "discovered_only",
            "lowered": lowered_events[event],
            "executable": 0,
            "validated": 0,
            "reason": "event window discovered; execution order is not validated in this baseline",
        }
        for event, count in sorted(report.event_counts.items())
    }
    formula_status = _formula_status(ir)
    modifier_status = _modifier_status(ir, lowered_opcodes, executable_opcodes)
    action_execution_status = _action_execution_status(ir)

    ir_status_counts: Counter[str] = Counter()
    for collection in (
        ir.entities,
        ir.combatant_profiles,
        ir.action_definitions,
        ir.action_ability_bindings,
        ir.ability_phases,
        ir.ability_tasks,
        ir.action_events,
        ir.hit_profiles,
        ir.damage_emissions,
        ir.toughness_emissions,
        ir.break_templates,
        ir.break_damage_emissions,
        ir.break_status_emissions,
        ir.status_callbacks,
        ir.status_callback_tasks,
        ir.status_damage_emissions,
        ir.action_delay_emissions,
        ir.super_break_emissions,
        ir.triggers,
        ir.effects,
        ir.conditions,
        ir.formulas,
    ):
        for item in collection:
            ir_status_counts[item.coverage_status] += 1

    return CoverageMatrix(
        discovery_summary=report.to_json()["summary"],
        ir_summary={
            "entities": len(ir.entities),
            "combatant_profiles": len(ir.combatant_profiles),
            "action_definitions": len(ir.action_definitions),
            "action_ability_bindings": len(ir.action_ability_bindings),
            "ability_phases": len(ir.ability_phases),
            "ability_tasks": len(ir.ability_tasks),
            "action_events": len(ir.action_events),
            "hit_profiles": len(ir.hit_profiles),
            "damage_emissions": len(ir.damage_emissions),
            "toughness_emissions": len(ir.toughness_emissions),
            "break_templates": len(ir.break_templates),
            "break_damage_emissions": len(ir.break_damage_emissions),
            "break_status_emissions": len(ir.break_status_emissions),
            "status_callbacks": len(ir.status_callbacks),
            "status_callback_tasks": len(ir.status_callback_tasks),
            "status_damage_emissions": len(ir.status_damage_emissions),
            "action_delay_emissions": len(ir.action_delay_emissions),
            "super_break_emissions": len(ir.super_break_emissions),
            "triggers": len(ir.triggers),
            "effects": len(ir.effects),
            "conditions": len(ir.conditions),
            "formulas": len(ir.formulas),
            "coverage_status_counts": dict(sorted(ir_status_counts.items())),
        },
        opcode_status=opcode_status,
        event_status=event_status,
        formula_status=formula_status,
        table_status=dict(ir.metadata.get("table_status", {})),
        modifier_status=modifier_status,
        combatant_profile_status=_combatant_profile_status(ir),
        action_execution_status=action_execution_status,
    )


def classify_opcode(opcode: str) -> str:
    if opcode in KNOWN_AUDIT_EFFECTS or opcode in KNOWN_AUDIT_CONDITIONS:
        return "audit_only"
    if opcode.endswith("Alias") or opcode.startswith("Target"):
        return "supported_alias"
    return "unsupported"


def explain_opcode_status(opcode: str, support_status: str, fidelity_status: str) -> str:
    if fidelity_status == "executable":
        return "opcode has at least one executable Canonical IR path"
    if fidelity_status == "lowered":
        return "opcode is lowered to Canonical IR but runtime semantics are not executable yet"
    if support_status == "supported_alias":
        return "target alias is recognized but not validated as a complete runtime mechanic"
    if support_status == "audit_only":
        return "opcode is recognized as combat-relevant but intentionally audit-only in this baseline"
    return f"opcode {opcode!r} has no v8 semantic mapping yet"


def _fidelity_status(support_status: str, lowered: int, executable: int) -> str:
    if executable:
        return "executable"
    if lowered:
        return "lowered"
    if support_status == "unsupported":
        return "blocked"
    return "discovered_only"


def _formula_status(ir: CanonicalIR) -> dict[str, dict[str, Any]]:
    return {
        "elation_damage": _damage_formula_status(
            ir,
            family="elation",
            status="blocked",
            reason=(
                "ElationDamage is discovered as a 4.0 mainline damage family, "
                "but the complete damage formula is not executable in v0_208"
            ),
        ),
        "true_damage": _damage_formula_status(
            ir,
            family="true_damage",
            status="lowered",
            reason="True damage bypasses normal damage multipliers; event semantics are not fully validated yet",
        ),
        "hp_loss": _damage_formula_status(
            ir,
            family="hp_loss",
            status="lowered",
            reason="HP loss bypasses normal damage multipliers and is tracked separately from damage records",
        ),
    }


def _damage_formula_status(ir: CanonicalIR, family: str, status: str, reason: str) -> dict[str, Any]:
    formulas = [formula for formula in ir.formulas if formula.expression.get("damage_formula_family") == family]
    properties = sorted({str(formula.expression.get("property")) for formula in formulas if formula.expression.get("property")})
    executable = sum(1 for formula in formulas if formula.expression.get("runtime_status") == "executable")
    fidelity_status = "discovered_only"
    if formulas:
        fidelity_status = "blocked" if status == "blocked" else "lowered"
    return {
        "status": status,
        "fidelity_status": fidelity_status,
        "lowered": len(formulas),
        "executable": executable,
        "validated": 0,
        "properties": properties,
        "reason": reason,
    }


def _modifier_status(
    ir: CanonicalIR,
    lowered_opcodes: Counter[str],
    executable_opcodes: Counter[str],
) -> dict[str, Any]:
    definitions = [entity for entity in ir.entities if entity.entity_type == "modifier_definition"]
    global_definitions = [
        entity for entity in definitions if entity.source.raw_type == "GlobalModifiers"
    ]
    with_stack_properties = [
        entity for entity in definitions if entity.fields.get("stack_properties")
    ]
    return {
        "modifier_definitions": len(definitions),
        "global_modifier_definitions": len(global_definitions),
        "definitions_with_stack_properties": len(with_stack_properties),
        "add_modifier": {
            "lowered": lowered_opcodes["AddModifier"],
            "executable": executable_opcodes["AddModifier"],
            "reason": "AddModifier payload is standardized; runtime execution is validated by v0_210",
        },
        "dynamic_value_store": {
            "set_dynamic_value": {
                "lowered": lowered_opcodes["SetDynamicValue"],
                "executable": executable_opcodes["SetDynamicValue"],
                "blocked": max(0, lowered_opcodes["SetDynamicValue"] - executable_opcodes["SetDynamicValue"]),
                "reason": "SetDynamicValue is standardized into DynamicValueStore writes when target and numeric payload are executable",
            },
            "set_dynamic_value_by_modifier_value": {
                "lowered": lowered_opcodes["SetDynamicValueByModifierValue"],
                "executable": executable_opcodes["SetDynamicValueByModifierValue"],
                "blocked": max(
                    0,
                    lowered_opcodes["SetDynamicValueByModifierValue"]
                    - executable_opcodes["SetDynamicValueByModifierValue"],
                ),
                "reason": "SetDynamicValueByModifierValue is standardized when source modifier, value type, target key, and multiplier are executable",
            },
        },
    }


def _combatant_profile_status(ir: CanonicalIR) -> dict[str, Any]:
    status_counts = Counter(profile.coverage_status for profile in ir.combatant_profiles)
    blocked_reasons = Counter(profile.blocked_reason for profile in ir.combatant_profiles if profile.blocked_reason)
    monster_profiles = [profile for profile in ir.combatant_profiles if profile.entity_type == "monster"]
    return {
        "lowered": len(ir.combatant_profiles),
        "monster_profiles": len(monster_profiles),
        "executable": status_counts["executable"],
        "blocked": status_counts["blocked"],
        "lowered_only": status_counts["lowered"],
        "status_counts": dict(sorted(status_counts.items())),
        "blocked_reason_counts": dict(sorted(blocked_reasons.items())),
        "reason": "CombatantProfileIR derives enemy base profile from MonsterConfig and MonsterTemplateConfig; executable monster profiles may seed scenario state when panel fields are absent",
    }


def _action_execution_status(ir: CanonicalIR) -> dict[str, Any]:
    binding_status = Counter(binding.coverage_status for binding in ir.action_ability_bindings)
    binding_reasons = Counter(
        binding.blocked_reason
        for binding in ir.action_ability_bindings
        if binding.blocked_reason
    )
    phase_status = Counter(phase.coverage_status for phase in ir.ability_phases)
    phase_reasons = Counter(phase.blocked_reason for phase in ir.ability_phases if phase.blocked_reason)
    task_status = Counter(task.coverage_status for task in ir.ability_tasks)
    task_reasons = Counter(task.blocked_reason for task in ir.ability_tasks if task.blocked_reason)
    task_opcodes = Counter(task.opcode for task in ir.ability_tasks)
    event_status = Counter(event.coverage_status for event in ir.action_events)
    hit_status = Counter(profile.coverage_status for profile in ir.hit_profiles)
    emission_status = Counter(emission.coverage_status for emission in ir.damage_emissions)
    emission_reasons = Counter(
        emission.blocked_reason
        for emission in ir.damage_emissions
        if emission.blocked_reason
    )
    toughness_status = Counter(emission.coverage_status for emission in ir.toughness_emissions)
    toughness_reasons = Counter(
        emission.blocked_reason
        for emission in ir.toughness_emissions
        if emission.blocked_reason
    )
    break_template_status = Counter(template.coverage_status for template in ir.break_templates)
    break_template_reasons = Counter(template.blocked_reason for template in ir.break_templates if template.blocked_reason)
    break_damage_status = Counter(emission.coverage_status for emission in ir.break_damage_emissions)
    break_damage_reasons = Counter(
        emission.blocked_reason
        for emission in ir.break_damage_emissions
        if emission.blocked_reason
    )
    break_status_status = Counter(emission.coverage_status for emission in ir.break_status_emissions)
    break_status_reasons = Counter(
        emission.blocked_reason
        for emission in ir.break_status_emissions
        if emission.blocked_reason
    )
    status_callback_status = Counter(callback.coverage_status for callback in ir.status_callbacks)
    status_callback_reasons = Counter(callback.blocked_reason for callback in ir.status_callbacks if callback.blocked_reason)
    status_callback_blocked_categories = Counter(
        _listener_blocked_category(callback.blocked_reason or callback.blocking_dependency)
        for callback in ir.status_callbacks
        if callback.blocked_reason or callback.blocking_dependency
    )
    status_callback_scopes = Counter(callback.scope_kind for callback in ir.status_callbacks)
    status_callback_source_modes = Counter(callback.source_mode for callback in ir.status_callbacks)
    status_callback_task_status = Counter(task.coverage_status for task in ir.status_callback_tasks)
    status_callback_task_reasons = Counter(task.blocked_reason for task in ir.status_callback_tasks if task.blocked_reason)
    status_damage_status = Counter(emission.coverage_status for emission in ir.status_damage_emissions)
    status_damage_reasons = Counter(emission.blocked_reason for emission in ir.status_damage_emissions if emission.blocked_reason)
    action_delay_status = Counter(emission.coverage_status for emission in ir.action_delay_emissions)
    action_delay_reasons = Counter(emission.blocked_reason for emission in ir.action_delay_emissions if emission.blocked_reason)
    super_break_status = Counter(emission.coverage_status for emission in ir.super_break_emissions)
    super_break_reasons = Counter(
        emission.blocked_reason
        for emission in ir.super_break_emissions
        if emission.blocked_reason
    )
    hit_reasons = Counter(
        profile.blocked_reason
        for profile in ir.hit_profiles
        if profile.blocked_reason
    )
    fidelity_status = Counter(profile.numeric_fidelity_status for profile in ir.hit_profiles)
    multi_param_profiles = [
        profile
        for profile in ir.hit_profiles
        if isinstance(profile.multiplier_source, dict)
        and profile.multiplier_source.get("multi_param_list_not_implemented") is True
    ]
    show_evidence_profiles = [
        profile
        for profile in ir.hit_profiles
        if (
            isinstance(profile.multiplier_source, dict)
            and profile.multiplier_source.get("show_damage_audit_only") is True
        )
        or (
            isinstance(profile.stance_source, dict)
            and profile.stance_source.get("show_stance_audit_only") is True
        )
    ]
    return {
        "action_ability_bindings": {
            "lowered": len(ir.action_ability_bindings),
            "executable": binding_status["executable"],
            "blocked": binding_status["blocked"],
            "audit_only": binding_status["audit_only"],
            "status_counts": dict(sorted(binding_status.items())),
            "blocked_reason_counts": dict(sorted(binding_reasons.items())),
            "reason": "ActionAbilityBindingIR binds action definitions to mainline ConfigCharacter and ConfigAbility evidence where stable paths exist",
        },
        "ability_phases": {
            "lowered": len(ir.ability_phases),
            "status_counts": dict(sorted(phase_status.items())),
            "blocked_reason_counts": dict(sorted(phase_reasons.items())),
            "reason": "AbilityPhaseIR lowers phase structure and links to AbilityTaskIR; only standardized task effects are executable in this baseline",
        },
        "ability_tasks": {
            "lowered": len(ir.ability_tasks),
            "executable": task_status["executable"],
            "blocked": task_status["blocked"],
            "status_counts": dict(sorted(task_status.items())),
            "blocked_reason_counts": dict(sorted(task_reasons.items())),
            "top_opcode_counts": dict(task_opcodes.most_common(20)),
            "reason": "AbilityTaskIR lowers phase callback tasks; only standardized executable effects are run by the runtime",
        },
        "action_events": {
            "lowered": len(ir.action_events),
            "status_counts": dict(sorted(event_status.items())),
            "reason": "ActionEventIR is driven by action ability binding/phase graph when available, with derived windows explicitly marked",
        },
        "hit_profiles": {
            "lowered": len(ir.hit_profiles),
            "executable": hit_status["executable"],
            "blocked": hit_status["blocked"],
            "status_counts": dict(sorted(hit_status.items())),
            "numeric_fidelity_status_counts": dict(sorted(fidelity_status.items())),
            "blocked_reason_counts": dict(sorted(hit_reasons.items())),
            "multi_param_profile_count": len(multi_param_profiles),
            "show_damage_or_stance_evidence_count": len(show_evidence_profiles),
            "reason": "HitProfileIR carries multiplier evidence; multi-hit and display stance/damage mappings are not treated as final runtime semantics",
        },
        "damage_emissions": {
            "lowered": len(ir.damage_emissions),
            "executable": emission_status["executable"],
            "blocked": emission_status["blocked"],
            "audit_only": emission_status["audit_only"],
            "status_counts": dict(sorted(emission_status.items())),
            "blocked_reason_counts": dict(sorted(emission_reasons.items())),
            "reason": "DamageEmissionIR links AbilityTaskIR damage opcodes to hit profile evidence; blocked emissions are not allowed to create fake damage packets",
        },
        "toughness_emissions": {
            "lowered": len(ir.toughness_emissions),
            "executable": toughness_status["executable"],
            "blocked": toughness_status["blocked"],
            "audit_only": toughness_status["audit_only"],
            "status_counts": dict(sorted(toughness_status.items())),
            "blocked_reason_counts": dict(sorted(toughness_reasons.items())),
            "reason": "ToughnessEmissionIR links AbilityTaskIR AttackProperty.StanceValue to runtime toughness execution; ShowStance remains audit-only display evidence",
        },
        "break_templates": {
            "lowered": len(ir.break_templates),
            "executable": break_template_status["executable"],
            "blocked": break_template_status["blocked"],
            "status_counts": dict(sorted(break_template_status.items())),
            "blocked_reason_counts": dict(sorted(break_template_reasons.items())),
            "reason": "BreakTemplateIR lowers normal StanceBreak global templates for break lifecycle source tracing",
        },
        "break_base_damage": {
            "lowered": len(ir.break_base_damage),
            "executable": sum(1 for item in ir.break_base_damage if item.coverage_status == "executable"),
            "blocked": sum(1 for item in ir.break_base_damage if item.coverage_status == "blocked"),
            "reason": "BreakBaseDamageIR lowers AvatarBreakDamage level table used by admitted normal break damage",
        },
        "break_damage_emissions": {
            "lowered": len(ir.break_damage_emissions),
            "executable": break_damage_status["executable"],
            "blocked": break_damage_status["blocked"],
            "status_counts": dict(sorted(break_damage_status.items())),
            "blocked_reason_counts": dict(sorted(break_damage_reasons.items())),
            "reason": "BreakDamageEmissionIR records admitted ByBreakDamage template tasks; runtime still blocks unsupported formula operands",
        },
        "break_status_emissions": {
            "lowered": len(ir.break_status_emissions),
            "executable": break_status_status["executable"],
            "blocked": break_status_status["blocked"],
            "status_counts": dict(sorted(break_status_status.items())),
            "blocked_reason_counts": dict(sorted(break_status_reasons.items())),
            "reason": "BreakStatusEmissionIR records standardized status effects from normal break templates; executable emissions go through EffectRegistry and StatusSystem",
        },
        "status_callbacks": {
            "lowered": len(ir.status_callbacks),
            "executable": status_callback_status["executable"],
            "blocked": status_callback_status["blocked"],
            "status_counts": dict(sorted(status_callback_status.items())),
            "blocked_reason_counts": dict(sorted(status_callback_reasons.items())),
            "blocked_category_counts": dict(sorted(status_callback_blocked_categories.items())),
            "scope_counts": dict(sorted(status_callback_scopes.items())),
            "source_mode_counts": dict(sorted(status_callback_source_modes.items())),
            "reason": "StatusCallbackIR lowers modifier callbacks with explicit listener scope; only admitted source/scope/task combinations may mutate runtime state",
        },
        "status_callback_tasks": {
            "lowered": len(ir.status_callback_tasks),
            "executable": status_callback_task_status["executable"],
            "blocked": status_callback_task_status["blocked"],
            "status_counts": dict(sorted(status_callback_task_status.items())),
            "blocked_reason_counts": dict(sorted(status_callback_task_reasons.items())),
            "reason": "StatusCallbackTaskIR lowers modifier callback tasks; unsupported branches remain blocked and non-mutating",
        },
        "status_damage_emissions": {
            "lowered": len(ir.status_damage_emissions),
            "executable": status_damage_status["executable"],
            "blocked": status_damage_status["blocked"],
            "status_counts": dict(sorted(status_damage_status.items())),
            "blocked_reason_counts": dict(sorted(status_damage_reasons.items())),
            "reason": "StatusDamageEmissionIR admits OnPhase1 ByBreakDamage DOT tick sources only when formula shape can be evaluated by NumericEvaluator",
        },
        "action_delay_emissions": {
            "lowered": len(ir.action_delay_emissions),
            "executable": action_delay_status["executable"],
            "blocked": action_delay_status["blocked"],
            "status_counts": dict(sorted(action_delay_status.items())),
            "blocked_reason_counts": dict(sorted(action_delay_reasons.items())),
            "reason": "ActionDelayEmissionIR records OnStack delay evidence; ModifyActionDelay normalized AV scale remains blocked until source semantics are admitted",
        },
        "super_break_emissions": {
            "lowered": len(ir.super_break_emissions),
            "executable": super_break_status["executable"],
            "blocked": super_break_status["blocked"],
            "status_counts": dict(sorted(super_break_status.items())),
            "blocked_reason_counts": dict(sorted(super_break_reasons.items())),
            "reason": "SuperBreakEmissionIR records admitted global super-break template damage tasks; runtime requires audited stance-damage and break-base inputs",
        },
    }


def _listener_blocked_category(reason: str) -> str:
    if not reason:
        return ""
    if "event_alias" in reason or "listener_event_mapping" in reason:
        return "event_alias_missing"
    if "source_mode_not_admitted" in reason or reason.startswith("source_"):
        return "source_not_admitted"
    if reason.startswith("scope_") or "scope_not_admitted" in reason:
        return "scope_not_admitted"
    if "condition" in reason:
        return "condition_not_admitted"
    if "target" in reason or "alias" in reason:
        return "target_not_admitted"
    if "effect" in reason or "opcode" in reason or "callback_task" in reason:
        return "effect_not_admitted"
    if "queue" in reason or "intent" in reason or "normalized_action_delay" in reason:
        return "downstream_intent_missing"
    if reason in {"status_callback_missing", "listener_match_missing"}:
        return "effect_not_admitted"
    if reason == "status_detail_missing":
        return "target_not_admitted"
    return "downstream_intent_missing"
