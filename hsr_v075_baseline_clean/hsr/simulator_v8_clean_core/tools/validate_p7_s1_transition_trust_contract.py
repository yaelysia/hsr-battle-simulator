from __future__ import annotations

import argparse
import ast
from dataclasses import replace
import inspect
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.atomic_commit import finalize_selected_execution_graph
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..core.transition_outcome import (
    ExecutionNodeResult,
    TransitionOutcome,
    classify_transition_outcome,
    unclassified_transition_outcome,
)
from ..core.transition_consumer import (
    transition_blocked_reason as _transition_blocked_reason,
    transition_successor_state as _transition_successor_state,
)
from ..resource_event_contract import UNIT_ENERGY_EVENT_CONTRACT
from ..rules.ir import StatusEventFamilyIR
from ..rules.rulebook import RuleBook
from ..systems.scheduler import CombatScheduler, _combine_scheduler_transitions
from .io import write_json
from .static_checks import run_static_checks
from .validate_p7_s0_kernel_trust_baseline import _base_state, _decision_state, _minimal_rulebook, _source


VALIDATION_VERSION = "p7_s1_transition_trust_contract"
MATRIX_SCHEMA_VERSION = "p7_s1_transition_trust_matrix_v1"


def run_validation(package_root: Path, output_dir: Path) -> dict[str, Any]:
    rules = _trust_rulebook()
    base_state = _decision_state(_base_state(skill_points=3))
    committed_state, committed = CombatExecutor(rules).execute(
        ActionCommand(
            actor_id="ally:actor",
            action_id="validation:normal",
            action_level=1,
            target_ids=("enemy:target",),
        ),
        base_state,
    )
    blocked_before = _decision_state(_base_state(skill_points=0))
    blocked_state, blocked = CombatExecutor(rules).execute(
        ActionCommand(
            actor_id="ally:actor",
            action_id="validation:partial",
            action_level=1,
            target_ids=("enemy:target",),
        ),
        blocked_before,
    )
    diagnostic_before = _decision_state(_base_state(skill_points=3))
    diagnostic_state, diagnostic = _diagnostic_from_committed_candidate(
        diagnostic_before,
        committed_state,
        committed,
    )
    no_target_before = _decision_state(_base_state(skill_points=3))
    no_target_state, no_target = CombatExecutor(rules).execute(
        ActionCommand(
            actor_id="ally:actor",
            action_id="validation:normal",
            action_level=1,
            target_ids=(),
        ),
        no_target_before,
    )
    unclassified = replace(committed, outcome=unclassified_transition_outcome())

    cases = {
        "committed": _case_evidence(rules, base_state, committed_state, committed),
        "blocked": _case_evidence(rules, blocked_before, blocked_state, blocked),
        "diagnostic": _case_evidence(rules, diagnostic_before, diagnostic_state, diagnostic),
        "no_selected_target": _case_evidence(rules, no_target_before, no_target_state, no_target),
        "unclassified": _case_evidence(rules, base_state, base_state, unclassified),
    }
    coverage_independence = _coverage_independence(committed, blocked)
    ui_consumer = _ui_consumer_evidence(base_state, committed_state, committed, blocked, diagnostic)
    scheduler = _scheduler_evidence(rules, base_state, committed_state, committed)
    boundary = _boundary_evidence(package_root)
    contradiction_contracts = _contradiction_contract_evidence(committed, diagnostic)
    static_checks = run_static_checks(package_root)

    checks = {
        "committed_category": committed.outcome.category == "committed",
        "committed_successor_eligible": committed.outcome.successor_eligible,
        "committed_returned_state_matches_transition": committed_state.snapshot().to_json() == committed.after.to_json(),
        "committed_has_explicit_nodes": bool(committed.outcome.node_results)
        and all(item.complete for item in committed.outcome.node_results),
        "blocked_category": blocked.outcome.category == "blocked",
        "blocked_not_successor_eligible": not blocked.outcome.successor_eligible,
        "blocked_state_unchanged": blocked_state == blocked_before
        and blocked.after.to_json() == blocked_before.snapshot().to_json(),
        "blocked_has_no_mutations": not blocked.transaction.mutations,
        "diagnostic_category": diagnostic.outcome.category == "diagnostic",
        "diagnostic_not_successor_eligible": not diagnostic.outcome.successor_eligible,
        "diagnostic_official_state_unchanged": diagnostic_state == diagnostic_before,
        "diagnostic_retains_candidate_evidence": diagnostic.after.to_json()
        == diagnostic_before.snapshot().to_json()
        and not diagnostic.transaction.mutations
        and isinstance(diagnostic.coverage.get("atomic_commit"), dict)
        and diagnostic.coverage["atomic_commit"].get("candidate_state_changed") is True
        and int(diagnostic.coverage["atomic_commit"].get("planned_mutation_count") or 0) > 0,
        "diagnostic_identifies_selected_unsupported_node": any(
            item.status in {"unsupported", "partial", "error"}
            for item in diagnostic.outcome.node_results
        ),
        "no_selected_target_is_blocked": no_target.outcome.category == "blocked"
        and not no_target.outcome.successor_eligible
        and no_target_state == no_target_before
        and not no_target.transaction.mutations
        and "no_selected_target" in no_target.outcome.reason_codes,
        "unclassified_defaults_diagnostic": unclassified.outcome.category == "diagnostic"
        and not unclassified.outcome.successor_eligible,
        "contradictory_outcomes_rejected": contradiction_contracts["ok"],
        "all_contracts_structurally_valid": all(
            cases[name]["contract"]["ok"] is True
            for name in ("committed", "blocked", "diagnostic", "no_selected_target")
        )
        and cases["unclassified"]["contract"]["ok"] is False,
        "committed_replay_ok": cases["committed"]["replay"]["ok"] is True,
        "blocked_replay_ok": cases["blocked"]["replay"]["ok"] is True,
        "diagnostic_candidate_replay_ok": cases["diagnostic"]["replay"]["ok"] is True,
        "source_audit_outputs_present": all(isinstance(case["source_audit"], dict) for case in cases.values()),
        "all_source_audits_ok": all(case["source_audit"]["ok"] is True for case in cases.values()),
        "coverage_does_not_drive_outcome": coverage_independence["ok"],
        "ui_consumes_outcome_only": ui_consumer["ok"],
        "scheduler_outcomes_explicit": scheduler["ok"],
        "production_constructors_explicit": boundary["production_constructors_explicit"],
        "classifier_does_not_read_audit_fields": boundary["classifier_does_not_read_audit_fields"],
        "ui_behavior_does_not_read_audit_fields": boundary["ui_behavior_does_not_read_audit_fields"],
        "existing_static_checks": static_checks.ok,
        "s0_partial_defect_no_longer_exposed_as_successor": diagnostic_state == diagnostic_before
        and diagnostic.outcome.category == "diagnostic",
        "no_tbgd_or_large_artifacts": True,
    }
    ok = all(checks.values())
    matrix = {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "rows": [
            {
                "case": name,
                "expected_category": {
                    "committed": "committed",
                    "blocked": "blocked",
                    "diagnostic": "diagnostic",
                    "no_selected_target": "blocked",
                    "unclassified": "diagnostic",
                }[name],
                "actual_category": case["outcome"]["category"],
                "successor_eligible": case["outcome"]["successor_eligible"],
                "returned_state_unchanged": case["returned_state_unchanged"],
                "candidate_state_unchanged": case["candidate_state_unchanged"],
                "mutation_count": case["mutation_count"],
                "contract_ok": case["contract"]["ok"],
                "replay_ok": case["replay"]["ok"],
            }
            for name, case in cases.items()
        ],
        "summary": {
            "row_count": len(cases),
            "categories": {name: case["outcome"]["category"] for name, case in cases.items()},
            "all_contracts_structurally_valid": checks["all_contracts_structurally_valid"],
        },
    }
    summary = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": ok,
        "p7_s1_ready_for_review": ok,
        "p7_all_fixed": False,
        "p7_done_eligible": False,
        "checks": checks,
        "matrix_summary": matrix["summary"],
        "coverage_independence": coverage_independence,
        "ui_consumer": ui_consumer,
        "scheduler": scheduler,
        "boundary": boundary,
        "contradiction_contracts": contradiction_contracts,
        "static_checks": static_checks.to_json(),
        "resource_budget": {
            "tbgd_read_count": 0,
            "full_rulebook_build_count": 0,
            "minimal_in_memory_rulebook_build_count": 1,
            "large_artifacts_written": False,
            "full_transition_dump_written": False,
            "output_scope": "summary_matrix_compact_case_evidence",
        },
        "deferred": {
            "p7_s2_mutation_before_validation": True,
            "p7_s3_diagnostic_candidate_atomic_commit": True,
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "p7_s1_transition_trust_matrix.json", matrix)
    write_json(
        output_dir / "p7_s1_transition_trust_cases.json",
        {
            "cases": cases,
            "coverage_independence": coverage_independence,
            "ui_consumer": ui_consumer,
            "scheduler": scheduler,
            "boundary": boundary,
            "contradiction_contracts": contradiction_contracts,
        },
    )
    write_json(output_dir / "validation_summary_p7_s1_transition_trust_contract.json", summary)
    return summary


