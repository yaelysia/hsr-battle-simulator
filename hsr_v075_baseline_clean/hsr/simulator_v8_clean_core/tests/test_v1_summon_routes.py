"""V1 summon builds through public choices; no state injection."""
import math

import pytest

from hsr.simulator_v8_clean_core.battle_archive import write_archive
from hsr.simulator_v8_clean_core.session import command_from_json, rule_assumption_records
from hsr.simulator_v8_clean_core.systems.unit_stats import effective_unit_stat
from hsr.simulator_v8_clean_core.tests.test_ordinary_element_break_natural_routes import open_route
from hsr.simulator_v8_clean_core.tests.test_r05_ordinary_party_routes import _records


@pytest.mark.integration
def test_memory_charge_support_true_damage_epic_and_resummon(tmp_path):
    from hsr.simulator_v8_clean_core.systems.dynamic_values import store_from_state

    _, _, session, commands = open_route('memory_lv80_support_and_equipment')
    seen, supports, true_hits, basic_checked, healed = set(), 0, 0, False, False
    for command in commands:
        decision, automatic = session.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, (command, result.transition.outcome.reason_codes)
        for unit in session.state.units.values():
            if unit.template_id == 'servant:18007':
                seen.add(unit.unit_id)
                assert effective_unit_stat(unit, 'speed').value == 130
        charges = [entry['value'] for entry in store_from_state(session.state)['entries'].values()
                   if entry.get('hash') == '582796324' and entry.get('target_id') in seen]
        assert all(0 <= value <= 100 for value in charges)
        records = tuple(_records((*automatic, result.transition)))
        damage = [r['payload'] for r in records if r['record_type'] == 'damage']
        true_hits += sum(p['damage_formula_family'] == 'true_damage' and p['amount'] > 0 for p in damage)
        if command['action_id'] == 'avatar_skill:800701' and not basic_checked:
            hits = [p for p in damage if 'avatar_skill:800701' in p['damage_emission_id']]
            assert len(hits) == 1 and not hits[0]['crit_resolution']['is_crit']
            assert math.isclose(hits[0]['amount'], 623.7718684729729, rel_tol=.01)
            basic_checked = True
        if command['action_id'] == 'servant_skill:1800707':
            supports += 1
            assert [entry['value'] for entry in store_from_state(session.state)['entries'].values()
                    if entry.get('hash') == '582796324' and entry.get('target_id') == command['actor_id']] == [0]
            assert session.state.units['memory'].action_value == 0
            assert 'modifier:M_PlayerBoyServant_30_EnableSkill' not in session.state.units[command['actor_id']].statuses
        healed |= command['action_id'] == 'avatar_skill:800709'
    assert basic_checked and supports >= 2 and true_hits and healed and len(seen) >= 2
    assert any(session.state.units[unit_id].lifecycle_status == 'removed' for unit_id in seen)
    assert any(c['action_id'] == 'avatar_skill:800708' for c in commands)
    assert any(c['action_id'] == 'avatar_skill:800701' for c in commands[8:])
    write_archive(tmp_path / 'memory_v1_complete.json.gz', session.archive())


@pytest.mark.integration
def test_hyacine_heals_ica_extra_actions_duration_and_equipment(tmp_path):
    from hsr.simulator_v8_clean_core.systems.dynamic_values import store_from_state

    _, _, session, commands = open_route('hyacine_lv80_healing_and_equipment')
    counts, memo_hits, heals, basic_checked = set(), 0, 0, False
    for command in commands:
        decision, automatic = session.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, (command, result.transition.outcome.reason_codes)
        for unit in session.state.units.values():
            if unit.template_id == 'servant:11409':
                assert effective_unit_stat(unit, 'speed').value == 0
        counts.update(entry['value'] for entry in store_from_state(session.state)['entries'].values()
                      if entry.get('target_id') == 'hyacine' and entry.get('hash') == '1859710505')
        records = tuple(_records((*automatic, result.transition)))
        heals += sum(r['record_type'] == 'heal' for r in records)
        for record in records:
            if record['record_type'] != 'damage':
                continue
            hit = record['payload']
            memo_hits += 'servant_skill:1140901' in hit['damage_emission_id'] and hit['amount'] > 1e-8
            if 'avatar_skill:140901' in hit['damage_emission_id'] and not basic_checked:
                assert hit['crit_resolution']['is_crit']  # A2 grants +100% CR.
                assert math.isclose(hit['amount'], 1158.1467868652346, rel_tol=.01)
                basic_checked = True
    assert basic_checked and memo_hits >= 2 and heals >= 10 and {0, 1, 2, 3} <= counts
    assert not any(c['actor_id'].startswith('summon:') for c in commands)  # Ica acts through extra-turn queue.
    assert any(r['payload']['assumption_id'] == 'hyacine_heal_tally_boundary'
               for r in rule_assumption_records(session.operations))
    write_archive(tmp_path / 'hyacine_v1_complete.json.gz', session.archive())


