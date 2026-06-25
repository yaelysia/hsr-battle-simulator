from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from ..core.model import BattleState, JSONValue, RNGEvent, UnitState
from ..rules.ir import ActionDefinitionIR
from .scaling_basis import resolve_scaling_basis


@dataclass(frozen=True)
class ModifierTerm:
    source_type: str
    source_id: str
    bucket: str
    key: str
    scope: str
    condition: str
    applied_value: float | None = None
    applied_reason: str = ""
    skipped_reason: str = ""
    raw_path: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "bucket": self.bucket,
            "key": self.key,
            "scope": self.scope,
            "condition": self.condition,
            "applied_value": self.applied_value,
            "applied_reason": self.applied_reason,
            "skipped_reason": self.skipped_reason,
            "raw_path": self.raw_path,
        }


@dataclass(frozen=True)
class DamageFormulaBucket:
    bucket: str
    multiplier: float
    applied_terms: tuple[ModifierTerm, ...] = ()
    skipped_terms: tuple[ModifierTerm, ...] = ()
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "bucket": self.bucket,
            "multiplier": self.multiplier,
            "applied_terms": [term.to_json() for term in self.applied_terms],
            "skipped_terms": [term.to_json() for term in self.skipped_terms],
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ModifierLedger:
    formula_family: str
    buckets: tuple[DamageFormulaBucket, ...]

    def to_json(self) -> dict[str, JSONValue]:
        applied_count = sum(len(bucket.applied_terms) for bucket in self.buckets)
        skipped_count = sum(len(bucket.skipped_terms) for bucket in self.buckets)
        return {
            "formula_family": self.formula_family,
            "buckets": [bucket.to_json() for bucket in self.buckets],
            "applied_count": applied_count,
            "skipped_count": skipped_count,
            "applied_terms": [
                term.to_json()
                for bucket in self.buckets
                for term in bucket.applied_terms
            ],
            "skipped_terms": [
                term.to_json()
                for bucket in self.buckets
                for term in bucket.skipped_terms
            ],
        }


@dataclass(frozen=True)
class CritResolution:
    event_id: str
    mode: str
    is_crit: bool
    crit_rate: float
    crit_damage: float
    multiplier: float
    rng_roll: float | None = None
    reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "event_id": self.event_id,
            "mode": self.mode,
            "is_crit": self.is_crit,
            "crit_rate": self.crit_rate,
            "crit_damage": self.crit_damage,
            "multiplier": self.multiplier,
            "rng_roll": self.rng_roll,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DamageFormulaInput:
    state: BattleState
    attacker_id: str
    target_id: str
    action_definition: ActionDefinitionIR
    attack_type: str
    element_type: str | None
    scaling_ratio: float
    scaling_basis: dict[str, JSONValue] = field(default_factory=dict)
    source_trace: dict[str, JSONValue] = field(default_factory=dict)
    crit_mode: str | None = None
    direct_modifier_terms: tuple[dict[str, JSONValue], ...] = ()


@dataclass(frozen=True)
class DamageFormulaResult:
    formula_family: str
    attacker_id: str
    target_id: str
    action_definition_id: str
    attack_type: str
    element_type: str | None
    scaling_stat: str
    scaling_value: float
    scaling_ratio: float
    scaling_basis: dict[str, JSONValue]
    flat_damage: float
    base_damage: float
    crit_resolution: CritResolution
    crit_mult: float
    damage_bonus_mult: float
    def_mult: float
    res_mult: float
    damage_taken_mult: float
    damage_reduction_mult: float
    toughness_state_mult: float
    final_damage: float
    modifier_ledger: ModifierLedger
    rng_events: tuple[RNGEvent, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "formula_family": self.formula_family,
            "attacker_id": self.attacker_id,
            "target_id": self.target_id,
            "action_definition_id": self.action_definition_id,
            "attack_type": self.attack_type,
            "element_type": self.element_type,
            "scaling": {
                "stat": self.scaling_stat,
                "value": self.scaling_value,
                "ratio": self.scaling_ratio,
                "basis_result": self.scaling_basis,
                "flat_damage": self.flat_damage,
                "base_damage": self.base_damage,
            },
            "crit_resolution": self.crit_resolution.to_json(),
            "multipliers": {
                "crit": self.crit_mult,
                "damage_bonus": self.damage_bonus_mult,
                "defense": self.def_mult,
                "resistance": self.res_mult,
                "damage_taken": self.damage_taken_mult,
                "damage_reduction": self.damage_reduction_mult,
                "toughness_state": self.toughness_state_mult,
            },
            "final_damage": self.final_damage,
            "modifier_ledger": self.modifier_ledger.to_json(),
            "rng_events": [event.to_json() for event in self.rng_events],
            "calculation_mode": "v0_209_direct_damage_formula",
        }


