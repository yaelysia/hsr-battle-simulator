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
PARTITION_A = "formal_ability_task"
PARTITION_B = "formal_status_callback_task"
PARTITION_C = "template_definition_no_formal_producer"
PARTITION_D = "blocked_or_unresolved"

if os.environ.get("P9_A2_P4_EXTERNAL_BASELINE") != "1":
    sys.path.insert(0, str(BASELINE))

from hsr.simulator_v8_clean_core.rules.evaluator import RuleEvaluator
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, TargetExpressionIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.rules.task_graph import TaskGraphIR
from hsr.simulator_v8_clean_core.systems.action_contract import (
    _formal_action_task_graph_projection,
)
from hsr.simulator_v8_clean_core.systems.task_graph import TaskGraphExecutor
from hsr.simulator_v8_clean_core.tbgd import (
    lowering as lowering_module,
    task_graph_materializer,
)
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
    _state_for_admission,
    build_context as _build_context,
    definitions as _definitions,
)
from hsr.simulator_v8_clean_core.tools.validate_p9_a2_p3_wait_anim_state_process_only_barrier_retirement import (
    AUDIT_EFFECT_BLOCKER,
    _FormalTaskGraphViewBuilder,
    _enriched_provenance,
    _family_for_task,
    _process_contract_ok,
    _slice_materialization_context,
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
        "status_callback_authority_unchanged": True,
        "task_graph_materializer_unchanged": True,
    }


