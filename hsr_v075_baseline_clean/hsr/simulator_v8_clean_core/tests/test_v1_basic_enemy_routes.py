"""Roster enemies: native attacks and external received-damage comparisons."""
import math

import pytest

from hsr.simulator_v8_clean_core.session import command_from_json
from hsr.simulator_v8_clean_core.tests.test_ordinary_element_break_natural_routes import open_route
from hsr.simulator_v8_clean_core.tests.test_r05_ordinary_party_routes import _records


@pytest.mark.integration
def test_envoy_shake_lock_cleanse_skyfall_and_marked_timing(tmp_path):
    from hsr.simulator_v8_clean_core.battle_archive import write_archive
    from hsr.simulator_v8_clean_core.systems.action_selection import ActionTargetSelectionSystem

    _, rules, session, commands = open_route('aurumaton_envoy_lv66')
    boss = 'enemy:stage:3099044:wave:0:pos:0'
    shake, unstable = 'modifier:MCommon_Shake', 'modifier:MCommon_Unstable'
    lock = 'modifier:MMonster_W2_Valkyrie02_00_Skill04_Target'
    actions, assumptions = set(), set()
    compared = cleansed = False
    for command in commands:
        decision = session.advance()
        assert decision.ready, decision.blocked_reason
        action = command['action_id']
        if action == 'avatar_skill:100102' and shake in session.state.units['natasha'].statuses and not cleansed:
            original = session.state
            branch = session.fork()
            result = branch.submit(command_from_json({**command, 'target_ids': ['natasha']}))
            assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
            assert shake not in branch.state.units['natasha'].statuses
            assert lock in branch.state.units['natasha'].statuses
            targets = ActionTargetSelectionSystem(rules)
            assert targets.query(branch.state, boss, 'monster_skill:201302006', 1).candidate_ids == ('natasha',)
            assert not targets.query(branch.state, boss, 'monster_skill:201302004', 1).resolved
            assert session.state is original
            cleansed = True
        if action in {'monster_skill:201302004', 'monster_skill:201302006'}:
            offered = next(c for c in decision.availability.choices if c.action_id == action)
            assert offered.target_query.candidate_ids == ('natasha',)
            branch = session.fork()
            before = branch.state
            rejected = branch.submit(command_from_json({**command, 'target_ids': ['march']}))
            assert not rejected.transition.outcome.successor_eligible
            assert branch.state == before
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        records = list(_records((result.transition,)))
        hits = [r['payload'] for r in records if r['record_type'] == 'damage']
        assumptions.update(r['payload']['assumption_id'] for r in records if r['record_type'] == 'rule_assumption'
                           and r['payload']['status'] == '未实证' and r['payload']['todo'])
        if action == 'monster_skill:201302002':
            assert unstable in session.state.units['natasha'].statuses
            assert shake not in session.state.units['natasha'].statuses
        elif action == 'monster_skill:201302001':
            assert shake in session.state.units['natasha'].statuses
            assert lock in session.state.units['natasha'].statuses
        elif action in {'monster_skill:201302004', 'monster_skill:201302006'}:
            ratios = [1, 1, 1, 1, 2] if action.endswith('004') else [1, 1, 1, 1]
            assert [h['amount'] / hits[0]['amount'] for h in hits] == pytest.approx(ratios)
            assert shake not in session.state.units['natasha'].statuses
            assert lock not in session.state.units['natasha'].statuses
        elif action == 'avatar_skill:110501' and not compared:
            assert not hits[0]['crit_resolution']['is_crit']
            assert math.isclose(hits[0]['amount'], 668.4990899352752, rel_tol=.01)
            compared = True
        if action.startswith('monster_skill:'):
            actions.add(action)
    assert actions == {f'monster_skill:20130200{i}' for i in (1, 2, 3, 4, 6)}
    assert {'envoy_lock_timing', 'after_attack_listener_snapshot'} <= assumptions
    assert compared and cleansed and session.advance().ready
    write_archive(tmp_path / 'envoy_v1_complete.json.gz', session.archive())


