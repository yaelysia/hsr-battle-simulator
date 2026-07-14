from __future__ import annotations

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
