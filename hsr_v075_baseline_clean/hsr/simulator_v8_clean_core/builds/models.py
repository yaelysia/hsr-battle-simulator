from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Literal, TypeVar, cast

from ..build_types import (
    BuildSourceRef,
    StaticStatAggregate,
    StaticStatContribution,
    aggregate_static_stat_contributions,
    canonical_decimal,
    canonical_json_fingerprint,
    immutable_ir_source,
    ir_source_from_json,
    require_int,
    require_sha256,
    require_text,
)
from ..equipment.models import EquipmentAssemblyResult, EquipmentBuildInput
from ..immutable_json import freeze_json, thaw_json
from ..ir_types import IRSource, JSONValue, same_ir_source_raw_row


AssemblyStatus = Literal["assembled", "blocked"]
BattleAdmissionStatus = Literal["admitted", "blocked"]
MechanismKind = Literal["trace_ability", "eidolon_ability"]
SkillLevelSourceKind = Literal["trace_base", "fixed_action", "eidolon_bonus"]
_T = TypeVar("_T")


def _closed_mapping(value: object, field_name: str, allowed: set[str]) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} must be a JSON object")
    extra = sorted(set(value).difference(allowed))
    if extra:
        raise ValueError(f"{field_name} contains unsupported fields: {extra}")
    return cast(Mapping[str, object], value)


def _string_sequence(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be a list or tuple")
    result = tuple(require_text(item, f"{field_name}[]") for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"{field_name} contains duplicate identities")
    return result


@dataclass(frozen=True)
class CharacterBuildInput:
    build_id: str
    character_card_id: str
    level: int
    promotion: int
    eidolon_level: int
    unlocked_trace_node_ids: tuple[str, ...]
    equipment_build: EquipmentBuildInput
    input_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        require_text(self.build_id, "build_id")
        require_text(self.character_card_id, "character_card_id")
        require_int(self.level, "level")
        require_int(self.promotion, "promotion")
        require_int(self.eidolon_level, "eidolon_level")
        if self.level <= 0 or self.promotion < 0 or self.eidolon_level < 0:
            raise ValueError("character progression values are outside the non-negative input boundary")
        object.__setattr__(
            self,
            "unlocked_trace_node_ids",
            tuple(sorted(_string_sequence(self.unlocked_trace_node_ids, "unlocked_trace_node_ids"))),
        )
        if not isinstance(self.equipment_build, EquipmentBuildInput):
            raise TypeError("equipment_build must be EquipmentBuildInput")
        if self.equipment_build.character_card_id != self.character_card_id:
            raise ValueError("embedded equipment build character_card_id mismatch")
        object.__setattr__(
            self,
            "input_fingerprint",
            canonical_json_fingerprint(self._fingerprint_payload()),
        )

    def _fingerprint_payload(self) -> dict[str, JSONValue]:
        return {
            "build_id": self.build_id,
            "character_card_id": self.character_card_id,
            "level": self.level,
            "promotion": self.promotion,
            "eidolon_level": self.eidolon_level,
            "unlocked_trace_node_ids": list(self.unlocked_trace_node_ids),
            "equipment_build": self.equipment_build.to_json(),
        }

    def to_json(self) -> dict[str, JSONValue]:
        return {**self._fingerprint_payload(), "input_fingerprint": self.input_fingerprint}

    @classmethod
    def from_json(cls, value: object) -> CharacterBuildInput:
        row = _closed_mapping(
            value,
            "character_build",
            {
                "build_id",
                "character_card_id",
                "level",
                "promotion",
                "eidolon_level",
                "unlocked_trace_node_ids",
                "equipment_build",
                "input_fingerprint",
            },
        )
        equipment_row = _closed_mapping(
            row.get("equipment_build"),
            "equipment_build",
            {
                "build_id",
                "character_card_id",
                "light_cone",
                "relics",
                "identity_labels",
                "build_fingerprint",
            },
        )
        result = cls(
            build_id=require_text(row.get("build_id"), "build_id"),
            character_card_id=require_text(row.get("character_card_id"), "character_card_id"),
            level=require_int(row.get("level"), "level"),
            promotion=require_int(row.get("promotion"), "promotion"),
            eidolon_level=require_int(row.get("eidolon_level"), "eidolon_level"),
            unlocked_trace_node_ids=_string_sequence(
                row.get("unlocked_trace_node_ids"),
                "unlocked_trace_node_ids",
            ),
            equipment_build=EquipmentBuildInput.from_json(equipment_row),
        )
        encoded = row.get("input_fingerprint")
        if encoded is not None:
            require_sha256(encoded, "input_fingerprint")
            if encoded != result.input_fingerprint:
                raise ValueError("character build input fingerprint mismatch")
        return result


@dataclass(frozen=True)
class CharacterInitialResourceValue:
    resource_definition_id: str
    source_kind: Literal["ability_battle_entry_initializer"] = (
        "ability_battle_entry_initializer"
    )

    def __post_init__(self) -> None:
        require_text(self.resource_definition_id, "resource_definition_id")
        if self.source_kind != "ability_battle_entry_initializer":
            raise ValueError("initial special resource must use its ability initializer")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "resource_definition_id": self.resource_definition_id,
            "source_kind": self.source_kind,
        }

    @classmethod
    def from_json(cls, value: object) -> CharacterInitialResourceValue:
        row = _closed_mapping(
            value,
            "initial_resource_value",
            {"resource_definition_id", "source_kind"},
        )
        return cls(
            resource_definition_id=require_text(
                row.get("resource_definition_id"),
                "resource_definition_id",
            ),
            source_kind=cast(
                Literal["ability_battle_entry_initializer"],
                require_text(row.get("source_kind"), "source_kind"),
            ),
        )


@dataclass(frozen=True)
class CharacterInitialConditionInput:
    hp_mode: Literal["full"]
    initial_energy: str | None
    initial_resource_values: tuple[CharacterInitialResourceValue, ...] = ()

    def __post_init__(self) -> None:
        if self.hp_mode != "full":
            raise ValueError("S2 formal character initial hp_mode must be full")
        if self.initial_energy is not None:
            object.__setattr__(
                self,
                "initial_energy",
                canonical_decimal(self.initial_energy, "initial_energy"),
            )
        if self.initial_energy not in {None, "0"}:
            raise ValueError("S2 formal character initial energy must be explicitly zero")
        if not isinstance(self.initial_resource_values, (list, tuple)) or not all(
            isinstance(item, CharacterInitialResourceValue)
            for item in self.initial_resource_values
        ):
            raise TypeError(
                "initial_resource_values must contain CharacterInitialResourceValue values"
            )
        values = tuple(
            sorted(
                self.initial_resource_values,
                key=lambda item: item.resource_definition_id,
            )
        )
        identities = [item.resource_definition_id for item in values]
        if len(set(identities)) != len(identities):
            raise ValueError("initial_resource_values contains duplicate definitions")
        object.__setattr__(self, "initial_resource_values", values)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "hp_mode": self.hp_mode,
            "initial_energy": self.initial_energy,
            "initial_resource_values": [
                item.to_json() for item in self.initial_resource_values
            ],
        }

    @classmethod
    def from_json(cls, value: object) -> CharacterInitialConditionInput:
        row = _closed_mapping(
            value,
            "initial_condition",
            {"hp_mode", "initial_energy", "initial_resource_values"},
        )
        raw_values = row.get("initial_resource_values", ())
        if not isinstance(raw_values, (list, tuple)):
            raise TypeError("initial_resource_values must be a JSON array")
        raw_energy = row.get("initial_energy")
        return cls(
            hp_mode=cast(Literal["full"], require_text(row.get("hp_mode"), "hp_mode")),
            initial_energy=(
                require_text(raw_energy, "initial_energy")
                if raw_energy is not None
                else None
            ),
            initial_resource_values=tuple(
                CharacterInitialResourceValue.from_json(item)
                for item in raw_values
            ),
        )


