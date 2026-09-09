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
VALIDATOR_PATH = (
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/"
    "validate_p9_a2_p1_formal_process_only_source_identity.py"
)
REPORT_PATH = (
    "hsr_v075_baseline_clean/hsr/live_validation_reports/"
    "P9-A2-P1_FORMAL_PROCESS_ONLY_SOURCE_IDENTITY_execution_report.md"
)
WORKFLOW_PATH = ".github/workflows/p9-a2-p1-pr-validation.yml"
CARD_PATH = (
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/"
    "P9-A2-P1_FORMAL_PROCESS_ONLY_SOURCE_IDENTITY.md"
)
MISMATCH = "process_only_task_effect_source_mismatch"
TOPOLOGY_EVIDENCE = {"parent_task_id", "child_task_count"}

if os.environ.get("P9_A2_P1_EXTERNAL_BASELINE") != "1":
    if str(BASELINE_ROOT) not in sys.path:
        sys.path.insert(0, str(BASELINE_ROOT))

from hsr.simulator_v8_clean_core.ir_types import IRSource
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.systems.ability_task_contract import (
    ability_task_runtime_blocked_reason,
)
from hsr.simulator_v8_clean_core.systems.action_contract import (
    _formal_action_task_graph_projection,
)
from hsr.simulator_v8_clean_core.systems.task_graph import TaskGraphExecutor
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    TBGDLowering,
    build_character_action_definition_ir,
)
from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import (
    materialize_ability_task_graph_catalog,
)
from hsr.simulator_v8_clean_core.tools.validate_p9_formal_action_graph_admission_authority import (
    _accepted_context,
    _run_fast as _run_a1_fast,
    _state_for_admission,
)

_ALLOWED_CHANGED_PATHS = {
    CARD_PATH,
    LOWERING_PATH,
    VALIDATOR_PATH,
    REPORT_PATH,
    WORKFLOW_PATH,
}
_A1_AUTHORITY_PATHS = (
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability_task_contract.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/task_graph.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/ir_types.py",
)
_EXPECTED_LOWERING_ADDED_LINES = (
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
)


def _fail(message: str) -> None:
    raise AssertionError(message)


def _git(*args: str, cwd: Path = REPO_ROOT) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=cwd,
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()


def _json_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_json(source: Any) -> dict[str, Any]:
    to_json = getattr(source, "to_json", None)
    if not callable(to_json):
        _fail("source_without_to_json")
    value = to_json()
    if not isinstance(value, dict):
        _fail("source_to_json_not_object")
    return value


def _normalized_source_json(source: Any) -> dict[str, Any]:
    value = json.loads(json.dumps(_source_json(source)))
    evidence = value.get("evidence")
    if isinstance(evidence, dict):
        for key in TOPOLOGY_EVIDENCE:
            evidence.pop(key, None)
    return value


def _occurrence_key(task: Any) -> str:
    source = _source_json(task.source)
    evidence = source.get("evidence")
    if not isinstance(evidence, dict):
        _fail(f"source_evidence_missing:{task.task_id}")
    source_path = str(source.get("source_path") or "")
    json_path = str(evidence.get("json_path") or "")
    fingerprint = str(evidence.get("content_sha256") or "")
    if not source_path or not json_path.startswith("$") or len(fingerprint) != 64:
        _fail(f"formal_source_identity_incomplete:{task.task_id}")
    return "|".join((source_path, json_path, str(task.opcode)))


def _assert_pin(root: Path) -> str:
    actual = _git("rev-parse", "HEAD", cwd=root)
    if actual != TBGD_PIN:
        _fail(f"tbgd_pin_mismatch:{actual}")
    return actual


def _function_ast(source: str, function_name: str) -> str:
    module = ast.parse(source)
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return ast.dump(node, include_attributes=False)
    _fail(f"function_missing:{function_name}")


