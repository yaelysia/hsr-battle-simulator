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
    priority_key: str = ""
    priority_value: float | None = None
    queue_priority_id: str = ""
    priority_source_trace: dict[str, JSONValue] | None = None
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
            "priority_key": self.priority_key,
            "priority_value": self.priority_value,
            "queue_priority_id": self.queue_priority_id,
            "priority_source_trace": self.priority_source_trace or {},
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
    queue_priority_id: str = ""
    priority_key: str = ""
    priority_value: float | None = None
    resolved_kind: str = ""
    drain_order: int | None = None

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
            "queue_priority_id": self.queue_priority_id,
            "priority_key": self.priority_key,
            "priority_value": self.priority_value,
            "resolved_kind": self.resolved_kind,
            "drain_order": self.drain_order,
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
        return self._plan_entry(queue_name, entry, resolution, drain_order=0)

    def plan_next_drain(
        self,
        state: BattleState,
        queue_name: str,
        resolutions_by_intent: dict[str, QueueResolutionIR],
    ) -> QueueDrainPlan:
        entries = self._entries(state, queue_name)
        if not entries:
            return QueueDrainPlan(False, "blocked", queue_name, {}, "", "", "queue_empty_or_legacy_entry")
        plans = [
            self._plan_entry(
                queue_name,
                entry,
                resolutions_by_intent.get(str(entry.get("queue_intent_id") or "")),
                drain_order=index,
            )
            for index, entry in enumerate(entries)
        ]
        admitted = [plan for plan in plans if plan.ok]
        if not admitted:
            return plans[0]
        return sorted(
            admitted,
            key=lambda plan: (
                float(plan.priority_value) if plan.priority_value is not None else float("inf"),
                plan.drain_order if plan.drain_order is not None else 0,
                str(plan.queue_entry.get("entry_id") or ""),
            ),
        )[0]

    def _entries(self, state: BattleState, queue_name: str) -> tuple[dict[str, JSONValue], ...]:
        return tuple(entry for entry in state.queues.get(queue_name, ()) if isinstance(entry, dict))

    def _plan_entry(
        self,
        queue_name: str,
        entry: dict[str, JSONValue] | None,
        resolution: QueueResolutionIR | None,
        *,
        drain_order: int | None,
    ) -> QueueDrainPlan:
        if entry is None:
            return QueueDrainPlan(False, "blocked", queue_name, {}, "", "", "queue_empty_or_legacy_entry")
        queue_intent_id = str(entry.get("queue_intent_id") or "")
        if not queue_intent_id:
            return QueueDrainPlan(False, "blocked", queue_name, entry, "", "", "queue_entry_missing_intent_id")
        if resolution is None:
            return QueueDrainPlan(
                False,
                "blocked",
                queue_name,
                entry,
                queue_intent_id,
                "",
                "queue_resolution_missing",
                drain_order=drain_order,
            )
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
                resolved_kind=resolution.resolved_kind,
                drain_order=drain_order,
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
                resolved_kind=resolution.resolved_kind,
                drain_order=drain_order,
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
                resolved_kind=resolution.resolved_kind,
                drain_order=drain_order,
            )
        priority_value_raw = priority_source.get("priority_value")
        priority_value = float(priority_value_raw) if isinstance(priority_value_raw, (int, float)) else None
        if priority_value is None:
            return QueueDrainPlan(
                False,
                "blocked",
                queue_name,
                entry,
                queue_intent_id,
                resolution.queue_resolution_id,
                "queue_priority_value_missing",
                {"queue_resolution_source": resolution.source.to_json()},
                queue_priority_id=str(priority_source.get("queue_priority_id") or ""),
                priority_key=str(priority_source.get("priority_key") or ""),
                resolved_kind=resolution.resolved_kind,
                drain_order=drain_order,
            )
        if resolution.resolved_kind == "standalone_ability_graph":
            executable_task_ids = resolution.resolved_ids.get("executable_task_ids")
            if not isinstance(executable_task_ids, list) or not executable_task_ids:
                return QueueDrainPlan(
                    False,
                    "blocked",
                    queue_name,
                    entry,
                    queue_intent_id,
                    resolution.queue_resolution_id,
                    "queue_standalone_ability_has_no_executable_runtime_task",
                    {"queue_resolution_source": resolution.source.to_json()},
                    queue_priority_id=str(priority_source.get("queue_priority_id") or ""),
                    priority_key=str(priority_source.get("priority_key") or ""),
                    priority_value=priority_value,
                    resolved_kind=resolution.resolved_kind,
                    drain_order=drain_order,
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
            queue_priority_id=str(priority_source.get("queue_priority_id") or ""),
            priority_key=str(priority_source.get("priority_key") or ""),
            priority_value=priority_value,
            resolved_kind=resolution.resolved_kind,
            drain_order=drain_order,
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
        return self.dequeue_entry(state, queue_name, None, source, metadata=metadata)

    def dequeue_entry(
        self,
        state: BattleState,
        queue_name: str,
        entry_id: str | None,
        source: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Mutation:
        current = tuple(state.queues.get(queue_name, ()))
        if entry_id:
            index = next(
                (
                    idx
                    for idx, item in enumerate(current)
                    if isinstance(item, dict) and item.get("entry_id") == entry_id
                ),
                -1,
            )
            if index < 0:
                raise ValueError(f"queue entry not found for dequeue: {entry_id}")
            dequeued = current[index]
            updated = (*current[:index], *current[index + 1 :])
        else:
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
                "dequeue_entry_id": entry_id or "",
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
        entry_id = str(plan.queue_entry.get("entry_id") or "")
        return self.dequeue_entry(
            state,
            plan.queue_name,
            entry_id or None,
            source,
            metadata={
                **(metadata or {}),
                "queue_intent_id": plan.queue_intent_id,
                "queue_resolution_id": plan.queue_resolution_id,
                "queue_priority_id": plan.queue_priority_id,
                "priority_key": plan.priority_key,
                "priority_value": plan.priority_value,
                "source_trace": plan.source_trace or {},
                "drain_plan": plan.to_json(),
            },
        )
