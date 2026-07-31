from __future__ import annotations

from dataclasses import dataclass

from ..core.model import BattleState, GameEvent, JSONValue, Mutation, RNGEvent
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..core.transition_outcome import ExecutionNodeResult
from ..rules.evaluator import NumericEvaluationContext, RuleEvaluator
from ..rules.ir import AbilityPropertyRangeIR
from ..rules.rulebook import RuleBook
from .dynamic_values import status_binding_sources
from .status_callbacks import StatusCallbackExecutionResult, StatusCallbackSystem
from .unit_stats import ability_property_value


WATCHER_STATE_FIELD = "ability_property_watcher_state"


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
    ) -> AbilityPropertyWatcherResult:
        original_state = state
        current_state = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        records: list[dict[str, JSONValue]] = []
        nodes: list[ExecutionNodeResult] = []

        for unit_id in tuple(dict.fromkeys(unit_ids)):
            result = self._reconcile_unit(
                current_state,
                unit_id=unit_id,
                trigger_event=trigger_event,
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
        return AbilityPropertyWatcherResult(
            ok=True,
            after_state=current_state,
            mutations=tuple(mutations),
            events=tuple(events),
            rng_events=tuple(rng_events),
            records=tuple(records),
            node_results=tuple(nodes),
        )

    def _reconcile_unit(
        self,
        state: BattleState,
        *,
        unit_id: str,
        trigger_event: GameEvent,
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
        removed_watcher_instance_ids: set[str] = set()

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
                if watcher.coverage_status != "executable":
                    return _blocked(
                        state,
                        watcher.blocked_reason
                        or "ability_property_watcher_not_executable",
                    )
                property_value = ability_property_value(
                    current_state.units[unit_id],
                    watcher.property_name,
                )
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
                        callback_result = (
                            self.status_callbacks.execute_callback_id(
                                current_state,
                                callback_id=callback_id,
                                watcher_id=watcher.watcher_id,
                                range_id=property_range.range_id,
                                branch=branch,
                                unit_id=unit_id,
                                modifier_name=modifier_name,
                                trigger_event=trigger_event,
                                detail_override=current_detail,
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
        dynamic_values = _numeric_bindings(detail.get("dynamic_values"))
        bindings = status_binding_sources(
            state,
            (str(detail.get("owner_id") or ""),),
        )
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
