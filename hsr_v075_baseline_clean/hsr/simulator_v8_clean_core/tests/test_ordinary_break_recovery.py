"""Source-backed ordinary single-stance recovery from an installed break state."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.session import BattleSession
from hsr.simulator_v8_clean_core.systems.damage_formula import status_modifier_terms
from hsr.simulator_v8_clean_core.systems.damage_formula import effective_unit_stat
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.systems.toughness import ToughnessPacket
from hsr.simulator_v8_clean_core.systems.timeline import TimelineSystem
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

pytestmark = pytest.mark.integration


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
        if event.event_type == "break.triggered":
            continue  # TriggerBreak mapping is separately blocked; seed the installed state below.
        dispatch = session.decisions.scheduler.event_dispatcher.dispatch_event(state, event=event)
        assert not dispatch.errors, dispatch.errors
        state = dispatch.after_state

    callback = rules.status_callbacks_for_modifier_event("Local_ListenStanceBreak", "OnBeingBreak")[0]
    tasks = rules.status_callback_tasks_for_callback(callback.callback_id)
    add_effect = rules.effect(next(task.effect_id for task in tasks if task.opcode == "AddModifier"))
    remove_effect = rules.effect(next(task.effect_id for task in tasks if task.opcode == "RemoveModifier"))
    assert add_effect is not None and remove_effect is not None
    status = StatusSystem(rules)
    installed = status.apply_add_modifier(
        state, add_effect, caster_id=attacker_id, source_id=attacker_id,
        owner_id=target_id, _resolved_target_ids=(target_id,),
    )
    assert installed.ok, installed.unsupported
    state = MutationReducer().apply_all(state, installed.mutations)
    assert "modifier:StanceBreakState" in state.units[target_id].statuses
    assert state.units[target_id].flags["monster_stance_count"] == 1
    on_create = rules.status_callbacks_for_modifier_event("StanceBreakState", "OnCreate")[0]
    delay_task = next(task for task in rules.status_callback_tasks_for_callback(on_create.callback_id)
                      if task.opcode == "ModifyActionDelay")
    delay_emission = rules.action_delay_emissions_for_callback(on_create.callback_id)[0]
    assert delay_emission.coverage_status == "executable"
    detail = next(item for item in state.units[target_id].flags["status_details"]
                  if item.get("modifier_name") == "StanceBreakState")
    create_event = next(event for event in installed.events
                        if event.event_type == "status.lifecycle"
                        and event.payload.get("callback_event") == "OnCreate")
    delayed = session.decisions.scheduler.event_dispatcher.status_callbacks._execute_formal_leaf_task(
        state, on_create, delay_task, detail, create_event, None,
    )
    assert delayed.ok, delayed.errors
    timeline_rule, reason = rules.select_timeline_rule()
    assert timeline_rule is not None, reason
    full_av = TimelineSystem().full_action_value(
        effective_unit_stat(state.units[target_id], "speed").value, timeline_rule,
    )
    assert abs(delayed.after_state.units[target_id].action_value
               - state.units[target_id].action_value - 0.25 * full_av) < 1e-8
    removed = status.apply_remove_modifier(
        state, remove_effect, caster_id=attacker_id, source_id=attacker_id,
        owner_id=target_id,
    )
    assert removed.ok, removed.unsupported
    state = MutationReducer().apply_all(state, removed.mutations)
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
