from __future__ import annotations

from dataclasses import dataclass, replace

from ..core.model import ActionCommand, BattleState, GameEvent, JSONValue, Mutation, RNGEvent, TargetResolution
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..rules.ir import ActionDefinitionIR, StatusCallbackIR, StatusEventFamilyIR
from ..rules.rulebook import RuleBook
from .damage import DamageSystem, DamageWindowLedger
from .effect import EffectRegistry
from .mutation_events import MUTATION_BACKED_EVENT_TYPES, PRE_MUTATION_BLOCK_REASON
from .status_callbacks import StatusCallbackSystem
from .timeline import TimelineSystem
from .trigger import TriggerSystem


@dataclass(frozen=True)
class EventDispatchResult:
    after_state: BattleState
    mutations: tuple[Mutation, ...] = ()
    events: tuple[GameEvent, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
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
    order_key: dict[str, JSONValue] | None = None
    event_alias: dict[str, JSONValue] | None = None
    blocked_category: str = ""

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
            "order_key": self.order_key or {},
            "event_alias": self.event_alias or {},
            "blocked_category": self.blocked_category,
        }


@dataclass(frozen=True)
class EventAlias:
    callback_event: str
    scope_kind: str
    source_basis: str
    admission_status: str = "executable"
    blocked_dependency: str = ""
    status_event_family_id: str = ""
    event_family: str = ""
    runtime_event_source: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "callback_event": self.callback_event,
            "scope_kind": self.scope_kind,
            "source_basis": self.source_basis,
            "admission_status": self.admission_status,
            "blocked_dependency": self.blocked_dependency,
            "blocked_category": _blocked_category(self.blocked_dependency),
            "status_event_family_id": self.status_event_family_id,
            "event_family": self.event_family,
            "runtime_event_source": self.runtime_event_source,
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
        damage_window_ledger: DamageWindowLedger | None = None,
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
            damage_window_ledger=damage_window_ledger,
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
        event_aliases = _event_aliases(event, self.rules)
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
                "event_aliases": [alias.to_json() for alias in event_aliases],
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
            rng_events=result.rng_events,
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
        damage_window_ledger: DamageWindowLedger | None = None,
    ) -> EventDispatchResult:
        return self.dispatch_event(
            state,
            event=event,
            unit_id=unit_id,
            modifier_name=modifier_name,
            damage_window_ledger=damage_window_ledger,
        )

    def _dispatch_listener_event(
        self,
        state: BattleState,
        *,
        event: GameEvent,
        unit_id: str | None,
        modifier_name: str | None,
        damage_window_ledger: DamageWindowLedger | None,
    ) -> EventDispatchResult:
        aliases = _event_aliases(event, self.rules)
        dispatch_scope = aliases[0].scope_kind if aliases else "unknown"
        dispatch_record = _dispatch_record(
            event,
            listener_kind="listener_dispatch",
            scope=dispatch_scope,
            status="dispatching",
            metadata={
                "unit_id": unit_id or "",
                "modifier_name": modifier_name or "",
                "callback_events": [alias.callback_event for alias in aliases if alias.callback_event],
                "event_scope_kind": dispatch_scope,
                "event_aliases": [alias.to_json() for alias in aliases],
            },
        )
        matches = self._resolve_listener_matches(
            state,
            event=event,
            aliases=aliases,
            unit_id=unit_id,
            modifier_name=modifier_name,
        )
        if not matches:
            reason = "listener_match_missing"
            alias = aliases[0] if aliases else EventAlias(
                callback_event="",
                scope_kind=dispatch_scope,
                source_basis=f"runtime_event:{event.event_type}",
                admission_status="blocked",
                blocked_dependency="event_alias_missing",
            )
            target_unit = str(unit_id or event.target_id or _event_current_hit_target_id(event) or "")
            listener_record = _listener_record(
                event,
                listener_kind="listener_dispatch",
                listener_id="",
                source="event_dispatch_system",
                status="skipped",
                reason=reason,
                metadata={
                    "callback_events": [alias.callback_event for alias in aliases if alias.callback_event],
                    "event_scope_kind": dispatch_scope,
                    "unit_id": unit_id or "",
                    "modifier_name": modifier_name or "",
                    "event_aliases": [alias.to_json() for alias in aliases],
                    "order_key": _listener_order_key(state, alias.scope_kind, target_unit, -1, None),
                    "event_alias": alias.to_json(),
                    "blocked_category": _blocked_category(reason),
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
        rng_events: list[RNGEvent] = []
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
                trigger_event=event,
                damage_window_ledger=damage_window_ledger,
            )
            current_state = result.after_state
            mutations.extend(result.mutations)
            rng_events.extend(result.rng_events)
            records.extend(result.records)
            events.extend(result.events)
            errors.extend(result.errors)
            child_depth = _event_mutation_depth(event)
            if child_depth < 1:
                for emitted_event in result.events:
                    if emitted_event.event_type not in MUTATION_BACKED_EVENT_TYPES:
                        continue
                    child_event = replace(
                        emitted_event,
                        payload={**emitted_event.payload, "mutation_event_depth": child_depth + 1},
                    )
                    child_result = self.dispatch_event(
                        current_state,
                        event=child_event,
                        damage_window_ledger=damage_window_ledger,
                    )
                    current_state = child_result.after_state
                    mutations.extend(child_result.mutations)
                    rng_events.extend(child_result.rng_events)
                    records.extend(child_result.records)
                    events.extend(child_result.events)
                    errors.extend(child_result.errors)
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
            rng_events=tuple(rng_events),
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
        aliases: tuple[EventAlias, ...],
        unit_id: str | None,
        modifier_name: str | None,
    ) -> tuple[ListenerMatch, ...]:
        pre_mutation_reason = _pre_mutation_listener_block_reason(event)
        if pre_mutation_reason:
            return tuple(
                _pre_mutation_blocked_match(
                    event,
                    alias,
                    state,
                    reason=pre_mutation_reason,
                    unit_id=unit_id,
                    modifier_name=modifier_name,
                )
                for alias in aliases
            )
        if unit_id and modifier_name:
            return self._explicit_status_matches(state, event, aliases, unit_id, modifier_name)
        matches: list[ListenerMatch] = []
        for alias in aliases:
            if not alias.callback_event or alias.admission_status != "executable":
                matches.append(_alias_blocked_match(event, alias, state))
                continue
            for callback in self.rules.status_callbacks_for_event_scope(alias.callback_event, alias.scope_kind):
                for detail in _status_details_for_modifier(state, callback.modifier_name):
                    match = _match_callback_to_event(event, callback, detail, explicit=False, alias=alias, state=state)
                    if match is not None:
                        matches.append(match)
        return tuple(sorted(matches, key=_match_sort_key))

    def _explicit_status_matches(
        self,
        state: BattleState,
        event: GameEvent,
        aliases: tuple[EventAlias, ...],
        unit_id: str,
        modifier_name: str,
    ) -> tuple[ListenerMatch, ...]:
        detail = _status_detail_for_unit_modifier(state, unit_id, modifier_name)
        if detail is None:
            return (
                ListenerMatch(
                    listener_kind="status_callback",
                    scope_kind="status_local",
                    callback_event=aliases[0].callback_event if aliases else "",
                    unit_id=unit_id,
                    modifier_name=modifier_name,
                    callback=None,
                    status="blocked",
                    reason="status_detail_missing",
                    source="event_dispatch_system",
                    order_key=_listener_order_key(state, "status_local", unit_id, -1, None),
                    event_alias=aliases[0].to_json() if aliases else {},
                    blocked_category=_blocked_category("status_detail_missing"),
                ),
            )
        matches: list[ListenerMatch] = []
        for alias in aliases:
            if not alias.callback_event or alias.admission_status != "executable":
                matches.append(_alias_blocked_match(event, alias, state, unit_id=unit_id, modifier_name=modifier_name))
                continue
            callbacks = self.rules.status_callbacks_for_modifier_event_scope(
                modifier_name,
                alias.callback_event,
                alias.scope_kind,
            ) or self.rules.status_callbacks_for_modifier_event(modifier_name, alias.callback_event)
            if not callbacks:
                matches.append(
                    ListenerMatch(
                        listener_kind="status_callback",
                        scope_kind=alias.scope_kind,
                        callback_event=alias.callback_event,
                        unit_id=unit_id,
                        modifier_name=modifier_name,
                        callback=None,
                        status="skipped",
                        reason="status_callback_missing",
                        source="event_dispatch_system",
                        status_instance_id=str(detail.get("instance_id") or ""),
                        order_key=_listener_order_key(state, alias.scope_kind, unit_id, _status_order(state, unit_id, detail), None),
                        event_alias=alias.to_json(),
                        blocked_category=_blocked_category("status_callback_missing"),
                    )
                )
                continue
            for callback in callbacks:
                match = _match_callback_to_event(event, callback, detail, explicit=True, alias=alias, state=state)
                if match is not None:
                    matches.append(match)
        return tuple(sorted(matches, key=_match_sort_key))

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
        aliases = _event_aliases(event, self.rules)
        alias = aliases[0] if aliases else EventAlias(
            callback_event="",
            scope_kind=scope,
            source_basis=f"runtime_event:{event.event_type}",
            admission_status="blocked",
            blocked_dependency="event_alias_missing",
        )
        listener_metadata: dict[str, JSONValue] = {
            **(metadata or {}),
            "order_key": {
                "scope_priority": SCOPE_PRIORITY.get(scope, 999),
                "scope_kind": scope,
                "unit_order": 999999,
                "unit_id": str(event.target_id or ""),
                "status_order": -1,
                "callback_source_order": "",
                "callback_id": "",
                "task_order": [],
            },
            "event_alias": alias.to_json(),
            "blocked_category": _blocked_category(reason),
        }
        listener_record = _listener_record(
            event,
            listener_kind=listener_kind,
            listener_id="",
            source="event_dispatch_system",
            status="blocked",
            reason=reason,
            metadata=listener_metadata,
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


SCOPE_PRIORITY = {
    "actor_local": 10,
    "status_local": 20,
    "primary_target_local": 30,
    "per_hit_target_local": 40,
    "being_hit_target_local": 50,
    "owner_local": 60,
    "global_listener": 90,
}


CANONICAL_EVENT_ALIASES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "turn.begin": (
        ("OnListenAllowAction", "owner_local", ""),
        ("OnEnterBattle", "owner_local", "event_alias_missing:on_enter_battle_requires_battle_start_event"),
    ),
    "turn.end": (
        ("OnListenTurnEnd", "global_listener", ""),
    ),
    "action.window.before_skill_use": (
        ("OnBeforeSkillUse", "actor_local", ""),
    ),
    "action.window.before_attack": (
        ("OnBeforeAttack", "actor_local", ""),
    ),
    "action.window.after_attack": (
        ("OnAfterAttack", "actor_local", ""),
    ),
    "action.window.after_skill_use": (
        ("OnAfterSkillUse", "actor_local", ""),
    ),
    "action.after_attack": (
        ("OnListenAfterAttack", "global_listener", ""),
        ("OnAfterAttack", "actor_local", ""),
    ),
    "action.end": (
        ("OnActionEnd", "actor_local", ""),
    ),
    "queue.action.before": (
        ("OnBeforeInsertActionPrepare", "actor_local", ""),
        ("OnInsertActionStart", "actor_local", ""),
    ),
    "queue.action.after": (
        ("OnInsertActionFinish", "actor_local", ""),
        ("OnListenInsertAbilityFinish", "actor_local", ""),
    ),
    "unit.defeated": (
        ("OnTriggerDeath", "owner_local", ""),
        ("OnListenCharacterDie", "owner_local", ""),
        ("OnTriggerDeathrattle", "owner_local", ""),
    ),
    "unit.before_dying": (
        ("OnBeforeDying", "owner_local", ""),
    ),
    "damage.hit": (
        ("OnBeforeHit", "per_hit_target_local", "event_alias_missing:on_before_hit_requires_pre_damage_event"),
        ("OnAfterHitAll", "actor_local", ""),
        ("OnAfterHit", "per_hit_target_local", ""),
        ("OnAfterBeingAttacked", "being_hit_target_local", ""),
        ("OnHit", "per_hit_target_local", "downstream_intent_missing:per_hit_listener_execution_not_admitted"),
        ("OnBeingHit", "being_hit_target_local", "downstream_intent_missing:being_hit_listener_execution_not_admitted"),
    ),
    "toughness.hit": (
        ("OnHit", "per_hit_target_local", "downstream_intent_missing:per_hit_listener_execution_not_admitted"),
    ),
    "break.triggered": (
        ("OnTriggerBreak", "actor_local", "downstream_intent_missing:break_listener_execution_not_admitted"),
        ("OnBeingBreak", "being_hit_target_local", "downstream_intent_missing:being_break_listener_execution_not_admitted"),
    ),
    "status.callback": (
        ("OnPhase1", "status_local", "event_alias_missing:status_callback_requires_explicit_callback_event"),
        ("OnCreate", "status_local", "event_alias_missing:on_create_requires_status_create_event"),
        ("OnDestroy", "status_local", "event_alias_missing:on_destroy_requires_status_destroy_event"),
    ),
    "custom.event": (
        ("OnCustomEvent", "owner_local", "event_alias_missing:custom_event_source_not_admitted"),
    ),
    "wave.monster": (
        ("OnWaveMonster", "global_listener", ""),
    ),
}


