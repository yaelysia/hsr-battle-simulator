from __future__ import annotations

from dataclasses import dataclass, field

from ..core.model import BattleState, JSONValue, UnitState
from .unit_stats import effective_unit_stat


@dataclass(frozen=True)
class ScalingBasisResult:
    ok: bool
    basis_kind: str
    unit_ref: str
    unit_id: str
    stat: str
    value: float | None
    source_trace: dict[str, JSONValue] = field(default_factory=dict)
    source_terms: tuple[dict[str, JSONValue], ...] = ()
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "basis_kind": self.basis_kind,
            "unit_ref": self.unit_ref,
            "unit_id": self.unit_id,
            "stat": self.stat,
            "value": self.value,
            "source_trace": self.source_trace,
            "source_terms": [dict(term) for term in self.source_terms],
            "blocked_reason": self.blocked_reason,
        }


def resolve_scaling_basis(
    state: BattleState,
    *,
    attacker_id: str,
    target_id: str,
    basis: dict[str, JSONValue],
    source_trace: dict[str, JSONValue] | None = None,
) -> ScalingBasisResult:
    trace = {**(source_trace or {}), "scaling_basis": basis}
    if not isinstance(basis, dict) or not basis:
        return _blocked("scaling_basis_missing", trace)
    kind = str(basis.get("kind") or "")
    if kind == "fixed":
        value = basis.get("value")
        if not isinstance(value, (int, float)):
            return _blocked("fixed_scaling_basis_value_missing", trace, basis_kind=kind)
        return ScalingBasisResult(
            ok=True,
            basis_kind=kind,
            unit_ref="",
            unit_id="",
            stat="fixed",
            value=float(value),
            source_trace=trace,
        )
    if kind != "unit_stat":
        return _blocked(f"scaling_basis_kind_not_supported:{kind or 'missing'}", trace, basis_kind=kind)

    unit_ref = str(basis.get("unit_ref") or "")
    unit_id = _resolve_unit_id(unit_ref, attacker_id, target_id)
    if not unit_id:
        return _blocked(f"scaling_basis_unit_ref_not_supported:{unit_ref or 'missing'}", trace, basis_kind=kind, unit_ref=unit_ref)
    unit = state.units.get(unit_id)
    if unit is None:
        return _blocked("scaling_basis_unit_missing", trace, basis_kind=kind, unit_ref=unit_ref, unit_id=unit_id)

    stat = str(basis.get("stat") or "")
    value, source_terms = _unit_stat_value(unit, stat)
    if value is None:
        return _blocked(
            f"scaling_basis_stat_not_supported:{stat or 'missing'}",
            trace,
            basis_kind=kind,
            unit_ref=unit_ref,
            unit_id=unit_id,
            stat=stat,
        )
    return ScalingBasisResult(
        ok=True,
        basis_kind=kind,
        unit_ref=unit_ref,
        unit_id=unit_id,
        stat=stat,
        value=value,
        source_trace=trace,
        source_terms=source_terms,
    )


def _resolve_unit_id(unit_ref: str, attacker_id: str, target_id: str) -> str:
    if unit_ref in {"attacker", "actor", "caster", "source"}:
        return attacker_id
    if unit_ref in {"target", "defender", "victim"}:
        return target_id
    return ""


def _unit_stat_value(
    unit: UnitState,
    stat: str,
) -> tuple[float | None, tuple[dict[str, JSONValue], ...]]:
    if stat == "hp":
        return float(unit.hp), ()
    if stat == "max_hp":
        return float(unit.max_hp), ()
    if stat in {"attack", "defense", "speed"}:
        effective = effective_unit_stat(unit, stat)
        return effective.value, effective.source_terms
    if stat == "toughness":
        return float(unit.toughness), ()
    if stat == "max_toughness":
        return float(unit.max_toughness), ()
    resource_value = unit.resources.get(stat)
    if isinstance(resource_value, (int, float)) and not isinstance(resource_value, bool):
        effective = effective_unit_stat(unit, stat)
        return effective.value, effective.source_terms
    return None, ()


def _blocked(
    reason: str,
    source_trace: dict[str, JSONValue],
    *,
    basis_kind: str = "",
    unit_ref: str = "",
    unit_id: str = "",
    stat: str = "",
) -> ScalingBasisResult:
    return ScalingBasisResult(
        ok=False,
        basis_kind=basis_kind,
        unit_ref=unit_ref,
        unit_id=unit_id,
        stat=stat,
        value=None,
        source_trace=source_trace,
        blocked_reason=reason,
    )
