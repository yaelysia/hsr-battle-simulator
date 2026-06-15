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
    opcode_status: dict[str, dict[str, Any]] = {}
    for opcode, count in sorted(report.gamecore_type_counts.items()):
        status = classify_opcode(opcode)
        opcode_status[opcode] = {"count": count, "status": status}

    event_status = {
        event: {"count": count, "status": "audit_only"}
        for event, count in sorted(report.event_counts.items())
    }

    ir_status_counts: Counter[str] = Counter()
    for collection in (ir.entities, ir.triggers, ir.effects, ir.conditions, ir.formulas):
        for item in collection:
            ir_status_counts[item.coverage_status] += 1

    return CoverageMatrix(
        discovery_summary=report.to_json()["summary"],
        ir_summary={
            "entities": len(ir.entities),
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

