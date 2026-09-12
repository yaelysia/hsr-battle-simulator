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
from hsr.simulator_v8_clean_core.systems.task_graph import (
    TaskGraphExecutionResult,
    TaskGraphExecutor,
)
from hsr.simulator_v8_clean_core.tbgd import (
    task_graph_materializer as task_graph_materializer,
)
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
_ZERO_CHANNEL_KEYS = (
    "mutation_count",
    "event_count",
    "rng_event_count",
    "settlement_record_count",
    "replay_mutation_count",
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


def _source_identity(source: Any) -> tuple[str, str, str]:
    evidence = source.evidence
    return (
        str(source.source_path),
        str(evidence.get("json_path") or ""),
        str(evidence.get("content_sha256") or ""),
    )


def _raw_family(raw: object) -> str:
    if not isinstance(raw, Mapping):
        return ""
    value = raw.get("$type")
    if not isinstance(value, str) or not value:
        return ""
    return value.rsplit(".", 1)[-1]


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


def _classify_formal_wait_occurrence(
    *,
    task: Any,
    phase: Any,
    effect: Any | None,
    graph: TaskGraphIR | None,
    node: Any | None,
    control: Any | None,
    raw: object,
    expected_content_sha256: str,
) -> dict[str, Any]:
    reasons: list[str] = []
    task_identity = _source_identity(task.source)
    source_path, json_path, task_content_sha = task_identity

    source_contract_reason = ""
    if not isinstance(raw, Mapping):
        reasons.append("raw_source_missing_or_not_object")
    else:
        if _raw_family(raw) != "WaitAnimState":
            reasons.append("raw_family_not_wait_anim_state")
        source_contract_reason = _process_only_ability_task_source_blocked_reason(
            dict(raw),
            "WaitAnimState",
        )
        if source_contract_reason:
            reasons.append("source_contract:" + source_contract_reason)

    if not source_path or not json_path.startswith("$"):
        reasons.append("task_source_identity_incomplete")
    if not expected_content_sha256 or len(expected_content_sha256) != 64:
        reasons.append("formal_source_content_fingerprint_missing")
    elif task_content_sha != expected_content_sha256:
        reasons.append("task_source_content_fingerprint_mismatch")

    if phase is None:
        reasons.append("formal_phase_owner_missing")
        invocation_role = ""
    else:
        invocation_role = str(phase.invocation_role)
        if phase.phase_id != task.phase_id:
            reasons.append("formal_phase_task_identity_mismatch")

    if task.execution_mode != "process_only":
        reasons.append("task_execution_mode_not_process_only")
    if task.coverage_status != "audit_only":
        reasons.append("task_coverage_not_audit_only")
    if task.blocked_reason:
        reasons.append("task_blocked:" + str(task.blocked_reason))
    if not task.effect_id:
        reasons.append("task_effect_identity_missing")

    if effect is None:
        reasons.append("audit_effect_missing")
    else:
        if not _process_contract_ok(effect, task):
            reasons.append("audit_effect_process_only_contract_invalid")
        if _source_identity(effect.source) != task_identity:
            reasons.append("effect_source_identity_mismatch")

    if graph is None or node is None:
        reasons.append("formal_task_graph_node_missing_or_ambiguous")
        graph_id = ""
        graph_node_id = ""
    else:
        graph_id = graph.graph_id
        graph_node_id = node.graph_node_id
        if (
            graph.entry_kind != "ability_phase_callback"
            or graph.owner_id != task.phase_id
            or graph.callback_kind != task.callback_kind
        ):
            reasons.append("formal_graph_owner_identity_mismatch")
        if node.formal_task_id != task.task_id:
            reasons.append("graph_node_formal_task_identity_mismatch")
        if node.source_family != "WaitAnimState":
            reasons.append("graph_node_family_not_wait_anim_state")
        if _source_identity(node.source) != task_identity:
            reasons.append("graph_node_source_identity_mismatch")
        if node.node_kind != "leaf":
            reasons.append("graph_node_not_leaf")
        if node.materialization_status != "materialized":
            reasons.append(
                "graph_node_not_materialized:"
                + str(node.status_reason or node.materialization_status)
            )
        if tuple(node.owner_domains) != ("task_graph_execution",):
            reasons.append("graph_node_owner_domains_not_execution_only")

    if control is None:
        reasons.append("control_node_missing")
        control_node_id = ""
        control_role = ""
        control_coverage_status = ""
        control_blocked_reason = ""
        branch_count = -1
        termination_kind = ""
        responsibility_count = 0
    else:
        control_node_id = control.node_id
        control_role = control.control_role
        control_coverage_status = control.coverage_status
        control_blocked_reason = control.blocked_reason
        branch_count = len(control.branches)
        termination_kind = control.termination.termination_kind
        responsibility_count = len(control.field_responsibilities)
        if (
            graph is not None
            and node is not None
            and node.source_contract_node_id != control.node_id
        ):
            reasons.append("graph_control_identity_mismatch")
        if control.family != "WaitAnimState":
            reasons.append("control_family_not_wait_anim_state")
        if control.control_role != "presentation_barrier":
            reasons.append("control_role_not_presentation_barrier")
        if control.blocked_reason:
            reasons.append("control_blocked:" + str(control.blocked_reason))
        if _source_identity(control.source) != task_identity:
            reasons.append("control_source_identity_mismatch")
        if any(
            item.responsibility != "presentation_excluded"
            or item.owner_stage != "excluded"
            for item in control.field_responsibilities
        ):
            reasons.append("control_has_non_presentation_responsibility")
        if control.branches:
            reasons.append("control_has_child_branch")
        if control.termination.termination_kind != "not_applicable":
            reasons.append("control_has_gameplay_termination")

    references: list[dict[str, Any]] = []
    if graph is not None and node is not None:
        references = [
            {
                "reference_kind": item.reference_kind,
                "definition_id": item.definition_id,
                "resolution_status": item.resolution_status,
                "blocked_reason": item.blocked_reason,
                "source_matches_task": item.source == task.source,
            }
            for item in node.references
        ]
        if (
            len(node.references) != 1
            or node.references[0].reference_kind != "effect"
            or node.references[0].definition_id != task.effect_id
            or node.references[0].resolution_status != "deferred"
            or node.references[0].blocked_reason != AUDIT_EFFECT_BLOCKER
            or node.references[0].source != task.source
        ):
            reasons.append("graph_audit_effect_reference_invalid")

    admitted = not reasons
    return {
        "action_id": task.action_id,
        "action_level": task.level,
        "ability_name": task.ability_name,
        "invocation_role": invocation_role,
        "task_id": task.task_id,
        "phase_id": task.phase_id,
        "callback_kind": task.callback_kind,
        "source_path": source_path,
        "json_path": json_path,
        "content_sha256": expected_content_sha256,
        "raw_family": _raw_family(raw),
        "source_contract_reason": source_contract_reason,
        "control_node_id": control_node_id,
        "control_role": control_role,
        "control_coverage_status": control_coverage_status,
        "control_blocked_reason": control_blocked_reason,
        "responsibility_count": responsibility_count,
        "branch_count": branch_count,
        "termination_kind": termination_kind,
        "effect_id": task.effect_id,
        "effect_present": effect is not None,
        "graph_id": graph_id,
        "graph_node_id": graph_node_id,
        "references": references,
        "admitted": admitted,
        "disposition": "admitted" if admitted else "blocked",
        "reason": "" if admitted else reasons[0],
        "reasons": reasons,
    }


def formal_wait_anim_denominator(root: Path) -> dict[str, Any]:
    lowerer, _source_graph, snapshot, scope = _build_context(root)
    source_catalog = lowerer.build_character_control_flow_contract_catalog(
        snapshot=snapshot,
        scope_catalog=scope,
    )
    controls = {item.node_id: item for item in source_catalog.nodes}
    formal_context = lowerer._character_formal_task_source_context()
    content_sha_by_path = formal_context.content_sha256_by_path

    canonical = lowerer.build()
    catalog = canonical.task_graph_catalog
    if type(catalog) is not TaskGraphCatalogIR:
        fail("formal_wait_anim_task_graph_catalog_missing")
    rules = RuleBook(canonical)

    phases = {phase.phase_id: phase for phase in canonical.ability_phases}
    tasks = {task.task_id: task for task in canonical.ability_tasks}
    if len(phases) != len(canonical.ability_phases):
        fail("formal_wait_anim_phase_identity_ambiguous")
    if len(tasks) != len(canonical.ability_tasks):
        fail("formal_wait_anim_task_identity_ambiguous")

    formal_task_ids: list[str] = []
    for entry in catalog.entry_materializations:
        if entry.entry_kind != "ability_phase_callback":
            continue
        formal_task_ids.extend(entry.formal_task_ids)
    if not formal_task_ids:
        fail("formal_ability_task_denominator_empty")
    if len(formal_task_ids) != len(set(formal_task_ids)):
        fail("formal_ability_task_denominator_identity_ambiguous")

    graph_nodes_by_task: dict[str, list[tuple[TaskGraphIR, Any]]] = {}
    for graph in catalog.graphs:
        if graph.entry_kind != "ability_phase_callback":
            continue
        for node in graph.nodes:
            graph_nodes_by_task.setdefault(node.formal_task_id, []).append((graph, node))

    rows: list[dict[str, Any]] = []
    wait_task_ids = [
        task_id
        for task_id in formal_task_ids
        if (task := tasks.get(task_id)) is not None
        and _family_for_task(task) == "WaitAnimState"
    ]
    if not wait_task_ids:
        fail("formal_wait_anim_denominator_empty")

    for task_id in wait_task_ids:
        task = tasks.get(task_id)
        if task is None:
            fail("formal_wait_anim_task_missing")
        phase = phases.get(task.phase_id)
        matches = graph_nodes_by_task.get(task.task_id, [])
        graph: TaskGraphIR | None = None
        node: Any | None = None
        if len(matches) == 1:
            graph, node = matches[0]
        effect = rules.effect(task.effect_id) if task.effect_id else None
        control = (
            controls.get(node.source_contract_node_id)
            if node is not None and node.source_contract_node_id
            else None
        )

        source_path = task.source.source_path
        json_path = str(task.source.evidence.get("json_path") or "")
        raw: object = None
        document = snapshot.documents.get(source_path)
        if document is not None:
            try:
                raw = _value_at_rooted_json_path(document, json_path)
            except (KeyError, IndexError, TypeError, ValueError):
                raw = None

        row = _classify_formal_wait_occurrence(
            task=task,
            phase=phase,
            effect=effect,
            graph=graph,
            node=node,
            control=control,
            raw=raw,
            expected_content_sha256=str(content_sha_by_path.get(source_path) or ""),
        )
        if len(matches) != 1:
            if "formal_task_graph_node_missing_or_ambiguous" not in row["reasons"]:
                row["reasons"].insert(0, "formal_task_graph_node_missing_or_ambiguous")
                row["reason"] = row["reasons"][0]
                row["admitted"] = False
                row["disposition"] = "blocked"
        rows.append(row)

    rows.sort(
        key=lambda item: (
            str(item["source_path"]),
            str(item["json_path"]),
            str(item["action_id"]),
            int(item["action_level"]),
            str(item["task_id"]),
        )
    )
    admitted = sum(bool(row["admitted"]) for row in rows)
    blocked = len(rows) - admitted
    blocked_reasons = Counter(
        str(row["reason"])
        for row in rows
        if not row["admitted"]
    )
    return {
        "kind": "formal_ability_wait_anim_state_occurrences",
        "formal_ability_entry_count": sum(
            entry.entry_kind == "ability_phase_callback"
            for entry in catalog.entry_materializations
        ),
        "formal_ability_task_count": len(formal_task_ids),
        "total": len(rows),
        "admitted": admitted,
        "blocked": blocked,
        "blocked_reason_counts": dict(sorted(blocked_reasons.items())),
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


def _sequence_len(value: object) -> int:
    return len(value) if isinstance(value, (list, tuple)) else 0


def _mapping_len(value: object) -> int:
    return len(value) if isinstance(value, Mapping) else 0


def _replay_state_entries(snapshot: Mapping[str, Any]) -> int:
    global_flags = snapshot.get("global_flags")
    if not isinstance(global_flags, Mapping):
        return 0
    count = 0
    for key, value in global_flags.items():
        if "replay" not in str(key).lower():
            continue
        if isinstance(value, Mapping):
            count += len(value)
        elif isinstance(value, (list, tuple)):
            count += len(value)
        elif value not in (None, "", False, 0):
            count += 1
    return count


def _state_channel_deltas(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> dict[str, int]:
    before_settlement = before.get("settlement")
    after_settlement = after.get("settlement")
    return {
        "pending_event_delta_count": (
            _sequence_len(after.get("pending_events"))
            - _sequence_len(before.get("pending_events"))
        ),
        "event_index_delta": int(after.get("event_index") or 0)
        - int(before.get("event_index") or 0),
        "rng_state_event_delta_count": (
            _sequence_len(after.get("rng_events"))
            - _sequence_len(before.get("rng_events"))
        ),
        "settlement_state_delta_count": (
            _mapping_len(after_settlement)
            - _mapping_len(before_settlement)
        ),
        "replay_state_delta_count": (
            _replay_state_entries(after)
            - _replay_state_entries(before)
        ),
    }


def _formal_channel_observation(
    *,
    execute_calls: int,
    condition_calls: int,
    rng_draw_calls: int,
    state_deltas: Mapping[str, int],
) -> dict[str, Any]:
    result_fields = set(TaskGraphExecutionResult.__dataclass_fields__)
    required = {"mutations", "events", "rng_events", "settlement_records"}
    if not required.issubset(result_fields):
        fail("task_graph_formal_channel_contract_changed")
    replay_fields = sorted(name for name in result_fields if "replay" in name.lower())
    if replay_fields:
        fail("task_graph_replay_channel_requires_explicit_observer")
    if execute_calls:
        fail("admission_attempted_runtime_graph_execution")
    if condition_calls:
        fail("admission_attempted_condition_evaluation")
    if rng_draw_calls:
        fail("admission_attempted_rng")
    if any(int(value) != 0 for value in state_deltas.values()):
        fail("action_admission_formal_channel_state_delta")
    return {
        "task_graph_execute_calls": execute_calls,
        "condition_evaluation_calls": condition_calls,
        "rng_draw_calls": rng_draw_calls,
        "mutation_count": 0,
        "event_count": 0,
        "rng_event_count": 0,
        "settlement_record_count": 0,
        "replay_mutation_count": 0,
        "replay_runtime_channel_defined": False,
        "state_deltas": dict(state_deltas),
    }


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
            catalog = task_graph_materializer.materialize_ability_task_graph_catalog(
                source_catalog,
                canonical,
                source_snapshot=snapshot,
            )
            canonical_with_graph = replace(canonical, task_graph_catalog=catalog)
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
                tuple(str(value) for value in projection.blocked_reasons),
            )
            if accepted is None or accepted[4] != "external_turn":
                continue
            state, _, _, admission, mode, decision = accepted
            window = str(state.global_flags.get("current_window") or "idle")
            expected_state = _state_for_admission(admission, window)
            before_snapshot = expected_state.snapshot().to_json()
            after_snapshot = state.snapshot().to_json()
            if after_snapshot != before_snapshot:
                fail("action_contract_mutated_state")
            provenance = _enriched_provenance(rules, projection)
            hit_random = _hit_random_rows(provenance)
            counts = Counter(str(row.get("family") or "") for row in hit_random)
            if (
                require_baseline_shape
                and counts != Counter({"WaitAnimState": 2, "FireProjectile": 1})
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
                "wait_anim_nodes": _formal_wait_nodes(rules, projection),
                "root_graph_ids": list(projection.root_graph_ids),
                "reachable_task_ids": list(projection.reachable_task_ids),
                "excluded_bound_task_ids": list(projection.excluded_bound_task_ids),
                "source_fingerprint": snapshot.source_fingerprint,
                "source_catalog_id": source_catalog.catalog_id,
                "s8c_sibling_signature": _s8c_sibling_signature(source_catalog),
                "scanned_action_definitions": scanned,
                "state_unchanged": True,
                "state_channel_deltas": _state_channel_deltas(
                    before_snapshot,
                    after_snapshot,
                ),
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
            {"scanned": scanned, "diagnostics": diagnostics[-10:]},
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
        side_effect=AssertionError("admission attempted runtime graph execution"),
    ) as execute_mock, patch.object(
        RuleEvaluator,
        "evaluate_condition_result",
        side_effect=AssertionError("admission attempted condition evaluation"),
    ) as condition_mock, patch.object(
        random,
        "random",
        side_effect=AssertionError("admission attempted RNG"),
    ) as rng_mock:
        row = representative(
            root,
            target=target,
            require_baseline_shape=target is None,
            started=started,
        )
    row["formal_channels"] = _formal_channel_observation(
        execute_calls=execute_mock.call_count,
        condition_calls=condition_mock.call_count,
        rng_draw_calls=rng_mock.call_count,
        state_deltas=row.pop("state_channel_deltas"),
    )
    return {
        "representative": row,
        "resource": {
            "wall_seconds": round(time.perf_counter() - started, 6),
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
    }


def baseline_probe(root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="p9-a2-p3-wait-base-") as temp:
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
            git("worktree", "remove", "--force", str(worktree))
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
                    "lowered_with_obligation" if has_obligation else "lowered"
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
                fail(f"canonical_{label}_wrong_error:{exc}")
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
        fail("baseline_hit_random_provenance_changed:" + json.dumps(base_hit))
    if current_hit != {"FireProjectile": 1}:
        fail("current_hit_random_provenance_not_3_to_1:" + json.dumps(current_hit))
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
    if current["s8c_sibling_signature"] != base["s8c_sibling_signature"]:
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
        row for row in baseline_provenance if row not in removed_wait
    ]
    if (
        len(removed_wait) != 2
        or current["blocker_provenance"] != expected_current
    ):
        fail("non_wait_anim_provenance_changed")

    denominator = formal_wait_anim_denominator(root)
    if (
        denominator["total"] <= 0
        or denominator["admitted"] <= 0
        or denominator["total"]
        != denominator["admitted"] + denominator["blocked"]
    ):
        fail("formal_wait_anim_denominator_not_proven")
    if any(
        bool(row["admitted"]) != (not row["reasons"])
        for row in denominator["rows"]
    ):
        fail("formal_wait_anim_denominator_disposition_inconsistent")
    representative_task_ids = {row["task_id"] for row in current_wait.values()}
    denominator_task_ids = {row["task_id"] for row in denominator["rows"]}
    if not representative_task_ids.issubset(denominator_task_ids):
        fail("representative_wait_anim_missing_from_formal_denominator")

    channels = current["formal_channels"]
    if any(int(channels[key]) != 0 for key in _ZERO_CHANNEL_KEYS):
        fail("zero_gameplay_formal_channels_not_zero")
    if (
        channels["task_graph_execute_calls"]
        or channels["condition_evaluation_calls"]
        or channels["rng_draw_calls"]
        or any(int(value) != 0 for value in channels["state_deltas"].values())
    ):
        fail("zero_gameplay_runtime_boundary_not_preserved")

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
        "formal_wait_anim_denominator_nonempty": bool(denominator["total"]),
        "formal_wait_anim_denominator_admitted_nonempty": bool(
            denominator["admitted"]
        ),
        "formal_wait_anim_denominator_complete": (
            denominator["total"]
            == denominator["admitted"] + denominator["blocked"]
        ),
        "action_admission_state_unchanged": True,
        "formal_mutation_event_rng_settlement_replay_channels_zero": True,
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
        "formal_wait_anim_denominator": denominator,
        "formal_channel_counts": channels,
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
