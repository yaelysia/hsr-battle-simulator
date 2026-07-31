from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Literal, cast

from .immutable_json import FrozenJSONDict, freeze_json, thaw_json
from .ir_types import IRSource, JSONValue


ContributionPool = Literal["base", "percentage", "flat", "resource"]
CalculationKind = Literal["constant", "linear_growth", "ratio", "flat", "resource"]
ApplicationKind = Literal["base_stat_ratio", "base_stat_delta", "resource_delta"]
AggregationBasis = Literal["base", "ratio", "flat", "resource"]
CONTRIBUTION_POOL_ORDER = {"base": 0, "percentage": 1, "flat": 2, "resource": 3}
BASE_STAT_PROPERTY_TYPES = frozenset(
    {"max_hp", "attack", "defense", "speed", "max_energy"}
)
_APPLICATION_KIND_CHANNELS: Mapping[
    ApplicationKind,
    tuple[ContributionPool, CalculationKind],
] = MappingProxyType(
    {
        "base_stat_ratio": ("percentage", "ratio"),
        "base_stat_delta": ("flat", "flat"),
        "resource_delta": ("resource", "resource"),
    }
)
_CONTRIBUTION_CALCULATION_KINDS: Mapping[
    ContributionPool,
    frozenset[CalculationKind],
] = MappingProxyType(
    {
        "base": frozenset({"constant", "linear_growth"}),
        "percentage": frozenset({"ratio"}),
        "flat": frozenset({"flat"}),
        "resource": frozenset({"resource"}),
    }
)


def require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def require_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")
    return value


def canonical_decimal(value: object, field_name: str) -> str:
    if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be an exact decimal string or integer")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must be a valid decimal") from exc
    if not number.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def contribution_channel_for_application_kind(
    application_kind: object,
) -> tuple[ContributionPool, CalculationKind] | None:
    if not isinstance(application_kind, str):
        return None
    return _APPLICATION_KIND_CHANNELS.get(cast(ApplicationKind, application_kind))


def admitted_calculation_kinds(
    contribution_pool: ContributionPool,
) -> frozenset[CalculationKind]:
    try:
        return _CONTRIBUTION_CALCULATION_KINDS[contribution_pool]
    except KeyError as exc:
        raise ValueError("invalid contribution_pool") from exc


@dataclass(frozen=True)
class StaticPropertyBinding:
    contribution_pool: ContributionPool
    canonical_property_type: str
    calculation_kind: CalculationKind
    application_kind: ApplicationKind

    def __post_init__(self) -> None:
        if self.contribution_pool not in {"percentage", "flat", "resource"}:
            raise ValueError("static property bindings must use percentage, flat, or resource pools")
        require_text(self.canonical_property_type, "canonical_property_type")
        expected = contribution_channel_for_application_kind(self.application_kind)
        if expected != (self.contribution_pool, self.calculation_kind):
            raise ValueError("static property binding channels are inconsistent")


