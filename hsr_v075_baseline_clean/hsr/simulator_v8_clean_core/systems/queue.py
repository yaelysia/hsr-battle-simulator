from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..core.model import (
    ActionCommand, BattleState, GameEvent, JSONValue, Mutation, QueueActionStartFact, QueueActionTerminalFact, TargetResolution,
    _QUEUE_ACTION_START_PRODUCER, _QUEUE_ACTION_TERMINAL_PRODUCER,
)
from ..core.settlement import SettlementRecord
from ..rules.ir import QueueResolutionIR
from .mutation_events import mutation_backed_event_id
from .unit_relation import is_opposing_combat_team, is_same_combat_team
from .unit_lifecycle import UnitLifecycleSystem

if TYPE_CHECKING:
    from ..rules.rulebook import RuleBook
    from .action_selection import ActionTargetSelectionContext


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


DEATHRATTLE_ADMISSION_FIELDS = frozenset({
    "unit_id",
    "death_instance_id",
    "hp_mutation_id",
    "source_event_id",
    "source_status_instance_id",
    "source_modifier_name",
    "ability_name",
    "queue_intent_id",
    "queue_kind",
    "source_task_id",
})


@dataclass(frozen=True)
class DeathrattleQueueAdmission:
    """Limited queue authority for one unit's own Deathrattle insert.

    A unit that has just been finally defeated can still enqueue its source
    Deathrattle animation ability (OwnerAliveState/TargetAliveState
    Mask_AliveOrLimbo, CanRunOnUnselectableTarget). The permission is bound to
    the concrete death instance, the lethal HP mutation, the committed death
    event, the Deathrattle modifier instance and the formal queue intent that
    produced the callback. It does not admit any other defeated unit, any other
    queue intent, or a changed death record.
    """

    unit_id: str
    death_instance_id: str
    hp_mutation_id: str
    source_event_id: str
    source_status_instance_id: str
    source_modifier_name: str
    ability_name: str
    queue_intent_id: str
    queue_kind: str
    source_task_id: str

    def __post_init__(self) -> None:
        values = (
            self.unit_id,
            self.death_instance_id,
            self.hp_mutation_id,
            self.source_event_id,
            self.source_status_instance_id,
            self.source_modifier_name,
            self.ability_name,
            self.queue_intent_id,
            self.queue_kind,
            self.source_task_id,
        )
        if any(type(value) is not str or not value for value in values):
            raise ValueError("deathrattle_queue_admission_identity_invalid")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "unit_id": self.unit_id,
            "death_instance_id": self.death_instance_id,
            "hp_mutation_id": self.hp_mutation_id,
            "source_event_id": self.source_event_id,
            "source_status_instance_id": self.source_status_instance_id,
            "source_modifier_name": self.source_modifier_name,
            "ability_name": self.ability_name,
            "queue_intent_id": self.queue_intent_id,
            "queue_kind": self.queue_kind,
            "source_task_id": self.source_task_id,
        }

    @staticmethod
    def from_json(raw: object) -> "DeathrattleQueueAdmission":
        # Queue entries live in the frozen JSON snapshot, so the mapping is a
        # dict-compatible immutable view rather than a plain dict.
        if not isinstance(raw, dict) or set(raw) != DEATHRATTLE_ADMISSION_FIELDS:
            raise ValueError("deathrattle_queue_admission_shape_invalid")
        return DeathrattleQueueAdmission(
            **{field: raw[field] for field in DEATHRATTLE_ADMISSION_FIELDS}
        )

    def entry_contract_blocked_reason(self, entry: dict[str, JSONValue]) -> str:
        targets = QueueActionTerminalFact.accepted_entry_target_ids(entry)
        if targets is None:
            return "queue_entry_target_identity_invalid"
        if (
            str(entry.get("actor_id") or "") != self.unit_id
            or str(entry.get("queue_intent_id") or "") != self.queue_intent_id
            or str(entry.get("action_or_ability_ref") or "") != self.ability_name
            or str(entry.get("queue_kind") or "") != self.queue_kind
            or str(entry.get("owner_alive_state") or "") != "alive_or_limbo"
            or str(entry.get("target_alive_state") or "") != "alive_or_limbo"
            or entry.get("can_run_on_unselectable_target") is not True
        ):
            return f"queue_owner_deathrattle_contract_mismatch:{self.unit_id}"
        if any(target_id != self.unit_id for target_id in targets):
            return f"queue_target_deathrattle_target_not_admitted:{self.unit_id}"
        return ""

    def resolution_blocked_reason(
        self,
        entry: dict[str, JSONValue],
        resolution: QueueResolutionIR | None,
        rules: "RuleBook | None",
    ) -> str:
        """Re-verify the formal intent and resolution body for this authority.

        The queue entry, the RuleBook intent and the resolution object actually
        passed to the drain must all describe the same ability. A hand-made
        resolution that merely reuses the admitted ability name is not enough.
        """

        if rules is None:
            return f"queue_owner_deathrattle_rulebook_missing:{self.unit_id}"
        intent = rules.queue_intent(self.queue_intent_id)
        formal = rules.queue_resolution_for_intent(self.queue_intent_id)
        if intent is None:
            return f"queue_owner_deathrattle_intent_missing:{self.queue_intent_id}"
        if formal is None:
            return f"queue_owner_deathrattle_resolution_missing:{self.queue_intent_id}"
        if (
            intent.action_ref_or_ability_name != self.ability_name
            or intent.queue_kind != self.queue_kind
            or intent.source_task_id != self.source_task_id
            or intent.owner_alive_state != "alive_or_limbo"
            or intent.target_alive_state != "alive_or_limbo"
            or intent.can_run_on_unselectable_target is not True
            or intent.coverage_status != "executable"
            or intent.blocked_reason
        ):
            return f"queue_owner_deathrattle_intent_mismatch:{self.queue_intent_id}"
        callback = rules.status_callback(intent.callback_id)
        task = rules.status_callback_task(self.source_task_id)
        if (
            callback is None
            or task is None
            or callback.event != "OnDeathrattle"
            or task.event != "OnDeathrattle"
            or task.callback_id != callback.callback_id
            or task.task_id not in callback.task_ids
            or task.modifier_name != self.source_modifier_name
            or callback.modifier_name != self.source_modifier_name
            or callback.coverage_status != "executable"
            or callback.blocked_reason
            or task.coverage_status != "executable"
            or task.blocked_reason
        ):
            return (
                "queue_owner_deathrattle_source_callback_not_admitted:"
                f"{self.queue_intent_id}"
            )
        if resolution is None or resolution != formal:
            return f"queue_owner_deathrattle_resolution_mismatch:{self.queue_intent_id}"
        if (
            resolution.queue_intent_id != self.queue_intent_id
            or resolution.action_or_ability_ref != self.ability_name
            or resolution.coverage_status != "executable"
            or resolution.resolved_kind != formal.resolved_kind
        ):
            return f"queue_owner_deathrattle_resolution_mismatch:{self.queue_intent_id}"
        if resolution.resolved_kind == "standalone_ability_graph":
            executable = resolution.resolved_ids.get("executable_task_ids")
            if not isinstance(executable, (list, tuple)) or not executable:
                return f"queue_owner_deathrattle_body_missing:{self.queue_intent_id}"
        return ""

    def blocked_reason(self, state: BattleState) -> str:
        unit = state.units.get(self.unit_id)
        if unit is None:
            return f"deathrattle_admission_unit_missing:{self.unit_id}"
        lifecycle_status = UnitLifecycleSystem().status_of(unit)
        if lifecycle_status == "removed":
            return f"deathrattle_admission_unit_removed:{self.unit_id}"
        if lifecycle_status != "defeated":
            return f"deathrattle_admission_unit_not_defeated:{self.unit_id}"
        record = unit.flags.get("defeat_record")
        if not isinstance(record, dict):
            return f"deathrattle_admission_defeat_record_missing:{self.unit_id}"
        if str(record.get("lifecycle_mutation_id") or "") != self.death_instance_id:
            return f"deathrattle_admission_death_instance_mismatch:{self.unit_id}"
        if (
            str(record.get("hp_mutation_id") or "") != self.hp_mutation_id
            or str(record.get("target_id") or "") != self.unit_id
            or str(record.get("defeated_unit_id") or "") != self.unit_id
        ):
            return f"deathrattle_admission_hp_mutation_mismatch:{self.unit_id}"
        expected_event_id = mutation_backed_event_id(
            self.death_instance_id, "unit.defeated"
        )
        if self.source_event_id != expected_event_id:
            return f"deathrattle_admission_source_event_mismatch:{self.unit_id}"
        matching = [
            detail
            for detail in unit.flags.get("status_details", ())
            if isinstance(detail, dict)
            and str(detail.get("instance_id") or "") == self.source_status_instance_id
        ]
        if len(matching) != 1:
            return f"deathrattle_admission_source_status_missing:{self.unit_id}"
        detail = matching[0]
        if (
            str(detail.get("modifier_name") or "") != self.source_modifier_name
            or str(detail.get("owner_id") or "") != self.unit_id
        ):
            return f"deathrattle_admission_source_modifier_mismatch:{self.unit_id}"
        if "Deathrattle" not in tuple(detail.get("behavior_flags") or ()):
            return f"deathrattle_admission_source_flag_missing:{self.unit_id}"
        if str(detail.get("lifecycle_state") or "active").startswith(
            ("expired", "removed")
        ):
            return f"deathrattle_admission_source_status_inactive:{self.unit_id}"
        if float(unit.hp) > 0:
            return f"deathrattle_admission_unit_not_defeated:{self.unit_id}"
        return ""


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
    action_level: int | None = None
    resource_policy: dict[str, JSONValue] | None = None
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
    elation_override_points: float | None = None
    custom_tag: str = ""
    insert_abort: dict[str, JSONValue] | None = None
    owner_alive_state: str = "alive_only"
    target_alive_state: str = "alive_only"
    can_run_on_unselectable_target: bool = False
    deathrattle_admission: dict[str, JSONValue] | None = None

    def __post_init__(self) -> None:
        value = self.elation_override_points
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ValueError("queue_elation_override_points_invalid")
        admitted_states = {"alive_only", "alive_or_limbo", "alive_or_revivable"}
        if self.owner_alive_state not in admitted_states or self.target_alive_state not in admitted_states:
            raise ValueError("queue_entry_alive_state_not_admitted")
        if type(self.can_run_on_unselectable_target) is not bool:
            raise ValueError("queue_entry_unselectable_permission_invalid")
        if self.deathrattle_admission is not None:
            DeathrattleQueueAdmission.from_json(self.deathrattle_admission)

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
            "action_level": self.action_level,
            "resource_policy": self.resource_policy or {},
            "status": self.status,
            "drain_status": self.drain_status,
            "elation_override_points": self.elation_override_points,
            "custom_tag": self.custom_tag,
            "insert_abort": self.insert_abort or {},
            "owner_alive_state": self.owner_alive_state,
            "target_alive_state": self.target_alive_state,
            "can_run_on_unselectable_target": self.can_run_on_unselectable_target,
            "deathrattle_admission": self.deathrattle_admission or {},
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