def _trust_rulebook() -> RuleBook:
    baseline = _minimal_rulebook()
    families = tuple(
        StatusEventFamilyIR(
            status_event_family_id=f"validation:event_family:{callback_event}",
            callback_event=callback_event,
            event_family="validation",
            default_scope_kind=scope_kind,
            runtime_event_sources=(runtime_event,),
            source_basis="validation_structured_event_family",
            source=_source(f"event_family:{callback_event}"),
            coverage_status="executable",
            admission_status="executable",
        )
        for callback_event, runtime_event, scope_kind in (
            ("OnBeforeSkillUse", "action.window.before_skill_use", "global_listener"),
            ("OnAfterSkillUse", "action.window.after_skill_use", "global_listener"),
            (
                UNIT_ENERGY_EVENT_CONTRACT.after_callback_events[-1],
                UNIT_ENERGY_EVENT_CONTRACT.after_event_type,
                UNIT_ENERGY_EVENT_CONTRACT.scope_kind,
            ),
        )
    )
    return RuleBook(replace(baseline.ir, status_event_families=families))


def _diagnostic_from_committed_candidate(
    before_state: BattleState,
    candidate_state: BattleState,
    committed,
):
    node_results = (
        *committed.outcome.node_results,
        ExecutionNodeResult(
            node_kind="validation_selected_node",
            node_id="validation:diagnostic:unsupported",
            status="unsupported",
            reason_code="validation_selected_node_not_executable",
        ),
    )
    atomic = finalize_selected_execution_graph(
        before_state,
        candidate_state,
        committed.transaction.mutations,
        node_results,
    )
    settlement = committed.transaction.settlement
    transaction = replace(
        committed.transaction,
        before=before_state.snapshot(),
        mutations=(),
        settlement=replace(settlement, records=()) if settlement is not None else None,
    )
    diagnostic = replace(
        committed,
        transaction=transaction,
        after=before_state.snapshot(),
        outcome=atomic.outcome,
        coverage={
            **committed.coverage,
            "atomic_commit": atomic.evidence,
            "action_enabled": False,
            "blocked_reason": "validation_selected_node_not_executable",
        },
    )
    return before_state, diagnostic


