from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from hashlib import sha256
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, cast

from ..equipment.models import (
    CharacterEquipmentEligibilityIR,
    EquipmentAbilityParameterReadIR,
    EquipmentMechanismRefIR,
    LightConeDefinitionIR,
    RelicDomainDefinitionIR,
    RelicMainAffixDefinitionIR,
    RelicMainAffixGroupDefinitionIR,
    RelicSetDefinitionIR,
    RelicSetThresholdIR,
    RelicSlotDefinitionIR,
    RelicSubAffixDefinitionIR,
    RelicSubAffixGroupDefinitionIR,
    RelicTemplateDefinitionIR,
)
from ..immutable_json import freeze_json, thaw_json
from ..ir_types import CoverageStatus, IRSource, JSONValue
from .expression_ir import DynamicValueOperationIR, is_exact_numeric_expression

if TYPE_CHECKING:
    from .action_target_contract import ActionTargetContractCatalogIR
    from .task_graph import TaskGraphCatalogIR


def _ir_json_value(value: Any) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _ir_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_ir_json_value(item) for item in value]
    to_json = getattr(value, "to_json", None)
    if callable(to_json):
        return _ir_json_value(to_json())
    raise TypeError(f"unsupported IR JSON value: {type(value).__name__}")


def _immutable_character_ability_source(source: IRSource) -> IRSource:
    if type(source) is not IRSource:
        raise TypeError("character ability source must be an IRSource")
    for field_name, value in (
        ("source_path", source.source_path),
        ("raw_type", source.raw_type),
        ("raw_id", source.raw_id),
    ):
        if not isinstance(value, str) or not value:
            raise ValueError(f"character ability source {field_name} is required")
    if not isinstance(source.evidence, Mapping):
        raise TypeError("character ability source evidence must be an object")
    return IRSource(
        source_path=source.source_path,
        raw_type=source.raw_type,
        raw_id=source.raw_id,
        evidence=cast(dict[str, JSONValue], freeze_json(dict(source.evidence))),
    )


def _character_ability_source_json(source: IRSource) -> dict[str, JSONValue]:
    return {
        "source_path": source.source_path,
        "raw_type": source.raw_type,
        "raw_id": source.raw_id,
        "evidence": cast(dict[str, JSONValue], thaw_json(source.evidence)),
    }


def character_ability_stable_id(prefix: str, *parts: object) -> str:
    payload = json.dumps(
        [str(part) for part in parts],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}:{sha256(payload).hexdigest()}"


def character_ability_scope_record_id(
    occurrence_kind: str,
    source_path: str,
    json_path: str,
    family: str,
) -> str:
    parts = (occurrence_kind, source_path, json_path, family)
    if any(not isinstance(part, str) or not part for part in parts):
        raise ValueError("character ability scope identity parts are required")
    identity = "\0".join(parts).encode("utf-8")
    return f"character_ability_scope:{sha256(identity).hexdigest()[:24]}"


def character_ability_definition_package_owner(
    source_path: str,
) -> CharacterAbilityDefinitionPackageOwner:
    if not isinstance(source_path, str) or not source_path.startswith(
        "Config/ConfigAbility/"
    ):
        raise ValueError("ability definition source is outside ConfigAbility")
    if source_path.startswith("Config/ConfigAbility/Avatar/Camera/"):
        return "character_presentation_ability"
    if source_path.startswith("Config/ConfigAbility/Avatar/"):
        return "character_ability"
    if source_path.startswith("Config/ConfigAbility/Activity/"):
        return "shared_activity_ability"
    return "shared_ability_package"


CharacterAbilityScope = Literal[
    "gameplay",
    "build_resolution",
    "battle_data_projection",
    "input_projection",
    "environment_input",
    "non_gameplay",
    "decode_required",
]
CharacterAbilitySemanticKind = Literal[
    "combat_runtime",
    "combat_condition",
    "combat_control_flow",
    "simulation_sequence",
    "contextual_data",
    "combat_event",
    "build_resolution",
    "battle_data_projection",
    "input_control_projection",
    "environment_input",
    "presentation_only",
    "client_only_excluded",
    "ai_excluded",
    "telemetry_excluded",
    "combat_decode_required",
]
CharacterAbilityOccurrenceKind = Literal[
    "typed_node",
    "event",
    "structural_entry",
]
CharacterAbilityAdmissionStatus = Literal[
    "gameplay_candidate",
    "build_only",
    "projection_only",
    "retired",
    "blocked",
]
CharacterAbilityProjectionScope = Literal[
    "build_resolution",
    "battle_data_projection",
    "input_projection",
    "environment_input",
]
CharacterAbilityMaterializationRole = Literal["selected", "ancestor_context"]
CharacterAbilityProjectionKind = Literal[
    "build_selector",
    "special_resource_state_fragment",
    "target_persistence",
    "environment_dependency",
    "unit_topology",
    "input_action_contract",
]
CharacterAbilityDefinitionKind = Literal[
    "character_main",
    "character_shared",
    "presentation",
]
CharacterActionSourceKind = Literal[
    "basic",
    "skill",
    "ultimate",
    "passive",
    "maze",
]
CharacterAbilityBindingKind = Literal[
    "entry",
    "phase",
    "passive",
    "standalone",
    "presentation",
]
CharacterAbilityBindingGapKind = Literal[
    "source_gap_blocked",
    "missing_entry_blocked",
    "missing_phase_blocked",
    "missing_action_source_blocked",
    "duplicate_action_source_blocked",
    "ambiguous_binding_blocked",
    "cross_character_blocked",
    "cross_kind_blocked",
    "lowering_gap",
]
CharacterBuildSelectionKind = Literal["trace", "eidolon"]
CharacterBuildSelectorKind = Literal["skill_point", "rank"]
CharacterBuildSelectorLocationKind = Literal[
    "ability_definition",
    "source_root",
]
CharacterBuildSelectorGapKind = Literal[
    "selection_missing",
    "selection_ambiguous",
    "cross_character",
    "source_graph_missing",
    "source_closure_mismatch",
    "ability_definition_ambiguous",
]
CharacterBuildDynamicRefKind = Literal[
    "none",
    "direct_ability",
]
CharacterBuildProjectionKind = Literal[
    "static_contribution",
    "resource_contribution",
    "skill_level_change",
    "dynamic_graph_ref",
    "source_gap",
]
CharacterSkillLevelChangeKind = Literal["base", "bonus", "none"]
CharacterBuildRuntimeAdmissionStatus = Literal["not_applicable", "blocked"]
CharacterSourceResolutionOutcome = Literal[
    "decoded_to_package",
    "source_gap_blocked",
    "non_gameplay",
]
CharacterDecodedSourceKind = Literal[
    "dynamic_value_definition",
    "dynamic_value_write",
    "action_queue_precheck",
    "target_alias",
]
CharacterSourceResolutionSubjectKind = Literal[
    "source_graph_gap",
    "ability_task_reference",
]
CharacterDecodedPackageOwner = Literal[
    "character_dynamic_values",
    "character_action_queue",
    "character_target_expression",
]
CharacterAbilityDefinitionPackageOwner = Literal[
    "character_presentation_ability",
    "character_ability",
    "shared_activity_ability",
    "shared_ability_package",
]
CharacterEquivalentRawType = Literal[
    "RPG.GameCore.DefineDynamicValue",
    "RPG.GameCore.SetDynamicValue",
    "RPG.GameCore.TargetAlias",
]


_CHARACTER_ABILITY_ADMISSION_BY_SCOPE: dict[
    CharacterAbilityScope,
    CharacterAbilityAdmissionStatus,
] = {
    "gameplay": "gameplay_candidate",
    "build_resolution": "build_only",
    "battle_data_projection": "projection_only",
    "input_projection": "projection_only",
    "environment_input": "projection_only",
    "non_gameplay": "retired",
    "decode_required": "blocked",
}

_CHARACTER_ABILITY_COVERAGE_BY_SCOPE: dict[
    CharacterAbilityScope,
    CoverageStatus,
] = {
    "gameplay": "discovered_only",
    "build_resolution": "lowered",
    "battle_data_projection": "lowered",
    "input_projection": "lowered",
    "environment_input": "lowered",
    "non_gameplay": "audit_only",
    "decode_required": "blocked",
}

_CHARACTER_ABILITY_SCOPES = frozenset(_CHARACTER_ABILITY_ADMISSION_BY_SCOPE)
_CHARACTER_ABILITY_SEMANTIC_KINDS = frozenset(
    {
        "combat_runtime",
        "combat_condition",
        "combat_control_flow",
        "simulation_sequence",
        "contextual_data",
        "combat_event",
        "build_resolution",
        "battle_data_projection",
        "input_control_projection",
        "environment_input",
        "presentation_only",
        "client_only_excluded",
        "ai_excluded",
        "telemetry_excluded",
        "combat_decode_required",
    }
)
_CHARACTER_ABILITY_OCCURRENCE_KINDS = frozenset(
    {"typed_node", "event", "structural_entry"}
)
_CHARACTER_ABILITY_ADMISSION_STATUSES = frozenset(
    _CHARACTER_ABILITY_ADMISSION_BY_SCOPE.values()
)
_CHARACTER_ABILITY_MATERIALIZATION_ROLES = frozenset(
    {"selected", "ancestor_context"}
)
_CHARACTER_ABILITY_PROJECTION_KINDS = frozenset(
    {
        "build_selector",
        "special_resource_state_fragment",
        "target_persistence",
        "environment_dependency",
        "unit_topology",
        "input_action_contract",
    }
)
_CHARACTER_ABILITY_DEFINITION_KINDS = frozenset(
    {"character_main", "character_shared", "presentation"}
)
_CHARACTER_ACTION_SOURCE_KINDS = frozenset(
    {"basic", "skill", "ultimate", "passive", "maze"}
)
_CHARACTER_ABILITY_BINDING_KINDS = frozenset(
    {"entry", "phase", "passive", "standalone", "presentation"}
)
_CHARACTER_ABILITY_BINDING_GAP_KINDS = frozenset(
    {
        "source_gap_blocked",
        "missing_entry_blocked",
        "missing_phase_blocked",
        "missing_action_source_blocked",
        "duplicate_action_source_blocked",
        "ambiguous_binding_blocked",
        "cross_character_blocked",
        "cross_kind_blocked",
        "lowering_gap",
    }
)
_CHARACTER_SOURCE_RESOLUTION_OUTCOMES = frozenset(
    {"decoded_to_package", "source_gap_blocked", "non_gameplay"}
)
_CHARACTER_DECODED_SOURCE_KINDS = frozenset(
    {
        "dynamic_value_definition",
        "dynamic_value_write",
        "action_queue_precheck",
        "target_alias",
    }
)
_CHARACTER_SOURCE_RESOLUTION_SUBJECT_KINDS = frozenset(
    {"source_graph_gap", "ability_task_reference"}
)
_CHARACTER_DECODED_PACKAGE_OWNERS = frozenset(
    {
        "character_dynamic_values",
        "character_action_queue",
        "character_target_expression",
    }
)
_CHARACTER_ABILITY_DEFINITION_PACKAGE_OWNERS = frozenset(
    {
        "character_presentation_ability",
        "character_ability",
        "shared_activity_ability",
        "shared_ability_package",
    }
)
_CHARACTER_EQUIVALENT_RAW_TYPES = frozenset(
    {
        "RPG.GameCore.DefineDynamicValue",
        "RPG.GameCore.SetDynamicValue",
        "RPG.GameCore.TargetAlias",
    }
)
_CHARACTER_DECODE_FAMILY_CONTRACTS: dict[
    str,
    tuple[str, str, frozenset[str]],
] = {
    "LAJIKDENEOO": (
        "character_dynamic_values",
        "RPG.GameCore.SetDynamicValue",
        frozenset({"target_alias", "dynamic_key", "value_expression"}),
    ),
    "NKLOMENKLHK": (
        "character_dynamic_values",
        "RPG.GameCore.DefineDynamicValue",
        frozenset({"target_alias", "dynamic_key"}),
    ),
    "IKDAKCBKFAB": (
        "character_action_queue",
        "",
        frozenset(),
    ),
    "TargetAlias": (
        "character_target_expression",
        "RPG.GameCore.TargetAlias",
        frozenset({"alias"}),
    ),
}


def _semantic_scope(value: str) -> str:
    if value in {
        "combat_runtime",
        "combat_condition",
        "combat_control_flow",
        "simulation_sequence",
        "contextual_data",
        "combat_event",
    }:
        return "gameplay"
    if value in {
        "presentation_only",
        "client_only_excluded",
        "ai_excluded",
        "telemetry_excluded",
    }:
        return "non_gameplay"
    if value == "input_control_projection":
        return "input_projection"
    if value == "combat_decode_required":
        return "decode_required"
    return value


def _require_string_enum(value: object, allowed: frozenset[str], name: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"invalid {name}: {value!r}")
    return value


def _require_unique_strings(values: object, name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple) or any(
        not isinstance(value, str) or not value for value in values
    ):
        raise TypeError(f"{name} must be a tuple of non-empty strings")
    if len(values) != len(set(values)):
        raise ValueError(f"{name} contains duplicates")
    return tuple(sorted(values))


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_source_numeric_expression(value: object, field_name: str) -> None:
    if not isinstance(value, Mapping) or set(value) not in (
        {"IsDynamic", "FixedValue"},
        {"IsDynamic", "PostfixExpr"},
    ):
        raise ValueError(f"invalid {field_name} source expression shape")
    dynamic = value.get("IsDynamic")
    if not isinstance(dynamic, bool):
        raise TypeError(f"{field_name}.IsDynamic must be boolean")
    if dynamic:
        postfix = value.get("PostfixExpr")
        if not isinstance(postfix, Mapping) or set(postfix) != {
            "OpCodes",
            "FixedValues",
            "DynamicHashes",
        }:
            raise ValueError(f"invalid {field_name}.PostfixExpr shape")
        if not isinstance(postfix.get("OpCodes"), str):
            raise TypeError(f"{field_name}.PostfixExpr.OpCodes must be a string")
        fixed_values = postfix.get("FixedValues")
        dynamic_hashes = postfix.get("DynamicHashes")
        if not isinstance(fixed_values, (list, tuple)) or any(
            not isinstance(item, Mapping)
            or set(item) != {"Value"}
            or not _is_number(item.get("Value"))
            for item in fixed_values
        ):
            raise ValueError(f"invalid {field_name}.PostfixExpr.FixedValues")
        if not isinstance(dynamic_hashes, (list, tuple)) or any(
            not isinstance(item, int) or isinstance(item, bool)
            for item in dynamic_hashes
        ):
            raise ValueError(f"invalid {field_name}.PostfixExpr.DynamicHashes")
    else:
        fixed = value.get("FixedValue")
        if (
            not isinstance(fixed, Mapping)
            or set(fixed) != {"Value"}
            or not _is_number(fixed.get("Value"))
        ):
            raise ValueError(f"invalid {field_name}.FixedValue")


def _validate_projection_payload(
    projection_kind: str,
    projection_scope: str,
    source_opcode: str,
    payload: Mapping[str, Any],
) -> None:
    if projection_kind == "build_selector":
        if (
            projection_scope != "build_resolution"
            or source_opcode not in {"BySkillPointActivated", "ByRankActivated"}
            or set(payload)
            != {
                "operation",
                "selector_kind",
                "selector_key",
                "selector_hash",
                "inverse",
                "selector_json_path",
                "branch_kind",
                "branch_root_path",
                "true_subtree_path",
                "false_subtree_path",
            }
        ):
            raise ValueError("build selector projection contract mismatch")
        selector_key = payload.get("selector_key")
        selector_hash = payload.get("selector_hash")
        expected_kind = (
            "skill_point"
            if source_opcode == "BySkillPointActivated"
            else "rank"
        )
        if (
            payload.get("operation") != "build_selector"
            or payload.get("selector_kind") != expected_kind
            or not isinstance(payload.get("inverse"), bool)
            or not isinstance(payload.get("selector_json_path"), str)
            or not payload.get("selector_json_path")
            or payload.get("branch_kind")
            not in {
                "explicit_task_branches",
                "predicate_gated_object",
                "predicate_context",
            }
            or not isinstance(payload.get("branch_root_path"), str)
            or not payload.get("branch_root_path")
            or not isinstance(payload.get("true_subtree_path"), str)
            or not isinstance(payload.get("false_subtree_path"), str)
        ):
            raise ValueError("build selector projection payload is invalid")
        if source_opcode == "BySkillPointActivated":
            if (
                not isinstance(selector_key, str)
                or not selector_key
                or selector_hash is not None
            ):
                raise ValueError("skill-point selector key is invalid")
        elif (
            selector_key is not None
            or not isinstance(selector_hash, int)
            or isinstance(selector_hash, bool)
        ):
            raise ValueError("rank selector hash is invalid")
        return
    if projection_kind == "special_resource_state_fragment":
        if projection_scope != "battle_data_projection" or source_opcode not in {
            "SetEnergyBarState",
            "SetSummonerEnergyBarState",
        }:
            raise ValueError("special resource projection kind/scope/opcode mismatch")
        if set(payload) != {"operation", "resource_fields"}:
            raise ValueError("invalid special resource projection payload keys")
        expected_operation = (
            "summoner_resource_state"
            if source_opcode == "SetSummonerEnergyBarState"
            else "resource_state"
        )
        if payload.get("operation") != expected_operation:
            raise ValueError("invalid special resource projection operation")
        fields = payload.get("resource_fields")
        if not isinstance(fields, Mapping):
            raise TypeError("special resource fields must be an object")
        allowed = {
            "Active",
            "ActiveCount",
            "BarType",
            "CD",
            "CurrentCount",
            "CurrentState",
            "MaxCount",
            "TargetType",
        }
        if not fields or not set(fields).issubset(allowed):
            raise ValueError("special resource fields are empty or unknown")
        for name in ("ActiveCount", "CD", "CurrentCount", "MaxCount"):
            if name in fields:
                _validate_source_numeric_expression(fields[name], name)
        if "Active" in fields:
            active = fields["Active"]
            if not isinstance(active, str) or active not in {"True", "False"}:
                raise ValueError("invalid special resource Active value")
        if "BarType" in fields and (
            not isinstance(fields["BarType"], int)
            or isinstance(fields["BarType"], bool)
            or fields["BarType"] < 0
        ):
            raise ValueError("invalid special resource BarType")
        if "CurrentState" in fields and (
            not isinstance(fields["CurrentState"], str)
            or not fields["CurrentState"]
        ):
            raise ValueError("invalid special resource CurrentState")
        if "TargetType" in fields:
            target = fields["TargetType"]
            if (
                not isinstance(target, Mapping)
                or set(target) != {"$type", "Alias"}
                or target.get("$type") != "RPG.GameCore.TargetAlias"
                or not isinstance(target.get("Alias"), str)
                or not target.get("Alias")
            ):
                raise ValueError("invalid special resource target selector")
        return
    if projection_kind == "target_persistence":
        if (
            projection_scope != "input_projection"
            or source_opcode != "SetTeamLockTarget"
            or set(payload)
            != {
                "operation",
                "team",
                "target_selector",
                "persists_across_phases",
            }
        ):
            raise ValueError("target persistence projection contract mismatch")
        selector = payload.get("target_selector")
        if (
            payload.get("operation") != "team_lock_target"
            or not isinstance(payload.get("team"), str)
            or not payload.get("team")
            or payload.get("persists_across_phases") is not True
            or not isinstance(selector, Mapping)
            or set(selector) != {"kind", "alias"}
            or selector.get("kind") != "target_alias"
            or not isinstance(selector.get("alias"), str)
            or not selector.get("alias")
        ):
            raise ValueError("invalid target persistence projection payload")
        return
    if projection_kind == "environment_dependency":
        if projection_scope != "environment_input" or source_opcode not in {
            "ByInTurnBasedGameModeState",
            "ByIsMazeSkillAffectCurrentWave",
            "ByIsStageFirstWave",
            "SetDynamicValueByWaveStageCount",
            "SetDynamicValueByWorldLevel",
        }:
            raise ValueError("environment projection kind/scope/opcode mismatch")
        if source_opcode.startswith("By"):
            if (
                set(payload) != {"operation", "environment_key", "parameters"}
                or payload.get("operation") != "predicate_input"
                or not isinstance(payload.get("environment_key"), str)
                or not payload.get("environment_key")
                or not isinstance(payload.get("parameters"), Mapping)
                or payload.get("parameters")
            ):
                raise ValueError("invalid environment predicate projection")
        elif (
            set(payload)
            != {"operation", "environment_key", "write_to_key", "context_scope"}
            or payload.get("operation") != "dynamic_value_input"
            or not isinstance(payload.get("environment_key"), str)
            or not payload.get("environment_key")
            or not isinstance(payload.get("write_to_key"), str)
            or not payload.get("write_to_key")
            or not isinstance(payload.get("context_scope"), str)
        ):
            raise ValueError("invalid environment dynamic-value projection")
        return
    if projection_kind == "unit_topology":
        if (
            projection_scope != "battle_data_projection"
            or source_opcode != "SetExcludeInMultiCharacterFormation"
        ):
            raise ValueError("unit topology projection kind/scope/opcode mismatch")
        raise ValueError("unit topology has no admitted current-source payload shape")
    if projection_kind == "input_action_contract":
        if (
            projection_scope != "input_projection"
            or source_opcode
            not in {"SetDeathDragonSkillButtonState", "SetUseTemporaryLockTarget"}
        ):
            raise ValueError("input action projection kind/scope/opcode mismatch")
        raise ValueError("input action has no admitted current-source payload shape")
    raise ValueError(f"unknown character ability projection kind:{projection_kind}")


def _validate_projection_field_lineage(
    projection_kind: str,
    source_opcode: str,
    payload: Mapping[str, Any],
    raw_field_names: tuple[str, ...],
    ignored_client_fields: tuple[str, ...],
) -> None:
    raw_names = set(raw_field_names)
    ignored = set(ignored_client_fields)
    if projection_kind == "build_selector":
        required = (
            {"PointTriggerKey"}
            if source_opcode == "BySkillPointActivated"
            else {"TriggerKey"}
        )
        if (
            not required.issubset(raw_names)
            or not raw_names.issubset(required | {"Inverse", "TargetType"})
            or ignored
        ):
            raise ValueError("build selector raw field lineage mismatch")
        return
    if projection_kind == "special_resource_state_fragment":
        if not ignored.issubset(
            {"EnergyDotPrefabPaths", "IconPath", "PrefabPath"}
        ):
            raise ValueError("special resource projection ignores unknown client fields")
        resource_fields = payload["resource_fields"]
        if not isinstance(resource_fields, Mapping):
            raise TypeError("special resource fields must be an object")
        if raw_names != set(resource_fields) | ignored:
            raise ValueError("special resource projection raw field lineage mismatch")
        return
    if projection_kind == "target_persistence":
        if raw_names != {"TargetType", "Team"} or ignored:
            raise ValueError("target persistence raw field lineage mismatch")
        return
    if projection_kind == "environment_dependency":
        expected = (
            set()
            if source_opcode.startswith("By")
            else {"ContextScope", "WriteToKey"}
        )
        if raw_names != expected or ignored:
            raise ValueError("environment projection raw field lineage mismatch")
        return
    raise ValueError("projection kind has no admitted field lineage")


