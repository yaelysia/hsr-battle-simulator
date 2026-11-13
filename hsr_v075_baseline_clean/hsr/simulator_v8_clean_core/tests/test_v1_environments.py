"""Full-stage public routes, independent numeric comparisons and wave boundaries."""
import math

import pytest

from hsr.simulator_v8_clean_core.battle_archive import write_archive
from hsr.simulator_v8_clean_core.session import command_from_json, rule_assumption_records
from hsr.simulator_v8_clean_core.tests.test_ordinary_element_break_natural_routes import open_route
from hsr.simulator_v8_clean_core.tests.test_r05_ordinary_party_routes import _records
from hsr.simulator_v8_clean_core.systems.unit_stats import effective_unit_stat


@pytest.mark.integration
def test_academic_rumors_ultimate_bonus_independent_numeric(tmp_path):
    _, _, session, commands = open_route('academic_rumors_numeric')
    hits = []
    for command in commands:
        assert session.advance().ready
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        hits.extend(r['payload'] for r in _records((result.transition,)) if r['record_type'] == 'damage')
    # Primary and adjacent damage are interleaved; use the typed packet target.
    references = (2779.799971949773, 926.5999906499244, 5559.599943899546)
    assert len(hits) == 6
    primary = [hit for hit in hits if hit['source_frame']['target_id'] == 'enemy:stage:30123061:wave:0:pos:1']
    assert len(primary) == 3
    for hit, expected in zip(primary, references):
        assert not hit['crit_resolution']['is_crit']
        assert math.isclose(hit['amount'], expected, rel_tol=.01)
    clock = session.state.units['environment:memory_turbulence']
    assert clock.resources['stage_hits'] == 1  # One ultimate, not one per hit.
    assert clock.resources['cycles_used'] == 0
    write_archive(tmp_path / 'academic_rumors_numeric.json.gz', session.archive())


@pytest.mark.integration
def test_full_stage_two_waves_and_ultimate_interrupt_cleanup(tmp_path):
    scenario, rules, session, commands = open_route('ordinary_stage_lv10')
    assert scenario['battle_setup']['metadata']['stage_scope'] == 'full_stage'
    assert 'level:global' in session.state.units
    definition = rules.wave_definition_for_stage('201010110')
    assert definition.stage_environment_status == 'executable' and definition.wave_count == 2
    waves, comparisons, interrupted = set(), set(), False
    for command in commands:
        decision, automatic = session.advance_with_transitions()
        assert decision.ready, decision.blocked_reason
        for index, transition in enumerate(automatic):
            if not any(e.event_type == 'wave.started' for e in transition.transaction.events):
                continue
            snapshot = transition.after.to_json()
            wave = snapshot['battle']['wave_index']
            waves.add(wave)
            if wave == 1:
                assert interrupted
                assert any(t.transaction.command.action_id == 'timeline:end_current_turn' for t in automatic[:index])
                assert snapshot['timeline']['turn_owner_id'] is None
                assert not snapshot['timeline']['active_turn']
                assert len([e for e in transition.transaction.events if e.event_type == 'wave.monster']) == 3
                for actor in ('march', 'natasha'):
                    expected = 10000 / effective_unit_stat(session.state.units[actor], 'speed').value
                    assert math.isclose(snapshot['timeline']['action_values'][actor], expected, abs_tol=1e-8)
        previous_owner = session.state.global_flags.get('turn_owner_id', '')
        wave = session.state.wave_index
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        if command['action_id'] == 'avatar_skill:100103' and str(previous_owner).startswith('enemy:'):
            interrupted |= any(e.event_type == 'unit.defeated' and e.target_id == previous_owner
                               for e in result.transition.transaction.events)
        if command['action_id'] == 'avatar_skill:110501':
            hit = next(r['payload'] for r in _records((result.transition,)) if r['record_type'] == 'damage')
            assert not hit['crit_resolution']['is_crit']
            assert math.isclose(hit['amount'], 956.4679286766248, rel_tol=.01)
            comparisons.add(wave)
    session.advance()
    assert session.outcome == 'victory' and waves == comparisons == {0, 1}
    assert any(r['payload']['assumption_id'] == 'wave_action_order_boundary'
               for r in rule_assumption_records(session.operations))
    write_archive(tmp_path / 'ordinary_stage_v1_complete.json.gz', session.archive())
