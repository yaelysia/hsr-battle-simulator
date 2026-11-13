"""R07 derived-unit routes through the public advance/submit interface."""
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.builds.models import CharacterBuildInput
from hsr.simulator_v8_clean_core.equipment.models import EquipmentBuildInput
from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

pytestmark = pytest.mark.integration
_ROOT = Path(__file__).resolve().parents[4]
_ENEMY_ACTION = 'monster_skill:201301003'  # 201301002 remains an unadopted action.


def _unit(name, avatar_id, position, *, level=80, energy='0'):
    card = f'character_data_card:avatar:{avatar_id}'
    equipment = EquipmentBuildInput(build_id=f'{name}:equipment', character_card_id=card).to_json()
    return {
        'unit_id': name, 'side': 'ally', 'entity_ref': f'avatar:{avatar_id}', 'level': level,
        'eidolon_level': 0, 'position': position, 'build_mode': 'assembled_character_build',
        'character_build': {
            'build_id': f'{name}:build', 'character_card_id': card, 'level': level,
            'promotion': 6 if level >= 80 else 0, 'eidolon_level': 0,
            'unlocked_trace_node_ids': [], 'equipment_build': equipment,
        },
        'initial_condition': {'hp_mode': 'full', 'initial_energy': energy, 'initial_resource_values': []},
    }


def _session(*units, world_level=None):
    scenario = {
        'scenario_id': 'r07:route', 'version': 'v0_200', 'units': list(units), 'stage_ref': '307214',
        'wave_index': 0, 'route': [], 'battle_setup': {
            **({'world_level': world_level} if world_level is not None else {}),
            'timeline': {'mode': 'runtime_initialize'},
            'metadata': {'stage_scope': 'wave_only', 'scope': 'R07 derived-unit route'},
        },
    }
    return BattleSession(build_battle_rulebook(_ROOT / 'turnbasedgamedata-main', scenario), scenario)


def _drive(session, policy, steps):
    """Submit public choices; return transitions including automatic queue actions."""
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


def _pick(choices, actor, action):
    return next((item for item in choices if item.action_id == action
                 and item.command_template['actor_id'] == actor), None)


def _enemy(choices):
    return _pick(choices, 'enemy:stage:307214:wave:0:pos:0', _ENEMY_ACTION)


def _enemy_hp_loss(transitions):
    return sum(
        mutation.before - mutation.after
        for transition in transitions for mutation in transition.transaction.mutations
        if mutation.path[-1:] == ('hp',) and mutation.path[1].startswith('enemy:')
    )


def test_dan_heng_dragon_spirit_creation_shield_owner_change_and_attack():
    session = _session(_unit('dh', 1414, 0), _unit('ally', 1105, 1, level=1))
    casts = []

    def policy(choices):
        skill = _pick(choices, 'dh', 'avatar_skill:141402')
        if skill is not None:
            casts.append(1)
            return skill, ['dh' if len(casts) == 1 else 'ally']
        enemy = _enemy(choices)
        if enemy is not None:  # Keep the level-1 teammate alive as the owner-change target.
            return enemy, ['dh']
        return (_pick(choices, 'ally', 'avatar_skill:110501') or choices[0]), None

    _drive(session, policy, 6)
    events = [uid for uid in session.state.units if uid.startswith('battle_event:11414')]
    # One dragon spirit: the second cast changes its owner instead of creating another.
    assert len(events) == 1
    dragon = session.state.units[events[0]]
    assert dragon.flags['owner_id'] == 'ally' and dragon.lifecycle_status == 'active'
    names = lambda unit: {item.get('modifier_name') for item in session.state.units[unit].flags['status_details']}
    assert 'MAvatar_DanHengPT_00_LongLing' in names('ally')
    assert 'MAvatar_DanHengPT_00_LongLing' not in names('dh')
    # E0 does not satisfy the eidolon predicates of the sub-modifiers.
    assert not any('Rank0' in str(name) for name in names('ally'))
    assert all(session.state.units[unit].shield_instances for unit in ('dh', 'ally'))