@dataclass(frozen=True)
class CharacterAbilitySourceIR:
    source_id: str
    source_kind: Literal["character_main", "character_shared"]
    avatar_id: str
    base_type: str
    content_sha256: str
    byte_size: int
    source: IRSource
    coverage_status: CoverageStatus = "lowered"
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        _require_string_enum(
            self.source_kind,
            frozenset({"character_main", "character_shared"}),
            "character ability source_kind",
        )
        if not isinstance(self.source_id, str) or not self.source_id:
            raise ValueError("character ability source identity must be non-empty")
        if (
            not isinstance(self.avatar_id, str)
            or not isinstance(self.base_type, str)
            or not self.base_type
            or not isinstance(self.blocked_reason, str)
        ):
            raise ValueError("character ability source metadata is invalid")
        if (
            not isinstance(self.content_sha256, str)
            or len(self.content_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.content_sha256)
        ):
            raise ValueError("character ability source digest must be sha256")
        if (
            not isinstance(self.byte_size, int)
            or isinstance(self.byte_size, bool)
            or self.byte_size < 0
        ):
            raise ValueError("character ability source byte size must be non-negative")
        if self.source_kind == "character_main" and not self.avatar_id:
            raise ValueError("character main ability source must identify its avatar")
        if self.source_kind == "character_shared" and self.avatar_id:
            raise ValueError("character shared ability source cannot identify one avatar")
        if self.coverage_status not in {"lowered", "blocked"}:
            raise ValueError("invalid character ability source coverage")
        if self.coverage_status == "blocked" and not self.blocked_reason:
            raise ValueError("blocked character ability source must explain why")
        if self.coverage_status != "blocked" and self.blocked_reason:
            raise ValueError("non-blocked character ability source cannot carry a block")
        frozen_source = _immutable_character_ability_source(self.source)
        if frozen_source.raw_id != self.source_id:
            raise ValueError("character ability source raw identity mismatch")
        if frozen_source.raw_type != "character_ability_source":
            raise ValueError("character ability source raw type mismatch")
        object.__setattr__(self, "source", frozen_source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "avatar_id": self.avatar_id,
            "base_type": self.base_type,
            "content_sha256": self.content_sha256,
            "byte_size": self.byte_size,
            "source": _character_ability_source_json(self.source),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class CharacterAbilityScopeRecordIR:
    record_id: str
    occurrence_kind: CharacterAbilityOccurrenceKind
    family: str
    semantic_kind: CharacterAbilitySemanticKind
    nominal_scope: CharacterAbilityScope
    effective_scope: CharacterAbilityScope
    admission_status: CharacterAbilityAdmissionStatus
    source: IRSource
    materialization_role: CharacterAbilityMaterializationRole = "selected"
    parent_record_id: str = ""
    parent_branch_path: str = ""
    raw_fields: Mapping[str, Any] = field(default_factory=dict)
    coverage_status: CoverageStatus = "discovered_only"
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        _require_string_enum(
            self.occurrence_kind,
            _CHARACTER_ABILITY_OCCURRENCE_KINDS,
            "character ability occurrence_kind",
        )
        _require_string_enum(
            self.semantic_kind,
            _CHARACTER_ABILITY_SEMANTIC_KINDS,
            "character ability semantic_kind",
        )
        _require_string_enum(
            self.nominal_scope,
            _CHARACTER_ABILITY_SCOPES,
            "character ability nominal_scope",
        )
        _require_string_enum(
            self.effective_scope,
            _CHARACTER_ABILITY_SCOPES,
            "character ability effective_scope",
        )
        _require_string_enum(
            self.admission_status,
            _CHARACTER_ABILITY_ADMISSION_STATUSES,
            "character ability admission_status",
        )
        _require_string_enum(
            self.materialization_role,
            _CHARACTER_ABILITY_MATERIALIZATION_ROLES,
            "character ability materialization_role",
        )
        if (
            not isinstance(self.record_id, str)
            or not self.record_id
            or not isinstance(self.family, str)
            or not self.family
            or not isinstance(self.blocked_reason, str)
        ):
            raise ValueError("character ability scope record identity must be non-empty")
        if not isinstance(self.parent_record_id, str) or not self.parent_record_id:
            raise ValueError("character ability scope record parent identity is required")
        if not isinstance(self.parent_branch_path, str) or not self.parent_branch_path:
            raise ValueError("character ability scope record parent path is required")
        expected_admission = _CHARACTER_ABILITY_ADMISSION_BY_SCOPE[
            self.effective_scope
        ]
        if _semantic_scope(self.semantic_kind) != self.effective_scope:
            raise ValueError("character ability semantic kind does not match effective scope")
        if self.admission_status != expected_admission:
            raise ValueError("character ability admission does not match effective scope")
        expected_coverage = _CHARACTER_ABILITY_COVERAGE_BY_SCOPE[
            self.effective_scope
        ]
        if self.coverage_status != expected_coverage:
            raise ValueError("character ability coverage does not match effective scope")
        if not isinstance(self.raw_fields, Mapping):
            raise TypeError("character ability raw fields must be an object")
        frozen_raw_fields = cast(
            Mapping[str, Any], freeze_json(dict(self.raw_fields))
        )
        if self.effective_scope == "decode_required":
            if not self.blocked_reason or not frozen_raw_fields:
                raise ValueError(
                    "decode-required character ability records must preserve raw fields"
                )
        elif self.blocked_reason or frozen_raw_fields:
            raise ValueError(
                "classified character ability records cannot carry decode-only fields"
            )
        frozen_source = _immutable_character_ability_source(self.source)
        if frozen_source.raw_id != self.record_id:
            raise ValueError("character ability scope record raw identity mismatch")
        if frozen_source.raw_type != self.family:
            raise ValueError("character ability scope record raw type mismatch")
        evidence = frozen_source.evidence
        expected_evidence = {
            "json_path",
            "parent_branch_path",
            "inherited_scope_record_id",
            "nominal_semantic_kind",
            "source_kind",
            "avatar_id",
        }
        if set(evidence) != expected_evidence:
            raise ValueError("character ability scope evidence schema is invalid")
        json_path = evidence.get("json_path")
        inherited_id = evidence.get("inherited_scope_record_id")
        nominal_semantic = evidence.get("nominal_semantic_kind")
        source_kind = evidence.get("source_kind")
        avatar_id = evidence.get("avatar_id")
        if (
            not isinstance(json_path, str)
            or not json_path
            or evidence.get("parent_branch_path") != self.parent_branch_path
            or not isinstance(inherited_id, str)
            or not isinstance(nominal_semantic, str)
            or nominal_semantic not in _CHARACTER_ABILITY_SEMANTIC_KINDS
            or _semantic_scope(nominal_semantic) != self.nominal_scope
            or not isinstance(source_kind, str)
            or source_kind not in {"character_main", "character_shared"}
            or not isinstance(avatar_id, str)
            or (source_kind == "character_main" and not avatar_id)
            or (source_kind == "character_shared" and bool(avatar_id))
        ):
            raise ValueError("character ability scope evidence is inconsistent")
        object.__setattr__(self, "raw_fields", frozen_raw_fields)
        object.__setattr__(self, "source", frozen_source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "record_id": self.record_id,
            "occurrence_kind": self.occurrence_kind,
            "family": self.family,
            "semantic_kind": self.semantic_kind,
            "nominal_scope": self.nominal_scope,
            "effective_scope": self.effective_scope,
            "admission_status": self.admission_status,
            "materialization_role": self.materialization_role,
            "parent_record_id": self.parent_record_id,
            "parent_branch_path": self.parent_branch_path,
            "raw_fields": cast(JSONValue, thaw_json(self.raw_fields)),
            "source": _character_ability_source_json(self.source),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class CharacterAbilityFamilyIR:
    family: str
    occurrence_kind: CharacterAbilityOccurrenceKind
    semantic_kind: CharacterAbilitySemanticKind
    nominal_scope: CharacterAbilityScope
    occurrence_count: int
    source_paths: tuple[str, ...]
    effective_scope_counts: Mapping[str, int]

    def __post_init__(self) -> None:
        _require_string_enum(
            self.occurrence_kind,
            _CHARACTER_ABILITY_OCCURRENCE_KINDS,
            "character ability family occurrence_kind",
        )
        _require_string_enum(
            self.semantic_kind,
            _CHARACTER_ABILITY_SEMANTIC_KINDS,
            "character ability family semantic_kind",
        )
        _require_string_enum(
            self.nominal_scope,
            _CHARACTER_ABILITY_SCOPES,
            "character ability family nominal_scope",
        )
        if _semantic_scope(self.semantic_kind) != self.nominal_scope:
            raise ValueError("character ability family semantic scope mismatch")
        if (
            not isinstance(self.family, str)
            or not self.family
            or not isinstance(self.occurrence_count, int)
            or isinstance(self.occurrence_count, bool)
            or self.occurrence_count <= 0
        ):
            raise ValueError("character ability family summary must be non-empty")
        source_paths = _require_unique_strings(
            self.source_paths,
            "character ability family source_paths",
        )
        if not source_paths:
            raise ValueError("character ability family summary must retain its sources")
        if not isinstance(self.effective_scope_counts, Mapping):
            raise TypeError("character ability family scope counts must be a mapping")
        scope_counts: dict[str, int] = {}
        for scope, count in self.effective_scope_counts.items():
            _require_string_enum(
                scope,
                _CHARACTER_ABILITY_SCOPES,
                "character ability family effective scope",
            )
            if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
                raise ValueError("character ability family scope count must be positive")
            scope_counts[scope] = count
        if sum(scope_counts.values()) != self.occurrence_count:
            raise ValueError("character ability family scope counts do not reconcile")
        object.__setattr__(self, "source_paths", tuple(source_paths))
        object.__setattr__(self, "effective_scope_counts", freeze_json(scope_counts))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "family": self.family,
            "occurrence_kind": self.occurrence_kind,
            "semantic_kind": self.semantic_kind,
            "nominal_scope": self.nominal_scope,
            "occurrence_count": self.occurrence_count,
            "source_paths": list(self.source_paths),
            "effective_scope_counts": cast(
                JSONValue, thaw_json(self.effective_scope_counts)
            ),
        }


@dataclass(frozen=True)
class CharacterAbilityProjectionIR:
    projection_id: str
    scope_record_id: str
    projection_scope: CharacterAbilityProjectionScope
    projection_kind: CharacterAbilityProjectionKind
    source_opcode: str
    payload: Mapping[str, Any]
    raw_field_names: tuple[str, ...]
    ignored_client_fields: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "lowered"
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        _require_string_enum(
            self.projection_scope,
            frozenset(
                {
                    "build_resolution",
                    "battle_data_projection",
                    "input_projection",
                    "environment_input",
                }
            ),
            "character ability projection_scope",
        )
        _require_string_enum(
            self.projection_kind,
            _CHARACTER_ABILITY_PROJECTION_KINDS,
            "character ability projection_kind",
        )
        if (
            not isinstance(self.projection_id, str)
            or not self.projection_id
            or not isinstance(self.scope_record_id, str)
            or not self.scope_record_id
            or not isinstance(self.blocked_reason, str)
        ):
            raise ValueError("character ability projection identity must be non-empty")
        if not isinstance(self.source_opcode, str) or not self.source_opcode:
            raise ValueError("character ability projection kind must be non-empty")
        raw_field_names = _require_unique_strings(
            self.raw_field_names,
            "character ability projection raw_field_names",
        )
        ignored_client_fields = _require_unique_strings(
            self.ignored_client_fields,
            "character ability projection ignored_client_fields",
        )
        if not set(ignored_client_fields).issubset(raw_field_names):
            raise ValueError("ignored client fields must be raw source fields")
        if self.coverage_status not in {"lowered", "blocked"}:
            raise ValueError("invalid character ability projection coverage")
        if self.coverage_status == "blocked" and not self.blocked_reason:
            raise ValueError("blocked character ability projection must explain why")
        if self.coverage_status != "blocked" and self.blocked_reason:
            raise ValueError("non-blocked character ability projection cannot carry a block")
        if not isinstance(self.payload, Mapping):
            raise TypeError("character ability projection payload must be an object")
        frozen_payload = cast(Mapping[str, Any], freeze_json(dict(self.payload)))
        _validate_projection_payload(
            self.projection_kind,
            self.projection_scope,
            self.source_opcode,
            frozen_payload,
        )
        _validate_projection_field_lineage(
            self.projection_kind,
            self.source_opcode,
            frozen_payload,
            raw_field_names,
            ignored_client_fields,
        )
        frozen_source = _immutable_character_ability_source(self.source)
        if frozen_source.raw_id != self.scope_record_id:
            raise ValueError("character ability projection source identity mismatch")
        if frozen_source.raw_type != self.source_opcode:
            raise ValueError("character ability projection source type mismatch")
        object.__setattr__(self, "payload", frozen_payload)
        object.__setattr__(self, "raw_field_names", raw_field_names)
        object.__setattr__(self, "ignored_client_fields", ignored_client_fields)
        object.__setattr__(self, "source", frozen_source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "projection_id": self.projection_id,
            "scope_record_id": self.scope_record_id,
            "projection_scope": self.projection_scope,
            "projection_kind": self.projection_kind,
            "source_opcode": self.source_opcode,
            "payload": cast(JSONValue, thaw_json(self.payload)),
            "raw_field_names": list(self.raw_field_names),
            "ignored_client_fields": list(self.ignored_client_fields),
            "runtime_admission": "projection_only",
            "source": _character_ability_source_json(self.source),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class CharacterAbilityExternalDependencyIR:
    dependency_id: str
    projection_kind: CharacterAbilityProjectionKind
    status: Literal["external_content_dependency", "not_proven"]
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.dependency_id, str) or not self.dependency_id:
            raise ValueError("external dependency identity must be non-empty")
        _require_string_enum(
            self.projection_kind,
            _CHARACTER_ABILITY_PROJECTION_KINDS,
            "external dependency projection_kind",
        )
        _require_string_enum(
            self.status,
            frozenset({"external_content_dependency", "not_proven"}),
            "external dependency status",
        )
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("external dependency reason must be non-empty")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "dependency_id": self.dependency_id,
            "projection_kind": self.projection_kind,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CharacterAbilityDefinitionIR:
    definition_id: str
    source_id: str
    owner_avatar_id: str
    ability_name: str
    definition_kind: CharacterAbilityDefinitionKind
    source: IRSource

    def __post_init__(self) -> None:
        for field_name in ("definition_id", "source_id", "ability_name"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"character ability definition {field_name} is required")
        if not isinstance(self.owner_avatar_id, str):
            raise TypeError("character ability definition owner must be a string")
        _require_string_enum(
            self.definition_kind,
            _CHARACTER_ABILITY_DEFINITION_KINDS,
            "character ability definition_kind",
        )
        if self.definition_kind == "character_shared":
            if self.owner_avatar_id:
                raise ValueError("shared ability definition cannot have one avatar owner")
        elif not self.owner_avatar_id:
            raise ValueError("owned ability definition requires an avatar owner")
        frozen_source = _immutable_character_ability_source(self.source)
        if frozen_source.raw_id != self.ability_name:
            raise ValueError("ability definition source identity mismatch")
        expected_raw_type = (
            "PresentationAbilityList"
            if self.definition_kind == "presentation"
            else "AbilityList"
        )
        if frozen_source.raw_type != expected_raw_type:
            raise ValueError("ability definition source type mismatch")
        evidence = frozen_source.evidence
        if set(evidence) != {
            "source_id",
            "source_kind",
            "avatar_id",
            "json_path",
            "ability_index",
            "content_sha256",
        }:
            raise ValueError("ability definition evidence schema is invalid")
        ability_index = evidence.get("ability_index")
        digest = evidence.get("content_sha256")
        if (
            evidence.get("source_id") != self.source_id
            or evidence.get("source_kind") != self.definition_kind
            or evidence.get("avatar_id") != self.owner_avatar_id
            or not isinstance(evidence.get("json_path"), str)
            or not evidence.get("json_path")
            or not isinstance(ability_index, int)
            or isinstance(ability_index, bool)
            or ability_index < 0
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("ability definition evidence is inconsistent")
        object.__setattr__(self, "source", frozen_source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "definition_id": self.definition_id,
            "source_id": self.source_id,
            "owner_avatar_id": self.owner_avatar_id,
            "ability_name": self.ability_name,
            "definition_kind": self.definition_kind,
            "source": _character_ability_source_json(self.source),
            "coverage_status": (
                "audit_only"
                if self.definition_kind == "presentation"
                else "lowered"
            ),
        }


@dataclass(frozen=True)
class CharacterActionSourceIR:
    action_source_id: str
    action_id: str
    owner_avatar_id: str
    skill_id: str
    skill_trigger_key: str
    action_kind: CharacterActionSourceKind
    levels: tuple[int, ...]
    highest_level: int
    config_source: IRSource
    skill_sources: tuple[IRSource, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "action_source_id",
            "action_id",
            "owner_avatar_id",
            "skill_id",
            "skill_trigger_key",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"character action source {field_name} is required")
        if self.action_id != f"avatar_skill:{self.skill_id}":
            raise ValueError("character action identity does not match skill identity")
        _require_string_enum(
            self.action_kind,
            _CHARACTER_ACTION_SOURCE_KINDS,
            "character action source kind",
        )
        level_values = tuple(self.levels)
        if (
            not level_values
            or any(
                not isinstance(level, int)
                or isinstance(level, bool)
                or level <= 0
                for level in level_values
            )
            or level_values != tuple(sorted(set(level_values)))
            or not isinstance(self.highest_level, int)
            or isinstance(self.highest_level, bool)
            or self.highest_level != level_values[-1]
        ):
            raise ValueError("character action levels are invalid")
        config_source = _immutable_character_ability_source(self.config_source)
        skill_source_values = tuple(self.skill_sources)
        if any(type(source) is not IRSource for source in skill_source_values):
            raise TypeError("character action skill sources must be exact IRSource values")
        skill_sources = tuple(
            sorted(
                (_immutable_character_ability_source(source) for source in skill_source_values),
                key=lambda source: (
                    cast(int, source.evidence.get("level")),
                    source.source_path,
                    cast(int, source.evidence.get("row_index")),
                ),
            )
        )
        if len(skill_sources) != len(level_values):
            raise ValueError("character action level sources do not reconcile")
        if tuple(cast(int, source.evidence.get("level")) for source in skill_sources) != level_values:
            raise ValueError("character action source levels are inconsistent")
        if config_source.raw_id != self.skill_trigger_key:
            raise ValueError("character action config source identity mismatch")
        config_evidence = config_source.evidence
        if set(config_evidence) != {
            "source_id",
            "avatar_id",
            "skill_id",
            "skill_trigger_key",
            "json_path",
            "inventory_source_path",
            "inventory_row_index",
            "selected_version",
            "ability_source_path",
            "inventory_content_sha256",
            "content_sha256",
        }:
            raise ValueError("character action config evidence schema is invalid")
        if (
            config_evidence.get("avatar_id") != self.owner_avatar_id
            or config_evidence.get("skill_id") != self.skill_id
            or config_evidence.get("skill_trigger_key") != self.skill_trigger_key
            or not isinstance(config_evidence.get("source_id"), str)
            or not config_evidence.get("source_id")
            or not isinstance(config_evidence.get("json_path"), str)
            or not config_evidence.get("json_path")
            or not isinstance(config_evidence.get("inventory_source_path"), str)
            or not config_evidence.get("inventory_source_path")
            or not isinstance(config_evidence.get("inventory_row_index"), int)
            or isinstance(config_evidence.get("inventory_row_index"), bool)
            or cast(int, config_evidence.get("inventory_row_index")) < 0
            or config_evidence.get("selected_version") not in {"base", "enhanced"}
            or not isinstance(config_evidence.get("ability_source_path"), str)
            or not config_evidence.get("ability_source_path")
            or not _is_sha256(config_evidence.get("inventory_content_sha256"))
            or not _is_sha256(config_evidence.get("content_sha256"))
        ):
            raise ValueError("character action config evidence is inconsistent")
        for source, level in zip(skill_sources, level_values, strict=True):
            evidence = source.evidence
            if set(evidence) != {
                "avatar_id",
                "skill_id",
                "row_index",
                "level",
                "skill_trigger_key",
                "content_sha256",
            }:
                raise ValueError("character action level evidence schema is invalid")
            if (
                source.raw_id != self.skill_id
                or evidence.get("avatar_id") != self.owner_avatar_id
                or evidence.get("skill_id") != self.skill_id
                or evidence.get("skill_trigger_key") != self.skill_trigger_key
                or evidence.get("level") != level
                or not isinstance(evidence.get("row_index"), int)
                or isinstance(evidence.get("row_index"), bool)
                or cast(int, evidence.get("row_index")) < 0
                or not _is_sha256(evidence.get("content_sha256"))
            ):
                raise ValueError("character action level evidence is inconsistent")
        object.__setattr__(self, "levels", level_values)
        object.__setattr__(self, "config_source", config_source)
        object.__setattr__(self, "skill_sources", skill_sources)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "action_source_id": self.action_source_id,
            "action_id": self.action_id,
            "owner_avatar_id": self.owner_avatar_id,
            "skill_id": self.skill_id,
            "skill_trigger_key": self.skill_trigger_key,
            "action_kind": self.action_kind,
            "levels": list(self.levels),
            "highest_level": self.highest_level,
            "config_source": _character_ability_source_json(self.config_source),
            "skill_sources": [
                _character_ability_source_json(source)
                for source in self.skill_sources
            ],
        }


@dataclass(frozen=True)
class CharacterNonGameplaySkillSourceIR:
    non_gameplay_skill_source_id: str
    graph_id: str
    owner_avatar_id: str
    skill_id: str
    raw_attack_type: str
    raw_skill_effect: str
    row_index: int
    content_sha256: str
    retired_reason: Literal["maze_normal_without_skill_trigger"]
    source: IRSource

    def __post_init__(self) -> None:
        for field_name in (
            "non_gameplay_skill_source_id",
            "graph_id",
            "owner_avatar_id",
            "skill_id",
            "retired_reason",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"non-gameplay skill source {field_name} is required")
        if self.raw_attack_type != "MazeNormal":
            raise ValueError("only MazeNormal skills can be retired as non-gameplay")
        if not isinstance(self.raw_skill_effect, str):
            raise TypeError("non-gameplay skill effect must retain its raw string")
        if self.retired_reason != "maze_normal_without_skill_trigger":
            raise ValueError("non-gameplay skill retired reason is invalid")
        if (
            not isinstance(self.row_index, int)
            or isinstance(self.row_index, bool)
            or self.row_index < 0
            or not _is_sha256(self.content_sha256)
        ):
            raise ValueError("non-gameplay skill row evidence is invalid")
        source = _immutable_character_ability_source(self.source)
        evidence = source.evidence
        if source.raw_type != "CharacterSkillActionRow" or source.raw_id != self.skill_id:
            raise ValueError("non-gameplay skill source identity is invalid")
        if set(evidence) != {
            "graph_id",
            "owner_avatar_id",
            "skill_id",
            "skill_trigger_key",
            "attack_type",
            "skill_effect",
            "row_index",
            "retired_reason",
            "content_sha256",
        }:
            raise ValueError("non-gameplay skill evidence schema is invalid")
        if (
            evidence.get("graph_id") != self.graph_id
            or evidence.get("owner_avatar_id") != self.owner_avatar_id
            or evidence.get("skill_id") != self.skill_id
            or evidence.get("skill_trigger_key") != ""
            or evidence.get("attack_type") != self.raw_attack_type
            or evidence.get("skill_effect") != self.raw_skill_effect
            or evidence.get("row_index") != self.row_index
            or evidence.get("retired_reason") != self.retired_reason
            or evidence.get("content_sha256") != self.content_sha256
            or self.non_gameplay_skill_source_id
            != character_ability_stable_id(
                "character_non_gameplay_skill_source",
                self.graph_id,
                self.owner_avatar_id,
                self.skill_id,
                source.source_path,
                self.row_index,
                self.raw_attack_type,
                self.raw_skill_effect,
                self.retired_reason,
            )
        ):
            raise ValueError("non-gameplay skill evidence is inconsistent")
        object.__setattr__(self, "source", source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "non_gameplay_skill_source_id": self.non_gameplay_skill_source_id,
            "graph_id": self.graph_id,
            "owner_avatar_id": self.owner_avatar_id,
            "skill_id": self.skill_id,
            "raw_attack_type": self.raw_attack_type,
            "raw_skill_effect": self.raw_skill_effect,
            "row_index": self.row_index,
            "content_sha256": self.content_sha256,
            "retired_reason": self.retired_reason,
            "source": _character_ability_source_json(self.source),
            "coverage_status": "non_gameplay_retired",
        }


@dataclass(frozen=True)
class CharacterAbilityBindingIR:
    binding_id: str
    relation_id: str
    graph_id: str
    owner_avatar_id: str
    action_source_id: str
    ability_definition_id: str
    ability_name: str
    binding_kind: CharacterAbilityBindingKind
    ordinal: int
    relation_source: IRSource

    def __post_init__(self) -> None:
        for field_name in (
            "binding_id",
            "relation_id",
            "graph_id",
            "ability_definition_id",
            "ability_name",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"character ability binding {field_name} is required")
        if not isinstance(self.owner_avatar_id, str) or not isinstance(
            self.action_source_id, str
        ):
            raise TypeError("character ability binding owner/action refs must be strings")
        _require_string_enum(
            self.binding_kind,
            _CHARACTER_ABILITY_BINDING_KINDS,
            "character ability binding kind",
        )
        if self.binding_kind in {"entry", "phase", "passive"} and not self.action_source_id:
            raise ValueError("action entry, phase, and passive bindings require an action source")
        if self.binding_kind == "standalone" and self.action_source_id:
            raise ValueError("standalone ability cannot be action-bound")
        if self.binding_kind != "standalone" and not self.owner_avatar_id:
            raise ValueError("non-standalone ability bindings require an avatar owner")
        if (
            not isinstance(self.ordinal, int)
            or isinstance(self.ordinal, bool)
            or self.ordinal < 0
        ):
            raise ValueError("character ability binding ordinal is invalid")
        relation_source = _immutable_character_ability_source(self.relation_source)
        if relation_source.raw_id != self.ability_name:
            raise ValueError("character ability binding source identity mismatch")
        evidence = relation_source.evidence
        if set(evidence) != {
            "relation_id",
            "graph_id",
            "owner_avatar_id",
            "action_source_id",
            "skill_id",
            "binding_kind",
            "relation_ordinal",
            "json_path",
            "content_sha256",
        }:
            raise ValueError("character ability binding evidence schema is invalid")
        if (
            evidence.get("relation_id") != self.relation_id
            or evidence.get("graph_id") != self.graph_id
            or evidence.get("owner_avatar_id") != self.owner_avatar_id
            or evidence.get("action_source_id") != self.action_source_id
            or evidence.get("binding_kind") != self.binding_kind
            or evidence.get("relation_ordinal") != self.ordinal
            or not isinstance(evidence.get("skill_id"), str)
            or not isinstance(evidence.get("json_path"), str)
            or not evidence.get("json_path")
            or not _is_sha256(evidence.get("content_sha256"))
        ):
            raise ValueError("character ability binding evidence is inconsistent")
        object.__setattr__(self, "relation_source", relation_source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "binding_id": self.binding_id,
            "relation_id": self.relation_id,
            "graph_id": self.graph_id,
            "owner_avatar_id": self.owner_avatar_id,
            "action_source_id": self.action_source_id,
            "ability_definition_id": self.ability_definition_id,
            "ability_name": self.ability_name,
            "binding_kind": self.binding_kind,
            "ordinal": self.ordinal,
            "relation_source": _character_ability_source_json(
                self.relation_source
            ),
            "coverage_status": (
                "audit_only"
                if self.binding_kind == "presentation"
                else "lowered"
            ),
        }


@dataclass(frozen=True)
class CharacterAbilityBindingGapIR:
    gap_id: str
    relation_id: str
    graph_id: str
    owner_avatar_id: str
    action_source_id: str
    requested_ability_name: str
    expected_binding_kind: CharacterAbilityBindingKind
    ordinal: int
    gap_kind: CharacterAbilityBindingGapKind
    candidate_definition_ids: tuple[str, ...]
    candidate_action_source_ids: tuple[str, ...]
    searched_source_ids: tuple[str, ...]
    source: IRSource
    blocked_reason: str

    def __post_init__(self) -> None:
        for field_name in ("gap_id", "relation_id", "graph_id", "blocked_reason"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"character ability gap {field_name} is required")
        if (
            not isinstance(self.owner_avatar_id, str)
            or not isinstance(self.action_source_id, str)
            or not isinstance(self.requested_ability_name, str)
        ):
            raise TypeError("character ability gap references must be strings")
        _require_string_enum(
            self.expected_binding_kind,
            _CHARACTER_ABILITY_BINDING_KINDS,
            "character ability gap expected kind",
        )
        _require_string_enum(
            self.gap_kind,
            _CHARACTER_ABILITY_BINDING_GAP_KINDS,
            "character ability gap kind",
        )
        if (
            not isinstance(self.ordinal, int)
            or isinstance(self.ordinal, bool)
            or self.ordinal < 0
        ):
            raise ValueError("character ability gap ordinal is invalid")
        if not self.owner_avatar_id and self.expected_binding_kind != "standalone":
            raise ValueError("only shared standalone gaps may omit an avatar owner")
        candidate_ids = _require_unique_strings(
            self.candidate_definition_ids,
            "character ability gap candidates",
        )
        searched_ids = _require_unique_strings(
            self.searched_source_ids,
            "character ability gap searched sources",
        )
        action_candidate_ids = _require_unique_strings(
            self.candidate_action_source_ids,
            "character ability gap action candidates",
        )
        if self.gap_kind == "source_gap_blocked" and (
            not self.requested_ability_name
            or candidate_ids
            or not searched_ids
        ):
            raise ValueError("source gaps require an exhausted candidate search")
        if self.gap_kind in {
            "ambiguous_binding_blocked",
            "cross_character_blocked",
            "cross_kind_blocked",
            "duplicate_action_source_blocked",
        } and not (candidate_ids or action_candidate_ids):
            raise ValueError("candidate conflict gaps must retain candidates")
        if self.gap_kind == "missing_phase_blocked" and self.requested_ability_name:
            raise ValueError("missing phase-list gaps cannot invent an ability name")
        source = _immutable_character_ability_source(self.source)
        evidence = source.evidence
        if set(evidence) != {
            "relation_id",
            "graph_id",
            "owner_avatar_id",
            "action_source_id",
            "skill_id",
            "binding_kind",
            "relation_ordinal",
            "json_path",
            "content_sha256",
        }:
            raise ValueError("character ability gap evidence schema is invalid")
        if (
            evidence.get("relation_id") != self.relation_id
            or evidence.get("graph_id") != self.graph_id
            or evidence.get("owner_avatar_id") != self.owner_avatar_id
            or evidence.get("action_source_id") != self.action_source_id
            or evidence.get("binding_kind") != self.expected_binding_kind
            or evidence.get("relation_ordinal") != self.ordinal
            or not isinstance(evidence.get("skill_id"), str)
            or not isinstance(evidence.get("json_path"), str)
            or not evidence.get("json_path")
            or not _is_sha256(evidence.get("content_sha256"))
        ):
            raise ValueError("character ability gap evidence is inconsistent")
        object.__setattr__(self, "candidate_definition_ids", candidate_ids)
        object.__setattr__(self, "candidate_action_source_ids", action_candidate_ids)
        object.__setattr__(self, "searched_source_ids", searched_ids)
        object.__setattr__(self, "source", source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "gap_id": self.gap_id,
            "relation_id": self.relation_id,
            "graph_id": self.graph_id,
            "owner_avatar_id": self.owner_avatar_id,
            "action_source_id": self.action_source_id,
            "requested_ability_name": self.requested_ability_name,
            "expected_binding_kind": self.expected_binding_kind,
            "ordinal": self.ordinal,
            "gap_kind": self.gap_kind,
            "candidate_definition_ids": list(self.candidate_definition_ids),
            "candidate_action_source_ids": list(self.candidate_action_source_ids),
            "searched_source_ids": list(self.searched_source_ids),
            "source": _character_ability_source_json(self.source),
            "coverage_status": "blocked",
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class CharacterAbilitySourceGraphIR:
    graph_id: str
    source_id: str
    source_kind: Literal["character_main", "character_shared"]
    owner_avatar_id: str
    definition_ids: tuple[str, ...]
    action_source_ids: tuple[str, ...]
    non_gameplay_skill_source_ids: tuple[str, ...]
    binding_ids: tuple[str, ...]
    gap_ids: tuple[str, ...]
    selected_skill_ids: tuple[str, ...]
    inventory_source: IRSource | None
    shared_graph_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("graph_id", "source_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"character ability graph {field_name} is required")
        _require_string_enum(
            self.source_kind,
            frozenset({"character_main", "character_shared"}),
            "character ability graph source kind",
        )
        if not isinstance(self.owner_avatar_id, str):
            raise TypeError("character ability graph owner must be a string")
        if self.source_kind == "character_shared":
            if self.owner_avatar_id or self.shared_graph_ids:
                raise ValueError("shared ability graph cannot have an owner or shared refs")
        elif not self.owner_avatar_id:
            raise ValueError("character ability graph owner is required")
        for field_name in (
            "definition_ids",
            "action_source_ids",
            "non_gameplay_skill_source_ids",
            "binding_ids",
            "gap_ids",
            "selected_skill_ids",
            "shared_graph_ids",
        ):
            values = _require_unique_strings(
                getattr(self, field_name),
                f"character ability graph {field_name}",
            )
            if self.graph_id in values:
                raise ValueError("character ability graph cannot reference itself")
            object.__setattr__(self, field_name, values)
        if not self.definition_ids:
            raise ValueError("character ability graph must retain its definitions")
        if self.source_kind == "character_shared":
            if (
                self.selected_skill_ids
                or self.non_gameplay_skill_source_ids
                or self.inventory_source is not None
            ):
                raise ValueError("shared ability graph cannot carry inventory selection")
        else:
            if type(self.inventory_source) is not IRSource:
                raise TypeError("owned ability graph requires an exact inventory source")
            inventory_source = _immutable_character_ability_source(self.inventory_source)
            if inventory_source.raw_id != self.owner_avatar_id:
                raise ValueError("owned ability graph inventory identity is inconsistent")
            evidence = inventory_source.evidence
            evidence_skill_ids = evidence.get("skill_ids")
            if set(evidence) != {
                "source_id",
                "avatar_id",
                "row_index",
                "selected_version",
                "character_config_path",
                "ability_source_path",
                "skill_ids",
                "content_sha256",
            }:
                raise ValueError("owned ability graph inventory evidence schema is invalid")
            if (
                evidence.get("source_id") != self.source_id
                or evidence.get("avatar_id") != self.owner_avatar_id
                or not isinstance(evidence_skill_ids, (list, tuple))
                or tuple(evidence_skill_ids) != self.selected_skill_ids
                or not isinstance(evidence.get("row_index"), int)
                or isinstance(evidence.get("row_index"), bool)
                or cast(int, evidence.get("row_index")) < 0
                or evidence.get("selected_version") not in {"base", "enhanced"}
                or not isinstance(evidence.get("character_config_path"), str)
                or not evidence.get("character_config_path")
                or not isinstance(evidence.get("ability_source_path"), str)
                or not evidence.get("ability_source_path")
                or not _is_sha256(evidence.get("content_sha256"))
            ):
                raise ValueError("owned ability graph inventory evidence is inconsistent")
            object.__setattr__(self, "inventory_source", inventory_source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "graph_id": self.graph_id,
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "owner_avatar_id": self.owner_avatar_id,
            "definition_ids": list(self.definition_ids),
            "action_source_ids": list(self.action_source_ids),
            "non_gameplay_skill_source_ids": list(
                self.non_gameplay_skill_source_ids
            ),
            "binding_ids": list(self.binding_ids),
            "gap_ids": list(self.gap_ids),
            "selected_skill_ids": list(self.selected_skill_ids),
            "inventory_source": (
                _character_ability_source_json(self.inventory_source)
                if self.inventory_source is not None
                else None
            ),
            "shared_graph_ids": list(self.shared_graph_ids),
        }


@dataclass(frozen=True)
class CharacterAbilityGraphRefIR:
    graph_ref_id: str
    character_data_card_id: str
    owner_avatar_id: str
    graph_id: str
    reference_kind: Literal["owned", "shared"]
    source: IRSource

    def __post_init__(self) -> None:
        for field_name in (
            "graph_ref_id",
            "character_data_card_id",
            "owner_avatar_id",
            "graph_id",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"character ability graph ref {field_name} is required"
                )
        _require_string_enum(
            self.reference_kind,
            frozenset({"owned", "shared"}),
            "character ability graph reference kind",
        )
        source = _immutable_character_ability_source(self.source)
        if source.raw_id != self.character_data_card_id:
            raise ValueError("character ability card source identity mismatch")
        if self.graph_ref_id != (
            f"character_ability_graph_ref:{self.character_data_card_id}:"
            f"{self.reference_kind}:{self.graph_id}"
        ):
            raise ValueError("character ability graph ref identity is inconsistent")
        evidence = source.evidence
        if set(evidence) != {
            "graph_id",
            "reference_kind",
            "source_graph_catalog_id",
            "source_id",
            "avatar_id",
            "row_index",
            "selected_version",
            "character_config_path",
            "content_sha256",
        }:
            raise ValueError("character ability graph ref evidence schema is invalid")
        if (
            evidence.get("graph_id") != self.graph_id
            or evidence.get("reference_kind") != self.reference_kind
            or evidence.get("avatar_id") != self.owner_avatar_id
            or not isinstance(evidence.get("source_graph_catalog_id"), str)
            or not evidence.get("source_graph_catalog_id")
            or not isinstance(evidence.get("source_id"), str)
            or not evidence.get("source_id")
            or not isinstance(evidence.get("row_index"), int)
            or isinstance(evidence.get("row_index"), bool)
            or cast(int, evidence.get("row_index")) < 0
            or evidence.get("selected_version") not in {"base", "enhanced"}
            or not isinstance(evidence.get("character_config_path"), str)
            or not evidence.get("character_config_path")
            or not _is_sha256(evidence.get("content_sha256"))
        ):
            raise ValueError("character ability graph ref evidence is inconsistent")
        object.__setattr__(self, "source", source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "graph_ref_id": self.graph_ref_id,
            "character_data_card_id": self.character_data_card_id,
            "owner_avatar_id": self.owner_avatar_id,
            "graph_id": self.graph_id,
            "reference_kind": self.reference_kind,
            "source": _character_ability_source_json(self.source),
        }

def _ambiguous_character_action_source_ids(
    action_sources: tuple[CharacterActionSourceIR, ...],
) -> frozenset[str]:
    if type(action_sources) is not tuple or any(
        type(action) is not CharacterActionSourceIR for action in action_sources
    ):
        raise TypeError("character action ambiguity requires exact typed sources")
    actions_by_owner_id: dict[
        tuple[str, str], list[CharacterActionSourceIR]
    ] = {}
    for action in action_sources:
        actions_by_owner_id.setdefault(
            (action.action_id, action.owner_avatar_id), []
        ).append(action)
    return frozenset(
        action.action_source_id
        for actions in actions_by_owner_id.values()
        if len(actions) != 1
        for action in actions
    )


@dataclass(frozen=True)
class CharacterAbilitySourceGraphCatalogIR:
    snapshot_id: str
    scope_catalog_id: str
    source_fingerprint: str
    fingerprint_kind: Literal["complete", "partial"]
    sources: tuple[CharacterAbilitySourceIR, ...]
    relation_source_digests: Mapping[str, str]
    definitions: tuple[CharacterAbilityDefinitionIR, ...]
    action_sources: tuple[CharacterActionSourceIR, ...]
    non_gameplay_skill_sources: tuple[CharacterNonGameplaySkillSourceIR, ...]
    bindings: tuple[CharacterAbilityBindingIR, ...]
    gaps: tuple[CharacterAbilityBindingGapIR, ...]
    graphs: tuple[CharacterAbilitySourceGraphIR, ...]
    build_counters: Mapping[str, Any]
    catalog_id: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in ("snapshot_id", "scope_catalog_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"character ability source catalog {field_name} is required")
        if (
            not isinstance(self.source_fingerprint, str)
            or len(self.source_fingerprint) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.source_fingerprint
            )
        ):
            raise ValueError("character ability source graph fingerprint is invalid")
        _require_string_enum(
            self.fingerprint_kind,
            frozenset({"complete", "partial"}),
            "character ability source graph fingerprint kind",
        )
        collections = (
            (self.sources, CharacterAbilitySourceIR, "sources", "source_id"),
            (self.definitions, CharacterAbilityDefinitionIR, "definitions", "definition_id"),
            (self.action_sources, CharacterActionSourceIR, "action_sources", "action_source_id"),
            (self.non_gameplay_skill_sources, CharacterNonGameplaySkillSourceIR, "non_gameplay_skill_sources", "non_gameplay_skill_source_id"),
            (self.bindings, CharacterAbilityBindingIR, "bindings", "binding_id"),
            (self.gaps, CharacterAbilityBindingGapIR, "gaps", "gap_id"),
            (self.graphs, CharacterAbilitySourceGraphIR, "graphs", "graph_id"),
        )
        normalized: dict[str, tuple[Any, ...]] = {}
        for values, expected_type, field_name, identity_field in collections:
            items = tuple(values)
            if any(type(item) is not expected_type for item in items):
                raise TypeError(
                    f"character ability source catalog {field_name} contains an invalid IR value"
                )
            ordered = tuple(sorted(items, key=lambda item: getattr(item, identity_field)))
            identities = [getattr(item, identity_field) for item in ordered]
            if len(identities) != len(set(identities)):
                raise ValueError(f"duplicate character ability {field_name} identity")
            normalized[field_name] = ordered
            object.__setattr__(self, field_name, ordered)
        if not self.sources or not self.graphs:
            raise ValueError("character ability source graph catalog cannot be empty")
        if not isinstance(self.relation_source_digests, Mapping):
            raise TypeError("relation source digests must be a mapping")
        digests: dict[str, str] = {}
        for path, digest in self.relation_source_digests.items():
            if (
                not isinstance(path, str)
                or not path
                or not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError("relation source digest is invalid")
            digests[path] = digest
        if not isinstance(self.build_counters, Mapping):
            raise TypeError("character ability source graph counters must be a mapping")
        counters = cast(Mapping[str, Any], freeze_json(dict(self.build_counters)))
        frozen_digests = cast(Mapping[str, str], freeze_json(dict(sorted(digests.items()))))
        object.__setattr__(self, "relation_source_digests", frozen_digests)
        object.__setattr__(self, "build_counters", counters)

        sources_by_id = {source.source_id: source for source in self.sources}
        source_path_digests = {
            source.source.source_path: source.content_sha256
            for source in self.sources
        }
        for source in self.sources:
            evidence = source.source.evidence
            if set(evidence) != {
                "avatar_id",
                "base_type",
                "config_source_path",
                "config_row_index",
                "selected_version",
            }:
                raise ValueError("character ability S0 source evidence schema is invalid")
            if (
                evidence.get("avatar_id") != source.avatar_id
                or evidence.get("base_type") != source.base_type
                or not isinstance(evidence.get("config_source_path"), str)
                or not evidence.get("config_source_path")
                or not isinstance(evidence.get("config_row_index"), int)
                or isinstance(evidence.get("config_row_index"), bool)
                or cast(int, evidence.get("config_row_index")) < 0
                or evidence.get("selected_version")
                not in {"base", "enhanced", "shared"}
            ):
                raise ValueError("character ability S0 source evidence is inconsistent")
        conflicting_digest_paths = set(source_path_digests) & set(frozen_digests)
        if any(
            source_path_digests[path] != frozen_digests[path]
            for path in conflicting_digest_paths
        ):
            raise ValueError("character ability source digest maps conflict")
        audited_digests = {**source_path_digests, **dict(frozen_digests)}
        definitions_by_id = {
            definition.definition_id: definition for definition in self.definitions
        }
        actions_by_id = {
            action.action_source_id: action for action in self.action_sources
        }
        non_gameplay_by_id = {
            source.non_gameplay_skill_source_id: source
            for source in self.non_gameplay_skill_sources
        }
        bindings_by_id = {binding.binding_id: binding for binding in self.bindings}
        gaps_by_id = {gap.gap_id: gap for gap in self.gaps}
        graphs_by_id = {graph.graph_id: graph for graph in self.graphs}
        definition_membership: dict[str, int] = {}
        action_membership: dict[str, int] = {}
        non_gameplay_membership: dict[str, int] = {}
        binding_membership: dict[str, int] = {}
        gap_membership: dict[str, int] = {}
        for graph in self.graphs:
            source = sources_by_id.get(graph.source_id)
            if (
                source is None
                or source.source_kind != graph.source_kind
                or source.avatar_id != graph.owner_avatar_id
                or graph.graph_id
                != character_ability_stable_id(
                    "character_ability_source_graph", graph.source_id
                )
            ):
                raise ValueError("character ability graph source reference is invalid")
            if graph.source_kind == "character_main":
                inventory_source = cast(IRSource, graph.inventory_source)
                inventory_evidence = inventory_source.evidence
                source_evidence = source.source.evidence
                if (
                    inventory_source.source_path
                    != source_evidence.get("config_source_path")
                    or inventory_evidence.get("row_index")
                    != source_evidence.get("config_row_index")
                    or inventory_evidence.get("selected_version")
                    != source_evidence.get("selected_version")
                    or inventory_evidence.get("ability_source_path")
                    != source.source.source_path
                    or inventory_evidence.get("content_sha256")
                    != frozen_digests.get(inventory_source.source_path)
                ):
                    raise ValueError(
                        "owned ability graph does not match its S0 inventory selection"
                    )
            if any(graph_id not in graphs_by_id for graph_id in graph.shared_graph_ids):
                raise ValueError("character ability shared graph reference is dangling")
            if any(item_id not in definitions_by_id for item_id in graph.definition_ids):
                raise ValueError("character ability graph definition reference is dangling")
            if any(item_id not in actions_by_id for item_id in graph.action_source_ids):
                raise ValueError("character ability graph action reference is dangling")
            if any(
                item_id not in non_gameplay_by_id
                for item_id in graph.non_gameplay_skill_source_ids
            ):
                raise ValueError("character graph non-gameplay source reference is dangling")
            if any(item_id not in bindings_by_id for item_id in graph.binding_ids):
                raise ValueError("character ability graph binding reference is dangling")
            if any(item_id not in gaps_by_id for item_id in graph.gap_ids):
                raise ValueError("character ability graph gap reference is dangling")
            for item_id, membership in (
                *((item_id, definition_membership) for item_id in graph.definition_ids),
                *((item_id, action_membership) for item_id in graph.action_source_ids),
                *((item_id, non_gameplay_membership) for item_id in graph.non_gameplay_skill_source_ids),
                *((item_id, binding_membership) for item_id in graph.binding_ids),
                *((item_id, gap_membership) for item_id in graph.gap_ids),
            ):
                membership[item_id] = membership.get(item_id, 0) + 1
            for definition_id in graph.definition_ids:
                definition = definitions_by_id[definition_id]
                if graph.source_kind == "character_shared":
                    if definition.definition_kind != "character_shared":
                        raise ValueError("shared graph contains an owned definition")
                elif (
                    definition.definition_kind == "character_shared"
                    or definition.owner_avatar_id != graph.owner_avatar_id
                ):
                    raise ValueError("owned graph contains a foreign definition")
            if any(
                actions_by_id[action_id].owner_avatar_id != graph.owner_avatar_id
                for action_id in graph.action_source_ids
            ):
                raise ValueError("character ability graph contains a foreign action")
            graph_actions = tuple(
                actions_by_id[action_id] for action_id in graph.action_source_ids
            )
            graph_non_gameplay = tuple(
                non_gameplay_by_id[source_id]
                for source_id in graph.non_gameplay_skill_source_ids
            )
            if any(
                action.skill_id not in graph.selected_skill_ids
                for action in graph_actions
            ):
                raise ValueError("character ability graph contains an unselected action")
            if any(
                source.graph_id != graph.graph_id
                or source.owner_avatar_id != graph.owner_avatar_id
                or source.skill_id not in graph.selected_skill_ids
                for source in graph_non_gameplay
            ):
                raise ValueError("character graph contains a foreign non-gameplay source")
            if len({source.skill_id for source in graph_non_gameplay}) != len(
                graph_non_gameplay
            ):
                raise ValueError("selected skill has duplicate non-gameplay sources")
            action_skill_ids = {action.skill_id for action in graph_actions}
            non_gameplay_skill_ids = {
                source.skill_id for source in graph_non_gameplay
            }
            missing_action_skill_ids = {
                cast(str, gaps_by_id[gap_id].source.evidence.get("skill_id"))
                for gap_id in graph.gap_ids
                if gaps_by_id[gap_id].gap_kind == "missing_action_source_blocked"
            }
            selected_skill_ids = set(graph.selected_skill_ids)
            categories = (
                action_skill_ids,
                non_gameplay_skill_ids,
                missing_action_skill_ids,
            )
            if (
                set.union(*categories) != selected_skill_ids
                or any(
                    categories[left] & categories[right]
                    for left in range(len(categories))
                    for right in range(left + 1, len(categories))
                )
            ):
                raise ValueError(
                    "selected skills must have one exclusive admission outcome"
                )
        for values, membership, label in (
            (definitions_by_id, definition_membership, "definition"),
            (actions_by_id, action_membership, "action"),
            (non_gameplay_by_id, non_gameplay_membership, "non-gameplay source"),
            (bindings_by_id, binding_membership, "binding"),
            (gaps_by_id, gap_membership, "gap"),
        ):
            if set(values) != set(membership) or any(
                count != 1 for count in membership.values()
            ):
                raise ValueError(f"character ability {label} graph membership is not exclusive")
        for source in self.non_gameplay_skill_sources:
            if (
                source.source.evidence.get("content_sha256")
                != audited_digests.get(source.source.source_path)
            ):
                raise ValueError("non-gameplay skill source digest is invalid")
        for definition in self.definitions:
            if definition.definition_kind != "presentation":
                source = sources_by_id.get(definition.source_id)
                if (
                    source is None
                    or source.source.source_path != definition.source.source_path
                    or definition.source.evidence.get("content_sha256")
                    != source.content_sha256
                ):
                    raise ValueError("ability definition source reference is dangling")
            elif (
                definition.source.source_path not in frozen_digests
                or definition.source.evidence.get("content_sha256")
                != frozen_digests[definition.source.source_path]
            ):
                raise ValueError("presentation definition source digest is invalid")
            ability_index = cast(int, definition.source.evidence["ability_index"])
            if (
                definition.source.evidence.get("json_path")
                != f"$.AbilityList[{ability_index}]"
                or definition.definition_id
                != character_ability_stable_id(
                    "character_ability_definition",
                    definition.definition_kind,
                    definition.source_id,
                    definition.source.source_path,
                    ability_index,
                    definition.ability_name,
                )
            ):
                raise ValueError("ability definition row identity is invalid")
        for action in self.action_sources:
            config_evidence = action.config_source.evidence
            skill_source_paths = {
                source.source_path for source in action.skill_sources
            }
            if (
                len(skill_source_paths) != 1
                or
                action.config_source.source_path not in frozen_digests
                or config_evidence.get("content_sha256")
                != frozen_digests[action.config_source.source_path]
                or config_evidence.get("inventory_content_sha256")
                != frozen_digests.get(
                    cast(str, config_evidence.get("inventory_source_path"))
                )
                or any(
                    source.source_path not in frozen_digests
                    or source.evidence.get("content_sha256")
                    != frozen_digests[source.source_path]
                    for source in action.skill_sources
                )
            ):
                raise ValueError("character action relation source digest is invalid")
            table_path = next(iter(skill_source_paths))
            if action.action_source_id != character_ability_stable_id(
                "character_action_source",
                action.owner_avatar_id,
                action.skill_id,
                table_path,
                action.skill_trigger_key,
                action.action_kind,
                action.config_source.source_path,
                config_evidence.get("json_path"),
                *(
                    f"{source.evidence.get('row_index')}:{source.evidence.get('level')}"
                    for source in action.skill_sources
                ),
            ):
                raise ValueError("character action row identity is invalid")
            action_graph = next(
                graph
                for graph in self.graphs
                if action.action_source_id in graph.action_source_ids
            )
            inventory_source = cast(IRSource, action_graph.inventory_source)
            inventory_evidence = inventory_source.evidence
            if (
                config_evidence.get("source_id") != action_graph.source_id
                or config_evidence.get("inventory_source_path")
                != inventory_source.source_path
                or config_evidence.get("inventory_row_index")
                != inventory_evidence.get("row_index")
                or config_evidence.get("selected_version")
                != inventory_evidence.get("selected_version")
                or config_evidence.get("ability_source_path")
                != inventory_evidence.get("ability_source_path")
            ):
                raise ValueError("character action does not use its graph inventory row")
        ambiguous_action_source_ids = _ambiguous_character_action_source_ids(
            self.action_sources
        )
        resolved_relation_ids: set[str] = set()
        for binding in self.bindings:
            definition = definitions_by_id.get(binding.ability_definition_id)
            graph = graphs_by_id.get(binding.graph_id)
            action = actions_by_id.get(binding.action_source_id) if binding.action_source_id else None
            if (
                definition is None
                or graph is None
                or binding.binding_id not in graph.binding_ids
                or definition.ability_name != binding.ability_name
                or definition.owner_avatar_id not in {"", binding.owner_avatar_id}
                or (binding.action_source_id and action is None)
                or (action is not None and action.owner_avatar_id != binding.owner_avatar_id)
                or binding.action_source_id in ambiguous_action_source_ids
                or (
                    binding.binding_kind == "passive"
                    and (action is None or action.action_kind != "passive")
                )
                or (
                    binding.binding_kind in {"entry", "phase"}
                    and (action is None or action.action_kind == "passive")
                )
                or (
                    binding.binding_kind == "presentation"
                    and definition.definition_kind != "presentation"
                )
                or (
                    binding.binding_kind != "presentation"
                    and definition.definition_kind == "presentation"
                )
                or binding.relation_source.evidence.get("content_sha256")
                != audited_digests.get(binding.relation_source.source_path)
                or binding.relation_source.evidence.get("skill_id")
                != (action.skill_id if action is not None else "")
                or (
                    action is not None
                    and binding.relation_source.source_path
                    != action.config_source.source_path
                )
                or (
                    action is None
                    and binding.relation_source.source_path
                    != definition.source.source_path
                )
                or binding.binding_id
                != character_ability_stable_id(
                    "character_ability_binding",
                    binding.relation_id,
                    binding.ability_definition_id,
                )
                or binding.relation_id
                != character_ability_stable_id(
                    "character_ability_relation",
                    binding.graph_id,
                    binding.owner_avatar_id,
                    binding.action_source_id,
                    binding.relation_source.evidence.get("skill_id"),
                    binding.relation_source.raw_id,
                    binding.binding_kind,
                    binding.ordinal,
                    binding.relation_source.source_path,
                    binding.relation_source.evidence.get("json_path"),
                )
            ):
                raise ValueError("character ability binding references are inconsistent")
            if binding.relation_id in resolved_relation_ids:
                raise ValueError(
                    "character ability relation has duplicate outcomes"
                )
            resolved_relation_ids.add(binding.relation_id)
        for gap in self.gaps:
            graph = graphs_by_id.get(gap.graph_id)
            gap_action = (
                actions_by_id.get(gap.action_source_id)
                if gap.action_source_id
                else None
            )
            if (
                graph is None
                or gap.gap_id not in graph.gap_ids
                or any(
                    definition_id not in definitions_by_id
                    for definition_id in gap.candidate_definition_ids
                )
                or any(
                    action_source_id not in actions_by_id
                    for action_source_id in gap.candidate_action_source_ids
                )
                or gap.source.evidence.get("content_sha256")
                != audited_digests.get(gap.source.source_path)
                or gap.relation_id in resolved_relation_ids
                or (
                    gap.action_source_id
                    and (
                        gap_action is None
                        or gap_action.owner_avatar_id != gap.owner_avatar_id
                        or gap.source.source_path
                        != gap_action.config_source.source_path
                        or gap.source.evidence.get("skill_id")
                        != gap_action.skill_id
                    )
                )
                or gap.gap_id
                != character_ability_stable_id(
                    "character_ability_binding_gap",
                    gap.relation_id,
                    gap.gap_kind,
                    *gap.candidate_definition_ids,
                    *gap.candidate_action_source_ids,
                )
                or gap.relation_id
                != character_ability_stable_id(
                    "character_ability_relation",
                    gap.graph_id,
                    gap.owner_avatar_id,
                    gap.action_source_id,
                    gap.source.evidence.get("skill_id"),
                    gap.source.raw_id,
                    gap.expected_binding_kind,
                    gap.ordinal,
                    gap.source.source_path,
                    gap.source.evidence.get("json_path"),
                )
            ):
                raise ValueError("character ability gap references are inconsistent")
            resolved_relation_ids.add(gap.relation_id)
        identity_payload = self._identity_payload()
        catalog_id = "character_ability_source_graph_catalog:" + sha256(
            json.dumps(
                identity_payload,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        object.__setattr__(self, "catalog_id", catalog_id)

    @property
    def source_catalog_complete(self) -> bool:
        return self.fingerprint_kind == "complete"

    @property
    def current_bindings_fully_classified(self) -> bool:
        return not any(gap.gap_kind == "lowering_gap" for gap in self.gaps)

    def _identity_payload(self) -> dict[str, JSONValue]:
        return {
            "snapshot_id": self.snapshot_id,
            "scope_catalog_id": self.scope_catalog_id,
            "source_fingerprint": self.source_fingerprint,
            "fingerprint_kind": self.fingerprint_kind,
            "sources": [source.to_json() for source in self.sources],
            "relation_source_digests": cast(
                JSONValue, thaw_json(self.relation_source_digests)
            ),
            "definitions": [definition.to_json() for definition in self.definitions],
            "action_sources": [action.to_json() for action in self.action_sources],
            "non_gameplay_skill_sources": [
                source.to_json() for source in self.non_gameplay_skill_sources
            ],
            "bindings": [binding.to_json() for binding in self.bindings],
            "gaps": [gap.to_json() for gap in self.gaps],
            "graphs": [graph.to_json() for graph in self.graphs],
        }

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "catalog_id": self.catalog_id,
            **self._identity_payload(),
            "build_counters": cast(JSONValue, thaw_json(self.build_counters)),
        }


@dataclass(frozen=True)
class CharacterDecodedSourceIR:
    decoded_id: str
    scope_record_id: str
    source_family: str
    source_occurrence_kind: CharacterAbilityOccurrenceKind
    decoded_kind: CharacterDecodedSourceKind
    package_owner: CharacterDecodedPackageOwner
    payload: Mapping[str, Any]
    source: IRSource
    typed_operation: Mapping[str, Any] | None = None
    runtime_admission: Literal["not_admitted"] = "not_admitted"

    def __post_init__(self) -> None:
        for field_name in (
            "decoded_id",
            "scope_record_id",
            "source_family",
            "package_owner",
        ):
            if not isinstance(getattr(self, field_name), str) or not getattr(
                self, field_name
            ):
                raise ValueError(f"decoded character source {field_name} is required")
        _require_string_enum(
            self.source_occurrence_kind,
            _CHARACTER_ABILITY_OCCURRENCE_KINDS,
            "decoded character source occurrence kind",
        )
        _require_string_enum(
            self.decoded_kind,
            _CHARACTER_DECODED_SOURCE_KINDS,
            "decoded character source kind",
        )
        _require_string_enum(
            self.package_owner,
            _CHARACTER_DECODED_PACKAGE_OWNERS,
            "decoded character package owner",
        )
        expected_owner = {
            "dynamic_value_definition": "character_dynamic_values",
            "dynamic_value_write": "character_dynamic_values",
            "action_queue_precheck": "character_action_queue",
            "target_alias": "character_target_expression",
        }[self.decoded_kind]
        if self.package_owner != expected_owner:
            raise ValueError("decoded character kind and package owner disagree")
        if self.runtime_admission != "not_admitted":
            raise ValueError("decoded character source cannot enter runtime in S3")
        if not isinstance(self.payload, Mapping):
            raise TypeError("decoded character source payload must be an object")
        payload = cast(Mapping[str, Any], freeze_json(dict(self.payload)))
        expected_keys = {
            "dynamic_value_definition": {"target_alias", "dynamic_key"},
            "dynamic_value_write": {
                "target_alias",
                "dynamic_key",
                "value_expression",
                "operation",
            },
            "action_queue_precheck": {"metric", "threshold_expression"},
            "target_alias": {"alias"},
        }[self.decoded_kind]
        if set(payload) != expected_keys:
            raise ValueError("decoded character source payload schema is invalid")
        string_fields = {
            "dynamic_value_definition": ("target_alias", "dynamic_key"),
            "dynamic_value_write": ("target_alias", "dynamic_key"),
            "action_queue_precheck": ("metric",),
            "target_alias": ("alias",),
        }[self.decoded_kind]
        if any(
            not isinstance(payload.get(field_name), str)
            or not payload.get(field_name)
            for field_name in string_fields
        ):
            raise ValueError("decoded character source string field is invalid")
        if self.decoded_kind == "dynamic_value_write":
            operation = payload.get("operation")
            if operation is not None and (
                not isinstance(operation, str) or not operation
            ):
                raise ValueError("decoded dynamic write operation is invalid")
        if self.decoded_kind == "action_queue_precheck" and (
            payload.get("metric") != "SameTagInsertUnusedCount"
        ):
            raise ValueError("decoded action queue precheck metric is invalid")
        expression_key = {
            "dynamic_value_write": "value_expression",
            "action_queue_precheck": "threshold_expression",
        }.get(self.decoded_kind)
        if expression_key is not None:
            expression = payload.get(expression_key)
            if not is_exact_numeric_expression(thaw_json(expression)):
                raise ValueError("decoded character numeric expression is untyped")
        source = _immutable_character_ability_source(self.source)
        dynamic_kind = self.decoded_kind in {
            "dynamic_value_definition",
            "dynamic_value_write",
        }
        if dynamic_kind:
            if not isinstance(self.typed_operation, Mapping):
                raise TypeError("decoded dynamic source requires a typed operation")
            typed_operation = cast(
                Mapping[str, Any],
                freeze_json(dict(self.typed_operation)),
            )
            DynamicValueOperationIR.from_spec(thaw_json(typed_operation), source)
        elif self.typed_operation is not None:
            raise ValueError("non-dynamic decoded source cannot carry a dynamic operation")
        else:
            typed_operation = None
        if (
            source.raw_id != self.scope_record_id
            or source.raw_type != self.source_family
        ):
            raise ValueError("decoded character source identity is inconsistent")
        evidence = source.evidence
        if set(evidence) != {
            "json_path",
            "parent_branch_path",
            "inherited_scope_record_id",
            "nominal_semantic_kind",
            "source_kind",
            "avatar_id",
        } or (
            not isinstance(evidence.get("json_path"), str)
            or not evidence.get("json_path")
            or not isinstance(evidence.get("parent_branch_path"), str)
            or not evidence.get("parent_branch_path")
            or not isinstance(evidence.get("inherited_scope_record_id"), str)
            or not isinstance(evidence.get("nominal_semantic_kind"), str)
            or evidence.get("source_kind")
            not in {"character_main", "character_shared"}
            or not isinstance(evidence.get("avatar_id"), str)
        ):
            raise ValueError("decoded character source evidence schema is invalid")
        if self.scope_record_id != character_ability_scope_record_id(
            self.source_occurrence_kind,
            source.source_path,
            evidence.get("json_path"),
            self.source_family,
        ):
            raise ValueError("decoded character scope identity is invalid")
        if self.decoded_kind == "action_queue_precheck" and not cast(
            str, evidence.get("json_path")
        ).endswith(".PreCheck.$type"):
            raise ValueError("decoded action queue precheck source path is invalid")
        if self.decoded_id != character_ability_stable_id(
            "character_decoded_source",
            self.scope_record_id,
            self.source_family,
            self.source_occurrence_kind,
            self.decoded_kind,
            self.package_owner,
            source.source_path,
            evidence.get("json_path"),
        ):
            raise ValueError("decoded character source stable identity is invalid")
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "typed_operation", typed_operation)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "decoded_id": self.decoded_id,
            "scope_record_id": self.scope_record_id,
            "source_family": self.source_family,
            "source_occurrence_kind": self.source_occurrence_kind,
            "decoded_kind": self.decoded_kind,
            "package_owner": self.package_owner,
            "payload": cast(JSONValue, thaw_json(self.payload)),
            "typed_operation": cast(JSONValue, thaw_json(self.typed_operation)),
            "source": _character_ability_source_json(self.source),
            "coverage_status": "lowered",
            "runtime_admission": self.runtime_admission,
        }


@dataclass(frozen=True)
class CharacterEquivalentStructureEvidenceIR:
    evidence_id: str
    raw_type: CharacterEquivalentRawType
    observed_fields: tuple[str, ...]
    field_role_mapping: Mapping[str, str]
    source: IRSource

    def __post_init__(self) -> None:
        _require_string_enum(
            self.raw_type,
            _CHARACTER_EQUIVALENT_RAW_TYPES,
            "character equivalent raw type",
        )
        observed_fields = _require_unique_strings(
            self.observed_fields, "character equivalent observed fields"
        )
        if "$type" not in observed_fields:
            raise ValueError("character equivalent evidence must retain $type")
        if not isinstance(self.field_role_mapping, Mapping):
            raise TypeError("character equivalent field roles must be a mapping")
        allowed_roles = {
            "RPG.GameCore.DefineDynamicValue": {
                "TargetType": "target_alias",
                "DynamicKey": "dynamic_key",
            },
            "RPG.GameCore.SetDynamicValue": {
                "TargetType": "target_alias",
                "DynamicKey": "dynamic_key",
                "Value": "value_expression",
                "SetType": "operation",
            },
            "RPG.GameCore.TargetAlias": {"Alias": "alias"},
        }[self.raw_type]
        roles: dict[str, str] = {}
        for field_name, role in self.field_role_mapping.items():
            if (
                not isinstance(field_name, str)
                or not isinstance(role, str)
                or field_name not in observed_fields
                or allowed_roles.get(field_name) != role
            ):
                raise ValueError("character equivalent field role is invalid")
            roles[field_name] = role
        if not roles:
            raise ValueError("character equivalent evidence has no normalized role")
        frozen_roles = cast(
            Mapping[str, str], freeze_json(dict(sorted(roles.items())))
        )
        source = _immutable_character_ability_source(self.source)
        evidence = source.evidence
        if set(evidence) != {"json_path", "content_sha256"} or (
            source.raw_id != self.evidence_id
            or source.raw_type != self.raw_type
            or not isinstance(evidence.get("json_path"), str)
            or not evidence.get("json_path")
            or not _is_sha256(evidence.get("content_sha256"))
        ):
            raise ValueError("character equivalent source evidence is inconsistent")
        if self.evidence_id != character_ability_stable_id(
            "character_equivalent_structure_evidence",
            self.raw_type,
            source.source_path,
            evidence.get("json_path"),
            evidence.get("content_sha256"),
            *observed_fields,
            *(f"{key}:{value}" for key, value in frozen_roles.items()),
        ):
            raise ValueError("character equivalent evidence identity is invalid")
        object.__setattr__(self, "observed_fields", observed_fields)
        object.__setattr__(self, "field_role_mapping", frozen_roles)
        object.__setattr__(self, "source", source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "evidence_id": self.evidence_id,
            "raw_type": self.raw_type,
            "observed_fields": list(self.observed_fields),
            "field_role_mapping": cast(
                JSONValue, thaw_json(self.field_role_mapping)
            ),
            "source": _character_ability_source_json(self.source),
            "coverage_status": "audit_only",
        }


@dataclass(frozen=True)
class CharacterDecodeFamilyResolutionIR:
    resolution_id: str
    family: str
    outcome: CharacterSourceResolutionOutcome
    scope_record_ids: tuple[str, ...]
    decoded_item_ids: tuple[str, ...]
    package_owner: CharacterDecodedPackageOwner | Literal[""]
    observed_fields: tuple[str, ...]
    parent_families: tuple[str, ...]
    target_aliases: tuple[str, ...]
    value_shapes: tuple[str, ...]
    condition_families: tuple[str, ...]
    graph_neighbor_families: tuple[str, ...]
    source_paths: tuple[str, ...]
    candidate_equivalent_types: tuple[str, ...]
    candidate_evidence: tuple[CharacterEquivalentStructureEvidenceIR, ...]
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.family, str) or not self.family:
            raise ValueError("decode family identity is required")
        _require_string_enum(
            self.outcome,
            _CHARACTER_SOURCE_RESOLUTION_OUTCOMES,
            "decode family outcome",
        )
        for field_name in (
            "scope_record_ids",
            "decoded_item_ids",
            "observed_fields",
            "parent_families",
            "target_aliases",
            "value_shapes",
            "condition_families",
            "graph_neighbor_families",
            "source_paths",
            "candidate_equivalent_types",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_unique_strings(
                    getattr(self, field_name), f"decode family {field_name}"
                ),
            )
        evidence_items = tuple(self.candidate_evidence)
        if any(
            type(item) is not CharacterEquivalentStructureEvidenceIR
            for item in evidence_items
        ):
            raise TypeError("decode family candidate evidence must be typed")
        evidence_items = tuple(
            sorted(evidence_items, key=lambda item: item.evidence_id)
        )
        evidence_ids = [item.evidence_id for item in evidence_items]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("decode family candidate evidence is duplicated")
        if evidence_items and set(self.candidate_equivalent_types) != {
            item.raw_type for item in evidence_items
        }:
            raise ValueError("decode family equivalent evidence type is inconsistent")
        object.__setattr__(self, "candidate_evidence", evidence_items)
        if not self.scope_record_ids or not self.observed_fields or not self.source_paths:
            raise ValueError("decode family dossier is incomplete")
        if not isinstance(self.package_owner, str) or not isinstance(
            self.blocked_reason, str
        ):
            raise TypeError("decode family resolution metadata must be strings")
        if self.package_owner:
            _require_string_enum(
                self.package_owner,
                _CHARACTER_DECODED_PACKAGE_OWNERS,
                "decode family package owner",
            )
        if self.outcome == "decoded_to_package":
            if (
                not self.package_owner
                or self.blocked_reason
                or len(self.scope_record_ids) != len(self.decoded_item_ids)
            ):
                raise ValueError("decoded family must lower every current occurrence")
            contract = _CHARACTER_DECODE_FAMILY_CONTRACTS.get(self.family)
            if contract is None or self.package_owner != contract[0]:
                raise ValueError("decoded family package contract is invalid")
            equivalent_type, required_roles = contract[1], contract[2]
            if equivalent_type:
                if not evidence_items or any(
                    item.raw_type != equivalent_type
                    or not required_roles.issubset(
                        set(item.field_role_mapping.values())
                    )
                    for item in evidence_items
                ):
                    raise ValueError("decoded family equivalent evidence is incompatible")
            elif evidence_items:
                raise ValueError("queue precheck family cannot invent equivalent evidence")
            if self.family == "IKDAKCBKFAB" and self.parent_families != (
                "TurnInsertAction",
            ):
                raise ValueError("queue precheck family parent context is invalid")
        elif self.outcome == "source_gap_blocked":
            if self.package_owner or self.decoded_item_ids or not self.blocked_reason:
                raise ValueError("blocked family cannot publish decoded ownership")
        elif self.package_owner or self.decoded_item_ids or self.blocked_reason:
            raise ValueError("non-gameplay family resolution is inconsistent")
        if self.resolution_id != character_ability_stable_id(
            "character_decode_family_resolution",
            self.family,
            self.outcome,
            self.package_owner,
            *self.scope_record_ids,
            *self.decoded_item_ids,
            *(item.evidence_id for item in self.candidate_evidence),
            self.blocked_reason,
        ):
            raise ValueError("decode family resolution identity is invalid")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "resolution_id": self.resolution_id,
            "family": self.family,
            "outcome": self.outcome,
            "scope_record_ids": list(self.scope_record_ids),
            "decoded_item_ids": list(self.decoded_item_ids),
            "package_owner": self.package_owner,
            "dossier": {
                "observed_fields": list(self.observed_fields),
                "parent_families": list(self.parent_families),
                "target_aliases": list(self.target_aliases),
                "value_shapes": list(self.value_shapes),
                "condition_families": list(self.condition_families),
                "graph_neighbor_families": list(
                    self.graph_neighbor_families
                ),
                "source_paths": list(self.source_paths),
                "candidate_equivalent_types": list(
                    self.candidate_equivalent_types
                ),
                "candidate_evidence": [
                    item.to_json() for item in self.candidate_evidence
                ],
            },
            "coverage_status": (
                "lowered"
                if self.outcome == "decoded_to_package"
                else "audit_only"
                if self.outcome == "non_gameplay"
                else "blocked"
            ),
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class CharacterAbilityDefinitionCandidateIR:
    candidate_id: str
    ability_name: str
    package_owner: CharacterAbilityDefinitionPackageOwner
    source: IRSource

    def __post_init__(self) -> None:
        for field_name in ("candidate_id", "ability_name", "package_owner"):
            if not isinstance(getattr(self, field_name), str) or not getattr(
                self, field_name
            ):
                raise ValueError(f"ability candidate {field_name} is required")
        _require_string_enum(
            self.package_owner,
            _CHARACTER_ABILITY_DEFINITION_PACKAGE_OWNERS,
            "ability definition package owner",
        )
        source = _immutable_character_ability_source(self.source)
        evidence = source.evidence
        if set(evidence) != {
            "ability_name",
            "json_path",
            "content_sha256",
            "byte_size",
            "package_owner",
        }:
            raise ValueError("ability candidate evidence schema is invalid")
        if (
            source.raw_id != self.candidate_id
            or source.raw_type != "character_ability_definition_candidate"
            or evidence.get("ability_name") != self.ability_name
            or evidence.get("package_owner") != self.package_owner
            or not isinstance(evidence.get("json_path"), str)
            or not evidence.get("json_path")
            or not _is_sha256(evidence.get("content_sha256"))
            or not isinstance(evidence.get("byte_size"), int)
            or isinstance(evidence.get("byte_size"), bool)
            or cast(int, evidence.get("byte_size")) < 0
        ):
            raise ValueError("ability candidate source evidence is inconsistent")
        if self.candidate_id != character_ability_stable_id(
            "character_ability_definition_candidate",
            source.source_path,
            evidence.get("json_path"),
            self.ability_name,
            evidence.get("content_sha256"),
        ):
            raise ValueError("ability candidate stable identity is invalid")
        if self.package_owner != character_ability_definition_package_owner(
            source.source_path
        ):
            raise ValueError("ability candidate package domain is invalid")
        object.__setattr__(self, "source", source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "candidate_id": self.candidate_id,
            "ability_name": self.ability_name,
            "package_owner": self.package_owner,
            "source": _character_ability_source_json(self.source),
            "coverage_status": "audit_only",
        }


@dataclass(frozen=True)
class CharacterAbilityReferenceResolutionIR:
    resolution_id: str
    subject_kind: CharacterSourceResolutionSubjectKind
    subject_id: str
    owner_avatar_id: str
    ability_name: str
    reference_opcode: str
    outcome: CharacterSourceResolutionOutcome
    package_owner: CharacterAbilityDefinitionPackageOwner | Literal[""]
    candidate_ids: tuple[str, ...]
    source: IRSource
    source_graph_gap_kind: CharacterAbilityBindingGapKind | Literal[""] = ""
    source_graph_candidate_definition_ids: tuple[str, ...] = ()
    source_graph_candidate_action_source_ids: tuple[str, ...] = ()
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        for field_name in ("resolution_id", "subject_id"):
            if not isinstance(getattr(self, field_name), str) or not getattr(
                self, field_name
            ):
                raise ValueError(f"ability reference resolution {field_name} is required")
        _require_string_enum(
            self.subject_kind,
            _CHARACTER_SOURCE_RESOLUTION_SUBJECT_KINDS,
            "ability reference subject kind",
        )
        _require_string_enum(
            self.outcome,
            _CHARACTER_SOURCE_RESOLUTION_OUTCOMES,
            "ability reference outcome",
        )
        if any(
            not isinstance(value, str)
            for value in (
                self.owner_avatar_id,
                self.ability_name,
                self.reference_opcode,
                self.package_owner,
                self.blocked_reason,
            )
        ):
            raise TypeError("ability reference resolution metadata must be strings")
        candidate_ids = _require_unique_strings(
            self.candidate_ids, "ability reference candidates"
        )
        source_graph_definition_ids = _require_unique_strings(
            self.source_graph_candidate_definition_ids,
            "source graph gap definition candidates",
        )
        source_graph_action_ids = _require_unique_strings(
            self.source_graph_candidate_action_source_ids,
            "source graph gap action candidates",
        )
        if self.package_owner:
            _require_string_enum(
                self.package_owner,
                _CHARACTER_ABILITY_DEFINITION_PACKAGE_OWNERS,
                "ability reference package owner",
            )
        if self.outcome in {"decoded_to_package", "non_gameplay"}:
            if (
                len(candidate_ids) != 1
                or not self.package_owner
                or self.blocked_reason
                or not self.ability_name
            ):
                raise ValueError("resolved ability reference must identify one package row")
        elif self.package_owner or not self.blocked_reason:
            raise ValueError("blocked ability reference cannot publish package ownership")
        source = _immutable_character_ability_source(self.source)
        evidence = source.evidence
        if self.subject_kind == "ability_task_reference":
            if (
                self.source_graph_gap_kind
                or source_graph_definition_ids
                or source_graph_action_ids
            ):
                raise ValueError("ability task reference cannot carry S1 gap identity")
            if set(evidence) != {
                "ability_name",
                "json_path",
                "owner_avatar_id",
                "content_sha256",
            } or (
                source.raw_id != self.subject_id
                or source.raw_type != self.reference_opcode
                or evidence.get("ability_name") != self.ability_name
                or evidence.get("owner_avatar_id") != self.owner_avatar_id
                or not isinstance(evidence.get("json_path"), str)
                or not evidence.get("json_path")
                or not _is_sha256(evidence.get("content_sha256"))
            ):
                raise ValueError("ability task reference evidence is inconsistent")
            if self.subject_id != character_ability_stable_id(
                "character_ability_task_reference",
                source.source_path,
                evidence.get("json_path"),
                self.reference_opcode,
                self.ability_name,
            ):
                raise ValueError("ability task reference identity is invalid")
        elif set(evidence) != {
            "relation_id",
            "graph_id",
            "owner_avatar_id",
            "action_source_id",
            "skill_id",
            "binding_kind",
            "relation_ordinal",
            "json_path",
            "content_sha256",
        } or (
            source.raw_type != "CharacterAbilityRelation"
            or not isinstance(source.raw_id, str)
            or not source.raw_id
            or not isinstance(evidence.get("relation_id"), str)
            or not evidence.get("relation_id")
            or not isinstance(evidence.get("graph_id"), str)
            or not evidence.get("graph_id")
            or evidence.get("owner_avatar_id") != self.owner_avatar_id
            or not isinstance(evidence.get("action_source_id"), str)
            or not isinstance(evidence.get("skill_id"), str)
            or evidence.get("binding_kind") != self.reference_opcode
            or not isinstance(evidence.get("relation_ordinal"), int)
            or isinstance(evidence.get("relation_ordinal"), bool)
            or cast(int, evidence.get("relation_ordinal")) < 0
            or not isinstance(evidence.get("json_path"), str)
            or not evidence.get("json_path")
            or not _is_sha256(evidence.get("content_sha256"))
        ):
            raise ValueError("source graph gap evidence is inconsistent")
        else:
            _require_string_enum(
                self.source_graph_gap_kind,
                _CHARACTER_ABILITY_BINDING_GAP_KINDS,
                "source graph gap kind",
            )
            expected_relation_id = character_ability_stable_id(
                "character_ability_relation",
                evidence.get("graph_id"),
                self.owner_avatar_id,
                evidence.get("action_source_id"),
                evidence.get("skill_id"),
                source.raw_id,
                self.reference_opcode,
                evidence.get("relation_ordinal"),
                source.source_path,
                evidence.get("json_path"),
            )
            if evidence.get("relation_id") != expected_relation_id:
                raise ValueError("source graph relation identity is invalid")
            if self.subject_id != character_ability_stable_id(
                "character_ability_binding_gap",
                expected_relation_id,
                self.source_graph_gap_kind,
                *source_graph_definition_ids,
                *source_graph_action_ids,
            ):
                raise ValueError("source graph gap identity is invalid")
        if self.resolution_id != character_ability_stable_id(
            "character_ability_reference_resolution",
            self.subject_kind,
            self.subject_id,
        ):
            raise ValueError("ability reference resolution identity is invalid")
        object.__setattr__(self, "candidate_ids", candidate_ids)
        object.__setattr__(
            self,
            "source_graph_candidate_definition_ids",
            source_graph_definition_ids,
        )
        object.__setattr__(
            self,
            "source_graph_candidate_action_source_ids",
            source_graph_action_ids,
        )
        object.__setattr__(self, "source", source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "resolution_id": self.resolution_id,
            "subject_kind": self.subject_kind,
            "subject_id": self.subject_id,
            "owner_avatar_id": self.owner_avatar_id,
            "ability_name": self.ability_name,
            "reference_opcode": self.reference_opcode,
            "outcome": self.outcome,
            "package_owner": self.package_owner,
            "candidate_ids": list(self.candidate_ids),
            "source_graph_gap_kind": self.source_graph_gap_kind,
            "source_graph_candidate_definition_ids": list(
                self.source_graph_candidate_definition_ids
            ),
            "source_graph_candidate_action_source_ids": list(
                self.source_graph_candidate_action_source_ids
            ),
            "source": _character_ability_source_json(self.source),
            "coverage_status": (
                "audit_only"
                if self.outcome == "non_gameplay"
                else "blocked"
                if self.outcome == "source_gap_blocked"
                else "lowered"
            ),
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class CharacterAbilitySourceResolutionCatalogIR:
    scope_catalog_id: str
    source_graph_catalog_id: str
    source_fingerprint: str
    package_search_root: str
    package_manifest_digests: Mapping[str, str]
    package_manifest_sizes: Mapping[str, int]
    decode_required_record_ids: tuple[str, ...]
    source_graph_gap_ids: tuple[str, ...]
    unresolved_reference_ids: tuple[str, ...]
    family_resolutions: tuple[CharacterDecodeFamilyResolutionIR, ...]
    decoded_items: tuple[CharacterDecodedSourceIR, ...]
    definition_candidates: tuple[CharacterAbilityDefinitionCandidateIR, ...]
    reference_resolutions: tuple[CharacterAbilityReferenceResolutionIR, ...]
    build_counters: Mapping[str, Any]
    catalog_id: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in (
            "scope_catalog_id",
            "source_graph_catalog_id",
            "package_search_root",
        ):
            if not isinstance(getattr(self, field_name), str) or not getattr(
                self, field_name
            ):
                raise ValueError(f"source resolution catalog {field_name} is required")
        if not _is_sha256(self.source_fingerprint):
            raise ValueError("source resolution fingerprint is invalid")
        for field_name in (
            "decode_required_record_ids",
            "source_graph_gap_ids",
            "unresolved_reference_ids",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_unique_strings(
                    getattr(self, field_name), f"source resolution {field_name}"
                ),
            )
        typed_collections = (
            (
                self.family_resolutions,
                CharacterDecodeFamilyResolutionIR,
                "family_resolutions",
                "resolution_id",
            ),
            (self.decoded_items, CharacterDecodedSourceIR, "decoded_items", "decoded_id"),
            (
                self.definition_candidates,
                CharacterAbilityDefinitionCandidateIR,
                "definition_candidates",
                "candidate_id",
            ),
            (
                self.reference_resolutions,
                CharacterAbilityReferenceResolutionIR,
                "reference_resolutions",
                "resolution_id",
            ),
        )
        for values, expected_type, field_name, identity_field in typed_collections:
            items = tuple(values)
            if any(type(item) is not expected_type for item in items):
                raise TypeError(f"source resolution {field_name} contains invalid IR")
            ordered = tuple(sorted(items, key=lambda item: getattr(item, identity_field)))
            identities = [getattr(item, identity_field) for item in ordered]
            if len(identities) != len(set(identities)):
                raise ValueError(f"source resolution {field_name} identity is duplicated")
            object.__setattr__(self, field_name, ordered)
        if not self.family_resolutions or not self.decode_required_record_ids:
            raise ValueError("source resolution decode catalog cannot be empty")
        if not isinstance(self.package_manifest_digests, Mapping) or not isinstance(
            self.package_manifest_sizes, Mapping
        ):
            raise TypeError("source resolution package manifest must be mappings")
        digests: dict[str, str] = {}
        sizes: dict[str, int] = {}
        for path, digest in self.package_manifest_digests.items():
            if not isinstance(path, str) or not path or not _is_sha256(digest):
                raise ValueError("source resolution package digest is invalid")
            digests[path] = digest
        for path, size in self.package_manifest_sizes.items():
            if (
                not isinstance(path, str)
                or not path
                or not isinstance(size, int)
                or isinstance(size, bool)
                or size < 0
            ):
                raise ValueError("source resolution package size is invalid")
            sizes[path] = size
        if not digests or set(digests) != set(sizes):
            raise ValueError("source resolution package manifest is incomplete")
        frozen_digests = cast(
            Mapping[str, str], freeze_json(dict(sorted(digests.items())))
        )
        frozen_sizes = cast(
            Mapping[str, int], freeze_json(dict(sorted(sizes.items())))
        )
        if not isinstance(self.build_counters, Mapping):
            raise TypeError("source resolution build counters must be a mapping")
        counters = cast(Mapping[str, Any], freeze_json(dict(self.build_counters)))
        object.__setattr__(self, "package_manifest_digests", frozen_digests)
        object.__setattr__(self, "package_manifest_sizes", frozen_sizes)
        object.__setattr__(self, "build_counters", counters)

        decoded_by_id = {item.decoded_id: item for item in self.decoded_items}
        family_record_ids = {
            record_id
            for resolution in self.family_resolutions
            for record_id in resolution.scope_record_ids
        }
        family_decoded_ids = {
            decoded_id
            for resolution in self.family_resolutions
            for decoded_id in resolution.decoded_item_ids
        }
        if family_record_ids != set(self.decode_required_record_ids):
            raise ValueError("decode family resolutions do not cover the current set")
        if family_decoded_ids != set(decoded_by_id):
            raise ValueError("decoded family item membership is incomplete")
        if len(family_record_ids) != sum(
            len(resolution.scope_record_ids)
            for resolution in self.family_resolutions
        ):
            raise ValueError("decode family record membership is not exclusive")
        for resolution in self.family_resolutions:
            items = [decoded_by_id[item_id] for item_id in resolution.decoded_item_ids]
            if resolution.outcome == "decoded_to_package" and (
                {item.scope_record_id for item in items}
                != set(resolution.scope_record_ids)
                or any(
                    item.source_family != resolution.family
                    or item.package_owner != resolution.package_owner
                    for item in items
                )
            ):
                raise ValueError("decoded family item ownership is inconsistent")
            if any(path not in frozen_digests for path in resolution.source_paths):
                raise ValueError("decode family source path is outside the package manifest")
            if items and {
                item.source.source_path for item in items
            } != set(resolution.source_paths):
                raise ValueError("decoded family source path membership is inconsistent")
            for item in items:
                if item.source.source_path not in frozen_digests:
                    raise ValueError("decoded source path is outside the package manifest")
            for equivalent in resolution.candidate_evidence:
                source_path = equivalent.source.source_path
                if (
                    source_path not in frozen_digests
                    or equivalent.source.evidence.get("content_sha256")
                    != frozen_digests[source_path]
                ):
                    raise ValueError("equivalent structure evidence is stale")

        expected_subjects = {
            ("source_graph_gap", item_id)
            for item_id in self.source_graph_gap_ids
        } | {
            ("ability_task_reference", item_id)
            for item_id in self.unresolved_reference_ids
        }
        actual_subjects = {
            (resolution.subject_kind, resolution.subject_id)
            for resolution in self.reference_resolutions
        }
        if actual_subjects != expected_subjects:
            raise ValueError("ability reference resolution closure is incomplete")
        candidates_by_id = {
            candidate.candidate_id: candidate
            for candidate in self.definition_candidates
        }
        referenced_candidate_ids = {
            candidate_id
            for resolution in self.reference_resolutions
            for candidate_id in resolution.candidate_ids
        }
        if referenced_candidate_ids != set(candidates_by_id):
            raise ValueError("ability candidate membership is incomplete")
        for candidate in self.definition_candidates:
            source_path = candidate.source.source_path
            evidence = candidate.source.evidence
            if (
                source_path not in frozen_digests
                or evidence.get("content_sha256") != frozen_digests[source_path]
                or evidence.get("byte_size") != frozen_sizes[source_path]
            ):
                raise ValueError("ability candidate package evidence is stale")
        for resolution in self.reference_resolutions:
            candidates = [
                candidates_by_id[candidate_id]
                for candidate_id in resolution.candidate_ids
            ]
            if resolution.outcome in {"decoded_to_package", "non_gameplay"} and (
                len(candidates) != 1
                or candidates[0].package_owner != resolution.package_owner
                or candidates[0].ability_name != resolution.ability_name
            ):
                raise ValueError("resolved ability reference package ownership is forged")
            if resolution.subject_kind == "ability_task_reference":
                source_path = resolution.source.source_path
                if (
                    source_path not in frozen_digests
                    or resolution.source.evidence.get("content_sha256")
                    != frozen_digests[source_path]
                ):
                    raise ValueError("ability task reference source is stale")
        identity_payload = self._identity_payload()
        object.__setattr__(
            self,
            "catalog_id",
            "character_ability_source_resolution_catalog:"
            + sha256(
                json.dumps(
                    identity_payload,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        )

    @property
    def all_decode_items_have_structured_resolution(self) -> bool:
        return bool(self.decode_required_record_ids) and {
            record_id
            for resolution in self.family_resolutions
            for record_id in resolution.scope_record_ids
        } == set(self.decode_required_record_ids)

    @property
    def missing_ability_search_closure_complete(self) -> bool:
        return bool(self.package_manifest_digests) and len(
            self.reference_resolutions
        ) == len(self.source_graph_gap_ids) + len(self.unresolved_reference_ids)

    def _identity_payload(self) -> dict[str, JSONValue]:
        return {
            "scope_catalog_id": self.scope_catalog_id,
            "source_graph_catalog_id": self.source_graph_catalog_id,
            "source_fingerprint": self.source_fingerprint,
            "package_search_root": self.package_search_root,
            "package_manifest_digests": cast(
                JSONValue, thaw_json(self.package_manifest_digests)
            ),
            "package_manifest_sizes": cast(
                JSONValue, thaw_json(self.package_manifest_sizes)
            ),
            "decode_required_record_ids": list(self.decode_required_record_ids),
            "source_graph_gap_ids": list(self.source_graph_gap_ids),
            "unresolved_reference_ids": list(self.unresolved_reference_ids),
            "family_resolutions": [
                resolution.to_json() for resolution in self.family_resolutions
            ],
            "decoded_items": [item.to_json() for item in self.decoded_items],
            "definition_candidates": [
                candidate.to_json() for candidate in self.definition_candidates
            ],
            "reference_resolutions": [
                resolution.to_json() for resolution in self.reference_resolutions
            ],
        }

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "catalog_id": self.catalog_id,
            **self._identity_payload(),
            "build_counters": cast(JSONValue, thaw_json(self.build_counters)),
        }


@dataclass(frozen=True)
class FormulaIR:
    formula_id: str
    kind: str
    expression: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "audit_only"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "formula_id": self.formula_id,
            "kind": self.kind,
            "expression": self.expression,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
        }


class _FrozenIRPayloadDict(dict[str, Any]):
    """Dict-compatible immutable payload that can contain typed IR children."""

    def __init__(self, values: Mapping[str, Any]) -> None:
        if not all(isinstance(key, str) for key in values):
            raise TypeError("IR payload keys must be strings")
        dict.__init__(self, {key: _freeze_ir_payload_value(value) for key, value in values.items()})

    def _immutable(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("frozen IR payload cannot be mutated")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


class _FrozenIRPayloadList(list[Any]):
    def __init__(self, values: Iterable[Any]) -> None:
        list.__init__(self, [_freeze_ir_payload_value(value) for value in values])

    def _immutable(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("frozen IR payload cannot be mutated")

    __setitem__ = _immutable
    __delitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable


def _freeze_ir_payload_value(value: Any) -> Any:
    if type(value) in (TargetExpressionNodeIR, ConditionIR):
        return value
    if isinstance(value, Mapping):
        return _FrozenIRPayloadDict(value)
    if isinstance(value, (list, tuple)):
        return _FrozenIRPayloadList(value)
    return freeze_json(value)


@dataclass(frozen=True)
class ConditionIR:
    condition_id: str
    opcode: str
    payload: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "unsupported"
    expression_schema_version: str = ""
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        if type(self) is not ConditionIR:
            raise TypeError("condition IR must not be subclassed")
        if not isinstance(self.condition_id, str) or not self.condition_id:
            raise ValueError("condition identity is required")
        if not isinstance(self.opcode, str) or not self.opcode:
            raise ValueError("condition opcode is required")
        if not isinstance(self.payload, Mapping):
            raise TypeError("condition payload must be an object")
        if not isinstance(self.source, IRSource):
            raise TypeError("condition source must be IRSource")
        if self.coverage_status == "executable" and self.blocked_reason:
            raise ValueError("executable condition cannot carry a blocked reason")
        if self.coverage_status == "blocked" and not self.blocked_reason:
            raise ValueError("blocked condition requires a reason")
        object.__setattr__(self, "payload", _FrozenIRPayloadDict(self.payload))
        object.__setattr__(
            self,
            "source",
            IRSource(
                source_path=self.source.source_path,
                raw_type=self.source.raw_type,
                raw_id=self.source.raw_id,
                evidence=freeze_json(dict(self.source.evidence)),
            ),
        )
        _validate_condition_target_sources(self)
        nested_target_blocked_reason = _payload_target_node_blocked_reason(self.payload)
        if self.coverage_status == "executable" and nested_target_blocked_reason:
            raise ValueError("executable condition cannot contain a blocked target")
        if self.coverage_status == "blocked" and nested_target_blocked_reason and self.blocked_reason != nested_target_blocked_reason:
            raise ValueError("blocked condition must retain its nested target reason")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "condition_id": self.condition_id,
            "opcode": self.opcode,
            "payload": _ir_json_value(self.payload),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "expression_schema_version": self.expression_schema_version,
            "blocked_reason": self.blocked_reason,
        }

    @classmethod
    def from_json(cls, value: object) -> "ConditionIR":
        if not isinstance(value, Mapping) or set(value) != {
            "condition_id",
            "opcode",
            "payload",
            "source",
            "coverage_status",
            "expression_schema_version",
            "blocked_reason",
        }:
            raise ValueError("condition JSON schema is invalid")
        source = _ir_source_from_json(value.get("source"))
        payload = value.get("payload")
        if not isinstance(payload, Mapping):
            raise TypeError("condition JSON payload must be an object")
        return cls(
            condition_id=_json_required_string(value, "condition_id"),
            opcode=_json_required_string(value, "opcode"),
            payload=_condition_payload_from_json(payload),
            source=source,
            coverage_status=cast(CoverageStatus, _json_required_string(value, "coverage_status")),
            expression_schema_version=_json_required_string(value, "expression_schema_version"),
            blocked_reason=_json_required_string(value, "blocked_reason"),
        )


def _condition_payload_from_json(value: Mapping[str, object]) -> Mapping[str, Any]:
    """Restore typed children embedded in a condition payload.

    Target predicates are allowed to contain target expressions.  Treating
    their serialized form as plain JSON preserves the bytes but loses the
    executable type contract, so decode only the exact tagged schemas here.
    """

    def decode(item: object) -> Any:
        if isinstance(item, Mapping):
            keys = set(item)
            if keys == {
                "schema_version", "node_id", "expression_kind", "source", "payload",
            }:
                return TargetExpressionNodeIR.from_json(item)
            if keys == {
                "condition_id", "opcode", "payload", "source", "coverage_status",
                "expression_schema_version", "blocked_reason",
            }:
                return ConditionIR.from_json(item)
            return {str(key): decode(child) for key, child in item.items()}
        if isinstance(item, list):
            return [decode(child) for child in item]
        return item

    return cast(Mapping[str, Any], decode(value))


def _ir_source_from_json(value: object) -> IRSource:
    if not isinstance(value, Mapping) or set(value) != {
        "source_path",
        "raw_type",
        "raw_id",
        "evidence",
    }:
        raise ValueError("IR source JSON schema is invalid")
    evidence = value.get("evidence")
    if not isinstance(evidence, Mapping):
        raise TypeError("IR source evidence must be an object")
    return IRSource(
        source_path=_json_required_string(value, "source_path"),
        raw_type=_json_required_string(value, "raw_type"),
        raw_id=_json_required_string(value, "raw_id"),
        evidence=cast(dict[str, JSONValue], freeze_json(dict(evidence))),
    )


def _json_required_string(value: Mapping[str, object], field_name: str) -> str:
    field_value = value.get(field_name)
    if not isinstance(field_value, str):
        raise TypeError(f"JSON field must be a string:{field_name}")
    return field_value


_TARGET_NODE_PAYLOAD_FIELDS: dict[str, frozenset[str]] = {
    "TargetAlias": frozenset({"alias"}),
    "TargetConcat": frozenset({"children"}),
    "TargetSequence": frozenset({"children"}),
    "TargetCompute": frozenset({"children", "compute_type"}),
    "TargetSelector": frozenset({"children", "predicate"}),
    "TargetFilter": frozenset({"candidate", "predicate"}),
    "Retarget": frozenset({"target", "predicate", "by_random", "max_number_expr", "include_limbo"}),
    "TargetQuery": frozenset({
        "entity_type_mask",
        "alive_state_mask",
        "target",
        "compare",
    }),
    "TargetFetchCaster": frozenset({"name", "unique_name"}),
    "TargetFetchModifierOwner": frozenset({"name", "unique_name"}),
    "TargetFetchOwner": frozenset({"name", "unique_name"}),
    "TargetFetchAbilityTarget": frozenset({"name", "unique_name"}),
    "TargetFetchCurrentActionTarget": frozenset({"name", "unique_name"}),
    "TargetFetchParamEntity": frozenset({"name", "unique_name"}),
    "TargetFetchParamEntityList": frozenset({"name", "unique_name"}),
    "TargetFetchTeamEntity": frozenset({"team_type"}),
    "TargetFetchBattleEventEntityList": frozenset(),
    "TargetFetchTurnOwnerEntity": frozenset(),
    "TargetFetchNone": frozenset(),
    "TargetFetchActualOwner": frozenset({"name", "unique_name"}),
    "TargetFetchPartner": frozenset({"name", "unique_name"}),
    "TargetFetchUniqueNameEntity": frozenset({"name", "unique_name"}),
    "TargetMapAdjoinEntity": frozenset({"side", "counting_option"}),
    "TargetMapSummoner": frozenset({"recursive"}),
    "TargetMapSummonedMinions": frozenset(),
    "TargetMapAllTeamMember": frozenset({"allow_unselectable"}),
    "TargetMapEnemyTeamEntity": frozenset(),
    "TargetRemoveUnselectable": frozenset(),
    "TargetFilterAliveState": frozenset({"alive_state_mask"}),
    "TargetFilterUnselectable": frozenset({"inverse"}),
    "TargetFilterEntityType": frozenset({"entity_type_mask", "inverse"}),
    "TargetFetchAllUnselectable": frozenset({"candidate"}),
    "TargetFetchAllCustomUnselectable": frozenset({"candidate"}),
    "TargetMapCreator": frozenset(),
    "TargetMapAllTeamMemberFromFirstEntity": frozenset({"select_enemy_team"}),
    "TargetReverse": frozenset(),
    "TargetShuffle": frozenset(),
    "TargetTake": frozenset({"count_expr"}),
    "TargetIndex": frozenset({"index_type", "index_expr"}),
    "TargetSortByProperty": frozenset({"sort_key", "highest_first"}),
    "TargetSortByPropertyRatio": frozenset({"sort_key", "highest_first"}),
    "TargetSortByFormation": frozenset({"sort_key", "highest_first"}),
    "TargetSortMonsterRank": frozenset({"highest_first", "max_rank"}),
    "TargetSortByModifierValue": frozenset({"modifier_name", "value_type", "highest_first"}),
    "TargetSortByModifierStatusCount": frozenset({"buff_status", "highest_first"}),
    "TargetSortByActionOrder": frozenset({"highest_first"}),
    "TargetPresentationOrderIgnored": frozenset({"original_kind", "presentation_key"}),
    "TargetUnsupported": frozenset({"original_kind", "blocked_reason"}),
}

_TARGET_SORT_PROPERTY_KEYS = frozenset({"CurrentHP", "MaxHP", "CurrentStance", "MaxStance", "Shield", "BreakDamageAddedRatio"})
_TARGET_SORT_RATIO_KEYS = frozenset({"HPRatio", "StanceRatio"})


def _target_node_source(source: IRSource) -> IRSource:
    if type(source) is not IRSource:
        raise TypeError("target node source must be exact IRSource")
    evidence = source.evidence
    if (
        not isinstance(source.source_path, str)
        or not source.source_path
        or not isinstance(source.raw_type, str)
        or not source.raw_type
        or not isinstance(source.raw_id, str)
        or not source.raw_id
        or not isinstance(evidence, Mapping)
        or not isinstance(evidence.get("json_path"), str)
        or not str(evidence["json_path"])
        or not str(evidence["json_path"]).startswith("$")
    ):
        raise ValueError("target node source requires a raw JSON path")
    return IRSource(
        source_path=source.source_path,
        raw_type=source.raw_type,
        raw_id=source.raw_id,
        evidence=cast(dict[str, JSONValue], freeze_json(dict(evidence))),
    )


def _target_node_stable_id(
    expression_kind: str,
    source: IRSource,
    payload: Mapping[str, Any],
) -> str:
    canonical = {
        "expression_kind": expression_kind,
        "source_path": source.source_path,
        "raw_type": source.raw_type,
        "raw_id": source.raw_id,
        "json_path": source.evidence["json_path"],
        "payload": _target_node_payload_json(payload),
    }
    encoded = json.dumps(canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"target_expression_node:{sha256(encoded).hexdigest()}"


def _target_node_payload_json(value: Any) -> JSONValue:
    if isinstance(value, TargetExpressionNodeIR):
        return value.to_json()
    if isinstance(value, ConditionIR):
        return value.to_json()
    if isinstance(value, Mapping):
        return {str(key): _target_node_payload_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_target_node_payload_json(item) for item in value]
    return _ir_json_value(value)


def _target_node_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return freeze_json(dict(value))
    return value


@dataclass(frozen=True)
class TargetExpressionNodeIR:
    node_id: str
    expression_kind: str
    source: IRSource
    payload: Mapping[str, Any]
    schema_version: str = "hsr.target_expression_node.v2"

    def __post_init__(self) -> None:
        if type(self) is not TargetExpressionNodeIR:
            raise TypeError("target expression node must not be subclassed")
        expected_fields = _TARGET_NODE_PAYLOAD_FIELDS.get(self.expression_kind)
        if expected_fields is None:
            raise ValueError(f"unknown target expression node kind:{self.expression_kind}")
        if self.schema_version != "hsr.target_expression_node.v2":
            raise ValueError("target expression node schema version is invalid")
        if not isinstance(self.payload, Mapping) or set(self.payload) != expected_fields:
            raise ValueError(f"target node payload schema is invalid:{self.expression_kind}")
        source = _target_node_source(self.source)
        payload = _validate_target_node_payload(self.expression_kind, self.payload)
        _validate_target_node_sources(self.expression_kind, source, payload)
        expected_id = _target_node_stable_id(self.expression_kind, source, payload)
        if self.node_id != expected_id:
            raise ValueError("target expression node identity does not close")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "payload", payload)

    @classmethod
    def build(
        cls,
        expression_kind: str,
        source: IRSource,
        payload: Mapping[str, Any],
    ) -> "TargetExpressionNodeIR":
        validated_source = _target_node_source(source)
        validated_payload = _validate_target_node_payload(expression_kind, payload)
        return cls(
            node_id=_target_node_stable_id(expression_kind, validated_source, validated_payload),
            expression_kind=expression_kind,
            source=validated_source,
            payload=validated_payload,
            schema_version="hsr.target_expression_node.v2",
        )

    @property
    def alias(self) -> str:
        return cast(str, self.payload.get("alias", ""))

    @property
    def children(self) -> tuple["TargetExpressionNodeIR", ...]:
        return cast(tuple["TargetExpressionNodeIR", ...], self.payload.get("children", ()))

    @property
    def candidate(self) -> "TargetExpressionNodeIR | None":
        return cast("TargetExpressionNodeIR | None", self.payload.get("candidate"))

    @property
    def predicate(self) -> ConditionIR | None:
        return cast(ConditionIR | None, self.payload.get("predicate"))

    @property
    def target(self) -> "TargetExpressionNodeIR | None":
        return cast("TargetExpressionNodeIR | None", self.payload.get("target"))

    @property
    def query_entity_type_mask(self) -> str:
        return cast(str, self.payload.get("entity_type_mask", ""))

    @property
    def query_alive_state_mask(self) -> str:
        return cast(str, self.payload.get("alive_state_mask", ""))

    @property
    def query_target(self) -> "TargetExpressionNodeIR | None":
        return cast("TargetExpressionNodeIR | None", self.payload.get("target"))

    @property
    def query_compare(self) -> "TargetExpressionNodeIR | None":
        return cast("TargetExpressionNodeIR | None", self.payload.get("compare"))

    @property
    def fetch_kind(self) -> str:
        return self.expression_kind if self.expression_kind.startswith("TargetFetch") else ""

    @property
    def unique_name(self) -> str:
        return cast(str, self.payload.get("unique_name", ""))

    @property
    def name(self) -> str:
        return cast(str, self.payload.get("name", ""))

    @property
    def team_type(self) -> str:
        return cast(str, self.payload.get("team_type", ""))

    @property
    def allow_unselectable(self) -> bool:
        return cast(bool, self.payload.get("allow_unselectable", False))

    @property
    def select_enemy_team(self) -> bool:
        return cast(bool, self.payload.get("select_enemy_team", False))

    @property
    def inverse(self) -> bool:
        return cast(bool, self.payload.get("inverse", False))

    @property
    def alive_state_mask(self) -> str:
        return cast(str, self.payload.get("alive_state_mask", ""))

    @property
    def max_rank(self) -> str:
        return cast(str, self.payload.get("max_rank", ""))

    @property
    def modifier_name(self) -> str:
        return cast(str, self.payload.get("modifier_name", ""))

    @property
    def value_type(self) -> str:
        return cast(str, self.payload.get("value_type", ""))

    @property
    def buff_status(self) -> str:
        return cast(str, self.payload.get("buff_status", ""))

    @property
    def adjacent_side(self) -> str:
        return cast(str, self.payload.get("side", ""))

    @property
    def adjacent_counting_option(self) -> str:
        return cast(str, self.payload.get("counting_option", ""))

    @property
    def recursive_summoner(self) -> bool:
        return cast(bool, self.payload.get("recursive", False))

    @property
    def by_random(self) -> bool:
        return cast(bool, self.payload.get("by_random", False))

    @property
    def include_limbo(self) -> bool:
        return cast(bool, self.payload.get("include_limbo", False))

    @property
    def max_number_expr(self) -> Mapping[str, JSONValue]:
        return cast(Mapping[str, JSONValue], self.payload.get("max_number_expr", {}))

    @property
    def count_expr(self) -> Mapping[str, JSONValue]:
        return cast(Mapping[str, JSONValue], self.payload.get("count_expr", {}))

    @property
    def index_type(self) -> str:
        return cast(str, self.payload.get("index_type", ""))

    @property
    def index_expr(self) -> Mapping[str, JSONValue]:
        return cast(Mapping[str, JSONValue], self.payload.get("index_expr", {}))

    @property
    def sort_kind(self) -> str:
        return self.expression_kind if self.expression_kind.startswith("TargetSort") else ""

    @property
    def sort_key(self) -> str:
        return cast(str, self.payload.get("sort_key", ""))

    @property
    def highest_first(self) -> bool:
        return cast(bool, self.payload.get("highest_first", False))

    @property
    def runtime_blocked_reason(self) -> str:
        return _target_node_blocked_reason(self)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "schema_version": self.schema_version,
            "node_id": self.node_id,
            "expression_kind": self.expression_kind,
            "source": self.source.to_json(),
            "payload": _target_node_payload_json(self.payload),
        }

    @classmethod
    def from_json(cls, value: object) -> "TargetExpressionNodeIR":
        if not isinstance(value, Mapping) or set(value) != {
            "schema_version",
            "node_id",
            "expression_kind",
            "source",
            "payload",
        }:
            raise ValueError("target expression node JSON schema is invalid")
        payload = _target_node_payload_from_json(
            _json_required_string(value, "expression_kind"),
            value.get("payload"),
        )
        return cls(
            node_id=_json_required_string(value, "node_id"),
            expression_kind=_json_required_string(value, "expression_kind"),
            source=_ir_source_from_json(value.get("source")),
            payload=payload,
            schema_version=_json_required_string(value, "schema_version"),
        )


def _validate_target_node_payload(
    expression_kind: str,
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    expected = _TARGET_NODE_PAYLOAD_FIELDS.get(expression_kind)
    if expected is None or set(payload) != expected:
        raise ValueError(f"target node payload schema is invalid:{expression_kind}")
    normalized: dict[str, Any] = {}
    for field_name, value in payload.items():
        if field_name == "children":
            if not isinstance(value, tuple) or not value or any(type(item) is not TargetExpressionNodeIR for item in value):
                raise TypeError("target node children must be a non-empty tuple of exact nodes")
            normalized[field_name] = value
        elif field_name in {"candidate", "target", "compare"}:
            if value is not None and type(value) is not TargetExpressionNodeIR:
                raise TypeError(f"target node {field_name} must be an exact node or null")
            normalized[field_name] = value
        elif field_name == "predicate":
            if value is not None and type(value) is not ConditionIR:
                raise TypeError("target predicate must be an exact ConditionIR or null")
            normalized[field_name] = value
        elif field_name in {"by_random", "highest_first", "recursive", "include_limbo", "allow_unselectable", "select_enemy_team", "inverse"}:
            if not isinstance(value, bool):
                raise TypeError(f"target node {field_name} must be boolean")
            normalized[field_name] = value
        elif field_name in {"max_number_expr", "count_expr", "index_expr"}:
            if not isinstance(value, Mapping):
                raise TypeError(f"target node {field_name} must be an object")
            numeric = dict(value)
            if numeric and not is_exact_numeric_expression(numeric):
                raise ValueError(f"target node {field_name} must be an exact numeric expression")
            normalized[field_name] = freeze_json(numeric)
        elif field_name in {
            "alias", "entity_type_mask", "alive_state_mask", "name", "unique_name",
            "side", "counting_option", "index_type", "sort_key", "team_type", "max_rank",
            "modifier_name", "value_type", "buff_status", "compute_type", "original_kind",
            "presentation_key", "blocked_reason",
        }:
            if not isinstance(value, str):
                raise TypeError(f"target node {field_name} must be a string")
            normalized[field_name] = value
        else:
            raise ValueError(f"unknown target node field:{field_name}")
    if expression_kind == "TargetAlias" and not normalized["alias"]:
        raise ValueError("target alias cannot be empty")
    if expression_kind == "TargetFilter" and normalized["predicate"] is None:
        raise ValueError("target filter requires a predicate")
    if expression_kind == "Retarget" and normalized["target"] is None:
        raise ValueError("retarget requires a target")
    if expression_kind == "TargetQuery" and (
        (normalized["target"] is None) != (normalized["compare"] is None)
    ):
        raise ValueError("target query comparison requires both sides")
    if expression_kind == "TargetQuery" and normalized["entity_type_mask"] != "Servant":
        raise ValueError("target query entity type is invalid")
    lifecycle_masks = {
        "Mask_AliveOnly", "Mask_AliveOrLimbo", "Mask_DiedButNotDispose", "Bit_Died", "Anyone",
    }
    if expression_kind in {"TargetQuery", "TargetFilterAliveState"} and normalized["alive_state_mask"] not in lifecycle_masks:
        raise ValueError("target lifecycle mask is invalid")
    if expression_kind == "TargetCompute" and normalized["compute_type"] != "Union":
        raise ValueError("target compute type is invalid")
    if expression_kind == "TargetSelector" and (
        len(normalized["children"]) != 2 or normalized["predicate"] is None
    ):
        raise ValueError("target selector requires one predicate and exactly two branches")
    if expression_kind == "TargetFilterEntityType" and normalized["entity_type_mask"] not in {
        "Servant", "BattleEvent",
    }:
        raise ValueError("target entity type mask is invalid")
    if expression_kind == "TargetMapAdjoinEntity" and normalized["side"] not in {
        "Both", "Left", "Right",
    }:
        raise ValueError("target adjacent side is invalid")
    if expression_kind == "TargetMapAdjoinEntity" and normalized["counting_option"] not in {
        "", "IgnoreServant",
    }:
        raise ValueError("target adjacent counting option is invalid")
    if expression_kind == "TargetFetchTeamEntity" and normalized["team_type"] not in {
        "TeamLight", "TeamDark",
    }:
        raise ValueError("target team entity type is invalid")
    if expression_kind == "TargetSortByProperty" and normalized["sort_key"] not in _TARGET_SORT_PROPERTY_KEYS:
        raise ValueError("target sort property is invalid")
    if expression_kind == "TargetSortByPropertyRatio" and normalized["sort_key"] not in _TARGET_SORT_RATIO_KEYS:
        raise ValueError("target sort ratio is invalid")
    if expression_kind == "TargetSortByFormation" and normalized["sort_key"] != "formation_position":
        raise ValueError("target formation sort key is invalid")
    if expression_kind == "TargetSortByModifierValue" and (
        not normalized["modifier_name"] or normalized["value_type"] not in {"", "Layer"}
    ):
        raise ValueError("target modifier value sort contract is invalid")
    if expression_kind == "TargetSortByModifierStatusCount" and normalized["buff_status"] not in {
        "Buff", "Debuff",
    }:
        raise ValueError("target modifier status sort contract is invalid")
    if expression_kind == "TargetPresentationOrderIgnored" and normalized["original_kind"] != (
        "TargetSortByCustomFormationIndexClientOnly"
    ):
        raise ValueError("target presentation-only operation is invalid")
    if expression_kind == "TargetPresentationOrderIgnored" and not normalized["presentation_key"]:
        raise ValueError("target presentation-only key is missing")
    if expression_kind == "TargetTake" and not normalized["count_expr"]:
        raise ValueError("target take requires a count")
    if expression_kind == "TargetTake" and not _target_numeric_expression_runtime_bound(
        normalized["count_expr"]
    ):
        raise ValueError("target take count must be runtime-bound")
    if expression_kind == "Retarget" and normalized["max_number_expr"] and not _target_numeric_expression_runtime_bound(
        normalized["max_number_expr"]
    ):
        raise ValueError("retarget maximum number must be runtime-bound")
    if expression_kind == "TargetIndex" and normalized["index_type"] not in {
        "First", "IndexStrict", "Last",
    }:
        raise ValueError("target index type is invalid")
    if expression_kind == "TargetIndex" and normalized["index_type"] in {"First", "Last"} and normalized["index_expr"]:
        raise ValueError("first and last target indexes cannot carry an index expression")
    if expression_kind == "TargetIndex" and normalized["index_type"] == "IndexStrict" and normalized["index_expr"] and not _target_numeric_expression_runtime_bound(
        normalized["index_expr"]
    ):
        raise ValueError("strict target index must be runtime-bound")
    fetch_reason = _target_fetch_payload_reason(expression_kind, normalized)
    if fetch_reason:
        raise ValueError(fetch_reason)
    if expression_kind == "TargetFetchUniqueNameEntity" and not normalized["unique_name"]:
        raise ValueError("unique target fetch requires a unique name")
    if expression_kind == "TargetUnsupported" and (
        not normalized["original_kind"] or not normalized["blocked_reason"]
    ):
        raise ValueError("blocked target node requires source kind and reason")
    return MappingProxyType(normalized)


def _target_numeric_expression_runtime_bound(value: Mapping[str, Any]) -> bool:
    if not is_exact_numeric_expression(dict(value)) or value.get("supported") is not True:
        return False
    kind = value.get("kind")
    return kind in {"fixed", "program"} or (kind == "dynamic_hash" and value.get("hash") is not None)


def _target_fetch_payload_reason(expression_kind: str, payload: Mapping[str, Any]) -> str:
    if not expression_kind.startswith("TargetFetch"):
        return ""
    name = cast(str, payload.get("name", ""))
    unique_name = cast(str, payload.get("unique_name", ""))
    if expression_kind == "TargetFetchPartner":
        return "target_fetch_partner_unique_name_unused" if unique_name else ""
    if expression_kind == "TargetFetchUniqueNameEntity":
        return "target_fetch_unique_name_name_unused" if name else ""
    if name:
        return "target_fetch_name_unused"
    if unique_name:
        return "target_fetch_unique_name_unused"
    return ""


def _source_descends_from(parent: IRSource, child: IRSource, suffixes: tuple[str, ...]) -> bool:
    parent_path = parent.evidence.get("json_path")
    child_path = child.evidence.get("json_path")
    if (
        child.source_path != parent.source_path
        or not isinstance(parent_path, str)
        or not isinstance(child_path, str)
        or not _json_path_descends_from(parent_path, child_path)
        or not child.raw_id.startswith(parent.raw_id + ":")
    ):
        return False
    relative_path = child_path[len(parent_path):]
    return any(_json_path_matches_field_prefix(relative_path, suffix) for suffix in suffixes)


def _json_path_descends_from(parent_path: str, child_path: str) -> bool:
    return child_path.startswith(parent_path) and len(child_path) > len(parent_path) and child_path[len(parent_path)] in ".["


def _json_path_matches_field_prefix(relative_path: str, field_prefix: str) -> bool:
    if field_prefix == ".":
        return relative_path.startswith((".", "["))
    if not relative_path.startswith(field_prefix):
        return False
    remaining = relative_path[len(field_prefix):]
    if field_prefix.endswith("["):
        index_end = remaining.find("]")
        return index_end > 0 and remaining[:index_end].isdigit() and len(remaining) == index_end + 1
    return not remaining


def _validate_target_node_sources(
    expression_kind: str,
    source: IRSource,
    payload: Mapping[str, Any],
) -> None:
    child_prefixes: tuple[str, ...] = ()
    children = cast(tuple[TargetExpressionNodeIR, ...], payload.get("children", ()))
    if expression_kind == "TargetConcat":
        child_prefixes = (".Targets[",)
    elif expression_kind == "TargetCompute":
        child_prefixes = (".Targets[",)
    elif expression_kind == "TargetSequence":
        child_prefixes = (".Sequence[",)
    elif expression_kind == "TargetSelector":
        child_prefixes = (".SuccTarget", ".FailTarget")
    for child in children:
        if not _source_descends_from(source, child.source, child_prefixes):
            raise ValueError("target child source does not close to its parent")

    child_specs: tuple[tuple[str, tuple[str, ...]], ...] = ()
    if expression_kind == "TargetFilter":
        child_specs = (("candidate", (".TargetType", ".Target", ".Targets")),)
    elif expression_kind == "Retarget":
        child_specs = (("target", (".TargetType",)),)
    elif expression_kind == "TargetQuery":
        child_specs = (
            ("target", (".Predicate.TargetType",)),
            ("compare", (".Predicate.CompareType",)),
        )
    for field_name, suffixes in child_specs:
        child = payload.get(field_name)
        if child is not None and not _source_descends_from(
            source, cast(TargetExpressionNodeIR, child).source, suffixes
        ):
            raise ValueError("target child source does not close to its parent")

    if expression_kind in {"TargetFilter", "Retarget", "TargetSelector"}:
        predicate = cast(ConditionIR | None, payload.get("predicate"))
        if predicate is not None:
            if not _source_descends_from(source, predicate.source, (".Predicate",)):
                raise ValueError("target predicate source does not close to its parent")
            _validate_condition_target_sources(predicate)


def _validate_condition_target_sources(condition: ConditionIR) -> None:
    parent_path = condition.source.evidence.get("json_path")
    if not isinstance(parent_path, str) or not parent_path.startswith("$"):
        if _condition_payload_contains_target(value=condition.payload):
            raise ValueError("nested condition target requires an exact parent source")
        return

    def source_closes(source: IRSource, expected_path: str) -> bool:
        return (
            source.source_path == condition.source.source_path
            and source.evidence.get("json_path") == expected_path
            and source.raw_id.startswith(condition.source.raw_id + ":")
        )

    def visit(value: object, expected_path: str) -> None:
        if type(value) is TargetExpressionNodeIR:
            if not source_closes(value.source, expected_path):
                raise ValueError("nested condition target source does not close")
            return
        if type(value) is ConditionIR:
            if not source_closes(value.source, expected_path):
                raise ValueError("nested condition source does not close")
            return
        if isinstance(value, Mapping):
            for key, child in value.items():
                if not isinstance(key, str):
                    raise TypeError("condition payload keys must be strings")
                visit(child, f"{expected_path}.{key}")
        elif isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                visit(child, f"{expected_path}[{index}]")

    visit(condition.payload, parent_path)


def _condition_payload_contains_target(*, value: object) -> bool:
    if type(value) in {TargetExpressionNodeIR, ConditionIR}:
        return True
    if isinstance(value, Mapping):
        return any(_condition_payload_contains_target(value=child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(_condition_payload_contains_target(value=child) for child in value)
    return False


def _target_node_blocked_reason(node: TargetExpressionNodeIR) -> str:
    if node.expression_kind == "TargetUnsupported":
        return cast(str, node.payload["blocked_reason"])
    if node.expression_kind == "TargetMapAdjoinEntity" and node.adjacent_counting_option not in {"", "IgnoreServant"}:
        return f"target_adjacent_counting_option_deferred_s5b:{node.adjacent_counting_option}"
    if node.expression_kind == "TargetQuery" and node.query_alive_state_mask not in {
        "", "Mask_AliveOnly", "Mask_AliveOrLimbo", "Mask_DiedButNotDispose", "Bit_Died", "Anyone",
    }:
        return f"target_query_alive_state_mask_deferred_s5b:{node.query_alive_state_mask}"
    for child in node.children:
        reason = _target_node_blocked_reason(child)
        if reason:
            return reason
    for child in (node.candidate, node.target, node.query_target, node.query_compare):
        if child is not None:
            reason = _target_node_blocked_reason(child)
            if reason:
                return reason
    if node.predicate is not None:
        if node.predicate.coverage_status != "executable":
            return node.predicate.blocked_reason or "target_predicate_not_executable"
        for value in node.predicate.payload.values():
            reason = _payload_target_node_blocked_reason(value)
            if reason:
                return reason
    return ""


def _payload_target_node_blocked_reason(value: object) -> str:
    if type(value) is TargetExpressionNodeIR:
        return _target_node_blocked_reason(value)
    if type(value) is ConditionIR:
        if value.coverage_status != "executable":
            return value.blocked_reason or "condition_not_executable"
        return _payload_target_node_blocked_reason(value.payload)
    if isinstance(value, Mapping):
        for child in value.values():
            reason = _payload_target_node_blocked_reason(child)
            if reason:
                return reason
    elif isinstance(value, (list, tuple)):
        for child in value:
            reason = _payload_target_node_blocked_reason(child)
            if reason:
                return reason
    return ""


def _target_node_payload_from_json(
    expression_kind: str,
    value: object,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("target node JSON payload must be an object")
    decoded: dict[str, Any] = {}
    for field_name, field_value in value.items():
        if field_name == "children":
            if not isinstance(field_value, list):
                raise TypeError("target node JSON children must be an array")
            decoded[field_name] = tuple(TargetExpressionNodeIR.from_json(item) for item in field_value)
        elif field_name in {"candidate", "target", "compare"}:
            decoded[field_name] = None if field_value is None else TargetExpressionNodeIR.from_json(field_value)
        elif field_name == "predicate":
            decoded[field_name] = None if field_value is None else ConditionIR.from_json(field_value)
        else:
            decoded[field_name] = field_value
    return _validate_target_node_payload(expression_kind, decoded)


@dataclass(frozen=True)
class TargetExpressionIR:
    target_expression_id: str
    expression_kind: str
    alias: str
    source: IRSource
    node: TargetExpressionNodeIR | None = None
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    admission_batch: str = ""
    runtime_scope: str = "effect_target"

    def __post_init__(self) -> None:
        if type(self) is not TargetExpressionIR:
            raise TypeError("target expression IR must not be subclassed")
        if not isinstance(self.target_expression_id, str) or not self.target_expression_id:
            raise ValueError("target expression identity is required")
        if not isinstance(self.expression_kind, str) or not self.expression_kind:
            raise ValueError("target expression kind is required")
        if not isinstance(self.alias, str):
            raise TypeError("target expression alias must be a string")
        source = _target_node_source(self.source)
        if self.node is not None and type(self.node) is not TargetExpressionNodeIR:
            raise TypeError("target expression node must be exact typed IR")
        if self.coverage_status not in {"executable", "blocked"}:
            raise ValueError("target expression coverage must be executable or blocked")
        if self.node is not None and (
            self.node.source.source_path != source.source_path
            or self.node.source.raw_id != source.raw_id
            or self.node.source.evidence.get("json_path") != source.evidence.get("json_path")
        ):
            raise ValueError("target expression root and node source do not close")
        node_blocked_reason = _target_node_blocked_reason(self.node) if self.node is not None else ""
        if self.coverage_status == "executable":
            if self.node is None or self.blocked_reason:
                raise ValueError("executable target expression must have an unblocked node")
            if self.node.expression_kind != self.expression_kind or node_blocked_reason:
                raise ValueError("executable target expression contains a blocked or mismatched node")
        elif self.coverage_status == "blocked":
            if not self.blocked_reason:
                raise ValueError("blocked target expression requires a reason")
            if node_blocked_reason and self.blocked_reason != node_blocked_reason:
                raise ValueError("blocked target expression must retain its node reason")
        elif self.blocked_reason:
            raise ValueError("non-blocked target expression cannot carry a block")
        object.__setattr__(self, "source", source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "target_expression_id": self.target_expression_id,
            "expression_kind": self.expression_kind,
            "alias": self.alias,
            "node": self.node.to_json() if self.node is not None else None,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "admission_batch": self.admission_batch,
            "runtime_scope": self.runtime_scope,
        }

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(self.to_json(), ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return sha256(encoded).hexdigest()

    @classmethod
    def from_json(cls, value: object) -> "TargetExpressionIR":
        if not isinstance(value, Mapping) or set(value) != {
            "target_expression_id",
            "expression_kind",
            "alias",
            "node",
            "source",
            "coverage_status",
            "blocked_reason",
            "admission_batch",
            "runtime_scope",
        }:
            raise ValueError("target expression JSON schema is invalid")
        node_value = value.get("node")
        return cls(
            target_expression_id=_json_required_string(value, "target_expression_id"),
            expression_kind=_json_required_string(value, "expression_kind"),
            alias=_json_required_string(value, "alias"),
            node=None if node_value is None else TargetExpressionNodeIR.from_json(node_value),
            source=_ir_source_from_json(value.get("source")),
            coverage_status=cast(CoverageStatus, _json_required_string(value, "coverage_status")),
            blocked_reason=_json_required_string(value, "blocked_reason"),
            admission_batch=_json_required_string(value, "admission_batch"),
            runtime_scope=_json_required_string(value, "runtime_scope"),
        )


@dataclass(frozen=True)
class EffectIR:
    effect_id: str
    opcode: str
    payload: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "unsupported"
    modifier_definition_id: str = ""
    status_callback_ids: tuple[str, ...] = ()
    ability_property_watcher_ids: tuple[str, ...] = ()
    source_mode: str = "unclassified"
    link_blocked_reason: str = ""
    owner_modifier_name: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "effect_id": self.effect_id,
            "opcode": self.opcode,
            "payload": self.payload,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "modifier_definition_id": self.modifier_definition_id,
            "status_callback_ids": list(self.status_callback_ids),
            "ability_property_watcher_ids": list(
                self.ability_property_watcher_ids
            ),
            "source_mode": self.source_mode,
            "link_blocked_reason": self.link_blocked_reason,
            "owner_modifier_name": self.owner_modifier_name,
        }


@dataclass(frozen=True)
class DamageModifierIR:
    damage_modifier_id: str
    callback_id: str
    source_task_id: str
    modifier_name: str
    event: str
    target_alias: str
    modifier_terms: tuple[dict[str, JSONValue], ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "damage_modifier_id": self.damage_modifier_id,
            "callback_id": self.callback_id,
            "source_task_id": self.source_task_id,
            "modifier_name": self.modifier_name,
            "event": self.event,
            "target_alias": self.target_alias,
            "modifier_terms": list(self.modifier_terms),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class TriggerIR:
    trigger_id: str
    event: str
    conditions: tuple[str, ...]
    effects: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "audit_only"
    modifier_name: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "trigger_id": self.trigger_id,
            "event": self.event,
            "conditions": list(self.conditions),
            "effects": list(self.effects),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "modifier_name": self.modifier_name,
        }


@dataclass(frozen=True)
class RuleEntity:
    entity_id: str
    entity_type: str
    fields: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "audit_only"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "fields": self.fields,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
        }


@dataclass(frozen=True)
class CombatantProfileIR:
    profile_id: str
    entity_id: str
    entity_type: str
    template_id: str
    base_stats: dict[str, JSONValue]
    toughness_profile: dict[str, JSONValue]
    weaknesses: tuple[str, ...]
    resistances: dict[str, JSONValue]
    source: IRSource
    status_resistance: JSONValue = None
    debuff_resistances: tuple[JSONValue, ...] = ()
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "profile_id": self.profile_id,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "template_id": self.template_id,
            "base_stats": self.base_stats,
            "toughness_profile": self.toughness_profile,
            "weaknesses": list(self.weaknesses),
            "resistances": self.resistances,
            "status_resistance": self.status_resistance,
            "debuff_resistances": list(self.debuff_resistances),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class AvatarPromotionTierIR:
    promotion_tier_id: str
    avatar_id: str
    promotion: int
    promotion_field_present: bool
    max_level: int
    hp_base: str
    hp_add: str
    attack_base: str
    attack_add: str
    defense_base: str
    defense_add: str
    speed_base: str
    critical_chance: str
    critical_damage: str
    base_aggro: str
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "promotion_tier_id": self.promotion_tier_id,
            "avatar_id": self.avatar_id,
            "promotion": self.promotion,
            "promotion_field_present": self.promotion_field_present,
            "max_level": self.max_level,
            "hp_base": self.hp_base,
            "hp_add": self.hp_add,
            "attack_base": self.attack_base,
            "attack_add": self.attack_add,
            "defense_base": self.defense_base,
            "defense_add": self.defense_add,
            "speed_base": self.speed_base,
            "critical_chance": self.critical_chance,
            "critical_damage": self.critical_damage,
            "base_aggro": self.base_aggro,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class SpecialResourceInitializerIR:
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
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "initializer_id": self.initializer_id,
            "maximum_value_dynamic_key": self.maximum_value_dynamic_key,
            "maximum_value_dynamic_hash": self.maximum_value_dynamic_hash,
            "level_dynamic_key": self.level_dynamic_key,
            "level_dynamic_hash": self.level_dynamic_hash,
            "zero_floor_dynamic_hash": self.zero_floor_dynamic_hash,
            "world_level_threshold": self.world_level_threshold,
            "low_world_level_expression": self.low_world_level_expression,
            "high_world_level_expression": self.high_world_level_expression,
            "minimum_expression": self.minimum_expression,
            "initial_current_expression": self.initial_current_expression,
            "initial_current_binding_hash": self.initial_current_binding_hash,
            "initial_current_binding_value": self.initial_current_binding_value,
            "level_source": self.level_source,
            "initial_current_trigger": self.initial_current_trigger,
            "sources": [source.to_json() for source in self.sources],
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class SpecialResourceDefinitionIR:
    resource_definition_id: str
    current_property: str
    maximum_property: str
    current_resource_key: str
    maximum_resource_key: str
    initial_current_mode: Literal["ability_battle_entry_initializer"]
    maximum_initialization_mode: Literal["ability_initializer"]
    initializer_task_names: tuple[str, ...]
    initializer: SpecialResourceInitializerIR | None
    supporting_sources: tuple[IRSource, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

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
            "initializer": self.initializer.to_json() if self.initializer else None,
            "supporting_sources": [source.to_json() for source in self.supporting_sources],
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class AvatarProfileIR:
    avatar_profile_id: str
    avatar_id: str
    base_type: str
    damage_type: str
    skill_ids: tuple[str, ...]
    promotion_tiers: tuple[AvatarPromotionTierIR, ...]
    max_energy: str | None
    max_energy_source: IRSource | None
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    resource_mode: Literal["standard_energy", "special_resource", "source_missing"] = "standard_energy"
    special_resource_source: IRSource | None = None
    special_resource_definition: SpecialResourceDefinitionIR | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "avatar_profile_id": self.avatar_profile_id,
            "avatar_id": self.avatar_id,
            "base_type": self.base_type,
            "damage_type": self.damage_type,
            "skill_ids": list(self.skill_ids),
            "promotion_tiers": [tier.to_json() for tier in self.promotion_tiers],
            "max_energy": self.max_energy,
            "max_energy_source": self.max_energy_source.to_json() if self.max_energy_source else None,
            "resource_mode": self.resource_mode,
            "special_resource_source": (
                self.special_resource_source.to_json() if self.special_resource_source else None
            ),
            "special_resource_definition": (
                self.special_resource_definition.to_json()
                if self.special_resource_definition is not None
                else None
            ),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class CharacterDataCardIR:
    card_id: str
    entity_ref: str
    profile_id: str
    skill_ids: tuple[str, ...]
    skill_formula_binding_ids: tuple[str, ...]
    bounce_policy_ids: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    schema_version: str = "v0_265"
    action_set: dict[str, JSONValue] = field(default_factory=dict)
    mechanism_slot_ids: tuple[str, ...] = ()
    trace_node_ids: tuple[str, ...] = ()
    eidolon_slot_ids: tuple[str, ...] = ()
    card_contract: dict[str, JSONValue] = field(default_factory=dict)
    dynamic_value_bindings: dict[str, JSONValue] = field(default_factory=dict)
    equipment_eligibility_id: str = ""
    ability_source_graph_refs: tuple[CharacterAbilityGraphRefIR, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("card_id", "entity_ref", "profile_id", "schema_version"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"character data card {field_name} is required")
        if not self.entity_ref.startswith("avatar:") or not self.entity_ref[7:]:
            raise ValueError("character data card entity_ref must identify an avatar")
        owner_avatar_id = self.entity_ref[7:]
        for field_name in (
            "skill_ids",
            "skill_formula_binding_ids",
            "bounce_policy_ids",
            "mechanism_slot_ids",
            "trace_node_ids",
            "eidolon_slot_ids",
        ):
            values = tuple(getattr(self, field_name))
            if any(not isinstance(value, str) or not value for value in values):
                raise TypeError(
                    f"character data card {field_name} must contain non-empty strings"
                )
            if len(values) != len(set(values)):
                raise ValueError(f"character data card {field_name} contains duplicates")
            object.__setattr__(self, field_name, values)
        refs = tuple(self.ability_source_graph_refs)
        if any(type(ref) is not CharacterAbilityGraphRefIR for ref in refs):
            raise TypeError(
                "character data card graph refs must be exact CharacterAbilityGraphRefIR values"
            )
        refs = tuple(sorted(refs, key=lambda ref: ref.graph_ref_id))
        if len({ref.graph_ref_id for ref in refs}) != len(refs):
            raise ValueError("character data card graph refs contain duplicate identities")
        if any(
            ref.character_data_card_id != self.card_id
            or ref.owner_avatar_id != owner_avatar_id
            for ref in refs
        ):
            raise ValueError("character data card graph ref ownership is inconsistent")
        if refs and sum(ref.reference_kind == "owned" for ref in refs) != 1:
            raise ValueError("character data card must reference exactly one owned graph")
        for field_name in (
            "action_set",
            "card_contract",
            "dynamic_value_bindings",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, Mapping):
                raise TypeError(f"character data card {field_name} must be a mapping")
            object.__setattr__(
                self,
                field_name,
                cast(dict[str, JSONValue], freeze_json(dict(value))),
            )
        object.__setattr__(self, "source", _immutable_character_ability_source(self.source))
        object.__setattr__(self, "ability_source_graph_refs", refs)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "card_id": self.card_id,
            "schema_version": self.schema_version,
            "entity_ref": self.entity_ref,
            "profile_id": self.profile_id,
            "skill_ids": list(self.skill_ids),
            "action_set": self.action_set,
            "skill_formula_binding_ids": list(self.skill_formula_binding_ids),
            "bounce_policy_ids": list(self.bounce_policy_ids),
            "mechanism_slot_ids": list(self.mechanism_slot_ids),
            "trace_node_ids": list(self.trace_node_ids),
            "eidolon_slot_ids": list(self.eidolon_slot_ids),
            "card_contract": self.card_contract,
            "dynamic_value_bindings": self.dynamic_value_bindings,
            "equipment_eligibility_id": self.equipment_eligibility_id,
            "ability_source_graph_refs": [
                ref.to_json() for ref in self.ability_source_graph_refs
            ],
            "source": _character_ability_source_json(self.source),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class MonsterDataCardIR:
    card_id: str
    entity_ref: str
    monster_id: str
    template_id: str
    rank: str
    profile_id: str
    action_set_id: str
    skill_ids: tuple[str, ...]
    skill_slots: tuple[dict[str, JSONValue], ...]
    ai_policy: dict[str, JSONValue]
    action_sequence: tuple[dict[str, JSONValue], ...]
    summon_refs: tuple[str, ...]
    raw_parameter_blocks: dict[str, JSONValue]
    card_contract: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    schema_version: str = "v0_277"
    display: dict[str, JSONValue] = field(default_factory=dict)
    passive_mechanism_slot_ids: tuple[str, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "card_id": self.card_id,
            "schema_version": self.schema_version,
            "entity_ref": self.entity_ref,
            "monster_id": self.monster_id,
            "template_id": self.template_id,
            "rank": self.rank,
            "display": self.display,
            "profile_id": self.profile_id,
            "action_set_id": self.action_set_id,
            "skill_ids": list(self.skill_ids),
            "skill_slots": [dict(slot) for slot in self.skill_slots],
            "ai_policy": self.ai_policy,
            "action_sequence": [dict(step) for step in self.action_sequence],
            "passive_mechanism_slot_ids": list(self.passive_mechanism_slot_ids),
            "summon_refs": list(self.summon_refs),
            "raw_parameter_blocks": self.raw_parameter_blocks,
            "card_contract": self.card_contract,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class SummonUnitDefinitionIR:
    summon_definition_id: str
    summon_unit_id: str
    summon_kind: str
    config_path: str
    unique_group: str
    max_summon_count: int | None
    destroy_on_enter_battle: bool | None
    remove_maze_buff_on_destroy: bool | None
    battle_admission: dict[str, JSONValue]
    skill_config: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    schema_version: str = "p1_3_summon_unit_definition_v1"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "summon_definition_id": self.summon_definition_id,
            "schema_version": self.schema_version,
            "summon_unit_id": self.summon_unit_id,
            "summon_kind": self.summon_kind,
            "config_path": self.config_path,
            "unique_group": self.unique_group,
            "max_summon_count": self.max_summon_count,
            "destroy_on_enter_battle": self.destroy_on_enter_battle,
            "remove_maze_buff_on_destroy": self.remove_maze_buff_on_destroy,
            "battle_admission": self.battle_admission,
            "skill_config": self.skill_config,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class UnitBirthTemplateIR:
    birth_template_id: str
    spawn_kind: Literal["summoned_monster", "servant", "wave_enemy"]
    entity_ref: str
    unit_field_specs: dict[str, JSONValue]
    flag_specs: dict[str, JSONValue]
    resource_specs: dict[str, JSONValue]
    request_contract: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    schema_version: str = "p6_unit_birth_template_v1"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "birth_template_id": self.birth_template_id,
            "schema_version": self.schema_version,
            "spawn_kind": self.spawn_kind,
            "entity_ref": self.entity_ref,
            "unit_field_specs": self.unit_field_specs,
            "flag_specs": self.flag_specs,
            "resource_specs": self.resource_specs,
            "request_contract": self.request_contract,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class SummonMonsterEntryIR:
    entry_id: str
    monster_entity_ref: str
    monster_raw_id: str
    position_policy: dict[str, JSONValue]
    count: int
    level_policy: dict[str, JSONValue]
    wave_clear_policy: Literal["counts", "ignore", "blocked"]
    source: IRSource
    birth_template_id: str = ""
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "entry_id": self.entry_id,
            "monster_entity_ref": self.monster_entity_ref,
            "monster_raw_id": self.monster_raw_id,
            "position_policy": self.position_policy,
            "count": self.count,
            "level_policy": self.level_policy,
            "wave_clear_policy": self.wave_clear_policy,
            "birth_template_id": self.birth_template_id,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class SummonMonsterIntentIR:
    summon_intent_id: str
    source_task_id: str
    owner_scope: str
    target_scope: str
    delay_policy: dict[str, JSONValue]
    entries: tuple[SummonMonsterEntryIR, ...]
    source_event: str
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    schema_version: str = "p1_3_summon_monster_intent_v1"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "summon_intent_id": self.summon_intent_id,
            "schema_version": self.schema_version,
            "source_task_id": self.source_task_id,
            "owner_scope": self.owner_scope,
            "target_scope": self.target_scope,
            "delay_policy": self.delay_policy,
            "entries": [entry.to_json() for entry in self.entries],
            "source_event": self.source_event,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class AssistantAbilityResolutionIR:
    assistant_resolution_id: str
    queue_intent_id: str
    assistant_ability_id: str
    owner_alias: str
    target_alias: str
    resolved_graph_id: str
    attribution_policy: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    schema_version: str = "p1_3_assistant_ability_resolution_v1"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "assistant_resolution_id": self.assistant_resolution_id,
            "schema_version": self.schema_version,
            "queue_intent_id": self.queue_intent_id,
            "assistant_ability_id": self.assistant_ability_id,
            "owner_alias": self.owner_alias,
            "target_alias": self.target_alias,
            "resolved_graph_id": self.resolved_graph_id,
            "attribution_policy": self.attribution_policy,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class ServantOwnerRelationIR:
    owner_relation_id: str
    owner_entity_ref: str
    owner_character_card_id: str
    auxiliary_skill_ids: tuple[str, ...]
    sources: tuple[IRSource, ...]
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "owner_relation_id": self.owner_relation_id,
            "owner_entity_ref": self.owner_entity_ref,
            "owner_character_card_id": self.owner_character_card_id,
            "auxiliary_skill_ids": list(self.auxiliary_skill_ids),
            "sources": [source.to_json() for source in self.sources],
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class ServantDefinitionIR:
    servant_definition_id: str
    servant_ref: str
    representation: Literal["unit", "component", "blocked"]
    ability_graph_ids: tuple[str, ...]
    action_set: dict[str, JSONValue]
    stat_source: dict[str, JSONValue]
    timeline_source: dict[str, JSONValue]
    lifecycle_source: dict[str, JSONValue]
    source: IRSource
    birth_template_id: str = ""
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    schema_version: str = "p1_3_servant_definition_v1"
    skill_ids: tuple[str, ...] = ()
    owner_relations: tuple[ServantOwnerRelationIR, ...] = ()
    spawn_sources: tuple[IRSource, ...] = ()

    @property
    def owner_entity_refs(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    relation.owner_entity_ref
                    for relation in self.owner_relations
                    if relation.coverage_status == "executable"
                    and relation.owner_entity_ref
                }
            )
        )

    def owner_relation_for(self, owner_entity_ref: str) -> ServantOwnerRelationIR | None:
        matches = tuple(
            relation
            for relation in self.owner_relations
            if relation.owner_entity_ref == owner_entity_ref
            and relation.coverage_status == "executable"
        )
        return matches[0] if len(matches) == 1 else None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "servant_definition_id": self.servant_definition_id,
            "schema_version": self.schema_version,
            "servant_ref": self.servant_ref,
            "owner_entity_refs": list(self.owner_entity_refs),
            "owner_relations": [relation.to_json() for relation in self.owner_relations],
            "skill_ids": list(self.skill_ids),
            "spawn_sources": [source.to_json() for source in self.spawn_sources],
            "representation": self.representation,
            "ability_graph_ids": list(self.ability_graph_ids),
            "action_set": self.action_set,
            "stat_source": self.stat_source,
            "timeline_source": self.timeline_source,
            "lifecycle_source": self.lifecycle_source,
            "birth_template_id": self.birth_template_id,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class CharacterBuildSelectorContextRefIR:
    scope_record_id: str
    family: Literal["TargetAlias"]
    json_path: str
    parent_branch_path: str
    source: IRSource

    def __post_init__(self) -> None:
        for field_name in (
            "scope_record_id",
            "family",
            "json_path",
            "parent_branch_path",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"character build selector context {field_name} is required"
                )
        if self.family != "TargetAlias":
            raise ValueError("selector context must be a TargetAlias record")
        source = _immutable_character_ability_source(self.source)
        evidence = source.evidence
        if (
            source.raw_id != self.scope_record_id
            or source.raw_type != self.family
            or evidence.get("json_path") != self.json_path
            or evidence.get("parent_branch_path") != self.parent_branch_path
            or not isinstance(
                evidence.get("inherited_scope_record_id"),
                str,
            )
        ):
            raise ValueError("selector context source identity is inconsistent")
        object.__setattr__(self, "source", source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "scope_record_id": self.scope_record_id,
            "family": self.family,
            "json_path": self.json_path,
            "parent_branch_path": self.parent_branch_path,
            "source": _character_ability_source_json(self.source),
        }


@dataclass(frozen=True)
class CharacterBuildSelectorRelationIR:
    selector_relation_id: str
    character_data_card_id: str
    owner_avatar_id: str
    selection_kind: CharacterBuildSelectionKind
    logical_selection_id: str
    selection_ref_ids: tuple[str, ...]
    selector_kind: CharacterBuildSelectorKind
    selector_key: str
    selector_hash: int | None
    selector_value_when_selected: bool
    selector_scope_record_id: str
    selector_projection_id: str
    source_id: str
    source_graph_id: str
    source_graph_ref_id: str
    location_kind: CharacterBuildSelectorLocationKind
    ability_definition_id: str
    ability_name: str
    source_content_sha256: str
    selector_json_path: str
    branch_kind: Literal[
        "explicit_task_branches",
        "predicate_gated_object",
        "predicate_context",
    ]
    branch_root_path: str
    true_subtree_path: str
    false_subtree_path: str
    selector_source: IRSource
    ability_definition_source: IRSource | None = None
    context_refs: tuple[CharacterBuildSelectorContextRefIR, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "selector_relation_id",
            "character_data_card_id",
            "owner_avatar_id",
            "logical_selection_id",
            "selector_scope_record_id",
            "selector_projection_id",
            "source_id",
            "source_graph_id",
            "source_graph_ref_id",
            "selector_json_path",
            "branch_root_path",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"character build selector {field_name} is required")
        _require_string_enum(
            self.selection_kind,
            frozenset({"trace", "eidolon"}),
            "character build selector selection kind",
        )
        _require_string_enum(
            self.selector_kind,
            frozenset({"skill_point", "rank"}),
            "character build selector kind",
        )
        _require_string_enum(
            self.location_kind,
            frozenset({"ability_definition", "source_root"}),
            "character build selector location kind",
        )
        _require_string_enum(
            self.branch_kind,
            frozenset(
                {
                    "explicit_task_branches",
                    "predicate_gated_object",
                    "predicate_context",
                }
            ),
            "character build selector branch kind",
        )
        selection_refs = _require_unique_strings(
            self.selection_ref_ids,
            "character build selector selection refs",
        )
        if not selection_refs:
            raise ValueError("character build selector requires a selection ref")
        if (self.selector_kind == "skill_point") != (
            self.selection_kind == "trace"
        ):
            raise ValueError("selector kind does not match its selection domain")
        if self.selector_kind == "skill_point":
            if not self.selector_key or self.selector_hash is not None:
                raise ValueError("skill-point selector identity is invalid")
        elif (
            self.selector_key
            or not isinstance(self.selector_hash, int)
            or isinstance(self.selector_hash, bool)
        ):
            raise ValueError("rank selector identity is invalid")
        if not isinstance(self.selector_value_when_selected, bool):
            raise TypeError("selector selected value must be boolean")
        if not _is_sha256(self.source_content_sha256):
            raise ValueError("selector source digest must be sha256")
        for path in (
            self.selector_json_path,
            self.branch_root_path,
            self.true_subtree_path,
            self.false_subtree_path,
        ):
            if path and not path.startswith("$"):
                raise ValueError("selector branch paths must be absolute JSON paths")
        if not self.selector_json_path.startswith(self.branch_root_path):
            raise ValueError("selector path is outside its branch root")
        if any(
            path and not path.startswith(self.branch_root_path)
            for path in (self.true_subtree_path, self.false_subtree_path)
        ):
            raise ValueError("selector subtree path is outside its branch root")
        selector_source = _immutable_character_ability_source(
            self.selector_source
        )
        evidence = selector_source.evidence
        expected_opcode = (
            "BySkillPointActivated"
            if self.selector_kind == "skill_point"
            else "ByRankActivated"
        )
        if (
            selector_source.raw_id != self.selector_scope_record_id
            or selector_source.raw_type != expected_opcode
            or evidence.get("json_path") != f"{self.selector_json_path}.$type"
            or evidence.get("avatar_id") != self.owner_avatar_id
            or evidence.get("selector_projection_id")
            != self.selector_projection_id
            or evidence.get("selector_kind") != self.selector_kind
            or evidence.get("selector_key")
            != (self.selector_key or None)
            or evidence.get("selector_hash") != self.selector_hash
            or evidence.get("source_content_sha256")
            != self.source_content_sha256
        ):
            raise ValueError("selector source identity is inconsistent")
        definition_source = (
            _immutable_character_ability_source(
                self.ability_definition_source
            )
            if self.ability_definition_source is not None
            else None
        )
        if self.location_kind == "ability_definition":
            if (
                not self.ability_definition_id
                or not self.ability_name
                or definition_source is None
                or definition_source.source_path != selector_source.source_path
                or not self.selector_json_path.startswith(
                    str(definition_source.evidence.get("json_path")) + "."
                )
            ):
                raise ValueError("selector ability definition closure is invalid")
        elif (
            self.ability_definition_id
            or self.ability_name
            or definition_source is not None
        ):
            raise ValueError("source-root selector cannot invent an ability definition")
        contexts = tuple(self.context_refs)
        if any(
            type(context) is not CharacterBuildSelectorContextRefIR
            for context in contexts
        ):
            raise TypeError("selector context refs contain an invalid value")
        if len({context.scope_record_id for context in contexts}) != len(contexts):
            raise ValueError("selector context refs contain duplicate identities")
        if any(
            context.source.source_path != selector_source.source_path
            or context.source.evidence.get("inherited_scope_record_id")
            != self.selector_scope_record_id
            for context in contexts
        ):
            raise ValueError("selector context refs are outside the selector source")
        object.__setattr__(self, "selection_ref_ids", selection_refs)
        object.__setattr__(self, "selector_source", selector_source)
        object.__setattr__(self, "ability_definition_source", definition_source)
        object.__setattr__(
            self,
            "context_refs",
            tuple(sorted(contexts, key=lambda item: item.scope_record_id)),
        )

    @property
    def selector_identity(self) -> tuple[object, ...]:
        return (
            self.owner_avatar_id,
            self.selector_kind,
            self.selector_key,
            self.selector_hash,
            self.selector_source.source_path,
            self.selector_json_path,
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "selector_relation_id": self.selector_relation_id,
            "character_data_card_id": self.character_data_card_id,
            "owner_avatar_id": self.owner_avatar_id,
            "selection_kind": self.selection_kind,
            "logical_selection_id": self.logical_selection_id,
            "selection_ref_ids": list(self.selection_ref_ids),
            "selector_kind": self.selector_kind,
            "selector_key": self.selector_key,
            "selector_hash": self.selector_hash,
            "selector_value_when_selected": self.selector_value_when_selected,
            "selector_scope_record_id": self.selector_scope_record_id,
            "selector_projection_id": self.selector_projection_id,
            "source_id": self.source_id,
            "source_graph_id": self.source_graph_id,
            "source_graph_ref_id": self.source_graph_ref_id,
            "location_kind": self.location_kind,
            "ability_definition_id": self.ability_definition_id,
            "ability_name": self.ability_name,
            "source_content_sha256": self.source_content_sha256,
            "selector_json_path": self.selector_json_path,
            "branch_kind": self.branch_kind,
            "branch_root_path": self.branch_root_path,
            "true_subtree_path": self.true_subtree_path,
            "false_subtree_path": self.false_subtree_path,
            "selector_source": _character_ability_source_json(
                self.selector_source
            ),
            "ability_definition_source": (
                _character_ability_source_json(self.ability_definition_source)
                if self.ability_definition_source is not None
                else None
            ),
            "context_refs": [item.to_json() for item in self.context_refs],
            "runtime_admission_status": "blocked",
        }


@dataclass(frozen=True)
class CharacterBuildSelectorGapIR:
    selector_gap_id: str
    character_data_card_id: str
    owner_avatar_id: str
    selector_kind: CharacterBuildSelectorKind
    selector_key: str
    selector_hash: int | None
    selector_scope_record_id: str
    selector_projection_id: str
    source_id: str
    source_graph_id: str
    source_content_sha256: str
    selector_json_path: str
    branch_root_path: str
    selector_source: IRSource
    gap_kind: CharacterBuildSelectorGapKind
    candidate_ref_ids: tuple[str, ...]
    blocked_reason: str
    context_refs: tuple[CharacterBuildSelectorContextRefIR, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "selector_gap_id",
            "owner_avatar_id",
            "selector_scope_record_id",
            "selector_projection_id",
            "selector_json_path",
            "branch_root_path",
            "blocked_reason",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"character selector gap {field_name} is required")
        if any(
            not isinstance(value, str)
            for value in (
                self.character_data_card_id,
                self.source_id,
                self.source_graph_id,
            )
        ):
            raise TypeError("character selector gap refs must be strings")
        _require_string_enum(
            self.selector_kind,
            frozenset({"skill_point", "rank"}),
            "character selector gap kind",
        )
        _require_string_enum(
            self.gap_kind,
            frozenset(
                {
                    "selection_missing",
                    "selection_ambiguous",
                    "cross_character",
                    "source_graph_missing",
                    "source_closure_mismatch",
                    "ability_definition_ambiguous",
                }
            ),
            "character selector gap classification",
        )
        if self.selector_kind == "skill_point":
            if not self.selector_key or self.selector_hash is not None:
                raise ValueError("skill-point selector gap identity is invalid")
        elif (
            self.selector_key
            or not isinstance(self.selector_hash, int)
            or isinstance(self.selector_hash, bool)
        ):
            raise ValueError("rank selector gap identity is invalid")
        if not _is_sha256(self.source_content_sha256):
            raise ValueError("selector gap source digest must be sha256")
        source = _immutable_character_ability_source(self.selector_source)
        expected_opcode = (
            "BySkillPointActivated"
            if self.selector_kind == "skill_point"
            else "ByRankActivated"
        )
        if (
            source.raw_id != self.selector_scope_record_id
            or source.raw_type != expected_opcode
            or source.evidence.get("json_path")
            != f"{self.selector_json_path}.$type"
            or source.evidence.get("avatar_id") != self.owner_avatar_id
            or source.evidence.get("selector_projection_id")
            != self.selector_projection_id
            or source.evidence.get("selector_kind") != self.selector_kind
            or source.evidence.get("selector_key")
            != (self.selector_key or None)
            or source.evidence.get("selector_hash") != self.selector_hash
            or source.evidence.get("source_content_sha256")
            != self.source_content_sha256
        ):
            raise ValueError("selector gap source identity is inconsistent")
        candidates = _require_unique_strings(
            self.candidate_ref_ids,
            "selector gap candidate refs",
        )
        contexts = tuple(self.context_refs)
        if any(
            type(context) is not CharacterBuildSelectorContextRefIR
            for context in contexts
        ):
            raise TypeError("selector gap context refs contain an invalid value")
        if len({context.scope_record_id for context in contexts}) != len(contexts):
            raise ValueError("selector gap context refs contain duplicate identities")
        if any(
            context.source.source_path != source.source_path
            or context.source.evidence.get("inherited_scope_record_id")
            != self.selector_scope_record_id
            for context in contexts
        ):
            raise ValueError("selector gap context refs are outside the selector source")
        if self.gap_kind in {
            "selection_ambiguous",
            "cross_character",
            "ability_definition_ambiguous",
        } and not candidates:
            raise ValueError("ambiguous selector gaps must retain candidates")
        if self.gap_kind not in {
            "source_graph_missing",
            "source_closure_mismatch",
        } and (not self.source_id or not self.source_graph_id):
            raise ValueError("selector selection gap requires S1 source closure")
        object.__setattr__(self, "selector_source", source)
        object.__setattr__(self, "candidate_ref_ids", candidates)
        object.__setattr__(
            self,
            "context_refs",
            tuple(sorted(contexts, key=lambda item: item.scope_record_id)),
        )

    @property
    def selector_identity(self) -> tuple[object, ...]:
        return (
            self.owner_avatar_id,
            self.selector_kind,
            self.selector_key,
            self.selector_hash,
            self.selector_source.source_path,
            self.selector_json_path,
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "selector_gap_id": self.selector_gap_id,
            "character_data_card_id": self.character_data_card_id,
            "owner_avatar_id": self.owner_avatar_id,
            "selector_kind": self.selector_kind,
            "selector_key": self.selector_key,
            "selector_hash": self.selector_hash,
            "selector_scope_record_id": self.selector_scope_record_id,
            "selector_projection_id": self.selector_projection_id,
            "source_id": self.source_id,
            "source_graph_id": self.source_graph_id,
            "source_content_sha256": self.source_content_sha256,
            "selector_json_path": self.selector_json_path,
            "branch_root_path": self.branch_root_path,
            "selector_source": _character_ability_source_json(
                self.selector_source
            ),
            "gap_kind": self.gap_kind,
            "candidate_ref_ids": list(self.candidate_ref_ids),
            "blocked_reason": self.blocked_reason,
            "context_refs": [item.to_json() for item in self.context_refs],
            "runtime_admission_status": "blocked",
        }


@dataclass(frozen=True)
class CharacterBuildBindingIR:
    build_binding_id: str
    character_data_card_id: str
    owner_avatar_id: str
    selection_kind: CharacterBuildSelectionKind
    selection_ref_id: str
    mechanism_slot_id: str
    projection_kind: CharacterBuildProjectionKind
    target_ref_id: str
    ordinal: int
    source: IRSource
    application_kind: str = ""
    property_type: str = ""
    exact_value: str = ""
    skill_level_change_kind: CharacterSkillLevelChangeKind = "none"
    skill_level_value: int = 0
    source_graph_ref_id: str = ""
    source_graph_id: str = ""
    ability_binding_id: str = ""
    ability_definition_id: str = ""
    relation_source: IRSource | None = None
    definition_source: IRSource | None = None
    candidate_ref_ids: tuple[str, ...] = ()
    runtime_admission_status: CharacterBuildRuntimeAdmissionStatus = "not_applicable"
    blocked_reason: str = ""
    dynamic_ref_kind: CharacterBuildDynamicRefKind = "none"

    def __post_init__(self) -> None:
        for field_name in (
            "build_binding_id",
            "character_data_card_id",
            "owner_avatar_id",
            "selection_ref_id",
            "mechanism_slot_id",
            "target_ref_id",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"character build binding {field_name} is required")
        _require_string_enum(
            self.selection_kind,
            frozenset({"trace", "eidolon"}),
            "character build selection kind",
        )
        _require_string_enum(
            self.projection_kind,
            frozenset(
                {
                    "static_contribution",
                    "resource_contribution",
                    "skill_level_change",
                    "dynamic_graph_ref",
                    "source_gap",
                }
            ),
            "character build projection kind",
        )
        _require_string_enum(
            self.skill_level_change_kind,
            frozenset({"base", "bonus", "none"}),
            "character skill level change kind",
        )
        _require_string_enum(
            self.runtime_admission_status,
            frozenset({"not_applicable", "blocked"}),
            "character build runtime admission status",
        )
        _require_string_enum(
            self.dynamic_ref_kind,
            frozenset({"none", "direct_ability"}),
            "character build dynamic ref kind",
        )
        if (
            not isinstance(self.ordinal, int)
            or isinstance(self.ordinal, bool)
            or self.ordinal < 0
        ):
            raise ValueError("character build binding ordinal is invalid")
        source = _immutable_character_ability_source(self.source)
        relation_source = (
            _immutable_character_ability_source(self.relation_source)
            if self.relation_source is not None
            else None
        )
        definition_source = (
            _immutable_character_ability_source(self.definition_source)
            if self.definition_source is not None
            else None
        )
        candidates = _require_unique_strings(
            self.candidate_ref_ids,
            "character build binding candidate refs",
        )
        graph_fields = (
            self.source_graph_ref_id,
            self.source_graph_id,
            self.ability_binding_id,
            self.ability_definition_id,
        )
        if (
            self.projection_kind != "dynamic_graph_ref"
            and self.dynamic_ref_kind != "none"
        ):
            raise ValueError("non-dynamic build binding cannot carry a dynamic ref")
        if self.projection_kind in {
            "static_contribution",
            "resource_contribution",
        }:
            if (
                not self.application_kind
                or not self.property_type
                or not self.exact_value
                or self.skill_level_change_kind != "none"
                or self.skill_level_value != 0
                or any(graph_fields)
                or relation_source is not None
                or definition_source is not None
                or candidates
                or self.runtime_admission_status != "not_applicable"
                or self.blocked_reason
            ):
                raise ValueError("static/resource character build binding is inconsistent")
            if (
                self.projection_kind == "resource_contribution"
            ) != (self.application_kind == "resource_delta"):
                raise ValueError("character build contribution channel is inconsistent")
        elif self.projection_kind == "skill_level_change":
            if (
                self.skill_level_change_kind not in {"base", "bonus"}
                or not isinstance(self.skill_level_value, int)
                or isinstance(self.skill_level_value, bool)
                or self.skill_level_value <= 0
                or self.application_kind
                or self.property_type
                or self.exact_value
                or any(graph_fields)
                or relation_source is not None
                or definition_source is not None
                or candidates
                or self.runtime_admission_status != "not_applicable"
                or self.blocked_reason
            ):
                raise ValueError("skill-level character build binding is inconsistent")
        elif self.projection_kind == "dynamic_graph_ref":
            if (
                self.dynamic_ref_kind == "none"
                or not self.source_graph_ref_id
                or not self.source_graph_id
                or relation_source is None
                or self.application_kind
                or self.property_type
                or self.exact_value
                or self.skill_level_change_kind != "none"
                or self.skill_level_value != 0
                or candidates
                or self.runtime_admission_status != "blocked"
                or not self.blocked_reason
            ):
                raise ValueError("dynamic character graph binding is inconsistent")
            if self.dynamic_ref_kind != "direct_ability" or (
                not self.ability_binding_id
                or not self.ability_definition_id
                or definition_source is None
            ):
                raise ValueError("direct ability build binding is incomplete")
        elif (
            any(graph_fields)
            or relation_source is not None
            or definition_source is not None
            or self.application_kind
            or self.property_type
            or self.exact_value
            or self.skill_level_change_kind != "none"
            or self.skill_level_value != 0
            or self.runtime_admission_status != "blocked"
            or not self.blocked_reason
        ):
            raise ValueError("source-gap character build binding is inconsistent")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "relation_source", relation_source)
        object.__setattr__(self, "definition_source", definition_source)
        object.__setattr__(self, "candidate_ref_ids", candidates)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "build_binding_id": self.build_binding_id,
            "character_data_card_id": self.character_data_card_id,
            "owner_avatar_id": self.owner_avatar_id,
            "selection_kind": self.selection_kind,
            "selection_ref_id": self.selection_ref_id,
            "mechanism_slot_id": self.mechanism_slot_id,
            "projection_kind": self.projection_kind,
            "target_ref_id": self.target_ref_id,
            "ordinal": self.ordinal,
            "application_kind": self.application_kind,
            "property_type": self.property_type,
            "exact_value": self.exact_value,
            "skill_level_change_kind": self.skill_level_change_kind,
            "skill_level_value": self.skill_level_value,
            "source_graph_ref_id": self.source_graph_ref_id,
            "source_graph_id": self.source_graph_id,
            "ability_binding_id": self.ability_binding_id,
            "ability_definition_id": self.ability_definition_id,
            "dynamic_ref_kind": self.dynamic_ref_kind,
            "relation_source": (
                _character_ability_source_json(self.relation_source)
                if self.relation_source is not None
                else None
            ),
            "definition_source": (
                _character_ability_source_json(self.definition_source)
                if self.definition_source is not None
                else None
            ),
            "candidate_ref_ids": list(self.candidate_ref_ids),
            "runtime_admission_status": self.runtime_admission_status,
            "blocked_reason": self.blocked_reason,
            "source": _character_ability_source_json(self.source),
        }


@dataclass(frozen=True)
class CharacterMechanismSlotIR:
    mechanism_slot_id: str
    character_data_card_id: str
    mechanism_kind: str
    runtime_system: str
    linked_ir_ids: dict[str, JSONValue]
    activation: dict[str, JSONValue]
    semantics: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "mechanism_slot_id": self.mechanism_slot_id,
            "character_data_card_id": self.character_data_card_id,
            "mechanism_kind": self.mechanism_kind,
            "runtime_system": self.runtime_system,
            "linked_ir_ids": self.linked_ir_ids,
            "activation": self.activation,
            "semantics": self.semantics,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class PassiveMechanismSlotIR:
    passive_slot_id: str
    data_card_id: str
    data_card_kind: str
    owner_entity_ref: str
    mechanism_kind: str
    runtime_system: str
    linked_ir_ids: dict[str, JSONValue]
    activation: dict[str, JSONValue]
    semantics: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "passive_slot_id": self.passive_slot_id,
            "data_card_id": self.data_card_id,
            "data_card_kind": self.data_card_kind,
            "owner_entity_ref": self.owner_entity_ref,
            "mechanism_kind": self.mechanism_kind,
            "runtime_system": self.runtime_system,
            "linked_ir_ids": self.linked_ir_ids,
            "activation": self.activation,
            "semantics": self.semantics,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class CharacterTraceNodeIR:
    trace_node_id: str
    character_data_card_id: str
    avatar_id: str
    trace_id: str
    trace_kind: str
    linked_mechanism_slot_ids: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    level: int = 1
    max_level: int = 1
    default_unlocked: bool = False
    required_promotion: int | None = None
    required_character_level: int | None = None
    prerequisite_trace_ids: tuple[str, ...] = ()
    level_up_skill_ids: tuple[str, ...] = ()
    extra_effect_ids: tuple[str, ...] = ()
    simple_extra_effect_ids: tuple[str, ...] = ()
    build_bindings: tuple[CharacterBuildBindingIR, ...] = ()

    def __post_init__(self) -> None:
        bindings = tuple(self.build_bindings)
        if any(type(binding) is not CharacterBuildBindingIR for binding in bindings):
            raise TypeError("character trace build bindings must be exact typed values")
        if len({binding.build_binding_id for binding in bindings}) != len(bindings):
            raise ValueError("character trace build bindings contain duplicate identities")
        if any(
            binding.character_data_card_id != self.character_data_card_id
            or binding.owner_avatar_id != self.avatar_id
            or binding.selection_kind != "trace"
            or binding.selection_ref_id != self.trace_node_id
            or binding.source != self.source
            for binding in bindings
        ):
            raise ValueError("character trace build binding ownership is inconsistent")
        object.__setattr__(
            self,
            "build_bindings",
            tuple(sorted(bindings, key=lambda binding: binding.build_binding_id)),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "trace_node_id": self.trace_node_id,
            "character_data_card_id": self.character_data_card_id,
            "avatar_id": self.avatar_id,
            "trace_id": self.trace_id,
            "trace_kind": self.trace_kind,
            "level": self.level,
            "max_level": self.max_level,
            "default_unlocked": self.default_unlocked,
            "required_promotion": self.required_promotion,
            "required_character_level": self.required_character_level,
            "prerequisite_trace_ids": list(self.prerequisite_trace_ids),
            "level_up_skill_ids": list(self.level_up_skill_ids),
            "extra_effect_ids": list(self.extra_effect_ids),
            "simple_extra_effect_ids": list(self.simple_extra_effect_ids),
            "build_bindings": [binding.to_json() for binding in self.build_bindings],
            "linked_mechanism_slot_ids": list(self.linked_mechanism_slot_ids),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class CharacterEidolonSlotIR:
    eidolon_slot_id: str
    character_data_card_id: str
    avatar_id: str
    rank: int
    rank_id: str
    linked_mechanism_slot_ids: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = "eidolon_interface_reserved_v0_265"
    activation: dict[str, JSONValue] = field(default_factory=dict)
    semantics: dict[str, JSONValue] = field(default_factory=dict)
    build_bindings: tuple[CharacterBuildBindingIR, ...] = ()

    def __post_init__(self) -> None:
        bindings = tuple(self.build_bindings)
        if any(type(binding) is not CharacterBuildBindingIR for binding in bindings):
            raise TypeError("character eidolon build bindings must be exact typed values")
        if len({binding.build_binding_id for binding in bindings}) != len(bindings):
            raise ValueError("character eidolon build bindings contain duplicate identities")
        if any(
            binding.character_data_card_id != self.character_data_card_id
            or binding.owner_avatar_id != self.avatar_id
            or binding.selection_kind != "eidolon"
            or binding.selection_ref_id != self.eidolon_slot_id
            or binding.source != self.source
            for binding in bindings
        ):
            raise ValueError("character eidolon build binding ownership is inconsistent")
        object.__setattr__(
            self,
            "build_bindings",
            tuple(sorted(bindings, key=lambda binding: binding.build_binding_id)),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "eidolon_slot_id": self.eidolon_slot_id,
            "character_data_card_id": self.character_data_card_id,
            "avatar_id": self.avatar_id,
            "rank": self.rank,
            "rank_id": self.rank_id,
            "linked_mechanism_slot_ids": list(self.linked_mechanism_slot_ids),
            "activation": self.activation,
            "semantics": self.semantics,
            "build_bindings": [binding.to_json() for binding in self.build_bindings],
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class BouncePolicyIR:
    bounce_policy_id: str
    character_data_card_id: str
    action_id: str
    level: int
    bounce_count: int
    initial_target_group: str
    bounce_target_group: str
    candidate_scope: str
    selection_strategy: str
    live_target_priority: bool
    continue_on_all_defeated: bool
    allow_repeat_after_all_hit: bool
    rng_source_kind: str
    random_selector_sources: tuple[IRSource, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        if type(self) is not BouncePolicyIR:
            raise TypeError("bounce policy must not be subclassed")
        required_identities = (
            self.bounce_policy_id,
            self.action_id,
            self.initial_target_group,
            self.bounce_target_group,
            self.candidate_scope,
            self.selection_strategy,
            self.rng_source_kind,
        )
        if any(not isinstance(value, str) or not value for value in required_identities):
            raise ValueError("bounce policy identity is incomplete")
        if type(self.level) is not int or self.level <= 0:
            raise ValueError("bounce policy level is invalid")
        if type(self.bounce_count) is not int or self.bounce_count < 0:
            raise ValueError("bounce policy count is invalid")
        if any(
            type(value) is not bool
            for value in (
                self.live_target_priority,
                self.continue_on_all_defeated,
                self.allow_repeat_after_all_hit,
            )
        ):
            raise TypeError("bounce policy switches must be booleans")
        if type(self.source) is not IRSource:
            raise TypeError("bounce policy requires an exact IR source")
        if not isinstance(self.random_selector_sources, tuple) or any(
            type(source) is not IRSource for source in self.random_selector_sources
        ):
            raise TypeError("bounce policy random selector sources must be exact")
        selector_sources = tuple(self.random_selector_sources)
        canonical_selector_sources = tuple(
            sorted(selector_sources, key=_bounce_selector_source_order_key)
        )
        selector_identities = tuple(
            (
                source.source_path,
                str(source.evidence.get("json_path") or ""),
                source.raw_id,
            )
            for source in selector_sources
        )
        if (
            len(selector_identities) != len(set(selector_identities))
            or selector_sources != canonical_selector_sources
            or any(
                source.raw_type != "RandomSelectInTargetList"
                or not isinstance(source.evidence.get("json_path"), str)
                or not source.evidence.get("json_path")
                for source in selector_sources
            )
        ):
            raise ValueError("bounce policy random selector source lineage is invalid")
        object.__setattr__(self, "random_selector_sources", selector_sources)
        if self.coverage_status == "executable":
            if self.blocked_reason:
                raise ValueError("executable bounce policy carries a blocker")
            if not self.character_data_card_id:
                raise ValueError("executable bounce policy requires an owner card")
            if self.bounce_count <= 0:
                raise ValueError("executable bounce policy requires positive hit count")
            if self.initial_target_group != "primary" or self.bounce_target_group != "bounce":
                raise ValueError("executable bounce policy target groups are invalid")
            if self.candidate_scope != "enemy_single":
                raise ValueError("executable bounce policy candidate scope is unsupported")
            if self.selection_strategy not in {
                "random_live_targets",
                "prefer_unhit_then_random",
            }:
                raise ValueError("executable bounce policy selection strategy is unsupported")
            if self.rng_source_kind != "battle_rng":
                raise ValueError("executable bounce policy RNG source is unsupported")
            if selector_sources and len(selector_sources) != self.bounce_count:
                raise ValueError("bounce policy random selector count is inconsistent")
        elif self.coverage_status == "blocked":
            if not self.blocked_reason:
                raise ValueError("blocked bounce policy requires a reason")
        else:
            raise ValueError("bounce policy coverage must be executable or blocked")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "bounce_policy_id": self.bounce_policy_id,
            "character_data_card_id": self.character_data_card_id,
            "action_id": self.action_id,
            "level": self.level,
            "bounce_count": self.bounce_count,
            "initial_target_group": self.initial_target_group,
            "bounce_target_group": self.bounce_target_group,
            "candidate_scope": self.candidate_scope,
            "selection_strategy": self.selection_strategy,
            "live_target_priority": self.live_target_priority,
            "continue_on_all_defeated": self.continue_on_all_defeated,
            "allow_repeat_after_all_hit": self.allow_repeat_after_all_hit,
            "rng_source_kind": self.rng_source_kind,
            "random_selector_sources": [
                source.to_json() for source in self.random_selector_sources
            ],
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


def _bounce_selector_source_order_key(
    source: IRSource,
) -> tuple[str, tuple[tuple[int, int | str], ...], str]:
    path = str(source.evidence.get("json_path") or "")
    segments = tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r"(\d+)", path)
        if part
    )
    return source.source_path, segments, source.raw_id


@dataclass(frozen=True)
class ActionPhaseStepIR:
    kind: str
    phase: str
    canonical_window: str = ""
    tbgd_event: str = ""
    requires_action_enabled: bool = True
    coverage_status: CoverageStatus = "audit_only"
    blocked_reason: str = ""
    source: IRSource | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "kind": self.kind,
            "phase": self.phase,
            "canonical_window": self.canonical_window,
            "tbgd_event": self.tbgd_event,
            "requires_action_enabled": self.requires_action_enabled,
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "source": self.source.to_json() if self.source else None,
        }


@dataclass(frozen=True)
class HitProfileIR:
    hit_profile_id: str
    action_id: str
    level: int
    hit_index: int
    target_group: str
    multiplier_expr: dict[str, JSONValue]
    multiplier_source: dict[str, JSONValue]
    stance_expr: dict[str, JSONValue]
    stance_source: dict[str, JSONValue]
    damage_formula_family: str
    element_type: str | None
    source: IRSource
    coverage_status: CoverageStatus = "audit_only"
    blocked_reason: str = ""
    numeric_fidelity_status: str = "structural_only"
    bounce_policy_id: str = ""
    target_selection_policy: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "hit_profile_id": self.hit_profile_id,
            "action_id": self.action_id,
            "level": self.level,
            "hit_index": self.hit_index,
            "target_group": self.target_group,
            "multiplier_expr": self.multiplier_expr,
            "multiplier_source": self.multiplier_source,
            "stance_expr": self.stance_expr,
            "stance_source": self.stance_source,
            "damage_formula_family": self.damage_formula_family,
            "element_type": self.element_type,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "numeric_fidelity_status": self.numeric_fidelity_status,
            "bounce_policy_id": self.bounce_policy_id,
            "target_selection_policy": self.target_selection_policy,
        }


@dataclass(frozen=True)
class SkillFormulaBindingIR:
    binding_id: str
    character_data_card_id: str
    formula_slot_id: str
    action_id: str
    level: int
    param_index: int
    sequence_order: int
    formula_role: str
    target_group_hint: str
    param_value: JSONValue
    scaling_basis_expr: dict[str, JSONValue]
    text_hash: str
    skill_text: str
    matched_text: str
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    bounce_policy_id: str = ""
    data_card_id: str = ""
    data_card_kind: str = ""
    owner_entity_ref: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "binding_id": self.binding_id,
            "character_data_card_id": self.character_data_card_id,
            "data_card_id": self.data_card_id or self.character_data_card_id,
            "data_card_kind": self.data_card_kind or ("character" if self.character_data_card_id else ""),
            "owner_entity_ref": self.owner_entity_ref,
            "formula_slot_id": self.formula_slot_id,
            "action_id": self.action_id,
            "level": self.level,
            "param_index": self.param_index,
            "sequence_order": self.sequence_order,
            "formula_role": self.formula_role,
            "target_group_hint": self.target_group_hint,
            "param_value": self.param_value,
            "scaling_basis_expr": self.scaling_basis_expr,
            "text_hash": self.text_hash,
            "skill_text": self.skill_text,
            "matched_text": self.matched_text,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "bounce_policy_id": self.bounce_policy_id,
        }


@dataclass(frozen=True)
class DamageEmissionIR:
    damage_emission_id: str
    action_id: str
    level: int
    phase_id: str
    source_task_id: str
    hit_profile_id: str
    target_group: str
    damage_formula_family: str
    element_type: str | None
    scaling_ratio_expr: dict[str, JSONValue]
    scaling_basis_expr: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    damage_custom_name: str = ""
    damage_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.damage_tags, (list, tuple))
            or not all(isinstance(tag, str) and tag for tag in self.damage_tags)
        ):
            raise TypeError("damage tags must be non-empty strings")
        tags = tuple(self.damage_tags)
        if len(tags) != len(set(tags)):
            raise ValueError("damage tags must be unique")
        object.__setattr__(self, "damage_tags", tags)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "damage_emission_id": self.damage_emission_id,
            "action_id": self.action_id,
            "level": self.level,
            "phase_id": self.phase_id,
            "source_task_id": self.source_task_id,
            "hit_profile_id": self.hit_profile_id,
            "target_group": self.target_group,
            "damage_formula_family": self.damage_formula_family,
            "element_type": self.element_type,
            "scaling_ratio_expr": self.scaling_ratio_expr,
            "scaling_basis_expr": self.scaling_basis_expr,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "damage_custom_name": self.damage_custom_name,
            "damage_tags": list(self.damage_tags),
        }


