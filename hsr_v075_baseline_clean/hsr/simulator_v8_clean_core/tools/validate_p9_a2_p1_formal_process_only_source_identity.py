from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import random
import resource
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[4]
BASELINE_ROOT = REPO_ROOT / "hsr_v075_baseline_clean"
TBGD_ROOT = REPO_ROOT / "turnbasedgamedata-main"
BASE_SHA = "770a0649926932794585fcd30589c6776892bc3b"
TBGD_PIN = "14c1d18f91a8101d610e6c523447a7517de3fae1"
LOWERING_PATH = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py"
VALIDATOR_PATH = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p1_formal_process_only_source_identity.py"
REPORT_PATH = "hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2-P1_FORMAL_PROCESS_ONLY_SOURCE_IDENTITY_execution_report.md"
WORKFLOW_PATH = ".github/workflows/p9-a2-p1-pr-validation.yml"
CARD_PATH = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-A2-P1_FORMAL_PROCESS_ONLY_SOURCE_IDENTITY.md"
MISMATCH = "process_only_task_effect_source_mismatch"
TOPOLOGY_EVIDENCE = {"parent_task_id", "child_task_count"}

if os.environ.get("P9_A2_P1_EXTERNAL_BASELINE") != "1":
    sys.path.insert(0, str(BASELINE_ROOT))

from hsr.simulator_v8_clean_core.ir_types import IRSource
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.ability_task_contract import ability_task_runtime_blocked_reason
from hsr.simulator_v8_clean_core.systems.action_contract import _formal_action_task_graph_projection
from hsr.simulator_v8_clean_core.systems.task_graph import TaskGraphExecutor
from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering, build_character_action_definition_ir
from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import materialize_ability_task_graph_catalog
from hsr.simulator_v8_clean_core.tools.validate_p9_formal_action_graph_admission_authority import (
    _accepted_context,
    _run_fast as _run_a1_fast,
    _state_for_admission,
)

ALLOWED = {CARD_PATH, LOWERING_PATH, VALIDATOR_PATH, REPORT_PATH, WORKFLOW_PATH}
A1_PATHS = (
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability_task_contract.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/task_graph.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/ir_types.py",
)
EXPECTED_LOWERING_ADDED = (
    "        pre_canonical_parent_source = parent_source",
    "        if (",
    '            parent.execution_mode == "process_only"',
    "            and parent.effect_id",
    "            and parent_source != pre_canonical_parent_source",
    "        ):",
    "            matching_effects = [",
    "                (effect_index, effect)",
    "                for effect_index, effect in enumerate(lowered.effects)",
    "                if effect.effect_id == parent.effect_id",
    "            ]",
    "            if (",
    "                len(matching_effects) == 1",
    "                and matching_effects[0][1].source == pre_canonical_parent_source",
    "            ):",
    "                effect_index, effect = matching_effects[0]",
    "                lowered.effects[effect_index] = replace(",
    "                    effect,",
    "                    source=parent_source,",
    "                )",
    "    for effect_index, effect in enumerate(lowered.effects):",
    "        if effect.effect_id not in client_only_effect_ids:",
    "            continue",
    "        matching_tasks = [",
    "            task",
    "            for task in lowered.ability_tasks",
    "            if task.effect_id == effect.effect_id",
    '            and task.execution_mode == "process_only"',
    "        ]",
    "        if len(matching_tasks) != 1:",
    "            continue",
    "        task = matching_tasks[0]",
    "        pre_canonical_task_source = IRSource(",
    "            task.source.source_path,",
    "            task.source.raw_type,",
    "            task.source.raw_id,",
    "            {",
    "                **dict(task.source.evidence),",
    '                "parent_task_id": "",',
    "            },",
    "        )",
    "        if effect.source == pre_canonical_task_source:",
    "            lowered.effects[effect_index] = replace(",
    "                effect,",
    "                source=task.source,",
    "            )",
)

def fail(message: str) -> None:
    raise AssertionError(message)

