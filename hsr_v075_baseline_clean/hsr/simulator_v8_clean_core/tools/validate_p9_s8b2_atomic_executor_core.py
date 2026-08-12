from __future__ import annotations

import argparse
import json
import resource
import time
from pathlib import Path
from typing import Any, Callable

from ..core.model import BattleState, GameEvent, Mutation, RNGEvent
from ..ir_types import IRSource
from ..rules.expression_ir import numeric_fixed
from ..rules.task_graph import (
    TaskGraphBranchIR,
    TaskGraphDefinitionReferenceIR,
    TaskGraphIR,
    TaskGraphNodeIR,
    TaskGraphNumericDefinitionIR,
    task_graph_branch_id,
    task_graph_entry_id,
    task_graph_id,
    task_graph_node_id,
    task_graph_numeric_id,
    task_graph_reference_id,
    task_graph_source_occurrence_id,
)
from ..systems.task_graph import (
    TaskGraphBranchResult,
    TaskGraphConditionResult,
    TaskGraphCountResult,
    TaskGraphExecutionContext,
    TaskGraphExecutionHooks,
    TaskGraphExecutor,
    TaskGraphGraphResult,
    TaskGraphLeafResult,
    TaskGraphSettlementRecord,
    TaskGraphTargetResult,
)


MAX_LINES = 390
SHA = "a" * 64


def _source(name: str, family: str) -> IRSource:
    return IRSource(
        "validation_fixture/task_graph.json",
        name,
        name,
        {"json_path": f"$.{name}", "content_sha256": SHA, "source_opcode": family},
    )


def _graph(name: str, specs: dict[str, dict[str, Any]], roots: tuple[str, ...]) -> TaskGraphIR:
    entry = task_graph_entry_id("ability_phase_callback", f"owner:{name}", "OnStart")
    graph_id = task_graph_id("validation_fixture_catalog", entry, SHA)
    sources = {key: _source(f"{name}:{key}", f"family:{key}") for key in specs}
    occurrences = {
        key: task_graph_source_occurrence_id(sources[key], f"family:{key}") for key in specs
    }
    node_ids = {
        key: task_graph_node_id(graph_id, f"task:{key}", occurrences[key]) for key in specs
    }
    numeric: list[TaskGraphNumericDefinitionIR] = []
    nodes: list[TaskGraphNodeIR] = []
    for key, spec in specs.items():
        source, node_id = sources[key], node_ids[key]
        branches = tuple(
            TaskGraphBranchIR(
                task_graph_branch_id(
                    node_id, kind, index, label, tuple(node_ids[item] for item in children)
                ),
                node_id,
                kind,
                index,
                label,
                tuple(node_ids[item] for item in children),
                source,
            )
            for index, (kind, label, children) in enumerate(spec.get("branches", ()))
        )
        refs = []
        for kind, definition_id in spec.get("refs", ()):
            refs.append(
                TaskGraphDefinitionReferenceIR(
                    task_graph_reference_id(node_id, kind, definition_id),
                    node_id,
                    kind,
                    definition_id,
                    definition_id if kind == "template" else "",
                    "resolved",
                    "task_graph_execution",
                    source,
                )
            )
        termination = spec.get("termination", "not_applicable")
        numeric_id = ""
        if termination in {"count_expression", "condition_with_source_cap"}:
            expression = numeric_fixed(float(spec.get("count", 2)))
            numeric_id = task_graph_numeric_id(occurrences[key], expression)
            numeric.append(TaskGraphNumericDefinitionIR(numeric_id, occurrences[key], expression, source))
            refs.append(
                TaskGraphDefinitionReferenceIR(
                    task_graph_reference_id(node_id, "numeric", numeric_id),
                    node_id,
                    "numeric",
                    numeric_id,
                    "",
                    "resolved",
                    "task_graph_execution",
                    source,
                )
            )
        deferred = spec.get("deferred", False)
        nodes.append(
            TaskGraphNodeIR(
                node_id,
                graph_id,
                occurrences[key],
                "",
                f"task:{key}",
                f"opcode:{key}",
                f"family:{key}",
                "deferred" if deferred else spec["kind"],
                branches,
                tuple(refs),
                termination,
                {
                    "not_applicable": "not_applicable",
                    "count_expression": "source_backed",
                    "condition_with_source_cap": "source_backed",
                    "condition_progress_required": "runtime_proof_required",
                    "finite_target_collection": "source_backed",
                }[termination],
                numeric_id,
                "deferred" if deferred else "materialized",
                ("hit_random_sequence",) if deferred else ("task_graph_execution",),
                source,
                "requires_hit_random_sequence" if deferred else "",
            )
        )
    return TaskGraphIR(
        graph_id,
        entry,
        "ability_phase_callback",
        f"owner:{name}",
        "OnStart",
        tuple(node_ids[item] for item in roots),
        tuple(nodes),
        tuple(numeric),
        "validation_fixture_catalog",
        SHA,
        sources[roots[0]],
        "lowered_with_obligation" if any(item.get("deferred") for item in specs.values()) else "lowered",
    )


