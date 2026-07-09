from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from .. import BASELINE_VERSION
from ..rules.rulebook import RuleBook
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p5_s0_formula_dynamic_source_ledger import (
    build_p5_s0_formula_dynamic_source_ledger_matrix,
    validate_p5_s0_formula_dynamic_source_ledger_matrix,
)
from .validate_p5_s1_value_binding_contract import (
    build_p5_s1_value_binding_contract_matrix,
    validate_p5_s1_value_binding_contract_matrix,
)
from .validate_p5_s2_static_param_level_binding import (
    build_p5_s2_static_param_level_binding_matrix,
    validate_p5_s2_static_param_level_binding_matrix,
)
from .validate_p5_s3_dynamic_custom_binding_projection import (
    build_p5_s3_dynamic_custom_binding_projection_matrix,
    validate_p5_s3_dynamic_custom_binding_projection_matrix,
)
from .validate_p5_s4_value_resolver_admission import (
    build_p5_s4_value_resolver_admission_matrix,
    validate_p5_s4_value_resolver_admission_matrix,
)
from .validate_p5_s5_damage_toughness_value_resolver_consumers import (
    build_p5_s5_damage_toughness_value_resolver_consumers_matrix,
    validate_p5_s5_damage_toughness_value_resolver_consumers_matrix,
)
from .validate_p5_s6_resource_status_callback_consumers import (
    build_p5_s6_resource_status_callback_consumers_matrix,
    validate_p5_s6_resource_status_callback_consumers_matrix,
)
from .validate_p5_s7_monster_custom_summon_binding import (
    build_p5_s7_monster_custom_summon_binding_matrix,
    validate_p5_s7_monster_custom_summon_binding_matrix,
)
from .validate_p5_s8_character_trace_eidolon_binding import (
    build_p5_s8_character_trace_eidolon_binding_matrix,
    validate_p5_s8_character_trace_eidolon_binding_matrix,
)
from .validate_p5_s9_negative_audit_replay_migration import (
    build_p5_s9_negative_audit_replay_migration_matrix,
    validate_p5_s9_negative_audit_replay_migration_matrix,
)


VALIDATION_VERSION = "p5_formula_dynamic_param_binding"
MATRIX_SCHEMA_VERSION = "p5_formula_dynamic_param_binding_matrix_v1"

