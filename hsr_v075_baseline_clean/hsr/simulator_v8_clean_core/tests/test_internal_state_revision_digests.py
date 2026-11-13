"""State identities retain every field and reuse immutable subtrees."""
from __future__ import annotations

import json
from hsr.simulator_v8_clean_core.immutable_json import freeze_json, json_tree_digest

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.systems.action_contract import _action_state_revision
from hsr.simulator_v8_clean_core.systems.action_selection import action_target_state_revision
from hsr.simulator_v8_clean_core.systems.decision import _state_revision
from hsr.simulator_v8_clean_core.systems.dynamic_values import dynamic_value_state_fingerprint
from hsr.simulator_v8_clean_core.systems.scheduler import _scheduler_state_revision


def test_mutation_identity_retains_before_after_and_metadata_with_shared_subtrees():
    from dataclasses import replace
    from hsr.simulator_v8_clean_core.core.model import Mutation

    shared = freeze_json({'source': {'rows': list(range(1000))}})
    first = Mutation('set', ('global_flags', 'value'), {'value': 1, 'evidence': shared},
                     {'value': 2, 'evidence': shared}, 'identity check', 'fixture', metadata={'source': shared})
    assert replace(first).stable_id() == first.stable_id()
    for variant in (replace(first, before={'value': 0, 'evidence': shared}),
                    replace(first, after={'value': 3, 'evidence': shared}),
                    replace(first, metadata={'source': shared, 'kind': 'different'})):
        assert variant.stable_id() != first.stable_id()
    assert replace(first, mutation_id='explicit-id').stable_id() == 'explicit-id'


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


def test_internal_state_digests_match_detached_state_content():
    state = _state()
    full = _baseline_encoding(state, ensure_ascii=True, allow_nan=False)
    full_digest = "state:" + json_tree_digest(json.loads(full)).hex()
    short_digest = full_digest[:30]
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


def test_short_and_full_identity_serialize_a_state_only_once(monkeypatch):
    from hsr.simulator_v8_clean_core.core import model
    original = model.json_tree_digest
    calls = []
    def tracked(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    state = _state()
    monkeypatch.setattr(model, 'json_tree_digest', tracked)
    assert action_target_state_revision(state) == dynamic_value_state_fingerprint(state)[:30]
    assert len(calls) == 1


def test_tree_digest_keeps_types_boundaries_order_and_mutable_inputs():
    values = [False, 0, 0.0, -0.0, '0', [], {}, [1, 2], [2, 1], {'ab': 'c'}, {'a': 'bc'}]
    assert len({json_tree_digest(value) for value in values}) == len(values)
    assert json_tree_digest({'标签': 1, 'a': 2}) == json_tree_digest({'a': 2, '标签': 1})
    mutable = {'source_trace': {'id': 'first'}}
    frozen = freeze_json(mutable)
    before = json_tree_digest(frozen)
    assert json_tree_digest(mutable) == before
    mutable['source_trace']['id'] = 'second'
    assert json_tree_digest(mutable) != before == json_tree_digest(frozen)


def test_new_state_reuses_unchanged_frozen_subtrees(monkeypatch):
    from hsr.simulator_v8_clean_core import immutable_json
    shared = freeze_json({'large': list(range(1000))})
    first = freeze_json({'shared': shared, 'changed': 0})
    json_tree_digest(first)
    calls = []
    original = immutable_json.json.dumps
    def tracked(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)
    monkeypatch.setattr(immutable_json.json, 'dumps', tracked)
    second = freeze_json({'shared': shared, 'changed': 1})
    assert json_tree_digest(second) != json_tree_digest(first)
    assert len(calls) < 10  # The unchanged thousand-element list was not re-encoded.
