"""Automatic insert-action closure: queue tag facts, cleanup and rollback.

Unit checks stay synthetic. The integration checks share one formal rule build
and one public eight-step prelude: the success route owns that session history
and its ninth submission, while the cancel and late-failure branches only read
the saved prelude state.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest import mock

import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.rules.condition_state import TransientConditionOperandRequest
from hsr.simulator_v8_clean_core.rules.ir import ActionDefinitionIR, IRSource, QueueIntentIR
from hsr.simulator_v8_clean_core.systems.action_preflight import (
    action_resource_blocked_reason,
    action_resource_plan,
)
from hsr.simulator_v8_clean_core.systems.queue import QueueEntry, QueueSystem
from hsr.simulator_v8_clean_core.systems.resource import ResourcePlan, ResourceSystem
from hsr.simulator_v8_clean_core.systems.scheduler import CombatScheduler
from hsr.simulator_v8_clean_core.systems.skill_properties import (
    effective_action_property,
    resolve_skill_property_overrides,
    skill_property_override_plan,
)
from hsr.simulator_v8_clean_core.systems.status_callbacks import (
    QueueEventConditionProvider,
    _INSERT_ACTION_LEGAL_CANCEL_REASONS,
    _queue_insert_precheck_blocked,
)
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CORE_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLES = _CORE_ROOT / "examples" / "cli"
_SCENARIO = _EXAMPLES / "seele_automatic_insert_natural.json"
_COMMANDS = _EXAMPLES / "seele_automatic_insert_natural.commands.json"
_INSERT_ACTION = "avatar_skill:1110202"
_MUTE = "modifier:MAvatar_Advanced_Seele_00_Skill02InsertMuteSp"
_CLEAN = "modifier:MAvatar_Advanced_Seele_00_Skill02InsertMuteSp_Clean"
_CHECK = "modifier:MAvatar_Advanced_Seele_00_Skill02InsertCheck"
_READY = "modifier:MAvatar_Advanced_Seele_00_Skill02InsertReady_ShowBuff"
_CD = "modifier:MAvatar_Advanced_Seele_00_Skill02InsertCD_ShowBuff"
_TAG = "Advanced_Seele_00_Skill02InsertCheck"


def _fixture_state() -> BattleState:
    return BattleState(
        units={
            "seele": UnitState("seele", "ally", "avatar:1102", hp=100.0, max_hp=100.0),
            "enemy": UnitState("enemy", "enemy", "monster:8011020", hp=100.0, max_hp=100.0),
        },
        skill_points=5,
        max_skill_points=5,
        queues={"turn_insert_action": ()},
    )


def _enqueue(queue: QueueSystem, state: BattleState, tag: str = _TAG):
    entry = QueueEntry(
        "queue_entry:probe:1",
        "turn_insert_action",
        "turn_insert_action",
        "queue_intent:probe:1",
        "seele",
        "skill_type:ControlSkill02",
        ("enemy",),
        {"priority_ordering_admitted": True, "priority_value": 0.0},
        {"fixture": "automatic_insert"},
        queue_window_id="queue_window:probe:1",
        window_family="insert_action",
        target_resolution={"ok": True, "target_ids": ["enemy"]},
        custom_tag=tag,
    )
    mutation = queue.enqueue(state, "turn_insert_action", entry, source="queue_system")
    after = MutationReducer().apply_all(state, (mutation,))
    return entry, mutation, after


def _request(invocation_id: str, window: str) -> TransientConditionOperandRequest:
    return TransientConditionOperandRequest(
        fact_kind="event.param_string",
        invocation_id=invocation_id,
        window=window,
    )


def test_queue_start_tag_fact_is_typed_and_dispatch_scoped() -> None:
    queue = QueueSystem()
    state = _fixture_state()
    entry, enqueue, queued = _enqueue(queue, state)
    dequeue = queue.dequeue_entry(
        queued, "turn_insert_action", entry.entry_id, source="queue_system"
    )
    after = MutationReducer().apply_all(queued, (dequeue,))
    event = queue.action_start_event(after, dequeue)
    invocation_id, window = "status_callback:probe", "task_graph_node:probe"
    provider = QueueEventConditionProvider(
        after, invocation_id, window, event, "seele", event.queue_action_start_fact,
    )

    resolved = provider.resolve_transient(_request(invocation_id, window))
    assert resolved.status == "resolved" and resolved.value == _TAG
    assert resolved.source_identity.startswith("queue_event:queue.action.before:")

    # An earlier listener of the same atomic dispatch may already have mutated
    # the state; the typed fact stays valid for the entry it removed.
    derived = replace(after, skill_points=4)
    assert provider.resolve_transient(_request(invocation_id, window)).value == _TAG

    # Stale or foreign identity is rejected.
    stale = replace(after, event_index=after.event_index + 1)
    stale_provider = QueueEventConditionProvider(
        stale, invocation_id, window, event, "seele", event.queue_action_start_fact,
    )
    stale_result = stale_provider.resolve_transient(_request(invocation_id, window))
    assert stale_result.status == "blocked"
    assert stale_result.blocked_reason == "queue_event_param_string_fact_missing_or_mismatched"

    wrong_window = provider.resolve_transient(
        _request(invocation_id, "task_graph_node:other")
    )
    assert wrong_window.status == "blocked"
    assert wrong_window.blocked_reason == "queue_event_param_string_identity_mismatch"

    # A plain payload string is never accepted as the tag fact.
    forged = GameEvent(
        "queue.action.before",
        source_id="seele",
        event_id="event:forged:queue",
        window="queue",
        process_only=True,
        payload={"queue_entry": entry.to_json(), "param_string": _TAG},
    )
    forged_provider = QueueEventConditionProvider(
        after, invocation_id, window, forged, "seele", None,
    )
    forged_result = forged_provider.resolve_transient(_request(invocation_id, window))
    assert forged_result.status == "blocked"
    assert forged_result.blocked_reason == "queue_event_param_string_fact_missing_or_mismatched"

    # Tag/actor scope belongs to the entry and its producer.
    other_actor = QueueEventConditionProvider(
        after, invocation_id, window, event, "natasha", event.queue_action_start_fact,
    )
    actor_result = other_actor.resolve_transient(_request(invocation_id, window))
    assert actor_result.status == "blocked"
    assert actor_result.blocked_reason == "queue_event_param_string_actor_scope_mismatch"

    # The strict producer identity stays stricter than the dispatch-scoped one.
    fact = event.queue_action_start_fact
    assert fact.matches(after, event)
    assert not fact.matches(derived, event)


def test_queue_terminal_tag_fact_covers_finish_conditions() -> None:
    queue = QueueSystem()
    state = _fixture_state()
    entry, mutation, after = _enqueue(queue, state)
    dequeue = queue.dequeue_entry(
        after, "turn_insert_action", entry.entry_id, source="queue_system"
    )
    after_dequeue = MutationReducer().apply_all(after, (dequeue,))
    event = queue.action_terminal_event(after_dequeue, dequeue)
    invocation_id, window = "status_callback:finish", "task_graph_node:finish"
    fact = event.queue_action_terminal_fact
    provider = QueueEventConditionProvider(
        after_dequeue, invocation_id, window, event, "seele", fact,
    )
    resolved = provider.resolve_transient(_request(invocation_id, window))
    assert resolved.status == "resolved" and resolved.value == _TAG

    # An entry without a tag has a real but empty tag fact; the condition is
    # implementation-blocked instead of being compared against a guess.
    plain_state = _fixture_state()
    plain_entry, plain_mutation, plain_after = _enqueue(queue, plain_state, tag="")
    plain_dequeue = queue.dequeue_entry(
        plain_after, "turn_insert_action", plain_entry.entry_id, source="queue_system"
    )
    plain_after_dequeue = MutationReducer().apply_all(plain_after, (plain_dequeue,))
    plain_event = queue.action_terminal_event(plain_after_dequeue, plain_dequeue)
    plain_provider = QueueEventConditionProvider(
        plain_after_dequeue, invocation_id, window, plain_event, "seele",
        plain_event.queue_action_terminal_fact,
    )
    missing = plain_provider.resolve_transient(_request(invocation_id, window))
    assert missing.status == "blocked"
    assert missing.blocked_reason == "queue_event_param_string_custom_tag_fact_missing"


def test_skill_property_overrides_are_status_instance_scoped() -> None:
    def unit_with(overrides: list[dict], lifecycle: str = "active") -> UnitState:
        return UnitState(
            "seele", "ally", "avatar:1102", hp=100.0, max_hp=100.0,
            statuses=("modifier:insert",),
            flags={"status_details": [{
                "instance_id": "status:insert:1",
                "modifier_name": "insert",
                "status_id": "modifier:insert",
                "owner_id": "seele",
                "caster_id": "seele",
                "lifecycle_state": lifecycle,
                "skill_property_overrides": overrides,
            }]},
        )

    override = {
        "property_type": "SPBase",
        "skill_types": ["Skill"],
        "value": 0.0,
        "value_source": "absent_value_muted_to_zero",
        "status_instance_id": "status:insert:1",
    }
    active = BattleState(units={"seele": unit_with([override])})
    resolved = resolve_skill_property_overrides(active, "seele", "Skill")
    assert resolved.ok and resolved.values == {"SPBase": 0.0}
    assert skill_property_override_plan(None, resolved.values) == {"sp_base": 0.0}
    # The property belongs to the declared skill type only.
    assert resolve_skill_property_overrides(active, "seele", "Normal").values == {}

    # Removing the owning status instance retires the override without a
    # residual manual-skill mutation.
    removed = BattleState(units={"seele": unit_with([override], lifecycle="removed")})
    assert resolve_skill_property_overrides(removed, "seele", "Skill").values == {}

    conflict = BattleState(units={"seele": unit_with([
        override,
        {**override, "value": 5.0, "status_instance_id": "status:insert:2"},
    ])})
    blocked = resolve_skill_property_overrides(conflict, "seele", "Skill")
    assert not blocked.ok
    assert blocked.blocked_reason.startswith("skill_property_override_conflict")


@pytest.fixture(scope="module")
def preparation_counts():
    """Count the production preparations this module actually performs."""
    from hsr.simulator_v8_clean_core import session as session_module

    counts = {"rulebook_builds": 0, "sessions": 0, "fingerprint_calls": 0}
    original_build = build_battle_rulebook
    original_init = session_module.BattleSession.__init__
    original_fingerprint = session_module.rulebook_fingerprint

    def counting_build(*args, **kwargs):
        counts["rulebook_builds"] += 1
        return original_build(*args, **kwargs)

    def counting_init(session, *args, **kwargs):
        counts["sessions"] += 1
        return original_init(session, *args, **kwargs)

    def counting_fingerprint(*args, **kwargs):
        counts["fingerprint_calls"] += 1
        return original_fingerprint(*args, **kwargs)

    with mock.patch.dict(globals(), {"build_battle_rulebook": counting_build}), \
            mock.patch.object(
                session_module.BattleSession, "__init__", counting_init), \
            mock.patch.object(
                session_module, "rulebook_fingerprint", counting_fingerprint):
        yield counts
    assert counts == {
        "rulebook_builds": 1, "sessions": 1, "fingerprint_calls": 0,
    }, counts


def _open_session(rules, scenario):
    from hsr.simulator_v8_clean_core.session import BattleSession

    return BattleSession(rules, scenario, diagnostics="full")


def _submit_public_prefix(session, commands, count):
    from hsr.simulator_v8_clean_core.session import command_from_json

    for index, command in enumerate(commands[:count]):
        decision = session.advance()
        assert decision.ready, (index, decision.blocked_reason)
        result = session.submit(command_from_json(command))
        assert result.transition.outcome.successor_eligible, (
            index, result.transition.outcome.reason_codes,
        )


@pytest.fixture(scope="module")
def natural_route(preparation_counts) -> dict:
    """Build the formal rules and run the shared eight-step prelude once."""
    scenario = json.loads(_SCENARIO.read_text(encoding="utf-8"))
    commands = json.loads(_COMMANDS.read_text(encoding="utf-8"))["commands"]
    rules = build_battle_rulebook(_REPO_ROOT / "turnbasedgamedata-main", scenario)
    session = _open_session(rules, scenario)
    _submit_public_prefix(session, commands, 8)
    return {
        "scenario": scenario,
        "commands": commands,
        "rules": rules,
        "session": session,
        # Branches that must not advance the success history read this saved
        # prelude state instead of the session's later state.
        "pending": session.state,
        "counts": preparation_counts,
    }


@pytest.mark.integration
def test_natural_insert_route_executes_body_and_cleanup(natural_route) -> None:
    rules = natural_route["rules"]
    # The success route owns the shared session and keeps its history.
    session = natural_route["session"]
    pending = natural_route["pending"]
    assert session.state is pending
    queued = pending.queues.get("turn_insert_action", ())
    assert len(queued) == 1
    entry = queued[0]
    assert entry["custom_tag"] == _TAG
    assert entry["insert_abort"]["callback_id"].endswith("OnListenAfterAttack")
    assert entry["insert_abort"]["child_formal_task_ids"]
    skill_points_before = pending.skill_points

    scheduler = session.decisions.scheduler
    step = scheduler._try_queue_drain(pending)
    assert step is not None
    transition = step.transition
    assert transition.outcome.successor_eligible, transition.outcome.reason_codes

    # Every mutation of the automatic insert consumption remains traceable to
    # its executable source IR, including the skill-property start callback.
    audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    assert audit.ok, [violation.to_json() for violation in audit.violations]

    events = transition.transaction.events
    event_types = [event.event_type for event in events]
    assert "queue.action.before" in event_types
    assert any(
        event.event_type == "action.requested"
        and event.payload.get("action_id") == _INSERT_ACTION
        for event in events
    )
    assert "queue.action.after" in event_types
    assert "queue.action.abort" not in event_types
    # The accepted insert identity reaches the body command: all action window
    # events derived from it report is_insert_action=True.
    window_events = [
        event for event in events if event.event_type.startswith("action.window.")
    ]
    assert window_events
    assert all(event.payload.get("is_insert_action") is True for event in window_events)
    # The insert body acted on its own accepted target and produced damage.
    assert any(
        event.event_type == "damage.hit"
        and event.target_id == "enemy:stage:400020800:wave:0:pos:0"
        for event in events
    )
    before = transition.transaction.before.to_json(detach=False)
    after = transition.after.to_json(detach=False)
    assert after["queues"].get("turn_insert_action", []) == []
    # IgnoreBPDec keeps the skill point ledger unchanged; the start callback's
    # SPBase mute keeps the insert body from granting action energy. Kill
    # energy is a separate shared producer and may still fire.
    assert after["skill_points"] == before["skill_points"]
    energy_mutations = [
        mutation for mutation in transition.transaction.mutations
        if mutation.path == ("units", "seele", "energy")
    ]
    action_energy_mutations = [
        mutation for mutation in energy_mutations
        if mutation.metadata.get("resource_operation") != "kill_energy_gain"
    ]
    assert not action_energy_mutations, [
        mutation.to_json(detach=False) for mutation in action_energy_mutations
    ]
    kill_energy = sum(
        float(mutation.after) - float(mutation.before)
        for mutation in energy_mutations
        if mutation.metadata.get("resource_operation") == "kill_energy_gain"
    )
    assert after["units"]["seele"]["energy"] == (
        before["units"]["seele"]["energy"] + kill_energy
    )

    # The insert body used the acting unit's effective action level, not the
    # compiled action-set default level.
    expected_level = pending.units["seele"].flags[
        "effective_skill_levels_by_action_id"
    ][_INSERT_ACTION]
    requested = [
        event for event in events
        if event.event_type == "action.requested"
        and event.payload.get("action_id") == _INSERT_ACTION
    ]
    assert requested and requested[0].payload["action_level"] == expected_level

    session._accept(step)
    # Advancing the success history must not touch the prelude state other
    # branches read.
    assert session.state is not pending
    assert natural_route["pending"] is pending
    assert len(pending.queues.get("turn_insert_action", ())) == 1
    statuses = session.state.units["seele"].statuses
    assert _MUTE not in statuses
    assert _CLEAN not in statuses
    assert _CHECK not in statuses
    assert _READY not in statuses
    assert _CD in statuses
    assert session.state.queues.get("turn_insert_action", ()) == ()
    assert session.state.skill_points == skill_points_before
    decision = session.advance()
    assert decision.ready, decision.blocked_reason
    # The ninth public command is accepted after the automatic insert action.
    from hsr.simulator_v8_clean_core.session import command_from_json

    follow_up = session.submit(command_from_json(natural_route["commands"][8]))
    assert follow_up.transition.outcome.successor_eligible, (
        follow_up.transition.outcome.reason_codes,
    )
    assert any(
        event.event_type == "action.requested"
        and event.payload.get("action_id") == "avatar_skill:110502"
        for event in follow_up.transition.transaction.events
    )
    assert session.state.skill_points == skill_points_before - 1


@pytest.mark.integration
def test_shared_preparation_and_formal_fingerprint_reuse(natural_route) -> None:
    # One formal rule build, one session and one eight-step prelude serve every
    # integration branch. The session reuses the builder's formal rule identity
    # instead of hashing the same IR a second time.
    assert natural_route["counts"] == {
        "rulebook_builds": 1, "sessions": 1, "fingerprint_calls": 0,
    }
    session = natural_route["session"]
    manifest = session.build.build_manifest
    assert manifest is not None
    assert session.rules_fingerprint == manifest.rule_identity.rules_fingerprint
    assert len(natural_route["pending"].queues.get("turn_insert_action", ())) == 1


@pytest.mark.integration
def test_insert_action_cancel_before_start_runs_abort_branch(natural_route) -> None:
    from hsr.simulator_v8_clean_core.systems.dynamic_values import find_status_detail
    from hsr.simulator_v8_clean_core.systems.effect import EffectRegistry
    from hsr.simulator_v8_clean_core.systems.status import StatusSystem
    from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem
    from hsr.simulator_v8_clean_core.rules.task_graph import TaskGraphNodeIR

    rules = natural_route["rules"]
    # The cancel branch reads the saved prelude state, never the advanced
    # success session, and keeps its own scheduler and candidate state.
    state = natural_route["pending"]
    queued = state.queues.get("turn_insert_action", ())
    assert len(queued) == 1
    entry = queued[0]
    binding = entry["insert_abort"]
    assert binding and binding["child_formal_task_ids"]
    callback = rules.status_callback(binding["callback_id"])
    node = rules.query_task_graph_node(binding["graph_node_id"]).value
    assert isinstance(node, TaskGraphNodeIR) and node.opcode == "TurnInsertAction"
    detail = find_status_detail(state, "seele", modifier_name=binding["modifier_name"])
    assert detail is not None and detail["instance_id"] == binding["status_instance_id"]
    task = rules.status_callback_task(node.formal_task_id)
    assert task is not None and task.opcode == "TurnInsertAction"

    system = StatusCallbackSystem(rules, effect_registry=EffectRegistry(StatusSystem(rules)))
    # Without a pending same-tag entry the source PreCheck passes and the leaf
    # stays on the normal enqueue path.
    no_pending = replace(state, queues={"turn_insert_action": ()})
    assert system._insert_action_cancel_leaf(no_pending, callback, task, detail) is None
    # With a pending same-tag entry the formal PreCheck cancels before start.
    leaf = system._insert_action_cancel_leaf(state, callback, task, detail)
    assert leaf is not None and leaf.status == "resolved"
    assert leaf.outcome_kind == "insert_abort"
    assert leaf.settlement_records[0].record_type == "insert_action_cancelled_before_start"

    # The delayed abort branch then runs the source cleanup tasks: the used
    # marker is installed, the mute status is removed, and no queue entry is
    # added or consumed.
    abort = system.execute_insert_abort(state, binding=binding, trigger_event=None)
    assert abort.ok, abort.errors
    statuses = abort.after_state.units["seele"].statuses
    assert _CHECK in statuses
    assert _MUTE not in statuses
    assert abort.after_state.queues.get("turn_insert_action", ()) == queued


@pytest.mark.integration
def test_late_queue_finish_failure_rolls_back_consumption(natural_route, monkeypatch) -> None:
    rules = natural_route["rules"]
    # The late-failure branch reads the saved prelude state, never the advanced
    # success session, and keeps its own scheduler and failed dispatch hook.
    before = natural_route["pending"]
    assert len(before.queues.get("turn_insert_action", ())) == 1
    scheduler = CombatScheduler(rules)
    original = scheduler.event_dispatcher.dispatch_event

    def fail_finish(state, *, event, **kwargs):
        if event.event_type == "queue.action.after":
            from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchResult

            return EventDispatchResult(after_state=state, errors=("late_finish_failure",))
        return original(state, event=event, **kwargs)

    monkeypatch.setattr(scheduler.event_dispatcher, "dispatch_event", fail_finish)
    step = scheduler._try_queue_drain(before)
    assert step is not None
    assert not step.transition.outcome.successor_eligible
    assert step.transition.outcome.reason_codes
    # Nothing of this consumption leaked: the entry stays queued and the state
    # object is the pre-drain one.
    assert step.after_state is before
    assert len(step.after_state.queues.get("turn_insert_action", ())) == 1
    assert step.transition.transaction.mutations == ()


def _fixture_definition(**overrides) -> ActionDefinitionIR:
    values = {
        "definition_id": "action_def:fixture:1",
        "action_id": "fixture",
        "level": 1,
        "attack_type": "BPSkill",
        "skill_effect": "SingleAttack",
        "target_mode": "single",
        "bp_need": 1.0,
        "bp_add": 0.0,
        "sp_base": 30.0,
        "sp_multiple_ratio": 1.0,
        "param_list": (),
        "show_stance_list": (),
        "show_damage_list": (),
        "stance_damage_type": "Quantum",
        "source": IRSource("synthetic:action", "validation", "fixture", {}),
        "coverage_status": "executable",
    }
    values.update(overrides)
    return ActionDefinitionIR(**values)


def _unit_with_overrides(overrides: list[dict], skill_types: list[str]) -> UnitState:
    return UnitState(
        "seele", "ally", "avatar:1102", hp=100.0, max_hp=100.0,
        statuses=("modifier:insert",),
        flags={"status_details": [{
            "instance_id": "status:insert:1",
            "modifier_name": "insert",
            "status_id": "modifier:insert",
            "owner_id": "seele",
            "caster_id": "seele",
            "lifecycle_state": "active",
            "skill_property_overrides": [
                {
                    "property_type": property_type,
                    "skill_types": skill_types,
                    "value": value,
                    "status_instance_id": "status:insert:1",
                }
                for property_type, value in overrides
            ],
        }]},
    )


def _precheck_intent(max_count_expr: dict) -> QueueIntentIR:
    return QueueIntentIR(
        queue_intent_id="queue_intent:probe:precheck",
        source_task_id="probe:task",
        callback_id="probe:callback",
        phase_id="",
        opcode="TurnInsertAction",
        queue_kind="turn_insert_action",
        priority_source={"priority_ordering_admitted": True, "priority_value": 0.0},
        actor_target_alias="ModifierOwnerEntity",
        action_ref_or_ability_name="skill_type:ControlSkill02",
        skill_index_expr={"kind": "skill_type", "value": "ControlSkill02", "supported": True},
        ability_target_alias="ParamEntity",
        auto_cast=True,
        abort_policy={
            "insert_once_policy": {
                "kind": "same_tag_insert_unused_count",
                "custom_tag": _TAG,
                "max_count_expr": max_count_expr,
            },
        },
        source=IRSource(
            "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json",
            "Modifiers",
            "probe",
            {},
        ),
    )


def test_unresolved_insert_precheck_is_not_a_legal_cancel() -> None:
    state = BattleState(
        units={},
        queues={"turn_insert_action": ({"custom_tag": _TAG, "status": "pending"},)},
    )
    unresolved = _queue_insert_precheck_blocked(
        state, _precheck_intent({"kind": "missing", "supported": False})
    )
    assert unresolved == "queue_insert_precheck_max_count_unresolved"
    assert unresolved not in _INSERT_ACTION_LEGAL_CANCEL_REASONS
    legal = _queue_insert_precheck_blocked(
        state, _precheck_intent({"kind": "fixed", "value": 1.0, "supported": True})
    )
    assert legal == "queue_insert_precheck_same_tag_pending"
    assert legal in _INSERT_ACTION_LEGAL_CANCEL_REASONS


def test_skill_property_override_drives_resource_gates() -> None:
    definition = _fixture_definition()
    bp_state = BattleState(
        units={"seele": _unit_with_overrides([("BPNeed", 0.0)], ["Skill"])},
        skill_points=0,
        max_skill_points=5,
    )
    value, blocked = effective_action_property(
        bp_state, "seele", definition, "BPNeed", definition.bp_need
    )
    assert (value, blocked) == (0.0, "")
    plan = action_resource_plan(
        definition, source="probe", state=bp_state, actor_id="seele"
    )
    assert plan.skill_point_delta == 0 and not plan.blocked_reason
    assert ResourceSystem().plan_action_resources(bp_state, "seele", plan).ok

    sp_state = BattleState(
        units={"seele": _unit_with_overrides([("SPBase", 0.0)], ["Skill"])},
        skill_points=5,
    )
    sp_plan = action_resource_plan(
        definition, source="probe", state=sp_state, actor_id="seele"
    )
    assert sp_plan.energy_gain == 0.0
    assert effective_action_property(
        sp_state, "seele", definition, "SPBase", definition.sp_base
    )[0] == 0.0


def test_conflicting_skill_property_override_blocks_resource_admission() -> None:
    definition = _fixture_definition()
    unit = _unit_with_overrides([("SPBase", 0.0)], ["Skill"])
    conflict_unit = replace(
        unit,
        flags={"status_details": [
            *unit.flags["status_details"],
            {
                "instance_id": "status:insert:2",
                "modifier_name": "insert",
                "status_id": "modifier:insert",
                "owner_id": "seele",
                "caster_id": "seele",
                "lifecycle_state": "active",
                "skill_property_overrides": [{
                    "property_type": "SPBase",
                    "skill_types": ["Skill"],
                    "value": 5.0,
                    "status_instance_id": "status:insert:2",
                }],
            },
        ]},
    )
    state = BattleState(units={"seele": conflict_unit}, skill_points=5)
    plan = action_resource_plan(
        definition, source="probe", state=state, actor_id="seele"
    )
    assert plan.blocked_reason.startswith(
        "resource_skill_property_override_blocked:skill_property_override_conflict:SPBase"
    )
    result = ResourceSystem().plan_action_resources(state, "seele", plan)
    assert not result.ok and result.mutations == ()
    assert action_resource_blocked_reason(result.errors) == plan.blocked_reason
    assert plan.metadata["skill_property_override_blocked_reason"].startswith(
        "skill_property_override_conflict"
    )

    explicit = ResourcePlan(blocked_reason="probe_blocked")
    blocked = ResourceSystem().plan_action_resources(state, "seele", explicit)
    assert not blocked.ok and blocked.errors == ("probe_blocked",)


def test_action_sp_base_formula_reads_effective_override() -> None:
    from hsr.simulator_v8_clean_core.systems.effect import _resolve_formula_amount

    definition = _fixture_definition(sp_base=30.0)
    standard = {
        "scale_basis": "action_sp_base",
        "operation": "add",
        "formula_type": "ByBaseValue",
        "formula_base": "flat",
        "amount_role": "flat",
    }
    plain = BattleState(units={"seele": UnitState("seele", "ally", "avatar:1102")})
    amount, details, blocked = _resolve_formula_amount(
        "resource_delta", plain, standard, None, "seele", 1.0,
        action_definition=definition,
    )
    assert (amount, blocked) == (30.0, "")
    assert details["base_value_source"] == "action_definition"

    muted = BattleState(
        units={"seele": _unit_with_overrides([("SPBase", 0.0)], ["Skill"])}
    )
    amount, details, blocked = _resolve_formula_amount(
        "resource_delta", muted, standard, None, "seele", 1.0,
        action_definition=definition,
    )
    assert (amount, blocked) == (0.0, "")
    assert details["base_value_source"] == "skill_property_override"

    conflicting = replace(
        muted,
        units={"seele": replace(
            muted.units["seele"],
            flags={"status_details": [
                *muted.units["seele"].flags["status_details"],
                {
                    "instance_id": "status:insert:2",
                    "modifier_name": "insert",
                    "status_id": "modifier:insert",
                    "owner_id": "seele",
                    "caster_id": "seele",
                    "lifecycle_state": "active",
                    "skill_property_overrides": [{
                        "property_type": "SPBase",
                        "skill_types": ["Skill"],
                        "value": 5.0,
                        "status_instance_id": "status:insert:2",
                    }],
                },
            ]},
        )},
    )
    amount, _details, blocked = _resolve_formula_amount(
        "resource_delta", conflicting, standard, None, "seele", 1.0,
        action_definition=definition,
    )
    assert amount == 0.0
    assert blocked.startswith(
        "unsupported_formula:resource_action_sp_base_override_blocked:"
    )


def test_explicit_body_energy_keeps_resource_plan_zero() -> None:
    from types import SimpleNamespace

    from hsr.simulator_v8_clean_core.systems.action_preflight import action_energy_gain

    class _StubRules:
        def ability_tasks_for_action(self, action_id, level):
            return (SimpleNamespace(effect_id="effect:energy"),)

        def effect(self, effect_id):
            return SimpleNamespace(payload={"standard": {
                "resource": "energy",
                "scale_basis": "action_sp_base",
            }})

    definition = _fixture_definition(sp_base=30.0)
    rules = _StubRules()
    # The body is the single producer for explicit action_sp_base requests: the
    # plan stays zero even when an override changes the body value.
    assert action_energy_gain(rules, definition) == 0.0
    assert action_energy_gain(rules, definition, {"sp_base": 60.0}) == 0.0
    assert action_energy_gain(rules, definition, {"sp_base": 0.0}) == 0.0
    # Without an explicit body request the plan grants the effective value.
    assert action_energy_gain(None, definition, {"sp_base": 60.0}, base_value=30.0) == 60.0
    assert action_energy_gain(None, definition, {}, base_value=30.0) == 30.0



