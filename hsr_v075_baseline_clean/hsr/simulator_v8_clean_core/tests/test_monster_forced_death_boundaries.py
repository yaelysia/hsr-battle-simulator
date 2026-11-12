"""Boundary checks for the monster forced-death closure.

These are component-level checks around the real compiled source slice used by
the Silvermane Lieutenant owner-death route: queue alive-state masks, the
AbortUnusedInsertAbility cleanup shape, forced-death lifecycle preconditions,
transaction rollback when the second relation listener cannot enqueue, and the
native audit negative cases.
"""
from __future__ import annotations

import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest

from hsr.simulator_v8_clean_core.core.model import GameEvent, Mutation, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.settlement import SettlementRecord
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.session import BattleSession, command_from_json
from hsr.simulator_v8_clean_core.systems.queue import (
    QueueEntry,
    QueueSystem,
    QueueTargetResolution,
    QueueTargetResolver,
    unit_alive_state_blocked_reason,
)
from hsr.simulator_v8_clean_core.systems.mutation_events import mutation_backed_event_id
from hsr.simulator_v8_clean_core.systems.unit_lifecycle import UnitLifecycleSystem
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

_CORE = Path(__file__).resolve().parents[1]
_ROOT = Path(__file__).resolve().parents[4]
_SCENARIO = _CORE / "examples/cli/silvermane_lieutenant_owner_death.json"
_COMMANDS = _CORE / "examples/cli/silvermane_lieutenant_owner_death.commands.json"

_LIEUT = "enemy:stage:307311:wave:0:pos:0"


@lru_cache(maxsize=1)
def _rules():
    scenario = json.loads(_SCENARIO.read_text(encoding="utf-8"))
    return build_battle_rulebook(_ROOT / "turnbasedgamedata-main", scenario)


def _summoned_monsters(state):
    return {
        unit_id: unit
        for unit_id, unit in state.units.items()
        if unit.flags.get("summon_kind") == "summoned_monster"
    }


def _enter_with_soldiers():
    scenario = json.loads(_SCENARIO.read_text(encoding="utf-8"))
    commands = json.loads(_COMMANDS.read_text(encoding="utf-8"))["commands"]
    rules = _rules()
    session = BattleSession(rules, scenario, diagnostics="full")
    session.advance()
    result = session.submit(command_from_json(commands[0]))
    assert result.transition.outcome.successor_eligible
    assert len(_summoned_monsters(session.state)) == 2
    return rules, session, commands


def _relation_intent(rules):
    return next(
        intent
        for intent in rules.ir.queue_intents
        if "MCommon_Servant" in intent.callback_id
    )


def _queue_entry(rules, intent, actor_id, entry_id):
    window = next(
        item
        for item in rules.ir.queue_windows
        if item.queue_intent_id == intent.queue_intent_id
    )
    target_resolution = {
        "ok": True,
        "actor_id": actor_id,
        "target_ids": [actor_id],
        "actor_alias": "ModifierOwnerEntity",
        "target_alias": "ModifierOwnerEntity",
        "blocked_reason": "",
        "source_trace": {},
    }
    return QueueEntry(
        entry_id=entry_id,
        queue_name=intent.queue_kind,
        queue_kind=intent.queue_kind,
        queue_intent_id=intent.queue_intent_id,
        actor_id=actor_id,
        action_or_ability_ref="Common_Servant_Forcekill",
        target_ids=(actor_id,),
        priority_source=intent.priority_source,
        source_trace={},
        priority_key=str(intent.priority_source.get("priority_key") or ""),
        priority_value=float(intent.priority_source.get("priority_value") or 0.0),
        queue_priority_id=str(intent.priority_source.get("queue_priority_id") or ""),
        queue_window_id=window.queue_window_id,
        window_family=window.window_family,
        window_policy=window.window_policy,
        target_resolution=target_resolution,
        owner_id=actor_id,
        owner_alive_state=intent.owner_alive_state,
        target_alive_state=intent.target_alive_state,
        can_run_on_unselectable_target=intent.can_run_on_unselectable_target,
    ).to_json()


