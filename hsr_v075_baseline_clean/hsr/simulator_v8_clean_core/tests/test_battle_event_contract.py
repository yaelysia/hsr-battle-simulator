"""Event-container components; no full character battle or catalogue compilation."""
from copy import deepcopy
from dataclasses import replace

import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.rules.engine_rule_registry import build_engine_rule_registry
from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_fixed
from hsr.simulator_v8_clean_core.rules.ir import AbilityPhaseIR, AbilityTaskIR, CanonicalIR, EffectIR, IRSource, TargetExpressionIR
from hsr.simulator_v8_clean_core.tbgd.lowering import _target_expression_execution_node
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.rules.task_graph import (
    TaskGraphIR, TaskGraphNodeIR, TaskGraphDefinitionReferenceIR, TaskGraphQueryResult,
    task_graph_entry_id, task_graph_id, task_graph_node_id,
    task_graph_source_occurrence_id, task_graph_reference_id,
)
from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry
from hsr.simulator_v8_clean_core.systems.status import StatusSystem


def _case(startup_delay=None):
    source = IRSource('fixture:event', 'ComponentEvent', 'create',
                      {'json_path': '$.component', 'content_sha256': 'a' * 64, 'source_opcode': 'SetActionDelay'})
    delay = EffectIR('delay', 'SetActionDelay', {'standard': {
        'operation': 'set_action_value', 'target_alias': 'Caster',
        'value': numeric_fixed(startup_delay or 0),
    }}, source, 'executable')
    phase_id = 'phase:event'
    entry_id = task_graph_entry_id('ability_phase_callback', phase_id, 'OnAdd')
    graph_id = task_graph_id('component', entry_id, 'a' * 64)
    occurrence = task_graph_source_occurrence_id(source, 'SetActionDelay')
    node_id = task_graph_node_id(graph_id, 'task:delay', occurrence)
    reference = TaskGraphDefinitionReferenceIR(task_graph_reference_id(node_id, 'effect', 'delay'),
        node_id, 'effect', 'delay', '', 'resolved', 'task_graph_execution', source)
    node = TaskGraphNodeIR(node_id, graph_id, occurrence, '', 'task:delay', 'SetActionDelay',
        'SetActionDelay', 'leaf', (), (reference,), 'not_applicable', 'not_applicable', '',
        'materialized', ('task_graph_execution',), source)
    graph = TaskGraphIR(graph_id, entry_id, 'ability_phase_callback', phase_id, 'OnAdd',
        (node_id,), (node,), (), 'component', 'a' * 64, source, 'lowered')
    task = AbilityTaskIR('task:delay', phase_id, 'fixture:event:start', 0, 'start', 'OnAdd',
        0, 'OnAdd[0]', 'root', 'SetActionDelay', source, effect_id='delay', coverage_status='executable')
    phase = AbilityPhaseIR(phase_id, '', 'fixture:event', 0, 'start', 0, {}, {}, {}, source,
        coverage_status='executable', task_ids=('task:delay',) if startup_delay is not None else (),
        invocation_role='build_startup' if startup_delay is not None else 'non_gameplay_noop')
    create = EffectIR('create', 'CreateBattleEvent', {'standard': {
        'operation': 'create_battle_event', 'team': 'TeamLight', 'event_id': numeric_fixed(1),
        'dynamic_values': {}, 'definition': {
            'entity_ref': 'battle_event:fixture', 'phase_ids': [phase_id],
            'speed_binding': {'kind': 'fixed', 'value': 100}, 'properties': {'attack': 100},
            'battle_event_kind': 'auto_action', 'actionable': True,
        },
    }}, source, 'executable')

    class Rules(RuleBook):
        def query_formal_task_graph(self, *args):
            return TaskGraphQueryResult('resolved', 'graph', (graph_id,), graph, '')

        def query_task_graph(self, requested):
            assert requested == graph_id
            return TaskGraphQueryResult('resolved', 'graph', (graph_id,), graph, '')

        def query_task_graph_node(self, requested):
            assert requested == node_id
            return TaskGraphQueryResult('resolved', 'node', (node_id,), node, '')

    rules = Rules(CanonicalIR('event-component', effects=(create, delay), ability_phases=(phase,),
        ability_tasks=(task,) if startup_delay is not None else (),
        timeline_rules=build_engine_rule_registry().timeline_rules))
    state = BattleState(units={'owner': UnitState('owner', 'ally', 'fixture:owner', hp=100, max_hp=100)})
    context = EffectExecutionContext(state, 'owner', 'create')
    return rules, create, context


