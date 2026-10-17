"""Real shield/counter callbacks keep the attacker, holder, and caster distinct."""
from dataclasses import replace
from pathlib import Path

from hsr.simulator_v8_clean_core.core.model import ActionCommand, BattleState, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.evaluator import RuleEvaluator
from hsr.simulator_v8_clean_core.rules.ir import ActionDefinitionIR, CanonicalIR, IRSource
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.action_event_contract import damage_listener_window_event
from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry
from hsr.simulator_v8_clean_core.systems.status import StatusInstance, StatusLifecyclePlan, StatusSystem
from hsr.simulator_v8_clean_core.systems.status_callbacks import _condition_context
from hsr.simulator_v8_clean_core.systems.target import TargetSystem
from hsr.simulator_v8_clean_core.tbgd.adopted_modifier_counts import MODIFIER, SOURCE
from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering
from hsr.simulator_v8_clean_core.tbgd.target_source import build_target_language_definitions


def test_real_shield_counter_condition_refresh_and_unchanged_bar():
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    lowered = TBGDLowering(root)._lower_ability_file(root / SOURCE, {}, ability_file_order=0)
    condition = next(item for item in lowered.conditions
                     if item.opcode == 'ByAnd' and 'BPSkill_Shield_Counter' in item.source.raw_id)
    rules = RuleBook(CanonicalIR('shield-counter-check', conditions=tuple(lowered.conditions),
        effects=tuple(lowered.effects), target_expressions=(
            *lowered.target_expressions, *(item.expression for item in build_target_language_definitions(root))),
        status_callbacks=tuple(lowered.status_callbacks), status_callback_tasks=tuple(lowered.status_callback_tasks)))
    count = StatusInstance('count', f'modifier:{MODIFIER}', MODIFIER, 'caster', 'passive', 'caster',
                           stacks=2, stack_policy='independent_count').to_json()
    shield_name = 'MAvatar_March7th_00_BPSkill_Shield'
    shield = StatusInstance('shield', f'modifier:{shield_name}', shield_name, 'holder', 'skill', 'caster',
                            behavior_flags=('Shield',), remaining_duration=2)
    listener = StatusInstance('counter', 'modifier:counter', 'MAvatar_March7th_00_BPSkill_Shield_Counter',
                              'holder', 'passive', 'caster').to_json()
    state = BattleState(units={
        'caster': UnitState('caster', 'ally', 'fixture:caster', hp=100, max_hp=100,
            statuses=(count['status_id'],), flags={'status_details': [count],
            'mechanism_bars': {'3': {'state': 'Active', 'current_count': 2.0, 'max_count': 2.0}}}),
        'holder': UnitState('holder', 'ally', 'fixture:holder', hp=100, max_hp=100,
            statuses=(shield.status_id, listener['status_id']), flags={'status_details': [shield.to_json(), listener]}),
        'enemy': UnitState('enemy', 'enemy', 'fixture:enemy', hp=100, max_hp=100),
    })
    action = ActionDefinitionIR('check:attack', 'check:attack', 1, 'Normal', 'SingleAttack', 'single',
        0, 0, 0, 0, (), (), (), None, IRSource('fixture', 'action', 'attack'))
    command = ActionCommand(actor_id='enemy', action_id=action.action_id, action_level=1, target_ids=('holder',))
    event = damage_listener_window_event(state, command, action, event_type='damage.target_attack.before',
        target_id='holder', selected_target_ids=('holder',), primary_target_id='holder', source_trace={})
    assert event.payload['param_entity_id'] == 'enemy'
    assert event.target_id == 'holder' and event.payload['selected_target_ids'] == ['holder']
    result = RuleEvaluator().evaluate_condition_result(condition,
        _condition_context(rules, state, listener, event, condition=condition, targets=TargetSystem(rules)))
    assert result.ok and result.result, result.to_json()
    exhausted = replace(state, units={**state.units, 'caster': replace(state.units['caster'],
        flags={**state.units['caster'].flags, 'status_details': [{**count, 'stacks': 0}]})})
    result = RuleEvaluator().evaluate_condition_result(condition,
        _condition_context(rules, exhausted, listener, event, condition=condition, targets=TargetSystem(rules)))
    assert result.ok and not result.result, result.to_json()

    # Refresh emits the callback that owns InitShield without replaying OnCreate.
    lifecycle = StatusSystem(rules)._apply_lifecycle_plan(state, StatusLifecyclePlan(
        'refresh', 'holder', shield.status_id, 'check', status_instance=replace(shield, remaining_duration=3),
        before_details=tuple(state.units['holder'].flags['status_details']), existing_detail=shield.to_json()))
    assert lifecycle.ok
    assert [event.window for event in lifecycle.events] == ['OnStack', 'OnModifierAdd', 'OnListenModifierAdd']
    assert any(task.modifier_name == shield_name and task.event == 'OnStack' and task.opcode == 'InitShield'
               for task in lowered.status_callback_tasks)

    bar = next(effect for effect in lowered.effects if effect.opcode == 'SetEnergyBarState'
               and effect.payload.get('standard', {}).get('state') == 'Active'
               and effect.payload.get('standard', {}).get('bar_type') is None)
    registry = EffectRegistry(StatusSystem(rules))
    context = EffectExecutionContext(state, 'caster', 'listener', owner_id='caster')
    for _ in range(2):
        unchanged = registry.execute(bar, context)
        assert not unchanged.unsupported and not unchanged.mutations
        assert unchanged.records[0]['process_only'] and unchanged.records[0]['mutation_id'] is None
    inactive = replace(state, units={**state.units, 'caster': replace(state.units['caster'],
        flags={**state.units['caster'].flags, 'mechanism_bars': {'3': {'state': 'Normal'}}})})
    changed = registry.execute(bar, replace(context, state=inactive))
    assert not changed.unsupported and len(changed.mutations) == 1
    after = MutationReducer().apply_all(inactive, changed.mutations)
    assert after.units['caster'].flags['mechanism_bars']['3']['state'] == 'Active'
