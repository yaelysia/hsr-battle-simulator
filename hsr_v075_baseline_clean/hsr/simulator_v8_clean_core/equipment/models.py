from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
from typing import Callable, Generic, Literal, TypeVar, cast

from ..build_types import (
    CalculationKind,
    ContributionPool,
    StaticStatContribution,
    immutable_ir_source,
    ir_source_from_json,
    static_property_binding,
)
from ..immutable_json import FrozenJSONDict, freeze_json, thaw_json
from ..ir_types import CoverageStatus, IRSource, JSONValue


EquipmentDefinitionKind = Literal[
    "character_equipment_eligibility",
    "light_cone",
    "relic_domain",
    "relic_slot",
    "relic_main_affix_group",
    "relic_main_affix",
    "relic_sub_affix_group",
    "relic_sub_affix",
    "relic_template",
    "relic_set",
    "relic_set_threshold",
    "equipment_mechanism",
]
EquipmentResolutionStatus = Literal["resolved", "blocked"]
AssemblyStatus = Literal["assembled", "blocked"]
BattleAdmissionStatus = Literal["admitted", "blocked"]
ActivationStatus = Literal["active", "inactive", "blocked"]
LedgerChannel = Literal["static", "dynamic", "activation"]
LightConePublicationStatus = Literal["published", "unpublished", "status_unknown"]
RelicPublicationStatus = Literal["published", "unpublished", "status_unknown"]
RelicDomain = Literal["outer", "planar"]
RelicTemplateMode = Literal["BASIC", "CUSTOM", "UNKNOWN"]
EquipmentGapClassification = Literal[
    "lowering_gap",
    "admission_gap",
    "implementation_missing",
]
EquipmentBattleBlockerChannel = Literal["static_passive", "dynamic_ability"]

LIGHT_CONE_PUBLICATION_STATES = frozenset(
    {"published", "unpublished", "status_unknown"}
)
LIGHT_CONE_PROMOTION_VALUE_FIELD_ORDER = (
    "base_hp",
    "hp_per_level",
    "base_attack",
    "attack_per_level",
    "base_defence",
    "defence_per_level",
)
LIGHT_CONE_PROMOTION_VALUE_FIELDS = frozenset(
    LIGHT_CONE_PROMOTION_VALUE_FIELD_ORDER
)

EQUIPMENT_DEFINITION_KINDS: frozenset[str] = frozenset(
    {
        "character_equipment_eligibility",
        "light_cone",
        "relic_domain",
        "relic_slot",
        "relic_main_affix_group",
        "relic_main_affix",
        "relic_sub_affix_group",
        "relic_sub_affix",
        "relic_template",
        "relic_set",
        "relic_set_threshold",
        "equipment_mechanism",
    }
)
EQUIPMENT_SOURCE_KINDS = frozenset({"tbgd", "derived", "validation_fixture"})
RELIC_SOURCE_TABLE_PATHS = {
    "relic_config": "ExcelOutput/RelicConfig.json",
    "relic_base_type": "ExcelOutput/RelicBaseType.json",
    "relic_main_affix_config": "ExcelOutput/RelicMainAffixConfig.json",
    "relic_sub_affix_config": "ExcelOutput/RelicSubAffixConfig.json",
    "relic_set_config": "ExcelOutput/RelicSetConfig.json",
    "relic_set_skill_config": "ExcelOutput/RelicSetSkillConfig.json",
}
EQUIPMENT_COVERAGE_STATES = frozenset(
    {
        "discovered_only",
        "lowered",
        "executable",
        "validated",
        "blocked",
        "supported_alias",
        "audit_only",
        "unsupported",
        "skipped_with_reason",
    }
)
EQUIPMENT_RESOLVABLE_COVERAGE_STATES = frozenset(
    {"lowered", "executable", "validated"}
)
FINGERPRINT_REQUIRED_FIELDS = frozenset(
    {"algorithm", "sha256", "file_count", "byte_count", "paths", "coverage"}
)
FINGERPRINT_ALLOWED_FIELDS = FINGERPRINT_REQUIRED_FIELDS | {"schema_version"}
SOURCE_BEHAVIOR_FIELDS = frozenset(
    {
        "activation_status",
        "assembly_status",
        "blocked_reason",
        "coverage_status",
        "definition_identity",
        "definition_kind",
        "execution_status",
        "resolution_status",
    }
)


def _require_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_string(value: object, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")


def _require_integer(value: object, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")


def _require_sha256(value: object, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")


def _typed_tuple(
    value: object,
    expected_type: type[object],
    field_name: str,
) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be a list or tuple")
    detached = tuple(value)
    if not all(isinstance(item, expected_type) for item in detached):
        raise TypeError(
            f"{field_name} members must be {expected_type.__name__} instances"
        )
    return detached


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    return cast(tuple[str, ...], _typed_tuple(value, str, field_name))


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} must be a JSON object")
    return cast(Mapping[str, object], value)


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be a JSON array")
    return cast(Sequence[object], value)


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    return value


def _integer(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")
    return value


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a boolean")
    return value


def _require_exact_fields(
    row: Mapping[str, object],
    expected: frozenset[str],
    field_name: str,
) -> None:
    unknown = sorted(set(row).difference(expected))
    if unknown:
        raise ValueError(f"{field_name} contains unknown fields: {unknown}")


def _canonical_decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("equipment decimal values must be finite")
    if value == 0:
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def exact_decimal_text(value: object, field_name: str = "exact_value") -> str:
    """Validate canonical decimal text at the typed IR/JSON boundary."""

    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be canonical decimal text")
    try:
        decimal_value = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must be a decimal string") from exc
    canonical = _canonical_decimal_text(decimal_value)
    if value != canonical:
        raise ValueError(f"{field_name} must use canonical decimal text")
    return canonical


def raw_exact_decimal_text(value: object, field_name: str = "raw_value") -> str:
    """Project raw JSON numbers; strings and binary floats are never raw numbers."""

    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise TypeError(f"{field_name} must be a raw int or Decimal")
    return _canonical_decimal_text(Decimal(value))


def _optional_mapping(value: object, field_name: str) -> Mapping[str, object] | None:
    if value is None:
        return None
    return _mapping(value, field_name)


def _freeze_mapping(value: Mapping[str, JSONValue]) -> FrozenJSONDict:
    return cast(FrozenJSONDict, freeze_json(dict(value)))


def _json_mapping(value: Mapping[str, object]) -> dict[str, JSONValue]:
    return cast(dict[str, JSONValue], thaw_json(value))


def _canonical_fingerprint(value: Mapping[str, JSONValue]) -> str:
    raw = json.dumps(
        thaw_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_equipment_source_fingerprint(value: Mapping[str, object]) -> None:
    unknown = sorted(set(value).difference(FINGERPRINT_ALLOWED_FIELDS))
    if unknown:
        raise ValueError(f"source fingerprint contains unknown fields: {unknown}")
    missing = sorted(FINGERPRINT_REQUIRED_FIELDS.difference(value))
    if missing:
        raise ValueError(f"source fingerprint missing fields: {missing}")
    sha256 = value.get("sha256")
    _require_sha256(sha256, "source fingerprint sha256")
    if not isinstance(value.get("algorithm"), str) or not value.get("algorithm"):
        raise ValueError("source fingerprint algorithm is missing")
    if not isinstance(value.get("coverage"), str) or not value.get("coverage"):
        raise ValueError("source fingerprint coverage is missing")
    file_count = value.get("file_count")
    byte_count = value.get("byte_count")
    paths = value.get("paths")
    if not isinstance(file_count, int) or isinstance(file_count, bool) or file_count <= 0:
        raise ValueError("source fingerprint file_count must be positive")
    if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count <= 0:
        raise ValueError("source fingerprint byte_count must be positive")
    if not isinstance(paths, (list, tuple)) or not paths or not all(isinstance(path, str) and path for path in paths):
        raise ValueError("source fingerprint paths must be a non-empty string array")
    if len(paths) != file_count:
        raise ValueError("source fingerprint file_count must equal the number of paths")
    if len(set(paths)) != len(paths):
        raise ValueError("source fingerprint paths must be unique")


def make_equipment_source(
    *,
    source_path: str,
    raw_type: str,
    raw_id: str,
    json_path: str,
    source_fingerprint: Mapping[str, JSONValue],
    source_kind: Literal["tbgd", "derived", "validation_fixture"] = "tbgd",
) -> IRSource:
    _require_text(source_path, "source_path")
    _require_text(raw_type, "raw_type")
    _require_text(raw_id, "raw_id")
    _require_text(json_path, "json_path")
    _require_string(source_kind, "source_kind")
    if source_kind not in EQUIPMENT_SOURCE_KINDS:
        raise ValueError(f"unsupported equipment source_kind {source_kind!r}")
    validate_equipment_source_fingerprint(cast(Mapping[str, object], source_fingerprint))
    evidence = _freeze_mapping(
        {
            "json_path": json_path,
            "source_kind": source_kind,
            "source_fingerprint": cast(dict[str, JSONValue], thaw_json(source_fingerprint)),
        }
    )
    return IRSource(
        source_path=source_path,
        raw_type=raw_type,
        raw_id=raw_id,
        evidence=evidence,
    )


def _require_equipment_source(source: IRSource) -> None:
    if not isinstance(source, IRSource):
        raise TypeError("equipment source must be an IRSource")
    _require_text(source.source_path, "source.source_path")
    _require_text(source.raw_type, "source.raw_type")
    _require_text(source.raw_id, "source.raw_id")
    if not isinstance(source.evidence, FrozenJSONDict):
        raise TypeError("equipment source evidence must be recursively frozen at the creation boundary")
    _require_exact_fields(
        source.evidence,
        frozenset({"json_path", "source_kind", "source_fingerprint"}),
        "equipment source evidence",
    )
    forbidden_fields = sorted(SOURCE_BEHAVIOR_FIELDS.intersection(source.evidence))
    if forbidden_fields:
        raise ValueError(
            "equipment source evidence cannot control lookup, activation, or execution: "
            f"{forbidden_fields}"
        )
    json_path = source.evidence.get("json_path")
    source_kind = source.evidence.get("source_kind")
    fingerprint = source.evidence.get("source_fingerprint")
    _require_text(json_path, "source.evidence.json_path")
    _require_string(source_kind, "source.evidence.source_kind")
    if source_kind not in EQUIPMENT_SOURCE_KINDS:
        raise ValueError("equipment source evidence has an invalid source_kind")
    validate_equipment_source_fingerprint(_mapping(fingerprint, "source.evidence.source_fingerprint"))


def _source_kind(source: IRSource) -> str:
    return cast(str, source.evidence.get("source_kind"))


def _require_source_fingerprint_path(source: IRSource) -> None:
    fingerprint = _mapping(
        source.evidence.get("source_fingerprint"),
        "source.evidence.source_fingerprint",
    )
    paths = fingerprint.get("paths")
    if (
        not isinstance(paths, (list, tuple))
        or source.source_path not in paths
    ):
        raise ValueError(
            "TBGD equipment source path must belong to its source fingerprint"
        )


def _require_equipment_ability_record_source(
    source: IRSource,
    *,
    ability_name: str,
    record_index: int,
) -> None:
    """Require a real TBGD AbilityList record or an explicit test fixture."""

    _require_equipment_source(source)
    source_kind = _source_kind(source)
    if source_kind not in {"tbgd", "validation_fixture"}:
        raise ValueError(
            "equipment ability records cannot use derived provenance"
        )
    if source.raw_type != "AbilityList" or source.raw_id != ability_name:
        raise ValueError(
            "ability source must identify the matching AbilityList record"
        )
    if source.evidence.get("json_path") != f"$.AbilityList[{record_index}]":
        raise ValueError("ability source json_path must match record_index")
    if source_kind == "validation_fixture":
        return
    source_path = PurePosixPath(source.source_path)
    if (
        source_path.is_absolute()
        or ".." in source_path.parts
        or source.source_path != source_path.as_posix()
        or not source.source_path.startswith("Config/ConfigAbility/Equip/")
        or source_path.suffix != ".json"
        or source_path.name.endswith(".layout.json")
    ):
        raise ValueError(
            "TBGD ability source is outside the equipment ability namespace"
        )
    _require_source_fingerprint_path(source)


def _indexed_json_path_matches(value: object, suffix: str) -> bool:
    if not isinstance(value, str) or not value.startswith("$["):
        return False
    index_text, separator, remainder = value[2:].partition("]")
    return bool(separator) and index_text.isdigit() and remainder == suffix


def _require_relic_record_source(
    source: IRSource,
    *,
    source_role: str,
    raw_type: str,
    raw_id: str | None = None,
    raw_id_suffix: str = "",
    json_path_suffix: str = "",
) -> None:
    """Bind a real relic definition to the exact TBGD record identity."""

    if _source_kind(source) == "validation_fixture":
        return
    if _source_kind(source) != "tbgd":
        raise ValueError("raw relic definitions require a TBGD record source")
    expected_path = RELIC_SOURCE_TABLE_PATHS[source_role]
    if source.source_path != expected_path or source.raw_type != raw_type:
        raise ValueError("relic source table or raw_type does not match definition")
    if raw_id is not None:
        if source.raw_id != raw_id:
            raise ValueError("relic source raw_id does not match definition identity")
    elif raw_id_suffix and not source.raw_id.endswith(raw_id_suffix):
        raise ValueError("relic source raw_id suffix does not match nested identity")
    if not _indexed_json_path_matches(
        source.evidence.get("json_path"),
        json_path_suffix,
    ):
        raise ValueError("relic source json_path does not match record position")
    _require_source_fingerprint_path(source)


def _require_relic_derived_source(
    source: IRSource,
    *,
    source_role: str,
    raw_type: str,
    raw_id: str,
) -> None:
    """Require aggregate directory objects to declare derived provenance."""

    if _source_kind(source) == "validation_fixture":
        return
    if _source_kind(source) != "derived":
        raise ValueError("aggregate relic definitions require derived provenance")
    if (
        source.source_path != RELIC_SOURCE_TABLE_PATHS[source_role]
        or source.raw_type != raw_type
        or source.raw_id != raw_id
        or source.evidence.get("json_path") != "$"
    ):
        raise ValueError("derived relic source identity does not match projection")
    _require_source_fingerprint_path(source)


def _source_row_json_path(source: IRSource) -> str:
    json_path = source.evidence.get("json_path")
    if not isinstance(json_path, str) or not _indexed_json_path_matches(
        json_path,
        "",
    ):
        raise ValueError("relic source must identify one table row")
    return json_path


def _source_from_json(value: object) -> IRSource:
    source = _mapping(value, "source")
    _require_exact_fields(
        source,
        frozenset({"source_path", "raw_type", "raw_id", "evidence"}),
        "source",
    )
    evidence = _mapping(source.get("evidence"), "source.evidence")
    _require_exact_fields(
        evidence,
        frozenset({"json_path", "source_kind", "source_fingerprint"}),
        "source.evidence",
    )
    fingerprint = _mapping(evidence.get("source_fingerprint"), "source.evidence.source_fingerprint")
    source_kind = _text(evidence.get("source_kind"), "source.evidence.source_kind")
    if source_kind not in EQUIPMENT_SOURCE_KINDS:
        raise ValueError(f"unsupported equipment source_kind {source_kind!r}")
    return make_equipment_source(
        source_path=_text(source.get("source_path"), "source.source_path"),
        raw_type=_text(source.get("raw_type"), "source.raw_type"),
        raw_id=_text(source.get("raw_id"), "source.raw_id"),
        json_path=_text(evidence.get("json_path"), "source.evidence.json_path"),
        source_fingerprint=_json_mapping(fingerprint),
        source_kind=cast(Literal["tbgd", "derived", "validation_fixture"], source_kind),
    )


def _validate_coverage(status: CoverageStatus, blocked_reason: str) -> None:
    _require_string(status, "coverage_status")
    if status not in EQUIPMENT_COVERAGE_STATES:
        raise ValueError(f"invalid equipment coverage_status {status!r}")
    _require_string(blocked_reason, "blocked_reason")
    if status == "blocked" and not blocked_reason:
        raise ValueError("blocked equipment objects require blocked_reason")


def _equipment_key_tuple(
    value: object,
    expected_kind: EquipmentDefinitionKind,
    field_name: str,
    *,
    require_non_empty: bool = False,
) -> tuple[EquipmentDefinitionKey, ...]:
    keys = cast(
        tuple[EquipmentDefinitionKey, ...],
        _typed_tuple(value, EquipmentDefinitionKey, field_name),
    )
    for key in keys:
        _require_kind(key, expected_kind)
    if require_non_empty and not keys:
        raise ValueError(f"{field_name} must be non-empty")
    if len(keys) != len(set(keys)):
        raise ValueError(f"{field_name} must contain unique keys")
    if keys != tuple(sorted(keys, key=lambda item: item.stable_id)):
        raise ValueError(f"{field_name} must use canonical key order")
    return keys


def _validate_relic_definition_coverage(
    status: CoverageStatus,
    blocked_reason: str,
) -> None:
    _validate_coverage(status, blocked_reason)
    if status not in {"lowered", "blocked"}:
        raise ValueError("relic definition coverage must be lowered or blocked")
    if status == "lowered" and blocked_reason:
        raise ValueError("lowered relic definitions cannot carry blocked_reason")


def _require_matching_source_fingerprints(sources: Sequence[IRSource], field_name: str) -> None:
    if not sources:
        return
    fingerprints = [source.evidence.get("source_fingerprint") for source in sources]
    if any(value != fingerprints[0] for value in fingerprints[1:]):
        raise ValueError(f"{field_name} sources must share one source fingerprint")


@dataclass(frozen=True, order=True)
class EquipmentDefinitionKey:
    definition_kind: EquipmentDefinitionKind
    definition_identity: str

    def __post_init__(self) -> None:
        _require_string(self.definition_kind, "definition_kind")
        if self.definition_kind not in EQUIPMENT_DEFINITION_KINDS:
            raise ValueError(f"unsupported equipment definition kind {self.definition_kind!r}")
        _require_text(self.definition_identity, "definition_identity")

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
    def from_json(cls, value: object) -> EquipmentDefinitionKey:
        row = _mapping(value, "definition_key")
        _require_exact_fields(
            row,
            frozenset({"definition_kind", "definition_identity", "stable_id"}),
            "definition_key",
        )
        result = cls(
            definition_kind=cast(
                EquipmentDefinitionKind,
                _text(row.get("definition_kind"), "definition_key.definition_kind"),
            ),
            definition_identity=_text(
                row.get("definition_identity"),
                "definition_key.definition_identity",
            ),
        )
        stable_id = _text(row.get("stable_id"), "definition_key.stable_id")
        if stable_id != result.stable_id:
            raise ValueError("definition_key.stable_id does not match canonical identity")
        return result


@dataclass(frozen=True)
class CharacterEquipmentEligibilityIR:
    definition_key: EquipmentDefinitionKey
    character_card_id: str
    character_profile_id: str
    character_path_type: str
    passive_activation_path_types: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = "character_equipment_eligibility_not_lowered"

    def __post_init__(self) -> None:
        _require_kind(self.definition_key, "character_equipment_eligibility")
        _require_text(self.character_card_id, "character_card_id")
        if self.definition_key.definition_identity != self.character_card_id:
            raise ValueError("character equipment eligibility identity must match character_card_id")
        _require_text(self.character_profile_id, "character_profile_id")
        _require_text(self.character_path_type, "character_path_type")
        object.__setattr__(
            self,
            "passive_activation_path_types",
            _string_tuple(
                self.passive_activation_path_types,
                "passive_activation_path_types",
            ),
        )
        if not self.passive_activation_path_types:
            raise ValueError("character equipment eligibility requires activation path types")
        if len(set(self.passive_activation_path_types)) != len(
            self.passive_activation_path_types
        ):
            raise ValueError("passive activation path types must be unique")
        if self.character_path_type not in self.passive_activation_path_types:
            raise ValueError("character path must be present in passive activation path types")
        object.__setattr__(self, "source", immutable_ir_source(self.source))
        _validate_coverage(self.coverage_status, self.blocked_reason)

    def to_json(self) -> dict[str, JSONValue]:
        return _definition_json(
            self.definition_key,
            self.source,
            self.coverage_status,
            self.blocked_reason,
            {
                "character_card_id": self.character_card_id,
                "character_profile_id": self.character_profile_id,
                "character_path_type": self.character_path_type,
                "passive_activation_path_types": list(
                    self.passive_activation_path_types
                ),
            },
        )

    @classmethod
    def from_json(cls, value: object) -> CharacterEquipmentEligibilityIR:
        row = _mapping(value, "character_equipment_eligibility")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "definition_key",
                    "character_card_id",
                    "character_profile_id",
                    "character_path_type",
                    "passive_activation_path_types",
                    "source",
                    "coverage_status",
                    "blocked_reason",
                }
            ),
            "character_equipment_eligibility",
        )
        return cls(
            definition_key=EquipmentDefinitionKey.from_json(row.get("definition_key")),
            character_card_id=_text(row.get("character_card_id"), "character_card_id"),
            character_profile_id=_text(
                row.get("character_profile_id"), "character_profile_id"
            ),
            character_path_type=_text(
                row.get("character_path_type"), "character_path_type"
            ),
            passive_activation_path_types=tuple(
                _text(item, "passive_activation_path_types[]")
                for item in _sequence(
                    row.get("passive_activation_path_types"),
                    "passive_activation_path_types",
                )
            ),
            source=ir_source_from_json(row.get("source")),
            coverage_status=_coverage_from_json(row),
            blocked_reason=_text(row.get("blocked_reason", ""), "blocked_reason"),
        )


@dataclass(frozen=True)
class LightConePromotionValueIR:
    field_name: str
    exact_value: str
    source: IRSource

    def __post_init__(self) -> None:
        if self.field_name not in LIGHT_CONE_PROMOTION_VALUE_FIELDS:
            raise ValueError(f"unsupported light-cone promotion value field {self.field_name!r}")
        exact_decimal_text(self.exact_value, f"promotion_values.{self.field_name}")
        _require_equipment_source(self.source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "field_name": self.field_name,
            "exact_value": self.exact_value,
            "source": self.source.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> LightConePromotionValueIR:
        row = _mapping(value, "light_cone_promotion_value")
        _require_exact_fields(
            row,
            frozenset({"field_name", "exact_value", "source"}),
            "light_cone_promotion_value",
        )
        return cls(
            field_name=_text(row.get("field_name"), "field_name"),
            exact_value=_text(row.get("exact_value"), "exact_value"),
            source=_source_from_json(row.get("source")),
        )


@dataclass(frozen=True)
class LightConePromotionTierIR:
    promotion_stage: int
    promotion_field_present: bool
    max_level: int
    stat_values: tuple[LightConePromotionValueIR, ...]
    source: IRSource

    def __post_init__(self) -> None:
        _require_integer(self.promotion_stage, "promotion_stage")
        if self.promotion_stage < 0:
            raise ValueError("promotion_stage must be non-negative")
        _boolean(self.promotion_field_present, "promotion_field_present")
        if not self.promotion_field_present and self.promotion_stage != 0:
            raise ValueError("missing Promotion field is only valid for stage zero")
        _require_integer(self.max_level, "max_level")
        if self.max_level <= 0:
            raise ValueError("light-cone promotion max_level must be positive")
        values = cast(
            tuple[LightConePromotionValueIR, ...],
            _typed_tuple(self.stat_values, LightConePromotionValueIR, "stat_values"),
        )
        object.__setattr__(self, "stat_values", values)
        fields = tuple(item.field_name for item in values)
        if fields != LIGHT_CONE_PROMOTION_VALUE_FIELD_ORDER:
            raise ValueError(
                "light-cone promotion tier requires each exact stat field once in canonical order"
            )
        _require_equipment_source(self.source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "promotion_stage": self.promotion_stage,
            "promotion_field_present": self.promotion_field_present,
            "max_level": self.max_level,
            "stat_values": [item.to_json() for item in self.stat_values],
            "source": self.source.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> LightConePromotionTierIR:
        row = _mapping(value, "light_cone_promotion_tier")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "promotion_stage",
                    "promotion_field_present",
                    "max_level",
                    "stat_values",
                    "source",
                }
            ),
            "light_cone_promotion_tier",
        )
        return cls(
            promotion_stage=_integer(row.get("promotion_stage"), "promotion_stage"),
            promotion_field_present=_boolean(
                row.get("promotion_field_present"), "promotion_field_present"
            ),
            max_level=_integer(row.get("max_level"), "max_level"),
            stat_values=tuple(
                LightConePromotionValueIR.from_json(item)
                for item in _sequence(row.get("stat_values"), "stat_values")
            ),
            source=_source_from_json(row.get("source")),
        )


