"""C route: real enemy actions across the two-wave source.

Reuses StageConfig 201010110 with the shipped melee-turn battle inputs. The
first wave is cleared by real actions, the second wave is born and initialized
once, an enemy actually executes its source skill, and public submissions
continue to victory. Every wave/terminal transition is checked with the native
source auditor and the session archive is replayed in an independent process.
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
_SCENARIO = _CORE / "examples/cli/c_multiwave_real_action.json"
_COMMANDS = _CORE / "examples/cli/c_multiwave_real_action.commands.json"


def _records(transition):
    settlement = transition.transaction.settlement
    return tuple(settlement.records) if settlement is not None else ()


def test_multiwave_real_enemy_action_route(tmp_path):
    scenario = json.loads(_SCENARIO.read_text(encoding="utf-8"))
    commands = json.loads(_COMMANDS.read_text(encoding="utf-8"))["commands"]
    rules = build_battle_rulebook(_ROOT / "turnbasedgamedata-main", scenario)
    session = BattleSession(rules, scenario)
    auditor = RuntimeSourceAuditor(rules)

    enemy_skill_steps = []
    wave_starts = []
    wave_clears = []
    victory_steps = []
    startup_units = []
    submitted = 0
    audited = 0

    def audit(transition, label):
        nonlocal audited
        result = auditor.validate_transition(transition)
        assert result.ok, (label, result.violations)
        audited += 1

    while submitted < len(commands):
        decision, advance_transitions = session.advance_with_transitions()
        assert decision.ready, (submitted, decision.blocked_reason)
        for transition in advance_transitions:
            action = transition.transaction.command.action_id
            for event in transition.transaction.events:
                if event.event_type == "wave.started":
                    wave_starts.append(event.payload["wave_index"])
                elif event.event_type == "wave.cleared":
                    wave_clears.append(event.payload["wave_index"])
                elif event.event_type == "battle.victory":
                    victory_steps.append(submitted)
            for record in _records(transition):
                if record.get("record_type") == "monster_startup":
                    unit_id = (record.get("payload") or {}).get("unit_id")
                    if isinstance(unit_id, str):
                        startup_units.append(unit_id)
            if action in {"wave:transition", "wave.started", "wave.cleared"}:
                audit(transition, f"advance:{action}")
            elif action.startswith("scheduler:"):
                audit(transition, f"advance:{action}")

        surface_before = session.state
        command = commands[submitted]
        result = session.submit(command_from_json(command))
        submitted += 1
        transition = result.transition
        assert transition.outcome.successor_eligible, (
            submitted, transition.outcome.reason_codes,
        )
        assert command["actor_id"] == transition.transaction.command.actor_id
        for mutation in transition.transaction.mutations:
            if mutation.path[:1] == ("units",):
                continue
        if (
            command["actor_id"].startswith("enemy:")
            and command["action_id"].startswith("monster_skill:")
        ):
            enemy_skill_steps.append((submitted, command["action_id"]))
            audit(transition, f"enemy:{command['action_id']}")
            assert session.state.units[command["target_ids"][0]].hp < surface_before.units[
                command["target_ids"][0]
            ].hp
        if session.outcome:
            break

    final_decision, final_transitions = session.advance_with_transitions()
    assert final_decision.ready is False
    for transition in final_transitions:
        action = transition.transaction.command.action_id
        for event in transition.transaction.events:
            if event.event_type == "wave.cleared":
                wave_clears.append(event.payload["wave_index"])
            elif event.event_type == "battle.victory":
                victory_steps.append(submitted)
        if action == "wave:transition" or action.startswith("scheduler:"):
            audit(transition, f"final:{action}")

    assert session.outcome == "victory"
    assert enemy_skill_steps, "no real enemy skill executed"
    assert session.state.wave_index == 1
    assert wave_starts == [0, 1], wave_starts
    assert wave_clears == [0, 1], wave_clears
    # The second wave starts only after the first one is cleared.
    assert wave_clears[0] < wave_starts[1]
    # Every new-wave monster starts its passive exactly once.
    duplicate_starts = {
        unit_id for unit_id in startup_units if startup_units.count(unit_id) > 1
    }
    assert not duplicate_starts, startup_units
    # Victory is only reported after the second wave starts and is cleared.
    assert victory_steps and victory_steps[-1] >= 1
    assert audited >= 3

    assert not session.advance().ready
    assert session.submit(command_from_json(commands[-1])).transition.outcome.successor_eligible is False

    archive_path = Path(tmp_path) / "c_multiwave_real_action.archive.json"
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
