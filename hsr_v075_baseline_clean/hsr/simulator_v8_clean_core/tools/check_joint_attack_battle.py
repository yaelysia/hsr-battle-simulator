"""Check summon, ultimate and joint damage through public battle commands.

Usage: python tools/check_joint_attack_battle.py OUTPUT_PREFIX
Initial energy is a scenario input; rules and runtime state are never injected.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from simulator_v8_ui.live import LiveBattle
from simulator_v8_clean_core.systems.unit_stats import effective_unit_stat


def main() -> None:
    output = Path(sys.argv[1])
    core = Path(__file__).resolve().parents[1]
    root = Path(__file__).resolve().parents[4]
    scenario = json.loads((core / 'examples/cli/aglaea_servant_vs_antimatter.json').read_text())
    scenario['scenario_id'] = 'mvp:aglaea-e0-lv1-joint-vs-antimatter'
    scenario['units'][0]['initial_condition']['initial_energy'] = '350'
    battle = LiveBattle(root / 'turnbasedgamedata-main')
    view = battle.start({'scenario': scenario})
    commands = []

    def choices():
        assert view['decision']['ready'], view['decision']
        return view['decision']['availability']['choices']

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

    initial = choices()
    assert not any(row['action_id'] == 'avatar_skill:140208' for row in initial)
    submit(next(row for row in initial if row['action_id'] == 'avatar_skill:140202'))
    submit(next(row for row in choices() if row['action_id'] == 'timeline:select_tied_actor'
                and row['actor_id'] == 'aglaea'))
    submit(next(row for row in choices() if row['choice_kind'] == 'manual_ultimate_request'))
    submit(next(row for row in choices() if row['choice_kind'] == 'ultimate_window'))
    countdown = [unit for unit in battle.session.state.units.values()
                 if unit.flags.get('entity_type') == 'battle_event']
    assert len(countdown) == 1
    assert effective_unit_stat(countdown[0], 'speed').value == countdown[0].action_value == 100
    availability = view['decision']['availability']
    assert {row['action_id'] for row in availability['choices']} == {'avatar_skill:140208'}
    blocked = {row.get('action_id'): row['reason'] for row in availability['blocked']}
    assert blocked['avatar_skill:140201'] == 'action_replaced_by_control_skill_mapping'
    assert blocked['avatar_skill:140209'].startswith('status_control_gate:skill_type:Skill:')
    before = battle.session.state
    servant = next(unit for unit in before.units.values() if unit.flags.get('summon_kind') == 'servant')
    speeds_before = {actor: effective_unit_stat(before.units[actor], 'speed').value
                     for actor in ('aglaea', servant.unit_id)}
    submit(next(row for row in choices() if row['action_id'] == 'avatar_skill:140208'))
    records = battle.results[-1][1].transition.to_json(detach=False)['settlement']['records']
    hits = [row['payload'] for row in records if row['record_type'] == 'damage'
            and row['payload']['source_frame']['source_kind'] == 'primary_action_damage']
    actors = Counter(hit['source_frame']['owner_id'] for hit in hits)
    assert actors == {'aglaea': 8, servant.unit_id: 2}, actors
    assert all(hit['final_damage'] > 0 for hit in hits)
    child_windows = [event for event in battle.results[-1][1].transition.transaction.events
                     if event.event_type == 'action.window.after_attack' and event.source_id == servant.unit_id]
    assert len(child_windows) == 1, len(child_windows)
    after = battle.session.state
    speeds_after = {actor: effective_unit_stat(after.units[actor], 'speed').value for actor in speeds_before}
    Path(f'{output}.joint_callbacks.json').write_text(json.dumps({
        'unit_statuses': {actor: [{key: detail.get(key) for key in (
            'modifier_name', 'stacks', 'modifiers',
        )} | {'dynamic_values': {key: value for key, value in detail.get('dynamic_values', {}).items()
                                if not key.startswith('__')}}
            for detail in after.units[actor].flags.get('status_details', ())] for actor in after.units},
        'callbacks': [{
            'status': row['payload'].get('status'), 'reason': row['payload'].get('reason'),
            'unit_id': row['payload'].get('metadata', {}).get('unit_id'),
            'alias': row['payload'].get('event_alias'),
            'event_type': row['payload'].get('event', {}).get('event_type'),
        } for row in records if row['record_type'] == 'listener_match'],
    }, ensure_ascii=False, indent=2) + '\n')
    assert all(speeds_after[actor] > speeds_before[actor] for actor in speeds_before), (speeds_before, speeds_after)
    summary = {'damage_hit_counts': dict(actors), 'joint_damage': sum(hit['final_damage'] for hit in hits),
               'additional_damage_count': sum(row['record_type'] == 'additional_damage' for row in records),
               'speeds_before': speeds_before, 'speeds_after': speeds_after,
               'countdown_id': countdown[0].unit_id, 'countdown_speed': 100,
               'child_after_attack_count': len(child_windows)}
    print('joint_attack_passed', json.dumps(summary, ensure_ascii=False), flush=True)
    for _ in range(20):
        if battle.session.outcome:
            break
        available = [row for row in choices() if row['choice_kind'] != 'manual_ultimate_request']
        assert available, view['decision']
        submit(available[0])
    assert battle.session.outcome == 'victory', battle.session.outcome
    summary.update(outcome=battle.session.outcome, command_count=len(commands),
                   scope='E0/Lv1, empty equipment, initial energy 350; no countdown expiry check')
    for suffix, value in [('scenario', scenario), ('commands', {'commands': commands}), ('result', summary)]:
        Path(f'{output}.{suffix}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
