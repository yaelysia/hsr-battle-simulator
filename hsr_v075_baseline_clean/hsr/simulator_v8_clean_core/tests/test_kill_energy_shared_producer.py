"""Shared kill settlement and a real admitted Arlan action, with typed test targets."""
from dataclasses import replace
import math
import json
from pathlib import Path

import pytest

from hsr.simulator_v8_clean_core.core.executor import CombatExecutor
from hsr.simulator_v8_clean_core.core.model import ActionCommand, BattleState, UnitState
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from hsr.simulator_v8_clean_core.rules.engine_rule_registry import build_engine_rule_registry
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.action_selection import ActionTargetSelectionSystem
from hsr.simulator_v8_clean_core.systems.damage import DamagePacket, DamageSourceFrame, DamageSystem


def test_source_stack_property_admission_keeps_unknown_semantics_blocked():
    from hsr.simulator_v8_clean_core.tbgd.lowering import _status_callback_task_admission

    source = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main/Config/ConfigAbility/Avatar/Avatar_Arlan_00_Ability.json"
    task = json.loads(source.read_text())["GlobalModifiers"]["MAvatar_Arlan_00_Passive_DamageUp"]["_CallbackList"][0]["CallbackConfig"][0]
    assert _status_callback_task_admission("OnStack", "StackProperty", task) == ("executable", "")
    for changed in ({**task, "IsRefresh": True}, {**task, "UnknownField": True},
                    {**task, "TargetType": {"Alias": "Caster", "TaskList": []}}):
        status, reason = _status_callback_task_admission("OnStack", "StackProperty", changed)
        assert status == "blocked" and reason


def _primitive_case():
    state = BattleState(units={
        "source": UnitState("source", "ally", "test:source", hp=100, max_hp=100),
        "owner": UnitState("owner", "ally", "test:owner", hp=100, max_hp=100,
                           energy=20, max_energy=100, resources={"energy_regeneration_rate": 0.25}),
        "target": UnitState("target", "enemy", "test:target", hp=1, max_hp=100),
    })
    packet = DamagePacket(
        attacker_id="source", target_id="target", attack_type="test", damage_formula_family="true_damage",
        amount=2, amount_stage="fixed_final", source_frame=DamageSourceFrame(
            owner_id="owner", source_id="source", source_kind="unit", sequence_id="test:sequence",
            target_id="target",
        ),
    )
    return state, packet


def test_shared_producer_attributes_once_to_living_owner_with_err():
    state, packet = _primitive_case()
    system = DamageSystem()
    result = system.apply_packet(state, packet)
    assert result.ok, result.errors
    energy = [mutation for mutation in result.mutations if mutation.path[-1] == "energy"]
    assert len(energy) == 1 and energy[0].path == ("units", "owner", "energy")
    assert (energy[0].before, energy[0].after) == (20, 32.5)
    assert energy[0].metadata["kill_credit_source_id"] == "source"
    assert sum(event.event_type == "unit.defeated" for event in result.events) == 1
    assert sum(event.event_type == "energy.change" for event in result.events) == 1
    after = MutationReducer().apply_all(state, result.mutations)
    repeated = system.apply_packet(after, packet)
    assert repeated.ok and not repeated.mutations
    dead_owner = replace(state, units={**state.units, "owner": replace(state.units["owner"], hp=0,
                                                                       lifecycle_status="defeated")})
    result = system.apply_packet(dead_owner, packet)
    assert result.ok and not any(m.path[-1] == "energy" for m in result.mutations)


def test_missing_kill_rule_rejects_entire_lethal_damage():
    state, packet = _primitive_case()
    registry = build_engine_rule_registry()
    registry = replace(registry, resource_rules=tuple(rule for rule in registry.resource_rules
                                                      if rule.rule_kind != "kill_energy_gain"))
    result = DamageSystem(engine_rules=registry).apply_packet(state, packet)
    assert not result.ok and not result.mutations and not result.rng_events
    assert "resource_engine_rule_missing:kill_energy_gain" in result.errors


@pytest.fixture(scope="module")
def arlan_case():
    from hsr.simulator_v8_clean_core.tests.test_character_passive_startup import _source_case
    rules, built = _source_case()
    owner = replace(built.state.units["owner"], energy=20,
                    resources={**built.state.units["owner"].resources, "energy_regeneration_rate": 0.25})
    state = replace(built.state, units={
        "owner": owner,
        "target": UnitState("target", "enemy", "test:target", hp=1, max_hp=1000,
                            toughness=100, max_toughness=100, flags={"position": 0}),
        "spare": UnitState("spare", "enemy", "test:spare", hp=1000, max_hp=1000,
                           toughness=100, max_toughness=100, flags={"position": 1}),
    }, global_flags={**built.state.global_flags, "phase": "combat", "current_window": "idle",
                     "turn_owner_id": "owner"})
    return rules, state


