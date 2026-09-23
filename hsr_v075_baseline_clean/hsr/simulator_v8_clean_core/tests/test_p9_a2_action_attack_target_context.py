from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hsr.simulator_v8_clean_core.core.model import ActionCommand, BattleState, GameEvent, UnitState
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.rules.ir import IRSource, TargetExpressionNodeIR
from hsr.simulator_v8_clean_core.systems.action_event_contract import (
    AdmittedActionTargetFact,
    _issue_action_window_expected_scope,
)
from hsr.simulator_v8_clean_core.systems.action_selection import ActionTargetSelectionSystem
from hsr.simulator_v8_clean_core.systems.status_callbacks import (
    _callback_scoped_event,
    _retarget_event,
)
from hsr.simulator_v8_clean_core.systems.target import TargetSystem
from hsr.simulator_v8_clean_core.systems.unit_relation import TargetEvaluationContext
from hsr.simulator_v8_clean_core.tbgd.lowering import _target_expression_from_raw
from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering
from hsr.simulator_v8_clean_core.tools.validate_p9_s5c2_action_selection_query_submit_context import (
    DEFAULT_TBGD,
    _select_contracts,
    _state as _selection_state,
    _transport_rulebook,
)


def _state() -> BattleState:
    return BattleState(
        units={
            "actor": UnitState("actor", "ally", "avatar:actor"),
            "target:a": UnitState("target:a", "enemy", "monster:a"),
            "target:b": UnitState("target:b", "enemy", "monster:b"),
        }
    )


def _source() -> IRSource:
    return IRSource(
        "fixture/ability.json",
        "AbilityTask",
        "fixture:task",
        {"json_path": "$.AbilityList[0].TargetType"},
    )


def _expression() -> TargetExpressionNodeIR:
    expression = _target_expression_from_raw(
        {
            "$type": "RPG.GameCore.TargetSequence",
            "Sequence": [
                {
                    "$type": "RPG.GameCore.TargetFetchCaster",
                    "Name": "",
                    "UniqueName": "",
                },
                {"$type": "RPG.GameCore.TargetMapAttackTargetList"},
            ],
        },
        field_name="TargetType",
        expression_id="target_expression:sequence",
        source=_source(),
    )
    assert expression is not None and expression.coverage_status == "executable"
    return expression.node


def _map_expression(fetch_type: str | None) -> TargetExpressionNodeIR:
    sequence = []
    if fetch_type is not None:
        sequence.append({"$type": fetch_type, "Name": "", "UniqueName": ""})
    sequence.append({"$type": "RPG.GameCore.TargetMapAttackTargetList"})
    expression = _target_expression_from_raw(
        {"$type": "RPG.GameCore.TargetSequence", "Sequence": sequence},
        field_name="TargetType",
        expression_id=f"target_expression:{fetch_type or 'empty'}",
        source=_source(),
    )
    assert expression is not None and expression.coverage_status == "executable"
    return expression.node


def _context(fact: object | None, expected_scope: object | None = None) -> TargetEvaluationContext:
    return TargetEvaluationContext(
        caster_id="ally:actor",
        action_event_id="event:window",
        action_window="OnAttack",
        admitted_action_target_fact=fact,  # type: ignore[arg-type]
        expected_action_window_scope=expected_scope,  # type: ignore[arg-type]
    )


def _bind_fact(fact, *, event_id: str = "event:window", window: str = "OnAttack"):
    scope = _issue_action_window_expected_scope(
        execution_token=object(),
        actor_id=fact.actor_id,
        action_id=fact.action_id,
        action_level=fact.action_level,
        canonical_action_event_id=fact.canonical_action_event_id,
        impact_fingerprint=fact.impact_fingerprint,
        event_id=event_id,
        window=window,
        step_id=f"0:fixture:{window}",
        step_index=0,
    )
    return fact.bind_invocation(scope), scope


@pytest.fixture(scope="module")
def selection_fixture():
    lowering = TBGDLowering(DEFAULT_TBGD)
    catalog = lowering.build_action_target_contract_catalog()
    selected = _select_contracts(catalog)
    return catalog, selected


def _resolved_impact(selection_fixture, target_mode: str):
    catalog, selected = selection_fixture
    contract = selected["automatic"] if target_mode == "aoe" else selected["explicit"]
    rules = _transport_rulebook(catalog, selected["explicit"], selected["automatic"])
    events = tuple(
        replace(event, target_mode=target_mode)
        if event.action_id == contract.action_id and event.level == contract.level
        else event
        for event in rules.ir.action_events
    )
    rules = RuleBook(replace(rules.ir, action_events=events))
    state = _selection_state()
    system = ActionTargetSelectionSystem(rules)
    query = system.query(state, "ally:actor", contract.action_id, contract.level)
    submitted = () if query.selection_mode == "automatic" else ("enemy:actor",)
    accepted = system.accept(state, query, submitted)
    assert accepted.context is not None
    command = ActionCommand(
        actor_id="ally:actor",
        action_id=contract.action_id,
        action_level=contract.level,
        target_ids=submitted,
    )
    event = rules.action_event(contract.action_id, contract.level)
    assert event is not None
    impact = system.resolve_impact(state, command, accepted.context, event)
    assert impact.ok and impact.admitted_action_target_fact is not None
    return rules, state, system, command, accepted.context, event, impact