@pytest.mark.parametrize('declaration', [
    {'property_from_target_alias': 'Caster'},
    {'owner_sync_property_types': ['CriticalChance']},
    {'property_overrides': [{'property_type': 'CriticalDamage', 'value_present': False, 'declared_value': None}]},
])
def test_actionable_event_with_unconsumed_property_declaration_is_atomic_blocked(declaration):
    rules, create, context = _case()
    standard = create.payload['standard']
    unresolved = replace(create, payload={'standard': {**standard,
        'definition': {**standard['definition'], **declaration}}})
    result = EffectRegistry(StatusSystem(rules)).execute(unresolved, context)
    assert result.unsupported and 'battle_event_property_semantics_not_admitted' in str(result.unsupported)
    assert not result.mutations and not result.rng_events
    assert set(context.state.units) == {'owner'}


@pytest.mark.parametrize('startup_delay,expected_av', [(None, 100), (35., 35.), (0., 0.)])
def test_event_birth_keeps_formal_startup_action_value(startup_delay, expected_av):
    rules, create, context = _case(startup_delay)
    result = EffectRegistry(StatusSystem(rules)).execute(create, context)
    assert not result.unsupported, result.unsupported
    after = MutationReducer().apply_all(context.state, result.mutations)
    event = next(unit for unit in after.units.values() if unit.side == 'summon')
    assert event.action_value == expected_av
    audit = RuntimeSourceAuditor(rules).validate_execution(result.mutations, result.records)
    assert audit.ok, audit.to_json()
    assert set(context.state.units) == {'owner'}


def test_event_audit_rejects_reassociated_birth_payload_and_missing_group_member():
    rules, create, context = _case()
    result = EffectRegistry(StatusSystem(rules)).execute(create, context)
    spawn = next(m for m in result.mutations if m.op == 'spawn')
    after = deepcopy(spawn.to_json()['after'])
    after['flags']['owner_id'] = 'sibling'
    forged = replace(spawn, after=after, mutation_id='')
    mutations = tuple(forged if m is spawn else m for m in result.mutations)
    records = tuple({**r, 'mutation_id': forged.stable_id()} if r.get('mutation_id') == spawn.stable_id()
                    else r for r in result.records)
    auditor = RuntimeSourceAuditor(rules)
    assert not auditor.validate_execution(mutations, records).ok
    assert not auditor.validate_execution(result.mutations[:-1], result.records).ok
    missing = tuple(replace(m, battle_event_fact=None) for m in result.mutations)
    assert not auditor.validate_execution(missing, result.records).ok
    renamed = tuple(replace(m, source='effect_system', mutation_id='') if m is spawn else m
                    for m in result.mutations)
    assert not auditor.validate_execution(renamed, result.records).ok


def _target(expression_id, kind, source):
    node = _target_expression_execution_node({'$type': 'RPG.GameCore.' + kind}, source)
    return TargetExpressionIR(expression_id, kind, expression_id, source, node=node,
                              coverage_status='executable')


