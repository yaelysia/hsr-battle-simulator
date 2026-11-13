from __future__ import annotations

from dataclasses import dataclass, replace

from ..core.model import BattleState, GameEvent, JSONValue, Mutation, RNGEvent
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..core.transition_outcome import ExecutionNodeResult
from ..rules.evaluator import NumericEvaluationContext, RuleEvaluator
from ..rules.expression_ir import numeric_dynamic_hash, numeric_dynamic_hashes
from ..rules.ir import AbilityPropertyRangeIR, AbilityPropertyWatcherIR
from ..rules.rulebook import RuleBook
from .dynamic_values import (
    status_binding_sources, binding_source_from_store, binding_source_from_status_detail,
    character_declared_dynamic_binding_source, servant_declared_dynamic_binding_source,
    store_from_state,
)
from .status_callbacks import StatusCallbackExecutionResult, StatusCallbackSystem, _condition_context
from .task_graph import (
    TaskGraphContinuation,
    TaskGraphExecutionHooks,
    TaskGraphNodeProjection,
)
from .unit_stats import ability_property_value


WATCHER_STATE_FIELD = "ability_property_watcher_state"
_PROPERTY_CHANGE_PRODUCER = object()


@dataclass(frozen=True)
class AbilityPropertyChangeFact:
    """A watcher-native before/after read and its exact callback event."""
    before_state: BattleState
    after_state: BattleState
    watcher: AbilityPropertyWatcherIR
    range_id: str
    unit_id: str
    before: float
    after: float
    event_id: str
    event_source_id: str
    event_target_id: str | None
    _producer_token: object
    _issued: tuple[object, ...]
    _event_signature: tuple[object, ...]
    status_instance_id: str
    rules: RuleBook

    def __post_init__(self) -> None:
        import math
        issued = (id(self.before_state), id(self.after_state), id(self.watcher), self.range_id,
                  self.unit_id, self.before, self.after, self.event_id, self.event_source_id, self.event_target_id, self._event_signature, self.status_instance_id, id(self.rules))
        if self._producer_token is not _PROPERTY_CHANGE_PRODUCER or self._issued != issued:
            raise ValueError("property change fact requires its issued native reads")
        if (type(self.watcher) is not AbilityPropertyWatcherIR
                or type(self.before_state) is not BattleState or type(self.after_state) is not BattleState
                or type(self.before) not in (int, float) or type(self.after) not in (int, float)
                or not math.isfinite(self.before) or not math.isfinite(self.after) or self.before == self.after
                or self.unit_id not in self.before_state.units or self.unit_id not in self.after_state.units
                or self.range_id not in self.watcher.range_ids):
            raise ValueError("property change fact source is incomplete")
        before, before_reason = _watcher_property_value(self.before_state, self.before_state.units[self.unit_id], self.watcher, self.rules, self.status_instance_id)
        after, after_reason = _watcher_property_value(self.after_state, self.after_state.units[self.unit_id], self.watcher, self.rules, self.status_instance_id)
        if before_reason or after_reason or before != self.before or after != self.after:
            raise ValueError("property change fact must match its native state reads")

    @property
    def delta(self) -> float:
        return self.after - self.before

    def matches_event(self, event: GameEvent) -> bool:
        data = event.payload.get("ability_property_change_value") if isinstance(event.payload, dict) else None
        return bool(type(event) is GameEvent and event.ability_property_change_fact is self
            and event.event_id == self.event_id and event.source_id == self.event_source_id
            and event.target_id == self.event_target_id
            and (event.event_type, event.event_id, event.source_id, event.target_id, event.window, event.process_only) == self._event_signature
            and isinstance(data, dict)
            and data == {"before": self.before, "after": self.after, "delta": self.delta,
                         "watcher_id": self.watcher.watcher_id, "range_id": self.range_id, "unit_id": self.unit_id})



