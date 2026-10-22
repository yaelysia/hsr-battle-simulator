"""Silvermane Lieutenant source summon: natural summon, child actions, defeat and re-summon.

Source route: StageConfig 307311 wave 0, one Lv44 monster:1003010 (Silvermane
Lieutenant). The public summon skill monster_skill:100301004 runs
Monster_W1_Soldier03_00_Skill08_Phase02, whose ByCompareMonsterID predicate is false
for this card. The failed branch's SummonMonster entries read
MonsterIDFromCustomValue.Hash against the card's own CustomValues row, summon two
monster:1002040 soldiers at First/Last, start their source passives, let them act,
defeat one, and summon again while the lieutenant is alive.

Every step below is an external advance/submit decision on the shipped example inputs;
no HP, AV, status, timeline or queue value is injected.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace

import pytest

pytestmark = pytest.mark.integration

from hsr.simulator_v8_clean_core.battle_archive import write_archive
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.rules.ir import IRSource
from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.systems.ability import (
    _summon_monster_intent_caster_card_blocked_reason,
)
from hsr.simulator_v8_clean_core.systems.unit_relation import (
    EntityRelationResolver,
    TargetEvaluationContext,
)
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

from pathlib import Path

_CORE = Path(__file__).resolve().parents[1]
_ROOT = Path(__file__).resolve().parents[4]
_SCENARIO = _CORE / "examples/cli/silvermane_lieutenant_summon_natural.json"
_COMMANDS = _CORE / "examples/cli/silvermane_lieutenant_summon_natural.commands.json"

_LIEUT = "enemy:stage:307311:wave:0:pos:0"
_SUMMON_SKILL = "monster_skill:100301004"
_CHILD_SKILL = "monster_skill:100204001"
_CHILD_TEMPLATE = "monster:1002040"
_STARTUP_STATUSES = {
    "modifier:Local_ListenRedStance",
    "modifier:Local_ListenStanceBreak",
    "modifier:MonsterAllDamageReduce",
    "modifier:TriggerStanceCountDown_Monster",
}


def _records(transition):
    settlement = transition.transaction.settlement
    return tuple(settlement.records) if settlement is not None else ()


def _condition_results(transition):
    found = []
    for record in _records(transition):
        if record.get("record_type") != "ability_task":
            continue
        condition = (record.get("payload") or {}).get("condition_result") or {}
        if condition.get("opcode"):
            found.append(condition)
    return found


def _summoned_monsters(state):
    return {
        unit_id: unit
        for unit_id, unit in state.units.items()
        if unit.flags.get("summon_kind") == "summoned_monster"
    }


def _decision_actors(decision):
    if decision.token is not None and decision.token.actor_id:
        yield decision.token.actor_id
    for choice in decision.availability.choices:
        if choice.actor_id:
            yield choice.actor_id


def _base_action_gauge(rules):
    return next(
        rule.base_action_gauge
        for rule in rules.ir.timeline_rules
        if rule.coverage_status == "executable"
    )


def _assert_unique_present_positions(state):
    seen = {}
    for unit_id, unit in state.units.items():
        if unit.side != "enemy" or unit.lifecycle_status == "removed":
            continue
        position = unit.flags.get("position")
        if not isinstance(position, int) or isinstance(position, bool):
            continue
        assert position not in seen, (position, unit_id, seen[position])
        seen[position] = unit_id
    return seen


def _adjacent_targets(state, unit_id):
    return EntityRelationResolver().resolve(
        state,
        "formation.adjacent",
        TargetEvaluationContext(caster_id=unit_id, effect_owner_id=unit_id),
        subject_ids=(unit_id,),
        options={"side": "Both"},
    )


def _owned_dynamic_values(state, unit_id):
    store = (state.global_flags.get("dynamic_value_store") or {}).get("entries") or {}
    return {
        entry.get("name"): entry.get("value")
        for entry in store.values()
        if isinstance(entry, dict) and entry.get("target_id") == unit_id
    }


def test_silvermane_lieutenant_natural_summon_route(tmp_path):
    scenario = json.loads(_SCENARIO.read_text(encoding="utf-8"))
    commands = json.loads(_COMMANDS.read_text(encoding="utf-8"))["commands"]
    rules = build_battle_rulebook(_ROOT / "turnbasedgamedata-main", scenario)
    session = BattleSession(rules, scenario)
    auditor = RuntimeSourceAuditor(rules)
    gauge = _base_action_gauge(rules)

    # The caster card scope is a formal intent field; source evidence stays
    # audit-only and trimming it must not change admission.
    summon_intent = next(
        intent
        for intent in rules.ir.summon_monster_intents
        if intent.coverage_status == "executable"
        and "monster_skill:100301004" in intent.source_task_id
    )
    assert summon_intent.caster_card_scope["monster_id"] == 1003010
    assert summon_intent.caster_card_scope["custom_value_binding_scope"][
        "character_config_path"
    ].endswith("Monster_W1_Soldier03_00_Config.json")
    assert "caster_card_scope" not in summon_intent.source.evidence
    lieutenant_actor = session.state.units[_LIEUT]
    stripped_intent = replace(
        summon_intent,
        source=IRSource(
            source_path=summon_intent.source.source_path,
            raw_type=summon_intent.source.raw_type,
            raw_id=summon_intent.source.raw_id,
            evidence={},
        ),
    )
    assert (
        _summon_monster_intent_caster_card_blocked_reason(
            rules, summon_intent, lieutenant_actor
        )
        == ""
    )
    assert (
        _summon_monster_intent_caster_card_blocked_reason(
            rules, stripped_intent, lieutenant_actor
        )
        == ""
    )
    foreign_caster = replace(
        stripped_intent,
        caster_card_scope={**summon_intent.caster_card_scope, "monster_id": 1003011},
    )
    assert (
        _summon_monster_intent_caster_card_blocked_reason(
            rules, foreign_caster, lieutenant_actor
        )
        == "summon_monster_intent_caster_card_mismatch"
    )

    # Entry: the lieutenant's passive initialization is admitted and its source
    # initializers ran (SummonCounter omitted ResetValue, AICounter explicit).
    lieutenant = session.state.units[_LIEUT]
    assert lieutenant.flags["enabled_passive_mechanism_slot_ids"]
    assert _owned_dynamic_values(session.state, _LIEUT) == {
        "W1_Soldier03_00_BattleScore2_Flag": 0.0,
        "W1_Soldier03_00_SummonCounter": 0.0,
        "W1_Soldier03_00_AICounter": 1.0,
    }

    decision = session.advance()
    assert decision.ready, decision.blocked_reason
    assert decision.token.actor_id == _LIEUT
    choices = {choice.action_id: choice for choice in decision.availability.choices}
    assert _SUMMON_SKILL in choices
    assert choices[_SUMMON_SKILL].target_query.to_json()["selection_mode"] == "automatic"

    first_children = {}
    first_child_birth_statuses = ()
    first_child_actions = []
    second_children = {}
    second_child_actions = []
    defeated_id = ""
    defeat_step = -1
    summon_steps = []
    summon_unit_ids = []
    decision_actors_by_step = []
    spawn_mutations = {}
    audited_transitions = 0

    for index, command in enumerate(commands):
        decision = session.advance()
        assert decision.ready, (index, decision.blocked_reason)
        decision_actors_by_step.append(set(_decision_actors(decision)))
        actors = decision_actors_by_step[-1]
        action_id = command["action_id"]
        actor_id = command["actor_id"]
        if actor_id.startswith("enemy:summon:"):
            assert actor_id in actors, (index, actor_id, sorted(actors))
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, (
            index,
            action_id,
            result.transition.outcome.reason_codes,
        )
        transition = result.transition
        if action_id == _SUMMON_SKILL or actor_id.startswith("enemy:summon:"):
            audit = auditor.validate_transition(transition)
            assert audit.ok, (index, action_id, audit.violations)
            audited_transitions += 1
        for mutation in transition.transaction.mutations:
            if mutation.op == "spawn":
                unit_id = str(mutation.path[1])
                spawn_mutations[unit_id] = spawn_mutations.get(unit_id, 0) + 1

        if action_id == _SUMMON_SKILL:
            summon_steps.append(index)
            current = _summoned_monsters(session.state)
            summon_unit_ids.append(tuple(sorted(current)))
            summon_records = [
                record.get("payload") or {}
                for record in _records(transition)
                if record.get("record_type") == "summon_transition"
            ]
            started = {
                str(payload["unit_ids"][0])
                for payload in summon_records
                if payload.get("ok") is True and payload.get("unit_ids")
            }
            startup_units = {
                str((record.get("payload") or {}).get("unit_id"))
                for record in _records(transition)
                if record.get("record_type") == "monster_startup"
            }
            assert len(started) == 2, started
            assert startup_units == started, (startup_units, started)
            if not first_children:
                by_opcode = {}
                for condition in _condition_results(transition):
                    by_opcode.setdefault(condition["opcode"], []).append(condition["result"])
                # The source branch for this card: the caster is not monster 1003011.
                assert by_opcode["ByCompareMonsterID"] == [False]
                assert by_opcode["ByCompareCharacterNumber"] == [True, True]
                assert by_opcode["ByCompareDynamicValue"] == [True, True]
                assert by_opcode["ByIsTeamLocationIndexType"] == [True, True]
                executed = [
                    (record.get("payload") or {}).get("task_id")
                    for record in _records(transition)
                    if record.get("record_type") == "ability_task"
                    and (record.get("payload") or {}).get("opcode") == "SummonMonster"
                    and (record.get("payload") or {}).get("ok") is True
                ]
                assert len(executed) == 2, executed
                assert len(current) == 2
                first_children = dict(current)
                first_child_birth_statuses = tuple(sorted(next(iter(current.values())).statuses))
                for unit_id, unit in first_children.items():
                    assert unit.template_id == _CHILD_TEMPLATE
                    assert unit.level == 44  # owner level binding
                    assert unit.flags["owner_id"] == _LIEUT
                    assert unit.flags["summoner_id"] == _LIEUT
                    assert unit.flags["team_side"] == "enemy"
                    assert unit.flags["monster_data_card_id"] == "monster_data_card:monster:1002040"
                    assert unit.flags["custom_value_tags"] == ["W1_Soldier"]
                    assert unit.flags["timeline_admitted"] is True
                    assert _STARTUP_STATUSES.issubset(set(unit.statuses)), unit.statuses
                    # The executed failed branch declares no DelayRatio, so the
                    # initial action value is the full source action value.
                    assert unit.action_value == pytest.approx(gauge / unit.speed)
                    assert _owned_dynamic_values(session.state, unit_id) == {}
                first_positions = {
                    unit.flags["position"] for unit in first_children.values()
                }
                assert len(first_positions) == 2
                # Empty formation: First/Last anchors are the source relative slots.
                assert first_positions == {-1000, 1000}
                assert first_positions.isdisjoint(
                    {session.state.units[_LIEUT].flags["position"]}
                )
                _assert_unique_present_positions(session.state)
                adjacent = _adjacent_targets(session.state, _LIEUT)
                assert adjacent.status == "resolved", adjacent.blocked_reason
                assert adjacent.target_ids
            else:
                # Re-summon while the lieutenant is alive: the defeated instance
                # stays defeated and a fresh pair enters the timeline.
                assert set(first_children).issubset(set(current))
                new_ids = set(current) - set(first_children)
                assert len(new_ids) == 2
                second_children = {unit_id: current[unit_id] for unit_id in new_ids}
                old_positions = {
                    unit.flags["position"] for unit in first_children.values()
                }
                new_positions = {
                    unit.flags["position"] for unit in second_children.values()
                }
                for unit_id, unit in second_children.items():
                    assert unit.lifecycle_status == "active"
                    assert unit.template_id == _CHILD_TEMPLATE
                    assert unit.flags["owner_id"] == _LIEUT
                    assert isinstance(unit.flags["position"], int)
                    assert unit.action_value == pytest.approx(gauge / unit.speed)
                    assert tuple(sorted(unit.statuses)) == first_child_birth_statuses
                    assert _owned_dynamic_values(session.state, unit_id) == {}
                # Re-summon must not reuse a living (or present) unit's position.
                assert len(new_positions) == 2
                assert new_positions.isdisjoint(old_positions)
                _assert_unique_present_positions(session.state)
                adjacent = _adjacent_targets(session.state, _LIEUT)
                assert adjacent.status == "resolved", adjacent.blocked_reason
                assert adjacent.target_ids
                assert session.state.units[defeated_id].lifecycle_status == "defeated"

        if actor_id.startswith("enemy:summon:") and action_id == _CHILD_SKILL:
            assert command["target_ids"] == ["natasha"]
            if not second_children:
                first_child_actions.append(actor_id)
            else:
                second_child_actions.append(actor_id)

        for mutation in transition.transaction.mutations:
            if (
                mutation.path[:1] == ("units",)
                and len(mutation.path) == 3
                and mutation.path[2] == "lifecycle_status"
                and mutation.after == "defeated"
                and mutation.path[1].startswith("enemy:summon:")
            ):
                assert not defeated_id or defeated_id == mutation.path[1]
                defeated_id = str(mutation.path[1])
                defeat_step = index

    assert len(summon_steps) == 2
    assert len(first_children) == 2 and len(second_children) == 2
    assert defeat_step >= 0 and summon_steps[1] > defeat_step
    assert defeated_id in first_children
    assert set(second_children).isdisjoint(set(first_children))
    assert set(first_child_actions) >= set(first_children), (first_child_actions, first_children)
    assert set(second_child_actions) >= set(second_children), (second_child_actions, second_children)
    assert audited_transitions >= 4
    assert all(count == 1 for count in spawn_mutations.values()), spawn_mutations
    assert spawn_mutations[defeated_id] == 1
    # The defeated instance never acts again after its defeat.
    for step in range(defeat_step + 1, len(decision_actors_by_step)):
        assert defeated_id not in decision_actors_by_step[step], step

    decision = session.advance()
    assert decision.ready, decision.blocked_reason
    assert session.outcome == ""
    assert session.state.units[_LIEUT].lifecycle_status == "active"
    assert session.state.units[defeated_id].lifecycle_status == "defeated"

    # Save the formal session archive and replay it in an independent process.
    archive_path = Path(tmp_path) / "silvermane_lieutenant_summon_natural.archive.json"
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
    assert report["step_count"] == len(session.operations)
    assert report["errors"] == []