def git(*args: str, cwd: Path = REPO_ROOT) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()

def digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()

def source_json(source: Any) -> dict[str, Any]:
    value = source.to_json()
    if not isinstance(value, dict):
        fail("source_to_json_not_object")
    return value

def normalized_source(source: Any) -> dict[str, Any]:
    value = json.loads(json.dumps(source_json(source)))
    evidence = value.get("evidence")
    if isinstance(evidence, dict):
        for key in TOPOLOGY_EVIDENCE:
            evidence.pop(key, None)
    return value

def fn_ast(text: str, name: str) -> str:
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.dump(node, include_attributes=False)
    fail(f"function_missing:{name}")

def assert_pin(root: Path) -> str:
    actual = git("rev-parse", "HEAD", cwd=root)
    if actual != TBGD_PIN:
        fail(f"tbgd_pin_mismatch:{actual}")
    return actual

def governance() -> dict[str, Any]:
    if git("merge-base", BASE_SHA, "HEAD") != BASE_SHA:
        fail("fixed_base_not_ancestor")
    changed = tuple(x for x in git("diff", "--name-only", BASE_SHA, "HEAD").splitlines() if x)
    extra = sorted(set(changed) - ALLOWED)
    if extra:
        fail("scope_leak:" + ",".join(extra))
    for path in A1_PATHS:
        current = (REPO_ROOT / path).read_text(encoding="utf-8").rstrip("\n")
        if current != git("show", f"{BASE_SHA}:{path}").rstrip("\n"):
            fail(f"a1_authority_changed:{path}")
    diff = git("diff", "--unified=3", BASE_SHA, "HEAD", "--", LOWERING_PATH)
    added = tuple(line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
    deleted = tuple(line[1:] for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))
    if deleted or added != EXPECTED_LOWERING_ADDED:
        fail("lowering_patch_not_exact:" + json.dumps({"added": added, "deleted": deleted}))
    cur = (REPO_ROOT / LOWERING_PATH).read_text(encoding="utf-8")
    base = git("show", f"{BASE_SHA}:{LOWERING_PATH}")
    if fn_ast(cur, "_lower_ability_task_tree") != fn_ast(base, "_lower_ability_task_tree"):
        fail("unexpected_lowering_authority_change:_lower_ability_task_tree")
    if fn_ast(cur, "_lower_formal_ability_task_tree") == fn_ast(base, "_lower_formal_ability_task_tree"):
        fail("formal_lowering_ast_unchanged")
    if fn_ast(cur, "_mark_client_only_trigger_ability_tasks") == fn_ast(base, "_mark_client_only_trigger_ability_tasks"):
        fail("client_only_process_only_source_sync_ast_unchanged")
    return {
        "fixed_base": BASE_SHA,
        "changed_paths": list(changed),
        "production_write_authority_is_lowering_only": True,
        "a1_authority_changed": False,
        "process_only_contract_weakened": False,
        "task_graph_materializer_changed": False,
        "runtime_changed": False,
    }

class FixtureRules:
    def __init__(self, effect: Any | None):
        self.effect_value = effect
    def effect(self, effect_id: str) -> Any | None:
        return self.effect_value if effect_id == "fixture:effect" else None

def fast_contract() -> dict[str, str]:
    canonical = IRSource("fixture.json", "AbilityTask", "fixture", {"json_path": "$.AbilityList[0].OnStart[0]"})
    stale = IRSource(canonical.source_path, canonical.raw_type, canonical.raw_id, {**dict(canonical.evidence), "parent_task_id": "", "child_task_count": 0})
    task = SimpleNamespace(execution_mode="process_only", coverage_status="audit_only", blocked_reason="", effect_id="fixture:effect", opcode="AuditTask", source=canonical)
    contract = {"schema_version": "ability_process_only_source_shape_v1", "opcode": "AuditTask", "source_fields": ["$type"], "source_field_types": {"$type": "str"}, "source_shape_status": "admitted", "blocked_reason": ""}
    def effect(source: Any) -> Any:
        return SimpleNamespace(opcode="AuditTask", coverage_status="audit_only", source=source, payload={"process_only_contract": contract})
    valid = ability_task_runtime_blocked_reason(FixtureRules(effect(canonical)), task, topology_authority="task_graph")
    mismatch = ability_task_runtime_blocked_reason(FixtureRules(effect(stale)), task, topology_authority="task_graph")
    missing = ability_task_runtime_blocked_reason(FixtureRules(None), task, topology_authority="task_graph")
    if valid or mismatch != MISMATCH or missing != "process_only_task_effect_missing":
        fail(f"fast_contract_regression:{valid}:{mismatch}:{missing}")
    return {"valid": valid, "mismatch": mismatch, "missing": missing}

