from __future__ import annotations

import argparse
import ast
import json
import resource
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
BASELINE_ROOT = REPO_ROOT / "hsr_v075_baseline_clean"
CORE_ROOT = BASELINE_ROOT / "hsr" / "simulator_v8_clean_core"
TBGD_ROOT = REPO_ROOT / "turnbasedgamedata-main"
BASE_SHA = "bd1a4ac94ca394d2ea563d086eaf56e9ed45b285"
LOWERING_PATH = (
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py"
)

if str(BASELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(BASELINE_ROOT))

from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering,
    _finalize_action_window_status_callback_admission,
)


def _fail(message: str) -> None:
    raise AssertionError(message)


def _function_ast(source: str, function_name: str) -> str:
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return ast.dump(node, include_attributes=False)
    _fail(f"function missing:{function_name}")


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=REPO_ROOT, text=True, stderr=subprocess.STDOUT
    )


def _assert_governance_guards() -> None:
    current = (REPO_ROOT / LOWERING_PATH).read_text(encoding="utf-8")
    baseline = _git("show", f"{BASE_SHA}:{LOWERING_PATH}")
    for name in ("_link_trigger_ability_graphs", "_link_status_trigger_ability_graphs"):
        if _function_ast(current, name) != _function_ast(baseline, name):
            _fail(f"existing_link_authority_changed:{name}")

    changed = tuple(
        line.strip()
        for line in _git("diff", "--name-only", BASE_SHA, "HEAD").splitlines()
        if line.strip()
    )
    forbidden_prefixes = (
        "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/",
        "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/core/",
        "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/",
    )
    forbidden_exact = (
        "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py",
    )
    bad = [path for path in changed if path.startswith(forbidden_prefixes) or path in forbidden_exact]
    if bad:
        _fail("forbidden_runtime_or_rule_change:" + ",".join(bad))

    diff = _git("diff", "--unified=0", BASE_SHA, "HEAD", "--", LOWERING_PATH)
    added = "\n".join(
        line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")
    )
    for token in ("RandomConfig", "weighted_selection", "weighted-selection", "rng", "RNG"):
        if token in added:
            _fail(f"pr9_rng_scope_leak:{token}")


@dataclass(frozen=True)
class _Source:
    source_path: str


@dataclass(frozen=True)
class _Callback:
    callback_id: str
    modifier_name: str
    event: str
    task_ids: tuple[str, ...]
    source: _Source
    coverage_status: str
    blocked_reason: str
    scope_kind: str
    source_mode: str
    admission_status: str
    blocking_dependency: str


@dataclass(frozen=True)
class _Task:
    task_id: str
    callback_id: str
    event: str
    opcode: str
    effect_id: str
    source: _Source
    coverage_status: str
    blocked_reason: str
    linked_standalone_graph_id: str = ""
    linked_ability_phase_id: str = ""


@dataclass(frozen=True)
class _Family:
    callback_event: str
    runtime_event_sources: tuple[str, ...]
    coverage_status: str = "executable"
    blocked_reason: str = ""
    admission_status: str = "executable"


@dataclass(frozen=True)
class _Effect:
    effect_id: str
    opcode: str
    payload: dict[str, Any]
    source: _Source
    coverage_status: str = "executable"
    blocked_reason: str = ""


@dataclass(frozen=True)
class _Graph:
    standalone_ability_graph_id: str
    ability_name: str
    phase_ids: tuple[str, ...]
    source: _Source
    source_mode: str = "mainline_avatar"
    coverage_status: str = "executable"
    blocked_reason: str = ""


@dataclass(frozen=True)
class _Phase:
    phase_id: str
    ability_name: str
    binding_id: str
    source: _Source
    coverage_status: str = "executable"
    blocked_reason: str = ""


