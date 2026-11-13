"""Explicit Count replaces a remaining-use counter; layers remain distinct."""
from dataclasses import replace
import json
from pathlib import Path
import pytest

from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_fixed
from hsr.simulator_v8_clean_core.rules.ir import IRSource
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.tests.test_status_control_resistance import _source_case, _state
from hsr.simulator_v8_clean_core.tbgd.lowering import _standard_add_modifier_payload
from hsr.simulator_v8_clean_core.tbgd.adopted_modifier_counts import ADOPTED_DYNAMIC_MAXIMUMS, LINGSHA_SOURCE
from hsr.simulator_v8_clean_core.tbgd.lowering import _effect_payload


@pytest.mark.parametrize('bounded,retain_zero', ((False, False), (True, False), (False, True)))
def test_explicit_count_initializes_refreshes_and_consumes_independently(bounded, retain_zero):
    rules, effect, definition, *_ = _source_case()
    missing = {'kind': 'missing'}
    name = 'fixture_remaining_uses'
    definition = replace(definition, fields={**definition.fields, 'modifier_name': name,
        'max_layer_expr': numeric_fixed(4) if bounded else missing,
        'layer_add_when_stack_expr': numeric_fixed(1) if bounded else missing,
        'behavior_flags': ['RetainCountZero'] if retain_zero else [], 'stack_properties': [], 'dynamic_values': {},
        'dynamic_value_bindings': {}, 'callback_events': []})
    standard = {**effect.payload['standard'], 'modifier_name': name, 'count': numeric_fixed(3),
                'dynamic_values': {}, 'dynamic_value_requests': []}
    effect = replace(effect, status_callback_ids=(), payload={**effect.payload, 'standard': standard})
    rules = RuleBook(replace(rules.ir, entities=(definition,), effects=(effect,),
                             status_callbacks=(), status_callback_tasks=()))
    system, reducer, state = StatusSystem(rules), MutationReducer(), _state()
    for count in ((0, 3, 5) if retain_zero else (3, 5)):
        request = replace(effect, payload={**effect.payload, 'standard': {**standard, 'count': numeric_fixed(count)}})
        result = system.apply_add_modifier(state, request, caster_id='holder', source_id='counter-task')
        assert result.ok, result.unsupported
        state = reducer.apply_all(state, result.mutations)
        detail = state.units['holder'].flags['status_details'][0]
        assert detail['stacks'] == (min(count, 4) if bounded else count)
        assert detail['max_stacks'] == (4 if bounded else None)
        assert detail['stack_policy'] == ('additive_stack' if bounded else 'independent_count')
    if bounded:
        return
    implicit = replace(effect, effect_id='implicit-count-write', opcode='SetModifierValue',
        payload={'standard': {'value_kind_from_instance': True}})
    system = StatusSystem(RuleBook(replace(rules.ir, effects=(effect, implicit))))
    changed = system.modify_modifier_value(state, 'holder', name, 'Layer', 'Add', -1,
        caster_id='holder', metadata={'effect_id': implicit.effect_id})
    assert changed.ok, changed.unsupported
    assert reducer.apply_all(state, changed.mutations).units['holder'].flags['status_details'][0]['stacks'] == 4
    for remaining in (4, 3, 2, 1, 0):
        result = system.modify_modifier_value(state, 'holder', name, 'independent_count', 'Add', -1, caster_id='holder', metadata={})
        assert result.ok, result.unsupported
        state = reducer.apply_all(state, result.mutations)
        if remaining or retain_zero:
            assert state.units['holder'].flags['status_details'][0]['stacks'] == remaining
        else:
            assert not state.units['holder'].statuses
    if retain_zero:
        result = system.modify_modifier_value(state, 'holder', name, 'independent_count', 'Add', 2,
                                              caster_id='holder', metadata={})
        assert result.ok, result.unsupported
        assert reducer.apply_all(state, result.mutations).units['holder'].flags['status_details'][0]['stacks'] == 2


def test_fuyuan_index_tag_is_not_a_zero_layer_effect():
    source = IRSource('Config/ConfigAbility/Avatar/Avatar_Lingsha_00_Ability.json', 'AbilityTask', 'birth-tag')
    raw = {'ModifierName': {'Value': 'MAvatar_Lingsha_BPSkill_BattleEvent'},
           'Count': {'IsDynamic': True, 'PostfixExpr': {'OpCodes': 'AQAR', 'FixedValues': [], 'DynamicHashes': [-584750360]}}}
    payload = _standard_add_modifier_payload(raw, source=source)
    assert 'count' not in payload and payload['count_admission']['kind'] == 'presence_identity_tag'


def test_fuyuan_limit_is_the_source_talent_parameter():
    rule = ADOPTED_DYNAMIC_MAXIMUMS[(LINGSHA_SOURCE, 'Lingsha_AttackTime')]
    table = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main/ExcelOutput/AvatarSkillConfig.json'
    values = {r['ParamList'][4]['Value'] for r in json.loads(table.read_text()) if r['SkillID'] == 122204}
    assert values == {rule['maximum']} == {5}
    raw = {'$type': 'RPG.GameCore.SetDynamicValue', 'DynamicKey': {'Value': 'Lingsha_AttackTime'},
           'Value': rule['expected_value']}
    payload = _effect_payload(raw, 'SetDynamicValue', '', source=IRSource(LINGSHA_SOURCE, 'AbilityTask', 'Skill02'))
    assert payload['standard']['max_value'] == numeric_fixed(5)
    assert payload['standard']['dynamic_operation']['maximum'] is not None