@dataclass(frozen=True)
class ToughnessEmissionIR:
    toughness_emission_id: str
    action_id: str
    level: int
    phase_id: str
    source_task_id: str
    hit_profile_id: str
    target_group: str
    element_type: str | None
    toughness_amount_expr: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "toughness_emission_id": self.toughness_emission_id,
            "action_id": self.action_id,
            "level": self.level,
            "phase_id": self.phase_id,
            "source_task_id": self.source_task_id,
            "hit_profile_id": self.hit_profile_id,
            "target_group": self.target_group,
            "element_type": self.element_type,
            "toughness_amount_expr": self.toughness_amount_expr,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class BreakBaseDamageIR:
    level: int
    break_base_damage: float
    hardness_base_damage: float | None
    source: IRSource
    coverage_status: CoverageStatus = "executable"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "level": self.level,
            "break_base_damage": self.break_base_damage,
            "hardness_base_damage": self.hardness_base_damage,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class BreakTemplateIR:
    template_id: str
    element_type: str | None
    task_names: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "template_id": self.template_id,
            "element_type": self.element_type,
            "task_names": list(self.task_names),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class BreakDamageEmissionIR:
    break_damage_emission_id: str
    template_id: str
    source_task_id: str
    element_type: str | None
    damage_formula_family: str
    scaling_expr: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "break_damage_emission_id": self.break_damage_emission_id,
            "template_id": self.template_id,
            "source_task_id": self.source_task_id,
            "element_type": self.element_type,
            "damage_formula_family": self.damage_formula_family,
            "scaling_expr": self.scaling_expr,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class BreakStatusEmissionIR:
    break_status_emission_id: str
    template_id: str
    source_task_id: str
    effect_id: str
    opcode: str
    target_alias: str | None
    modifier_name: str | None
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "break_status_emission_id": self.break_status_emission_id,
            "template_id": self.template_id,
            "source_task_id": self.source_task_id,
            "effect_id": self.effect_id,
            "opcode": self.opcode,
            "target_alias": self.target_alias,
            "modifier_name": self.modifier_name,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class StatusCallbackIR:
    callback_id: str
    modifier_name: str
    event: str
    task_ids: tuple[str, ...]
    source: IRSource
    execution_order: tuple[int, int]
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    scope_kind: str = "status_local"
    source_mode: str = "mainline"
    admission_status: CoverageStatus = "blocked"
    blocking_dependency: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "callback_id": self.callback_id,
            "modifier_name": self.modifier_name,
            "event": self.event,
            "task_ids": list(self.task_ids),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "scope_kind": self.scope_kind,
            "source_mode": self.source_mode,
            "admission_status": self.admission_status,
            "blocking_dependency": self.blocking_dependency,
            "execution_order": list(self.execution_order),
        }


