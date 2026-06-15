from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from ..rules.ir import CanonicalIR
from ..tbgd.coverage import classify_opcode
from ..tbgd.discovery import DiscoveryReport


@dataclass(frozen=True)
class MechanicFidelityMatrix:
    opcode_status: dict[str, dict[str, Any]]
    event_status: dict[str, dict[str, Any]]
    formula_status: dict[str, dict[str, Any]]
    summary: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "opcode_status": self.opcode_status,
            "event_status": self.event_status,
            "formula_status": self.formula_status,
        }


def build_fidelity_matrix(report: DiscoveryReport, ir: CanonicalIR) -> MechanicFidelityMatrix:
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
    lifecycle_counts: Counter[str] = Counter()
    for opcode, count in sorted(report.gamecore_type_counts.items()):
        support_status = classify_opcode(opcode)
        lifecycle = _mechanic_lifecycle(
            discovered=count,
            lowered=lowered_opcodes[opcode],
            executable=executable_opcodes[opcode],
            support_status=support_status,
        )
        lifecycle_counts[lifecycle] += 1
        opcode_status[opcode] = {
            "discovered": count,
            "lowered": lowered_opcodes[opcode],
            "executable": executable_opcodes[opcode],
            "validated": 0,
            "support_status": support_status,
            "fidelity_status": lifecycle,
            "reason": _reason(opcode, support_status, lifecycle),
        }

    lowered_events = Counter(trigger.event for trigger in ir.triggers)
    event_status: dict[str, dict[str, Any]] = {}
    event_lifecycle_counts: Counter[str] = Counter()
    for event, count in sorted(report.event_counts.items()):
        lifecycle = "lowered" if lowered_events[event] else "discovered_only"
        event_lifecycle_counts[lifecycle] += 1
        event_status[event] = {
            "discovered": count,
            "lowered": lowered_events[event],
            "executable": 0,
            "validated": 0,
            "fidelity_status": lifecycle,
            "reason": "event window discovered; execution order not validated in v0_203",
        }

    formula_status = {
        "postfix_expr": {
            "lowered": sum(1 for formula in ir.formulas if formula.kind == "postfix_expr"),
            "executable": 0,
            "validated": 0,
            "fidelity_status": "lowered",
            "reason": "postfix expressions are recorded for audit but not executable in v0_203",
        },
        "fixed_value": {
            "lowered": sum(1 for formula in ir.formulas if formula.kind == "fixed_value"),
            "executable": sum(
                1 for formula in ir.formulas if formula.kind == "fixed_value" and formula.coverage_status == "executable"
            ),
            "validated": 0,
            "fidelity_status": "executable",
            "reason": "fixed literal values are executable but not yet tied to full combat formulas",
        },
    }

    return MechanicFidelityMatrix(
        opcode_status=opcode_status,
        event_status=event_status,
        formula_status=formula_status,
        summary={
            "opcode_count": len(opcode_status),
            "event_count": len(event_status),
            "opcode_lifecycle_counts": dict(sorted(lifecycle_counts.items())),
            "event_lifecycle_counts": dict(sorted(event_lifecycle_counts.items())),
        },
    )


def _mechanic_lifecycle(discovered: int, lowered: int, executable: int, support_status: str) -> str:
    if executable:
        return "executable"
    if lowered:
        return "lowered"
    if support_status == "unsupported":
        return "blocked"
    if discovered:
        return "discovered_only"
    return "blocked"


def _reason(opcode: str, support_status: str, lifecycle: str) -> str:
    if lifecycle == "executable":
        return "opcode has at least one executable Canonical IR path"
    if lifecycle == "lowered":
        return "opcode is lowered to Canonical IR but runtime semantics are not executable yet"
    if support_status == "supported_alias":
        return "target alias is recognized but not validated as a complete runtime mechanic"
    if support_status == "audit_only":
        return "opcode is recognized as combat-relevant but intentionally audit-only in v0_203"
    return f"opcode {opcode!r} has no v8 semantic mapping yet"

