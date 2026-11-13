from __future__ import annotations

from dataclasses import dataclass, replace
from ..core.content_hooks import processor_replaces_status_callback

from ..core.model import ActionCommand, BattleState, GameEvent, HitWindowInvocationFact, JSONValue, Mutation, PendingDefeatPlan, RNGEvent, TargetResolution, QueueActionStartFact, QueueActionTerminalFact, StanceCountDownFact, StatusImmunityFact
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..core.transition_outcome import ExecutionNodeResult
from ..resource_event_contract import (
    resource_scope_for_callback,
    resource_scope_for_event,
)
from ..rules.ir import ActionDefinitionIR, StatusCallbackIR, StatusEventFamilyIR
from ..rules.rulebook import RuleBook
from .damage import DamageModifierContribution, DamageSystem, DamageWindowLedger, lifecycle_settlement_records
from .ability_property_watchers import AbilityPropertyWatcherSystem
from .action_event_contract import ActionWindowExpectedScope
from .effect import EffectRegistry
from .mutation_events import (
    MUTATION_BACKED_EVENT_TYPES,
    PRE_MUTATION_BLOCK_REASON,
    HealEventFact,
    native_energy_change_value,
    native_hp_change_value,
    mutation_backed_event_id,
)
from .phase_machine import CombatPhaseMachine
from .shield import ShieldExhaustionFact
from .status import StatusSystem
from .status_callbacks import StatusCallbackSystem
from .task_graph import (
    TaskGraphContinuation,
    TaskGraphExecutionHooks,
    TaskGraphNodeProjection,
)
from .timeline import TimelineSystem
from .trigger import TriggerSystem
from .unit_lifecycle import LIMBO_CALLBACKS, UnitLifecycleSystem


