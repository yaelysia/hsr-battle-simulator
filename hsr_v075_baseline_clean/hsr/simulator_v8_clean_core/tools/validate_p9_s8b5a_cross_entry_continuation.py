from __future__ import annotations

import argparse
import hashlib
import json
import resource
import time
from pathlib import Path
from typing import Any

from ..core.model import BattleState, Mutation
from ..ir_types import IRSource
from ..rules.task_graph import TaskGraphIR, TaskGraphNodeIR
from ..rules.task_graph import task_graph_entry_id, task_graph_id, task_graph_node_id
from ..rules.task_graph import task_graph_source_occurrence_id
from ..systems.task_graph import TaskGraphContinuation, TaskGraphExecutionContext
from ..systems.task_graph import TaskGraphExecutionHooks, TaskGraphExecutor, TaskGraphHookRequest
from ..systems.task_graph import TaskGraphLeafResult, TaskGraphNodeProjection


SHA = "b" * 64


def _graph(name: str) -> TaskGraphIR:
    family = f"Fixture{name}"
    source = IRSource("validation_fixture/cross_entry.json", name, name, {
        "json_path": f"$.{name}", "content_sha256": SHA, "source_opcode": family,
    })
    entry = task_graph_entry_id("ability_phase_callback", f"owner:{name}", "OnStart")
    graph_id = task_graph_id("validation_fixture_catalog", entry, SHA)
    occurrence = task_graph_source_occurrence_id(source, family)
    node_id = task_graph_node_id(graph_id, f"task:{name}", occurrence)
    node = TaskGraphNodeIR(
        node_id,
        graph_id,
        occurrence,
        "",
        f"task:{name}",
        family,
        family,
        "leaf",
        (),
        (),
        "not_applicable",
        "not_applicable",
        "",
        "materialized",
        ("task_graph_execution",),
        source,
    )
    return TaskGraphIR(
        graph_id, entry, "ability_phase_callback", f"owner:{name}", "OnStart",
        (node_id,), (node,), (), "validation_fixture_catalog", SHA, source, "lowered",
    )