@dataclass(frozen=True)
class LightConeParameterIR:
    parameter_index: int
    exact_value: str
    source: IRSource

    def __post_init__(self) -> None:
        _require_integer(self.parameter_index, "parameter_index")
        if self.parameter_index < 0:
            raise ValueError("parameter_index must be non-negative")
        exact_decimal_text(self.exact_value, "parameter exact_value")
        _require_equipment_source(self.source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "parameter_index": self.parameter_index,
            "exact_value": self.exact_value,
            "source": self.source.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> LightConeParameterIR:
        row = _mapping(value, "light_cone_parameter")
        _require_exact_fields(
            row,
            frozenset({"parameter_index", "exact_value", "source"}),
            "light_cone_parameter",
        )
        return cls(
            parameter_index=_integer(row.get("parameter_index"), "parameter_index"),
            exact_value=_text(row.get("exact_value"), "exact_value"),
            source=_source_from_json(row.get("source")),
        )


@dataclass(frozen=True)
class LightConeStaticPropertyIR:
    property_index: int
    property_type: str
    contribution_pool: ContributionPool
    canonical_property_type: str
    calculation_kind: CalculationKind
    exact_value: str
    source: IRSource

    def __post_init__(self) -> None:
        _require_integer(self.property_index, "property_index")
        if self.property_index < 0:
            raise ValueError("property_index must be non-negative")
        _require_text(self.property_type, "property_type")
        binding = static_property_binding(self.property_type)
        if binding is None:
            raise ValueError(
                f"light-cone static property type is not admitted: {self.property_type}"
            )
        if (
            self.contribution_pool != binding.contribution_pool
            or self.canonical_property_type != binding.canonical_property_type
            or self.calculation_kind != binding.calculation_kind
        ):
            raise ValueError("light-cone static property binding does not match the shared mapping")
        exact_decimal_text(self.exact_value, "static property exact_value")
        _require_equipment_source(self.source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "property_index": self.property_index,
            "property_type": self.property_type,
            "contribution_pool": self.contribution_pool,
            "canonical_property_type": self.canonical_property_type,
            "calculation_kind": self.calculation_kind,
            "exact_value": self.exact_value,
            "source": self.source.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> LightConeStaticPropertyIR:
        row = _mapping(value, "light_cone_static_property")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "property_index",
                    "property_type",
                    "contribution_pool",
                    "canonical_property_type",
                    "calculation_kind",
                    "exact_value",
                    "source",
                }
            ),
            "light_cone_static_property",
        )
        return cls(
            property_index=_integer(row.get("property_index"), "property_index"),
            property_type=_text(row.get("property_type"), "property_type"),
            contribution_pool=cast(
                ContributionPool,
                _text(row.get("contribution_pool"), "contribution_pool"),
            ),
            canonical_property_type=_text(
                row.get("canonical_property_type"), "canonical_property_type"
            ),
            calculation_kind=cast(
                CalculationKind,
                _text(row.get("calculation_kind"), "calculation_kind"),
            ),
            exact_value=_text(row.get("exact_value"), "exact_value"),
            source=_source_from_json(row.get("source")),
        )


@dataclass(frozen=True)
class LightConeSuperimpositionLevelIR:
    skill_id: str
    level: int
    ability_name: str
    skill_name_hash: str
    skill_description_hash: str
    parameters: tuple[LightConeParameterIR, ...]
    static_properties: tuple[LightConeStaticPropertyIR, ...]
    source: IRSource

    def __post_init__(self) -> None:
        _require_text(self.skill_id, "skill_id")
        _require_integer(self.level, "superimposition level")
        if self.level <= 0:
            raise ValueError("superimposition level must be positive")
        _require_text(self.ability_name, "ability_name")
        _require_text(self.skill_name_hash, "skill_name_hash")
        _require_text(self.skill_description_hash, "skill_description_hash")
        parameters = cast(
            tuple[LightConeParameterIR, ...],
            _typed_tuple(self.parameters, LightConeParameterIR, "parameters"),
        )
        properties = cast(
            tuple[LightConeStaticPropertyIR, ...],
            _typed_tuple(
                self.static_properties,
                LightConeStaticPropertyIR,
                "static_properties",
            ),
        )
        if tuple(item.parameter_index for item in parameters) != tuple(range(len(parameters))):
            raise ValueError("light-cone parameter indices must be contiguous and ordered")
        if tuple(item.property_index for item in properties) != tuple(range(len(properties))):
            raise ValueError("light-cone property indices must be contiguous and ordered")
        rank_json_path = self.source.evidence.get("json_path")
        if (
            self.source.raw_type == "EquipmentSkillConfig"
            and isinstance(rank_json_path, str)
            and rank_json_path
            and any(
                item.source.raw_type != "EquipmentSkillStaticProperty"
                or item.source.raw_id
                != f"{self.skill_id}:{self.level}:{item.property_index}"
                or item.source.source_path != self.source.source_path
                or item.source.evidence.get("json_path")
                != (
                    f"{rank_json_path}.AbilityProperty["
                    f"{item.property_index}].Value.Value"
                )
                for item in properties
            )
        ):
            raise ValueError("light-cone static property source does not match its rank row")
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "static_properties", properties)
        _require_equipment_source(self.source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "skill_id": self.skill_id,
            "level": self.level,
            "ability_name": self.ability_name,
            "skill_name_hash": self.skill_name_hash,
            "skill_description_hash": self.skill_description_hash,
            "parameters": [item.to_json() for item in self.parameters],
            "static_properties": [item.to_json() for item in self.static_properties],
            "source": self.source.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> LightConeSuperimpositionLevelIR:
        row = _mapping(value, "light_cone_superimposition_level")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "skill_id",
                    "level",
                    "ability_name",
                    "skill_name_hash",
                    "skill_description_hash",
                    "parameters",
                    "static_properties",
                    "source",
                }
            ),
            "light_cone_superimposition_level",
        )
        return cls(
            skill_id=_text(row.get("skill_id"), "skill_id"),
            level=_integer(row.get("level"), "level"),
            ability_name=_text(row.get("ability_name"), "ability_name"),
            skill_name_hash=_text(row.get("skill_name_hash"), "skill_name_hash"),
            skill_description_hash=_text(
                row.get("skill_description_hash"), "skill_description_hash"
            ),
            parameters=tuple(
                LightConeParameterIR.from_json(item)
                for item in _sequence(row.get("parameters"), "parameters")
            ),
            static_properties=tuple(
                LightConeStaticPropertyIR.from_json(item)
                for item in _sequence(row.get("static_properties"), "static_properties")
            ),
            source=_source_from_json(row.get("source")),
        )


@dataclass(frozen=True)
class LightConeAbilitySourceIR:
    ability_name: str
    record_index: int
    source: IRSource

    def __post_init__(self) -> None:
        _require_text(self.ability_name, "ability_name")
        _require_integer(self.record_index, "ability record_index")
        if self.record_index < 0:
            raise ValueError("ability record_index must be non-negative")
        _require_equipment_ability_record_source(
            self.source,
            ability_name=self.ability_name,
            record_index=self.record_index,
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ability_name": self.ability_name,
            "record_index": self.record_index,
            "source": self.source.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> LightConeAbilitySourceIR:
        row = _mapping(value, "light_cone_ability_source")
        _require_exact_fields(
            row,
            frozenset({"ability_name", "record_index", "source"}),
            "light_cone_ability_source",
        )
        return cls(
            ability_name=_text(row.get("ability_name"), "ability_name"),
            record_index=_integer(row.get("record_index"), "record_index"),
            source=_source_from_json(row.get("source")),
        )


@dataclass(frozen=True)
class LightConeDefinitionIR:
    definition_key: EquipmentDefinitionKey
    raw_equipment_id: str
    publication_status: LightConePublicationStatus
    release_field_present: bool
    equipment_name_hash: str
    path_type: str
    rarity: str
    max_promotion: int
    max_superimposition: int
    skill_id: str
    promotion_tiers: tuple[LightConePromotionTierIR, ...]
    superimposition_levels: tuple[LightConeSuperimpositionLevelIR, ...]
    ability_source: LightConeAbilitySourceIR | None
    mechanism_ref_ids: tuple[EquipmentDefinitionKey, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = "light_cone_definition_not_lowered"

    def __post_init__(self) -> None:
        _require_kind(self.definition_key, "light_cone")
        _require_text(self.raw_equipment_id, "raw_equipment_id")
        if self.definition_key.definition_identity != self.raw_equipment_id:
            raise ValueError("light-cone definition identity must match raw_equipment_id")
        if self.publication_status not in LIGHT_CONE_PUBLICATION_STATES:
            raise ValueError(f"invalid light-cone publication_status {self.publication_status!r}")
        _boolean(self.release_field_present, "release_field_present")
        if self.publication_status in {"published", "unpublished"} and not self.release_field_present:
            raise ValueError("published/unpublished light-cone status requires the raw Release field")
        if not self.release_field_present and self.publication_status != "status_unknown":
            raise ValueError("missing raw Release field must remain status_unknown")
        _require_text(self.equipment_name_hash, "equipment_name_hash")
        _require_text(self.path_type, "path_type")
        _require_text(self.rarity, "rarity")
        _require_integer(self.max_promotion, "max_promotion")
        _require_integer(self.max_superimposition, "max_superimposition")
        if self.max_promotion < 0 or self.max_superimposition <= 0:
            raise ValueError("light-cone max promotion/rank values are invalid")
        _require_text(self.skill_id, "skill_id")
        promotion_tiers = cast(
            tuple[LightConePromotionTierIR, ...],
            _typed_tuple(self.promotion_tiers, LightConePromotionTierIR, "promotion_tiers"),
        )
        levels = cast(
            tuple[LightConeSuperimpositionLevelIR, ...],
            _typed_tuple(
                self.superimposition_levels,
                LightConeSuperimpositionLevelIR,
                "superimposition_levels",
            ),
        )
        mechanisms = cast(
            tuple[EquipmentDefinitionKey, ...],
            _typed_tuple(
                self.mechanism_ref_ids,
                EquipmentDefinitionKey,
                "mechanism_ref_ids",
            ),
        )
        for key in mechanisms:
            _require_kind(key, "equipment_mechanism")
        if len(mechanisms) != len(set(mechanisms)):
            raise ValueError("light-cone mechanism references must be unique")
        if self.ability_source is not None and not isinstance(
            self.ability_source, LightConeAbilitySourceIR
        ):
            raise TypeError("ability_source must be LightConeAbilitySourceIR or None")
        object.__setattr__(self, "promotion_tiers", promotion_tiers)
        object.__setattr__(self, "superimposition_levels", levels)
        object.__setattr__(self, "mechanism_ref_ids", mechanisms)
        _require_equipment_source(self.source)
        _validate_coverage(self.coverage_status, self.blocked_reason)
        if self.coverage_status == "lowered":
            if self.blocked_reason:
                raise ValueError("lowered light-cone definitions cannot have blocked_reason")
            if tuple(item.promotion_stage for item in promotion_tiers) != tuple(
                range(self.max_promotion + 1)
            ):
                raise ValueError("lowered light-cone promotion tiers must be complete and ordered")
            if tuple(item.level for item in levels) != tuple(
                range(1, self.max_superimposition + 1)
            ):
                raise ValueError("lowered light-cone superimposition levels must be complete and ordered")
            if any(item.skill_id != self.skill_id for item in levels):
                raise ValueError("lowered light-cone superimposition skill identity mismatch")
            ability_names = {item.ability_name for item in levels}
            if self.ability_source is None or ability_names != {self.ability_source.ability_name}:
                raise ValueError("lowered light-cone ability source must match every rank row")
            sources: list[IRSource] = [self.source]
            sources.extend(item.source for item in promotion_tiers)
            sources.extend(value.source for item in promotion_tiers for value in item.stat_values)
            sources.extend(item.source for item in levels)
            sources.extend(value.source for item in levels for value in item.parameters)
            sources.extend(value.source for item in levels for value in item.static_properties)
            sources.append(self.ability_source.source)
            fingerprints = [item.evidence.get("source_fingerprint") for item in sources]
            if any(value != fingerprints[0] for value in fingerprints[1:]):
                raise ValueError("lowered light-cone sources must share one source content fingerprint")

    def to_json(self) -> dict[str, JSONValue]:
        return _definition_json(
            self.definition_key,
            self.source,
            self.coverage_status,
            self.blocked_reason,
            {
                "raw_equipment_id": self.raw_equipment_id,
                "publication_status": self.publication_status,
                "release_field_present": self.release_field_present,
                "equipment_name_hash": self.equipment_name_hash,
                "path_type": self.path_type,
                "rarity": self.rarity,
                "max_promotion": self.max_promotion,
                "max_superimposition": self.max_superimposition,
                "skill_id": self.skill_id,
                "promotion_tiers": [item.to_json() for item in self.promotion_tiers],
                "superimposition_levels": [
                    item.to_json() for item in self.superimposition_levels
                ],
                "ability_source": self.ability_source.to_json()
                if self.ability_source is not None
                else None,
                "mechanism_ref_ids": [key.to_json() for key in self.mechanism_ref_ids],
            },
        )

    @classmethod
    def from_json(cls, value: object) -> LightConeDefinitionIR:
        row = _mapping(value, "light_cone_definition")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "definition_key",
                    "raw_equipment_id",
                    "publication_status",
                    "release_field_present",
                    "equipment_name_hash",
                    "path_type",
                    "rarity",
                    "max_promotion",
                    "max_superimposition",
                    "skill_id",
                    "promotion_tiers",
                    "superimposition_levels",
                    "ability_source",
                    "mechanism_ref_ids",
                    "source",
                    "coverage_status",
                    "blocked_reason",
                }
            ),
            "light_cone_definition",
        )
        ability_source = row.get("ability_source")
        return cls(
            definition_key=EquipmentDefinitionKey.from_json(row.get("definition_key")),
            raw_equipment_id=_text(row.get("raw_equipment_id"), "raw_equipment_id"),
            publication_status=cast(
                LightConePublicationStatus,
                _text(row.get("publication_status"), "publication_status"),
            ),
            release_field_present=_boolean(
                row.get("release_field_present"), "release_field_present"
            ),
            equipment_name_hash=_text(row.get("equipment_name_hash"), "equipment_name_hash"),
            path_type=_text(row.get("path_type"), "path_type"),
            rarity=_text(row.get("rarity"), "rarity"),
            max_promotion=_integer(row.get("max_promotion"), "max_promotion"),
            max_superimposition=_integer(
                row.get("max_superimposition"), "max_superimposition"
            ),
            skill_id=_text(row.get("skill_id"), "skill_id"),
            promotion_tiers=tuple(
                LightConePromotionTierIR.from_json(item)
                for item in _sequence(row.get("promotion_tiers"), "promotion_tiers")
            ),
            superimposition_levels=tuple(
                LightConeSuperimpositionLevelIR.from_json(item)
                for item in _sequence(
                    row.get("superimposition_levels"), "superimposition_levels"
                )
            ),
            ability_source=LightConeAbilitySourceIR.from_json(ability_source)
            if ability_source is not None
            else None,
            mechanism_ref_ids=tuple(
                EquipmentDefinitionKey.from_json(item)
                for item in _sequence(row.get("mechanism_ref_ids"), "mechanism_ref_ids")
            ),
            source=_source_from_json(row.get("source")),
            coverage_status=_coverage_from_json(row),
            blocked_reason=_text(row.get("blocked_reason", ""), "blocked_reason"),
        )


