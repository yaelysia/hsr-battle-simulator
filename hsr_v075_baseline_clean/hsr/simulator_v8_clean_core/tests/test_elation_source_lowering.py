"""Real point tasks and ElationDamagePercentage use their own canonical inputs."""
import json
import math
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from hsr.simulator_v8_clean_core.rules.ability_properties import ability_property_stat_name
from hsr.simulator_v8_clean_core.rules.ir import ActionDefinitionIR, HitProfileIR, IRSource
from hsr.simulator_v8_clean_core.rules.task_graph import TaskGraphTemplateParameterIR
from hsr.simulator_v8_clean_core.tbgd.character_control_flow_contracts import _discover_shared_templates, _template_ir
from hsr.simulator_v8_clean_core.tbgd.expression_lowering import lower_numeric_expression
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering, _effect_coverage_status, _effect_payload, _lower_damage_emissions,
    _normalized_equipment_task, _status_damage_emission_from_task,
    _queue_intent_from_task, _attach_target_expressions_to_effect_payload,
)
from hsr.simulator_v8_clean_core.tbgd.target_source import close_target_expression_language
from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import _materialize_template_parameters


ROOT = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'


def _document(relative):
    return json.loads((ROOT / relative).read_text())


def test_real_elation_operations_and_ratio_do_not_reuse_skill_points_or_attack():
    avatar_path = 'Config/ConfigAbility/Avatar/Avatar_YaoGuang_00_Ability.json'
    avatar = _document(avatar_path)
    stage = _document('Config/ConfigAbility/BattleEvent/StageAbility_Elation.json')
    shared = _document('Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json')
    equipment = _document('Config/ConfigAbility/Equip/Equip42.json')
    relic = _document('Config/ConfigAbility/Equip/Equip40.json')
    cases = (
        (avatar['AbilityList'][6]['OnStart'][3], 'add_points'),
        (equipment['AbilityList'][1]['Modifiers']['MEquip_23057_Main']['_CallbackList'][1]['CallbackConfig'][0]['SuccessTaskList'][1], 'add_points'),
        (relic['AbilityList'][4]['Modifiers']['MRelic_129_Main']['_CallbackList'][0]['CallbackConfig'][0], 'read_points'),
        (stage['AbilityList'][5]['OnStart'][5]['FailedTaskList'][0], 'set_points'),
        (stage['GlobalModifiers']['MLevel_Elation_Common']['OnElationPointChange'][0]['OnChange'][0], 'read_points'),
        (shared['TaskListTemplate'][49]['TaskList'][0]['TaskList'][0], 'convert_echo'),
    )
    for raw, expected in cases:
        for equipment_scope in (False, True):
            opcode, task, evidence = _normalized_equipment_task(raw['$type'], raw, equipment_source_admitted=equipment_scope)
            assert opcode == 'ElationOperation' and task == raw
            assert evidence['schema_alias_raw_opcode'] == raw['$type']
            payload = _effect_payload(task, opcode, '')
            assert payload['standard']['elation_operation'] == expected
            assert _effect_coverage_status(opcode, payload) == 'executable'
            assert 'skill_points' not in json.dumps(payload['standard'])
            invalid = _effect_payload({**task, 'UnknownPointBehavior': True}, opcode, '')
            assert _effect_coverage_status(opcode, invalid) == 'blocked'
        if expected == 'read_points':
            assert payload['standard']['target_alias'] == 'ModifierOwnerEntity'
            assert payload['standard']['point_type'] == ('base' if raw.get('PICEOEEKCIN') == 'BasePoint' else 'effective')
            assert payload['standard']['destination_dynamic_key'] == raw['FHLJGDGMMHK']
        if expected == 'convert_echo':
            assert payload['standard']['target_alias'] == 'ModifierOwnerEntity'
            assert payload['standard']['recipient_target_alias'] == raw['HILNFHCPEAD']['Alias'] == 'ParamEntity'
    assert _effect_coverage_status('ElationOperation', _effect_payload(
        {**cases[2][0], 'PICEOEEKCIN': 'UnknownPoint'}, 'ElationOperation', '')) == 'blocked'
    assert ability_property_stat_name('ElationEchoPoint') == 'elation_echo_point'
    assert ability_property_stat_name('ElationDamageExtraAddedRatio') == 'elation_damage_extra_added_ratio'

    lowerer = TBGDLowering(ROOT)
    transitions = lowerer._lower_battle_state_transitions()
    assert len(transitions) == 2 and all(item.participant_team == 'ally' for item in transitions)
    assert all(item.to_json()['participant_team'] == 'ally' for item in transitions)
    stage_lowered = lowerer._lower_ability_file(
        ROOT / 'Config/ConfigAbility/BattleEvent/StageAbility_Elation.json', {}, ability_file_order=0)
    echo_name = 'MBattleEvent_Elation_ElationEchoPointBuff'
    echo_definition = next(item for item in stage_lowered.entities if item.fields.get('modifier_name') == echo_name)
    assert echo_definition.fields['duration_admission']['admission_status'] == 'executable'
    assert echo_definition.fields['life_step_moment'] == 'ModifierPhase1End'
    assert echo_definition.fields['duration_admission']['remaining_duration'] == 2
    assert all(item.coverage_status == 'executable' for item in stage_lowered.status_callbacks
               if item.modifier_name == echo_name)
    assert all(item.coverage_status == 'executable' for item in stage_lowered.status_callback_tasks
               if item.modifier_name == echo_name)
    ranged = [item for item in stage_lowered.status_callbacks
              if item.event == 'OnElationPointChange' and item.modifier_name == 'MLevel_Elation_Common']
    assert len(ranged) == 1 and ranged[0].blocked_reason == 'elation_point_callback_range_or_fields_not_admitted'
    source = IRSource(avatar_path, 'AbilityTask', 'real_elation', {'json_path': '$.AbilityList[8].OnStart[3].FailedTaskList[0]'})
    definition = ActionDefinitionIR('check', 'check', 1, 'Elation', 'AoEAttack', 'aoe',
        0, 0, 0, 0, (), (), (), None, source, damage_formula_family='elation', element_type='Physical')
    raw = avatar['AbilityList'][8]['OnStart'][3]['FailedTaskList'][0]
    lowered = lowerer._lower_ability_task_tree(raw, definition=definition, phase_id='phase',
        ability_name=avatar['AbilityList'][8]['Name'], ability_path=avatar_path, ability_index=8,
        callback_kind='OnStart', task_index=0, task_path='OnStart[3].FailedTaskList[0]', branch='failed',
        parent_task_id='', source_json_path=source.evidence['json_path'])
    profile = HitProfileIR('profile', 'check', 1, 0, 'selected', {}, {}, {}, {}, 'elation',
        'Physical', source, coverage_status='executable')
    emissions = _lower_damage_emissions(lowered.ability_tasks, lowered.effects, [profile], [], {})
    assert len(emissions) == 1 and emissions[0].coverage_status == 'executable', emissions
    emission = emissions[0]
    assert emission.scaling_ratio_expr == lower_numeric_expression(raw['AttackProperty']['ElationDamagePercentage'])
    assert emission.scaling_basis_expr['kind'] == 'elation_level_base'
    assert emission.scaling_basis_expr['elation_point_source'] == 'moment'
    assert 'stat' not in emission.scaling_basis_expr
    language = lowerer._strict_target_language_definitions()
    assert lowered.target_expressions
    for expression in lowered.target_expressions:
        closed = close_target_expression_language(expression, language)
        assert closed.coverage_status == 'executable', closed
    bad_effect = replace(lowered.effects[0], payload={**lowered.effects[0].payload,
        'AttackProperty': {**raw['AttackProperty'], 'OriginalMultiplier': 2}})
    rejected = _lower_damage_emissions(lowered.ability_tasks, [bad_effect], [profile], [], {})
    assert rejected[0].coverage_status == 'blocked' and 'fields_not_admitted' in rejected[0].blocked_reason
    indirect = avatar['GlobalModifiers']['G_MAvatar_YaoGuang_00_Passive_ToMember']['_CallbackList'][2]['CallbackConfig'][0]['SuccessTaskList'][1]['TaskList'][0]
    indirect_source = IRSource(avatar_path, 'StatusCallbackTask', 'real_indirect', {
        'json_path': '$.GlobalModifiers.G_MAvatar_YaoGuang_00_Passive_ToMember._CallbackList[2].CallbackConfig[0].SuccessTaskList[1].TaskList[0]',
    })
    _, indirect_targets = _attach_target_expressions_to_effect_payload({}, indirect,
        effect_id='real_indirect', source=indirect_source, target_language_definitions=language)
    status = _status_damage_emission_from_task(callback_id='callback', task_id='task',
        modifier_name='modifier', event='OnAfterAttack', task=indirect, source=indirect_source,
        target_expressions=tuple(indirect_targets))
    assert status.damage_formula_family == 'elation' and status.scaling_expr['elation_point_source'] == 'echo'
    assert status.coverage_status == 'executable', status.blocked_reason
    assert status.damage_custom_name == 'DamageTag_HongBao'
    assert status.attacker_target_expression_id and status.property_source_target_expression_id
    assert status.element_source_target_expression_id
    turn = stage['AbilityList'][1]['OnStart'][3]['FailedTaskList'][0]
    intent = _queue_intent_from_task(callback_id='callback', task_id='task', event='OnStart',
        opcode='TurnInsertAction', task=turn, source=source, queue_priority_lookup={})
    assert intent.elation_point_override_expr == lower_numeric_expression(turn['OverrideElationPoint'])
    assert intent.to_json()['elation_point_override_expr'] == intent.elation_point_override_expr
    start = stage['AbilityList'][1]['OnStart'][3]['SuccessTaskList'][1]
    start_intent = _queue_intent_from_task(callback_id='callback', task_id='start-task', event='OnStart',
        opcode='TurnInsertAction', task=start, source=source, queue_priority_lookup={})
    assert start_intent.elation_point_override_expr == lower_numeric_expression(
        start['DynamicValues']['ElationTime_OverrideElationPoint'])

    with TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / 'ExcelOutput/ElationBasicLevelDamage.json'
        path.parent.mkdir()
        path.write_bytes((ROOT / 'ExcelOutput/ElationBasicLevelDamage.json').read_bytes())
        formulas = TBGDLowering(root)._lower_elation_mechanics()
        shared_path = root / 'Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json'
        shared_path.parent.mkdir(parents=True)
        shared_path.write_bytes((ROOT / shared_path.relative_to(root)).read_bytes())
        drafts, problems, _, _ = _discover_shared_templates(root)
        assert not problems
        template = _template_ir(next(item for item in drafts if item.name == 'AddElationEchoPoint'), {})
        stage_path = 'Config/ConfigAbility/BattleEvent/StageAbility_Elation.json'
        stage_bytes = (ROOT / stage_path).read_bytes()
        include_source = IRSource(stage_path, 'AbilityTask', 'real_echo_include', {
            'json_path': '$.GlobalModifiers.MBattleEvent_Elation_Passive._CallbackList[8].CallbackConfig[8].FailedTaskList[1]',
            'content_sha256': sha256(stage_bytes).hexdigest(), 'source_opcode': 'IncludeTaskListTemplate'})
        parameters = _materialize_template_parameters(
            SimpleNamespace(source_bytes={stage_path: stage_bytes}), include_source, template)
        assert len(parameters) == 1 and parameters[0].parameter_name == 'AddValue'
        assert parameters[0].destination_hash == '299898218'
        assert TaskGraphTemplateParameterIR.from_json(parameters[0].to_json()) == parameters[0]
    table = next(item for item in formulas if item.kind == 'elation_level_base')
    assert table.coverage_status == 'executable' and len(table.expression['values']) == 101
    assert table.expression['values']['1'] == 108 and table.expression['values']['80'] == 7535.107
    rule = next(item for item in formulas if item.kind == 'elation_multiplier_rule')
    assert rule.source.raw_type == 'AdoptedMechanismRule' and rule.expression['punchline_offset'] == 240