_STATIC_PROPERTY_BINDINGS: Mapping[str, StaticPropertyBinding] = MappingProxyType(
    {
        "AttackAddedRatio": StaticPropertyBinding(
            "percentage", "attack", "ratio", "base_stat_ratio"
        ),
        "HPAddedRatio": StaticPropertyBinding(
            "percentage", "max_hp", "ratio", "base_stat_ratio"
        ),
        "DefenceAddedRatio": StaticPropertyBinding(
            "percentage", "defense", "ratio", "base_stat_ratio"
        ),
        "SpeedAddedRatio": StaticPropertyBinding(
            "percentage", "speed", "ratio", "base_stat_ratio"
        ),
        "SpeedDelta": StaticPropertyBinding(
            "flat", "speed", "flat", "base_stat_delta"
        ),
        "HPDelta": StaticPropertyBinding(
            "flat", "max_hp", "flat", "base_stat_delta"
        ),
        "AttackDelta": StaticPropertyBinding(
            "flat", "attack", "flat", "base_stat_delta"
        ),
        "DefenceDelta": StaticPropertyBinding(
            "flat", "defense", "flat", "base_stat_delta"
        ),
        "BaseSpeed": StaticPropertyBinding(
            "flat", "speed", "flat", "base_stat_delta"
        ),
        "CriticalChanceBase": StaticPropertyBinding(
            "resource", "critical_chance", "resource", "resource_delta"
        ),
        "CriticalDamageBase": StaticPropertyBinding(
            "resource", "critical_damage", "resource", "resource_delta"
        ),
        "BreakDamageAddedRatioBase": StaticPropertyBinding(
            "resource", "break_damage_added_ratio", "resource", "resource_delta"
        ),
        "StatusProbabilityBase": StaticPropertyBinding(
            "resource", "effect_hit_rate", "resource", "resource_delta"
        ),
        "StatusResistanceBase": StaticPropertyBinding(
            "resource", "effect_resistance", "resource", "resource_delta"
        ),
        "AllDamageTypeAddedRatio": StaticPropertyBinding(
            "resource", "damage_added_ratio", "resource", "resource_delta"
        ),
        "PhysicalAddedRatio": StaticPropertyBinding(
            "resource", "Physical_damage_added_ratio", "resource", "resource_delta"
        ),
        "FireAddedRatio": StaticPropertyBinding(
            "resource", "Fire_damage_added_ratio", "resource", "resource_delta"
        ),
        "IceAddedRatio": StaticPropertyBinding(
            "resource", "Ice_damage_added_ratio", "resource", "resource_delta"
        ),
        "ThunderAddedRatio": StaticPropertyBinding(
            "resource", "Thunder_damage_added_ratio", "resource", "resource_delta"
        ),
        "WindAddedRatio": StaticPropertyBinding(
            "resource", "Wind_damage_added_ratio", "resource", "resource_delta"
        ),
        "QuantumAddedRatio": StaticPropertyBinding(
            "resource", "Quantum_damage_added_ratio", "resource", "resource_delta"
        ),
        "ImaginaryAddedRatio": StaticPropertyBinding(
            "resource", "Imaginary_damage_added_ratio", "resource", "resource_delta"
        ),
        "ElationDamageAddedRatioBase": StaticPropertyBinding(
            "resource", "elation_damage_added_ratio", "resource", "resource_delta"
        ),
        "SPRatioBase": StaticPropertyBinding(
            "resource", "energy_regeneration_rate", "resource", "resource_delta"
        ),
        "HealRatioBase": StaticPropertyBinding(
            "resource", "outgoing_healing_ratio", "resource", "resource_delta"
        ),
        "HealTakenRatio": StaticPropertyBinding(
            "resource", "incoming_healing_ratio", "resource", "resource_delta"
        ),
    }
)


def static_property_binding(raw_property_type: str) -> StaticPropertyBinding | None:
    if not isinstance(raw_property_type, str) or not raw_property_type.strip():
        return None
    return _STATIC_PROPERTY_BINDINGS.get(raw_property_type)