def test_event_specified_creator_and_owner_change_keep_creation_source():
    rules, create, context = _case()
    expressions = (_target('self', 'TargetFetchCaster', create.source),
                   _target('holder', 'TargetFetchModifierOwner', create.source))
    holder_ref = {'target_expression_id': 'holder', 'coverage_status': 'executable'}
    self_ref = {'target_expression_id': 'self', 'coverage_status': 'executable'}
    from hsr.simulator_v8_clean_core.tbgd.derived_unit_lifecycle import registered_battle_event_lifecycle
    create = replace(create, payload={'standard': {**create.payload['standard'],
        'definition': {**create.payload['standard']['definition'], 'terminal_dependency_policy':
                       registered_battle_event_lifecycle('battle_event:11414')},
        'specify_caster_alias': 'ModifierOwnerEntity',
        'target_expression_refs': {'SpecifyCaster': holder_ref},
    }})
    transfer = EffectIR('transfer', 'ChangeBattleEventOwner', {'standard': {
        'operation': 'change_battle_event_owner', 'target_expression_refs': {
            'BattleEvent': self_ref, 'Owner': holder_ref,
        },
    }}, create.source, 'executable')
    rules = RuleBook(replace(rules.ir, effects=(*rules.ir.effects[1:], create, transfer),
                             target_expressions=expressions))
    state = replace(context.state, units={**context.state.units,
        'holder': UnitState('holder', 'ally', 'fixture:holder', hp=100, max_hp=100),
        'next': UnitState('next', 'ally', 'fixture:next', hp=100, max_hp=100),
    })
    context = replace(context, state=state, owner_id='holder')
    registry = EffectRegistry(StatusSystem(rules))
    born = registry.execute(create, context)
    assert not born.unsupported, born.unsupported
    after = MutationReducer().apply_all(state, born.mutations)
    event = next(unit for unit in after.units.values() if unit.side == 'summon')
    assert event.flags['owner_id'] == event.flags['summoner_id'] == 'holder'
    assert event.flags['creation_source_unit_id'] == event.flags['property_source_id'] == 'owner'
    changed = registry.execute(transfer, replace(context, state=after,
        caster_id=event.unit_id, owner_id='next'))
    assert not changed.unsupported, changed.unsupported
    final = MutationReducer().apply_all(after, changed.mutations)
    assert final.units[event.unit_id].flags['owner_id'] == 'next'
    assert final.units[event.unit_id].flags['creation_source_unit_id'] == 'owner'
    assert final.units['holder'] == after.units['holder']
    assert final.units['next'] == after.units['next']
    audit = RuntimeSourceAuditor(rules).validate_execution(changed.mutations, changed.records)
    assert audit.ok, audit.to_json()
    from hsr.simulator_v8_clean_core.systems.battle_event import retire_battle_event
    previous_holder_dead = replace(final, units={**final.units,
        'holder': replace(final.units['holder'], hp=0, lifecycle_status='defeated')})
    assert not retire_battle_event(rules, previous_holder_dead, event.unit_id, 'holder').mutations
    for dependency_id in ('owner', 'next'):
        terminal = replace(final, units={**final.units,
            dependency_id: replace(final.units[dependency_id], hp=0, lifecycle_status='defeated')})
        retired = retire_battle_event(rules, terminal, event.unit_id, dependency_id)
        assert not retired.unsupported and retired.mutations
        assert MutationReducer().apply_all(terminal, retired.mutations).units[event.unit_id].lifecycle_status == 'removed'
        assert RuntimeSourceAuditor(rules).validate_execution(retired.mutations, retired.records).ok


def test_queue_team_aliases_use_live_formal_relation_not_dead_roster_members():
    from hsr.simulator_v8_clean_core.systems.queue import QueueTargetResolver
    state = BattleState(units={
        'owner': UnitState('owner', 'ally', 'fixture:owner', hp=100, max_hp=100),
        'live': UnitState('live', 'enemy', 'fixture:enemy', hp=100, max_hp=100),
        'dead': UnitState('dead', 'enemy', 'fixture:enemy', hp=0, max_hp=100, lifecycle_status='defeated'),
        'removed': UnitState('removed', 'enemy', 'fixture:enemy', hp=100, max_hp=100, lifecycle_status='removed'),
        'dead-ally': UnitState('dead-ally', 'ally', 'fixture:ally', hp=0, max_hp=100, lifecycle_status='defeated'),
    })
    resolver = QueueTargetResolver()
    for alias, expected in (('AllDarkTeam', ('live',)), ('AllLightTeam', ('owner',))):
        result = resolver.resolve(state, detail={'caster_id': 'owner'}, trigger_event=None,
            actor_alias='Caster', target_alias=alias)
        assert result.ok and result.target_ids == expected, result
    explicit_dead = resolver.resolve(state, detail={'caster_id': 'owner'},
        trigger_event=GameEvent('component', target_id='dead'),
        actor_alias='Caster', target_alias='ParamEntity')
    assert not explicit_dead.ok and 'lifecycle_blocked' in explicit_dead.blocked_reason


