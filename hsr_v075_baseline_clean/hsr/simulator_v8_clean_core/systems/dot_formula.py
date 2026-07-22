from __future__ import annotations

from dataclasses import dataclass, field

from ..core.model import BattleState, JSONValue
from ..dynamic_key_hash import tbgd_dynamic_key_hash
from ..rules.evaluator import NumericEvaluationContext, NumericEvaluationResult, RuleEvaluator
from ..rules.expression_ir import numeric_dynamic_hashes
from ..rules.ir import StatusDamageEmissionIR
from .dynamic_values import binding_source_from_status_detail, binding_source_from_store, store_from_state
from .scaling_basis import resolve_scaling_basis
from .unit_stats import effective_unit_stat


@dataclass(frozen=True)
class DotFormulaInput:
    state: BattleState
    caster_id: str
    target_id: str
    status_detail: dict[str, JSONValue]
    emission: StatusDamageEmissionIR
    source_trace: dict[str, JSONValue] = field(default_factory=dict)
    event_payload: dict[str, JSONValue] = field(default_factory=dict)


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
        if isinstance(value, dict) and value.get("ok") is True:
            return value
        value = self.numeric_evaluations.get("damage_percentage")
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

        binding_sources, event_binding_reason = _dot_binding_sources(
            formula_input.state,
            formula_input.status_detail,
            formula_input.emission,
            formula_input.event_payload,
        )
        if event_binding_reason:
            return _blocked(event_binding_reason, emission.source.to_json())
        context = NumericEvaluationContext(
            binding_sources=binding_sources,
            source_trace={
                **formula_input.source_trace,
                "status_damage_source": emission.source.to_json(),
                "status_instance_source": _json_dict(formula_input.status_detail.get("source_trace")),
            },
        )
        evaluator = RuleEvaluator()
        damage_value_expr = _json_dict(scaling.get("damage_value"))
        base_eval = evaluator.evaluate_numeric(damage_value_expr, context)
        percentage_expr = _json_dict(scaling.get("damage_percentage"))
        numeric_evaluations: dict[str, JSONValue] = {}
        terms: list[dict[str, JSONValue]] = []
        base_damage = 0.0
        damage_value_admitted = _expr_admitted(damage_value_expr)
        damage_percentage_admitted = _expr_admitted(percentage_expr)
        if not damage_value_admitted and not damage_percentage_admitted:
            return _blocked_with_eval(
                base_eval.blocked_reason or "dot_base_damage_expression_missing",
                emission.source.to_json(),
                base_eval,
            )

        if damage_value_admitted:
            numeric_evaluations["damage_value"] = base_eval.to_json()
            if not base_eval.ok or base_eval.value is None:
                return _blocked_with_eval(
                    base_eval.blocked_reason
                    or "dot_damage_value_numeric_evaluation_failed",
                    emission.source.to_json(),
                    base_eval,
                )
            fixed_damage = max(0.0, float(base_eval.value))
            base_damage += fixed_damage
            terms.append(
                {
                    "bucket": "base_damage",
                    "key": "DamageValue",
                    "applied": True,
                    "value": fixed_damage,
                    "source": "AttackProperty.DamageValue",
                    "numeric_evaluation": base_eval.to_json(),
                }
            )
        else:
            terms.append(
                {
                    "bucket": "base_damage",
                    "key": "DamageValue",
                    "applied": False,
                    "skipped_reason": "damage_value_missing",
                    "source": "AttackProperty.DamageValue",
                }
            )

        if damage_percentage_admitted:
            percentage_eval = evaluator.evaluate_numeric(percentage_expr, context)
            numeric_evaluations["damage_percentage"] = percentage_eval.to_json()
            if not percentage_eval.ok or percentage_eval.value is None:
                return _blocked_with_evaluations(
                    percentage_eval.blocked_reason or "dot_damage_percentage_numeric_evaluation_failed",
                    emission.source.to_json(),
                    numeric_evaluations,
            )
            basis_expr = _dot_damage_percentage_basis_expr(scaling, formula_input.status_detail)
            if basis_expr.get("kind") == "missing" and basis_expr.get("reason"):
                return _blocked_with_evaluations(
                    str(basis_expr.get("reason")),
                    emission.source.to_json(),
                    numeric_evaluations,
                )
            basis_result = resolve_scaling_basis(
                formula_input.state,
                attacker_id=formula_input.caster_id,
                target_id=formula_input.target_id,
                basis=basis_expr,
                source_trace={
                    **formula_input.source_trace,
                    "status_damage_source": emission.source.to_json(),
                    "damage_percentage": percentage_expr,
                },
            )
            numeric_evaluations["damage_percentage_basis"] = basis_result.to_json()
            if not basis_result.ok or basis_result.value is None:
                return _blocked_with_evaluations(
                    basis_result.blocked_reason or "dot_damage_percentage_basis_not_admitted",
                    emission.source.to_json(),
                    numeric_evaluations,
                )
            percentage_damage = max(
                0.0,
                float(basis_result.value) * float(percentage_eval.value),
            )
            base_damage += percentage_damage
            terms.append(
                {
                    "bucket": "base_damage",
                    "key": "DamagePercentage",
                    "applied": True,
                    "base_stat": basis_result.stat,
                    "base_value": basis_result.value,
                    "ratio": float(percentage_eval.value),
                    "value": percentage_damage,
                    "source": "AttackProperty.DamagePercentage",
                    "numeric_evaluation": percentage_eval.to_json(),
                    "basis_result": basis_result.to_json(),
                }
            )
        else:
            terms.append(
                {
                    "bucket": "base_damage",
                    "key": "DamagePercentage",
                    "applied": False,
                    "skipped_reason": "damage_percentage_missing",
                    "source": "AttackProperty.DamagePercentage",
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
            effective_defense = effective_unit_stat(caster, "defense")
            extra_damage = max(0.0, effective_defense.value * float(extra_eval.value))
            terms.append(
                {
                    "bucket": "extra_damage",
                    "key": "ExtraFormulaType.ByDefence",
                    "applied": True,
                    "base_stat": "caster.defense",
                    "base_value": effective_defense.value,
                    "effective_stat": effective_defense.to_json(),
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


def _dot_binding_sources(
    state: BattleState,
    detail: dict[str, JSONValue],
    emission: StatusDamageEmissionIR,
    event_payload: dict[str, JSONValue],
) -> tuple[tuple[dict[str, JSONValue], ...], str]:
    sources: list[dict[str, JSONValue]] = []
    status_source = binding_source_from_status_detail(detail, detail.get("dynamic_values"))
    if status_source is not None:
        sources.append(status_source)
    store_source = binding_source_from_store(store_from_state(state))
    if store_source.get("entries"):
        sources.append(store_source)
    custom_source, reason = _custom_event_binding_source(
        emission,
        event_payload,
        tuple(sources),
        status_detail=detail,
        owner_id=str(detail.get("owner_id") or ""),
    )
    if reason:
        return tuple(sources), reason
    if custom_source:
        override_hash = custom_source.get("override_hash")
        if isinstance(override_hash, str) and override_hash:
            sources = [
                _binding_source_without_hash(source, override_hash)
                for source in sources
            ]
        sources.append(custom_source)
    return tuple(sources), ""


def _custom_event_binding_source(
    emission: StatusDamageEmissionIR,
    event_payload: dict[str, JSONValue],
    base_sources: tuple[dict[str, JSONValue], ...],
    *,
    status_detail: dict[str, JSONValue],
    owner_id: str,
) -> tuple[dict[str, JSONValue], str]:
    if event_payload.get("runtime_event_type") != "custom.event":
        return {}, ""
    dynamic_key = event_payload.get("custom_event_dynamic_key")
    value = event_payload.get("custom_event_value")
    producer_source = event_payload.get("producer_effect_source")
    if not isinstance(dynamic_key, str) or not dynamic_key:
        return {}, "custom_event_dynamic_key_missing"
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return {}, "custom_event_value_missing"
    if not isinstance(producer_source, dict) or not producer_source:
        return {}, "custom_event_producer_source_missing"
    scaling = emission.scaling_expr
    hashes = tuple(
        sorted(
            {
                str(hash_key)
                for field_name in (
                    "damage_value",
                    "damage_percentage",
                    "extra_damage_percentage",
                )
                for hash_key in numeric_dynamic_hashes(
                    scaling.get(field_name)
                    if isinstance(scaling, dict)
                    else None
                )
            }
        )
    )
    if not hashes:
        return {}, "custom_event_consumer_dynamic_hash_missing"
    named_hashes = _status_dynamic_key_hashes(status_detail, dynamic_key)
    matching_named_hashes = tuple(
        hash_key for hash_key in named_hashes if hash_key in hashes
    )
    if len(matching_named_hashes) == 1:
        hash_key = matching_named_hashes[0]
        binding_rule = "status_definition_dynamic_key_override"
    else:
        evaluator = RuleEvaluator()
        unresolved: list[str] = []
        for hash_key in hashes:
            probe = evaluator.evaluate_numeric(
                {"kind": "dynamic_hash", "hash": hash_key},
                NumericEvaluationContext(binding_sources=base_sources),
            )
            if probe.ok:
                continue
            if probe.blocked_reason == f"dynamic_hash_unbound:{hash_key}":
                unresolved.append(hash_key)
                continue
            return {}, probe.blocked_reason or f"custom_event_existing_binding_invalid:{hash_key}"
        if len(unresolved) != 1:
            definition_bindings = (
                status_detail.get("dynamic_values", {}).get(
                    "__definition_bindings", {}
                )
                if isinstance(status_detail.get("dynamic_values"), dict)
                else {}
            )
            definition_hashes = (
                definition_bindings.get("by_hash", {})
                if isinstance(definition_bindings, dict)
                else {}
            )
            return {}, (
                f"custom_event_consumer_hash_not_unique:{len(unresolved)}:"
                f"dynamic_key_hashes={','.join(named_hashes)}:"
                f"definition_hash_count={len(definition_hashes) if isinstance(definition_hashes, dict) else 0}"
            )
        hash_key = unresolved[0]
        binding_rule = "unique_unbound_consumer_dynamic_hash"
    event_id = str(event_payload.get("runtime_event_id") or "")
    if not event_id:
        return {}, "custom_event_identity_missing"
    entry_key = f"custom_event:{event_id}:{hash_key}"
    entry = {
        "scope": "modifier_custom_event",
        "owner_id": owner_id,
        "name": dynamic_key,
        "hash": hash_key,
        "value": float(value),
        "source_trace": {
            "event_id": event_id,
            "producer_effect_id": event_payload.get("producer_effect_id"),
            "producer_effect_source": producer_source,
            "consumer_status_damage_source": emission.source.to_json(),
            "binding_rule": binding_rule,
        },
    }
    return {
        "source_type": "modifier_custom_event",
        "entries": {entry_key: entry},
        "by_hash": {hash_key: [entry_key]},
        "by_name": {dynamic_key: [entry_key]},
        "override_hash": hash_key,
    }, ""


def _status_dynamic_key_hashes(
    status_detail: dict[str, JSONValue],
    dynamic_key: str,
) -> tuple[str, ...]:
    dynamic_values = status_detail.get("dynamic_values")
    definition_bindings = (
        dynamic_values.get("__definition_bindings")
        if isinstance(dynamic_values, dict)
        else None
    )
    by_name = (
        definition_bindings.get("by_name")
        if isinstance(definition_bindings, dict)
        else None
    )
    binding = by_name.get(dynamic_key) if isinstance(by_name, dict) else None
    hashes = binding.get("hashes") if isinstance(binding, dict) else None
    direct = (
        tuple(dict.fromkeys(str(value) for value in hashes if str(value)))
        if isinstance(hashes, (list, tuple))
        else ()
    )
    if direct:
        return direct
    by_hash = (
        definition_bindings.get("by_hash")
        if isinstance(definition_bindings, dict)
        else None
    )
    computed_hash = str(tbgd_dynamic_key_hash(dynamic_key))
    computed_binding = (
        by_hash.get(computed_hash) if isinstance(by_hash, dict) else None
    )
    read_info = (
        computed_binding.get("read_info")
        if isinstance(computed_binding, dict)
        else None
    )
    if (
        isinstance(read_info, dict)
        and str(read_info.get("Type") or "") == "None"
    ):
        return (computed_hash,)
    return ()


def _binding_source_without_hash(
    source: dict[str, JSONValue],
    hash_key: str,
) -> dict[str, JSONValue]:
    by_hash = source.get("by_hash")
    entry_keys = (
        tuple(str(key) for key in by_hash.get(hash_key, ()))
        if isinstance(by_hash, dict)
        and isinstance(by_hash.get(hash_key), (list, tuple))
        else ()
    )
    if not entry_keys:
        return source
    removed = set(entry_keys)
    entries = source.get("entries")
    by_name = source.get("by_name")
    return {
        **source,
        "entries": {
            key: value
            for key, value in entries.items()
            if key not in removed
        }
        if isinstance(entries, dict)
        else {},
        "by_hash": {
            key: value
            for key, value in by_hash.items()
            if key != hash_key
        },
        "by_name": {
            key: [item for item in value if str(item) not in removed]
            for key, value in by_name.items()
            if isinstance(value, (list, tuple))
            and any(str(item) not in removed for item in value)
        }
        if isinstance(by_name, dict)
        else {},
    }


def _dot_damage_percentage_basis_expr(
    scaling: dict[str, JSONValue],
    status_detail: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    basis_expr = _json_dict(scaling.get("damage_percentage_basis"))
    if basis_expr.get("kind") != "status_formula_binding":
        return basis_expr
    for binding in _status_formula_bindings(status_detail):
        if binding.get("formula_role") != "dot_damage":
            continue
        if binding.get("coverage_status") != "executable":
            continue
        expr = _json_dict(binding.get("scaling_basis_expr"))
        if not expr:
            continue
        source_trace = _json_dict(expr.get("source_trace"))
        expr = dict(expr)
        expr["source_trace"] = {
            **source_trace,
            "status_formula_binding": binding,
            "status_instance_id": str(status_detail.get("instance_id") or ""),
        }
        return expr
    return {
        "kind": "missing",
        "supported": False,
        "reason": "dot_status_formula_binding_missing",
        "source_trace": {
            "status_instance_id": str(status_detail.get("instance_id") or ""),
            "requested_basis": basis_expr,
        },
    }


def _status_formula_bindings(status_detail: dict[str, JSONValue]) -> tuple[dict[str, JSONValue], ...]:
    bindings = status_detail.get("formula_bindings")
    if not isinstance(bindings, list):
        return ()
    return tuple(item for item in bindings if isinstance(item, dict))


def _expr_admitted(expression: dict[str, JSONValue]) -> bool:
    return (
        expression.get("kind") in {"fixed", "dynamic_hash", "program"}
        and expression.get("supported") is True
    )


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


def _blocked_with_evaluations(
    reason: str,
    source_trace: dict[str, JSONValue],
    evaluations: dict[str, JSONValue],
) -> DotFormulaResult:
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