@dataclass(frozen=True)
class CharacterResourceInitializerBinding:
    initializer_id: str
    maximum_value_dynamic_key: str
    maximum_value_dynamic_hash: int
    level_dynamic_key: str
    level_dynamic_hash: int
    zero_floor_dynamic_hash: int
    world_level_threshold: int
    low_world_level_expression: dict[str, JSONValue]
    high_world_level_expression: dict[str, JSONValue]
    minimum_expression: dict[str, JSONValue]
    initial_current_expression: dict[str, JSONValue]
    initial_current_binding_hash: int
    initial_current_binding_value: str
    level_source: Literal["highest_alive_non_servant_ally"]
    initial_current_trigger: Literal["first_wave_battle_entry_without_technique"]
    sources: tuple[IRSource, ...]
    source: IRSource

    def __post_init__(self) -> None:
        for field_name in (
            "initializer_id",
            "maximum_value_dynamic_key",
            "level_dynamic_key",
        ):
            require_text(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "initial_current_binding_value",
            canonical_decimal(
                self.initial_current_binding_value,
                "initial_current_binding_value",
            ),
        )
        initial_ratio = Decimal(self.initial_current_binding_value)
        if initial_ratio < 0 or initial_ratio > 1:
            raise ValueError("initial_current_binding_value must be between zero and one")
        for field_name in (
            "maximum_value_dynamic_hash",
            "level_dynamic_hash",
            "zero_floor_dynamic_hash",
            "world_level_threshold",
            "initial_current_binding_hash",
        ):
            require_int(getattr(self, field_name), field_name)
        if self.world_level_threshold < 0:
            raise ValueError("world_level_threshold cannot be negative")
        if self.level_source != "highest_alive_non_servant_ally":
            raise ValueError("unsupported special-resource level source")
        if self.initial_current_trigger != "first_wave_battle_entry_without_technique":
            raise ValueError("unsupported special-resource initial trigger")
        for field_name in (
            "low_world_level_expression",
            "high_world_level_expression",
            "minimum_expression",
            "initial_current_expression",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, Mapping):
                raise TypeError(f"{field_name} must be a typed numeric expression")
            object.__setattr__(self, field_name, freeze_json(value))
        object.__setattr__(self, "source", immutable_ir_source(self.source))
        if not isinstance(self.sources, (list, tuple)) or not all(
            isinstance(item, IRSource) for item in self.sources
        ):
            raise TypeError("special-resource initializer sources must contain IRSource values")
        object.__setattr__(
            self,
            "sources",
            tuple(
                sorted(
                    (immutable_ir_source(item) for item in self.sources),
                    key=lambda item: (item.source_path, item.raw_type, item.raw_id),
                )
            ),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "initializer_id": self.initializer_id,
            "maximum_value_dynamic_key": self.maximum_value_dynamic_key,
            "maximum_value_dynamic_hash": self.maximum_value_dynamic_hash,
            "level_dynamic_key": self.level_dynamic_key,
            "level_dynamic_hash": self.level_dynamic_hash,
            "zero_floor_dynamic_hash": self.zero_floor_dynamic_hash,
            "world_level_threshold": self.world_level_threshold,
            "low_world_level_expression": thaw_json(self.low_world_level_expression),
            "high_world_level_expression": thaw_json(self.high_world_level_expression),
            "minimum_expression": thaw_json(self.minimum_expression),
            "initial_current_expression": thaw_json(self.initial_current_expression),
            "initial_current_binding_hash": self.initial_current_binding_hash,
            "initial_current_binding_value": self.initial_current_binding_value,
            "level_source": self.level_source,
            "initial_current_trigger": self.initial_current_trigger,
            "sources": [item.to_json() for item in self.sources],
            "source": self.source.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> CharacterResourceInitializerBinding:
        row = _closed_mapping(
            value,
            "character_resource_initializer_binding",
            {
                "initializer_id",
                "maximum_value_dynamic_key",
                "maximum_value_dynamic_hash",
                "level_dynamic_key",
                "level_dynamic_hash",
                "zero_floor_dynamic_hash",
                "world_level_threshold",
                "low_world_level_expression",
                "high_world_level_expression",
                "minimum_expression",
                "initial_current_expression",
                "initial_current_binding_hash",
                "initial_current_binding_value",
                "level_source",
                "initial_current_trigger",
                "sources",
                "source",
            },
        )
        raw_sources = row.get("sources")
        if not isinstance(raw_sources, (list, tuple)):
            raise TypeError("character_resource_initializer_binding.sources must be an array")
        expressions = {
            name: row.get(name)
            for name in (
                "low_world_level_expression",
                "high_world_level_expression",
                "minimum_expression",
                "initial_current_expression",
            )
        }
        if not all(isinstance(item, Mapping) for item in expressions.values()):
            raise TypeError("character resource initializer expressions must be objects")
        return cls(
            initializer_id=require_text(row.get("initializer_id"), "initializer_id"),
            maximum_value_dynamic_key=require_text(
                row.get("maximum_value_dynamic_key"), "maximum_value_dynamic_key"
            ),
            maximum_value_dynamic_hash=require_int(
                row.get("maximum_value_dynamic_hash"), "maximum_value_dynamic_hash"
            ),
            level_dynamic_key=require_text(row.get("level_dynamic_key"), "level_dynamic_key"),
            level_dynamic_hash=require_int(row.get("level_dynamic_hash"), "level_dynamic_hash"),
            zero_floor_dynamic_hash=require_int(
                row.get("zero_floor_dynamic_hash"), "zero_floor_dynamic_hash"
            ),
            world_level_threshold=require_int(
                row.get("world_level_threshold"), "world_level_threshold"
            ),
            low_world_level_expression=cast(dict[str, JSONValue], expressions["low_world_level_expression"]),
            high_world_level_expression=cast(dict[str, JSONValue], expressions["high_world_level_expression"]),
            minimum_expression=cast(dict[str, JSONValue], expressions["minimum_expression"]),
            initial_current_expression=cast(dict[str, JSONValue], expressions["initial_current_expression"]),
            initial_current_binding_hash=require_int(
                row.get("initial_current_binding_hash"), "initial_current_binding_hash"
            ),
            initial_current_binding_value=require_text(
                row.get("initial_current_binding_value"), "initial_current_binding_value"
            ),
            level_source=cast(
                Literal["highest_alive_non_servant_ally"],
                require_text(row.get("level_source"), "level_source"),
            ),
            initial_current_trigger=cast(
                Literal["first_wave_battle_entry_without_technique"],
                require_text(row.get("initial_current_trigger"), "initial_current_trigger"),
            ),
            sources=tuple(ir_source_from_json(item) for item in raw_sources),
            source=ir_source_from_json(row.get("source")),
        )


@dataclass(frozen=True)
class CharacterResourceBinding:
    resource_definition_id: str
    current_property: str
    maximum_property: str
    current_resource_key: str
    maximum_resource_key: str
    initial_current_mode: Literal["ability_battle_entry_initializer"]
    maximum_initialization_mode: Literal["ability_initializer"]
    initializer_task_names: tuple[str, ...]
    initializer: CharacterResourceInitializerBinding
    source: IRSource
    supporting_sources: tuple[IRSource, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "resource_definition_id",
            "current_property",
            "maximum_property",
            "current_resource_key",
            "maximum_resource_key",
        ):
            require_text(getattr(self, field_name), field_name)
        if self.current_resource_key == self.maximum_resource_key:
            raise ValueError("special resource current and maximum slots must differ")
        if self.initial_current_mode != "ability_battle_entry_initializer":
            raise ValueError("unsupported special resource initial-current mode")
        if self.maximum_initialization_mode != "ability_initializer":
            raise ValueError("unsupported special resource maximum-initialization mode")
        if not isinstance(self.initializer, CharacterResourceInitializerBinding):
            raise TypeError("initializer must be CharacterResourceInitializerBinding")
        object.__setattr__(
            self,
            "initializer_task_names",
            tuple(sorted(_string_sequence(self.initializer_task_names, "initializer_task_names"))),
        )
        object.__setattr__(self, "source", immutable_ir_source(self.source))
        if not isinstance(self.supporting_sources, (list, tuple)) or not all(
            isinstance(item, IRSource) for item in self.supporting_sources
        ):
            raise TypeError("supporting_sources must contain IRSource values")
        sources = tuple(immutable_ir_source(item) for item in self.supporting_sources)
        source_ids = [
            (item.source_path, item.raw_type, item.raw_id) for item in sources
        ]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("supporting_sources contains duplicate identities")
        object.__setattr__(
            self,
            "supporting_sources",
            tuple(sorted(sources, key=lambda item: (item.source_path, item.raw_type, item.raw_id))),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "resource_definition_id": self.resource_definition_id,
            "current_property": self.current_property,
            "maximum_property": self.maximum_property,
            "current_resource_key": self.current_resource_key,
            "maximum_resource_key": self.maximum_resource_key,
            "initial_current_mode": self.initial_current_mode,
            "maximum_initialization_mode": self.maximum_initialization_mode,
            "initializer_task_names": list(self.initializer_task_names),
            "initializer": self.initializer.to_json(),
            "source": self.source.to_json(),
            "supporting_sources": [item.to_json() for item in self.supporting_sources],
        }

    @classmethod
    def from_json(cls, value: object) -> CharacterResourceBinding:
        row = _closed_mapping(
            value,
            "character_resource_binding",
            {
                "resource_definition_id",
                "current_property",
                "maximum_property",
                "current_resource_key",
                "maximum_resource_key",
                "initial_current_mode",
                "maximum_initialization_mode",
                "initializer_task_names",
                "initializer",
                "source",
                "supporting_sources",
            },
        )
        raw_sources = row.get("supporting_sources")
        if not isinstance(raw_sources, (list, tuple)):
            raise TypeError("supporting_sources must be a JSON array")
        return cls(
            resource_definition_id=require_text(
                row.get("resource_definition_id"),
                "resource_definition_id",
            ),
            current_property=require_text(row.get("current_property"), "current_property"),
            maximum_property=require_text(row.get("maximum_property"), "maximum_property"),
            current_resource_key=require_text(
                row.get("current_resource_key"),
                "current_resource_key",
            ),
            maximum_resource_key=require_text(
                row.get("maximum_resource_key"),
                "maximum_resource_key",
            ),
            initial_current_mode=cast(
                Literal["ability_battle_entry_initializer"],
                require_text(row.get("initial_current_mode"), "initial_current_mode"),
            ),
            maximum_initialization_mode=cast(
                Literal["ability_initializer"],
                require_text(
                    row.get("maximum_initialization_mode"),
                    "maximum_initialization_mode",
                ),
            ),
            initializer_task_names=_string_sequence(
                row.get("initializer_task_names"),
                "initializer_task_names",
            ),
            initializer=CharacterResourceInitializerBinding.from_json(
                row.get("initializer")
            ),
            source=ir_source_from_json(row.get("source")),
            supporting_sources=tuple(
                ir_source_from_json(item) for item in raw_sources
            ),
        )


@dataclass(frozen=True)
class CharacterPanelResource:
    property_type: str
    exact_value: str

    def __post_init__(self) -> None:
        require_text(self.property_type, "property_type")
        object.__setattr__(
            self,
            "exact_value",
            canonical_decimal(self.exact_value, "exact_value"),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {"property_type": self.property_type, "exact_value": self.exact_value}

    @classmethod
    def from_json(cls, value: object) -> CharacterPanelResource:
        row = _closed_mapping(value, "panel_resource", {"property_type", "exact_value"})
        return cls(
            property_type=require_text(row.get("property_type"), "property_type"),
            exact_value=require_text(row.get("exact_value"), "exact_value"),
        )


@dataclass(frozen=True)
class CharacterBasePanel:
    max_hp: str
    attack: str
    defense: str
    speed: str
    max_energy: str | None
    critical_chance: str
    critical_damage: str
    base_aggro: str
    additional_resources: tuple[CharacterPanelResource, ...] = ()
    resource_mode: Literal["standard_energy", "special_resource"] = "standard_energy"
    special_resource_binding: CharacterResourceBinding | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "max_hp",
            "attack",
            "defense",
            "speed",
            "critical_chance",
            "critical_damage",
            "base_aggro",
        ):
            object.__setattr__(
                self,
                field_name,
                canonical_decimal(getattr(self, field_name), field_name),
            )
        if self.max_energy is not None:
            object.__setattr__(
                self,
                "max_energy",
                canonical_decimal(self.max_energy, "max_energy"),
            )
        if self.resource_mode not in {"standard_energy", "special_resource"}:
            raise ValueError("invalid character panel resource_mode")
        if self.resource_mode == "standard_energy":
            if self.max_energy is None or self.special_resource_binding is not None:
                raise ValueError(
                    "standard-energy panel requires max_energy and no special resource binding"
                )
        elif (
            self.max_energy is not None
            or not isinstance(self.special_resource_binding, CharacterResourceBinding)
        ):
            raise ValueError(
                "special-resource panel requires a typed binding and no ordinary max_energy"
            )
        if not isinstance(self.additional_resources, (list, tuple)) or not all(
            isinstance(item, CharacterPanelResource) for item in self.additional_resources
        ):
            raise TypeError("additional_resources must contain CharacterPanelResource values")
        resource_ids = [item.property_type for item in self.additional_resources]
        if len(set(resource_ids)) != len(resource_ids):
            raise ValueError("additional_resources contains duplicate property types")
        object.__setattr__(
            self,
            "additional_resources",
            tuple(sorted(self.additional_resources, key=lambda item: item.property_type)),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "max_hp": self.max_hp,
            "attack": self.attack,
            "defense": self.defense,
            "speed": self.speed,
            "max_energy": self.max_energy,
            "critical_chance": self.critical_chance,
            "critical_damage": self.critical_damage,
            "base_aggro": self.base_aggro,
            "additional_resources": [item.to_json() for item in self.additional_resources],
            "resource_mode": self.resource_mode,
            "special_resource_binding": (
                self.special_resource_binding.to_json()
                if self.special_resource_binding is not None
                else None
            ),
        }

    @classmethod
    def from_json(cls, value: object) -> CharacterBasePanel:
        names = {
            "max_hp",
            "attack",
            "defense",
            "speed",
            "max_energy",
            "critical_chance",
            "critical_damage",
            "base_aggro",
            "additional_resources",
            "resource_mode",
            "special_resource_binding",
        }
        row = _closed_mapping(value, "base_panel", names)
        resources = row.get("additional_resources")
        if not isinstance(resources, (list, tuple)):
            raise TypeError("additional_resources must be a JSON array")
        scalar_names = names.difference(
            {
                "additional_resources",
                "resource_mode",
                "special_resource_binding",
                "max_energy",
            }
        )
        special_binding = row.get("special_resource_binding")
        resource_mode = cast(
            Literal["standard_energy", "special_resource"],
            require_text(row.get("resource_mode", "standard_energy"), "resource_mode"),
        )
        raw_max_energy = row.get("max_energy")
        return cls(
            **{name: require_text(row.get(name), name) for name in scalar_names},
            max_energy=(
                require_text(raw_max_energy, "max_energy")
                if raw_max_energy is not None
                else None
            ),
            additional_resources=tuple(CharacterPanelResource.from_json(item) for item in resources),
            resource_mode=resource_mode,
            special_resource_binding=(
                CharacterResourceBinding.from_json(special_binding)
                if special_binding is not None
                else None
            ),
        )


@dataclass(frozen=True)
class CharacterSkillLevelSource:
    source_kind: SkillLevelSourceKind
    level_value: int
    source_ref: BuildSourceRef
    source: IRSource

    def __post_init__(self) -> None:
        if self.source_kind not in {"trace_base", "fixed_action", "eidolon_bonus"}:
            raise ValueError("invalid skill level source_kind")
        require_int(self.level_value, "level_value")
        if self.level_value <= 0:
            raise ValueError("skill level source value must be positive")
        if not isinstance(self.source_ref, BuildSourceRef):
            raise TypeError("source_ref must be BuildSourceRef")
        expected_kind = (
            "character_action_definition"
            if self.source_kind == "fixed_action"
            else "character_mechanism_slot"
        )
        if self.source_ref.definition_kind != expected_kind:
            raise ValueError(
                f"{self.source_kind} skill level source must use {expected_kind} namespace"
            )
        object.__setattr__(self, "source", immutable_ir_source(self.source))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "source_kind": self.source_kind,
            "level_value": self.level_value,
            "source_ref": self.source_ref.to_json(),
            "source": self.source.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> CharacterSkillLevelSource:
        row = _closed_mapping(
            value,
            "skill_level_source",
            {"source_kind", "level_value", "source_ref", "source"},
        )
        return cls(
            source_kind=cast(
                SkillLevelSourceKind,
                require_text(row.get("source_kind"), "source_kind"),
            ),
            level_value=require_int(row.get("level_value"), "level_value"),
            source_ref=BuildSourceRef.from_json(row.get("source_ref")),
            source=ir_source_from_json(row.get("source")),
        )


@dataclass(frozen=True)
class CharacterSkillLevelResolution:
    skill_id: str
    action_id: str
    action_definition_id: str
    action_record_source: IRSource
    action_definition_source: IRSource
    base_level: int
    eidolon_level_bonus: int
    effective_level: int
    sources: tuple[CharacterSkillLevelSource, ...]

    def __post_init__(self) -> None:
        require_text(self.skill_id, "skill_id")
        require_text(self.action_id, "action_id")
        require_text(self.action_definition_id, "action_definition_id")
        if self.action_id not in {
            f"avatar_skill:{self.skill_id}",
            f"servant_skill:{self.skill_id}",
        }:
            raise ValueError(
                "skill level action_id must use the canonical combatant skill namespace"
            )
        object.__setattr__(
            self,
            "action_record_source",
            immutable_ir_source(
                self.action_record_source,
                "action_record_source",
            ),
        )
        object.__setattr__(
            self,
            "action_definition_source",
            immutable_ir_source(
                self.action_definition_source,
                "action_definition_source",
            ),
        )
        require_int(self.base_level, "base_level")
        require_int(self.eidolon_level_bonus, "eidolon_level_bonus")
        require_int(self.effective_level, "effective_level")
        if self.base_level <= 0 or self.eidolon_level_bonus < 0:
            raise ValueError("skill levels are outside the admitted range")
        if self.effective_level != self.base_level + self.eidolon_level_bonus:
            raise ValueError("effective skill level must equal base level plus eidolon bonus")
        if not same_ir_source_raw_row(
            self.action_record_source,
            self.action_definition_source,
            expected_level=self.effective_level,
        ):
            raise ValueError(
                "skill level action record and definition must identify the same raw row"
            )
        if not isinstance(self.sources, (list, tuple)) or not all(
            isinstance(item, CharacterSkillLevelSource) for item in self.sources
        ):
            raise TypeError("skill level sources must be a typed sequence")
        sources = tuple(self.sources)
        source_ids = [item.source_ref.stable_id for item in sources]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("skill level sources contain duplicate identities")
        base_sources = tuple(
            item for item in sources if item.source_kind in {"trace_base", "fixed_action"}
        )
        bonus_sources = tuple(item for item in sources if item.source_kind == "eidolon_bonus")
        if len(base_sources) != 1 or base_sources[0].level_value != self.base_level:
            raise ValueError("skill level resolution requires exactly one matching base source")
        if sum(item.level_value for item in bonus_sources) != self.eidolon_level_bonus:
            raise ValueError("skill level eidolon bonus does not match its sources")
        source_order = {"trace_base": 0, "fixed_action": 0, "eidolon_bonus": 1}
        object.__setattr__(
            self,
            "sources",
            tuple(
                sorted(
                    sources,
                    key=lambda item: (source_order[item.source_kind], item.source_ref.stable_id),
                )
            ),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "skill_id": self.skill_id,
            "action_id": self.action_id,
            "action_definition_id": self.action_definition_id,
            "action_record_source": self.action_record_source.to_json(),
            "action_definition_source": self.action_definition_source.to_json(),
            "base_level": self.base_level,
            "eidolon_level_bonus": self.eidolon_level_bonus,
            "effective_level": self.effective_level,
            "sources": [item.to_json() for item in self.sources],
        }

    @classmethod
    def from_json(cls, value: object) -> CharacterSkillLevelResolution:
        row = _closed_mapping(
            value,
            "skill_level_resolution",
            {
                "skill_id",
                "action_id",
                "action_definition_id",
                "action_record_source",
                "action_definition_source",
                "base_level",
                "eidolon_level_bonus",
                "effective_level",
                "sources",
            },
        )
        sources = row.get("sources")
        if not isinstance(sources, (list, tuple)):
            raise TypeError("skill level resolution sources must be a JSON array")
        return cls(
            skill_id=require_text(row.get("skill_id"), "skill_id"),
            action_id=require_text(row.get("action_id"), "action_id"),
            action_definition_id=require_text(
                row.get("action_definition_id"),
                "action_definition_id",
            ),
            action_record_source=ir_source_from_json(
                row.get("action_record_source"),
                "action_record_source",
            ),
            action_definition_source=ir_source_from_json(
                row.get("action_definition_source"),
                "action_definition_source",
            ),
            base_level=require_int(row.get("base_level"), "base_level"),
            eidolon_level_bonus=require_int(
                row.get("eidolon_level_bonus"), "eidolon_level_bonus"
            ),
            effective_level=require_int(row.get("effective_level"), "effective_level"),
            sources=tuple(CharacterSkillLevelSource.from_json(item) for item in sources),
        )


@dataclass(frozen=True)
class CharacterMechanismRef:
    mechanism_ref_id: str
    mechanism_kind: MechanismKind
    character_card_id: str
    target_ref_id: str
    source_ref: BuildSourceRef
    source: IRSource

    def __post_init__(self) -> None:
        require_text(self.mechanism_ref_id, "mechanism_ref_id")
        if self.mechanism_kind not in {"trace_ability", "eidolon_ability"}:
            raise ValueError("invalid character mechanism_kind")
        require_text(self.character_card_id, "character_card_id")
        require_text(self.target_ref_id, "target_ref_id")
        if not isinstance(self.source_ref, BuildSourceRef):
            raise TypeError("source_ref must be BuildSourceRef")
        object.__setattr__(self, "source", immutable_ir_source(self.source))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "mechanism_ref_id": self.mechanism_ref_id,
            "mechanism_kind": self.mechanism_kind,
            "character_card_id": self.character_card_id,
            "target_ref_id": self.target_ref_id,
            "source_ref": self.source_ref.to_json(),
            "source": self.source.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> CharacterMechanismRef:
        row = _closed_mapping(
            value,
            "mechanism_ref",
            {
                "mechanism_ref_id",
                "mechanism_kind",
                "character_card_id",
                "target_ref_id",
                "source_ref",
                "source",
            },
        )
        return cls(
            mechanism_ref_id=require_text(row.get("mechanism_ref_id"), "mechanism_ref_id"),
            mechanism_kind=cast(MechanismKind, require_text(row.get("mechanism_kind"), "mechanism_kind")),
            character_card_id=require_text(row.get("character_card_id"), "character_card_id"),
            target_ref_id=require_text(row.get("target_ref_id"), "target_ref_id"),
            source_ref=BuildSourceRef.from_json(row.get("source_ref")),
            source=ir_source_from_json(row.get("source")),
        )


@dataclass(frozen=True)
class CharacterMechanismDiagnostic:
    diagnostic_id: str
    mechanism_kind: str
    target_ref_id: str
    reason: str
    source: IRSource | None = None

    def __post_init__(self) -> None:
        require_text(self.diagnostic_id, "diagnostic_id")
        require_text(self.mechanism_kind, "mechanism_kind")
        require_text(self.target_ref_id, "target_ref_id")
        require_text(self.reason, "reason")
        if self.source is not None:
            object.__setattr__(self, "source", immutable_ir_source(self.source))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "diagnostic_id": self.diagnostic_id,
            "mechanism_kind": self.mechanism_kind,
            "target_ref_id": self.target_ref_id,
            "reason": self.reason,
            "source": self.source.to_json() if self.source is not None else None,
        }

    @classmethod
    def from_json(cls, value: object) -> CharacterMechanismDiagnostic:
        row = _closed_mapping(
            value,
            "mechanism_diagnostic",
            {"diagnostic_id", "mechanism_kind", "target_ref_id", "reason", "source"},
        )
        source = row.get("source")
        return cls(
            diagnostic_id=require_text(row.get("diagnostic_id"), "diagnostic_id"),
            mechanism_kind=require_text(row.get("mechanism_kind"), "mechanism_kind"),
            target_ref_id=require_text(row.get("target_ref_id"), "target_ref_id"),
            reason=require_text(row.get("reason"), "reason"),
            source=ir_source_from_json(source) if source is not None else None,
        )


