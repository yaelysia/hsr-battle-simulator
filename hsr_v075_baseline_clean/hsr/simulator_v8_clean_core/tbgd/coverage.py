from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from .discovery import DiscoveryReport
from ..rules.ir import CanonicalIR


KNOWN_AUDIT_EFFECTS = {
    "AddModifier",
    "RemoveModifier",
    "ModifySPNew",
    "ModifyHP",
    "HealHP",
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
    "SummonUnit",
    "SummonMonster",
    "ForceKill",
    "PredicateTaskList",
}

KNOWN_AUDIT_CONDITIONS = {
    "ByCurrentSkillType",
    "ByCompareHPRatio",
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

    def to_json(self) -> dict[str, Any]:
        return {
            "discovery_summary": self.discovery_summary,
            "ir_summary": self.ir_summary,
            "opcode_status": self.opcode_status,
            "event_status": self.event_status,
            "formula_status": self.formula_status,
            "table_status": self.table_status,
            "modifier_status": self.modifier_status,
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

    ir_status_counts: Counter[str] = Counter()
    for collection in (ir.entities, ir.action_definitions, ir.triggers, ir.effects, ir.conditions, ir.formulas):
        for item in collection:
            ir_status_counts[item.coverage_status] += 1

    return CoverageMatrix(
        discovery_summary=report.to_json()["summary"],
        ir_summary={
            "entities": len(ir.entities),
            "action_definitions": len(ir.action_definitions),
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
    }
