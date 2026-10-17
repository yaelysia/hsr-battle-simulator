"""Real monster action source through command admission; not full monster startup."""
from dataclasses import replace
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.executor import CombatExecutor
from hsr.simulator_v8_clean_core.core.model import ActionCommand, BattleState, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.action_selection import ActionTargetSelectionSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def source_ir():
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    return TBGDLowering(root).build(
        avatar_ids=frozenset(), monster_ids=frozenset({"8011010", "8003040"}),
        stage_ids=frozenset(), include_equipment=False,
    )


def _state(hp=1000.0):
    return BattleState(units={
        "enemy": UnitState("enemy", "enemy", "monster:8011010", hp=1000, max_hp=1000, attack=100,
                           flags={"position": 0, "monster_data_card_id": "monster_data_card:monster:8011010",
                                  "enemy_action_sequence_cursor": 0}),
        "ally": UnitState("ally", "ally", "avatar:1008", hp=hp, max_hp=1000, energy=20, max_energy=100,
                          resources={"energy_regeneration_rate": 0.25}, flags={"position": 0}),
    }, global_flags={"phase": "combat", "current_window": "idle", "turn_owner_id": "enemy"})


def _execute(ir, state):
    rules = RuleBook(ir)
    selection = ActionTargetSelectionSystem(rules)
    query = selection.query(state, "enemy", "monster_skill:801101001", 1)
    assert query.status == "resolved", query.to_json()
    accepted = selection.accept(state, query, ("ally",))
    assert accepted.status == "accepted"
    return CombatExecutor(rules).execute(
        ActionCommand("enemy", "monster_skill:801101001", 1, ("ally",)), state,
        target_selection_context=accepted.context,
    )


def test_real_monster_action_query_uses_external_choices(source_ir):
    from hsr.simulator_v8_clean_core.systems.action_availability import ActionAvailabilitySystem
    from hsr.simulator_v8_clean_core.systems.enemy_action import EnemyActionSystem
    state = _state()
    rules = RuleBook(source_ir)
    constraint = EnemyActionSystem(rules).candidate_constraint(state, 'enemy')
    assert constraint['ok'] and constraint['mode'] == 'external_card_actions'
    choices, blocked = ActionAvailabilitySystem(rules)._enemy_choices(state, state.units['enemy'])
    assert choices, [reason.to_json() for reason in blocked]
    assert all(choice.choice_kind == 'normal_action' for choice in choices)
    assert {choice.action_id for choice in choices} == {'monster_skill:801101001'}
    assert all(choice.metadata['selection_controller'] == 'external' for choice in choices)


def test_real_single_monster_hit_gains_target_energy_without_toughness(source_ir):
    from hsr.simulator_v8_clean_core.core.action_plan import _damage_plan_from_emissions
    from hsr.simulator_v8_clean_core.core.executor import _damage_packet
    emission = next(e for e in source_ir.damage_emissions if e.action_id == "monster_skill:801101001")
    assert emission.hit_energy_gain == 10 and emission.toughness_emission_required is False
    assert not any(e.action_id == emission.action_id for e in source_ir.toughness_emissions)
    rules = RuleBook(source_ir)
    definition = rules.action_definition(emission.action_id, emission.level)
    plans = _damage_plan_from_emissions(
        definition, (emission,), {p.hit_profile_id: p for p in source_ir.hit_profiles},
        {emission.target_group: ("ally",)}, "ally", "",
    )
    assert len(plans) == 1 and plans[0].hit_energy_gain == 10
    packet = _damage_packet(ActionCommand("enemy", emission.action_id, 1, ("ally",)),
                            definition, emission.source.to_json(), plans[0])
    assert packet.hit_energy_gain == 10
    state = _state()
    after, transition = _execute(source_ir, state)
    assert transition.outcome.successor_eligible, transition.outcome.to_json()
    assert after.units["ally"].hp < state.units["ally"].hp
    assert after.units["ally"].energy == 32.5
    assert after.units["enemy"].energy == state.units["enemy"].energy
    assert sum(event.event_type == "hp.change" for event in transition.transaction.events) == 1
    assert sum(event.event_type == "energy.change" for event in transition.transaction.events) == 1
    energy = [m for m in transition.transaction.mutations if m.path[-1] == "energy"]
    assert len(energy) == 1 and energy[0].metadata["source_task_id"] == emission.source_task_id
    assert not any(m.path[-1] == "toughness" for m in transition.transaction.mutations)
    assert MutationReducer().replay_snapshot(state, transition.transaction.mutations, after.snapshot().to_json()).ok
    auditor = RuntimeSourceAuditor(RuleBook(source_ir))
    audit = auditor.validate_transition(transition)
    assert audit.ok, audit.to_json()
    records = tuple(record for record in transition.transaction.settlement.records
                    if record.get("mutation_id") == energy[0].stable_id())
    for changes in ({"raw_delta": 999}, {"target_id": "enemy"}, {"delta": 999},
                    {"energy_regeneration_rate": {}}):
        forged = replace(energy[0], metadata={**energy[0].metadata, **changes})
        forged_records = tuple({**record, "mutation_id": forged.stable_id()} for record in records)
        assert not auditor.validate_execution((forged,), forged_records).ok