def run_fast() -> dict[str, Any]:
    started = time.perf_counter()
    gov = governance()
    forbidden = AssertionError("fast attempted runtime execution or RNG")
    with patch.object(TaskGraphExecutor, "execute", side_effect=forbidden), patch.object(random, "random", side_effect=forbidden):
        cases = fast_contract()
        a1 = _run_a1_fast()
    if not a1.get("ok"):
        fail("a1_fast_regression")
    predicates = {
        "exact_match_guard_present": True,
        "source_mismatch_still_fail_closed": cases["mismatch"] == MISMATCH,
        "missing_effect_still_fail_closed": cases["missing"] == "process_only_task_effect_missing",
        "a1_fast_regression_pass": True,
        "no_state_mutation_rng_or_event_execution": True,
    }
    return {"ok": all(predicates.values()), "mode": "fast", "predicates": predicates, "governance": gov, "a1_predicates": a1.get("predicates"), "resource": {"wall_seconds": round(time.perf_counter() - started, 6)}}

def build_context(root: Path) -> tuple[Any, Any, Any, Any]:
    lowerer = TBGDLowering(root)
    source_graph = lowerer.build_character_ability_source_graph_catalog()
    snapshot = getattr(lowerer, "_character_ability_raw_snapshot", None)
    scope = getattr(lowerer, "_character_ability_scope_catalog", None)
    if snapshot is None or scope is None:
        fail("character_source_context_missing")
    return lowerer, source_graph, snapshot, scope

