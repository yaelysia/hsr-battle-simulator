from __future__ import annotations

import argparse
import hashlib
import json
import resource
import time
from pathlib import Path
from typing import Any, cast

from ..core.model import BattleState, GameEvent, TargetResolution, UnitState
from ..ir_types import IRSource
from ..rules.ir import (
    AbilityPhaseIR, AbilityTaskIR, StatusCallbackIR, StatusCallbackTaskIR,
)
from ..rules.task_graph import (
    TaskGraphDefinitionReferenceIR,
    TaskGraphEntryMaterializationIR,
    TaskGraphIR,
    TaskGraphNodeIR,
    TaskGraphQueryResult,
    task_graph_entry_id,
    task_graph_id,
    task_graph_materialization_id,
    task_graph_node_id,
    task_graph_reference_id,
    task_graph_source_occurrence_id,
)
from ..systems.ability import AbilityTaskSystem, StandaloneAbilityInvocation, _FormalAbilityInvocation
from ..systems.ability_property_watchers import AbilityPropertyWatcherResult
from ..systems.event_dispatch import EventDispatchSystem, ListenerMatch
from ..systems.phase_machine import CombatPhaseMachine
from ..systems.status_callbacks import StatusCallbackExecutionResult, StatusCallbackSystem
from ..systems.task_graph import (
    TaskGraphContinuation,
    TaskGraphExecutionContext,
    TaskGraphExecutionHooks,
    TaskGraphExecutor,
    TaskGraphHookRequest,
    TaskGraphLeafResult,
    TaskGraphNodeProjection,
)

SHA = "c" * 64
CATALOG = "validation_fixture_cross_entry_runtime"


def _source(name: str, family: str, *, status: bool) -> IRSource:
    opcode_key = "raw_opcode" if status else "source_opcode"
    return IRSource(
        "validation_fixture/p9_s8b5c.json",
        name,
        name,
        {"json_path": f"$.{name}", "content_sha256": SHA, opcode_key: family},
    )


def _graph(
    entry_kind: str,
    owner_id: str,
    callback_kind: str,
    task_id: str,
    family: str,
    *,
    target_phase_id: str = "",
) -> tuple[TaskGraphIR, TaskGraphEntryMaterializationIR]:
    status = entry_kind == "status_callback"
    source = _source(task_id, family, status=status)
    entry_id = task_graph_entry_id(cast(Any, entry_kind), owner_id, callback_kind)
    graph_id = task_graph_id(CATALOG, entry_id, SHA)
    occurrence = task_graph_source_occurrence_id(source, family)
    node_id = task_graph_node_id(graph_id, task_id, occurrence)
    references = () if not target_phase_id else (TaskGraphDefinitionReferenceIR(
        task_graph_reference_id(node_id, "ability", target_phase_id), node_id,
        "ability", target_phase_id, "", "resolved", "task_graph_execution", source,
    ),)
    node = TaskGraphNodeIR(
        node_id, graph_id, occurrence, "", task_id, family, family,
        "ability_call" if target_phase_id else "leaf", (), references,
        "not_applicable", "not_applicable", "", "materialized",
        ("task_graph_execution",), source,
    )
    graph = TaskGraphIR(
        graph_id, entry_id, cast(Any, entry_kind), owner_id, callback_kind,
        (node_id,), (node,), (), CATALOG, SHA, source, "lowered",
    )
    entry = TaskGraphEntryMaterializationIR(
        task_graph_materialization_id(entry_id, (task_id,), (occurrence,)), entry_id,
        cast(Any, entry_kind), owner_id, callback_kind, graph_id, (task_id,),
        (occurrence,), "materialized", source,
    )
    return graph, entry


