from __future__ import annotations

import argparse, json, os, random, resource, subprocess, sys, tempfile, time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
BASELINE = ROOT / "hsr_v075_baseline_clean"
TBGD = ROOT / "turnbasedgamedata-main"
BASE_SHA = "f6ea5d2e2d067cb8cecb82bb28faf14beb2a29b4"
TBGD_PIN = "14c1d18f91a8101d610e6c523447a7517de3fae1"
MISMATCH = "ability_task_graph_nested_identity_mismatch"
ACTION = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py"
VALIDATOR = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p2_process_only_trigger_ability_admission_identity.py"
REPORT = "hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2-P2_PROCESS_ONLY_TRIGGER_ABILITY_ADMISSION_IDENTITY_execution_report.md"
WORKFLOW = ".github/workflows/p9-a2-p2-pr-validation.yml"
CARD = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-A2-P2_PROCESS_ONLY_TRIGGER_ABILITY_ADMISSION_IDENTITY.md"
ALLOWED = {ACTION, VALIDATOR, REPORT, WORKFLOW, CARD}
READ_ONLY = (
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability_task_contract.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/task_graph.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/rulebook.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/ir_types.py",
)
if os.environ.get("P9_A2_P2_EXTERNAL_BASELINE") != "1":
    sys.path.insert(0, str(BASELINE))

from hsr.simulator_v8_clean_core.rules.evaluator import RuleEvaluator
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.rules.task_graph import TaskGraphIR
from hsr.simulator_v8_clean_core.systems.ability_task_contract import ability_task_runtime_blocked_reason, is_process_only_ability_task
from hsr.simulator_v8_clean_core.systems.action_contract import _formal_action_task_graph_projection
from hsr.simulator_v8_clean_core.systems.task_graph import TaskGraphExecutor
from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering
from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import materialize_ability_task_graph_catalog
from hsr.simulator_v8_clean_core.tools.validate_p9_formal_action_graph_admission_authority import _graph, _phase, _project, _run_fast as _a1_fast, _source, _task
from hsr.simulator_v8_clean_core.tools.validate_p9_a2_p1_formal_process_only_source_identity import build_context as _build_context, definitions as _definitions, _accepted_context, _state_for_admission


def fail(msg: str) -> None: raise AssertionError(msg)
def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()

def governance() -> dict[str, Any]:
    if git("merge-base", BASE_SHA, "HEAD") != BASE_SHA: fail("fixed_base_not_ancestor")
    changed = tuple(x for x in git("diff", "--name-only", BASE_SHA, "HEAD").splitlines() if x)
    extra = sorted(set(changed) - ALLOWED)
    if extra: fail("scope_leak:" + ",".join(extra))
    production = tuple(x for x in changed if "/simulator_v8_clean_core/" in x and "/tools/" not in x and "/docs/" not in x)
    if production != (ACTION,): fail("production_authority_changed:" + ",".join(production))
    for path in READ_ONLY:
        if (ROOT / path).read_text(encoding="utf-8").rstrip("\n") != git("show", f"{BASE_SHA}:{path}").rstrip("\n"):
            fail("read_only_authority_changed:" + path)
    diff = git("diff", "--unified=3", BASE_SHA, "HEAD", "--", ACTION)
    for token in ("process_only = is_process_only_ability_task(task)", 'task.opcode == "TriggerAbility" and not process_only', "or process_only"):
        if token not in diff: fail("production_patch_shape_missing:" + token)
    return {"fixed_base": BASE_SHA, "changed_paths": list(changed), "production_paths": list(production)}

def effect(task: Any, source: Any | None = None) -> Any:
    return SimpleNamespace(opcode=task.opcode, coverage_status="audit_only", source=task.source if source is None else source, payload={"process_only_contract": {"schema_version": "ability_process_only_source_shape_v1", "opcode": task.opcode, "source_fields": ["$type"], "source_field_types": {"$type": "str"}, "source_shape_status": "admitted", "blocked_reason": ""}})

def reasons(p: Any) -> set[str]: return {str(x) for x in p.blocked_reasons}

