"""Parallel child graphs consume their own sealed skill-target capability."""
from dataclasses import replace

from hsr.simulator_v8_clean_core.core.model import ActionCommand, BattleState, TargetResolution, UnitState
from hsr.simulator_v8_clean_core.rules.ir import (
    AbilityPhaseIR, AbilityTaskIR, ActionDefinitionIR, ActionEventIR, ActionPhaseStepIR,
    CanonicalIR, EffectIR, IRSource, TargetExpressionIR,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.rules.task_graph import TaskGraphQueryResult
from hsr.simulator_v8_clean_core.systems.ability import AbilityTaskSystem, _FormalAbilityInvocation
from hsr.simulator_v8_clean_core.systems.action_event_contract import (
    _issue_action_window_expected_scope, _issue_admitted_action_target_fact,
)
from hsr.simulator_v8_clean_core.systems.effect import EffectRegistry
from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchResult
from hsr.simulator_v8_clean_core.systems.task_graph import TaskGraphHookRequest
from hsr.simulator_v8_clean_core.tbgd.lowering import _target_expression_execution_node
from hsr.simulator_v8_clean_core.tools.validate_p9_s8b2_atomic_executor_core import _graph
from hsr.simulator_v8_clean_core.tools.validate_p9_formal_action_graph_admission_authority import _graph as _leaf_graph


def test_parallel_executor_binds_child_skill_lists_without_changing_parent(monkeypatch):
    source = IRSource('validation_fixture/parallel', 'AbilityTask', 'parallel',
                      {'json_path': '$.OnStart[0]', 'content_sha256': 'a' * 64,
                       'source_opcode': 'TriggerParallelAbility'})
    def expression(label, raw):
        origin = replace(source, raw_id=label, evidence={'json_path': '$.' + label})
        node = _target_expression_execution_node(raw, origin)
        return TargetExpressionIR(label, node.expression_kind, '', origin, node=node, coverage_status='executable')

    caster = expression('caster', {'$type': 'RPG.GameCore.TargetFetchTemplateEntityList'})
    maps = tuple(expression(kind, {'$type': 'RPG.GameCore.TargetSequence', 'Sequence': [
        {'$type': 'RPG.GameCore.TargetFetchCaster'}, {'$type': 'RPG.GameCore.' + kind},
    ]}) for kind in ('TargetMapSkillTarget', 'TargetMapSkillSubTarget'))
    child_graph = _graph('parallel-child', {
        str(index): {'kind': 'target_scope', 'refs': (('target', item.target_expression_id),),
                     'branches': (('target_scope', 'selected', ()),)}
        for index, item in enumerate(maps)
    }, ('0', '1'))
    child_tasks = tuple(AbilityTaskIR(node.formal_task_id, child_graph.owner_id, 'action', 1,
        'child', 'OnStart', index, f'OnStart[{index}]', 'root', node.opcode, node.source,
        target_expression_id=maps[index].target_expression_id, coverage_status='executable')
        for index, node in enumerate(child_graph.nodes))
    phase = AbilityPhaseIR(child_graph.owner_id, 'binding', 'action', 1, 'child', 0, {}, {}, {}, source,
        coverage_status='executable', task_ids=tuple(task.task_id for task in child_tasks), invocation_role='nested_only')
    parent_task = AbilityTaskIR('parallel', 'parent-phase', 'action', 1, 'parent', 'OnStart', 0,
        'OnStart[0]', 'root', 'TriggerParallelAbility', source, effect_id='parallel-effect', coverage_status='executable')
    parent_graph = _leaf_graph(parent_task.phase_id, parent_task)
    effect = EffectIR(parent_task.effect_id, parent_task.opcode, {'standard': {
        'operation': 'parallel_ability_calls', 'calls': [{'phase_ids': [phase.phase_id]}],
        'target_expression_refs': {'ParallelAbilityList[0].TargetType': {'target_expression_id': caster.target_expression_id}},
    }}, source, 'executable')
    definition = ActionDefinitionIR('definition', 'action', 1, 'Normal', 'Basic', 'single',
        0, 0, 0, 0, (), (), (), None, source, coverage_status='executable')
    steps = tuple(ActionPhaseStepIR('trigger_window', window, window, callback,
        coverage_status='executable', source=source) for window, callback in (
        ('before_attack', 'OnBeforeAttack'), ('after_attack', 'OnAfterAttack')))
    event = ActionEventIR('action:event', 'action', 1, 'single', 'explicit', steps, (),
        'derived', '', source, coverage_status='executable')

    class Rules(RuleBook):
        def query_task_graph(self, graph_id):
            graph = next(graph for graph in (parent_graph, child_graph) if graph.graph_id == graph_id)
            return TaskGraphQueryResult('resolved', 'graph', (graph_id,), graph, '')

        def query_task_graph_node(self, node_id):
            node = next(node for graph in (parent_graph, child_graph) for node in graph.nodes
                        if node.graph_node_id == node_id)
            return TaskGraphQueryResult('resolved', 'node', (node_id,), node, '')

        def query_formal_task_graph(self, kind, owner, callback, task_ids):
            assert kind == 'ability_phase_callback' and owner == phase.phase_id and callback == 'OnStart'
            assert set(task_ids) == set(phase.task_ids)
            return self.query_task_graph(child_graph.graph_id)

    rules = Rules(CanonicalIR('parallel-skill-check', ability_phases=(phase,),
        ability_tasks=(parent_task, *child_tasks), effects=(effect,), target_expressions=(caster, *maps),
        action_definitions=(definition,), action_events=(event,)))
    state = BattleState(units={key: UnitState(key, side, 'fixture:' + key, hp=100, max_hp=100)
        for key, side in (('parent', 'ally'), ('child', 'ally'), ('main', 'enemy'), ('sub', 'enemy'))})
    targets = TargetResolution(selected=('main',), legal=('main',), primary='main', impact_group=('main', 'sub'))
    parent_fact = _issue_admitted_action_target_fact(actor_id='parent', action_id='action', action_level=1,
        selection_context_fingerprint='selection', contract_fingerprint='contract', impact_fingerprint='impact',
        canonical_action_event_id=event.action_event_id, target_mode='blast', target_ids=('main', 'sub'),
        skill_target_ids=('main',), skill_sub_target_ids=('sub',))
    claims = parent_fact._claim_values()
    token = object()
    parent_scope = _issue_action_window_expected_scope(execution_token=token, actor_id='parent', action_id='action',
        action_level=1, canonical_action_event_id=event.action_event_id, impact_fingerprint='impact',
        event_id='parent:window', window='OnStart', step_id='parent:step', step_index=0)
    invocation = _FormalAbilityInvocation('action', 'parent', 'action', 1, targets,
        action_command=ActionCommand('parent', 'action', 1, ('main',)), action_definition=definition,
        action_execution_token=token, accepted_action_target_fact=parent_fact,
        admitted_action_target_fact=parent_fact.bind_invocation(parent_scope), expected_action_window_scope=parent_scope)
    windows = []
    class Dispatcher:
        def dispatch_action_window_listeners(self, current, *, event, expected_window_scope, **kwargs):
            fact = event.admitted_action_target_fact
            assert fact.actor_id == 'child' and not fact.invocation_blocked_reason(expected_scope=expected_window_scope)
            assert fact.skill_target_ids == ('main',) and fact.skill_sub_target_ids == ('sub',)
            windows.append(event.window)
            return EventDispatchResult(current)

    runtime = AbilityTaskSystem(rules, EffectRegistry(), event_dispatcher=Dispatcher())
    observed = []
    resolve = runtime._resolve_formal_targets
    def inspect(request, current, *, invocation):
        result = resolve(request, current, invocation=invocation)
        assert invocation.actor_id == 'child' and result.status == 'resolved'
        assert invocation.target_resolution.selected == ('sub',)  # Current Retarget is separate from skill main.
        assert not invocation.admitted_action_target_fact.invocation_blocked_reason(
            expected_scope=invocation.expected_action_window_scope)
        wrong = resolve(request, current, invocation=replace(invocation, expected_action_window_scope=parent_scope))
        assert wrong.status == 'blocked' and wrong.blocked_reason == 'action_target_fact_invocation_mismatch'
        observed.append(result.target_ids)
        return result
    monkeypatch.setattr(runtime, '_resolve_formal_targets', inspect)
    node = parent_graph.nodes[0]
    request = TaskGraphHookRequest('parent', parent_graph.graph_id, node.graph_node_id, parent_task.task_id,
        parent_task.opcode, node.source_family, (), {}, (parent_graph.graph_id,), (), ('sub',), None, ('root',),
        template_target_ids=('child',))
    result = runtime._execute_parallel_abilities(request, state, parent_task, invocation)
    assert result.status == 'resolved', result.blocked_reason
    assert observed == [('main',), ('sub',)] and windows == ['before_attack', 'after_attack']
    assert parent_fact.actor_id == 'parent' and not parent_fact.event_id and parent_fact._claim_values() == claims
    assert not result.mutations and not result.rng_events
