"""Canonical segment-count view over committed toughness state."""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.model import UnitState


@dataclass(frozen=True)
class ToughnessSegments:
    maximum_segments: int
    remaining_segments: int

    def to_json(self) -> dict[str, int]:
        return {"maximum_segments": self.maximum_segments, "remaining_segments": self.remaining_segments}


def read_toughness_segments(unit: UnitState) -> ToughnessSegments:
    """Single bars follow their existing scalar; multiple bars require a producer."""
    if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
           for value in (unit.toughness, unit.max_toughness)):
        raise ValueError("toughness_segment_scalar_invalid")
    maximum = unit.flags.get("monster_stance_count", 1 if unit.max_toughness > 0 or unit.toughness > 0 else 0)
    if type(maximum) is not int or maximum < 0 or maximum == 0 and "monster_stance_count" in unit.flags:
        raise ValueError("toughness_segment_maximum_invalid")
    if maximum <= 1:
        if "stance_segments_remaining" in unit.flags:
            raise ValueError("single_toughness_segment_has_duplicate_count")
        return ToughnessSegments(maximum, int(unit.toughness > 0))
    remaining = unit.flags.get("stance_segments_remaining")
    if (unit.max_toughness <= 0 or type(remaining) is not int or not 0 <= remaining <= maximum):
        raise ValueError("toughness_segments_remaining_missing_or_invalid")
    return ToughnessSegments(maximum, remaining)