@dataclass(frozen=True)
class RelicSlotFilterIR:
    filter_identity: str
    allowed_property_types: tuple[str, ...]
    source: IRSource

    def __post_init__(self) -> None:
        _require_text(self.filter_identity, "relic slot filter identity")
        properties = _string_tuple(
            self.allowed_property_types,
            "relic slot filter allowed_property_types",
        )
        if not properties or len(properties) != len(set(properties)):
            raise ValueError("relic slot filter properties must be non-empty and unique")
        object.__setattr__(self, "allowed_property_types", properties)
        _require_equipment_source(self.source)
        _require_relic_record_source(
            self.source,
            source_role="relic_base_type",
            raw_type="RelicBaseType",
            raw_id=self.filter_identity,
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "filter_identity": self.filter_identity,
            "allowed_property_types": list(self.allowed_property_types),
            "source": self.source.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> RelicSlotFilterIR:
        row = _mapping(value, "relic_slot_filter")
        _require_exact_fields(
            row,
            frozenset({"filter_identity", "allowed_property_types", "source"}),
            "relic_slot_filter",
        )
        return cls(
            filter_identity=_text(row.get("filter_identity"), "filter_identity"),
            allowed_property_types=tuple(
                _text(item, "allowed_property_types[]")
                for item in _sequence(
                    row.get("allowed_property_types"),
                    "allowed_property_types",
                )
            ),
            source=_source_from_json(row.get("source")),
        )


@dataclass(frozen=True)
class RelicDomainDefinitionIR:
    definition_key: EquipmentDefinitionKey
    domain: RelicDomain
    slot_keys: tuple[EquipmentDefinitionKey, ...]
    set_keys: tuple[EquipmentDefinitionKey, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = "relic_domain_definition_not_lowered"

    def __post_init__(self) -> None:
        _require_kind(self.definition_key, "relic_domain")
        if self.domain not in {"outer", "planar"}:
            raise ValueError("relic domain must be outer or planar")
        if self.definition_key.definition_identity != self.domain:
            raise ValueError("relic domain identity must match domain")
        slots = _equipment_key_tuple(
            self.slot_keys,
            "relic_slot",
            "relic domain slot_keys",
            require_non_empty=True,
        )
        sets = _equipment_key_tuple(
            self.set_keys,
            "relic_set",
            "relic domain set_keys",
            require_non_empty=True,
        )
        object.__setattr__(self, "slot_keys", slots)
        object.__setattr__(self, "set_keys", sets)
        _require_equipment_source(self.source)
        _require_relic_derived_source(
            self.source,
            source_role="relic_config",
            raw_type="RelicDomainMembershipProjection",
            raw_id=self.domain,
        )
        _validate_relic_definition_coverage(
            self.coverage_status,
            self.blocked_reason,
        )

    def to_json(self) -> dict[str, JSONValue]:
        return _definition_json(
            self.definition_key,
            self.source,
            self.coverage_status,
            self.blocked_reason,
            {
                "domain": self.domain,
                "slot_keys": [key.to_json() for key in self.slot_keys],
                "set_keys": [key.to_json() for key in self.set_keys],
            },
        )

    @classmethod
    def from_json(cls, value: object) -> RelicDomainDefinitionIR:
        row = _mapping(value, "relic_domain_definition")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "definition_key",
                    "domain",
                    "slot_keys",
                    "set_keys",
                    "source",
                    "coverage_status",
                    "blocked_reason",
                }
            ),
            "relic_domain_definition",
        )
        return cls(
            definition_key=EquipmentDefinitionKey.from_json(row.get("definition_key")),
            domain=cast(RelicDomain, _text(row.get("domain"), "domain")),
            slot_keys=tuple(
                EquipmentDefinitionKey.from_json(item)
                for item in _sequence(row.get("slot_keys"), "slot_keys")
            ),
            set_keys=tuple(
                EquipmentDefinitionKey.from_json(item)
                for item in _sequence(row.get("set_keys"), "set_keys")
            ),
            source=_source_from_json(row.get("source")),
            coverage_status=_coverage_from_json(row),
            blocked_reason=_text(row.get("blocked_reason", ""), "blocked_reason"),
        )


@dataclass(frozen=True)
class RelicSlotDefinitionIR:
    definition_key: EquipmentDefinitionKey
    raw_slot_type: str
    domain_key: EquipmentDefinitionKey
    allowed_main_property_types: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = "relic_slot_definition_not_lowered"

    def __post_init__(self) -> None:
        _require_kind(self.definition_key, "relic_slot")
        _require_text(self.raw_slot_type, "raw_slot_type")
        if self.definition_key.definition_identity != self.raw_slot_type:
            raise ValueError("relic slot identity must match raw_slot_type")
        _require_kind(self.domain_key, "relic_domain")
        properties = _string_tuple(
            self.allowed_main_property_types,
            "relic slot allowed_main_property_types",
        )
        if not properties or len(properties) != len(set(properties)):
            raise ValueError("relic slot main properties must be non-empty and unique")
        object.__setattr__(self, "allowed_main_property_types", properties)
        _require_equipment_source(self.source)
        _require_relic_record_source(
            self.source,
            source_role="relic_base_type",
            raw_type="RelicBaseType",
            raw_id=self.raw_slot_type,
        )
        _validate_relic_definition_coverage(
            self.coverage_status,
            self.blocked_reason,
        )

    def to_json(self) -> dict[str, JSONValue]:
        return _definition_json(
            self.definition_key,
            self.source,
            self.coverage_status,
            self.blocked_reason,
            {
                "raw_slot_type": self.raw_slot_type,
                "domain_key": self.domain_key.to_json(),
                "allowed_main_property_types": list(
                    self.allowed_main_property_types
                ),
            },
        )

    @classmethod
    def from_json(cls, value: object) -> RelicSlotDefinitionIR:
        row = _mapping(value, "relic_slot_definition")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "definition_key",
                    "raw_slot_type",
                    "domain_key",
                    "allowed_main_property_types",
                    "source",
                    "coverage_status",
                    "blocked_reason",
                }
            ),
            "relic_slot_definition",
        )
        return cls(
            definition_key=EquipmentDefinitionKey.from_json(row.get("definition_key")),
            raw_slot_type=_text(row.get("raw_slot_type"), "raw_slot_type"),
            domain_key=EquipmentDefinitionKey.from_json(row.get("domain_key")),
            allowed_main_property_types=tuple(
                _text(item, "allowed_main_property_types[]")
                for item in _sequence(
                    row.get("allowed_main_property_types"),
                    "allowed_main_property_types",
                )
            ),
            source=_source_from_json(row.get("source")),
            coverage_status=_coverage_from_json(row),
            blocked_reason=_text(row.get("blocked_reason", ""), "blocked_reason"),
        )


@dataclass(frozen=True)
class RelicMainAffixGroupDefinitionIR:
    definition_key: EquipmentDefinitionKey
    raw_group_id: str
    affix_keys: tuple[EquipmentDefinitionKey, ...]
    property_types: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = "relic_main_affix_group_not_lowered"

    def __post_init__(self) -> None:
        _require_kind(self.definition_key, "relic_main_affix_group")
        _require_text(self.raw_group_id, "raw_group_id")
        if self.definition_key.definition_identity != self.raw_group_id:
            raise ValueError("main affix group identity must match raw_group_id")
        affix_keys = _equipment_key_tuple(
            self.affix_keys,
            "relic_main_affix",
            "main affix group affix_keys",
            require_non_empty=True,
        )
        properties = _string_tuple(
            self.property_types,
            "main affix group property_types",
        )
        if not properties or len(properties) != len(set(properties)):
            raise ValueError("main affix group properties must be non-empty and unique")
        object.__setattr__(self, "affix_keys", affix_keys)
        object.__setattr__(self, "property_types", properties)
        _require_equipment_source(self.source)
        _require_relic_derived_source(
            self.source,
            source_role="relic_main_affix_config",
            raw_type="RelicMainAffixGroupProjection",
            raw_id=self.raw_group_id,
        )
        _validate_relic_definition_coverage(
            self.coverage_status,
            self.blocked_reason,
        )

    def to_json(self) -> dict[str, JSONValue]:
        return _definition_json(
            self.definition_key,
            self.source,
            self.coverage_status,
            self.blocked_reason,
            {
                "raw_group_id": self.raw_group_id,
                "affix_keys": [key.to_json() for key in self.affix_keys],
                "property_types": list(self.property_types),
            },
        )

    @classmethod
    def from_json(cls, value: object) -> RelicMainAffixGroupDefinitionIR:
        row = _mapping(value, "relic_main_affix_group_definition")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "definition_key",
                    "raw_group_id",
                    "affix_keys",
                    "property_types",
                    "source",
                    "coverage_status",
                    "blocked_reason",
                }
            ),
            "relic_main_affix_group_definition",
        )
        return cls(
            definition_key=EquipmentDefinitionKey.from_json(row.get("definition_key")),
            raw_group_id=_text(row.get("raw_group_id"), "raw_group_id"),
            affix_keys=tuple(
                EquipmentDefinitionKey.from_json(item)
                for item in _sequence(row.get("affix_keys"), "affix_keys")
            ),
            property_types=tuple(
                _text(item, "property_types[]")
                for item in _sequence(row.get("property_types"), "property_types")
            ),
            source=_source_from_json(row.get("source")),
            coverage_status=_coverage_from_json(row),
            blocked_reason=_text(row.get("blocked_reason", ""), "blocked_reason"),
        )


@dataclass(frozen=True)
class RelicMainAffixDefinitionIR:
    definition_key: EquipmentDefinitionKey
    group_key: EquipmentDefinitionKey
    raw_affix_id: str
    property_type: str
    base_value: str
    level_add: str
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = "relic_main_affix_not_lowered"

    def __post_init__(self) -> None:
        _require_kind(self.definition_key, "relic_main_affix")
        _require_kind(self.group_key, "relic_main_affix_group")
        _require_text(self.raw_affix_id, "raw_affix_id")
        expected_identity = (
            f"{self.group_key.definition_identity}:{self.raw_affix_id}"
        )
        if self.definition_key.definition_identity != expected_identity:
            raise ValueError("main affix identity must match group and affix ids")
        _require_text(self.property_type, "property_type")
        object.__setattr__(
            self,
            "base_value",
            exact_decimal_text(self.base_value, "main affix base_value"),
        )
        object.__setattr__(
            self,
            "level_add",
            exact_decimal_text(self.level_add, "main affix level_add"),
        )
        _require_equipment_source(self.source)
        _require_relic_record_source(
            self.source,
            source_role="relic_main_affix_config",
            raw_type="RelicMainAffixConfig",
            raw_id=self.definition_key.definition_identity,
        )
        _validate_relic_definition_coverage(
            self.coverage_status,
            self.blocked_reason,
        )

    def to_json(self) -> dict[str, JSONValue]:
        return _definition_json(
            self.definition_key,
            self.source,
            self.coverage_status,
            self.blocked_reason,
            {
                "group_key": self.group_key.to_json(),
                "raw_affix_id": self.raw_affix_id,
                "property_type": self.property_type,
                "base_value": self.base_value,
                "level_add": self.level_add,
            },
        )

    @classmethod
    def from_json(cls, value: object) -> RelicMainAffixDefinitionIR:
        row = _mapping(value, "relic_main_affix_definition")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "definition_key",
                    "group_key",
                    "raw_affix_id",
                    "property_type",
                    "base_value",
                    "level_add",
                    "source",
                    "coverage_status",
                    "blocked_reason",
                }
            ),
            "relic_main_affix_definition",
        )
        return cls(
            definition_key=EquipmentDefinitionKey.from_json(row.get("definition_key")),
            group_key=EquipmentDefinitionKey.from_json(row.get("group_key")),
            raw_affix_id=_text(row.get("raw_affix_id"), "raw_affix_id"),
            property_type=_text(row.get("property_type"), "property_type"),
            base_value=_text(row.get("base_value"), "base_value"),
            level_add=_text(row.get("level_add"), "level_add"),
            source=_source_from_json(row.get("source")),
            coverage_status=_coverage_from_json(row),
            blocked_reason=_text(row.get("blocked_reason", ""), "blocked_reason"),
        )


@dataclass(frozen=True)
class RelicSubAffixGroupDefinitionIR:
    definition_key: EquipmentDefinitionKey
    raw_group_id: str
    affix_keys: tuple[EquipmentDefinitionKey, ...]
    property_types: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = "relic_sub_affix_group_not_lowered"

    def __post_init__(self) -> None:
        _require_kind(self.definition_key, "relic_sub_affix_group")
        _require_text(self.raw_group_id, "raw_group_id")
        if self.definition_key.definition_identity != self.raw_group_id:
            raise ValueError("sub affix group identity must match raw_group_id")
        affix_keys = _equipment_key_tuple(
            self.affix_keys,
            "relic_sub_affix",
            "sub affix group affix_keys",
            require_non_empty=True,
        )
        properties = _string_tuple(
            self.property_types,
            "sub affix group property_types",
        )
        if not properties or len(properties) != len(set(properties)):
            raise ValueError("sub affix group properties must be non-empty and unique")
        object.__setattr__(self, "affix_keys", affix_keys)
        object.__setattr__(self, "property_types", properties)
        _require_equipment_source(self.source)
        _require_relic_derived_source(
            self.source,
            source_role="relic_sub_affix_config",
            raw_type="RelicSubAffixGroupProjection",
            raw_id=self.raw_group_id,
        )
        _validate_relic_definition_coverage(
            self.coverage_status,
            self.blocked_reason,
        )

    def to_json(self) -> dict[str, JSONValue]:
        return _definition_json(
            self.definition_key,
            self.source,
            self.coverage_status,
            self.blocked_reason,
            {
                "raw_group_id": self.raw_group_id,
                "affix_keys": [key.to_json() for key in self.affix_keys],
                "property_types": list(self.property_types),
            },
        )

    @classmethod
    def from_json(cls, value: object) -> RelicSubAffixGroupDefinitionIR:
        row = _mapping(value, "relic_sub_affix_group_definition")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "definition_key",
                    "raw_group_id",
                    "affix_keys",
                    "property_types",
                    "source",
                    "coverage_status",
                    "blocked_reason",
                }
            ),
            "relic_sub_affix_group_definition",
        )
        return cls(
            definition_key=EquipmentDefinitionKey.from_json(row.get("definition_key")),
            raw_group_id=_text(row.get("raw_group_id"), "raw_group_id"),
            affix_keys=tuple(
                EquipmentDefinitionKey.from_json(item)
                for item in _sequence(row.get("affix_keys"), "affix_keys")
            ),
            property_types=tuple(
                _text(item, "property_types[]")
                for item in _sequence(row.get("property_types"), "property_types")
            ),
            source=_source_from_json(row.get("source")),
            coverage_status=_coverage_from_json(row),
            blocked_reason=_text(row.get("blocked_reason", ""), "blocked_reason"),
        )


@dataclass(frozen=True)
class RelicSubAffixDefinitionIR:
    definition_key: EquipmentDefinitionKey
    group_key: EquipmentDefinitionKey
    raw_affix_id: str
    property_type: str
    base_value: str
    step_value: str
    step_count: int
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = "relic_sub_affix_not_lowered"

    def __post_init__(self) -> None:
        _require_kind(self.definition_key, "relic_sub_affix")
        _require_kind(self.group_key, "relic_sub_affix_group")
        _require_text(self.raw_affix_id, "raw_affix_id")
        expected_identity = (
            f"{self.group_key.definition_identity}:{self.raw_affix_id}"
        )
        if self.definition_key.definition_identity != expected_identity:
            raise ValueError("sub affix identity must match group and affix ids")
        _require_text(self.property_type, "property_type")
        object.__setattr__(
            self,
            "base_value",
            exact_decimal_text(self.base_value, "sub affix base_value"),
        )
        object.__setattr__(
            self,
            "step_value",
            exact_decimal_text(self.step_value, "sub affix step_value"),
        )
        _require_integer(self.step_count, "sub affix step_count")
        if self.step_count <= 0:
            raise ValueError("sub affix step_count must be positive")
        _require_equipment_source(self.source)
        _require_relic_record_source(
            self.source,
            source_role="relic_sub_affix_config",
            raw_type="RelicSubAffixConfig",
            raw_id=self.definition_key.definition_identity,
        )
        _validate_relic_definition_coverage(
            self.coverage_status,
            self.blocked_reason,
        )

    def to_json(self) -> dict[str, JSONValue]:
        return _definition_json(
            self.definition_key,
            self.source,
            self.coverage_status,
            self.blocked_reason,
            {
                "group_key": self.group_key.to_json(),
                "raw_affix_id": self.raw_affix_id,
                "property_type": self.property_type,
                "base_value": self.base_value,
                "step_value": self.step_value,
                "step_count": self.step_count,
            },
        )

    @classmethod
    def from_json(cls, value: object) -> RelicSubAffixDefinitionIR:
        row = _mapping(value, "relic_sub_affix_definition")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "definition_key",
                    "group_key",
                    "raw_affix_id",
                    "property_type",
                    "base_value",
                    "step_value",
                    "step_count",
                    "source",
                    "coverage_status",
                    "blocked_reason",
                }
            ),
            "relic_sub_affix_definition",
        )
        return cls(
            definition_key=EquipmentDefinitionKey.from_json(row.get("definition_key")),
            group_key=EquipmentDefinitionKey.from_json(row.get("group_key")),
            raw_affix_id=_text(row.get("raw_affix_id"), "raw_affix_id"),
            property_type=_text(row.get("property_type"), "property_type"),
            base_value=_text(row.get("base_value"), "base_value"),
            step_value=_text(row.get("step_value"), "step_value"),
            step_count=_integer(row.get("step_count"), "step_count"),
            source=_source_from_json(row.get("source")),
            coverage_status=_coverage_from_json(row),
            blocked_reason=_text(row.get("blocked_reason", ""), "blocked_reason"),
        )