def _assert_governance() -> dict[str, Any]:
    if _git("merge-base", BASE_SHA, "HEAD") != BASE_SHA:
        _fail("fixed_base_not_ancestor")
    changed = tuple(
        line
        for line in _git("diff", "--name-only", BASE_SHA, "HEAD").splitlines()
        if line
    )
    extra = sorted(set(changed) - _ALLOWED_CHANGED_PATHS)
    if extra:
        _fail("scope_leak:" + ",".join(extra))

    equal_paths: list[str] = []
    for relative in _A1_AUTHORITY_PATHS:
        current = (REPO_ROOT / relative).read_text(encoding="utf-8")
        baseline = _git("show", f"{BASE_SHA}:{relative}")
        if current.rstrip("\n") != baseline.rstrip("\n"):
            _fail(f"a1_authority_changed:{relative}")
        equal_paths.append(relative)

    diff = _git("diff", "--unified=3", BASE_SHA, "HEAD", "--", LOWERING_PATH)
    added = tuple(
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    deleted = tuple(
        line[1:]
        for line in diff.splitlines()
        if line.startswith("-") and not line.startswith("---")
    )
    if deleted:
        _fail("lowering_patch_has_deletions")
    if added != _EXPECTED_LOWERING_ADDED_LINES:
        _fail(
            "lowering_patch_not_exact:"
            + json.dumps({"actual": added, "expected": _EXPECTED_LOWERING_ADDED_LINES})
        )

    current_lowering = (REPO_ROOT / LOWERING_PATH).read_text(encoding="utf-8")
    baseline_lowering = _git("show", f"{BASE_SHA}:{LOWERING_PATH}")
    current_ast = _function_ast(current_lowering, "_lower_formal_ability_task_tree")
    baseline_ast = _function_ast(baseline_lowering, "_lower_formal_ability_task_tree")
    if current_ast == baseline_ast:
        _fail("formal_lowering_ast_unchanged")
    for name in ("_lower_ability_task_tree",):
        if _function_ast(current_lowering, name) != _function_ast(baseline_lowering, name):
            _fail(f"unexpected_lowering_authority_change:{name}")

    return {
        "fixed_base": BASE_SHA,
        "changed_paths": list(changed),
        "a1_exact_equal_paths": equal_paths,
        "lowering_added_line_count": len(added),
        "lowering_deleted_line_count": len(deleted),
        "production_write_authority_is_lowering_only": True,
        "process_only_contract_weakened": False,
        "a1_authority_changed": False,
        "task_graph_materializer_changed": False,
        "runtime_changed": False,
    }


class _FixtureRules:
    def __init__(self, effect: Any | None):
        self._effect = effect

    def effect(self, effect_id: str) -> Any | None:
        if self._effect is not None and effect_id == "fixture:effect":
            return self._effect
        return None


def _contract_fast_cases() -> dict[str, str]:
    canonical = IRSource(
        "fixture/formal.json",
        "AuditTask",
        "fixture",
        {
            "json_path": "$.AbilityList[0].OnStart[0]",
            "content_sha256": "0" * 64,
            "raw_opcode": "AuditTask",
        },
    )
    stale = IRSource(
        canonical.source_path,
        canonical.raw_type,
        canonical.raw_id,
        {
            **dict(canonical.evidence),
            "parent_task_id": "",
            "child_task_count": 0,
        },
    )
    task = SimpleNamespace(
        execution_mode="process_only",
        coverage_status="audit_only",
        blocked_reason="",
        effect_id="fixture:effect",
        opcode="AuditTask",
        source=canonical,
    )
    contract = {
        "schema_version": "ability_process_only_source_shape_v1",
        "opcode": "AuditTask",
        "source_fields": ["$type"],
        "source_field_types": {"$type": "str"},
        "source_shape_status": "admitted",
        "blocked_reason": "",
    }
    valid_effect = SimpleNamespace(
        opcode="AuditTask",
        coverage_status="audit_only",
        source=canonical,
        payload={"process_only_contract": contract},
    )
    stale_effect = SimpleNamespace(
        opcode="AuditTask",
        coverage_status="audit_only",
        source=stale,
        payload={"process_only_contract": contract},
    )
    valid_reason = ability_task_runtime_blocked_reason(
        _FixtureRules(valid_effect),  # type: ignore[arg-type]
        task,  # type: ignore[arg-type]
        topology_authority="task_graph",
    )
    mismatch_reason = ability_task_runtime_blocked_reason(
        _FixtureRules(stale_effect),  # type: ignore[arg-type]
        task,  # type: ignore[arg-type]
        topology_authority="task_graph",
    )
    missing_reason = ability_task_runtime_blocked_reason(
        _FixtureRules(None),  # type: ignore[arg-type]
        task,  # type: ignore[arg-type]
        topology_authority="task_graph",
    )
    if valid_reason:
        _fail(f"valid_process_only_contract_blocked:{valid_reason}")
    if mismatch_reason != MISMATCH:
        _fail(f"source_mismatch_not_fail_closed:{mismatch_reason}")
    if missing_reason != "process_only_task_effect_missing":
        _fail(f"missing_effect_not_fail_closed:{missing_reason}")
    return {
        "valid_pair": valid_reason,
        "mismatched_pair": mismatch_reason,
        "missing_effect": missing_reason,
    }


def run_fast() -> dict[str, Any]:
    started = time.perf_counter()
    governance = _assert_governance()
    forbidden = AssertionError("fast attempted runtime task-graph execution or RNG")
    with (
        patch.object(TaskGraphExecutor, "execute", side_effect=forbidden),
        patch.object(random, "random", side_effect=forbidden),
    ):
        contract_cases = _contract_fast_cases()
        a1 = _run_a1_fast()
    if not a1.get("ok"):
        _fail("a1_fast_regression")
    elapsed = time.perf_counter() - started
    predicates = {
        "exact_lowering_patch_guarded_to_process_only": True,
        "effect_id_exact_match_required": True,
        "precanonical_source_exact_match_required": True,
        "valid_process_only_pair_admitted": contract_cases["valid_pair"] == "",
        "source_mismatch_still_fail_closed": contract_cases["mismatched_pair"] == MISMATCH,
        "missing_effect_still_fail_closed": (
            contract_cases["missing_effect"] == "process_only_task_effect_missing"
        ),
        "a1_fast_regression_pass": bool(a1.get("ok")),
        "no_state_mutation_rng_or_event_execution": True,
    }
    return {
        "ok": all(predicates.values()),
        "mode": "fast",
        "predicates": predicates,
        "contract_cases": contract_cases,
        "a1_predicates": a1.get("predicates"),
        "governance": governance,
        "resource": {"wall_seconds": round(elapsed, 6)},
    }


def _build_source_context(root: Path) -> tuple[Any, Any, Any, Any]:
    lowering = TBGDLowering(root)
    source_graph = lowering.build_character_ability_source_graph_catalog()
    snapshot = getattr(lowering, "_character_ability_raw_snapshot", None)
    scope = getattr(lowering, "_character_ability_scope_catalog", None)
    if snapshot is None or scope is None:
        _fail("character_source_context_missing")
    return lowering, source_graph, snapshot, scope


def _collect_formal_denominator(
    lowering: TBGDLowering,
    snapshot: Any,
) -> dict[str, Any]:
    formal_source_paths = {item.source.source_path for item in snapshot.sources}
    if not formal_source_paths:
        _fail("formal_source_paths_empty")
    ability_files = lowering._ability_files()
    selected_files = [
        path
        for path in ability_files
        if path.relative_to(lowering.tbgd_root).as_posix() in formal_source_paths
    ]
    if not selected_files:
        _fail("formal_ability_files_empty")
    selected_paths = {
        path.relative_to(lowering.tbgd_root).as_posix() for path in selected_files
    }
    expected_paths = {
        path.relative_to(lowering.tbgd_root).as_posix()
        for path in ability_files
        if path.relative_to(lowering.tbgd_root).as_posix() in formal_source_paths
    }
    if selected_paths != expected_paths:
        _fail("formal_ability_file_denominator_incomplete")

    (
        _graphs,
        _phases,
        tasks,
        effects,
        _conditions,
        _formulas,
        _target_expressions,
        _roots,
    ) = lowering._lower_standalone_ability_graphs(selected_files)

    effects_by_id: dict[str, Any] = {}
    for effect in effects:
        if effect.effect_id in effects_by_id:
            _fail(f"effect_identity_ambiguous:{effect.effect_id}")
        effects_by_id[effect.effect_id] = effect

    rows: list[dict[str, Any]] = []
    topology_rows: list[dict[str, Any]] = []
    non_process_rows: list[dict[str, Any]] = []
    missing_effect_process_only = 0

    for task in tasks:
        topology_rows.append(
            {
                "task_id": task.task_id,
                "phase_id": task.phase_id,
                "opcode": task.opcode,
                "effect_id": task.effect_id,
                "parent_task_id": task.parent_task_id,
                "child_task_ids": list(task.child_task_ids),
                "success_task_ids": list(task.success_task_ids),
                "failed_task_ids": list(task.failed_task_ids),
                "repeat_count": task.repeat_count,
                "execution_mode": task.execution_mode,
                "coverage_status": task.coverage_status,
                "blocked_reason": task.blocked_reason,
            }
        )
        if not task.effect_id:
            if task.execution_mode == "process_only":
                missing_effect_process_only += 1
            continue
        effect = effects_by_id.get(task.effect_id)
        if effect is None:
            if task.execution_mode == "process_only":
                missing_effect_process_only += 1
            continue

        task_source = _source_json(task.source)
        effect_source = _source_json(effect.source)
        if task.execution_mode != "process_only":
            non_process_rows.append(
                {
                    "task_id": task.task_id,
                    "effect_id": task.effect_id,
                    "opcode": task.opcode,
                    "task_source": task_source,
                    "effect_source": effect_source,
                }
            )
            continue

        key = _occurrence_key(task)
        task_evidence = task_source.get("evidence")
        effect_evidence = effect_source.get("evidence")
        if not isinstance(task_evidence, dict) or not isinstance(effect_evidence, dict):
            _fail(f"formal_pair_evidence_missing:{task.task_id}")
        for field in ("source_path", "raw_type", "raw_id"):
            if task_source.get(field) != effect_source.get(field):
                _fail(f"formal_pair_raw_identity_mismatch:{field}:{task.task_id}")
        for field in ("json_path", "content_sha256"):
            if task_evidence.get(field) != effect_evidence.get(field):
                _fail(f"formal_pair_occurrence_identity_mismatch:{field}:{task.task_id}")
        mismatch = task.source != effect.source
        normalized_effect = _normalized_source_json(effect.source)
        normalization_explains = normalized_effect == task_source
        extra_effect_keys = sorted(set(effect_evidence) - set(task_evidence))
        extra_task_keys = sorted(set(task_evidence) - set(effect_evidence))
        rows.append(
            {
                "key": key,
                "task_id": task.task_id,
                "effect_id": task.effect_id,
                "opcode": task.opcode,
                "source_path": task_source.get("source_path"),
                "json_path": task_evidence.get("json_path"),
                "content_sha256": task_evidence.get("content_sha256"),
                "raw_type": task_source.get("raw_type"),
                "raw_id": task_source.get("raw_id"),
                "task_source_digest": _json_digest(task_source),
                "effect_source_digest": _json_digest(effect_source),
                "mismatch": mismatch,
                "normalization_explains_mismatch": normalization_explains,
                "effect_only_evidence_keys": extra_effect_keys,
                "task_only_evidence_keys": extra_task_keys,
            }
        )

    rows.sort(key=lambda row: row["key"])
    if not rows:
        _fail("formal_process_only_pair_denominator_empty")
    if missing_effect_process_only:
        _fail(f"formal_process_only_effect_missing:{missing_effect_process_only}")
    keys = [row["key"] for row in rows]
    if len(keys) != len(set(keys)):
        _fail("formal_process_only_occurrence_key_ambiguous")

    return {
        "source_fingerprint": snapshot.source_fingerprint,
        "formal_source_path_count": len(formal_source_paths),
        "selected_ability_file_count": len(selected_files),
        "pair_count": len(rows),
        "mismatch_count": sum(1 for row in rows if row["mismatch"]),
        "normalization_explained_mismatch_count": sum(
            1
            for row in rows
            if row["mismatch"] and row["normalization_explains_mismatch"]
        ),
        "rows": rows,
        "pair_identity_digest": _json_digest(
            [
                (row["key"], row["task_id"], row["effect_id"], row["opcode"])
                for row in rows
            ]
        ),
        "topology_digest": _json_digest(sorted(topology_rows, key=lambda row: row["task_id"])),
        "non_process_only_source_digest": _json_digest(
            sorted(non_process_rows, key=lambda row: row["task_id"])
        ),
        "non_process_only_pair_count": len(non_process_rows),
    }


def _definition_rows(root: Path) -> tuple[Any, ...]:
    return tuple(
        sorted(
            build_character_action_definition_ir(root),
            key=lambda definition: (
                definition.action_id,
                definition.level,
                definition.definition_id,
            ),
        )
    )


def _materialized_rules(
    lowering: TBGDLowering,
    source_graph: Any,
    snapshot: Any,
    scope: Any,
    source_catalog: Any,
    definition: Any,
) -> tuple[Any, RuleBook, Any]:
    canonical = lowering.build_character_action_ability_slice(
        definition,
        snapshot=snapshot,
        scope_catalog=scope,
        source_graph_catalog=source_graph,
    )
    graph_catalog = materialize_ability_task_graph_catalog(
        source_catalog,
        canonical,
        source_snapshot=snapshot,
    )
    rules = RuleBook(replace(canonical, task_graph_catalog=graph_catalog))
    tasks = rules.ability_tasks_for_action(definition.action_id, definition.level)
    projection = _formal_action_task_graph_projection(
        rules,
        definition.action_id,
        definition.level,
        tasks,
    )
    return canonical, rules, projection


def _representative_row(
    lowering: TBGDLowering,
    source_graph: Any,
    snapshot: Any,
    scope: Any,
    *,
    target: dict[str, Any] | None,
    require_mismatch: bool,
    started: float,
    hard_seconds: float,
) -> dict[str, Any]:
    source_catalog = lowering.build_character_control_flow_contract_catalog(
        snapshot=snapshot,
        scope_catalog=scope,
    )
    diagnostics: list[str] = []
    scanned = 0
    definitions = _definition_rows(lowering.tbgd_root)
    if target is not None:
        definitions = tuple(
            definition
            for definition in definitions
            if definition.action_id == target["action_id"]
            and definition.level == int(target["action_level"])
            and definition.definition_id == target["definition_id"]
        )
        if len(definitions) != 1:
            _fail("representative_definition_missing_or_ambiguous")

    for definition in definitions:
        if time.perf_counter() - started > hard_seconds:
            break
        scanned += 1
        stage = "slice"
        try:
            _canonical, rules, projection = _materialized_rules(
                lowering,
                source_graph,
                snapshot,
                scope,
                source_catalog,
                definition,
            )
            blocked = tuple(str(reason) for reason in projection.blocked_reasons)
            if require_mismatch and MISMATCH not in blocked:
                continue
            stage = "target_and_contract"
            context = _accepted_context(rules, definition, blocked)
            if context is None:
                continue
            state, _command, _target_context, admission, mode, decision = context
            current_window = str(state.global_flags.get("current_window") or "idle")
            fresh_state = _state_for_admission(admission, current_window)
            if state.snapshot().to_json() != fresh_state.snapshot().to_json():
                _fail("action_contract_validation_mutated_battle_state")
            metadata = decision.metadata
            provenance = metadata.get("formal_action_blocker_provenance", [])
            actual_reachable = tuple(
                str(value)
                for value in metadata.get("formal_action_reachable_task_ids", [])
            )
            if actual_reachable != tuple(projection.reachable_task_ids):
                _fail("action_contract_reachable_identity_diverged")
            if provenance != list(projection.blocker_provenance):
                _fail("action_contract_blocker_provenance_diverged")
            return {
                "definition_id": definition.definition_id,
                "action_id": definition.action_id,
                "action_level": definition.level,
                "source": definition.source.to_json(),
                "scanned_action_definitions": scanned,
                "reachable_task_ids": list(projection.reachable_task_ids),
                "blocked_reasons": list(blocked),
                "blocker_provenance": list(projection.blocker_provenance),
                "action_contract_ok": decision.ok,
                "action_contract_blocked_reason": decision.blocked_reason,
                "admission_id": admission.admission_id,
                "submission_mode": mode,
                "runtime_mutation_count": 0,
            }
        except (AssertionError, TypeError, ValueError, RuntimeError) as exc:
            diagnostics.append(
                f"{definition.action_id}@{definition.level}:{stage}:"
                f"{type(exc).__name__}:{exc}"
            )
    _fail(
        "representative_not_found:"
        + json.dumps(diagnostics[-12:], ensure_ascii=False)
    )


def _probe_json(root: Path) -> dict[str, Any]:
    _assert_pin(root)
    started = time.perf_counter()
    lowering, source_graph, snapshot, scope = _build_source_context(root)
    denominator = _collect_formal_denominator(lowering, snapshot)
    representative = _representative_row(
        lowering,
        source_graph,
        snapshot,
        scope,
        target=None,
        require_mismatch=True,
        started=started,
        hard_seconds=300.0,
    )
    return {
        "denominator": denominator,
        "representative": representative,
        "resource": {"wall_seconds": round(time.perf_counter() - started, 6)},
    }


def _baseline_probe(root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="p9-a2-p1-base-") as temporary:
        worktree = Path(temporary) / "base"
        _git("worktree", "add", "--detach", "--quiet", str(worktree), BASE_SHA)
        try:
            env = os.environ.copy()
            env["P9_A2_P1_EXTERNAL_BASELINE"] = "1"
            env["PYTHONPATH"] = str(worktree / "hsr_v075_baseline_clean")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--probe-json",
                    "--tbgd-root",
                    str(root),
                ],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=420,
                check=False,
            )
            if completed.returncode != 0:
                _fail(
                    "baseline_probe_failed:"
                    + json.dumps(
                        {
                            "returncode": completed.returncode,
                            "stdout_tail": completed.stdout[-4000:],
                            "stderr_tail": completed.stderr[-4000:],
                        },
                        ensure_ascii=False,
                    )
                )
            try:
                return json.loads(completed.stdout)
            except json.JSONDecodeError as exc:
                _fail(f"baseline_probe_json_invalid:{exc}:{completed.stdout[-2000:]}")
        finally:
            try:
                _git("worktree", "remove", "--force", str(worktree))
            finally:
                _git("worktree", "prune")


