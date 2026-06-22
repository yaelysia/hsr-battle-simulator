from __future__ import annotations

from dataclasses import dataclass

from ..core.model import ActionCommand, BattleState, GameEvent, JSONValue, Mutation, TargetResolution
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..rules.ir import ActionDefinitionIR
from ..rules.rulebook import RuleBook
from .damage import DamageSystem
from .effect import EffectRegistry
from .status_callbacks import StatusCallbackSystem
from .timeline import TimelineSystem
from .trigger import TriggerSystem


@dataclass(frozen=True)
class EventDispatchResult:
    after_state: BattleState
    mutations: tuple[Mutation, ...] = ()
    events: tuple[GameEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    trigger_windows: tuple[dict[str, JSONValue], ...] = ()
    listener_records: tuple[dict[str, JSONValue], ...] = ()
    errors: tuple[str, ...] = ()


class EventDispatchSystem:
    """Unified runtime dispatch boundary for admitted event listeners.

    This is intentionally an orchestration layer over the existing trigger and
    status-callback executors. It keeps the execution source-auditable while
    preventing new runtime systems from calling listener helpers directly.
    """

    def __init__(
        self,
        rules: RuleBook,
        effect_registry: EffectRegistry,
        *,
        reducer: MutationReducer | None = None,
        damage: DamageSystem | None = None,
        timeline: TimelineSystem | None = None,
        trigger_system: TriggerSystem | None = None,
        status_callbacks: StatusCallbackSystem | None = None,
    ) -> None:
        self.rules = rules
        self.reducer = reducer or MutationReducer()
        self.damage = damage or DamageSystem()
        self.timeline = timeline or TimelineSystem()
        self.trigger_system = trigger_system or TriggerSystem(rules, effect_registry, reducer=self.reducer)
        self.status_callbacks = status_callbacks or StatusCallbackSystem(
            rules,
            damage=self.damage,
            reducer=self.reducer,
            timeline=self.timeline,
        )

    def dispatch_action_window(
        self,
        state: BattleState,
        *,
        event: GameEvent,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        target_resolution: TargetResolution,
        enabled: bool = True,
        skipped_reason: str = "",
    ) -> EventDispatchResult:
        canonical_window = event.window
        tbgd_event = _event_payload_str(event, "tbgd_event") or event.event_type
        dispatch_record = _dispatch_record(
            event,
            listener_kind="action_status_window",
            scope="status_local",
            status="dispatching" if enabled else "skipped",
            reason=skipped_reason,
            metadata={
                "tbgd_event": tbgd_event,
                "selected_target_ids": list(target_resolution.selected),
                "requested_target_ids": list(target_resolution.requested),
            },
        )
        result = self.trigger_system.execute_status_window(
            state,
            canonical_window=canonical_window,
            tbgd_event=tbgd_event,
            command=command,
            action_definition=action_definition,
            target_resolution=target_resolution,
            enabled=enabled,
            skipped_reason=skipped_reason,
        )
        listener_records = tuple(_listener_records_from_trigger_windows(result.trigger_windows))
        return EventDispatchResult(
            after_state=result.after_state,
            mutations=result.mutations,
            events=(event, *result.events),
            records=(dispatch_record, *listener_records, *result.records),
            trigger_windows=result.trigger_windows,
            listener_records=listener_records,
            errors=(),
        )

    def dispatch_status_callback(
        self,
        state: BattleState,
        *,
        event: GameEvent,
        unit_id: str,
        modifier_name: str,
    ) -> EventDispatchResult:
        callback_event = _event_payload_str(event, "callback_event") or event.window or event.event_type
        dispatch_record = _dispatch_record(
            event,
            listener_kind="status_callback",
            scope="status_local",
            status="dispatching",
            metadata={
                "unit_id": unit_id,
                "modifier_name": modifier_name,
                "callback_event": callback_event,
            },
        )
        result = self.status_callbacks.execute(
            state,
            unit_id=unit_id,
            modifier_name=modifier_name,
            event=callback_event,
        )
        listener_records = tuple(
            _listener_record(
                event,
                listener_kind="status_callback",
                listener_id=_record_payload_str(record, "callback_id"),
                source="status_callback_system",
                status="ok" if result.ok else "blocked",
                reason=",".join(result.errors),
                metadata={
                    "unit_id": unit_id,
                    "modifier_name": modifier_name,
                    "callback_event": callback_event,
                    "mutation_count": len(result.mutations),
                    "record_type": str(record.get("record_type") or ""),
                },
            )
            for record in result.records
            if isinstance(record, dict)
        )
        return EventDispatchResult(
            after_state=result.after_state,
            mutations=result.mutations,
            events=(event, *result.events),
            records=(dispatch_record, *listener_records, *result.records),
            trigger_windows=(),
            listener_records=listener_records,
            errors=result.errors,
        )

    def dispatch_blocked(
        self,
        state: BattleState,
        *,
        event: GameEvent,
        listener_kind: str,
        scope: str,
        reason: str,
        metadata: dict[str, JSONValue] | None = None,
    ) -> EventDispatchResult:
        dispatch_record = _dispatch_record(
            event,
            listener_kind=listener_kind,
            scope=scope,
            status="blocked",
            reason=reason,
            metadata=metadata or {},
        )
        listener_record = _listener_record(
            event,
            listener_kind=listener_kind,
            listener_id="",
            source="event_dispatch_system",
            status="blocked",
            reason=reason,
            metadata=metadata or {},
        )
        return EventDispatchResult(
            after_state=state,
            events=(event,),
            records=(dispatch_record, listener_record),
            listener_records=(listener_record,),
            errors=(reason,),
        )


def _dispatch_record(
    event: GameEvent,
    *,
    listener_kind: str,
    scope: str,
    status: str,
    reason: str = "",
    metadata: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="event_dispatch",
        source="event_dispatch_system",
        process_only=True,
        payload={
            "event": event.to_json(),
            "listener_kind": listener_kind,
            "scope": scope,
            "status": status,
            "reason": reason,
            "metadata": metadata or {},
        },
        trace={"event_id": event.to_json()["event_id"]},
    ).to_json()


def _listener_record(
    event: GameEvent,
    *,
    listener_kind: str,
    listener_id: str,
    source: str,
    status: str,
    reason: str = "",
    metadata: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="listener_match",
        source="event_dispatch_system",
        process_only=True,
        payload={
            "event": event.to_json(),
            "listener_kind": listener_kind,
            "listener_id": listener_id,
            "listener_source": source,
            "status": status,
            "reason": reason,
            "metadata": metadata or {},
        },
        trace={"event_id": event.to_json()["event_id"], "listener_id": listener_id},
    ).to_json()


def _listener_records_from_trigger_windows(
    windows: tuple[dict[str, JSONValue], ...],
) -> tuple[dict[str, JSONValue], ...]:
    records: list[dict[str, JSONValue]] = []
    for window in windows:
        if not isinstance(window, dict):
            continue
        metadata = window.get("metadata") if isinstance(window.get("metadata"), dict) else {}
        event = GameEvent(
            event_type=str(window.get("tbgd_event") or "trigger.window"),
            source_id=str(metadata.get("actor_id") or "") if isinstance(metadata, dict) else "",
            target_id=str(metadata.get("primary_target_id") or "") if isinstance(metadata, dict) else "",
            window=str(window.get("canonical_window") or "unspecified"),
            process_only=True,
            payload={
                "canonical_window": str(window.get("canonical_window") or ""),
                "tbgd_event": str(window.get("tbgd_event") or ""),
                "status_instance_id": str(window.get("status_instance_id") or ""),
                "modifier_name": str(window.get("modifier_name") or ""),
                "trigger_id": str(window.get("trigger_id") or ""),
            },
        )
        status = "matched"
        reason = ""
        if window.get("blocked_reason"):
            status = "blocked"
            reason = str(window.get("blocked_reason") or "")
        elif window.get("skipped_reason"):
            status = "skipped"
            reason = str(window.get("skipped_reason") or "")
        records.append(
            _listener_record(
                event,
                listener_kind="trigger",
                listener_id=str(window.get("trigger_id") or ""),
                source="trigger_system",
                status=status,
                reason=reason,
                metadata={
                    "canonical_window": str(window.get("canonical_window") or ""),
                    "tbgd_event": str(window.get("tbgd_event") or ""),
                    "status_instance_id": str(window.get("status_instance_id") or ""),
                    "modifier_name": str(window.get("modifier_name") or ""),
                    "mutation_count": int(window.get("mutation_count") or 0),
                },
            )
        )
    return tuple(records)


def _event_payload_str(event: GameEvent, key: str) -> str:
    value = event.payload.get(key)
    return str(value) if isinstance(value, str) else ""


def _record_payload_str(record: dict[str, JSONValue], key: str) -> str:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return ""
    value = payload.get(key)
    return str(value) if isinstance(value, str) else ""
