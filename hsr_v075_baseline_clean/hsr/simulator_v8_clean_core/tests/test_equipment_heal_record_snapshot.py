"""R06 integration: healer-attack healing record and the committed heal snapshot.

The recording status is attached by the real 23013 equipment graph, the heal
facts come from a formal heal mutation, and the snapshot event is projected from
that same mutation (never from a unit birth or an exported BattleState).
"""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.rules.ir import EffectIR, IRSource
from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry
from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem
from hsr.simulator_v8_clean_core.systems.mutation_events import (
    HealEventFact,
    MUTATION_BACKED_EVENT_TYPES,
)
from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _effect_coverage_status, _effect_payload,
)

pytestmark = pytest.mark.integration

_MAIN = "MEquip_23013_Main"
_SUB = "MEquip_23013_Sub"


@lru_cache(maxsize=1)
def _rules():
    core = Path(__file__).resolve().parents[1]
    scenario = json.loads(
        (core / "examples/cli/arlan_fleet_vs_antimatter.json").read_text()
    )
    return build_battle_rulebook(
        Path(__file__).resolve().parents[4] / "turnbasedgamedata-main", scenario
    )


def _startup_state(rules):
    graph = next(
        item
        for item in rules.ir.standalone_ability_graphs
        if item.ability_name == "Ability23013"
        and item.source_mode == "mainline_equipment"
    )
    task = next(
        rules.ability_task(task_id)
        for task_id in graph.task_ids
        if rules.ability_task(task_id) is not None
        and rules.ability_task(task_id).opcode == "AddModifier"
    )
    effect = rules.effect(task.effect_id)
    state = BattleState(units={
        "holder": UnitState("holder", "ally", "test:holder", max_hp=2000.0, hp=1500.0,
                            attack=0.0, speed=100.0),
        "ally": UnitState("ally", "ally", "test:ally", max_hp=2000.0, hp=1000.0,
                          speed=90.0),
        "other": UnitState("other", "ally", "test:other", max_hp=2000.0, hp=1500.0,
                           speed=80.0),
        "enemy": UnitState("enemy", "enemy", "test:enemy", max_hp=10000.0, hp=10000.0,
                           attack=100.0, speed=70.0),
    })
    # Superimposition 1: additional damage ratio = 0.36.
    parameter_values = {"1078169603": 0.36}
    result = StatusSystem(rules).apply_add_modifier(
        state,
        effect,
        application_instance_id="startup:test:A23013",
        caster_id="holder",
        source_id="test:startup",
        owner_id="holder",
        param_entity_id="holder",
        current_action_target_id="holder",
        dynamic_values=parameter_values,
        binding_sources=(),
        retained_runtime_hashes=tuple(sorted(parameter_values)),
    )
    assert result.ok, result.unsupported
    state = _commit(state, result.mutations)
    registry = EffectRegistry(StatusSystem(rules))
    system = EventDispatchSystem(rules, registry)
    for event in result.events:
        state = _dispatch(system, state, event)
    return state, registry, system


def _commit(state, mutations):
    result = MutationReducer().apply_all_result(state, mutations)
    assert result.ok, result.errors
    return result.after_state


def _dispatch(system, state, event):
    result = system.dispatch_event(state, event=event)
    assert not result.errors, result.errors
    return result.after_state


def _details(state, unit_id, modifier_name):
    return tuple(
        detail
        for detail in state.units[unit_id].flags.get("status_details", ())
        if isinstance(detail, dict) and detail.get("modifier_name") == modifier_name
    )


def _dynamic_value(state, unit_id, modifier_name, name):
    # Shared ability-level slots are committed at the owner-unit scope, so the
    # accumulated total is read from the canonical store; instance-local
    # declared defaults must not shadow it.
    from hsr.simulator_v8_clean_core.dynamic_key_hash import tbgd_dynamic_key_hash
    from hsr.simulator_v8_clean_core.systems.dynamic_values import store_from_state

    store = store_from_state(state)
    hash_key = str(tbgd_dynamic_key_hash(name))
    for entry in (store.get("entries") or {}).values():
        if (
            isinstance(entry, dict)
            and str(entry.get("hash") or "") == hash_key
            and str(entry.get("scope") or "") == "unit"
            and str(entry.get("target_id") or "") == unit_id
        ):
            return entry.get("value")
    details = _details(state, unit_id, modifier_name)
    assert len(details) == 1
    dynamic = details[0].get("dynamic_values", {})
    by_name = dynamic.get("__by_name", {}) if isinstance(dynamic, dict) else {}
    if isinstance(by_name, dict) and name in by_name:
        return by_name[name]
    return dynamic.get(name)


