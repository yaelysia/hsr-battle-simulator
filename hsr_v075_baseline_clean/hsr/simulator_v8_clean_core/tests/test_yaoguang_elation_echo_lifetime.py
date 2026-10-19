"""Real YaoGuang trace B3 extends the added ElationEchoPoint instance."""
import json
from dataclasses import replace
from pathlib import Path

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, EffectIR, IRSource
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.effect import EffectRegistry
from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.tests.test_status_shared_immunity import _formal_immunity_source
from hsr.simulator_v8_clean_core.tbgd.character_cards import build_character_card_ir
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _attach_target_expressions_to_effect_payload, _lower_status_event_families,
    _modifier_definition_entity, _standard_add_modifier_payload,
    _synchronize_effect_target_expression_metadata,
)
from hsr.simulator_v8_clean_core.tbgd.target_source import close_target_expression_language
from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import (
    attach_task_graph_catalog, materialize_status_callback_task_graph,
)

ROOT = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
ABILITY_PATH = "Config/ConfigAbility/Avatar/Avatar_YaoGuang_00_Ability.json"
ECHO_PATH = "Config/ConfigAbility/BattleEvent/StageAbility_Elation.json"
SKILL_TREE = "MAvatar_YaoGuang_00_SkillTree03"
ECHO = "MBattleEvent_Elation_ElationEchoPointBuff"
FIXTURE_BUFF = "FixturePlainBuff"


def _add_effect(relative, name, effect_id, source_json_path, languages, callback_ids=()):
    raw = {"$type": "RPG.GameCore.AddModifier",
           "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
           "ModifierName": {"Value": name}}
    source = IRSource(relative, "AddModifier", effect_id, {"json_path": source_json_path})
    payload, targets = _attach_target_expressions_to_effect_payload(
        {"standard": _standard_add_modifier_payload(raw)}, raw,
        effect_id=effect_id, source=source,
    )
    targets = [close_target_expression_language(target, languages) for target in targets]
    effect = EffectIR(effect_id, "AddModifier", payload, source, "executable",
                      source_mode="mainline",
                      status_callback_ids=tuple(callback_ids))
    return _synchronize_effect_target_expression_metadata([effect], targets)[0], targets


def _world(tmp_path):
    lowering, sources, lowered, languages = _formal_immunity_source(tmp_path, ABILITY_PATH, 1502)
    callback = next(row for row in lowered.status_callbacks
                    if row.modifier_name == SKILL_TREE and row.event == "OnModifierAdd")
    tasks = tuple(row for row in lowered.status_callback_tasks if row.callback_id == callback.callback_id)
    assert tasks and all(row.coverage_status == "executable" for row in tasks)

    echo_document = json.loads((ROOT / ECHO_PATH).read_text())
    echo_definition = _modifier_definition_entity(
        ECHO_PATH, "GlobalModifiers", ECHO, echo_document["GlobalModifiers"][ECHO],
        source_context={"json_path": "$.GlobalModifiers." + ECHO})
    fixture_definition = _modifier_definition_entity(
        "validation_fixture/yaoguang_echo_listeners.json", "ModifierMap", FIXTURE_BUFF, {},
        source_context={"json_path": "$.ModifierMap." + FIXTURE_BUFF})

    skill_effect, skill_targets = _add_effect(
        ABILITY_PATH, SKILL_TREE, "fixture:skill-tree", "$.AbilityList[13].OnStart[0]", languages,
        callback_ids=(callback.callback_id,))
    echo_effect, echo_targets = _add_effect(
        ECHO_PATH, ECHO, "fixture:echo", "$.fixture.echo", languages)
    plain_effect, plain_targets = _add_effect(
        "validation_fixture/yaoguang_echo_listeners.json", FIXTURE_BUFF,
        "fixture:plain-buff", "$.fixture.plain", languages)

    card_build = build_character_card_ir(
        ROOT, max_records_per_table=None, skill_tables=(), avatar_ids=frozenset({"1502"}))
    assert len(card_build.character_data_cards) == 1

    canonical = CanonicalIR(
        "yaoguang-echo-lifetime-component",
        entities=(*lowered.entities, echo_definition, fixture_definition),
        effects=(*lowered.effects, skill_effect, echo_effect, plain_effect),
        conditions=tuple(lowered.conditions),
        status_callbacks=(callback,),
        status_callback_tasks=tasks,
        status_event_families=tuple(_lower_status_event_families([callback], list(tasks))),
        character_data_cards=tuple(card_build.character_data_cards),
        character_trace_nodes=tuple(card_build.character_trace_nodes),
        character_mechanism_slots=tuple(card_build.character_mechanism_slots),
        target_expressions=tuple(close_target_expression_language(row, languages)
            for row in lowered.target_expressions)
            + tuple(row.expression for row in languages)
            + tuple(skill_targets) + tuple(echo_targets) + tuple(plain_targets),
    )
    catalog = materialize_status_callback_task_graph(
        sources, canonical, callback_id=callback.callback_id,
        source_snapshot=lowering._character_ability_raw_snapshot)
    assert len(catalog.graphs) == 1, catalog.entries
    assert all(row.materialization_status == "materialized" for row in catalog.graphs[0].nodes)
    rules = RuleBook(attach_task_graph_catalog(canonical, catalog))
    return {
        "rules": rules,
        "callback": callback,
        "card": card_build.character_data_cards[0],
        "trace_node": next(row for row in card_build.character_trace_nodes
                           if row.activation_key == "PointB3"),
        "skill_effect": skill_effect,
        "echo_effect": echo_effect,
        "plain_effect": plain_effect,
    }