@pytest.mark.integration
def test_evernight_night_healing_resummon_enhancement_exit_and_equipment(tmp_path):
    import json
    from pathlib import Path
    from hsr.simulator_v8_clean_core.session import BattleSession

    scenario, rules, session, commands = open_route('evernight_lv80_night_and_equipment')
    seen, energy_stacks, basic_checked, entered, exited = set(), set(), False, False, False
    mode = 'modifier:MAvatar_Evernight_00_UltraMode'
    for command in commands:
        decision, automatic = session.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, (command, result.transition.outcome.reason_codes)
        owner = session.state.units['evernight']
        entered |= mode in owner.statuses
        exited |= entered and mode not in owner.statuses
        energy_stacks.update(d['stacks'] for d in owner.flags.get('status_details', ())
                             if d['modifier_name'] == 'MAvatar_Evernight_00_UltraMode_Energy')
        for unit in session.state.units.values():
            if unit.template_id == 'servant:11413':
                seen.add(unit.unit_id)
                if unit.lifecycle_status == 'active':
                    assert effective_unit_stat(unit, 'speed').value == 160
        if command['action_id'] == 'avatar_skill:141301' and not basic_checked:
            hits = [r['payload'] for r in _records((result.transition,)) if r['record_type'] == 'damage'
                    and 'avatar_skill:141301' in r['payload'].get('damage_emission_id', '')]
            assert len(hits) == 1 and not hits[0]['crit_resolution']['is_crit']
            assert math.isclose(hits[0]['amount'], 1822.7619930898568, rel_tol=.01)
            basic_checked = True
    assert basic_checked and entered and exited and {1, 2} <= energy_stacks and len(seen) >= 4
    assert any(c['action_id'] == 'servant_skill:1141307' for c in commands)
    assert any(r['payload']['assumption_id'] == 'evernight_party_count_alive_boundary'
               for r in rule_assumption_records(session.operations))
    write_archive(tmp_path / 'evernight_v1_complete.json.gz', session.archive())

    branch = BattleSession(rules, scenario)
    path = Path(__file__).resolve().parents[1] / 'examples/cli/evernight_lv80_night_and_equipment.heal.commands.json'
    for command in json.loads(path.read_text())['commands']:
        decision = branch.advance()
        assert decision.ready, decision.blocked_reason
        night = next(u for u in branch.state.units.values()
                     if u.template_id == 'servant:11413' and u.lifecycle_status == 'active')
        result = branch.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        if command['action_id'] == 'avatar_skill:141309':
            assert branch.state.units[night.unit_id].hp > night.hp
            assert branch.state.units[night.unit_id].lifecycle_status == 'active'
    write_archive(tmp_path / 'evernight_existing_night_healed.json.gz', branch.archive())


