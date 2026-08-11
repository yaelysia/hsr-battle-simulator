from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, Protocol

from ..immutable_json import freeze_json, thaw_json
from ..ir_types import JSONValue


ConditionOperandStatus = Literal["resolved", "blocked"]
ConditionOperandValueType = Literal[
    "none",
    "boolean",
    "number",
    "string",
    "identity_set",
]

TransientConditionContextKind = Literal[
    "action",
    "damage",
    "event",
    "queue",
    "resource_change",
    "status_callback",
    "turn",
]


TRANSIENT_CONDITION_FACT_SPECS: Mapping[
    str, tuple[TransientConditionContextKind, str]
] = MappingProxyType({
    "action.charm_phase": ("action", "charm_action_context"),
    "action.dynamic_target": ("action", "action_target_contract"),
    "action.target_type": ("action", "action_target_contract"),
    "damage.is_split": ("damage", "damage_context"),
    "damage.source_behavior_flags": ("damage", "damage_context"),
    "damage.type": ("damage", "damage_context"),
    "event.param_string": ("event", "event_context"),
    "queue.has_insert_action_by_target": ("queue", "queue_context"),
    "queue.next_unused_insert_action_matches": ("queue", "queue_context"),
    "queue.unused_insert_ability_count": ("queue", "queue_context"),
    "queue.unused_ultimate_count": ("queue", "queue_context"),
    "resource_change.tags": ("resource_change", "resource_change_context"),
    "status_callback.modifier_value": ("status_callback", "status_callback_context"),
    "turn.action_entity.identity": ("turn", "turn_context"),
    "turn.action_entity.team": ("turn", "turn_context"),
    "turn.owner.action_phase_end": ("turn", "turn_context"),
    "turn.owner.has_action": ("turn", "turn_context"),
    "turn.owner.pending_one_more": ("turn", "turn_context"),
})
TRANSIENT_CONDITION_FACT_KINDS = frozenset(TRANSIENT_CONDITION_FACT_SPECS)


COMMITTED_CONDITION_FACT_KINDS = frozenset(
    {
        "battle.skill_points",
        "relation.body_part",
        "relation.hp_shared_group",
        "relation.opposing",
        "relation.summoner",
        "unit.avatar_base_type",
        "unit.battle_event_id",
        "unit.hp",
        "unit.is_battle_event_entity",
        "unit.lifecycle_mask",
        "unit.monster_rank",
        "unit.red_stance",
        "unit.special_resource_ratio",
        "unit.stance_current",
        "unit.stance_ratio",
        "unit.stance_segment_count",
        "unit.stance_weak",
        "unit.status_resist_chance",
        "unit.target_unselectable",
    }
)


@dataclass(frozen=True)
class ConditionOperandRequest:
    fact_kind: str
    subject_ids: tuple[str, ...] = ()
    parameters: dict[str, JSONValue] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.fact_kind, str):
            raise TypeError("condition operand fact kind must be a string")
        if self.fact_kind not in COMMITTED_CONDITION_FACT_KINDS:
            raise ValueError(f"unknown committed condition fact {self.fact_kind!r}")
        if isinstance(self.subject_ids, str) or not isinstance(
            self.subject_ids, (list, tuple)
        ):
            raise TypeError("condition operand subjects must be a list or tuple")
        subjects = tuple(self.subject_ids)
        if any(not isinstance(item, str) or not item for item in subjects):
            raise ValueError("condition operand contains an invalid subject identity")
        if self.parameters is None:
            raw_parameters: Mapping[str, JSONValue] = {}
        elif isinstance(self.parameters, Mapping):
            raw_parameters = self.parameters
        else:
            raise TypeError("condition operand parameters must be a JSON object")
        parameters = freeze_json(raw_parameters)
        if not isinstance(parameters, dict):
            raise TypeError("condition operand parameters must be a JSON object")
        object.__setattr__(self, "subject_ids", subjects)
        object.__setattr__(self, "parameters", parameters)


