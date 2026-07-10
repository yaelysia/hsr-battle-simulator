from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.model import BattleState, GameEvent, JSONValue, Mutation
from ..rules.ir import QueueResolutionIR
from .unit_relation import is_opposing_combat_team, is_same_combat_team
from .unit_lifecycle import UnitLifecycleSystem


@dataclass(frozen=True)
class QueueTargetResolution:
    ok: bool
    actor_id: str
    target_ids: tuple[str, ...]
    actor_alias: str
    target_alias: str
    blocked_reason: str = ""
    source_trace: dict[str, JSONValue] | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "actor_id": self.actor_id,
            "target_ids": list(self.target_ids),
            "actor_alias": self.actor_alias,
            "target_alias": self.target_alias,
            "blocked_reason": self.blocked_reason,
            "source_trace": self.source_trace or {},
        }


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
    queue_window_id: str = ""
    window_family: str = ""
    window_policy: dict[str, JSONValue] | None = None
    target_resolution: dict[str, JSONValue] | None = None
    owner_id: str = ""
    source_id: str = ""
    expiration_policy: dict[str, JSONValue] | None = None
    cancel_policy: dict[str, JSONValue] | None = None
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
            "queue_window_id": self.queue_window_id,
            "window_family": self.window_family,
            "window_policy": self.window_policy or {},
            "target_resolution": self.target_resolution or {},
            "owner_id": self.owner_id,
            "source_id": self.source_id,
            "expiration_policy": self.expiration_policy or {},
            "cancel_policy": self.cancel_policy or {},
            "source_trace": self.source_trace,
            "status": self.status,
            "drain_status": self.drain_status,
        }


@dataclass(frozen=True)
class QueueWindowPlan:
    ok: bool
    status: str
    window_kind: str
    queue_kind: str
    queue_intent_id: str
    queue_resolution_id: str
    queue_priority_id: str = ""
    queue_window_id: str = ""
    window_family: str = ""
    priority_key: str = ""
    priority_value: float | None = None
    window_policy: dict[str, JSONValue] | None = None
    target_resolution: dict[str, JSONValue] | None = None
    blocked_reason: str = ""
    source_trace: dict[str, JSONValue] | None = None
    control: str = ""
    family_order: int | None = None
    ordering_source_kind: str = ""
    ordering: dict[str, JSONValue] | None = None

    def to_json(self) -> dict[str, JSONValue]:
        ordering = self.ordering or queue_ordering_metadata(
            window_family=self.window_family,
            priority_source={
                "queue_priority_id": self.queue_priority_id,
                "priority_key": self.priority_key,
                "priority_value": self.priority_value,
            },
            priority_key=self.priority_key,
            priority_value=self.priority_value,
            drain_order=None,
            entry_id="",
            blocked_reason=self.blocked_reason,
        )
        control = self.control or queue_window_control(self.window_family, ok=self.ok)
        if (
            not self.control
            and self.ok
            and self.window_family == "extra_turn"
            and (self.window_policy or {}).get("action_selection_policy") == "source_or_route_selected_action_required"
        ):
            control = "selectable"
        return {
            "ok": self.ok,
            "status": self.status,
            "window_kind": self.window_kind,
            "queue_kind": self.queue_kind,
            "queue_intent_id": self.queue_intent_id,
            "queue_resolution_id": self.queue_resolution_id,
            "queue_priority_id": self.queue_priority_id,
            "queue_window_id": self.queue_window_id,
            "window_family": self.window_family,
            "priority_key": self.priority_key,
            "priority_value": self.priority_value,
            "window_policy": self.window_policy or {},
            "target_resolution": self.target_resolution or {},
            "blocked_reason": self.blocked_reason,
            "source_trace": self.source_trace or {},
            "control": control,
            "family_order": self.family_order if self.family_order is not None else queue_window_family_order(self.window_family),
            "ordering_source_kind": self.ordering_source_kind or str(ordering.get("ordering_source_kind") or ""),
            "ordering": ordering,
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
    queue_window: dict[str, JSONValue] | None = None
    resolved_action_id: str = ""
    resolved_action_level: int | None = None
    control: str = ""
    family_order: int | None = None
    ordering_source_kind: str = ""
    tie_breaker: dict[str, JSONValue] | None = None
    ordering: dict[str, JSONValue] | None = None

    def to_json(self) -> dict[str, JSONValue]:
        window = self.queue_window or {}
        window_family = str(window.get("window_family") or "")
        priority_source = None
        entry_priority = self.queue_entry.get("priority_source") if isinstance(self.queue_entry, dict) else None
        if isinstance(entry_priority, dict):
            priority_source = entry_priority
        ordering = self.ordering or queue_ordering_metadata(
            window_family=window_family,
            priority_source=priority_source,
            priority_key=self.priority_key,
            priority_value=self.priority_value,
            drain_order=self.drain_order,
            entry_id=str(self.queue_entry.get("entry_id") or "") if isinstance(self.queue_entry, dict) else "",
            blocked_reason=self.blocked_reason,
        )
        if self.control:
            control = self.control
        elif self.ok and window_family == "extra_turn" and self.resolved_kind == "extra_turn_action_choice":
            control = "selectable"
        else:
            control = queue_window_control(window_family, ok=self.ok)
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
            "queue_window": self.queue_window or {},
            "resolved_action_id": self.resolved_action_id,
            "resolved_action_level": self.resolved_action_level,
            "control": control,
            "family_order": self.family_order if self.family_order is not None else queue_window_family_order(window_family),
            "ordering_source_kind": self.ordering_source_kind or str(ordering.get("ordering_source_kind") or ""),
            "tie_breaker": self.tie_breaker or dict(ordering.get("tie_breaker", {})),
            "ordering": ordering,
        }


