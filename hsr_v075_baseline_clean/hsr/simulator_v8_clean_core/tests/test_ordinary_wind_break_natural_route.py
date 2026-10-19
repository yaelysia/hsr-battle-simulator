"""Natural Wind break, Wind Shear tick, stance recovery and a second break.

Source route: Lv23 Minion 8011010 from StageConfig wave 400020830 (Wind weakness,
StanceCount=1, toughness 30) against a formal Dan Heng build. Every step below is an
external advance/submit decision; no HP, toughness, status, timeline or queue value is
injected.
"""
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.battle_archive import read_json_object, verify_archive
from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

pytestmark = pytest.mark.integration

ENEMY_ID = "enemy:stage:400020830:wave:0:pos:0"
POISON = "modifier:MCommon_Element_Poison"


def _break_triggered(result):
    return [event for event in result.transition.transaction.events
            if event.event_type == "break.triggered"]


def _hp_mutations(result, unit_id):
    return [mutation for mutation in result.transition.transaction.mutations
            if mutation.path == ("units", unit_id, "hp")]


def _status_detail(state, unit_id, modifier_name):
    return next((detail for detail in state.units[unit_id].flags["status_details"]
                 if detail.get("modifier_name") == modifier_name), None)


def test_natural_wind_break_wind_shear_tick_recovery_and_second_break():
    core = Path(__file__).resolve().parents[1]
    root = Path(__file__).resolve().parents[4]
    example = core / "examples/cli/danheng_wind_break_natural.json"
    scenario = read_json_object(example)
    rules = build_battle_rulebook(root / "turnbasedgamedata-main", scenario)

    # The source card owns the Wind weakness and the single ordinary stance layer.
    profile = rules.combatant_profile("monster:8011010")
    assert profile is not None and "Wind" in profile.weaknesses
    session = BattleSession(rules, scenario)
    enemy_before = session.state.units[ENEMY_ID]
    assert enemy_before.side == "enemy"
    assert "Wind" in enemy_before.flags["weaknesses"]
    assert enemy_before.max_toughness == 30
    assert enemy_before.flags["monster_stance_count"] == 1
    assert enemy_before.flags["stage_id"] == "400020830"
    assert enemy_before.hp == enemy_before.max_hp
    assert enemy_before.toughness == enemy_before.max_toughness

    commands = read_json_object(example.with_suffix(".commands.json"))["commands"]
    assert len(commands) == 5
    assert [command["actor_id"] for command in commands] == [
        "danheng", "natasha", ENEMY_ID, "danheng", "natasha",
    ]

    # 1. First Wind break from Dan Heng's formal basic attack.
    decision = session.advance()
    assert decision.ready, decision.blocked_reason
    assert decision.token.actor_id == "danheng"
    first_break = session.submit(command_from_json(commands[0]))
    assert first_break.transition.outcome.successor_eligible, (
        first_break.transition.outcome.reason_codes)
    triggered = _break_triggered(first_break)
    assert len(triggered) == 1
    assert triggered[0].payload["element_type"] == "Wind"
    assert triggered[0].payload["target_id"] == ENEMY_ID
    assert triggered[0].payload["attacker_id"] == "danheng"
    broken = session.state.units[ENEMY_ID]
    assert broken.toughness == 0 and broken.flags["broken"] is True
    assert "modifier:StanceBreakState" in broken.statuses
    assert POISON in broken.statuses
    assert "modifier:MonsterAllDamageReduce" not in broken.statuses
    break_damage = [mutation for mutation in _hp_mutations(first_break, ENEMY_ID)
                    if mutation.metadata.get("damage_formula_family") == "break"]
    assert len(break_damage) == 1
    assert break_damage[0].metadata.get("break_template_id") == "break_template:StanceBreak_Wind"
    assert break_damage[0].metadata.get("element_type") == "Wind"
    poison = _status_detail(session.state, ENEMY_ID, "MCommon_Element_Poison")
    assert poison is not None
    assert poison["caster_id"] == "danheng" and poison["stacks"] == 1
    assert poison["source_id"] == "break_status_emission:StanceBreak_Wind:1:FailedTaskList:0"
    delay = [mutation for mutation in first_break.transition.transaction.mutations
             if mutation.path == ("units", ENEMY_ID, "action_value")
             and mutation.metadata.get("modifier_name") == "StanceBreakState"]
    assert len(delay) == 1 and delay[0].after > delay[0].before

    # 2. A legal non-Wind action while the target is broken; Physical is not a source
    # weakness, so it cannot reduce the stance.
    decision = session.advance()
    assert decision.ready, decision.blocked_reason
    assert decision.token.actor_id == "natasha"
    filler = session.submit(command_from_json(commands[1]))
    assert filler.transition.outcome.successor_eligible, (
        filler.transition.outcome.reason_codes)
    assert not _break_triggered(filler)
    assert session.state.units[ENEMY_ID].toughness == 0
    hp_before_tick = session.state.units[ENEMY_ID].hp

    # 3. The target's natural turn settles Wind Shear and then restores the stance layer.
    decision = session.advance()
    assert decision.ready, decision.blocked_reason
    assert decision.token.actor_id == ENEMY_ID
    turn_transition = session.operations[-1]["transitions"]
    assert session.operations[-1]["kind"] == "advance" and len(turn_transition) == 1
    turn_transition = turn_transition[0]
    assert turn_transition["coverage"]["pre_action_lifecycle"]["life_step_moment"] == "ModifierPhase1End"
    mutations = turn_transition["mutations"]
    tick_index = next(
        index for index, mutation in enumerate(mutations)
        if mutation["path"] == ["units", ENEMY_ID, "hp"]
        and (mutation["metadata"] or {}).get("record_type") == "break_dot_tick"
    )
    tick = mutations[tick_index]
    dot_ticks = [mutation for mutation in mutations
                 if mutation["path"] == ["units", ENEMY_ID, "hp"]
                 and (mutation["metadata"] or {}).get("record_type") == "break_dot_tick"]
    assert len(dot_ticks) == 1
    assert (tick["metadata"]["damage_source_kind"] == "status_damage"
            and tick["metadata"]["damage_source_owner_id"] == "danheng"
            and tick["metadata"]["modifier_name"] == "MCommon_Element_Poison")
    assert tick["metadata"]["status_damage_emission_id"]
    assert 0 < tick["after"] < tick["before"]
    recovery_index = next(
        index for index, mutation in enumerate(mutations)
        if mutation["path"] == ["units", ENEMY_ID, "toughness"]
        and mutation["before"] == 0
    )
    assert tick_index < recovery_index
    assert mutations[recovery_index]["after"] == enemy_before.max_toughness
    event_types = [event["event_type"] for event in turn_transition["events"]]
    assert (event_types.index("status.lifecycle.tick")
            < event_types.index("break.recovery_requested")
            < event_types.index("break.recovered"))
    recovering = session.state.units[ENEMY_ID]
    assert recovering.toughness == recovering.max_toughness
    assert recovering.flags["broken"] is False
    assert "modifier:StanceBreakState" not in recovering.statuses
    assert "modifier:MonsterAllDamageReduce" in recovering.statuses
    assert recovering.hp < hp_before_tick
    assert recovering.hp == tick["after"]
    assert session.state.units["danheng"].hp > 0

    # 4. The target acts, then the same target is broken by Wind again.
    enemy_turn = session.submit(command_from_json(commands[2]))
    assert enemy_turn.transition.outcome.successor_eligible, (
        enemy_turn.transition.outcome.reason_codes)
    assert session.state.units[ENEMY_ID].toughness == enemy_before.max_toughness
    assert session.state.units[ENEMY_ID].flags["broken"] is False
    decision = session.advance()
    assert decision.ready, decision.blocked_reason
    assert decision.token.actor_id == "danheng"
    second_break = session.submit(command_from_json(commands[3]))
    assert second_break.transition.outcome.successor_eligible, (
        second_break.transition.outcome.reason_codes)
    triggered = _break_triggered(second_break)
    assert len(triggered) == 1
    assert triggered[0].payload["target_id"] == ENEMY_ID
    assert triggered[0].payload["element_type"] == "Wind"
    rebroken = session.state.units[ENEMY_ID]
    assert rebroken.toughness == 0 and rebroken.flags["broken"] is True
    assert "modifier:StanceBreakState" in rebroken.statuses
    assert "modifier:MonsterAllDamageReduce" not in rebroken.statuses
    assert any(mutation.metadata.get("damage_formula_family") == "break"
               for mutation in _hp_mutations(second_break, ENEMY_ID))

    # 5. One more legal external action is available and succeeds on the broken target.
    decision = session.advance()
    assert decision.ready, decision.blocked_reason
    assert decision.token.actor_id == "natasha"
    assert any(choice.actor_id == "natasha"
               and choice.action_id == commands[4]["action_id"]
               for choice in decision.availability.choices)
    follow_up = session.submit(command_from_json(commands[4]))
    assert follow_up.transition.outcome.successor_eligible, (
        follow_up.transition.outcome.reason_codes)
    assert session.outcome == ""
    assert session.state.units[ENEMY_ID].hp > 0
    assert session.state.units["danheng"].hp > 0

    submits = [operation for operation in session.operations if operation["kind"] == "submit"]
    assert len(submits) == len(commands)
    assert verify_archive(session.archive(), rules)["ok"]