class DirectDamageFormula:
    def calculate(self, formula_input: DamageFormulaInput) -> DamageFormulaResult:
        state = formula_input.state
        actor = state.units[formula_input.attacker_id]
        target = state.units[formula_input.target_id]
        action_definition = formula_input.action_definition
        element = formula_input.element_type

        scaling_ratio = formula_input.scaling_ratio
        flat_damage = 0.0
        basis_result = resolve_scaling_basis(
            state,
            attacker_id=formula_input.attacker_id,
            target_id=formula_input.target_id,
            basis=formula_input.scaling_basis,
            source_trace=formula_input.source_trace,
        )
        if not basis_result.ok or basis_result.value is None:
            raise ValueError(basis_result.blocked_reason or "scaling_basis_not_admitted")
        scaling_value = basis_result.value
        base_damage = max(0.0, scaling_value * scaling_ratio + flat_damage)

        crit_resolution, rng_event, crit_bucket = _resolve_crit(formula_input, actor)
        damage_bonus_mult, damage_bonus_bucket = _damage_bonus_bucket(actor, element)
        def_mult, defense_bucket = _defense_bucket(actor, target, formula_input)
        res_mult, resistance_bucket = _resistance_bucket(actor, target, element)
        damage_taken_mult, damage_taken_bucket = _damage_taken_bucket(target)
        damage_reduction_mult, damage_reduction_bucket = _damage_reduction_bucket(target)
        toughness_mult, toughness_bucket = _toughness_state_bucket(target)
        final_damage = max(
            0.0,
            base_damage
            * crit_resolution.multiplier
            * damage_bonus_mult
            * def_mult
            * res_mult
            * damage_taken_mult
            * damage_reduction_mult
            * toughness_mult,
        )
        ledger = ModifierLedger(
            formula_family="direct",
            buckets=(
                crit_bucket,
                damage_bonus_bucket,
                defense_bucket,
                resistance_bucket,
                damage_taken_bucket,
                damage_reduction_bucket,
                toughness_bucket,
            ),
        )
        return DamageFormulaResult(
            formula_family="direct",
            attacker_id=formula_input.attacker_id,
            target_id=formula_input.target_id,
            action_definition_id=action_definition.definition_id,
            attack_type=formula_input.attack_type,
            element_type=element,
            scaling_stat=basis_result.stat,
            scaling_value=scaling_value,
            scaling_ratio=scaling_ratio,
            scaling_basis=basis_result.to_json(),
            flat_damage=flat_damage,
            base_damage=base_damage,
            crit_resolution=crit_resolution,
            crit_mult=crit_resolution.multiplier,
            damage_bonus_mult=damage_bonus_mult,
            def_mult=def_mult,
            res_mult=res_mult,
            damage_taken_mult=damage_taken_mult,
            damage_reduction_mult=damage_reduction_mult,
            toughness_state_mult=toughness_mult,
            final_damage=final_damage,
            modifier_ledger=ledger,
            rng_events=(rng_event,),
        )