@pytest.mark.integration
def test_trampler_charge_target_entangle_stacks_and_expiry(tmp_path):
    from hsr.simulator_v8_clean_core.battle_archive import write_archive

    _, _, session, commands = open_route('voidranger_trampler_lv40')
    boss = 'enemy:stage:301005:wave:0:pos:0'
    charge = 'modifier:Monster_AML_Elite01_00_Endurance'
    aim = 'modifier:MMonster_AML_Elite01_00_Aim'
    counts, actions = set(), set()
    compared, delayed = False, []
    for command in commands:
        decision, automatic = session.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        delayed.extend(r['payload'] for r in _records(automatic) if r['record_type'] == 'additional_damage'
                       and r['payload'].get('modifier_name') == 'MCommon_Entangle')
        action = command['action_id']
        if action == 'monster_skill:801301005':
            offered = [c for c in decision.availability.choices if c.actor_id == boss]
            assert [c.action_id for c in offered] == [action]
            assert offered[0].target_query.candidate_ids == ('natasha',)
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        hits = [r['payload'] for r in _records((result.transition,)) if r['record_type'] == 'damage']
        if action == 'monster_skill:801301004':
            assert not hits and charge in session.state.units[boss].statuses
            assert aim in session.state.units['natasha'].statuses
        elif action == 'monster_skill:801301005':
            assert len(hits) == 1 and hits[0]['element_type'] == 'Quantum'
            assert charge not in session.state.units[boss].statuses
            assert aim not in session.state.units['natasha'].statuses
        elif action == 'avatar_skill:110501' and not compared:
            assert not hits[0]['crit_resolution']['is_crit']
            assert math.isclose(hits[0]['amount'], 777.1301920497575, rel_tol=.01)
            compared = True
        for detail in session.state.units['natasha'].flags.get('status_details', ()):
            if detail.get('modifier_name') == 'MCommon_Entangle':
                counts.add(detail['stacks'])
                assert detail['stacks'] == detail['dynamic_values']['MDF_BeingHitDamageValue'] + 1
        if command['actor_id'] == boss and action.startswith('monster_skill:'):
            actions.add(action)
    decision, automatic = session.advance_with_transitions()
    delayed.extend(r['payload'] for r in _records(automatic) if r['record_type'] == 'additional_damage'
                   and r['payload'].get('modifier_name') == 'MCommon_Entangle')
    assert decision.ready and compared and counts == {1, 2, 3, 4}
    assert actions == {f'monster_skill:80130100{i}' for i in (1, 2, 3, 4, 5)}
    assert len(delayed) == 1 and delayed[0]['element_type'] == 'Quantum' and delayed[0]['amount'] > 0
    assert 'modifier:MCommon_Entangle' not in session.state.units['natasha'].statuses
    write_archive(tmp_path / 'trampler_v1_complete.json.gz', session.archive())


@pytest.mark.integration
def test_weaver_blast_enhancement_and_passive_admission(tmp_path):
    from hsr.simulator_v8_clean_core.battle_archive import write_archive

    _, _, session, commands = open_route('imaginary_weaver_lv76')
    buff = 'modifier:XP_Minion02_00_Attack'
    actions = set()
    compared = False
    for command in commands:
        decision = session.advance()
        assert decision.ready, decision.blocked_reason
        action, actor_id = command['action_id'], command['actor_id']
        if action.startswith('monster_skill:'):
            enhanced = buff in session.state.units[actor_id].statuses
            offered = {c.action_id for c in decision.availability.choices if c.actor_id == actor_id}
            assert offered == {'monster_skill:800201003',
                               'monster_skill:800201002' if enhanced else 'monster_skill:800201001'}
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        records = list(_records((result.transition,)))
        hits = [r['payload'] for r in records if r.get('record_type') == 'damage']
        energy = [r['payload'] for r in records if r.get('record_type') == 'hit_energy_gain']
        if action == 'monster_skill:800201003':
            assert len(hits) == 2
            assert {(p['target_id'], p['raw_energy_gain']) for p in energy} == {('natasha', 10), ('march', 10)}
            assert buff in session.state.units[actor_id].statuses
        elif action == 'monster_skill:800201002':
            assert len(hits) == 3
            total = sum(p['amount'] for p in hits)
            assert [p['amount'] / total for p in hits] == pytest.approx([.3, .3, .4])
            assert all(p['formula_result']['multipliers']['damage_bonus'] == 2 for p in hits)
            assert [p['raw_energy_gain'] for p in energy] == [15, 15, 15]
            assert buff not in session.state.units[actor_id].statuses
        elif action == 'avatar_skill:110501' and not compared:
            assert not hits[0]['crit_resolution']['is_crit']
            assert math.isclose(hits[0]['amount'], 634.3919935100062, rel_tol=.01)
            compared = True
        if action.startswith('monster_skill:'):
            actions.add(action)
    assert actions == {f'monster_skill:80020100{i}' for i in (1, 2, 3)}
    assert compared and session.advance().ready
    write_archive(tmp_path / 'weaver_v1_complete.json.gz', session.archive())


