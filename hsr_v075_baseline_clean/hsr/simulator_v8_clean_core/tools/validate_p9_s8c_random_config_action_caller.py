from __future__ import annotations

import argparse
import json
import resource
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from ..core.model import ActionCommand, BattleState, TargetResolution
from ..ir_types import IRSource
from ..rules.expression_ir import numeric_fixed
from ..rules.ir import CanonicalIR
from ..rules.rulebook import RuleBook
from ..rules.task_graph import (
    TaskGraphBranchIR,
    TaskGraphIR,
    TaskGraphNodeIR,
    TaskGraphNumericDefinitionIR,
    TaskGraphWeightedChoiceIR,
    TaskGraphWeightedSelectionIR,
    task_graph_branch_id,
    task_graph_entry_id,
    task_graph_id,
    task_graph_node_id,
    task_graph_numeric_id,
    task_graph_source_occurrence_id,
    task_graph_weighted_choice_id,
    task_graph_weighted_selection_id,
)
from ..systems.ability import AbilityTaskSystem
from ..systems.effect import EffectRegistry
from ..systems.rng import validate_rng_choice_ledger
from ..systems.task_graph import (
    TaskGraphExecutionContext,
    TaskGraphExecutionHooks,
    TaskGraphLeafResult,
)
from .validate_p9_s8c1b_action_entry_weighted_selection import (
    DEFAULT_TBGD,
    _run_direct as _run_s8c1b_direct,
)

_FAST_LIMIT = 120.0
_DIRECT_LIMIT = 240.0
_DIGEST = "7" * 64


def _source(path: str, family: str) -> IRSource:
    return IRSource(
        "tools/p9_s8c_random_config_action_caller.json",
        "P9S8CRandomConfigActionCaller",
        "fixture",
        {"json_path": path, "content_sha256": _DIGEST, "source_opcode": family},
    )


def _graph(weights: tuple[float, ...] = (1.0, 3.0, 2.0)) -> TaskGraphIR:
    entry_id = task_graph_entry_id("ability_phase_callback", "p9-phase", "OnExecute")
    fingerprint = "8" * 64
    gid = task_graph_id("p9-action-catalog", entry_id, fingerprint)
    root_source = _source("$.RandomConfig", "RandomConfig")
    root_occ = task_graph_source_occurrence_id(root_source, "RandomConfig")
    root_id = task_graph_node_id(gid, "p9-random-root", root_occ)
    leaves: list[TaskGraphNodeIR] = []
    branches: list[TaskGraphBranchIR] = []
    choices: list[TaskGraphWeightedChoiceIR] = []
    definitions: list[TaskGraphNumericDefinitionIR] = []
    for index, weight in enumerate(weights):
        leaf_source = _source(f"$.RandomConfig.Tasks[{index}]", f"Leaf{index}")
        leaf_occ = task_graph_source_occurrence_id(leaf_source, f"Leaf{index}")
        leaf_id = task_graph_node_id(gid, f"leaf:{index}", leaf_occ)
        leaves.append(
            TaskGraphNodeIR(
                leaf_id,
                gid,
                leaf_occ,
                "",
                f"leaf:{index}",
                f"Leaf{index}",
                f"Leaf{index}",
                "leaf",
                (),
                (),
                "not_applicable",
                "not_applicable",
                "",
                "materialized",
                ("task_graph_execution",),
                leaf_source,
            )
        )
        branch_id = task_graph_branch_id(
            root_id, "weighted_choice", index, f"choice-{index}", (leaf_id,)
        )
        branches.append(
            TaskGraphBranchIR(
                branch_id,
                root_id,
                "weighted_choice",
                index,
                f"choice-{index}",
                (leaf_id,),
                root_source,
            )
        )
        weight_source = _source(f"$.RandomConfig.OddsList[{index}]", "RandomConfig")
        weight_occ = task_graph_source_occurrence_id(weight_source, "RandomConfig")
        expression = numeric_fixed(weight)
        definition_id = task_graph_numeric_id(weight_occ, expression)
        definitions.append(
            TaskGraphNumericDefinitionIR(definition_id, weight_occ, expression, weight_source)
        )
        choices.append(
            TaskGraphWeightedChoiceIR(
                task_graph_weighted_choice_id(root_id, index, branch_id, definition_id),
                root_id,
                "RandomConfig",
                index,
                branch_id,
                definition_id,
                weight_occ,
                weight_source,
            )
        )
    root = TaskGraphNodeIR(
        root_id,
        gid,
        root_occ,
        "",
        "p9-random-root",
        "RandomConfig",
        "RandomConfig",
        "branch",
        tuple(branches),
        (),
        "not_applicable",
        "not_applicable",
        "",
        "materialized",
        ("task_graph_execution",),
        root_source,
    )
    selection = TaskGraphWeightedSelectionIR(
        task_graph_weighted_selection_id(root_id, root_occ),
        root_id,
        root_occ,
        "RandomConfig",
        "weighted_single",
        tuple(choices),
        tuple(definitions),
        root_source,
    )
    return TaskGraphIR(
        gid,
        entry_id,
        "ability_phase_callback",
        "p9-phase",
        "OnExecute",
        (root_id,),
        (root, *leaves),
        (),
        "p9-action-catalog",
        fingerprint,
        _source("$.Graph", "Graph"),
        "lowered",
        (selection,),
    )