def _retirement_case():
    from hsr.simulator_v8_clean_core.tbgd.derived_unit_lifecycle import registered_battle_event_lifecycle
    from hsr.simulator_v8_clean_core.systems.dynamic_values import store_from_state, upsert_dynamic_value
    from hsr.simulator_v8_clean_core.systems.queue import QueueEntry

    rules, create, context = _case()
    standard = deepcopy(create.payload['standard'])
    standard['definition']['terminal_dependency_policy'] = registered_battle_event_lifecycle('battle_event:11216')
    create = replace(create, payload={'standard': standard})
    kill = EffectIR('kill-dependency', 'ForceKill', {'standard': {
        'operation': 'formal_forced_death', 'target_alias': 'Caster',
        'abort_unused_insert_ability': False,
    }}, create.source, 'executable')
    rules = RuleBook(replace(rules.ir, effects=(create, kill)))
    state = replace(context.state, units={**context.state.units,
        'sibling': UnitState('sibling', 'ally', 'fixture:sibling', hp=100, max_hp=100)})
    registry = EffectRegistry(StatusSystem(rules))
    born = registry.execute(create, replace(context, state=state))
    assert not born.unsupported
    state = MutationReducer().apply_all(state, born.mutations)
    own_id = next(m.path[1] for m in born.mutations if m.op == 'spawn')
    other = registry.execute(create, replace(context, state=state, caster_id='sibling'))
    assert not other.unsupported
    state = MutationReducer().apply_all(state, other.mutations)
    other_id = next(m.path[1] for m in other.mutations if m.op == 'spawn')
    store = store_from_state(state)
    from hsr.simulator_v8_clean_core.systems.status import StatusInstance
    units = dict(state.units)
    for unit_id in (own_id, other_id):
        detail = StatusInstance('status:' + unit_id, 'component:status', 'component:modifier',
            unit_id, unit_id, unit_id, source_trace=create.source.to_json()).to_json()
        units[unit_id] = replace(units[unit_id], statuses=('component:status',),
            flags={**units[unit_id].flags, 'status_details': [detail]})
        store = upsert_dynamic_value(store, scope='status', owner_id=unit_id,
            status_instance_id='status:' + unit_id, status_id='component:status',
            value_name='InstanceCount', hash_key='124', value=1, source_id=unit_id)
        store = upsert_dynamic_value(store, scope='unit', owner_id=unit_id,
            value_name='Count', hash_key='123', value=2, source_id=unit_id)
    def queued(entry_id, actor_id, owner_id, targets):
        return QueueEntry(entry_id, 'insert_ability', 'insert_ability', 'fixture:intent',
            actor_id, 'fixture:ability', targets, {}, create.source.to_json(), owner_id=owner_id).to_json()
    entries = [queued('event-action', own_id, own_id, ('sibling',)),
               queued('event-source', 'owner', own_id, ('sibling',)),
               queued('sibling', 'sibling', other_id, ('owner',)),
               queued('target-only', 'sibling', other_id, (own_id,))]
    state = replace(state, units=units, global_flags={**state.global_flags, 'dynamic_value_store': store,
                    'turn_owner_id': own_id}, queues={'insert_ability': entries})
    return rules, state, own_id, other_id