def run_fast() -> dict[str, Any]:
    started = time.perf_counter(); gov = governance()
    forbidden = AssertionError("admission attempted runtime execution")
    with patch.object(TaskGraphExecutor, "execute", side_effect=forbidden), patch.object(RuleEvaluator, "evaluate_condition_result", side_effect=forbidden), patch.object(random, "random", side_effect=forbidden):
        pp = _phase("p2:p:process"); pt = _task("p2:t:process", pp.phase_id, opcode="TriggerAbility", execution_mode="process_only", coverage_status="audit_only", effect_id="p2:e:process")
        pg = _graph(pp.phase_id, pt, node_kind="leaf", references=(("effect", pt.effect_id, "deferred", "audit_only_reference"),))
        positive, prules = _project((pp,), (pt,), (pg,), {pt.effect_id: effect(pt)})
        if positive.blocked_reasons or prules.graph_query_count != 1: fail("valid_process_only_trigger_leaf_not_admitted")
        bad_source, _ = _project((pp,), (pt,), (pg,), {pt.effect_id: effect(pt, _source("foreign", "TriggerAbility"))})
        if "process_only_task_effect_source_mismatch" not in reasons(bad_source) or MISMATCH in reasons(bad_source): fail("process_only_contract_not_fail_closed")
        missing = _task("p2:t:missing", pp.phase_id, opcode="TriggerAbility", execution_mode="process_only", coverage_status="audit_only")
        missing_p, _ = _project((pp,), (missing,), (_graph(pp.phase_id, missing),))
        if "process_only_task_effect_missing" not in reasons(missing_p): fail("process_only_missing_effect_not_fail_closed")
        process_call, _ = _project((pp,), (pt,), (_graph(pp.phase_id, pt, node_kind="ability_call", references=(("ability", "p2:p:unused", "resolved", ""),)),), {pt.effect_id: effect(pt)})
        if MISMATCH not in reasons(process_call): fail("process_only_ability_call_not_fail_closed")
        gp = _phase("p2:p:gameplay"); np = _phase("p2:p:nested", "nested_only")
        gt = _task("p2:t:gameplay", gp.phase_id, opcode="TriggerAbility", linked_ability_phase_id=np.phase_id)
        leaf, _ = _project((gp, np), (gt,), (_graph(gp.phase_id, gt, node_kind="leaf"),))
        if MISMATCH not in reasons(leaf): fail("runtime_trigger_leaf_not_fail_closed")
        op = _phase("p2:p:ordinary"); ot = _task("p2:t:ordinary", op.phase_id)
        ordinary, _ = _project((op,), (ot,), (_graph(op.phase_id, ot, node_kind="ability_call", references=(("ability", "p2:p:unused", "resolved", ""),)),))
        if MISMATCH not in reasons(ordinary): fail("ordinary_ability_call_not_fail_closed")
        nt = _task("p2:t:nested_blocker", np.phase_id, coverage_status="blocked", blocked_reason="fixture_nested_blocker")
        legal, _ = _project((gp, np), (gt, nt), (_graph(gp.phase_id, gt, node_kind="ability_call", references=(("ability", np.phase_id, "resolved", ""),)), _graph(np.phase_id, nt)))
        if MISMATCH in reasons(legal) or "fixture_nested_blocker" not in reasons(legal): fail("legal_nested_contract_regressed")
        matrices = []
        matrices.append(_project((gp, np), (gt,), (_graph(gp.phase_id, gt, node_kind="ability_call"),))[0])
        matrices.append(_project((gp, np), (gt,), (_graph(gp.phase_id, gt, node_kind="ability_call", references=(("ability", np.phase_id, "deferred", "unresolved"),)),))[0])
        matrices.append(_project((gp, np), (gt,), (_graph(gp.phase_id, gt, node_kind="ability_call", references=(("ability", np.phase_id, "resolved", ""), ("ability", "p2:p:other", "resolved", ""))),))[0])
        if any("ability_task_graph_nested_reference_not_resolved" not in reasons(p) for p in matrices): fail("nested_reference_matrix_not_fail_closed")
        mismatch_link, _ = _project((gp, np), (gt,), (_graph(gp.phase_id, gt, node_kind="ability_call", references=(("ability", "p2:p:wrong", "resolved", ""),)),))
        if "ability_task_graph_nested_phase_identity_mismatch" not in reasons(mismatch_link): fail("linked_phase_mismatch_not_fail_closed")
        st = _task("p2:t:standalone", gp.phase_id, opcode="TriggerAbility"); st.linked_standalone_graph_id = "p2:standalone"; st.linked_ability_phase_id = ""
        standalone, _ = _project((gp,), (st,), (_graph(gp.phase_id, st, node_kind="ability_call", references=(("ability", "p2:wrong", "resolved", ""),)),))
        if "ability_task_graph_nested_standalone_identity_mismatch" not in reasons(standalone): fail("standalone_mismatch_not_fail_closed")
        up = _phase("p2:p:unsupported"); ut = _task("p2:t:unsupported", up.phase_id, coverage_status="blocked", blocked_reason="fixture_unsupported_gameplay")
        unsupported, _ = _project((up,), (ut,), (_graph(up.phase_id, ut),))
        if "fixture_unsupported_gameplay" not in reasons(unsupported): fail("unsupported_gameplay_not_preserved")
        repeated, _ = _project((pp,), (pt,), (pg,), {pt.effect_id: effect(pt)})
        if repeated != positive: fail("projection_not_deterministic")
        a1 = _a1_fast()
    elapsed = time.perf_counter() - started
    preds = {"process_only_trigger_leaf_admitted": True, "invalid_process_only_contract_fail_closed": True, "gameplay_nested_identity_fail_closed": True, "nested_reference_link_fail_closed": True, "reachable_future_blocker_preserved": True, "projection_deterministic": True, "a1_fast_regression": bool(a1.get("ok")), "no_runtime_execution_condition_or_rng": True}
    return {"ok": elapsed <= 30 and all(preds.values()), "mode": "fast", "predicates": preds, "governance": gov, "a1_predicates": a1.get("predicates"), "resource": {"wall_seconds": round(elapsed, 6)}}

