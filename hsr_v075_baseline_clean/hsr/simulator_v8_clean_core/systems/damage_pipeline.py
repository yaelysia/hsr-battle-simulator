from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..core.audit_policy import diagnostic_json

from ..core.model import BattleState, JSONValue, UnitState
from ..rules.ir import FormulaIR
from ..rules.engine_rule_registry import (
    EngineRuleRegistry,
    build_engine_rule_registry,
    evaluate_defense_multiplier,
    evaluate_resistance_multiplier,
)
from .damage_formula import damage_reduction_residuals, status_modifier_terms, toughness_state_multiplier
from .unit_stats import effective_unit_stat
from .elation import ElationDamageContext
from .toughness_state import read_toughness_segments


DAMAGE_STAGE_SCHEMA_VERSION = "damage_stage_pipeline_v1"
DAMAGE_STAGE_ORDER = (
    "critical",
    "damage_bonus",
    "break_bonus",
    "defense",
    "resistance",
    "damage_taken",
    "damage_reduction",
    "toughness_state",
    "toughness_bonus",
)

DAMAGE_FAMILY_STAGE_MATRIX: dict[str, tuple[str, ...]] = {
    "elation": ("critical", "elation_bonus", "punchline", "merrymake", "defense", "resistance", "damage_taken", "damage_reduction", "toughness_state"),
    "additional": ("critical", "damage_bonus", "defense", "resistance", "damage_taken", "damage_reduction", "toughness_state"),
    "dot": ("damage_bonus", "defense", "resistance", "damage_taken", "damage_reduction", "toughness_state"),
    "break": ("break_bonus", "defense", "resistance", "damage_taken", "damage_reduction"),
    "super_break": ("break_bonus", "defense", "resistance", "damage_taken", "damage_reduction"),
    "true_damage": (),
    "hp_loss": (),
    "toughness": ("toughness_bonus",),
}


@dataclass(frozen=True)
class DamageStageBucket:
    stage: str
    applicable: bool
    multiplier: float
    applied_terms: tuple[dict[str, JSONValue], ...] = ()
    skipped_terms: tuple[dict[str, JSONValue], ...] = ()
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "stage": self.stage,
            "applicable": self.applicable,
            "multiplier": self.multiplier,
            "applied_terms": list(self.applied_terms),
            "skipped_terms": list(self.skipped_terms),
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class DamagePipelineResult:
    ok: bool
    family: str
    attacker_id: str
    target_id: str
    producer_base_amount: float
    final_amount: float
    stage_buckets: tuple[DamageStageBucket, ...]
    source_trace: dict[str, JSONValue]
    input_state_event_index: int
    blocked_reason: str = ""

    @property
    def applied_terms(self) -> tuple[dict[str, JSONValue], ...]:
        return tuple(term for bucket in self.stage_buckets for term in bucket.applied_terms)

    @property
    def skipped_terms(self) -> tuple[dict[str, JSONValue], ...]:
        return tuple(term for bucket in self.stage_buckets for term in bucket.skipped_terms)

    def to_json(self) -> dict[str, JSONValue]:
        amount = self.producer_base_amount
        stages: list[dict[str, JSONValue]] = []
        for bucket in self.stage_buckets:
            before = amount
            amount = max(0.0, amount * bucket.multiplier)
            stages.append(
                {
                    "stage": bucket.stage,
                    "applicable": bucket.applicable,
                    "input_amount": before,
                    "multiplier": bucket.multiplier,
                    "output_amount": amount,
                    "bucket": bucket.to_json(),
                }
            )
        return diagnostic_json({
            "schema_version": DAMAGE_STAGE_SCHEMA_VERSION,
            "ok": self.ok,
            "family": self.family,
            "attacker_id": self.attacker_id,
            "target_id": self.target_id,
            "input_state_event_index": self.input_state_event_index,
            "producer_base_amount": self.producer_base_amount,
            "stages": stages,
            "final_amount": self.final_amount,
            "applied_terms": list(self.applied_terms),
            "skipped_terms": list(self.skipped_terms),
            "source_trace": self.source_trace,
            "blocked_reason": self.blocked_reason,
        })


