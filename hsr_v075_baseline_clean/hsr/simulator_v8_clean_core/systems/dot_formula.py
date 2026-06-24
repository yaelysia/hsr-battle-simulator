from __future__ import annotations

from dataclasses import dataclass, field

from ..core.model import BattleState, JSONValue
from ..rules.evaluator import NumericEvaluationContext, NumericEvaluationResult, RuleEvaluator
from ..rules.ir import StatusDamageEmissionIR
from .dynamic_values import binding_source_from_status_detail, binding_source_from_store, store_from_state


@dataclass(frozen=True)
class DotFormulaInput:
    state: BattleState
    caster_id: str
    target_id: str
    status_detail: dict[str, JSONValue]
    emission: StatusDamageEmissionIR
    source_trace: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class DotFormulaResult:
    ok: bool
    base_damage: float
    extra_damage: float
    final_damage: float
    numeric_evaluations: dict[str, JSONValue]
    dot_ledger: dict[str, JSONValue]
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "base_damage": self.base_damage,
            "extra_damage": self.extra_damage,
            "final_damage": self.final_damage,
            "numeric_evaluations": self.numeric_evaluations,
            "dot_ledger": self.dot_ledger,
            "blocked_reason": self.blocked_reason,
        }

    @property
    def primary_numeric_evaluation(self) -> dict[str, JSONValue]:
        value = self.numeric_evaluations.get("damage_value")
        return value if isinstance(value, dict) else {}


class DotFormula:
    """Conservative ordinary DoT formula for admitted StatusDamageEmissionIR."""

    def calculate(self, formula_input: DotFormulaInput) -> DotFormulaResult:
        emission = formula_input.emission
        scaling = emission.scaling_expr
        if scaling.get("kind") != "dot_attack_property":
            return _blocked("dot_scaling_kind_not_admitted", emission.source.to_json())

        caster = formula_input.state.units.get(formula_input.caster_id)
        target = formula_input.state.units.get(formula_input.target_id)
        if caster is None or target is None:
            return _blocked("dot_actor_or_target_missing", emission.source.to_json())

        context = NumericEvaluationContext(
            binding_sources=_dot_binding_sources(formula_input.state, formula_input.status_detail),
            source_trace={
                **formula_input.source_trace,
                "status_damage_source": emission.source.to_json(),
                "status_instance_source": _json_dict(formula_input.status_detail.get("source_trace")),
            },
        )
        evaluator = RuleEvaluator()
        damage_value_expr = _json_dict(scaling.get("damage_value"))
        base_eval = evaluator.evaluate_numeric(damage_value_expr, context)
        if not base_eval.ok or base_eval.value is None:
            if _expr_admitted(damage_value_expr):
                return _blocked_with_eval(
                    base_eval.blocked_reason or "dot_damage_value_numeric_evaluation_failed",
                    emission.source.to_json(),
                    base_eval,
                )
            percentage_expr = _json_dict(scaling.get("damage_percentage"))
            if _expr_admitted(percentage_expr):
                return _blocked_with_eval(
                    "dot_damage_percentage_base_not_admitted",
                    emission.source.to_json(),
                    base_eval,
                    percentage_expr=percentage_expr,
                )
            return _blocked_with_eval(
                base_eval.blocked_reason or "dot_damage_value_numeric_evaluation_failed",
                emission.source.to_json(),
                base_eval,
            )

        base_damage = max(0.0, float(base_eval.value))
        numeric_evaluations: dict[str, JSONValue] = {"damage_value": base_eval.to_json()}
        terms: list[dict[str, JSONValue]] = [
            {
                "bucket": "base_damage",
                "key": "DamageValue",
                "applied": True,
                "value": base_damage,
                "source": "AttackProperty.DamageValue",
                "numeric_evaluation": base_eval.to_json(),
            }
        ]

        percentage_expr = _json_dict(scaling.get("damage_percentage"))
        if _expr_admitted(percentage_expr):
            terms.append(
                {
                    "bucket": "base_damage",
                    "key": "DamagePercentage",
                    "applied": False,
                    "skipped_reason": "damage_percentage_base_not_admitted",
                    "source": "AttackProperty.DamagePercentage",
                    "expression": percentage_expr,
                }
            )

        extra_damage = 0.0
        extra_formula_type = str(scaling.get("extra_formula_type") or "")
        extra_expr = _json_dict(scaling.get("extra_damage_percentage"))
        if extra_formula_type:
            if extra_formula_type != "ByDefence":
                return _blocked_with_eval(
                    f"dot_extra_formula_type_not_admitted:{extra_formula_type}",
                    emission.source.to_json(),
                    base_eval,
                )
            extra_eval = evaluator.evaluate_numeric(extra_expr, context)
            numeric_evaluations["extra_damage_percentage"] = extra_eval.to_json()
            if not extra_eval.ok or extra_eval.value is None:
                return _blocked_with_eval(
                    extra_eval.blocked_reason or "dot_extra_damage_percentage_numeric_evaluation_failed",
                    emission.source.to_json(),
                    base_eval,
                    extra_eval=extra_eval,
                )
            extra_damage = max(0.0, float(caster.defense) * float(extra_eval.value))
            terms.append(
                {
                    "bucket": "extra_damage",
                    "key": "ExtraFormulaType.ByDefence",
                    "applied": True,
                    "base_stat": "caster.defense",
                    "base_value": float(caster.defense),
                    "ratio": float(extra_eval.value),
                    "value": extra_damage,
                    "source": "AttackProperty.ExtraDamagePercentage",
                    "numeric_evaluation": extra_eval.to_json(),
                }
            )
        else:
            terms.append(
                {
                    "bucket": "extra_damage",
                    "key": "ExtraFormulaType",
                    "applied": False,
                    "skipped_reason": "extra_formula_missing",
                }
            )

        final_damage = max(0.0, base_damage + extra_damage)
        return DotFormulaResult(
            ok=True,
            base_damage=base_damage,
            extra_damage=extra_damage,
            final_damage=final_damage,
            numeric_evaluations=numeric_evaluations,
            dot_ledger={
                "formula_family": "dot",
                "terms": terms,
                "applied_terms": [term for term in terms if term.get("applied") is True],
                "skipped_terms": [term for term in terms if term.get("applied") is False],
            },
        )