def _resolve_crit(formula_input: DamageFormulaInput, actor: UnitState) -> tuple[CritResolution, RNGEvent, DamageFormulaBucket]:
    crit_modifier_terms = _direct_modifier_terms(formula_input, bucket="crit", key="critical_chance")
    crit_bonus = sum(float(term.get("value") or 0.0) for term in crit_modifier_terms)
    crit_rate = _clamp(_resource(actor, "critical_chance") + crit_bonus, 0.0, 1.0)
    crit_damage = _resource(actor, "critical_damage")
    event_id = (
        f"rng:{formula_input.state.event_index}:"
        f"{formula_input.attacker_id}:{formula_input.action_definition.definition_id}:"
        f"{formula_input.target_id}:crit"
    )
    mode = str(formula_input.crit_mode or "deterministic").lower()
    if mode in {"crit", "forced_crit", "true"}:
        is_crit = True
        roll = None
        reason = "forced_crit"
    elif mode in {"noncrit", "non_crit", "false"}:
        is_crit = False
        roll = None
        reason = "forced_noncrit"
    elif mode in {"", "deterministic", "auto"}:
        roll = _deterministic_roll(
            formula_input.state.rng_state,
            formula_input.state.event_index,
            formula_input.attacker_id,
            formula_input.action_definition.definition_id,
            formula_input.target_id,
        )
        is_crit = roll < crit_rate
        reason = "deterministic_rng"
    elif mode == "expected":
        raise ValueError("expected crit mode is not executable in v0_209")
    else:
        raise ValueError(f"unknown crit mode {formula_input.crit_mode!r}")
    multiplier = 1.0 + crit_damage if is_crit else 1.0
    resolution = CritResolution(
        event_id=event_id,
        mode=mode or "deterministic",
        is_crit=is_crit,
        crit_rate=crit_rate,
        crit_damage=crit_damage,
        multiplier=multiplier,
        rng_roll=roll,
        reason=reason,
    )
    rng_event = RNGEvent(
        rng_type="crit",
        source="damage_formula",
        event_id=event_id,
        before_state=formula_input.state.rng_state,
        after_state=formula_input.state.rng_state,
        result=resolution.to_json(),
        metadata={
            "actor_id": formula_input.attacker_id,
            "target_id": formula_input.target_id,
            "action_definition_id": formula_input.action_definition.definition_id,
            "source_trace": formula_input.source_trace,
        },
    )
    bucket = DamageFormulaBucket(
        bucket="crit",
        multiplier=multiplier,
        applied_terms=(
            _applied_term("actor.resources", actor.unit_id, "crit", "critical_chance", "actor", "always", crit_rate, "crit_rate_clamped", "resources.critical_chance"),
            _applied_term("actor.resources", actor.unit_id, "crit", "critical_damage", "actor", "is_crit" if is_crit else "not_crit", crit_damage, "crit_damage_available", "resources.critical_damage"),
            *tuple(_direct_modifier_applied_term(term, "crit") for term in crit_modifier_terms),
        ),
        metadata={**resolution.to_json(), "direct_modifier_bonus": crit_bonus},
    )
    return resolution, rng_event, bucket


def _damage_bonus_bucket(actor: UnitState, element: str | None) -> tuple[float, DamageFormulaBucket]:
    all_bonus = _resource(actor, "damage_added_ratio")
    element_key = f"{element}_damage_added_ratio" if element else ""
    element_bonus = _resource(actor, element_key) if element_key else 0.0
    status_bonus, status_terms, skipped_terms = _status_modifier_terms(
        actor,
        source_type="actor.status",
        bucket="damage_bonus",
        keys=("damage_added_ratio", element_key) if element_key else ("damage_added_ratio",),
    )
    multiplier = 1.0 + all_bonus + element_bonus + status_bonus
    terms = (
        _applied_term("actor.resources", actor.unit_id, "damage_bonus", "damage_added_ratio", "actor", "always", all_bonus, _neutral_reason(all_bonus), "resources.damage_added_ratio"),
        _applied_term("actor.resources", actor.unit_id, "damage_bonus", element_key or "element_damage_added_ratio", "actor", f"element={element}", element_bonus, _neutral_reason(element_bonus), f"resources.{element_key}" if element_key else "resources.<element>_damage_added_ratio"),
        *status_terms,
    )
    return multiplier, DamageFormulaBucket(
        bucket="damage_bonus",
        multiplier=multiplier,
        applied_terms=terms,
        skipped_terms=skipped_terms,
        metadata={"status_bonus": status_bonus},
    )


