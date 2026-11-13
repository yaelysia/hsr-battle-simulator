"""Small processor checks; synthetic battle states are not game evidence."""
from dataclasses import replace
from pathlib import Path

from hsr.simulator_v8_clean_core.content_processors.academic_rumors import AcademicRumorsProcessor, _CLOCK
from hsr.simulator_v8_clean_core.core.content_hooks import attach_processors, MountedProcessor
from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, UnitState
from hsr.simulator_v8_clean_core.rules.engine_rule_registry import build_engine_rule_registry
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, WaveDefinitionIR, IRSource, ActionDefinitionIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
from hsr.simulator_v8_clean_core.systems.effect import EffectRegistry
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.systems.wave import _wave_started_event
from hsr.simulator_v8_clean_core.tbgd.adopted_stage_environment import compile_stage_environment


def test_source_clock_global_bonus_and_cycle_limit_request():
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    data = compile_stage_environment(root, '30123061', '30146')
    source = IRSource('fixture', 'environment_test', 'stage')
    wave = WaveDefinitionIR('wave', '30123061', 2, (), (), source,
        stage_environment_status='executable', stage_environment_blocked_reason='', stage_environment_data=data)
    rules = RuleBook(CanonicalIR('fixture', wave_definitions=(wave,),
                               timeline_rules=build_engine_rule_registry().timeline_rules))
    processor = AcademicRumorsProcessor()
    attach_processors(rules, (MountedProcessor(processor.content_id, processor.version, processor),))
    dispatcher = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules)))
    state = BattleState(units={
        'level:global': UnitState('level:global', 'ally', 'system_entity:level', hp=1, max_hp=1,
                                 flags={'timeline_admitted': False}),
        'actor': UnitState('actor', 'ally', 'fixture', hp=100, max_hp=100),
        'target': UnitState('target', 'enemy', 'fixture', hp=100, max_hp=100),
    }, global_flags={'wave_runtime': {'wave_definition_id': 'wave'}, 'challenge_cycles_used': 29,
                     'combat_phase': 'wave_transition'})
    born = dispatcher.dispatch_event(state,
        event=_wave_started_event(state, wave, 0, (state.units['target'],), source.to_json()))
    assert not born.errors, born.errors
    clock = born.after_state.units[_CLOCK]
    assert clock.speed == 100 and clock.action_value == 150 and clock.resources['cycles_used'] == 29
    action = ActionDefinitionIR('ultimate', 'ultimate', 1, 'Ultra', 'Ultra', 'single',
                                0, 0, 0, 0, (), (), (), 'Physical', source, coverage_status='executable')
    attacking = replace(born.after_state, global_flags={**born.after_state.global_flags, 'combat_phase': 'action_execution'})
    hit = dispatcher.dispatch_event(attacking, event=GameEvent('damage.hit_sequence.before',
        source_id='actor', target_id='actor', event_id='hit', action_definition=action))
    assert not hit.errors and len(hit.damage_modifiers) == 1
    assert hit.damage_modifiers[0].value == .5
    follow_up = dispatcher.dispatch_event(attacking, event=GameEvent('damage.hit_sequence.before',
        source_id='actor', target_id='actor', event_id='follow-up', action_definition=replace(action, attack_type='Insert')))
    assert not follow_up.errors and follow_up.damage_modifiers[0].value == .5
    assert follow_up.after_state.units[_CLOCK].resources['stage_hits'] == 1
    second_hit = dispatcher.dispatch_event(follow_up.after_state, event=GameEvent('damage.hit_sequence.before',
        source_id='actor', target_id='actor', event_id='follow-up-hit-2', action_definition=replace(action, attack_type='Insert')))
    assert not second_hit.errors and second_hit.after_state.units[_CLOCK].resources['stage_hits'] == 1
    ordinary = dispatcher.dispatch_event(attacking, event=GameEvent('damage.hit_sequence.before',
        source_id='actor', target_id='actor', event_id='ordinary', action_definition=replace(action, attack_type='Normal')))
    assert not ordinary.damage_modifiers
    beginning = replace(born.after_state, global_flags={**born.after_state.global_flags, 'combat_phase': 'turn_begin'})
    expired = dispatcher.dispatch_event(beginning,
        event=GameEvent('turn.begin', source_id=_CLOCK, target_id=_CLOCK, event_id='cycle'))
    assert not expired.errors, expired.errors
    assert expired.after_state.global_flags['battle_defeat_requested'] is True
    assert expired.after_state.units[_CLOCK].resources['cycles_used'] == 30