@dataclass(frozen=True)
class EventNormalization:
    before: GameEvent
    after: GameEvent
    kind: str


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
    node_results: tuple[ExecutionNodeResult, ...] = ()
    event_normalizations: tuple[EventNormalization, ...] = ()
    task_graph_projections: tuple[TaskGraphNodeProjection, ...] = ()
    dispatched_event_ids: frozenset[str] = frozenset()
    damage_modifiers: tuple[DamageModifierContribution, ...] = ()

    def __post_init__(self) -> None:
        if any(type(item) is not DamageModifierContribution for item in self.damage_modifiers):
            raise TypeError("event dispatch damage modifiers must be typed")
        if self.errors and self.damage_modifiers:
            raise ValueError("blocked event dispatch leaks damage modifiers")
        object.__setattr__(self, "damage_modifiers", tuple(self.damage_modifiers))
        projections = tuple(self.task_graph_projections)
        if any(type(item) is not TaskGraphNodeProjection for item in projections):
            raise TypeError("event dispatch task graph projections are invalid")
        if self.errors and projections:
            raise ValueError("blocked event dispatch leaks task graph projections")
        object.__setattr__(self, "task_graph_projections", projections)


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
    status_detail: dict[str, JSONValue] | None = None

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
        self.damage = damage or DamageSystem(rules)
        self.timeline = timeline or TimelineSystem()
        self.trigger_system = trigger_system or TriggerSystem(rules, effect_registry, reducer=self.reducer)
        self.status_callbacks = status_callbacks or StatusCallbackSystem(
            rules,
            damage=self.damage,
            reducer=self.reducer,
            timeline=self.timeline,
            effect_registry=effect_registry,
        )
        self.ability_property_watchers = AbilityPropertyWatcherSystem(
            rules,
            status_callbacks=self.status_callbacks,
            reducer=self.reducer,
        )
        self.phases = CombatPhaseMachine()
        self._registered_event_nested_provider = None

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

    def dispatch_action_window_listeners(
        self,
        state: BattleState,
        *,
        event: GameEvent,
        damage_window_ledger: DamageWindowLedger | None,
        nested_ability_provider: StatusNestedAbilityHookProvider,
        expected_window_scope: ActionWindowExpectedScope,
    ) -> EventDispatchResult:
        from .ability import StatusNestedAbilityHookProvider

        if type(nested_ability_provider) is not StatusNestedAbilityHookProvider:
            return self.dispatch_blocked(
                state,
                event=event,
                listener_kind="action_window_formal_root_transport",
                scope=_event_scope_kind(event),
                reason="action_window_nested_ability_provider_type_invalid",
                metadata={"event_type": event.event_type},
            )
        if not event.event_type.startswith("action.window."):
            return self.dispatch_blocked(
                state,
                event=event,
                listener_kind="action_window_formal_root_transport",
                scope=_event_scope_kind(event),
                reason="action_window_formal_root_event_invalid",
                metadata={"event_type": event.event_type},
            )
        fact = event.admitted_action_target_fact
        if type(expected_window_scope) is not ActionWindowExpectedScope or fact is None:
            return self.dispatch_blocked(
                state,
                event=event,
                listener_kind="action_window_formal_root_transport",
                scope=_event_scope_kind(event),
                reason="action_window_target_scope_missing",
                metadata={"event_type": event.event_type},
            )
        scope_reason = fact.invocation_blocked_reason(
            expected_scope=expected_window_scope
        )
        if scope_reason:
            return self.dispatch_blocked(
                state,
                event=event,
                listener_kind="action_window_formal_root_transport",
                scope=_event_scope_kind(event),
                reason=scope_reason,
                metadata={"event_type": event.event_type},
            )
        return self._dispatch_event(
            state,
            event=replace(
                event,
                expected_action_window_scope=expected_window_scope,
            ),
            damage_window_ledger=damage_window_ledger,
            status_nested_ability_provider=nested_ability_provider,
            expected_window_scope=expected_window_scope,
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
        task_graph_continuation: TaskGraphContinuation | None = None,
        nested_ability_hooks: TaskGraphExecutionHooks | None = None,
        _processor_depth: int = 0,
    ) -> EventDispatchResult:
        return self._dispatch_event(
            state,
            event=event,
            command=command,
            action_definition=action_definition,
            target_resolution=target_resolution,
            enabled=enabled,
            skipped_reason=skipped_reason,
            unit_id=unit_id,
            modifier_name=modifier_name,
            damage_window_ledger=damage_window_ledger,
            task_graph_continuation=task_graph_continuation,
            nested_ability_hooks=nested_ability_hooks,
            _processor_depth=_processor_depth,
        )

    def _dispatch_event(
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
        task_graph_continuation: TaskGraphContinuation | None = None,
        nested_ability_hooks: TaskGraphExecutionHooks | None = None,
        status_nested_ability_provider: StatusNestedAbilityHookProvider | None = None,
        expected_window_scope: ActionWindowExpectedScope | None = None,
        _processor_depth: int = 0,
    ) -> EventDispatchResult:
        from .ability import StatusNestedAbilityHookProvider

        if event.event_type == "status.immunity":
            fact = event.status_immunity_fact
            reason = ""
            if type(fact) is not StatusImmunityFact or not fact.matches(state, event):
                reason = "status_immunity_fact_missing_or_mismatched"
            elif ((unit_id is not None and unit_id != fact.target_id)
                    or (modifier_name is not None and modifier_name != fact.protection_modifier_name)):
                reason = "status_immunity_receiver_identity_mismatch"
            elif event.window != "OnImmuneDebuff":
                reason = "status_immunity_callback_window_mismatch"
            elif any(value is not None for value in (command, action_definition, target_resolution)):
                reason = "status_immunity_action_context_not_admitted"
            elif event.payload.get("param_entity_id") not in (None, fact.target_id):
                reason = "status_immunity_parameter_identity_mismatch"
            elif any(
                isinstance(detail, dict)
                and detail.get("owner_id") == unit.unit_id
                and detail.get("status_id") in unit.statuses
                and detail.get("lifecycle_state") in {"active", "active_partial"}
                and isinstance(detail.get("trigger_ids_by_event"), dict)
                and any(name.startswith("OnListenImmune") and trigger_ids
                        for name, trigger_ids in detail["trigger_ids_by_event"].items())
                for unit in state.units.values()
                for detail in unit.flags.get("status_details", ())
            ):
                reason = "status_immunity_global_listener_not_admitted"
            if reason:
                return self.dispatch_blocked(state, event=event, listener_kind="status_immunity_dispatch",
                    scope="owner_local", reason=reason)
            unit_id, modifier_name = fact.target_id, fact.protection_modifier_name
        if event.event_type == "energy.change":
            _, energy_reason = native_energy_change_value(event)
            if energy_reason:
                return self.dispatch_blocked(state, event=event, listener_kind="energy_change_event_dispatch",
                    scope=_event_scope_kind(event), reason=energy_reason)
        if event.event_type == "hp.change":
            _, hp_reason = native_hp_change_value(event)
            if hp_reason:
                return self.dispatch_blocked(state, event=event, listener_kind="hp_change_event_dispatch",
                    scope=_event_scope_kind(event), reason=hp_reason)
        if event.event_type in {"heal.after", "heal.snapshot.created"}:
            heal_fact = event.heal_event_fact
            heal_reason = ""
            if event.event_type == "heal.snapshot.created":
                if type(heal_fact) is not HealEventFact or not heal_fact.matches_snapshot(event):
                    heal_reason = "heal_snapshot_fact_missing_or_mismatched"
                elif any(
                    value is not None
                    for value in (command, action_definition, target_resolution)
                ):
                    heal_reason = "heal_snapshot_action_context_not_admitted"
            elif type(heal_fact) is not HealEventFact or not heal_fact.matches_heal_after(event):
                heal_reason = "heal_event_fact_missing_or_mismatched"
            if heal_reason:
                return self.dispatch_blocked(
                    state,
                    event=event,
                    listener_kind="heal_event_dispatch",
                    scope=_event_scope_kind(event),
                    reason=heal_reason,
                    metadata={"event_type": event.event_type},
                )
        transport_reason = _task_graph_transport_reason(
            task_graph_continuation,
            nested_ability_hooks,
        )
        if transport_reason:
            return self.dispatch_blocked(
                state,
                event=event,
                listener_kind="task_graph_event_transport",
                scope=_event_scope_kind(event),
                reason=transport_reason,
                metadata={"event_type": event.event_type},
            )
        if status_nested_ability_provider is not None and (
            type(status_nested_ability_provider) is not StatusNestedAbilityHookProvider
            or task_graph_continuation is not None
            or nested_ability_hooks is not None
        ):
            return self.dispatch_blocked(
                state,
                event=event,
                listener_kind="action_window_formal_root_transport",
                scope=_event_scope_kind(event),
                reason="action_window_formal_root_transport_conflict",
                metadata={"event_type": event.event_type},
            )
        event_before_normalization = event
        event, param_entity_reason = _event_with_typed_param_entity(state, event)
        if param_entity_reason:
            return _with_controlled_event_normalization(
                self.dispatch_blocked(
                    state,
                    event=event,
                    listener_kind="event_parameter_dispatch",
                    scope=_event_scope_kind(event),
                    reason=param_entity_reason,
                    metadata={"event_type": event.event_type},
                ),
                before=event_before_normalization,
                after=event,
            )
        lifecycle_payload_reason = _lifecycle_event_payload_block_reason(
            state,
            event,
        )
        if lifecycle_payload_reason:
            return _with_controlled_event_normalization(
                self.dispatch_blocked(
                    state,
                    event=event,
                    listener_kind="lifecycle_event_dispatch",
                    scope=_event_scope_kind(event),
                    reason=lifecycle_payload_reason,
                    metadata={"event_type": event.event_type},
                ),
                before=event_before_normalization,
                after=event,
            )
        transition_payload_reason = _battle_state_transition_event_block_reason(
            event,
            self.rules,
        )
        if transition_payload_reason:
            return _with_controlled_event_normalization(
                self.dispatch_blocked(
                    state,
                    event=event,
                    listener_kind="battle_state_transition_event_dispatch",
                    scope=_event_scope_kind(event),
                    reason=transition_payload_reason,
                    metadata={"event_type": event.event_type},
                ),
                before=event_before_normalization,
                after=event,
            )
        phase_reason = self.phases.event_blocked_reason(state, event.event_type)
        if phase_reason:
            return _with_controlled_event_normalization(
                self.dispatch_blocked(
                    state,
                    event=event,
                    listener_kind="listener_dispatch",
                    scope=_event_scope_kind(event),
                    reason=phase_reason,
                    metadata={"combat_phase": self.phases.current_phase(state)},
                ),
                before=event_before_normalization,
                after=event,
            )
        if command is not None and action_definition is not None and target_resolution is not None:
            result = self._dispatch_action_window_event(
                state,
                event=event,
                command=command,
                action_definition=action_definition,
                target_resolution=target_resolution,
                enabled=enabled,
                skipped_reason=skipped_reason,
            )
        else:
            result = self._dispatch_listener_event(
                state,
                event=event,
                unit_id=unit_id,
                modifier_name=modifier_name,
                damage_window_ledger=damage_window_ledger,
                task_graph_continuation=task_graph_continuation,
                nested_ability_hooks=nested_ability_hooks,
                status_nested_ability_provider=status_nested_ability_provider,
                expected_window_scope=expected_window_scope,
            )
        if event.event_type == "shield.exhausted" and not result.errors:
            result = self._remove_exhausted_shield_owners(result, event)
        result = self._reconcile_ability_property_watchers(
            result,
            before_state=state,
            event=event,
            damage_window_ledger=damage_window_ledger,
            task_graph_continuation=task_graph_continuation,
            nested_ability_hooks=nested_ability_hooks,
        )
        result = self._complete_limbo_window(
            state, result, event=event, damage_window_ledger=damage_window_ledger,
            task_graph_continuation=task_graph_continuation, nested_ability_hooks=nested_ability_hooks,
            status_nested_ability_provider=status_nested_ability_provider,
        )
        result = self._complete_battle_event_dependencies(state, result, event)
        result = self._notify_content_processors(
            result, event=event, damage_window_ledger=damage_window_ledger,
            processor_depth=_processor_depth,
        )
        return _with_controlled_event_normalization(
            _with_event_dispatch_node_result(result, event),
            before=event_before_normalization,
            after=event,
        )

    def _notify_content_processors(
        self,
        result: EventDispatchResult,
        *,
        event: GameEvent,
        damage_window_ledger: DamageWindowLedger | None,
        processor_depth: int,
    ) -> EventDispatchResult:
        """H2: notify mounted content processors after normal listener dispatch.

        Generic dispatch: processors are looked up by their own content's
        presence and subscription scope, in content_id order. Processor
        output joins the same dispatch result and atomic boundary; emitted
        events re-enter this same typed channel (with a re-entry depth cap).
        """
        if not self.rules.content_processors or result.errors:
            return result
        from ..core.content_hooks import (
            PROCESSOR_EVENT_DEPTH_LIMIT,
            EventHookContext,
            ProcessorServices,
            run_hook,
        )

        mounts = self.rules.processors_for_event(result.after_state, event)
        if not mounts:
            return result
        if processor_depth >= PROCESSOR_EVENT_DEPTH_LIMIT:
            return replace(
                result,
                errors=(*result.errors, "content_processor_event_depth_exceeded"),
                damage_modifiers=(), task_graph_projections=(),
                node_results=(
                    *result.node_results,
                    ExecutionNodeResult(
                        node_kind="content_processor_event",
                        node_id=event.event_id or event.event_type,
                        status="blocked",
                        reason_code="content_processor_event_depth_exceeded",
                    ),
                ),
            )
        current = result.after_state
        mutations = list(result.mutations)
        events = list(result.events)
        rng_events = list(result.rng_events)
        records = list(result.records)
        node_results = list(result.node_results)
        errors: list[str] = []
        normalizations = list(result.event_normalizations)
        dispatched_ids = set(result.dispatched_event_ids)
        damage_modifiers = list(result.damage_modifiers)
        for mount in mounts:
            services = ProcessorServices(
                current, self.rules,
                producer_id=f"{mount.content_id}:{mount.version}",
                event_dispatcher=self,
                processor_depth=processor_depth + 1,
            )
            ctx = EventHookContext(state=current, event=event, services=services)
            hook = run_hook(mount.processor, "event", ctx)
            node_results.append(ExecutionNodeResult(
                node_kind="content_processor_event",
                node_id=f"{mount.content_id}:{event.event_id or event.event_type}",
                status="complete" if hook.ok else "blocked",
                reason_code=hook.blocked_reason,
            ))
            if not hook.ok:
                errors.append(hook.blocked_reason or "content_processor_event_blocked")
                break
            reduction = self.reducer.apply_all_result(current, hook.mutations)
            if not reduction.ok:
                conflict = reduction.conflicts[0].code if reduction.conflicts else "unknown"
                errors.append(f"content_processor_reducer_conflict:{conflict}")
                break
            current = reduction.after_state
            mutations.extend(hook.mutations)
            records.extend(hook.records)
            damage_modifiers.extend(hook.damage_modifiers)
            rng_events.extend(hook.rng_events)
            normalizations.extend(hook.event_normalizations)
            dispatched_ids.update(hook.dispatched_event_ids)
            for index, hook_event in enumerate(hook.events):
                if not hook_event.event_id:
                    hook_event = replace(
                        hook_event,
                        event_id=(
                            f"event:{current.event_index}:processor:"
                            f"{mount.content_id}:{index}:{hook_event.event_type}"
                        ),
                    )
                if hook_event.event_id in dispatched_ids:
                    events.append(hook_event)
                    continue
                dispatched = self.dispatch_event(
                    current,
                    event=hook_event,
                    damage_window_ledger=damage_window_ledger,
                    _processor_depth=processor_depth + 1,
                )
                current = dispatched.after_state
                mutations.extend(dispatched.mutations)
                # dispatch_event already includes its input event. Appending it
                # before dispatch would duplicate the identity inside task graphs.
                events.extend(dispatched.events or (hook_event,))
                rng_events.extend(dispatched.rng_events)
                records.extend(dispatched.records)
                node_results.extend(dispatched.node_results)
                normalizations.extend(dispatched.event_normalizations)
                dispatched_ids.update(dispatched.dispatched_event_ids)
                if dispatched.errors:
                    errors.extend(dispatched.errors)
                    break
            if errors:
                break
        if errors:
            return replace(
                result,
                errors=tuple(dict.fromkeys(errors)),
                node_results=tuple(node_results),
                damage_modifiers=(), task_graph_projections=(),
            )
        return replace(
            result,
            after_state=current,
            mutations=tuple(mutations),
            events=tuple(events),
            rng_events=tuple(rng_events),
            records=tuple(records),
            node_results=tuple(node_results),
            event_normalizations=tuple(normalizations),
            dispatched_event_ids=frozenset(dispatched_ids),
            damage_modifiers=tuple(damage_modifiers),
        )

    def _complete_battle_event_dependencies(
        self, before: BattleState, result: EventDispatchResult, event: GameEvent,
    ) -> EventDispatchResult:
        if result.errors or event.event_type not in {"unit.defeated", "unit.removed"}:
            return result
        from .battle_event import retire_battle_event

        dependency_id = str(event.target_id or "")
        if dependency_id not in result.after_state.units:
            return result
        for unit_id in sorted(result.after_state.units):
            unit = result.after_state.units[unit_id]
            if (unit.flags.get("entity_type") != "battle_event"
                    or unit.lifecycle_status == "removed"
                    or not unit.flags.get("battle_event_creation_effect_id")):
                continue
            cleanup = retire_battle_event(self.rules, result.after_state, unit_id, dependency_id)
            if cleanup.unsupported:
                return _atomic_dispatch_failure(before, replace(result,
                    errors=(*result.errors, *cleanup.unsupported)))
            if not cleanup.mutations:
                continue
            reduced = self.reducer.apply_all_result(result.after_state, cleanup.mutations)
            if not reduced.ok:
                return _atomic_dispatch_failure(before, replace(result,
                    errors=(*result.errors, "battle_event_retirement_commit_failed")))
            result = replace(result, after_state=reduced.after_state,
                mutations=(*result.mutations, *cleanup.mutations),
                events=(*result.events, *cleanup.events),
                records=(*result.records, *cleanup.records),
                rng_events=(*result.rng_events, *cleanup.rng_events),
                dispatched_event_ids=result.dispatched_event_ids | cleanup.dispatched_event_ids)
        return result

    def _complete_limbo_window(
        self, before: BattleState, result: EventDispatchResult, *, event: GameEvent,
        damage_window_ledger: DamageWindowLedger | None,
        task_graph_continuation: TaskGraphContinuation | None,
        nested_ability_hooks: TaskGraphExecutionHooks | None,
        status_nested_ability_provider: StatusNestedAbilityHookProvider | None,
    ) -> EventDispatchResult:
        stages = tuple(item[0] for item in LIMBO_CALLBACKS)
        if event.event_type not in stages or result.errors:
            return result
        plan = event.pending_defeat_plan
        lifecycle = UnitLifecycleSystem()
        try:
            rescued_unit = result.after_state.units.get(plan.unit_id)
            if (rescued_unit is not None and "pending_defeat" not in rescued_unit.flags
                    and rescued_unit.lifecycle_status == "active" and rescued_unit.hp > 0):
                # 窗口内已被正式救回（如锁血）：窗口关闭，后续回调的队列变化照常生效。
                return result
            # A limbo wait window may enqueue one admitted turn-insert rescue.
            # The committing executor runs it before publishing this transition,
            # so the window stays open here instead of finalizing the defeat.
            queue_mutations = tuple(
                mutation
                for mutation in result.mutations
                if mutation.path[:1] == ("queues",)
            )
            if queue_mutations:
                if event.event_type != "unit.limbo_wait_heal":
                    raise ValueError("limbo_queue_rescue_stage_not_admitted")
                rescue_entries = tuple(
                    entry
                    for entries in result.after_state.queues.values()
                    if isinstance(entries, (list, tuple))
                    for entry in entries
                    if isinstance(entry, dict)
                    and str(entry.get("actor_id") or "") == plan.unit_id
                    and str(entry.get("owner_alive_state") or "") == "alive_or_limbo"
                )
                if not rescue_entries:
                    raise ValueError("limbo_queue_rescue_entry_missing")
                for entry in rescue_entries:
                    resolution = self.rules.queue_resolution_for_intent(
                        str(entry.get("queue_intent_id") or "")
                    )
                    if (
                        resolution is None
                        or resolution.coverage_status != "executable"
                        or resolution.resolved_kind != "standalone_ability_graph"
                    ):
                        raise ValueError("limbo_queue_rescue_not_connected")
                return result
            current = lifecycle.pending_defeat(result.after_state, plan.unit_id)
            if current is None:
                unit = result.after_state.units[plan.unit_id]
                if unit.lifecycle_status == "active" and unit.hp > 0:
                    return result
                raise ValueError("pending_defeat_window_closed_without_resolution")
            if current != plan:
                raise ValueError("pending_defeat_window_identity_mismatch")
            stage = stages.index(event.event_type)
            if stage + 1 < len(stages):
                emitted = (lifecycle.limbo_events(plan)[stage + 1],)
            else:
                mutations = lifecycle.finalize_pending_defeat_mutations(result.after_state, plan)
                terminal = replace(plan.terminal_event,
                    event_id=mutation_backed_event_id(mutations[0].stable_id(), "unit.defeated"),
                    payload={**plan.terminal_event.payload, "lifecycle_mutation_id": mutations[0].stable_id(),
                             "pending_defeat_id": plan.pending_id, "param_entity_id": plan.unit_id})
                energy, energy_events, energy_records = self.damage.kill_energy_artifacts(
                    result.after_state, plan, terminal)
                reduction = self.reducer.apply_all_result(result.after_state, (*mutations, *energy))
                if not reduction.ok:
                    raise ValueError("pending_defeat_finalization_mutation_failed")
                result = replace(result, after_state=reduction.after_state,
                    mutations=(*result.mutations, *mutations, *energy),
                    records=(*result.records, *lifecycle_settlement_records(mutations), *energy_records))
                emitted = (terminal, *energy_events)
            for child in emitted:
                child = replace(child, event_id=str(child.to_json()["event_id"]))
                dispatched = self._dispatch_event(result.after_state, event=child,
                    damage_window_ledger=damage_window_ledger,
                    task_graph_continuation=task_graph_continuation, nested_ability_hooks=nested_ability_hooks,
                    status_nested_ability_provider=status_nested_ability_provider)
                if dispatched.errors:
                    # A failed child rolls the whole window back; its partial
                    # projections must not be merged into the failure result.
                    return _atomic_dispatch_failure(before, replace(
                        result, errors=(*result.errors, *dispatched.errors),
                        task_graph_projections=(), damage_modifiers=(),
                    ))
                result = replace(result, after_state=dispatched.after_state,
                    mutations=(*result.mutations, *dispatched.mutations),
                    events=(*result.events, *dispatched.events),
                    rng_events=(*result.rng_events, *dispatched.rng_events),
                    records=(*result.records, *dispatched.records),
                    trigger_windows=(*result.trigger_windows, *dispatched.trigger_windows),
                    listener_records=(*result.listener_records, *dispatched.listener_records),
                    errors=(*result.errors, *dispatched.errors),
                    node_results=(*result.node_results, *dispatched.node_results),
                    event_normalizations=(*result.event_normalizations, *dispatched.event_normalizations),
                    task_graph_projections=(*result.task_graph_projections, *dispatched.task_graph_projections),
                    dispatched_event_ids=result.dispatched_event_ids | dispatched.dispatched_event_ids)
                if result.errors:
                    return _atomic_dispatch_failure(before, result)
                if damage_window_ledger is not None:
                    damage_window_ledger.record_defeat_event(child)
            return result
        except ValueError as exc:
            return _atomic_dispatch_failure(before, replace(
                result, errors=(*result.errors, str(exc)),
                task_graph_projections=(), damage_modifiers=(),
            ))

    def _remove_exhausted_shield_owners(
        self,
        result: EventDispatchResult,
        event: GameEvent,
    ) -> EventDispatchResult:
        fact = event.shield_exhaustion_fact
        target_id = str(event.target_id or "")
        if (
            type(fact) is not ShieldExhaustionFact
            or fact.event_id != event.event_id
            or fact.mutation.path != ("units", target_id, "shield_instances")
            or fact.mutation.stable_id() != event.payload.get("mutation_id")
            or {owner.instance_id for owner in fact.owners}
            != set(event.payload.get("exhausted_instance_ids") or ())
            or target_id not in result.after_state.units
        ):
            return _atomic_dispatch_failure(
                result.after_state,
                replace(result, errors=("shield_exhaustion_typed_fact_missing_or_mismatch",), damage_modifiers=()),
            )
        current = result.after_state
        mutations = list(result.mutations)
        events = list(result.events)
        records = list(result.records)
        rng_events = list(result.rng_events)
        nodes = list(result.node_results)
        normalizations = list(result.event_normalizations)
        projections = list(result.task_graph_projections)
        dispatched_ids = set(result.dispatched_event_ids)
        removed_owners: set[tuple[str, str, str]] = set()
        for owner in fact.owners:
            if owner.instance_id in {
                str(item.get("instance_id") or "")
                for item in current.units[target_id].shield_instances
            }:
                return _atomic_dispatch_failure(
                    result.after_state,
                    replace(result, errors=("shield_exhausted_instance_still_present",), damage_modifiers=()),
                )
            if not owner.modifier_name and not owner.status_instance_id:
                continue
            if not owner.modifier_name or not owner.status_instance_id:
                return _atomic_dispatch_failure(
                    result.after_state,
                    replace(result, errors=("shield_exhausted_owner_identity_incomplete",), damage_modifiers=()),
                )
            owner_key = (owner.modifier_name, owner.status_instance_id, owner.caster_id)
            if owner_key in removed_owners:
                continue
            removed_owners.add(owner_key)
            removal = StatusSystem(self.rules).remove_exhausted_shield_owner(
                current,
                target_id=target_id,
                modifier_name=owner.modifier_name,
                status_instance_id=owner.status_instance_id,
                caster_id=owner.caster_id,
                exhaustion_fact=fact,
            )
            if not removal.ok:
                return _atomic_dispatch_failure(
                    result.after_state,
                    replace(result, errors=removal.unsupported or ("shield_owner_status_remove_failed",), damage_modifiers=()),
                )
            reduction = self.reducer.apply_all_result(current, removal.mutations)
            if not reduction.ok:
                return _atomic_dispatch_failure(
                    result.after_state,
                    replace(result, errors=("shield_owner_status_mutation_conflict",), damage_modifiers=()),
                )
            current = reduction.after_state
            mutations.extend(removal.mutations)
            records.extend(removal.records)
            for lifecycle_event in removal.events:
                dispatched = self.dispatch_event(current, event=lifecycle_event)
                if dispatched.errors:
                    return _atomic_dispatch_failure(
                        result.after_state,
                        replace(result, errors=dispatched.errors, damage_modifiers=()),
                    )
                current = dispatched.after_state
                mutations.extend(dispatched.mutations)
                events.extend(dispatched.events)
                records.extend(dispatched.records)
                rng_events.extend(dispatched.rng_events)
                nodes.extend(dispatched.node_results)
                normalizations.extend(dispatched.event_normalizations)
                projections.extend(dispatched.task_graph_projections)
                dispatched_ids.update(dispatched.dispatched_event_ids)
        return replace(
            result,
            after_state=current,
            mutations=tuple(mutations),
            events=tuple(events),
            records=tuple(records),
            rng_events=tuple(rng_events),
            node_results=tuple(nodes),
            event_normalizations=tuple(normalizations),
            task_graph_projections=tuple(projections),
            dispatched_event_ids=frozenset(dispatched_ids),
        )

    def _reconcile_ability_property_watchers(
        self,
        result: EventDispatchResult,
        *,
        before_state: BattleState,
        event: GameEvent,
        damage_window_ledger: DamageWindowLedger | None,
        task_graph_continuation: TaskGraphContinuation | None,
        nested_ability_hooks: TaskGraphExecutionHooks | None,
    ) -> EventDispatchResult:
        if result.errors:
            return _atomic_dispatch_failure(before_state, result)
        if event.event_type == "dynamic.value.changed":
            from .dynamic_values import DynamicValueChangeFact
            fact = event.dynamic_value_change_fact
            if type(fact) is not DynamicValueChangeFact or not fact.matches_event(event):
                return self.dispatch_blocked(before_state, event=event,
                    listener_kind="dynamic_value_watcher", scope="global_listener",
                    reason="dynamic_value_change_fact_missing_or_mismatched")
            before_state = fact.before_state
        unit_ids = _ability_property_recheck_unit_ids(
            result.after_state,
            event,
            result.mutations,
        )
        if not unit_ids:
            return result
        watcher_result = self.ability_property_watchers.reconcile(
            result.after_state,
            unit_ids=unit_ids,
            trigger_event=event,
            task_graph_continuation=task_graph_continuation,
            nested_ability_hooks=nested_ability_hooks,
            before_state=before_state,
        )
        if not watcher_result.ok:
            return _atomic_dispatch_failure(
                before_state,
                replace(
                    result,
                    records=(*result.records, *watcher_result.records),
                    errors=(*result.errors, *watcher_result.errors),
                    damage_modifiers=(),
                    node_results=(
                        *result.node_results,
                        *watcher_result.node_results,
                    ),
                    task_graph_projections=(),
                ),
            )

        current_state = watcher_result.after_state
        mutations = [*result.mutations, *watcher_result.mutations]
        events = [*result.events, *watcher_result.events]
        rng_events = [*result.rng_events, *watcher_result.rng_events]
        records = [*result.records, *watcher_result.records]
        errors = [*result.errors]
        nodes = [*result.node_results, *watcher_result.node_results]
        normalizations = [*result.event_normalizations]
        projections = [
            *result.task_graph_projections,
            *watcher_result.task_graph_projections,
        ]
        dispatched_event_ids = set(result.dispatched_event_ids | watcher_result.dispatched_event_ids)
        child_depth = _event_mutation_depth(event)
        dispatchable_events = tuple(
            emitted_event
            for emitted_event in watcher_result.events
            if emitted_event.event_type in CALLBACK_EMITTED_EVENT_TYPES
            and str(emitted_event.to_json()["event_id"]) not in dispatched_event_ids
        )
        if (
            dispatchable_events
            and child_depth >= MAX_CALLBACK_EMITTED_EVENT_DEPTH
        ):
            errors.append("callback_emitted_event_depth_exceeded")
        else:
            # Recursive dispatch returns each emitted event as its input event.
            events = [
                *result.events,
                *(emitted for emitted in watcher_result.events
                  if emitted.event_type not in CALLBACK_EMITTED_EVENT_TYPES
                  or str(emitted.to_json()["event_id"]) in dispatched_event_ids),
            ]
            for emitted_event in dispatchable_events:
                if str(emitted_event.to_json()["event_id"]) in dispatched_event_ids:
                    continue
                child_event = emitted_event
                if "mutation_event_depth" not in emitted_event.payload:
                    child_event = replace(
                        emitted_event,
                        event_id=(
                            emitted_event.event_id
                            or str(emitted_event.to_json().get("event_id") or "")
                        ),
                        payload={
                            **emitted_event.payload,
                            "mutation_event_depth": child_depth + 1,
                        },
                    )
                    normalizations.append(
                        EventNormalization(
                            before=emitted_event,
                            after=child_event,
                            kind="mutation_event_depth",
                        )
                    )
                if child_event.event_type == "status.lifecycle" and event.break_notification_fact is not None:
                    child_event = replace(child_event, break_notification_fact=event.break_notification_fact)
                child_result = self.dispatch_event(
                    current_state,
                    event=child_event,
                    damage_window_ledger=damage_window_ledger,
                    task_graph_continuation=task_graph_continuation,
                    nested_ability_hooks=nested_ability_hooks,
                )
                current_state = child_result.after_state
                mutations.extend(child_result.mutations)
                events.extend(child_result.events)
                rng_events.extend(child_result.rng_events)
                records.extend(child_result.records)
                errors.extend(child_result.errors)
                nodes.extend(child_result.node_results)
                normalizations.extend(child_result.event_normalizations)
                projections.extend(child_result.task_graph_projections)
                dispatched_event_ids.update(child_result.dispatched_event_ids)
        merged = replace(
            result,
            after_state=current_state,
            mutations=tuple(mutations),
            events=tuple(events),
            rng_events=tuple(rng_events),
            records=tuple(records),
            errors=tuple(errors),
            node_results=tuple(nodes),
            event_normalizations=tuple(normalizations),
            dispatched_event_ids=frozenset(dispatched_event_ids),
            task_graph_projections=(() if errors else tuple(projections)),
            damage_modifiers=() if errors else result.damage_modifiers,
        )
        return (
            _atomic_dispatch_failure(before_state, merged)
            if errors
            else merged
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
            node_results=_trigger_window_node_results(event, result.trigger_windows),
        )

    def dispatch_status_callback(
        self,
        state: BattleState,
        *,
        event: GameEvent,
        unit_id: str,
        modifier_name: str,
        damage_window_ledger: DamageWindowLedger | None = None,
        task_graph_continuation: TaskGraphContinuation | None = None,
        nested_ability_hooks: TaskGraphExecutionHooks | None = None,
    ) -> EventDispatchResult:
        return self.dispatch_event(
            state,
            event=event,
            unit_id=unit_id,
            modifier_name=modifier_name,
            damage_window_ledger=damage_window_ledger,
            task_graph_continuation=task_graph_continuation,
            nested_ability_hooks=nested_ability_hooks,
        )

    def _dispatch_listener_event(
        self,
        state: BattleState,
        *,
        event: GameEvent,
        unit_id: str | None,
        modifier_name: str | None,
        damage_window_ledger: DamageWindowLedger | None,
        task_graph_continuation: TaskGraphContinuation | None,
        nested_ability_hooks: TaskGraphExecutionHooks | None,
        status_nested_ability_provider: StatusNestedAbilityHookProvider | None,
        expected_window_scope: ActionWindowExpectedScope | None,
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
        if _dispatch_only_without_listener(event, aliases):
            listener_record = _listener_record(
                event,
                listener_kind="lifecycle_event_dispatch",
                listener_id="",
                source="event_dispatch_system",
                status="processed",
                reason="no_admitted_listener_for_lifecycle_event",
                metadata={
                    "event_scope_kind": dispatch_scope,
                    "event_aliases": [alias.to_json() for alias in aliases],
                },
            )
            return EventDispatchResult(
                after_state=state,
                events=(event,),
                records=(dispatch_record, listener_record),
                listener_records=(listener_record,),
            )
        matches = self._resolve_listener_matches(
            state,
            event=event,
            aliases=aliases,
            unit_id=unit_id,
            modifier_name=modifier_name,
        )
        if event.event_type == "status.immunity" and not any(
            match.status == "matched" and match.callback_event == "OnImmuneDebuff" for match in matches
        ):
            return self.dispatch_blocked(state, event=event, listener_kind="status_immunity_dispatch",
                scope="owner_local", reason=next((match.reason for match in matches if match.status == "blocked"),
                                                 "status_immunity_callback_not_admitted"))
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
        node_results: list[ExecutionNodeResult] = []
        event_normalizations: list[EventNormalization] = []
        task_graph_projections: list[TaskGraphNodeProjection] = []
        damage_modifiers: list[DamageModifierContribution] = []
        dispatched_event_ids: set[str] = set()
        # A synchronous listener may remove a status whose remaining add
        # lifecycle notifications are still queued in this same batch. Track
        # the instances retired here so those notifications keep their
        # produced fact instead of looking like forged events.
        removed_lifecycle_instances: set[str] = set()
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
                if match.status == "blocked" and match.reason:
                    errors.append(match.reason)
                continue
            listener_event = event
            if match.callback_event == "OnListenBeforeHitAll":
                if event.event_type != "damage.hit_sequence.before" or event.source_id not in current_state.units:
                    errors.append("before_hit_all_listener_attacker_missing")
                    continue
                # Global listeners receive the actual attacker. Actor-local
                # OnBeforeHitAll retains the current victim as its ParamEntity.
                listener_event = replace(event, payload={**event.payload, "param_entity_id": event.source_id})
            formal_action_window_callback = (
                status_nested_ability_provider is not None
                and match.callback is not None
                and match.callback.source_mode
                in {
                    "mainline_avatar_ability",
                    "mainline_servant_ability",
                    "mainline_stage_ability",
                }
            )
            if status_nested_ability_provider is not None and match.callback is None:
                errors.append("action_window_formal_root_callback_missing")
                continue
            if formal_action_window_callback:
                result = self.status_callbacks.execute_action_window_formal_root(
                    current_state,
                    callback_id=match.callback.callback_id,
                    unit_id=match.unit_id,
                    modifier_name=match.modifier_name,
                    event=match.callback_event,
                    trigger_event=listener_event,
                    damage_window_ledger=damage_window_ledger,
                    detail_override=match.status_detail,
                    nested_ability_provider=status_nested_ability_provider,
                    expected_window_scope=expected_window_scope,
                )
            elif (task_graph_continuation is None and nested_ability_hooks is None
                    and not event.event_type.startswith("action.window.")
                    and match.callback is not None
                    and match.callback.source_mode in {"mainline_avatar_ability", "mainline_servant_ability", "mainline_stage_ability"}
                    and self.rules.status_event_family(match.callback_event) is not None
                    and any(task.opcode == "TriggerAbility"
                            for task in self.rules.status_callback_tasks_for_callback(match.callback.callback_id))):
                if getattr(self, "_registered_event_nested_provider", None) is None:
                    from .ability import AbilityTaskSystem

                    self._registered_event_nested_provider = AbilityTaskSystem(
                        self.rules, self.status_callbacks.effect_registry, reducer=self.reducer,
                        damage=self.damage, event_dispatcher=self,
                    ).formal_status_nested_ability_provider()
                result = self.status_callbacks.execute_registered_event_formal_root(
                    current_state, callback_id=match.callback.callback_id, unit_id=match.unit_id,
                    modifier_name=match.modifier_name, event=match.callback_event, trigger_event=listener_event,
                    damage_window_ledger=damage_window_ledger, detail_override=match.status_detail,
                    nested_ability_provider=self._registered_event_nested_provider,
                )
            else:
                result = self.status_callbacks.execute(
                    current_state,
                    unit_id=match.unit_id,
                    modifier_name=match.modifier_name,
                    event=match.callback_event,
                    trigger_event=listener_event,
                    damage_window_ledger=damage_window_ledger,
                    detail_override=match.status_detail,
                    task_graph_continuation=task_graph_continuation,
                    nested_ability_hooks=nested_ability_hooks,
                )
            current_state = result.after_state
            for produced_event in result.events:
                removed_instance = _lifecycle_removed_instance(produced_event)
                if removed_instance:
                    removed_lifecycle_instances.add(removed_instance)
            mutations.extend(result.mutations)
            rng_events.extend(result.rng_events)
            records.extend(result.records)
            errors.extend(result.errors)
            node_results.extend(result.node_results)
            task_graph_projections.extend(result.task_graph_projections)
            damage_modifiers.extend(result.damage_modifiers)
            dispatched_event_ids.update(result.dispatched_event_ids)
            child_depth = _event_mutation_depth(event)
            dispatchable_events = tuple(
                emitted_event
                for emitted_event in result.events
                if emitted_event.event_type in CALLBACK_EMITTED_EVENT_TYPES
                and str(emitted_event.to_json()["event_id"]) not in dispatched_event_ids
            )
            if (
                dispatchable_events
                and child_depth >= MAX_CALLBACK_EMITTED_EVENT_DEPTH
            ):
                events.extend(result.events)
                errors.append("callback_emitted_event_depth_exceeded")
            else:
                # Child dispatch includes its input event in child_result.events.
                events.extend(
                    emitted for emitted in result.events
                    if emitted.event_type not in CALLBACK_EMITTED_EVENT_TYPES
                    or str(emitted.to_json()["event_id"]) in dispatched_event_ids
                )
                for emitted_event in dispatchable_events:
                    if str(emitted_event.to_json()["event_id"]) in dispatched_event_ids:
                        continue
                    child_event = emitted_event
                    if (
                        "mutation_event_depth"
                        not in emitted_event.payload
                    ):
                        child_event = replace(
                            emitted_event,
                            event_id=(
                                emitted_event.event_id
                                or str(
                                    emitted_event.to_json().get(
                                        "event_id"
                                    )
                                    or ""
                                )
                            ),
                            payload={
                                **emitted_event.payload,
                                "mutation_event_depth": (
                                    child_depth + 1
                                ),
                            },
                        )
                        event_normalizations.append(
                            EventNormalization(
                                before=emitted_event,
                                after=child_event,
                                kind="mutation_event_depth",
                            )
                        )
                    if child_event.event_type == "status.lifecycle" and event.break_notification_fact is not None:
                        child_event = replace(child_event, break_notification_fact=event.break_notification_fact)
                    produced_fact = child_event.status_lifecycle_fact
                    if (
                        produced_fact is not None
                        and produced_fact.status_instance_id in removed_lifecycle_instances
                    ):
                        child_event = replace(child_event, lifecycle_instance_gone=True)
                    child_result = self.dispatch_event(
                        current_state,
                        event=child_event,
                        damage_window_ledger=damage_window_ledger,
                        task_graph_continuation=task_graph_continuation,
                        nested_ability_hooks=nested_ability_hooks,
                    )
                    for dispatched_event in child_result.events:
                        removed_instance = _lifecycle_removed_instance(dispatched_event)
                        if removed_instance:
                            removed_lifecycle_instances.add(removed_instance)
                    current_state = child_result.after_state
                    mutations.extend(child_result.mutations)
                    rng_events.extend(child_result.rng_events)
                    records.extend(child_result.records)
                    events.extend(child_result.events)
                    errors.extend(child_result.errors)
                    node_results.extend(child_result.node_results)
                    event_normalizations.extend(
                        child_result.event_normalizations
                    )
                    task_graph_projections.extend(
                        child_result.task_graph_projections
                    )
                    dispatched_event_ids.update(child_result.dispatched_event_ids)
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
        result = EventDispatchResult(
            after_state=current_state,
            mutations=tuple(mutations),
            events=tuple(events),
            rng_events=tuple(rng_events),
            records=tuple(records),
            trigger_windows=(),
            listener_records=tuple(listener_records),
            errors=tuple(errors),
            node_results=tuple(node_results),
            event_normalizations=tuple(event_normalizations),
            task_graph_projections=(
                () if errors else tuple(task_graph_projections)
            ),
            dispatched_event_ids=frozenset(dispatched_event_ids),
            damage_modifiers=() if errors else tuple(damage_modifiers),
        )
        return _atomic_dispatch_failure(state, result) if errors else result

    def _resolve_listener_matches(
        self,
        state: BattleState,
        *,
        event: GameEvent,
        aliases: tuple[EventAlias, ...],
        unit_id: str | None,
        modifier_name: str | None,
    ) -> tuple[ListenerMatch, ...]:
        aliases = tuple(
            alias
            for alias in aliases
            if not _optional_missing_mutation_alias(event, alias)
            and not _non_gameplay_alias(self.rules, alias)
        )
        if not aliases:
            return ()
        if unit_id and modifier_name:
            matches = list(
                self._explicit_status_matches(
                    state,
                    event,
                    aliases,
                    unit_id,
                    modifier_name,
                )
            )
        else:
            matches = []
            detached_detail = _detached_status_detail(event)
            for alias in aliases:
                if not alias.callback_event or alias.admission_status != "executable":
                    matches.append(_alias_blocked_match(event, alias, state))
                    continue
                for callback in self.rules.status_callbacks_for_event_scope(
                    alias.callback_event,
                    alias.scope_kind,
                ):
                    details = _status_details_for_modifier(
                        state,
                        callback.modifier_name,
                    )
                    if (
                        detached_detail is not None
                        and callback.modifier_name
                        == str(detached_detail.get("modifier_name") or "")
                    ):
                        details = (*details, detached_detail)
                    for detail in details:
                        match = _match_callback_to_event(
                            event,
                            callback,
                            detail,
                            explicit=False,
                            alias=alias,
                            state=state,
                        )
                        if match is not None:
                            matches.append(match)
        fact = event.hit_window_invocation_fact
        if (event.event_type in {'damage.target_attack.after', 'damage.target_hit_sequence.after'}
                and type(fact) is HitWindowInvocationFact and fact.matches(event)
                and fact.target_status_instance_ids is not None):
            # The damage producer captured listeners at the first admitted hit.
            # Debuffs applied after damage cannot react to that earlier attack.
            matches = [replace(match, status='skipped', reason='status_not_present_at_attack_start')
                       if match.unit_id == event.target_id and match.status_instance_id
                       and match.status_instance_id not in fact.target_status_instance_ids else match for match in matches]
        # L2 can replace an exact callback on its own card; all unrelated
        # listeners and the subsequent content-event dispatch stay unchanged.
        for index, match in enumerate(matches):
            unit = state.units.get(match.unit_id)
            detail = next((d for d in unit.flags.get("status_details", ())
                           if d.get("instance_id") == match.status_instance_id), {}) if unit else {}
            if match.status == "matched" and processor_replaces_status_callback(
                self.rules, state, detail, match.callback_event
            ):
                matches[index] = replace(match, status="skipped", reason="content_processor_replaces_callback")
        pre_mutation_reason = _pre_mutation_listener_block_reason(event)
        if pre_mutation_reason:
            matches = [
                replace(
                    match,
                    status="blocked",
                    reason=pre_mutation_reason,
                    source="mutation_backed_event_safety",
                    blocked_category=_blocked_category(pre_mutation_reason),
                )
                if match.status == "matched"
                else match
                for match in matches
            ]
        return tuple(sorted(matches, key=_match_sort_key))

    def _explicit_status_matches(
        self,
        state: BattleState,
        event: GameEvent,
        aliases: tuple[EventAlias, ...],
        unit_id: str,
        modifier_name: str,
    ) -> tuple[ListenerMatch, ...]:
        fact = event.status_immunity_fact if event.event_type == "status.immunity" else None
        detail = _status_detail_for_unit_modifier(state, unit_id, modifier_name,
            status_instance_id=fact.protection_instance_id if type(fact) is StatusImmunityFact else "")
        if detail is None:
            detached = _detached_status_detail(event)
            if (
                detached is not None
                and str(detached.get("owner_id") or "") == unit_id
                and str(detached.get("modifier_name") or "") == modifier_name
            ):
                detail = detached
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
                "callback_execution_order": [],
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
            node_results=(
                ExecutionNodeResult(
                    node_kind="event_dispatch",
                    node_id=event.event_id or event.event_type,
                    status="blocked",
                    reason_code=reason,
                ),
            ),
        )


