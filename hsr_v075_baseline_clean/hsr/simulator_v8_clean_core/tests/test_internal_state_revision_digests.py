"""Internal state revisions keep encoding the same bytes after sharing the snapshot.

The five digest helpers encode a read-only internal snapshot instead of materializing
a detached copy. Their algorithm, options and truncation stay the baseline ones.
"""
from __future__ import annotations

import hashlib
import json

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.systems.action_contract import _action_state_revision
from hsr.simulator_v8_clean_core.systems.action_selection import action_target_state_revision
from hsr.simulator_v8_clean_core.systems.decision import _state_revision
from hsr.simulator_v8_clean_core.systems.dynamic_values import dynamic_value_state_fingerprint
from hsr.simulator_v8_clean_core.systems.scheduler import _scheduler_state_revision


def _state(hp: float = 10.0) -> BattleState:
    unit = UnitState(
        "actor",
        "ally",
        "test:actor",
        hp=hp,
        max_hp=20.0,
        attack=5.0,
        defense=3.0,
        speed=100.0,
        energy=1.0,
        max_energy=10.0,
        toughness=30.0,
        max_toughness=30.0,
        statuses=("status:a",),
        flags={
            "position": 0,
            "weaknesses": ["quantum"],
            "status_details": [
                {"instance_id": "status:a", "stacks": 1, "payload": {"values": [1, 2]}}
            ],
        },
        resources={"recoverable_hp": 2.0, "critical_chance": 0.5},
    )
    return BattleState(
        units={"actor": unit},
        global_flags={
            "phase": "action",
            "nested": {"values": [1, {"enabled": True}], "label": "标签"},
        },
        queues={"turn_insert_action": ({"entry_id": "queue:1", "payload": {"steps": [1]}},)},
        rng_state="seed:1",
        event_index=5,
    )


def _baseline_encoding(state: BattleState, **options: object) -> str:
    payload = json.dumps(
        state.snapshot().to_json(),
        sort_keys=True,
        separators=(",", ":"),
        **options,
    )
    return payload


def test_internal_state_digests_match_the_detached_baseline_encoding():
    state = _state()
    short = _baseline_encoding(state, ensure_ascii=False)
    full = _baseline_encoding(state, ensure_ascii=True, allow_nan=False)
    short_digest = "state:" + hashlib.sha256(short.encode("utf-8")).hexdigest()[:24]
    full_digest = "state:" + hashlib.sha256(full.encode("utf-8")).hexdigest()
    assert action_target_state_revision(state) == short_digest
    assert _state_revision(state) == short_digest
    assert _action_state_revision(state) == short_digest
    assert _scheduler_state_revision(state) == short_digest
    assert dynamic_value_state_fingerprint(state) == full_digest


def test_same_event_index_different_state_changes_every_digest():
    left = _state()
    right = _state(hp=11.0)
    assert left.event_index == right.event_index
    for revision in (
        action_target_state_revision,
        _state_revision,
        _action_state_revision,
        _scheduler_state_revision,
        dynamic_value_state_fingerprint,
    ):
        assert revision(left) != revision(right)