def _fixture(
    *,
    callback_id: str = "callback:1",
    task_id: str = "task:1",
    event: str = "OnAfterAttack",
    source_path: str = "Config/ConfigAbility/Avatar/Test.json",
    callback_reason: str | None = None,
    task_reason: str | None = None,
    source_mode: str = "mainline_avatar_ability",
    link_graph: str = "graph:1",
    link_phase: str = "",
    family_sources: tuple[str, ...] = ("action.window.after_attack", "action.after_attack"),
    family_status: str = "executable",
) -> tuple[list[_Callback], list[_Task], list[_Family], list[_Effect], list[_Graph], list[_Phase], set[str]]:
    stale = f"status_callback_event_not_admitted:{event}"
    callback_reason = stale if callback_reason is None else callback_reason
    task_reason = stale if task_reason is None else task_reason
    source = _Source(source_path)
    callback = _Callback(
        callback_id=callback_id,
        modifier_name="Modifier",
        event=event,
        task_ids=(task_id,),
        source=source,
        coverage_status="blocked" if callback_reason else "executable",
        blocked_reason=callback_reason,
        scope_kind="owner",
        source_mode=source_mode,
        admission_status="blocked" if callback_reason else "executable",
        blocking_dependency=callback_reason,
    )
    task = _Task(
        task_id=task_id,
        callback_id=callback_id,
        event=event,
        opcode="TriggerAbility",
        effect_id="effect:1",
        source=source,
        coverage_status="blocked" if task_reason else "executable",
        blocked_reason=task_reason,
        linked_standalone_graph_id=link_graph,
        linked_ability_phase_id=link_phase,
    )
    family = _Family(
        callback_event=event,
        runtime_event_sources=family_sources,
        coverage_status=family_status,
        blocked_reason="" if family_status == "executable" else "event_family_blocked",
        admission_status=family_status,
    )
    effect = _Effect(
        effect_id="effect:1",
        opcode="TriggerAbility",
        payload={"standard": {"ability_name": "NestedAbility"}},
        source=source,
    )
    graph = _Graph(
        standalone_ability_graph_id="graph:1",
        ability_name="NestedAbility",
        phase_ids=("phase:1",),
        source=source,
    )
    phase = _Phase(
        phase_id="phase:1",
        ability_name="NestedAbility",
        binding_id="graph:1",
        source=source,
    )
    return [callback], [task], [family], [effect], [graph], [phase], {source_path}


def _run_finalizer(fixture: tuple[Any, ...]) -> tuple[list[Any], list[Any], tuple[dict[str, Any], ...]]:
    callbacks, tasks, families, effects, graphs, phases, formal = fixture
    return _finalize_action_window_status_callback_admission(
        callbacks,
        tasks,
        families,
        effects,
        graphs,
        phases,
        formal,
    )