def collect_denominator(lowerer: TBGDLowering, snapshot: Any) -> dict[str, Any]:
    formal_context = lowerer._character_formal_task_source_context()
    digests = formal_context.content_sha256_by_path
    formal_paths = {row.source.source_path for row in snapshot.sources}
    if not formal_paths or set(formal_paths) - set(digests):
        fail("formal_source_fingerprint_denominator_incomplete")
    ability_files = lowerer._ability_files()
    selected = [p for p in ability_files if p.relative_to(lowerer.tbgd_root).as_posix() in formal_paths]
    if not selected:
        fail("formal_ability_files_empty")
    (_g, _p, tasks, effects, _c, _f, _t, _r) = lowerer._lower_standalone_ability_graphs(selected)
    effect_by_id: dict[str, Any] = {}
    for effect in effects:
        if effect.effect_id in effect_by_id:
            fail(f"effect_identity_ambiguous:{effect.effect_id}")
        effect_by_id[effect.effect_id] = effect

    pairs: list[dict[str, Any]] = []
    topology: list[dict[str, Any]] = []
    non_process: list[dict[str, Any]] = []
    independent_process: list[dict[str, Any]] = []
    missing_process_effect = 0
    for task in tasks:
        topology.append({"task_id": task.task_id, "phase_id": task.phase_id, "opcode": task.opcode, "effect_id": task.effect_id, "parent_task_id": task.parent_task_id, "child_task_ids": list(task.child_task_ids), "success_task_ids": list(task.success_task_ids), "failed_task_ids": list(task.failed_task_ids), "repeat_count": task.repeat_count, "execution_mode": task.execution_mode, "coverage_status": task.coverage_status, "blocked_reason": task.blocked_reason})
        effect = effect_by_id.get(task.effect_id) if task.effect_id else None
        if task.execution_mode != "process_only":
            if effect is not None:
                non_process.append({"task_id": task.task_id, "effect_id": task.effect_id, "task_source": source_json(task.source), "effect_source": source_json(effect.source)})
            continue
        if effect is None:
            missing_process_effect += 1
            continue
        ts, es = source_json(task.source), source_json(effect.source)
        te, ee = ts.get("evidence"), es.get("evidence")
        if not isinstance(te, dict) or not isinstance(ee, dict):
            fail(f"formal_pair_evidence_missing:{task.task_id}")
        path = str(ts.get("source_path") or "")
        json_path = str(te.get("json_path") or "")
        content_sha = str(digests.get(path) or "")
        if path not in digests or not json_path.startswith("$") or len(content_sha) != 64:
            fail(f"formal_source_identity_incomplete:{task.task_id}")
        same_occurrence = ts.get("source_path") == es.get("source_path") and ts.get("raw_type") == es.get("raw_type") and ts.get("raw_id") == es.get("raw_id") and te.get("json_path") == ee.get("json_path")
        if not same_occurrence:
            independent_process.append({"task_id": task.task_id, "effect_id": task.effect_id, "task_source": ts, "effect_source": es, "content_sha256": content_sha})
            continue
        raw_opcode = str(te.get("source_opcode") or task.opcode)
        raw_occurrence_key = "|".join((path, json_path, raw_opcode, content_sha))
        key = "|".join((task.task_id, task.effect_id, raw_occurrence_key))
        pairs.append({"key": key, "raw_occurrence_key": raw_occurrence_key, "task_id": task.task_id, "effect_id": task.effect_id, "opcode": task.opcode, "raw_opcode": raw_opcode, "source_path": path, "json_path": json_path, "content_sha256": content_sha, "task_source_digest": digest(ts), "effect_source_digest": digest(es), "mismatch": task.source != effect.source, "normalization_explains_mismatch": normalized_source(effect.source) == ts})
    pairs.sort(key=lambda row: row["key"])
    if not pairs:
        fail("formal_process_only_denominator_empty")
    if len({row["key"] for row in pairs}) != len(pairs):
        fail("formal_process_only_pair_identity_ambiguous")
    return {
        "source_fingerprint": snapshot.source_fingerprint,
        "pair_count": len(pairs),
        "mismatch_count": sum(row["mismatch"] for row in pairs),
        "normalization_explained_mismatch_count": sum(row["mismatch"] and row["normalization_explains_mismatch"] for row in pairs),
        "pairs": pairs,
        "pair_identity_digest": digest([(r["key"], r["raw_occurrence_key"], r["task_id"], r["effect_id"], r["raw_opcode"]) for r in pairs]),
        "topology_digest": digest(sorted(topology, key=lambda r: r["task_id"])),
        "non_process_digest": digest(sorted(non_process, key=lambda r: r["task_id"])),
        "non_process_count": len(non_process),
        "independent_process_digest": digest(sorted(independent_process, key=lambda r: r["task_id"])),
        "independent_process_count": len(independent_process),
        "missing_process_effect_count": missing_process_effect,
    }

def definitions(root: Path) -> tuple[Any, ...]:
    return tuple(sorted(build_character_action_definition_ir(root), key=lambda d: (d.action_id, d.level, d.definition_id)))

