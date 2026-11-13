"""Status-scoped dynamic values must not survive their status lifecycle.

An ordinary break status instance id is a deterministic source identity, so a
later lifecycle of the same modifier reuses it. Values written for the removed
lifecycle (Entanglement hit counters, slow/delay locals) must be pruned in the
same transaction; otherwise the next lifecycle reads counters from the previous
one. `remove_status_instance_entries` also prunes the operation ledger that
references the removed entries so the store keeps passing its strict validator.
"""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, EffectIR, IRSource
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.dynamic_values import (
    _entry_key,
    _ledger_record_fingerprint,
    _reindex,
    empty_dynamic_value_store,
    normalized_dynamic_value_store,
    store_from_state,
    remove_status_instance_entries,
    upsert_dynamic_value,
)
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _attach_target_expressions_to_effect_payload,
    _effect_coverage_status,
    _standard_dispel_status_payload,
    _standard_remove_modifier_payload,
)
from hsr.simulator_v8_clean_core.tbgd.target_source import build_target_language_definitions

REMOVED_INSTANCE = "status:fixture:removed"
KEPT_INSTANCE = "status:fixture:kept"
EPSILON_STATUS = "modifier:MEquip_EquipUnique_AttackAddedRatio"


def _status_entry(store, *, instance_id, name, hash_key, value):
    return upsert_dynamic_value(
        store,
        scope="status",
        owner_id="enemy:fixture",
        value=value,
        value_name=name,
        hash_key=hash_key,
        status_id="modifier:MCommon_Element_Entangle",
        status_instance_id=instance_id,
        effect_id="effect:fixture:break",
        source_id="break_status_emission:StanceBreak_Quantum:1",
        source_trace={"effect_id": "effect:fixture:break"},
    )


def _unit_entry(store):
    return upsert_dynamic_value(
        store,
        scope="unit",
        owner_id="enemy:fixture",
        value=7.0,
        value_name="fixture:unit_value",
        hash_key=424242,
        effect_id="effect:fixture:unit",
        source_id="source:fixture:unit",
        source_trace={"effect_id": "effect:fixture:unit"},
    )


def test_immutable_store_validation_is_reused_without_trusting_new_or_mutable_inputs(monkeypatch):
    import pytest
    from hsr.simulator_v8_clean_core.immutable_json import freeze_json, thaw_json
    from hsr.simulator_v8_clean_core.systems import dynamic_values

    store = freeze_json(_fixture_store(with_ledger=True))
    expected = normalized_dynamic_value_store(store)
    def unexpected(_item):
        raise AssertionError('unchanged immutable ledger was revalidated')
    with monkeypatch.context() as patch:
        patch.setattr(dynamic_values, '_ledger_record_fingerprint', unexpected)
        copied = normalized_dynamic_value_store(store)
        assert copied is expected
        assert normalized_dynamic_value_store(copied) is copied
        with pytest.raises(TypeError):
            copied['entries'].clear()
        detached = thaw_json(copied)
        detached['entries'].clear()
        assert normalized_dynamic_value_store(store)['entries'] == expected['entries']
    for frozen in (False, True):
        changed = thaw_json(store)
        changed['by_hash'].clear()
        with pytest.raises(ValueError, match='store_index_mismatch'):
            normalized_dynamic_value_store(freeze_json(changed) if frozen else changed)
    mutable = thaw_json(store)
    normalized_dynamic_value_store(mutable)
    mutable['by_name'].clear()
    with pytest.raises(ValueError, match='store_index_mismatch'):
        normalized_dynamic_value_store(mutable)


