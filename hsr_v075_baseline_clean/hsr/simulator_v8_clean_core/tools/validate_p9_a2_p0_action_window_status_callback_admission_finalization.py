from __future__ import annotations

import argparse
import ast
import hashlib
import json
import resource
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[4]
BASELINE_ROOT = REPO_ROOT / "hsr_v075_baseline_clean"
TBGD_ROOT = REPO_ROOT / "turnbasedgamedata-main"
BASE_SHA = "bd1a4ac94ca394d2ea563d086eaf56e9ed45b285"
LOWERING_PATH = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py"
A1_AUTHORITY_PATHS = (
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_formal_action_graph_admission_authority.py",
)

if str(BASELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(BASELINE_ROOT))

from hsr.simulator_v8_clean_core import BASELINE_VERSION
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering,
    _assign_character_ability_invocation_roles,
    _block_status_callback_derived_by_callback,
    _block_status_callbacks_by_event_family,
    _block_status_callback_tasks_by_callback,
    _dedupe_target_expressions,
    _finalize_action_window_status_callback_admission,
    _link_status_trigger_ability_graphs,
    _link_trigger_ability_graphs,
    _lower_queue_resolutions,
    _lower_status_event_families,
    _status_event_blocked_reasons,
)
from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import (
    materialize_character_runtime_task_graph_catalog,
)
from hsr.simulator_v8_clean_core.tools.validate_p9_formal_action_graph_admission_authority import (
    _run_direct as _run_a1_direct,
    _run_fast as _run_a1_fast,
)


def _fail(message: str) -> None:
    raise AssertionError(message)


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=REPO_ROOT, text=True, stderr=subprocess.STDOUT
    )


def _function_ast(source: str, function_name: str) -> str:
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return ast.dump(node, include_attributes=False)
    _fail(f"function_missing:{function_name}")


def _json_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _assert_a1_authority_unchanged() -> dict[str, Any]:
    equal_paths: list[str] = []
    for relative in A1_AUTHORITY_PATHS:
        current = (REPO_ROOT / relative).read_text(encoding="utf-8")
        baseline = _git("show", f"{BASE_SHA}:{relative}")
        if current != baseline:
            _fail(f"a1_authority_changed:{relative}")
        equal_paths.append(relative)
    return {"fixed_base": BASE_SHA, "exact_equal_paths": equal_paths}


