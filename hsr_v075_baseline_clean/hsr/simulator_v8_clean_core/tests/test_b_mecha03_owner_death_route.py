"""Aurumaton Gatekeeper: native deathrattle explosion and linked retirement.

Source route: StageConfig 307214 wave 0, one Lv44 monster:2013010. Ally skill
uses raise the Overdrive accumulate stacks to three; the DelayActive controller
inserts Monster_W2_Mecha03_00_SkillP01_Insert at MonsterChangeState, which
summons two monster:2012010 Illumination Dragonfish through the shared summon
relation.

Both children act. One child is then naturally defeated by an ally attack. Its
OnDeathrattle callback (MMonster_W2_Mecha02_00_Initiate, Deathrattle +
KeepOnDeathrattle) removes its other statuses through the real status lifecycle,
confirms the finalized death instance with SetDieImmediately, and enqueues
Monster_W2_Mecha02_00_SkillP01_Insert at MonsterDeathRattle with the source
Mask_AliveOrLimbo masks and CanRunOnUnselectableTarget.

The inserted death animation's gameplay leaves execute in source order:
DamageByAttackProperty(AllTeammate, Fire, ByMaxHP) and
AddModifier(MCommon_DefenceRatioDown). The native ByMaxHP formula reads the
caster's own Max HP, so the explosion is 40% of the dead Dragonfish itself - a
real but bounded Fire hit on the caster team's other living units (the
Gatekeeper and the surviving Dragonfish), followed by the formal defence-down
entry of that same insert instance. The defence-down chance is native, so one
recipient may legitimately miss.

The Gatekeeper is not required to die in the explosion transaction. It is
defeated later by ordinary ally attacks while the other child is still alive;
its MCommon_Servant summon-relation listener then enqueues
Common_Servant_Forcekill for that child at MonsterForceKill. The formal
non-damage forced death runs the child's own deathrattle insert (no living
teammate remains) before the wave closes into victory.

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
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

_CORE = Path(__file__).resolve().parents[1]
_ROOT = Path(__file__).resolve().parents[4]
_SCENARIO = _CORE / "examples/cli/b_mecha03_blue_dragon_fish_owner_death.json"
_COMMANDS = _CORE / "examples/cli/b_mecha03_blue_dragon_fish_owner_death.commands.json"

_BOSS = "enemy:stage:307214:wave:0:pos:0"
_SUMMON_ABILITY = "Monster_W2_Mecha03_00_SkillP01_Insert"
_DEATHRATTLE_ABILITY = "Monster_W2_Mecha02_00_SkillP01_Insert"
_FORCE_KILL_ABILITY = "Common_Servant_Forcekill"
_DEATHRATTLE_MODIFIER = "MMonster_W2_Mecha02_00_Initiate"
_SERVANT_MODIFIER = "MCommon_Servant"
_DEFENCE_DOWN = "MCommon_DefenceRatioDown"
_OVERDRIVE_ACCUMULATE = "MMonster_W2_Mecha03_00_Overdrive_Accumulate"


def _records(transition):
    settlement = transition.transaction.settlement
    return tuple(settlement.records) if settlement is not None else ()


def _payloads(transition, record_type):
    return tuple(
        record.get("payload") or {}
        for record in _records(transition)
        if record.get("record_type") == record_type
    )


def _events(transition, event_type):
    return tuple(
        event
        for event in transition.transaction.events
        if event.event_type == event_type
    )


def _units(transition, phase):
    # The action transaction stores its own before snapshot; the committed
    # after snapshot belongs to the transition itself.
    state = transition.transaction.before if phase == "before" else transition.after
    return state.data["units"]


def _summoned_monsters(state):
    return {
        unit_id: unit
        for unit_id, unit in state.units.items()
        if unit.flags.get("summon_kind") == "summoned_monster"
    }


def _status_details(committed_state, unit_id):
    return tuple(
        detail
        for detail in committed_state.data["units"][unit_id]["flags"].get("status_details") or ()
        if isinstance(detail, dict)
    )


def _rules_facts(rules):
    """Re-check the formal source of the explosion and return its ratio."""

    deathrattle_graph = next(
        item
        for item in rules.ir.standalone_ability_graphs
        if item.ability_name == _DEATHRATTLE_ABILITY
    )
    assert deathrattle_graph.coverage_status == "executable", deathrattle_graph.blocked_reason
    tasks = [
        task
        for phase_id in deathrattle_graph.phase_ids
        for task in rules.ability_tasks_for_phase(phase_id)
    ]
    by_id = {task.task_id: task for task in tasks}
    wrapper = next(task for task in tasks if task.opcode == "TriggerAnimStateWithMove")
    assert wrapper.coverage_status == "executable", wrapper.blocked_reason
    assert wrapper.execution_mode == "runtime_effect"
    wrapper_children = [by_id[task_id] for task_id in wrapper.child_task_ids]
    assert {child.parent_task_id for child in wrapper_children} == {wrapper.task_id}
    gameplay_children = [
        child.opcode
        for child in wrapper_children
        if child.execution_mode == "runtime_effect"
    ]
    assert gameplay_children == [
        "DamageByAttackProperty",
        "AddModifier",
    ]
    damage_task = next(
        by_id[task_id]
        for task_id in wrapper.child_task_ids
        if by_id[task_id].opcode == "DamageByAttackProperty"
    )
    emission = rules.damage_emissions_for_task(damage_task.task_id)[0]
    assert damage_task.coverage_status == "executable", damage_task.blocked_reason
    assert emission.coverage_status == "executable", emission.blocked_reason
    assert emission.target_group == "all_teammate"
    assert emission.element_type == "Fire"
    basis = emission.scaling_basis_expr
    assert basis["kind"] == "unit_stat"
    # A native AttackData ByMaxHP formula reads the caster's own Max HP. The
    # Illumination Dragonfish explosion is a ratio of the dead Dragonfish
    # itself, never of any damaged recipient.
    assert basis["unit_ref"] == "attacker"
    assert basis["stat"] == "max_hp"
    assert basis["formula_type"] == "ByMaxHP"
    assert basis["data_card_id"] == "monster_data_card:monster:2012010"
    assert basis["param_index"] == 0
    source_param = basis["param_value"]
    assert isinstance(source_param, dict) and set(source_param) == {"Value"}
    source_ratio = float(source_param["Value"])
    assert 0 < source_ratio < 1
    add_modifier = next(
        by_id[task_id] for task_id in wrapper.child_task_ids
        if by_id[task_id].opcode == "AddModifier"
    )
    assert add_modifier.coverage_status == "executable", add_modifier.blocked_reason
    modifier_effect = rules.effect(add_modifier.effect_id)
    assert modifier_effect.payload["standard"]["modifier_name"] == _DEFENCE_DOWN
    assert modifier_effect.payload["standard"]["target_alias"] == "AllTeammate"

    intent = next(
        item
        for item in rules.ir.queue_intents
        if item.action_ref_or_ability_name == _DEATHRATTLE_ABILITY
        and item.coverage_status == "executable"
    )
    assert intent.opcode == "TurnInsertAbility"
    assert intent.owner_alive_state == "alive_or_limbo"
    assert intent.target_alive_state == "alive_or_limbo"
    assert intent.can_run_on_unselectable_target is True
    assert intent.priority_source["priority_key"] == "MonsterDeathRattle"
    assert intent.priority_source["priority_ordering_admitted"] is True

    callback = next(
        item
        for item in rules.ir.status_callbacks
        if item.modifier_name == _DEATHRATTLE_MODIFIER
        and item.event == "OnDeathrattle"
    )
    assert callback.coverage_status == "executable", callback.blocked_reason
    callback_tasks = [
        next(task for task in rules.ir.status_callback_tasks if task.task_id == task_id)
        for task_id in callback.task_ids
    ]
    assert [task.opcode for task in callback_tasks] == [
        "DispelStatus",
        "SetDieImmediately",
        "TurnInsertAbility",
    ]
    assert rules.effect(callback_tasks[0].effect_id).payload["standard"]["operation"] == "deathrattle_status_cleanup"
    assert rules.effect(callback_tasks[1].effect_id).payload["standard"]["deathrattle_source"] is True

    force_kill_intent = next(
        item
        for item in rules.ir.queue_intents
        if item.action_ref_or_ability_name == _FORCE_KILL_ABILITY
        and item.coverage_status == "executable"
    )
    assert force_kill_intent.opcode == "TurnInsertAbility"
    assert force_kill_intent.owner_alive_state == "alive_or_revivable"
    assert force_kill_intent.target_alive_state == "alive_or_revivable"
    assert force_kill_intent.can_run_on_unselectable_target is True
    assert force_kill_intent.priority_source["priority_key"] == "MonsterForceKill"
    force_kill_graph = next(
        item
        for item in rules.ir.standalone_ability_graphs
        if item.ability_name == _FORCE_KILL_ABILITY
    )
    assert force_kill_graph.coverage_status == "executable", force_kill_graph.blocked_reason
    force_kill_task = next(
        task
        for phase_id in force_kill_graph.phase_ids
        for task in rules.ability_tasks_for_phase(phase_id)
        if task.opcode == "ForceKill"
    )
    force_kill_standard = rules.effect(force_kill_task.effect_id).payload["standard"]
    assert force_kill_standard["operation"] == "formal_forced_death"
    assert force_kill_standard["abort_unused_insert_ability"] is True
    assert force_kill_standard["source_shape_admitted"] is True
    return source_ratio


def test_b_aurumaton_second_summoner_deathrattle_owner_death(tmp_path):
    scenario = json.loads(_SCENARIO.read_text(encoding="utf-8"))
    script = json.loads(_COMMANDS.read_text(encoding="utf-8"))
    # The formal CLI script is exactly the commands root, nothing else.
    assert set(script) == {"commands"}
    commands = script["commands"]
    assert commands
    rules = build_battle_rulebook(_ROOT / "turnbasedgamedata-main", scenario)
    source_ratio = _rules_facts(rules)
    session = BattleSession(rules, scenario)
    auditor = RuntimeSourceAuditor(rules)

    transitions = []
    audited = 0

    def collect(items, label):
        nonlocal audited
        for transition in items:
            audit = auditor.validate_transition(transition)
            assert audit.ok, (label, [violation.to_json() for violation in audit.violations[:3]])
            audited += 1
            transitions.append(transition)

    for index, command in enumerate(commands):
        decision, advancements = session.advance_with_transitions()
        collect(advancements, f"advance:{index}")
        if session.outcome:
            break
        assert decision.ready, (index, decision.blocked_reason)
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, result.transition.outcome.reason_codes
        collect((result.transition,), f"submit:{index}")
        if session.outcome:
            break
    for _ in range(8):
        if session.outcome:
            break
        _, advancements = session.advance_with_transitions()
        collect(advancements, "final_advance")
    assert session.outcome == "victory"
    assert audited >= 4

    children = _summoned_monsters(session.state)
    assert len(children) == 2
    assert {unit.flags.get("summoner_id") for unit in children.values()} == {_BOSS}

    # --- Overdrive and the formal summon insert ---------------------------
    overdrive_peaks = []
    summon_enqueue = None
    for index, transition in enumerate(transitions):
        for mutation in transition.transaction.mutations:
            if (
                len(mutation.path) == 4
                and mutation.path[2:] == ("flags", "status_details")
                and mutation.path[1] == _BOSS
            ):
                stacks = [
                    detail.get("stacks")
                    for detail in (mutation.after or ())
                    if isinstance(detail, dict)
                    and detail.get("modifier_name") == _OVERDRIVE_ACCUMULATE
                ]
                overdrive_peaks.extend(int(value) for value in stacks if isinstance(value, int))
        if summon_enqueue is not None:
            continue
        entries = [
            item["entry"]
            for item in _payloads(transition, "queue_enqueue")
            if isinstance(item.get("entry"), dict)
            and item["entry"].get("action_or_ability_ref") == _SUMMON_ABILITY
        ]
        if entries:
            summon_enqueue = (index, entries)
    assert max(overdrive_peaks) == 3
    assert summon_enqueue is not None
    _, summon_entries = summon_enqueue
    assert len(summon_entries) == 1
    assert summon_entries[0]["owner_alive_state"] == "alive_only"
    assert summon_entries[0]["target_alive_state"] == "alive_only"

    # --- Natural death of one child and its typed Deathrattle admission ---
    natural_death_index = next(
        index
        for index, transition in enumerate(transitions)
        if any(
            event.target_id in children
            and event.payload.get("record_type") != "formal_forced_death"
            for event in _events(transition, "unit.defeated")
        )
    )
    death = transitions[natural_death_index]
    dead_child = next(
        event.target_id
        for event in _events(death, "unit.defeated")
        if event.target_id in children
    )
    survivor = next(iter(set(children) - {dead_child}))
    defeat_event = next(
        event
        for event in _events(death, "unit.defeated")
        if event.target_id == dead_child
    )
    death_instance_id = defeat_event.payload["lifecycle_mutation_id"]
    ally_ids = {
        unit_id for unit_id, unit in session.state.units.items() if unit.side == "ally"
    }
    assert defeat_event.payload.get("record_type") in {"damage", "break_damage"}
    assert defeat_event.payload.get("attacker_id") in ally_ids
    death_before = _units(death, "before")
    death_after = _units(death, "after")
    assert death_before[survivor]["lifecycle_status"] == "active"
    assert death_after[survivor]["lifecycle_status"] == "active"
    assert death_after[dead_child]["lifecycle_status"] == "defeated"
    assert death_after[dead_child]["hp"] == 0

    cleanups = _payloads(death, "deathrattle_status_cleanup")
    assert len(cleanups) == 1
    cleanup = cleanups[0]
    assert cleanup["target_id"] == dead_child
    assert cleanup["death_instance_id"] == death_instance_id
    assert cleanup["removed_instance_ids"]
    kept_reasons = {item.get("reason") for item in cleanup["kept"]}
    assert "keep_on_deathrattle" in kept_reasons
    immediate = _payloads(death, "deathrattle_immediate_retirement")
    assert immediate and immediate[0]["death_instance_id"] == death_instance_id
    before_names = {
        detail.get("modifier_name")
        for detail in _status_details(death.transaction.before, dead_child)
    }
    after_names = {
        detail.get("modifier_name")
        for detail in _status_details(death.after, dead_child)
    }
    assert _SERVANT_MODIFIER in before_names
    assert _SERVANT_MODIFIER not in after_names
    assert _DEATHRATTLE_MODIFIER in after_names

    enqueued = [
        item["entry"]
        for item in _payloads(death, "queue_enqueue")
        if isinstance(item.get("entry"), dict)
        and item["entry"].get("action_or_ability_ref") == _DEATHRATTLE_ABILITY
    ]
    assert len(enqueued) == 1
    entry = enqueued[0]
    admission = entry["deathrattle_admission"]
    assert admission["unit_id"] == dead_child
    assert admission["death_instance_id"] == death_instance_id
    assert admission["source_event_id"] == defeat_event.event_id
    assert admission["queue_intent_id"] == entry["queue_intent_id"]
    assert admission["queue_kind"] == entry["queue_kind"]
    assert admission["source_task_id"]
    assert entry["owner_alive_state"] == "alive_or_limbo"
    assert entry["target_alive_state"] == "alive_or_limbo"
    assert entry["can_run_on_unselectable_target"] is True

    # --- The inserted death animation drains in its own transaction -------
    insert_index = next(
        index
        for index in range(natural_death_index + 1, len(transitions))
        if transitions[index].transaction.command.actor_id == dead_child
        and any(
            payload.get("ability_name") == _DEATHRATTLE_ABILITY
            for payload in _payloads(transitions[index], "standalone_ability_execution")
        )
    )
    insert_drain = transitions[insert_index]
    invocation = next(
        payload["invocation"]
        for payload in _payloads(insert_drain, "standalone_ability_execution")
        if payload.get("ability_name") == _DEATHRATTLE_ABILITY
    )
    assert invocation["actor_id"] == dead_child
    assert invocation["death_instance_id"] == death_instance_id
    assert invocation["queue_entry_id"] == entry["entry_id"]
    assert insert_drain.outcome.successor_eligible

    before_units = _units(insert_drain, "before")
    after_units = _units(insert_drain, "after")
    assert before_units[dead_child]["lifecycle_status"] == "defeated"
    assert before_units[dead_child]["hp"] == 0
    assert before_units[_BOSS]["lifecycle_status"] == "active"
    assert before_units[survivor]["lifecycle_status"] == "active"
    living_team = {
        unit_id
        for unit_id, unit in before_units.items()
        if unit["side"] == "enemy"
        and unit["lifecycle_status"] == "active"
        and unit["hp"] > 0
    }
    assert living_team == {_BOSS, survivor}
    survivor_names = {
        detail.get("modifier_name")
        for detail in _status_details(insert_drain.transaction.before, survivor)
    }
    assert _SERVANT_MODIFIER in survivor_names
    fish_max_hp = before_units[dead_child]["max_hp"]
    assert fish_max_hp > 0
    # The two recipients do not share the caster's Max HP.
    assert len({before_units[unit_id]["max_hp"] for unit_id in living_team}) == 2
    assert fish_max_hp != before_units[_BOSS]["max_hp"]

    # --- Native ByMaxHP explosion, checked from formula and ledger --------
    damage_events = _events(insert_drain, "damage.hit")
    assert {event.target_id for event in damage_events} == living_team
    assert all(event.payload.get("element_type") == "Fire" for event in damage_events)
    assert all(
        event.payload.get("attacker_id") == dead_child for event in damage_events
    )
    damage_records = [
        record
        for record in _records(insert_drain)
        if record.get("record_type") == "damage"
    ]
    assert len(damage_records) == 2
    damaged_targets = set()
    for record in damage_records:
        payload = record["payload"]
        formula = payload["formula_result"]
        scaling = formula["scaling"]
        basis = scaling["basis_result"]
        assert payload["element_type"] == "Fire"
        assert basis["ok"] is True
        assert not basis["blocked_reason"]
        assert basis["unit_ref"] == "attacker"
        assert basis["unit_id"] == dead_child
        assert basis["stat"] == "max_hp"
        assert basis["value"] == pytest.approx(fish_max_hp)
        # The ratio is the formal SkillP01 ParamList[0] value, never a baked
        # damage number.
        assert payload["scaling_ratio"] == pytest.approx(source_ratio)
        assert scaling["ratio"] == pytest.approx(source_ratio)
        assert scaling["base_damage"] == pytest.approx(basis["value"] * source_ratio)
        ledger_terms = [
            term
            for term in payload["damage_pipeline"]["applied_terms"]
            if term.get("source_type") == "scaling_basis"
        ]
        assert len(ledger_terms) == 1
        term = ledger_terms[0]
        assert term["applied_reason"] == "resolved_scaling_basis"
        assert term["scope"] == "attacker"
        assert term["key"] == "max_hp"
        assert term["source_id"] == dead_child
        assert term["applied_value"] == pytest.approx(fish_max_hp)
        target_id = formula["target_id"]
        assert target_id in living_team
        assert payload["target_before_hp"] > 0
        damaged_targets.add(target_id)
    assert damaged_targets == living_team

    # --- The same insert lands the formal defence-down on the caster team --
    landed = [
        record
        for record in _records(insert_drain)
        if record.get("record_type") == "status"
        and (record.get("payload") or {})
        .get("status_instance", {})
        .get("modifier_name") == _DEFENCE_DOWN
    ]
    assert landed
    landed_owners = set()
    for record in landed:
        payload = record["payload"]
        instance = payload["status_instance"]
        assert payload["partial"] is False
        assert not payload["lifecycle_result"]["unsupported"]
        assert instance["caster_id"] == dead_child
        assert instance["owner_id"] in living_team
        assert instance["lifecycle_state"] == "active"
        assert "STAT_DefenceDown" in instance["behavior_flags"]
        landed_owners.add(instance["owner_id"])
    chance_failures = [
        record
        for record in _records(insert_drain)
        if record.get("record_type") == "status_apply_failed"
        and (record.get("payload") or {}).get("modifier_name") == _DEFENCE_DOWN
    ]
    for record in chance_failures:
        payload = record["payload"]
        assert payload["reason"] == "final_status_application_failed"
        assert payload["caster_id"] == dead_child
        assert payload["target_id"] in living_team
        chance = payload["chance_admission"]
        assert chance["admission_status"] == "executable"
        assert chance["guaranteed"] is False
        assert 0 < chance["final_success_probability"] < 1
        assert payload["rng_event"]
    attempted = landed_owners | {
        record["payload"]["target_id"] for record in chance_failures
    }
    assert attempted == living_team
    # The real defence-down instance landed on the Gatekeeper.
    assert _BOSS in landed_owners
    boss_details_after = {
        detail.get("modifier_name")
        for detail in _status_details(insert_drain.after, _BOSS)
    }
    assert _DEFENCE_DOWN in boss_details_after

    # --- The owner is defeated later by ordinary ally attacks -------------
    assert not [
        event
        for event in _events(insert_drain, "unit.defeated")
        if event.target_id == _BOSS
    ]
    assert after_units[_BOSS]["lifecycle_status"] == "active"
    assert after_units[survivor]["lifecycle_status"] == "active"
    boss_death_index = next(
        index
        for index in range(insert_index + 1, len(transitions))
        if any(
            event.target_id == _BOSS
            for event in _events(transitions[index], "unit.defeated")
        )
    )
    boss_death = transitions[boss_death_index]
    boss_defeat = next(
        event
        for event in _events(boss_death, "unit.defeated")
        if event.target_id == _BOSS
    )
    assert boss_defeat.payload.get("record_type") == "damage"
    assert not boss_defeat.payload.get("forced_death_kind")
    assert boss_defeat.payload.get("attacker_id") in ally_ids
    boss_before = _units(boss_death, "before")
    assert boss_before[_BOSS]["lifecycle_status"] == "active"
    assert boss_before[survivor]["lifecycle_status"] == "active"
    assert boss_before[survivor]["hp"] > 0

    # --- The summon relation enqueues the formal ForceKill ---------------
    force_kill_entries = [
        item["entry"]
        for item in _payloads(boss_death, "queue_enqueue")
        if isinstance(item.get("entry"), dict)
        and item["entry"].get("action_or_ability_ref") == _FORCE_KILL_ABILITY
    ]
    assert len(force_kill_entries) == 1
    force_kill_entry = force_kill_entries[0]
    assert force_kill_entry["queue_kind"] == "turn_insert_ability"
    assert force_kill_entry["priority_key"] == "MonsterForceKill"
    assert force_kill_entry["owner_alive_state"] == "alive_or_revivable"
    assert force_kill_entry["target_alive_state"] == "alive_or_revivable"
    assert force_kill_entry["can_run_on_unselectable_target"] is True
    assert force_kill_entry["actor_id"] == survivor
    assert force_kill_entry["target_ids"] == [survivor]

    # --- The related child dies through the formal forced-death branch ----
    forced_index = next(
        index
        for index in range(boss_death_index + 1, len(transitions))
        if any(
            event.target_id == survivor
            and event.payload.get("forced_death_kind") == "formal_ability_force_kill"
            for event in _events(transitions[index], "unit.defeated")
        )
    )
    forced = transitions[forced_index]
    forced_event = next(
        event
        for event in _events(forced, "unit.defeated")
        if event.target_id == survivor
    )
    assert forced_event.payload.get("record_type") == "formal_forced_death"
    assert forced_event.payload.get("forced_death_kind") == "formal_ability_force_kill"
    assert forced.transaction.command.actor_id == survivor
    assert not _events(forced, "damage.hit")
    force_kill_resolutions = [
        payload["queue_resolution"]
        for payload in _payloads(forced, "queue_dequeue")
        if isinstance(payload.get("queue_resolution"), dict)
        and payload["queue_resolution"].get("action_or_ability_ref") == _FORCE_KILL_ABILITY
    ]
    assert force_kill_resolutions
    assert forced.outcome.successor_eligible
    forced_after = _units(forced, "after")
    assert forced_after[survivor]["lifecycle_status"] == "defeated"
    assert forced_after[survivor]["hp"] == 0
    assert forced_after[survivor]["flags"]["defeat_record"]["forced_death_kind"] == (
        "formal_ability_force_kill"
    )

    # --- The forced death runs the sibling's own (empty) deathrattle ------
    survivor_insert_index = next(
        index
        for index in range(forced_index, len(transitions))
        if transitions[index].transaction.command.actor_id == survivor
        and any(
            payload.get("ability_name") == _DEATHRATTLE_ABILITY
            for payload in _payloads(transitions[index], "standalone_ability_execution")
        )
    )
    survivor_insert = transitions[survivor_insert_index]
    assert not [
        record
        for record in _records(survivor_insert)
        if record.get("record_type") == "damage"
    ]
    empty_group = [
        record
        for record in _records(survivor_insert)
        if record.get("record_type") == "ability_task"
        and (record.get("payload") or {}).get("blocked_reason")
        == "damage_relative_side_target_group_empty"
    ]
    assert empty_group
    assert survivor_insert.outcome.successor_eligible

    # --- Queue closure precedes the wave transition and victory -----------
    victory_index = next(
        index
        for index, transition in enumerate(transitions)
        if _events(transition, "battle.victory")
    )
    assert victory_index > survivor_insert_index
    assert session.outcome == "victory"
    assert session.state.units[_BOSS].lifecycle_status in {"defeated", "removed"}
    assert session.state.units[survivor].lifecycle_status == "defeated"
    assert session.state.units[dead_child].lifecycle_status == "defeated"
    rejected = session.submit(command_from_json(commands[-1]))
    assert rejected.transition.outcome.successor_eligible is False

    archive_path = Path(tmp_path) / "b_mecha03_owner_death.archive.json"
    write_archive(archive_path, session.archive())
    env = {**os.environ, "PYTHONPATH": str(_ROOT / "hsr_v075_baseline_clean")}
    completed = subprocess.run(
        [sys.executable, "-m", "hsr.simulator_v8_clean_core.cli", "replay", str(archive_path)],
        cwd=str(_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert completed.returncode == 0, (completed.stdout[-2000:], completed.stderr[-2000:])
    report = json.loads(completed.stdout)
    assert report["ok"] is True, report
    assert report["errors"] == []
    assert report["step_count"] == len(session.operations)