def test_jing_yuan_lightning_lord_acts_and_retires_with_its_owner():
    session = _session(_unit('jy', 1204, 0, energy='130'))
    used = []

    def policy(choices):
        window = next((item for item in choices if item.choice_kind == 'ultimate_window'), None)
        if window is not None:
            return window, None
        ultimate = _pick(choices, 'jy', 'avatar_skill:120403')
        if ultimate is not None and not used:
            used.append(1)
            return ultimate, None
        return (_pick(choices, 'jy', 'avatar_skill:120402') or _pick(choices, 'jy', 'avatar_skill:120401')
                or _enemy(choices) or choices[0]), None

    transitions = _drive(session, policy, 12)
    # A Lightning Lord turn acts automatically: toughness falls without a submission.
    assert any(
        mutation.path[-1:] == ('toughness',) and mutation.after < mutation.before
        for transition in transitions if transition.outcome.successor_eligible
        for mutation in transition.transaction.mutations
    )
    assert _enemy_hp_loss(transitions) > 0
    if session.outcome == 'defeat':
        event = next(unit for uid, unit in session.state.units.items() if uid.startswith('battle_event:11203'))
        assert event.lifecycle_status == 'removed'


def test_topaz_numby_skill_and_ultimate_consumption():
    session = _session(_unit('tz', 1112, 0, energy='130'))
    used = []

    def policy(choices):
        window = next((item for item in choices if item.choice_kind == 'ultimate_window'), None)
        if window is not None:
            return window, None
        ultimate = _pick(choices, 'tz', 'avatar_skill:111203')
        if ultimate is not None and not used:
            used.append(1)
            return ultimate, None
        return (_pick(choices, 'tz', 'avatar_skill:111202') or _enemy(choices) or choices[0]), None

    transitions = _drive(session, policy, 5)
    assert used and session.state.units['tz'].energy < 130
    assert _enemy_hp_loss(transitions) > 0


def test_lingsha_fuyuan_damages_heals_and_ultimate_acts():
    session = _session(_unit('ls', 1222, 0, energy='110'))
    used = []

    def policy(choices):
        window = next((item for item in choices if item.choice_kind == 'ultimate_window'), None)
        if window is not None:
            return window, None
        skill = _pick(choices, 'ls', 'avatar_skill:122202')
        if skill is not None and session.state.skill_points > 0:
            return skill, None
        ultimate = _pick(choices, 'ls', 'avatar_skill:122203')
        if ultimate is not None and not used:
            used.append(1)
            return ultimate, None
        return (_pick(choices, 'ls', 'avatar_skill:122201') or _enemy(choices) or choices[0]), None

    transitions = _drive(session, policy, 8)
    assert any(uid.startswith('battle_event:11222') for uid in session.state.units)
    assert _enemy_hp_loss(transitions) > 0
    assert any(
        mutation.path == ('units', 'ls', 'hp') and mutation.after > mutation.before
        for transition in transitions for mutation in transition.transaction.mutations
    )


def _summons(session):
    return [uid for uid in session.state.units if uid.startswith('summon:servant:')]


def test_trailblazer_memosprite_ultimate_attack_and_owner_death_retirement():
    session = _session(_unit('tb', 8007, 0, energy='160'))
    enemy_id = 'enemy:stage:307214:wave:0:pos:0'
    seen = set()

    def policy(choices):
        window = next((item for item in choices if item.choice_kind == 'ultimate_window'), None)
        if window is not None:
            seen.add(window.action_id)
            return window, None
        ultimate = _pick(choices, 'tb', 'avatar_skill:800703')
        if ultimate is not None and 'avatar_skill:800703' not in seen:
            return ultimate, None
        for servant in _summons(session):
            attack = _pick(choices, servant, 'servant_skill:1800701')
            if attack is not None:
                seen.add(attack.action_id)
                return attack, None
        basic = _pick(choices, 'tb', 'avatar_skill:800701')
        if basic is not None:
            return basic, None
        return _enemy(choices), ['tb']

    hp_before = session.state.units[enemy_id].hp
    _drive(session, policy, 3)
    # The ultimate creates the memosprite first, then deals damage as the memosprite.
    assert 'avatar_skill:800703' in seen
    assert _summons(session)
    assert session.state.units[enemy_id].hp < hp_before
    transitions = _drive(session, policy, 12)
    assert 'servant_skill:1800701' in seen
    assert _enemy_hp_loss(transitions) > 0
    # Owner defeat retires the memosprite; its departure cannot fault the action.
    assert session.outcome
    assert session.state.units['tb'].lifecycle_status == 'defeated'
    assert all(session.state.units[uid].lifecycle_status != 'active' for uid in _summons(session))


