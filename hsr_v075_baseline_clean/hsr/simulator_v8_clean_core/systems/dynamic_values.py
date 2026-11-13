from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..core.audit_policy import eager_identity_audit_enabled
from ..core.model import battle_state_full_fingerprint as dynamic_value_state_fingerprint
from ..core.model import BattleState, GameEvent, JSONValue, Mutation, TargetResolution, current_max_hp
from ..core.settlement import SettlementRecord
from ..immutable_json import FrozenJSONDict, freeze_json, json_tree_digest, thaw_json
from ..rules.expression_ir import DynamicValueOperationIR, NumericOperandIR
from ..rules.rulebook import RuleBook
from ..rules.value_binding import resolve_runtime_numeric_expression
from .unit_lifecycle import UnitLifecycleSystem
from .unit_stats import ability_property_value
from .task_graph import TaskGraphStatusScope

if TYPE_CHECKING:
    from .status import StatusLifecyclePlan
    from .action_event_contract import AdmittedActionTargetFact, ActionWindowExpectedScope


DYNAMIC_VALUE_PLAN_SCHEMA = "hsr.dynamic_value_plan.v1"

_DYNAMIC_VALUE_SCOPE_CONTRACTS = {
    "unit": ("unit", "combat"),
    "ContextCaster": ("unit", "combat"),
    "ContextOwner": ("unit", "combat"),
    "TargetEntity": ("unit", "combat"),
    "ability": ("ability", "ability_action"),
    "ContextAbility": ("ability", "ability_action"),
    "ContextTaskTemplate": ("ability", "ability_action"),
    "status": ("status", "status_instance"),
    "modifier_local": ("status", "status_instance"),
    "ContextModifier": ("status", "status_instance"),
    "event": ("event", "event"),
    # AI tags are enemy-AI metadata.  The project does not implement enemy AI,
    # but source callbacks still read and write these names as initialize-once
    # guards.  They live in the unit's combat namespace and never feed damage,
    # resource or lifecycle decisions.
    "AITag": ("unit", "combat"),
}


@dataclass(frozen=True)
class DynamicValueExecutionRequest:
    caster_id: str
    source_id: str
    effect_id: str
    opcode: str
    owner_id: str = ""
    param_entity_id: str = ""
    current_action_target_id: str = ""
    ability_instance_id: str = ""
    status_instance_id: str = ""
    event_id: str = ""
    operation_event_id: str = ""
    task_id: str = ""
    status_modifier_name: str = ""
    status_id: str = ""
    status_source_id: str = ""
    binding_sources: tuple[Mapping[str, Any], ...] = ()
    status_lifecycle_plan: StatusLifecyclePlan | None = None
    param_status_scope: TaskGraphStatusScope | None = None
    template_target_ids: tuple[str, ...] | None = None
    # Process-only effect event fact for operands typed as event_value.  The
    # caller (effect system) forwards the trigger event payload verbatim; no
    # log, snapshot export or adjacent field may stand in for it.
    event_payload: Mapping[str, Any] | None = None
    # Typed producer fact for an admitted heal mutation.  The transport payload
    # above is only a convenience copy; the fact is the authority.
    heal_event_fact: HealEventFact | None = None
    trigger_event: GameEvent | None = None
    target_resolution: TargetResolution | None = None
    admitted_action_target_fact: AdmittedActionTargetFact | None = None
    expected_action_window_scope: ActionWindowExpectedScope | None = None

    def __post_init__(self) -> None:
        for field_name in ("caster_id", "source_id", "effect_id", "opcode"):
            if not isinstance(getattr(self, field_name), str) or not getattr(
                self, field_name
            ):
                raise ValueError(f"dynamic value request {field_name} is required")
        for field_name in (
            "owner_id",
            "param_entity_id",
            "current_action_target_id",
            "ability_instance_id",
            "status_instance_id",
            "event_id",
            "operation_event_id",
            "task_id",
            "status_modifier_name",
            "status_id",
            "status_source_id",
        ):
            if not isinstance(getattr(self, field_name), str):
                raise TypeError(f"dynamic value request {field_name} must be a string")
        if not isinstance(self.binding_sources, tuple):
            raise TypeError("dynamic value binding sources must be a tuple")
        if any(not isinstance(source, Mapping) for source in self.binding_sources):
            raise TypeError("dynamic value binding sources must be objects")
        sources = tuple(freeze_json(dict(source)) for source in self.binding_sources)
        if not all(isinstance(source, dict) for source in sources):
            raise TypeError("dynamic value binding sources must be objects")
        object.__setattr__(self, "binding_sources", sources)
        if self.param_status_scope is not None and type(self.param_status_scope) is not TaskGraphStatusScope:
            raise TypeError("dynamic value parameter status scope is invalid")
        if self.template_target_ids is not None and (
            not isinstance(self.template_target_ids, tuple)
            or any(not isinstance(value, str) or not value for value in self.template_target_ids)
            or len(self.template_target_ids) != len(set(self.template_target_ids))
        ):
            raise ValueError("dynamic value template target identities are invalid")
        if self.event_payload is not None:
            if not isinstance(self.event_payload, Mapping):
                raise TypeError("dynamic value event payload must be an object")
            try:
                frozen_payload = freeze_json(dict(self.event_payload))
            except (TypeError, ValueError):
                # A non-JSON payload cannot be an event fact; leave it absent so
                # an event_value operand fails closed instead of storing a value.
                frozen_payload = None
            object.__setattr__(self, "event_payload", frozen_payload)
        if self.trigger_event is not None and type(self.trigger_event) is not GameEvent:
            raise TypeError("dynamic value trigger event must be a native GameEvent")
        if self.heal_event_fact is not None:
            from .mutation_events import HealEventFact as _HealEventFact

            if type(self.heal_event_fact) is not _HealEventFact:
                raise TypeError("dynamic value heal event fact must be typed")

    def to_json(self, *, detach: bool = True) -> dict[str, JSONValue]:
        return {
            "caster_id": self.caster_id,
            "source_id": self.source_id,
            "effect_id": self.effect_id,
            "opcode": self.opcode,
            "owner_id": self.owner_id,
            "param_entity_id": self.param_entity_id,
            "current_action_target_id": self.current_action_target_id,
            "ability_instance_id": self.ability_instance_id,
            "status_instance_id": self.status_instance_id,
            "event_id": self.event_id,
            "operation_event_id": self.operation_event_id,
            "task_id": self.task_id,
            "status_modifier_name": self.status_modifier_name,
            "status_id": self.status_id,
            "status_source_id": self.status_source_id,
            "binding_sources": [thaw_json(source) if detach else source for source in self.binding_sources],
            "status_lifecycle_plan": self.status_lifecycle_plan.to_json() if self.status_lifecycle_plan else None,
            "param_status_scope": ({"owner_id": self.param_status_scope.owner_id,
                                    "instance_id": self.param_status_scope.instance_id}
                                   if self.param_status_scope else None),
            "template_target_ids": list(self.template_target_ids) if self.template_target_ids is not None else None,
            "event_payload": (
                (thaw_json(self.event_payload) if detach else self.event_payload)
                if self.event_payload is not None
                else None
            ),
        }


@dataclass(frozen=True)
class DynamicValuePlan:
    ok: bool
    plan_id: str
    operation: DynamicValueOperationIR
    request: DynamicValueExecutionRequest | None
    operation_instance_id: str
    before_state_fingerprint: str
    resolved_scope: Mapping[str, Any]
    result_value: float | None
    mutations: tuple[Mutation, ...] = ()
    records: tuple[Mapping[str, Any], ...] = ()
    evaluation: Mapping[str, Any] | None = None
    blocked_reason: str = ""
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.ok, bool) or not isinstance(self.replayed, bool):
            raise TypeError("dynamic value plan flags must be boolean")
        if type(self.operation) is not DynamicValueOperationIR:
            raise TypeError("dynamic value plan requires an exact operation")
        if self.request is not None and type(self.request) is not DynamicValueExecutionRequest:
            raise TypeError("dynamic value plan request must be exact")
        if (
            not isinstance(self.plan_id, str)
            or not self.plan_id
            or not isinstance(self.before_state_fingerprint, str)
            or not self.before_state_fingerprint
            or not isinstance(self.operation_instance_id, str)
            or not isinstance(self.blocked_reason, str)
        ):
            raise ValueError("dynamic value plan identity is incomplete")
        if not isinstance(self.resolved_scope, Mapping):
            raise TypeError("dynamic value plan scope must be an object")
        if not isinstance(self.mutations, tuple) or any(
            type(mutation) is not Mutation for mutation in self.mutations
        ):
            raise TypeError("dynamic value plan mutations must be an exact tuple")
        if not isinstance(self.records, tuple) or any(
            not isinstance(record, Mapping) for record in self.records
        ):
            raise TypeError("dynamic value plan records must be an object tuple")
        if self.evaluation is not None and not isinstance(self.evaluation, Mapping):
            raise TypeError("dynamic value plan evaluation must be an object or null")
        if self.result_value is not None and not _finite_number(self.result_value):
            raise ValueError("dynamic value plan result must be finite")
        scope = freeze_json(dict(self.resolved_scope))
        records = tuple(freeze_json(dict(record)) for record in self.records)
        evaluation = (
            freeze_json(dict(self.evaluation))
            if isinstance(self.evaluation, Mapping)
            else None
        )
        if self.ok:
            if self.blocked_reason:
                raise ValueError("successful dynamic value plan has a blocker")
            if not self.operation_instance_id:
                raise ValueError("successful dynamic value plan has no operation identity")
            if self.request is None:
                raise ValueError("successful dynamic value plan has no request")
            if not self.replayed and (self.result_value is None or not self.mutations):
                raise ValueError("successful dynamic value plan has no write")
        elif not self.blocked_reason or self.mutations or self.records:
            raise ValueError("blocked dynamic value plan must be side-effect free")
        object.__setattr__(self, "resolved_scope", scope)
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "evaluation", evaluation)
        _validate_resolved_scope(scope, allow_empty=not self.ok)
        # Eager identity rehashing is switchable audit (2026-11-10 correction):
        # the sole producer derives plan_id from these exact fields, and replay
        # still compares it. Default off keeps the hot path free of audit cost.
        if eager_identity_audit_enabled() and self.plan_id != _dynamic_value_plan_id(self):
            raise ValueError("dynamic value plan identity is inconsistent")

    def to_json(self, *, detach: bool = True) -> dict[str, JSONValue]:
        return {
            "schema_version": DYNAMIC_VALUE_PLAN_SCHEMA,
            "ok": self.ok,
            "plan_id": self.plan_id,
            "operation": self.operation.to_json(),
            "request": self.request.to_json(detach=detach) if self.request is not None else None,
            "operation_instance_id": self.operation_instance_id,
            "before_state_fingerprint": self.before_state_fingerprint,
            "resolved_scope": thaw_json(self.resolved_scope) if detach else self.resolved_scope,
            "result_value": self.result_value,
            "mutations": [mutation.to_json(detach=detach) for mutation in self.mutations],
            "records": [thaw_json(record) if detach else record for record in self.records],
            "evaluation": thaw_json(self.evaluation) if detach else self.evaluation,
            "blocked_reason": self.blocked_reason,
            "replayed": self.replayed,
        }


@dataclass(frozen=True)
class DynamicValueExecutionResult:
    ok: bool
    plan_id: str
    mutations: tuple[Mutation, ...] = ()
    records: tuple[Mapping[str, Any], ...] = ()
    blocked_reason: str = ""
    replayed: bool = False

    def __post_init__(self) -> None:
        records = tuple(freeze_json(dict(record)) for record in self.records)
        if self.ok and self.blocked_reason:
            raise ValueError("successful dynamic execution has a blocker")
        if not self.ok and (not self.blocked_reason or self.mutations or records):
            raise ValueError("blocked dynamic execution must be side-effect free")
        object.__setattr__(self, "records", records)


@dataclass(frozen=True)
class DynamicValueChangeFact:
    """The executed typed write and its pre-write state, retained for watchers."""
    plan: DynamicValuePlan
    before_state: BattleState
    event_id: str

    def matches_event(self, event: GameEvent) -> bool:
        return (type(self.plan) is DynamicValuePlan and self.plan.ok and not self.plan.replayed
            and type(self.before_state) is BattleState and self.plan.request is not None
            and event.dynamic_value_change_fact is self and event.event_type == "dynamic.value.changed"
            and event.event_id == self.event_id and event.source_id == self.plan.request.source_id
            and event.target_id == self.plan.resolved_scope.get("target_id"))


def dynamic_value_change_events(state: BattleState, plan: DynamicValuePlan, rules: RuleBook | None) -> tuple[GameEvent, ...]:
    # Only materialized watchers need notification; ordinary scratch writes stay cheap.
    from ..rules.expression_ir import numeric_dynamic_hashes
    if plan.replayed or rules is None or not any(
        item.coverage_status == "executable" and item.property_source.endswith("_dynamic_value") and str(plan.operation.destination_hash) in {
            item.property_name, *(str(key) for interval in rules.ability_property_ranges_for_watcher(item.watcher_id)
                for bound in (interval.minimum, interval.maximum) for key in numeric_dynamic_hashes(bound))}
        for item in rules.ir.ability_property_watchers
    ):
        return ()
    event_id = f"event:dynamic_value_changed:{plan.operation_instance_id}"
    fact = DynamicValueChangeFact(plan, state, event_id)
    return (GameEvent(event_type="dynamic.value.changed", source_id=plan.request.source_id,
        target_id=str(plan.resolved_scope["target_id"]), event_id=event_id, process_only=True,
        dynamic_value_change_fact=fact, payload={"operation_id": plan.operation.operation_id}),)


def empty_dynamic_value_store() -> dict[str, JSONValue]:
    return {"entries": {}, "by_hash": {}, "by_name": {}, "operation_ledger": {}}


def normalized_dynamic_value_store(value: object) -> dict[str, JSONValue]:
    if value is None:
        return empty_dynamic_value_store()
    return _strict_dynamic_value_store(value)


def store_from_state(state: BattleState) -> dict[str, JSONValue]:
    return normalized_dynamic_value_store(state.global_flags.get("dynamic_value_store"))


def remove_status_instance_entries(
    store: object,
    status_instance_id: str,
) -> dict[str, JSONValue] | None:
    """Drop status-scoped dynamic values once their status instance is gone.

    Status instance ids are deterministic source identities, so a later
    lifecycle of the same modifier can reuse the id. Leaving per-instance
    entries behind would let the new lifecycle read counters from the removed
    one. Only entries whose scope kind is ``status`` and whose instance id
    matches are pruned; unit/ability/event scoped entries are untouched.
    Returns ``None`` when nothing was pruned so callers emit no mutation.
    """
    if not isinstance(status_instance_id, str) or not status_instance_id:
        return None
    normalized = normalized_dynamic_value_store(store)
    entries = normalized.get("entries")
    if not isinstance(entries, dict):
        return None
    kept = {
        key: entry
        for key, entry in entries.items()
        if not (
            isinstance(entry, dict)
            and str(entry.get("scope_kind") or "") == "status"
            and str(entry.get("status_instance_id") or "") == status_instance_id
        )
    }
    if len(kept) == len(entries):
        return None
    ledger = normalized.get("operation_ledger")
    kept_ledger = (
        {
            key: item
            for key, item in ledger.items()
            if isinstance(item, dict) and item.get("destination_entry_key") in kept
        }
        if isinstance(ledger, dict)
        else {}
    )
    return _reindex(
        {
            "entries": kept,
            "operation_ledger": kept_ledger,
        }
    )


def remove_unit_entries(store: object, unit_id: str) -> dict[str, JSONValue] | None:
    """Retire only slots owned by or scoped to this departed unit, and their ledger."""
    if not isinstance(unit_id, str) or not unit_id:
        raise ValueError("dynamic cleanup requires a unit identity")
    normalized = normalized_dynamic_value_store(store)
    entries = normalized["entries"]
    kept = {key: entry for key, entry in entries.items()
            if entry.get("owner_id") != unit_id and entry.get("target_id") != unit_id}
    if len(kept) == len(entries):
        return None
    ledger = {key: item for key, item in normalized["operation_ledger"].items()
              if item.get("destination_entry_key") in kept}
    return _reindex({"entries": kept, "operation_ledger": ledger})


