"""One real source-backed battle, including startup, terminal state and replay."""
from pathlib import Path
from dataclasses import replace

import pytest

from hsr.simulator_v8_clean_core.battle_archive import read_json_object, verify_archive
from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook


def test_real_battle_startup_actions_victory_and_replay():
    root = Path(__file__).resolve().parents[4]
    example = Path(__file__).resolve().parents[1] / "examples/cli/arlan_vs_antimatter.json"
    scenario = read_json_object(example)
    rules = build_battle_rulebook(root / "turnbasedgamedata-main", scenario)
    card = rules.monster_data_card_for_entity("monster:8011010")
    slots = rules.passive_mechanism_slots_for_card(card.card_id)
    assert len(slots) == 2
    assert {slot.coverage_status for slot in slots} == {"executable", "skipped_with_reason"}
    session = BattleSession(rules, scenario)
    enemies = [unit for unit in session.state.units.values() if unit.side == "enemy"]
    for enemy in enemies:
        installed = {item["modifier_name"] for item in enemy.flags["status_details"]}
        assert {"Local_ListenStanceBreak", "Local_ListenRedStance", "MonsterAllDamageReduce",
                "TriggerStanceCountDown_Monster"} <= installed
    commands = read_json_object(example.with_suffix(".commands.json"))["commands"]
    for command in commands:
        decision = session.advance()
        assert decision.ready, decision.blocked_reason
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.to_json()
    session.advance()
    assert session.outcome == "victory"
    assert 0 < session.state.units["arlan"].hp < 6
    assert all(session.state.units[enemy.unit_id].hp == 0 for enemy in enemies)
    archive = session.archive()
    assert verify_archive(archive, rules)["ok"]


def test_real_healing_battle_turn_ticks_resource_costs_victory_and_replay():
    root = Path(__file__).resolve().parents[4]
    example = Path(__file__).resolve().parents[1] / "examples/cli/arlan_natasha_vs_antimatter.json"
    scenario = read_json_object(example)
    rules = build_battle_rulebook(root / "turnbasedgamedata-main", scenario)
    session = BattleSession(rules, scenario)
    commands = read_json_object(example.with_suffix(".commands.json"))["commands"]
    heal_count = 0
    hot = lambda: [d for d in session.state.units["arlan"].flags["status_details"]
                   if d["modifier_name"] == "MAvatar_Natasha_00_HOT_HPByMaxHP"]
    for index, command in enumerate(commands):
        before_advance_hp = session.state.units["arlan"].hp
        decision = session.advance()
        assert decision.ready, decision.blocked_reason
        if index == 1:
            # A component probe uses the same real talent, dynamic parameters and
            # decision submission, without changing the scripted session history.
            arlan = session.state.units["arlan"]
            low_state = replace(session.state, units={
                **session.state.units, "arlan": replace(arlan, hp=0.3 * arlan.max_hp),
            })
            low_decision = session.decisions.current_decision(low_state)
            low_result = session.decisions.submit(low_state, low_decision.token, command_from_json(command))
            assert low_result.transition.outcome.successor_eligible, low_result.transition.outcome.reason_codes
            assert low_result.after_state.units["arlan"].hp == pytest.approx(
                0.3 * arlan.max_hp + (0.07 * session.state.units["natasha"].max_hp + 70) * 1.25,
            )
        if index in {5, 8}:
            expected = min(session.state.units["arlan"].max_hp,
                           before_advance_hp + 0.048 * session.state.units["natasha"].max_hp + 48)
            assert session.state.units["arlan"].hp == pytest.approx(expected)
            assert (len(hot()), hot()[0]["remaining_duration"] if hot() else None) == (
                (1, 1.0) if index == 5 else (0, None)
            )
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        if command["actor_id"] == "natasha":
            heal_count += 1
            assert session.state.skill_points == 3 - heal_count
            assert session.state.units["natasha"].energy == 30 * heal_count
        if index == 1:
            assert session.state.units["arlan"].hp == session.state.units["arlan"].max_hp
            assert len(hot()) == 1 and hot()[0]["remaining_duration"] == 2
    session.advance()
    assert session.outcome == "victory"
    assert all(unit.hp == 0 for unit in session.state.units.values() if unit.side == "enemy")
    assert session.state.units["arlan"].hp > 0
    assert verify_archive(session.archive(), rules)["ok"]