@pytest.mark.integration
def test_castorice_joint_breath_finisher_resummon_lifetime_and_equipment(tmp_path):
    import json
    from pathlib import Path

    _, _, session, commands = open_route('castorice_lv80_netherwing_and_equipment')
    seen, breath_turns, breath_ratios, basic_checked, finished = set(), [], [], False, False
    for command in commands:
        decision = session.advance()
        assert decision.ready, decision.blocked_reason
        action = command['action_id']
        if action in {'servant_skill:1140702', 'servant_skill:1140710', 'servant_skill:1140711'}:
            breath_turns.append(session.state.global_flags['active_turn']['turn_sequence_index'])
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, (command, result.transition.outcome.reason_codes)
        records = tuple(_records((result.transition,)))
        hits = [r['payload'] for r in records if r['record_type'] == 'damage']
        if action == 'avatar_skill:140701' and not basic_checked:
            assert len(hits) == 2 and all(not h['crit_resolution']['is_crit'] for h in hits)
            assert math.isclose(sum(h['amount'] for h in hits), 1872.3072661053538, rel_tol=.01)
            basic_checked = True
        if action in {'servant_skill:1140702', 'servant_skill:1140710', 'servant_skill:1140711'}:
            breath_ratios.append(hits[0]['scaling_ratio'])
        if action == 'servant_skill:1140712':
            assert len(hits) == 6
            assert session.state.units[command['actor_id']].lifecycle_status == 'removed'
            assert len([r for r in records if r['record_type'] == 'heal']) == 2
            finished = True
        for unit in session.state.units.values():
            if unit.template_id == 'servant:11407':
                seen.add(unit.unit_id)
                if unit.lifecycle_status == 'active':
                    assert effective_unit_stat(unit, 'speed').value == 165
    assert basic_checked and finished and len(seen) == 2
    assert len(breath_turns) == 3 and len(set(breath_turns)) == 1
    assert all(math.isclose(value, expected) for value, expected in zip(breath_ratios, (.24, .28, .34)))
    assert any(r['payload']['assumption_id'] == 'netherwing_breath_chain_settlement_window'
               for r in rule_assumption_records(session.operations))
    write_archive(tmp_path / 'castorice_v1_complete.json.gz', session.archive())

    branch = session.fork(44)  # First 22 public choices: immediately after the first summon.
    path = Path(__file__).resolve().parents[1] / 'examples/cli/castorice_lv80_netherwing_and_equipment.lifetime.commands.json'
    lifetime_commands = json.loads(path.read_text())['commands']
    assert [{k: c[k] for k in ('actor_id', 'action_id', 'action_level', 'target_ids')} for c in lifetime_commands[:22]] == commands[:22]
    turn_begins = 0
    for command in lifetime_commands[22:]:
        decision, automatic = branch.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        turn_begins += sum(e.event_type == 'turn.begin' and (e.source_id or '').startswith('summon:')
                           for t in automatic for e in t.transaction.events)
        if command['action_id'] == 'servant_skill:1140712':
            unit = branch.state.units[command['actor_id']]
            assert unit.hp == unit.max_hp
            assert 'modifier:MServant_CastoriceServant_TiggerKiller' in unit.statuses
        result = branch.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
    assert turn_begins == 3
    assert branch.state.units[lifetime_commands[-1]['actor_id']].lifecycle_status == 'removed'
    write_archive(tmp_path / 'castorice_lifetime_complete.json.gz', branch.archive())

    branch = session.fork(44)
    path = path.with_name('castorice_lv80_netherwing_and_equipment.lock.commands.json')
    lock_commands = json.loads(path.read_text())['commands']
    locked = False
    for command in lock_commands[22:]:
        decision = branch.advance()
        assert decision.ready, decision.blocked_reason
        dragon = next(u for u in branch.state.units.values()
                      if u.template_id == 'servant:11407' and u.lifecycle_status == 'active')
        result = branch.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        if any(m.path == ('units', 'castorice', 'hp') and m.after == 1.0 and m.metadata.get('lock_key')
               for m in result.transition.transaction.mutations):
            locked = True
            assert branch.state.units[dragon.unit_id].hp < dragon.hp
    assert locked and branch.state.units['castorice'].hp > 0
    write_archive(tmp_path / 'castorice_hp_lock_complete.json.gz', branch.archive())


