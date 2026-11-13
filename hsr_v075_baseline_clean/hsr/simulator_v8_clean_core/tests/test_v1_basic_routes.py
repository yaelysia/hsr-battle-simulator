"""Fixed roster builds through public commands; external values are check-only."""
import json
import math
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.core.model import current_max_hp
from hsr.simulator_v8_clean_core.systems.unit_stats import effective_unit_stat
from hsr.simulator_v8_clean_core.tests.test_ordinary_element_break_natural_routes import open_route
from hsr.simulator_v8_clean_core.tests.test_r05_ordinary_party_routes import _records


@pytest.mark.integration
def test_lv80_enhanced_seele_damage_resurgence_and_terminal_cleanup(tmp_path):
    _, _, session, commands = open_route("seele_lv80_resurgence_and_equipment")
    first_basic = first_ultimate = None
    extra_count = 0
    tags = []
    for command in commands:
        decision, automatic = session.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        extra = decision.availability.queue.window_family == "extra_turn"
        if extra:
            extra_count += 1
            assert {c.action_id for c in decision.availability.choices} == {
                "avatar_skill:1110201", "avatar_skill:1110202"}
            branch = session.fork()
            before_av = session.state.units["seele"].action_value
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        for t in (*automatic, result.transition):
            tags.extend(e.payload.get("custom_tag") for e in t.transaction.events if e.event_type == "queue.action.before")
        damage = [r["payload"] for r in _records((result.transition,)) if r.get("record_type") == "damage"]
        if command["action_id"] == "avatar_skill:1110201" and first_basic is None:
            first_basic = damage
        if command["action_id"] == "avatar_skill:1110203" and damage and first_ultimate is None:
            first_ultimate = damage[0]
        if extra:
            assert session.state.units["seele"].action_value == before_av
            for name in ("MAvatar_Advanced_Seele_00_Passive_DamageUp", "MAvatar_Advanced_Seele_00_BPSkill_SpeedUp"):
                duration = lambda state: next(d["remaining_duration"] for d in state.units["seele"].flags["status_details"]
                                               if d.get("modifier_name") == name)
                assert duration(session.state) == duration(branch.state)
            # This extra action kills a summon without chaining another extra
            # turn. A public RNG fork changes a hit while preserving the main session.
            main_snapshot = session.state.snapshot().to_json()
            roll = next(e for e in reversed(result.transition.rng_events)
                        if e.rng_type == "crit" and e.result.get("value") == "noncrit")
            key = roll.metadata["available_rng_outcomes"]["choice_key"]
            killed = branch.submit(command_from_json({**command, "metadata": {"rng_choices": {key: "crit"}}}))
            assert killed.transition.outcome.successor_eligible, killed.transition.outcome.reason_codes
            assert branch.state.units[command["target_ids"][0]].hp == 0
            assert session.state.units[command["target_ids"][0]].hp == 0
            assert any(e.result.get("value") == "crit" and e.metadata.get("choice_key") == key
                       for e in killed.transition.rng_events)
            assert not any(e.get("custom_tag") == "Avatar_Seele_00_BonusInsertAction"
                           for entries in branch.state.queues.values() for e in entries)
            assert branch.advance().ready or branch.outcome == "victory"
            assert session.state.snapshot().to_json() == main_snapshot
    for hit, expected in zip(first_basic, (462.10587415157414, 1078.247039687006)):
        assert not hit["crit_resolution"]["is_crit"]
        assert math.isclose(hit["amount"], expected, rel_tol=0.01)
    assert len(first_basic) == 2 and extra_count == 2
    assert not first_ultimate["crit_resolution"]["is_crit"]
    assert math.isclose(first_ultimate["amount"], 20381.32734529872, rel_tol=0.01)
    assert tags.count("Avatar_Seele_00_BonusInsertAction") == 2
    assert "Advanced_Seele_00_Skill02InsertCheck" in tags
    session.advance()
    assert session.outcome == "victory"
    assert not any(session.state.queues.values())
    from hsr.simulator_v8_clean_core.battle_archive import write_archive

    print(write_archive(tmp_path / "seele_v1_complete.json.gz", session.archive()))


