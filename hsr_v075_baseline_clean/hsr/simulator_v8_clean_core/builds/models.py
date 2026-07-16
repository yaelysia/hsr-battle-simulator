from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Literal, TypeVar, cast

from ..build_types import (
    BuildSourceRef,
    StaticStatContribution,
    canonical_decimal,
    canonical_json_fingerprint,
    immutable_ir_source,
    ir_source_from_json,
    require_int,
    require_sha256,
    require_text,
)
from ..equipment.models import EquipmentAssemblyResult, EquipmentBuildInput
from ..immutable_json import thaw_json
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
class CharacterInitialConditionInput:
    hp_mode: Literal["full"]
    initial_energy: str

    def __post_init__(self) -> None:
        if self.hp_mode != "full":
            raise ValueError("S2 formal character initial hp_mode must be full")
        object.__setattr__(
            self,
            "initial_energy",
            canonical_decimal(self.initial_energy, "initial_energy"),
        )
        if self.initial_energy != "0":
            raise ValueError("S2 formal character initial energy must be explicitly zero")

    def to_json(self) -> dict[str, JSONValue]:
        return {"hp_mode": self.hp_mode, "initial_energy": self.initial_energy}

    @classmethod
    def from_json(cls, value: object) -> CharacterInitialConditionInput:
        row = _closed_mapping(value, "initial_condition", {"hp_mode", "initial_energy"})
        return cls(
            hp_mode=cast(Literal["full"], require_text(row.get("hp_mode"), "hp_mode")),
            initial_energy=require_text(row.get("initial_energy"), "initial_energy"),
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
    max_energy: str
    critical_chance: str
    critical_damage: str
    base_aggro: str
    additional_resources: tuple[CharacterPanelResource, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "max_hp",
            "attack",
            "defense",
            "speed",
            "max_energy",
            "critical_chance",
            "critical_damage",
            "base_aggro",
        ):
            object.__setattr__(
                self,
                field_name,
                canonical_decimal(getattr(self, field_name), field_name),
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
        }
        row = _closed_mapping(value, "base_panel", names)
        resources = row.get("additional_resources")
        if not isinstance(resources, (list, tuple)):
            raise TypeError("additional_resources must be a JSON array")
        scalar_names = names.difference({"additional_resources"})
        return cls(
            **{name: require_text(row.get(name), name) for name in scalar_names},
            additional_resources=tuple(CharacterPanelResource.from_json(item) for item in resources),
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
        if self.action_id != f"avatar_skill:{self.skill_id}":
            raise ValueError("skill level action_id must use the canonical avatar skill namespace")
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
class CharacterBuildAssemblyResult:
    assembly_status: AssemblyStatus
    battle_admission_status: BattleAdmissionStatus
    input_fingerprint: str
    equipment_assembly_result: EquipmentAssemblyResult | None = None
    base_panel: CharacterBasePanel | None = None
    contribution_ledger: tuple[StaticStatContribution, ...] = ()
    effective_skill_levels: tuple[CharacterSkillLevelResolution, ...] = ()
    admitted_dynamic_mechanism_refs: tuple[CharacterMechanismRef, ...] = ()
    unadmitted_mechanism_diagnostics: tuple[CharacterMechanismDiagnostic, ...] = ()
    blocked_reasons: tuple[str, ...] = ()
    result_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.assembly_status not in {"assembled", "blocked"}:
            raise ValueError("invalid assembly_status")
        if self.battle_admission_status not in {"admitted", "blocked"}:
            raise ValueError("invalid battle_admission_status")
        require_sha256(self.input_fingerprint, "input_fingerprint")
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
        object.__setattr__(self, "unadmitted_mechanism_diagnostics", diagnostics)
        object.__setattr__(self, "blocked_reasons", tuple(sorted(reasons)))
        if self.assembly_status == "blocked":
            if self.base_panel is not None or contributions or skill_levels or mechanisms:
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
            expected_panel = _panel_values_from_contributions(contributions)
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
            if encoded_panel != expected_panel:
                raise ValueError("base_panel must exactly equal deterministic contribution-ledger recomputation")
            if reasons:
                raise ValueError("assembled character result cannot carry static blocked reasons")
            if diagnostics and self.battle_admission_status != "blocked":
                raise ValueError("unadmitted selected mechanisms must block battle admission")
            equipment_blocks_battle = (
                self.equipment_assembly_result.battle_admission_status == "blocked"
            )
            if self.battle_admission_status == "blocked" and not (
                diagnostics or equipment_blocks_battle
            ):
                raise ValueError(
                    "blocked battle admission requires a typed character or equipment blocker"
                )
            if self.battle_admission_status == "admitted" and (
                diagnostics or equipment_blocks_battle
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
                "equipment_assembly_result",
                "base_panel",
                "contribution_ledger",
                "effective_skill_levels",
                "admitted_dynamic_mechanism_refs",
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


def _panel_values_from_contributions(
    contributions: tuple[StaticStatContribution, ...],
) -> dict[str, str]:
    by_pool: dict[str, dict[str, Decimal]] = {
        "base": {},
        "percentage": {},
        "flat": {},
        "resource": {},
    }
    for contribution in contributions:
        pool = by_pool[contribution.contribution_pool]
        pool[contribution.property_type] = pool.get(contribution.property_type, Decimal(0)) + Decimal(
            contribution.exact_value
        )
    result: dict[str, str] = {}
    properties = set().union(*(pool.keys() for pool in by_pool.values()))
    for property_type in sorted(properties):
        base = by_pool["base"].get(property_type, Decimal(0))
        percentage = by_pool["percentage"].get(property_type, Decimal(0))
        flat = by_pool["flat"].get(property_type, Decimal(0))
        resource = by_pool["resource"].get(property_type, Decimal(0))
        if property_type in {"max_hp", "attack", "defense", "speed", "max_energy"}:
            if resource:
                raise ValueError(f"base panel property {property_type} cannot use resource pool")
            value = base * (Decimal(1) + percentage) + flat
        else:
            if base or percentage or flat:
                raise ValueError(f"resource property {property_type} cannot use base stat pools")
            value = resource
        result[property_type] = canonical_decimal(str(value), property_type)
    required = {
        "max_hp",
        "attack",
        "defense",
        "speed",
        "max_energy",
        "critical_chance",
        "critical_damage",
        "base_aggro",
    }
    missing = sorted(required.difference(result))
    if missing:
        raise ValueError(f"contribution ledger is missing base panel properties: {missing}")
    return result