def test_unit_binding_projection_validates_input_and_keeps_foreign_status_slots():
    import pytest
    from hsr.simulator_v8_clean_core.systems.dynamic_values import binding_source_from_store_for_units

    store = _fixture_store(with_ledger=True)
    for owner in ('selected', 'other'):
        store = upsert_dynamic_value(store, scope='unit', owner_id=owner, value=2,
                                     value_name='shared', hash_key='123')
    source = binding_source_from_store_for_units(store, ('selected',))
    assert {e['owner_id'] for e in source['entries'].values() if e['scope'] == 'unit'} == {'selected'}
    assert {k for k,e in source['entries'].items() if e['scope'] == 'status'} == {
        k for k,e in store['entries'].items() if e['scope'] == 'status'}
    assert 'operation_ledger' not in source
    broken = copy.deepcopy(store)
    next(iter(broken['operation_ledger'].values()))['record_fingerprint'] = 'invalid'
    with pytest.raises(ValueError, match='operation_ledger_entry_mismatch'):
        binding_source_from_store_for_units(broken, ('selected',))


def _fixture_store(*, with_ledger=False):
    store = empty_dynamic_value_store()
    store = _status_entry(
        store, instance_id=REMOVED_INSTANCE,
        name="MDF_BeingHitDamageValue", hash_key=-434232686, value=1.0,
    )
    store = _status_entry(
        store, instance_id=REMOVED_INSTANCE,
        name="MDF_BeHitFlag", hash_key=369211422, value=1.0,
    )
    store = _status_entry(
        store, instance_id=KEPT_INSTANCE,
        name="MDF_BeingHitDamageValue", hash_key=-434232686, value=2.0,
    )
    store = _unit_entry(store)
    if with_ledger:
        entries = {}
        ledger = {}
        for entry in store["entries"].values():
            operation_id = (
                "fixture:operation:"
                f"{entry['status_instance_id']}:{entry['name']}"
            )
            operation_instance_id = f"{operation_id}:instance"
            updated = {
                **entry,
                "operation_id": operation_id,
                "operation_instance_id": operation_instance_id,
                "operation_source_id": "effect:fixture:break:operation",
            }
            key = _entry_key(updated)
            entries[key] = updated
            item = {
                "operation_id": operation_id,
                "operation_instance_id": operation_instance_id,
                "destination_entry_key": key,
                "result_value": updated["value"],
                "source_id": updated["source_id"],
                "effect_id": updated["effect_id"],
                "operation_source_id": updated["operation_source_id"],
            }
            item["record_fingerprint"] = _ledger_record_fingerprint(item)
            ledger[operation_instance_id] = item
        store = _reindex({"entries": entries, "operation_ledger": ledger})
    # The fixture must start in the strict canonical shape.
    assert normalized_dynamic_value_store(store)["entries"]
    return store


def _scope_identities(entries):
    return {
        (entry.get("scope_kind"), entry.get("status_instance_id"), entry.get("name"))
        for entry in entries.values()
    }


def test_removing_a_status_instance_prunes_only_its_dynamic_values():
    store = _fixture_store()
    before = normalized_dynamic_value_store(store)
    pruned = remove_status_instance_entries(store, REMOVED_INSTANCE)
    assert pruned is not None
    after = normalized_dynamic_value_store(pruned)

    assert _scope_identities(before["entries"]) - _scope_identities(after["entries"]) == {
        ("status", REMOVED_INSTANCE, "MDF_BeingHitDamageValue"),
        ("status", REMOVED_INSTANCE, "MDF_BeHitFlag"),
    }
    assert _scope_identities(after["entries"]) == {
        ("status", KEPT_INSTANCE, "MDF_BeingHitDamageValue"),
        ("unit", None, "fixture:unit_value"),
    }
    # Unit-scoped values are never pruned by a status lifecycle.
    assert remove_status_instance_entries(pruned, REMOVED_INSTANCE) is None
    assert remove_status_instance_entries(pruned, "status:fixture:missing") is None
    assert remove_status_instance_entries(pruned, "") is None


