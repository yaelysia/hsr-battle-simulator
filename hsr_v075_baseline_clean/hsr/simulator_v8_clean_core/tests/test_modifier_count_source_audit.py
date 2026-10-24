"""Exact-diff audit for the native independent-count status producer.

The positive fixture lowers one real ability file and executes the registered
March 7th counter tasks. The negative cases tamper only the produced mutation
and settlement copies (with re-associated ids), so no second BattleSession or
full rulebook is needed.
"""
from dataclasses import dataclass, replace
import json
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.ir_types import IRSource
from hsr.simulator_v8_clean_core.rules.expression_ir import NUMERIC_EXPRESSION_SCHEMA
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, EffectIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry
from hsr.simulator_v8_clean_core.systems.status import StatusInstance, StatusSystem
from hsr.simulator_v8_clean_core.tbgd.adopted_modifier_counts import MODIFIER, SOURCE
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering,
    _effect_coverage_status,
    _effect_payload,
)

CONSUME_PATH = "$.AbilityList[8].OnStart[10]"
RESET_PATH = (
    "$.AbilityList[7].Modifiers.MAvatar_March7th_00_Passive._CallbackList[0]"
    ".CallbackConfig[1].FailedTaskList[0]"
)
COUNT_HASH = "1299003598"
_UNSET = object()


@dataclass(frozen=True)
class _CountFixture:
    registry: EffectRegistry
    auditor: RuntimeSourceAuditor
    effects: dict[str, EffectIR]


@pytest.fixture(scope="module")
def count_fixture() -> _CountFixture:
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    document = json.loads((root / SOURCE).read_text())
    lowering = TBGDLowering(root)
    lowered = lowering._lower_ability_file(root / SOURCE, {}, ability_file_order=0)
    consume_source = IRSource(
        SOURCE,
        "AbilityTask",
        f"count-audit:{CONSUME_PATH}",
        {"json_path": CONSUME_PATH},
    )
    consume_payload = _effect_payload(
        document["AbilityList"][8]["OnStart"][10],
        "SetModifierValue",
        "",
        source=consume_source,
    )
    assert _effect_coverage_status("SetModifierValue", consume_payload) == "executable"
    reset_effects = [
        effect
        for effect in lowered.effects
        if effect.opcode == "SetModifierValue"
        and effect.source.evidence.get("json_path") == RESET_PATH
    ]
    assert len(reset_effects) == 1
    reset_effect = reset_effects[0]
    assert reset_effect.coverage_status == "executable"
    assert reset_effect.payload["standard"]["value_kind"] == "independent_count"
    effects: dict[str, EffectIR] = {
        "consume": EffectIR(
            CONSUME_PATH,
            "SetModifierValue",
            consume_payload,
            consume_source,
            "executable",
        ),
        "reset": reset_effect,
    }

    layer_raw = {
        "$type": "RPG.GameCore.SetModifierValue",
        "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
        "ModifierName": {"Value": "fixture_layers"},
        "ValueType": "Layer",
        "ModifyFunction": "Set",
        "Value": {"IsDynamic": False, "FixedValue": {"Value": 9}},
    }
    layer_payload = _effect_payload(layer_raw, "SetModifierValue", "")
    assert _effect_coverage_status("SetModifierValue", layer_payload) == "executable"
    effects["layer"] = EffectIR(
        "fixture:layers",
        "SetModifierValue",
        layer_payload,
        IRSource("fixture", "AbilityTask", "layers"),
        "executable",
    )

    rules = RuleBook(
        CanonicalIR(
            "modifier-count-audit",
            entities=tuple(lowered.entities),
            effects=tuple(effects.values()),
        )
    )
    return _CountFixture(
        registry=EffectRegistry(StatusSystem(rules)),
        auditor=RuntimeSourceAuditor(rules),
        effects=effects,
    )