def _with_event_dispatch_node_result(
    result: EventDispatchResult,
    event: GameEvent,
) -> EventDispatchResult:
    nodes = list(result.node_results)
    if result.errors:
        nodes.append(
            ExecutionNodeResult(
                node_kind="event_dispatch",
                node_id=event.event_id or event.event_type,
                status="blocked",
                reason_code=",".join(result.errors),
            )
        )
    elif not nodes:
        nodes.append(
            ExecutionNodeResult(
                node_kind="event_dispatch",
                node_id=event.event_id or event.event_type,
                status="complete",
            )
        )
    return replace(result, node_results=tuple(nodes), dispatched_event_ids=(
        result.dispatched_event_ids | {str(event.to_json()["event_id"])}
    ))


def _with_controlled_event_normalization(
    result: EventDispatchResult,
    *,
    before: GameEvent,
    after: GameEvent,
) -> EventDispatchResult:
    if before.to_json() == after.to_json():
        return result
    return replace(
        result,
        event_normalizations=(
            EventNormalization(
                before=before,
                after=after,
                kind="typed_param_entity",
            ),
            *result.event_normalizations,
        ),
    )


def _atomic_dispatch_failure(
    before_state: BattleState,
    result: EventDispatchResult,
) -> EventDispatchResult:
    return replace(
        result,
        after_state=before_state,
        mutations=(),
        events=(),
        rng_events=(),
        records=tuple(
            record
            for record in result.records
            if record.get("process_only") is True
        ),
        trigger_windows=(),
        task_graph_projections=(),
        damage_modifiers=(),
        dispatched_event_ids=frozenset(),
    )


