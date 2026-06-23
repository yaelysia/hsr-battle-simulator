from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..rules.ir import QueueLifecyclePolicyIR, QueueWindowIR
from ..rules.rulebook import RuleBook
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_235 import _execute_break_setup, _select_break_family_case
from .validate_v0_248 import _extra_turn_execution_case


VALIDATION_VERSION = "v0_250"

EXTRA_TURN_SOURCE_TOKENS = (
    "OneMore",
    "OneMoreCount",
    "UseSkillOneMore",
    "ByTurnOwnerHasPendingOneMore",
)

SPECIAL_SOURCE_MARKERS = (
    "/Activity/",
    "/Rogue/",
    "/GridFight/",
    "/ElationBattle/",
    "/Fate/",
    "/Story/",
    "/Level/",
    "/SubLevelGraph/",
    "TrialPlayer",
)


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    coverage = build_coverage_matrix(discovery, ir)
    static_result = run_static_checks(package_root)

    source_matrix = _extra_turn_source_actionability_matrix(ir, coverage.to_json(), tbgd_root)
    execution_case = _extra_turn_lifecycle_case(ir, rules)
    trust_matrix = _trust_matrix(source_matrix, execution_case)
    checks = {
        "source_discovery": _source_discovery_checks(source_matrix),
        "execution_or_blocker": _execution_checks(source_matrix, execution_case),
        "blocked_sources": _blocked_source_checks(ir, execution_case),
        "trust_matrix": _trust_matrix_checks(trust_matrix),
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
            "selection_policy": {
                "extra_turn_source": (
                    "Source/actionability matrix is derived from Canonical IR queue windows, "
                    "QueueLifecyclePolicyIR, and structured TBGD source tokens; no fixed character/action/hash sample."
                ),
                "execution": "Only executable QueueWindowIR(window_family=extra_turn) may run; absent admission remains blocked.",
            },
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "extra_turn_source_actionability_matrix": source_matrix,
        "extra_turn_lifecycle_case": execution_case,
        "trust_matrix": trust_matrix,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_250.json", result)
    write_json(output_dir / "extra_turn_source_actionability_matrix_v0_250.json", source_matrix)
    write_json(output_dir / "sample_extra_turn_lifecycle_case_v0_250.json", execution_case)
    write_json(output_dir / "trust_matrix_v0_250.json", trust_matrix)
    write_json(output_dir / "coverage_summary_v0_250.json", coverage.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_250 extra-turn lifecycle closure.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _extra_turn_source_actionability_matrix(ir, coverage_json: dict[str, Any], tbgd_root: Path) -> dict[str, Any]:
    windows = tuple(window for window in ir.queue_windows if window.window_family == "extra_turn")
    lifecycle_policies = tuple(policy for policy in ir.queue_lifecycle_policies if policy.window_family == "extra_turn")
    source_policy = _source_policy(lifecycle_policies)
    executable_windows = tuple(window for window in windows if window.coverage_status == "executable")
    raw_scan = _raw_extra_turn_source_scan(tbgd_root)
    rows = {
        "extra_turn_source_discovery": {
            "current_actionability": "fixed_now",
            "semantic_status": "trusted_for_current_scope",
            "evidence": source_policy.to_json() if source_policy is not None else {},
            "blocking_dependency": "",
        },
        "extra_turn_queue_window": {
            "current_actionability": "wait_for_dependency" if not executable_windows else "fixed_now",
            "semantic_status": "blocked" if not executable_windows else "trusted_for_current_scope",
            "blocking_dependency": ""
            if executable_windows
            else _extra_turn_window_blocker(windows),
            "window_count": len(windows),
            "executable_window_count": len(executable_windows),
        },
        "extra_turn_lifecycle_policy": {
            "current_actionability": "wait_for_dependency" if not executable_windows else "fixed_now",
            "semantic_status": "blocked" if not executable_windows else "trusted_for_current_scope",
            "blocking_dependency": ""
            if executable_windows
            else "QueueLifecyclePolicyIR source is discovered, but no executable extra-turn QueueWindowIR can bind it to a queue entry",
            "policy_count": len(lifecycle_policies),
            "status_counts": dict(Counter(policy.coverage_status for policy in lifecycle_policies)),
        },
        "extra_turn_execution": {
            "current_actionability": "wait_for_dependency" if not executable_windows else "fixed_now",
            "semantic_status": "blocked" if not executable_windows else "trusted_for_current_scope",
            "blocking_dependency": ""
            if executable_windows
            else "missing admitted QueueIntentIR/QueueResolutionIR/QueuePriorityIR/QueueWindowIR chain for extra-turn child action",
        },
    }
    queue_coverage = coverage_json.get("action_execution_status", {})
    return {
        "rows": rows,
        "counts": {
            "queue_window_family_counts": queue_coverage.get("queue_windows", {}).get("window_family_counts", {}),
            "queue_lifecycle_policy_status_counts": queue_coverage.get("queue_lifecycle_policies", {}).get("status_counts", {}),
            "raw_source_scan": raw_scan["counts"],
        },
        "source_policy": source_policy.to_json() if source_policy is not None else {},
        "extra_turn_windows": [_window_summary(window) for window in windows[:20]],
        "raw_source_scan": raw_scan,
    }


def _extra_turn_lifecycle_case(ir, rules: RuleBook) -> dict[str, Any]:
    executable_windows = tuple(
        window
        for window in sorted(ir.queue_windows, key=_queue_window_sort_key)
        if window.window_family == "extra_turn" and window.coverage_status == "executable"
    )
    if not executable_windows:
        return {
            "status": "blocked",
            "blocking_dependency": "no executable extra-turn QueueWindowIR in current Canonical IR",
            "checks": {
                "ok": True,
                "no_synthetic_extra_turn": True,
                "blocked_reason_specific": True,
                "no_transition_or_mutation_generated": True,
            },
            "source_audit": {"ok": True, "checked_mutations": 0, "checked_records": 0, "violations": [], "traces": []},
        }
    base_state = _execute_break_setup(rules, _select_break_family_case(ir, rules))["initial_state"]
    return _extra_turn_execution_case(ir, rules, base_state)


def _extra_turn_window_blocker(windows: tuple[QueueWindowIR, ...]) -> str:
    if not windows:
        return "no mainline QueueIntentIR classified as extra_turn"
    reasons = Counter(window.blocked_reason or "extra_turn_window_not_executable" for window in windows)
    reason, count = reasons.most_common(1)[0]
    return f"extra_turn QueueIntentIR discovered but no executable window; dominant_blocker={reason}; count={count}"


def _source_discovery_checks(matrix: dict[str, Any]) -> dict[str, Any]:
    source_policy = matrix.get("source_policy", {})
    lifecycle_policy = source_policy.get("lifecycle_policy", {}) if isinstance(source_policy, dict) else {}
    evidence = source_policy.get("source_basis", {}).get("evidence", {}) if isinstance(source_policy.get("source_basis"), dict) else {}
    checks = {
        "queue_lifecycle_policy_present": bool(source_policy),
        "one_more_lifecycle_source_discovered": source_policy.get("coverage_status") == "discovered_only",
        "one_more_lifetime_admitted": lifecycle_policy.get("remaining_duration") == 1,
        "one_more_life_step_admitted": lifecycle_policy.get("duration_tick_policy") == "ActionPhaseEnd_from_OneMore_LifeStepMoment",
        "enum_or_global_evidence_present": bool(evidence),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _execution_checks(matrix: dict[str, Any], execution_case: dict[str, Any]) -> dict[str, Any]:
    executable_count = int(matrix.get("rows", {}).get("extra_turn_queue_window", {}).get("executable_window_count", 0) or 0)
    if executable_count:
        checks = {
            "executable_window_has_execution": execution_case.get("status") == "executed",
            "execution_checks_pass": bool(execution_case.get("checks", {}).get("ok")),
            "source_audit_pass": bool(execution_case.get("source_audit", {}).get("ok")),
        }
    else:
        checks = {
            "blocked_when_no_executable_window": execution_case.get("status") == "blocked",
            "no_synthetic_extra_turn": bool(execution_case.get("checks", {}).get("no_synthetic_extra_turn")),
            "specific_blocker_present": bool(execution_case.get("blocking_dependency")),
        }
    return {"ok": all(checks.values()), "checks": checks}


def _blocked_source_checks(ir, execution_case: dict[str, Any]) -> dict[str, Any]:
    blocked_or_non_executable = tuple(
        window
        for window in ir.queue_windows
        if window.window_family == "extra_turn" and window.coverage_status != "executable"
    )
    checks = {
        "blocked_or_discovered_extra_turn_window_not_executed": execution_case.get("status") != "executed" or not blocked_or_non_executable,
        "text_only_source_not_executable": all(
            window.coverage_status != "executable"
            for window in ir.queue_windows
            if isinstance(window.window_policy.get("source_basis"), dict)
            and window.window_policy["source_basis"].get("source_basis") == "text_only_queue_window_hint"
        ),
        "source_only_lifecycle_policy_not_executable": all(
            policy.coverage_status != "executable"
            for policy in ir.queue_lifecycle_policies
            if not policy.queue_window_id and policy.window_family == "extra_turn"
        ),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _trust_matrix(matrix: dict[str, Any], execution_case: dict[str, Any]) -> dict[str, Any]:
    execution_trusted = execution_case.get("status") == "executed" and bool(execution_case.get("checks", {}).get("ok"))
    return {
        "extra_turn_source_discovery": {
            "semantic_status": "trusted_for_current_scope",
            "source_audit_applicable": False,
            "remaining_risk": "source discovery only; no runtime mutation is produced by source-only policy",
        },
        "extra_turn_lifecycle_policy": {
            "semantic_status": "trusted_for_current_scope" if execution_trusted else "blocked",
            "blocking_dependency": ""
            if execution_trusted
            else matrix.get("rows", {}).get("extra_turn_lifecycle_policy", {}).get("blocking_dependency", ""),
        },
        "extra_turn_execution": {
            "semantic_status": "trusted_for_current_scope" if execution_trusted else "blocked",
            "blocking_dependency": "" if execution_trusted else execution_case.get("blocking_dependency", ""),
        },
    }


def _trust_matrix_checks(trust_matrix: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "no_needs_fix": all(row.get("semantic_status") != "needs_fix" for row in trust_matrix.values()),
        "blocked_rows_have_dependency": all(
            row.get("semantic_status") != "blocked" or bool(row.get("blocking_dependency"))
            for row in trust_matrix.values()
        ),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _source_policy(policies: tuple[QueueLifecyclePolicyIR, ...]) -> QueueLifecyclePolicyIR | None:
    for policy in policies:
        if policy.queue_lifecycle_policy_id == "queue_lifecycle_policy:extra_turn_source:OneMore":
            return policy
    return policies[0] if policies else None


def _window_summary(window: QueueWindowIR) -> dict[str, Any]:
    return {
        "queue_window_id": window.queue_window_id,
        "queue_intent_id": window.queue_intent_id,
        "queue_kind": window.queue_kind,
        "window_family": window.window_family,
        "coverage_status": window.coverage_status,
        "blocked_reason": window.blocked_reason,
        "source": window.source.to_json(),
        "window_policy": window.window_policy,
    }


def _raw_extra_turn_source_scan(tbgd_root: Path) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    scan_roots = (
        tbgd_root / "Config" / "ConfigAbility" / "Avatar",
        tbgd_root / "Config" / "ConfigAbility" / "Monster",
        tbgd_root / "Config" / "ConfigGlobalModifier",
        tbgd_root / "Config" / "ConfigAbility" / "BattleEventAbility",
        tbgd_root / "Config" / "GlobalConfig",
    )
    for root in scan_roots:
        if not root.exists():
            continue
        paths = [root] if root.is_file() else sorted(root.rglob("*.json"))
        for path in paths:
            relative = path.relative_to(tbgd_root).as_posix()
            text = _read_text(path)
            if not text or not any(token in text for token in EXTRA_TURN_SOURCE_TOKENS):
                continue
            mode = _source_mode(relative)
            counts[mode] += 1
            counts["total"] += 1
            if len(samples) < 40:
                samples.append(
                    {
                        "source_path": relative,
                        "source_mode": mode,
                        "matched_tokens": [token for token in EXTRA_TURN_SOURCE_TOKENS if token in text],
                        "admission_status": "audit_only" if mode != "mainline" else "discovered_only",
                        "blocked_dependency": "raw_token_match_requires_queue_intent_target_priority_action_lifecycle_admission",
                    }
                )
    return {"counts": dict(sorted(counts.items())), "samples": samples}


def _source_mode(relative_path: str) -> str:
    marked = "/" + relative_path
    if any(marker in marked for marker in SPECIAL_SOURCE_MARKERS):
        return "special_or_non_mainline"
    if relative_path.startswith("Config/ConfigAbility/Avatar/") or relative_path.startswith("Config/ConfigAbility/Monster/"):
        return "mainline"
    if relative_path.startswith("Config/ConfigGlobalModifier/") or relative_path.startswith("Config/GlobalConfig/"):
        return "global_mainline_evidence"
    return "audit_only"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _queue_window_sort_key(window: QueueWindowIR) -> tuple[str, str, str]:
    return (window.source.source_path, window.queue_window_id, window.queue_intent_id)


if __name__ == "__main__":
    raise SystemExit(main())
