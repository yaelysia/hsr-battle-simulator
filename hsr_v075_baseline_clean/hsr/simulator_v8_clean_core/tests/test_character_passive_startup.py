from __future__ import annotations

import math
import json
import sys
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hsr.simulator_v8_clean_core.builds.character_assembler import assemble_character_build
from hsr.simulator_v8_clean_core.builds.models import CharacterBuildInput, CharacterInitialConditionInput
from hsr.simulator_v8_clean_core.core.model import BattleState, Mutation, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.equipment.models import EquipmentBuildInput
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.rules.evaluator import NumericEvaluationContext, RuleEvaluator
from hsr.simulator_v8_clean_core.scenarios.build_state import ScenarioStateBuilder
from hsr.simulator_v8_clean_core.scenarios.schema import BattleSetupSpec, ScenarioSpec, TimelineSetupSpec, UnitSpec
from hsr.simulator_v8_clean_core.systems.ability import AbilityTaskSystem, CharacterStartupInvocation
from hsr.simulator_v8_clean_core.systems.dynamic_values import (
    binding_source_from_status_detail, character_skill_param_binding_sources, upsert_dynamic_value,
)
from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry, _binding_sources
from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
from hsr.simulator_v8_clean_core.systems.mutation_events import events_for_mutation
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering, _effect_payload


@lru_cache(maxsize=1)
def _source_case(monster_ids=frozenset()):
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    ir = TBGDLowering(root).build(
        avatar_ids=frozenset({"1008"}), monster_ids=monster_ids,
        stage_ids=frozenset(), include_equipment=False,
    )
    rules = RuleBook(ir)
    card_id = "character_data_card:avatar:1008"
    build = CharacterBuildInput(
        "passive-test", card_id, 1, 0, 0, (), EquipmentBuildInput("empty", card_id),
    )
    assembly = assemble_character_build(rules, build)
    assert assembly.battle_admission_status == "admitted", (
        assembly.blocked_reasons,
        tuple((item.target_ref_id, item.reason) for item in assembly.unadmitted_mechanism_diagnostics),
    )
    scenario = ScenarioSpec("passive-test", "1", (
        UnitSpec("owner", "ally", "avatar:1008", "assembled_character_build",
                 level=1, panel=None, character_build=build,
                 initial_condition=CharacterInitialConditionInput("full", "0")),
    ), (), battle_setup=BattleSetupSpec(timeline=TimelineSetupSpec()))
    result = ScenarioStateBuilder(rules).build(scenario)
    assert not result.blocked_setup, result.blocked_setup
    return rules, result


def _bonus(unit):
    return sum(float(modifier["value"])
               for detail in unit.flags.get("status_details", ())
               for modifier in detail.get("modifiers", ())
               if modifier.get("bucket") == "damage_bonus"
               and modifier.get("key") == "damage_added_ratio")


def test_real_named_hp_writer_updates_the_formula_hash():
    source = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main/Config/ConfigAbility/Avatar/Avatar_Arlan_00_Ability.json"
    ability = next(item for item in json.loads(source.read_text())["AbilityList"]
                   if item.get("Name") == "Avatar_Arlan_PassiveSkill01")
    callback = next(item for item in ability["Modifiers"]["M_Arlan_Passive"]["_CallbackList"]
                    if item["Event"] == "OnHPChange")
    task = callback["CallbackConfig"][0]["FailedTaskList"][0]
    assert task["$type"] == "RPG.GameCore.SetDynamicValueByHPRatio"
    operation = _effect_payload(task, "SetDynamicValueByHPRatio", "M_Arlan_Passive")["standard"]["dynamic_operation"]
    assert operation["destination_key"] == "_HPRatio"
    assert operation["destination_hash"] == "912879638"


