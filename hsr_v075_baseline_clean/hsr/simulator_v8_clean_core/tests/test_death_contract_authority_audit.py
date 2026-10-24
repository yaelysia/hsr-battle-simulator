"""Focused component contracts for death authority, status silence and native audit.

These checks use the shipped typed producers and a minimal formal RuleBook. They
are not a battle integration test: every positive is produced by the same
producer the runtime calls, and every negative tampers only the produced
mutation/queue/record copies.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from hsr.simulator_v8_clean_core.core.model import (
    BattleState,
    GameEvent,
    Mutation,
    PendingDefeatPlan,
    UnitState,
    thaw_json,
)
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.settlement import SettlementRecord
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.core.state_integrity import CommittedStateIntegrityGate
from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_fixed
from hsr.simulator_v8_clean_core.rules.ir import (
    AbilityPhaseIR,
    AbilityTaskIR,
    BreakTemplateIR,
    CanonicalIR,
    EffectIR,
    HitProfileIR,
    IRSource,
    QueueIntentIR,
    QueueResolutionIR,
    StandaloneAbilityGraphIR,
    StatusCallbackIR,
    StatusCallbackTaskIR,
    ToughnessEmissionIR,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.break_system import clear_death_break_state
from hsr.simulator_v8_clean_core.systems.damage import DamageSystem
from hsr.simulator_v8_clean_core.systems.ability import (
    AbilityTaskSystem,
    StandaloneAbilityInvocation,
)
from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry
from hsr.simulator_v8_clean_core.systems.mutation_events import mutation_backed_event_id
from hsr.simulator_v8_clean_core.systems.queue import (
    DeathrattleQueueAdmission,
    QueueEntry,
    QueueSystem,
)
from hsr.simulator_v8_clean_core.systems.scheduler import (
    CombatScheduler,
    _standalone_death_instance_id,
)
from hsr.simulator_v8_clean_core.systems.status import (
    StatusInstance,
    StatusLifecyclePlan,
    StatusSystem,
    _status_lifecycle_events,
)
from hsr.simulator_v8_clean_core.systems.status_callbacks import (
    _deathrattle_queue_admission,
)
from hsr.simulator_v8_clean_core.systems.unit_lifecycle import UnitLifecycleSystem


def _source() -> IRSource:
    return IRSource(
        "component/death-contract",
        "ValidationSynthetic",
        "component",
        {"component_input": True},
    )


def _queue_fixture():
    source = _source()
    callback = StatusCallbackIR(
        "callback:death",
        "component:Deathrattle",
        "OnDeathrattle",
        ("task:callback",),
        source,
        (0,),
        coverage_status="executable",
    )
    task = StatusCallbackTaskIR(
        "task:callback",
        "callback:death",
        "component:Deathrattle",
        "OnDeathrattle",
        0,
        "root",
        "root",
        "TurnInsertAbility",
        source,
        coverage_status="executable",
    )
    intent = QueueIntentIR(
        "intent:allowed",
        "task:callback",
        "callback:death",
        "phase",
        "TurnInsertAbility",
        "turn_insert_ability",
        {
            "priority_ordering_admitted": True,
            "priority_value": 1,
            "priority_key": "MonsterDeathRattle",
        },
        "Caster",
        "allowed",
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
        "resolution:allowed",
        "intent:allowed",
        "allowed",
        "standalone_ability_graph",
        {
            "standalone_ability_graph_id": "graph",
            "task_ids": ["task:allowed"],
            "executable_task_ids": ["task:allowed"],
            "phase_ids": ["phase"],
        },
        source,
        coverage_status="executable",
    )
    rules = RuleBook(
        CanonicalIR(
            "component:queue",
            queue_intents=(intent,),
            queue_resolutions=(resolution,),
            status_callbacks=(callback,),
            status_callback_tasks=(task,),
        )
    )
    dead = UnitState(
        "dead",
        "enemy",
        "component:dead",
        hp=0.0,
        lifecycle_status="defeated",
        flags={
            "defeat_record": {
                "lifecycle_mutation_id": "death",
                "hp_mutation_id": "lethal",
                "target_id": "dead",
                "defeated_unit_id": "dead",
            },
            "status_details": [
                {
                    "instance_id": "status:death",
                    "owner_id": "dead",
                    "modifier_name": "component:Deathrattle",
                    "behavior_flags": ["Deathrattle"],
                    "lifecycle_state": "active",
                }
            ],
        },
    )
    death_event = GameEvent(
        "unit.defeated",
        source_id="owner",
        target_id="dead",
        event_id=mutation_backed_event_id("death", "unit.defeated"),
        window="unit.defeated",
        payload={
            "target_id": "dead",
            "defeated_unit_id": "dead",
            "lifecycle_mutation_id": "death",
            "hp_mutation_id": "lethal",
        },
    )
    permit, reason = _deathrattle_queue_admission(
        BattleState(units={"dead": dead}),
        callback,
        task,
        dict(dead.flags["status_details"][0]),
        death_event,
        intent,
    )
    assert permit is not None and not reason, reason
    entry = QueueEntry(
        "entry",
        "interrupt_queue",
        "turn_insert_ability",
        "intent:allowed",
        "dead",
        "allowed",
        ("dead",),
        {"priority_ordering_admitted": True, "priority_value": 1},
        {},
        queue_window_id="window",
        window_family="insert_ability",
        target_resolution={"ok": True, "target_ids": ["dead"]},
        owner_alive_state="alive_or_limbo",
        target_alive_state="alive_or_limbo",
        can_run_on_unselectable_target=True,
        deathrattle_admission=permit.to_json(),
    ).to_json()
    state = BattleState(units={"dead": dead}, queues={"interrupt_queue": (entry,)})
    return source, rules, resolution, permit, state, entry, dead


def _weakness_fixture():
    source = _source()
    effect = EffectIR(
        "effect:protected",
        "StackWeakness",
        {
            "standard": {
                "operation_type": "Protected",
                "target_alias": "ModifierOwnerEntity",
                "target_expression_id": "expr:protected",
                "target_expression_coverage_status": "executable",
                "weaknesses": ["Physical"],
                "blocked_reason": "",
            }
        },
        source,
        coverage_status="executable",
    )
    rules = RuleBook(CanonicalIR("component:protected", effects=(effect,)))
    state = BattleState(
        units={
            "owner": UnitState(
                "owner",
                "enemy",
                "component:owner",
                hp=100.0,
                flags={
                    "status_details": [
                        {
                            "instance_id": "status:1",
                            "status_id": "modifier:protect",
                            "owner_id": "owner",
                            "modifier_name": "component:protect",
                            "lifecycle_state": "active",
                            "source_trace": {"fixture": True},
                        }
                    ]
                },
            )
        }
    )
    registry = EffectRegistry(StatusSystem(rules))
    context = EffectExecutionContext(
        state,
        "owner",
        "component",
        owner_id="owner",
        event_payload={
            "status_instance_id": "status:1",
            "modifier_name": "component:protect",
        },
    )
    return rules, effect, state, registry, context


def _break_fixture():
    source = _source()
    task = AbilityTaskIR(
        "task",
        "phase",
        "action",
        1,
        "component",
        "OnStart",
        0,
        "$.OnStart[0]",
        "root",
        "DamageByAttackProperty",
        source,
        coverage_status="executable",
    )
    profile = HitProfileIR(
        "profile",
        "action",
        1,
        0,
        "selected",
        numeric_fixed(1),
        {},
        numeric_fixed(30),
        {},
        "direct",
        "Fire",
        source,
        coverage_status="executable",
    )
    emission = ToughnessEmissionIR(
        "toughness",
        "action",
        1,
        "phase",
        "task",
        "profile",
        "selected",
        "Fire",
        numeric_fixed(30),
        source,
        coverage_status="executable",
    )
    template = BreakTemplateIR(
        "break", "Fire", (), source, coverage_status="executable"
    )
    effect = EffectIR(
        "exit",
        "ExitBreakState",
        {
            "standard": {
                "operation": "exit_break_state",
                "target_alias": "Caster",
                "cancel_recover_anim": True,
                "blocked_reason": "",
            }
        },
        source,
        coverage_status="executable",
    )
    rules = RuleBook(
        CanonicalIR(
            "component:death-break",
            ability_tasks=(task,),
            hit_profiles=(profile,),
            toughness_emissions=(emission,),
            break_templates=(template,),
            effects=(effect,),
        )
    )
    break_source = {
        "attacker_id": "attacker",
        "toughness_emission_id": "toughness",
        "source_task_id": "task",
        "hit_profile_id": "profile",
        "source_trace": {"fixture": True},
        "break_template_id": "break",
        "break_template_source": template.source.to_json(),
    }
    break_flags = {
        "broken": True,
        "break_element": "Fire",
        "break_source": break_source,
    }
    state = BattleState(
        units={
            "corpse": UnitState(
                "corpse",
                "enemy",
                "component:corpse",
                hp=0.0,
                lifecycle_status="defeated",
                flags={
                    **break_flags,
                    "defeat_record": {
                        "lifecycle_mutation_id": "death",
                        "hp_mutation_id": "lethal",
                        "target_id": "corpse",
                        "defeated_unit_id": "corpse",
                    },
                },
            ),
            "other_live_unit": UnitState(
                "other_live_unit",
                "enemy",
                "component:other",
                hp=100.0,
                flags=dict(break_flags),
            ),
        }
    )
    return rules, state, effect, source


def _violation_reasons(result) -> set[str]:
    return {violation.reason for violation in result.violations}


def test_silent_dispel_is_a_typed_plan_field_not_an_audit_switch():
    instance = StatusInstance(
        "component:status",
        "modifier:component",
        "component",
        "owner",
        "component:source",
        "owner",
    ).to_json()
    state = BattleState(
        units={
            "owner": UnitState(
                "owner",
                "ally",
                "component",
                flags={"status_details": [instance]},
            )
        }
    )
    plan = StatusLifecyclePlan(
        operation="remove",
        target_id="owner",
        status_id="modifier:component",
        source="status_system",
        existing_detail=instance,
        source_trace={},
    )
    baseline = _status_lifecycle_events(
        plan, state, mutation_ids=("component:mutation",)
    )
    trace_only = _status_lifecycle_events(
        replace(plan, source_trace={"silent_dispel": True}),
        state,
        mutation_ids=("component:mutation",),
    )
    formal = _status_lifecycle_events(
        replace(plan, silent_dispel=True),
        state,
        mutation_ids=("component:mutation",),
    )
    assert [event.payload["callback_event"] for event in baseline] == [
        "OnDestroy",
        "OnModifierRemove",
        "OnListenModifierRemove",
    ]
    assert [event.payload["callback_event"] for event in trace_only] == [
        event.payload["callback_event"] for event in baseline
    ]
    assert formal == ()
    assert plan.to_json()["silent_dispel"] is False
    assert replace(plan, silent_dispel=True).to_json()["silent_dispel"] is True


def test_deathrattle_admission_is_bound_to_formal_intent_and_resolution():
    source, rules, resolution, permit, state, entry, dead = _queue_fixture()
    plan = QueueSystem().plan_drain(
        state, "interrupt_queue", resolution, rules=rules
    )
    assert plan.ok, plan.blocked_reason

    # The producer binds the actual callback task, not just matching text ids.
    intent = rules.queue_intent("intent:allowed")
    callback = rules.status_callback("callback:death")
    task = rules.status_callback_task("task:callback")
    death_event = GameEvent(
        "unit.defeated",
        source_id="owner",
        target_id="dead",
        event_id=mutation_backed_event_id("death", "unit.defeated"),
        window="unit.defeated",
        payload={
            "target_id": "dead",
            "defeated_unit_id": "dead",
            "lifecycle_mutation_id": "death",
            "hp_mutation_id": "lethal",
        },
    )
    detail = dict(dead.flags["status_details"][0])
    base_state = BattleState(units={"dead": dead})
    assert _deathrattle_queue_admission(
        base_state,
        callback,
        replace(task, modifier_name="component:Other"),
        detail,
        death_event,
        intent,
    ) == (None, "deathrattle_admission_source_callback_not_admitted")
    foreign_callback = replace(callback, modifier_name="component:Other")
    foreign_task = replace(task, modifier_name="component:Other")
    assert _deathrattle_queue_admission(
        base_state,
        foreign_callback,
        foreign_task,
        detail,
        death_event,
        intent,
    ) == (None, "deathrattle_admission_source_modifier_mismatch")
    assert _deathrattle_queue_admission(
        base_state,
        callback,
        replace(
            task,
            coverage_status="blocked",
            blocked_reason="component:task_not_admitted",
        ),
        detail,
        death_event,
        intent,
    ) == (None, "deathrattle_admission_source_callback_not_admitted")

    # A formally blocked intent is no executable authority even when the
    # resolution object is still the admitted one.
    blocked_rules = RuleBook(
        replace(
            rules.ir,
            queue_intents=(
                replace(
                    intent,
                    coverage_status="blocked",
                    blocked_reason="component:source_not_admitted",
                ),
            ),
        )
    )
    blocked_plan = QueueSystem().plan_drain(
        state, "interrupt_queue", resolution, rules=blocked_rules
    )
    assert not blocked_plan.ok
    assert "queue_owner_deathrattle_intent_mismatch" in blocked_plan.blocked_reason

    # A callback/task that does not describe this source modifier's
    # OnDeathrattle is not the formal source of the admission.
    foreign_rules = RuleBook(
        replace(
            rules.ir,
            status_callbacks=(
                replace(callback, modifier_name="component:Other"),
            ),
        )
    )
    foreign_plan = QueueSystem().plan_drain(
        state, "interrupt_queue", resolution, rules=foreign_rules
    )
    assert not foreign_plan.ok
    assert (
        "queue_owner_deathrattle_source_callback_not_admitted"
        in foreign_plan.blocked_reason
    )

    # Frozen queue snapshots must round-trip the typed authority.
    from hsr.simulator_v8_clean_core.immutable_json import freeze_json

    frozen = freeze_json(permit.to_json())
    assert DeathrattleQueueAdmission.from_json(frozen) == permit

    other_entry = {
        **entry,
        "queue_intent_id": "intent:other",
        "action_or_ability_ref": "other",
    }
    other_resolution = replace(
        resolution,
        queue_resolution_id="resolution:other",
        queue_intent_id="intent:other",
        action_or_ability_ref="other",
        resolved_ids={"executable_task_ids": ["task:other"]},
    )
    other_state = BattleState(
        units={"dead": dead}, queues={"interrupt_queue": (other_entry,)}
    )
    borrowed = QueueSystem().plan_drain(
        other_state, "interrupt_queue", other_resolution, rules=rules
    )
    assert not borrowed.ok
    assert "queue_owner_deathrattle_contract_mismatch" in borrowed.blocked_reason

    other_death = replace(
        permit,
        death_instance_id="other-death",
        source_event_id=mutation_backed_event_id("other-death", "unit.defeated"),
    )
    other_death_entry = {**entry, "deathrattle_admission": other_death.to_json()}
    other_death_state = BattleState(
        units={"dead": dead},
        queues={"interrupt_queue": (other_death_entry,)},
    )
    other_death_plan = QueueSystem().plan_drain(
        other_death_state, "interrupt_queue", resolution, rules=rules
    )
    assert not other_death_plan.ok
    assert "deathrattle_admission_death_instance_mismatch" in other_death_plan.blocked_reason

    forged_event = replace(permit, source_event_id="event:forged")
    forged_entry = {**entry, "deathrattle_admission": forged_event.to_json()}
    forged_state = BattleState(
        units={"dead": dead}, queues={"interrupt_queue": (forged_entry,)}
    )
    forged_plan = QueueSystem().plan_drain(
        forged_state, "interrupt_queue", resolution, rules=rules
    )
    assert not forged_plan.ok
    assert "deathrattle_admission_source_event_mismatch" in forged_plan.blocked_reason

    wrong_body = QueueSystem().plan_drain(
        state,
        "interrupt_queue",
        replace(resolution, resolved_ids={**resolution.resolved_ids,
                                           "executable_task_ids": ["task:other"]}),
        rules=rules,
    )
    assert not wrong_body.ok
    assert "queue_owner_deathrattle_resolution_mismatch" in wrong_body.blocked_reason

    # No RuleBook means no formal intent/body verification: fail closed.
    without_rules = QueueSystem().plan_drain(state, "interrupt_queue", resolution)
    assert not without_rules.ok
    assert "queue_owner_deathrattle_rulebook_missing" in without_rules.blocked_reason

    # An ordinary defeated actor cannot borrow the Mask_AliveOrLimbo branch.
    plain_entry = {**entry, "deathrattle_admission": {}}
    plain_state = BattleState(
        units={"dead": dead}, queues={"interrupt_queue": (plain_entry,)}
    )
    plain = QueueSystem().plan_drain(
        plain_state, "interrupt_queue", resolution, rules=rules
    )
    assert not plain.ok
    assert (
        "queue_owner_alive_state" in plain.blocked_reason
        or "queue_action_actor" in plain.blocked_reason
    )


def test_malformed_deathrattle_permission_blocks_without_cancelling():
    _, rules, _, permit, state, entry, dead = _queue_fixture()
    cases = (
        (
            "bad_shape",
            {
                **entry,
                "deathrattle_admission": {
                    **permit.to_json(),
                    "unexpected": True,
                },
            },
            "queue_owner_deathrattle_admission_invalid",
        ),
        (
            "borrowed_contract",
            {**entry, "action_or_ability_ref": "other"},
            "queue_owner_deathrattle_contract_mismatch",
        ),
    )
    for label, bad_entry, expected_reason in cases:
        bad_state = BattleState(
            units={"dead": dead}, queues={"interrupt_queue": (bad_entry,)}
        )
        step = CombatScheduler(rules)._try_queue_drain(bad_state)
        assert step is not None, label
        assert step.transition.outcome.successor_eligible is False, label
        assert step.transition.transaction.mutations == (), label
        assert len(step.after_state.queues["interrupt_queue"]) == 1, label
        assert any(
            expected_reason in reason
            for reason in step.transition.outcome.reason_codes
        ), (label, step.transition.outcome.reason_codes)


def test_protected_weakness_audit_rebuilds_the_formal_union():
    rules, effect, state, registry, context = _weakness_fixture()
    auditor = RuntimeSourceAuditor(rules)
    result = registry.execute(effect, context)
    assert not result.unsupported
    assert result.mutations and result.records
    assert auditor.validate_execution(result.mutations, result.records).ok

    mutation = result.mutations[0]
    tampered = replace(
        mutation,
        after=[
            {**detail, "weakness_protection": ["Fire"]}
            for detail in mutation.after
        ],
        metadata={**mutation.metadata, "weakness_protection": ["Fire"]},
    )
    record = result.records[0]
    tampered_record = {
        **record,
        "mutation_id": tampered.stable_id(),
        "payload": {**record["payload"], "weakness_protection": ["Fire"]},
    }
    rejected = auditor.validate_execution((tampered,), (tampered_record,))
    assert not rejected.ok
    assert "weakness_protection_declared_not_effect_expected" in _violation_reasons(rejected)

    # A repeated projection of the same formal element is a legitimate no-diff.
    after = MutationReducer().apply_all(state, result.mutations)
    repeated = registry.execute(effect, replace(context, state=after))
    assert not repeated.unsupported
    assert len(repeated.mutations) == 1
    assert repeated.mutations[0].before == repeated.mutations[0].after
    assert auditor.validate_execution(repeated.mutations, repeated.records).ok


def test_death_break_exit_requires_the_final_death_and_exact_provenance():
    rules, state, effect, source = _break_fixture()
    result = clear_death_break_state(
        rules,
        state,
        unit_id="corpse",
        effect_id="exit",
        death_instance_id="death",
    )
    assert result.ok, result.errors
    # The caller's audit trace is never a runtime precondition.
    with pytest.raises(TypeError):
        clear_death_break_state(
            rules,
            state,
            unit_id="corpse",
            effect_id="exit",
            death_instance_id="death",
            effect_source_trace={},
        )
    auditor = RuntimeSourceAuditor(rules)
    assert auditor.validate_execution(result.mutations, result.records).ok

    # The formal effect caller consumes the same final-death identity; without
    # it the broken branch must fail closed instead of guessing a corpse.
    registry = EffectRegistry(StatusSystem(rules))
    effect_result = registry.execute(
        effect,
        EffectExecutionContext(
            state,
            "corpse",
            "component",
            owner_id="corpse",
            death_instance_id="death",
        ),
    )
    assert not effect_result.unsupported
    assert auditor.validate_execution(
        effect_result.mutations, effect_result.records
    ).ok
    missing_identity = registry.execute(
        effect,
        EffectExecutionContext(state, "corpse", "component", owner_id="corpse"),
    )
    assert missing_identity.unsupported
    assert missing_identity.mutations == ()

    mutation = result.mutations[0]
    record = result.records[0]
    redirected = replace(
        mutation, path=("units", "other_live_unit", "flags", "broken")
    )
    redirected_record = {**record, "mutation_id": redirected.stable_id()}
    redirected_audit = auditor.validate_execution(
        (redirected,), (redirected_record,)
    )
    assert not redirected_audit.ok
    assert "death_break_exit_write_not_admitted" in _violation_reasons(
        redirected_audit
    )

    wrong_source = {**record, "source": "unrelated_producer"}
    wrong_source_audit = auditor.validate_execution((mutation,), (wrong_source,))
    assert not wrong_source_audit.ok
    assert "death_break_exit_native_record_missing" in _violation_reasons(
        wrong_source_audit
    )

    # A partially reported cleanup cannot pass for the same death instance.
    partial_audit = auditor.validate_execution((mutation,), result.records)
    assert not partial_audit.ok
    assert "death_break_exit_mutation_set_mismatch" in _violation_reasons(
        partial_audit
    )

    # A renamed recovery kind cannot fall back to the ordinary audit path.
    laundered = []
    laundered_records = []
    for item_record, item in zip(result.records, result.mutations):
        metadata = thaw_json(item.metadata)
        metadata["break_recovery"]["kind"] = "ordinary_before_action"
        forged = replace(
            item,
            path=("units", "other_live_unit", "flags", item.path[-1]),
            metadata=metadata,
        )
        laundered.append(forged)
        laundered_records.append(
            {**item_record, "mutation_id": forged.stable_id()}
        )
    laundered_audit = auditor.validate_execution(
        tuple(laundered), tuple(laundered_records)
    )
    assert not laundered_audit.ok
    assert "break_recovery_family_label_not_admitted" in _violation_reasons(
        laundered_audit
    )
    assert "death_break_exit_write_not_admitted" in _violation_reasons(
        laundered_audit
    )

    # The three writes must describe one original scene; re-signing only one
    # mutation trace and its native record is not a new scene.
    forged_metadata = thaw_json(mutation.metadata)
    forged_trace = forged_metadata["source_trace"]
    forged_source = thaw_json(forged_trace["original_break_source"])
    forged_source["attacker_id"] = "other_live_unit"
    forged_trace["original_break_source"] = forged_source
    forged_trace["original_break_state"]["break_source"] = forged_source
    forged_mutation = replace(mutation, metadata=forged_metadata)
    forged_records = tuple(
        {
            **item_record,
            "mutation_id": forged_mutation.stable_id(),
            "trace": forged_trace,
        }
        if item_record["mutation_id"] == mutation.stable_id()
        else item_record
        for item_record in result.records
    )
    scene_audit = auditor.validate_execution(
        (forged_mutation, *result.mutations[1:]), forged_records
    )
    assert not scene_audit.ok
    assert "death_break_exit_original_scene_mismatch" in _violation_reasons(
        scene_audit
    )

    limbo = replace(
        state,
        units={
            "corpse": replace(state.units["corpse"], lifecycle_status="limbo"),
            "other_live_unit": state.units["other_live_unit"],
        },
    )
    limbo_result = clear_death_break_state(
        rules,
        limbo,
        unit_id="corpse",
        effect_id="exit",
        death_instance_id="death",
    )
    assert not limbo_result.ok
    assert limbo_result.mutations == ()
    assert "death_break_exit_target_not_finalized" in limbo_result.errors


def test_native_pending_defeat_is_not_cleared_as_a_corpse():
    from hsr.simulator_v8_clean_core.tests.test_kill_energy_shared_producer import (
        _primitive_case,
    )

    rules, state, _, source = _break_fixture()
    base, packet = _primitive_case()
    break_flags = {
        key: state.units["corpse"].flags[key]
        for key in ("broken", "break_element", "break_source")
    }
    target = base.units["target"]
    base = replace(
        base,
        units={
            **base.units,
            "target": replace(target, flags={**target.flags, **break_flags}),
        },
    )
    native = DamageSystem().apply_packet(base, packet)
    assert native.ok, native.errors
    hp = next(
        mutation
        for mutation in native.mutations
        if mutation.path == ("units", "target", "hp")
    )
    cause = PendingDefeatPlan(
        "target",
        base.event_index,
        hp,
        "owner",
        packet.source_frame.to_json(),
        packet.source_trace,
    )
    lifecycle = UnitLifecycleSystem()
    entering = (hp, *lifecycle.begin_limbo_mutations(base, cause))
    pending_state = MutationReducer().apply_all(base, entering)
    integrity = CommittedStateIntegrityGate().check_full(pending_state)
    assert integrity.ok, integrity
    assert lifecycle.pending_defeat(pending_state, "target") is not None
    assert "defeat_record" not in pending_state.units["target"].flags
    cleared = clear_death_break_state(
        rules,
        pending_state,
        unit_id="target",
        effect_id="exit",
        death_instance_id=cause.hp_mutation.stable_id(),
    )
    assert not cleared.ok
    assert cleared.mutations == ()
    assert "death_break_exit_target_not_finalized" in cleared.errors
def _standalone_death_fixture():
    source = _source()
    exit_effect = EffectIR(
        "exit",
        "ExitBreakState",
        {
            "standard": {
                "operation": "exit_break_state",
                "target_alias": "Caster",
                "cancel_recover_anim": True,
                "blocked_reason": "",
            }
        },
        source,
        coverage_status="executable",
    )
    exit_task = AbilityTaskIR(
        "task:exit",
        "phase:exit",
        "action:exit",
        1,
        "exit ability",
        "OnStart",
        0,
        "$.OnStart[0]",
        "root",
        "ExitBreakState",
        source,
        effect_id="exit",
        coverage_status="executable",
    )
    exit_phase = AbilityPhaseIR(
        "phase:exit",
        "",
        "action:exit",
        1,
        "exit ability",
        0,
        {},
        {},
        {},
        source,
        coverage_status="executable",
        task_ids=("task:exit",),
        invocation_role="external_legacy",
    )
    graph = StandaloneAbilityGraphIR(
        "graph:exit",
        "exit ability",
        "mainline_monster",
        ("phase:exit",),
        ("task:exit",),
        ("task:exit",),
        source,
        coverage_status="executable",
    )
    break_task = AbilityTaskIR(
        "task:break",
        "phase:break",
        "action:break",
        1,
        "component",
        "OnStart",
        0,
        "$.OnStart[0]",
        "root",
        "DamageByAttackProperty",
        source,
        coverage_status="executable",
    )
    profile = HitProfileIR(
        "profile",
        "action:break",
        1,
        0,
        "selected",
        numeric_fixed(1),
        {},
        numeric_fixed(30),
        {},
        "direct",
        "Fire",
        source,
        coverage_status="executable",
    )
    emission = ToughnessEmissionIR(
        "toughness",
        "action:break",
        1,
        "phase:break",
        "task:break",
        "profile",
        "selected",
        "Fire",
        numeric_fixed(30),
        source,
        coverage_status="executable",
    )
    template = BreakTemplateIR(
        "break", "Fire", (), source, coverage_status="executable"
    )
    callback = StatusCallbackIR(
        "callback:death",
        "component:Deathrattle",
        "OnDeathrattle",
        ("task:callback",),
        source,
        (0,),
        coverage_status="executable",
    )
    callback_task = StatusCallbackTaskIR(
        "task:callback",
        "callback:death",
        "component:Deathrattle",
        "OnDeathrattle",
        0,
        "root",
        "root",
        "TurnInsertAbility",
        source,
        coverage_status="executable",
    )
    intent = QueueIntentIR(
        "intent:exit",
        "task:callback",
        "callback:death",
        "phase:exit",
        "TurnInsertAbility",
        "turn_insert_ability",
        {"priority_ordering_admitted": True, "priority_value": 1},
        "Caster",
        "exit ability",
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
        "resolution:exit",
        "intent:exit",
        "exit ability",
        "standalone_ability_graph",
        {
            "standalone_ability_graph_id": "graph:exit",
            "phase_ids": ["phase:exit"],
            "task_ids": ["task:exit"],
            "executable_task_ids": ["task:exit"],
        },
        source,
        coverage_status="executable",
    )
    rules = RuleBook(
        CanonicalIR(
            "component:standalone-death",
            effects=(exit_effect,),
            ability_tasks=(exit_task, break_task),
            ability_phases=(exit_phase,),
            standalone_ability_graphs=(graph,),
            queue_intents=(intent,),
            queue_resolutions=(resolution,),
            status_callbacks=(callback,),
            status_callback_tasks=(callback_task,),
            hit_profiles=(profile,),
            toughness_emissions=(emission,),
            break_templates=(template,),
        )
    )
    break_source = {
        "attacker_id": "attacker",
        "toughness_emission_id": "toughness",
        "source_task_id": "task:break",
        "hit_profile_id": "profile",
        "source_trace": {"fixture": True},
        "break_template_id": "break",
        "break_template_source": template.source.to_json(),
    }
    status_detail = {
        "instance_id": "status:death",
        "owner_id": "corpse",
        "modifier_name": "component:Deathrattle",
        "behavior_flags": ["Deathrattle"],
        "lifecycle_state": "active",
    }
    corpse = UnitState(
        "corpse",
        "enemy",
        "component:corpse",
        hp=0.0,
        lifecycle_status="defeated",
        flags={
            "broken": True,
            "break_element": "Fire",
            "break_source": break_source,
            "defeat_record": {
                "lifecycle_mutation_id": "death",
                "hp_mutation_id": "lethal",
                "target_id": "corpse",
                "defeated_unit_id": "corpse",
            },
            "status_details": [status_detail],
        },
    )
    state = BattleState(units={"corpse": corpse})
    death_event = GameEvent(
        "unit.defeated",
        source_id="owner",
        target_id="corpse",
        event_id=mutation_backed_event_id("death", "unit.defeated"),
        window="unit.defeated",
        payload={
            "target_id": "corpse",
            "defeated_unit_id": "corpse",
            "lifecycle_mutation_id": "death",
            "hp_mutation_id": "lethal",
        },
    )
    permit, reason = _deathrattle_queue_admission(
        state, callback, callback_task, dict(status_detail), death_event, intent
    )
    assert permit is not None and not reason, reason
    entry = QueueEntry(
        "entry:exit",
        "interrupt_queue",
        "turn_insert_ability",
        "intent:exit",
        "corpse",
        "exit ability",
        ("corpse",),
        {"priority_ordering_admitted": True, "priority_value": 1},
        {},
        queue_window_id="window",
        window_family="insert_ability",
        target_resolution={"ok": True, "target_ids": ["corpse"]},
        owner_alive_state="alive_or_limbo",
        target_alive_state="alive_or_limbo",
        can_run_on_unselectable_target=True,
        deathrattle_admission=permit.to_json(),
    ).to_json()
    state = BattleState(
        units={"corpse": corpse},
        queues={"interrupt_queue": (entry,)},
    )
    return rules, state, entry, resolution, permit


def test_deathrattle_standalone_body_receives_the_admitted_death_instance():
    rules, state, entry, resolution, permit = _standalone_death_fixture()
    plan = QueueSystem().plan_drain(
        state, "interrupt_queue", resolution, rules=rules
    )
    assert plan.ok, plan.blocked_reason
    assert plan.queue_entry["entry_id"] == entry["entry_id"]
    death_instance_id, reason = _standalone_death_instance_id(entry, resolution)
    assert death_instance_id == "death"
    assert not reason, reason

    # The scheduler binding re-checks the entry contract; a borrowed ability
    # name cannot smuggle the death identity into another body.
    borrowed = {
        **entry,
        "deathrattle_admission": replace(
            permit, ability_name="other"
        ).to_json(),
    }
    borrowed_id, borrowed_reason = _standalone_death_instance_id(
        borrowed, resolution
    )
    assert not borrowed_id
    assert "queue_owner_deathrattle_contract_mismatch" in borrowed_reason

    invocation = StandaloneAbilityInvocation(
        graph_id="graph:exit",
        actor_id="corpse",
        target_ids=("corpse",),
        queue_name="interrupt_queue",
        queue_entry_id=entry["entry_id"],
        queue_intent_id="intent:exit",
        queue_resolution_id="resolution:exit",
        death_instance_id=death_instance_id,
    )
    registry = EffectRegistry(StatusSystem(rules))
    ability = AbilityTaskSystem(rules, registry)
    result = ability._execute_admitted_queue_standalone(
        state, invocation=invocation
    )
    assert result.node_results and all(
        node.status == "complete" for node in result.node_results
    ), [node.to_json() for node in result.node_results]
    assert len(result.mutations) == 3
    checked = RuntimeSourceAuditor(rules).validate_execution(
        result.mutations, result.records
    )
    assert checked.ok, checked.to_json()

    # The corpse cleanup never guesses an identity the entry did not admit.
    blocked = ability._execute_admitted_queue_standalone(
        state, invocation=replace(invocation, death_instance_id="")
    )
    assert any(node.status != "complete" for node in blocked.node_results)
    assert blocked.mutations == ()


def test_ordinary_lifecycle_with_protection_field_is_not_the_protected_family():
    source = _source()
    effect = EffectIR(
        "effect:add", "AddModifier", {"standard": {}}, source,
        coverage_status="executable",
    )
    rules = RuleBook(
        CanonicalIR("component:ordinary-add", effects=(effect,))
    )
    detail = {
        "instance_id": "status:ordinary",
        "status_id": "modifier:ordinary",
        "owner_id": "owner",
        "modifier_name": "component:ordinary",
        "lifecycle_state": "active",
        "weakness_protection": ["Physical"],
    }
    lifecycle = {
        "operation": "add",
        "target_id": "owner",
        "status_id": "modifier:ordinary",
        "source_trace": {"effect_id": "effect:add"},
    }
    mutation = Mutation(
        "set",
        ("units", "owner", "flags", "status_details"),
        [],
        [detail],
        "ordinary add of a status that already carries protection",
        "status_system",
        metadata={
            "status_id": "modifier:ordinary",
            "operation": "add",
            "lifecycle_plan": lifecycle,
        },
    )
    record = SettlementRecord(
        "status_lifecycle",
        "status_system",
        mutation_id=mutation.stable_id(),
        process_only=False,
        payload={"operation": "add", "lifecycle_plan": lifecycle},
        trace=lifecycle["source_trace"],
    ).to_json()
    checked = RuntimeSourceAuditor(rules).validate_execution(
        (mutation,), (record,)
    )
    assert checked.ok, checked.to_json()