def _assert_governance_guards() -> dict[str, Any]:
    current = (REPO_ROOT / LOWERING_PATH).read_text(encoding="utf-8")
    baseline = _git("show", f"{BASE_SHA}:{LOWERING_PATH}")
    for name in ("_link_trigger_ability_graphs", "_link_status_trigger_ability_graphs"):
        if _function_ast(current, name) != _function_ast(baseline, name):
            _fail(f"existing_link_authority_changed:{name}")

    changed = tuple(
        line.strip()
        for line in _git("diff", "--name-only", BASE_SHA).splitlines()
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
    bad = [
        path
        for path in changed
        if path.startswith(forbidden_prefixes) or path in forbidden_exact
    ]
    if bad:
        _fail("forbidden_runtime_or_rule_change:" + ",".join(bad))

    diff = _git("diff", "--unified=0", BASE_SHA, "--", LOWERING_PATH)
    added = "\n".join(
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    for token in ("RandomConfig", "weighted_selection", "weighted-selection", "rng", "RNG"):
        if token in added:
            _fail(f"pr9_rng_scope_leak:{token}")

    return {
        "changed_paths": list(changed),
        "a1_authority": _assert_a1_authority_unchanged(),
    }


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
    task_path: str = "CallbackConfig[0]"
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
    link_blocked_reason: str = ""


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
        callbacks, tasks, families, effects, graphs, phases, formal
    )


def _a1_fast_regression() -> dict[str, Any]:
    authority = _assert_a1_authority_unchanged()
    result = _run_a1_fast()
    if not result.get("ok"):
        _fail("a1_fast_behavior_regression")
    stable = {"predicates": result.get("predicates"), "sample": result.get("sample")}
    return {
        "authority": authority,
        "behavior_digest": _json_digest(stable),
        "predicates": result.get("predicates"),
    }


def run_fast() -> None:
    governance = _assert_governance_guards()
    negative_reasons: list[str] = []

    callbacks, tasks, audit = _run_finalizer(_fixture())
    if callbacks[0].coverage_status != "executable" or tasks[0].coverage_status != "executable":
        _fail("positive_finalization_did_not_promote")
    if not any(row["decision"] == "promoted" for row in audit):
        _fail("positive_audit_missing")

    callbacks, tasks, audit = _run_finalizer(_fixture(callback_reason="", task_reason=None))
    if callbacks[0].coverage_status != "executable" or tasks[0].coverage_status != "executable":
        _fail("already_executable_callback_stale_child_not_promoted")

    callbacks, tasks, audit = _run_finalizer(_fixture(task_reason="unsupported_target_expression"))
    if tasks[0].coverage_status != "blocked" or callbacks[0].coverage_status != "blocked":
        _fail("independent_blocker_was_removed")
    negative_reasons.extend(row["decision"] for row in audit)

    for graph_id, phase_id, expected in (
        ("", "", "typed_target_missing"),
        ("graph:1", "phase:1", "typed_target_ambiguous"),
        ("graph:missing", "", "typed_target_graph_missing"),
    ):
        callbacks, tasks, audit = _run_finalizer(_fixture(link_graph=graph_id, link_phase=phase_id))
        if tasks[0].coverage_status != "blocked":
            _fail(expected)
        negative_reasons.extend(row["decision"] for row in audit)

    callbacks, tasks, audit = _run_finalizer(_fixture(source_mode="synthetic"))
    if tasks[0].coverage_status != "blocked":
        _fail("synthetic_source_promoted")
    negative_reasons.extend(row["decision"] for row in audit)

    callbacks, tasks, audit = _run_finalizer(_fixture(family_sources=("action.after_attack",)))
    if tasks[0].coverage_status != "blocked":
        _fail("missing_action_window_producer_promoted")
    negative_reasons.extend(row["decision"] for row in audit)

    callbacks, tasks, audit = _run_finalizer(
        _fixture(family_sources=("action.window.after_attack", "action.window.after_attack.secondary"))
    )
    if tasks[0].coverage_status != "blocked":
        _fail("ambiguous_action_window_producer_promoted")
    negative_reasons.extend(row["decision"] for row in audit)

    callbacks, tasks, audit = _run_finalizer(_fixture(family_status="blocked"))
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
    callbacks0[0] = replace(callbacks0[0], task_ids=(tasks0[0].task_id, sibling.task_id))
    callbacks, tasks, audit = _run_finalizer(
        (callbacks0, [tasks0[0], sibling], families, effects, graphs, phases, formal)
    )
    if any(task.coverage_status == "executable" for task in tasks):
        _fail("blocked_sibling_closure_was_bypassed")
    negative_reasons.extend(row["decision"] for row in audit)

    fixture = _fixture(callback_reason="", task_reason=None)
    callbacks0, tasks0, families, effects, graphs, phases, formal = fixture
    root = replace(
        tasks0[0],
        task_id="task:root",
        opcode="Retarget",
        effect_id="",
        coverage_status="executable",
        blocked_reason="",
        linked_standalone_graph_id="",
    )
    child = replace(
        tasks0[0],
        task_id="task:child",
        task_path="CallbackConfig[0].formal_branch[0].child[0]",
    )
    callbacks0[0] = replace(callbacks0[0], task_ids=(root.task_id,))
    callbacks, tasks, _ = _run_finalizer(
        (callbacks0, [root, child], families, effects, graphs, phases, formal)
    )
    promoted_child = next(item for item in tasks if item.task_id == child.task_id)
    if promoted_child.coverage_status != "executable":
        _fail("formal_branch_child_closure_not_admitted")

    link_callbacks, link_tasks, _, link_effects, link_graphs, _, _ = _fixture(link_graph="")
    before_link_status = (link_tasks[0].coverage_status, link_tasks[0].blocked_reason)
    linked = _link_status_trigger_ability_graphs(
        link_tasks, link_callbacks, link_effects, link_graphs
    )
    if linked[0].linked_standalone_graph_id != "graph:1":
        _fail("s8b5b_link_pass_did_not_resolve_typed_target")
    if (linked[0].coverage_status, linked[0].blocked_reason) != before_link_status:
        _fail("s8b5b_link_pass_promoted_blocked_parent")

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

    required = {
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
    missing = required - observed
    if missing:
        _fail("negative_reason_coverage_missing:" + ",".join(sorted(missing)))

    a1 = _a1_fast_regression()
    print("FAST PASS")
    print("negative_reasons=" + json.dumps(sorted(Counter(negative_reasons).items())))
    print("a1_regression=" + json.dumps(a1, ensure_ascii=False, sort_keys=True))
    print("governance=" + json.dumps(governance, ensure_ascii=False, sort_keys=True))


def _unique_index(items: list[Any], field: str, subject: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in items:
        key = str(getattr(item, field))
        if key in result:
            _fail(f"independent_denominator_duplicate:{subject}:{key}")
        result[key] = item
    return result


def _source_identity(source: Any) -> str:
    to_json = getattr(source, "to_json", None)
    if callable(to_json):
        return _json_digest(to_json())
    return _json_digest({"source_path": str(getattr(source, "source_path", ""))})


def _formal_graph_for_target(
    task: Any,
    callback: Any,
    ability_name: str,
    graphs_by_id: dict[str, Any],
    phases_by_id: dict[str, Any],
    graphs_by_phase: dict[str, list[Any]],
) -> tuple[str, str]:
    graph_id = str(task.linked_standalone_graph_id or "")
    phase_id = str(task.linked_ability_phase_id or "")
    if bool(graph_id) == bool(phase_id):
        return "", ""
    if graph_id:
        graph = graphs_by_id.get(graph_id)
        if (
            graph is not None
            and graph.source.source_path == callback.source.source_path
            and graph.ability_name == ability_name
        ):
            return graph_id, graph_id
        return graph_id, ""
    phase = phases_by_id.get(phase_id)
    owner_graphs = tuple(graphs_by_phase.get(phase_id, ()))
    if (
        phase is not None
        and len(owner_graphs) == 1
        and phase.source.source_path == callback.source.source_path
        and phase.ability_name == ability_name
        and owner_graphs[0].source.source_path == callback.source.source_path
        and owner_graphs[0].ability_name == ability_name
    ):
        return phase_id, owner_graphs[0].standalone_ability_graph_id
    return phase_id, ""


def _action_window_event_sources(families: list[Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for family in families:
        sources = tuple(
            source
            for source in family.runtime_event_sources
            if source.startswith("action.window.")
        )
        if len(sources) == 1:
            if family.callback_event in result and result[family.callback_event] != sources[0]:
                _fail(f"action_window_event_source_not_unique:{family.callback_event}")
            result[family.callback_event] = sources[0]
    return result


def _independent_expected_denominator(
    callbacks: list[Any],
    tasks: list[Any],
    families: list[Any],
    effects: list[Any],
    graphs: list[Any],
    phases: list[Any],
    formal_source_paths: set[str],
) -> tuple[dict[str, Any], ...]:
    callbacks_by_id = _unique_index(callbacks, "callback_id", "callback")
    effects_by_id = _unique_index(effects, "effect_id", "effect")
    graphs_by_id = _unique_index(graphs, "standalone_ability_graph_id", "graph")
    phases_by_id = _unique_index(phases, "phase_id", "phase")
    families_by_event: dict[str, list[Any]] = {}
    for family in families:
        families_by_event.setdefault(family.callback_event, []).append(family)
    graphs_by_phase: dict[str, list[Any]] = {}
    for graph in graphs:
        for phase_id in graph.phase_ids:
            graphs_by_phase.setdefault(phase_id, []).append(graph)

    rows: list[dict[str, Any]] = []
    for task in tasks:
        if task.opcode != "TriggerAbility":
            continue
        callback = callbacks_by_id.get(task.callback_id)
        if callback is None:
            _fail(f"independent_denominator_callback_missing:{task.callback_id}")
        if callback.source_mode != "mainline_avatar_ability":
            continue
        if (
            callback.source.source_path not in formal_source_paths
            or task.source.source_path != callback.source.source_path
        ):
            continue
        event_families = tuple(families_by_event.get(callback.event, ()))
        if len(event_families) != 1:
            continue
        action_sources = tuple(
            source
            for source in event_families[0].runtime_event_sources
            if source.startswith("action.window.")
        )
        if len(action_sources) != 1:
            continue
        effect = effects_by_id.get(task.effect_id)
        if effect is None or effect.opcode != "TriggerAbility":
            continue
        standard = effect.payload.get("standard")
        ability_name = (
            str(standard.get("ability_name") or "")
            if isinstance(standard, Mapping)
            else ""
        )
        if not ability_name:
            continue
        typed_target, formal_graph_id = _formal_graph_for_target(
            task,
            callback,
            ability_name,
            graphs_by_id,
            phases_by_id,
            graphs_by_phase,
        )
        rows.append(
            {
                "source_path": callback.source.source_path,
                "source_identity": _source_identity(callback.source),
                "source_mode": callback.source_mode,
                "callback_id": callback.callback_id,
                "task_id": task.task_id,
                "event": callback.event,
                "old_callback_coverage_status": callback.coverage_status,
                "old_callback_admission_status": callback.admission_status,
                "old_callback_blocked_reason": callback.blocked_reason,
                "old_callback_blocking_dependency": callback.blocking_dependency,
                "old_task_coverage_status": task.coverage_status,
                "old_task_blocked_reason": task.blocked_reason,
                "action_window_runtime_source": action_sources[0],
                "linked_standalone_graph_id": str(task.linked_standalone_graph_id or ""),
                "linked_ability_phase_id": str(task.linked_ability_phase_id or ""),
                "typed_target": typed_target,
                "formal_graph_id": formal_graph_id,
                "effect_id": task.effect_id,
                "ability_name": ability_name,
            }
        )
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                row["source_path"],
                row["callback_id"],
                row["task_id"],
                row["event"],
            ),
        )
    )


def _denominator_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("source_path") or ""),
        str(row.get("callback_id") or ""),
        str(row.get("task_id") or ""),
        str(row.get("event") or ""),
    )


