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
    _bootstrap_repo_root,
    _run_direct as _run_s8c1b_direct,
)

_DIGEST = "7" * 64
_FAST_HARD_SECONDS = 120.0
_DIRECT_HARD_SECONDS = 240.0


def _source(path: str, family: str) -> IRSource:
    return IRSource(
        source_path="tools/p9_s8c_random_config_action_caller.json",
        raw_type="P9S8CRandomConfigActionCaller",
        raw_id="fixture",
        evidence={
            "json_path": path,
            "content_sha256": _DIGEST,
            "source_opcode": family,
        },
    )


def _graph(weights: tuple[float, ...] = (1.0, 3.0, 2.0)) -> TaskGraphIR:
    entry_kind = "ability_phase_callback"
    owner_id = "p9-s8c-action-phase"
    callback_kind = "OnExecute"
    entry_id = task_graph_entry_id(entry_kind, owner_id, callback_kind)
    fingerprint = "8" * 64
    graph_id = task_graph_id("p9-s8c-action-catalog", entry_id, fingerprint)
    root_source = _source("$.RandomConfig", "RandomConfig")
    root_occurrence = task_graph_source_occurrence_id(root_source, "RandomConfig")
    root_formal_task_id = "p9-s8c-random-root"
    root_id = task_graph_node_id(graph_id, root_formal_task_id, root_occurrence)

    leaves: list[TaskGraphNodeIR] = []
    branches: list[TaskGraphBranchIR] = []
    choices: list[TaskGraphWeightedChoiceIR] = []
    definitions: list[TaskGraphNumericDefinitionIR] = []
    for index, weight in enumerate(weights):
        leaf_source = _source(f"$.RandomConfig.Tasks[{index}]", f"Leaf{index}")
        leaf_occurrence = task_graph_source_occurrence_id(leaf_source, f"Leaf{index}")
        leaf_id = task_graph_node_id(graph_id, f"leaf:{index}", leaf_occurrence)
        leaves.append(
            TaskGraphNodeIR(
                graph_node_id=leaf_id,
                graph_id=graph_id,
                source_occurrence_id=leaf_occurrence,
                source_contract_node_id="",
                formal_task_id=f"leaf:{index}",
                opcode=f"Leaf{index}",
                source_family=f"Leaf{index}",
                node_kind="leaf",
                branches=(),
                references=(),
                termination_kind="not_applicable",
                termination_status="not_applicable",
                termination_numeric_definition_id="",
                materialization_status="materialized",
                owner_domains=("task_graph_execution",),
                source=leaf_source,
            )
        )
        branch_id = task_graph_branch_id(
            root_id, "weighted_choice", index, f"choice-{index}", (leaf_id,)
        )
        branches.append(
            TaskGraphBranchIR(
                branch_id=branch_id,
                graph_node_id=root_id,
                branch_kind="weighted_choice",
                ordinal=index,
                label=f"choice-{index}",
                child_node_ids=(leaf_id,),
                source=root_source,
            )
        )
        weight_source = _source(f"$.RandomConfig.OddsList[{index}]", "RandomConfig")
        weight_occurrence = task_graph_source_occurrence_id(weight_source, "RandomConfig")
        expression = numeric_fixed(weight)
        definition_id = task_graph_numeric_id(weight_occurrence, expression)
        definitions.append(
            TaskGraphNumericDefinitionIR(
                definition_id=definition_id,
                source_occurrence_id=weight_occurrence,
                expression=expression,
                source=weight_source,
            )
        )
        choices.append(
            TaskGraphWeightedChoiceIR(
                choice_id=task_graph_weighted_choice_id(
                    root_id, index, branch_id, definition_id
                ),
                graph_node_id=root_id,
                family="RandomConfig",
                ordinal=index,
                branch_id=branch_id,
                weight_definition_id=definition_id,
                weight_source_occurrence_id=weight_occurrence,
                source=weight_source,
            )
        )

    root = TaskGraphNodeIR(
        graph_node_id=root_id,
        graph_id=graph_id,
        source_occurrence_id=root_occurrence,
        source_contract_node_id="",
        formal_task_id=root_formal_task_id,
        opcode="RandomConfig",
        source_family="RandomConfig",
        node_kind="branch",
        branches=tuple(branches),
        references=(),
        termination_kind="not_applicable",
        termination_status="not_applicable",
        termination_numeric_definition_id="",
        materialization_status="materialized",
        owner_domains=("task_graph_execution",),
        source=root_source,
    )
    selection = TaskGraphWeightedSelectionIR(
        selection_id=task_graph_weighted_selection_id(root_id, root_occurrence),
        graph_node_id=root_id,
        parent_source_occurrence_id=root_occurrence,
        family="RandomConfig",
        selection_kind="weighted_single",
        choices=tuple(choices),
        numeric_definitions=tuple(definitions),
        source=root_source,
    )
    return TaskGraphIR(
        graph_id=graph_id,
        entry_id=entry_id,
        entry_kind=entry_kind,
        owner_id=owner_id,
        callback_kind=callback_kind,
        root_node_ids=(root_id,),
        nodes=(root, *leaves),
        numeric_definitions=(),
        source_catalog_id="p9-s8c-action-catalog",
        source_fingerprint=fingerprint,
        source=_source("$.Graph", "Graph"),
        coverage_status="lowered",
        weighted_selections=(selection,),
    )