def binding_source_from_store(
    store: object,
    *,
    excluded_status_instance_ids: tuple[str, ...] = (),
    excluded_hashes: tuple[str, ...] = (),
    excluded_names: tuple[str, ...] = (),
    excluded_scopes: tuple[str, ...] = (),
    visible_scope: Mapping[str, Any] | None = None,
) -> dict[str, JSONValue]:
    normalized = normalized_dynamic_value_store(store)
    excluded = {item for item in excluded_status_instance_ids if item}
    excluded_hash_keys = {str(item) for item in excluded_hashes if str(item)}
    excluded_name_keys = {str(item) for item in excluded_names if str(item)}
    excluded_scope_keys = {str(item) for item in excluded_scopes if str(item)}
    if excluded or excluded_hash_keys or excluded_name_keys or excluded_scope_keys or visible_scope is not None:
        entries = normalized.get("entries")
        # Ponytail: scope lookup scans stored slots; add a scope index if long battles make it costly.
        filtered_entries = {
            key: entry
            for key, entry in (entries.items() if isinstance(entries, dict) else ())
            if not isinstance(entry, dict)
            or (
                str(entry.get("status_instance_id") or "") not in excluded
                and str(entry.get("hash") or "") not in excluded_hash_keys
                and str(entry.get("name") or "") not in excluded_name_keys
                and str(entry.get("scope") or "") not in excluded_scope_keys
                and (visible_scope is None or _entry_visible(entry, visible_scope))
            )
        }
        normalized = _reindex({"entries": filtered_entries})
    return {
        "source_type": "dynamic_value_store",
        "entries": normalized["entries"],
        "by_hash": normalized["by_hash"],
        "by_name": normalized["by_name"],
    }


def binding_source_from_store_for_units(
    store: object,
    allowed_unit_ids: tuple[str, ...],
    **kwargs: object,
) -> dict[str, JSONValue]:
    """Store bindings with unit-scope entries limited to the given owners.

    Unit-scope slots are committed per owner; a consumer for one unit must not
    resolve another unit's value.  Status/ability/event scopes keep their
    existing visibility rules.
    """

    source = binding_source_from_store(store, **kwargs)
    allowed = {unit_id for unit_id in allowed_unit_ids if unit_id}
    if not allowed:
        return source
    entries = source.get("entries")
    if not isinstance(entries, dict):
        return source
    filtered = {
        key: entry
        for key, entry in entries.items()
        if not (
            isinstance(entry, dict)
            and str(entry.get("scope") or entry.get("scope_kind") or "")
            in {"unit", "combat"}
            and str(entry.get("target_id") or entry.get("owner_id") or "") not in allowed
        )
    }
    if len(filtered) == len(entries):
        return source
    # The input was validated above. This is a read-only binding projection,
    # not a new committed store: it needs indexes, never a copied write ledger.
    indexed = _reindex({"entries": filtered})
    return {**source, **{key: indexed[key] for key in ("entries", "by_hash", "by_name")}}


def upsert_dynamic_value(
    store: object,
    *,
    scope: str,
    owner_id: str,
    value: float,
    value_name: str | None = None,
    hash_key: str | int | None = None,
    status_id: str | None = None,
    status_instance_id: str | None = None,
    effect_id: str | None = None,
    scope_kind: str | None = None,
    lifecycle: str | None = None,
    target_id: str | None = None,
    ability_instance_id: str | None = None,
    event_id: str | None = None,
    operation_id: str | None = None,
    operation_instance_id: str | None = None,
    source_id: str | None = None,
    operation_source_id: str | None = None,
    source_trace: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    if not _finite_number(value):
        raise ValueError("dynamic value write requires a finite non-bool number")
    if not isinstance(scope, str) or scope not in _DYNAMIC_VALUE_SCOPE_CONTRACTS:
        raise ValueError(f"dynamic value write scope is invalid:{scope}")
    contract_scope_kind, contract_lifecycle = _DYNAMIC_VALUE_SCOPE_CONTRACTS[scope]
    if scope_kind is not None and scope_kind != contract_scope_kind:
        raise ValueError("dynamic value write scope_kind disagrees with scope")
    if lifecycle is not None and lifecycle != contract_lifecycle:
        raise ValueError("dynamic value write lifecycle disagrees with scope")
    normalized = normalized_dynamic_value_store(store)
    entries = dict(normalized["entries"]) if isinstance(normalized.get("entries"), dict) else {}
    resolved_scope_kind = contract_scope_kind
    resolved_lifecycle = contract_lifecycle
    _validate_resolved_scope(
        {
            "scope_kind": resolved_scope_kind,
            "lifecycle": resolved_lifecycle,
            "owner_id": owner_id,
            "target_id": target_id or owner_id,
            "ability_instance_id": ability_instance_id,
            "status_instance_id": status_instance_id,
            "event_id": event_id,
        },
        allow_empty=False,
    )
    entry = {
        "scope": resolved_scope_kind,
        "scope_kind": resolved_scope_kind,
        "lifecycle": resolved_lifecycle,
        "owner_id": owner_id,
        "target_id": target_id or owner_id,
        "status_id": status_id,
        "status_instance_id": status_instance_id,
        "ability_instance_id": ability_instance_id,
        "event_id": event_id,
        "operation_id": operation_id,
        "operation_instance_id": operation_instance_id,
        "effect_id": effect_id,
        "source_id": source_id,
        "operation_source_id": operation_source_id,
        "name": value_name,
        "hash": str(hash_key) if hash_key is not None else None,
        "value": float(value),
        "source_trace": source_trace or {},
    }
    entries[_entry_key(entry)] = entry
    return _reindex(
        {
            "entries": entries,
            "operation_ledger": normalized.get("operation_ledger", {}),
        }
    )


def plan_dynamic_value_operation(
    state: BattleState,
    operation: DynamicValueOperationIR,
    request: DynamicValueExecutionRequest,
    *,
    rules: RuleBook | None = None,
) -> DynamicValuePlan:
    try:
        before_fingerprint = dynamic_value_state_fingerprint(state)
    except (TypeError, ValueError) as exc:
        return _blocked_plan(
            operation,
            "state:unfingerprintable",
            f"dynamic_before_state_invalid:{exc}",
        )
    if operation.coverage_status != "executable":
        return _blocked_plan(
            operation,
            before_fingerprint,
            f"dynamic_operation_not_executable:{operation.blocked_reason}",
        )
    try:
        store = _strict_dynamic_value_store(
            state.global_flags.get("dynamic_value_store")
        )
    except (TypeError, ValueError) as exc:
        return _blocked_plan(
            operation,
            before_fingerprint,
            f"dynamic_value_store_invalid:{exc}",
        )
    target_id = resolve_operation_target(state, operation, request, rules=rules)
    if not target_id:
        return _blocked_plan(
            operation,
            before_fingerprint,
            f"dynamic_target_unresolved:{operation.target_alias}",
        )
    if target_id != "level:global" and target_id not in state.units:
        return _blocked_plan(
            operation,
            before_fingerprint,
            f"dynamic_target_not_in_state:{target_id}",
        )
    resolved_scope, scope_reason = _resolved_scope(
        state,
        operation,
        request,
        target_id,
        rules=rules,
    )
    if scope_reason:
        return _blocked_plan(operation, before_fingerprint, scope_reason)
    operation_instance_id = _operation_instance_id(operation, request, resolved_scope)
    if not operation_instance_id:
        return _blocked_plan(
            operation,
            before_fingerprint,
            "dynamic_operation_event_identity_missing",
            resolved_scope=resolved_scope,
        )
    destination_entry = _destination_entry(
        operation,
        request,
        operation_instance_id,
        resolved_scope,
        value=0.0,
    )
    destination_entry_key = _entry_key(destination_entry)
    replay = _operation_replay(
        store,
        operation,
        request,
        operation_instance_id,
        destination_entry_key,
    )
    if replay is not None:
        replay_ok, replay_value, replay_reason = replay
        if not replay_ok:
            return _blocked_plan(
                operation,
                before_fingerprint,
                replay_reason,
                operation_instance_id=operation_instance_id,
                resolved_scope=resolved_scope,
            )
        return _make_dynamic_value_plan(
            ok=True,
            operation=operation,
            request=request,
            operation_instance_id=operation_instance_id,
            before_state_fingerprint=before_fingerprint,
            resolved_scope=resolved_scope,
            result_value=replay_value,
            replayed=True,
        )
    if operation.operand.operand_kind == "slot_adsorption":
        current = store["entries"].get(destination_entry_key)
        current_value = current.get("value") if isinstance(current, dict) else None
        threshold = json.loads(str(operation.operand.parameters["threshold_json"]))
        if not _finite_number(current_value):
            operand_value, evaluation, operand_reason = None, {}, "dynamic_adsorption_destination_missing"
        else:
            nearest = float(round(float(current_value)))
            operand_value = nearest if abs(float(current_value) - nearest) < threshold else float(current_value)
            evaluation, operand_reason = {
                "source_type": "slot_adsorption", "threshold": threshold,
                "before": float(current_value), "after": operand_value,
            }, ""
    else:
        operand_value, evaluation, operand_reason = _resolve_operand(
            state,
            store,
            operation.operand,
            request,
            resolved_scope,
            rules=rules,
        )
    if operand_reason or operand_value is None:
        return _blocked_plan(
            operation,
            before_fingerprint,
            operand_reason or "dynamic_operand_unresolved",
            operation_instance_id=operation_instance_id,
            resolved_scope=resolved_scope,
        )
    value = operand_value
    if operation.operation_kind == "add":
        current = store["entries"].get(destination_entry_key)
        if not isinstance(current, dict) or not _finite_number(current.get("value")):
            baseline = _declared_slot_baseline(rules, state, target_id, operation)
            if baseline is not None:
                current = {"value": baseline}
        if not isinstance(current, dict) or not _finite_number(current.get("value")):
            return _blocked_plan(
                operation,
                before_fingerprint,
                "dynamic_add_destination_missing",
                operation_instance_id=operation_instance_id,
                resolved_scope=resolved_scope,
            )
        value = float(current["value"]) + value
    for bound_name, bound, choose in (
        ("minimum", operation.minimum, max),
        ("maximum", operation.maximum, min),
    ):
        if bound is None:
            continue
        bound_value, _, bound_reason = _resolve_operand(
            state,
            store,
            bound,
            request,
            resolved_scope,
            rules=rules,
        )
        if bound_reason or bound_value is None:
            return _blocked_plan(
                operation,
                before_fingerprint,
                f"dynamic_{bound_name}_unresolved:{bound_reason}",
                operation_instance_id=operation_instance_id,
                resolved_scope=resolved_scope,
            )
        value = choose(value, bound_value)
    if not _finite_number(value):
        return _blocked_plan(
            operation,
            before_fingerprint,
            "dynamic_calculation_non_finite",
            operation_instance_id=operation_instance_id,
            resolved_scope=resolved_scope,
        )

    # Mutation, settlement and plan all retain the same numeric explanation.
    # Freeze it once so their identity checks can share the immutable subtree.
    evaluation = freeze_json(evaluation)
    entry = _destination_entry(
        operation,
        request,
        operation_instance_id,
        resolved_scope,
        value=value,
    )
    entries = dict(store["entries"])
    entries[destination_entry_key] = entry
    ledger = dict(store["operation_ledger"])
    ledger_record = {
        "operation_id": operation.operation_id,
        "operation_instance_id": operation_instance_id,
        "destination_entry_key": destination_entry_key,
        "result_value": float(value),
        "source_id": request.source_id,
        "effect_id": request.effect_id,
        "operation_source_id": _operation_source_id(operation),
    }
    ledger_record["record_fingerprint"] = _ledger_record_fingerprint(ledger_record)
    ledger[operation_instance_id] = ledger_record
    after_store = freeze_json(_reindex({"entries": entries, "operation_ledger": ledger}))
    # This producer extends an already validated store with its checked scoped
    # entry and matching ledger row. Re-readers need not audit the entire write
    # history again; imported/mutable stores still enter the full validator.
    after_store._dynamic_store_validated = True
    metadata = {
        "effect_id": request.effect_id,
        "opcode": request.opcode,
        "source_id": request.source_id,
        "caster_id": request.caster_id,
        "target_id": target_id,
        "operation_id": operation.operation_id,
        "operation_instance_id": operation_instance_id,
        "resolved_scope": resolved_scope,
        "value_name": operation.destination_key,
        "hash": operation.destination_hash,
        "value": float(value),
        "numeric_evaluation": evaluation,
        "effect_source": operation.source.to_json(),
    }
    store_mutation = Mutation(
        op="set",
        path=("global_flags", "dynamic_value_store"),
        before=state.global_flags.get("dynamic_value_store"),
        after=after_store,
        reason=f"apply {request.opcode} scoped dynamic value write",
        source="effect_system",
        before_exists="dynamic_value_store" in state.global_flags,
        metadata=metadata,
    )
    mutations: tuple[Mutation, ...] = (store_mutation,)
    status_mutation, status_reason = _status_dynamic_value_mutation(
        state,
        operation,
        request,
        resolved_scope,
        value,
        evaluation,
    )
    if status_reason:
        return _blocked_plan(
            operation,
            before_fingerprint,
            status_reason,
            operation_instance_id=operation_instance_id,
            resolved_scope=resolved_scope,
        )
    if status_mutation is not None:
        mutations = (status_mutation, store_mutation)
    records = tuple(
        SettlementRecord(
            record_type=(
                "status_dynamic_value"
                if mutation.path[:3] == ("units", target_id, "flags")
                else "dynamic_value_store"
            ),
            source="effect_system",
            mutation_id=mutation.stable_id(),
            process_only=False,
            payload={
                "effect_id": request.effect_id,
                "opcode": request.opcode,
                "operation_id": operation.operation_id,
                "operation_instance_id": operation_instance_id,
                "target_id": target_id,
                "value_name": operation.destination_key,
                "hash": operation.destination_hash,
                "value": float(value),
                "path": list(mutation.path),
                "resolved_scope": resolved_scope,
                "numeric_evaluation": evaluation,
            },
            trace={"effect_source": operation.source.to_json()},
        ).to_json()
        for mutation in mutations
    )
    return _make_dynamic_value_plan(
        ok=True,
        operation=operation,
        request=request,
        operation_instance_id=operation_instance_id,
        before_state_fingerprint=before_fingerprint,
        resolved_scope=resolved_scope,
        result_value=float(value),
        mutations=mutations,
        records=records,
        evaluation=evaluation,
    )


def execute_dynamic_value_plan(
    state: BattleState,
    plan: DynamicValuePlan,
    *,
    rules: RuleBook | None = None,
) -> DynamicValueExecutionResult:
    if type(plan) is not DynamicValuePlan:
        raise TypeError("dynamic value execution requires an exact plan")
    if not plan.ok:
        return DynamicValueExecutionResult(
            ok=False,
            plan_id=plan.plan_id,
            blocked_reason=plan.blocked_reason,
        )
    try:
        current_fingerprint = dynamic_value_state_fingerprint(state)
    except (TypeError, ValueError):
        current_fingerprint = "state:unfingerprintable"
    if current_fingerprint != plan.before_state_fingerprint:
        return DynamicValueExecutionResult(
            ok=False,
            plan_id=plan.plan_id,
            blocked_reason="stale_dynamic_value_plan",
        )
    if plan.request is None:
        return DynamicValueExecutionResult(
            ok=False,
            plan_id=plan.plan_id,
            blocked_reason="dynamic_value_plan_request_missing",
        )
    if eager_identity_audit_enabled():
        try:
            expected = plan_dynamic_value_operation(state, plan.operation, plan.request, rules=rules)
            matches = expected.ok and expected.to_json(detach=False) == plan.to_json(detach=False)
        except (TypeError, ValueError):
            matches = False
        if not matches:
            return DynamicValueExecutionResult(
                ok=False,
                plan_id=plan.plan_id,
                blocked_reason="dynamic_value_plan_integrity_mismatch",
            )
    return DynamicValueExecutionResult(
        ok=True,
        plan_id=plan.plan_id,
        mutations=plan.mutations,
        records=plan.records,
        replayed=plan.replayed,
    )


def _strict_dynamic_value_store(value: object) -> dict[str, JSONValue]:
    if value is None:
        return empty_dynamic_value_store()
    # Internal readers share one canonical immutable view. Writers already copy
    # entries/ledger before constructing a new store; mutable inputs stay detached.
    if type(value) is FrozenJSONDict and getattr(value, "_dynamic_store_validated", False):
        return getattr(value, "_canonical_dynamic_store", value)
    if not isinstance(value, dict):
        raise TypeError("store_not_object")
    expected_store_fields = {"entries", "by_hash", "by_name", "operation_ledger"}
    if set(value) != expected_store_fields:
        raise ValueError("store_schema_invalid")
    entries = value.get("entries")
    if not isinstance(entries, dict):
        raise TypeError("entries_not_object")
    for key, entry in entries.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            raise TypeError("entry_schema_invalid")
        expected_entry_fields = {
            "scope",
            "scope_kind",
            "lifecycle",
            "owner_id",
            "target_id",
            "status_id",
            "status_instance_id",
            "ability_instance_id",
            "event_id",
            "operation_id",
            "operation_instance_id",
            "effect_id",
            "source_id",
            "operation_source_id",
            "name",
            "hash",
            "value",
            "source_trace",
        }
        if set(entry) != expected_entry_fields:
            raise ValueError(f"entry_fields_invalid:{key}")
        if not _finite_number(entry.get("value")):
            raise ValueError(f"entry_value_invalid:{key}")
        if not isinstance(entry.get("name"), str) or not entry.get("name"):
            raise ValueError(f"entry_identity_missing:{key}")
        scope_kind = entry.get("scope_kind")
        lifecycle = {
            "unit": "combat",
            "ability": "ability_action",
            "status": "status_instance",
            "event": "event",
        }.get(scope_kind)
        if entry.get("scope") != scope_kind or entry.get("lifecycle") != lifecycle:
            raise ValueError(f"entry_scope_invalid:{key}")
        if any(
            not isinstance(entry.get(field_name), str) or not entry.get(field_name)
            for field_name in ("owner_id", "target_id")
        ):
            raise ValueError(f"entry_owner_target_invalid:{key}")
        _validate_resolved_scope(
            {
                "scope_kind": entry.get("scope_kind"),
                "lifecycle": entry.get("lifecycle"),
                "owner_id": entry.get("owner_id"),
                "target_id": entry.get("target_id"),
                "ability_instance_id": entry.get("ability_instance_id"),
                "status_instance_id": entry.get("status_instance_id"),
                "event_id": entry.get("event_id"),
            },
            allow_empty=False,
        )
        for field_name in (
            "status_id",
            "status_instance_id",
            "ability_instance_id",
            "event_id",
            "operation_id",
            "operation_instance_id",
            "effect_id",
            "source_id",
            "operation_source_id",
            "hash",
        ):
            optional_identity = entry.get(field_name)
            if optional_identity is not None and (
                not isinstance(optional_identity, str) or not optional_identity
            ):
                raise TypeError(f"entry_optional_identity_invalid:{key}:{field_name}")
        if not isinstance(entry.get("source_trace"), dict):
            raise TypeError(f"entry_source_trace_invalid:{key}")
        if _entry_key(entry) != key:
            raise ValueError(f"entry_key_mismatch:{key}")
    ledger = value.get("operation_ledger", {})
    if not isinstance(ledger, dict):
        raise TypeError("operation_ledger_not_object")
    for operation_instance_id, item in ledger.items():
        expected_ledger_fields = {
            "operation_id",
            "operation_instance_id",
            "destination_entry_key",
            "result_value",
            "source_id",
            "effect_id",
            "operation_source_id",
            "record_fingerprint",
        }
        if (
            not isinstance(operation_instance_id, str)
            or not operation_instance_id
            or not isinstance(item, dict)
            or not isinstance(item.get("operation_id"), str)
            or not item.get("operation_id")
            or not isinstance(item.get("operation_instance_id"), str)
            or not item.get("operation_instance_id")
            or not isinstance(item.get("destination_entry_key"), str)
            or not item.get("destination_entry_key")
            or not isinstance(item.get("source_id"), str)
            or not item.get("source_id")
            or not isinstance(item.get("effect_id"), str)
            or not item.get("effect_id")
            or not isinstance(item.get("operation_source_id"), str)
            or not item.get("operation_source_id")
            or not isinstance(item.get("record_fingerprint"), str)
            or not item.get("record_fingerprint")
            or not _finite_number(item.get("result_value"))
            or set(item) != expected_ledger_fields
        ):
            raise ValueError("operation_ledger_entry_invalid")
        entry = entries.get(item["destination_entry_key"])
        if (
            item.get("operation_instance_id") != operation_instance_id
            or not isinstance(entry, dict)
            or item.get("record_fingerprint")
            != _ledger_record_fingerprint(item)
        ):
            raise ValueError("operation_ledger_entry_mismatch")
        if entry.get("operation_instance_id") == operation_instance_id and (
            entry.get("operation_id") != item.get("operation_id")
            or entry.get("source_id") != item.get("source_id")
            or entry.get("effect_id") != item.get("effect_id")
            or entry.get("operation_source_id") != item.get("operation_source_id")
            or float(entry["value"]) != float(item["result_value"])
        ):
            raise ValueError("operation_ledger_current_entry_mismatch")
    for key, entry in entries.items():
        operation_instance_id = entry.get("operation_instance_id")
        if operation_instance_id is None:
            continue
        item = ledger.get(operation_instance_id)
        if not isinstance(item, dict) or item.get("destination_entry_key") != key:
            raise ValueError("entry_operation_ledger_missing")
    canonical = _reindex({"entries": entries, "operation_ledger": ledger})
    if value.get("by_hash") != canonical["by_hash"] or value.get("by_name") != canonical["by_name"]:
        raise ValueError("store_index_mismatch")
    if type(value) is FrozenJSONDict:
        canonical = freeze_json(canonical)
        canonical._dynamic_store_validated = True
        value._canonical_dynamic_store = canonical
        value._dynamic_store_validated = True
    return canonical


def _blocked_plan(
    operation: DynamicValueOperationIR,
    before_fingerprint: str,
    reason: str,
    *,
    operation_instance_id: str = "",
    resolved_scope: Mapping[str, Any] | None = None,
) -> DynamicValuePlan:
    return _make_dynamic_value_plan(
        ok=False,
        operation=operation,
        request=None,
        operation_instance_id=operation_instance_id,
        before_state_fingerprint=before_fingerprint,
        resolved_scope=resolved_scope or {},
        result_value=None,
        blocked_reason=reason,
    )


def _resolve_unique_expression_target(
    state: BattleState, expression_id: str, request: DynamicValueExecutionRequest, rules: RuleBook | None,
) -> str:
    if rules is None:
        return ""
    from .target import TargetSystem
    from .unit_relation import TargetEvaluationContext
    expression, reason = rules.target_expression_resolution(expression_id)
    if expression is None:
        return ""
    result = TargetSystem(rules).resolve_target_expression(state, expression,
        context=TargetEvaluationContext(request.caster_id,
            effect_owner_id=request.owner_id or request.caster_id,
            parameter_entity_ids=(request.param_entity_id,) if request.param_entity_id else (),
            template_entity_ids=request.template_target_ids,
            selected_target_ids=request.target_resolution.selected if request.target_resolution else (),
            current_target_id=request.current_action_target_id or None,
            admitted_action_target_fact=request.admitted_action_target_fact,
            expected_action_window_scope=request.expected_action_window_scope),
        target_resolution=request.target_resolution, condition_event_payload=request.event_payload,
        binding_sources=request.binding_sources)
    # Random target producers must transport their RNG; this deterministic path
    # never silently consumes/discards one or chooses the first of many results.
    return result.target_ids[0] if result.resolved and len(result.target_ids) == 1 and not result.rng_events else ""


def resolve_operation_target(
    state: BattleState, operation: DynamicValueOperationIR, request: DynamicValueExecutionRequest,
    *, rules: RuleBook | None = None,
) -> str:
    effect = rules.effect(request.effect_id) if rules is not None else None
    standard = effect.payload.get("standard", {}) if effect is not None else {}
    expression_id = standard.get("target_expression_id")
    if expression_id:
        refs = standard.get("target_expression_refs", {})
        ref = refs.get("TargetType", {})
        if ref.get("expression_kind") == "TargetAlias" and ref.get("alias") == operation.target_alias:
            direct = _resolve_request_alias(state, operation.target_alias, request)
            if direct:
                return direct
        return _resolve_unique_expression_target(state, str(expression_id), request, rules)
    return _resolve_request_alias(state, operation.target_alias, request)


def _resolve_request_alias(
    state: BattleState,
    alias: object,
    request: DynamicValueExecutionRequest,
) -> str:
    if alias in {"DamageAttackerEntity", "DamageDefenderEntity"}:
        from .damage import event_damage_identity_ids

        attacker, defender = event_damage_identity_ids(state, request.trigger_event)
        return (attacker if alias == "DamageAttackerEntity" else defender) or ""
    # The dotted spellings name the same committed summon relations.
    alias = {"Caster.GetServant": "CasterServant", "Caster.GetSummoner": "CasterSummoner"}.get(str(alias or ""), alias)
    if alias in {"CasterServant", "CasterSummoner"}:
        from .unit_relation import EntityRelationResolver, TargetEvaluationContext

        resolver = EntityRelationResolver()
        context = TargetEvaluationContext(caster_id=request.caster_id,
                                          template_entity_ids=request.template_target_ids)
        result = resolver.resolve(
            state, "summon.owned" if alias == "CasterServant" else "summon.summoner",
            context, subject_ids=(request.caster_id,),
        )
        if not result.resolved:
            return ""
        target_ids = result.target_ids
        if alias == "CasterServant":
            servants = resolver.resolve(state, "entity.servant", context)
            if not servants.resolved:
                return ""
            target_ids = tuple(unit_id for unit_id in target_ids if unit_id in servants.target_ids)
        return target_ids[0] if len(target_ids) == 1 else ""
    if str(alias or "") == "CasterSelfCreateBattleEvent":
        from .target import resolve_created_battle_event_targets

        created = resolve_created_battle_event_targets(state, request.caster_id)
        return created[0] if len(created) == 1 else ""
    if str(alias or "") == "BattleEventCaster":
        # The battle event's creator, through the committed entity.creator
        # relation; a non-event caster resolves nothing and stays fail-closed.
        from .unit_relation import EntityRelationResolver, TargetEvaluationContext

        caster = state.units.get(request.caster_id)
        if caster is None or caster.flags.get("entity_type") != "battle_event":
            return ""
        resolved = EntityRelationResolver().resolve(
            state,
            "entity.creator",
            TargetEvaluationContext(caster_id=request.caster_id),
            subject_ids=(request.caster_id,),
        )
        return resolved.target_ids[0] if resolved.resolved and len(resolved.target_ids) == 1 else ""
    return {
        "Caster": request.caster_id,
        "ModifierOwnerEntity": request.owner_id or request.caster_id,
        "ParamEntity": request.param_entity_id,
        "CurrentActionTarget": request.current_action_target_id,
        "LevelEntity": "level:global",
    }.get(str(alias or ""), "")


def _unit_scope_destination_entry(
    state: BattleState,
    target_id: str,
    operation: DynamicValueOperationIR,
) -> dict[str, JSONValue] | None:
    entries = store_from_state(state).get("entries", {})
    if not isinstance(entries, dict):
        return None
    for entry in entries.values():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("scope") or entry.get("scope_kind") or "") not in {
            "unit", "combat",
        }:
            continue
        if str(entry.get("target_id") or entry.get("owner_id") or "") != target_id:
            continue
        if (
            operation.destination_hash is not None
            and str(entry.get("hash") or "") == str(operation.destination_hash)
        ):
            return entry
        if operation.destination_key and entry.get("name") == operation.destination_key:
            return entry
    return None


