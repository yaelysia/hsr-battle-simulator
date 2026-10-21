from dataclasses import replace

import pytest

from hsr.simulator_v8_clean_core.core.atomic_commit import finalize_selected_execution_graph
from hsr.simulator_v8_clean_core.core.model import BattleState, Mutation, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.transition_outcome import ExecutionNodeResult
from hsr.simulator_v8_clean_core.core.unit_state_codec import unit_state_to_payload


def test_internal_snapshot_shares_frozen_data_and_exports_remain_detached():
    unit = UnitState("actor", "ally", "test:actor", hp=10.0, max_hp=20.0,
                     flags={"source": {"nested": [1, {"value": 2}]}})
    state = BattleState(units={unit.unit_id: unit})
    snapshot = state.snapshot()
    assert snapshot.to_json(detach=False) is snapshot.data
    assert snapshot.data["units"]["actor"]["flags"]["source"] is unit.flags["source"]
    exported = snapshot.to_json()
    exported["units"]["actor"]["flags"]["source"]["nested"][1]["value"] = 99
    unit_export = unit.to_snapshot()
    unit_export["flags"]["source"]["nested"].append(3)
    assert unit.flags["source"]["nested"] == [1, {"value": 2}]
    assert snapshot.to_json()["units"]["actor"]["flags"]["source"]["nested"] == [1, {"value": 2}]
    mutation = Mutation("set", ("units", "actor", "hp"), 10.0, 15.0, "test:heal", "test:source")
    assert mutation.to_json(detach=False)["metadata"] is mutation.metadata
    after = MutationReducer().apply_all(state, (mutation,))
    nodes = (ExecutionNodeResult("effect", "test:heal", "complete"),)
    committed = finalize_selected_execution_graph(state, after, (mutation,), nodes)
    assert committed.outcome.successor_eligible and committed.after_state.units["actor"].hp == 15
    mismatch = replace(after, units={"actor": replace(after.units["actor"], hp=16.0)})
    failed = finalize_selected_execution_graph(state, mismatch, (mutation,), nodes)
    assert not failed.outcome.successor_eligible and failed.after_state is state
    assert failed.evidence["commit_status"] == "candidate_state_mismatch"


def _shield_instance(instance_id: str = "shield:1") -> dict[str, object]:
    return {
        "instance_id": instance_id,
        "shield_id": "shield:capped",
        "source_id": "source:test",
        "source_actor_id": "actor",
        "source_kind": "status",
        "remaining": 12.0,
        "capacity": 20.0,
        "priority": 0,
        "stack_policy": "replace",
        "absorb_families": ["normal"],
        "created_event_index": 0,
        "source_trace": {"trace": "test"},
        "priority_audit": {"rule": "test"},
        "priority_rule": {
            "shield_priority_rule_id": "rule:test",
            "registry_version": "1",
        },
        "owner_modifier_name": "modifier:test",
        "status_instance_id": "status:test",
    }


def _reducer_state() -> BattleState:
    unit = UnitState(
        "actor",
        "ally",
        "test:actor",
        hp=10.0,
        max_hp=20.0,
        attack=5.0,
        defense=3.0,
        speed=100.0,
        energy=1.0,
        max_energy=10.0,
        toughness=30.0,
        max_toughness=30.0,
        statuses=("status:a",),
        shield_instances=(_shield_instance(),),
        flags={
            "position": 0,
            "weaknesses": ["quantum"],
            "status_details": [
                {"instance_id": "status:a", "stacks": 1, "payload": {"values": [1, 2]}}
            ],
            "modifiers": [],
        },
        resources={"recoverable_hp": 2.0, "critical_chance": 0.5},
    )
    enemy = UnitState("enemy", "enemy", "test:enemy", hp=40.0, max_hp=40.0)
    return BattleState(
        units={"actor": unit, "enemy": enemy},
        skill_points=3,
        global_flags={
            "session": {"events": [{"index": 0, "payload": {"tag": "x"}}]},
            "phase": "action",
        },
        queues={
            "turn_insert_action": (
                {"entry_id": "queue:1", "payload": {"steps": [1, 2]}},
            )
        },
        rng_state="seed:1",
        event_index=7,
    )