@dataclass(frozen=True)
class OwnedCombatantStatBinding:
    property_type: str
    binding_kind: Literal[
        "owner_linear",
        "owner_field",
        "owner_resource",
        "fixed",
        "inactive_schema_slot",
    ]
    owner_field: str
    scale: str | None
    offset: str | None
    sources: tuple[IRSource, ...]
    exact_value: str | None = None

    def __post_init__(self) -> None:
        require_text(self.property_type, "property_type")
        if self.binding_kind not in {
            "owner_linear",
            "owner_field",
            "owner_resource",
            "fixed",
            "inactive_schema_slot",
        }:
            raise ValueError("invalid owned-combatant stat binding_kind")
        if self.binding_kind in {"owner_linear", "owner_field", "owner_resource"}:
            require_text(self.owner_field, "owner_field")
        if self.binding_kind == "owner_linear":
            if self.scale is None or self.offset is None:
                raise ValueError("owner_linear stat binding requires scale and offset")
            object.__setattr__(self, "scale", canonical_decimal(self.scale, "scale"))
            object.__setattr__(self, "offset", canonical_decimal(self.offset, "offset"))
        elif self.scale is not None or self.offset is not None:
            raise ValueError("non-linear stat binding cannot carry scale or offset")
        if self.binding_kind == "fixed":
            if self.exact_value is None:
                raise ValueError("fixed stat binding requires exact_value")
            object.__setattr__(
                self,
                "exact_value",
                canonical_decimal(self.exact_value, "exact_value"),
            )
        elif self.exact_value is not None:
            raise ValueError("non-fixed stat binding cannot carry exact_value")
        if not isinstance(self.sources, (list, tuple)) or not all(
            isinstance(item, IRSource) for item in self.sources
        ):
            raise TypeError("owned-combatant stat sources must contain IRSource values")
        sources = tuple(immutable_ir_source(item) for item in self.sources)
        if self.binding_kind != "inactive_schema_slot" and not sources:
            raise ValueError("active owned-combatant stat binding requires source proof")
        object.__setattr__(
            self,
            "sources",
            tuple(sorted(sources, key=lambda item: (item.source_path, item.raw_type, item.raw_id))),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "property_type": self.property_type,
            "binding_kind": self.binding_kind,
            "owner_field": self.owner_field,
            "scale": self.scale,
            "offset": self.offset,
            "exact_value": self.exact_value,
            "sources": [source.to_json() for source in self.sources],
        }

    @classmethod
    def from_json(cls, value: object) -> OwnedCombatantStatBinding:
        row = _closed_mapping(
            value,
            "owned_combatant_stat_binding",
            {
                "property_type",
                "binding_kind",
                "owner_field",
                "scale",
                "offset",
                "exact_value",
                "sources",
            },
        )
        raw_sources = row.get("sources")
        if not isinstance(raw_sources, (list, tuple)):
            raise TypeError("owned-combatant stat sources must be a JSON array")
        scale = row.get("scale")
        offset = row.get("offset")
        exact_value = row.get("exact_value")
        return cls(
            property_type=require_text(row.get("property_type"), "property_type"),
            binding_kind=cast(
                Literal[
                    "owner_linear",
                    "owner_field",
                    "owner_resource",
                    "fixed",
                    "inactive_schema_slot",
                ],
                require_text(row.get("binding_kind"), "binding_kind"),
            ),
            owner_field=str(row.get("owner_field") or ""),
            scale=require_text(scale, "scale") if scale is not None else None,
            offset=require_text(offset, "offset") if offset is not None else None,
            sources=tuple(ir_source_from_json(item) for item in raw_sources),
            exact_value=(
                require_text(exact_value, "exact_value")
                if exact_value is not None
                else None
            ),
        )