def _event_aliases(event: GameEvent, rules: RuleBook | None = None) -> tuple[EventAlias, ...]:
    if event.event_type == "wave.monster":
        payload_reason = _wave_monster_payload_block_reason(event)
        if payload_reason:
            return (
                EventAlias(
                    callback_event="OnWaveMonster",
                    scope_kind="global_listener",
                    source_basis="wave_monster_payload_validation",
                    admission_status="blocked",
                    blocked_dependency=payload_reason,
                    runtime_event_source=event.event_type,
                ),
            )
    aliases: list[EventAlias] = []
    raw_events = event.payload.get("callback_events")
    if isinstance(raw_events, (list, tuple)):
        for item in raw_events:
            if isinstance(item, str) and item:
                aliases.append(_event_alias_for_callback(event, item, "event.payload.callback_events", rules))
    for key in ("callback_event", "tbgd_event"):
        value = event.payload.get(key)
        if isinstance(value, str) and value:
            aliases.append(_event_alias_for_callback(event, value, f"event.payload.{key}", rules))
    if event.window.startswith("On"):
        aliases.append(_event_alias_for_callback(event, event.window, "event.window", rules))
    if not aliases:
        families = rules.status_event_families_for_runtime_event(event.event_type) if rules is not None else ()
        for family in families:
            aliases.append(_event_alias_for_family(event, family, f"status_event_family:{event.event_type}"))
        if not aliases:
            for callback_event, scope_kind, blocked_dependency in CANONICAL_EVENT_ALIASES.get(event.event_type, ()):
                family = rules.status_event_family(callback_event) if rules is not None else None
                if family is not None:
                    aliases.append(_event_alias_for_family(event, family, f"canonical_event_alias_fallback:{event.event_type}"))
                    continue
                aliases.append(
                    EventAlias(
                        callback_event=callback_event,
                        scope_kind=scope_kind,
                        source_basis=f"canonical_event_alias:{event.event_type}",
                        admission_status="blocked" if blocked_dependency else "executable",
                        blocked_dependency=blocked_dependency,
                        runtime_event_source=event.event_type,
                    )
                )
    deduped: list[EventAlias] = []
    seen: set[tuple[str, str]] = set()
    for alias in aliases:
        key = (alias.callback_event, alias.scope_kind)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(alias)
    if deduped:
        return tuple(deduped)
    return (
        EventAlias(
            callback_event="",
            scope_kind=_event_scope_kind(event),
            source_basis=f"runtime_event:{event.event_type}",
            admission_status="blocked",
            blocked_dependency="event_alias_missing",
        ),
    )