def _state(world):
    return BattleState(units={"yao": UnitState(
        "yao", "ally", world["card"].entity_ref, hp=1000, max_hp=1000,
        flags={
            "character_data_card_id": world["card"].card_id,
            "selected_trace_node_ids": [world["trace_node"].trace_node_id],
        },
    )})


def _install(world, state, effect, *, application_id=""):
    result = StatusSystem(world["rules"]).apply_add_modifier(
        state, effect, caster_id="yao", source_id=effect.effect_id,
        application_instance_id=application_id,
    )
    assert result.ok, result.unsupported
    return result, MutationReducer().apply_all(state, result.mutations)


def _dispatch(world, state, event):
    dispatcher = EventDispatchSystem(world["rules"], EffectRegistry(StatusSystem(world["rules"])))
    return dispatcher.dispatch_event(state, event=event)


def test_real_yaoguang_trace_b3_extends_only_the_triggering_echo_instance(tmp_path):
    world = _world(tmp_path)
    state = _state(world)
    skill_result, state = _install(world, state, world["skill_effect"])
    assert skill_result.events
    first_result, state = _install(world, state, world["echo_effect"], application_id="fixture:echo:first")
    second_result, state = _install(world, state, world["echo_effect"], application_id="fixture:echo:second")
    _, state = _install(world, state, world["plain_effect"])
    first_echo = next(row for row in first_result.mutations
                      if row.path == ("units", "yao", "flags", "status_details")).after
    first_id = next(row["instance_id"] for row in first_echo
                    if row["modifier_name"] == ECHO and row["remaining_duration"] == 2.0)
    second_id = next(row["instance_id"] for row in state.units["yao"].flags["status_details"]
                     if row["modifier_name"] == ECHO and row["instance_id"] != first_id)
    event = next(row for row in second_result.events if row.window == "OnModifierAdd")
    assert event.payload["status_instance_id"] == second_id
    assert event.payload["behavior_flags"] == ["ElationEchoPoint"]

    dispatched = _dispatch(world, state, event)
    assert not dispatched.errors, dispatched.errors
    details = dispatched.after_state.units["yao"].flags["status_details"]
    by_id = {row["instance_id"]: row for row in details}
    assert by_id[second_id]["remaining_duration"] == 3.0
    assert by_id[first_id]["remaining_duration"] == 2.0
    assert by_id[second_id]["caster_id"] == "yao" and by_id[second_id]["stacks"] == 1
    assert by_id[second_id]["dynamic_values"] == next(
        row["dynamic_values"] for row in state.units["yao"].flags["status_details"]
        if row["instance_id"] == second_id)
    assert dispatched.after_state.units["yao"].flags["status_details"] == [
        {**row, "remaining_duration": 3.0} if row["instance_id"] == second_id else row
        for row in state.units["yao"].flags["status_details"]]
    audit = RuntimeSourceAuditor(world["rules"]).validate_execution(
        dispatched.mutations, dispatched.records)
    assert audit.ok, audit.to_json()


