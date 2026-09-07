from __future__ import annotations

import argparse
import inspect
import json
import resource
import sys
import time
import types
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping, cast
from unittest.mock import patch

if __package__ in {None, ""}:
    _PACKAGE_ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_PACKAGE_ROOT))
    __package__ = "simulator_v8_clean_core.tools"

from ..core.action_plan import build_action_execution_plan
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, GameEvent, TargetResolution, UnitState
from ..core.reducer import MutationReducer
from ..rules.engine_rule_registry import build_engine_rule_registry
from ..rules.ir import CanonicalIR, build_external_task_topology_dependency_ledger
from ..rules.rulebook import RuleBook
from ..rules.task_graph import TaskGraphIR, TaskGraphQueryResult
from ..systems.action_contract import ActionContractSystem
from ..systems.action_selection import ActionTargetSelectionSystem
from ..systems.ability import (
    AbilityTaskSystem,
    StatusNestedAbilityContext,
    StatusNestedAbilityHookProvider,
)
from ..systems.event_dispatch import EventDispatchSystem, _event_aliases
from ..systems.status import StatusSystem, status_control_gate_for_actor
from ..systems.status_callbacks import StatusCallbackExecutionResult
from ..systems.task_graph import (
    TaskGraphBranchResult,
    TaskGraphConditionResult,
    TaskGraphContinuation,
    TaskGraphCountResult,
    TaskGraphExecutionHooks,
    TaskGraphGraphResult,
    TaskGraphHookRequest,
    TaskGraphLeafResult,
    TaskGraphTargetResult,
    TaskGraphWeightedSelectionResult,
)
from ..tbgd.lowering import TBGDLowering, _lower_status_event_families
from ..tbgd.task_graph_materializer import materialize_character_runtime_task_graph_catalog
from .validate_p9_formal_action_graph_admission_authority import (
    _accepted_context as _a1_accepted_context,
    _run_fast as _run_a1_fast,
)
from .validate_p9_s8b5c_cross_entry_runtime_transport import (
    _Dispatcher as _B5Dispatcher,
    _Rules as _B5Rules,
    _StatusCallbacks as _B5StatusCallbacks,
    _graph as _b5_graph,
    _install_ability as _b5_install_ability,
    _install_callback as _b5_install_callback,
)
from .validate_p9_s8c1c_remaining_entry_random_config_source_closure import (
    _build_real_context as _s8c1c_build_real_context,
    _dedupe as _s8c1c_dedupe,
    _fixture as _random_fixture,
)

ROOT = Path(__file__).resolve().parents[4]
TBGD_ROOT = ROOT / "turnbasedgamedata-main"
DEFERRED_REASON = "ability_task_weighted_selection_caller_deferred_to_pr9"
_FAST_HARD_SECONDS = 30.0
_FAST_RSS_LIMIT_KIB = 512 * 1024
_DIRECT_HARD_SECONDS = 120.0
_DIRECT_RSS_LIMIT_KIB = int(1.5 * 1024 * 1024)


def _state(detail: Mapping[str, Any] | None = None) -> BattleState:
    owner_flags: dict[str, Any] = {}
    if detail is not None:
        owner_flags["status_details"] = [dict(detail)]
    return BattleState(
        units={
            "owner": UnitState(
                unit_id="owner",
                side="ally",
                template_id="fixture:owner",
                max_hp=100.0,
                hp=100.0,
                flags=owner_flags,
            ),
            "outer": UnitState(
                unit_id="outer",
                side="ally",
                template_id="fixture:outer",
                max_hp=100.0,
                hp=100.0,
            ),
            "target": UnitState(
                unit_id="target",
                side="enemy",
                template_id="fixture:target",
                max_hp=100.0,
                hp=100.0,
            ),
        },
        global_flags={
            "turn_owner_id": "outer",
            "current_window": "idle",
            "phase": "combat",
        },
    )


def _target_resolution(*targets: str) -> TargetResolution:
    values = tuple(targets)
    return TargetResolution(
        requested=values,
        selectable=values,
        legal=values,
        primary=values[0] if values else None,
        impact_group=values,
        selected=values,
        reason="a2_validation",
        source="p9_a2_validator",
    )


def _install_formal_query(rules: _B5Rules) -> None:
    def query_formal_task_graph(
        self: _B5Rules,
        entry_kind: str,
        owner_id: str,
        callback_kind: str,
        formal_task_ids: Iterable[str],
    ) -> TaskGraphQueryResult:
        expected = tuple(formal_task_ids)
        entry_result = self.query_task_graph_entry(entry_kind, owner_id, callback_kind)
        entry = entry_result.value
        if entry_result.status != "resolved" or entry is None:
            return TaskGraphQueryResult(
                "blocked",
                "graph",
                (),
                None,
                entry_result.blocked_reason or "fixture_formal_entry_missing",
            )
        graph_result = self.query_task_graph(entry.graph_id)
        graph = graph_result.value
        if graph_result.status != "resolved" or type(graph) is not TaskGraphIR:
            return graph_result
        if tuple(graph.root_formal_task_ids) != expected:
            return TaskGraphQueryResult(
                "blocked",
                "graph",
                (graph.graph_id,),
                None,
                "fixture_formal_root_task_identity_mismatch",
            )
        return graph_result

    rules.query_formal_task_graph = types.MethodType(query_formal_task_graph, rules)  # type: ignore[attr-defined]


def _request(
    graph: TaskGraphIR,
    root_graph_id: str,
    *,
    target_ids: tuple[str, ...] = ("target",),
) -> TaskGraphHookRequest:
    node = graph.nodes[0]
    return TaskGraphHookRequest(
        invocation_id="a2:fixture:child",
        graph_id=graph.graph_id,
        graph_node_id=node.graph_node_id,
        formal_task_id=node.formal_task_id,
        opcode=node.opcode,
        source_family=node.source_family,
        references=node.references,
        context_values={"outer_action_actor_id": "outer"},
        active_graph_stack=(root_graph_id, graph.graph_id),
        frame_ids=("frame:root", "frame:child"),
        target_ids=target_ids,
        iteration_index=None,
    )


def _single_graph_request(
    graph: TaskGraphIR,
    identity: str,
    *,
    target_ids: tuple[str, ...] = ("target",),
) -> TaskGraphHookRequest:
    node = graph.nodes[0]
    return TaskGraphHookRequest(
        invocation_id=identity,
        graph_id=graph.graph_id,
        graph_node_id=node.graph_node_id,
        formal_task_id=node.formal_task_id,
        opcode=node.opcode,
        source_family=node.source_family,
        references=node.references,
        context_values={"outer_action_actor_id": "outer"},
        active_graph_stack=(graph.graph_id,),
        frame_ids=(f"frame:{identity}",),
        target_ids=target_ids,
        iteration_index=None,
    )