@dataclass(frozen=True)
class OwnedCombatantActionBinding:
    skill_id: str
    action_id: str
    effective_level: int
    action_definition_id: str
    ability_binding_id: str
    action_source: IRSource
    ability_binding_source: IRSource
    action_role: Literal["required_action"] = "required_action"

    def __post_init__(self) -> None:
        require_text(self.skill_id, "skill_id")
        require_text(self.action_id, "action_id")
        require_int(self.effective_level, "effective_level")
        require_text(self.action_definition_id, "action_definition_id")
        require_text(self.ability_binding_id, "ability_binding_id")
        if self.action_role != "required_action":
            raise ValueError("owned-combatant action binding must be required_action")
        if self.effective_level <= 0:
            raise ValueError("owned-combatant action level must be positive")
        if not self.action_id.endswith(f":{self.skill_id}"):
            raise ValueError("owned-combatant action and skill identities mismatch")
        object.__setattr__(self, "action_source", immutable_ir_source(self.action_source))
        object.__setattr__(
            self,
            "ability_binding_source",
            immutable_ir_source(self.ability_binding_source),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "skill_id": self.skill_id,
            "action_id": self.action_id,
            "effective_level": self.effective_level,
            "action_definition_id": self.action_definition_id,
            "ability_binding_id": self.ability_binding_id,
            "action_source": self.action_source.to_json(),
            "ability_binding_source": self.ability_binding_source.to_json(),
            "action_role": self.action_role,
        }

    @classmethod
    def from_json(cls, value: object) -> OwnedCombatantActionBinding:
        row = _closed_mapping(
            value,
            "owned_combatant_action_binding",
            {
                "skill_id",
                "action_id",
                "effective_level",
                "action_definition_id",
                "ability_binding_id",
                "action_source",
                "ability_binding_source",
                "action_role",
            },
        )
        return cls(
            skill_id=require_text(row.get("skill_id"), "skill_id"),
            action_id=require_text(row.get("action_id"), "action_id"),
            effective_level=require_int(row.get("effective_level"), "effective_level"),
            action_definition_id=require_text(
                row.get("action_definition_id"),
                "action_definition_id",
            ),
            ability_binding_id=require_text(
                row.get("ability_binding_id"),
                "ability_binding_id",
            ),
            action_source=ir_source_from_json(row.get("action_source")),
            ability_binding_source=ir_source_from_json(
                row.get("ability_binding_source")
            ),
            action_role=cast(
                Literal["required_action"],
                require_text(row.get("action_role"), "action_role"),
            ),
        )