@pytest.mark.integration
def test_lv80_lynx_entry_energy_survival_hot_and_real_cleanse():
    _, _, session, commands = open_route("lynx_lv80_survival_and_equipment")
    assert session.state.skill_points == 4
    assert session.state.units["lynx"].energy == 100
    assert session.state.units["arlan"].energy == 6
    assert math.isclose(effective_unit_stat(session.state.units["lynx"], "control_resistance").value, 0.35)
    initial_max_hp = {uid: current_max_hp(unit) for uid, unit in session.state.units.items()}
    original_max_hp = initial_max_hp["arlan"]
    records = []
    cleansed = False
    for command in commands:
        decision, automatic = session.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        had_debuff = "modifier:MCommon_DefenceRatioDown" in session.state.units["arlan"].statuses
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        records.extend(_records((*automatic, result.transition)))
        if command["action_id"] == "avatar_skill:111002":
            target = command["target_ids"][0]
            assert current_max_hp(session.state.units[target]) > initial_max_hp[target]
            hot = next(d for d in session.state.units[target].flags["status_details"]
                       if d.get("modifier_name") == "MAvatar_Lynx_00_HOT_HealByMaxHp")
            assert hot["duration"] == 3
        if had_debuff and command["action_id"] == "avatar_skill:111003":
            if "modifier:MCommon_DefenceRatioDown" not in session.state.units["arlan"].statuses:
                cleansed = True
                assert session.state.units["arlan"].hp > 1000
    heals = [r["payload"] for r in records if r.get("record_type") == "heal" and r["payload"].get("target_id") == "lynx"]
    ultimate = next(h for h in heals if "avatar_skill:111003:" in h.get("effect_id", ""))
    hot = next(h for h in heals if "HOT_HealByMaxHp" in h.get("effect_id", ""))
    assert math.isclose(ultimate["amount"], 1377.0976519864946, rel_tol=0.01)
    assert math.isclose(hot["amount"], 367.22604052973185, rel_tol=0.01)
    assert cleansed
    assert current_max_hp(session.state.units["arlan"]) == original_max_hp
    assert session.advance().ready