ALLOWED_GAP_STATES = {"admission_gap", "source_gap_blocked"}
DISALLOWED_GAP_STATES = {"implementation_missing", "lowering_gap", "validation_gap", "unclassified"}
REQUIRED_STAGES = tuple(f"s{index}" for index in range(10))


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p5_formula_dynamic_param_binding_matrix(package_root, tbgd_root, ir, rules)
    matrix_checks = validate_p5_formula_dynamic_param_binding_matrix(matrix)
    checks = {
        "matrix": matrix_checks,
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    validation_gate_ok = all(bool(item["ok"]) for item in checks.values())
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": validation_gate_ok,
        "validation_gate_ok": validation_gate_ok,
        "p5_formula_dynamic_param_binding_phase_complete": validation_gate_ok,
        "p5_formula_dynamic_param_binding_substrate_complete": validation_gate_ok,
        "p5_all_executable_complete": matrix["summary"]["p5_all_executable_complete"],
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "p5_s10_stage_matrix_aggregate",
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "full_ir_written": False,
                "full_rulebook_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "stage_summary": matrix["stage_summary"],
        "source_matrix": matrix["source_matrix"],
        "mechanism_matrix": matrix["mechanism_matrix"],
        "allowed_gap_evidence_matrix": matrix["allowed_gap_evidence_matrix"],
        "positive_samples": matrix["positive_samples"],
        "blocked_samples": matrix["blocked_samples"],
        "source_audit_replay_samples": matrix["source_audit_replay_samples"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p5_formula_dynamic_param_binding.json", result)
    write_json(output_dir / "p5_formula_dynamic_param_binding_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P5 formula/dynamic/parameter binding aggregate.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} validation_gate_ok={result['validation_gate_ok']} "
        f"p5_substrate_complete={result['p5_formula_dynamic_param_binding_substrate_complete']} "
        f"p5_all_executable_complete={result['p5_all_executable_complete']} "
        f"gap_counts={result['summary']['p5_gap_counts']}"
    )
    return 0 if result["ok"] else 1


def build_p5_formula_dynamic_param_binding_matrix(
    package_root: Path,
    tbgd_root: Path,
    ir: Any,
    rules: RuleBook,
) -> dict[str, Any]:
    stage_matrices: dict[str, dict[str, Any]] = {
        "s0": build_p5_s0_formula_dynamic_source_ledger_matrix(package_root, tbgd_root, ir, rules),
        "s1": build_p5_s1_value_binding_contract_matrix(package_root, ir, rules),
        "s2": build_p5_s2_static_param_level_binding_matrix(ir, rules),
        "s3": build_p5_s3_dynamic_custom_binding_projection_matrix(ir, rules),
        "s4": build_p5_s4_value_resolver_admission_matrix(ir, rules),
    }
    stage_matrices["s5"] = build_p5_s5_damage_toughness_value_resolver_consumers_matrix(ir, rules)
    stage_matrices["s6"] = build_p5_s6_resource_status_callback_consumers_matrix(ir, rules)
    stage_matrices["s7"] = build_p5_s7_monster_custom_summon_binding_matrix(ir, rules)
    stage_matrices["s8"] = build_p5_s8_character_trace_eidolon_binding_matrix(ir, rules)
    stage_matrices["s9"] = build_p5_s9_negative_audit_replay_migration_matrix(
        ir,
        rules,
        {stage_id: stage_matrices[stage_id] for stage_id in ("s5", "s6", "s7", "s8")},
    )

    stage_checks = _stage_checks(stage_matrices)
    stage_summary = _stage_summary(stage_matrices, stage_checks)
    all_rows = _all_stage_rows(stage_matrices)
    total_gap_counts = _total_gap_counts(stage_summary)
    classification_counts = _total_classification_counts(stage_summary)
    disallowed_gap_count = sum(int(total_gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES)
    p5_sources_classified = int(classification_counts.get("unclassified", 0)) == 0
    allowed_gap_evidence = _allowed_gap_evidence_matrix(all_rows)
    source_matrix = _source_matrix(stage_matrices)
    mechanism_matrix = _mechanism_matrix(stage_summary, all_rows)
    positive_samples = _sample_rows(all_rows, sample_kind="positive")
    blocked_samples = _sample_rows(all_rows, sample_kind="blocked")
    audit_replay_samples = _sample_rows(all_rows, sample_kind="audit_replay")
    all_executable = (
        disallowed_gap_count == 0
        and int(total_gap_counts.get("admission_gap", 0)) == 0
        and int(total_gap_counts.get("source_gap_blocked", 0)) == 0
        and p5_sources_classified
    )
    validation_gate_ok = (
        all(bool(checks.get("ok")) for checks in stage_checks.values())
        and p5_sources_classified
        and disallowed_gap_count == 0
        and allowed_gap_evidence["summary"]["all_evidence_ok"] is True
        and allowed_gap_evidence["summary"]["disallowed_gap_count"] == 0
        and positive_samples["summary"]["sample_count"] > 0
        and blocked_samples["summary"]["sample_count"] > 0
        and audit_replay_samples["summary"]["sample_count"] > 0
    )

    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "stage_summary": stage_summary,
        "source_matrix": source_matrix,
        "mechanism_matrix": mechanism_matrix,
        "allowed_gap_evidence_matrix": allowed_gap_evidence,
        "positive_samples": positive_samples,
        "blocked_samples": blocked_samples,
        "source_audit_replay_samples": audit_replay_samples,
        "stage_matrices": _compact_stage_matrices(stage_matrices),
        "summary": {
            "validation_gate_ok": validation_gate_ok,
            "p5_formula_dynamic_param_binding_phase_complete": validation_gate_ok,
            "p5_formula_dynamic_param_binding_substrate_complete": validation_gate_ok,
            "p5_all_executable_complete": all_executable,
            "p5_sources_classified": p5_sources_classified,
            "p5_gap_counts": dict(sorted(total_gap_counts.items())),
            "p5_classification_counts": dict(sorted(classification_counts.items())),
            "p5_implementation_missing_count": int(total_gap_counts.get("implementation_missing", 0)),
            "p5_lowering_gap_count": int(total_gap_counts.get("lowering_gap", 0)),
            "p5_validation_gap_count": int(total_gap_counts.get("validation_gap", 0)),
            "p5_unclassified_count": int(classification_counts.get("unclassified", 0)),
            "p5_admission_gap_count": int(total_gap_counts.get("admission_gap", 0)),
            "p5_source_gap_blocked_count": int(total_gap_counts.get("source_gap_blocked", 0)),
            "stage_count": len(stage_matrices),
            "failed_stage_count": sum(0 if checks.get("ok") else 1 for checks in stage_checks.values()),
            "allowed_gap_evidence_summary": allowed_gap_evidence["summary"],
            "source_row_count": source_matrix["summary"]["row_count"],
            "mechanism_row_count": mechanism_matrix["summary"]["row_count"],
            "positive_sample_count": positive_samples["summary"]["sample_count"],
            "blocked_sample_count": blocked_samples["summary"]["sample_count"],
            "source_audit_replay_sample_count": audit_replay_samples["summary"]["sample_count"],
        },
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "static_check_count": 1,
            "subprocess_validation_count": 0,
            "stage_matrices_reused_in_memory": list(REQUIRED_STAGES),
            "s9_reused_s5_to_s8_stage_matrices": True,
            "full_ir_written": False,
            "full_rulebook_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_scope": "p5_s10_summary_stage_matrices_samples_gap_evidence_only",
            "output_files": [
                "validation_summary_p5_formula_dynamic_param_binding.json",
                "p5_formula_dynamic_param_binding_matrix.json",
            ],
        },
    }


def validate_p5_formula_dynamic_param_binding_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    stage_summary = dict(matrix.get("stage_summary") or {})
    summary = dict(matrix.get("summary") or {})
    missing_stages = sorted(set(REQUIRED_STAGES).difference(stage_summary))
    checks = {
        "required_stages_present": not missing_stages,
        "all_stage_checks_ok": all(dict(row.get("checks") or {}).get("ok") is True for row in stage_summary.values()),
        "p5_sources_classified": summary.get("p5_sources_classified") is True,
        "implementation_missing_zero": int(summary.get("p5_implementation_missing_count") or 0) == 0,
        "lowering_gap_zero": int(summary.get("p5_lowering_gap_count") or 0) == 0,
        "validation_gap_zero": int(summary.get("p5_validation_gap_count") or 0) == 0,
        "unclassified_zero": int(summary.get("p5_unclassified_count") or 0) == 0,
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
            and matrix.get("resource_budget", {}).get("full_rulebook_written") is False
            and matrix.get("resource_budget", {}).get("full_transition_dump_written") is False
            and matrix.get("resource_budget", {}).get("large_artifacts_written") is False
        ),
    }
    checks["validation_gate_ok"] = all(value for key, value in checks.items() if key != "validation_gate_ok")
    checks["ok"] = checks["validation_gate_ok"]
    return {"ok": checks["ok"], "checks": checks, "missing_stages": missing_stages}


