from __future__ import annotations

import argparse
import json
import resource
import time
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, TargetResolution, UnitState
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
from ..tbgd.lowering import TBGDLowering, build_character_action_definition_ir
from ..tbgd.task_graph_materializer import materialize_ability_task_graph_catalog
from ..systems.task_graph import (
    TaskGraphExecutionContext,
    TaskGraphExecutionHooks,
    TaskGraphLeafResult,
)
from .validate_p9_s8c1b_action_entry_weighted_selection import (
    DEFAULT_TBGD,
    _build_slice,
    _candidate_action_ids,
    _verify_selection,
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
    weighted = system._formal_task_graph_hooks(
        invocation=cast(Any, invocation)
    ).weighted_selection
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


def _execute_real_action(
    canonical: CanonicalIR,
    state: BattleState,
    *,
    action_id: str,
    action_level: int,
    metadata: dict[str, Any],
) -> tuple[BattleState, Any, ActionCommand, Any]:
    rules = RuleBook(canonical)
    executor = CombatExecutor(rules)
    query = executor.action_targets.query(state, "actor", action_id, action_level)
    if not query.resolved:
        raise RuntimeError(f"target_query:{query.blocked_reason}")
    if query.selection_mode == "automatic":
        submitted: tuple[str, ...] = ()
    else:
        minimum = query.selection_min or 1
        submitted = tuple(query.candidate_ids[:minimum])
        if len(submitted) < minimum:
            raise RuntimeError("target_query:not_enough_candidates")
    accepted = executor.action_targets.accept(state, query, submitted)
    if not accepted.accepted or accepted.context is None:
        raise RuntimeError(f"target_accept:{accepted.blocked_reason}")
    command = ActionCommand(
        "actor",
        action_id,
        action_level,
        submitted,
        metadata=cast(dict[str, Any], metadata),
    )
    after, transition = executor.execute(
        command,
        state,
        target_selection_context=accepted.context,
    )
    return after, transition, command, accepted.context


def _real_action_state(owner_entity_ref: str, current_window: str) -> BattleState:
    return BattleState(
        units={
            "actor": UnitState(
                "actor",
                "ally",
                owner_entity_ref,
                level=80,
                max_hp=100000.0,
                hp=100000.0,
                attack=5000.0,
                defense=2000.0,
                speed=120.0,
                energy=1000.0,
                max_energy=1000.0,
                flags={"position": 0},
                resources={
                    "recoverable_hp": 0.0,
                    "special_energy": 1000.0,
                    "special_resource": 1000.0,
                },
            ),
            "ally": UnitState(
                "ally",
                "ally",
                "avatar:validation_ally",
                level=80,
                max_hp=100000.0,
                hp=100000.0,
                attack=1000.0,
                defense=1000.0,
                speed=100.0,
                flags={"position": 1},
            ),
            "enemy": UnitState(
                "enemy",
                "enemy",
                "monster:validation_enemy",
                level=80,
                max_hp=10000000.0,
                hp=10000000.0,
                attack=1000.0,
                defense=1000.0,
                speed=100.0,
                toughness=1000.0,
                max_toughness=1000.0,
                flags={"position": 0, "weaknesses": ["Physical", "Fire", "Ice", "Thunder", "Wind", "Quantum", "Imaginary"]},
            ),
        },
        skill_points=5,
        max_skill_points=5,
        global_flags={
            "phase": "battle",
            "current_window": current_window,
            "turn_owner_id": "actor",
            "global_av": 0.0,
        },
        rng_state="p9-s8c-r1-direct-seed",
    )


def _selection_rng_events(transition: Any, selection_id: str) -> tuple[Any, ...]:
    events: list[Any] = []
    for event in transition.rng_events:
        metadata = event.metadata if isinstance(event.metadata, Mapping) else {}
        result = event.result if isinstance(event.result, Mapping) else {}
        if metadata.get("selection_id") == selection_id or result.get("selection_id") == selection_id:
            events.append(event)
    return tuple(events)


def _ledger_entry(event: Any) -> dict[str, Any]:
    result = event.result if isinstance(event.result, Mapping) else {}
    key = result.get("choice_key")
    choice = result.get("selected_outcome_id")
    if not isinstance(key, str) or not key or not isinstance(choice, str) or not choice:
        raise RuntimeError(f"non_replayable_rng_event:{event.event_id}")
    return {"choice_key": key, "choice": choice}


def _run_direct(root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    lowering = TBGDLowering(root)
    source_graph = lowering.build_character_ability_source_graph_catalog()
    snapshot = lowering._character_ability_raw_snapshot
    scope = lowering._character_ability_scope_catalog
    if snapshot is None or scope is None:
        raise AssertionError("production signed character ability source context is unavailable")
    source_catalog = lowering.build_character_control_flow_contract_catalog(
        snapshot=snapshot,
        scope_catalog=scope,
    )
    candidate_ids = _candidate_action_ids(source_graph, source_catalog)
    if not candidate_ids:
        raise AssertionError("no real formal action RandomConfig candidate exists")
    definitions_by_action: dict[str, list[Any]] = defaultdict(list)
    for definition in build_character_action_definition_ir(root):
        definitions_by_action[definition.action_id].append(definition)

    failures: list[str] = []
    selected_output: dict[str, Any] | None = None
    for action_id in candidate_ids:
        if time.perf_counter() - started > 210.0:
            break
        definitions = sorted(
            definitions_by_action.get(action_id, ()),
            key=lambda item: item.level,
        )
        for definition in definitions:
            if time.perf_counter() - started > 210.0:
                break
            try:
                canonical = _build_slice(
                    lowering,
                    definition,
                    snapshot,
                    scope,
                    source_graph,
                )
                ability_catalog = materialize_ability_task_graph_catalog(
                    source_catalog,
                    canonical,
                    source_snapshot=snapshot,
                )
            except (TypeError, ValueError, RuntimeError) as exc:
                failures.append(
                    f"{action_id}:{definition.level}:materialize:{type(exc).__name__}:{exc}"
                )
                continue
            graphs = tuple(
                graph
                for graph in ability_catalog.graphs
                if graph.entry_kind == "ability_phase_callback"
                and graph.weighted_selections
            )
            for graph in graphs:
                selection = graph.weighted_selections[0]
                random_node = next(
                    (
                        node
                        for node in graph.nodes
                        if node.graph_node_id == selection.graph_node_id
                    ),
                    None,
                )
                if (
                    random_node is None
                    or random_node.materialization_status != "materialized"
                    or random_node.owner_domains != ("task_graph_execution",)
                ):
                    failures.append(
                        f"{action_id}:{definition.level}:{graph.entry_id}:random_config_not_runtime_materialized"
                    )
                    continue
                try:
                    source_evidence = _verify_selection(snapshot, graph)
                except (AssertionError, TypeError, ValueError) as exc:
                    failures.append(
                        f"{action_id}:{definition.level}:{graph.entry_id}:source:{type(exc).__name__}:{exc}"
                    )
                    continue
                runtime_canonical = replace(
                    canonical,
                    task_graph_catalog=ability_catalog,
                )
                admissions = tuple(
                    admission
                    for admission in runtime_canonical.action_admissions
                    if admission.action_id == action_id
                    and admission.action_level == definition.level
                    and admission.coverage_status == "executable"
                    and "external_turn" in admission.submission_modes
                    and admission.allowed_windows
                )
                if not admissions:
                    failures.append(
                        f"{action_id}:{definition.level}:{graph.entry_id}:no_external_turn_admission"
                    )
                    continue
                for admission in admissions:
                    for current_window in admission.allowed_windows:
                        if time.perf_counter() - started > 210.0:
                            break
                        state = _real_action_state(
                            admission.owner_entity_ref,
                            current_window,
                        )
                        try:
                            after, transition, command, _ = _execute_real_action(
                                runtime_canonical,
                                state,
                                action_id=action_id,
                                action_level=definition.level,
                                metadata={"rng_mode": "deterministic_seed"},
                            )
                        except (AssertionError, TypeError, ValueError, RuntimeError, KeyError) as exc:
                            failures.append(
                                f"{action_id}:{definition.level}:{current_window}:execute:{type(exc).__name__}:{exc}"
                            )
                            continue
                        if not transition.outcome.successor_eligible:
                            failures.append(
                                f"{action_id}:{definition.level}:{current_window}:blocked:"
                                + ",".join(transition.outcome.reason_codes[:4])
                            )
                            continue
                        selection_events = _selection_rng_events(
                            transition,
                            selection.selection_id,
                        )
                        if len(selection_events) != 1:
                            failures.append(
                                f"{action_id}:{definition.level}:{current_window}:selection_rng_count:{len(selection_events)}"
                            )
                            continue
                        event = selection_events[0]
                        result_payload = (
                            event.result if isinstance(event.result, Mapping) else {}
                        )
                        selected_choice_id = result_payload.get(
                            "selected_outcome_id"
                        )
                        if selected_choice_id not in {
                            choice.choice_id for choice in selection.choices
                        }:
                            failures.append(
                                f"{action_id}:{definition.level}:{current_window}:selected_choice_identity_mismatch"
                            )
                            continue
                        deterministic_ledger = validate_rng_choice_ledger(
                            dict(command.metadata),
                            transition.rng_events,
                        )
                        rng_nodes = tuple(
                            node
                            for node in transition.outcome.node_results
                            if node.node_kind == "rng_ledger"
                        )
                        if (
                            not deterministic_ledger.ok
                            or len(rng_nodes) != 1
                            or not rng_nodes[0].complete
                        ):
                            failures.append(
                                f"{action_id}:{definition.level}:{current_window}:whole_action_rng_ledger_not_complete"
                            )
                            continue
                        try:
                            ledger_entries = [
                                _ledger_entry(item)
                                for item in transition.rng_events
                            ]
                        except RuntimeError as exc:
                            failures.append(
                                f"{action_id}:{definition.level}:{current_window}:{exc}"
                            )
                            continue
                        if not ledger_entries:
                            failures.append(
                                f"{action_id}:{definition.level}:{current_window}:empty_rng_ledger"
                            )
                            continue
                        explicit_meta = {
                            "rng_mode": "explicit_ledger",
                            "rng_choice_ledger": ledger_entries,
                        }
                        try:
                            explicit_after, explicit_transition, explicit_command, _ = _execute_real_action(
                                runtime_canonical,
                                state,
                                action_id=action_id,
                                action_level=definition.level,
                                metadata=explicit_meta,
                            )
                        except (AssertionError, TypeError, ValueError, RuntimeError, KeyError) as exc:
                            failures.append(
                                f"{action_id}:{definition.level}:{current_window}:replay:{type(exc).__name__}:{exc}"
                            )
                            continue
                        explicit_selection_events = _selection_rng_events(
                            explicit_transition,
                            selection.selection_id,
                        )
                        explicit_ledger = validate_rng_choice_ledger(
                            dict(explicit_command.metadata),
                            explicit_transition.rng_events,
                        )
                        explicit_rng_nodes = tuple(
                            node
                            for node in explicit_transition.outcome.node_results
                            if node.node_kind == "rng_ledger"
                        )
                        if (
                            not explicit_transition.outcome.successor_eligible
                            or len(explicit_selection_events) != 1
                            or not explicit_ledger.ok
                            or len(explicit_rng_nodes) != 1
                            or not explicit_rng_nodes[0].complete
                            or explicit_selection_events[0].result
                            != event.result
                        ):
                            failures.append(
                                f"{action_id}:{definition.level}:{current_window}:explicit_replay_not_identical"
                            )
                            continue

                        rc_result = (
                            event.result
                            if isinstance(event.result, Mapping)
                            else {}
                        )
                        rc_key = rc_result.get("choice_key")
                        if not isinstance(rc_key, str) or not rc_key:
                            failures.append(
                                f"{action_id}:{definition.level}:{current_window}:selection_choice_key_missing"
                            )
                            continue
                        stale_entries = [
                            dict(item) for item in ledger_entries
                        ]
                        replaced_key = False
                        for entry in stale_entries:
                            if entry.get("choice_key") == rc_key:
                                entry["choice_key"] = rc_key + ":stale"
                                replaced_key = True
                                break
                        if not replaced_key:
                            failures.append(
                                f"{action_id}:{definition.level}:{current_window}:selection_ledger_entry_missing"
                            )
                            continue
                        try:
                            stale_after, stale_transition, _, _ = _execute_real_action(
                                runtime_canonical,
                                state,
                                action_id=action_id,
                                action_level=definition.level,
                                metadata={
                                    "rng_mode": "explicit_ledger",
                                    "rng_choice_ledger": stale_entries,
                                },
                            )
                        except (AssertionError, TypeError, ValueError, RuntimeError, KeyError) as exc:
                            failures.append(
                                f"{action_id}:{definition.level}:{current_window}:stale_execute:{type(exc).__name__}:{exc}"
                            )
                            continue
                        if (
                            stale_transition.outcome.successor_eligible
                            or stale_after != state
                            or stale_transition.transaction.mutations
                            or stale_transition.rng_events
                        ):
                            failures.append(
                                f"{action_id}:{definition.level}:{current_window}:stale_ledger_not_atomic"
                            )
                            continue

                        selected_output = {
                            "action_id": action_id,
                            "action_level": definition.level,
                            "owner_entity_ref": admission.owner_entity_ref,
                            "window": current_window,
                            "phase_id": graph.owner_id,
                            "callback_kind": graph.callback_kind,
                            "graph_id": graph.graph_id,
                            "selection_id": selection.selection_id,
                            "source": source_evidence,
                            "denominator": len(selection.choices),
                            "choice_ids": [
                                choice.choice_id
                                for choice in selection.choices
                            ],
                            "selected_choice_id": selected_choice_id,
                            "choice_key": rc_key,
                            "rng_event_id": event.event_id,
                            "whole_action_rng_event_count": len(
                                transition.rng_events
                            ),
                            "whole_action_ledger": deterministic_ledger.to_json(),
                            "explicit_ledger": explicit_ledger.to_json(),
                            "stale_outcome": stale_transition.outcome.to_json(),
                            "committed_state_changed": after != state,
                            "explicit_state_matches_deterministic": explicit_after == after,
                        }
                        break
                    if selected_output is not None:
                        break
                if selected_output is not None:
                    break
            if selected_output is not None:
                break
        if selected_output is not None:
            break

    if selected_output is None:
        raise AssertionError(
            "no real formal action RandomConfig completed CombatExecutor transaction:"
            + json.dumps(failures[-12:], ensure_ascii=False)
        )
    elapsed = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "ok": elapsed <= _DIRECT_LIMIT and peak <= 1024 * 1024,
        "mode": "direct",
        "predicates": {
            "dynamic_real_formal_action_random_config": True,
            "signed_source_weight_choice_branch_closure": True,
            "action_random_config_runtime_materialized": True,
            "combat_executor_action_transaction": True,
            "formal_ability_and_shared_executor": True,
            "existing_rng_authority": True,
            "exact_one_random_config_rng_event": True,
            "whole_action_rng_ledger_complete": True,
            "explicit_replay_identical": True,
            "stale_explicit_choice_atomic_block": True,
            "synthetic_runtime_stitching_used": False,
        },
        "representative": selected_output,
        "discovery_failures_before_success": failures[-8:],
        "resource": {
            "wall_seconds": round(elapsed, 6),
            "peak_rss_kib": peak,
        },
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