@pytest.mark.integration
def test_lv80_danheng_slow_talent_cooldown_and_external_damage(tmp_path):
    _, _, session, commands = open_route("danheng_lv80_slow_and_equipment")
    records = []
    skill_count = 0
    first_basic = None
    first_skill = None
    slow_branch = None
    for command in commands:
        decision, automatic = session.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        current = tuple(_records((result.transition,)))
        records.extend(_records((*automatic, result.transition)))
        action = command["action_id"]
        if action == "avatar_skill:100203" and any(r.get("record_type") == "damage" for r in current):
            slow_branch = session.fork()
        if action == "avatar_skill:110502":
            assert "modifier:MAvatar_DanHeng_00_Passive_SelfBeingTargetEnhance" in session.state.units["danheng"].statuses
        if action == "avatar_skill:100201" and first_basic is None:
            first_basic = [r["payload"] for r in current if r.get("record_type") == "damage"]
            enemy = session.state.units["enemy:stage:402120485:wave:0:pos:0"]
            assert math.isclose(enemy.max_toughness - enemy.toughness, 30.0)
        if action == "avatar_skill:100202":
            skill_count += 1
            if first_skill is None:
                first_skill = next(r["payload"] for r in current if r.get("record_type") == "damage")
                enemy = session.state.units["enemy:stage:402120485:wave:0:pos:0"]
                assert math.isclose(enemy.max_toughness - enemy.toughness, 90.0)
                assert "modifier:MAvatar_DanHeng_00_BPSkill_SpeedDown" in enemy.statuses
                assert "modifier:MAvatar_DanHeng_00_Passive_BeginTargetEnhanceCD" in session.state.units["danheng"].statuses
                rolls = [e for e in result.transition.rng_events if e.rng_type == "status_apply"]
                assert len(rolls) >= 2 and len({e.event_id for e in rolls}) == len(rolls)
    assert len(first_basic) == 2 and skill_count >= 3
    for hit, expected in zip(first_basic, (700.6282422161448, 856.323407153066)):
        assert not hit["crit_resolution"]["is_crit"]
        assert math.isclose(hit["amount"], expected, rel_tol=0.01)
    assert not first_skill["crit_resolution"]["is_crit"]
    assert math.isclose(first_skill["amount"], 1555.1865709990761, rel_tol=0.01)
    ultimate = next(r["payload"] for r in records if r.get("record_type") == "damage"
                    and r["payload"].get("source_task_id", "").startswith("ability_task:ability_phase:avatar_skill:100203:"))
    assert not ultimate["crit_resolution"]["is_crit"]
    assert math.isclose(ultimate["amount"], 7623.463583328807, rel_tol=0.01)
    statuses = session.state.units["danheng"].statuses
    assert "modifier:MAvatar_DanHeng_00_Passive_BeginTargetEnhance" in statuses
    assert "modifier:MAvatar_DanHeng_00_SkillTree_AggroDown" in statuses
    assert session.advance().ready
    # Branch the public session after the ultimate to exercise A6's slowed basic.
    path = Path(__file__).resolve().parents[1] / "examples/cli/danheng_lv80_slow_and_equipment.slow_basic.commands.json"
    branch_records = []
    original_state = session.state.snapshot().to_json()
    for command in json.loads(path.read_text())["commands"][6:]:
        assert slow_branch.advance().ready
        result = slow_branch.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        branch_records.extend(_records((result.transition,)))
    hits = [r["payload"] for r in branch_records if r.get("record_type") == "damage"
            and r["payload"].get("source_task_id", "").startswith("ability_task:ability_phase:avatar_skill:100201:")]
    assert len(hits) == 2
    for hit, expected in zip(hits, (864.2499706976755, 1584.4582694127694)):
        assert math.isclose(hit["amount"], expected, rel_tol=0.01)
    assert session.state.snapshot().to_json() == original_state

    from hsr.simulator_v8_clean_core.battle_archive import write_archive
    write_archive(tmp_path / 'danheng_v1_complete.json.gz', session.archive())


@pytest.mark.integration
def test_lv80_asta_five_hits_energy_charging_and_speed():
    _, _, session, commands = open_route("asta_lv80_bounce_and_equipment")
    initial_speed = {uid: effective_unit_stat(session.state.units[uid], "speed").value for uid in ("asta", "natasha")}
    initial_attack = effective_unit_stat(session.state.units["natasha"], "attack").value
    records = []
    skill_count = 0
    for index, command in enumerate(commands):
        decision, automatic = session.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        before_energy = session.state.units["asta"].energy
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        current = tuple(_records((result.transition,)))
        records.extend(_records((*automatic, result.transition)))
        if index == 0:
            assert effective_unit_stat(session.state.units["natasha"], "attack").value > initial_attack
            hit = next(r["payload"] for r in current if r.get("record_type") == "damage")
            assert not hit["crit_resolution"]["is_crit"]
            assert math.isclose(hit["amount"], 1556.161046323466, rel_tol=0.01)
        if index == 5:
            for uid, speed in initial_speed.items():
                assert math.isclose(effective_unit_stat(session.state.units[uid], "speed").value - speed, 50.0)
        if command["action_id"] == "avatar_skill:100902":
            skill_count += 1
            assert len([r for r in current if r.get("record_type") == "damage"]) == 5
            assert [r["payload"]["raw_amount"] for r in current if r.get("record_type") == "content_energy"] == [6.0] * 4
            if skill_count == 1:
                assert math.isclose(session.state.units["asta"].energy - before_energy, 35.83182045)
    assert skill_count == 3
    assert any(r.get("record_type") == "dot_damage" for r in records)
    for uid, speed in initial_speed.items():
        assert math.isclose(effective_unit_stat(session.state.units[uid], "speed").value, speed)
    assert session.advance().ready