@pytest.mark.integration
def test_real_passive_installs_and_tracks_hp_changes():
    rules, built = _source_case()
    before = built.state
    assert any(detail.get("modifier_name") == "M_Arlan_Passive"
               for detail in before.units["owner"].flags["status_details"])
    passive = next(detail for detail in before.units["owner"].flags["status_details"]
                   if detail.get("modifier_name") == "M_Arlan_Passive")
    assert passive["dynamic_values"]["__by_hash"]["912879638"] == 0.0
    assert passive["dynamic_values"]["__by_hash"]["1980782708"] == 0.36
    assert math.isclose(_bonus(before.units["owner"]), 0.0)
    effects = EffectRegistry(StatusSystem(rules))
    dispatch = EventDispatchSystem(rules, effects)
    task = next(task for task in rules.ir.ability_tasks
                if task.action_id == "avatar_skill:100802" and task.level == 1
                and task.opcode == "LoseHPByRatio")
    effect = rules.effect(task.effect_id)
    assert effect is not None
    loss = effects.execute(effect, EffectExecutionContext(
        state=before, caster_id="owner", source_id=task.task_id, owner_id="owner",
        include_ambient_status_bindings=False,
        binding_sources=character_skill_param_binding_sources(
            rules, before, ("owner",), action_level=1, current_action_trigger_key="Skill02",
        ),
    ))
    assert not loss.unsupported, loss.unsupported
    assert sum(event.event_type == "hp.change" for event in loss.events) == 1
    reducer = MutationReducer()
    current = reducer.apply_all(before, loss.mutations)
    for event in loss.events:
        changed = dispatch.dispatch_event(current, event=event)
        assert not changed.errors, changed.errors
        current = changed.after_state
    owner = current.units["owner"]
    assert owner.hp < owner.max_hp
    updated_passive = next(detail for detail in owner.flags["status_details"]
                           if detail.get("modifier_name") == "M_Arlan_Passive")
    values = updated_passive["dynamic_values"]
    assert math.isclose(values["__by_name"]["_HPRatio"], owner.hp / owner.max_hp)
    assert values["__by_hash"]["912879638"] == values["__by_name"]["_HPRatio"]
    assert math.isclose(_bonus(owner), (1 - owner.hp / owner.max_hp) * 0.36), (
        owner.hp, owner.max_hp, _bonus(owner),
        [(detail.get("modifier_name"), detail.get("modifiers"))
         for detail in owner.flags["status_details"]],
    )
    # Fixture restoration exercises the formal HP-change event; it is not an
    # invented Arlan healing ability.
    restoration = Mutation(
        "set", ("units", "owner", "hp"), owner.hp, owner.max_hp,
        "restore test HP", "fixture:hp_restore",
    )
    current = reducer.apply(current, restoration)
    for event in events_for_mutation(restoration, actor_id="owner", source_id="fixture", event_index=current.event_index):
        changed = dispatch.dispatch_event(current, event=event)
        assert not changed.errors, changed.errors
        current = changed.after_state
    assert math.isclose(_bonus(current.units["owner"]), 0.0)


def test_status_parameters_are_local_to_the_selected_callback():
    detail = {"owner_id": "owner", "instance_id": "status:other", "status_id": "other",
              "dynamic_values": {"__by_hash": {"shared": 99.0}}}
    store = upsert_dynamic_value(None, scope="status", owner_id="owner", value=88.0,
                                 hash_key="shared", value_name="shared", status_instance_id="status:stored")
    state = BattleState({"owner": UnitState("owner", "ally", "fixture", flags={
        "status_details": [detail],
    })}, global_flags={"dynamic_value_store": store})
    action_source = {"source_type": "fixture_action_parameter", "values": {"shared": 0.15}}
    callback_source = binding_source_from_status_detail(detail, detail["dynamic_values"])
    assert callback_source is not None
    for explicit, expected in ((action_source, 0.15), (callback_source, 99.0), (None, None)):
        context = EffectExecutionContext(state=state, caster_id="owner", source_id="fixture",
                                         owner_id="owner", binding_sources=((explicit,) if explicit else ()),
                                         include_ambient_status_bindings=False)
        result = RuleEvaluator().evaluate_numeric(
            {"kind": "dynamic_hash", "hash": "shared"},
            NumericEvaluationContext(binding_sources=_binding_sources(context)),
        )
        if expected is None:
            assert not result.ok and result.value is None, result
        else:
            assert result.ok and result.value == expected, result


@pytest.mark.integration
def test_startup_identity_failure_has_no_mutation():
    rules, built = _source_case()
    effects = EffectRegistry(StatusSystem(rules))
    runtime = AbilityTaskSystem(rules, effects, event_dispatcher=EventDispatchSystem(rules, effects))
    result = runtime.execute_character_startup(built.state, invocation=CharacterStartupInvocation(
        "owner", "avatar_skill:100804", 1, "wrong-binding",
    ))
    assert result.after_state == built.state and not result.mutations
    assert any(node.status == "blocked" for node in result.node_results)


@pytest.mark.integration
def test_source_lifecycle_without_listener_remains_observable():
    rules, built = _source_case()
    event = next(event for event in built.setup_events
                 if event.event_type == "status.lifecycle"
                 and event.payload.get("callback_event") == "OnAddModifierSuc")
    assert rules.status_event_family("OnAddModifierSuc") is None
    effects = EffectRegistry(StatusSystem(rules))
    dispatch = EventDispatchSystem(rules, effects)
    result = dispatch.dispatch_event(built.state, event=event)
    assert not result.errors and not result.mutations
    assert event in result.events and result.listener_records
    unknown = replace(event, window="OnUnknownLifecycle", payload={
        **event.payload, "callback_event": "OnUnknownLifecycle",
    })
    rejected = dispatch.dispatch_event(built.state, event=unknown)
    assert rejected.errors and not rejected.mutations
    assert rejected.after_state == built.state


if __name__ == "__main__":
    test_real_named_hp_writer_updates_the_formula_hash()
    test_status_parameters_are_local_to_the_selected_callback()
    test_real_passive_installs_and_tracks_hp_changes()
    test_startup_identity_failure_has_no_mutation()
    test_source_lifecycle_without_listener_remains_observable()
    print("5 character passive startup checks passed")
