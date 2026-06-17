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
    binding_sources: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class NumericEvaluationContext:
    dynamic_values: dict[str, float] | None = None
    binding_sources: tuple[dict[str, Any], ...] = ()
    source_trace: dict[str, Any] | None = None


@dataclass(frozen=True)
class NumericEvaluationResult:
    ok: bool
    value: float | None
    expression_kind: str
    bindings: dict[str, Any]
    source_trace: dict[str, Any]
    blocked_reason: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "value": self.value,
            "expression_kind": self.expression_kind,
            "bindings": self.bindings,
            "source_trace": self.source_trace,
            "blocked_reason": self.blocked_reason,
        }


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
            result = self.evaluate_numeric(
                {"kind": "fixed", "value": expression.get("Value")},
                NumericEvaluationContext(
                    dynamic_values=context.dynamic_values,
                    binding_sources=context.binding_sources,
                    source_trace=formula.source.to_json(),
                ),
            )
            return result.value if result.ok else None
        if formula.kind == "dynamic_hash":
            result = self.evaluate_numeric(
                {"kind": "dynamic_hash", "hash": expression.get("hash")},
                NumericEvaluationContext(
                    dynamic_values=context.dynamic_values,
                    binding_sources=context.binding_sources,
                    source_trace=formula.source.to_json(),
                ),
            )
            return result.value if result.ok else None
        return None

    def evaluate_numeric(self, expression: Any, context: NumericEvaluationContext | None = None) -> NumericEvaluationResult:
        context = context or NumericEvaluationContext()
        source_trace = dict(context.source_trace or {})
        if isinstance(expression, (int, float)):
            return NumericEvaluationResult(
                ok=True,
                value=float(expression),
                expression_kind="fixed",
                bindings={},
                source_trace=source_trace,
            )
        if expression is None:
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="missing",
                bindings={},
                source_trace=source_trace,
                blocked_reason="missing",
            )
        if not isinstance(expression, dict):
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="unsupported",
                bindings={"raw": expression},
                source_trace=source_trace,
                blocked_reason="unsupported_numeric_expression",
            )

        kind = str(expression.get("kind") or "")
        if kind == "fixed" and isinstance(expression.get("value"), (int, float)):
            return NumericEvaluationResult(
                ok=True,
                value=float(expression["value"]),
                expression_kind="fixed",
                bindings={},
                source_trace=source_trace,
            )
        if kind == "missing":
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="missing",
                bindings={},
                source_trace=source_trace,
                blocked_reason=str(expression.get("reason") or "missing"),
            )
        if kind == "dynamic_hash":
            return _evaluate_dynamic_hash(expression, context, source_trace)
        if kind == "postfix_expr":
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="postfix_expr",
                bindings={"raw": expression.get("raw")},
                source_trace=source_trace,
                blocked_reason=str(expression.get("reason") or "unsupported_postfix_expr"),
            )
        if kind == "unsupported":
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="unsupported",
                bindings={"raw": expression.get("raw")},
                source_trace=source_trace,
                blocked_reason=str(expression.get("reason") or "unsupported_numeric_expression"),
            )

        fixed = expression.get("FixedValue")
        if isinstance(fixed, dict) and isinstance(fixed.get("Value"), (int, float)):
            return self.evaluate_numeric(
                {"kind": "fixed", "value": fixed["Value"]},
                context,
            )
        if isinstance(expression.get("Value"), (int, float)):
            return self.evaluate_numeric(
                {"kind": "fixed", "value": expression["Value"]},
                context,
            )
        postfix = expression.get("PostfixExpr")
        if isinstance(postfix, dict):
            hashes = postfix.get("DynamicHashes")
            fixed_values = postfix.get("FixedValues")
            opcodes = postfix.get("OpCodes")
            if (
                opcodes == "AQAR"
                and isinstance(hashes, list)
                and len(hashes) == 1
                and isinstance(hashes[0], int)
                and (not fixed_values)
            ):
                return _evaluate_dynamic_hash(
                    {"kind": "dynamic_hash", "hash": int(hashes[0]), "raw": expression},
                    context,
                    source_trace,
                )
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="postfix_expr",
                bindings={"raw": expression},
                source_trace=source_trace,
                blocked_reason="unsupported_postfix_expr",
            )

        return NumericEvaluationResult(
            ok=False,
            value=None,
            expression_kind=kind or "unsupported",
            bindings={"raw": expression},
            source_trace=source_trace,
            blocked_reason="unsupported_numeric_expression",
        )