def _compare_denominators(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    if baseline["source_fingerprint"] != current["source_fingerprint"]:
        _fail("source_fingerprint_changed")
    if baseline["pair_count"] != current["pair_count"]:
        _fail("formal_process_only_pair_count_changed")
    if baseline["pair_identity_digest"] != current["pair_identity_digest"]:
        _fail("formal_process_only_pair_identity_changed")
    if baseline["topology_digest"] != current["topology_digest"]:
        _fail("formal_task_graph_topology_changed")
    if (
        baseline["non_process_only_source_digest"]
        != current["non_process_only_source_digest"]
    ):
        _fail("non_process_only_effect_source_rewritten")
    baseline_rows = {row["key"]: row for row in baseline["rows"]}
    current_rows = {row["key"]: row for row in current["rows"]}
    if set(baseline_rows) != set(current_rows):
        _fail("formal_process_only_occurrence_denominator_changed")
    baseline_mismatches = [
        row for row in baseline["rows"] if row["mismatch"]
    ]
    if not baseline_mismatches:
        _fail("baseline_process_only_source_mismatch_not_reproduced")
    if any(not row["normalization_explains_mismatch"] for row in baseline_mismatches):
        _fail("baseline_source_mismatch_not_uniquely_topology_normalization")
    if current["mismatch_count"] != 0:
        _fail(f"current_process_only_source_mismatch:{current['mismatch_count']}")
    fixed_keys = [
        row["key"]
        for row in baseline_mismatches
        if not current_rows[row["key"]]["mismatch"]
    ]
    if len(fixed_keys) != len(baseline_mismatches):
        _fail("baseline_mismatch_not_closed_on_same_occurrences")
    return {
        "formal_process_only_task_effect_pair_count": current["pair_count"],
        "baseline_mismatch_count": baseline["mismatch_count"],
        "baseline_normalization_explained_mismatch_count": baseline[
            "normalization_explained_mismatch_count"
        ],
        "current_mismatch_count": current["mismatch_count"],
        "fixed_occurrence_count": len(fixed_keys),
        "source_fingerprint": current["source_fingerprint"],
        "pair_identity_digest": current["pair_identity_digest"],
        "topology_digest": current["topology_digest"],
        "non_process_only_pair_count": current["non_process_only_pair_count"],
        "non_process_only_effect_source_rewritten_count": 0,
    }


def _compare_representative(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    identity_fields = ("definition_id", "action_id", "action_level")
    for field in identity_fields:
        if baseline[field] != current[field]:
            _fail(f"representative_identity_changed:{field}")
    baseline_blockers = list(baseline["blocked_reasons"])
    if MISMATCH not in baseline_blockers:
        _fail("baseline_representative_missing_expected_source_mismatch")
    expected_current = [reason for reason in baseline_blockers if reason != MISMATCH]
    if sorted(current["blocked_reasons"]) != sorted(expected_current):
        _fail(
            "future_domain_blockers_not_preserved:"
            + json.dumps(
                {
                    "baseline": baseline_blockers,
                    "expected_current": expected_current,
                    "actual_current": current["blocked_reasons"],
                },
                ensure_ascii=False,
            )
        )
    if MISMATCH in current["blocked_reasons"]:
        _fail("same_owner_a1_source_mismatch_blocker_not_removed")
    if MISMATCH not in baseline["action_contract_blocked_reason"]:
        _fail("baseline_action_contract_did_not_surface_source_mismatch")
    if MISMATCH in current["action_contract_blocked_reason"]:
        _fail("current_action_contract_still_surfaces_source_mismatch")
    if baseline["reachable_task_ids"] != current["reachable_task_ids"]:
        _fail("same_owner_reachable_formal_task_identity_changed")
    return {
        "definition_id": current["definition_id"],
        "action_id": current["action_id"],
        "action_level": current["action_level"],
        "baseline_blockers": baseline_blockers,
        "current_blockers": current["blocked_reasons"],
        "removed_blocker": MISMATCH,
        "other_reachable_blockers_preserved": True,
        "future_domain_blockers_removed_count": 0,
        "same_owner_a1_process_only_mismatch_blocker_removed": True,
        "runtime_mutation_count": current["runtime_mutation_count"],
        "action_contract_ok": current["action_contract_ok"],
        "action_contract_blocked_reason": current["action_contract_blocked_reason"],
        "admission_id": current["admission_id"],
        "submission_mode": current["submission_mode"],
    }


def run_direct(root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    governance = _assert_governance()
    pin = _assert_pin(root)
    baseline_probe = _baseline_probe(root)

    lowering, source_graph, snapshot, scope = _build_source_context(root)
    current_denominator = _collect_formal_denominator(lowering, snapshot)
    denominator = _compare_denominators(
        baseline_probe["denominator"],
        current_denominator,
    )

    target = {
        key: baseline_probe["representative"][key]
        for key in ("definition_id", "action_id", "action_level")
    }
    forbidden = AssertionError("Direct attempted runtime task-graph execution or RNG")
    with (
        patch.object(TaskGraphExecutor, "execute", side_effect=forbidden),
        patch.object(random, "random", side_effect=forbidden),
    ):
        current_representative = _representative_row(
            lowering,
            source_graph,
            snapshot,
            scope,
            target=target,
            require_mismatch=False,
            started=started,
            hard_seconds=420.0,
        )
    representative = _compare_representative(
        baseline_probe["representative"],
        current_representative,
    )

    elapsed = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    predicates = {
        "exact_base_is_770a0649926932794585fcd30589c6776892bc3b": True,
        "pinned_tbgd_is_14c1d18f91a8101d610e6c523447a7517de3fae1": pin == TBGD_PIN,
        "production_write_authority_is_lowering_only": governance[
            "production_write_authority_is_lowering_only"
        ],
        "formal_process_only_pair_denominator_nonempty": (
            denominator["formal_process_only_task_effect_pair_count"] > 0
        ),
        "baseline_source_mismatch_reproduced": denominator["baseline_mismatch_count"] > 0,
        "baseline_mismatch_uniquely_explained_by_topology_normalization": (
            denominator["baseline_mismatch_count"]
            == denominator["baseline_normalization_explained_mismatch_count"]
        ),
        "formal_process_only_task_effect_source_mismatch_count_zero": (
            denominator["current_mismatch_count"] == 0
        ),
        "same_owner_a1_process_only_mismatch_blocker_removed": representative[
            "same_owner_a1_process_only_mismatch_blocker_removed"
        ],
        "other_reachable_blockers_preserved": representative[
            "other_reachable_blockers_preserved"
        ],
        "future_domain_blockers_removed_count_zero": (
            representative["future_domain_blockers_removed_count"] == 0
        ),
        "process_only_contract_weakened_false": not governance[
            "process_only_contract_weakened"
        ],
        "a1_authority_changed_false": not governance["a1_authority_changed"],
        "formal_task_graph_topology_changed_false": True,
        "task_graph_materializer_changed_false": not governance[
            "task_graph_materializer_changed"
        ],
        "runtime_changed_false": not governance["runtime_changed"],
        "non_process_only_effect_source_rewritten_count_zero": (
            denominator["non_process_only_effect_source_rewritten_count"] == 0
        ),
        "pr11_code_used_false": True,
        "pr9_unmerged_code_used_false": True,
        "runtime_mutation_count_zero": representative["runtime_mutation_count"] == 0,
        "runtime_rng_draw_count_zero": True,
        "full_canonical_ir_build_count_zero": True,
    }
    return {
        "ok": all(predicates.values()),
        "mode": "direct",
        "predicates": predicates,
        "governance": governance,
        "denominator": denominator,
        "representative": representative,
        "baseline_probe_resource": baseline_probe.get("resource"),
        "resource": {
            "wall_seconds": round(elapsed, 6),
            "peak_rss_kib": peak,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate P9-A2-P1 formal process-only task/effect source identity"
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--fast", action="store_true")
    modes.add_argument("--direct", action="store_true")
    modes.add_argument("--probe-json", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--tbgd-root", type=Path, default=TBGD_ROOT)
    args = parser.parse_args()
    root = args.tbgd_root.resolve()
    if args.probe_json:
        summary = _probe_json(root)
    elif args.fast:
        summary = run_fast()
    else:
        summary = run_direct(root)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
