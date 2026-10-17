"""Real callback sources; synthetic states check transport, not kit acceptance."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.dynamic_values import binding_source_from_status_detail
from hsr.simulator_v8_clean_core.systems.status import _merge_dynamic_values, _resolve_dynamic_values
from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem, _effect_context
from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering, _modifier_definition_entity, _status_callback_task_admission


def test_named_application_inputs_publish_compiled_hash_without_local_slot_declaration():
    from hsr.simulator_v8_clean_core.dynamic_key_hash import tbgd_dynamic_key_hash
    from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_dynamic_hashes
    from hsr.simulator_v8_clean_core.rules.ir import EffectIR, IRSource
    from hsr.simulator_v8_clean_core.tbgd.lowering import _effect_payload, _link_status_effect_runtime_fields

    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    path = 'Config/ConfigAbility/Avatar/Avatar_Asta_00_Ability.json'
    ability = next(row for row in json.loads((root / path).read_text())['AbilityList']
                   if row['Name'] == 'Avatar_Asta_00_PassiveSkill_1')
    raw = ability['OnStart'][0]
    name = raw['ModifierName']['Value']
    definition = _modifier_definition_entity(path, 'Modifiers', name, ability['Modifiers'][name])
    source = IRSource(path, raw['$type'], 'OnStart[0]')
    effect = EffectIR('application', 'AddModifier', _effect_payload(raw, 'AddModifier', '', source=source), source)
    linked = _link_status_effect_runtime_fields([effect], [definition], [])[0]
    standard = linked.payload['standard']
    max_name = 'MDF_MaxCount'
    max_hash = str(tbgd_dynamic_key_hash(max_name))
    assert max_hash not in definition.fields['dynamic_value_bindings']['by_hash']
    assert standard['named_dynamic_hashes'][max_name] == max_hash
    input_hashes = {name: str(numeric_dynamic_hashes(expr)[0])
                    for name, expr in standard['dynamic_values'].items()}
    values = _resolve_dynamic_values(standard, definition, None, ({
        'source_type': 'fixture_skill_parameters',
        'values': {input_hashes[max_name]: 5, input_hashes['MDF_CostLayer']: 3},
    },), {})
    assert values['__by_name'][max_name] == values['__by_hash'][max_hash] == 5

    # Explicit application inputs also work when no callback happens to read
    # the hash; unrelated runtime bindings cannot introduce a mutable slot.
    bare = replace(definition, fields={**definition.fields,
        'dynamic_value_bindings': {}, 'callback_dynamic_hashes': {}})
    values = _resolve_dynamic_values(standard, bare, {'unrelated': 99}, ({
        'source_type': 'fixture_skill_parameters',
        'values': {input_hashes[max_name]: 5, input_hashes['MDF_CostLayer']: 3},
    },), {})
    assert values['__by_hash'][max_hash] == 5
    assert 'unrelated' not in values['__by_hash']


def test_character_declared_accumulator_initializes_once_without_shadowing_values():
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    ability_path = 'Config/ConfigAbility/Avatar/Avatar_Pela_00_Ability.json'
    config_path = 'Config/ConfigCharacter/Avatar/Avatar_Pela_00_Config.json'
    abilities = json.loads((root / ability_path).read_text())['AbilityList']
    passive = next(item for item in abilities if item['Name'] == 'Avatar_Pela_00_PassiveSkill01')
    name, modifier = next(iter(passive['Modifiers'].items()))
    definition = _modifier_definition_entity(ability_path, 'Modifiers', name, modifier)
    floats = json.loads((root / config_path).read_text())['DynamicValues']['Floats']
    configured = {'by_hash': {
        key: {'hash': key, 'read_info': value['ReadInfo'], 'source_path': config_path,
              'raw_path': f'DynamicValues.Floats[{key}]'}
        for key, value in floats.items()
    }}
    resolved = _resolve_dynamic_values({}, definition, None, (), {}, character_bindings=configured)
    assert resolved['__by_hash']['2612209'] == 0
    assert '-876414897' not in resolved['__by_hash']  # Talent parameter still needs its formal reader.
    assert '-648181786' not in resolved['__by_hash']  # An unrelated character slot is not copied in.
    binding = resolved['__definition_bindings']['by_hash']['2612209']
    assert binding['source_scope'] == 'character_dynamic_values'
    assert binding['source_path'] == config_path
    explicit = _resolve_dynamic_values({}, definition, {'2612209': 7.0}, (), {}, character_bindings=configured)
    assert explicit['__by_hash']['2612209'] == explicit['2612209'] == 7
    initialized = _merge_dynamic_values(resolved, {'2612209': 3.0, '__by_hash': {'2612209': 3.0}})
    assert initialized['__by_hash']['2612209'] == initialized['2612209'] == 3


def test_named_character_slot_initial_value_and_context_caster_writes():
    from hsr.simulator_v8_clean_core.rules.evaluator import RuleEvaluator
    from hsr.simulator_v8_clean_core.rules.expression_ir import CONDITION_EXPRESSION_NODE_SCHEMA
    from hsr.simulator_v8_clean_core.rules.ir import ConditionIR, IRSource
    from hsr.simulator_v8_clean_core.systems.dynamic_values import (
        DynamicValueExecutionRequest, plan_dynamic_value_operation,
    )
    from hsr.simulator_v8_clean_core.systems.status_callbacks import _condition_context
    from hsr.simulator_v8_clean_core.tbgd.lowering import (
        _document_dynamic_key_hash_bindings, _typed_condition_payload,
        lower_character_dynamic_value_operation,
    )

    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    ability_path = 'Config/ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json'
    config_path = 'Config/ConfigCharacter/Avatar/Avatar_Mar_7th_00_Config.json'
    abilities = json.loads((root / ability_path).read_text())['AbilityList']
    passive = next(item for item in abilities if item['Name'] == 'Avatar_Mar_7th_00_PassiveSkill01')
    name = 'MAvatar_March7th_00_ListenEnergyBar'
    modifier = passive['Modifiers'][name]
    named = _document_dynamic_key_hash_bindings([('Modifiers', name, modifier, {})])
    definition = _modifier_definition_entity(ability_path, 'Modifiers', name, modifier,
                                             dynamic_key_hash_bindings=named)
    floats = json.loads((root / config_path).read_text())['DynamicValues']['Floats']
    configured = {'by_hash': {
        key: {'hash': key, 'read_info': value['ReadInfo'], 'source_path': config_path,
              'raw_path': f'DynamicValues.Floats[{key}]'}
        for key, value in floats.items()
    }}
    key, hash_key = 'Mar7th_00_Passive_CounterView', '1994008536'
    initial = _resolve_dynamic_values({}, definition, None, (), {}, character_bindings=configured)
    assert initial['__by_name'][key] == initial['__by_hash'][hash_key] == 0
    explicit = _resolve_dynamic_values({}, definition, {hash_key: 7.0}, (), {}, character_bindings=configured)
    assert explicit['__by_name'][key] == explicit['__by_hash'][hash_key] == 7
    missing = _resolve_dynamic_values({}, definition, None, (), {}, character_bindings={})
    assert key not in missing['__by_name'] and hash_key not in missing['__by_hash']

    raw_condition = modifier['_CallbackList'][0]['CallbackConfig'][0]['Predicate']
    condition_source = IRSource(ability_path, 'ByCompareDynamicValue', name, {
        'json_path': f'$.AbilityList[{abilities.index(passive)}].Modifiers.{name}._CallbackList[0].CallbackConfig[0].Predicate',
    })
    condition = ConditionIR('real:counter-predicate', 'ByCompareDynamicValue',
        _typed_condition_payload('ByCompareDynamicValue', {k: v for k, v in raw_condition.items() if k != '$type'},
                                 source=condition_source),
        condition_source, 'executable',
        expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA,
    )
    rules = RuleBook(CanonicalIR('named-character-slot', conditions=(condition,)))
    detail = {'instance_id': 'listener:1', 'status_id': f'modifier:{name}', 'modifier_name': name,
              'owner_id': 'caster', 'caster_id': 'caster', 'source_id': 'passive', 'dynamic_values': initial}
    state = BattleState(units={
        'caster': UnitState('caster', 'ally', 'fixture:caster', flags={'status_details': [detail]}),
        'other': UnitState('other', 'ally', 'fixture:other'),
    })
    writer = next(item for item in passive['OnStart'][-1]['FailedTaskList']
                  if item['$type'] == 'RPG.GameCore.SetDynamicValue')
    operation = lower_character_dynamic_value_operation('SetDynamicValue', writer,
        IRSource(ability_path, writer['$type'], 'OnStart.FailedTaskList.SetDynamicValue'))
    for writer_id, value, expected in (('other', 9.0, False), ('caster', 2.0, True), ('caster', 0.0, False)):
        request = DynamicValueExecutionRequest(
            caster_id=writer_id, owner_id=writer_id, source_id='passive', effect_id='counter-write',
            opcode='SetDynamicValue', operation_event_id=f'{writer_id}:{value}',
            binding_sources=({'source_type': 'fixture_skill_parameter', 'values': {'1299003598': value}},),
        )
        plan = plan_dynamic_value_operation(state, operation, request)
        assert plan.ok, plan.blocked_reason
        state = MutationReducer().apply_all(state, plan.mutations)
        result = RuleEvaluator().evaluate_condition_result(condition,
            _condition_context(rules, state, detail, None, condition=condition))
        assert result.ok and result.result is expected, result.to_json()


@pytest.fixture(scope='module')
def source():
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    path = root / 'Config/ConfigAbility/Avatar/Avatar_Pela_00_Ability.json'
    return TBGDLowering(root)._lower_ability_file(path, {}, ability_file_order=0), json.loads(path.read_text())


def test_real_callback_admission_reuses_closed_operands_and_preserves_gaps(source):
    lowered, raw = source
    for event, opcode, expected in [('OnAfterAttack', 'SetDynamicValueByStatusCount', 2),
                                     ('OnAfterAttack', 'ModifySPNew', 1),
                                     ('OnListenCharacterDie', 'RemoveModifier', 1)]:
        tasks = [task for task in lowered.status_callback_tasks if task.event == event and task.opcode == opcode]
        assert len(tasks) == expected
        assert all(task.coverage_status == 'executable' and not task.blocked_reason for task in tasks)
    count = next(task for task in lowered.status_callback_tasks
                 if task.event == 'OnBeforeHitAll' and task.opcode == 'SetDynamicValueByStatusCount')
    assert count.coverage_status == 'blocked'
    assert count.blocked_reason == 'unsupported_dynamic_source_target_alias:DamageDefenderEntity'
    damage = next(task for task in lowered.status_callback_tasks
                  if task.event == 'OnAfterAttack' and task.opcode == 'DamageByAttackProperty')
    assert damage.coverage_status == 'blocked'  # The E6 damage shape remains outside this change.
    passive = next(ability for ability in raw['AbilityList'] if ability['Name'] == 'Avatar_Pela_00_PassiveSkill01')
    callback = next(item for item in passive['Modifiers']['Avatar_Pela_00_PassiveSkill01_Modifier']['_CallbackList']
                    if item['Event'] == 'OnAfterAttack')
    task = callback['CallbackConfig'][0]['TaskList'][0]
    assert _status_callback_task_admission('OnAfterAttack', 'SetDynamicValueByStatusCount', task) == ('executable', '')
    for changed in ({**task, 'FutureFlag': True}, {**task, 'ReadTargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Unknown'}},
                    {key: value for key, value in task.items() if key != 'ReadTargetType'}):
        assert _status_callback_task_admission('OnAfterAttack', 'SetDynamicValueByStatusCount', changed)[0] == 'blocked'


@pytest.mark.parametrize('malformed', [False, True])
def test_real_count_callback_reads_retargeted_status_instances_atomically(source, malformed):
    lowered, _ = source
    task = next(task for task in lowered.status_callback_tasks
                if task.event == 'OnAfterAttack' and task.opcode == 'SetDynamicValueByStatusCount')
    callback = next(item for item in lowered.status_callbacks if item.callback_id == task.callback_id)
    effect = next(item for item in lowered.effects if item.effect_id == task.effect_id)
    accumulation = next(item for item in lowered.status_callback_tasks
                        if item.callback_id == task.callback_id and item.opcode == 'SetDynamicValue')
    accumulation_effect = next(item for item in lowered.effects if item.effect_id == accumulation.effect_id)
    rules = RuleBook(CanonicalIR('callback-check', effects=(effect, accumulation_effect)))
    detail = {'instance_id': 'passive', 'status_id': 'passive', 'modifier_name': task.modifier_name,
              'owner_id': 'actor', 'caster_id': 'actor', 'source_id': 'synthetic', 'status_category': 'buff'}
    statuses = [{'instance_id': f'effect:{i}', 'status_id': f'status:{i}', 'modifier_name': f'modifier:{i}',
                 'owner_id': 'target', 'caster_id': 'actor', 'source_id': 'synthetic',
                 'status_category': category, 'stacks': 5}
                for i, category in enumerate(('debuff', 'buff', 'debuff'))]
    if malformed:
        statuses[1]['owner_id'] = 'wrong'
    original = BattleState(units={
        'actor': UnitState('actor', 'ally', 'synthetic', hp=100, max_hp=100,
                           statuses=('passive',), flags={'status_details': [detail]}),
        'target': UnitState('target', 'enemy', 'synthetic', hp=100, max_hp=100,
                            flags={'status_details': statuses}),
    })
    before = original.snapshot().to_json()
    event = GameEvent(event_id='after-attack:retarget', event_type='action.window.after_attack', source_id='actor', target_id='target',
                      payload={'param_entity_id': 'target'})
    result = StatusCallbackSystem(rules)._execute_effect_task(original, callback, task, detail, event, None)
    assert original.snapshot().to_json() == before
    if malformed:
        assert not result.ok and not result.mutations and not result.rng_events
        assert result.after_state == original
        return
    assert result.ok, result.errors
    entries = result.after_state.global_flags['dynamic_value_store']['entries'].values()
    assert [entry['value'] for entry in entries if entry['name'] == 'DebuffNumber_SingleTarget'] == [2.0]
    assert MutationReducer().replay_snapshot(original, result.mutations, result.after_state.snapshot().to_json()).ok
    # The native accumulator has no source-proven initializer here. Reject that
    # missing input, rather than misreporting the preceding write as ambiguous.
    uninitialized = StatusCallbackSystem(rules)._execute_effect_task(
        result.after_state, callback, accumulation, detail, event, None)
    assert not uninitialized.ok and not uninitialized.mutations and not uninitialized.rng_events
    assert uninitialized.errors == ('dynamic_hash_unbound:2612209',)
    # An explicit synthetic initializer isolates the write/read transport check.
    actor = result.after_state.units['actor']
    initialized_detail = dict(actor.flags['status_details'][0])
    values = dict(initialized_detail['dynamic_values'])
    values['__by_hash'] = {**values['__by_hash'], '2612209': 0.0}
    initialized_detail['dynamic_values'] = values
    initialized = replace(result.after_state, units={**result.after_state.units,
        'actor': replace(actor, flags={**actor.flags, 'status_details': [initialized_detail]})})
    accumulated = StatusCallbackSystem(rules)._execute_effect_task(
        initialized, callback, accumulation, initialized_detail, event, None)
    assert accumulated.ok, accumulated.errors
    assert accumulated.after_state.units['actor'].flags['status_details'][0]['dynamic_values']['DebuffNumber'] == 2.0
    assert MutationReducer().replay_snapshot(initialized, accumulated.mutations, accumulated.after_state.snapshot().to_json()).ok
    system = StatusCallbackSystem(rules)
    context = _effect_context(rules, initialized, accumulation, initialized_detail, event)
    foreign = binding_source_from_status_detail(
        {**detail, 'instance_id': 'other-status'}, {'__by_hash': {'262987897': 2.0}})
    conflict = system.effect_registry.execute(accumulation_effect, replace(
        context, binding_sources=(*context.binding_sources, foreign)))
    assert conflict.unsupported == ('dynamic_hash_binding_ambiguous:262987897',)
    assert not conflict.mutations and not conflict.rng_events
    missing = replace(event, target_id='missing', payload={'param_entity_id': 'missing'})
    refused = StatusCallbackSystem(rules)._execute_effect_task(original, callback, task, detail, missing, None)
    assert not refused.ok and not refused.mutations and not refused.rng_events