def run_fast() -> None:
    _assert_governance_guards()
    negative_reasons: list[str] = []

    callbacks, tasks, audit = _run_finalizer(_fixture())
    if callbacks[0].coverage_status != "executable" or tasks[0].coverage_status != "executable":
        _fail("positive_finalization_did_not_promote")
    if not any(row["decision"] == "promoted" for row in audit):
        _fail("positive_audit_missing")

    fixture = _fixture(task_reason="unsupported_target_expression")
    callbacks, tasks, audit = _run_finalizer(fixture)
    if tasks[0].coverage_status != "blocked" or callbacks[0].coverage_status != "blocked":
        _fail("independent_blocker_was_removed")
    negative_reasons.extend(row["decision"] for row in audit)

    for graph_id, phase_id, expected in (
        ("", "", "typed_target_missing"),
        ("graph:1", "phase:1", "typed_target_ambiguous"),
        ("graph:missing", "", "typed_target_graph_missing"),
    ):
        fixture = _fixture(link_graph=graph_id, link_phase=phase_id)
        callbacks, tasks, audit = _run_finalizer(fixture)
        if tasks[0].coverage_status != "blocked":
            _fail(expected)
        negative_reasons.extend(row["decision"] for row in audit)

    fixture = _fixture(source_mode="synthetic")
    callbacks, tasks, audit = _run_finalizer(fixture)
    if tasks[0].coverage_status != "blocked":
        _fail("synthetic_source_promoted")
    negative_reasons.extend(row["decision"] for row in audit)

    fixture = _fixture(family_sources=("action.after_attack",))
    callbacks, tasks, audit = _run_finalizer(fixture)
    if tasks[0].coverage_status != "blocked":
        _fail("missing_action_window_producer_promoted")
    negative_reasons.extend(row["decision"] for row in audit)

    fixture = _fixture(
        family_sources=("action.window.after_attack", "action.window.after_attack.secondary")
    )
    callbacks, tasks, audit = _run_finalizer(fixture)
    if tasks[0].coverage_status != "blocked":
        _fail("ambiguous_action_window_producer_promoted")
    negative_reasons.extend(row["decision"] for row in audit)

    fixture = _fixture(family_status="blocked")
    callbacks, tasks, audit = _run_finalizer(fixture)
    if tasks[0].coverage_status != "blocked":
        _fail("blocked_event_family_promoted")
    negative_reasons.extend(row["decision"] for row in audit)

    fixture = _fixture()
    callbacks0, tasks0, families, effects, graphs, phases, formal = fixture
    sibling = replace(
        tasks0[0],
        task_id="task:blocked-sibling",
        opcode="Unsupported",
        effect_id="",
        coverage_status="blocked",
        blocked_reason="unsupported_status_callback_task",
        linked_standalone_graph_id="",
    )
    callbacks0[0] = replace(
        callbacks0[0], task_ids=(tasks0[0].task_id, sibling.task_id)
    )
    callbacks, tasks, audit = _run_finalizer(
        (callbacks0, [tasks0[0], sibling], families, effects, graphs, phases, formal)
    )
    if any(task.coverage_status == "executable" for task in tasks):
        _fail("blocked_sibling_closure_was_bypassed")
    negative_reasons.extend(row["decision"] for row in audit)

    before_cb, before_task, *_ = _fixture()
    callbacks, tasks, _ = _run_finalizer(_fixture())
    before_identity = (
        before_cb[0].callback_id,
        before_cb[0].modifier_name,
        before_cb[0].event,
        before_cb[0].task_ids,
        before_cb[0].source,
        before_task[0].task_id,
        before_task[0].callback_id,
        before_task[0].event,
        before_task[0].opcode,
        before_task[0].effect_id,
        before_task[0].source,
        before_task[0].linked_standalone_graph_id,
        before_task[0].linked_ability_phase_id,
    )
    after_identity = (
        callbacks[0].callback_id,
        callbacks[0].modifier_name,
        callbacks[0].event,
        callbacks[0].task_ids,
        callbacks[0].source,
        tasks[0].task_id,
        tasks[0].callback_id,
        tasks[0].event,
        tasks[0].opcode,
        tasks[0].effect_id,
        tasks[0].source,
        tasks[0].linked_standalone_graph_id,
        tasks[0].linked_ability_phase_id,
    )
    if before_identity != after_identity:
        _fail("stable_identity_changed")

    required_negative_prefixes = {
        "task_not_exact_stale_blocker",
        "typed_target_missing",
        "typed_target_ambiguous",
        "typed_target_graph_missing",
        "source_mode_not_admitted",
        "action_window_producer_missing",
        "action_window_producer_ambiguous",
        "event_family_blocked",
        "callback_closure_blocked",
    }
    observed = {reason.split(":", 1)[0] for reason in negative_reasons}
    missing = required_negative_prefixes - observed
    if missing:
        _fail("negative_reason_coverage_missing:" + ",".join(sorted(missing)))

    print("FAST PASS")
    print("negative_reasons=" + json.dumps(sorted(Counter(negative_reasons).items())))


def _audit_histogram(audit: tuple[dict[str, Any], ...], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get(field) or "") for row in audit).items()))