@pytest.mark.parametrize('initial_energy', [20.0, 95.0])
def test_real_lethal_hit_commits_damage_defeat_and_target_energy(source_ir, initial_energy):
    state = _state(hp=1)
    state = replace(state, units={**state.units,
        'ally': replace(state.units['ally'], energy=initial_energy)})
    after, transition = _execute(source_ir, state)
    assert transition.outcome.successor_eligible, transition.outcome.to_json()
    assert after.units['ally'].hp == 0 and after.units['ally'].lifecycle_status == 'defeated'
    assert after.units['ally'].energy == min(100, initial_energy + 10 * 1.25)
    assert after.units['enemy'].energy == state.units['enemy'].energy
    energy = [m for m in transition.transaction.mutations if m.path[-1] == 'energy']
    assert len(energy) == 1 and energy[0].metadata['resource_operation'] == 'hit_energy_gain'
    assert MutationReducer().replay_snapshot(state, transition.transaction.mutations, after.snapshot().to_json()).ok
    audit = RuntimeSourceAuditor(RuleBook(source_ir)).validate_transition(transition)
    assert audit.ok, audit.to_json()


@pytest.mark.parametrize("initial_energy", [20.0, 95.0])
def test_real_two_request_weights_reach_damage_consumer_and_capacity(source_ir, initial_energy):
    # This isolates the real damage requests. The full monster's presentation /
    # modifier admission is a separate content task, not bypassed for this check.
    action_id = "monster_skill:800304003"
    emissions = tuple(e for e in source_ir.damage_emissions
                      if e.action_id == action_id and e.level == 1)
    assert len(emissions) == 2
    assert all(e.coverage_status == "executable" and e.hit_energy_gain == 7.5 for e in emissions)
    assert all(e.source.evidence["hit_energy_rule"]["request_weight"]["value"] == 0.5
               for e in emissions)
    rules = RuleBook(source_ir)
    state = _state()
    state = replace(state, units={
        **state.units,
        "enemy": replace(state.units["enemy"], template_id="monster:8003040", flags={
            "position": 0, "monster_data_card_id": "monster_data_card:monster:8003040",
            "enemy_action_sequence_cursor": 0,
        }),
        "ally": replace(state.units["ally"], hp=10000.0, max_hp=10000.0, energy=initial_energy),
    })
    command = ActionCommand("enemy", action_id, 1, ("ally",))
    selector = ActionTargetSelectionSystem(rules)
    query = selector.query(state, "enemy", action_id, 1)
    accepted = selector.accept(state, query, command.target_ids)
    assert accepted.status == "accepted", accepted.to_json()
    impact = selector.resolve_impact(state, command, accepted.context, rules.action_event(action_id, 1))
    assert impact.ok, impact.to_json()
    executor = CombatExecutor(rules)
    current = state
    all_mutations, all_records = [], []
    for index, emission in enumerate(emissions, 1):
        task = next(t for t in source_ir.ability_tasks if t.task_id == emission.source_task_id)
        current, mutations, events, _, records, _ = executor.ability_tasks._execute_damage_task(
            current, task, command=command, action_definition=rules.action_definition(action_id, 1),
            primary_target="ally", target_resolution=impact.resolution,
            task_graph_continuation=None, nested_ability_hooks=None,
        )
        assert any(m.path == ("units", "ally", "hp") for m in mutations), records
        assert current.units["ally"].energy == min(100, initial_energy + 7.5 * 1.25 * index)
        assert current.units["enemy"].energy == state.units["enemy"].energy
        all_mutations.extend(mutations)
        all_records.extend(records)
    assert MutationReducer().replay_snapshot(state, all_mutations, current.snapshot().to_json()).ok
    audit = RuntimeSourceAuditor(rules).validate_execution(tuple(all_mutations), tuple(all_records))
    assert audit.ok, audit.to_json()
