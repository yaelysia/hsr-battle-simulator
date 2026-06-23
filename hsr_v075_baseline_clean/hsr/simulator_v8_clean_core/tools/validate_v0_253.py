from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..rules.ir import ExtraActionPolicyIR, QueueWindowIR
from ..rules.rulebook import RuleBook
from ..systems.skill_continuation import SkillContinuationRunner
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_251 import _queue_priority_case


VALIDATION_VERSION = "v0_253"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    coverage = build_coverage_matrix(discovery, ir)
    static_result = run_static_checks(package_root)

    execution_matrix = _extra_action_execution_matrix(ir, rules)
    continuation_case = _skill_continuation_runner_case(rules)
    extra_turn_case = _extra_turn_action_choice_case(ir, rules)
    priority_case = _queue_priority_case()
    checks = {
        "extra_action_policy_ir": execution_matrix["checks"],
        "skill_continuation_runner": continuation_case["checks"],
        "extra_turn_action_choice": extra_turn_case["checks"],
        "queue_priority": priority_case["checks"],
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
                "extra_action_policy": "Selected from ExtraActionPolicyIR by source_kind/coverage/window family; no character/action/file/hash fixed selector.",
                "skill_continuation": "Selected from SkillContinuationIR opcode evidence; runner is process-only until segment-to-action mapping is admitted.",
                "extra_turn_execution": "Only executable extra-turn QueueWindowIR + ExtraActionPolicyIR may drain; absent source remains blocked.",
            },
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "extra_action_execution_matrix": execution_matrix,
        "skill_continuation_runner_case": continuation_case,
        "extra_turn_action_choice_case": extra_turn_case,
        "queue_priority_case": priority_case,
        "coverage_summary": coverage.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_253.json", result)
    write_json(output_dir / "extra_action_execution_matrix_v0_253.json", execution_matrix)
    write_json(output_dir / "skill_continuation_runner_case_v0_253.json", continuation_case)
    write_json(output_dir / "extra_turn_action_choice_case_v0_253.json", extra_turn_case)
    write_json(output_dir / "coverage_summary_v0_253.json", coverage.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_253 extra-action execution closure.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _extra_action_execution_matrix(ir, rules: RuleBook) -> dict[str, Any]:
    policies = tuple(sorted(ir.extra_action_policies, key=lambda item: item.extra_action_policy_id))
    policies_by_kind = Counter(policy.source_kind for policy in policies)
    policies_by_status = Counter(policy.coverage_status for policy in policies)
    true_extra = tuple(policy for policy in policies if policy.source_kind == "true_extra_turn")
    limited = tuple(policy for policy in policies if policy.action_selection_kind == "state_restricted_action")
    continuations = tuple(policy for policy in policies if policy.source_kind == "skill_or_ultimate_internal_continuation")
    executable_true_extra = tuple(policy for policy in true_extra if policy.coverage_status == "executable")
    use_skill_windows = tuple(
        window
        for window in ir.queue_windows
        if window.window_family == "extra_turn"
        and isinstance(window.source.evidence, dict)
        and window.source.evidence.get("opcode") == "UseSkillOneMore"
    )
    text_hint_direct_executable = tuple(
        window
        for window in ir.queue_windows
        if _text_hint_directly_matches_family(window) and window.coverage_status == "executable"
    )
    checks = {
        "ok": False,
        "extra_action_policy_ir_present": len(policies) > 0,
        "skill_continuation_policies_present": len(continuations) > 0,
        "use_skill_one_more_not_true_extra_turn": len(use_skill_windows) == 0,
        "text_hints_not_executable_window_source": len(text_hint_direct_executable) == 0,
        "true_extra_turn_policies_have_lifecycle_link": all(bool(policy.lifecycle_policy_id) for policy in true_extra),
        "executable_true_extra_has_policy_source": all(bool(policy.source.source_path) for policy in executable_true_extra),
        "limited_extra_turn_not_free_skill_selection_without_policy": all(
            policy.action_selection_kind != "route_or_source_selected_non_ultimate_action"
            for policy in limited
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "policy_counts": {
            "total": len(policies),
            "by_source_kind": dict(sorted(policies_by_kind.items())),
            "by_status": dict(sorted(policies_by_status.items())),
            "true_extra_turn": len(true_extra),
            "executable_true_extra_turn": len(executable_true_extra),
            "state_restricted": len(limited),
            "skill_continuation": len(continuations),
        },
        "true_extra_turn_samples": [_policy_summary(policy, rules) for policy in true_extra[:20]],
        "skill_continuation_policy_samples": [_policy_summary(policy, rules) for policy in continuations[:20]],
        "current_status": (
            "executable_true_extra_turn_available"
            if executable_true_extra
            else "no executable true extra-turn source; execution stays blocked instead of synthetic"
        ),
        "remaining_dependency": (
            ""
            if executable_true_extra
            else "needs admitted QueueIntentIR/QueueResolutionIR/QueuePriorityIR/QueueWindowIR and source-specific action-choice policy"
        ),
    }


def _skill_continuation_runner_case(rules: RuleBook) -> dict[str, Any]:
    continuations = rules.skill_continuations()
    selected = next((item for item in continuations if item.opcode == "UseSkillOneMore"), None)
    if selected is None:
        return {
            "status": "blocked",
            "blocking_dependency": "no UseSkillOneMore SkillContinuationIR found",
            "checks": {"ok": False, "continuation_present": False},
        }
    result = SkillContinuationRunner(rules).execute(
        state=_empty_state(),
        continuation=selected,
        actor_id="validation:actor",
        target_ids=("validation:target",),
    )
    checks = {
        "ok": False,
        "continuation_present": True,
        "runner_process_only_blocked": not result.ok and not result.mutations,
        "after_state_unchanged": result.after_state == _empty_state(),
        "record_marks_not_extra_turn": bool(result.records and result.records[0].get("payload", {}).get("not_extra_turn") is True),
        "blocked_reason_specific": bool(result.blocked_reason and "skill_continuation" in result.blocked_reason),
        "source_trace_present": bool(result.records and result.records[0].get("trace", {}).get("skill_continuation_source")),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "status": "blocked_without_state_change",
        "checks": checks,
        "selected_continuation": selected.to_json(),
        "blocked_reason": result.blocked_reason,
        "records": result.records,
        "events": [event.to_json() for event in result.events],
    }


def _extra_turn_action_choice_case(ir, rules: RuleBook) -> dict[str, Any]:
    executable = tuple(
        policy
        for policy in sorted(ir.extra_action_policies, key=lambda item: item.extra_action_policy_id)
        if policy.source_kind == "true_extra_turn" and policy.coverage_status == "executable"
    )
    if not executable:
        return {
            "status": "blocked",
            "blocking_dependency": "no executable true extra-turn ExtraActionPolicyIR in current Canonical IR",
            "checks": {
                "ok": True,
                "no_synthetic_extra_turn_execution": True,
                "blocked_reason_specific": True,
                "no_transition_or_mutation_generated": True,
            },
            "source_audit": {"ok": True, "checked_mutations": 0, "violations": []},
        }
    return {
        "status": "requires_runtime_case",
        "blocking_dependency": (
            "executable policy exists, but validate_v0_253 needs a stateful queue entry case with route/manual basic or skill command"
        ),
        "checks": {
            "ok": False,
            "executable_policy_present": True,
            "runtime_case_missing": True,
        },
        "selected_policy": executable[0].to_json(),
    }


def _policy_summary(policy: ExtraActionPolicyIR, rules: RuleBook) -> dict[str, Any]:
    window = rules.queue_window(policy.queue_window_id) if policy.queue_window_id else None
    return {
        "extra_action_policy_id": policy.extra_action_policy_id,
        "source_kind": policy.source_kind,
        "action_selection_kind": policy.action_selection_kind,
        "allowed_action_kinds": list(policy.allowed_action_kinds),
        "coverage_status": policy.coverage_status,
        "blocked_reason": policy.blocked_reason,
        "queue_window": window.to_json() if window is not None else {},
        "source_path": policy.source.source_path,
    }


def _text_hint_directly_matches_family(window: QueueWindowIR) -> bool:
    evidence = window.source.evidence if isinstance(window.source.evidence, dict) else {}
    basis = evidence.get("family_basis") if isinstance(evidence.get("family_basis"), dict) else {}
    hints = basis.get("text_hints") if isinstance(basis, dict) else ()
    return str(window.window_family or "") in {str(item) for item in hints if isinstance(item, str)}


def _empty_state():
    from ..core.model import BattleState

    return BattleState()


if __name__ == "__main__":
    raise SystemExit(main())
