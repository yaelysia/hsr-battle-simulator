from __future__ import annotations

from dataclasses import dataclass

from .model import BattleTransition, JSONValue
from .settlement import SettlementTraceabilityValidator
from .snapshot_contract import SnapshotCompletenessValidator


REQUIRED_TRANSITION_KEYS = (
    "command",
    "before",
    "after",
    "target_resolution",
    "events",
    "rng_events",
    "outcome",
    "mutations",
    "trigger_windows",
    "settlement",
    "coverage",
)


@dataclass(frozen=True)
class TransitionContractResult:
    ok: bool
    missing_keys: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    snapshot_before: dict[str, JSONValue] | None = None
    snapshot_after: dict[str, JSONValue] | None = None
    settlement_traceability: dict[str, JSONValue] | None = None
    outcome_validation: dict[str, JSONValue] | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "missing_keys": list(self.missing_keys),
            "errors": list(self.errors),
            "snapshot_before": self.snapshot_before,
            "snapshot_after": self.snapshot_after,
            "settlement_traceability": self.settlement_traceability,
            "outcome_validation": self.outcome_validation,
        }


class TransitionContractValidator:
    def __init__(self) -> None:
        self.snapshot_validator = SnapshotCompletenessValidator()
        self.settlement_validator = SettlementTraceabilityValidator()

    def validate(self, transition: BattleTransition) -> TransitionContractResult:
        transition_json = transition.to_json()
        missing = tuple(key for key in REQUIRED_TRANSITION_KEYS if key not in transition_json)
        errors: list[str] = []
        if transition.transaction.settlement is None:
            errors.append("transition settlement is missing")
        if not transition_json.get("target_resolution"):
            errors.append("transition target_resolution is empty")
        if not isinstance(transition_json.get("trigger_windows"), list):
            errors.append("transition trigger_windows must be a list")

        before = self.snapshot_validator.validate(transition.transaction.before)
        after = self.snapshot_validator.validate(transition.after)
        settlement = self.settlement_validator.validate(
            transition.transaction.settlement,
            transition.transaction.mutations,
        )
        outcome_validation = _validate_outcome(transition)
        ok = not missing and not errors and before.ok and after.ok and settlement.ok and outcome_validation["ok"] is True
        return TransitionContractResult(
            ok=ok,
            missing_keys=missing,
            errors=tuple(errors),
            snapshot_before=before.to_json(),
            snapshot_after=after.to_json(),
            settlement_traceability=settlement.to_json(),
            outcome_validation=outcome_validation,
        )


def _validate_outcome(transition: BattleTransition) -> dict[str, JSONValue]:
    outcome = transition.outcome
    errors: list[str] = []
    state_unchanged = transition.transaction.before.to_json() == transition.after.to_json()
    mutation_count = len(transition.transaction.mutations)
    incomplete = tuple(item for item in outcome.node_results if not item.complete)

    if outcome.category == "committed":
        if not outcome.node_results:
            errors.append("committed transition completeness signals are missing")
        if incomplete:
            errors.append("committed transition contains incomplete execution nodes")
        if not outcome.successor_eligible:
            errors.append("committed transition must be successor eligible")
        if not state_unchanged and mutation_count == 0:
            errors.append("committed transition state change requires mutations")
    elif outcome.category == "blocked":
        if outcome.successor_eligible:
            errors.append("blocked transition must not be successor eligible")
        if not state_unchanged:
            errors.append("blocked transition must keep state unchanged")
        if mutation_count:
            errors.append("blocked transition must not contain mutations")
        if not incomplete:
            errors.append("blocked transition must identify an incomplete node")
        if not outcome.reason_codes:
            errors.append("blocked transition reason codes are missing")
    elif outcome.category == "diagnostic":
        if outcome.successor_eligible:
            errors.append("diagnostic transition must not be successor eligible")
        if not outcome.reason_codes:
            errors.append("diagnostic transition reason codes are missing")
    else:
        errors.append(f"unknown transition outcome category: {outcome.category}")

    return {
        "ok": not errors,
        "category": outcome.category,
        "successor_eligible": outcome.successor_eligible,
        "state_unchanged": state_unchanged,
        "mutation_count": mutation_count,
        "node_result_count": len(outcome.node_results),
        "incomplete_node_count": len(incomplete),
        "errors": errors,
    }