def _heal_effect(amount):
    raw = {
        "$type": "RPG.GameCore.HealHP",
        "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "ParamEntity"},
        "ModifyValue": {"IsDynamic": False, "FixedValue": {"Value": amount}},
    }
    payload = _effect_payload(raw, "HealHP", "")
    return EffectIR(
        "test:heal", "HealHP", payload,
        IRSource("synthetic:heal", "HealHP", "test"),
        _effect_coverage_status("HealHP", payload),
    )


def _perform_heal(state, registry, system, *, healer, target, amount):
    result = registry.execute(
        _heal_effect(amount),
        EffectExecutionContext(state, healer, f"test:heal:{healer}",
                              owner_id=target, param_entity_id=target,
                              current_action_target_id=target),
    )
    assert not result.unsupported, result.records
    events = result.events
    assert any(event.event_type == "heal.after" for event in events)
    snapshot = [event for event in events if event.event_type == "heal.snapshot.created"]
    assert len(snapshot) == 1
    assert snapshot[0].payload.get("healer_id") == healer
    assert snapshot[0].payload.get("param_entity_id") == healer
    assert snapshot[0].payload.get("snapshot_id")
    assert snapshot[0].payload.get("snapshot_lifetime", {}).get("kind") == "source_mutation"
    state = _commit(state, result.mutations)
    for event in events:
        if event.event_type == "heal.snapshot.created":
            # Route the snapshot through the same public dispatch entry as the
            # executor; the listener record proves OnSnapshotCreate executed.
            snapshot_result = system.dispatch_event(state, event=event)
            assert not snapshot_result.errors, snapshot_result.errors
            assert any(
                "OnSnapshotCreate" in json.dumps(record, default=str)
                for record in snapshot_result.records
            ), snapshot_result.records
            state = snapshot_result.after_state
            continue
        state = _dispatch(system, state, event)
    return state


def test_healer_attack_record_accumulates_only_the_equipment_healer():
    rules = _rules()
    state, registry, system = _startup_state(rules)
    assert len(_details(state, "holder", _MAIN)) == 1
    assert len(_details(state, "holder", _SUB)) == 1
    assert _dynamic_value(state, "holder", _SUB, "_TotalAmount") == pytest.approx(0.0)

    state = _perform_heal(
        state, registry, system, healer="holder", target="ally", amount=100.0
    )
    assert _dynamic_value(state, "holder", _SUB, "_HealAmount") == pytest.approx(100.0)
    assert _dynamic_value(state, "holder", _SUB, "_TotalAmount") == pytest.approx(100.0)

    state = _perform_heal(
        state, registry, system, healer="holder", target="ally", amount=50.0
    )
    assert _dynamic_value(state, "holder", _SUB, "_TotalAmount") == pytest.approx(150.0)

    # A heal from another unit must not be recorded by this equipment instance.
    state = _perform_heal(
        state, registry, system, healer="other", target="ally", amount=70.0
    )
    assert _dynamic_value(state, "holder", _SUB, "_TotalAmount") == pytest.approx(150.0)
    # The snapshot attach on the committed healer is idempotent: one instance.
    assert len(_details(state, "holder", _SUB)) == 1
    # The snapshot belongs to the healer whose committed heal created it.  A
    # heal from another unit is not observed by this wearer's Main, so no
    # foreign recording instance is created and the holder total is unchanged.
    assert len(_details(state, "other", _SUB)) == 0
    assert _dynamic_value(state, "holder", _SUB, "_TotalAmount") == pytest.approx(150.0)




def test_heal_payload_tamper_is_blocked_by_the_typed_fact():
    rules = _rules()
    state, registry, system = _startup_state(rules)
    result = registry.execute(
        _heal_effect(100.0),
        EffectExecutionContext(
            state, "holder", "test:heal:holder",
            owner_id="ally", param_entity_id="ally", current_action_target_id="ally",
        ),
    )
    assert not result.unsupported, result.records
    state = _commit(state, result.mutations)
    event = next(item for item in result.events if item.event_type == "heal.after")
    assert type(event.heal_event_fact) is HealEventFact
    forged = replace(event, payload={**event.payload, "heal_amount": 99999.0})
    consumed = system.dispatch_event(state, event=forged)
    assert consumed.errors and not consumed.mutations, consumed.errors
    assert _dynamic_value(consumed.after_state, "holder", _SUB, "_TotalAmount") == pytest.approx(0.0)


