"""Real Castorice Remodifier/InfectModifier copies the talent buff to Pollux."""
import json
import math
from dataclasses import replace
from pathlib import Path

from hsr.simulator_v8_clean_core.core.model import BattleState, TargetResolution, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.rules.ir import (
    AbilityPhaseIR, ActionDefinitionIR, CanonicalIR, IRSource,
)
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.ability import AbilityTaskSystem, _FormalAbilityInvocation
from hsr.simulator_v8_clean_core.systems.effect import EffectRegistry
from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
from hsr.simulator_v8_clean_core.systems.status import StatusInstance, StatusSystem, _runtime_modifiers
from hsr.simulator_v8_clean_core.systems.summon_runtime import empty_summon_runtime
from hsr.simulator_v8_clean_core.systems.task_graph import TaskGraphExecutionContext
from hsr.simulator_v8_clean_core.tests.test_status_shared_immunity import _formal_immunity_source
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _lower_status_event_families, _synchronize_effect_target_expression_metadata,
)
from hsr.simulator_v8_clean_core.tbgd.target_source import close_target_expression_language
from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import (
    attach_task_graph_catalog, build_complete_task_graph_catalog,
    materialize_ability_phase_task_graph, materialize_status_callback_task_graph,
    merge_task_graph_slices,
)

ROOT = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
RELATIVE = "Config/ConfigAbility/Avatar/Avatar_Castorice_00_Ability.json"
BUFF = "MAvatar_Castorice_00_Passive_AllDamageTypeAddedRatio"
SERVANT = "summon:servant"
CASTER = "castorice"


def _lower_ability_task(lowerer, definition, ability_index, task_index, task_path):
    document = lowerer._character_formal_task_source_context().documents[RELATIVE]
    ability = document["AbilityList"][ability_index]
    task = ability["OnStart"][task_index]
    lowered = lowerer._lower_ability_task_tree(
        task, definition=definition, phase_id="phase", ability_name=ability["Name"],
        ability_path=RELATIVE, ability_index=ability_index, callback_kind="OnStart",
        task_index=task_index, task_path=task_path, branch="root", parent_task_id="",
        formal_source_context=lowerer._character_formal_task_source_context(),
        source_json_path=f"$.AbilityList[{ability_index}].OnStart[{task_index}]",
    )
    return ability, lowered