QUEUE_WINDOW_FAMILY_ORDER: dict[str, int] = {
    "follow_up": 0,
    "counter": 0,
    "ultimate": 10,
    "extra_turn": 10,
    "interrupt": 20,
    "immediate": 50,
    "insert_action": 60,
    "insert_ability": 70,
    "assistant": 90,
    "unknown": 999,
}


def queue_window_family_order(window_family: str) -> int:
    return QUEUE_WINDOW_FAMILY_ORDER.get(window_family or "unknown", 999)


def queue_window_control(window_family: str, resolution: QueueResolutionIR | None = None, *, ok: bool = True) -> str:
    if not ok:
        return "blocked"
    if window_family == "ultimate":
        return "selectable"
    if (
        window_family == "extra_turn"
        and resolution is not None
        and resolution.resolved_kind == "extra_turn_action_choice"
    ):
        return "selectable"
    return "mandatory"


def queue_ordering_metadata(
    *,
    window_family: str,
    priority_source: dict[str, JSONValue] | None,
    priority_key: str,
    priority_value: float | None,
    drain_order: int | None,
    entry_id: str,
    blocked_reason: str = "",
) -> dict[str, JSONValue]:
    priority = priority_source if isinstance(priority_source, dict) else {}
    priority_source_kind = _priority_ordering_source_kind(priority)
    family_order = queue_window_family_order(window_family)
    return {
        "family_order": family_order,
        "family_order_source_kind": "engine_scheduling_convention",
        "priority_key": priority_key,
        "priority_value": priority_value,
        "priority_order_source_kind": priority_source_kind,
        "priority_table": str(priority.get("priority_table") or ""),
        "queue_priority_id": str(priority.get("queue_priority_id") or ""),
        "tie_breaker_source_kind": "engine_scheduling_convention",
        "tie_breaker": {
            "drain_order": drain_order,
            "entry_id": entry_id,
            "rule": "stable_drain_order_then_entry_id",
        },
        "ordering_source_kind": "source_gap_blocked" if blocked_reason else priority_source_kind,
        "engine_scheduling_convention": {
            "family_order_table": dict(QUEUE_WINDOW_FAMILY_ORDER),
            "sort_key": [
                family_order,
                priority_value if priority_value is not None else "inf",
                drain_order if drain_order is not None else 0,
                entry_id,
            ],
        },
        "blocked_reason": blocked_reason,
    }