def test_unproduced_snapshot_event_cannot_attach_the_recording_status():
    rules = _rules()
    state, _registry, system = _startup_state(rules)
    forged = GameEvent(
        "heal.snapshot.created", source_id="holder", target_id="other",
        event_id="forged:snapshot", window="OnSnapshotCreate", process_only=True,
        payload={
            "callback_events": ["OnSnapshotCreate"], "listener_scope": "actor_local",
            "actor_id": "holder", "param_entity_id": "other", "healer_id": "other",
            "snapshot_kind": "heal_data", "snapshot_id": "forged",
            "snapshot_lifetime": {"kind": "source_mutation", "mutation_id": "absent"},
        },
    )
    consumed = system.dispatch_event(state, event=forged)
    assert consumed.errors and not consumed.mutations, consumed.errors
    assert not _details(consumed.after_state, "other", _SUB)


def _add_second_wearer(rules, state, system):
    graph = next(
        item for item in rules.ir.standalone_ability_graphs
        if item.ability_name == "Ability23013"
        and item.source_mode == "mainline_equipment"
    )
    task = next(
        rules.ability_task(task_id) for task_id in graph.task_ids
        if rules.ability_task(task_id) is not None
        and rules.ability_task(task_id).opcode == "AddModifier"
    )
    result = StatusSystem(rules).apply_add_modifier(
        state, rules.effect(task.effect_id),
        application_instance_id="startup:test:other",
        caster_id="other", owner_id="other", param_entity_id="other",
        current_action_target_id="other", source_id="test:startup:other",
        dynamic_values={"1078169603": 0.36}, binding_sources=(),
        retained_runtime_hashes=("1078169603",),
    )
    assert result.ok, result.unsupported
    state = _commit(state, result.mutations)
    for event in result.events:
        state = _dispatch(system, state, event)
    return state


def test_two_wearers_record_only_their_own_heals_without_source_conflict():
    rules = _rules()
    state, registry, system = _startup_state(rules)
    state = _add_second_wearer(rules, state, system)
    assert len(_details(state, "other", _MAIN)) == 1
    assert len(_details(state, "other", _SUB)) == 1
    for _ in range(2):
        state = _perform_heal(
            state, registry, system, healer="holder", target="ally", amount=100.0
        )
    assert _dynamic_value(state, "holder", _SUB, "_TotalAmount") == pytest.approx(200.0)
    assert _dynamic_value(state, "other", _SUB, "_TotalAmount") == pytest.approx(0.0)
    assert len(_details(state, "holder", _SUB)) == 1
    assert len(_details(state, "other", _SUB)) == 1


def _pure_additional_hit(rules, *, bonus: float = 0.0, critical: float = 0.0):
    state, registry, system = _startup_state(rules)
    state = _perform_heal(state, registry, system, healer="holder", target="ally", amount=100.0)
    actor = state.units["holder"]
    extra = {
        "instance_id": "fixture:damage-bonus",
        "modifiers": [
            {
                "bucket": "damage_bonus", "key": "damage_added_ratio", "value": bonus,
                "raw_path": "component:damage-bonus",
            }
        ],
    }
    actor = replace(
        actor,
        resources={**actor.resources, "critical_chance": critical, "critical_damage": 1.0},
        flags={
            **actor.flags,
            "damage_type": "Physical",
            "status_details": [*actor.flags["status_details"], extra],
        },
    )
    state = replace(state, units={**state.units, "holder": actor})
    emission = next(
        item for item in rules.ir.status_damage_emissions
        if item.modifier_name == _MAIN
        and item.scaling_expr.get("final_formula_type") == "ByPureDamage"
    )
    callback = rules.status_callback(emission.callback_id)
    task = rules.status_callback_task(emission.source_task_id)
    detail = _details(state, "holder", _MAIN)[0]
    event = GameEvent(
        "test:attack", source_id="holder", target_id="enemy",
        event_id="test:pure-hit", window="OnListenAfterAttack",
        payload={"actor_id": "holder", "param_entity_id": "enemy", "target_id": "enemy"},
    )
    result = StatusCallbackSystem(rules)._execute_additional_damage_emission(
        state, callback, task, detail, event, emission, None
    )
    assert result.ok, result.errors
    assert not result.rng_events
    payloads = [
        record["payload"] for record in result.records
        if record.get("record_type") == "additional_damage"
    ]
    assert len(payloads) == 1
    return payloads[0], result