@pytest.mark.integration
def test_jingyuan_technique_lord_hits_energy_traces_and_equipment(tmp_path):
    _, _, session, commands = open_route('jingyuan_lv80_lord_and_equipment')
    def lord():
        return next(u for u in session.state.units.values() if u.flags.get('entity_type') == 'battle_event')
    def count():
        return next(d['dynamic_values']['ATKCount'] for d in lord().flags['status_details']
                    if d['modifier_name'] == 'MAvatar_JingYuan_00_BattleEvent_ATKCountShowText')
    assert session.state.units['jingyuan'].energy == 130  # 115 input + 15 A4.
    assert count() == 6 and effective_unit_stat(lord(), 'speed').value == 90  # Technique +3.
    observed, basic_checked, energy_checked, blast_checked = set(), False, False, False
    for command in commands:
        decision, automatic = session.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        for transition in automatic:
            for unit in transition.after.to_json(detach=False)['units'].values():
                if unit['flags'].get('entity_type') == 'battle_event':
                    observed.update(d['dynamic_values']['ATKCount'] for d in unit['status_details']
                                    if d['modifier_name'] == 'MAvatar_JingYuan_00_BattleEvent_ATKCountShowText')
            hits = [r['payload'] for r in _records((transition,)) if r['record_type'] == 'damage'
                    and r['payload'].get('attack_type') == 'Insert']
            if not blast_checked and any(math.isclose(hit['scaling_ratio'], .165) for hit in hits):
                blast_checked = True
                assert all(hit['crit_resolution']['crit_damage'] == .75 for hit in hits)
        before = session.state.units['jingyuan'].energy
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        if command['action_id'] == 'avatar_skill:120401' and not basic_checked:
            hits = [r['payload'] for r in _records((result.transition,)) if r['record_type'] == 'damage']
            assert len(hits) == 2
            for hit, reference in zip(hits, (887.5681842761473, 1084.8055585597358)):
                assert not hit['crit_resolution']['is_crit']
                assert math.isclose(hit['amount'], reference, rel_tol=.01)
            basic_checked = True
        if command['action_id'] == 'avatar_skill:120402' and not energy_checked:
            assert session.state.units['jingyuan'].energy - before == 30
            assert 'modifier:MAvatar_JingYuan_00_Tree03_CriticalChanceUp' in session.state.units['jingyuan'].statuses
            energy_checked = True
        observed.add(count())
        assert effective_unit_stat(lord(), 'speed').value == 60 + (count() - 3) * 10
    assert {3, 10} <= observed
    assert basic_checked and energy_checked and blast_checked
    assert any(r['payload']['assumption_id'] == 'jingyuan_skill_energy_timing'
               for r in rule_assumption_records(session.operations))
    write_archive(tmp_path / 'jingyuan_v1_complete.json.gz', session.archive())


@pytest.mark.integration
def test_aglaea_joint_countdown_retained_speed_resummon_and_equipment(tmp_path):
    _, _, session, commands = open_route('aglaea_lv80_joint_and_equipment')
    seen, joint_count, basic_checked, retained = set(), 0, False, False
    for command in commands:
        decision, automatic = session.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, (command, result.transition.outcome.reason_codes)
        for u in session.state.units.values():
            if u.flags.get('summon_kind') == 'servant':
                seen.add(u.unit_id)
            if u.template_id == 'battle_event:11402' and u.lifecycle_status == 'active':
                assert effective_unit_stat(u, 'speed').value == 100
        if command['action_id'] == 'avatar_skill:140201' and not basic_checked:
            hits = [r['payload'] for r in _records((result.transition,)) if r['record_type'] == 'damage']
            assert len(hits) == 3
            # Split fractions are source inputs, not independently measured.
            for hit, fraction in zip(hits, (.2, .2, .6)):
                reference = 2926.4691333778915 if hit['crit_resolution']['is_crit'] else 1950.9794239962393
                assert math.isclose(hit['amount'], reference * fraction, rel_tol=.01)
            basic_checked = True
        joint_count += command['action_id'] == 'avatar_skill:140208'
        if command['action_id'] == 'avatar_skill:140202':
            memo = next(u for u in session.state.units.values() if u.flags.get('summon_kind') == 'servant'
                        and u.lifecycle_status == 'active')
            speed = next(d for d in memo.flags['status_details'] if d['modifier_name'] == 'MServant_AglaeaServant_00_AddSpeed')
            assert speed['stacks'] == 1 and speed['dynamic_values']['SpeedAddTotal'] == 55
            retained = True
    assert len(seen) == 2 and joint_count >= 2 and basic_checked and retained
    assert any(u.lifecycle_status == 'removed' for u in session.state.units.values() if u.unit_id in seen)
    assert any(r['payload']['assumption_id'] == 'aglaea_countdown_speed_retention'
               for r in rule_assumption_records(session.operations))
    write_archive(tmp_path / 'aglaea_v1_complete.json.gz', session.archive())


