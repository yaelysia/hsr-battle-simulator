"""A committed scoped write drives the existing range watcher exactly once."""
from dataclasses import replace

from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, EffectIR, IRSource, AbilityPropertyWatcherIR, AbilityPropertyRangeIR, StatusCallbackIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.dynamic_values import upsert_dynamic_value
from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry
from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackExecutionResult
from hsr.simulator_v8_clean_core.tbgd.lowering import _effect_payload


def test_constant_watcher_bounds_do_not_construct_runtime_binding_sources(monkeypatch):
    from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_fixed
    from hsr.simulator_v8_clean_core.systems import ability_property_watchers as module

    source = IRSource('fixture', 'range', 'constant')
    interval = AbilityPropertyRangeIR('range', 'watcher', 0, numeric_fixed(0), numeric_fixed(1),
        True, False, '', '', source, coverage_status='executable')
    from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem
    rules = RuleBook(CanonicalIR('constant'))
    system = module.AbilityPropertyWatcherSystem(rules, status_callbacks=StatusCallbackSystem(rules))
    def unexpected(*args):
        raise AssertionError('constant bounds requested runtime bindings')
    monkeypatch.setattr(module, '_condition_context', unexpected)
    assert system._range_contains(BattleState(), {}, interval, 0) == (True, '')
    assert system._range_contains(BattleState(), {}, interval, 1) == (False, '')


def test_callback_template_scratch_is_kept_with_each_status_instance():
    import json
    from hsr.simulator_v8_clean_core.systems.dynamic_values import store_from_state, normalized_dynamic_value_store

    source = IRSource('fixture', 'SetDynamicValue', 'scratch')
    raw = {'$type': 'RPG.GameCore.SetDynamicValue', 'DynamicKey': {'Value': 'scratch'},
           'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'ModifierOwnerEntity'},
           'ContextScope': 'ContextTaskTemplate',
           'Value': {'IsDynamic': False, 'FixedValue': {'Value': 5}}}
    effect = EffectIR('scratch', 'SetDynamicValue', _effect_payload(raw, 'SetDynamicValue', '', source=source),
                      source, 'executable', owner_modifier_name='marker')
    rules = RuleBook(CanonicalIR('scratch', effects=(effect,)))
    units = {}
    for owner in ('first', 'second'):
        detail = {'owner_id': owner, 'caster_id': 'first', 'instance_id': owner + ':status',
                  'status_id': 'status', 'modifier_name': 'marker', 'source_id': 'fixture',
                  'dynamic_values': {}, 'lifecycle_state': 'active'}
        units[owner] = UnitState(owner, 'ally', 'fixture', hp=10, max_hp=10,
                                statuses=('status',), flags={'status_details': [detail]})
    state = BattleState(units=units)
    registry = EffectRegistry(StatusSystem(rules))
    for owner in units:
        result = registry.execute(effect, EffectExecutionContext(state, 'first', 'fixture', owner_id=owner,
            event_payload={'event_id': owner + ':heal', 'operation_event_id': owner + ':scratch',
                           'status_instance_id': owner + ':status'}))
        assert not result.unsupported, result.unsupported
        for mutation in result.mutations:
            if mutation.path == ('global_flags', 'dynamic_value_store'):
                # External JSON has no cache marker and must pass every check.
                assert normalized_dynamic_value_store(json.loads(json.dumps(mutation.after))) == mutation.after
        state = MutationReducer().apply_all(state, result.mutations)
    entries = list(store_from_state(state)['entries'].values())
    assert len(entries) == 2 and all(e['scope'] == 'status' and e['value'] == 5 for e in entries)
    assert {e['status_instance_id'] for e in entries} == {'first:status', 'second:status'}
    from hsr.simulator_v8_clean_core.rules.evaluator import RuleEvaluator, NumericEvaluationContext
    from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_dynamic_hash
    from hsr.simulator_v8_clean_core.systems.status_callbacks import _condition_context
    for owner in units:
        detail = state.units[owner].flags['status_details'][0]
        context = _condition_context(rules, state, detail, None)
        read = RuleEvaluator().evaluate_numeric(numeric_dynamic_hash('scratch'),
            NumericEvaluationContext(binding_sources=context.binding_sources))
        assert read.ok and read.value == 5, read.blocked_reason

    # Creation-time shared values must also be reset by a later ability. They
    # are not template scratch, even without a character-card declaration.
    key = effect.payload['standard']['dynamic_operation']['destination_hash']
    shared = upsert_dynamic_value(None, scope='unit', owner_id='first',
                                  value_name='scratch', hash_key=key, value=1)
    state = BattleState(units=units, global_flags={'dynamic_value_store': shared})
    for ability_id in ('', 'later:ability'):
        result = registry.execute(effect, EffectExecutionContext(state, 'first', 'fixture', owner_id='first',
            ability_instance_id=ability_id, event_payload={'event_id': 'shared:' + ability_id,
                'operation_event_id': 'shared:' + ability_id, 'status_instance_id': 'first:status'}))
        assert not result.unsupported, result.unsupported
        state = MutationReducer().apply_all(state, result.mutations)
        entries = tuple(store_from_state(state)['entries'].values())
        assert len(entries) == 1 and entries[0]['scope'] == 'unit' and entries[0]['value'] == 5


