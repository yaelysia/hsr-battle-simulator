from __future__ import annotations

from dataclasses import dataclass

from ..core.model import ActionCommand, BattleState, GameEvent, JSONValue, Mutation, TargetResolution
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..rules.ir import ActionDefinitionIR, StatusCallbackIR
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


@dataclass(frozen=True)
class ListenerMatch:
    listener_kind: str
    scope_kind: str
    callback_event: str
    unit_id: str
    modifier_name: str
    callback: StatusCallbackIR | None
    status_instance_id: str = ""
    status: str = "matched"
    reason: str = ""
    source: str = "rulebook"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "listener_kind": self.listener_kind,
            "scope_kind": self.scope_kind,
            "callback_event": self.callback_event,
            "unit_id": self.unit_id,
            "modifier_name": self.modifier_name,
            "callback_id": self.callback.callback_id if self.callback else "",
            "callback": self.callback.to_json() if self.callback else None,
            "status_instance_id": self.status_instance_id,
            "status": self.status,
            "reason": self.reason,
            "source": self.source,
        }


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
        return self.dispatch_event(
            state,
            event=event,
            command=command,
            action_definition=action_definition,
            target_resolution=target_resolution,
            enabled=enabled,
            skipped_reason=skipped_reason,
        )

    def dispatch_event(
        self,
        state: BattleState,
        *,
        event: GameEvent,
        command: ActionCommand | None = None,
        action_definition: ActionDefinitionIR | None = None,
        target_resolution: TargetResolution | None = None,
        enabled: bool = True,
        skipped_reason: str = "",
        unit_id: str | None = None,
        modifier_name: str | None = None,
    ) -> EventDispatchResult:
        if command is not None and action_definition is not None and target_resolution is not None:
            return self._dispatch_action_window_event(
                state,
                event=event,
                command=command,
                action_definition=action_definition,
                target_resolution=target_resolution,
                enabled=enabled,
                skipped_reason=skipped_reason,
            )
        return self._dispatch_listener_event(
            state,
            event=event,
            unit_id=unit_id,
            modifier_name=modifier_name,
        )

    def _dispatch_action_window_event(
        self,
        state: BattleState,
        *,
        event: GameEvent,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        target_resolution: TargetResolution,
        enabled: bool,
        skipped_reason: str,
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
        return self.dispatch_event(
            state,
            event=event,
            unit_id=unit_id,
            modifier_name=modifier_name,
        )

    def _dispatch_listener_event(
        self,
        state: BattleState,
        *,
        event: GameEvent,
        unit_id: str | None,
        modifier_name: str | None,
    ) -> EventDispatchResult:
        callback_events = _callback_events_for_event(event)
        dispatch_scope = _event_scope_kind(event)
        dispatch_record = _dispatch_record(
            event,
            listener_kind="listener_dispatch",
            scope=dispatch_scope,
            status="dispatching",
            metadata={
                "unit_id": unit_id or "",
                "modifier_name": modifier_name or "",
                "callback_events": list(callback_events),
                "event_scope_kind": dispatch_scope,
            },
        )
        if not callback_events:
            reason = "listener_event_mapping_missing"
            listener_record = _listener_record(
                event,
                listener_kind="listener_dispatch",
                listener_id="",
                source="event_dispatch_system",
                status="blocked",
                reason=reason,
                metadata={"event_scope_kind": dispatch_scope},
            )
            return EventDispatchResult(
                after_state=state,
                events=(event,),
                records=(dispatch_record, listener_record),
                listener_records=(listener_record,),
                errors=(reason,),
            )

        matches = self._resolve_listener_matches(
            state,
            event=event,
            callback_events=callback_events,
            unit_id=unit_id,
            modifier_name=modifier_name,
        )
        if not matches:
            reason = "listener_match_missing"
            listener_record = _listener_record(
                event,
                listener_kind="listener_dispatch",
                listener_id="",
                source="event_dispatch_system",
                status="skipped",
                reason=reason,
                metadata={
                    "callback_events": list(callback_events),
                    "event_scope_kind": dispatch_scope,
                    "unit_id": unit_id or "",
                    "modifier_name": modifier_name or "",
                },
            )
            return EventDispatchResult(
                after_state=state,
                events=(event,),
                records=(dispatch_record, listener_record),
                listener_records=(listener_record,),
            )

        current_state = state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = [dispatch_record]
        events: list[GameEvent] = [event]
        listener_records: list[dict[str, JSONValue]] = []
        errors: list[str] = []
        for match in matches:
            listener_record = _listener_record(
                event,
                listener_kind=match.listener_kind,
                listener_id=match.callback.callback_id if match.callback else "",
                source=match.source,
                status=match.status,
                reason=match.reason,
                metadata=match.to_json(),
            )
            listener_records.append(listener_record)
            records.append(listener_record)
            if match.status != "matched":
                if match.reason:
                    errors.append(match.reason)
                continue
            result = self.status_callbacks.execute(
                current_state,
                unit_id=match.unit_id,
                modifier_name=match.modifier_name,
                event=match.callback_event,
            )
            current_state = result.after_state
            mutations.extend(result.mutations)
            records.extend(result.records)
            events.extend(result.events)
            errors.extend(result.errors)
            execution_record = _listener_record(
                event,
                listener_kind=match.listener_kind,
                listener_id=match.callback.callback_id if match.callback else "",
                source="status_callback_system",
                status="executed" if result.ok else "blocked",
                reason=",".join(result.errors),
                metadata={
                    **match.to_json(),
                    "mutation_count": len(result.mutations),
                    "record_count": len(result.records),
                },
            )
            listener_records.append(execution_record)
            records.append(execution_record)
        return EventDispatchResult(
            after_state=current_state,
            mutations=tuple(mutations),
            events=tuple(events),
            records=tuple(records),
            trigger_windows=(),
            listener_records=tuple(listener_records),
            errors=tuple(errors),
        )

    def _resolve_listener_matches(
        self,
        state: BattleState,
        *,
        event: GameEvent,
        callback_events: tuple[str, ...],
        unit_id: str | None,
        modifier_name: str | None,
    ) -> tuple[ListenerMatch, ...]:
        if unit_id and modifier_name:
            return self._explicit_status_matches(state, event, callback_events, unit_id, modifier_name)
        matches: list[ListenerMatch] = []
        for callback_event in callback_events:
            for callback in self.rules.status_callbacks_for_event(callback_event):
                for detail in _status_details_for_modifier(state, callback.modifier_name):
                    match = _match_callback_to_event(event, callback, detail, explicit=False)
                    if match is not None:
                        matches.append(match)
        return tuple(matches)

    def _explicit_status_matches(
        self,
        state: BattleState,
        event: GameEvent,
        callback_events: tuple[str, ...],
        unit_id: str,
        modifier_name: str,
    ) -> tuple[ListenerMatch, ...]:
        detail = _status_detail_for_unit_modifier(state, unit_id, modifier_name)
        if detail is None:
            return (
                ListenerMatch(
                    listener_kind="status_callback",
                    scope_kind="status_local",
                    callback_event=callback_events[0],
                    unit_id=unit_id,
                    modifier_name=modifier_name,
                    callback=None,
                    status="blocked",
                    reason="status_detail_missing",
                    source="event_dispatch_system",
                ),
            )
        matches: list[ListenerMatch] = []
        for callback_event in callback_events:
            callbacks = self.rules.status_callbacks_for_modifier_event(modifier_name, callback_event)
            if not callbacks:
                matches.append(
                    ListenerMatch(
                        listener_kind="status_callback",
                        scope_kind="status_local",
                        callback_event=callback_event,
                        unit_id=unit_id,
                        modifier_name=modifier_name,
                        callback=None,
                        status="matched",
                        source="event_dispatch_system",
                        status_instance_id=str(detail.get("instance_id") or ""),
                    )
                )
                continue
            for callback in callbacks:
                match = _match_callback_to_event(event, callback, detail, explicit=True)
                if match is not None:
                    matches.append(match)
        return tuple(matches)

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


def _callback_events_for_event(event: GameEvent) -> tuple[str, ...]:
    raw_events = event.payload.get("callback_events")
    if isinstance(raw_events, (list, tuple)):
        events = tuple(str(item) for item in raw_events if isinstance(item, str) and item)
        if events:
            return tuple(dict.fromkeys(events))
    for key in ("callback_event", "tbgd_event"):
        value = event.payload.get(key)
        if isinstance(value, str) and value:
            return (value,)
    if event.window.startswith("On"):
        return (event.window,)
    return ()


def _event_scope_kind(event: GameEvent) -> str:
    value = event.payload.get("listener_scope")
    if isinstance(value, str) and value:
        return value
    if event.event_type in {"damage.hit", "toughness.hit"}:
        return "per_hit_target_local"
    if event.event_type.startswith("break."):
        return "being_hit_target_local"
    if event.window.startswith("OnListen"):
        return "global_listener"
    if event.window.startswith("OnBeing"):
        return "being_hit_target_local"
    if "Hit" in event.window:
        return "per_hit_target_local"
    return "status_local"


def _status_details_for_modifier(state: BattleState, modifier_name: str) -> tuple[dict[str, JSONValue], ...]:
    details: list[dict[str, JSONValue]] = []
    for unit in state.units.values():
        for detail in unit.flags.get("status_details", ()):
            if isinstance(detail, dict) and detail.get("modifier_name") == modifier_name:
                details.append(detail)
    return tuple(details)


def _status_detail_for_unit_modifier(
    state: BattleState,
    unit_id: str,
    modifier_name: str,
) -> dict[str, JSONValue] | None:
    unit = state.units.get(unit_id)
    if unit is None:
        return None
    for detail in unit.flags.get("status_details", ()):
        if isinstance(detail, dict) and detail.get("modifier_name") == modifier_name:
            return detail
    return None


def _match_callback_to_event(
    event: GameEvent,
    callback: StatusCallbackIR,
    detail: dict[str, JSONValue],
    *,
    explicit: bool,
) -> ListenerMatch | None:
    unit_id = str(detail.get("owner_id") or event.target_id or "")
    modifier_name = str(detail.get("modifier_name") or callback.modifier_name)
    scope_kind = callback.scope_kind or _event_scope_kind(event)
    status_instance_id = str(detail.get("instance_id") or "")
    scope_ok, scope_reason = _scope_matches(event, scope_kind, detail, explicit=explicit)
    status = "matched"
    reason = ""
    if not scope_ok:
        status = "skipped"
        reason = scope_reason
    elif callback.coverage_status != "executable":
        status = "blocked"
        reason = callback.blocked_reason or f"listener_not_executable:{callback.coverage_status}"
    elif callback.admission_status != "executable":
        status = "blocked"
        reason = callback.blocking_dependency or f"listener_not_admitted:{callback.admission_status}"
    elif scope_kind == "global_listener" and not explicit:
        status = "blocked"
        reason = "global_listener_auto_execution_not_admitted"
    if status == "skipped" and not explicit:
        return None
    return ListenerMatch(
        listener_kind=_listener_kind_for_scope(scope_kind),
        scope_kind=scope_kind,
        callback_event=callback.event,
        unit_id=unit_id,
        modifier_name=modifier_name,
        callback=callback,
        status_instance_id=status_instance_id,
        status=status,
        reason=reason,
        source="rulebook.status_callback",
    )


def _scope_matches(
    event: GameEvent,
    scope_kind: str,
    detail: dict[str, JSONValue],
    *,
    explicit: bool,
) -> tuple[bool, str]:
    if explicit:
        return True, ""
    owner_id = str(detail.get("owner_id") or "")
    actor_id = _event_actor_id(event)
    primary_target_id = _event_primary_target_id(event)
    current_hit_target_id = _event_current_hit_target_id(event)
    if scope_kind == "global_listener":
        return True, ""
    if scope_kind == "actor_local":
        return (owner_id == actor_id, "scope_actor_mismatch")
    if scope_kind == "primary_target_local":
        return (owner_id == primary_target_id, "scope_primary_target_mismatch")
    if scope_kind == "per_hit_target_local":
        return (owner_id == current_hit_target_id, "scope_current_hit_target_mismatch")
    if scope_kind == "being_hit_target_local":
        target_id = current_hit_target_id or str(event.target_id or "")
        return (owner_id == target_id, "scope_being_hit_target_mismatch")
    if scope_kind == "owner_local":
        return (owner_id in {actor_id, primary_target_id, current_hit_target_id}, "scope_owner_not_in_event_context")
    return False, f"scope_not_admitted:{scope_kind}"


def _event_actor_id(event: GameEvent) -> str:
    for key in ("actor_id", "attacker_id"):
        value = event.payload.get(key)
        if isinstance(value, str) and value:
            return value
    return str(event.source_id or "")


def _event_primary_target_id(event: GameEvent) -> str:
    value = event.payload.get("primary_action_target_id")
    if isinstance(value, str) and value:
        return value
    return str(event.target_id or "")


def _event_current_hit_target_id(event: GameEvent) -> str:
    value = event.payload.get("current_hit_target_id")
    if isinstance(value, str) and value:
        return value
    return str(event.target_id or "")


def _listener_kind_for_scope(scope_kind: str) -> str:
    if scope_kind == "global_listener":
        return "global_listener"
    if scope_kind == "being_hit_target_local":
        return "being_hit_listener"
    if scope_kind == "per_hit_target_local":
        return "per_hit_listener"
    return "status_callback"


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
