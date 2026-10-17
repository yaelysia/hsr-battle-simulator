"""Public-command battle covering countdown expiry, departure and resummoning.

Usage: python tools/check_servant_retirement_battle.py OUTPUT_PREFIX
Uses a source wave and a completed build; never injects rules or runtime state.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from simulator_v8_ui.live import LiveBattle
from simulator_v8_clean_core.systems.unit_stats import effective_unit_stat


def main() -> None:
    output = Path(sys.argv[1])
    core = Path(__file__).resolve().parents[1]
    root = Path(__file__).resolve().parents[4]
    scenario = json.loads((core / 'examples/cli/aglaea_joint_vs_antimatter.json').read_text())
    scenario.update(scenario_id='mvp:aglaea-e0-lv20-countdown-and-resummon', stage_ref='400020640')
    actor = scenario['units'][0]
    actor['level'] = actor['character_build']['level'] = 20
    actor['character_build'].pop('input_fingerprint', None)
    scenario['battle_setup']['metadata']['scope'] = 'StageConfig 400020640 wave only; countdown and resummoning'
    battle = LiveBattle(root / 'turnbasedgamedata-main')
    view = battle.start({'scenario': scenario})
    commands = []
    enemy_attacks = 0

    def choices():
        assert view['decision']['ready'], view['decision']['blocked_reason']
        return view['decision']['availability']['choices']

    def submit(choice):
        nonlocal view, enemy_attacks
        command = {**choice['command_template'], 'metadata': {}}
        query = choice.get('target_query') or {}
        if query.get('selection_mode') == 'explicit':
            command['target_ids'] = query['candidate_ids'][:1]
            if command['actor_id'].startswith('enemy:'):
                servants = [uid for uid in query['candidate_ids'] if uid.startswith('summon:')]
                if servants and enemy_attacks > 0:
                    command['target_ids'] = servants[:1]
                enemy_attacks += 1
        view = battle.submit({'session_id': view['session_id'], 'revision': view['revision'],
            'decision_id': view['decision']['token']['decision_id'], 'command': command})
        outcome = view['steps'][-1]['transition_outcome']
        assert outcome['successor_eligible'], outcome['reason_codes']
        commands.append(command)
        print('command', len(commands), command['action_id'], 'passed', flush=True)

    for action in ('avatar_skill:140202', 'timeline:select_tied_actor', 'avatar_skill:140203', 'avatar_skill:140203'):
        submit(next(row for row in choices() if row['action_id'] == action and row['actor_id'] == 'aglaea'))
    original = next(u for u in battle.session.state.units.values() if u.flags.get('summon_kind') == 'servant')
    countdown = next(u for u in battle.session.state.units.values() if u.flags.get('entity_type') == 'battle_event')
    for _ in range(20):
        if battle.session.state.units[countdown.unit_id].lifecycle_status == 'removed':
            break
        assert not battle.session.outcome, battle.session.outcome
        submit(next(row for row in choices() if row['choice_kind'] != 'manual_ultimate_request'))
    state = battle.session.state
    Path(f'{output}.expiry.state.json').write_text(json.dumps(state.snapshot().to_json()) + '\n')
    assert state.units[countdown.unit_id].lifecycle_status == 'removed'
    assert state.units[original.unit_id].lifecycle_status == 'removed'
    before_expiry_energy = battle.results[-1][1].after_state.units['aglaea'].energy
    assert state.units['aglaea'].energy == before_expiry_energy + 20
    bar = state.units['aglaea'].flags['mechanism_bars']['Number']
    assert bar['active'] == 'False' and bar['current_count'] == 0
    assert effective_unit_stat(state.units['aglaea'], 'speed').value == 102
    assert not state.units[original.unit_id].statuses
    assert not any(state.queues.values())
    expiry = {'command_count': len(commands), 'energy_before': before_expiry_energy,
              'energy_after': state.units['aglaea'].energy, 'countdown_id': countdown.unit_id,
              'retired_servant_id': original.unit_id, 'mechanism_bar': dict(bar)}
    print('expiry_passed', json.dumps(expiry, ensure_ascii=False), flush=True)

    resummoned = None
    for _ in range(30):
        if battle.session.outcome:
            break
        available = [row for row in choices() if row['choice_kind'] != 'manual_ultimate_request']
        if resummoned is None and any(row['actor_id'] == 'aglaea' for row in available):
            assert not any(row['action_id'] == 'avatar_skill:140208' for row in available)
            submit(next(row for row in available if row['action_id'] == 'avatar_skill:140202'))
            resummoned = next(u for u in battle.session.state.units.values()
                             if u.flags.get('summon_kind') == 'servant' and u.lifecycle_status == 'active')
            assert resummoned.unit_id != original.unit_id
            print('resummon_passed', resummoned.unit_id, flush=True)
        else:
            submit(available[0])
    assert resummoned is not None
    assert battle.session.outcome == 'victory', battle.session.outcome
    summary = {**expiry, 'resummoned_servant_id': resummoned.unit_id,
               'command_count': len(commands), 'outcome': battle.session.outcome,
               'scope': 'E0/Lv20, empty equipment, initial energy 350; source enemy wave only'}
    for suffix, value in [('scenario', scenario), ('commands', {'commands': commands}), ('result', summary)]:
        Path(f'{output}.{suffix}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