def _stage_checks(stage_matrices: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    validators: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
        "s0": validate_p5_s0_formula_dynamic_source_ledger_matrix,
        "s1": validate_p5_s1_value_binding_contract_matrix,
        "s2": validate_p5_s2_static_param_level_binding_matrix,
        "s3": validate_p5_s3_dynamic_custom_binding_projection_matrix,
        "s4": validate_p5_s4_value_resolver_admission_matrix,
        "s5": validate_p5_s5_damage_toughness_value_resolver_consumers_matrix,
        "s6": validate_p5_s6_resource_status_callback_consumers_matrix,
        "s7": validate_p5_s7_monster_custom_summon_binding_matrix,
        "s8": validate_p5_s8_character_trace_eidolon_binding_matrix,
        "s9": validate_p5_s9_negative_audit_replay_migration_matrix,
    }
    return {stage_id: validators[stage_id](stage_matrices[stage_id]) for stage_id in REQUIRED_STAGES}


def _stage_summary(
    stage_matrices: dict[str, dict[str, Any]],
    stage_checks: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for stage_id in REQUIRED_STAGES:
        matrix = stage_matrices[stage_id]
        summary = dict(matrix.get("summary") or {})
        rows[stage_id] = {
            "stage_id": stage_id,
            "ok": bool(stage_checks[stage_id].get("ok")),
            "checks": stage_checks[stage_id],
            "schema_version": matrix.get("schema_version", ""),
            "row_count": _summary_row_count(summary),
            "classification_counts": dict(summary.get("classification_counts") or {}),
            "gap_counts": dict(summary.get("gap_attribution_counts") or {}),
            "disallowed_gap_count": int(summary.get("disallowed_gap_count") or 0),
            "resource_budget": dict(matrix.get("resource_budget") or {}),
        }
    return rows


def _all_stage_rows(stage_matrices: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stage_id, matrix in stage_matrices.items():
        seen: set[tuple[str, str]] = set()
        for path, row in _iter_rows(matrix):
            row_id = str(row.get("row_id") or path.rsplit(".", 1)[-1])
            key = (path, row_id)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"stage_id": stage_id, "path": path, "row_id": row_id, "row": row})
    return rows