@dataclass(frozen=True)
class StatusCallbackTaskIR:
    task_id: str
    callback_id: str
    modifier_name: str
    event: str
    task_index: int
    task_path: str
    branch: str
    opcode: str
    source: IRSource
    effect_id: str = ""
    condition_id: str = ""
    target_expression_id: str = ""
    parent_task_id: str = ""
    child_task_ids: tuple[str, ...] = ()
    success_task_ids: tuple[str, ...] = ()
    failed_task_ids: tuple[str, ...] = ()
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    task_payload: dict[str, JSONValue] = field(default_factory=dict)
    retarget_policy: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "task_id": self.task_id,
            "callback_id": self.callback_id,
            "modifier_name": self.modifier_name,
            "event": self.event,
            "task_index": self.task_index,
            "task_path": self.task_path,
            "branch": self.branch,
            "opcode": self.opcode,
            "effect_id": self.effect_id,
            "condition_id": self.condition_id,
            "target_expression_id": self.target_expression_id,
            "parent_task_id": self.parent_task_id,
            "child_task_ids": list(self.child_task_ids),
            "success_task_ids": list(self.success_task_ids),
            "failed_task_ids": list(self.failed_task_ids),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "task_payload": self.task_payload,
            "retarget_policy": self.retarget_policy,
        }