def _task_graph_transport_reason(
    continuation: object,
    hooks: object,
) -> str:
    if continuation is not None and type(continuation) is not TaskGraphContinuation:
        return "task_graph_event_continuation_type_invalid"
    if hooks is not None and type(hooks) is not TaskGraphExecutionHooks:
        return "task_graph_event_hooks_type_invalid"
    if hooks is not None and continuation is None:
        return "task_graph_event_hooks_without_continuation"
    return ""


def _trigger_window_node_results(
    event: GameEvent,
    trigger_windows: tuple[dict[str, JSONValue], ...],
) -> tuple[ExecutionNodeResult, ...]:
    if not trigger_windows:
        return (
            ExecutionNodeResult(
                node_kind="trigger_window",
                node_id=event.event_id or event.event_type,
                status="complete",
            ),
        )
    results: list[ExecutionNodeResult] = []
    for index, window in enumerate(trigger_windows):
        reason = str(window.get("blocked_reason") or "")
        results.append(
            ExecutionNodeResult(
                node_kind="trigger_window",
                node_id=str(window.get("trigger_id") or f"{event.event_id or event.event_type}:{index}"),
                status="blocked" if reason else "complete",
                reason_code=reason,
            )
        )
    return tuple(results)


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
    "summoner_relation_local": 65,
    "global_listener": 90,
}


