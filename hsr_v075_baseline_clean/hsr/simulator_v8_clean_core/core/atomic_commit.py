from __future__ import annotations

from dataclasses import dataclass

from .model import BattleState, JSONValue, Mutation
from .reducer import MutationReducer
from .transition_outcome import ExecutionNodeResult, TransitionOutcome, classify_transition_outcome


@dataclass(frozen=True)
class AtomicCommitResult:
    """Official result of one selected execution graph.

    Systems may evaluate an immutable candidate state while planning dependent
    nodes.  This result is the only boundary allowed to publish that candidate
    as a successor state.
    """

    after_state: BattleState
    committed_mutations: tuple[Mutation, ...]
    outcome: TransitionOutcome
    evidence: dict[str, JSONValue]


def finalize_selected_execution_graph(
    before_state: BattleState,
    candidate_after_state: BattleState,
    planned_mutations: tuple[Mutation, ...],
    node_results: tuple[ExecutionNodeResult, ...],
    *,
    reducer: MutationReducer | None = None,
    preflight_blocked: bool = False,
    preflight_reason: str = "",
) -> AtomicCommitResult:
    """Validate and atomically publish a complete selected execution graph."""

    reducer = reducer or MutationReducer()
    selected_graph_complete = bool(node_results) and all(item.complete for item in node_results)
    planned_evidence = [_planned_mutation_evidence(mutation) for mutation in planned_mutations]

    if preflight_blocked or not selected_graph_complete:
        outcome = classify_transition_outcome(
            node_results,
            state_changed=False,
            mutation_count=0,
            preflight_blocked=preflight_blocked,
            preflight_reason=preflight_reason,
        )
        return AtomicCommitResult(
            after_state=before_state,
            committed_mutations=(),
            outcome=outcome,
            evidence={
                "schema_version": "p7_s3_atomic_commit_v1",
                "commit_status": "preflight_blocked" if preflight_blocked else "selected_graph_incomplete",
                "selected_graph_complete": selected_graph_complete,
                "candidate_state_published": False,
                "candidate_state_changed": before_state.snapshot().to_json()
                != candidate_after_state.snapshot().to_json(),
                "planned_mutation_count": len(planned_mutations),
                "committed_mutation_count": 0,
                "planned_mutations": planned_evidence,
                "conflicts": [],
            },
        )

    reduction = reducer.apply_all_result(before_state, planned_mutations)
    commit_nodes = node_results
    commit_status = "committed"
    candidate_matches_reduction = False
    if reduction.ok:
        candidate_matches_reduction = (
            reduction.after_state.snapshot().to_json() == candidate_after_state.snapshot().to_json()
        )
        if not candidate_matches_reduction:
            commit_status = "candidate_state_mismatch"
            commit_nodes = (
                *node_results,
                ExecutionNodeResult(
                    node_kind="atomic_commit",
                    node_id="selected_execution_graph",
                    status="error",
                    reason_code="candidate_state_does_not_match_planned_mutations",
                ),
            )
    else:
        commit_status = "mutation_conflict"
        reason = reduction.conflicts[0].code if reduction.conflicts else "unknown"
        commit_nodes = (
            *node_results,
            ExecutionNodeResult(
                node_kind="atomic_commit",
                node_id="selected_execution_graph",
                status="error",
                reason_code=f"mutation_conflict:{reason}",
            ),
        )

    if commit_status != "committed":
        outcome = classify_transition_outcome(
            commit_nodes,
            state_changed=False,
            mutation_count=0,
        )
        return AtomicCommitResult(
            after_state=before_state,
            committed_mutations=(),
            outcome=outcome,
            evidence={
                "schema_version": "p7_s3_atomic_commit_v1",
                "commit_status": commit_status,
                "selected_graph_complete": selected_graph_complete,
                "candidate_state_published": False,
                "candidate_state_changed": before_state.snapshot().to_json()
                != candidate_after_state.snapshot().to_json(),
                "candidate_matches_reduction": candidate_matches_reduction,
                "planned_mutation_count": len(planned_mutations),
                "committed_mutation_count": 0,
                "planned_mutations": planned_evidence,
                "conflicts": [conflict.to_json() for conflict in reduction.conflicts],
            },
        )

    committed_after = reduction.after_state
    committed_mutations = planned_mutations
    outcome = classify_transition_outcome(
        commit_nodes,
        state_changed=before_state.snapshot().to_json() != committed_after.snapshot().to_json(),
        mutation_count=len(committed_mutations),
    )
    return AtomicCommitResult(
        after_state=committed_after,
        committed_mutations=committed_mutations,
        outcome=outcome,
        evidence={
            "schema_version": "p7_s3_atomic_commit_v1",
            "commit_status": "committed",
            "selected_graph_complete": True,
            "candidate_state_published": True,
            "candidate_state_changed": before_state.snapshot().to_json()
            != candidate_after_state.snapshot().to_json(),
            "candidate_matches_reduction": True,
            "planned_mutation_count": len(planned_mutations),
            "committed_mutation_count": len(committed_mutations),
            "planned_mutations": planned_evidence,
            "conflicts": [],
        },
    )


def _planned_mutation_evidence(mutation: Mutation) -> dict[str, JSONValue]:
    payload = mutation.to_json()
    return {
        "mutation_id": payload["mutation_id"],
        "op": payload["op"],
        "path": payload["path"],
        "source": payload["source"],
        "metadata": payload["metadata"],
    }


def records_for_atomic_result(
    records: tuple[dict[str, JSONValue], ...],
    result: AtomicCommitResult,
) -> tuple[dict[str, JSONValue], ...]:
    """Keep failed-plan evidence without claiming that a mutation committed."""

    if result.outcome.successor_eligible:
        return records
    normalized: list[dict[str, JSONValue]] = []
    for record in records:
        if record.get("process_only") is not False:
            normalized.append(record)
            continue
        payload = record.get("payload")
        diagnostic_payload = dict(payload) if isinstance(payload, dict) else {}
        diagnostic_payload.update(
            {
                "planned_only": True,
                "atomic_commit_status": result.evidence.get("commit_status", "not_committed"),
            }
        )
        normalized.append(
            {
                **record,
                "process_only": True,
                "payload": diagnostic_payload,
            }
        )
    return tuple(normalized)