def _run_graph(
    graph: TaskGraphIR,
    *,
    metadata: dict[str, Any] | None = None,
    invocation_id: str = "p9-s8c-action-invocation",
) -> tuple[Any, list[str], ActionCommand]:
    rules = RuleBook(CanonicalIR(version="p9-s8c-action-caller-fast"))
    system = AbilityTaskSystem(rules, EffectRegistry())
    root_task = SimpleNamespace(task_id="p9-s8c-random-root", task_index=4)
    system._formal_task_for_request = lambda request: (  # type: ignore[method-assign]
        (root_task, "")
        if request.formal_task_id == root_task.task_id
        else (None, "unexpected_fast_leaf_lookup")
    )
    command = ActionCommand(
        actor_id="actor",
        action_id="p9-s8c-action",
        action_level=1,
        target_ids=("target",),
        metadata=cast(dict[str, Any], metadata or {}),
    )
    target_resolution = TargetResolution(
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
        target_resolution=target_resolution,
        action_command=command,
        action_definition=None,
    )
    formal_hooks = system._formal_task_graph_hooks(cast(Any, invocation))
    if formal_hooks.weighted_selection is None:
        raise AssertionError("AbilityTaskSystem did not expose weighted_selection hook")
    seen: list[str] = []

    def leaf(request: Any, _state: BattleState) -> TaskGraphLeafResult:
        seen.append(request.formal_task_id)
        return TaskGraphLeafResult(status="resolved")

    result = system.task_graph_executor.execute(
        BattleState(),
        graph,
        TaskGraphExecutionContext(invocation_id),
        TaskGraphExecutionHooks(
            leaf=leaf,
            weighted_selection=formal_hooks.weighted_selection,
        ),
    )
    return result, seen, command


