"""Typed component rules for exact HP-clamp provenance; no source compilation."""
from dataclasses import replace

import pytest

from hsr.simulator_v8_clean_core.immutable_json import thaw_json
from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState, UnitStatPool, current_max_hp
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.rules.ir import (
    CanonicalIR, EffectIR, IRSource, RuleEntity, StatusCallbackIR, StatusCallbackTaskIR,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.status import StatusInstance, StatusSystem


def _native_clamp(key="hp_convert", *, stat_pools=(), max_hp=100):
    name = "ComponentMaxHp"
    source = IRSource("validation_fixture/hp_clamp.json", "ComponentModifier", name)
    value = 1.0 if key == "hp_added_ratio" else 100.0
    modifier = {"bucket": "attribute", "key": key, "value": value}
    entity = RuleEntity(
        "modifier_definition:" + name, "modifier_definition",
        {"modifier_name": name, "modifiers": [modifier]}, source, "executable",
    )
    effect = EffectIR(
        "component:add-hp", "AddModifier",
        {"standard": {"modifier_name": name, "target_alias": "Caster"}},
        source, "executable",
    )
    rules = RuleBook(CanonicalIR(version="component", entities=(entity,), effects=(effect,)))
    trace = {"effect_id": effect.effect_id, "modifier_name": name}
    instance = StatusInstance(
        "component:hp", "modifier:" + name, name, "u", "u", "u",
        source_trace=trace, modifiers=(modifier,),
    )
    sibling = StatusInstance("component:sibling", "modifier:sibling", "sibling", "u", "u", "u")
    state = BattleState(units={"u": UnitState(
        "u", "ally", "component:u", hp=150, max_hp=max_hp, stat_pools=stat_pools,
        statuses=(instance.status_id, sibling.status_id),
        flags={"status_details": [instance.to_json(), sibling.to_json()]},
    )})
    assert current_max_hp(state.units["u"]) == 200
    result = StatusSystem(rules).remove_status_instance(
        state, target_id="u", detail=instance.to_json(), source="status_system", source_trace=trace,
    )
    assert result.ok, result.unsupported
    after = MutationReducer().apply_all(state, result.mutations)
    assert after.units["u"].hp == current_max_hp(after.units["u"]) == max_hp
    assert after.units["u"].flags["status_details"] == [sibling.to_json()]
    clamp = next(m for m in result.mutations if m.path == ("units", "u", "hp"))
    assert "status_hp_clamp_fact" not in clamp.to_json()
    return rules, result, clamp


@pytest.mark.parametrize("key", ["hp_convert", "hp_delta", "hp_added_ratio"])
def test_legal_hp_modifier_removals_stay_auditable(key):
    rules, result, _ = _native_clamp(key)
    audit = RuntimeSourceAuditor(rules).validate_execution(result.mutations, result.records)
    assert audit.ok, [v.to_json() for v in audit.violations]


def test_hp_clamp_uses_base_pool_percentage_and_flat_terms():
    rules, result, _ = _native_clamp(
        "hp_added_ratio", stat_pools=(UnitStatPool("max_hp", 80, 0.25, 20),), max_hp=120,
    )
    audit = RuntimeSourceAuditor(rules).validate_execution(result.mutations, result.records)
    assert audit.ok, [v.to_json() for v in audit.violations]


@pytest.mark.parametrize("variant", [
    "coherent_ceiling", "stripped_labels", "wrong_instance", "no_fact_or_labels", "extra_record",
])
def test_hp_clamp_audit_uses_independent_authority(variant):
    rules, result, clamp = _native_clamp()
    auditor = RuntimeSourceAuditor(rules)
    baseline = auditor.validate_execution(result.mutations, result.records)
    assert baseline.ok, [v.to_json() for v in baseline.violations]
    metadata = thaw_json(clamp.metadata)
    if variant == "coherent_ceiling":
        metadata.update(hp_after=99.0, current_max_hp=99.0,
                        effective_max_hp_before=199.0, effective_max_hp_after=99.0)
        metadata["hp_contract"].update(
            after_hp=99.0, delta=99.0 - clamp.before,
            effective_max_hp_before=199.0, effective_max_hp_after=99.0,
        )
        wrong = replace(clamp, after=99.0, metadata=metadata)
    elif variant in {"stripped_labels", "no_fact_or_labels"}:
        metadata.pop("lifecycle_operation")
        metadata.pop("hp_contract")
        wrong = replace(clamp, after=99.0, metadata=metadata,
                        status_hp_clamp_fact=None if variant == "no_fact_or_labels" else clamp.status_hp_clamp_fact)
    elif variant == "wrong_instance":
        metadata["status_instance_id"] = "not-the-removed-instance"
        wrong = replace(clamp, metadata=metadata)
    else:
        wrong = clamp
    mutations = tuple(wrong if m is clamp else m for m in result.mutations)
    records = []
    for record in result.records:
        record = thaw_json(record)
        if record.get("mutation_id") == clamp.stable_id():
            record["mutation_id"] = wrong.stable_id()
            if variant not in {"stripped_labels", "no_fact_or_labels"}:
                record["payload"] = thaw_json(metadata)
            if variant == "no_fact_or_labels":
                record["record_type"] = "status_lifecycle"
            if variant == "extra_record":
                records.append({**record, "record_type": "unrelated"})
        records.append(record)
    checked = auditor.validate_execution(mutations, tuple(records))
    assert not checked.ok, variant


def test_hp_clamp_cannot_reuse_a_host_with_a_changed_sibling():
    rules, result, _ = _native_clamp()
    host = next(m for m in result.mutations if m.path == ("units", "u", "flags", "status_details"))
    after = thaw_json(host.after)
    after[0]["stacks"] = 999
    wrong = replace(host, after=after)
    mutations = tuple(wrong if m is host else m for m in result.mutations)
    records = tuple(
        {**thaw_json(r), "mutation_id": wrong.stable_id()}
        if r.get("mutation_id") == host.stable_id() else r for r in result.records
    )
    audit = RuntimeSourceAuditor(rules).validate_execution(mutations, records)
    assert not audit.ok


@pytest.mark.parametrize("append", [False, True])
def test_attribute_write_and_its_clamp_share_an_auditable_native_result(append):
    from hsr.simulator_v8_clean_core.rules.expression_ir import numeric_fixed
    from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem

    source = IRSource("validation_fixture/hp_clamp.json", "StackProperty", "component:property")
    prop, key, value = ("HPDelta", "hp_delta", -50.0) if append else ("HPConvert", "hp_convert", 50.0)
    task = StatusCallbackTaskIR(
        "component:task", "component:callback", "ComponentMaxHp", "OnStack", 0,
        "Modifier.Callback.OnStack[0]", "", "StackProperty", source,
        coverage_status="executable", task_payload={
            "Property": prop, "PropertyValue": numeric_fixed(value), "TargetType": "ModifierOwnerEntity",
        },
    )
    callback = StatusCallbackIR(
        task.callback_id, task.modifier_name, "OnStack", (task.task_id,), source, (0, 0),
        coverage_status="executable",
    )
    rules = RuleBook(CanonicalIR(version="component", status_callbacks=(callback,), status_callback_tasks=(task,)))
    entry = {"bucket": "attribute", "key": key, "scope": "actor", "value": 100.0,
             "property": prop, "producer_task_id": task.task_id, "producer_task_path": task.task_path,
             "raw_path": task.task_path, "applied_reason": "status_stack_property"}
    instance = StatusInstance("component:hp", "modifier:ComponentMaxHp", task.modifier_name, "u", "u", "u",
                              modifiers=() if append else (entry,))
    detail = instance.to_json()
    state = BattleState(units={"u": UnitState("u", "ally", "component:u", max_hp=100,
        hp=100 if append else 200, statuses=(instance.status_id,), flags={"status_details": [detail]})})
    result = StatusCallbackSystem(rules)._execute_formal_leaf_task(state, callback, task, detail, None, None)
    assert result.ok, result.errors
    assert result.after_state.units["u"].hp == current_max_hp(result.after_state.units["u"])
    audit = RuntimeSourceAuditor(rules).validate_execution(result.mutations, result.records)
    assert audit.ok, [v.to_json() for v in audit.violations]
