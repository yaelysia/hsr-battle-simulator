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
BASE_SHA = "4beebe293f74e37e709d5cfc978f098d1e804128"
TBGD_PIN = "14c1d18f91a8101d610e6c523447a7517de3fae1"
FAMILY = "SetEntityVisible"
COVERAGE = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/coverage.py"
LOWERING = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py"
TEST = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_p9_a2_p4_set_entity_visible_process_only_retirement.py"
VALIDATOR = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p4_set_entity_visible_process_only_retirement.py"
REPORT = "hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2-P4_SET_ENTITY_VISIBLE_PROCESS_ONLY_RETIREMENT_execution_report.md"
WORKFLOW = ".github/workflows/p9-a2-p4-pr-validation.yml"
CARD = "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-A2-P4_SET_ENTITY_VISIBLE_PROCESS_ONLY_RETIREMENT.md"
ALLOWED = {COVERAGE, LOWERING, TEST, VALIDATOR, REPORT, WORKFLOW, CARD}
READ_ONLY = (
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/character_ability_scope.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/character_control_flow_contracts.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/ir.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability_task_contract.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/task_graph.py",
    "hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/core/executor.py",
)
SET_UNSUPPORTED = "effect_coverage_status:unsupported:SetEntityVisible"
UNSUPPORTED_DEFINITION = "task_graph_definition_not_admitted:effect:unsupported"
DAMAGE_HEAL_SHIELD = "task_graph_control_requires_domains:damage_heal_shield"
HIT_RANDOM = "task_graph_control_requires_domains:hit_random_sequence"

if os.environ.get("P9_A2_P4_EXTERNAL_BASELINE") != "1":
    sys.path.insert(0, str(BASELINE))

from hsr.simulator_v8_clean_core.rules.evaluator import RuleEvaluator
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.rules.task_graph import TaskGraphIR
from hsr.simulator_v8_clean_core.systems.action_contract import (
    _formal_action_task_graph_projection,
)
from hsr.simulator_v8_clean_core.systems.task_graph import TaskGraphExecutor
from hsr.simulator_v8_clean_core.tbgd.coverage import ability_task_execution_mode
from hsr.simulator_v8_clean_core.tbgd.lowering import (
    _process_only_ability_task_source_blocked_reason,
    _value_at_rooted_json_path,
)
from hsr.simulator_v8_clean_core.tbgd.task_graph_materializer import (
    materialize_ability_task_graph_catalog,
)
from hsr.simulator_v8_clean_core.tools.validate_p9_a2_p1_formal_process_only_source_identity import (
    _accepted_context,
    _build_context,
    _definitions,
    _state_for_admission,
)
from hsr.simulator_v8_clean_core.tools.validate_p9_a2_p3_wait_anim_state_process_only_barrier_retirement import (
    AUDIT_EFFECT_BLOCKER,
    _FormalTaskGraphViewBuilder,
    _enriched_provenance,
    _family_for_task,
    _process_contract_ok,
    _source_identity,
    _state_channel_deltas,
)


def fail(message: str) -> None:
    raise AssertionError(message)


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=cwd,
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()


def assert_pin(root: Path) -> str:
    actual = git("rev-parse", "HEAD", cwd=root)
    if actual != TBGD_PIN:
        fail(f"tbgd_pin_mismatch:{actual}")
    return actual


