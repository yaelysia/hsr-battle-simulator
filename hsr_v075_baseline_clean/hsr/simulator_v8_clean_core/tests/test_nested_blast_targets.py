"""A retargeted primary must retain its actual formation neighbours."""
from dataclasses import replace

import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState, TargetResolution
from hsr.simulator_v8_clean_core.systems.ability import _damage_targets_for_emission


def test_nested_primary_recomputes_neighbours_including_a_defeated_anchor():
    state = BattleState(units={
        'actor': UnitState('actor', 'ally', 'fixture', hp=100, max_hp=100, flags={'position': 0}),
        **{uid: UnitState(uid, 'enemy', 'fixture', hp=100, max_hp=100, flags={'position': pos})
           for pos, uid in enumerate(('left', 'middle', 'right'))},
    })
    scoped = TargetResolution(primary='middle', selected=('middle',), impact_group=('middle',),
                              source='task_graph_executor')
    assert _damage_targets_for_emission('adjacent', scoped, state=state, attacker_id='actor') == ('left', 'right')
    dead = replace(state, units={**state.units, 'middle': replace(state.units['middle'], hp=0, lifecycle_status='defeated')})
    assert _damage_targets_for_emission('adjacent', scoped, state=dead, attacker_id='actor') == ('left', 'right')
    edge = replace(scoped, primary='right', selected=('right',), impact_group=('right',))
    assert _damage_targets_for_emission('adjacent', edge, state=state, attacker_id='actor') == ('middle',)
    invalid = replace(state, units={**state.units, 'middle': replace(state.units['middle'], flags={})})
    with pytest.raises(ValueError, match='formation_position_missing'):
        _damage_targets_for_emission('adjacent', scoped, state=invalid, attacker_id='actor')