def _wave_monster_payload_block_reason(event: GameEvent) -> str:
    payload = event.payload
    required = (
        "wave_definition_id",
        "wave_index",
        "unit_id",
        "entry_id",
        "position",
        "source_trace",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        return "wave_monster_payload_incomplete"
    if not isinstance(payload.get("source_trace"), dict) or not payload.get("source_trace"):
        return "wave_monster_source_trace_missing"
    if str(payload.get("unit_id") or "") != str(event.target_id or payload.get("unit_id") or ""):
        return "wave_monster_target_payload_mismatch"
    return ""


def _event_alias_for_callback(
    event: GameEvent,
    callback_event: str,
    source_basis: str,
    rules: RuleBook | None,
) -> EventAlias:
    family = rules.status_event_family(callback_event) if rules is not None else None
    if family is None:
        return EventAlias(
            callback_event=callback_event,
            scope_kind=_scope_kind_for_callback_event(event, callback_event),
            source_basis=source_basis,
            admission_status="executable" if rules is None else "blocked",
            blocked_dependency="" if rules is None else f"status_event_family_missing:{callback_event}",
            runtime_event_source=event.event_type,
        )
    return _event_alias_for_family(event, family, source_basis)


def _event_alias_for_family(event: GameEvent, family: StatusEventFamilyIR, source_basis: str) -> EventAlias:
    blocked_dependency = family.blocking_dependency or family.blocked_reason
    admission_status = family.admission_status
    if family.coverage_status != "executable" or family.admission_status != "executable":
        admission_status = "blocked"
        blocked_dependency = blocked_dependency or f"status_event_family_not_executable:{family.coverage_status}"
    return EventAlias(
        callback_event=family.callback_event,
        scope_kind=family.default_scope_kind or _scope_kind_for_callback_event(event, family.callback_event),
        source_basis=source_basis,
        admission_status=admission_status,
        blocked_dependency=blocked_dependency,
        status_event_family_id=family.status_event_family_id,
        event_family=family.event_family,
        runtime_event_source=event.event_type,
    )


def _event_scope_kind(event: GameEvent) -> str:
    value = event.payload.get("listener_scope")
    if isinstance(value, str) and value:
        return value
    if event.event_type in {"damage.before_hit", "damage.hit", "toughness.hit"}:
        return "per_hit_target_local"
    if event.event_type in {
        "hp.change",
        "heal.after",
        "shield.change",
        "sp.change",
        "energy.change",
        "energy.before_change",
        "toughness.before_hit",
        "action_delay.changed",
    }:
        return "being_hit_target_local"
    if event.event_type == "unit.defeated":
        return "owner_local"
    if event.event_type.startswith("break."):
        return "being_hit_target_local"
    if event.window.startswith("OnListen"):
        return "global_listener"
    if event.window.startswith("OnBeing"):
        return "being_hit_target_local"
    if "Hit" in event.window:
        return "per_hit_target_local"
    return "status_local"


def _scope_kind_for_callback_event(event: GameEvent, callback_event: str) -> str:
    explicit = event.payload.get("listener_scope")
    if isinstance(explicit, str) and explicit:
        return explicit
    if callback_event == "OnListenAllowAction":
        return "owner_local"
    if callback_event in {"OnAfterDealHeal", "OnBeforeDealHeal"}:
        return "actor_local"
    if callback_event in {
        "OnHPChange",
        "OnHPOverflow",
        "OnAfterBeingHeal",
        "OnBeforeBeingHeal",
        "OnShieldChange",
        "OnSPChange",
        "OnEnergyPointChange",
        "OnBeforeEnergyPointChange",
        "OnBeforeBeingStanceDamage",
        "OnBeingStanceDamage",
        "OnActionDelayEffect",
        "OnActionDelayEffectAll",
    }:
        return "being_hit_target_local"
    if callback_event in {
        "OnBeforeHitAll",
        "OnAfterHitAll",
        "OnAfterSkillUse",
        "OnBeforeSkillUse",
        "OnBeforeAttack",
        "OnAfterAttack",
        "OnActionEnd",
        "OnBeforeInsertActionPrepare",
        "OnInsertActionStart",
        "OnInsertActionFinish",
        "OnListenInsertAbilityFinish",
    }:
        return "actor_local"
    if callback_event.startswith("OnListen"):
        return "global_listener"
    if (
        callback_event.startswith("OnBeing")
        or "BeingHit" in callback_event
        or "BeingAttacked" in callback_event
        or "BeingBreak" in callback_event
    ):
        return "being_hit_target_local"
    if "Hit" in callback_event:
        return "per_hit_target_local"
    if callback_event in {"OnBeforeSkillUse", "OnBeforeAttack", "OnAfterAttack", "OnAfterSkillUse"}:
        return "actor_local"
    if callback_event in {"OnTriggerDeath", "OnListenCharacterDie", "OnTriggerDeathrattle"}:
        return "owner_local"
    if callback_event == "OnBeforeDying":
        return "owner_local"
    if callback_event in {
        "OnStack",
        "OnPhase1",
        "OnCreate",
        "OnDestroy",
        "OnModifierAdd",
        "OnModifierRemove",
        "OnAddModifierSuc",
        "OnModifierOnStack",
        "OnModifierDotAdd",
    }:
        return "status_local"
    return _event_scope_kind(event)


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
    alias: EventAlias,
    state: BattleState,
) -> ListenerMatch | None:
    unit_id = str(detail.get("owner_id") or event.target_id or "")
    modifier_name = str(detail.get("modifier_name") or callback.modifier_name)
    scope_kind = callback.scope_kind or _event_scope_kind(event)
    if event.event_type == "unit.defeated" and alias.callback_event in {
        "OnTriggerDeath",
        "OnListenCharacterDie",
        "OnTriggerDeathrattle",
    }:
        scope_kind = alias.scope_kind
    status_instance_id = str(detail.get("instance_id") or "")
    scope_ok, scope_reason = _scope_matches(event, scope_kind, detail, explicit=explicit)
    status = "matched"
    reason = ""
    if not scope_ok:
        status = "skipped"
        reason = scope_reason
    elif not _status_detail_admits_callback(detail, callback):
        status = "skipped"
        reason = "status_trigger_id_not_admitted_for_event"
    elif callback.coverage_status != "executable":
        status = "blocked"
        reason = callback.blocked_reason or f"listener_not_executable:{callback.coverage_status}"
    elif callback.admission_status != "executable":
        status = "blocked"
        reason = callback.blocking_dependency or f"listener_not_admitted:{callback.admission_status}"
    elif scope_kind == "global_listener" and not explicit and not _global_listener_auto_admitted(event, callback, alias):
        status = "blocked"
        reason = "global_listener_auto_execution_not_admitted"
    if status == "skipped" and not explicit:
        return None
    status_order = _status_order(state, unit_id, detail)
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
        order_key=_listener_order_key(state, scope_kind, unit_id, status_order, callback),
        event_alias=alias.to_json(),
        blocked_category=_blocked_category(reason),
    )