@dataclass(frozen=True)
class ConditionOperandResolution:
    fact_kind: str
    status: ConditionOperandStatus
    value_type: ConditionOperandValueType
    value: JSONValue
    authority: str
    source_identity: str = ""
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        if self.fact_kind not in COMMITTED_CONDITION_FACT_KINDS:
            raise ValueError("condition operand result fact kind is invalid")
        if self.status not in {"resolved", "blocked"}:
            raise ValueError("condition operand status is invalid")
        if self.value_type not in {
            "none",
            "boolean",
            "number",
            "string",
            "identity_set",
        }:
            raise ValueError("condition operand value type is invalid")
        if not isinstance(self.authority, str) or not self.authority:
            raise ValueError("condition operand authority is required")
        if not isinstance(self.source_identity, str) or not isinstance(
            self.blocked_reason, str
        ):
            raise TypeError("condition operand result identities must be strings")
        if self.status == "blocked":
            if self.value is not None or self.value_type != "none":
                raise ValueError("blocked condition operand cannot carry a value")
            if not self.blocked_reason or self.source_identity:
                raise ValueError("blocked condition operand contract is inconsistent")
            return
        if self.blocked_reason or not self.source_identity:
            raise ValueError("resolved condition operand contract is inconsistent")
        value = freeze_json(self.value)
        if self.value_type == "boolean" and type(value) is not bool:
            raise TypeError("boolean condition operand has the wrong value type")
        if self.value_type == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError("numeric condition operand must be finite")
            try:
                finite = math.isfinite(float(value))
            except OverflowError as exc:
                raise ValueError("numeric condition operand must be finite") from exc
            if not finite:
                raise ValueError("numeric condition operand must be finite")
        if self.value_type == "string" and (
            not isinstance(value, str) or not value
        ):
            raise TypeError("string condition operand must be non-empty")
        if self.value_type == "identity_set":
            if not isinstance(value, (list, tuple)):
                raise TypeError("identity-set condition operand must be a sequence")
            identities = tuple(value)
            if any(not isinstance(item, str) or not item for item in identities):
                raise ValueError("identity-set condition operand contains an invalid identity")
            if identities != tuple(sorted(identities)) or len(identities) != len(
                set(identities)
            ):
                raise ValueError("identity-set condition operand must be sorted and unique")
        if self.value_type == "none" or value is None:
            raise ValueError("resolved condition operand must carry a typed value")
        object.__setattr__(self, "value", value)

    @classmethod
    def resolved(
        cls,
        value_type: ConditionOperandValueType,
        value: JSONValue,
        *,
        fact_kind: str,
        authority: str,
        source_identity: str,
    ) -> "ConditionOperandResolution":
        return cls(
            fact_kind=fact_kind,
            status="resolved",
            value_type=value_type,
            value=value,
            authority=authority,
            source_identity=source_identity,
        )

    @classmethod
    def blocked(
        cls,
        reason: str,
        *,
        fact_kind: str,
        authority: str,
    ) -> "ConditionOperandResolution":
        return cls(
            fact_kind=fact_kind,
            status="blocked",
            value_type="none",
            value=None,
            authority=authority,
            blocked_reason=reason,
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "fact_kind": self.fact_kind,
            "status": self.status,
            "value_type": self.value_type,
            "value": thaw_json(self.value),
            "authority": self.authority,
            "source_identity": self.source_identity,
            "blocked_reason": self.blocked_reason,
        }


class ConditionOperandProvider(Protocol):
    def resolve(
        self,
        state: Any,
        request: ConditionOperandRequest,
    ) -> ConditionOperandResolution: ...


@dataclass(frozen=True)
class TransientConditionOperandRequest:
    fact_kind: str
    invocation_id: str
    window: str
    subject_ids: tuple[str, ...] = ()
    parameters: dict[str, JSONValue] | None = None

    def __post_init__(self) -> None:
        if type(self) is not TransientConditionOperandRequest:
            raise TypeError("transient condition request must not be subclassed")
        if self.fact_kind not in TRANSIENT_CONDITION_FACT_KINDS:
            raise ValueError(f"unknown transient condition fact {self.fact_kind!r}")
        if not isinstance(self.invocation_id, str) or not self.invocation_id:
            raise ValueError("transient condition invocation identity is required")
        if not isinstance(self.window, str) or not self.window:
            raise ValueError("transient condition window identity is required")
        if isinstance(self.subject_ids, str) or not isinstance(
            self.subject_ids, (list, tuple)
        ):
            raise TypeError("transient condition subjects must be a list or tuple")
        subjects = tuple(self.subject_ids)
        if any(not isinstance(item, str) or not item for item in subjects):
            raise ValueError("transient condition subject identity is invalid")
        if len(subjects) != len(set(subjects)):
            raise ValueError("transient condition subject identities must be unique")
        if self.parameters is None:
            raw_parameters: Mapping[str, JSONValue] = {}
        elif isinstance(self.parameters, Mapping):
            raw_parameters = self.parameters
        else:
            raise TypeError("transient condition parameters must be a JSON object")
        parameters = freeze_json(raw_parameters)
        if not isinstance(parameters, dict):
            raise TypeError("transient condition parameters must be a JSON object")
        object.__setattr__(self, "subject_ids", subjects)
        object.__setattr__(self, "parameters", parameters)