def test_reducer_shares_frozen_subtrees_and_keeps_inputs_isolated():
    state = _reducer_state()
    before_export = state.snapshot().to_json()
    reducer = MutationReducer()
    flag_mutation = Mutation(
        "set",
        ("units", "actor", "flags", "reducer_flag"),
        None,
        {"nested": [{"token": "stable"}], "enabled": True},
        "test:flag",
        "test:source",
        before_exists=False,
    )
    global_mutation = Mutation(
        "set",
        ("global_flags", "reducer_ledger"),
        None,
        {"ledger": [{"index": 0}]},
        "test:global",
        "test:source",
        before_exists=False,
    )
    queue_mutation = Mutation(
        "set",
        ("queues", "turn_insert_action"),
        list(state.queues["turn_insert_action"]),
        [{"entry_id": "queue:2", "payload": {"steps": [3]}}],
        "test:queue",
        "test:source",
    )
    after = reducer.apply_all(state, (flag_mutation, global_mutation, queue_mutation))
    actor = after.units["actor"]
    # Untouched frozen subtrees stay shared instead of being copied.
    assert actor.flags["status_details"] is state.units["actor"].flags["status_details"]
    assert after.units["enemy"] is state.units["enemy"]
    assert actor.flags["reducer_flag"] is flag_mutation.after
    assert after.global_flags["reducer_ledger"] is global_mutation.after
    assert after.global_flags["session"] is state.global_flags["session"]
    assert after.queues["turn_insert_action"][-1] is queue_mutation.after[0]
    # Shared values are immutable and neither the old state nor the mutation moves.
    assert state.snapshot().to_json() == before_export
    with pytest.raises(TypeError):
        flag_mutation.after["nested"] = []
    with pytest.raises(TypeError):
        state.units["actor"].flags["reducer_flag"] = {}
    # Public exports stay detached even when internal subtrees are shared.
    exported = after.snapshot().to_json()
    exported["units"]["actor"]["flags"]["reducer_flag"]["nested"][0]["token"] = "tampered"
    exported["units"]["actor"]["flags"]["status_details"][0]["payload"]["values"].append(3)
    exported["global_flags"]["reducer_ledger"]["ledger"].append({"index": 1})
    exported_unit = actor.to_snapshot()
    exported_unit["flags"]["reducer_flag"]["nested"].append({"token": "extra"})
    assert actor.flags["reducer_flag"]["nested"] == [{"token": "stable"}]
    assert actor.flags["status_details"][0]["payload"]["values"] == [1, 2]
    assert after.global_flags["reducer_ledger"]["ledger"] == [{"index": 0}]


def test_reducer_strict_scalar_equality_rejects_type_drift():
    state = replace(_reducer_state(), global_flags={"value": 1.0})
    reducer = MutationReducer()
    for declared in (1, True):
        mutation = Mutation(
            "set", ("global_flags", "value"), declared, 2.0, "test:strict", "test:source"
        )
        result = reducer.apply_all_result(state, (mutation,))
        assert not result.ok
        assert result.conflicts[0].code == "before_value_mismatch"
        assert result.after_state is state
    assert reducer.apply(
        state,
        Mutation("set", ("global_flags", "value"), 1.0, 2.0, "test:strict", "test:source"),
    ).global_flags["value"] == 2.0


def test_reducer_container_equality_accepts_frozen_and_plain_shapes():
    state = replace(
        _reducer_state(),
        global_flags={"value": {"a": [1, {"b": True}], "c": None}},
    )
    reducer = MutationReducer()
    declared = {"c": None, "a": (1, {"b": True})}
    after = reducer.apply(
        state,
        Mutation(
            "set",
            ("global_flags", "value"),
            declared,
            {"next": 1},
            "test:container",
            "test:source",
        ),
    )
    assert after.global_flags["value"] == {"next": 1}
    missing_vs_none = reducer.apply(
        after,
        Mutation(
            "set",
            ("global_flags", "missing"),
            None,
            1,
            "test:container",
            "test:source",
            before_exists=False,
        ),
    )
    conflict = reducer.apply_all_result(
        missing_vs_none,
        (
            Mutation(
                "set",
                ("global_flags", "still_missing"),
                None,
                1,
                "test:container",
                "test:source",
            ),
        ),
    )
    assert not conflict.ok
    assert conflict.conflicts[0].code == "before_presence_mismatch"
    assert conflict.after_state is missing_vs_none


