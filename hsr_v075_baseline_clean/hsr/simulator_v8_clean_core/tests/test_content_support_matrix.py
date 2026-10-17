"""Support reporting preserves scope and consumes real admission results."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.queries.content_support import content_support_matrix, summarize_content_support
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.scenarios.loader import ScenarioLoader
from hsr.simulator_v8_clean_core.scenarios.schema import ScenarioSpec


def test_source_pass_does_not_claim_formal_or_execution_support():
    catalog = {'source_fingerprints': {'fixture': 'source'}, 'rows': [{
        'kind': 'character', 'content_id': 'card', 'owner_ids': ['avatar:fixture'],
        'source_checks': [{'kind': 'source_identity', 'ref_id': 'card', 'status': 'supported', 'reasons': []}],
        'formal_checks': [],
    }]}
    before = deepcopy(catalog)
    matrix = content_support_matrix(catalog)
    row = matrix['rows'][0]
    assert row['source_status'] == 'supported' and row['formal_status'] == 'unchecked'
    assert row['execution_evidence']['status'] == 'not_executed'
    assert catalog == before
    unknown = {'kind': 'runtime_context', 'status': 'unchecked', 'reasons': ['context_not_checked']}
    summary = summarize_content_support('fixture', [*row['source_checks'], unknown])
    assert summary['status'] == 'unchecked' and not summary['blocked_reasons']
    with pytest.raises(ValueError, match='formal RuleBook'):
        content_support_matrix(catalog, scenario=object())
    gap = {'kind': 'source_ability_linkage_gap', 'ref_id': 'gap', 'status': 'blocked',
           'reasons': ['structured_ability_candidates_exhausted'], 'source': {'json_path': '$.AbilityList[2]'}}
    catalog['rows'][0]['source_checks'].append(gap)
    catalog['rows'].append({'kind': 'character_action', 'content_id': 'action', 'owner_ids': ['avatar:fixture'],
        'source_checks': [{'kind': 'source_action_ability_linkage', 'ref_id': 'action', 'status': 'blocked',
                           'reasons': ['action_relationship_gap_blocked'], 'gap_ids': ['gap']}], 'formal_checks': []})
    action = next(row for row in content_support_matrix(catalog)['rows'] if row['kind'] == 'character_action')
    assert 'structured_ability_candidates_exhausted' in action['known_source_gaps']
    assert action['source_checks'][-1]['source']['json_path'] == '$.AbilityList[2]'


def test_stage_environment_scope_uses_compiled_admission_without_claiming_execution():
    from dataclasses import replace
    from hsr.simulator_v8_clean_core.rules.ir import IRSource, WaveDefinitionIR

    wave = WaveDefinitionIR('wave:fixture', 'fixture', 1, (), (), IRSource('fixture', 'Stage', 'fixture'))
    catalog = {'rows': [{'kind': 'stage', 'content_id': wave.wave_definition_id,
                        'source_checks': [], 'formal_checks': []}]}
    for definition, expected in (
        (wave, 'unchecked'),
        (replace(wave, stage_environment_status='executable', stage_environment_blocked_reason=''), 'supported'),
        (replace(wave, stage_environment_blocked_reason='stage_scoring_missing'), 'blocked'),
    ):
        row = content_support_matrix(catalog, rules=RuleBook(CanonicalIR(
            'fixture', wave_definitions=(definition,))))['rows'][0]
        check = next(item for item in row['formal_checks'] if item['kind'] == 'full_stage_environment')
        assert check['status'] == expected
        assert row['execution_evidence']['status'] == 'not_executed'
        assert row['formal_status'] == ('blocked' if expected == 'blocked' else 'unchecked')


def test_selected_configuration_merges_real_build_rejection_without_compiling(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail('matrix aggregation must not compile or start a battle')
    monkeypatch.setattr('hsr.simulator_v8_clean_core.tbgd.lowering.TBGDLowering.build', forbidden)
    path = Path(__file__).resolve().parents[1] / 'examples/cli/arlan_vs_antimatter.json'
    scenario = ScenarioLoader().load_dict(json.loads(path.read_text()))
    # This deliberately empty formal scope cannot admit the selected card. The
    # real assembler, rather than directory membership, must explain rejection.
    matrix = content_support_matrix({'rows': []}, rules=RuleBook(CanonicalIR('fixture')), scenario=scenario)
    row = next(row for row in matrix['rows'] if row['kind'] == 'character_build')
    build = next(unit.character_build for unit in scenario.units if unit.character_build is not None)
    assert row['build']['input_fingerprint'] == build.input_fingerprint
    assert row['formal_status'] == 'blocked' and row['formal_blocked_reasons']
    assert any('character' in reason and 'missing' in reason for reason in row['formal_blocked_reasons'])
    assert row['execution_evidence']['status'] == 'not_executed' and not row['actions']
    json.dumps(matrix, allow_nan=False)


def test_admitted_build_uses_formal_selection_flags_without_claiming_its_actions_work():
    from hsr.simulator_v8_clean_core.tests.test_p9_a2_formal_build_param_projection import _fixture

    rules, unit, assembly = _fixture()
    scenario = ScenarioSpec('fixture', 'fixture', (unit,), ())
    before = repr(scenario)
    catalog = {'rows': [{'kind': 'character', 'content_id': unit.character_build.character_card_id,
                         'owner_ids': [unit.entity_ref], 'source_checks': []}]}
    report = content_support_matrix(catalog, rules=rules, scenario=scenario)
    character = next(row for row in report['rows'] if row['kind'] == 'character')
    assert character['formal_status'] == 'unchecked'
    assert character['formal_checks'][0]['status'] == 'supported'
    build = next(row for row in report['rows'] if row['kind'] == 'character_build')
    assert build['formal_checks'][0]['result_fingerprint'] == assembly.result_fingerprint
    assert build['formal_status'] == 'supported' and build['actions']
    assert all(action['scope'] == 'build_selected_action_static' for action in build['actions'])
    # The fixture admits its build but intentionally supplies no target/action
    # graphs. Build success must not turn those missing definitions into support.
    assert all(action['status'] == 'blocked' for action in build['actions'])
    assert build['execution_evidence']['status'] == 'not_executed' and repr(scenario) == before
    json.dumps(report, allow_nan=False)