class DamageStagePipeline:
    def __init__(self, engine_rules: EngineRuleRegistry | None = None) -> None:
        self.engine_rules = engine_rules or build_engine_rule_registry()

    def calculate(
        self,
        state: BattleState,
        *,
        family: str,
        attacker_id: str,
        target_id: str,
        producer_base_amount: float,
        element_type: str | None,
        source_trace: dict[str, JSONValue],
        attack_type: str | None = None,
        base_includes_break_bonus: bool = False,
        critical_bucket: DamageStageBucket | None = None,
        elation_context: ElationDamageContext | None = None,
        elation_rule: FormulaIR | None = None,
        modifier_terms: tuple[dict[str, JSONValue], ...] = (),
        pure_damage: bool = False,
    ) -> DamagePipelineResult:
        if family not in DAMAGE_FAMILY_STAGE_MATRIX:
            return DamagePipelineResult(
                False,
                family,
                attacker_id,
                target_id,
                max(0.0, float(producer_base_amount)),
                0.0,
                (),
                source_trace,
                state.event_index,
                "damage_family_stage_matrix_missing",
            )
        actor = state.units.get(attacker_id)
        target = state.units.get(target_id)
        if actor is None or target is None:
            return DamagePipelineResult(
                False,
                family,
                attacker_id,
                target_id,
                max(0.0, float(producer_base_amount)),
                0.0,
                (),
                source_trace,
                state.event_index,
                "damage_pipeline_actor_or_target_missing",
            )
        applicable = set(DAMAGE_FAMILY_STAGE_MATRIX[family])
        if pure_damage:
            # ByPureDamage additional damage is fixed by its final formula and
            # is not affected by ordinary buffs; target-side multipliers
            # (defense/resistance/damage taken) still apply.
            applicable -= {
                "critical",
                "damage_bonus",
                "break_bonus",
                "toughness_bonus",
                "elation_bonus",
                "punchline",
                "merrymake",
            }
        if family == "elation":
            reason = ("elation_damage_context_missing" if type(elation_context) is not ElationDamageContext
                      else elation_context.blocked_reason(actor_id=attacker_id, state=state,
                                                         modifier_terms=modifier_terms))
            if reason:
                raise ValueError(reason)
            if (type(elation_rule) is not FormulaIR or elation_rule.kind != "elation_multiplier_rule"
                    or elation_rule.coverage_status != "executable"):
                raise ValueError("elation_multiplier_rule_not_admitted")
        if "critical" in applicable and (
            critical_bucket is None or critical_bucket.stage != "critical"
            or not critical_bucket.applicable or not math.isfinite(critical_bucket.multiplier)
        ):
            raise ValueError("additional_damage_critical_resolution_required")
        if base_includes_break_bonus:
            if family != "break":
                return DamagePipelineResult(
                    False, family, attacker_id, target_id, max(0.0, float(producer_base_amount)),
                    0.0, (), source_trace, state.event_index, "included_break_bonus_requires_break_family",
                )
            applicable.discard("break_bonus")
        buckets = tuple(
            critical_bucket if stage == "critical" and "critical" in applicable else self._bucket(
                stage,
                applicable,
                actor,
                target,
                element_type,
                family,
                attack_type,
                elation_context,
                elation_rule,
                modifier_terms,
            )
            for stage in (("base", "critical", "damage_bonus", "weakness", "elation_bonus", "punchline", "merrymake",
                           "defense", "resistance", "damage_taken", "damage_reduction", "toughness_state")
                          if family == "elation" else DAMAGE_STAGE_ORDER)
        )
        final = max(0.0, float(producer_base_amount))
        for bucket in buckets:
            final = max(0.0, final * bucket.multiplier)
        return DamagePipelineResult(
            True,
            family,
            attacker_id,
            target_id,
            max(0.0, float(producer_base_amount)),
            final,
            buckets,
            source_trace,
            state.event_index,
        )

    def _bucket(
        self,
        stage: str,
        applicable: set[str],
        actor: UnitState,
        target: UnitState,
        element_type: str | None,
        family: str,
        attack_type: str | None,
        elation_context: ElationDamageContext | None = None,
        elation_rule: FormulaIR | None = None,
        modifier_terms: tuple[dict[str, JSONValue], ...] = (),
    ) -> DamageStageBucket:
        if stage not in applicable:
            return DamageStageBucket(
                stage=stage,
                applicable=False,
                multiplier=1.0,
                skipped_terms=(_skipped(stage, "family_not_applicable", family), *(
                    {**term, "applied": False, "skipped_reason": "family_not_applicable"}
                    for term in modifier_terms if term.get("bucket") == stage
                )),
            )
        if stage in {"elation_bonus", "merrymake"}:
            key = "elation_damage_added_ratio" if stage == "elation_bonus" else "elation_damage_extra_added_ratio"
            value = _resource(actor, key)
            status, terms, skipped = _status_terms(actor, source_type="actor.status", stage="damage_bonus", keys=(key,))
            transient = _transient_terms(modifier_terms, stage, (key,))
            transient_value = sum(float(term["value"]) for term in transient)
            return DamageStageBucket(stage, True, max(0.0, 1.0 + value + status + transient_value),
                applied_terms=(_applied(stage, key, value, "actor.resources"), *terms, *transient), skipped_terms=skipped)
        if stage == "punchline":
            assert elation_context is not None and elation_rule is not None
            parameters = elation_rule.expression
            numerator, offset = parameters.get("punchline_numerator"), parameters.get("punchline_offset")
            if (type(numerator) not in (int, float) or not math.isfinite(numerator) or numerator < 0
                    or type(offset) not in (int, float) or not math.isfinite(offset) or offset <= 0):
                raise ValueError("elation_multiplier_rule_parameters_invalid")
            points = elation_context.points
            return DamageStageBucket(stage, True, 1.0 + numerator * (points / (points + offset)),
                applied_terms=(_applied(stage, "punchline_points", points, "elation_damage_context"),),
                metadata={"context": elation_context.to_json(), "formula_rule": elation_rule.to_json()})
        if stage == "damage_bonus":
            all_bonus = _resource(actor, "damage_added_ratio")
            element_key = f"{element_type}_damage_added_ratio" if element_type else ""
            element_bonus = _resource(actor, element_key) if element_key else 0.0
            specialized_keys: tuple[str, ...] = ()
            if family == "dot" or attack_type == "DOT":
                specialized_keys = ("dot_damage_added_ratio",)
            elif attack_type == "ElationDamage":
                specialized_keys = ("elation_damage_added_ratio",)
            status_keys = (
                ("damage_added_ratio", element_key, *specialized_keys)
                if element_key
                else ("damage_added_ratio", *specialized_keys)
            )
            status_bonus, status_terms, status_skipped = _status_terms(
                actor,
                source_type="actor.status",
                stage=stage,
                keys=status_keys,
            )
            return DamageStageBucket(
                stage,
                True,
                1.0 + all_bonus + element_bonus + status_bonus,
                applied_terms=(
                    _applied(stage, "damage_added_ratio", all_bonus, "actor.resources"),
                    _applied(stage, element_key or "element_damage_added_ratio", element_bonus, "actor.resources"),
                    *status_terms,
                ),
                skipped_terms=status_skipped,
                metadata={"status_bonus": status_bonus},
            )
        if stage == "break_bonus":
            value = _resource(actor, "break_damage_added_ratio")
            status_bonus, status_terms, status_skipped = _status_terms(
                actor,
                source_type="actor.status",
                stage=stage,
                keys=(
                    "break_damage_added_ratio",
                    "break_damage_extra_added_ratio",
                ),
            )
            return DamageStageBucket(
                stage,
                True,
                1.0 + value + status_bonus,
                applied_terms=(
                    _applied(stage, "break_damage_added_ratio", value, "actor.resources"),
                    *status_terms,
                ),
                skipped_terms=status_skipped,
                metadata={"status_bonus": status_bonus},
            )
        if stage == "defense":
            transient = _transient_terms(modifier_terms, stage, ("defender_defence_added_ratio",))
            transient_ratio = sum(float(term["value"]) for term in transient)
            reduction = _resource(target, "def_reduction")
            ignore = _resource(actor, "def_ignore")
            status_reduction, target_status_terms, target_status_skipped = _status_terms(
                target,
                source_type="target.status",
                stage=stage,
                keys=("def_reduction",),
            )
            status_ignore, actor_status_terms, actor_status_skipped = _status_terms(
                actor,
                source_type="actor.status",
                stage=stage,
                keys=("def_ignore",),
            )
            status_defense_ratio, target_attribute_terms, target_attribute_skipped = _status_terms(
                target,
                source_type="target.status",
                stage="attribute",
                keys=("defense_added_ratio",),
            )
            status_defense_flat, target_attribute_flat_terms, target_attribute_flat_skipped = _status_terms(
                target,
                source_type="target.status",
                stage="attribute",
                keys=("defense_delta",),
            )
            defense_stat = effective_unit_stat(target, "defense")
            # Keep the existing hit-context convention separate from committed stat pools.
            effective = max(
                0.0,
                defense_stat.value
                + target.defense
                * (
                    transient_ratio - reduction
                    - status_reduction
                    - ignore
                    - status_ignore
                ),
            )
            multiplier, engine_rule = evaluate_defense_multiplier(
                effective_defense=effective,
                attacker_level=actor.level,
                registry=self.engine_rules,
            )
            return DamageStageBucket(
                stage,
                True,
                multiplier,
                applied_terms=(
                    _applied(stage, "defense", target.defense, "target.stats"),
                    _applied(stage, "def_reduction", reduction, "target.resources"),
                    _applied(stage, "def_ignore", ignore, "actor.resources"),
                    *target_attribute_terms,
                    *target_attribute_flat_terms,
                    *target_status_terms,
                    *actor_status_terms,
                    *transient,
                ),
                skipped_terms=(
                    *target_attribute_skipped,
                    *target_attribute_flat_skipped,
                    *target_status_skipped,
                    *actor_status_skipped,
                ),
                metadata={
                    "effective_defense": effective,
                    "effective_defense_stat": defense_stat.to_json(),
                    "context_ratio_basis": target.defense,
                    "context_ratio_rule": "existing_engine_convention",
                    "actor_level": actor.level,
                    "status_def_reduction": status_reduction,
                    "status_def_ignore": status_ignore,
                    "status_defense_added_ratio": status_defense_ratio,
                    "status_defense_delta": status_defense_flat,
                    "engine_rule": engine_rule.to_json(),
                },
            )
        if stage == "resistance":
            element_key = f"{element_type}_resistance" if element_type else ""
            pen_key = f"{element_type}_res_pen" if element_type else ""
            has_element = bool(element_key and element_key in target.resources)
            resistance = _resource(target, element_key) if has_element else _resource(target, "all_resistance")
            pen = (_resource(actor, pen_key) if pen_key else 0.0) + _resource(actor, "all_res_pen")
            transient = _transient_terms(modifier_terms, stage, (pen_key, "all_res_pen"))
            transient_pen = sum(float(term["value"]) for term in transient)
            status_resistance, status_terms, status_skipped = _status_terms(
                target,
                source_type="target.status",
                stage=stage,
                keys=(f"{element_type}_resistance_delta", "all_resistance_delta")
                if element_type
                else ("all_resistance_delta",),
            )
            skipped = (
                _skipped(stage, "all_resistance", "element_specific_resistance_selected")
                if has_element
                else _skipped(stage, element_key or "element_resistance", "missing_element_resistance_uses_all")
            )
            multiplier, engine_rule = evaluate_resistance_multiplier(
                resistance=resistance + status_resistance,
                penetration=pen + transient_pen,
                registry=self.engine_rules,
            )
            return DamageStageBucket(
                stage,
                True,
                multiplier,
                applied_terms=(
                    _applied(stage, element_key if has_element else "all_resistance", resistance, "target.resources"),
                    _applied(stage, pen_key or "all_res_pen", pen, "actor.resources"),
                    *status_terms,
                    *transient,
                ),
                skipped_terms=(skipped, *status_skipped, *(
                    {**term, "applied": False, "skipped_reason": "different_element_penetration"}
                    for term in modifier_terms if term.get("bucket") == stage and term.get("key") not in {pen_key, "all_res_pen"}
                )),
                metadata={
                    "status_resistance_delta": status_resistance,
                    "engine_rule": engine_rule.to_json(),
                },
            )
        if stage == "damage_taken":
            value = _resource(target, "damage_taken_ratio")
            transient = _transient_terms(modifier_terms, stage, ("damage_taken_ratio",))
            transient_value = sum(float(term["value"]) for term in transient)
            status_value, status_terms, status_skipped = _status_terms(
                target,
                source_type="target.status",
                stage=stage,
                keys=("damage_taken_ratio",),
            )
            return DamageStageBucket(
                stage,
                True,
                1.0 + value + status_value + transient_value,
                applied_terms=(
                    _applied(stage, "damage_taken_ratio", value, "target.resources"),
                    *status_terms,
                    *transient,
                ),
                skipped_terms=status_skipped,
                metadata={"status_damage_taken": status_value},
            )
        if stage == "damage_reduction":
            value = _resource(target, "damage_reduction")
            transient = _transient_terms(modifier_terms, stage, ("damage_reduction",))
            status_value, status_terms, status_skipped = _status_terms(
                target,
                source_type="target.status",
                stage=stage,
                keys=("damage_reduction",),
            )
            residuals = damage_reduction_residuals(value, status_terms, tuple(float(term["value"]) for term in transient))
            return DamageStageBucket(
                stage,
                True,
                math.prod(residuals),
                applied_terms=(
                    _applied(stage, "damage_reduction", value, "target.resources"),
                    *status_terms,
                    *transient,
                ),
                skipped_terms=status_skipped,
                metadata={
                    "status_damage_reduction": status_value,
                    "aggregation": "independent_reduction_product",
                    "reduction_residuals": list(residuals),
                },
            )
        if stage == "toughness_state":
            broken = bool(target.flags.get("broken", False))
            status_driven = target.flags.get("toughness_reduction_mode") == "status"
            segments = read_toughness_segments(target)
            multiplier = toughness_state_multiplier(target)
            return DamageStageBucket(
                stage,
                True,
                multiplier,
                applied_terms=(
                    _applied(stage, "current_toughness", target.toughness, "target.state"),
                    _applied(stage, "broken", 1.0 if broken else 0.0, "target.state"),
                    _applied(stage, "remaining_toughness_segments", segments.remaining_segments,
                             "target.flags.stance_segments_remaining" if segments.maximum_segments > 1 else "target.toughness"),
                ),
                metadata={"broken": broken, "reduction_from_status": status_driven,
                          "toughness_segments": segments.to_json()},
            )
        if stage == "toughness_bonus":
            value = _resource(actor, "toughness_damage_added_ratio")
            status_value, status_terms, status_skipped = _status_terms(
                actor,
                source_type="actor.status",
                stage=stage,
                keys=("toughness_damage_added_ratio",),
            )
            return DamageStageBucket(
                stage,
                True,
                1.0 + value + status_value,
                applied_terms=(
                    _applied(stage, "toughness_damage_added_ratio", value, "actor.resources"),
                    *status_terms,
                ),
                skipped_terms=status_skipped,
                metadata={"status_toughness_bonus": status_value},
            )
        return DamageStageBucket(stage, False, 1.0, skipped_terms=(_skipped(stage, "stage_not_implemented", family),))