CANONICAL_EVENT_ALIASES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "summon.retiring": (("OnDeathrattle", "being_hit_target_local", ""),),
    # These callbacks are produced by StatusSystem._status_lifecycle_events.
    # A scoped source slice may contain no listener for one of them; existing
    # source families still take precedence over this producer-side mapping.
    "status.lifecycle": (
        ("OnCreate", "status_local", ""),
        ("OnStack", "status_local", ""),
        ("OnModifierAdd", "status_local", ""),
        ("OnAddModifierSuc", "status_local", ""),
        ("OnListenModifierAdd", "global_listener", ""),
        ("OnModifierDotAdd", "status_local", ""),
        ("OnModifierOnStack", "status_local", ""),
        ("OnListenModifierOnStack", "global_listener", ""),
        ("OnDestroy", "status_local", ""),
        ("OnModifierRemove", "status_local", ""),
        ("OnListenModifierRemove", "global_listener", ""),
    ),
    "battle.start": (
        ("OnEnterBattle", "owner_local", ""),
    ),
    "turn.begin": (
        ("OnListenAllowAction", "owner_local", ""),
        ("OnListenTurnBegin", "global_listener", ""),
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
        ("OnListenAfterSkillUse", "global_listener", ""),
    ),
    "action.after_attack": (
        ("OnListenAfterAttack", "global_listener", ""),
    ),
    "action.attack_end": (
        ("OnAfterAttackEnd", "actor_local", ""),
    ),
    "action.end": (
        ("OnActionEnd", "actor_local", ""),
    ),
    "queue.action.before": (
        ("OnBeforeInsertActionPrepare", "actor_local", ""),
        ("OnInsertActionStart", "actor_local", ""),
        ("OnListenInsertAbilityStart", "global_listener", ""),
    ),
    "queue.action.after": (
        ("OnInsertActionFinish", "actor_local", ""),
        ("OnListenInsertAbilityFinish", "global_listener", ""),
    ),
    "queue.action.abort": (
        ("OnListenInsertAbilityAbort", "global_listener", ""),
    ),
    "unit.defeated": (
        ("OnTriggerDeath", "owner_local", ""),
        ("OnListenCharacterDie", "owner_local", ""),
        ("OnTriggerDeathrattle", "owner_local", ""),
    ),
    "battle_event.created": (
        ("OnListenBattleEventCreate", "global_listener", ""),
    ),
    "unit.created": (
        ("OnListenCharacterCreate", "global_listener", ""),
    ),
    "summon.spawned": (
        ("OnListenCharacterCreate", "global_listener", ""),
    ),
    "unit.departed.started": (
        ("OnListenDepartedStart", "global_listener", ""),
    ),
    "unit.departed.ended": (
        ("OnListenDepartedEnd", "global_listener", ""),
    ),
    "unit.before_dying": (
        ("OnBeforeDying", "owner_local", ""),
    ),
    "unit.before_mortally_wounded": (
        ("OnBeforeMortallyWonded", "owner_local", ""),
    ),
    "unit.hp_overflow": (
        ("OnHPOverflow", "being_hit_target_local", ""),
    ),
    "unit.being_limbo": (("OnBeingLimbo", "being_hit_target_local", ""),),
    "unit.limbo_wait_heal": (("OnLimboWaitHeal", "being_hit_target_local", ""),),
    "damage.hit": (
        ("OnHit", "per_hit_target_local", ""),
        ("OnBeingHit", "being_hit_target_local", ""),
    ),
    "energy.change": (
        ("OnSPChange", "being_hit_target_local", ""),
    ),
    "damage.attacker_hit": (
        ("OnAfterHit", "actor_local", ""),
    ),
    "damage.before_hit": (
        ("OnBeforeHit", "actor_local", ""),
    ),
    "damage.hit_sequence.before": (
        ("OnBeforeHitAll", "actor_local", ""),
    ),
    "damage.hit_sequence.after": (
        ("OnAfterHitAll", "actor_local", ""),
    ),
    "damage.target_attack.before": (
        ("OnBeforeBeingAttacked", "being_hit_target_local", ""),
    ),
    "damage.target_attack.after": (
        ("OnAfterBeingAttacked", "being_hit_target_local", ""),
    ),
    "damage.target_hit_sequence.before": (
        ("OnBeforeBeingHitAll", "being_hit_target_local", ""),
    ),
    "damage.target_hit_sequence.after": (
        ("OnAfterBeingHitAll", "being_hit_target_local", ""),
    ),
    "toughness.hit": (
        ("OnBeingStanceDamage", "being_hit_target_local", ""),
        ("OnHit", "per_hit_target_local", ""),
    ),
    "break.entered": (
        ("OnBeingBreak", "being_hit_target_local", ""),
    ),
    "toughness.segment_depleted": (
        ("OnBeingStanceCountDown", "being_hit_target_local", ""),
        ("OnTriggerStanceCountDown", "actor_local", ""),
    ),
    "break.triggered": (
        ("OnTriggerBreak", "actor_local", ""),
        ("OnListenBreak", "global_listener", ""),
    ),
    "status.callback": (
        ("OnPhase1", "status_local", "event_alias_missing:status_callback_requires_explicit_callback_event"),
        ("OnCreate", "status_local", "event_alias_missing:on_create_requires_status_create_event"),
        ("OnDestroy", "status_local", "event_alias_missing:on_destroy_requires_status_destroy_event"),
    ),
    "custom.event": (
        ("OnCustomEvent", "owner_local", ""),
    ),
    "wave.monster": (
        ("OnWaveMonster", "global_listener", ""),
    ),
}


