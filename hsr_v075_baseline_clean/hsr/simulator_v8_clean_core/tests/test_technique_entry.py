"""Selected ordinary techniques use their formal entry graph and build parameters."""
from dataclasses import replace
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.builds.models import CharacterBuildInput, CharacterInitialConditionInput
from hsr.simulator_v8_clean_core.equipment.models import EquipmentBuildInput
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.scenarios import (
    BattleSetupSpec, ScenarioLoader, ScenarioSpec, ScenarioStateBuilder,
    TechniqueSetupSpec, TimelineSetupSpec, UnitSpec,
)
from hsr.simulator_v8_clean_core.systems.ability import AbilityTaskSystem, CharacterTechniqueInvocation
from hsr.simulator_v8_clean_core.systems.effect import EffectRegistry
from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering


def _scenario():
    card = "character_data_card:avatar:1002"
    build = CharacterBuildInput("technique-test", card, 1, 0, 0, (), EquipmentBuildInput("empty", card))
    return ScenarioSpec("technique-test", "1", (
        UnitSpec("owner", "ally", "avatar:1002", "assembled_character_build", level=1,
                 panel=None, character_build=build,
                 initial_condition=CharacterInitialConditionInput("full", "0")),
    ), (), battle_setup=BattleSetupSpec(timeline=TimelineSetupSpec()))


def test_technique_configuration_has_no_parameter_or_level_override():
    scenario = _scenario()
    raw = {"scenario_id": "technique-test", "version": "1", "route": [], "units": [{
        "unit_id": "owner", "side": "ally", "entity_ref": "avatar:1002",
        "build_mode": "assembled_character_build", "level": 1,
        "character_build": scenario.units[0].character_build.to_json(),
        "initial_condition": scenario.units[0].initial_condition.to_json(),
    }], "battle_setup": {"timeline": {"mode": "runtime_initialize"},
                             "techniques": [{"actor_id": "owner", "action_ref": "avatar_skill:100207"}]}}
    loaded = ScenarioLoader().load_dict(raw)
    assert loaded.battle_setup.techniques == (TechniqueSetupSpec("owner", "avatar_skill:100207"),)
    raw["battle_setup"]["techniques"][0]["action_level"] = 10
    with pytest.raises(ValueError, match="parameters come from the build"):
        ScenarioLoader().load_dict(raw)


@pytest.mark.integration
def test_ordinary_source_technique_installs_before_enter_battle_without_spending_a_turn():
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    rules = RuleBook(TBGDLowering(root).build(
        avatar_ids=frozenset({"1002"}), monster_ids=frozenset(), stage_ids=frozenset(),
        include_equipment=False,
    ))
    scenario = _scenario()
    before = ScenarioStateBuilder(rules).build(scenario)
    activated = replace(scenario, battle_setup=replace(
        scenario.battle_setup, techniques=(TechniqueSetupSpec("owner", "avatar_skill:100207"),),
    ))
    built = ScenarioStateBuilder(rules).build(activated)
    assert not built.blocked_setup
    detail = next(row for row in built.state.units["owner"].flags["status_details"]
                  if row["modifier_name"] == "MAvatar_DanHeng_00_MazeSkill_AttackRatioUp")
    assert detail["duration"] == 3
    assert any(row["key"] == "attack_added_ratio" and row["value"] == .4 for row in detail["modifiers"])
    assert not any(row["modifier_name"] == detail["modifier_name"]
                   for row in before.state.units["owner"].flags["status_details"])
    assert built.state.skill_points == before.state.skill_points
    assert built.state.units["owner"].energy == before.state.units["owner"].energy
    assert built.state.global_flags.get("global_av", 0) == before.state.global_flags.get("global_av", 0)
    assert built.state.units["owner"].action_value == before.state.units["owner"].action_value
    assert any(row["record_type"] == "setup_technique" for row in built.setup_records)
    effects = EffectRegistry(StatusSystem(rules))
    runtime = AbilityTaskSystem(rules, effects, event_dispatcher=EventDispatchSystem(rules, effects))
    rejected = runtime.execute_character_technique(before.state, invocation=CharacterTechniqueInvocation(
        "owner", "avatar_skill:100207", 1, "wrong-source-binding",
    ))
    assert rejected.after_state == before.state and not rejected.mutations and not rejected.rng_events
    duplicate = replace(activated, battle_setup=replace(
        activated.battle_setup, techniques=activated.battle_setup.techniques * 2,
    ))
    with pytest.raises(ValueError, match="duplicate activated technique"):
        ScenarioStateBuilder(rules).build(duplicate)