def test_status_binding_cache_tracks_the_immutable_status_version_and_filtered_values():
    from hsr.simulator_v8_clean_core.immutable_json import freeze_json, thaw_json
    from hsr.simulator_v8_clean_core.systems.dynamic_values import binding_source_from_status_detail

    detail = freeze_json({'owner_id': 'owner', 'status_id': 'status', 'instance_id': 'instance',
        'stacks': 2, 'remaining_duration': 3, 'dynamic_values': {'charge': 5}})
    original = binding_source_from_status_detail(detail, detail['dynamic_values'])
    assert binding_source_from_status_detail(detail, detail['dynamic_values']) is original
    filtered = binding_source_from_status_detail(detail, {})
    assert 'charge' not in filtered['by_name'] and 'charge' in original['by_name']
    from hsr.simulator_v8_clean_core.systems.status_callbacks import _without_unit_scoped_slots, _slot_hash
    hashes = frozenset({_slot_hash('charge')})
    projected, dropped = _without_unit_scoped_slots(detail['dynamic_values'], hashes)
    assert dropped == hashes
    assert _without_unit_scoped_slots(detail['dynamic_values'], hashes)[0] is projected
    filtered = binding_source_from_status_detail(detail, projected)
    assert binding_source_from_status_detail(detail, projected) is filtered
    assert 'charge' not in filtered['by_name'] and 'Layer' in filtered['by_name']
    assert binding_source_from_status_detail(detail, detail['dynamic_values']) is original
    other, _ = _without_unit_scoped_slots(detail['dynamic_values'], frozenset({'other'}))
    assert 'charge' in binding_source_from_status_detail(detail, other)['by_name']
    changed = thaw_json(detail)
    changed['stacks'] = 1
    changed['dynamic_values']['charge'] = 7
    changed = freeze_json(changed)
    updated = binding_source_from_status_detail(changed, changed['dynamic_values'])
    assert updated != original
    assert sorted(e['value'] for e in updated['entries'].values()) == [1, 1, 1, 3, 3, 3, 7]


def test_status_binding_cache_tracks_the_immutable_status_version_and_filtered_values():
    from hsr.simulator_v8_clean_core.immutable_json import freeze_json, thaw_json
    from hsr.simulator_v8_clean_core.systems.dynamic_values import binding_source_from_status_detail

    detail = freeze_json({'owner_id': 'owner', 'status_id': 'status', 'instance_id': 'instance',
        'stacks': 2, 'remaining_duration': 3, 'dynamic_values': {'charge': 5}})
    original = binding_source_from_status_detail(detail, detail['dynamic_values'])
    assert binding_source_from_status_detail(detail, detail['dynamic_values']) is original
    filtered = binding_source_from_status_detail(detail, {})
    assert 'charge' not in filtered['by_name'] and 'charge' in original['by_name']
    changed = thaw_json(detail)
    changed['stacks'] = 1
    changed['dynamic_values']['charge'] = 7
    updated = binding_source_from_status_detail(freeze_json(changed), changed['dynamic_values'])
    assert updated != original
    assert sorted(e['value'] for e in updated['entries'].values()) == [1, 1, 1, 3, 3, 3, 7]


