from __future__ import annotations

import argparse
import gc
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[4]
BASELINE = ROOT / "hsr_v075_baseline_clean"
TBGD = ROOT / "turnbasedgamedata-main"
BASE_SHA = "5f9f909e276811bb36fc3bb6701633dc25e4ff27"
TBGD_PIN = "14c1d18f91a8101d610e6c523447a7517de3fae1"
ACTION_CONTRACT = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py"
TEST = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_p9_a2_p6_damage_audit_reference_admission.py"
VALIDATOR = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p6_damage_audit_reference_admission.py"
REPORT = "hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2-P6_DAMAGE_AUDIT_REFERENCE_ADMISSION_execution_report.md"
CARD = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-A2-P6_DAMAGE_AUDIT_REFERENCE_ADMISSION.md"
WORKFLOW = ".github/workflows/p9-a2-p6-pr-validation.yml"
ALLOWED = {ACTION_CONTRACT, TEST, VALIDATOR, REPORT, CARD, WORKFLOW}
AUDIT_BLOCKER = "task_graph_definition_not_admitted:effect:audit_only"

if os.environ.get("P9_A2_P6_EXTERNAL_BASELINE") != "1":
    sys.path.insert(0, str(BASELINE))

from hsr.simulator_v8_clean_core.ir_types import IRSource
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.rules.task_graph import TaskGraphIR
from hsr.simulator_v8_clean_core.systems.ability_task_contract import (
    ability_task_runtime_blocked_reason,
)
from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import (
    materialize_ability_task_graph_catalog,
)
from hsr.simulator_v8_clean_core.tools import (
    validate_p9_a2_p5_process_only_settlement_barrier_retirement as p5,
)


def fail(message: str) -> None:
    raise AssertionError(message)


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=cwd, text=True, stderr=subprocess.STDOUT
    ).strip()


def governance() -> dict[str, Any]:
    if git("merge-base", BASE_SHA, "HEAD") != BASE_SHA:
        fail("fixed_base_not_ancestor")
    changed = tuple(
        filter(None, git("diff", "--name-only", BASE_SHA, "HEAD").splitlines())
    )
    extra = sorted(set(changed) - ALLOWED)
    if extra:
        fail("scope_leak:" + ",".join(extra))
    production = tuple(path for path in changed if "/systems/" in path)
    if production != (ACTION_CONTRACT,):
        fail("production_authority_changed:" + ",".join(production))
    return {"fixed_base": BASE_SHA, "changed_paths": list(changed)}


def _source_relation(task: Any, effect: Any) -> dict[str, Any]:
    task_evidence = dict(task.source.evidence)
    reconstructed = IRSource(
        task.source.source_path,
        task.source.raw_type,
        task.source.raw_id,
        {**task_evidence, "parent_task_id": ""},
    )
    effect_evidence = dict(effect.source.evidence)
    added = {
        key: value for key, value in effect_evidence.items()
        if key not in task_evidence
    }
    removed = sorted(set(task_evidence) - set(effect_evidence))
    changed = {
        key: {"task": task_evidence[key], "effect": effect_evidence[key]}
        for key in task_evidence.keys() & effect_evidence.keys()
        if task_evidence[key] != effect_evidence[key]
    }
    return {
        "canonical_has_parent_task_id": "parent_task_id" in task_evidence,
        "canonical_has_child_task_count": "child_task_count" in task_evidence,
        "added_evidence": added,
        "removed_evidence_keys": removed,
        "changed_evidence": changed,
        "exact_precanonical_reconstruction": effect.source == reconstructed,
        "task_source": task.source.to_json(),
        "effect_source": effect.source.to_json(),
    }