def test_pruning_keeps_the_operation_ledger_consistent():
    store = _fixture_store(with_ledger=True)
    before = normalized_dynamic_value_store(store)
    assert len(before["operation_ledger"]) == len(before["entries"])
    pruned = remove_status_instance_entries(store, REMOVED_INSTANCE)
    assert pruned is not None
    after = normalized_dynamic_value_store(pruned)
    # Every ledger entry still points at a live destination; the strict
    # validator inside normalized_dynamic_value_store already rejects stale
    # ledger keys, so this is a regression guard for the cleanup itself.
    kept_keys = set(after["entries"])
    assert after["operation_ledger"]
    assert all(
        item["destination_entry_key"] in kept_keys
        for item in after["operation_ledger"].values()
    )
    # The pruned instance's entries are gone and their ledger records too.
    removed_keys = {
        _entry_key(entry)
        for entry in before["entries"].values()
        if entry.get("status_instance_id") == REMOVED_INSTANCE
    }
    assert removed_keys
    assert not removed_keys & kept_keys
    assert not removed_keys & {
        item["destination_entry_key"] for item in after["operation_ledger"].values()
    }


# ---------------------------------------------------------------------------
# 多目标移除：真实 Ability20005 RemoveModifier 一次移除两个带动态值的目标
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _ability_20005_case():
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    relative = "Config/ConfigAbility/Equip/EquipmemtAbility.json"
    abilities = json.loads((root / relative).read_text())["AbilityList"]
    index, ability = next(
        (i, item) for i, item in enumerate(abilities) if item["Name"] == "Ability20005"
    )
    raw = ability["Modifiers"]["MEquip_20005_Main"]["_CallbackList"][0]["CallbackConfig"][0]
    source = IRSource(
        relative,
        "RemoveModifier",
        "cleanup",
        {"json_path": f"$.AbilityList[{index}].Modifiers.MEquip_20005_Main._CallbackList[0].CallbackConfig[0]"},
    )
    languages = build_target_language_definitions(root)
    payload, targets = _attach_target_expressions_to_effect_payload(
        {"standard": _standard_remove_modifier_payload(raw, "RemoveModifier", "")},
        raw,
        effect_id="cleanup",
        source=source,
        target_language_definitions=languages,
    )
    assert _effect_coverage_status("RemoveModifier", payload) == "executable"
    effect = EffectIR("cleanup", "RemoveModifier", payload, source, "executable")
    rules = RuleBook(
        CanonicalIR(
            "cleanup-multi-target",
            effects=(effect,),
            target_expressions=(
                *targets,
                *(language.expression for language in languages),
            ),
        )
    )
    return rules, effect


def _status_store_entry(store, *, owner_id, instance_id, name, hash_key, value):
    return upsert_dynamic_value(
        store,
        scope="status",
        owner_id=owner_id,
        value=value,
        value_name=name,
        hash_key=hash_key,
        status_id=EPSILON_STATUS,
        status_instance_id=instance_id,
        effect_id="effect:fixture:break",
        source_id="break_status_emission:StanceBreak_Quantum:1",
        source_trace={"effect_id": "effect:fixture:break"},
    )


def _multi_target_state():
    def detail(owner_id):
        return {
            "instance_id": f"status:fixture:{owner_id}",
            "status_id": EPSILON_STATUS,
            "modifier_name": EPSILON_STATUS.removeprefix("modifier:"),
            "owner_id": owner_id,
            "caster_id": "caster",
            "lifecycle_state": "active",
        }

    units = {
        "caster": UnitState("caster", "ally", "fixture", hp=100, max_hp=100),
        "targetA": UnitState(
            "targetA", "ally", "fixture", hp=100, max_hp=100,
            statuses=(EPSILON_STATUS,),
            flags={"status_details": [detail("targetA")]},
        ),
        "targetB": UnitState(
            "targetB", "ally", "fixture", hp=100, max_hp=100,
            statuses=(EPSILON_STATUS,),
            flags={"status_details": [detail("targetB")]},
        ),
    }
    store = empty_dynamic_value_store()
    for owner_id in ("targetA", "targetB"):
        store = _status_store_entry(
            store, owner_id=owner_id, instance_id=f"status:fixture:{owner_id}",
            name="MDF_BeingHitDamageValue", hash_key=-434232686, value=1.0,
        )
    store = upsert_dynamic_value(
        store,
        scope="unit",
        owner_id="caster",
        value=7.0,
        value_name="fixture:unit_value",
        hash_key=424242,
        effect_id="effect:fixture:unit",
        source_id="source:fixture:unit",
        source_trace={"effect_id": "effect:fixture:unit"},
    )
    return BattleState(units=units, global_flags={"dynamic_value_store": store})