def canonical_json_fingerprint(value: Mapping[str, JSONValue]) -> str:
    encoded = json.dumps(
        thaw_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def require_sha256(value: object, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


def immutable_ir_source(source: IRSource, field_name: str = "source") -> IRSource:
    if not isinstance(source, IRSource):
        raise TypeError(f"{field_name} must be an IRSource")
    require_text(source.source_path, f"{field_name}.source_path")
    require_text(source.raw_type, f"{field_name}.raw_type")
    require_text(source.raw_id, f"{field_name}.raw_id")
    if not isinstance(source.evidence, Mapping):
        raise TypeError(f"{field_name}.evidence must be a JSON object")
    evidence = cast(FrozenJSONDict, freeze_json(dict(source.evidence)))
    return IRSource(
        source_path=source.source_path,
        raw_type=source.raw_type,
        raw_id=source.raw_id,
        evidence=evidence,
    )


def ir_source_from_json(value: object, field_name: str = "source") -> IRSource:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a JSON object")
    allowed = {"source_path", "raw_type", "raw_id", "evidence"}
    extra = sorted(set(value).difference(allowed))
    if extra:
        raise ValueError(f"{field_name} contains unsupported fields: {extra}")
    evidence = value.get("evidence")
    if not isinstance(evidence, Mapping):
        raise TypeError(f"{field_name}.evidence must be a JSON object")
    return immutable_ir_source(
        IRSource(
            source_path=require_text(value.get("source_path"), f"{field_name}.source_path"),
            raw_type=require_text(value.get("raw_type"), f"{field_name}.raw_type"),
            raw_id=require_text(value.get("raw_id"), f"{field_name}.raw_id"),
            evidence=cast(dict[str, JSONValue], thaw_json(evidence)),
        ),
        field_name,
    )


@dataclass(frozen=True, order=True)
class BuildSourceRef:
    definition_kind: str
    definition_identity: str

    def __post_init__(self) -> None:
        require_text(self.definition_kind, "definition_kind")
        require_text(self.definition_identity, "definition_identity")

    @property
    def stable_id(self) -> str:
        return f"{self.definition_kind}::{self.definition_identity}"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "definition_kind": self.definition_kind,
            "definition_identity": self.definition_identity,
            "stable_id": self.stable_id,
        }

    @classmethod
    def from_json(cls, value: object) -> BuildSourceRef:
        if not isinstance(value, Mapping):
            raise TypeError("source_ref must be a JSON object")
        allowed = {"definition_kind", "definition_identity", "stable_id"}
        extra = sorted(set(value).difference(allowed))
        if extra:
            raise ValueError(f"source_ref contains unsupported fields: {extra}")
        result = cls(
            definition_kind=require_text(value.get("definition_kind"), "definition_kind"),
            definition_identity=require_text(value.get("definition_identity"), "definition_identity"),
        )
        encoded_id = value.get("stable_id")
        if encoded_id is not None and encoded_id != result.stable_id:
            raise ValueError("source_ref stable_id is damaged")
        return result


@dataclass(frozen=True)
class StatCalculation:
    calculation_kind: CalculationKind
    base_value: str
    per_level_value: str = "0"
    level_offset: int = 0

    def __post_init__(self) -> None:
        if self.calculation_kind not in {"constant", "linear_growth", "ratio", "flat", "resource"}:
            raise ValueError("invalid stat calculation_kind")
        object.__setattr__(self, "base_value", canonical_decimal(self.base_value, "base_value"))
        object.__setattr__(
            self,
            "per_level_value",
            canonical_decimal(self.per_level_value, "per_level_value"),
        )
        require_int(self.level_offset, "level_offset")
        if self.level_offset < 0:
            raise ValueError("level_offset must be non-negative")
        if self.calculation_kind != "linear_growth" and (
            self.per_level_value != "0" or self.level_offset != 0
        ):
            raise ValueError("only linear_growth may carry per-level operands")

    @property
    def exact_value(self) -> str:
        value = Decimal(self.base_value) + Decimal(self.per_level_value) * self.level_offset
        return canonical_decimal(str(value), "exact_value")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "calculation_kind": self.calculation_kind,
            "base_value": self.base_value,
            "per_level_value": self.per_level_value,
            "level_offset": self.level_offset,
            "exact_value": self.exact_value,
        }

    @classmethod
    def from_json(cls, value: object) -> StatCalculation:
        if not isinstance(value, Mapping):
            raise TypeError("calculation must be a JSON object")
        allowed = {
            "calculation_kind",
            "base_value",
            "per_level_value",
            "level_offset",
            "exact_value",
        }
        extra = sorted(set(value).difference(allowed))
        if extra:
            raise ValueError(f"calculation contains unsupported fields: {extra}")
        result = cls(
            calculation_kind=cast(CalculationKind, require_text(value.get("calculation_kind"), "calculation_kind")),
            base_value=require_text(value.get("base_value"), "base_value"),
            per_level_value=require_text(value.get("per_level_value", "0"), "per_level_value"),
            level_offset=require_int(value.get("level_offset", 0), "level_offset"),
        )
        encoded = value.get("exact_value")
        if encoded is not None and canonical_decimal(encoded, "exact_value") != result.exact_value:
            raise ValueError("calculation exact_value is damaged")
        return result


