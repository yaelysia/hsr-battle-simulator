"""Adjacency uses a retained position; it does not make a dead unit targetable."""
from dataclasses import replace

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.systems.unit_lifecycle import UnitLifecycleSystem
from hsr.simulator_v8_clean_core.systems.unit_relation import EntityRelationResolver, TargetEvaluationContext


def test_defeated_anchor_keeps_living_neighbours_until_removed():
    state = BattleState(units={
        key: UnitState(key, 'enemy', 'fixture', hp=100, max_hp=100, flags={'position': index})
        for index, key in enumerate(('left', 'anchor', 'right', 'far'))
    })
    resolver = EntityRelationResolver()
    context = TargetEvaluationContext('left')
    def adjacent(current):
        return resolver.resolve(current, 'formation.adjacent', context, subject_ids=('anchor',))
    assert adjacent(state).target_ids == ('left', 'right')
    dead = replace(state, units={**state.units, 'anchor': replace(
        state.units['anchor'], hp=0, lifecycle_status='defeated',
    )})
    assert adjacent(dead).target_ids == ('left', 'right')
    assert not UnitLifecycleSystem().can_target(dead, 'anchor')[0]
    # Other dead units are not returned or treated as living neighbours.
    dead_neighbour = replace(dead, units={**dead.units, 'right': replace(
        dead.units['right'], hp=0, lifecycle_status='defeated',
    )})
    assert adjacent(dead_neighbour).target_ids == ('left', 'far')
    removed = replace(dead, units={**dead.units, 'anchor': replace(
        dead.units['anchor'], lifecycle_status='removed',
    )})
    assert adjacent(removed).blocked_reason == 'formation_anchor_not_present'
    ambiguous = replace(dead, units={**dead.units, 'right': replace(
        dead.units['right'], flags={'position': 1},
    )})
    assert adjacent(ambiguous).blocked_reason == 'formation_position_duplicate'