def _status_detail(
    instance_id: str,
    *,
    stacks: int,
    caster_id: str = "owner",
    source_id: str = "component:source",
    dynamic_amount: float | None = None,
) -> dict:
    dynamic_values = (
        {"__by_hash": {COUNT_HASH: dynamic_amount}}
        if dynamic_amount is not None
        else {}
    )
    return StatusInstance(
        instance_id,
        "modifier:" + MODIFIER,
        MODIFIER,
        "owner",
        source_id,
        caster_id,
        stacks=stacks,
        max_stacks=None,
        stack_policy="independent_count",
        source_trace={"origin": "component"},
        dynamic_values=dynamic_values,
    ).to_json()


def _count_state(*, stacks: int = 2, dynamic_amount: float | None = None) -> BattleState:
    selected = _status_detail(
        "counter:1",
        stacks=stacks,
        dynamic_amount=dynamic_amount,
    )
    sibling = _status_detail(
        "counter:2",
        stacks=5,
        caster_id="other_caster",
        source_id="component:source2",
    )
    other = StatusInstance(
        "other:1",
        "modifier:other",
        "other",
        "owner",
        "component:other",
        "owner",
    ).to_json()
    return BattleState(
        units={
            "owner": UnitState(
                "owner",
                "ally",
                "avatar:1001",
                statuses=(selected["status_id"], other["status_id"]),
                flags={"status_details": [selected, sibling, other]},
            )
        }
    )


def _layer_state() -> BattleState:
    detail = StatusInstance(
        "layers:1",
        "modifier:fixture_layers",
        "fixture_layers",
        "owner",
        "component:layers",
        "owner",
        max_stacks=3,
        stack_policy="additive_stack",
    ).to_json()
    return BattleState(
        units={
            "owner": UnitState(
                "owner",
                "ally",
                "avatar:1001",
                statuses=(detail["status_id"],),
                flags={"status_details": [detail]},
            )
        }
    )


def _run(fixture: _CountFixture, key: str, state: BattleState):
    result = fixture.registry.execute(
        fixture.effects[key],
        EffectExecutionContext(state, "owner", "count-audit-source", owner_id="owner"),
    )
    assert not result.unsupported, result.unsupported
    return result


def _program_count_fixture(
    fixture: _CountFixture, instructions: list[dict]
) -> _CountFixture:
    payload = _thaw(fixture.effects["consume"].payload)
    standard = payload["standard"]
    standard.pop("adopted_rule_source", None)
    standard["amount"] = {
        "schema_version": NUMERIC_EXPRESSION_SCHEMA,
        "kind": "program",
        "supported": True,
        "instructions": instructions,
    }
    source = IRSource("component", "AbilityTask", "program-count")
    effect = EffectIR(
        "component:program-count",
        "SetModifierValue",
        payload,
        source,
        "executable",
    )
    rules = RuleBook(replace(fixture.auditor.rules.ir, effects=(effect,)))
    return replace(
        fixture,
        registry=EffectRegistry(StatusSystem(rules)),
        auditor=RuntimeSourceAuditor(rules),
        effects={"program": effect},
    )


def _audit(fixture: _CountFixture, result):
    return fixture.auditor.validate_execution(result.mutations, result.records)


def _details_index(result) -> int:
    indices = [
        index
        for index, mutation in enumerate(result.mutations)
        if mutation.path == ("units", "owner", "flags", "status_details")
    ]
    assert len(indices) == 1
    return indices[0]


def _thaw(value):
    return json.loads(json.dumps(value))


def _reaudit(
    fixture: _CountFixture,
    result,
    *,
    after=_UNSET,
    metadata=_UNSET,
    record_payload=_UNSET,
    record_trace=_UNSET,
    record_overrides: dict | None = None,
    mutation_id: str | None = None,
):
    index = _details_index(result)
    original = result.mutations[index]
    changes = {}
    if after is not _UNSET:
        changes["after"] = after
    if metadata is not _UNSET:
        changes["metadata"] = metadata
    if mutation_id is not None:
        changes["mutation_id"] = mutation_id
    changed = replace(original, **changes)
    old_id = original.stable_id()
    new_id = changed.stable_id()
    mutations = tuple(
        changed if position == index else mutation
        for position, mutation in enumerate(result.mutations)
    )
    records = []
    for record in result.records:
        if record.get("mutation_id") == old_id:
            record = {**record, "mutation_id": new_id}
            if record_payload is not _UNSET:
                record["payload"] = record_payload
            if record_trace is not _UNSET:
                record["trace"] = record_trace
            if record_overrides:
                record.update(record_overrides)
        records.append(record)
    return mutations, tuple(records)