def governance() -> dict[str, Any]:
    if git("merge-base", BASE_SHA, "HEAD") != BASE_SHA:
        fail("fixed_base_not_ancestor")
    changed = tuple(
        row
        for row in git("diff", "--name-only", BASE_SHA, "HEAD").splitlines()
        if row
    )
    extra = sorted(set(changed) - ALLOWED)
    if extra:
        fail("scope_leak:" + ",".join(extra))
    production = tuple(
        row
        for row in changed
        if row.startswith("hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/")
        and "/tools/" not in row
        and "/tests/" not in row
        and "/docs/" not in row
    )
    if set(production) != {COVERAGE, LOWERING}:
        fail("production_authority_changed:" + ",".join(production))
    for path in READ_ONLY:
        current = (ROOT / path).read_text(encoding="utf-8").rstrip("\n")
        baseline = git("show", f"{BASE_SHA}:{path}").rstrip("\n")
        if current != baseline:
            fail("read_only_authority_changed:" + path)
    coverage_diff = git("diff", "--unified=0", BASE_SHA, "HEAD", "--", COVERAGE)
    lowering_diff = git("diff", "--unified=0", BASE_SHA, "HEAD", "--", LOWERING)
    if coverage_diff.count('+        "SetEntityVisible",') != 1:
        fail("coverage_patch_shape_invalid")
    for token in (
        '+    "SetEntityVisible": {"TargetType": "mapping", "UniqueKey": "string", "Visible": "bool"},',
        '+    if opcode == "SetEntityVisible":',
        '+        return ""',
    ):
        if lowering_diff.count(token) != 1:
            fail("lowering_patch_shape_invalid:" + token)
    deleted = [
        line
        for diff in (coverage_diff, lowering_diff)
        for line in diff.splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]
    if deleted:
        fail("production_patch_deleted_lines")
    return {
        "fixed_base": BASE_SHA,
        "changed_paths": list(changed),
        "production_paths": list(production),
        "read_only_authorities_unchanged": True,
    }


