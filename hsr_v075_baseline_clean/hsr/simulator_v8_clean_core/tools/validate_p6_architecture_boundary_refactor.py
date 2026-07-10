from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from .io import write_json
from .validate_p6_s0_architecture_boundary_ledger import VIOLATION_STATES, run_validation as run_s0
from .validate_p6_s1_damage_toughness_calculation_entry import run_validation as run_s1
from .validate_p6_s2_s3_unit_spawn_birth_plan import run_validation as run_s2_s3
from .validate_p6_s4_s5_boundary_static import run_validation as run_s4_s5
from ..tbgd.paths import find_tbgd_root


VALIDATION_VERSION = "p6_architecture_boundary_refactor"
P6_EXPLICITLY_DEFERRED_S0_FINDING_IDS: frozenset[str] = frozenset()


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stage_results = {
        "p6_s0": run_s0(package_root, output_dir / "p6_s0"),
        "p6_s1": run_s1(package_root, tbgd_root, output_dir / "p6_s1"),
        "p6_s2_s3": run_s2_s3(package_root, tbgd_root, output_dir / "p6_s2_s3"),
        "p6_s4_s5": run_s4_s5(package_root, output_dir / "p6_s4_s5"),
    }
    stage_summary = {stage_id: _stage_summary(result) for stage_id, result in stage_results.items()}
    s0_summary = dict(stage_results["p6_s0"].get("summary") or {})
    s0_unresolved = _partition_s0_unresolved(stage_results["p6_s0"])
    checks = {
        "all_stage_validations_ok": all(result.get("ok") is True for result in stage_results.values()),
        "s0_unresolved_rows_inherited": int(s0_summary.get("violation_row_count") or 0)
        == len(s0_unresolved["blocking_rows"]) + len(s0_unresolved["deferred_rows"]),
        "s0_no_p6_owned_unresolved": not s0_unresolved["blocking_rows"],
        "s1_positive_rows_present": _classification_count(stage_results["p6_s1"], "executable") >= 2,
        "s1_no_raw_param_path_parsing": _matrix_row_check(
            stage_results["p6_s1"],
            "calculation_entry_matrix",
            "executor_trace_mining_static_guard",
            "action_plan_no_param_list_marker",
        )
        and _matrix_row_check(
            stage_results["p6_s1"],
            "calculation_entry_matrix",
            "executor_trace_mining_static_guard",
            "action_plan_no_raw_path_param_index",
        ),
        "s2_s3_positive_rows_present": _classification_count(stage_results["p6_s2_s3"], "executable") >= 3,
        "s2_s3_incomplete_birth_plan_blocks": _matrix_row_check(
            stage_results["p6_s2_s3"],
            "unit_spawn_birth_plan_matrix",
            "summoned_monster_incomplete_birth_plan_negative",
            "all_variants_blocked",
        )
        and _matrix_row_check(
            stage_results["p6_s2_s3"],
            "unit_spawn_birth_plan_matrix",
            "servant_incomplete_birth_plan_negative",
            "all_variants_blocked",
        )
        and _matrix_row_check(
            stage_results["p6_s2_s3"],
            "unit_spawn_birth_plan_matrix",
            "wave_incomplete_birth_plan_negative",
            "all_variants_blocked",
        ),
        "s2_s3_incomplete_birth_plan_no_mutations": _matrix_row_check(
            stage_results["p6_s2_s3"],
            "unit_spawn_birth_plan_matrix",
            "summoned_monster_incomplete_birth_plan_negative",
            "no_mutations",
        )
        and _matrix_row_check(
            stage_results["p6_s2_s3"],
            "unit_spawn_birth_plan_matrix",
            "servant_incomplete_birth_plan_negative",
            "no_mutations",
        )
        and _matrix_row_check(
            stage_results["p6_s2_s3"],
            "unit_spawn_birth_plan_matrix",
            "wave_incomplete_birth_plan_negative",
            "no_mutations",
        ),
        "s2_s3_tampered_birth_plan_blocks": _matrix_row_check(
            stage_results["p6_s2_s3"],
            "unit_spawn_birth_plan_matrix",
            "summoned_monster_tampered_birth_plan_negative",
            "all_variants_blocked",
        )
        and _matrix_row_check(
            stage_results["p6_s2_s3"],
            "unit_spawn_birth_plan_matrix",
            "servant_tampered_birth_plan_negative",
            "all_variants_blocked",
        )
        and _matrix_row_check(
            stage_results["p6_s2_s3"],
            "unit_spawn_birth_plan_matrix",
            "wave_tampered_birth_plan_negative",
            "all_variants_blocked",
        ),
        "s2_s3_tampered_birth_plan_no_mutations": _matrix_row_check(
            stage_results["p6_s2_s3"],
            "unit_spawn_birth_plan_matrix",
            "summoned_monster_tampered_birth_plan_negative",
            "no_mutations",
        )
        and _matrix_row_check(
            stage_results["p6_s2_s3"],
            "unit_spawn_birth_plan_matrix",
            "servant_tampered_birth_plan_negative",
            "no_mutations",
        )
        and _matrix_row_check(
            stage_results["p6_s2_s3"],
            "unit_spawn_birth_plan_matrix",
            "wave_tampered_birth_plan_negative",
            "no_mutations",
        ),
        "s2_s3_birth_template_projected_before_runtime": _matrix_row_check(
            stage_results["p6_s2_s3"],
            "unit_spawn_birth_plan_matrix",
            "unit_birth_template_ir_projection",
            "all_executable_sources_reference_templates",
        )
        and _matrix_row_check(
            stage_results["p6_s2_s3"],
            "unit_spawn_birth_plan_matrix",
            "unit_birth_template_ir_projection",
            "runtime_materializer_has_no_rulebook",
        ),
        "s2_s3_wave_level_source_backed": _matrix_row_check(
            stage_results["p6_s2_s3"],
            "unit_spawn_birth_plan_matrix",
            "wave_stage_level_source_contract",
            "spawned_level_matches_stage",
        )
        and _matrix_row_check(
            stage_results["p6_s2_s3"],
            "unit_spawn_birth_plan_matrix",
            "wave_stage_level_source_contract",
            "hard_level_source_present",
        )
        and _matrix_row_check(
            stage_results["p6_s2_s3"],
            "unit_spawn_birth_plan_matrix",
            "wave_stage_level_source_contract",
            "no_level_80_literal_in_spawn_runtime",
        ),
        "s4_s5_boundary_rows_present": _classification_count(stage_results["p6_s4_s5"], "boundary_guard") >= 5,
        "aggregation_does_not_claim_full_reimplementation": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": checks["ok"],
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "p6_stage_validation_aggregation",
                "inherits_stage_gaps": True,
                "full_ir_written": False,
                "full_rulebook_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
            },
        },
        "checks": {"ok": checks["ok"], "checks": checks},
        "summary": {
            "stage_count": len(stage_results),
            "ok_stage_count": sum(1 for result in stage_results.values() if result.get("ok") is True),
            "stage_ok": {stage_id: bool(result.get("ok")) for stage_id, result in stage_results.items()},
            "stage_summary": stage_summary,
            "inherited_s0_unresolved": {
                "violation_row_count": int(s0_summary.get("violation_row_count") or 0),
                "classification_counts": dict(s0_summary.get("classification_counts") or {}),
                "followup_stage_counts": dict(s0_summary.get("followup_stage_counts") or {}),
                "blocking_rows": s0_unresolved["blocking_rows"],
                "explicitly_deferred_rows": s0_unresolved["deferred_rows"],
            },
            "p6_architecture_boundary_refactor_ready_for_review": checks["ok"],
            "p6_all_mechanisms_reimplemented": False,
        },
        "stage_results": stage_summary,
        "resource_budget": {
            "subvalidation_count": len(stage_results),
            "lowering_build_count": 2,
            "rulebook_build_count": 2,
            "full_ir_written": False,
            "full_rulebook_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
        },
    }
    write_json(output_dir / "validation_summary_p6_architecture_boundary_refactor.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P6 architecture boundary refactor aggregate.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} "
        f"stages={result['summary']['ok_stage_count']}/{result['summary']['stage_count']} "
        f"ready_for_review={result['summary']['p6_architecture_boundary_refactor_ready_for_review']}"
    )
    return 0 if result["ok"] else 1


