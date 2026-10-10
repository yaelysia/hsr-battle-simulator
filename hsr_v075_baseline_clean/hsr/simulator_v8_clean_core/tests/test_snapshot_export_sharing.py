from dataclasses import replace

from hsr.simulator_v8_clean_core.core.atomic_commit import finalize_selected_execution_graph
from hsr.simulator_v8_clean_core.core.model import BattleState, Mutation, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.transition_outcome import ExecutionNodeResult


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
