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

    def to_json(self) -> dict[str, Any]:
        return {
            "discovery_summary": self.discovery_summary,
            "ir_summary": self.ir_summary,
            "opcode_status": self.opcode_status,
            "event_status": self.event_status,
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
