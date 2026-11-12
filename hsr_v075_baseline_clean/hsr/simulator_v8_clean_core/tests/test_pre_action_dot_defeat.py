"""A source-backed turn-start DOT defeat commits and leaves the scheduler idle."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.session import BattleSession
from hsr.simulator_v8_clean_core.systems.toughness import ToughnessPacket
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

pytestmark = pytest.mark.integration


def test_pre_action_dot_defeat_commits_and_next_actor_can_act():
    root = Path(__file__).resolve().parents[4]
    scenario = json.loads((root / "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/arlan_vs_antimatter.json").read_text())
    rules = build_battle_rulebook(root / "turnbasedgamedata-main", scenario)
    session = BattleSession(rules, scenario, diagnostics="full")
    scheduler = session.decisions.scheduler
    target_id = next(uid for uid, unit in session.state.units.items() if unit.side == "enemy")
    attacker_id = next(uid for uid, unit in session.state.units.items() if unit.side == "ally")
    emission = next(item for item in rules.ir.toughness_emissions
                    if item.action_id == "avatar_skill:100802" and item.level == 1
                    and item.coverage_status == "executable" and item.element_type == "Thunder")
    target = session.state.units[target_id]
    setup = replace(session.state, units={
        **session.state.units,
        target_id: replace(target, toughness=0, hp=10000, max_hp=10000, action_value=0),
    })
    packet = ToughnessPacket(
        attacker_id=attacker_id, target_id=target_id,
        toughness_emission_id=emission.toughness_emission_id,
        source_task_id=emission.source_task_id, hit_profile_id=emission.hit_profile_id,
        element_type=emission.element_type, amount=0, target_group=emission.target_group,
        coverage_status=emission.coverage_status, source_trace=emission.source.to_json(),
    )
    entered = scheduler.breaks.enter_break(setup, packet)
    assert entered.ok, entered.errors
    state = entered.after_state
    for event in entered.events:
        if str(event.to_json()["event_id"]) in entered.dispatched_event_ids:
            continue
        dispatch = scheduler.event_dispatcher.dispatch_event(state, event=event)
        assert not dispatch.errors, dispatch.errors
        state = dispatch.after_state
    assert "modifier:MCommon_Element_Electric" in state.units[target_id].statuses
    active = state.units[target_id]
    before = replace(state, units={
        **state.units, target_id: replace(active, hp=1, action_value=0),
    })
    timeline_rule, reason = rules.select_timeline_rule()
    assert timeline_rule is not None, reason
    assert scheduler.timeline.plan_next_actor(before, timeline_rule).actor_id == target_id

    result = scheduler.advance_to_next_turn(before)
    assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
    assert result.transition.transaction.command.action_id == "timeline:consume_defeated_turn"
    assert result.after_state.units[target_id].hp == 0
    assert result.after_state.units[target_id].lifecycle_status == "defeated"
    assert result.after_state.global_flags["combat_phase"] == "idle"
    assert "turn_owner_id" not in result.after_state.global_flags
    assert any(event.event_type == "damage.hit" for event in result.transition.transaction.events)
    assert any(event.event_type == "unit.defeated" for event in result.transition.transaction.events)
    assert any(mutation.path == ("units", target_id, "hp")
               and mutation.before == 1 and mutation.after == 0
               for mutation in result.transition.transaction.mutations)
    assert not any(event.event_type == "turn.end" for event in result.transition.transaction.events)
    assert RuntimeSourceAuditor(rules).validate_execution(
        result.transition.transaction.mutations, result.transition.transaction.settlement.records,
    ).ok
    assert MutationReducer().replay_snapshot(
        before, result.transition.transaction.mutations, result.after_state.snapshot().to_json(),
    ).ok

    next_turn = scheduler.step(result.after_state)
    assert next_turn.transition.outcome.successor_eligible, next_turn.transition.outcome.reason_codes
    assert next_turn.transition.transaction.command.actor_id != target_id
