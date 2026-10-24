"""Boundary checks for terminal queue removal and the revive branch.

These are the P2 acceptance counterexamples around one real compiled ForceKill
leaf and typed queue IR: the native producer still audits, stripping every
cleanup label cannot hide a changed retained entry or skip the forced-death
cleanup contract, and an alive_or_revivable entry for a unit still in limbo
blocks with the entry retained and no mutation instead of cancelling.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch

import pytest

from hsr.simulator_v8_clean_core.core.model import PendingDefeatPlan, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.core.state_integrity import CommittedStateIntegrityGate
from hsr.simulator_v8_clean_core.core.unit_state_codec import (
    unit_state_from_payload,
    unit_state_to_payload,
)
from hsr.simulator_v8_clean_core.immutable_json import thaw_json
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.damage import DamageSystem
from hsr.simulator_v8_clean_core.systems.queue import QueueSystem
from hsr.simulator_v8_clean_core.systems.unit_lifecycle import UnitLifecycleSystem
from hsr.simulator_v8_clean_core.tests.test_forced_death_source_audit import (
    _QUEUE,
    _entry,
    _produce,
    _queue_mutation,
)
from hsr.simulator_v8_clean_core.tests.test_kill_energy_shared_producer import (
    _primitive_case,
)
from hsr.simulator_v8_clean_core.tests.test_queue_battle_state_transition import (
    test_drain_starts_and_ends_formal_moment_and_failed_body_publishes_neither
    as _exercise_native_drain,
)


def test_native_forced_death_cleanup_still_audits():
    _effect, rules, result, _state = _produce()
    audit = RuntimeSourceAuditor(rules).validate_execution(
        result.mutations, result.records
    )
    assert audit.ok, [violation.to_json() for violation in audit.violations]


def _stripped_cleanup(result, *, change_after=None):
    """Re-associate one native cleanup after removing every cleanup label."""

    cleanup = _queue_mutation(result)
    metadata = thaw_json(cleanup.metadata)
    metadata.pop("queue_cleanup_operation", None)
    metadata["source_trace"] = {
        key: value
        for key, value in metadata["source_trace"].items()
        if not key.startswith("forced_death_")
    }
    metadata["queue_terminal_plan"]["source_trace"] = metadata["source_trace"]
    after = thaw_json(cleanup.after)
    if change_after is not None:
        change_after(after)
    changed = replace(cleanup, metadata=metadata, after=after)
    records = []
    for original in result.records:
        if original.get("mutation_id") != cleanup.stable_id():
            records.append(original)
            continue
        record = deepcopy(original)
        record["mutation_id"] = changed.stable_id()
        record["trace"] = metadata["source_trace"]
        record["payload"]["queue_terminal_plan"] = metadata["queue_terminal_plan"]
        record["payload"].pop("cleanup_operation", None)
        records.append(record)
    return cleanup, changed, tuple(records)


def test_stripping_cleanup_labels_cannot_hide_a_changed_sibling():
    _effect, rules, result, _state = _produce()
    def change_after(after):
        after[0]["target_ids"] = ["foreign-target"]

    cleanup, tampered, records = _stripped_cleanup(
        result, change_after=change_after
    )
    mutations = tuple(
        tampered if mutation is cleanup else mutation
        for mutation in result.mutations
    )
    audit = RuntimeSourceAuditor(rules).validate_execution(mutations, records)
    assert not audit.ok
    assert any(
        violation.reason == "queue_terminal_remove_not_exact_single_entry_removal"
        for violation in audit.violations
    ), [violation.reason for violation in audit.violations]


def test_stripped_cleanup_labels_cannot_skip_the_forced_death_contract():
    _effect, rules, result, _state = _produce()
    cleanup, changed, records = _stripped_cleanup(result)
    mutations = tuple(
        changed if mutation is cleanup else mutation
        for mutation in result.mutations
    )
    audit = RuntimeSourceAuditor(rules).validate_execution(mutations, records)
    assert not audit.ok
    assert any(
        violation.reason == "queue_cleanup_operation_not_admitted"
        for violation in audit.violations
    ), [violation.reason for violation in audit.violations]


def test_confirmed_defeat_cancellation_keeps_passing_the_shared_boundary():
    _effect, rules, _result, state = _produce(with_queue=False)
    defeated = replace(state.units["child"], lifecycle_status="defeated", hp=0.0)
    for mask in ("alive_only", "alive_or_revivable"):
        entry = dict(_entry("child", f"entry:child:cancel:{mask}"))
        entry["owner_alive_state"] = mask
        entry["target_alive_state"] = mask
        cancelled_state = replace(
            state, units={"child": defeated}, queues={_QUEUE: (entry,)}
        )
        queue = QueueSystem()
        plan = queue.plan_drain(cancelled_state, _QUEUE, None, rules=rules)
        terminal = queue.plan_terminal_resolution(cancelled_state, plan)
        assert (
            terminal.ok
            and terminal.disposition == "cancelled"
            and terminal.retained is False
        ), terminal.to_json()
        result = queue.resolve_terminal(cancelled_state, terminal)
        audit = RuntimeSourceAuditor(rules).validate_execution(
            result.mutations, result.records
        )
        assert audit.ok, [violation.to_json() for violation in audit.violations]


def test_unimplemented_revivable_branch_keeps_the_entry_and_produces_no_mutation():
    _effect, rules, _result, _state = _produce()
    before, packet = _primitive_case()
    before = replace(
        before,
        units={
            unit_id: unit_state_from_payload(unit_state_to_payload(unit))
            for unit_id, unit in before.units.items()
        },
    )
    native = DamageSystem().apply_packet(before, packet)
    assert native.ok, native.errors
    hp = next(m for m in native.mutations if m.path == ("units", "target", "hp"))
    cause = PendingDefeatPlan(
        "target",
        before.event_index,
        hp,
        "owner",
        packet.source_frame.to_json(),
        packet.source_trace,
    )
    lifecycle = UnitLifecycleSystem()
    state = MutationReducer().apply_all(
        before, (hp, *lifecycle.begin_limbo_mutations(before, cause))
    )
    assert CommittedStateIntegrityGate().check_full(state).ok
    assert lifecycle.pending_defeat(state, "target") == cause
    entry = _entry("target", "entry:target")
    state = replace(state, queues={_QUEUE: (entry,)})
    queue = QueueSystem()
    plan = queue.plan_drain(state, _QUEUE, None, rules=rules)
    assert "revivable_branch_not_admitted" in plan.blocked_reason
    terminal = queue.plan_terminal_resolution(state, plan)
    result = queue.resolve_terminal(state, terminal)
    assert not terminal.ok and terminal.retained and not result.mutations, (
        terminal.to_json()
    )


def test_joint_operation_and_disposition_rewrite_cannot_hide_a_changed_sibling():
    _effect, rules, result, _state = _produce()
    cleanup = _queue_mutation(result)
    cleanup_record = next(
        record
        for record in result.records
        if record.get("mutation_id") == cleanup.stable_id()
    )
    metadata = thaw_json(cleanup.metadata)
    metadata.pop("queue_cleanup_operation", None)
    metadata["queue_operation"] = "renamed_terminal_write"
    metadata["source_trace"] = {
        key: value
        for key, value in metadata["source_trace"].items()
        if not key.startswith("forced_death_")
    }
    terminal_plan = thaw_json(metadata["queue_terminal_plan"])
    terminal_plan.update(
        {"disposition": "waiting_window", "retained": True, "monotonic_progress": True}
    )
    terminal_plan["source_trace"] = metadata["source_trace"]
    metadata["queue_terminal_plan"] = terminal_plan
    after = thaw_json(cleanup.after)
    after[0]["target_ids"] = ["foreign-target"]
    changed = replace(cleanup, metadata=metadata, after=after)
    record = deepcopy(cleanup_record)
    record["mutation_id"] = changed.stable_id()
    record["trace"] = metadata["source_trace"]
    record["payload"]["queue_terminal_plan"] = terminal_plan
    record["payload"].pop("cleanup_operation", None)
    records = tuple(
        record if item is cleanup_record else item for item in result.records
    )
    mutations = tuple(
        changed if mutation is cleanup else mutation
        for mutation in result.mutations
    )
    audit = RuntimeSourceAuditor(rules).validate_execution(mutations, records)
    assert not audit.ok
    assert any(
        violation.reason == "queue_terminal_remove_not_exact_single_entry_removal"
        for violation in audit.violations
    ), [violation.reason for violation in audit.violations]


def test_waiting_window_and_retargeted_transitions_keep_auditing():
    _effect, rules, _result, state = _produce(with_queue=False)
    defeated = replace(state.units["child"], lifecycle_status="defeated", hp=0.0)
    other = UnitState("other", "enemy", "monster:1002040", hp=100.0, max_hp=100.0)
    base_state = replace(state, units={"child": defeated, "other": other})
    queue = QueueSystem()
    for name, cancel_policy, expected in (
        (
            "wait",
            {"wait_policy_admitted": True, "wait_for_windows": ["turn"]},
            "waiting_window",
        ),
        (
            "retarget",
            {"retarget_policy_admitted": True, "retarget_target_ids": ["other"]},
            "retargeted",
        ),
    ):
        entry = dict(_entry("other", f"entry:{name}"))
        entry["target_ids"] = ["child"]
        entry["cancel_policy"] = cancel_policy
        transition_state = replace(base_state, queues={_QUEUE: (entry,)})
        plan = queue.plan_drain(transition_state, _QUEUE, None, rules=rules)
        terminal = queue.plan_terminal_resolution(transition_state, plan)
        assert terminal.disposition == expected and terminal.retained, (
            terminal.to_json()
        )
        result = queue.resolve_terminal(transition_state, terminal)
        audit = RuntimeSourceAuditor(rules).validate_execution(
            result.mutations, result.records
        )
        assert audit.ok, [violation.to_json() for violation in audit.violations]



def test_dead_owner_still_cancels_when_an_admitted_target_is_limbo():
    _effect, rules, death, original = _produce(with_queue=False)
    rules = RuleBook(
        replace(
            rules.ir,
            queue_intents=tuple(
                replace(intent, target_alive_state="alive_or_limbo")
                for intent in rules.ir.queue_intents
            ),
        )
    )
    dead = MutationReducer().apply_all(original, death.mutations).units["child"]
    before, packet = _primitive_case()
    before = replace(
        before,
        units={
            unit_id: unit_state_from_payload(unit_state_to_payload(unit))
            for unit_id, unit in before.units.items()
        },
    )
    damage = DamageSystem().apply_packet(before, packet)
    assert damage.ok, damage.errors
    hp = next(
        mutation
        for mutation in damage.mutations
        if mutation.path == ("units", "target", "hp")
    )
    cause = PendingDefeatPlan(
        "target",
        before.event_index,
        hp,
        "owner",
        packet.source_frame.to_json(),
        packet.source_trace,
    )
    lifecycle = UnitLifecycleSystem()
    state = MutationReducer().apply_all(
        before, (hp, *lifecycle.begin_limbo_mutations(before, cause))
    )
    state = replace(state, units={**state.units, "child": dead})
    assert CommittedStateIntegrityGate().check_full(state).ok
    entry = _entry("child", "entry:dead-owner")
    entry["target_ids"] = ["target"]
    entry["target_alive_state"] = "alive_or_limbo"
    state = replace(state, queues={_QUEUE: (entry,)})
    queue = QueueSystem()
    plan = queue.plan_drain(state, _QUEUE, None, rules=rules)
    assert plan.blocked_reason == "queue_owner_revivable_branch_not_admitted:child"
    terminal = queue.plan_terminal_resolution(state, plan)
    assert terminal.ok and terminal.disposition == "cancelled", terminal.to_json()


def test_removal_cannot_rename_its_settlement_to_lose_forcekill_causality():
    _effect, rules, result, _state = _produce()
    cleanup, changed, records = _stripped_cleanup(result)
    metadata = thaw_json(changed.metadata)
    metadata["queue_operation"] = "renamed_terminal_write"
    renamed = replace(changed, metadata=metadata)
    reassociated = []
    for original in records:
        record = deepcopy(original)
        if record.get("mutation_id") == changed.stable_id():
            record["mutation_id"] = renamed.stable_id()
            record["record_type"] = "unrelated_queue_write"
        reassociated.append(record)
    mutations = tuple(
        renamed if mutation is cleanup else mutation
        for mutation in result.mutations
    )
    audit = RuntimeSourceAuditor(rules).validate_execution(
        mutations, tuple(reassociated)
    )
    reasons = {violation.reason for violation in audit.violations}
    assert not audit.ok
    assert "queue_removal_settlement_producer_mismatch" in reasons, reasons
    assert "queue_cleanup_operation_not_admitted" in reasons, reasons


def test_waiting_transition_cannot_rewrite_the_updated_entry_actor():
    _effect, rules, death, original = _produce(with_queue=False)
    state = MutationReducer().apply_all(original, death.mutations)
    dead = state.units["child"]
    other = replace(original.units["child"], unit_id="other")
    entry = _entry("other", "entry:waiting")
    entry["target_ids"] = ["child"]
    entry["cancel_policy"] = {"wait_policy_admitted": True, "wait_for_windows": ["turn"]}
    foreign = replace(other, unit_id="foreign-actor")
    state = replace(
        state,
        units={"child": dead, "other": other, "foreign-actor": foreign},
        queues={_QUEUE: (entry,)},
    )
    queue = QueueSystem()
    drain = queue.plan_drain(state, _QUEUE, None, rules=rules)
    terminal = queue.plan_terminal_resolution(state, drain)
    assert terminal.disposition == "waiting_window"
    result = queue.resolve_terminal(state, terminal)
    assert (
        RuntimeSourceAuditor(rules).validate_execution(result.mutations, result.records).ok
    )
    mutation = result.mutations[0]
    after = thaw_json(mutation.after)
    after[0]["actor_id"] = "foreign-actor"
    changed = replace(mutation, after=after)
    after_state = MutationReducer().apply_all(state, (changed,))
    assert CommittedStateIntegrityGate().check_full(after_state).ok
    records = deepcopy(result.records)
    for record in records:
        record["mutation_id"] = changed.stable_id()
    audit = RuntimeSourceAuditor(rules).validate_execution((changed,), records)
    assert not audit.ok
    assert any(
        violation.reason == "queue_terminal_transition_entry_mismatch"
        for violation in audit.violations
    ), [violation.reason for violation in audit.violations]



@pytest.mark.parametrize(
    "drain_plan",
    (
        None,
        {},
        {"ok": False, "queue_name": "foreign", "queue_entry": {"entry_id": "foreign"}},
    ),
)
def test_invalid_drain_claim_cannot_exempt_forcekill_cleanup(drain_plan):
    _effect, rules, result, _state = _produce()
    cleanup, stripped, records = _stripped_cleanup(result)
    metadata = thaw_json(stripped.metadata)
    metadata["queue_operation"] = "renamed_terminal_write"
    if drain_plan is not None:
        metadata["drain_plan"] = drain_plan
    changed = replace(stripped, metadata=metadata)
    reassociated = []
    for original in records:
        record = deepcopy(original)
        if record.get("mutation_id") == stripped.stable_id():
            record["mutation_id"] = changed.stable_id()
            record["record_type"] = "queue_dequeue"
            record["payload"] = {
                "drain_plan": drain_plan,
                "queue_resolution": {},
                "queue_window_plan": metadata.get("queue_window_plan"),
                "external_command": {},
            }
        reassociated.append(record)
    mutations = tuple(
        changed if mutation is cleanup else mutation
        for mutation in result.mutations
    )
    audit = RuntimeSourceAuditor(rules).validate_execution(
        mutations, tuple(reassociated)
    )
    reasons = {violation.reason for violation in audit.violations}
    assert not audit.ok, "an absent/blocked/foreign drain exempted the cleanup"
    assert "queue_removal_settlement_producer_mismatch" in reasons, reasons
    assert "queue_cleanup_operation_not_admitted" in reasons, reasons



@pytest.fixture(scope="module")
def native_dequeue_settlement():
    """Capture one real scheduler dequeue settlement that already audits."""

    captured = []
    original = RuntimeSourceAuditor.validate_execution

    def observe(self, mutations, records):
        result = original(self, mutations, records)
        if result.ok and any(
            record.get("record_type") == "queue_dequeue" for record in records
        ):
            captured.append((self.rules, mutations, records))
        return result

    with patch.object(RuntimeSourceAuditor, "validate_execution", observe):
        _exercise_native_drain()
    assert captured
    return captured[0]


@pytest.mark.parametrize("change", ("empty", "wrong_id", "foreign_tasks"))
def test_native_dequeue_record_must_match_formal_resolution(
    native_dequeue_settlement, change
):
    rules, mutations, records = native_dequeue_settlement
    modified = deepcopy(records)
    record = next(
        item for item in modified if item.get("record_type") == "queue_dequeue"
    )
    resolution = record["payload"]["queue_resolution"]
    if change == "empty":
        record["payload"]["queue_resolution"] = {}
    elif change == "wrong_id":
        resolution["queue_resolution_id"] = "foreign-resolution"
    else:
        resolution["resolved_ids"]["executable_task_ids"] = ["foreign-task"]
    audit = RuntimeSourceAuditor(rules).validate_execution(mutations, modified)
    assert not audit.ok
    assert any(
        violation.reason == "queue_removal_settlement_producer_mismatch"
        for violation in audit.violations
    ), [violation.reason for violation in audit.violations]