def _world(tmp_path):
    lowering, sources, lowered, languages = _formal_immunity_source(tmp_path, RELATIVE, 1407)
    on_stack = next(row for row in lowered.status_callbacks
                    if row.modifier_name == BUFF and row.event == "OnStack")
    on_stack_tasks = tuple(row for row in lowered.status_callback_tasks
                           if row.callback_id == on_stack.callback_id)
    assert on_stack_tasks and all(row.coverage_status == "executable" for row in on_stack_tasks)
    document = lowering._character_formal_task_source_context().documents[RELATIVE]

    definition = ActionDefinitionIR(
        "validation:castorice", "validation:castorice", 1, "BPSkill", "Support", "single",
        0, 0, 0, 0, (), (), (), None,
        IRSource(RELATIVE, "AbilityList", "Avatar_Castorice_00_Skill03_Phase02",
                 {"json_path": "$.AbilityList[8]", "ability_index": 8}),
    )
    ability, lowered_task = _lower_ability_task(lowering, definition, 8, 6, "OnStart[6]")
    remodifier = next(row for row in lowered_task.ability_tasks if row.opcode == "Remodifier")
    infect = next(row for row in lowered_task.ability_tasks if row.opcode == "InfectModifier")
    assert remodifier.coverage_status == infect.coverage_status == "executable"
    infect_effect = next(row for row in lowered_task.effects if row.opcode == "InfectModifier")
    standard = infect_effect.payload["standard"]
    assert standard["operation"] == "infect_modifier"
    assert standard["source_shape_admitted"] is True
    assert standard["use_param_modifier"] is True
    assert standard["infect_type"] == "Override"
    assert standard["status_dispel_filter"] == "AnyStatus"

    # The maze ability uses the same Remodifier -> InfectModifier source shape.
    maze = document["AbilityList"][10]
    maze_task = maze["OnStart"][10]
    maze_lowered = lowering._lower_ability_task_tree(
        maze_task, definition=replace(definition, action_id="validation:castorice-maze"),
        phase_id="phase", ability_name=maze["Name"], ability_path=RELATIVE, ability_index=10,
        callback_kind="OnStart", task_index=10, task_path="OnStart[10]", branch="root",
        parent_task_id="", formal_source_context=lowering._character_formal_task_source_context(),
        source_json_path="$.AbilityList[10].OnStart[10]",
    )
    maze_infect = next(row for row in maze_lowered.ability_tasks if row.opcode == "InfectModifier")
    assert maze_infect.coverage_status == "executable"

    closed = [close_target_expression_language(row, languages) for row in lowered_task.target_expressions]
    closed_status = [close_target_expression_language(row, languages)
                     for row in lowered.target_expressions]
    effects = _synchronize_effect_target_expression_metadata(lowered_task.effects, closed)
    assert all(row.coverage_status == "executable" for row in effects)
    phase = AbilityPhaseIR("phase", "binding", definition.action_id, 1, ability["Name"], 0,
        {}, {}, {}, lowered_task.ability_tasks[0].source,
        task_ids=tuple(row.task_id for row in lowered_task.ability_tasks),
        invocation_role="action_root")
    canonical = CanonicalIR(
        "castorice-infect-component",
        action_definitions=(definition,), ability_phases=(phase,),
        ability_tasks=tuple(lowered_task.ability_tasks),
        effects=tuple((*lowered.effects, *effects)),
        conditions=tuple((*lowered.conditions, *lowered_task.conditions)),
        status_callbacks=(on_stack,), status_callback_tasks=on_stack_tasks,
        status_event_families=tuple(_lower_status_event_families([on_stack], list(on_stack_tasks))),
        target_expressions=tuple(closed) + tuple(closed_status)
            + tuple(row.expression for row in languages),
        entities=tuple(lowered.entities),
    )
    ability_catalog = materialize_ability_phase_task_graph(
        sources, canonical, phase_id="phase", callback_kind="OnStart",
        source_snapshot=lowering._character_ability_raw_snapshot)
    assert len(ability_catalog.graphs) == 1, ability_catalog.entry_materializations
    graph = ability_catalog.graphs[0]
    assert all(row.materialization_status == "materialized" for row in graph.nodes)
    status_catalog = materialize_status_callback_task_graph(
        sources, canonical, callback_id=on_stack.callback_id,
        source_snapshot=lowering._character_ability_raw_snapshot)
    assert len(status_catalog.graphs) == 1, [
        (entry.blocked_reason, entry.status) for entry in status_catalog.entry_materializations]
    complete = build_complete_task_graph_catalog(
        sources, lowering._character_ability_raw_snapshot)
    merged = merge_task_graph_slices(complete, (ability_catalog, status_catalog))
    rules = RuleBook(attach_task_graph_catalog(canonical, merged))
    return {"rules": rules, "graph": graph, "on_stack": on_stack,
            "on_stack_tasks": on_stack_tasks,
            "infect_effect": infect_effect, "definition": definition}


def _summon_runtime():
    runtime = empty_summon_runtime()
    runtime["entities"][SERVANT] = {
        "runtime_id": SERVANT, "unit_id": SERVANT, "summon_kind": "servant",
        "owner_id": CASTER, "summoner_id": CASTER, "team_side": "ally",
        "status": "active", "targetability": {"targetable": True},
    }
    runtime["by_owner"][CASTER] = [SERVANT]
    runtime["servants"][SERVANT] = dict(runtime["entities"][SERVANT])
    runtime["last_servants"] = [SERVANT]
    return runtime