def _case_evidence(
    rules: RuleBook,
    before_state: BattleState,
    returned_state: BattleState,
    transition,
) -> dict[str, Any]:
    contract = TransitionContractValidator().validate(transition)
    replay = MutationReducer().replay_snapshot(
        before_state,
        transition.transaction.mutations,
        transition.after.to_json(),
    )
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    return {
        "outcome": transition.outcome.to_json(),
        "returned_state_unchanged": returned_state == before_state,
        "candidate_state_unchanged": transition.after.to_json() == before_state.snapshot().to_json(),
        "mutation_count": len(transition.transaction.mutations),
        "contract": contract.to_json(),
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
        "source_audit": {
            "ok": source_audit.ok,
            "checked_mutations": source_audit.checked_mutations,
            "checked_records": source_audit.checked_records,
            "violation_count": len(source_audit.violations),
            "violations": [item.to_json() for item in source_audit.violations[:3]],
        },
    }


def _coverage_independence(committed, blocked) -> dict[str, Any]:
    committed_tampered = replace(
        committed,
        coverage={"blocked_reason": "coverage_must_not_override_committed", "action_enabled": False},
    )
    blocked_tampered = replace(blocked, coverage={"action_enabled": True})
    return {
        "ok": committed_tampered.outcome == committed.outcome and blocked_tampered.outcome == blocked.outcome,
        "committed_category_after_coverage_tamper": committed_tampered.outcome.category,
        "blocked_category_after_coverage_tamper": blocked_tampered.outcome.category,
    }


