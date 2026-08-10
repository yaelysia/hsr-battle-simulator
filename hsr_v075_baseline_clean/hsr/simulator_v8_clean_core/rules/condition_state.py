from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
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


__all__ = [
    "COMMITTED_CONDITION_FACT_KINDS",
    "ConditionOperandProvider",
    "ConditionOperandRequest",
    "ConditionOperandResolution",
]