def _assert_count_rejected(fixture: _CountFixture, mutations, records, *reasons: str) -> None:
    audit = fixture.auditor.validate_execution(mutations, records)
    actual = {violation.reason for violation in audit.violations}
    assert not audit.ok, actual
    assert actual & set(reasons), actual


def test_real_counter_consume_and_reset_pass_exact_native_settlement(count_fixture):
    consumed = _run(count_fixture, "consume", _count_state(stacks=2))
    audit = _audit(count_fixture, consumed)
    assert audit.ok, [violation.reason for violation in audit.violations]
    mutation = consumed.mutations[_details_index(consumed)]
    before, after = mutation.before, mutation.after
    assert [detail["stacks"] for detail in after] == [1, 5, 1]
    assert after[1] == before[1] and after[2] == before[2]
    assert after[0]["modifiers"] == before[0]["modifiers"]
    assert after[0]["dynamic_values"] == before[0]["dynamic_values"]
    record = next(
        record
        for record in consumed.records
        if record.get("mutation_id") == mutation.stable_id()
    )
    assert record["payload"] == {
        "operation": "modify_modifier_count",
        "status_instance_id": "counter:1",
        "before": 2,
        "after": 1,
    }
    assert record["process_only"] is False and record["source"] == "status_system"

    restored = _run(count_fixture, "reset", _count_state(stacks=1, dynamic_amount=2.0))
    audit = _audit(count_fixture, restored)
    assert audit.ok, [violation.reason for violation in audit.violations]
    restored_mutation = restored.mutations[_details_index(restored)]
    assert restored_mutation.after[0]["stacks"] == 2
    assert restored_mutation.after[1] == restored_mutation.before[1]
    assert restored_mutation.after[0]["source_id"] == "component:source"

    idempotent = _run(count_fixture, "reset", _count_state(stacks=2, dynamic_amount=2.0))
    audit = _audit(count_fixture, idempotent)
    assert audit.ok, [violation.reason for violation in audit.violations]
    idempotent_mutation = idempotent.mutations[_details_index(idempotent)]
    assert idempotent_mutation.before == idempotent_mutation.after


def test_real_count_reaching_zero_removes_only_selected_instance(count_fixture):
    result = _run(count_fixture, "reset", _count_state(stacks=2, dynamic_amount=0.0))
    audit = _audit(count_fixture, result)
    assert audit.ok, [violation.reason for violation in audit.violations]
    mutation = result.mutations[_details_index(result)]
    before, after = mutation.before, mutation.after
    assert [detail["instance_id"] for detail in after] == ["counter:2", "other:1"]
    assert after == before[1:]
    statuses = next(
        item for item in result.mutations if item.path == ("units", "owner", "statuses")
    )
    assert statuses.before == statuses.after
    record = next(
        record
        for record in result.records
        if record.get("mutation_id") == mutation.stable_id()
    )
    assert record["record_type"] == "status_stack_reduce_remove"
    assert record["process_only"] is False
    assert record["payload"]["removed_detail"] == before[0]

    consumed_to_zero = _run(count_fixture, "consume", _count_state(stacks=1))
    audit = _audit(count_fixture, consumed_to_zero)
    assert audit.ok, [violation.reason for violation in audit.violations]
    consumed_mutation = consumed_to_zero.mutations[_details_index(consumed_to_zero)]
    assert [detail["instance_id"] for detail in consumed_mutation.after] == ["counter:2", "other:1"]


