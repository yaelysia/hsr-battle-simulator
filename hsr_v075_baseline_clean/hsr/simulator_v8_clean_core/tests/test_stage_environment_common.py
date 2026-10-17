"""Small real common-stage compilation, without character/equipment builds."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, UnitState
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.rules.ir import AvatarProfileIR, CanonicalIR, CharacterDataCardIR, IRSource, WaveDefinitionIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.ability import AbilityTaskSystem
from hsr.simulator_v8_clean_core.systems.effect import EffectRegistry
from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.systems.summon_runtime import empty_summon_runtime
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering, _dedupe_target_expressions, _link_status_effect_runtime_fields,
    _link_status_trigger_ability_graphs, _link_trigger_ability_graphs,
    _lower_status_event_families, _synchronize_effect_target_expression_metadata,
)
from hsr.simulator_v8_clean_core.tbgd.target_source import close_target_expression_language
from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import (
    attach_task_graph_catalog, materialize_selected_character_task_graphs,
)


def build_common_stage_component(directory: Path) -> tuple[RuleBook, WaveDefinitionIR]:
    """Compile the real 200020050 environment; combatants remain test fixtures."""
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    for table in ('AvatarConfig', 'AvatarConfigLD', 'AvatarConfigEnhanced', 'AvatarServantConfig'):
        path = directory / f'ExcelOutput/{table}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('[]')
    # The source authority also includes the existing common ability file. No
    # character card, equipment catalog, monster card or full build is compiled.
    for relative in (
        'ExcelOutput/StageConfig.json', 'Config/Level/StageCommonTemplate.json',
        'Config/ConfigAbility/Avatar/Avatar_Common_Ability.json',
        'Config/ConfigAbility/Level/Level_BattleCommonRule_Ability.json',
        'Config/ConfigAbility/BattleEvent/StageAbility_Elation.json',
        'Config/GlobalConfig/TargetAliasConfig.json', 'Config/GlobalConfig/TargetOperationConfig.json',
        'Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json',
    ):
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((root / relative).read_bytes())
    lowerer = TBGDLowering(directory)
    info = lowerer._prepare_stage_ability_sources(frozenset({'200020050'}))['200020050']
    assert info['ability_refs'] == ('StageAbility_BattleCommonRule', 'StageAbility_Elation')
    assert not info['blocked_reason'], info['blocked_reason']
    graphs, phases, lowered = lowerer._lower_stage_startup_abilities()
    context = lowerer._character_formal_task_source_context()
    for order, relative in enumerate(lowerer._stage_ability_indices):
        lowered.merge(lowerer._lower_ability_file(directory / relative, {}, ability_file_order=order,
            formal_status_source_context=context))
    lowered.ability_tasks = _link_trigger_ability_graphs(lowered.ability_tasks, lowered.effects, graphs, phases)
    lowered.status_callback_tasks = _link_status_trigger_ability_graphs(
        lowered.status_callback_tasks, lowered.status_callbacks, lowered.effects, graphs)
    language = lowerer._strict_target_language_definitions()
    targets = list(_dedupe_target_expressions([
        close_target_expression_language(row, language) for row in lowered.target_expressions
    ] + [row.expression for row in language]).values())
    effects = _synchronize_effect_target_expression_metadata(_link_status_effect_runtime_fields(
        lowered.effects, lowered.entities, lowered.status_callbacks, lowered.ability_property_watchers), targets)
    stage_rows = json.loads((root / 'ExcelOutput/StageConfig.json').read_text())
    row_index = next(index for index, row in enumerate(stage_rows) if row['StageID'] == 200020050)
    # This wave binds only the environment component. Its combatants are stated
    # below as fixtures; it never claims a source-complete playable stage build.
    wave = WaveDefinitionIR('fixture:stage-environment:200020050', '200020050', 1, (), info['ability_refs'],
        IRSource('ExcelOutput/StageConfig.json', 'StageConfig', '200020050', {
            'stage_row_index': row_index, 'component_scope': 'stage_environment_only',
        }), stage_startup_phase_ids=tuple(
            next(phase.phase_id for phase in phases if phase.ability_name == name)
            for name in info['ability_refs']),
        stage_environment_status='executable', stage_environment_blocked_reason='')
    canonical = CanonicalIR('common-stage-source-component',
        # This explicitly synthetic card supplies only the typed path predicate;
        # it is not an assembled build or an extra TBGD combat source.
        avatar_profiles=(AvatarProfileIR('fixture:profile', 'fixture', 'Warrior', 'Physical', (), (),
            None, None, IRSource('validation_fixture/common_stage', 'AvatarProfile', 'fixture'), 'executable'),),
        character_data_cards=(CharacterDataCardIR('fixture:card', 'avatar:fixture', 'fixture:profile', (), (), (),
            IRSource('validation_fixture/common_stage', 'CharacterDataCard', 'fixture'), 'executable'),),
        entities=tuple(lowered.entities), standalone_ability_graphs=tuple(graphs),
        ability_phases=tuple(phases), ability_tasks=tuple(lowered.ability_tasks),
        effects=tuple(effects), conditions=tuple(lowered.conditions), formulas=tuple(lowered.formulas),
        status_callbacks=tuple(lowered.status_callbacks), status_callback_tasks=tuple(lowered.status_callback_tasks),
        status_event_families=tuple(_lower_status_event_families(lowered.status_callbacks, lowered.status_callback_tasks)),
        status_damage_emissions=tuple(lowered.status_damage_emissions), damage_modifiers=tuple(lowered.damage_modifiers),
        action_delay_emissions=tuple(lowered.action_delay_emissions), queue_intents=tuple(lowered.queue_intents),
        ability_property_watchers=tuple(lowered.ability_property_watchers),
        ability_property_ranges=tuple(lowered.ability_property_ranges),
        target_expressions=tuple(targets), wave_definitions=(wave,))
    catalog = materialize_selected_character_task_graphs(lowerer.build_character_control_flow_contract_catalog(),
        canonical, source_snapshot=lowerer._runtime_task_raw_snapshot,
        selected_source_paths=frozenset(lowerer._stage_ability_indices))
    return RuleBook(attach_task_graph_catalog(canonical, catalog)), wave


def common_stage_fixture(wave: WaveDefinitionIR) -> BattleState:
    return BattleState(units={
        'level:global': UnitState('level:global', 'ally', 'system_entity:level', hp=1, max_hp=1, speed=0,
            flags={'system_entity_kind': 'level', 'selectable': False, 'unselectable': True}),
        'ally': UnitState('ally', 'ally', 'avatar:fixture', hp=1000, max_hp=1000,
            flags={'entity_type': 'avatar', 'character_data_card_id': 'fixture:card'}),
        'enemy': UnitState('enemy', 'enemy', 'fixture:enemy', hp=1000, max_hp=1000,
            flags={'entity_type': 'monster'}),
    }, global_flags={'summon_runtime': empty_summon_runtime(), 'wave_runtime': {
        'wave_definition_id': wave.wave_definition_id, 'stage_id': wave.stage_id,
        'wave_index': 0, 'wave_count': 1,
    }})


def test_real_common_and_elation_startup_then_level_enter_battle():
    with TemporaryDirectory() as temporary:
        rules, wave = build_common_stage_component(Path(temporary))
        assert tuple(rules.ability_phase(phase_id).ability_name for phase_id in wave.stage_startup_phase_ids) == (
            'StageAbility_BattleCommonRule', 'StageAbility_Elation')
        registry = EffectRegistry(StatusSystem(rules))
        dispatcher = EventDispatchSystem(rules, registry)
        runtime = AbilityTaskSystem(rules, registry, event_dispatcher=dispatcher)
        startup = runtime.execute_stage_startup(common_stage_fixture(wave),
            actor_id='level:global', wave_definition_id=wave.wave_definition_id)
        assert all(row.status == 'complete' for row in startup.node_results), [
            row.reason_code for row in startup.node_results if row.status != 'complete']
        assert startup.mutations and startup.after_state.units['level:global'].statuses
        entered = dispatcher.dispatch_event(startup.after_state, event=GameEvent('battle.setup',
            source_id='scenario:setup', target_id='level:global', event_id='fixture:level-enter',
            window='OnEnterBattle', process_only=True, payload={
                'actor_id': 'level:global', 'target_id': 'level:global', 'param_entity_id': 'level:global',
            }))
        assert not entered.errors, (entered.errors, entered.records)
        assert entered.mutations, 'the real character-count producer must write zero'
        audit = RuntimeSourceAuditor(rules).validate_execution(
            (*startup.mutations, *entered.mutations), (*startup.records, *entered.records))
        assert audit.ok, audit.to_json()


if __name__ == '__main__':
    test_real_common_and_elation_startup_then_level_enter_battle()
    print('common stage environment component passed')
