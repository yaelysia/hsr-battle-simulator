"""Pinned source fragments with explicit boundary states, not full kit acceptance."""
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, EffectIR, IRSource, StatusCallbackIR, StatusCallbackTaskIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry
from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering, _effect_payload, _effect_coverage_status, _status_callback_task_admission


SOURCE = 'Config/ConfigAbility/Avatar/Avatar_DanHeng_00_Ability.json'


def _tasks():
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'

    def walk(value, path='$', event=''):
        if isinstance(value, dict):
            event = value.get('Event', event)
            if '$type' in value:
                yield event, path, value
            for key, child in value.items():
                yield from walk(child, f'{path}.{key}', event)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from walk(child, f'{path}[{index}]', event)

    return tuple(walk(json.loads((root / SOURCE).read_text())))


def _effect(raw, path):
    opcode = raw['$type'].rsplit('.', 1)[-1]
    payload = _effect_payload(raw, opcode, '')
    return EffectIR(path, opcode, payload, IRSource(SOURCE, opcode, path, {'json_path': path}),
                    _effect_coverage_status(opcode, payload))


def _cooldown():
    return next((path, raw) for event, path, raw in _tasks()
                if event == 'OnListenTurnEnd' and raw['$type'] == 'RPG.GameCore.SetEnergyBarState')


def _context(**fields):
    state = BattleState(units={key: UnitState(key, 'ally', 'boundary', hp=100, max_hp=100)
                               for key in ('caster', 'owner')})
    return EffectExecutionContext(state, 'caster', 'boundary', owner_id='owner', **fields)


def test_real_cooldown_updates_current_owner_and_replays():
    path, raw = _cooldown()
    effect = _effect(raw, path)
    context = _context(dynamic_values={'-94684849': 2.0})
    before = context.state.snapshot().to_json()
    result = EffectRegistry().execute(effect, context)
    assert not result.unsupported, result.unsupported
    assert len(result.mutations) == 1 and not result.rng_events
    reducer = MutationReducer()
    after = reducer.apply_all(context.state, result.mutations)
    assert after.units['owner'].flags['mechanism_bars']['1'] == {
        'state': 'CoolDown', 'active': 'True', 'cooldown': 2.0,
    }
    assert 'mechanism_bars' not in after.units['caster'].flags
    assert result.mutations[0].metadata['effect_source']['source_path'] == SOURCE
    assert reducer.replay_snapshot(context.state, result.mutations, after.snapshot().to_json()).ok
    assert context.state.snapshot().to_json() == before


@pytest.mark.parametrize('failure', ['missing_binding', 'invalid_count', 'unknown_field', 'unknown_target',
                                     'missing_target_context', 'missing_bar', 'empty_update'])
def test_incomplete_bar_update_never_commits_other_fields(failure):
    path, raw = _cooldown()
    raw = deepcopy(raw)
    context = _context(dynamic_values={'-94684849': 2.0})
    if failure == 'missing_binding':
        context = replace(context, dynamic_values={})
    elif failure == 'invalid_count':
        raw['CurrentCount'] = {'Unsupported': 3}
    elif failure == 'unknown_field':
        raw['FutureFlag'] = True
    elif failure in {'unknown_target', 'missing_target_context'}:
        raw['TargetType'] = {'$type': 'RPG.GameCore.TargetAlias',
                             'Alias': 'Unknown' if failure == 'unknown_target' else 'ParamEntity'}
    elif failure == 'missing_bar':
        raw.pop('BarType')
    else:
        raw = {'$type': raw['$type'], 'BarType': 1}
    effect = _effect(raw, path)
    before = context.state.snapshot().to_json()
    result = EffectRegistry().execute(effect, context)
    assert result.unsupported
    assert not result.mutations and not result.events and not result.rng_events
    assert context.state.snapshot().to_json() == before