@dataclass(frozen=True)
class RelicAbilitySourceIR:
    ability_name: str
    record_index: int
    source: IRSource

    def __post_init__(self) -> None:
        _require_text(self.ability_name, "relic ability_name")
        _require_integer(self.record_index, "relic ability record_index")
        if self.record_index < 0:
            raise ValueError("relic ability record_index must be non-negative")
        _require_equipment_ability_record_source(
            self.source,
            ability_name=self.ability_name,
            record_index=self.record_index,
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ability_name": self.ability_name,
            "record_index": self.record_index,
            "source": self.source.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> RelicAbilitySourceIR:
        row = _mapping(value, "relic_ability_source")
        _require_exact_fields(
            row,
            frozenset({"ability_name", "record_index", "source"}),
            "relic_ability_source",
        )
        return cls(
            ability_name=_text(row.get("ability_name"), "ability_name"),
            record_index=_integer(row.get("record_index"), "record_index"),
            source=_source_from_json(row.get("source")),
        )


@dataclass(frozen=True)
class RelicSetParameterIR:
    parameter_index: int
    exact_value: str
    source: IRSource

    def __post_init__(self) -> None:
        _require_integer(self.parameter_index, "relic set parameter_index")
        if self.parameter_index < 0:
            raise ValueError("relic set parameter_index must be non-negative")
        object.__setattr__(
            self,
            "exact_value",
            exact_decimal_text(self.exact_value, "relic set parameter exact_value"),
        )
        _require_equipment_source(self.source)
        _require_relic_record_source(
            self.source,
            source_role="relic_set_skill_config",
            raw_type="RelicSetSkillParameter",
            raw_id_suffix=f":{self.parameter_index}",
            json_path_suffix=(
                f".AbilityParamList[{self.parameter_index}].Value"
            ),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "parameter_index": self.parameter_index,
            "exact_value": self.exact_value,
            "source": self.source.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> RelicSetParameterIR:
        row = _mapping(value, "relic_set_parameter")
        _require_exact_fields(
            row,
            frozenset({"parameter_index", "exact_value", "source"}),
            "relic_set_parameter",
        )
        return cls(
            parameter_index=_integer(row.get("parameter_index"), "parameter_index"),
            exact_value=_text(row.get("exact_value"), "exact_value"),
            source=_source_from_json(row.get("source")),
        )


@dataclass(frozen=True)
class RelicSetStaticPropertyIR:
    property_index: int
    property_type: str
    exact_value: str
    source: IRSource

    def __post_init__(self) -> None:
        _require_integer(self.property_index, "relic set property_index")
        if self.property_index < 0:
            raise ValueError("relic set property_index must be non-negative")
        _require_text(self.property_type, "relic set property_type")
        object.__setattr__(
            self,
            "exact_value",
            exact_decimal_text(self.exact_value, "relic set property exact_value"),
        )
        _require_equipment_source(self.source)
        _require_relic_record_source(
            self.source,
            source_role="relic_set_skill_config",
            raw_type="RelicSetSkillStaticProperty",
            raw_id_suffix=f":{self.property_index}",
            json_path_suffix=(
                f".PropertyList[{self.property_index}].MNDFOPKBHKP.Value"
            ),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "property_index": self.property_index,
            "property_type": self.property_type,
            "exact_value": self.exact_value,
            "source": self.source.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> RelicSetStaticPropertyIR:
        row = _mapping(value, "relic_set_static_property")
        _require_exact_fields(
            row,
            frozenset({"property_index", "property_type", "exact_value", "source"}),
            "relic_set_static_property",
        )
        return cls(
            property_index=_integer(row.get("property_index"), "property_index"),
            property_type=_text(row.get("property_type"), "property_type"),
            exact_value=_text(row.get("exact_value"), "exact_value"),
            source=_source_from_json(row.get("source")),
        )


@dataclass(frozen=True)
class RelicTemplateDefinitionIR:
    definition_key: EquipmentDefinitionKey
    raw_relic_id: str
    publication_status: RelicPublicationStatus
    slot_key: EquipmentDefinitionKey
    domain_key: EquipmentDefinitionKey
    set_key: EquipmentDefinitionKey
    rarity: str
    max_level: int
    main_affix_group_key: EquipmentDefinitionKey
    sub_affix_group_key: EquipmentDefinitionKey
    mode: RelicTemplateMode
    raw_mode: str
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = "relic_template_definition_not_lowered"

    def __post_init__(self) -> None:
        _require_kind(self.definition_key, "relic_template")
        _require_text(self.raw_relic_id, "raw_relic_id")
        if self.definition_key.definition_identity != self.raw_relic_id:
            raise ValueError("relic template identity must match raw_relic_id")
        if self.publication_status not in LIGHT_CONE_PUBLICATION_STATES:
            raise ValueError("invalid relic publication_status")
        _require_kind(self.slot_key, "relic_slot")
        _require_kind(self.domain_key, "relic_domain")
        _require_kind(self.set_key, "relic_set")
        _require_text(self.rarity, "rarity")
        _require_integer(self.max_level, "max_level")
        if self.max_level < 0:
            raise ValueError("relic max_level must be non-negative")
        _require_kind(self.main_affix_group_key, "relic_main_affix_group")
        _require_kind(self.sub_affix_group_key, "relic_sub_affix_group")
        if self.mode not in {"BASIC", "CUSTOM", "UNKNOWN"}:
            raise ValueError("invalid relic template mode")
        _require_text(self.raw_mode, "raw_mode")
        if self.mode != "UNKNOWN" and self.raw_mode != self.mode:
            raise ValueError("known relic template mode must match raw_mode")
        _require_equipment_source(self.source)
        _require_relic_record_source(
            self.source,
            source_role="relic_config",
            raw_type="RelicConfig",
            raw_id=self.raw_relic_id,
        )
        _validate_relic_definition_coverage(
            self.coverage_status,
            self.blocked_reason,
        )
        if self.mode == "UNKNOWN" and self.coverage_status != "blocked":
            raise ValueError("unknown relic template modes must remain blocked")

    def to_json(self) -> dict[str, JSONValue]:
        return _definition_json(
            self.definition_key,
            self.source,
            self.coverage_status,
            self.blocked_reason,
            {
                "raw_relic_id": self.raw_relic_id,
                "publication_status": self.publication_status,
                "slot_key": self.slot_key.to_json(),
                "domain_key": self.domain_key.to_json(),
                "set_key": self.set_key.to_json(),
                "rarity": self.rarity,
                "max_level": self.max_level,
                "main_affix_group_key": self.main_affix_group_key.to_json(),
                "sub_affix_group_key": self.sub_affix_group_key.to_json(),
                "mode": self.mode,
                "raw_mode": self.raw_mode,
            },
        )

    @classmethod
    def from_json(cls, value: object) -> RelicTemplateDefinitionIR:
        row = _mapping(value, "relic_template_definition")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "definition_key",
                    "raw_relic_id",
                    "publication_status",
                    "slot_key",
                    "domain_key",
                    "set_key",
                    "rarity",
                    "max_level",
                    "main_affix_group_key",
                    "sub_affix_group_key",
                    "mode",
                    "raw_mode",
                    "source",
                    "coverage_status",
                    "blocked_reason",
                }
            ),
            "relic_template_definition",
        )
        return cls(
            definition_key=EquipmentDefinitionKey.from_json(row.get("definition_key")),
            raw_relic_id=_text(row.get("raw_relic_id"), "raw_relic_id"),
            publication_status=cast(
                RelicPublicationStatus,
                _text(row.get("publication_status"), "publication_status"),
            ),
            slot_key=EquipmentDefinitionKey.from_json(row.get("slot_key")),
            domain_key=EquipmentDefinitionKey.from_json(row.get("domain_key")),
            set_key=EquipmentDefinitionKey.from_json(row.get("set_key")),
            rarity=_text(row.get("rarity"), "rarity"),
            max_level=_integer(row.get("max_level"), "max_level"),
            main_affix_group_key=EquipmentDefinitionKey.from_json(
                row.get("main_affix_group_key")
            ),
            sub_affix_group_key=EquipmentDefinitionKey.from_json(
                row.get("sub_affix_group_key")
            ),
            mode=cast(RelicTemplateMode, _text(row.get("mode"), "mode")),
            raw_mode=_text(row.get("raw_mode"), "raw_mode"),
            source=_source_from_json(row.get("source")),
            coverage_status=_coverage_from_json(row),
            blocked_reason=_text(row.get("blocked_reason", ""), "blocked_reason"),
        )


@dataclass(frozen=True)
class RelicSetDefinitionIR:
    definition_key: EquipmentDefinitionKey
    raw_set_id: str
    publication_status: RelicPublicationStatus
    release_field_present: bool
    domain_key: EquipmentDefinitionKey
    slot_keys: tuple[EquipmentDefinitionKey, ...]
    template_keys: tuple[EquipmentDefinitionKey, ...]
    threshold_keys: tuple[EquipmentDefinitionKey, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = "relic_set_definition_not_lowered"

    def __post_init__(self) -> None:
        _require_kind(self.definition_key, "relic_set")
        _require_text(self.raw_set_id, "raw_set_id")
        if self.definition_key.definition_identity != self.raw_set_id:
            raise ValueError("relic set identity must match raw_set_id")
        if self.publication_status not in LIGHT_CONE_PUBLICATION_STATES:
            raise ValueError("invalid relic set publication_status")
        _boolean(self.release_field_present, "release_field_present")
        if (
            self.publication_status in {"published", "unpublished"}
            and not self.release_field_present
        ):
            raise ValueError("known relic set publication requires Release field")
        if (
            not self.release_field_present
            and self.publication_status != "status_unknown"
        ):
            raise ValueError("missing relic set Release must remain status_unknown")
        _require_kind(self.domain_key, "relic_domain")
        slots = _equipment_key_tuple(
            self.slot_keys,
            "relic_slot",
            "relic set slot_keys",
            require_non_empty=True,
        )
        templates = _equipment_key_tuple(
            self.template_keys,
            "relic_template",
            "relic set template_keys",
            require_non_empty=True,
        )
        thresholds = _equipment_key_tuple(
            self.threshold_keys,
            "relic_set_threshold",
            "relic set threshold_keys",
            require_non_empty=True,
        )
        object.__setattr__(self, "slot_keys", slots)
        object.__setattr__(self, "template_keys", templates)
        object.__setattr__(self, "threshold_keys", thresholds)
        _require_equipment_source(self.source)
        _require_relic_record_source(
            self.source,
            source_role="relic_set_config",
            raw_type="RelicSetConfig",
            raw_id=self.raw_set_id,
        )
        _validate_relic_definition_coverage(
            self.coverage_status,
            self.blocked_reason,
        )

    def to_json(self) -> dict[str, JSONValue]:
        return _definition_json(
            self.definition_key,
            self.source,
            self.coverage_status,
            self.blocked_reason,
            {
                "raw_set_id": self.raw_set_id,
                "publication_status": self.publication_status,
                "release_field_present": self.release_field_present,
                "domain_key": self.domain_key.to_json(),
                "slot_keys": [key.to_json() for key in self.slot_keys],
                "template_keys": [key.to_json() for key in self.template_keys],
                "threshold_keys": [key.to_json() for key in self.threshold_keys],
            },
        )

    @classmethod
    def from_json(cls, value: object) -> RelicSetDefinitionIR:
        row = _mapping(value, "relic_set_definition")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "definition_key",
                    "raw_set_id",
                    "publication_status",
                    "release_field_present",
                    "domain_key",
                    "slot_keys",
                    "template_keys",
                    "threshold_keys",
                    "source",
                    "coverage_status",
                    "blocked_reason",
                }
            ),
            "relic_set_definition",
        )
        return cls(
            definition_key=EquipmentDefinitionKey.from_json(row.get("definition_key")),
            raw_set_id=_text(row.get("raw_set_id"), "raw_set_id"),
            publication_status=cast(
                RelicPublicationStatus,
                _text(row.get("publication_status"), "publication_status"),
            ),
            release_field_present=_boolean(
                row.get("release_field_present"),
                "release_field_present",
            ),
            domain_key=EquipmentDefinitionKey.from_json(row.get("domain_key")),
            slot_keys=tuple(
                EquipmentDefinitionKey.from_json(item)
                for item in _sequence(row.get("slot_keys"), "slot_keys")
            ),
            template_keys=tuple(
                EquipmentDefinitionKey.from_json(item)
                for item in _sequence(row.get("template_keys"), "template_keys")
            ),
            threshold_keys=tuple(
                EquipmentDefinitionKey.from_json(item)
                for item in _sequence(row.get("threshold_keys"), "threshold_keys")
            ),
            source=_source_from_json(row.get("source")),
            coverage_status=_coverage_from_json(row),
            blocked_reason=_text(row.get("blocked_reason", ""), "blocked_reason"),
        )


@dataclass(frozen=True)
class RelicSetThresholdIR:
    definition_key: EquipmentDefinitionKey
    set_key: EquipmentDefinitionKey
    require_count: int
    static_properties: tuple[RelicSetStaticPropertyIR, ...]
    parameters: tuple[RelicSetParameterIR, ...]
    ability_source: RelicAbilitySourceIR | None
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = "relic_set_threshold_not_lowered"

    def __post_init__(self) -> None:
        _require_kind(self.definition_key, "relic_set_threshold")
        _require_kind(self.set_key, "relic_set")
        _require_integer(self.require_count, "require_count")
        if self.require_count <= 0:
            raise ValueError("relic set require_count must be positive")
        expected_identity = (
            f"{self.set_key.definition_identity}:{self.require_count}"
        )
        if self.definition_key.definition_identity != expected_identity:
            raise ValueError("relic set threshold identity must match set and count")
        static_properties = cast(
            tuple[RelicSetStaticPropertyIR, ...],
            _typed_tuple(
                self.static_properties,
                RelicSetStaticPropertyIR,
                "relic set static_properties",
            ),
        )
        parameters = cast(
            tuple[RelicSetParameterIR, ...],
            _typed_tuple(
                self.parameters,
                RelicSetParameterIR,
                "relic set parameters",
            ),
        )
        if tuple(item.property_index for item in static_properties) != tuple(
            range(len(static_properties))
        ):
            raise ValueError("relic set static properties must be ordered and contiguous")
        if tuple(item.parameter_index for item in parameters) != tuple(
            range(len(parameters))
        ):
            raise ValueError("relic set parameters must be ordered and contiguous")
        if self.ability_source is not None and not isinstance(
            self.ability_source,
            RelicAbilitySourceIR,
        ):
            raise TypeError("relic ability_source must be RelicAbilitySourceIR or None")
        if not static_properties and self.ability_source is None:
            raise ValueError(
                "relic set thresholds require a static property or ability source"
            )
        object.__setattr__(self, "static_properties", static_properties)
        object.__setattr__(self, "parameters", parameters)
        _require_equipment_source(self.source)
        _require_relic_record_source(
            self.source,
            source_role="relic_set_skill_config",
            raw_type="RelicSetSkillConfig",
            raw_id=self.definition_key.definition_identity,
        )
        if _source_kind(self.source) == "tbgd":
            row_json_path = _source_row_json_path(self.source)
            nested_identity_prefix = (
                f"{self.set_key.definition_identity}:{self.require_count}"
            )
            for item in static_properties:
                if (
                    item.source.raw_id
                    != f"{nested_identity_prefix}:{item.property_index}"
                    or item.source.evidence.get("json_path")
                    != (
                        f"{row_json_path}.PropertyList[{item.property_index}]"
                        ".MNDFOPKBHKP.Value"
                    )
                ):
                    raise ValueError(
                        "relic static property source must belong to its threshold row"
                    )
            for item in parameters:
                if (
                    item.source.raw_id
                    != f"{nested_identity_prefix}:{item.parameter_index}"
                    or item.source.evidence.get("json_path")
                    != (
                        f"{row_json_path}.AbilityParamList[{item.parameter_index}]"
                        ".Value"
                    )
                ):
                    raise ValueError(
                        "relic parameter source must belong to its threshold row"
                    )
        sources: list[IRSource] = [self.source]
        sources.extend(item.source for item in static_properties)
        sources.extend(item.source for item in parameters)
        if self.ability_source is not None:
            sources.append(self.ability_source.source)
        _require_matching_source_fingerprints(sources, "relic set threshold")
        _validate_relic_definition_coverage(
            self.coverage_status,
            self.blocked_reason,
        )

    def to_json(self) -> dict[str, JSONValue]:
        return _definition_json(
            self.definition_key,
            self.source,
            self.coverage_status,
            self.blocked_reason,
            {
                "set_key": self.set_key.to_json(),
                "require_count": self.require_count,
                "static_properties": [
                    item.to_json() for item in self.static_properties
                ],
                "parameters": [item.to_json() for item in self.parameters],
                "ability_source": (
                    self.ability_source.to_json()
                    if self.ability_source is not None
                    else None
                ),
            },
        )

    @classmethod
    def from_json(cls, value: object) -> RelicSetThresholdIR:
        row = _mapping(value, "relic_set_threshold")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "definition_key",
                    "set_key",
                    "require_count",
                    "static_properties",
                    "parameters",
                    "ability_source",
                    "source",
                    "coverage_status",
                    "blocked_reason",
                }
            ),
            "relic_set_threshold",
        )
        ability_source = row.get("ability_source")
        return cls(
            definition_key=EquipmentDefinitionKey.from_json(row.get("definition_key")),
            set_key=EquipmentDefinitionKey.from_json(row.get("set_key")),
            require_count=_integer(row.get("require_count"), "require_count"),
            static_properties=tuple(
                RelicSetStaticPropertyIR.from_json(item)
                for item in _sequence(
                    row.get("static_properties"),
                    "static_properties",
                )
            ),
            parameters=tuple(
                RelicSetParameterIR.from_json(item)
                for item in _sequence(row.get("parameters"), "parameters")
            ),
            ability_source=(
                RelicAbilitySourceIR.from_json(ability_source)
                if ability_source is not None
                else None
            ),
            source=_source_from_json(row.get("source")),
            coverage_status=_coverage_from_json(row),
            blocked_reason=_text(row.get("blocked_reason", ""), "blocked_reason"),
        )