def test_terminal_dependency_retirement_preserves_sibling_and_target_only_queue():
    from hsr.simulator_v8_clean_core.systems.battle_event import retire_battle_event
    from hsr.simulator_v8_clean_core.systems.unit_relation import EntityRelationResolver, TargetEvaluationContext
    rules, state, own_id, other_id = _retirement_case()
    state = replace(state, units={**state.units,
        'owner': replace(state.units['owner'], hp=0, lifecycle_status='defeated')})
    result = retire_battle_event(rules, state, own_id, 'owner')
    assert not result.unsupported, result.unsupported
    from hsr.simulator_v8_clean_core.core.executor import _dedupe_events
    _dedupe_events(*result.events)
    after = MutationReducer().apply_all(state, result.mutations)
    assert after.units[own_id].lifecycle_status == 'removed'
    assert not after.units[own_id].statuses and not after.units[own_id].flags.get('status_details')
    assert after.units[other_id] == state.units[other_id]
    assert [entry['entry_id'] for entry in after.queues['insert_ability']] == ['sibling', 'target-only']
    assert 'turn_owner_id' not in after.global_flags
    assert all(entry['owner_id'] != own_id and entry['target_id'] != own_id
               for entry in after.global_flags['dynamic_value_store']['entries'].values())
    assert any(entry['owner_id'] == other_id
               for entry in after.global_flags['dynamic_value_store']['entries'].values())
    relation = EntityRelationResolver().resolve(after, 'entity.created_battle_events',
        TargetEvaluationContext(caster_id='owner'), subject_ids=('owner',))
    assert relation.resolved and own_id not in relation.target_ids
    audit = RuntimeSourceAuditor(rules).validate_execution(result.mutations, result.records)
    assert audit.ok, audit.to_json()
    assert not RuntimeSourceAuditor(rules).validate_execution(result.mutations[:-1], result.records).ok
    assert not retire_battle_event(rules, after, own_id, 'owner').mutations


def test_limbo_and_unrelated_dependency_cannot_retire_event():
    from hsr.simulator_v8_clean_core.systems.battle_event import retire_battle_event
    rules, state, own_id, _ = _retirement_case()
    pending = replace(state, units={**state.units,
        'owner': replace(state.units['owner'], hp=0, lifecycle_status='limbo')})
    denied = retire_battle_event(rules, pending, own_id, 'owner')
    assert denied.unsupported and not denied.mutations and not denied.rng_events
    sibling = replace(state, units={**state.units,
        'sibling': replace(state.units['sibling'], hp=0, lifecycle_status='defeated')})
    assert not retire_battle_event(rules, sibling, own_id, 'sibling').mutations


def test_confirmed_defeat_dispatch_consumes_registered_event_retirement():
    from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
    rules, state, own_id, other_id = _retirement_case()
    registry = EffectRegistry(StatusSystem(rules))
    killed = registry.execute(rules.effect('kill-dependency'), EffectExecutionContext(state, 'owner', 'component:defeat'))
    assert not killed.unsupported, killed.unsupported
    state = MutationReducer().apply_all(state, killed.mutations)
    dispatcher = EventDispatchSystem(rules, registry)
    result = dispatcher.dispatch_event(state, event=next(event for event in killed.events
                                                        if event.event_type == 'unit.defeated'))
    assert not result.errors, result.errors
    assert result.after_state.units[own_id].lifecycle_status == 'removed'
    assert result.after_state.units[other_id].lifecycle_status == 'active'


def test_retirement_late_destroy_callback_failure_leaks_no_state_queue_or_rng():
    from hsr.simulator_v8_clean_core.rules.ir import StatusCallbackIR
    from hsr.simulator_v8_clean_core.systems.battle_event import retire_battle_event
    rules, state, own_id, _ = _retirement_case()
    detail = {**state.units[own_id].flags['status_details'][0],
              'trigger_ids_by_event': {'OnDestroy': ['component:blocked-destroy']}}
    event = replace(state.units[own_id], flags={**state.units[own_id].flags, 'status_details': [detail]})
    state = replace(state, units={**state.units, own_id: event,
        'owner': replace(state.units['owner'], hp=0, lifecycle_status='defeated')})
    callback = StatusCallbackIR('component:blocked-destroy', 'component:modifier', 'OnDestroy', (),
        rules.effect('create').source, (0, 0), coverage_status='blocked',
        blocked_reason='component:destroy_dependency_missing', admission_status='blocked')
    rules = RuleBook(replace(rules.ir, status_callbacks=(callback,)))
    before = state.snapshot().to_json()
    result = retire_battle_event(rules, state, own_id, 'owner')
    assert result.unsupported and 'callback' in result.unsupported[0]
    assert not result.mutations and not result.events and not result.rng_events
    assert state.snapshot().to_json() == before