class _Rules:
    def __init__(self) -> None:
        self.callbacks: dict[str, StatusCallbackIR] = {}
        self.status_tasks: dict[str, StatusCallbackTaskIR] = {}
        self.phases: dict[str, AbilityPhaseIR] = {}
        self.ability_tasks: dict[str, AbilityTaskIR] = {}
        self.graphs: dict[str, TaskGraphIR] = {}
        self.entries: dict[str, TaskGraphEntryMaterializationIR] = {}
        self.nodes: dict[str, TaskGraphNodeIR] = {}

    def add_graph(
        self, graph: TaskGraphIR, entry: TaskGraphEntryMaterializationIR
    ) -> None:
        self.graphs[graph.graph_id] = graph
        self.entries[entry.entry_id] = entry
        self.nodes.update({node.graph_node_id: node for node in graph.nodes})

    @staticmethod
    def _query(kind: str, value: object | None, identity: str) -> TaskGraphQueryResult:
        if value is None:
            return TaskGraphQueryResult(
                "blocked", cast(Any, kind), (), None, f"fixture_{kind}_missing"
            )
        return TaskGraphQueryResult(
            "resolved", cast(Any, kind), (identity,), cast(Any, value), ""
        )

    def query_task_graph(self, graph_id: str) -> TaskGraphQueryResult:
        return self._query("graph", self.graphs.get(graph_id), graph_id)

    def query_task_graph_entry(self, kind: str, owner: str, callback: str) -> TaskGraphQueryResult:
        identity = task_graph_entry_id(cast(Any, kind), owner, callback)
        return self._query("entry", self.entries.get(identity), identity)

    def query_task_graph_node(self, node_id: str) -> TaskGraphQueryResult:
        return self._query("node", self.nodes.get(node_id), node_id)

    def status_callback(self, callback_id: str) -> StatusCallbackIR | None:
        return self.callbacks.get(callback_id)

    def status_callback_task(self, task_id: str) -> StatusCallbackTaskIR | None:
        return self.status_tasks.get(task_id)

    def ability_task(self, task_id: str) -> AbilityTaskIR | None:
        return self.ability_tasks.get(task_id)

    def status_callbacks_for_modifier_event(
        self, modifier: str, event: str
    ) -> tuple[StatusCallbackIR, ...]:
        return tuple(item for item in self.callbacks.values()
                     if item.modifier_name == modifier and item.event == event)

    def status_callback_tasks_for_callback(
        self, callback_id: str
    ) -> tuple[StatusCallbackTaskIR, ...]:
        return tuple(item for item in self.status_tasks.values()
                     if item.callback_id == callback_id)

    def ability_phase(self, phase_id: str) -> AbilityPhaseIR | None:
        return self.phases.get(phase_id)

    def ability_tasks_for_phase(self, phase_id: str) -> tuple[AbilityTaskIR, ...]:
        return tuple(item for item in self.ability_tasks.values() if item.phase_id == phase_id)

    @staticmethod
    def standalone_ability_graph(_graph_id: str) -> None:
        return None

    @staticmethod
    def status_event_families_for_runtime_event(_event: str) -> tuple[object, ...]:
        return ()

    @staticmethod
    def status_event_family(_event: str) -> None:
        return None


def _install_ability(rules: _Rules, name: str) -> TaskGraphIR:
    phase_id, task_id = f"phase:{name}", f"ability_task:{name}"
    source = _source(task_id, f"Ability{name}", status=False)
    rules.ability_tasks[task_id] = AbilityTaskIR(
        task_id, phase_id, f"action:{name}", 1, f"Ability{name}", "OnStart", 0,
        f"$.{name}", "", f"Ability{name}", source, execution_mode="process_only",
        coverage_status="executable",
    )
    rules.phases[phase_id] = AbilityPhaseIR(
        phase_id, f"binding:{name}", f"action:{name}", 1, f"Ability{name}", 0,
        {}, {}, {}, source, "executable", task_ids=(task_id,), invocation_role="nested_only",
    )
    graph, entry = _graph("ability_phase_callback", phase_id, "OnStart",
                          task_id, f"Ability{name}")
    rules.add_graph(graph, entry)
    return graph