def _source_status(on_stack_id, **overrides):
    status = StatusInstance(
        "buff:source", "modifier:" + BUFF, BUFF, CASTER, "status_callback_status:source", CASTER,
        stacks=2, max_stacks=3, duration=3.0, remaining_duration=3.0,
        duration_unit="turn", life_step_moment="ModifierPhase1End",
        duration_admission={"admission_status": "executable", "source_kind": "component_fixture"},
        stack_policy="single_instance", refresh_policy="replace_by_caster",
        lifecycle_state="active", status_type="Buff", status_category="buff",
        # 2128130574 = MDF_PropertyValue, 1662446059 = MDF_Layer; the real
        # OnStack expression multiplies them, so 0.2 x 2 layers = 0.4.
        dynamic_values={
            "__by_name": {}, "__by_hash": {"2128130574": 0.2, "1662446059": 1.0},
            "2128130574": 0.2, "1662446059": 1.0,
        },
        # Formal _runtime_modifiers entries only carry the raw callback path and
        # the copied layer value is stale until the instance's OnStack runs.
        modifiers=({"bucket": "damage_bonus", "key": "damage_added_ratio",
                    "scope": "actor", "value": 0.2, "property": "AllDamageTypeAddedRatio",
                    "raw_path": "_CallbackList[0].CallbackConfig[1]",
                    "applied_reason": "status_stack_property",
                    "condition": "property=AllDamageTypeAddedRatio"},),
        trigger_ids_by_event={"OnStack": (on_stack_id,)},
        source_trace={"modifier_name": BUFF, "fixture_component": True},
    )
    return replace(status, **overrides).to_json()


def _state(world):
    source = _source_status(world["on_stack"].callback_id)
    servant = UnitState(SERVANT, "ally", "servant:11407", hp=500, max_hp=500, flags={
        "owner_id": CASTER, "summoner_id": CASTER, "summon_kind": "servant",
        "team_side": "ally", "servant_definition_id": "servant:11407",
    })
    return BattleState(global_flags={"summon_runtime": _summon_runtime()}, units={
        CASTER: UnitState(CASTER, "ally", "avatar:1407", hp=1000, max_hp=1000,
            statuses=(source["status_id"],), flags={"status_details": [source]}),
        SERVANT: servant,
        "other": UnitState("other", "ally", "fixture:other", hp=100, max_hp=100),
    })


def _invocation(world):
    return _FormalAbilityInvocation(
        "status_nested", CASTER, world["definition"].action_id, 1,
        TargetResolution(requested=(SERVANT,), selectable=(SERVANT,), legal=(SERVANT,)),
    )


def _execute(world, state):
    runtime = AbilityTaskSystem(world["rules"], EffectRegistry(StatusSystem(world["rules"])))
    hooks = runtime._formal_task_graph_hooks(invocation=_invocation(world))
    return runtime.task_graph_executor.execute(
        state, world["graph"], TaskGraphExecutionContext("component:castorice"), hooks)