def _reconcile_expected_with_audit(
    expected: tuple[dict[str, Any], ...],
    audit: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    expected_by_key = {_denominator_key(row): row for row in expected}
    if len(expected_by_key) != len(expected):
        _fail("independent_denominator_key_not_unique")
    audit_rows = tuple(
        row
        for row in audit
        if row.get("source_mode") == "mainline_avatar_ability"
        and row.get("action_window_runtime_source")
    )
    audit_by_key = {_denominator_key(row): row for row in audit_rows}
    if len(audit_by_key) != len(audit_rows):
        _fail("finalizer_audit_denominator_key_not_unique")
    if set(expected_by_key) != set(audit_by_key):
        missing = sorted(set(expected_by_key) - set(audit_by_key))
        extra = sorted(set(audit_by_key) - set(expected_by_key))
        _fail(
            "independent_denominator_bidirectional_mismatch:"
            + json.dumps({"missing": missing, "extra": extra}, sort_keys=True)
        )

    compared = (
        "source_path",
        "source_mode",
        "callback_id",
        "task_id",
        "event",
        "old_callback_coverage_status",
        "old_callback_blocked_reason",
        "old_task_coverage_status",
        "old_task_blocked_reason",
        "action_window_runtime_source",
        "typed_target",
        "formal_graph_id",
    )
    reconciled: list[dict[str, Any]] = []
    for key in sorted(expected_by_key):
        left = expected_by_key[key]
        right = audit_by_key[key]
        for field in compared:
            if str(left.get(field) or "") != str(right.get(field) or ""):
                _fail(f"independent_denominator_field_mismatch:{field}:{key}")
        reconciled.append(
            {
                **left,
                "decision": right.get("decision"),
                "new_task_coverage_status": right.get("new_task_coverage_status"),
                "new_task_blocked_reason": right.get("new_task_blocked_reason"),
            }
        )
    return tuple(reconciled)


def _status_transition_snapshot(
    callbacks: list[Any],
    tasks: list[Any],
    families: list[Any],
    formal_source_paths: set[str],
) -> dict[str, Any]:
    event_sources = _action_window_event_sources(families)
    callback_rows: dict[str, dict[str, Any]] = {}
    for callback in callbacks:
        if (
            callback.source_mode != "mainline_avatar_ability"
            or callback.source.source_path not in formal_source_paths
            or callback.event not in event_sources
        ):
            continue
        callback_rows[callback.callback_id] = {
            "callback_id": callback.callback_id,
            "event": callback.event,
            "runtime_source": event_sources[callback.event],
            "source_path": callback.source.source_path,
            "source_identity": _source_identity(callback.source),
            "source_mode": callback.source_mode,
            "task_ids": tuple(callback.task_ids),
            "coverage_status": callback.coverage_status,
            "admission_status": callback.admission_status,
            "blocked_reason": callback.blocked_reason,
            "blocking_dependency": callback.blocking_dependency,
        }

    task_rows: dict[str, dict[str, Any]] = {}
    for task in tasks:
        callback = callback_rows.get(task.callback_id)
        if callback is None:
            continue
        if task.event != callback["event"]:
            _fail(f"same_event_task_event_mismatch:{task.task_id}")
        task_rows[task.task_id] = {
            "task_id": task.task_id,
            "callback_id": task.callback_id,
            "event": task.event,
            "runtime_source": callback["runtime_source"],
            "callback_source_path": callback["source_path"],
            "source_path": task.source.source_path,
            "source_identity": _source_identity(task.source),
            "opcode": task.opcode,
            "effect_id": task.effect_id,
            "task_path": str(getattr(task, "task_path", "") or ""),
            "linked_standalone_graph_id": str(task.linked_standalone_graph_id or ""),
            "linked_ability_phase_id": str(task.linked_ability_phase_id or ""),
            "coverage_status": task.coverage_status,
            "blocked_reason": task.blocked_reason,
        }
    return {
        "event_sources": event_sources,
        "callbacks": callback_rows,
        "tasks": task_rows,
    }


def _transition_histogram(rows: dict[str, dict[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get(field) or "") for row in rows.values()).items()))


