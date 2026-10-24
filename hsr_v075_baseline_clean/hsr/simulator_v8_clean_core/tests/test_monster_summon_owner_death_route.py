"""Silvermane Lieutenant natural death closes the summon lifecycle.

Source route: StageConfig 307311 wave 0, one Lv44 monster:1003010. The public
summon skill monster_skill:100301004 spawns two monster:1002040 soldiers through
the failed ByCompareMonsterID branch. Seele breaks the Lieutenant's Quantum
weakness and the native quantum break-DOT tick defeats the summoner while both
soldiers are still alive. Each soldier's MCommon_Servant OnListenCharacterDie
listener matches ByHasSummonRelation, enqueues Common_Servant_Forcekill at
MonsterForceKill priority with the alive_or_revivable masks and
CanRunOnUnselectableTarget, and each inserted ability performs a formal forced
death (no hit, damage packet or kill credit) that aborts the dying unit's unused
insert abilities. The wave clears only after both soldiers retire, then the
battle ends in victory.

Every step is an external advance/submit decision on the shipped example inputs;
no HP, AV, status, timeline, queue or outcome value is injected.
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
from hsr.simulator_v8_clean_core.systems.queue import unit_alive_state_blocked_reason
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

_CORE = Path(__file__).resolve().parents[1]
_ROOT = Path(__file__).resolve().parents[4]
_SCENARIO = _CORE / "examples/cli/silvermane_lieutenant_owner_death.json"
_COMMANDS = _CORE / "examples/cli/silvermane_lieutenant_owner_death.commands.json"

_LIEUT = "enemy:stage:307311:wave:0:pos:0"
_SUMMON_SKILL = "monster_skill:100301004"
_FORCE_KILL_ABILITY = "Common_Servant_Forcekill"


def _records(transition):
    settlement = transition.transaction.settlement
    return tuple(settlement.records) if settlement is not None else ()


def _payloads(transition, record_type):
    return tuple(
        record.get("payload") or {}
        for record in _records(transition)
        if record.get("record_type") == record_type
    )


def _summoned_monsters(state):
    return {
        unit_id: unit
        for unit_id, unit in state.units.items()
        if unit.flags.get("summon_kind") == "summoned_monster"
    }


def _rules_facts(rules):
    callback = next(
        item
        for item in rules.ir.status_callbacks
        if item.modifier_name == "MCommon_Servant"
        and item.event == "OnListenCharacterDie"
    )
    assert callback.coverage_status == "executable"
    assert callback.scope_kind == "summoner_relation_local"

    intent = next(
        item for item in rules.ir.queue_intents if "MCommon_Servant" in item.callback_id
    )
    assert intent.coverage_status == "executable", intent.blocked_reason
    assert intent.opcode == "TurnInsertAbility"
    assert intent.action_ref_or_ability_name == _FORCE_KILL_ABILITY
    assert intent.owner_alive_state == "alive_or_revivable"
    assert intent.target_alive_state == "alive_or_revivable"
    assert intent.can_run_on_unselectable_target is True
    assert intent.priority_source["priority_key"] == "MonsterForceKill"
    assert intent.priority_source["priority_ordering_admitted"] is True

    graph = next(
        item
        for item in rules.ir.standalone_ability_graphs
        if item.ability_name == _FORCE_KILL_ABILITY
    )
    assert graph.coverage_status == "executable"
    assert graph.source_mode == "mainline_common_additional"
    assert graph.source.source_path.endswith("Common_Additional_Ability.json")

    effect = next(
        item
        for item in rules.ir.effects
        if item.opcode == "ForceKill" and _FORCE_KILL_ABILITY in item.effect_id
    )
    assert effect.coverage_status == "executable"
    standard = effect.payload["standard"]
    assert standard["operation"] == "formal_forced_death"
    assert standard["target_alias"] == "AbilityTargetEntity"
    assert standard["abort_unused_insert_ability"] is True
    assert standard["mute_hp_change"] is False
    assert standard["mute_all_trigger_death"] is False
    return callback, intent, graph, effect


def _find_death_advance(transitions):
    for position, transition in enumerate(transitions):
        if any(
            mutation.path == ("units", _LIEUT, "lifecycle_status")
            and mutation.after == "defeated"
            for mutation in transition.transaction.mutations
        ):
            return position, transition
    return -1, None


def test_silvermane_lieutenant_owner_death_route(tmp_path):
    scenario = json.loads(_SCENARIO.read_text(encoding="utf-8"))
    commands = json.loads(_COMMANDS.read_text(encoding="utf-8"))["commands"]
    rules = build_battle_rulebook(_ROOT / "turnbasedgamedata-main", scenario)
    session = BattleSession(rules, scenario)
    auditor = RuntimeSourceAuditor(rules)
    _rules_facts(rules)

    summon_transition = None
    children: dict[str, object] = {}
    death_advance = None
    victory_advance = None
    audited_transitions = 0

    for index, command in enumerate(commands):
        decision, advance_transitions = session.advance_with_transitions()
        assert decision.ready, (index, decision.blocked_reason)
        for transition in advance_transitions:
            audit = auditor.validate_transition(transition)
            assert audit.ok, (
                index,
                transition.transaction.command.action_id,
                audit.violations,
            )
            audited_transitions += 1
        death_position, death_transition_now = _find_death_advance(advance_transitions)
        if death_transition_now is not None:
            assert death_advance is None, "summoner defeated twice"
            death_advance = (index, death_position, advance_transitions)
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, (
            index,
            command["action_id"],
            result.transition.outcome.reason_codes,
        )
        if command["action_id"] == _SUMMON_SKILL:
            summon_transition = result.transition
            children = _summoned_monsters(session.state)
            assert len(children) == 2
            for unit in children.values():
                assert unit.lifecycle_status == "active"
                assert unit.flags["summoner_id"] == _LIEUT
                assert "modifier:MCommon_Servant" in unit.statuses
        if session.outcome:
            break

    # The defeating quantum break-DOT tick runs at the summoner's turn start, so
    # the terminal advance is the follow-up scheduler step after the last
    # submitted action.
    decision, advance_transitions = session.advance_with_transitions()
    for transition in advance_transitions:
        audit = auditor.validate_transition(transition)
        assert audit.ok, (
            transition.transaction.command.action_id,
            audit.violations,
        )
        audited_transitions += 1
    death_position, death_transition_now = _find_death_advance(advance_transitions)
    if death_transition_now is not None:
        assert death_advance is None, "summoner defeated twice"
        death_advance = (len(commands), death_position, advance_transitions)

    assert summon_transition is not None and len(children) == 2
    assert death_advance is not None, "summoner never died"
    assert session.outcome == "victory"
    death_index, death_position, transitions = death_advance
    death_transition = transitions[death_position]
    advance_actions = [
        transition.transaction.command.action_id for transition in transitions
    ]

    # 1) The summoner died from the real lethal damage path while both soldiers
    #    were still on the field.
    lethal = [
        event
        for event in death_transition.transaction.events
        if event.event_type == "unit.defeated" and event.target_id == _LIEUT
    ]
    assert len(lethal) == 1, lethal
    assert lethal[0].payload.get("record_type") == "break_dot_tick"
    assert lethal[0].payload.get("kill_credit_owner_id")
    lethal_hp = [
        mutation
        for mutation in death_transition.transaction.mutations
        if mutation.path == ("units", _LIEUT, "hp")
        and mutation.source == "damage_system"
        and mutation.after == 0
    ]
    assert len(lethal_hp) == 1
    before_units = death_transition.transaction.before.data["units"]
    for unit_id in children:
        assert before_units[unit_id]["lifecycle_status"] == "active"
        assert before_units[unit_id]["hp"] > 0

    # 2) Both live soldiers enqueued their own forced-retirement ability through
    #    the summon-relation death listener; no unrelated entry was created.
    enqueues = [
        payload
        for payload in _payloads(death_transition, "queue_enqueue")
        if (payload.get("entry") or {}).get("action_or_ability_ref")
        == _FORCE_KILL_ABILITY
    ]
    assert len(enqueues) == 2, enqueues
    enqueued_actors = set()
    for payload in enqueues:
        entry = payload["entry"]
        assert entry["queue_kind"] == "turn_insert_ability"
        assert entry["priority_key"] == "MonsterForceKill"
        assert entry["owner_alive_state"] == "alive_or_revivable"
        assert entry["target_alive_state"] == "alive_or_revivable"
        assert entry["can_run_on_unselectable_target"] is True
        assert entry["actor_id"] in children
        assert entry["target_ids"] == [entry["actor_id"]]
        enqueued_actors.add(entry["actor_id"])
    assert enqueued_actors == set(children)

    # 3) The same advance drains both entries after the defeat and before the
    #    wave transition; each drain performs one formal forced death.
    defeat_position = next(
        position
        for position, transition in enumerate(transitions)
        if any(
            event.event_type == "unit.defeated" and event.target_id == _LIEUT
            for event in transition.transaction.events
        )
    )
    drain_positions = [
        position for position, action in enumerate(advance_actions)
        if action == "queue:drain_admitted"
    ]
    assert len(drain_positions) == 2, advance_actions
    wave_positions = [
        position for position, action in enumerate(advance_actions)
        if action == "wave:transition"
    ]
    assert len(wave_positions) == 1
    wave_position = wave_positions[0]
    assert defeat_position < min(drain_positions)
    assert max(drain_positions) < wave_position

    forced_events = [
        event
        for transition in transitions
        for event in transition.transaction.events
        if event.event_type == "unit.defeated" and event.target_id in children
    ]
    assert len(forced_events) == 2
    forced_ids = {event.target_id for event in forced_events}
    assert forced_ids == set(children)
    for event in forced_events:
        assert event.payload.get("record_type") == "formal_forced_death"
        assert event.payload.get("kill_credit_owner_id") == ""
        assert event.payload.get("damage_event_id") == ""

    for unit_id in children:
        unit = session.state.units[unit_id]
        assert unit.lifecycle_status == "defeated"
        assert unit.hp == 0
        record = unit.flags.get("defeat_record") or {}
        assert record.get("forced_death_kind") == "formal_ability_force_kill"
        assert record.get("effect_id")
        assert not record.get("kill_credit_owner_id")
        assert not record.get("damage_event_id")

    # 4) Forced death never produces hit/damage packets or kill energy, and the
    #    abort-unused-insert cleanup did not remove another unit's entry.
    forced_transitions = [
        transition for position, transition in enumerate(transitions)
        if position in drain_positions
    ]
    for transition in forced_transitions:
        assert not [
            mutation for mutation in transition.transaction.mutations
            if mutation.source.startswith("damage_system")
        ]
        assert not [
            event for event in transition.transaction.events
            if event.event_type.startswith("damage.")
        ]
        terminal_removals = [
            mutation.metadata
            for mutation in transition.transaction.mutations
            if mutation.metadata.get("queue_operation") == "terminal_remove"
        ]
        for metadata in terminal_removals:
            assert (
                metadata.get("queue_cleanup_operation")
                == "abort_unused_insert_ability"
            )
            assert metadata["queue_entry"] is not None

    # 5) The wave transition is last and ends the battle; living soldiers must
    #    have blocked it until both forced retirements finished.
    assert advance_actions[wave_position] == "wave:transition"
    assert wave_position == len(advance_actions) - 1
    victory_events = [
        event for event in transitions[wave_position].transaction.events
        if event.event_type == "battle.victory"
    ]
    assert victory_events
    assert session.outcome == "victory"
    # No earlier transition of the death advance reported victory or cleared the
    # wave while a soldier was still alive.
    for position, transition in enumerate(transitions):
        if position == wave_position:
            continue
        assert not [
            event for event in transition.transaction.events
            if event.event_type in {"battle.victory", "wave.cleared"}
        ], position

    # 6) Terminal state rejects further decisions and mutations.
    assert not session.advance().ready
    rejected = session.submit(command_from_json(commands[-1]))
    assert rejected.transition.outcome.successor_eligible is False

    # 7) The alive-or-revivable mask keeps the unsupported revivable branch
    #    explicit instead of reusing limbo semantics.
    assert unit_alive_state_blocked_reason(
        session.state, sorted(children)[0], "alive_or_revivable", role="target"
    ).startswith("queue_target_revivable_branch_not_admitted:")
    assert unit_alive_state_blocked_reason(
        session.state, _LIEUT, "alive_or_revivable", role="owner"
    ).startswith("queue_owner_revivable_branch_not_admitted:")

    # 8) Save the formal session archive and replay it in an independent process.
    assert audited_transitions >= 4
    archive_path = Path(tmp_path) / "silvermane_lieutenant_owner_death.archive.json"
    write_archive(archive_path, session.archive())
    env = {**os.environ, "PYTHONPATH": str(_ROOT / "hsr_v075_baseline_clean")}
    completed = subprocess.run(
        [sys.executable, "-m", "hsr.simulator_v8_clean_core.cli", "replay", str(archive_path)],
        cwd=str(_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert completed.returncode == 0, (completed.stdout[-2000:], completed.stderr[-2000:])
    report = json.loads(completed.stdout)
    assert report["ok"] is True, report
    assert report["errors"] == []
    assert report["step_count"] == len(session.operations)