@dataclass(frozen=True)
class OwnedCombatantLifecycleAdmission:
    owner_relation_id: str
    birth_template_id: str
    spawn_sources: tuple[IRSource, ...]
    lifecycle_sources: tuple[IRSource, ...]
    admission_status: BattleAdmissionStatus
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        require_text(self.owner_relation_id, "owner_relation_id")
        require_text(self.birth_template_id, "birth_template_id")
        if self.admission_status not in {"admitted", "blocked"}:
            raise ValueError("invalid owned-combatant lifecycle admission status")
        for field_name in ("spawn_sources", "lifecycle_sources"):
            value = getattr(self, field_name)
            if not isinstance(value, (list, tuple)) or not all(
                isinstance(item, IRSource) for item in value
            ):
                raise TypeError(f"{field_name} must contain IRSource values")
            object.__setattr__(
                self,
                field_name,
                tuple(
                    sorted(
                        (immutable_ir_source(item) for item in value),
                        key=lambda item: (item.source_path, item.raw_type, item.raw_id),
                    )
                ),
            )
        if self.admission_status == "admitted" and (
            not self.spawn_sources or not self.lifecycle_sources or self.blocked_reason
        ):
            raise ValueError("admitted lifecycle requires source-backed spawn and lifecycle")
        if self.admission_status == "blocked" and not self.blocked_reason:
            raise ValueError("blocked lifecycle requires a reason")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "owner_relation_id": self.owner_relation_id,
            "birth_template_id": self.birth_template_id,
            "spawn_sources": [source.to_json() for source in self.spawn_sources],
            "lifecycle_sources": [source.to_json() for source in self.lifecycle_sources],
            "admission_status": self.admission_status,
            "blocked_reason": self.blocked_reason,
        }

    @classmethod
    def from_json(cls, value: object) -> OwnedCombatantLifecycleAdmission:
        row = _closed_mapping(
            value,
            "owned_combatant_lifecycle_admission",
            {
                "owner_relation_id",
                "birth_template_id",
                "spawn_sources",
                "lifecycle_sources",
                "admission_status",
                "blocked_reason",
            },
        )
        raw_spawn = row.get("spawn_sources")
        raw_lifecycle = row.get("lifecycle_sources")
        if not isinstance(raw_spawn, (list, tuple)) or not isinstance(
            raw_lifecycle,
            (list, tuple),
        ):
            raise TypeError("owned-combatant lifecycle sources must be JSON arrays")
        return cls(
            owner_relation_id=require_text(
                row.get("owner_relation_id"),
                "owner_relation_id",
            ),
            birth_template_id=require_text(
                row.get("birth_template_id"),
                "birth_template_id",
            ),
            spawn_sources=tuple(ir_source_from_json(item) for item in raw_spawn),
            lifecycle_sources=tuple(
                ir_source_from_json(item) for item in raw_lifecycle
            ),
            admission_status=cast(
                BattleAdmissionStatus,
                require_text(row.get("admission_status"), "admission_status"),
            ),
            blocked_reason=str(row.get("blocked_reason") or ""),
        )


