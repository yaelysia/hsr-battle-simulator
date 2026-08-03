from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..core.model import BattleState, JSONValue, Mutation
from ..core.settlement import SettlementRecord
from ..immutable_json import freeze_json, thaw_json
from ..rules.expression_ir import DynamicValueOperationIR, NumericOperandIR
from ..rules.rulebook import RuleBook
from ..rules.value_binding import resolve_runtime_numeric_expression
from .unit_stats import ability_property_value


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

    def to_json(self) -> dict[str, JSONValue]:
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
            "binding_sources": [thaw_json(source) for source in self.binding_sources],
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
        if self.plan_id != _dynamic_value_plan_id(self):
            raise ValueError("dynamic value plan identity is inconsistent")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "schema_version": DYNAMIC_VALUE_PLAN_SCHEMA,
            "ok": self.ok,
            "plan_id": self.plan_id,
            "operation": self.operation.to_json(),
            "request": self.request.to_json() if self.request is not None else None,
            "operation_instance_id": self.operation_instance_id,
            "before_state_fingerprint": self.before_state_fingerprint,
            "resolved_scope": thaw_json(self.resolved_scope),
            "result_value": self.result_value,
            "mutations": [mutation.to_json() for mutation in self.mutations],
            "records": [thaw_json(record) for record in self.records],
            "evaluation": thaw_json(self.evaluation),
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


def empty_dynamic_value_store() -> dict[str, JSONValue]:
    return {"entries": {}, "by_hash": {}, "by_name": {}, "operation_ledger": {}}


def normalized_dynamic_value_store(value: object) -> dict[str, JSONValue]:
    if value is None:
        return empty_dynamic_value_store()
    return _strict_dynamic_value_store(value)


def store_from_state(state: BattleState) -> dict[str, JSONValue]:
    return normalized_dynamic_value_store(state.global_flags.get("dynamic_value_store"))


def binding_source_from_store(
    store: object,
    *,
    excluded_status_instance_ids: tuple[str, ...] = (),
    excluded_hashes: tuple[str, ...] = (),
    excluded_names: tuple[str, ...] = (),
) -> dict[str, JSONValue]:
    normalized = normalized_dynamic_value_store(store)
    excluded = {item for item in excluded_status_instance_ids if item}
    excluded_hash_keys = {str(item) for item in excluded_hashes if str(item)}
    excluded_name_keys = {str(item) for item in excluded_names if str(item)}
    if excluded or excluded_hash_keys or excluded_name_keys:
        entries = normalized.get("entries")
        filtered_entries = {
            key: entry
            for key, entry in (entries.items() if isinstance(entries, dict) else ())
            if not isinstance(entry, dict)
            or (
                str(entry.get("status_instance_id") or "") not in excluded
                and str(entry.get("hash") or "") not in excluded_hash_keys
                and str(entry.get("name") or "") not in excluded_name_keys
            )
        }
        normalized = _reindex({"entries": filtered_entries})
    return {
        "source_type": "dynamic_value_store",
        "entries": normalized["entries"],
        "by_hash": normalized["by_hash"],
        "by_name": normalized["by_name"],
    }


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
    target_id = _resolve_request_alias(operation.target_alias, request)
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
    operand_value, evaluation, operand_reason = _resolve_operand(
        state,
        store,
        operation.operand,
        request,
        resolved_scope,
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
    after_store = _reindex({"entries": entries, "operation_ledger": ledger})
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
    try:
        expected = plan_dynamic_value_operation(state, plan.operation, plan.request)
        matches = expected.ok and expected.to_json() == plan.to_json()
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


def dynamic_value_state_fingerprint(state: BattleState) -> str:
    encoded = json.dumps(
        state.snapshot().to_json(),
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "state:" + hashlib.sha256(encoded).hexdigest()


def _strict_dynamic_value_store(value: object) -> dict[str, JSONValue]:
    if value is None:
        return empty_dynamic_value_store()
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


def _resolve_request_alias(
    alias: object,
    request: DynamicValueExecutionRequest,
) -> str:
    return {
        "Caster": request.caster_id,
        "ModifierOwnerEntity": request.owner_id or request.caster_id,
        "ParamEntity": request.param_entity_id,
        "CurrentActionTarget": request.current_action_target_id,
        "LevelEntity": "level:global",
    }.get(str(alias or ""), "")


def _resolved_scope(
    state: BattleState,
    operation: DynamicValueOperationIR,
    request: DynamicValueExecutionRequest,
    target_id: str,
) -> tuple[dict[str, JSONValue], str]:
    scope_kind = operation.scope_kind
    if scope_kind == "contextual":
        if request.status_instance_id:
            scope_kind = "status"
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
) -> tuple[float | None, dict[str, JSONValue], str]:
    if operand.coverage_status != "executable":
        return None, {}, f"numeric_operand_blocked:{operand.blocked_reason}"
    sources = _operand_binding_sources(store, request, resolved_scope)
    evaluation: dict[str, JSONValue]
    value: float | None = None
    reason = ""
    if operand.operand_kind == "expression":
        result = resolve_runtime_numeric_expression(
            thaw_json(operand.expression),
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
        thaw_json(source)
        for source in request.binding_sources
        if source.get("source_type") != "dynamic_value_store"
    )
    entries = store.get("entries")
    visible = {
        key: entry
        for key, entry in (entries.items() if isinstance(entries, dict) else ())
        if isinstance(entry, dict) and _entry_visible(entry, resolved_scope)
    }
    indexed = _reindex({"entries": visible})
    return (
        *sources,
        {
            "source_type": "dynamic_value_store",
            "entries": indexed["entries"],
            "by_hash": indexed["by_hash"],
            "by_name": indexed["by_name"],
        },
    )


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
) -> tuple[float | None, dict[str, JSONValue], str]:
    parameters = operand.parameters
    source_alias = parameters.get("source_target_alias")
    source_id = _resolve_request_alias(source_alias, request) if source_alias else ""
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
            value = unit.hp / unit.max_hp if unit.max_hp > 0 else None
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
            ]
            if len(matches) != 1:
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
        return None, "dynamic_status_instance_missing"
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
            "numeric_evaluation": thaw_json(evaluation),
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
        "request": request.to_json() if request is not None else None,
        "operation_instance_id": operation_instance_id,
        "before_state_fingerprint": before_state_fingerprint,
        "resolved_scope": thaw_json(resolved_scope),
        "result_value": result_value,
        "mutations": [mutation.to_json() for mutation in mutations],
        "records": [thaw_json(record) for record in records],
        "evaluation": thaw_json(evaluation),
        "blocked_reason": blocked_reason,
        "replayed": replayed,
    }


