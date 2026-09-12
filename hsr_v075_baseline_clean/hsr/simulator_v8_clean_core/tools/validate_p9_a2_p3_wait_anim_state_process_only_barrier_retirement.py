from __future__ import annotations

import argparse
import json
import os
import random
import resource
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
BASELINE = ROOT / "hsr_v075_baseline_clean"
TBGD = ROOT / "turnbasedgamedata-main"
BASE_SHA = "eedebb406b85ab2611e8345b3fe7a75e9a7c53a0"
TBGD_PIN = "14c1d18f91a8101d610e6c523447a7517de3fae1"
MATERIALIZER = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py"
TEST = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_p9_a2_p3_wait_anim_state_process_only_barrier_retirement.py"
VALIDATOR = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p3_wait_anim_state_process_only_barrier_retirement.py"
REPORT = "hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2-P3_S8C_WAIT_ANIM_STATE_PROCESS_ONLY_BARRIER_RETIREMENT_execution_report.md"
CARD = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-A2-P3_S8C_WAIT_ANIM_STATE_PROCESS_ONLY_BARRIER_RETIREMENT.md"
ALLOWED = {MATERIALIZER, TEST, VALIDATOR, REPORT, CARD}
READ_ONLY = (
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/coverage.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/character_control_flow_contracts.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/ir.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/control_flow_contract.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/task_graph.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability_task_contract.py",
)

if os.environ.get("P9_A2_P3_EXTERNAL_BASELINE") != "1":
    sys.path.insert(0, str(BASELINE))

from hsr.simulator_v8_clean_core.rules.evaluator import RuleEvaluator
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.rules.task_graph import (
    TaskGraphCatalogIR,
    TaskGraphDefinitionReferenceIR,
    TaskGraphIR,
    task_graph_reference_id,
)
from hsr.simulator_v8_clean_core.systems.action_contract import (
    _formal_action_task_graph_projection,
)
from hsr.simulator_v8_clean_core.systems.task_graph import TaskGraphExecutor
from hsr.simulator_v8_clean_core.tbgd import (
    task_graph_materializer as task_graph_materializer,
)
from hsr.simulator_v8_clean_core.tbgd.coverage import ability_task_execution_mode
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _process_only_ability_task_source_blocked_reason,
    _value_at_rooted_json_path,
)
from hsr.simulator_v8_clean_core.tools.validate_p9_a2_p1_formal_process_only_source_identity import (
    _accepted_context,
    _state_for_admission,
    build_context as _build_context,
    definitions as _definitions,
)

HIT_RANDOM = "task_graph_control_requires_domains:hit_random_sequence"
AUDIT_EFFECT_BLOCKER = "task_graph_definition_not_admitted:effect:audit_only"
PRESERVED = {
    "effect_coverage_status:unsupported:FireProjectile",
    "task_graph_definition_not_admitted:effect:unsupported",
    "task_graph_definition_not_admitted:effect:audit_only",
    "task_graph_control_requires_domains:damage_heal_shield",
}


def fail(message: str) -> None:
    raise AssertionError(message)


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=cwd,
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()


def governance() -> dict[str, Any]:
    if git("merge-base", BASE_SHA, "HEAD") != BASE_SHA:
        fail("fixed_base_not_ancestor")
    changed = tuple(
        item
        for item in git("diff", "--name-only", BASE_SHA, "HEAD").splitlines()
        if item
    )
    extra = sorted(set(changed) - ALLOWED)
    if extra:
        fail("scope_leak:" + ",".join(extra))
    production = tuple(
        item
        for item in changed
        if "/simulator_v8_clean_core/" in item
        and "/tools/" not in item
        and "/tests/" not in item
        and "/docs/" not in item
    )
    if production != (MATERIALIZER,):
        fail("production_authority_changed:" + ",".join(production))
    for path in READ_ONLY:
        current = (ROOT / path).read_text(encoding="utf-8").rstrip("\n")
        baseline = git("show", f"{BASE_SHA}:{path}").rstrip("\n")
        if current != baseline:
            fail("read_only_authority_changed:" + path)
    current_materializer = (ROOT / MATERIALIZER).read_text(encoding="utf-8")
    diff = git("diff", "--unified=3", BASE_SHA, "HEAD", "--", MATERIALIZER)
    for token in (
        "_is_wait_anim_state_process_only_presentation_shape",
        "_wait_anim_state_process_only_effect",
        "task_graph_wait_anim_state_source_contract_missing",
        "task_graph_wait_anim_state_process_only_effect_contract_invalid",
        "retire_wait_anim_state_barrier",
        AUDIT_EFFECT_BLOCKER,
    ):
        if token not in diff:
            fail("production_patch_shape_missing:" + token)
    if 'presentation_only_wait and kind == "effect"' in current_materializer:
        fail("wait_anim_state_effect_reference_still_suppressed")
    return {
        "fixed_base": BASE_SHA,
        "changed_paths": list(changed),
        "production_paths": list(production),
        "read_only_authorities_unchanged": True,
        "wait_anim_effect_reference_suppression_removed": True,
    }