def test_committed_dynamic_write_notifies_owner_and_caster_without_repeating_equal_write():
    source = IRSource('fixture:dynamic-watch', 'Component', 'charge')
    raw = {'$type': 'RPG.GameCore.SetDynamicValue', 'DynamicKey': {'Value': 'charge'},
           'ContextScope': 'ContextOwner', 'Value': {'IsDynamic': False, 'FixedValue': {'Value': 100}}}
    payload = _effect_payload(raw, 'SetDynamicValue', '', source=source)
    key = str(payload['standard']['dynamic_operation']['destination_hash'])
    effect = EffectIR('write', 'SetDynamicValue', payload, source, 'executable')
    watchers = tuple(AbilityPropertyWatcherIR(name, 'marker', key, (name + ':range',), source,
        property_source=scope, coverage_status='executable') for name, scope in
        (('owner', 'owner_dynamic_value'), ('caster', 'caster_dynamic_value')))
    ranges = tuple(AbilityPropertyRangeIR(w.range_ids[0], w.watcher_id, 0, None, None, True, True,
        '', '', source, coverage_status='executable', change_callback_id=w.watcher_id + ':change') for w in watchers)
    callbacks = tuple(StatusCallbackIR(w.watcher_id + ':change', 'marker', 'OnAbilityPropertyChange', (),
        IRSource(source.source_path, source.raw_type, source.raw_id, {
            'ability_property_watcher_id': w.watcher_id, 'ability_property_range_id': w.range_ids[0],
            'ability_property_range_branch': 'OnChange'}), (0, 0), coverage_status='executable',
        admission_status='executable', scope_kind='ability_property_range') for w in watchers)
    rules = RuleBook(CanonicalIR('dynamic-watch', effects=(effect,), ability_property_watchers=watchers,
                                 ability_property_ranges=ranges, status_callbacks=callbacks))
    def unit(name, watcher):
        detail = {'instance_id': name + ':instance', 'status_id': 'status', 'modifier_name': 'marker',
                  'owner_id': name, 'caster_id': 'owner', 'source_id': 'fixture',
                  'ability_property_watcher_ids': [watcher.watcher_id],
                  'ability_property_watcher_state': {watcher.watcher_id: list(watcher.range_ids)}}
        return UnitState(name, 'ally', 'fixture:' + name, hp=10, max_hp=10, flags={'status_details': [detail]})
    store = upsert_dynamic_value(None, scope='unit', owner_id='owner', hash_key=key, value_name='charge', value=50)
    # A different unit owns the same key; it must not contaminate a caster read.
    store = upsert_dynamic_value(store, scope='unit', owner_id='recipient', hash_key=key, value_name='charge', value=7)
    state = BattleState(units={name: unit(name, w) for name, w in zip(('owner', 'recipient'), watchers)},
                        global_flags={'dynamic_value_store': store})
    registry = EffectRegistry(StatusSystem(rules))
    dispatcher = EventDispatchSystem(rules, registry)
    captured = []
    class Capture:
        def execute_callback_id(self, state, **kwargs):
            fact = kwargs['trigger_event'].ability_property_change_fact
            assert fact.matches_event(kwargs['trigger_event']) and fact.delta == 50
            captured.append(kwargs['unit_id'])
            return StatusCallbackExecutionResult(True, state)
    dispatcher.ability_property_watchers.status_callbacks = Capture()
    for index in range(2):
        result = registry.execute(effect, EffectExecutionContext(state, 'owner', 'fixture', owner_id='owner',
            event_payload={'operation_event_id': str(index)}))
        assert not result.unsupported, result.unsupported
        state = MutationReducer().apply_all(state, result.mutations)
        assert len(result.events) == 1
        event = result.events[0]
        dispatched = dispatcher.dispatch_event(state, event=event)
        assert not dispatched.errors, dispatched.errors
        state = dispatched.after_state
    assert captured == ['owner', 'recipient']
    from hsr.simulator_v8_clean_core.core.content_hooks import ProcessorServices
    services = ProcessorServices(state, rules, producer_id='fixture', event_dispatcher=dispatcher)
    services.set_dynamic_value('owner', 'charge', key, 100., GameEvent('test', source_id='owner', event_id='service'))
    assert not services.finish().blocked_reason and captured == ['owner', 'recipient']
    rejected = dispatcher.dispatch_event(state, event=replace(event, dynamic_value_change_fact=None))
    assert rejected.errors and not rejected.mutations


