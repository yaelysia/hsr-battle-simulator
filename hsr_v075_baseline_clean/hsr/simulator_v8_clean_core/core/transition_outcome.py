from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ExecutionNodeStatus = Literal["complete", "blocked", "unsupported", "partial", "error"]
TransitionOutcomeCategory = Literal["committed", "blocked", "diagnostic"]


@dataclass(frozen=True)
class ExecutionNodeResult:
    node_kind: str
    node_id: str
    status: ExecutionNodeStatus
    reason_code: str = ""

    @property
    def complete(self) -> bool:
        return self.status == "complete"

    def to_json(self) -> dict[str, object]:
        return {
            "node_kind": self.node_kind,
            "node_id": self.node_id,
            "status": self.status,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class TransitionOutcome:
    category: TransitionOutcomeCategory
    reason_codes: tuple[str, ...] = ()
    node_results: tuple[ExecutionNodeResult, ...] = ()
    schema_version: str = "p7_s1_transition_outcome_v1"

    @property
    def successor_eligible(self) -> bool:
        return self.category == "committed"

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "category": self.category,
            "successor_eligible": self.successor_eligible,
            "reason_codes": list(self.reason_codes),
            "node_results": [item.to_json() for item in self.node_results],
        }


def classify_transition_outcome(
    node_results: tuple[ExecutionNodeResult, ...],
    *,
    state_changed: bool,
    mutation_count: int,
    preflight_blocked: bool = False,
    preflight_reason: str = "",
) -> TransitionOutcome:
    reasons = _reason_codes(node_results, extra=(preflight_reason,))
    if not node_results:
        return unclassified_transition_outcome("transition_completeness_signals_missing")

    incomplete = tuple(item for item in node_results if not item.complete)
    if preflight_blocked:
        if not state_changed and mutation_count == 0 and incomplete:
            return TransitionOutcome(
                category="blocked",
                reason_codes=reasons or ("transition_preflight_blocked",),
                node_results=node_results,
            )
        consistency_reasons = (
            *(reasons or ("transition_preflight_blocked",)),
            *(("blocked_transition_changed_state",) if state_changed else ()),
            *(("blocked_transition_has_mutations",) if mutation_count else ()),
            *(("blocked_transition_has_no_blocked_node",) if not incomplete else ()),
        )
        return TransitionOutcome(
            category="diagnostic",
            reason_codes=tuple(dict.fromkeys(consistency_reasons)),
            node_results=node_results,
        )

    if state_changed and mutation_count == 0:
        return TransitionOutcome(
            category="diagnostic",
            reason_codes=tuple(dict.fromkeys((*reasons, "state_changed_without_mutations"))),
            node_results=node_results,
        )

    if incomplete:
        return TransitionOutcome(
            category="diagnostic",
            reason_codes=reasons or ("selected_execution_node_incomplete",),
            node_results=node_results,
        )
    return TransitionOutcome(category="committed", node_results=node_results)


def unclassified_transition_outcome(reason_code: str = "transition_outcome_unclassified") -> TransitionOutcome:
    return TransitionOutcome(category="diagnostic", reason_codes=(reason_code,))


def _reason_codes(
    node_results: tuple[ExecutionNodeResult, ...],
    *,
    extra: tuple[str, ...] = (),
) -> tuple[str, ...]:
    values = [item.reason_code for item in node_results if item.reason_code]
    values.extend(item for item in extra if item)
    return tuple(dict.fromkeys(values))