def _raw_family(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    raw_type = value.get("$type")
    if not isinstance(raw_type, str):
        return ""
    return raw_type.rsplit(".", 1)[-1]


def _object_json_path(record: Any) -> str:
    path = str(record.source.evidence.get("json_path") or "")
    return path[:-6] if path.endswith(".$type") else path


def _field_type(value: object) -> str:
    if type(value) is bool:
        return "bool"
    if isinstance(value, Mapping):
        return "mapping"
    if isinstance(value, list):
        return "list"
    return type(value).__name__


def formal_denominator(root: Path) -> dict[str, Any]:
    view = _FormalTaskGraphViewBuilder(root)
    scope_view = view.scope.for_families((FAMILY,))
    records = tuple(
        record
        for record in scope_view.scope_records
        if record.family == FAMILY and record.materialization_role == "selected"
    )
    if not records:
        fail("set_entity_visible_source_scope_denominator_empty")
    bad_scope = [
        {
            "source_path": record.source.source_path,
            "json_path": str(record.source.evidence.get("json_path") or ""),
            "semantic_kind": record.semantic_kind,
            "effective_scope": record.effective_scope,
        }
        for record in records
        if record.semantic_kind != "presentation_only"
        or record.effective_scope != "non_gameplay"
    ]
    if bad_scope:
        fail("set_entity_visible_non_presentation_scope:" + json.dumps(bad_scope[:8]))

    canonical = view.build()
    graph_catalog = materialize_ability_task_graph_catalog(
        view.source_catalog,
        canonical,
        source_snapshot=view.snapshot,
    )
    rules = RuleBook(replace(canonical, task_graph_catalog=graph_catalog))
    tasks = tuple(
        task for task in canonical.ability_tasks if _family_for_task(task) == FAMILY
    )
    if not tasks:
        fail("set_entity_visible_formal_task_denominator_empty")
    task_groups: dict[tuple[str, str], list[Any]] = {}
    for task in tasks:
        key = (
            str(task.source.source_path),
            str(task.source.evidence.get("json_path") or ""),
        )
        task_groups.setdefault(key, []).append(task)

    record_keys = [
        (str(record.source.source_path), _object_json_path(record)) for record in records
    ]
    if len(record_keys) != len(set(record_keys)):
        fail("set_entity_visible_scope_occurrence_identity_ambiguous")

    field_sets: Counter[tuple[str, ...]] = Counter()
    field_types: Counter[tuple[tuple[str, str], ...]] = Counter()
    blocked_reasons: Counter[str] = Counter()
    admitted = 0
    blocked = 0
    task_count = 0
    graph_node_count = 0
    sample: dict[str, Any] | None = None

    for record in records:
        source_path = str(record.source.source_path)
        json_path = _object_json_path(record)
        reasons: list[str] = []
        document = view.formal_context.documents.get(source_path)
        raw: object = None
        if document is not None and json_path.startswith("$"):
            try:
                raw = _value_at_rooted_json_path(document, json_path)
            except (KeyError, IndexError, TypeError, ValueError):
                raw = None
        if not isinstance(raw, Mapping):
            reasons.append("raw_source_missing")
        else:
            if _raw_family(raw) != FAMILY:
                reasons.append("raw_family_mismatch")
            source_reason = _process_only_ability_task_source_blocked_reason(
                dict(raw), FAMILY
            )
            if source_reason:
                reasons.append("source_contract:" + source_reason)
            field_sets[tuple(sorted(str(key) for key in raw))] += 1
            field_types[
                tuple(sorted((str(key), _field_type(value)) for key, value in raw.items()))
            ] += 1

        expected_sha = str(
            view.formal_context.content_sha256_by_path.get(source_path) or ""
        )
        if len(expected_sha) != 64:
            reasons.append("source_content_fingerprint_missing")
        matching_tasks = tuple(task_groups.get((source_path, json_path), ()))
        if not matching_tasks:
            reasons.append("formal_task_missing")

        for task in matching_tasks:
            task_count += 1
            if task.execution_mode != "process_only":
                reasons.append("task_execution_mode_not_process_only")
            if task.coverage_status != "audit_only" or task.blocked_reason:
                reasons.append("task_not_admitted_audit_only")
            if _source_identity(task.source) != (source_path, json_path, expected_sha):
                reasons.append("task_source_identity_mismatch")
            effect = rules.effect(task.effect_id) if task.effect_id else None
            if effect is None:
                reasons.append("audit_effect_missing")
            else:
                if not _process_contract_ok(effect, task):
                    reasons.append("audit_effect_process_only_contract_invalid")
                if effect.source != task.source:
                    reasons.append("audit_effect_source_mismatch")
                if effect.effect_id != task.effect_id or effect.opcode != FAMILY:
                    reasons.append("audit_effect_identity_mismatch")

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
                reasons.append("formal_task_graph_missing")
                continue
            nodes = tuple(
                node for node in graph.nodes if node.formal_task_id == task.task_id
            )
            if len(nodes) != 1:
                reasons.append("formal_task_graph_node_missing_or_ambiguous")
                continue
            node = nodes[0]
            graph_node_count += 1
            if node.node_kind != "leaf" or node.materialization_status != "materialized":
                reasons.append("formal_task_graph_node_not_materialized_leaf")
            if _source_identity(node.source) != (source_path, json_path, expected_sha):
                reasons.append("formal_task_graph_node_source_mismatch")
            if len(node.references) != 1:
                reasons.append("formal_task_graph_effect_reference_count_invalid")
            else:
                reference = node.references[0]
                if (
                    reference.reference_kind != "effect"
                    or reference.definition_id != task.effect_id
                    or reference.source != task.source
                    or reference.resolution_status != "deferred"
                    or reference.blocked_reason != AUDIT_EFFECT_BLOCKER
                ):
                    reasons.append("formal_task_graph_audit_reference_invalid")

        reasons = list(dict.fromkeys(reasons))
        if reasons:
            blocked += 1
            blocked_reasons[reasons[0]] += 1
        else:
            admitted += 1
        if sample is None:
            sample = {
                "source_path": source_path,
                "json_path": json_path,
                "content_sha256": expected_sha,
                "task_count": len(matching_tasks),
                "admitted": not reasons,
                "reasons": reasons,
            }

    if admitted + blocked != len(records):
        fail("set_entity_visible_denominator_count_mismatch")
    return {
        "kind": "formal_source_scope_set_entity_visible_occurrences",
        "total": len(records),
        "admitted": admitted,
        "blocked": blocked,
        "blocked_reason_counts": dict(sorted(blocked_reasons.items())),
        "source_file_count": len({record.source.source_path for record in records}),
        "formal_task_count": task_count,
        "formal_graph_node_count": graph_node_count,
        "field_sets": {str(key): value for key, value in sorted(field_sets.items())},
        "field_types": {str(key): value for key, value in sorted(field_types.items())},
        "source_fingerprint": view.snapshot.source_fingerprint,
        "sample": sample or {},
    }


def _set_specific(row: Mapping[str, Any]) -> bool:
    return str(row.get("family") or "") == FAMILY and str(row.get("reason") or "") in {
        SET_UNSUPPORTED,
        UNSUPPORTED_DEFINITION,
    }


def representative(
    root: Path,
    *,
    target: Mapping[str, Any] | None,
    require_set_blocker: bool,
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
    scanned = 0
    diagnostics: list[str] = []
    for definition in definitions:
        if not definition.action_id.startswith("avatar_skill:"):
            continue
        scanned += 1
        try:
            canonical = lowerer.build_character_action_ability_slice(
                definition,
                snapshot=snapshot,
                scope_catalog=scope,
                source_graph_catalog=source_graph,
            )
            catalog = materialize_ability_task_graph_catalog(
                source_catalog,
                canonical,
                source_snapshot=snapshot,
            )
            rules = RuleBook(replace(canonical, task_graph_catalog=catalog))
            tasks = rules.ability_tasks_for_action(definition.action_id, definition.level)
            projection = _formal_action_task_graph_projection(
                rules,
                definition.action_id,
                definition.level,
                tasks,
            )
            accepted = _accepted_context(
                rules,
                definition,
                tuple(str(value) for value in projection.blocked_reasons),
            )
            if accepted is None or accepted[4] != "external_turn":
                continue
            state, _command, _target_context, admission, mode, decision = accepted
            window = str(state.global_flags.get("current_window") or "idle")
            expected_state = _state_for_admission(admission, window)
            before = expected_state.snapshot().to_json()
            after = state.snapshot().to_json()
            if before != after:
                fail("action_contract_mutated_state")
            provenance = _enriched_provenance(rules, projection)
            set_rows = [row for row in provenance if _set_specific(row)]
            has_effect = any(row.get("reason") == SET_UNSUPPORTED for row in set_rows)
            has_definition = any(
                row.get("reason") == UNSUPPORTED_DEFINITION for row in set_rows
            )
            if require_set_blocker and not (has_effect and has_definition):
                continue
            wait_hit_random = [
                row
                for row in provenance
                if row.get("family") == "WaitAnimState"
                and row.get("reason") == HIT_RANDOM
            ]
            return {
                "definition_id": definition.definition_id,
                "action_id": definition.action_id,
                "action_level": definition.level,
                "source": definition.source.to_json(),
                "admission_id": admission.admission_id,
                "submission_mode": mode,
                "current_window": window,
                "action_contract_ok": decision.ok,
                "action_contract_blocked_reason": decision.blocked_reason,
                "blocked_reasons": list(projection.blocked_reasons),
                "blocker_provenance": provenance,
                "set_entity_visible_rows": set_rows,
                "wait_anim_hit_random_rows": wait_hit_random,
                "reachable_task_ids": list(projection.reachable_task_ids),
                "state_unchanged": True,
                "state_channel_deltas": _state_channel_deltas(before, after),
                "source_fingerprint": snapshot.source_fingerprint,
                "source_catalog_id": source_catalog.catalog_id,
                "scanned_action_definitions": scanned,
            }
        except (AssertionError, TypeError, ValueError, RuntimeError) as exc:
            diagnostics.append(
                f"{definition.action_id}@{definition.level}:{type(exc).__name__}:{exc}"
            )
            if target is not None:
                raise
    fail(
        "same_owner_outer_action_not_found:"
        + json.dumps({"scanned": scanned, "diagnostics": diagnostics[-12:]})
    )


def probe(root: Path, *, target: Mapping[str, Any] | None = None) -> dict[str, Any]:
    assert_pin(root)
    with patch.object(
        TaskGraphExecutor,
        "execute",
        side_effect=AssertionError("runtime task graph execution forbidden"),
    ) as execute_mock, patch.object(
        RuleEvaluator,
        "evaluate_condition_result",
        side_effect=AssertionError("condition evaluation forbidden"),
    ) as condition_mock, patch.object(
        random,
        "random",
        side_effect=AssertionError("gameplay RNG forbidden"),
    ) as rng_mock:
        row = representative(
            root,
            target=target,
            require_set_blocker=target is None,
        )
    if execute_mock.call_count or condition_mock.call_count or rng_mock.call_count:
        fail("runtime_boundary_called")
    if any(int(value) != 0 for value in row["state_channel_deltas"].values()):
        fail("formal_channel_state_delta")
    return {
        "representative": row,
        "formal_channels": {
            "task_graph_execute_calls": execute_mock.call_count,
            "condition_evaluation_calls": condition_mock.call_count,
            "rng_draw_calls": rng_mock.call_count,
            "mutation_count": 0,
            "event_count": 0,
            "settlement_record_count": 0,
            "replay_mutation_count": 0,
        },
    }


def baseline_probe(root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="p9-a2-p4-base-") as temp:
        worktree = Path(temp) / "base"
        git("worktree", "add", "--detach", "--quiet", str(worktree), BASE_SHA)
        try:
            env = os.environ.copy()
            env["P9_A2_P4_EXTERNAL_BASELINE"] = "1"
            env["P9_A2_P3_EXTERNAL_BASELINE"] = "1"
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
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=240,
                check=False,
            )
            if completed.returncode:
                fail(
                    "baseline_probe_failed:"
                    + json.dumps(
                        {
                            "returncode": completed.returncode,
                            "stdout_tail": completed.stdout[-4000:],
                            "stderr_tail": completed.stderr[-4000:],
                        }
                    )
                )
            return json.loads(completed.stdout)
        finally:
            git("worktree", "remove", "--force", str(worktree))
            git("worktree", "prune")


def compare_representative(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
) -> dict[str, Any]:
    base = baseline["representative"]
    cur = current["representative"]
    for field in ("definition_id", "action_id", "action_level"):
        if base[field] != cur[field]:
            fail("representative_identity_changed:" + field)
    base_set = list(base["set_entity_visible_rows"])
    cur_set = list(cur["set_entity_visible_rows"])
    if not base_set:
        fail("baseline_set_entity_visible_provenance_missing")
    if cur_set:
        fail("current_set_entity_visible_unsupported_provenance_remaining")
    if base["wait_anim_hit_random_rows"] or cur["wait_anim_hit_random_rows"]:
        fail("p3_wait_anim_hit_random_regressed")
    base_other = [row for row in base["blocker_provenance"] if not _set_specific(row)]
    cur_other = [row for row in cur["blocker_provenance"] if not _set_specific(row)]
    if base_other != cur_other:
        fail("non_p4_blocker_provenance_changed")
    if DAMAGE_HEAL_SHIELD not in cur["blocked_reasons"]:
        fail("s11_damage_heal_shield_blocker_not_preserved")
    if not cur["blocked_reasons"]:
        fail("outer_action_unexpectedly_executable")
    return {
        "definition_id": cur["definition_id"],
        "action_id": cur["action_id"],
        "action_level": cur["action_level"],
        "current_window": cur["current_window"],
        "baseline_set_entity_visible_rows": base_set,
        "current_set_entity_visible_rows": cur_set,
        "other_blocker_provenance_preserved": True,
        "p3_wait_anim_hit_random_rows": cur["wait_anim_hit_random_rows"],
        "s11_damage_heal_shield_preserved": True,
        "current_blocked_reasons": cur["blocked_reasons"],
        "action_contract_ok": cur["action_contract_ok"],
    }


def run_direct(root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    gov = governance()
    pin = assert_pin(root)
    baseline = baseline_probe(root)
    target = {
        key: baseline["representative"][key]
        for key in ("definition_id", "action_id", "action_level")
    }
    current = probe(root, target=target)
    delta = compare_representative(baseline, current)
    if ability_task_execution_mode(FAMILY) != "process_only":
        fail("set_entity_visible_execution_mode_not_process_only")
    if ability_task_execution_mode("SetEntityForceVisible") != "runtime_effect":
        fail("set_entity_force_visible_sibling_mode_changed")

    with patch.object(
        TaskGraphExecutor,
        "execute",
        side_effect=AssertionError("denominator runtime task graph execution forbidden"),
    ) as execute_mock, patch.object(
        RuleEvaluator,
        "evaluate_condition_result",
        side_effect=AssertionError("denominator condition evaluation forbidden"),
    ) as condition_mock, patch.object(
        random,
        "random",
        side_effect=AssertionError("denominator gameplay RNG forbidden"),
    ) as rng_mock:
        denominator = formal_denominator(root)
    if execute_mock.call_count or condition_mock.call_count or rng_mock.call_count:
        fail("denominator_runtime_boundary_called")
    if denominator["blocked"]:
        fail(
            "set_entity_visible_denominator_not_fully_admitted:"
            + json.dumps(denominator["blocked_reason_counts"])
        )
    if denominator["total"] != denominator["admitted"]:
        fail("set_entity_visible_denominator_incomplete")

    elapsed = time.perf_counter() - started
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    predicates = {
        "fixed_base": gov["fixed_base"] == BASE_SHA,
        "pinned_tbgd": pin == TBGD_PIN,
        "source_scope_denominator_nonempty": denominator["total"] > 0,
        "source_scope_denominator_fully_admitted": denominator["blocked"] == 0,
        "source_scope_presentation_only": True,
        "process_only_task_effect_identity_closed": denominator["formal_task_count"] > 0,
        "formal_task_graph_leaf_identity_closed": denominator["formal_graph_node_count"] > 0,
        "set_entity_visible_unsupported_provenance_removed": not delta[
            "current_set_entity_visible_rows"
        ],
        "p3_wait_anim_no_regression": not delta["p3_wait_anim_hit_random_rows"],
        "s11_damage_heal_shield_preserved": delta[
            "s11_damage_heal_shield_preserved"
        ],
        "other_blockers_preserved": delta["other_blocker_provenance_preserved"],
        "set_entity_force_visible_sibling_unchanged": ability_task_execution_mode(
            "SetEntityForceVisible"
        )
        == "runtime_effect",
        "runtime_execution_condition_rng_zero": True,
        "read_only_authorities_unchanged": gov["read_only_authorities_unchanged"],
    }
    return {
        "ok": elapsed < 420 and peak < 3 * 1024 * 1024 and all(predicates.values()),
        "mode": "direct",
        "predicates": predicates,
        "governance": gov,
        "formal_set_entity_visible_denominator": denominator,
        "baseline_representative": baseline["representative"],
        "current_representative": current["representative"],
        "provenance_delta": delta,
        "formal_channels": current["formal_channels"],
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
    args = parser.parse_args()
    root = args.tbgd_root.resolve()
    if args.probe_json:
        print(json.dumps(probe(root), ensure_ascii=False, sort_keys=True))
        return 0
    if not args.direct:
        fail("--direct is required")
    result = run_direct(root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
