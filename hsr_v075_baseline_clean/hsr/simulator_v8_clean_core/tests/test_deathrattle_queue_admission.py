"""Deathrattle insert queue authority is bound to one written death instance.

Component-level checks over the frozen queue-entry payload: only the unit's own
finalized death, its lethal HP mutation, the still-active Deathrattle status
instance and the formal OnDeathrattle callback/task/intent/resolution admit the
source Mask_AliveOrLimbo insert entry. Ordinary queue requests and every other
defeated unit keep the existing actor gate.
"""
from __future__ import annotations

from dataclasses import replace

from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, Mutation, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.ir import (
    CanonicalIR,
    IRSource,
    QueueIntentIR,
    QueueResolutionIR,
    StatusCallbackIR,
    StatusCallbackTaskIR,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.mutation_events import mutation_backed_event_id
from hsr.simulator_v8_clean_core.systems.queue import (
    DeathrattleQueueAdmission,
    QueueEntry,
    QueueTargetResolver,
    _entry_alive_state_blocked_reason,
    _entry_deathrattle_admitted,
    _is_gameplay_abort,
)
from hsr.simulator_v8_clean_core.systems.status_callbacks import (
    _deathrattle_queue_admission,
)
from hsr.simulator_v8_clean_core.systems.unit_lifecycle import UnitLifecycleSystem


MODIFIER_NAME = "Test_Initiate"
ABILITY_NAME = "Test_Insert"
INTENT_ID = "queue_intent:test"
QUEUE_KIND = "turn_insert_ability"
SOURCE_TASK_ID = "task:deathrattle"
CALLBACK_ID = "callback:deathrattle"

DEATHRATTLE_DETAIL = {
    "instance_id": "status:deathrattle",
    "status_id": "modifier:Test_Initiate",
    "modifier_name": MODIFIER_NAME,
    "owner_id": "child",
    "caster_id": "child",
    "source_id": "test",
    "lifecycle_state": "active",
    "behavior_flags": ["Deathrattle", "KeepOnDeathrattle"],
}
SERVANT_DETAIL = {
    "instance_id": "status:servant",
    "status_id": "modifier:MCommon_Servant",
    "modifier_name": "MCommon_Servant",
    "owner_id": "child",
    "caster_id": "owner",
    "source_id": "test",
    "lifecycle_state": "active",
    "behavior_flags": [],
}


def _rules():
    source = IRSource(
        "component/deathrattle-admission",
        "ValidationSynthetic",
        "component",
        {"component_input": True},
    )
    callback = StatusCallbackIR(
        CALLBACK_ID,
        MODIFIER_NAME,
        "OnDeathrattle",
        (SOURCE_TASK_ID,),
        source,
        (0,),
        coverage_status="executable",
    )
    task = StatusCallbackTaskIR(
        SOURCE_TASK_ID,
        CALLBACK_ID,
        MODIFIER_NAME,
        "OnDeathrattle",
        0,
        "root",
        "root",
        "TurnInsertAbility",
        source,
        coverage_status="executable",
    )
    intent = QueueIntentIR(
        INTENT_ID,
        SOURCE_TASK_ID,
        CALLBACK_ID,
        "phase",
        ABILITY_NAME,
        QUEUE_KIND,
        {
            "priority_ordering_admitted": True,
            "priority_value": 1,
            "priority_key": "MonsterDeathRattle",
        },
        "Caster",
        ABILITY_NAME,
        {},
        "Caster",
        True,
        {},
        source,
        coverage_status="executable",
        owner_alive_state="alive_or_limbo",
        target_alive_state="alive_or_limbo",
        can_run_on_unselectable_target=True,
        custom_tag="deathrattle",
    )
    resolution = QueueResolutionIR(
        "resolution:test",
        INTENT_ID,
        ABILITY_NAME,
        "standalone_ability_graph",
        {
            "standalone_ability_graph_id": "graph:deathrattle",
            "task_ids": ["task:insert"],
            "executable_task_ids": ["task:insert"],
            "phase_ids": ["phase"],
        },
        source,
        coverage_status="executable",
    )
    rules = RuleBook(
        CanonicalIR(
            "component:deathrattle-admission",
            queue_intents=(intent,),
            queue_resolutions=(resolution,),
            status_callbacks=(callback,),
            status_callback_tasks=(task,),
        )
    )
    return rules, callback, task, intent, resolution


def _case():
    rules, callback, task, intent, resolution = _rules()
    state = BattleState(
        units={
            "owner": UnitState("owner", "enemy", "test:owner", hp=100, max_hp=100),
            "child": UnitState("child", "enemy", "test:child", hp=100, max_hp=100),
            "other": UnitState("other", "enemy", "test:other", hp=100, max_hp=100),
        }
    )
    lifecycle = UnitLifecycleSystem()
    mutations, record = lifecycle.forced_death_mutations(
        state,
        "child",
        effect_id="effect:test_force_kill",
        effect_source={"kind": "validation_fixture"},
        source_trace={"kind": "validation_fixture"},
        target_alias="Caster",
    )
    reducer = MutationReducer()
    defeated = reducer.apply_all(state, mutations)
    status_mutation = Mutation(
        "set",
        ("units", "child", "flags", "status_details"),
        None,
        [DEATHRATTLE_DETAIL, SERVANT_DETAIL],
        "validation fixture statuses",
        "scenario_setup",
        before_exists=False,
    )
    defeated = reducer.apply_all(defeated, (status_mutation,))
    death_instance_id = record["lifecycle_mutation_id"]
    death_event = GameEvent(
        "unit.defeated",
        source_id="owner",
        target_id="child",
        event_id=mutation_backed_event_id(death_instance_id, "unit.defeated"),
        window="unit.defeated",
        process_only=True,
        payload={
            "target_id": "child",
            "defeated_unit_id": "child",
            "lifecycle_mutation_id": death_instance_id,
            "hp_mutation_id": record["hp_mutation_id"],
            "record_type": "formal_forced_death",
        },
    )
    detail = next(
        item
        for item in defeated.units["child"].flags["status_details"]
        if str(item.get("instance_id") or "") == "status:deathrattle"
    )
    admission, reason = _deathrattle_queue_admission(
        defeated, callback, task, dict(detail), death_event, intent
    )
    assert admission is not None and not reason, reason
    return state, defeated, record, admission, rules, resolution, death_event


def _entry(admission, **overrides):
    values = {
        "entry_id": "queue_entry:test:0",
        "queue_name": "turn_insert_ability",
        "queue_kind": admission.queue_kind if admission is not None else QUEUE_KIND,
        "queue_intent_id": admission.queue_intent_id if admission is not None else INTENT_ID,
        "actor_id": "child",
        "action_or_ability_ref": (
            admission.ability_name if admission is not None else ABILITY_NAME
        ),
        "target_ids": (),
        "priority_source": {"priority_ordering_admitted": True},
        "source_trace": {},
        "owner_alive_state": "alive_or_limbo",
        "target_alive_state": "alive_or_limbo",
        "can_run_on_unselectable_target": True,
        "deathrattle_admission": admission.to_json() if admission is not None else None,
    }
    values.update(overrides)
    return QueueEntry(**values).to_json()


def _resolve(defeated, death_event, admission):
    return QueueTargetResolver().resolve(
        defeated,
        detail={"owner_id": "child", "caster_id": "child", "instance_id": "status:deathrattle"},
        trigger_event=death_event,
        actor_alias="ModifierOwnerEntity",
        target_alias=None,
        allow_unselectable_target=True,
        deathrattle_admission=admission,
    )


def test_own_death_instance_admits_the_deathrattle_insert():
    _, defeated, _, admission, rules, resolution, death_event = _case()
    assert admission.queue_intent_id == INTENT_ID
    assert admission.queue_kind == QUEUE_KIND
    assert admission.source_task_id == SOURCE_TASK_ID
    entry = _entry(admission)
    assert admission.blocked_reason(defeated) == ""
    assert admission.resolution_blocked_reason(entry, resolution, rules) == ""
    assert _entry_alive_state_blocked_reason(defeated, entry) == ""
    assert _entry_deathrattle_admitted(defeated, entry) is True
    result = _resolve(defeated, death_event, admission)
    assert result.ok, result.blocked_reason
    assert result.actor_id == "child"


def test_other_defeated_units_and_plain_entries_stay_blocked():
    _, defeated, _, admission, _, _, death_event = _case()
    plain = _entry(None)
    assert _entry_alive_state_blocked_reason(defeated, plain) == (
        "queue_owner_alive_state_not_met:child:defeated"
    )
    assert _entry_deathrattle_admitted(defeated, plain) is False
    assert _is_gameplay_abort(defeated, plain, "queue_owner_alive_state_not_met:child:defeated")
    result = _resolve(defeated, death_event, None)
    assert not result.ok and result.blocked_reason == "queue_actor_unit_defeated:child"
    other = _entry(admission, actor_id="other")
    assert _entry_alive_state_blocked_reason(defeated, other) == (
        "queue_owner_deathrattle_contract_mismatch:child"
    )
    # The formal body of the same intent is still not a licence for another
    # actor's entry.
    assert _resolve(defeated, death_event, replace(admission, unit_id="other")).blocked_reason == (
        "queue_actor_deathrattle_unit_mismatch:child"
    )



def test_admission_rejects_a_changed_death_or_source_identity():
    _, defeated, _, admission, rules, resolution, _ = _case()
    changed_death = replace(admission, death_instance_id="mutation:other")
    assert changed_death.blocked_reason(defeated) == (
        "deathrattle_admission_death_instance_mismatch:child"
    )
    entry = _entry(changed_death)
    assert _entry_deathrattle_admitted(defeated, entry) is False
    reason = _entry_alive_state_blocked_reason(defeated, entry)
    assert reason == "deathrattle_admission_death_instance_mismatch:child"
    # A changed death record is an implementation defect, not an ordinary
    # alive-state cancellation: the entry must block and stay retained.
    assert not _is_gameplay_abort(defeated, entry, reason)
    changed_hp = replace(admission, hp_mutation_id="mutation:other")
    assert changed_hp.blocked_reason(defeated) == (
        "deathrattle_admission_hp_mutation_mismatch:child"
    )
    changed_status = replace(admission, source_status_instance_id="status:servant")
    assert changed_status.blocked_reason(defeated) == (
        "deathrattle_admission_source_modifier_mismatch:child"
    )
    assert replace(
        admission,
        source_event_id=mutation_backed_event_id("mutation:other", "unit.defeated"),
    ).blocked_reason(defeated) == "deathrattle_admission_source_event_mismatch:child"
    missing_status = replace(admission, source_status_instance_id="status:missing")
    assert missing_status.blocked_reason(defeated) == (
        "deathrattle_admission_source_status_missing:child"
    )
    assert replace(admission, unit_id="other").blocked_reason(defeated) == (
        "deathrattle_admission_unit_not_defeated:other"
    )


def test_admission_rejects_a_changed_formal_queue_intent():
    _, defeated, _, admission, rules, resolution, _ = _case()
    # The state-side death identity of the source entry is untouched; only the
    # formal intent/task the Deathrattle callback bound to is changed.
    changed_intent = replace(admission, queue_intent_id="queue_intent:other")
    assert changed_intent.blocked_reason(defeated) == ""
    assert changed_intent.resolution_blocked_reason(
        _entry(changed_intent), resolution, rules
    ) == "queue_owner_deathrattle_intent_missing:queue_intent:other"
    changed_kind = replace(admission, queue_kind="interrupt_queue")
    assert changed_kind.resolution_blocked_reason(
        _entry(changed_kind), resolution, rules
    ) == f"queue_owner_deathrattle_intent_mismatch:{INTENT_ID}"
    changed_task = replace(admission, source_task_id="task:other")
    assert changed_task.resolution_blocked_reason(
        _entry(changed_task), resolution, rules
    ) == f"queue_owner_deathrattle_intent_mismatch:{INTENT_ID}"
    assert admission.resolution_blocked_reason(_entry(admission), None, rules) == (
        f"queue_owner_deathrattle_resolution_mismatch:{INTENT_ID}"
    )
    assert admission.resolution_blocked_reason(_entry(admission), resolution, None) == (
        "queue_owner_deathrattle_rulebook_missing:child"
    )
    hand_made = replace(
        resolution,
        resolved_ids={
            **resolution.resolved_ids,
            "executable_task_ids": ["task:other"],
        },
    )
    assert admission.resolution_blocked_reason(_entry(admission), hand_made, rules) == (
        f"queue_owner_deathrattle_resolution_mismatch:{INTENT_ID}"
    )


def test_entry_admission_payload_shape_is_validated():
    _, defeated, _, admission, _, _, _ = _case()
    for field in ("source_event_id", "queue_intent_id", "source_task_id"):
        bad = dict(admission.to_json())
        bad.pop(field)
        entry = dict(_entry(None))
        entry["deathrattle_admission"] = bad
        reason = _entry_alive_state_blocked_reason(defeated, entry)
        assert reason.startswith("queue_owner_deathrattle_admission_invalid:"), field
        assert not _is_gameplay_abort(defeated, entry, reason), field
    # A shape-complete admission still has to describe the entry that carries it.
    borrowed = _entry(admission, queue_intent_id="queue_intent:other")
    assert _entry_alive_state_blocked_reason(defeated, borrowed) == (
        "queue_owner_deathrattle_contract_mismatch:child"
    )
    assert DeathrattleQueueAdmission.from_json(admission.to_json()) == admission