def test_real_castorice_infect_copies_exact_instance_to_servant(tmp_path):
    world = _world(tmp_path)
    state = _state(world)
    result = _execute(world, state)
    assert result.ok, result.errors
    source = state.units[CASTER].flags["status_details"][0]
    copied = [row for row in result.after_state.units[SERVANT].flags["status_details"]
              if row["modifier_name"] == BUFF]
    assert len(copied) == 1
    copy = copied[0]
    assert copy["caster_id"] == source["caster_id"] == CASTER
    assert copy["stacks"] == source["stacks"] == 2
    assert copy["remaining_duration"] == source["remaining_duration"] == 3.0
    assert copy["duration"] == source["duration"] == 3.0
    assert copy["dynamic_values"] == source["dynamic_values"]
    assert copy["modifiers"] == source["modifiers"]
    assert copy["behavior_flags"] == source["behavior_flags"]
    assert copy["owner_id"] == SERVANT and copy["lifecycle_state"] == "active"
    assert result.after_state.units[CASTER] == state.units[CASTER]
    assert result.after_state.units["other"] == state.units["other"]
    infection = next(record for record in result.settlement_records
                     if record.record_type == "status_infection")
    payload = infection.to_json()["payload"]
    assert payload["operation"] == "add"
    assert payload["source_instance_id"] == source["instance_id"]
    assert payload["copied"]["stacks"] == 2
    audit = RuntimeSourceAuditor(world["rules"]).validate_execution(
        result.mutations, tuple(record.to_json() for record in result.settlement_records))
    assert audit.ok, audit.to_json()

    # The copied instance's own OnStack effect still runs from the formal
    # lifecycle event, updating only its own computed stack property.
    on_stack = next(event for event in result.events if event.window == "OnStack")
    dispatched = EventDispatchSystem(
        world["rules"], EffectRegistry(StatusSystem(world["rules"]))).dispatch_event(
            result.after_state, event=on_stack)
    assert not dispatched.errors, dispatched.errors
    after = [row for row in dispatched.after_state.units[SERVANT].flags["status_details"]
             if row["modifier_name"] == BUFF]
    assert len(after) == 1
    stack_task = next(task for task in world["on_stack_tasks"] if task.opcode == "StackProperty")
    produced = [item for item in after[0]["modifiers"]
                if item.get("producer_task_id") == stack_task.task_id]
    assert len(produced) == 1
    # Copied MDF_PropertyValue (0.2) and two copied layers drive the real
    # AllDamageTypeAddedRatio contribution on the servant.
    assert produced[0]["value"] == 0.4
    assert after[0]["dynamic_values"]["__by_hash"]["1662446059"] == 2.0
    assert after[0]["stacks"] == 2 and after[0]["remaining_duration"] == 3.0
    assert dispatched.after_state.units[CASTER] == state.units[CASTER]
    audit = RuntimeSourceAuditor(world["rules"]).validate_execution(
        dispatched.mutations, dispatched.records)
    assert audit.ok, audit.to_json()


def test_real_castorice_override_refreshes_existing_servant_copy(tmp_path):
    world = _world(tmp_path)
    state = _state(world)
    first = _execute(world, state)
    assert first.ok, first.errors
    copy_id = next(row["instance_id"] for row in first.after_state.units[SERVANT].flags["status_details"]
                   if row["modifier_name"] == BUFF)
    source = state.units[CASTER].flags["status_details"][0]
    upgraded_source = {**source, "stacks": 3, "duration": 2.0, "remaining_duration": 2.0}
    upgraded = replace(first.after_state, units={
        **first.after_state.units,
        CASTER: replace(first.after_state.units[CASTER],
            flags={"status_details": [upgraded_source]}),
    })
    second = _execute(world, upgraded)
    assert second.ok, second.errors
    copies = [row for row in second.after_state.units[SERVANT].flags["status_details"]
              if row["modifier_name"] == BUFF]
    assert len(copies) == 1 and copies[0]["instance_id"] == copy_id
    assert copies[0]["stacks"] == 3 and copies[0]["remaining_duration"] == 2.0
    infection = next(record for record in second.settlement_records
                     if record.record_type == "status_infection")
    assert infection.to_json()["payload"]["operation"] == "replace"
    assert infection.to_json()["payload"]["replaced_instance_id"] == copy_id
    audit = RuntimeSourceAuditor(world["rules"]).validate_execution(
        second.mutations, tuple(record.to_json() for record in second.settlement_records))
    assert audit.ok, audit.to_json()


