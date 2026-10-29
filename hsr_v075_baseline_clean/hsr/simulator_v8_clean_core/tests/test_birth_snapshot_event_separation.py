"""Combatant creation must not dispatch a snapshot-entity callback."""

from hsr.simulator_v8_clean_core.core.model import BattleState, GameEvent, Mutation, UnitState
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, IRSource, StatusCallbackIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.effect import EffectRegistry
from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchSystem
from hsr.simulator_v8_clean_core.systems.mutation_events import events_for_mutation
from hsr.simulator_v8_clean_core.systems.summon import SummonTransitionPlan, _spawn_event
from hsr.simulator_v8_clean_core.tbgd.lowering import _lower_status_event_families


def test_birth_events_leave_snapshot_callback_blocked_and_uninvoked():
    callback = StatusCallbackIR(
        "snapshot:callback", "M", "OnSnapshotCreate", (),
        IRSource("fixture", "fixture", "M"), (0, 0),
        scope_kind="global_listener", coverage_status="blocked", admission_status="blocked",
        blocked_reason="status_callback_event_not_admitted:OnSnapshotCreate",
    )
    families = tuple(_lower_status_event_families([callback], []))
    rules = RuleBook(CanonicalIR("birth-snapshot-check", status_callbacks=(callback,),
                                 status_event_families=families))
    born = UnitState("born", "enemy", "fixture:born")
    state = BattleState(units={"owner": UnitState("owner", "ally", "fixture:owner"), "born": born})
    mutation = Mutation("spawn", ("units", "born"), None, born.to_snapshot(),
                        "birth", "unit_spawn_system", before_exists=False)
    events = (
        GameEvent("unit.created", source_id="owner", target_id="born",
                  payload={"unit_id": "born", "param_entity_id": "born"}),
        *events_for_mutation(mutation, actor_id="owner"),
        _spawn_event(state, SummonTransitionPlan(True, "spawn_summon", owner_id="owner"), born),
    )
    dispatch = EventDispatchSystem(rules, EffectRegistry())
    for event in events:
        result = dispatch.dispatch_event(state, event=event)
        assert not result.errors, result.errors
        assert not result.mutations
        assert all(alias["callback_event"] != "OnSnapshotCreate"
                   for record in result.event_normalizations
                   for alias in record.get("aliases", ()))
    # A caller explicitly requesting the unresolved snapshot event still fails closed.
    result = dispatch.dispatch_event(state, event=GameEvent(
        "snapshot.created", source_id="owner", target_id="born", window="OnSnapshotCreate"))
    # A unit birth or exported state cannot mint the heal-snapshot protocol;
    # the runtime rejects the undeclared event source for the family.
    assert result.errors == ("event_source_not_admitted_for_family:snapshot.created",)
    assert not result.mutations and result.after_state is state