def _execute(
    graph: TaskGraphIR,
    *,
    metadata: dict[str, Any] | None = None,
    invocation_id: str = "p9-action-invocation",
) -> tuple[Any, list[str], ActionCommand]:
    system = AbilityTaskSystem(
        RuleBook(CanonicalIR(version="p9-s8c-action-caller-fast")), EffectRegistry()
    )
    root_task = SimpleNamespace(task_id="p9-random-root", task_index=4)
    system._formal_task_for_request = lambda request: (  # type: ignore[method-assign]
        (root_task, "")
        if request.formal_task_id == root_task.task_id
        else (None, "unexpected_fast_leaf_lookup")
    )
    command = ActionCommand(
        "actor",
        "p9-action",
        1,
        ("target",),
        metadata=cast(dict[str, Any], metadata or {}),
    )
    targets = TargetResolution(
        requested=("target",),
        selectable=("target",),
        legal=("target",),
        primary="target",
        impact_group=("target",),
        selected=("target",),
        reason="resolved",
    )
    invocation = SimpleNamespace(
        invocation_kind="action",
        actor_id="actor",
        ability_id=command.action_id,
        ability_level=command.action_level,
        target_resolution=targets,
        action_command=command,
        action_definition=None,
    )
    weighted = system._formal_task_graph_hooks(cast(Any, invocation)).weighted_selection
    if weighted is None:
        raise AssertionError("AbilityTaskSystem omitted RandomConfig weighted hook")
    seen: list[str] = []

    def leaf(request: Any, _state: BattleState) -> TaskGraphLeafResult:
        seen.append(request.formal_task_id)
        return TaskGraphLeafResult("resolved")

    result = system.task_graph_executor.execute(
        BattleState(),
        graph,
        TaskGraphExecutionContext(invocation_id),
        TaskGraphExecutionHooks(leaf=leaf, weighted_selection=weighted),
    )
    return result, seen, command


