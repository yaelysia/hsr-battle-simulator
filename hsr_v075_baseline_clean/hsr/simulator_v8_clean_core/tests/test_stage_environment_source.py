"""Selected stage rules share the authoritative task graph source pipeline."""
import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from hsr.simulator_v8_clean_core.rules.ir import ActionDefinitionIR, CanonicalIR, IRSource, WaveDefinitionIR
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering, _dedupe_target_expressions, _link_status_effect_runtime_fields,
    _lower_status_event_families, _synchronize_effect_target_expression_metadata,
)
from hsr.simulator_v8_clean_core.tbgd.target_source import close_target_expression_language
from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import (
    materialize_ability_phase_task_graph, materialize_status_callback_task_graph,
    attach_task_graph_catalog, build_complete_task_graph_catalog, merge_task_graph_slices,
)


def _stage_source_graphs(directory):
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    avatar = next(row for row in json.loads((root / 'ExcelOutput/AvatarConfig.json').read_text())
                  if row['AvatarID'] == 1009)
    for name, rows in {'AvatarConfig': [avatar], 'AvatarConfigLD': [],
                       'AvatarConfigEnhanced': [], 'AvatarServantConfig': []}.items():
        path = directory / f'ExcelOutput/{name}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows))
    files = (
        'ExcelOutput/StageConfig.json', 'Config/Level/StageCommonTemplate.json',
        'Config/ConfigAbility/Avatar/Avatar_Asta_00_Ability.json',
        'Config/ConfigAbility/Avatar/Avatar_Common_Ability.json',
        'Config/ConfigAbility/Level/Level_MazeChallengeBuff_Ability.json',
        'Config/ConfigAbility/Level/Level_BattleCommonRule_Ability.json',
        'Config/ConfigAbility/BattleEvent/StageAbility_Elation.json',
        'Config/GlobalConfig/TargetAliasConfig.json', 'Config/GlobalConfig/TargetOperationConfig.json',
        'Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json',
    )
    for relative in files:
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((root / relative).read_bytes())
    lowerer = TBGDLowering(directory)
    info = lowerer._prepare_stage_ability_sources(frozenset({'301008'}))['301008']
    assert info['ability_refs'] == ('StageAbility_301008', 'StageAbility_BattleCommonRule', 'StageAbility_Elation')
    assert info['blocked_reason'] == 'stage_environment_field_not_admitted:BattleScoringGroup'
    graphs, phases, lowered = lowerer._lower_stage_startup_abilities()
    phase = next(row for row in phases if row.ability_name == 'StageAbility_301008')
    assert phase.invocation_role == 'build_startup' and phase.coverage_status == 'executable'
    phase_tasks = [row for row in lowered.ability_tasks if row.phase_id == phase.phase_id]
    assert [(row.callback_kind, row.opcode, row.coverage_status) for row in phase_tasks] == [('OnAdd', 'AddModifier', 'executable')]
    relative = phase.source.source_path
    callbacks = lowerer._lower_ability_file(directory / relative, {}, ability_file_order=0,
        formal_status_source_context=lowerer._character_formal_task_source_context())
    lowered.merge(callbacks)
    lowered.effects = _link_status_effect_runtime_fields(lowered.effects, lowered.entities, lowered.status_callbacks)
    language = lowerer._strict_target_language_definitions()
    targets = tuple(_dedupe_target_expressions(
        [close_target_expression_language(row, language) for row in lowered.target_expressions]).values())
    canonical = CanonicalIR('stage-source-check', entities=tuple(lowered.entities),
        ability_phases=tuple(phases), ability_tasks=tuple(lowered.ability_tasks),
        standalone_ability_graphs=tuple(graphs),
        effects=tuple(_synchronize_effect_target_expression_metadata(lowered.effects, list(targets))),
        conditions=tuple(lowered.conditions), status_callbacks=tuple(lowered.status_callbacks),
        status_callback_tasks=tuple(lowered.status_callback_tasks),
        target_expressions=targets + tuple(row.expression for row in language))
    catalog = lowerer.build_character_control_flow_contract_catalog()
    snapshot = lowerer._runtime_task_raw_snapshot
    startup = materialize_ability_phase_task_graph(catalog, canonical, phase_id=phase.phase_id,
        callback_kind='OnAdd', source_snapshot=snapshot)
    assert len(startup.graphs) == 1, [row.blocked_reason for row in startup.entry_materializations]
    selected_callbacks = [row for row in callbacks.status_callbacks
                          if row.modifier_name in {'StageAbility_301008_Modifier', 'StageAbility_301008_Modifier_Sub'}]
    assert {row.event for row in selected_callbacks} == {'OnListenCharacterCreate', 'OnStack', 'OnBeforeHitAll'}
    slices = [startup]
    for callback in selected_callbacks:
        assert callback.source_mode == 'mainline_stage_ability' and callback.coverage_status == 'executable', callback
        result = materialize_status_callback_task_graph(catalog, canonical, callback_id=callback.callback_id,
            source_snapshot=snapshot)
        assert len(result.graphs) == 1, [row.blocked_reason for row in result.entry_materializations]
        assert all(row.materialization_status == 'materialized' for row in result.graphs[0].nodes), [
            (row.opcode, row.status_reason) for row in result.graphs[0].nodes]
        slices.append(result)
    stack = next(row for row in callbacks.status_callback_tasks
                 if row.modifier_name == 'StageAbility_301008_Modifier_Sub' and row.opcode == 'StackProperty')
    effect = next(row for row in canonical.effects if row.effect_id == stack.effect_id)
    assert effect.payload['Property'] == 'CriticalChanceBase' and effect.payload['PropertyValue']['FixedValue']['Value'] == 1
    assert all(row.source_kind == 'stage' for row in snapshot.sources if row.source.source_path.startswith('Config/ConfigAbility/Level/'))
    return lowerer, canonical, tuple(slices)