@dataclass(frozen=True)
class AbilityPropertyRangeIR:
    range_id: str
    watcher_id: str
    range_index: int
    minimum: dict[str, JSONValue] | None
    maximum: dict[str, JSONValue] | None
    minimum_inclusive: bool
    maximum_inclusive: bool
    enter_callback_id: str
    exit_callback_id: str
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "range_id": self.range_id,
            "watcher_id": self.watcher_id,
            "range_index": self.range_index,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "minimum_inclusive": self.minimum_inclusive,
            "maximum_inclusive": self.maximum_inclusive,
            "enter_callback_id": self.enter_callback_id,
            "exit_callback_id": self.exit_callback_id,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class AbilityPropertyWatcherIR:
    watcher_id: str
    modifier_name: str
    property_name: str
    range_ids: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "watcher_id": self.watcher_id,
            "modifier_name": self.modifier_name,
            "property_name": self.property_name,
            "range_ids": list(self.range_ids),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class StatusEventFamilyIR:
    status_event_family_id: str
    callback_event: str
    event_family: str
    default_scope_kind: str
    runtime_event_sources: tuple[str, ...]
    source_basis: str
    source: IRSource
    callback_count: int = 0
    executable_callback_count: int = 0
    blocked_callback_count: int = 0
    task_count: int = 0
    task_opcode_counts: dict[str, JSONValue] = field(default_factory=dict)
    source_mode_counts: dict[str, JSONValue] = field(default_factory=dict)
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    admission_status: CoverageStatus = "blocked"
    blocking_dependency: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "status_event_family_id": self.status_event_family_id,
            "callback_event": self.callback_event,
            "event_family": self.event_family,
            "default_scope_kind": self.default_scope_kind,
            "runtime_event_sources": list(self.runtime_event_sources),
            "source_basis": self.source_basis,
            "source": self.source.to_json(),
            "callback_count": self.callback_count,
            "executable_callback_count": self.executable_callback_count,
            "blocked_callback_count": self.blocked_callback_count,
            "task_count": self.task_count,
            "task_opcode_counts": dict(sorted(self.task_opcode_counts.items())),
            "source_mode_counts": dict(sorted(self.source_mode_counts.items())),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "admission_status": self.admission_status,
            "blocking_dependency": self.blocking_dependency,
        }