@dataclass(frozen=True)
class StaticStatContribution:
    contribution_id: str
    contribution_pool: ContributionPool
    property_type: str
    exact_value: str
    source_ref: BuildSourceRef
    calculation: StatCalculation
    source: IRSource

    def __post_init__(self) -> None:
        require_text(self.contribution_id, "contribution_id")
        if self.contribution_pool not in CONTRIBUTION_POOL_ORDER:
            raise ValueError("invalid contribution_pool")
        require_text(self.property_type, "property_type")
        object.__setattr__(self, "exact_value", canonical_decimal(self.exact_value, "exact_value"))
        if not isinstance(self.source_ref, BuildSourceRef):
            raise TypeError("source_ref must be BuildSourceRef")
        if not isinstance(self.calculation, StatCalculation):
            raise TypeError("calculation must be StatCalculation")
        if self.exact_value != self.calculation.exact_value:
            raise ValueError("contribution exact_value must match calculation")
        if (
            self.calculation.calculation_kind
            not in admitted_calculation_kinds(self.contribution_pool)
        ):
            raise ValueError(
                "contribution pool and calculation kind use different aggregation bases"
            )
        is_base_stat = self.property_type in BASE_STAT_PROPERTY_TYPES
        if is_base_stat and self.contribution_pool == "resource":
            raise ValueError("base stat contribution cannot use the resource pool")
        if not is_base_stat and self.contribution_pool != "resource":
            raise ValueError("resource contribution cannot use a base stat pool")
        object.__setattr__(self, "source", immutable_ir_source(self.source))

    @property
    def sort_key(self) -> tuple[int, str, str, str]:
        return (
            CONTRIBUTION_POOL_ORDER[self.contribution_pool],
            self.property_type,
            self.source_ref.stable_id,
            self.contribution_id,
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "contribution_id": self.contribution_id,
            "contribution_pool": self.contribution_pool,
            "property_type": self.property_type,
            "exact_value": self.exact_value,
            "source_ref": self.source_ref.to_json(),
            "calculation": self.calculation.to_json(),
            "source": self.source.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> StaticStatContribution:
        if not isinstance(value, Mapping):
            raise TypeError("stat contribution must be a JSON object")
        allowed = {
            "contribution_id",
            "contribution_pool",
            "property_type",
            "exact_value",
            "source_ref",
            "calculation",
            "source",
        }
        extra = sorted(set(value).difference(allowed))
        if extra:
            raise ValueError(f"stat contribution contains unsupported fields: {extra}")
        return cls(
            contribution_id=require_text(value.get("contribution_id"), "contribution_id"),
            contribution_pool=cast(ContributionPool, require_text(value.get("contribution_pool"), "contribution_pool")),
            property_type=require_text(value.get("property_type"), "property_type"),
            exact_value=require_text(value.get("exact_value"), "exact_value"),
            source_ref=BuildSourceRef.from_json(value.get("source_ref")),
            calculation=StatCalculation.from_json(value.get("calculation")),
            source=ir_source_from_json(value.get("source")),
        )


@dataclass(frozen=True)
class StaticStatAggregate:
    """Deterministic Decimal aggregate derived from source-granular ledger terms."""

    property_type: str
    aggregation_kind: Literal["base_stat", "resource"]
    base_total: str
    ratio_total: str
    flat_total: str
    resource_total: str
    final_value: str
    base_contribution_ids: tuple[str, ...] = ()
    ratio_contribution_ids: tuple[str, ...] = ()
    flat_contribution_ids: tuple[str, ...] = ()
    resource_contribution_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_text(self.property_type, "property_type")
        if self.aggregation_kind not in {"base_stat", "resource"}:
            raise ValueError("invalid aggregation_kind")
        for field_name in (
            "base_total",
            "ratio_total",
            "flat_total",
            "resource_total",
            "final_value",
        ):
            object.__setattr__(
                self,
                field_name,
                canonical_decimal(getattr(self, field_name), field_name),
            )
        for field_name in (
            "base_contribution_ids",
            "ratio_contribution_ids",
            "flat_contribution_ids",
            "resource_contribution_ids",
        ):
            raw_ids = getattr(self, field_name)
            if not isinstance(raw_ids, (list, tuple)) or not all(
                isinstance(item, str) and item for item in raw_ids
            ):
                raise TypeError(f"{field_name} must contain non-empty strings")
            if len(set(raw_ids)) != len(raw_ids):
                raise ValueError(f"{field_name} contains duplicate identities")
            object.__setattr__(self, field_name, tuple(sorted(raw_ids)))
        expected_kind = (
            "base_stat"
            if self.property_type in BASE_STAT_PROPERTY_TYPES
            else "resource"
        )
        if self.aggregation_kind != expected_kind:
            raise ValueError("property type and aggregation kind are inconsistent")
        if self.aggregation_kind == "base_stat":
            if Decimal(self.resource_total) != 0 or self.resource_contribution_ids:
                raise ValueError("base stat aggregate cannot carry resource terms")
            expected = Decimal(self.base_total) * (
                Decimal(1) + Decimal(self.ratio_total)
            ) + Decimal(self.flat_total)
        else:
            if (
                Decimal(self.base_total) != 0
                or Decimal(self.ratio_total) != 0
                or Decimal(self.flat_total) != 0
                or self.base_contribution_ids
                or self.ratio_contribution_ids
                or self.flat_contribution_ids
            ):
                raise ValueError("resource aggregate cannot carry base stat terms")
            expected = Decimal(self.resource_total)
        if self.final_value != canonical_decimal(str(expected), "final_value"):
            raise ValueError("aggregate final_value does not match its typed basis")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "property_type": self.property_type,
            "aggregation_kind": self.aggregation_kind,
            "base_total": self.base_total,
            "ratio_total": self.ratio_total,
            "flat_total": self.flat_total,
            "resource_total": self.resource_total,
            "final_value": self.final_value,
            "base_contribution_ids": list(self.base_contribution_ids),
            "ratio_contribution_ids": list(self.ratio_contribution_ids),
            "flat_contribution_ids": list(self.flat_contribution_ids),
            "resource_contribution_ids": list(self.resource_contribution_ids),
        }