@dataclass(frozen=True)
class EquipmentAbilityParameterReadIR:
    parameter_read_id: str
    graph_ref_id: str
    dynamic_hash: str
    parameter_index: int
    value_type: str
    source: IRSource
    coverage_status: CoverageStatus = "lowered"
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        _require_text(self.parameter_read_id, "parameter_read_id")
        _require_text(self.graph_ref_id, "graph_ref_id")
        _require_text(self.dynamic_hash, "dynamic_hash")
        _require_integer(self.parameter_index, "parameter_index")
        if self.parameter_index < 0:
            raise ValueError("equipment ability parameter_index must be non-negative")
        _require_text(self.value_type, "value_type")
        _require_equipment_source(self.source)
        _validate_coverage(self.coverage_status, self.blocked_reason)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "parameter_read_id": self.parameter_read_id,
            "graph_ref_id": self.graph_ref_id,
            "dynamic_hash": self.dynamic_hash,
            "parameter_index": self.parameter_index,
            "value_type": self.value_type,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }

    @classmethod
    def from_json(cls, value: object) -> EquipmentAbilityParameterReadIR:
        row = _mapping(value, "equipment_ability_parameter_read")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "parameter_read_id",
                    "graph_ref_id",
                    "dynamic_hash",
                    "parameter_index",
                    "value_type",
                    "source",
                    "coverage_status",
                    "blocked_reason",
                }
            ),
            "equipment_ability_parameter_read",
        )
        return cls(
            parameter_read_id=_text(row.get("parameter_read_id"), "parameter_read_id"),
            graph_ref_id=_text(row.get("graph_ref_id"), "graph_ref_id"),
            dynamic_hash=_text(row.get("dynamic_hash"), "dynamic_hash"),
            parameter_index=_integer(row.get("parameter_index"), "parameter_index"),
            value_type=_text(row.get("value_type"), "value_type"),
            source=_source_from_json(row.get("source")),
            coverage_status=_coverage_from_json(row),
            blocked_reason=_text(row.get("blocked_reason", ""), "blocked_reason"),
        )


@dataclass(frozen=True)
class EquipmentMechanismRefIR:
    definition_key: EquipmentDefinitionKey
    graph_ref_id: str
    parameter_binding_ids: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = "equipment_mechanism_graph_not_lowered"

    def __post_init__(self) -> None:
        _require_kind(self.definition_key, "equipment_mechanism")
        _require_text(self.graph_ref_id, "graph_ref_id")
        object.__setattr__(
            self,
            "parameter_binding_ids",
            _string_tuple(self.parameter_binding_ids, "parameter_binding_ids"),
        )
        _require_equipment_source(self.source)
        _validate_coverage(self.coverage_status, self.blocked_reason)

    def to_json(self) -> dict[str, JSONValue]:
        return _definition_json(
            self.definition_key,
            self.source,
            self.coverage_status,
            self.blocked_reason,
            {
                "graph_ref_id": self.graph_ref_id,
                "parameter_binding_ids": list(self.parameter_binding_ids),
            },
        )

    @classmethod
    def from_json(cls, value: object) -> EquipmentMechanismRefIR:
        row = _mapping(value, "equipment_mechanism_ref")
        return cls(
            definition_key=EquipmentDefinitionKey.from_json(row.get("definition_key")),
            graph_ref_id=_text(row.get("graph_ref_id"), "graph_ref_id"),
            parameter_binding_ids=tuple(
                _text(item, "parameter_binding_ids[]")
                for item in _sequence(row.get("parameter_binding_ids"), "parameter_binding_ids")
            ),
            source=_source_from_json(row.get("source")),
            coverage_status=_coverage_from_json(row),
            blocked_reason=_text(row.get("blocked_reason", ""), "blocked_reason"),
        )


EquipmentDefinition = (
    CharacterEquipmentEligibilityIR
    | LightConeDefinitionIR
    | RelicDomainDefinitionIR
    | RelicSlotDefinitionIR
    | RelicMainAffixGroupDefinitionIR
    | RelicMainAffixDefinitionIR
    | RelicSubAffixGroupDefinitionIR
    | RelicSubAffixDefinitionIR
    | RelicTemplateDefinitionIR
    | RelicSetDefinitionIR
    | RelicSetThresholdIR
    | EquipmentMechanismRefIR
)


@dataclass(frozen=True)
class RelicDefinitionReferenceIssue:
    definition_key: EquipmentDefinitionKey
    issue_code: str
    related_key: EquipmentDefinitionKey | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.definition_key.definition_kind not in {
            "relic_domain",
            "relic_slot",
            "relic_main_affix_group",
            "relic_main_affix",
            "relic_sub_affix_group",
            "relic_sub_affix",
            "relic_template",
            "relic_set",
            "relic_set_threshold",
        }:
            raise ValueError("relic reference issue requires a relic definition key")
        _require_text(self.issue_code, "relic reference issue_code")
        _require_string(self.detail, "relic reference issue detail")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "definition_key": self.definition_key.to_json(),
            "issue_code": self.issue_code,
            "related_key": (
                self.related_key.to_json()
                if self.related_key is not None
                else None
            ),
            "detail": self.detail,
        }


def relic_definition_reference_issues(
    definitions: Sequence[EquipmentDefinition],
) -> tuple[RelicDefinitionReferenceIssue, ...]:
    """Validate every relic reference and its reverse directory relation."""

    relic_types = (
        RelicDomainDefinitionIR,
        RelicSlotDefinitionIR,
        RelicMainAffixGroupDefinitionIR,
        RelicMainAffixDefinitionIR,
        RelicSubAffixGroupDefinitionIR,
        RelicSubAffixDefinitionIR,
        RelicTemplateDefinitionIR,
        RelicSetDefinitionIR,
        RelicSetThresholdIR,
    )
    relic_definitions = tuple(
        definition
        for definition in definitions
        if isinstance(definition, relic_types)
    )
    candidates_by_key: dict[
        EquipmentDefinitionKey,
        list[EquipmentDefinition],
    ] = {}
    for definition in relic_definitions:
        candidates_by_key.setdefault(definition.definition_key, []).append(
            definition
        )
    issue_rows: set[
        tuple[
            EquipmentDefinitionKey,
            str,
            EquipmentDefinitionKey | None,
            str,
        ]
    ] = set()

    def add(
        owner: EquipmentDefinition,
        issue_code: str,
        related_key: EquipmentDefinitionKey | None = None,
        detail: str = "",
    ) -> None:
        issue_rows.add(
            (
                owner.definition_key,
                issue_code,
                related_key,
                detail,
            )
        )

    def resolve(
        owner: EquipmentDefinition,
        key: EquipmentDefinitionKey,
        expected_type: type[EquipmentDefinition],
        relation: str,
    ) -> EquipmentDefinition | None:
        candidates = candidates_by_key.get(key, ())
        if not candidates:
            add(owner, f"{relation}_missing", key)
            return None
        if len(candidates) != 1:
            add(owner, f"{relation}_ambiguous", key)
            return None
        selected = candidates[0]
        if not isinstance(selected, expected_type):
            add(owner, f"{relation}_type_mismatch", key)
            return None
        return selected

    def canonical_keys(
        values: Sequence[EquipmentDefinitionKey],
    ) -> tuple[EquipmentDefinitionKey, ...]:
        return tuple(sorted(set(values), key=lambda key: key.stable_id))

    def reverse_keys(
        expected_type: type[EquipmentDefinition],
        predicate: Callable[[EquipmentDefinition], bool],
    ) -> tuple[EquipmentDefinitionKey, ...]:
        return canonical_keys(
            tuple(
                definition.definition_key
                for definition in relic_definitions
                if isinstance(definition, expected_type)
                and predicate(definition)
            )
        )

    for key, candidates in candidates_by_key.items():
        if len(candidates) != 1:
            add(
                candidates[0],
                "relic_definition_reference_identity_ambiguous",
                key,
            )

    domains = tuple(
        definition
        for definition in relic_definitions
        if isinstance(definition, RelicDomainDefinitionIR)
    )
    slots = tuple(
        definition
        for definition in relic_definitions
        if isinstance(definition, RelicSlotDefinitionIR)
    )
    main_groups = tuple(
        definition
        for definition in relic_definitions
        if isinstance(definition, RelicMainAffixGroupDefinitionIR)
    )
    main_affixes = tuple(
        definition
        for definition in relic_definitions
        if isinstance(definition, RelicMainAffixDefinitionIR)
    )
    sub_groups = tuple(
        definition
        for definition in relic_definitions
        if isinstance(definition, RelicSubAffixGroupDefinitionIR)
    )
    sub_affixes = tuple(
        definition
        for definition in relic_definitions
        if isinstance(definition, RelicSubAffixDefinitionIR)
    )
    templates = tuple(
        definition
        for definition in relic_definitions
        if isinstance(definition, RelicTemplateDefinitionIR)
    )
    sets = tuple(
        definition
        for definition in relic_definitions
        if isinstance(definition, RelicSetDefinitionIR)
    )
    thresholds = tuple(
        definition
        for definition in relic_definitions
        if isinstance(definition, RelicSetThresholdIR)
    )

    for domain in domains:
        for slot_key in domain.slot_keys:
            slot = resolve(
                domain,
                slot_key,
                RelicSlotDefinitionIR,
                "relic_domain_slot_reference",
            )
            if (
                isinstance(slot, RelicSlotDefinitionIR)
                and slot.domain_key != domain.definition_key
            ):
                add(
                    domain,
                    "relic_domain_slot_relation_mismatch",
                    slot.definition_key,
                )
        for set_key in domain.set_keys:
            relic_set = resolve(
                domain,
                set_key,
                RelicSetDefinitionIR,
                "relic_domain_set_reference",
            )
            if (
                isinstance(relic_set, RelicSetDefinitionIR)
                and relic_set.domain_key != domain.definition_key
            ):
                add(
                    domain,
                    "relic_domain_set_relation_mismatch",
                    relic_set.definition_key,
                )
        if domain.slot_keys != reverse_keys(
            RelicSlotDefinitionIR,
            lambda item: cast(
                RelicSlotDefinitionIR,
                item,
            ).domain_key
            == domain.definition_key,
        ):
            add(domain, "relic_domain_slot_reverse_mismatch")
        if domain.set_keys != reverse_keys(
            RelicSetDefinitionIR,
            lambda item: cast(
                RelicSetDefinitionIR,
                item,
            ).domain_key
            == domain.definition_key,
        ):
            add(domain, "relic_domain_set_reverse_mismatch")

    for slot in slots:
        domain = resolve(
            slot,
            slot.domain_key,
            RelicDomainDefinitionIR,
            "relic_slot_domain_reference",
        )
        if (
            isinstance(domain, RelicDomainDefinitionIR)
            and slot.definition_key not in domain.slot_keys
        ):
            add(
                slot,
                "relic_slot_domain_reverse_mismatch",
                domain.definition_key,
            )

    for group in main_groups:
        for affix_key in group.affix_keys:
            affix = resolve(
                group,
                affix_key,
                RelicMainAffixDefinitionIR,
                "relic_main_group_affix_reference",
            )
            if (
                isinstance(affix, RelicMainAffixDefinitionIR)
                and affix.group_key != group.definition_key
            ):
                add(
                    group,
                    "relic_main_group_affix_relation_mismatch",
                    affix.definition_key,
                )
        members = tuple(
            affix
            for affix in main_affixes
            if affix.group_key == group.definition_key
        )
        if group.affix_keys != canonical_keys(
            tuple(item.definition_key for item in members)
        ):
            add(group, "relic_main_group_affix_reverse_mismatch")
        if group.property_types != tuple(
            sorted({item.property_type for item in members})
        ):
            add(group, "relic_main_group_property_projection_mismatch")

    for affix in main_affixes:
        group = resolve(
            affix,
            affix.group_key,
            RelicMainAffixGroupDefinitionIR,
            "relic_main_affix_group_reference",
        )
        if (
            isinstance(group, RelicMainAffixGroupDefinitionIR)
            and affix.definition_key not in group.affix_keys
        ):
            add(
                affix,
                "relic_main_affix_group_reverse_mismatch",
                group.definition_key,
            )

    for group in sub_groups:
        for affix_key in group.affix_keys:
            affix = resolve(
                group,
                affix_key,
                RelicSubAffixDefinitionIR,
                "relic_sub_group_affix_reference",
            )
            if (
                isinstance(affix, RelicSubAffixDefinitionIR)
                and affix.group_key != group.definition_key
            ):
                add(
                    group,
                    "relic_sub_group_affix_relation_mismatch",
                    affix.definition_key,
                )
        members = tuple(
            affix
            for affix in sub_affixes
            if affix.group_key == group.definition_key
        )
        if group.affix_keys != canonical_keys(
            tuple(item.definition_key for item in members)
        ):
            add(group, "relic_sub_group_affix_reverse_mismatch")
        if group.property_types != tuple(
            sorted({item.property_type for item in members})
        ):
            add(group, "relic_sub_group_property_projection_mismatch")

    for affix in sub_affixes:
        group = resolve(
            affix,
            affix.group_key,
            RelicSubAffixGroupDefinitionIR,
            "relic_sub_affix_group_reference",
        )
        if (
            isinstance(group, RelicSubAffixGroupDefinitionIR)
            and affix.definition_key not in group.affix_keys
        ):
            add(
                affix,
                "relic_sub_affix_group_reverse_mismatch",
                group.definition_key,
            )

    for template in templates:
        slot = resolve(
            template,
            template.slot_key,
            RelicSlotDefinitionIR,
            "relic_template_slot_reference",
        )
        domain = resolve(
            template,
            template.domain_key,
            RelicDomainDefinitionIR,
            "relic_template_domain_reference",
        )
        relic_set = resolve(
            template,
            template.set_key,
            RelicSetDefinitionIR,
            "relic_template_set_reference",
        )
        main_group = resolve(
            template,
            template.main_affix_group_key,
            RelicMainAffixGroupDefinitionIR,
            "relic_template_main_group_reference",
        )
        resolve(
            template,
            template.sub_affix_group_key,
            RelicSubAffixGroupDefinitionIR,
            "relic_template_sub_group_reference",
        )
        if (
            isinstance(slot, RelicSlotDefinitionIR)
            and slot.domain_key != template.domain_key
        ):
            add(
                template,
                "relic_template_slot_domain_mismatch",
                slot.definition_key,
            )
        if (
            isinstance(domain, RelicDomainDefinitionIR)
            and isinstance(slot, RelicSlotDefinitionIR)
            and slot.definition_key not in domain.slot_keys
        ):
            add(
                template,
                "relic_template_domain_slot_mismatch",
                domain.definition_key,
            )
        if isinstance(relic_set, RelicSetDefinitionIR):
            if relic_set.domain_key != template.domain_key:
                add(
                    template,
                    "relic_template_set_domain_mismatch",
                    relic_set.definition_key,
                )
            if template.slot_key not in relic_set.slot_keys:
                add(
                    template,
                    "relic_template_set_slot_mismatch",
                    relic_set.definition_key,
                )
            if template.definition_key not in relic_set.template_keys:
                add(
                    template,
                    "relic_template_set_reverse_mismatch",
                    relic_set.definition_key,
                )
        if (
            isinstance(slot, RelicSlotDefinitionIR)
            and isinstance(main_group, RelicMainAffixGroupDefinitionIR)
            and not set(main_group.property_types).issubset(
                slot.allowed_main_property_types
            )
        ):
            add(
                template,
                "relic_template_main_group_slot_mismatch",
                main_group.definition_key,
            )

    for relic_set in sets:
        domain = resolve(
            relic_set,
            relic_set.domain_key,
            RelicDomainDefinitionIR,
            "relic_set_domain_reference",
        )
        if (
            isinstance(domain, RelicDomainDefinitionIR)
            and relic_set.definition_key not in domain.set_keys
        ):
            add(
                relic_set,
                "relic_set_domain_reverse_mismatch",
                domain.definition_key,
            )
        for slot_key in relic_set.slot_keys:
            slot = resolve(
                relic_set,
                slot_key,
                RelicSlotDefinitionIR,
                "relic_set_slot_reference",
            )
            if (
                isinstance(slot, RelicSlotDefinitionIR)
                and slot.domain_key != relic_set.domain_key
            ):
                add(
                    relic_set,
                    "relic_set_slot_domain_mismatch",
                    slot.definition_key,
                )
        for template_key in relic_set.template_keys:
            template = resolve(
                relic_set,
                template_key,
                RelicTemplateDefinitionIR,
                "relic_set_template_reference",
            )
            if isinstance(template, RelicTemplateDefinitionIR) and (
                template.set_key != relic_set.definition_key
                or template.domain_key != relic_set.domain_key
                or template.slot_key not in relic_set.slot_keys
            ):
                add(
                    relic_set,
                    "relic_set_template_relation_mismatch",
                    template.definition_key,
                )
        for threshold_key in relic_set.threshold_keys:
            threshold = resolve(
                relic_set,
                threshold_key,
                RelicSetThresholdIR,
                "relic_set_threshold_reference",
            )
            if (
                isinstance(threshold, RelicSetThresholdIR)
                and threshold.set_key != relic_set.definition_key
            ):
                add(
                    relic_set,
                    "relic_set_threshold_relation_mismatch",
                    threshold.definition_key,
                )
        set_templates = tuple(
            template
            for template in templates
            if template.set_key == relic_set.definition_key
        )
        if relic_set.template_keys != canonical_keys(
            tuple(item.definition_key for item in set_templates)
        ):
            add(relic_set, "relic_set_template_reverse_mismatch")
        if relic_set.slot_keys != canonical_keys(
            tuple(item.slot_key for item in set_templates)
        ):
            add(relic_set, "relic_set_slot_reverse_mismatch")
        if relic_set.threshold_keys != reverse_keys(
            RelicSetThresholdIR,
            lambda item: cast(
                RelicSetThresholdIR,
                item,
            ).set_key
            == relic_set.definition_key,
        ):
            add(relic_set, "relic_set_threshold_reverse_mismatch")

    for threshold in thresholds:
        relic_set = resolve(
            threshold,
            threshold.set_key,
            RelicSetDefinitionIR,
            "relic_threshold_set_reference",
        )
        if (
            isinstance(relic_set, RelicSetDefinitionIR)
            and threshold.definition_key not in relic_set.threshold_keys
        ):
            add(
                threshold,
                "relic_threshold_set_reverse_mismatch",
                relic_set.definition_key,
            )

    return tuple(
        RelicDefinitionReferenceIssue(
            definition_key=definition_key,
            issue_code=issue_code,
            related_key=related_key,
            detail=detail,
        )
        for definition_key, issue_code, related_key, detail in sorted(
            issue_rows,
            key=lambda item: (
                item[0].stable_id,
                item[1],
                item[2].stable_id if item[2] is not None else "",
                item[3],
            ),
        )
    )


EquipmentDefinitionT = TypeVar(
    "EquipmentDefinitionT",
    bound=EquipmentDefinition,
)


DEFINITION_TYPES: dict[EquipmentDefinitionKind, type[EquipmentDefinition]] = {
    "character_equipment_eligibility": CharacterEquipmentEligibilityIR,
    "light_cone": LightConeDefinitionIR,
    "relic_domain": RelicDomainDefinitionIR,
    "relic_slot": RelicSlotDefinitionIR,
    "relic_main_affix_group": RelicMainAffixGroupDefinitionIR,
    "relic_main_affix": RelicMainAffixDefinitionIR,
    "relic_sub_affix_group": RelicSubAffixGroupDefinitionIR,
    "relic_sub_affix": RelicSubAffixDefinitionIR,
    "relic_template": RelicTemplateDefinitionIR,
    "relic_set": RelicSetDefinitionIR,
    "relic_set_threshold": RelicSetThresholdIR,
    "equipment_mechanism": EquipmentMechanismRefIR,
}


def equipment_definition_from_json(value: object) -> EquipmentDefinition:
    row = _mapping(value, "equipment_definition")
    key = EquipmentDefinitionKey.from_json(row.get("definition_key"))
    definition_type = DEFINITION_TYPES[key.definition_kind]
    return definition_type.from_json(row)