def _install_callback(
    rules: _Rules, name: str, target_phase_id: str, *, executable: bool = True
) -> tuple[StatusCallbackIR, dict[str, Any], TaskGraphIR | None]:
    callback_id, task_id = f"callback:{name}", f"status_task:{name}"
    source = _source(task_id, "TriggerAbility", status=True)
    coverage, reason = (
        ("executable", "") if executable else ("blocked", "fixture_blocked_callback")
    )
    callback = StatusCallbackIR(
        callback_id, f"Modifier{name}", "OnEnterBattle", (task_id,), source,
        (0, 0), coverage, reason, "status_local", "mainline_avatar_ability", coverage,
    )
    rules.callbacks[callback_id] = callback
    graph = None
    if executable:
        task = StatusCallbackTaskIR(
            task_id, callback_id, callback.modifier_name, callback.event, 0,
            f"$.{name}", "", "TriggerAbility", source, coverage_status="executable",
            linked_ability_phase_id=target_phase_id,
        )
        rules.status_tasks[task_id] = task
        graph, entry = _graph("status_callback", callback_id, callback.event,
                              task_id, "TriggerAbility", target_phase_id=target_phase_id)
        rules.add_graph(graph, entry)
    detail = {
        "instance_id": f"status:{name}", "status_id": f"status:{name}",
        "owner_id": "owner", "caster_id": "owner", "modifier_name": callback.modifier_name,
        "trigger_ids_by_event": {callback.event: [callback_id]},
        "source_trace": {"kind": "validation_fixture", "callback_id": callback_id},
    }
    return callback, detail, graph


class _Watchers:
    def __init__(self) -> None:
        self.transports: list[tuple[object, object]] = []
        self.fail = False

    def reconcile(self, state: BattleState, **kwargs: object) -> AbilityPropertyWatcherResult:
        self.transports.append((kwargs.get("task_graph_continuation"), kwargs.get("nested_ability_hooks")))
        if self.fail:
            return AbilityPropertyWatcherResult(False, state, errors=("fixture_watcher_blocked",))
        return AbilityPropertyWatcherResult(True, state)


class _StatusCallbacks(StatusCallbackSystem):
    def __init__(self, rules: _Rules) -> None:
        self.rules = cast(Any, rules)
        self.task_graph_executor = TaskGraphExecutor()


class _Dispatcher(EventDispatchSystem):
    def __init__(self, rules: _Rules, callbacks: StatusCallbackSystem, details: dict[str, dict[str, Any]]) -> None:
        self.rules = cast(Any, rules)
        self.status_callbacks = callbacks
        self.phases = CombatPhaseMachine()
        self.ability_property_watchers = _Watchers()
        self.details = details

    def _resolve_listener_matches(self, _state: BattleState, *, event: GameEvent, **_kwargs: object) -> tuple[ListenerMatch, ...]:
        callback_ids = tuple(event.payload.get("fixture_callback_ids") or ())
        return tuple(
            ListenerMatch(
                "status_callback", "owner_local", callback.event, "owner",
                callback.modifier_name, callback, detail["instance_id"],
                status_detail=detail,
            )
            for callback_id in callback_ids
            if (callback := self.rules.status_callback(str(callback_id))) is not None
            and (detail := self.details.get(str(callback_id))) is not None
        )


class _ProbeAbility(AbilityTaskSystem):
    def __init__(self, rules: _Rules, dispatcher: _Dispatcher, callback_id: str) -> None:
        self.rules = cast(Any, rules)
        self.dispatcher = dispatcher
        self.callback_id = callback_id
        self.captured: tuple[TaskGraphContinuation, TaskGraphExecutionHooks] | None = None

    def _execute_formal_leaf_task(self, state: BattleState, _task: AbilityTaskIR, **kwargs: object):
        continuation = cast(TaskGraphContinuation, kwargs["task_graph_continuation"])
        hooks = cast(TaskGraphExecutionHooks, kwargs["nested_ability_hooks"])
        if _task.task_id != "ability_task:A":
            return state, [], [], [], [], []
        self.captured = continuation, hooks
        result = self.dispatcher.dispatch_event(
            state, event=_event((self.callback_id,), "event:ability-probe"),
            task_graph_continuation=continuation, nested_ability_hooks=hooks,
        )
        return (result.after_state, list(result.mutations), list(result.events),
                list(result.rng_events), list(result.records),
                list(result.task_graph_projections))


def _event(callback_ids: tuple[str, ...], identity: str) -> GameEvent:
    return GameEvent(
        "battle.start", "owner", "owner", identity, payload={
            "fixture_callback_ids": list(callback_ids), "param_entity_id": "owner",
        }
    )