def test_count_update_rejects_tampered_after_values_and_numeric_summary(count_fixture):
    result = _run(count_fixture, "consume", _count_state(stacks=2))
    original = result.mutations[_details_index(result)]

    after = _thaw(original.after)
    after[0]["stacks"] = 999
    mutations, records = _reaudit(count_fixture, result, after=after)
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_update_diff_mismatch",
        "modifier_count_stack_plan_mismatch",
    )

    metadata = _thaw(original.metadata)
    fixed_997 = {
        "schema_version": "hsr.numeric_expression.v1",
        "kind": "fixed",
        "value": 997.0,
        "supported": True,
    }
    metadata["standard"] = {**metadata["standard"], "amount": fixed_997}
    metadata["amount"] = 997.0
    metadata["numeric_evaluation"] = {**metadata["numeric_evaluation"], "value": 997.0}
    metadata["stack_plan"] = {"stacks_before": 2, "stacks_after": 999}
    trace = metadata["lifecycle_plan"]["source_trace"]
    trace["standard"] = metadata["standard"]
    trace["amount"] = 997.0
    trace["numeric_evaluation"] = metadata["numeric_evaluation"]
    trace["stack_plan"] = metadata["stack_plan"]
    disguised_payload = {
        "operation": "modify_modifier_count",
        "status_instance_id": "counter:1",
        "before": 2,
        "after": 999,
    }
    mutations, records = _reaudit(
        count_fixture,
        result,
        after=after,
        metadata=metadata,
        record_payload=disguised_payload,
        record_trace=trace,
    )
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_trace_mismatch",
        "modifier_count_fixed_amount_mismatch",
    )


def test_count_update_rejects_settlement_producer_and_copy_disguise(count_fixture):
    result = _run(count_fixture, "consume", _count_state(stacks=2))
    original = result.mutations[_details_index(result)]
    record = next(
        record
        for record in result.records
        if record.get("mutation_id") == original.stable_id()
    )

    for overrides in (
        {"source": "effect_system"},
        {"record_type": "status_stack"},
        {"process_only": True},
    ):
        mutations, records = _reaudit(
            count_fixture,
            result,
            record_overrides=overrides,
        )
        _assert_count_rejected(
            count_fixture,
            mutations,
            records,
            "modifier_count_settlement_mismatch",
        )

    payload = _thaw(record["payload"])
    payload["status_instance_id"] = "counter:2"
    mutations, records = _reaudit(
        count_fixture,
        result,
        record_payload=payload,
    )
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_settlement_mismatch",
    )

    metadata = _thaw(original.metadata)
    metadata["stack_plan"] = {"stacks_before": 2, "stacks_after": 999}
    trace = metadata["lifecycle_plan"]["source_trace"]
    trace["stack_plan"] = metadata["stack_plan"]
    mutations, records = _reaudit(
        count_fixture,
        result,
        metadata=metadata,
        record_trace=trace,
    )
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_stack_plan_mismatch",
    )

    payload = _thaw(record["payload"])
    payload["before"] = 3
    mutations, records = _reaudit(
        count_fixture,
        result,
        record_payload=payload,
    )
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_settlement_mismatch",
    )


def test_count_update_rejects_retained_sibling_and_type_differences(count_fixture):
    result = _run(count_fixture, "consume", _count_state(stacks=2))
    original = result.mutations[_details_index(result)]

    sibling_changed = _thaw(original.after)
    sibling_changed[1]["stacks"] = 6
    mutations, records = _reaudit(
        count_fixture,
        result,
        after=sibling_changed,
    )
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_update_diff_mismatch",
    )

    sibling_removed = _thaw(original.after)
    del sibling_removed[1]
    mutations, records = _reaudit(
        count_fixture,
        result,
        after=sibling_removed,
    )
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_update_diff_mismatch",
    )

    float_count = _thaw(original.after)
    float_count[0]["stacks"] = 1.0
    mutations, records = _reaudit(
        count_fixture,
        result,
        after=float_count,
    )
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_update_diff_mismatch",
    )

    bool_as_int = _thaw(original.after)
    bool_as_int[0]["partial"] = 1
    mutations, records = _reaudit(
        count_fixture,
        result,
        after=bool_as_int,
    )
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_update_diff_mismatch",
    )

    wrong_owner = _thaw(original.after)
    wrong_owner[0]["owner_id"] = "someone_else"
    mutations, records = _reaudit(
        count_fixture,
        result,
        after=wrong_owner,
    )
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_update_diff_mismatch",
    )