@dataclass(frozen=True)
class StatusDamageEmissionIR:
    status_damage_emission_id: str
    callback_id: str
    source_task_id: str
    modifier_name: str
    event: str
    attack_type: str
    damage_formula_family: str
    element_type: str | None
    scaling_expr: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "status_damage_emission_id": self.status_damage_emission_id,
            "callback_id": self.callback_id,
            "source_task_id": self.source_task_id,
            "modifier_name": self.modifier_name,
            "event": self.event,
            "attack_type": self.attack_type,
            "damage_formula_family": self.damage_formula_family,
            "element_type": self.element_type,
            "scaling_expr": self.scaling_expr,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class ActionDelayEmissionIR:
    action_delay_emission_id: str
    callback_id: str
    source_task_id: str
    modifier_name: str
    event: str
    opcode: str
    target_alias: str | None
    delay_mode: str
    delay_expr: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "action_delay_emission_id": self.action_delay_emission_id,
            "callback_id": self.callback_id,
            "source_task_id": self.source_task_id,
            "modifier_name": self.modifier_name,
            "event": self.event,
            "opcode": self.opcode,
            "target_alias": self.target_alias,
            "delay_mode": self.delay_mode,
            "delay_expr": self.delay_expr,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class QueueIntentIR:
    queue_intent_id: str
    source_task_id: str
    callback_id: str
    phase_id: str
    opcode: str
    queue_kind: str
    priority_source: dict[str, JSONValue]
    actor_target_alias: str | None
    action_ref_or_ability_name: str
    skill_index_expr: dict[str, JSONValue]
    ability_target_alias: str | None
    auto_cast: bool
    abort_policy: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "queue_intent_id": self.queue_intent_id,
            "source_task_id": self.source_task_id,
            "callback_id": self.callback_id,
            "phase_id": self.phase_id,
            "opcode": self.opcode,
            "queue_kind": self.queue_kind,
            "priority_source": self.priority_source,
            "actor_target_alias": self.actor_target_alias,
            "action_ref_or_ability_name": self.action_ref_or_ability_name,
            "skill_index_expr": self.skill_index_expr,
            "ability_target_alias": self.ability_target_alias,
            "auto_cast": self.auto_cast,
            "abort_policy": self.abort_policy,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class SuperBreakEmissionIR:
    super_break_emission_id: str
    template_id: str
    source_task_id: str
    target_alias: str | None
    attack_type: str
    damage_formula_family: str
    element_type: str | None
    scaling_expr: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "super_break_emission_id": self.super_break_emission_id,
            "template_id": self.template_id,
            "source_task_id": self.source_task_id,
            "target_alias": self.target_alias,
            "attack_type": self.attack_type,
            "damage_formula_family": self.damage_formula_family,
            "element_type": self.element_type,
            "scaling_expr": self.scaling_expr,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class QueueResolutionIR:
    queue_resolution_id: str
    queue_intent_id: str
    action_or_ability_ref: str
    resolved_kind: str
    resolved_ids: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "queue_resolution_id": self.queue_resolution_id,
            "queue_intent_id": self.queue_intent_id,
            "action_or_ability_ref": self.action_or_ability_ref,
            "resolved_kind": self.resolved_kind,
            "resolved_ids": self.resolved_ids,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class QueuePriorityIR:
    queue_priority_id: str
    priority_table: str
    priority_key: str
    priority_value: float
    source: IRSource
    coverage_status: CoverageStatus = "executable"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "queue_priority_id": self.queue_priority_id,
            "priority_table": self.priority_table,
            "priority_key": self.priority_key,
            "priority_value": self.priority_value,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class QueueWindowIR:
    queue_window_id: str
    queue_intent_id: str
    queue_kind: str
    window_family: str
    priority_key: str
    priority_value: float | None
    window_policy: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "queue_window_id": self.queue_window_id,
            "queue_intent_id": self.queue_intent_id,
            "queue_kind": self.queue_kind,
            "window_family": self.window_family,
            "priority_key": self.priority_key,
            "priority_value": self.priority_value,
            "window_policy": self.window_policy,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class QueueLifecyclePolicyIR:
    queue_lifecycle_policy_id: str
    queue_window_id: str
    queue_intent_id: str
    window_family: str
    lifecycle_policy: dict[str, JSONValue]
    source_basis: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "queue_lifecycle_policy_id": self.queue_lifecycle_policy_id,
            "queue_window_id": self.queue_window_id,
            "queue_intent_id": self.queue_intent_id,
            "window_family": self.window_family,
            "lifecycle_policy": self.lifecycle_policy,
            "source_basis": self.source_basis,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class ExtraActionPolicyIR:
    extra_action_policy_id: str
    queue_intent_id: str
    queue_window_id: str
    source_kind: str
    action_selection_kind: str
    allowed_action_kinds: tuple[str, ...]
    fixed_action_ref: str
    lifecycle_policy_id: str
    source_basis: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "extra_action_policy_id": self.extra_action_policy_id,
            "queue_intent_id": self.queue_intent_id,
            "queue_window_id": self.queue_window_id,
            "source_kind": self.source_kind,
            "action_selection_kind": self.action_selection_kind,
            "allowed_action_kinds": list(self.allowed_action_kinds),
            "fixed_action_ref": self.fixed_action_ref,
            "lifecycle_policy_id": self.lifecycle_policy_id,
            "source_basis": self.source_basis,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class StandaloneAbilityGraphIR:
    standalone_ability_graph_id: str
    ability_name: str
    source_mode: str
    phase_ids: tuple[str, ...]
    task_ids: tuple[str, ...]
    executable_task_ids: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    status_callback_ids: tuple[str, ...] = ()
    non_gameplay_callback_ids: tuple[str, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "standalone_ability_graph_id": self.standalone_ability_graph_id,
            "ability_name": self.ability_name,
            "source_mode": self.source_mode,
            "phase_ids": list(self.phase_ids),
            "task_ids": list(self.task_ids),
            "executable_task_ids": list(self.executable_task_ids),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "status_callback_ids": list(self.status_callback_ids),
            "non_gameplay_callback_ids": list(self.non_gameplay_callback_ids),
        }


