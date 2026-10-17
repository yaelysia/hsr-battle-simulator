"""Source-backed ordinary single-stance recovery from an installed break state."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.systems.damage_formula import status_modifier_terms
from hsr.simulator_v8_clean_core.systems.damage_formula import effective_unit_stat
from hsr.simulator_v8_clean_core.systems.toughness import ToughnessPacket
from hsr.simulator_v8_clean_core.systems.timeline import TimelineSystem
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

pytestmark = pytest.mark.integration


def test_ordinary_hit_breaks_once_and_removes_reduction_before_break_damage():
    root = Path(__file__).resolve().parents[4]
    scenario = json.loads((root / "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/arlan_vs_antimatter.json").read_text())
    rules = build_battle_rulebook(root / "turnbasedgamedata-main", scenario)
    session = BattleSession(rules, scenario)
    assert session.advance().ready
    target_id = next(uid for uid, unit in session.state.units.items() if unit.side == "enemy")
    target = session.state.units[target_id]
    # Boundary fixture: retain real startup/callbacks, but force a nonlethal
    # matching depletion. The check covers our adopted behavior, not native internals.
    session.state = replace(session.state, units={
        **session.state.units,
        target_id: replace(target, toughness=1, hp=10000, max_hp=10000,
                           flags={**target.flags, "weaknesses": ["Thunder"]}),
    })
    before = session.state
    result = session.submit(command_from_json({
        "actor_id": "arlan", "action_id": "avatar_skill:100801", "action_level": 1,
        "target_ids": [target_id],
    }))
    assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
    transaction = result.transition.transaction
    assert sum(event.event_type == "break.triggered" for event in transaction.events) == 1
    unit = session.state.units[target_id]
    assert unit.toughness == 0 and unit.flags["broken"] is True
    assert "modifier:StanceBreakState" in unit.statuses
    assert "modifier:MonsterAllDamageReduce" not in unit.statuses
    breaks = [mutation for mutation in transaction.mutations
              if mutation.path == ("units", target_id, "hp")
              and mutation.metadata.get("damage_formula_family") == "break"]
    assert len(breaks) == 1
    pipeline = breaks[0].metadata["damage_pipeline"]
    assert next(bucket for bucket in pipeline["stages"]
                if bucket["stage"] == "damage_reduction")["multiplier"] == 1
    # The source still owns the 25% delay; it must run only once.
    timeline_rule, reason = rules.select_timeline_rule()
    assert timeline_rule is not None, reason
    full_av = TimelineSystem().full_action_value(effective_unit_stat(unit, "speed").value, timeline_rule)
    delays = [mutation for mutation in transaction.mutations
              if mutation.path == ("units", target_id, "action_value")]
    assert sum(mutation.after - mutation.before for mutation in delays) == pytest.approx(0.25 * full_av)
    assert before.units[target_id].toughness == 1


def test_ordinary_break_recovery_restores_stance_and_common_reduction():
    root = Path(__file__).resolve().parents[4]
    scenario = json.loads((root / "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/arlan_vs_antimatter.json").read_text())
    rules = build_battle_rulebook(root / "turnbasedgamedata-main", scenario)
    session = BattleSession(rules, scenario)
    assert session.advance().ready
    target_id = next(uid for uid, unit in session.state.units.items() if unit.side == "enemy")
    attacker_id = next(uid for uid, unit in session.state.units.items() if unit.side == "ally")
    emission = next(item for item in rules.ir.toughness_emissions
                    if item.action_id == "avatar_skill:100802" and item.level == 1
                    and item.coverage_status == "executable" and item.element_type == "Thunder")
    target = session.state.units[target_id]
    state = replace(session.state, units={
        **session.state.units,
        target_id: replace(target, toughness=0, hp=10000, max_hp=10000),
    })
    packet = ToughnessPacket(
        attacker_id=attacker_id, target_id=target_id,
        toughness_emission_id=emission.toughness_emission_id,
        source_task_id=emission.source_task_id, hit_profile_id=emission.hit_profile_id,
        element_type=emission.element_type, amount=0, target_group=emission.target_group,
        coverage_status=emission.coverage_status, source_trace=emission.source.to_json(),
    )
    entered = session.decisions.scheduler.breaks.enter_break(state, packet)
    assert entered.ok, entered.errors
    state = entered.after_state
    for event in entered.events:
        if str(event.to_json()["event_id"]) in entered.dispatched_event_ids:
            continue
        dispatch = session.decisions.scheduler.event_dispatcher.dispatch_event(state, event=event)
        assert not dispatch.errors, dispatch.errors
        state = dispatch.after_state

    assert "modifier:StanceBreakState" in state.units[target_id].statuses
    assert state.units[target_id].flags["monster_stance_count"] == 1
    timeline_rule, reason = rules.select_timeline_rule()
    assert timeline_rule is not None, reason
    full_av = TimelineSystem().full_action_value(
        effective_unit_stat(state.units[target_id], "speed").value, timeline_rule,
    )
    assert state.units[target_id].action_value - target.action_value == pytest.approx(0.25 * full_av)
    assert "modifier:MonsterAllDamageReduce" not in state.units[target_id].statuses
    assert status_modifier_terms(
        state.units[target_id], source_type="target.damage_reduction",
        bucket="damage_reduction", keys=("damage_reduction",),
    )[0] == 0
    before_recovery = state
    recovery = session.decisions.scheduler.breaks.recover_ordinary_before_action(state, unit_id=target_id)
    assert recovery is not None and recovery.ok, recovery.errors if recovery else None
    unit = recovery.after_state.units[target_id]
    assert unit.toughness == unit.max_toughness
    assert unit.flags["broken"] is False
    assert "modifier:StanceBreakState" not in unit.statuses
    assert "modifier:MonsterAllDamageReduce" in unit.statuses
    assert "modifier:MCommon_Element_Electric" in unit.statuses
    electric = next(item for item in unit.flags["status_details"]
                    if item.get("modifier_name") == "MCommon_Element_Electric")
    assert electric["dynamic_values"]["MDF_DamagePercentage"] == 2.0
    assert electric["dynamic_values"]["1486739431"] == 2.0
    assert status_modifier_terms(
        unit, source_type="target.damage_reduction",
        bucket="damage_reduction", keys=("damage_reduction",),
    )[0] == 0.1
    audit = RuntimeSourceAuditor(rules).validate_execution(recovery.mutations, recovery.records)
    assert audit.ok, [(issue.reason, issue.details.get("coverage_status")) for issue in audit.violations]
    assert MutationReducer().replay_snapshot(
        before_recovery, recovery.mutations, recovery.after_state.snapshot().to_json(),
    ).ok
    phase = session.decisions.scheduler._apply_status_lifecycle_tick(
        recovery.after_state, "ModifierPhase1End", actor_id=target_id,
    )
    assert not phase.errors, phase.errors
    assert phase.after_state.units[target_id].hp < unit.hp