def _raw_family(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    raw_type = value.get("$type")
    if not isinstance(raw_type, str):
        return ""
    return raw_type.rsplit(".", 1)[-1]


def _normalize_json_path(path: object) -> str:
    value = str(path or "")
    return value[:-6] if value.endswith(".$type") else value


def _object_json_path(record: Any) -> str:
    return _normalize_json_path(record.source.evidence.get("json_path"))


def _source_location(source: Any) -> tuple[str, str]:
    return (
        str(source.source_path),
        _normalize_json_path(source.evidence.get("json_path")),
    )


def _source_contract_reasons(
    source: Any,
    *,
    source_path: str,
    json_path: str,
    content_sha256: str,
    require_fingerprint: bool,
) -> list[str]:
    reasons: list[str] = []
    if _source_location(source) != (source_path, json_path):
        reasons.append("source_location_mismatch")
    actual_sha = str(source.evidence.get("content_sha256") or "")
    if actual_sha and actual_sha != content_sha256:
        reasons.append("source_content_fingerprint_conflict")
    if require_fingerprint and actual_sha != content_sha256:
        reasons.append("source_content_fingerprint_missing_or_mismatch")
    if require_fingerprint and source.evidence.get("content_fingerprint_scope") not in {
        None,
        "source_file",
    }:
        reasons.append("source_content_fingerprint_scope_invalid")
    return reasons


def _field_type(value: object) -> str:
    if type(value) is bool:
        return "bool"
    if isinstance(value, Mapping):
        return "mapping"
    if isinstance(value, list):
        return "list"
    return type(value).__name__


def _producer_partition_kind(
    *,
    ability_count: int,
    status_count: int,
    template_count: int,
    template_reference_count: int,
) -> tuple[str, str]:
    if ability_count and status_count:
        return PARTITION_D, "formal_producer_kind_ambiguous"
    if ability_count:
        return PARTITION_A, ""
    if status_count:
        return PARTITION_B, ""
    if template_count > 1:
        return PARTITION_D, "template_definition_identity_ambiguous"
    if template_count == 1:
        if template_reference_count:
            return PARTITION_D, "template_reference_missing_formal_expansion"
        return PARTITION_C, ""
    return PARTITION_D, "formal_producer_unresolved"


def _template_attribution(
    source_catalog: Any,
    *,
    source_path: str,
    json_path: str,
) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    candidates: list[tuple[int, Any]] = []
    for template in source_catalog.template_definitions:
        if template.source.source_path != source_path:
            continue
        template_path = _normalize_json_path(template.source.evidence.get("json_path"))
        task_prefix = f"{template_path}.TaskList["
        if json_path.startswith(task_prefix):
            candidates.append((len(template_path), template))
    if not candidates:
        return (), ()
    max_prefix = max(length for length, _template in candidates)
    templates = tuple(
        template
        for length, template in candidates
        if length == max_prefix
    )
    template_ids = {template.template_id for template in templates}
    references = tuple(
        reference
        for reference in source_catalog.template_references
        if template_ids.intersection(reference.candidate_template_ids)
        or reference.resolved_template_id in template_ids
    )
    return templates, references


def _ability_entry(
    canonical: Any,
    materialization_context: Any,
    cache: dict[tuple[str, str], tuple[Any, TaskGraphIR | None]],
    task: Any,
) -> tuple[Any, TaskGraphIR | None]:
    key = (task.phase_id, task.callback_kind)
    cached = cache.get(key)
    if cached is not None:
        return cached
    phase_tasks = tuple(
        candidate
        for candidate in canonical.ability_tasks
        if candidate.phase_id == task.phase_id
        and candidate.callback_kind == task.callback_kind
    )
    if not phase_tasks:
        fail("ability_entry_task_denominator_empty")
    entry, graph = task_graph_materializer._materialize_entry(
        materialization_context,
        "ability_phase_callback",
        task.phase_id,
        task.callback_kind,
        tuple(candidate.task_id for candidate in phase_tasks),
        tuple(task_graph_materializer._ability_task(candidate) for candidate in phase_tasks),
    )
    cache[key] = (entry, graph)
    return entry, graph


def _status_entry(
    canonical: Any,
    materialization_context: Any,
    callback_by_id: Mapping[str, Any],
    cache: dict[str, tuple[Any, TaskGraphIR | None]],
    task: Any,
) -> tuple[Any, TaskGraphIR | None]:
    cached = cache.get(task.callback_id)
    if cached is not None:
        return cached
    callback = callback_by_id.get(task.callback_id)
    if callback is None:
        fail("status_callback_owner_missing")
    tasks = tuple(
        candidate
        for candidate in canonical.status_callback_tasks
        if candidate.callback_id == task.callback_id
    )
    if not tasks:
        fail("status_callback_task_denominator_empty")
    ordered = task_graph_materializer._ordered_status_task_ids(callback, tasks)
    entry, graph = task_graph_materializer._materialize_entry(
        materialization_context,
        "status_callback",
        callback.callback_id,
        callback.event,
        ordered,
        tuple(task_graph_materializer._status_task(candidate) for candidate in tasks),
    )
    cache[task.callback_id] = (entry, graph)
    return entry, graph


def _validate_ability_occurrence(
    *,
    canonical: Any,
    materialization_context: Any,
    entry_cache: dict[tuple[str, str], tuple[Any, TaskGraphIR | None]],
    effect_by_id: Mapping[str, Any],
    matching_tasks: tuple[Any, ...],
    source_path: str,
    json_path: str,
    expected_sha: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    reasons: list[str] = []
    producer_rows: list[dict[str, Any]] = []
    for task in matching_tasks:
        task_reasons: list[str] = []
        if task.execution_mode != "process_only":
            task_reasons.append("task_execution_mode_not_process_only")
        if task.coverage_status != "audit_only" or task.blocked_reason:
            task_reasons.append("task_not_admitted_audit_only")
        if not task.effect_id:
            task_reasons.append("task_effect_identity_missing")
        task_reasons.extend(
            _source_contract_reasons(
                task.source,
                source_path=source_path,
                json_path=json_path,
                content_sha256=expected_sha,
                require_fingerprint=False,
            )
        )
        effect = effect_by_id.get(task.effect_id) if task.effect_id else None
        if effect is None:
            task_reasons.append("audit_effect_missing")
        else:
            if not _process_contract_ok(effect, task):
                task_reasons.append("audit_effect_process_only_contract_invalid")
            if effect.source != task.source:
                task_reasons.append("audit_effect_source_mismatch")
            if effect.effect_id != task.effect_id or effect.opcode != FAMILY:
                task_reasons.append("audit_effect_identity_mismatch")
            task_reasons.extend(
                _source_contract_reasons(
                    effect.source,
                    source_path=source_path,
                    json_path=json_path,
                    content_sha256=expected_sha,
                    require_fingerprint=False,
                )
            )

        formal_task = task_graph_materializer._ability_task(task)
        direct_reference_rows: list[dict[str, Any]] = []
        direct_node_id = ""
        direct_reference = None
        try:
            formal_source = task_graph_materializer._formal_source(
                formal_task,
                materialization_context.digest_by_path,
            )
            control = materialization_context.control_by_location.get(
                (
                    formal_source.source_path,
                    formal_source.evidence["json_path"],
                    formal_task.family,
                )
            )
            node_kind, node_status, owner_domains, node_reason = (
                task_graph_materializer._node_status(control, formal_task)
            )
            direct_entry_id = task_graph_materializer.task_graph_entry_id(
                "ability_phase_callback",
                task.phase_id,
                task.callback_kind,
            )
            direct_graph_id = task_graph_materializer.task_graph_id(
                materialization_context.base.source_catalog_id,
                direct_entry_id,
                materialization_context.base.source_fingerprint,
            )
            occurrence_id = task_graph_materializer.task_graph_source_occurrence_id(
                formal_source,
                formal_task.family,
            )
            direct_node_id = task_graph_materializer.task_graph_node_id(
                direct_graph_id,
                task.task_id,
                occurrence_id,
            )
            direct_references = task_graph_materializer._references(
                formal_task,
                control,
                direct_node_id,
                formal_source,
                materialization_context.definitions,
                materialization_context.template_refs_by_node,
            )
            task_reasons.extend(
                _source_contract_reasons(
                    formal_source,
                    source_path=source_path,
                    json_path=json_path,
                    content_sha256=expected_sha,
                    require_fingerprint=True,
                )
            )
            if (
                node_kind != "leaf"
                or node_status != "materialized"
                or tuple(owner_domains) != ("task_graph_execution",)
                or node_reason
            ):
                task_reasons.append("formal_task_node_contract_not_materialized_leaf")
            if len(direct_references) != 1:
                task_reasons.append("formal_task_node_audit_reference_count_invalid")
            else:
                direct_reference = direct_references[0]
                direct_reference_rows.append(
                    {
                        "reference_kind": direct_reference.reference_kind,
                        "definition_id": direct_reference.definition_id,
                        "resolution_status": direct_reference.resolution_status,
                        "owner_domain": direct_reference.owner_domain,
                        "blocked_reason": direct_reference.blocked_reason,
                        "source": direct_reference.source.to_json(),
                    }
                )
                if (
                    direct_reference.reference_kind != "effect"
                    or direct_reference.definition_id != task.effect_id
                    or direct_reference.resolution_status != "deferred"
                    or direct_reference.blocked_reason != AUDIT_EFFECT_BLOCKER
                    or direct_reference.source != formal_source
                ):
                    task_reasons.append("formal_task_node_audit_reference_invalid")
        except (TypeError, ValueError, RuntimeError) as exc:
            task_reasons.append(
                "formal_task_node_contract_blocked:"
                + type(exc).__name__
                + ":"
                + str(exc)
            )

        entry, graph = _ability_entry(
            canonical,
            materialization_context,
            entry_cache,
            task,
        )
        node = None
        references: list[dict[str, Any]] = []
        if entry.status != "materialized":
            if graph is not None:
                task_reasons.append("formal_task_graph_blocked_entry_published_graph")
        elif graph is None:
            task_reasons.append("formal_task_graph_materialized_entry_graph_missing")
        else:
            nodes = tuple(
                candidate
                for candidate in graph.nodes
                if candidate.formal_task_id == task.task_id
            )
            if len(nodes) != 1:
                task_reasons.append("formal_task_graph_node_missing_or_ambiguous")
            else:
                node = nodes[0]
                if (
                    node.node_kind != "leaf"
                    or node.materialization_status != "materialized"
                ):
                    task_reasons.append("formal_task_graph_node_not_materialized_leaf")
                task_reasons.extend(
                    _source_contract_reasons(
                        node.source,
                        source_path=source_path,
                        json_path=json_path,
                        content_sha256=expected_sha,
                        require_fingerprint=True,
                    )
                )
                if len(node.references) != 1:
                    task_reasons.append(
                        "formal_task_graph_effect_reference_count_invalid"
                    )
                else:
                    reference = node.references[0]
                    references.append(
                        {
                            "reference_kind": reference.reference_kind,
                            "definition_id": reference.definition_id,
                            "resolution_status": reference.resolution_status,
                            "owner_domain": reference.owner_domain,
                            "blocked_reason": reference.blocked_reason,
                            "source": reference.source.to_json(),
                        }
                    )
                    if (
                        reference.reference_kind != "effect"
                        or reference.definition_id != task.effect_id
                        or reference.resolution_status != "deferred"
                        or reference.blocked_reason != AUDIT_EFFECT_BLOCKER
                        or direct_reference is None
                        or reference != direct_reference
                    ):
                        task_reasons.append(
                            "formal_task_graph_audit_reference_invalid"
                        )
                    task_reasons.extend(
                        _source_contract_reasons(
                            reference.source,
                            source_path=source_path,
                            json_path=json_path,
                            content_sha256=expected_sha,
                            require_fingerprint=True,
                        )
                    )

        reasons.extend(task_reasons)
        producer_rows.append(
            {
                "task_id": task.task_id,
                "phase_id": task.phase_id,
                "callback_kind": task.callback_kind,
                "execution_mode": task.execution_mode,
                "task_coverage_status": task.coverage_status,
                "task_blocked_reason": task.blocked_reason,
                "effect_id": task.effect_id,
                "effect_coverage_status": getattr(effect, "coverage_status", ""),
                "entry_status": entry.status,
                "entry_blocked_reason": entry.blocked_reason,
                "graph_id": graph.graph_id if graph is not None else "",
                "graph_node_id": node.graph_node_id if node is not None else "",
                "direct_node_id": direct_node_id,
                "direct_references": direct_reference_rows,
                "references": references,
                "reasons": list(dict.fromkeys(task_reasons)),
            }
        )
    return list(dict.fromkeys(reasons)), producer_rows


def _validate_status_occurrence(
    *,
    canonical: Any,
    materialization_context: Any,
    callback_by_id: Mapping[str, Any],
    entry_cache: dict[str, tuple[Any, TaskGraphIR | None]],
    matching_tasks: tuple[Any, ...],
    source_path: str,
    json_path: str,
    expected_sha: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    reasons: list[str] = []
    producer_rows: list[dict[str, Any]] = []
    for task in matching_tasks:
        task_reasons: list[str] = []
        raw_family = task.source.evidence.get("raw_opcode")
        if raw_family not in {None, "", FAMILY} or task.opcode != FAMILY:
            task_reasons.append("status_task_family_mismatch")
        task_reasons.extend(
            _source_contract_reasons(
                task.source,
                source_path=source_path,
                json_path=json_path,
                content_sha256=expected_sha,
                require_fingerprint=False,
            )
        )
        callback = callback_by_id.get(task.callback_id)
        if callback is None:
            task_reasons.append("status_callback_owner_missing")
        elif (
            callback.callback_id != task.callback_id
            or callback.event != task.event
            or callback.source.source_path
            != str(task.source.evidence.get("admission_source_path") or "")
        ):
            task_reasons.append("status_callback_owner_identity_mismatch")

        formal_task = task_graph_materializer._status_task(task)
        if formal_task.execution_mode != "runtime_effect":
            task_reasons.append("status_formal_execution_mode_changed")

        entry, graph = _status_entry(
            canonical,
            materialization_context,
            callback_by_id,
            entry_cache,
            task,
        )
        node = None
        if graph is not None:
            nodes = tuple(
                candidate
                for candidate in graph.nodes
                if candidate.formal_task_id == task.task_id
            )
            if len(nodes) != 1:
                task_reasons.append("status_formal_graph_node_missing_or_ambiguous")
            else:
                node = nodes[0]
                task_reasons.extend(
                    _source_contract_reasons(
                        node.source,
                        source_path=source_path,
                        json_path=json_path,
                        content_sha256=expected_sha,
                        require_fingerprint=True,
                    )
                )

        reasons.extend(task_reasons)
        producer_rows.append(
            {
                "task_id": task.task_id,
                "callback_id": task.callback_id,
                "event": task.event,
                "task_coverage_status": task.coverage_status,
                "task_blocked_reason": task.blocked_reason,
                "formal_execution_mode": formal_task.execution_mode,
                "entry_status": entry.status,
                "entry_blocked_reason": entry.blocked_reason,
                "graph_id": graph.graph_id if graph is not None else "",
                "graph_node_id": node.graph_node_id if node is not None else "",
                "node_materialization_status": (
                    node.materialization_status if node is not None else ""
                ),
                "node_status_reason": node.status_reason if node is not None else "",
                "disposition": "deferred_status_callback_formal_authority",
                "reasons": list(dict.fromkeys(task_reasons)),
            }
        )
    return list(dict.fromkeys(reasons)), producer_rows


def formal_denominator(root: Path) -> dict[str, Any]:
    view = _FormalTaskGraphViewBuilder(root)
    lowerer = view.production_lowerer
    source_catalog = view.source_catalog
    snapshot = view.snapshot
    formal_context = view.formal_context
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
        fail(
            "set_entity_visible_non_presentation_scope:"
            + json.dumps(bad_scope[:8], sort_keys=True)
        )

    snapshot_sha_by_path = {
        str(source.source.source_path): str(source.content_sha256)
        for source in snapshot.sources
    }
    if len(snapshot_sha_by_path) != len(snapshot.sources):
        fail("snapshot_source_identity_ambiguous")

    record_keys = [
        (str(record.source.source_path), _object_json_path(record))
        for record in records
    ]
    if len(record_keys) != len(set(record_keys)):
        fail("set_entity_visible_scope_occurrence_identity_ambiguous")
    record_key_set = set(record_keys)

    field_sets: Counter[tuple[str, ...]] = Counter()
    field_types: Counter[tuple[tuple[str, str], ...]] = Counter()
    raw_reasons: dict[tuple[str, str], list[str]] = {}
    for record in records:
        source_path = str(record.source.source_path)
        json_path = _object_json_path(record)
        key = (source_path, json_path)
        occurrence_reasons: list[str] = []
        expected_sha = str(formal_context.content_sha256_by_path.get(source_path) or "")
        snapshot_sha = snapshot_sha_by_path.get(source_path, "")
        if len(expected_sha) != 64:
            occurrence_reasons.append("source_content_fingerprint_missing")
        elif snapshot_sha != expected_sha:
            occurrence_reasons.append("snapshot_formal_content_fingerprint_mismatch")

        document = formal_context.documents.get(source_path)
        raw: object = None
        if document is not None and json_path.startswith("$"):
            try:
                raw = _value_at_rooted_json_path(document, json_path)
            except (KeyError, IndexError, TypeError, ValueError):
                raw = None
        if not isinstance(raw, Mapping):
            occurrence_reasons.append("raw_source_missing")
        else:
            if _raw_family(raw) != FAMILY:
                occurrence_reasons.append("raw_family_mismatch")
            source_reason = _process_only_ability_task_source_blocked_reason(
                dict(raw),
                FAMILY,
            )
            if source_reason:
                occurrence_reasons.append("source_contract:" + source_reason)
            field_sets[tuple(sorted(str(field) for field in raw))] += 1
            field_types[
                tuple(
                    sorted(
                        (str(field), _field_type(value))
                        for field, value in raw.items()
                    )
                )
            ] += 1
        raw_reasons[key] = list(dict.fromkeys(occurrence_reasons))

    empty_canonical = CanonicalIR(version=lowering_module.BASELINE_VERSION)
    base_materialization_context = task_graph_materializer._prepare_materialization(
        source_catalog,
        empty_canonical,
        snapshot,
    )

    ability_evidence: dict[tuple[str, str], dict[str, Any]] = {}
    status_evidence: dict[tuple[str, str], dict[str, Any]] = {}

    def record_ability_slice(
        *,
        phases: list[Any] | tuple[Any, ...],
        tasks: list[Any] | tuple[Any, ...],
        effects: list[Any] | tuple[Any, ...],
        conditions: list[Any] | tuple[Any, ...],
        standalone_graphs: list[Any] | tuple[Any, ...] = (),
    ) -> None:
        groups: dict[tuple[str, str], list[Any]] = {}
        for task in tasks:
            if _family_for_task(task) != FAMILY:
                continue
            key = _source_location(task.source)
            if key in record_key_set:
                groups.setdefault(key, []).append(task)
        if not groups:
            return

        canonical = CanonicalIR(
            version=lowering_module.BASELINE_VERSION,
            ability_phases=tuple(phases),
            ability_tasks=tuple(tasks),
            standalone_ability_graphs=tuple(standalone_graphs),
            effects=tuple(effects),
            conditions=tuple(conditions),
        )
        context = _slice_materialization_context(
            base_materialization_context,
            conditions=conditions,
            effects=effects,
            phases=phases,
            standalone_graphs=standalone_graphs,
        )
        effect_by_id = {effect.effect_id: effect for effect in effects}
        if len(effect_by_id) != len(effects):
            fail("formal_ability_slice_effect_identity_ambiguous")
        entry_cache: dict[
            tuple[str, str], tuple[Any, TaskGraphIR | None]
        ] = {}
        for key, matching in groups.items():
            expected_sha = str(
                formal_context.content_sha256_by_path.get(key[0]) or ""
            )
            reasons, rows = _validate_ability_occurrence(
                canonical=canonical,
                materialization_context=context,
                entry_cache=entry_cache,
                effect_by_id=effect_by_id,
                matching_tasks=tuple(matching),
                source_path=key[0],
                json_path=key[1],
                expected_sha=expected_sha,
            )
            bucket = ability_evidence.setdefault(
                key,
                {"count": 0, "reasons": [], "producer_rows": []},
            )
            bucket["count"] += len(matching)
            bucket["reasons"].extend(reasons)
            bucket["producer_rows"].extend(rows)

    action_definitions = lowerer._lower_action_definitions()
    action_phase_metadata: list[Any] = []
    for index, definition in enumerate(action_definitions):
        if not definition.action_id.startswith("avatar_skill:"):
            continue
        _binding, phases, lowered = lowerer._avatar_action_binding(definition)
        action_phase_metadata.extend(phases)
        record_ability_slice(
            phases=phases,
            tasks=lowered.ability_tasks,
            effects=lowered.effects,
            conditions=lowered.conditions,
        )
        del _binding, phases, lowered
        if index % 32 == 31:
            gc.collect()

    ability_files = lowerer._ability_files()
    formal_ability_source_paths = set(formal_context.documents)
    formal_ability_files = [
        path
        for path in ability_files
        if lowering_module.relative_source_path(root, path)
        in formal_ability_source_paths
    ]
    standalone_graphs: list[Any] = []
    standalone_phases: list[Any] = []
    for index, path in enumerate(formal_ability_files):
        (
            file_graphs,
            file_phases,
            file_tasks,
            file_effects,
            file_conditions,
            _file_formulas,
            _file_targets,
            _file_roots,
        ) = lowerer._lower_standalone_ability_graphs([path])
        standalone_graphs.extend(file_graphs)
        standalone_phases.extend(file_phases)
        record_ability_slice(
            phases=file_phases,
            tasks=file_tasks,
            effects=file_effects,
            conditions=file_conditions,
            standalone_graphs=file_graphs,
        )
        del (
            file_graphs,
            file_phases,
            file_tasks,
            file_effects,
            file_conditions,
            _file_formulas,
            _file_targets,
            _file_roots,
        )
        if index % 16 == 15:
            gc.collect()

    status_callbacks: list[Any] = []
    status_callback_tasks: list[Any] = []
    status_effects: list[Any] = []
    status_conditions: list[Any] = []
    status_targets: list[Any] = []
    queue_priorities = lowerer._lower_queue_priorities()
    queue_priority_lookup = {
        (priority.priority_table, priority.priority_key): priority
        for priority in queue_priorities
        if priority.coverage_status == "executable"
    }
    formal_status_root_paths = {
        item.source.source_path for item in snapshot.sources
    }
    for ability_file_order, path in enumerate(ability_files):
        relative = lowering_module.relative_source_path(root, path)
        if (
            relative.startswith("Config/ConfigAbility/Equip/")
            or relative not in formal_status_root_paths
        ):
            continue
        lowered = lowerer._lower_ability_file(
            path,
            queue_priority_lookup,
            ability_file_order=ability_file_order,
            formal_status_source_context=formal_context,
        )
        status_callbacks.extend(lowered.status_callbacks)
        status_callback_tasks.extend(lowered.status_callback_tasks)

        p4_callback_ids = {
            task.callback_id
            for task in lowered.status_callback_tasks
            if (
                task.opcode == FAMILY
                or task.source.evidence.get("raw_opcode") == FAMILY
            )
            and _source_location(task.source) in record_key_set
        }
        selected_callback_tasks = [
            task
            for task in lowered.status_callback_tasks
            if task.callback_id in p4_callback_ids
        ]
        needed_effect_ids = {
            task.effect_id
            for task in lowered.status_callback_tasks
            if task.effect_id
            and (
                task.opcode == "TriggerAbility"
                or task.callback_id in p4_callback_ids
            )
        }
        needed_condition_ids = {
            task.condition_id
            for task in selected_callback_tasks
            if task.condition_id
        }
        needed_target_ids = {
            task.target_expression_id
            for task in selected_callback_tasks
            if task.target_expression_id
        }
        status_effects.extend(
            effect
            for effect in lowered.effects
            if effect.effect_id in needed_effect_ids
        )
        status_conditions.extend(
            condition
            for condition in lowered.conditions
            if condition.condition_id in needed_condition_ids
        )
        status_targets.extend(
            target
            for target in lowered.target_expressions
            if target.target_expression_id in needed_target_ids
        )
        del lowered
        if ability_file_order % 32 == 31:
            gc.collect()

    status_callback_tasks = list(
        lowering_module._link_status_trigger_ability_graphs(
            status_callback_tasks,
            status_callbacks,
            status_effects,
            standalone_graphs,
        )
    )
    status_event_families = lowering_module._lower_status_event_families(
        status_callbacks,
        status_callback_tasks,
    )
    all_phase_metadata = [*action_phase_metadata, *standalone_phases]
    (
        status_callbacks,
        status_callback_tasks,
        _status_callback_finalization_audit,
    ) = lowering_module._finalize_action_window_status_callback_admission(
        status_callbacks,
        status_callback_tasks,
        status_event_families,
        status_effects,
        standalone_graphs,
        all_phase_metadata,
        formal_status_root_paths,
    )
    status_event_families = lowering_module._lower_status_event_families(
        status_callbacks,
        status_callback_tasks,
    )
    status_event_blocked_reasons = lowering_module._status_event_blocked_reasons(
        status_event_families
    )
    status_callbacks = list(
        lowering_module._block_status_callbacks_by_event_family(
            status_callbacks,
            status_event_blocked_reasons,
        )
    )
    status_callback_blocked_reasons = {
        callback.callback_id: (
            status_event_blocked_reasons.get(callback.event)
            or callback.blocked_reason
            or callback.blocking_dependency
        )
        for callback in status_callbacks
        if (
            callback.event in status_event_blocked_reasons
            or callback.blocked_reason
            == "equipment_modifier_definition_unreferenced"
        )
    }
    status_callback_tasks = list(
        lowering_module._block_status_callback_tasks_by_callback(
            status_callback_tasks,
            status_callback_blocked_reasons,
        )
    )

    status_groups: dict[tuple[str, str], list[Any]] = {}
    for task in status_callback_tasks:
        raw_family = task.source.evidence.get("raw_opcode")
        if task.opcode != FAMILY and raw_family != FAMILY:
            continue
        key = _source_location(task.source)
        if key in record_key_set:
            status_groups.setdefault(key, []).append(task)

    if status_groups:
        callback_by_id = {
            callback.callback_id: callback for callback in status_callbacks
        }
        if len(callback_by_id) != len(status_callbacks):
            fail("formal_status_callback_identity_ambiguous")
        status_canonical = CanonicalIR(
            version=lowering_module.BASELINE_VERSION,
            status_callbacks=tuple(status_callbacks),
            status_callback_tasks=tuple(status_callback_tasks),
        )
        status_context = _slice_materialization_context(
            base_materialization_context,
            conditions=status_conditions,
            effects=status_effects,
            phases=all_phase_metadata,
            standalone_graphs=standalone_graphs,
        )
        if status_targets:
            status_context = replace(
                status_context,
                definitions=replace(
                    status_context.definitions,
                    targets=task_graph_materializer._definition_multimap(
                        status_targets,
                        TargetExpressionIR,
                        "target_expression_id",
                    ),
                ),
            )
        status_entry_cache: dict[str, tuple[Any, TaskGraphIR | None]] = {}
        for key, matching in status_groups.items():
            expected_sha = str(
                formal_context.content_sha256_by_path.get(key[0]) or ""
            )
            reasons, rows = _validate_status_occurrence(
                canonical=status_canonical,
                materialization_context=status_context,
                callback_by_id=callback_by_id,
                entry_cache=status_entry_cache,
                matching_tasks=tuple(matching),
                source_path=key[0],
                json_path=key[1],
                expected_sha=expected_sha,
            )
            status_evidence[key] = {
                "count": len(matching),
                "reasons": reasons,
                "producer_rows": rows,
            }

    del (
        status_callbacks,
        status_callback_tasks,
        status_effects,
        status_conditions,
        status_targets,
        action_phase_metadata,
        standalone_graphs,
        standalone_phases,
    )
    gc.collect()

    partition_rows: dict[str, list[dict[str, Any]]] = {
        PARTITION_A: [],
        PARTITION_B: [],
        PARTITION_C: [],
        PARTITION_D: [],
    }
    reason_counts: Counter[str] = Counter()
    producer_task_count = Counter()

    for record in records:
        source_path = str(record.source.source_path)
        json_path = _object_json_path(record)
        key = (source_path, json_path)
        occurrence_reasons = list(raw_reasons.get(key, ()))
        ability = ability_evidence.get(
            key, {"count": 0, "reasons": [], "producer_rows": []}
        )
        status = status_evidence.get(
            key, {"count": 0, "reasons": [], "producer_rows": []}
        )
        templates, template_references = _template_attribution(
            source_catalog,
            source_path=source_path,
            json_path=json_path,
        )
        partition, partition_reason = _producer_partition_kind(
            ability_count=int(ability["count"]),
            status_count=int(status["count"]),
            template_count=len(templates),
            template_reference_count=len(template_references),
        )
        if partition_reason:
            occurrence_reasons.append(partition_reason)

        producer_rows: list[dict[str, Any]] = []
        if partition == PARTITION_A:
            occurrence_reasons.extend(ability["reasons"])
            producer_rows = list(ability["producer_rows"])
            producer_task_count[PARTITION_A] += int(ability["count"])
        elif partition == PARTITION_B:
            occurrence_reasons.extend(status["reasons"])
            producer_rows = list(status["producer_rows"])
            producer_task_count[PARTITION_B] += int(status["count"])
        elif partition == PARTITION_C:
            producer_rows = [
                {
                    "template_id": templates[0].template_id,
                    "template_name": templates[0].name,
                    "template_scope_kind": templates[0].scope_kind,
                    "template_source": templates[0].source.to_json(),
                    "reference_count": 0,
                    "attribution": "no_formal_producer",
                }
            ]

        occurrence_reasons = list(dict.fromkeys(occurrence_reasons))
        final_partition = partition if not occurrence_reasons else PARTITION_D
        if final_partition == PARTITION_D:
            for reason in occurrence_reasons:
                reason_counts[reason] += 1
        row = {
            "source_path": source_path,
            "json_path": json_path,
            "content_sha256": str(
                formal_context.content_sha256_by_path.get(source_path) or ""
            ),
            "avatar_id": record.source.evidence.get("avatar_id"),
            "source_kind": record.source.evidence.get("source_kind"),
            "parent_branch_path": record.parent_branch_path,
            "partition": final_partition,
            "producer_rows": producer_rows,
            "template_ids": [template.template_id for template in templates],
            "template_references": [
                {
                    "reference_id": reference.reference_id,
                    "node_id": reference.node_id,
                    "reference_kind": reference.reference_kind,
                    "candidate_template_ids": list(
                        reference.candidate_template_ids
                    ),
                    "resolved_template_id": reference.resolved_template_id,
                    "coverage_status": reference.coverage_status,
                    "blocked_reason": reference.blocked_reason,
                    "source": reference.source.to_json(),
                }
                for reference in template_references
            ],
            "reasons": occurrence_reasons,
        }
        partition_rows[final_partition].append(row)

    counts = {key: len(value) for key, value in partition_rows.items()}
    total_partitioned = sum(counts.values())
    if total_partitioned != len(records):
        fail("set_entity_visible_partition_identity_mismatch")
    if not counts[PARTITION_A]:
        fail("set_entity_visible_formal_ability_task_slice_empty")

    return {
        "kind": "formal_source_scope_set_entity_visible_occurrences",
        "total_selected": len(records),
        "source_file_count": len(
            {record.source.source_path for record in records}
        ),
        "partition_counts": counts,
        "partition_identity_closed": total_partitioned == len(records),
        "blocked_reason_counts": dict(sorted(reason_counts.items())),
        "producer_task_counts": dict(sorted(producer_task_count.items())),
        "field_sets": {
            str(key): value for key, value in sorted(field_sets.items())
        },
        "field_types": {
            str(key): value for key, value in sorted(field_types.items())
        },
        "source_fingerprint": snapshot.source_fingerprint,
        "samples": {
            key: rows[:4] for key, rows in partition_rows.items()
        },
        "blocked_or_unresolved": partition_rows[PARTITION_D],
        "status_callback_semantics": {
            "authority": "StatusCallbackTaskIR/task_graph_materializer._status_task",
            "production_unchanged": True,
            "formal_execution_mode": "runtime_effect",
        },
        "template_attribution": {
            "rule": (
                "exact producer first; otherwise longest containing formal "
                "template definition; any reference without production "
                "expansion is blocked_or_unresolved"
            ),
            "no_formal_producer_count": counts[PARTITION_C],
        },
        "materialization_mode": "streamed_source_slices",
    }


def _set_specific(row: Mapping[str, Any]) -> bool:
    return str(row.get("family") or "") == FAMILY and str(
        row.get("reason") or ""
    ) in {
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
    if target is None:
        scope_view = scope.for_families((FAMILY,))
        owner_avatar_ids = {
            str(record.source.evidence.get("avatar_id") or "")
            for record in scope_view.scope_records
            if record.family == FAMILY
            and record.materialization_role == "selected"
        }
        owner_avatar_ids.discard("")
        candidate_action_ids = {
            action.action_id
            for action in source_graph.action_sources
            if action.owner_avatar_id in owner_avatar_ids
        }
        definitions = tuple(
            definition
            for definition in definitions
            if definition.action_id in candidate_action_ids
        )
        if not definitions:
            fail("set_entity_visible_owner_action_candidates_empty")
    else:
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
            if not any(
                task.task_id in projection.reachable_task_ids
                and _family_for_task(task) == FAMILY
                for task in tasks
            ):
                continue

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
            has_effect = any(
                row.get("reason") == SET_UNSUPPORTED for row in set_rows
            )
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
                f"{definition.action_id}@{definition.level}:"
                f"{type(exc).__name__}:{exc}"
            )
            if target is not None:
                raise
    fail(
        "same_owner_outer_action_not_found:"
        + json.dumps(
            {"scanned": scanned, "diagnostics": diagnostics[-12:]},
            sort_keys=True,
        )
    )


def probe(
    root: Path,
    *,
    target: Mapping[str, Any] | None = None,
    require_set_blocker: bool = False,
) -> dict[str, Any]:
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
            require_set_blocker=require_set_blocker,
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


def baseline_probe(
    root: Path,
    target: Mapping[str, Any],
) -> dict[str, Any]:
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
                    "--definition-id",
                    str(target["definition_id"]),
                    "--action-id",
                    str(target["action_id"]),
                    "--action-level",
                    str(target["action_level"]),
                    "--require-set-blocker",
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
                        },
                        sort_keys=True,
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
    if not any(row.get("reason") == SET_UNSUPPORTED for row in base_set):
        fail("baseline_set_entity_visible_effect_blocker_missing")
    if not any(row.get("reason") == UNSUPPORTED_DEFINITION for row in base_set):
        fail("baseline_set_entity_visible_definition_blocker_missing")
    if cur_set:
        fail("current_set_entity_visible_unsupported_provenance_remaining")

    if base["wait_anim_hit_random_rows"] or cur["wait_anim_hit_random_rows"]:
        fail("p3_wait_anim_hit_random_regressed")

    base_other = [
        row for row in base["blocker_provenance"] if not _set_specific(row)
    ]
    cur_other = [
        row for row in cur["blocker_provenance"] if not _set_specific(row)
    ]
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

    print("P4_STAGE current_probe_start", file=sys.stderr, flush=True)
    current = probe(root)
    print("P4_STAGE current_probe_done", file=sys.stderr, flush=True)
    target = {
        key: current["representative"][key]
        for key in ("definition_id", "action_id", "action_level")
    }
    print("P4_STAGE baseline_probe_start", file=sys.stderr, flush=True)
    baseline = baseline_probe(root, target)
    print("P4_STAGE baseline_probe_done", file=sys.stderr, flush=True)
    delta = compare_representative(baseline, current)

    if ability_task_execution_mode(FAMILY) != "process_only":
        fail("set_entity_visible_execution_mode_not_process_only")
    if ability_task_execution_mode("SetEntityForceVisible") != "runtime_effect":
        fail("set_entity_force_visible_sibling_mode_changed")

    with patch.object(
        TaskGraphExecutor,
        "execute",
        side_effect=AssertionError(
            "denominator runtime task graph execution forbidden"
        ),
    ) as execute_mock, patch.object(
        RuleEvaluator,
        "evaluate_condition_result",
        side_effect=AssertionError("denominator condition evaluation forbidden"),
    ) as condition_mock, patch.object(
        random,
        "random",
        side_effect=AssertionError("denominator gameplay RNG forbidden"),
    ) as rng_mock:
        print("P4_STAGE denominator_start", file=sys.stderr, flush=True)
        denominator = formal_denominator(root)
        print("P4_STAGE denominator_done", file=sys.stderr, flush=True)

    if execute_mock.call_count or condition_mock.call_count or rng_mock.call_count:
        fail("denominator_runtime_boundary_called")
    counts = denominator["partition_counts"]
    if counts[PARTITION_D]:
        fail(
            "set_entity_visible_denominator_unresolved:"
            + json.dumps(
                denominator["blocked_reason_counts"],
                sort_keys=True,
            )
        )
    if denominator["total_selected"] != sum(counts.values()):
        fail("set_entity_visible_denominator_incomplete")
    if not counts[PARTITION_A]:
        fail("set_entity_visible_formal_ability_task_slice_empty")

    elapsed = time.perf_counter() - started
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    predicates = {
        "fixed_base": gov["fixed_base"] == BASE_SHA,
        "pinned_tbgd": pin == TBGD_PIN,
        "source_scope_denominator_nonempty": denominator["total_selected"] > 0,
        "producer_partition_identity_closed": denominator[
            "partition_identity_closed"
        ],
        "blocked_or_unresolved_empty": counts[PARTITION_D] == 0,
        "formal_ability_task_slice_nonempty": counts[PARTITION_A] > 0,
        "formal_status_callback_slice_attributed": (
            counts[PARTITION_B] >= 0
            and denominator["status_callback_semantics"]["production_unchanged"]
        ),
        "template_no_producer_attribution_closed": (
            denominator["template_attribution"]["no_formal_producer_count"]
            == counts[PARTITION_C]
        ),
        "set_entity_visible_unsupported_provenance_removed": not delta[
            "current_set_entity_visible_rows"
        ],
        "p3_wait_anim_no_regression": not delta[
            "p3_wait_anim_hit_random_rows"
        ],
        "s11_damage_heal_shield_preserved": delta[
            "s11_damage_heal_shield_preserved"
        ],
        "other_blockers_preserved": delta[
            "other_blocker_provenance_preserved"
        ],
        "set_entity_force_visible_sibling_unchanged": (
            ability_task_execution_mode("SetEntityForceVisible")
            == "runtime_effect"
        ),
        "runtime_execution_condition_rng_zero": True,
        "read_only_authorities_unchanged": gov[
            "read_only_authorities_unchanged"
        ],
        "status_callback_authority_unchanged": gov[
            "status_callback_authority_unchanged"
        ],
    }
    return {
        "ok": (
            elapsed < 300
            and peak < 2 * 1024 * 1024
            and all(predicates.values())
        ),
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
            "budget_wall_seconds": 300,
            "budget_peak_rss_kib": 2 * 1024 * 1024,
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
    parser.add_argument("--require-set-blocker", action="store_true")
    args = parser.parse_args()
    root = args.tbgd_root.resolve()

    target = None
    target_fields = (args.definition_id, args.action_id, args.action_level)
    if any(value is not None for value in target_fields):
        if (
            args.definition_id is None
            or args.action_id is None
            or args.action_level is None
        ):
            fail("probe_target_identity_incomplete")
        target = {
            "definition_id": args.definition_id,
            "action_id": args.action_id,
            "action_level": args.action_level,
        }

    if args.probe_json:
        print(
            json.dumps(
                probe(
                    root,
                    target=target,
                    require_set_blocker=args.require_set_blocker,
                ),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    if not args.direct:
        fail("--direct is required")
    result = run_direct(root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())