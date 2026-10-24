"""Native source-audit checks for the formal forced death and its insert cleanup.

These are component checks around one real TBGD ForceKill leaf and typed queue
IR; no content compilation and no full battle are involved. They cover the
normal producer result, order-independent legal re-association, actual HP /
lifecycle / defeat-record tampering with synchronized mutation ids, missing or
disguised formal effect identity, wrong settlement producers, and the exact
retained-entry/order/causality contract of AbortUnusedInsertAbility.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from hsr.simulator_v8_clean_core.core.model import (
    BattleState,
    Mutation,
    TargetResolution,
    UnitState,
)
from hsr.simulator_v8_clean_core.core.settlement import SettlementRecord
from hsr.simulator_v8_clean_core.core.source_audit import (
    FORCED_DEATH_LIFECYCLE_OPERATIONS,
    RuntimeSourceAuditor,
)
from hsr.simulator_v8_clean_core.ir_types import IRSource
from hsr.simulator_v8_clean_core.rules.ir import (
    CanonicalIR,
    EffectIR,
    QueueIntentIR,
    QueuePriorityIR,
    QueueWindowIR,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.effect import (
    EffectExecutionContext,
    EffectRegistry,
)
from hsr.simulator_v8_clean_core.systems.queue import QueueEntry, QueueSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _effect_coverage_status,
    _effect_payload,
)

_ROOT = Path(__file__).resolve().parents[4]
_TBGD = _ROOT / "turnbasedgamedata-main"
_FORCE_KILL_SOURCE = "Config/ConfigAbility/Common_Additional_Ability.json"
_FORCE_KILL_ABILITY = "Common_Servant_Forcekill"
_UNIT = "child"
_SIBLING = "sibling"
_QUEUE = "turn_insert_ability"
_INTENT = "queue_intent:review:forcekill"
_WINDOW = "queue_window:review:forcekill"
_PRIORITY = "queue_priority:review:forcekill"
_WINDOW_POLICY = {
    "window_family": "insert_ability",
    "dequeue_before_execute": True,
    "drain_via_scheduler": True,
}


def _source(raw_type: str, raw_id: str, json_path: str) -> IRSource:
    return IRSource(_FORCE_KILL_SOURCE, raw_type, raw_id, {"json_path": json_path})


def _force_kill_effect() -> EffectIR:
    """Lower only the fixed Common_Servant_Forcekill leaf, not a full compile."""

    data = json.loads(
        (_TBGD / _FORCE_KILL_SOURCE).read_text(encoding="utf-8")
    )
    ability = next(
        item for item in data["AbilityList"] if item["Name"] == _FORCE_KILL_ABILITY
    )
    raw = ability["OnStart"][0]
    assert raw["$type"].endswith(".ForceKill")
    source = _source(
        raw["$type"],
        f"review:{_FORCE_KILL_ABILITY}",
        f"{_FORCE_KILL_ABILITY}.OnStart[0]",
    )
    payload = _effect_payload(raw, "ForceKill", "")
    effect = EffectIR(
        f"effect:review:{_FORCE_KILL_ABILITY}",
        "ForceKill",
        payload,
        source,
        coverage_status=_effect_coverage_status("ForceKill", payload),
    )
    assert effect.coverage_status == "executable"
    assert effect.payload["standard"]["operation"] == "formal_forced_death"
    return effect


def _muted_force_kill_effect() -> EffectIR:
    """The already admitted double-mute retirement shape, for regression."""

    raw = {
        "$type": "RPG.GameCore.ForceKill",
        "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
        "MuteHpChange": True,
        "MuteAllTriggerDeath": True,
    }
    source = _source(
        raw["$type"], "review:muted_forcekill", "review.muted_forcekill"
    )
    payload = _effect_payload(raw, "ForceKill", "")
    effect = EffectIR(
        "effect:review:muted_forcekill",
        "ForceKill",
        payload,
        source,
        coverage_status=_effect_coverage_status("ForceKill", payload),
    )
    assert effect.payload["standard"]["operation"] == "muted_unit_retirement"
    assert effect.payload["standard"]["blocked_reason"] == ""
    assert effect.coverage_status == "executable"
    return effect


def _queue_rules(effect: EffectIR, *extra_effects: EffectIR) -> RuleBook:
    """Typed minimal component queue IR (not a compiled real rulebook)."""

    source = IRSource(
        "component/ConfigAbility/Review_Queue.json",
        "ValidationSynthetic",
        "review:queue_ir",
        {"negative_or_baseline_fixture": True},
    )
    priority = QueuePriorityIR(
        _PRIORITY,
        "insert_ability",
        "MonsterForceKill",
        70.0,
        source,
        coverage_status="executable",
    )
    intent = QueueIntentIR(
        _INTENT,
        "task:review",
        "callback:review",
        "phase:review",
        "TurnInsertAbility",
        _QUEUE,
        {
            "queue_priority_id": _PRIORITY,
            "priority_key": "MonsterForceKill",
            "priority_value": 70.0,
            "priority_ordering_admitted": True,
        },
        "ModifierOwnerEntity",
        _FORCE_KILL_ABILITY,
        {},
        "ModifierOwnerEntity",
        False,
        {},
        source,
        coverage_status="executable",
        owner_alive_state="alive_or_revivable",
        target_alive_state="alive_or_revivable",
        can_run_on_unselectable_target=True,
    )
    window = QueueWindowIR(
        _WINDOW,
        _INTENT,
        _QUEUE,
        "insert_ability",
        "MonsterForceKill",
        70.0,
        dict(_WINDOW_POLICY),
        source,
        coverage_status="executable",
    )
    return RuleBook(
        CanonicalIR(
            "review-component",
            effects=(effect, *extra_effects),
            queue_intents=(intent,),
            queue_priorities=(priority,),
            queue_windows=(window,),
        )
    )


def _entry(actor_id: str, entry_id: str) -> dict:
    return QueueEntry(
        entry_id,
        _QUEUE,
        _QUEUE,
        _INTENT,
        actor_id,
        _FORCE_KILL_ABILITY,
        (actor_id,),
        {
            "queue_priority_id": _PRIORITY,
            "priority_key": "MonsterForceKill",
            "priority_value": 70.0,
            "priority_ordering_admitted": True,
        },
        {"component": "review"},
        priority_key="MonsterForceKill",
        priority_value=70.0,
        queue_priority_id=_PRIORITY,
        queue_window_id=_WINDOW,
        window_family="insert_ability",
        window_policy=dict(_WINDOW_POLICY),
        owner_id=actor_id,
        owner_alive_state="alive_or_revivable",
        target_alive_state="alive_or_revivable",
        can_run_on_unselectable_target=True,
    ).to_json()


def _produce(
    unit_id: str = _UNIT,
    *,
    with_queue: bool = True,
) -> tuple[EffectIR, RuleBook, object, BattleState]:
    effect = _force_kill_effect()
    rules = _queue_rules(effect)
    units = {
        unit_id: UnitState(
            unit_id, "enemy", "monster:1002040", hp=100.0, max_hp=100.0
        )
    }
    queues: dict[str, tuple[dict, ...]] = {}
    if with_queue:
        queues = {
            _QUEUE: (
                _entry(_SIBLING, "entry:sibling:1"),
                _entry(unit_id, f"entry:{unit_id}:1"),
                _entry(_SIBLING, "entry:sibling:2"),
            )
        }
    state = BattleState(units=units, queues=queues)
    context = EffectExecutionContext(
        state,
        unit_id,
        unit_id,
        target_resolution=TargetResolution(
            requested=(unit_id,),
            legal=(unit_id,),
            selected=(unit_id,),
            rejected=(),
            reason="component",
            source="review",
        ),
    )
    result = EffectRegistry()._execute_formal_forced_death(
        effect, context, effect.payload["standard"]
    )
    return effect, rules, result, state


def _group(result) -> tuple:
    found = {
        mutation.metadata.get("lifecycle_operation"): mutation
        for mutation in result.mutations
        if mutation.metadata.get("lifecycle_operation")
        in FORCED_DEATH_LIFECYCLE_OPERATIONS
    }
    return (
        found["unit_forced_death_hp"],
        found["unit_defeat"],
        found["unit_defeat_record"],
    )


def _queue_mutation(result):
    return next(
        mutation
        for mutation in result.mutations
        if mutation.metadata.get("queue_cleanup_operation")
    )


def _record_for(records, mutation):
    return next(
        record
        for record in records
        if record.get("mutation_id") == mutation.stable_id()
    )


def _relink(records, replacements: dict[str, str]) -> tuple:
    relinked = []
    for record in records:
        copy = dict(record)
        mutation_id = copy.get("mutation_id")
        if mutation_id in replacements:
            copy["mutation_id"] = replacements[mutation_id]
        relinked.append(copy)
    return tuple(relinked)


def _forced_death_record_payload(effect, unit_id, hp, status) -> dict:
    return {
        "unit_id": unit_id,
        "target_alias": effect.payload["standard"]["target_alias"],
        "forced_death_kind": "formal_ability_force_kill",
        "before_hp": hp.before,
        "after_hp": hp.after,
        "lifecycle_mutation_id": status.stable_id(),
        "hp_mutation_id": hp.stable_id(),
        "kill_credit": None,
        "damage": None,
        "effect_id": effect.effect_id,
    }


def _rebuild_forced_death_result(
    effect,
    result,
    *,
    hp_after=None,
    status_before=None,
    defeat_record_after_hp=None,
):
    """Rebuild the producer-shaped group with synchronized ids and records.

    A tamper is only meaningful when every dependent mutation id, metadata copy
    and settlement mutation_id is re-associated consistently, so a rejection
    cannot come from a merely stale id.
    """

    old_hp, old_status, old_record = _group(result)
    old_ids = {
        old_hp.stable_id(): old_hp,
        old_status.stable_id(): old_status,
        old_record.stable_id(): old_record,
    }
    unit_id = old_hp.path[1]
    alias = effect.payload["standard"]["target_alias"]
    effect_source = effect.source.to_json()
    common = {
        "effect_id": effect.effect_id,
        "effect_source": effect_source,
        "source_trace": effect_source,
        "forced_death_kind": "formal_ability_force_kill",
        "forced_death_target_alias": alias,
    }
    hp = replace(
        old_hp,
        after=old_hp.after if hp_after is None else hp_after,
        metadata={**common, "lifecycle_operation": "unit_forced_death_hp"},
    )
    before_value = "active" if status_before is None else status_before
    base_record = {
        "target_id": unit_id,
        "defeated_unit_id": unit_id,
        "target_before_hp": hp.before,
        "target_after_hp": (
            hp.after if defeat_record_after_hp is None else defeat_record_after_hp
        ),
        "hp_mutation_id": hp.stable_id(),
        "forced_death_kind": "formal_ability_force_kill",
        "forced_death_target_alias": alias,
        "effect_id": effect.effect_id,
        "effect_source": effect_source,
        "source_trace": effect_source,
    }
    status = replace(
        old_status,
        before=before_value,
        metadata={
            **common,
            "lifecycle_operation": "unit_defeat",
            "lifecycle_status_before": before_value,
            "lifecycle_status_after": "defeated",
            "hp_mutation_id": hp.stable_id(),
            "defeat_record": base_record,
        },
    )
    typed_record = {**base_record, "lifecycle_mutation_id": status.stable_id()}
    record_mutation = replace(
        old_record,
        after=typed_record,
        metadata={
            **common,
            "lifecycle_operation": "unit_defeat_record",
            "lifecycle_mutation_id": status.stable_id(),
            "hp_mutation_id": hp.stable_id(),
            "defeat_record": typed_record,
        },
    )
    payload = _forced_death_record_payload(effect, unit_id, hp, status)
    trace = effect_source
    group_records = (
        SettlementRecord(
            "unit_forced_death_hp",
            "effect_system",
            hp.stable_id(),
            False,
            payload,
            trace,
        ).to_json(),
        SettlementRecord(
            "unit_forced_death",
            "effect_system",
            status.stable_id(),
            False,
            payload,
            trace,
        ).to_json(),
        SettlementRecord(
            "unit_forced_death_record",
            "effect_system",
            record_mutation.stable_id(),
            False,
            payload,
            trace,
        ).to_json(),
    )
    mutations = (hp, status, record_mutation) + tuple(
        mutation
        for mutation in result.mutations
        if mutation.metadata.get("lifecycle_operation")
        not in FORCED_DEATH_LIFECYCLE_OPERATIONS
    )
    records = group_records + tuple(
        record
        for record in result.records
        if record.get("mutation_id") not in old_ids
    )
    return mutations, records


def test_native_forced_death_and_cleanup_pass_and_legal_reassociation_is_stable():
    effect, rules, result, _state = _produce()
    auditor = RuntimeSourceAuditor(rules)
    audit = auditor.validate_execution(result.mutations, result.records)
    assert audit.ok, [violation.to_json() for violation in audit.violations]

    hp, status, record_mutation = _group(result)
    assert hp.path == ("units", _UNIT, "hp")
    assert hp.after == 0
    assert status.path == ("units", _UNIT, "lifecycle_status")
    assert status.after == "defeated"
    assert record_mutation.after["target_id"] == _UNIT
    assert record_mutation.after["hp_mutation_id"] == hp.stable_id()
    assert record_mutation.after["lifecycle_mutation_id"] == status.stable_id()
    assert record_mutation.after["target_after_hp"] == 0

    cleanup = _queue_mutation(result)
    assert cleanup.path == ("queues", _QUEUE)
    assert [item["entry_id"] for item in cleanup.before] == [
        "entry:sibling:1",
        f"entry:{_UNIT}:1",
        "entry:sibling:2",
    ]
    assert [item["entry_id"] for item in cleanup.after] == [
        "entry:sibling:1",
        "entry:sibling:2",
    ]
    assert cleanup.metadata["queue_terminal_plan"]["entry_id"] == (
        f"entry:{_UNIT}:1"
    )

    # Records are associated by stable id, not by list position: the same
    # committed result in another order must still pass.
    reassociated = auditor.validate_execution(
        tuple(reversed(result.mutations)), tuple(reversed(result.records))
    )
    assert reassociated.ok, [
        violation.to_json() for violation in reassociated.violations
    ]


@pytest.mark.parametrize(
    "tamper",
    (
        {"hp_after": 99.0},
        {"status_before": "limbo"},
        {"defeat_record_after_hp": 99.0},
    ),
)
def test_forced_death_group_tamper_with_synchronized_ids_is_rejected(tamper):
    effect, rules, result, _state = _produce(with_queue=False)
    mutations, records = _rebuild_forced_death_result(effect, result, **tamper)
    assert any(
        mutation.stable_id() not in {item.stable_id() for item in result.mutations}
        for mutation in mutations[:3]
    )
    audit = RuntimeSourceAuditor(rules).validate_execution(mutations, records)
    assert not audit.ok
    assert any(
        violation.reason == "forced_death_group_inconsistent"
        for violation in audit.violations
    ), [violation.reason for violation in audit.violations]


def test_forced_death_labels_and_effect_identity_cannot_fall_back_to_generic_audit():
    effect, rules, result, _state = _produce(with_queue=False)
    auditor = RuntimeSourceAuditor(rules)
    hp, status, record_mutation = _group(result)

    # 1) The role labels are removed while the formal effect, written values and
    #    native settlement records stay intact.
    stripped = []
    for mutation in (hp, status, record_mutation):
        metadata = {
            key: value
            for key, value in mutation.metadata.items()
            if key not in {
                "lifecycle_operation",
                "forced_death_kind",
                "forced_death_target_alias",
            }
        }
        stripped.append(replace(mutation, metadata=metadata))
    replacements = {
        old.stable_id(): new.stable_id()
        for old, new in zip((hp, status, record_mutation), stripped)
    }
    mutations = tuple(stripped) + tuple(
        mutation
        for mutation in result.mutations
        if mutation.metadata.get("lifecycle_operation")
        not in FORCED_DEATH_LIFECYCLE_OPERATIONS
    )
    audit = auditor.validate_execution(
        mutations, _relink(result.records, replacements)
    )
    assert not audit.ok
    assert any(
        violation.reason
        == "forced_death_lifecycle_operation_missing_or_unknown"
        for violation in audit.violations
    ), [violation.reason for violation in audit.violations]

    # 2) A forced-death role label disguises a muted retirement definition: the
    #    label alone must never admit it through the generic effect audit.
    muted = _muted_force_kill_effect()
    mixed_rules = _queue_rules(effect, muted)
    muted_source = muted.source.to_json()
    disguised = replace(
        hp,
        metadata={
            **hp.metadata,
            "effect_id": muted.effect_id,
            "effect_source": muted_source,
            "source_trace": muted_source,
        },
    )
    mutations = (disguised, status, record_mutation)
    audit = RuntimeSourceAuditor(mixed_rules).validate_execution(
        mutations, _relink(result.records, {hp.stable_id(): disguised.stable_id()})
    )
    assert not audit.ok
    assert any(
        violation.reason == "forced_death_formal_effect_definition_mismatch"
        for violation in audit.violations
    ), [violation.reason for violation in audit.violations]


def test_wrong_settlement_producer_for_forced_death_is_rejected():
    effect, rules, result, _state = _produce(with_queue=False)
    auditor = RuntimeSourceAuditor(rules)
    hp, _status, _record = _group(result)
    hp_record = _record_for(result.records, hp)

    # 1) A native-looking record that claims the damage producer.
    forged_source = {**hp_record, "source": "damage_system"}
    records = tuple(
        forged_source if record is hp_record else record
        for record in result.records
    )
    audit = auditor.validate_execution(result.mutations, records)
    assert not audit.ok
    assert any(
        violation.reason == "forced_death_settlement_producer_mismatch"
        for violation in audit.violations
    ), [violation.reason for violation in audit.violations]

    # 2) The same record type/payload from another unit's real forced death,
    #    re-associated to this mutation id.
    other_effect, _other_rules, other_result, _state = _produce(
        unit_id="other", with_queue=False
    )
    assert other_effect.effect_id == effect.effect_id
    other_hp = _group(other_result)[0]
    foreign = dict(_record_for(other_result.records, other_hp))
    foreign["mutation_id"] = hp.stable_id()
    records = tuple(
        foreign if record is hp_record else record
        for record in result.records
    )
    audit = auditor.validate_execution(result.mutations, records)
    assert not audit.ok
    assert any(
        violation.reason == "forced_death_settlement_producer_mismatch"
        for violation in audit.violations
    ), [violation.reason for violation in audit.violations]

    # 3) The process-only flag cannot stand in for the producer's own record.
    process_only = {**hp_record, "process_only": True}
    records = tuple(
        process_only if record is hp_record else record
        for record in result.records
    )
    audit = auditor.validate_execution(result.mutations, records)
    assert not audit.ok
    assert any(
        violation.reason == "forced_death_settlement_producer_mismatch"
        for violation in audit.violations
    ), [violation.reason for violation in audit.violations]


def test_queue_cleanup_requires_exact_retained_entries_and_order():
    effect, rules, result, _state = _produce()
    auditor = RuntimeSourceAuditor(rules)
    cleanup = _queue_mutation(result)
    cleanup_record = _record_for(result.records, cleanup)

    def audit_after(after):
        altered = replace(cleanup, after=after)
        records = tuple(
            (
                {**cleanup_record, "mutation_id": altered.stable_id()}
                if record is cleanup_record
                else record
            )
            for record in result.records
        )
        mutations = tuple(
            altered if mutation is cleanup else mutation
            for mutation in result.mutations
        )
        return auditor.validate_execution(mutations, records)

    # 1) A retained sibling's actor identity is rewritten while the removed
    #    entry and the native settlement record are kept and re-associated.
    rewritten = [dict(item) for item in cleanup.after]
    rewritten[0]["actor_id"] = "wrong-actor"
    audit = audit_after(rewritten)
    assert not audit.ok
    assert any(
        violation.reason == "queue_cleanup_not_exact_single_entry_removal"
        for violation in audit.violations
    ), [violation.reason for violation in audit.violations]

    # 2) The retained sibling entries keep their content but lose their order.
    swapped = [dict(cleanup.after[1]), dict(cleanup.after[0])]
    audit = audit_after(swapped)
    assert not audit.ok
    assert any(
        violation.reason == "queue_cleanup_not_exact_single_entry_removal"
        for violation in audit.violations
    ), [violation.reason for violation in audit.violations]

    # 3) A native-looking terminal record that claims another producer.
    def audit_record(record):
        records = tuple(
            record if item is cleanup_record else item
            for item in result.records
        )
        return auditor.validate_execution(result.mutations, records)

    forged = {**cleanup_record, "source": "summon_system"}
    audit = audit_record(forged)
    assert not audit.ok
    assert any(
        violation.reason == "queue_cleanup_settlement_producer_mismatch"
        for violation in audit.violations
    ), [violation.reason for violation in audit.violations]


def test_queue_cleanup_causality_must_be_the_same_forced_death():
    effect, rules, result, state = _produce()
    auditor = RuntimeSourceAuditor(rules)
    group_mutations = _group(result)
    group_records = tuple(
        record
        for record in result.records
        if record.get("mutation_id")
        in {mutation.stable_id() for mutation in group_mutations}
    )

    # 1) The producer can remove another unit's entries; that exact removal is
    #    still not the cleanup of this forced death.
    mutations, _events, records = QueueSystem().abort_unused_insert_entries_for_unit(
        state,
        _SIBLING,
        reason="queue_action_actor_unit_defeated",
        source_trace={
            "forced_death_effect_id": effect.effect_id,
            "forced_death_source": effect.source.to_json(),
        },
    )
    assert mutations
    audit = auditor.validate_execution(
        (*group_mutations, *mutations), (*group_records, *records)
    )
    assert not audit.ok
    assert any(
        violation.reason == "forced_death_group_missing_or_ambiguous"
        for violation in audit.violations
    ), [violation.reason for violation in audit.violations]

    # 2) The cleanup mutation alone, without its same-execution death group, is
    #    not evidence of a formal forced death.
    cleanup = _queue_mutation(result)
    cleanup_record = _record_for(result.records, cleanup)
    audit = auditor.validate_execution((cleanup,), (cleanup_record,))
    assert not audit.ok
    assert any(
        violation.reason == "forced_death_group_missing_or_ambiguous"
        for violation in audit.violations
    ), [violation.reason for violation in audit.violations]

    # 3) A missing or unknown cleanup operation can never fall back to the
    #    generic terminal removal; the carried ForceKill provenance still
    #    selects the strict cleanup contract.
    for unknown_operation in ("", "rewrite_all_queues"):
        metadata = {
            key: value
            for key, value in cleanup.metadata.items()
            if key != "queue_cleanup_operation"
        }
        if unknown_operation:
            metadata["queue_cleanup_operation"] = unknown_operation
        stripped = replace(cleanup, metadata=metadata)
        records = tuple(
            (
                {**cleanup_record, "mutation_id": stripped.stable_id()}
                if record is cleanup_record
                else record
            )
            for record in result.records
        )
        mutations = tuple(
            stripped if mutation is cleanup else mutation
            for mutation in result.mutations
        )
        audit = auditor.validate_execution(mutations, records)
        assert not audit.ok
        assert any(
            violation.reason == "queue_cleanup_operation_not_admitted"
            for violation in audit.violations
        ), [violation.reason for violation in audit.violations]

    # 4) The terminal plan still declares the forced-death provenance even if
    #    the top-level cleanup label and trace marker are dropped.
    stripped_trace = {
        key: value
        for key, value in cleanup.metadata["source_trace"].items()
        if key not in {"forced_death_effect_id", "forced_death_source"}
    }
    hidden = replace(
        cleanup,
        metadata={
            **{
                key: value
                for key, value in cleanup.metadata.items()
                if key != "queue_cleanup_operation"
            },
            "source_trace": stripped_trace,
        },
    )
    records = tuple(
        (
            {**cleanup_record, "mutation_id": hidden.stable_id()}
            if record is cleanup_record
            else record
        )
        for record in result.records
    )
    mutations = tuple(
        hidden if mutation is cleanup else mutation
        for mutation in result.mutations
    )
    audit = auditor.validate_execution(mutations, records)
    assert not audit.ok
    assert any(
        violation.reason == "queue_cleanup_operation_not_admitted"
        for violation in audit.violations
    ), [violation.reason for violation in audit.violations]


def test_muted_retirement_and_other_effect_mutations_keep_generic_admission():
    muted = _muted_force_kill_effect()
    rules = RuleBook(
        CanonicalIR("review-component", effects=(muted,))
    )
    mutation = Mutation(
        "set",
        ("units", _UNIT, "hp"),
        100.0,
        0.0,
        "begin forced servant retirement",
        "effect_system",
        metadata={
            "effect_id": muted.effect_id,
            "effect_source": muted.source.to_json(),
        },
    )
    record = SettlementRecord(
        "unit_retirement",
        "effect_system",
        mutation.stable_id(),
        False,
        {"target_id": _UNIT},
        muted.source.to_json(),
    ).to_json()
    audit = RuntimeSourceAuditor(rules).validate_execution((mutation,), (record,))
    assert audit.ok, [violation.to_json() for violation in audit.violations]


def _muted_producer_result(effect: EffectIR, flags: dict) -> object:
    """Run the real double-mute ForceKill producer on one minimal unit."""

    unit = UnitState(
        _UNIT, "enemy", "monster:1002040", hp=100.0, max_hp=100.0, flags=flags
    )
    state = BattleState(units={_UNIT: unit})
    expression = object()
    registry = EffectRegistry()
    registry.status_system = SimpleNamespace(
        rules=SimpleNamespace(target_expression=lambda _target_id: expression)
    )
    registry.targets = SimpleNamespace(
        resolve_target_expression=lambda *_args, **_kwargs: SimpleNamespace(
            resolved=True,
            target_ids=(_UNIT,),
            blocked_reason="",
            rng_events=(),
        )
    )
    context = EffectExecutionContext(
        state,
        _UNIT,
        _UNIT,
        target_resolution=TargetResolution(
            requested=(_UNIT,),
            legal=(_UNIT,),
            selected=(_UNIT,),
            rejected=(),
            reason="component",
            source="review",
        ),
    )
    return registry._execute_force_kill(effect, context)


def test_muted_retirement_producer_output_is_not_an_actual_death_group():
    muted = _muted_force_kill_effect()
    rules = RuleBook(CanonicalIR("review-component", effects=(muted,)))

    # A retired servant legitimately reaches HP 0 and defeated without any
    # typed defeat record; the actual-write family detection must stay quiet.
    servant = _muted_producer_result(muted, {"summon_kind": "servant"})
    assert [mutation.path for mutation in servant.mutations] == [
        ("units", _UNIT, "hp"),
        ("units", _UNIT, "lifecycle_status"),
        ("units", _UNIT, "flags", "forced_retirement"),
    ]
    assert [mutation.after for mutation in servant.mutations] == [0.0, "defeated", True]
    audit = RuntimeSourceAuditor(rules).validate_execution(
        servant.mutations, servant.records
    )
    assert audit.ok, [violation.to_json() for violation in audit.violations]

    # The battle-event exit writes lifecycle "removed" plus the removed record,
    # which is not a death write either. (Its generic effect-metadata gap is a
    # pre-existing producer/audit difference outside this family detection.)
    battle_event = _muted_producer_result(muted, {"entity_type": "battle_event"})
    assert [mutation.path for mutation in battle_event.mutations] == [
        ("units", _UNIT, "lifecycle_status"),
        ("units", _UNIT, "flags", "removed_record"),
    ]
    assert [mutation.after for mutation in battle_event.mutations][0] == "removed"
    audit = RuntimeSourceAuditor(rules).validate_execution(
        battle_event.mutations, battle_event.records
    )
    assert not any(
        violation.reason.startswith("forced_death")
        for violation in audit.violations
    ), [violation.reason for violation in audit.violations]


def test_effect_reference_swap_with_stripped_labels_cannot_hide_actual_death_group():
    effect, rules, result, _state = _produce()
    assert RuntimeSourceAuditor(rules).validate_execution(
        result.mutations, result.records
    ).ok
    muted = _muted_force_kill_effect()
    muted_source = muted.source.to_json()

    def swapped_execution(*, keep_hp: bool) -> tuple:
        replaced = {}
        for mutation in _group(result):
            metadata = {
                key: value
                for key, value in mutation.metadata.items()
                if key not in {
                    "lifecycle_operation",
                    "forced_death_kind",
                    "forced_death_target_alias",
                }
            }
            metadata.update(
                effect_id=muted.effect_id,
                effect_source=muted_source,
                source_trace=muted_source,
            )
            after = mutation.after
            if not keep_hp and mutation.path[-1] == "hp":
                after = 99.0
            replaced[mutation.stable_id()] = replace(
                mutation, metadata=metadata, after=after
            )
        mutations = tuple(
            replaced.get(mutation.stable_id(), mutation)
            for mutation in result.mutations
        )
        records = _relink(
            result.records,
            {old: new.stable_id() for old, new in replaced.items()},
        )
        # The queue cleanup is unrelated to this death-group case.
        mutations = tuple(
            mutation for mutation in mutations if mutation.source == "effect_system"
        )
        mutation_ids = {mutation.stable_id() for mutation in mutations}
        return mutations, tuple(
            record for record in records if record.get("mutation_id") in mutation_ids
        )

    swapped_rules = _queue_rules(effect, muted)
    for keep_hp in (False, True):
        mutations, records = swapped_execution(keep_hp=keep_hp)
        audit = RuntimeSourceAuditor(swapped_rules).validate_execution(mutations, records)
        assert not audit.ok
        flagged = {
            violation.mutation_id
            for violation in audit.violations
            if violation.reason
            == "forced_death_actual_write_effect_definition_mismatch"
        }
        assert flagged == {mutation.stable_id() for mutation in mutations}, [
            violation.reason for violation in audit.violations
        ]


def test_native_forced_death_record_and_settlement_copy_types_are_strict():
    effect, rules, result, _state = _produce(with_queue=False)
    hp, _status, record_mutation = _group(result)
    assert hp.before == 100.0 and hp.after == 0
    native_record = _record_for(result.records, record_mutation)
    assert native_record["payload"]["before_hp"] == 100.0
    assert record_mutation.metadata["defeat_record"]["target_before_hp"] == 100.0

    # 1) The typed defeat_record copy inside the mutation metadata changes type
    #    (100.0 -> 100); the mutation id and its record are re-associated.
    metadata = dict(record_mutation.metadata)
    defeat_record = dict(metadata["defeat_record"])
    defeat_record["target_before_hp"] = 100
    metadata["defeat_record"] = defeat_record
    altered = replace(record_mutation, metadata=metadata)
    records = tuple(
        (
            {**native_record, "mutation_id": altered.stable_id()}
            if record is native_record
            else record
        )
        for record in result.records
    )
    mutations = tuple(
        altered if mutation is record_mutation else mutation
        for mutation in result.mutations
    )
    audit = RuntimeSourceAuditor(rules).validate_execution(mutations, records)
    assert not audit.ok
    assert any(
        violation.reason == "forced_death_group_inconsistent"
        for violation in audit.violations
    ), [violation.reason for violation in audit.violations]

    # 2) The native settlement copy changes only the JSON type of before_hp.
    tampered = {
        **native_record,
        "payload": {**native_record["payload"], "before_hp": 100},
    }
    records = tuple(
        tampered if record is native_record else record for record in result.records
    )
    audit = RuntimeSourceAuditor(rules).validate_execution(result.mutations, records)
    assert not audit.ok
    assert any(
        violation.reason == "forced_death_settlement_producer_mismatch"
        for violation in audit.violations
    ), [violation.reason for violation in audit.violations]


def test_retained_sibling_boolean_as_number_is_rejected():
    effect, rules, result, _state = _produce()
    cleanup = _queue_mutation(result)
    cleanup_record = _record_for(result.records, cleanup)
    after = json.loads(json.dumps(cleanup.after))
    assert after[0]["priority_source"]["priority_ordering_admitted"] is True
    after[0]["priority_source"]["priority_ordering_admitted"] = 1
    altered = replace(cleanup, after=after)
    records = tuple(
        (
            {**cleanup_record, "mutation_id": altered.stable_id()}
            if record is cleanup_record
            else record
        )
        for record in result.records
    )
    mutations = tuple(
        altered if mutation is cleanup else mutation
        for mutation in result.mutations
    )
    audit = RuntimeSourceAuditor(rules).validate_execution(mutations, records)
    assert not audit.ok
    assert any(
        violation.reason == "queue_cleanup_not_exact_single_entry_removal"
        for violation in audit.violations
    ), [violation.reason for violation in audit.violations]