def test_reducer_unit_field_queue_and_delete_paths():
    state = _reducer_state()
    reducer = MutationReducer()
    actor = state.units["actor"]
    payload = unit_state_to_payload(actor)
    after = reducer.apply_all(
        state,
        (
            Mutation(
                "set",
                ("units", "actor", "statuses"),
                list(actor.statuses),
                ["status:a", "status:b"],
                "test:field",
                "test:source",
            ),
            Mutation(
                "set",
                ("units", "actor", "shield_instances"),
                payload["shield_instances"],
                [_shield_instance("shield:2")],
                "test:field",
                "test:source",
            ),
            Mutation(
                "set",
                ("units", "actor", "flags"),
                dict(actor.flags),
                {"position": 1, "weaknesses": [], "status_details": [], "modifiers": []},
                "test:field",
                "test:source",
            ),
            Mutation(
                "set",
                ("units", "actor", "resources"),
                dict(actor.resources),
                {"recoverable_hp": 1.5, "critical_chance": 0.5},
                "test:field",
                "test:source",
            ),
            Mutation(
                "delete",
                ("units", "actor", "flags", "modifiers"),
                [],
                None,
                "test:delete",
                "test:source",
                after_exists=False,
            ),
            Mutation(
                "delete",
                ("queues", "turn_insert_action"),
                list(state.queues["turn_insert_action"]),
                None,
                "test:delete",
                "test:source",
                after_exists=False,
            ),
        ),
    )
    updated = after.units["actor"]
    assert updated.statuses == ("status:a", "status:b")
    assert updated.shield_instances[0]["instance_id"] == "shield:2"
    assert updated.flags == {
        "position": 1,
        "weaknesses": [],
        "status_details": [],
    }
    assert updated.resources == {"recoverable_hp": 1.5, "critical_chance": 0.5}
    assert "turn_insert_action" not in after.queues
    assert actor.statuses == ("status:a",)
    assert "modifiers" in actor.flags
    assert "turn_insert_action" in state.queues
    for path, value in (
        (("units", "actor", "statuses"), ["status:a", 1]),
        (("units", "actor", "shield_instances"), [{"instance_id": "incomplete"}]),
        (("units", "actor", "resources"), {"recoverable_hp": 1}),
        (("units", "actor", "hp"), "not-a-number"),
    ):
        current = unit_state_to_payload(updated)
        before = current[path[2]]
        result = reducer.apply_all_result(
            after,
            (
                Mutation(
                    "set", path, before, value, "test:field", "test:source"
                ),
            ),
        )
        assert not result.ok
        assert result.after_state is after
        assert result.applied_count == 0
    invalid_delete = reducer.apply_all_result(
        after,
        (
            Mutation(
                "delete",
                ("units", "actor", "flags", "absent"),
                None,
                None,
                "test:delete",
                "test:source",
                before_exists=False,
                after_exists=False,
            ),
        ),
    )
    assert not invalid_delete.ok
    assert invalid_delete.conflicts[0].code == "invalid_delete"


def test_reducer_spawn_shares_frozen_payload_and_rejects_drift():
    state = _reducer_state()
    reducer = MutationReducer()
    spawned = UnitState(
        "summon",
        "summon",
        "test:summon",
        hp=5.0,
        max_hp=5.0,
        flags={"template": {"nested": [1]}},
        resources={"critical_chance": 0.25},
    )
    payload = unit_state_to_payload(spawned)
    before_export = state.snapshot().to_json()
    mutation = Mutation(
        "spawn",
        ("units", "summon"),
        None,
        payload,
        "test:spawn",
        "test:source",
        before_exists=False,
    )
    after = reducer.apply(state, mutation)
    summon = after.units["summon"]
    assert summon.flags is mutation.after["flags"]
    assert summon.shield_instances == ()
    assert state.snapshot().to_json() == before_export
    exported = summon.to_snapshot()
    exported["flags"]["template"]["nested"].append(2)
    assert summon.flags["template"]["nested"] == [1]
    for path, drifted in (
        (("units", "summon"), {**payload, "extra": 1}),
        (("units", "summon"), {**payload, "hp": 5}),
        (("units", "summon"), {**payload, "unit_id": "other"}),
    ):
        result = reducer.apply_all_result(
            state,
            (
                Mutation(
                    "spawn",
                    path,
                    None,
                    drifted,
                    "test:spawn",
                    "test:source",
                    before_exists=False,
                ),
            ),
        )
        assert not result.ok
        assert result.conflicts[0].code == "invalid_spawn_payload"
        assert result.after_state is state
        assert result.applied_count == 0


def test_reducer_batch_is_atomic_and_ordered_by_candidate_state():
    state = _reducer_state()
    reducer = MutationReducer()
    first = Mutation("set", ("units", "actor", "hp"), 10.0, 9.0, "test:batch", "test:source")
    stale = Mutation("set", ("units", "actor", "hp"), 10.0, 8.0, "test:batch", "test:source")
    failed = reducer.apply_all_result(state, (first, stale))
    assert not failed.ok
    assert failed.conflicts[0].mutation_index == 1
    assert failed.conflicts[0].code == "same_path_before_value_mismatch"
    assert failed.after_state is state
    assert failed.applied_count == 0
    assert state.units["actor"].hp == 10.0
    chained = reducer.apply_all(
        state,
        (
            first,
            Mutation("set", ("units", "actor", "hp"), 9.0, 8.0, "test:batch", "test:source"),
        ),
    )
    assert chained.units["actor"].hp == 8.0
    assert state.units["actor"].hp == 10.0
    # Neighbouring state is shared, not rebuilt through a round trip.
    assert chained.units["actor"].flags is state.units["actor"].flags
    assert chained.units["actor"].resources is state.units["actor"].resources
    assert chained.units["enemy"] is state.units["enemy"]
    assert chained.global_flags is state.global_flags
    assert chained.queues is state.queues
    assert chained.rng_state == state.rng_state