@pytest.mark.integration
def test_abort_unused_insert_preserves_unrelated_entries_and_order():
    rules, session, _commands = _enter_with_soldiers()
    intent = _relation_intent(rules)
    children = sorted(_summoned_monsters(session.state))
    assert len(children) == 2
    first, second = children
    unrelated = _queue_entry(rules, intent, _LIEUT, "queue_entry:test:unrelated")
    first_entry = _queue_entry(rules, intent, first, "queue_entry:test:first")
    second_entry = _queue_entry(rules, intent, second, "queue_entry:test:second")
    queue_name = str(intent.queue_kind)
    seeded = MutationReducer().apply_all(
        session.state,
        (
            Mutation(
                "set",
                ("queues", queue_name),
                None,
                [first_entry, unrelated, second_entry],
                reason="component fixture queue entries",
                source="queue_system",
                before_exists=False,
            ),
        ),
    )

    mutations, events, records = QueueSystem().abort_unused_insert_entries_for_unit(
        seeded,
        first,
        reason="queue_action_actor_unit_defeated",
        source_trace={"injected": "abort_unused_insert"},
    )

    assert len(mutations) == 1
    mutation = mutations[0]
    assert mutation.path == ("queues", queue_name)
    assert mutation.before == [first_entry, unrelated, second_entry]
    assert mutation.after == [unrelated, second_entry]
    assert mutation.metadata["queue_operation"] == "terminal_remove"
    assert (
        mutation.metadata["queue_cleanup_operation"]
        == "abort_unused_insert_ability"
    )
    terminal = mutation.metadata["queue_terminal_plan"]
    assert terminal["disposition"] == "cancelled"
    assert terminal["monotonic_progress"] is True
    assert terminal["blocked_reason"] == "queue_action_actor_unit_defeated"
    assert mutation.metadata["queue_intent_id"] == intent.queue_intent_id
    assert len(events) == 1 and events[0].event_type == "queue.entry.terminal"
    assert len(records) == 1 and records[0]["record_type"] == "queue_entry_terminal"
    # The sibling soldier's own entry is untouched and keeps its order.
    applied = MutationReducer().apply_all(seeded, mutations)
    assert [item["entry_id"] for item in applied.queues[queue_name]] == [
        unrelated["entry_id"],
        second_entry["entry_id"],
    ]


def test_alive_state_mask_blocks_revivable_branch_explicitly():
    defeated = UnitState(
        "child", "enemy", "monster:minion", lifecycle_status="defeated", hp=0.0
    )
    limbo = UnitState(
        "limbo", "enemy", "monster:minion", lifecycle_status="limbo", hp=0.0
    )
    active = UnitState("active", "enemy", "monster:minion")
    state = SimpleNamespace(
        units={item.unit_id: item for item in (defeated, limbo, active)}
    )

    assert unit_alive_state_blocked_reason(
        state, "active", "alive_only", role="owner"
    ) == ""
    assert unit_alive_state_blocked_reason(
        state, "limbo", "alive_or_limbo", role="target"
    ) == ""
    assert unit_alive_state_blocked_reason(
        state, "limbo", "alive_only", role="target"
    ) == "queue_target_alive_state_not_met:limbo:limbo"
    assert unit_alive_state_blocked_reason(
        state, "child", "alive_or_revivable", role="target"
    ) == "queue_target_revivable_branch_not_admitted:child"
    assert unit_alive_state_blocked_reason(
        state, "missing", "alive_or_revivable", role="owner"
    ) == "queue_owner_alive_state_unit_missing:missing"


def test_forced_death_requires_an_active_target():
    lifecycle = UnitLifecycleSystem()
    defeated = UnitState(
        "child", "enemy", "monster:minion", lifecycle_status="defeated", hp=0.0
    )
    state = SimpleNamespace(units={"child": defeated})
    with pytest.raises(ValueError, match="forced_death_requires_active_target"):
        lifecycle.forced_death_mutations(
            state,
            "child",
            effect_id="effect:test",
            effect_source={},
            source_trace={},
            target_alias="AbilityTargetEntity",
        )
    with pytest.raises(ValueError, match="forced_death_unit_missing"):
        lifecycle.forced_death_mutations(
            state,
            "missing",
            effect_id="effect:test",
            effect_source={},
            source_trace={},
            target_alias="AbilityTargetEntity",
        )