def _plan_id_from_payload(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "dynamic_value_plan:" + hashlib.sha256(encoded).hexdigest()


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


def character_skill_param_binding_sources(
    rules: RuleBook,
    state: BattleState,
    unit_ids: tuple[str, ...],
    *,
    action_level: int | None = None,
    current_action_trigger_key: str | None = None,
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
        )
        if source is not None:
            sources.append(source)
    return tuple(sources)


def character_skill_param_binding_source(
    rules: RuleBook,
    state: BattleState,
    unit_id: str,
    *,
    action_level: int | None = None,
    current_action_trigger_key: str | None = None,
) -> dict[str, JSONValue] | None:
    unit = state.units.get(unit_id)
    if unit is None:
        return None
    card_id = unit.flags.get("character_data_card_id")
    card = rules.character_data_card(str(card_id)) if isinstance(card_id, str) and card_id else None
    if card is None:
        card = rules.character_data_card_for_entity(unit.template_id)
    if card is None:
        return None
    config_bindings = rules.character_dynamic_value_bindings_for_card(card.card_id)
    if not isinstance(config_bindings, dict):
        return None
    by_hash = config_bindings.get("by_hash")
    if not isinstance(by_hash, dict):
        return None

    skill_levels_by_trigger_key = unit.flags.get("skill_levels_by_trigger_key")
    if not isinstance(skill_levels_by_trigger_key, dict):
        skill_levels_by_trigger_key = {}
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
        if not isinstance(trigger_key, str) or not isinstance(param_index, int):
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
            },
        }
        entries[_entry_key(entry)] = entry
    if not entries:
        return None
    indexed = _reindex({"entries": entries})
    return {
        "source_type": "character_skill_param_slot",
        "unit_id": unit_id,
        "character_data_card_id": card.card_id,
        "entries": indexed["entries"],
        "by_hash": indexed["by_hash"],
        "by_name": indexed["by_name"],
    }


def _skill_param_level_for_trigger(
    trigger_key: str,
    *,
    action_level: int | None,
    current_action_trigger_key: str | None,
    skill_levels_by_trigger_key: dict[object, object],
) -> tuple[int | None, str]:
    configured_level = skill_levels_by_trigger_key.get(trigger_key)
    if isinstance(configured_level, int):
        return configured_level, "unit.skill_levels_by_trigger_key"
    if trigger_key == current_action_trigger_key and isinstance(action_level, int):
        return action_level, "current_action_level"
    return None, "skill_level_missing_for_trigger_key"


def _select_skill_param_slot(
    slots: tuple[Any, ...],
    trigger_key: str,
    param_index: int,
    action_level: int,
) -> Any | None:
    matches = [
        slot
        for slot in slots
        if slot.semantics.get("skill_trigger_key") == trigger_key
        and slot.semantics.get("param_index") == param_index
    ]
    if not matches:
        return None
    level_matches = [slot for slot in matches if slot.semantics.get("level") == action_level]
    if not level_matches:
        return None
    return sorted(level_matches, key=lambda item: str(item.mechanism_slot_id))[0]


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
    return {
        "source_type": "status_instance",
        "status_instance_id": str(detail.get("instance_id") or ""),
        "status_id": str(detail.get("status_id") or ""),
        "entries": indexed["entries"],
        "by_hash": indexed["by_hash"],
        "by_name": indexed["by_name"],
    }


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
    payload = {
        "scope": entry.get("scope"),
        "scope_kind": entry.get("scope_kind"),
        "lifecycle": entry.get("lifecycle"),
        "owner_id": entry.get("owner_id"),
        "target_id": entry.get("target_id"),
        "status_id": entry.get("status_id"),
        "status_instance_id": entry.get("status_instance_id"),
        "ability_instance_id": entry.get("ability_instance_id"),
        "event_id": entry.get("event_id"),
        "name": entry.get("name"),
        "hash": entry.get("hash"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "dyn:" + hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:16]


def _reindex(store: dict[str, JSONValue]) -> dict[str, JSONValue]:
    entries = store.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    by_hash: dict[str, list[str]] = {}
    by_name: dict[str, list[str]] = {}
    for key, item in entries.items():
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
