"""Typed starting conditions; assembled caps are checked by the birth plan."""
from dataclasses import replace

import pytest

from hsr.simulator_v8_clean_core.builds.models import CharacterInitialConditionInput


@pytest.mark.parametrize('mode,value,expected', [('full', None, None), ('ratio', '0.500', '0.5'),
                                               ('absolute', '123.450', '123.45')])
def test_initial_condition_round_trip_keeps_exact_input(mode, value, expected):
    condition = CharacterInitialConditionInput(mode, '30.00', hp_value=value)
    assert condition.hp_value == expected and condition.initial_energy == '30'
    assert CharacterInitialConditionInput.from_json(condition.to_json()) == condition
    assert replace(condition, initial_energy=None).initial_energy is None


@pytest.mark.parametrize('fields', [
    {'hp_mode': 'unknown'}, {'hp_value': '1'},
    {'hp_mode': 'ratio'}, {'hp_mode': 'ratio', 'hp_value': '1.01'},
    {'hp_mode': 'ratio', 'hp_value': '0'}, {'hp_mode': 'absolute', 'hp_value': '-1'},
    {'hp_mode': 'absolute', 'hp_value': 'NaN'}, {'hp_mode': 'absolute', 'hp_value': True},
    {'initial_energy': '-1'}, {'initial_energy': 'Infinity'}, {'initial_energy': True},
])
def test_invalid_initial_condition_is_rejected(fields):
    with pytest.raises((ValueError, TypeError)):
        CharacterInitialConditionInput(**{'hp_mode': 'full', 'initial_energy': '0', **fields})