def aggregate_static_stat_contributions(
    contributions: tuple[StaticStatContribution, ...]
    | list[StaticStatContribution],
) -> tuple[StaticStatAggregate, ...]:
    if not isinstance(contributions, (list, tuple)) or not all(
        isinstance(item, StaticStatContribution) for item in contributions
    ):
        raise TypeError(
            "contributions must contain StaticStatContribution values"
        )
    contribution_ids = [item.contribution_id for item in contributions]
    if len(set(contribution_ids)) != len(contribution_ids):
        raise ValueError("contributions contain duplicate identities")
    totals: dict[str, dict[AggregationBasis, Decimal]] = {}
    source_ids: dict[str, dict[AggregationBasis, list[str]]] = {}
    basis_by_pool: dict[ContributionPool, AggregationBasis] = {
        "base": "base",
        "percentage": "ratio",
        "flat": "flat",
        "resource": "resource",
    }
    for contribution in sorted(contributions, key=lambda item: item.sort_key):
        basis = basis_by_pool[contribution.contribution_pool]
        property_totals = totals.setdefault(
            contribution.property_type,
            {
                "base": Decimal(0),
                "ratio": Decimal(0),
                "flat": Decimal(0),
                "resource": Decimal(0),
            },
        )
        property_totals[basis] += Decimal(contribution.exact_value)
        property_sources = source_ids.setdefault(
            contribution.property_type,
            {"base": [], "ratio": [], "flat": [], "resource": []},
        )
        property_sources[basis].append(contribution.contribution_id)
    aggregates: list[StaticStatAggregate] = []
    for property_type in sorted(totals):
        property_totals = totals[property_type]
        property_sources = source_ids[property_type]
        aggregation_kind: Literal["base_stat", "resource"] = (
            "base_stat"
            if property_type in BASE_STAT_PROPERTY_TYPES
            else "resource"
        )
        final = (
            property_totals["base"]
            * (Decimal(1) + property_totals["ratio"])
            + property_totals["flat"]
            if aggregation_kind == "base_stat"
            else property_totals["resource"]
        )
        aggregates.append(
            StaticStatAggregate(
                property_type=property_type,
                aggregation_kind=aggregation_kind,
                base_total=str(property_totals["base"]),
                ratio_total=str(property_totals["ratio"]),
                flat_total=str(property_totals["flat"]),
                resource_total=str(property_totals["resource"]),
                final_value=str(final),
                base_contribution_ids=tuple(property_sources["base"]),
                ratio_contribution_ids=tuple(property_sources["ratio"]),
                flat_contribution_ids=tuple(property_sources["flat"]),
                resource_contribution_ids=tuple(property_sources["resource"]),
            )
        )
    return tuple(aggregates)