def _priority_ordering_source_kind(priority_source: dict[str, JSONValue]) -> str:
    priority_key = str(priority_source.get("priority_key") or "")
    priority_table = str(priority_source.get("priority_table") or "")
    queue_priority_id = str(priority_source.get("queue_priority_id") or "")
    if priority_source.get("field") == "manual_route_input" or priority_key == "manual_ultimate":
        return "manual_route_input"
    if queue_priority_id or priority_table:
        return "tbgd_priority_table"
    if priority_source.get("priority_ordering_admitted") is True:
        return "queue_intent_priority_source"
    return "source_gap_blocked"


class QueueTargetResolver:
    def __init__(self) -> None:
        self.lifecycle = UnitLifecycleSystem()

    def resolve(
        self,
        state: BattleState,
        *,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        actor_alias: str | None,
        target_alias: str | None,
        source_trace: dict[str, JSONValue] | None = None,
    ) -> QueueTargetResolution:
        actor_id = self._resolve_single(state, detail, trigger_event, actor_alias, relative_actor_id="")
        if not actor_id:
            return QueueTargetResolution(
                False,
                "",
                (),
                actor_alias or "",
                target_alias or "",
                f"queue_actor_not_resolved:{actor_alias or 'missing'}",
                source_trace,
            )
        if actor_id not in state.units:
            return QueueTargetResolution(
                False,
                actor_id,
                (),
                actor_alias or "",
                target_alias or "",
                f"queue_actor_missing:{actor_id}",
                source_trace,
            )
        actor_ok, actor_reason = self.lifecycle.can_act(state, actor_id)
        if not actor_ok:
            return QueueTargetResolution(
                False,
                actor_id,
                (),
                actor_alias or "",
                target_alias or "",
                f"queue_actor_{actor_reason}:{actor_id}",
                source_trace,
            )
        target_ids = self._resolve_many(state, detail, trigger_event, target_alias, relative_actor_id=actor_id)
        if target_alias and not target_ids:
            return QueueTargetResolution(
                False,
                actor_id,
                (),
                actor_alias or "",
                target_alias,
                f"queue_target_not_resolved:{target_alias}",
                source_trace,
            )
        missing_targets = tuple(target_id for target_id in target_ids if target_id not in state.units)
        if missing_targets:
            return QueueTargetResolution(
                False,
                actor_id,
                target_ids,
                actor_alias or "",
                target_alias or "",
                f"queue_target_missing:{','.join(missing_targets)}",
                source_trace,
            )
        invalid_targets = tuple(
            target_id
            for target_id in target_ids
            if not self.lifecycle.can_target(state, target_id, allow_defeated=False)[0]
        )
        if invalid_targets:
            reasons = [
                f"{self.lifecycle.can_target(state, target_id, allow_defeated=False)[1]}:{target_id}"
                for target_id in invalid_targets
            ]
            return QueueTargetResolution(
                False,
                actor_id,
                target_ids,
                actor_alias or "",
                target_alias or "",
                f"queue_target_lifecycle_blocked:{','.join(reasons)}",
                source_trace,
            )
        return QueueTargetResolution(True, actor_id, target_ids, actor_alias or "", target_alias or "", "", source_trace)

    def _resolve_single(
        self,
        state: BattleState,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        alias: str | None,
        *,
        relative_actor_id: str,
    ) -> str:
        values = self._resolve_many(state, detail, trigger_event, alias, relative_actor_id=relative_actor_id)
        return values[0] if values else ""

    def _resolve_many(
        self,
        state: BattleState,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        alias: str | None,
        *,
        relative_actor_id: str,
    ) -> tuple[str, ...]:
        if not alias:
            return ()
        payload = trigger_event.payload if trigger_event is not None else {}
        if not isinstance(payload, dict):
            payload = {}
        if alias == "Caster":
            return _nonempty_tuple(detail.get("caster_id"))
        if alias == "ModifierOwnerEntity":
            return _nonempty_tuple(detail.get("owner_id"))
        if alias in {"ParamEntity", "CurrentActionTarget", "AbilityTargetEntity"}:
            return _first_nonempty_tuple(
                payload.get("param_entity_id"),
                payload.get("current_hit_target_id"),
                payload.get("primary_target_id"),
                payload.get("target_id"),
                trigger_event.target_id if trigger_event is not None else "",
            )
        if alias == "DamageAttackerEntity":
            return _first_nonempty_tuple(
                payload.get("damage_attacker_id"),
                payload.get("attacker_id"),
                trigger_event.source_id if trigger_event is not None else "",
            )
        if alias == "ModifierOwnerSkillTargetEntityList":
            return _first_nonempty_tuple(
                payload.get("modifier_owner_skill_target_ids"),
                payload.get("selected_target_ids"),
                payload.get("target_ids"),
            )
        if alias == "ParamEntitySkillTargetEntityList":
            return _first_nonempty_tuple(
                payload.get("param_entity_skill_target_ids"),
                payload.get("selected_target_ids"),
                payload.get("target_ids"),
                payload.get("current_hit_target_id"),
            )
        if alias == "AllEnemy":
            return _units_by_relative_side(state, relative_actor_id, enemy=True)
        if alias in {"AllTeamMember", "AllLightTeam"}:
            return _units_by_relative_side(state, relative_actor_id, enemy=False)
        return ()