def _defense_bucket(actor: UnitState, target: UnitState, formula_input: DamageFormulaInput) -> tuple[float, DamageFormulaBucket]:
    resource_def_reduction = _resource(target, "def_reduction")
    resource_def_ignore = _resource(actor, "def_ignore")
    direct_terms = _direct_modifier_terms(formula_input, bucket="defense", key="defender_defence_added_ratio")
    defender_added_ratio = sum(float(term.get("value") or 0.0) for term in direct_terms)
    status_def_reduction, target_status_terms, target_skipped_terms = _status_modifier_terms(
        target,
        source_type="target.status",
        bucket="defense",
        keys=("def_reduction",),
    )
    status_def_ignore, actor_status_terms, actor_skipped_terms = _status_modifier_terms(
        actor,
        source_type="actor.status",
        bucket="defense",
        keys=("def_ignore",),
    )
    def_reduction = resource_def_reduction + status_def_reduction
    def_ignore = resource_def_ignore + status_def_ignore
    effective_def = max(0.0, target.defense * (1.0 + defender_added_ratio - def_reduction - def_ignore))
    multiplier = 1.0 if effective_def <= 0 else 1.0 - effective_def / (effective_def + 200.0 + 10.0 * actor.level)
    terms = (
        _applied_term("target.stats", target.unit_id, "defense", "defense", "target", "always", target.defense, "base_target_defense", "unit.defense"),
        _applied_term("target.resources", target.unit_id, "defense", "def_reduction", "target", "always", resource_def_reduction, _neutral_reason(resource_def_reduction), "resources.def_reduction"),
        _applied_term("actor.resources", actor.unit_id, "defense", "def_ignore", "actor", "always", resource_def_ignore, _neutral_reason(resource_def_ignore), "resources.def_ignore"),
        *tuple(_direct_modifier_applied_term(term, "defense") for term in direct_terms),
        *target_status_terms,
        *actor_status_terms,
    )
    return multiplier, DamageFormulaBucket(
        bucket="defense",
        multiplier=multiplier,
        applied_terms=terms,
        skipped_terms=(*target_skipped_terms, *actor_skipped_terms),
        metadata={
            "effective_defense": effective_def,
            "actor_level": actor.level,
            "status_def_reduction": status_def_reduction,
            "status_def_ignore": status_def_ignore,
            "direct_defender_added_ratio": defender_added_ratio,
        },
    )


def _resistance_bucket(actor: UnitState, target: UnitState, element: str | None) -> tuple[float, DamageFormulaBucket]:
    element_res_key = f"{element}_resistance" if element else ""
    element_pen_key = f"{element}_res_pen" if element else ""
    element_res = _resource(target, element_res_key) if element_res_key else 0.0
    all_res = _resource(target, "all_resistance")
    uses_element_res = bool(element_res_key and element_res_key in target.resources)
    status_res_delta, status_terms, status_skipped_terms = _status_modifier_terms(
        target,
        source_type="target.status",
        bucket="resistance",
        keys=(f"{element}_resistance_delta", "all_resistance_delta") if element else ("all_resistance_delta",),
    )
    selected_res = (element_res if uses_element_res else all_res) + status_res_delta
    element_pen = _resource(actor, element_pen_key) if element_pen_key else 0.0
    all_pen = _resource(actor, "all_res_pen")
    multiplier = 1.0 - selected_res + element_pen + all_pen
    target_res_term = (
        _applied_term("target.resources", target.unit_id, "resistance", element_res_key or "element_resistance", "target", f"element={element}", element_res, _neutral_reason(element_res), f"resources.{element_res_key}" if element_res_key else "resources.<element>_resistance")
        if uses_element_res
        else _applied_term("target.resources", target.unit_id, "resistance", "all_resistance", "target", "fallback", all_res, _neutral_reason(all_res), "resources.all_resistance")
    )
    applied_terms = (
        target_res_term,
        _applied_term("actor.resources", actor.unit_id, "resistance", element_pen_key or "element_res_pen", "actor", f"element={element}", element_pen, _neutral_reason(element_pen), f"resources.{element_pen_key}" if element_pen_key else "resources.<element>_res_pen"),
        _applied_term("actor.resources", actor.unit_id, "resistance", "all_res_pen", "actor", "always", all_pen, _neutral_reason(all_pen), "resources.all_res_pen"),
        *status_terms,
    )
    skipped_terms = (
        (
            _skipped_term("target.resources", target.unit_id, "resistance", "all_resistance", "target", "element_resistance_present", "element_specific_resistance_selected", "resources.all_resistance"),
        )
        if uses_element_res
        else (
            _skipped_term("target.resources", target.unit_id, "resistance", element_res_key or "element_resistance", "target", f"element={element}", "missing_element_resistance_uses_all_resistance", f"resources.{element_res_key}" if element_res_key else "resources.<element>_resistance"),
        )
    ) + status_skipped_terms
    return multiplier, DamageFormulaBucket(
        bucket="resistance",
        multiplier=multiplier,
        applied_terms=applied_terms,
        skipped_terms=skipped_terms,
        metadata={"selected_resistance": selected_res, "status_resistance_delta": status_res_delta},
    )


