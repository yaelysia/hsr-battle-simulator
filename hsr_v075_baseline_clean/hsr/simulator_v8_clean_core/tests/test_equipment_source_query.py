"""Source lookup consumes real registration data; whole-transition audit is optional."""
import json
import time
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.queries.equipment import EquipmentQueryService
from hsr.simulator_v8_clean_core.session import BattleSession
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook


@pytest.mark.integration
def test_equipment_source_query_audits_only_when_requested(monkeypatch):
    core = Path(__file__).resolve().parents[1]
    data = json.loads((core / 'examples/cli/arlan_lv80_full_traces_two_waves.json').read_text())
    started = time.perf_counter()
    rules = build_battle_rulebook(Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main', data)
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