def test_real_owner_elation_status_damage_runs_its_global_before_hit_callback():
    """Real source component; combatants and the initialized ratio slot are typed fixtures."""
    from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, UnitState
    from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
    from hsr.simulator_v8_clean_core.rules.engine_rule_registry import build_engine_rule_registry
    from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR
    from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
    from hsr.simulator_v8_clean_core.systems.effect import EffectRegistry
    from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
    from hsr.simulator_v8_clean_core.systems.status import StatusInstance, StatusSystem
    from hsr.simulator_v8_clean_core.systems.unit_stats import effective_unit_stat
    from hsr.simulator_v8_clean_core.tbgd.lowering import (
        _dedupe_target_expressions, _lower_status_event_families, _synchronize_effect_target_expression_metadata,
    )
    from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import (
        attach_task_graph_catalog, build_complete_task_graph_catalog,
        materialize_status_callback_task_graph, merge_task_graph_slices,
    )

    relative = 'Config/ConfigAbility/Avatar/Avatar_YaoGuang_00_Ability.json'
    modifier = 'G_MAvatar_YaoGuang_00_Passive_ToMember'
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        for table in ('AvatarConfig', 'AvatarConfigLD', 'AvatarConfigEnhanced', 'AvatarServantConfig'):
            rows = [row for row in _document(f'ExcelOutput/{table}.json') if row.get('AvatarID') == 1502]
            path = root / f'ExcelOutput/{table}.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(rows))
        for name in (relative, 'Config/ConfigAbility/Avatar/Avatar_Common_Ability.json',
                     'Config/GlobalConfig/TargetAliasConfig.json', 'Config/GlobalConfig/TargetOperationConfig.json',
                     'Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json'):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / name).read_bytes())
        lowerer = TBGDLowering(root)
        source_catalog = lowerer.build_character_control_flow_contract_catalog()
        lowered = lowerer._lower_ability_file(root / relative, {}, ability_file_order=0,
            formal_status_source_context=lowerer._character_formal_task_source_context())
        definitions = lowerer._strict_target_language_definitions()
        targets = tuple(_dedupe_target_expressions([
            *(close_target_expression_language(row, definitions) for row in lowered.target_expressions),
            *(row.expression for row in definitions),
        ]).values())
        callback = next(row for row in lowered.status_callbacks
            if row.modifier_name == modifier and row.event == 'OnListenBeforeHitAll')
        damage_callback = next(row for row in lowered.status_callbacks
            if row.modifier_name == modifier and row.event == 'OnAfterAttack')
        task = next(row for row in lowered.status_callback_tasks
            if row.callback_id == damage_callback.callback_id and row.opcode == 'DamageByAttackProperty')
        emission = next(row for row in lowered.status_damage_emissions if row.source_task_id == task.task_id)
        definition = next(row for row in lowered.entities if row.fields.get('modifier_name') == modifier)
        assert callback.coverage_status == emission.coverage_status == 'executable'
        assert task.coverage_status == 'executable', task.blocked_reason
        selected_callbacks = (callback, damage_callback)
        selected_ids = {row.callback_id for row in selected_callbacks}
        selected_tasks = tuple(row for row in lowered.status_callback_tasks if row.callback_id in selected_ids)
        engine = build_engine_rule_registry()
        formulas = tuple(row for row in TBGDLowering(ROOT)._lower_elation_mechanics() if row.coverage_status == 'executable')
        canonical = CanonicalIR('real-owner-status-elation-component', entities=tuple(lowered.entities),
            effects=tuple(_synchronize_effect_target_expression_metadata(lowered.effects, list(targets))),
            conditions=tuple(lowered.conditions), target_expressions=targets,
            status_callbacks=selected_callbacks, status_callback_tasks=selected_tasks,
            status_damage_emissions=tuple(row for row in lowered.status_damage_emissions if row.callback_id in selected_ids),
            damage_modifiers=tuple(row for row in lowered.damage_modifiers if row.callback_id in selected_ids),
            status_event_families=tuple(_lower_status_event_families(selected_callbacks, selected_tasks)),
            formulas=formulas, damage_formula_rules=engine.damage_formula_rules, damage_route_rules=engine.damage_route_rules)
        snapshot = lowerer._character_ability_raw_snapshot
        catalog = merge_task_graph_slices(build_complete_task_graph_catalog(source_catalog, snapshot),
            (materialize_status_callback_task_graph(source_catalog, canonical,
                callback_id=row.callback_id, source_snapshot=snapshot) for row in selected_callbacks))
        pre_hit_graph = next(row for row in catalog.graphs if row.owner_id == callback.callback_id)
        assert all(row.materialization_status == 'materialized' for row in pre_hit_graph.nodes)
        rules = RuleBook(attach_task_graph_catalog(canonical, catalog))

    # This is the source's initialized caster-provided MDF_PropertyValue slot,
    # not an assembled skill-level build. Other unit properties deliberately differ.
    detail = StatusInstance('passive:owner', 'modifier:' + modifier, modifier, 'owner', 'fixture:passive', 'caster',
        dynamic_values={'MDF_PropertyValue': .35, '__by_hash': {'2128130574': .35},
                        '__definition_bindings': definition.fields['dynamic_value_bindings']},
        trigger_ids_by_event={'OnListenBeforeHitAll': (callback.callback_id,)},
        source_trace=definition.source.to_json()).to_json()
    owner = UnitState('owner', 'ally', 'fixture:owner', level=20, hp=1000, max_hp=1000,
        resources={'critical_chance': 1., 'critical_damage': .5, 'elation_damage_added_ratio': .2, 'elation_echo_point': 3.},
        statuses=(detail['status_id'],), flags={'damage_type': 'Fire', 'status_details': [detail]})
    caster = UnitState('caster', 'ally', 'fixture:caster', level=80, hp=1000, max_hp=1000,
        resources={'critical_chance': 0., 'critical_damage': 3., 'elation_damage_added_ratio': .8, 'elation_echo_point': 40.},
        flags={'damage_type': 'Quantum'})
    enemy = UnitState('enemy', 'enemy', 'fixture:enemy', hp=1000000, max_hp=1000000,
        resources={'Fire_resistance': .2, 'Quantum_resistance': .8})
    state = BattleState(units={row.unit_id: row for row in (owner, caster, enemy)})
    trigger = GameEvent('fixture:attack', source_id='owner', target_id='enemy', event_id='fixture:attack',
        payload={'param_entity_id': 'enemy'})

    def execute(selected_rules):
        registry = EffectRegistry(StatusSystem(selected_rules))
        dispatcher = EventDispatchSystem(selected_rules, registry)
        system = dispatcher.status_callbacks
        packets = []
        apply = system.damage.apply_packet

        def capture(current, packet, **kwargs):
            packets.append(packet)
            return apply(current, packet, **kwargs)

        system.damage.apply_packet = capture
        result = system._execute_damage_emissions(state, damage_callback, task, detail, trigger, (emission,), None)
        return result, packets

    result, packets = execute(rules)
    assert result.ok, result.errors
    assert len(packets) == 1
    packet = packets[0]
    assert packet.attacker_id == 'owner' and packet.element_type == 'Fire'
    assert packet.scaling_ratio == .35 and packet.elation_context.points == 40
    damage = next(row['payload'] for row in result.records if row['record_type'] == 'damage')
    table = next(row for row in formulas if row.kind == 'elation_level_base')
    assert damage['elation_formula']['level_base'] == float(table.expression['values']['20'])
    assert damage['crit_resolution']['is_crit']
    stages = {row['stage']: row for row in damage['damage_pipeline']['stages']}
    assert math.isclose(stages['elation_bonus']['multiplier'], 1.8)
    assert math.isclose(stages['punchline']['multiplier'], 1 + 5 * 40 / 280)
    assert math.isclose(stages['critical']['multiplier'], 1.5)
    terms = [row.formula_term() for row in packet.modifier_contributions]
    assert len(terms) == 3
    assert math.isclose(next(row['value'] for row in terms if row['key'] == 'elation_damage_added_ratio'), .6)
    assert all(result.after_state.units[unit_id].resources == state.units[unit_id].resources for unit_id in ('owner', 'caster'))
    assert effective_unit_stat(result.after_state.units['owner'], 'elation_damage_added_ratio').value == .2
    assert effective_unit_stat(result.after_state.units['owner'], 'elation_echo_point').value == 3
    windows = [event for event in result.events if event.event_type in {
        'damage.hit_sequence.before', 'damage.before_hit', 'damage.hit_sequence.after'}]
    assert {event.event_type for event in windows} == {
        'damage.hit_sequence.before', 'damage.before_hit', 'damage.hit_sequence.after'}
    assert {event.event_id for event in windows} <= result.dispatched_event_ids
    assert len([event for event in result.events if event.event_type == 'status.callback'
                and event.payload.get('callback_id') == callback.callback_id]) == 1
    assert not any(event.event_type.startswith('action.') for event in result.events)
    audit = RuntimeSourceAuditor(rules).validate_execution(result.mutations, result.records)
    assert audit.ok, audit.to_json()
    bad_formulas = tuple(replace(row, expression={'values': {'80': row.expression['values']['80']}})
        if row.kind == 'elation_level_base' else row for row in formulas)
    failed, _ = execute(RuleBook(replace(rules.ir, formulas=bad_formulas)))
    assert failed.errors == ('elation_level_base_missing_or_invalid',)
    assert not failed.ok and failed.after_state == state and not failed.mutations and not failed.rng_events
    assert not failed.dispatched_event_ids
