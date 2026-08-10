from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Literal, cast

from ..immutable_json import freeze_json, thaw_json
from ..ir_types import IRSource, JSONValue
from .ir import TargetExpressionIR


ActionTargetCoverageStatus = Literal["lowered", "blocked"]
ActionTargetSelectionMode = Literal["automatic", "explicit"]
ActionTargetCandidateRelation = Literal[
    "self",
    "enemy",
    "ally_or_self",
]
ActionTargetAliveState = Literal["alive_only", "alive_or_limbo"]
ActionTargetFriendServantPolicy = Literal[
    "default",
    "forbidden",
    "allow_when_summoner_unselectable",
]
ActionTargetEnemyServantPolicy = Literal["default", "forbidden"]
ActionTargetServantSelection = Literal["none", "servant_or_summoner"]
ActionTargetImpactSubTarget = Literal["default", "adjacent", "all_teammate"]
ActionTargetSourceRole = Literal[
    "character_config",
    "monster_config",
    "servant_config",
    "action_table",
]
ActionTargetSemanticRole = Literal[
    "action_selection",
    "effect_shape",
    "non_gameplay",
    "unclassified",
]
ActionTargetGapOwner = Literal[
    "",
    "source_scope",
    "source_gap",
    "source_ambiguity",
    "source_decode",
    "p9_s5c2",
    "p9_s6",
]

_SELECTION_MODES = frozenset({"automatic", "explicit"})
_CANDIDATE_RELATIONS = frozenset(
    {"self", "enemy", "ally_or_self"}
)
_SOURCE_ROLES = frozenset(
    {"character_config", "monster_config", "servant_config", "action_table"}
)
_SEMANTIC_ROLES = frozenset(
    {"action_selection", "effect_shape", "non_gameplay", "unclassified"}
)
_COMPONENT_KINDS = frozenset(
    {
        "target_type",
        "sub_target_type",
        "alive_state",
        "target_filter",
        "allow_friend_servant",
        "allow_enemy_servant",
        "merge_servant_select_to_summoner",
        "avoid_self",
        "is_dynamic_target",
        "adjoin_sub_target_count",
        "max_target_count",
        "invalid_target_message",
        "invalid_target_message_icon",
        "skill_effect",
        "unclassified",
    }
)
_GAP_OWNERS = frozenset(
    {
        "", "source_scope", "source_gap", "source_ambiguity", "source_decode",
        "p9_s5c2", "p9_s6",
    }
)


def _stable_id(prefix: str, *parts: object) -> str:
    payload = json.dumps(
        [str(part) for part in parts],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}:{sha256(payload).hexdigest()}"


def _exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} fields are invalid")


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} is required")
    return value


def _source_from_json(value: object) -> IRSource:
    if not isinstance(value, Mapping):
        raise TypeError("action target source must be an object")
    _exact_keys(value, {"source_path", "raw_type", "raw_id", "evidence"}, "source")
    evidence = value["evidence"]
    if not isinstance(evidence, Mapping):
        raise TypeError("action target source evidence must be an object")
    return _immutable_source(
        IRSource(
            source_path=_required_text(value["source_path"], "source_path"),
            raw_type=_required_text(value["raw_type"], "raw_type"),
            raw_id=_required_text(value["raw_id"], "raw_id"),
            evidence=cast(dict[str, JSONValue], dict(evidence)),
        )
    )


def _immutable_source(source: IRSource) -> IRSource:
    if type(source) is not IRSource:
        raise TypeError("action target source must be an exact IRSource")
    _required_text(source.source_path, "source_path")
    _required_text(source.raw_type, "raw_type")
    _required_text(source.raw_id, "raw_id")
    if not isinstance(source.evidence, Mapping):
        raise TypeError("action target source evidence must be an object")
    return IRSource(
        source_path=source.source_path,
        raw_type=source.raw_type,
        raw_id=source.raw_id,
        evidence=cast(dict[str, JSONValue], freeze_json(dict(source.evidence))),
    )


