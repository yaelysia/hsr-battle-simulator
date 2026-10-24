"""D route: natural defeat with live enemy summons.

StageConfig 307311 wave 0: the Lieutenant summons two soldiers and then defeats
the single Lv1 Seele with its own skill. Live enemy summons must not block the
natural defeat, and the terminal state must reject further decisions. No HP,
outcome or ally roster value is written by the harness.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from hsr.simulator_v8_clean_core.battle_archive import write_archive
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

_CORE = Path(__file__).resolve().parents[1]
_ROOT = Path(__file__).resolve().parents[4]
_SCENARIO = _CORE / "examples/cli/d_natural_defeat_terminal.json"
_COMMANDS = _CORE / "examples/cli/d_natural_defeat_terminal.commands.json"

_LIEUT = "enemy:stage:307311:wave:0:pos:0"


def _records(transition):
    settlement = transition.transaction.settlement
    return tuple(settlement.records) if settlement is not None else ()


def _active_summons(state):
    return [
        unit_id for unit_id, unit in state.units.items()
        if unit.flags.get("summon_kind") == "summoned_monster"
        and unit.lifecycle_status == "active"
    ]


def test_natural_defeat_with_live_enemy_summons(tmp_path):
    scenario = json.loads(_SCENARIO.read_text(encoding="utf-8"))
    commands = json.loads(_COMMANDS.read_text(encoding="utf-8"))["commands"]
    rules = build_battle_rulebook(_ROOT / "turnbasedgamedata-main", scenario)
    session = BattleSession(rules, scenario)
    auditor = RuntimeSourceAuditor(rules)
    audited = 0
    last_submit_transition = None

    for index, command in enumerate(commands):
        decision, advance_transitions = session.advance_with_transitions()
        assert decision.ready, (index, decision.blocked_reason)
        for transition in advance_transitions:
            if transition.transaction.command.action_id.startswith("timeline:"):
                audit = auditor.validate_transition(transition)
                assert audit.ok, (index, audit.violations)
                audited += 1
        result = session.submit(command_from_json(command))
        last_submit_transition = result.transition
        assert result.transition.outcome.successor_eligible, (
            index, result.transition.outcome.reason_codes,
        )

    assert _active_summons(session.state), "summons must still be alive at defeat"
    assert session.state.units["seele"].lifecycle_status != "active"

    final_decision, final_transitions = session.advance_with_transitions()
    assert final_decision.ready is False
    defeat_transition = None
    for transition in final_transitions:
        if any(
            event.event_type == "battle.defeat"
            for event in transition.transaction.events
        ):
            audit = auditor.validate_transition(transition)
            assert audit.ok, audit.violations
            audited += 1
            defeat_transition = transition
    assert defeat_transition is not None, "no native battle.defeat transition"
    assert session.outcome == "defeat"

    seele = session.state.units["seele"]
    assert seele.lifecycle_status == "defeated"
    assert seele.hp == 0
    record = seele.flags.get("defeat_record") or {}
    assert record.get("kill_credit_owner_id") == _LIEUT
    assert record.get("hp_mutation_id")
    lethal_sources = [last_submit_transition, *final_transitions]
    lethal_mutations = [
        mutation
        for transition in lethal_sources
        for mutation in transition.transaction.mutations
        if mutation.path == ("units", "seele", "hp")
        and mutation.source == "damage_system"
        and mutation.after == 0
    ]
    assert lethal_mutations, "no native lethal damage mutation"
    assert session.state.units[_LIEUT].lifecycle_status == "active"
    assert not any(
        event.event_type == "battle.victory"
        for transition in final_transitions
        for event in transition.transaction.events
    )

    assert not session.advance().ready
    rejected = session.submit(command_from_json(commands[-1]))
    assert rejected.transition.outcome.successor_eligible is False

    archive_path = Path(tmp_path) / "d_natural_defeat_terminal.archive.json"
    write_archive(archive_path, session.archive())
    env = {**os.environ, "PYTHONPATH": str(_ROOT / "hsr_v075_baseline_clean")}
    completed = subprocess.run(
        [sys.executable, "-m", "hsr.simulator_v8_clean_core.cli", "replay", str(archive_path)],
        cwd=str(_ROOT), env=env, capture_output=True, text=True, timeout=900,
    )
    assert completed.returncode == 0, (completed.stdout[-2000:], completed.stderr[-2000:])
    report = json.loads(completed.stdout)
    assert report["ok"] is True, report
    assert report["errors"] == []
    assert audited >= 1
