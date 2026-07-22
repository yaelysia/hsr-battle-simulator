from __future__ import annotations

from collections.abc import Mapping, Sequence

from .model import BattleState, JSONValue


def transition_blocked_reason(transition_json: Mapping[str, JSONValue]) -> str:
    """Return the stable reason exposed to transition consumers."""

    raw_outcome = transition_json.get("outcome")
    outcome = raw_outcome if isinstance(raw_outcome, Mapping) else {}
    if (
        outcome.get("category") == "committed"
        and outcome.get("successor_eligible") is True
    ):
        return ""
    reasons = outcome.get("reason_codes")
    if isinstance(reasons, Sequence) and not isinstance(reasons, (str, bytes)):
        for reason in reasons:
            if isinstance(reason, str) and reason:
                return reason
    if outcome:
        return "transition_outcome_not_successor_eligible"
    return ""


def transition_successor_state(
    before_state: BattleState,
    candidate_after_state: BattleState,
    transition_json: Mapping[str, JSONValue],
) -> BattleState:
    """Select a successor only from the explicit transition outcome."""

    raw_outcome = transition_json.get("outcome")
    outcome = raw_outcome if isinstance(raw_outcome, Mapping) else {}
    if (
        outcome.get("category") == "committed"
        and outcome.get("successor_eligible") is True
    ):
        return candidate_after_state
    return before_state
