"""Real source multi-wave battle and atomic subsequent-monster startup."""
import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.battle_archive import _json_equal, read_archive, restore_session, write_archive
from hsr.simulator_v8_clean_core.builds.models import CharacterBuildInput
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.systems.scheduler import CombatScheduler
from hsr.simulator_v8_clean_core.systems.dynamic_values import monster_skill_param_binding_sources
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

pytestmark = pytest.mark.integration


@lru_cache(maxsize=1)
def _case():
    core = Path(__file__).resolve().parents[1]
    scenario = json.loads((core / 'examples/cli/arlan_serval_natasha_two_waves.json').read_text())
    return build_battle_rulebook(core.parents[2] / 'turnbasedgamedata-main', scenario), scenario


def _cleared_boundary(rules, scenario):
    session = BattleSession(rules, scenario, diagnostics="full")
    assert session.advance().ready
    # Cleared-boundary fixture only; the whole-battle test below executes damage.
    return replace(session.state, units={uid: replace(unit, hp=0., lifecycle_status='defeated')
                   if unit.side == 'enemy' else unit for uid, unit in session.state.units.items()})


def test_later_wave_has_passives_creation_and_auditable_state():
    rules, scenario = _case()
    # Four SkillParams exist, but only damage's own hash emits a direct hit.
    emissions = [e for e in rules.ir.damage_emissions if e.action_id == 'monster_skill:100205001']
    assert len(emissions) == 1 and emissions[0].coverage_status == 'executable'
    assert emissions[0].scaling_basis_expr['param_index'] == 0
    before = _cleared_boundary(rules, scenario)
    gunner = next(u for u in before.units.values() if u.template_id == 'monster:1002050')
    sources = monster_skill_param_binding_sources(rules, before, gunner.unit_id, 'monster_skill:100205001', 1)
    assert len(sources) == 1 and len(sources[0]['by_hash']) == 4
    assert not monster_skill_param_binding_sources(rules, before, 'arlan', 'monster_skill:100205001', 1)
    assert not monster_skill_param_binding_sources(rules, before, gunner.unit_id, 'avatar_skill:100802', 1)
    result = CombatScheduler(rules)._try_wave_transition(before)
    assert result.transition.outcome.successor_eligible, result.transition.outcome.to_json()
    after = result.after_state
    assert after.wave_index == 1
    for uid, unit in before.units.items():
        if unit.side == 'ally':
            assert after.units[uid] == unit
        else:
            assert after.units[uid].lifecycle_status == 'removed' and after.units[uid].hp == 0
    enemies = [u for u in after.units.values() if u.side == 'enemy' and u.lifecycle_status == 'active']
    assert len(enemies) == 3
    for unit in enemies:
        assert unit.flags['toughness_reduction_mode'] == 'status'
        original = next(u for u in before.units.values() if u.template_id == unit.template_id)
        assert unit.flags['monster_stance_count'] == original.flags['monster_stance_count']
        names = [d['modifier_name'] for d in unit.flags['status_details']]
        assert set(names) == {d['modifier_name'] for d in original.flags['status_details']}
        assert len(names) == len(set(names))
        for event_type in ('unit.created', 'wave.monster'):
            assert sum(e.event_type == event_type and e.target_id == unit.unit_id
                       for e in result.transition.transaction.events) == 1
    audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
    assert audit.ok, audit.to_json()
    assert MutationReducer().replay_snapshot(before, result.transition.transaction.mutations,
                                             after.snapshot().to_json()).ok