def test_declared_nonzero_charge_parameters_and_real_turn_owner():
    from hsr.simulator_v8_clean_core.tbgd.adopted_dynamic_parameters import adopt_charge_parameters
    from hsr.simulator_v8_clean_core.rules.ir import CharacterDataCardIR
    from hsr.simulator_v8_clean_core.rules.evaluator import EvaluationContext, RuleEvaluator, _condition_by_is_turn_owner_entity
    from hsr.simulator_v8_clean_core.systems.dynamic_values import character_declared_dynamic_binding_source

    bindings = adopt_charge_parameters({'by_hash': {}},
        'Config/ConfigCharacter/Servant/Servant_PlayerBoyServant_30_Config.json')
    from hsr.simulator_v8_clean_core.immutable_json import freeze_json
    bindings = freeze_json(bindings)
    source = IRSource('fixture:declared', 'Component', 'charge')
    card = CharacterDataCardIR(card_id='card', entity_ref='avatar:fixture', profile_id='profile', skill_ids=(),
        skill_formula_binding_ids=(), bounce_policy_ids=(), action_set={}, source=source, dynamic_value_bindings=bindings)
    rules = RuleBook(CanonicalIR('declared', character_data_cards=(card,)))
    detached = rules.character_dynamic_value_bindings_for_card('card')
    detached['by_hash'].clear()
    assert rules.character_dynamic_value_bindings_for_card('card', detach=False)['by_hash']
    state = BattleState(units={'owner': UnitState('owner', 'ally', 'avatar:fixture'),
                               'other': UnitState('other', 'ally', 'avatar:other')},
                        global_flags={'turn_owner_id': 'other'})
    values = character_declared_dynamic_binding_source(rules, state, 'owner')
    assert {e['hash']: e['value'] for e in values['entries'].values()} == {'1283247492': 100., '1776456860': 1.}
    assert character_declared_dynamic_binding_source(rules, state, 'owner') is values
    changed = replace(state, units={**state.units, 'owner': replace(state.units['owner'], flags={
        'status_details': [{'owner_id': 'owner', 'status_id': 'charge', 'instance_id': 'charge:1',
                            'dynamic_values': {'__by_hash': {'1283247492': 75.}}}]})})
    updated = character_declared_dynamic_binding_source(rules, changed, 'owner')
    assert {e['hash']: e['value'] for e in updated['entries'].values()}['1283247492'] == 75.
    assert character_declared_dynamic_binding_source(rules, state, 'owner') is values
    result = _condition_by_is_turn_owner_entity(RuleEvaluator(), 'ByIsTurnOwnerEntity',
        {'TargetType': {'alias': 'Caster'}},
        EvaluationContext(state=state, actor_id='owner', event_payload={'actor_id': 'owner', 'turn_owner_id': 'owner'}),
        condition_id='turn', source_trace={})
    assert result.ok and result.result is False


def test_visual_dynamic_watcher_is_retained_for_audit_without_runtime_tasks():
    import json
    from pathlib import Path
    from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering

    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    relative = 'Config/ConfigAbility/Servant/Servant_EvernightServant_00_Ability.json'
    doc = json.loads((root / relative).read_text())
    name = 'MServant_EvernightServant_00_PartnerControl'
    raw = doc['AbilityList'][7]['Modifiers'][name]['OnDynamicValueChange']
    lowered, _ = TBGDLowering(root)._lower_ability_property_watchers(raw,
        watcher_event='OnDynamicValueChange', relative=relative, map_name='Modifiers', modifier_name=name,
        ability_file_order=0, callback_index=0, queue_priority_lookup={},
        source_context={'json_path': '$.AbilityList[7].Modifiers.' + name}, task_templates={}, formal_source_context=None)
    assert lowered.ability_property_watchers
    assert all(w.blocked_reason == 'source_proven_presentation_only' for w in lowered.ability_property_watchers)
    assert all(t.blocked_reason == 'source_proven_presentation_only' for t in lowered.status_callback_tasks)