def run_direct() -> None:
    if not TBGD_ROOT.is_dir():
        _fail(f"pinned_tbgd_missing:{TBGD_ROOT}")

    _assert_governance_guards()
    started = time.perf_counter()
    lowerer = TBGDLowering(TBGD_ROOT)
    ir = lowerer.build()
    rulebook = RuleBook(ir)
    elapsed = time.perf_counter() - started
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    audit = getattr(lowerer, "_action_window_status_callback_finalization_audit", None)
    if not isinstance(audit, tuple) or not audit:
        _fail("production_finalizer_audit_missing")

    callbacks = {item.callback_id: item for item in ir.status_callbacks}
    tasks = {item.task_id: item for item in ir.status_callback_tasks}
    graphs = {
        item.standalone_ability_graph_id: item for item in ir.standalone_ability_graphs
    }
    phases = {item.phase_id: item for item in ir.ability_phases}
    families = {item.callback_event: item for item in ir.status_event_families}

    denominator = [
        row
        for row in audit
        if row.get("source_mode") == "mainline_avatar_ability"
        and row.get("action_window_runtime_source")
    ]
    if not denominator:
        _fail("direct_source_denominator_empty")

    promoted = [row for row in denominator if row.get("decision") == "promoted"]
    if not promoted:
        _fail("direct_real_positive_missing")

    materializations = (
        tuple(rulebook.ir.task_graph_catalog.entry_materializations)
        if rulebook.ir.task_graph_catalog is not None
        else ()
    )
    task_graphs = (
        {graph.graph_id: graph for graph in rulebook.ir.task_graph_catalog.graphs}
        if rulebook.ir.task_graph_catalog is not None
        else {}
    )

    promoted_ledger: list[dict[str, Any]] = []
    for row in promoted:
        callback = callbacks.get(str(row["callback_id"]))
        task = tasks.get(str(row["task_id"]))
        if callback is None or task is None:
            _fail("promoted_identity_missing_from_canonical_ir")
        if (
            callback.coverage_status != "executable"
            or callback.admission_status != "executable"
            or callback.blocked_reason
            or callback.blocking_dependency
            or task.coverage_status != "executable"
            or task.blocked_reason
            or task.opcode != "TriggerAbility"
        ):
            _fail("promoted_row_not_executable_in_canonical_ir")

        graph_id = task.linked_standalone_graph_id
        phase_id = task.linked_ability_phase_id
        if bool(graph_id) == bool(phase_id):
            _fail("promoted_typed_target_not_unique")
        if graph_id:
            graph = graphs.get(graph_id)
            if graph is None or graph.source.source_path != callback.source.source_path:
                _fail("promoted_graph_target_not_formal")
            formal_graph_id = graph_id
        else:
            phase = phases.get(phase_id)
            if phase is None or phase.source.source_path != callback.source.source_path:
                _fail("promoted_phase_target_not_formal")
            formal_graph_id = phase.binding_id

        entries = [
            item
            for item in materializations
            if item.entry_kind == "status_callback"
            and item.owner_id == callback.callback_id
            and item.status == "materialized"
        ]
        if len(entries) != 1 or not entries[0].graph_id or entries[0].graph_id not in task_graphs:
            _fail("promoted_formal_status_root_not_resolved")

        family = families.get(callback.event)
        action_sources = (
            tuple(
                source
                for source in family.runtime_event_sources
                if source.startswith("action.window.")
            )
            if family is not None
            else ()
        )
        if len(action_sources) != 1:
            _fail("promoted_action_window_producer_not_unique")

        promoted_ledger.append(
            {
                "source": callback.source.source_path,
                "callback_id": callback.callback_id,
                "task_id": task.task_id,
                "event": callback.event,
                "old_reason": row["old_task_blocked_reason"],
                "new_status": task.coverage_status,
                "typed_target": graph_id or phase_id,
                "formal_graph": formal_graph_id,
                "status_root_graph": entries[0].graph_id,
            }
        )

    illegal = [
        row
        for row in audit
        if row.get("decision") == "promoted"
        and row.get("old_task_blocked_reason")
        != f"status_callback_event_not_admitted:{row.get('event')}"
    ]
    if illegal:
        _fail("non_stale_blocker_promoted")

    negatives = [row for row in denominator if row.get("decision") != "promoted"]
    for row in negatives:
        task = tasks.get(str(row["task_id"]))
        if task is not None and task.coverage_status == "executable":
            _fail("negative_denominator_row_became_executable")

    evidence = {
        "mode": "direct",
        "wall_seconds": round(elapsed, 3),
        "peak_rss_kib": peak_rss,
        "denominator_count": len(denominator),
        "promoted_count": len(promoted),
        "decision_histogram": _audit_histogram(audit, "decision"),
        "before_task_reason_histogram": _audit_histogram(audit, "old_task_blocked_reason"),
        "after_task_status_histogram": _audit_histogram(audit, "new_task_coverage_status"),
        "promoted_rows": promoted_ledger,
    }
    print("DIRECT PASS")
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fast", action="store_true")
    group.add_argument("--direct", action="store_true")
    args = parser.parse_args()
    if args.fast:
        run_fast()
    else:
        run_direct()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