def _source_json(source: IRSource) -> dict[str, JSONValue]:
    return {
        "source_path": source.source_path,
        "raw_type": source.raw_type,
        "raw_id": source.raw_id,
        "evidence": cast(dict[str, JSONValue], thaw_json(source.evidence)),
    }


@dataclass(frozen=True)
class ActionTargetSourceComponentIR:
    action_id: str
    level: int
    component_kind: Literal[
        "target_type",
        "sub_target_type",
        "alive_state",
        "target_filter",
        "allow_friend_servant",
        "allow_enemy_servant",
        "merge_servant_select_to_summoner",
        "avoid_self",
        "is_dynamic_target",
        "adjoin_sub_target_count",
        "max_target_count",
        "invalid_target_message",
        "invalid_target_message_icon",
        "skill_effect",
        "unclassified",
    ]
    source_field: str
    source_role: ActionTargetSourceRole
    semantic_role: ActionTargetSemanticRole
    raw_value: str
    decoded_value: str
    source: IRSource
    component_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self) is not ActionTargetSourceComponentIR:
            raise TypeError("action target source component must not be subclassed")
        _required_text(self.action_id, "action target component action_id")
        if not isinstance(self.level, int) or isinstance(self.level, bool) or self.level <= 0:
            raise ValueError("action target component level is invalid")
        if self.component_kind not in _COMPONENT_KINDS:
            raise ValueError("action target component kind is invalid")
        _required_text(self.source_field, "action target source field")
        if self.source_role not in _SOURCE_ROLES:
            raise ValueError("action target source role is invalid")
        if self.semantic_role not in _SEMANTIC_ROLES:
            raise ValueError("action target semantic role is invalid")
        if self.component_kind == "skill_effect" and (
            self.source_role != "action_table"
            or self.semantic_role != "effect_shape"
        ):
            raise ValueError("action table skill effect cannot define selection")
        if self.semantic_role == "action_selection" and self.source_role not in {
            "character_config",
            "monster_config",
            "servant_config",
        }:
            raise ValueError("action selection requires a combatant config source")
        if self.component_kind == "target_type" and self.semantic_role != "action_selection":
            raise ValueError("target type must define action selection")
        expected_roles = {
            "target_type": "action_selection",
            "alive_state": "action_selection",
            "target_filter": "action_selection",
            "allow_friend_servant": "action_selection",
            "allow_enemy_servant": "action_selection",
            "merge_servant_select_to_summoner": "action_selection",
            "avoid_self": "action_selection",
            "sub_target_type": None,
            "is_dynamic_target": "effect_shape",
            "adjoin_sub_target_count": "effect_shape",
            "max_target_count": "action_selection",
            "invalid_target_message": "non_gameplay",
            "invalid_target_message_icon": "non_gameplay",
            "skill_effect": "effect_shape",
            "unclassified": "unclassified",
        }
        expected_role = expected_roles[self.component_kind]
        if expected_role is not None and self.semantic_role != expected_role:
            raise ValueError("action target component semantic role is inconsistent")
        if self.component_kind == "sub_target_type" and self.semantic_role not in {
            "action_selection", "effect_shape",
        }:
            raise ValueError("sub-target semantic role is invalid")
        _required_text(self.raw_value, "action target raw value")
        _required_text(self.decoded_value, "action target decoded value")
        source = _immutable_source(self.source)
        evidence = source.evidence
        if (
            evidence.get("action_id") != self.action_id
            or evidence.get("level") != self.level
            or evidence.get("component_kind") != self.component_kind
            or evidence.get("source_field") != self.source_field
            or evidence.get("source_role") != self.source_role
            or evidence.get("semantic_role") != self.semantic_role
            or evidence.get("raw_value") != self.raw_value
            or evidence.get("decoded_value") != self.decoded_value
            or not isinstance(evidence.get("json_path"), str)
            or not evidence.get("json_path")
            or not isinstance(evidence.get("content_sha256"), str)
            or len(cast(str, evidence.get("content_sha256"))) != 64
            or any(
                character not in "0123456789abcdef"
                for character in cast(str, evidence.get("content_sha256"))
            )
        ):
            raise ValueError("action target source evidence is inconsistent")
        component_id = _stable_id(
            "action_target_source",
            self.action_id,
            self.level,
            self.component_kind,
            self.source_field,
            self.source_role,
            self.semantic_role,
            source.source_path,
            evidence["json_path"],
            self.raw_value,
            self.decoded_value,
        )
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "component_id", component_id)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "component_id": self.component_id,
            "action_id": self.action_id,
            "level": self.level,
            "component_kind": self.component_kind,
            "source_field": self.source_field,
            "source_role": self.source_role,
            "semantic_role": self.semantic_role,
            "raw_value": self.raw_value,
            "decoded_value": self.decoded_value,
            "source": _source_json(self.source),
        }

    @classmethod
    def from_json(cls, value: object) -> ActionTargetSourceComponentIR:
        if not isinstance(value, Mapping):
            raise TypeError("action target source component must be an object")
        _exact_keys(
            value,
            {
                "component_id",
                "action_id",
                "level",
                "component_kind",
                "source_field",
                "source_role",
                "semantic_role",
                "raw_value",
                "decoded_value",
                "source",
            },
            "action target source component",
        )
        item = cls(
            action_id=cast(str, value["action_id"]),
            level=cast(int, value["level"]),
            component_kind=cast(Any, value["component_kind"]),
            source_field=cast(str, value["source_field"]),
            source_role=cast(Any, value["source_role"]),
            semantic_role=cast(Any, value["semantic_role"]),
            raw_value=cast(str, value["raw_value"]),
            decoded_value=cast(str, value["decoded_value"]),
            source=_source_from_json(value["source"]),
        )
        if value["component_id"] != item.component_id:
            raise ValueError("action target source component identity mismatch")
        return item