@dataclass(frozen=True, order=True)
class EquipmentResolutionCandidate:
    definition_key: EquipmentDefinitionKey
    object_type: str
    source: IRSource = field(compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.definition_key, EquipmentDefinitionKey):
            raise TypeError("resolution candidate definition_key must be EquipmentDefinitionKey")
        _require_text(self.object_type, "object_type")
        if self.definition_key.definition_kind == "character_equipment_eligibility":
            object.__setattr__(self, "source", immutable_ir_source(self.source))
        else:
            _require_equipment_source(self.source)

    @property
    def diagnostic_id(self) -> str:
        json_path = str(self.source.evidence.get("json_path") or "")
        return f"{self.definition_key.stable_id}@{self.source.source_path}#{json_path}"

    @classmethod
    def from_definition(cls, definition: EquipmentDefinition) -> EquipmentResolutionCandidate:
        return cls(
            definition_key=definition.definition_key,
            object_type=type(definition).__name__,
            source=definition.source,
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "definition_key": self.definition_key.to_json(),
            "object_type": self.object_type,
            "diagnostic_id": self.diagnostic_id,
            "source": self.source.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> EquipmentResolutionCandidate:
        row = _mapping(value, "resolution_candidate")
        _require_exact_fields(
            row,
            frozenset({"definition_key", "object_type", "diagnostic_id", "source"}),
            "resolution_candidate",
        )
        key = EquipmentDefinitionKey.from_json(row.get("definition_key"))
        return cls(
            definition_key=key,
            object_type=_text(row.get("object_type"), "object_type"),
            source=(
                ir_source_from_json(row.get("source"))
                if key.definition_kind == "character_equipment_eligibility"
                else _source_from_json(row.get("source"))
            ),
        )


@dataclass(frozen=True)
class EquipmentDefinitionResolution(Generic[EquipmentDefinitionT]):
    resolution_status: EquipmentResolutionStatus
    requested_key: EquipmentDefinitionKey
    expected_kind: EquipmentDefinitionKind
    value: EquipmentDefinitionT | None
    candidates: tuple[EquipmentResolutionCandidate, ...] = ()
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        _require_string(self.resolution_status, "resolution_status")
        if self.resolution_status not in {"resolved", "blocked"}:
            raise ValueError(f"invalid equipment resolution_status {self.resolution_status!r}")
        _require_string(self.expected_kind, "expected_kind")
        if self.expected_kind not in EQUIPMENT_DEFINITION_KINDS:
            raise ValueError(f"invalid equipment expected_kind {self.expected_kind!r}")
        if not isinstance(self.requested_key, EquipmentDefinitionKey):
            raise TypeError("equipment query requested_key must be EquipmentDefinitionKey")
        _require_string(self.blocked_reason, "blocked_reason")
        if self.expected_kind != self.requested_key.definition_kind:
            raise ValueError("expected_kind must match requested_key.definition_kind")
        typed_candidates = cast(
            tuple[EquipmentResolutionCandidate, ...],
            _typed_tuple(
                self.candidates,
                EquipmentResolutionCandidate,
                "resolution candidates",
            ),
        )
        ordered = tuple(
            sorted(
                typed_candidates,
                key=lambda item: (
                    item.definition_key.definition_kind,
                    item.definition_key.definition_identity,
                    item.diagnostic_id,
                ),
            )
        )
        object.__setattr__(self, "candidates", ordered)
        if self.resolution_status == "resolved":
            if self.value is None or len(ordered) != 1 or self.blocked_reason:
                raise ValueError("resolved equipment queries require one value, one candidate, and no blocked_reason")
            expected_type = DEFINITION_TYPES[self.expected_kind]
            if type(self.value) is not expected_type:
                raise TypeError("resolved equipment query value has the wrong concrete type")
            if self.value.definition_key != self.requested_key or ordered[0].definition_key != self.requested_key:
                raise ValueError("resolved equipment query candidate does not match the requested key")
            if self.value.coverage_status not in EQUIPMENT_RESOLVABLE_COVERAGE_STATES:
                raise ValueError("resolved equipment query value is not in a resolvable coverage state")
            if ordered[0].object_type != expected_type.__name__:
                raise ValueError("resolved equipment query candidate object_type does not match the value")
            if ordered[0].source != self.value.source:
                raise ValueError("resolved equipment query candidate source does not match the value")
        elif self.resolution_status == "blocked":
            if self.value is not None or not self.blocked_reason:
                raise ValueError("blocked equipment queries require value=None and blocked_reason")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "resolution_status": self.resolution_status,
            "requested_key": self.requested_key.to_json(),
            "expected_kind": self.expected_kind,
            "value": self.value.to_json() if self.value is not None else None,
            "candidates": [candidate.to_json() for candidate in self.candidates],
            "candidate_ids": [candidate.diagnostic_id for candidate in self.candidates],
            "blocked_reason": self.blocked_reason,
        }

    @classmethod
    def from_json(cls, value: object) -> EquipmentDefinitionResolution[EquipmentDefinition]:
        row = _mapping(value, "equipment_definition_resolution")
        definition = row.get("value")
        return EquipmentDefinitionResolution[EquipmentDefinition](
            resolution_status=cast(
                EquipmentResolutionStatus,
                _text(row.get("resolution_status"), "resolution_status"),
            ),
            requested_key=EquipmentDefinitionKey.from_json(row.get("requested_key")),
            expected_kind=cast(
                EquipmentDefinitionKind,
                _text(row.get("expected_kind"), "expected_kind"),
            ),
            value=equipment_definition_from_json(definition) if definition is not None else None,
            candidates=tuple(
                EquipmentResolutionCandidate.from_json(item)
                for item in _sequence(row.get("candidates"), "candidates")
            ),
            blocked_reason=_text(row.get("blocked_reason", ""), "blocked_reason"),
        )


@dataclass(frozen=True)
class LightConeInstanceInput:
    instance_id: str
    definition_key: EquipmentDefinitionKey
    level: int
    promotion: int
    superimposition: int
    instance_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        _require_text(self.instance_id, "light_cone.instance_id")
        _require_kind(self.definition_key, "light_cone")
        _require_integer(self.level, "light_cone.level")
        _require_integer(self.promotion, "light_cone.promotion")
        _require_integer(self.superimposition, "light_cone.superimposition")
        object.__setattr__(
            self,
            "instance_fingerprint",
            _canonical_fingerprint(self._fingerprint_payload()),
        )

    def _fingerprint_payload(self) -> dict[str, JSONValue]:
        return {
            "instance_id": self.instance_id,
            "definition_key": self.definition_key.to_json(),
            "level": self.level,
            "promotion": self.promotion,
            "superimposition": self.superimposition,
        }

    def to_json(self) -> dict[str, JSONValue]:
        return {
            **self._fingerprint_payload(),
            "instance_fingerprint": self.instance_fingerprint,
        }

    @classmethod
    def from_json(cls, value: object) -> LightConeInstanceInput:
        row = _mapping(value, "light_cone_instance")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "instance_id",
                    "definition_key",
                    "level",
                    "promotion",
                    "superimposition",
                    "instance_fingerprint",
                }
            ),
            "light_cone_instance",
        )
        result = cls(
            instance_id=_text(row.get("instance_id"), "instance_id"),
            definition_key=EquipmentDefinitionKey.from_json(row.get("definition_key")),
            level=_integer(row.get("level"), "level"),
            promotion=_integer(row.get("promotion"), "promotion"),
            superimposition=_integer(row.get("superimposition"), "superimposition"),
        )
        encoded = _text(row.get("instance_fingerprint"), "instance_fingerprint")
        _require_sha256(encoded, "instance_fingerprint")
        if encoded != result.instance_fingerprint:
            raise ValueError("light-cone instance fingerprint mismatch")
        return result


@dataclass(frozen=True)
class RelicSubAffixRollInput:
    affix_key: EquipmentDefinitionKey
    count: int
    step: int

    def __post_init__(self) -> None:
        _require_kind(self.affix_key, "relic_sub_affix")
        _require_integer(self.count, "relic_sub_affix.count")
        _require_integer(self.step, "relic_sub_affix.step")

    def to_json(self) -> dict[str, JSONValue]:
        return {"affix_key": self.affix_key.to_json(), "count": self.count, "step": self.step}

    @classmethod
    def from_json(cls, value: object) -> RelicSubAffixRollInput:
        row = _mapping(value, "relic_sub_affix_roll")
        return cls(
            affix_key=EquipmentDefinitionKey.from_json(row.get("affix_key")),
            count=_integer(row.get("count"), "count"),
            step=_integer(row.get("step"), "step"),
        )


@dataclass(frozen=True)
class RelicInstanceInput:
    instance_id: str
    template_key: EquipmentDefinitionKey
    selected_slot_type: str
    level: int
    main_affix_key: EquipmentDefinitionKey
    sub_affix_rolls: tuple[RelicSubAffixRollInput, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.instance_id, "relic.instance_id")
        _require_kind(self.template_key, "relic_template")
        _require_text(self.selected_slot_type, "selected_slot_type")
        _require_integer(self.level, "relic.level")
        _require_kind(self.main_affix_key, "relic_main_affix")
        object.__setattr__(
            self,
            "sub_affix_rolls",
            cast(
                tuple[RelicSubAffixRollInput, ...],
                _typed_tuple(
                    self.sub_affix_rolls,
                    RelicSubAffixRollInput,
                    "sub_affix_rolls",
                ),
            ),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "instance_id": self.instance_id,
            "template_key": self.template_key.to_json(),
            "selected_slot_type": self.selected_slot_type,
            "level": self.level,
            "main_affix_key": self.main_affix_key.to_json(),
            "sub_affix_rolls": [roll.to_json() for roll in self.sub_affix_rolls],
        }

    @classmethod
    def from_json(cls, value: object) -> RelicInstanceInput:
        row = _mapping(value, "relic_instance")
        return cls(
            instance_id=_text(row.get("instance_id"), "instance_id"),
            template_key=EquipmentDefinitionKey.from_json(row.get("template_key")),
            selected_slot_type=_text(row.get("selected_slot_type"), "selected_slot_type"),
            level=_integer(row.get("level"), "level"),
            main_affix_key=EquipmentDefinitionKey.from_json(row.get("main_affix_key")),
            sub_affix_rolls=tuple(
                RelicSubAffixRollInput.from_json(item)
                for item in _sequence(row.get("sub_affix_rolls"), "sub_affix_rolls")
            ),
        )


@dataclass(frozen=True)
class EquipmentBuildInput:
    build_id: str
    character_card_id: str
    light_cone: LightConeInstanceInput | None = None
    relics: tuple[RelicInstanceInput, ...] = ()
    identity_labels: Mapping[str, str] = field(default_factory=dict)
    build_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        _require_text(self.build_id, "build_id")
        _require_text(self.character_card_id, "character_card_id")
        if self.light_cone is not None and not isinstance(
            self.light_cone,
            LightConeInstanceInput,
        ):
            raise TypeError("equipment build light_cone must be LightConeInstanceInput or None")
        object.__setattr__(
            self,
            "relics",
            cast(
                tuple[RelicInstanceInput, ...],
                _typed_tuple(self.relics, RelicInstanceInput, "relics"),
            ),
        )
        if not isinstance(self.identity_labels, Mapping):
            raise TypeError("equipment build identity_labels must be a mapping")
        labels = dict(self.identity_labels)
        if not all(
            isinstance(key, str) and key.strip() and isinstance(value, str)
            for key, value in labels.items()
        ):
            raise TypeError("equipment build identity_labels must map non-empty strings to strings")
        frozen_labels = _freeze_mapping(labels)
        object.__setattr__(self, "identity_labels", frozen_labels)
        object.__setattr__(self, "build_fingerprint", _canonical_fingerprint(self._fingerprint_payload()))

    def _fingerprint_payload(self) -> dict[str, JSONValue]:
        return {
            "build_id": self.build_id,
            "character_card_id": self.character_card_id,
            "light_cone": self.light_cone.to_json() if self.light_cone is not None else None,
            "relics": [relic.to_json() for relic in self.relics],
            "identity_labels": cast(dict[str, JSONValue], thaw_json(self.identity_labels)),
        }

    def to_json(self) -> dict[str, JSONValue]:
        return {**self._fingerprint_payload(), "build_fingerprint": self.build_fingerprint}

    @classmethod
    def from_json(cls, value: object) -> EquipmentBuildInput:
        row = _mapping(value, "equipment_build_input")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "build_id",
                    "character_card_id",
                    "light_cone",
                    "relics",
                    "identity_labels",
                    "build_fingerprint",
                }
            ),
            "equipment_build_input",
        )
        light_cone = _optional_mapping(row.get("light_cone"), "light_cone")
        result = cls(
            build_id=_text(row.get("build_id"), "build_id"),
            character_card_id=_text(row.get("character_card_id"), "character_card_id"),
            light_cone=LightConeInstanceInput.from_json(light_cone) if light_cone is not None else None,
            relics=tuple(
                RelicInstanceInput.from_json(item)
                for item in _sequence(row.get("relics"), "relics")
            ),
            identity_labels={
                key: _text(item, f"identity_labels.{key}")
                for key, item in _mapping(row.get("identity_labels"), "identity_labels").items()
            },
        )
        encoded_fingerprint = _text(row.get("build_fingerprint"), "build_fingerprint")
        _require_sha256(encoded_fingerprint, "build_fingerprint")
        if encoded_fingerprint != result.build_fingerprint:
            raise ValueError("equipment build fingerprint does not match the encoded payload")
        return result


@dataclass(frozen=True)
class EquipmentDynamicParameterBinding:
    binding_id: str
    parameter_read_id: str
    graph_ref_id: str
    value_type: str
    dynamic_hash: str
    parameter_index: int
    exact_value: str
    read_source: IRSource
    value_source: IRSource

    def __post_init__(self) -> None:
        _require_text(self.binding_id, "binding_id")
        _require_text(self.parameter_read_id, "parameter_read_id")
        _require_text(self.graph_ref_id, "graph_ref_id")
        _require_text(self.value_type, "value_type")
        _require_text(self.dynamic_hash, "dynamic_hash")
        _require_integer(self.parameter_index, "parameter_index")
        if self.parameter_index < 0:
            raise ValueError("dynamic equipment parameter_index must be non-negative")
        object.__setattr__(
            self,
            "exact_value",
            exact_decimal_text(self.exact_value, "dynamic parameter exact_value"),
        )
        _require_equipment_source(self.read_source)
        _require_equipment_source(self.value_source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "binding_id": self.binding_id,
            "parameter_read_id": self.parameter_read_id,
            "graph_ref_id": self.graph_ref_id,
            "value_type": self.value_type,
            "dynamic_hash": self.dynamic_hash,
            "parameter_index": self.parameter_index,
            "exact_value": self.exact_value,
            "read_source": self.read_source.to_json(),
            "value_source": self.value_source.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> EquipmentDynamicParameterBinding:
        row = _mapping(value, "equipment_dynamic_parameter_binding")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "binding_id",
                    "parameter_read_id",
                    "graph_ref_id",
                    "value_type",
                    "dynamic_hash",
                    "parameter_index",
                    "exact_value",
                    "read_source",
                    "value_source",
                }
            ),
            "equipment_dynamic_parameter_binding",
        )
        return cls(
            binding_id=_text(row.get("binding_id"), "binding_id"),
            parameter_read_id=_text(row.get("parameter_read_id"), "parameter_read_id"),
            graph_ref_id=_text(row.get("graph_ref_id"), "graph_ref_id"),
            value_type=_text(row.get("value_type"), "value_type"),
            dynamic_hash=_text(row.get("dynamic_hash"), "dynamic_hash"),
            parameter_index=_integer(row.get("parameter_index"), "parameter_index"),
            exact_value=_text(row.get("exact_value"), "exact_value"),
            read_source=_source_from_json(row.get("read_source")),
            value_source=_source_from_json(row.get("value_source")),
        )


@dataclass(frozen=True)
class DynamicMechanismSelection:
    selection_id: str
    mechanism_key: EquipmentDefinitionKey
    target_definition_key: EquipmentDefinitionKey
    graph_ref_id: str
    equipment_instance_id: str
    wearer_character_card_id: str
    skill_id: str
    superimposition_level: int
    parameter_bindings: tuple[EquipmentDynamicParameterBinding, ...]
    source: IRSource
    coverage_status: CoverageStatus
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        _require_text(self.selection_id, "selection_id")
        _require_kind(self.mechanism_key, "equipment_mechanism")
        _require_kind(self.target_definition_key, "light_cone")
        _require_text(self.graph_ref_id, "graph_ref_id")
        _require_text(self.equipment_instance_id, "equipment_instance_id")
        _require_text(self.wearer_character_card_id, "wearer_character_card_id")
        _require_text(self.skill_id, "skill_id")
        _require_integer(self.superimposition_level, "superimposition_level")
        if self.superimposition_level <= 0:
            raise ValueError("dynamic mechanism superimposition_level must be positive")
        bindings = cast(
            tuple[EquipmentDynamicParameterBinding, ...],
            _typed_tuple(
                self.parameter_bindings,
                EquipmentDynamicParameterBinding,
                "parameter_bindings",
            ),
        )
        if len({item.binding_id for item in bindings}) != len(bindings):
            raise ValueError("dynamic equipment parameter binding identities must be unique")
        if len({item.parameter_read_id for item in bindings}) != len(bindings):
            raise ValueError("dynamic equipment parameter reads must be selected at most once")
        if any(item.graph_ref_id != self.graph_ref_id for item in bindings):
            raise ValueError("dynamic equipment parameter bindings must reference the selected graph")
        object.__setattr__(self, "parameter_bindings", bindings)
        _require_equipment_source(self.source)
        _validate_coverage(self.coverage_status, self.blocked_reason)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "selection_id": self.selection_id,
            "mechanism_key": self.mechanism_key.to_json(),
            "target_definition_key": self.target_definition_key.to_json(),
            "graph_ref_id": self.graph_ref_id,
            "equipment_instance_id": self.equipment_instance_id,
            "wearer_character_card_id": self.wearer_character_card_id,
            "skill_id": self.skill_id,
            "superimposition_level": self.superimposition_level,
            "parameter_bindings": [item.to_json() for item in self.parameter_bindings],
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }

    @classmethod
    def from_json(cls, value: object) -> DynamicMechanismSelection:
        row = _mapping(value, "dynamic_mechanism_selection")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "selection_id",
                    "mechanism_key",
                    "target_definition_key",
                    "graph_ref_id",
                    "equipment_instance_id",
                    "wearer_character_card_id",
                    "skill_id",
                    "superimposition_level",
                    "parameter_bindings",
                    "source",
                    "coverage_status",
                    "blocked_reason",
                }
            ),
            "dynamic_mechanism_selection",
        )
        return cls(
            selection_id=_text(row.get("selection_id"), "selection_id"),
            mechanism_key=EquipmentDefinitionKey.from_json(row.get("mechanism_key")),
            target_definition_key=EquipmentDefinitionKey.from_json(
                row.get("target_definition_key")
            ),
            graph_ref_id=_text(row.get("graph_ref_id"), "graph_ref_id"),
            equipment_instance_id=_text(
                row.get("equipment_instance_id"),
                "equipment_instance_id",
            ),
            wearer_character_card_id=_text(
                row.get("wearer_character_card_id"),
                "wearer_character_card_id",
            ),
            skill_id=_text(row.get("skill_id"), "skill_id"),
            superimposition_level=_integer(
                row.get("superimposition_level"),
                "superimposition_level",
            ),
            parameter_bindings=tuple(
                EquipmentDynamicParameterBinding.from_json(item)
                for item in _sequence(
                    row.get("parameter_bindings"),
                    "parameter_bindings",
                )
            ),
            source=_source_from_json(row.get("source")),
            coverage_status=_coverage_from_json(row),
            blocked_reason=_text(row.get("blocked_reason", ""), "blocked_reason"),
        )


