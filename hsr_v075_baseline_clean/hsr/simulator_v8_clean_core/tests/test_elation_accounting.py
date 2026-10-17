"""Bounded shared accounting check; no character compilation or battle."""
from dataclasses import replace

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_fixed
from hsr.simulator_v8_clean_core.rules.ir import BattleStateTransitionIR, CanonicalIR, EffectIR, IRSource
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.battle_state_transition import (
    BattleStateTransitionRequest, BattleStateTransitionSystem,
)
from hsr.simulator_v8_clean_core.systems.dynamic_values import store_from_state
from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext
from hsr.simulator_v8_clean_core.systems.elation import (
    ElationDamageContext, execute_elation_operation, resolve_elation_damage_context, validate_elation_runtime,
)
from hsr.simulator_v8_clean_core.systems.mutation_events import events_for_mutation
from hsr.simulator_v8_clean_core.systems.status import StatusInstance


def test_points_windows_echo_and_contextual_values_share_audited_storage():
    source = IRSource('validation_fixture/elation.json', 'Elations', 'shared',
                      {'json_path': '$.operations'})
    def effect(name, operation, **fields):
        return EffectIR(name, 'ElationOperation', {'standard': {
            'kind': 'elation', 'elation_operation': operation, **fields,
        }}, source, 'executable')
    add = effect('add', 'add_points', amount_expr=numeric_fixed(5))
    clear = effect('clear', 'set_points', amount_expr=numeric_fixed(0))
    cap = effect('cap', 'set_points', amount_expr=numeric_fixed(10001))
    read_base = effect('read-base', 'read_points', point_type='base', target_alias='Caster',
                       destination_dynamic_key='base', destination_dynamic_hash='1')
    read_effective = effect('read-effective', 'read_points', point_type='effective', target_alias='Caster',
                            destination_dynamic_key='effective', destination_dynamic_hash='2')
    convert = replace(effect('convert', 'convert_echo', amount_expr=numeric_fixed(13), target_alias='ModifierOwnerEntity',
        recipient_target_alias='ParamEntity',
        destination_dynamic_key='grant', destination_dynamic_hash='3'), owner_modifier_name='Fixture')
    transitions = tuple(BattleStateTransitionIR(name, 'fixture', name,
        ('global_flags', 'elation_time_active'), before, after, event, callback, source,
        coverage_status='executable', allow_missing_before=after, participant_team='ally') for name, before, after, event, callback in (
            ('start', False, True, 'elation.time.started', 'OnListenElationTimeStart'),
            ('end', True, False, 'elation.time.ended', 'OnListenElationTimeEnd')))
    rules = RuleBook(CanonicalIR('elation-accounting-check', effects=(add, clear, cap, read_base, read_effective, convert),
                                 battle_state_transitions=transitions))
    detail = StatusInstance('status', 'modifier:Fixture', 'Fixture', 'actor', 'fixture', 'actor',
        modifiers=({'bucket': 'resource', 'key': 'elation_echo_point', 'value': 3.},)).to_json()
    state = BattleState(units={
        'actor': UnitState('actor', 'ally', 'fixture', hp=100, max_hp=100,
            resources={'elation_echo_point': 7}, statuses=('modifier:Fixture',), flags={'status_details': [detail]}),
        'enemy': UnitState('enemy', 'enemy', 'fixture', hp=100, max_hp=100),
        'moment': UnitState('moment', 'summon', 'fixture', hp=1, max_hp=1,
                            flags={'entity_type': 'battle_event', 'owner_id': 'actor'}),
    })
    reducer = MutationReducer()
    audit = RuntimeSourceAuditor(rules)
    initial = state.snapshot().to_json()
    sequence = 0

    def apply(current, operation, caster='actor'):
        nonlocal sequence
        sequence += 1
        context = EffectExecutionContext(current, caster, 'fixture', owner_id=caster, param_entity_id='actor',
            ability_instance_id='ability:fixture', event_payload={
                'operation_event_id': f'operation:{sequence}',
                **({'status_instance_id': 'status'} if operation == convert else {}),
            })
        result = execute_elation_operation(current, rules, operation, context)
        assert not result.unsupported, result.unsupported
        checked = audit.validate_execution(result.mutations, result.records)
        assert checked.ok, checked.to_json()
        return reducer.apply_all(current, result.mutations), result

    def transition(current, name, override=None):
        result = BattleStateTransitionSystem(rules).apply(current,
            BattleStateTransitionRequest('fixture', name, actor_id='moment', elation_override_points=override))
        assert result.ok, result.errors
        checked = audit.validate_execution(result.mutations, result.records)
        assert checked.ok, checked.to_json()
        assert not validate_elation_runtime(result.after_state.global_flags['elation_runtime'])
        return result.after_state

    zero, _ = apply(state, read_base)
    assert next(iter(store_from_state(zero)['entries'].values()))['value'] == 0
    current, result = apply(state, add, caster='enemy')
    assert len(result.events) == 1 and result.events[0].payload['before'] == 0 and result.events[0].payload['after'] == 5
    regenerated = events_for_mutation(result.mutations[0], actor_id='enemy', source_id='fixture')
    assert regenerated == result.events
    current = transition(current, 'start')
    echo = resolve_elation_damage_context(current, 'actor', point_source='echo')
    moment = resolve_elation_damage_context(current, 'actor', point_source='moment')
    assert echo.points == 10 and moment.points == 5 and echo.source_kind != moment.source_kind
    assert not echo.blocked_reason(actor_id='actor', state=current)
    assert echo.blocked_reason(actor_id='enemy', state=current) == 'elation_context_actor_mismatch'
    current, _ = apply(current, add)
    assert resolve_elation_damage_context(current, 'actor', point_source='moment').points == 10
    assert moment.blocked_reason(actor_id='actor', state=current) == 'elation_context_stale'
    current, _ = apply(current, clear)
    current, _ = apply(current, read_base)
    current, _ = apply(current, read_effective)
    values = {row['name']: row['value'] for row in store_from_state(current)['entries'].values()}
    assert values == {'base': 0, 'effective': 0}
    current, _ = apply(current, convert)
    assert current.units['actor'].flags['status_details'][0]['dynamic_values']['__by_hash']['3'] == 13
    assert current.units['actor'].statuses == state.units['actor'].statuses
    assert resolve_elation_damage_context(current, 'actor', point_source='echo').points == 10
    current = transition(current, 'end')
    assert moment.blocked_reason(actor_id='actor', state=current)
    assert len(current.global_flags['elation_runtime']['moments']) == 1
    current = transition(current, 'start', 40)
    current, _ = apply(current, add)
    assert resolve_elation_damage_context(current, 'actor', point_source='moment').points == 40
    assert resolve_elation_damage_context(current, 'actor', point_source='echo').points == 10
    current, _ = apply(current, cap)
    assert current.global_flags['elation_runtime']['base_points'] == 9999
    assert len(current.global_flags['elation_runtime']['moments']) == 2
    current = transition(current, 'end')
    assert len(current.global_flags['elation_runtime']['moments']) == 1
    try:
        resolve_elation_damage_context(replace(state, global_flags={'elation_time_active': True}),
                                       'actor', point_source='moment')
    except ValueError:
        pass
    else:
        raise AssertionError('an active boolean must not invent a moment tally')
    try:
        ElationDamageContext(actor_id='actor', points=999)
    except TypeError:
        pass
    else:
        raise AssertionError('a caller must not manufacture per-hit points')
    assert state.snapshot().to_json() == initial
    _check_real_echo_template_and_independent_expiry()


