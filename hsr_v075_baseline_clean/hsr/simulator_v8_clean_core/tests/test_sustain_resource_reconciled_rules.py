"""PR8 arithmetic and fail-closed checks; synthetic fixtures are not kit acceptance."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.executor import CombatExecutor
from hsr.simulator_v8_clean_core.core.model import ActionCommand, BattleState, Mutation, RNGEvent, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.ir import (
    CanonicalIR, ConditionIR, EffectIR, IRSource, StatusCallbackIR,
    StatusCallbackTaskIR, TargetExpressionIR,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.rules.expression_ir import CONDITION_EXPRESSION_NODE_SCHEMA
from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _condition_payload_executable, _effect_coverage_status, _effect_payload, _equipment_task_admission,
    _status_callback_runtime_payload, _target_expression_execution_node,
    _typed_condition_payload,
)


def _state():
    return BattleState(units={
        "caster": UnitState("caster", "ally", "synthetic:caster", max_hp=5000.0, hp=1000.0,
                            defense=2000.0, energy=25.0, max_energy=120.0,
                            resources={"outgoing_healing_ratio": 0.2, "shield_added_ratio": 0.25}),
        "target": UnitState("target", "ally", "synthetic:target", max_hp=2000.0, hp=1800.0,
                            defense=100.0, energy=20.0, max_energy=100.0,
                            resources={"incoming_healing_ratio": 0.1, "energy_regeneration_rate": 0.5,
                                       "shield_added_ratio": 2}),
    })


def _effect(opcode, **fields):
    raw = {"$type": f"RPG.GameCore.{opcode}", "TargetType": {"Alias": "ParamEntity"}, **fields}
    payload = _effect_payload(raw, opcode, "")
    return EffectIR("synthetic:sustain", opcode, payload,
                    IRSource("synthetic:sustain", opcode, "test"),
                    _effect_coverage_status(opcode, payload))


def _execute(effect, state=None, **context_fields):
    state = state or _state()
    before = state.snapshot().to_json()
    context = EffectExecutionContext(state, "caster", "synthetic:test", owner_id="target",
                                     param_entity_id="target", current_action_target_id="target",
                                     **context_fields)
    result = EffectRegistry().execute(effect, context)
    assert state.snapshot().to_json() == before
    return state, result


def _commit_and_replay(state, result):
    assert not result.unsupported, result.records
    assert result.mutations
    reducer = MutationReducer()
    after = reducer.apply_all(state, result.mutations)
    replay = reducer.replay_snapshot(state, result.mutations, after.snapshot().to_json())
    assert replay.ok, replay.errors
    return after


def test_pre_heal_producer_separates_dispatched_trigger_from_new_hp_events():
    from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem

    effect = _effect("HealHP", ModifyValue={"Value": 100})
    state = _state()
    callbacks = StatusCallbackSystem(RuleBook(CanonicalIR(version="pre_heal_dispatch", effects=(effect,))))
    result = callbacks.effect_registry.execute(effect, EffectExecutionContext(
        state, "caster", "synthetic:heal", owner_id="caster", param_entity_id="target",
    ))
    assert not result.unsupported
    before = next(event for event in result.events if event.event_type == "heal.before")
    assert result.dispatched_event_ids == frozenset({before.event_id})
    pending = [event for event in result.events if event.event_type in {"hp.change", "heal.after"}]
    assert len(pending) == 1 and pending[0].event_type == "heal.after"
    assert all(event.to_json()["event_id"] not in result.dispatched_event_ids for event in pending)


@pytest.mark.parametrize("formula,base", [
    ("HealByHealerMaxHP", 5000), ("HealByTargetMaxHP", 2000), ("HealByTargetLostHP", 200),
])
def test_ratio_heal_adds_flat_before_bonus_and_audits_overheal(formula, base):
    effect = _effect("HealHP", FormulaType=formula, HealPercentage={"Value": 0.1}, ModifyValue={"Value": 100})
    state, result = _execute(effect)
    after = _commit_and_replay(state, result)
    offered = (base * 0.1 + 100) * 1.3
    realized = min(200, offered)
    details = result.mutations[0].metadata["formula_details"]
    assert details["base_amount"] == pytest.approx(base * 0.1 + 100)
    assert details["offered_healing"] == pytest.approx(offered)
    assert details["realized_healing"] == pytest.approx(realized)
    assert details["overheal"] == pytest.approx(offered - realized)
    assert after.units["target"].hp == pytest.approx(1800 + realized)
    assert after.units["caster"] == state.units["caster"]


def test_source_backed_recipient_heal_penalty_uses_one_additive_factor():
    from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackSystem
    from hsr.simulator_v8_clean_core.systems.summon_runtime import empty_summon_runtime

    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    source_path = "Config/ConfigAbility/Monster/Monster_W3_Sam_00_Ability.json"
    document = json.loads((root / source_path).read_text())
    modifier_name = "Monster_W3_Sam_00_BurningBP"
    callbacks = document["GlobalModifiers"][modifier_name]["_CallbackList"]
    callback_index, raw_callback = next(
        (index, item) for index, item in enumerate(callbacks)
        if item["Event"] == "OnBeforeBeingHeal"
    )
    raw_predicate_task = raw_callback["CallbackConfig"][0]
    raw_condition = raw_predicate_task["Predicate"]
    raw_modifier = raw_predicate_task["SuccessTaskList"][0]
    assert raw_modifier["$type"] == "RPG.GameCore.ModifyHealData"
    assert set(raw_modifier) == {"$type", "Target_HealTakenRatio"}
    admission, reason = _equipment_task_admission(
        "OnBeforeBeingHeal", "ModifyHealData", raw_modifier, modifier_name=modifier_name,
    )
    assert admission == "executable", reason

    alias_path = "Config/GlobalConfig/TargetAliasConfig.json"
    aliases = json.loads((root / alias_path).read_text())["AliasDict"]
    target_expressions = []
    for alias in ("ParamEntity", "ParamEntityActualOwner", "ModifierOwnerEntity"):
        raw_alias = aliases[alias]
        alias_source = IRSource(alias_path, raw_alias["$type"], alias, {
            "json_path": f"$.AliasDict.{alias}", "source_raw_id": alias,
        })
        node = _target_expression_execution_node(raw_alias, alias_source)
        target_expressions.append(TargetExpressionIR(
            f"test:alias:{alias}", node.expression_kind, alias, alias_source,
            node=node, coverage_status="executable",
        ))

    path = f"$.GlobalModifiers.{modifier_name}._CallbackList[{callback_index}].CallbackConfig[0]"
    callback_source = IRSource(source_path, "OnBeforeBeingHeal", modifier_name, {"json_path": path})
    condition_source = IRSource(source_path, "ByCompareTarget", modifier_name, {
        "json_path": f"{path}.Predicate",
    })
    condition = ConditionIR(
        "test:sam:heal-owner", "ByCompareTarget",
        _typed_condition_payload(
            "ByCompareTarget", {key: value for key, value in raw_condition.items() if key != "$type"},
            source=condition_source,
        ), condition_source, coverage_status="executable",
        expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA,
    )
    assert _condition_payload_executable("ByCompareTarget", condition.payload)
    predicate_id, modifier_id = "test:sam:predicate", "test:sam:modifier"
    callback = StatusCallbackIR(
        "test:sam:being-healed", modifier_name, "OnBeforeBeingHeal",
        (predicate_id,), callback_source, (callback_index, 0),
        coverage_status="executable", source_mode="mainline_monster_ability",
        admission_status="executable",
    )
    predicate = StatusCallbackTaskIR(
        predicate_id, callback.callback_id, modifier_name, callback.event, 0,
        "CallbackConfig[0]", "root", "PredicateTaskList", callback_source,
        condition_id=condition.condition_id, success_task_ids=(modifier_id,),
        child_task_ids=(modifier_id,), coverage_status="executable",
    )
    modifier_source = IRSource(source_path, "ModifyHealData", modifier_name, {
        "json_path": f"{path}.SuccessTaskList[0]",
    })
    modifier = StatusCallbackTaskIR(
        modifier_id, callback.callback_id, modifier_name, callback.event, 0,
        "CallbackConfig[0].SuccessTaskList[0]", "success", "ModifyHealData", modifier_source,
        parent_task_id=predicate_id, coverage_status="executable",
        task_payload=_status_callback_runtime_payload(raw_modifier),
    )
    effect = _effect("HealHP", ModifyValue={"Value": 1000})
    rules = RuleBook(CanonicalIR(
        "test:sam:heal-penalty", effects=(effect,), conditions=(condition,),
        target_expressions=tuple(target_expressions), status_callbacks=(callback,),
        status_callback_tasks=(predicate, modifier),
    ))
    state = _state()
    state = replace(state, global_flags={"summon_runtime": empty_summon_runtime()}, units={
        **state.units,
        "caster": replace(state.units["caster"], resources={"outgoing_healing_ratio": 0.5}),
        "target": replace(state.units["target"], hp=1000.0, resources={}, flags={
            "status_details": [{
                "modifier_name": modifier_name, "instance_id": "test:sam:burning",
                "owner_id": "target", "caster_id": "target",
                "dynamic_values": {"__by_hash": {"1260053363": 0.9}},
                "source_trace": {"source_path": source_path, "raw_id": modifier_name},
            }],
        }),
    })
    result = StatusCallbackSystem(rules).effect_registry.execute(
        effect, EffectExecutionContext(
            state, "caster", "test:heal", owner_id="caster", param_entity_id="target",
        ),
    )
    assert not result.unsupported, result.records
    assert len([event for event in result.events if event.event_type == "heal.before"]) == 1
    after = _commit_and_replay(state, result)
    details = result.mutations[-1].metadata["formula_details"]
    assert details["healing_multiplier"] == pytest.approx(0.6)
    assert details["offered_healing"] == pytest.approx(600)
    assert details["realized_healing"] == pytest.approx(600)
    assert after.units["target"].hp == pytest.approx(1600)
    assert any(record.get("record_type") == "heal_modifier" and
               record["payload"]["heal_field"] == "Target_HealTakenRatio"
               for record in result.records)


@pytest.mark.parametrize("formula,base", [
    ("ShieldByCasterDefence", 2000), ("ShieldByCasterMaxHP", 5000), ("ShieldByTargetMaxHP", 2000),
])
def test_ratio_shield_adds_flat_before_creator_bonus(formula, base):
    effect = _effect("InitShield", FormulaType=formula,
                     ShieldPercentage={"Value": 0.608}, ShieldValue={"Value": 845.5})
    state, result = _execute(effect)
    after = _commit_and_replay(state, result)
    details = result.mutations[0].metadata["formula_details"]
    assert details["base_amount"] == pytest.approx(base * 0.608 + 845.5)
    assert details["shield_multiplier"] == 1.25
    assert result.mutations[0].metadata["amount"] == pytest.approx((base * 0.608 + 845.5) * 1.25)
    assert after.units["target"].shield_instances


def test_omitted_heal_formula_accepts_only_flat_and_internal_heal_stays_valid():
    effect = _effect("HealHP", ModifyValue={"Value": 100})
    state, result = _execute(effect)
    assert _commit_and_replay(state, result).units["target"].hp == pytest.approx(1930)
    assert effect.payload["standard"]["formula_type_source"] == "reconciled_flat_only_heal_model"
    internal = EffectIR("internal:heal", "Heal", {"standard": {
        "kind": "heal", "target_alias": "ParamEntity", "amount": {"kind": "fixed", "value": 100},
    }}, IRSource("synthetic:internal", "Heal", "test"), "executable")
    state, result = _execute(internal)
    assert _commit_and_replay(state, result).units["target"].hp == pytest.approx(1930)


@pytest.mark.parametrize("fields", [
    {"HealPercentage": {"Value": 0.1}},
    {"HealPercentage": {"Value": 0.1}, "ModifyValue": {"Value": 100}},
    {"FormulaType": None, "ModifyValue": {"Value": 100}},
    {"FormulaType": "HealByHealerMaxHP", "HealPercentage": {"Value": 0.1}, "ModifyValue": {}},
])
def test_ambiguous_or_malformed_heal_blocks_without_mutation_or_rng(fields):
    state, result = _execute(_effect("HealHP", **fields))
    assert result.unsupported
    assert not result.mutations
    assert not result.rng_events
    assert MutationReducer().replay_snapshot(state, (), state.snapshot().to_json()).ok


@pytest.mark.parametrize("opcode,ratio_key,flat_key,formula", [
    ("HealHP", "HealPercentage", "ModifyValue", "HealByHealerMaxHP"),
    ("InitShield", "ShieldPercentage", "ShieldValue", "ShieldByCasterDefence"),
])
def test_declared_flat_missing_dynamic_binding_does_not_silently_drop(opcode, ratio_key, flat_key, formula):
    dynamic = {"IsDynamic": True, "PostfixExpr": {"OpCodes": "AQAR", "FixedValues": [], "DynamicHashes": [987654]}}
    effect = _effect(opcode, FormulaType=formula, **{ratio_key: {"Value": 0.1}, flat_key: dynamic})
    _, result = _execute(effect)
    assert result.unsupported
    assert not result.mutations and not result.rng_events
    assert "flat_addition_evaluation_failed" in str(result.records)


@pytest.mark.parametrize("field,value,expected,err", [
    ("AddValue", 10, 35, 1.5), ("FixedAddValue", 10, 30, 1),
    ("AddMaxSPRatio", 0.1, 35, 1.5), ("FixedAddMaxSPRatio", 0.1, 30, 1),
    ("SetValue", 10, 10, 1), ("FixedSetValue", 10, 10, 1),
    ("SetMaxSPRatio", 0.1, 10, 1), ("FixedSetMaxSPRatio", 0.1, 10, 1),
    ("AddValue", -10, 10, 1),
])
def test_energy_add_set_and_fixed_grants_use_distinct_err_policy(field, value, expected, err):
    state, result = _execute(_effect("ModifySPNew", **{field: {"Value": value}}))
    after = _commit_and_replay(state, result)
    assert after.units["target"].energy == pytest.approx(expected)
    assert result.mutations[0].metadata["formula_details"]["energy_regeneration_multiplier"] == err
    assert after.units["caster"] == state.units["caster"]


@pytest.mark.parametrize("fields", [
    {"AddValue": {"Value": 10}, "FixedAddValue": {"Value": 10}},
    {"SetValue": {"Value": 10}, "AddMaxSPRatio": {"Value": 0.1}},
    {"AddValue": {"Value": 10}, "FixedAddRatio": {"Value": 0.1}},
])
def test_mixed_energy_formula_fields_block_instead_of_dropping_operands(fields):
    _, result = _execute(_effect("ModifySPNew", **fields))
    assert result.unsupported and not result.mutations and not result.rng_events
    assert "resource_combined_formula_not_supported" in str(result.records)


def test_real_march_shield_raw_lowering_to_mutation_and_replay():
    source_path = "Config/ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json"
    root = Path(__file__).resolve().parents[4]
    document = json.loads((root / "turnbasedgamedata-main" / source_path).read_text())

    def occurrences(value, path="$."):
        if isinstance(value, dict):
            if value.get("$type") == "RPG.GameCore.InitShield" and value.get("FormulaType") == "ShieldByCasterDefence":
                yield path, value
            for key, item in value.items():
                yield from occurrences(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from occurrences(item, f"{path}[{index}]")

    matches = list(occurrences(document))
    assert len(matches) == 1
    occurrence, raw = matches[0]
    payload = _effect_payload(raw, "InitShield", "")
    effect = EffectIR("raw:march:shield", "InitShield", payload,
                      IRSource(source_path, "InitShield", occurrence,
                               evidence={"test_binding_basis": "PR8 confirmed coefficients; not full character admission"}),
                      _effect_coverage_status("InitShield", payload))
    state, result = _execute(effect, dynamic_values={"2126266902": 845.5, "-2062890509": 0.608})
    _commit_and_replay(state, result)
    mutation = result.mutations[0]
    assert mutation.metadata["amount"] == pytest.approx((2000 * 0.608 + 845.5) * 1.25)
    assert mutation.metadata["effect_source"]["source_path"] == source_path
    assert mutation.metadata["effect_source"]["raw_id"] == occurrence


def test_stack_shield_lowering_preserves_owner_and_capacity():
    raw = {"$type": "RPG.GameCore.StackShield", "StackValue": {"Value": 100}, "MaxStack": {"Value": 150}}
    payload = _effect_payload(raw, "StackShield", "synthetic:shield-owner")
    assert payload["standard"]["target_alias"] == "ModifierOwnerEntity"
    effect = EffectIR("synthetic:stack", "StackShield", payload,
                      IRSource("synthetic:stack", "StackShield", "test"),
                      _effect_coverage_status("StackShield", payload))
    context = {"event_payload": {"modifier_name": "synthetic:shield-owner", "status_instance_id": "synthetic:status"}}
    state, result = _execute(effect, **context)
    assert result.unsupported and not result.mutations
    assert "shield_bonus_stack_cap_policy_unconfirmed" in str(result.records)
    caster = state.units["caster"]
    state = replace(state, units={**state.units, "caster": replace(
        caster, resources={**caster.resources, "shield_added_ratio": 0.0},
    )})
    _, result = _execute(effect, state, **context)
    after = _commit_and_replay(state, result)
    assert result.mutations[0].metadata["formula_details"]["max_capacity"] == pytest.approx(150.0)
    _, repeated = _execute(effect, after, **context)
    final = _commit_and_replay(after, repeated)
    assert len(final.units["target"].shield_instances) == 1
    shield = final.units["target"].shield_instances[0]
    assert shield["remaining"] == pytest.approx(150.0)


def test_stack_shield_dynamic_cap_missing_binding_blocks_without_mutation():
    cap = {"IsDynamic": True, "PostfixExpr": {"OpCodes": "AQAR", "FixedValues": [], "DynamicHashes": [777]}}
    _, result = _execute(_effect("StackShield", StackValue={"Value": 100}, MaxStack=cap))
    assert result.unsupported and not result.mutations and not result.rng_events
    assert "shield_max_capacity_evaluation_failed" in str(result.records)


def test_formal_executor_rejects_unadmitted_action_without_any_state_change():
    # This proves the public action gate, not an admitted action's sustain callback.
    effect = _effect("HealHP", HealPercentage={"Value": 0.1})
    rules = RuleBook(CanonicalIR(version="synthetic:sustain-gate", effects=(effect,)))
    state = replace(_state(), queues={"pending": ({"synthetic": "must-remain"},)},
                    rng_state="synthetic:unchanged", skill_points=2)
    before = state.snapshot().to_json()
    command = ActionCommand("caster", "synthetic:unadmitted-action", 1, ("target",))
    after, transition = CombatExecutor(rules).execute(command, state)
    assert transition.outcome.category == "blocked"
    assert transition.outcome.reason_codes
    assert after.snapshot().to_json() == before == transition.after.to_json()
    assert after.skill_points == 2 and after.queues == state.queues and after.rng_state == state.rng_state
    assert not transition.transaction.mutations and not transition.rng_events
    assert MutationReducer().replay_snapshot(state, (), transition.after.to_json()).ok


@pytest.mark.parametrize("missing_flat_binding", [False, True])
def test_eventful_transaction_commits_complete_producer_or_discards_every_plan(missing_flat_binding):
    """Transaction API coverage, not proof of an admitted ActionCommand callback graph."""
    flat = {"IsDynamic": True, "PostfixExpr": {"OpCodes": "AQAR", "FixedValues": [], "DynamicHashes": [777]}}
    effect = _effect("HealHP", FormulaType="HealByHealerMaxHP", HealPercentage={"Value": 0.01}, ModifyValue=flat)
    rules = RuleBook(CanonicalIR(version="synthetic:eventful-sustain", effects=(effect,)))
    state = replace(_state(), queues={"pending": ("existing",)}, rng_state="synthetic:rng-before")
    before = state.snapshot().to_json()
    produced = EffectRegistry().execute(effect, EffectExecutionContext(
        state, "caster", "synthetic:heal-operation", param_entity_id="target",
        dynamic_values={} if missing_flat_binding else {"777": 10},
    ))
    assert bool(produced.unsupported) is missing_flat_binding
    planned = (
        Mutation("set", ("skill_points",), 3, 2, "synthetic planned SP cost", "synthetic:transaction"),
        Mutation("set", ("queues", "pending"), ["existing"], ["planned"], "synthetic queue plan", "synthetic:transaction"),
        Mutation("set", ("rng_state",), state.rng_state, "synthetic:rng-after", "synthetic RNG plan", "synthetic:transaction"),
        *produced.mutations,
    )
    planned_rng = RNGEvent("synthetic", "synthetic:transaction", 0.25,
                           event_id="synthetic:rng", before_state=state.rng_state, after_state="synthetic:rng-after")
    # The positive arm proves these exact auxiliary plans are valid and committable.
    assert MutationReducer().apply_all_result(state, planned).ok
    result = CombatExecutor(rules).commit_eventful_transition(
        state, mutations=planned, events=produced.events, records=produced.records,
        rng_events=(planned_rng,), producer_kind="effect", producer_id="caster",
        actor_id="caster",
        producer_ok=not produced.unsupported,
        blocked_reason=produced.unsupported[0] if produced.unsupported else "",
    )
    if missing_flat_binding:
        assert result.errors and not result.mutations and not result.rng_events
        assert result.after_state.snapshot().to_json() == before
        assert result.after_state.skill_points == 3
        assert result.after_state.queues == state.queues
        assert result.after_state.rng_state == state.rng_state
    else:
        assert not result.errors, result.errors
        assert len(result.mutations) == len(planned)
        assert result.rng_events == (planned_rng,)
        assert result.after_state.skill_points == 2
        assert result.after_state.queues["pending"] == ("planned",)
        assert result.after_state.rng_state == "synthetic:rng-after"
        assert result.after_state.units["target"].hp == pytest.approx(1878)
    assert state.snapshot().to_json() == before
    assert MutationReducer().replay_snapshot(
        state, result.mutations, result.after_state.snapshot().to_json(),
    ).ok


def test_eventful_commit_keeps_distinct_producer_sources_for_one_target():
    effect = _effect("HealHP", ModifyValue={"Value": 10})
    state = _state()
    current = state
    mutations, events, records = [], [], []
    for source in ("operation:first", "operation:second"):
        result = EffectRegistry().execute(effect, EffectExecutionContext(
            current, "caster", source, param_entity_id="target",
        ))
        assert not result.unsupported
        mutations.extend(result.mutations)
        events.extend(result.events)
        records.extend(result.records)
        current = MutationReducer().apply_all(current, result.mutations)
    rules = RuleBook(CanonicalIR(version="synthetic:multi-source", effects=(effect,)))
    committed = CombatExecutor(rules).commit_eventful_transition(
        state, mutations=tuple(mutations), events=tuple(events), records=tuple(records),
        producer_kind="effect", producer_id="transaction", actor_id="caster",
    )
    assert not committed.errors, committed.errors
    assert committed.after_state.snapshot().to_json() == current.snapshot().to_json()
    assert {event.source_id for event in committed.events if event.event_type == "heal.after"} == {
        "operation:first", "operation:second",
    }