def _mutation(state: BattleState, key: str, value: int) -> Mutation:
    exists = key in state.global_flags
    return Mutation(
        "set",
        ("global_flags", key),
        state.global_flags.get(key),
        value,
        "validation fixture",
        "validation_fixture",
        exists,
        True,
        mutation_id=f"mutation:{key}:{value}",
    )


def _blocked(reason: str) -> TaskGraphLeafResult:
    return TaskGraphLeafResult("blocked", outcome_kind="", blocked_reason=reason)


def _run() -> tuple[dict[str, bool], dict[str, Any]]:
    state, executor = BattleState(), TaskGraphExecutor()
    context = TaskGraphExecutionContext("fixture:invocation", {"mode": "focused"})
    external_payload = {"value": [1]}
    simple = _graph("simple", {"one": {"kind": "leaf"}}, ("one",))

    def successful_leaf(_request: Any, current: BattleState) -> TaskGraphLeafResult:
        mutation = _mutation(current, "one", 1)
        return TaskGraphLeafResult(
            "resolved",
            (mutation,),
            (GameEvent("fixture_event", event_id="event:one", payload=external_payload),),
            (RNGEvent("fixture_rng", "validation_fixture", 1, event_id="rng:one"),),
            (TaskGraphSettlementRecord("fixture", "validation_fixture", mutation.stable_id()),),
        )

    simple_result = executor.execute(
        state, simple, context, TaskGraphExecutionHooks(leaf=successful_leaf)
    )
    external_payload["value"].append(2)
    rollback = _graph(
        "rollback",
        {
            "first": {"kind": "sequence", "branches": (("task_list", "", ("second",)),)},
            "second": {"kind": "leaf"},
        },
        ("first",),
    )

    def rollback_leaf(request: Any, current: BattleState) -> TaskGraphLeafResult:
        if request.formal_task_id == "task:second":
            return _blocked("fixture_second_leaf_blocked")
        return TaskGraphLeafResult(
            "resolved", (_mutation(current, "first", 1),), outcome_kind="task_list"
        )

    rollback_result = executor.execute(
        state, rollback, context, TaskGraphExecutionHooks(leaf=rollback_leaf)
    )
    branch = _graph(
        "branch",
        {
            "choose": {"kind": "branch", "branches": (("success", "", ("good",)), ("failed", "", ("later",)))},
            "good": {"kind": "leaf"},
            "later": {"kind": "leaf", "deferred": True},
            "switch": {"kind": "branch", "branches": (("case", "one", ("case_good",)), ("default", "", ("case_later",)))},
            "case_good": {"kind": "leaf"},
            "case_later": {"kind": "leaf", "deferred": True},
        },
        ("choose", "switch"),
    )
    branch_result = executor.execute(
        state,
        branch,
        context,
        TaskGraphExecutionHooks(
            leaf=lambda _r, _s: TaskGraphLeafResult("resolved"),
            condition=lambda _r, _s: TaskGraphConditionResult("resolved", True),
            branch=lambda _r, _s: TaskGraphBranchResult("resolved", "case", "one"),
        ),
    )
    one_sided = _graph(
        "one_sided",
        {
            "root": {"kind": "sequence", "branches": (("effect_failed", "", ("trap",)),)},
            "trap": {"kind": "leaf"},
        },
        ("root",),
    )
    trap_calls: list[str] = []
    one_sided_result = executor.execute(
        state,
        one_sided,
        context,
        TaskGraphExecutionHooks(
            leaf=lambda request, _s: trap_calls.append(request.formal_task_id)
            or TaskGraphLeafResult("resolved")
        ),
    )
    calls: list[tuple[str, tuple[str, ...]]] = []

    def counted_leaf(request: Any, _state: BattleState) -> TaskGraphLeafResult:
        calls.append((request.formal_task_id, request.target_ids))
        return TaskGraphLeafResult("resolved")

    loop_specs = {
        "count": {"kind": "loop", "termination": "count_expression", "count": 2, "branches": (("task_list", "", ("count_body",)),)},
        "count_body": {"kind": "leaf"},
        "progress": {"kind": "loop", "termination": "condition_progress_required", "branches": (("task_list", "", ("progress_body",)),)},
        "progress_body": {"kind": "leaf"},
        "targets": {"kind": "loop", "termination": "finite_target_collection", "branches": (("task_list", "", ("target_body",)),)},
        "target_body": {"kind": "leaf"},
    }
    loops = _graph("loops", loop_specs, ("count", "progress", "targets"))
    progress = iter((2, 1, None))
    loop_result = executor.execute(
        state,
        loops,
        context,
        TaskGraphExecutionHooks(
            leaf=counted_leaf,
            count=lambda _r, _d, _s: TaskGraphCountResult("resolved", 2),
            condition=lambda _r, _s: (
                TaskGraphConditionResult("resolved", False)
                if (value := next(progress)) is None
                else TaskGraphConditionResult("resolved", True, value)
            ),
            targets=lambda _r, _s: TaskGraphTargetResult("resolved", ("u1", "u2")),
        ),
    )
    template = _graph(
        "template",
        {
            "include": {"kind": "template_call", "refs": (("template", "template:def"),), "branches": (("template_parameter_sequence", "p", ("parameter_body",)), ("template_body", "template:def", ("fetch",)))},
            "parameter_body": {"kind": "leaf"},
            "fetch": {"kind": "template_parameter", "branches": (("template_parameter_fetch", "p", ()),)},
        },
        ("include",),
    )
    template_calls: list[str] = []
    template_result = executor.execute(
        state,
        template,
        context,
        TaskGraphExecutionHooks(
            leaf=lambda request, _s: template_calls.append(request.formal_task_id) or TaskGraphLeafResult("resolved")
        ),
    )
    nested = _graph("nested", {"leaf": {"kind": "leaf"}}, ("leaf",))
    caller = _graph("caller", {"call": {"kind": "ability_call", "refs": (("ability", "nested:def"),)}}, ("call",))
    nested_result = executor.execute(
        state,
        caller,
        context,
        TaskGraphExecutionHooks(
            leaf=lambda _r, _s: TaskGraphLeafResult("resolved"),
            graph=lambda _r, _s: TaskGraphGraphResult("resolved", "nested:def", nested),
        ),
    )
    cycle_a = _graph("cycle_a", {"call": {"kind": "ability_call", "refs": (("ability", "cycle:b"),)}}, ("call",))
    cycle_b = _graph("cycle_b", {"call": {"kind": "ability_call", "refs": (("ability", "cycle:a"),)}}, ("call",))
    cycle_result = executor.execute(
        state,
        cycle_a,
        context,
        TaskGraphExecutionHooks(
            graph=lambda request, _s: (
                TaskGraphGraphResult("resolved", "cycle:b", cycle_b)
                if request.graph_id == cycle_a.graph_id
                else TaskGraphGraphResult("resolved", "cycle:a", cycle_a)
            )
        ),
    )
    deferred = _graph("deferred", {"later": {"kind": "leaf", "deferred": True}}, ("later",))
    deferred_result = executor.execute(state, deferred, context, TaskGraphExecutionHooks())
    duplicate_event = executor.execute(
        state, simple, context, TaskGraphExecutionHooks(leaf=lambda _r, _s: TaskGraphLeafResult(
            "resolved", events=(GameEvent("duplicate", event_id="event:duplicate"), GameEvent("duplicate", event_id="event:duplicate"))
        ))
    )
    invalid_field = executor.execute(
        state, simple, context, TaskGraphExecutionHooks(
            leaf=lambda _r, _s: TaskGraphLeafResult("resolved", outcome_kind=1)  # type: ignore[arg-type]
        )
    )
    bad_progress_calls: list[str] = []
    progress_only = _graph(
        "bad_progress",
        {"loop": {"kind": "loop", "termination": "condition_progress_required", "branches": (("task_list", "", ("body",)),)}, "body": {"kind": "leaf"}},
        ("loop",),
    )
    bad_progress = executor.execute(
        state,
        progress_only,
        context,
        TaskGraphExecutionHooks(
            condition=lambda _r, _s: TaskGraphConditionResult("resolved", True),
            leaf=lambda request, _s: bad_progress_calls.append(request.formal_task_id) or TaskGraphLeafResult("resolved"),
        ),
    )
    source = Path(__file__).parents[1] / "systems" / "task_graph.py"
    source_text = source.read_text(encoding="utf-8")
    loop_counts = {name: sum(item[0] == f"task:{name}" for item in calls) for name in ("count_body", "progress_body", "target_body")}
    all_projections = (*simple_result.node_projections, *loop_result.node_projections, *nested_result.node_projections)
    predicates = {
        "one_shared_executor_owns_control_flow": all(item.ok for item in (simple_result, branch_result, loop_result, template_result, nested_result)),
        "domain_hooks_cannot_execute_children": "child_node_ids" not in TaskGraphExecutionHooks.__annotations__ and "child_runner" not in source_text,
        "selected_path_failure_is_atomic": not rollback_result.ok and rollback_result.after_state is state and not rollback_result.mutations and not rollback_result.events and not rollback_result.rng_events and not rollback_result.settlement_records,
        "unselected_blocked_branch_does_not_preblock_selected_path": branch_result.ok and all(item.formal_task_id not in {"task:later", "task:case_later"} for item in branch_result.node_projections),
        "single_failure_branch_is_not_treated_as_unconditional": one_sided_result.ok and trap_calls == ["task:root"],
        "loop_termination_is_source_admitted": loop_counts == {"count_body": 2, "progress_body": 2, "target_body": 2} and not bad_progress.ok and not bad_progress_calls,
        "active_graph_cycle_fails_without_depth_cap": not cycle_result.ok and any("active_cycle" in item for item in cycle_result.errors),
        "executed_projections_are_graph_qualified": bool(all_projections) and len({item.execution_id for item in all_projections}) == len(all_projections) and all(item.graph_id and item.graph_node_id for item in all_projections),
        "s8c_control_kinds_remain_blocked": not deferred_result.ok and not deferred_result.mutations,
        "template_parameter_frame_is_lazy_and_exact": template_result.ok and template_calls == ["task:parameter_body"],
        "hook_outputs_are_frozen_and_linked": simple_result.ok and simple_result.events[0].payload["value"] == [1] and simple_result.settlement_records[0].mutation_id == simple_result.mutations[0].stable_id(),
        "duplicate_channel_identity_fails_atomically": not duplicate_event.ok and not duplicate_event.events,
        "hook_result_field_types_fail_closed": not invalid_field.ok and invalid_field.after_state is state,
        "source_scan_count": 0 if "..tbgd" not in source_text else 1,
    }
    facts = {"loop_body_counts": loop_counts, "projection_count": len(all_projections), "full_canonical_ir_build_count": 0, "source_scan_count": predicates["source_scan_count"]}
    return predicates, facts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    predicates, facts = _run()
    line_count = sum(bool(line.strip()) for line in Path(__file__).read_text(encoding="utf-8").splitlines())
    predicates["validator_within_budget"] = line_count <= MAX_LINES
    ok = all(
        (type(value) is bool and value)
        or (type(value) is int and value == 0)
        for value in predicates.values()
    )
    summary = {
        "stage": "P9-S8B2",
        "ok": ok,
        "predicates": predicates,
        "source_facts": facts,
        "manual_review_required": {"production_domain_consumers_changed": "git_diff_scope_review"},
        "resource": {
            "wall_seconds": round(time.perf_counter() - started, 6),
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "validator_nonblank_lines": line_count,
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    (args.output_dir / "validation_summary_p9_s8b2_atomic_executor_core.json").write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