def test_count_removal_rejects_retained_or_extra_instances(count_fixture):
    result = _run(count_fixture, "reset", _count_state(stacks=2, dynamic_amount=0.0))
    original = result.mutations[_details_index(result)]
    record = next(
        record
        for record in result.records
        if record.get("mutation_id") == original.stable_id()
    )

    removed_sibling_too = _thaw(original.after)
    del removed_sibling_too[0]
    mutations, records = _reaudit(
        count_fixture,
        result,
        after=removed_sibling_too,
    )
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_removal_diff_mismatch",
    )

    target_kept = _thaw(original.before)
    target_kept[0]["stacks"] = 0
    mutations, records = _reaudit(
        count_fixture,
        result,
        after=target_kept,
    )
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_removal_diff_mismatch",
    )

    status_index = next(
        index
        for index, item in enumerate(result.mutations)
        if item.path == ("units", "owner", "statuses")
    )
    status_mutation = result.mutations[status_index]
    status_after = [
        value
        for value in status_mutation.before
        if value != original.before[0]["status_id"]
    ]
    changed_status = replace(status_mutation, after=status_after)
    old_status_mutation_id = status_mutation.stable_id()
    new_status_mutation_id = changed_status.stable_id()
    mutations = tuple(
        changed_status if index == status_index else item
        for index, item in enumerate(result.mutations)
    )
    records = tuple(
        {**record, "mutation_id": new_status_mutation_id}
        if record.get("mutation_id") == old_status_mutation_id
        else record
        for record in result.records
    )
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_status_list_diff_mismatch",
    )

    payload = _thaw(record["payload"])
    payload["removed_detail"]["stacks"] = 1
    mutations, records = _reaudit(
        count_fixture,
        result,
        record_payload=payload,
    )
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_settlement_mismatch",
    )


def test_count_audit_rejects_disguised_effect_and_missing_fields(count_fixture):
    result = _run(count_fixture, "consume", _count_state(stacks=2))
    original = result.mutations[_details_index(result)]

    disguised_after = _thaw(original.after)
    disguised_after[0]["stacks"] = 999
    disguised_after[0]["stack_policy"] = "additive_stack"
    metadata = _thaw(original.metadata)
    metadata["lifecycle_plan"]["operation"] = "stack"
    metadata["lifecycle_plan"]["source_trace"]["effect_id"] = "fixture:layers"
    mutations, records = _reaudit(
        count_fixture,
        result,
        after=disguised_after,
        metadata=metadata,
    )
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_effect_contract_missing_or_not_admitted",
    )

    metadata = _thaw(original.metadata)
    del metadata["numeric_evaluation"]
    del metadata["lifecycle_plan"]["source_trace"]["numeric_evaluation"]
    mutations, records = _reaudit(
        count_fixture,
        result,
        metadata=metadata,
    )
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_numeric_evaluation_invalid",
    )


def test_count_update_accepts_legitimate_reassociated_settlement_ids(count_fixture):
    result = _run(count_fixture, "consume", _count_state(stacks=2))
    mutations, records = _reaudit(
        count_fixture,
        result,
        mutation_id="mutation:count-audit-reassociated",
    )
    audit = count_fixture.auditor.validate_execution(mutations, records)
    assert audit.ok, [violation.reason for violation in audit.violations]
    assert mutations[_details_index(result)].stable_id() == "mutation:count-audit-reassociated"


def test_generic_layer_status_path_keeps_its_own_contract(count_fixture):
    result = _run(count_fixture, "layer", _layer_state())
    audit = _audit(count_fixture, result)
    assert audit.ok, [violation.reason for violation in audit.violations]
    mutation = result.mutations[_details_index(result)]
    after = mutation.after[0]
    assert after["stacks"] == 3
    assert after["stack_policy"] == "additive_stack"
    assert after["max_stacks"] == 3