def _transient_terms(terms: tuple[dict[str, JSONValue], ...], stage: str,
                     keys: tuple[str, ...]) -> tuple[dict[str, JSONValue], ...]:
    return tuple({**term, "stage": stage, "applied": True} for term in terms
                 if term.get("bucket") == stage and term.get("key") in keys)


def _resource(unit: UnitState, key: str) -> float:
    value = unit.resources.get(key, 0.0)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _applied(stage: str, key: str, value: float, source: str) -> dict[str, JSONValue]:
    return {
        "stage": stage,
        "key": key,
        "source": source,
        "value": float(value),
        "applied": True,
        "applied_reason": "neutral_value_applied" if value == 0.0 else "structured_value_applied",
    }


def _skipped(stage: str, key: str, reason: str) -> dict[str, JSONValue]:
    return {"stage": stage, "key": key, "applied": False, "skipped_reason": reason}


def _status_terms(
    unit: UnitState,
    *,
    source_type: str,
    stage: str,
    keys: tuple[str, ...],
) -> tuple[float, tuple[dict[str, JSONValue], ...], tuple[dict[str, JSONValue], ...]]:
    total, applied, skipped = status_modifier_terms(
        unit,
        source_type=source_type,
        bucket=stage,
        keys=keys,
    )
    if not applied and not skipped:
        return total, (), (_skipped(stage, "status_modifier", "no_applicable_status_modifier_source"),)
    return total, tuple(term.to_json() for term in applied), tuple(term.to_json() for term in skipped)