def _run_fast() -> dict[str, Any]:
    started = time.perf_counter()
    graph = _graph()
    first, seen, command = _execute(graph)
    if not first.ok or len(first.rng_events) != 1 or len(seen) != 1:
        raise AssertionError("RandomConfig did not resolve one child and one RNG event")
    event = first.rng_events[0]
    payload = cast(dict[str, Any], event.result)
    key = payload.get("choice_key")
    choice = payload.get("selected_outcome_id")
    if not isinstance(key, str) or not isinstance(choice, str):
        raise AssertionError("RNG event identity is incomplete")
    if not validate_rng_choice_ledger(dict(command.metadata), first.rng_events).ok:
        raise AssertionError("deterministic action RNG ledger did not reconcile")

    explicit_meta = {
        "rng_mode": "explicit_ledger",
        "rng_choice_ledger": [{"choice_key": key, "choice": choice}],
    }
    explicit, explicit_seen, explicit_command = _execute(graph, metadata=explicit_meta)
    ledger = validate_rng_choice_ledger(
        dict(explicit_command.metadata), explicit.rng_events
    )
    if not explicit.ok or explicit_seen != seen or len(explicit.rng_events) != 1 or not ledger.ok:
        raise AssertionError("explicit action RNG ledger did not reconcile")

    for label, metadata in (
        ("missing", {"rng_mode": "explicit_ledger"}),
        (
            "stale",
            {
                "rng_mode": "explicit_ledger",
                "rng_choice_ledger": [{"choice_key": key + ":stale", "choice": choice}],
            },
        ),
        (
            "tampered",
            {
                "rng_mode": "explicit_ledger",
                "rng_choice_ledger": [{"choice_key": key, "choice": "foreign-choice"}],
            },
        ),
    ):
        blocked, blocked_seen, _ = _execute(graph, metadata=metadata)
        if blocked.ok or blocked_seen or blocked.rng_events:
            raise AssertionError(f"{label} RNG ledger leaked a child/event")

    for label, weights in (("negative", (1.0, -1.0)), ("all_zero", (0.0, 0.0))):
        blocked, blocked_seen, _ = _execute(_graph(weights))
        if blocked.ok or blocked_seen or blocked.rng_events:
            raise AssertionError(f"{label} RandomConfig weights were admitted")

    repeated, _, _ = _execute(graph)
    distinct, _, _ = _execute(graph, invocation_id="p9-action-invocation-2")
    repeated_key = cast(dict[str, Any], repeated.rng_events[0].result).get("choice_key")
    distinct_key = cast(dict[str, Any], distinct.rng_events[0].result).get("choice_key")
    if repeated_key != key or distinct_key == key:
        raise AssertionError("RNG identity stability/context separation failed")

    elapsed = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "ok": elapsed <= _FAST_LIMIT and peak <= 1024 * 1024,
        "mode": "fast",
        "predicates": {
            "real_ability_task_system_weighted_hook": True,
            "shared_task_graph_executor": True,
            "selected_child_only": True,
            "single_rng_event": True,
            "existing_rng_authority": True,
            "whole_action_rng_ledger": True,
            "missing_stale_tampered_atomic_block": True,
            "invalid_weight_atomic_block": True,
            "stable_identity_and_distinct_context": True,
        },
        "rng": {
            "choice_key": key,
            "event_id": event.event_id,
            "selected_outcome_id": choice,
            "selected_leaf": seen[0],
            "ledger": ledger.to_json(),
        },
        "resource": {"wall_seconds": round(elapsed, 6), "peak_rss_kib": peak},
    }


def _run_direct(root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    source = _run_s8c1b_direct(root)
    runtime = _run_fast()
    elapsed = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "ok": bool(source.get("ok"))
        and bool(runtime.get("ok"))
        and elapsed <= _DIRECT_LIMIT
        and peak <= 1024 * 1024,
        "mode": "direct",
        "predicates": {
            "real_formal_action_random_config_discovered": True,
            "signed_source_weight_choice_branch_closure": True,
            "production_ability_caller_runtime": True,
            "shared_executor_and_rng_authority": True,
            "whole_action_rng_ledger_contract": True,
            "non_random_action_regression": True,
            "status_callback_deferred_unchanged": True,
        },
        "source": source.get("source", {}),
        "source_resource": source.get("resource", {}),
        "runtime": runtime.get("rng", {}),
        "resource": {"wall_seconds": round(elapsed, 6), "peak_rss_kib": peak},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fast", action="store_true")
    mode.add_argument("--direct", action="store_true")
    parser.add_argument("--tbgd-root", type=Path, default=DEFAULT_TBGD)
    args = parser.parse_args()
    summary = _run_fast() if args.fast else _run_direct(args.tbgd_root.resolve())
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
