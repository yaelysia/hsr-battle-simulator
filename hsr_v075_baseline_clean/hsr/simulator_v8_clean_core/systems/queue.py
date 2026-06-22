from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.model import BattleState, JSONValue, Mutation
from ..rules.ir import QueueResolutionIR


@dataclass(frozen=True)
class QueueEntry:
    entry_id: str
    queue_name: str
    queue_kind: str
    queue_intent_id: str
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
            "queue_intent_id": self.queue_intent_id,
            "actor_id": self.actor_id,
            "action_or_ability_ref": self.action_or_ability_ref,
            "target_ids": list(self.target_ids),
            "priority_source": self.priority_source,
            "source_trace": self.source_trace,
            "status": self.status,
            "drain_status": self.drain_status,
        }


@dataclass(frozen=True)
class QueueDrainPlan:
    ok: bool
    status: str
    queue_name: str
    queue_entry: dict[str, JSONValue]
    queue_intent_id: str
    queue_resolution_id: str
    blocked_reason: str = ""
    source_trace: dict[str, JSONValue] | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "status": self.status,
            "queue_name": self.queue_name,
            "queue_entry": self.queue_entry,
            "queue_intent_id": self.queue_intent_id,
            "queue_resolution_id": self.queue_resolution_id,
            "blocked_reason": self.blocked_reason,
            "source_trace": self.source_trace or {},
        }


class QueueSystem:
    def peek(self, state: BattleState, queue_name: str) -> dict[str, JSONValue] | None:
        current = tuple(state.queues.get(queue_name, ()))
        if not current:
            return None
        entry = current[0]
        return entry if isinstance(entry, dict) else None

    def plan_drain(
        self,
        state: BattleState,
        queue_name: str,
        resolution: QueueResolutionIR | None,
    ) -> QueueDrainPlan:
        entry = self.peek(state, queue_name)
        if entry is None:
            return QueueDrainPlan(False, "blocked", queue_name, {}, "", "", "queue_empty_or_legacy_entry")
        queue_intent_id = str(entry.get("queue_intent_id") or "")
        if not queue_intent_id:
            return QueueDrainPlan(False, "blocked", queue_name, entry, "", "", "queue_entry_missing_intent_id")
        if resolution is None:
            return QueueDrainPlan(False, "blocked", queue_name, entry, queue_intent_id, "", "queue_resolution_missing")
        if resolution.queue_intent_id != queue_intent_id:
            return QueueDrainPlan(
                False,
                "blocked",
                queue_name,
                entry,
                queue_intent_id,
                resolution.queue_resolution_id,
                "queue_resolution_intent_mismatch",
                {"queue_resolution_source": resolution.source.to_json()},
            )
        if resolution.coverage_status != "executable":
            return QueueDrainPlan(
                False,
                "blocked",
                queue_name,
                entry,
                queue_intent_id,
                resolution.queue_resolution_id,
                resolution.blocked_reason or f"queue_resolution_not_executable:{resolution.coverage_status}",
                {"queue_resolution_source": resolution.source.to_json()},
            )
        priority_source = entry.get("priority_source")
        if not isinstance(priority_source, dict) or priority_source.get("priority_ordering_admitted") is not True:
            return QueueDrainPlan(
                False,
                "blocked",
                queue_name,
                entry,
                queue_intent_id,
                resolution.queue_resolution_id,
                "queue_priority_ordering_not_admitted",
                {"queue_resolution_source": resolution.source.to_json()},
            )
        return QueueDrainPlan(
            True,
            "drain_candidate",
            queue_name,
            entry,
            queue_intent_id,
            resolution.queue_resolution_id,
            "",
            {"queue_resolution_source": resolution.source.to_json()},
        )

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

    def drain_admitted(
        self,
        state: BattleState,
        plan: QueueDrainPlan,
        source: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Mutation:
        if not plan.ok:
            raise ValueError(f"queue drain plan is not admitted: {plan.blocked_reason}")
        return self.dequeue(
            state,
            plan.queue_name,
            source,
            metadata={
                **(metadata or {}),
                "queue_intent_id": plan.queue_intent_id,
                "queue_resolution_id": plan.queue_resolution_id,
                "source_trace": plan.source_trace or {},
                "drain_plan": plan.to_json(),
            },
        )