def test_real_callbacks_use_registered_producers_and_reject_unknown_fields():
    from hsr.simulator_v8_clean_core.tbgd.lowering import (
        _process_only_ability_task_source_blocked_reason, _status_callback_presentation_only,
    )

    observed = set()
    for event, path, raw in _tasks():
        opcode = raw['$type'].rsplit('.', 1)[-1]
        if opcode in {'SetEnergyBarState', 'TriggerEnergyBarEffect', 'SetDynamicValueByModifierValue'} and event:
            status, reason = _status_callback_task_admission(event, opcode, raw)
            observed.add((event, opcode))
            if opcode == 'TriggerEnergyBarEffect':
                assert reason == 'source_proven_presentation_only'
                for extra in ({'FutureFlag': True}, {'FutureConfig': {'UnknownBehavior': True}}):
                    changed = {**raw, **extra}
                    assert _status_callback_task_admission(event, opcode, changed)[1] != reason
                    assert _process_only_ability_task_source_blocked_reason(changed, opcode)
                    assert not _status_callback_presentation_only([changed])
            else:
                assert (status, reason) == ('executable', ''), (event, path, reason)
                assert _status_callback_task_admission(event, opcode, {**raw, 'FutureFlag': True})[0] == 'blocked'
        if event == 'OnListenAfterSkillUse' and opcode in {'AddModifier', 'SetDynamicValue', 'RemoveModifier'}:
            assert _status_callback_task_admission(event, opcode, raw) == ('executable', '')
    assert ('OnListenTurnEnd', 'SetDynamicValueByModifierValue') in observed
    assert ('OnListenAfterSkillUse', 'SetEnergyBarState') in observed
    assert ('OnListenInsertAbilityAbort', 'SetEnergyBarState') in observed


def test_callback_owner_admits_the_same_existing_event_as_its_tasks():
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    lowered = TBGDLowering(root)._lower_ability_file(root / SOURCE, {}, ability_file_order=0)
    for event in ('OnListenAfterSkillUse', 'OnAfterHit'):
        callbacks = [callback for callback in lowered.status_callbacks if callback.event == event]
        assert callbacks
        assert all(callback.coverage_status == 'executable' for callback in callbacks), [
            callback.blocked_reason for callback in callbacks
        ]


def test_modifier_lifetime_reaches_bar_through_callback_dynamic_store():
    path, raw = next((path, raw) for event, path, raw in _tasks()
                     if event == 'OnListenTurnEnd' and raw['$type'] == 'RPG.GameCore.SetDynamicValueByModifierValue')
    modifier = raw['ModifierName']
    effects = tuple(replace(_effect(task, source_path), owner_modifier_name=modifier)
                    for source_path, task in ((path, raw), _cooldown()))
    tasks = tuple(StatusCallbackTaskIR(
        effect.effect_id, 'callback', modifier, 'OnListenTurnEnd', index, effect.effect_id, 'root',
        effect.opcode, effect.source, effect_id=effect.effect_id, coverage_status=effect.coverage_status,
    ) for index, effect in enumerate(effects))
    callback = StatusCallbackIR('callback', modifier, 'OnListenTurnEnd', tuple(t.task_id for t in tasks),
                                effects[0].source, (0, 0), coverage_status='executable')
    rules = RuleBook(CanonicalIR('boundary', effects=effects))
    system = StatusCallbackSystem(rules)
    detail = {'instance_id': 'cooldown', 'status_id': f'modifier:{modifier}', 'modifier_name': modifier,
              'owner_id': 'owner', 'caster_id': 'caster', 'source_id': 'boundary', 'status_category': 'buff',
              'duration': 3, 'remaining_duration': 2, 'stacks': 1, 'max_stacks': 1}
    original = _context().state
    owner = replace(original.units['owner'], statuses=(detail['status_id'],), flags={'status_details': [detail]})
    original = replace(original, units={**original.units, 'owner': owner})
    state = original
    event = GameEvent(event_id='turn:end', event_type='turn.end', source_id='owner', target_id='owner')
    mutations = []
    for task in tasks:
        result = system._execute_effect_task(state, callback, task, detail, event, None)
        assert result.ok, result.errors
        state = result.after_state
        mutations.extend(result.mutations)
    assert state.units['owner'].flags['mechanism_bars']['1']['cooldown'] == 2
    assert MutationReducer().replay_snapshot(original, mutations, state.snapshot().to_json()).ok
    assert 'mechanism_bars' not in original.units['owner'].flags
    missing = replace(original, units={**original.units, 'owner': replace(owner, flags={'status_details': []}, statuses=())})
    result = system._execute_effect_task(missing, callback, tasks[0], detail, event, None)
    assert not result.ok and not result.mutations and not result.rng_events
