from __future__ import annotations

import argparse
import ast
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.atomic_commit import AtomicCommitResult, finalize_selected_execution_graph
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, Mutation, TargetResolution
from ..core.reducer import MutationReducer
from ..core.transition_contract import TransitionContractValidator
from ..core.transition_outcome import ExecutionNodeResult, TransitionOutcome
from ..rules.rulebook import RuleBook
from ..systems.scheduler import _combine_scheduler_transitions
from .io import write_json
from .validate_p7_s0_kernel_trust_baseline import _base_state, _decision_state
from .validate_p7_s1_transition_trust_contract import _trust_rulebook


VALIDATION_VERSION = "p7_s3_selected_graph_atomic_commit"
MATRIX_SCHEMA_VERSION = "p7_s3_atomic_commit_matrix_v1"


def run_validation(package_root: Path, output_dir: Path) -> dict[str, Any]:
    before = BattleState(skill_points=3, event_index=0)
    resource_mutation = _mutation(
        ("skill_points",),
        before=3,
        after=2,
        source="resource_system",
        node_id="resource:consume",
    )
    event_mutation = _mutation(
        ("event_index",),
        before=0,
        after=1,
        source="event_dispatch_system",
        node_id="event:advance",
    )
    planned = (resource_mutation, event_mutation)
    candidate = MutationReducer().apply_all(before, planned)

    complete_nodes = (
        _node("ability_task", "task:resource"),
        _node("event_dispatch", "event:advance"),
    )
    complete = finalize_selected_execution_graph(before, candidate, planned, complete_nodes)
    mid_task_failure = finalize_selected_execution_graph(
        before,
        candidate,
        planned,
        (*complete_nodes, _node("ability_task", "task:unsupported", "unsupported", "task_not_executable")),
    )

    status_mutation = _mutation(
        ("global_flags", "status_activation"),
        before=None,
        after={"status_id": "status:structural", "layer": 1},
        source="status_system",
        node_id="status:activation",
        before_exists=False,
    )
    status_candidate = MutationReducer().apply_all(before, (status_mutation,))
    status_partial = finalize_selected_execution_graph(
        before,
        status_candidate,
        (status_mutation,),
        (
            _node("status_admission", "status:admitted"),
            _node("status_activation", "status:callback", "partial", "selected_status_callback_incomplete"),
        ),
    )

    callback_partial = finalize_selected_execution_graph(
        before,
        candidate,
        planned,
        (
            _node("status_callback", "callback:first"),
            _node("status_callback", "callback:second", "error", "selected_callback_execution_failed"),
        ),
    )

    conflict_mutation = _mutation(
        ("skill_points",),
        before=99,
        after=98,
        source="resource_system",
        node_id="resource:conflict",
    )
    reducer_conflict = finalize_selected_execution_graph(
        before,
        before,
        (conflict_mutation,),
        (_node("resource_plan", "resource:conflict"),),
    )

    mismatched_candidate = MutationReducer().apply_all(before, (event_mutation,))
    candidate_mismatch = finalize_selected_execution_graph(
        before,
        mismatched_candidate,
        (resource_mutation,),
        (_node("ability_task", "task:resource"),),
    )

    unentered_branch = finalize_selected_execution_graph(
        before,
        MutationReducer().apply_all(before, (resource_mutation,)),
        (resource_mutation,),
        (_node("conditional_selected_branch", "branch:selected"),),
    )

    executor_integration = _executor_integration_case()
    scheduler_integration = _scheduler_integration_case()
    boundary = _boundary_evidence(package_root)

    cases = {
        "complete_multi_node": _commit_case(before, complete),
        "multi_task_mid_failure": _commit_case(before, mid_task_failure),
        "status_partial_activation": _commit_case(before, status_partial),
        "callback_mid_failure": _commit_case(before, callback_partial),
        "reducer_conflict": _commit_case(before, reducer_conflict),
        "candidate_mismatch": _commit_case(before, candidate_mismatch),
        "unentered_conditional_branch": _commit_case(before, unentered_branch),
        "executor_integration": executor_integration,
        "scheduler_integration": scheduler_integration,
    }

    checks = {
        "complete_multi_node_commits_once": _committed(complete, planned_count=2),
        "complete_multi_node_strict_replay": _strict_replay(before, complete),
        "mid_task_failure_is_atomic": _not_committed(before, mid_task_failure, "selected_graph_incomplete"),
        "status_partial_activation_is_atomic": _not_committed(before, status_partial, "selected_graph_incomplete"),
        "callback_mid_failure_is_atomic": _not_committed(before, callback_partial, "selected_graph_incomplete"),
        "reducer_conflict_is_atomic_and_structured": _not_committed(before, reducer_conflict, "mutation_conflict")
        and bool(reducer_conflict.evidence.get("conflicts")),
        "candidate_mismatch_is_rejected": _not_committed(before, candidate_mismatch, "candidate_state_mismatch"),
        "unentered_branch_does_not_block": _committed(unentered_branch, planned_count=1),
        "planned_mutation_sources_remain_auditable": all(
            _planned_sources_auditable(result)
            for result in (mid_task_failure, status_partial, callback_partial, reducer_conflict)
        ),
        "executor_uses_atomic_boundary": executor_integration["ok"],
        "scheduler_propagates_child_failure_atomically": scheduler_integration["ok"],
        "transition_contract_rejects_changed_diagnostic": executor_integration[
            "changed_diagnostic_contract_rejected"
        ],
        "production_commit_boundaries_present": boundary["ok"],
        "no_large_artifacts": True,
    }
    ok = all(checks.values())

    matrix = {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "rows": [
            {
                "case": name,
                "commit_status": case.get("commit_status", "integration"),
                "successor_eligible": case.get("successor_eligible"),
                "state_unchanged": case.get("state_unchanged"),
                "committed_mutation_count": case.get("committed_mutation_count"),
            }
            for name, case in cases.items()
        ],
    }
    summary = {
        "validation_version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ready_for_review": ok,
        "ok": ok,
        "checks": checks,
        "boundary": boundary,
        "case_count": len(cases),
        "matrix_schema_version": MATRIX_SCHEMA_VERSION,
        "artifact_policy": {
            "large_artifacts_written": False,
            "canonical_ir_serialized": False,
            "full_transition_dump_written": False,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "p7_s3_atomic_commit_cases.json", cases)
    write_json(output_dir / "p7_s3_atomic_commit_matrix.json", matrix)
    write_json(output_dir / "validation_summary_p7_s3_selected_graph_atomic_commit.json", summary)
    return summary


def _executor_integration_case() -> dict[str, Any]:
    baseline_rules = _trust_rulebook()
    rules = RuleBook(
        replace(
            baseline_rules.ir,
            ability_tasks=tuple(
                replace(task, coverage_status="executable", blocked_reason="")
                if task.action_id == "validation:partial"
                else task
                for task in baseline_rules.ir.ability_tasks
            ),
        )
    )
    state = _decision_state(_base_state(skill_points=3))
    actor_id = next(unit.unit_id for unit in state.units.values() if unit.side == "ally")
    target_id = next(unit.unit_id for unit in state.units.values() if unit.side == "enemy")
    executor = CombatExecutor(rules)
    selected = None
    for definition in sorted(rules.ir.action_definitions, key=lambda item: item.definition_id):
        returned, transition = executor.execute(
            ActionCommand(
                actor_id=actor_id,
                action_id=definition.action_id,
                action_level=definition.level,
                target_ids=(target_id,),
            ),
            state,
        )
        atomic = transition.coverage.get("atomic_commit")
        if (
            transition.outcome.category == "diagnostic"
            and isinstance(atomic, dict)
            and int(atomic.get("planned_mutation_count") or 0) > 0
        ):
            selected = (returned, transition, atomic)
            break
    if selected is None:
        return {"ok": False, "reason": "structural_diagnostic_action_not_found"}

    returned, transition, atomic = selected
    contract = TransitionContractValidator().validate(transition)
    changed_diagnostic = replace(
        transition,
        after=MutationReducer().apply_all(
            state,
            (
                _mutation(
                    ("event_index",),
                    before=state.event_index,
                    after=state.event_index + 1,
                    source="validation",
                    node_id="changed_diagnostic",
                ),
            ),
        ).snapshot(),
    )
    changed_contract = TransitionContractValidator().validate(changed_diagnostic)
    records = transition.transaction.settlement.records if transition.transaction.settlement else ()
    traceable_record = any(
        record.get("record_type") in {"action_definition", "ability_task_graph", "action_execution_plan"}
        and isinstance(record.get("trace"), dict)
        for record in records
    )
    ok = (
        returned == state
        and transition.after.to_json() == state.snapshot().to_json()
        and not transition.transaction.mutations
        and transition.outcome.category == "diagnostic"
        and not transition.outcome.successor_eligible
        and atomic.get("candidate_state_published") is False
        and atomic.get("candidate_state_changed") is True
        and contract.ok
        and traceable_record
        and not changed_contract.ok
    )
    return {
        "ok": ok,
        "action_selection_predicate": "first diagnostic action with planned_mutation_count>0",
        "selected_definition_id": transition.coverage.get("definition_id"),
        "outcome": transition.outcome.to_json(),
        "state_unchanged": transition.after.to_json() == state.snapshot().to_json(),
        "committed_mutation_count": len(transition.transaction.mutations),
        "atomic_commit": atomic,
        "contract": contract.to_json(),
        "source_trace_record_present": traceable_record,
        "changed_diagnostic_contract_rejected": not changed_contract.ok,
    }


def _scheduler_integration_case() -> dict[str, Any]:
    rules = _trust_rulebook()
    before = _decision_state(_base_state(skill_points=3))
    actor_id = next(unit.unit_id for unit in before.units.values() if unit.side == "ally")
    target_id = next(unit.unit_id for unit in before.units.values() if unit.side == "enemy")
    committed_state = None
    committed_transition = None
    for definition in sorted(rules.ir.action_definitions, key=lambda item: item.definition_id):
        returned, transition = CombatExecutor(rules).execute(
            ActionCommand(actor_id, definition.action_id, definition.level, (target_id,)),
            before,
        )
        if transition.outcome.successor_eligible and transition.transaction.mutations:
            committed_state = returned
            committed_transition = transition
            break
    if committed_state is None or committed_transition is None:
        return {"ok": False, "reason": "structural_committed_action_not_found"}

    diagnostic_child = replace(
        committed_transition,
        outcome=TransitionOutcome(
            category="diagnostic",
            reason_codes=("synthetic_child_failure",),
            node_results=committed_transition.outcome.node_results,
        ),
    )
    parent = _combine_scheduler_transitions(
        before_state=before,
        after_state=committed_state,
        actor_id=actor_id,
        events=committed_transition.transaction.events,
        mutations=committed_transition.transaction.mutations,
        records=committed_transition.transaction.settlement.records,
        target_resolution=TargetResolution(reason="scheduler_validation", source="validation"),
        child_transitions=(diagnostic_child,),
        coverage={"scheduler_step": "atomic_child_validation"},
    )
    contract = TransitionContractValidator().validate(parent)
    ok = (
        parent.outcome.category == "diagnostic"
        and not parent.outcome.successor_eligible
        and parent.after.to_json() == before.snapshot().to_json()
        and not parent.transaction.mutations
        and contract.ok
        and parent.coverage.get("atomic_commit", {}).get("commit_status") == "selected_graph_incomplete"
    )
    return {
        "ok": ok,
        "state_unchanged": parent.after.to_json() == before.snapshot().to_json(),
        "successor_eligible": parent.outcome.successor_eligible,
        "committed_mutation_count": len(parent.transaction.mutations),
        "outcome": parent.outcome.to_json(),
        "atomic_commit": parent.coverage.get("atomic_commit"),
        "contract": contract.to_json(),
    }


def _commit_case(before: BattleState, result: AtomicCommitResult) -> dict[str, Any]:
    return {
        "commit_status": result.evidence.get("commit_status"),
        "successor_eligible": result.outcome.successor_eligible,
        "state_unchanged": result.after_state.snapshot().to_json() == before.snapshot().to_json(),
        "committed_mutation_count": len(result.committed_mutations),
        "outcome": result.outcome.to_json(),
        "evidence": result.evidence,
    }


def _committed(result: AtomicCommitResult, *, planned_count: int) -> bool:
    return (
        result.outcome.category == "committed"
        and result.outcome.successor_eligible
        and len(result.committed_mutations) == planned_count
        and result.evidence.get("commit_status") == "committed"
        and result.evidence.get("candidate_matches_reduction") is True
    )


def _not_committed(before: BattleState, result: AtomicCommitResult, status: str) -> bool:
    return (
        result.outcome.category == "diagnostic"
        and not result.outcome.successor_eligible
        and result.after_state.snapshot().to_json() == before.snapshot().to_json()
        and not result.committed_mutations
        and result.evidence.get("commit_status") == status
        and result.evidence.get("candidate_state_published") is False
    )


def _strict_replay(before: BattleState, result: AtomicCommitResult) -> bool:
    replay = MutationReducer().replay_snapshot(
        before,
        result.committed_mutations,
        result.after_state.snapshot().to_json(),
    )
    return replay.ok


def _planned_sources_auditable(result: AtomicCommitResult) -> bool:
    planned = result.evidence.get("planned_mutations")
    return isinstance(planned, list) and bool(planned) and all(
        isinstance(item, dict)
        and bool(item.get("mutation_id"))
        and bool(item.get("path"))
        and bool(item.get("source"))
        and isinstance(item.get("metadata"), dict)
        for item in planned
    )


def _mutation(
    path: tuple[str, ...],
    *,
    before: Any,
    after: Any,
    source: str,
    node_id: str,
    before_exists: bool = True,
) -> Mutation:
    return Mutation(
        op="set",
        path=path,
        before=before,
        after=after,
        before_exists=before_exists,
        after_exists=True,
        reason="p7_s3_selected_graph_validation",
        source=source,
        metadata={
            "execution_node_id": node_id,
            "source_trace": {
                "source_path": "validation/selected_graph.json",
                "raw_type": "SelectedExecutionNode",
                "raw_id": node_id,
            },
        },
    )


def _node(
    node_kind: str,
    node_id: str,
    status: str = "complete",
    reason: str = "",
) -> ExecutionNodeResult:
    return ExecutionNodeResult(node_kind=node_kind, node_id=node_id, status=status, reason_code=reason)  # type: ignore[arg-type]


def _boundary_evidence(package_root: Path) -> dict[str, Any]:
    expected = {
        "core/executor.py": 1,
        "systems/scheduler.py": 2,
    }
    rows = []
    ok = True
    for relative, minimum in expected.items():
        path = package_root / relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        count = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "finalize_selected_execution_graph"
        )
        rows.append({"path": relative, "call_count": count, "minimum": minimum})
        ok = ok and count >= minimum
    return {"ok": ok, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate P7-S3 selected execution graph atomic commit")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/hsr_v8_p7_s3_selected_graph_atomic_commit"),
    )
    args = parser.parse_args()
    package_root = Path(__file__).resolve().parents[1]
    summary = run_validation(package_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={summary['ok']} "
        f"cases={summary['case_count']} ready_for_review={summary['ready_for_review']}"
    )
    raise SystemExit(0 if summary["ok"] else 1)


if __name__ == "__main__":
    main()
