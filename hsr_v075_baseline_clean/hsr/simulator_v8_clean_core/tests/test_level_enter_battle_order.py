"""Level owner entry follows combatant creation and precedes combatant entry."""

from unittest.mock import patch

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, IRSource, RuleEntity, StatusCallbackIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.scenarios.build_state import _dispatch_battle_setup_event
from hsr.simulator_v8_clean_core.scenarios.schema import ScenarioSpec
from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import _lower_status_event_families


def test_level_has_one_owner_entry_after_creation_before_combatant_entry():
    source = IRSource("fixture:stage", "Stage", "stage")
    callback = StatusCallbackIR(
        "level:enter", "MLevel", "OnEnterBattle", (), source, (0, 0),
        coverage_status="executable", admission_status="executable",
        scope_kind="owner_local", source_mode="mainline_stage_ability",
    )
    rules = RuleBook(CanonicalIR(
        "level-entry-order",
        entities=(RuleEntity("fixture:actor", "avatar", {}, source, "executable"),),
        status_callbacks=(callback,),
        status_event_families=tuple(_lower_status_event_families([callback], [])),
    ))
    detail = {
        "instance_id": "level:root", "owner_id": "level:global", "caster_id": "level:global",
        "source_id": "stage:root", "status_id": "modifier:MLevel", "modifier_name": "MLevel",
        "lifecycle_state": "active", "trigger_ids_by_event": {"OnEnterBattle": [callback.callback_id]},
        "ability_property_watcher_ids": [],
        "source_trace": source.to_json(),
    }
    state = BattleState(units={
        "actor": UnitState("actor", "ally", "fixture:actor"),
        "level:global": UnitState("level:global", "ally", "system_entity:level",
            statuses=(detail["status_id"],), flags={
                "system_entity_kind": "level", "system_entity_sources": [source.to_json()],
                "status_details": [detail],
            }),
        "event:system": UnitState("event:system", "ally", "system_entity:event",
            flags={"system_entity_kind": "battle_event"}),
    })
    scenario = ScenarioSpec("level-entry", "fixture", (), (), stage_ref="stage:fixture")
    dispatched = []
    original = EventDispatchSystem.dispatch_event

    def capture(dispatcher, current, *, event, **kwargs):
        dispatched.append(event)
        return original(dispatcher, current, event=event, **kwargs)

    with patch.object(EventDispatchSystem, "dispatch_event", capture):
        result = _dispatch_battle_setup_event(rules, state, scenario)
    assert not result.blocked
    assert [(event.event_type, event.target_id) for event in dispatched] == [
        ("unit.created", "actor"),
        ("battle.setup", "level:global"),
        ("battle.setup", "actor"),
    ]
    assert dispatched[1].payload["system_entity_sources"] == [source.to_json()]
    assert dispatched[1].payload["stage_ref"] == scenario.stage_ref
    callbacks = [event for event in result.events if event.event_type == "status.callback"]
    assert len(callbacks) == 1
    assert callbacks[0].target_id == "level:global"
    assert callbacks[0].payload["callback_id"] == callback.callback_id
    assert result.state is state and not result.mutations
