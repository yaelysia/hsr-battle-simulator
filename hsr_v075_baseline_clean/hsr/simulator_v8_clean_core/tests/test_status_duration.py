"""Default status durations count holder turn ends, with explicit immediate stepping."""
from dataclasses import replace

import pytest

from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import _standard_add_modifier_payload
from hsr.simulator_v8_clean_core.tests.test_status_control_resistance import _source_case, _state


@pytest.mark.parametrize('owner,immediate,first_tick', [
    ('holder', False, 8), ('holder', True, 7), ('opponent', False, 8),
])
def test_default_duration_keeps_both_holder_actions(owner, immediate, first_tick):
    rules, effect, *_ = _source_case()
    standard = _standard_add_modifier_payload({
        'ModifierName': {'Value': effect.payload['standard']['modifier_name']},
        'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Caster'},
        'LifeTime': {'IsDynamic': False, 'FixedValue': {'Value': 2}},
        'LifeStepImmediately': immediate,
    })
    effect = replace(effect, payload={**effect.payload, 'standard': {
        **effect.payload['standard'], **standard,
    }})
    state = replace(_state(), global_flags={'turn_owner_id': owner, 'turn_sequence_index': 7})
    system, reducer = StatusSystem(rules), MutationReducer()
    applied = system.apply_add_modifier(state, effect, caster_id='holder', source_id='duration-check',
                                       dynamic_values={'1153510288': .7})
    assert applied.ok, applied.unsupported
    state = reducer.apply_all(state, applied.mutations)
    detail = state.units['holder'].flags['status_details'][0]
    assert detail['life_step_moment'] == 'TurnEnd' and detail['remaining_duration'] == 2
    assert not system.apply_lifecycle_tick(state, 'holder', detail, 'ModifierPhase1End').mutations
    if owner == 'holder' and not immediate:
        assert not system.apply_lifecycle_tick(state, 'holder', detail, 'TurnEnd').mutations
    for turn, remaining in ((first_tick, 1), (first_tick + 1, 0)):
        state = replace(state, global_flags={'turn_owner_id': 'holder', 'turn_sequence_index': turn})
        detail = state.units['holder'].flags['status_details'][0]
        result = system.apply_lifecycle_tick(state, 'holder', detail, 'TurnEnd')
        assert result.ok
        state = reducer.apply_all(state, result.mutations)
        details = state.units['holder'].flags['status_details']
        assert (details[0]['remaining_duration'] if details else 0) == remaining