@dataclass(frozen=True)
class ActionAdmissionIR:
    admission_id: str
    owner_entity_ref: str
    action_id: str
    action_level: int
    action_role: str
    submission_modes: tuple[str, ...]
    allowed_windows: tuple[str, ...]
    control_kind: str
    resource_gate_kind: str
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "admission_id": self.admission_id,
            "owner_entity_ref": self.owner_entity_ref,
            "action_id": self.action_id,
            "action_level": self.action_level,
            "action_role": self.action_role,
            "submission_modes": list(self.submission_modes),
            "allowed_windows": list(self.allowed_windows),
            "control_kind": self.control_kind,
            "resource_gate_kind": self.resource_gate_kind,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class CombatantActionSetIR:
    combatant_action_set_id: str
    entity_ref: str
    skill_index_map: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "combatant_action_set_id": self.combatant_action_set_id,
            "entity_ref": self.entity_ref,
            "skill_index_map": self.skill_index_map,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class AbilityPhaseIR:
    phase_id: str
    binding_id: str
    action_id: str
    level: int
    ability_name: str
    phase_index: int
    target_info: dict[str, JSONValue]
    opcode_summary: dict[str, JSONValue]
    callback_summaries: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "audit_only"
    blocked_reason: str = ""
    task_ids: tuple[str, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "phase_id": self.phase_id,
            "binding_id": self.binding_id,
            "action_id": self.action_id,
            "level": self.level,
            "ability_name": self.ability_name,
            "phase_index": self.phase_index,
            "target_info": self.target_info,
            "opcode_summary": self.opcode_summary,
            "callback_summaries": self.callback_summaries,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "task_ids": list(self.task_ids),
        }


@dataclass(frozen=True)
class AbilityTaskIR:
    task_id: str
    phase_id: str
    action_id: str
    level: int
    ability_name: str
    callback_kind: str
    task_index: int
    task_path: str
    branch: str
    opcode: str
    source: IRSource
    effect_id: str = ""
    condition_id: str = ""
    parent_task_id: str = ""
    child_task_ids: tuple[str, ...] = ()
    success_task_ids: tuple[str, ...] = ()
    failed_task_ids: tuple[str, ...] = ()
    repeat_count: int = 0
    execution_mode: Literal["runtime_effect", "process_only"] = "runtime_effect"
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    linked_standalone_graph_id: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "task_id": self.task_id,
            "phase_id": self.phase_id,
            "action_id": self.action_id,
            "level": self.level,
            "ability_name": self.ability_name,
            "callback_kind": self.callback_kind,
            "task_index": self.task_index,
            "task_path": self.task_path,
            "branch": self.branch,
            "opcode": self.opcode,
            "effect_id": self.effect_id,
            "condition_id": self.condition_id,
            "parent_task_id": self.parent_task_id,
            "child_task_ids": list(self.child_task_ids),
            "success_task_ids": list(self.success_task_ids),
            "failed_task_ids": list(self.failed_task_ids),
            "repeat_count": self.repeat_count,
            "execution_mode": self.execution_mode,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "linked_standalone_graph_id": self.linked_standalone_graph_id,
        }


@dataclass(frozen=True)
class ActionAbilityBindingIR:
    binding_id: str
    action_id: str
    level: int
    skill_trigger_key: str
    skill_name: str
    entry_ability: str
    ability_names: tuple[str, ...]
    config_source: dict[str, JSONValue]
    phase_ids: tuple[str, ...]
    source_mode: str
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "binding_id": self.binding_id,
            "action_id": self.action_id,
            "level": self.level,
            "skill_trigger_key": self.skill_trigger_key,
            "skill_name": self.skill_name,
            "entry_ability": self.entry_ability,
            "ability_names": list(self.ability_names),
            "config_source": self.config_source,
            "phase_ids": list(self.phase_ids),
            "source_mode": self.source_mode,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class ActionEventIR:
    action_event_id: str
    action_id: str
    level: int
    target_mode: str
    selection_mode: str
    phase_steps: tuple[ActionPhaseStepIR, ...]
    hit_profile_ids: tuple[str, ...]
    derived_status: str
    derived_reason: str
    source: IRSource
    coverage_status: CoverageStatus = "audit_only"
    blocked_reason: str = ""
    binding_id: str = ""
    phase_ids: tuple[str, ...] = ()
    source_mode: str = "derived"
    event_source_status: str = "derived_from_action_definition"
    target_relation: str = "unknown"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "action_event_id": self.action_event_id,
            "action_id": self.action_id,
            "level": self.level,
            "target_mode": self.target_mode,
            "selection_mode": self.selection_mode,
            "phase_steps": [step.to_json() for step in self.phase_steps],
            "hit_profile_ids": list(self.hit_profile_ids),
            "derived_status": self.derived_status,
            "derived_reason": self.derived_reason,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "binding_id": self.binding_id,
            "phase_ids": list(self.phase_ids),
            "source_mode": self.source_mode,
            "event_source_status": self.event_source_status,
            "target_relation": self.target_relation,
        }


@dataclass(frozen=True)
class ActionDefinitionIR:
    definition_id: str
    action_id: str
    level: int
    attack_type: str
    skill_effect: str
    target_mode: str
    bp_need: float
    bp_add: float
    sp_base: float
    sp_multiple_ratio: float
    param_list: tuple[JSONValue, ...]
    show_stance_list: tuple[JSONValue, ...]
    show_damage_list: tuple[JSONValue, ...]
    stance_damage_type: str | None
    source: IRSource
    coverage_status: CoverageStatus = "audit_only"
    damage_kind: str = "unknown"
    damage_formula_family: str = "unknown"
    element_type: str | None = None
    source_mode: str = "mainline"
    skill_trigger_key: str = ""
    target_relation: str = "unknown"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "definition_id": self.definition_id,
            "action_id": self.action_id,
            "level": self.level,
            "attack_type": self.attack_type,
            "skill_effect": self.skill_effect,
            "target_mode": self.target_mode,
            "bp_need": self.bp_need,
            "bp_add": self.bp_add,
            "sp_base": self.sp_base,
            "sp_multiple_ratio": self.sp_multiple_ratio,
            "param_list": list(self.param_list),
            "show_stance_list": list(self.show_stance_list),
            "show_damage_list": list(self.show_damage_list),
            "stance_damage_type": self.stance_damage_type,
            "damage_kind": self.damage_kind,
            "damage_formula_family": self.damage_formula_family,
            "element_type": self.element_type,
            "source_mode": self.source_mode,
            "skill_trigger_key": self.skill_trigger_key,
            "target_relation": self.target_relation,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
        }


@dataclass(frozen=True)
class SkillContinuationIR:
    continuation_id: str
    source_task_id: str
    phase_id: str
    action_id: str
    level: int
    ability_name: str
    opcode: str
    continuation_kind: str
    fixed_skill_type: str
    child_skill_index_expr: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "continuation_id": self.continuation_id,
            "source_task_id": self.source_task_id,
            "phase_id": self.phase_id,
            "action_id": self.action_id,
            "level": self.level,
            "ability_name": self.ability_name,
            "opcode": self.opcode,
            "continuation_kind": self.continuation_kind,
            "fixed_skill_type": self.fixed_skill_type,
            "child_skill_index_expr": self.child_skill_index_expr,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class TimelineRuleIR:
    timeline_rule_id: str
    base_action_gauge: float
    initial_action_value_rule: str
    turn_reset_rule: str
    source_kind: str
    source: IRSource
    coverage_status: CoverageStatus = "executable"
    blocked_reason: str = ""
    registry_version: str = ""
    applicability: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "timeline_rule_id": self.timeline_rule_id,
            "base_action_gauge": self.base_action_gauge,
            "initial_action_value_rule": self.initial_action_value_rule,
            "turn_reset_rule": self.turn_reset_rule,
            "source_kind": self.source_kind,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "registry_version": self.registry_version,
            "applicability": self.applicability,
        }


@dataclass(frozen=True)
class ResourceRuleIR:
    resource_rule_id: str
    rule_kind: str
    operation: str
    source_kind: str
    source: IRSource
    coverage_status: CoverageStatus = "executable"
    blocked_reason: str = ""
    registry_version: str = ""
    applicability: str = ""
    numeric_value: float | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "resource_rule_id": self.resource_rule_id,
            "rule_kind": self.rule_kind,
            "operation": self.operation,
            "source_kind": self.source_kind,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "registry_version": self.registry_version,
            "applicability": self.applicability,
            "numeric_value": self.numeric_value,
        }


@dataclass(frozen=True)
class BattleStateTransitionIR:
    """Source-backed transition for a shared battle-state event window."""

    transition_rule_id: str
    trigger_kind: str
    trigger_identity: str
    state_path: tuple[str, ...]
    before_value: JSONValue
    after_value: JSONValue
    runtime_event_type: str
    callback_event: str
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    allow_missing_before: bool = False

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "transition_rule_id": self.transition_rule_id,
            "trigger_kind": self.trigger_kind,
            "trigger_identity": self.trigger_identity,
            "state_path": list(self.state_path),
            "before_value": _ir_json_value(self.before_value),
            "after_value": _ir_json_value(self.after_value),
            "runtime_event_type": self.runtime_event_type,
            "callback_event": self.callback_event,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "allow_missing_before": self.allow_missing_before,
        }


@dataclass(frozen=True)
class DamageFormulaRuleIR:
    damage_formula_rule_id: str
    rule_kind: str
    operation: str
    numeric_parameters: dict[str, float]
    source_kind: str
    source: IRSource
    coverage_status: CoverageStatus = "executable"
    blocked_reason: str = ""
    registry_version: str = ""
    applicability: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "damage_formula_rule_id": self.damage_formula_rule_id,
            "rule_kind": self.rule_kind,
            "operation": self.operation,
            "numeric_parameters": self.numeric_parameters,
            "source_kind": self.source_kind,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "registry_version": self.registry_version,
            "applicability": self.applicability,
        }