@dataclass(frozen=True)
class OwnedCombatantBuildAssemblyResult:
    assembly_status: AssemblyStatus
    battle_admission_status: BattleAdmissionStatus
    owned_build_id: str
    parent_build_id: str
    parent_input_fingerprint: str
    owner_character_card_id: str
    owner_entity_ref: str
    servant_definition_id: str
    servant_ref: str
    owner_relation_id: str
    classified_skill_ids: tuple[str, ...]
    stat_bindings: tuple[OwnedCombatantStatBinding, ...]
    effective_skill_levels: tuple[CharacterSkillLevelResolution, ...]
    action_bindings: tuple[OwnedCombatantActionBinding, ...]
    mechanism_binding_ids: tuple[str, ...]
    lifecycle_admission: OwnedCombatantLifecycleAdmission
    blocked_reasons: tuple[str, ...] = ()
    result_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.assembly_status not in {"assembled", "blocked"}:
            raise ValueError("invalid owned-combatant assembly status")
        if self.battle_admission_status not in {"admitted", "blocked"}:
            raise ValueError("invalid owned-combatant battle admission status")
        for field_name in (
            "owned_build_id",
            "parent_build_id",
            "owner_character_card_id",
            "owner_entity_ref",
            "servant_definition_id",
            "servant_ref",
            "owner_relation_id",
        ):
            require_text(getattr(self, field_name), field_name)
        require_sha256(self.parent_input_fingerprint, "parent_input_fingerprint")
        object.__setattr__(
            self,
            "classified_skill_ids",
            tuple(sorted(_string_sequence(self.classified_skill_ids, "classified_skill_ids"))),
        )
        object.__setattr__(
            self,
            "mechanism_binding_ids",
            tuple(sorted(_string_sequence(self.mechanism_binding_ids, "mechanism_binding_ids"))),
        )
        for field_name, expected_type, identity in (
            ("stat_bindings", OwnedCombatantStatBinding, lambda item: item.property_type),
            ("effective_skill_levels", CharacterSkillLevelResolution, lambda item: item.skill_id),
            ("action_bindings", OwnedCombatantActionBinding, lambda item: item.action_id),
        ):
            values = getattr(self, field_name)
            if not isinstance(values, (list, tuple)) or not all(
                isinstance(item, expected_type) for item in values
            ):
                raise TypeError(f"{field_name} contains the wrong object type")
            ids = [identity(item) for item in values]
            if len(set(ids)) != len(ids):
                raise ValueError(f"{field_name} contains duplicate identities")
            object.__setattr__(self, field_name, tuple(sorted(values, key=identity)))
        if not isinstance(self.lifecycle_admission, OwnedCombatantLifecycleAdmission):
            raise TypeError("lifecycle_admission must be typed")
        reasons = tuple(sorted(_string_sequence(self.blocked_reasons, "blocked_reasons"))) if self.blocked_reasons else ()
        object.__setattr__(self, "blocked_reasons", reasons)
        if self.battle_admission_status == "admitted":
            if (
                self.assembly_status != "assembled"
                or reasons
                or not self.classified_skill_ids
                or not self.stat_bindings
                or not self.effective_skill_levels
                or not self.action_bindings
                or self.lifecycle_admission.admission_status != "admitted"
            ):
                raise ValueError("admitted owned-combatant result is incomplete")
        elif not reasons:
            raise ValueError("blocked owned-combatant result requires reasons")
        if any(
            action.skill_id not in self.classified_skill_ids
            for action in self.action_bindings
        ):
            raise ValueError("owned-combatant action skill was not classified")
        object.__setattr__(
            self,
            "result_fingerprint",
            canonical_json_fingerprint(self._fingerprint_payload()),
        )

    def _fingerprint_payload(self) -> dict[str, JSONValue]:
        return {
            "assembly_status": self.assembly_status,
            "battle_admission_status": self.battle_admission_status,
            "owned_build_id": self.owned_build_id,
            "parent_build_id": self.parent_build_id,
            "parent_input_fingerprint": self.parent_input_fingerprint,
            "owner_character_card_id": self.owner_character_card_id,
            "owner_entity_ref": self.owner_entity_ref,
            "servant_definition_id": self.servant_definition_id,
            "servant_ref": self.servant_ref,
            "owner_relation_id": self.owner_relation_id,
            "classified_skill_ids": list(self.classified_skill_ids),
            "stat_bindings": [item.to_json() for item in self.stat_bindings],
            "effective_skill_levels": [
                item.to_json() for item in self.effective_skill_levels
            ],
            "action_bindings": [item.to_json() for item in self.action_bindings],
            "mechanism_binding_ids": list(self.mechanism_binding_ids),
            "lifecycle_admission": self.lifecycle_admission.to_json(),
            "blocked_reasons": list(self.blocked_reasons),
        }

    def to_json(self) -> dict[str, JSONValue]:
        return {**self._fingerprint_payload(), "result_fingerprint": self.result_fingerprint}

    @classmethod
    def from_json(cls, value: object) -> OwnedCombatantBuildAssemblyResult:
        row = _closed_mapping(
            value,
            "owned_combatant_build_result",
            {
                "assembly_status",
                "battle_admission_status",
                "owned_build_id",
                "parent_build_id",
                "parent_input_fingerprint",
                "owner_character_card_id",
                "owner_entity_ref",
                "servant_definition_id",
                "servant_ref",
                "owner_relation_id",
                "classified_skill_ids",
                "stat_bindings",
                "effective_skill_levels",
                "action_bindings",
                "mechanism_binding_ids",
                "lifecycle_admission",
                "blocked_reasons",
                "result_fingerprint",
            },
        )

        def sequence(name: str) -> tuple[object, ...]:
            raw = row.get(name)
            if not isinstance(raw, (list, tuple)):
                raise TypeError(f"{name} must be a JSON array")
            return tuple(raw)

        result = cls(
            assembly_status=cast(AssemblyStatus, require_text(row.get("assembly_status"), "assembly_status")),
            battle_admission_status=cast(BattleAdmissionStatus, require_text(row.get("battle_admission_status"), "battle_admission_status")),
            owned_build_id=require_text(row.get("owned_build_id"), "owned_build_id"),
            parent_build_id=require_text(row.get("parent_build_id"), "parent_build_id"),
            parent_input_fingerprint=require_text(row.get("parent_input_fingerprint"), "parent_input_fingerprint"),
            owner_character_card_id=require_text(row.get("owner_character_card_id"), "owner_character_card_id"),
            owner_entity_ref=require_text(row.get("owner_entity_ref"), "owner_entity_ref"),
            servant_definition_id=require_text(row.get("servant_definition_id"), "servant_definition_id"),
            servant_ref=require_text(row.get("servant_ref"), "servant_ref"),
            owner_relation_id=require_text(row.get("owner_relation_id"), "owner_relation_id"),
            classified_skill_ids=tuple(require_text(item, "classified_skill_ids[]") for item in sequence("classified_skill_ids")),
            stat_bindings=tuple(OwnedCombatantStatBinding.from_json(item) for item in sequence("stat_bindings")),
            effective_skill_levels=tuple(CharacterSkillLevelResolution.from_json(item) for item in sequence("effective_skill_levels")),
            action_bindings=tuple(OwnedCombatantActionBinding.from_json(item) for item in sequence("action_bindings")),
            mechanism_binding_ids=tuple(require_text(item, "mechanism_binding_ids[]") for item in sequence("mechanism_binding_ids")),
            lifecycle_admission=OwnedCombatantLifecycleAdmission.from_json(row.get("lifecycle_admission")),
            blocked_reasons=tuple(require_text(item, "blocked_reasons[]") for item in sequence("blocked_reasons")),
        )
        encoded = row.get("result_fingerprint")
        if encoded is not None:
            require_sha256(encoded, "result_fingerprint")
            if encoded != result.result_fingerprint:
                raise ValueError("owned-combatant result fingerprint mismatch")
        return result


