"""Transient modifier boundary checks; synthetic inputs are not game evidence."""
from dataclasses import replace

import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_fixed
from hsr.simulator_v8_clean_core.rules.ir import (
    ActionDefinitionIR, CanonicalIR, CharacterDataCardIR, CharacterEidolonSlotIR, DamageModifierIR, IRSource,
    StatusCallbackIR, StatusCallbackTaskIR,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.damage import DamagePacket, DamageSystem
from hsr.simulator_v8_clean_core.systems.dynamic_values import (
    character_skill_param_binding_sources, character_skill_param_declared_keys,
)
from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem


def _case(*, broken_term=False, wrong_source=False):
    source = IRSource('synthetic', 'validation', 'modifier')
    term = {'coverage_status': 'executable', 'bucket': 'damage_bonus',
            'key': 'damage_added_ratio', 'numeric_expr': numeric_fixed(0.1)}
    modifier = DamageModifierIR(
        'modifier', 'callback', 'task', 'status', 'OnBeforeHitAll', 'Caster',
        (term, {**term, 'numeric_expr': {'kind': 'unsupported'}}) if broken_term else (term,),
        source, coverage_status='executable',
    )
    task = StatusCallbackTaskIR(
        'task', 'callback', 'status', 'OnBeforeHitAll', 0, '$.TaskList[0]', 'root',
        'ModifyDamageData', replace(source, raw_id='different') if wrong_source else source,
        coverage_status='executable',
    )
    callback = StatusCallbackIR('callback', 'status', 'OnBeforeHitAll', ('task',),
                                source, (0, 0), coverage_status='executable')
    rules = RuleBook(CanonicalIR('validation', damage_modifiers=(modifier,)))
    state = BattleState(units={
        'actor': UnitState('actor', 'ally', 'validation', hp=1000, max_hp=1000, attack=100),
        'target': UnitState('target', 'enemy', 'validation', hp=1000, max_hp=1000),
    })
    result = StatusCallbackSystem(rules)._execute_damage_modifier_task(
        state, callback, task, {'owner_id': 'actor', 'caster_id': 'actor'},
    )
    return state, result, source


def test_producer_facts_reach_damage_once_without_consuming_audit_metadata():
    state, produced, source = _case()
    assert produced.ok and len(produced.damage_modifiers) == 1
    assert produced.after_state == state and not produced.mutations and not produced.rng_events
    action = ActionDefinitionIR(
        'definition', 'action', 1, 'Normal', 'SingleAttack', 'Single',
        0, 0, 0, 0, (), (), (), 'Fire', source,
    )
    packet = DamagePacket(
        'actor', 'target', 'Normal', 'direct', action_definition=action,
        scaling_ratio=1, scaling_basis={'kind': 'unit_stat', 'unit_ref': 'attacker', 'stat': 'attack'},
        element_type='Fire', metadata={'crit_mode': 'noncrit'},
    )
    system = DamageSystem()
    baseline = system.apply_packet(state, packet)
    actual = system.apply_packet(state, replace(packet, modifier_contributions=produced.damage_modifiers))
    forged = system.apply_packet(state, replace(packet, metadata={
        **packet.metadata, 'direct_modifier_terms': [produced.damage_modifiers[0].formula_term()],
    }))
    assert baseline.ok and actual.ok and forged.ok
    loss = lambda result: next(m.before - m.after for m in result.mutations if m.path[-1] == 'hp')
    assert loss(actual) == pytest.approx(loss(baseline) * 1.1)
    assert loss(forged) == loss(baseline)
    assert state.units['target'].hp == 1000


@pytest.mark.parametrize('failure', ['broken_term', 'wrong_source'])
def test_incomplete_modifier_cannot_leak_partial_facts_or_state(failure):
    state, result, _ = _case(**{failure: True})
    assert not result.ok and result.errors
    assert result.after_state == state
    assert not result.mutations and not result.rng_events and not result.damage_modifiers


@pytest.mark.parametrize('case', ['selected', 'unselected', 'foreign_card', 'bad_index', 'read_mismatch'])
def test_rank_parameters_require_selected_source_closed_build(case):
    source = IRSource('synthetic', 'validation', 'rank')
    read = {'Type': 'SkillRank', 'TriggerKey': 'Rank01', 'Index': 0}
    card = CharacterDataCardIR(
        card_id='card', entity_ref='avatar:fixture', profile_id='profile', skill_ids=(),
        skill_formula_binding_ids=(), bounce_policy_ids=(), action_set={}, source=source,
        dynamic_value_bindings={'by_hash': {'123': {'read_info': read}}},
        eidolon_slot_ids=('rank',),
    )
    binding = {'read_info': dict(read), 'param_index': 0, 'rank': 1}
    if case == 'bad_index':
        binding['param_index'] = 1
    if case == 'read_mismatch':
        binding['read_info']['TriggerKey'] = 'Rank02'
    slot = CharacterEidolonSlotIR(
        'rank', 'card', 'fixture', 1, 'rank-id', (), source,
        semantics={'param_values': [0.1], 'dynamic_value_bindings': {'by_hash': {'123': binding}}},
        coverage_status='executable', blocked_reason='',
    )
    rules = RuleBook(CanonicalIR('validation', character_data_cards=(card,), character_eidolon_slots=(slot,)))
    state = BattleState(units={'actor': UnitState('actor', 'ally', 'avatar:fixture', flags={
        'build_mode': 'assembled_character_build', 'character_build_battle_admission_status': 'admitted',
        'character_data_card_id': 'other' if case == 'foreign_card' else 'card',
        'selected_eidolon_slot_ids': () if case == 'unselected' else ('rank',),
    })})
    sources = character_skill_param_binding_sources(rules, state, ('actor',))
    values = [entry['value'] for item in sources for entry in item['entries'].values()]
    assert values == ([0.1] if case == 'selected' else [])
    assert character_skill_param_declared_keys(rules, state, 'actor') == (('123',), ())
    assert not character_skill_param_binding_sources(rules, state, ('actor',), excluded_hashes=('123',))