def _damage_taken_bucket(target: UnitState) -> tuple[float, DamageFormulaBucket]:
    resource_value = _resource(target, "damage_taken_ratio")
    status_value, status_terms, status_skipped_terms = _status_modifier_terms(
        target,
        source_type="target.status",
        bucket="damage_taken",
        keys=("damage_taken_ratio",),
    )
    value = resource_value + status_value
    multiplier = 1.0 + value
    return multiplier, DamageFormulaBucket(
        bucket="damage_taken",
        multiplier=multiplier,
        applied_terms=(
            _applied_term("target.resources", target.unit_id, "damage_taken", "damage_taken_ratio", "target", "always", resource_value, _neutral_reason(resource_value), "resources.damage_taken_ratio"),
            *status_terms,
        ),
        skipped_terms=status_skipped_terms,
        metadata={"status_damage_taken_ratio": status_value},
    )


def _damage_reduction_bucket(target: UnitState) -> tuple[float, DamageFormulaBucket]:
    value = _resource(target, "damage_reduction")
    multiplier = max(0.0, 1.0 - value)
    return multiplier, DamageFormulaBucket(
        bucket="damage_reduction",
        multiplier=multiplier,
        applied_terms=(
            _applied_term("target.resources", target.unit_id, "damage_reduction", "damage_reduction", "target", "always", value, _neutral_reason(value), "resources.damage_reduction"),
        ),
    )


def _toughness_state_bucket(target: UnitState) -> tuple[float, DamageFormulaBucket]:
    broken = bool(target.flags.get("broken", False))
    has_positive_toughness = target.toughness > 0
    multiplier = 0.9 if has_positive_toughness and not broken else 1.0
    reason = "positive_toughness_not_broken" if multiplier == 0.9 else "broken_or_no_positive_toughness"
    return multiplier, DamageFormulaBucket(
        bucket="toughness_state",
        multiplier=multiplier,
        applied_terms=(
            _applied_term("target.state", target.unit_id, "toughness_state", "current_toughness", "target", "always", target.toughness, reason, "unit.toughness"),
            _applied_term("target.state", target.unit_id, "toughness_state", "broken", "target", "always", 1.0 if broken else 0.0, reason, "flags.broken"),
        ),
        metadata={"broken": broken, "current_toughness": target.toughness, "max_toughness": target.max_toughness},
    )


