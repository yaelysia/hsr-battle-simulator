"""Diagnostic trimming preserves values and never changes the caller's input."""
from hsr.simulator_v8_clean_core.core.audit_policy import diagnostic_detail, diagnostic_json


def test_compact_diagnostics_preserve_numeric_rows_and_restore_full_mode():
    source = {'source_path': 'fixture.json', 'raw_type': 'fixture', 'raw_id': '1',
              'evidence': {'json_path': '$[0]', 'expanded_explanation': ['unused'] * 100}}
    numeric_row = {**source, 'level': 44, 'value': 123.5}
    data = {'source': source, 'row': numeric_row, 'source_frame': {'source_trace': source},
            'final_damage': 123.5}
    with diagnostic_detail(True):
        assert diagnostic_json(data) is data
        with diagnostic_detail(False):
            result = diagnostic_json(data)
            assert result['final_damage'] == result['row']['value'] == 123.5
            assert result['row']['level'] == 44
            assert result['source']['evidence'] == {'json_path': '$[0]'}
            assert result['source_frame'] == data['source_frame']
        assert diagnostic_json(data) is data
    assert len(source['evidence']['expanded_explanation']) == 100