def test_pure_additional_damage_ignores_ordinary_bonus_and_crit():
    rules = _rules()
    base, _ = _pure_additional_hit(rules)
    for bonus, critical in ((1.0, 0.0), (0.0, 1.0)):
        changed, result = _pure_additional_hit(rules, bonus=bonus, critical=critical)
        assert changed["final_damage"] == pytest.approx(base["final_damage"]), (
            bonus, critical, base["final_damage"], changed["final_damage"],
        )
        assert not result.rng_events
        assert changed["pure_damage_contract"]["applied"] is True


def test_produced_snapshot_is_in_the_formal_event_transport():
    from hsr.simulator_v8_clean_core.systems.event_dispatch import (
        CALLBACK_EMITTED_EVENT_TYPES,
    )

    state, registry, system = _startup_state(_rules())
    result = registry.execute(
        _heal_effect(100.0),
        EffectExecutionContext(
            state, "holder", "test:heal:holder",
            owner_id="ally", param_entity_id="ally", current_action_target_id="ally",
        ),
    )
    snapshot = next(
        item for item in result.events if item.event_type == "heal.snapshot.created"
    )
    assert "heal.snapshot.created" in MUTATION_BACKED_EVENT_TYPES
    assert "heal.snapshot.created" in CALLBACK_EMITTED_EVENT_TYPES
    assert snapshot.payload["listener_scope"] == "actor_local"
    assert snapshot.payload["param_entity_id"] == "holder"



def _committed_heal_event(rules):
    state, registry, system = _startup_state(rules)
    result = registry.execute(
        _heal_effect(100.0),
        EffectExecutionContext(
            state, "holder", "test:heal:holder",
            owner_id="ally", param_entity_id="ally", current_action_target_id="ally",
        ),
    )
    assert not result.unsupported, result.records
    assert type(next(
        item for item in result.events if item.event_type == "heal.after"
    ).heal_event_fact) is HealEventFact
    state = _commit(state, result.mutations)
    event = next(item for item in result.events if item.event_type == "heal.after")
    return state, system, event


@pytest.mark.parametrize("variant", ["target_id", "event_id", "listener_scope"])
def test_heal_fact_binds_the_full_event_identity(variant):
    state, system, event = _committed_heal_event(_rules())
    if variant == "target_id":
        forged = replace(event, target_id="other")
    elif variant == "event_id":
        forged = replace(event, event_id="different:invocation")
    else:
        forged = replace(
            event, payload={**event.payload, "listener_scope": "global_listener"}
        )
    result = system.dispatch_event(state, event=forged)
    assert result.errors and not result.mutations, (variant, result.errors)
    assert _dynamic_value(result.after_state, "holder", _SUB, "_TotalAmount") == pytest.approx(0.0)


def test_a_replayed_heal_event_does_not_count_twice():
    state, system, event = _committed_heal_event(_rules())
    native = system.dispatch_event(state, event=event)
    assert not native.errors, native.errors
    assert _dynamic_value(native.after_state, "holder", _SUB, "_TotalAmount") == pytest.approx(100.0)
    replay = system.dispatch_event(
        native.after_state,
        event=replace(event, event_id="replayed:invocation"),
    )
    assert replay.errors and not replay.mutations, replay.errors
    assert _dynamic_value(replay.after_state, "holder", _SUB, "_TotalAmount") == pytest.approx(100.0)


def test_a_copied_fact_cannot_mint_an_uncommitted_heal():
    state, system, event = _committed_heal_event(_rules())
    original = event.heal_event_fact
    mutation = replace(
        original.source_mutation, mutation_id="",
        after=float(original.source_mutation.before) + 999,
    )
    forged_fact = None
    try:
        forged_fact = replace(
            original, source_mutation=mutation, heal_amount=999.0,
            snapshot_id="heal_snapshot:" + mutation.stable_id(),
        )
    except (TypeError, ValueError):
        pass
    if forged_fact is not None:
        result = system.dispatch_event(
            state, event=replace(
                event, heal_event_fact=forged_fact,
                payload={
                    **event.payload, "mutation_id": mutation.stable_id(),
                    "heal_amount": 999.0,
                },
            )
        )
        assert result.errors and not result.mutations, result.errors
        assert _dynamic_value(result.after_state, "holder", _SUB, "_TotalAmount") == pytest.approx(0.0)


