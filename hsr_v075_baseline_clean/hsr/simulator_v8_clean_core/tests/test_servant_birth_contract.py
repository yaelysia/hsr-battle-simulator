"""Component birth checks: no mocked spawn/startup, not full character acceptance."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from hsr.simulator_v8_clean_core.builds.models import OwnedCombatantStatBinding
from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState, current_max_hp
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.rules.ir import (
    CanonicalIR, IRSource, ServantDefinitionIR, ServantOwnerRelationIR, UnitBirthTemplateIR,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.summon import SummonSystem
from hsr.simulator_v8_clean_core.systems.summon_runtime import empty_summon_runtime
from hsr.simulator_v8_clean_core.systems.unit_spawn import (
    UnitSpawnPlan, UnitSpawnSystem, _resolve_owned_combatant_stat,
)


def _case():
    source = IRSource('fixture:birth', 'ComponentServant', 'child')
    trace = source.to_json()
    relation = ServantOwnerRelationIR('relation', 'fixture:owner', 'card', (),
                                      (source,), coverage_status='executable')
    template = UnitBirthTemplateIR(
        'birth', 'servant', 'servant:child',
        {'side': 'summon', 'template_id': 'servant:child', 'level': 1,
         'hp': {'binding_kind': 'creation_parameter', 'parameter_name': 'CurrentHP',
                'parameter_family': 'current_hp'},
         'max_hp': {'binding_kind': 'creation_parameter', 'parameter_name': 'MaxHP',
                    'parameter_family': 'max_hp'},
         'attack': 10, 'defense': 10, 'speed': 100, 'energy': 0, 'max_energy': 0,
         'toughness': 0, 'max_toughness': 0, 'action_value': 100},
        {'summon_kind': 'servant', 'servant_definition_id': 'servant:child',
         'servant_ref': 'servant:child', 'summon_intent_id': 'servant:child',
         'owner_id': {'binding_kind': 'request_field', 'field': 'owner_id'},
         'summoner_id': {'binding_kind': 'request_field', 'field': 'summoner_id'},
         'team_side': {'binding_kind': 'owner_team_side'},
         'summon_source_trace': trace, 'servant_definition_source_trace': trace},
        {}, {'template_source_role': 'entry', 'owner_required': True,
             'creation_parameter_bindings': {'max_hp': 'MaxHP', 'current_hp': 'CurrentHP'}},
        source, coverage_status='executable',
    )
    definition = ServantDefinitionIR(
        'servant:child', 'servant:child', 'unit', (), {'startup_abilities': []}, {}, {}, {},
        source, birth_template_id='birth', coverage_status='executable',
        owner_relations=(relation,), spawn_sources=(source,),
    )
    rules = RuleBook(CanonicalIR('birth-component', servant_definitions=(definition,),
                                unit_birth_templates=(template,)))
    state = BattleState(units={'owner': UnitState('owner', 'ally', 'fixture:owner', hp=100, max_hp=100)},
                        global_flags={'summon_runtime': empty_summon_runtime()})
    initial = {'MaxHP': {'value': 240., 'hash': '101'},
               'CurrentHP': {'value': 180., 'hash': '102'}}
    return rules, state, definition, template, initial


def test_creation_parameters_survive_plan_consumption_and_actual_spawn():
    rules, state, definition, template, initial = _case()
    system = SummonSystem(rules)
    plan = system.plan_spawn_servant(state, definition, owner_id='owner',
                                     spawn_source=definition.source, initial_values=initial)
    assert plan.ok, plan.blocked_reason
    result = system.apply_spawn_servant(state, plan, initial_values=initial)
    assert result.plan.ok, result.plan.blocked_reason
    spawn = next(m for m in result.mutations if m.op == 'spawn')
    assert spawn.after['max_hp'] == 240 and spawn.after['hp'] == 180
    assert spawn.unit_birth_fact.parameter_values == {'MaxHP': 240, 'CurrentHP': 180}
    audit = RuntimeSourceAuditor(rules).validate_execution(result.mutations, result.records)
    assert audit.ok, audit.to_json()
    # Consumption uses separately supplied formal inputs, not plan metadata.
    for values in (None, {'MaxHP': {'value': 999., 'hash': '101'}, 'CurrentHP': initial['CurrentHP']}):
        failed = system.apply_spawn_servant(state, plan, initial_values=values)
        assert not failed.plan.ok and not failed.mutations and not failed.rng_events
    encoded = UnitSpawnPlan.from_json(plan.metadata['unit_spawn_plans'][0])
    with pytest.raises(ValueError, match='creation_max_hp_parameter_missing'):
        encoded.to_unit(expected_request=plan.spawn_requests[0], expected_template=template,
                        owner=state.units['owner'])
    assert state.units.keys() == {'owner'}


def test_birth_audit_recomputes_instead_of_trusting_reassociated_plan_copies():
    rules, state, definition, _, initial = _case()
    system = SummonSystem(rules)
    plan = system.plan_spawn_servant(state, definition, owner_id='owner', initial_values=initial)
    result = system.apply_spawn_servant(state, plan, initial_values=initial)
    spawn = next(m for m in result.mutations if m.op == 'spawn')
    records = tuple(r for r in result.records if r.get('mutation_id') == spawn.stable_id())
    audit = RuntimeSourceAuditor(rules).validate_execution(result.mutations, result.records)
    assert audit.ok, audit.to_json()
    payload = deepcopy(spawn.to_json()['after'])
    payload['hp'] = payload['max_hp'] = 999.
    forged = replace(spawn, after=payload, mutation_id='')
    reassociated = deepcopy(list(records))
    for r in reassociated:
        r['mutation_id'] = forged.stable_id()
        r['payload']['mutation_ids'] = [forged.stable_id() if value == spawn.stable_id() else value
                                        for value in r['payload']['mutation_ids']]
        r['payload']['plan']['metadata']['unit_spawn_plans'][0]['unit'].update(hp=999., max_hp=999.)
    denied = RuntimeSourceAuditor(rules).validate_execution((forged,), tuple(reassociated))
    assert not denied.ok
    assert 'servant_spawn_formal_birth_payload_mismatch' in {v.reason for v in denied.violations}
    missing = replace(spawn, unit_birth_fact=None)
    assert not RuntimeSourceAuditor(rules).validate_execution((missing,), records).ok


@pytest.mark.parametrize('missing_path', [('global_flags', 'summon_runtime'),
                                         ('global_flags', 'dynamic_value_store')])
def test_birth_audit_requires_complete_native_group_even_without_missing_records(missing_path):
    rules, state, definition, _, initial = _case()
    system = SummonSystem(rules)
    plan = system.plan_spawn_servant(state, definition, owner_id='owner', initial_values=initial)
    result = system.apply_spawn_servant(state, plan, initial_values=initial)
    removed = next(m for m in result.mutations if m.path == missing_path)
    mutations = tuple(m for m in result.mutations if m is not removed)
    records = tuple(r for r in result.records if r.get('mutation_id') != removed.stable_id())
    denied = RuntimeSourceAuditor(rules).validate_execution(mutations, records)
    assert not denied.ok
    assert 'servant_birth_native_group_mismatch' in {v.reason for v in denied.violations}


def test_birth_audit_cannot_be_bypassed_by_renaming_producer_and_removing_native_fact():
    from hsr.simulator_v8_clean_core.rules.ir import EffectIR
    rules, state, definition, _, initial = _case()
    unrelated = EffectIR('unrelated-delay', 'ModifyActionDelay', {'standard': {}},
                         definition.source, 'executable')
    rules = RuleBook(replace(rules.ir, effects=(unrelated,)))
    system = SummonSystem(rules)
    plan = system.plan_spawn_servant(state, definition, owner_id='owner', initial_values=initial)
    result = system.apply_spawn_servant(state, plan, initial_values=initial)
    spawn = next(m for m in result.mutations if m.op == 'spawn')
    payload = deepcopy(spawn.to_json()['after'])
    payload.update(hp=999., max_hp=999.)
    forged = replace(spawn, after=payload, source='effect_system', unit_birth_fact=None,
                     metadata={'effect_id': unrelated.effect_id,
                               'effect_source': unrelated.source.to_json()}, mutation_id='')
    records = tuple({**r, 'mutation_id': forged.stable_id()} for r in result.records
                    if r.get('mutation_id') == spawn.stable_id())
    denied = RuntimeSourceAuditor(rules).validate_execution((forged,), records)
    assert not denied.ok
    assert 'servant_spawn_native_birth_fact_missing' in {v.reason for v in denied.violations}


def test_formal_creation_expression_cannot_be_replaced_by_self_consistent_birth_inputs():
    from hsr.simulator_v8_clean_core.ir_types import IRSource
    from hsr.simulator_v8_clean_core.rules.ir import EffectIR
    from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry
    from hsr.simulator_v8_clean_core.systems.status import StatusSystem
    from hsr.simulator_v8_clean_core.tbgd.lowering import _effect_payload
    rules, state, definition, _, _ = _case()
    template = rules.ir.unit_birth_templates[0]
    ref = "servant:7001"
    template = replace(template, entity_ref=ref, unit_field_specs={**template.unit_field_specs, "template_id": ref},
        flag_specs={**template.flag_specs, "servant_ref": ref, "servant_definition_id": ref, "summon_intent_id": ref})
    definition = replace(definition, servant_definition_id=ref, servant_ref=ref)
    rules = RuleBook(replace(rules.ir, servant_definitions=(definition,), unit_birth_templates=(template,)))
    source = IRSource('fixture-create', 'AbilityTask', 'create', {'json_path': '$.CreateServant'})
    raw = {'$type': 'RPG.GameCore.CreateServant',
           'ServantID': {'IsDynamic': False, 'FixedValue': {'Value': 7001}},
           'DynamicValues': {'MaxHP': {'IsDynamic': False, 'FixedValue': {'Value': 20}},
                             'CurrentHP': {'IsDynamic': False, 'FixedValue': {'Value': 15}}}}
    payload = _effect_payload(raw, 'CreateServant', '', source=source)
    spawn_source = IRSource(**payload['standard']['spawn_source'])
    definition = replace(definition, spawn_sources=(spawn_source,))
    template = replace(template, flag_specs={**template.flag_specs, 'summon_source_trace': spawn_source.to_json()})
    effect = EffectIR('create-fixture-servant', 'CreateServant', payload, source, 'executable')
    rules = RuleBook(replace(rules.ir, servant_definitions=(definition,), unit_birth_templates=(template,), effects=(effect,)))
    result = EffectRegistry(StatusSystem(rules)).execute(effect, EffectExecutionContext(state, 'owner', 'create'))
    assert not result.unsupported, result.unsupported
    assert RuntimeSourceAuditor(rules).validate_execution(result.mutations, result.records).ok
    fact = result.mutations[0].effect_execution_fact
    system = SummonSystem(rules)
    alternate = {name: {'value': value, 'hash': payload['standard']['dynamic_values'][name]['hash']}
                 for name, value in (('MaxHP', 999.), ('CurrentHP', 500.))}
    plan = system.plan_spawn_servant(state, definition, owner_id='owner', spawn_source=spawn_source,
                                     initial_values=alternate)
    wrong = system.apply_spawn_servant(state, plan, initial_values=alternate)
    assert wrong.plan.ok
    forged = tuple(replace(mutation, effect_execution_fact=fact) for mutation in wrong.mutations)
    denied = RuntimeSourceAuditor(rules).validate_execution(forged, wrong.records)
    assert not denied.ok
    assert 'effect_native_write_group_mismatch' in {v.reason for v in denied.violations}


def test_owned_birth_inherits_effective_hp_and_other_declared_combat_stats():
    source = IRSource('fixture:birth', 'ComponentStat', 'inherit')
    bindings = tuple(OwnedCombatantStatBinding(
        stat, kind, stat, '2' if kind == 'owner_linear' else None,
        '10' if kind == 'owner_linear' else None, (source,),
    ) for stat, kind in [('max_hp', 'owner_linear'), ('speed', 'owner_linear'),
                         ('attack', 'owner_field'), ('critical_chance', 'owner_resource')])
    # Only the stat resolver's typed binding contract is under test here.
    build = SimpleNamespace(stat_bindings=bindings)
    owner = UnitState('owner', 'ally', 'fixture:owner', hp=100, max_hp=100, speed=100, attack=20,
        resources={'critical_chance': .05}, flags={'status_details': [{'modifiers': [
            {'bucket': 'attribute', 'key': 'hp_added_ratio', 'value': .5},
            {'bucket': 'attribute', 'key': 'hp_convert', 'value': 30},
            {'bucket': 'attribute', 'key': 'speed_delta', 'value': 20},
            {'bucket': 'attribute', 'key': 'attack_added_ratio', 'value': .5},
            {'bucket': 'crit', 'key': 'critical_chance', 'value': .1},
        ]}]})
    assert current_max_hp(owner) == 180 and owner.max_hp == 100
    expected = {'max_hp': 370, 'speed': 250, 'attack': 30, 'critical_chance': .15}
    for stat, value in expected.items():
        assert _resolve_owned_combatant_stat(owner, build, stat) == pytest.approx(value)
    sibling = replace(owner, unit_id='sibling', flags={})
    assert _resolve_owned_combatant_stat(sibling, build, 'max_hp') == 210

def test_mechanism_bar_dotted_summoner_target_resolves_the_actual_owner():
    from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
    from hsr.simulator_v8_clean_core.rules.ir import EffectIR
    from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry

    rules, state, definition, _, initial = _case()
    system = SummonSystem(rules)
    plan = system.plan_spawn_servant(state, definition, owner_id='owner',
                                     spawn_source=definition.source, initial_values=initial)
    spawned = system.apply_spawn_servant(state, plan, initial_values=initial)
    assert spawned.plan.ok, spawned.plan.blocked_reason
    after = MutationReducer().apply_all(state, spawned.mutations)
    servant_id = next(unit_id for unit_id in after.units if unit_id != 'owner')
    assert after.units[servant_id].flags['summoner_id'] == 'owner'

    standard = {
        'kind': 'mechanism_bar_state', 'opcode': 'SetSummonerEnergyBarState',
        'target_alias': 'Caster.GetSummoner', 'bar_type': 'Progress', 'active': 'True',
        'state': None,
        'current_count': {'schema_version': 'hsr.numeric_expression.v1', 'kind': 'fixed',
                          'value': 1.0, 'supported': True},
        'max_count': {'schema_version': 'hsr.numeric_expression.v1', 'kind': 'fixed',
                      'value': 2.0, 'supported': True},
    }
    source = IRSource('fixture:bar', 'AbilityTask', 'bar', {'json_path': '$.bar'})
    effect = EffectIR('fixture:summoner-bar', 'SetSummonerEnergyBarState',
                      {'standard': standard}, source, 'executable')
    result = EffectRegistry().execute(
        effect, EffectExecutionContext(after, servant_id, 'fixture', owner_id='owner'))
    assert not result.unsupported, result.unsupported
    final = MutationReducer().apply_all(after, result.mutations)
    assert final.units['owner'].flags['mechanism_bars']['Progress'] == {
        'active': 'True', 'current_count': 1.0, 'max_count': 2.0,
    }
    assert 'mechanism_bars' not in final.units[servant_id].flags

    # A dotted relation is a real relation, not an alias fallback: an owner
    # without a summoner has no target and therefore no mutation.
    blocked = EffectRegistry().execute(
        effect, EffectExecutionContext(after, 'owner', 'fixture', owner_id='owner'))
    assert blocked.unsupported
    assert not blocked.mutations and not blocked.events and not blocked.rng_events
