from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable


RuleCallback = Callable[..., Any]


@dataclass
class RuleBook:
    """Canonical runtime rule bundle consumed by combat core.

    The rule book stores simulator-facing IR/model-pack data. Raw TBGD fields
    are compiler inputs and must not be placed here.
    """

    actions: dict[str, dict[str, Any]] = field(default_factory=dict)
    status_definitions: dict[str, dict[str, Any]] = field(default_factory=dict)
    triggers: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_case(cls, case: dict[str, Any]) -> "RuleBook":
        units = case.get("units", {}) if isinstance(case.get("units", {}), dict) else {}
        actions: dict[str, dict[str, Any]] = {}
        status_definitions: dict[str, dict[str, Any]] = {}
        for unit_id, unit in units.items():
            if not isinstance(unit, dict):
                continue
            for action_id, action in (unit.get("actions") or {}).items():
                if isinstance(action, dict):
                    actions[f"{unit_id}.{action_id}"] = deepcopy(action)
            for status_id, status in (unit.get("status_effects") or {}).items():
                if isinstance(status, dict):
                    status_definitions[f"{unit_id}.{status_id}"] = deepcopy(status)
        return cls(
            actions=actions,
            status_definitions=status_definitions,
            triggers=deepcopy(case.get("triggers", [])),
            metadata={
                "source": "model_pack_or_compiled_case",
                "action_count": len(actions),
                "status_definition_count": len(status_definitions),
            },
        )


class RuleEvaluator:
    """Explicit rule-query surface for combat core runtime."""

    def __init__(self, rule_book: RuleBook, callbacks: dict[str, RuleCallback] | None = None) -> None:
        self.rule_book = rule_book
        self.callbacks = dict(callbacks or {})
        self.coverage_records: list[dict[str, Any]] = []

    def _call(self, name: str, *args: Any, fallback: Any = None, **kwargs: Any) -> Any:
        callback = self.callbacks.get(name)
        if callback is None:
            self.coverage_records.append({"query": name, "status": "unsupported", "reason": "missing_callback"})
            return fallback
        self.coverage_records.append({"query": name, "status": "legacy_callback", "handler": name})
        return callback(*args, **kwargs)

    def eval_condition(self, expression: Any, ctx: dict[str, Any]) -> bool:
        return bool(self._call("eval_condition", expression, ctx, fallback=bool(expression)))

    def numeric_expr(self, expression: Any, ctx: dict[str, Any], *, default: float = 0.0) -> float:
        return float(self._call("resolve_numeric_expr", expression, ctx, fallback=default, default=default))

    def dynamic_element(self, expression: Any, ctx: dict[str, Any]) -> str:
        return str(self._call("resolve_dynamic_element", expression, ctx, fallback=expression))

    def contextual_stat(self, unit: Any, name: str, ctx: dict[str, Any]) -> float:
        return float(self._call("contextual_stat", unit, name, ctx, fallback=0.0))

    def applicable_status_modifiers(self, unit: Any, ctx: dict[str, Any]) -> list[tuple[Any, dict[str, Any]]]:
        return list(self._call("applicable_status_modifiers", unit, ctx, fallback=[]))

    def target_reference(self, spec: Any, ctx: dict[str, Any], *, default: str = "actor") -> list[str]:
        return list(self._call("resolve_effect_targets", {"target": spec}, ctx, fallback=[], default=default))

    def coverage_matrix(self) -> dict[str, Any]:
        summary: dict[str, int] = {}
        for row in self.coverage_records:
            status = str(row.get("status") or "unknown")
            summary[status] = summary.get(status, 0) + 1
        return {
            "encoding": "hsr.clean_core.rule_coverage.v1",
            "summary": summary,
            "records": deepcopy(self.coverage_records),
            "rule_book": deepcopy(self.rule_book.metadata),
        }