@dataclass(frozen=True)
class TransientConditionOperandResolution:
    fact_kind: str
    invocation_id: str
    status: ConditionOperandStatus
    value_type: ConditionOperandValueType
    value: JSONValue
    context_kind: TransientConditionContextKind
    producer_authority: str
    window: str = ""
    source_identity: str = ""
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        if type(self) is not TransientConditionOperandResolution:
            raise TypeError("transient condition resolution must not be subclassed")
        spec = TRANSIENT_CONDITION_FACT_SPECS.get(self.fact_kind)
        if spec is None:
            raise ValueError("transient condition result fact kind is invalid")
        expected_context, expected_authority = spec
        if not isinstance(self.invocation_id, str) or not self.invocation_id:
            raise ValueError("transient condition result invocation identity is required")
        if self.context_kind != expected_context or self.producer_authority != expected_authority:
            raise ValueError("transient condition result authority is inconsistent")
        if self.status not in {"resolved", "blocked"}:
            raise ValueError("transient condition result status is invalid")
        if self.value_type not in {"none", "boolean", "number", "string", "identity_set"}:
            raise ValueError("transient condition result value type is invalid")
        if not isinstance(self.blocked_reason, str):
            raise TypeError("transient condition blocked reason must be a string")
        if self.status == "blocked":
            if (
                self.value is not None
                or self.value_type != "none"
                or self.window
                or self.source_identity
                or not self.blocked_reason
            ):
                raise ValueError("blocked transient condition result carries formal data")
            return
        if (
            self.blocked_reason
            or not isinstance(self.window, str)
            or not self.window
            or not isinstance(self.source_identity, str)
            or not self.source_identity
        ):
            raise ValueError("resolved transient condition result lacks formal identity")
        value = freeze_json(self.value)
        if self.value_type == "boolean" and type(value) is not bool:
            raise TypeError("transient boolean fact has the wrong value type")
        if self.value_type == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError("transient numeric fact must be finite")
            try:
                finite = math.isfinite(float(value))
            except OverflowError as exc:
                raise ValueError("transient numeric fact must be finite") from exc
            if not finite:
                raise ValueError("transient numeric fact must be finite")
        if self.value_type == "string" and (
            not isinstance(value, str) or not value
        ):
            raise TypeError("transient string fact must be non-empty")
        if self.value_type == "identity_set":
            if not isinstance(value, (list, tuple)):
                raise TypeError("transient identity-set fact must be a sequence")
            identities = tuple(value)
            if any(not isinstance(item, str) or not item for item in identities):
                raise ValueError("transient identity-set fact contains an invalid identity")
            if identities != tuple(sorted(identities)) or len(identities) != len(
                set(identities)
            ):
                raise ValueError("transient identity-set fact must be sorted and unique")
        if self.value_type == "none" or value is None:
            raise ValueError("resolved transient condition fact requires a typed value")
        object.__setattr__(self, "value", value)

    @classmethod
    def resolved(
        cls,
        value_type: ConditionOperandValueType,
        value: JSONValue,
        *,
        fact_kind: str,
        invocation_id: str,
        window: str,
        source_identity: str,
    ) -> "TransientConditionOperandResolution":
        context_kind, producer_authority = TRANSIENT_CONDITION_FACT_SPECS[fact_kind]
        return cls(
            fact_kind=fact_kind,
            invocation_id=invocation_id,
            status="resolved",
            value_type=value_type,
            value=value,
            context_kind=context_kind,
            producer_authority=producer_authority,
            window=window,
            source_identity=source_identity,
        )

    @classmethod
    def blocked(
        cls,
        reason: str,
        *,
        fact_kind: str,
        invocation_id: str,
    ) -> "TransientConditionOperandResolution":
        context_kind, producer_authority = TRANSIENT_CONDITION_FACT_SPECS[fact_kind]
        return cls(
            fact_kind=fact_kind,
            invocation_id=invocation_id,
            status="blocked",
            value_type="none",
            value=None,
            context_kind=context_kind,
            producer_authority=producer_authority,
            blocked_reason=reason,
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "fact_kind": self.fact_kind,
            "invocation_id": self.invocation_id,
            "status": self.status,
            "value_type": self.value_type,
            "value": thaw_json(self.value),
            "context_kind": self.context_kind,
            "producer_authority": self.producer_authority,
            "window": self.window,
            "source_identity": self.source_identity,
            "blocked_reason": self.blocked_reason,
        }


class TransientConditionOperandProvider(Protocol):
    invocation_id: str
    window: str

    def resolve_transient(
        self,
        request: TransientConditionOperandRequest,
    ) -> TransientConditionOperandResolution: ...


__all__ = [
    "COMMITTED_CONDITION_FACT_KINDS",
    "TRANSIENT_CONDITION_FACT_KINDS",
    "TRANSIENT_CONDITION_FACT_SPECS",
    "TransientConditionContextKind",
    "ConditionOperandProvider",
    "ConditionOperandRequest",
    "ConditionOperandResolution",
    "TransientConditionOperandProvider",
    "TransientConditionOperandRequest",
    "TransientConditionOperandResolution",
]