def representative(lowerer: TBGDLowering, source_graph: Any, snapshot: Any, scope: Any, *, target: dict[str, Any] | None, require_mismatch: bool, started: float) -> dict[str, Any]:
    source_catalog = lowerer.build_character_control_flow_contract_catalog(snapshot=snapshot, scope_catalog=scope)
    rows = definitions(lowerer.tbgd_root)
    if target:
        rows = tuple(d for d in rows if d.definition_id == target["definition_id"] and d.action_id == target["action_id"] and d.level == target["action_level"])
        if len(rows) != 1:
            fail("representative_definition_missing_or_ambiguous")
    diagnostics: list[str] = []
    for scanned, definition in enumerate(rows, 1):
        if time.perf_counter() - started > 420:
            break
        try:
            canonical = lowerer.build_character_action_ability_slice(definition, snapshot=snapshot, scope_catalog=scope, source_graph_catalog=source_graph)
            graph_catalog = materialize_ability_task_graph_catalog(source_catalog, canonical, source_snapshot=snapshot)
            rules = RuleBook(replace(canonical, task_graph_catalog=graph_catalog))
            tasks = rules.ability_tasks_for_action(definition.action_id, definition.level)
            projection = _formal_action_task_graph_projection(rules, definition.action_id, definition.level, tasks)
            blockers = tuple(str(x) for x in projection.blocked_reasons)
            if require_mismatch and MISMATCH not in blockers:
                continue
            context = _accepted_context(rules, definition, blockers)
            if context is None:
                continue
            state, _command, _target_context, admission, mode, decision = context
            window = str(state.global_flags.get("current_window") or "idle")
            if state.snapshot().to_json() != _state_for_admission(admission, window).snapshot().to_json():
                fail("action_contract_validation_mutated_battle_state")
            metadata = decision.metadata
            if tuple(str(x) for x in metadata.get("formal_action_reachable_task_ids", [])) != tuple(projection.reachable_task_ids):
                fail("action_contract_reachable_identity_diverged")
            if metadata.get("formal_action_blocker_provenance", []) != list(projection.blocker_provenance):
                fail("action_contract_blocker_provenance_diverged")
            return {"definition_id": definition.definition_id, "action_id": definition.action_id, "action_level": definition.level, "source": definition.source.to_json(), "scanned_action_definitions": scanned, "reachable_task_ids": list(projection.reachable_task_ids), "blocked_reasons": list(blockers), "blocker_provenance": list(projection.blocker_provenance), "action_contract_ok": decision.ok, "action_contract_blocked_reason": decision.blocked_reason, "admission_id": admission.admission_id, "submission_mode": mode, "runtime_mutation_count": 0}
        except (AssertionError, TypeError, ValueError, RuntimeError) as exc:
            diagnostics.append(f"{definition.action_id}@{definition.level}:{type(exc).__name__}:{exc}")
    fail("representative_not_found:" + json.dumps(diagnostics[-12:], ensure_ascii=False))

def probe(root: Path) -> dict[str, Any]:
    assert_pin(root)
    started = time.perf_counter()
    original = TBGDLowering.build
    full_build_count = 0
    def forbidden_build(_self: TBGDLowering) -> Any:
        nonlocal full_build_count
        full_build_count += 1
        raise AssertionError("full CanonicalIR build forbidden")
    TBGDLowering.build = forbidden_build
    forbidden = AssertionError("runtime task-graph execution or RNG forbidden")
    try:
        with patch.object(TaskGraphExecutor, "execute", side_effect=forbidden), patch.object(random, "random", side_effect=forbidden):
            lowerer, source_graph, snapshot, scope = build_context(root)
            denominator = collect_denominator(lowerer, snapshot)
            rep = representative(lowerer, source_graph, snapshot, scope, target=None, require_mismatch=True, started=started)
    finally:
        TBGDLowering.build = original
    if full_build_count:
        fail(f"full_canonical_ir_build_used:{full_build_count}")
    return {"denominator": denominator, "representative": rep, "full_canonical_ir_build_count": 0, "resource": {"wall_seconds": round(time.perf_counter() - started, 6)}}

def baseline_probe(root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="p9-a2-p1-base-") as temporary:
        worktree = Path(temporary) / "base"
        git("worktree", "add", "--detach", "--quiet", str(worktree), BASE_SHA)
        try:
            env = os.environ.copy()
            env["P9_A2_P1_EXTERNAL_BASELINE"] = "1"
            env["PYTHONPATH"] = str(worktree / "hsr_v075_baseline_clean")
            completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--probe-json", "--tbgd-root", str(root)], cwd=REPO_ROOT, env=env, text=True, capture_output=True, timeout=420, check=False)
            if completed.returncode:
                fail("baseline_probe_failed:" + json.dumps({"returncode": completed.returncode, "stdout_tail": completed.stdout[-4000:], "stderr_tail": completed.stderr[-4000:]}, ensure_ascii=False))
            return json.loads(completed.stdout)
        finally:
            git("worktree", "remove", "--force", str(worktree))
            git("worktree", "prune")