@dataclass(frozen=True)
class CharacterBuildAssemblyResult:
    assembly_status: AssemblyStatus
    battle_admission_status: BattleAdmissionStatus
    input_fingerprint: str
    build_id: str
    equipment_assembly_result: EquipmentAssemblyResult | None = None
    base_panel: CharacterBasePanel | None = None
    contribution_ledger: tuple[StaticStatContribution, ...] = ()
    effective_skill_levels: tuple[CharacterSkillLevelResolution, ...] = ()
    admitted_dynamic_mechanism_refs: tuple[CharacterMechanismRef, ...] = ()
    resource_bindings: tuple[CharacterResourceBinding, ...] = ()
    owned_combatant_results: tuple[OwnedCombatantBuildAssemblyResult, ...] = ()
    unadmitted_mechanism_diagnostics: tuple[CharacterMechanismDiagnostic, ...] = ()
    blocked_reasons: tuple[str, ...] = ()
    result_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.assembly_status not in {"assembled", "blocked"}:
            raise ValueError("invalid assembly_status")
        if self.battle_admission_status not in {"admitted", "blocked"}:
            raise ValueError("invalid battle_admission_status")
        require_sha256(self.input_fingerprint, "input_fingerprint")
        require_text(self.build_id, "build_id")
        if self.equipment_assembly_result is not None and not isinstance(
            self.equipment_assembly_result,
            EquipmentAssemblyResult,
        ):
            raise TypeError(
                "equipment_assembly_result must be EquipmentAssemblyResult or None"
            )
        contributions = self._typed_unique_sorted(
            self.contribution_ledger,
            StaticStatContribution,
            "contribution_ledger",
            lambda item: item.contribution_id,
            lambda item: item.sort_key,
        )
        skill_levels = self._typed_unique_sorted(
            self.effective_skill_levels,
            CharacterSkillLevelResolution,
            "effective_skill_levels",
            lambda item: item.skill_id,
            lambda item: item.action_id,
        )
        mechanisms = self._typed_unique_sorted(
            self.admitted_dynamic_mechanism_refs,
            CharacterMechanismRef,
            "admitted_dynamic_mechanism_refs",
            lambda item: item.mechanism_ref_id,
            lambda item: item.mechanism_ref_id,
        )
        resource_bindings = self._typed_unique_sorted(
            self.resource_bindings,
            CharacterResourceBinding,
            "resource_bindings",
            lambda item: item.resource_definition_id,
            lambda item: item.resource_definition_id,
        )
        owned_combatants = self._typed_unique_sorted(
            self.owned_combatant_results,
            OwnedCombatantBuildAssemblyResult,
            "owned_combatant_results",
            lambda item: item.owned_build_id,
            lambda item: item.owned_build_id,
        )
        diagnostics = self._typed_unique_sorted(
            self.unadmitted_mechanism_diagnostics,
            CharacterMechanismDiagnostic,
            "unadmitted_mechanism_diagnostics",
            lambda item: item.diagnostic_id,
            lambda item: item.diagnostic_id,
        )
        reasons = _string_sequence(self.blocked_reasons, "blocked_reasons") if self.blocked_reasons else ()
        invalid_contribution_source_kinds = sorted(
            {
                item.source_ref.definition_kind
                for item in contributions
                if item.source_ref.definition_kind
                not in {
                    "avatar_promotion_tier",
                    "avatar_profile",
                    "character_mechanism_slot",
                    "light_cone",
                    "relic_main_affix",
                    "relic_sub_affix",
                    "relic_set_threshold",
                }
            }
        )
        if invalid_contribution_source_kinds:
            raise ValueError(
                f"character contribution source kinds are not admitted: {invalid_contribution_source_kinds}"
            )
        if any(
            item.source_ref.definition_kind != "character_mechanism_slot"
            for item in mechanisms
        ):
            raise ValueError("character mechanism refs must use the character_mechanism_slot namespace")
        object.__setattr__(self, "contribution_ledger", contributions)
        object.__setattr__(self, "effective_skill_levels", skill_levels)
        object.__setattr__(self, "admitted_dynamic_mechanism_refs", mechanisms)
        object.__setattr__(self, "resource_bindings", resource_bindings)
        object.__setattr__(self, "owned_combatant_results", owned_combatants)
        object.__setattr__(self, "unadmitted_mechanism_diagnostics", diagnostics)
        object.__setattr__(self, "blocked_reasons", tuple(sorted(reasons)))
        if self.assembly_status == "blocked":
            if (
                self.base_panel is not None
                or contributions
                or skill_levels
                or mechanisms
                or resource_bindings
                or owned_combatants
            ):
                raise ValueError("blocked character assembly cannot expose formal result channels")
            if self.battle_admission_status != "blocked" or not reasons:
                raise ValueError("blocked character assembly requires blocked battle admission and reasons")
            if (
                self.equipment_assembly_result is not None
                and self.equipment_assembly_result.assembly_status != "blocked"
            ):
                raise ValueError(
                    "blocked character assembly may only retain a blocked equipment result"
                )
        else:
            if (
                not isinstance(self.base_panel, CharacterBasePanel)
                or not contributions
            ):
                raise ValueError(
                    "assembled character result requires panel and contribution ledger"
                )
            if (
                self.equipment_assembly_result is None
                or self.equipment_assembly_result.assembly_status != "assembled"
            ):
                raise ValueError(
                    "assembled character result requires an assembled equipment result"
                )
            contribution_json_by_id = {
                item.contribution_id: item.to_json() for item in contributions
            }
            if any(
                contribution_json_by_id.get(item.contribution_id) != item.to_json()
                for item in self.equipment_assembly_result.static_contributions
            ):
                raise ValueError(
                    "character contribution ledger is missing equipment contributions"
                )
            expected_panel = _panel_values_from_aggregates(
                aggregate_static_stat_contributions(contributions),
                resource_mode=self.base_panel.resource_mode,
            )
            encoded_panel = {
                "max_hp": self.base_panel.max_hp,
                "attack": self.base_panel.attack,
                "defense": self.base_panel.defense,
                "speed": self.base_panel.speed,
                "max_energy": self.base_panel.max_energy,
                "critical_chance": self.base_panel.critical_chance,
                "critical_damage": self.base_panel.critical_damage,
                "base_aggro": self.base_panel.base_aggro,
                **{
                    item.property_type: item.exact_value
                    for item in self.base_panel.additional_resources
                },
            }
            if self.base_panel.max_energy is None:
                encoded_panel.pop("max_energy")
            if encoded_panel != expected_panel:
                raise ValueError("base_panel must exactly equal deterministic contribution-ledger recomputation")
            if self.base_panel.resource_mode == "standard_energy":
                if resource_bindings:
                    raise ValueError("standard-energy build cannot carry special resource bindings")
            elif (
                len(resource_bindings) != 1
                or self.base_panel.special_resource_binding != resource_bindings[0]
            ):
                raise ValueError("special-resource panel and build binding must match")
            if any(
                item.parent_build_id != self.build_id
                or item.parent_input_fingerprint != self.input_fingerprint
                for item in owned_combatants
            ):
                raise ValueError("owned-combatant result parent identity mismatch")
            if reasons:
                raise ValueError("assembled character result cannot carry static blocked reasons")
            if diagnostics and self.battle_admission_status != "blocked":
                raise ValueError("unadmitted selected mechanisms must block battle admission")
            equipment_blocks_battle = (
                self.equipment_assembly_result.battle_admission_status == "blocked"
            )
            owned_combatant_blocks_battle = any(
                item.battle_admission_status != "admitted"
                for item in owned_combatants
            )
            if self.battle_admission_status == "blocked" and not (
                diagnostics or equipment_blocks_battle or owned_combatant_blocks_battle
            ):
                raise ValueError(
                    "blocked battle admission requires a typed character or equipment blocker"
                )
            if self.battle_admission_status == "admitted" and (
                diagnostics or equipment_blocks_battle or owned_combatant_blocks_battle
            ):
                raise ValueError(
                    "admitted battle result cannot carry unadmitted character or equipment channels"
                )
            if self.battle_admission_status == "admitted" and not skill_levels:
                raise ValueError("admitted character result requires effective skill levels")
        object.__setattr__(
            self,
            "result_fingerprint",
            canonical_json_fingerprint(self._fingerprint_payload()),
        )

    @staticmethod
    def _typed_unique_sorted(
        value: tuple[_T, ...] | list[_T],
        expected_type: type[_T],
        field_name: str,
        identity: Callable[[_T], object],
        sort_key: Callable[[_T], object],
    ) -> tuple[_T, ...]:
        if not isinstance(value, (list, tuple)):
            raise TypeError(f"{field_name} must be a list or tuple")
        result = tuple(value)
        if not all(isinstance(item, expected_type) for item in result):
            raise TypeError(f"{field_name} contains the wrong object type")
        ids = [identity(item) for item in result]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{field_name} contains duplicate identities")
        return tuple(sorted(result, key=sort_key))

    def _fingerprint_payload(self) -> dict[str, JSONValue]:
        return {
            "assembly_status": self.assembly_status,
            "battle_admission_status": self.battle_admission_status,
            "input_fingerprint": self.input_fingerprint,
            "build_id": self.build_id,
            "equipment_assembly_result": (
                self.equipment_assembly_result.to_json()
                if self.equipment_assembly_result is not None
                else None
            ),
            "base_panel": self.base_panel.to_json() if self.base_panel is not None else None,
            "contribution_ledger": [item.to_json() for item in self.contribution_ledger],
            "effective_skill_levels": [item.to_json() for item in self.effective_skill_levels],
            "admitted_dynamic_mechanism_refs": [
                item.to_json() for item in self.admitted_dynamic_mechanism_refs
            ],
            "resource_bindings": [item.to_json() for item in self.resource_bindings],
            "owned_combatant_results": [
                item.to_json() for item in self.owned_combatant_results
            ],
            "unadmitted_mechanism_diagnostics": [
                item.to_json() for item in self.unadmitted_mechanism_diagnostics
            ],
            "blocked_reasons": list(self.blocked_reasons),
        }

    def to_json(self) -> dict[str, JSONValue]:
        return {**self._fingerprint_payload(), "result_fingerprint": self.result_fingerprint}

    @classmethod
    def from_json(cls, value: object) -> CharacterBuildAssemblyResult:
        row = _closed_mapping(
            value,
            "character_assembly_result",
            {
                "assembly_status",
                "battle_admission_status",
                "input_fingerprint",
                "build_id",
                "equipment_assembly_result",
                "base_panel",
                "contribution_ledger",
                "effective_skill_levels",
                "admitted_dynamic_mechanism_refs",
                "resource_bindings",
                "owned_combatant_results",
                "unadmitted_mechanism_diagnostics",
                "blocked_reasons",
                "result_fingerprint",
            },
        )
        def sequence(name: str) -> tuple[object, ...]:
            raw = row.get(name)
            if not isinstance(raw, (list, tuple)):
                raise TypeError(f"{name} must be a JSON array")
            return tuple(raw)

        panel = row.get("base_panel")
        equipment_result = row.get("equipment_assembly_result")
        result = cls(
            assembly_status=cast(AssemblyStatus, require_text(row.get("assembly_status"), "assembly_status")),
            battle_admission_status=cast(
                BattleAdmissionStatus,
                require_text(row.get("battle_admission_status"), "battle_admission_status"),
            ),
            input_fingerprint=require_text(row.get("input_fingerprint"), "input_fingerprint"),
            build_id=require_text(row.get("build_id"), "build_id"),
            equipment_assembly_result=(
                EquipmentAssemblyResult.from_json(equipment_result)
                if equipment_result is not None
                else None
            ),
            base_panel=CharacterBasePanel.from_json(panel) if panel is not None else None,
            contribution_ledger=tuple(
                StaticStatContribution.from_json(item) for item in sequence("contribution_ledger")
            ),
            effective_skill_levels=tuple(
                CharacterSkillLevelResolution.from_json(item)
                for item in sequence("effective_skill_levels")
            ),
            admitted_dynamic_mechanism_refs=tuple(
                CharacterMechanismRef.from_json(item)
                for item in sequence("admitted_dynamic_mechanism_refs")
            ),
            resource_bindings=tuple(
                CharacterResourceBinding.from_json(item)
                for item in sequence("resource_bindings")
            ),
            owned_combatant_results=tuple(
                OwnedCombatantBuildAssemblyResult.from_json(item)
                for item in sequence("owned_combatant_results")
            ),
            unadmitted_mechanism_diagnostics=tuple(
                CharacterMechanismDiagnostic.from_json(item)
                for item in sequence("unadmitted_mechanism_diagnostics")
            ),
            blocked_reasons=tuple(
                require_text(item, "blocked_reasons[]") for item in sequence("blocked_reasons")
            ),
        )
        encoded = row.get("result_fingerprint")
        if encoded is not None:
            require_sha256(encoded, "result_fingerprint")
            if encoded != result.result_fingerprint:
                raise ValueError("character assembly result fingerprint mismatch")
        return result


def _panel_values_from_aggregates(
    aggregates: tuple[StaticStatAggregate, ...],
    *,
    resource_mode: Literal["standard_energy", "special_resource"],
) -> dict[str, str]:
    result = {
        aggregate.property_type: aggregate.final_value
        for aggregate in aggregates
    }
    required = {
        "max_hp",
        "attack",
        "defense",
        "speed",
        "critical_chance",
        "critical_damage",
        "base_aggro",
    }
    if resource_mode == "standard_energy":
        required.add("max_energy")
    elif "max_energy" in result:
        raise ValueError("special-resource contribution ledger cannot contain max_energy")
    missing = sorted(required.difference(result))
    if missing:
        raise ValueError(f"contribution ledger is missing base panel properties: {missing}")
    return result
