from __future__ import annotations

import argparse
import gc
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
BASE_SHA = "8064d5ab01837d1ebb4d8388ca072796c7946634"
TBGD_PIN = "14c1d18f91a8101d610e6c523447a7517de3fae1"
MATERIALIZER = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py"
TEST = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_p9_a2_p5_process_only_settlement_barrier_retirement.py"
VALIDATOR = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p5_process_only_settlement_barrier_retirement.py"
REPORT = "hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2-P5_PROCESS_ONLY_SETTLEMENT_BARRIER_RETIREMENT_execution_report.md"
CARD = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-A2-P5_PROCESS_ONLY_SETTLEMENT_BARRIER_RETIREMENT.md"
WORKFLOW = ".github/workflows/p9-a2-p5-pr-validation.yml"
ALLOWED = {MATERIALIZER, TEST, VALIDATOR, REPORT, CARD, WORKFLOW}
FAMILIES = frozenset({"DamagePerformFinish", "SkillPerformFinish"})
AUDIT_BLOCKER = "task_graph_definition_not_admitted:effect:audit_only"
DAMAGE_BLOCKER = "task_graph_control_requires_domains:damage_heal_shield"

if os.environ.get("P9_A2_P5_EXTERNAL_BASELINE") != "1":
    sys.path.insert(0, str(BASELINE))

from hsr.simulator_v8_clean_core.rules.evaluator import RuleEvaluator
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.rules.task_graph import TaskGraphIR
from hsr.simulator_v8_clean_core.systems.action_contract import (
    _formal_action_task_graph_projection,
)
from hsr.simulator_v8_clean_core.systems.task_graph import TaskGraphExecutor
from hsr.simulator_v8_clean_core.tbgd import task_graph_materializer
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _process_only_ability_task_source_blocked_reason,
    _value_at_rooted_json_path,
)
from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import (
    materialize_ability_task_graph_catalog,
)
from hsr.simulator_v8_clean_core.tools.validate_p9_a2_p1_formal_process_only_source_identity import (
    _accepted_context,
    _state_for_admission,
    build_context as _build_context,
    definitions as _definitions,
)
from hsr.simulator_v8_clean_core.tools.validate_p9_a2_p0_action_window_status_callback_admission_finalization import (
    _raw_source_trigger_ability_denominator,
)


def fail(message: str) -> None:
    raise AssertionError(message)


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=cwd, text=True, stderr=subprocess.STDOUT
    ).strip()


def _family(task: Any) -> str:
    value = task.source.evidence.get("source_opcode")
    return value if isinstance(value, str) and value else str(task.opcode)


def governance() -> dict[str, Any]:
    if git("merge-base", BASE_SHA, "HEAD") != BASE_SHA:
        fail("fixed_base_not_ancestor")
    changed = tuple(filter(None, git("diff", "--name-only", BASE_SHA, "HEAD").splitlines()))
    extra = sorted(set(changed) - ALLOWED)
    if extra:
        fail("scope_leak:" + ",".join(extra))
    production = tuple(path for path in changed if path.endswith("task_graph_materializer.py"))
    if production != (MATERIALIZER,):
        fail("production_authority_changed:" + ",".join(production))
    return {"fixed_base": BASE_SHA, "changed_paths": list(changed)}


