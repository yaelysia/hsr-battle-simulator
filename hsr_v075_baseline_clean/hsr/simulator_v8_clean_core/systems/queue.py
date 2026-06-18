from __future__ import annotations

from typing import Any

from ..core.model import BattleState, Mutation


class QueueSystem:
    def enqueue(
        self,
        state: BattleState,
        queue_name: str,
        action_ref: str,
        source: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Mutation:
        current = tuple(state.queues.get(queue_name, ()))
        updated = (*current, action_ref)
        return Mutation(
            op="set",
            path=("queues", queue_name),
            before=list(current),
            after=list(updated),
            reason="enqueue action",
            source=source,
            metadata={
                **(metadata or {}),
                "queue_name": queue_name,
                "action_ref": action_ref,
                "queue_operation": "enqueue",
            },
        )

    def dequeue(
        self,
        state: BattleState,
        queue_name: str,
        source: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Mutation:
        current = tuple(state.queues.get(queue_name, ()))
        updated = current[1:] if current else ()
        return Mutation(
            op="set",
            path=("queues", queue_name),
            before=list(current),
            after=list(updated),
            reason="dequeue action",
            source=source,
            metadata={
                **(metadata or {}),
                "queue_name": queue_name,
                "queue_operation": "dequeue",
                "action_ref": current[0] if current else "",
            },
        )