def node_for(rules: RuleBook, row: dict[str, Any]) -> tuple[Any, Any]:
    tasks = tuple(t for t in rules.ability_tasks_for_phase(str(row["phase_id"])) if t.callback_kind == row["callback_kind"])
    q = rules.query_formal_task_graph("ability_phase_callback", str(row["phase_id"]), str(row["callback_kind"]), (t.task_id for t in tasks)); g = q.value
    if q.status != "resolved" or type(g) is not TaskGraphIR or g.graph_id != row["graph_id"]: fail("provenance_graph_identity_mismatch")
    ns = [n for n in g.nodes if n.graph_node_id == row["graph_node_id"]]; t = rules.ability_task(str(row["task_id"]))
    if len(ns) != 1 or t is None or ns[0].formal_task_id != t.task_id: fail("provenance_node_task_identity_mismatch")
    return t, ns[0]

def qualifying(rules: RuleBook, projection: Any) -> list[dict[str, Any]]:
    out = []
    for raw in projection.blocker_provenance:
        row = dict(raw)
        if row.get("reason") != MISMATCH or row.get("source") != "nested_node_identity": continue
        task, node = node_for(rules, row); rr = ability_task_runtime_blocked_reason(rules, task, topology_authority="task_graph")
        if task.opcode == "TriggerAbility" and is_process_only_ability_task(task) and node.node_kind == "leaf" and node.materialization_status == "materialized" and not rr:
            out.append({**row, "opcode": task.opcode, "execution_mode": task.execution_mode, "node_kind": node.node_kind, "materialization_status": node.materialization_status, "runtime_support_blocked_reason": rr, "task_source": task.source.to_json()})
    return out