@pytest.mark.integration
def test_prowler_absorption_stacks_and_overheat(tmp_path):
    from hsr.simulator_v8_clean_core.battle_archive import write_archive
    from hsr.simulator_v8_clean_core.systems.unit_stats import effective_unit_stat

    _, _, session, commands = open_route('frigid_prowler_lv44')
    boss = 'enemy:stage:307211:wave:0:pos:0'
    rage = 'modifier:Monster_W1_Mecha03_01_Rage'
    heat = 'modifier:Monster_W1_Mecha03_01_Overheat'
    base_defense = effective_unit_stat(session.state.units[boss], 'defense').value
    bursts, absorbed, compared, overheated = 0, 0, False, False

    def live_minions():
        return {u.unit_id for u in session.state.units.values()
                if u.flags.get('summoner_id') == boss and u.hp > 0 and u.lifecycle_status == 'active'}

    for command in commands:
        decision = session.advance()
        assert decision.ready, decision.blocked_reason
        action = command['action_id']
        before_minions = live_minions()
        if action == 'monster_skill:102302009':
            assert rage in session.state.units[boss].statuses
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        records = list(_records((result.transition,)))
        hits = [r['payload'] for r in records if r.get('record_type') == 'damage']
        if action == 'avatar_skill:110501' and not compared:
            assert not hits[0]['crit_resolution']['is_crit']
            assert math.isclose(hits[0]['amount'], 606.5406376973718, rel_tol=.01)
            compared = True
        if action == 'monster_skill:102302005':
            assert len(live_minions()) == 2
        elif action == 'monster_skill:102302007':
            assert len(before_minions - live_minions()) == 1
            assert rage in session.state.units[boss].statuses
            assert not any(e.event_type == 'action.window.after_attack' for e in result.transition.transaction.events)
            assert not hits
            absorbed += 1
        elif action in ('monster_skill:102302001', 'monster_skill:102302009'):
            count = 5 if action.endswith('001') else 10
            assert len(hits) == count
            assert [p['amount'] for p in hits] == pytest.approx([hits[0]['amount']] * count)
            energy = [r['payload']['raw_energy_gain'] for r in records if r.get('record_type') == 'hit_energy_gain']
            assert energy == [2] * count
            if action.endswith('009'):
                bursts += 1
                assert rage not in session.state.units[boss].statuses
                detail = next(d for d in session.state.units['natasha'].flags['status_details']
                              if d['modifier_name'] == 'Monster_W1_Mecha03_01_Frozen')
                assert detail['stacks'] == bursts + 1
                assert {m['property']: m['value'] for m in detail['modifiers']} == pytest.approx({
                    'IceResistanceDelta': -.2 * (bursts + 1), 'SpeedAddedRatio': -.12 * (bursts + 1),
                })
            elif overheated:
                assert heat not in session.state.units[boss].statuses
                assert effective_unit_stat(session.state.units[boss], 'defense').value == pytest.approx(base_defense)
        elif action == 'monster_skill:102302008':
            assert not live_minions() and heat in session.state.units[boss].statuses
            assert effective_unit_stat(session.state.units[boss], 'defense').value == pytest.approx(base_defense * .5)
            overheated = True
    assert compared and overheated and bursts == absorbed == 2 and session.advance().ready
    write_archive(tmp_path / 'prowler_v1_complete.json.gz', session.archive())


