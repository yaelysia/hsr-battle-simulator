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

def _special_state(current, maximum, *, keys=True):
    flags = {"special_resource_definition_id": "special_resource_definition:synthetic"}
    resources = {}
    if keys:
        flags.update(special_resource_current_key="current_special_s_p",
                     special_resource_maximum_key="max_special_s_p")
        resources = {"current_special_s_p": current, "max_special_s_p": maximum}
    return BattleState(units={"actor": UnitState("actor", "ally", "synthetic:actor", energy=0.0,
                                                 max_energy=0, resources=resources, flags=flags)},
                       global_flags={"current_window": "ultimate"})


@pytest.mark.parametrize("current,maximum,reason", [
    (34000.0, 34000.0, ""),
    (10200.0, 34000.0, "ultimate_special_resource_not_ready"),
    (0.0, 34000.0, "ultimate_special_resource_not_ready"),
])
def test_special_resource_ultimate_activates_at_its_declared_maximum(current, maximum, reason):
    state, rules = _special_state(current, maximum), _rules(None)
    before = state.snapshot().to_json()
    decision = ActionContractSystem(rules).evaluate(
        state, ActionCommand("actor", "synthetic:ultimate", 1), submission_mode="insert_window",
    )
    assert decision.resource_status == ("blocked" if reason else "ok")
    assert decision.resource_blocked_reason == reason
    assert decision.metadata.get("sp_need") is None
    if reason:
        assert decision.metadata["special_resource_ultimate_gate"]["maximum"] == maximum
    preflight = _selectable_resource_preflight(rules, state, _plan())
    assert preflight["ok"] is (not reason)
    assert preflight["blocked_reason"] == reason
    assert preflight["special_resource_ultimate_gate"]["current"] == current
    assert state.snapshot().to_json() == before


@pytest.mark.parametrize("state,reason", [
    (_special_state(0.0, 0.0), "ultimate_special_resource_gate_values_invalid"),
    (_special_state(0.0, 0.0, keys=False), "ultimate_special_resource_gate_keys_missing"),
])
def test_special_resource_gate_fails_closed_on_incomplete_declaration(state, reason):
    rules = _rules(None)
    decision = ActionContractSystem(rules).evaluate(
        state, ActionCommand("actor", "synthetic:ultimate", 1), submission_mode="insert_window",
    )
    assert decision.resource_status == "blocked"
    assert decision.resource_blocked_reason == reason
    assert _selectable_resource_preflight(rules, state, _plan())["blocked_reason"] == reason


def test_ordinary_avatar_without_special_resource_keeps_energy_cost_gate():
    rules = _rules(None)
    assert _selectable_resource_preflight(rules, _state(200.0, 200.0), _plan())["blocked_reason"] == "ultimate_energy_cost_invalid"