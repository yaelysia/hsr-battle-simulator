"""Castorice content-processor routes through public advance/submit (M1-3).

Integration: real TBGD compilation, formal builds, public operations only.
The generic compiled path keeps owning Newbud, the ultimate cost, the spawn
and the dragon damage graphs; these routes verify the processor-owned
lifecycle gaps (re-creation after departure) and the content's targetability.
"""
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.equipment.models import EquipmentBuildInput
from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

pytestmark = pytest.mark.integration
_ROOT = Path(__file__).resolve().parents[4]
_ENEMY_ACTION = 'monster_skill:201301003'
_ENEMY = 'enemy:stage:307214:wave:0:pos:0'


def _unit(name, avatar_id, position, *, level=19):
    card = f'character_data_card:avatar:{avatar_id}'
    equipment = EquipmentBuildInput(build_id=f'{name}:equipment', character_card_id=card).to_json()
    return {
        'unit_id': name, 'side': 'ally', 'entity_ref': f'avatar:{avatar_id}', 'level': level,
        'eidolon_level': 0, 'position': position, 'build_mode': 'assembled_character_build',
        'character_build': {
            'build_id': f'{name}:build', 'character_card_id': card, 'level': level,
            'promotion': 0, 'eidolon_level': 0, 'unlocked_trace_node_ids': [],
            'equipment_build': equipment,
        },
        'initial_condition': {'hp_mode': 'full', 'initial_energy': '0', 'initial_resource_values': []},
    }


def _session():
    scenario = {
        'scenario_id': 'm1-3:castorice-processor', 'version': 'v0_200',
        'units': [_unit('ca', 1407, 0), _unit('nat', 1105, 1),
                  _unit('m1', 1104, 2), _unit('m2', 1107, 3)],
        'stage_ref': '307214', 'wave_index': 0, 'route': [],
        'battle_setup': {
            'world_level': 1, 'timeline': {'mode': 'runtime_initialize'},
            'metadata': {'stage_scope': 'wave_only', 'scope': 'M1-3 processor route'},
        },
    }
    rules = build_battle_rulebook(_ROOT / 'turnbasedgamedata-main', scenario)
    return BattleSession(rules, scenario)


def _dragons(session):
    return [uid for uid in session.state.units if uid.startswith('summon:servant:')]


def _pick(choices, actor, action):
    return next((item for item in choices if item.action_id == action
                 and item.command_template['actor_id'] == actor), None)


def _policy(session, seen):
    def policy(choices):
        window = next((item for item in choices if item.choice_kind == 'ultimate_window'), None)
        if window is not None:
            seen['ult'] += 1
            return window, None
        request = _pick(choices, 'ca', 'avatar_skill:140703')
        if request is not None and seen['ult'] < 8:
            return request, None
        servant = next((item for item in choices if item.choice_kind == 'summon_action'), None)
        if servant is not None:
            seen['dragon_actions'] += 1
            return servant, None
        heal = _pick(choices, 'nat', 'avatar_skill:110502') if session.state.skill_points > 0 else None
        if heal is not None:
            query = heal.target_query
            if query and query.selection_mode == 'explicit':
                target = min(query.candidate_ids,
                             key=lambda uid: session.state.units[uid].hp / session.state.units[uid].max_hp)
                return heal, [target]
            return heal, None
        ca = session.state.units['ca']
        skill = (_pick(choices, 'ca', 'avatar_skill:140702')
                 if session.state.skill_points > 1 and ca.hp > ca.max_hp * 0.5 else None)
        for choice in (skill, _pick(choices, 'ca', 'avatar_skill:140701'),
                       _pick(choices, 'nat', 'avatar_skill:110501'),
                       _pick(choices, 'm1', 'avatar_skill:110401'),
                       _pick(choices, 'm2', 'avatar_skill:110701')):
            if choice is not None:
                return choice, None
        attack = _pick(choices, _ENEMY, _ENEMY_ACTION)
        if attack is not None:
            teammates = [uid for uid in attack.target_query.candidate_ids if uid in {'nat', 'm1', 'm2'}]
            if _dragons(session):
                # Spread damage to keep the team alive: a defeated ally still
                # referenced by an enemy queue entry triggers the known generic
                # queue-staleness block (recorded limitation, not processor scope).
                teammates.sort(key=lambda uid: session.state.units[uid].hp, reverse=True)
            return attack, [(teammates or list(attack.target_query.candidate_ids))[0]]
        return choices[0], None
    return policy


def _drive(session, policy, steps):
    transitions = []
    for _ in range(steps):
        decision, automatic = session.advance_with_transitions()
        transitions.extend(automatic)
        assert all(item.outcome.successor_eligible for item in automatic), [
            item.outcome.reason_codes for item in automatic]
        if session.outcome:
            break
        assert decision.ready, decision.blocked_reason
        choices = list(decision.availability.choices)
        choice, targets = policy(choices)
        if targets is None:
            query = choice.target_query
            targets = [query.candidate_ids[0]] if query and query.selection_mode == 'explicit' else []
        result = session.submit(command_from_json({**choice.command_template, 'target_ids': targets}))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        transitions.append(result.transition)
    return transitions


def test_castorice_processor_mounted_and_dragon_recreated_after_departure():
    session = _session()
    # The catalog mounts both Castorice cards for this scenario.
    assert [m.content_id for m in session.rules.content_processors] == ['avatar:1407', 'servant:11407']
    seen = {'ult': 0, 'dragon_actions': 0}
    policy = _policy(session, seen)
    firstdragon = None
    departed = False
    recreated = None
    for _ in range(120):
        _drive(session, policy, 1)
        if session.outcome:
            break
        dragons = _dragons(session)
        if firstdragon is None and dragons:
            firstdragon = dragons[0]
        if firstdragon is not None and not departed:
            if session.state.units[firstdragon].lifecycle_status in {'defeated', 'removed'}:
                departed = True
        if departed and recreated is None:
            live = [uid for uid in dragons
                    if uid != firstdragon and session.state.units[uid].lifecycle_status == 'active']
            if live:
                recreated = live[0]
                break
    assert firstdragon is not None, 'first Netherwing was never created'
    assert departed, 'first Netherwing never departed within the route'
    assert recreated is not None, 'processor re-creation did not produce a second Netherwing'
    assert seen['ult'] >= 2 and seen['dragon_actions'] >= 1
    # The second instance is a fresh unit, not a resurrection of the old one.
    assert recreated != firstdragon
    assert session.state.units[recreated].flags.get('owner_id') == 'ca'
