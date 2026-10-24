"""Component boundaries for external ability failure propagation.

These checks isolate the external-legacy walker with typed reducer and event
results.  They do not compile TBGD, construct a BattleSession, or replay an
archive.  The presentation case exercises a component source-shape contract;
the real Arlan source slice stays in test_arlan_action_graph_mvp.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hsr.simulator_v8_clean_core.core.model import (
    BattleState,
    GameEvent,
    Mutation,
    RNGEvent,
    TargetResolution,
    UnitState,
)
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.rules.evaluator import EvaluationContext, RuleEvaluator
from hsr.simulator_v8_clean_core.rules.expression_ir import (
    CONDITION_EXPRESSION_NODE_SCHEMA,
)
from hsr.simulator_v8_clean_core.rules.ir import (
    ConditionIR,
    EffectIR,
    IRSource,
)
from hsr.simulator_v8_clean_core.systems.ability import (
    AbilityTaskSystem,
    StandaloneAbilityInvocation,
    _FormalAbilityInvocation,
    _external_legacy_trigger_is_process_only,
    _task_process_record,
)
from hsr.simulator_v8_clean_core.systems.condition_state import (
    CommittedConditionFactProvider,
)
from hsr.simulator_v8_clean_core.systems.event_dispatch import EventDispatchResult
from hsr.simulator_v8_clean_core.systems.queue import QueueDrainPlan, QueueSystem
from hsr.simulator_v8_clean_core.tbgd.lowering import _typed_condition_payload


# ---------------------------------------------------------------------------
# External-legacy walker fixtures (component inputs, not TBGD content).
# ---------------------------------------------------------------------------


def _battle_state() -> BattleState:
    return BattleState(
        units={
            "owner": UnitState(
                "owner", "ally", "avatar:component", hp=100.0, max_hp=100.0
            ),
            "child": UnitState(
                "child", "enemy", "monster:component", hp=100.0, max_hp=100.0
            ),
        }
    )


def _task(
    task_id: str,
    *,
    opcode: str = "ForceKill",
    coverage: str = "executable",
    execution_mode: str = "runtime_effect",
    effect_id: str = "",
    blocked_reason: str = "",
    index: int = 0,
    path: str | None = None,
    phase_id: str = "phase",
    parent_task_id: str = "",
    linked_phase: str = "",
    linked_graph: str = "",
    source: IRSource | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        task_id=task_id,
        phase_id=phase_id,
        ability_name="component",
        callback_kind="OnStart",
        opcode=opcode,
        coverage_status=coverage,
        execution_mode=execution_mode,
        blocked_reason=blocked_reason,
        parent_task_id=parent_task_id,
        branch="root",
        task_index=index,
        task_path=path or f"OnStart[{index}]",
        effect_id=effect_id or f"effect:{task_id}",
        condition_id="",
        source=source or IRSource("component", "AbilityTask", task_id),
        linked_ability_phase_id=linked_phase,
        linked_standalone_graph_id=linked_graph,
    )


def _entries() -> tuple[tuple[SimpleNamespace, str], ...]:
    return ((SimpleNamespace(phase_id="phase", ability_name="component"), "OnStart"),)


def _invocation(dispatched: tuple[str, ...] = ()) -> _FormalAbilityInvocation:
    target = "child"
    standalone = StandaloneAbilityInvocation(
        "graph",
        "owner",
        (target,),
        "interrupt_queue",
        "entry",
        "intent",
        "resolution",
    )
    return _FormalAbilityInvocation(
        "queue_standalone",
        "owner",
        "graph",
        0,
        TargetResolution(
            requested=(target,),
            legal=(target,),
            selected=(target,),
            primary=target,
            reason="component",
            source="component",
        ),
        standalone=standalone,
        dispatched_event_ids=set(dispatched),
    )


def _system(
    tasks: tuple[SimpleNamespace, ...],
    *,
    dispatch,
    effects: tuple[EffectIR, ...] = (),
) -> AbilityTaskSystem:
    effect_by_id = {effect.effect_id: effect for effect in effects}
    system = AbilityTaskSystem.__new__(AbilityTaskSystem)
    system.rules = SimpleNamespace(
        ability_tasks_for_phase=lambda _phase_id: tasks,
        ability_phase=lambda phase_id: SimpleNamespace(
            phase_id=phase_id, ability_name="component"
        ),
        standalone_ability_graph=lambda _graph_id: None,
        effect=lambda effect_id: effect_by_id.get(effect_id),
        # The walker consumes this typed interface; these fixtures are
        # non-damage leaves, so the source has no damage emission.
        damage_emissions_for_task=lambda _task_id: (),
    )
    system.reducer = MutationReducer()
    system.event_dispatcher = SimpleNamespace(dispatch_event=dispatch)
    return system


def _presentation_leaf(
    task_id: str = "leaf:presentation",
    opcode: str = "ShowBattleUI",
) -> tuple[EffectIR, SimpleNamespace]:
    """Build a strict process-only contract in the shape lowering publishes.

    Component input only: the source string names the fixture, not TBGD.
    """
    source = IRSource(
        "component/presentation",
        "AbilityTask",
        task_id,
        {"json_path": "$.AbilityList[0].OnStart[0]"},
    )
    contract = {
        "schema_version": "ability_process_only_source_shape_v1",
        "opcode": opcode,
        "source_fields": ["$type", "Value"],
        "source_field_types": {"$type": "str", "Value": "int"},
        "source_shape_status": "admitted",
        "blocked_reason": "",
    }
    effect = EffectIR(
        f"effect:{task_id}",
        opcode,
        {"process_only_contract": contract},
        source,
        coverage_status="audit_only",
    )
    task = _task(
        task_id,
        opcode=opcode,
        coverage="audit_only",
        execution_mode="process_only",
        effect_id=effect.effect_id,
        source=source,
    )
    return effect, task


def test_listener_failure_rolls_back_the_whole_external_call():
    state = _battle_state()
    tasks = (
        _task("leaf:1", index=0),
        _task("leaf:2", index=1),
        _task("leaf:3", index=2),
    )
    calls: list[str] = []
    dispatch_calls: list[str] = []

    def execute_leaf(current, task, *, invocation, **kwargs):
        calls.append(task.task_id)
        assert task.task_id != "leaf:3", "a failed call must not run later roots"
        invocation.dispatched_event_ids.add(f"candidate:{task.task_id}")
        if task.task_id == "leaf:1":
            mutation = Mutation(
                "set", ("units", "child", "hp"), 100.0, 60.0, "leaf one", "component"
            )
            event = GameEvent(
                "component.leaf.one",
                source_id="owner",
                target_id="child",
                event_id="event:leaf-one",
            )
            rng = RNGEvent("component", "leaf:1", 1, event_id="rng:leaf-one")
        else:
            mutation = Mutation(
                "set", ("units", "child", "hp"), 60.0, 0.0, "leaf two", "component"
            )
            event = GameEvent(
                "component.leaf.two",
                source_id="owner",
                target_id="child",
                event_id="event:leaf-two",
            )
            rng = RNGEvent("component", "leaf:2", 2, event_id="rng:leaf-two")
        return current, [mutation], [event], [rng], [_task_process_record(task, ok=True)]

    def dispatch(current, *, event, **kwargs):
        dispatch_calls.append(event.event_id)
        if event.event_id == "event:leaf-one":
            return EventDispatchResult(
                after_state=current,
                events=(event,),
                dispatched_event_ids=frozenset({event.event_id}),
            )
        assert event.event_id == "event:leaf-two"
        return EventDispatchResult(
            after_state=current,
            mutations=(
                Mutation(
                    "set",
                    ("units", "child", "hp"),
                    60.0,
                    0.0,
                    "listener candidate",
                    "component",
                ),
            ),
            rng_events=(
                RNGEvent("component", "listener", 2, event_id="rng:listener"),
            ),
            errors=("queue_action_actor_unit_defeated:child",),
        )

    system = _system(tasks, dispatch=dispatch)
    system._execute_effect_leaf_task = execute_leaf
    invocation = _invocation(dispatched=("event:preserved",))
    result = system._execute_external_legacy_standalone_entries(
        state, entries=_entries(), invocation=invocation
    )

    assert calls == ["leaf:1", "leaf:2"]
    assert dispatch_calls == ["event:leaf-one", "event:leaf-two"]
    # The first leaf really succeeded, but the blocked call publishes nothing.
    assert state.units["child"].hp == 100.0
    assert result.after_state == state
    assert result.mutations == ()
    assert result.events == ()
    assert result.rng_events == ()
    assert not result.dispatched_event_ids
    assert invocation.dispatched_event_ids == {"event:preserved"}
    assert len(result.node_results) == 1
    node = result.node_results[0]
    assert node.status == "blocked"
    assert "external_legacy_task_blocked" in node.reason_code
    assert (
        "ability_task_listener_blocked:queue_action_actor_unit_defeated:child"
        in node.reason_code
    )
    assert len(result.records) == 1
    blocked_record = result.records[0]
    assert blocked_record["record_type"] == "standalone_ability_blocked"
    assert blocked_record["payload"]["reason"] == node.reason_code


def test_successful_external_call_commits_each_event_once_in_order():
    state = _battle_state()
    tasks = (_task("leaf:1", index=0), _task("leaf:2", index=1))
    calls: list[str] = []
    dispatch_calls: list[str] = []

    def execute_leaf(current, task, *, invocation, **kwargs):
        calls.append(task.task_id)
        invocation.dispatched_event_ids.add(f"candidate:{task.task_id}")
        if task.task_id == "leaf:1":
            mutation = Mutation(
                "set", ("units", "child", "hp"), 100.0, 60.0, "leaf one", "component"
            )
            event = GameEvent(
                "component.leaf.one",
                source_id="owner",
                target_id="child",
                event_id="event:leaf-one",
            )
            rng = RNGEvent("component", "leaf:1", 1, event_id="rng:leaf-one")
        else:
            mutation = Mutation(
                "set", ("units", "child", "hp"), 60.0, 20.0, "leaf two", "component"
            )
            event = GameEvent(
                "component.leaf.two",
                source_id="owner",
                target_id="child",
                event_id="event:leaf-two",
            )
            rng = RNGEvent("component", "leaf:2", 2, event_id="rng:leaf-two")
        return current, [mutation], [event], [rng], [_task_process_record(task, ok=True)]

    def dispatch(current, *, event, **kwargs):
        dispatch_calls.append(event.event_id)
        return EventDispatchResult(
            after_state=current,
            events=(event,),
            dispatched_event_ids=frozenset({event.event_id}),
        )

    system = _system(tasks, dispatch=dispatch)
    system._execute_effect_leaf_task = execute_leaf
    invocation = _invocation(dispatched=("event:preserved",))
    result = system._execute_external_legacy_standalone_entries(
        state, entries=_entries(), invocation=invocation
    )

    assert calls == ["leaf:1", "leaf:2"]
    assert dispatch_calls == ["event:leaf-one", "event:leaf-two"]
    assert result.after_state.units["child"].hp == 20.0
    assert [mutation.reason for mutation in result.mutations] == ["leaf one", "leaf two"]
    assert [event.event_id for event in result.events] == [
        "event:leaf-one",
        "event:leaf-two",
    ]
    assert [event.event_id for event in result.rng_events] == [
        "rng:leaf-one",
        "rng:leaf-two",
    ]
    assert [node.status for node in result.node_results] == ["complete", "complete"]
    assert [node.node_id for node in result.node_results] == ["leaf:1", "leaf:2"]
    assert result.dispatched_event_ids == frozenset(
        {
            "event:preserved",
            "candidate:leaf:1",
            "candidate:leaf:2",
            "event:leaf-one",
            "event:leaf-two",
        }
    )
    assert invocation.dispatched_event_ids == set(result.dispatched_event_ids)


# ---------------------------------------------------------------------------
# Process-only proof and blocked-task admission.
# ---------------------------------------------------------------------------


def test_blocked_or_missing_trigger_links_are_not_presentation():
    blocked_leaf = _task(
        "blocked-leaf",
        coverage="blocked",
        blocked_reason="force_kill_death_semantics_not_admitted",
    )
    blocked_phase = SimpleNamespace(phase_id="phase:child", ability_name="child")
    trigger = _task("trigger", opcode="TriggerAbility", linked_phase="phase:child")

    linked_rules = SimpleNamespace(
        standalone_ability_graph=lambda _graph_id: None,
        ability_phase=lambda phase_id: (
            blocked_phase if phase_id == "phase:child" else None
        ),
        ability_tasks_for_phase=lambda _phase_id: (blocked_leaf,),
    )
    assert _external_legacy_trigger_is_process_only(linked_rules, trigger) is False

    empty_rules = SimpleNamespace(
        standalone_ability_graph=lambda _graph_id: None,
        ability_phase=lambda phase_id: (
            blocked_phase if phase_id == "phase:child" else None
        ),
        ability_tasks_for_phase=lambda _phase_id: (),
    )
    assert _external_legacy_trigger_is_process_only(empty_rules, trigger) is False

    missing_rules = SimpleNamespace(
        standalone_ability_graph=lambda _graph_id: None,
        ability_phase=lambda _phase_id: None,
        ability_tasks_for_phase=lambda _phase_id: (),
    )
    assert _external_legacy_trigger_is_process_only(missing_rules, trigger) is False

    unknown_leaf = _task(
        "unknown-leaf", coverage="discovered_only", blocked_reason=""
    )
    unknown_rules = SimpleNamespace(
        standalone_ability_graph=lambda _graph_id: None,
        ability_phase=lambda phase_id: (
            blocked_phase if phase_id == "phase:child" else None
        ),
        ability_tasks_for_phase=lambda _phase_id: (unknown_leaf,),
    )
    assert _external_legacy_trigger_is_process_only(unknown_rules, trigger) is False


def test_trigger_presentation_requires_the_strict_process_only_contract():
    effect, request = _presentation_leaf()
    phase = SimpleNamespace(phase_id="phase:child", ability_name="child")
    trigger = _task("trigger", opcode="TriggerAbility", linked_phase="phase:child")
    rules = SimpleNamespace(
        standalone_ability_graph=lambda _graph_id: None,
        ability_phase=lambda phase_id: phase if phase_id == "phase:child" else None,
        ability_tasks_for_phase=lambda _phase_id: (request,),
        effect=lambda effect_id: effect if effect_id == effect.effect_id else None,
    )
    assert _external_legacy_trigger_is_process_only(rules, trigger) is True

    contract = effect.payload["process_only_contract"]
    blocked_effect = EffectIR(
        effect.effect_id,
        effect.opcode,
        {
            "process_only_contract": {
                **contract,
                "source_shape_status": "blocked",
                "blocked_reason": "unknown_nested_gameplay",
            }
        },
        effect.source,
        coverage_status="audit_only",
    )
    blocked_rules = SimpleNamespace(
        standalone_ability_graph=lambda _graph_id: None,
        ability_phase=lambda phase_id: phase if phase_id == "phase:child" else None,
        ability_tasks_for_phase=lambda _phase_id: (request,),
        effect=lambda _effect_id: blocked_effect,
    )
    assert _external_legacy_trigger_is_process_only(blocked_rules, trigger) is False


def test_false_predicate_takes_the_failed_branch_instead_of_blocking():
    state = _battle_state()
    root = _task("predicate", opcode="PredicateTaskList", index=0)
    child = _task(
        "failed-leaf",
        index=1,
        parent_task_id="predicate",
        path="OnStart[0].FailedTaskList[0]",
    )
    child.branch = "failed"
    calls: list[str] = []

    def execute_leaf(current, task, *, invocation, **kwargs):
        calls.append(task.task_id)
        return current, [], [], [], [_task_process_record(task, ok=True)]

    system = _system(
        (root, child),
        dispatch=lambda *_args, **_kwargs: pytest.fail("no event should dispatch"),
    )
    system._evaluate_formal_ability_condition = lambda *_args, **_kwargs: (
        False,
        "",
        {},
    )
    system._execute_effect_leaf_task = execute_leaf
    result = system._execute_external_legacy_standalone_entries(
        state, entries=_entries(), invocation=_invocation()
    )

    assert calls == ["failed-leaf"]
    assert result.after_state == state
    assert result.mutations == () and result.events == () and result.rng_events == ()
    assert [node.node_id for node in result.node_results] == ["failed-leaf"]
    assert result.node_results[0].status == "complete"


def test_undecidable_predicate_blocks_instead_of_selecting_a_branch():
    state = _battle_state()
    root = _task("predicate", opcode="PredicateTaskList", index=0)
    system = _system(
        (root,),
        dispatch=lambda *_args, **_kwargs: pytest.fail("no event should dispatch"),
    )
    system._evaluate_formal_ability_condition = lambda *_args, **_kwargs: (
        None,
        "missing_predicate_condition",
        {},
    )
    system._execute_effect_leaf_task = lambda *_args, **_kwargs: pytest.fail(
        "an undecidable predicate must not execute a branch"
    )
    result = system._execute_external_legacy_standalone_entries(
        state, entries=_entries(), invocation=_invocation()
    )

    assert result.after_state == state
    assert result.mutations == () and result.events == () and result.rng_events == ()
    assert result.node_results[0].status == "blocked"
    assert (
        result.node_results[0].reason_code
        == "external_legacy_predicate_blocked:missing_predicate_condition"
    )


def test_blocked_non_blacklisted_leaf_blocks_instead_of_skipping():
    state = _battle_state()
    task = _task(
        "leaf:blocked",
        opcode="DamageByAttackProperty",
        coverage="blocked",
        blocked_reason="damage_source_shape_not_admitted",
    )
    system = _system(
        (task,),
        dispatch=lambda *_args, **_kwargs: pytest.fail("no dispatch may run"),
    )
    system._execute_effect_leaf_task = lambda *_args, **_kwargs: pytest.fail(
        "a blocked task must not reach the effect leaf"
    )
    invocation = _invocation()
    result = system._execute_external_legacy_standalone_entries(
        state, entries=_entries(), invocation=invocation
    )

    assert result.after_state == state
    assert result.mutations == () and result.events == () and result.rng_events == ()
    assert len(result.node_results) == 1
    node = result.node_results[0]
    assert node.status == "blocked"
    assert node.reason_code == (
        "external_legacy_required_task_blocked:DamageByAttackProperty:"
        "OnStart[0]:damage_source_shape_not_admitted"
    )
    assert result.records[0]["record_type"] == "standalone_ability_blocked"


def test_admitted_process_only_leaf_still_completes_as_a_presentation_skip():
    state = _battle_state()
    effect, task = _presentation_leaf()
    system = _system(
        (task,),
        dispatch=lambda *_args, **_kwargs: pytest.fail("no dispatch may run"),
        effects=(effect,),
    )
    system._execute_effect_leaf_task = lambda *_args, **_kwargs: pytest.fail(
        "an admitted process-only leaf must not execute gameplay"
    )
    result = system._execute_external_legacy_standalone_entries(
        state, entries=_entries(), invocation=_invocation()
    )

    assert result.after_state == state
    assert result.mutations == () and result.events == () and result.rng_events == ()
    assert len(result.node_results) == 1
    assert result.node_results[0].node_kind == "external_ability_process_only"
    assert result.node_results[0].status == "complete"
    records = [
        record
        for record in result.records
        if record.get("record_type") == "ability_task"
    ]
    assert len(records) == 1
    assert records[0]["payload"]["blocked_reason"].startswith(
        "external_legacy_non_gameplay_task_skipped"
    )


def test_broken_process_only_contract_blocks_the_external_call():
    state = _battle_state()
    effect, task = _presentation_leaf()
    contract = effect.payload["process_only_contract"]
    blocked_effect = EffectIR(
        effect.effect_id,
        effect.opcode,
        {
            "process_only_contract": {
                **contract,
                "source_shape_status": "blocked",
                "blocked_reason": "unknown_nested_gameplay",
            }
        },
        effect.source,
        coverage_status="audit_only",
    )
    system = _system(
        (task,),
        dispatch=lambda *_args, **_kwargs: pytest.fail("no dispatch may run"),
        effects=(blocked_effect,),
    )
    system._execute_effect_leaf_task = lambda *_args, **_kwargs: pytest.fail(
        "an unproven process-only leaf must not execute gameplay"
    )
    result = system._execute_external_legacy_standalone_entries(
        state, entries=_entries(), invocation=_invocation()
    )

    assert result.after_state == state
    assert result.mutations == () and result.events == () and result.rng_events == ()
    node = result.node_results[0]
    assert node.status == "blocked"
    assert node.reason_code.startswith(
        "external_legacy_process_only_task_not_admitted:ShowBattleUI:"
    )


def test_listener_failure_is_not_a_gameplay_terminal_cancel():
    state = _battle_state()
    reason = (
        "queue_standalone_ability_not_successor:"
        "external_legacy_task_blocked:ForceKill:OnStart[1]:"
        "ability_task_listener_blocked:queue_action_actor_unit_defeated:child"
    )
    plan = QueueDrainPlan(
        ok=True,
        status="ready",
        queue_name="interrupt_queue",
        queue_entry={
            "entry_id": "entry",
            "actor_id": "owner",
            "target_ids": ["child"],
        },
        queue_intent_id="intent",
        queue_resolution_id="resolution",
        source_trace={},
    )
    terminal = QueueSystem().plan_terminal_resolution(
        state, plan, blocked_reason=reason
    )

    assert terminal.ok is False
    assert terminal.disposition == "blocked"
    assert terminal.retained is True
    assert terminal.blocked_reason == reason


# ---------------------------------------------------------------------------
# TargetEntity dynamic-value scope.
# ---------------------------------------------------------------------------


def _dynamic_condition(
    *,
    scope: str = "TargetEntity",
    target_alias: str | None = "AbilityTargetEntity",
    compare: float = 1.0,
) -> ConditionIR:
    payload: dict[str, object] = {
        "DynamicKey": {"Value": "Counter"},
        "ContextScope": scope,
        "CompareType": "Equal",
        "CompareValue": {"kind": "fixed", "value": compare},
    }
    if target_alias is not None:
        payload["TargetType"] = {"alias": target_alias}
    return ConditionIR(
        "component:target-scope",
        "ByCompareDynamicValue",
        payload,
        IRSource("component", "ByCompareDynamicValue", "component:condition"),
        "executable",
        expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA,
    )


def _dynamic_state(
    *,
    target_value: float | None = None,
    owner_value: float | None = None,
    extra_enemy: bool = False,
) -> BattleState:
    units = {
        "owner": UnitState(
            "owner", "ally", "avatar:component", hp=100.0, max_hp=100.0
        ),
        "target": UnitState(
            "target", "enemy", "monster:component", hp=100.0, max_hp=100.0
        ),
    }
    if extra_enemy:
        units["enemy2"] = UnitState(
            "enemy2", "enemy", "monster:component", hp=100.0, max_hp=100.0
        )
    entries: dict[str, object] = {}

    def add(unit_id: str, value: float) -> None:
        entries[f"entry:{unit_id}"] = {
            "name": "Counter",
            "scope": "unit",
            "lifecycle": "combat",
            "owner_id": unit_id,
            "target_id": unit_id,
            "value": value,
        }

    if target_value is not None:
        add("target", target_value)
    if owner_value is not None:
        add("owner", owner_value)
    return BattleState(
        units=units,
        global_flags={"dynamic_value_store": {"entries": entries}},
    )


def _dynamic_context(
    state: BattleState,
    *,
    ambient: dict[str, float] | None = None,
    target_id: str | None = "target",
    errors: dict[str, str] | None = None,
    groups: dict[str, tuple[str, ...]] | None = None,
) -> EvaluationContext:
    return EvaluationContext(
        state=state,
        actor_id="owner",
        owner_id="owner",
        target_id=target_id,
        current_action_target_id=target_id,
        dynamic_values=ambient,
        target_resolution_errors=errors or {},
        resolved_target_groups=groups or {},
        committed_condition_provider=CommittedConditionFactProvider(None),
    )


def test_target_entity_reads_only_the_formal_target_unit_value():
    state = _dynamic_state(target_value=1.0, owner_value=3.0)
    result = RuleEvaluator().evaluate_condition_result(
        _dynamic_condition(compare=1.0),
        _dynamic_context(state, ambient={"Counter": 3.0}),
    )

    assert result.ok, result.to_json()
    assert result.result is True
    assert result.details["actual"] == 1.0


def test_target_entity_missing_value_never_falls_back_to_owner_or_ambient():
    state = _dynamic_state(owner_value=1.0)
    result = RuleEvaluator().evaluate_condition_result(
        _dynamic_condition(compare=1.0),
        _dynamic_context(state, ambient={"Counter": 1.0}),
    )

    assert result.ok is False
    assert result.result is None
    assert "unit_dynamic_value_missing:Counter" in result.reason


def test_target_entity_omitted_target_keeps_the_formal_owner_default():
    state = _dynamic_state(owner_value=1.0)
    result = RuleEvaluator().evaluate_condition_result(
        _dynamic_condition(target_alias=None, compare=1.0),
        _dynamic_context(state, ambient={"Counter": 3.0}),
    )
    assert result.ok, result.to_json()
    assert result.result is True
    assert result.details["actual"] == 1.0

    # The default is a target scope, not a fallback to ambient values.
    missing = RuleEvaluator().evaluate_condition_result(
        _dynamic_condition(target_alias=None, compare=1.0),
        _dynamic_context(_dynamic_state(), ambient={"Counter": 1.0}),
    )
    assert missing.ok is False
    assert "unit_dynamic_value_missing:Counter" in missing.reason


def test_real_monster_summon_counter_keeps_the_omitted_target_default():
    """Real source leaf; no battle construction or full compilation."""
    root = Path(__file__).resolve().parents[4] / "turnbasedgamedata-main"
    relative = (
        "Config/ConfigAbility/Monster/Monster_W1_Soldier03_00_Ability.json"
    )
    document = json.loads((root / relative).read_text(encoding="utf-8"))
    raw = document["AbilityList"][12]["OnStart"][3]["SuccessTaskList"][0][
        "SuccessTaskList"
    ][0]["Predicate"]
    source = IRSource(
        relative,
        "ByCompareDynamicValue",
        "real:summon-counter",
        {
            "json_path": "$.AbilityList[12].OnStart[3].SuccessTaskList[0]"
            ".SuccessTaskList[0].Predicate"
        },
    )
    payload = _typed_condition_payload(
        "ByCompareDynamicValue",
        {key: value for key, value in raw.items() if key != "$type"},
        source=source,
    )
    condition = ConditionIR(
        "real:summon-counter",
        "ByCompareDynamicValue",
        payload,
        source,
        "executable",
        expression_schema_version=CONDITION_EXPRESSION_NODE_SCHEMA,
    )
    entry = {
        "name": "W1_Soldier03_00_SummonCounter",
        "scope": "unit",
        "lifecycle": "combat",
        "owner_id": "soldier",
        "target_id": "soldier",
        "value": 0.0,
    }
    state = BattleState(
        units={
            "soldier": UnitState(
                "soldier", "enemy", "monster:1002040", hp=100.0, max_hp=100.0
            )
        },
        global_flags={"dynamic_value_store": {"entries": {"entry:counter": entry}}},
    )
    result = RuleEvaluator().evaluate_condition_result(
        condition,
        EvaluationContext(
            state=state,
            actor_id="soldier",
            owner_id="soldier",
            target_id="soldier",
            dynamic_values={"W1_Soldier03_00_SummonCounter": 99.0},
            committed_condition_provider=CommittedConditionFactProvider(None),
        ),
    )
    assert result.ok, result.to_json()
    assert result.result is True
    assert result.details["actual"] == 0.0

    missing = BattleState(
        units=state.units,
        global_flags={"dynamic_value_store": {"entries": {}}},
    )
    blocked = RuleEvaluator().evaluate_condition_result(
        condition,
        EvaluationContext(
            state=missing,
            actor_id="soldier",
            owner_id="soldier",
            target_id="soldier",
            dynamic_values={"W1_Soldier03_00_SummonCounter": 0.0},
            committed_condition_provider=CommittedConditionFactProvider(None),
        ),
    )
    assert blocked.ok is False
    assert (
        "unit_dynamic_value_missing:W1_Soldier03_00_SummonCounter"
        in blocked.reason
    )


def test_target_entity_requires_one_formal_target():
    state = _dynamic_state(target_value=1.0, extra_enemy=True)
    result = RuleEvaluator().evaluate_condition_result(
        _dynamic_condition(target_alias="AllEnemy", compare=1.0),
        _dynamic_context(state),
    )
    assert result.ok is False
    assert result.reason == "condition_fact_target_requires_singleton"
    assert set(result.details["target_ids"]) == {"target", "enemy2"}

    failed = RuleEvaluator().evaluate_condition_result(
        _dynamic_condition(compare=1.0),
        _dynamic_context(
            state,
            errors={"alias:AbilityTargetEntity": "target_expression_blocked"},
        ),
    )
    assert failed.ok is False
    assert failed.reason == "condition_fact_target_requires_singleton"
    assert failed.details["reason"] == "target_expression_blocked"


def test_target_entity_unknown_unit_uses_the_operand_boundary():
    state = _dynamic_state(target_value=1.0)
    result = RuleEvaluator().evaluate_condition_result(
        _dynamic_condition(compare=1.0),
        _dynamic_context(state, target_id="missing"),
    )

    assert result.ok is False
    assert result.reason == "condition_fact_subject_missing:missing"


def test_other_dynamic_value_scopes_keep_their_ambient_read():
    state = _dynamic_state()
    result = RuleEvaluator().evaluate_condition_result(
        _dynamic_condition(
            scope="ContextCaster", target_alias=None, compare=3.0
        ),
        _dynamic_context(state, ambient={"Counter": 3.0}),
    )

    assert result.ok, result.to_json()
    assert result.result is True