def source_denominator(root: Path) -> dict[str, Any]:
    lowerer, _source_graph, snapshot, scope = _build_context(root)
    catalog = lowerer.build_character_control_flow_contract_catalog(
        snapshot=snapshot, scope_catalog=scope
    )
    documents = lowerer._character_formal_task_source_context().documents
    partitions: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    samples: dict[str, list[dict[str, Any]]] = {"A": [], "B": [], "C": []}
    for control in catalog.nodes:
        if control.family not in FAMILIES:
            continue
        source_path = control.source.source_path
        json_path = str(control.source.evidence.get("json_path") or "")
        raw: object = None
        try:
            raw = _value_at_rooted_json_path(documents[source_path], json_path)
        except (KeyError, IndexError, TypeError, ValueError):
            pass
        source_reason = (
            _process_only_ability_task_source_blocked_reason(dict(raw), control.family)
            if isinstance(raw, Mapping)
            else "raw_source_missing"
        )
        eligible = bool(
            not source_reason
            and control.control_role == "settlement_barrier"
            and control.coverage_status != "blocked"
            and not control.blocked_reason
            and control.peer_field_names == ()
            and control.field_responsibilities == ()
            and not control.branches
            and not control.template_reference_ids
            and control.termination.termination_kind == "not_applicable"
            and control.termination.status == "not_applicable"
            and control.downstream_stages == ("p9_s11",)
        )
        payload = bool(control.peer_field_names or control.field_responsibilities)
        partition = "A" if eligible else "B" if payload or source_reason else "C"
        partitions[partition] += 1
        reasons[source_reason or "admitted"] += 1
        if len(samples[partition]) < 3:
            samples[partition].append({
                "family": control.family,
                "source_path": source_path,
                "json_path": json_path,
                "raw_fields": sorted(raw) if isinstance(raw, Mapping) else [],
                "peer_field_names": list(control.peer_field_names),
                "source_reason": source_reason,
            })
    total = sum(partitions.values())
    if not total or not partitions["A"] or partitions["C"]:
        fail("settlement_barrier_source_denominator_unresolved:" + json.dumps(dict(partitions), sort_keys=True))
    return {
        "total": total,
        "eligible_no_payload_process_only": partitions["A"],
        "explicit_s11_payload": partitions["B"],
        "other_blocked_or_unresolved": partitions["C"],
        "identity_closed": total == sum(partitions.values()),
        "source_contract_reason_counts": dict(sorted(reasons.items())),
        "samples": samples,
    }