@pytest.mark.integration
def test_lv80_pela_dispels_buffs_next_attack_and_interrupts_frozen_turn():
    _, _, session, commands = open_route("pela_lv80_dispel_and_equipment")
    boost = "modifier:MAvatar_Pela_SkillTree03_DamageAddedRatio"
    records = []
    granted = False
    ultimate_used = False
    for index, command in enumerate(commands):
        decision, automatic = session.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        assert all(t.outcome.successor_eligible for t in automatic)
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        records.extend(_records((*automatic, result.transition)))
        current = tuple(_records((result.transition,)))
        if any(r.get("record_type") == "dispel_count" and r["payload"]["count"] > 0 for r in current):
            assert boost in session.state.units["pela"].statuses
            granted = True
        if command["action_id"] == "avatar_skill:110603" and any(r.get("record_type") == "damage" for r in current):
            assert granted
            assert boost not in session.state.units["pela"].statuses
            ultimate_used = True
    basic = [r["payload"] for r in records if r.get("record_type") == "damage"
             and r["payload"].get("source_task_id", "").startswith("ability_task:ability_phase:avatar_skill:110601:")]
    assert len(basic) == 2
    assert all(not hit["crit_resolution"]["is_crit"] for hit in basic)
    assert all(math.isclose(hit["amount"], 614.0719691853528, rel_tol=0.01) for hit in basic)
    ultimate = next(r["payload"] for r in records if r.get("record_type") == "damage"
                    and r["payload"].get("source_task_id", "").startswith("ability_task:ability_phase:avatar_skill:110603:")
                    and r["payload"].get("source_frame", {}).get("target_id", "").endswith(":pos:1"))
    assert not ultimate["crit_resolution"]["is_crit"]
    assert math.isclose(ultimate["amount"], 1790.227481675655, rel_tol=0.01)
    counts = [r["payload"]["count"] for r in records if r.get("record_type") == "dispel_count"]
    assert counts[0] == 1 and 0 in counts
    assert ultimate_used
    assert any(r.get("record_type") == "status_dispel"
               and r["payload"]["status_id"] == "modifier:Monster_W1_Soldier01_03_Buff" for r in records)
    assert any(r.get("record_type") == "status_control_turn_interrupted" for r in records)
    assert any(r.get("record_type") == "status_control_turn_skipped" for r in records)
    assert session.advance().ready


@pytest.mark.integration
def test_lv80_equipped_arlan_breaks_recovers_and_continues():
    _, _, session, commands = open_route("arlan_lv80_thunder_break")
    events = []
    for command in commands:
        decision, automatic = session.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        assert all(t.outcome.successor_eligible for t in automatic)
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        for transition in (*automatic, result.transition):
            events.extend(transition.transaction.events)
    breaks = [event for event in events if event.event_type == "break.triggered"]
    assert len(breaks) == 2
    assert all(event.payload["attacker_id"] == "arlan" and event.payload["element_type"] == "Thunder" for event in breaks)
    assert any(event.event_type == "break.recovered" for event in events)
    decision = session.advance()
    assert decision.ready, decision.blocked_reason
    choice = decision.availability.choices[0]
    query = choice.target_query
    targets = [query.candidate_ids[0]] if query and query.selection_mode == "explicit" else []
    result = session.submit(command_from_json({**choice.command_template, "target_ids": targets}))
    assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
    assert session.advance().ready


