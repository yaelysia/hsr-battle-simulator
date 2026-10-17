"""Run summon, heal and servant attacks through public battle commands.

Usage: python tools/check_servant_battle.py OUTPUT_PREFIX
Uses the existing scoped IR cache; does not inject rules or battle state.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from simulator_v8_ui.live import LiveBattle


def main() -> None:
    output = Path(sys.argv[1])
    root = Path(__file__).resolve().parents[4]
    core = Path(__file__).resolve().parents[1]
    battle = LiveBattle(root / 'turnbasedgamedata-main')
    scenario = json.loads((core / 'examples/cli/arlan_natasha_vs_antimatter.json').read_text())
    scenario['units'] = scenario['units'][:1]
    scenario['units'][0]['unit_id'] = 'aglaea'
    scenario = battle.configure_character({
        'scenario': scenario, 'unit_id': 'aglaea', 'entity_ref': 'avatar:1402',
    })['scenario']
    scenario['scenario_id'] = 'mvp:aglaea-e0-lv1-servant-vs-antimatter'
    view = battle.start({'scenario': scenario})
    assert view['decision']['ready'], view['decision']
    commands = []

    def submit(choice):
        nonlocal view
        command = {**choice['command_template'], 'metadata': {}}
        query = choice.get('target_query') or {}
        if query.get('selection_mode') == 'explicit':
            command['target_ids'] = query['candidate_ids'][:1]
        view = battle.submit({'session_id': view['session_id'], 'revision': view['revision'],
            'decision_id': view['decision']['token']['decision_id'], 'command': command})
        outcome = view['steps'][-1]['transition_outcome']
        assert outcome['successor_eligible'], outcome['reason_codes']
        commands.append(command)
        print('command', len(commands), command['action_id'], 'passed', flush=True)

    submit(next(choice for choice in view['decision']['availability']['choices']
                if choice['action_id'] == 'avatar_skill:140202'))
    state = battle.session.state
    servants = [unit for unit in state.units.values() if unit.flags.get('summon_kind') == 'servant']
    assert len(servants) == 1, [unit.unit_id for unit in servants]
    servant = servants[0]
    owner = state.units['aglaea']
    assert servant.template_id == 'servant:11402' and servant.flags['owner_id'] == owner.unit_id
    assert servant.hp == servant.max_hp > 0 and servant.attack > 0 and servant.speed > 0
    # AvatarServantConfig HPSkill/HPBase/HPInherit resolve through the owner's
    # selected level: Lv1 talent ParamList[5]=180 and ParamList[4]=0.44.
    assert math.isclose(servant.max_hp, owner.max_hp * 0.44 + 180), (servant.max_hp, owner.max_hp)
    modifiers = {detail['modifier_name'] for detail in servant.flags['status_details']}
    assert {'Servant_Common_PassiveModifier', 'MServant_AglaeaServant_Passive',
            'MServant_AglaeaServant_00_BattleCry', 'MServant_AglaeaServant_00_DeathRattle'} <= modifiers
    bars = owner.flags['mechanism_bars']
    assert any(bar.get('current_count') == 0 and bar.get('max_count') == 6 for bar in bars.values()), bars
    assert owner.action_value == servant.action_value == 0, (owner.action_value, servant.action_value)
    assert owner.flags['control_skill_mappings']['skill'] == 'Skill21'
    print('birth_and_initialization_passed', flush=True)

    submit(next(choice for choice in view['decision']['availability']['choices']
                if choice['action_id'] == 'timeline:select_tied_actor' and choice['actor_id'] == owner.unit_id))
    availability = view['decision']['availability']
    old_skill = next(item for item in availability['blocked'] if item.get('action_id') == 'avatar_skill:140202')
    assert 'action_replaced_by_control_skill_mapping' in old_skill['reason'], old_skill
    before = battle.session.state
    rejected = battle.submit({'session_id': view['session_id'], 'revision': view['revision'],
        'decision_id': view['decision']['token']['decision_id'], 'command': commands[0]})
    assert not rejected['steps'][-1]['transition_outcome']['successor_eligible']
    assert battle.session.state == before
    view = rejected
    submit(next(choice for choice in view['decision']['availability']['choices']
                if choice['action_id'] == 'avatar_skill:140209'))
    healed = battle.session.state
    assert healed.skill_points == before.skill_points - 1
    assert healed.units[owner.unit_id].energy > before.units[owner.unit_id].energy
    records = battle.results[-1][1].transition.to_json(detach=False)['settlement']['records']
    heals = [record['payload'] for record in records
             if record['record_type'] == 'heal' and record['payload'].get('target_id') == servant.unit_id]
    assert len(heals) == 1 and math.isclose(heals[0]['amount'], servant.max_hp * 0.25), heals
    print('servant_heal_passed', flush=True)
    submit(next(choice for choice in view['decision']['availability']['choices']
                if choice['actor_id'] == servant.unit_id and choice['action_id'] == 'servant_skill:1140201'))
    first_attack = [record for record in view['steps'][-1]['damage_records'] if record['record_type'] == 'damage']
    assert len(first_attack) == 8 and all(record['final_damage'] > 0 for record in first_attack), first_attack
    print('servant_first_attack_passed', flush=True)
    # A deterministic external route, including explicit enemy choices; no AI in the core.
    for _ in range(20):
        if battle.session.outcome:
            break
        choices = [choice for choice in view['decision']['availability']['choices']
                   if choice['choice_kind'] != 'manual_ultimate_request']
        assert choices, view['decision']
        submit(choices[0])
    assert battle.session.outcome == 'victory', battle.session.outcome

    additional = [record for step in view['steps'] for record in step['damage_records']
                  if record['record_type'] == 'additional_damage']
    assert additional and all(record['final_damage'] > 0 for record in additional), additional

    summary = {'servant_id': servant.unit_id, 'hp': servant.hp, 'attack': servant.attack,
               'speed': servant.speed, 'owner_action_value': owner.action_value,
               'servant_action_value': servant.action_value, 'mechanism_bars': bars,
               'control_skill_mappings': owner.flags['control_skill_mappings'],
               'heal_amount': heals[0]['amount'],
               'first_servant_hit_count': len(first_attack),
               'first_servant_damage': sum(record['final_damage'] for record in first_attack),
               'additional_damage_count': len(additional),
               'outcome': battle.session.outcome, 'command_count': len(commands),
               'remaining_blocked_actions': availability['blocked'],
               'scope': 'E0/Lv1 no equipment; summon, heal, servant attacks and victory in one source wave; no ultimate or joint attack'}
    for suffix, value in (('scenario', scenario), ('commands', {'commands': commands}), ('result', summary)):
        Path(f'{output}.{suffix}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: value for key, value in summary.items() if key != 'remaining_blocked_actions'},
                     ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
