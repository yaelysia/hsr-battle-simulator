from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from ..immutable_json import freeze_json, thaw_json
from ..ir_types import IRSource, JSONValue


CONDITION_RESPONSIBILITY_SCHEMA = "hsr.character_condition_responsibility.v1"

ConditionEvaluationStage = Literal[
    "p9_s6b_committed_state",
    "p9_s7_transient_context",
    "excluded_non_gameplay",
    "blocked_unclassified",
]
ConditionAuthority = Literal[
    "action_context",
    "battle_resource",
    "damage_context",
    "entity_relation",
    "event_context",
    "formation_state",
    "lifecycle_state",
    "presentation_only",
    "queue_context",
    "resource_event_context",
    "status_callback",
    "status_resistance",
    "target_collection",
    "targetability",
    "toughness_state",
    "unit_definition",
    "unit_resource",
    "unit_state",
    "unclassified",
]

_EVALUATION_STAGES = frozenset(
    {
        "p9_s6b_committed_state",
        "p9_s7_transient_context",
        "excluded_non_gameplay",
        "blocked_unclassified",
    }
)
_AUTHORITIES = frozenset(
    {
        "action_context",
        "battle_resource",
        "damage_context",
        "entity_relation",
        "event_context",
        "formation_state",
        "lifecycle_state",
        "presentation_only",
        "queue_context",
        "resource_event_context",
        "status_callback",
        "status_resistance",
        "target_collection",
        "targetability",
        "toughness_state",
        "unit_definition",
        "unit_resource",
        "unit_state",
        "unclassified",
    }
)
_PRODUCER_STAGES = frozenset(
    {
        "current",
        "none",
        "p9_s9",
        "p9_s10",
        "p9_s11",
        "p9_s12",
        "p9_s13",
        "p9_s14",
        "p9_s15",
        "p9_s16",
        "p9_s17",
    }
)
_PLANNED_SCOPE_BASIS = "scope_catalog_gameplay_candidate"
_BLOCKED_SCOPE_BASIS = "source_responsibility_unclassified"
_EXCLUDED_SCOPE_BASES = frozenset(
    {
        "presentation_only_controlled_task_branches",
        "presentation_structural_container:ModifierAffectedPreshowConfig",
    }
)


def _canonical_strings(values: object, field_name: str) -> tuple[str, ...]:
    if isinstance(values, str) or not isinstance(values, (list, tuple)):
        raise TypeError(f"{field_name} must be a list or tuple")
    result = tuple(values)
    if any(not isinstance(value, str) or not value for value in result):
        raise ValueError(f"{field_name} contains an invalid identity")
    if result != tuple(sorted(result)) or len(result) != len(set(result)):
        raise ValueError(f"{field_name} must be sorted and unique")
    return result


def _immutable_source(source: IRSource) -> IRSource:
    if type(source) is not IRSource:
        raise TypeError("condition responsibility source must be exact IRSource")
    if not source.source_path or not source.raw_type or not source.raw_id:
        raise ValueError("condition responsibility source identity is incomplete")
    evidence = freeze_json(source.evidence)
    if not isinstance(evidence, dict):
        raise TypeError("condition responsibility evidence must be an object")
    return IRSource(
        source_path=source.source_path,
        raw_type=source.raw_type,
        raw_id=source.raw_id,
        evidence=evidence,
    )