def test_real_basic_and_ultimate_battle_with_per_target_talent_and_victory():
    root = Path(__file__).resolve().parents[4]
    examples = Path(__file__).resolve().parents[1] / "examples/cli"
    scenario = read_json_object(examples / "arlan_natasha_vs_antimatter.json")
    rules = build_battle_rulebook(root / "turnbasedgamedata-main", scenario)
    session = BattleSession(rules, scenario)
    commands = read_json_object(examples / "arlan_natasha_ultimate_vs_antimatter.commands.json")["commands"]
    for index, command in enumerate(commands):
        decision = session.advance()
        assert decision.ready, decision.blocked_reason
        before = session.state
        if index == 6:
            # Activating the source-selected E6 branch must still expose its
            # missing damage semantics; pruning is only for inactive branches.
            task = next(t for t in rules.ir.ability_tasks if t.action_id == command["action_id"]
                        and t.level == 1 and t.condition_id
                        and rules.condition(t.condition_id).opcode == "ByRankActivated")
            selector_hash = rules.condition(task.condition_id).payload["build_selector"]["selector_hash"]
            actor = before.units["natasha"]
            relation = next(r for r in rules.character_build_selector_relations_for_card(
                actor.flags["character_data_card_id"],
            ) if r.selector_hash == selector_hash)
            selected = replace(before, units={**before.units, "natasha": replace(actor, flags={
                **actor.flags, "selected_eidolon_slot_ids": relation.selection_ref_ids,
            })})
            blocked = session.decisions.current_decision(selected).availability.to_json()
            assert command["action_id"] not in {c["action_id"] for c in blocked["choices"]}
            assert command["action_id"] in {c["action_id"] for c in blocked["blocked"]}
        if index == 12:
            assert before.units["natasha"].energy == 90
            # This state-copy probe checks independent talent eligibility for
            # two wounded targets; it does not alter the scripted battle.
            low = replace(before, units={**before.units,
                "arlan": replace(before.units["arlan"], hp=0.3 * before.units["arlan"].max_hp),
                "natasha": replace(before.units["natasha"], hp=0.31 * before.units["natasha"].max_hp),
            })
            low_decision = session.decisions.current_decision(low)
            probe = session.decisions.submit(low, low_decision.token, command_from_json(command))
            assert probe.transition.outcome.successor_eligible, probe.transition.outcome.reason_codes
            heals = {m["path"][1]: m["metadata"]["formula_details"]
                     for m in probe.transition.to_json()["mutations"] if m["path"][-1] == "hp"}
            base = 0.092 * before.units["natasha"].max_hp + 92
            assert heals["arlan"]["offered_healing"] == pytest.approx(base * 1.25)
            assert heals["natasha"]["offered_healing"] == pytest.approx(base)
            assert probe.after_state.units["arlan"].hp > low.units["arlan"].hp
            assert probe.after_state.units["natasha"].hp > low.units["natasha"].hp
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        if index == 6:
            assert session.state.units["natasha"].energy == 70
            assert session.state.skill_points == before.skill_points + 1
            assert session.state.units[command["target_ids"][0]].hp < before.units[command["target_ids"][0]].hp
        if index == 12:
            heals = [m for m in result.transition.to_json()["mutations"] if m["path"][-1] == "hp"]
            assert {m["path"][1] for m in heals} == {"arlan", "natasha"}
            assert session.state.units["natasha"].hp == session.state.units["natasha"].max_hp
            assert session.state.units["natasha"].energy == 5
            assert session.state.skill_points == before.skill_points
    session.advance()
    assert session.outcome == "victory"
    assert session.state.skill_points == 4
    assert all(unit.hp == 0 for unit in session.state.units.values() if unit.side == "enemy")