def test_registered_dependency_rules_link_to_pinned_source_descriptions():
    import json
    from pathlib import Path
    from hsr.simulator_v8_clean_core.tbgd.derived_unit_lifecycle import registered_battle_event_lifecycle
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    texts = json.loads((root / 'TextMap/TextMapCHS.json').read_text())
    for ref in ('battle_event:11203', 'battle_event:11216', 'battle_event:11222', 'battle_event:11414'):
        policy = registered_battle_event_lifecycle(ref)
        text = texts[policy['source']['raw_id']]
        assert '无法战斗' in text and '消失' in text
    assert registered_battle_event_lifecycle('battle_event:11408') == {}


def test_late_startup_failure_exposes_no_birth_store_or_timeline_writes():
    rules, create, context = _case(35.)
    delay = replace(rules.effect('delay'), coverage_status='blocked')
    rules = type(rules)(replace(rules.ir, effects=(create, delay)))
    result = EffectRegistry(StatusSystem(rules)).execute(create, context)
    assert result.unsupported
    assert not result.mutations and not result.events and not result.rng_events
    assert set(context.state.units) == {'owner'}


def test_event_birth_copies_declared_source_properties_once():
    rules, create, context = _case()
    standard = create.payload['standard']
    declared = [
        'AttackDelta', 'AttackAddedRatio', 'CriticalChance', 'CriticalDamage',
        'FirePenetrate', 'StatusProbability', 'FireAddedRatio',
        'AllDamageTypeAddedRatio',
    ]
    policy = {
        'kind': 'birth_snapshot', 'source': 'creator',
        'declared_property_types': declared,
        'runtime_property_types': declared,
        'unsupported_declared_property_types': [],
        'explicit_property_values': {'BaseAttack': 100.0},
        'source_trace': [],
    }
    create = replace(create, payload={'standard': {**standard,
        'definition': {**standard['definition'], 'property_sync_policy': policy}}})
    rules = type(rules)(replace(rules.ir, effects=(create, rules.effect('delay'))))
    owner = UnitState('owner', 'ally', 'fixture:owner', hp=100, max_hp=100,
        attack=640.0, resources={
            'critical_chance': 0.35, 'critical_damage': 1.4,
            'Fire_damage_added_ratio': 0.4, 'damage_added_ratio': 0.25,
            'effect_hit_rate': 0.6, 'Fire_res_pen': 0.1,
        })
    state = BattleState(units={'owner': owner})
    result = EffectRegistry(StatusSystem(rules)).execute(create, replace(context, state=state))
    assert not result.unsupported, result.unsupported
    after = MutationReducer().apply_all(state, result.mutations)
    event = next(unit for unit in after.units.values() if unit.side == 'summon')
    assert event.attack == 640.0
    assert event.resources == {
        'critical_chance': 0.35, 'critical_damage': 1.4,
        'Fire_damage_added_ratio': 0.4, 'damage_added_ratio': 0.25,
        'effect_hit_rate': 0.6, 'Fire_res_pen': 0.1,
    }
    sync = event.flags['battle_event_property_sync']
    assert sync['source_unit_id'] == 'owner'
    assert sync['resolved_values']['CriticalChance'] == 0.35
    # Birth is a one-shot snapshot: later owner changes do not alias the event.
    changed_owner = replace(owner, attack=999.0)
    changed = replace(after, units={**after.units, 'owner': changed_owner})
    assert changed.units[event.unit_id].attack == 640.0
    audit = RuntimeSourceAuditor(rules).validate_execution(result.mutations, result.records)
    assert audit.ok, audit.to_json()


def test_event_property_sync_without_a_policy_remains_atomic_blocked():
    rules, create, context = _case()
    standard = create.payload['standard']
    unresolved = replace(create, payload={'standard': {**standard,
        'definition': {**standard['definition'],
                       'owner_sync_property_types': ['CriticalChance']}}})
    result = EffectRegistry(StatusSystem(rules)).execute(unresolved, context)
    assert result.unsupported and 'battle_event_property_semantics_not_admitted' in str(result.unsupported)
    assert not result.mutations and not result.rng_events
    assert set(context.state.units) == {'owner'}