@dataclass(frozen=True)
class ActionTargetContractIR:
    definition_id: str
    action_id: str
    level: int
    source_components: tuple[ActionTargetSourceComponentIR, ...]
    source_action_source_ids: tuple[str, ...]
    coverage_status: ActionTargetCoverageStatus
    blocked_reason: str = ""
    gap_owner: ActionTargetGapOwner = ""
    selection_mode: ActionTargetSelectionMode | None = None
    candidate_relation: ActionTargetCandidateRelation | None = None
    selection_min: int | None = None
    selection_max: int | None = None
    allow_duplicates: bool | None = None
    candidate_alive_state: ActionTargetAliveState | None = None
    friend_servant_policy: ActionTargetFriendServantPolicy | None = None
    enemy_servant_policy: ActionTargetEnemyServantPolicy | None = None
    servant_selection: ActionTargetServantSelection | None = None
    merge_servant_selection_to_summoner: bool | None = None
    avoid_self: bool | None = None
    selection_filter: TargetExpressionIR | None = None
    impact_sub_target: ActionTargetImpactSubTarget | None = None
    adjacent_target_count: int | None = None
    dynamic_target: bool | None = None
    contract_id: str = field(init=False)
    contract_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self) is not ActionTargetContractIR:
            raise TypeError("action target contract must not be subclassed")
        _required_text(self.definition_id, "action target definition_id")
        _required_text(self.action_id, "action target action_id")
        if not isinstance(self.level, int) or isinstance(self.level, bool) or self.level <= 0:
            raise ValueError("action target level is invalid")
        components = tuple(self.source_components)
        if any(type(item) is not ActionTargetSourceComponentIR for item in components):
            raise TypeError("action target source components are invalid")
        components = tuple(sorted(components, key=lambda item: item.component_id))
        component_ids = tuple(item.component_id for item in components)
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("action target source components contain duplicates")
        if any(item.action_id != self.action_id or item.level != self.level for item in components):
            raise ValueError("action target source component identity mismatch")
        source_ids = tuple(sorted(self.source_action_source_ids))
        if any(not isinstance(item, str) or not item for item in source_ids):
            raise TypeError("action target source graph references are invalid")
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("action target source graph references contain duplicates")
        if self.coverage_status not in {"lowered", "blocked"}:
            raise ValueError("action target coverage status is invalid")
        if self.gap_owner not in _GAP_OWNERS:
            raise ValueError("action target gap owner is invalid")
        payload = (
            self.selection_mode,
            self.candidate_relation,
            self.selection_min,
            self.selection_max,
            self.allow_duplicates,
            self.candidate_alive_state,
            self.friend_servant_policy,
            self.enemy_servant_policy,
            self.servant_selection,
            self.merge_servant_selection_to_summoner,
            self.avoid_self,
            self.selection_filter,
            self.impact_sub_target,
            self.adjacent_target_count,
            self.dynamic_target,
        )
        if self.coverage_status == "blocked":
            if not self.blocked_reason or not self.gap_owner or any(item is not None for item in payload):
                raise ValueError("blocked action target contract carries executable payload")
        else:
            if self.blocked_reason or self.gap_owner:
                raise ValueError("lowered action target contract carries a blocker")
            if self.selection_mode not in _SELECTION_MODES:
                raise ValueError("lowered action target selection mode is invalid")
            if self.candidate_relation not in _CANDIDATE_RELATIONS:
                raise ValueError("lowered action target candidate relation is invalid")
            if self.candidate_alive_state not in {"alive_only", "alive_or_limbo"}:
                raise ValueError("lowered action target alive state is invalid")
            if self.friend_servant_policy not in {
                "default", "forbidden", "allow_when_summoner_unselectable",
            }:
                raise ValueError("lowered action target friend servant policy is invalid")
            if self.enemy_servant_policy not in {"default", "forbidden"}:
                raise ValueError("lowered action target enemy servant policy is invalid")
            if self.servant_selection not in {"none", "servant_or_summoner"}:
                raise ValueError("lowered action target servant selection is invalid")
            if self.impact_sub_target not in {"default", "adjacent", "all_teammate"}:
                raise ValueError("lowered action target impact sub-target is invalid")
            if (
                not isinstance(self.selection_min, int)
                or isinstance(self.selection_min, bool)
                or not isinstance(self.selection_max, int)
                or isinstance(self.selection_max, bool)
                or self.selection_min < 0
                or self.selection_max < self.selection_min
                or type(self.allow_duplicates) is not bool
                or type(self.merge_servant_selection_to_summoner) is not bool
                or type(self.avoid_self) is not bool
                or type(self.dynamic_target) is not bool
            ):
                raise ValueError("lowered action target cardinality is invalid")
            if self.selection_filter is not None and (
                type(self.selection_filter) is not TargetExpressionIR
                or self.selection_filter.coverage_status != "executable"
            ):
                raise ValueError("lowered action target filter is not executable typed IR")
            if self.adjacent_target_count is not None and (
                not isinstance(self.adjacent_target_count, int)
                or isinstance(self.adjacent_target_count, bool)
                or self.adjacent_target_count <= 0
                or self.impact_sub_target != "adjacent"
            ):
                raise ValueError("lowered adjacent target count is invalid")
            if self.merge_servant_selection_to_summoner and self.servant_selection != "servant_or_summoner":
                raise ValueError("servant merge requires servant-or-summoner selection")
            if self.servant_selection == "servant_or_summoner" and (
                self.selection_mode != "explicit" or self.candidate_relation != "ally_or_self"
            ):
                raise ValueError("servant-or-summoner selection requires an explicit ally target")
            if self.selection_mode == "automatic" and (
                self.selection_min,
                self.selection_max,
            ) != (0, 0):
                raise ValueError("action target mode and cardinality are inconsistent")
            if self.selection_mode == "explicit" and (
                self.selection_min != 1 or self.selection_max < 1
            ):
                raise ValueError("explicit action target cardinality is inconsistent")
            if not any(
                item.semantic_role == "action_selection"
                and item.component_kind == "target_type"
                and item.source_role
                in {"character_config", "monster_config", "servant_config"}
                for item in components
            ):
                raise ValueError("lowered action target contract lacks selection source")
            if any(item.semantic_role == "unclassified" for item in components):
                raise ValueError("lowered action target contract contains an unclassified source field")

            def decoded_values(kind: str) -> set[str]:
                return {
                    item.decoded_value
                    for item in components
                    if item.component_kind == kind
                }

            target_shapes = decoded_values("target_type")
            expected_shape = (
                f"{self.selection_mode}:{self.candidate_relation}:"
                f"{self.selection_min}:{1 if self.selection_mode == 'explicit' else 0}"
            )
            if target_shapes != {expected_shape}:
                raise ValueError("action target selection payload does not match target type source")
            max_counts = decoded_values("max_target_count")
            if max_counts:
                if max_counts != {str(self.selection_max)} or self.selection_mode != "explicit":
                    raise ValueError("action target maximum count does not match source")
            elif self.selection_mode == "explicit" and self.selection_max != 1:
                raise ValueError("multi-target selection lacks a maximum count source")

            source_defaults = {
                "alive_state": (self.candidate_alive_state, "alive_only"),
                "allow_friend_servant": (self.friend_servant_policy, "default"),
                "allow_enemy_servant": (self.enemy_servant_policy, "default"),
                "merge_servant_select_to_summoner": (
                    "merge" if self.merge_servant_selection_to_summoner else "do_not_merge",
                    "do_not_merge",
                ),
                "avoid_self": (
                    "avoid_self" if self.avoid_self else "allow_self",
                    "allow_self",
                ),
                "is_dynamic_target": (
                    "dynamic" if self.dynamic_target else "static",
                    "static",
                ),
            }
            for kind, (actual, default) in source_defaults.items():
                values = decoded_values(kind)
                if values and values != {actual}:
                    raise ValueError(f"action target payload does not match source:{kind}")
                if not values and actual != default:
                    raise ValueError(f"action target non-default payload lacks source:{kind}")

            sub_targets = decoded_values("sub_target_type")
            if len(sub_targets) > 1:
                raise ValueError("action target carries conflicting sub-target sources")
            servant_expected = self.servant_selection == "servant_or_summoner"
            if servant_expected != ("servant_or_summoner_selection" in sub_targets):
                raise ValueError("action target servant selection does not match source")
            impact_source = {
                "adjacent": "adjacent_effect_targets",
                "all_teammate": "all_teammate_effect_targets",
            }.get(self.impact_sub_target)
            if (impact_source is not None) != bool(
                impact_source and impact_source in sub_targets
            ):
                raise ValueError("action target impact shape does not match source")
            if self.impact_sub_target == "default" and sub_targets - {
                "servant_or_summoner_selection"
            }:
                raise ValueError("default action impact carries a non-default source")
            adjacent_counts = decoded_values("adjoin_sub_target_count")
            if adjacent_counts:
                if adjacent_counts != {str(self.adjacent_target_count)}:
                    raise ValueError("adjacent target count does not match source")
            elif self.adjacent_target_count is not None:
                raise ValueError("adjacent target count lacks source")
            filter_components = tuple(
                item for item in components if item.component_kind == "target_filter"
            )
            if (self.selection_filter is None) != (not filter_components):
                raise ValueError("action target filter source and payload disagree")
            if self.selection_filter is not None and not any(
                item.source.source_path == self.selection_filter.source.source_path
                and item.source.evidence.get("json_path")
                == self.selection_filter.source.evidence.get("json_path")
                and item.decoded_value
                == f"typed_target_expression:{self.selection_filter.fingerprint}"
                for item in filter_components
            ):
                raise ValueError("action target filter source does not close")
        identity = {
            "definition_id": self.definition_id,
            "action_id": self.action_id,
            "level": self.level,
            "source_components": [item.to_json() for item in components],
            "source_action_source_ids": list(source_ids),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "gap_owner": self.gap_owner,
            "selection_mode": self.selection_mode,
            "candidate_relation": self.candidate_relation,
            "selection_min": self.selection_min,
            "selection_max": self.selection_max,
            "allow_duplicates": self.allow_duplicates,
            "candidate_alive_state": self.candidate_alive_state,
            "friend_servant_policy": self.friend_servant_policy,
            "enemy_servant_policy": self.enemy_servant_policy,
            "servant_selection": self.servant_selection,
            "merge_servant_selection_to_summoner": self.merge_servant_selection_to_summoner,
            "avoid_self": self.avoid_self,
            "selection_filter": self.selection_filter.to_json() if self.selection_filter is not None else None,
            "impact_sub_target": self.impact_sub_target,
            "adjacent_target_count": self.adjacent_target_count,
            "dynamic_target": self.dynamic_target,
        }
        encoded = json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "source_components", components)
        object.__setattr__(self, "source_action_source_ids", source_ids)
        object.__setattr__(self, "contract_id", _stable_id("action_target_contract", self.action_id, self.level))
        object.__setattr__(self, "contract_fingerprint", sha256(encoded).hexdigest())

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "contract_id": self.contract_id,
            "contract_fingerprint": self.contract_fingerprint,
            "definition_id": self.definition_id,
            "action_id": self.action_id,
            "level": self.level,
            "source_components": [item.to_json() for item in self.source_components],
            "source_action_source_ids": list(self.source_action_source_ids),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "gap_owner": self.gap_owner,
            "selection_mode": self.selection_mode,
            "candidate_relation": self.candidate_relation,
            "selection_min": self.selection_min,
            "selection_max": self.selection_max,
            "allow_duplicates": self.allow_duplicates,
            "candidate_alive_state": self.candidate_alive_state,
            "friend_servant_policy": self.friend_servant_policy,
            "enemy_servant_policy": self.enemy_servant_policy,
            "servant_selection": self.servant_selection,
            "merge_servant_selection_to_summoner": self.merge_servant_selection_to_summoner,
            "avoid_self": self.avoid_self,
            "selection_filter": self.selection_filter.to_json() if self.selection_filter is not None else None,
            "impact_sub_target": self.impact_sub_target,
            "adjacent_target_count": self.adjacent_target_count,
            "dynamic_target": self.dynamic_target,
        }

    @classmethod
    def from_json(cls, value: object) -> ActionTargetContractIR:
        if not isinstance(value, Mapping):
            raise TypeError("action target contract must be an object")
        expected = {
            "contract_id", "contract_fingerprint", "definition_id", "action_id", "level",
            "source_components", "source_action_source_ids", "coverage_status", "blocked_reason",
            "gap_owner", "selection_mode", "candidate_relation", "selection_min", "selection_max",
            "allow_duplicates", "candidate_alive_state", "friend_servant_policy",
            "enemy_servant_policy",
            "servant_selection", "merge_servant_selection_to_summoner", "avoid_self",
            "selection_filter", "impact_sub_target", "adjacent_target_count", "dynamic_target",
        }
        _exact_keys(value, expected, "action target contract")
        components = value["source_components"]
        source_ids = value["source_action_source_ids"]
        if not isinstance(components, Sequence) or isinstance(components, (str, bytes)):
            raise TypeError("action target source components must be an array")
        if not isinstance(source_ids, Sequence) or isinstance(source_ids, (str, bytes)):
            raise TypeError("action target source graph references must be an array")
        filter_value = value["selection_filter"]
        item = cls(
            definition_id=cast(str, value["definition_id"]),
            action_id=cast(str, value["action_id"]),
            level=cast(int, value["level"]),
            source_components=tuple(ActionTargetSourceComponentIR.from_json(part) for part in components),
            source_action_source_ids=tuple(cast(Sequence[str], source_ids)),
            coverage_status=cast(Any, value["coverage_status"]),
            blocked_reason=cast(str, value["blocked_reason"]),
            gap_owner=cast(Any, value["gap_owner"]),
            selection_mode=cast(ActionTargetSelectionMode | None, value["selection_mode"]),
            candidate_relation=cast(ActionTargetCandidateRelation | None, value["candidate_relation"]),
            selection_min=cast(int | None, value["selection_min"]),
            selection_max=cast(int | None, value["selection_max"]),
            allow_duplicates=cast(bool | None, value["allow_duplicates"]),
            candidate_alive_state=cast(ActionTargetAliveState | None, value["candidate_alive_state"]),
            friend_servant_policy=cast(ActionTargetFriendServantPolicy | None, value["friend_servant_policy"]),
            enemy_servant_policy=cast(ActionTargetEnemyServantPolicy | None, value["enemy_servant_policy"]),
            servant_selection=cast(ActionTargetServantSelection | None, value["servant_selection"]),
            merge_servant_selection_to_summoner=cast(bool | None, value["merge_servant_selection_to_summoner"]),
            avoid_self=cast(bool | None, value["avoid_self"]),
            selection_filter=(
                None if filter_value is None else TargetExpressionIR.from_json(filter_value)
            ),
            impact_sub_target=cast(ActionTargetImpactSubTarget | None, value["impact_sub_target"]),
            adjacent_target_count=cast(int | None, value["adjacent_target_count"]),
            dynamic_target=cast(bool | None, value["dynamic_target"]),
        )
        if value["contract_id"] != item.contract_id or value["contract_fingerprint"] != item.contract_fingerprint:
            raise ValueError("action target contract identity mismatch")
        return item


