from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal


JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
CoverageStatus = Literal[
    "discovered_only",
    "lowered",
    "executable",
    "validated",
    "blocked",
    "supported_alias",
    "audit_only",
    "unsupported",
    "skipped_with_reason",
]


@dataclass(frozen=True)
class IRSource:
    source_path: str
    raw_type: str
    raw_id: str
    evidence: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "source_path": self.source_path,
            "raw_type": self.raw_type,
            "raw_id": self.raw_id,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, order=True)
class IRRawRowIdentity:
    source_path: str
    raw_type: str
    raw_id: str
    id_key: str
    row_index: int
    level: int


def ir_source_raw_row_identity(
    source: IRSource,
    *,
    expected_level: int | None = None,
) -> IRRawRowIdentity:
    if not isinstance(source, IRSource):
        raise TypeError("source must be an IRSource")
    for field_name, value in (
        ("source_path", source.source_path),
        ("raw_type", source.raw_type),
        ("raw_id", source.raw_id),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"source raw row {field_name} must be a non-empty string")
    if not isinstance(source.evidence, Mapping):
        raise TypeError("source raw row evidence must be a mapping")
    id_key = source.evidence.get("id_key")
    row_index = source.evidence.get("row_index")
    level = source.evidence.get("level")
    if not isinstance(id_key, str) or not id_key.strip():
        raise ValueError("source raw row id_key must be a non-empty string")
    if not isinstance(row_index, int) or isinstance(row_index, bool) or row_index < 0:
        raise ValueError("source raw row row_index must be a non-negative integer")
    if not isinstance(level, int) or isinstance(level, bool) or level <= 0:
        raise ValueError("source raw row level must be a positive integer")
    if expected_level is not None:
        if (
            not isinstance(expected_level, int)
            or isinstance(expected_level, bool)
            or expected_level <= 0
        ):
            raise ValueError("expected raw row level must be a positive integer")
        if level != expected_level:
            raise ValueError("source raw row level does not match the expected level")
    return IRRawRowIdentity(
        source_path=source.source_path,
        raw_type=source.raw_type,
        raw_id=source.raw_id,
        id_key=id_key,
        row_index=row_index,
        level=level,
    )


def same_ir_source_raw_row(
    left: IRSource,
    right: IRSource,
    *,
    expected_level: int | None = None,
) -> bool:
    return ir_source_raw_row_identity(
        left,
        expected_level=expected_level,
    ) == ir_source_raw_row_identity(
        right,
        expected_level=expected_level,
    )
