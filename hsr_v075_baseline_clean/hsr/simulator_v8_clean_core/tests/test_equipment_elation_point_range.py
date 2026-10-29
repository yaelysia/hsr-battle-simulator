"""R06 integration: Elation point range watcher (20024 Lingering Tear).

Real equipment IR is lowered once from the fixed TBGD catalog; the battle facts
are produced by the formal Punchline mutation/event path, never injected into
the watcher directly.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.ir import EffectIR, IRSource
from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry
from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
from hsr.simulator_v8_clean_core.systems.status import StatusSystem
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering, _effect_coverage_status, _effect_payload,
)

pytestmark = pytest.mark.integration

_WATCHER_ID = (
    "ability_property_watcher:Config/ConfigAbility/Equip/Equip40.json:"
    "MEquip_20024_Main:elation_point"
)


@lru_cache(maxsize=1)
def _rules():
    core = Path(__file__).resolve().parents[1]
    scenario = json.loads(
        (core / "examples/cli/arlan_fleet_vs_antimatter.json").read_text()
    )
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    return build_battle_rulebook(root, scenario)


def _graph(rules):
    graph = next(
        (
            item
            for item in rules.ir.standalone_ability_graphs
            if item.ability_name == "Ability20024"
            and item.source_mode == "mainline_equipment"
        ),
        None,
    )
    assert graph is not None
    return graph


def _system(rules):
    registry = EffectRegistry(StatusSystem(rules))
    return registry, EventDispatchSystem(rules, registry)


def _apply(state, mutations):
    result = MutationReducer().apply_all_result(state, mutations)
    assert result.ok, result.errors
    return result.after_state


def _add_main(rules, registry):
    graph = _graph(rules)
    task = next(
        rules.ability_task(task_id)
        for task_id in graph.task_ids
        if rules.ability_task(task_id) is not None
        and rules.ability_task(task_id).opcode == "AddModifier"
    )
    effect = rules.effect(task.effect_id)
    assert effect is not None
    state = BattleState(
        units={
            "holder": UnitState(
                "holder", "ally", "test:holder", max_hp=2000.0, hp=2000.0,
                speed=100.0, energy=0.0, max_energy=100.0,
            )
        }
    )
    # Startup binds the exact light-cone parameter table to the root status.
    # Superimposition 1: Min = 10 Punchline points, CRIT DMG = 0.2.
    parameter_values = {"138206455": 10.0, "-716465292": 0.2}
    result = StatusSystem(rules).apply_add_modifier(
        state,
        effect,
        application_instance_id="startup:test:A20024",
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
    state = _apply(state, result.mutations)
    return state


def _reconcile(system, state, unit_ids=("holder",)):
    """Baseline watcher state through the formal watcher boundary."""

    result = system.ability_property_watchers.reconcile(
        state,
        unit_ids=tuple(unit_ids),
        trigger_event=GameEvent("battle.start", source_id="battle", event_id="event:start"),
    )
    assert result.ok, result.errors
    return _apply(state, result.mutations)


def _dispatch(system, state, event):
    result = system.dispatch_event(state, event=event)
    assert not result.errors, result.errors
    return result.after_state


def _change_points(registry, system, state, delta):
    raw = {
        "$type": "RPG.GameCore.JDOLDFECMPL",
        "AJHHCOHFIFA": {"IsDynamic": False, "FixedValue": {"Value": delta}},
        "FKCKKFALPBK": "Add",
    }
    payload = _effect_payload(raw, "ElationOperation", "")
    effect = EffectIR(
        "test:elation", "ElationOperation", payload,
        IRSource("synthetic:elation", "ElationOperation", "test"),
        _effect_coverage_status("ElationOperation", payload),
    )
    result = registry.execute(
        effect, EffectExecutionContext(state, "holder", "test:elation")
    )
    assert not result.unsupported, result.records
    assert result.mutations and result.events
    state = _apply(state, result.mutations)
    for event in result.events:
        state = _dispatch(system, state, event)
    return state


def _sub_details(state):
    return tuple(
        detail
        for detail in state.units["holder"].flags.get("status_details", ())
        if isinstance(detail, dict)
        and detail.get("modifier_name") == "MEquip_20024_Sub"
    )


def _watcher_state(state):
    detail = next(
        detail
        for detail in state.units["holder"].flags.get("status_details", ())
        if isinstance(detail, dict)
        and detail.get("modifier_name") == "MEquip_20024_Main"
    )
    return detail.get("ability_property_watcher_state", {})


def test_elation_point_range_enter_exit_and_reenter_lifecycle():
    rules = _rules()
    watcher = next(
        item
        for item in rules.ir.ability_property_watchers
        if item.watcher_id == _WATCHER_ID
    )
    assert watcher.property_name == "elation_points"
    assert watcher.property_source == "elation_base_points"
    assert watcher.coverage_status == "executable"
    ranges = tuple(
        rules.ability_property_range(range_id) for range_id in watcher.range_ids
    )
    assert len(ranges) == 1
    assert ranges[0].minimum is not None
    assert ranges[0].minimum_inclusive is True
    assert ranges[0].enter_callback_id and ranges[0].exit_callback_id
    assert ranges[0].coverage_status == "executable"

    registry, system = _system(rules)
    state = _add_main(rules, registry)
    assert not _sub_details(state)
    state = _reconcile(system, state)
    assert _watcher_state(state) == {_WATCHER_ID: []}
    assert not _sub_details(state)

    # Below the threshold: no notification and no status.
    state = _change_points(registry, system, state, 9)
    assert _watcher_state(state) == {_WATCHER_ID: []}
    assert not _sub_details(state)

    # Exactly at the inclusive lower bound enters the range once.
    state = _change_points(registry, system, state, 1)
    sub_details = _sub_details(state)
    assert len(sub_details) == 1
    assert len(_watcher_state(state)[_WATCHER_ID]) == 1
    critical_terms = [
        term
        for detail in sub_details
        for term in detail.get("modifiers", ())
        if isinstance(term, dict)
        and term.get("bucket") == "crit"
        and term.get("key") == "critical_damage"
    ]
    assert critical_terms and critical_terms[0]["value"] == pytest.approx(0.2)

    # Further points changes stay inside the same range: no duplicate add.
    state = _change_points(registry, system, state, 5)
    assert len(_sub_details(state)) == 1

    # Dropping below the range removes only this source's status instance.
    state = _change_points(registry, system, state, -20)
    assert not _sub_details(state)
    assert _watcher_state(state) == {_WATCHER_ID: []}
    assert any(
        isinstance(detail, dict)
        and detail.get("modifier_name") == "MEquip_20024_Main"
        for detail in state.units["holder"].flags.get("status_details", ())
    )

    # Re-entering the range adds again from the formal producer fact.
    state = _change_points(registry, system, state, 10)
    assert len(_sub_details(state)) == 1
    assert len(_watcher_state(state)[_WATCHER_ID]) == 1



def test_non_equipment_native_range_callbacks_remain_visible_and_blocked():
    """A source outside this batch keeps its real callbacks with a block reason."""

    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    path = root / "Config/ConfigAbility/Monster/Monster_W5_JK_00_Ability.json"
    result = TBGDLowering(root)._lower_ability_file(path, {}, ability_file_order=0)
    name = "MMonster_W5_JK_00_ElationPointListener"
    callbacks = [
        callback for callback in result.status_callbacks
        if callback.modifier_name == name and callback.event == "OnElationPointChange"
    ]
    paths = [
        str(callback.source.evidence.get("callback_json_path") or "")
        for callback in callbacks
    ]
    assert any(path.endswith("OnElationPointChange[0]") for path in paths), paths
    assert any(path.endswith("OnElationPointChange[1]") for path in paths), paths
    assert all(
        callback.coverage_status == "blocked" and callback.blocked_reason
        for callback in callbacks
    ), [(item.callback_id, item.coverage_status, item.blocked_reason) for item in callbacks]
    assert not any(
        watcher.modifier_name == name
        for watcher in result.ability_property_watchers
    )