def test_later_wave_startup_failure_rolls_back_entire_transition(monkeypatch):
    rules, scenario = _case()
    before = _cleared_boundary(rules, scenario)
    card = rules.monster_data_card_for_entity(next(u.template_id for u in before.units.values()
                                                  if u.side == 'enemy'))
    slot = next(s for s in rules.passive_mechanism_slots_for_card(card.card_id)
                if s.coverage_status == 'executable')
    admitted = slot.semantics['startup_admission']['admitted_tasks']
    tasks = [rules.ability_task(item['task_id']) for item in admitted]
    effect_id = next(t.effect_id for t in reversed(tasks) if t.effect_id)
    effect = rules.effect
    monkeypatch.setattr(type(rules), 'effect', lambda self, identity: None if identity == effect_id else effect(identity))
    result = CombatScheduler(rules)._try_wave_transition(before)
    assert result is not None and not result.transition.outcome.successor_eligible
    assert result.after_state == before
    assert result.after_state.snapshot().to_json() == before.snapshot().to_json()
    assert not result.transition.transaction.mutations and not result.transition.rng_events
    assert 'wave_monster_startup_blocked' in result.transition.outcome.reason_codes


def test_real_two_wave_battle_completes_with_archive(tmp_path):
    rules, scenario = _case()
    session = BattleSession(rules, scenario, diagnostics="full")
    seen_waves = set()
    submitted = 0
    for _ in range(100):
        decision = session.advance()
        seen_waves.add(session.state.wave_index)
        if session.outcome:
            break
        assert decision.ready, decision.blocked_reason
        choices = decision.availability.choices
        preferred = ([c for c in choices if c.choice_kind == 'ultimate_window']
                     or [c for c in choices if c.choice_kind == 'manual_ultimate_request' and c.actor_id == 'arlan']
                     or [c for c in choices if c.choice_kind == 'timeline_actor'
                         or c.choice_kind == 'normal_action' and
                         (c.actor_side == 'enemy' or c.action_id in {'avatar_skill:100802', 'avatar_skill:110302'})]
                     or [c for c in choices if c.choice_kind == 'normal_action' and c.action_id == 'avatar_skill:110501'])
        choice = preferred[0]
        targets = ([choice.target_query.candidate_ids[0]]
                   if choice.target_query and choice.target_query.selection_mode == 'explicit' else [])
        if choice.actor_id == 'arlan' and targets:
            # This external route defeats enemies before their blocked actions;
            # it validates wave lifecycle, not all actions in this stage.
            targets = sorted(choice.target_query.candidate_ids,
                             key=lambda uid: session.state.units[uid].template_id != 'monster:1002050')[:1]
        result = session.submit(command_from_json({**choice.command_template, 'target_ids': targets}))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.to_json()
        submitted += 1
        if submitted == 2:
            # Save after an action, with an unfinished wave; restoration must
            # replay it, not initialize a fresh battle from the final snapshot.
            checkpoint = write_archive(tmp_path / 'two-wave-checkpoint.json.gz', session.archive())
            saved = read_archive(checkpoint)
            tampered = {**saved, 'final_snapshot': {**saved['final_snapshot'], 'wave_index': 999}}
            with pytest.raises(ValueError, match='final_snapshot_mismatch'):
                restore_session(tampered, rules)
            resumed = restore_session(saved, rules)
            assert _json_equal(resumed.state.snapshot().to_json(detach=False),
                               session.state.snapshot().to_json(detach=False))
            assert _json_equal(resumed.operations, session.operations)
            saved['operations'][0]['blocked_reason'] = 'caller mutation'
            assert resumed.operations[0]['blocked_reason'] != 'caller mutation'
            session = resumed
            print(f'checkpoint: {checkpoint}')
    assert seen_waves == {0, 1} and session.outcome == 'victory'
    assert session.state.units['arlan'].hp > 0
    assert submitted == 4
    path = write_archive(tmp_path / 'two-wave-battle.json.gz', session.archive())
    print(f'archive: {path}')