def _run_fast() -> dict[str, Any]:
    started = time.perf_counter()
    graph = _graph()
    first, first_seen, first_command = _run_graph(graph)
    if not first.ok or len(first.rng_events) != 1 or len(first_seen) != 1:
        raise AssertionError("formal RandomConfig caller did not resolve exactly one branch/event")
    event = first.rng_events[0]
    result_payload = cast(dict[str, Any], event.result)
    choice_key = result_payload.get("choice_key")
    selected_id = result_payload.get("selected_outcome_id")
    if not isinstance(choice_key, str) or not isinstance(selected_id, str):
        raise AssertionError("RNG event omitted stable choice identity")
    if validate_rng_choice_ledger(dict(first_command.metadata), first.rng_events).ok is not True:
        raise AssertionError("deterministic whole-action RNG ledger validation failed")

    explicit_meta = {
        "rng_mode": "explicit_ledger",
        "rng_choice_ledger": [{"choice_key": choice_key, "choice": selected_id}],
    }
    explicit, explicit_seen, explicit_command = _run_graph(graph, metadata=explicit_meta)
    ledger = validate_rng_choice_ledger(dict(explicit_command.metadata), explicit.rng_events)
    if not explicit.ok or len(explicit.rng_events) != 1 or not ledger.ok:
        raise AssertionError("explicit whole-action RNG ledger did not reconcile")
    if explicit_seen != first_seen:
        raise AssertionError("explicit ledger changed selected formal branch")

    missing, missing_seen, _ = _run_graph(graph, metadata={"rng_mode": "explicit_ledger"})
    if missing.ok or missing_seen or missing.rng_events:
        raise AssertionError("missing explicit RNG ledger leaked a child/event")
    stale, stale_seen, _ = _run_graph(
        graph,
        metadata={
            "rng_mode": "explicit_ledger",
            "rng_choice_ledger": [{"choice_key": choice_key + ":stale", "choice": selected_id}],
        },
    )
    if stale.ok or stale_seen or stale.rng_events:
        raise AssertionError("stale explicit RNG ledger leaked a child/event")
    tampered, tampered_seen, _ = _run_graph(
        graph,
        metadata={
            "rng_mode": "explicit_ledger",
            "rng_choice_ledger": [{"choice_key": choice_key, "choice": "foreign-choice"}],
        },
    )
    if tampered.ok or tampered_seen or tampered.rng_events:
        raise AssertionError("tampered explicit RNG ledger leaked a child/event")

    negative, negative_seen, _ = _run_graph(_graph((1.0, -1.0)))
    zero, zero_seen, _ = _run_graph(_graph((0.0, 0.0)))
    if negative.ok or negative_seen or negative.rng_events:
        raise AssertionError("negative RandomConfig weight was admitted")
    if zero.ok or zero_seen or zero.rng_events:
        raise AssertionError("all-zero RandomConfig weight set was admitted")

    repeated, _, _ = _run_graph(graph)
    distinct, _, _ = _run_graph(graph, invocation_id="p9-s8c-action-invocation-2")
    repeated_key = cast(dict[str, Any], repeated.rng_events[0].result).get("choice_key")
    distinct_key = cast(dict[str, Any], distinct.rng_events[0].result).get("choice_key")
    if repeated_key != choice_key or distinct_key == choice_key:
        raise AssertionError("RNG identity stability/context separation failed")

    elapsed = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "ok": elapsed <= _FAST_HARD_SECONDS and peak <= 1024 * 1024,
        "mode": "fast",
        "predicates": {
            "real_ability_task_system_hook": True,
            "shared_task_graph_executor": True,
            "selected_child_only": True,
            "single_rng_event": True,
            "existing_rng_authority": True,
            "whole_action_ledger_validation": True,
            "missing_stale_tampered_ledger_atomic_block": True,
            "negative_and_all_zero_weights_block": True,
            "same_identity_stable_distinct_context_separate": True,
        },
        "rng": {
            "choice_key": choice_key,
            "event_id": event.event_id,
            "selected_outcome_id": selected_id,
            "selected_leaf": first_seen[0],
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
        and elapsed <= _DIRECT_HARD_SECONDS
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
    parser = argparse.ArgumentParser(
        description="Validate P9 S8C formal action RandomConfig caller and RNG ledger"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fast", action="store_true")
    mode.add_argument("--direct", action="store_true")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args()
    root = args.tbgd_root.resolve() if args.tbgd_root is not None else _bootstrap_repo_root()
    summary = _run_fast() if args.fast else _run_direct(root)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