@pytest.mark.integration
def test_danhengpt_dragon_owner_transfer_enhancement_cap_and_equipment(tmp_path):
    _, _, session, commands = open_route('danhengpt_lv80_dragon_and_equipment')
    owners, counts, extra_owners, ratios = set(), set(), set(), set()
    basic_checked, followup = False, False
    for command in commands:
        decision, automatic = session.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, (command, result.transition.outcome.reason_codes)
        for transition in (*automatic, result.transition):
            snapshot = transition.after.to_json(detach=False)
            store = snapshot['global_flags']['dynamic_value_store']
            counts.update(store['entries'][key]['value'] for key in store['by_name'].get('DanHengPT_Passive_Count', ()))
            for u in snapshot['units'].values():
                if u['template_id'] == 'battle_event:11414':
                    owners.add(u['flags']['owner_id'])
            for record in _records((transition,)):
                if record['record_type'] != 'damage':
                    continue
                p = record['payload']
                followup |= p['attack_type'] == 'Insert'
                if p['attack_type'] == 'Pursued':
                    extra_owners.add(p['source_frame']['owner_id'])
                    ratios.add(p['scaling_ratio'])
        if command['action_id'] == 'avatar_skill:141401' and not basic_checked:
            hits = [r['payload'] for r in _records((result.transition,)) if r['record_type'] == 'damage']
            assert len(hits) == 2 and all(not h['crit_resolution']['is_crit'] for h in hits)
            assert math.isclose(sum(h['amount'] for h in hits), 1371.6610033195775, rel_tol=.01)
            basic_checked = True
        for u in session.state.units.values():
            if u.template_id == 'battle_event:11414':
                assert effective_unit_stat(u, 'speed').value == 165
    assert owners == extra_owners == {'danhengpt', 'natasha'}
    assert {0, 1, 2} <= counts and {.4, .8} <= ratios
    assert basic_checked and followup
    assert all(session.state.units[uid].shield_instances for uid in ('danhengpt', 'natasha'))
    assert any(r['payload']['assumption_id'] == 'shield_falling_cap_retains_existing'
               for r in rule_assumption_records(session.operations))
    write_archive(tmp_path / 'danhengpt_v1_complete.json.gz', session.archive())


@pytest.mark.integration
def test_lingsha_fuyuan_last_action_resummon_count_cap_and_equipment(tmp_path):
    _, _, session, commands = open_route('lingsha_lv80_fuyuan_and_equipment')
    seen, counts, healed, emergency, basic_checked = set(), set(), False, False, False
    replenishment = None
    for index, command in enumerate(commands):
        decision, automatic = session.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        transitions = (*automatic, result.transition)
        for transition in transitions:
            for uid, unit in transition.after.to_json(detach=False)['units'].items():
                if unit['template_id'] != 'battle_event:11222':
                    emergency |= any(d['modifier_name'] == 'MAvatar_Lingsha_00_PointB3_CD'
                                     for d in unit['status_details'])
                    continue
                seen.add(uid)
                for detail in unit['status_details']:
                    if detail['modifier_name'].endswith('_BattleEvent_LifeTime'):
                        counts.add(detail['stacks'])
                        assert detail['stacks'] == detail['dynamic_values']['_AttackTime']
            for record in _records((transition,)):
                healed |= record['record_type'] == 'heal' and record['payload'].get('amount', 0) > 0
        if index == 12:
            fuyuan_ids = {uid for uid, unit in session.state.units.items()
                          if unit.template_id == 'battle_event:11222'}
            # One ally falls below the source 60% threshold: exactly one
            # emergency is queued, regardless of the two-member target group.
            assert sum(entry.get('actor_id') in fuyuan_ids for queue in session.state.queues.values()
                       for entry in queue) == 1
        for unit in session.state.units.values():
            if unit.template_id == 'battle_event:11222' and unit.lifecycle_status == 'active':
                assert effective_unit_stat(unit, 'speed').value == 90
        if command['action_id'] == 'avatar_skill:122201' and not basic_checked:
            hit = next(r['payload'] for r in _records((result.transition,)) if r['record_type'] == 'damage')
            assert not hit['crit_resolution']['is_crit']
            assert math.isclose(hit['amount'], 966.2053740166346, rel_tol=.01)
            basic_checked = True
        if command['action_id'] == 'avatar_skill:122202' and replenishment is None:
            replenishment = session.fork()
    assert {1, 2, 3} <= counts and len(seen) >= 3
    assert basic_checked and healed and emergency
    retired = [u for u in session.state.units.values() if u.template_id == 'battle_event:11222'
               and u.lifecycle_status == 'removed']
    assert len(retired) >= 2 and all(not u.statuses for u in retired)
    assert any(r['payload']['assumption_id'] == 'fuyuan_last_action_lifetime'
               for r in rule_assumption_records(session.operations))
    write_archive(tmp_path / 'lingsha_v1_complete.json.gz', session.archive())

    # Repeat the same public route from the first summon, then replenish an
    # existing Fuyuan instead of using the next basic. No state is injected.
    assert replenishment is not None
    for command in commands[10:16]:
        decision = replenishment.advance()
        assert decision.ready, decision.blocked_reason
        if command['action_id'] == 'avatar_skill:122201':
            command = {**command, 'action_id': 'avatar_skill:122202', 'action_level': 10, 'target_ids': []}
        result = replenishment.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
    unit = next(u for u in replenishment.state.units.values() if u.template_id == 'battle_event:11222')
    detail = next(d for d in unit.flags['status_details'] if d['modifier_name'].endswith('_BattleEvent_LifeTime'))
    assert detail['stacks'] == detail['dynamic_values']['_AttackTime'] == 5


