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
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR
from hsr.simulator_v8_clean_core.systems.action_selection import ActionTargetSelectionSystem
from hsr.simulator_v8_clean_core.systems.damage import DamagePacket, DamageSourceFrame, DamageSystem


def test_source_stack_property_admission_keeps_unknown_semantics_blocked():
    from hsr.simulator_v8_clean_core.tbgd.lowering import _status_callback_task_admission

    source = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main/Config/ConfigAbility/Avatar/Avatar_Arlan_00_Ability.json"
    task = json.loads(source.read_text())["GlobalModifiers"]["MAvatar_Arlan_00_Passive_DamageUp"]["_CallbackList"][0]["CallbackConfig"][0]
    assert _status_callback_task_admission("OnStack", "StackProperty", task) == ("executable", "")
    # A refresh-shaped stack property overwrites instead of accumulating and
    # runs through the runtime refresh branch, so it is an admitted shape.
    assert _status_callback_task_admission(
        "OnStack", "StackProperty", {**task, "IsRefresh": True}
    ) == ("executable", "")
    for changed in ({**task, "UnknownField": True},
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
        source_trace={"kind": "validation_fixture", "scope": "kill_energy"},
    )
    return state, packet


def _settle_packet(state, packet, system=None):
    executor = CombatExecutor(RuleBook(CanonicalIR("validation")))
    system = system or DamageSystem()
    executor.event_dispatcher.damage = system
    produced = system.apply_packet(state, packet)
    return executor.commit_eventful_transition(
        state, mutations=produced.mutations, events=produced.events, records=produced.records,
        rng_events=produced.rng_events, producer_kind="damage", producer_id="validation:lethal",
        actor_id=packet.attacker_id, producer_ok=produced.ok, blocked_reason=",".join(produced.errors),
    )


def test_shared_producer_attributes_once_to_living_owner_with_err():
    state, packet = _primitive_case()
    system = DamageSystem()
    result = _settle_packet(state, packet, system)
    assert not result.errors, result.errors
    energy = [mutation for mutation in result.mutations if mutation.path[-1] == "energy"]
    assert len(energy) == 1 and energy[0].path == ("units", "owner", "energy")
    assert (energy[0].before, energy[0].after) == (20, 32.5)
    assert energy[0].metadata["kill_credit_source_id"] == "source"
    assert sum(event.event_type == "unit.defeated" for event in result.events) == 1
    assert sum(event.event_type == "energy.change" for event in result.events) == 1
    after = MutationReducer().apply_all(state, result.mutations)
    assert after == result.after_state and after.units["target"].lifecycle_status == "defeated"
    assert "pending_defeat" not in after.units["target"].flags
    stages = [event for event in result.events if event.event_type.startswith("unit.")]
    assert [event.event_type for event in stages] == [
        "unit.before_dying", "unit.being_limbo", "unit.limbo_wait_heal", "unit.defeated"]
    assert all(event.event_id and event.payload["lifecycle_mutation_id"] for event in stages)
    repeated = _settle_packet(after, packet, system)
    assert not repeated.errors and not repeated.mutations
    dead_owner = replace(state, units={**state.units, "owner": replace(state.units["owner"], hp=0,
                                                                       lifecycle_status="defeated")})
    result = _settle_packet(dead_owner, packet, system)
    assert not result.errors and not any(m.path[-1] == "energy" for m in result.mutations)


def test_missing_kill_rule_rejects_entire_lethal_damage():
    state, packet = _primitive_case()
    registry = build_engine_rule_registry()
    registry = replace(registry, resource_rules=tuple(rule for rule in registry.resource_rules
                                                      if rule.rule_kind != "kill_energy_gain"))
    result = _settle_packet(state, packet, DamageSystem(engine_rules=registry))
    assert result.errors and not result.mutations and not result.rng_events
    assert result.after_state == state
    assert "resource_engine_rule_missing:kill_energy_gain" in result.errors


def test_missing_lethal_source_is_a_typed_atomic_rejection():
    state, packet = _primitive_case()
    result = DamageSystem().apply_packet(state, replace(packet, source_trace={}))
    assert not result.ok and not result.mutations and not result.events and not result.rng_events
    assert result.errors == ("pending_defeat_source_missing:source_trace",)


