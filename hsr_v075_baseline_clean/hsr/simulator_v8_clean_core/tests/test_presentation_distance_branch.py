"""Distance-only presentation choices must not invent combat facts."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering, _process_only_ability_task_source_blocked_reason,
    _status_callback_presentation_only, _mark_client_only_trigger_ability_tasks,
    _presentation_delay_template_only,
)

ROOT = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
SOURCE = 'Config/ConfigAbility/Monster/Monster_W1_Soldier01_00_Ability.json'


def test_reviewed_display_delay_template_keeps_gameplay_outside_exclusion():
    raw = json.loads((ROOT / 'Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json').read_text())
    template = next(row for row in raw['TaskListTemplate'] if row['Name'] == 'PursuedDamage_PerformanceDelay')
    assert _presentation_delay_template_only(template['Name'], template['TaskList'])
    changed = deepcopy(template['TaskList'])
    changed[1]['TaskList'].append({'$type': 'RPG.GameCore.DamageByAttackProperty'})
    assert not _presentation_delay_template_only(template['Name'], changed)


def test_break_element_visual_switch_does_not_hide_gameplay():
    raw = json.loads((ROOT / 'Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json').read_text())
    tasks = raw['ModifierMap']['StanceBreakState_Effect']['_CallbackList'][0]['CallbackConfig']
    assert _status_callback_presentation_only(tasks)
    changed = deepcopy(tasks)
    cases = changed[0]['SuccessTaskList'][0]['CaseTaskList']
    cases[0]['TaskList'].append({'$type': 'RPG.GameCore.AddModifier'})
    assert not _status_callback_presentation_only(changed)


def _branches():
    raw = json.loads((ROOT / SOURCE).read_text())
    return [(index, ability['Name'], task_index, task)
            for index, ability in enumerate(raw['AbilityList'])
            for task_index, task in enumerate(ability.get('OnStart', []))
            if task.get('$type') == 'RPG.GameCore.PredicateTaskList'
            and task.get('Predicate', {}).get('$type') == 'RPG.GameCore.ByDistance']


def _lower(row, *, lower_children=True, source=SOURCE):
    index, name, task_index, task = row
    return TBGDLowering(ROOT)._lower_ability_task_tree(
        task, definition=SimpleNamespace(action_id='test:distance', level=1),
        phase_id='test:phase', ability_name=name, ability_path=source, ability_index=index,
        callback_kind='OnStart', task_index=task_index, task_path=f'OnStart[{task_index}]',
        branch='root', parent_task_id='', lower_children=lower_children,
    )


def test_actual_presentation_branches_preserve_source_without_distance_condition():
    rows = _branches()
    assert len(rows) >= 2
    for row in rows:
        raw = row[-1]
        assert not _process_only_ability_task_source_blocked_reason(raw, 'PredicateTaskList')
        result = _lower(row)
        assert not result.conditions and len(result.ability_tasks) == 1
        task = result.ability_tasks[0]
        assert task.execution_mode == 'process_only' and task.coverage_status == 'audit_only'
        assert task.source.source_path == SOURCE and task.source.evidence['source_opcode'] == 'PredicateTaskList'
        effect = next(e for e in result.effects if e.effect_id == task.effect_id)
        for key in ('Predicate', 'SuccessTaskList', 'FailedTaskList'):
            assert effect.payload[key] == raw[key]
        # Formal lowering keeps topology separately and needs no visual condition.
        formal = _lower(row, lower_children=False)
        assert not formal.conditions and formal.ability_tasks[0].coverage_status == 'audit_only'


def test_one_sided_visual_predicate_needs_no_turn_fact():
    source = 'Config/ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json'
    ability = json.loads((ROOT / source).read_text())['AbilityList'][3]
    raw = ability['OnStart'][9]
    assert raw['Predicate']['$type'] == 'RPG.GameCore.ByIsTurnActionEntity'
    assert 'SuccessTaskList' not in raw
    for lower_children in (True, False):
        result = _lower((3, ability['Name'], 9, raw), source=source, lower_children=lower_children)
        assert not result.conditions and len(result.ability_tasks) == 1
        task = result.ability_tasks[0]
        assert task.execution_mode == 'process_only' and task.coverage_status == 'audit_only'
        assert result.effects[0].payload['FailedTaskList'] == raw['FailedTaskList']
    for opcode in ('AddModifier', 'UnknownTask'):
        changed = deepcopy(raw)
        changed['FailedTaskList'].append({'$type': f'RPG.GameCore.{opcode}'})
        assert not _status_callback_presentation_only([changed])
        result = _lower((3, ability['Name'], 9, changed), source=source, lower_children=False)
        assert result.ability_tasks[0].execution_mode == 'runtime_effect'
        assert result.conditions and result.ability_tasks[0].condition_id


def test_referenced_visual_abilities_retire_the_whole_real_skill_branch():
    source = 'Config/ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json'
    camera_source = 'Config/ConfigAbility/Avatar/Camera/Avatar_Mar_7th_00_Camera.json'
    document = json.loads((ROOT / source).read_text())
    camera_document = json.loads((ROOT / camera_source).read_text())
    records = {row['Name']: row for row in camera_document['AbilityList']}
    lowering = TBGDLowering(ROOT)
    # Keep this check to the two real files, without building every avatar's catalog.
    lowering._character_ability_definition_record = lambda item: (records[item.ability_name], camera_document)
    definitions = [SimpleNamespace(definition_kind='presentation', definition_id=name, ability_name=name)
                   for name in records]
    candidates = {item.ability_name: [item] for item in definitions}
    names = frozenset(item.ability_name for item in definitions
                      if lowering._character_presentation_ability_only(item, candidates))
    ability = document['AbilityList'][2]
    branch = ability['OnStart'][2]
    called_names = {branch[key][0]['AbilityName']['Value'] for key in ('SuccessTaskList', 'FailedTaskList')}
    assert called_names <= names
    result = lowering._lower_ability_phase_tasks(
        definition=SimpleNamespace(action_id='check:visual-call', level=1), phase_id='check:phase',
        ability_name=ability['Name'], ability=ability, ability_path=source, ability_index=2,
    )
    _mark_client_only_trigger_ability_tasks(
        result, client_only_ability_names=names, client_only_ability_path=camera_source,
        formal_source_context=SimpleNamespace(documents={source: document}),
    )
    branch_task = next(task for task in result.ability_tasks if task.task_path == 'OnStart[2]')
    assert branch_task.execution_mode == 'process_only' and not branch_task.condition_id
    assert branch_task.coverage_status == 'audit_only' and not branch_task.blocked_reason
    effect = next(effect for effect in result.effects if effect.effect_id == branch_task.effect_id)
    assert effect.source == branch_task.source and effect.payload['process_only_contract']['source_shape_status'] == 'admitted'
    counter_ability = document['AbilityList'][8]
    counter_call = counter_ability['OnStart'][3]
    assert counter_call['AbilityInherentTargetType']['Alias'] == 'AbilityTargetEntity'
    counter_result = lowering._lower_ability_phase_tasks(
        definition=SimpleNamespace(action_id='check:visual-counter', level=1), phase_id='check:counter',
        ability_name=counter_ability['Name'], ability=counter_ability, ability_path=source, ability_index=8,
    )
    _mark_client_only_trigger_ability_tasks(
        counter_result, client_only_ability_names=names, client_only_ability_path=camera_source,
        formal_source_context=SimpleNamespace(documents={source: document}),
    )
    counter_task = next(task for task in counter_result.ability_tasks if task.task_path == 'OnStart[3]')
    assert counter_task.execution_mode == 'process_only' and counter_task.coverage_status == 'audit_only'
    assert not counter_task.blocked_reason
    unsafe_call = deepcopy(counter_call)
    unsafe_call['AbilityInherentTargetType']['TaskList'] = [{'$type': 'RPG.GameCore.AddModifier'}]
    assert not _status_callback_presentation_only([unsafe_call], presentation_ability_names=names)
    # A combat or unknown descendant in the referenced definition cannot be retired.
    selected = next(item for item in definitions if item.ability_name in called_names)
    for opcode in ('AddModifier', 'UnknownTask'):
        records[selected.ability_name]['OnStart'].append({'$type': f'RPG.GameCore.{opcode}'})
        assert not lowering._character_presentation_ability_only(selected, candidates)
        records[selected.ability_name]['OnStart'].pop()
    changed = deepcopy(branch)
    changed['FailedTaskList'].append({'$type': 'RPG.GameCore.AddModifier'})
    assert not _status_callback_presentation_only([changed], presentation_ability_names=names)


@pytest.mark.parametrize('invalid', ['gameplay', 'unknown_child', 'unknown_root', 'unknown_predicate',
                                  'dynamic_distance', 'unknown_target', 'different_barrier', 'invalid_children'])
def test_distance_branches_fail_closed_on_gameplay_or_unknown_source(invalid):
    row = list(next(row for row in _branches()
                    if any(c['$type'] == 'RPG.GameCore.SkillExecutionStart' for c in row[-1]['SuccessTaskList'])))
    task = deepcopy(row[-1])
    row[-1] = task
    if invalid == 'gameplay':
        task['SuccessTaskList'].append({'$type': 'RPG.GameCore.HealHP'})
    elif invalid == 'unknown_child':
        task['FailedTaskList'][0]['OnFinish'] = []
    elif invalid == 'unknown_root':
        task['OnFinish'] = []
    elif invalid == 'unknown_predicate':
        task['Predicate']['OnEvaluate'] = []
    elif invalid == 'dynamic_distance':
        task['Predicate']['CompareValue']['IsDynamic'] = True
    elif invalid == 'unknown_target':
        task['Predicate']['From']['TaskList'] = []
    elif invalid == 'different_barrier':
        task['FailedTaskList'].pop()
    else:
        task['FailedTaskList'] = {}
    assert _process_only_ability_task_source_blocked_reason(task, 'PredicateTaskList')
    result = _lower(row)
    assert result.ability_tasks[0].coverage_status == 'blocked'