@dataclass(frozen=True)
class LightConeAssemblySelection:
    instance_id: str
    instance_fingerprint: str
    definition_key: EquipmentDefinitionKey
    level: int
    promotion_stage: int
    superimposition_level: int
    skill_id: str
    parameter_indices: tuple[int, ...]
    static_property_indices: tuple[int, ...]
    ability_name: str
    ability_record_index: int
    promotion_source: IRSource
    superimposition_source: IRSource
    ability_source: IRSource
    base_contribution_ids: tuple[str, ...]
    passive_contribution_ids: tuple[str, ...]
    selection_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        _require_text(self.instance_id, "light-cone selection instance_id")
        _require_sha256(self.instance_fingerprint, "instance_fingerprint")
        _require_kind(self.definition_key, "light_cone")
        for field_name in ("level", "promotion_stage", "superimposition_level"):
            _require_integer(getattr(self, field_name), field_name)
        if self.level <= 0 or self.promotion_stage < 0 or self.superimposition_level <= 0:
            raise ValueError("light-cone selection progression is outside the valid type boundary")
        _require_text(self.skill_id, "skill_id")
        _require_text(self.ability_name, "ability_name")
        _require_integer(self.ability_record_index, "ability_record_index")
        if self.ability_record_index < 0:
            raise ValueError("ability_record_index must be non-negative")
        for field_name in ("parameter_indices", "static_property_indices"):
            raw = getattr(self, field_name)
            if not isinstance(raw, (list, tuple)) or not all(
                isinstance(item, int) and not isinstance(item, bool) and item >= 0
                for item in raw
            ):
                raise TypeError(f"{field_name} must contain non-negative integers")
            values = tuple(raw)
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{field_name} must be unique and ordered")
            object.__setattr__(self, field_name, values)
        contribution_ids = _string_tuple(
            self.base_contribution_ids,
            "base_contribution_ids",
        )
        if not contribution_ids or len(set(contribution_ids)) != len(contribution_ids):
            raise ValueError("base contribution identities must be non-empty and unique")
        object.__setattr__(self, "base_contribution_ids", contribution_ids)
        passive_contribution_ids = _string_tuple(
            self.passive_contribution_ids,
            "passive_contribution_ids",
        ) if self.passive_contribution_ids else ()
        if len(set(passive_contribution_ids)) != len(passive_contribution_ids):
            raise ValueError("passive contribution identities must be unique")
        if set(contribution_ids).intersection(passive_contribution_ids):
            raise ValueError("base and passive contribution identities must be disjoint")
        expected_passive_contribution_ids = tuple(
            f"light_cone_passive:{self.instance_id}:rank:{self.superimposition_level}:property:{property_index}"
            for property_index in self.static_property_indices
        )
        if passive_contribution_ids and (
            passive_contribution_ids != expected_passive_contribution_ids
        ):
            raise ValueError(
                "passive contribution identities must match the selected rank properties"
            )
        object.__setattr__(
            self,
            "passive_contribution_ids",
            passive_contribution_ids,
        )
        for source in (
            self.promotion_source,
            self.superimposition_source,
            self.ability_source,
        ):
            _require_equipment_source(source)
        if (
            self.promotion_source.raw_type != "EquipmentPromotionConfig"
            or self.promotion_source.raw_id
            != f"{self.definition_key.definition_identity}:{self.promotion_stage}"
        ):
            raise ValueError("promotion selection source identity mismatch")
        if (
            self.superimposition_source.raw_type != "EquipmentSkillConfig"
            or self.superimposition_source.raw_id
            != f"{self.skill_id}:{self.superimposition_level}"
        ):
            raise ValueError("superimposition selection source identity mismatch")
        if (
            self.ability_source.raw_type != "AbilityList"
            or self.ability_source.raw_id != self.ability_name
            or self.ability_source.evidence.get("json_path")
            != f"$.AbilityList[{self.ability_record_index}]"
        ):
            raise ValueError("ability selection source identity mismatch")
        fingerprints = tuple(
            source.evidence.get("source_fingerprint")
            for source in (
                self.promotion_source,
                self.superimposition_source,
                self.ability_source,
            )
        )
        if any(item != fingerprints[0] for item in fingerprints[1:]):
            raise ValueError("light-cone selection sources must share one source fingerprint")
        object.__setattr__(
            self,
            "selection_fingerprint",
            _canonical_fingerprint(self._fingerprint_payload()),
        )

    def _fingerprint_payload(self) -> dict[str, JSONValue]:
        return {
            "instance_id": self.instance_id,
            "instance_fingerprint": self.instance_fingerprint,
            "definition_key": self.definition_key.to_json(),
            "level": self.level,
            "promotion_stage": self.promotion_stage,
            "superimposition_level": self.superimposition_level,
            "skill_id": self.skill_id,
            "parameter_indices": list(self.parameter_indices),
            "static_property_indices": list(self.static_property_indices),
            "ability_name": self.ability_name,
            "ability_record_index": self.ability_record_index,
            "promotion_source": self.promotion_source.to_json(),
            "superimposition_source": self.superimposition_source.to_json(),
            "ability_source": self.ability_source.to_json(),
            "base_contribution_ids": list(self.base_contribution_ids),
            "passive_contribution_ids": list(self.passive_contribution_ids),
        }

    def to_json(self) -> dict[str, JSONValue]:
        return {
            **self._fingerprint_payload(),
            "selection_fingerprint": self.selection_fingerprint,
        }

    @classmethod
    def from_json(cls, value: object) -> LightConeAssemblySelection:
        row = _mapping(value, "light_cone_assembly_selection")
        fields = frozenset(
            {
                "instance_id",
                "instance_fingerprint",
                "definition_key",
                "level",
                "promotion_stage",
                "superimposition_level",
                "skill_id",
                "parameter_indices",
                "static_property_indices",
                "ability_name",
                "ability_record_index",
                "promotion_source",
                "superimposition_source",
                "ability_source",
                "base_contribution_ids",
                "passive_contribution_ids",
                "selection_fingerprint",
            }
        )
        _require_exact_fields(row, fields, "light_cone_assembly_selection")
        result = cls(
            instance_id=_text(row.get("instance_id"), "instance_id"),
            instance_fingerprint=_text(
                row.get("instance_fingerprint"), "instance_fingerprint"
            ),
            definition_key=EquipmentDefinitionKey.from_json(row.get("definition_key")),
            level=_integer(row.get("level"), "level"),
            promotion_stage=_integer(row.get("promotion_stage"), "promotion_stage"),
            superimposition_level=_integer(
                row.get("superimposition_level"), "superimposition_level"
            ),
            skill_id=_text(row.get("skill_id"), "skill_id"),
            parameter_indices=tuple(
                _integer(item, "parameter_indices[]")
                for item in _sequence(row.get("parameter_indices"), "parameter_indices")
            ),
            static_property_indices=tuple(
                _integer(item, "static_property_indices[]")
                for item in _sequence(
                    row.get("static_property_indices"), "static_property_indices"
                )
            ),
            ability_name=_text(row.get("ability_name"), "ability_name"),
            ability_record_index=_integer(
                row.get("ability_record_index"), "ability_record_index"
            ),
            promotion_source=_source_from_json(row.get("promotion_source")),
            superimposition_source=_source_from_json(
                row.get("superimposition_source")
            ),
            ability_source=_source_from_json(row.get("ability_source")),
            base_contribution_ids=tuple(
                _text(item, "base_contribution_ids[]")
                for item in _sequence(
                    row.get("base_contribution_ids"), "base_contribution_ids"
                )
            ),
            passive_contribution_ids=tuple(
                _text(item, "passive_contribution_ids[]")
                for item in _sequence(
                    row.get("passive_contribution_ids"),
                    "passive_contribution_ids",
                )
            ),
        )
        encoded = _text(row.get("selection_fingerprint"), "selection_fingerprint")
        _require_sha256(encoded, "selection_fingerprint")
        if encoded != result.selection_fingerprint:
            raise ValueError("light-cone selection fingerprint mismatch")
        return result


@dataclass(frozen=True)
class EquipmentActivationBasis:
    basis_kind: Literal["light_cone_path_equality"]
    comparison_policy: Literal["exact_internal_path_identity_equality"]
    policy_origin: Literal["build_assembly_rule"]
    character_eligibility_key: EquipmentDefinitionKey
    light_cone_definition_key: EquipmentDefinitionKey
    character_path_type: str
    light_cone_path_type: str
    character_path_source: IRSource
    light_cone_path_source: IRSource

    def __post_init__(self) -> None:
        if self.basis_kind != "light_cone_path_equality":
            raise ValueError("unsupported equipment activation basis kind")
        if self.comparison_policy != "exact_internal_path_identity_equality":
            raise ValueError("unsupported equipment activation comparison policy")
        if self.policy_origin != "build_assembly_rule":
            raise ValueError("equipment activation policy must remain a derived build rule")
        _require_kind(
            self.character_eligibility_key,
            "character_equipment_eligibility",
        )
        _require_kind(self.light_cone_definition_key, "light_cone")
        _require_text(self.character_path_type, "character_path_type")
        _require_text(self.light_cone_path_type, "light_cone_path_type")
        object.__setattr__(
            self,
            "character_path_source",
            immutable_ir_source(self.character_path_source),
        )
        _require_equipment_source(self.light_cone_path_source)
        if (
            self.light_cone_path_source.raw_id
            != self.light_cone_definition_key.definition_identity
        ):
            raise ValueError("light-cone activation path source identity mismatch")

    @property
    def values_match(self) -> bool:
        return self.character_path_type == self.light_cone_path_type

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "basis_kind": self.basis_kind,
            "comparison_policy": self.comparison_policy,
            "policy_origin": self.policy_origin,
            "character_eligibility_key": self.character_eligibility_key.to_json(),
            "light_cone_definition_key": self.light_cone_definition_key.to_json(),
            "character_path_type": self.character_path_type,
            "light_cone_path_type": self.light_cone_path_type,
            "character_path_source": self.character_path_source.to_json(),
            "light_cone_path_source": self.light_cone_path_source.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> EquipmentActivationBasis:
        row = _mapping(value, "equipment_activation_basis")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "basis_kind",
                    "comparison_policy",
                    "policy_origin",
                    "character_eligibility_key",
                    "light_cone_definition_key",
                    "character_path_type",
                    "light_cone_path_type",
                    "character_path_source",
                    "light_cone_path_source",
                }
            ),
            "equipment_activation_basis",
        )
        return cls(
            basis_kind=cast(
                Literal["light_cone_path_equality"],
                _text(row.get("basis_kind"), "basis_kind"),
            ),
            comparison_policy=cast(
                Literal["exact_internal_path_identity_equality"],
                _text(row.get("comparison_policy"), "comparison_policy"),
            ),
            policy_origin=cast(
                Literal["build_assembly_rule"],
                _text(row.get("policy_origin"), "policy_origin"),
            ),
            character_eligibility_key=EquipmentDefinitionKey.from_json(
                row.get("character_eligibility_key")
            ),
            light_cone_definition_key=EquipmentDefinitionKey.from_json(
                row.get("light_cone_definition_key")
            ),
            character_path_type=_text(
                row.get("character_path_type"), "character_path_type"
            ),
            light_cone_path_type=_text(
                row.get("light_cone_path_type"), "light_cone_path_type"
            ),
            character_path_source=ir_source_from_json(
                row.get("character_path_source")
            ),
            light_cone_path_source=_source_from_json(
                row.get("light_cone_path_source")
            ),
        )


@dataclass(frozen=True)
class EquipmentActivationDecision:
    decision_id: str
    definition_key: EquipmentDefinitionKey
    activation_status: ActivationStatus
    reason_code: str
    basis: EquipmentActivationBasis

    def __post_init__(self) -> None:
        _require_text(self.decision_id, "decision_id")
        if not isinstance(self.definition_key, EquipmentDefinitionKey):
            raise TypeError("activation decision definition_key must be EquipmentDefinitionKey")
        _require_kind(self.definition_key, "light_cone")
        _require_string(self.activation_status, "activation_status")
        if self.activation_status not in {"active", "inactive"}:
            raise ValueError("invalid activation_status")
        _require_text(self.reason_code, "activation reason_code")
        if not isinstance(self.basis, EquipmentActivationBasis):
            raise TypeError("activation decision basis must be EquipmentActivationBasis")
        if self.basis.light_cone_definition_key != self.definition_key:
            raise ValueError("activation decision basis definition mismatch")
        expected_status = "active" if self.basis.values_match else "inactive"
        expected_reason = (
            "light_cone_path_match"
            if self.basis.values_match
            else "light_cone_path_mismatch"
        )
        if self.activation_status != expected_status or self.reason_code != expected_reason:
            raise ValueError("activation decision does not match the derived path comparison")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "decision_id": self.decision_id,
            "definition_key": self.definition_key.to_json(),
            "activation_status": self.activation_status,
            "reason_code": self.reason_code,
            "basis": self.basis.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> EquipmentActivationDecision:
        row = _mapping(value, "equipment_activation_decision")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "decision_id",
                    "definition_key",
                    "activation_status",
                    "reason_code",
                    "basis",
                }
            ),
            "equipment_activation_decision",
        )
        return cls(
            decision_id=_text(row.get("decision_id"), "decision_id"),
            definition_key=EquipmentDefinitionKey.from_json(row.get("definition_key")),
            activation_status=cast(
                ActivationStatus,
                _text(row.get("activation_status"), "activation_status"),
            ),
            reason_code=_text(row.get("reason_code"), "reason_code"),
            basis=EquipmentActivationBasis.from_json(row.get("basis")),
        )


@dataclass(frozen=True)
class EquipmentBattleAdmissionBlocker:
    blocker_id: str
    channel: EquipmentBattleBlockerChannel
    target_definition_key: EquipmentDefinitionKey
    gap_classification: EquipmentGapClassification
    reason_code: str
    source_refs: tuple[IRSource, ...]

    def __post_init__(self) -> None:
        _require_text(self.blocker_id, "blocker_id")
        if self.channel not in {"static_passive", "dynamic_ability"}:
            raise ValueError("invalid equipment battle blocker channel")
        _require_kind(self.target_definition_key, "light_cone")
        if self.gap_classification not in {
            "lowering_gap",
            "admission_gap",
            "implementation_missing",
        }:
            raise ValueError("invalid equipment gap classification")
        _require_text(self.reason_code, "reason_code")
        if not isinstance(self.source_refs, (list, tuple)) or not self.source_refs:
            raise TypeError("equipment battle blockers require source_refs")
        sources = tuple(self.source_refs)
        for source in sources:
            _require_equipment_source(source)
        object.__setattr__(
            self,
            "source_refs",
            tuple(
                sorted(
                    sources,
                    key=lambda item: (
                        item.source_path,
                        item.raw_type,
                        item.raw_id,
                        str(item.evidence.get("json_path") or ""),
                    ),
                )
            ),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "blocker_id": self.blocker_id,
            "channel": self.channel,
            "target_definition_key": self.target_definition_key.to_json(),
            "gap_classification": self.gap_classification,
            "reason_code": self.reason_code,
            "source_refs": [source.to_json() for source in self.source_refs],
        }

    @classmethod
    def from_json(cls, value: object) -> EquipmentBattleAdmissionBlocker:
        row = _mapping(value, "equipment_battle_admission_blocker")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "blocker_id",
                    "channel",
                    "target_definition_key",
                    "gap_classification",
                    "reason_code",
                    "source_refs",
                }
            ),
            "equipment_battle_admission_blocker",
        )
        return cls(
            blocker_id=_text(row.get("blocker_id"), "blocker_id"),
            channel=cast(
                EquipmentBattleBlockerChannel,
                _text(row.get("channel"), "channel"),
            ),
            target_definition_key=EquipmentDefinitionKey.from_json(
                row.get("target_definition_key")
            ),
            gap_classification=cast(
                EquipmentGapClassification,
                _text(row.get("gap_classification"), "gap_classification"),
            ),
            reason_code=_text(row.get("reason_code"), "reason_code"),
            source_refs=tuple(
                _source_from_json(item)
                for item in _sequence(row.get("source_refs"), "source_refs")
            ),
        )


@dataclass(frozen=True)
class EquipmentSourceLedgerEntry:
    ledger_entry_id: str
    channel: LedgerChannel
    definition_key: EquipmentDefinitionKey
    source: IRSource

    def __post_init__(self) -> None:
        _require_text(self.ledger_entry_id, "ledger_entry_id")
        _require_string(self.channel, "source ledger channel")
        if self.channel not in {"static", "dynamic", "activation"}:
            raise ValueError("invalid equipment source ledger channel")
        if not isinstance(self.definition_key, EquipmentDefinitionKey):
            raise TypeError("source ledger definition_key must be EquipmentDefinitionKey")
        _require_equipment_source(self.source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ledger_entry_id": self.ledger_entry_id,
            "channel": self.channel,
            "definition_key": self.definition_key.to_json(),
            "source": self.source.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> EquipmentSourceLedgerEntry:
        row = _mapping(value, "equipment_source_ledger_entry")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "ledger_entry_id",
                    "channel",
                    "definition_key",
                    "source",
                }
            ),
            "equipment_source_ledger_entry",
        )
        return cls(
            ledger_entry_id=_text(row.get("ledger_entry_id"), "ledger_entry_id"),
            channel=cast(LedgerChannel, _text(row.get("channel"), "channel")),
            definition_key=EquipmentDefinitionKey.from_json(row.get("definition_key")),
            source=_source_from_json(row.get("source")),
        )


@dataclass(frozen=True)
class EquipmentAssemblyDiagnostic:
    diagnostic_id: str
    reason: str
    requested_key: EquipmentDefinitionKey | None = None
    candidates: tuple[EquipmentResolutionCandidate, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.diagnostic_id, "diagnostic_id")
        _require_text(self.reason, "reason")
        if self.requested_key is not None and not isinstance(
            self.requested_key,
            EquipmentDefinitionKey,
        ):
            raise TypeError("assembly diagnostic requested_key must be EquipmentDefinitionKey or None")
        typed_candidates = cast(
            tuple[EquipmentResolutionCandidate, ...],
            _typed_tuple(
                self.candidates,
                EquipmentResolutionCandidate,
                "assembly diagnostic candidates",
            ),
        )
        object.__setattr__(
            self,
            "candidates",
            tuple(sorted(typed_candidates, key=lambda item: item.diagnostic_id)),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "diagnostic_id": self.diagnostic_id,
            "reason": self.reason,
            "requested_key": self.requested_key.to_json() if self.requested_key is not None else None,
            "candidates": [candidate.to_json() for candidate in self.candidates],
        }

    @classmethod
    def from_json(cls, value: object) -> EquipmentAssemblyDiagnostic:
        row = _mapping(value, "equipment_assembly_diagnostic")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "diagnostic_id",
                    "reason",
                    "requested_key",
                    "candidates",
                }
            ),
            "equipment_assembly_diagnostic",
        )
        requested_key = _optional_mapping(row.get("requested_key"), "requested_key")
        return cls(
            diagnostic_id=_text(row.get("diagnostic_id"), "diagnostic_id"),
            reason=_text(row.get("reason"), "reason"),
            requested_key=EquipmentDefinitionKey.from_json(requested_key) if requested_key is not None else None,
            candidates=tuple(
                EquipmentResolutionCandidate.from_json(item)
                for item in _sequence(row.get("candidates"), "candidates")
            ),
        )