@dataclass(frozen=True)
class CharacterConditionResponsibilityIR:
    record_id: str
    opcode: str
    evaluation_stage: ConditionEvaluationStage
    authority: ConditionAuthority
    required_context: tuple[str, ...]
    producer_stage: str
    field_signature: tuple[str, ...]
    scope_basis: str
    source: IRSource

    def __post_init__(self) -> None:
        if not isinstance(self.record_id, str) or not self.record_id:
            raise ValueError("condition responsibility record identity is required")
        if not isinstance(self.opcode, str) or not self.opcode:
            raise ValueError("condition responsibility opcode is required")
        if self.evaluation_stage not in _EVALUATION_STAGES:
            raise ValueError("condition responsibility evaluation stage is invalid")
        if self.authority not in _AUTHORITIES:
            raise ValueError("condition responsibility authority is invalid")
        if self.producer_stage not in _PRODUCER_STAGES:
            raise ValueError("condition responsibility producer stage is invalid")
        if not isinstance(self.scope_basis, str) or not self.scope_basis:
            raise ValueError("condition responsibility scope basis is required")
        required_context = _canonical_strings(
            self.required_context, "condition required_context"
        )
        field_signature = _canonical_strings(
            self.field_signature, "condition field_signature"
        )
        source = _immutable_source(self.source)
        if source.raw_id != self.record_id or source.raw_type != self.opcode:
            raise ValueError("condition responsibility source identity is inconsistent")
        if self.evaluation_stage == "excluded_non_gameplay":
            if (
                self.authority != "presentation_only"
                or self.producer_stage != "none"
                or required_context
                or self.scope_basis not in _EXCLUDED_SCOPE_BASES
            ):
                raise ValueError("excluded condition responsibility carries gameplay data")
        elif self.evaluation_stage == "blocked_unclassified":
            if (
                self.authority != "unclassified"
                or self.producer_stage != "none"
                or required_context
                or self.scope_basis != _BLOCKED_SCOPE_BASIS
            ):
                raise ValueError("blocked condition responsibility is not fail-closed")
        elif self.authority in {"presentation_only", "unclassified"}:
            raise ValueError("planned condition responsibility has an invalid authority")
        elif not required_context:
            raise ValueError("planned condition responsibility requires typed context")
        elif self.producer_stage == "none":
            raise ValueError("planned condition responsibility requires a producer")
        elif self.scope_basis != _PLANNED_SCOPE_BASIS:
            raise ValueError("planned condition responsibility scope basis is invalid")
        object.__setattr__(self, "required_context", required_context)
        object.__setattr__(self, "field_signature", field_signature)
        object.__setattr__(self, "source", source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "schema_version": CONDITION_RESPONSIBILITY_SCHEMA,
            "record_id": self.record_id,
            "opcode": self.opcode,
            "evaluation_stage": self.evaluation_stage,
            "authority": self.authority,
            "required_context": list(self.required_context),
            "producer_stage": self.producer_stage,
            "field_signature": list(self.field_signature),
            "scope_basis": self.scope_basis,
            "source": {
                "source_path": self.source.source_path,
                "raw_type": self.source.raw_type,
                "raw_id": self.source.raw_id,
                "evidence": cast(JSONValue, thaw_json(self.source.evidence)),
            },
        }

    @classmethod
    def from_json(cls, value: object) -> "CharacterConditionResponsibilityIR":
        expected = {
            "schema_version",
            "record_id",
            "opcode",
            "evaluation_stage",
            "authority",
            "required_context",
            "producer_stage",
            "field_signature",
            "scope_basis",
            "source",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("condition responsibility payload schema is invalid")
        if value.get("schema_version") != CONDITION_RESPONSIBILITY_SCHEMA:
            raise ValueError("condition responsibility schema version is invalid")
        source = value.get("source")
        if not isinstance(source, dict) or set(source) != {
            "source_path",
            "raw_type",
            "raw_id",
            "evidence",
        }:
            raise ValueError("condition responsibility source schema is invalid")
        evidence = source.get("evidence")
        if not isinstance(evidence, dict):
            raise TypeError("condition responsibility source evidence is invalid")
        string_fields = (
            "record_id",
            "opcode",
            "evaluation_stage",
            "authority",
            "producer_stage",
            "scope_basis",
        )
        if any(not isinstance(value.get(field), str) for field in string_fields):
            raise TypeError("condition responsibility string field is invalid")
        if any(
            not isinstance(source.get(field), str)
            for field in ("source_path", "raw_type", "raw_id")
        ):
            raise TypeError("condition responsibility source identity is invalid")
        return cls(
            record_id=cast(str, value["record_id"]),
            opcode=cast(str, value["opcode"]),
            evaluation_stage=cast(Any, value["evaluation_stage"]),
            authority=cast(Any, value["authority"]),
            required_context=cast(Any, value.get("required_context")),
            producer_stage=cast(str, value["producer_stage"]),
            field_signature=cast(Any, value.get("field_signature")),
            scope_basis=cast(str, value["scope_basis"]),
            source=IRSource(
                source_path=cast(str, source["source_path"]),
                raw_type=cast(str, source["raw_type"]),
                raw_id=cast(str, source["raw_id"]),
                evidence=evidence,
            ),
        )


@dataclass(frozen=True)
class ConditionResponsibilityIssueIR:
    code: str
    record_id: str
    detail: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value
            for value in (self.code, self.record_id, self.detail)
        ):
            raise ValueError("condition responsibility issue is invalid")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "code": self.code,
            "record_id": self.record_id,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class CharacterConditionResponsibilityCatalog:
    source_fingerprint: str
    condition_record_ids: tuple[str, ...]
    existing_family_record_ids: tuple[str, ...]
    responsibilities: tuple[CharacterConditionResponsibilityIR, ...]
    issues: tuple[ConditionResponsibilityIssueIR, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_fingerprint, str)
            or len(self.source_fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in self.source_fingerprint)
        ):
            raise ValueError("condition responsibility fingerprint is invalid")
        record_ids = _canonical_strings(
            self.condition_record_ids, "condition record ids"
        )
        existing_ids = _canonical_strings(
            self.existing_family_record_ids,
            "existing condition family record ids",
        )
        responsibilities = tuple(
            sorted(self.responsibilities, key=lambda item: item.record_id)
        )
        if any(
            type(item) is not CharacterConditionResponsibilityIR
            for item in responsibilities
        ):
            raise TypeError("condition responsibility catalog contains an invalid row")
        responsibility_ids = tuple(item.record_id for item in responsibilities)
        if len(responsibility_ids) != len(set(responsibility_ids)):
            raise ValueError("condition responsibility identities are duplicated")
        if set(existing_ids).intersection(responsibility_ids):
            raise ValueError("condition responsibility partitions overlap")
        if set(record_ids) != set(existing_ids).union(responsibility_ids):
            raise ValueError("condition responsibility partitions are not exhaustive")
        issues = tuple(sorted(self.issues, key=lambda item: (item.code, item.record_id)))
        if any(type(item) is not ConditionResponsibilityIssueIR for item in issues):
            raise TypeError("condition responsibility catalog issue is invalid")
        object.__setattr__(self, "condition_record_ids", record_ids)
        object.__setattr__(self, "existing_family_record_ids", existing_ids)
        object.__setattr__(self, "responsibilities", responsibilities)
        object.__setattr__(self, "issues", issues)

    @property
    def complete(self) -> bool:
        return not self.issues and all(
            row.evaluation_stage != "blocked_unclassified"
            for row in self.responsibilities
        )

    def summary_json(self) -> dict[str, JSONValue]:
        stage_counts: dict[str, int] = {}
        family_sets: dict[str, set[str]] = {}
        for row in self.responsibilities:
            stage_counts[row.evaluation_stage] = (
                stage_counts.get(row.evaluation_stage, 0) + 1
            )
            family_sets.setdefault(row.evaluation_stage, set()).add(row.opcode)
        return {
            "complete": self.complete,
            "source_fingerprint": self.source_fingerprint,
            "condition_record_count": len(self.condition_record_ids),
            "existing_family_record_count": len(
                self.existing_family_record_ids
            ),
            "responsibility_record_count": len(self.responsibilities),
            "stage_counts": dict(sorted(stage_counts.items())),
            "stage_families": {
                stage: sorted(families)
                for stage, families in sorted(family_sets.items())
            },
            "issues": [issue.to_json() for issue in self.issues],
        }