@pytest.mark.integration
def test_guardian_bans_counter_cleanse_and_eight_bounces(tmp_path):
    from hsr.simulator_v8_clean_core.battle_archive import write_archive

    _, _, session, commands = open_route('guardian_shadow_lv40')
    boss = 'enemy:stage:301008:wave:0:pos:0'
    counter_name = 'Monster_XP_Elite02_00_SkillP01_Phase01'
    counters, compared, barrage, skill_branch = 0, False, False, False

    def guardian_counters(transitions):
        return [t for t in transitions if any(r.get('record_type') == 'standalone_ability_execution'
                and r['payload']['ability_name'] == counter_name for r in _records((t,)))]

    for command in commands:
        decision, automatic = session.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        for transition in guardian_counters(automatic):
            hits = [r for r in _records((transition,)) if r.get('record_type') == 'damage']
            assert len(hits) == 1
            counters += 1
        action, actor_id = command['action_id'], command['actor_id']
        silent = 'modifier:Monster_XP_Elite02_00_Edict03' in session.state.units[actor_id].statuses
        if action == 'avatar_skill:100102' and silent:
            before = session.state
            branch = session.fork()
            # Shielding another ally leaves March's own ban in place.
            result = branch.submit(command_from_json({**command, 'target_ids': ['natasha']}))
            assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
            branch_decision, branch_automatic = branch.advance_with_transitions()
            assert branch_decision.ready, branch_decision.blocked_reason
            assert len(guardian_counters(branch_automatic)) == 1
            assert session.state is before
            skill_branch = True
        branch = session.fork() if action == 'monster_skill:800303006' else None
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        records = list(_records((result.transition,)))
        hits = [r['payload'] for r in records if r.get('record_type') == 'damage']
        if action == 'avatar_skill:110501' and not compared:
            assert not hits[0]['crit_resolution']['is_crit']
            assert math.isclose(hits[0]['amount'], 777.1301920497575, rel_tol=.01)
            compared = True
        if silent and action in ('avatar_skill:100102', 'avatar_skill:110502'):
            assert 'modifier:Monster_XP_Elite02_00_Edict03' not in session.state.units[actor_id].statuses
        if action == 'monster_skill:800303006':
            assert len(hits) == 8
            assert [r['payload']['raw_energy_gain'] for r in records if r.get('record_type') == 'hit_energy_gain'] == [5] * 8
            rng = [e for e in result.transition.rng_events if e.rng_type == 'target_random']
            assert len(rng) == 8 and len({e.event_id for e in rng}) == 8
            assert all('modifier:MCommon_DOT_Electric' in session.state.units[u].statuses for u in ('natasha', 'march'))
            selected = rng[0].result['selected_outcome_id']
            alternative = 'march' if selected == 'natasha' else 'natasha'
            before = session.state
            fork_result = branch.submit(command_from_json({**command, 'metadata': {
                'rng_choices': {rng[0].metadata['choice_key']: alternative},
            }}))
            assert fork_result.transition.outcome.successor_eligible, fork_result.transition.outcome.reason_codes
            first = next(e for e in fork_result.transition.rng_events if e.rng_type == 'target_random')
            assert first.result['selected_outcome_id'] == alternative
            assert session.state is before
            barrage = True
        assert 'monster_skill:800303007' not in {c.action_id for c in decision.availability.choices}
    assert compared and barrage and skill_branch and counters == 2 and session.advance().ready
    write_archive(tmp_path / 'guardian_v1_complete.json.gz', session.archive())


@pytest.mark.integration
@pytest.mark.parametrize('name,expected', [
    ('baryons', {'monster:8011010': 621.7041536398061, 'monster:8011020': 777.1301920497575}),
    ('silvermane', {'monster:1002040': 621.7041536398061, 'monster:1002050': 777.1301920497575}),
])
def test_basic_enemy_actions_and_received_damage(name, expected):
    _, _, session, commands = open_route(f'basic_enemies_{name}_lv40')
    attacked, compared = set(), set()
    shields = 0
    for command in commands:
        decision = session.advance()
        assert decision.ready, decision.blocked_reason
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        if command['action_id'].startswith('monster_skill:'):
            attacked.add(session.state.units[command['actor_id']].template_id)
        if command['action_id'] == 'avatar_skill:100102':
            shields += 1  # Replacing an undamaged shield must also succeed.
        if command['action_id'] != 'avatar_skill:110501':
            continue
        target = session.state.units[command['target_ids'][0]]
        hit = next(r['payload'] for r in _records((result.transition,)) if r.get('record_type') == 'damage')
        assert target.level == 40 and not hit['crit_resolution']['is_crit']
        assert math.isclose(hit['amount'], expected[target.template_id], rel_tol=0.01)
        compared.add(target.template_id)
    assert attacked == compared == set(expected)
    assert shields == 2 and session.advance().ready