def _pure_emission(rules):
    return next(
        item for item in rules.ir.status_damage_emissions
        if item.modifier_name == _MAIN
        and item.scaling_expr.get("final_formula_type") == "ByPureDamage"
    )


@pytest.mark.parametrize(
    "final_formula,indirect",
    [("UnsupportedFinalFormula", False), ("ByPureDamage", False)],
)
def test_invalid_final_formula_fails_before_block_consumption(final_formula, indirect):
    from hsr.simulator_v8_clean_core.systems.damage import DamagePacket, DamageSystem
    from hsr.simulator_v8_clean_core.tests.test_damage_formula_reconciled_rules import (
        _r05_block_case,
    )

    rules = _rules()
    state, old_packet = _r05_block_case()
    emission = _pure_emission(rules)
    packet = DamagePacket(
        "source", "target", "Pursued", "additional", amount=10,
        amount_stage="family_base",
        status_damage_emission_id=emission.status_damage_emission_id,
        source_task_id=emission.source_task_id,
        final_formula_type=final_formula, is_indirect=indirect,
        source_frame=old_packet.source_frame, source_trace={"kind": "component"},
    )
    no_block_state = replace(
        state,
        units={
            **state.units,
            "target": replace(state.units["target"], flags={}, statuses=()),
        },
    )
    control = DamageSystem(rules).apply_packet(no_block_state, packet)
    assert not control.ok and not control.mutations, control.to_json()
    blocked = DamageSystem(rules).apply_packet(state, packet)
    assert not blocked.ok and not blocked.mutations and not blocked.rng_events, blocked.to_json()


def test_packet_final_formula_must_match_its_formal_emission():
    from hsr.simulator_v8_clean_core.systems.damage import DamagePacket, DamageSystem

    rules = _rules()
    state, _registry, _system = _startup_state(rules)
    emission = _pure_emission(rules)
    packet = DamagePacket(
        "holder", "enemy", "Pursued", "additional", amount=36,
        amount_stage="family_base",
        status_damage_emission_id=emission.status_damage_emission_id,
        source_task_id=emission.source_task_id,
        status_callback_id=emission.callback_id,
        status_instance_id=_details(state, "holder", _MAIN)[0]["instance_id"],
        modifier_name=_MAIN,
        source_trace={"status_damage_source": emission.source.to_json()},
        final_formula_type="ByPureDamage", is_indirect=True,
    )
    control = DamageSystem(rules).apply_packet(state, packet)
    assert control.ok, control.errors
    downgraded = DamageSystem(rules).apply_packet(
        state, replace(packet, final_formula_type="", is_indirect=False)
    )
    assert not downgraded.ok and not downgraded.mutations, downgraded.to_json()


def test_formula_downgrade_cannot_pass_native_source_audit():
    from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor

    rules = _rules()
    _payload, native = _pure_additional_hit(rules)
    auditor = RuntimeSourceAuditor(rules)
    control = auditor.validate_execution(native.mutations, native.records)
    assert control.ok, control.to_json()
    downgraded = tuple(
        replace(
            mutation,
            metadata={
                **mutation.metadata, "final_formula_type": "", "is_indirect": False,
            },
        )
        for mutation in native.mutations
    )
    assert downgraded
    checked = auditor.validate_execution(downgraded, native.records)
    assert not checked.ok, checked.to_json()



def test_final_formula_audit_binds_the_actual_additional_records():
    """Re-linked native settlement records stay authoritative in the audit."""

    from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor

    rules = _rules()
    _payload, native = _pure_additional_hit(rules)
    auditor = RuntimeSourceAuditor(rules)
    control = auditor.validate_execution(native.mutations, native.records)
    assert control.ok, control.to_json()
    for changed in ("metadata", "settlement", "both"):
        mutations = []
        id_map = {}
        for mutation in native.mutations:
            metadata = dict(mutation.metadata)
            if changed in {"metadata", "both"}:
                metadata.update(final_formula_type="", is_indirect=False)
            linked = replace(mutation, mutation_id="", metadata=metadata)
            mutations.append(linked)
            id_map[mutation.stable_id()] = linked.stable_id()
        records = deepcopy(list(native.records))
        for record in records:
            if record.get("mutation_id") in id_map:
                record["mutation_id"] = id_map[record["mutation_id"]]
            if changed in {"settlement", "both"} and record.get("record_type") == "additional_damage":
                record["payload"]["final_formula_type"] = ""
                record["payload"]["is_indirect"] = False
        linked_ids = {record.get("mutation_id") for record in records}
        assert {mutation.stable_id() for mutation in mutations} <= linked_ids
        checked = auditor.validate_execution(tuple(mutations), tuple(records))
        assert not checked.ok, (changed, checked.to_json())



