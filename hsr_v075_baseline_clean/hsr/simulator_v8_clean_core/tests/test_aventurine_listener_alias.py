"""Real Aventurine Rank06 listener consumes the OnModifierAdd event family."""
from dataclasses import replace
from pathlib import Path

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, EffectIR, IRSource
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.effect import EffectRegistry
from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
from hsr.simulator_v8_clean_core.systems.status import StatusInstance, StatusSystem
from hsr.simulator_v8_clean_core.tests.test_status_shared_immunity import _formal_immunity_source
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _attach_target_expressions_to_effect_payload, _lower_status_event_families,
    _modifier_definition_entity, _standard_add_modifier_payload,
    _synchronize_effect_target_expression_metadata,
)
from hsr.simulator_v8_clean_core.tbgd.target_source import close_target_expression_language
from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import (
    attach_task_graph_catalog, materialize_status_callback_task_graph,
)

RELATIVE = "Config/ConfigAbility/Avatar/Avatar_Aventurine_00_Ability.json"
LISTENER = "MAvatar_Aventurine_Rank06"
PLAIN = "FixturePlainBuff"
AVENTURINE = "aventurine"


def _world(tmp_path):
    lowering, sources, lowered, languages = _formal_immunity_source(tmp_path, RELATIVE, 1304)
    callback = next(row for row in lowered.status_callbacks
                    if row.modifier_name == LISTENER and row.event == "OnListenModifierAdd")
    tasks = tuple(row for row in lowered.status_callback_tasks
                  if row.callback_id == callback.callback_id)
    assert tasks and all(row.coverage_status == "executable" for row in tasks)

    definition = _modifier_definition_entity(
        "validation_fixture/aventurine_listener.json", "ModifierMap", PLAIN, {},
        source_context={"json_path": "$.ModifierMap." + PLAIN})
    raw = {"$type": "RPG.GameCore.AddModifier",
           "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
           "ModifierName": {"Value": PLAIN}}
    source = IRSource("validation_fixture/aventurine_listener.json", "AddModifier",
                      "fixture:plain", {"json_path": "$.fixture.plain"})
    payload, targets = _attach_target_expressions_to_effect_payload(
        {"standard": _standard_add_modifier_payload(raw)}, raw,
        effect_id="fixture:plain", source=source)
    targets = [close_target_expression_language(row, languages) for row in targets]
    effect = EffectIR("fixture:plain", "AddModifier", payload, source, "executable",
                      modifier_definition_id=definition.entity_id, source_mode="mainline")
    effect = _synchronize_effect_target_expression_metadata([effect], targets)[0]

    canonical = CanonicalIR(
        "aventurine-listener-alias",
        entities=(*lowered.entities, definition),
        effects=(*lowered.effects, effect),
        conditions=tuple(lowered.conditions),
        status_callbacks=(callback,),
        status_callback_tasks=tasks,
        status_event_families=tuple(_lower_status_event_families([callback], list(tasks))),
        target_expressions=tuple(lowered.target_expressions) + tuple(targets)
            + tuple(row.expression for row in languages),
    )
    catalog = materialize_status_callback_task_graph(
        sources, canonical, callback_id=callback.callback_id,
        source_snapshot=lowering._character_ability_raw_snapshot)
    assert len(catalog.graphs) == 1, catalog.entry_materializations
    return {
        "rules": RuleBook(attach_task_graph_catalog(canonical, catalog)),
        "callback": callback,
        "plain_effect": effect,
    }


def _state(world):
    listener = StatusInstance(
        "aventurine:rank06", "modifier:" + LISTENER, LISTENER, AVENTURINE,
        "status_callback_status:rank06", AVENTURINE,
        trigger_ids_by_event={"OnListenModifierAdd": (world["callback"].callback_id,)},
    ).to_json()
    return BattleState(units={AVENTURINE: UnitState(
        AVENTURINE, "ally", "avatar:1304", hp=1000, max_hp=1000,
        statuses=(listener["status_id"],), flags={"status_details": [listener]},
    )})


def _plain_add_event(world, state):
    installed = StatusSystem(world["rules"]).apply_add_modifier(
        state, world["plain_effect"], caster_id=AVENTURINE, source_id="fixture:plain")
    assert installed.ok, installed.unsupported
    after = MutationReducer().apply_all(state, installed.mutations)
    event = next(row for row in installed.events if row.window == "OnModifierAdd")
    return after, event


def _dispatch(world, state, event):
    return EventDispatchSystem(
        world["rules"], EffectRegistry(StatusSystem(world["rules"]))).dispatch_event(
            state, event=event)


def test_real_aventurine_rank06_alias_listener_accepts_plain_buff_add(tmp_path):
    world = _world(tmp_path)
    state = _state(world)
    after, event = _plain_add_event(world, state)
    assert event.status_lifecycle_fact.callback_event == "OnModifierAdd"
    dispatched = _dispatch(world, after, event)
    assert not dispatched.errors, dispatched.errors
    assert dispatched.after_state == after
    assert not dispatched.mutations


def test_real_aventurine_rank06_tampered_condition_payload_is_rejected(tmp_path):
    world = _world(tmp_path)
    state = _state(world)
    after, event = _plain_add_event(world, state)
    tampered = replace(event, payload={
        **event.payload, "behavior_flags": ["Shield"],
    })
    dispatched = _dispatch(world, after, tampered)
    assert dispatched.errors
    assert dispatched.after_state == after
    assert not dispatched.mutations