@pytest.mark.parametrize("target_mode", ["single", "self_or_team", "blast", "aoe"])
def test_resolve_impact_is_the_fact_producer_for_static_modes(
    selection_fixture, target_mode: str
) -> None:
    _rules, _state_value, _system, _command, _context_value, event, impact = (
        _resolved_impact(selection_fixture, target_mode)
    )
    fact = impact.admitted_action_target_fact
    assert fact is not None
    assert fact.target_mode == target_mode
    assert fact.canonical_action_event_id == event.action_event_id
    assert fact.target_ids == impact.resolution.impact_group
    assert "admitted_action_target_fact" not in impact.to_json()


def test_target_map_uses_only_issued_invocation_bound_impact_fact(selection_fixture) -> None:
    _rules, state, _system, _command, _accepted, _event, impact = _resolved_impact(
        selection_fixture, "blast"
    )
    fact = impact.admitted_action_target_fact
    assert fact is not None
    bound, scope = _bind_fact(fact)
    result = TargetSystem().resolve_target_expression(
        state, _expression(), context=_context(bound, scope)
    )
    assert result.resolved
    assert result.target_ids == impact.resolution.impact_group


def test_target_map_blocks_missing_fact() -> None:
    result = TargetSystem().resolve_target_expression(
        _selection_state(), _expression(), context=_context(None)
    )
    assert result.blocked


def test_target_map_rejects_forged_or_cross_invocation_facts(selection_fixture) -> None:
    forged = AdmittedActionTargetFact(
        actor_id="ally:actor",
        action_id="action:fixture",
        action_level=1,
        selection_context_fingerprint="selection:fixture",
        contract_fingerprint="contract:fixture",
        impact_fingerprint="impact:fixture",
        canonical_action_event_id="action_event:fixture",
        target_mode="single",
        target_ids=("enemy:actor",),
        event_id="event:window",
        window="OnAttack",
        step_id="0:fixture:OnAttack",
        step_index=0,
        _execution_token=object(),
    )
    forged_result = TargetSystem().resolve_target_expression(
        _selection_state(), _expression(), context=_context(forged)
    )
    assert forged_result.blocked_reason == "action_target_fact_not_issued"

    _rules, state, _system, _command, _accepted, _event, impact = _resolved_impact(
        selection_fixture, "single"
    )
    fact = impact.admitted_action_target_fact
    assert fact is not None
    cross_window = TargetSystem().resolve_target_expression(
        state,
        _expression(),
        context=TargetEvaluationContext(
            caster_id="ally:actor",
            action_event_id="event:other",
            action_window="OnAttack",
            admitted_action_target_fact=_bind_fact(fact)[0],
            expected_action_window_scope=_bind_fact(
                fact, event_id="event:other"
            )[1],
        ),
    )
    assert cross_window.blocked_reason == "action_target_fact_invocation_mismatch"


def test_target_map_rejects_same_event_from_another_execute_or_step(
    selection_fixture,
) -> None:
    _rules, state, _system, _command, _accepted, _event, impact = _resolved_impact(
        selection_fixture, "single"
    )
    fact = impact.admitted_action_target_fact
    assert fact is not None
    bound, scope = _bind_fact(fact)
    _other_bound, other_execute_scope = _bind_fact(fact)
    assert TargetSystem().resolve_target_expression(
        state,
        _expression(),
        context=_context(bound, other_execute_scope),
    ).blocked_reason == "action_target_fact_invocation_mismatch"

    wrong_step = _issue_action_window_expected_scope(
        execution_token=scope._execution_token,
        actor_id=fact.actor_id,
        action_id=fact.action_id,
        action_level=fact.action_level,
        canonical_action_event_id=fact.canonical_action_event_id,
        impact_fingerprint=fact.impact_fingerprint,
        event_id=scope.event_id,
        window=scope.window,
        step_id="1:fixture:OnAttack",
        step_index=1,
    )
    assert TargetSystem().resolve_target_expression(
        state,
        _expression(),
        context=_context(bound, wrong_step),
    ).blocked_reason == "action_target_fact_invocation_mismatch"


