"""Run the first shield counter through the public session, without a whole battle.

Usage: python tools/check_queued_character_counter.py SCENARIO COMMANDS OUTPUT_PREFIX
The supplied command prefix is basic attack, shield, tied-actor choice, enemy attack.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from simulator_v8_ui.live import LiveBattle


def main() -> None:
    scenario_path, commands_path, output_prefix = map(Path, sys.argv[1:])
    root = Path(__file__).resolve().parents[4]
    scenario = json.loads(scenario_path.read_text())
    commands = json.loads(commands_path.read_text())['commands'][:4]
    assert len(commands) == 4
    commands = [{**command, 'metadata': {}} for command in commands]
    battle = LiveBattle(root / 'turnbasedgamedata-main')
    view = battle.start({'scenario': scenario})
    graph = next(graph for graph in battle.session.rules.ir.standalone_ability_graphs
                 if graph.ability_name == 'Avatar_Mar_7th_00_PassiveSkill01_InsertAbility')
    assert graph.action_id == 'avatar_skill:100104'
    print('source_binding', graph.action_id, flush=True)
    for index, command in enumerate(commands):
        if index == 3:
            counter_before = next(detail['stacks'] for unit in battle.session.state.units.values()
                for detail in unit.flags.get('status_details', ())
                if detail.get('modifier_name') == 'MAvatar_March7th_00_Passive_CanAttack')
        view = battle.submit({'session_id': view['session_id'], 'revision': view['revision'],
            'decision_id': view['decision']['token']['decision_id'], 'command': command})
        outcome = view['steps'][-1]['transition_outcome']
        assert outcome['successor_eligible'], outcome['reason_codes']
        print('command', index, command['action_id'], 'passed', flush=True)
    state = battle.session.state
    counters = [detail['stacks'] for unit in state.units.values()
                for detail in unit.flags.get('status_details', ())
                if detail.get('modifier_name') == 'MAvatar_March7th_00_Passive_CanAttack']
    assert counter_before > 0 and counters == [counter_before - 1], counters
    records = [record for operation in battle.session.operations
               for transition in operation.get('transitions', ())
               for record in transition['settlement']['records']]
    counter_damage = [record['payload']['final_damage'] for record in records
                      if record['record_type'] == 'damage' and record['payload'].get('attack_type') == 'Insert']
    assert len(counter_damage) == 1 and counter_damage[0] > 0, counter_damage
    assert not any(queue for queue in state.queues.values()), state.queues.keys()
    summary = {'counter_damage': counter_damage[0], 'counter_before': counter_before, 'counter_after': counters[0],
               'attacker_hp': state.units[commands[-1]['actor_id']].hp,
               'scope': 'four public commands; first automatic counter only'}
    Path(str(output_prefix) + '.scenario.json').write_text(json.dumps(scenario, ensure_ascii=False, indent=2) + '\n')
    Path(str(output_prefix) + '.commands.json').write_text(json.dumps({'commands': commands}, ensure_ascii=False, indent=2) + '\n')
    Path(str(output_prefix) + '.result.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
