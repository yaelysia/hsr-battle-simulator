from __future__ import annotations

from ..core.model import BattleState, Mutation


class QueueSystem:
    def enqueue(self, state: BattleState, queue_name: str, action_ref: str, source: str) -> Mutation:
        current = tuple(state.queues.get(queue_name, ()))
        updated = (*current, action_ref)
        return Mutation(
            op="set",
            path=("queues", queue_name),
            before=list(current),
            after=list(updated),
            reason="enqueue action",
            source=source,
            metadata={"action_ref": action_ref},
        )

    def dequeue(self, state: BattleState, queue_name: str, source: str) -> Mutation:
        current = tuple(state.queues.get(queue_name, ()))
        updated = current[1:] if current else ()
        return Mutation(
            op="set",
            path=("queues", queue_name),
            before=list(current),
            after=list(updated),
            reason="dequeue action",
            source=source,
        )