def _declared_slot_baseline(
    rules: RuleBook | None,
    state: BattleState,
    unit_id: str,
    operation: DynamicValueOperationIR,
) -> float | None:
    """Declared mutable slots start at their config baseline (usually zero)."""

    if rules is None:
        return None
    source = character_declared_dynamic_binding_source(
        rules, state, unit_id,
    ) or servant_declared_dynamic_binding_source(
        rules, state, unit_id,
    )
    if source is None:
        return None
    entries = source.get("entries")
    if not isinstance(entries, dict):
        return None
    destination_hash = (
        str(operation.destination_hash)
        if operation.destination_hash is not None
        else ""
    )
    for entry in entries.values():
        if not isinstance(entry, dict):
            continue
        hash_matches = (
            bool(destination_hash)
            and str(entry.get("hash") or "") == destination_hash
        )
        name_matches = (
            bool(operation.destination_key)
            and entry.get("name") == operation.destination_key
        )
        if not (hash_matches or name_matches):
            continue
        value = entry.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numeric = float(value)
            if math.isfinite(numeric):
                return numeric
    return None


def _resolved_scope(
    state: BattleState,
    operation: DynamicValueOperationIR,
    request: DynamicValueExecutionRequest,
    target_id: str,
    *,
    rules: RuleBook | None = None,
) -> tuple[dict[str, JSONValue], str]:
    scope_kind = operation.scope_kind
    if (
        scope_kind in {"contextual", "ability"}
        and (_unit_scope_destination_entry(state, target_id, operation)
             or _declared_slot_baseline(rules, state, target_id, operation) is not None)
    ):
        # A config-declared or already instantiated unit slot stays on that
        # unit. Creation-time parameters also need later ability resets to
        # update the same slot, rather than leave its previous value live.
        scope_kind = "unit"
    if scope_kind == "ability" and not request.ability_instance_id and request.status_instance_id:
        # A status-callback template runs inside event dispatch, not an ability
        # instance. Keep scratch values with that status, so another receiver's
        # callback cannot supply a same-named temporary to a numeric expression.
        scope_kind = "status" if target_id == (request.owner_id or request.caster_id) else "unit"
    if scope_kind == "contextual":
        if request.status_instance_id and (
            _unit_scope_destination_entry(state, target_id, operation)
            or _declared_slot_baseline(rules, state, target_id, operation) is not None
        ):
            # A contextual write that already owns a unit-scope destination on
            # the target keeps using that store; status-local defaults must not
            # split the same dynamic value between two scopes.
            scope_kind = "unit"
        elif request.status_instance_id:
            # A status-listener callback may write a contextual value onto a
            # different unit (for example a servant syncing a summoner display
            # value). The status instance lives on the callback owner, so the
            # source intent is that target unit's own dynamic value store.
            target_instances = _status_details_by_instance(
                state, target_id, request.status_instance_id,
            )
            if target_instances:
                scope_kind = "status"
            else:
                owner_id = request.owner_id or request.caster_id
                owner_instances = (
                    _status_details_by_instance(
                        state, owner_id, request.status_instance_id,
                    )
                    if owner_id and owner_id != target_id
                    else ()
                )
                scope_kind = (
                    "unit"
                    if owner_instances and target_id in state.units
                    else "status"
                )
        elif request.ability_instance_id:
            scope_kind = "ability"
        elif request.event_id:
            scope_kind = "event"
        else:
            return {}, "dynamic_contextual_scope_unresolved"
    lifecycle = {
        "unit": "combat",
        "ability": "ability_action",
        "status": "status_instance",
        "event": "event",
    }[scope_kind]
    owner_id = request.owner_id or request.caster_id
    scope: dict[str, JSONValue] = {
        "scope_kind": scope_kind,
        "lifecycle": lifecycle,
        "owner_id": owner_id,
        "target_id": target_id,
        "ability_instance_id": None,
        "status_instance_id": None,
        "event_id": None,
    }
    if scope_kind == "ability":
        if not request.ability_instance_id:
            return {}, "dynamic_ability_instance_missing"
        scope["ability_instance_id"] = request.ability_instance_id
    elif scope_kind == "status":
        if not request.status_instance_id:
            return {}, "dynamic_status_instance_missing"
        matches = _status_details_by_instance(
            state,
            target_id,
            request.status_instance_id,
        )
        if not matches:
            removed = _removed_status_detail(request, target_id)
            matches = (removed,) if removed is not None else ()
        if len(matches) != 1:
            return {}, (
                "dynamic_status_instance_missing"
                if not matches
                else "dynamic_status_instance_ambiguous"
            )
        identity_reason = _status_scope_identity_reason(
            matches[0],
            target_id=target_id,
            request=request,
        )
        if identity_reason:
            return {}, identity_reason
        scope["status_instance_id"] = request.status_instance_id
    elif scope_kind == "event":
        if not request.event_id:
            return {}, "dynamic_event_identity_missing"
        scope["event_id"] = request.event_id
    return scope, ""


def _removed_status_detail(
    request: DynamicValueExecutionRequest, target_id: str,
) -> dict[str, JSONValue] | None:
    # Only the status lifecycle producer may retain a removed instance for its
    # destruction callback. A payload or an old status binding is insufficient.
    from .status import StatusLifecyclePlan
    from .action_event_contract import AdmittedActionTargetFact, ActionWindowExpectedScope

    plan = request.status_lifecycle_plan
    if (type(plan) is not StatusLifecyclePlan
            or plan.operation not in {"remove", "expire", "dispel", "stack_reduce_remove"}
            or plan.target_id != target_id or plan.status_id != request.status_id
            or not isinstance(plan.existing_detail, dict)
            or plan.existing_detail.get("instance_id") != request.status_instance_id
            or _status_scope_identity_reason(plan.existing_detail, target_id=target_id, request=request)):
        return None
    return plan.existing_detail


