"""A trace consumed only by its servant remains an admitted owner parameter."""
from pathlib import Path

from hsr.simulator_v8_clean_core.tbgd.character_cards import (
    _character_config_dynamic_value_bindings_by_avatar_version,
    _trace_dynamic_value_bindings_for_row,
)


def test_aglaea_retains_speed_stack_parameter_from_owned_servant_config():
    root = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'
    bindings = _character_config_dynamic_value_bindings_by_avatar_version(
        root, max_records_per_table=None, avatar_ids=frozenset({'1402', '1008'}))
    trace = _trace_dynamic_value_bindings_for_row({'PointTriggerKey': 'PointB2'}, bindings[('1402', '')])
    entry = trace['by_hash']['-867693099']
    assert entry['param_index'] == 0
    assert entry['source_path'] == 'Config/ConfigCharacter/Servant/Servant_AglaeaServant_00_Config.json'
    assert '-867693099' not in bindings[('1008', '')]['by_hash']