def _global_listener_auto_admitted(event: GameEvent, callback: StatusCallbackIR, alias: EventAlias) -> bool:
    return (
        event.event_type == "action.after_attack"
        and alias.callback_event == "OnListenAfterAttack"
        and callback.event == "OnListenAfterAttack"
        and alias.admission_status == "executable"
    ) or (
        event.event_type == "turn.end"
        and alias.callback_event == "OnListenTurnEnd"
        and callback.event == "OnListenTurnEnd"
        and alias.admission_status == "executable"
    ) or (
        (
            event.event_type in MUTATION_BACKED_EVENT_TYPES
            or event.event_type in {"status.lifecycle", "break.triggered"}
        )
        and alias.callback_event.startswith("OnListen")
        and callback.event == alias.callback_event
        and alias.admission_status == "executable"
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
        if event.event_type == "unit.defeated":
            return (owner_id == actor_id, "scope_kill_credit_owner_mismatch")
        return (owner_id in {actor_id, primary_target_id, current_hit_target_id}, "scope_owner_not_in_event_context")
    if scope_kind == "status_local":
        target_id = str(event.target_id or event.payload.get("target_id") or "")
        event_modifier = event.payload.get("modifier_name")
        status_instance_id = str(detail.get("instance_id") or "")
        event_status_instance_id = event.payload.get("status_instance_id")
        modifier_ok = not isinstance(event_modifier, str) or not event_modifier or event_modifier == detail.get("modifier_name")
        instance_ok = (
            not isinstance(event_status_instance_id, str)
            or not event_status_instance_id
            or event_status_instance_id == status_instance_id
        )
        return (owner_id == target_id and modifier_ok and instance_ok, "scope_status_local_mismatch")
    return False, f"scope_not_admitted:{scope_kind}"


def _status_detail_admits_callback(detail: dict[str, JSONValue], callback: StatusCallbackIR) -> bool:
    mapping = detail.get("trigger_ids_by_event")
    if not isinstance(mapping, dict):
        return True
    raw_ids = mapping.get(callback.event)
    if not isinstance(raw_ids, list):
        return False
    return callback.callback_id in {str(item) for item in raw_ids if isinstance(item, str)}


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


def _alias_blocked_match(
    event: GameEvent,
    alias: EventAlias,
    state: BattleState,
    *,
    unit_id: str | None = None,
    modifier_name: str | None = None,
) -> ListenerMatch:
    reason = alias.blocked_dependency or f"event_alias_not_admitted:{alias.admission_status}"
    target_unit = unit_id or str(event.target_id or _event_current_hit_target_id(event) or "")
    return ListenerMatch(
        listener_kind=_listener_kind_for_scope(alias.scope_kind),
        scope_kind=alias.scope_kind,
        callback_event=alias.callback_event,
        unit_id=target_unit,
        modifier_name=modifier_name or "",
        callback=None,
        status="blocked",
        reason=reason,
        source="event_alias_matrix",
        order_key=_listener_order_key(state, alias.scope_kind, target_unit, -1, None),
        event_alias=alias.to_json(),
        blocked_category=_blocked_category(reason),
    )


def _pre_mutation_listener_block_reason(event: GameEvent) -> str:
    admission = event.payload.get("pre_mutation_execution_admission")
    if admission != "blocked":
        return ""
    reason = event.payload.get("blocked_reason")
    return str(reason) if isinstance(reason, str) and reason else PRE_MUTATION_BLOCK_REASON


def _event_mutation_depth(event: GameEvent) -> int:
    value = event.payload.get("mutation_event_depth")
    return int(value) if isinstance(value, int) and value >= 0 else 0


def _pre_mutation_blocked_match(
    event: GameEvent,
    alias: EventAlias,
    state: BattleState,
    *,
    reason: str,
    unit_id: str | None = None,
    modifier_name: str | None = None,
) -> ListenerMatch:
    target_unit = unit_id or str(event.target_id or _event_current_hit_target_id(event) or "")
    return ListenerMatch(
        listener_kind=_listener_kind_for_scope(alias.scope_kind),
        scope_kind=alias.scope_kind,
        callback_event=alias.callback_event,
        unit_id=target_unit,
        modifier_name=modifier_name or "",
        callback=None,
        status="blocked",
        reason=reason,
        source="mutation_backed_event_safety",
        order_key=_listener_order_key(state, alias.scope_kind, target_unit, -1, None),
        event_alias=alias.to_json(),
        blocked_category=_blocked_category(reason),
    )


def _listener_order_key(
    state: BattleState,
    scope_kind: str,
    unit_id: str,
    status_order: int,
    callback: StatusCallbackIR | None,
) -> dict[str, JSONValue]:
    unit_order = _unit_order(state, unit_id)
    callback_source_key = ""
    callback_id = ""
    task_order: list[str] = []
    if callback is not None:
        callback_source_key = f"{callback.source.source_path}:{callback.source.raw_type}:{callback.source.raw_id}"
        callback_id = callback.callback_id
        task_order = list(callback.task_ids)
    return {
        "scope_priority": SCOPE_PRIORITY.get(scope_kind, 999),
        "scope_kind": scope_kind,
        "unit_order": unit_order,
        "unit_id": unit_id,
        "status_order": status_order,
        "callback_source_order": callback_source_key,
        "callback_id": callback_id,
        "task_order": task_order,
    }


def _match_sort_key(match: ListenerMatch) -> tuple[object, ...]:
    order = match.order_key or {}
    return (
        int(order.get("scope_priority") or 999),
        int(order.get("unit_order") or 999999),
        int(order.get("status_order") if isinstance(order.get("status_order"), int) else 999999),
        str(order.get("callback_source_order") or ""),
        str(order.get("callback_id") or ""),
        tuple(str(item) for item in order.get("task_order", []) if isinstance(item, str))
        if isinstance(order.get("task_order"), list)
        else (),
    )


def _unit_order(state: BattleState, unit_id: str) -> int:
    for index, candidate in enumerate(sorted(state.units)):
        if candidate == unit_id:
            return index
    return 999999


def _status_order(state: BattleState, unit_id: str, detail: dict[str, JSONValue]) -> int:
    unit = state.units.get(unit_id)
    if unit is None:
        return 999999
    instance_id = str(detail.get("instance_id") or "")
    for index, candidate in enumerate(unit.flags.get("status_details", ())):
        if isinstance(candidate, dict) and str(candidate.get("instance_id") or "") == instance_id:
            return index
    return 999999


def _blocked_category(reason: str) -> str:
    if not reason:
        return ""
    if "event_alias" in reason or "listener_event_mapping" in reason:
        return "event_alias_missing"
    if "source_mode_not_admitted" in reason or reason.startswith("source_"):
        return "source_not_admitted"
    if reason.startswith("scope_") or "scope_not_admitted" in reason:
        return "scope_not_admitted"
    if "condition" in reason:
        return "condition_not_admitted"
    if "target" in reason or "alias" in reason:
        return "target_not_admitted"
    if "effect" in reason or "opcode" in reason or "callback_task" in reason:
        return "effect_not_admitted"
    if "queue" in reason or "intent" in reason or "normalized_action_delay" in reason:
        return "downstream_intent_missing"
    if reason in {"status_callback_missing", "listener_match_missing"}:
        return "effect_not_admitted"
    if reason == "status_detail_missing":
        return "target_not_admitted"
    return "downstream_intent_missing"


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
    metadata = metadata or {}
    order_key = metadata.get("order_key") if isinstance(metadata.get("order_key"), dict) else {}
    event_alias = metadata.get("event_alias") if isinstance(metadata.get("event_alias"), dict) else {}
    blocked_category = str(metadata.get("blocked_category") or _blocked_category(reason))
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
            "blocked_category": blocked_category,
            "order_key": order_key,
            "event_alias": event_alias,
            "metadata": metadata,
        },
        trace={"event_id": event.to_json()["event_id"], "listener_id": listener_id},
    ).to_json()