@pytest.mark.integration
def test_lieutenant_counter_thrust_and_summoned_guards(tmp_path):
    from hsr.simulator_v8_clean_core.battle_archive import write_archive

    _, _, session, commands = open_route('silvermane_lieutenant_lv44')
    boss = 'enemy:stage:307311:wave:0:pos:0'
    stance = 'modifier:MMonster_W1_Soldier03_00_ListenBeingAttacked'
    counter_count = 0
    guards = set()

    def five_hits(records):
        hits = [r['payload']['amount'] for r in records if r.get('record_type') == 'damage']
        assert len(hits) == 5
        assert [value / sum(hits) for value in hits] == pytest.approx([.2, .1, .1, .1, .5])
        energy = [r['payload']['raw_energy_gain'] for r in records if r.get('record_type') == 'hit_energy_gain']
        assert energy == [4, 2, 2, 2, 10]

    for index, command in enumerate(commands):
        decision, automatic = session.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        for transition in automatic:
            records = list(_records((transition,)))
            if any(r.get('record_type') == 'standalone_ability_execution' for r in records):
                five_hits(records)
                counter_count += 1
                assert stance not in session.state.units[boss].statuses
                delay = [m for m in transition.transaction.mutations if m.path == ('units', boss, 'action_value')]
                assert len(delay) == 1 and delay[0].after > delay[0].before
        if index == 7:
            # Avoid attacking the stance in a public branch, then actively thrust.
            branch = session.fork()
            heal = branch.submit(command_from_json({
                'actor_id': 'natasha', 'action_id': 'avatar_skill:110502',
                'action_level': 10, 'target_ids': ['natasha'],
            }))
            assert heal.transition.outcome.successor_eligible
            assert branch.advance().ready and stance in branch.state.units[boss].statuses
            thrust = branch.submit(command_from_json(commands[10]))
            assert thrust.transition.outcome.successor_eligible, thrust.transition.outcome.reason_codes
            five_hits(list(_records((thrust.transition,))))
            assert stance not in branch.state.units[boss].statuses and branch.advance().ready
            assert stance in session.state.units[boss].statuses
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        records = list(_records((result.transition,)))
        if index == 1:
            hit = next(r['payload'] for r in records if r.get('record_type') == 'damage')
            assert math.isclose(hit['amount'], 758.1757971217147, rel_tol=.01)
        if command['action_id'] == 'monster_skill:100301003':
            assert stance in session.state.units[boss].statuses
        if command['action_id'] == 'monster_skill:100301002':
            five_hits(records)
            assert stance not in session.state.units[boss].statuses
        if command['action_id'] == 'monster_skill:100204001':
            guards.add(command['actor_id'])
    assert counter_count == 1 and len(guards) == 2 and session.advance().ready
    assert all(session.state.units[guard].template_id == 'monster:1002040' for guard in guards)
    write_archive(tmp_path / 'lieutenant_v1_complete.json.gz', session.archive())


@pytest.mark.integration
def test_aurumaton_natural_sanction_keeps_two_actions_and_two_turns(tmp_path):
    from hsr.simulator_v8_clean_core.battle_archive import write_archive
    from hsr.simulator_v8_clean_core.systems.unit_stats import effective_unit_stat

    _, _, session, commands = open_route('aurumaton_lv70_sanction')
    boss = 'enemy:stage:402120485:wave:0:pos:0'
    mode = 'modifier:MMonster_W2_Mecha03_00_Overdrive_On'
    base_speed = effective_unit_stat(session.state.units[boss], 'speed').value
    pair = None
    completed_turns = 0
    for index, command in enumerate(commands):
        decision = session.advance()
        assert decision.ready, decision.blocked_reason
        actor = session.state.units[boss]
        action = command['action_id']
        if command['actor_id'] == boss:
            offered = {c.action_id for c in decision.availability.choices if c.actor_id == boss}
            assert 'monster_skill:201301001' not in offered
            assert offered == ({'monster_skill:201301003', 'monster_skill:201301004'} if mode in actor.statuses
                               else {'monster_skill:201301002'})
        if action == 'monster_skill:201301003':
            assert effective_unit_stat(actor, 'speed').value == pytest.approx(base_speed + 30)
            duration = next(d['remaining_duration'] for d in actor.flags['status_details'] if d['status_id'] == mode)
            assert duration == 2 - completed_turns
            pair = (session.state.global_flags['turn_sequence_index'], session.state.global_flags['global_av'], actor.action_value)
        if action == 'monster_skill:201301004':
            assert pair == (session.state.global_flags['turn_sequence_index'], session.state.global_flags['global_av'], actor.action_value)
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        records = list(_records((result.transition,)))
        if index in (1, 4):
            hit = next(r['payload'] for r in records if r.get('record_type') == 'damage')
            if index == 1:
                assert math.isclose(hit['amount'], 523.5403399072051, rel_tol=.01)
            else:
                assert hit['formula_result']['multipliers']['weaken'] == pytest.approx(.8)
        if action == 'monster_skill:201301003':
            assert session.state.global_flags['turn_owner_id'] == boss
            assert session.state.units[boss].action_value == pair[2]
        if action == 'monster_skill:201301004':
            completed_turns += 1
            assert (mode in session.state.units[boss].statuses) == (completed_turns == 1)
            assert 'modifier:MCommon_Confine' in session.state.units['natasha'].statuses
    guards = [u for u in session.state.units.values() if u.template_id == 'monster:2012010']
    assert completed_turns == 2 and len(guards) == 2 and session.advance().ready
    write_archive(tmp_path / 'aurumaton_v1_complete.json.gz', session.archive())