def _check_real_echo_template_and_independent_expiry():
    import json
    from hashlib import sha256
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from types import SimpleNamespace
    from hsr.simulator_v8_clean_core.core.model import TargetResolution
    from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_dynamic_hash
    from hsr.simulator_v8_clean_core.rules.ir import AbilityTaskIR
    from hsr.simulator_v8_clean_core.rules.task_graph import (
        TaskGraphQueryResult, task_graph_branch_id, task_graph_node_id,
        task_graph_reference_id, task_graph_source_occurrence_id,
    )
    from hsr.simulator_v8_clean_core.systems.ability import AbilityTaskSystem, _FormalAbilityInvocation
    from hsr.simulator_v8_clean_core.systems.dynamic_values import upsert_dynamic_value
    from hsr.simulator_v8_clean_core.systems.effect import EffectRegistry
    from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
    from hsr.simulator_v8_clean_core.systems.status import StatusSystem
    from hsr.simulator_v8_clean_core.systems.task_graph import TaskGraphExecutionContext
    from hsr.simulator_v8_clean_core.systems.unit_stats import effective_unit_stat
    from hsr.simulator_v8_clean_core.tbgd.character_control_flow_contracts import _discover_shared_templates, _template_ir
    from hsr.simulator_v8_clean_core.tbgd.lowering import (
        TBGDLowering, _attach_target_expressions_to_effect_payload, _effect_payload,
        _link_status_effect_runtime_fields, _synchronize_effect_target_expression_metadata,
    )
    from hsr.simulator_v8_clean_core.tbgd.target_source import build_target_language_definitions, close_target_expression_language
    from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import _materialize_template_parameters
    from hsr.simulator_v8_clean_core.tools.validate_p9_s8b2_atomic_executor_core import _graph

    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    stage_path = 'Config/ConfigAbility/BattleEvent/StageAbility_Elation.json'
    shared_path = 'Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json'
    stage_bytes, shared_bytes = (root / stage_path).read_bytes(), (root / shared_path).read_bytes()
    stage, shared = json.loads(stage_bytes), json.loads(shared_bytes)
    base_path = '$.GlobalModifiers.MBattleEvent_Elation_Passive._CallbackList[8].CallbackConfig[8].FailedTaskList'
    branch = stage['GlobalModifiers']['MBattleEvent_Elation_Passive']['_CallbackList'][8]['CallbackConfig'][8]['FailedTaskList']
    template_index, template_raw = next((index, row) for index, row in enumerate(shared['TaskListTemplate'])
                                        if row['Name'] == 'AddElationEchoPoint')
    body_path = f'$.TaskListTemplate[{template_index}].TaskList[0]'
    convert_raw, grant_raw = template_raw['TaskList'][0]['TaskList']
    def origin(path, raw, json_path):
        data = stage_bytes if path == stage_path else shared_bytes
        return IRSource(path, 'AbilityTask', json_path, {'json_path': json_path,
            'content_sha256': sha256(data).hexdigest(), 'source_opcode': raw['$type'].split('.')[-1]})
    include_source = origin(stage_path, branch[1], base_path + '[1]')
    with TemporaryDirectory() as directory:
        mini = Path(directory)
        path = mini / shared_path
        path.parent.mkdir(parents=True)
        path.write_bytes(shared_bytes)
        drafts, _, _, _ = _discover_shared_templates(mini)
        template = _template_ir(next(row for row in drafts if row.name == template_raw['Name']), {})
        parameters = _materialize_template_parameters(SimpleNamespace(source_bytes={stage_path: stage_bytes}),
                                                      include_source, template)
    definitions = build_target_language_definitions(root)
    effects, targets = {}, []
    for name, raw, source in (
        ('read', branch[0], origin(stage_path, branch[0], base_path + '[0]')),
        ('convert', convert_raw, origin(shared_path, convert_raw, body_path + '.TaskList[0]')),
        ('grant', grant_raw, origin(shared_path, grant_raw, body_path + '.TaskList[1]')),
    ):
        opcode = 'AddModifier' if name == 'grant' else 'ElationOperation'
        payload, expressions = _attach_target_expressions_to_effect_payload(
            _effect_payload(raw, opcode, '', source=source), raw, effect_id='real:' + name, source=source)
        expressions = [close_target_expression_language(row, definitions) for row in expressions]
        targets.extend(expressions)
        effects[name] = _synchronize_effect_target_expression_metadata([
            EffectIR('real:' + name, opcode, payload, source, 'executable')], expressions)[0]
    lowered = TBGDLowering(root)._lower_ability_file(root / stage_path, {}, ability_file_order=0)
    modifier = grant_raw['ModifierName']['Value']
    definition = next(row for row in lowered.entities if row.fields.get('modifier_name') == modifier)
    callbacks = tuple(row for row in lowered.status_callbacks if row.modifier_name == modifier)
    callback_tasks = tuple(row for row in lowered.status_callback_tasks if row.modifier_name == modifier)
    assert callbacks and all(row.coverage_status == 'executable' for row in (*callbacks, *callback_tasks))
    effects['grant'] = _link_status_effect_runtime_fields([effects['grant']], [definition], list(callbacks))[0]
    # The component starts with an admitted recipient list; the stage's complete
    # OnEnd selection/queue graph is deliberately outside this bounded check.
    graph = _graph('real-echo-template', {
        'read': {'kind': 'leaf'},
        'include': {'kind': 'template_call', 'refs': (('template', template.template_id),),
                    'branches': (('template_body', template_raw['Name'], ('convert', 'grant')),)},
        'convert': {'kind': 'leaf'}, 'grant': {'kind': 'leaf'}, 'after': {'kind': 'leaf'},
    }, ('read', 'include', 'after'))
    effects['after'] = EffectIR('real:after', 'ResourceDelta', {'standard': {
        'target_alias': 'ParamEntity', 'resource': 'outer_parameter', 'amount': numeric_dynamic_hash(parameters[0].destination_hash),
    }}, IRSource('validation_fixture/template_exit.json', 'ResourceDelta', 'after',
                 {'json_path': '$.after', 'content_sha256': 'a' * 64, 'source_opcode': 'ResourceDelta'}), 'executable')
    tasks = tuple(AbilityTaskIR(node.formal_task_id, graph.owner_id, 'fixture:echo', 1, 'fixture', 'OnStart', index,
        f'OnStart[{index}]', 'root', 'IncludeTaskListTemplate' if node.formal_task_id == 'task:include'
        else effects[node.formal_task_id.split(':')[-1]].opcode,
        include_source if node.formal_task_id == 'task:include' else effects[node.formal_task_id.split(':')[-1]].source,
        effect_id='' if node.formal_task_id == 'task:include' else effects[node.formal_task_id.split(':')[-1]].effect_id,
        coverage_status='executable') for index, node in enumerate(graph.nodes))
    occurrences = {node.graph_node_id: task_graph_source_occurrence_id(task.source, task.source.evidence['source_opcode'])
                   for node, task in zip(graph.nodes, tasks)}
    ids = {node.graph_node_id: task_graph_node_id(graph.graph_id, node.formal_task_id, occurrences[node.graph_node_id])
           for node in graph.nodes}
    nodes = []
    for node, task in zip(graph.nodes, tasks):
        node_id = ids[node.graph_node_id]
        branches = tuple(replace(branch, graph_node_id=node_id,
            branch_id=task_graph_branch_id(node_id, branch.branch_kind, branch.ordinal, branch.label,
                tuple(ids[key] for key in branch.child_node_ids)),
            child_node_ids=tuple(ids[key] for key in branch.child_node_ids)) for branch in node.branches)
        references = tuple(replace(ref, graph_node_id=node_id,
            reference_id=task_graph_reference_id(node_id, ref.reference_kind, ref.definition_id)) for ref in node.references)
        nodes.append(replace(node, graph_node_id=node_id, source_occurrence_id=occurrences[node.graph_node_id],
            opcode=task.opcode, source=task.source, branches=branches, references=references,
            source_family=task.source.evidence['source_opcode'],
            template_parameters=parameters if task.opcode == 'IncludeTaskListTemplate' else ()))
    graph = replace(graph, nodes=tuple(nodes), root_node_ids=tuple(ids[key] for key in graph.root_node_ids))

    class Rules(RuleBook):
        def query_task_graph(self, graph_id):
            return TaskGraphQueryResult('resolved', 'graph', (graph_id,), graph, '')
        def query_task_graph_node(self, node_id):
            node = next(node for node in graph.nodes if node.graph_node_id == node_id)
            return TaskGraphQueryResult('resolved', 'node', (node_id,), node, '')

    rules = Rules(CanonicalIR('real-echo-template-check', entities=(definition,), ability_tasks=tasks,
        effects=tuple(effects.values()), status_callbacks=callbacks, status_callback_tasks=callback_tasks,
        target_expressions=(*targets, *(row.expression for row in definitions))))
    registry = EffectRegistry(StatusSystem(rules))
    dispatcher = EventDispatchSystem(rules, registry)
    runtime = AbilityTaskSystem(rules, registry, event_dispatcher=dispatcher)
    outer_store = upsert_dynamic_value(None, scope='ability', owner_id='level:global', target_id='level:global',
        ability_instance_id='ability_status_nested:0:level:global:fixture:echo:1', value=97,
        value_name=parameters[0].parameter_name, hash_key=parameters[0].destination_hash,
        source_id='fixture:outer-parameter', source_trace=include_source.to_json())
    state = BattleState(units={
        'recipient': UnitState('recipient', 'ally', 'fixture', hp=100, max_hp=100),
        'level:global': UnitState('level:global', 'ally', 'system_entity:level', hp=1, max_hp=1, speed=0,
                                  flags={'system_entity_kind': 'level', 'unselectable': True}),
    },
        global_flags={'dynamic_value_store': outer_store, 'elation_runtime': {
            'schema_version': 'hsr.elation_runtime.v1', 'base_points': 5., 'moments': {},
            'active_moment_id': '', 'moment_sequence': 0}})
    reducer, auditor = MutationReducer(), RuntimeSourceAuditor(rules)
    invocation = _FormalAbilityInvocation('status_nested', 'level:global', 'fixture:echo', 1,
        TargetResolution(primary='recipient', selected=('recipient',), legal=('recipient',)))
    def grant(current, identity):
        result = runtime.task_graph_executor.execute(current, graph,
            TaskGraphExecutionContext(identity, template_target_ids=('recipient',)),
            runtime._formal_task_graph_hooks(invocation=invocation))
        assert result.ok, result.errors
        checked = auditor.validate_execution(result.mutations, tuple(row.to_json() for row in result.settlement_records))
        assert checked.ok, checked.to_json()
        return result.after_state
    current = grant(state, 'grant:first')
    assert effective_unit_stat(current.units['recipient'], 'elation_echo_point').value == 5
    assert current.units['recipient'].resources['outer_parameter'] == 97
    first = current.units['recipient'].flags['status_details'][0]
    assert first['remaining_duration'] == 2
    repeated = runtime.task_graph_executor.execute(current, graph,
        TaskGraphExecutionContext('grant:first', template_target_ids=('recipient',)),
        runtime._formal_task_graph_hooks(invocation=invocation))
    assert not repeated.ok and repeated.errors == ('status_application_instance_replayed',)
    assert repeated.after_state == current and not repeated.mutations and not repeated.events and not repeated.rng_events
    tick = registry.status_system.apply_lifecycle_tick(current, 'recipient', first, first['life_step_moment'])
    assert tick.ok
    assert auditor.validate_execution(tick.mutations, tick.records).ok
    current = reducer.apply_all(current, tick.mutations)
    current = grant(current, 'grant:second')
    details = current.units['recipient'].flags['status_details']
    assert len(details) == 2 and len({row['instance_id'] for row in details}) == 2
    assert sorted(row['remaining_duration'] for row in details) == [1, 2]
    assert effective_unit_stat(current.units['recipient'], 'elation_echo_point').value == 10
    for detail in tuple(details):
        tick = registry.status_system.apply_lifecycle_tick(current, 'recipient', detail, detail['life_step_moment'])
        assert tick.ok
        assert auditor.validate_execution(tick.mutations, tick.records).ok
        current = reducer.apply_all(current, tick.mutations)
    assert effective_unit_stat(current.units['recipient'], 'elation_echo_point').value == 5
    remaining = current.units['recipient'].flags['status_details'][0]
    assert remaining['status_id'] in current.units['recipient'].statuses
    tick = registry.status_system.apply_lifecycle_tick(current, 'recipient', remaining, remaining['life_step_moment'])
    assert tick.ok and auditor.validate_execution(tick.mutations, tick.records).ok
    current = reducer.apply_all(current, tick.mutations)
    assert effective_unit_stat(current.units['recipient'], 'elation_echo_point').value == 0
    assert not current.units['recipient'].statuses
    assert not state.units['recipient'].statuses
