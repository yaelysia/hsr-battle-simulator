from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.model import BattleState, JSONValue, Mutation


@dataclass(frozen=True)
class QueueEntry:
    entry_id: str
    queue_name: str
    queue_kind: str
    actor_id: str
    action_or_ability_ref: str
    target_ids: tuple[str, ...]
    priority_source: dict[str, JSONValue]
    source_trace: dict[str, JSONValue]
    status: str = "pending"
    drain_status: str = "not_attempted"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "entry_id": self.entry_id,
            "queue_name": self.queue_name,
            "queue_kind": self.queue_kind,
            "actor_id": self.actor_id,
            "action_or_ability_ref": self.action_or_ability_ref,
            "target_ids": list(self.target_ids),
            "priority_source": self.priority_source,
            "source_trace": self.source_trace,
            "status": self.status,
            "drain_status": self.drain_status,
        }


class QueueSystem:
    def enqueue(
        self,
        state: BattleState,
        queue_name: str,
        entry: QueueEntry,
        source: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Mutation:
        current = tuple(state.queues.get(queue_name, ()))
        entry_json = entry.to_json()
        updated = (*current, entry_json)
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
                "action_ref": entry.action_or_ability_ref,
                "queue_entry": entry_json,
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
        dequeued = current[0] if current else ""
        action_ref = ""
        if isinstance(dequeued, dict):
            value = dequeued.get("action_or_ability_ref", "")
            action_ref = value if isinstance(value, str) else ""
        elif isinstance(dequeued, str):
            action_ref = dequeued
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
                "action_ref": action_ref,
                "queue_entry": dequeued,
            },
        )
