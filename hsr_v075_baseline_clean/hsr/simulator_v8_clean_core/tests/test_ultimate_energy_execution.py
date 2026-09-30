"""Resource producer/transaction coverage, not an admitted Ultra ActionCommand graph.

The reusable action fixtures require a complete target catalog and task-graph
materialization. This bounded fixture exercises the actual resource producer,
effect failure, atomic commit and replay without replacing any production gate.
"""
from dataclasses import replace

from hsr.simulator_v8_clean_core.core.executor import CombatExecutor
from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.ir import ActionDefinitionIR, CanonicalIR, EffectIR, IRSource
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.action_preflight import action_resource_plan
from hsr.simulator_v8_clean_core.systems.effect import EffectExecutionContext, EffectRegistry
from hsr.simulator_v8_clean_core.systems.mutation_events import events_for_mutation
from hsr.simulator_v8_clean_core.systems.resource import ResourceSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import _effect_coverage_status, _effect_payload


def _fixture():
    source = IRSource("synthetic:ultimate-energy", "validation", "SPNeed-and-SPBase")
    definition = ActionDefinitionIR(
        "synthetic:ultimate", "synthetic:ultimate", 1, "Ultra", "Ultimate", "single",
        0, 0, 5.0, 0, (), (), (), None, source, coverage_status="executable", sp_need=100.0,
    )
    rules = RuleBook(CanonicalIR(version="synthetic:ultimate-energy", action_definitions=(definition,)))
    state = BattleState(units={"actor": UnitState(
        "actor", "ally", "synthetic:actor", energy=140.0, max_energy=200.0,
        resources={"energy_regeneration_rate": 0.25},
    )}, queues={"pending": ("preserved",)}, rng_state="synthetic:preserved")
    plan = action_resource_plan(definition, source="synthetic:ultimate-resources", metadata={
        "action_definition_id": definition.definition_id,
        "action_definition_source": source.to_json(),
    })
    return rules, state, plan


def test_cost_then_independent_base_gain_commits_two_energy_mutations_and_replays():
    rules, state, plan = _fixture()
    before = state.snapshot().to_json()
    assert plan.energy_cost == 100 and plan.energy_gain == 5
    produced = ResourceSystem().plan_action_resources(state, "actor", plan)
    assert produced.ok, produced.errors
    assert len(produced.mutations) == 2
    debit, gain = produced.mutations
    assert debit.path == gain.path == ("units", "actor", "energy")
    assert (debit.before, debit.after) == (140.0, 40.0)
    assert (gain.before, gain.after) == (40.0, 46.25)
    assert debit.metadata["resource_operation"] == "ultimate_energy_cost"
    assert debit.metadata["energy_cost"] == 100
    assert debit.metadata["raw_delta"] == -100
    assert gain.metadata["raw_delta"] == 5 and gain.metadata["delta"] == 6.25
    committed = CombatExecutor(rules).commit_eventful_transition(
        state, mutations=produced.mutations, events=(), producer_kind="resource_system",
        producer_id="actor", actor_id="actor", producer_ok=produced.ok,
    )
    assert not committed.errors, committed.errors
    assert len(committed.mutations) == 2
    assert committed.after_state.units["actor"].energy == 46.25
    assert committed.after_state.queues == state.queues
    assert committed.after_state.rng_state == state.rng_state
    assert state.snapshot().to_json() == before
    assert MutationReducer().replay_snapshot(
        state, committed.mutations, committed.after_state.snapshot().to_json(),
    ).ok


