"""A registered status event can enter the existing formal nested graph."""
from dataclasses import replace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from simulator_v8_clean_core.core.model import BattleState, GameEvent, Mutation, UnitState
from simulator_v8_clean_core.core.reducer import MutationReducer
from simulator_v8_clean_core.rules.ir import CanonicalIR, StatusEventFamilyIR
from simulator_v8_clean_core.rules.rulebook import RuleBook
from simulator_v8_clean_core.systems.ability import AbilityTaskSystem
from simulator_v8_clean_core.systems.effect import EffectRegistry
from simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
from simulator_v8_clean_core.systems.status import StatusSystem
from simulator_v8_clean_core.systems.status_callbacks import StatusCallbackExecutionResult
from simulator_v8_clean_core.tools.validate_p9_s8b5c_cross_entry_runtime_transport import (
    _Rules, _Dispatcher, _install_ability, _install_callback, _event,
)


def test_registered_root_injects_nested_hooks_without_action_capability(monkeypatch):
    empty = RuleBook(CanonicalIR("registered-nested-check"))

    class Rules(_Rules):
        def __getattr__(self, name):
            return getattr(empty, name)

        def status_event_family(self, event):
            return family if event == family.callback_event else None

        def status_event_families_for_runtime_event(self, event):
            return (family,) if event in family.runtime_event_sources else ()

    rules = Rules()
    child = _install_ability(rules, "A")
    callback, detail, root = _install_callback(rules, "C", child.owner_id)
    detail.update(lifecycle_state="active", source_id="fixture:source", ability_property_watcher_ids=[])
    family = StatusEventFamilyIR("family:enter", callback.event, "battle", "status_local",
        ("battle.start",), "fixture", callback.source,
        coverage_status="executable", admission_status="executable")
    registry = EffectRegistry(StatusSystem(rules))
    dispatcher = object.__new__(_Dispatcher)
    EventDispatchSystem.__init__(dispatcher, rules, registry)
    dispatcher.details = {callback.callback_id: detail}
    state = BattleState(units={"owner": UnitState("owner", "ally", "fixture:owner", hp=100, max_hp=100,
        statuses=(detail["status_id"],), flags={"status_details": [detail]})},
        global_flags={"phase": "combat"})
    observed = []

    def leaf(_system, current, task, *, invocation, **kwargs):
        observed.append(invocation)
        assert invocation.actor_id == detail["caster_id"]
        assert invocation.admitted_action_target_fact is None
        assert invocation.expected_action_window_scope is None
        assert kwargs["task_graph_continuation"].active_graph_stack == (root.graph_id, child.graph_id)
        mutation = Mutation("set", ("units", "owner", "hp"), current.units["owner"].hp, 90.0,
            "nested transport check", "fixture")
        # Mutation is reduced by the production TaskGraphExecutor boundary.
        return current, [mutation], [], [], [], []

    monkeypatch.setattr(AbilityTaskSystem, "_execute_formal_leaf_task", leaf)
    event = _event((callback.callback_id,), "registered-event")
    result = dispatcher.dispatch_event(state, event=event)
    assert not result.errors, result.errors
    assert result.after_state.units["owner"].hp == 90 and len(observed) == 1
    assert state.units["owner"].hp == 100

    # A synchronous inner dispatcher has already consumed this child. The
    # outer boundary must keep its evidence without executing it a second time.
    processed_child = GameEvent("custom.event", source_id="owner", target_id="owner",
        event_id="fixture:already-processed", payload={"callback_events": [callback.event]})
    handled = []
    def already_dispatched(current, **_kwargs):
        handled.append(current)
        mutation = Mutation("set", ("units", "owner", "hp"), current.units["owner"].hp, 90.,
            "synchronous inner callback", "fixture")
        return StatusCallbackExecutionResult(True, MutationReducer().apply(current, mutation),
            mutations=(mutation,), events=(processed_child,),
            dispatched_event_ids=frozenset({processed_child.event_id}))
    with monkeypatch.context() as scoped:
        scoped.setattr(dispatcher.status_callbacks, "execute_registered_event_formal_root", already_dispatched)
        once = dispatcher.dispatch_event(state, event=event)
        assert not once.errors and len(handled) == 1
        assert once.after_state.units["owner"].hp == 90 and len(once.mutations) == 1
        assert once.events.count(processed_child) == 1
        assert processed_child.event_id in once.dispatched_event_ids

    rejected = dispatcher.dispatch_event(state, event=replace(event, event_type="fixture.unknown"))
    assert "registered_event_formal_root_source_not_admitted" in rejected.errors
    assert rejected.after_state == state and not rejected.mutations and len(observed) == 1
    dispatcher.details[callback.callback_id] = {**detail, "trigger_ids_by_event": {callback.event: []}}
    unattached_state = replace(state, units={"owner": replace(state.units["owner"],
        flags={"status_details": [dispatcher.details[callback.callback_id]]})})
    unattached = dispatcher.dispatch_event(unattached_state, event=event)
    assert "status_callback_not_attached_to_instance" in unattached.errors
    assert unattached.after_state == unattached_state and not unattached.mutations