def _validate_resolved_scope(
    scope: Mapping[str, Any],
    *,
    allow_empty: bool,
) -> None:
    if allow_empty and not scope:
        return
    expected_fields = {
        "scope_kind",
        "lifecycle",
        "owner_id",
        "target_id",
        "ability_instance_id",
        "status_instance_id",
        "event_id",
    }
    if set(scope) != expected_fields:
        raise ValueError("dynamic value resolved scope schema is invalid")
    scope_kind = scope.get("scope_kind")
    lifecycle = scope.get("lifecycle")
    expected_lifecycle = {
        "unit": "combat",
        "ability": "ability_action",
        "status": "status_instance",
        "event": "event",
    }.get(scope_kind)
    if expected_lifecycle is None or lifecycle != expected_lifecycle:
        raise ValueError("dynamic value resolved scope lifecycle is invalid")
    if any(
        not isinstance(scope.get(field_name), str) or not scope.get(field_name)
        for field_name in ("owner_id", "target_id")
    ):
        raise ValueError("dynamic value resolved scope owner or target is invalid")
    identity_fields = {
        "ability": "ability_instance_id",
        "status": "status_instance_id",
        "event": "event_id",
    }
    active_field = identity_fields.get(str(scope_kind))
    for field_name in ("ability_instance_id", "status_instance_id", "event_id"):
        value = scope.get(field_name)
        if field_name == active_field:
            if not isinstance(value, str) or not value:
                raise ValueError("dynamic value resolved scope identity is missing")
        elif value is not None:
            raise ValueError("dynamic value resolved scope carries a foreign identity")


def _status_scope_identity_reason(
    detail: Mapping[str, Any],
    *,
    target_id: str,
    request: DynamicValueExecutionRequest,
) -> str:
    if not request.status_modifier_name:
        return "dynamic_status_effect_owner_missing"
    if not request.status_id or not request.status_source_id:
        return "dynamic_status_request_source_identity_missing"
    required = (
        "instance_id",
        "status_id",
        "modifier_name",
        "owner_id",
        "source_id",
    )
    if any(not isinstance(detail.get(key), str) or not detail.get(key) for key in required):
        return "dynamic_status_instance_schema_invalid"
    if detail.get("owner_id") != target_id or (
        request.owner_id and detail.get("owner_id") != request.owner_id
    ):
        return "dynamic_status_instance_owner_target_mismatch"
    expected = (
        ("modifier_name", request.status_modifier_name),
        ("status_id", request.status_id),
        ("source_id", request.status_source_id),
    )
    for field_name, expected_value in expected:
        if expected_value and detail.get(field_name) != expected_value:
            return f"dynamic_status_instance_{field_name}_mismatch"
    return ""


