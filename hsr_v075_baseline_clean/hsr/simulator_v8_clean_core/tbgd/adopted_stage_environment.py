"""Selected V1 environment parameters; no native presentation graph execution.

Fixed TBGD 14c1d18f: BattleEventAbility_Challenge_Month_46 reads the six
BattleEventConfig parameters in order. Its true damage uses target BaseHP,
with rank 1/2, rank 3 and other boss ranks selecting the last three parameters.
MCommon_ChallengeTurnLimit supplies the initial half-gauge delay; the selected
ChallengeMazeConfig supplies the shared two-half cycle budget.
"""
import json
import math
from pathlib import Path


def compile_stage_environment(root: Path, stage_id: str, event_id: str) -> dict:
    if event_id != '30146':
        raise ValueError('stage_battle_event_not_in_v1:' + event_id)
    events = json.loads((root / 'ExcelOutput/BattleEventConfig.json').read_text())
    rows = [r for r in events if str(r.get('BattleEventID')) == event_id]
    if len(rows) != 1 or rows[0].get('AbilityList') != ['BattleEventAbility_Challenge_Month_46']:
        raise ValueError('stage_battle_event_definition_changed')
    row = rows[0]
    params = [p.get('Value') for p in row.get('ParamList', ())]
    if (len(params) != 6 or any(type(p) not in (float, int) or not math.isfinite(p) or p < 0 for p in params)
            or any(params[i] <= 0 or int(params[i]) != params[i] for i in (1, 2))):
        raise ValueError('stage_battle_event_parameters_invalid')
    maze = json.loads((root / 'ExcelOutput/ChallengeMazeConfig.json').read_text())
    limits = {r['ChallengeCountDown'] for r in maze if int(stage_id) in
              (*r.get('EventIDList1', ()), *r.get('EventIDList2', ()))}
    if len(limits) != 1 or any(type(v) is not int or v <= 0 for v in limits):
        raise ValueError('stage_cycle_limit_missing_or_ambiguous')
    modifiers = json.loads((root / 'Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json').read_text())
    callbacks = modifiers['ModifierMap']['MCommon_ChallengeTurnLimit']['_CallbackList']
    initial = [t['AddNormalizedValue']['FixedValue']['Value'] for c in callbacks if c['Event'] == 'OnEnterBattle'
               for t in c['CallbackConfig'] if t.get('$type') == 'RPG.GameCore.ModifyActionDelay']
    speed = row.get('Speed', {}).get('Value')
    hp = [v['Value']['Value'] for v in row.get('OverrideProperty', ()) if v['PropertyType'] == 'BaseHP']
    if (len(initial) != 1 or type(initial[0]) not in (int, float) or not math.isfinite(initial[0])
            or initial[0] < 0 or type(speed) not in (int, float) or not math.isfinite(speed) or speed <= 0
            or len(hp) != 1 or type(hp[0]) not in (int, float) or not math.isfinite(hp[0]) or hp[0] <= 0):
        raise ValueError('stage_cycle_clock_parameters_invalid')
    return {'event_id': event_id, 'damage_bonus': params[0], 'hits_per_action': int(params[1]),
            'max_hits': int(params[2]), 'hp_ratios': {'Minion': params[3], 'MinionLv2': params[3],
                'Elite': params[4], 'LittleBoss': params[5], 'BigBoss': params[5]},
            'speed': speed, 'base_hp': hp[0], 'initial_delay_ratio': initial[0], 'cycle_limit': next(iter(limits))}