def test_multi_target_removal_merges_dynamic_value_cleanup_atomically():
    rules, effect = _ability_20005_case()
    state = _multi_target_state()
    result = StatusSystem(rules).apply_remove_modifier(
        state, effect, caster_id="caster", source_id="cleanup",
    )
    assert result.ok, result.unsupported

    cleanup_mutations = [
        mutation for mutation in result.mutations
        if mutation.path == ("global_flags", "dynamic_value_store")
    ]
    assert len(cleanup_mutations) == 2
    after = MutationReducer().apply_all(state, result.mutations)
    for target_id in ("targetA", "targetB"):
        assert EPSILON_STATUS not in after.units[target_id].statuses
    store = normalized_dynamic_value_store(after.global_flags.get("dynamic_value_store"))
    remaining_instances = {
        entry.get("status_instance_id") for entry in store["entries"].values()
    }
    assert "status:fixture:targetA" not in remaining_instances
    assert "status:fixture:targetB" not in remaining_instances
    assert any(entry.get("name") == "fixture:unit_value" for entry in store["entries"].values())

    audit = RuntimeSourceAuditor(rules).validate_execution(result.mutations, result.records)
    assert audit.ok, [
        (violation.reason, violation.details) for violation in audit.violations
    ]


def test_cleanup_audit_rejects_changes_to_retained_store_entries():
    rules, effect = _ability_20005_case()
    state = _multi_target_state()
    result = StatusSystem(rules).apply_remove_modifier(
        state, effect, caster_id="caster", source_id="cleanup",
    )
    assert result.ok, result.unsupported
    cleanup = next(
        mutation for mutation in result.mutations
        if mutation.path == ("global_flags", "dynamic_value_store")
    )
    cleanup_record = next(
        record for record in result.records
        if isinstance(record, dict)
        and record.get("record_type") == "status_dynamic_value_cleanup"
        and record.get("mutation_id") == cleanup.stable_id()
    )

    # mutation payloads are frozen JSON; thaw to a plain object before tampering.
    tampered_after = json.loads(json.dumps(cleanup.after))
    for entry in tampered_after["entries"].values():
        if entry.get("name") == "fixture:unit_value":
            entry["value"] = 999.0
    tampered = replace(cleanup, after=tampered_after)
    tampered_record = {**cleanup_record, "mutation_id": tampered.stable_id()}
    audit = RuntimeSourceAuditor(rules).validate_execution(
        (tampered,), (tampered_record,),
    )
    assert not audit.ok
    assert "status_dynamic_value_cleanup_diff_mismatch" in {
        violation.reason for violation in audit.violations
    }

    record_tampered = {
        **cleanup_record,
        "payload": {**cleanup_record["payload"], "removed_entry_count": 0},
    }
    record_audit = RuntimeSourceAuditor(rules).validate_execution(
        (cleanup,), (record_tampered,),
    )
    assert not record_audit.ok
    assert "status_dynamic_value_cleanup_record_mismatch" in {
        violation.reason for violation in record_audit.violations
    }


def _dispel_case(raw=None):
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    relative = "Config/ConfigAbility/Equip/EquipmemtAbility.json"
    source = IRSource(relative, "DispelStatus", "dispel", {"json_path": "$.fixture.DispelStatus"})
    raw = raw or {
        "$type": "RPG.GameCore.DispelStatus",
        "DispelCountKey": "BuffNumber",
        "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "AllTeamMember"},
        "Numbers": {"IsDynamic": False, "FixedValue": {"Value": 1}},
        "Order": "LastAdded",
    }
    languages = build_target_language_definitions(root)
    payload, targets = _attach_target_expressions_to_effect_payload(
        {"standard": _standard_dispel_status_payload(raw)},
        raw,
        effect_id="dispel",
        source=source,
        target_language_definitions=languages,
    )
    effect = EffectIR("dispel", "DispelStatus", payload, source, "executable")
    rules = RuleBook(
        CanonicalIR(
            "dispel-multi-target",
            effects=(effect,),
            target_expressions=(
                *targets,
                *(language.expression for language in languages),
            ),
        )
    )
    return rules, effect