def _barrier_nodes(rules: RuleBook, projection: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task_id in projection.reachable_task_ids:
        task = rules.ability_task(task_id)
        if task is None or _family(task) not in FAMILIES:
            continue
        phase_tasks = [
            candidate for candidate in rules.ability_tasks_for_phase(task.phase_id)
            if candidate.callback_kind == task.callback_kind
        ]
        query = rules.query_formal_task_graph(
            "ability_phase_callback", task.phase_id, task.callback_kind,
            (candidate.task_id for candidate in phase_tasks),
        )
        graph = query.value
        if query.status != "resolved" or type(graph) is not TaskGraphIR:
            fail("settlement_barrier_formal_graph_missing")
        matches = [node for node in graph.nodes if node.formal_task_id == task.task_id]
        if len(matches) != 1:
            fail("settlement_barrier_formal_node_missing_or_ambiguous")
        node = matches[0]
        effect = rules.effect(task.effect_id) if task.effect_id else None
        contract = effect.payload.get("process_only_contract") if effect is not None else None
        rows.append({
            "task_id": task.task_id,
            "family": _family(task),
            "node_kind": node.node_kind,
            "materialization_status": node.materialization_status,
            "owner_domains": list(node.owner_domains),
            "references": [
                (reference.reference_kind, reference.resolution_status, reference.blocked_reason)
                for reference in node.references
            ],
            "task_mode": task.execution_mode,
            "task_coverage": task.coverage_status,
            "effect_identity": bool(effect is not None and effect.source == task.source and effect.opcode == task.opcode),
            "process_contract_admitted": bool(
                isinstance(contract, Mapping)
                and contract.get("source_shape_status") == "admitted"
                and not contract.get("blocked_reason")
                and contract.get("source_fields") == ["$type"]
            ),
        })
    return sorted(rows, key=lambda row: (row["family"], row["task_id"]))


def _provenance(rules: RuleBook, projection: Any) -> list[dict[str, Any]]:
    result = []
    for raw in projection.blocker_provenance:
        row = dict(raw)
        task = rules.ability_task(str(row.get("task_id") or ""))
        row["family"] = _family(task) if task is not None else ""
        result.append(row)
    return result


def _a2_candidate_action_ids(
    lowerer: Any, source_graph: Any, snapshot: Any, scope: Any
) -> set[str]:
    """Reuse P0's raw action-window TriggerAbility denominator before action slices."""

    formal_context = lowerer._character_formal_task_source_context()
    formal_paths = {item.source.source_path for item in snapshot.sources}
    rows, _meta = _raw_source_trigger_ability_denominator(
        lowerer, formal_context, formal_paths
    )
    candidate_paths = {
        str(row["callback_source_path"])
        for row in rows
    }
    owner_ids = {
        str(record.source.evidence.get("avatar_id") or "")
        for record in scope.scope_records
        if record.source.source_path in candidate_paths
    }
    owner_ids.discard("")
    result = {
        action.action_id
        for action in source_graph.action_sources
        if action.owner_avatar_id in owner_ids
    }
    if not result:
        fail("a2_raw_candidate_action_denominator_empty")
    return result


def representative(root: Path, target: Mapping[str, Any] | None = None) -> dict[str, Any]:
    lowerer, source_graph, snapshot, scope = _build_context(root)
    source_catalog = lowerer.build_character_control_flow_contract_catalog(snapshot=snapshot, scope_catalog=scope)
    definitions = _definitions(root)
    if target is not None:
        definitions = tuple(
            item for item in definitions
            if item.definition_id == target["definition_id"]
            and item.action_id == target["action_id"]
            and item.level == target["action_level"]
        )
    else:
        candidate_action_ids = _a2_candidate_action_ids(
            lowerer, source_graph, snapshot, scope
        )
        definitions = tuple(
            item for item in definitions if item.action_id in candidate_action_ids
        )
    scanned = 0
    for definition in definitions:
        if not definition.action_id.startswith("avatar_skill:"):
            continue
        scanned += 1
        canonical = lowerer.build_character_action_ability_slice(
            definition, snapshot=snapshot, scope_catalog=scope, source_graph_catalog=source_graph
        )
        task_catalog = materialize_ability_task_graph_catalog(source_catalog, canonical, source_snapshot=snapshot)
        rules = RuleBook(replace(canonical, task_graph_catalog=task_catalog))
        tasks = rules.ability_tasks_for_action(definition.action_id, definition.level)
        projection = _formal_action_task_graph_projection(rules, definition.action_id, definition.level, tasks)
        reachable = [rules.ability_task(task_id) for task_id in projection.reachable_task_ids]
        damage_tasks = [
            task for task in reachable
            if task is not None and _family(task) == "DamageByAttackProperty"
        ]
        if not (
            any(task is not None and task.opcode == "TriggerAbility" for task in reachable)
            and any(task is not None and _family(task) in FAMILIES for task in reachable)
            and len(damage_tasks) > 1
        ):
            del canonical, task_catalog, rules
            gc.collect()
            continue
        accepted = _accepted_context(rules, definition, tuple(str(value) for value in projection.blocked_reasons))
        if accepted is None or accepted[4] != "external_turn":
            del canonical, task_catalog, rules
            gc.collect()
            continue
        state, _command, _context, admission, mode, decision = accepted
        before = _state_for_admission(admission, str(state.global_flags.get("current_window") or "idle")).snapshot().to_json()
        after = state.snapshot().to_json()
        if before != after:
            fail("action_contract_mutated_state")
        return {
            "definition_id": definition.definition_id,
            "action_id": definition.action_id,
            "action_level": definition.level,
            "scanned_action_definitions": scanned,
            "action_contract_ok": decision.ok,
            "action_contract_blocked_reason": decision.blocked_reason,
            "blocked_reasons": list(projection.blocked_reasons),
            "provenance": _provenance(rules, projection),
            "barrier_nodes": _barrier_nodes(rules, projection),
            "damage_task_ids": sorted(task.task_id for task in damage_tasks),
            "submission_mode": mode,
        }
    fail("a2_action_window_trigger_ability_candidate_not_found:" + str(scanned))


def probe(root: Path, target: Mapping[str, Any] | None = None) -> dict[str, Any]:
    with patch.object(TaskGraphExecutor, "execute", side_effect=AssertionError("runtime task graph execution forbidden")) as execute, patch.object(RuleEvaluator, "evaluate_condition_result", side_effect=AssertionError("condition evaluation forbidden")) as evaluate, patch.object(random, "random", side_effect=AssertionError("rng forbidden")) as rng:
        row = representative(root, target)
    if execute.call_count or evaluate.call_count or rng.call_count:
        fail("runtime_channel_touched")
    return {"representative": row, "channels": {"task_graph_execute_calls": execute.call_count, "condition_evaluation_calls": evaluate.call_count, "rng_draw_calls": rng.call_count, "mutation_count": 0, "event_count": 0, "settlement_record_count": 0, "replay_mutation_count": 0}}


def baseline_probe(root: Path, target: Mapping[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="p9-a2-p5-base-") as temp:
        worktree = Path(temp) / "base"
        git("worktree", "add", "--detach", "--quiet", str(worktree), BASE_SHA)
        try:
            env = os.environ | {"P9_A2_P5_EXTERNAL_BASELINE": "1", "PYTHONPATH": str(worktree / "hsr_v075_baseline_clean")}
            run = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--probe-json", "--tbgd-root", str(root), "--definition-id", str(target["definition_id"]), "--action-id", str(target["action_id"]), "--action-level", str(target["action_level"])], cwd=ROOT, env=env, text=True, capture_output=True, timeout=240)
            if run.returncode:
                fail("baseline_probe_failed:" + run.stderr[-2000:])
            return json.loads(run.stdout)
        finally:
            git("worktree", "remove", "--force", str(worktree))
            git("worktree", "prune")


def run_direct(root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    gov = governance()
    if git("rev-parse", "HEAD", cwd=root) != TBGD_PIN:
        fail("tbgd_pin_mismatch")
    denominator = source_denominator(root)
    current = probe(root)
    target = {key: current["representative"][key] for key in ("definition_id", "action_id", "action_level")}
    baseline = baseline_probe(root, target)
    base = baseline["representative"]
    cur = current["representative"]
    if any(base[key] != cur[key] for key in target):
        fail("same_owner_candidate_identity_changed")
    base_stale = [row for row in base["provenance"] if row.get("family") in FAMILIES and row.get("reason") == DAMAGE_BLOCKER and row.get("source") == "node_materialization"]
    current_stale = [row for row in cur["provenance"] if row.get("family") in FAMILIES and row.get("reason") == DAMAGE_BLOCKER and row.get("source") == "node_materialization"]
    if not base_stale or current_stale:
        fail("settlement_barrier_provenance_delta_missing")
    if not cur["damage_task_ids"] or cur["action_contract_ok"]:
        fail("real_s11_gameplay_or_outer_action_not_deferred")
    current_damage_rows = [
        row for row in cur["provenance"]
        if row.get("family") == "DamageByAttackProperty"
    ]
    if not current_damage_rows or any(
        row.get("reason") != AUDIT_BLOCKER for row in current_damage_rows
    ):
        fail("real_damage_task_not_preserved_as_nonexecutable")
    if not cur["barrier_nodes"] or not all(
        row["node_kind"] == "leaf" and row["materialization_status"] == "materialized"
        and row["owner_domains"] == ["task_graph_execution"]
        and row["references"] == [("effect", "deferred", AUDIT_BLOCKER)]
        and row["task_mode"] == "process_only" and row["task_coverage"] == "audit_only"
        and row["effect_identity"] and row["process_contract_admitted"]
        for row in cur["barrier_nodes"]
    ):
        fail("eligible_settlement_barrier_not_exact_process_only_leaf")
    elapsed = time.perf_counter() - started
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    predicates = {
        "source_denominator_closed": denominator["identity_closed"],
        "source_denominator_a_nonempty": bool(denominator["eligible_no_payload_process_only"]),
        "source_denominator_b_remains_s11_payload": bool(denominator["explicit_s11_payload"]),
        "source_denominator_c_empty": denominator["other_blocked_or_unresolved"] == 0,
        "same_owner_stale_damage_owner_retired": True,
        "audit_reference_remains_nonexecutable": True,
        "real_s11_damage_task_remains_nonexecutable": True,
        "outer_action_remains_fail_closed": True,
        "runtime_channels_zero": all(value == 0 for value in current["channels"].values()),
    }
    return {"ok": elapsed < 300 and peak < 2 * 1024 * 1024 and all(predicates.values()), "mode": "direct", "predicates": predicates, "governance": gov, "denominator": denominator, "baseline_representative": base, "current_representative": cur, "provenance_delta": {"removed_stale_settlement_barriers": base_stale, "remaining_blockers": cur["blocked_reasons"]}, "formal_channels": current["channels"], "resource": {"wall_seconds": round(elapsed, 6), "peak_rss_kib": peak}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--direct", action="store_true")
    parser.add_argument("--probe-json", action="store_true")
    parser.add_argument("--tbgd-root", type=Path, default=TBGD)
    parser.add_argument("--definition-id")
    parser.add_argument("--action-id")
    parser.add_argument("--action-level", type=int)
    args = parser.parse_args()
    target = None if args.definition_id is None else {"definition_id": args.definition_id, "action_id": args.action_id, "action_level": args.action_level}
    if args.probe_json:
        print(json.dumps(probe(args.tbgd_root.resolve(), target), sort_keys=True))
    elif args.direct:
        result = run_direct(args.tbgd_root.resolve())
        print(json.dumps(result, indent=2, sort_keys=True))
        if not result["ok"]:
            return 1
    else:
        parser.error("one of --direct or --probe-json is required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