def _listener_records_from_trigger_windows(
    windows: tuple[dict[str, JSONValue], ...],
) -> tuple[dict[str, JSONValue], ...]:
    records: list[dict[str, JSONValue]] = []
    for index, window in enumerate(windows):
        if not isinstance(window, dict):
            continue
        metadata = window.get("metadata") if isinstance(window.get("metadata"), dict) else {}
        tbgd_event = str(window.get("tbgd_event") or "")
        alias = EventAlias(
            callback_event=tbgd_event,
            scope_kind="actor_local",
            source_basis="trigger_window.tbgd_event",
        )
        event = GameEvent(
            event_type=tbgd_event or "trigger.window",
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
                    "tbgd_event": tbgd_event,
                    "status_instance_id": str(window.get("status_instance_id") or ""),
                    "modifier_name": str(window.get("modifier_name") or ""),
                    "mutation_count": int(window.get("mutation_count") or 0),
                    "order_key": {
                        "scope_priority": SCOPE_PRIORITY["actor_local"],
                        "scope_kind": "actor_local",
                        "unit_order": index,
                        "unit_id": str(metadata.get("actor_id") or "") if isinstance(metadata, dict) else "",
                        "status_order": index,
                        "callback_source_order": "trigger_system",
                        "callback_id": str(window.get("trigger_id") or ""),
                        "task_order": [],
                    },
                    "event_alias": alias.to_json(),
                    "blocked_category": _blocked_category(reason),
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