@dataclass(frozen=True)
class EquipmentAssemblyResult:
    assembly_id: str
    build_fingerprint: str
    assembly_status: AssemblyStatus
    battle_admission_status: BattleAdmissionStatus
    light_cone_selection: LightConeAssemblySelection | None = None
    static_contributions: tuple[StaticStatContribution, ...] = ()
    dynamic_mechanisms: tuple[DynamicMechanismSelection, ...] = ()
    activation_decisions: tuple[EquipmentActivationDecision, ...] = ()
    battle_admission_blockers: tuple[EquipmentBattleAdmissionBlocker, ...] = ()
    source_ledger: tuple[EquipmentSourceLedgerEntry, ...] = ()
    diagnostics: tuple[EquipmentAssemblyDiagnostic, ...] = ()
    result_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        _require_text(self.assembly_id, "assembly_id")
        _require_text(self.build_fingerprint, "build_fingerprint")
        _require_sha256(self.build_fingerprint, "build_fingerprint")
        _require_string(self.assembly_status, "assembly_status")
        if self.battle_admission_status not in {"admitted", "blocked"}:
            raise ValueError("invalid equipment battle_admission_status")
        if self.light_cone_selection is not None and not isinstance(
            self.light_cone_selection,
            LightConeAssemblySelection,
        ):
            raise TypeError(
                "light_cone_selection must be LightConeAssemblySelection or None"
            )
        object.__setattr__(
            self,
            "static_contributions",
            cast(
                tuple[StaticStatContribution, ...],
                _typed_tuple(
                    self.static_contributions,
                    StaticStatContribution,
                    "static_contributions",
                ),
            ),
        )
        contribution_id_values = tuple(
            item.contribution_id for item in self.static_contributions
        )
        if len(contribution_id_values) != len(set(contribution_id_values)):
            raise ValueError("equipment static contribution identities must be unique")
        for contribution in self.static_contributions:
            if contribution.source_ref.definition_kind not in EQUIPMENT_DEFINITION_KINDS:
                raise ValueError("equipment static contribution has a non-equipment source_ref")
            _require_equipment_source(contribution.source)
        object.__setattr__(
            self,
            "dynamic_mechanisms",
            cast(
                tuple[DynamicMechanismSelection, ...],
                _typed_tuple(
                    self.dynamic_mechanisms,
                    DynamicMechanismSelection,
                    "dynamic_mechanisms",
                ),
            ),
        )
        object.__setattr__(
            self,
            "activation_decisions",
            cast(
                tuple[EquipmentActivationDecision, ...],
                _typed_tuple(
                    self.activation_decisions,
                    EquipmentActivationDecision,
                    "activation_decisions",
                ),
            ),
        )
        object.__setattr__(
            self,
            "battle_admission_blockers",
            cast(
                tuple[EquipmentBattleAdmissionBlocker, ...],
                _typed_tuple(
                    self.battle_admission_blockers,
                    EquipmentBattleAdmissionBlocker,
                    "battle_admission_blockers",
                ),
            ),
        )
        object.__setattr__(
            self,
            "source_ledger",
            cast(
                tuple[EquipmentSourceLedgerEntry, ...],
                _typed_tuple(
                    self.source_ledger,
                    EquipmentSourceLedgerEntry,
                    "source_ledger",
                ),
            ),
        )
        ledger_entry_ids = tuple(item.ledger_entry_id for item in self.source_ledger)
        if len(ledger_entry_ids) != len(set(ledger_entry_ids)):
            raise ValueError("equipment source ledger identities must be unique")
        static_ledger = {
            item.ledger_entry_id: item
            for item in self.source_ledger
            if item.channel == "static"
        }
        expected_static_ledger_ids = {
            f"equipment_source:{item.contribution_id}"
            for item in self.static_contributions
        }
        if set(static_ledger) != expected_static_ledger_ids:
            raise ValueError(
                "equipment static contributions require exactly one matching source ledger entry"
            )
        for contribution in self.static_contributions:
            entry = static_ledger[
                f"equipment_source:{contribution.contribution_id}"
            ]
            if (
                entry.definition_key.definition_kind
                != contribution.source_ref.definition_kind
                or entry.definition_key.definition_identity
                != contribution.source_ref.definition_identity
                or entry.source != contribution.source
            ):
                raise ValueError(
                    "equipment static contribution source does not match its ledger entry"
                )
        object.__setattr__(
            self,
            "diagnostics",
            cast(
                tuple[EquipmentAssemblyDiagnostic, ...],
                _typed_tuple(
                    self.diagnostics,
                    EquipmentAssemblyDiagnostic,
                    "diagnostics",
                ),
            ),
        )
        if self.assembly_status == "blocked":
            if (
                self.light_cone_selection is not None
                or self.static_contributions
                or self.dynamic_mechanisms
                or self.activation_decisions
                or self.battle_admission_blockers
                or self.source_ledger
            ):
                raise ValueError("blocked assembly results must have empty formal result channels")
            if self.battle_admission_status != "blocked" or not self.diagnostics:
                raise ValueError("blocked assembly results require diagnostics")
        elif self.assembly_status != "assembled":
            raise ValueError(f"invalid assembly_status {self.assembly_status!r}")
        else:
            if self.battle_admission_status == "admitted":
                if self.battle_admission_blockers:
                    raise ValueError("admitted equipment results cannot carry battle blockers")
            elif not self.battle_admission_blockers:
                raise ValueError("assembled but battle-blocked equipment requires blockers")
            if self.light_cone_selection is None:
                if (
                    self.static_contributions
                    or self.dynamic_mechanisms
                    or self.activation_decisions
                    or self.battle_admission_blockers
                    or self.source_ledger
                ):
                    raise ValueError(
                        "empty S4 equipment results cannot expose light-cone result channels"
                    )
            else:
                contributions_by_id = {
                    item.contribution_id: item for item in self.static_contributions
                }
                contribution_ids = set(contributions_by_id)
                if not set(self.light_cone_selection.base_contribution_ids).issubset(
                    contribution_ids
                ):
                    raise ValueError(
                        "light-cone selection base contributions are missing from the assembly result"
                    )
                matching_decisions = tuple(
                    decision
                    for decision in self.activation_decisions
                    if decision.definition_key
                    == self.light_cone_selection.definition_key
                )
                if len(matching_decisions) != 1:
                    raise ValueError(
                        "light-cone selections require exactly one matching activation decision"
                    )
                selected_base_contributions = tuple(
                    contribution
                    for contribution in self.static_contributions
                    if contribution.contribution_id
                    in self.light_cone_selection.base_contribution_ids
                )
                if any(
                    contribution.source_ref.definition_kind != "light_cone"
                    or contribution.source_ref.definition_identity
                    != self.light_cone_selection.definition_key.definition_identity
                    for contribution in selected_base_contributions
                ):
                    raise ValueError(
                        "light-cone base contributions must reference the selected definition"
                    )
                if any(
                    contribution.source_ref.definition_kind != "light_cone"
                    or contribution.source_ref.definition_identity
                    != self.light_cone_selection.definition_key.definition_identity
                    or static_ledger[
                        f"equipment_source:{contribution.contribution_id}"
                    ].definition_key
                    != self.light_cone_selection.definition_key
                    for contribution in self.static_contributions
                ):
                    raise ValueError(
                        "all light-cone static contributions and ledger entries must belong to the selected definition"
                    )
                if contribution_ids != set(
                    self.light_cone_selection.base_contribution_ids
                ).union(self.light_cone_selection.passive_contribution_ids):
                    raise ValueError(
                        "light-cone results cannot carry unselected static contributions"
                    )
                activation = matching_decisions[0]
                for mechanism in self.dynamic_mechanisms:
                    if (
                        mechanism.target_definition_key
                        != self.light_cone_selection.definition_key
                        or mechanism.equipment_instance_id
                        != self.light_cone_selection.instance_id
                        or mechanism.skill_id != self.light_cone_selection.skill_id
                        or mechanism.superimposition_level
                        != self.light_cone_selection.superimposition_level
                        or mechanism.source
                        != self.light_cone_selection.ability_source
                    ):
                        raise ValueError(
                            "light-cone dynamic mechanisms must belong to the selected instance and ability source"
                        )
                    rank_json_path = (
                        self.light_cone_selection.superimposition_source.evidence.get(
                            "json_path"
                        )
                    )
                    ability_json_path = (
                        self.light_cone_selection.ability_source.evidence.get(
                            "json_path"
                        )
                    )
                    rank_fingerprint = (
                        self.light_cone_selection.superimposition_source.evidence.get(
                            "source_fingerprint"
                        )
                    )
                    ability_fingerprint = (
                        self.light_cone_selection.ability_source.evidence.get(
                            "source_fingerprint"
                        )
                    )
                    if not isinstance(rank_json_path, str) or not isinstance(
                        ability_json_path,
                        str,
                    ):
                        raise ValueError(
                            "light-cone dynamic parameter sources require raw record paths"
                        )
                    for binding in mechanism.parameter_bindings:
                        if binding.parameter_index not in self.light_cone_selection.parameter_indices:
                            raise ValueError(
                                "dynamic parameter binding does not select a rank parameter"
                            )
                        if binding.parameter_read_id != (
                            f"equipment_parameter_read:"
                            f"{self.light_cone_selection.ability_source.source_path}:"
                            f"json_path:{ability_json_path}:"
                            f"value_type:{binding.value_type}:"
                            f"dynamic_hash:{binding.dynamic_hash}:"
                            f"parameter_index:{binding.parameter_index}"
                        ):
                            raise ValueError(
                                "dynamic parameter read identity does not match its source node"
                            )
                        if (
                            binding.value_source.raw_type != "EquipmentSkillParameter"
                            or binding.value_source.raw_id
                            != (
                                f"{self.light_cone_selection.skill_id}:"
                                f"{self.light_cone_selection.superimposition_level}:"
                                f"{binding.parameter_index}"
                            )
                            or binding.value_source.source_path
                            != self.light_cone_selection.superimposition_source.source_path
                            or binding.value_source.evidence.get("json_path")
                            != (
                                f"{rank_json_path}.ParamList["
                                f"{binding.parameter_index}].Value"
                            )
                            or binding.value_source.evidence.get("source_fingerprint")
                            != rank_fingerprint
                        ):
                            raise ValueError(
                                "dynamic parameter value source does not match the selected rank row"
                            )
                        if (
                            binding.read_source.raw_type
                            != "EquipmentAbilityParameterRead"
                            or binding.read_source.raw_id
                            != (
                                f"{self.light_cone_selection.ability_name}:"
                                f"{binding.dynamic_hash}:{binding.parameter_index}"
                            )
                            or binding.read_source.source_path
                            != self.light_cone_selection.ability_source.source_path
                            or binding.read_source.evidence.get("json_path")
                            != (
                                f"{ability_json_path}.DynamicValues."
                                f"{binding.value_type}.{binding.dynamic_hash}.ReadInfo"
                            )
                            or binding.read_source.evidence.get("source_fingerprint")
                            != ability_fingerprint
                        ):
                            raise ValueError(
                                "dynamic parameter read source does not match the selected ability row"
                            )
                expected_passive_ids = tuple(
                    f"light_cone_passive:{self.light_cone_selection.instance_id}:"
                    f"rank:{self.light_cone_selection.superimposition_level}:"
                    f"property:{property_index}"
                    for property_index in self.light_cone_selection.static_property_indices
                )
                if activation.activation_status == "active":
                    if (
                        self.light_cone_selection.passive_contribution_ids
                        != expected_passive_ids
                    ):
                        raise ValueError(
                            "active light-cone passives must exactly match the selected rank properties"
                        )
                    rank_json_path = (
                        self.light_cone_selection.superimposition_source.evidence.get(
                            "json_path"
                        )
                    )
                    rank_source_fingerprint = (
                        self.light_cone_selection.superimposition_source.evidence.get(
                            "source_fingerprint"
                        )
                    )
                    if not isinstance(rank_json_path, str) or not rank_json_path:
                        raise ValueError(
                            "selected light-cone rank requires a concrete raw record path"
                        )
                    for property_index, contribution_id in zip(
                        self.light_cone_selection.static_property_indices,
                        expected_passive_ids,
                        strict=True,
                    ):
                        contribution = contributions_by_id[contribution_id]
                        source = contribution.source
                        if (
                            source.raw_type != "EquipmentSkillStaticProperty"
                            or source.raw_id
                            != (
                                f"{self.light_cone_selection.skill_id}:"
                                f"{self.light_cone_selection.superimposition_level}:"
                                f"{property_index}"
                            )
                            or source.source_path
                            != self.light_cone_selection.superimposition_source.source_path
                            or source.evidence.get("json_path")
                            != (
                                f"{rank_json_path}.AbilityProperty["
                                f"{property_index}].Value.Value"
                            )
                            or source.evidence.get("source_fingerprint")
                            != rank_source_fingerprint
                        ):
                            raise ValueError(
                                "light-cone passive contribution source does not match the selected rank property"
                            )
                if (
                    activation.activation_status == "inactive"
                    and (
                        self.light_cone_selection.passive_contribution_ids
                        or self.dynamic_mechanisms
                        or self.battle_admission_blockers
                    )
                ):
                    raise ValueError(
                        "inactive light-cone passives cannot expose passive result channels"
                    )
                if activation.activation_status == "active":
                    if self.battle_admission_status == "admitted" and (
                        len(self.dynamic_mechanisms) != 1
                        or self.dynamic_mechanisms[0].coverage_status != "executable"
                    ):
                        raise ValueError(
                            "battle-admitted active light-cone abilities require one executable dynamic selection"
                        )
                    if any(
                        mechanism.coverage_status == "blocked"
                        for mechanism in self.dynamic_mechanisms
                    ) and not self.battle_admission_blockers:
                        raise ValueError(
                            "blocked dynamic selections require a battle admission blocker"
                        )
                if any(
                    blocker.target_definition_key
                    != self.light_cone_selection.definition_key
                    for blocker in self.battle_admission_blockers
                ):
                    raise ValueError(
                        "light-cone battle blockers must target the selected definition"
                    )
        object.__setattr__(self, "result_fingerprint", _canonical_fingerprint(self._fingerprint_payload()))

    def _fingerprint_payload(self) -> dict[str, JSONValue]:
        return {
            "assembly_id": self.assembly_id,
            "build_fingerprint": self.build_fingerprint,
            "assembly_status": self.assembly_status,
            "battle_admission_status": self.battle_admission_status,
            "light_cone_selection": (
                self.light_cone_selection.to_json()
                if self.light_cone_selection is not None
                else None
            ),
            "static_contributions": [item.to_json() for item in self.static_contributions],
            "dynamic_mechanisms": [item.to_json() for item in self.dynamic_mechanisms],
            "activation_decisions": [item.to_json() for item in self.activation_decisions],
            "battle_admission_blockers": [
                item.to_json() for item in self.battle_admission_blockers
            ],
            "source_ledger": [item.to_json() for item in self.source_ledger],
            "diagnostics": [item.to_json() for item in self.diagnostics],
        }

    def to_json(self) -> dict[str, JSONValue]:
        return {**self._fingerprint_payload(), "result_fingerprint": self.result_fingerprint}

    @classmethod
    def from_json(cls, value: object) -> EquipmentAssemblyResult:
        row = _mapping(value, "equipment_assembly_result")
        _require_exact_fields(
            row,
            frozenset(
                {
                    "assembly_id",
                    "build_fingerprint",
                    "assembly_status",
                    "battle_admission_status",
                    "light_cone_selection",
                    "static_contributions",
                    "dynamic_mechanisms",
                    "activation_decisions",
                    "battle_admission_blockers",
                    "source_ledger",
                    "diagnostics",
                    "result_fingerprint",
                }
            ),
            "equipment_assembly_result",
        )
        selection = row.get("light_cone_selection")
        result = cls(
            assembly_id=_text(row.get("assembly_id"), "assembly_id"),
            build_fingerprint=_text(row.get("build_fingerprint"), "build_fingerprint"),
            assembly_status=cast(AssemblyStatus, _text(row.get("assembly_status"), "assembly_status")),
            battle_admission_status=cast(
                BattleAdmissionStatus,
                _text(row.get("battle_admission_status"), "battle_admission_status"),
            ),
            light_cone_selection=(
                LightConeAssemblySelection.from_json(selection)
                if selection is not None
                else None
            ),
            static_contributions=tuple(
                StaticStatContribution.from_json(item)
                for item in _sequence(row.get("static_contributions"), "static_contributions")
            ),
            dynamic_mechanisms=tuple(
                DynamicMechanismSelection.from_json(item)
                for item in _sequence(row.get("dynamic_mechanisms"), "dynamic_mechanisms")
            ),
            activation_decisions=tuple(
                EquipmentActivationDecision.from_json(item)
                for item in _sequence(row.get("activation_decisions"), "activation_decisions")
            ),
            battle_admission_blockers=tuple(
                EquipmentBattleAdmissionBlocker.from_json(item)
                for item in _sequence(
                    row.get("battle_admission_blockers"),
                    "battle_admission_blockers",
                )
            ),
            source_ledger=tuple(
                EquipmentSourceLedgerEntry.from_json(item)
                for item in _sequence(row.get("source_ledger"), "source_ledger")
            ),
            diagnostics=tuple(
                EquipmentAssemblyDiagnostic.from_json(item)
                for item in _sequence(row.get("diagnostics"), "diagnostics")
            ),
        )
        encoded_fingerprint = _text(row.get("result_fingerprint"), "result_fingerprint")
        _require_sha256(encoded_fingerprint, "result_fingerprint")
        if encoded_fingerprint != result.result_fingerprint:
            raise ValueError("equipment assembly result fingerprint does not match the encoded payload")
        return result


def _require_kind(key: EquipmentDefinitionKey, expected: EquipmentDefinitionKind) -> None:
    if not isinstance(key, EquipmentDefinitionKey):
        raise TypeError("equipment definition references must use EquipmentDefinitionKey")
    if key.definition_kind != expected:
        raise TypeError(
            f"equipment definition key kind {key.definition_kind!r} does not match {expected!r}"
        )


def _definition_json(
    definition_key: EquipmentDefinitionKey,
    source: IRSource,
    coverage_status: CoverageStatus,
    blocked_reason: str,
    fields: Mapping[str, JSONValue],
) -> dict[str, JSONValue]:
    return {
        "definition_key": definition_key.to_json(),
        **dict(fields),
        "source": source.to_json(),
        "coverage_status": coverage_status,
        "blocked_reason": blocked_reason,
    }


def _coverage_from_json(row: Mapping[str, object]) -> CoverageStatus:
    return cast(CoverageStatus, _text(row.get("coverage_status"), "coverage_status"))
