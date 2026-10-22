"""Two-instance monster summon keeps the parent action atomic.

The first summoned instance may already be born and started when the second one's
passive startup fails. The parent transition must then commit nothing: no unit, no
summon runtime, no listener dispatch, no RNG and no settlement leak.
"""
from __future__ import annotations

from dataclasses import replace

from hsr.simulator_v8_clean_core.core.model import BattleState, Mutation, UnitState
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems import startup as startup_module
from hsr.simulator_v8_clean_core.systems.summon import SummonSystem, SummonTransitionPlan
from hsr.simulator_v8_clean_core.systems.unit_lifecycle import UnitLifecycleSystem


def _spawn_births(state: BattleState, plan: SummonTransitionPlan):
    lifecycle = UnitLifecycleSystem()
    return tuple(
        lifecycle.spawn_mutation(
            state,
            UnitState(
                unit_id,
                "enemy",
                "monster:minion",
                flags={
                    "owner_id": plan.owner_id,
                    "summoner_id": plan.owner_id,
                    "summon_kind": "summoned_monster",
                },
            ),
            reason="spawn summoned monster",
            source="summon_system",
            source_trace={},
        )
        for unit_id in plan.unit_ids
    )


def test_second_child_startup_failure_rolls_back_both_births(monkeypatch):
    rules = RuleBook(CanonicalIR("summon-two-child-rollback-check"))
    system = SummonSystem(rules)
    state = BattleState(
        units={"owner": UnitState("owner", "enemy", "monster:owner", hp=100.0, max_hp=100.0)}
    )
    plan = SummonTransitionPlan(
        True, "spawn_summoned_monster", owner_id="owner", unit_ids=("child:a", "child:b")
    )
    births = _spawn_births(state, plan)
    before = state.snapshot().to_json()

    first_child_leak = Mutation(
        op="set",
        path=("units", "child:a", "flags"),
        before=None,
        after={"leaked": True},
        reason="first child startup",
        source="monster_startup",
    )
    seen: list[tuple[str, ...]] = []

    def fake_startup(candidate, rules_arg, unit_ids):
        seen.append(tuple(unit_ids))
        return startup_module._SetupApplyResult(
            candidate,
            records=({"record_type": "monster_startup", "payload": {"unit_id": "child:a"}},),
            mutations=(first_child_leak,),
            blocked=(
                {
                    "unit_id": "child:b",
                    "reason": "monster_passive_startup_root_on_start_has_unadmitted_tasks",
                },
            ),
            dispatched_event_ids=frozenset({"event:leaked-child-a"}),
        )

    monkeypatch.setattr(startup_module, "apply_monster_startup", fake_startup)
    result = system._with_halo_reconciliation(state, plan, births, (), ())

    assert seen == [("child:a", "child:b")]
    assert not result.plan.ok
    assert result.plan.blocked_reason.startswith("summon_monster_startup_blocked:")
    assert "monster_passive_startup_root_on_start_has_unadmitted_tasks" in result.plan.blocked_reason
    # Nothing of the partially started pair survives the failed transition.
    assert result.mutations == ()
    assert result.events == ()
    assert result.rng_events == ()
    assert result.dispatched_event_ids == frozenset()
    assert "child:a" not in state.units and "child:b" not in state.units
    assert "summon_runtime" not in state.global_flags
    assert state.snapshot().to_json() == before


def test_spawn_events_are_dispatched_once_per_instance(monkeypatch):
    rules = RuleBook(CanonicalIR("summon-two-child-dispatch-check"))
    system = SummonSystem(rules)
    state = BattleState(
        units={"owner": UnitState("owner", "enemy", "monster:owner", hp=100.0, max_hp=100.0)}
    )
    plan = SummonTransitionPlan(
        True, "spawn_summoned_monster", owner_id="owner", unit_ids=("child:a", "child:b")
    )
    births = _spawn_births(state, plan)
    seen: list[tuple[str, ...]] = []

    def fake_startup(candidate, rules_arg, unit_ids):
        seen.append(tuple(unit_ids))
        return startup_module._SetupApplyResult(candidate)

    monkeypatch.setattr(startup_module, "apply_monster_startup", fake_startup)
    result = system._with_halo_reconciliation(state, plan, births, (), ())

    assert seen == [("child:a", "child:b")]
    assert result.plan.ok
    spawn_event_ids = [
        str(event.to_json()["event_id"])
        for event in result.events
        if event.event_type.startswith("unit.")
    ]
    assert len(spawn_event_ids) == len(set(spawn_event_ids))
    assert result.dispatched_event_ids.issubset(set(spawn_event_ids))
    spawned = [mutation for mutation in result.mutations if mutation.op == "spawn"]
    assert {str(mutation.path[1]) for mutation in spawned} == {"child:a", "child:b"}