def _resource(unit: UnitState, key: str) -> float:
    if not key:
        return 0.0
    value = unit.resources.get(key, 0.0)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _status_modifier_terms(
    unit: UnitState,
    *,
    source_type: str,
    bucket: str,
    keys: tuple[str, ...],
) -> tuple[float, tuple[ModifierTerm, ...], tuple[ModifierTerm, ...]]:
    allowed_keys = {key for key in keys if key}
    applied: list[ModifierTerm] = []
    skipped: list[ModifierTerm] = []
    total = 0.0
    for detail in _status_details(unit):
        instance_id = str(detail.get("instance_id") or detail.get("status_id") or "unknown_status")
        modifiers = detail.get("modifiers")
        if not isinstance(modifiers, list):
            continue
        for index, modifier in enumerate(modifiers):
            if not isinstance(modifier, dict):
                continue
            modifier_bucket = str(modifier.get("bucket") or "")
            modifier_key = str(modifier.get("key") or "")
            if modifier_bucket != bucket:
                continue
            raw_path = str(modifier.get("raw_path") or f"status_details.{instance_id}.modifiers[{index}]")
            scope = str(modifier.get("scope") or source_type.split(".", 1)[0])
            condition = str(modifier.get("condition") or "status_modifier")
            if modifier_key not in allowed_keys:
                skipped.append(
                    _skipped_term(
                        source_type,
                        instance_id,
                        bucket,
                        modifier_key or "<missing>",
                        scope,
                        condition,
                        "modifier_key_not_applicable_for_bucket_context",
                        raw_path,
                    )
                )
                continue
            value = modifier.get("value")
            if not isinstance(value, (int, float)):
                skipped.append(
                    _skipped_term(
                        source_type,
                        instance_id,
                        bucket,
                        modifier_key,
                        scope,
                        condition,
                        "modifier_value_not_numeric",
                        raw_path,
                    )
                )
                continue
            value_float = float(value)
            total += value_float
            applied.append(
                _applied_term(
                    source_type,
                    instance_id,
                    bucket,
                    modifier_key,
                    scope,
                    condition,
                    value_float,
                    str(modifier.get("applied_reason") or _neutral_reason(value_float)),
                    raw_path,
                )
            )
    return total, tuple(applied), tuple(skipped)


def _status_details(unit: UnitState) -> tuple[dict[str, JSONValue], ...]:
    raw_details = unit.flags.get("status_details", ())
    if not isinstance(raw_details, (list, tuple)):
        return ()
    return tuple(item for item in raw_details if isinstance(item, dict))


def _direct_modifier_terms(
    formula_input: DamageFormulaInput,
    *,
    bucket: str,
    key: str,
) -> tuple[dict[str, JSONValue], ...]:
    terms: list[dict[str, JSONValue]] = []
    for item in formula_input.direct_modifier_terms:
        if not isinstance(item, dict):
            continue
        if item.get("bucket") != bucket or item.get("key") != key:
            continue
        if not isinstance(item.get("value"), (int, float)):
            continue
        terms.append(item)
    return tuple(terms)


def _direct_modifier_applied_term(term: dict[str, JSONValue], bucket: str) -> ModifierTerm:
    return _applied_term(
        str(term.get("source_type") or "damage_modifier_ir"),
        str(term.get("source_id") or term.get("damage_modifier_id") or ""),
        bucket,
        str(term.get("key") or ""),
        str(term.get("scope") or ""),
        str(term.get("condition") or "condition_passed"),
        float(term.get("value") or 0.0),
        str(term.get("applied_reason") or "damage_modifier_applied"),
        str(term.get("raw_path") or term.get("field") or ""),
    )


def _deterministic_roll(
    rng_state: str,
    event_index: int,
    attacker_id: str,
    action_definition_id: str,
    target_id: str,
) -> float:
    payload = {
        "rng_state": rng_state,
        "event_index": event_index,
        "attacker_id": attacker_id,
        "action_definition_id": action_definition_id,
        "target_id": target_id,
        "rng_type": "crit",
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:13]
    return int(digest, 16) / float(0x10000000000000)


def _applied_term(
    source_type: str,
    source_id: str,
    bucket: str,
    key: str,
    scope: str,
    condition: str,
    value: float,
    reason: str,
    raw_path: str,
) -> ModifierTerm:
    return ModifierTerm(
        source_type=source_type,
        source_id=source_id,
        bucket=bucket,
        key=key,
        scope=scope,
        condition=condition,
        applied_value=value,
        applied_reason=reason,
        raw_path=raw_path,
    )


def _skipped_term(
    source_type: str,
    source_id: str,
    bucket: str,
    key: str,
    scope: str,
    condition: str,
    reason: str,
    raw_path: str,
) -> ModifierTerm:
    return ModifierTerm(
        source_type=source_type,
        source_id=source_id,
        bucket=bucket,
        key=key,
        scope=scope,
        condition=condition,
        skipped_reason=reason,
        raw_path=raw_path,
    )


def _neutral_reason(value: float) -> str:
    return "applied" if abs(value) > 1e-12 else "neutral_default"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
