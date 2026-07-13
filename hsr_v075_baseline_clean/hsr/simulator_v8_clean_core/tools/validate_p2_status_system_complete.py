from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..rules.rulebook import RuleBook
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .validate_p2_s10_status_callback_coverage import run_validation as run_s10_validation
from .validate_p2_s11_full_status_source_closure import run_validation as run_s11_validation


VALIDATION_VERSION = "p2_status_system_complete"


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    *,
    rules: RuleBook | None = None,
) -> dict[str, Any]:
    s10_output = output_dir / "s10_callback_coverage"
    s11_output = output_dir / "s11_source_closure"
    s10 = run_s10_validation(package_root, tbgd_root, s10_output, rules=rules)
    s11 = run_s11_validation(package_root, tbgd_root, s11_output, rules=rules)

    final_summary = _final_summary(s10, s11)
    source_audit_report = _source_audit_replay_report(s10)
    mechanism_matrix = _mechanism_matrix(s11)
    positive_samples = _positive_samples(s10, s11)
    negative_samples = _negative_samples(s10, s11)
    resource_budget = _resource_budget(output_dir, lowering_runs=0 if rules is not None else 2)
    checks = {
        "s10_callback_coverage": {"ok": s10["ok"], "checks": {"s10_ok": s10["ok"]}},
        "s11_source_closure": {"ok": s11["ok"], "checks": {"s11_ok": s11["ok"]}},
        "final_summary": _summary_checks(final_summary),
        "source_audit_replay_samples": source_audit_report["checks"],
        "resource_budget": resource_budget["checks"],
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "summary": final_summary,
        "checks": checks,
        "matrices": {
            "status_total_coverage": s11["summary"]["family_closure"],
            "status_mechanism_classification": mechanism_matrix,
            "source_domains": s11["summary"]["source_domains"],
            "blocked_evidence": s11["summary"]["blocked_evidence"],
            "content_coverage_gaps": final_summary["p2_status_content_coverage_gaps"],
        },
        "samples": {
            "positive": positive_samples,
            "negative": negative_samples,
            "source_audit_replay": source_audit_report["samples"],
        },
        "resource_budget": resource_budget["summary"],
        "sub_validation_outputs": {
            "s10_callback_coverage": s10_output.as_posix(),
            "s11_source_closure": s11_output.as_posix(),
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p2_status_system_complete.json", result)
    return result


def _final_summary(s10: dict[str, Any], s11: dict[str, Any]) -> dict[str, Any]:
    family_summary = s11["summary"]["family_closure"]
    classification_counts = Counter(family_summary["classification_counts"])
    return {
        "ok": bool(s10["ok"] and s11["ok"]),
        "p2_status_substrate_complete": bool(s10["ok"] and s11["ok"]),
        "p2_all_status_sources_classified": family_summary["unclassified_count"] == 0,
        "p2_status_full_callback_coverage": not bool(s10["summary"].get("content_gaps")),
        "p2_status_content_coverage_gap_count": len(s10["summary"].get("content_gaps", {})),
        "p2_status_content_coverage_gaps": s10["summary"].get("content_gaps", {}),
        "p2_status_implementation_missing_count": classification_counts.get("implementation_missing", 0),
        "p2_status_lowering_gap_count": classification_counts.get("lowering_gap", 0),
        "p2_status_admission_gap_count": classification_counts.get("admission_gap", 0),
        "p2_status_validation_gap_count": classification_counts.get("validation_gap", 0),
        "p2_status_unclassified_count": family_summary["unclassified_count"],
        "source_absent_not_required_count": classification_counts.get("source_absent_not_required", 0),
        "status_family_count": family_summary["family_count"],
        "status_family_classification_counts": dict(sorted(classification_counts.items())),
        "source_domain_classification_counts": s11["summary"]["source_domain_classification_counts"],
        "raw_total": family_summary["source_item_counts"]["raw_total"],
        "ir_total": family_summary["source_item_counts"]["ir_total"],
        "executable_total": family_summary["source_item_counts"]["executable_total"],
        "blocked_total": family_summary["source_item_counts"]["blocked_total"],
    }


def _summary_checks(summary: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "summary_ok": summary["ok"] is True,
        "substrate_complete": summary["p2_status_substrate_complete"] is True,
        "all_sources_classified": summary["p2_all_status_sources_classified"] is True,
        "content_coverage_gaps_classified": all(
            isinstance(item, dict) and item.get("classification") == "implementation_missing"
            for item in summary["p2_status_content_coverage_gaps"].values()
        ),
        "implementation_missing_zero": summary["p2_status_implementation_missing_count"] == 0,
        "lowering_gap_zero": summary["p2_status_lowering_gap_count"] == 0,
        "admission_gap_zero": summary["p2_status_admission_gap_count"] == 0,
        "validation_gap_zero": summary["p2_status_validation_gap_count"] == 0,
        "unclassified_zero": summary["p2_status_unclassified_count"] == 0,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"ok": checks["ok"], "checks": checks}


def _mechanism_matrix(s11: dict[str, Any]) -> dict[str, Any]:
    evidence = s11["summary"]["blocked_evidence"]
    result: dict[str, Any] = {}
    for family_id, item in sorted(evidence.items()):
        result[family_id] = {
            "classification": item["classification"],
            "blocked_count": item["blocked_count"],
            "blocked_validation_script": item["validation_script"],
            "blocked_validation_evidence": item["evidence"],
        }
    return result


def _positive_samples(s10: dict[str, Any], s11: dict[str, Any]) -> dict[str, Any]:
    return {
        "status_callback_mutation_cases": {
            key: value
            for key, value in s10["summary"]["positive_cases"].items()
            if value.get("classification") == "executable"
        },
        "source_domain_cases": s11["summary"]["source_domains"],
    }


def _negative_samples(s10: dict[str, Any], s11: dict[str, Any]) -> dict[str, Any]:
    return {
        "status_callback_blocked_cases": s10["summary"]["negative_cases"],
        "blocked_family_evidence": {
            family_id: item
            for family_id, item in s11["summary"]["blocked_evidence"].items()
            if item["blocked_count"] > 0
        },
        "content_coverage_gaps": s10["summary"].get("content_gaps", {}),
    }


def _source_audit_replay_report(s10: dict[str, Any]) -> dict[str, Any]:
    samples: dict[str, Any] = {}
    counters = Counter()
    for name, check in sorted(s10["checks"].items()):
        transition = check.get("transition")
        if not isinstance(transition, dict):
            continue
        transition_checks = transition.get("checks") if isinstance(transition.get("checks"), dict) else {}
        if not transition_checks:
            continue
        counters["transition_sample_count"] += 1
        if transition_checks.get("source_audit"):
            counters["source_audit_ok_count"] += 1
        if transition_checks.get("replay"):
            counters["replay_ok_count"] += 1
        if transition_checks.get("settlement_traceability"):
            counters["settlement_traceability_ok_count"] += 1
        samples[name] = {
            "transition_checks": transition_checks,
            "source_audit": transition.get("source_audit", {}),
            "replay": transition.get("replay", {}),
        }
    checks = {
        "transition_samples_present": counters["transition_sample_count"] > 0,
        "all_sample_source_audit_ok": counters["source_audit_ok_count"] == counters["transition_sample_count"],
        "all_sample_replay_ok": counters["replay_ok_count"] == counters["transition_sample_count"],
        "all_sample_settlement_traceability_ok": (
            counters["settlement_traceability_ok_count"] == counters["transition_sample_count"]
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks, "counts": dict(sorted(counters.items()))},
        "samples": samples,
    }


def _resource_budget(output_dir: Path, *, lowering_runs: int) -> dict[str, Any]:
    summary = {
        "full_tbgd_lowering_runs": lowering_runs,
        "sub_validations": ("validate_p2_s10_status_callback_coverage", "validate_p2_s11_full_status_source_closure"),
        "large_artifacts_written": False,
        "full_canonical_ir_written": False,
        "full_transition_dump_written": False,
        "output_dir": output_dir.as_posix(),
    }
    checks = {
        "large_artifacts_not_written": not summary["large_artifacts_written"],
        "full_canonical_ir_not_written": not summary["full_canonical_ir_written"],
        "full_transition_dump_not_written": not summary["full_transition_dump_written"],
        "lowering_runs_bounded": summary["full_tbgd_lowering_runs"] <= 2,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "summary": summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P2 status system completion.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    print(f"p2_status_substrate_complete={result['summary']['p2_status_substrate_complete']}")
    print(f"p2_all_status_sources_classified={result['summary']['p2_all_status_sources_classified']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