class QueueSystem:
    def __init__(self) -> None:
        self.lifecycle = UnitLifecycleSystem()

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
        return self._plan_entry(state, queue_name, entry, resolution, drain_order=0)

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
                state,
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
                QUEUE_WINDOW_FAMILY_ORDER.get(plan.queue_window.get("window_family") or "unknown", 999),
                float(plan.priority_value) if plan.priority_value is not None else float("inf"),
                plan.drain_order if plan.drain_order is not None else 0,
                str(plan.queue_entry.get("entry_id") or ""),
            ),
        )[0]

    def _entries(self, state: BattleState, queue_name: str) -> tuple[dict[str, JSONValue], ...]:
        return tuple(entry for entry in state.queues.get(queue_name, ()) if isinstance(entry, dict))

    def _plan_entry(
        self,
        state: BattleState,
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
            window = self._queue_window_plan(
                entry,
                resolution,
                priority_source=priority_source,
                priority_value=priority_value,
            )
            if not window.ok:
                return self._blocked_with_window(
                    queue_name,
                    entry,
                    queue_intent_id,
                    resolution,
                    priority_source,
                    priority_value,
                    drain_order,
                    window,
                )
        elif resolution.resolved_kind == "action_definition":
            action_match = self._resolve_action_candidate(state, entry, resolution)
            window = self._queue_window_plan(
                entry,
                resolution,
                priority_source=priority_source,
                priority_value=priority_value,
            )
            if not action_match["ok"]:
                return QueueDrainPlan(
                    False,
                    "blocked",
                    queue_name,
                    entry,
                    queue_intent_id,
                    resolution.queue_resolution_id,
                    str(action_match["blocked_reason"]),
                    {"queue_resolution_source": resolution.source.to_json()},
                    queue_priority_id=str(priority_source.get("queue_priority_id") or ""),
                    priority_key=str(priority_source.get("priority_key") or ""),
                    priority_value=priority_value,
                    resolved_kind=resolution.resolved_kind,
                    drain_order=drain_order,
                    queue_window=window.to_json(),
                )
            if not window.ok:
                return self._blocked_with_window(
                    queue_name,
                    entry,
                    queue_intent_id,
                    resolution,
                    priority_source,
                    priority_value,
                    drain_order,
                    window,
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
                queue_window=window.to_json(),
                resolved_action_id=str(action_match["action_id"]),
                resolved_action_level=int(action_match["action_level"]),
            )
        elif resolution.resolved_kind == "extra_turn_action_choice":
            window = self._queue_window_plan(
                entry,
                resolution,
                priority_source=priority_source,
                priority_value=priority_value,
            )
            if not window.ok:
                return self._blocked_with_window(
                    queue_name,
                    entry,
                    queue_intent_id,
                    resolution,
                    priority_source,
                    priority_value,
                    drain_order,
                    window,
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
                queue_window=window.to_json(),
            )
        else:
            window = self._queue_window_plan(
                entry,
                resolution,
                priority_source=priority_source,
                priority_value=priority_value,
            )
            return self._blocked_with_window(
                queue_name,
                entry,
                queue_intent_id,
                resolution,
                priority_source,
                priority_value,
                drain_order,
                window,
            )
        window = self._queue_window_plan(
            entry,
            resolution,
            priority_source=priority_source,
            priority_value=priority_value,
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
            queue_window=window.to_json(),
        )

    def _queue_window_plan(
        self,
        entry: dict[str, JSONValue],
        resolution: QueueResolutionIR,
        *,
        priority_source: dict[str, JSONValue],
        priority_value: float,
    ) -> QueueWindowPlan:
        queue_kind = str(entry.get("queue_kind") or "")
        queue_window_id = str(entry.get("queue_window_id") or "")
        window_family = str(entry.get("window_family") or "")
        window_policy = entry.get("window_policy") if isinstance(entry.get("window_policy"), dict) else {}
        target_resolution = entry.get("target_resolution") if isinstance(entry.get("target_resolution"), dict) else {}
        if not queue_window_id or not window_family:
            return QueueWindowPlan(
                False,
                "blocked",
                "unknown",
                queue_kind,
                str(entry.get("queue_intent_id") or ""),
                resolution.queue_resolution_id,
                queue_priority_id=str(priority_source.get("queue_priority_id") or ""),
                queue_window_id=queue_window_id,
                window_family=window_family,
                priority_key=str(priority_source.get("priority_key") or ""),
                priority_value=priority_value,
                window_policy=window_policy,
                target_resolution=target_resolution,
                blocked_reason="queue_window_ir_missing_on_entry",
                source_trace={"queue_resolution_source": resolution.source.to_json(), "queue_entry": entry},
            )
        if target_resolution and target_resolution.get("ok") is not True:
            return QueueWindowPlan(
                False,
                "blocked",
                window_family,
                queue_kind,
                str(entry.get("queue_intent_id") or ""),
                resolution.queue_resolution_id,
                queue_priority_id=str(priority_source.get("queue_priority_id") or ""),
                queue_window_id=queue_window_id,
                window_family=window_family,
                priority_key=str(priority_source.get("priority_key") or ""),
                priority_value=priority_value,
                window_policy=window_policy,
                target_resolution=target_resolution,
                blocked_reason=str(target_resolution.get("blocked_reason") or "queue_target_resolution_not_admitted"),
                source_trace={"queue_resolution_source": resolution.source.to_json(), "queue_entry": entry},
            )
        if window_family not in QUEUE_WINDOW_FAMILY_ORDER or window_family in {"assistant", "unknown"}:
            return QueueWindowPlan(
                False,
                "blocked",
                window_family or "unknown",
                queue_kind,
                str(entry.get("queue_intent_id") or ""),
                resolution.queue_resolution_id,
                queue_priority_id=str(priority_source.get("queue_priority_id") or ""),
                queue_window_id=queue_window_id,
                window_family=window_family or "unknown",
                priority_key=str(priority_source.get("priority_key") or ""),
                priority_value=priority_value,
                window_policy=window_policy,
                target_resolution=target_resolution,
                blocked_reason=f"queue_window_family_not_admitted:{window_family or 'missing'}",
                source_trace={"queue_resolution_source": resolution.source.to_json(), "queue_entry": entry},
            )
        if window_policy.get("window_ordering_admitted") is False:
            return QueueWindowPlan(
                False,
                "blocked",
                window_family,
                queue_kind,
                str(entry.get("queue_intent_id") or ""),
                resolution.queue_resolution_id,
                queue_priority_id=str(priority_source.get("queue_priority_id") or ""),
                queue_window_id=queue_window_id,
                window_family=window_family,
                priority_key=str(priority_source.get("priority_key") or ""),
                priority_value=priority_value,
                window_policy=window_policy,
                target_resolution=target_resolution,
                blocked_reason=str(window_policy.get("blocking_dependency") or "queue_window_ordering_not_admitted"),
                source_trace={"queue_resolution_source": resolution.source.to_json(), "queue_entry": entry},
            )
        if window_family == "extra_turn" and window_policy.get("lifecycle_policy_admitted") is not True:
            return QueueWindowPlan(
                False,
                "blocked",
                window_family,
                queue_kind,
                str(entry.get("queue_intent_id") or ""),
                resolution.queue_resolution_id,
                queue_priority_id=str(priority_source.get("queue_priority_id") or ""),
                queue_window_id=queue_window_id,
                window_family=window_family,
                priority_key=str(priority_source.get("priority_key") or ""),
                priority_value=priority_value,
                window_policy=window_policy,
                target_resolution=target_resolution,
                blocked_reason=str(window_policy.get("blocking_dependency") or "extra_turn_lifecycle_policy_not_admitted"),
                source_trace={"queue_resolution_source": resolution.source.to_json(), "queue_entry": entry},
            )
        return QueueWindowPlan(
            True,
            "admitted",
            window_family,
            queue_kind,
            str(entry.get("queue_intent_id") or ""),
            resolution.queue_resolution_id,
            queue_priority_id=str(priority_source.get("queue_priority_id") or ""),
            queue_window_id=queue_window_id,
            window_family=window_family,
            priority_key=str(priority_source.get("priority_key") or ""),
            priority_value=priority_value,
            window_policy=window_policy,
            target_resolution=target_resolution,
            source_trace={"queue_resolution_source": resolution.source.to_json(), "queue_entry": entry},
        )

    def _resolve_action_candidate(
        self,
        state: BattleState,
        entry: dict[str, JSONValue],
        resolution: QueueResolutionIR,
    ) -> dict[str, JSONValue]:
        actor_id = str(entry.get("actor_id") or "")
        if not actor_id or actor_id not in state.units:
            return {"ok": False, "blocked_reason": "queue_action_actor_missing"}
        actor_ok, actor_reason = self.lifecycle.can_act(state, actor_id)
        if not actor_ok:
            return {"ok": False, "blocked_reason": f"queue_action_actor_{actor_reason}"}
        actor = state.units[actor_id]
        if not actor.template_id:
            return {"ok": False, "blocked_reason": "queue_action_actor_template_missing"}
        candidates = resolution.resolved_ids.get("action_set_candidates")
        if not isinstance(candidates, list):
            return {"ok": False, "blocked_reason": "queue_action_set_candidates_missing"}
        matches = [
            candidate
            for candidate in candidates
            if isinstance(candidate, dict) and candidate.get("entity_ref") == actor.template_id
        ]
        if not matches:
            return {
                "ok": False,
                "blocked_reason": f"queue_action_set_not_resolved_for_actor:{actor.template_id}",
            }
        if len(matches) > 1:
            return {
                "ok": False,
                "blocked_reason": f"queue_action_set_ambiguous_for_actor:{actor.template_id}",
            }
        match = matches[0]
        action_id = match.get("action_ref")
        action_level = match.get("action_level")
        if not isinstance(action_id, str) or not action_id:
            return {"ok": False, "blocked_reason": "queue_action_ref_missing"}
        if not isinstance(action_level, int):
            return {"ok": False, "blocked_reason": "queue_action_level_missing"}
        target_ids = entry.get("target_ids")
        if not isinstance(target_ids, list) or not any(isinstance(item, str) and item for item in target_ids):
            return {"ok": False, "blocked_reason": "queue_action_target_missing"}
        invalid_targets = tuple(
            str(item)
            for item in target_ids
            if isinstance(item, str)
            and item
            and not self.lifecycle.can_target(state, item, allow_defeated=False)[0]
        )
        if invalid_targets:
            reasons = [
                f"{self.lifecycle.can_target(state, target_id, allow_defeated=False)[1]}:{target_id}"
                for target_id in invalid_targets
            ]
            return {"ok": False, "blocked_reason": f"queue_action_target_lifecycle_blocked:{','.join(reasons)}"}
        return {
            "ok": True,
            "action_id": action_id,
            "action_level": action_level,
            "combatant_action_set_id": str(match.get("combatant_action_set_id") or ""),
        }

    def _blocked_with_window(
        self,
        queue_name: str,
        entry: dict[str, JSONValue],
        queue_intent_id: str,
        resolution: QueueResolutionIR,
        priority_source: dict[str, JSONValue],
        priority_value: float,
        drain_order: int | None,
        window: QueueWindowPlan,
    ) -> QueueDrainPlan:
        return QueueDrainPlan(
            False,
            "blocked",
            queue_name,
            entry,
            queue_intent_id,
            resolution.queue_resolution_id,
            window.blocked_reason or f"queue_window_not_admitted:{window.window_kind}",
            {"queue_resolution_source": resolution.source.to_json()},
            queue_priority_id=str(priority_source.get("queue_priority_id") or ""),
            priority_key=str(priority_source.get("priority_key") or ""),
            priority_value=priority_value,
            resolved_kind=resolution.resolved_kind,
            drain_order=drain_order,
            queue_window=window.to_json(),
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
            before=list(current) if queue_name in state.queues else None,
            after=list(updated),
            reason="enqueue action",
            source=source,
            before_exists=queue_name in state.queues,
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
            before=list(current) if queue_name in state.queues else None,
            after=list(updated),
            reason="dequeue action",
            source=source,
            before_exists=queue_name in state.queues,
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
                "queue_window_plan": plan.queue_window or {},
                "queue_window_id": (plan.queue_window or {}).get("queue_window_id", ""),
                "window_family": (plan.queue_window or {}).get("window_family", ""),
                "target_resolution": (plan.queue_window or {}).get("target_resolution", {}),
                "resolved_action_id": plan.resolved_action_id,
                "resolved_action_level": plan.resolved_action_level,
            },
        )


def _first_nonempty_tuple(*values: Any) -> tuple[str, ...]:
    for value in values:
        result = _nonempty_tuple(value)
        if result:
            return result
    return ()


def _nonempty_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str) and value:
        return (value,)
    if isinstance(value, (tuple, list)):
        return tuple(str(item) for item in value if isinstance(item, str) and item)
    return ()


def _units_by_relative_side(state: BattleState, actor_id: str, *, enemy: bool) -> tuple[str, ...]:
    actor = state.units.get(actor_id)
    if actor is None:
        return ()
    lifecycle = UnitLifecycleSystem()

    return tuple(
        unit_id
        for unit_id, unit in sorted(state.units.items())
        if (is_opposing_combat_team(actor, unit) if enemy else is_same_combat_team(actor, unit))
        and lifecycle.can_target(state, unit_id, allow_defeated=False)[0]
    )
