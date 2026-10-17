"""Component check of CreateServant's typed continuation, not character acceptance."""
from dataclasses import replace

from hsr.simulator_v8_clean_core.core.model import BattleState, Mutation, TargetResolution, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.settlement import SettlementRecord
from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_fixed
from hsr.simulator_v8_clean_core.rules.ir import (
    AbilityTaskIR, CanonicalIR, EffectIR, ServantDefinitionIR,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.rules.task_graph import TaskGraphQueryResult
from hsr.simulator_v8_clean_core.systems.ability import AbilityTaskSystem, _FormalAbilityInvocation
from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry, EffectResult
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.systems.summon import (
    SummonSystem, SummonTransitionPlan, SummonTransitionResult,
)
from hsr.simulator_v8_clean_core.systems.task_graph import TaskGraphExecutionContext
from hsr.simulator_v8_clean_core.systems.unit_lifecycle import UnitLifecycleSystem
from hsr.simulator_v8_clean_core.tools.validate_p9_s8b2_atomic_executor_core import _graph


def test_created_servant_continuation_runs_after_initialization_and_rolls_back(monkeypatch):
    graph = _graph('servant-continuation', {
        'create': {'kind': 'leaf', 'refs': (('effect', 'effect:create'),),
                   'branches': (('servant_created', '', ('callback', 'caster')),)},
        'callback': {'kind': 'leaf'}, 'caster': {'kind': 'leaf'}, 'after': {'kind': 'leaf'},
    }, ('create', 'after'))
    tasks = tuple(AbilityTaskIR(node.formal_task_id, graph.owner_id, 'fixture:ability', 1,
        'fixture', 'OnStart', index, f'OnStart[{index}]', 'root',
        'CreateServant' if node.formal_task_id == 'task:create' else 'ResourceDelta', node.source,
        effect_id=node.formal_task_id.replace('task:', 'effect:'), coverage_status='executable')
        for index, node in enumerate(graph.nodes))
    graph = replace(graph, nodes=tuple(replace(node, opcode=task.opcode)
                                      for node, task in zip(graph.nodes, tasks)))
    create = next(task for task in tasks if task.opcode == 'CreateServant')
    source = create.source
    effects = (EffectIR(create.effect_id, 'CreateServant', {'standard': {
        'operation': 'create_servant', 'servant_id': numeric_fixed(1),
        'creation_callback_required': True,
        'dynamic_values': {'initial': {'expression': numeric_fixed(7), 'hash': '17'}},
        'spawn_source': source.to_json(),
    }}, source, 'executable'), *(EffectIR(task.effect_id, task.opcode, {'standard': {
        'target_alias': 'Caster' if task.task_id == 'task:caster' else 'ParamEntity',
        'resource': 'callback_count', 'amount': numeric_fixed(1), 'operation': 'add',
    }}, task.source, 'executable') for task in tasks if task != create))
    definition = ServantDefinitionIR('servant:1', 'servant:1', 'unit', (), {}, {}, {}, {}, source,
                                    coverage_status='executable')

    class Rules(RuleBook):
        def query_task_graph(self, graph_id):
            assert graph_id == graph.graph_id
            return TaskGraphQueryResult('resolved', 'graph', (graph_id,), graph, '')

        def query_task_graph_node(self, node_id):
            node = next(node for node in graph.nodes if node.graph_node_id == node_id)
            return TaskGraphQueryResult('resolved', 'node', (node_id,), node, '')

    rules = Rules(CanonicalIR('servant-continuation-check', ability_tasks=tasks,
                              effects=effects, servant_definitions=(definition,)))
    state = BattleState(units={key: UnitState(key, side, 'fixture:' + key,
        hp=100, max_hp=100) for key, side in (('owner', 'ally'), ('outer', 'enemy'))})
    before = state.snapshot().to_json()
    calls = []

    # The existing servant route verifies full source-bound birth/initialization.
    # This fixture keeps the actual effect -> plan.unit_ids -> graph handoff and
    # substitutes only the costly servant build and startup input assembly.
    def plan_spawn(self, current, candidate, *, owner_id, spawn_source):
        assert current == state and candidate == definition
        assert owner_id == 'owner' and spawn_source == source
        calls.append('plan')
        return SummonTransitionPlan(True, 'servant_spawn', actor_id=owner_id,
                                    owner_id=owner_id, unit_ids=('newborn',))

    def apply_spawn(self, current, plan, *, initial_values):
        assert initial_values == {'initial': {'value': 7., 'hash': '17'}}
        calls.append('initialize')
        child = UnitState('newborn', 'summon', 'servant:1', hp=100, max_hp=100,
                          flags={'owner_id': plan.owner_id, 'summon_kind': 'servant'})
        birth = UnitLifecycleSystem().spawn_mutation(current, child,
            reason='continuation fixture birth', source='validation_fixture', source_trace=source.to_json())
        initialized = Mutation('set', ('units', 'newborn', 'flags', 'initialized'), None, True,
            'continuation fixture startup', 'validation_fixture', before_exists=False)
        records = tuple(SettlementRecord('fixture_birth', 'validation_fixture', mutation.stable_id(),
            payload={'source': source.to_json()}).to_json() for mutation in (birth, initialized))
        return SummonTransitionResult(plan, (birth, initialized), (), records)

    monkeypatch.setattr(SummonSystem, 'plan_spawn_servant', plan_spawn)
    monkeypatch.setattr(SummonSystem, 'apply_spawn_servant', apply_spawn)
    registry = EffectRegistry(StatusSystem(rules))
    execute = registry.execute
    denied = execute(effects[0], EffectExecutionContext(state, 'owner', 'fixture'))
    assert denied.unsupported == ('servant_create_continuation_required',)
    assert not denied.mutations and not denied.created_unit_ids and not calls
    observed = []
    reject_callback = False

    def inspect(effect, context):
        if effect.opcode == 'ResourceDelta':
            assert context.caster_id == 'owner'
            if effect.effect_id in {'effect:callback', 'effect:caster'}:
                assert calls == ['plan', 'initialize']
                assert context.state.units['newborn'].flags['initialized'] is True
                assert context.param_entity_id == 'newborn'
                assert context.target_resolution.selected == ('newborn',)
            else:
                assert context.param_entity_id == 'outer'
                assert context.target_resolution.selected == ('outer',)
            observed.append(effect.effect_id)
            if reject_callback and effect.effect_id == 'effect:callback':
                return EffectResult(unsupported=('fixture_callback_failure',))
        return execute(effect, context)

    monkeypatch.setattr(registry, 'execute', inspect)
    runtime = AbilityTaskSystem(rules, registry)
    targets = TargetResolution(primary='outer', selected=('outer',), legal=('outer',))
    invocation = _FormalAbilityInvocation('status_nested', 'owner', 'fixture:ability', 1, targets)

    def run():
        return runtime.task_graph_executor.execute(state, graph,
            TaskGraphExecutionContext('servant-continuation'),
            runtime._formal_task_graph_hooks(invocation=invocation))

    result = run()
    assert result.ok, result.errors
    assert observed == ['effect:callback', 'effect:caster', 'effect:after']
    assert all(result.after_state.units[key].resources['callback_count'] == 1
               for key in ('newborn', 'owner', 'outer'))
    assert result.after_state.units['newborn'].flags['initialized'] is True
    assert state.snapshot().to_json() == before
    assert MutationReducer().apply_all(state, result.mutations) == result.after_state

    calls.clear()
    observed.clear()
    reject_callback = True
    failed = run()
    assert not failed.ok and any('fixture_callback_failure' in reason for reason in failed.errors)
    assert calls == ['plan', 'initialize'] and observed == ['effect:callback']
    assert failed.after_state == state and not failed.mutations and not failed.events and not failed.rng_events
    assert state.snapshot().to_json() == before