def test_missing_dynamic_effect_binding_discards_both_planned_energy_mutations():
    rules, state, plan = _fixture()
    before = state.snapshot().to_json()
    produced = ResourceSystem().plan_action_resources(state, "actor", plan)
    assert produced.ok and len(produced.mutations) == 2
    candidate = MutationReducer().apply_all(state, produced.mutations)
    raw = {"$type": "RPG.GameCore.ModifySPNew", "TargetType": {"Alias": "Caster"},
           "AddValue": {"IsDynamic": True, "PostfixExpr": {
               "OpCodes": "AQAR", "FixedValues": [], "DynamicHashes": [98765],
           }}}
    payload = _effect_payload(raw, "ModifySPNew", "")
    effect = EffectIR("synthetic:missing-energy-binding", "ModifySPNew", payload,
                      IRSource("synthetic:ultimate-effect", "ModifySPNew", "missing-binding"),
                      _effect_coverage_status("ModifySPNew", payload))
    failed = EffectRegistry().execute(effect, EffectExecutionContext(
        candidate, "actor", "synthetic:ultimate-effect", dynamic_values={},
    ))
    assert failed.unsupported and not failed.mutations and not failed.rng_events
    assert "dynamic" in str(failed.records)
    result = CombatExecutor(rules).commit_eventful_transition(
        state, mutations=produced.mutations, events=failed.events, records=failed.records,
        rng_events=failed.rng_events, producer_kind="ultimate_effect", producer_id="actor",
        actor_id="actor", producer_ok=False, blocked_reason=failed.unsupported[0],
    )
    assert result.errors and not result.mutations and not result.rng_events
    assert result.after_state.snapshot().to_json() == before
    assert result.after_state.units["actor"].energy == 140.0
    assert state.snapshot().to_json() == before
    assert MutationReducer().replay_snapshot(state, (), before).ok


def test_insufficient_authored_cost_produces_neither_cost_nor_base_gain():
    _rules, state, plan = _fixture()
    actor = replace(state.units["actor"], energy=99.0)
    state = replace(state, units={"actor": actor})
    produced = ResourceSystem().plan_action_resources(state, "actor", plan)
    assert not produced.ok
    assert produced.errors == ("ultimate_energy_not_ready",)
    assert not produced.mutations


def test_gain_replanned_after_intervening_energy_effect_keeps_its_gain():
    """Model a cost-listener output using the real effect and split resource plans."""
    rules, state, plan = _fixture()
    resources, reducer = ResourceSystem(), MutationReducer()
    debit = resources.plan_action_resources(state, "actor", replace(plan, energy_gain=0))
    assert debit.ok
    debited = reducer.apply_all(state, debit.mutations)
    assert debited.units["actor"].energy == 40.0
    raw = {"$type": "RPG.GameCore.ModifySPNew", "TargetType": {"Alias": "Caster"},
           "FixedAddValue": {"Value": 10}}
    payload = _effect_payload(raw, "ModifySPNew", "")
    effect = EffectIR("synthetic:cost-listener", "ModifySPNew", payload,
                      IRSource("synthetic:listener", "ModifySPNew", "fixed-energy"),
                      _effect_coverage_status("ModifySPNew", payload))
    intervening = EffectRegistry().execute(effect, EffectExecutionContext(debited, "actor", "synthetic:listener"))
    assert not intervening.unsupported
    changed = reducer.apply_all(debited, intervening.mutations)
    assert changed.units["actor"].energy == 50.0
    gain = resources.plan_action_resources(changed, "actor", replace(plan, energy_cost=0))
    assert gain.ok
    assert (gain.mutations[0].before, gain.mutations[0].after) == (50.0, 56.25)
    native_resource_events = tuple(
        event
        for mutation in (*debit.mutations, *gain.mutations)
        for event in events_for_mutation(mutation, actor_id="actor", source_id="actor", event_index=state.event_index)
    )
    result = CombatExecutor(rules).commit_eventful_transition(
        state, mutations=(*debit.mutations, *intervening.mutations, *gain.mutations),
        events=(*native_resource_events, *intervening.events), records=intervening.records,
        producer_kind="resource_steps", producer_id="actor", actor_id="actor",
    )
    assert not result.errors, result.errors
    assert len(result.mutations) == 3
    assert result.after_state.units["actor"].energy == 56.25
    assert reducer.replay_snapshot(state, result.mutations, result.after_state.snapshot().to_json()).ok