@pytest.mark.parametrize(
    "modifier", ["MEquip_20018_Sub", "MEquip_21029_Main"]
)
def test_ordinary_indirect_additional_keeps_its_formal_identity(modifier):
    rules = _rules()
    emission = next(
        item for item in rules.ir.status_damage_emissions
        if item.modifier_name == modifier
    )
    assert emission.scaling_expr.get("final_formula_type") == ""
    assert emission.scaling_expr.get("is_indirect") is True
    effects = [
        effect for effect in rules.ir.effects
        if effect.opcode == "AddModifier"
        and isinstance(effect.payload.get("standard"), dict)
        and effect.payload["standard"].get("modifier_name") == modifier
    ]
    assert len(effects) == 1, [effect.effect_id for effect in effects]
    state = BattleState(units={
        "holder": UnitState(
            "holder", "ally", "component:holder", level=80,
            max_hp=2000.0, hp=2000.0, attack=1000.0, speed=100.0,
            resources={"critical_chance": 0.0},
            flags={"damage_type": "Physical"},
        ),
        "enemy": UnitState(
            "enemy", "enemy", "component:enemy", level=80,
            max_hp=10000.0, hp=10000.0, speed=90.0,
        ),
    })
    added = StatusSystem(rules).apply_add_modifier(
        state, effects[0], caster_id="holder", owner_id="holder",
        param_entity_id="holder", current_action_target_id="holder",
        source_id="test:startup:" + modifier,
        application_instance_id="test:startup:" + modifier,
        dynamic_values={"-1470945310": 0.36}, binding_sources=(),
        retained_runtime_hashes=("-1470945310",),
    )
    assert added.ok, added.unsupported
    state = _commit(state, added.mutations)
    dispatcher = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules)))
    for event in added.events:
        state = _dispatch(dispatcher, state, event)
    detail = _details(state, "holder", modifier)[0]
    callback = rules.status_callback(emission.callback_id)
    task = rules.status_callback_task(emission.source_task_id)
    event = GameEvent(
        "test:attack", source_id="holder", target_id="enemy",
        event_id="test:" + modifier, window=callback.event,
        payload={"actor_id": "holder", "param_entity_id": "enemy", "target_id": "enemy"},
    )
    native = StatusCallbackSystem(rules)._execute_additional_damage_emission(
        state, callback, task, detail, event, emission, None
    )
    assert native.ok, native.errors
    records = [
        record for record in native.records
        if record.get("record_type") == "additional_damage"
    ]
    assert records and records[0]["payload"]["is_indirect"] is True
    assert records[0]["payload"]["final_formula_type"] == ""
    audit = RuntimeSourceAuditor(rules).validate_execution(
        native.mutations, native.records
    )
    assert audit.ok, audit.to_json()


@pytest.mark.parametrize(
    "variant",
    ["renamed_type", "wrong_producer", "invalid_payload", "relabeled_downgrade"],
)
def test_additional_audit_requires_an_actual_native_settlement(variant):
    rules = _rules()
    _payload, native = _pure_additional_hit(rules)
    records = deepcopy(list(native.records))
    matched = 0
    for record in records:
        if record.get("record_type") != "additional_damage":
            continue
        matched += 1
        if variant in {"renamed_type", "relabeled_downgrade"}:
            record["record_type"] = "unrelated"
        if variant == "wrong_producer":
            record["source"] = "unrelated"
        if variant == "invalid_payload":
            record["payload"] = 123
        if variant == "relabeled_downgrade":
            record["payload"]["final_formula_type"] = ""
            record["payload"]["is_indirect"] = False
    assert matched == 1
    audit = RuntimeSourceAuditor(rules).validate_execution(
        native.mutations, tuple(records)
    )
    assert not audit.ok, (variant, audit.to_json())
