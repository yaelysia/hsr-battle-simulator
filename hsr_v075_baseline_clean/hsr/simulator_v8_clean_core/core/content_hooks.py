"""L1 public mount points for content-specific processors (L2).

This module is the generic kernel side of the content-processor contract
(ARCHITECTURE_BOUNDARY_CONTRACT.md section 5, established by the M1-3
experiment). It defines the processor protocol, typed hook results, the
read-only hook contexts and the L1 services facade. Dispatch is generic:
the kernel looks processors up by the acting unit's own content identity
(the same shape as combatant action-set lookup) and never branches on
content names or fixed ids. The catalog of which content carries which
processor is L2 data (content_processors package).

Boundary rules enforced here:
- Processors only produce typed mutations/events/rng events; all state
  change flows through the same atomic commit as every other system.
- A failed hook yields zero mutations and zero RNG consumption because the
  owning transition is rejected by the existing atomic boundary.
- No eager identity hashing or thaw/to_json on the hook path: frozen
  containers serialize directly; identity checks happen on demand.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Callable, Mapping

from .model import (
    ActionCommand,
    BattleState,
    GameEvent,
    JSONValue,
    Mutation,
    RNGEvent,
    TargetResolution,
    UnitState,
)

if TYPE_CHECKING:
    from ..rules.ir import ActionDefinitionIR
    from ..rules.rulebook import RuleBook
    from ..systems.action_availability import ActionChoice, BlockedActionReason
    from ..systems.damage import DamageModifierContribution
    from ..systems.event_dispatch import EventDispatchSystem, EventNormalization


PROCESSOR_EVENT_DEPTH_LIMIT = 8

# Graph-coverage block reasons bypassed for processor-claimed actions (H1/H4).
# These describe the compiled task graph's admission state, which the
# processor replaces via the H1 execution hook. Anything outside this set
# (target, resource, lifecycle, control, identity) is never bypassed.
GRAPH_COVERAGE_BLOCK_PREFIXES = (
    "task_graph_",
    "effect_coverage_",
    "bounce_not_executable",
    "condition_not_executable",
    "damage_emission_scaling_ratio_not_runtime_bound",
    "process_only_task_coverage_mismatch",
)


def graph_coverage_block_reason(reason: str) -> bool:
    """True when every comma-separated part is a compiled-graph coverage block."""
    parts = tuple(part for part in reason.split(",") if part)
    return bool(parts) and all(
        part.startswith(GRAPH_COVERAGE_BLOCK_PREFIXES) for part in parts
    )


class ProcessorBlocked(Exception):
    """Internal service failure; the hook runner turns it into a blocked result."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class HookResult:
    """Typed processor output; merged into the owning atomic transition.

    takeover=False (default): the processor acted as a pre-effect hook and
    the compiled action graph still runs afterwards. takeover=True: the
    processor replaces the compiled effect segment for this action.
    """

    ok: bool
    blocked_reason: str = ""
    mutations: tuple[Mutation, ...] = ()
    events: tuple[GameEvent, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    takeover: bool = False
    dispatched_event_ids: frozenset[str] = frozenset()
    event_normalizations: tuple[EventNormalization, ...] = ()


@dataclass(frozen=True)
class EventSubscription:
    """Which events a processor listens to, and about which units.

    scope "self_units": event target/source is a unit of the processor's
    own content. scope "owned_units": additionally units owned by a self
    unit (summons/servants). A processor is only notified while at least
    one unit of its content is present (not removed).
    """

    event_types: tuple[str, ...]
    scope: str = "self_units"

    def __post_init__(self) -> None:
        if self.scope not in {"self_units", "owned_units"}:
            raise ValueError("event subscription scope is not admitted")
        if not self.event_types or any(not isinstance(item, str) or not item for item in self.event_types):
            raise ValueError("event subscription requires non-empty event types")
        object.__setattr__(self, "event_types", tuple(dict.fromkeys(self.event_types)))


@dataclass(frozen=True)
class AvailabilityContext:
    state: BattleState
    actor: UnitState
    choices: tuple[Any, ...]
    blocked: tuple[Any, ...]


@dataclass(frozen=True)
class ActionHookContext:
    state: BattleState
    command: ActionCommand
    action_definition: "ActionDefinitionIR"
    target_resolution: TargetResolution
    services: "ProcessorServices"


@dataclass(frozen=True)
class EventHookContext:
    state: BattleState
    event: GameEvent
    services: "ProcessorServices"


class ContentProcessorBase:
    """Default no-op hooks; content processors subclass and override.

    Subclasses must set content_id (the card identity they belong to) and
    version (bump on every semantic change; recorded in setup audit).
    """

    content_id: str = ""
    version: str = "0"

    def claims_action(self, state: BattleState, action_id: str, action_level: int) -> bool:
        return False

    def execute_action(self, ctx: ActionHookContext) -> HookResult:
        return HookResult(ok=False, blocked_reason="content_processor_action_not_implemented")

    def subscriptions(self) -> tuple[EventSubscription, ...]:
        return ()

    def on_event(self, ctx: EventHookContext) -> HookResult:
        return ctx.services.finish()

    def filter_choices(self, ctx: AvailabilityContext) -> AvailabilityContext:
        return ctx


@dataclass(frozen=True)
class MountedProcessor:
    content_id: str
    version: str
    processor: ContentProcessorBase

    def to_json(self) -> dict[str, JSONValue]:
        return {"content_id": self.content_id, "version": self.version}


class ProcessorServices:
    """L1 facade offered to processors inside one hook invocation.

    Every method returns typed results and advances an internal candidate
    state through the same MutationReducer the kernel uses, so later steps
    observe earlier effects. Accumulated output is returned via finish();
    block() aborts the hook with zero committed output (the owning atomic
    transition rejects everything, including RNG events).
    """

    def __init__(
        self, state: BattleState, rules: "RuleBook", *, producer_id: str,
        action_command: ActionCommand | None = None,
        action_damage_modifiers: tuple[DamageModifierContribution, ...] = (),
        event_dispatcher: EventDispatchSystem | None = None,
        processor_depth: int = 0,
    ) -> None:
        from .reducer import MutationReducer

        self._rules = rules
        self._reducer = MutationReducer()
        self._state = state
        self._producer_id = producer_id
        self._mutations: list[Mutation] = []
        self._events: list[GameEvent] = []
        self._rng_events: list[RNGEvent] = []
        self._records: list[dict[str, JSONValue]] = []
        self._blocked_reason = ""
        self._action_command = action_command
        self._action_damage_modifiers = tuple(action_damage_modifiers)
        self._event_dispatcher = event_dispatcher
        self._processor_depth = processor_depth
        self._dispatched_event_ids: set[str] = set()
        self._event_normalizations: list[EventNormalization] = []

    @property
    def state(self) -> BattleState:
        return self._state

    @property
    def rules(self) -> "RuleBook":
        return self._rules

    def _apply(self, mutations: tuple[Mutation, ...]) -> None:
        if not mutations:
            return
        reduction = self._reducer.apply_all_result(self._state, mutations)
        if not reduction.ok:
            conflict = reduction.conflicts[0].code if reduction.conflicts else "unknown"
            raise ProcessorBlocked(f"content_processor_reducer_conflict:{conflict}")
        self._state = reduction.after_state
        self._mutations.extend(mutations)

    def _absorb(self, result: Any) -> None:
        self._apply(tuple(result.mutations))
        self._events.extend(result.events)
        self._rng_events.extend(result.rng_events)
        self._records.extend(result.records)
        self._dispatched_event_ids.update(getattr(result, "dispatched_event_ids", ()))
        self._event_normalizations.extend(getattr(result, "event_normalizations", ()))

    def _dispatch_event(self, event: GameEvent) -> None:
        result = self._event_dispatcher.dispatch_event(
            self._state, event=event, _processor_depth=self._processor_depth,
        )
        if result.errors:
            raise ProcessorBlocked(",".join(result.errors))
        self._absorb(result)
        self._dispatched_event_ids.add(str(event.to_json()["event_id"]))
        self._dispatched_event_ids.update(str(item.to_json()["event_id"]) for item in result.events)

    # -- typed state helpers -------------------------------------------------

    def unit(self, unit_id: str) -> UnitState | None:
        return self._state.units.get(unit_id)

    def set_unit_flag(
        self,
        unit_id: str,
        key: str,
        value: JSONValue,
        *,
        reason: str,
        metadata: dict[str, JSONValue] | None = None,
    ) -> Mutation:
        unit = self._state.units.get(unit_id)
        if unit is None:
            raise ProcessorBlocked(f"content_processor_unit_missing:{unit_id}")
        mutation = Mutation(
            "set", ("units", unit_id, "flags", key), unit.flags.get(key), value,
            before_exists=key in unit.flags,
            reason=reason, source="content_processor",
            metadata={"processor": self._producer_id, **(metadata or {})},
        )
        self._apply((mutation,))
        return mutation

    def set_unit_resource(
        self,
        unit_id: str,
        key: str,
        value: float,
        *,
        reason: str,
        metadata: dict[str, JSONValue] | None = None,
    ) -> Mutation:
        unit = self._state.units.get(unit_id)
        if unit is None:
            raise ProcessorBlocked(f"content_processor_unit_missing:{unit_id}")
        mutation = Mutation(
            "set", ("units", unit_id, "resources", key), unit.resources.get(key), float(value),
            before_exists=key in unit.resources,
            reason=reason, source="content_processor",
            metadata={"processor": self._producer_id, **(metadata or {})},
        )
        self._apply((mutation,))
        return mutation

    # -- L1 system calls ------------------------------------------------------

    def spawn_servant(
        self,
        servant_ref: str,
        owner_id: str,
        *,
        spawn_source: Any,
        initial_values: dict[str, JSONValue] | None = None,
    ) -> Any:
        from ..systems.summon import SummonSystem

        definition = self._rules.servant_definition(servant_ref)
        if definition is None:
            raise ProcessorBlocked(f"content_processor_servant_definition_missing:{servant_ref}")
        summons = SummonSystem(self._rules)
        plan = summons.plan_spawn_servant(
            self._state, definition, owner_id=owner_id,
            spawn_source=spawn_source, initial_values=initial_values,
        )
        if not plan.ok:
            raise ProcessorBlocked(plan.blocked_reason or "content_processor_servant_spawn_blocked")
        result = summons.apply_spawn_servant(self._state, plan, initial_values=initial_values)
        if not result.plan.ok:
            raise ProcessorBlocked(result.plan.blocked_reason or "content_processor_servant_spawn_blocked")
        self._absorb(result)
        return result

    def remove_summon(
        self,
        unit_id: str,
        reason: str,
        *,
        source_trace: dict[str, JSONValue] | None = None,
    ) -> Any:
        from ..systems.summon import SummonSystem

        summons = SummonSystem(self._rules)
        # Removal is admitted by the mounted processor's admitted behavior plus
        # the domain planner's formal conditions below. source_trace is audit
        # description only (AGENTS.md source_trace boundary): it is recorded,
        # never a runtime gate.
        trace = {"content_processor": self._producer_id, **(source_trace or {})}
        plan = summons.plan_remove(
            self._state, unit_id, reason,
            source_trace=trace,
            admission={
                "coverage_status": "executable",
                "remove_source_admitted": True,
                "admission_basis": "content_processor_mounted_behavior",
                "rule_source": dict(source_trace or {}),
            },
        )
        if not plan.ok:
            raise ProcessorBlocked(plan.blocked_reason or "content_processor_summon_remove_blocked")
        result = summons.apply_remove(self._state, plan)
        if not result.plan.ok:
            raise ProcessorBlocked(result.plan.blocked_reason or "content_processor_summon_remove_blocked")
        self._absorb(result)
        return result

    def apply_toughness(self, packet: Any) -> Any:
        """Apply one typed toughness packet through the shared ToughnessSystem.

        The packet carries the formal emission identity and amount expression;
        the L1 system owns weakness matching, the toughness pipeline, break
        and overflow. Skips (no weakness / no toughness) are not failures.
        """
        from ..systems.break_system import BreakSystem
        from ..systems.effect import EffectRegistry
        from ..systems.event_dispatch import EventDispatchSystem
        from ..systems.mutation_events import before_toughness_calculation_event
        from ..systems.status import StatusSystem
        from ..systems.toughness import ToughnessSystem

        effects = EffectRegistry(StatusSystem(self._rules))
        if self._event_dispatcher is None:
            self._event_dispatcher = EventDispatchSystem(self._rules, effects, reducer=self._reducer)
        before_event = before_toughness_calculation_event(
            actor_id=packet.attacker_id, target_id=packet.target_id,
            event_index=self._state.event_index, packet=packet.to_json(),
        )
        self._events.append(before_event)
        self._dispatch_event(before_event)
        system = ToughnessSystem(self._rules)
        result = system.apply_packet(self._state, packet)
        if not result.ok:
            raise ProcessorBlocked(
                result.errors[0] if result.errors else "content_processor_toughness_blocked"
            )
        self._apply(result.mutations)
        self._events.extend(result.events)
        self._records.extend(result.records)
        for event in result.events:
            self._dispatch_event(event)
        broken = BreakSystem(
            self._rules, effects, reducer=self._reducer,
            event_dispatcher=self._event_dispatcher,
            processor_depth=self._processor_depth,
        ).enter_if_depleted(self._state, result)
        if broken is not None:
            if not broken.ok:
                raise ProcessorBlocked(",".join(broken.errors) or "content_processor_break_blocked")
            self._absorb(broken)
            for event in broken.events:
                if str(event.to_json()["event_id"]) not in self._dispatched_event_ids:
                    self._dispatch_event(event)
        return result

    def apply_damage(self, packet: Any) -> Any:
        """Apply one typed damage packet through the shared DamageSystem.

        Covers hp_damage and hp_loss families alike; the packet carries the
        scaling basis/ratio and source frame, and the L1 formula owns the
        settlement. The result joins the hook output and atomic boundary.
        """
        from ..systems.damage import DamageSystem

        if (
            self._action_command is not None
            and packet.attacker_id == self._action_command.actor_id
            and packet.damage_kind == "hp_damage"
            and packet.damage_formula_family in {"direct", "elation"}
            and self._action_damage_modifiers
        ):
            packet = replace(packet, modifier_contributions=(
                *(item for item in self._action_damage_modifiers
                  if item not in packet.modifier_contributions),
                *packet.modifier_contributions,
            ))
        result = DamageSystem(self._rules).apply_packet(self._state, packet)
        if not result.ok:
            raise ProcessorBlocked(",".join(result.errors) or "content_processor_damage_blocked")
        self._absorb(result)
        return result

    def resolve_rng(self, request: Any) -> Any:
        """Resolve one typed RNG request through the shared deterministic RNG.

        The request carries its own before_state identity; the resolution
        event is recorded in the hook output and committed (or discarded)
        with the owning atomic transition.
        """
        from ..systems.rng import resolve_rng_request

        resolution = resolve_rng_request(request)
        if not resolution.ok:
            raise ProcessorBlocked(resolution.blocked_reason or "content_processor_rng_blocked")
        if resolution.event is None:
            raise ProcessorBlocked("content_processor_rng_event_missing")
        self._rng_events.append(resolution.event)
        return resolution

    # -- output ----------------------------------------------------------------

    def emit_event(self, event: GameEvent) -> None:
        self._events.append(event)

    def add_record(self, record: dict[str, JSONValue]) -> None:
        self._records.append(record)

    def finish(self, *, takeover: bool = False) -> HookResult:
        if self._blocked_reason:
            return HookResult(ok=False, blocked_reason=self._blocked_reason)
        events = tuple(self._events)
        if self._dispatched_event_ids:
            from .executor import _dedupe_events, _EventIdentityConflict

            try:
                events = _dedupe_events(*events, event_normalizations=tuple(self._event_normalizations))
            except _EventIdentityConflict as conflict:
                return self.block(conflict.reason_code)
            # Eventful commits assign fresh ids to id-less events. Preserve
            # the ids already consumed by the internal dispatch boundary.
            events = tuple(
                replace(event, event_id=str(event.to_json()["event_id"]))
                if not event.event_id and str(event.to_json()["event_id"]) in self._dispatched_event_ids
                else event for event in events
            )
        return HookResult(
            ok=True,
            mutations=tuple(self._mutations),
            events=events,
            rng_events=tuple(self._rng_events),
            records=tuple(self._records),
            takeover=takeover,
            dispatched_event_ids=frozenset(self._dispatched_event_ids),
            event_normalizations=tuple(self._event_normalizations),
        )

    def block(self, reason: str) -> HookResult:
        self._blocked_reason = reason
        return HookResult(ok=False, blocked_reason=reason)


def run_hook(
    processor: ContentProcessorBase,
    hook: str,
    ctx: Any,
) -> HookResult:
    """Invoke one hook, converting service failures into blocked results."""
    try:
        if hook == "action":
            result = processor.execute_action(ctx)
        elif hook == "event":
            result = processor.on_event(ctx)
        else:
            raise ValueError(f"unknown processor hook:{hook}")
    except ProcessorBlocked as blocked:
        return HookResult(ok=False, blocked_reason=blocked.reason)
    if type(result) is not HookResult:
        return HookResult(ok=False, blocked_reason="content_processor_invalid_hook_result")
    return result


# -- generic mount and dispatch ------------------------------------------------


def _unit_present(unit: UnitState | None) -> bool:
    return unit is not None and unit.lifecycle_status != "removed"


def _self_units(state: BattleState, content_id: str) -> tuple[str, ...]:
    return tuple(
        unit_id for unit_id, unit in sorted(state.units.items())
        if unit.template_id == content_id and _unit_present(unit)
    )


def _owned_units(state: BattleState, content_id: str) -> tuple[str, ...]:
    self_ids = set(_self_units(state, content_id))
    owned = set(self_ids)
    for unit_id, unit in sorted(state.units.items()):
        if _unit_present(unit) and str(unit.flags.get("owner_id") or "") in self_ids:
            owned.add(unit_id)
    return tuple(sorted(owned))


def attach_processors(rules: "RuleBook", mounts: tuple[MountedProcessor, ...]) -> "RuleBook":
    """Attach sorted mounts to a RuleBook (frozen; same pattern as its indexes)."""
    ordered = tuple(sorted(mounts, key=lambda item: item.content_id))
    if len({item.content_id for item in ordered}) != len(ordered):
        raise ValueError("content processor mounts must have unique content ids")
    by_entity: dict[str, tuple[MountedProcessor, ...]] = {}
    for mount in ordered:
        by_entity.setdefault(mount.content_id, ())
        by_entity[mount.content_id] = (*by_entity[mount.content_id], mount)
    object.__setattr__(rules, "content_processors", ordered)
    object.__setattr__(rules, "_processors_by_entity", by_entity)
    return rules


def mount_catalog(rules: "RuleBook", catalog: Mapping[str, Callable[[], ContentProcessorBase]]) -> "RuleBook":
    """Mount catalog entries whose content identity exists in the RuleBook.

    The catalog is L2 data; this function only performs generic presence
    checks against the compiled IR (avatar profiles, servant definitions,
    monster cards, entities). No content name or id is interpreted here.
    """
    mounts: list[MountedProcessor] = []
    for content_id in sorted(catalog):
        if not _content_present(rules, content_id):
            continue
        processor = catalog[content_id]()
        if processor.content_id != content_id:
            raise ValueError(f"content processor identity mismatch:{content_id}")
        mounts.append(MountedProcessor(
            content_id=content_id, version=str(processor.version), processor=processor,
        ))
    return attach_processors(rules, tuple(mounts))


def _content_present(rules: "RuleBook", content_id: str) -> bool:
    if content_id.startswith("avatar:"):
        return rules.avatar_profile(content_id[len("avatar:"):]) is not None
    if content_id.startswith("servant:"):
        return rules.servant_definition(content_id) is not None
    if content_id.startswith("monster:"):
        return rules.monster_data_card_for_entity(content_id) is not None
    return rules.entity(content_id) is not None


def processor_action_hook(
    rules: "RuleBook", state: BattleState, command: ActionCommand,
) -> MountedProcessor | None:
    unit = state.units.get(command.actor_id)
    if unit is None:
        return None
    for mount in getattr(rules, "_processors_by_entity", {}).get(unit.template_id, ()):
        if mount.processor.claims_action(state, command.action_id, command.action_level):
            return mount
    return None


def processors_for_event(
    rules: "RuleBook", state: BattleState, event: GameEvent,
) -> tuple[MountedProcessor, ...]:
    mounts = getattr(rules, "content_processors", ())
    if not mounts:
        return ()
    matched: list[MountedProcessor] = []
    referenced = tuple(
        unit_id for unit_id in (event.target_id, event.source_id)
        if unit_id and unit_id in state.units
    )
    for mount in mounts:
        subscriptions = mount.processor.subscriptions()
        if not any(event.event_type in subscription.event_types for subscription in subscriptions):
            continue
        if not _self_units(state, mount.content_id):
            continue
        scopes = {
            subscription.scope for subscription in subscriptions
            if event.event_type in subscription.event_types
        }
        if "owned_units" in scopes:
            scope_units = set(_owned_units(state, mount.content_id))
        else:
            scope_units = set(_self_units(state, mount.content_id))
        if any(unit_id in scope_units for unit_id in referenced):
            matched.append(mount)
    return tuple(matched)


def filter_actor_choices(
    rules: "RuleBook",
    state: BattleState,
    actor: UnitState,
    choices: tuple[Any, ...],
    blocked: tuple[Any, ...],
) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    mounts = getattr(rules, "_processors_by_entity", {}).get(actor.template_id, ())
    for mount in mounts:
        ctx = AvailabilityContext(state=state, actor=actor, choices=choices, blocked=blocked)
        filtered = mount.processor.filter_choices(ctx)
        if type(filtered) is not AvailabilityContext:
            raise ValueError("content processor filter must return an AvailabilityContext")
        choices, blocked = tuple(filtered.choices), tuple(filtered.blocked)
    return choices, blocked
