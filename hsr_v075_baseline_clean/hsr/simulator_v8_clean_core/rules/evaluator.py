from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ir import ConditionIR, FormulaIR


@dataclass(frozen=True)
class EvaluationContext:
    actor_id: str | None = None
    target_id: str | None = None
    event_payload: dict[str, Any] | None = None
    dynamic_values: dict[str, float] | None = None


class RuleEvaluator:
    """Conservative evaluator for v0_200.

    Only literal and identity-safe expressions are executable. Everything else
    remains audit-only or unsupported until the corresponding HSR mechanic is
    implemented explicitly.
    """

    def evaluate_condition(self, condition: ConditionIR, context: EvaluationContext) -> bool | None:
        if condition.coverage_status != "executable":
            return None
        if condition.opcode == "AlwaysTrue":
            return True
        if condition.opcode == "ByCurrentSkillType":
            expected = condition.payload.get("SkillType")
            actual = (context.event_payload or {}).get("SkillType")
            return expected == actual
        return None

    def evaluate_formula(self, formula: FormulaIR, context: EvaluationContext) -> float | None:
        expression = formula.expression
        if formula.coverage_status != "executable":
            return None
        if formula.kind == "fixed_value":
            value = expression.get("Value")
            return float(value) if isinstance(value, (int, float)) else None
        if formula.kind == "dynamic_hash":
            key = str(expression.get("hash"))
            values = context.dynamic_values or {}
            return values.get(key)
        return None

