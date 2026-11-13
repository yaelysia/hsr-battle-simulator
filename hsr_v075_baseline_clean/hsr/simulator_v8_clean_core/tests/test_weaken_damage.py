"""Weaken changes outgoing ordinary damage, independently of damage bonuses."""
from dataclasses import replace

import pytest

from hsr.simulator_v8_clean_core.rules.ir import ActionDefinitionIR
from hsr.simulator_v8_clean_core.systems.damage import DamagePacket, DamageSystem
from hsr.simulator_v8_clean_core.systems.damage_pipeline import DamageStageBucket, DamageStagePipeline
from hsr.simulator_v8_clean_core.systems.status import _map_stack_property
from hsr.simulator_v8_clean_core.tests.test_damage_modifier_transport import _case


def test_weaken_is_an_actor_multiplier_and_does_not_change_break_damage():
    state, _, source = _case()
    bucket, key, scope = _map_stack_property('FatigueRatio')
    actor = state.units['actor']
    weakened = replace(state, units={**state.units, 'actor': replace(actor,
        statuses=('weak',), flags={'status_details': [{
            'instance_id': 'weak', 'status_id': 'weak', 'modifiers': [
                {'bucket': bucket, 'key': key, 'scope': scope, 'value': .2},
            ],
        }]})})
    action = ActionDefinitionIR('definition', 'action', 1, 'Normal', 'SingleAttack', 'Single',
                                0, 0, 0, 0, (), (), (), 'Fire', source)
    packet = DamagePacket('actor', 'target', 'Normal', 'direct', action_definition=action,
        scaling_ratio=1, scaling_basis={'kind': 'unit_stat', 'unit_ref': 'attacker', 'stat': 'attack'},
        element_type='Fire', metadata={'crit_mode': 'noncrit'})
    baseline = DamageSystem().apply_packet(state, packet)
    actual = DamageSystem().apply_packet(weakened, packet)
    assert baseline.ok and actual.ok
    loss = lambda result: next(m.before - m.after for m in result.mutations if m.path[-1] == 'hp')
    assert loss(actual) == pytest.approx(loss(baseline) * .8)
    pipeline = DamageStagePipeline()
    for family, factor in [('dot', .8), ('additional', .8), ('break', 1), ('super_break', 1)]:
        args = dict(family=family, attacker_id='actor', target_id='target',
                    producer_base_amount=100, element_type='Fire', source_trace={})
        if family == 'additional':
            args['critical_bucket'] = DamageStageBucket('critical', True, 1.0)
        original, reduced = pipeline.calculate(state, **args), pipeline.calculate(weakened, **args)
        assert original.ok and reduced.ok
        assert reduced.final_amount == pytest.approx(original.final_amount * factor)