def representative(root: Path, target: dict[str, Any] | None, require_mismatch: bool, started: float) -> dict[str, Any]:
    lowerer, source_graph, snapshot, scope = _build_context(root); source_catalog = lowerer.build_character_control_flow_contract_catalog(snapshot=snapshot, scope_catalog=scope)
    rows = _definitions(root)
    if target:
        rows = tuple(d for d in rows if d.definition_id == target["definition_id"] and d.action_id == target["action_id"] and d.level == target["action_level"])
        if len(rows) != 1: fail("representative_definition_missing")
    scanned = eligible = matches = occurrences = 0; diagnostics = []
    for d in rows:
        if time.perf_counter() - started > 105: break
        scanned += 1
        try:
            canonical = lowerer.build_character_action_ability_slice(d, snapshot=snapshot, scope_catalog=scope, source_graph_catalog=source_graph)
            catalog = materialize_ability_task_graph_catalog(source_catalog, canonical, source_snapshot=snapshot); rules = RuleBook(replace(canonical, task_graph_catalog=catalog)); tasks = rules.ability_tasks_for_action(d.action_id, d.level)
            projection = _formal_action_task_graph_projection(rules, d.action_id, d.level, tasks); ctx = _accepted_context(rules, d, tuple(str(x) for x in projection.blocked_reasons))
            if ctx is None or ctx[4] != "external_turn": continue
            eligible += 1; state, _, _, admission, mode, decision = ctx; window = str(state.global_flags.get("current_window") or "idle")
            if state.snapshot().to_json() != _state_for_admission(admission, window).snapshot().to_json(): fail("action_contract_mutated_state")
            qs = qualifying(rules, projection); matches += bool(qs); occurrences += len(qs)
            if require_mismatch and not qs: continue
            if not require_mismatch and qs: fail("current_process_only_nested_identity_mismatch_remains")
            shapes = []
            for task_id in projection.reachable_task_ids:
                task = rules.ability_task(task_id)
                if task is None or task.opcode != "TriggerAbility" or not is_process_only_ability_task(task): continue
                phase_tasks = tuple(t for t in rules.ability_tasks_for_phase(task.phase_id) if t.callback_kind == task.callback_kind); q = rules.query_formal_task_graph("ability_phase_callback", task.phase_id, task.callback_kind, (t.task_id for t in phase_tasks)); g = q.value
                if q.status != "resolved" or type(g) is not TaskGraphIR: fail("current_process_graph_missing")
                nodes = [n for n in g.nodes if n.formal_task_id == task_id]
                if len(nodes) != 1: fail("current_process_node_missing")
                n = nodes[0]; shapes.append({"task_id": task_id, "opcode": task.opcode, "execution_mode": task.execution_mode, "node_kind": n.node_kind, "materialization_status": n.materialization_status, "runtime_support_blocked_reason": ability_task_runtime_blocked_reason(rules, task, topology_authority="task_graph")})
            return {"definition_id": d.definition_id, "action_id": d.action_id, "action_level": d.level, "source_fingerprint": snapshot.source_fingerprint, "scanned_action_definitions": scanned, "eligible_external_turn_candidates": eligible, "matching_candidate_count": matches, "matching_occurrence_count": occurrences, "root_graph_ids": list(projection.root_graph_ids), "reachable_task_ids": list(projection.reachable_task_ids), "excluded_bound_task_ids": list(projection.excluded_bound_task_ids), "blocked_reasons": list(projection.blocked_reasons), "blocker_provenance": list(projection.blocker_provenance), "qualifying_mismatches": qs, "process_only_trigger_shapes": shapes, "action_contract_ok": decision.ok, "action_contract_blocked_reason": decision.blocked_reason, "admission_id": admission.admission_id, "submission_mode": mode}
        except (AssertionError, TypeError, ValueError, RuntimeError) as exc: diagnostics.append(f"{d.action_id}@{d.level}:{type(exc).__name__}:{exc}")
    fail("representative_not_found:" + json.dumps({"scanned": scanned, "eligible": eligible, "matches": matches, "occurrences": occurrences, "diagnostics": diagnostics[-10:]}, ensure_ascii=False))