@dataclass(frozen=True)
class AbilityPropertyWatcherResult:
    ok: bool
    after_state: BattleState
    mutations: tuple[Mutation, ...] = ()
    events: tuple[GameEvent, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    errors: tuple[str, ...] = ()
    node_results: tuple[ExecutionNodeResult, ...] = ()
    task_graph_projections: tuple[TaskGraphNodeProjection, ...] = ()
    dispatched_event_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        dispatched = frozenset(self.dispatched_event_ids)
        if any(type(event_id) is not str or not event_id for event_id in dispatched):
            raise ValueError("ability property watcher dispatched event identities are invalid")
        if not self.ok and dispatched:
            raise ValueError("blocked ability property watcher leaks dispatched events")
        object.__setattr__(self, "dispatched_event_ids", dispatched)
        projections = tuple(self.task_graph_projections)
        if any(type(item) is not TaskGraphNodeProjection for item in projections):
            raise TypeError("ability property watcher task graph projections are invalid")
        if not self.ok and projections:
            raise ValueError("blocked ability property watcher leaks task graph projections")
        object.__setattr__(self, "task_graph_projections", projections)


class AbilityPropertyWatcherSystem:
    """Reconciles source-backed property ranges after committed state changes."""

    def __init__(
        self,
        rules: RuleBook,
        *,
        status_callbacks: StatusCallbackSystem,
        reducer: MutationReducer | None = None,
    ) -> None:
        self.rules = rules
        self.status_callbacks = status_callbacks
        self.reducer = reducer or MutationReducer()
        self.evaluator = RuleEvaluator()

    def reconcile(
        self,
        state: BattleState,
        *,
        unit_ids: tuple[str, ...],
        trigger_event: GameEvent,
        task_graph_continuation: TaskGraphContinuation | None = None,
        nested_ability_hooks: TaskGraphExecutionHooks | None = None,
        before_state: BattleState | None = None,
    ) -> AbilityPropertyWatcherResult:
        original_state = state
        current_state = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        records: list[dict[str, JSONValue]] = []
        nodes: list[ExecutionNodeResult] = []
        projections: list[TaskGraphNodeProjection] = []
        dispatched_event_ids: set[str] = set()

        for unit_id in tuple(dict.fromkeys(unit_ids)):
            result = self._reconcile_unit(
                current_state,
                unit_id=unit_id,
                trigger_event=trigger_event,
                task_graph_continuation=task_graph_continuation,
                nested_ability_hooks=nested_ability_hooks,
                before_state=before_state,
            )
            if not result.ok:
                return AbilityPropertyWatcherResult(
                    ok=False,
                    after_state=original_state,
                    records=result.records,
                    errors=result.errors,
                    node_results=result.node_results,
                )
            current_state = result.after_state
            mutations.extend(result.mutations)
            events.extend(result.events)
            rng_events.extend(result.rng_events)
            records.extend(result.records)
            nodes.extend(result.node_results)
            projections.extend(result.task_graph_projections)
            dispatched_event_ids.update(result.dispatched_event_ids)
        return AbilityPropertyWatcherResult(
            ok=True,
            after_state=current_state,
            mutations=tuple(mutations),
            events=tuple(events),
            rng_events=tuple(rng_events),
            records=tuple(records),
            node_results=tuple(nodes),
            task_graph_projections=tuple(projections),
            dispatched_event_ids=frozenset(dispatched_event_ids),
        )

    def _reconcile_unit(
        self,
        state: BattleState,
        *,
        unit_id: str,
        trigger_event: GameEvent,
        task_graph_continuation: TaskGraphContinuation | None,
        nested_ability_hooks: TaskGraphExecutionHooks | None,
        before_state: BattleState | None = None,
    ) -> AbilityPropertyWatcherResult:
        unit = state.units.get(unit_id)
        if unit is None:
            return _blocked(state, "ability_property_watcher_unit_missing")
        details = _status_details(unit.flags)
        current_state = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        records: list[dict[str, JSONValue]] = []
        nodes: list[ExecutionNodeResult] = []
        projections: list[TaskGraphNodeProjection] = []
        removed_watcher_instance_ids: set[str] = set()
        dispatched_event_ids: set[str] = set()

        for original_detail in details:
            instance_id = str(original_detail.get("instance_id") or "")
            modifier_name = str(original_detail.get("modifier_name") or "")
            watcher_ids, watcher_identity_reason = _attached_watcher_ids(
                original_detail
            )
            if watcher_identity_reason:
                return _blocked(state, watcher_identity_reason)
            if not watcher_ids:
                continue
            current_detail = _status_detail_by_instance(
                current_state,
                unit_id,
                instance_id,
            )
            if current_detail is None:
                if instance_id in removed_watcher_instance_ids:
                    continue
                return _blocked(
                    state,
                    "ability_property_watcher_status_instance_missing",
                )
            current_watcher_ids, watcher_identity_reason = _attached_watcher_ids(
                current_detail
            )
            if (
                watcher_identity_reason
                or current_watcher_ids != watcher_ids
            ):
                return _blocked(
                    state,
                    watcher_identity_reason
                    or "ability_property_watcher_instance_identity_mismatch",
                )
            watchers = tuple(
                self.rules.ability_property_watcher(watcher_id)
                for watcher_id in watcher_ids
            )
            if any(watcher is None for watcher in watchers) or any(
                watcher is not None
                and watcher.modifier_name != modifier_name
                for watcher in watchers
            ):
                return _blocked(
                    state,
                    "ability_property_watcher_instance_identity_mismatch",
                )
            raw_state = current_detail.get(WATCHER_STATE_FIELD)
            if raw_state is None:
                watcher_state: dict[str, list[str]] = {}
                state_initialized = False
            elif isinstance(raw_state, dict):
                watcher_state = {
                    str(key): [str(item) for item in value]
                    for key, value in raw_state.items()
                    if isinstance(key, str)
                    and isinstance(value, (list, tuple))
                    and all(isinstance(item, str) for item in value)
                }
                if len(watcher_state) != len(raw_state):
                    return _blocked(
                        state,
                        "ability_property_watcher_state_invalid",
                    )
                if set(watcher_state) != set(watcher_ids):
                    return _blocked(
                        state,
                        "ability_property_watcher_state_identity_incomplete",
                    )
                state_initialized = True
            else:
                return _blocked(state, "ability_property_watcher_state_invalid")

            next_state = dict(watcher_state)
            instance_removed = False
            for watcher in watchers:
                assert watcher is not None
                if watcher.property_source.endswith("_dynamic_value") and state_initialized:
                    fact = trigger_event.dynamic_value_change_fact if trigger_event else None
                    # The dedicated producer owns this change. Parent HP/action
                    # notifications must not replay a nested dynamic callback.
                    bound_hashes = {str(key) for item in self.rules.ability_property_ranges_for_watcher(watcher.watcher_id)
                                    for bound in (item.minimum, item.maximum) for key in numeric_dynamic_hashes(bound)}
                    if (fact is None or trigger_event.event_type != "dynamic.value.changed"
                            or str(fact.plan.operation.destination_hash) not in {watcher.property_name, *bound_hashes}):
                        continue
                    value_owner = (str(current_detail.get("caster_id") or "")
                                   if watcher.property_source == "caster_dynamic_value" else unit_id)
                    if fact.plan.resolved_scope.get("target_id") != value_owner:
                        continue
                    if (watcher.property_source == "status_dynamic_value"
                            and fact.plan.resolved_scope.get("scope_kind") == "status"
                            and fact.plan.resolved_scope.get("status_instance_id") != instance_id):
                        continue
                if watcher.coverage_status != "executable":
                    return _blocked(
                        state,
                        watcher.blocked_reason
                        or "ability_property_watcher_not_executable",
                    )
                property_read_state = current_state
                property_value, value_reason = _watcher_property_value(
                    property_read_state,
                    current_state.units[unit_id],
                    watcher, self.rules, instance_id,
                )
                if value_reason:
                    return _blocked(state, value_reason)
                if property_value is None:
                    return _blocked(
                        state,
                        f"ability_property_value_missing:{watcher.property_name}",
                    )
                ranges = self.rules.ability_property_ranges_for_watcher(
                    watcher.watcher_id
                )
                if (
                    not ranges
                    or tuple(item.range_id for item in ranges)
                    != watcher.range_ids
                ):
                    return _blocked(
                        state,
                        "ability_property_watcher_range_identity_mismatch",
                    )
                active_ids: list[str] = []
                for property_range in ranges:
                    member, reason = self._range_contains(
                        current_state,
                        current_detail,
                        property_range,
                        property_value,
                    )
                    if reason:
                        return _blocked(state, reason)
                    if member:
                        active_ids.append(property_range.range_id)

                changed_range_ids: list[str] = []
                if before_state is not None and active_ids:
                    previous_unit = before_state.units.get(unit_id)
                    if previous_unit is not None and _status_detail_by_instance(before_state, unit_id, instance_id) is not None:
                        previous_value, previous_reason = (
                            _watcher_property_value(
                                before_state,
                                previous_unit,
                                watcher, self.rules, instance_id,
                            )
                        )
                        if previous_reason:
                            return _blocked(state, previous_reason)
                        if (
                            previous_value is not None
                            and previous_value != property_value
                        ):
                            changed_range_ids = [
                                property_range.range_id
                                for property_range in ranges
                                if property_range.change_callback_id
                                and property_range.range_id in active_ids
                            ]
                prior_ids = next_state.get(watcher.watcher_id)
                if prior_ids is not None:
                    known_ids = set(watcher.range_ids)
                    canonical_prior_ids = [
                        range_id
                        for range_id in watcher.range_ids
                        if range_id in set(prior_ids)
                    ]
                    if (
                        len(prior_ids) != len(set(prior_ids))
                        or any(item not in known_ids for item in prior_ids)
                        or prior_ids != canonical_prior_ids
                    ):
                        return _blocked(
                            state,
                            "ability_property_watcher_state_range_invalid",
                        )
                    exits = tuple(item for item in prior_ids if item not in active_ids)
                    enters = tuple(item for item in active_ids if item not in prior_ids)
                    for range_id, branch in (
                        *((item, "exit") for item in exits),
                        *((item, "enter") for item in enters),
                        *((item, "change") for item in changed_range_ids),
                    ):
                        property_range = self.rules.ability_property_range(
                            range_id
                        )
                        if property_range is None:
                            return _blocked(
                                state,
                                "ability_property_range_identity_missing",
                            )
                        callback_id = (
                            property_range.exit_callback_id
                            if branch == "exit"
                            else property_range.change_callback_id
                            if branch == "change"
                            else property_range.enter_callback_id
                        )
                        if not callback_id:
                            continue
                        current_detail = _status_detail_by_instance(
                            current_state,
                            unit_id,
                            instance_id,
                        )
                        if current_detail is None:
                            return _blocked(
                                state,
                                "ability_property_watcher_status_instance_missing",
                            )
                        callback_trigger_event = trigger_event
                        if branch == "change" and trigger_event is not None:
                            change_payload = (
                                dict(trigger_event.payload)
                                if isinstance(trigger_event.payload, dict)
                                else {}
                            )
                            change_payload["ability_property_change_value"] = {
                                "before": previous_value,
                                "after": property_value,
                                "delta": property_value - previous_value,
                                "watcher_id": watcher.watcher_id,
                                "range_id": property_range.range_id,
                                "unit_id": unit_id,
                            }
                            issued = (id(before_state), id(property_read_state), id(watcher), property_range.range_id,
                                      unit_id, previous_value, property_value, trigger_event.event_id,
                                      trigger_event.source_id, trigger_event.target_id,
                                      (trigger_event.event_type, trigger_event.event_id, trigger_event.source_id,
                                       trigger_event.target_id, trigger_event.window, trigger_event.process_only), instance_id, id(self.rules))
                            property_fact = AbilityPropertyChangeFact(before_state, property_read_state, watcher,
                                property_range.range_id, unit_id, previous_value, property_value,
                                trigger_event.event_id, trigger_event.source_id, trigger_event.target_id,
                                _PROPERTY_CHANGE_PRODUCER, issued, (trigger_event.event_type, trigger_event.event_id,
                                    trigger_event.source_id, trigger_event.target_id, trigger_event.window, trigger_event.process_only), instance_id, self.rules)
                            callback_trigger_event = replace(
                                trigger_event, payload=change_payload, ability_property_change_fact=property_fact,
                            )
                        callback_result = (
                            self.status_callbacks.execute_callback_id(
                                current_state,
                                callback_id=callback_id,
                                watcher_id=watcher.watcher_id,
                                range_id=property_range.range_id,
                                branch=branch,
                                unit_id=unit_id,
                                modifier_name=modifier_name,
                                trigger_event=callback_trigger_event,
                                detail_override=current_detail,
                                task_graph_continuation=task_graph_continuation,
                                nested_ability_hooks=nested_ability_hooks,
                            )
                        )
                        if not callback_result.ok:
                            return _callback_blocked(
                                state,
                                callback_result,
                            )
                        current_state = callback_result.after_state
                        mutations.extend(callback_result.mutations)
                        events.extend(callback_result.events)
                        rng_events.extend(callback_result.rng_events)
                        records.extend(callback_result.records)
                        nodes.extend(callback_result.node_results)
                        projections.extend(
                            callback_result.task_graph_projections
                        )
                        dispatched_event_ids.update(callback_result.dispatched_event_ids)
                        removed_watcher_instance_ids.update(
                            _formally_removed_status_instance_ids(
                                callback_result.mutations,
                                callback_result.events,
                                unit_id=unit_id,
                            )
                        )
                        if instance_id in removed_watcher_instance_ids:
                            instance_removed = True
                            break
                    if instance_removed:
                        break
                next_state[watcher.watcher_id] = active_ids

            if instance_removed:
                continue
            current_detail = _status_detail_by_instance(
                current_state,
                unit_id,
                instance_id,
            )
            if current_detail is None:
                return _blocked(
                    state,
                    "ability_property_watcher_status_instance_missing",
                )
            if not state_initialized or next_state != watcher_state:
                state_mutation = _watcher_state_mutation(
                    current_state,
                    unit_id=unit_id,
                    instance_id=instance_id,
                    next_state=next_state,
                    trigger_event=trigger_event,
                    watcher_sources=tuple(
                        watcher.source.to_json()
                        for watcher in watchers
                        if watcher is not None
                    ),
                )
                if state_mutation is None:
                    return _blocked(
                        state,
                        "ability_property_watcher_state_update_failed",
                    )
                current_state = self.reducer.apply(current_state, state_mutation)
                mutations.append(state_mutation)
                records.append(
                    SettlementRecord(
                        record_type="ability_property_watcher_state",
                        source="ability_property_watcher_system",
                        mutation_id=state_mutation.stable_id(),
                        process_only=False,
                        payload={
                            "unit_id": unit_id,
                            "status_instance_id": instance_id,
                            "watcher_ids": list(watcher_ids),
                            "watcher_state": next_state,
                            "baseline_only": not state_initialized,
                        },
                        trace={
                            "trigger_event_id": trigger_event.to_json()[
                                "event_id"
                            ],
                            "watcher_sources": [
                                watcher.source.to_json()
                                for watcher in watchers
                                if watcher is not None
                            ],
                        },
                    ).to_json()
                )
                nodes.append(
                    ExecutionNodeResult(
                        node_kind="ability_property_watcher",
                        node_id=instance_id,
                        status="complete",
                    )
                )
        return AbilityPropertyWatcherResult(
            ok=True,
            after_state=current_state,
            mutations=tuple(mutations),
            events=tuple(events),
            rng_events=tuple(rng_events),
            records=tuple(records),
            node_results=tuple(nodes),
            task_graph_projections=tuple(projections),
            dispatched_event_ids=frozenset(dispatched_event_ids),
        )

    def _range_contains(
        self,
        state: BattleState,
        detail: dict[str, JSONValue],
        property_range: AbilityPropertyRangeIR,
        value: float,
    ) -> tuple[bool, str]:
        if property_range.coverage_status != "executable":
            return False, (
                property_range.blocked_reason
                or "ability_property_range_not_executable"
            )
        dynamic_values = {}
        # Constant bounds need no status/store bindings. Building that context
        # on every HP/event notification otherwise copies the whole party's sources.
        bindings = (() if all(bound is None or bound.get("kind") == "fixed"
                              for bound in (property_range.minimum, property_range.maximum))
                    else _condition_context(self.rules, state, detail, None).binding_sources)
        minimum, reason = self._bound_value(
            property_range.minimum,
            dynamic_values,
            bindings,
            property_range,
            "minimum",
        )
        if reason:
            return False, reason
        maximum, reason = self._bound_value(
            property_range.maximum,
            dynamic_values,
            bindings,
            property_range,
            "maximum",
        )
        if reason:
            return False, reason
        above_minimum = (
            minimum is None
            or value > minimum
            or (property_range.minimum_inclusive and value == minimum)
        )
        below_maximum = (
            maximum is None
            or value < maximum
            or (property_range.maximum_inclusive and value == maximum)
        )
        return above_minimum and below_maximum, ""

    def _bound_value(
        self,
        expression: dict[str, JSONValue] | None,
        dynamic_values: dict[str, float],
        binding_sources: tuple[dict[str, JSONValue], ...],
        property_range: AbilityPropertyRangeIR,
        bound_name: str,
    ) -> tuple[float | None, str]:
        if expression is None:
            return None, ""
        result = self.evaluator.evaluate_numeric(
            expression,
            NumericEvaluationContext(
                dynamic_values=dynamic_values,
                binding_sources=binding_sources,
                source_trace={
                    "ability_property_range": property_range.source.to_json(),
                    "bound": bound_name,
                },
            ),
        )
        if not result.ok or result.value is None:
            return None, (
                result.blocked_reason
                or f"ability_property_range_{bound_name}_evaluation_failed"
            )
        return float(result.value), ""


def _watcher_property_value(
    state: BattleState,
    unit: object,
    watcher: object,
    rules: RuleBook | None = None,
    instance_id: str = "",
) -> tuple[float | None, str]:
    """Resolve a watcher's formal value source without adjacent fallbacks."""

    source = str(getattr(watcher, "property_source", "unit_property") or "")
    if source == "unit_property":
        return ability_property_value(unit, getattr(watcher, "property_name", "")), ""
    if source == "elation_base_points":
        from .elation import elation_base_points

        try:
            return elation_base_points(state), ""
        except (TypeError, ValueError) as exc:
            return None, str(exc)
    if source in {"owner_dynamic_value", "caster_dynamic_value", "status_dynamic_value"}:
        detail = _status_detail_by_instance(state, unit.unit_id, instance_id)
        if detail is None or rules is None:
            return None, "dynamic_watcher_status_instance_missing"
        owner_id = str(detail.get("caster_id") or "") if source == "caster_dynamic_value" else unit.unit_id
        if owner_id not in state.units:
            return None, "dynamic_watcher_value_owner_missing"
        key = watcher.property_name
        local = source == "status_dynamic_value"
        stored = binding_source_from_store(store_from_state(state), visible_scope={
            "target_id": owner_id, "status_instance_id": instance_id if local else "",
        })
        sources = [stored]
        if key not in stored.get("by_hash", {}):
            baseline = (binding_source_from_status_detail(detail, detail.get("dynamic_values")) if local else
                character_declared_dynamic_binding_source(rules, state, owner_id)
                or servant_declared_dynamic_binding_source(rules, state, owner_id))
            if baseline:
                sources.append(baseline)
        result = RuleEvaluator().evaluate_numeric(numeric_dynamic_hash(key),
            NumericEvaluationContext(binding_sources=tuple(sources)))
        return (float(result.value), "") if result.ok and result.value is not None else (None, result.blocked_reason)
    return None, f"ability_property_watcher_source_not_admitted:{source or 'missing'}"


def _watcher_state_mutation(
    state: BattleState,
    *,
    unit_id: str,
    instance_id: str,
    next_state: dict[str, list[str]],
    trigger_event: GameEvent,
    watcher_sources: tuple[dict[str, JSONValue], ...],
) -> Mutation | None:
    unit = state.units.get(unit_id)
    if unit is None:
        return None
    before_details = _status_details(unit.flags)
    after_details: list[dict[str, JSONValue]] = []
    found = False
    for detail in before_details:
        if str(detail.get("instance_id") or "") != instance_id:
            after_details.append(dict(detail))
            continue
        found = True
        after_details.append(
            {
                **detail,
                WATCHER_STATE_FIELD: {
                    key: list(value)
                    for key, value in sorted(next_state.items())
                },
            }
        )
    if not found:
        return None
    return Mutation(
        op="set",
        path=("units", unit_id, "flags", "status_details"),
        before=before_details if "status_details" in unit.flags else None,
        after=after_details,
        reason="reconcile source-backed ability property watcher state",
        source="ability_property_watcher_system",
        before_exists="status_details" in unit.flags,
        metadata={
            "unit_id": unit_id,
            "status_instance_id": instance_id,
            "trigger_event_id": trigger_event.to_json()["event_id"],
            "watcher_ids": sorted(next_state),
            "watcher_state": next_state,
            "source_trace": {
                "watcher_sources": list(watcher_sources),
            },
        },
    )


def _status_detail_by_instance(
    state: BattleState,
    unit_id: str,
    instance_id: str,
) -> dict[str, JSONValue] | None:
    unit = state.units.get(unit_id)
    if unit is None:
        return None
    return next(
        (
            detail
            for detail in _status_details(unit.flags)
            if str(detail.get("instance_id") or "") == instance_id
        ),
        None,
    )


def _attached_watcher_ids(
    detail: dict[str, JSONValue],
) -> tuple[tuple[str, ...], str]:
    if "ability_property_watcher_ids" not in detail:
        return (), "ability_property_watcher_instance_identity_missing"
    raw_ids = detail.get("ability_property_watcher_ids")
    if not isinstance(raw_ids, (list, tuple)) or any(
        not isinstance(watcher_id, str) or not watcher_id
        for watcher_id in raw_ids
    ):
        return (), "ability_property_watcher_instance_identity_invalid"
    watcher_ids = tuple(raw_ids)
    if (
        len(watcher_ids) != len(set(watcher_ids))
        or watcher_ids != tuple(sorted(watcher_ids))
    ):
        return (), "ability_property_watcher_instance_identity_invalid"
    return watcher_ids, ""


def _formally_removed_status_instance_ids(
    mutations: tuple[Mutation, ...],
    events: tuple[GameEvent, ...],
    *,
    unit_id: str,
) -> set[str]:
    remove_operations = {"remove", "expire", "dispel", "stack_reduce_remove"}
    removed: set[str] = set()
    lifecycle_events = tuple(
        event
        for event in events
        if event.event_type == "status.lifecycle"
        and event.target_id == unit_id
        and event.payload.get("lifecycle_operation") in remove_operations
    )
    for mutation in mutations:
        if mutation.path != (
            "units",
            unit_id,
            "flags",
            "status_details",
        ):
            continue
        operation = mutation.metadata.get("operation")
        lifecycle_plan = mutation.metadata.get("lifecycle_plan")
        existing_detail = (
            lifecycle_plan.get("existing_detail")
            if isinstance(lifecycle_plan, dict)
            else None
        )
        instance_id = (
            str(existing_detail.get("instance_id") or "")
            if isinstance(existing_detail, dict)
            else ""
        )
        mutation_id = mutation.stable_id()
        if (
            operation not in remove_operations
            or not instance_id
            or not any(
                event.payload.get("status_instance_id") == instance_id
                and mutation_id in tuple(event.payload.get("mutation_ids") or ())
                for event in lifecycle_events
            )
        ):
            continue
        removed.add(instance_id)
    return removed


def _status_details(
    flags: dict[str, JSONValue],
) -> tuple[dict[str, JSONValue], ...]:
    details = flags.get("status_details", ())
    if not isinstance(details, (list, tuple)):
        return ()
    return tuple(detail for detail in details if isinstance(detail, dict))


def _numeric_bindings(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, float] = {}
    for key, item in value.items():
        if (
            not str(key).startswith("__")
            and isinstance(item, (int, float))
            and not isinstance(item, bool)
        ):
            result[str(key)] = float(item)
    for index_key in ("__by_name", "__by_hash"):
        indexed = value.get(index_key)
        if not isinstance(indexed, dict):
            continue
        for key, item in indexed.items():
            if isinstance(item, (int, float)) and not isinstance(item, bool):
                result[str(key)] = float(item)
    return result


def _callback_blocked(
    state: BattleState,
    result: StatusCallbackExecutionResult,
) -> AbilityPropertyWatcherResult:
    return AbilityPropertyWatcherResult(
        ok=False,
        after_state=state,
        records=result.records,
        errors=result.errors or ("ability_property_watcher_callback_failed",),
        node_results=result.node_results,
    )


def _blocked(
    state: BattleState,
    reason: str,
) -> AbilityPropertyWatcherResult:
    return AbilityPropertyWatcherResult(
        ok=False,
        after_state=state,
        records=(
            SettlementRecord(
                record_type="ability_property_watcher_blocked",
                source="ability_property_watcher_system",
                process_only=True,
                payload={"reason": reason},
                trace={},
            ).to_json(),
        ),
        errors=(reason,),
        node_results=(
            ExecutionNodeResult(
                node_kind="ability_property_watcher",
                node_id=reason,
                status="blocked",
                reason_code=reason,
            ),
        ),
    )