CALLBACK_EMITTED_EVENT_TYPES = MUTATION_BACKED_EVENT_TYPES | {
    "dynamic.value.changed",
    "unit.before_dying",
    "unit.hp_overflow",
    "unit.defeated",
    "custom.event",
    "status.lifecycle",
    "summon.spawned",
    "summon.removed",
    "summon.retiring",
}
MAX_CALLBACK_EMITTED_EVENT_DEPTH = 16

LIFECYCLE_DISPATCH_ONLY_EVENT_TYPES = {
    "wave.started",
    "wave.cleared",
    "battle.victory",
    "battle.defeat",
    "battle.completed",
}


def _dispatch_only_without_listener(event: GameEvent, aliases: tuple[EventAlias, ...]) -> bool:
    if event.event_type == "dynamic.value.changed":
        return True
    if (
        event.event_type not in LIFECYCLE_DISPATCH_ONLY_EVENT_TYPES
        and event.event_type not in MUTATION_BACKED_EVENT_TYPES
    ):
        return False
    return not any(alias.callback_event and alias.admission_status == "executable" for alias in aliases)


def _lifecycle_event_payload_block_reason(
    state: BattleState,
    event: GameEvent,
) -> str:
    payload = event.payload
    if event.event_type == "unit.hp_overflow":
        from .mutation_events import HPOverflowFact
        fact = event.hp_overflow_fact
        if type(fact) is not HPOverflowFact or not fact.matches_event(event):
            return "hp_overflow_fact_missing_or_mismatched"
    if event.event_type in {item[0] for item in LIMBO_CALLBACKS}:
        plan = event.pending_defeat_plan
        if type(plan) is not PendingDefeatPlan:
            return "limbo_event_native_plan_missing"
        try:
            lifecycle = UnitLifecycleSystem()
            if lifecycle.pending_defeat(state, plan.unit_id) != plan:
                return "limbo_event_pending_cause_mismatch"
            expected = next(item for item in lifecycle.limbo_events(plan) if item.event_type == event.event_type)
            if "mutation_event_depth" in payload:
                depth = payload["mutation_event_depth"]
                if type(depth) is not int or not 0 <= depth <= MAX_CALLBACK_EMITTED_EVENT_DEPTH:
                    return "limbo_event_dispatch_depth_invalid"
                expected = replace(expected, payload={**expected.payload, "mutation_event_depth": depth})
            if expected.to_json() != event.to_json():
                return "limbo_event_native_context_mismatch"
        except ValueError as exc:
            return str(exc)
    if event.event_type == "unit.defeated":
        if event.window != "unit.defeated":
            return "unit_defeated_window_invalid"
        target_id = str(event.target_id or "")
        identities = (
            target_id,
            payload.get("target_id"),
            payload.get("defeated_unit_id"),
        )
        if any(
            not isinstance(identity, str) or not identity
            for identity in identities
        ):
            return "unit_defeated_identity_missing"
        if any(identity != target_id for identity in identities[1:]):
            return "unit_defeated_identity_mismatch"
        if not isinstance(payload.get("lifecycle_mutation_id"), str) or not payload.get(
            "lifecycle_mutation_id"
        ):
            return "unit_defeated_lifecycle_mutation_missing"
        lifecycle_mutation_id = str(payload["lifecycle_mutation_id"])
        if not event.event_id:
            return "unit_defeated_event_identity_missing"
        if event.event_id != mutation_backed_event_id(
            lifecycle_mutation_id,
            event.event_type,
        ):
            return "unit_defeated_event_identity_mismatch"
        unit = state.units.get(target_id)
        if unit is None:
            return "unit_defeated_target_missing"
        if UnitLifecycleSystem().status_of(unit) != "defeated":
            return "unit_defeated_state_mismatch"
        defeat_record = unit.flags.get("defeat_record")
        if (
            not isinstance(defeat_record, dict)
            or defeat_record.get("lifecycle_mutation_id")
            != lifecycle_mutation_id
            or defeat_record.get("target_id") != target_id
            or defeat_record.get("defeated_unit_id") != target_id
        ):
            return "unit_defeated_lifecycle_mutation_uncommitted"
    if event.event_type == "status.lifecycle" and payload.get(
        "lifecycle_operation"
    ) in {"remove", "expire", "dispel", "stack_reduce_remove"}:
        detail = payload.get("status_detail")
        if not isinstance(detail, dict):
            return "status_lifecycle_removed_detail_missing"
        identities = (
            ("owner_id", event.target_id),
            ("modifier_name", payload.get("modifier_name")),
            ("instance_id", payload.get("status_instance_id")),
        )
        if any(
            not isinstance(expected, str)
            or not expected
            or detail.get(key) != expected
            for key, expected in identities
        ):
            return "status_lifecycle_removed_detail_identity_mismatch"
        if not isinstance(detail.get("source_trace"), dict):
            return "status_lifecycle_removed_detail_source_missing"
    required_by_type = {
        "wave.started": ("wave_definition_id", "stage_id", "wave_index", "unit_ids"),
        "wave.cleared": (
            "wave_definition_id",
            "stage_id",
            "wave_index",
            "cleared_unit_ids",
            "removed_unit_ids",
        ),
        "battle.victory": ("wave_transition_plan",),
        "battle.defeat": ("wave_transition_plan",),
        "battle.completed": ("outcome", "wave_definition_id", "stage_id", "wave_index"),
    }
    required = required_by_type.get(event.event_type)
    if required is None:
        return ""
    if any(key not in payload for key in required):
        return f"{event.event_type.replace('.', '_')}_payload_incomplete"
    if event.event_type == "wave.started":
        unit_ids = payload.get("unit_ids")
        if not isinstance(unit_ids, (list, tuple)) or not unit_ids:
            return "wave_started_unit_ids_missing"
    if event.event_type == "battle.completed" and payload.get("outcome") not in {"victory", "defeat"}:
        return "battle_completed_outcome_invalid"
    return ""


