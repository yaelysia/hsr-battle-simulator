"""Public build inputs: short identities normalize to the existing typed model."""
import copy
import json
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.builds.models import CharacterBuildInput
from hsr.simulator_v8_clean_core.equipment.models import EquipmentBuildInput


def test_short_equipment_input_has_the_same_canonical_build_and_fingerprint():
    path = Path(__file__).resolve().parents[1] / 'examples/cli/arlan_lv80_full_traces_two_waves.json'
    encoded = json.loads(path.read_text())['units'][0]['character_build']

    def shorten(value):
        if isinstance(value, list):
            return [shorten(item) for item in value]
        if isinstance(value, dict):
            if 'definition_kind' in value and 'definition_identity' in value:
                return value['definition_identity']
            return {key: shorten(item) for key, item in value.items() if not key.endswith('_fingerprint')}
        return value

    full = CharacterBuildInput.from_json(encoded)
    short = CharacterBuildInput.from_json(shorten(encoded))
    assert short == full
    assert short.to_json() == full.to_json()
    assert short.equipment_build.build_fingerprint == full.equipment_build.build_fingerprint


def test_supplied_fingerprint_and_definition_kind_are_still_checked():
    path = Path(__file__).resolve().parents[1] / 'examples/cli/arlan_lv80_full_traces_two_waves.json'
    encoded = json.loads(path.read_text())['units'][0]['character_build']['equipment_build']
    wrong = copy.deepcopy(encoded)
    wrong['build_fingerprint'] = '0' * 64
    with pytest.raises(ValueError, match='fingerprint'):
        EquipmentBuildInput.from_json(wrong)
    wrong = copy.deepcopy(encoded)
    wrong['relics'][0]['template_key'] = 'light_cone::23002'
    with pytest.raises(TypeError, match='kind'):
        EquipmentBuildInput.from_json(wrong)
    empty = EquipmentBuildInput.from_json({'build_id': 'empty', 'character_card_id': encoded['character_card_id']})
    assert not empty.relics and empty.light_cone is None