@pytest.mark.integration
@pytest.mark.parametrize("low_hp,reference", [(False, 2621.79359765625), (True, 2720.7328296562496)])
def test_lv80_march_shield_matches_external_calculator(low_hp, reference):
    scenario, rules, session, commands = open_route("march_lv80_shield_and_counter")
    if low_hp:
        scenario["units"][0]["initial_condition"].update(hp_mode="ratio", hp_value="0.4")
        session = BattleSession(rules, scenario)
        commands = commands[:1]
    records = []
    for command in commands:
        decision, automatic = session.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        assert all(t.outcome.successor_eligible for t in automatic)
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        records.extend(_records((*automatic, result.transition)))
    shield = next(r["payload"] for r in records if r.get("record_type") == "shield")
    assert shield["target_id"] == "natasha"
    assert math.isclose(shield["amount"], reference, rel_tol=0.01)
    if not low_hp:
        assert any(r.get("record_type") == "shield_absorption" for r in records)
        assert any(r.get("record_type") == "damage" and r["payload"].get("attack_type") == "Insert"
                   and r["payload"].get("source_frame", {}).get("owner_id") == "march" for r in records)
    assert session.advance().ready


@pytest.mark.integration
def test_lv80_serval_direct_damage_shock_and_kill_buff():
    _, _, session, commands = open_route("serval_lv80_shock_and_equipment")
    assert session.state.units["serval"].energy == 15
    records = []
    for command in commands:
        decision, automatic = session.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        assert all(t.outcome.successor_eligible for t in automatic)
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        records.extend(_records((*automatic, result.transition)))
    # Independent Fribbels outputs for the unbuffed direct component, E0.
    for skill, expected in ((110301, 1738.031048829728), (110302, 2269.806910312666), (110303, 3506.69477937823)):
        damage = next(r["payload"] for r in records if r.get("record_type") == "damage"
                      and r["payload"].get("source_task_id", "").startswith(f"ability_task:ability_phase:avatar_skill:{skill}:"))
        assert not damage["crit_resolution"]["is_crit"]
        assert math.isclose(damage["amount"], expected, rel_tol=0.01)
    assert any(r.get("record_type") == "dot_damage" for r in records)
    assert any(r.get("record_type") == "additional_damage"
               and r["payload"].get("modifier_name") == "Avatar_Serval_Passive01Modifier" for r in records)
    assert "modifier:MAvatar_Serval_00_Tree03_AttackRatioUp" in session.state.units["serval"].statuses
    assert session.advance().ready


@pytest.mark.integration
@pytest.mark.parametrize("ultimate,reference", [(False, 1446.3531302283739), (True, 1900.9212568715773)])
def test_lv80_natasha_heal_matches_external_calculator_and_continues(ultimate, reference):
    # Fribbels d60f0375 native output; exact inputs and limitations are recorded
    # in docs/numeric_validation/records/m2-natasha-e0-lv80-23013-101-302-001.yaml.
    name = "natasha_lv80_heal_and_equipment"
    _, _, session, commands = open_route(name)
    if ultimate:
        path = Path(__file__).resolve().parents[1] / "examples/cli" / f"{name}.ultimate.commands.json"
        commands = json.loads(path.read_text())["commands"]
    assert session.state.skill_points == 4  # Passerby 4-piece battle entry.
    records = []
    for command in commands:
        decision, automatic = session.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        assert all(t.outcome.successor_eligible for t in automatic)
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        records.extend(_records((*automatic, result.transition)))
    heal = next(r["payload"] for r in records if r.get("record_type") == "heal"
                and r["payload"].get("target_id") == "natasha")
    assert math.isclose(heal["amount"], reference, rel_tol=0.01)
    assert math.isclose(heal["after"] - heal["before"], heal["amount"])
    if not ultimate:
        assert any(r.get("record_type") == "additional_damage"
                   and r["payload"].get("modifier_name") == "MEquip_23013_Main" for r in records)
        assert any(r.get("record_type") == "heal"
                   and "HOT_HPByMaxHP" in r["payload"].get("effect_id", "") for r in records)
    assert session.advance().ready