def test_real_castorice_formal_property_entry_updates_in_place_and_audits(tmp_path):
    world = _world(tmp_path)
    state = _state(world)
    first = _execute(world, state)
    assert first.ok, first.errors
    copy = next(row for row in first.after_state.units[SERVANT].flags["status_details"]
                if row["modifier_name"] == BUFF)
    copy_id = copy["instance_id"]
    stack_task = next(task for task in world["on_stack_tasks"]
                      if task.opcode == "StackProperty")
    assert copy["modifiers"][0]["raw_path"] == "_CallbackList[0].CallbackConfig[1]"
    assert "producer_task_id" not in copy["modifiers"][0]

    system = StatusSystem(world["rules"])
    stacked = system.modify_modifier_value(
        first.after_state, SERVANT, BUFF, "Layer", "Add", 1,
        caster_id=CASTER, metadata={"fixture": "layer_increase"},
        status_instance_id=copy_id,
    )
    assert stacked.ok, stacked.unsupported
    stacked_state = MutationReducer().apply_all(first.after_state, stacked.mutations)
    on_stack = next(event for event in stacked.events if event.window == "OnStack")
    dispatched = EventDispatchSystem(
        world["rules"], EffectRegistry(StatusSystem(world["rules"]))).dispatch_event(
            stacked_state, event=on_stack)
    assert not dispatched.errors, dispatched.errors
    updated = next(row for row in dispatched.after_state.units[SERVANT].flags["status_details"]
                   if row["instance_id"] == copy_id)
    assert updated["stacks"] == 3
    assert len(updated["modifiers"]) == 1
    entry = updated["modifiers"][0]
    assert entry["raw_path"] == "_CallbackList[0].CallbackConfig[1]"
    assert entry["producer_task_id"] == stack_task.task_id
    assert entry["producer_task_path"] == stack_task.task_path
    assert entry["applied_reason"] == "status_stack_property"
    assert math.isclose(entry["value"], 0.6)
    assert dispatched.after_state.units[CASTER] == first.after_state.units[CASTER]
    audit = RuntimeSourceAuditor(world["rules"]).validate_execution(
        dispatched.mutations, dispatched.records)
    assert audit.ok, audit.to_json()


def test_real_castorice_delayed_property_entry_after_onstack_audits(tmp_path):
    world = _world(tmp_path)
    definition = world["rules"].modifier_definition(BUFF)
    deferred, unsupported = _runtime_modifiers(
        definition, {"__by_hash": {"2128130574": 0.2}},
        caster_id=CASTER, target_id=SERVANT)
    assert not unsupported and len(deferred) == 1
    assert deferred[0]["value"] is None
    assert deferred[0]["value_mode"] == "modifier_internal_dynamic"
    assert deferred[0]["applied_reason"] == "status_stack_property_dynamic"
    source = _source_status(
        world["on_stack"].callback_id,
        dynamic_values={"__by_name": {}, "__by_hash": {"2128130574": 0.2},
                        "2128130574": 0.2},
        modifiers=tuple(deferred),
    )
    base = _state(world)
    state = replace(base, units={
        **base.units,
        CASTER: replace(base.units[CASTER], statuses=(source["status_id"],),
                        flags={"status_details": [source]}),
    })
    first = _execute(world, state)
    assert first.ok, first.errors
    copy = next(row for row in first.after_state.units[SERVANT].flags["status_details"]
                if row["modifier_name"] == BUFF)
    copy_id = copy["instance_id"]
    stack_task = next(task for task in world["on_stack_tasks"]
                      if task.opcode == "StackProperty")
    assert copy["modifiers"][0]["value"] is None
    assert copy["modifiers"][0]["applied_reason"] == "status_stack_property_dynamic"

    stacked = StatusSystem(world["rules"]).modify_modifier_value(
        first.after_state, SERVANT, BUFF, "Layer", "Add", 1,
        caster_id=CASTER, metadata={"fixture": "layer_increase"},
        status_instance_id=copy_id,
    )
    assert stacked.ok, stacked.unsupported
    stacked_state = MutationReducer().apply_all(first.after_state, stacked.mutations)
    on_stack = next(event for event in stacked.events if event.window == "OnStack")
    dispatched = EventDispatchSystem(
        world["rules"], EffectRegistry(StatusSystem(world["rules"]))).dispatch_event(
            stacked_state, event=on_stack)
    assert not dispatched.errors, dispatched.errors
    updated = next(row for row in dispatched.after_state.units[SERVANT].flags["status_details"]
                   if row["instance_id"] == copy_id)
    assert len(updated["modifiers"]) == 1
    entry = updated["modifiers"][0]
    assert math.isclose(entry["value"], 0.6)
    assert entry["applied_reason"] == "status_stack_property"
    assert entry["producer_task_id"] == stack_task.task_id
    assert entry["producer_task_path"] == stack_task.task_path
    assert entry["raw_path"] == "_CallbackList[0].CallbackConfig[1]"
    assert "value_mode" not in entry and "deferred_dynamic_hashes" not in entry
    audit = RuntimeSourceAuditor(world["rules"]).validate_execution(
        dispatched.mutations, dispatched.records)
    assert audit.ok, audit.to_json()