def test_real_serval_basic_skill_shock_ultimate_victory_and_replay():
    root = Path(__file__).resolve().parents[4]
    example = Path(__file__).resolve().parents[1] / "examples/cli/serval_natasha_vs_antimatter.json"
    scenario = read_json_object(example)
    rules = build_battle_rulebook(root / "turnbasedgamedata-main", scenario)
    session = BattleSession(rules, scenario)
    commands = read_json_object(example.with_suffix(".commands.json"))["commands"]
    assert session.state.units["serval"].energy == 0
    enemy_ids = [u.unit_id for u in session.state.units.values() if u.side == "enemy"]
    shock = lambda state, unit_id: next(d for d in state.units[unit_id].flags["status_details"]
                                        if d["modifier_name"] == "MCommon_DOT_Electric")
    seen = set()
    for command in commands:
        decision = session.advance()
        assert decision.ready, decision.blocked_reason
        before = session.state
        if command["action_id"] == "avatar_skill:110303" and command["source"] == "manual":
            assert before.units["serval"].energy == 100
            # Keep both targets alive to exercise the source's random Retarget
            # and lifetime extension through the real queue consumer.
            unchanged = before.snapshot().data
            probe_state = replace(before, units={
                key: replace(unit, hp=unit.max_hp) if unit.side == "enemy" else unit
                for key, unit in before.units.items()
            })
            probe_decision = session.decisions.current_decision(probe_state)
            requested = session.decisions.submit(probe_state, probe_decision.token, command_from_json(command))
            assert requested.transition.outcome.successor_eligible
            queued = next(c.command_template for c in session.decisions.current_decision(requested.after_state).availability.choices
                          if c.actor_id == "serval" and c.command_template["source"] == "queue")
            queued_decision = session.decisions.current_decision(requested.after_state)
            probe = session.decisions.submit(requested.after_state, queued_decision.token, command_from_json(queued))
            assert probe.transition.outcome.successor_eligible, probe.transition.outcome.reason_codes
            assert probe.after_state.units["serval"].energy == 5
            assert any(event.rng_type == "target_random" for event in probe.transition.rng_events)
            for unit_id in enemy_ids:
                assert probe.after_state.units[unit_id].hp > 0
                assert shock(probe.after_state, unit_id)["remaining_duration"] == shock(before, unit_id)["remaining_duration"] + 2
            assert before.snapshot().data == unchanged
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        if command["action_id"] == "avatar_skill:110302":
            seen.add("skill")
            assert session.state.units["serval"].energy == 100
            assert [shock(session.state, unit_id)["remaining_duration"] for unit_id in enemy_ids] == [2, 2]
            additional = [m.path[1] for m in result.transition.transaction.mutations
                          if m.path[-1] == "hp" and m.metadata.get("damage_formula_family") == "additional"]
            assert sorted(additional) == sorted(enemy_ids)
        if command["action_id"] == "avatar_skill:110301":
            seen.add("basic")
        if command["action_id"] == "avatar_skill:110303" and command["source"] == "queue":
            seen.add("ultimate")
            assert session.state.units["serval"].energy == 15
            assert session.state.units[enemy_ids[0]].hp == 0
            assert shock(session.state, enemy_ids[1])["remaining_duration"] == 4
            assert session.state.skill_points == before.skill_points
    session.advance()
    assert seen == {"basic", "skill", "ultimate"} and session.outcome == "victory"
    assert all(session.state.units[unit_id].hp == 0 for unit_id in enemy_ids)
    assert session.state.units["serval"].hp == 124.8 and session.state.units["serval"].energy == 25
    assert session.state.units["natasha"].hp == 158.4 and session.state.skill_points == 2
    assert any(t["command"]["action_id"] == "timeline:consume_defeated_turn"
               for op in session.operations if op["kind"] == "advance" for t in op["transitions"])
    archive = session.archive()
    replay = verify_archive(archive, rules)
    assert replay["ok"], replay["errors"]