def _reconcile_same_event_transitions(
    before: dict[str, Any],
    after: dict[str, Any],
    audit: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    before_callbacks = before["callbacks"]
    after_callbacks = after["callbacks"]
    before_tasks = before["tasks"]
    after_tasks = after["tasks"]
    if set(before_callbacks) != set(after_callbacks):
        _fail("same_event_callback_identity_set_changed")
    if set(before_tasks) != set(after_tasks):
        _fail("same_event_task_identity_set_changed")
    if before["event_sources"] != after["event_sources"]:
        _fail("action_window_runtime_source_mapping_changed")

    promoted_rows = tuple(row for row in audit if row.get("decision") == "promoted")
    promoted_task_ids = {str(row.get("task_id") or "") for row in promoted_rows}
    promoted_callback_ids = {str(row.get("callback_id") or "") for row in promoted_rows}

    task_changes: list[dict[str, Any]] = []
    for task_id in sorted(before_tasks):
        old = before_tasks[task_id]
        new = after_tasks[task_id]
        stable_fields = (
            "task_id",
            "callback_id",
            "event",
            "runtime_source",
            "callback_source_path",
            "source_path",
            "source_identity",
            "opcode",
            "effect_id",
            "task_path",
            "linked_standalone_graph_id",
            "linked_ability_phase_id",
        )
        if any(old[field] != new[field] for field in stable_fields):
            _fail(f"same_event_task_stable_identity_changed:{task_id}")
        became_executable = (
            old["coverage_status"] == "blocked" and new["coverage_status"] == "executable"
        )
        if became_executable and task_id not in promoted_task_ids:
            _fail(f"same_event_nonfinalizer_task_promoted:{task_id}")
        if task_id in promoted_task_ids:
            stale = f"status_callback_event_not_admitted:{old['event']}"
            if old["coverage_status"] != "blocked" or old["blocked_reason"] != stale:
                _fail(f"same_event_promoted_task_not_exact_stale:{task_id}")
            if new["coverage_status"] != "executable" or new["blocked_reason"]:
                _fail(f"same_event_promoted_task_not_final_executable:{task_id}")
        elif old["coverage_status"] == "blocked" and new["coverage_status"] == "executable":
            _fail(f"same_event_blocker_bypassed:{task_id}")
        if (
            old["coverage_status"] != new["coverage_status"]
            or old["blocked_reason"] != new["blocked_reason"]
        ):
            task_changes.append(
                {
                    "task_id": task_id,
                    "callback_id": old["callback_id"],
                    "event": old["event"],
                    "opcode": old["opcode"],
                    "before_status": old["coverage_status"],
                    "before_reason": old["blocked_reason"],
                    "after_status": new["coverage_status"],
                    "after_reason": new["blocked_reason"],
                    "promoted_by_finalizer": task_id in promoted_task_ids,
                }
            )

    callback_changes: list[dict[str, Any]] = []
    for callback_id in sorted(before_callbacks):
        old = before_callbacks[callback_id]
        new = after_callbacks[callback_id]
        stable_fields = (
            "callback_id",
            "event",
            "runtime_source",
            "source_path",
            "source_identity",
            "source_mode",
            "task_ids",
        )
        if any(old[field] != new[field] for field in stable_fields):
            _fail(f"same_event_callback_stable_identity_changed:{callback_id}")
        became_executable = (
            old["coverage_status"] == "blocked" and new["coverage_status"] == "executable"
        )
        if became_executable and callback_id not in promoted_callback_ids:
            _fail(f"same_event_callback_promoted_without_task:{callback_id}")
        if became_executable:
            stale = f"status_callback_event_not_admitted:{old['event']}"
            if old["blocked_reason"] != stale and old["blocking_dependency"] != stale:
                _fail(f"same_event_callback_nonstale_blocker_removed:{callback_id}")
        if (
            old["coverage_status"] != new["coverage_status"]
            or old["admission_status"] != new["admission_status"]
            or old["blocked_reason"] != new["blocked_reason"]
            or old["blocking_dependency"] != new["blocking_dependency"]
        ):
            callback_changes.append(
                {
                    "callback_id": callback_id,
                    "event": old["event"],
                    "before_status": old["coverage_status"],
                    "before_admission": old["admission_status"],
                    "before_reason": old["blocked_reason"],
                    "before_dependency": old["blocking_dependency"],
                    "after_status": new["coverage_status"],
                    "after_admission": new["admission_status"],
                    "after_reason": new["blocked_reason"],
                    "after_dependency": new["blocking_dependency"],
                    "owns_promoted_task": callback_id in promoted_callback_ids,
                }
            )

    return {
        "event_sources": before["event_sources"],
        "callback_count": len(before_callbacks),
        "task_count": len(before_tasks),
        "promoted_task_ids": sorted(promoted_task_ids),
        "before_callback_status_histogram": _transition_histogram(before_callbacks, "coverage_status"),
        "after_callback_status_histogram": _transition_histogram(after_callbacks, "coverage_status"),
        "before_callback_reason_histogram": _transition_histogram(before_callbacks, "blocked_reason"),
        "after_callback_reason_histogram": _transition_histogram(after_callbacks, "blocked_reason"),
        "before_task_status_histogram": _transition_histogram(before_tasks, "coverage_status"),
        "after_task_status_histogram": _transition_histogram(after_tasks, "coverage_status"),
        "before_task_reason_histogram": _transition_histogram(before_tasks, "blocked_reason"),
        "after_task_reason_histogram": _transition_histogram(after_tasks, "blocked_reason"),
        "callback_changes": callback_changes,
        "task_changes": task_changes,
    }


def _queue_resolution_evidence(
    queue_role_intents: list[Any],
    queue_resolutions: list[Any],
) -> dict[str, Any]:
    if len(queue_role_intents) != len(queue_resolutions):
        _fail("queue_role_resolution_denominator_mismatch")
    status_histogram = Counter(
        str(getattr(item, "coverage_status", "") or "") for item in queue_resolutions
    )
    blocker_histogram = Counter(
        str(getattr(item, "blocked_reason", "") or "")
        for item in queue_resolutions
        if getattr(item, "coverage_status", "") != "executable"
    )
    if any(
        getattr(item, "coverage_status", "") != "executable"
        and not str(getattr(item, "blocked_reason", "") or "")
        for item in queue_resolutions
    ):
        _fail("blocked_queue_resolution_without_reason")
    queue_root_graph_ids = sorted(
        {
            str(item.resolved_ids.get("standalone_ability_graph_id"))
            for item in queue_resolutions
            if getattr(item, "coverage_status", "") == "executable"
            and getattr(item, "resolved_kind", "") == "standalone_ability_graph"
            and isinstance(item.resolved_ids.get("standalone_ability_graph_id"), str)
            and item.resolved_ids.get("standalone_ability_graph_id")
        }
    )
    return {
        "input_scope": "post_status_blocking_source_backed_TurnInsertAbility",
        "role_authority": "_lower_queue_resolutions -> _assign_character_ability_invocation_roles",
        "intent_count": len(queue_role_intents),
        "resolution_count": len(queue_resolutions),
        "coverage_histogram": dict(sorted(status_histogram.items())),
        "blocked_reason_histogram": dict(sorted(blocker_histogram.items())),
        "executable_queue_root_graph_ids": queue_root_graph_ids,
    }


def _build_focused_direct_ir() -> tuple[
    TBGDLowering,
    CanonicalIR,
    RuleBook,
    tuple[dict[str, Any], ...],
    tuple[dict[str, Any], ...],
    dict[str, Any],
    dict[str, Any],
]:
    lowerer = TBGDLowering(TBGD_ROOT)
    lowerer.build_character_ability_source_graph_catalog()
    snapshot = getattr(lowerer, "_character_ability_raw_snapshot", None)
    scope_catalog = getattr(lowerer, "_character_ability_scope_catalog", None)
    if snapshot is None or scope_catalog is None:
        _fail("focused_source_catalog_prerequisite_missing")

    formal_context = lowerer._character_formal_task_source_context()
    formal_source_paths = {item.source.source_path for item in snapshot.sources}
    if not formal_source_paths:
        _fail("focused_formal_source_denominator_empty")

    queue_priorities = lowerer._lower_queue_priorities()
    queue_priority_lookup = {
        (priority.priority_table, priority.priority_key): priority
        for priority in queue_priorities
        if priority.coverage_status == "executable"
    }

    selected_files: list[Path] = []
    status_callbacks: list[Any] = []
    status_callback_tasks: list[Any] = []
    queue_intents: list[Any] = []
    effects: list[Any] = []
    conditions: list[Any] = []
    formulas: list[Any] = []
    target_expressions: list[Any] = []

    ability_files = lowerer._ability_files()
    for ability_file_order, path in enumerate(ability_files):
        relative = path.relative_to(TBGD_ROOT).as_posix()
        if relative not in formal_source_paths:
            continue
        selected_files.append(path)
        lowered = lowerer._lower_ability_file(
            path,
            queue_priority_lookup,
            ability_file_order=ability_file_order,
            formal_status_source_context=formal_context,
        )
        status_callbacks.extend(lowered.status_callbacks)
        status_callback_tasks.extend(lowered.status_callback_tasks)
        queue_intents.extend(lowered.queue_intents)
        effects.extend(lowered.effects)
        conditions.extend(lowered.conditions)
        formulas.extend(lowered.formulas)
        target_expressions.extend(lowered.target_expressions)

    selected_paths = {path.relative_to(TBGD_ROOT).as_posix() for path in selected_files}
    expected_paths = formal_source_paths.intersection(
        path.relative_to(TBGD_ROOT).as_posix() for path in ability_files
    )
    if selected_paths != expected_paths or not selected_paths:
        _fail("focused_formal_source_file_denominator_incomplete")

    (
        standalone_graphs,
        standalone_phases,
        standalone_tasks,
        standalone_effects,
        standalone_conditions,
        standalone_formulas,
        standalone_target_expressions,
        _standalone_root_task_ids_by_graph,
    ) = lowerer._lower_standalone_ability_graphs(selected_files)
    effects.extend(standalone_effects)
    conditions.extend(standalone_conditions)
    formulas.extend(standalone_formulas)
    target_expressions.extend(standalone_target_expressions)

    standalone_tasks = _link_trigger_ability_graphs(
        standalone_tasks,
        effects,
        standalone_graphs,
        standalone_phases,
    )
    status_callback_tasks = _link_status_trigger_ability_graphs(
        status_callback_tasks,
        status_callbacks,
        effects,
        standalone_graphs,
    )

    status_event_families = _lower_status_event_families(
        status_callbacks, status_callback_tasks
    )
    expected_denominator = _independent_expected_denominator(
        status_callbacks,
        status_callback_tasks,
        status_event_families,
        effects,
        standalone_graphs,
        standalone_phases,
        formal_source_paths,
    )
    if not expected_denominator:
        _fail("independent_source_denominator_empty")
    before_transitions = _status_transition_snapshot(
        status_callbacks,
        status_callback_tasks,
        status_event_families,
        formal_source_paths,
    )

    status_callbacks, status_callback_tasks, audit = (
        _finalize_action_window_status_callback_admission(
            status_callbacks,
            status_callback_tasks,
            status_event_families,
            effects,
            standalone_graphs,
            standalone_phases,
            formal_source_paths,
        )
    )
    reconciled = _reconcile_expected_with_audit(expected_denominator, audit)

    status_event_families = _lower_status_event_families(
        status_callbacks, status_callback_tasks
    )
    status_event_blocked_reasons = _status_event_blocked_reasons(status_event_families)
    status_callbacks = _block_status_callbacks_by_event_family(
        status_callbacks, status_event_blocked_reasons
    )
    status_callback_blocked_reasons = {
        callback.callback_id: (
            status_event_blocked_reasons.get(callback.event)
            or callback.blocked_reason
            or callback.blocking_dependency
        )
        for callback in status_callbacks
        if (
            callback.event in status_event_blocked_reasons
            or callback.blocked_reason == "equipment_modifier_definition_unreferenced"
        )
    }
    status_callback_tasks = _block_status_callback_tasks_by_callback(
        status_callback_tasks, status_callback_blocked_reasons
    )
    queue_intents = _block_status_callback_derived_by_callback(
        queue_intents, status_callback_blocked_reasons
    )
    status_event_families = _lower_status_event_families(
        status_callbacks, status_callback_tasks
    )
    after_transitions = _status_transition_snapshot(
        status_callbacks,
        status_callback_tasks,
        status_event_families,
        formal_source_paths,
    )
    transition_evidence = _reconcile_same_event_transitions(
        before_transitions, after_transitions, audit
    )

    queue_role_intents = [
        intent for intent in queue_intents if intent.opcode == "TurnInsertAbility"
    ]
    queue_resolutions = _lower_queue_resolutions(
        queue_intents=queue_role_intents,
        action_bindings=[],
        ability_phases=standalone_phases,
        standalone_graphs=standalone_graphs,
        combatant_action_sets=[],
    )
    queue_evidence = _queue_resolution_evidence(queue_role_intents, queue_resolutions)
    assigned_phases = _assign_character_ability_invocation_roles(
        standalone_phases,
        standalone_tasks,
        standalone_graphs,
        queue_resolutions,
        status_callback_tasks=status_callback_tasks,
        status_callbacks=status_callbacks,
    )
    assigned_by_id = {phase.phase_id: phase for phase in assigned_phases}
    if len(assigned_by_id) != len(assigned_phases):
        _fail("queue_aware_invocation_role_phase_identity_not_unique")

    graphs_by_id = {
        graph.standalone_ability_graph_id: graph for graph in standalone_graphs
    }
    queue_root_graph_ids = set(queue_evidence["executable_queue_root_graph_ids"])
    queue_root_phase_ids: set[str] = set()
    for graph_id in queue_root_graph_ids:
        graph = graphs_by_id.get(graph_id)
        if graph is None:
            _fail(f"queue_root_graph_missing_from_focused_catalog:{graph_id}")
        queue_root_phase_ids.update(graph.phase_ids)
    for phase in assigned_phases:
        if phase.phase_id in queue_root_phase_ids and phase.invocation_role != "standalone_root":
            _fail(f"queue_root_phase_role_not_standalone_root:{phase.phase_id}")
        if phase.invocation_role == "standalone_root" and phase.phase_id not in queue_root_phase_ids:
            _fail(f"standalone_root_without_queue_resolution:{phase.phase_id}")

    materialization_phases = [
        phase for phase in assigned_phases if phase.invocation_role != "standalone_root"
    ]
    if not materialization_phases:
        _fail("focused_status_materialization_phase_denominator_empty")
    excluded_queue_root_phase_ids = sorted(
        phase.phase_id
        for phase in assigned_phases
        if phase.invocation_role == "standalone_root"
    )

    control_flow_catalog = lowerer.build_character_control_flow_contract_catalog(
        snapshot=snapshot, scope_catalog=scope_catalog
    )
    task_graph_view = CanonicalIR(
        version=BASELINE_VERSION,
        ability_phases=tuple(materialization_phases),
        ability_tasks=tuple(standalone_tasks),
        standalone_ability_graphs=tuple(standalone_graphs),
        effects=tuple(effects),
        conditions=tuple(conditions),
        formulas=tuple(formulas),
        target_expressions=tuple(
            _dedupe_target_expressions(target_expressions).values()
        ),
        status_callbacks=tuple(status_callbacks),
        status_callback_tasks=tuple(status_callback_tasks),
        status_event_families=tuple(status_event_families),
    )
    task_graph_catalog = materialize_character_runtime_task_graph_catalog(
        control_flow_catalog,
        task_graph_view,
        source_snapshot=snapshot,
        definition_scope_complete=True,
    )
    ir = replace(task_graph_view, task_graph_catalog=task_graph_catalog)
    rulebook = RuleBook(ir)

    role_histogram = dict(
        sorted(Counter(phase.invocation_role for phase in assigned_phases).items())
    )
    denominator_meta = {
        "snapshot_source_count": len(snapshot.sources),
        "formal_source_path_count": len(formal_source_paths),
        "selected_formal_ability_file_count": len(selected_files),
        "status_callback_count": len(status_callbacks),
        "status_callback_task_count": len(status_callback_tasks),
        "standalone_graph_count": len(standalone_graphs),
        "queue_intent_count": len(queue_intents),
        "queue_resolution": queue_evidence,
        "queue_aware_invocation_role_histogram": role_histogram,
        "status_materializer_scope": "queue-aware phases excluding unrelated standalone_root entries",
        "status_materializer_excluded_queue_root_phase_ids": excluded_queue_root_phase_ids,
        "task_graph_materialization_count": len(task_graph_catalog.entry_materializations),
    }
    return (
        lowerer,
        ir,
        rulebook,
        audit,
        reconciled,
        denominator_meta,
        transition_evidence,
    )


def _audit_histogram(audit: tuple[dict[str, Any], ...], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get(field) or "") for row in audit).items()))


