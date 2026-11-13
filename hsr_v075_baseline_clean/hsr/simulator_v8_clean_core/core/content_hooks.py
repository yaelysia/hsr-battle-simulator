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

def processor_replaces_status_callback(rules, state, detail, event):
    """Use the same card ownership rule for dispatched and direct callbacks."""
    return any(
        (detail.get("modifier_name"), event) in mount.processor.replaced_status_callbacks
        for unit_id in {detail.get("owner_id"), detail.get("caster_id")}
        if unit_id in state.units
        for mount in rules._processors_by_entity.get(state.units[unit_id].template_id, ())
    )


if TYPE_CHECKING:
    from ..rules.ir import ActionDefinitionIR
    from ..rules.rulebook import RuleBook
    from ..systems.action_availability import ActionChoice, BlockedActionReason
    from ..systems.damage import DamageModifierContribution, DamageWindowLedger
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
    "projectile_source_shape_not_admitted",
    "retarget_child_task_blocked",
    "fixed_positive_loop_count_required",
    "target_language_dependency_blocked",
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
    hit_target_ids: tuple[str, ...] = ()
    damage_modifiers: tuple[DamageModifierContribution, ...] = ()


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
        if self.scope not in {"self_units", "owned_units", "battle"}:
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
    # Exact native status callbacks replaced by this card's event handler.
    replaced_status_callbacks: frozenset[tuple[str, str]] = frozenset()
    # Content may select an already compiled gameplay body instead of its
    # presentation wrapper; the native queue still owns start/finish/abort.
    standalone_body_overrides: tuple[tuple[str, str], ...] = ()
    standalone_body_leaf_opcodes: tuple[tuple[str, tuple[str, ...]], ...] = ()

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

    def filter_target_candidates(
        self, state: BattleState, actor: UnitState, action_id: str,
        action_level: int, candidates: tuple[str, ...],
    ) -> tuple[str, ...]:
        return candidates


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
        damage_window_ledger: DamageWindowLedger | None = None,
    ) -> None:
        from .reducer import MutationReducer
        from ..systems.damage import DamageWindowLedger

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
        self._damage_window_ledger = damage_window_ledger or DamageWindowLedger()
        self._hit_target_ids: list[str] = []
        self._damage_modifiers: list[DamageModifierContribution] = []

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

    def spawn_unit(self, unit: UnitState, *, reason: str) -> None:
        from ..systems.unit_lifecycle import UnitLifecycleSystem
        from ..systems.mutation_events import events_for_mutation

        mutation = UnitLifecycleSystem().spawn_mutation(self._state, unit, reason=reason, source="content_processor",
            source_trace={"content_processor": self._producer_id})
        self._apply((mutation,))
        self._events.extend(events_for_mutation(mutation, actor_id=unit.unit_id,
                            source_id=self._producer_id, event_index=self._state.event_index))

    def set_action_value(self, unit_id: str, value: float) -> None:
        from ..systems.timeline import TimelineSystem

        self._apply((TimelineSystem().set_action_value(self._state, unit_id, value, "content_processor"),))

    def request_battle_defeat(self, reason: str) -> None:
        key = "battle_defeat_requested"
        self._apply((Mutation("set", ("global_flags", key), self._state.global_flags.get(key), True,
            before_exists=key in self._state.global_flags, reason=reason, source="content_processor"),))

    def add_damage_modifier(self, contribution: DamageModifierContribution) -> None:
        from ..systems.damage import DamageModifierContribution

        if type(contribution) is not DamageModifierContribution:
            raise ProcessorBlocked("content_damage_modifier_requires_typed_contribution")
        self._damage_modifiers.append(contribution)

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

    def set_dynamic_value(self, unit_id: str, key: str, hash_key: str, value: float, event: GameEvent) -> None:
        """Write a content-declared unit slot through L1, including its watchers."""
        from ..rules.expression_ir import DynamicValueOperationIR, NumericOperandIR, numeric_fixed, DYNAMIC_VALUE_OPERATION_SCHEMA
        from ..rules.ir import IRSource
        from ..systems.dynamic_values import (DynamicValueExecutionRequest, plan_dynamic_value_operation,
            execute_dynamic_value_plan, dynamic_value_change_events)

        operation_id = f"{self._producer_id}:set:{key}"
        operand = NumericOperandIR(operation_id + ":value", "expression", {"formula_role": "value"},
                                   expression=numeric_fixed(value), coverage_status="executable")
        operation = DynamicValueOperationIR.from_spec({
            "schema_version": DYNAMIC_VALUE_OPERATION_SCHEMA, "operation_kind": "set", "destination_key": key,
            "destination_hash": hash_key, "target_alias": "Caster", "scope_kind": "unit", "lifecycle": "combat",
            "operand": operand.to_json(), "minimum": None, "maximum": None,
            "coverage_status": "executable", "blocked_reason": "",
        }, IRSource(self._producer_id, "content_processor", key))
        request = DynamicValueExecutionRequest(unit_id, self._producer_id, operation_id, "SetDynamicValue",
            owner_id=unit_id, operation_event_id=event.event_id)
        before = self._state
        plan = plan_dynamic_value_operation(before, operation, request, rules=self._rules)
        result = execute_dynamic_value_plan(before, plan, rules=self._rules)
        if not result.ok:
            raise ProcessorBlocked(result.blocked_reason)
        self._apply(result.mutations)
        self._records.extend(dict(record) for record in result.records)
        for changed in dynamic_value_change_events(before, plan, self._rules):
            self._events.append(changed)
            self._dispatch_event(changed)

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

    def execute_damage_tasks(
        self, task_ids: tuple[str, ...], *,
        action_definition: "ActionDefinitionIR", target_resolution: TargetResolution,
        execution_key: str = "",
    ) -> None:
        """Run content-selected compiled hits through the ordinary hit pipeline.

        Only ordering belongs to the processor. Numeric binding, hit windows,
        energy, toughness, break and death still belong to AbilityTaskSystem.
        """
        from ..systems.ability import AbilityTaskSystem, _ability_task_records_blocked_reason
        from ..systems.effect import EffectRegistry
        from ..systems.event_dispatch import EventDispatchSystem
        from ..systems.status import StatusSystem

        command = self._action_command
        if command is None or not task_ids or len(set(task_ids)) != len(task_ids):
            raise ProcessorBlocked("content_processor_damage_task_context_invalid")
        if execution_key:
            command = replace(command, metadata={**command.metadata, "ability_task_execution_path": execution_key})
        effects = EffectRegistry(StatusSystem(self._rules))
        if self._event_dispatcher is None:
            self._event_dispatcher = EventDispatchSystem(self._rules, effects, reducer=self._reducer)
        system = AbilityTaskSystem(self._rules, effects, reducer=self._reducer,
                                   event_dispatcher=self._event_dispatcher)
        ledger = self._damage_window_ledger
        sequence_id = f"processor_action:{self._state.event_index}:{command.actor_id}:{command.action_id}"
        if execution_key:
            sequence_id += f":{execution_key}"
        for task_id in task_ids:
            task = self._rules.ability_task(task_id)
            if (task is None or task.opcode != "DamageByAttackProperty"
                    or task.action_id != command.action_id or task.level != command.action_level
                    or task.coverage_status != "executable" or task.blocked_reason):
                raise ProcessorBlocked("content_processor_damage_task_not_admitted")
            _, mutations, events, rng_events, records, _ = system._execute_damage_task(
                self._state, task, command=command, action_definition=action_definition,
                primary_target=target_resolution.primary,
                target_resolution=target_resolution, task_graph_continuation=None,
                nested_ability_hooks=None, dispatched_event_ids=self._dispatched_event_ids,
                action_damage_modifiers=self._action_damage_modifiers,
                window_ledger=ledger, packet_sequence_id=sequence_id,
                hit_target_ids=self._hit_target_ids,
            )
            reason = _ability_task_records_blocked_reason(records)
            if reason:
                raise ProcessorBlocked(reason)
            self._apply(tuple(mutations))
            self._events.extend(events)
            self._rng_events.extend(rng_events)
            self._records.extend(records)
            # The hit pipeline already dispatched its events and produced its
            # process-only callback markers; the outer hook must not repeat them.
            self._dispatched_event_ids.update(str(event.to_json()["event_id"]) for event in events)

    def execute_effect_task(
        self, task_id: str, *, action_definition: "ActionDefinitionIR",
        target_resolution: TargetResolution, execution_key: str = "",
    ) -> None:
        """Apply a selected compiled leaf through the ordinary effect pipeline."""
        from ..systems.ability import AbilityTaskSystem, _ability_task_records_blocked_reason
        from ..systems.effect import EffectRegistry
        from ..systems.status import StatusSystem

        command = self._action_command
        task = self._rules.ability_task(task_id)
        if (command is None or task is None or task.action_id != command.action_id
                or task.level != command.action_level or task.child_task_ids
                or task.opcode == "DamageByAttackProperty"):
            raise ProcessorBlocked("content_processor_effect_task_context_invalid")
        command = replace(command, metadata={**command.metadata, "ability_task_execution_path": execution_key})
        system = AbilityTaskSystem(self._rules, EffectRegistry(StatusSystem(self._rules)),
                                   reducer=self._reducer, event_dispatcher=self._event_dispatcher)
        _, mutations, events, rng_events, records, _ = system._execute_ability_leaf_task(
            self._state, task, command=command, action_definition=action_definition,
            primary_target=target_resolution.primary, target_resolution=target_resolution,
            topology_authority="external_legacy", dispatched_event_ids=self._dispatched_event_ids,
        )
        reason = _ability_task_records_blocked_reason(records)
        if reason:
            raise ProcessorBlocked(reason)
        self._apply(tuple(mutations))
        self._events.extend(events)
        self._rng_events.extend(rng_events)
        self._records.extend(records)

    def apply_status_effect(self, effect_id: str, *, caster_id: str, target_id: str, execution_key: str = "") -> None:
        """Apply a compiled modifier to a content-selected target through L1."""
        from ..systems.status import StatusSystem

        effect = self._rules.effect(effect_id)
        if effect is None or effect.opcode != "AddModifier" or effect.coverage_status != "executable":
            raise ProcessorBlocked("content_status_effect_not_admitted")
        result = StatusSystem(self._rules).apply_add_modifier(
            self._state, effect, caster_id=caster_id, source_id=effect_id,
            owner_id=caster_id, _resolved_target_ids=(target_id,),
            application_instance_id=f"processor:{self._producer_id}:{self._state.event_index}:{caster_id}:{target_id}:{effect_id}:{execution_key}",
        )
        if not result.ok:
            raise ProcessorBlocked(",".join(result.unsupported))
        self._absorb(result)

    def remove_status(self, target_id: str, detail: dict[str, JSONValue]) -> None:
        from ..systems.status import StatusSystem

        result = StatusSystem(self._rules).remove_status_instance(
            self._state, target_id=target_id, detail=detail,
            source="content_processor", source_trace={"processor": self._producer_id},
        )
        if not result.ok:
            raise ProcessorBlocked(",".join(result.unsupported))
        self._apply(result.mutations)
        self._events.extend(result.events)
        self._records.extend(result.records)

    def execute_status_tasks(
        self, owner_id: str, modifier_name: str, callback_event: str,
        task_ids: tuple[str, ...], predicate_task_id: str | None, trigger_event: GameEvent,
        *, parameter_entity_id: str | None = None,
    ) -> None:
        """Run selected compiled leaves under their native status predicate.

        Content chooses the gameplay leaves; status ownership, condition values,
        queue admission and mutations remain with their existing L1 consumers.
        """
        from ..systems.status_callbacks import StatusCallbackSystem, _retarget_event

        unit = self.unit(owner_id)
        details = [d for d in unit.flags.get("status_details", ())
                   if d.get("modifier_name") == modifier_name] if unit is not None else []
        callbacks = self._rules.status_callbacks_for_modifier_event(modifier_name, callback_event)
        if len(details) != 1 or len(callbacks) != 1:
            raise ProcessorBlocked("content_status_callback_identity_missing_or_ambiguous")
        detail, callback = details[0], callbacks[0]
        tasks = {t.task_id: t for t in self._rules.status_callback_tasks_for_callback(callback.callback_id)}
        predicate = tasks.get(predicate_task_id)
        condition = self._rules.condition(predicate.condition_id) if predicate is not None else None
        if any(task_id not in tasks for task_id in task_ids):
            raise ProcessorBlocked("content_status_task_missing")
        system = (self._event_dispatcher.status_callbacks if self._event_dispatcher is not None
                  else StatusCallbackSystem(self._rules))
        event = trigger_event
        if parameter_entity_id is not None:
            if parameter_entity_id not in self._state.units:
                raise ProcessorBlocked("content_status_parameter_entity_missing")
            event = _retarget_event(trigger_event, parameter_entity_id)
        if predicate_task_id is None:
            if any(t.condition_id for t in tasks.values()):
                raise ProcessorBlocked("content_status_callback_requires_predicate")
        else:
            if condition is None:
                raise ProcessorBlocked("content_status_task_missing")
            decision, rng, event = system._evaluate_callback_condition(
                condition, self._state, callback, predicate, detail, event,
            )
            if not decision.ok or decision.result is None:
                raise ProcessorBlocked(decision.reason)
            self._rng_events.extend(rng)
            if not decision.result:
                return
        for task_id in task_ids:
            detail = next((d for d in self.unit(owner_id).flags.get('status_details', ())
                           if d.get('instance_id') == detail.get('instance_id')), detail)
            result = system._execute_formal_leaf_task(
                self._state, callback, tasks[task_id], detail, event, None,
            )
            if not result.ok:
                raise ProcessorBlocked(",".join(result.errors))
            self._absorb(result)

    def grant_energy(self, unit_id: str, amount: float, event: GameEvent) -> None:
        from ..systems.resource import ResourceSystem
        from ..systems.mutation_events import events_for_mutation
        from .settlement import SettlementRecord

        mutation = ResourceSystem().change_unit_energy(self._state, unit_id, amount, "content_processor")
        mutation = replace(mutation, mutation_id=f"{mutation.mutation_id}:{event.event_id}")
        self._apply((mutation,))
        self._events.extend(events_for_mutation(
            mutation, actor_id=unit_id, source_id=unit_id, event_index=self._state.event_index,
        ))
        self._records.append(SettlementRecord(
            record_type="content_energy", source="content_processor",
            mutation_id=mutation.stable_id(), process_only=False,
            payload={"unit_id": unit_id, "raw_amount": amount, "before": mutation.before,
                     "after": mutation.after, "trigger_event_id": event.event_id},
        ).to_json())

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
        result = DamageSystem(self._rules).apply_packet(
            self._state, packet, window_ledger=self._damage_window_ledger,
        )
        if not result.ok:
            raise ProcessorBlocked(",".join(result.errors) or "content_processor_damage_blocked")
        self._absorb(result)
        if packet.damage_kind == "hp_damage" and packet.damage_formula_family in {"direct", "elation"}:
            self._hit_target_ids.append(packet.target_id)
        for event in result.events:
            self._damage_window_ledger.record_defeat_event(event)
        return result

    def resolve_rng(self, request: Any) -> Any:
        """Resolve one typed RNG request through the shared deterministic RNG.

        The request carries its own before_state identity; the resolution
        event is recorded in the hook output and committed (or discarded)
        with the owning atomic transition.
        """
        from ..systems.rng import resolve_rng_request, rng_choices_from_payload, rng_mode_from_payload

        metadata = self._action_command.metadata if self._action_command is not None else {}
        resolution = resolve_rng_request(request, rng_choices=rng_choices_from_payload(metadata),
                                         rng_mode=rng_mode_from_payload(metadata))
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
            hit_target_ids=tuple(dict.fromkeys(self._hit_target_ids)),
            damage_modifiers=tuple(self._damage_modifiers),
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


