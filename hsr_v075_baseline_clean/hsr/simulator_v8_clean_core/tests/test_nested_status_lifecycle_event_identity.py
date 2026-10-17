"""A callback-emitted lifecycle event is returned once after recursive dispatch."""

from types import SimpleNamespace
from dataclasses import replace

from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, RNGEvent, UnitState
from hsr.simulator_v8_clean_core.core.executor import _dedupe_events, _EventIdentityConflict
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, IRSource, StatusCallbackIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.effect import EffectRegistry
from hsr.simulator_v8_clean_core.systems.event_dispatch import (
    MAX_CALLBACK_EMITTED_EVENT_DEPTH, EventDispatchSystem, EventNormalization, ListenerMatch,
)
from hsr.simulator_v8_clean_core.systems.status_callbacks import StatusCallbackExecutionResult


def test_nested_lifecycle_event_has_one_identity_and_keeps_callback_rng():
    rules = RuleBook(CanonicalIR("nested-status-lifecycle-check"))
    dispatch = EventDispatchSystem(rules, EffectRegistry())
    state = BattleState(units={"owner": UnitState("owner", "ally", "fixture:owner")})
    parent = GameEvent(
        "status.lifecycle", source_id="owner", target_id="owner", window="OnCreate",
        event_id="parent", payload={"callback_event": "OnCreate", "lifecycle_operation": "add",
                                    "modifier_name": "M", "status_instance_id": "s", "mutation_event_depth": 1},
    )
    child = GameEvent(
        "status.lifecycle", source_id="owner", target_id="owner", window="OnStack",
        event_id="child", payload={"callback_event": "OnStack", "lifecycle_operation": "add",
                                   "modifier_name": "M", "status_instance_id": "s"},
    )
    callback = StatusCallbackIR(
        "callback", "M", "OnCreate", (), IRSource("fixture", "fixture", "M"), (0, 0),
        coverage_status="executable", admission_status="executable",
    )
    match = ListenerMatch(
        "status_callback", "status_local", "OnCreate", "owner", "M", callback,
        status_detail={"owner_id": "owner", "modifier_name": "M", "instance_id": "s"},
    )
    dispatch._resolve_listener_matches = lambda state, *, event, **kwargs: (
        (match,) if event.event_id == "parent" else ()
    )
    dispatch.status_callbacks = SimpleNamespace(execute=lambda state, **kwargs: StatusCallbackExecutionResult(
        True, state, events=(child,), rng_events=(RNGEvent("fixture", "fixture", 1, event_id="rng:1"),),
    ))

    result = dispatch.dispatch_event(state, event=parent)
    assert not result.errors
    assert [event.to_json()["event_id"] for event in result.events] == ["parent", "child"]
    assert [event.to_json()["event_id"] for event in result.rng_events] == ["rng:1"]
    canonical = _dedupe_events(parent, child, *result.events,
                               event_normalizations=result.event_normalizations)
    assert len(canonical) == 2 and canonical[1].payload['mutation_event_depth'] == 2
    for invalid_depth in (0, -1, True, MAX_CALLBACK_EMITTED_EVENT_DEPTH + 1):
        invalid = replace(child, payload={**child.payload, 'mutation_event_depth': invalid_depth})
        try:
            _dedupe_events(child, event_normalizations=(EventNormalization(child, invalid, 'mutation_event_depth'),))
        except _EventIdentityConflict:
            continue
        raise AssertionError('invalid callback depth admitted')