def _execution_id(graph_id: str, node_id: str, path: tuple[str, ...]) -> str:
    raw = json.dumps(
        (graph_id, node_id, *path), ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    return f"task_graph_execution:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _mutation(state: BattleState) -> Mutation:
    return Mutation(
        "set", ("global_flags", "forbidden_commit"),
        state.global_flags.get("forbidden_commit"), 1,
        "validation fixture", "validation_fixture",
        "forbidden_commit" in state.global_flags, True,
        mutation_id="mutation:forbidden_commit",
    )


def _raises(function: Any, expected: type[BaseException]) -> bool:
    try:
        function()
    except expected:
        return True
    return False


def _blocked(reason: str) -> TaskGraphLeafResult:
    return TaskGraphLeafResult("blocked", outcome_kind="", blocked_reason=reason)


def _run() -> tuple[dict[str, bool], dict[str, Any]]:
    state, executor, graph_a, graph_b = BattleState(), TaskGraphExecutor(), _graph("A"), _graph("B")
    external = {"nested": [1]}
    context = TaskGraphExecutionContext("outer", external)
    external["nested"].append(2)
    captured: list[tuple[TaskGraphHookRequest, TaskGraphContinuation]] = []

    def success_leaf(request: TaskGraphHookRequest, current: BattleState) -> TaskGraphLeafResult:
        if request.graph_id == graph_b.graph_id:
            return TaskGraphLeafResult("resolved")
        continuation = TaskGraphContinuation.from_hook_request(request)
        captured.append((request, continuation))
        child = executor.execute(
            current,
            graph_b,
            continuation.child_context("child:B"),
            TaskGraphExecutionHooks(leaf=success_leaf),
        )
        return (
            TaskGraphLeafResult(
                "resolved", child_projections=(*child.node_projections, *child.node_projections)
            )
            if child.ok
            else _blocked(child.errors[0])
        )

    success = executor.execute(
        state, graph_a, context, TaskGraphExecutionHooks(leaf=success_leaf)
    )
    request, continuation = captured[0]
    malformed_request_rejected = _raises(
        lambda: TaskGraphHookRequest(
            "fake", "graph", "node", "task", "opcode", "family", (), {}, ("other",), (), (), None
        ),
        ValueError,
    )
    direct_construction_rejected = _raises(lambda: TaskGraphContinuation(), TypeError)
    immutable = _raises(
        lambda: setattr(continuation, "parent_graph_id", "changed"), Exception
    ) and list(continuation.context_values["nested"]) == [1]

    def direct_leaf(request: TaskGraphHookRequest, current: BattleState) -> TaskGraphLeafResult:
        nested = executor.execute(
            current,
            graph_a,
            TaskGraphContinuation.from_hook_request(request).child_context("direct-cycle"),
            TaskGraphExecutionHooks(leaf=direct_leaf),
        )
        return _blocked(nested.errors[0])

    direct = executor.execute(
        state, graph_a, TaskGraphExecutionContext("direct"), TaskGraphExecutionHooks(leaf=direct_leaf)
    )

    def indirect_leaf(request: TaskGraphHookRequest, current: BattleState) -> TaskGraphLeafResult:
        nested_graph = graph_b if request.graph_id == graph_a.graph_id else graph_a
        nested = executor.execute(
            current,
            nested_graph,
            TaskGraphContinuation.from_hook_request(request).child_context(
                f"indirect:{nested_graph.owner_id}"
            ),
            TaskGraphExecutionHooks(leaf=indirect_leaf),
        )
        return TaskGraphLeafResult("resolved", child_projections=nested.node_projections) if nested.ok else _blocked(nested.errors[0])

    indirect = executor.execute(
        state,
        graph_a,
        TaskGraphExecutionContext("indirect"),
        TaskGraphExecutionHooks(leaf=indirect_leaf),
    )

    def conflict_leaf(request: TaskGraphHookRequest, current: BattleState) -> TaskGraphLeafResult:
        path = (f"invocation:{request.invocation_id}", "root:0")
        forged = TaskGraphNodeProjection(
            _execution_id(request.graph_id, request.graph_node_id, path),
            request.graph_id,
            request.graph_node_id,
            "task:forged",
            path,
            "complete",
        )
        return TaskGraphLeafResult(
            "resolved", mutations=(_mutation(current),), child_projections=(forged,)
        )

    conflict = executor.execute(
        state,
        graph_a,
        TaskGraphExecutionContext("conflict"),
        TaskGraphExecutionHooks(leaf=conflict_leaf),
    )
    child_projection = next(item for item in success.node_projections if item.graph_id == graph_b.graph_id)
    blocked_leak_rejected = _raises(
        lambda: TaskGraphLeafResult(
            "blocked",
            outcome_kind="",
            blocked_reason="fixture_blocked",
            child_projections=(child_projection,),
        ),
        ValueError,
    )
    no_channels = lambda result: (
        result.after_state is result.before_state
        and not result.mutations
        and not result.events
        and not result.rng_events
        and not result.settlement_records
    )
    predicates = {
        "continuation_is_derived_from_typed_hook_request": direct_construction_rejected
        and malformed_request_rejected
        and continuation.parent_invocation_id == request.invocation_id
        and continuation.parent_graph_id == request.graph_id
        and continuation.parent_graph_node_id == request.graph_node_id
        and continuation.parent_formal_task_id == request.formal_task_id,
        "continuation_is_recursively_immutable": immutable
        and continuation.child_context("immutable-child").active_graph_stack == (graph_a.graph_id,),
        "direct_and_indirect_cycles_fail_before_mutation": not direct.ok
        and not indirect.ok
        and no_channels(direct)
        and no_channels(indirect)
        and all("task_graph_active_cycle" in item.errors[0] for item in (direct, indirect)),
        "child_projections_are_graph_qualified": success.ok
        and {item.graph_id for item in success.node_projections} == {graph_a.graph_id, graph_b.graph_id}
        and len(success.node_projections) == 2,
        "projection_identity_conflict_is_atomic": not conflict.ok
        and no_channels(conflict)
        and "task_graph_child_projection_identity_conflict" in conflict.errors[0]
        and all(item.status == "blocked" for item in conflict.node_projections),
        "blocked_leaf_cannot_leak_child_projection": blocked_leak_rejected,
    }
    details = {
        "success_projection_ids": [item.execution_id for item in success.node_projections],
        "direct_cycle_error": direct.errors[0],
        "indirect_cycle_error": indirect.errors[0],
        "conflict_error": conflict.errors[0],
        "full_canonical_ir_build_count": 0,
    }
    return predicates, details


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    predicates, details = _run()
    elapsed = time.perf_counter() - started
    summary = {
        "ok": all(predicates.values()),
        "predicates": predicates,
        "manual_review_required": ["domain_consumers_changed"],
        "details": details,
        "elapsed_seconds": elapsed,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "validation_summary_p9_s8b5a.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