def _event_with_typed_param_entity(
    state: BattleState,
    event: GameEvent,
) -> tuple[GameEvent, str]:
    """Bind callback target resolution to one validated event entity identity."""

    if not event.event_id:
        event = replace(event, event_id=str(event.to_json()["event_id"]))
    payload = dict(event.payload)
    if event.event_type == "toughness.segment_depleted":
        fact = event.stance_count_down_fact
        if type(fact) is not StanceCountDownFact or not fact.matches(state, event):
            return event, "stance_count_down_fact_missing_or_mismatched"
        if payload.get("param_entity_id") not in (None, fact.target_id):
            return event, "stance_count_down_parameter_identity_mismatch"
        return replace(event, payload={**payload, "param_entity_id": fact.target_id}), ""
    if event.event_type == "queue.action.before":
        fact = event.queue_action_start_fact
        if type(fact) is not QueueActionStartFact or not fact.matches(state, event):
            return event, "queue_action_start_fact_missing_or_mismatched"
        return event, ""
    if event.event_type in {"queue.action.after", "queue.action.abort"}:
        fact = event.queue_action_terminal_fact
        if type(fact) is not QueueActionTerminalFact or not fact.matches(state, event):
            return event, "queue_action_terminal_fact_missing_or_mismatched"
        return event, ""
    raw_param_entity_id = payload.get("param_entity_id")
    callback_events = payload.get("callback_events")
    creation_event = (
        event.event_type in {
            "unit.created",
            "summon.spawned",
            "battle_event.created",
        }
        or (
            isinstance(callback_events, (list, tuple))
            and "OnListenCharacterCreate" in callback_events
        )
    )
    if creation_event:
        identities = (
            event.target_id,
            payload.get("unit_id"),
            raw_param_entity_id,
        )
        if any(not isinstance(identity, str) or not identity for identity in identities):
            return event, "event_param_entity_missing"
        typed_identity = str(identities[0])
        if any(identity != typed_identity for identity in identities[1:]):
            return event, "event_param_entity_identity_mismatch"
        if typed_identity not in state.units:
            return event, "event_param_entity_unit_missing"
        return replace(
            event,
            payload={**payload, "param_entity_id": typed_identity},
        ), ""

    if raw_param_entity_id is not None:
        if not isinstance(raw_param_entity_id, str) or not raw_param_entity_id:
            return event, "event_param_entity_invalid"
        if raw_param_entity_id not in state.units:
            return event, "event_param_entity_unit_missing"
        return event, ""

    if isinstance(event.target_id, str) and event.target_id in state.units:
        event_id = event.event_id or str(
            event.to_json().get("event_id") or ""
        )
        return replace(
            event,
            event_id=event_id,
            payload={**payload, "param_entity_id": event.target_id},
        ), ""
    return event, ""


def _battle_state_transition_event_block_reason(
    event: GameEvent,
    rules: RuleBook,
) -> str:
    if event.event_type not in {
        "elation.time.started",
        "elation.time.ended",
    }:
        return ""
    payload = event.payload
    metadata = payload.get("metadata")
    if (
        payload.get("mutation_backed_event") is not True
        or payload.get("mutation_path")
        != ["global_flags", "elation_time_active"]
        or payload.get("source") != "battle_state_transition_system"
        or not isinstance(metadata, dict)
    ):
        return "battle_state_transition_event_producer_evidence_missing"
    transition_rule_id = metadata.get("battle_state_transition_rule_id")
    if not isinstance(transition_rule_id, str) or not transition_rule_id:
        return "battle_state_transition_event_rule_identity_missing"
    rule = rules.battle_state_transition(transition_rule_id)
    candidates = rules.battle_state_transitions_for_runtime_event(
        event.event_type
    )
    if (
        rule is None
        or len(candidates) != 1
        or candidates[0].transition_rule_id != transition_rule_id
        or rule.coverage_status != "executable"
    ):
        return "battle_state_transition_event_rule_unresolved"
    expected_before = rule.before_value
    actual_before = payload.get("before")
    if (
        payload.get("after") != rule.after_value
        or type(payload.get("after")) is not type(rule.after_value)
        or (
            payload.get("before") is not None
            and (
                actual_before != expected_before
                or type(actual_before) is not type(expected_before)
            )
        )
        or event.window != rule.callback_event
        or payload.get("callback_events") != [rule.callback_event]
        or metadata.get("trigger_kind") != rule.trigger_kind
        or metadata.get("trigger_identity") != rule.trigger_identity
        or metadata.get("runtime_event_type") != rule.runtime_event_type
        or metadata.get("callback_event") != rule.callback_event
        or payload.get("source_trace") != rule.source.to_json()
        or metadata.get("source_trace") != rule.source.to_json()
    ):
        return "battle_state_transition_event_contract_mismatch"
    return ""


_REMOVE_LIFECYCLE_OPERATIONS = frozenset(
    {"remove", "expire", "dispel", "stack_reduce_remove"}
)


def _lifecycle_removed_instance(event: GameEvent) -> str:
    """Return the status instance a dispatched removal notification retired."""

    if event.event_type != "status.lifecycle" or not isinstance(event.payload, dict):
        return ""
    if event.payload.get("lifecycle_operation") not in _REMOVE_LIFECYCLE_OPERATIONS:
        return ""
    instance_id = event.payload.get("status_instance_id")
    return instance_id if isinstance(instance_id, str) else ""


def _detached_status_detail(event: GameEvent) -> dict[str, JSONValue] | None:
    if event.event_type != "status.lifecycle" or event.window != "OnDestroy" or event.payload.get(
        "lifecycle_operation"
    ) not in {"remove", "expire", "dispel", "stack_reduce_remove"}:
        return None
    detail = event.payload.get("status_detail")
    return dict(detail) if isinstance(detail, dict) else None


