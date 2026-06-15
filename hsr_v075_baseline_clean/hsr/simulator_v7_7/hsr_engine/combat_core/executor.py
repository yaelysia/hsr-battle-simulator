from __future__ import annotations

from typing import Any

from hsr_engine.settlement import ActionSettlement

from .contracts import ActionInput, ActionTransaction
from .runtime import CombatRuntime


class CombatExecutor:
    """Parallel combat-core action executor boundary.

    The first migration stage exposes the transaction boundary. Full action
    lifecycle migration will move into this class incrementally.
    """

    def __init__(self) -> None:
        self.runtime: CombatRuntime | None = None

    def bind_runtime(self, simulator: Any) -> CombatRuntime:
        self.runtime = CombatRuntime(simulator)
        return self.runtime

    def _runtime(self, simulator: Any) -> CombatRuntime:
        if self.runtime is None or self.runtime.sim is not simulator:
            return self.bind_runtime(simulator)
        return self.runtime

    def resolve_route_step(self, simulator: Any, step: dict[str, Any]) -> None:
        return self._runtime(simulator).resolve_route_step(step)

    def resolve_action(self, simulator: Any, action: dict[str, Any], targets: list[str], events: dict[str, Any], context: dict[str, Any] | None = None) -> None:
        return self._runtime(simulator).resolve_action(action, targets, events, context=context)

    def apply_effect(self, simulator: Any, eff: dict[str, Any], ctx: dict[str, Any]) -> None:
        return self._runtime(simulator).apply_effect(eff, ctx)

    def drain_queues(self, simulator: Any, default_events: dict[str, Any] | None = None) -> None:
        return self._runtime(simulator).drain_queues(default_events=default_events)

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
