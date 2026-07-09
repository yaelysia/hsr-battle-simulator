from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .. import BASELINE_VERSION
from ..core.model import JSONValue
from ..rules.rulebook import RuleBook
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p3_summon_assistant_servant_complete import _build_stage_results as _build_p3_stage_results
from .validate_p4_s0_combatant_source_inventory import (
    build_p4_s0_combatant_source_inventory_matrix,
    validate_p4_s0_combatant_source_inventory_matrix,
)
from .validate_p4_s1_data_card_rulebook_contract import (
    build_p4_s1_data_card_rulebook_contract_matrix,
    validate_p4_s1_data_card_rulebook_contract_matrix,
)
from .validate_p4_s2_combatant_action_availability import (
    build_p4_s2_combatant_action_availability_matrix,
    validate_p4_s2_combatant_action_availability_matrix,
)
from .validate_p4_s3_formula_dynamic_binding import (
    build_p4_s3_formula_dynamic_binding_matrix,
    validate_p4_s3_formula_dynamic_binding_matrix,
)
from .validate_p4_s4_target_query_admission import (
    _global_target_config,
    build_p4_s4_target_backlog_matrix,
    validate_p4_s4_target_backlog_matrix,
)
from .validate_p4_s5_monster_action_graph import (
    build_p4_s5_monster_action_graph_matrix,
    validate_p4_s5_monster_action_graph_matrix,
)
from .validate_p4_s6_monster_passive_listener_wave import (
    build_p4_s6_monster_passive_listener_wave_matrix,
    validate_p4_s6_monster_passive_listener_wave_matrix,
)
from .validate_p4_s7_character_action_mechanism_slots import (
    build_p4_s7_character_action_mechanism_slots_matrix,
    validate_p4_s7_character_action_mechanism_slots_matrix,
)
from .validate_p4_s8_trace_eidolon_level_resource_hooks import (
    build_p4_s8_trace_eidolon_level_resource_hooks_matrix,
    validate_p4_s8_trace_eidolon_level_resource_hooks_matrix,
)
from .validate_p4_s9_data_card_mutation_source_linkage import (
    build_p4_s9_data_card_mutation_source_linkage_matrix,
    validate_p4_s9_data_card_mutation_source_linkage_matrix,
)
from .validate_p4_s10_p3_backlog_recovery import (
    build_p4_s10_p3_backlog_recovery_matrix,
    validate_p4_s10_p3_backlog_recovery_matrix,
)
from .validate_p4_s11_action_query_contract import (
    build_p4_s11_action_query_contract_matrix,
    validate_p4_s11_action_query_contract_matrix,
)


VALIDATION_VERSION = "p4_combatant_data_card_expansion"
MATRIX_SCHEMA_VERSION = "p4_combatant_data_card_expansion_matrix_v1"

GAP_STATES = {
    "source_gap_blocked",
    "lowering_gap",
    "admission_gap",
    "validation_gap",
    "implementation_missing",
    "unclassified",
}
DISALLOWED_GAP_STATES = {"implementation_missing", "lowering_gap", "validation_gap", "unclassified"}
ALLOWED_RETAINED_GAP_STATES = {"admission_gap", "source_gap_blocked"}