def _dot_binding_sources(state: BattleState, detail: dict[str, JSONValue]) -> tuple[dict[str, JSONValue], ...]:
    sources: list[dict[str, JSONValue]] = []
    status_source = binding_source_from_status_detail(detail, detail.get("dynamic_values"))
    if status_source is not None:
        sources.append(status_source)
    store_source = binding_source_from_store(store_from_state(state))
    if store_source.get("entries"):
        sources.append(store_source)
    return tuple(sources)


def _expr_admitted(expression: dict[str, JSONValue]) -> bool:
    return expression.get("kind") in {"fixed", "dynamic_hash", "postfix_expr"} and expression.get("supported") is True


def _blocked(reason: str, source_trace: dict[str, JSONValue]) -> DotFormulaResult:
    return DotFormulaResult(
        ok=False,
        base_damage=0.0,
        extra_damage=0.0,
        final_damage=0.0,
        numeric_evaluations={},
        dot_ledger={"formula_family": "dot", "terms": [], "applied_terms": [], "skipped_terms": []},
        blocked_reason=reason,
    )


def _blocked_with_eval(
    reason: str,
    source_trace: dict[str, JSONValue],
    base_eval: NumericEvaluationResult,
    *,
    extra_eval: NumericEvaluationResult | None = None,
    percentage_expr: dict[str, JSONValue] | None = None,
) -> DotFormulaResult:
    evaluations: dict[str, JSONValue] = {"damage_value": base_eval.to_json()}
    if extra_eval is not None:
        evaluations["extra_damage_percentage"] = extra_eval.to_json()
    if percentage_expr is not None:
        evaluations["damage_percentage"] = {"ok": False, "expression": percentage_expr, "blocked_reason": reason}
    return DotFormulaResult(
        ok=False,
        base_damage=0.0,
        extra_damage=0.0,
        final_damage=0.0,
        numeric_evaluations=evaluations,
        dot_ledger={
            "formula_family": "dot",
            "terms": [],
            "applied_terms": [],
            "skipped_terms": [{"bucket": "dot", "key": "formula", "skipped_reason": reason}],
            "source_trace": source_trace,
        },
        blocked_reason=reason,
    )


def _json_dict(value: object) -> dict[str, JSONValue]:
    return value if isinstance(value, dict) else {}