def _a1_direct_regression() -> dict[str, Any]:
    authority = _assert_a1_authority_unchanged()
    result = _run_a1_direct(TBGD_ROOT)
    if not result.get("ok"):
        _fail("a1_direct_behavior_regression")
    stable = {
        "predicates": result.get("predicates"),
        "source": result.get("source"),
        "flat_vs_graph_delta": result.get("flat_vs_graph_delta"),
        "reachable_blocker_representative": result.get("reachable_blocker_representative"),
        "external_legacy_representative": result.get("external_legacy_representative"),
    }
    return {
        "authority": authority,
        "behavior_digest": _json_digest(stable),
        "predicates": result.get("predicates"),
        "source": result.get("source"),
    }


def run_direct() -> None:
    if not TBGD_ROOT.is_dir():
        _fail(f"pinned_tbgd_missing:{TBGD_ROOT}")

    governance = _assert_governance_guards()
    started = time.perf_counter()
    (
        lowerer,
        ir,
        rulebook,
        audit,
        reconciled_denominator,
        focused_denominator,
        same_event_transitions,
    ) = _build_focused_direct_ir()
    del lowerer
    elapsed = time.perf_counter() - started
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if not isinstance(audit, tuple) or not audit:
        _fail("production_finalizer_audit_missing")
    if not reconciled_denominator:
        _fail("direct_source_denominator_empty")

    callbacks = {item.callback_id: item for item in ir.status_callbacks}
    tasks = {item.task_id: item for item in ir.status_callback_tasks}
    graphs = {
        item.standalone_ability_graph_id: item for item in ir.standalone_ability_graphs
    }
    phases = {item.phase_id: item for item in ir.ability_phases}
    families = {item.callback_event: item for item in ir.status_event_families}

    audit_by_key = {_denominator_key(row): row for row in audit}
    for expected in reconciled_denominator:
        key = _denominator_key(expected)
        audit_row = audit_by_key.get(key)
        task = tasks.get(expected["task_id"])
        callback = callbacks.get(expected["callback_id"])
        if audit_row is None or task is None or callback is None:
            _fail(f"reconciled_denominator_output_missing:{key}")
        if (
            task.coverage_status != audit_row.get("new_task_coverage_status")
            or task.blocked_reason != audit_row.get("new_task_blocked_reason")
        ):
            _fail(f"finalizer_audit_output_mismatch:{key}")
        if callback.coverage_status != (
            "executable" if not callback.blocked_reason else callback.coverage_status
        ):
            _fail(f"final_callback_coverage_inconsistent:{key}")
        if (
            task.linked_standalone_graph_id != expected["linked_standalone_graph_id"]
            or task.linked_ability_phase_id != expected["linked_ability_phase_id"]
        ):
            _fail(f"typed_link_identity_changed:{key}")

    promoted = [
        row for row in reconciled_denominator if row.get("decision") == "promoted"
    ]
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
    queue_root_graph_ids = set(
        focused_denominator["queue_resolution"]["executable_queue_root_graph_ids"]
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

        target_phase_ids = tuple(graphs[graph_id].phase_ids) if graph_id else (phase_id,)
        if not target_phase_ids or any(
            phases.get(target_phase_id) is None
            or phases[target_phase_id].invocation_role != "nested_only"
            for target_phase_id in target_phase_ids
        ):
            _fail("promoted_nested_target_role_not_resolved_with_queue_context")
        if formal_graph_id in queue_root_graph_ids:
            _fail("promoted_nested_target_is_executable_queue_root")

        entries = [
            item
            for item in materializations
            if item.entry_kind == "status_callback"
            and item.owner_id == callback.callback_id
            and item.status == "materialized"
        ]
        if (
            len(entries) != 1
            or not entries[0].graph_id
            or entries[0].graph_id not in task_graphs
        ):
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
        old_reason_lower = str(row["old_task_blocked_reason"]).lower()
        if "queue" in old_reason_lower or "deferred" in old_reason_lower:
            _fail("queue_or_deferred_blocker_was_promoted")

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
                "queue_root_conflict": False,
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

    for row in reconciled_denominator:
        if row.get("decision") == "promoted":
            continue
        task = tasks.get(str(row["task_id"]))
        if (
            task is not None
            and row.get("old_task_coverage_status") == "blocked"
            and task.coverage_status == "executable"
        ):
            _fail("negative_denominator_row_became_executable")

    a1 = _a1_direct_regression()
    evidence = {
        "mode": "direct",
        "builder": "focused_formal_character_source_denominator",
        "independent_denominator_builder": "pre_finalizer_source_backed_ir",
        "bidirectional_reconciliation": "exact",
        "focused_denominator": focused_denominator,
        "same_action_window_event_transitions": same_event_transitions,
        "wall_seconds": round(elapsed, 3),
        "peak_rss_kib": peak_rss,
        "denominator_count": len(reconciled_denominator),
        "promoted_count": len(promoted),
        "decision_histogram": _audit_histogram(audit, "decision"),
        "before_task_reason_histogram": _audit_histogram(
            audit, "old_task_blocked_reason"
        ),
        "after_task_status_histogram": _audit_histogram(
            audit, "new_task_coverage_status"
        ),
        "promoted_rows": promoted_ledger,
        "a1_regression": a1,
        "governance": governance,
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