def _fast_component_matrix() -> tuple[dict[str, bool], dict[str, Any]]:
    rules = _B5Rules()
    _install_formal_query(rules)
    child_graph = _b5_install_ability(rules, "A")
    callback, detail, root_graph = _b5_install_callback(
        rules, "C", child_graph.owner_id
    )
    assert root_graph is not None
    state = _state(detail)
    target_resolution = _target_resolution("target", "outer")

    ability = object.__new__(AbilityTaskSystem)
    ability.rules = cast(Any, rules)
    provider = ability.formal_status_nested_ability_provider()
    context = StatusNestedAbilityContext(
        callback_id=callback.callback_id,
        modifier_name=callback.modifier_name,
        status_instance_id=str(detail["instance_id"]),
        owner_id="owner",
        root_graph_id=root_graph.graph_id,
        trigger_event_id="event:a2:action-window",
        target_resolution=target_resolution,
    )
    hooks = provider.hooks_for(context)
    child_request = _request(child_graph, root_graph.graph_id)

    invocation, invocation_reason = ability._status_nested_invocation_for_request(
        context, child_request, state
    )
    if invocation is None or invocation_reason:
        raise AssertionError(f"valid status nested request blocked:{invocation_reason}")

    _, weighted_selection = _random_fixture("status_callback")
    rng_guard = AssertionError("A2 weighted deferred hook attempted random draw")
    before_snapshot = state.snapshot().to_json()
    with patch("random.random", side_effect=rng_guard):
        weighted_result = cast(Any, hooks.weighted_selection)(
            child_request,
            weighted_selection,
            state,
        )
    after_snapshot = state.snapshot().to_json()

    bad_stack = replace(
        child_request,
        active_graph_stack=(child_graph.graph_id,),
    )
    bad_stack_invocation, bad_stack_reason = ability._status_nested_invocation_for_request(
        context, bad_stack, state
    )
    bad_task = replace(child_request, formal_task_id="ability_task:wrong")
    bad_task_invocation, bad_task_reason = ability._status_nested_invocation_for_request(
        context, bad_task, state
    )
    bad_status_graph, bad_status_entry = _b5_graph(
        "status_callback",
        "callback:bad-child",
        callback.event,
        "status_task:bad-child",
        "TriggerAbility",
    )
    rules.add_graph(bad_status_graph, bad_status_entry)
    bad_entry_request = _request(bad_status_graph, root_graph.graph_id)
    bad_entry_invocation, bad_entry_reason = ability._status_nested_invocation_for_request(
        context, bad_entry_request, state
    )
    status_request = _request(root_graph, "graph:fixture:status-parent")
    missing_status_invocation, missing_status_reason = ability._status_nested_invocation_for_request(
        context,
        child_request,
        _state(),
    )

    root_task = rules.status_callback_tasks_for_callback(callback.callback_id)[0]
    duplicate_task = replace(root_task, task_id=f"{root_task.task_id}:duplicate")
    rules.status_tasks[duplicate_task.task_id] = duplicate_task
    ambiguous_invocation, ambiguous_reason = ability._status_nested_invocation_for_request(
        context, child_request, state
    )
    del rules.status_tasks[duplicate_task.task_id]
    saved_task = rules.status_tasks.pop(root_task.task_id)
    missing_link_invocation, missing_link_reason = ability._status_nested_invocation_for_request(
        context, child_request, state
    )
    rules.status_tasks[root_task.task_id] = saved_task

    seen_channels: list[str] = []
    sentinel_hooks = TaskGraphExecutionHooks(
        leaf=lambda _request, _state: (
            seen_channels.append("leaf")
            or TaskGraphLeafResult("resolved")
        ),
        condition=lambda _request, _state: (
            seen_channels.append("condition")
            or TaskGraphConditionResult("resolved", value=True)
        ),
        branch=lambda _request, _state: (
            seen_channels.append("branch")
            or TaskGraphBranchResult("resolved", branch_kind="sentinel", label="ok")
        ),
        count=lambda _request, _definition, _state: (
            seen_channels.append("count")
            or TaskGraphCountResult("resolved", count=1)
        ),
        targets=lambda _request, _state: (
            seen_channels.append("targets")
            or TaskGraphTargetResult("resolved", target_ids=("target",))
        ),
        graph=lambda _request, _state: (
            seen_channels.append("graph")
            or TaskGraphGraphResult("blocked", blocked_reason="sentinel:graph")
        ),
        weighted_selection=lambda _request, _selection, _state: (
            seen_channels.append("weighted_selection")
            or TaskGraphWeightedSelectionResult(
                "blocked", blocked_reason="sentinel:weighted_selection"
            )
        ),
    )
    status_callbacks = _B5StatusCallbacks(rules)
    routed = status_callbacks._formal_status_hooks(
        callback,
        dict(detail),
        GameEvent(
            "action.window.after_attack",
            source_id="outer",
            target_id="target",
            event_id="event:a2:route",
            window="action.window.after_attack",
            payload={"selected_target_ids": ["target"]},
        ),
        None,
        sentinel_hooks,
    )
    cast(Any, routed.leaf)(child_request, state)
    cast(Any, routed.condition)(child_request, state)
    cast(Any, routed.branch)(child_request, state)
    cast(Any, routed.count)(child_request, cast(Any, object()), state)
    cast(Any, routed.targets)(child_request, state)
    cast(Any, routed.graph)(child_request, state)
    cast(Any, routed.weighted_selection)(child_request, weighted_selection, state)
    seven_channel_seen = tuple(seen_channels)

    before_status_route = len(seen_channels)
    status_weighted = cast(Any, routed.weighted_selection)(
        status_request, weighted_selection, state
    )
    status_graph_did_not_escape = len(seen_channels) == before_status_route

    callback_e, detail_e, _ = _b5_install_callback(
        rules,
        "E",
        child_graph.owner_id,
        executable=False,
    )
    generic_details = {
        callback.callback_id: dict(detail),
        callback_e.callback_id: dict(detail_e),
    }
    outer_graph = _b5_install_ability(rules, "OUTER")
    outer_request = _single_graph_request(outer_graph, "a2:s8b5:outer")
    outer_continuation = TaskGraphContinuation.from_hook_request(outer_request)
    generic_seen: list[tuple[str, tuple[str, ...]]] = []
    generic_hooks = TaskGraphExecutionHooks(
        leaf=lambda request, _state: (
            generic_seen.append((request.graph_id, request.active_graph_stack))
            or TaskGraphLeafResult(
                "resolved",
                events=(
                    GameEvent(
                        "fixture.s8b5.child",
                        source_id="owner",
                        target_id="target",
                        event_id="event:a2:s8b5-child",
                    ),
                ),
            )
        )
    )
    generic_dispatcher = _B5Dispatcher(
        rules,
        _B5StatusCallbacks(rules),
        generic_details,
    )
    generic_success = generic_dispatcher.dispatch_event(
        state,
        event=GameEvent(
            "battle.start",
            source_id="outer",
            target_id="target",
            event_id="event:a2:s8b5-success",
            payload={"fixture_callback_ids": [callback.callback_id]},
        ),
        task_graph_continuation=outer_continuation,
        nested_ability_hooks=generic_hooks,
    )
    expected_generic_stack = (
        outer_graph.graph_id,
        root_graph.graph_id,
        child_graph.graph_id,
    )
    generic_pair_transport = any(
        type(item[0]) is TaskGraphContinuation
        and type(item[1]) is TaskGraphExecutionHooks
        and item[0] == outer_continuation
        and item[1] is generic_hooks
        for item in generic_dispatcher.ability_property_watchers.transports
    )
    generic_child_stack_ok = any(
        graph_id == child_graph.graph_id and stack == expected_generic_stack
        for graph_id, stack in generic_seen
    )

    cycle_request = _single_graph_request(child_graph, "a2:s8b5:cycle")
    cycle_dispatcher = _B5Dispatcher(
        rules,
        _B5StatusCallbacks(rules),
        generic_details,
    )
    cycle_result = cycle_dispatcher.dispatch_event(
        state,
        event=GameEvent(
            "battle.start",
            source_id="outer",
            target_id="target",
            event_id="event:a2:s8b5-cycle",
            payload={"fixture_callback_ids": [callback.callback_id]},
        ),
        task_graph_continuation=TaskGraphContinuation.from_hook_request(cycle_request),
        nested_ability_hooks=generic_hooks,
    )
    cycle_has_no_success_projection = not any(
        projection.status == "complete"
        for projection in cycle_result.task_graph_projections
    )

    grouped_dispatcher = _B5Dispatcher(
        rules,
        _B5StatusCallbacks(rules),
        generic_details,
    )
    grouped_failure = grouped_dispatcher.dispatch_event(
        state,
        event=GameEvent(
            "battle.start",
            source_id="outer",
            target_id="target",
            event_id="event:a2:s8b5-group-failure",
            payload={
                "fixture_callback_ids": [callback.callback_id, callback_e.callback_id]
            },
        ),
        task_graph_continuation=outer_continuation,
        nested_ability_hooks=generic_hooks,
    )
    grouped_has_no_success_projection = not any(
        projection.status == "complete"
        for projection in grouped_failure.task_graph_projections
    )
    result_guard = False
    if generic_success.task_graph_projections:
        try:
            StatusCallbackExecutionResult(
                False,
                state,
                errors=("blocked",),
                task_graph_projections=(generic_success.task_graph_projections[0],),
            )
        except ValueError:
            result_guard = True

    wrong_provider_dispatcher = _B5Dispatcher(
        rules,
        _B5StatusCallbacks(rules),
        generic_details,
    )
    wrong_provider = wrong_provider_dispatcher.dispatch_action_window_listeners(
        state,
        event=GameEvent(
            "action.window.after_attack",
            source_id="outer",
            target_id="target",
            event_id="event:a2:wrong-provider",
            window="action.window.after_attack",
            payload={
                "fixture_callback_ids": [callback.callback_id],
                "selected_target_ids": ["target"],
                "primary_target_id": "target",
            },
        ),
        damage_window_ledger=None,
        nested_ability_provider=cast(Any, object()),
    )

    ordinary_dispatcher = _B5Dispatcher(
        rules,
        _B5StatusCallbacks(rules),
        generic_details,
    )
    ordinary = ordinary_dispatcher.dispatch_event(
        state,
        event=GameEvent(
            "battle.start",
            source_id="outer",
            target_id="target",
            event_id="event:a2:ordinary",
            window="battle.start",
            payload={"fixture_callback_ids": [callback.callback_id]},
        ),
    )

    class _RootProbe(_B5StatusCallbacks):
        def __init__(self, fixture_rules: _B5Rules) -> None:
            super().__init__(fixture_rules)
            self.captured: tuple[object, object] | None = None

        def _execute_callback(
            self,
            current_state: BattleState,
            selected_callback: Any,
            selected_detail: dict[str, Any],
            trigger_event: GameEvent | None,
            damage_window_ledger: Any,
            task_graph_continuation: Any,
            nested_ability_hooks: Any,
        ) -> StatusCallbackExecutionResult:
            del selected_callback, selected_detail, trigger_event, damage_window_ledger
            self.captured = (task_graph_continuation, nested_ability_hooks)
            return StatusCallbackExecutionResult(ok=True, after_state=current_state)

    root_probe = _RootProbe(rules)
    root_dispatcher = _B5Dispatcher(
        rules,
        root_probe,
        generic_details,
    )
    root_dispatch = root_dispatcher.dispatch_action_window_listeners(
        state,
        event=GameEvent(
            "action.window.after_attack",
            source_id="outer",
            target_id="target",
            event_id="event:a2:root-probe",
            window="action.window.after_attack",
            payload={
                "fixture_callback_ids": [callback.callback_id],
                "selected_target_ids": ["target", "outer"],
                "primary_target_id": "target",
            },
        ),
        damage_window_ledger=None,
        nested_ability_provider=provider,
    )

    forged_provider_rejected = False
    try:
        StatusNestedAbilityHookProvider(cast(Any, lambda _context: TaskGraphExecutionHooks()))
    except TypeError:
        forged_provider_rejected = True

    continuation_constructor_rejected = False
    try:
        TaskGraphContinuation()
    except TypeError:
        continuation_constructor_rejected = True

    executor_source = inspect.getsource(CombatExecutor.execute)
    public_dispatch_signature = inspect.signature(EventDispatchSystem.dispatch_event)

    predicates = {
        "continuation_constructor_sealed": continuation_constructor_rejected,
        "continuation_factory_unique_in_contract": inspect.getsource(TaskGraphContinuation).count("from_hook_request") == 1,
        "executor_has_explicit_action_window_capability_handoff": (
            "dispatch_action_window_listeners" in executor_source
            and "formal_status_nested_ability_provider" in executor_source
        ),
        "executor_does_not_construct_fake_parent_continuation": "TaskGraphContinuation" not in executor_source,
        "public_dispatch_does_not_expose_formal_root_capability": "status_nested_ability_provider" not in public_dispatch_signature.parameters,
        "forged_provider_rejected": forged_provider_rejected,
        "wrong_provider_type_blocked_before_channels": (
            bool(wrong_provider.errors)
            and "action_window_nested_ability_provider_type_invalid" in wrong_provider.errors
            and not wrong_provider.mutations
            tuple(event.event_id for event in wrong_provider.events)
            == ("event:a2:wrong-provider",)
            and all(event.process_only for event in wrong_provider.events)
            and not wrong_provider.rng_events
            and not wrong_provider.task_graph_projections
            and not wrong_provider_dispatcher.ability_property_watchers.transports
        ),
        "ordinary_listener_has_no_ambient_nested_only_capability": (
            bool(ordinary.errors)
            and not ordinary.mutations
            and not ordinary.events
            and not ordinary.rng_events
            and not ordinary.task_graph_projections
        ),
        "action_window_root_has_no_forged_parent_continuation": (
            not root_dispatch.errors
            and root_probe.captured is not None
            and root_probe.captured[0] is None
            and type(root_probe.captured[1]) is TaskGraphExecutionHooks
        ),
        "request_stack_identity_fail_closed": (
            bad_stack_invocation is None
            and bad_stack_reason == "status_nested_ability_request_stack_mismatch"
        ),
        "request_task_identity_fail_closed": bad_task_invocation is None and bool(bad_task_reason),
        "wrong_child_entry_kind_fail_closed": (
            bad_entry_invocation is None
            and bad_entry_reason == "status_nested_ability_child_graph_identity_mismatch"
        ),
        "missing_status_identity_fail_closed": (
            missing_status_invocation is None
            and missing_status_reason == "status_nested_ability_status_instance_identity_mismatch"
        ),
        "duplicate_typed_root_link_fail_closed": (
            ambiguous_invocation is None
            and ambiguous_reason == "status_nested_ability_root_link_ambiguous"
        ),
        "missing_typed_root_link_fail_closed": (
            missing_link_invocation is None
            and missing_link_reason == "status_nested_ability_root_link_missing"
        ),
        "status_owner_is_nested_actor_not_outer_action_actor": (
            invocation.actor_id == "owner" and invocation.actor_id != "outer"
        ),
        "target_scope_comes_from_hook_request": (
            tuple(invocation.target_resolution.selected) == ("target",)
            and tuple(context.target_resolution.selected) == ("target", "outer")
        ),
        "seven_channels_routed_to_nested_capability": seven_channel_seen == (
            "leaf",
            "condition",
            "branch",
            "count",
            "targets",
            "graph",
            "weighted_selection",
        ),
        "status_graph_ids_remain_status_owned": (
            status_graph_did_not_escape
            and status_weighted.blocked_reason == "status_callback_weighted_selection_not_admitted"
        ),
        "weighted_selection_reaches_ability_owned_deferred_boundary": (
            weighted_result.status == "blocked"
            and weighted_result.blocked_reason == DEFERRED_REASON
        ),
        "weighted_selection_has_zero_rng_and_zero_state_change": (
            weighted_result.rng_event is None and before_snapshot == after_snapshot
        ),
        "s8b5_continuation_pair_regression_pass": (
            not generic_success.errors
            and generic_pair_transport
        ),
        "s8b5_active_stack_regression_pass": (
            not generic_success.errors
            and generic_child_stack_ok
        ),
        "s8b5_cycle_guard_regression_pass": (
            bool(cycle_result.errors)
            and any("task_graph_active_cycle" in item for item in cycle_result.errors)
            and cycle_result.after_state is state
            and not cycle_result.mutations
            and not cycle_result.events
            and not cycle_result.rng_events
            and cycle_has_no_success_projection
        ),
        "s8b5_atomic_rollback_regression_pass": (
            bool(grouped_failure.errors)
            and grouped_failure.after_state is state
            and not grouped_failure.mutations
            and not grouped_failure.events
            and not grouped_failure.rng_events
            and grouped_has_no_success_projection
            and result_guard
        ),
    }
    details = {
        "root_graph_id": root_graph.graph_id,
        "child_graph_id": child_graph.graph_id,
        "callback_id": callback.callback_id,
        "child_actor": invocation.actor_id,
        "child_targets": list(invocation.target_resolution.selected),
        "weighted_reason": weighted_result.blocked_reason,
        "seven_channel_order": list(seven_channel_seen),
        "ordinary_errors": list(ordinary.errors),
        "wrong_provider_errors": list(wrong_provider.errors),
        "negative_reasons": {
            "stack": bad_stack_reason,
            "task": bad_task_reason,
            "entry": bad_entry_reason,
            "status": missing_status_reason,
            "duplicate_link": ambiguous_reason,
            "missing_link": missing_link_reason,
        },
        "s8b5_targeted": {
            "generic_errors": list(generic_success.errors),
            "generic_projection_graph_ids": [
                item.graph_id for item in generic_success.task_graph_projections
            ],
            "generic_seen": [
                {"graph_id": graph_id, "active_graph_stack": list(stack)}
                for graph_id, stack in generic_seen
            ],
            "watcher_transport_count": len(
                generic_dispatcher.ability_property_watchers.transports
            ),
            "cycle_errors": list(cycle_result.errors),
            "cycle_projection_statuses": [
                [item.graph_id, item.status]
                for item in cycle_result.task_graph_projections
            ],
            "grouped_failure_errors": list(grouped_failure.errors),
            "grouped_projection_statuses": [
                [item.graph_id, item.status]
                for item in grouped_failure.task_graph_projections
            ],
            "result_guard": result_guard,
        },
    }
    return predicates, details