def test_count_update_family_rejects_extra_changes_and_disguise(count_fixture):
    result = _run(count_fixture, "consume", _count_state(stacks=2))
    original = result.mutations[_details_index(result)]

    # Extra fields and retained-sibling edits are rejection reasons, not a
    # reason to stop treating the write as the count family.
    after = _thaw(original.after)
    after[0]["stacks"] = 999
    after[1]["source_id"] = "wrong-source"
    metadata = _thaw(original.metadata)
    metadata["lifecycle_plan"]["operation"] = "stack"
    mutations, records = _reaudit(
        count_fixture,
        result,
        after=after,
        metadata=metadata,
    )
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_update_diff_mismatch",
        "modifier_count_update_operation_mismatch",
    )

    # Replacing the stack identity or the effect reference cannot hide the
    # same actual count change behind the generic lifecycle audit.
    for broken in ("policy", "identity"):
        after = _thaw(original.after)
        after[0]["stacks"] = 999
        after[1]["source_id"] = "wrong-source"
        if broken == "policy":
            after[0]["stack_policy"] = "additive_stack"
        else:
            after[0]["instance_id"] = "counter:renamed"
        metadata = _thaw(original.metadata)
        metadata["lifecycle_plan"]["operation"] = "stack"
        metadata["lifecycle_plan"]["source_trace"]["effect_id"] = "fixture:layers"
        mutations, records = _reaudit(
            count_fixture,
            result,
            after=after,
            metadata=metadata,
        )
        _assert_count_rejected(
            count_fixture,
            mutations,
            records,
            "modifier_count_effect_contract_missing_or_not_admitted",
        )

    # The Set half of the same family keeps the widened identification.
    set_result = _run(
        count_fixture, "reset", _count_state(stacks=1, dynamic_amount=2.0)
    )
    set_original = set_result.mutations[_details_index(set_result)]
    after = _thaw(set_original.after)
    after[0]["stacks"] = 999
    after[1]["source_id"] = "wrong-source"
    metadata = _thaw(set_original.metadata)
    metadata["lifecycle_plan"]["operation"] = "stack"
    mutations, records = _reaudit(
        count_fixture,
        set_result,
        after=after,
        metadata=metadata,
    )
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_update_diff_mismatch",
    )


def test_count_zero_family_rejects_extra_changes_and_disguise(count_fixture):
    result = _run(
        count_fixture, "reset", _count_state(stacks=2, dynamic_amount=0.0)
    )
    original = result.mutations[_details_index(result)]

    after = _thaw(original.after)
    after[0]["source_id"] = "wrong-source"
    mutations, records = _reaudit(count_fixture, result, after=after)
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_removal_diff_mismatch",
    )

    metadata = _thaw(original.metadata)
    metadata["lifecycle_plan"]["operation"] = "stack"
    metadata["lifecycle_plan"]["source_trace"]["effect_id"] = "fixture:layers"
    mutations, records = _reaudit(
        count_fixture,
        result,
        after=after,
        metadata=metadata,
    )
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_effect_contract_missing_or_not_admitted",
    )