@dataclass(frozen=True)
class ActionTargetContractCatalogIR:
    definition_scope: Literal["complete", "partial"]
    source_graph_catalog_id: str
    source_graph_fingerprint: str
    character_source_level_keys: tuple[str, ...]
    contracts: tuple[ActionTargetContractIR, ...]
    build_counters: Mapping[str, JSONValue]
    catalog_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self) is not ActionTargetContractCatalogIR:
            raise TypeError("action target catalog must not be subclassed")
        if self.definition_scope not in {"complete", "partial"}:
            raise ValueError("action target definition scope is invalid")
        _required_text(self.source_graph_catalog_id, "action target source graph catalog id")
        if not isinstance(self.source_graph_fingerprint, str) or len(self.source_graph_fingerprint) != 64:
            raise ValueError("action target source graph fingerprint is invalid")
        level_keys = tuple(sorted(self.character_source_level_keys))
        if any(not isinstance(item, str) or not item for item in level_keys):
            raise TypeError("action target character source level keys are invalid")
        if len(level_keys) != len(set(level_keys)):
            raise ValueError("action target character source level keys contain duplicates")
        contracts = tuple(self.contracts)
        if any(type(item) is not ActionTargetContractIR for item in contracts):
            raise TypeError("action target catalog contracts are invalid")
        contracts = tuple(sorted(contracts, key=lambda item: (item.action_id, item.level, item.contract_id)))
        contract_ids = tuple(item.contract_id for item in contracts)
        contract_keys = tuple((item.action_id, item.level) for item in contracts)
        if len(contract_ids) != len(set(contract_ids)) or len(contract_keys) != len(set(contract_keys)):
            raise ValueError("action target catalog contains duplicate identities")
        covered_keys = {
            f"{source_id}\0{item.action_id}\0{item.level}"
            for item in contracts
            for source_id in item.source_action_source_ids
        }
        if not covered_keys.issubset(set(level_keys)):
            raise ValueError("action target catalog invents character source coverage")
        if self.definition_scope == "complete" and covered_keys != set(level_keys):
            raise ValueError("complete action target catalog misses character source coverage")
        if not isinstance(self.build_counters, Mapping):
            raise TypeError("action target build counters must be an object")
        counters = cast(Mapping[str, JSONValue], freeze_json(dict(self.build_counters)))
        if counters.get("generic_record_limit_applied") != (self.definition_scope == "partial"):
            raise ValueError("action target catalog scope and build counters disagree")
        identity = {
            "definition_scope": self.definition_scope,
            "source_graph_catalog_id": self.source_graph_catalog_id,
            "source_graph_fingerprint": self.source_graph_fingerprint,
            "character_source_level_keys": list(level_keys),
            "contracts": [item.to_json() for item in contracts],
        }
        encoded = json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "character_source_level_keys", level_keys)
        object.__setattr__(self, "contracts", contracts)
        object.__setattr__(self, "build_counters", counters)
        object.__setattr__(self, "catalog_id", f"action_target_catalog:{sha256(encoded).hexdigest()}")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "catalog_id": self.catalog_id,
            "definition_scope": self.definition_scope,
            "source_graph_catalog_id": self.source_graph_catalog_id,
            "source_graph_fingerprint": self.source_graph_fingerprint,
            "character_source_level_keys": list(self.character_source_level_keys),
            "contracts": [item.to_json() for item in self.contracts],
            "build_counters": cast(dict[str, JSONValue], thaw_json(self.build_counters)),
        }

    @classmethod
    def from_json(cls, value: object) -> ActionTargetContractCatalogIR:
        if not isinstance(value, Mapping):
            raise TypeError("action target catalog must be an object")
        expected = {
            "catalog_id", "definition_scope", "source_graph_catalog_id", "source_graph_fingerprint",
            "character_source_level_keys", "contracts", "build_counters",
        }
        _exact_keys(value, expected, "action target catalog")
        level_keys = value["character_source_level_keys"]
        contracts = value["contracts"]
        counters = value["build_counters"]
        if not isinstance(level_keys, Sequence) or isinstance(level_keys, (str, bytes)):
            raise TypeError("action target character source level keys must be an array")
        if not isinstance(contracts, Sequence) or isinstance(contracts, (str, bytes)):
            raise TypeError("action target contracts must be an array")
        if not isinstance(counters, Mapping):
            raise TypeError("action target build counters must be an object")
        item = cls(
            definition_scope=cast(Any, value["definition_scope"]),
            source_graph_catalog_id=cast(str, value["source_graph_catalog_id"]),
            source_graph_fingerprint=cast(str, value["source_graph_fingerprint"]),
            character_source_level_keys=tuple(cast(Sequence[str], level_keys)),
            contracts=tuple(ActionTargetContractIR.from_json(part) for part in contracts),
            build_counters=cast(Mapping[str, JSONValue], counters),
        )
        if value["catalog_id"] != item.catalog_id:
            raise ValueError("action target catalog identity mismatch")
        return item