def test_real_yaoguang_echo_without_the_flag_does_not_change_any_lifetime(tmp_path):
    world = _world(tmp_path)
    state = _state(world)
    _, state = _install(world, state, world["skill_effect"])
    plain_result, state = _install(world, state, world["plain_effect"])
    event = next(row for row in plain_result.events if row.window == "OnModifierAdd")
    before = state.units["yao"].flags["status_details"]
    dispatched = _dispatch(world, state, event)
    assert not dispatched.errors and dispatched.after_state == state
    assert not dispatched.mutations
    assert state.units["yao"].flags["status_details"] == before

    # Only changing the ordinary payload behavior flag (the condition input)
    # must not bypass the producer fact and extend the plain Buff.
    tampered = replace(event, payload={
        **event.payload, "behavior_flags": ["ElationEchoPoint"],
    })
    rejected = _dispatch(world, state, tampered)
    assert rejected.errors
    assert rejected.after_state == state
    assert not rejected.mutations
    assert state.units["yao"].flags["status_details"] == before


def test_real_yaoguang_missing_trace_selection_blocks_atomically(tmp_path):
    world = _world(tmp_path)
    state = _state(world)
    _, state = _install(world, state, world["skill_effect"])
    echo_result, state = _install(world, state, world["echo_effect"], application_id="fixture:echo:first")
    event = next(row for row in echo_result.events if row.window == "OnModifierAdd")
    unselected = replace(state, units={"yao": replace(state.units["yao"], flags={
        **state.units["yao"].flags, "selected_trace_node_ids": []})})
    dispatched = _dispatch(world, unselected, event)
    assert dispatched.errors
    assert dispatched.after_state == unselected
    assert not dispatched.mutations and not dispatched.rng_events


def test_real_yaoguang_payload_instance_tamper_blocks_without_state_change(tmp_path):
    world = _world(tmp_path)
    state = _state(world)
    _, state = _install(world, state, world["skill_effect"])
    first_result, state = _install(world, state, world["echo_effect"], application_id="fixture:echo:first")
    second_result, state = _install(world, state, world["echo_effect"], application_id="fixture:echo:second")
    first_details = next(row for row in first_result.mutations
                         if row.path == ("units", "yao", "flags", "status_details")).after
    first_id = next(row["instance_id"] for row in first_details if row["modifier_name"] == ECHO)
    second_id = next(row["instance_id"] for row in state.units["yao"].flags["status_details"]
                     if row["modifier_name"] == ECHO and row["instance_id"] != first_id)
    event = next(row for row in second_result.events if row.window == "OnModifierAdd")
    assert event.payload["status_instance_id"] == second_id
    tampered = replace(event, payload={**event.payload, "status_instance_id": first_id})
    dispatched = _dispatch(world, state, tampered)
    assert dispatched.errors
    assert dispatched.after_state == state
    assert not dispatched.mutations and not dispatched.rng_events
    lifetimes = {row["instance_id"]: row["remaining_duration"]
                 for row in state.units["yao"].flags["status_details"]
                 if row["modifier_name"] == ECHO}
    assert lifetimes == {first_id: 2.0, second_id: 2.0}

    # The precision path must also fail closed when a caller strips the typed
    # producer fact and keeps only payload-looking fields.
    missing_fact = replace(event, status_lifecycle_fact=None)
    dispatched = _dispatch(world, state, missing_fact)
    assert dispatched.errors
    assert dispatched.after_state == state
    assert not dispatched.mutations and not dispatched.rng_events