def _run_fast() -> dict[str, Any]:
    started = time.perf_counter()
    component_predicates, component_details = _fast_component_matrix()
    a1 = _run_a1_fast()
    predicates = {
        **component_predicates,
        "a1_admission_regression_pass": bool(a1.get("ok")),
    }
    elapsed = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    ok = (
        all(predicates.values())
        and elapsed <= _FAST_HARD_SECONDS
        and peak <= _FAST_RSS_LIMIT_KIB
    )
    return {
        "ok": ok,
        "mode": "fast",
        "predicates": predicates,
        "component": component_details,
        "a1": a1,
        "resource": {
            "wall_seconds": round(elapsed, 6),
            "peak_rss_kib": peak,
            "wall_budget_seconds": _FAST_HARD_SECONDS,
            "rss_budget_kib": _FAST_RSS_LIMIT_KIB,
        },
    }


def _action_window_callback_map(rules: RuleBook) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...]]:
    event_types: set[str] = set()
    for definition in rules.ir.action_definitions:
        action_event = rules.action_event(definition.action_id, definition.level)
        if action_event is None:
            continue
        for step in action_event.phase_steps:
            if step.kind == "trigger_window" and step.canonical_window:
                event_types.add(f"action.window.{step.canonical_window}")
    callback_to_events: dict[str, list[str]] = {}
    for event_type in sorted(event_types):
        event = GameEvent(
            event_type,
            source_id="validation:actor",
            target_id="validation:enemy",
            event_id=f"event:a2:denominator:{event_type}",
            window=event_type,
            payload={
                "selected_target_ids": ["validation:enemy"],
                "target_ids": ["validation:enemy"],
                "primary_target_id": "validation:enemy",
                "primary_action_target_id": "validation:enemy",
                "current_hit_target_id": "validation:enemy",
                "actor_id": "validation:actor",
                "attacker_id": "validation:actor",
            },
        )
        for alias in _event_aliases(event, rules):
            if alias.admission_status != "executable":
                continue
            callback_to_events.setdefault(alias.callback_event, []).append(event_type)
    return (
        {key: tuple(dict.fromkeys(values)) for key, values in callback_to_events.items()},
        tuple(sorted(event_types)),
    )


def _status_denominator(rules: RuleBook) -> tuple[list[dict[str, Any]], dict[str, tuple[str, ...]]]:
    callback_to_events, _ = _action_window_callback_map(rules)
    rows: list[dict[str, Any]] = []
    for callback in rules.ir.status_callbacks:
        if (
            callback.source_mode != "mainline_avatar_ability"
            or callback.coverage_status != "executable"
            or callback.admission_status != "executable"
            or callback.event not in callback_to_events
        ):
            continue
        callback_tasks = tuple(rules.status_callback_tasks_for_callback(callback.callback_id))
        root_query = rules.query_formal_task_graph(
            "status_callback",
            callback.callback_id,
            callback.event,
            (task.task_id for task in callback_tasks),
        )
        root_graph = root_query.value
        if root_query.status != "resolved" or type(root_graph) is not TaskGraphIR:
            continue
        for task in callback_tasks:
            if task.coverage_status != "executable" or task.opcode != "TriggerAbility":
                continue
            phase_ids: tuple[str, ...] = ()
            linked_kind = ""
            linked_id = ""
            if task.linked_ability_phase_id:
                phase_ids = (task.linked_ability_phase_id,)
                linked_kind = "ability_phase"
                linked_id = task.linked_ability_phase_id
            elif task.linked_standalone_graph_id:
                standalone = rules.standalone_ability_graph(task.linked_standalone_graph_id)
                if standalone is None:
                    continue
                phase_ids = standalone.phase_ids
                linked_kind = "standalone"
                linked_id = task.linked_standalone_graph_id
            else:
                continue
            child_candidates: list[tuple[Any, TaskGraphIR]] = []
            for phase_id in phase_ids:
                phase = rules.ability_phase(phase_id)
                if phase is None or phase.invocation_role != "nested_only":
                    continue
                child_tasks = tuple(
                    candidate
                    for candidate in rules.ability_tasks_for_phase(phase_id)
                    if candidate.callback_kind == task.callback_kind
                )
                if not child_tasks:
                    continue
                child_query = rules.query_formal_task_graph(
                    "ability_phase_callback",
                    phase_id,
                    task.callback_kind,
                    (candidate.task_id for candidate in child_tasks),
                )
                child_graph = child_query.value
                if child_query.status == "resolved" and type(child_graph) is TaskGraphIR:
                    child_candidates.append((phase, child_graph))
            if len(child_candidates) != 1:
                continue
            phase, child_graph = child_candidates[0]
            rows.append(
                {
                    "callback_id": callback.callback_id,
                    "modifier_name": callback.modifier_name,
                    "callback_event": callback.event,
                    "callback_source_path": callback.source.source_path,
                    "status_task_id": task.task_id,
                    "status_root_graph_id": root_graph.graph_id,
                    "linked_kind": linked_kind,
                    "linked_id": linked_id,
                    "nested_phase_id": phase.phase_id,
                    "nested_phase_level": phase.level,
                    "nested_callback_kind": task.callback_kind,
                    "nested_graph_id": child_graph.graph_id,
                    "nested_task_ids": list(child_graph.root_formal_task_ids),
                    "weighted_selection_ids": [
                        item.selection_id for item in child_graph.weighted_selections
                    ],
                    "action_window_event_types": list(callback_to_events[callback.event]),
                }
            )
    rows.sort(
        key=lambda row: (
            row["callback_id"],
            row["status_task_id"],
            row["nested_graph_id"],
        )
    )
    return rows, callback_to_events


def _action_windows(rules: RuleBook, definition: Any) -> tuple[str, ...]:
    action_event = rules.action_event(definition.action_id, definition.level)
    if action_event is None:
        return ()
    plan = build_action_execution_plan(
        definition,
        action_event,
        rules.hit_profiles_for_action(definition.action_id, definition.level),
        rules.damage_emissions_for_action(definition.action_id, definition.level),
        rules.toughness_emissions_for_action(definition.action_id, definition.level),
        requested_target_ids=("validation:enemy",),
    )
    return tuple(
        f"action.window.{step.canonical_window}"
        for step in plan.event_steps
        if step.kind == "trigger_window" and step.canonical_window
    )


