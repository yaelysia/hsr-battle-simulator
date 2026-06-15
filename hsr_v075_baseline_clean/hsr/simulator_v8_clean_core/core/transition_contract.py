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
    "mutations",
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

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "missing_keys": list(self.missing_keys),
            "errors": list(self.errors),
            "snapshot_before": self.snapshot_before,
            "snapshot_after": self.snapshot_after,
            "settlement_traceability": self.settlement_traceability,
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

        before = self.snapshot_validator.validate(transition.transaction.before)
        after = self.snapshot_validator.validate(transition.after)
        settlement = self.settlement_validator.validate(
            transition.transaction.settlement,
            transition.transaction.mutations,
        )
        ok = not missing and not errors and before.ok and after.ok and settlement.ok
        return TransitionContractResult(
            ok=ok,
            missing_keys=missing,
            errors=tuple(errors),
            snapshot_before=before.to_json(),
            snapshot_after=after.to_json(),
            settlement_traceability=settlement.to_json(),
        )

