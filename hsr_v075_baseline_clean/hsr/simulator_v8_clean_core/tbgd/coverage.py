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
    }