def _evaluate_dynamic_hash(
    expression: dict[str, Any],
    context: NumericEvaluationContext,
    source_trace: dict[str, Any],
) -> NumericEvaluationResult:
    hash_value = expression.get("hash")
    key = str(hash_value)
    sources_checked: list[dict[str, Any]] = []
    values = context.dynamic_values or {}
    if key in values and isinstance(values[key], (int, float)):
        return NumericEvaluationResult(
            ok=True,
            value=float(values[key]),
            expression_kind="dynamic_hash",
            bindings={
                "hash": hash_value,
                "key": key,
                "value": float(values[key]),
                "source_type": "explicit_dynamic_values",
            },
            source_trace=source_trace,
        )
    sources_checked.append({"source_type": "explicit_dynamic_values", "hit": False})
    for index, source in enumerate(context.binding_sources):
        value, binding = _lookup_binding_source(source, key)
        sources_checked.append(
            {
                "source_type": str(source.get("source_type") or f"binding_source:{index}"),
                "hit": value is not None,
            }
        )
        if value is not None:
            return NumericEvaluationResult(
                ok=True,
                value=value,
                expression_kind="dynamic_hash",
                bindings={"hash": hash_value, "key": key, "value": value, **binding},
                source_trace=source_trace,
            )
    return NumericEvaluationResult(
        ok=False,
        value=None,
        expression_kind="dynamic_hash",
        bindings={"hash": hash_value, "key": key, "sources_checked": sources_checked},
        source_trace=source_trace,
        blocked_reason=f"dynamic_hash_unbound:{key}",
    )


def _lookup_binding_source(source: dict[str, Any], key: str) -> tuple[float | None, dict[str, Any]]:
    entries = source.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    by_hash = source.get("by_hash")
    value, entry_key, entry = _lookup_index(entries, by_hash, key)
    if value is not None:
        return value, _binding_metadata(source, entry_key, entry, matched_by="hash")
    by_name = source.get("by_name")
    value, entry_key, entry = _lookup_index(entries, by_name, key)
    if value is not None:
        return value, _binding_metadata(source, entry_key, entry, matched_by="name")
    values = source.get("values")
    if isinstance(values, dict) and isinstance(values.get(key), (int, float)):
        return float(values[key]), {
            "source_type": str(source.get("source_type") or "binding_source"),
            "matched_by": "values",
        }
    if isinstance(source.get(key), (int, float)):
        return float(source[key]), {
            "source_type": str(source.get("source_type") or "binding_source"),
            "matched_by": "direct_key",
        }
    return None, {}


def _lookup_index(
    entries: dict[str, Any],
    index: object,
    key: str,
) -> tuple[float | None, str | None, dict[str, Any] | None]:
    if not isinstance(index, dict) or key not in index:
        return None, None, None
    indexed = index[key]
    if isinstance(indexed, (int, float)):
        return float(indexed), None, None
    if isinstance(indexed, dict) and isinstance(indexed.get("value"), (int, float)):
        return float(indexed["value"]), None, indexed
    keys = indexed if isinstance(indexed, list) else [indexed]
    for entry_key in keys:
        if not isinstance(entry_key, str):
            continue
        entry = entries.get(entry_key)
        if isinstance(entry, dict) and isinstance(entry.get("value"), (int, float)):
            return float(entry["value"]), entry_key, entry
    return None, None, None


def _binding_metadata(
    source: dict[str, Any],
    entry_key: str | None,
    entry: dict[str, Any] | None,
    *,
    matched_by: str,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source_type": str(source.get("source_type") or "binding_source"),
        "matched_by": matched_by,
    }
    if entry_key is not None:
        metadata["entry_key"] = entry_key
    if entry is not None:
        metadata["entry"] = entry
    return metadata