@pytest.mark.integration
def test_second_relation_listener_enqueue_failure_rolls_back_the_transaction(monkeypatch):
    rules, session, commands = _enter_with_soldiers()
    original = QueueTargetResolver.resolve
    failing_actor = sorted(_summoned_monsters(session.state))[1]
    relation_calls = {"ok": 0, "failed": 0}

    def injected_resolve(self, state, *, detail, trigger_event, actor_alias,
                         target_alias, source_trace=None,
                         allow_unselectable_target=False):
        resolution = original(
            self,
            state,
            detail=detail,
            trigger_event=trigger_event,
            actor_alias=actor_alias,
            target_alias=target_alias,
            source_trace=source_trace,
            allow_unselectable_target=allow_unselectable_target,
        )
        if str(detail.get("modifier_name") or "") == "MCommon_Servant" and resolution.ok:
            if resolution.actor_id == failing_actor:
                relation_calls["failed"] += 1
                return QueueTargetResolution(
                    False,
                    resolution.actor_id,
                    (),
                    resolution.actor_alias,
                    resolution.target_alias,
                    "injected_second_listener_failure",
                    resolution.source_trace,
                )
            relation_calls["ok"] += 1
        return resolution

    monkeypatch.setattr(QueueTargetResolver, "resolve", injected_resolve)

    for index, command in enumerate(commands[1:], start=1):
        decision, _ = session.advance_with_transitions()
        assert decision.ready, (index, decision.blocked_reason)
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, index

    before = session.state.snapshot().to_json()
    decision, transitions = session.advance_with_transitions()
    reason_codes = tuple(
        code
        for transition in transitions
        for code in transition.outcome.reason_codes
    )
    assert relation_calls["ok"] >= 1
    assert relation_calls["failed"] >= 1
    # The second relation listener's enqueue failed, so the whole defeated-turn
    # transaction must roll back: no HP change, no pending/defeat record, no
    # queue entry, no first listener artifact.
    assert session.state.snapshot().to_json() == before
    assert session.state.units[_LIEUT].hp > 0
    assert session.state.units[_LIEUT].lifecycle_status == "active"
    assert "pending_defeat" not in session.state.units[_LIEUT].flags
    assert "defeat_record" not in session.state.units[_LIEUT].flags
    assert not session.state.queues.get("turn_insert_ability")
    assert "injected_second_listener_failure" in " ".join(
        (decision.blocked_reason, *reason_codes)
    )