def test_real_stage_startup_and_birth_modifier_use_formal_source_graphs():
    with TemporaryDirectory() as temporary:
        lowerer, canonical, slices = _stage_source_graphs(Path(temporary))
        catalog = merge_task_graph_slices(build_complete_task_graph_catalog(
            lowerer.build_character_control_flow_contract_catalog(), lowerer._runtime_task_raw_snapshot), slices)
        phase = next(row for row in canonical.ability_phases if row.ability_name == 'StageAbility_301008')
        # Component boundary: execute this real ability in isolation. The actual
        # stage remains blocked on its other template/scoring dependencies.
        wave = WaveDefinitionIR('fixture:stage-component', '301008', 1, (), (phase.ability_name,), phase.source,
            stage_startup_phase_ids=(phase.phase_id,), stage_environment_status='executable',
            stage_environment_blocked_reason='')
        callback_ids = {entry.owner_id for part in slices for entry in part.entry_materializations
                        if entry.entry_kind == 'status_callback'}
        callbacks = tuple(row for row in canonical.status_callbacks if row.callback_id in callback_ids)
        callback_tasks = tuple(row for row in canonical.status_callback_tasks if row.callback_id in callback_ids)
        canonical = attach_task_graph_catalog(replace(canonical, wave_definitions=(wave,),
            ability_phases=(phase,), ability_tasks=tuple(row for row in canonical.ability_tasks if row.phase_id == phase.phase_id),
            standalone_ability_graphs=tuple(row for row in canonical.standalone_ability_graphs if phase.phase_id in row.phase_ids),
            status_callbacks=callbacks, status_callback_tasks=callback_tasks,
            status_event_families=tuple(_lower_status_event_families(list(callbacks), list(callback_tasks)))), catalog)
        _check_stage_ability_runtime(canonical, wave)


def _check_stage_ability_runtime(canonical, wave):
    from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, UnitState
    from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
    from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
    from hsr.simulator_v8_clean_core.systems.ability import AbilityTaskSystem
    from hsr.simulator_v8_clean_core.systems.damage import DamagePacket, DamageSystem
    from hsr.simulator_v8_clean_core.systems.effect import EffectRegistry
    from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
    from hsr.simulator_v8_clean_core.systems.status import StatusSystem
    from hsr.simulator_v8_clean_core.systems.unit_stats import effective_unit_stat

    rules = RuleBook(canonical)
    registry = EffectRegistry(StatusSystem(rules))
    dispatcher = EventDispatchSystem(rules, registry)
    runtime = AbilityTaskSystem(rules, registry, event_dispatcher=dispatcher)
    state = BattleState(units={
        'level:global': UnitState('level:global', 'ally', 'system_entity:level',
                                 hp=1, max_hp=1, speed=0, flags={'system_entity_kind': 'level'}),
        'ally': UnitState('ally', 'ally', 'fixture:ally', hp=1000, max_hp=1000, attack=100,
                          resources={'critical_chance': 0., 'critical_damage': .5}),
        'enemy': UnitState('enemy', 'enemy', 'fixture:enemy', hp=10000, max_hp=10000),
    }, global_flags={'wave_runtime': {'wave_definition_id': wave.wave_definition_id, 'stage_id': wave.stage_id}})
    startup = runtime.execute_stage_startup(state, actor_id='level:global', wave_definition_id=wave.wave_definition_id)
    assert startup.node_results and all(row.status == 'complete' for row in startup.node_results), startup.records
    assert startup.mutations and startup.after_state.units['level:global'].statuses
    audit = RuntimeSourceAuditor(rules).validate_execution(startup.mutations, startup.records)
    assert audit.ok, audit.to_json()
    current = startup.after_state
    for unit_id in ('ally', 'enemy'):
        created = GameEvent('unit.created', source_id='scenario:setup', target_id=unit_id,
            event_id='fixture:birth:' + unit_id, window='OnListenCharacterCreate', process_only=True,
            payload={'unit_id': unit_id, 'target_id': unit_id, 'param_entity_id': unit_id,
                     'callback_events': ['OnListenCharacterCreate'], 'listener_scope': 'global_listener'})
        dispatched = dispatcher.dispatch_event(current, event=created)
        assert not dispatched.errors, dispatched.errors
        audit = RuntimeSourceAuditor(rules).validate_execution(dispatched.mutations, dispatched.records)
        assert audit.ok, audit.to_json()
        current = dispatched.after_state
    assert effective_unit_stat(current.units['ally'], 'critical_chance').value == 1
    assert effective_unit_stat(current.units['enemy'], 'critical_chance').value == 0
    source = IRSource('validation_fixture/direct_hit', 'Action', 'normal')
    action = ActionDefinitionIR('fixture:normal', 'fixture:normal', 1, 'Normal', 'SingleAttack', 'single',
                                0, 0, 0, 0, (), (), (), 'Fire', source)
    packet = DamagePacket('ally', 'enemy', 'Normal', 'direct', action_definition=action,
        scaling_ratio=1, scaling_basis={'kind': 'unit_stat', 'unit_ref': 'attacker', 'stat': 'attack'}, element_type='Fire')
    baseline = DamageSystem().apply_packet(state, packet)
    boosted = DamageSystem().apply_packet(current, packet)
    assert baseline.ok and boosted.ok, (baseline.errors, boosted.errors)
    loss = lambda result: next(row.before - row.after for row in result.mutations if row.path[-1] == 'hp')
    assert loss(boosted) == loss(baseline) * 1.5


if __name__ == '__main__':
    test_real_stage_startup_and_birth_modifier_use_formal_source_graphs()
    print('stage environment source check passed')