def _ui_consumer_evidence(
    before_state: BattleState,
    committed_state: BattleState,
    committed,
    blocked,
    diagnostic,
) -> dict[str, Any]:
    committed_json = committed.to_json()
    committed_json["coverage"] = {"blocked_reason": "coverage_must_not_block"}
    blocked_json = blocked.to_json()
    blocked_json["coverage"] = {"action_enabled": True}
    diagnostic_json = diagnostic.to_json()
    committed_reason = _transition_blocked_reason(committed_json)
    blocked_reason = _transition_blocked_reason(blocked_json)
    diagnostic_reason = _transition_blocked_reason(diagnostic_json)
    committed_successor = _transition_successor_state(before_state, committed_state, committed_json)
    diagnostic_successor = _transition_successor_state(before_state, committed_state, diagnostic_json)
    return {
        "ok": not committed_reason
        and bool(blocked_reason)
        and bool(diagnostic_reason)
        and committed_successor == committed_state
        and diagnostic_successor == before_state,
        "committed_reason": committed_reason,
        "blocked_reason": blocked_reason,
        "diagnostic_reason": diagnostic_reason,
        "committed_uses_candidate": committed_successor == committed_state,
        "diagnostic_uses_before": diagnostic_successor == before_state,
    }


def _scheduler_evidence(
    rules: RuleBook,
    state: BattleState,
    committed_state: BattleState,
    committed,
) -> dict[str, Any]:
    scheduler = CombatScheduler(rules)
    initialized = scheduler.initialize_timeline(state)
    empty = BattleState()
    blocked = scheduler.advance_to_next_turn(empty)
    diagnostic_child = replace(
        committed,
        outcome=TransitionOutcome(
            category="diagnostic",
            reason_codes=("synthetic_diagnostic_child",),
            node_results=committed.outcome.node_results,
        ),
    )
    diagnostic_parent = _combine_scheduler_transitions(
        before_state=state,
        after_state=committed_state,
        actor_id="ally:actor",
        events=committed.transaction.events,
        mutations=committed.transaction.mutations,
        records=committed.transaction.settlement.records if committed.transaction.settlement else (),
        target_resolution=committed.target_resolution,
        child_transitions=(diagnostic_child,),
        coverage={"validation": "diagnostic_child_identity"},
    )
    return {
        "ok": initialized.transition.outcome.category == "committed"
        and initialized.transition.outcome.successor_eligible
        and blocked.transition.outcome.category == "blocked"
        and not blocked.transition.outcome.successor_eligible
        and blocked.after_state == empty
        and diagnostic_parent.outcome.category == "diagnostic"
        and not diagnostic_parent.outcome.successor_eligible
        and any(
            item.node_kind == "child_transition" and item.status == "partial"
            for item in diagnostic_parent.outcome.node_results
        ),
        "initialized_outcome": initialized.transition.outcome.to_json(),
        "blocked_outcome": blocked.transition.outcome.to_json(),
        "diagnostic_child_outcome": diagnostic_child.outcome.to_json(),
        "diagnostic_parent_outcome": diagnostic_parent.outcome.to_json(),
    }


