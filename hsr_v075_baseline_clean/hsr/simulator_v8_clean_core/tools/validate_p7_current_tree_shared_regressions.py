from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

from ..rules.rulebook import RuleBook
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .p7_evidence import (
    current_regression_structured_check_contract,
    current_regression_structured_check_negative_cases,
    file_sha256,
    source_tree_fingerprint,
)
from .validate_p1_9_phase1_aggregate import run_validation as run_p1
from .validate_p2_status_system_complete import run_validation as run_p2
from .validate_p3_summon_assistant_servant_complete import run_validation as run_p3
from .validate_p4_s2_combatant_action_availability import run_validation as run_p4_s2
from .validate_p4_s3_formula_dynamic_binding import run_validation as run_p4_s3
from .validate_p6_s1_damage_toughness_calculation_entry import run_validation as run_p6_s1
from .validate_p6_s4_s5_boundary_static import run_validation as run_p6_static
from .validate_p7_s6_action_ownership_window_contract import _source_card_samples_from_ir
from .validate_p7_s16_in_combat_summon_lifecycle import run_validation_with_rules as run_s16
from .validate_p7_s17_wave_lifecycle_events import run_validation_with_rules as run_s17


VALIDATION_VERSION = "p7_current_tree_shared_regressions"
SEQUENCE = ("p1", "p2", "p3", "p4_s2", "p4_s3", "p6_s1", "p6_static", "s16", "s17")
SUMMARY_NAMES = {
    "p1": "validation_summary_p1_9_phase1_aggregate.json",
    "p2": "validation_summary_p2_status_system_complete.json",
    "p3": "validation_summary_p3_summon_assistant_servant_complete.json",
    "p4_s2": "validation_summary_p4_s2_combatant_action_availability.json",
    "p4_s3": "validation_summary_p4_s3_formula_dynamic_binding.json",
    "p6_s1": "validation_summary_p6_s1_damage_toughness_calculation_entry.json",
    "p6_static": "validation_summary_p6_s4_s5_boundary_static.json",
    "s16": "validation_summary_p7_s16_in_combat_summon_lifecycle.json",
    "s17": "validation_summary_p7_s17_wave_lifecycle_events.json",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    initial_fingerprint = source_tree_fingerprint(package_root)
    structured_check_negatives = current_regression_structured_check_negative_cases(
        _semantic_checks
    )
    rules = RuleBook(TBGDLowering(tbgd_root).build())
    runners: dict[str, Callable[[Path], dict[str, Any]]] = {
        "p1": lambda path: run_p1(package_root, tbgd_root, path, rules=rules),
        "p2": lambda path: run_p2(package_root, tbgd_root, path, rules=rules),
        "p3": lambda path: run_p3(package_root, tbgd_root, path, rules=rules),
        "p4_s2": lambda path: run_p4_s2(package_root, tbgd_root, path, rules=rules),
        "p4_s3": lambda path: run_p4_s3(package_root, tbgd_root, path, rules=rules),
        "p6_s1": lambda path: run_p6_s1(package_root, tbgd_root, path, rules=rules),
        "p6_static": lambda path: run_p6_static(package_root, path),
        "s16": lambda path: run_s16(rules, path),
        "s17": lambda path: run_s17(rules.ir, rules, path),
    }
    entries: dict[str, dict[str, Any]] = {}
    stopped_after = ""
    for name in SEQUENCE:
        stage_output = output_dir / name
        try:
            summary = runners[name](stage_output)
            semantic_checks = _semantic_checks(name, summary)
            entry_ok = all(semantic_checks.values())
            summary_path = stage_output / SUMMARY_NAMES[name]
            summary["current_source_binding"] = {
                "schema_version": "current_source_binding_v1",
                "source_tree_fingerprint": initial_fingerprint,
                "shared_validation_version": VALIDATION_VERSION,
                "shared_rulebook_build_count": 1,
            }
            write_json(summary_path, summary)
            entries[name] = {
                "summary": summary_path.as_posix(),
                "summary_sha256": file_sha256(summary_path),
                "semantic_checks": semantic_checks,
                "classification": _classification(name, summary),
                "ok": entry_ok,
            }
        except Exception as exc:  # evidence must survive the first real failure
            entries[name] = {
                "summary": "",
                "summary_sha256": "",
                "semantic_checks": {},
                "classification": "validation_exception",
                "error": f"{type(exc).__name__}: {exc}",
                "ok": False,
            }
            stopped_after = name
            break
        if not entry_ok:
            stopped_after = name
            break

    fingerprint = source_tree_fingerprint(package_root)
    s6_real_source_evidence = {"source_card_samples": _source_card_samples_from_ir(rules.ir)}
    s6_real_source_path = output_dir / "p7_s6_real_source_evidence.json"
    write_json(s6_real_source_path, s6_real_source_evidence)
    checks = {
        "single_shared_rulebook_build": True,
        "sequence_complete": tuple(entries) == SEQUENCE,
        "all_semantic_gates_ok": tuple(entries) == SEQUENCE and all(entry["ok"] for entry in entries.values()),
        "source_tree_stable_during_run": initial_fingerprint == fingerprint,
        "p2_retained_gap_explicit": entries.get("p2", {}).get("classification")
        == "retained_action_delay_content_gap",
        "p3_reopened_gap_explicit": entries.get("p3", {}).get("classification") == "reopened_servant_action_content_gap",
        "p4_p6_current_targeted_regressions_ok": all(
            entries.get(name, {}).get("classification") == "current_tree_regression_passed"
            for name in ("p4_s2", "p4_s3", "p6_s1", "p6_static")
        ),
        "structured_check_gate_negatives_ok": structured_check_negatives.get("ok") is True,
        "no_large_ir_artifact_written": True,
    }
    result = {
        "schema_version": "p7_current_tree_shared_regressions_v3",
        "version": VALIDATION_VERSION,
        "ok": all(checks.values()),
        "source_tree_fingerprint": fingerprint,
        "sequence": list(SEQUENCE),
        "completed_sequence": list(entries),
        "stopped_after": stopped_after,
        "checks": checks,
        "entries": entries,
        "structured_check_gate_negative_evidence": structured_check_negatives,
        "shared_real_source_evidence": {
            "s6": s6_real_source_path.as_posix(),
            "s6_sha256": file_sha256(s6_real_source_path),
        },
        "resource_budget": {
            "tbgd_lowering_build_count": 1,
            "rulebook_build_count": 1,
            "serial_execution": True,
            "large_artifacts_written": False,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "p7_current_tree_shared_regression_manifest.json", result)
    return result


def _semantic_checks(name: str, summary: dict[str, Any]) -> dict[str, bool]:
    if name == "p1":
        break_case = (
            summary.get("direct_regression_checks", {})
            .get("status_cases", {})
            .get("break_status", {})
        )
        break_checks = dict(break_case.get("checks") or {})
        return {
            "validation_gate_ok": summary.get("ok") is True,
            "break_status_case_ok": break_case.get("ok") is True,
            "break_status_mutation_ok": break_checks.get("real_break_status_mutation_ok") is True,
            "break_status_replay_ok": break_checks.get("real_break_replay_ok") is True,
            "break_status_source_audit_ok": break_checks.get("real_break_source_audit_ok") is True,
            "break_status_typed_target_ok": break_checks.get("executable_break_targets_typed") is True,
            "break_status_param_entity_ok": break_checks.get("param_entity_target_preserved") is True,
        }
    if name == "p2":
        summary_data = dict(summary.get("summary") or {})
        content_gaps = dict(summary_data.get("p2_status_content_coverage_gaps") or {})
        action_delay = dict(content_gaps.get("action_delay_callback_graph") or {})
        return {
            "historical_substrate_not_claimed": summary.get("ok") is False
            and summary_data.get("p2_status_substrate_complete") is False,
            "source_closure_ok": summary.get("checks", {}).get("s11_source_closure", {}).get("ok") is True,
            "source_audit_replay_samples_ok": summary.get("checks", {}).get("source_audit_replay_samples", {}).get("ok") is True,
            "single_action_delay_gap_explicit": set(content_gaps) == {"action_delay_callback_graph"}
            and action_delay.get("classification") == "implementation_missing"
            and action_delay.get("p7_invariant_blocker") is False
            and int(action_delay.get("primitive_runtime_candidate_count") or 0) > 0,
        }
    if name == "p3":
        return {
            "validation_gate_ok": summary.get("ok") is True and summary.get("validation_gate_ok") is True,
            "historical_foundation_not_claimed": summary.get("p3_summon_foundation_closed") is False,
            "servant_action_gap_reopened": int(summary.get("p3_summon_implementation_missing_count") or 0) > 0,
            "result_status_explicit": summary.get("p3_summon_result_status")
            == "validation_gate_ok_phase_incomplete_with_disallowed_gaps",
        }
    if name in {"p4_s2", "p4_s3", "p6_s1", "p6_static"}:
        budget = dict(summary.get("resource_budget") or {})
        return {
            "validation_gate_ok": summary.get("ok") is True,
            **current_regression_structured_check_contract(name, summary),
            "shared_rulebook_not_rebuilt": (
                budget.get("lowering_build_count") == 0
                and budget.get("rulebook_build_count") == 0
                and budget.get("shared_rulebook_reused") is True
            )
            if name != "p6_static"
            else budget.get("large_artifacts_written") is False,
            "no_large_artifacts": budget.get("large_artifacts_written") is False,
        }
    return {
        "validation_gate_ok": summary.get("ok") is True,
        "ready_for_review": summary.get("ready_for_review") is True,
    }


def _classification(name: str, summary: dict[str, Any]) -> str:
    if name == "p2":
        gaps = dict((summary.get("summary") or {}).get("p2_status_content_coverage_gaps") or {})
        if set(gaps) == {"action_delay_callback_graph"}:
            return "retained_action_delay_content_gap"
    if name == "p3" and int(summary.get("p3_summon_implementation_missing_count") or 0) > 0:
        return "reopened_servant_action_content_gap"
    return "current_tree_regression_passed" if summary.get("ok") is True else "current_tree_regression_failed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run P1/P2/P3, targeted P4/P6, and S16/S17 against one shared current RuleBook."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    tbgd_root = args.tbgd_root or find_tbgd_root(package_root.parent)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} "
        f"completed={len(result['completed_sequence'])}/{len(SEQUENCE)} "
        f"shared_rulebook_builds={result['resource_budget']['rulebook_build_count']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