def _event_aliases(event: GameEvent, rules: RuleBook | None = None) -> tuple[EventAlias, ...]:
    if event.event_type == "status.immunity":
        return (_event_alias_for_callback(event, "OnImmuneDebuff", "status_immunity_fact", rules),)
    if event.event_type == "toughness.segment_depleted":
        return tuple(_event_alias_for_callback(event, callback, "stance_count_down_fact", rules)
                     for callback in ("OnBeingStanceCountDown", "OnTriggerStanceCountDown"))
    if event.event_type == "queue.action.before":
        fact = event.queue_action_start_fact
        if type(fact) is not QueueActionStartFact:
            return ()
        callbacks = ()
        if fact.queue_kind == "turn_insert_ability" and fact.window_family == "insert_ability":
            callbacks = (
                "OnListenInsertAbilityStart",
                *(
                    ("OnInsertAbilityStart",)
                    if rules is not None
                    and rules.status_event_family("OnInsertAbilityStart") is not None
                    else ()
                ),
            )
        elif fact.queue_kind == "turn_insert_action" and fact.window_family in {"insert_action", "extra_turn"}:
            callbacks = ("OnBeforeInsertActionPrepare", "OnInsertActionStart")
        return tuple(_event_alias_for_callback(event, callback, "queue_action_start_fact", rules)
                     for callback in callbacks)
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
    explicit_callback_events: set[str] = set()
    raw_events = event.payload.get("callback_events")
    if isinstance(raw_events, (list, tuple)):
        for item in raw_events:
            if isinstance(item, str) and item:
                explicit_callback_events.add(item)
                aliases.append(_event_alias_for_callback(event, item, "event.payload.callback_events", rules))
    for key in ("callback_event", "tbgd_event"):
        value = event.payload.get(key)
        if isinstance(value, str) and value:
            explicit_callback_events.add(value)
            aliases.append(_event_alias_for_callback(event, value, f"event.payload.{key}", rules))
    if event.window.startswith("On"):
        explicit_callback_events.add(event.window)
        aliases.append(_event_alias_for_callback(event, event.window, "event.window", rules))
    families = rules.status_event_families_for_runtime_event(event.event_type) if rules is not None else ()
    for family in families:
        if explicit_callback_events and not _family_matches_explicit_callback(
            family.callback_event,
            explicit_callback_events,
        ):
            continue
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
    if event.event_type == "unit.defeated":
        relation_alias = next(
            (
                alias
                for alias in aliases
                if alias.callback_event == "OnListenCharacterDie"
                and alias.scope_kind == "owner_local"
            ),
            None,
        )
        if relation_alias is not None:
            # Death observers reach the summoner's servants in addition to the
            # kill-credit owner; the callback's own ByHasSummonRelation predicate
            # still decides the final relation.
            aliases.append(
                replace(relation_alias, scope_kind="summoner_relation_local")
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


def _family_matches_explicit_callback(
    callback_event: str,
    explicit_callback_events: set[str],
) -> bool:
    if callback_event in explicit_callback_events:
        return True
    callback_key = _callback_companion_key(callback_event)
    return bool(callback_key) and any(
        _callback_companion_key(explicit) == callback_key
        for explicit in explicit_callback_events
    )


def _callback_companion_key(callback_event: str) -> str:
    value = callback_event.removeprefix("On")
    return value.removeprefix("Listen")


def _wave_monster_payload_block_reason(event: GameEvent) -> str:
    payload = event.payload
    required = (
        "wave_definition_id",
        "wave_index",
        "unit_id",
        "entry_id",
        "position",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        return "wave_monster_payload_incomplete"
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
        canonical_alias = next(
            (
                (scope_kind, blocked_dependency)
                for admitted_callback, scope_kind, blocked_dependency in CANONICAL_EVENT_ALIASES.get(
                    event.event_type,
                    (),
                )
                if admitted_callback == callback_event
            ),
            None,
        )
        if canonical_alias is not None:
            scope_kind, blocked_dependency = canonical_alias
            return EventAlias(
                callback_event=callback_event,
                scope_kind=scope_kind,
                source_basis=source_basis,
                admission_status=(
                    "blocked" if blocked_dependency else "executable"
                ),
                blocked_dependency=blocked_dependency,
                runtime_event_source=event.event_type,
            )
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
    elif event.event_type not in family.runtime_event_sources:
        admission_status = "blocked"
        blocked_dependency = f"event_source_not_admitted_for_family:{event.event_type}"
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
    resource_scope = resource_scope_for_event(event.event_type)
    if resource_scope:
        return resource_scope
    if event.event_type in {"damage.before_hit", "damage.hit", "damage.attacker_hit", "toughness.hit"}:
        return "per_hit_target_local"
    if event.event_type in {
        "damage.hit_sequence.before",
        "damage.hit_sequence.after",
    }:
        return "actor_local"
    if event.event_type in {
        "damage.target_attack.before",
        "damage.target_attack.after",
        "damage.target_hit_sequence.before",
        "damage.target_hit_sequence.after",
    }:
        return "being_hit_target_local"
    if event.event_type in {
        "hp.change",
        "energy.change",
        "heal.after",
        "shield.change",
        "shield.exhausted",
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


def _ability_property_recheck_unit_ids(
    state: BattleState,
    event: GameEvent,
    mutations: tuple[Mutation, ...],
) -> tuple[str, ...]:
    unit_ids: list[str] = []
    if event.event_type == "status.lifecycle" and event.target_id:
        unit_ids.append(event.target_id)
    mutation_path = event.payload.get("mutation_path")
    if (
        event.event_type in MUTATION_BACKED_EVENT_TYPES
        and event.payload.get("mutation_backed_event") is True
        and isinstance(event.payload.get("mutation_id"), str)
        and event.payload.get("mutation_id")
        and isinstance(mutation_path, (list, tuple))
        and len(mutation_path) >= 2
        and mutation_path[0] == "units"
        and mutation_path[1] == event.target_id
        and event.target_id in state.units
    ):
        unit_ids.append(event.target_id)
    if event.event_type in {"elation.points.changed", "dynamic.value.changed"}:
        # A battle resource change can cross a range on any wearer that owns a
        # source-backed watcher; only those units are rechecked.
        unit_ids.extend(
            unit_id
            for unit_id, unit in state.units.items()
            if isinstance(unit.flags.get("status_details"), (list, tuple))
            and any(
                isinstance(detail, dict)
                and detail.get("ability_property_watcher_ids")
                for detail in unit.flags.get("status_details", ())
            )
        )
    if event.event_type in {"battle.start", "battle.setup"}:
        unit_ids.extend(state.units)
    for mutation in mutations:
        if (
            len(mutation.path) >= 2
            and mutation.path[0] == "units"
            and mutation.path[1] in state.units
        ):
            unit_ids.append(mutation.path[1])
    return tuple(dict.fromkeys(unit_ids))


def _scope_kind_for_callback_event(event: GameEvent, callback_event: str) -> str:
    explicit = event.payload.get("listener_scope")
    if isinstance(explicit, str) and explicit:
        return explicit
    resource_scope = resource_scope_for_callback(callback_event)
    if resource_scope:
        return resource_scope
    if callback_event == "OnListenAllowAction":
        return "owner_local"
    if callback_event in {"OnAfterDealHeal", "OnBeforeDealHeal", "OnTriggerBreak", "OnTriggerStanceCountDown"}:
        return "actor_local"
    if callback_event in {
        "OnHPChange",
        "OnSPChange",
        "OnHPOverflow",
        "OnAfterBeingHeal",
        "OnBeforeBeingHeal",
        "OnShieldChange",
        "OnBeforeBeingStanceDamage",
        "OnBeingStanceDamage",
        "OnActionDelayEffect",
        "OnActionDelayEffectAll",
        "OnDeathrattle",
    }:
        return "being_hit_target_local"
    if callback_event in {
        "OnBeforeHit",
        "OnAfterHit",
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
    }:
        return "actor_local"
    if callback_event == "OnSnapshotCreate":
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
    if callback_event in {"OnBeforeDying", "OnBeforeMortallyWonded"}:
        return "owner_local"
    if callback_event in {
        "OnStack",
        "OnPhase1",
        "OnPhase2",
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
        if unit.lifecycle_status == "removed":
            continue
        for detail in unit.flags.get("status_details", ()):
            if isinstance(detail, dict) and detail.get("modifier_name") == modifier_name:
                details.append(detail)
    return tuple(details)


def _status_detail_for_unit_modifier(
    state: BattleState,
    unit_id: str,
    modifier_name: str,
    *,
    status_instance_id: str = "",
) -> dict[str, JSONValue] | None:
    unit = state.units.get(unit_id)
    if unit is None:
        return None
    for detail in unit.flags.get("status_details", ()):
        if (isinstance(detail, dict) and detail.get("modifier_name") == modifier_name
                and (not status_instance_id or detail.get("instance_id") == status_instance_id)):
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
    scope_ok, scope_reason = _scope_matches(
        event, scope_kind, detail, explicit=explicit, state=state
    )
    status = "matched"
    reason = ""
    if not scope_ok:
        status = "skipped"
        reason = scope_reason
    elif callback.blocked_reason in {"equipment_event_family_non_gameplay", "source_proven_presentation_only"}:
        status = "skipped"
        reason = "non_gameplay_listener_excluded"
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
        status_detail=detail,
    )


def _global_listener_auto_admitted(event: GameEvent, callback: StatusCallbackIR, alias: EventAlias) -> bool:
    return (
        bool(event.event_type)
        and callback.event == alias.callback_event
        and alias.admission_status == "executable"
    )


def _scope_matches(
    event: GameEvent,
    scope_kind: str,
    detail: dict[str, JSONValue],
    *,
    explicit: bool,
    state: BattleState | None = None,
) -> tuple[bool, str]:
    if scope_kind == "summoner_relation_local":
        # Formal summoner relation: the listener's owner must be a unit whose
        # summoner is the defeated unit. The caller's ByHasSummonRelation task
        # remains the authority for the final predicate result.
        if event.event_type != "unit.defeated" or state is None:
            return False, "summoner_relation_scope_event_or_state_missing"
        owner_id = str(detail.get("owner_id") or "")
        defeated_id = str(event.target_id or "")
        if owner_id not in state.units or not defeated_id:
            return False, "summoner_relation_scope_owner_missing"
        from .unit_relation import EntityRelationResolver, TargetEvaluationContext

        relation = EntityRelationResolver().resolve(
            state,
            "summon.summoner",
            TargetEvaluationContext(caster_id=owner_id, effect_owner_id=owner_id),
            subject_ids=(owner_id,),
            options={"allow_defeated": True},
        )
        if relation.blocked:
            return False, f"summoner_relation_scope_blocked:{relation.blocked_reason}"
        return (
            defeated_id in tuple(relation.target_ids),
            "scope_summoner_relation_mismatch",
        )
    if event.event_type in {item[0] for item in LIMBO_CALLBACKS}:
        plan = event.pending_defeat_plan
        if type(plan) is not PendingDefeatPlan:
            return False, "limbo_event_native_plan_missing"
        if scope_kind not in {"owner_local", "being_hit_target_local", "per_hit_target_local"}:
            return False, "limbo_listener_scope_not_admitted"
        return detail.get("owner_id") == plan.unit_id, "scope_dying_owner_mismatch"
    if event.event_type == "toughness.segment_depleted":
        fact = event.stance_count_down_fact
        owner_id = str(detail.get("owner_id") or "")
        if type(fact) is not StanceCountDownFact:
            return False, "stance_count_down_fact_missing_or_mismatched"
        if scope_kind == "actor_local":
            return owner_id == fact.attacker_id, "scope_actor_mismatch"
        if scope_kind == "being_hit_target_local":
            return owner_id == fact.target_id, "scope_being_hit_target_mismatch"
        return False, "stance_count_down_listener_scope_not_admitted"
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
        if event.event_type == "unit.before_dying":
            return (owner_id == current_hit_target_id, "scope_dying_owner_mismatch")
        return (owner_id in {actor_id, primary_target_id, current_hit_target_id}, "scope_owner_not_in_event_context")
    if scope_kind == "status_local":
        target_id = str(event.target_id or event.payload.get("target_id") or "")
        if event.event_type == "status.lifecycle" and event.window in {"OnModifierAdd", "OnModifierRemove"}:
            return (owner_id == target_id, "scope_modifier_owner_mismatch")
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
    if event.event_type == "toughness.segment_depleted" and type(event.stance_count_down_fact) is StanceCountDownFact:
        return event.stance_count_down_fact.attacker_id
    queue_fact = (event.queue_action_start_fact if event.event_type == "queue.action.before"
                  else event.queue_action_terminal_fact if event.event_type in {"queue.action.after", "queue.action.abort"}
                  else None)
    if type(queue_fact) in {QueueActionStartFact, QueueActionTerminalFact}:
        return queue_fact.actor_id
    for key in ("actor_id", "attacker_id"):
        value = event.payload.get(key)
        if isinstance(value, str) and value:
            return value
    return str(event.source_id or "")


def _event_primary_target_id(event: GameEvent) -> str:
    if event.event_type == "toughness.segment_depleted" and type(event.stance_count_down_fact) is StanceCountDownFact:
        return event.stance_count_down_fact.target_id
    value = event.payload.get("primary_action_target_id")
    if isinstance(value, str) and value:
        return value
    return str(event.target_id or "")


def _event_current_hit_target_id(event: GameEvent) -> str:
    if event.event_type == "toughness.segment_depleted" and type(event.stance_count_down_fact) is StanceCountDownFact:
        return event.stance_count_down_fact.target_id
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


def _optional_missing_mutation_alias(event: GameEvent, alias: EventAlias) -> bool:
    """Skip an absent optional listener on an already admitted mutation.

    Mutation producers may expose several TBGD callback spellings.  A focused
    RuleBook legitimately contains only the families used by its content; a
    missing family cannot execute and therefore must not roll back the
    mutation.  Existing-but-blocked families remain fail-closed.
    """

    return (
        event.event_type in MUTATION_BACKED_EVENT_TYPES
        and alias.admission_status != "executable"
        and alias.blocked_dependency.startswith("status_event_family_missing:")
    )


def _non_gameplay_alias(rules: RuleBook, alias: EventAlias) -> bool:
    callbacks = rules.status_callbacks_for_event(alias.callback_event)
    return bool(callbacks) and all(
        callback.blocked_reason in {"equipment_event_family_non_gameplay", "source_proven_presentation_only"}
        for callback in callbacks
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


def _listener_order_key(
    state: BattleState,
    scope_kind: str,
    unit_id: str,
    status_order: int,
    callback: StatusCallbackIR | None,
) -> dict[str, JSONValue]:
    unit_order = _unit_order(state, unit_id)
    callback_execution_order: list[int] = []
    callback_id = ""
    task_order: list[str] = []
    if callback is not None:
        callback_execution_order = [int(item) for item in callback.execution_order]
        callback_id = callback.callback_id
        task_order = list(callback.task_ids)
    return {
        "scope_priority": SCOPE_PRIORITY.get(scope_kind, 999),
        "scope_kind": scope_kind,
        "unit_order": unit_order,
        "unit_id": unit_id,
        "status_order": status_order,
        "callback_execution_order": callback_execution_order,
        "callback_id": callback_id,
        "task_order": task_order,
    }


def _match_sort_key(match: ListenerMatch) -> tuple[object, ...]:
    order = match.order_key or {}
    return (
        int(order.get("scope_priority") or 999),
        int(order.get("unit_order") or 999999),
        int(order.get("status_order") if isinstance(order.get("status_order"), int) else 999999),
        tuple(
            int(item)
            for item in order.get("callback_execution_order", [])
            if isinstance(item, int) and not isinstance(item, bool)
        )
        if isinstance(order.get("callback_execution_order"), list)
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
                        "callback_execution_order": [index, 0],
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
