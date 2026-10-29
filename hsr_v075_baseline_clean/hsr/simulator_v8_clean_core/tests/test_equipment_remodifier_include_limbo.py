"""R06 integration: Remodifier IncludeLimbo candidate filtering (23041 Smelt).

The query payload is the real lowered 23041 OnBeforeHitAll task; the target
status instance carries a real behavior flag and committed owner/caster fields.
"""
from __future__ import annotations

import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.systems.status_callbacks import (
    resolve_remodifier_status_scopes,
)
from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook

pytestmark = pytest.mark.integration


@lru_cache(maxsize=1)
def _rules():
    core = Path(__file__).resolve().parents[1]
    scenario = json.loads(
        (core / "examples/cli/arlan_fleet_vs_antimatter.json").read_text()
    )
    return build_battle_rulebook(
        Path(__file__).resolve().parents[4] / "turnbasedgamedata-main", scenario
    )


def _remodifier_payload(rules):
    graph = next(
        item
        for item in rules.ir.standalone_ability_graphs
        if item.ability_name == "Ability23041"
        and item.source_mode == "mainline_equipment"
    )
    callback = next(
        rules.status_callback(callback_id)
        for callback_id in graph.status_callback_ids
        if rules.status_callback(callback_id).event == "OnBeforeHitAll"
    )
    task = next(
        rules.status_callback_task(task_id)
        for task_id in callback.task_ids
        if rules.status_callback_task(task_id).opcode == "Remodifier"
    )
    return task.task_payload


def _status_detail(owner_id, caster_id):
    return {
        "instance_id": "status:test:implanted-weakness",
        "status_id": "modifier:TestImplantedWeakness",
        "modifier_name": "TestImplantedWeakness",
        "owner_id": owner_id,
        "caster_id": caster_id,
        "lifecycle_state": "active",
        "status_type": "Debuff",
        "behavior_flags": ["STAT_AttachWeakness"],
        "stacks": 1,
        "remaining_duration": 2,
        "modifiers": [],
        "dynamic_values": {},
        "source_trace": {"test_fixture": "implanted_weakness"},
    }


def _state(lifecycle_status="active", caster_id="holder"):
    detail = _status_detail("enemy", caster_id)
    enemy = UnitState(
        "enemy", "enemy", "test:enemy", max_hp=5000.0, hp=5000.0,
        speed=100.0, lifecycle_status=lifecycle_status,
        statuses=("modifier:TestImplantedWeakness",),
        flags={"status_details": (detail,)},
    )
    return BattleState(units={
        "holder": UnitState("holder", "ally", "test:holder", max_hp=2000.0,
                            hp=2000.0, speed=110.0),
        "enemy": enemy,
    })


def _resolve(state, payload, **kwargs):
    return resolve_remodifier_status_scopes(
        state, payload, ("enemy",), **kwargs
    )


def test_remodifier_includes_limbo_only_when_the_source_declares_it():
    rules = _rules()
    payload = _remodifier_payload(rules)
    assert payload.get("IncludeLimbo") is True
    assert payload.get("BehaviorFlagFilter") == ["STAT_AttachWeakness"]
    assert payload.get("CasterFilter") == "Caster"
    on_field = _state()
    included = _resolve(on_field, payload, caster_id="holder", maximum=1)
    assert included.status == "resolved"
    assert len(included.status_scopes) == 1
    assert included.status_scopes[0].owner_id == "enemy"

    # Without the source flag the same live target stays selected.
    without_flag = {key: value for key, value in payload.items()
                    if key != "IncludeLimbo"}
    assert len(_resolve(on_field, without_flag, caster_id="holder",
                        maximum=1).status_scopes) == 1

    limbo = _state(lifecycle_status="limbo")
    excluded = _resolve(limbo, without_flag, caster_id="holder", maximum=1)
    assert excluded.status == "resolved"
    assert excluded.status_scopes == ()

    admitted = _resolve(limbo, {**payload, "IncludeLimbo": True},
                        caster_id="holder", maximum=1)
    assert admitted.status == "resolved"
    assert len(admitted.status_scopes) == 1

    # Caster/behavior filters still gate the instance; the flag is not a bypass.
    wrong_caster = _state(caster_id="someone-else")
    assert _resolve(wrong_caster, payload, caster_id="holder",
                    maximum=1).status_scopes == ()
    assert len(_resolve(wrong_caster, payload, caster_id="someone-else",
                        maximum=1).status_scopes) == 1