def processor_standalone_body(rules: "RuleBook", actor: UnitState, ability_name: str) -> str | None:
    names = {dict(mount.processor.standalone_body_overrides)[ability_name]
             for mount in getattr(rules, "_processors_by_entity", {}).get(actor.template_id, ())
             if ability_name in dict(mount.processor.standalone_body_overrides)}
    if len(names) > 1:
        raise ProcessorBlocked("content_standalone_body_ambiguous")
    return next(iter(names), None)


def processor_standalone_leaf_opcodes(rules: "RuleBook", actor: UnitState, body_name: str) -> frozenset[str] | None:
    selections = {frozenset(dict(mount.processor.standalone_body_leaf_opcodes)[body_name])
                  for mount in getattr(rules, "_processors_by_entity", {}).get(actor.template_id, ())
                  if body_name in dict(mount.processor.standalone_body_leaf_opcodes)}
    if len(selections) > 1 or frozenset() in selections:
        raise ProcessorBlocked("content_standalone_leaf_selection_invalid")
    return next(iter(selections), None)


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
    if content_id.startswith("battle_event:"):
        # Scoped cards retain the formal birth definition in CreateBattleEvent,
        # even when the catalog's standalone entity row is outside their scope.
        return rules.entity(content_id) is not None or any(
            effect.opcode == "CreateBattleEvent" and effect.coverage_status == "executable"
            and effect.payload.get("standard", {}).get("definition", {}).get("entity_ref") == content_id
            for effect in rules.ir.effects
        )
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
        self_units = _self_units(state, mount.content_id)
        retired = state.units.get(event.target_id) if event.event_type == "unit.removed" else None
        if retired is not None and retired.template_id == mount.content_id:
            self_units = tuple(dict.fromkeys((*self_units, retired.unit_id)))
        if not self_units:
            continue
        scopes = {
            subscription.scope for subscription in subscriptions
            if event.event_type in subscription.event_types
        }
        if "battle" in scopes:
            matched.append(mount)
            continue
        if "owned_units" in scopes:
            scope_units = set(_owned_units(state, mount.content_id))
        else:
            scope_units = set(self_units)
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
