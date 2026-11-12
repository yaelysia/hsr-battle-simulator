"""Source lookup consumes real registration data; whole-transition audit is optional."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.queries.equipment import EquipmentQueryService
from hsr.simulator_v8_clean_core.battle_archive import write_archive
from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook


@pytest.mark.integration
def test_equipment_source_query_audits_only_when_requested(monkeypatch, tmp_path):
    core = Path(__file__).resolve().parents[1]
    data = json.loads((core / 'examples/cli/arlan_lv80_full_traces_two_waves.json').read_text())
    started = time.perf_counter()
    rules = build_battle_rulebook(Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main', data)
    assert {d.definition_key.definition_identity for d in rules.ir.light_cone_definitions} == {'23002'}
    assert {d.definition_key.definition_identity for d in rules.ir.relic_set_definitions} == {'102', '302'}
    loaded = time.perf_counter()
    session = BattleSession(rules, data)
    print({'rulebook_seconds': loaded - started, 'first_session_seconds': time.perf_counter() - loaded})
    registration = session.build.ability_provider_registration
    assert registration is not None and registration.ok
    transition = registration.to_transition()
    mutation = registration.mutations[0]
    provider_id = mutation.metadata['providers'][0]['provider_id']
    calls = []
    original = RuntimeSourceAuditor.validate_transition
    def counted(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(RuntimeSourceAuditor, 'validate_transition', counted)
    service = EquipmentQueryService(rules)
    args = (session.build.character_build_results[0], transition, mutation.stable_id())
    plain = service.get_dynamic_mutation_source(*args, provider_id=provider_id)
    assert plain.resolution_status == 'resolved', plain.blocked_reason
    assert plain.audit_trace['audit_status'] == 'not_run' and not calls
    audited = service.get_dynamic_mutation_source(*args, provider_id=provider_id, audit=True)
    assert audited.resolution_status == 'resolved', audited.blocked_reason
    assert len(calls) == 1 and plain.ability_provider == audited.ability_provider
    commands = json.loads((core / 'examples/cli/arlan_lv80_full_traces_two_waves.commands.json').read_text())['commands']
    for raw in commands:
        decision = session.advance()
        assert decision.ready, decision.blocked_reason
        choice = next(c for c in decision.availability.choices
                      if c.actor_id == raw['actor_id'] and c.action_id == raw['action_id'])
        command = command_from_json({**choice.command_template, 'target_ids': raw['target_ids']})
        result = session.submit(command)
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
    archive = write_archive(tmp_path / 'selected-equipment.json.gz', session.archive())
    replay = subprocess.run([
        sys.executable, '-B', '-m', 'hsr.simulator_v8_clean_core.cli',
        '--data-root', str(Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'),
        'replay', str(archive),
    ], capture_output=True, text=True, env={**os.environ, 'PYTHONPATH': str(core.parents[1])})
    assert replay.returncode == 0, replay.stdout + replay.stderr
