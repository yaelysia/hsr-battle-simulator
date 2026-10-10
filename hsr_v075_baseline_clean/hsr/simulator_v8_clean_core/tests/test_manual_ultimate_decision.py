"""Real Arlan startup/actions against a kernel fixture; not a full monster build."""
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hsr.simulator_v8_clean_core.core.model import UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.session import command_from_json
from hsr.simulator_v8_clean_core.systems.decision import DecisionSystem
from hsr.simulator_v8_clean_core.tests.test_character_passive_startup import _source_case

pytestmark = pytest.mark.integration


@lru_cache(maxsize=1)
def _case():
    rules, built = _source_case(frozenset({"8011010"}))
    timeline_rule, reason = rules.select_timeline_rule()
    assert timeline_rule is not None, reason
    # This explicit boundary fixture isolates request/queue behavior. It does
    # not claim monster passive, phase, or real battle energy-gain coverage.
    actor = replace(built.state.units["owner"], energy=110)
    enemy = UnitState("enemy", "enemy", "monster:8011010", level=1,
                      hp=10000, max_hp=10000, toughness=10000, max_toughness=10000,
                      attack=100, action_value=0, flags={"position": 0,
                      "build_mode": "kernel_fixture",
                      "monster_data_card_id": "monster_data_card:monster:8011010",
                      "enemy_action_sequence_cursor": 0})
    state = replace(built.state, units={"owner": actor, "enemy": enemy}, global_flags={
        **built.state.global_flags, "phase": "combat", "combat_phase": "awaiting_decision",
        "current_window": "turn_active", "turn_owner_id": "enemy",
        "active_turn": {"actor_id": "enemy", "turn_kind": "regular",
                        "turn_sequence_index": 1, "timeline_rule_id": timeline_rule.timeline_rule_id},
    })
    return rules, state


def _request(decision):
    return next((choice for choice in decision.availability.choices
                 if choice.choice_kind == "manual_ultimate_request"), None)


def _command(choice, target="enemy"):
    return command_from_json({**choice.command_template, "target_ids": [target]})


def test_request_queues_then_uses_existing_consumer_without_consuming_enemy_turn():
    rules, state = _case()
    system = DecisionSystem(rules)
    decision = system.current_decision(state)
    assert decision.ready, decision.to_json()
    choice = _request(decision)
    assert choice is not None, decision.to_json()
    assert decision.availability.turn_owner_id == "enemy"
    assert any(item.actor_id == "enemy" for item in decision.availability.choices)
    wrong_target = system.submit(state, decision.token, _command(choice, "owner"))
    assert not wrong_target.transition.outcome.successor_eligible
    assert wrong_target.after_state == state and not wrong_target.transition.transaction.mutations
    request = system.submit(state, decision.token, _command(choice))
    assert request.transition.outcome.successor_eligible, request.transition.outcome.to_json()
    queued = request.after_state
    assert queued.units == state.units
    assert queued.global_flags["turn_owner_id"] == "enemy"
    assert queued.queues["manual_ultimate"]
    stale = system.submit(queued, decision.token, _command(choice))
    assert not stale.transition.outcome.successor_eligible and stale.after_state == queued
    queue_decision = system.current_decision(queued)
    assert queue_decision.ready and queue_decision.availability.mode == "queued_selectable", queue_decision.to_json()
    queued_choice = next(item for item in queue_decision.availability.choices
                         if item.choice_kind == "ultimate_window")
    executed = system.submit(queued, queue_decision.token, _command(queued_choice))
    assert executed.transition.outcome.successor_eligible, executed.transition.to_json()
    assert not executed.transition.coverage.get("queue_terminal_plan"), (
        executed.transition.coverage.get("child_transition"),
    )
    after = executed.after_state
    assert executed.child_transitions
    assert executed.transition.rng_events == executed.child_transitions[0].rng_events
    assert not after.queues.get("manual_ultimate")
    assert after.units["owner"].energy < state.units["owner"].energy
    assert after.units["enemy"].hp < state.units["enemy"].hp
    assert after.units["enemy"].action_value == state.units["enemy"].action_value
    assert after.units["owner"].action_value == state.units["owner"].action_value
    assert after.global_flags["turn_owner_id"] == "enemy"
    assert after.global_flags.get("active_turn") == state.global_flags.get("active_turn")
    assert after.global_flags["current_window"] == state.global_flags["current_window"]
    assert not any(m.path == ("global_flags", "turn_owner_id")
                   for m in executed.transition.transaction.mutations)
    audit = RuntimeSourceAuditor(rules).validate_transition(executed.transition)
    assert audit.ok, audit.to_json()
    assert MutationReducer().replay_snapshot(
        queued, executed.transition.transaction.mutations, after.snapshot().to_json(),
    ).ok
    resumed = system.current_decision(after)
    assert resumed.ready and resumed.availability.mode == "external_selectable", resumed.to_json()
    assert resumed.availability.turn_owner_id == "enemy"


def test_unready_dead_and_wrong_window_have_no_request():
    rules, state = _case()
    system = DecisionSystem(rules)
    cases = (
        replace(state, units={**state.units, "owner": replace(state.units["owner"], energy=109)}),
        replace(state, units={**state.units, "owner": replace(state.units["owner"], hp=0, lifecycle_status="defeated")}),
        replace(state, global_flags={**state.global_flags, "current_window": "unknown_window"}),
        replace(state, global_flags={**state.global_flags, "combat_phase": "action_execution"}),
    )
    for candidate in cases:
        before = candidate.snapshot().to_json()
        assert _request(system.current_decision(candidate)) is None
        assert candidate.snapshot().to_json() == before


if __name__ == "__main__":
    test_request_queues_then_uses_existing_consumer_without_consuming_enemy_turn()
    test_unready_dead_and_wrong_window_have_no_request()
    print("2 manual ultimate decision checks passed")
