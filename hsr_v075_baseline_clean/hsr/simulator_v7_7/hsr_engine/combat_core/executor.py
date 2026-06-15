from __future__ import annotations

from typing import Any

from hsr_engine.settlement import ActionSettlement

from .contracts import ActionInput, ActionTransaction


class CombatExecutor:
    """Parallel combat-core action executor boundary.

    The first migration stage exposes the transaction boundary. Full action
    lifecycle migration will move into this class incrementally.
    """

    def begin_transaction(self, action_input: ActionInput, legacy_context: dict[str, Any] | None = None) -> ActionTransaction:
        return ActionTransaction.begin(action_input, legacy_context=legacy_context)

    def execute(self, action_input: ActionInput, state: Any, rules: Any) -> ActionSettlement:
        transaction = self.begin_transaction(action_input)
        before = getattr(state, "snapshot", None)
        if callable(before):
            transaction.settlement.capture_before_snapshot(before())
        after = getattr(state, "snapshot", None)
        if callable(after):
            transaction.settlement.capture_after_snapshot(after())
        return ActionSettlement(transition=transaction.transition.to_dict())