def test_dynamic_count_rejects_numeric_summary_without_native_binding_agreement(
    count_fixture,
):
    result = _run(
        count_fixture, "reset", _count_state(stacks=1, dynamic_amount=2.0)
    )
    assert _audit(count_fixture, result).ok
    original = result.mutations[_details_index(result)]
    record = next(
        record
        for record in result.records
        if record.get("mutation_id") == original.stable_id()
    )

    def tampered(*, forge_binding: bool):
        after = _thaw(original.after)
        after[0]["stacks"] = 999
        metadata = _thaw(original.metadata)
        trace = metadata["lifecycle_plan"]["source_trace"]
        trace["amount"] = 999.0
        trace["numeric_evaluation"]["value"] = 999.0
        trace["stack_plan"] = {"stacks_before": 1, "stacks_after": 999}
        if forge_binding:
            trace["numeric_evaluation"]["bindings"]["value"] = 999.0
            trace["numeric_evaluation"]["bindings"]["entry"]["value"] = 999.0
        for key in ("amount", "numeric_evaluation", "stack_plan"):
            metadata[key] = _thaw(trace[key])
        payload = _thaw(record["payload"])
        payload["after"] = 999
        return after, metadata, trace, payload

    after, metadata, trace, payload = tampered(forge_binding=False)
    mutations, records = _reaudit(
        count_fixture,
        result,
        after=after,
        metadata=metadata,
        record_trace=trace,
        record_payload=payload,
    )
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_numeric_binding_value_mismatch",
    )

    # A fully self-consistent forged summary still disagrees with the selected
    # before instance's dynamic value and native entry.
    after, metadata, trace, payload = tampered(forge_binding=True)
    mutations, records = _reaudit(
        count_fixture,
        result,
        after=after,
        metadata=metadata,
        record_trace=trace,
        record_payload=payload,
    )
    _assert_count_rejected(
        count_fixture,
        mutations,
        records,
        "modifier_count_numeric_binding_source_mismatch",
        "modifier_count_numeric_value_mismatch",
    )


def test_program_count_recomputes_formal_instructions(count_fixture):
    constant = _program_count_fixture(
        count_fixture,
        [
            {"opcode": "push_fixed", "value": -1.0},
            {"opcode": "end"},
        ],
    )
    result = _run(constant, "program", _count_state(stacks=2))
    assert _audit(constant, result).ok
    original = result.mutations[_details_index(result)]
    record = next(
        record
        for record in result.records
        if record.get("mutation_id") == original.stable_id()
    )
    after = _thaw(original.after)
    after[0]["stacks"] = 999
    metadata = _thaw(original.metadata)
    trace = metadata["lifecycle_plan"]["source_trace"]
    trace["amount"] = 997.0
    trace["numeric_evaluation"]["value"] = 997.0
    trace["stack_plan"] = {"stacks_before": 2, "stacks_after": 999}
    for key in ("amount", "numeric_evaluation", "stack_plan"):
        metadata[key] = _thaw(trace[key])
    payload = _thaw(record["payload"])
    payload["after"] = 999
    mutations, records = _reaudit(
        constant,
        result,
        after=after,
        metadata=metadata,
        record_trace=trace,
        record_payload=payload,
    )
    _assert_count_rejected(
        constant,
        mutations,
        records,
        "modifier_count_numeric_value_mismatch",
    )

    dynamic = _program_count_fixture(
        count_fixture,
        [
            {"opcode": "push_dynamic", "hash": int(COUNT_HASH)},
            {"opcode": "push_fixed", "value": -1.0},
            {"opcode": "add"},
            {"opcode": "end"},
        ],
    )
    result = _run(
        dynamic, "program", _count_state(stacks=2, dynamic_amount=2.0)
    )
    assert _audit(dynamic, result).ok
    original = result.mutations[_details_index(result)]
    record = next(
        record
        for record in result.records
        if record.get("mutation_id") == original.stable_id()
    )
    after = _thaw(original.after)
    after[0]["stacks"] = 999
    metadata = _thaw(original.metadata)
    trace = metadata["lifecycle_plan"]["source_trace"]
    trace["amount"] = 999.0
    trace["numeric_evaluation"]["value"] = 999.0
    operand = trace["numeric_evaluation"]["bindings"]["dynamic_operands"][0]
    operand["value"] = 999.0
    operand["bindings"]["value"] = 999.0
    operand["bindings"]["entry"]["value"] = 999.0
    trace["stack_plan"] = {"stacks_before": 2, "stacks_after": 999}
    for key in ("amount", "numeric_evaluation", "stack_plan"):
        metadata[key] = _thaw(trace[key])
    payload = _thaw(record["payload"])
    payload["after"] = 999
    mutations, records = _reaudit(
        dynamic,
        result,
        after=after,
        metadata=metadata,
        record_trace=trace,
        record_payload=payload,
    )
    _assert_count_rejected(
        dynamic,
        mutations,
        records,
        "modifier_count_numeric_binding_source_mismatch",
    )