def test_real_castorice_appended_property_value_tamper_is_rejected(tmp_path):
    world = _world(tmp_path)
    source = _source_status(world["on_stack"].callback_id, modifiers=())
    base = _state(world)
    state = replace(base, units={
        **base.units,
        CASTER: replace(base.units[CASTER], statuses=(source["status_id"],),
                        flags={"status_details": [source]}),
    })
    first = _execute(world, state)
    assert first.ok, first.errors
    copy = next(row for row in first.after_state.units[SERVANT].flags["status_details"]
                if row["modifier_name"] == BUFF)
    copy_id = copy["instance_id"]
    on_stack = next(event for event in first.events if event.window == "OnStack")
    dispatched = EventDispatchSystem(
        world["rules"], EffectRegistry(StatusSystem(world["rules"]))).dispatch_event(
            first.after_state, event=on_stack)
    assert not dispatched.errors, dispatched.errors
    audit = RuntimeSourceAuditor(world["rules"]).validate_execution(
        dispatched.mutations, dispatched.records)
    assert audit.ok, audit.to_json()
    stack_record = next(record for record in dispatched.records
                        if record.get("record_type") == "status_stack_property")
    mutation = next(item for item in dispatched.mutations
                    if item.stable_id() == stack_record["mutation_id"])
    assert mutation.path == ("units", SERVANT, "flags", "status_details")
    tampered_after = [
        {
            **detail,
            "modifiers": [
                {**item, "value": 999.0}
                if item.get("producer_task_id") else item
                for item in detail.get("modifiers", ())
            ],
        } if detail.get("instance_id") == copy_id else detail
        for detail in mutation.after
    ]
    tampered = replace(mutation, after=tampered_after)
    original_id = mutation.stable_id()
    records = tuple(
        {**record, "mutation_id": tampered.stable_id()}
        if record.get("mutation_id") == original_id else record
        for record in dispatched.records
    )
    rejected = RuntimeSourceAuditor(world["rules"]).validate_execution(
        (tampered,), records)
    assert not rejected.ok
    assert any(
        violation.reason == "status_stack_property_settlement_mismatch"
        for violation in rejected.violations
    ), rejected.to_json()


def test_real_castorice_appended_property_shape_tamper_is_rejected(tmp_path):
    world = _world(tmp_path)
    source = _source_status(world["on_stack"].callback_id, modifiers=())
    base = _state(world)
    state = replace(base, units={
        **base.units,
        CASTER: replace(base.units[CASTER], statuses=(source["status_id"],),
                        flags={"status_details": [source]}),
    })
    first = _execute(world, state)
    assert first.ok, first.errors
    copy_id = next(row["instance_id"] for row in first.after_state.units[SERVANT].flags["status_details"]
                   if row["modifier_name"] == BUFF)
    on_stack = next(event for event in first.events if event.window == "OnStack")
    dispatched = EventDispatchSystem(
        world["rules"], EffectRegistry(StatusSystem(world["rules"]))).dispatch_event(
            first.after_state, event=on_stack)
    assert not dispatched.errors, dispatched.errors
    stack_record = next(record for record in dispatched.records
                        if record.get("record_type") == "status_stack_property")
    mutation = next(item for item in dispatched.mutations
                    if item.stable_id() == stack_record["mutation_id"])
    original_id = mutation.stable_id()
    for tamper in (
        {"bucket": "status_resistance"},
        {"value_mode": "modifier_internal_dynamic"},
    ):
        tampered_after = [
            {
                **detail,
                "modifiers": [
                    {**item, **tamper}
                    if item.get("producer_task_id") else item
                    for item in detail.get("modifiers", ())
                ],
            } if detail.get("instance_id") == copy_id else detail
            for detail in mutation.after
        ]
        tampered = replace(mutation, after=tampered_after)
        records = tuple(
            {**record, "mutation_id": tampered.stable_id()}
            if record.get("mutation_id") == original_id else record
            for record in dispatched.records
        )
        rejected = RuntimeSourceAuditor(world["rules"]).validate_execution(
            (tampered,), records)
        assert not rejected.ok, tamper
        assert any(
            violation.reason == "status_stack_property_settlement_mismatch"
            for violation in rejected.violations
        ), rejected.to_json()


