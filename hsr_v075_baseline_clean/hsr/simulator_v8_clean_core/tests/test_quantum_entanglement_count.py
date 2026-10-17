"""The actual ordinary Entanglement callbacks share adopted count parameters."""
import json
from pathlib import Path

from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, UnitState
from hsr.simulator_v8_clean_core.rules.engine_rule_registry import ENGINE_RULE_REGISTRY_VERSION, TIMELINE_RULE_APPLICABILITY
from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_fixed
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, IRSource, TimelineRuleIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.status import StatusInstance, _resolve_dynamic_values
from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem
from hsr.simulator_v8_clean_core.tbgd.adopted_modifier_counts import ENTANGLE_MODIFIER, ENTANGLE_SOURCE
from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering


def test_entanglement_actual_callbacks_start_at_one_gain_per_hit_and_cap_at_five():
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    raw = json.loads((root / ENTANGLE_SOURCE).read_text())['ModifierMap'][ENTANGLE_MODIFIER]
    lowering = TBGDLowering(root)
    lowered = lowering._lower_ability_file(root / ENTANGLE_SOURCE, {}, ability_file_order=0,
        raw_document={'ModifierMap': {ENTANGLE_MODIFIER: raw}})
    definition = lowered.entities[0]
    values = _resolve_dynamic_values({}, definition, {}, (), {})
    assert values['__by_hash']['808921108'] == 5
    assert values['__by_hash']['560166466'] == 1
    assert values['__by_hash']['-434232686'] == 0
    assert definition.fields['max_layer_expr']['kind'] == 'missing'
    assert definition.fields['dynamic_value_bindings']['by_hash']['808921108']['initial_value_source']['kind'] == 'adopted_mechanism_data'
    explicit = _resolve_dynamic_values({}, definition, {'808921108': 7.0}, (), {})
    assert explicit['__by_hash']['808921108'] == 7
    named = _resolve_dynamic_values({'dynamic_values': {'Max_Count': numeric_fixed(7)}}, definition, {}, (), {})
    assert named['__by_hash']['808921108'] == 7
    clock = TimelineRuleIR('fixture:clock', 10000, 'base_action_gauge_div_speed',
        'base_action_gauge_div_speed', 'engine_convention', IRSource('fixture', 'TimelineRule', 'clock'),
        registry_version=ENGINE_RULE_REGISTRY_VERSION, applicability=TIMELINE_RULE_APPLICABILITY)
    language = lowering._strict_target_language_definitions()
    rules = RuleBook(CanonicalIR('fixture:quantum-count', entities=tuple(lowered.entities),
        effects=tuple(lowered.effects), conditions=tuple(lowered.conditions), status_callbacks=tuple(lowered.status_callbacks),
        status_callback_tasks=tuple(lowered.status_callback_tasks),
        action_delay_emissions=tuple(lowered.action_delay_emissions), timeline_rules=(clock,),
        target_expressions=(*lowered.target_expressions, *(item.expression for item in language))))
    attached = {event: tuple(callback.callback_id for callback in lowered.status_callbacks if callback.event == event)
                for event in ('OnStack', 'OnBeforeBeingAttacked', 'OnAfterBeingAttacked')}
    detail = StatusInstance('fixture:entangle:1', f'modifier:{ENTANGLE_MODIFIER}', ENTANGLE_MODIFIER,
        'target', 'fixture:break', 'caster', dynamic_values=values, trigger_ids_by_event=attached,
        behavior_flags=tuple(raw['BehaviorFlagList']), status_category='control', control_kind='Entangle',
        source_trace={'modifier_definition': definition.source.to_json()}).to_json()
    state = BattleState(units={
        'caster': UnitState('caster', 'ally', 'fixture:caster', hp=100, max_hp=100),
        'target': UnitState('target', 'enemy', 'fixture:target', hp=100, max_hp=100, speed=100,
            statuses=(detail['status_id'],), flags={'status_details': [detail]}),
    })
    callbacks = StatusCallbackSystem(rules)
    event_number = 0

    def execute(current, event):
        nonlocal event_number
        event_number += 1
        result = callbacks.execute(current, unit_id='target', modifier_name=ENTANGLE_MODIFIER, event=event,
            trigger_event=GameEvent('status.lifecycle', source_id='caster',
                target_id='target', window=event, event_id=f'fixture:{event_number}:{event}'))
        assert result.ok, result.errors
        return result.after_state

    state = execute(state, 'OnStack')
    detail = state.units['target'].flags['status_details'][0]
    assert detail['stacks'] == 1 and detail['stack_policy'] == 'independent_count'
    for expected in (2, 3, 4, 5, 5, 5):
        state = execute(execute(state, 'OnBeforeBeingAttacked'), 'OnAfterBeingAttacked')
        detail = state.units['target'].flags['status_details'][0]
        assert detail['stacks'] == expected
        assert detail['dynamic_values']['__by_hash']['-434232686'] + 1 == expected
    assert state.units['target'].statuses == (detail['status_id'],)