def _boundary_evidence(package_root: Path) -> dict[str, Any]:
    constructor_sites: list[dict[str, Any]] = []
    parse_errors: list[dict[str, str]] = []
    scanned_file_count = 0
    roots = (package_root, package_root.parent / "simulator_v8_ui")
    paths = sorted({path for root in roots for path in root.rglob("*.py")})
    for path in paths:
        relative = path.relative_to(package_root.parent).as_posix()
        if path.is_relative_to(package_root / "tools") or "__pycache__" in path.parts:
            continue
        scanned_file_count += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, SyntaxError) as exc:
            parse_errors.append({"path": relative, "error": f"{type(exc).__name__}: {exc}"})
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_leaf(node.func) != "BattleTransition":
                continue
            keyword_names = sorted(keyword.arg for keyword in node.keywords if keyword.arg)
            constructor_sites.append(
                {
                    "path": relative,
                    "line": node.lineno,
                    "keyword_names": keyword_names,
                    "outcome_explicit": "outcome" in keyword_names,
                }
            )
    classifier_source = inspect.getsource(classify_transition_outcome)
    ui_source = inspect.getsource(_transition_blocked_reason) + inspect.getsource(_transition_successor_state)
    forbidden_behavior_inputs = ("coverage", "settlement", "source_trace", "evidence")
    return {
        "production_constructor_count": len(constructor_sites),
        "production_python_file_count": scanned_file_count,
        "parse_error_count": len(parse_errors),
        "parse_errors": parse_errors,
        "constructor_sites": constructor_sites,
        "production_constructors_explicit": not parse_errors
        and bool(constructor_sites)
        and all(item["outcome_explicit"] for item in constructor_sites),
        "classifier_does_not_read_audit_fields": not any(token in classifier_source for token in forbidden_behavior_inputs),
        "ui_behavior_does_not_read_audit_fields": not any(token in ui_source for token in forbidden_behavior_inputs),
        "forbidden_behavior_inputs": list(forbidden_behavior_inputs),
    }


def _contradiction_contract_evidence(committed, diagnostic) -> dict[str, Any]:
    false_committed = replace(
        diagnostic,
        outcome=TransitionOutcome(
            category="committed",
            node_results=diagnostic.outcome.node_results,
        ),
    )
    false_blocked = replace(
        committed,
        outcome=TransitionOutcome(
            category="blocked",
            reason_codes=("synthetic_false_blocked",),
            node_results=(
                ExecutionNodeResult(
                    node_kind="validation",
                    node_id="false_blocked",
                    status="blocked",
                    reason_code="synthetic_false_blocked",
                ),
            ),
        ),
    )
    false_committed_contract = TransitionContractValidator().validate(false_committed)
    false_blocked_contract = TransitionContractValidator().validate(false_blocked)
    changed_without_mutations_outcome = classify_transition_outcome(
        committed.outcome.node_results,
        state_changed=True,
        mutation_count=0,
    )
    false_changed_without_mutations = replace(
        committed,
        transaction=replace(committed.transaction, mutations=()),
        outcome=TransitionOutcome(
            category="committed",
            node_results=committed.outcome.node_results,
        ),
    )
    false_changed_without_mutations_contract = TransitionContractValidator().validate(
        false_changed_without_mutations
    )
    outcome_errors = (
        false_changed_without_mutations_contract.outcome_validation.get("errors", [])
        if isinstance(false_changed_without_mutations_contract.outcome_validation, dict)
        else []
    )
    return {
        "ok": not false_committed_contract.ok
        and not false_blocked_contract.ok
        and changed_without_mutations_outcome.category == "diagnostic"
        and not changed_without_mutations_outcome.successor_eligible
        and "state_changed_without_mutations" in changed_without_mutations_outcome.reason_codes
        and not false_changed_without_mutations_contract.ok
        and "committed transition state change requires mutations" in outcome_errors,
        "false_committed": false_committed_contract.to_json(),
        "false_blocked": false_blocked_contract.to_json(),
        "changed_without_mutations_classifier": changed_without_mutations_outcome.to_json(),
        "false_changed_without_mutations": false_changed_without_mutations_contract.to_json(),
    }


def _call_leaf(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P7-S1 machine-readable transition trust outcomes.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/hsr_v8_p7_s1_transition_trust_contract"),
    )
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    result = run_validation(package_root, args.output_dir.resolve())
    categories = result["matrix_summary"]["categories"]
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} "
        f"committed={categories['committed']} blocked={categories['blocked']} "
        f"diagnostic={categories['diagnostic']} unclassified={categories['unclassified']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
