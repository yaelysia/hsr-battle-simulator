"""Real equipment cleanup source against explicit multiple-caster boundary states."""
import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.evaluator import RuleEvaluator
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, ConditionIR, EffectIR, IRSource
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.systems.status_callbacks import _condition_context
from hsr.simulator_v8_clean_core.systems.target import TargetSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    CONDITION_EXPRESSION_NODE_SCHEMA, _typed_condition_payload,
    _attach_target_expressions_to_effect_payload, _effect_coverage_status,
    _equipment_task_admission, _standard_remove_modifier_payload, _status_callback_task_admission,
)
from hsr.simulator_v8_clean_core.tbgd.target_source import build_target_language_definitions


@lru_cache(maxsize=1)
def _case():
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    relative = 'Config/ConfigAbility/Equip/EquipmemtAbility.json'
    abilities = json.loads((root / relative).read_text())['AbilityList']
    index, ability = next((i, a) for i, a in enumerate(abilities) if a['Name'] == 'Ability20005')
    raw = ability['Modifiers']['MEquip_20005_Main']['_CallbackList'][0]['CallbackConfig'][0]
    source = IRSource(relative, 'RemoveModifier', 'cleanup', {
        'json_path': f'$.AbilityList[{index}].Modifiers.MEquip_20005_Main._CallbackList[0].CallbackConfig[0]',
    })
    languages = build_target_language_definitions(root)
    payload, targets = _attach_target_expressions_to_effect_payload(
        {'standard': _standard_remove_modifier_payload(raw, 'RemoveModifier', '')}, raw,
        effect_id='cleanup', source=source, target_language_definitions=languages,
    )
    assert _effect_coverage_status('RemoveModifier', payload) == 'executable'
    effect = EffectIR('cleanup', 'RemoveModifier', payload, source, 'executable')
    rules = RuleBook(CanonicalIR('test', effects=(effect,), target_expressions=(
        *targets, *(language.expression for language in languages),
    )))
    return rules, effect, raw


def _state(effect):
    status_id = effect.payload['standard']['status_id']
    # Boundary fixture: two casters share a modifier name on a third ally.
    details = [{'instance_id': caster + ':buff', 'status_id': status_id, 'caster_id': caster,
                'owner_id': 'target', 'modifier_name': status_id.removeprefix('modifier:')}
               for caster in ('other', 'caster')]
    return BattleState(units={
        **{key: UnitState(key, 'ally', 'fixture', hp=100, max_hp=100) for key in ('caster', 'other')},
        'target': UnitState('target', 'ally', 'fixture', hp=100, max_hp=100,
                            statuses=(status_id,), flags={'status_details': details}),
    })


def test_source_closed_compound_target_is_required_for_equipment_admission():
    _, effect, raw = _case()
    assert effect.payload['standard']['only_remove_caster_added'] is True
    assert _equipment_task_admission('OnDestroy', 'RemoveModifier', raw, modifier_name='')[0] == 'blocked'
    assert _equipment_task_admission('OnDestroy', 'RemoveModifier', raw, modifier_name='',
                                    source_effect_payload=dict(effect.payload)) == ('executable', '')
    for event in ('OnStack', 'OnHPChange', 'OnDestroy', 'OnBeforeDying', 'OnListenCharacterDie'):
        assert _status_callback_task_admission(event, 'RemoveModifier', raw)[0] == 'blocked'
        assert _status_callback_task_admission(event, 'RemoveModifier', raw,
                    source_effect_payload=dict(effect.payload)) == ('executable', '')
        blocked = {**effect.payload, 'standard': {**effect.payload['standard'],
                   'target_expression_coverage_status': 'blocked'}}
        assert _status_callback_task_admission(event, 'RemoveModifier', raw,
                    source_effect_payload=blocked)[0] == 'blocked'
    invalid = _standard_remove_modifier_payload({**raw, 'OnlyRemoveCasterAdded': 'true'}, 'RemoveModifier', '')
    assert _effect_coverage_status('RemoveModifier', {'standard': invalid}) == 'blocked'


def test_caster_cleanup_preserves_foreign_instance_and_is_idempotent():
    rules, effect, _ = _case()
    state = _state(effect)
    system = StatusSystem(rules)
    result = system.apply_remove_modifier(state, effect, caster_id='caster', source_id='cleanup')
    assert result.ok, result.unsupported
    after = MutationReducer().apply_all(state, result.mutations)
    remaining = after.units['target'].flags['status_details']
    assert [detail['caster_id'] for detail in remaining] == ['other']
    assert after.units['target'].statuses == state.units['target'].statuses
    repeated = system.apply_remove_modifier(after, effect, caster_id='caster', source_id='cleanup')
    assert repeated.ok and not repeated.mutations and not repeated.rng_events
    assert all(record['process_only'] for record in repeated.records)


@pytest.mark.parametrize('failure', ['caster_missing', 'flag_invalid'])
def test_cleanup_missing_authority_is_atomic(failure):
    rules, effect, _ = _case()
    state = _state(effect)
    if failure == 'caster_missing':
        owner = state.units['target']
        details = [dict(detail) for detail in owner.flags['status_details']]
        details[0].pop('caster_id')
        state = replace(state, units={**state.units, 'target': replace(owner, flags={'status_details': details})})
    else:
        effect = replace(effect, payload={**effect.payload, 'standard': {
            **effect.payload['standard'], 'only_remove_caster_added': 1,
        }})
    result = StatusSystem(rules).apply_remove_modifier(state, effect, caster_id='caster', source_id='cleanup')
    assert not result.ok and not result.mutations and not result.events and not result.rng_events


def test_creation_emitter_is_not_a_unit_but_unknown_target_stays_blocked():
    rules, effect, _ = _case()
    state = _state(effect)
    detail = state.units['target'].flags['status_details'][1]
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    relative = 'Config/ConfigAbility/Equip/RelicAbility.json'
    abilities = json.loads((root / relative).read_text())['AbilityList']
    index, ability = next((i, a) for i, a in enumerate(abilities) if a['Name'] == 'Ability53021')
    raw = ability['Modifiers']['MRelic_302_Main']['_CallbackList'][0]['CallbackConfig'][0]['Predicate']
    source = IRSource(relative, 'ByTargetTeam', 'creation-team', {
        'json_path': f'$.AbilityList[{index}].Modifiers.MRelic_302_Main._CallbackList[0].CallbackConfig[0].Predicate',
    })
    condition = ConditionIR('creation-team', 'ByTargetTeam', _typed_condition_payload(
        'ByTargetTeam', {key: value for key, value in raw.items() if key != '$type'}, source=source,
    ), source, 'executable', expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA)
    for target, expected in (('target', True), ('unknown-unit', None)):
        event = GameEvent(event_id='creation', event_type='unit.created', source_id='scenario:setup', target_id=target,
                          window='OnListenCharacterCreate', payload={'param_entity_id': target})
        context = _condition_context(rules, state, detail, event, condition=condition,
                                     targets=TargetSystem(rules))
        result = RuleEvaluator().evaluate_condition_result(condition, context)
        assert result.result is expected
        assert result.ok is (expected is not None)
        if expected is None:
            assert 'target_context_unknown_identity:unknown-unit' in context.target_resolution_errors.values()