@pytest.mark.integration
def test_topaz_auto_debt_numby_speed_enhancement_and_equipment(tmp_path):
    _, _, session, commands = open_route('topaz_lv80_numby_and_equipment')
    assert 'modifier:MAvatar_Topaz_00_Skill02_SpecialMarkAdder' in session.state.units['topaz'].statuses
    targets, counts, basic_checked, automatic_damage = set(), set(), False, False
    def inspect(snapshot):
        marked = [uid for uid, u in snapshot['units'].items() if u['side'] == 'enemy' and u['hp'] > 0
            and any(d['modifier_name'] == 'MAvatar_Topaz_BETargetTag' for d in u['status_details'])]
        assert len(marked) <= 1
        targets.update(marked)
        for u in snapshot['units'].values():
            if u['flags'].get('entity_type') == 'battle_event':
                counts.add(next((d['dynamic_values']['ATKCount'] for d in u['status_details']
                    if d['modifier_name'] == 'MAvatar_Topaz_BE_UltraEnhance_ShowText'), 0))
    for command in commands:
        decision, automatic = session.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        for transition in automatic:
            inspect(transition.after.to_json(detach=False))
            automatic_damage |= any(r['record_type'] == 'damage' and r['payload'].get('attack_type') == 'Insert'
                                    for r in _records((transition,)))
        numby = next(u for u in session.state.units.values() if u.flags.get('entity_type') == 'battle_event')
        assert effective_unit_stat(numby, 'speed').value == 80
        if command['action_id'] == 'avatar_skill:111201' and not basic_checked:
            marked = [u for u in session.state.units.values() if u.side == 'enemy' and u.hp > 0
                      and any(d['modifier_name'] == 'MAvatar_Topaz_BETargetTag' for d in u.flags['status_details'])]
            assert len(marked) == 1  # The first friendly turn supplies a debt target before any Skill.
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        inspect(result.transition.after.to_json(detach=False))
        if command['action_id'] == 'avatar_skill:111201' and not basic_checked:
            hit = next(r['payload'] for r in _records((result.transition,)) if r['record_type'] == 'damage')
            assert hit['attack_type'] == 'Insert' and not hit['crit_resolution']['is_crit']
            assert math.isclose(hit['amount'], 1458.1746956366444, rel_tol=.01)
            basic_checked = True
    assert basic_checked and automatic_damage and len(targets) == 2 and {0, 1, 2} <= counts
    assert any(r['payload']['assumption_id'] == 'topaz_debt_window' for r in rule_assumption_records(session.operations))
    write_archive(tmp_path / 'topaz_v1_complete.json.gz', session.archive())