@dataclass(frozen=True)
class ActionTargetContractQueryResult:
    resolution_status: Literal["resolved", "blocked"]
    action_id: str
    level: int
    value: ActionTargetContractIR | None = None
    candidate_ids: tuple[str, ...] = ()
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        _required_text(self.action_id, "action target query action_id")
        if not isinstance(self.level, int) or isinstance(self.level, bool) or self.level <= 0:
            raise ValueError("action target query level is invalid")
        if self.resolution_status not in {"resolved", "blocked"}:
            raise ValueError("action target query status is invalid")
        candidates = tuple(sorted(self.candidate_ids))
        if len(candidates) != len(set(candidates)) or any(not item for item in candidates):
            raise ValueError("action target query candidates are invalid")
        if self.resolution_status == "resolved":
            if type(self.value) is not ActionTargetContractIR or self.blocked_reason or candidates != (self.value.contract_id,):
                raise ValueError("resolved action target query is inconsistent")
            if self.value.coverage_status != "lowered" or (self.value.action_id, self.value.level) != (self.action_id, self.level):
                raise ValueError("resolved action target query value is invalid")
        elif self.value is not None or not self.blocked_reason:
            raise ValueError("blocked action target query is inconsistent")
        object.__setattr__(self, "candidate_ids", candidates)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "resolution_status": self.resolution_status,
            "action_id": self.action_id,
            "level": self.level,
            "value": self.value.to_json() if self.value is not None else None,
            "candidate_ids": list(self.candidate_ids),
            "blocked_reason": self.blocked_reason,
        }
