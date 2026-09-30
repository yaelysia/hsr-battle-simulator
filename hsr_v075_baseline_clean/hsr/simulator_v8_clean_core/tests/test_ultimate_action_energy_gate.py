"""Cost/energy gate checks; the synthetic action has no executable combat graph."""
from dataclasses import replace

import pytest

from hsr.simulator_v8_clean_core.core.model import ActionCommand, BattleState, UnitState
from hsr.simulator_v8_clean_core.rules.ir import ActionAdmissionIR, ActionDefinitionIR, CanonicalIR, IRSource
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.action_availability import _selectable_resource_preflight
from hsr.simulator_v8_clean_core.systems.action_contract import ActionContractSystem
from hsr.simulator_v8_clean_core.systems.queue import QueueDrainPlan


def _rules(cost):
    source = IRSource("synthetic:ultimate", "validation", "energy-cost")
    definition = ActionDefinitionIR(
        "synthetic:ultimate", "synthetic:ultimate", 1, "Ultra", "Ultimate", "single",
        0, 0, 0, 0, (), (), (), None, source, coverage_status="executable", sp_need=cost,
    )
    admission = ActionAdmissionIR(
        "synthetic:admission", "synthetic:actor", definition.action_id, 1, "insert_action",
        ("insert_window", "queue"), ("ultimate",), "selectable_window", "ultimate_energy",
        source, coverage_status="executable",
    )
    return RuleBook(CanonicalIR(version="synthetic:ultimate-gate", action_definitions=(definition,),
                                action_admissions=(admission,)))


def _state(energy, capacity):
    return BattleState(units={"actor": UnitState("actor", "ally", "synthetic:actor",
                                                 energy=energy, max_energy=capacity)},
                       global_flags={"current_window": "ultimate"})


def _plan():
    return QueueDrainPlan(
        True, "ready", "ultimate", {"actor_id": "actor"}, "manual_ultimate:synthetic", "synthetic:resolution",
        queue_window={"window_family": "ultimate"}, resolved_action_id="synthetic:ultimate", resolved_action_level=1,
    )


@pytest.mark.parametrize("energy,capacity,cost,reason", [
    (140.0, 200.0, 100.0, ""),
    (100.0, 200.0, 100.0, ""),
    (100.0, 100.0, 120.0, "ultimate_energy_not_ready"),
    (99.0, 200.0, 100.0, "ultimate_energy_not_ready"),
    (200.0, 200.0, None, "ultimate_energy_cost_invalid"),
    (200.0, 200.0, 0.0, "ultimate_energy_cost_invalid"),
    (200.0, 200.0, -10.0, "ultimate_energy_cost_invalid"),
])
def test_action_contract_and_selected_queue_agree_on_authored_cost(energy, capacity, cost, reason):
    state, rules = _state(energy, capacity), _rules(cost)
    before = state.snapshot().to_json()
    decision = ActionContractSystem(rules).evaluate(
        state, ActionCommand("actor", "synthetic:ultimate", 1), submission_mode="insert_window",
    )
    assert decision.resource_status == ("blocked" if reason else "ok")
    assert decision.resource_blocked_reason == reason
    if reason:
        assert decision.blocked_reason == reason
        assert decision.metadata["sp_need"] == cost
    else:
        # Other graph checks still fail closed; this is only the resource gate.
        assert not decision.ok
        assert "energy" not in decision.blocked_reason
    preflight = _selectable_resource_preflight(rules, state, _plan())
    assert preflight["ok"] is (not reason)
    assert preflight["blocked_reason"] == reason
    assert preflight["sp_need"] == cost
    assert preflight["max_energy"] == capacity
    assert not preflight["requires_action_command_before_action_resource_preflight"]
    assert state.snapshot().to_json() == before


def test_unselected_queue_action_defers_cost_without_capacity_fallback():
    plan = replace(_plan(), resolved_action_id="", resolved_action_level=None)
    result = _selectable_resource_preflight(_rules(100), _state(0.0, 200.0), plan)
    assert result["ok"]
    assert result["sp_need"] is None
    assert result["requires_action_command_before_action_resource_preflight"]


def test_selected_missing_definition_and_actor_stay_blocked():
    state, rules = _state(200.0, 200.0), _rules(100)
    missing = replace(_plan(), resolved_action_id="synthetic:missing")
    assert _selectable_resource_preflight(rules, state, missing)["blocked_reason"] == "ultimate_energy_cost_invalid"
    assert _selectable_resource_preflight(rules, BattleState(), _plan())["blocked_reason"] == "queue_action_actor_missing"


def test_resolved_queue_definition_wins_over_entry_and_trace_hints():
    plan = replace(_plan(), queue_entry={"actor_id": "actor", "action_or_ability_ref": "synthetic:other", "sp_need": 1000},
                   source_trace={"sp_need": 1000})
    result = _selectable_resource_preflight(_rules(100), _state(100.0, 200.0), plan)
    assert result["ok"] and result["sp_need"] == 100