def _task_evidence(rules: RuleBook, projection: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task_id in projection.reachable_task_ids:
        task = rules.ability_task(task_id)
        if task is None or p5._family(task) != "DamageByAttackProperty":
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
            fail("damage_formal_graph_missing")
        nodes = tuple(
            node for node in graph.nodes if node.formal_task_id == task.task_id
        )
        if len(nodes) != 1:
            fail("damage_formal_node_missing_or_ambiguous")
        node = nodes[0]
        unresolved = tuple(
            reference
            for reference in node.references
            if reference.resolution_status != "resolved"
        )
        effect = rules.effect(task.effect_id)
        if effect is None:
            fail("damage_audit_effect_missing")
        damage_emissions = rules.damage_emissions_for_task(task.task_id)
        toughness_emissions = rules.toughness_emissions_for_task(task.task_id)
        damage_profiles = tuple(
            rules.hit_profile(emission.hit_profile_id)
            for emission in damage_emissions
        )
        toughness_profiles = tuple(
            rules.hit_profile(emission.hit_profile_id)
            for emission in toughness_emissions
        )
        runtime_reason = ability_task_runtime_blocked_reason(
            rules, task, topology_authority="task_graph"
        )
        relation = _source_relation(task, effect)
        exact_shape = bool(
            task.execution_mode == "runtime_effect"
            and task.coverage_status == "executable"
            and not task.blocked_reason
            and not task.parent_task_id
            and node.node_kind == "leaf"
            and node.materialization_status == "materialized"
            and node.owner_domains == ("task_graph_execution",)
            and len(unresolved) == 1
            and unresolved[0].reference_kind == "effect"
            and unresolved[0].definition_id == task.effect_id
            and unresolved[0].resolution_status == "deferred"
            and unresolved[0].blocked_reason == AUDIT_BLOCKER
            and effect.opcode == task.opcode
            and effect.coverage_status == "audit_only"
            and relation["exact_precanonical_reconstruction"]
            and not relation["canonical_has_parent_task_id"]
            and not relation["canonical_has_child_task_count"]
            and relation["added_evidence"] == {"parent_task_id": ""}
            and not relation["removed_evidence_keys"]
            and not relation["changed_evidence"]
        )
        support_closed = bool(
            not runtime_reason
            and damage_emissions
            and all(
                emission.coverage_status == "executable"
                and not emission.blocked_reason
                and emission.action_id == task.action_id
                and emission.level == task.level
                and emission.phase_id == task.phase_id
                for emission in damage_emissions
            )
            and all(
                profile is not None
                and profile.coverage_status == "executable"
                and not profile.blocked_reason
                and profile.action_id == task.action_id
                and profile.level == task.level
                for profile in damage_profiles
            )
            and all(
                emission.coverage_status == "executable"
                and not emission.blocked_reason
                and emission.action_id == task.action_id
                and emission.level == task.level
                and emission.phase_id == task.phase_id
                for emission in toughness_emissions
            )
            and all(
                profile is not None
                and profile.coverage_status == "executable"
                and not profile.blocked_reason
                for profile in toughness_profiles
            )
            and {
                emission.hit_profile_id for emission in damage_emissions
            }
            == {
                emission.hit_profile_id for emission in toughness_emissions
            }
        )
        rows.append({
            "task_id": task.task_id,
            "task_coverage": task.coverage_status,
            "task_blocked_reason": task.blocked_reason,
            "runtime_support_reason": runtime_reason,
            "runtime_support_closed": support_closed,
            "exact_shape": exact_shape,
            "source_relation": relation,
            "task": task.to_json(),
            "effect": effect.to_json(),
            "node": node.to_json(),
            "unresolved_references": [item.to_json() for item in unresolved],
            "damage_emissions": [item.to_json() for item in damage_emissions],
            "damage_profiles": [
                item.to_json() if item is not None else None
                for item in damage_profiles
            ],
            "toughness_emissions": [
                item.to_json() for item in toughness_emissions
            ],
            "toughness_profiles": [
                item.to_json() if item is not None else None
                for item in toughness_profiles
            ],
        })
    return sorted(rows, key=lambda row: row["task_id"])


def representative(
    root: Path, target: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    p5_result = p5.probe(root, target)
    representative = p5_result["representative"]
    identity = {
        key: representative[key]
        for key in ("definition_id", "action_id", "action_level")
    }
    lowerer, source_graph, snapshot, scope = p5._build_context(root)
    definitions = tuple(
        item
        for item in p5._definitions(root)
        if item.definition_id == identity["definition_id"]
        and item.action_id == identity["action_id"]
        and item.level == identity["action_level"]
    )
    if len(definitions) != 1:
        fail("damage_candidate_definition_missing_or_ambiguous")
    definition = definitions[0]
    source_catalog = lowerer.build_character_control_flow_contract_catalog(
        snapshot=snapshot, scope_catalog=scope
    )
    canonical = lowerer.build_character_action_ability_slice(
        definition,
        snapshot=snapshot,
        scope_catalog=scope,
        source_graph_catalog=source_graph,
    )
    task_catalog = materialize_ability_task_graph_catalog(
        source_catalog, canonical, source_snapshot=snapshot
    )
    rules = RuleBook(replace(canonical, task_graph_catalog=task_catalog))
    tasks = rules.ability_tasks_for_action(definition.action_id, definition.level)
    projection = p5._formal_action_task_graph_projection(
        rules, definition.action_id, definition.level, tasks
    )
    evidence = _task_evidence(rules, projection)
    result = {
        **identity,
        "a2_source_bindings": representative["a2_source_bindings"],
        "action_contract_ok": representative["action_contract_ok"],
        "action_contract_blocked_reason": representative[
            "action_contract_blocked_reason"
        ],
        "blocked_reasons": list(projection.blocked_reasons),
        "provenance": p5._provenance(rules, projection),
        "target_task_ids": [row["task_id"] for row in evidence],
        "tasks": evidence,
    }
    del canonical, task_catalog, rules
    gc.collect()
    return {
        "representative": result,
        "channels": p5_result["channels"],
    }


def baseline_probe(root: Path, target: Mapping[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="p9-a2-p6-base-") as temp:
        worktree = Path(temp) / "base"
        git("worktree", "add", "--detach", "--quiet", str(worktree), BASE_SHA)
        try:
            env = os.environ | {
                "P9_A2_P6_EXTERNAL_BASELINE": "1",
                "PYTHONPATH": str(worktree / "hsr_v075_baseline_clean"),
            }
            run = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--probe-json",
                    "--tbgd-root",
                    str(root),
                    "--definition-id",
                    str(target["definition_id"]),
                    "--action-id",
                    str(target["action_id"]),
                    "--action-level",
                    str(target["action_level"]),
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=240,
            )
            if run.returncode:
                fail("baseline_probe_failed:" + run.stderr[-2000:])
            return json.loads(run.stdout)
        finally:
            git("worktree", "remove", "--force", str(worktree))
            git("worktree", "prune")


def _stable_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        json.dumps(row, sort_keys=True, separators=(",", ":")): row
        for row in rows
    }


def run_direct(root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    gov = governance()
    if git("rev-parse", "HEAD", cwd=root) != TBGD_PIN:
        fail("tbgd_pin_mismatch")
    current = representative(root)
    cur = current["representative"]
    target = {
        key: cur[key] for key in ("definition_id", "action_id", "action_level")
    }
    baseline = baseline_probe(root, target)
    base = baseline["representative"]
    if any(base[key] != cur[key] for key in target):
        fail("damage_candidate_identity_changed")
    if not cur["a2_source_bindings"]:
        fail("a2_raw_trigger_source_binding_missing")
    target_ids = set(cur["target_task_ids"])
    if not target_ids or target_ids != set(base["target_task_ids"]):
        fail("damage_target_denominator_changed")
    base_damage_rows = [
        row
        for row in base["provenance"]
        if row.get("family") == "DamageByAttackProperty"
        and row.get("reason") == AUDIT_BLOCKER
        and row.get("source") == "graph_reference"
    ]
    if {str(row.get("task_id") or "") for row in base_damage_rows} != target_ids:
        fail("baseline_damage_audit_provenance_incomplete")
    current_damage_rows = [
        row
        for row in cur["provenance"]
        if row.get("family") == "DamageByAttackProperty"
        and row.get("reason") == AUDIT_BLOCKER
    ]
    if current_damage_rows:
        fail("current_damage_audit_provenance_not_removed")
    if not all(
        row["exact_shape"] and row["runtime_support_closed"]
        for row in cur["tasks"]
    ):
        fail("current_damage_source_or_runtime_support_not_closed")
    base_tasks = {row["task_id"]: row for row in base["tasks"]}
    current_tasks = {row["task_id"]: row for row in cur["tasks"]}
    immutable_fields = (
        "task",
        "effect",
        "node",
        "unresolved_references",
        "damage_emissions",
        "damage_profiles",
        "toughness_emissions",
        "toughness_profiles",
    )
    if any(
        base_tasks[task_id][field] != current_tasks[task_id][field]
        for task_id in target_ids
        for field in immutable_fields
    ):
        fail("damage_ir_or_graph_object_changed")
    base_rows = _stable_rows(base["provenance"])
    current_rows = _stable_rows(cur["provenance"])
    removed = [base_rows[key] for key in sorted(base_rows.keys() - current_rows)]
    added = [current_rows[key] for key in sorted(current_rows.keys() - base_rows)]
    if _stable_rows(removed) != _stable_rows(base_damage_rows) or added:
        fail("unrelated_blocker_provenance_changed")
    if any(current["channels"].values()) or any(baseline["channels"].values()):
        fail("runtime_channel_touched")
    remaining = list(cur["blocked_reasons"])
    predecessor_chain_empty = not remaining and bool(cur["action_contract_ok"])
    elapsed = time.perf_counter() - started
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    predicates = {
        "candidate_binding_closed": True,
        "target_denominator_closed": True,
        "runtime_support_closed": True,
        "exact_precanonical_source_relation": True,
        "damage_ir_and_audit_reference_unchanged": True,
        "only_damage_audit_provenance_removed": True,
        "runtime_channels_zero": True,
        "within_wall_budget": elapsed < 300,
        "within_rss_budget": peak < 2 * 1024 * 1024,
    }
    return {
        "ok": all(predicates.values()),
        "mode": "direct",
        "predicates": predicates,
        "governance": gov,
        "candidate": target,
        "a2_source_bindings": cur["a2_source_bindings"],
        "target_task_ids": sorted(target_ids),
        "tasks": cur["tasks"],
        "provenance_delta": {
            "removed": removed,
            "added": added,
            "remaining": cur["provenance"],
        },
        "remaining_blocked_reasons": remaining,
        "predecessor_chain_empty": predecessor_chain_empty,
        "action_contract_ok": cur["action_contract_ok"],
        "formal_channels": current["channels"],
        "resource": {
            "wall_seconds": round(elapsed, 6),
            "peak_rss_kib": peak,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--direct", action="store_true")
    parser.add_argument("--probe-json", action="store_true")
    parser.add_argument("--tbgd-root", type=Path, default=TBGD)
    parser.add_argument("--definition-id")
    parser.add_argument("--action-id")
    parser.add_argument("--action-level", type=int)
    args = parser.parse_args()
    target = None
    if args.definition_id is not None:
        target = {
            "definition_id": args.definition_id,
            "action_id": args.action_id,
            "action_level": args.action_level,
        }
    if args.probe_json:
        print(json.dumps(representative(args.tbgd_root.resolve(), target), sort_keys=True))
        return 0
    if args.direct:
        result = run_direct(args.tbgd_root.resolve())
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1
    parser.error("one of --direct or --probe-json is required")


if __name__ == "__main__":
    raise SystemExit(main())
