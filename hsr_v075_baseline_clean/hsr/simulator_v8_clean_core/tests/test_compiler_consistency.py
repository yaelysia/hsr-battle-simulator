"""Shared lowering keeps unknown source semantics blocked and typed queries authoritative."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.rules.ir import (
    ActionDefinitionIR, CanonicalIR, ConditionIR, IRSource, TargetExpressionNodeIR,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.scenarios.identity import IdentityResolver
from hsr.simulator_v8_clean_core.scenarios.schema import RouteStepSpec, ScenarioSpec
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    CONDITION_EXPRESSION_NODE_SCHEMA, IRIdentityConflictError,
    _condition_payload_target_blocked_reason, _target_expression_execution_node,
    TBGDLowering, _condition_ir_from_typed_target_predicate, merge_identical_ir_items,
    _effect_payload,
)
from hsr.simulator_v8_clean_core.tbgd.character_ability_scope import (
    AVATAR_CONFIG_TABLES, AVATAR_ENHANCED_CONFIG_TABLE, SERVANT_CONFIG_TABLE, _discover_source_candidates_from_rows,
)
from hsr.simulator_v8_clean_core.tbgd.character_ability_source_graph import (
    CharacterAbilitySourceGraphPlanMismatch, _action_kinds,
)


def test_action_source_context_is_shared_immutably_without_changing_json():
    from hsr.simulator_v8_clean_core.immutable_json import FrozenJSONDict, freeze_json
    from hsr.simulator_v8_clean_core.tbgd.lowering import _ability_graph_source_context, _json_safe
    parameters = [1.0, 2.0]
    context = _ability_graph_source_context(
        source_mode='fixture', skill_row={'SkillID': 1, 'ParamList': parameters},
        skill_trigger_key='Skill01', character_path='fixture.json', character_config={},
        config_source={}, config_kind='fixture', ability_paths=('ability.json',),
    )
    assert type(context) is FrozenJSONDict
    parameters.append(3.0)
    assert context['param_list'] == [1.0, 2.0]
    first = _json_safe({'ability_source_context': context})
    second = _json_safe({'ability_source_context': context})
    assert first is not second and first['ability_source_context'] is second['ability_source_context'] is context
    assert json.loads(json.dumps(first))['ability_source_context'] == context
    with pytest.raises(TypeError):
        first['ability_source_context']['param_list'].append(3.0)
    frozen_list = freeze_json([{'value': 1}])
    assert _json_safe(frozen_list) is frozen_list
    mutable = {'values': [{'value': 1}]}
    copied = _json_safe(mutable)
    copied['values'][0]['value'] = 2
    assert mutable['values'][0]['value'] == 1


def test_scoped_ir_keeps_known_event_protocol_without_admitting_unknown_events():
    from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, UnitState
    from hsr.simulator_v8_clean_core.systems.effect import EffectRegistry
    from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
    from hsr.simulator_v8_clean_core.systems.status import StatusSystem
    from hsr.simulator_v8_clean_core.tbgd.lowering import _lower_status_event_families

    rules = RuleBook(CanonicalIR('fixture:scoped-events',
                                status_event_families=tuple(_lower_status_event_families([], []))))
    family = rules.status_event_family('OnBeforeBeingBreak')
    assert family is not None and family.callback_count == 0
    assert family.source_basis == 'runtime_event_protocol'
    assert family.default_scope_kind == 'being_hit_target_local'
    state = BattleState(units={
        'attacker': UnitState('attacker', 'ally', 'fixture:attacker'),
        'target': UnitState('target', 'enemy', 'fixture:target'),
    })
    dispatch = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules)))
    event = GameEvent('toughness.hit', source_id='attacker', target_id='target',
                      payload={'callback_events': ['OnBeforeBeingBreak']})
    known = dispatch.dispatch_event(state, event=event)
    assert not known.errors and not known.mutations and known.after_state == state
    for invalid in (replace(event, event_type='damage.hit'),
                    replace(event, payload={'callback_events': ['OnUnknownBreak']})):
        rejected = dispatch.dispatch_event(state, event=invalid)
        assert rejected.errors and not rejected.mutations and rejected.after_state == state


def test_existing_invalid_template_retains_its_parameter_gap_and_scope():
    from hsr.simulator_v8_clean_core.tbgd.character_control_flow_contracts import (
        _TemplateDraft, _TemplateProblem, _template_parameters, _template_references_for_node,
    )
    relative = 'Config/ConfigAbility/Avatar/Avatar_SilverWolf999_00_Ability.json'
    raw = json.loads((Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main' / relative).read_text())
    template = raw['GlobalTemplates'][1]
    path = '$.GlobalTemplates[1]'
    parameters, reason = _template_parameters(template, path)
    assert not parameters and reason == 'dynamic_float_read_info_invalid'
    problem = _TemplateProblem('template_parameter_invalid', relative, path, 'a' * 64,
                               reason, template['Name'], 'document_global', '$')
    shared = _TemplateDraft('shared', template['Name'], 'shared_global', '$',
                            '$.TaskListTemplate[0].TaskList', 'shared.json', (), (), 'b' * 64)
    reference, = _template_references_for_node('caller', 'IncludeTaskListTemplate',
        {'Name': template['Name']}, source_path=relative, node_path='$.AbilityList[10].OnStart[4]',
        content_sha256='a' * 64, drafts=(shared,), problems=(problem,))
    assert reference.coverage_status == 'blocked' and not reference.resolved_template_id
    assert reference.blocked_reason == f'control_flow_template_invalid:{template["Name"]}:{reason}'
    assert not reference.candidate_template_ids
    reference, = _template_references_for_node('caller', 'IncludeTaskListTemplate',
        {'Name': template['Name']}, source_path='other.json', node_path='$.AbilityList[0].OnStart[0]',
        content_sha256='a' * 64, drafts=(shared,), problems=(problem,))
    assert reference.coverage_status == 'lowered' and reference.resolved_template_id == 'shared'


def test_repeated_status_template_calls_keep_distinct_identity_and_real_source():
    from hsr.simulator_v8_clean_core.tbgd.lowering import _task_list_template_bindings
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    relative = 'Config/ConfigAbility/Activity/Activity_Fate_Ability.json'
    modifier_name = 'MActivity_Fate_SaberBE_Base_Avatar'
    modifier_path = f'$.AbilityList[19].Modifiers.{modifier_name}'
    modifier = json.loads((root / relative).read_text())['AbilityList'][19]['Modifiers'][modifier_name]
    callback = modifier['_CallbackList'][2]
    lowered = TBGDLowering(root)._lower_status_callback_tasks(
        callback['CallbackConfig'], relative=relative, map_name='Modifiers',
        modifier_name=modifier_name, callback_id='source:callback',
        event=callback['Event'], callback_index=39,
        task_list_json_path=f'{modifier_path}._CallbackList[2].CallbackConfig',
        queue_priority_lookup={}, task_templates=_task_list_template_bindings(
            modifier['TaskListTemplate'], json_path=f'{modifier_path}.TaskListTemplate', scope='modifier'),
    )
    for items, key in ((lowered.effects, 'effect_id'), (lowered.conditions, 'condition_id'),
                       (lowered.status_callback_tasks, 'task_id')):
        assert len(merge_identical_ir_items(items, key, item_kind=key)) == len(items)
    healing = [task for task in lowered.status_callback_tasks if task.opcode == 'HealHP']
    assert len(healing) == len({task.parent_task_id for task in healing}) == 3
    assert {task.source.evidence['json_path'] for task in healing} == {
        f'{modifier_path}.TaskListTemplate[0].TaskList[1]'}
    assert len({task.task_path for task in healing}) == 3
    nested = [task for task in lowered.status_callback_tasks
              if task.source.evidence['json_path'] ==
              f'{modifier_path}.TaskListTemplate[0].TaskList[0].SuccessTaskList[0]']
    assert len(nested) == 3 and all(task.opcode == 'SetDynamicValue' for task in nested)


def test_status_sources_outside_the_formal_catalog_remain_blocked_and_auditable():
    from hsr.simulator_v8_clean_core.tbgd.character_ability_scope import build_character_ability_raw_snapshot
    from hsr.simulator_v8_clean_core.rules.ir import build_external_task_topology_dependency_ledger
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    relative = 'Config/ConfigAbility/Avatar/Avatar_AetherDivide_Common_Ability.json'
    builder = TBGDLowering(root)
    builder._character_ability_raw_snapshot = build_character_ability_raw_snapshot(root,
        source_paths=('Config/ConfigAbility/Avatar/Avatar_Asta_00_Ability.json',))
    lowered = builder._lower_ability_file(root / relative, {}, ability_file_order=0)
    assert lowered.status_callbacks and lowered.status_callback_tasks
    assert any(task.parent_task_id or task.child_task_ids for task in lowered.status_callback_tasks)
    assert all(callback.source_mode == 'mainline_unadmitted'
               and callback.coverage_status == callback.admission_status == 'blocked'
               and callback.blocked_reason == callback.blocking_dependency
               == 'character_ability_source_outside_formal_catalog'
               and callback.source.source_path == relative
               for callback in lowered.status_callbacks)
    ledger = build_external_task_topology_dependency_ledger(action_ability_bindings=(),
        ability_phases=(), ability_tasks=(), standalone_ability_graphs=(),
        status_callbacks=lowered.status_callbacks, status_callback_tasks=lowered.status_callback_tasks)
    assert {item.task_id for item in ledger} == {task.task_id for task in lowered.status_callback_tasks}
    assert all(item.source.source_path == relative for item in ledger)


def test_blocked_external_status_call_does_not_register_a_character_root():
    from hsr.simulator_v8_clean_core.rules.ir import StandaloneAbilityGraphIR
    from hsr.simulator_v8_clean_core.tbgd.lowering import _status_trigger_ability_phase_roots
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    relative = 'Config/ConfigAbility/Avatar/Avatar_AetherDivide_Common_Ability.json'
    lowered = TBGDLowering(root)._lower_ability_file(root / relative, {}, ability_file_order=0)
    task = next(task for task in lowered.status_callback_tasks if task.opcode == 'TriggerAbility')
    owner = next(owner for owner in lowered.status_callbacks if owner.callback_id == task.callback_id)
    assert task.coverage_status == 'blocked'
    graph = StandaloneAbilityGraphIR('camera', 'camera', 'mainline_avatar', (), (), (),
        IRSource('Config/ConfigAbility/BattleEventAbility.json', 'AbilityList', 'camera'), 'blocked', 'fixture')
    task = replace(task, linked_standalone_graph_id=graph.standalone_ability_graph_id)
    assert not _status_trigger_ability_phase_roots({}, {'camera': graph}, {}, [task], [owner])
    with pytest.raises(ValueError, match='outside character scope'):
        _status_trigger_ability_phase_roots({}, {'camera': graph}, {},
            [replace(task, coverage_status='executable', blocked_reason='')],
            [replace(owner, coverage_status='executable', admission_status='executable',
                     blocked_reason='', blocking_dependency='')])


@pytest.mark.parametrize('kind', ['ability', 'status'])
def test_trigger_linking_merges_identical_effects_and_rejects_real_collisions(kind):
    from hsr.simulator_v8_clean_core.rules.ir import EffectIR
    from hsr.simulator_v8_clean_core.tbgd.lowering import (
        _link_trigger_ability_graphs, _link_status_trigger_ability_graphs,
    )
    effect = EffectIR('effect', 'TriggerAbility', {'standard': {'ability_name': 'child'}},
                      IRSource('fixture.json', 'TriggerAbility', 'child'), 'blocked')
    effects = [effect, replace(effect)]
    def link(items):
        return (_link_trigger_ability_graphs([], items, [], []) if kind == 'ability'
                else _link_status_trigger_ability_graphs([], [], items, []))
    assert link(effects) == []
    with pytest.raises(IRIdentityConflictError):
        link([effect, replace(effect, payload={'standard': {'ability_name': 'other'}})])


def test_real_multi_modifier_operand_stays_typed_and_blocked():
    from hsr.simulator_v8_clean_core.rules.expression_ir import NumericOperandIR
    relative = 'Config/ConfigAbility/Level/Level_RogueBuff_Ability_4.json'
    raw = json.loads((Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main' / relative).read_text())
    task = raw['AbilityList'][14]['Modifiers']['StageAbility_612054_Modifier_Sub2']['_CallbackList'][0]['CallbackConfig'][0]
    payload = _effect_payload(task, 'SetDynamicValueByMultiModifierValueSum', 'StageAbility_612054_Modifier_Sub2')
    operand = NumericOperandIR.from_json(payload['standard']['dynamic_operation']['operand'])
    assert operand.operand_kind == 'modifier_value'
    assert operand.coverage_status == 'blocked' and operand.blocked_reason == 'operand_producer_not_closed:modifier_value'
    assert operand.parameters['source_target_alias'] == 'ModifierOwnerEntity'
    assert operand.parameters['modifier_value_name'] == 'Amount'
    with pytest.raises(ValueError, match='parameter schema'):
        replace(operand, parameters={})


def test_nested_loop_and_callback_invocations_preserve_the_actual_execution_path():
    from hsr.simulator_v8_clean_core.core.model import BattleState
    from hsr.simulator_v8_clean_core.systems.ability import _task_graph_execution_path
    from hsr.simulator_v8_clean_core.systems.task_graph import (
        TaskGraphContinuation, TaskGraphCountResult, TaskGraphExecutionContext,
        TaskGraphExecutionHooks, TaskGraphExecutor, TaskGraphLeafResult,
    )
    from hsr.simulator_v8_clean_core.tools.validate_p9_s8b2_atomic_executor_core import _graph
    graph = _graph('nested', {
        'outer': {'kind': 'loop', 'termination': 'count_expression', 'branches': [('task_list', '', ('inner',))]},
        'inner': {'kind': 'loop', 'termination': 'count_expression', 'branches': [('task_list', '', ('leaf',))]},
        'leaf': {'kind': 'leaf'},
    }, ('outer',))
    child = _graph('callback', {'callback': {'kind': 'leaf'}}, ('callback',))
    paths, child_paths = [], []

    def child_leaf(request, _state):
        child_paths.append(_task_graph_execution_path(request))
        return TaskGraphLeafResult('resolved')

    def leaf(request, state):
        paths.append(_task_graph_execution_path(request))
        context = TaskGraphContinuation.from_hook_request(request).child_context('callback')
        result = TaskGraphExecutor().execute(state, child, context, TaskGraphExecutionHooks(leaf=child_leaf))
        assert result.ok, result.errors
        return TaskGraphLeafResult('resolved')

    result = TaskGraphExecutor().execute(BattleState(), graph, TaskGraphExecutionContext('nested'),
        TaskGraphExecutionHooks(leaf=leaf, count=lambda *_: TaskGraphCountResult('resolved', 2)))
    assert result.ok, result.errors
    assert len(paths) == len(set(paths)) == len(child_paths) == len(set(child_paths)) == 4
    assert all(parent in path for parent, path in zip((p.rsplit('/task:leaf', 1)[0] for p in paths), child_paths))


def test_source_inventory_covers_every_released_character_including_memory_and_elation():
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    rows = {path: json.loads((root / path).read_text())
            for path in (*AVATAR_CONFIG_TABLES, AVATAR_ENHANCED_CONFIG_TABLE, SERVANT_CONFIG_TABLE)}
    released = {str(row['AvatarID']) for path in AVATAR_CONFIG_TABLES
                for row in rows[path] if row['Release']}
    candidates = _discover_source_candidates_from_rows(rows)
    assert {item.avatar_id for item in candidates if item.source_kind == 'character_main'} == released
    assert all((root / item.relative_path).is_file() for item in candidates)
    assert {'Memory', 'Elation'} <= {item.base_type for item in candidates}


def test_elation_source_kind_is_preserved_and_unknown_kinds_still_fail_closed():
    assert _action_kinds({'AttackType': 'ElationDamage'}, {'SkillType': 'Elation'}) == ('elation',)
    with pytest.raises(CharacterAbilitySourceGraphPlanMismatch):
        _action_kinds({'AttackType': 'Unknown'}, {})


def test_real_unsupported_entity_filter_is_blocked_with_its_exact_source():
    relative = 'Config/ConfigAbility/Monster/Monster_W4_DawnsEye_01_Ability.json'
    path = '$.AbilityList[19].OnStart[4].SuccessTaskList[0].TargetType.Sequence[1]'
    raw = json.loads((Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main' / relative).read_text())
    raw = raw['AbilityList'][19]['OnStart'][4]['SuccessTaskList'][0]['TargetType']['Sequence'][1]
    source = IRSource(relative, 'TargetFilter', 'source:filter', {'json_path': path})
    node = _target_expression_execution_node(raw, source)
    assert node.expression_kind == 'TargetUnsupported'
    assert node.runtime_blocked_reason == 'target_entity_type_filter_invalid'
    assert node.source.source_path == relative and node.source.evidence['json_path'] == path
    assert TargetExpressionNodeIR.from_json(node.to_json()) == node


@pytest.mark.parametrize('predicate, reason', [
    ({'$type': 'RPG.GameCore.ByTargetEntityType', 'EntityTypeMask': 'Servant', 'Inverse': 1}, 'target_entity_type_filter_invalid'),
    ({'$type': 'RPG.GameCore.ByTargetAliveState', 'AliveStateMask': 'unknown'}, 'target_alive_state_mask_invalid'),
    ({'$type': 'RPG.GameCore.ByIsTargetUnselectable', 'Inverse': 'false'}, 'target_unselectable_inverse_invalid'),
])
def test_malformed_special_filter_does_not_reach_executable_ir(predicate, reason):
    source = IRSource('fixture.json', 'TargetFilter', 'filter', {'json_path': '$.Target'})
    node = _target_expression_execution_node({'$type': 'RPG.GameCore.TargetFilter', 'Predicate': predicate}, source)
    assert node.runtime_blocked_reason == reason


def test_admitted_entity_filter_still_builds_typed_ir():
    source = IRSource('fixture.json', 'TargetFilter', 'filter', {'json_path': '$.Target'})
    raw = {'$type': 'RPG.GameCore.TargetFilter', 'Predicate': {
        '$type': 'RPG.GameCore.ByTargetEntityType', 'EntityTypeMask': 'Servant', 'Inverse': False,
    }}
    node = _target_expression_execution_node(raw, source)
    assert node.expression_kind == 'TargetFilterEntityType' and not node.runtime_blocked_reason


def test_invalid_pipeline_mask_retains_a_typed_blocker():
    source = IRSource('fixture.json', 'TargetFilterAliveState', 'filter', {'json_path': '$.Target.Sequence[1]'})
    raw = {'$type': 'RPG.GameCore.TargetFilterAliveState', 'Mask': 'Mask_Disposed'}
    node = _target_expression_execution_node(raw, source)
    assert node.expression_kind == 'TargetUnsupported'
    assert node.runtime_blocked_reason == 'target_alive_state_mask_invalid'
    assert node.source.evidence['json_path'] == '$.Target.Sequence[1]'
    assert TargetExpressionNodeIR.from_json(node.to_json()) == node
    raw['Mask'] = 'Mask_AliveOnly'
    assert _target_expression_execution_node(raw, source).runtime_blocked_reason == ''


def test_nested_target_reason_survives_outer_condition_metadata():
    source = IRSource('fixture.json', 'ByAny', 'condition', {'json_path': '$.Predicate'})
    nested_source = replace(source, raw_id='condition:PredicateList[0].TargetType',
                            evidence={'json_path': '$.Predicate.PredicateList[0].TargetType'})
    target = TargetExpressionNodeIR.build('TargetUnsupported', nested_source,
                                        {'original_kind': 'Unknown', 'blocked_reason': 'target_source_missing'})
    payload = {'PredicateList': [{'schema_version': CONDITION_EXPRESSION_NODE_SCHEMA,
                                'supported': False, 'blocked_reason': 'condition_not_admitted:Unknown',
                                'TargetType': target}]}
    reason = _condition_payload_target_blocked_reason(payload)
    assert reason == 'target_source_missing'
    condition = ConditionIR('condition', 'ByAny', payload, source, 'blocked',
                            CONDITION_EXPRESSION_NODE_SCHEMA, reason)
    assert ConditionIR.from_json(condition.to_json()) == condition
    with pytest.raises(ValueError, match='nested target reason'):
        replace(condition, blocked_reason='condition_not_admitted:Unknown')


def test_real_sibling_condition_gap_cannot_hide_a_later_nested_target_gap():
    relative = 'Config/ConfigAbility/Monster/Monster_W2_Kafka_00_IFEX_Ability.json'
    path = '$.AbilityList[11].OnStart[8].ParallelAbilityList[5].Predicate'
    raw = json.loads((Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main' / relative).read_text())
    raw = raw['AbilityList'][11]['OnStart'][8]['ParallelAbilityList'][5]['Predicate']
    source = IRSource(relative, 'ByAnd', 'source:condition', {'json_path': path})
    condition = _condition_ir_from_typed_target_predicate(raw, source)
    assert condition.coverage_status == 'blocked'
    assert condition.blocked_reason == 'target_expression_kind_not_typed:TargetFetchMonsterByID'
    assert ConditionIR.from_json(condition.to_json()) == condition


def test_route_uses_typed_action_definition_without_an_audit_entity():
    definition = ActionDefinitionIR('action:level1', 'avatar_skill:fixture', 1,
        'Normal', 'SingleAttack', 'single_enemy', 0, 1, 20, 0, (), (), (), None,
        IRSource('fixture.json', 'Skill', 'fixture', {}))
    rules = RuleBook(CanonicalIR('fixture', action_definitions=(definition,)))
    route = (RouteStepSpec('actor', definition.action_id, 1, ('target',)),)
    result = IdentityResolver(rules).validate(ScenarioSpec('fixture', '1', (), route))
    assert not any('action' in error for error in result.errors), result.errors
    missing = replace(route[0], action_level=2)
    result = IdentityResolver(rules).validate(ScenarioSpec('fixture', '1', (), (missing,)))
    assert any('unknown action definition' in error for error in result.errors)
    with pytest.raises(IRIdentityConflictError):
        merge_identical_ir_items((definition, replace(definition, bp_add=2)), 'definition_id')


@pytest.mark.integration
def test_formal_compilation_keeps_source_gaps_and_blocks_their_graph_queries():
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    builder = TBGDLowering(root)
    ir = builder.build(avatar_ids=frozenset({'1005'}), monster_ids=frozenset(),
                       stage_ids=frozenset(), include_equipment=False)
    rules = RuleBook(ir)
    catalog = ir.task_graph_catalog
    blocked = [entry for entry in catalog.entry_materializations if entry.status == 'blocked']
    assert blocked
    for entry in blocked:
        query = rules.query_formal_task_graph(entry.entry_kind, entry.owner_id,
                                             entry.callback_kind, entry.formal_task_ids)
        assert query.status == 'blocked' and query.value is None
    deferred = [node for graph in catalog.graphs for node in graph.nodes
                if node.opcode == 'Retarget' and any(ref.reference_kind == 'target'
                   and ref.resolution_status != 'resolved' for ref in node.references)]
    assert deferred and all(node.materialization_status == 'deferred' for node in deferred)
    control = builder.build_character_control_flow_contract_catalog()
    assert control.issues
    assert ir.metadata['character_task_graph']['source_issues'] == [issue.to_json() for issue in control.issues]
    assert all(item.disposition == 'blocked' and not item.formal_materialization_ids
               for item in catalog.source_dispositions
               if item.source_record_id in {node.node_id for node in
                  control.nodes if node.coverage_status == 'blocked'})
    relative = 'Config/ConfigAbility/Avatar/Assistant/Avatar_Asta_00_Assistant.json'
    graphs, *parts = builder._lower_standalone_ability_graphs([root / relative])
    assert graphs and all(graph.coverage_status == 'blocked' and not graph.phase_ids
                         and graph.blocked_reason == 'character_ability_source_outside_formal_catalog'
                         and graph.source.source_path == relative for graph in graphs)
    assert not any(parts)