@pytest.mark.integration
def test_native_audit_rejects_forged_forced_death_sources():
    rules = _rules()
    auditor = RuntimeSourceAuditor(rules)
    source_trace = {
        "source_path": "fixture", "raw_type": "fixture", "raw_id": "fixture"
    }

    # 1) A lethal HP mutation that claims the damage producer without a damage
    #    source frame/emission lineage is rejected.
    forged_hp = Mutation(
        "set",
        ("units", "child", "hp"),
        100.0,
        0.0,
        "forged lethal damage",
        "damage_system",
    )
    forged_record = SettlementRecord(
        "damage", "damage_system", forged_hp.stable_id(), False,
        {"amount": 100.0}, source_trace,
    ).to_json()
    result = auditor.validate_execution((forged_hp,), (forged_record,))
    assert not result.ok, [violation.reason for violation in result.violations]
    assert result.violations

    # 2) Kill energy cannot cite a forced-death HP mutation as its lethal cause.
    forced_hp = Mutation(
        "set",
        ("units", "child", "hp"),
        100.0,
        0.0,
        "formal forced death",
        "effect_system",
        metadata={
            "effect_id": "effect:test:forced",
            "effect_source": source_trace,
            "lifecycle_operation": "unit_forced_death_hp",
        },
    )
    forced_status = Mutation(
        "set",
        ("units", "child", "lifecycle_status"),
        "active",
        "defeated",
        "formal forced death",
        "effect_system",
        metadata={
            "effect_id": "effect:test:forced",
            "effect_source": source_trace,
            "lifecycle_operation": "unit_defeat",
            "hp_mutation_id": forced_hp.stable_id(),
        },
    )
    kill_energy = Mutation(
        "set",
        ("units", "seele", "energy"),
        0.0,
        10.0,
        "forged kill energy",
        "damage_system.kill_energy",
        metadata={
            "hp_mutation_id": forced_hp.stable_id(),
            "lifecycle_mutation_id": forced_status.stable_id(),
            "defeated_target_id": "child",
            "source_frame": {"owner_id": "seele"},
            "source_trace": source_trace,
        },
    )
    forged_records = tuple(
        SettlementRecord(
            record_type, mutation.source, mutation.stable_id(), False,
            {"unit_id": "child"}, source_trace,
        ).to_json()
        for record_type, mutation in (
            ("unit_forced_death_hp", forced_hp),
            ("unit_defeat", forced_status),
            ("kill_energy_gain", kill_energy),
        )
    )
    result = auditor.validate_execution(
        (forced_hp, forced_status, kill_energy), forged_records
    )
    assert not result.ok, [violation.reason for violation in result.violations]
    assert any(
        violation.reason == "kill_energy_lethal_mutation_lineage_invalid"
        for violation in result.violations
    )

    # 3) An effect-system mutation must carry its executable EffectIR identity.
    missing_effect = Mutation(
        "set",
        ("units", "child", "hp"),
        100.0,
        0.0,
        "forced death without effect identity",
        "effect_system",
        metadata={"effect_source": source_trace},
    )
    record = SettlementRecord(
        "unit_forced_death_hp", "effect_system", missing_effect.stable_id(), False,
        {"unit_id": "child"}, source_trace,
    ).to_json()
    result = auditor.validate_execution((missing_effect,), (record,))
    assert not result.ok, [violation.reason for violation in result.violations]
    assert result.violations


@pytest.mark.integration
def test_tampered_terminal_death_event_is_rejected_without_state_change():
    rules, session, _commands = _enter_with_soldiers()
    dispatcher = session.decisions.scheduler.event_dispatcher
    child_id = sorted(_summoned_monsters(session.state))[0]
    before = session.state.snapshot().to_json()
    lifecycle_mutation_id = "mutation:forged:forced-death"
    forged = GameEvent(
        "unit.defeated",
        source_id="",
        target_id=child_id,
        event_id=mutation_backed_event_id(lifecycle_mutation_id, "unit.defeated"),
        window="unit.defeated",
        process_only=True,
        payload={
            "record_type": "formal_forced_death",
            "target_id": child_id,
            "defeated_unit_id": child_id,
            "param_entity_id": child_id,
            "lifecycle_mutation_id": lifecycle_mutation_id,
            "hp_mutation_id": "mutation:forged:hp",
            "target_before_hp": 100.0,
            "target_after_hp": 0.0,
            "forced_death_kind": "formal_ability_force_kill",
            "effect_id": "effect:forged",
            "source_trace": {},
            "kill_credit_owner_id": "",
        },
    )
    result = dispatcher.dispatch_event(session.state, event=forged)
    assert result.after_state.snapshot().to_json() == before
    assert not result.mutations
    assert any(
        "unit_defeated_state_mismatch" in json.dumps(record.get("payload") or {})
        for record in result.records
    ), result.records

    wrong_window = replace(forged, window="unit.defeated.forged")
    result = dispatcher.dispatch_event(session.state, event=wrong_window)
    assert result.after_state.snapshot().to_json() == before
    assert not result.mutations
    assert any(
        "unit_defeated_window_invalid" in json.dumps(record.get("payload") or {})
        for record in result.records
    ), result.records