def _execute(rules, state, action_id="avatar_skill:100801"):
    selection = ActionTargetSelectionSystem(rules)
    query = selection.query(state, "owner", action_id, 1)
    assert query.status == "resolved", query.to_json()
    accepted = selection.accept(state, query, ("target",))
    assert accepted.status == "accepted", accepted.to_json()
    return CombatExecutor(rules).execute(
        ActionCommand("owner", action_id, 1, ("target",)), state,
        target_selection_context=accepted.context,
    )


@pytest.mark.parametrize("action_id,expected_energy", [("avatar_skill:100801", 57.5), ("avatar_skill:100802", 70.0)])
def test_real_admitted_action_kill_energy_and_spbase_are_distinct_once(arlan_case, action_id, expected_energy):
    rules, state = arlan_case
    after, transition = _execute(rules, state, action_id)
    assert transition.outcome.successor_eligible, transition.outcome.to_json()
    mutations = transition.transaction.mutations
    kills = [m for m in mutations if m.source == "damage_system.kill_energy"]
    assert len(kills) == 1 and kills[0].metadata["raw_energy_gain"] == 10
    assert kills[0].after - kills[0].before == 12.5
    gains = [m for m in mutations if m.path == ("units", "owner", "energy")]
    assert len(gains) == 2
    assert after.units["owner"].energy == expected_energy  # SPBase (20/30) + caused-kill 10, at ERR 25%.
    assert sum(event.event_type == "unit.defeated" for event in transition.transaction.events) == 1
    assert sum(event.event_type == "energy.change" for event in transition.transaction.events) == 2
    if action_id == "avatar_skill:100801":
        callbacks = [event for event in transition.transaction.events
                     if event.event_type == "status.callback" and event.window == "OnBeforeHitAll"]
        assert len({event.payload["trigger_event_id"] for event in callbacks}) >= 2
        assert len({event.to_json()["event_id"] for event in callbacks}) == len(callbacks)
    else:
        from hsr.simulator_v8_clean_core.tests.test_character_passive_startup import _bonus
        owner = after.units["owner"]
        assert owner.hp < state.units["owner"].hp
        assert math.isclose(_bonus(owner), (1 - owner.hp / owner.max_hp) * 0.36)
        damage = next(m for m in mutations if m.path == ("units", "target", "hp"))
        assert math.isclose(damage.metadata["formula_result"]["multipliers"]["damage_bonus"], 1 + _bonus(owner))
    assert MutationReducer().replay_snapshot(state, mutations, after.snapshot().to_json()).ok
    auditor = RuntimeSourceAuditor(rules)
    audit = auditor.validate_transition(transition)
    assert audit.ok, audit.to_json()
    for changes in ({"raw_energy_gain": 999}, {"hp_mutation_id": "missing"},
                    {"energy_regeneration_rate": {}}, {"kill_credit_owner_id": "spare"},
                    {"kill_credit_source_id": "forged"}):
        forged = replace(kills[0], metadata={**kills[0].metadata, **changes})
        altered = tuple(forged if m is kills[0] else m for m in mutations)
        assert not auditor.validate_execution(altered, transition.transaction.settlement.records).ok


def test_admitted_basic_applies_resolved_toughness_after_hp_damage(arlan_case):
    rules, state = arlan_case
    target = replace(state.units["target"], hp=1000,
                     flags={**state.units["target"].flags, "weaknesses": ["Thunder"]})
    state = replace(state, units={**state.units, "target": target})
    after, transition = _execute(rules, state)
    assert transition.outcome.successor_eligible, transition.outcome.to_json()
    assert after.units["target"].toughness == 70
    assert after.units["target"].hp < target.hp
    damage = next(m for m in transition.transaction.mutations
                  if m.path == ("units", "target", "hp"))
    assert damage.metadata["formula_result"]["multipliers"]["toughness_state"] == 0.9
    event_types = [event.event_type for event in transition.transaction.events]
    assert event_types.index("damage.hit") < event_types.index("toughness.hit")


def test_real_admitted_action_missing_kill_rule_has_zero_commit(arlan_case):
    rules, state = arlan_case
    rejected = RuleBook(replace(rules.ir, resource_rules=tuple(
        rule for rule in rules.ir.resource_rules if rule.rule_kind != "kill_energy_gain")))
    before = state.snapshot().to_json()
    after, transition = _execute(rejected, state)
    assert not transition.outcome.successor_eligible and not transition.transaction.mutations
    assert after.snapshot().to_json() == before
    assert "resource_engine_rule_missing:kill_energy_gain" in transition.outcome.reason_codes