@dataclass(frozen=True)
class QueueEntryTerminalPlan:
    ok: bool
    disposition: str
    queue_name: str
    entry_id: str
    blocked_reason: str
    retained: bool
    source_trace: dict[str, JSONValue]
    before_length: int
    after_length: int
    waiting_for_windows: tuple[str, ...] = ()
    replacement_target_ids: tuple[str, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "disposition": self.disposition,
            "queue_name": self.queue_name,
            "entry_id": self.entry_id,
            "blocked_reason": self.blocked_reason,
            "retained": self.retained,
            "source_trace": self.source_trace,
            "before_length": self.before_length,
            "after_length": self.after_length,
            "waiting_for_windows": list(self.waiting_for_windows),
            "replacement_target_ids": list(self.replacement_target_ids),
            "monotonic_progress": (
                self.after_length < self.before_length
                or bool(self.waiting_for_windows)
                or bool(self.replacement_target_ids)
            ),
        }


@dataclass(frozen=True)
class QueueEntryTerminalResult:
    plan: QueueEntryTerminalPlan
    mutations: tuple[Mutation, ...]
    events: tuple[GameEvent, ...]
    records: tuple[dict[str, JSONValue], ...]


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
QUEUE_DRAIN_STEP_BUDGET = 1


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
        allow_unselectable_target: bool = False,
        deathrattle_admission: "DeathrattleQueueAdmission | None" = None,
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
        if deathrattle_admission is not None:
            # The admitted death instance carries limited authority for this
            # unit's own Deathrattle insert; ordinary actor liveness still
            # applies to every other queue request.
            if actor_id != deathrattle_admission.unit_id:
                return QueueTargetResolution(
                    False,
                    actor_id,
                    (),
                    actor_alias or "",
                    target_alias or "",
                    f"queue_actor_deathrattle_unit_mismatch:{actor_id}",
                    source_trace,
                )
            admission_reason = deathrattle_admission.blocked_reason(state)
            if admission_reason:
                return QueueTargetResolution(
                    False,
                    actor_id,
                    (),
                    actor_alias or "",
                    target_alias or "",
                    f"queue_actor_{admission_reason}:{actor_id}",
                    source_trace,
                )
        else:
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
            if not _queue_target_admitted(
                self.lifecycle, state, target_id,
                allow_unselectable=allow_unselectable_target,
                deathrattle_unit_id=(
                    deathrattle_admission.unit_id
                    if deathrattle_admission is not None
                    else ""
                ),
            )
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
        *,
        rules: "RuleBook | None" = None,
    ) -> QueueDrainPlan:
        entry = self.peek(state, queue_name)
        return self._plan_entry(
            state, queue_name, entry, resolution, drain_order=0, rules=rules
        )

    def plan_next_drain(
        self,
        state: BattleState,
        queue_name: str,
        resolutions_by_intent: dict[str, QueueResolutionIR],
        *,
        rules: "RuleBook | None" = None,
    ) -> QueueDrainPlan:
        entries = self._entries(state, queue_name)
        if not entries:
            waiting = next(
                (
                    entry
                    for entry in state.queues.get(queue_name, ())
                    if isinstance(entry, dict) and _waiting_for_other_window(state, entry)
                ),
                None,
            )
            if waiting is not None:
                return QueueDrainPlan(
                    False,
                    "waiting_window",
                    queue_name,
                    waiting,
                    str(waiting.get("queue_intent_id") or ""),
                    str(waiting.get("queue_resolution_id") or ""),
                    "queue_waiting_for_window",
                    {"queue_entry_source": waiting.get("source_trace", {})},
                    queue_window={
                        "window_family": str(waiting.get("window_family") or ""),
                        "waiting_for_windows": waiting.get("waiting_for_windows", []),
                    },
                )
            return QueueDrainPlan(False, "blocked", queue_name, {}, "", "", "queue_empty_or_legacy_entry")
        plans = [
            self._plan_entry(
                state,
                queue_name,
                entry,
                resolutions_by_intent.get(str(entry.get("queue_intent_id") or "")),
                drain_order=index,
                rules=rules,
            )
            for index, entry in enumerate(entries)
        ]
        if not plans[0].ok:
            return plans[0]
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
        return tuple(
            entry
            for entry in state.queues.get(queue_name, ())
            if isinstance(entry, dict) and not _waiting_for_other_window(state, entry)
        )

    def _plan_entry(
        self,
        state: BattleState,
        queue_name: str,
        entry: dict[str, JSONValue] | None,
        resolution: QueueResolutionIR | None,
        *,
        drain_order: int | None,
        rules: "RuleBook | None" = None,
    ) -> QueueDrainPlan:
        if entry is None:
            return QueueDrainPlan(False, "blocked", queue_name, {}, "", "", "queue_empty_or_legacy_entry")
        queue_intent_id = str(entry.get("queue_intent_id") or "")
        if not queue_intent_id:
            return QueueDrainPlan(False, "blocked", queue_name, entry, "", "", "queue_entry_missing_intent_id")
        abort_reason = _abort_behavior_blocked_reason(state, entry)
        alive_state_reason = _entry_alive_state_blocked_reason(state, entry)
        if alive_state_reason:
            abort_reason = alive_state_reason
        _, actor_reason = self.lifecycle.can_act(state, str(entry.get("actor_id") or ""))
        if (
            not alive_state_reason
            and not _entry_deathrattle_admitted(state, entry)
            and actor_reason in {"unit_defeated", "unit_removed", "unit_departed"}
        ):
            abort_reason = f"queue_action_actor_{actor_reason}"
        if abort_reason:
            return QueueDrainPlan(
                False, "blocked", queue_name, entry, queue_intent_id, "", abort_reason,
                {"queue_entry_source": entry.get("source_trace", {})}, drain_order=drain_order,
            )
        source_status_reason = _source_status_blocked_reason(state, entry)
        if source_status_reason:
            return QueueDrainPlan(
                False,
                "blocked",
                queue_name,
                entry,
                queue_intent_id,
                "",
                source_status_reason,
                {"queue_entry_source": entry.get("source_trace", {})},
                drain_order=drain_order,
            )
        expiration_reason = _expiration_blocked_reason(state, entry)
        if expiration_reason:
            return QueueDrainPlan(
                False,
                "blocked",
                queue_name,
                entry,
                queue_intent_id,
                "",
                expiration_reason,
                {"queue_entry_source": entry.get("source_trace", {})},
                drain_order=drain_order,
            )
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
        try:
            deathrattle_admission = deathrattle_admission_from_entry(entry)
        except ValueError as exc:
            return QueueDrainPlan(
                False,
                "blocked",
                queue_name,
                entry,
                queue_intent_id,
                resolution.queue_resolution_id,
                f"queue_owner_deathrattle_admission_invalid:{exc}",
                {"queue_resolution_source": resolution.source.to_json()},
                resolved_kind=resolution.resolved_kind,
                drain_order=drain_order,
            )
        if deathrattle_admission is not None:
            formal_reason = deathrattle_admission.resolution_blocked_reason(
                entry, resolution, rules
            )
            if formal_reason:
                return QueueDrainPlan(
                    False,
                    "blocked",
                    queue_name,
                    entry,
                    queue_intent_id,
                    resolution.queue_resolution_id,
                    formal_reason,
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
            action_match = self._resolve_action_candidate(
                state, entry, resolution, rules=rules
            )
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
        *,
        rules: "RuleBook | None" = None,
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
        level_source = "action_set_default_level"
        skill_index_key = resolution.resolved_ids.get("skill_index")
        if rules is not None and isinstance(skill_index_key, str) and skill_index_key:
            # The actual action comes from the acting unit's combatant action set;
            # the precompiled candidate list only cross-checks it.
            action_set = rules.combatant_action_set(actor.template_id)
            if action_set is None:
                return {
                    "ok": False,
                    "blocked_reason": f"queue_action_set_missing_for_actor:{actor.template_id}",
                }
            slot = action_set.skill_index_map.get(skill_index_key)
            if not isinstance(slot, dict) or not isinstance(slot.get("action_ref"), str):
                return {
                    "ok": False,
                    "blocked_reason": (
                        f"queue_action_set_slot_missing:{actor.template_id}:{skill_index_key}"
                    ),
                }
            if slot["action_ref"] != action_id:
                return {
                    "ok": False,
                    "blocked_reason": (
                        f"queue_action_set_candidate_mismatch:{action_id}:{slot['action_ref']}"
                    ),
                }
            levels = actor.flags.get("effective_skill_levels_by_action_id")
            effective_level = levels.get(action_id) if isinstance(levels, dict) else None
            if isinstance(effective_level, int) and not isinstance(effective_level, bool):
                action_level = effective_level
                level_source = "effective_skill_levels_by_action_id"
            elif isinstance(action_level, int):
                level_source = "action_set_default_level"
            if rules.action_definition(action_id, int(action_level)) is None:
                return {
                    "ok": False,
                    "blocked_reason": f"queue_action_effective_definition_missing:{action_id}:{action_level}",
                }
        if not isinstance(action_id, str) or not action_id:
            return {"ok": False, "blocked_reason": "queue_action_ref_missing"}
        if not isinstance(action_level, int):
            return {"ok": False, "blocked_reason": "queue_action_level_missing"}
        target_ids = entry.get("target_ids")
        if (
            not isinstance(target_ids, list)
            or any(not isinstance(item, str) or not item for item in target_ids)
            or len(target_ids) != len(set(target_ids))
        ):
            return {"ok": False, "blocked_reason": "queue_action_target_payload_malformed"}
        return {
            "ok": True,
            "action_id": action_id,
            "action_level": action_level,
            "level_source": level_source,
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
        requested_operation = (
            str(metadata.get("queue_operation") or "dequeue")
            if isinstance(metadata, dict)
            else "dequeue"
        )
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
                "queue_operation": requested_operation,
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

    def plan_terminal_resolution(
        self,
        state: BattleState,
        plan: QueueDrainPlan,
        *,
        blocked_reason: str | None = None,
    ) -> QueueEntryTerminalPlan:
        entry = plan.queue_entry
        entry_id = str(entry.get("entry_id") or "")
        reason = blocked_reason or plan.blocked_reason or "queue_entry_execution_blocked"
        current = tuple(state.queues.get(plan.queue_name, ()))
        source_trace = _terminal_source_trace(plan)
        if not _is_gameplay_abort(state, entry, reason):
            return QueueEntryTerminalPlan(
                ok=False, disposition="blocked", queue_name=plan.queue_name,
                entry_id=entry_id, blocked_reason=reason, retained=True,
                source_trace=source_trace, before_length=len(current), after_length=len(current),
            )
        cancel_policy = entry.get("cancel_policy") if isinstance(entry.get("cancel_policy"), dict) else {}
        wait_for_windows = _admitted_wait_windows(cancel_policy, source_trace)
        current_window = str(state.global_flags.get("current_window") or "")
        if wait_for_windows and current_window not in wait_for_windows:
            return QueueEntryTerminalPlan(
                ok=True,
                disposition="waiting_window",
                queue_name=plan.queue_name,
                entry_id=entry_id,
                blocked_reason=reason,
                retained=True,
                source_trace=source_trace,
                before_length=len(current),
                after_length=len(current),
                waiting_for_windows=wait_for_windows,
            )
        replacement_targets = _admitted_retarget_ids(state, cancel_policy, source_trace)
        if replacement_targets:
            return QueueEntryTerminalPlan(
                ok=True,
                disposition="retargeted",
                queue_name=plan.queue_name,
                entry_id=entry_id,
                blocked_reason=reason,
                retained=True,
                source_trace=source_trace,
                before_length=len(current),
                after_length=len(current),
                replacement_target_ids=replacement_targets,
            )
        return QueueEntryTerminalPlan(
            ok=True,
            disposition="cancelled",
            queue_name=plan.queue_name,
            entry_id=entry_id,
            blocked_reason=reason,
            retained=False,
            source_trace=source_trace,
            before_length=len(current),
            after_length=max(0, len(current) - 1),
        )

    def resolve_terminal(
        self,
        state: BattleState,
        terminal: QueueEntryTerminalPlan,
    ) -> QueueEntryTerminalResult:
        if not terminal.ok:
            return QueueEntryTerminalResult(terminal, (), (), ())
        current = tuple(state.queues.get(terminal.queue_name, ()))
        index = next(
            (
                item_index
                for item_index, item in enumerate(current)
                if isinstance(item, dict) and str(item.get("entry_id") or "") == terminal.entry_id
            ),
            -1,
        )
        if index < 0:
            raise ValueError(f"queue terminal entry not found: {terminal.entry_id}")
        entry = current[index]
        assert isinstance(entry, dict)
        if terminal.disposition == "cancelled":
            priority_source = entry.get("priority_source") if isinstance(entry.get("priority_source"), dict) else {}
            mutation = self.dequeue_entry(
                state,
                terminal.queue_name,
                terminal.entry_id,
                "queue_system",
                metadata={
                    "queue_operation": "terminal_remove",
                    "queue_terminal_plan": terminal.to_json(),
                    "queue_terminal_disposition": terminal.disposition,
                    "queue_intent_id": str(entry.get("queue_intent_id") or ""),
                    "queue_resolution_id": str(terminal.source_trace.get("queue_resolution_id") or entry.get("queue_resolution_id") or ""),
                    "queue_priority_id": str(entry.get("queue_priority_id") or priority_source.get("queue_priority_id") or ""),
                    "priority_key": str(entry.get("priority_key") or priority_source.get("priority_key") or ""),
                    "priority_value": entry.get("priority_value", priority_source.get("priority_value")),
                    "queue_window_id": str(entry.get("queue_window_id") or ""),
                    "window_family": str(entry.get("window_family") or ""),
                    "queue_window_plan": {
                        "queue_window_id": str(entry.get("queue_window_id") or ""),
                        "window_family": str(entry.get("window_family") or ""),
                        "window_policy": entry.get("window_policy") if isinstance(entry.get("window_policy"), dict) else {},
                    },
                    "source_trace": terminal.source_trace,
                },
            )
        else:
            updated_entry = dict(entry)
            if terminal.disposition == "waiting_window":
                updated_entry.update(
                    {
                        "status": "waiting_window",
                        "drain_status": "waiting_window",
                        "waiting_for_windows": list(terminal.waiting_for_windows),
                        "last_blocked_reason": terminal.blocked_reason,
                    }
                )
            elif terminal.disposition == "retargeted":
                updated_entry.update(
                    {
                        "target_ids": list(terminal.replacement_target_ids),
                        "status": "pending",
                        "drain_status": "retargeted",
                        "last_blocked_reason": terminal.blocked_reason,
                    }
                )
            else:
                raise ValueError(f"unsupported queue terminal disposition: {terminal.disposition}")
            updated = (*current[:index], updated_entry, *current[index + 1 :])
            mutation = Mutation(
                op="set",
                path=("queues", terminal.queue_name),
                before=list(current),
                after=list(updated),
                reason=f"queue entry terminal transition: {terminal.disposition}",
                source="queue_system",
                metadata={
                    "queue_name": terminal.queue_name,
                    "queue_operation": "terminal_transition",
                    "queue_entry": entry,
                    "queue_intent_id": str(entry.get("queue_intent_id") or ""),
                    "queue_priority_id": str(entry.get("queue_priority_id") or ""),
                    "queue_window_id": str(entry.get("queue_window_id") or ""),
                    "window_family": str(entry.get("window_family") or ""),
                    "queue_terminal_plan": terminal.to_json(),
                    "queue_terminal_disposition": terminal.disposition,
                    "source_trace": terminal.source_trace,
                },
            )
        payload = {
            "queue_terminal_plan": terminal.to_json(),
            "queue_entry": entry,
            "mutation_path": list(mutation.path),
        }
        event = GameEvent(
            "queue.entry.terminal",
            source_id=str(entry.get("actor_id") or ""),
            event_id=f"event:{state.event_index}:queue_terminal:{terminal.entry_id}:{terminal.disposition}",
            window="queue",
            process_only=True,
            payload=payload,
        )
        record = SettlementRecord(
            record_type="queue_entry_terminal",
            source="queue_system",
            mutation_id=mutation.stable_id(),
            process_only=False,
            payload=payload,
            trace=terminal.source_trace,
        ).to_json()
        abort_events = (
            (self.action_terminal_event(state, mutation, cancelled=True),)
            if terminal.disposition == "cancelled" and _is_gameplay_abort(state, entry, terminal.blocked_reason)
            else ()
        )
        return QueueEntryTerminalResult(terminal, (mutation,), (event, *abort_events), (record,))

    def abort_unused_insert_entries_for_unit(
        self,
        state: BattleState,
        unit_id: str,
        *,
        reason: str,
        source_trace: dict[str, JSONValue],
    ) -> tuple[tuple[Mutation, ...], tuple[GameEvent, ...], tuple[dict[str, JSONValue], ...]]:
        """Cancel the not-yet-started insert entries owned by one unit.

        ForceKill's AbortUnusedInsertAbility removes the dying unit's own unused
        inserted abilities. Entries of other units and entries that only target
        this unit stay in place, in their original order; the currently
        executing consumer is already dequeued and is not affected.
        """

        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        records: list[dict[str, JSONValue]] = []
        for queue_name in sorted(state.queues):
            current = tuple(state.queues.get(queue_name, ()))
            if not current:
                continue
            kept = list(current)
            for entry in current:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("actor_id") or "") != unit_id:
                    continue
                entry_id = str(entry.get("entry_id") or "")
                if not entry_id:
                    continue
                index = next(
                    (position for position, item in enumerate(kept)
                     if isinstance(item, dict) and item.get("entry_id") == entry_id),
                    -1,
                )
                if index < 0:
                    continue
                priority_source = entry.get("priority_source") if isinstance(entry.get("priority_source"), dict) else {}
                entry_source = entry.get("source_trace") if isinstance(entry.get("source_trace"), dict) else {}
                terminal = QueueEntryTerminalPlan(
                    ok=True,
                    disposition="cancelled",
                    queue_name=queue_name,
                    entry_id=entry_id,
                    blocked_reason=reason,
                    retained=False,
                    source_trace={
                        **source_trace,
                        "queue_entry_source": entry_source,
                        "queue_intent_id": str(entry.get("queue_intent_id") or ""),
                        "queue_resolution_id": str(entry.get("queue_resolution_id") or ""),
                    },
                    before_length=len(kept),
                    after_length=len(kept) - 1,
                )
                updated = kept[:index] + kept[index + 1:]
                mutation = Mutation(
                    "set",
                    ("queues", queue_name),
                    list(kept),
                    list(updated),
                    "abort unused insert ability of the force-killed unit",
                    "queue_system",
                    before_exists=queue_name in state.queues,
                    metadata={
                        "queue_name": queue_name,
                        "queue_operation": "terminal_remove",
                        "queue_intent_id": str(entry.get("queue_intent_id") or ""),
                        "queue_resolution_id": str(entry.get("queue_resolution_id") or ""),
                        "queue_priority_id": str(entry.get("queue_priority_id") or priority_source.get("queue_priority_id") or ""),
                        "priority_key": str(entry.get("priority_key") or priority_source.get("priority_key") or ""),
                        "priority_value": entry.get("priority_value", priority_source.get("priority_value")),
                        "queue_window_id": str(entry.get("queue_window_id") or ""),
                        "window_family": str(entry.get("window_family") or ""),
                        "queue_window_plan": {
                            "queue_window_id": str(entry.get("queue_window_id") or ""),
                            "window_family": str(entry.get("window_family") or ""),
                            "window_policy": entry.get("window_policy") if isinstance(entry.get("window_policy"), dict) else {},
                        },
                        "queue_entry": entry,
                        "queue_terminal_plan": terminal.to_json(),
                        "queue_terminal_disposition": terminal.disposition,
                        "queue_cleanup_operation": "abort_unused_insert_ability",
                        "source_trace": terminal.source_trace,
                    },
                )
                payload = {
                    "queue_terminal_plan": terminal.to_json(),
                    "queue_entry": entry,
                    "mutation_path": list(mutation.path),
                    "cleanup_operation": "abort_unused_insert_ability",
                }
                mutations.append(mutation)
                events.append(GameEvent(
                    "queue.entry.terminal",
                    source_id=unit_id,
                    event_id=f"event:{state.event_index}:queue_terminal:{entry_id}:cancelled",
                    window="queue",
                    process_only=True,
                    payload=payload,
                ))
                records.append(SettlementRecord(
                    record_type="queue_entry_terminal",
                    source="queue_system",
                    mutation_id=mutation.stable_id(),
                    process_only=False,
                    payload=payload,
                    trace=terminal.source_trace,
                ).to_json())
                kept = updated
        return tuple(mutations), tuple(events), tuple(records)

    def action_start_event(
        self, state: BattleState, mutation: Mutation, *,
        accepted_command: ActionCommand | None = None,
        accepted_selection_context: ActionTargetSelectionContext | None = None,
        rules: RuleBook | None = None,
    ) -> GameEvent:
        entry = mutation.metadata.get("queue_entry")
        if not isinstance(entry, dict):
            raise ValueError("queue start requires its removed entry")
        if accepted_command is not None:
            from ..rules.rulebook import RuleBook
            from .action_selection import ActionTargetSelectionSystem

            if type(accepted_command) is not ActionCommand or type(rules) is not RuleBook:
                raise ValueError("queue start requires a typed command and its RuleBook")
            reason = ActionTargetSelectionSystem(rules).context_blocked_reason(
                state, accepted_command, accepted_selection_context,
            )
            if reason:
                raise ValueError(f"queue start selection not accepted:{reason}")
            assert accepted_selection_context is not None
            targets = accepted_selection_context.accepted.selected_target_ids
        else:
            if accepted_selection_context is not None:
                raise ValueError("queue start selection requires its command")
            targets = QueueActionTerminalFact.accepted_entry_target_ids(entry)
            if targets is None:
                raise ValueError("queue start accepted targets are invalid")
        event_id = f"event:{state.event_index}:queue.action.before:{mutation.stable_id()}"
        fact = QueueActionStartFact(
            source_mutation=mutation, event_id=event_id, event_index=state.event_index,
            actor_id=str(entry.get("actor_id") or ""), target_ids=targets,
            _state=state, _producer_token=_QUEUE_ACTION_START_PRODUCER,
            accepted_command=accepted_command,
        )
        return GameEvent(
            "queue.action.before", source_id=fact.actor_id, event_id=event_id, window="queue",
            process_only=True, queue_action_start_fact=fact,
            payload={"queue_entry": entry, "queue_mutation_id": mutation.stable_id(),
                     "actor_id": fact.actor_id, "target_ids": list(fact.target_ids),
                     "queue_intent_id": fact.queue_intent_id, "custom_tag": fact.custom_tag},
        )

    def action_terminal_event(
        self, state: BattleState, mutation: Mutation, *, cancelled: bool = False,
        completed_command: ActionCommand | None = None,
        completed_target_resolution: TargetResolution | None = None,
    ) -> GameEvent:
        entry = mutation.metadata["queue_entry"]
        assert isinstance(entry, dict)
        event_type = "queue.action.abort" if cancelled else "queue.action.after"
        event_id = f"event:{state.event_index}:{event_type}:{mutation.stable_id()}"
        fact = QueueActionTerminalFact(
            source_mutation=mutation, event_id=event_id, event_index=state.event_index,
            event_type=event_type, actor_id=str(entry.get("actor_id") or ""),
            _producer_token=_QUEUE_ACTION_TERMINAL_PRODUCER,
            completed_command=completed_command,
            completed_target_resolution=completed_target_resolution,
        )
        return GameEvent(
            event_type, source_id=fact.actor_id, event_id=event_id, window="queue",
            process_only=True, queue_action_terminal_fact=fact,
            payload={"queue_entry": entry, "queue_mutation_id": mutation.stable_id(),
                     "actor_id": fact.actor_id, "target_ids": list(fact.target_ids),
                     "terminal_disposition": "cancelled" if cancelled else "completed"},
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


def unit_alive_state_blocked_reason(
    state: BattleState,
    unit_id: str,
    mask: str,
    *,
    role: str,
) -> str:
    """Formal queue alive-state gate for one owner or target identity.

    The alive_or_revivable mask admits the live branch only: the revive path has
    no admitted consumer yet, so a dying/revivable unit is explicitly blocked
    instead of being treated as limbo.
    """

    unit = state.units.get(unit_id)
    if unit is None:
        return f"queue_{role}_alive_state_unit_missing:{unit_id}"
    status = UnitLifecycleSystem().status_of(unit)
    if status == "active":
        return ""
    if mask == "alive_or_limbo" and status == "limbo":
        return ""
    if mask == "alive_or_revivable":
        return f"queue_{role}_revivable_branch_not_admitted:{unit_id}"
    return f"queue_{role}_alive_state_not_met:{unit_id}:{status}"


def _queue_target_admitted(
    lifecycle: UnitLifecycleSystem,
    state: BattleState,
    target_id: str,
    *,
    allow_unselectable: bool,
    deathrattle_unit_id: str = "",
) -> bool:
    if deathrattle_unit_id and target_id == deathrattle_unit_id:
        unit = state.units.get(target_id)
        return unit is not None and lifecycle.status_of(unit) != "removed"
    if not allow_unselectable:
        return lifecycle.can_target(state, target_id, allow_defeated=False)[0]
    view = lifecycle.view(state, target_id)
    return (
        not view.is_removed
        and view.is_present
        and not view.is_defeated
        and view.status not in {"removed", "defeated"}
    )


def _entry_deathrattle_admission(
    entry: dict[str, JSONValue],
) -> tuple[DeathrattleQueueAdmission | None, str]:
    raw = entry.get("deathrattle_admission")
    if raw is None or raw == {}:
        return None, ""
    try:
        return DeathrattleQueueAdmission.from_json(raw), ""
    except (TypeError, ValueError) as exc:
        return None, str(exc)


def deathrattle_admission_from_entry(
    entry: dict[str, JSONValue],
) -> DeathrattleQueueAdmission | None:
    """Return the typed death authority carried by one queue entry.

    A present but malformed authority is an implementation error, never a
    missing optional field. Callers that already admitted the entry must fail
    closed instead of silently dropping its authority.
    """

    admission, reason = _entry_deathrattle_admission(entry)
    if reason:
        raise ValueError(reason)
    return admission


def _entry_deathrattle_admitted(state: BattleState, entry: dict[str, JSONValue]) -> bool:
    admission, reason = _entry_deathrattle_admission(entry)
    if reason or admission is None:
        return False
    return (
        not admission.entry_contract_blocked_reason(entry)
        and not admission.blocked_reason(state)
    )


def _entry_alive_state_blocked_reason(state: BattleState, entry: dict[str, JSONValue]) -> str:
    actor_id = str(entry.get("actor_id") or "")
    admission, admission_invalid = _entry_deathrattle_admission(entry)
    if admission_invalid:
        return f"queue_owner_deathrattle_admission_invalid:{admission_invalid}"
    targets = QueueActionTerminalFact.accepted_entry_target_ids(entry)
    if targets is None:
        return "queue_entry_target_identity_invalid"
    if admission is not None:
        # One admitted death instance owns this entry. Every identity check is
        # re-verified against the record the death producer actually wrote.
        contract_reason = admission.entry_contract_blocked_reason(entry)
        if contract_reason:
            return contract_reason
        return admission.blocked_reason(state)
    owner_mask = str(entry.get("owner_alive_state") or "alive_only")
    reason = unit_alive_state_blocked_reason(
        state, actor_id, owner_mask, role="owner"
    )
    if reason:
        return reason
    target_mask = str(entry.get("target_alive_state") or "alive_only")
    for target_id in targets:
        reason = unit_alive_state_blocked_reason(
            state, target_id, target_mask, role="target"
        )
        if reason:
            return reason
    return ""


def _waiting_for_other_window(state: BattleState, entry: dict[str, JSONValue]) -> bool:
    if str(entry.get("status") or "") != "waiting_window":
        return False
    waiting = _nonempty_tuple(entry.get("waiting_for_windows"))
    if not waiting:
        return False
    current = str(state.global_flags.get("current_window") or "")
    return current not in waiting


def _source_status_blocked_reason(state: BattleState, entry: dict[str, JSONValue]) -> str:
    policy = entry.get("cancel_policy") if isinstance(entry.get("cancel_policy"), dict) else {}
    if policy.get("requires_source_status_active") is not True:
        return ""
    instance_id = str(policy.get("source_status_instance_id") or entry.get("source_id") or "")
    owner_id = str(policy.get("source_status_owner_id") or entry.get("owner_id") or entry.get("actor_id") or "")
    owner = state.units.get(owner_id)
    if owner is None or not instance_id:
        return "queue_source_status_inactive"
    details = owner.flags.get("status_details", ())
    active = any(
        isinstance(detail, dict)
        and str(detail.get("instance_id") or "") == instance_id
        and not str(detail.get("lifecycle_state") or "active").startswith(("expired", "removed"))
        for detail in details
        if isinstance(details, (list, tuple))
    )
    return "" if active else "queue_source_status_inactive"


def _abort_behavior_blocked_reason(state: BattleState, entry: dict[str, JSONValue]) -> str:
    policy = entry.get("cancel_policy") if isinstance(entry.get("cancel_policy"), dict) else {}
    flags = policy.get("abort_behavior_flags", ())
    if not isinstance(flags, (list, tuple)) or any(not isinstance(flag, str) or not flag for flag in flags):
        return "queue_abort_behavior_flags_invalid"
    actor = state.units.get(str(entry.get("actor_id") or ""))
    if actor is None or not flags:
        return ""
    for detail in actor.flags.get("status_details", ()):
        if (not isinstance(detail, dict)
                or str(detail.get("lifecycle_state") or "active").startswith(("expired", "removed"))):
            continue
        matched = sorted(set(flags).intersection(detail.get("behavior_flags", ())))
        if matched:
            return f"queue_abort_behavior_flag:{matched[0]}"
    return ""


def _revivable_branch_cancellable(state: BattleState, reason: str) -> bool:
    """Whether the failed revivable identity is already confirmed defeated/removed.

    Only the identity named by the actual failure selects the branch: another
    owner/target that is formally admitted for limbo must not keep the entry
    alive, and a unit still in limbo is the unimplemented revive branch and
    blocks with the entry retained. An unparsable identity fails closed.
    """

    unit_id = ""
    for prefix in (
        "queue_owner_revivable_branch_not_admitted:",
        "queue_target_revivable_branch_not_admitted:",
    ):
        if reason.startswith(prefix):
            unit_id = reason[len(prefix):]
            break
    unit = state.units.get(unit_id)
    if unit is None:
        return False
    return UnitLifecycleSystem().status_of(unit) != "limbo"


def _is_gameplay_abort(state: BattleState, entry: dict[str, JSONValue], reason: str) -> bool:
    # Only formal alive-state transitions are ordinary queue obsolescence. A
    # Deathrattle admission defect (shape, missing identity, changed death
    # record, borrowed ability or non-matching resolution body) is an
    # implementation failure: it must block with the entry retained, never
    # masquerade as a successful queue cancellation.
    if reason.startswith(
        ("queue_owner_alive_state", "queue_target_alive_state",
         "queue_owner_revivable", "queue_target_revivable")
    ):
        if reason != _entry_alive_state_blocked_reason(state, entry):
            return False
        if "revivable_branch_not_admitted" in reason:
            # The alive_or_revivable mask has no admitted revive consumer yet.
            # While the failing identity is still in limbo the branch is
            # unresolved: it must block with the entry retained and produce no
            # mutation instead of masquerading as a normal cancellation. A
            # confirmed defeat or removal stays ordinary queue obsolescence;
            # limbo of a different, formally admitted identity never changes
            # this decision.
            return _revivable_branch_cancellable(state, reason)
        return True
    actor_id = str(entry.get("actor_id") or "")
    targets = QueueActionTerminalFact.accepted_entry_target_ids(entry)
    if (actor_id not in state.units or targets is None
            or any(target not in state.units for target in targets)):
        return False
    if reason.startswith("queue_abort_behavior_flag:"):
        return reason == _abort_behavior_blocked_reason(state, entry)
    if reason == "queue_source_status_inactive":
        return reason == _source_status_blocked_reason(state, entry)
    if reason.startswith("queue_window_expired:"):
        return reason == _expiration_blocked_reason(state, entry)
    lifecycle = UnitLifecycleSystem()
    _, actor_reason = lifecycle.can_act(state, actor_id)
    if actor_reason in {"unit_defeated", "unit_removed", "unit_departed"}:
        if reason == f"queue_action_actor_{actor_reason}":
            return True
    for target in targets:
        _, target_reason = lifecycle.can_target(state, target)
        if target_reason in {"unit_defeated", "unit_removed", "unit_departed"}:
            if reason == f"queue_action_target_lifecycle_blocked:{target_reason}:{target}":
                return True
    return False


def _expiration_blocked_reason(state: BattleState, entry: dict[str, JSONValue]) -> str:
    policy = entry.get("expiration_policy") if isinstance(entry.get("expiration_policy"), dict) else {}
    expires_at = policy.get("expires_at_event_index")
    if isinstance(expires_at, (int, float)) and not isinstance(expires_at, bool):
        if state.event_index > int(expires_at):
            return "queue_window_expired:event_index"
    valid_windows = _nonempty_tuple(policy.get("valid_windows"))
    if policy.get("expire_on_window_mismatch") is True and valid_windows:
        current = str(state.global_flags.get("current_window") or "")
        if current not in valid_windows:
            return f"queue_window_expired:{current or 'missing'}"
    return ""


def _terminal_source_trace(plan: QueueDrainPlan) -> dict[str, JSONValue]:
    entry_source = plan.queue_entry.get("source_trace") if isinstance(plan.queue_entry, dict) else None
    trace = plan.source_trace if isinstance(plan.source_trace, dict) else {}
    return {
        **trace,
        **({"queue_entry_source": entry_source} if isinstance(entry_source, dict) and entry_source else {}),
        "queue_intent_id": plan.queue_intent_id,
        "queue_resolution_id": plan.queue_resolution_id,
    }


def _admitted_wait_windows(
    cancel_policy: dict[str, JSONValue],
    source_trace: dict[str, JSONValue],
) -> tuple[str, ...]:
    if cancel_policy.get("wait_policy_admitted") is not True:
        return ()
    return _nonempty_tuple(cancel_policy.get("wait_for_windows"))


def _admitted_retarget_ids(
    state: BattleState,
    cancel_policy: dict[str, JSONValue],
    source_trace: dict[str, JSONValue],
) -> tuple[str, ...]:
    if cancel_policy.get("retarget_policy_admitted") is not True:
        return ()
    target_ids = _nonempty_tuple(cancel_policy.get("retarget_target_ids"))
    lifecycle = UnitLifecycleSystem()
    if not target_ids or not all(lifecycle.can_target(state, target_id, allow_defeated=False)[0] for target_id in target_ids):
        return ()
    return target_ids


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