def _execution_id(graph: TaskGraphIR, request: TaskGraphHookRequest) -> str:
    path = (f"invocation:{request.invocation_id}", "root:0")
    raw = json.dumps(
        (graph.graph_id, graph.root_node_ids[0], *path),
        ensure_ascii=True, sort_keys=True, separators=(",", ":"),
    )
    return f"task_graph_execution:{hashlib.sha256(raw.encode()).hexdigest()}"


def _run() -> tuple[dict[str, bool], dict[str, Any]]:
    rules = _Rules()
    graph_a, graph_b = _install_ability(rules, "A"), _install_ability(rules, "B")
    callback_c, detail_c, _ = _install_callback(rules, "C", "phase:B")
    callback_d, detail_d, _ = _install_callback(rules, "D", "phase:A")
    callback_e, detail_e, _ = _install_callback(rules, "E", "phase:B", executable=False)
    details = {item["source_trace"]["callback_id"]: item for item in (detail_c, detail_d, detail_e)}
    state = BattleState(units={
        "owner": UnitState(
            "owner", "ally", "avatar:fixture",
            statuses=tuple(f"modifier:{item['modifier_name']}" for item in details.values()),
            flags={"status_details": tuple(details.values())},
        )
    })
    status = _StatusCallbacks(rules)
    dispatcher = _Dispatcher(rules, status, details)
    executor = TaskGraphExecutor()

    probe = _ProbeAbility(rules, dispatcher, callback_c.callback_id)
    standalone = StandaloneAbilityInvocation("probe", "owner", ("owner",), "q", "e", "i", "r")
    invocation = _FormalAbilityInvocation(
        "queue_standalone", "owner", "probe", 0,
        TargetResolution(selected=("owner",), primary="owner"), standalone=standalone,
    )
    ability_probe = executor.execute(
        state, graph_a, TaskGraphExecutionContext("ability-probe"),
        TaskGraphExecutionHooks(
            leaf=lambda request, current: probe._execute_formal_leaf(
                request, current, invocation=invocation
            )
        ),
    )

    mode = "success"
    outer_request: TaskGraphHookRequest | None = None
    nested_hooks: TaskGraphExecutionHooks

    def nested_leaf(request: TaskGraphHookRequest, current: BattleState) -> TaskGraphLeafResult:
        nonlocal mode
        if mode == "indirect" and request.graph_id == graph_b.graph_id:
            result = dispatcher.dispatch_event(
                current, event=_event((callback_d.callback_id,), "event:indirect"),
                task_graph_continuation=TaskGraphContinuation.from_hook_request(request),
                nested_ability_hooks=nested_hooks,
            )
            if result.errors:
                return TaskGraphLeafResult("blocked", outcome_kind="", blocked_reason=result.errors[0])
            return TaskGraphLeafResult("resolved", child_projections=result.task_graph_projections)
        if mode == "conflict" and outer_request is not None:
            path = (f"invocation:{outer_request.invocation_id}", "root:0")
            forged = TaskGraphNodeProjection(
                _execution_id(graph_a, outer_request), graph_a.graph_id,
                graph_a.root_node_ids[0], "ability_task:forged", path, "complete",
            )
            return TaskGraphLeafResult("resolved", child_projections=(forged,))
        return TaskGraphLeafResult("resolved")

    nested_hooks = TaskGraphExecutionHooks(leaf=nested_leaf)

    def run(callback_ids: tuple[str, ...], selected_mode: str):
        nonlocal mode, outer_request
        mode, outer_request = selected_mode, None

        def outer_leaf(request: TaskGraphHookRequest, current: BattleState) -> TaskGraphLeafResult:
            nonlocal outer_request
            outer_request = request
            result = dispatcher.dispatch_event(
                current, event=_event(callback_ids, f"event:{selected_mode}"),
                task_graph_continuation=TaskGraphContinuation.from_hook_request(request),
                nested_ability_hooks=nested_hooks,
            )
            if result.errors:
                return TaskGraphLeafResult("blocked", outcome_kind="", blocked_reason=result.errors[0])
            return TaskGraphLeafResult(
                "resolved", events=result.events,
                child_projections=result.task_graph_projections,
            )

        return executor.execute(
            state, graph_a, TaskGraphExecutionContext(f"outer:{selected_mode}"),
            TaskGraphExecutionHooks(leaf=outer_leaf),
        )

    success = ability_probe
    direct = run((callback_d.callback_id,), "direct")
    indirect = run((callback_c.callback_id,), "indirect")
    conflict = run((callback_c.callback_id,), "conflict")
    grouped_failure = run((callback_c.callback_id, callback_e.callback_id), "group_failure")
    dispatcher.ability_property_watchers.fail = True
    watcher_failure = run((callback_c.callback_id,), "watcher_failure")
    dispatcher.ability_property_watchers.fail = False
    invalid_transport = dispatcher.dispatch_event(
        state, event=_event((callback_c.callback_id,), "event:invalid"),
        task_graph_continuation=cast(Any, object()),
    )
    sample_projection = next(item for item in success.node_projections if item.graph_id == graph_b.graph_id)
    result_guard = False
    try:
        StatusCallbackExecutionResult(
            False, state, errors=("blocked",), task_graph_projections=(sample_projection,)
        )
    except ValueError:
        result_guard = True

    no_channels = lambda result: result.after_state is result.before_state \
        and not (result.mutations or result.events or result.rng_events \
                 or result.settlement_records)
    no_child_projection = lambda result: bool(result.node_projections) and all(
        item.graph_id == graph_a.graph_id and item.status == "blocked"
        for item in result.node_projections
    )
    captured = probe.captured
    success_graphs = {item.graph_id for item in success.node_projections}
    predicates = {
        "ability_leaf_derives_and_transports_exact_continuation": ability_probe.ok and captured is not None
        and type(captured[0]) is TaskGraphContinuation
        and type(captured[1]) is TaskGraphExecutionHooks,
        "active_graph_stack_survives_synchronous_cross_entry_calls": success.ok and success_graphs == {
            graph_a.graph_id, graph_b.graph_id, rules.entries[task_graph_entry_id(
                "status_callback", callback_c.callback_id, callback_c.event
            )].graph_id
        } and bool(dispatcher.ability_property_watchers.transports)
        and all(type(item[0]) is TaskGraphContinuation for item in dispatcher.ability_property_watchers.transports),
        "direct_and_indirect_graph_cycles_fail_before_mutation": not direct.ok and not indirect.ok
        and no_channels(direct) and no_channels(indirect)
        and no_child_projection(direct) and no_child_projection(indirect)
        and all("task_graph_active_cycle" in item.errors[0] for item in (direct, indirect)),
        "executed_projections_are_graph_qualified_and_conflict_checked": not conflict.ok and no_channels(conflict)
        and no_child_projection(conflict) and "task_graph_child_projection_identity_conflict" in conflict.errors[0],
        "failed_transactions_publish_no_successful_child_projection": not grouped_failure.ok
        and not watcher_failure.ok and no_channels(grouped_failure) and no_channels(watcher_failure)
        and no_child_projection(grouped_failure) and no_child_projection(watcher_failure)
        and result_guard,
        "cross_entry_context_reconstruction_count_is_zero": bool(captured)
        and dispatcher.ability_property_watchers.transports[0] == captured,
        "status_trigger_ability_uses_typed_nested_graph": success.ok and graph_b.graph_id in success_graphs,
        "invalid_transport_is_rejected_before_execution": bool(invalid_transport.errors)
        and invalid_transport.after_state is state and not invalid_transport.task_graph_projections,
    }
    return predicates, {
        "success_projection_graph_ids": sorted(success_graphs),
        "direct_cycle_error": direct.errors[0],
        "indirect_cycle_error": indirect.errors[0],
        "conflict_error": conflict.errors[0],
        "group_failure_error": grouped_failure.errors[0],
        "watcher_failure_error": watcher_failure.errors[0],
        "full_canonical_ir_build_count": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    predicates, details = _run()
    summary = {
        "ok": all(predicates.values()),
        "predicates": predicates,
        "manual_review_required": {
            "s8c_s9_s10_obligations_remain_precise_and_unexecuted": True,
            "real_character_end_to_end_executed": False,
        },
        "details": details,
        "elapsed_seconds": time.perf_counter() - started,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "validation_summary_p9_s8b5c.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