STAGE_ROW_KEYS = {
    "p4_s0": "domain_matrix",
    "p4_s1": "contract_matrix",
    "p4_s2": "action_availability_matrix",
    "p4_s3": "formula_dynamic_binding_matrix",
    "p4_s4": "target_backlog_matrix",
    "p4_s5": "monster_action_graph_matrix",
    "p4_s6": "monster_passive_listener_wave_matrix",
    "p4_s7": "character_action_mechanism_slots_matrix",
    "p4_s8": "trace_eidolon_level_resource_matrix",
    "p4_s9": "data_card_mutation_source_matrix",
    "p4_s10": "p3_backlog_recovery_matrix",
    "p4_s11": "action_query_contract_matrix",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p4_combatant_data_card_expansion_matrix(package_root, tbgd_root, ir, rules)
    matrix_checks = validate_p4_combatant_data_card_expansion_matrix(matrix)
    checks = {
        "matrix": matrix_checks,
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    validation_gate_ok = bool(matrix["summary"]["validation_gate_ok"]) and static_result.ok and matrix_checks["ok"]
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": validation_gate_ok,
        "validation_gate_ok": validation_gate_ok,
        "p4_combatant_data_card_phase_complete": validation_gate_ok,
        "p4_combatant_data_card_substrate_complete": validation_gate_ok,
        "p4_all_executable_complete": bool(matrix["summary"]["p4_all_executable_complete"]),
        "p4_sources_classified": bool(matrix["summary"]["p4_sources_classified"]),
        "p4_implementation_missing_count": int(matrix["summary"]["p4_implementation_missing_count"]),
        "p4_lowering_gap_count": int(matrix["summary"]["p4_lowering_gap_count"]),
        "p4_validation_gap_count": int(matrix["summary"]["p4_validation_gap_count"]),
        "p4_unclassified_count": int(matrix["summary"]["p4_unclassified_count"]),
        "allowed_gap_evidence_summary": matrix["allowed_gap_evidence_matrix"]["summary"],
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "p4_s12_aggregate_from_current_s0_s11_matrices",
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "stage_summary": matrix["stage_summary"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p4_combatant_data_card_expansion.json", result)
    write_json(output_dir / "p4_combatant_data_card_expansion_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P4 combatant data-card expansion aggregate.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} validation_gate_ok={result['validation_gate_ok']} "
        f"p4_substrate_complete={result['p4_combatant_data_card_substrate_complete']} "
        f"p4_all_executable_complete={result['p4_all_executable_complete']} "
        f"gap_counts={result['summary']['p4_gap_counts']}"
    )
    return 0 if result["ok"] else 1


def build_p4_combatant_data_card_expansion_matrix(
    package_root: Path,
    tbgd_root: Path,
    ir,
    rules: RuleBook,
) -> dict[str, Any]:
    s0 = build_p4_s0_combatant_source_inventory_matrix(tbgd_root, ir, rules)
    s1 = build_p4_s1_data_card_rulebook_contract_matrix(ir, rules, s0)
    s2 = build_p4_s2_combatant_action_availability_matrix(ir, rules, s1)
    s3 = build_p4_s3_formula_dynamic_binding_matrix(ir, rules, s0)
    s4 = build_p4_s4_target_backlog_matrix(ir, rules, _global_target_config(tbgd_root))
    s5 = build_p4_s5_monster_action_graph_matrix(ir, rules)
    s6 = build_p4_s6_monster_passive_listener_wave_matrix(ir, rules)
    s7 = build_p4_s7_character_action_mechanism_slots_matrix(ir, rules)
    s8 = build_p4_s8_trace_eidolon_level_resource_hooks_matrix(ir, rules)
    s9 = build_p4_s9_data_card_mutation_source_linkage_matrix(ir, rules)
    p3_stage_results = _build_p3_stage_results(package_root, tbgd_root, rules)
    s10 = build_p4_s10_p3_backlog_recovery_matrix(p3_stage_results, rules)
    s11 = build_p4_s11_action_query_contract_matrix(ir, rules)

    stages = {
        "p4_s0": _stage("p4_s0", s0, validate_p4_s0_combatant_source_inventory_matrix(s0)),
        "p4_s1": _stage("p4_s1", s1, validate_p4_s1_data_card_rulebook_contract_matrix(s1)),
        "p4_s2": _stage("p4_s2", s2, validate_p4_s2_combatant_action_availability_matrix(s2)),
        "p4_s3": _stage("p4_s3", s3, validate_p4_s3_formula_dynamic_binding_matrix(s3)),
        "p4_s4": _stage("p4_s4", s4, validate_p4_s4_target_backlog_matrix(s4)),
        "p4_s5": _stage("p4_s5", s5, validate_p4_s5_monster_action_graph_matrix(s5)),
        "p4_s6": _stage("p4_s6", s6, validate_p4_s6_monster_passive_listener_wave_matrix(s6)),
        "p4_s7": _stage("p4_s7", s7, validate_p4_s7_character_action_mechanism_slots_matrix(s7)),
        "p4_s8": _stage("p4_s8", s8, validate_p4_s8_trace_eidolon_level_resource_hooks_matrix(s8)),
        "p4_s9": _stage("p4_s9", s9, validate_p4_s9_data_card_mutation_source_linkage_matrix(s9)),
        "p4_s10": _stage("p4_s10", s10, validate_p4_s10_p3_backlog_recovery_matrix(s10)),
        "p4_s11": _stage("p4_s11", s11, validate_p4_s11_action_query_contract_matrix(s11)),
    }

    stage_rows = {stage_id: _stage_public(stage_id, stage) for stage_id, stage in stages.items()}
    total_gap_counts = _total_gap_counts(stages)
    allowed_gap_evidence = _allowed_gap_evidence_matrix(stages)
    source_total_matrix = _source_total_matrix(s0)
    mechanism_total_matrix = _mechanism_total_matrix(stages)
    scope_exclusions = _scope_exclusion_matrix(stages)
    positive_samples = _positive_samples(stages)
    blocked_samples = _blocked_samples(stages)
    audit_replay_samples = _source_audit_replay_samples(stages)

    disallowed_gap_count = sum(int(total_gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES)
    stage_ok = all(bool(stage["checks"].get("ok")) for stage in stages.values())
    p4_sources_classified = int(total_gap_counts.get("unclassified", 0)) == 0
    all_executable = (
        disallowed_gap_count == 0
        and int(total_gap_counts.get("admission_gap", 0)) == 0
        and int(total_gap_counts.get("source_gap_blocked", 0)) == 0
    )
    validation_gate_ok = (
        stage_ok
        and p4_sources_classified
        and disallowed_gap_count == 0
        and allowed_gap_evidence["summary"]["all_evidence_ok"] is True
        and allowed_gap_evidence["summary"]["disallowed_gap_count"] == 0
    )

    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "stage_summary": stage_rows,
        "source_total_matrix": source_total_matrix,
        "mechanism_total_matrix": mechanism_total_matrix,
        "data_card_contract_matrix": _matrix_rows(stages["p4_s1"]["matrix"], "p4_s1"),
        "action_availability_matrix": _matrix_rows(stages["p4_s2"]["matrix"], "p4_s2"),
        "formula_dynamic_binding_matrix": _matrix_rows(stages["p4_s3"]["matrix"], "p4_s3"),
        "target_backlog_matrix": _matrix_rows(stages["p4_s4"]["matrix"], "p4_s4"),
        "monster_action_passive_matrix": {
            **_prefix_rows(_matrix_rows(stages["p4_s5"]["matrix"], "p4_s5"), "p4_s5"),
            **_prefix_rows(_matrix_rows(stages["p4_s6"]["matrix"], "p4_s6"), "p4_s6"),
        },
        "character_action_trace_eidolon_resource_matrix": {
            **_prefix_rows(_matrix_rows(stages["p4_s7"]["matrix"], "p4_s7"), "p4_s7"),
            **_prefix_rows(_matrix_rows(stages["p4_s8"]["matrix"], "p4_s8"), "p4_s8"),
        },
        "p3_backlog_recovery_matrix": _matrix_rows(stages["p4_s10"]["matrix"], "p4_s10"),
        "action_query_contract_matrix": _matrix_rows(stages["p4_s11"]["matrix"], "p4_s11"),
        "positive_samples": positive_samples,
        "blocked_samples": blocked_samples,
        "source_audit_replay_samples": audit_replay_samples,
        "allowed_gap_evidence_matrix": allowed_gap_evidence,
        "scope_exclusion_matrix": scope_exclusions,
        "summary": {
            "validation_gate_ok": validation_gate_ok,
            "p4_combatant_data_card_phase_complete": validation_gate_ok,
            "p4_combatant_data_card_substrate_complete": validation_gate_ok,
            "p4_all_executable_complete": all_executable,
            "p4_sources_classified": p4_sources_classified,
            "p4_gap_counts": dict(sorted(total_gap_counts.items())),
            "p4_implementation_missing_count": int(total_gap_counts.get("implementation_missing", 0)),
            "p4_lowering_gap_count": int(total_gap_counts.get("lowering_gap", 0)),
            "p4_validation_gap_count": int(total_gap_counts.get("validation_gap", 0)),
            "p4_unclassified_count": int(total_gap_counts.get("unclassified", 0)),
            "p4_admission_gap_count": int(total_gap_counts.get("admission_gap", 0)),
            "p4_source_gap_blocked_count": int(total_gap_counts.get("source_gap_blocked", 0)),
            "stage_count": len(stages),
            "failed_stage_count": sum(0 if stage["checks"].get("ok") else 1 for stage in stages.values()),
            "allowed_gap_evidence_summary": allowed_gap_evidence["summary"],
            "scope_exclusion_count": scope_exclusions["summary"]["row_count"],
            "positive_sample_count": positive_samples["summary"]["sample_count"],
            "blocked_sample_count": blocked_samples["summary"]["sample_count"],
            "source_audit_replay_sample_count": audit_replay_samples["summary"]["sample_count"],
        },
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "static_check_count": 1,
            "subprocess_validation_count": 0,
            "p4_subvalidators_reused_in_memory": True,
            "p3_stage_results_reused_in_memory_for_s10": True,
            "full_ir_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_scope": "aggregate_summary_matrices_samples_gap_evidence_only",
            "output_files": [
                "validation_summary_p4_combatant_data_card_expansion.json",
                "p4_combatant_data_card_expansion_matrix.json",
            ],
        },
    }


def validate_p4_combatant_data_card_expansion_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    summary = dict(matrix.get("summary") or {})
    stage_summary = dict(matrix.get("stage_summary") or {})
    required_stages = set(STAGE_ROW_KEYS)
    missing_stages = sorted(required_stages.difference(stage_summary))
    checks = {
        "required_stages_present": not missing_stages,
        "all_stage_checks_ok": all(dict(row.get("checks") or {}).get("ok") is True for row in stage_summary.values()),
        "p4_sources_classified": summary.get("p4_sources_classified") is True,
        "implementation_missing_zero": int(summary.get("p4_implementation_missing_count") or 0) == 0,
        "lowering_gap_zero": int(summary.get("p4_lowering_gap_count") or 0) == 0,
        "validation_gap_zero": int(summary.get("p4_validation_gap_count") or 0) == 0,
        "unclassified_zero": int(summary.get("p4_unclassified_count") or 0) == 0,
        "allowed_gap_evidence_ok": dict(summary.get("allowed_gap_evidence_summary") or {}).get("all_evidence_ok")
        is True,
        "allowed_gap_disallowed_zero": int(
            dict(summary.get("allowed_gap_evidence_summary") or {}).get("disallowed_gap_count") or 0
        )
        == 0,
        "positive_samples_present": int(summary.get("positive_sample_count") or 0) > 0,
        "blocked_samples_present": int(summary.get("blocked_sample_count") or 0) > 0,
        "source_audit_replay_samples_present": int(summary.get("source_audit_replay_sample_count") or 0) > 0,
        "resource_budget_summary_only": (
            matrix.get("resource_budget", {}).get("full_ir_written") is False
            and matrix.get("resource_budget", {}).get("full_transition_dump_written") is False
            and matrix.get("resource_budget", {}).get("large_artifacts_written") is False
        ),
    }
    checks["validation_gate_ok"] = all(value for key, value in checks.items() if key != "validation_gate_ok")
    checks["ok"] = checks["validation_gate_ok"]
    return {"ok": checks["ok"], "checks": checks, "missing_stages": missing_stages}


def _stage(stage_id: str, matrix: dict[str, Any], checks: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage_id": stage_id,
        "matrix": matrix,
        "checks": checks,
        "summary": _summary_for_matrix(stage_id, matrix),
        "rows": _matrix_rows(matrix, stage_id),
    }


def _stage_public(stage_id: str, stage: dict[str, Any]) -> dict[str, JSONValue]:
    return {
        "stage_id": stage_id,
        "ok": bool(stage["checks"].get("ok")),
        "matrix_ref": str(stage["matrix"].get("schema_version") or ""),
        "row_count": len(stage["rows"]),
        "summary": _compact_json(stage["summary"]),
        "gap_counts": dict(sorted(_stage_gap_counts(stage).items())),
        "checks": _compact_json(stage["checks"]),
    }


def _summary_for_matrix(stage_id: str, matrix: dict[str, Any]) -> dict[str, Any]:
    if isinstance(matrix.get("summary"), dict):
        return dict(matrix["summary"])
    if stage_id == "p4_s0":
        return {
            "classification_counts": matrix.get("classification_counts", {}),
            "gap_attribution_counts": matrix.get("gap_attribution_counts", {}),
            "unclassified_count": matrix.get("unclassified_count", 0),
            "raw_count_total": matrix.get("raw_count_total", 0),
            "ir_count_total": matrix.get("ir_count_total", 0),
            "rulebook_visible_count_total": matrix.get("rulebook_visible_count_total", 0),
            "executable_count_total": matrix.get("executable_count_total", 0),
            "blocked_or_gap_count_total": matrix.get("blocked_or_gap_count_total", 0),
        }
    return {}


def _matrix_rows(matrix: dict[str, Any], stage_id: str) -> dict[str, dict[str, JSONValue]]:
    key = STAGE_ROW_KEYS[stage_id]
    rows = matrix.get(key, {})
    if isinstance(rows, dict):
        return {str(row_id): _compact_json(row) for row_id, row in rows.items()}
    return {}


def _iter_rows(stage: dict[str, Any]) -> Iterable[dict[str, Any]]:
    rows = stage.get("rows", {})
    if isinstance(rows, dict):
        for row in rows.values():
            if isinstance(row, dict):
                yield row


def _total_gap_counts(stages: dict[str, dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter({key: 0 for key in GAP_STATES})
    for stage in stages.values():
        counts.update(_stage_gap_counts(stage))
    return counts


def _stage_gap_counts(stage: dict[str, Any]) -> Counter[str]:
    counts: Counter[str] = Counter({key: 0 for key in GAP_STATES})
    summary = stage.get("summary", {})
    gap_attribution = summary.get("gap_attribution_counts") if isinstance(summary, dict) else {}
    if isinstance(gap_attribution, dict):
        for key, value in gap_attribution.items():
            if str(key) in GAP_STATES:
                counts[str(key)] += int(value or 0)
    for row in _iter_rows(stage):
        row_gap_attribution = row.get("gap_attribution") if isinstance(row.get("gap_attribution"), dict) else {}
        if row_gap_attribution:
            for key, value in row_gap_attribution.items():
                if str(key) in GAP_STATES and not (isinstance(gap_attribution, dict) and str(key) in gap_attribution):
                    counts[str(key)] += int(value or 0)
            continue
        classification = str(row.get("classification") or "")
        if classification in GAP_STATES:
            counts[classification] += int(
                row.get("gap_count")
                or row.get("blocked_or_gap_count")
                or row.get("inherited_gap_count")
                or 1
            )
    unclassified = int(summary.get("unclassified_count") or 0) if isinstance(summary, dict) else 0
    counts["unclassified"] += unclassified
    return counts


def _allowed_gap_evidence_matrix(stages: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, JSONValue]] = []
    for stage_id, stage in stages.items():
        for row_id, row in stage["rows"].items():
            gap_kinds = _row_gap_kinds(row)
            if not gap_kinds:
                continue
            disallowed = sorted(gap_kinds & DISALLOWED_GAP_STATES)
            allowed = not disallowed and gap_kinds.issubset(ALLOWED_RETAINED_GAP_STATES)
            evidence_sources = {
                "has_gap_attribution": bool(row.get("gap_attribution")),
                "has_evidence": bool(row.get("evidence")),
                "has_details": bool(row.get("details")),
                "has_blocked_reasons": bool(row.get("blocked_reasons")),
                "has_work_package": bool(row.get("work_package_id")),
                "has_checks": bool(row.get("checks")),
            }
            evidence_ok = allowed and any(evidence_sources.values())
            rows.append(
                {
                    "stage_id": stage_id,
                    "row_id": str(row_id),
                    "classification": str(row.get("classification") or ""),
                    "gap_kinds": sorted(gap_kinds),
                    "gap_count": int(
                        row.get("gap_count")
                        or row.get("blocked_or_gap_count")
                        or row.get("inherited_gap_count")
                        or 1
                    ),
                    "allowed_for_p4_substrate": allowed,
                    "evidence_ok": evidence_ok,
                    "evidence_sources": evidence_sources,
                    "disallowed_gap_kinds": disallowed,
                }
            )
    classification_counts = Counter(str(row["classification"]) for row in rows)
    return {
        "schema_version": "p4_allowed_gap_evidence_matrix_v1",
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "classification_counts": dict(sorted(classification_counts.items())),
            "allowed_gap_count": sum(int(row["gap_count"]) for row in rows if row["allowed_for_p4_substrate"]),
            "disallowed_gap_count": sum(int(row["gap_count"]) for row in rows if row["disallowed_gap_kinds"]),
            "all_evidence_ok": all(bool(row["evidence_ok"]) for row in rows),
        },
    }


def _row_gap_kinds(row: dict[str, Any]) -> set[str]:
    gap_kinds: set[str] = set()
    attribution = row.get("gap_attribution")
    if isinstance(attribution, dict):
        gap_kinds.update(str(key) for key, value in attribution.items() if str(key) in GAP_STATES and int(value or 0) > 0)
    classification = str(row.get("classification") or "")
    if classification in GAP_STATES:
        gap_kinds.add(classification)
    return gap_kinds


def _source_total_matrix(s0_matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(s0_matrix.get("domain_matrix") or {})
    return {
        "schema_version": "p4_source_total_matrix_v1",
        "rows": {str(row_id): _compact_json(row) for row_id, row in rows.items()},
        "summary": {
            "row_count": len(rows),
            "classification_counts": dict(s0_matrix.get("classification_counts") or {}),
            "gap_attribution_counts": dict(s0_matrix.get("gap_attribution_counts") or {}),
            "unclassified_count": int(s0_matrix.get("unclassified_count") or 0),
            "raw_count_total": int(s0_matrix.get("raw_count_total") or 0),
            "ir_count_total": int(s0_matrix.get("ir_count_total") or 0),
            "rulebook_visible_count_total": int(s0_matrix.get("rulebook_visible_count_total") or 0),
        },
    }


def _mechanism_total_matrix(stages: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, JSONValue]] = []
    for stage_id, stage in stages.items():
        if stage_id in {"p4_s0", "p4_s1"}:
            continue
        gap_counts = _stage_gap_counts(stage)
        disallowed = sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES)
        classification = "executable"
        if int(gap_counts.get("source_gap_blocked", 0)) > 0:
            classification = "source_gap_blocked"
        if int(gap_counts.get("admission_gap", 0)) > 0:
            classification = "admission_gap"
        if disallowed:
            classification = next((kind for kind in DISALLOWED_GAP_STATES if int(gap_counts.get(kind, 0)) > 0), classification)
        rows.append(
            {
                "stage_id": stage_id,
                "classification": classification,
                "row_count": len(stage["rows"]),
                "gap_counts": dict(sorted(gap_counts.items())),
                "stage_ok": bool(stage["checks"].get("ok")),
                "evidence": "P4 aggregate mechanism row inherits its stage matrix gap counts.",
            }
        )
    classification_counts = Counter(row["classification"] for row in rows)
    return {
        "schema_version": "p4_mechanism_total_matrix_v1",
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "classification_counts": dict(sorted(classification_counts.items())),
        },
    }


