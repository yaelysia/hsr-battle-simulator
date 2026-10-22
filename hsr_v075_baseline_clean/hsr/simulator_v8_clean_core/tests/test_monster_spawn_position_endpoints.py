"""First/Last summoned-monster positions stay outside the whole formation.

`relative_owner_position` allocates against the present team formation plus the
siblings planned earlier in the same intent. First/Last are formation endpoints:
their slot must stay below the smallest and above the largest occupied position,
not merely miss the historical +-1000 anchor. A formation that already reaches
past the anchor (multi-copy `spawn_index` growth, or a gap left by a departed
sibling) used to push the anchor inside the formation.
"""
from __future__ import annotations

import pytest

from hsr.simulator_v8_clean_core.core.model import UnitState
from hsr.simulator_v8_clean_core.systems.unit_spawn import (
    UnitSpawnRequest,
    _resolve_spec,
)


def _request(positions: tuple[int, ...], spawn_index: int = 0) -> UnitSpawnRequest:
    return UnitSpawnRequest(
        spawn_kind="summoned_monster",
        unit_id="new",
        birth_template_id="birth",
        entity_ref="monster:child",
        source_id="intent",
        entry_id="entry",
        owner_id="owner",
        summoner_id="owner",
        entry_index=0,
        copy_index=0,
        spawn_index=spawn_index,
        formation_positions=positions,
    )


def _position(location_type: str, positions: tuple[int, ...], spawn_index: int = 0) -> int:
    owner = UnitState("owner", "enemy", "monster:owner", flags={"position": 0})
    return _resolve_spec(
        {
            "binding_kind": "relative_owner_position",
            "location_type": location_type,
            "offset_request_field": "spawn_index",
        },
        request=_request(positions, spawn_index),
        owner=owner,
        fields={},
    )


@pytest.mark.parametrize("location_type", ["First", "KeepOnFirst", "Last", "KeepOnLast"])
@pytest.mark.parametrize(
    "positions",
    [
        (),
        (0, 1, 2),
        (-1002, -1000, 0),
        (0, 1000, 1002),
        (-1002, -1000, 1000, 1002),
    ],
)
def test_first_last_stay_outside_the_formation(location_type, positions):
    actual = _position(location_type, positions)

    assert actual not in positions
    if location_type in {"First", "KeepOnFirst"}:
        assert actual < min(positions, default=0)
    else:
        assert actual > max(positions, default=0)


def test_first_last_keep_the_source_anchors_for_an_ordinary_formation():
    # A formation strictly inside the anchors keeps the historical +-1000 slots.
    assert _position("First", (0, 1, 2)) == -1000
    assert _position("Last", (0, 1, 2)) == 1000
    assert _position("First", ()) == -1000
    assert _position("Last", ()) == 1000


def test_gap_reproductions_move_the_endpoint_outward():
    # Both reproductions: the anchor itself is already occupied, so the first
    # free slot used to land between existing positions.
    first = _position("First", (-1002, -1000, 0))
    last = _position("Last", (0, 1000, 1002))

    assert first == -1003
    assert last == 1003


def test_consecutive_allocation_keeps_growing_outward():
    # Same intent, siblings planned one after another: each spawn receives the
    # previous allocation back in `formation_positions`.
    positions: set[int] = {-1002, -1000, 0, 1000, 1002}
    first_seen: list[int] = []
    last_seen: list[int] = []
    for spawn_index in range(3):
        first = _position("First", tuple(sorted(positions)), spawn_index)
        assert first < min(positions)
        positions.add(first)
        first_seen.append(first)
        last = _position("Last", tuple(sorted(positions)), spawn_index)
        assert last > max(positions)
        positions.add(last)
        last_seen.append(last)

    assert all(left < right for right, left in zip(first_seen, first_seen[1:])), first_seen
    assert all(left < right for left, right in zip(last_seen, last_seen[1:])), last_seen
    assert first_seen[0] == -1003 and last_seen[0] == 1003
    assert len(set(positions)) == len(positions)