def _iter_rows(value: Any, path: str = ""):
    if isinstance(value, dict):
        if "classification" in value and ("row_id" in value or "checks" in value):
            yield path, value
            return
        for key, child in value.items():
            if key in {"summary", "resource_budget", "runtime_samples", "runtime_sample", "stage_matrix_summaries"}:
                continue
            child_path = f"{path}.{key}" if path else str(key)
            yield from _iter_rows(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_rows(child, f"{path}[{index}]")


def _total_gap_counts(stage_summary: dict[str, dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in stage_summary.values():
        for key, value in dict(row.get("gap_counts") or {}).items():
            counts[str(key)] += int(value or 0)
    return counts


def _total_classification_counts(stage_summary: dict[str, dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in stage_summary.values():
        for key, value in dict(row.get("classification_counts") or {}).items():
            counts[str(key)] += int(value or 0)
    return counts


def _allowed_gap_evidence_matrix(all_rows: list[dict[str, Any]]) -> dict[str, Any]:
    evidence_rows: list[dict[str, Any]] = []
    allowed_gap_count = 0
    disallowed_gap_count = 0
    for item in all_rows:
        row = dict(item["row"])
        classification = str(row.get("classification") or "unclassified")
        raw_gap_attribution = row.get("gap_attribution")
        gap_attribution = dict(raw_gap_attribution) if isinstance(raw_gap_attribution, dict) else {}
        gap_keys = set(gap_attribution)
        if classification in ALLOWED_GAP_STATES:
            gap_keys.add(classification)
        if not gap_keys:
            continue
        allowed = {key: int(gap_attribution.get(key, 1 if key == classification else 0) or 0) for key in gap_keys if key in ALLOWED_GAP_STATES}
        disallowed = {key: int(gap_attribution.get(key, 1 if key == classification else 0) or 0) for key in gap_keys if key in DISALLOWED_GAP_STATES}
        allowed_gap_count += sum(allowed.values())
        disallowed_gap_count += sum(disallowed.values())
        evidence_ok = bool(allowed) and not disallowed and _checks_ok(row)
        evidence_rows.append(
            {
                "stage_id": item["stage_id"],
                "row_id": item["row_id"],
                "path": item["path"],
                "classification": classification,
                "gap_attribution": gap_attribution,
                "allowed_gap_counts": allowed,
                "disallowed_gap_counts": disallowed,
                "checks_ok": _checks_ok(row),
                "evidence_ok": evidence_ok,
            }
        )
    return {
        "rows": evidence_rows,
        "summary": {
            "row_count": len(evidence_rows),
            "allowed_gap_count": allowed_gap_count,
            "disallowed_gap_count": disallowed_gap_count,
            "all_evidence_ok": all(row["evidence_ok"] for row in evidence_rows),
        },
    }


def _source_matrix(stage_matrices: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for stage_id in ("s0", "s1", "s3"):
        for path, row in _iter_rows(stage_matrices[stage_id]):
            row_id = str(row.get("row_id") or path.rsplit(".", 1)[-1])
            rows.append(_compact_row(stage_id, path, row_id, row))
    return {"rows": rows, "summary": {"row_count": len(rows)}}


def _mechanism_matrix(
    stage_summary: dict[str, dict[str, Any]],
    all_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    stage_rows = [
        {
            "stage_id": stage_id,
            "row_count": row.get("row_count", 0),
            "ok": row.get("ok", False),
            "classification_counts": row.get("classification_counts", {}),
            "gap_counts": row.get("gap_counts", {}),
        }
        for stage_id, row in stage_summary.items()
    ]
    mechanism_rows = [
        _compact_row(item["stage_id"], item["path"], item["row_id"], item["row"])
        for item in all_rows
        if item["stage_id"] not in {"s0", "s1", "s3"}
    ]
    return {
        "stage_rows": stage_rows,
        "rows": mechanism_rows,
        "summary": {"row_count": len(stage_rows) + len(mechanism_rows), "stage_row_count": len(stage_rows)},
    }


def _sample_rows(all_rows: list[dict[str, Any]], *, sample_kind: str) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    for item in all_rows:
        row = dict(item["row"])
        classification = str(row.get("classification") or "")
        row_id = str(item["row_id"])
        checks = _inner_checks(row)
        if sample_kind == "positive":
            selected = classification == "executable" and _checks_ok(row)
        elif sample_kind == "blocked":
            selected = classification in {"boundary_only", "admission_gap", "source_gap_blocked"} or any(
                token in row_id for token in ("negative", "blocked", "missing")
            )
        else:
            selected = any(("source_audit" in key or "replay" in key) and value is True for key, value in checks.items())
        if not selected:
            continue
        samples.append(_compact_row(item["stage_id"], item["path"], row_id, row))
        if len(samples) >= 16:
            break
    return {"samples": samples, "summary": {"sample_count": len(samples), "sample_kind": sample_kind}}


def _compact_stage_matrices(stage_matrices: dict[str, dict[str, Any]]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for stage_id, matrix in stage_matrices.items():
        compact[stage_id] = {
            "schema_version": matrix.get("schema_version", ""),
            "summary": matrix.get("summary", {}),
            "row_refs": [
                {"path": path, "row_id": str(row.get("row_id") or path.rsplit(".", 1)[-1])}
                for path, row in _iter_rows(matrix)
            ],
        }
    return compact


def _compact_row(stage_id: str, path: str, row_id: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage_id": stage_id,
        "row_id": row_id,
        "path": path,
        "classification": row.get("classification", ""),
        "raw_count": int(row.get("raw_count") or 0),
        "executable_count": int(row.get("executable_count") or 0),
        "blocked_or_gap_count": int(row.get("blocked_or_gap_count") or 0),
        "gap_attribution": dict(row.get("gap_attribution")) if isinstance(row.get("gap_attribution"), dict) else {},
        "checks_ok": _checks_ok(row),
    }


def _checks_ok(row: dict[str, Any]) -> bool:
    checks = row.get("checks")
    if isinstance(checks, dict):
        return checks.get("ok") is True
    return True


def _inner_checks(row: dict[str, Any]) -> dict[str, Any]:
    checks = row.get("checks")
    if not isinstance(checks, dict):
        return {}
    inner = checks.get("checks")
    return inner if isinstance(inner, dict) else checks


def _summary_row_count(summary: dict[str, Any]) -> int:
    for key in (
        "row_count",
        "total_row_count",
        "source_family_row_count",
    ):
        if isinstance(summary.get(key), int):
            return int(summary[key])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