def _operation_instance_id(
    operation: DynamicValueOperationIR,
    request: DynamicValueExecutionRequest,
    resolved_scope: Mapping[str, Any],
) -> str:
    if not request.operation_event_id:
        return ""
    payload = {
        "operation_id": operation.operation_id,
        "operation_event_id": request.operation_event_id,
        "source_id": request.source_id,
        "task_id": request.task_id,
        "scope": thaw_json(resolved_scope),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return "dynamic_value_operation_instance:" + hashlib.sha256(encoded).hexdigest()


def _destination_entry(
    operation: DynamicValueOperationIR,
    request: DynamicValueExecutionRequest,
    operation_instance_id: str,
    resolved_scope: Mapping[str, Any],
    *,
    value: float,
) -> dict[str, JSONValue]:
    return {
        "scope": str(resolved_scope.get("scope_kind") or ""),
        "scope_kind": str(resolved_scope.get("scope_kind") or ""),
        "lifecycle": str(resolved_scope.get("lifecycle") or ""),
        "owner_id": str(resolved_scope.get("owner_id") or ""),
        "target_id": str(resolved_scope.get("target_id") or ""),
        "status_id": (
            request.status_id
            if resolved_scope.get("scope_kind") == "status"
            else None
        ),
        "status_instance_id": resolved_scope.get("status_instance_id"),
        "ability_instance_id": resolved_scope.get("ability_instance_id"),
        "event_id": resolved_scope.get("event_id"),
        "name": operation.destination_key,
        "hash": operation.destination_hash,
        "value": float(value),
        "operation_id": operation.operation_id,
        "operation_instance_id": operation_instance_id,
        "effect_id": request.effect_id,
        "source_id": request.source_id,
        "operation_source_id": _operation_source_id(operation),
        "source_trace": {"operation_source": operation.source.to_json()},
    }


def _operation_replay(
    store: dict[str, JSONValue],
    operation: DynamicValueOperationIR,
    request: DynamicValueExecutionRequest,
    operation_instance_id: str,
    destination_entry_key: str,
) -> tuple[bool, float | None, str] | None:
    ledger = store.get("operation_ledger")
    item = ledger.get(operation_instance_id) if isinstance(ledger, dict) else None
    if item is None:
        return None
    if not isinstance(item, dict):
        return False, None, "dynamic_operation_ledger_invalid"
    value = item.get("result_value")
    entry = (
        store.get("entries", {}).get(destination_entry_key)
        if isinstance(store.get("entries"), dict)
        else None
    )
    if (
        item.get("operation_id") != operation.operation_id
        or item.get("operation_instance_id") != operation_instance_id
        or item.get("destination_entry_key") != destination_entry_key
        or item.get("source_id") != request.source_id
        or item.get("effect_id") != request.effect_id
        or item.get("operation_source_id") != _operation_source_id(operation)
        or not _finite_number(value)
        or item.get("record_fingerprint") != _ledger_record_fingerprint(item)
        or not isinstance(entry, dict)
    ):
        return False, None, "dynamic_operation_replay_conflict"
    return True, float(value), ""


def _ledger_record_fingerprint(item: Mapping[str, Any]) -> str:
    payload = {
        key: item.get(key)
        for key in (
            "operation_id",
            "operation_instance_id",
            "destination_entry_key",
            "result_value",
            "source_id",
            "effect_id",
            "operation_source_id",
        )
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "dynamic_value_ledger:" + hashlib.sha256(encoded).hexdigest()


def _operation_source_id(operation: DynamicValueOperationIR) -> str:
    encoded = json.dumps(
        operation.source.to_json(),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "dynamic_value_source:" + hashlib.sha256(encoded).hexdigest()


def _resolve_operand(
    state: BattleState,
    store: dict[str, JSONValue],
    operand: NumericOperandIR,
    request: DynamicValueExecutionRequest,
    resolved_scope: Mapping[str, Any],
    *,
    rules: RuleBook | None = None,
) -> tuple[float | None, dict[str, JSONValue], str]:
    if operand.coverage_status != "executable":
        return None, {}, f"numeric_operand_blocked:{operand.blocked_reason}"
    # An active ability evaluates its operands in the executing caster's scope;
    # TargetType selects the write destination, not a second ability context.
    read_scope = ({**resolved_scope, "target_id": request.caster_id,
                   "ability_instance_id": request.ability_instance_id}
                  if request.ability_instance_id and not request.status_instance_id else resolved_scope)
    sources = _operand_binding_sources(store, request, read_scope)
    evaluation: dict[str, JSONValue]
    value: float | None = None
    reason = ""
    if operand.operand_kind == "expression":
        expression = thaw_json(operand.expression)
        result = resolve_runtime_numeric_expression(
            expression,
            binding_sources=sources,
            source_trace={"effect_id": request.effect_id, "source_id": request.source_id},
        )
        evaluation = result.to_json()
        value = result.value if result.ok else None
        reason = "" if result.ok else result.blocked_reason
    else:
        value, binding, reason = _resolve_source_operand(
            state,
            store,
            operand,
            request,
            resolved_scope,
            rules=rules,
        )
        evaluation = {
            "ok": not reason and value is not None,
            "value": value,
            "expression_kind": "typed_operand",
            "bindings": binding,
            "source_trace": {
                "effect_id": request.effect_id,
                "source_id": request.source_id,
            },
            "blocked_reason": reason,
        }
    if reason or value is None:
        return None, evaluation, reason or "numeric_operand_unresolved"
    if operand.scale_expression is not None:
        scale = resolve_runtime_numeric_expression(
            thaw_json(operand.scale_expression),
            binding_sources=sources,
            source_trace={"effect_id": request.effect_id, "source_id": request.source_id},
        )
        if not scale.ok or scale.value is None:
            return None, evaluation, (
                scale.blocked_reason or "numeric_operand_scale_unresolved"
            )
        value *= scale.value
        evaluation = {
            **evaluation,
            "value": value,
            "scale_evaluation": scale.to_json(),
        }
    if not _finite_number(value):
        return None, evaluation, "numeric_operand_non_finite"
    return float(value), evaluation, ""


def _operand_binding_sources(
    store: dict[str, JSONValue],
    request: DynamicValueExecutionRequest,
    resolved_scope: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    sources = tuple(
        dict(source)
        for source in request.binding_sources
        if source.get("source_type") != "dynamic_value_store"
    )
    status_instances = {
        source["status_instance_id"] for source in sources
        if source.get("source_type") == "status_instance" and source.get("status_instance_id")
    }
    entries = store.get("entries")
    visible = {
        key: entry
        for key, entry in (entries.items() if isinstance(entries, dict) else ())
        if isinstance(entry, dict) and _entry_visible(entry, resolved_scope)
        # Status writes update both the instance and this store. The explicit
        # instance binding already represents that same value, not a competitor.
        and not (entry.get("scope_kind") == "status"
                 and entry.get("status_instance_id") in status_instances)
    }
    indexed = _reindex({"entries": visible})
    from .task_graph import with_template_binding_sources

    return with_template_binding_sources((
        *(source for source in sources if source.get("source_type") != "task_template_parameter"),
        {
            "source_type": "dynamic_value_store",
            "entries": indexed["entries"],
            "by_hash": indexed["by_hash"],
            "by_name": indexed["by_name"],
        },
    ), tuple(source for source in sources if source.get("source_type") == "task_template_parameter"))


def _entry_visible(
    entry: Mapping[str, Any],
    resolved_scope: Mapping[str, Any],
) -> bool:
    target_id = str(resolved_scope.get("target_id") or "")
    entry_target = str(entry.get("target_id") or entry.get("owner_id") or "")
    if entry_target != target_id:
        return False
    scope_kind = str(entry.get("scope_kind") or entry.get("scope") or "")
    if scope_kind in {"unit", "combat", "ContextCaster", "ContextOwner", "TargetEntity"}:
        return True
    for kind, field_name in (
        ("ability", "ability_instance_id"),
        ("status", "status_instance_id"),
        ("event", "event_id"),
    ):
        if scope_kind == kind:
            expected = resolved_scope.get(field_name)
            return bool(expected) and entry.get(field_name) == expected
    return False


def _resolve_source_operand(
    state: BattleState,
    store: dict[str, JSONValue],
    operand: NumericOperandIR,
    request: DynamicValueExecutionRequest,
    resolved_scope: Mapping[str, Any],
    *,
    rules: RuleBook | None = None,
) -> tuple[float | None, dict[str, JSONValue], str]:
    parameters = operand.parameters
    source_alias = parameters.get("source_target_alias")
    source_expression_id = parameters.get("source_target_expression_id")
    source_id = (_resolve_unique_expression_target(state, str(source_expression_id), request, rules)
                 if source_expression_id and operand.operand_kind != "character_count"
                 else _resolve_request_alias(state, source_alias, request) if source_alias else "")
    param_detail = None
    if request.param_status_scope is not None:
        scope = request.param_status_scope
        details = _status_details_by_instance(state, scope.owner_id, scope.instance_id)
        owner = state.units.get(scope.owner_id)
        if (len(details) != 1 or owner is None or details[0].get("owner_id") != scope.owner_id
                or details[0].get("lifecycle_state") != "active"
                or details[0].get("status_id") not in owner.statuses):
            return None, {}, "parameter_modifier_instance_not_active"
        param_detail = details[0]
    if operand.operand_kind == "unit_identity":
        unit = state.units.get(source_id)
        action_set = rules.combatant_action_set(unit.template_id) if rules is not None and unit is not None else None
        if (unit is None or action_set is None or action_set.coverage_status != "executable"
                or parameters.get("identity_kind") != "character_id"):
            return None, {}, "unit_identity_formal_combatant_missing"
        from ..rules.combatant_identity import combatant_character_id
        identity = combatant_character_id(unit)
        if identity is None:
            return None, {}, "unit_identity_not_a_numeric_character_reference"
        return float(identity), {"source_type": "unit_identity", "source_unit_id": source_id,
            "entity_ref": unit.template_id, "identity_kind": "character_id",
            "rule_source": action_set.source.to_json()}, ""
    if operand.operand_kind == "world_level":
        world_level = state.global_flags.get("world_level")
        if not _finite_number(world_level):
            return None, {}, "battle_world_level_missing"
        return (
            float(world_level),
            {
                "source_type": "battle_setup_world_level",
                "world_level": int(world_level),
            },
            "",
        )
    if operand.operand_kind == "character_count":
        from .target import TargetSystem
        from .unit_relation import TargetEvaluationContext

        if parameters.get("predicate_json") not in {"", "null"}:
            return None, {}, "character_count_predicate_not_admitted"
        if type(parameters.get("alive_only")) is not bool:
            return None, {}, "character_count_alive_policy_missing"
        if rules is None:
            return None, {}, "character_count_target_rules_missing"
        expression_id = str(parameters.get("source_target_expression_id") or "")
        expression, reason = rules.target_expression_resolution(expression_id)
        if expression is None:
            return None, {}, f"character_count_{reason}"
        resolved = TargetSystem(rules).resolve_target_expression(state, expression,
            context=TargetEvaluationContext(request.caster_id,
                effect_owner_id=request.owner_id or request.caster_id,
                parameter_entity_ids=(request.param_entity_id,) if request.param_entity_id else (),
                current_target_id=request.current_action_target_id or None,
                template_entity_ids=request.template_target_ids),
            binding_sources=tuple(dict(source) for source in request.binding_sources))
        if resolved.blocked:
            return None, resolved.to_json(), resolved.blocked_reason
        if resolved.rng_events:
            return None, {}, "character_count_random_target_not_admitted"
        if any(target_id not in state.units for target_id in resolved.target_ids):
            return None, {}, "character_count_target_unit_missing"
        lifecycle = UnitLifecycleSystem()
        counted = tuple(target_id for target_id in resolved.target_ids
            if (view := lifecycle.view(state, target_id)).is_present
            and (parameters.get("alive_only") is not True or view.is_active and view.hp > 0))
        return float(len(counted)), {"source_type": "character_count", "target_resolution": resolved.to_json(),
                                    "counted_target_ids": list(counted)}, ""
    if source_alias == "SnapshotPropertyEntity":
        # TargetAliasConfig: Caster -> TargetFetchAliveSourceEntity. The status
        # callback samples the living source again, including subsequent buffs.
        # See https://www.reddit.com/r/HonkaiStarRail/comments/148tfhn/some_dot_tests/
        if operand.operand_kind != "unit_property" or resolved_scope.get("scope_kind") != "status":
            return None, {}, "snapshot_property_status_context_missing"
        details = _status_details_by_instance(
            state, str(resolved_scope.get("target_id") or ""), request.status_instance_id,
        )
        if len(details) != 1 or details[0].get("caster_id") != request.caster_id:
            return None, {}, "snapshot_property_status_caster_mismatch"
        lifecycle = UnitLifecycleSystem().view(state, request.caster_id)
        source_unit = state.units.get(request.caster_id)
        # 来源已正式倒下但仍保留在战场记录中：读取其倒下时已提交的属性
        # （用户 2026-11-09 裁决的工程规则，资料未给出依据）。已移除或缺失
        # 的来源仍失败关闭；不以目标或施加时缓存值替代。
        defeated_source = (
            source_unit is not None
            and source_unit.lifecycle_status == "defeated"
        )
        if not defeated_source and (
            not lifecycle.is_present or not lifecycle.is_active or lifecycle.hp <= 0
        ):
            return None, {}, "snapshot_property_alive_source_unavailable"
        source_id = request.caster_id
    if operand.operand_kind == "dynamic_value":
        source_key = str(parameters.get("source_key") or "")
        source_hash = str(parameters.get("source_hash") or "")
        source_modifier = str(parameters.get("source_modifier") or "")
        if source_modifier:
            if not source_id or source_id not in state.units:
                return None, {}, "dynamic_copy_source_unit_missing"
            details, details_reason = _validated_status_details(state, source_id)
            if details_reason:
                return None, {}, details_reason
            matches: list[tuple[str, Mapping[str, Any], object]] = []
            for detail in details:
                if str(detail.get("modifier_name") or "") != source_modifier:
                    continue
                if (param_detail is not None and param_detail.get("modifier_name") == source_modifier
                        and request.param_status_scope.owner_id == source_id
                        and detail.get("instance_id") != request.param_status_scope.instance_id):
                    continue
                dynamic_values = detail.get("dynamic_values")
                if not isinstance(dynamic_values, Mapping):
                    continue
                by_name = dynamic_values.get("__by_name")
                if by_name is not None and not isinstance(by_name, Mapping):
                    return None, {}, "status_dynamic_value_index_invalid"
                value = (
                    by_name.get(source_key)
                    if source_key and isinstance(by_name, Mapping)
                    else dynamic_values.get(source_key)
                    if source_key
                    else None
                )
                if _finite_number(value):
                    matches.append(
                        (str(detail.get("instance_id") or ""), detail, value)
                    )
            if len(matches) != 1:
                return None, {"candidate_count": len(matches)}, (
                    "dynamic_copy_source_missing"
                    if not matches
                    else "dynamic_copy_source_ambiguous"
                )
            instance_id, detail, value = matches[0]
            return float(value), {
                "source_type": "status_dynamic_value",
                "source_unit_id": source_id,
                "status_instance_id": instance_id,
                "modifier_name": source_modifier,
                "source_key": source_key,
                "status_source": detail.get("source_trace", {}),
            }, ""
        matches = [
            (key, entry)
            for key, entry in store["entries"].items()
            if isinstance(entry, dict)
            and _entry_visible(
                entry,
                {**resolved_scope, "target_id": source_id},
            )
            and (
                (source_hash and entry.get("hash") == source_hash)
                or (source_key and entry.get("name") == source_key)
            )
        ]
        if len(matches) != 1:
            return None, {"candidate_count": len(matches)}, (
                "dynamic_copy_source_missing"
                if not matches
                else "dynamic_copy_source_ambiguous"
            )
        entry_key, entry = matches[0]
        value = entry.get("value")
        return (
            float(value) if _finite_number(value) else None,
            {
                "source_type": "dynamic_value_store",
                "entry_key": entry_key,
                "entry": entry,
            },
            "" if _finite_number(value) else "dynamic_copy_source_non_finite",
        )
    if operand.operand_kind in {
        "unit_property",
        "hp_ratio",
        "shield_value",
        "status_count",
        "modifier_value",
    }:
        if not source_id or source_id not in state.units:
            return None, {}, "numeric_operand_source_unit_missing"
        unit = state.units[source_id]
        if operand.operand_kind == "unit_property":
            value = ability_property_value(unit, parameters.get("property_name"))
        elif operand.operand_kind == "hp_ratio":
            maximum = current_max_hp(unit)
            value = unit.hp / maximum if maximum > 0 else None
        elif operand.operand_kind == "shield_value":
            value = ability_property_value(unit, "Shield")
        elif operand.operand_kind == "status_count":
            details, details_reason = _validated_status_details(state, source_id)
            if details_reason:
                return None, {}, details_reason
            value = (
                float(
                    sum(
                        1
                        for detail in details
                        if detail.get("status_category") == "debuff"
                    )
                )
                if parameters.get("count_mode") == "debuff"
                else None
            )
        else:
            details, details_reason = _validated_status_details(state, source_id)
            if details_reason:
                return None, {}, details_reason
            matches = [
                detail
                for detail in details
                if str(detail.get("modifier_name") or "")
                == str(parameters.get("modifier_name") or "")
                and (param_detail is None or param_detail.get("modifier_name") != parameters.get("modifier_name")
                     or request.param_status_scope.owner_id != source_id
                     or detail.get("instance_id") == request.param_status_scope.instance_id)
            ]
            if len(matches) != 1:
                if (
                    not matches
                    and str(parameters.get("modifier_value_name") or "")
                    == "Layer"
                ):
                    # Native layer reads of an absent modifier are zero: the
                    # modifier simply contributes no layers. Pinned sources
                    # reference a few modifier names without definitions (for
                    # example MAvatar_Hyacine_00_IronWater), so the read stays
                    # a typed, audit-visible zero baseline instead of inventing
                    # or dropping the surrounding startup task.
                    return (
                        0.0,
                        {
                            "source_type": "modifier_value",
                            "source_unit_id": source_id,
                            "modifier_name": str(
                                parameters.get("modifier_name") or ""
                            ),
                            "value_basis": (
                                "absent_modifier_layer_zero_baseline"
                            ),
                        },
                        "",
                    )
                return None, {"candidate_count": len(matches)}, (
                    "modifier_value_source_missing"
                    if not matches
                    else "modifier_value_source_ambiguous"
                )
            value = _modifier_value(
                matches[0],
                str(parameters.get("modifier_value_name") or ""),
            )
        return (
            float(value) if _finite_number(value) else None,
            {
                "source_type": operand.operand_kind,
                "source_unit_id": source_id,
                "parameters": thaw_json(parameters),
            },
            "" if _finite_number(value) else f"{operand.operand_kind}_value_unresolved",
        )
    if operand.operand_kind == "event_value":
        event_kind = str(parameters.get("event_kind") or "")
        if event_kind == "SetDynamicValueByChangeValue":
            event = request.trigger_event
            from .ability_property_watchers import AbilityPropertyChangeFact
            fact = event.ability_property_change_fact if event is not None else None
            property_transport = isinstance(request.event_payload, Mapping) and "ability_property_change_value" in request.event_payload
            if fact is not None or property_transport:
                if type(fact) is not AbilityPropertyChangeFact or not fact.matches_event(event):
                    return None, {}, "event_value_property_change_fact_missing_or_mismatched"
                return fact.delta, {"source_type": "native_ability_property_change", "event_kind": event_kind,
                                    "watcher_id": fact.watcher.watcher_id, "range_id": fact.range_id,
                                    "before": fact.before, "after": fact.after, "delta": fact.delta}, ""
            if event is not None and event.event_type == "energy.change":
                from .mutation_events import native_energy_change_value
                delta, reason = native_energy_change_value(event)
                return delta, {"source_type": "native_energy_change", "event_kind": event_kind,
                               "event_id": event.event_id}, reason
            from .mutation_events import native_hp_change_value
            delta, reason = native_hp_change_value(event)
            return delta, {"source_type": "native_hp_change", "event_kind": event_kind,
                           "event_id": event.event_id if event is not None else ""}, reason
        if event_kind == "SetDynamicValueByVariateType":
            if str(parameters.get("variate_type") or "") != "ParamValue":
                return None, {}, "event_value_variate_type_not_admitted"
            from .mutation_events import native_hp_change_value
            amount, reason = native_hp_change_value(request.trigger_event)
            return amount, {"source_type": "native_hp_change", "event_kind": event_kind,
                            "event_id": request.trigger_event.event_id if request.trigger_event is not None else "",
                            "hp_change_amount": amount}, reason
        if event_kind == "SetDynamicValueByDamageDataProperty":
            # The hit window publishes the committed final damage of the hit it
            # follows.  Only the source property used by true-damage callbacks
            # is admitted, and the reader must be the attacker that dealt it.
            property_name = parameters.get("property_name")
            if property_name not in {
                "Result_FinalDamageBase", "Result_FinalDamage",
            }:
                return None, {}, (
                    "event_value_property_not_admitted:"
                    + str(property_name or "<missing>")
                )
            event_payload = request.event_payload
            if not isinstance(event_payload, Mapping):
                return None, {}, "event_value_damage_payload_missing"
            final_damage = event_payload.get("final_damage")
            if (
                type(final_damage) not in (int, float)
                or isinstance(final_damage, bool)
                or not math.isfinite(float(final_damage))
            ):
                return None, {}, "event_value_damage_value_not_finite"
            read_alias = str(parameters.get("source_target_alias") or "")
            if read_alias not in {"ModifierOwnerEntity", "Caster"}:
                return None, {}, (
                    "event_value_read_target_not_admitted:"
                    + (read_alias or "<missing>")
                )
            if not source_id:
                return None, {}, "event_value_read_target_unresolved"
            attacker_id = str(
                event_payload.get("attacker_id")
                or event_payload.get("damage_attacker_id")
                or ""
            )
            if source_id != attacker_id:
                return None, {}, "event_value_damage_scope_mismatch"
            return float(final_damage), {
                "source_type": "damage_event_value",
                "read_target_id": source_id,
                "attacker_id": attacker_id,
                "property_name": property_name,
                "final_damage": float(final_damage),
                "source_event_id": str(event_payload.get("event_id") or ""),
            }, ""
        if event_kind != "SetDynamicValueByHealDataProperty":
            return None, {}, f"event_value_kind_not_admitted:{event_kind or '<missing>'}"
        property_name = parameters.get("property_name")
        if property_name not in (None, "", "HealAmount"):
            return None, {}, (
                f"event_value_property_not_admitted:{property_name or '<missing>'}"
            )
        event_payload = request.event_payload
        if not isinstance(event_payload, Mapping):
            return None, {}, "event_value_heal_payload_missing"
        fact = request.heal_event_fact
        from .mutation_events import HealEventFact

        if type(fact) is not HealEventFact:
            return None, {}, "event_value_heal_fact_missing"
        if not fact.matches_heal_payload(dict(event_payload)):
            return None, {}, "event_value_heal_fact_mismatch"
        heal_amount = float(fact.heal_amount)
        healer_id = fact.healer_id
        read_alias = str(parameters.get("source_target_alias") or "")
        if read_alias not in {"ModifierOwnerEntity", "Caster", "ParamEntity"}:
            return None, {}, (
                f"event_value_read_target_not_admitted:{read_alias or '<missing>'}"
            )
        if not source_id:
            return None, {}, "event_value_read_target_unresolved"
        binding = {
            "source_type": "heal_event_value",
            "read_target_id": source_id,
            "healer_id": healer_id,
            "heal_target_id": fact.heal_target_id,
            "heal_amount": heal_amount,
            "source_mutation_id": fact.mutation_id,
            "heal_event_fact": "admitted",
        }
        if source_id != healer_id:
            # The heal-data property belongs to the committed healer only.  A
            # reader with another scope is an unadmitted consumer, not zero.
            return None, {}, "heal_event_value_scope_mismatch"
        return heal_amount, binding, ""
    if operand.operand_kind == "team_resource":
        resource_name = str(parameters.get("resource_name") or "")
        value: object = {
            "skill_points": state.skill_points,
            "max_skill_points": state.max_skill_points,
        }.get(resource_name)
        return (
            float(value) if _finite_number(value) else None,
            {"source_type": "battle_resource", "resource_name": resource_name},
            "" if _finite_number(value) else "team_resource_unresolved",
        )
    return None, {}, f"numeric_operand_runtime_not_closed:{operand.operand_kind}"


def _modifier_value(detail: Mapping[str, Any], value_name: str) -> float | None:
    if value_name == "Layer":
        value = detail.get("stacks")
    elif value_name == "MaxLayer":
        value = detail.get("max_stacks")
    elif value_name == "LifeTime":
        value = detail.get("remaining_duration", detail.get("duration"))
    else:
        return None
    return float(value) if _finite_number(value) else None


def _status_details(state: BattleState, unit_id: str) -> tuple[dict[str, Any], ...]:
    unit = state.units.get(unit_id)
    details = unit.flags.get("status_details", ()) if unit is not None else ()
    return tuple(detail for detail in details if isinstance(detail, dict)) if isinstance(details, (list, tuple)) else ()


def _validated_status_details(
    state: BattleState,
    unit_id: str,
) -> tuple[tuple[dict[str, Any], ...], str]:
    unit = state.units.get(unit_id)
    if unit is None:
        return (), "status_count_source_unit_missing"
    if "status_details" not in unit.flags:
        return (), ""
    raw_details = unit.flags.get("status_details")
    if not isinstance(raw_details, (list, tuple)):
        return (), "status_details_invalid"
    details: list[dict[str, Any]] = []
    seen: set[str] = set()
    for detail in raw_details:
        if not isinstance(detail, dict):
            return (), "status_detail_not_object"
        required_strings = (
            "instance_id",
            "status_id",
            "modifier_name",
            "owner_id",
            "source_id",
            "status_category",
        )
        if any(
            not isinstance(detail.get(field_name), str)
            or not detail.get(field_name)
            for field_name in required_strings
        ):
            return (), "status_detail_identity_invalid"
        if detail["owner_id"] != unit_id:
            return (), "status_detail_owner_mismatch"
        if detail["instance_id"] in seen:
            return (), "status_detail_instance_ambiguous"
        seen.add(detail["instance_id"])
        details.append(detail)
    return tuple(details), ""


def _status_details_by_instance(
    state: BattleState,
    unit_id: str,
    instance_id: str,
) -> tuple[dict[str, Any], ...]:
    return tuple(
        detail
        for detail in _status_details(state, unit_id)
        if detail.get("instance_id") == instance_id
    )


def _status_dynamic_value_mutation(
    state: BattleState,
    operation: DynamicValueOperationIR,
    request: DynamicValueExecutionRequest,
    resolved_scope: Mapping[str, Any],
    value: float,
    evaluation: Mapping[str, Any],
) -> tuple[Mutation | None, str]:
    if resolved_scope.get("scope_kind") != "status":
        return None, ""
    target_id = str(resolved_scope.get("target_id") or "")
    instance_id = str(resolved_scope.get("status_instance_id") or "")
    unit = state.units.get(target_id)
    if unit is None:
        return None, "dynamic_status_target_missing"
    before_details = list(unit.flags.get("status_details", ()))
    after_details: list[JSONValue] = []
    found = False
    for detail in before_details:
        if not isinstance(detail, dict) or detail.get("instance_id") != instance_id:
            after_details.append(detail)
            continue
        found = True
        raw_dynamic_values = detail.get("dynamic_values")
        if raw_dynamic_values is not None and not isinstance(raw_dynamic_values, Mapping):
            return None, "status_dynamic_values_invalid"
        dynamic_values = dict(raw_dynamic_values or {})
        raw_by_name = dynamic_values.get("__by_name")
        raw_by_hash = dynamic_values.get("__by_hash")
        if any(
            item is not None and not isinstance(item, Mapping)
            for item in (raw_by_name, raw_by_hash)
        ):
            return None, "status_dynamic_value_index_invalid"
        by_name = dict(raw_by_name or {})
        by_hash = dict(raw_by_hash or {})
        if any(
            not isinstance(key, str) or not _finite_number(item)
            for index in (by_name, by_hash)
            for key, item in index.items()
        ):
            return None, "status_dynamic_value_index_entry_invalid"
        dynamic_values[operation.destination_key] = float(value)
        by_name[operation.destination_key] = float(value)
        if operation.destination_hash is not None:
            dynamic_values[operation.destination_hash] = float(value)
            by_hash[operation.destination_hash] = float(value)
        dynamic_values["__by_name"] = by_name
        dynamic_values["__by_hash"] = by_hash
        after_details.append({**detail, "dynamic_values": dynamic_values})
    if not found:
        if _removed_status_detail(request, target_id) is not None:
            return None, ""  # The scoped store carries the write; do not resurrect the status.
        return None, "dynamic_status_instance_missing"
    if before_details == after_details:
        # The operation store still records this invocation; an unchanged
        # status projection must not emit the same mutation on every hit.
        return None, ""
    return Mutation(
        op="set",
        path=("units", target_id, "flags", "status_details"),
        before=before_details if "status_details" in unit.flags else None,
        after=after_details,
        reason=f"apply {request.opcode} status-scoped dynamic value write",
        source="effect_system",
        before_exists="status_details" in unit.flags,
        metadata={
            "effect_id": request.effect_id,
            "opcode": request.opcode,
            "source_id": request.source_id,
            "target_id": target_id,
            "status_instance_id": instance_id,
            "operation_id": operation.operation_id,
            "value_name": operation.destination_key,
            "hash": operation.destination_hash,
            "value": float(value),
            "numeric_evaluation": evaluation,
            "effect_source": operation.source.to_json(),
        },
    ), ""


def _dynamic_value_plan_payload(
    *,
    ok: bool,
    operation: DynamicValueOperationIR,
    request: DynamicValueExecutionRequest | None,
    operation_instance_id: str,
    before_state_fingerprint: str,
    resolved_scope: Mapping[str, Any],
    result_value: float | None,
    mutations: tuple[Mutation, ...],
    records: tuple[Mapping[str, Any], ...],
    evaluation: Mapping[str, Any] | None,
    blocked_reason: str,
    replayed: bool,
) -> dict[str, JSONValue]:
    return {
        "ok": ok,
        "operation": operation.to_json(),
        "request": request.to_json(detach=False) if request is not None else None,
        "operation_instance_id": operation_instance_id,
        "before_state_fingerprint": before_state_fingerprint,
        "resolved_scope": resolved_scope,
        "result_value": result_value,
        "mutations": [mutation.to_json(detach=False) for mutation in mutations],
        "records": list(records),
        "evaluation": evaluation,
        "blocked_reason": blocked_reason,
        "replayed": replayed,
    }


def _plan_id_from_payload(payload: Mapping[str, Any]) -> str:
    return "dynamic_value_plan:" + json_tree_digest(payload).hex()


def _dynamic_value_plan_id(plan: DynamicValuePlan) -> str:
    return _plan_id_from_payload(
        _dynamic_value_plan_payload(
            ok=plan.ok,
            operation=plan.operation,
            request=plan.request,
            operation_instance_id=plan.operation_instance_id,
            before_state_fingerprint=plan.before_state_fingerprint,
            resolved_scope=plan.resolved_scope,
            result_value=plan.result_value,
            mutations=plan.mutations,
            records=plan.records,
            evaluation=plan.evaluation,
            blocked_reason=plan.blocked_reason,
            replayed=plan.replayed,
        )
    )


def _make_dynamic_value_plan(
    *,
    ok: bool,
    operation: DynamicValueOperationIR,
    request: DynamicValueExecutionRequest | None,
    operation_instance_id: str,
    before_state_fingerprint: str,
    resolved_scope: Mapping[str, Any],
    result_value: float | None,
    mutations: tuple[Mutation, ...] = (),
    records: tuple[Mapping[str, Any], ...] = (),
    evaluation: Mapping[str, Any] | None = None,
    blocked_reason: str = "",
    replayed: bool = False,
) -> DynamicValuePlan:
    fields = {
        "ok": ok,
        "operation": operation,
        "request": request,
        "operation_instance_id": operation_instance_id,
        "before_state_fingerprint": before_state_fingerprint,
        "resolved_scope": resolved_scope,
        "result_value": result_value,
        "mutations": mutations,
        "records": records,
        "evaluation": evaluation,
        "blocked_reason": blocked_reason,
        "replayed": replayed,
    }
    return DynamicValuePlan(
        plan_id=_plan_id_from_payload(_dynamic_value_plan_payload(**fields)),
        **fields,
    )


def _finite_number(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def status_binding_sources(state: BattleState, unit_ids: tuple[str, ...]) -> tuple[dict[str, JSONValue], ...]:
    sources: list[dict[str, JSONValue]] = []
    seen: set[str] = set()
    for unit_id in unit_ids:
        if unit_id in seen:
            continue
        seen.add(unit_id)
        unit = state.units.get(unit_id)
        if unit is None:
            continue
        details = unit.flags.get("status_details", ())
        if not isinstance(details, (list, tuple)):
            continue
        for detail in details:
            if not isinstance(detail, dict):
                continue
            dynamic_values = detail.get("dynamic_values")
            source = binding_source_from_status_detail(detail, dynamic_values)
            if source is not None:
                sources.append(source)
    return tuple(sources)


def monster_skill_param_binding_sources(
    rules: RuleBook, state: BattleState, unit_id: str, action_id: str, level: int | None,
) -> tuple[dict[str, JSONValue], ...]:
    unit = state.units.get(unit_id)
    card = rules.monster_data_card_for_entity(unit.template_id) if unit else None
    definition = rules.action_definition(action_id, level) if level is not None else None
    if card is None or definition is None or unit.flags.get("monster_data_card_id") != card.card_id:
        return ()
    entries: dict[str, JSONValue] = {}
    hashes: set[str] = set()
    # ReadInfo hashes belong to the whole monster card. One action can read
    # another skill's parameters (for example the shared stacking debuff).
    for binding in (binding for skill_id in card.skill_ids
                    for binding in rules.skill_formula_bindings_for_action(f"monster_skill:{skill_id}", level)):
        if (binding.data_card_kind != "monster" or binding.data_card_id != card.card_id
                or binding.owner_entity_ref != unit.template_id or binding.coverage_status != "executable"):
            continue
        raw_hash = binding.scaling_basis_expr.get("dynamic_hash")
        value = binding.param_value.get("Value") if isinstance(binding.param_value, dict) else binding.param_value
        if (type(raw_hash) not in (str, int) or not str(raw_hash)
                or type(value) not in (int, float) or not math.isfinite(value)):
            continue
        if str(raw_hash) in hashes:
            return ()
        hashes.add(str(raw_hash))
        entry = {"scope": "monster_skill_param", "owner_id": unit_id, "hash": str(raw_hash),
                 "name": None, "value": float(value),
                 "source_trace": {"skill_formula_binding_id": binding.binding_id,
                                  "binding_source": binding.source.to_json()}}
        entries[_entry_key(entry)] = entry
    return ({"source_type": "monster_skill_param", "unit_id": unit_id, **_reindex({"entries": entries})},) if entries else ()


def monster_standalone_skill_param_binding_sources(
    rules: RuleBook, state: BattleState, unit_id: str, action_id: str,
) -> tuple[dict[str, JSONValue], ...]:
    """Bind card-declared skill params for a monster standalone ability.

    Monster cards declare DynamicValues ReadInfo bindings against their own skill
    rows. The monster_skill_param source keys off a skill action row, which an
    inserted standalone ability does not own; the emitted standalone action
    bindings carry the same card-scoped hash/value pairs.
    """

    unit = state.units.get(unit_id)
    card = rules.monster_data_card_for_entity(unit.template_id) if unit else None
    if card is None or unit.flags.get("monster_data_card_id") != card.card_id:
        return ()
    action_ref = action_id
    if action_id.startswith("standalone_ability_graph:"):
        graph = rules.standalone_ability_graph(action_id)
        if graph is None:
            return ()
        action_ref = f"standalone_ability:{graph.ability_name}"
    elif not action_id.startswith("standalone_ability:"):
        return ()
    entries: dict[str, JSONValue] = {}
    hashes: dict[str, float] = {}
    for binding in rules.skill_formula_bindings_for_action(action_ref, 0):
        if (
            binding.data_card_kind != "monster"
            or binding.data_card_id != card.card_id
            or binding.owner_entity_ref != unit.template_id
            or binding.coverage_status != "executable"
            or not isinstance(binding.scaling_basis_expr, dict)
        ):
            continue
        raw_hash = binding.scaling_basis_expr.get("dynamic_hash")
        value = (
            binding.param_value.get("Value")
            if isinstance(binding.param_value, dict)
            else binding.param_value
        )
        if (
            type(raw_hash) not in (str, int)
            or not str(raw_hash)
            or type(value) not in (int, float)
            or not math.isfinite(value)
        ):
            continue
        # The same card parameter can reach this action through more than one
        # formal projection (for example a damage task binding and the card
        # declaration). Identical hash/value pairs are one declaration; a
        # conflicting value for the same hash stays unbound.
        previous = hashes.get(str(raw_hash))
        if previous is not None:
            if previous != float(value):
                return ()
            continue
        hashes[str(raw_hash)] = float(value)
        entry = {
            "scope": "monster_standalone_skill_param",
            "owner_id": unit_id,
            "hash": str(raw_hash),
            "name": None,
            "value": float(value),
            "source_trace": {
                "skill_formula_binding_id": binding.binding_id,
                "binding_source": binding.source.to_json(),
            },
        }
        entries[_entry_key(entry)] = entry
    if not entries:
        return ()
    return (
        {
            "source_type": "monster_standalone_skill_param",
            "unit_id": unit_id,
            **_reindex({"entries": entries}),
        },
    )


def character_declared_dynamic_binding_source(
    rules: RuleBook, state: BattleState, unit_id: str,
    *, ability_instance_id: str = "", excluded_hashes: tuple[str, ...] = (),
) -> dict[str, JSONValue] | None:
    unit = state.units.get(unit_id)
    card = rules.character_data_card_for_entity(unit.template_id) if unit else None
    if card is None:
        return None
    bindings = rules.character_dynamic_value_bindings_for_card(card.card_id, detach=False)
    configured = bindings.get("by_hash") if isinstance(bindings, dict) else None
    if not isinstance(configured, dict):
        return None
    cache = getattr(state, "_declared_binding_cache", None)
    if cache is None:
        cache = {}
        object.__setattr__(state, "_declared_binding_cache", cache)
    cache_key = (unit_id, ability_instance_id, excluded_hashes)
    cached = cache.get(cache_key)
    if cached is not None and cached[0] is rules and cached[1] is bindings:
        return cached[2]
    stored = tuple(entry for entry in store_from_state(state).get("entries", {}).values()
                   if isinstance(entry, dict) and _entry_visible(entry, {
                       "target_id": unit_id, "ability_instance_id": ability_instance_id,
                   }))
    status_values = tuple(entry for source in status_binding_sources(state, (unit_id,))
                          for entry in source.get("entries", {}).values())
    entries = {}
    for key, binding in configured.items():
        if str(key) in excluded_hashes:
            continue
        info = binding.get("read_info") if isinstance(binding, dict) else None
        if (not isinstance(info, dict) or set(info) != {"Type", "Index"}
                or info.get("Type") != "None" or type(info.get("Index")) is not int or info["Index"] < 0
                or not isinstance(binding.get("source_path"), str) or not binding["source_path"]):
            continue
        producer = binding.get("value_producer")
        if producer == "owned_servant_identity":
            definitions = tuple(definition for definition in rules.ir.servant_definitions
                if definition.coverage_status == "executable" and any(
                    relation.coverage_status == "executable" and relation.owner_entity_ref == unit.template_id
                    for relation in definition.owner_relations))
            if len(definitions) != 1:
                continue
            definition = definitions[0]
            namespace, _, identifier = definition.servant_ref.partition(":")
            if namespace != "servant" or not identifier.isdecimal() or not 0 < int(identifier) <= 2 ** 53:
                continue
            value = float(int(identifier))
            committed = tuple(entry for entry in (*stored, *status_values) if str(entry.get("hash")) == str(key))
            if committed and any(not _finite_number(entry.get("value")) or entry["value"] != value for entry in committed):
                continue
            basis = "formal_owned_servant_identity"
            producer_sources = [definition.source.to_json()]
        elif producer is not None:
            continue
        else:
            candidates = tuple(entry for entry in stored if str(entry.get("hash")) == str(key))
            if not candidates:
                candidates = tuple(entry for entry in status_values if str(entry.get("hash")) == str(key))
            values = {float(entry["value"]) for entry in candidates if _finite_number(entry.get("value"))}
            # Conflicting committed writers require explicit scope resolution.
            if candidates and (len(values) != 1 or any(not _finite_number(entry.get("value")) for entry in candidates)):
                continue
            baseline = binding.get("initial_value", 0.0)
            if not _finite_number(baseline):
                continue
            value = next(iter(values), float(baseline))
            basis = "committed_dynamic_values" if candidates else "declared_mutable_numeric_slot_initial_value"
            producer_sources = [item.get("source_trace", {}) for item in candidates]
        entry = {"scope": "unit", "owner_id": unit_id, "hash": str(key), "name": binding.get("logical_name"), "value": value,
                 "source_trace": {"character_data_card": card.source.to_json(), "binding": binding,
                                   "value_basis": basis, "producer_sources": producer_sources}}
        entries[_entry_key(entry)] = entry
    result = (
        {
            "source_type": "character_declared_dynamic_values",
            "unit_id": unit_id,
            "binding_role": "declared_mutable_slot_default",
            **_reindex({"entries": entries}),
        }
        if entries
        else None
    )
    result = freeze_json(result)
    # Ponytail: bound query variants per immutable state. New state versions
    # start empty, so committed writes and status changes cannot reuse old values.
    if len(cache) >= 32:
        cache.clear()
    cache[cache_key] = (rules, bindings, result)
    return result


def ability_declared_dynamic_binding_source(
    rules: RuleBook,
    state: BattleState,
    ability_name: str,
    unit_id: str,
    *,
    ability_instance_id: str = "",
    excluded_hashes: tuple[str, ...] = (),
) -> dict[str, JSONValue] | None:
    """Declared ability-local mutable slots, defaulting unset slots to zero."""
    configured = rules.ability_phase_dynamic_value_bindings(ability_name, detach=False)
    if not isinstance(configured, dict):
        return None
    declared = configured.get("by_hash")
    if not isinstance(declared, dict):
        return None
    stored = tuple(
        entry
        for entry in store_from_state(state).get("entries", {}).values()
        if isinstance(entry, dict)
        and _entry_visible(
            entry,
            {"target_id": unit_id, "ability_instance_id": ability_instance_id},
        )
    )
    entries: dict[str, JSONValue] = {}
    for key, binding in declared.items():
        if str(key) in excluded_hashes:
            continue
        info = binding.get("read_info") if isinstance(binding, dict) else None
        if (
            not isinstance(info, dict)
            or set(info) != {"Type", "Index"}
            or info.get("Type") != "None"
            or type(info.get("Index")) is not int
            or info["Index"] < 0
        ):
            continue
        candidates = tuple(
            entry for entry in stored if str(entry.get("hash")) == str(key)
        )
        values = {
            float(entry["value"])
            for entry in candidates
            if _finite_number(entry.get("value"))
        }
        if candidates and (
            len(values) != 1
            or any(not _finite_number(entry.get("value")) for entry in candidates)
        ):
            continue
        entry = {
            "scope": "unit",
            "owner_id": unit_id,
            "hash": str(key),
            "name": None,
            "value": next(iter(values), 0.0),
            "source_trace": {
                "binding": binding,
                "value_basis": (
                    "committed_dynamic_values"
                    if candidates
                    else "declared_mutable_numeric_slot_initial_zero"
                ),
                "producer_sources": [
                    item.get("source_trace", {}) for item in candidates
                ],
            },
        }
        entries[_entry_key(entry)] = entry
    if not entries:
        return None
    return {
        "source_type": "ability_declared_dynamic_values",
        "unit_id": unit_id,
        "ability_name": ability_name,
        "binding_role": "declared_mutable_slot_default",
        **_reindex({"entries": entries}),
    }


def character_skill_param_binding_sources(
    rules: RuleBook,
    state: BattleState,
    unit_ids: tuple[str, ...],
    *,
    action_level: int | None = None,
    current_action_trigger_key: str | None = None,
    excluded_hashes: tuple[str, ...] = (),
    excluded_names: tuple[str, ...] = (),
    include_unowned_rank_defaults: bool = False,
) -> tuple[dict[str, JSONValue], ...]:
    sources: list[dict[str, JSONValue]] = []
    seen: set[str] = set()
    for unit_id in unit_ids:
        if unit_id in seen:
            continue
        seen.add(unit_id)
        unit = state.units.get(unit_id)
        if unit is None:
            continue
        source = character_skill_param_binding_source(
            rules,
            state,
            unit_id,
            action_level=action_level,
            current_action_trigger_key=current_action_trigger_key,
            excluded_hashes=excluded_hashes,
            excluded_names=excluded_names,
        )
        if source is not None:
            sources.append(source)
        rank_source = _character_rank_param_binding_source(
            rules, state, unit_id, excluded_hashes,
            include_unowned_rank_defaults=include_unowned_rank_defaults,
        )
        if rank_source is not None:
            sources.append(rank_source)
        trace_owner_id = str(unit.flags.get("owner_id") or "") if unit.flags.get("summon_kind") == "servant" else unit_id
        declared = {
            *(
                str(key)
                for source in sources
                if source.get("unit_id") in {unit_id, trace_owner_id}
                for key in (
                    source.get("by_hash", {}).keys()
                    if isinstance(source.get("by_hash"), dict)
                    else ()
                )
            ),
            *excluded_hashes,
        }
        trace_source = character_trace_param_binding_source(
            rules, state, unit_id, excluded_hashes=tuple(sorted(declared)),
        )
        if trace_source is not None:
            sources.append(trace_source)
    return tuple(sources)


def character_trace_param_binding_source(
    rules: RuleBook,
    state: BattleState,
    unit_id: str,
    *,
    excluded_hashes: tuple[str, ...] = (),
) -> dict[str, JSONValue] | None:
    """Read selected trace parameters through their formal build slots.

    SkillTreeParam values are declared on the character config and carried by
    the trace node's ability-hook mechanism slot or, for rows whose effect lives
    in source-gated ability tasks instead of a dedicated ability, by the
    trace_skill_point_param slot.  Only explicitly selected, executable trace
    nodes supply values; an unselected or blocked node never falls back to its
    raw param list.
    """

    unit = state.units.get(unit_id)
    if unit is None:
        return None
    if unit.flags.get("summon_kind") == "servant":
        definition = rules.servant_definition(str(unit.flags.get("servant_definition_id") or ""))
        owner = state.units.get(str(unit.flags.get("owner_id") or ""))
        if definition is None or owner is None or definition.owner_relation_for(owner.template_id) is None:
            return None
        unit, unit_id = owner, owner.unit_id
    card_id = unit.flags.get("character_data_card_id")
    if card_id is not None:
        if not isinstance(card_id, str) or not card_id:
            return None
        card = rules.character_data_card(card_id)
        if card is None or card.entity_ref != unit.template_id:
            return None
    else:
        card = rules.character_data_card_for_entity(unit.template_id)
    if card is None:
        return None
    selected = unit.flags.get("selected_trace_node_ids")
    if not isinstance(selected, (list, tuple)) or not selected:
        return None
    selected_ids = {
        item for item in selected if isinstance(item, str) and item
    }
    excluded = {str(item) for item in excluded_hashes if str(item)}
    entries: dict[str, JSONValue] = {}
    for node in rules.character_trace_nodes_for_card(card.card_id):
        if (
            node.trace_node_id not in selected_ids
            or node.coverage_status != "executable"
            or node.blocked_reason
        ):
            continue
        for slot_id in node.linked_mechanism_slot_ids:
            slot = rules.character_mechanism_slot(slot_id)
            if (
                slot is None
                or slot.character_data_card_id != card.card_id
                or slot.mechanism_kind
                not in {"trace_ability_hook", "trace_skill_point_param"}
            ):
                continue
            if (
                slot.mechanism_kind == "trace_skill_point_param"
                and (
                    slot.coverage_status != "executable"
                    or slot.blocked_reason
                )
            ):
                continue
            semantics = slot.semantics if isinstance(slot.semantics, dict) else {}
            bindings = semantics.get("dynamic_value_bindings")
            by_hash = bindings.get("by_hash") if isinstance(bindings, dict) else None
            params = semantics.get("param_values")
            if not isinstance(by_hash, dict) or not isinstance(params, (list, tuple)):
                continue
            for raw_hash, binding in by_hash.items():
                if not isinstance(binding, dict) or str(raw_hash) in excluded:
                    continue
                index = binding.get("param_index")
                if (
                    type(index) is not int
                    or not 0 <= index < len(params)
                    or not _finite_number(params[index])
                ):
                    continue
                entry = {
                    "scope": "character_trace_param",
                    "owner_id": unit_id,
                    "status_id": None,
                    "status_instance_id": None,
                    "effect_id": None,
                    "name": None,
                    "hash": str(raw_hash),
                    "value": float(params[index]),
                    "source_trace": {
                        "character_data_card_id": card.card_id,
                        "character_data_card_source": card.source.to_json(),
                        "trace_node_id": node.trace_node_id,
                        "trace_node_source": node.source.to_json(),
                        "mechanism_slot_id": slot.mechanism_slot_id,
                        "mechanism_slot_source": slot.source.to_json(),
                        "dynamic_value_binding": binding,
                        "param_values": list(params),
                        "selection_source": "character_build_assembly",
                    },
                }
                entries[_entry_key(entry)] = entry
    if not entries:
        return None
    indexed = _reindex({"entries": entries})
    return {
        "source_type": "character_trace_param",
        "unit_id": unit_id,
        "character_data_card_id": card.card_id,
        **indexed,
    }


def _character_rank_param_binding_source(
    rules: RuleBook, state: BattleState, unit_id: str, excluded_hashes: tuple[str, ...],
    *, include_unowned_rank_defaults: bool = False,
) -> dict[str, JSONValue] | None:
    unit = state.units[unit_id]
    if (unit.flags.get("build_mode") != "assembled_character_build"
            or unit.flags.get("character_build_battle_admission_status") != "admitted"):
        return None
    card = rules.character_data_card(str(unit.flags.get("character_data_card_id") or ""))
    selected = unit.flags.get("selected_eidolon_slot_ids")
    if (card is None or card.entity_ref != unit.template_id
            or not isinstance(selected, (list, tuple))):
        return None
    configured = rules.character_dynamic_value_bindings_for_card(card.card_id, detach=False).get("by_hash", {})
    if not isinstance(configured, dict):
        return None
    entries: dict[str, JSONValue] = {}
    seen_hashes: set[str] = set()
    ambiguous_hashes: set[str] = set()
    for slot in rules.character_eidolon_slots_for_card(card.card_id):
        if slot.eidolon_slot_id not in selected or slot.coverage_status != "executable" or slot.blocked_reason:
            continue
        bindings = slot.semantics.get("dynamic_value_bindings", {})
        by_hash = bindings.get("by_hash", {}) if isinstance(bindings, dict) else {}
        params = slot.semantics.get("param_values", ())
        if not isinstance(by_hash, dict) or not isinstance(params, (list, tuple)):
            continue
        for raw_hash, binding in by_hash.items():
            declaration = configured.get(raw_hash)
            if not isinstance(binding, dict) or not isinstance(declaration, dict) or str(raw_hash) in excluded_hashes:
                continue
            info = declaration.get("read_info")
            index = binding.get("param_index")
            if (not isinstance(info, dict) or info.get("Type") != "SkillRank"
                    or info != binding.get("read_info") or binding.get("rank") != slot.rank
                    or type(index) is not int or index != info.get("Index") or not 0 <= index < len(params)
                    or type(params[index]) not in (int, float) or not math.isfinite(params[index])):
                continue
            hash_key = str(raw_hash)
            if hash_key in seen_hashes:
                ambiguous_hashes.add(hash_key)
            seen_hashes.add(hash_key)
            entry = {
                "scope": "character_rank_param", "owner_id": unit_id,
                "hash": hash_key, "name": None, "value": float(params[index]),
                "source_trace": {
                    "character_data_card_id": card.card_id, "eidolon_slot_id": slot.eidolon_slot_id,
                    "eidolon_slot_source": slot.source.to_json(), "dynamic_value_binding": binding,
                    "selection_source": "character_build_assembly",
                },
            }
            entries[_entry_key(entry)] = entry
    if include_unowned_rank_defaults:
        # Runtime numeric consumers read a declared rank slot even when the
        # rank is not owned (for example an E0 talent formula or a battle-event
        # create parameter). The absent rank param is the zero baseline, not an
        # unbound hash. The generic source API keeps the strict no-entry contract
        # so build/selection audits still prove which ranks are selected.
        eidolon_slots = rules.character_eidolon_slots_for_card(card.card_id)
        selected_ranks = {
            slot.rank
            for slot in eidolon_slots
            if slot.eidolon_slot_id in selected
            and slot.coverage_status == "executable"
            and not slot.blocked_reason
        }
        available_ranks = {slot.rank for slot in eidolon_slots}
        for raw_hash, declaration in configured.items():
            hash_key = str(raw_hash)
            if (
                not isinstance(declaration, dict)
                or hash_key in excluded_hashes
                or hash_key in seen_hashes
            ):
                continue
            info = declaration.get("read_info")
            if not isinstance(info, dict) or info.get("Type") != "SkillRank":
                continue
            trigger_key = info.get("TriggerKey")
            index = info.get("Index")
            if (
                not isinstance(trigger_key, str)
                or not trigger_key.startswith("Rank")
                or type(index) is not int
                or isinstance(index, bool)
                or index < 0
            ):
                continue
            suffix = trigger_key.removeprefix("Rank")
            if not suffix.isdigit():
                continue
            rank = int(suffix)
            if rank not in available_ranks or rank in selected_ranks:
                continue
            entry = {
                "scope": "character_rank_param", "owner_id": unit_id,
                "hash": hash_key, "name": None, "value": 0.0,
                "binding_role": "declared_rank_param_default",
                "source_trace": {
                    "character_data_card_id": card.card_id,
                    "dynamic_value_binding": declaration,
                    "read_info": info,
                    "value_basis": "unowned_rank_param_zero_baseline",
                    "selection_source": "character_build_assembly",
                },
            }
            entries[_entry_key(entry)] = entry
    indexed = _reindex({"entries": {key: value for key, value in entries.items()
                                   if value["hash"] not in ambiguous_hashes}})
    if not indexed["entries"]:
        return None
    return {"source_type": "character_rank_param_slot", "unit_id": unit_id,
            "character_data_card_id": card.card_id, **indexed}


def servant_skill_param_binding_source(
    rules: RuleBook, state: BattleState, unit_id: str, *,
    excluded_hashes: tuple[str, ...] = (),
) -> dict[str, JSONValue] | None:
    from .summon import _formal_owned_combatant_build

    unit = state.units[unit_id]
    definition = rules.servant_definition(str(unit.flags.get("servant_definition_id") or ""))
    owner = state.units.get(str(unit.flags.get("owner_id") or ""))
    if definition is None or owner is None or definition.servant_ref != unit.template_id:
        return None
    build, reason = _formal_owned_combatant_build(owner, definition)
    if reason or build is None or unit.flags.get("owned_combatant_build_result") != build.to_json():
        return None
    slots = definition.action_set.get("skill_index_map", {})
    configured = definition.action_set.get("dynamic_value_bindings", {}).get("by_hash", {})
    entries: dict[str, JSONValue] = {}
    for raw_hash, binding in configured.items():
        info = binding.get("read_info")
        if not isinstance(info, dict) or info.get("Type") != "SkillParam" or str(raw_hash) in excluded_hashes:
            continue
        index = info.get("Index")
        matches = tuple(entry for entry in slots.values()
                        if entry.get("role_source", {}).get("skill_trigger_key") == info.get("TriggerKey"))
        if len(matches) != 1 or type(index) is not int or index < 0:
            continue
        levels = tuple(level for level in build.effective_skill_levels if level.action_id == matches[0].get("action_ref"))
        if len(levels) != 1:
            continue
        level = levels[0]
        action = rules.action_definition(level.action_id, level.effective_level)
        if action is None or action.coverage_status != "executable" or index >= len(action.param_list):
            continue
        value = action.param_list[index]
        value = value.get("Value") if isinstance(value, dict) else value
        if not _finite_number(value):
            continue
        entry = {"scope": "servant_skill_param", "owner_id": unit_id, "hash": str(raw_hash),
                 "name": None, "value": float(value),
                 "source_trace": {"servant_definition": definition.source.to_json(),
                                  "skill_definition": action.source.to_json(),
                                  "owned_build_fingerprint": build.result_fingerprint, "binding": binding}}
        entries[_entry_key(entry)] = entry
    return {"source_type": "servant_skill_param", "unit_id": unit_id, **_reindex({"entries": entries})} if entries else None


def servant_declared_dynamic_binding_source(
    rules: RuleBook, state: BattleState, unit_id: str,
    *, ability_instance_id: str = "", excluded_hashes: tuple[str, ...] = (),
) -> dict[str, JSONValue] | None:
    """Bind a servant definition's declared mutable numeric slots.

    Servant configs declare ReadInfo Type "None" slots exactly like avatar
    configs; committed values win, otherwise the declared baseline is zero.
    """

    unit = state.units.get(unit_id)
    if unit is None:
        return None
    definition_id = unit.flags.get("servant_definition_id")
    if not isinstance(definition_id, str) or not definition_id:
        return None
    definition = rules.servant_definition(definition_id)
    if definition is None or definition.servant_ref != unit.template_id:
        return None
    action_set = definition.action_set
    bindings = action_set.get("dynamic_value_bindings") if isinstance(action_set, dict) else None
    configured = bindings.get("by_hash") if isinstance(bindings, dict) else None
    if not isinstance(configured, dict):
        return None
    stored = tuple(
        entry
        for entry in store_from_state(state).get("entries", {}).values()
        if isinstance(entry, dict)
        and _entry_visible(entry, {
            "target_id": unit_id, "ability_instance_id": ability_instance_id,
        })
    )
    status_values = tuple(
        entry
        for source in status_binding_sources(state, (unit_id,))
        for entry in source.get("entries", {}).values()
    )
    skill_index_map = (
        action_set.get("skill_index_map")
        if isinstance(action_set, dict)
        else None
    )
    effective_levels = unit.flags.get("effective_skill_levels_by_action_id")
    entries: dict[str, JSONValue] = {}
    for key, binding in configured.items():
        if str(key) in excluded_hashes:
            continue
        info = binding.get("read_info") if isinstance(binding, dict) else None
        if (
            isinstance(info, dict)
            and set(info) == {"Type", "Index", "TriggerKey"}
            and info.get("Type") == "SkillParam"
            and type(info.get("Index")) is int
            and info["Index"] >= 0
        ):
            action_ref = ""
            default_level = 0
            if isinstance(skill_index_map, dict):
                for slot in skill_index_map.values():
                    if not isinstance(slot, dict):
                        continue
                    role_source = slot.get("role_source")
                    if (
                        isinstance(role_source, dict)
                        and role_source.get("skill_trigger_key")
                        == info.get("TriggerKey")
                    ):
                        action_ref = str(slot.get("action_ref") or "")
                        level = slot.get("default_level")
                        default_level = level if type(level) is int else 0
                        break
            level_value = (
                effective_levels.get(action_ref)
                if isinstance(effective_levels, dict)
                else None
            )
            level = level_value if type(level_value) is int else default_level
            definition = (
                rules.action_definition(action_ref, level) if action_ref else None
            )
            params = definition.param_list if definition is not None else ()
            value = None
            if 0 <= int(info["Index"]) < len(params):
                raw_param = params[int(info["Index"])]
                value = (
                    raw_param.get("Value")
                    if isinstance(raw_param, dict)
                    and set(raw_param) == {"Value"}
                    else raw_param
                )
            if not _finite_number(value):
                continue
            param_entry = {
                "scope": "unit",
                "owner_id": unit_id,
                "hash": str(key),
                "name": None,
                "value": float(value),
                "source_trace": {
                    "servant_definition": definition.source.to_json()
                    if definition is not None
                    else definition,
                    "binding": binding,
                    "value_basis": "servant_skill_param",
                    "param_index": int(info["Index"]),
                    "action_ref": action_ref,
                    "action_level": level,
                    "skill_definition": definition.to_json()
                    if definition is not None
                    else None,
                },
            }
            entries[_entry_key(param_entry)] = param_entry
            continue
        if (
            not isinstance(info, dict)
            or set(info) != {"Type", "Index"}
            or info.get("Type") != "None"
            or type(info.get("Index")) is not int
            or info["Index"] < 0
        ):
            continue
        candidates = tuple(entry for entry in stored if str(entry.get("hash")) == str(key))
        if not candidates:
            candidates = tuple(entry for entry in status_values if str(entry.get("hash")) == str(key))
        values = {float(entry["value"]) for entry in candidates if _finite_number(entry.get("value"))}
        if candidates and (len(values) != 1 or any(not _finite_number(entry.get("value")) for entry in candidates)):
            continue
        baseline = binding.get("initial_value", 0.0)
        if not _finite_number(baseline):
            continue
        entry = {
            "scope": "unit",
            "owner_id": unit_id,
            "hash": str(key),
            "name": None,
            "value": next(iter(values), float(baseline)),
            "source_trace": {
                "servant_definition": definition.source.to_json(),
                "binding": binding,
                "value_basis": "committed_dynamic_values" if candidates else "declared_mutable_numeric_slot_initial_value",
                "producer_sources": [item.get("source_trace", {}) for item in candidates],
            },
        }
        entries[_entry_key(entry)] = entry
    return (
        {
            "source_type": "servant_declared_dynamic_values",
            "unit_id": unit_id,
            "binding_role": "declared_mutable_slot_default",
            **_reindex({"entries": entries}),
        }
        if entries
        else None
    )


def servant_declared_dynamic_binding_source_for_owner(
    rules: RuleBook, state: BattleState, owner_unit_id: str, *,
    excluded_hashes: tuple[str, ...] = (),
) -> dict[str, JSONValue] | None:
    """Project a summoner unit's declared slots from its owned servants.

    Some servant modifiers synchronize display counters onto the summoner. The
    servant config declares those mutable slots, so the summoner unit resolves
    the same declared baseline.
    """

    owner = state.units.get(owner_unit_id)
    if owner is None:
        return None
    servants = [
        unit
        for unit in state.units.values()
        if unit.flags.get("owner_id") == owner_unit_id
        and unit.flags.get("servant_definition_id")
    ]
    merged: dict[tuple[str, float], dict[str, JSONValue]] = {}
    for servant in servants:
        source = servant_declared_dynamic_binding_source(
            rules,
            state,
            servant.unit_id,
            ability_instance_id="",
            excluded_hashes=excluded_hashes,
        )
        if source is None:
            continue
        for entry in source.get("entries", {}).values():
            if not isinstance(entry, dict):
                continue
            value = entry.get("value")
            if not _finite_number(value):
                continue
            merged[(str(entry.get("hash") or ""), float(value))] = entry
    entries: dict[str, JSONValue] = {}
    for (hash_key, value), entry in merged.items():
        projected = {
            "scope": "unit",
            "owner_id": owner_unit_id,
            "hash": hash_key,
            "name": None,
            "value": value,
            "source_trace": {
                "projected_from_owner_servant": True,
                "servant_source_trace": entry.get("source_trace", {}),
            },
        }
        entries[_entry_key(projected)] = projected
    return (
        {
            "source_type": "servant_declared_dynamic_values_projected_to_owner",
            "unit_id": owner_unit_id,
            "binding_role": "declared_mutable_slot_default",
            **_reindex({"entries": entries}),
        }
        if entries
        else None
    )


def character_skill_param_binding_source(
    rules: RuleBook,
    state: BattleState,
    unit_id: str,
    *,
    action_level: int | None = None,
    current_action_trigger_key: str | None = None,
    excluded_hashes: tuple[str, ...] = (),
    excluded_names: tuple[str, ...] = (),
) -> dict[str, JSONValue] | None:
    unit = state.units.get(unit_id)
    if unit is None:
        return None
    # A battle-event unit reads the skill parameters declared by the character
    # that created it; the values stay bound to the acting event unit.
    param_unit = unit
    if unit.flags.get("entity_type") == "battle_event":
        # Ownership can change without replacing the originating character build.
        creator_id = unit.flags.get("creation_source_unit_id", unit.flags.get("summoner_id"))
        creator = state.units.get(str(creator_id or ""))
        if creator is not None:
            param_unit = creator
    param_card_id = param_unit.flags.get("character_data_card_id")
    if param_card_id is not None:
        if not isinstance(param_card_id, str) or not param_card_id:
            return None
        card = rules.character_data_card(param_card_id)
        if card is None or card.entity_ref != param_unit.template_id:
            return None
    else:
        card = rules.character_data_card_for_entity(param_unit.template_id)
    if card is None:
        return servant_skill_param_binding_source(rules, state, unit_id, excluded_hashes=excluded_hashes)
    config_bindings = rules.character_dynamic_value_bindings_for_card(card.card_id, detach=False)
    if not isinstance(config_bindings, dict):
        return None
    by_hash = config_bindings.get("by_hash")
    if not isinstance(by_hash, dict):
        return None

    skill_levels_by_trigger_key = param_unit.flags.get("skill_levels_by_trigger_key")
    if not isinstance(skill_levels_by_trigger_key, dict):
        skill_levels_by_trigger_key = {}
    param_declaring_unit_id = unit_id if param_unit is unit else str(unit.flags.get("summoner_id") or "")
    cacheable = type(skill_levels_by_trigger_key) is FrozenJSONDict and type(config_bindings) is FrozenJSONDict
    cache = getattr(skill_levels_by_trigger_key, "_skill_param_sources", {}) if cacheable else {}
    cache_key = (card.card_id, unit_id, param_declaring_unit_id, type(action_level), action_level,
                 current_action_trigger_key, excluded_hashes, excluded_names)
    cached = cache.get(cache_key)
    if cached is not None and cached[0] is rules and cached[1] is config_bindings:
        return cached[2]
    param_slots = tuple(
        slot
        for slot in rules.character_mechanism_slots_for_card(card.card_id)
        if slot.mechanism_kind == "skill_param_slot" and slot.coverage_status == "executable"
    )
    entries: dict[str, JSONValue] = {}
    for raw_hash, binding in by_hash.items():
        if not isinstance(binding, dict):
            continue
        read_info = binding.get("read_info")
        if not isinstance(read_info, dict):
            continue
        if read_info.get("Type") != "SkillParam":
            continue
        trigger_key = read_info.get("TriggerKey")
        param_index = read_info.get("Index")
        if (
            not isinstance(trigger_key, str)
            or not trigger_key
            or not isinstance(param_index, int)
            or isinstance(param_index, bool)
            or param_index < 0
        ):
            continue
        selected_level, level_source = _skill_param_level_for_trigger(
            trigger_key,
            action_level=action_level,
            current_action_trigger_key=current_action_trigger_key,
            skill_levels_by_trigger_key=skill_levels_by_trigger_key,
        )
        if selected_level is None:
            continue
        slot = _select_skill_param_slot(param_slots, trigger_key, param_index, selected_level)
        if slot is None:
            continue
        value = _slot_param_value(slot)
        if value is None:
            continue
        entry = {
            "scope": "character_skill_param",
            "owner_id": unit_id,
            "status_id": None,
            "status_instance_id": None,
            "effect_id": None,
            "name": None,
            "hash": str(raw_hash),
            "value": value,
            "source_trace": {
                "character_data_card_id": card.card_id,
                "character_data_card_source": card.source.to_json(),
                "skill_param_slot_id": slot.mechanism_slot_id,
                "skill_param_slot_source": slot.source.to_json(),
                "dynamic_value_binding": binding,
                "skill_level": selected_level,
                "skill_level_source": level_source,
                "binding_owner_unit_id": unit_id,
                "param_declaring_unit_id": param_declaring_unit_id,
            },
        }
        entries[_entry_key(entry)] = entry
    if not entries:
        return None
    indexed = _reindex({"entries": entries})
    excluded_hash_keys = {str(item) for item in excluded_hashes if str(item)}
    excluded_name_keys = {str(item) for item in excluded_names if str(item)}
    if excluded_hash_keys or excluded_name_keys:
        indexed = _reindex(
            {
                "entries": {
                    key: entry
                    for key, entry in indexed["entries"].items()
                    if str(entry.get("hash") or "") not in excluded_hash_keys
                    and str(entry.get("name") or "") not in excluded_name_keys
                }
            }
        )
    if not indexed["entries"]:
        return None
    result = {
        "source_type": "character_skill_param_slot",
        "unit_id": unit_id,
        "character_data_card_id": card.card_id,
        "entries": indexed["entries"],
        "by_hash": indexed["by_hash"],
        "by_name": indexed["by_name"],
    }
    if cacheable:
        result = freeze_json(result)
        # Ponytail: only 64 query variants per immutable skill-level selection.
        # A changed build gets a new selection object and therefore a fresh cache.
        if len(cache) >= 64:
            cache.clear()
        cache[cache_key] = (rules, config_bindings, result)
        skill_levels_by_trigger_key._skill_param_sources = cache
    return result


def character_skill_param_declared_keys(
    rules: RuleBook,
    state: BattleState,
    unit_id: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Reserve canonical skill/rank keys even when a selected slot is unavailable."""

    unit = state.units.get(unit_id)
    if unit is None:
        return (), ()
    card = rules.character_data_card_for_entity(unit.template_id)
    if card is None:
        return (), ()
    bindings = rules.character_dynamic_value_bindings_for_card(card.card_id, detach=False)
    by_hash = bindings.get("by_hash") if isinstance(bindings, dict) else None
    if not isinstance(by_hash, dict):
        return (), ()
    hashes = tuple(
        sorted(
            str(raw_hash)
            for raw_hash, binding in by_hash.items()
            if isinstance(binding, dict)
            and isinstance(binding.get("read_info"), dict)
            and binding["read_info"].get("Type") in {"SkillParam", "SkillRank", "SkillTreeParam"}
        )
    )
    return hashes, ()


def _skill_param_level_for_trigger(
    trigger_key: str,
    *,
    action_level: int | None,
    current_action_trigger_key: str | None,
    skill_levels_by_trigger_key: dict[object, object],
) -> tuple[int | None, str]:
    configured = trigger_key in skill_levels_by_trigger_key
    configured_level = skill_levels_by_trigger_key.get(trigger_key)
    if (
        isinstance(configured_level, int)
        and not isinstance(configured_level, bool)
        and configured_level > 0
    ):
        return configured_level, "unit.skill_levels_by_trigger_key"
    if configured:
        return None, "skill_level_invalid_for_trigger_key"
    if (
        trigger_key == current_action_trigger_key
        and isinstance(action_level, int)
        and not isinstance(action_level, bool)
        and action_level > 0
    ):
        return action_level, "current_action_level"
    return None, "skill_level_missing_for_trigger_key"


def _select_skill_param_slot(
    slots: tuple[Any, ...],
    trigger_key: str,
    param_index: int,
    action_level: int,
) -> Any | None:
    if (
        not isinstance(param_index, int)
        or isinstance(param_index, bool)
        or param_index < 0
        or not isinstance(action_level, int)
        or isinstance(action_level, bool)
        or action_level <= 0
    ):
        return None
    matches = [
        slot
        for slot in slots
        if slot.semantics.get("skill_trigger_key") == trigger_key
        and isinstance(slot.semantics.get("param_index"), int)
        and not isinstance(slot.semantics.get("param_index"), bool)
        and slot.semantics.get("param_index") == param_index
    ]
    if not matches:
        return None
    level_matches = [
        slot
        for slot in matches
        if isinstance(slot.semantics.get("level"), int)
        and not isinstance(slot.semantics.get("level"), bool)
        and slot.semantics.get("level") == action_level
    ]
    if len(level_matches) != 1:
        return None
    return level_matches[0]


def _slot_param_value(slot: Any) -> float | None:
    value = slot.semantics.get("param_value")
    if isinstance(value, dict):
        value = value.get("Value")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def binding_source_from_status_detail(
    detail: dict[str, Any],
    dynamic_values: object,
) -> dict[str, JSONValue] | None:
    # Binding consumers only read this projection. A committed status version
    # owns its cache; changed stacks, duration or values produce a new version.
    cacheable = type(detail) is FrozenJSONDict and dynamic_values is detail.get("dynamic_values")
    cached = getattr(detail, "_status_binding_source", None) if cacheable else None
    if cached is not None:
        return cached
    filtered_cacheable = type(detail) is FrozenJSONDict and type(dynamic_values) is FrozenJSONDict and not cacheable
    filtered_cached = getattr(detail, "_filtered_binding_source", None) if filtered_cacheable else None
    if filtered_cached is not None and filtered_cached[0] is dynamic_values:
        return filtered_cached[1]
    entries: dict[str, JSONValue] = {}
    source_trace = detail.get("source_trace", {})
    owner_id = str(detail.get("owner_id") or "")
    status_id = str(detail.get("status_id") or "")
    status_instance_id = str(detail.get("instance_id") or "")
    stacks = detail.get("stacks")
    if isinstance(stacks, (int, float)) and not isinstance(stacks, bool):
        for key in ("Layer", "layer", "stacks"):
            entry = {
                "scope": "status_layer",
                "owner_id": owner_id,
                "status_id": status_id,
                "status_instance_id": status_instance_id,
                "name": key,
                "hash": key,
                "value": float(stacks),
                "source_trace": source_trace,
            }
            entries[_entry_key(entry)] = entry
    remaining_duration = detail.get("remaining_duration")
    if isinstance(remaining_duration, (int, float)) and not isinstance(remaining_duration, bool):
        for key in ("LifeTime", "life_time", "remaining_duration"):
            entry = {
                "scope": "status_lifetime",
                "owner_id": owner_id,
                "status_id": status_id,
                "status_instance_id": status_instance_id,
                "name": key,
                "hash": key,
                "value": float(remaining_duration),
                "source_trace": source_trace,
            }
            entries[_entry_key(entry)] = entry
    if isinstance(dynamic_values, dict):
        indexed_hash_values = dynamic_values.get("__by_hash")
        indexed_hash_keys = (
            {str(key) for key in indexed_hash_values}
            if isinstance(indexed_hash_values, dict)
            else set()
        )
        for key, value in dynamic_values.items():
            if key.startswith("__") or not isinstance(value, (int, float)):
                continue
            if str(key) in indexed_hash_keys:
                continue
            entry = {
                "scope": "status",
                "owner_id": owner_id,
                "status_id": status_id,
                "status_instance_id": status_instance_id,
                "name": str(key),
                "hash": str(key),
                "value": float(value),
                "source_trace": source_trace,
            }
            entries[_entry_key(entry)] = entry
        by_hash = indexed_hash_values
        if isinstance(by_hash, dict):
            for key, value in by_hash.items():
                if not isinstance(value, (int, float)):
                    continue
                entry = {
                    "scope": "status",
                    "owner_id": owner_id,
                    "status_id": status_id,
                    "status_instance_id": status_instance_id,
                    "name": None,
                    "hash": str(key),
                    "value": float(value),
                    "source_trace": source_trace,
                }
                entries[_entry_key(entry)] = entry
    if not entries:
        return None
    indexed = _reindex({"entries": entries})
    result = {
        "source_type": "status_instance",
        "status_instance_id": str(detail.get("instance_id") or ""),
        "status_id": str(detail.get("status_id") or ""),
        "entries": indexed["entries"],
        "by_hash": indexed["by_hash"],
        "by_name": indexed["by_name"],
    }
    if cacheable:
        result = freeze_json(result)
        detail._status_binding_source = result
    elif filtered_cacheable:
        result = freeze_json(result)
        detail._filtered_binding_source = (dynamic_values, result)
    return result


def find_status_detail(
    state: BattleState,
    unit_id: str,
    modifier_name: str | None = None,
    status_id: str | None = None,
) -> dict[str, JSONValue] | None:
    unit = state.units.get(unit_id)
    if unit is None:
        return None
    details = unit.flags.get("status_details", ())
    if not isinstance(details, (list, tuple)):
        return None
    expected_status_id = status_id or (f"modifier:{modifier_name}" if modifier_name else None)
    for detail in details:
        if not isinstance(detail, dict):
            continue
        if expected_status_id is not None and detail.get("status_id") == expected_status_id:
            return detail
        if modifier_name is not None and detail.get("modifier_name") == modifier_name:
            return detail
    return None


def _entry_key(entry: dict[str, Any]) -> str:
    scope_kind = str(entry.get("scope") or entry.get("scope_kind") or "")
    hash_key = entry.get("hash")
    # Unit/combat slots are identified by their hash: the raw name is display
    # metadata, and writers may mention it or not. Keeping both spellings as
    # separate entries would make one committed slot ambiguous.
    normalized_name = (
        None
        if hash_key and scope_kind in {"unit", "combat"}
        else entry.get("name")
    )
    # Unit/combat slots belong to their holder (target_id); owner_id only
    # records which unit wrote the value, so it must not split one slot into
    # two entries with different owners.
    normalized_owner = (
        None if scope_kind in {"unit", "combat"} else entry.get("owner_id")
    )
    payload = {
        "scope": entry.get("scope"),
        "scope_kind": entry.get("scope_kind"),
        "lifecycle": entry.get("lifecycle"),
        "owner_id": normalized_owner,
        "target_id": entry.get("target_id"),
        "status_id": entry.get("status_id"),
        "status_instance_id": entry.get("status_instance_id"),
        "ability_instance_id": entry.get("ability_instance_id"),
        "event_id": entry.get("event_id"),
        "name": normalized_name,
        "hash": hash_key,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "dyn:" + hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:16]


def _reindex(store: dict[str, JSONValue]) -> dict[str, JSONValue]:
    entries = store.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    by_hash: dict[str, list[str]] = {}
    by_name: dict[str, list[str]] = {}
    for key, item in sorted(entries.items()):
        if not isinstance(item, dict):
            continue
        hash_key = item.get("hash")
        if isinstance(hash_key, str) and hash_key:
            by_hash.setdefault(hash_key, []).append(str(key))
        name = item.get("name")
        if isinstance(name, str) and name:
            by_name.setdefault(name, []).append(str(key))
    return {
        "entries": dict(sorted(entries.items())),
        "by_hash": {key: value for key, value in sorted(by_hash.items())},
        "by_name": {key: value for key, value in sorted(by_name.items())},
        "operation_ledger": dict(
            sorted(
                (
                    store.get("operation_ledger", {}).items()
                    if isinstance(store.get("operation_ledger"), dict)
                    else ()
                )
            )
        ),
    }