def _partition_s0_unresolved(result: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    matrix = result.get("boundary_ledger_matrix")
    rows = matrix.values() if isinstance(matrix, dict) else ()
    blocking_rows: list[dict[str, str]] = []
    deferred_rows: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict) or str(row.get("classification") or "") not in VIOLATION_STATES:
            continue
        summary = {
            "finding_id": str(row.get("finding_id") or ""),
            "classification": str(row.get("classification") or ""),
            "followup_stage": str(row.get("followup_stage") or ""),
        }
        if summary["finding_id"] in P6_EXPLICITLY_DEFERRED_S0_FINDING_IDS:
            deferred_rows.append(summary)
        else:
            blocking_rows.append(summary)
    return {"blocking_rows": blocking_rows, "deferred_rows": deferred_rows}


def _stage_summary(result: dict[str, Any]) -> dict[str, Any]:
    summary = dict(result.get("summary") or {})
    return {
        "ok": bool(result.get("ok")),
        "version": str(result.get("version") or ""),
        "summary": summary,
        "checks_ok": bool(result.get("checks", {}).get("matrix", {}).get("ok", result.get("checks", {}).get("ok", False)))
        if isinstance(result.get("checks"), dict)
        else False,
    }


def _classification_count(result: dict[str, Any], classification: str) -> int:
    counts = result.get("summary", {}).get("classification_counts")
    if not isinstance(counts, dict):
        return 0
    value = counts.get(classification, 0)
    return int(value) if isinstance(value, int) else 0


def _matrix_row_check(result: dict[str, Any], matrix_key: str, row_id: str, check_name: str) -> bool:
    rows = result.get(matrix_key)
    if not isinstance(rows, dict):
        return False
    row = rows.get(row_id)
    if not isinstance(row, dict):
        return False
    checks = row.get("checks")
    if not isinstance(checks, dict):
        return False
    nested = checks.get("checks")
    if not isinstance(nested, dict):
        return False
    return bool(nested.get(check_name))


if __name__ == "__main__":
    raise SystemExit(main())