def _scope_exclusion_matrix(stages: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for stage_id, stage in stages.items():
        for row_id, row in stage["rows"].items():
            if row.get("classification") != "out_of_scope":
                continue
            rows.append({"stage_id": stage_id, "row_id": str(row_id), "row": _compact_json(row)})
    return {
        "schema_version": "p4_scope_exclusion_matrix_v1",
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "all_scope_exclusions_classified": all(
                dict(item["row"]).get("classification") == "out_of_scope" for item in rows
            ),
        },
    }


def _positive_samples(stages: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for stage_id, stage in stages.items():
        for row_id, row in stage["rows"].items():
            if row.get("classification") != "executable":
                continue
            sample = _sample_from_row(row)
            if not sample:
                continue
            rows.append({"stage_id": stage_id, "row_id": str(row_id), "sample": sample})
    return {"schema_version": "p4_positive_samples_v1", "rows": rows[:32], "summary": {"sample_count": len(rows[:32])}}


def _blocked_samples(stages: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for stage_id, stage in stages.items():
        for row_id, row in stage["rows"].items():
            if row.get("classification") not in {"boundary_only", "source_absent_not_required", "out_of_scope"}:
                continue
            sample = _sample_from_row(row)
            if not sample and not row.get("blocked_reasons"):
                continue
            rows.append(
                {
                    "stage_id": stage_id,
                    "row_id": str(row_id),
                    "classification": str(row.get("classification") or ""),
                    "sample": sample,
                    "blocked_reasons": _compact_json(row.get("blocked_reasons", [])),
                }
            )
    return {"schema_version": "p4_blocked_samples_v1", "rows": rows[:32], "summary": {"sample_count": len(rows[:32])}}


def _source_audit_replay_samples(stages: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for stage_id, stage in stages.items():
        for row_id, row in stage["rows"].items():
            contract = row.get("transition_contract") if isinstance(row.get("transition_contract"), dict) else {}
            if contract and (contract.get("source_audit_ok") is True or contract.get("replay_ok") is True):
                rows.append({"stage_id": stage_id, "row_id": str(row_id), "transition_contract": _compact_json(contract)})
                continue
            details = row.get("details") if isinstance(row.get("details"), dict) else {}
            if _contains_audit_or_replay(details):
                rows.append({"stage_id": stage_id, "row_id": str(row_id), "details": _compact_json(details)})
    return {
        "schema_version": "p4_source_audit_replay_samples_v1",
        "rows": rows[:32],
        "summary": {
            "sample_count": len(rows[:32]),
            "all_known_contract_samples_ok": all(
                dict(row.get("transition_contract") or {}).get("source_audit_ok", True) is True
                and dict(row.get("transition_contract") or {}).get("replay_ok", True) is True
                for row in rows[:32]
            ),
        },
    }


def _sample_from_row(row: dict[str, Any]) -> dict[str, JSONValue]:
    for key in ("sample_choice", "sample_actor", "sample_source_trace", "sample_expression", "transition_contract"):
        value = row.get(key)
        if value:
            return {key: _compact_json(value)}
    return {}


def _contains_audit_or_replay(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if "source_audit" in lowered or "replay" in lowered:
                return True
            if _contains_audit_or_replay(item):
                return True
    if isinstance(value, list):
        return any(_contains_audit_or_replay(item) for item in value)
    return False


def _prefix_rows(rows: dict[str, dict[str, JSONValue]], prefix: str) -> dict[str, dict[str, JSONValue]]:
    return {f"{prefix}:{row_id}": row for row_id, row in rows.items()}


def _compact_json(value: Any, *, depth: int = 0) -> JSONValue:
    if depth > 4:
        return "..."
    if isinstance(value, dict):
        result: dict[str, JSONValue] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 18:
                result["..."] = "truncated"
                break
            result[str(key)] = _compact_json(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_compact_json(item, depth=depth + 1) for item in list(value)[:18]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