def test_target_map_checks_subject_and_current_state_after_capability(
    selection_fixture,
) -> None:
    _rules, state, _system, _command, _accepted, _event, impact = _resolved_impact(
        selection_fixture, "single"
    )
    fact = impact.admitted_action_target_fact
    assert fact is not None
    bound, scope = _bind_fact(fact)
    wrong_subject = TargetSystem().resolve_target_expression(
        state,
        _map_expression("RPG.GameCore.TargetFetchParamEntity"),
        context=TargetEvaluationContext(
            caster_id="ally:actor",
            parameter_entity_ids=("enemy:actor",),
            action_event_id="event:window",
            action_window="OnAttack",
            admitted_action_target_fact=bound,
            expected_action_window_scope=scope,
        ),
    )
    assert wrong_subject.blocked_reason == "action_target_fact_subject_mismatch"

    state_without_target = replace(
        state,
        units={
            unit_id: unit
            for unit_id, unit in state.units.items()
            if unit_id not in bound.target_ids
        },
    )
    unknown = TargetSystem().resolve_target_expression(
        state_without_target,
        _expression(),
        context=_context(bound, scope),
    )
    assert unknown.blocked_reason == "action_target_fact_target_unknown"


def test_target_map_validates_capability_before_legal_empty_subject(
    selection_fixture,
) -> None:
    _rules, state, _system, _command, _accepted, _event, impact = _resolved_impact(
        selection_fixture, "single"
    )
    fact = impact.admitted_action_target_fact
    assert fact is not None
    bound, scope = _bind_fact(fact)
    expression = _map_expression(None)
    assert TargetSystem().resolve_target_expression(
        state,
        expression,
        context=_context(bound, scope),
    ).target_ids == ()
    assert TargetSystem().resolve_target_expression(
        state,
        expression,
        context=_context(None),
    ).blocked_reason == "action_target_fact_missing"


def test_transient_capability_cannot_be_rebound_injected_or_lost_by_parameter(
    selection_fixture,
) -> None:
    _rules, _state_value, _system, _command, _accepted, _event, impact = (
        _resolved_impact(selection_fixture, "single")
    )
    fact = impact.admitted_action_target_fact
    assert fact is not None
    bound, scope = _bind_fact(fact)
    with pytest.raises(ValueError, match="already invocation-bound"):
        bound.bind_invocation(scope)
    with pytest.raises(ValueError, match="claims do not match"):
        replace(bound, window="forged")

    context = _context(bound, scope)
    changed = context.with_parameter("enemy:actor")
    assert changed.admitted_action_target_fact is bound
    assert changed.expected_action_window_scope is scope

    injected = GameEvent(
        "action.window.after_attack",
        source_id="ally:actor",
        target_id="enemy:actor",
        event_id="event:window",
        window="OnAttack",
        payload={
            "admitted_action_target_fact": "forged",
            "expected_action_window_scope": "forged",
        },
    )
    assert injected.admitted_action_target_fact is None
    assert injected.expected_action_window_scope is None


def test_fact_claims_and_canonical_event_cannot_be_replaced(selection_fixture) -> None:
    rules, state, system, command, context, event, impact = _resolved_impact(
        selection_fixture, "single"
    )
    fact = impact.admitted_action_target_fact
    assert fact is not None
    with pytest.raises(ValueError, match="claims do not match"):
        replace(fact, actor_id="ally:forged")
    with pytest.raises(ValueError, match="claims do not match"):
        replace(fact, target_ids=("enemy:second",))

    tampered_event = replace(event, target_mode="blast")
    blocked = system.resolve_impact(state, command, context, tampered_event)
    assert not blocked.ok
    assert blocked.blocked_reason == "action_target_impact_event_not_canonical"
    assert blocked.admitted_action_target_fact is None


def test_status_retarget_and_scope_events_preserve_transient_target_capability(
    selection_fixture,
) -> None:
    _rules, _state_value, _system, _command, _context_value, _event, impact = (
        _resolved_impact(selection_fixture, "single")
    )
    fact = impact.admitted_action_target_fact
    assert fact is not None
    bound, scope = _bind_fact(fact)
    event = GameEvent(
        "action.window.after_attack",
        source_id="ally:actor",
        target_id="enemy:actor",
        event_id="event:window",
        window="after_attack",
        admitted_action_target_fact=bound,
        expected_action_window_scope=scope,
    )

    scoped = _callback_scoped_event(
        _retarget_event(event, "enemy:actor"),
        callback_scope="fixture:targets:root",
        decision_index=0,
    )

    assert scoped.admitted_action_target_fact is bound
    assert scoped.expected_action_window_scope is scope
    assert "admitted_action_target_fact" not in scoped.to_json()
    assert "expected_action_window_scope" not in scoped.to_json()


def test_target_map_raw_lowering_is_strict_and_round_trips() -> None:
    expression = _target_expression_from_raw(
        {"$type": "RPG.GameCore.TargetMapAttackTargetList"},
        field_name="TargetType",
        expression_id="target_expression:fixture",
        source=_source(),
    )
    assert expression is not None and expression.coverage_status == "executable"
    assert TargetExpressionNodeIR.from_json(expression.node.to_json()) == expression.node

    invalid = _target_expression_from_raw(
        {"$type": "RPG.GameCore.TargetMapAttackTargetList", "Unexpected": True},
        field_name="TargetType",
        expression_id="target_expression:invalid",
        source=_source(),
    )
    assert invalid is not None and invalid.coverage_status == "blocked"
