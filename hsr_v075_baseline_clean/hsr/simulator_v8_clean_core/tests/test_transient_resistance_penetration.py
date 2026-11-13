"""Source field admission and synthetic discriminators for transient penetration."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, DamageModifierIR, StatusCallbackIR, StatusCallbackTaskIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.damage import DamagePacket, DamageSystem
from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem
from hsr.simulator_v8_clean_core.tests.test_damage_modifier_transport import _case
from hsr.simulator_v8_clean_core.rules.ir import ActionDefinitionIR
from hsr.simulator_v8_clean_core.tbgd.lowering import _damage_modifier_terms
from hsr.simulator_v8_clean_core.systems.status import _map_stack_property
from hsr.simulator_v8_clean_core.systems.damage_pipeline import DamageStagePipeline


def test_pinned_penetration_fields_lower_to_shared_resistance_keys():
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main/Config/ConfigAbility/Avatar'
    found = set()
    def walk(value):
        if isinstance(value, dict):
            if value.get('$type') == 'RPG.GameCore.ModifyDamageData':
                for term in _damage_modifier_terms(value):
                    if term['field'].endswith('Penetrate'):
                        found.add(term['field'])
                        assert term['coverage_status'] == 'executable', term
                        element = term['field'].removeprefix('Attacker_').removesuffix('Penetrate')
                        assert term['bucket'] == 'resistance' and term['scope'] == 'attacker'
                        assert term['key'] == ('all_res_pen' if element == 'AllDamageType' else f'{element}_res_pen')
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    for path in root.glob('*.json'):
        walk(json.loads(path.read_text()))
    assert found == {'Attacker_PhysicalPenetrate', 'Attacker_AllDamageTypePenetrate', 'Attacker_WindPenetrate',
                     'Attacker_ImaginaryPenetrate', 'Attacker_QuantumPenetrate'}


@pytest.mark.parametrize('element,before,after', [('Quantum', .75, 1.10), ('Fire', .85, .95)])
def test_status_penetration_reaches_direct_and_dot_consumers(element, before, after):
    state, _, source = _case()
    actor = replace(state.units['actor'], resources={'all_res_pen': .05})
    target = replace(state.units['target'], resources={'Quantum_resistance': .30, 'all_resistance': .20})
    state = replace(state, units={'actor': actor, 'target': target})
    terms = []
    for prop, value in (('QuantumPenetrate', .25), ('AllDamageTypePenetrate', .10)):
        bucket, key, scope = _map_stack_property(prop)
        terms.append({'property': prop, 'bucket': bucket, 'key': key, 'scope': scope, 'value': value})
    buffed = replace(state, units={**state.units, 'actor': replace(actor, statuses=('pen',),
        flags={'status_details': [{'instance_id': 'pen', 'status_id': 'pen', 'modifiers': terms}]})})
    action = ActionDefinitionIR('definition', 'action', 1, 'Normal', 'SingleAttack', 'Single',
                                0, 0, 0, 0, (), (), (), element, source)
    packet = DamagePacket('actor', 'target', 'Normal', 'direct', action_definition=action,
        scaling_ratio=1, scaling_basis={'kind': 'unit_stat', 'unit_ref': 'attacker', 'stat': 'attack'},
        element_type=element, metadata={'crit_mode': 'noncrit'})
    system = DamageSystem()
    baseline, actual = system.apply_packet(state, packet), system.apply_packet(buffed, packet)
    assert baseline.ok and actual.ok
    loss = lambda result: next(m.before - m.after for m in result.mutations if m.path[-1] == 'hp')
    assert loss(actual) == pytest.approx(loss(baseline) * after / before)
    dot = DamageStagePipeline().calculate(buffed, family='dot', attacker_id='actor', target_id='target',
        producer_base_amount=100, element_type=element, source_trace={})
    assert dot.ok
    assert next(b.multiplier for b in dot.stage_buckets if b.stage == 'resistance') == pytest.approx(after)


@pytest.mark.parametrize('element,expected', [('Wind', 1.10), ('Fire', .90), (None, .90)])
def test_transient_penetration_uses_matching_element_and_stays_in_packet(element, expected):
    # Values deliberately isolate sum/filter behavior; they are not observed game answers.
    state, _, source = _case()
    actor = replace(state.units['actor'], resources={'Wind_res_pen': .10, 'all_res_pen': .05})
    target = replace(state.units['target'], resources={'all_resistance': .20, 'Wind_resistance': .30})
    state = replace(state, units={'actor': actor, 'target': target})
    terms = tuple(_damage_modifier_terms({'$type': 'RPG.GameCore.ModifyDamageData',
        'Attacker_WindPenetrate': {'IsDynamic': False, 'FixedValue': {'Value': .20}},
        'Attacker_AllDamageTypePenetrate': {'IsDynamic': False, 'FixedValue': {'Value': .05}},
    }))
    modifier = DamageModifierIR('pen', 'callback', 'task', 'status', 'OnBeforeHitAll', 'Caster', terms,
                                source, coverage_status='executable')
    callback = StatusCallbackIR('callback', 'status', 'OnBeforeHitAll', ('task',), source, (0, 0),
                                coverage_status='executable')
    task = StatusCallbackTaskIR('task', 'callback', 'status', 'OnBeforeHitAll', 0, '$.TaskList[0]',
                                'root', 'ModifyDamageData', source, coverage_status='executable')
    rules = RuleBook(CanonicalIR('validation', damage_modifiers=(modifier,)))
    produced = StatusCallbackSystem(rules)._execute_damage_modifier_task(
        state, callback, task, {'owner_id': 'actor', 'caster_id': 'actor'})
    assert produced.ok and len(produced.damage_modifiers) == 2
    assert produced.after_state == state and not produced.mutations and not produced.rng_events
    action = ActionDefinitionIR('definition', 'action', 1, 'Normal', 'SingleAttack', 'Single',
                                0, 0, 0, 0, (), (), (), element, source)
    packet = DamagePacket('actor', 'target', 'Normal', 'direct', action_definition=action,
                          scaling_ratio=1, scaling_basis={'kind': 'unit_stat', 'unit_ref': 'attacker', 'stat': 'attack'},
                          element_type=element, metadata={'crit_mode': 'noncrit'})
    system = DamageSystem()
    baseline = system.apply_packet(state, packet)
    actual = system.apply_packet(state, replace(packet, modifier_contributions=produced.damage_modifiers))
    assert baseline.ok and actual.ok
    loss = lambda result: next(m.before - m.after for m in result.mutations if m.path[-1] == 'hp')
    base_mult = .85
    assert loss(actual) == pytest.approx(loss(baseline) * expected / base_mult)
    forged = system.apply_packet(state, replace(packet, metadata={
        **packet.metadata, 'direct_modifier_terms': [m.formula_term() for m in produced.damage_modifiers]}))
    assert forged.ok and loss(forged) == loss(baseline)
    assert loss(system.apply_packet(state, packet)) == loss(baseline)
    unsupported = system.apply_packet(state, replace(packet, damage_formula_family='dot', amount=100,
                                                      modifier_contributions=produced.damage_modifiers))
    assert not unsupported.ok and 'transient_damage_modifiers_require_direct_consumer' in unsupported.errors
    assert not unsupported.mutations and not unsupported.events and not unsupported.rng_events
