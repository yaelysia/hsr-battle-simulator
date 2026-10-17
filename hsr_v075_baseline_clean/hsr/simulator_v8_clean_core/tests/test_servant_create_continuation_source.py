"""Two real creation callbacks keep their ordered, independently admitted tasks."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from hsr.simulator_v8_clean_core.rules.ir import ActionDefinitionIR, AbilityPhaseIR, CanonicalIR, IRSource
from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering, _effect_payload, _dedupe_target_expressions
from hsr.simulator_v8_clean_core.tbgd.target_source import close_target_expression_language
from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import materialize_ability_phase_task_graph


def _source_graph(directory, name, template_index, create_index, *, unknown_child=False):
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    identity = 1413 if name == 'Evernight_00' else 8007
    relative = f'Config/ConfigAbility/Avatar/Avatar_{name}_Ability.json'
    raw = json.loads((root / relative).read_text())
    create = raw['GlobalTemplates'][template_index]['TaskList'][0]['SuccessTaskList'][create_index]
    if unknown_child:
        create['OnServantCreate'].append({'$type': 'RPG.GameCore.UnknownCreationEffect'})
    for table in ('AvatarConfig', 'AvatarConfigLD', 'AvatarConfigEnhanced', 'AvatarServantConfig'):
        rows = json.loads((root / f'ExcelOutput/{table}.json').read_text()) if table == 'AvatarConfig' else []
        path = directory / f'ExcelOutput/{table}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([row for row in rows if row.get('AvatarID') == identity]))
    for file in (relative, 'Config/ConfigAbility/Avatar/Avatar_Common_Ability.json',
                 'Config/GlobalConfig/TargetAliasConfig.json', 'Config/GlobalConfig/TargetOperationConfig.json',
                 'Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json'):
        path = directory / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((root / file).read_bytes())
    if unknown_child:
        (directory / relative).write_text(json.dumps(raw))
    lowerer = TBGDLowering(directory)
    catalog = lowerer.build_character_control_flow_contract_catalog()
    context = lowerer._character_formal_task_source_context()
    json_path = f'$.GlobalTemplates[{template_index}].TaskList[0].SuccessTaskList[{create_index}]'
    definition = ActionDefinitionIR('validation:spawn', 'validation:spawn', 1, 'BPSkill',
        'Support', 'single', 0, 0, 0, 0, (), (), (), None, IRSource(relative, 'validation', name))
    lowered = lowerer._lower_ability_task_tree(create, definition=definition, phase_id='phase',
        ability_name='validation:creation-entry', ability_path=relative, ability_index=None,
        callback_kind='OnStart', task_index=0, task_path='OnStart[0]', branch='root', parent_task_id='',
        formal_source_context=context, source_json_path=json_path)
    legacy = lowerer._lower_ability_task_tree(create, definition=definition, phase_id='phase',
        ability_name='validation:creation-entry', ability_path=relative, ability_index=None,
        callback_kind='OnStart', task_index=0, task_path='OnStart[0]', branch='root', parent_task_id='',
        source_json_path=json_path)
    assert legacy.ability_tasks[0].coverage_status == 'blocked'
    assert legacy.ability_tasks[0].blocked_reason == 'servant_create_callback_requires_formal_task_graph'
    parent = lowered.ability_tasks[0]
    assert parent.opcode == 'CreateServant' and parent.coverage_status == 'executable', parent.blocked_reason
    effect = next(row for row in lowered.effects if row.effect_id == parent.effect_id)
    assert effect.coverage_status == 'executable' and 'OnServantCreate' not in effect.payload
    assert effect.payload['standard']['creation_callback_required'] is True
    control = context.control_by_location[(relative, json_path, 'CreateServant')]
    assert control.control_role == 'servant_creation_continuation'
    assert len(control.branches) == 1 and control.branches[0].branch_kind == 'servant_created'
    assert [row.family for row in control.branches[0].children] == [
        row['$type'].rsplit('.', 1)[-1] for row in create['OnServantCreate']]
    language = lowerer._strict_target_language_definitions()
    expressions = tuple(_dedupe_target_expressions([
        close_target_expression_language(row, language) for row in lowered.target_expressions]).values())
    phase = AbilityPhaseIR('phase', 'binding', definition.action_id, 1, 'validation:creation-entry',
        0, {}, {}, {}, parent.source, task_ids=tuple(row.task_id for row in lowered.ability_tasks),
        invocation_role='action_root')
    canonical = CanonicalIR('servant-create-source-check', action_definitions=(definition,),
        ability_phases=(phase,), ability_tasks=tuple(lowered.ability_tasks), effects=tuple(lowered.effects),
        conditions=tuple(lowered.conditions), target_expressions=expressions + tuple(row.expression for row in language))
    graphs = materialize_ability_phase_task_graph(catalog, canonical, phase_id='phase',
        callback_kind='OnStart', source_snapshot=lowerer._character_ability_raw_snapshot)
    assert len(graphs.graphs) == 1, [row.blocked_reason for row in graphs.entry_materializations]
    graph = graphs.graphs[0]
    nodes = {row.graph_node_id: row for row in graph.nodes}
    tasks = {row.task_id: row for row in lowered.ability_tasks}
    parent_node = next(row for row in graph.nodes if row.formal_task_id == parent.task_id)
    assert graph.root_node_ids == (parent_node.graph_node_id,)
    assert parent_node.node_kind == 'sequence' and parent_node.materialization_status == 'materialized'
    children = parent_node.branches[0].child_node_ids
    assert [tasks[nodes[child].formal_task_id].source.evidence['json_path'] for child in children] == [
        f'{json_path}.OnServantCreate[{index}]' for index in range(len(create['OnServantCreate']))]
    assert all(not task.parent_task_id and not task.child_task_ids for task in lowered.ability_tasks)
    if unknown_child:
        unknown = tasks[nodes[children[-1]].formal_task_id]
        assert unknown.opcode == 'UnknownCreationEffect' and unknown.coverage_status == 'blocked'
        assert nodes[children[-1]].references[0].resolution_status == 'deferred'
    return create, parent.source


def test_real_servant_creation_callbacks_preserve_order_and_unknown_child_admission():
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        for name, template, create_index in (('Evernight_00', 7, 0), ('PlayerBoy_30', 0, 1)):
            create, source = _source_graph(directory / name, name, template, create_index)
            for invalid in (None, {}, [7], [{}]):
                payload = _effect_payload({**create, 'OnServantCreate': invalid}, 'CreateServant', '', source=source)
                assert payload['standard']['blocked_reason'] == 'servant_create_fields_not_admitted'
            payload = _effect_payload({**create, 'UnexpectedCreationField': True}, 'CreateServant', '', source=source)
            assert payload['standard']['blocked_reason'] == 'servant_create_fields_not_admitted'
            for unchanged in ({key: value for key, value in create.items() if key != 'OnServantCreate'},
                              {**create, 'OnServantCreate': []}):
                payload = _effect_payload(unchanged, 'CreateServant', '', source=source)
                assert not payload['standard']['blocked_reason']
                assert payload['standard']['creation_callback_required'] is False
        _source_graph(directory / 'unknown', 'PlayerBoy_30', 0, 1, unknown_child=True)