def test_control_only_unbounded_dispel_removes_all_controls_and_keeps_dot():
    raw = {'$type': 'RPG.GameCore.DispelStatus',
           'TargetType': {'$type': 'RPG.GameCore.TargetAlias', 'Alias': 'Caster'},
           'BehaviorFlags': ['STAT_CTRL']}
    rules, effect = _dispel_case(raw)
    assert effect.payload['standard']['dispel_scope'] == 'all_eligible'
    details = [{'instance_id': f'status:{i}', 'status_id': f'modifier:fixture{i}',
                'modifier_name': f'fixture{i}', 'owner_id': 'caster', 'caster_id': 'caster',
                'can_dispel': True, 'lifecycle_state': 'active', 'status_type': 'Debuff',
                'control_kind': control} for i, control in enumerate(('CTRL_Frozen', 'CTRL_Imprison', ''))]
    state = BattleState(units={'caster': UnitState('caster', 'ally', 'fixture', hp=100, max_hp=100,
        statuses=tuple(d['status_id'] for d in details), flags={'status_details': details})})
    result = StatusSystem(rules).apply_dispel_status(state, effect, caster_id='caster', source_id='dispel')
    assert result.ok, result.unsupported
    assert result.dispelled_count == 2
    assert MutationReducer().apply_all(state, result.mutations).units['caster'].statuses == ('modifier:fixture2',)


def test_multi_target_dispel_merges_dynamic_value_cleanup_atomically():
    rules, effect = _dispel_case()

    def detail(owner_id):
        return {
            "instance_id": f"status:fixture:{owner_id}",
            "status_id": EPSILON_STATUS,
            "modifier_name": EPSILON_STATUS.removeprefix("modifier:"),
            "owner_id": owner_id,
            "caster_id": "caster",
            "can_dispel": True,
            "lifecycle_state": "active",
        }

    units = {
        "caster": UnitState("caster", "ally", "fixture", hp=100, max_hp=100),
        **{
            owner_id: UnitState(
                owner_id, "ally", "fixture", hp=100, max_hp=100,
                statuses=(EPSILON_STATUS,),
                flags={"status_details": [detail(owner_id)]},
            )
            for owner_id in ("targetA", "targetB")
        },
    }
    store = empty_dynamic_value_store()
    for owner_id in ("targetA", "targetB"):
        store = _status_store_entry(
            store, owner_id=owner_id, instance_id=f"status:fixture:{owner_id}",
            name="MDF_BeingHitDamageValue", hash_key=-434232686, value=1.0,
        )
    state = BattleState(units=units, global_flags={"dynamic_value_store": store})

    result = StatusSystem(rules).apply_dispel_status(
        state, effect, caster_id="caster", source_id="dispel",
    )
    assert result.ok, result.unsupported
    cleanup_mutations = [
        mutation for mutation in result.mutations
        if mutation.path == ("global_flags", "dynamic_value_store")
    ]
    assert len(cleanup_mutations) == 2
    assert result.dispelled_count == 2
    after = MutationReducer().apply_all(state, result.mutations)
    store_after = normalized_dynamic_value_store(after.global_flags.get("dynamic_value_store"))
    assert store_after["entries"] == {}
    from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry

    registry = EffectRegistry(StatusSystem(rules))
    context = EffectExecutionContext(state, "caster", "dispel", ability_instance_id="ability:dispel")
    for expected in (2, 0):
        result = registry.execute(effect, context)
        assert not result.unsupported, result.unsupported
        after = MutationReducer().apply_all(context.state, result.mutations)
        entries = store_from_state(after)["entries"].values()
        values = [entry["value"] for entry in entries if entry["name"] == "BuffNumber"]
        assert values == [expected]
        context = replace(context, state=after)