def _action_candidates_by_window(rules: RuleBook) -> dict[str, list[tuple[Any, Any]]]:
    result: dict[str, list[tuple[Any, Any]]] = {}
    for definition in sorted(
        rules.ir.action_definitions,
        key=lambda item: (item.action_id, item.level, item.definition_id),
    ):
        context = _a1_accepted_context(rules, definition, ())
        if context is None:
            continue
        _state_before, _command, _target_context, _admission, mode, decision = context
        if mode != "external_turn" or not decision.ok:
            continue
        event = rules.action_event(definition.action_id, definition.level)
        if event is None or event.target_mode == "bounce":
            continue
        for event_type in _action_windows(rules, definition):
            bucket = result.setdefault(event_type, []r€Y€[ЉќXЪЩ]
HЋ‚€ќXЪЩ]\[™

Yљ[љ][Ы‹ЫЫќ^
JB€™]\›€™\Э[‚‚™Y€Ь™X[ШYЫ[ЩYљY\—ЩY™™XЭКќ[\О€ќ[P›ЫЪЛ[ЩYљY\—Ы[YN€ЭЉHO€\VР[ћK‹‹—N‚€™\Э[HЧB€›Ь€Y™™XЭ[€ќ[\Лљ\‹™Y™™XЭО‚€Y€Y™™XЭ›ЬЫЩHOHђY[ЩYљY\€Ћ‚€ЫЫќ[ќYB€Э[™\™HY™™XЭњ^[ШY™Щ]
њЭ[™\™ЉB€Y€›Э\Ъ[њЭ[ЩJЭ[™\™X\[™КN‚€ЫЫќ[ќYB€Y€Э[™\™™Щ]
›[ЩYљY\—Ы[YHЉHOH[ЩYљY\—Ы[YN‚€ЫЫќ[ќYB€Y€Щ]]ЉY™™XЭЫЭ™\YЩWЬЭ]\И‹™^XЭ]X›HЉH›Э[€И€‹™^XЭ]X›HџN‚€ЫЫќ[ќYB€™\Э[\[™
Y™™XЭ
B€™]\›€\JЫЬќY
™\Э[Щ^O[[X™H][N€][K™Y™™XЭЪY
JB‚‚™Y€Ш]XЪYШШ[XЪЧЩ]Z[
€Э]N€]TЭ]K€›ЭО€X\[™ЦЬЭ‹[ћWKЉHO€XЭЬЭ‹[ћWH›Ы™N‚€XЭЬ€HЭ]Kќ[љ]Л™Щ]
ќ[Y][ЫЋXЭЬ€ЉB€Y€XЭЬ€\И›Ы™N‚€™]\›€›Ы™B€]Z[ИHXЭЬ‹™›YЬЛ™Щ]
њЭ]\ЧЩ]Z[И‹

JB€Y€›Э\Ъ[њЭ[ЩJ]Z[Л
\Э\JJN‚€™]\›€›Ы™B€X]Ъ\ИHЧB€›Ь€][H[€]Z[О‚€Y€›Э\Ъ[њЭ[ЩJ][KXЭ
N‚€ЫЫќ[ќYB€Y€ЭЉ][K™Щ]
›[ЩYљY\—Ы[YHЉHЬ€€ЉHOH›ЭЦИ›[ЩYљY\—Ы[YH—N‚€ЫЫќ[ќYB€љYЩЩ\—ЪYИH][K™Щ]
ќљYЩЩ\—ЪYЧШћWЩ]™[ќЉB€YИHљYЩЩ\—ЪYЛ™Щ]
›ЭЦИШ[XЪЧЩ]™[ќ—JHY€\Ъ[њЭ[ЩJљYЩЩ\—ЪYЛXЭ
H[ЩH›Ы™B€Y€\Ъ[њЭ[ЩJYЛ\Э
H[™›ЭЦИШ[XЪЧЪY—H[€YО‚€X]Ъ\Л\[™
XЭ
][JJB€™]\›€X]Ъ\ЦМHY€[ЉX]Ъ\КHOHH[ЩH›Ы™B‚‚™Y€Ш]XЪЬ™X[ЬЭ]\К€ќ[\О€ќ[P›ЫЪЛ€\ЩWЬЭ]N€]TЭ]K€›ЭО€X\[™ЦЬЭ‹[ћWKЉHO€\VР]TЭ]KXЭЬЭ‹[ћWKXЭЬЭ‹[ћWWH›Ы™N‚€Ю\Э[HHЭ]\ФЮ\Э[Jќ[\КB€™YXЩ\€H]]][Ы”™YXЩ\Љ
B€Щ]\Ь™\ЫЫ][Ы€H\™Щ]™\ЫЫ][ЫЉ€™\]Y\ЭYJќ[Y][ЫЋXЭЬ€‹
K€Щ[XЭX›OJќ[Y][ЫЋXЭЬ€‹
K€YШ[Jќ[Y][ЫЋXЭЬ€‹
K€љ[X\ћOHќ[Y][ЫЋXЭЬ€‹€[\XЭЩЬ›Э\Jќ[Y][ЫЋXЭЬ€‹
K€Щ[XЭYJќ[Y][ЫЋXЭЬ€‹
K€™X\ЫЫЏHњ›ЩXЭ[Ы—ЬЭ]\ЧЬЩ]\‹€ЫЭ\ЩOHњЭ]\ЧЬЮ\Э[WЬЩ]\Э\™Щ]‹€
B€Z[\™\О€\ЭЩXЭЬЭ‹[ћWWHHЧB€›Ь€Y™™XЭ[€Ь™X[ШYЫ[ЩYљY\—ЩY™™XЭКќ[\ЛЭЉ›ЭЦИ›[ЩYљY\—Ы[YH—JJN‚€›Ь€Ш\Э\—ЪY[€
ќ[Y][ЫЋXЭЬ€‹ќ[Y][ЫЋ™[™[^HЉN‚€™\Э[HЮ\Э[K\WШYЫ[ЩYљY\Љ€\ЩWЬЭ]K€Y™™XЭ€Ш\Э\—ЪYXШ\Э\—ЪY€ЫЭ\ЩWЪYXШ\Э\—ЪY€ЭЫ™\—ЪYHќ[Y][ЫЋXЭЬ€‹€\[WЩ[ќ]WЪYHќ[Y][ЫЋXЭЬ€‹€Э\њ™[ќШXЭ[Ы—Э\™Щ]ЪYHќ[Y][ЫЋXЭЬ€‹€\™Щ]Ь™\ЫЫ][ЫЏ\Щ]\Ь™\ЫЫ][Ы‹€]™[ќЬ^[ШY^В€ќ[Y][Ы—ЬЭYЩHЋ€”KPL€‹€XЭЬ—ЪYЋ€ќ[Y][ЫЋXЭЬ€‹€ќ\™Щ]ЪYЋ€ќ[Y][ЫЋXЭЬ€‹€њЩ[XЭYЭ\™Щ]ЪYИЋ€Иќ[Y][ЫЋXЭЬ€—K€њљ[X\ћWШXЭ[Ы—Э\™Щ]ЪYЋ€ќ[Y][ЫЋXЭЬ€‹€K€љ[™[™ЧЬЫЭ\Щ\ПJ€В€њЫЭ\ЩWЪЪ[™Ћ€њWШL—Щ\™XЭЬЭ]\ЧЬЩ]\‹€™Y™™XЭЪYЋ€Y™™XЭ™Y™™XЭЪY€Ш[XЪЧЪYЋ€ЭЉ›ЭЦИШ[XЪЧЪY—JK€K€
K€
B€Y€›Э™\Э[›ЪО‚€Z[\™\Л\[™
€В€™Y™™XЭЪYЋ€Y™™XЭ™Y™™XЭЪY€Ш\Э\—ЪYЋ€Ш\Э\—ЪY€ќ[њЭ\ЬќYЋ€\Э
™\Э[ќ[њЭ\ЬќY
K€B€
B€ЫЫќ[ќYB€™YXЩYH™YXЩ\‹\WШ[Ь™\Э[
\ЩWЬЭ]K™\Э[›]]][ЫњКB€Y€›Э™YXЩY›ЪО‚€Z[\™\Л\[™
€В€™Y™™XЭЪYЋ€Y™™XЭ™Y™™XЭЪY€Ш\Э\—ЪYЋ€Ш\Э\—ЪY€њ™YXЩ\—ШЫЫ™›XЭИЋ€Ъ][KЫЩH›Ь€][H[€™YXЩYЫЫ™›XЭЧK€B€
B€ЫЫќ[ќYB€]Z[HШ]XЪYШШ[XЪЧЩ]Z[
™YXЩYYќ\—ЬЭ]K›ЭКB€Y€]Z[\И›Ы™N‚€Z[\™\Л\[™
€В€™Y™™XЭЪYЋ€Y™™XЭ™Y™™XЭЪY€Ш\Э\—ЪYЋ€Ш\Э\—ЪY€њ™X\ЫЫ€Ћ€Ш[XЪЧЫ›ЭШ]XЪYЭЧШXЭЬ—ШYќ\—Ь™X[ЬЭ]\ЧШYZ\ЬЪ[Ы€‹€B€
B€ЫЫќ[ќYB€Y€Э]\ЧШЫЫќ›ЫЩШ]WЩ›Ь—ШXЭЬЉ™YXЩYYќ\—ЬЭ]Kќ[љ]ЦИќ[Y][ЫЋXЭЬ€—JH\И›Э›Ы™N‚€Z[\™\Л\[™
€В€™Y™™XЭЪYЋ€Y™™XЭ™Y™™XЭЪY€Ш\Э\—ЪYЋ€Ш\Э\—ЪY€њ™X\ЫЫ€Ћ€]XЪYЬЭ]\ЧШЫЫќ›ЫЧШXЭ[Ы—ШXЭЬ€‹€B€
B€ЫЫќ[ќYB€™]\›€
€™YXЩYYќ\—ЬЭ]K€]Z[€В€™Y™™XЭЪYЋ€Y™™XЭ™Y™™XЭЪY€™Y™™XЭЬЫЭ\ЩWЬ]Ћ€Y™™XЭњЫЭ\ЩKњЫЭ\ЩWЬ]€Ш\Э\—ЪYЋ€Ш\Э\—ЪY€њЩ]\Ы]]][Ы—ШЫЭ[ќЋ€[Љ™\Э[›]]][ЫњКK€њЩ]\Щ]™[ќШЫЭ[ќЋ€[Љ™\Э[™]™[ќКK€њЩ]\Ь›™ЧЩ]™[ќШЫЭ[ќЋ€[Љ™\Э[њ›™ЧЩ]™[ќКK€њЩ]\Ь™XЫЬ™ШЫЭ[ќЋ€[Љ™\Э[њ™XЫЬ™КK€K€
B€™]\›€›Ы™B‚‚™Y€ШXШЩ\YШXЭ[Ы—ЫЫ—ЬЭ]J€ќ[\О€ќ[P›ЫЪЛ€Э]N€]TЭ]K€Yљ[љ][ЫЋ€[ћKЉHO€\VРXЭ[ЫђЫЫ[X[™[ћK[ћWH›Ы™N‚€Щ[XЭЬ€HXЭ[Ы•\™Щ]Щ[XЭ[Ы”Ю\Э[Jќ[\КB€]Y\ћHHЩ[XЭЬ‹њ]Y\ћJ€Э]K€ќ[Y][ЫЋXЭЬ€‹€Yљ[љ][Ы‹XЭ[Ы—ЪY€Yљ[љ][Ы‹›]™[€
B€Y€]Y\ћKњЭ]\ИOHњ™\ЫЫ™YЋ‚€™]\›€›Ы™B€ЭX›Z]YH
€

B€Y€]Y\ћKњЩ[XЭ[Ы—Ы[ЩHOH]]ЫX]XИ‚€[ЩH\J]Y\ћKШ[™Y]WЪYЦО€
]Y\ћKњЩ[XЭ[Ы—ЫZ[€Ь€JWJB€
B€XШЩ\YHЩ[XЭЬ‹XШЩ\
Э]K]Y\ћKЭX›Z]Y
B€Y€XШЩ\YњЭ]\ИOHXШЩ\Y€Ь€XШЩ\YЫЫќ^\И›Ы™N‚€™]\›€›Ы™B€ЫЫ[X[™HXЭ[ЫђЫЫ[X[™
€XЭЬ—ЪYHќ[Y][ЫЋXЭЬ€‹€XЭ[Ы—ЪYYYљ[љ][Ы‹XЭ[Ы—ЪY€XЭ[Ы—Ы]™[YYљ[љ][Ы‹›]™[€\™Щ]ЪYПJ€

B€Y€]Y\ћKњЩ[XЭ[Ы—Ы[ЩHOH]]ЫX]XИ‚€[ЩHXШЩ\YЫЫќ^XШЩ\YњЩ[XЭYЭ\™Щ]ЪYВ€
K€
B€Y€Щ[XЭЬ‹ЫЫќ^Ш›ШЪЩYЬ™X\ЫЫЉЭ]KЫЫ[X[™XШЩ\YЫЫќ^
N‚€™]\›€›Ы™B€XЪ\Ъ[Ы€HXЭ[ЫђЫЫќXЭЮ\Э[Jќ[\КK™][X]J€Э]K€ЫЫ[X[™€ЭX›Z\ЬЪ[Ы—Ы[ЩOH™^\›[Э\›€‹€\™Щ]ЬЩ[XЭ[Ы—Щљ[™Щ\њљ[ќXXШЩ\YЫЫќ^ЫЫќ^Щљ[™Щ\њљ[ќ€
B€Y€›ЭXЪ\Ъ[Ы‹›ЪО‚€™]\›€›Ы™B€™]\›€ЫЫ[X[™XШЩ\YЫЫќ^XЪ\Ъ[Ы‚‚‚™Y€Ш][\Щ\™XЭ
€ќ[\О€ќ[P›ЫЪЛ€›ЭО€X\[™ЦЬЭ‹[ћWK€Yљ[љ][ЫЋ€[ћK€\ЩWШЫЫќ^€[ћK€
‹€^XЭЭЩZYЪY€›ЫЫЉHO€XЭЬЭ‹[ћWN‚€\ЩWЬЭ]HH\ЩWШЫЫќ^МB€]XЪYHШ]XЪЬ™X[ЬЭ]\Кќ[\Л\ЩWЬЭ]K›ЭКB€Y€]XЪY\И›Ы™N‚€™]\›€И›ЪИЋ€[ЩKњЭYЩHЋ€њЭ]\ЧШ]XЪ‹њ™X\ЫЫ€Ћ€њ™X[ЬЭ]\ЧЬ›ЩXЩ\—ЩШ\џB€Э]\ЧЬЭ]K]Z[Щ]\Щ]љY[ЩHH]XЪY€XШЩ\YHШXШЩ\YШXЭ[Ы—ЫЫ—ЬЭ]Jќ[\ЛЭ]\ЧЬЭ]KYљ[љ][ЫЉB€Y€XШЩ\Y\И›Ы™N‚€™]\›€И›ЪИЋ€[ЩKњЭYЩHЋ€XЭ[Ы—Ь™XYZ\ЬЪ[Ы€‹њ™X\ЫЫ€Ћ€XЭ[Ы—Ы›ЭШYZ]YШYќ\—ЬЭ]\ЧЬЩ]\џB€ЫЫ[X[™\™Щ]ШЫЫќ^XЪ\Ъ[Ы€HXШЩ\Y‚€^XЭ]Ь€HЫЫX]^XЭ]ЬЉќ[\КB€Ь™\™Y€\ЭЩXЭЬЭ‹[ћWWHHВ€В€њЭ\Ћ€XЭ[Ы—ШYZ\ЬЪ[Ы—ШXШЩ\Y‹€YZ\ЬЪ[Ы—ЪYЋ€XЪ\Ъ[Ы‹YZ\ЬЪ[Ы‹YZ\ЬЪ[Ы—ЪYY€XЪ\Ъ[Ы‹YZ\ЬЪ[Ы€[ЩH€‹€XЭ[Ы—ЪYЋ€ЫЫ[X[™XЭ[Ы—ЪY€XЭ[Ы—Ы]™[Ћ€ЫЫ[X[™XЭ[Ы—Ы]™[€ќ\™Щ]ЬЩ[XЭ[Ы—Щљ[™Щ\њљ[ќЋ€\™Щ]ШЫЫќ^ЫЫќ^Щљ[™Щ\њљ[ќ€B€B‚€ЬљYЪ[[ЭЪ[™ЭИH^XЭ]Ь‹™]™[ќЩ\Ь]Ъ\‹™\Ь]ЪШXЭ[Ы—ЭЪ[™ЭЧЫ\Э[™\њВ€Y€Ъ[™ЭЧЬ›Ш™JЭ\њ™[ќЬЭ]N€]TЭ]K
ЉљЭШ\™ЬО€[ћJHO€[ћN‚€]™[ќHЭШ\™ЬЦИ™]™[ќ—B€Ь™\™Y\[™
€В€њЭ\Ћ€XЭ[Ы—ЭЪ[™ЭЧЩ]™[ќЩ\Ь]ЪY‹€™]™[ќЭ\HЋ€]™[ќ™]™[ќЭ\K€™]™[ќЪYЋ€]™[ќ™]™[ќЪY€B€
B€™]\›€ЬљYЪ[[ЭЪ[™ЭКЭ\њ™[ќЬЭ]K
ЉљЭШ\™ЬКB€^XЭ]Ь‹™]™[ќЩ\Ь]Ъ\‹™\Ь]ЪШXЭ[Ы—ЭЪ[™ЭЧЫ\Э[™\њИHЪ[™ЭЧЬ›Ш™HИ\N€YЫ›Ь™VЫY]ЩX\ЬЪYЫ—B‚€ЬљYЪ[[Ь›ЫЭH^XЭ]Ь‹™]™[ќЩ\Ь]Ъ\‹њЭ]\ЧШШ[XЪЬЛ™^XЭ]WШXЭ[Ы—ЭЪ[™ЭЧЩ›Ь›X[Ь›ЫЭ€Y€›ЫЭЬ›Ш™JЭ\њ™[ќЬЭ]N€]TЭ]K
ЉљЭШ\™ЬО€[ћJHO€[ћN‚€Ш[XЪЧЪYHЭЉЭШ\™ЬЛ™Щ]
Ш[XЪЧЪYЉHЬ€€ЉB€Y€Ш[XЪЧЪYOH›ЭЦИШ[XЪЧЪY—N‚€ЭЫ™\€HЭ\њ™[ќЬЭ]Kќ[љ]Л™Щ]
ЭЉЭШ\™ЬЛ™Щ]
ќ[љ]ЪYЉHЬ€€ЉJB€™X[Щ]Z[H›Ы™B€Y€ЭЫ™\€\И›Э›Ы™N‚€]Z[ИHЭЫ™\‹™›YЬЛ™Щ]
њЭ]\ЧЩ]Z[И‹

JB€Y€\Ъ[њЭ[ЩJ]Z[Л
\Э\JJN‚€™X[Щ]Z[H™^
€
€][B€›Ь€][H[€]Z[В€Y€\Ъ[њЭ[ЩJ][KXЭ
B€[™ЭЉ][K™Щ]
љ[њЭ[ЩWЪYЉHЬ€€ЉHOHЭЉ]Z[Иљ[њЭ[ЩWЪY—JB€
K€›Ы™K€
B€Ь™\™Y\[™
€В€њЭ\Ћ€њ™X[ЬЭ]\ЧЫ\Э[™\—ЫX]ЪYШ[™Щ›Ь›X[Ь›ЫЭЬЭ\ќY‹€Ш[XЪЧЪYЋ€Ш[XЪЧЪY€њЭ]\ЧЪ[њЭ[ЩWЪYЋ€ЭЉ]Z[Иљ[њЭ[ЩWЪY—JK€њ™X[Щ]Z[Ь™\Щ[ќЋ€™X[Щ]Z[\И›Э›Ы™K€њЭ]\ЧЬ›ЫЭЩЬ\ЪYЋ€ЭЉ›ЭЦИњЭ]\ЧЬ›ЫЭЩЬ\ЪY—JK€B€
B€™]\›€ЬљYЪ[[Ь›ЫЭ
Э\њ™[ќЬЭ]K
ЉљЭШ\™ЬКB€^XЭ]Ь‹™]™[ќЩ\Ь]Ъ\‹њЭ]\ЧШШ[XЪЬЛ™^XЭ]WШXЭ[Ы—ЭЪ[™ЭЧЩ›Ь›X[Ь›ЫЭH›ЫЭЬ›Ш™HИ\N€YЫ›Ь™VЫY]ЩX\ЬЪYЫ—B‚€ЬљYЪ[[Ъ[ќ›ШШ][Ы€H^XЭ]Ь‹Xљ[]WЭ\ЪЬЛ—ЬЭ]\ЧЫ™\ЭYЪ[ќ›ШШ][Ы—Щ›Ь—Ь™\]Y\Э€Y€[ќ›ШШ][Ы—Ь›Ш™J€ЫЫќ^€Э]\У™\ЭYXљ[]PЫЫќ^€™\]Y\Э€\ЪСЬ\ЫЪФ™\]Y\Э€Э\њ™[ќЬЭ]N€]TЭ]K€
HO€[ћN‚€[ќ›ШШ][Ы‹™X\ЫЫ€HЬљYЪ[[Ъ[ќ›ШШ][ЫЉЫЫќ^™\]Y\ЭЭ\њ™[ќЬЭ]JB€Y€™\]Y\Э™Ь\ЪYOH›ЭЦИ›™\ЭYЩЬ\ЪY—N‚€Ь™\™Y\[™
€В€њЭ\Ћ€ќљYЩЩ\—ШXљ[]WЬЩ[XЭYЭ\YЫ™\ЭYЫЫ›WЩЬ\Ш[™Ь™XXЪYШXљ[]WШ]]Ьљ]H‹€њ›ЫЭЩЬ\ЪYЋ€ЫЫќ^њ›ЫЭЩЬ\ЪY€Ъ[ЩЬ\ЪYЋ€™\]Y\Э™Ь\ЪY€Ъ[ЩЬ\Ы›ЩWЪYЋ€™\]Y\Э™Ь\Ы›ЩWЪY€™›Ь›X[Э\ЪЧЪYЋ€™\]Y\Э™›Ь›X[Э\ЪЧЪY€XЭЬ—ЪYЋ€[ќ›ШШ][Ы‹XЭЬ—ЪYY€[ќ›ШШ][Ы€\И›Э›Ы™H[ЩH€‹€ќ\™Щ]ЪYИЋ€\Э
[ќ›ШШ][Ы‹ќ\™Щ]Ь™\ЫЫ][Ы‹њЩ[XЭY
HY€[ќ›ШШ][Ы€\И›Э›Ы™H[ЩHЧK€›ШЪЩYЬ™X\ЫЫ€Ћ€™X\ЫЫ‹€B€
B€™]\›€[ќ›ШШ][Ы‹™X\ЫЫ‚€^XЭ]Ь‹Xљ[]WЭ\ЪЬЛ—ЬЭ]\ЧЫ™\ЭYЪ[ќ›ШШ][Ы—Щ›Ь—Ь™\]Y\ЭH[ќ›ШШ][Ы—Ь›Ш™HИ\N€YЫ›Ь™VЫY]ЩX\ЬЪYЫ—B‚€ЬљYЪ[[ЭЩZYЪYH^XЭ]Ь‹Xљ[]WЭ\ЪЬЛ—Ь™\ЫЫ™WЩ›Ь›X[ЭЩZYЪYЬЩ[XЭ[Ы‚€Y€ЩZYЪYЬ›Ш™J™\]Y\Э€\ЪСЬ\ЫЪФ™\]Y\ЭЩ[XЭ[ЫЋ€[ћKЭ\њ™[ќЬЭ]N€]TЭ]JHO€[ћN‚€™\Э[HЬљYЪ[[ЭЩZYЪY
™\]Y\ЭЩ[XЭ[Ы‹Э\њ™[ќЬЭ]JB€Y€™\]Y\Э™Ь\ЪYOH›ЭЦИ›™\ЭYЩЬ\ЪY—N‚€Ь™\™Y\[™
€В€њЭ\Ћ€ќЩZYЪYЬЩ[XЭ[Ы—Ь™XXЪYШXљ[]WЫЭЫ™YЩY™\њ™YЪЫЪИ‹€њЩ[XЭ[Ы—ЪYЋ€Щ[XЭ[Ы‹њЩ[XЭ[Ы—ЪY€™Ь\Ы›ЩWЪYЋ€™\]Y\Э™Ь\Ы›ЩWЪY€›ШЪЩYЬ™X\ЫЫ€Ћ€™\Э[›ШЪЩYЬ™X\ЫЫ‹€њ›™ЧЩ]™[ќЬ™\Щ[ќЋ€™\Э[њ›™ЧЩ]™[ќ\И›Э›Ы™K€B€
B€™]\›€™\Э[€^XЭ]Ь‹Xљ[]WЭ\ЪЬЛ—Ь™\ЫЫ™WЩ›Ь›X[ЭЩZYЪYЬЩ[XЭ[Ы€HЩZYЪYЬ›Ш™HИ\N€YЫ›Ь™VЫY]ЩX\ЬЪYЫ—B‚€™Y›Ь™HHЭ]\ЧЬЭ]KњЫ\ЪЭ

KќЧЪњЫЫЉ
B€Yќ\—ЬЭ]K[њЪ][Ы€H^XЭ]Ь‹™^XЭ]J€ЫЫ[X[™€Э]\ЧЬЭ]K€\™Щ]ЬЩ[XЭ[Ы—ШЫЫќ^]\™Щ]ШЫЫќ^€
B€Yќ\€HYќ\—ЬЭ]KњЫ\ЪЭ

KќЧЪњЫЫЉ
B€Щ][Y[ќH[њЪ][Ы‹ќ[њШXЭ[Ы‹њЩ][Y[ќ€™XЫЬ™ИH\JЩ][Y[ќњ™XЫЬ™КHY€Щ][Y[ќ\И›Э›Ы™H[ЩH

B€ЭXШЩ\ЬЧЭ\ЪЧЫ›Щ\ИHВ€][B€›Ь€][H[€[њЪ][Ы‹›Э]ЫЫYK››ЩWЬ™\Э[В€Y€][K››ЩWЪЪ[™OHќ\ЪЧЩЬ\Ы›ЩH€[™][KњЭ]\ИOHЫЫ\]H‚€B€Щ[XЭYЭЪ[™ЭИH[ћJ€][K™Щ]
њЭ\ЉHOHXЭ[Ы—ЭЪ[™ЭЧЩ]™[ќЩ\Ь]ЪY‚€[™][K™Щ]
™]™[ќЭ\HЉH[€›ЭЦИXЭ[Ы—ЭЪ[™ЭЧЩ]™[ќЭ\\И—B€›Ь€][H[€Ь™\™Y€
B€™X[Ь›ЫЭH[ћJ€][K™Щ]
њЭ\ЉHOHњ™X[ЬЭ]\ЧЫ\Э[™\—ЫX]ЪYШ[™Щ›Ь›X[Ь›ЫЭЬЭ\ќY‚€[™][K™Щ]
њ™X[Щ]Z[Ь™\Щ[ќЉH\ИќYB€›Ь€][H[€Ь™\™Y€
B€Xљ[]WШ]]Ьљ]HH[ћJ€][K™Щ]
њЭ\ЉHOHќљYЩЩ\—ШXљ[]WЬЩ[XЭYЭ\YЫ™\ЭYЫЫ›WЩЬ\Ш[™Ь™XXЪYШXљ[]WШ]]Ьљ]H‚€[™][K™Щ]
Ъ[ЩЬ\ЪYЉHOH›ЭЦИ›™\ЭYЩЬ\ЪY—B€[™›Э][K™Щ]
›ШЪЩYЬ™X\ЫЫ€ЉB€›Ь€][H[€Ь™\™Y€
B€ЩZYЪYЪ]ИHВ€][B€›Ь€][H[€Ь™\™Y€Y€][K™Щ]
њЭ\ЉHOHќЩZYЪYЬЩ[XЭ[Ы—Ь™XXЪYШXљ[]WЫЭЫ™YЩY™\њ™YЪЫЪИ‚€B€ЬЬ›™ЧЩ]™[ќИH\J[њЪ][Ы‹њ›™ЧЩ]™[ќКB‚€Y€^XЭЭЩZYЪY‚€^XЭYЭ\›Z[[H
€›ЫЫ
ЩZYЪYЪ]КB€[™[
][K™Щ]
›ШЪЩYЬ™X\ЫЫ€ЉHOHQ‘T”‘QФ‘PTУУ€›Ь€][H[€ЩZYЪYЪ]КB€[™[
][K™Щ]
њ›™ЧЩ]™[ќЬ™\Щ[ќЉH\И[ЩH›Ь€][H[€ЩZYЪYЪ]КB€[™Yќ\€OH™Y›Ь™B€[™›Э[њЪ][Ы‹›Э]ЫЫYKњЭXШЩ\ЬЫЬ—Щ[YЪX›B€[™›Э[њЪ][Ы‹ќ[њШXЭ[Ы‹›]]][ЫњВ€[™›Э[њЪ][Ы‹ќ[њШXЭ[Ы‹™]™[ќВ€[™›ЭЬЬ›™ЧЩ]™[ќВ€[™›ЭЭXШЩ\ЬЧЭ\ЪЧЫ›Щ\В€
B€[ЩN‚€^XЭYЭ\›Z[[H[њЪ][Ы‹›Э]ЫЫYKњЭXШЩ\ЬЫЬ—Щ[YЪX›B‚€™]\›€В€›ЪИЋ€Щ[XЭYЭЪ[™ЭИ[™™X[Ь›ЫЭ[™Xљ[]WШ]]Ьљ]H[™^XЭYЭ\›Z[[€њЭYЩHЋ€ЫЫX]Щ^XЭ]Ь—Щ^XЭ]H‹€XЭ[Ы€Ћ€В€XЭ[Ы—ЪYЋ€ЫЫ[X[™XЭ[Ы—ЪY€XЭ[Ы—Ы]™[Ћ€ЫЫ[X[™XЭ[Ы—Ы]™[€™Yљ[љ][Ы—ЪYЋ€Yљ[љ][Ы‹™Yљ[љ][Ы—ЪY€K€њЭ]\ЧЬЩ]\Ћ€Щ]\Щ]љY[ЩK€њЭ]\ЧЪ[њЭ[ЩWЪYЋ€ЭЉ]Z[Иљ[њЭ[ЩWЪY—JK€›Ь™\™YЩ]љY[ЩHЋ€Ь™\™Y€›Э]ЫЫYHЋ€В€њЭXШЩ\ЬЫЬ—Щ[YЪX›HЋ€[њЪ][Ы‹›Э]ЫЫYKњЭXШЩ\ЬЫЬ—Щ[YЪX›K€њ™X\ЫЫ—ШЫЩ\ИЋ€\Э
[њЪ][Ы‹›Э]ЫЫYKњ™X\ЫЫ—ШЫЩ\КK€›]]][Ы—ШЫЭ[ќЋ€[Љ[њЪ][Ы‹ќ[њШXЭ[Ы‹›]]][ЫњКK€™]™[ќШЫЭ[ќЋ€[Љ[њЪ][Ы‹ќ[њШXЭ[Ы‹™]™[ќКK€њ›™ЧЩ]™[ќШЫЭ[ќЋ€[ЉЬЬ›™ЧЩ]™[ќКK€њЩ][Y[ќЬ™XЫЬ™ШЫЭ[ќЋ€[Љ™XЫЬ™КK€њЭXШЩ\ЬЩќ[Э\ЪЧЩЬ\Ы›ЩWШЫЭ[ќЋ€[ЉЭXШЩ\ЬЧЭ\ЪЧЫ›Щ\КK€њЭ]WШЪ[™ЩYЋ€Yќ\€OH™Y›Ь™K€K€B‚‚™Y€ШќZ[Щ›ШЭ\ЩYЩ\™XЭЬќ[X›ЫЪК
HO€\VФќ[P›ЫЪЛXЭЬЭ‹[ћWWN‚€™X[ШЫЫќ^HЬОМXЧШќZ[Ь™X[ШЫЫќ^
‘СФ“УХ
B€ЭЫ™YH™X[ШЫЫќ^›ЭЩ\љ[™ЛќZ[ЫЭЫ™YШЫЫX][ќШYZ\ЬЪ[Ы—Ь›Ъ™XЭ[ЫЉ€Щ™™[њЪ]™WШXЭ[Ы—ЫЫ›OUќYK€X^ЬЩ\ќ[ќШЫЭ[ќLK€
B€Y€›ЭЭЫ™Y›ЪО‚€Z\ЩH\ЬЩ\ќ[Ы‘\њ›ЬЉ€›ЭЫ™YЫЫX][ќ›Ъ™XЭ[Ы€Z[Y€‚€
И‹‹љ›Ъ[ЉЫЬќY
Ъ][KЫЩH›Ь€][H[€ЭЫ™Yљ\ЬЭY\ЯJJB€
B€Э]\ЧЭљY]ИH™X[ШЫЫќ^њЭ]\ЧШќ[™KќљY]В€ЫЭ\ЩWЬШЫЬWЬ]ИHВ€][KњЫЭ\ЩKњЫЭ\ЩWЬ]›Ь€][H[€™X[ШЫЫќ^њЫЭ\ЩWЩЬ\њЫЭ\Щ\В€B€[ШШ[XЪЬИHЬОМXЧЩY\J€

›ЭЫ™YњЭ]\ЧШШ[XЪЬЛ
њ™X[ШЫЫќ^њЭ]\ЧШќ[™KШ[XЪЬКK€Ш[XЪЧЪY‹€
B€Ш[XЪЬИH\J€Ш[XЪВ€›Ь€Ш[XЪИ[€[ШШ[XЪЬВ€Y€Ш[XЪЛњЫЭ\ЩKњЫЭ\ЩWЬ][€ЫЭ\ЩWЬШЫЬWЬ]В€
B€Ш[XЪЧЪYИHШШ[XЪЛШ[XЪЧЪY›Ь€Ш[XЪИ[€Ш[XЪЬЯB€[ЬЭ]\ЧЭ\ЪЬИHЬОМXЧЩY\J€

›ЭЫ™YњЭ]\ЧШШ[XЪЧЭ\ЪЬЛ
њ™X[ШЫЫќ^њЭ]\ЧШќ[™KњЭ]\ЧЭ\ЪЬКK€ќ\ЪЧЪY‹€
B€Э]\ЧЭ\ЪЬИH\J€\ЪИ›Ь€\ЪИ[€[ЬЭ]\ЧЭ\ЪЬИY€\ЪЛШ[XЪЧЪY[€Ш[XЪЧЪYВ€
B€\Щ\ИHЬОМXЧЩY\J€

›ЭЫ™YXљ[]WЬ\Щ\Л
њЭ]\ЧЭљY]ЛXљ[]WЬ\Щ\КK€њ\ЩWЪY‹€
B€Xљ[]WЭ\ЪЬИHЬОМXЧЩY\J€

›ЭЫ™YXљ[]WЭ\ЪЬЛ
њЭ]\ЧЭљY]ЛXљ[]WЭ\ЪЬКK€ќ\ЪЧЪY‹€
B€Y™™XЭИHЬОМXЧЩY\J€

›ЭЫ™Y™Y™™XЭЛ
њЭ]\ЧЭљY]Л™Y™™XЭКK€™Y™™XЭЪY‹€
B€ЫЫ™][ЫњИHЬОМXЧЩY\J€

›ЭЫ™YЫЫ™][ЫњЛ
њЭ]\ЧЭљY]ЛЫЫ™][ЫњКK€ЫЫ™][Ы—ЪY‹€
B€\™Щ]ИHЬОМXЧЩY\J€

›ЭЫ™Yќ\™Щ]Щ^™\ЬЪ[ЫњЛ
њЭ]\ЧЭљY]Лќ\™Щ]Щ^™\ЬЪ[ЫњКK€ќ\™Щ]Щ^™\ЬЪ[Ы—ЪY‹€
B€]Y]YWЪ[ќ[ќИHЬОМXЧЩY\J€

›ЭЫ™Yњ]Y]YWЪ[ќ[ќЛ
њ™X[ШЫЫќ^њЭ]\ЧШќ[™Kњ]Y]YWЪ[ќ[ќКK€њ]Y]YWЪ[ќ[ќЪY‹€
B€Э]\ЧЩ]™[ќЩ[Z[Y\ИH\J€ЫЭЩ\—ЬЭ]\ЧЩ]™[ќЩ[Z[Y\К\Э
Ш[XЪЬКK\Э
Э]\ЧЭ\ЪЬКJB€
B€[™Ъ[™WЬќ[\ИHќZ[Щ[™Ъ[™WЬќ[WЬ™YЪ\ЭћJ
B€љY]ИHШ[›ЫљXШ[TЉ€™\њЪ[ЫЏ\Э]\ЧЭљY]Лќ™\њЪ[Ы‹€[ќ]Y\П[ЭЫ™Y™[ќ]Y\Л€Э[™[Ы™WШXљ[]WЩЬ\П\Э]\ЧЭљY]ЛњЭ[™[Ы™WШXљ[]WЩЬ\Л€Xљ[]WЬ\Щ\П\\Щ\Л€Xљ[]WЭ\ЪЬПXXљ[]WЭ\ЪЬЛ€Y™™XЭПYY™™XЭЛ€ЫЫ™][ЫњПXЫЫ™][ЫњЛ€›Ь›][\П[ЭЫ™Y™›Ь›][\Л€\™Щ]Щ^™\ЬЪ[ЫњП]\™Щ]Л€Э]\ЧШШ[XЪЬПXШ[XЪЬЛ€Э]\ЧШШ[XЪЧЭ\ЪЬП\Э]\ЧЭ\ЪЬЛ€Э]\ЧЩ]™[ќЩ[Z[Y\П\Э]\ЧЩ]™[ќЩ[Z[Y\Л€Э]\ЧЩ[XYЩWЩ[Z\ЬЪ[ЫњП[ЭЫ™YњЭ]\ЧЩ[XYЩWЩ[Z\ЬЪ[ЫњЛ€[XYЩWЫ[ЩYљY\њП[ЭЫ™Y™[XYЩWЫ[ЩYљY\њЛ€XЭ[Ы—Щ[^WЩ[Z\ЬЪ[ЫњП[ЭЫ™YXЭ[Ы—Щ[^WЩ[Z\ЬЪ[ЫњЛ€]Y]YWЪ[ќ[ќП\]Y]YWЪ[ќ[ќЛ€ЪЪ[ШЫЫќ[ќX][ЫњП[ЭЫ™YњЪЪ[ШЫЫќ[ќX][ЫњЛ€љYЩЩ\њП[ЭЫ™YќљYЩЩ\њЛ€Щ\ќ[ќЩYљ[љ][ЫњП[ЭЫ™YњЩ\ќ[ќЩYљ[љ][ЫњЛ€XЭ[Ы—ЩYљ[љ][ЫњП[ЭЫ™YXЭ[Ы—ЩYљ[љ][ЫњЛ€XЭ[Ы—ШXљ[]WШљ[™[™ЬП[ЭЫ™YXЭ[Ы—ШXљ[]WШљ[™[™ЬЛ€XЭ[Ы—ШYZ\ЬЪ[ЫњП[ЭЫ™YXЭ[Ы—ШYZ\ЬЪ[ЫњЛ€[љ]Шљ\ќЭ[\]\П[ЭЫ™Yќ[љ]Шљ\ќЭ[\]\Л€ЫЫX][ќШXЭ[Ы—ЬЩ]П[ЭЫ™YЫЫX][ќШXЭ[Ы—ЬЩ]Л€XЭ[Ы—Щ]™[ќП[ЭЫ™YXЭ[Ы—Щ]™[ќЛ€]Ь›Щљ[\П[ЭЫ™Yљ]Ь›Щљ[\Л€ЪЪ[Щ›Ь›][WШљ[™[™ЬП[ЭЫ™YњЪЪ[Щ›Ь›][WШљ[™[™ЬЛ€[XYЩWЩ[Z\ЬЪ[ЫњП[ЭЫ™Y™[XYЩWЩ[Z\ЬЪ[ЫњЛ€ЭYЪ™\ЬЧЩ[Z\ЬЪ[ЫњП[ЭЫ™YќЭYЪ™\ЬЧЩ[Z\ЬЪ[ЫњЛ€]]\—Ь›Щљ[\П[ЭЫ™Y]]\—Ь›Щљ[\Л€Ъ\XЭ\—Щ]WШШ\™П[ЭЫ™YЪ\XЭ\—Щ]WШШ\™Л€Ъ\XЭ\—Щ\]Z\Y[ќЩ[YЪXљ[]Y\П[ЭЫ™YЪ\XЭ\—Щ\]Z\Y[ќЩ[YЪXљ[]Y\Л€Ъ\XЭ\—ЫYXЪ[љ\ЫWЬЫЭП[ЭЫ™YЪ\XЭ\—ЫYXЪ[љ\ЫWЬЫЭЛ€Ъ\XЭ\—ЭXЩWЫ›Щ\П[ЭЫ™YЪ\XЭ\—ЭXЩWЫ›Щ\Л€Ъ\XЭ\—ЩZYЫЫ—ЬЫЭП[ЭЫ™YЪ\XЭ\—ЩZYЫЫ—ЬЫЭЛ€›Э[ЩWЬЫXЪY\П[ЭЫ™Y›Э[ЩWЬЫXЪY\Л€[Y[[™WЬќ[\ПY[™Ъ[™WЬќ[\Лќ[Y[[™WЬќ[\Л€™\ЫЭ\ЩWЬќ[\ПY[™Ъ[™WЬќ[\Лњ™\ЫЭ\ЩWЬќ[\Л€[XYЩWЩ›Ь›][WЬќ[\ПY[™Ъ[™WЬќ[\Л™[XYЩWЩ›Ь›][WЬќ[\Л€[XYЩWЬ›Э]WЬќ[\ПY[™Ъ[™WЬќ[\Л™[XYЩWЬ›Э]WЬќ[\Л€ЪY[Ьљ[Ьљ]WЬќ[\ПY[™Ъ[™WЬќ[\ЛњЪY[Ьљ[Ьљ]WЬќ[\Л€Y]Y]O^В€ќ[Y][Ы—ЬШЫЬHЋ€њWШL—Щ›ШЭ\ЩYЩ\™XЭ‹€™ќ[Э™ЩЫЭЩ\љ[™ЧШќZ[ШЫЭ[ќЋ€€K€
B€Ш][ЩИHX]\љX[^™WШЪ\XЭ\—Ьќ[ќ[YWЭ\ЪЧЩЬ\ШШ][ЩК€™X[ШЫЫќ^њЫЭ\ЩWШШ][ЩЛ€љY]Л€ЫЭ\ЩWЬЫ\ЪЭ\™X[ШЫЫќ^њЫ\ЪЭ€Yљ[љ][Ы—ЬШЫЬWШЫЫ\]OUќYK€
B€^\›[Щ\[™[ЪY\ИHќZ[Щ^\›[Э\ЪЧЭЬЫЩЮWЩ\[™[ЮWЫYЩ\Љ€XЭ[Ы—ШXљ[]WШљ[™[™ЬП]љY]ЛXЭ[Ы—ШXљ[]WШљ[™[™ЬЛ€Xљ[]WЬ\Щ\П]љY]ЛXљ[]WЬ\Щ\Л€Xљ[]WЭ\ЪЬП]љY]ЛXљ[]WЭ\ЪЬЛ€Э[™[Ы™WШXљ[]WЩЬ\П]љY]ЛњЭ[™[Ы™WШXљ[]WЩЬ\Л€Э]\ЧШШ[XЪЬП]љY]ЛњЭ]\ЧШШ[XЪЬЛ€Э]\ЧШШ[XЪЧЭ\ЪЬП]љY]ЛњЭ]\ЧШШ[XЪЧЭ\ЪЬЛ€
B€Ш[›ЫљXШ[H™\XЩJ€љY]Л€\ЪЧЩЬ\ШШ][ЩПXШ][ЩЛ€^\›[Э\ЪЧЭЬЫЩЮWЩ\[™[ЪY\ПY^\›[Щ\[™[ЪY\Л€
B€™]\›€ќ[P›ЫЪКШ[›ЫљXШ[
KВ€™ќ[Э™ЩЫЭЩ\љ[™ЧШќZ[ШЫЭ[ќЋ€€›ЭЫ™YШXЭ[Ы—ЩYљ[љ][Ы—ШЫЭ[ќЋ€[ЉЭЫ™YXЭ[Ы—ЩYљ[љ][ЫњКK€њЫЭ\ЩWЬШЫЬWЬ]ШЫЭ[ќЋ€[ЉЫЭ\ЩWЬШЫЬWЬ]КK€њЭ]\ЧШШ[XЪЧШЫЭ[ќЋ€[ЉШ[XЪЬКK€њЭ]\ЧЭ\ЪЧШЫЭ[ќЋ€[ЉЭ]\ЧЭ\ЪЬКK€ќ\ЪЧЩЬ\Щ[ќћWШЫЭ[ќЋ€[ЉШ][ЩЛ™[ќћWЫX]\љX[^][ЫњКK€™^\›[Э\ЪЧЭЬЫЩЮWЩ\[™[ЮWШЫЭ[ќЋ€[Љ^\›[Щ\[™[ЪY\КK€B‚‚™Y€ЭЪ[™ЭЧЬЭ]\ЧЭ\ЪЧЩXYЫ›ЬЭXЬКќ[\О€ќ[P›ЫЪКHO€XЭЬЭ‹[ћWN‚€Ш[XЪЧЭЧЩ]™[ќЛИHШXЭ[Ы—ЭЪ[™ЭЧШШ[XЪЧЫX\
ќ[\КB€›ЭЬО€\ЭЩXЭЬЭ‹[ћWWHHЧB€ЬЫЩWШЫЭ™\YЩN€XЭЬЭ‹[ќHHЯB€љYЩЩ\—Ь›ЭЬО€\ЭЩXЭЬЭ‹[ћWWHHЧB€›Ь€Ш[XЪИ[€ќ[\Лљ\‹њЭ]\ЧШШ[XЪЬО‚€Y€
€Ш[XЪЛњЫЭ\ЩWЫ[ЩHOH›XZ[›[™WШ]]\—ШXљ[]H‚€Ь€Ш[XЪЛЫЭ™\YЩWЬЭ]\ИOH™^XЭ]X›H‚€Ь€Ш[XЪЛYZ\ЬЪ[Ы—ЬЭ]\ИOH™^XЭ]X›H‚€Ь€Ш[XЪЛ™]™[ќ›Э[€Ш[XЪЧЭЧЩ]™[ќВ€
N‚€ЫЫќ[ќYB€\ЪЬИH\Jќ[\ЛњЭ]\ЧШШ[XЪЧЭ\ЪЬЧЩ›Ь—ШШ[XЪКШ[XЪЛШ[XЪЧЪY
JB€›Ь€\ЪИ[€\ЪЬО‚€Щ^HH€ћЭ\ЪЛ›ЬЫЩ__Э\ЪЛЫЭ™\YЩWЬЭ]\Я_Э\ЪЛ›ШЪЩYЬ™X\ЫЫџH‚€ЬЫЩWШЫЭ™\YЩVЪЩ^WHHЬЫЩWШЫЭ™\YЩK™Щ]
Щ^K
H
ИB€Y€\ЪЛ›ЬЫЩHOH•љYЩЩ\ђXљ[]HЋ‚€љYЩЩ\—Ь›ЭЬЛ\[™
В€Ш[XЪЧЪYЋ€Ш[XЪЛШ[XЪЧЪY€›[ЩYљY\—Ы[YHЋ€Ш[XЪЛ›[ЩYљY\—Ы[YK€™]™[ќЋ€Ш[XЪЛ™]™[ќ€Ш[XЪЧЬЫЭ\ЩWЬ]Ћ€Ш[XЪЛњЫЭ\ЩKњЫЭ\ЩWЬ]€ќ\ЪЧЪYЋ€\ЪЛќ\ЪЧЪY€ќ\ЪЧЬ]Ћ€\ЪЛќ\ЪЧЬ]€ЫЭ™\YЩWЬЭ]\ИЋ€\ЪЛЫЭ™\YЩWЬЭ]\Л€›ШЪЩYЬ™X\ЫЫ€Ћ€\ЪЛ›ШЪЩYЬ™X\ЫЫ‹€™Y™™XЭЪYЋ€\ЪЛ™Y™™XЭЪY€›[љЩYШXљ[]WЬ\ЩWЪYЋ€\ЪЛ›[љЩYШXљ[]WЬ\ЩWЪY€›[љЩYЬЭ[™[Ы™WЩЬ\ЪYЋ€\ЪЛ›[љЩYЬЭ[™[Ы™WЩЬ\ЪY€JB€›ЭЬЛ\[™
В€Ш[XЪЧЪYЋ€Ш[XЪЛШ[XЪЧЪY€›[ЩYљY\—Ы[YHЋ€Ш[XЪЛ›[ЩYљY\—Ы[YK€™]™[ќЋ€Ш[XЪЛ™]™[ќ€њЫЭ\ЩWЬ]Ћ€Ш[XЪЛњЫЭ\ЩKњЫЭ\ЩWЬ]€ќ\ЪЧШЫЭ[ќЋ€[Љ\ЪЬКK€ќ\ЪЧЫЬЫЩ\ИЋ€В€В€ќ\ЪЧЪYЋ€\ЪЛќ\ЪЧЪY€›ЬЫЩHЋ€\ЪЛ›ЬЫЩK€ЫЭ™\YЩWЬЭ]\ИЋ€\ЪЛЫЭ™\YЩWЬЭ]\Л€›ШЪЩYЬ™X\ЫЫ€Ћ€\ЪЛ›ШЪЩYЬ™X\ЫЫ‹€њ\™[ќЭ\ЪЧЪYЋ€\ЪЛњ\™[ќЭ\ЪЧЪY€B€›Ь€\ЪИ[€\ЪЬВ€K€JB€™]\›€В€ќЪ[™ЭЧШШ[XЪЧШЫЭ[ќЋ€[Љ›ЭЬКK€›ЬЫЩWШЫЭ™\YЩWШЫЭ[ќИЋ€XЭ
ЫЬќY
ЬЫЩWШЫЭ™\YЩKљ][\К
JJK€ќљYЩЩ\—ШXљ[]WЭ\ЪЧШЫЭ[ќШ[ШЫЭ™\YЩ\ИЋ€[ЉљYЩЩ\—Ь›ЭЬКK€ќљYЩЩ\—Ь›ЭЬИЋ€љYЩЩ\—Ь›ЭЬЦОЋK€Ш[XЪЧЬ›ЭЬИЋ€›ЭЬЦОЊЌK€B‚‚™Y€Ьќ[—Щ\™XЭ

HO€XЭЬЭ‹[ћWN‚€Э\ќYH[YKњ\™—ШЫЭ[ќ\Љ
B€ќ[\ЛќZ[Щ]љY[ЩHHШќZ[Щ›ШЭ\ЩYЩ\™XЭЬќ[X›ЫЪК
B€Y€›ЭЩ]]Љќ[\Лљ\‹ќ\ЪЧЩЬ\ШШ][ЩИ‹›Ы™JN‚€Z\ЩH\ЬЩ\ќ[Ы‘\њ›ЬЉ™›ШЭ\ЩY›ЩXЭ[Ы€Ш[›ЫљXШ[T€\И›И\ЪИЬ\Ш][ЩИЉB‚€[›ЫZ[]Ь‹Ш[XЪЧЭЧЩ]™[ќИHЬЭ]\ЧЩ[›ЫZ[]ЬЉќ[\КB€[›ЫZ[]Ь—ЩXYЫ›ЬЭXЬИHЭЪ[™ЭЧЬЭ]\ЧЭ\ЪЧЩXYЫ›ЬЭXЬКќ[\КB€Y€›Э[›ЫZ[]ЬЋ‚€[\ЩYH[YKњ\™—ШЫЭ[ќ\Љ
HHЭ\ќY€XZИH™\ЫЭ\ЩK™Щ]ќ\ШYЩJ™\ЫЭ\ЩK”•TРQСWФСSЉKњќWЫX^њЬВ€™]\›€В€›ЪИЋ€[ЩK€›[ЩHЋ€™\™XЭ‹€њ™X\ЫЫ€Ћ€ђL€™X[\ЫЭ\ЩHЭ]\ЛO›™\ЭYXљ[]H[›ЫZ[]Ь€\И[\H‹€™[›ЫZ[]Ь€Ћ€ЧK€™[›ЫZ[]Ь—ШЫЭ[ќЋ€€ќZ[Щ]љY[ЩHЋ€ќZ[Щ]љY[ЩK€™[›ЫZ[]Ь—ЩXYЫ›ЬЭXЬИЋ€[›ЫZ[]Ь—ЩXYЫ›ЬЭXЬЛ€њ™\ЫЭ\ЩHЋ€В€ќШ[ЬЩXЫЫ™ИЋ€›Э[™
[\ЩYЉK€њXZЧЬњЬЧЪЪX€Ћ€XZЛ€ќШ[ШќYЩ]ЬЩXЫЫ™ИЋ€СT‘PХТT‘ФСPУУ‘Л€њњЬЧШќYЩ]ЪЪX€Ћ€СT‘PХФ”ФЧУSRUТТP‹€K€B€ЩZYЪYHЬ›ЭИ›Ь€›ЭИ[€[›ЫZ[]Ь€Y€›ЭЦИќЩZYЪYЬЩ[XЭ[Ы—ЪYИ—WB€›ЫќЩZYЪYHЬ›ЭИ›Ь€›ЭИ[€[›ЫZ[]Ь€Y€›Э›ЭЦИќЩZYЪYЬЩ[XЭ[Ы—ЪYИ—WB€XЭ[Ы—ШШ[™Y]\ИHШXЭ[Ы—ШШ[™Y]\ЧШћWЭЪ[™ЭКќ[\КB‚€][\О€\ЭЩXЭЬЭ‹[ћWWHHЧB€ЩZYЪYЬЭXШЩ\ЬО€XЭЬЭ‹[ћWH›Ы™HH›Ы™B€›Ь€›ЭИ[€ЩZYЪY‚€›Ь€]™[ќЭ\H[€›ЭЦИXЭ[Ы—ЭЪ[™ЭЧЩ]™[ќЭ\\И—N‚€›Ь€Yљ[љ][Ы‹\ЩWШЫЫќ^[€XЭ[Ы—ШШ[™Y]\Л™Щ]
]™[ќЭ\K

JN‚€][\HШ][\Щ\™XЭ
€ќ[\Л€›ЭЛ€Yљ[љ][Ы‹€\ЩWШЫЫќ^€^XЭЭЩZYЪYUќYK€
B€][\Л\[™
€В€љЪ[™Ћ€ќЩZYЪY‹€Ш[XЪЧЪYЋ€›ЭЦИШ[XЪЧЪY—K€™]™[ќЭ\HЋ€]™[ќЭ\K€XЭ[Ы—ЪYЋ€Yљ[љ][Ы‹XЭ[Ы—ЪY€›ЪИЋ€][\™Щ]
›ЪИ‹[ЩJK€њЭYЩHЋ€][\™Щ]
њЭYЩH‹€ЉK€њ™X\ЫЫ€Ћ€][\™Щ]
њ™X\ЫЫ€‹€ЉK€B€
B€Y€][\™Щ]
›ЪИЉN‚€ЩZYЪYЬЭXШЩ\ЬИHИ™[›ЫZ[]Ь—Ь›ЭИЋ€›ЭЛ™\™XЭЋ€][\B€њ™XZВ€Y€ЩZYЪYЬЭXШЩ\ЬИ\И›Э›Ы™N‚€њ™XZВ€Y€ЩZYЪYЬЭXШЩ\ЬИ\И›Э›Ы™N‚€њ™XZВ‚€›ЫќЩZYЪYЬЭXШЩ\ЬО€XЭЬЭ‹[ћWH›Ы™HH›Ы™B€Y€›ЫќЩZYЪY‚€›Ь€›ЭИ[€›ЫќЩZYЪY‚€›Ь€]™[ќЭ\H[€›ЭЦИXЭ[Ы—ЭЪ[™ЭЧЩ]™[ќЭ\\И—N‚€›Ь€Yљ[љ][Ы‹\ЩWШЫЫќ^[€XЭ[Ы—ШШ[™Y]\Л™Щ]
]™[ќЭ\K

JN‚€][\HШ][\Щ\™XЭ
€ќ[\Л€›ЭЛ€Yљ[љ][Ы‹€\ЩWШЫЫќ^€^XЭЭЩZYЪYQ[ЩK€
B€][\Л\[™
€В€љЪ[™Ћ€››ЫќЩZYЪY‹€Ш[XЪЧЪYЋ€›ЭЦИШ[XЪЧЪY—K€™]™[ќЭ\HЋ€]™[ќЭ\K€XЭ[Ы—ЪYЋ€Yљ[љ][Ы‹XЭ[Ы—ЪY€›ЪИЋ€][\™Щ]
›ЪИ‹[ЩJK€њЭYЩHЋ€][\™Щ]
њЭYЩH‹€ЉK€њ™X\ЫЫ€Ћ€][\™Щ]
њ™X\ЫЫ€‹€ЉK€B€
B€Y€][\™Щ]
›ЪИЉN‚€›ЫќЩZYЪYЬЭXШЩ\ЬИHИ™[›ЫZ[]Ь—Ь›ЭИЋ€›ЭЛ™\™XЭЋ€][\B€њ™XZВ€Y€›ЫќЩZYЪYЬЭXШЩ\ЬИ\И›Э›Ы™N‚€њ™XZВ€Y€›ЫќЩZYЪYЬЭXШЩ\ЬИ\И›Э›Ы™N‚€њ™XZВ‚€[\ЩYH[YKњ\™—ШЫЭ[ќ\Љ
HHЭ\ќY€XZИH™\ЫЭ\ЩK™Щ]ќ\ШYЩJ™\ЫЭ\ЩK”•TРQСWФСSЉKњќWЫX^њЬВ€™YXШ]\ИHВ€њ›ЩXЭ[Ы—ШШ[›ЫљXШ[Ъ\—ШќZ[Ћ€ќYK€™[[ZXЧЩ[›ЫZ[]Ь—Ы›Ы™[\HЋ€›ЫЫ
[›ЫZ[]ЬЉK€ќЩZYЪYЩ[›ЫZ[]Ь—Ь™XXЪ\ЧШXљ[]WЩY™\њ™YШ›Э[™\ћHЋ€
€›ЭЩZYЪYЬ€ЩZYЪYЬЭXШЩ\ЬИ\И›Э›Ы™B€
K€››ЫќЩZYЪYЩ[›ЫZ[]Ь—ЬЭXШЩ\ЬЧЩ^XЭ]\ЧЭЪ[—Ь™\Щ[ќЋ€
€›Э›ЫќЩZYЪYЬ€›ЫќЩZYЪYЬЭXШЩ\ЬИ\И›Э›Ы™B€
K€њ™X[Щ\™XЭЩ[ќћWЪ\ЧШЫЫX]Щ^XЭ]Ь—Щ^XЭ]HЋ€ќYK€њЮ[ќ]XЧЩ\™XЭШЫЭ[ќЪ\ЧЮ™\›ИЋ€ќYK€™\™XЭЭЪ][—Ь™XЫЫ[Y[™YЭШ[ШќYЩ]Ћ€[\ЩYHСT‘PХТT‘ФСPУУ‘Л€™\™XЭЭЪ][—Ь™XЫЫ[Y[™YЬњЬЧШќYЩ]Ћ€XZИHСT‘PХФ”ФЧУSRUТТP‹€B€™]\›€В€›ЪИЋ€[
™YXШ]\Лќ[Y\К
JK€›[ЩHЋ€™\™XЭ‹€њ™YXШ]\ИЋ€™YXШ]\Л€™[›ЫZ[]Ь€Ћ€[›ЫZ[]Ь‹€™[›ЫZ[]Ь—ШЫЭ[ќЋ€[Љ[›ЫZ[]ЬЉK€ќЩZYЪYЩ[›ЫZ[]Ь—ШЫЭ[ќЋ€[ЉЩZYЪY
K€››ЫќЩZYЪYЩ[›ЫZ[]Ь—ШЫЭ[ќЋ€[Љ›ЫќЩZYЪY
K€XЭ[Ы—ЭЪ[™ЭЧШШ[XЪЧЩ]™[ќИЋ€В€Щ^N€\Э
[YJH›Ь€Щ^K[YH[€ЫЬќY
Ш[XЪЧЭЧЩ]™[ќЛљ][\К
JB€K€ќЩZYЪYЬ™\™\Щ[ќ]]™HЋ€ЩZYЪYЬЭXШЩ\ЬЛ€››ЫќЩZYЪYЬ™\™\Щ[ќ]]™HЋ€›ЫќЩZYЪYЬЭXШЩ\ЬЛ€][\ИЋ€][\ЦЛN—K€ќZ[Щ]љY[ЩHЋ€ќZ[Щ]љY[ЩK€™[›ЫZ[]Ь—ЩXYЫ›ЬЭXЬИЋ€[›ЫZ[]Ь—ЩXYЫ›ЬЭXЬЛ€њ™\ЫЭ\ЩHЋ€В€ќШ[ЬЩXЫЫ™ИЋ€›Э[™
[\ЩYЉK€њXZЧЬњЬЧЪЪX€Ћ€XZЛ€ќШ[ШќYЩ]ЬЩXЫЫ™ИЋ€СT‘PХТT‘ФСPУУ‘Л€њњЬЧШќYЩ]ЪЪX€Ћ€СT‘PХФ”ФЧУSRUТТP‹€K€B‚‚™Y€Ь\њЩWШ\™ЬК
HO€\™Ь\њЩK“[Y\ЬXЩN‚€\њЩ\€H\™Ь\њЩKђ\™Э[Y[ќ\њЩ\Љ€\ШЬљ\[ЫЏH•[Y]HKPL€XЭ[Ы‹]Ъ[™ЭИЭ]\И™\ЭYXљ[]H[њЬЬќ€‚€
B€[ЩHH\њЩ\‹YЫ]]X[WЩ^Ы\Ъ]™WЩЬ›Э\
™\]Z\™YUќYJB€[ЩKYШ\™Э[Y[ќ
‹KY\Э‹XЭ[ЫЏHњЭЬ™WЭќYHЉB€[ЩKYШ\™Э[Y[ќ
‹KY\™XЭ‹XЭ[ЫЏHњЭЬ™WЭќYHЉB€™]\›€\њЩ\‹њ\њЩWШ\™ЬК
B‚‚™Y€XZ[Љ
HO€[ќ‚€\™ЬИHЬ\њЩWШ\™ЬК
B€™\Э[HЬќ[—Щ\Э

HY€\™ЬЛ™\Э[ЩHЬќ[—Щ\™XЭ

B€љ[ќ
њЫЫ‹™[\К™\Э[[њЭ\™WШ\ШЪZOQ[ЩKЫЬќЪЩ^\ПUќYK[™[ќLЉJB€™]\›€Y€™\Э[™Щ]
›ЪИЉH\ИќYH[ЩHB‚‚љY€ЧЫ[YWЧИOH—ЧЫXZ[—ЧИЋ‚€Z\ЩHЮ\Э[Q^]
XZ[Љ
JB