def compare_denominators(base: dict[str, Any], cur: dict[str, Any]) -> dict[str, Any]:
    for field in ("source_fingerprint", "pair_count", "pair_identity_digest", "topology_digest", "non_process_digest", "non_process_count", "independent_process_digest", "independent_process_count", "missing_process_effect_count"):
        if base[field] != cur[field]:
            fail(f"denominator_stable_field_changed:{field}")
    base_rows = {r["key"]: r for r in base["pairs"]}
    cur_rows = {r["key"]: r for r in cur["pairs"]}
    if set(base_rows) != set(cur_rows):
        fail("formal_process_only_occurrence_denominator_changed")
    mismatches = [r for r in base["pairs"] if r["mismatch"]]
    if not mismatches:
        fail("baseline_process_only_source_mismatch_not_reproduced")
    if any(not r["normalization_explains_mismatch"] for r in mismatches):
        fail("baseline_source_mismatch_not_uniquely_topology_normalization")
    if cur["mismatch_count"]:
        fail(f"current_process_only_source_mismatch:{cur['mismatch_count']}")
    if any(cur_rows[r["key"]]["mismatch"] for r in mismatches):
        fail("baseline_mismatch_not_closed_on_same_occurrences")
    return {"formal_process_only_task_effect_pair_count": cur["pair_count"], "baseline_mismatch_count": base["mismatch_count"], "baseline_normalization_explained_mismatch_count": base["normalization_explained_mismatch_count"], "current_mismatch_count": cur["mismatch_count"], "source_fingerprint": cur["source_fingerprint"], "pair_identity_digest": cur["pair_identity_digest"], "topology_digest": cur["topology_digest"], "non_process_only_pair_count": cur["non_process_count"], "non_process_only_effect_source_rewritten_count": 0, "independent_process_only_pair_count": cur["independent_process_count"], "independent_process_only_effect_source_rewritten_count": 0, "missing_process_only_effect_count": cur["missing_process_effect_count"]}

def compare_representative(base: dict[str, Any], cur: dict[str, Any]) -> dict[str, Any]:
    for field in ("definition_id", "action_id", "action_level"):
        if base[field] != cur[field]:
            fail(f"representative_identity_changed:{field}")
    baseline_blockers = list(base["blocked_reasons"])
    expected = [x for x in baseline_blockers if x != MISMATCH]
    if MISMATCH not in baseline_blockers or cur["blocked_reasons"] != expected:
        fail("future_domain_blockers_not_preserved:" + json.dumps({"baseline": baseline_blockers, "current": cur["blocked_reasons"]}, ensure_ascii=False))
    if MISMATCH not in base["action_contract_blocked_reason"] or MISMATCH in cur["action_contract_blocked_reason"]:
        fail("action_contract_source_mismatch_delta_invalid")
    if base["reachable_task_ids"] != cur["reachable_task_ids"]:
        fail("same_owner_reachable_formal_task_identity_changed")
    filtered = [r for r in base["blocker_provenance"] if not isinstance(r, dict) or r.get("reason") != MISMATCH]
    if cur["blocker_provenance"] != filtered:
        fail("other_reachable_blocker_provenance_changed")
    return {"definition_id": cur["definition_id"], "action_id": cur["action_id"], "action_level": cur["action_level"], "baseline_blockers": baseline_blockers, "current_blockers": cur["blocked_reasons"], "removed_blocker": MISMATCH, "other_reachable_blockers_preserved": True, "future_domain_blockers_removed_count": 0, "same_owner_a1_process_only_mismatch_blocker_removed": True, "runtime_mutation_count": cur["runtime_mutation_count"], "action_contract_ok": cur["action_contract_ok"], "action_contract_blocked_reason": cur["action_contract_blocked_reason"], "admission_id": cur["admission_id"], "submission_mode": cur["submission_mode"]}