@dataclass(frozen=True)
class DamageRouteRuleIR:
    damage_route_rule_id: str
    damage_family: str
    route_policy: str
    operation: str
    source_kind: str
    source: IRSource
    coverage_status: CoverageStatus = "executable"
    blocked_reason: str = ""
    registry_version: str = ""
    applicability: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "damage_route_rule_id": self.damage_route_rule_id,
            "damage_family": self.damage_family,
            "route_policy": self.route_policy,
            "operation": self.operation,
            "source_kind": self.source_kind,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "registry_version": self.registry_version,
            "applicability": self.applicability,
        }


@dataclass(frozen=True)
class ShieldPriorityRuleIR:
    shield_priority_rule_id: str
    operation: str
    source_kind: str
    source: IRSource
    coverage_status: CoverageStatus = "executable"
    blocked_reason: str = ""
    registry_version: str = ""
    applicability: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "shield_priority_rule_id": self.shield_priority_rule_id,
            "operation": self.operation,
            "source_kind": self.source_kind,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "registry_version": self.registry_version,
            "applicability": self.applicability,
        }


@dataclass(frozen=True)
class WaveMonsterEntryIR:
    entry_id: str
    stage_id: str
    wave_index: int
    position: int
    monster_entity_ref: str
    monster_raw_id: str
    source: IRSource
    birth_template_id: str = ""
    coverage_status: CoverageStatus = "executable"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "entry_id": self.entry_id,
            "stage_id": self.stage_id,
            "wave_index": self.wave_index,
            "position": self.position,
            "monster_entity_ref": self.monster_entity_ref,
            "monster_raw_id": self.monster_raw_id,
            "birth_template_id": self.birth_template_id,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class WaveDefinitionIR:
    wave_definition_id: str
    stage_id: str
    wave_count: int
    entries: tuple[WaveMonsterEntryIR, ...]
    stage_ability_refs: tuple[str, ...]
    source: IRSource
    level: int | None = None
    hard_level_group: int | None = None
    level_policy: dict[str, JSONValue] = field(default_factory=dict)
    coverage_status: CoverageStatus = "executable"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "wave_definition_id": self.wave_definition_id,
            "stage_id": self.stage_id,
            "wave_count": self.wave_count,
            "entries": [entry.to_json() for entry in self.entries],
            "stage_ability_refs": list(self.stage_ability_refs),
            "level": self.level,
            "hard_level_group": self.hard_level_group,
            "level_policy": self.level_policy,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class CanonicalIR:
    version: str
    entities: tuple[RuleEntity, ...] = ()
    avatar_profiles: tuple[AvatarProfileIR, ...] = ()
    character_data_cards: tuple[CharacterDataCardIR, ...] = ()
    monster_data_cards: tuple[MonsterDataCardIR, ...] = ()
    character_equipment_eligibilities: tuple[CharacterEquipmentEligibilityIR, ...] = ()
    light_cone_definitions: tuple[LightConeDefinitionIR, ...] = ()
    relic_domain_definitions: tuple[RelicDomainDefinitionIR, ...] = ()
    relic_slot_definitions: tuple[RelicSlotDefinitionIR, ...] = ()
    relic_main_affix_group_definitions: tuple[RelicMainAffixGroupDefinitionIR, ...] = ()
    relic_main_affix_definitions: tuple[RelicMainAffixDefinitionIR, ...] = ()
    relic_sub_affix_group_definitions: tuple[RelicSubAffixGroupDefinitionIR, ...] = ()
    relic_sub_affix_definitions: tuple[RelicSubAffixDefinitionIR, ...] = ()
    relic_template_definitions: tuple[RelicTemplateDefinitionIR, ...] = ()
    relic_set_definitions: tuple[RelicSetDefinitionIR, ...] = ()
    relic_set_thresholds: tuple[RelicSetThresholdIR, ...] = ()
    equipment_ability_parameter_reads: tuple[EquipmentAbilityParameterReadIR, ...] = ()
    equipment_mechanism_refs: tuple[EquipmentMechanismRefIR, ...] = ()
    summon_unit_definitions: tuple[SummonUnitDefinitionIR, ...] = ()
    unit_birth_templates: tuple[UnitBirthTemplateIR, ...] = ()
    summon_monster_intents: tuple[SummonMonsterIntentIR, ...] = ()
    assistant_ability_resolutions: tuple[AssistantAbilityResolutionIR, ...] = ()
    servant_definitions: tuple[ServantDefinitionIR, ...] = ()
    character_mechanism_slots: tuple[CharacterMechanismSlotIR, ...] = ()
    passive_mechanism_slots: tuple[PassiveMechanismSlotIR, ...] = ()
    character_trace_nodes: tuple[CharacterTraceNodeIR, ...] = ()
    character_eidolon_slots: tuple[CharacterEidolonSlotIR, ...] = ()
    character_build_selector_relations: tuple[
        CharacterBuildSelectorRelationIR, ...
    ] = ()
    character_build_selector_gaps: tuple[CharacterBuildSelectorGapIR, ...] = ()
    bounce_policies: tuple[BouncePolicyIR, ...] = ()
    combatant_profiles: tuple[CombatantProfileIR, ...] = ()
    action_definitions: tuple[ActionDefinitionIR, ...] = ()
    action_target_contract_catalog: ActionTargetContractCatalogIR | None = None
    action_ability_bindings: tuple[ActionAbilityBindingIR, ...] = ()
    ability_phases: tuple[AbilityPhaseIR, ...] = ()
    ability_tasks: tuple[AbilityTaskIR, ...] = ()
    task_graph_catalog: TaskGraphCatalogIR | None = None
    action_events: tuple[ActionEventIR, ...] = ()
    hit_profiles: tuple[HitProfileIR, ...] = ()
    skill_formula_bindings: tuple[SkillFormulaBindingIR, ...] = ()
    damage_emissions: tuple[DamageEmissionIR, ...] = ()
    damage_modifiers: tuple[DamageModifierIR, ...] = ()
    toughness_emissions: tuple[ToughnessEmissionIR, ...] = ()
    break_templates: tuple[BreakTemplateIR, ...] = ()
    break_base_damage: tuple[BreakBaseDamageIR, ...] = ()
    break_damage_emissions: tuple[BreakDamageEmissionIR, ...] = ()
    break_status_emissions: tuple[BreakStatusEmissionIR, ...] = ()
    status_event_families: tuple[StatusEventFamilyIR, ...] = ()
    status_callbacks: tuple[StatusCallbackIR, ...] = ()
    status_callback_tasks: tuple[StatusCallbackTaskIR, ...] = ()
    ability_property_watchers: tuple[AbilityPropertyWatcherIR, ...] = ()
    ability_property_ranges: tuple[AbilityPropertyRangeIR, ...] = ()
    status_damage_emissions: tuple[StatusDamageEmissionIR, ...] = ()
    action_delay_emissions: tuple[ActionDelayEmissionIR, ...] = ()
    queue_intents: tuple[QueueIntentIR, ...] = ()
    queue_resolutions: tuple[QueueResolutionIR, ...] = ()
    queue_priorities: tuple[QueuePriorityIR, ...] = ()
    queue_windows: tuple[QueueWindowIR, ...] = ()
    queue_lifecycle_policies: tuple[QueueLifecyclePolicyIR, ...] = ()
    extra_action_policies: tuple[ExtraActionPolicyIR, ...] = ()
    skill_continuations: tuple[SkillContinuationIR, ...] = ()
    standalone_ability_graphs: tuple[StandaloneAbilityGraphIR, ...] = ()
    combatant_action_sets: tuple[CombatantActionSetIR, ...] = ()
    action_admissions: tuple[ActionAdmissionIR, ...] = ()
    timeline_rules: tuple[TimelineRuleIR, ...] = ()
    resource_rules: tuple[ResourceRuleIR, ...] = ()
    battle_state_transitions: tuple[BattleStateTransitionIR, ...] = ()
    damage_formula_rules: tuple[DamageFormulaRuleIR, ...] = ()
    damage_route_rules: tuple[DamageRouteRuleIR, ...] = ()
    shield_priority_rules: tuple[ShieldPriorityRuleIR, ...] = ()
    super_break_emissions: tuple[SuperBreakEmissionIR, ...] = ()
    target_expressions: tuple[TargetExpressionIR, ...] = ()
    wave_definitions: tuple[WaveDefinitionIR, ...] = ()
    triggers: tuple[TriggerIR, ...] = ()
    effects: tuple[EffectIR, ...] = ()
    conditions: tuple[ConditionIR, ...] = ()
    formulas: tuple[FormulaIR, ...] = ()
    character_ability_source_graph_catalog: CharacterAbilitySourceGraphCatalogIR | None = None
    character_ability_source_resolution_catalog: CharacterAbilitySourceResolutionCatalogIR | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        target_catalog = self.action_target_contract_catalog
        if target_catalog is not None:
            from .action_target_contract import ActionTargetContractCatalogIR

            if type(target_catalog) is not ActionTargetContractCatalogIR:
                raise TypeError(
                    "CanonicalIR action target catalog must be the exact internal type"
                )
            definition_keys = tuple(
                (item.action_id, item.level) for item in self.action_definitions
            )
            if len(definition_keys) != len(set(definition_keys)):
                raise ValueError(
                    "CanonicalIR action definitions conflict with the target catalog"
                )
            contract_keys = tuple(
                (item.action_id, item.level) for item in target_catalog.contracts
            )
            if set(contract_keys) != set(definition_keys):
                raise ValueError(
                    "CanonicalIR action target catalog does not cover its definitions"
                )
            definitions_by_key = {
                (item.action_id, item.level): item for item in self.action_definitions
            }
            if any(
                definitions_by_key[(item.action_id, item.level)].definition_id
                != item.definition_id
                for item in target_catalog.contracts
            ):
                raise ValueError(
                    "CanonicalIR action target catalog definition identity mismatch"
                )
        relations = tuple(self.character_build_selector_relations)
        gaps = tuple(self.character_build_selector_gaps)
        if any(type(item) is not CharacterBuildSelectorRelationIR for item in relations):
            raise TypeError("CanonicalIR selector relations must be exact typed values")
        if any(type(item) is not CharacterBuildSelectorGapIR for item in gaps):
            raise TypeError("CanonicalIR selector gaps must be exact typed values")
        relations = tuple(replace(item) for item in relations)
        gaps = tuple(replace(item) for item in gaps)
        relation_ids = tuple(item.selector_relation_id for item in relations)
        gap_ids = tuple(item.selector_gap_id for item in gaps)
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("CanonicalIR selector relation identities must be unique")
        if len(gap_ids) != len(set(gap_ids)):
            raise ValueError("CanonicalIR selector gap identities must be unique")
        selector_identities = tuple(
            item.selector_identity for item in (*relations, *gaps)
        )
        if len(selector_identities) != len(set(selector_identities)):
            raise ValueError("CanonicalIR selector source identities must be unique")
        object.__setattr__(
            self,
            "character_build_selector_relations",
            tuple(sorted(relations, key=lambda item: item.selector_relation_id)),
        )
        object.__setattr__(
            self,
            "character_build_selector_gaps",
            tuple(sorted(gaps, key=lambda item: item.selector_gap_id)),
        )
        task_graph_catalog = self.task_graph_catalog
        if task_graph_catalog is not None:
            from .task_graph import TaskGraphCatalogIR

            if type(task_graph_catalog) is not TaskGraphCatalogIR:
                raise TypeError("CanonicalIR task graph catalog must be the exact internal type")
            ability_tasks = {item.task_id: item for item in self.ability_tasks}
            status_tasks = {item.task_id: item for item in self.status_callback_tasks}
            if len(ability_tasks) != len(self.ability_tasks) or len(status_tasks) != len(self.status_callback_tasks):
                raise ValueError("CanonicalIR formal task identities must be unique")
            phases = {item.phase_id: item for item in self.ability_phases}
            callbacks = {item.callback_id: item for item in self.status_callbacks}
            if len(phases) != len(self.ability_phases) or len(callbacks) != len(self.status_callbacks):
                raise ValueError("CanonicalIR task graph owners must be unique")
            reference_definitions = {
                "condition": {item.condition_id: item for item in self.conditions},
                "target": {
                    item.target_expression_id: item for item in self.target_expressions
                },
                "effect": {item.effect_id: item for item in self.effects},
                "ability": {
                    item.standalone_ability_graph_id: item
                    for item in self.standalone_ability_graphs
                },
            }
            if any(
                len(reference_definitions[kind]) != len(values)
                for kind, values in (
                    ("condition", self.conditions),
                    ("target", self.target_expressions),
                    ("effect", self.effects),
                    ("ability", self.standalone_ability_graphs),
                )
            ):
                raise ValueError("CanonicalIR task graph definitions must be unique")
            for entry in task_graph_catalog.entry_materializations:
                if entry.entry_kind == "ability_phase_callback":
                    owner = phases.get(entry.owner_id)
                    selected_tasks = ability_tasks
                    if owner is None:
                        raise ValueError("task graph ability phase owner is missing")
                    formal_tasks = tuple(
                        item
                        for item in self.ability_tasks
                        if item.phase_id == entry.owner_id
                        and item.callback_kind == entry.callback_kind
                    )
                    selected_task_ids = {
                        item.task_id for item in formal_tasks
                    }
                    ordered_task_ids = tuple(
                        task_id
                        for task_id in owner.task_ids
                        if task_id in selected_task_ids
                    )
                else:
                    owner = callbacks.get(entry.owner_id)
                    selected_tasks = status_tasks
                    if owner is None:
                        raise ValueError("task graph status callback owner is missing")
                    if owner.event != entry.callback_kind:
                        raise ValueError("task graph status callback event is inconsistent")
                    formal_tasks = tuple(
                        item
                        for item in self.status_callback_tasks
                        if item.callback_id == entry.owner_id
                    )
                    selected_task_ids = {
                        item.task_id for item in formal_tasks
                    }
                    ordered_task_ids = tuple(owner.task_ids)
                if (
                    not formal_tasks
                    or len(ordered_task_ids) != len(formal_tasks)
                    or set(ordered_task_ids) != selected_task_ids
                ):
                    raise ValueError("task graph formal owner ledger is incomplete")
                if entry.status != "materialized":
                    continue
                graph = next(
                    (item for item in task_graph_catalog.graphs if item.graph_id == entry.graph_id),
                    None,
                )
                if graph is None:
                    raise ValueError("task graph materialization graph is missing")
                nodes_by_task = {
                    item.formal_task_id: item for item in graph.nodes
                }
                if (
                    len(nodes_by_task) != len(graph.nodes)
                    or set(nodes_by_task) != selected_task_ids
                    or entry.formal_task_ids != ordered_task_ids
                    or entry.source_occurrence_ids
                    != tuple(
                        nodes_by_task[task_id].source_occurrence_id
                        for task_id in ordered_task_ids
                    )
                ):
                    raise ValueError("task graph formal materialization scope is inconsistent")
                first_node = nodes_by_task[ordered_task_ids[0]]
                if graph.source != first_node.source or entry.source != first_node.source:
                    raise ValueError("task graph entry source is inconsistent")
                expected_roots = tuple(
                    nodes_by_task[task_id].graph_node_id
                    for task_id in ordered_task_ids
                    if not selected_tasks[task_id].parent_task_id
                )
                if graph.root_node_ids != expected_roots:
                    raise ValueError("task graph formal roots are inconsistent")
                for node in graph.nodes:
                    task = selected_tasks.get(node.formal_task_id)
                    if (
                        task is None
                        or node.formal_task_id not in selected_task_ids
                        or task.opcode != node.opcode
                        or task.source.source_path != node.source.source_path
                        or task.source.raw_type != node.source.raw_type
                        or task.source.raw_id != node.source.raw_id
                        or task.source.evidence.get("json_path")
                        != node.source.evidence.get("json_path")
                    ):
                        raise ValueError("task graph formal task source is inconsistent")
                    child_node_ids = tuple(
                        child_id
                        for branch in node.branches
                        for child_id in branch.child_node_ids
                    )
                    expected_child_node_ids = tuple(
                        nodes_by_task[task_id].graph_node_id
                        for task_id in task.child_task_ids
                    )
                    if child_node_ids != expected_child_node_ids:
                        raise ValueError("task graph formal child topology is inconsistent")
                    for branch_kind, task_ids in (
                        ("success", task.success_task_ids),
                        ("failed", task.failed_task_ids),
                    ):
                        branch_node_ids = tuple(
                            child_id
                            for branch in node.branches
                            if branch.branch_kind == branch_kind
                            for child_id in branch.child_node_ids
                        )
                        if branch_node_ids != tuple(
                            nodes_by_task[task_id].graph_node_id
                            for task_id in task_ids
                        ):
                            raise ValueError("task graph formal branch topology is inconsistent")
                    expected_references = {
                        "condition": task.condition_id,
                        "target": getattr(task, "target_expression_id", ""),
                        "effect": task.effect_id,
                        "ability": getattr(task, "linked_standalone_graph_id", ""),
                    }
                    formal_source_family = task.source.evidence.get(
                        "source_opcode"
                        if entry.entry_kind == "ability_phase_callback"
                        else "raw_opcode"
                    )
                    if formal_source_family != node.source_family:
                        raise ValueError("task graph formal source family is inconsistent")
                    actual_references = {
                        kind: tuple(
                            reference.definition_id
                            for reference in node.references
                            if reference.reference_kind == kind
                        )
                        for kind in expected_references
                    }
                    if any(
                        actual_references[kind]
                        != ((definition_id,) if definition_id else ())
                        for kind, definition_id in expected_references.items()
                    ):
                        raise ValueError("task graph formal definition references are inconsistent")
                    for reference in node.references:
                        if reference.reference_kind in {"numeric", "template"}:
                            continue
                        definition = reference_definitions[reference.reference_kind].get(
                            reference.definition_id
                        )
                        if definition is None:
                            raise ValueError("task graph definition reference is dangling")
                        admitted = getattr(definition, "coverage_status", "blocked") in {
                            "executable",
                            "lowered",
                        }
                        if admitted != (reference.resolution_status == "resolved"):
                            raise ValueError(
                                "task graph definition admission is inconsistent"
                            )
        catalog = self.character_ability_source_graph_catalog
        resolution_catalog = self.character_ability_source_resolution_catalog
        if resolution_catalog is not None and (
            type(resolution_catalog) is not CharacterAbilitySourceResolutionCatalogIR
            or catalog is None
            or resolution_catalog.source_graph_catalog_id != catalog.catalog_id
            or resolution_catalog.scope_catalog_id != catalog.scope_catalog_id
            or resolution_catalog.source_fingerprint != catalog.source_fingerprint
        ):
            raise ValueError(
                "CanonicalIR character ability source resolution is inconsistent"
            )
        if catalog is None:
            if relations or gaps:
                raise ValueError("selector ledger requires the S1 source graph catalog")
            return
        if type(catalog) is not CharacterAbilitySourceGraphCatalogIR:
            raise TypeError(
                "CanonicalIR character ability source catalog must be the exact internal type"
            )
        if target_catalog is not None and (
            target_catalog.source_graph_catalog_id != catalog.catalog_id
            or target_catalog.source_graph_fingerprint != catalog.source_fingerprint
        ):
            raise ValueError(
                "CanonicalIR action target catalog source graph mismatch"
            )
        cards = tuple(self.character_data_cards)
        if any(type(card) is not CharacterDataCardIR for card in cards):
            raise TypeError(
                "CanonicalIR character data cards must be exact CharacterDataCardIR values"
            )
        graphs_by_id = {graph.graph_id: graph for graph in catalog.graphs}
        sources_by_id = {source.source_id: source for source in catalog.sources}
        definitions_by_id = {
            definition.definition_id: definition
            for definition in catalog.definitions
        }
        owned_graphs_by_avatar = {
            graph.owner_avatar_id: graph
            for graph in catalog.graphs
            if graph.source_kind == "character_main"
        }
        if len(owned_graphs_by_avatar) != sum(
            graph.source_kind == "character_main" for graph in catalog.graphs
        ):
            raise ValueError("character ability catalog has duplicate owner graphs")
        cards_by_avatar: dict[str, CharacterDataCardIR] = {}
        for card in cards:
            owner_avatar_id = card.entity_ref[7:]
            if owner_avatar_id in cards_by_avatar:
                raise ValueError("CanonicalIR has duplicate character data cards")
            cards_by_avatar[owner_avatar_id] = card
            expected_owned_graph = owned_graphs_by_avatar.get(owner_avatar_id)
            refs = card.ability_source_graph_refs
            if expected_owned_graph is None:
                if refs:
                    raise ValueError(
                        "character data card references a graph outside the catalog"
                    )
                continue
            owned_refs = tuple(
                ref for ref in refs if ref.reference_kind == "owned"
            )
            shared_refs = tuple(
                ref for ref in refs if ref.reference_kind == "shared"
            )
            if (
                len(owned_refs) != 1
                or owned_refs[0].graph_id != expected_owned_graph.graph_id
                or {ref.graph_id for ref in shared_refs}
                != set(expected_owned_graph.shared_graph_ids)
            ):
                raise ValueError(
                    "character data card graph refs do not close over its catalog graph"
                )
            inventory_source = cast(IRSource, expected_owned_graph.inventory_source)
            inventory_evidence = inventory_source.evidence
            if (
                set(card.skill_ids) != set(expected_owned_graph.selected_skill_ids)
                or card.source.source_path != inventory_source.source_path
                or card.source.evidence.get("row_index")
                != inventory_evidence.get("row_index")
                or card.source.evidence.get("version_kind")
                != inventory_evidence.get("selected_version")
                or {
                    str(skill_id)
                    for skill_id in cast(
                        Iterable[Any], card.source.evidence.get("skill_list") or ()
                    )
                    if skill_id is not None and str(skill_id)
                }
                != set(expected_owned_graph.selected_skill_ids)
            ):
                raise ValueError(
                    "character data card does not match its selected ability source row"
                )
            owned_source = sources_by_id[expected_owned_graph.source_id]
            for ref in refs:
                graph = graphs_by_id.get(ref.graph_id)
                if graph is None:
                    raise ValueError("character data card graph ref is dangling")
                if ref.reference_kind == "owned" and (
                    graph.source_kind != "character_main"
                    or graph.owner_avatar_id != owner_avatar_id
                ):
                    raise ValueError("owned character graph ref is inconsistent")
                if ref.reference_kind == "shared" and (
                    graph.source_kind != "character_shared" or graph.owner_avatar_id
                ):
                    raise ValueError("shared character graph ref is inconsistent")
                ref_evidence = ref.source.evidence
                if (
                    ref.source.source_path != card.source.source_path
                    or ref.source.raw_type != card.source.raw_type
                    or ref_evidence.get("source_graph_catalog_id")
                    != catalog.catalog_id
                    or ref_evidence.get("source_id") != owned_source.source_id
                    or ref_evidence.get("row_index")
                    != inventory_evidence.get("row_index")
                    or ref_evidence.get("selected_version")
                    != inventory_evidence.get("selected_version")
                    or ref_evidence.get("character_config_path")
                    != inventory_evidence.get("character_config_path")
                    or ref_evidence.get("content_sha256")
                    != inventory_evidence.get("content_sha256")
                ):
                    raise ValueError(
                        "character data card graph ref source is inconsistent"
                    )
        for item in (*relations, *gaps):
            card = cards_by_avatar.get(item.owner_avatar_id)
            source = sources_by_id.get(item.source_id)
            graph = graphs_by_id.get(item.source_graph_id)
            source_closed = (
                source is not None
                and source.source_kind == "character_main"
                and source.avatar_id == item.owner_avatar_id
                and source.source.source_path == item.selector_source.source_path
                and source.content_sha256 == item.source_content_sha256
                and graph is not None
                and graph.source_id == item.source_id
                and graph.source_kind == "character_main"
                and graph.owner_avatar_id == item.owner_avatar_id
            )
            if (
                card is None
                or card.card_id != item.character_data_card_id
                or card.entity_ref != f"avatar:{item.owner_avatar_id}"
            ):
                raise ValueError("CanonicalIR selector owner/card mismatch")
            if isinstance(item, CharacterBuildSelectorRelationIR):
                graph_ref = next(
                    (
                        ref
                        for ref in card.ability_source_graph_refs
                        if ref.graph_ref_id == item.source_graph_ref_id
                    ),
                    None,
                )
                if (
                    not source_closed
                    or graph_ref is None
                    or graph_ref.graph_id != item.source_graph_id
                ):
                    raise ValueError(
                        "CanonicalIR selector relation is outside source closure"
                    )
                if item.location_kind == "ability_definition":
                    definition = definitions_by_id.get(item.ability_definition_id)
                    if (
                        definition is None
                        or definition.definition_id not in graph.definition_ids
                        or definition.source_id != item.source_id
                        or definition.owner_avatar_id != item.owner_avatar_id
                        or definition.ability_name != item.ability_name
                        or definition.source != item.ability_definition_source
                    ):
                        raise ValueError(
                            "CanonicalIR selector definition is outside source closure"
                        )
            elif item.gap_kind not in {
                "source_graph_missing",
                "source_closure_mismatch",
            } and not source_closed:
                raise ValueError("CanonicalIR selector gap invented source closure")
        if catalog.source_catalog_complete and not set(
            owned_graphs_by_avatar
        ).issubset(cards_by_avatar):
            raise ValueError(
                "complete character ability catalog is missing an admitted character card"
            )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "version": self.version,
            "metadata": self.metadata,
            "entities": [entity.to_json() for entity in self.entities],
            "avatar_profiles": [profile.to_json() for profile in self.avatar_profiles],
            "character_data_cards": [card.to_json() for card in self.character_data_cards],
            "monster_data_cards": [card.to_json() for card in self.monster_data_cards],
            "character_equipment_eligibilities": [
                eligibility.to_json() for eligibility in self.character_equipment_eligibilities
            ],
            "light_cone_definitions": [definition.to_json() for definition in self.light_cone_definitions],
            "relic_domain_definitions": [definition.to_json() for definition in self.relic_domain_definitions],
            "relic_slot_definitions": [definition.to_json() for definition in self.relic_slot_definitions],
            "relic_main_affix_group_definitions": [
                definition.to_json()
                for definition in self.relic_main_affix_group_definitions
            ],
            "relic_main_affix_definitions": [
                definition.to_json() for definition in self.relic_main_affix_definitions
            ],
            "relic_sub_affix_group_definitions": [
                definition.to_json()
                for definition in self.relic_sub_affix_group_definitions
            ],
            "relic_sub_affix_definitions": [
                definition.to_json() for definition in self.relic_sub_affix_definitions
            ],
            "relic_template_definitions": [definition.to_json() for definition in self.relic_template_definitions],
            "relic_set_definitions": [definition.to_json() for definition in self.relic_set_definitions],
            "relic_set_thresholds": [threshold.to_json() for threshold in self.relic_set_thresholds],
            "equipment_ability_parameter_reads": [
                parameter_read.to_json()
                for parameter_read in self.equipment_ability_parameter_reads
            ],
            "equipment_mechanism_refs": [reference.to_json() for reference in self.equipment_mechanism_refs],
            "summon_unit_definitions": [definition.to_json() for definition in self.summon_unit_definitions],
            "unit_birth_templates": [template.to_json() for template in self.unit_birth_templates],
            "summon_monster_intents": [intent.to_json() for intent in self.summon_monster_intents],
            "assistant_ability_resolutions": [resolution.to_json() for resolution in self.assistant_ability_resolutions],
            "servant_definitions": [definition.to_json() for definition in self.servant_definitions],
            "character_mechanism_slots": [slot.to_json() for slot in self.character_mechanism_slots],
            "passive_mechanism_slots": [slot.to_json() for slot in self.passive_mechanism_slots],
            "character_trace_nodes": [node.to_json() for node in self.character_trace_nodes],
            "character_eidolon_slots": [slot.to_json() for slot in self.character_eidolon_slots],
            "character_build_selector_relations": [
                relation.to_json()
                for relation in self.character_build_selector_relations
            ],
            "character_build_selector_gaps": [
                gap.to_json() for gap in self.character_build_selector_gaps
            ],
            "bounce_policies": [policy.to_json() for policy in self.bounce_policies],
            "combatant_profiles": [profile.to_json() for profile in self.combatant_profiles],
            "action_definitions": [definition.to_json() for definition in self.action_definitions],
            "action_target_contract_catalog": (
                self.action_target_contract_catalog.to_json()
                if self.action_target_contract_catalog is not None
                else None
            ),
            "action_ability_bindings": [binding.to_json() for binding in self.action_ability_bindings],
            "ability_phases": [phase.to_json() for phase in self.ability_phases],
            "ability_tasks": [task.to_json() for task in self.ability_tasks],
            "task_graph_catalog": (
                self.task_graph_catalog.to_json()
                if self.task_graph_catalog is not None
                else None
            ),
            "action_events": [event.to_json() for event in self.action_events],
            "hit_profiles": [profile.to_json() for profile in self.hit_profiles],
            "skill_formula_bindings": [binding.to_json() for binding in self.skill_formula_bindings],
            "damage_emissions": [emission.to_json() for emission in self.damage_emissions],
            "damage_modifiers": [modifier.to_json() for modifier in self.damage_modifiers],
            "toughness_emissions": [emission.to_json() for emission in self.toughness_emissions],
            "break_templates": [template.to_json() for template in self.break_templates],
            "break_base_damage": [item.to_json() for item in self.break_base_damage],
            "break_damage_emissions": [emission.to_json() for emission in self.break_damage_emissions],
            "break_status_emissions": [emission.to_json() for emission in self.break_status_emissions],
            "status_event_families": [family.to_json() for family in self.status_event_families],
            "status_callbacks": [callback.to_json() for callback in self.status_callbacks],
            "status_callback_tasks": [task.to_json() for task in self.status_callback_tasks],
            "ability_property_watchers": [
                watcher.to_json() for watcher in self.ability_property_watchers
            ],
            "ability_property_ranges": [
                property_range.to_json()
                for property_range in self.ability_property_ranges
            ],
            "status_damage_emissions": [emission.to_json() for emission in self.status_damage_emissions],
            "action_delay_emissions": [emission.to_json() for emission in self.action_delay_emissions],
            "queue_intents": [intent.to_json() for intent in self.queue_intents],
            "queue_resolutions": [resolution.to_json() for resolution in self.queue_resolutions],
            "queue_priorities": [priority.to_json() for priority in self.queue_priorities],
            "queue_windows": [window.to_json() for window in self.queue_windows],
            "queue_lifecycle_policies": [policy.to_json() for policy in self.queue_lifecycle_policies],
            "extra_action_policies": [policy.to_json() for policy in self.extra_action_policies],
            "skill_continuations": [continuation.to_json() for continuation in self.skill_continuations],
            "standalone_ability_graphs": [graph.to_json() for graph in self.standalone_ability_graphs],
            "combatant_action_sets": [action_set.to_json() for action_set in self.combatant_action_sets],
            "action_admissions": [admission.to_json() for admission in self.action_admissions],
            "timeline_rules": [rule.to_json() for rule in self.timeline_rules],
            "resource_rules": [rule.to_json() for rule in self.resource_rules],
            "battle_state_transitions": [
                transition.to_json()
                for transition in self.battle_state_transitions
            ],
            "damage_formula_rules": [rule.to_json() for rule in self.damage_formula_rules],
            "damage_route_rules": [rule.to_json() for rule in self.damage_route_rules],
            "shield_priority_rules": [rule.to_json() for rule in self.shield_priority_rules],
            "super_break_emissions": [emission.to_json() for emission in self.super_break_emissions],
            "target_expressions": [expression.to_json() for expression in self.target_expressions],
            "wave_definitions": [definition.to_json() for definition in self.wave_definitions],
            "triggers": [trigger.to_json() for trigger in self.triggers],
            "effects": [effect.to_json() for effect in self.effects],
            "conditions": [condition.to_json() for condition in self.conditions],
            "formulas": [formula.to_json() for formula in self.formulas],
            "character_ability_source_graph_catalog": (
                self.character_ability_source_graph_catalog.to_json()
                if self.character_ability_source_graph_catalog is not None
                else None
            ),
            "character_ability_source_resolution_catalog": (
                self.character_ability_source_resolution_catalog.to_json()
                if self.character_ability_source_resolution_catalog is not None
                else None
            ),
        }
