"""A real bounce action lowers through its counted loop and shared template."""
import json
from pathlib import Path

from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR
from hsr.simulator_v8_clean_core.tbgd.character_cards import (
    _bounce_policy_from_row, skill_formula_bindings_from_row,
)
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering, _admit_damage_ability_tasks, _lower_action_execution_ir,
    _lower_damage_emissions, _lower_toughness_emissions, _link_trigger_ability_graphs,
    _dedupe_target_expressions,
)
from hsr.simulator_v8_clean_core.tbgd.target_source import close_target_expression_language
from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import materialize_ability_phase_task_graph


def test_real_bounce_action_keeps_template_parameters_loop_and_two_damage_requests(tmp_path):
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    avatar = next(row for row in json.loads((root / 'ExcelOutput/AvatarConfig.json').read_text())
                  if row['AvatarID'] == 1009)
    skill = next(row for row in json.loads((root / 'ExcelOutput/AvatarSkillConfig.json').read_text())
                 if row['SkillID'] == 100902 and row['Level'] == 1)
    tables = {'AvatarConfig': [avatar], 'AvatarSkillConfig': [skill], 'AvatarConfigLD': [],
              'AvatarConfigEnhanced': [], 'AvatarServantConfig': []}
    for name, rows in tables.items():
        path = tmp_path / f'ExcelOutput/{name}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows))
    # The mini inventory retains exact source files, including the common
    # template body. It never calls TBGDLowering.build or scans other characters.
    files = ('Config/ConfigCharacter/Avatar/Avatar_Asta_00_Config.json',
             'Config/ConfigAbility/Avatar/Avatar_Asta_00_Ability.json',
             'Config/ConfigAbility/Avatar/Camera/Avatar_Asta_00_Camera.json',
             'Config/ConfigAbility/Avatar/Avatar_Common_Ability.json',
             'Config/GlobalConfig/TargetAliasConfig.json',
             'Config/GlobalConfig/TargetOperationConfig.json',
             'Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json')
    for relative in files:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((root / relative).read_bytes())
    lowerer = TBGDLowering(tmp_path)
    source_catalog = lowerer.build_character_control_flow_contract_catalog()
    definition = lowerer._lower_action_definitions(
        action_ids=frozenset({'avatar_skill:100902'}), entity_types=frozenset({'avatar_skill'}),
    )[0]
    binding, phases, lowered = lowerer._avatar_action_binding(definition)
    assert binding.coverage_status == 'executable', binding.blocked_reason
    assert {phase.ability_name for phase in phases if phase.task_ids} == {
        'Avatar_Asta_00_Skill02_Phase01', 'Avatar_Asta_00_Skill02_Phase02',
    }
    tasks = _link_trigger_ability_graphs(lowered.ability_tasks, lowered.effects, [], phases)
    keywords = dict(relative_path='ExcelOutput/AvatarSkillConfig.json', entity_type='avatar_skill',
                    id_key='SkillID', row_index=0, row=skill,
                    text_map=json.loads((root / 'TextMap/TextMapCHS.json').read_text()),
                    skill_to_card={'100902': 'character_data_card:avatar:1009'})
    formulae = skill_formula_bindings_from_row(**keywords)
    policy = _bounce_policy_from_row(**keywords)
    _, profiles = _lower_action_execution_ir([definition], [binding], phases, formulae, [policy])
    damage = _lower_damage_emissions(tasks, lowered.effects, profiles, formulae, {})
    toughness = _lower_toughness_emissions(tasks, lowered.effects, profiles, formulae)
    tasks = _admit_damage_ability_tasks(tasks, damage, toughness, profiles)
    damage_tasks = [task for task in tasks if task.opcode == 'DamageByAttackProperty']
    assert len(damage_tasks) == len(damage) == len(toughness) == 2
    assert all(task.coverage_status == 'executable' and not task.blocked_reason for task in damage_tasks), [
        (task.task_path, task.blocked_reason) for task in damage_tasks]
    control = [task for task in tasks if task.opcode in {
        'LoopExecuteTaskList', 'IncludeTaskListTemplate', 'TaskTemplateFetchParamSequence'}]
    assert {task.opcode for task in control} == {
        'LoopExecuteTaskList', 'IncludeTaskListTemplate', 'TaskTemplateFetchParamSequence'}
    assert all(task.coverage_status == 'executable' and not task.blocked_reason for task in control)
    include = next(task for task in control if task.opcode == 'IncludeTaskListTemplate')
    language = lowerer._strict_target_language_definitions()
    expressions = tuple(_dedupe_target_expressions(
        [close_target_expression_language(row, language) for row in lowered.target_expressions]).values())
    target = next(row for row in expressions if row.target_expression_id == include.target_expression_id)
    assert target.alias == 'AllEnemy' and include.target_expression_id.endswith(':template_parameters')
    assert not target.node.runtime_blocked_reason
    canonical = CanonicalIR('bounce-source-check', action_definitions=(definition,),
        action_ability_bindings=(binding,), ability_phases=tuple(phases), ability_tasks=tuple(tasks),
        effects=tuple(lowered.effects), conditions=tuple(lowered.conditions), hit_profiles=tuple(profiles),
        skill_formula_bindings=tuple(formulae), damage_emissions=tuple(damage),
        toughness_emissions=tuple(toughness),
        target_expressions=expressions + tuple(row.expression for row in language))
    graphs = {}
    for phase in phases:
        if not phase.task_ids:
            continue
        catalog = materialize_ability_phase_task_graph(source_catalog, canonical,
            phase_id=phase.phase_id, callback_kind='OnStart',
            source_snapshot=lowerer._character_ability_raw_snapshot)
        assert len(catalog.graphs) == 1, [row.blocked_reason for row in catalog.entry_materializations]
        graph = catalog.graphs[0]
        assert all(node.materialization_status == 'materialized' for node in graph.nodes), [
            (node.source_family, node.status_reason) for node in graph.nodes if node.materialization_status != 'materialized']
        graphs[phase.ability_name] = graph
    graph = graphs['Avatar_Asta_00_Skill02_Phase02']
    loop = next(node for node in graph.nodes if node.source_family == 'LoopExecuteTaskList')
    assert loop.termination_kind == 'count_expression' and loop.termination_numeric_definition_id
    count = next(row for row in graph.numeric_definitions if row.definition_id == loop.termination_numeric_definition_id)
    assert count.expression['kind'] == 'dynamic_hash' and str(count.expression['hash']) == '-2146792706'
    template = next(node for node in graph.nodes if node.source_family == 'IncludeTaskListTemplate')
    assert any(row.reference_kind == 'target' and row.definition_id == target.target_expression_id
               for row in template.references)