def _family_for_task(task: Any) -> str:
    family = task.source.evidence.get("source_opcode")
    return family if isinstance(family, str) and family else str(task.opcode)


def _process_contract_ok(effect: Any, task: Any) -> bool:
    if effect is None:
        return False
    contract = effect.payload.get("process_only_contract")
    source_fields = (
        contract.get("source_fields") if isinstance(contract, Mapping) else None
    )
    source_field_types = (
        contract.get("source_field_types") if isinstance(contract, Mapping) else None
    )
    return bool(
        effect.opcode == task.opcode
        and effect.coverage_status == "audit_only"
        and effect.source == task.source
        and isinstance(contract, Mapping)
        and contract.get("schema_version") == "ability_process_only_source_shape_v1"
        and contract.get("opcode") == task.opcode
        and contract.get("source_shape_status") == "admitted"
        and not contract.get("blocked_reason")
        and isinstance(source_fields, (list, tuple))
        and "$type" in source_fields
        and len(source_fields) == len(set(source_fields))
        and isinstance(source_field_types, Mapping)
        and set(source_field_types) == set(source_fields)
        and all(
            isinstance(field_name, str)
            and field_name
            and isinstance(field_type, str)
            and field_type
            for field_name, field_type in source_field_types.items()
        )
    )


def _enriched_provenance(
    rules: RuleBook,
    projection: Any,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in projection.blocker_provenance:
        row = dict(raw)
        task_id = str(row.get("task_id") or "")
        if task_id:
            task = rules.ability_task(task_id)
            row["family"] = _family_for_task(task) if task is not None else "<missing>"
        else:
            row["family"] = ""
        result.append(row)
    return result


def _hit_random_rows(
    provenance: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        row
        for row in provenance
        if row.get("reason") == HIT_RANDOM
        and row.get("source") == "node_materialization"
    ]


def _formal_wait_nodes(
    rules: RuleBook,
    projection: Any,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for task_id in projection.reachable_task_ids:
        task = rules.ability_task(task_id)
        if task is None or _family_for_task(task) != "WaitAnimState":
            continue
        phase_tasks = tuple(
            candidate
            for candidate in rules.ability_tasks_for_phase(task.phase_id)
            if candidate.callback_kind == task.callback_kind
        )
        query = rules.query_formal_task_graph(
            "ability_phase_callback",
            task.phase_id,
            task.callback_kind,
            (candidate.task_id for candidate in phase_tasks),
        )
        graph = query.value
        if query.status != "resolved" or type(graph) is not TaskGraphIR:
            fail("wait_anim_graph_missing")
        nodes = tuple(
            node
            for node in graph.nodes
            if node.formal_task_id == task.task_id
        )
        if len(nodes) != 1:
            fail("wait_anim_node_missing_or_ambiguous")
        node = nodes[0]
        if node.graph_node_id in seen:
            fail("wait_anim_node_duplicate")
        seen.add(node.graph_node_id)
        effect = rules.effect(task.effect_id) if task.effect_id else None
        references = [
            {
                "reference_kind": item.reference_kind,
                "definition_id": item.definition_id,
                "resolution_status": item.resolution_status,
                "owner_domain": item.owner_domain,
                "blocked_reason": item.blocked_reason,
                "source_matches_node": item.source == node.source,
            }
            for item in node.references
        ]
        rows.append(
            {
                "task_id": task.task_id,
                "phase_id": task.phase_id,
                "callback_kind": task.callback_kind,
                "graph_id": graph.graph_id,
                "graph_node_id": node.graph_node_id,
                "node_kind": node.node_kind,
                "materialization_status": node.materialization_status,
                "owner_domains": list(node.owner_domains),
                "status_reason": node.status_reason,
                "references": references,
                "execution_mode": task.execution_mode,
                "task_coverage_status": task.coverage_status,
                "task_effect_id": task.effect_id,
                "effect_present": effect is not None,
                "effect_opcode": getattr(effect, "opcode", ""),
                "effect_coverage_status": getattr(effect, "coverage_status", ""),
                "effect_source_matches_task": (
                    effect is not None and effect.source == task.source
                ),
                "process_only_contract_admitted": _process_contract_ok(effect, task),
                "source_path": task.source.source_path,
                "json_path": task.source.evidence.get("json_path"),
                "source_contract_node_id": node.source_contract_node_id,
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            str(item["source_path"]),
            str(item["json_path"]),
        ),
    )


def _source_denominator(source_catalog: Any, snapshot: Any) -> dict[str, Any]:
    helper = getattr(
        task_graph_materializer,
        "_is_wait_anim_state_process_only_presentation_shape",
        None,
    )
    formal_task_type = getattr(task_graph_materializer, "_FormalTask", None)
    rows: list[dict[str, Any]] = []
    for control in source_catalog.nodes:
        if control.family != "WaitAnimState":
            continue
        source_path = control.source.source_path
        json_path = str(control.source.evidence.get("json_path") or "")
        document = snapshot.documents.get(source_path)
        raw: object = None
        source_reason = ""
        if document is None:
            source_reason = "wait_anim_state_source_document_missing"
        else:
            try:
                raw = _value_at_rooted_json_path(document, json_path)
            except (KeyError, IndexError, TypeError, ValueError):
                source_reason = "wait_anim_state_source_path_missing"
        if not source_reason and not isinstance(raw, Mapping):
            source_reason = "wait_anim_state_source_not_object"
        if not source_reason:
            source_reason = _process_only_ability_task_source_blocked_reason(
                dict(raw),
                "WaitAnimState",
            )
        admitted = False
        if (
            not source_reason
            and helper is not None
            and formal_task_type is not None
        ):
            task = formal_task_type(
                task_id=f"denominator:{control.node_id}",
                graph_task_path="denominator",
                opcode="WaitAnimState",
                family="WaitAnimState",
                condition_id="",
                target_expression_id="",
                effect_id=f"denominator-effect:{control.node_id}",
                ability_definition_id="",
                ability_definition_kind="",
                execution_mode=ability_task_execution_mode("WaitAnimState"),
                coverage_status="audit_only",
                source=control.source,
            )
            admitted = bool(helper(control, task))
        if not admitted and not source_reason and helper is not None:
            source_reason = "wait_anim_state_control_shape_not_retirable"
        rows.append(
            {
                "node_id": control.node_id,
                "source_path": source_path,
                "json_path": json_path,
                "control_role": control.control_role,
                "coverage_status": control.coverage_status,
                "peer_fields": list(control.peer_field_names),
                "responsibilities": [
                    {
                        "field": item.field_name,
                        "responsibility": item.responsibility,
                        "owner_stage": item.owner_stage,
                    }
                    for item in control.field_responsibilities
                ],
                "branch_count": len(control.branches),
                "termination_kind": control.termination.termination_kind,
                "downstream_stages": list(control.downstream_stages),
                "process_only_source_reason": source_reason,
                "admitted_by_current_gate": admitted,
            }
        )
    if not rows:
        fail("wait_anim_state_source_denominator_empty")
    return {
        "total": len(rows),
        "admitted": sum(
            bool(row["admitted_by_current_gate"])
            for row in rows
        ),
        "blocked": sum(
            not bool(row["admitted_by_current_gate"])
            for row in rows
        ),
        "rows": rows,
    }


def _s8c_sibling_signature(source_catalog: Any) -> list[list[Any]]:
    return sorted(
        [
            node.node_id,
            node.family,
            node.control_role,
            list(node.downstream_stages),
            node.coverage_status,
            node.blocked_reason,
        ]
        for node in source_catalog.nodes
        if node.family != "WaitAnimState"
        and "p9_s8c" in node.downstream_stages
    )


def representative(
    root: Path,
    *,
    target: Mapping[str, Any] | None,
    require_baseline_shape: bool,
    started: float,
) -> dict[str, Any]:
    lowerer, source_graph, snapshot, scope = _build_context(root)
    source_catalog = lowerer.build_character_control_flow_contract_catalog(
        snapshot=snapshot,
        scope_catalog=scope,
    )
    definitions = _definitions(root)
    if target is not None:
        definitions = tuple(
            definition
            for definition in definitions
            if definition.definition_id == target["definition_id"]
            and definition.action_id == target["action_id"]
            and definition.level == target["action_level"]
        )
        if len(definitions) != 1:
            fail("representative_definition_missing")
    diagnostics: list[str] = []
    scanned = 0
    for definition in definitions:
        if time.perf_counter() - started > 150:
            break
        scanned += 1
        try:
            canonical = lowerer.build_character_action_ability_slice(
                definition,
                snapshot=snapshot,
                scope_catalog=scope,
                source_graph_catalog=source_graph,
            )
            catalog = (
                task_graph_materializer.materialize_ability_task_graph_catalog(
                    source_catalog,
                    canonical,
                    source_snapshot=snapshot,
                )
            )
            canonical_with_graph = replace(
                canonical,
                task_graph_catalog=catalog,
            )
            rules = RuleBook(canonical_with_graph)
            tasks = rules.ability_tasks_for_action(
                definition.action_id,
                definition.level,
            )
            projection = _formal_action_task_graph_projection(
                rules,
                definition.action_id,
                definition.level,
                tasks,
            )
            accepted = _accepted_context(
                rules,
                definition,
                tuple(
                    str(value)
                    for value in projection.blocked_reasons
                ),
            )
            if accepted is None or accepted[4] != "external_turn":
                continue
            state, _, _, admission, mode, decision = accepted
            window = str(
                state.global_flags.get("current_window") or "idle"
            )
            if state.snapshot().to_json() != _state_for_admission(
                admission,
                window,
            ).snapshot().to_json():
                fail("action_contract_mutated_state")
            provenance = _enriched_provenance(rules, projection)
            hit_random = _hit_random_rows(provenance)
            counts = Counter(
                str(row.get("family") or "")
                for row in hit_random
            )
            if (
                require_baseline_shape
                and counts
                != Counter(
                    {"WaitAnimState": 2, "FireProjectile": 1}
                )
            ):
                continue
            return {
                "definition_id": definition.definition_id,
                "action_id": definition.action_id,
                "action_level": definition.level,
                "admission_id": admission.admission_id,
                "submission_mode": mode,
                "action_contract_ok": decision.ok,
                "blocked_reasons": list(projection.blocked_reasons),
                "blocker_provenance": provenance,
                "hit_random_provenance": hit_random,
                "hit_random_family_counts": dict(sorted(counts.items())),
                "wait_anim_nodes": _formal_wait_nodes(
                    rules,
                    projection,
                ),
                "root_graph_ids": list(projection.root_graph_ids),
                "reachable_task_ids": list(
                    projection.reachable_task_ids
                ),
                "excluded_bound_task_ids": list(
                    projection.excluded_bound_task_ids
                ),
                "source_fingerprint": snapshot.source_fingerprint,
                "source_catalog_id": source_catalog.catalog_id,
                "source_denominator": _source_denominator(
                    source_catalog,
                    snapshot,
                ),
                "s8c_sibling_signature": _s8c_sibling_signature(
                    source_catalog
                ),
                "scanned_action_definitions": scanned,
                "state_unchanged": True,
            }
        except (AssertionError, TypeError, ValueError, RuntimeError) as exc:
            diagnostics.append(
                f"{definition.action_id}@{definition.level}:"
                f"{type(exc).__name__}:{exc}"
            )
            if target is not None:
                raise
    fail(
        "representative_not_found:"
        + json.dumps(
            {
                "scanned": scanned,
                "diagnostics": diagnostics[-10:],
            },
            ensure_ascii=False,
        )
    )


def probe(
    root: Path,
    *,
    target: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if git("rev-parse", "HEAD", cwd=root) != TBGD_PIN:
        fail("tbgd_pin_mismatch")
    started = time.perf_counter()
    with patch.object(
        TaskGraphExecutor,
        "execute",
        side_effect=AssertionError(
            "admission attempted runtime graph execution"
        ),
    ), patch.object(
        RuleEvaluator,
        "evaluate_condition_result",
        side_effect=AssertionError(
            "admission attempted condition evaluation"
        ),
    ), patch.object(
        random,
        "random",
        side_effect=AssertionError("admission attempted RNG"),
    ):
        row = representative(
            root,
            target=target,
            require_baseline_shape=target is None,
            started=started,
        )
    return {
        "representative": row,
        "resource": {
            "wall_seconds": round(
                time.perf_counter() - started,
                6,
            ),
            "peak_rss_kib": resource.getrusage(
                resource.RUSAGE_SELF
            ).ru_maxrss,
        },
    }


def baseline_probe(root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix="p9-a2-p3-wait-base-"
    ) as temp:
        worktree = Path(temp) / "base"
        git(
            "worktree",
            "add",
            "--detach",
            "--quiet",
            str(worktree),
            BASE_SHA,
        )
        try:
            env = os.environ.copy()
            env["P9_A2_P3_EXTERNAL_BASELINE"] = "1"
            env["P9_A2_P1_EXTERNAL_BASELINE"] = "1"
            env["PYTHONPATH"] = str(
                worktree / "hsr_v075_baseline_clean"
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--probe-json",
                    "--tbgd-root",
                    str(root),
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=180,
                check=False,
            )
            if completed.returncode:
                fail(
                    "baseline_probe_failed:"
                    + json.dumps(
                        {
                            "rc": completed.returncode,
                            "stdout": completed.stdout[-3000:],
                            "stderr": completed.stderr[-3000:],
                        },
                        ensure_ascii=False,
                    )
                )
            return json.loads(completed.stdout)
        finally:
            git(
                "worktree",
                "remove",
                "--force",
                str(worktree),
            )
            git("worktree", "prune")


def _catalog_with_node_references(
    catalog: TaskGraphCatalogIR,
    *,
    graph_id: str,
    graph_node_id: str,
    references: tuple[TaskGraphDefinitionReferenceIR, ...],
) -> TaskGraphCatalogIR:
    graphs = []
    for graph in catalog.graphs:
        if graph.graph_id != graph_id:
            graphs.append(graph)
            continue
        nodes = tuple(
            replace(node, references=references)
            if node.graph_node_id == graph_node_id
            else node
            for node in graph.nodes
        )
        has_obligation = any(
            node.materialization_status == "deferred"
            for node in nodes
        ) or any(
            reference.resolution_status != "resolved"
            for node in nodes
            for reference in node.references
        )
        graphs.append(
            replace(
                graph,
                nodes=nodes,
                coverage_status=(
                    "lowered_with_obligation"
                    if has_obligation
                    else "lowered"
                ),
            )
        )
    return replace(catalog, graphs=tuple(graphs))


def canonical_reference_negatives(
    root: Path,
    target: Mapping[str, Any],
) -> dict[str, bool]:
    lowerer, source_graph, snapshot, scope = _build_context(root)
    source_catalog = lowerer.build_character_control_flow_contract_catalog(
        snapshot=snapshot,
        scope_catalog=scope,
    )
    definitions = tuple(
        definition
        for definition in _definitions(root)
        if definition.definition_id == target["definition_id"]
        and definition.action_id == target["action_id"]
        and definition.level == target["action_level"]
    )
    if len(definitions) != 1:
        fail("negative_definition_missing")
    canonical = lowerer.build_character_action_ability_slice(
        definitions[0],
        snapshot=snapshot,
        scope_catalog=scope,
        source_graph_catalog=source_graph,
    )
    catalog = task_graph_materializer.materialize_ability_task_graph_catalog(
        source_catalog,
        canonical,
        source_snapshot=snapshot,
    )
    valid = replace(canonical, task_graph_catalog=catalog)
    RuleBook(valid)
    task_by_id = {task.task_id: task for task in canonical.ability_tasks}
    candidates = [
        (graph, node, task_by_id.get(node.formal_task_id))
        for graph in catalog.graphs
        for node in graph.nodes
        if node.source_family == "WaitAnimState"
    ]
    candidates = [
        (graph, node, task)
        for graph, node, task in candidates
        if task is not None
        and task.execution_mode == "process_only"
        and task.coverage_status == "audit_only"
        and len(node.references) == 1
        and node.references[0].reference_kind == "effect"
        and node.references[0].definition_id == task.effect_id
    ]
    if not candidates:
        fail("canonical_negative_wait_anim_candidate_missing")
    graph, node, task = candidates[0]
    original = node.references[0]
    wrong_definition_id = f"{task.effect_id}:wrong"
    wrong = TaskGraphDefinitionReferenceIR(
        reference_id=task_graph_reference_id(
            node.graph_node_id,
            "effect",
            wrong_definition_id,
        ),
        graph_node_id=node.graph_node_id,
        reference_kind="effect",
        definition_id=wrong_definition_id,
        source_contract_record_id="",
        resolution_status="deferred",
        owner_domain=original.owner_domain,
        source=node.source,
        blocked_reason=AUDIT_EFFECT_BLOCKER,
    )
    cases = {
        "zero": (),
        "multiple": (original, wrong),
        "wrong": (wrong,),
    }
    results: dict[str, bool] = {}
    for label, references in cases.items():
        mutated_catalog = _catalog_with_node_references(
            catalog,
            graph_id=graph.graph_id,
            graph_node_id=node.graph_node_id,
            references=references,
        )
        try:
            replace(canonical, task_graph_catalog=mutated_catalog)
        except ValueError as exc:
            if "task graph formal definition references are inconsistent" not in str(exc):
                fail(
                    f"canonical_{label}_wrong_error:{exc}"
                )
            results[label] = True
        else:
            fail(f"canonical_{label}_effect_reference_not_rejected")
    return results


def _current_wait_node_ok(row: Mapping[str, Any]) -> bool:
    references = row.get("references")
    if not isinstance(references, list) or len(references) != 1:
        return False
    reference = references[0]
    return bool(
        row.get("materialization_status") == "materialized"
        and row.get("node_kind") == "leaf"
        and row.get("owner_domains") == ["task_graph_execution"]
        and row.get("execution_mode") == "process_only"
        and row.get("task_coverage_status") == "audit_only"
        and row.get("task_effect_id")
        and row.get("effect_present")
        and row.get("effect_opcode") == "WaitAnimState"
        and row.get("effect_coverage_status") == "audit_only"
        and row.get("effect_source_matches_task")
        and row.get("process_only_contract_admitted")
        and row.get("source_contract_node_id")
        and reference.get("reference_kind") == "effect"
        and reference.get("definition_id") == row.get("task_effect_id")
        and reference.get("resolution_status") == "deferred"
        and reference.get("blocked_reason") == AUDIT_EFFECT_BLOCKER
        and reference.get("source_matches_node")
    )


def run_direct(root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    gov = governance()
    if git("rev-parse", "HEAD", cwd=root) != TBGD_PIN:
        fail("tbgd_pin_mismatch")
    baseline = baseline_probe(root)
    base = baseline["representative"]
    target = {
        key: base[key]
        for key in ("definition_id", "action_id", "action_level")
    }
    current = probe(root, target=target)["representative"]

    base_hit = base["hit_random_family_counts"]
    current_hit = current["hit_random_family_counts"]
    if base_hit != {"FireProjectile": 1, "WaitAnimState": 2}:
        fail(
            "baseline_hit_random_provenance_changed:"
            + json.dumps(base_hit)
        )
    if current_hit != {"FireProjectile": 1}:
        fail(
            "current_hit_random_provenance_not_3_to_1:"
            + json.dumps(current_hit)
        )
    if HIT_RANDOM not in current["blocked_reasons"]:
        fail("top_level_hit_random_blocker_was_overclosed")
    if not PRESERVED.issubset(set(current["blocked_reasons"])):
        fail("required_future_blocker_missing")
    if set(current["blocked_reasons"]) != set(base["blocked_reasons"]):
        fail("top_level_blocker_set_changed")
    if current["action_contract_ok"] or not current["state_unchanged"]:
        fail("outer_action_no_longer_fail_closed")
    if current["source_fingerprint"] != base["source_fingerprint"]:
        fail("source_fingerprint_changed")
    if (
        current["s8c_sibling_signature"]
        != base["s8c_sibling_signature"]
    ):
        fail("s8c_sibling_source_authority_changed")

    base_wait = {
        (row["task_id"], row["graph_node_id"]): row
        for row in base["wait_anim_nodes"]
    }
    current_wait = {
        (row["task_id"], row["graph_node_id"]): row
        for row in current["wait_anim_nodes"]
    }
    if set(base_wait) != set(current_wait) or len(current_wait) != 2:
        fail("representative_wait_anim_identity_changed")
    for key, row in current_wait.items():
        prior = base_wait[key]
        if prior["materialization_status"] != "deferred":
            fail("baseline_wait_anim_not_deferred")
        if not _current_wait_node_ok(row):
            fail(
                "current_wait_anim_shape_not_retired:"
                + json.dumps(row, sort_keys=True)
            )

    baseline_provenance = base["blocker_provenance"]
    removed_wait = [
        row
        for row in baseline_provenance
        if row.get("reason") == HIT_RANDOM
        and row.get("source") == "node_materialization"
        and row.get("family") == "WaitAnimState"
    ]
    expected_current = [
        row
        for row in baseline_provenance
        if row not in removed_wait
    ]
    if (
        len(removed_wait) != 2
        or current["blocker_provenance"] != expected_current
    ):
        fail("non_wait_anim_provenance_changed")

    denominator = current["source_denominator"]
    if not denominator["total"] or not denominator["admitted"]:
        fail("current_wait_anim_denominator_not_proven")
    if any(
        row["admitted_by_current_gate"]
        and row["process_only_source_reason"]
        for row in denominator["rows"]
    ):
        fail("denominator_admitted_blocked_source")

    canonical_negatives = canonical_reference_negatives(root, target)
    if canonical_negatives != {
        "zero": True,
        "multiple": True,
        "wrong": True,
    }:
        fail("canonical_reference_negatives_incomplete")

    elapsed = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    predicates = {
        "fixed_base": gov["fixed_base"] == BASE_SHA,
        "baseline_provenance_2_wait_plus_1_projectile": True,
        "current_provenance_0_wait_plus_1_projectile": True,
        "wait_anim_nodes_materialized_process_only_leaf": True,
        "wait_anim_nodes_keep_exactly_one_audit_effect_reference": True,
        "canonical_zero_multiple_wrong_effect_refs_fail_closed": all(
            canonical_negatives.values()
        ),
        "fire_projectile_and_s11_blockers_preserved": True,
        "top_level_hit_random_still_fail_closed": True,
        "s8c_sibling_source_authority_unchanged": True,
        "source_denominator_nonempty": bool(denominator["total"]),
        "source_gate_admitted_nonempty": bool(denominator["admitted"]),
        "action_admission_state_unchanged": True,
        "runtime_graph_condition_rng_zero": True,
        "read_only_authorities_unchanged": gov[
            "read_only_authorities_unchanged"
        ],
    }
    return {
        "ok": (
            elapsed < 480
            and peak < 3 * 1024 * 1024
            and all(predicates.values())
        ),
        "mode": "direct",
        "predicates": predicates,
        "governance": gov,
        "baseline": base,
        "current": current,
        "canonical_reference_negatives": canonical_negatives,
        "provenance_delta": {
            "removed_wait_anim_state": removed_wait,
            "remaining_hit_random": current["hit_random_provenance"],
        },
        "denominator": denominator,
        "baseline_probe_resource": baseline.get("resource"),
        "resource": {
            "wall_seconds": round(elapsed, 6),
            "peak_rss_kib": peak,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-json", action="store_true")
    parser.add_argument("--tbgd-root", type=Path, default=TBGD)
    args = parser.parse_args()
    root = args.tbgd_root.resolve()
    if args.probe_json:
        print(
            json.dumps(
                probe(root),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    result = run_direct(root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