def test_limbo_receiver_and_native_cause_are_enforced():
    from hsr.simulator_v8_clean_core.systems.event_dispatch import _scope_matches
    from hsr.simulator_v8_clean_core.systems.unit_lifecycle import UnitLifecycleSystem
    from hsr.simulator_v8_clean_core.tbgd.lowering import _status_callback_scope_kind

    state, packet = _primitive_case()
    produced = DamageSystem().apply_packet(state, packet)
    pending = MutationReducer().apply_all(state, produced.mutations)
    plan = UnitLifecycleSystem().pending_defeat(pending, "target")
    assert type(plan).from_json(plan.to_json()) == plan
    event = UnitLifecycleSystem().limbo_events(plan)[-1]
    scope = _status_callback_scope_kind("OnLimboWaitHeal")
    for explicit in (False, True):
        assert _scope_matches(event, scope, {"owner_id": "target"}, explicit=explicit)[0]
        assert not _scope_matches(event, scope, {"owner_id": "owner"}, explicit=explicit)[0]
    executor = CombatExecutor(RuleBook(CanonicalIR("validation")))
    for forged in (replace(event, pending_defeat_plan=None),
                   replace(event, payload={**event.payload, "lifecycle_mutation_id": "wrong"})):
        rejected = executor.event_dispatcher.dispatch_event(pending, event=forged)
        assert rejected.errors and not rejected.mutations and rejected.after_state == pending
    completed = _settle_packet(state, packet)
    stale = executor.event_dispatcher.dispatch_event(completed.after_state, event=event)
    assert stale.errors and not stale.mutations and stale.after_state == completed.after_state


def test_packet_metadata_reserved_field_rejects_without_losing_evidence():
    state, packet = _primitive_case()
    result = DamageSystem().apply_packet(state, replace(packet, metadata={"packet_fields": {"source": "custom"}}))
    assert not result.ok and not result.mutations and not result.events
    assert result.errors == ("reserved_packet_metadata_field:packet_fields",)


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
@pytest.mark.integration
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
        # The lethal first hit defeats the target; the second hit of the same
        # action is skipped as a corpse hit (no duplicate zero-HP packet). Both
        # rank listeners therefore react to that one hit event: the trigger id
        # is shared, while each callback event keeps its own identity.
        assert len(callbacks) == 2
        assert len({event.payload["trigger_event_id"] for event in callbacks}) == 1
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
    hp = next(m for m in mutations if m.path == ("units", "target", "hp"))
    assert "packet_metadata" not in hp.metadata and "metadata" not in hp.metadata
    assert hp.metadata["packet_fields"]["target_id"] == "target"
    derived = [m for m in mutations if m.source == "damage_system"
               and m.metadata.get("lifecycle_operation") in {"unit_defeat", "unit_defeat_record"}]
    assert len(derived) == 2
    for mutation in [*derived, kills[0]]:
        assert mutation.metadata["hp_mutation_id"] == hp.stable_id()
        assert not {"damage_packet", "formula_result", "dot_formula_result", "numeric_evaluation"} & mutation.metadata.keys()
    for mutation in derived:
        forged = replace(mutation, mutation_id=mutation.stable_id(),
                         metadata={**mutation.metadata, "hp_mutation_id": "missing"})
        altered = tuple(forged if m is mutation else m for m in mutations)
        rejected = auditor.validate_execution(altered, transition.transaction.settlement.records)
        assert any(v.reason == "damage_lifecycle_lethal_mutation_lineage_invalid" for v in rejected.violations)
    for changes in ({"raw_energy_gain": 999}, {"hp_mutation_id": "missing"},
                    {"energy_regeneration_rate": {}}, {"kill_credit_owner_id": "spare"},
                    {"kill_credit_source_id": "forged"}):
        forged = replace(kills[0], mutation_id=kills[0].stable_id(), metadata={**kills[0].metadata, **changes})
        altered = tuple(forged if m is kills[0] else m for m in mutations)
        assert not auditor.validate_execution(altered, transition.transaction.settlement.records).ok


@pytest.mark.integration
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


@pytest.mark.integration
def test_real_admitted_action_missing_kill_rule_has_zero_commit(arlan_case):
    rules, state = arlan_case
    rejected = RuleBook(replace(rules.ir, resource_rules=tuple(
        rule for rule in rules.ir.resource_rules if rule.rule_kind != "kill_energy_gain")))
    before = state.snapshot().to_json()
    after, transition = _execute(rejected, state)
    assert not transition.outcome.successor_eligible and not transition.transaction.mutations
    assert after.snapshot().to_json() == before
    assert transition.outcome.reason_codes == (
        "ability_task_damage_event_blocked:resource_engine_rule_missing:kill_energy_gain",)