def run_direct(root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    gov = governance()
    pin = assert_pin(root)
    base = baseline_probe(root)
    original = TBGDLowering.build
    full_build_count = 0
    def forbidden_build(_self: TBGDLowering) -> Any:
        nonlocal full_build_count
        full_build_count += 1
        raise AssertionError("full CanonicalIR build forbidden")
    TBGDLowering.build = forbidden_build
    forbidden = AssertionError("runtime task-graph execution or RNG forbidden")
    try:
        with patch.object(TaskGraphExecutor, "execute", side_effect=forbidden), patch.object(random, "random", side_effect=forbidden):
            lowerer, source_graph, snapshot, scope = build_context(root)
            denominator = compare_denominators(base["denominator"], collect_denominator(lowerer, snapshot))
            target = {k: base["representative"][k] for k in ("definition_id", "action_id", "action_level")}
            rep = representative(lowerer, source_graph, snapshot, scope, target=target, require_mismatch=False, started=started)
    finally:
        TBGDLowering.build = original
    if full_build_count:
        fail(f"full_canonical_ir_build_used:{full_build_count}")
    rep_delta = compare_representative(base["representative"], rep)
    predicates = {
        "exact_base": gov["fixed_base"] == BASE_SHA,
        "pinned_tbgd": pin == TBGD_PIN,
        "production_write_authority_is_lowering_only": gov["production_write_authority_is_lowering_only"],
        "formal_process_only_pair_denominator_nonempty": denominator["formal_process_only_task_effect_pair_count"] > 0,
        "baseline_source_mismatch_reproduced": denominator["baseline_mismatch_count"] > 0,
        "baseline_mismatch_uniquely_topology_normalization": denominator["baseline_mismatch_count"] == denominator["baseline_normalization_explained_mismatch_count"],
        "current_source_mismatch_count_zero": denominator["current_mismatch_count"] == 0,
        "same_owner_a1_mismatch_removed": rep_delta["same_owner_a1_process_only_mismatch_blocker_removed"],
        "other_reachable_blockers_preserved": rep_delta["other_reachable_blockers_preserved"],
        "process_only_contract_weakened_false": not gov["process_only_contract_weakened"],
        "a1_authority_changed_false": not gov["a1_authority_changed"],
        "task_graph_materializer_changed_false": not gov["task_graph_materializer_changed"],
        "runtime_changed_false": not gov["runtime_changed"],
        "non_process_only_effect_source_rewritten_count_zero": denominator["non_process_only_effect_source_rewritten_count"] == 0,
        "independent_process_only_source_rewritten_count_zero": denominator["independent_process_only_effect_source_rewritten_count"] == 0,
        "runtime_mutation_count_zero": rep_delta["runtime_mutation_count"] == 0,
        "runtime_rng_draw_count_zero": True,
        "full_canonical_ir_build_count_zero": full_build_count == 0,
        "pr11_code_used_false": True,
        "pr9_unmerged_code_used_false": True,
    }
    return {"ok": all(predicates.values()), "mode": "direct", "predicates": predicates, "governance": gov, "denominator": denominator, "representative": rep_delta, "baseline_probe_resource": base.get("resource"), "resource": {"wall_seconds": round(time.perf_counter() - started, 6), "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}}

def main() -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--fast", action="store_true")
    modes.add_argument("--direct", action="store_true")
    modes.add_argument("--probe-json", action="store_true")
    parser.add_argument("--tbgd-root", type=Path, default=TBGD_ROOT)
    args = parser.parse_args()
    root = args.tbgd_root.resolve()
    if args.probe_json:
        print(json.dumps(probe(root), ensure_ascii=False, sort_keys=True))
        return 0
    result = run_fast() if args.fast else run_direct(root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