def test_real_castorice_sibling_status_change_is_rejected(tmp_path):
    world = _world(tmp_path)
    state = _state(world)
    first = _execute(world, state)
    assert first.ok, first.errors
    copy_id = next(row["instance_id"] for row in first.after_state.units[SERVANT].flags["status_details"]
                   if row["modifier_name"] == BUFF)
    sibling = StatusInstance(
        "sibling:1", "modifier:FixtureSibling", "FixtureSibling", SERVANT,
        "fixture:sibling", CASTER, stacks=1, duration=2.0, remaining_duration=2.0,
        duration_admission={"admission_status": "executable"},
        lifecycle_state="active", status_type="Buff", status_category="buff",
    ).to_json()
    servant = first.after_state.units[SERVANT]
    with_sibling = replace(first.after_state, units={
        **first.after_state.units,
        SERVANT: replace(servant, statuses=(*servant.statuses, sibling["status_id"]),
                         flags={**servant.flags,
                                "status_details": [*servant.flags["status_details"], sibling]}),
    })
    on_stack = next(event for event in first.events if event.window == "OnStack")
    dispatched = EventDispatchSystem(
        world["rules"], EffectRegistry(StatusSystem(world["rules"]))).dispatch_event(
            with_sibling, event=on_stack)
    assert not dispatched.errors, dispatched.errors
    audit = RuntimeSourceAuditor(world["rules"]).validate_execution(
        dispatched.mutations, dispatched.records)
    assert audit.ok, audit.to_json()
    stack_record = next(record for record in dispatched.records
                        if record.get("record_type") == "status_stack_property")
    mutation = next(item for item in dispatched.mutations
                    if item.stable_id() == stack_record["mutation_id"])
    original_id = mutation.stable_id()
    tampered_variants = (
        [
            {**detail, "stacks": 999} if detail.get("instance_id") == "sibling:1" else detail
            for detail in mutation.after
        ],
        [
            detail for detail in mutation.after
            if detail.get("instance_id") != "sibling:1"
        ],
    )
    for tampered_after in tampered_variants:
        tampered = replace(mutation, after=tampered_after)
        records = tuple(
            {**record, "mutation_id": tampered.stable_id()}
            if record.get("mutation_id") == original_id else record
            for record in dispatched.records
        )
        rejected = RuntimeSourceAuditor(world["rules"]).validate_execution(
            (tampered,), records)
        assert not rejected.ok
        assert any(
            violation.reason in {
                "status_stack_property_sibling_instance_changed",
                "status_stack_property_mutation_path_invalid",
            }
            for violation in rejected.violations
        ), rejected.to_json()


def test_real_castorice_missing_servant_blocks_without_state_change(tmp_path):
    world = _world(tmp_path)
    state = _state(world)
    no_servant = replace(state, units={
        key: value for key, value in state.units.items() if key != SERVANT})
    before = no_servant
    result = _execute(world, no_servant)
    assert not result.ok and result.after_state == before
    assert not result.mutations and not result.rng_events