def probe(root: Path) -> dict[str, Any]:
    if git("rev-parse", "HEAD", cwd=root) != TBGD_PIN: fail("tbgd_pin_mismatch")
    started = time.perf_counter(); original = TBGDLowering.build; count = 0
    def forbidden(_self: TBGDLowering) -> Any:
        nonlocal count; count += 1; raise AssertionError("full CanonicalIR build forbidden")
    TBGDLowering.build = forbidden
    try:
        with patch.object(TaskGraphExecutor, "execute", side_effect=AssertionError("runtime graph execution forbidden")), patch.object(RuleEvaluator, "evaluate_condition_result", side_effect=AssertionError("condition evaluation forbidden")), patch.object(random, "random", side_effect=AssertionError("rng forbidden")):
            rep = representative(root, None, True, started)
    finally: TBGDLowering.build = original
    if count: fail("full_build_used")
    return {"representative": rep, "resource": {"wall_seconds": round(time.perf_counter()-started, 6), "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}}

def baseline_probe(root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="p9-a2-p2-base-") as temp:
        wt = Path(temp) / "base"; git("worktree", "add", "--detach", "--quiet", str(wt), BASE_SHA)
        try:
            env = os.environ.copy(); env["P9_A2_P2_EXTERNAL_BASELINE"] = "1"; env["P9_A2_P1_EXTERNAL_BASELINE"] = "1"; env["PYTHONPATH"] = str(wt / "hsr_v075_baseline_clean")
            cp = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--probe-json", "--tbgd-root", str(root)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=110, check=False)
            if cp.returncode: fail("baseline_probe_failed:" + json.dumps({"rc": cp.returncode, "stdout": cp.stdout[-3000:], "stderr": cp.stderr[-3000:]}, ensure_ascii=False))
            return json.loads(cp.stdout)
        finally: git("worktree", "remove", "--force", str(wt)); git("worktree", "prune")

def run_direct(root: Path) -> dict[str, Any]:
    started = time.perf_counter(); gov = governance()
    if git("rev-parse", "HEAD", cwd=root) != TBGD_PIN: fail("tbgd_pin_mismatch")
    base = baseline_probe(root); b = base["representative"]; target = {k: b[k] for k in ("definition_id", "action_id", "action_level")}
    original = TBGDLowering.build; count = 0
    def forbidden(_self: TBGDLowering) -> Any:
        nonlocal count; count += 1; raise AssertionError("full CanonicalIR build forbidden")
    TBGDLowering.build = forbidden
    try:
        with patch.object(TaskGraphExecutor, "execute", side_effect=AssertionError("runtime graph execution forbidden")), patch.object(RuleEvaluator, "evaluate_condition_result", side_effect=AssertionError("condition evaluation forbidden")), patch.object(random, "random", side_effect=AssertionError("rng forbidden")):
            cur = representative(root, target, False, started)
    finally: TBGDLowering.build = original
    if count or not b["qualifying_mismatches"]: fail("direct_baseline_or_full_build_invalid")
    def provenance_key(row: dict[str, Any]) -> tuple[str, ...]:
        return tuple(str(row.get(key) or "") for key in ("reason", "source", "phase_id", "callback_kind", "graph_id", "graph_node_id", "task_id"))
    removed_keys = {provenance_key(row) for row in b["qualifying_mismatches"]}
    preserved = [row for row in b["blocker_provenance"] if provenance_key(row) not in removed_keys]
    preserved_mismatch = any(row.get("reason") == MISMATCH for row in preserved)
    expected_reasons = [r for r in b["blocked_reasons"] if r != MISMATCH or preserved_mismatch]
    if cur["root_graph_ids"] != b["root_graph_ids"] or cur["reachable_task_ids"] != b["reachable_task_ids"] or cur["excluded_bound_task_ids"] != b["excluded_bound_task_ids"]: fail("graph_or_task_identity_changed")
    if cur["blocker_provenance"] != preserved or cur["blocked_reasons"] != expected_reasons: fail("non_p2_blockers_changed")
    if cur["source_fingerprint"] != b["source_fingerprint"] or cur["qualifying_mismatches"] or cur["action_contract_ok"]: fail("current_representative_contract_invalid")
    ids = {row["task_id"] for row in b["qualifying_mismatches"]}; shapes = [row for row in cur["process_only_trigger_shapes"] if row["task_id"] in ids]
    if {row["task_id"] for row in shapes} != ids or any(row["opcode"] != "TriggerAbility" or row["execution_mode"] != "process_only" or row["node_kind"] != "leaf" or row["materialization_status"] != "materialized" or row["runtime_support_blocked_reason"] for row in shapes): fail("current_process_only_trigger_leaf_shape_changed")
    elapsed = time.perf_counter() - started; peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    preds = {"fixed_base": gov["fixed_base"] == BASE_SHA, "real_denominator_nonempty": bool(b["qualifying_mismatches"]), "baseline_root_cause_reproduced": True, "only_nested_identity_provenance_removed": True, "root_reachable_excluded_identity_preserved": True, "future_domain_blockers_preserved": bool(cur["blocked_reasons"]), "action_contract_still_fail_closed": not cur["action_contract_ok"], "runtime_mutation_rng_graph_condition_zero": True, "read_only_authorities_unchanged": True, "full_build_zero": count == 0}
    return {"ok": elapsed <= 120 and peak <= 1024*1024 and all(preds.values()), "mode": "direct", "predicates": preds, "governance": gov, "baseline": b, "current": cur, "provenance_delta": {"removed": b["qualifying_mismatches"], "preserved": preserved, "remaining_blocked_reasons": cur["blocked_reasons"]}, "baseline_probe_resource": base.get("resource"), "resource": {"wall_seconds": round(elapsed, 6), "peak_rss_kib": peak}}

def main() -> int:
    p = argparse.ArgumentParser(); m = p.add_mutually_exclusive_group(required=True); m.add_argument("--fast", action="store_true"); m.add_argument("--direct", action="store_true"); m.add_argument("--probe-json", action="store_true"); p.add_argument("--tbgd-root", type=Path, default=TBGD); a = p.parse_args(); root = a.tbgd_root.resolve()
    if a.probe_json: print(json.dumps(probe(root), ensure_ascii=False, sort_keys=True)); return 0
    result = run_fast() if a.fast else run_direct(root); print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return 0 if result["ok"] else 1
if __name__ == "__main__": raise SystemExit(main())