def test_evernight_memosprite_deals_ultimate_damage_from_its_own_max_hp():
    session = _session(_unit('en', 1413, 0, energy='240'))
    enemy_id = 'enemy:stage:307214:wave:0:pos:0'
    hp_before = session.state.units[enemy_id].hp

    def policy(choices):
        window = next((item for item in choices if item.choice_kind == 'ultimate_window'), None)
        if window is not None:
            return window, None
        return _pick(choices, 'en', 'avatar_skill:141303') or choices[0], None

    transitions = _drive(session, policy, 2)
    assert _summons(session)
    servant = session.state.units[_summons(session)[0]]
    assert servant.max_hp < session.state.units['en'].max_hp
    loss = hp_before - session.state.units[enemy_id].hp
    assert loss > 0
    # 文本倍率基于忆灵生命上限，不能按主人更高的生命结算。
    assert loss < session.state.units['en'].max_hp
    assert transitions


def test_opening_speed_tie_starts_the_wave_before_the_tie_choice():
    # Fu Xuan and this enemy share one speed, so the opening needs a tie choice.
    session = _session(_unit('fx', 1208, 0))
    enemy_id = 'enemy:stage:307214:wave:0:pos:0'
    decision = session.advance()
    tie = next(item for item in decision.availability.choices if item.choice_kind == 'timeline_actor')
    assert session.submit(command_from_json({**tie.command_template, 'target_ids': []})).transition.outcome.successor_eligible
    decision = session.advance()
    basic = _pick(list(decision.availability.choices), 'fx', 'avatar_skill:120801')
    before = session.state.units[enemy_id].hp
    result = session.submit(command_from_json({**basic.command_template, 'target_ids': [enemy_id]}))
    assert result.transition.outcome.successor_eligible
    # The command is the action itself, never swallowed by a late wave start.
    assert session.state.units[enemy_id].hp < before


def test_aglaea_joint_attack_countdown_exit_and_resummon():
    session = _session(_unit('ag', 1402, 0, energy='350'))
    spawned = set()

    def policy(choices):
        window = next((item for item in choices if item.choice_kind == 'ultimate_window'), None)
        if window is not None:
            return window, None
        for uid in _summons(session):
            spawned.add(uid)
        for name in ('avatar_skill:140203', 'avatar_skill:140208'):
            choice = _pick(choices, 'ag', name)
            if choice is not None and (name != 'avatar_skill:140203' or not spawned):
                return choice, None
        for uid in _summons(session):
            attack = _pick(choices, uid, 'servant_skill:1140201')
            if attack is not None:
                return attack, None
        skill = _pick(choices, 'ag', 'avatar_skill:140202')
        if skill is not None and not [u for u in _summons(session)
                                      if session.state.units[u].lifecycle_status == 'active']:
            return skill, None
        return (_pick(choices, 'ag', 'avatar_skill:140201') or _enemy(choices)
                or next(item for item in choices)), None

    transitions = _drive(session, policy, 10)
    for uid in _summons(session):
        spawned.add(uid)
    assert _enemy_hp_loss(transitions) > 0
    # The first memosprite leaves with the countdown; the skill summons a new one.
    assert len(spawned) >= 2
    assert any(session.state.units[uid].lifecycle_status != 'active' for uid in spawned)


def test_hyacine_ultimate_creates_memosprite_and_skill_heals_both():
    session = _session(_unit('hy', 1409, 0, energy='140'))

    def policy(choices):
        window = next((item for item in choices if item.choice_kind == 'ultimate_window'), None)
        if window is not None:
            return window, None
        ultimate = _pick(choices, 'hy', 'avatar_skill:140903')
        if ultimate is not None and not _summons(session):
            return ultimate, None
        skill = _pick(choices, 'hy', 'avatar_skill:140902')
        if skill is not None and session.state.skill_points > 0:
            return skill, None
        return (_pick(choices, 'hy', 'avatar_skill:140901') or _enemy(choices)), None

    transitions = _drive(session, policy, 6)
    servants = _summons(session)
    assert servants
    healed = {
        mutation.path[1] for transition in transitions for mutation in transition.transaction.mutations
        if mutation.path[-1:] == ('hp',) and mutation.after > mutation.before
    }
    assert {'hy', servants[0]} <= healed
