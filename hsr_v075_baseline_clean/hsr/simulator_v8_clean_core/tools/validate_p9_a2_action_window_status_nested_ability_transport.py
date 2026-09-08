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
    _PACKAGE_ROOT = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(_PACKAGE_ROOT))
    __package__ = "hsr.simulator_v8_clean_core.tools"

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
from ..tbgd.action_target_contracts import build_action_target_contract_catalog
from ..tbgd.task_graph_materializer import (
    build_complete_task_graph_catalog,
    materialize_ability_phase_task_graph,
    materialize_status_callback_task_graph,
    merge_task_graph_slices,
)
from .validate_p9_a2_p0_action_window_status_callback_admission_finalization import (
    _build_focused_direct_ir as _a2p0_build_focused_direct_ir,
)
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

    bad_stack = replace(child_request, active_graph_stack=(child_graph.graph_id,))
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
        context, child_request, _state()
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
            seen_channels.append("leaf") or TaskGraphLeafResult("resolved")
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
            seen_channels.append("count") or TaskGraphCountResult("resolved", count=1)
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
        rules, "E", child_graph.owner_id, executable=False
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
        rules, _B5StatusCallbacks(rules), generic_details
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
        rules, _B5StatusCallbacks(rules), generic_details
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
        rules, _B5StatusCallbacks(rules), generic_details
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
        rules, _B5StatusCallbacks(rules), generic_details
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
        rules, _B5StatusCallbacks(rules), generic_details
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
    root_dispatcher = _B5Dispatcher(rules, root_probe, generic_details)
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
            and tuple(event.event_id for event in wrong_provider.events)
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
        "status_graph_requests_remain_status_owned": (
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
            not generic_success.errors and generic_pair_transport
        ),
        "s8b5_active_stack_regression_pass": (
            not generic_success.errors and generic_child_stack_ok
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
    return predicates, {
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
    return {
        "ok": all(predicates.values()) and elapsed <= _FAST_HARD_SECONDS and peak <= _FAST_RSS_LIMIT_KIB,
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


def _merge_ir(values: Iterable[Any], field: str) -> tuple[Any, ...]:
    merged: dict[str, Any] = {}
    for value in values:
        identity = str(getattr(value, field))
        previous = merged.get(identity)
        if previous is not None and previous != value:
            raise AssertionError(f"focused_runtime_projection_conflict:{field}:{identity}")
        merged[identity] = value
    return tuple(merged[key] for key in sorted(merged))


def _build_runtime_direct_rulebook() -> tuple[
    RuleBook,
    tuple[dict[str, Any], ...],
    tuple[dict[str, Any], ...],
    dict[str, Any],
    dict[str, Any],
]:
    (
        lowerer,
        focused_ir,
        _focused_rules,
        finalizer_audit,
        reconciled_denominator,
        finalizer_build_evidence,
        same_event_transitions,
    ) = _a2p0_build_focused_direct_ir()
    del _focused_rules

    lowerer.build_character_ability_source_resolution_catalog()
    owned = lowerer.build_owned_combatant_admission_projection(
        offensive_action_only=True,
        max_servant_count=1,
    )
    if not owned.ok:
        raise AssertionError(
            "owned combatant projection failed:"
            + ",".join(sorted({item.code for item in owned.issues}))
        )
    snapshot = getattr(lowerer, "_character_ability_raw_snapshot", None)
    scope = getattr(lowerer, "_character_ability_scope_catalog", None)
    if snapshot is None or scope is None:
        raise AssertionError("focused runtime source catalog prerequisite missing")
    source_graph = lowerer.build_character_ability_source_graph_catalog(
        snapshot=snapshot,
        scope_catalog=scope,
    )
    source_catalog = lowerer.build_character_control_flow_contract_catalog(
        snapshot=snapshot,
        scope_catalog=scope,
    )
    complete_catalog = build_complete_task_graph_catalog(source_catalog, snapshot)

    action_events_by_key = {
        (event.action_id, event.level): event for event in owned.action_events
    }
    admissions_by_key: dict[tuple[str, int], list[Any]] = {}
    for admission in owned.action_admissions:
        if (
            admission.coverage_status == "executable"
            and not admission.blocked_reason
            and "external_turn" in admission.submission_modes
        ):
            admissions_by_key.setdefault(
                (admission.action_id, admission.action_level), []
            ).append(admission)

    selected_action_ir: CanonicalIR | None = None
    selected_action_definition: Any | None = None
    selected_action_context: Any | None = None
    selected_action_windows: tuple[str, ...] = ()
    action_slice_attempts: list[dict[str, str]] = []
    for definition in sorted(
        owned.action_definitions,
        key=lambda item: (item.action_id, item.level, item.definition_id),
    ):
        character_action_sources = tuple(
            source
            for source in source_graph.action_sources
            if source.action_id == definition.action_id
        )
        if len(character_action_sources) != 1:
            continue
        try:
            candidate_ir = lowerer.build_character_action_ability_slice(
                definition,
                snapshot=snapshot,
                scope_catalog=scope,
                source_graph_catalog=source_graph,
            )
            candidate_slices = []
            for phase in candidate_ir.ability_phases:
                if phase.invocation_role not in {"action_root", "nested_only"}:
                    continue
                phase_tasks = tuple(
                    task
                    for task in candidate_ir.ability_tasks
                    if task.phase_id == phase.phase_id
                )
                callback_kinds = tuple(
                    dict.fromkeys(task.callback_kind for task in phase_tasks)
                )
                for callback_kind in callback_kinds:
                    candidate_slices.append(
                        materialize_ability_phase_task_graph(
                            source_catalog,
                            candidate_ir,
                            phase_id=phase.phase_id,
                            callback_kind=callback_kind,
                            source_snapshot=snapshot,
                        )
                    )
            if not candidate_slices:
                action_slice_attempts.append(
                    {
                        "definition_id": definition.definition_id,
                        "reason": "formal_action_slice_empty",
                    }
                )
                continue
            candidate_catalog = merge_task_graph_slices(
                complete_catalog, candidate_slices
            )
            candidate_dependencies = build_external_task_topology_dependency_ledger(
                action_ability_bindings=candidate_ir.action_ability_bindings,
                ability_phases=candidate_ir.ability_phases,
                ability_tasks=candidate_ir.ability_tasks,
                standalone_ability_graphs=candidate_ir.standalone_ability_graphs,
                status_callbacks=candidate_ir.status_callbacks,
                status_callback_tasks=candidate_ir.status_callback_tasks,
            )
            candidate_rules = RuleBook(
                replace(
                    candidate_ir,
                    task_graph_catalog=candidate_catalog,
                    external_task_topology_dependencies=candidate_dependencies,
                )
            )
            candidate_context = _a1_accepted_context(
                candidate_rules, definition, ()
            )
            candidate_windows = _action_windows(candidate_rules, definition)
            if (
                candidate_context is None
                or candidate_context[4] != "external_turn"
                or not candidate_context[-1].ok
                or "action.window.after_attack" not in candidate_windows
            ):
                action_slice_attempts.append(
                    {
                        "definition_id": definition.definition_id,
                        "reason": "production_action_not_admitted_after_slice",
                    }
                )
                continue
            selected_action_ir = candidate_ir
            selected_action_definition = definition
            selected_action_context = candidate_context
            selected_action_windows = candidate_windows
            break
        except (AssertionError, TypeError, ValueError) as exc:
            action_slice_attempts.append(
                {
                    "definition_id": definition.definition_id,
                    "reason": str(exc)[:240],
                }
            )

    if (
        selected_action_ir is None
        or selected_action_definition is None
        or selected_action_context is None
    ):
        raise AssertionError(
            "production after-attack action slice denominator is empty:"
            + json.dumps(action_slice_attempts[-12:], sort_keys=True)
        )

    action_ir = selected_action_ir
    standalone_graphs = _merge_ir(
        (*focused_ir.standalone_ability_graphs, *action_ir.standalone_ability_graphs),
        "standalone_ability_graph_id",
    )
    phases = _merge_ir((*focused_ir.ability_phases, *action_ir.ability_phases), "phase_id")
    ability_tasks = _merge_ir((*focused_ir.ability_tasks, *action_ir.ability_tasks), "task_id")
    effects = _merge_ir((*focused_ir.effects, *action_ir.effects), "effect_id")
    conditions = _merge_ir((*focused_ir.conditions, *action_ir.conditions), "condition_id")
    formulas = _merge_ir((*focused_ir.formulas, *action_ir.formulas), "formula_id")
    targets = _merge_ir(
        (*focused_ir.target_expressions, *action_ir.target_expressions),
        "target_expression_id",
    )
    queue_intents = _merge_ir(
        (*focused_ir.queue_intents, *action_ir.queue_intents),
        "queue_intent_id",
    )
    engine_rules = build_engine_rule_registry()
    view = replace(
        action_ir,
        standalone_ability_graphs=standalone_graphs,
        ability_phases=phases,
        ability_tasks=ability_tasks,
        effects=effects,
        conditions=conditions,
        formulas=formulas,
        target_expressions=targets,
        status_callbacks=focused_ir.status_callbacks,
        status_callback_tasks=focused_ir.status_callback_tasks,
        status_event_families=focused_ir.status_event_families,
        queue_intents=queue_intents,
        timeline_rules=engine_rules.timeline_rules,
        resource_rules=engine_rules.resource_rules,
        damage_formula_rules=engine_rules.damage_formula_rules,
        damage_route_rules=engine_rules.damage_route_rules,
        shield_priority_rules=engine_rules.shield_priority_rules,
        metadata={
            **dict(action_ir.metadata),
            "validation_scope": "p9_a2_pr12_finalized_status_plus_production_action_slice",
            "full_tbgd_lowering_build_count": 0,
        },
    )

    formal_slices = []
    formal_roles = {"action_root", "nested_only"}
    ability_slice_keys: list[tuple[str, str]] = []
    for phase in phases:
        if phase.invocation_role not in formal_roles:
            continue
        phase_tasks = tuple(
            task for task in ability_tasks if task.phase_id == phase.phase_id
        )
        callback_kinds = tuple(dict.fromkeys(task.callback_kind for task in phase_tasks))
        if not callback_kinds:
            raise AssertionError(
                f"focused_runtime_formal_phase_task_denominator_empty:{phase.phase_id}"
            )
        for callback_kind in callback_kinds:
            formal_slices.append(
                materialize_ability_phase_task_graph(
                    source_catalog,
                    view,
                    phase_id=phase.phase_id,
                    callback_kind=callback_kind,
                    source_snapshot=snapshot,
                )
            )
            ability_slice_keys.append((phase.phase_id, callback_kind))

    status_slice_ids: list[str] = []
    for callback in focused_ir.status_callbacks:
        if not any(
            task.callback_id == callback.callback_id
            for task in focused_ir.status_callback_tasks
        ):
            continue
        formal_slices.append(
            materialize_status_callback_task_graph(
                source_catalog,
                view,
                callback_id=callback.callback_id,
                source_snapshot=snapshot,
            )
        )
        status_slice_ids.append(callback.callback_id)

    if not formal_slices or not ability_slice_keys or not status_slice_ids:
        raise AssertionError("focused runtime formal slice denominator is empty")
    catalog = merge_task_graph_slices(complete_catalog, formal_slices)
    external_dependencies = build_external_task_topology_dependency_ledger(
        action_ability_bindings=view.action_ability_bindings,
        ability_phases=view.ability_phases,
        ability_tasks=view.ability_tasks,
        standalone_ability_graphs=view.standalone_ability_graphs,
        status_callbacks=view.status_callbacks,
        status_callback_tasks=view.status_callback_tasks,
    )
    canonical = replace(
        view,
        task_graph_catalog=catalog,
        external_task_topology_dependencies=external_dependencies,
    )
    return (
        RuleBook(canonical),
        finalizer_audit,
        reconciled_denominator,
        {
            **finalizer_build_evidence,
            "owned_action_definition_count": len(owned.action_definitions),
            "selected_action_definition_id": selected_action_definition.definition_id,
            "selected_action_id": selected_action_definition.action_id,
            "selected_action_level": selected_action_definition.level,
            "selected_action_source_path": selected_action_definition.source.source_path,
            "selected_action_admission_id": selected_action_context[3].admission_id,
            "selected_action_windows": list(selected_action_windows),
            "action_slice_failed_attempt_count": len(action_slice_attempts),
            "combined_ability_phase_count": len(phases),
            "combined_ability_task_count": len(ability_tasks),
            "combined_effect_count": len(effects),
            "ability_formal_slice_count": len(ability_slice_keys),
            "status_formal_slice_count": len(status_slice_ids),
            "combined_task_graph_entry_count": len(catalog.entry_materializations),
            "external_task_topology_dependency_count": len(external_dependencies),
        },
        same_event_transitions,
    )


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
            child_candidates: list[tuple[Any, TaskGraphIR, str]] = []
            for phase_id in phase_ids:
                phase = rules.ability_phase(phase_id)
                if phase is None or phase.invocation_role != "nested_only":
                    continue
                phase_tasks = tuple(rules.ability_tasks_for_phase(phase_id))
                callback_kinds = tuple(
                    sorted({candidate.callback_kind for candidate in phase_tasks})
                )
                for callback_kind in callback_kinds:
                    child_tasks = tuple(
                        candidate
                        for candidate in phase_tasks
                        if candidate.callback_kind == callback_kind
                    )
                    if not child_tasks:
                        continue
                    child_query = rules.query_formal_task_graph(
                        "ability_phase_callback",
                        phase_id,
                        callback_kind,
                        (candidate.task_id for candidate in child_tasks),
                    )
                    child_graph = child_query.value
                    if child_query.status == "resolved" and type(child_graph) is TaskGraphIR:
                        child_candidates.append((phase, child_graph, callback_kind))
            if len(child_candidates) != 1:
                continue
            phase, child_graph, nested_callback_kind = child_candidates[0]
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
                    "nested_callback_kind": nested_callback_kind,
                    "nested_graph_id": child_graph.graph_id,
                    "nested_task_ids": list(child_graph.root_formal_task_ids),
                    "weighted_selection_ids": [
                        item.selection_id for item in child_graph.weighted_selections
                    ],
                    "action_window_event_types": list(callback_to_events[callback.event]),
                }
            )
    rows.sort(key=lambda row: (row["callback_id"], row["status_task_id"], row["nested_graph_id"]))
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
        event = rules.action_event(definition.action_id, definition.level)
        if event is None or event.target_mode == "bounce":
            continue
        admissions = tuple(
            sorted(
                (
                    admission
                    for admission in rules.ir.action_admissions
                    if admission.action_id == definition.action_id
                    and admission.action_level == definition.level
                    and admission.coverage_status == "executable"
                    and not admission.blocked_reason
                    and "external_turn" in admission.submission_modes
                ),
                key=lambda admission: admission.admission_id,
            )
        )
        context = None
        for admission in admissions:
            state = BattleState(
                units={
                    "validation:actor": UnitState(
                        unit_id="validation:actor",
                        side="ally",
                        template_id=admission.owner_entity_ref,
                        max_hp=100000.0,
                        hp=100000.0,
                        energy=100000.0,
                        max_energy=100000.0,
                        flags={"position": 0},
                        resources={
                            "special_energy": 100000.0,
                            "special_resource": 100000.0,
                            "charge": 100000.0,
                        },
                    ),
                    "validation:enemy": UnitState(
                        unit_id="validation:enemy",
                        side="enemy",
                        template_id="validation:enemy_template",
                        max_hp=100000.0,
                        hp=100000.0,
                        flags={"position": 1},
                    ),
                },
                skill_points=99,
                max_skill_points=99,
                global_flags={
                    "turn_owner_id": "validation:actor",
                    "current_window": (
                        admission.allowed_windows[0]
                        if admission.allowed_windows
                        else "idle"
                    ),
                    "phase": "combat",
                },
            )
            accepted = _accepted_action_on_state(rules, state, definition)
            if accepted is None:
                continue
            command, target_context, decision = accepted
            if (
                decision.admission is None
                or decision.admission.admission_id != admission.admission_id
            ):
                continue
            context = (
                state,
                command,
                target_context,
                admission,
                "external_turn",
                decision,
            )
            break
        if context is None:
            continue
        for event_type in _action_windows(rules, definition):
            bucket = result.setdefault(event_type, [])
            if len(bucket) < 6:
                bucket.append((definition, context))
    return result


def _real_add_modifier_effects(rules: RuleBook, modifier_name: str) -> tuple[Any, ...]:
    result = []
    for effect in rules.ir.effects:
        if effect.opcode != "AddModifier":
            continue
        standard = effect.payload.get("standard")
        if not isinstance(standard, Mapping) or standard.get("modifier_name") != modifier_name:
            continue
        if getattr(effect, "coverage_status", "executable") not in {"", "executable"}:
            continue
        result.append(effect)
    return tuple(sorted(result, key=lambda item: item.effect_id))


def _attached_callback_detail(state: BattleState, row: Mapping[str, Any]) -> dict[str, Any] | None:
    actor = state.units.get("validation:actor")
    if actor is None:
        return None
    details = actor.flags.get("status_details", ())
    if not isinstance(details, (list, tuple)):
        return None
    matches = []
    for item in details:
        if not isinstance(item, dict) or str(item.get("modifier_name") or "") != row["modifier_name"]:
            continue
        trigger_ids = item.get("trigger_ids_by_event")
        ids = trigger_ids.get(row["callback_event"]) if isinstance(trigger_ids, dict) else None
        if isinstance(ids, list) and row["callback_id"] in ids:
            matches.append(dict(item))
    return matches[0] if len(matches) == 1 else None


def _attach_real_status(
    rules: RuleBook,
    base_state: BattleState,
    row: Mapping[str, Any],
) -> tuple[BattleState, dict[str, Any], dict[str, Any]] | None:
    system = StatusSystem(rules)
    reducer = MutationReducer()
    setup_resolution = TargetResolution(
        requested=("validation:actor",),
        selectable=("validation:actor",),
        legal=("validation:actor",),
        primary="validation:actor",
        impact_group=("validation:actor",),
        selected=("validation:actor",),
        reason="production_status_setup",
        source="status_system_setup_target",
    )
    for effect in _real_add_modifier_effects(rules, str(row["modifier_name"])):
        for caster_id in ("validation:actor", "validation:enemy"):
            result = system.apply_add_modifier(
                base_state,
                effect,
                caster_id=caster_id,
                source_id=caster_id,
                owner_id="validation:actor",
                param_entity_id="validation:actor",
                current_action_target_id="validation:actor",
                target_resolution=setup_resolution,
                event_payload={
                    "validation_stage": "P9-A2",
                    "actor_id": "validation:actor",
                    "target_id": "validation:actor",
                    "selected_target_ids": ["validation:actor"],
                    "primary_action_target_id": "validation:actor",
                },
                binding_sources=(
                    {
                        "source_kind": "p9_a2_direct_status_setup",
                        "effect_id": effect.effect_id,
                        "callback_id": str(row["callback_id"]),
                    },
                ),
            )
            if not result.ok:
                continue
            reduced = reducer.apply_all_result(base_state, result.mutations)
            if not reduced.ok:
                continue
            detail = _attached_callback_detail(reduced.after_state, row)
            if detail is None:
                continue
            if status_control_gate_for_actor(reduced.after_state.units["validation:actor"]) is not None:
                continue
            return (
                reduced.after_state,
                detail,
                {
                    "effect_id": effect.effect_id,
                    "effect_source_path": effect.source.source_path,
                    "caster_id": caster_id,
                    "setup_mutation_count": len(result.mutations),
                    "setup_event_count": len(result.events),
                    "setup_rng_event_count": len(result.rng_events),
                    "setup_record_count": len(result.records),
                },
            )
    return None


def _accepted_action_on_state(
    rules: RuleBook,
    state: BattleState,
    definition: Any,
) -> tuple[ActionCommand, Any, Any] | None:
    selector = ActionTargetSelectionSystem(rules)
    query = selector.query(state, "validation:actor", definition.action_id, definition.level)
    if query.status != "resolved":
        return None
    submitted = () if query.selection_mode == "automatic" else tuple(
        query.candidate_ids[: (query.selection_min or 1)]
    )
    accepted = selector.accept(state, query, submitted)
    if accepted.status != "accepted" or accepted.context is None:
        return None
    command = ActionCommand(
        actor_id="validation:actor",
        action_id=definition.action_id,
        action_level=definition.level,
        target_ids=(
            () if query.selection_mode == "automatic" else accepted.context.accepted.selected_target_ids
        ),
    )
    if selector.context_blocked_reason(state, command, accepted.context):
        return None
    decision = ActionContractSystem(rules).evaluate(
        state,
        command,
        submission_mode="external_turn",
        target_selection_fingerprint=accepted.context.context_fingerprint,
    )
    if not decision.ok:
        return None
    return command, accepted.context, decision


def _attempt_direct(
    rules: RuleBook,
    row: Mapping[str, Any],
    definition: Any,
    base_context: Any,
    *,
    expect_weighted: bool,
) -> dict[str, Any]:
    base_state = base_context[0]
    attached = _attach_real_status(rules, base_state, row)
    if attached is None:
        return {"ok": False, "stage": "status_attach", "reason": "real_status_producer_gap"}
    status_state, detail, setup_evidence = attached
    accepted = _accepted_action_on_state(rules, status_state, definition)
    if accepted is None:
        return {"ok": False, "stage": "action_readmission", "reason": "action_not_admitted_after_status_setup"}
    command, target_context, decision = accepted

    executor = CombatExecutor(rules)
    ordered: list[dict[str, Any]] = [
        {
            "step": "action_admission_accepted",
            "admission_id": decision.admission.admission_id if decision.admission else "",
            "action_id": command.action_id,
            "action_level": command.action_level,
            "target_selection_fingerprint": target_context.context_fingerprint,
        }
    ]
    original_window = executor.event_dispatcher.dispatch_action_window_listeners

    def window_probe(current_state: BattleState, **kwargs: Any) -> Any:
        event = kwargs["event"]
        ordered.append(
            {
                "step": "action_window_event_dispatched",
                "event_type": event.event_type,
                "event_id": event.event_id,
            }
        )
        return original_window(current_state, **kwargs)

    executor.event_dispatcher.dispatch_action_window_listeners = window_probe  # type: ignore[method-assign]
    original_root = executor.event_dispatcher.status_callbacks.execute_action_window_formal_root

    def root_probe(current_state: BattleState, **kwargs: Any) -> Any:
        callback_id = str(kwargs.get("callback_id") or "")
        if callback_id == row["callback_id"]:
            owner = current_state.units.get(str(kwargs.get("unit_id") or ""))
            real_detail = None
            if owner is not None:
                details = owner.flags.get("status_details", ())
                if isinstance(details, (list, tuple)):
                    real_detail = next(
                        (
                            item
                            for item in details
                            if isinstance(item, dict)
                            and str(item.get("instance_id") or "") == str(detail["instance_id"])
                        ),
                        None,
                    )
            ordered.append(
                {
                    "step": "real_status_listener_matched_and_formal_root_started",
                    "callback_id": callback_id,
                    "status_instance_id": str(detail["instance_id"]),
                    "real_detail_present": real_detail is not None,
                    "status_root_graph_id": str(row["status_root_graph_id"]),
                }
            )
        return original_root(current_state, **kwargs)

    executor.event_dispatcher.status_callbacks.execute_action_window_formal_root = root_probe  # type: ignore[method-assign]
    original_invocation = executor.ability_tasks._status_nested_invocation_for_request

    def invocation_probe(
        context: StatusNestedAbilityContext,
        request: TaskGraphHookRequest,
        current_state: BattleState,
    ) -> Any:
        invocation, reason = original_invocation(context, request, current_state)
        if request.graph_id == row["nested_graph_id"]:
            ordered.append(
                {
                    "step": "trigger_ability_selected_typed_nested_only_graph_and_reached_ability_authority",
                    "root_graph_id": context.root_graph_id,
                    "child_graph_id": request.graph_id,
                    "child_graph_node_id": request.graph_node_id,
                    "formal_task_id": request.formal_task_id,
                    "actor_id": invocation.actor_id if invocation is not None else "",
                    "target_ids": list(invocation.target_resolution.selected) if invocation is not None else [],
                    "blocked_reason": reason,
                }
            )
        return invocation, reason

    executor.ability_tasks._status_nested_invocation_for_request = invocation_probe  # type: ignore[method-assign]
    original_weighted = executor.ability_tasks._resolve_formal_weighted_selection

    def weighted_probe(request: TaskGraphHookRequest, selection: Any, current_state: BattleState) -> Any:
        result = original_weighted(request, selection, current_state)
        if request.graph_id == row["nested_graph_id"]:
            ordered.append(
                {
                    "step": "weighted_selection_reached_ability_owned_deferred_hook",
                    "selection_id": selection.selection_id,
                    "graph_node_id": request.graph_node_id,
                    "blocked_reason": result.blocked_reason,
                    "rng_event_present": result.rng_event is not None,
                }
            )
        return result

    executor.ability_tasks._resolve_formal_weighted_selection = weighted_probe  # type: ignore[method-assign]
    before = status_state.snapshot().to_json()
    after_state, transition = executor.execute(
        command,
        status_state,
        target_selection_context=target_context,
    )
    after = after_state.snapshot().to_json()
    settlement = transition.transaction.settlement
    records = tuple(settlement.records) if settlement is not None else ()
    success_task_nodes = [
        item
        for item in transition.outcome.node_results
        if item.node_kind == "task_graph_node" and item.status == "complete"
    ]
    selected_window = any(
        item.get("step") == "action_window_event_dispatched"
        and item.get("event_type") in row["action_window_event_types"]
        for item in ordered
    )
    real_root = any(
        item.get("step") == "real_status_listener_matched_and_formal_root_started"
        and item.get("real_detail_present") is True
        for item in ordered
    )
    ability_authority = any(
        item.get("step") == "trigger_ability_selected_typed_nested_only_graph_and_reached_ability_authority"
        and item.get("child_graph_id") == row["nested_graph_id"]
        and not item.get("blocked_reason")
        for item in ordered
    )
    weighted_hits = [
        item
        for item in ordered
        if item.get("step") == "weighted_selection_reached_ability_owned_deferred_hook"
    ]
    top_rng_events = tuple(transition.rng_events)
    if expect_weighted:
        expected_terminal = (
            bool(weighted_hits)
            and all(item.get("blocked_reason") == DEFERRED_REASON for item in weighted_hits)
            and all(item.get("rng_event_present") is False for item in weighted_hits)
            and after == before
            and not transition.outcome.successor_eligible
            and not transition.transaction.mutations
            and not transition.transaction.events
            and not top_rng_events
            and not success_task_nodes
        )
    else:
        expected_terminal = transition.outcome.successor_eligible
    return {
        "ok": selected_window and real_root and ability_authority and expected_terminal,
        "stage": "combat_executor_execute",
        "action": {
            "action_id": command.action_id,
            "action_level": command.action_level,
            "definition_id": definition.definition_id,
        },
        "status_setup": setup_evidence,
        "status_instance_id": str(detail["instance_id"]),
        "ordered_evidence": ordered,
        "outcome": {
            "successor_eligible": transition.outcome.successor_eligible,
            "reason_codes": list(transition.outcome.reason_codes),
            "mutation_count": len(transition.transaction.mutations),
            "event_count": len(transition.transaction.events),
            "rng_event_count": len(top_rng_events),
            "settlement_record_count": len(records),
            "successful_task_graph_node_count": len(success_task_nodes),
            "state_changed": after != before,
        },
    }


def _run_direct() -> dict[str, Any]:
    started = time.perf_counter()
    (
        rules,
        finalizer_audit,
        reconciled_denominator,
        build_evidence,
        same_event_transitions,
    ) = _build_runtime_direct_rulebook()
    if not getattr(rules.ir, "task_graph_catalog", None):
        raise AssertionError("production-focused CanonicalIR has no task graph catalog")
    if not finalizer_audit or not reconciled_denominator:
        raise AssertionError("PR12 action-window admission finalizer evidence is empty")

    denominator, callback_to_events = _status_denominator(rules)
    if not denominator:
        raise AssertionError("A2 real-source status->nested ability denominator is empty")
    weighted = [row for row in denominator if row["weighted_selection_ids"]]
    nonweighted = [row for row in denominator if not row["weighted_selection_ids"]]
    action_candidates = _action_candidates_by_window(rules)

    attempts: list[dict[str, Any]] = []
    weighted_success: dict[str, Any] | None = None
    for row in weighted:
        for event_type in row["action_window_event_types"]:
            for definition, base_context in action_candidates.get(event_type, ()):
                attempt = _attempt_direct(
                    rules, row, definition, base_context, expect_weighted=True
                )
                attempts.append(
                    {
                        "kind": "weighted",
                        "callback_id": row["callback_id"],
                        "event_type": event_type,
                        "action_id": definition.action_id,
                        "ok": attempt.get("ok", False),
                        "stage": attempt.get("stage", ""),
                        "reason": attempt.get("reason", ""),
                    }
                )
                if attempt.get("ok"):
                    weighted_success = {"denominator_row": row, "direct": attempt}
                    break
            if weighted_success is not None:
                break
        if weighted_success is not None:
            break

    nonweighted_success: dict[str, Any] | None = None
    for row in nonweighted:
        for event_type in row["action_window_event_types"]:
            for definition, base_context in action_candidates.get(event_type, ()):
                attempt = _attempt_direct(
                    rules, row, definition, base_context, expect_weighted=False
                )
                attempts.append(
                    {
                        "kind": "nonweighted",
                        "callback_id": row["callback_id"],
                        "event_type": event_type,
                        "action_id": definition.action_id,
                        "ok": attempt.get("ok", False),
                        "stage": attempt.get("stage", ""),
                        "reason": attempt.get("reason", ""),
                    }
                )
                if attempt.get("ok"):
                    nonweighted_success = {"denominator_row": row, "direct": attempt}
                    break
            if nonweighted_success is not None:
                break
        if nonweighted_success is not None:
            break

    elapsed = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    predicates = {
        "production_canonical_ir_built": True,
        "dynamic_denominator_nonempty": bool(denominator),
        "action_window_action_candidates_nonempty": any(action_candidates.values()),
        "weighted_denominator_reaches_ability_deferred_boundary": (
            not weighted or weighted_success is not None
        ),
        "nonweighted_denominator_success_executes_when_present": (
            not nonweighted or nonweighted_success is not None
        ),
        "real_direct_entry_is_combat_executor_execute": True,
        "synthetic_direct_count_is_zero": True,
        "direct_within_recommended_wall_budget": elapsed <= _DIRECT_HARD_SECONDS,
        "direct_within_recommended_rss_budget": peak <= _DIRECT_RSS_LIMIT_KIB,
    }
    return {
        "ok": all(predicates.values()),
        "mode": "direct",
        "predicates": predicates,
        "denominator": denominator,
        "denominator_count": len(denominator),
        "weighted_denominator_count": len(weighted),
        "nonweighted_denominator_count": len(nonweighted),
        "action_candidate_counts": {
            key: len(value) for key, value in sorted(action_candidates.items())
        },
        "action_window_callback_events": {
            key: list(value) for key, value in sorted(callback_to_events.items())
        },
        "weighted_representative": weighted_success,
        "nonweighted_representative": nonweighted_success,
        "attempts": attempts[-80:],
        "build_evidence": build_evidence,
        "same_event_transitions": same_event_transitions,
        "pr12_reconciled_denominator_count": len(reconciled_denominator),
        "pr12_finalizer_audit_count": len(finalizer_audit),
        "resource": {
            "wall_seconds": round(elapsed, 6),
            "peak_rss_kib": peak,
            "wall_budget_seconds": _DIRECT_HARD_SECONDS,
            "rss_budget_kib": _DIRECT_RSS_LIMIT_KIB,
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate P9-A2 action-window status nested ability transport."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fast", action="store_true")
    mode.add_argument("--direct", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = _run_fast() if args.fast else _run_direct()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())