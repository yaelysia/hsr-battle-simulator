from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal, cast

from .immutable_json import FrozenJSONDict, freeze_json, thaw_json
from .ir_types import IRSource, JSONValue


ContributionPool = Literal["base", "percentage", "flat", "resource"]
CalculationKind = Literal["constant", "linear_growth", "ratio", "flat", "resource"]
CONTRIBUTION_POOL_ORDER = {"base": 0, "percentage": 1, "flat": 2, "resource": 3}


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
