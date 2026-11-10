"""Function symbols are compiler inputs, never default-valued dynamic slots."""
import json
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.dynamic_key_hash import tbgd_dynamic_key_hash
from hsr.simulator_v8_clean_core.rules.evaluator import NumericEvaluationContext, RuleEvaluator
from hsr.simulator_v8_clean_core.rules.expression_ir import is_typed_numeric_expression, numeric_dynamic_hashes
from hsr.simulator_v8_clean_core.tbgd.expression_lowering import lower_numeric_expression


def _call(name, values, *, dynamic=False):
    hashes = [tbgd_dynamic_key_hash(name)]
    fixed = []
    code = [1, 0]
    for index, value in enumerate(values):
        if dynamic:
            hashes.append(100 + index)
            code.extend((1, index + 1))
        else:
            fixed.append({'Value': value})
            code.extend((0, index))
    code.extend((16, len(values), 17))
    return {'IsDynamic': True, 'PostfixExpr': {
        'OpCodes': code, 'DynamicHashes': hashes, 'FixedValues': fixed,
    }}


@pytest.mark.parametrize('name,values,expected', [
    ('max', [1.2, -0.3], 1.2), ('min', [1.2, -0.3], -0.3),
    ('max', [-4, -3, -2], -2), ('min', [3], 3),
    ('floor', [1.9], 1), ('floor', [-1.9], -2),
    ('ceil', [1.2], 2), ('ceil', [-1.9], -1),
    ('int', [1.9], 1), ('int', [-1.9], -1), ('abs', [-3.5], 3.5),
])
def test_constant_and_dynamic_calls_have_identical_finite_semantics(name, values, expected):
    constant = lower_numeric_expression(_call(name, values))
    assert constant['kind'] == 'fixed' and constant['value'] == expected
    dynamic = lower_numeric_expression(_call(name, values, dynamic=True))
    assert is_typed_numeric_expression(dynamic)
    assert tbgd_dynamic_key_hash(name) not in numeric_dynamic_hashes(dynamic)
    result = RuleEvaluator().evaluate_numeric(dynamic, NumericEvaluationContext(
        dynamic_values={str(100 + index): value for index, value in enumerate(values)}))
    assert result.ok and result.value == expected, result.to_json()


def test_nested_call_consumes_its_own_function_symbol_not_a_numeric_zero():
    # max(floor(3.9), abs(-4.2))
    raw = {'IsDynamic': True, 'PostfixExpr': {
        'OpCodes': [1, 0, 1, 1, 0, 0, 16, 1, 1, 2, 0, 1, 16, 1, 16, 2, 17],
        'DynamicHashes': [tbgd_dynamic_key_hash(name) for name in ('max', 'floor', 'abs')],
        'FixedValues': [{'Value': 3.9}, {'Value': -4.2}],
    }}
    lowered = lower_numeric_expression(raw)
    assert lowered['kind'] == 'fixed' and lowered['value'] == 4.2


@pytest.mark.parametrize('name,values', [('not_a_function', [1]), ('floor', [1, 2]), ('max', [])])
def test_unknown_function_or_wrong_arity_is_not_guessed(name, values):
    lowered = lower_numeric_expression(_call(name, values))
    assert lowered['kind'] == 'unsupported' and not lowered['supported']


def test_cyrene_charge_energy_uses_real_max_call_and_only_real_numeric_bindings():
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    config = json.loads((root / 'Config/ConfigAbility/Avatar/Avatar_Cyrene_00_Ability.json').read_text())
    ability = next(item for item in config['GlobalTemplates'] if item['Name'] == 'Cyrene_00_ChargeEnergy')
    task = next(item for item in ability['TaskList']
                if item.get('DynamicKey') == {'Value': '_ExtraSpecialSP'})
    lowered = lower_numeric_expression(task['Value'])
    assert numeric_dynamic_hashes(lowered) == (1064615285, 1662106773, -2048376531)
    assert lowered['instructions'][-2] == {'opcode': 'max', 'operand_count': 2}
    for current, added, maximum, expected in ((10, 5, 12, 3), (2, 3, 12, 0)):
        result = RuleEvaluator().evaluate_numeric(lowered, NumericEvaluationContext(dynamic_values={
            '1064615285': current, '1662106773': added, '-2048376531': maximum}))
        assert result.ok and result.value == expected, result.to_json()