def test_gunner_bleed_executes_and_ticks_on_the_natural_target_turn():
    rules, _ = _case()
    scenario = json.loads((Path(__file__).resolve().parents[1]
                           / 'examples/cli/arlan_melee_two_waves.json').read_text())
    session = BattleSession(rules, scenario, diagnostics="full")
    gunner_hit = False
    for _ in range(10):
        hp_before_turn = session.state.units['arlan'].hp
        decision = session.advance()
        assert decision.ready, decision.blocked_reason
        if gunner_hit and session.state.units['arlan'].hp < hp_before_turn:
            assert any(event['event_type'] == 'damage.hit'
                       for transition in session.operations[-1]['transitions']
                       for event in transition['events'])
            return
        choice = next(c for c in decision.availability.choices if c.choice_kind == 'timeline_actor'
                      or c.choice_kind == 'normal_action' and (c.actor_side == 'enemy'
                      or c.action_id in {'avatar_skill:100802', 'avatar_skill:110301', 'avatar_skill:110501'}))
        targets = []
        if choice.target_query and choice.target_query.selection_mode == 'explicit':
            candidates = choice.target_query.candidate_ids
            targets = [next((uid for uid in candidates
                            if uid == 'arlan' or session.state.units[uid].template_id == 'monster:1002040'), candidates[0])]
        result = session.submit(command_from_json({**choice.command_template, 'target_ids': targets}))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        if choice.actor_side == 'enemy' and choice.choice_kind == 'normal_action':
            assert choice.action_id == 'monster_skill:100205001'
            assert 'modifier:MCommon_DOT_Tear' in session.state.units['arlan'].statuses
            gunner_hit = True
    pytest.fail('the natural gunner bleed tick was not reached')


def test_melee_natural_turns_and_debuff_complete_two_wave_battle(tmp_path):
    rules, _ = _case()
    examples = Path(__file__).resolve().parents[1] / 'examples/cli'
    scenario = json.loads((examples / 'arlan_melee_two_waves.json').read_text())
    commands = json.loads((examples / 'arlan_melee_two_waves.commands.json').read_text())['commands']
    session = BattleSession(rules, scenario, diagnostics="full")
    enemy_turns = 0
    submitted = 0
    waves = set()
    for _ in range(40):
        decision = session.advance()
        waves.add(session.state.wave_index)
        if session.outcome:
            break
        assert decision.ready, decision.blocked_reason
        choice = next(c for c in decision.availability.choices if c.choice_kind == 'timeline_actor'
                      or c.choice_kind == 'normal_action' and (c.actor_side == 'enemy'
                      or c.action_id in {'avatar_skill:100802', 'avatar_skill:110301', 'avatar_skill:110501'}))
        targets = []
        if choice.target_query and choice.target_query.selection_mode == 'explicit':
            if choice.actor_side == 'enemy':
                targets = ['arlan']
            else:
                preferred = 'monster:1002050' if choice.actor_id == 'arlan' else 'monster:1002040'
                targets = sorted(choice.target_query.candidate_ids,
                                 key=lambda uid: session.state.units[uid].template_id != preferred)[:1]
        before = session.state
        command = commands[submitted]
        assert command == {'actor_id': choice.actor_id, 'action_id': choice.action_id,
                           'action_level': choice.action_level, 'target_ids': targets}
        result = session.submit(command_from_json(command))
        submitted += 1
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        if choice.actor_side == 'enemy' and choice.choice_kind == 'normal_action':
            assert choice.action_id == 'monster_skill:100204001'
            enemy_turns += 1
            assert session.state.units['arlan'].hp < before.units['arlan'].hp
            energy = [m for m in result.transition.transaction.mutations if m.path[-1] == 'energy']
            assert len(energy) == 1 and energy[0].metadata['resource_operation'] == 'hit_energy_gain'
            debuffs = [d for d in session.state.units['arlan'].flags['status_details']
                       if d['modifier_name'] == 'Monster_W1_Soldier01_00_DefenceRatioDown']
            assert len(debuffs) == 1 and debuffs[0]['duration'] == 2
            assert debuffs[0]['dynamic_values']['__by_name']['MDF_PropertyValue'] == .5
            audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
            assert audit.ok, audit.to_json()
            assert MutationReducer().replay_snapshot(before, result.transition.transaction.mutations,
                                                     session.state.snapshot().to_json()).ok
    assert session.outcome == 'victory' and waves == {0, 1} and enemy_turns == 4
    assert submitted == len(commands) == 19
    path = write_archive(tmp_path / 'two-wave-melee-battle.json.gz', session.archive())
    print(f'archive: {path}; natural melee turns: {enemy_turns}')
