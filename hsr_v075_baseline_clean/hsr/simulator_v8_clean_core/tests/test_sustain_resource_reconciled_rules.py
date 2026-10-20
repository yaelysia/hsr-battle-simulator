"""PR8 arithmetic and fail-closed checks; synthetic fixtures are not kit acceptance."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.executor import CombatExecutor
from hsr.simulator_v8_clean_core.core.model import ActionCommand, BattleState, Mutation, RNGEvent, TargetResolution, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.ir import (
    AbilityTaskIR, CanonicalIR, ConditionIR, EffectIR, IRSource, StatusCallbackIR,
    StatusCallbackTaskIR, TargetExpressionIR,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.rules.expression_ir import CONDITION_EXPRESSION_NODE_SCHEMA
from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _condition_payload_executable, _effect_coverage_status, _effect_payload, _equipment_task_admission,
    _status_callback_runtime_payload, _status_callback_task_admission, _target_expression_execution_node,
    _typed_condition_payload,
)


def _state():
    return BattleState(units={
        "caster": UnitState("caster", "ally", "synthetic:caster", max_hp=5000.0, hp=1000.0,
                            defense=2000.0, energy=25.0, max_energy=120.0,
                            resources={"outgoing_healing_ratio": 0.2, "shield_added_ratio": 0.25}),
        "target": UnitState("target", "ally", "synthetic:target", max_hp=2000.0, hp=1800.0,
                            defense=100.0, energy=20.0, max_energy=100.0,
                            resources={"incoming_healing_ratio": 0.1, "energy_regeneration_rate": 0.5,
                                       "shield_added_ratio": 2}),
    })


def test_parallel_attack_completion_keeps_parent_capability_and_child_actor():
    from hsr.simulator_v8_clean_core.rules.ir import ActionDefinitionIR, ActionEventIR, ActionPhaseStepIR
    from hsr.simulator_v8_clean_core.systems.action_event_contract import (
        _issue_admitted_action_target_fact, parallel_attack_window_event,
    )

    source = IRSource('synthetic:parallel', 'validation', 'completion')
    definition = ActionDefinitionIR('action', 'action', 1, 'Normal', 'Basic', 'single',
                                   0, 0, 0, 0, (), (), (), None, source, coverage_status='executable')
    step = ActionPhaseStepIR('trigger_window', 'after_attack', 'after_attack', 'OnAfterAttack',
                            coverage_status='executable', source=source)
    action_event = ActionEventIR('action:event', 'action', 1, 'single', 'explicit', (step,), (),
                                'derived', '', source, coverage_status='executable')
    parent = _issue_admitted_action_target_fact(
        actor_id='owner', action_id='action', action_level=1, selection_context_fingerprint='selection',
        contract_fingerprint='contract', impact_fingerprint='impact', canonical_action_event_id='action:event',
        target_mode='single', target_ids=('target',),
    )
    event, scope = parallel_attack_window_event(
        parent_fact=parent, execution_token=object(), command=ActionCommand('servant', 'action', 1, ('target',)),
        definition=definition, action_event=action_event,
        target_resolution=TargetResolution(requested=('target',), legal=('target',), selected=('target',), rejected=()),
        invocation_id='parallel:1', window='after_attack',
    )
    assert event.source_id == 'servant' and event.payload['parallel_parent_actor_id'] == 'owner'
    assert event.admitted_action_target_fact.actor_id == 'servant'
    assert not event.admitted_action_target_fact.invocation_blocked_reason(expected_scope=scope)
    assert parent.actor_id == 'owner' and not parent.event_id


def test_parallel_source_markers_admit_no_extra_death_settlement_and_debug_only():
    from hsr.simulator_v8_clean_core.tbgd.coverage import ability_task_execution_mode
    from hsr.simulator_v8_clean_core.tbgd.lowering import _process_only_ability_task_source_blocked_reason as reason

    finish = {'$type': 'RPG.GameCore.DamagePerformFinish', 'SkipDeathSettlement': True}
    assert not reason(finish, 'DamagePerformFinish')
    assert reason({**finish, 'SkipDeathSettlement': False}, 'DamagePerformFinish')
    assert reason({**finish, 'IsFakeAvatarAttack': True}, 'DamagePerformFinish')
    log = {'$type': 'RPG.GameCore.DebugLog', 'Level': 'Warn', 'Message': 'source diagnostic'}
    assert ability_task_execution_mode('DebugLog') == 'process_only'
    assert not reason(log, 'DebugLog')
    assert reason({**log, 'Mutation': {}}, 'DebugLog')


def test_base_hp_read_excludes_equipment_percentage_flat_and_status_bonuses():
    from hsr.simulator_v8_clean_core.core.model import UnitStatPool
    from hsr.simulator_v8_clean_core.rules.ability_properties import ability_property_is_runtime_readable
    from hsr.simulator_v8_clean_core.systems.unit_stats import ability_property_value

    unit = UnitState('caster', 'ally', 'synthetic:caster', hp=700, max_hp=700,
                     stat_pools=(UnitStatPool('max_hp', 400, 0.5, 100),),
                     flags={'status_details': [{'modifiers': [
                         {'bucket': 'attribute', 'key': 'hp_added_ratio', 'value': 0.25},
                     ]}]})
    assert ability_property_is_runtime_readable('BaseHP')
    assert ability_property_value(unit, 'BaseHP') == 400
    assert ability_property_value(unit, 'CurrentHP') == 700
    assert ability_property_value(unit, 'MaxHP') == 800


def test_source_produced_base_speed_is_not_counted_again_from_birth_panel():
    from hsr.simulator_v8_clean_core.core.model import UnitStatPool
    from hsr.simulator_v8_clean_core.systems.unit_stats import effective_unit_stat

    event = UnitState('event', 'summon', 'synthetic:event', speed=100,
                      stat_pools=(UnitStatPool('speed', 100),), flags={
                          'status_produced_base_stats': ['speed'],
                          'status_details': [{'modifiers': [
                              {'bucket': 'attribute', 'key': 'speed_base_delta', 'value': 100},
                          ]}],
                      })
    assert effective_unit_stat(event, 'speed').value == 100
    regular = replace(event, flags={**event.flags, 'status_produced_base_stats': []})
    assert effective_unit_stat(regular, 'speed').value == 200


def test_battle_event_caster_reads_the_committed_creator_relation():
    from hsr.simulator_v8_clean_core.systems.target import TargetSystem
    from hsr.simulator_v8_clean_core.systems.unit_relation import TargetEvaluationContext

    path = 'Config/GlobalConfig/TargetAliasConfig.json'
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    raw = json.loads((root / path).read_text())['AliasDict']['BattleEventCaster']
    source = IRSource(path, raw['$type'], 'BattleEventCaster', {'json_path': '$.AliasDict.BattleEventCaster'})
    node = _target_expression_execution_node(raw, source)
    assert not node.runtime_blocked_reason
    expression = TargetExpressionIR('fixture:event-caster', node.expression_kind, 'BattleEventCaster',
                                    source, node=node, coverage_status='executable')
    state = _state()
    state = replace(state, units={**state.units, 'event': UnitState(
        'event', 'summon', 'fixture:event', flags={'entity_type': 'battle_event', 'summoner_id': 'caster'},
    )})
    targets = TargetSystem(RuleBook(CanonicalIR('fixture:event-caster', target_expressions=(expression,))))
    result = targets.resolve_target_expression(state, expression, context=TargetEvaluationContext(caster_id='event'))
    assert result.resolved and result.target_ids == ('caster',), result
    blocked = targets.resolve_target_expression(state, expression, context=TargetEvaluationContext(caster_id='caster'))
    assert not blocked.resolved and blocked.blocked_reason == 'battle_event_caster_requires_event'


def test_template_targets_stay_separate_from_current_parameters_in_effect_consumers(monkeypatch):
    from hsr.simulator_v8_clean_core.systems import effect as effect_module
    from hsr.simulator_v8_clean_core.systems.status import StatusInstance, StatusSystem

    source = IRSource('synthetic:template', 'TargetFetchTemplateEntityList', 'template',
                      {'json_path': '$.TargetType'})
    node = _target_expression_execution_node({'$type': 'RPG.GameCore.TargetFetchTemplateEntityList'}, source)
    expression = TargetExpressionIR('fixture:template', node.expression_kind, 'TemplateParamEntityList',
                                    source, node=node, coverage_status='executable')
    rules = RuleBook(CanonicalIR('fixture:template', target_expressions=(expression,)))
    status = StatusSystem(rules)
    registry = EffectRegistry(status)
    state = _state()
    detail = StatusInstance('fixture:buff:1', 'fixture:buff', 'fixture:buff', 'target',
        'fixture:source', 'caster', behavior_flags=('fixture',), remaining_duration=2,
        duration_admission={'admission_status': 'executable'}).to_json()
    state = replace(state, units={**state.units, 'target': replace(state.units['target'],
                    statuses=(detail['status_id'],), flags={'status_details': [detail]})})
    standard = {'target_alias': expression.alias, 'target_expression_id': expression.target_expression_id,
                'behavior_flags': ['fixture'], 'amount': {'kind': 'fixed', 'value': 1}}
    effect = EffectIR('fixture:extend', 'ExtendModifierLifeTime', {'standard': standard}, source,
                      coverage_status='executable')
    context = EffectExecutionContext(state, 'caster', 'fixture:template', param_entity_id='caster',
        target_resolution=TargetResolution(('caster',), ('caster',), ('caster',)),
        template_target_ids=('target',))
    result = registry._execute_modifier_lifetime(effect, context)
    assert not result.unsupported and result.mutations[0].path == ('units', 'target', 'flags', 'status_details')
    assert result.mutations[0].after[0]['remaining_duration'] == 3
    missing = registry._execute_modifier_lifetime(effect, replace(context, template_target_ids=None))
    assert missing.unsupported == ('target_template_parameters_missing',)
    selected, reason, _, _ = status._resolve_add_modifier_targets(
        state, standard, caster_id='caster', owner_id='caster', param_entity_id='caster',
        current_action_target_id=None, target_resolution=context.target_resolution,
        event_payload=None, dynamic_values=None, binding_sources=(),
        admitted_action_target_fact=None, expected_action_window_scope=None,
        template_target_ids=context.template_target_ids,
    )
    assert not reason and selected == ('target',)
    captured = []
    original = effect_module.plan_dynamic_value_operation
    def capture(current, operation, request, *, rules=None):
        captured.append(request)
        return original(current, operation, request, rules=rules)
    monkeypatch.setattr(effect_module, 'plan_dynamic_value_operation', capture)
    raw = {'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Caster'},
           'DynamicKey': {'Value': 'fixture_value'}, 'Value': {'FixedValue': {'Value': 1}}}
    dynamic = EffectIR('fixture:write', 'SetDynamicValue',
        _effect_payload(raw, 'SetDynamicValue', '', source=source), source, coverage_status='executable')
    written = registry.execute(dynamic, replace(context, ability_instance_id='fixture:ability',
        event_payload={'operation_event_id': 'fixture:operation', 'task_id': 'fixture:write'}))
    assert not written.unsupported and captured[0].template_target_ids == ('target',)
    assert captured[0].to_json()['template_target_ids'] == ['target']


def test_attached_skill_restriction_only_blocks_its_type_and_ends_with_status():
    from hsr.simulator_v8_clean_core.systems.status import status_control_gate_for_actor

    unit = UnitState('caster', 'ally', 'synthetic:caster', statuses=['test:disable'], flags={
        'status_details': [{'status_id': 'test:disable', 'instance_id': 'test:instance',
                            'lifecycle_state': 'active', 'disabled_skill_types': ['Skill']}],
    })
    assert status_control_gate_for_actor(unit) is None
    assert status_control_gate_for_actor(unit, skill_type='Normal') is None
    assert status_control_gate_for_actor(unit, skill_type='Ultra') is None
    assert status_control_gate_for_actor(unit, skill_type='Skill') is not None
    assert status_control_gate_for_actor(replace(unit, statuses=[]), skill_type='Skill') is None


def test_target_validity_uses_resolved_targets():
    from hsr.simulator_v8_clean_core.rules.evaluator import EvaluationContext, RuleEvaluator, _condition_target_key

    source = IRSource('synthetic:validity', 'ByIsTargetValid', 'test', {'json_path': '$.Predicate'})
    payload = _typed_condition_payload('ByIsTargetValid', {
        'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'CasterServant'}, 'AliveOnly': True,
    }, source=source)
    condition = ConditionIR('test:validity', 'ByIsTargetValid', payload, source,
                            coverage_status='executable', expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA)
    key = _condition_target_key(payload['TargetType'])
    context = EvaluationContext(state=_state(), actor_id='caster', resolved_target_groups={key: ('target',)})
    assert RuleEvaluator().evaluate_condition(condition, context) is True
    assert RuleEvaluator().evaluate_condition(condition, replace(context, resolved_target_groups={key: ()})) is False
    assert RuleEvaluator().evaluate_condition(condition, replace(context, target_resolution_errors={key: 'unresolved'})) is None
    contains_payload = _typed_condition_payload('ByIsContainModifier', {
        'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'CasterServant'},
        'ModifierName': {'Value': 'test:missing'},
    }, source=source)
    contains = replace(condition, opcode='ByIsContainModifier', payload=contains_payload)
    assert RuleEvaluator().evaluate_condition(contains, context) is False
    assert RuleEvaluator().evaluate_condition(contains, replace(context, target_resolution_errors={key: 'unresolved'})) is None


def _effect(opcode, **fields):
    raw = {"$type": f"RPG.GameCore.{opcode}", "TargetType": {"Alias": "ParamEntity"}, **fields}
    payload = _effect_payload(raw, opcode, "")
    return EffectIR("synthetic:sustain", opcode, payload,
                    IRSource("synthetic:sustain", opcode, "test"),
                    _effect_coverage_status(opcode, payload))


def _execute(effect, state=None, **context_fields):
    state = state or _state()
    before = state.snapshot().to_json()
    context = EffectExecutionContext(state, "caster", "synthetic:test", owner_id="target",
                                     param_entity_id="target", current_action_target_id="target",
                                     **context_fields)
    result = EffectRegistry().execute(effect, context)
    assert state.snapshot().to_json() == before
    return state, result


def _commit_and_replay(state, result):
    assert not result.unsupported, result.records
    assert result.mutations
    reducer = MutationReducer()
    after = reducer.apply_all(state, result.mutations)
    replay = reducer.replay_snapshot(state, result.mutations, after.snapshot().to_json())
    assert replay.ok, replay.errors
    return after


def test_group_heal_resolves_living_team_and_discards_partial_failure():
    from hsr.simulator_v8_clean_core.systems.effect import PreHealDispatchResult
    from hsr.simulator_v8_clean_core.systems.status import StatusSystem

    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    path = "Config/GlobalConfig/TargetAliasConfig.json"
    aliases = json.loads((root / path).read_text())["AliasDict"]
    raw = aliases["AllTeamMember"]
    source = IRSource(path, raw["$type"], "AllTeamMember", {
        "json_path": "$.AliasDict.AllTeamMember", "source_raw_id": "AllTeamMember",
    })
    node = _target_expression_execution_node(raw, source)
    expression = TargetExpressionIR("test:team", node.expression_kind, "AllTeamMember", source,
                                    node=node, coverage_status="executable")
    caster_source = IRSource(path, aliases["Caster"]["$type"], "Caster", {
        "json_path": "$.AliasDict.Caster", "source_raw_id": "Caster",
    })
    caster_node = _target_expression_execution_node(aliases["Caster"], caster_source)
    caster_expression = TargetExpressionIR("test:caster", caster_node.expression_kind, "Caster", caster_source,
                                           node=caster_node, coverage_status="executable")
    effect = _effect("HealHP", ModifyValue={"Value": 50})
    effect = replace(effect, payload={**effect.payload, "standard": {
        **effect.payload["standard"], "target_alias": expression.alias,
        "target_expression_id": expression.target_expression_id, "target_expression_coverage_status": "executable",
    }})
    state = replace(_state(), units={**_state().units,
        "enemy": UnitState("enemy", "enemy", "synthetic:enemy", hp=10, max_hp=100),
        "dead": UnitState("dead", "ally", "synthetic:dead", hp=0, max_hp=100, lifecycle_status="defeated"),
    })
    registry = EffectRegistry(StatusSystem(RuleBook(CanonicalIR(version="test:group-heal",
                                                               target_expressions=(expression, caster_expression)))))
    context = EffectExecutionContext(state, "caster", "synthetic:group")
    result = registry.execute(effect, context)
    after = _commit_and_replay(state, result)
    assert after.units["caster"].hp == 1060
    assert after.units["target"].hp == 1865
    assert after.units["enemy"].hp == 10 and after.units["dead"].hp == 0
    visited = []

    def fail_second(_effect, current):
        visited.append(current.current_action_target_id)
        if len(visited) == 2:
            assert current.state.units[visited[0]].hp > state.units[visited[0]].hp
            return PreHealDispatchResult(False, current.state, errors=("test:second-target-failed",))
        return PreHealDispatchResult(True, current.state)

    registry.set_pre_heal_dispatcher(fail_second)
    before = state.snapshot().to_json()
    failed = registry.execute(effect, context)
    assert len(visited) == 2 and failed.unsupported == ("test:second-target-failed",)
    assert not failed.mutations and not failed.events and not failed.rng_events
    assert state.snapshot().to_json() == before


def test_action_dynamic_reads_ignore_previous_instances_and_other_owners():
    from hsr.simulator_v8_clean_core.rules.evaluator import NumericEvaluationContext, RuleEvaluator
    from hsr.simulator_v8_clean_core.systems.ability import _binding_sources
    from hsr.simulator_v8_clean_core.systems.dynamic_values import upsert_dynamic_value
    from hsr.simulator_v8_clean_core.systems.effect import _binding_sources as effect_binding_sources

    store = None
    for owner, instance, value in (("caster", "old", 0), ("caster", "current", 2),
                                    ("target", "current", 9)):
        store = upsert_dynamic_value(store, scope="ability", owner_id=owner, value=value,
                                     value_name="duration", hash_key=123, ability_instance_id=instance)
    state = replace(_state(), global_flags={"dynamic_value_store": store})
    rules = RuleBook(CanonicalIR(version="test:ability-scope"))
    expression = {"schema_version": "hsr.numeric_expression.v1", "kind": "dynamic_hash", "hash": 123}
    for instance, expected in (("current", 2), ("old", 0), ("missing", None)):
        context = EffectExecutionContext(
            state, "caster", "test", ability_instance_id=instance,
            include_ambient_status_bindings=False,
            binding_sources=_binding_sources(rules, state, "caster", "target", ability_instance_id=instance),
        )
        result = RuleEvaluator().evaluate_numeric(expression, NumericEvaluationContext(
            binding_sources=effect_binding_sources(context),
        ))
        assert result.value == expected and result.ok == (expected is not None), result.to_json()


def test_declared_mutable_initial_value_does_not_duplicate_current_or_read_old_ability():
    from hsr.simulator_v8_clean_core.rules.ir import CharacterDataCardIR
    from hsr.simulator_v8_clean_core.rules.evaluator import NumericEvaluationContext, RuleEvaluator
    from hsr.simulator_v8_clean_core.systems.ability import _binding_sources
    from hsr.simulator_v8_clean_core.systems.dynamic_values import upsert_dynamic_value
    source = IRSource('synthetic:declaration', 'validation', 'initial')
    card = CharacterDataCardIR('card', 'avatar:test', 'profile', (), (), (), source,
        dynamic_value_bindings={'by_hash': {'123': {
            'read_info': {'Type': 'None', 'Index': 0}, 'source_path': 'synthetic:declaration',
        }}})
    rules = RuleBook(CanonicalIR(version='test:declared-value', character_data_cards=(card,)))
    store = None
    for instance, value in [('old', 9), ('current', 2)]:
        store = upsert_dynamic_value(store, scope='ability', owner_id='caster', value=value,
                                     hash_key=123, value_name='ratio', ability_instance_id=instance)
    state = _state()
    state = replace(state, units={**state.units, 'caster': replace(state.units['caster'], template_id='avatar:test')},
                    global_flags={'dynamic_value_store': store})
    for instance, expected in [('current', 2), ('new', 0)]:
        result = RuleEvaluator().evaluate_numeric(
            {'schema_version': 'hsr.numeric_expression.v1', 'kind': 'dynamic_hash', 'hash': 123},
            NumericEvaluationContext(binding_sources=_binding_sources(
                rules, state, 'caster', 'target', ability_instance_id=instance,
            )),
        )
        assert result.ok and result.value == expected, result.to_json()


def test_hit_callbacks_belong_to_attacker_and_being_hit_to_victim():
    from hsr.simulator_v8_clean_core.core.model import GameEvent
    from hsr.simulator_v8_clean_core.systems.event_dispatch import _event_aliases, _scope_matches
    from hsr.simulator_v8_clean_core.tbgd.lowering import _status_callback_scope_kind
    hit = GameEvent('damage.hit', source_id='caster', target_id='target',
                    payload={'attacker_id': 'caster', 'current_hit_target_id': 'target'})
    actor_hit = replace(hit, event_type='damage.attacker_hit')
    aliases = {alias.callback_event: alias.scope_kind for event in (hit, actor_hit)
               for alias in _event_aliases(event, None)}
    assert aliases['OnAfterHit'] == _status_callback_scope_kind('OnAfterHit') == 'actor_local'
    assert _scope_matches(hit, aliases['OnAfterHit'], {'owner_id': 'caster'}, explicit=False)[0]
    assert not _scope_matches(hit, aliases['OnAfterHit'], {'owner_id': 'target'}, explicit=False)[0]
    assert _scope_matches(hit, aliases['OnBeingHit'], {'owner_id': 'target'}, explicit=False)[0]
    before = replace(hit, event_type='damage.before_hit')
    assert _event_aliases(before, None)[0].scope_kind == _status_callback_scope_kind('OnBeforeHit') == 'actor_local'
    from hsr.simulator_v8_clean_core.rules.ir import ActionDefinitionIR
    from hsr.simulator_v8_clean_core.systems.damage import DamagePacket, _damage_events
    from hsr.simulator_v8_clean_core.systems.event_dispatch import _event_with_typed_param_entity
    source = IRSource('synthetic:hit', 'validation', 'producer')
    definition = ActionDefinitionIR('action', 'action', 1, 'Normal', 'Basic', 'single',
                                   0, 0, 0, 0, (), (), (), None, source)
    events = _damage_events(DamagePacket('caster', 'target', 'Normal', 'direct', action_definition=definition),
                            record_type='damage', amount=10, before_hp=100, after_hp=90)
    assert [(event.event_type, event.payload['param_entity_id']) for event in events] == [
        ('damage.hit', 'caster'), ('damage.attacker_hit', 'target'),
    ]
    normalized, reason = _event_with_typed_param_entity(_state(), events[1])
    assert not reason and normalized.event_id and normalized.payload['param_entity_id'] == 'target'


def test_status_target_self_inherits_each_recipient_as_caster():
    from hsr.simulator_v8_clean_core.systems.status import StatusSystem
    from hsr.simulator_v8_clean_core.tbgd.lowering import _modifier_definition_entity
    source = IRSource('synthetic:inherit', 'AddModifier', 'inherit')
    definition = _modifier_definition_entity('synthetic:inherit', 'GlobalModifiers', 'test:buff', {'Stacking': 'Replace'})
    raw = {'ModifierName': {'Value': 'test:buff'}, 'InheritCaster': 'TargetSelf',
           'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'ParamEntity'}}
    payload = _effect_payload(raw, 'AddModifier', '', source=source)
    from hsr.simulator_v8_clean_core.tbgd.lowering import _attach_target_expressions_to_effect_payload
    payload, targets = _attach_target_expressions_to_effect_payload(payload, raw, effect_id='inherit', source=source)
    effect = EffectIR('inherit', 'AddModifier', payload, source, coverage_status='executable', source_mode='mainline')
    rules = RuleBook(CanonicalIR(version='test:inherit', entities=(definition,), effects=(effect,), target_expressions=tuple(targets)))
    state = _state()
    result = StatusSystem(rules).apply_add_modifier(
        state, effect, caster_id='caster', source_id='source:inherit', param_entity_id='target',
        _resolved_target_ids=('caster', 'target'),
    )
    assert not result.unsupported, result.unsupported
    after = MutationReducer().apply_all(state, result.mutations)
    assert after.units['target'].flags['status_details'][0]['caster_id'] == 'target'
    assert after.units['caster'].flags['status_details'][0]['caster_id'] == 'caster'
    unsupported = _effect_payload({**raw, 'InheritCaster': {'invalid': True}}, 'AddModifier', '')
    assert _effect_coverage_status('AddModifier', unsupported) == 'blocked'


def test_status_copy_reuses_the_typed_dynamic_operation():
    raw = {'$type': 'RPG.GameCore.SetDynamicValueByCopying',
           'FromTargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'ModifierOwnerEntity'},
           'FromDynamicKey': {'Value': 'maximum'}, 'FromModifierName': {'Value': 'test:source'},
           'ToTargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'ModifierOwnerEntity'},
           'ToDynamicKey': {'Value': 'maximum'}}
    assert _status_callback_task_admission('OnStack', 'SetDynamicValueByCopying', raw,
        source_modifier_name='test:destination') == ('executable', '')


def test_ability_cross_unit_write_reads_the_caster_value():
    from hsr.simulator_v8_clean_core.systems.dynamic_values import upsert_dynamic_value
    source = IRSource('synthetic:cross-write', 'SetDynamicValue', 'check')
    raw = {'$type': 'RPG.GameCore.SetDynamicValue',
           'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'ParamEntity'},
           'DynamicKey': {'Value': 'copied'}, 'Value': {'IsDynamic': True,
               'PostfixExpr': {'OpCodes': 'AQAR', 'FixedValues': [], 'DynamicHashes': [123]}}}
    payload = _effect_payload(raw, 'SetDynamicValue', '', source=source)
    effect = EffectIR('cross-write', 'SetDynamicValue', payload, source, coverage_status='executable')
    state = _state()
    store = None
    for actor, instance, value in [('caster', 'ability:current', 42), ('caster', 'ability:old', 77),
                                    ('target', 'ability:current', 99)]:
        store = upsert_dynamic_value(store, scope='ability', owner_id=actor, value=value, hash_key=123,
                                     value_name='source_value', ability_instance_id=instance)
    state = replace(state, global_flags={'dynamic_value_store': store})
    result = EffectRegistry().execute(effect, EffectExecutionContext(
        state, 'caster', 'test:cross-write', owner_id='caster', ability_instance_id='ability:current',
        param_entity_id='target',
        event_payload={'task_id': 'task:cross-write', 'operation_event_id': 'event:cross-write'},
        include_ambient_status_bindings=False,
    ))
    assert not result.unsupported, result.unsupported
    mutation = next(m for m in result.mutations if m.path == ('global_flags', 'dynamic_value_store'))
    entry = next(e for e in mutation.after['entries'].values() if e.get('name') == 'copied')
    assert entry['target_id'] == 'target' and entry['value'] == 42


def test_repeated_hit_flag_write_keeps_ledger_without_duplicate_status_mutation():
    source = IRSource('synthetic:hit-flag', 'SetDynamicValue', 'flag')
    raw = {'$type': 'RPG.GameCore.SetDynamicValue',
           'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Caster'},
           'DynamicKey': {'Value': 'hit'}, 'Value': {'IsDynamic': False, 'FixedValue': {'Value': 1}}}
    payload = _effect_payload(raw, 'SetDynamicValue', 'fixture', source=source)
    effect = EffectIR('hit-flag', 'SetDynamicValue', payload, source,
                      coverage_status='executable', owner_modifier_name='fixture')
    state = _state()
    state = replace(state, units={**state.units, 'caster': replace(state.units['caster'],
        statuses=('modifier:fixture',), flags={'status_details': [{
            'status_id': 'modifier:fixture', 'instance_id': 'fixture:1', 'modifier_name': 'fixture',
            'owner_id': 'caster', 'caster_id': 'caster', 'source_id': 'fixture:source',
        }]})})
    seen = set()
    for hit in range(3):
        result = EffectRegistry().execute(effect, EffectExecutionContext(
            state, 'caster', 'fixture:source', owner_id='caster', event_payload={
                'status_instance_id': 'fixture:1', 'operation_event_id': f'hit:{hit}', 'task_id': 'hit-flag',
            },
        ))
        assert not result.unsupported, result.unsupported
        assert len(result.mutations) == (2 if hit == 0 else 1)
        identities = {m.stable_id() for m in result.mutations}
        assert not identities & seen
        seen.update(identities)
        state = MutationReducer().apply_all(state, result.mutations)
    assert len(state.global_flags['dynamic_value_store']['operation_ledger']) == 3


def test_empty_presence_marker_can_be_ensured_by_two_tasks_of_the_same_caster():
    from hsr.simulator_v8_clean_core.systems.status import StatusSystem
    from hsr.simulator_v8_clean_core.tbgd.lowering import (
        _attach_target_expressions_to_effect_payload, _modifier_definition_entity,
    )
    definition = _modifier_definition_entity('fixture:marker', 'Modifiers', 'marker', {})
    source = IRSource('fixture:marker', 'AddModifier', 'first')
    raw = {'$type': 'RPG.GameCore.AddModifier',
           'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Caster'},
           'ModifierName': {'Value': 'marker'}}
    payload = _effect_payload(raw, 'AddModifier', '', source=source)
    payload, targets = _attach_target_expressions_to_effect_payload(payload, raw, effect_id='first', source=source)
    first = EffectIR('first', 'AddModifier', payload, source, 'executable',
                     modifier_definition_id=definition.entity_id, source_mode='mainline')
    second = replace(first, effect_id='second', source=replace(source, raw_id='second'))
    system = StatusSystem(RuleBook(CanonicalIR('fixture:marker', entities=(definition,),
        effects=(first, second), target_expressions=tuple(targets))))
    state = _state()
    for effect in (first, second):
        result = system.apply_add_modifier(state, effect, caster_id='caster', owner_id='caster',
            source_id=effect.effect_id, _resolved_target_ids=('caster',))
        assert result.ok, result.unsupported
        state = MutationReducer().apply_all(state, result.mutations)
    assert len(state.units['caster'].flags['status_details']) == 1


def test_destroy_callback_keeps_local_writes_without_restoring_removed_status():
    from hsr.simulator_v8_clean_core.systems.status import StatusSystem
    from hsr.simulator_v8_clean_core.systems.status_callbacks import _current_status_detail, _effect_context
    from hsr.simulator_v8_clean_core.systems.task_graph import _freeze_event

    source = IRSource('synthetic:destroy', 'RemoveModifier', 'remove', {'json_path': '$.Remove'})
    raw = {'$type': 'RPG.GameCore.RemoveModifier',
           'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Caster'},
           'ModifierName': {'Value': 'fixture'}}
    payload = _effect_payload(raw, 'RemoveModifier', '', source=source)
    node = _target_expression_execution_node({'$type': 'RPG.GameCore.TargetFetchCaster'}, source)
    expression = TargetExpressionIR('remove:caster', node.expression_kind, 'Caster', source,
                                    node=node, coverage_status='executable')
    payload['standard']['target_expression_id'] = expression.target_expression_id
    effect = EffectIR('remove', 'RemoveModifier', payload, source, 'executable')
    rules = RuleBook(CanonicalIR('synthetic:destroy', target_expressions=(expression,)))
    system = StatusSystem(rules)
    detail = {'status_id': 'modifier:fixture', 'instance_id': 'fixture:1', 'modifier_name': 'fixture',
              'owner_id': 'caster', 'caster_id': 'caster', 'source_id': 'fixture:source',
              'dynamic_values': {'counter': 7.0}}
    initial = _state()
    initial = replace(initial, units={**initial.units, 'caster': replace(initial.units['caster'],
        statuses=('modifier:fixture',), flags={'status_details': [detail]})})
    removed = system.apply_remove_modifier(initial, effect, caster_id='caster', source_id='test:remove')
    assert removed.ok, removed.unsupported
    state = MutationReducer().apply_all(initial, removed.mutations)
    repeated = system.apply_remove_modifier(state, effect, caster_id='caster', source_id='test:remove-again')
    assert repeated.ok and not repeated.mutations and not repeated.events
    event = _freeze_event(next(e for e in removed.events if e.window == 'OnDestroy'))
    raw_write = {'$type': 'RPG.GameCore.SetDynamicValue', 'DynamicKey': {'Value': 'counter'},
                 'Value': {'IsDynamic': False, 'FixedValue': {'Value': 0}}}
    write = EffectIR('write', 'SetDynamicValue', _effect_payload(raw_write, 'SetDynamicValue', 'fixture', source=source),
                     source, 'executable', owner_modifier_name='fixture')
    task = StatusCallbackTaskIR('write', 'destroy', 'fixture', 'OnDestroy', 0, '$.Write', 'root',
                                'SetDynamicValue', source)
    context = _effect_context(rules, state, task, detail, event)
    denied = EffectRegistry().execute(write, replace(context, status_lifecycle_plan=None))
    assert denied.unsupported == ('dynamic_status_instance_missing',) and not denied.mutations
    result = EffectRegistry().execute(write, context)
    assert not result.unsupported, result.unsupported
    after = MutationReducer().apply_all(state, result.mutations)
    assert not after.units['caster'].statuses and not after.units['caster'].flags['status_details']
    assert _current_status_detail(after, detail)['dynamic_values']['counter'] == 0
    assert all(m.path == ('global_flags', 'dynamic_value_store') for m in result.mutations)
    assert MutationReducer().replay_snapshot(state, result.mutations, after.snapshot().to_json()).ok
    from hsr.simulator_v8_clean_core.systems.event_dispatch import EventAlias, EventDispatchSystem
    observer = {**detail, 'status_id': 'modifier:observer', 'instance_id': 'observer:1', 'modifier_name': 'observer'}
    observed = replace(state, units={**state.units, 'caster': replace(state.units['caster'],
        statuses=('modifier:observer',), flags={'status_details': [observer]})})
    callbacks = tuple(StatusCallbackIR(name, name, 'OnModifierRemove', (), source, (0, index),
        scope_kind='status_local', coverage_status='executable', admission_status='executable')
        for index, name in enumerate(('fixture', 'observer')))
    dispatch = EventDispatchSystem(RuleBook(CanonicalIR('fixture:removal-listeners', status_callbacks=callbacks)), EffectRegistry())
    notification = next(e for e in removed.events if e.window == 'OnModifierRemove')
    matches = dispatch._resolve_listener_matches(observed, event=notification,
        aliases=(EventAlias('OnModifierRemove', 'status_local', 'fixture'),), unit_id=None, modifier_name=None)
    assert [match.modifier_name for match in matches] == ['observer']


def test_servant_retirement_source_admission_keeps_gameplay_and_animation_separate():
    from hsr.simulator_v8_clean_core.tbgd.lowering import _process_only_ability_task_source_blocked_reason
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    path = 'Config/ConfigAbility/Servant/Servant_AglaeaServant_00_Ability.json'
    document = json.loads((root / path).read_text())
    ability = next(a for a in document['AbilityList']
                   if a['Name'] == 'Servant_Aglaea_00_PassiveSkill01_ForceKill_Insert')
    phase, kill, finish = [next(t for t in ability['OnStart'] if t['$type'].endswith('.' + opcode))
                           for opcode in ('CharacterChangePhase', 'ForceKill', 'SetDieImmediately')]
    assert not _process_only_ability_task_source_blocked_reason(phase, 'CharacterChangePhase')
    assert _process_only_ability_task_source_blocked_reason({**phase, 'CombatPhase': 2}, 'CharacterChangePhase')
    for raw, opcode in ((kill, 'ForceKill'), (finish, 'SetDieImmediately')):
        payload = _effect_payload(raw, opcode, '')
        assert _effect_coverage_status(opcode, payload) == 'executable'
    assert _effect_coverage_status('ForceKill', _effect_payload({**kill, 'MuteAllTriggerDeath': False}, 'ForceKill', '')) == 'blocked'
    modifier = next(a['Modifiers']['MServant_AglaeaServant_00_DeathRattle']
                    for a in document['AbilityList'] if 'MServant_AglaeaServant_00_DeathRattle' in a.get('Modifiers', {}))
    task = modifier['_CallbackList'][0]['CallbackConfig'][0]
    assert _status_callback_task_admission('OnDeathrattle', 'ModifySPNew', task) == ('executable', '')
    passive = next(a['Modifiers']['MServant_AglaeaServant_Passive']
                   for a in document['AbilityList'] if 'MServant_AglaeaServant_Passive' in a.get('Modifiers', {}))
    reset = next(c for c in passive['_CallbackList'] if c['Event'] == 'OnDestroy')['CallbackConfig'][0]
    operation = _effect_payload(reset, 'SetDynamicValue', '')['standard']['dynamic_operation']
    assert (operation['scope_kind'], operation['lifecycle']) == ('unit', 'combat')


def test_adopted_toughness_parameters_are_available_to_ability_operands():
    from hsr.simulator_v8_clean_core.rules.ir import HitProfileIR
    from hsr.simulator_v8_clean_core.rules.evaluator import NumericEvaluationContext, RuleEvaluator
    from hsr.simulator_v8_clean_core.systems.ability import _binding_sources

    source = IRSource('synthetic:toughness', 'validation', 'parameter')
    expression = {'kind': 'fixed', 'value': 60, 'dynamic_hash': 123,
                  'source_kind': 'adopted_fixed_skill_toughness', 'source_trace': source.to_json()}
    profile = HitProfileIR('hit', 'action', 1, 0, 'primary', {}, {}, expression, {},
                           'attack', 'Thunder', source, coverage_status='executable')
    rules = RuleBook(CanonicalIR(version='test:toughness-param', hit_profiles=(
        profile, replace(profile, hit_profile_id='same-parameter-hit', hit_index=1),
    )))
    context = NumericEvaluationContext(binding_sources=_binding_sources(
        rules, _state(), 'caster', 'target', action_id='action', action_level=1,
    ))
    result = RuleEvaluator().evaluate_numeric(
        {'schema_version': 'hsr.numeric_expression.v1', 'kind': 'dynamic_hash', 'hash': 123}, context,
    )
    assert result.ok and result.value == 60, result.to_json()


def test_one_composite_damage_request_does_not_expand_description_parameters_into_hits():
    from hsr.simulator_v8_clean_core.rules.ir import HitProfileIR, SkillFormulaBindingIR
    from hsr.simulator_v8_clean_core.tbgd.lowering import (
        _binding_param_multiplier_expr, _target_profiles_for_damage_task,
    )
    source = IRSource('synthetic:joint', 'validation', 'request')
    task = AbilityTaskIR('task', 'phase', 'action', 1, 'ability', 'OnStart', 0,
                         'OnStart[0]', '', 'DamageByAttackProperty', source)
    raw = {'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'AbilityTargetEntity'},
           'AttackProperty': {'DamagePercentage': {'IsDynamic': True, 'PostfixExpr': {
               'OpCodes': 'AQABAQIR', 'FixedValues': [], 'DynamicHashes': [7, 8]}}}}
    effect = EffectIR('effect', 'DamageByAttackProperty', raw, source)
    profile = HitProfileIR('hit:0', 'action', 1, 0, 'primary', {}, {'param_index': 0, 'raw_path': 'ParamList[0]'}, {}, {},
                           'direct', 'Thunder', source, coverage_status='executable')
    profiles = (profile, replace(profile, hit_profile_id='hit:2', hit_index=1,
                                multiplier_source={'param_index': 2, 'raw_path': 'ParamList[2]'}))
    binding = SkillFormulaBindingIR('binding:0', 'card', 'slot', 'action', 1, 0, 0, 'direct_damage',
        'primary', {'Value': 1}, {'kind': 'unit_stat', 'unit_ref': 'attacker', 'stat': 'attack'},
        '', '', '', source, coverage_status='executable')
    bindings = {
        'by_key': {('action', 1, 0): binding, ('action', 1, 2): replace(binding, param_index=2)},
        'by_task': {},
    }
    assert _target_profiles_for_damage_task(profiles, task, effect, bindings) == (profile,)
    expression = _binding_param_multiplier_expr(binding, effect)
    assert expression['kind'] == 'program'
    assert any(instruction.get('hash') == 8 for instruction in expression['instructions'])
    bindings['by_key']['action', 1, 2] = replace(binding, param_index=2,
                                      scaling_basis_expr={'kind': 'unit_stat', 'unit_ref': 'attacker', 'stat': 'max_hp'})
    assert _target_profiles_for_damage_task(profiles, task, effect, bindings) == (None,)


def test_dot_parameters_stay_with_the_current_status_instance():
    from hsr.simulator_v8_clean_core.rules.ir import StatusDamageEmissionIR
    from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_dynamic_hash, numeric_fixed
    from hsr.simulator_v8_clean_core.systems.dot_formula import DotFormula, DotFormulaInput
    from hsr.simulator_v8_clean_core.systems.dynamic_values import upsert_dynamic_value

    store = None
    for instance, owner, value in (("current", "target", 0.4), ("sibling", "caster", 0.9)):
        store = upsert_dynamic_value(store, scope="status", owner_id=owner, value=value,
                                     value_name="ratio", hash_key=42, status_instance_id=instance)
    state = replace(_state(), global_flags={"dynamic_value_store": store})
    state = replace(state, units={**state.units, "caster": replace(state.units["caster"], attack=100.0)})
    detail = {"instance_id": "current", "status_id": "synthetic:dot", "owner_id": "target",
              "caster_id": "caster", "dynamic_values": {"__by_hash": {"42": 0.4}}}
    emission = StatusDamageEmissionIR(
        "synthetic:dot", "synthetic:callback", "synthetic:task", "synthetic:dot", "OnPhase1", "DOT",
        "dot", "Thunder", {"kind": "dot_attack_property", "damage_value": numeric_fixed(0),
                            "damage_percentage": numeric_dynamic_hash(42),
                            "damage_percentage_basis": {"kind": "unit_stat", "unit_ref": "attacker", "stat": "attack"}},
        IRSource("synthetic:dot", "test", "dot"), "executable",
    )
    formula = DotFormula()
    result = formula.calculate(DotFormulaInput(state, "caster", "target", detail, emission))
    assert result.ok and result.final_damage == 40.0, result.to_json()
    ledger = result.dot_ledger
    assert sorted(ledger["applied_term_indices"] + ledger["skipped_term_indices"]) == list(range(len(ledger["terms"])))
    for index in ledger["applied_term_indices"]:
        term = ledger["terms"][index]
        assert result.numeric_evaluations[term["numeric_evaluation_key"]]["ok"]
        assert "numeric_evaluation" not in term and "basis_result" not in term
        if "basis_result_key" in term:
            assert result.numeric_evaluations[term["basis_result_key"]]["ok"]
    missing = formula.calculate(DotFormulaInput(state, "caster", "target", {**detail, "dynamic_values": {}}, emission))
    assert not missing.ok and "42" in missing.blocked_reason


@pytest.mark.parametrize("invalid_second", [False, True])
def test_modifier_lifetime_extends_matching_instances_or_discards_every_change(invalid_second):
    from hsr.simulator_v8_clean_core.systems.status import StatusSystem

    raw = {"$type": "RPG.GameCore.SetModifierValueByBehaviorFlag", "TargetType": {"Alias": "ParamEntity"},
           "ModifierBehaviorFlags": ["synthetic:dot"], "ModifyFunction": "Add", "ValueType": "LifeTime",
           "Value": {"Value": 2}}
    payload = _effect_payload(raw, "SetModifierValueByBehaviorFlag", "")
    payload["standard"].update(target_expression_id="synthetic:target", target_expression_coverage_status="executable")
    effect = EffectIR("synthetic:lifetime", "SetModifierValueByBehaviorFlag", payload,
                      IRSource("synthetic:lifetime", "test", "extension"), "executable")
    source = IRSource("synthetic:target", "TargetAlias", "ParamEntity", {"json_path": "$.TargetType"})
    node = _target_expression_execution_node({"$type": "RPG.GameCore.TargetAlias", "Alias": "ParamEntity"}, source)
    expression = TargetExpressionIR("synthetic:target", node.expression_kind, "ParamEntity", source,
                                    node=node, coverage_status="executable")
    alias_path = "Config/GlobalConfig/TargetAliasConfig.json"
    alias_raw = json.loads((Path(__file__).resolve().parents[4] / "turnbasedgamedata-main" / alias_path).read_text())["AliasDict"]["ParamEntity"]
    alias_source = IRSource(alias_path, alias_raw["$type"], "ParamEntity", {
        "json_path": "$.AliasDict.ParamEntity", "source_raw_id": "ParamEntity",
    })
    alias_node = _target_expression_execution_node(alias_raw, alias_source)
    alias = TargetExpressionIR("synthetic:param-definition", alias_node.expression_kind, "ParamEntity", alias_source,
                               node=alias_node, coverage_status="executable")
    rules = RuleBook(CanonicalIR(version="synthetic:lifetime", target_expressions=(expression, alias)))
    details = [dict(instance_id=f"synthetic:{i}", status_id=f"synthetic:status:{i}",
                    modifier_name=f"synthetic:modifier:{i}", owner_id="target", caster_id="caster",
                    source_id=f"synthetic:source:{i}",
                    behavior_flags=[flag], remaining_duration=duration, duration=3,
                    lifecycle_state="active", duration_admission={"admission_status": "executable"})
               for i, flag, duration in ((0, "synthetic:dot", 1), (1, "synthetic:dot", 2), (2, "synthetic:other", 3))]
    if invalid_second:
        details[1]["remaining_duration"] = None
    state = _state()
    state = replace(state, units={
        "caster": replace(state.units["caster"], statuses=(details[0]["status_id"],), flags={
            "status_details": [{**details[0], "instance_id": "synthetic:first-target", "owner_id": "caster"}]}),
        "target": replace(state.units["target"], statuses=tuple(detail["status_id"] for detail in details),
                          flags={"status_details": details}),
    })
    before = state.snapshot().to_json()
    result = EffectRegistry(StatusSystem(rules)).execute(effect, EffectExecutionContext(
        state, "caster", "synthetic:lifetime", param_entity_id="target",
        target_resolution=TargetResolution(selected=("caster", "target")),
    ))
    assert state.snapshot().to_json() == before
    if invalid_second:
        assert result.unsupported and not result.mutations
    else:
        after = _commit_and_replay(state, result)
        assert [d["remaining_duration"] for d in after.units["target"].flags["status_details"]] == [3, 4, 3]
        assert [d["duration"] for d in after.units["target"].flags["status_details"]] == [3, 3, 3]
        assert after.units["caster"].flags["status_details"][0]["remaining_duration"] == 3
        assert result.records[0]["mutation_id"] == result.mutations[0].stable_id()
    for changed in ({"ValueType": "Layer"}, {"ModifyFunction": "Set"}, {"TaskList": []},
                    {"ModifierBehaviorFlags": ["synthetic:dot", "synthetic:other"]}):
        assert _effect_coverage_status(effect.opcode, _effect_payload({**raw, **changed}, effect.opcode, "")) == "blocked"


@pytest.mark.parametrize("hp,expected", [(100.0, 83.95), (6.27, 1.0), (1.0, 1.0)])
def test_real_arlan_hp_cost_preserves_one_hp_without_rounding(hp, expected):
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    source_path = "Config/ConfigAbility/Avatar/Avatar_Arlan_00_Ability.json"
    raw = json.loads((root / source_path).read_text())
    task = raw["AbilityList"][3]["OnStart"][1]
    assert task["$type"] == "RPG.GameCore.LoseHPByRatio"
    payload = _effect_payload(task, "LoseHPByRatio", "")
    effect = EffectIR("test:arlan-hp-cost", "LoseHPByRatio", payload,
                      IRSource(source_path, "AbilityTask", "Avatar_Arlan_Skill02_Phase02"),
                      _effect_coverage_status("LoseHPByRatio", payload))
    state = BattleState(units={"caster": UnitState("caster", "ally", "avatar:1008", hp=hp, max_hp=107.0)})
    before = state.snapshot().to_json()
    result = EffectRegistry().execute(effect, EffectExecutionContext(
        state, "caster", effect.effect_id,
        binding_sources=({"by_hash": {"-1784868094": 0.15}},),
    ))
    assert not result.unsupported, result.records
    after = MutationReducer().apply_all(state, result.mutations)
    assert after.units["caster"].hp == pytest.approx(expected)
    assert after.units["caster"].lifecycle_status == "active"
    assert state.snapshot().to_json() == before
    assert not result.rng_events
    assert sum(event.event_type == "hp.change" for event in result.events) == (hp > 1)


def test_hp_cost_missing_floor_binding_cannot_commit_partial_loss():
    effect = _effect("LoseHPByRatio", RatioType="MaxHP", Ratio=0.15,
                     Floor={"IsDynamic": True, "PostfixExpr": {
                         "OpCodes": "AQAR", "FixedValues": [], "DynamicHashes": [123],
                     }})
    _, result = _execute(effect)
    assert result.unsupported
    assert not result.mutations and not result.events and not result.rng_events


def test_pre_heal_producer_separates_dispatched_trigger_from_new_hp_events():
    from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem

    effect = _effect("HealHP", ModifyValue={"Value": 100})
    state = _state()
    callbacks = StatusCallbackSystem(RuleBook(CanonicalIR(version="pre_heal_dispatch", effects=(effect,))))
    result = callbacks.effect_registry.execute(effect, EffectExecutionContext(
        state, "caster", "synthetic:heal", owner_id="caster", param_entity_id="target",
    ))
    assert not result.unsupported
    before = next(event for event in result.events if event.event_type == "heal.before")
    assert result.dispatched_event_ids == frozenset({before.event_id})
    pending = [event for event in result.events if event.event_type in {"hp.change", "heal.after"}]
    assert len(pending) == 1 and pending[0].event_type == "heal.after"
    assert all(event.to_json()["event_id"] not in result.dispatched_event_ids for event in pending)


@pytest.mark.parametrize("formula,base", [
    ("HealByHealerMaxHP", 5000), ("HealByTargetMaxHP", 2000), ("HealByTargetLostHP", 200),
])
def test_ratio_heal_adds_flat_before_bonus_and_audits_overheal(formula, base):
    effect = _effect("HealHP", FormulaType=formula, HealPercentage={"Value": 0.1}, ModifyValue={"Value": 100})
    state, result = _execute(effect)
    after = _commit_and_replay(state, result)
    offered = (base * 0.1 + 100) * 1.3
    realized = min(200, offered)
    details = result.mutations[0].metadata["formula_details"]
    assert details["base_amount"] == pytest.approx(base * 0.1 + 100)
    assert details["offered_healing"] == pytest.approx(offered)
    assert details["realized_healing"] == pytest.approx(realized)
    assert details["overheal"] == pytest.approx(offered - realized)
    assert after.units["target"].hp == pytest.approx(1800 + realized)
    assert after.units["caster"] == state.units["caster"]


def test_source_backed_recipient_heal_penalty_uses_one_additive_factor(monkeypatch):
    from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem
    from hsr.simulator_v8_clean_core.systems.summon_runtime import empty_summon_runtime

    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    source_path = "Config/ConfigAbility/Monster/Monster_W3_Sam_00_Ability.json"
    document = json.loads((root / source_path).read_text())
    modifier_name = "Monster_W3_Sam_00_BurningBP"
    callbacks = document["GlobalModifiers"][modifier_name]["_CallbackList"]
    callback_index, raw_callback = next(
        (index, item) for index, item in enumerate(callbacks)
        if item["Event"] == "OnBeforeBeingHeal"
    )
    raw_predicate_task = raw_callback["CallbackConfig"][0]
    raw_condition = raw_predicate_task["Predicate"]
    raw_modifier = raw_predicate_task["SuccessTaskList"][0]
    assert raw_modifier["$type"] == "RPG.GameCore.ModifyHealData"
    assert set(raw_modifier) == {"$type", "Target_HealTakenRatio"}
    admission, reason = _equipment_task_admission(
        "OnBeforeBeingHeal", "ModifyHealData", raw_modifier, modifier_name=modifier_name,
    )
    assert admission == "executable", reason

    alias_path = "Config/GlobalConfig/TargetAliasConfig.json"
    aliases = json.loads((root / alias_path).read_text())["AliasDict"]
    target_expressions = []
    for alias in ("ParamEntity", "ParamEntityActualOwner", "ModifierOwnerEntity"):
        raw_alias = aliases[alias]
        alias_source = IRSource(alias_path, raw_alias["$type"], alias, {
            "json_path": f"$.AliasDict.{alias}", "source_raw_id": alias,
        })
        node = _target_expression_execution_node(raw_alias, alias_source)
        target_expressions.append(TargetExpressionIR(
            f"test:alias:{alias}", node.expression_kind, alias, alias_source,
            node=node, coverage_status="executable",
        ))

    path = f"$.GlobalModifiers.{modifier_name}._CallbackList[{callback_index}].CallbackConfig[0]"
    callback_source = IRSource(source_path, "OnBeforeBeingHeal", modifier_name, {"json_path": path})
    condition_source = IRSource(source_path, "ByCompareTarget", modifier_name, {
        "json_path": f"{path}.Predicate",
    })
    condition = ConditionIR(
        "test:sam:heal-owner", "ByCompareTarget",
        _typed_condition_payload(
            "ByCompareTarget", {key: value for key, value in raw_condition.items() if key != "$type"},
            source=condition_source,
        ), condition_source, coverage_status="executable",
        expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA,
    )
    assert _condition_payload_executable("ByCompareTarget", condition.payload)
    predicate_id, modifier_id = "test:sam:predicate", "test:sam:modifier"
    callback = StatusCallbackIR(
        "test:sam:being-healed", modifier_name, "OnBeforeBeingHeal",
        (predicate_id,), callback_source, (callback_index, 0),
        coverage_status="executable", source_mode="mainline_monster_ability",
        admission_status="executable",
    )
    predicate = StatusCallbackTaskIR(
        predicate_id, callback.callback_id, modifier_name, callback.event, 0,
        "CallbackConfig[0]", "root", "PredicateTaskList", callback_source,
        condition_id=condition.condition_id, success_task_ids=(modifier_id,),
        child_task_ids=(modifier_id,), coverage_status="executable",
    )
    modifier_source = IRSource(source_path, "ModifyHealData", modifier_name, {
        "json_path": f"{path}.SuccessTaskList[0]",
    })
    modifier = StatusCallbackTaskIR(
        modifier_id, callback.callback_id, modifier_name, callback.event, 0,
        "CallbackConfig[0].SuccessTaskList[0]", "success", "ModifyHealData", modifier_source,
        parent_task_id=predicate_id, coverage_status="executable",
        task_payload=_status_callback_runtime_payload(raw_modifier),
    )
    effect = _effect("HealHP", ModifyValue={"Value": 1000})
    rules = RuleBook(CanonicalIR(
        "test:sam:heal-penalty", effects=(effect,), conditions=(condition,),
        target_expressions=tuple(target_expressions), status_callbacks=(callback,),
        status_callback_tasks=(predicate, modifier),
    ))
    state = _state()
    state = replace(state, global_flags={"summon_runtime": empty_summon_runtime()}, units={
        **state.units,
        "caster": replace(state.units["caster"], resources={"outgoing_healing_ratio": 0.5}),
        "target": replace(state.units["target"], hp=1000.0, resources={}, flags={
            "status_details": [{
                "modifier_name": modifier_name, "instance_id": "test:sam:burning",
                "owner_id": "target", "caster_id": "target",
                "dynamic_values": {"__by_hash": {"1260053363": 0.9}},
                "source_trace": {"source_path": source_path, "raw_id": modifier_name},
            }],
        }),
    })
    system = StatusCallbackSystem(rules)
    original_execute = system.execute

    def without_audit_heal_records(*args, **kwargs):
        callback_result = original_execute(*args, **kwargs)
        return replace(callback_result, records=tuple(
            record for record in callback_result.records if record.get("record_type") != "heal_modifier"
        ))

    monkeypatch.setattr(system, "execute", without_audit_heal_records)
    result = system.effect_registry.execute(
        effect, EffectExecutionContext(
            state, "caster", "test:heal", owner_id="caster", param_entity_id="target",
        ),
    )
    assert not result.unsupported, result.records
    assert len([event for event in result.events if event.event_type == "heal.before"]) == 1
    after = _commit_and_replay(state, result)
    details = result.mutations[-1].metadata["formula_details"]
    assert details["healing_multiplier"] == pytest.approx(0.6)
    assert details["offered_healing"] == pytest.approx(600)
    assert details["realized_healing"] == pytest.approx(600)
    assert after.units["target"].hp == pytest.approx(1600)
    assert not any(record.get("record_type") == "heal_modifier" for record in result.records)


def test_healing_uses_typed_selection_and_ignores_payload_heal_ratio():
    effect = _effect("HealHP", TargetType={"Alias": "AbilityTargetEntity"}, ModifyValue={"Value": 100})
    resolution = TargetResolution(selected=("target",), primary="target")
    state, result = _execute(effect, target_resolution=resolution,
                             event_payload={"heal_modifier_ratio": 1000})
    assert _commit_and_replay(state, result).units["target"].hp == pytest.approx(1930)
    for unresolved in (None, TargetResolution(selected=("caster", "target"), primary="caster")):
        _, result = _execute(effect, target_resolution=unresolved)
        assert result.unsupported and not result.mutations


@pytest.mark.parametrize("formula,base", [
    ("ShieldByCasterDefence", 2000), ("ShieldByCasterMaxHP", 5000), ("ShieldByTargetMaxHP", 2000),
])
def test_ratio_shield_adds_flat_before_creator_bonus(formula, base):
    effect = _effect("InitShield", FormulaType=formula,
                     ShieldPercentage={"Value": 0.608}, ShieldValue={"Value": 845.5})
    state, result = _execute(effect)
    after = _commit_and_replay(state, result)
    details = result.mutations[0].metadata["formula_details"]
    assert details["base_amount"] == pytest.approx(base * 0.608 + 845.5)
    assert details["shield_multiplier"] == 1.25
    assert result.mutations[0].metadata["amount"] == pytest.approx((base * 0.608 + 845.5) * 1.25)
    assert after.units["target"].shield_instances


def test_omitted_heal_formula_accepts_only_flat_and_internal_heal_stays_valid():
    effect = _effect("HealHP", ModifyValue={"Value": 100})
    state, result = _execute(effect)
    assert _commit_and_replay(state, result).units["target"].hp == pytest.approx(1930)
    assert effect.payload["standard"]["formula_type_source"] == "reconciled_flat_only_heal_model"
    internal = EffectIR("internal:heal", "Heal", {"standard": {
        "kind": "heal", "target_alias": "ParamEntity", "amount": {"kind": "fixed", "value": 100},
    }}, IRSource("synthetic:internal", "Heal", "test"), "executable")
    state, result = _execute(internal)
    assert _commit_and_replay(state, result).units["target"].hp == pytest.approx(1930)


@pytest.mark.parametrize("fields", [
    {"HealPercentage": {"Value": 0.1}},
    {"HealPercentage": {"Value": 0.1}, "ModifyValue": {"Value": 100}},
    {"FormulaType": None, "ModifyValue": {"Value": 100}},
    {"FormulaType": "HealByHealerMaxHP", "HealPercentage": {"Value": 0.1}, "ModifyValue": {}},
])
def test_ambiguous_or_malformed_heal_blocks_without_mutation_or_rng(fields):
    state, result = _execute(_effect("HealHP", **fields))
    assert result.unsupported
    assert not result.mutations
    assert not result.rng_events
    assert MutationReducer().replay_snapshot(state, (), state.snapshot().to_json()).ok


@pytest.mark.parametrize("opcode,ratio_key,flat_key,formula", [
    ("HealHP", "HealPercentage", "ModifyValue", "HealByHealerMaxHP"),
    ("InitShield", "ShieldPercentage", "ShieldValue", "ShieldByCasterDefence"),
])
def test_declared_flat_missing_dynamic_binding_does_not_silently_drop(opcode, ratio_key, flat_key, formula):
    dynamic = {"IsDynamic": True, "PostfixExpr": {"OpCodes": "AQAR", "FixedValues": [], "DynamicHashes": [987654]}}
    effect = _effect(opcode, FormulaType=formula, **{ratio_key: {"Value": 0.1}, flat_key: dynamic})
    _, result = _execute(effect)
    assert result.unsupported
    assert not result.mutations and not result.rng_events
    assert "flat_addition_evaluation_failed" in str(result.records)


@pytest.mark.parametrize("field,value,expected,err", [
    ("AddValue", 10, 35, 1.5), ("FixedAddValue", 10, 30, 1),
    ("AddMaxSPRatio", 0.1, 35, 1.5), ("FixedAddMaxSPRatio", 0.1, 30, 1),
    ("SetValue", 10, 10, 1), ("FixedSetValue", 10, 10, 1),
    ("SetMaxSPRatio", 0.1, 10, 1), ("FixedSetMaxSPRatio", 0.1, 10, 1),
    ("AddValue", -10, 10, 1),
])
def test_energy_add_set_and_fixed_grants_use_distinct_err_policy(field, value, expected, err):
    state, result = _execute(_effect("ModifySPNew", **{field: {"Value": value}}))
    after = _commit_and_replay(state, result)
    assert after.units["target"].energy == pytest.approx(expected)
    assert result.mutations[0].metadata["formula_details"]["energy_regeneration_multiplier"] == err
    assert after.units["caster"] == state.units["caster"]


@pytest.mark.parametrize("fields", [
    {"AddValue": {"Value": 10}, "FixedAddValue": {"Value": 10}},
    {"SetValue": {"Value": 10}, "AddMaxSPRatio": {"Value": 0.1}},
    {"AddValue": {"Value": 10}, "FixedAddRatio": {"Value": 0.1}},
])
def test_mixed_energy_formula_fields_block_instead_of_dropping_operands(fields):
    _, result = _execute(_effect("ModifySPNew", **fields))
    assert result.unsupported and not result.mutations and not result.rng_events
    assert "resource_combined_formula_not_supported" in str(result.records)


def test_real_healing_skill_energy_request_is_one_action_base_grant():
    from hsr.simulator_v8_clean_core.core.executor import _action_resource_plan_with_value_resolution
    from hsr.simulator_v8_clean_core.rules.value_binding import ValueResolver
    from hsr.simulator_v8_clean_core.systems.action_preflight import action_resource_plan
    from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering

    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    lowerer = TBGDLowering(root)
    definition = next(d for d in lowerer._lower_action_definitions(
        action_ids=frozenset({"avatar_skill:110502"}),
    ) if d.level == 1)
    raw = json.loads((root / "Config/ConfigAbility/Avatar/Avatar_Natasha_00_Ability.json").read_text())
    phase = next(p for p in raw["AbilityList"] if p["Name"] == "Avatar_Natasha_00_Skill02_Phase02")
    request = next(t for t in phase["OnStart"] if t["$type"] == "RPG.GameCore.ModifySPNew")
    payload = _effect_payload(request, "ModifySPNew", "")
    source = IRSource("Config/ConfigAbility/Avatar/Avatar_Natasha_00_Ability.json", "AbilityTask", phase["Name"])
    effect = EffectIR("test:healing-energy", "ModifySPNew", payload, source, _effect_coverage_status("ModifySPNew", payload))
    task = AbilityTaskIR("test:energy-task", "test:phase", definition.action_id, 1,
                         phase["Name"], "OnStart", 0, "OnStart[0]", "main", "ModifySPNew",
                         effect_id=effect.effect_id, source=source, coverage_status="executable")
    rules = RuleBook(CanonicalIR(version="test:healing-energy", action_definitions=(definition,),
                                 effects=(effect,), ability_tasks=(task,)))
    assert definition.sp_base == 30 and definition.bp_need == 1
    assert action_resource_plan(definition, source="test", rules=rules).energy_gain == 0
    plan, blocked = _action_resource_plan_with_value_resolution(
        ValueResolver(rules), ActionCommand("caster", definition.action_id, 1), definition,
        metadata={}, queue_resource_policy={},
    )
    assert not blocked and plan.energy_gain == 0
    state, result = _execute(effect, action_definition=definition)
    after = _commit_and_replay(state, result)
    assert after.units["caster"].energy == 55  # 25 + 30; MaxEnergy=120 is not the base.
    state = replace(state, units={**state.units, "caster": replace(
        state.units["caster"], resources={"energy_regeneration_rate": 0.5},
    )})
    _, result = _execute(effect, state, action_definition=definition)
    assert _commit_and_replay(state, result).units["caster"].energy == 70
    _, missing = _execute(effect, state)
    assert missing.unsupported and not missing.mutations
    assert "resource_action_context_missing" in str(missing.records)


def test_non_energy_ratio_is_not_given_skill_energy_semantics():
    _, result = _execute(_effect("ModifyTeamBoostPoint", AddRatio={"Value": 1}))
    assert result.unsupported and not result.mutations
    assert "resource_formula_type_not_supported:AddRatio" in str(result.records)


def test_real_march_shield_raw_lowering_to_mutation_and_replay():
    source_path = "Config/ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json"
    root = Path(__file__).resolve().parents[4]
    document = json.loads((root / "turnbasedgamedata-main" / source_path).read_text())

    def occurrences(value, path="$."):
        if isinstance(value, dict):
            if value.get("$type") == "RPG.GameCore.InitShield" and value.get("FormulaType") == "ShieldByCasterDefence":
                yield path, value
            for key, item in value.items():
                yield from occurrences(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from occurrences(item, f"{path}[{index}]")

    matches = list(occurrences(document))
    assert len(matches) == 1
    occurrence, raw = matches[0]
    assert _status_callback_task_admission('OnStack', 'InitShield', raw) == ('executable', '')
    for invalid in ({**raw, 'FutureFlag': True}, {**raw, 'DisplayData': {'Unknown': 1}},
                    {**raw, 'DisplayData': {'DitherRangeX': float('nan')}},
                    {**raw, 'TargetType': {**raw['TargetType'], 'Unknown': 1}}):
        assert _status_callback_task_admission('OnStack', 'InitShield', invalid)[0] == 'blocked'
    payload = _effect_payload(raw, "InitShield", "")
    effect = EffectIR("raw:march:shield", "InitShield", payload,
                      IRSource(source_path, "InitShield", occurrence,
                               evidence={"test_binding_basis": "PR8 confirmed coefficients; not full character admission"}),
                      _effect_coverage_status("InitShield", payload))
    state, result = _execute(effect, dynamic_values={"2126266902": 845.5, "-2062890509": 0.608})
    _commit_and_replay(state, result)
    mutation = result.mutations[0]
    assert mutation.metadata["amount"] == pytest.approx((2000 * 0.608 + 845.5) * 1.25)
    assert mutation.metadata["effect_source"]["source_path"] == source_path
    assert mutation.metadata["effect_source"]["raw_id"] == occurrence


def test_real_shield_callback_tasks_and_lifecycle_events_lower_without_bypassing_gaps():
    from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering

    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    source = root / 'Config/ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json'
    lowered = TBGDLowering(root)._lower_ability_file(source, {}, ability_file_order=0)
    tasks = lowered.status_callback_tasks
    shields = [task for task in tasks if task.opcode in {'InitShield', 'RemoveShield'}]
    assert len(shields) == 4
    assert all(task.coverage_status == 'executable' and task.effect_id for task in shields)
    for event, opcode in [('OnPhase2', 'AddModifier'), ('OnListenCharacterCreate', 'AddModifier'),
                          ('OnBeforeBeingAttacked', 'AddModifier'), ('OnListenModifierAdd', 'RemoveSelfModifier')]:
        matching = [task for task in tasks if task.event == event and task.opcode == opcode]
        assert matching and all(task.coverage_status == 'executable' for task in matching), (event, opcode)
        owners = {task.callback_id for task in matching}
        assert all(callback.coverage_status == 'executable' for callback in lowered.status_callbacks
                   if callback.callback_id in owners)
    effects = {effect.effect_id: effect for effect in lowered.effects}
    cleanup = [task for task in tasks if task.event == 'OnBeforeDying' and task.opcode == 'RemoveModifier']
    assert cleanup and all(task.coverage_status == 'executable' for task in cleanup), [
        task.blocked_reason for task in cleanup]
    assert all(effects[task.effect_id].payload['standard']['only_remove_caster_added'] is True
               for task in cleanup)
    missing_bar = [task for task in tasks if task.opcode == 'SetEnergyBarState'
                   and effects[task.effect_id].payload['standard'].get('bar_type') is None]
    assert len(missing_bar) == 4 and all(task.coverage_status == 'executable' for task in missing_bar)
    for task in missing_bar:
        effect = effects[task.effect_id]
        original = _state()
        bar = {'state': 'Normal', 'current_count': 2.0, 'max_count': 3.0}
        target = replace(original.units['target'], flags={'mechanism_bars': {'7': bar}})
        # An unrelated caster bar must not participate in owner selection.
        caster = replace(original.units['caster'], flags={'mechanism_bars': {'9': bar}})
        state = replace(original, units={'caster': caster, 'target': target})
        _, result = _execute(effect, state=state)
        if effect.payload['standard']['state'] == bar['state']:
            assert not result.unsupported and not result.mutations and not result.rng_events
            after = state
        else:
            after = _commit_and_replay(state, result)
        assert after.units['target'].flags['mechanism_bars'] == {
            '7': {**bar, 'state': effect.payload['standard']['state']},
        }
        assert after.units['caster'] == caster
        for bars, reason in (({}, 'mechanism_bar_identity_missing'),
                             ({'7': bar, '8': bar}, 'mechanism_bar_identity_ambiguous'),
                             ({'7': {}}, 'mechanism_bar_state_invalid')):
            unavailable = replace(state, units={**state.units, 'target': replace(
                target, flags={'mechanism_bars': bars},
            )})
            _, rejected = _execute(effect, state=unavailable)
            assert rejected.unsupported and reason in str(rejected.records)
            assert not rejected.mutations and not rejected.events and not rejected.rng_events
    resilience = [task for task in tasks if task.opcode == 'SetResilience']
    assert resilience and all(task.coverage_status == 'executable' for task in resilience)


def test_real_shield_resilience_follows_create_stack_destroy_order():
    from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem
    from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering

    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    lowered = TBGDLowering(root)._lower_ability_file(
        root / 'Config/ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json', {}, ability_file_order=0,
    )
    rules = RuleBook(CanonicalIR('real-shield-lifecycle',
        effects=tuple(lowered.effects), conditions=tuple(lowered.conditions),
        status_callbacks=tuple(lowered.status_callbacks),
        status_callback_tasks=tuple(lowered.status_callback_tasks),
        target_expressions=tuple(lowered.target_expressions),
    ))
    system = StatusCallbackSystem(rules)
    modifier = 'MAvatar_March7th_00_BPSkill_Shield'
    callbacks = {event: rules.status_callbacks_for_modifier_event(modifier, event)[0]
                 for event in ('OnCreate', 'OnStack', 'OnDestroy')}
    tasks = {event: rules.status_callback_tasks_for_callback(callback.callback_id)
             for event, callback in callbacks.items()}
    create = next(task for task in tasks['OnCreate'] if task.opcode == 'SetResilience')
    reset = next(task for task in tasks['OnDestroy'] if task.opcode == 'SetResilience')
    initialize = next(task for task in tasks['OnStack'] if task.opcode == 'InitShield')
    remove = next(task for task in tasks['OnDestroy'] if task.opcode == 'RemoveShield')
    detail = {'instance_id': 'shield:1', 'status_id': f'modifier:{modifier}',
              'modifier_name': modifier, 'owner_id': 'target', 'caster_id': 'caster',
              'source_id': 'shield-application', 'behavior_flags': ['Shield'],
              'trigger_ids_by_event': {event: [callback.callback_id] for event, callback in callbacks.items()}}
    original = _state()
    state = replace(original, units={**original.units, 'target': replace(
        original.units['target'], flags={'status_details': [detail]},
    )})
    created = system._execute_shield_resilience_sync_task(state, callbacks['OnCreate'], create, detail)
    assert created.ok and not created.mutations and created.after_state == state, created.errors
    assert created.records[0]['payload']['deferred_init_task_ids'] == [initialize.task_id]
    assert not state.units['target'].shield_instances

    payload = {'modifier_name': modifier, 'status_instance_id': 'shield:1'}
    _, initialized = _execute(rules.effect(initialize.effect_id), state=state, event_payload=payload,
                              dynamic_values={'2126266902': 845.5, '-2062890509': 0.608})
    shielded = _commit_and_replay(state, initialized)
    assert len(shielded.units['target'].shield_instances) == 1
    premature_reset = system._execute_shield_resilience_sync_task(shielded, callbacks['OnDestroy'], reset, detail)
    assert not premature_reset.ok and not premature_reset.mutations
    _, removed = _execute(rules.effect(remove.effect_id), state=shielded, event_payload=payload)
    cleared = _commit_and_replay(shielded, removed)
    destroyed = system._execute_shield_resilience_sync_task(cleared, callbacks['OnDestroy'], reset, detail)
    assert destroyed.ok and not destroyed.mutations and destroyed.after_state == cleared
    for invalid in ({**detail, 'behavior_flags': []},
                    {**detail, 'trigger_ids_by_event': {'OnStack': []}}):
        invalid_state = replace(state, units={**state.units, 'target': replace(
            state.units['target'], flags={'status_details': [invalid]},
        )})
        rejected = system._execute_shield_resilience_sync_task(invalid_state, callbacks['OnCreate'], create, invalid)
        assert not rejected.ok and not rejected.mutations and rejected.after_state == invalid_state
    raw = {'$type': 'RPG.GameCore.SetResilience'}
    assert _status_callback_task_admission('OnCreate', 'SetResilience', {**raw, 'Unknown': True})[0] == 'blocked'
    assert _status_callback_task_admission('OnDestroy', 'SetResilience', raw)[0] == 'blocked'


def test_stack_shield_lowering_preserves_owner_and_capacity():
    raw = {"$type": "RPG.GameCore.StackShield", "StackValue": {"Value": 100}, "MaxStack": {"Value": 150}}
    payload = _effect_payload(raw, "StackShield", "synthetic:shield-owner")
    assert payload["standard"]["target_alias"] == "ModifierOwnerEntity"
    effect = EffectIR("synthetic:stack", "StackShield", payload,
                      IRSource("synthetic:stack", "StackShield", "test"),
                      _effect_coverage_status("StackShield", payload))
    context = {"event_payload": {"modifier_name": "synthetic:shield-owner", "status_instance_id": "synthetic:status"}}
    state, result = _execute(effect, **context)
    assert result.unsupported and not result.mutations
    assert "shield_bonus_stack_cap_policy_unconfirmed" in str(result.records)
    caster = state.units["caster"]
    state = replace(state, units={**state.units, "caster": replace(
        caster, resources={**caster.resources, "shield_added_ratio": 0.0},
    )})
    _, result = _execute(effect, state, **context)
    after = _commit_and_replay(state, result)
    assert result.mutations[0].metadata["formula_details"]["max_capacity"] == pytest.approx(150.0)
    _, repeated = _execute(effect, after, **context)
    final = _commit_and_replay(after, repeated)
    assert len(final.units["target"].shield_instances) == 1
    shield = final.units["target"].shield_instances[0]
    assert shield["remaining"] == pytest.approx(150.0)


def test_stack_shield_dynamic_cap_missing_binding_blocks_without_mutation():
    cap = {"IsDynamic": True, "PostfixExpr": {"OpCodes": "AQAR", "FixedValues": [], "DynamicHashes": [777]}}
    _, result = _execute(_effect("StackShield", StackValue={"Value": 100}, MaxStack=cap))
    assert result.unsupported and not result.mutations and not result.rng_events
    assert "shield_max_capacity_evaluation_failed" in str(result.records)


def test_formal_executor_rejects_unadmitted_action_without_any_state_change():
    # This proves the public action gate, not an admitted action's sustain callback.
    effect = _effect("HealHP", HealPercentage={"Value": 0.1})
    rules = RuleBook(CanonicalIR(version="synthetic:sustain-gate", effects=(effect,)))
    state = replace(_state(), queues={"pending": ({"synthetic": "must-remain"},)},
                    rng_state="synthetic:unchanged", skill_points=2)
    before = state.snapshot().to_json()
    command = ActionCommand("caster", "synthetic:unadmitted-action", 1, ("target",))
    after, transition = CombatExecutor(rules).execute(command, state)
    assert transition.outcome.category == "blocked"
    assert transition.outcome.reason_codes
    assert after.snapshot().to_json() == before == transition.after.to_json()
    assert after.skill_points == 2 and after.queues == state.queues and after.rng_state == state.rng_state
    assert not transition.transaction.mutations and not transition.rng_events
    assert MutationReducer().replay_snapshot(state, (), transition.after.to_json()).ok


@pytest.mark.parametrize("missing_flat_binding", [False, True])
def test_eventful_transaction_commits_complete_producer_or_discards_every_plan(missing_flat_binding):
    """Transaction API coverage, not proof of an admitted ActionCommand callback graph."""
    flat = {"IsDynamic": True, "PostfixExpr": {"OpCodes": "AQAR", "FixedValues": [], "DynamicHashes": [777]}}
    effect = _effect("HealHP", FormulaType="HealByHealerMaxHP", HealPercentage={"Value": 0.01}, ModifyValue=flat)
    rules = RuleBook(CanonicalIR(version="synthetic:eventful-sustain", effects=(effect,)))
    state = replace(_state(), queues={"pending": ("existing",)}, rng_state="synthetic:rng-before")
    before = state.snapshot().to_json()
    produced = EffectRegistry().execute(effect, EffectExecutionContext(
        state, "caster", "synthetic:heal-operation", param_entity_id="target",
        dynamic_values={} if missing_flat_binding else {"777": 10},
    ))
    assert bool(produced.unsupported) is missing_flat_binding
    planned = (
        Mutation("set", ("skill_points",), 3, 2, "synthetic planned SP cost", "synthetic:transaction"),
        Mutation("set", ("queues", "pending"), ["existing"], ["planned"], "synthetic queue plan", "synthetic:transaction"),
        Mutation("set", ("rng_state",), state.rng_state, "synthetic:rng-after", "synthetic RNG plan", "synthetic:transaction"),
        *produced.mutations,
    )
    planned_rng = RNGEvent("synthetic", "synthetic:transaction", 0.25,
                           event_id="synthetic:rng", before_state=state.rng_state, after_state="synthetic:rng-after")
    # The positive arm proves these exact auxiliary plans are valid and committable.
    assert MutationReducer().apply_all_result(state, planned).ok
    result = CombatExecutor(rules).commit_eventful_transition(
        state, mutations=planned, events=produced.events, records=produced.records,
        rng_events=(planned_rng,), producer_kind="effect", producer_id="caster",
        actor_id="caster",
        producer_ok=not produced.unsupported,
        blocked_reason=produced.unsupported[0] if produced.unsupported else "",
    )
    if missing_flat_binding:
        assert result.errors and not result.mutations and not result.rng_events
        assert result.after_state.snapshot().to_json() == before
        assert result.after_state.skill_points == 3
        assert result.after_state.queues == state.queues
        assert result.after_state.rng_state == state.rng_state
    else:
        assert not result.errors, result.errors
        assert len(result.mutations) == len(planned)
        assert result.rng_events == (planned_rng,)
        assert result.after_state.skill_points == 2
        assert result.after_state.queues["pending"] == ("planned",)
        assert result.after_state.rng_state == "synthetic:rng-after"
        assert result.after_state.units["target"].hp == pytest.approx(1878)
    assert state.snapshot().to_json() == before
    assert MutationReducer().replay_snapshot(
        state, result.mutations, result.after_state.snapshot().to_json(),
    ).ok


def test_eventful_commit_keeps_distinct_producer_sources_for_one_target():
    effect = _effect("HealHP", ModifyValue={"Value": 10})
    state = _state()
    current = state
    mutations, events, records = [], [], []
    for source in ("operation:first", "operation:second"):
        result = EffectRegistry().execute(effect, EffectExecutionContext(
            current, "caster", source, param_entity_id="target",
        ))
        assert not result.unsupported
        mutations.extend(result.mutations)
        events.extend(result.events)
        records.extend(result.records)
        current = MutationReducer().apply_all(current, result.mutations)
    rules = RuleBook(CanonicalIR(version="synthetic:multi-source", effects=(effect,)))
    committed = CombatExecutor(rules).commit_eventful_transition(
        state, mutations=tuple(mutations), events=tuple(events), records=tuple(records),
        producer_kind="effect", producer_id="transaction", actor_id="caster",
    )
    assert not committed.errors, committed.errors
    assert committed.after_state.snapshot().to_json() == current.snapshot().to_json()
    assert {event.source_id for event in committed.events if event.event_type == "heal.after"} == {
        "operation:first", "operation:second",
    }
