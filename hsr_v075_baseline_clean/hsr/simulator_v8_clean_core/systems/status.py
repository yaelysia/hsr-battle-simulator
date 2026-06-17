from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from ..core.model import BattleState, JSONValue, Mutation
from ..core.settlement import SettlementRecord
from ..rules.ir import EffectIR, RuleEntity
from ..rules.rulebook import RuleBook


SUPPORTED_ADD_MODIFIER_ALIASES = {"Caster", "ModifierOwnerEntity", "ParamEntity", "CurrentActionTarget"}


@dataclass(frozen=True)
class StatusInstance:
    instance_id: str
    status_id: str
    modifier_name: str
    owner_id: str
    source_id: str
    caster_id: str
    stacks: int = 1
    max_stacks: int | None = None
    duration: float | None = None
    dynamic_values: dict[str, JSONValue] = field(default_factory=dict)
    source_trace: dict[str, JSONValue] = field(default_factory=dict)
    modifiers: tuple[dict[str, JSONValue], ...] = ()
    trigger_ids_by_event: dict[str, tuple[str, ...]] = field(default_factory=dict)
    unsupported: tuple[str, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "instance_id": self.instance_id,
            "status_id": self.status_id,
            "modifier_name": self.modifier_name,
            "owner_id": self.owner_id,
            "source_id": self.source_id,
            "caster_id": self.caster_id,
            "stacks": self.stacks,
            "max_stacks": self.max_stacks,
            "duration": self.duration,
            "dynamic_values": self.dynamic_values,
            "source_trace": self.source_trace,
            "modifiers": list(self.modifiers),
            "trigger_ids_by_event": {
                event: list(trigger_ids)
                for event, trigger_ids in sorted(self.trigger_ids_by_event.items())
            },
            "unsupported": list(self.unsupported),
        }


@dataclass(frozen=True)
class StatusApplicationResult:
    ok: bool
    mutations: tuple[Mutation, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    unsupported: tuple[str, ...] = ()
    status_instance: StatusInstance | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "mutations": [mutation.to_json() for mutation in self.mutations],
            "records": list(self.records),
            "unsupported": list(self.unsupported),
            "status_instance": self.status_instance.to_json() if self.status_instance else None,
        }


class StatusSystem:
    def __init__(self, rules: RuleBook | None = None):
        self.rules = rules

    def add_status(self, state: BattleState, unit_id: str, status_id: str, source: str) -> Mutation:
        unit = state.units[unit_id]
        statuses = tuple(dict.fromkeys((*unit.statuses, status_id)))
        return Mutation(
            op="set",
            path=("units", unit_id, "statuses"),
            before=list(unit.statuses),
            after=list(statuses),
            reason="add status",
            source=source,
            metadata={"status_id": status_id},
        )

    def remove_status(self, state: BattleState, unit_id: str, status_id: str, source: str) -> Mutation:
        unit = state.units[unit_id]
        statuses = tuple(item for item in unit.statuses if item != status_id)
        return Mutation(
            op="set",
            path=("units", unit_id, "statuses"),
            before=list(unit.statuses),
            after=list(statuses),
            reason="remove status",
            source=source,
            metadata={"status_id": status_id},
        )

    def apply_add_modifier(
        self,
        state: BattleState,
        effect: EffectIR,
        *,
        caster_id: str,
        source_id: str,
        owner_id: str | None = None,
        param_entity_id: str | None = None,
        current_action_target_id: str | None = None,
    ) -> StatusApplicationResult:
        if effect.opcode != "AddModifier":
            return _unsupported_result(effect, "effect is not AddModifier")
        if self.rules is None:
            return _unsupported_result(effect, "StatusSystem requires RuleBook for AddModifier")

        standard = effect.payload.get("standard")
        if not isinstance(standard, dict):
            return _unsupported_result(effect, "AddModifier effect has no standardized payload")
        modifier_name = standard.get("modifier_name")
        if not isinstance(modifier_name, str) or not modifier_name:
            return _unsupported_result(effect, "AddModifier has no modifier_name")
        target_alias = standard.get("target_alias")
        target_id = _resolve_target_alias(
            target_alias,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
        )
        if target_id is None:
            return _unsupported_result(effect, f"unsupported_or_missing_target_alias:{target_alias}")
        if target_id not in state.units:
            return _unsupported_result(effect, f"target unit {target_id!r} is not in state")

        definition = self.rules.modifier_definition(modifier_name)
        if definition is None:
            return _unsupported_result(effect, f"unknown modifier definition {modifier_name!r}")

        dynamic_values = _resolve_dynamic_values(standard)
        modifiers, unsupported = _runtime_modifiers(definition, dynamic_values)
        status_instance = StatusInstance(
            instance_id=_status_instance_id(target_id, modifier_name, effect.effect_id, source_id),
            status_id=f"modifier:{modifier_name}",
            modifier_name=modifier_name,
            owner_id=target_id,
            source_id=source_id,
            caster_id=caster_id,
            stacks=1,
            max_stacks=_optional_int(standard.get("max_layer")),
            duration=_optional_float(standard.get("lifetime")),
            dynamic_values=dynamic_values,
            source_trace={
                "effect_id": effect.effect_id,
                "effect_source": effect.source.to_json(),
                "modifier_definition": definition.source.to_json(),
            },
            modifiers=tuple(modifiers),
            trigger_ids_by_event=_trigger_ids_by_event(self.rules, modifier_name),
            unsupported=tuple(unsupported),
        )
        unit = state.units[target_id]
        before_statuses = list(unit.statuses)
        after_statuses = list(dict.fromkeys((*unit.statuses, status_instance.status_id)))
        before_details = _status_details(unit_flags=unit.flags)
        after_details = _replace_status_detail(before_details, status_instance)
        status_mutation = Mutation(
            op="set",
            path=("units", target_id, "statuses"),
            before=before_statuses,
            after=after_statuses,
            reason="apply AddModifier status id",
            source="status_system",
            metadata={"status_id": status_instance.status_id, "modifier_name": modifier_name},
        )
        detail_mutation = Mutation(
            op="set",
            path=("units", target_id, "flags", "status_details"),
            before=before_details,
            after=after_details,
            reason="apply AddModifier status details",
            source="status_system",
            metadata={"status_instance": status_instance.to_json()},
        )
        records = (
            SettlementRecord(
                record_type="status",
                source="status_system",
                mutation_id=detail_mutation.stable_id(),
                process_only=False,
                payload={
                    "operation": "add_modifier",
                    "status_instance": status_instance.to_json(),
                    "unsupported": list(unsupported),
                },
                trace=status_instance.source_trace,
            ).to_json(),
        )
        return StatusApplicationResult(
            ok=True,
            mutations=(status_mutation, detail_mutation),
            records=records,
            unsupported=tuple(unsupported),
            status_instance=status_instance,
        )


def _unsupported_result(effect: EffectIR, reason: str) -> StatusApplicationResult:
    return StatusApplicationResult(
        ok=False,
        records=(
            SettlementRecord(
                record_type="status_unsupported",
                source="status_system",
                process_only=True,
                payload={"reason": reason, "effect_id": effect.effect_id, "opcode": effect.opcode},
                trace={"effect_source": effect.source.to_json()},
            ).to_json(),
        ),
        unsupported=(reason,),
    )


def _resolve_target_alias(
    alias: object,
    *,
    caster_id: str,
    owner_id: str | None,
    param_entity_id: str | None,
    current_action_target_id: str | None,
) -> str | None:
    if alias == "Caster":
        return caster_id
    if alias == "ModifierOwnerEntity":
        return owner_id or caster_id
    if alias == "ParamEntity":
        return param_entity_id
    if alias == "CurrentActionTarget":
        return current_action_target_id
    return None


def _resolve_dynamic_values(standard: dict[str, JSONValue]) -> dict[str, JSONValue]:
    values: dict[str, JSONValue] = {}
    dynamic_values = standard.get("dynamic_values")
    if not isinstance(dynamic_values, dict):
        return values
    for key, expr in dynamic_values.items():
        value = _numeric_expr_value(expr)
        if value is not None:
            values[str(key)] = value
    return values


def _runtime_modifiers(
    definition: RuleEntity,
    dynamic_values: dict[str, JSONValue],
) -> tuple[list[dict[str, JSONValue]], list[str]]:
    modifiers: list[dict[str, JSONValue]] = []
    unsupported: list[str] = []
    stack_properties = definition.fields.get("stack_properties")
    if not isinstance(stack_properties, list):
        return modifiers, unsupported
    for index, item in enumerate(stack_properties):
        if not isinstance(item, dict):
            continue
        if item.get("event") != "OnStack":
            continue
        property_name = str(item.get("property") or "")
        mapped = _map_stack_property(property_name)
        if mapped is None:
            unsupported.append(f"unsupported_property:{property_name}")
            continue
        value, reason = _resolve_stack_property_value(item.get("value_expr"), dynamic_values)
        if value is None:
            unsupported.append(f"unsupported_formula:{property_name}:{reason}")
            continue
        bucket, key, scope = mapped
        modifiers.append(
            {
                "bucket": bucket,
                "key": key,
                "value": value,
                "scope": scope,
                "property": property_name,
                "raw_path": str(item.get("raw_path") or f"stack_properties[{index}]"),
                "applied_reason": "status_stack_property",
                "condition": f"property={property_name}",
            }
        )
    return modifiers, unsupported


def _resolve_stack_property_value(
    value_expr: object,
    dynamic_values: dict[str, JSONValue],
) -> tuple[float | None, str]:
    value = _numeric_expr_value(value_expr)
    if value is not None:
        return value, "fixed"
    if isinstance(value_expr, dict) and value_expr.get("kind") == "dynamic_hash":
        # v0_210 intentionally does not guess TBGD string-hash bindings. Keep
        # the evidence visible and require a later binder stage for these cases.
        return None, f"dynamic_hash_unbound:{value_expr.get('hash')}"
    return None, "unsupported_numeric_expression"


def _numeric_expr_value(expr: object) -> float | None:
    if isinstance(expr, dict) and expr.get("kind") == "fixed" and isinstance(expr.get("value"), (int, float)):
        return float(expr["value"])
    return None


def _map_stack_property(property_name: str) -> tuple[str, str, str] | None:
    element_prefixes = {
        "Physical": "Physical",
        "Fire": "Fire",
        "Ice": "Ice",
        "Thunder": "Thunder",
        "Wind": "Wind",
        "Quantum": "Quantum",
        "Imaginary": "Imaginary",
    }
    if property_name == "AllDamageTypeAddedRatio":
        return ("damage_bonus", "damage_added_ratio", "actor")
    for prefix in element_prefixes:
        if property_name == f"{prefix}AddedRatio":
            return ("damage_bonus", f"{prefix}_damage_added_ratio", "actor")
        if property_name == f"{prefix}ResistanceDelta":
            return ("resistance", f"{prefix}_resistance_delta", "target")
    if property_name == "AllResistanceDelta":
        return ("resistance", "all_resistance_delta", "target")
    if property_name in {"DamageTakenRatio", "AllDamageTakenRatio"}:
        return ("damage_taken", "damage_taken_ratio", "target")
    if property_name in {"DefenceReduce", "DefenseReduce", "DefenceReduction", "DefenseReduction"}:
        return ("defense", "def_reduction", "target")
    if property_name in {"DefenceIgnore", "DefenseIgnore"}:
        return ("defense", "def_ignore", "actor")
    return None


def _optional_float(expr: object) -> float | None:
    value = _numeric_expr_value(expr)
    return value if value is not None else None


def _optional_int(expr: object) -> int | None:
    value = _numeric_expr_value(expr)
    return int(value) if value is not None else None


def _status_details(unit_flags: dict[str, JSONValue]) -> list[JSONValue]:
    details = unit_flags.get("status_details", ())
    if isinstance(details, list):
        return list(details)
    if isinstance(details, tuple):
        return list(details)
    return []


def _replace_status_detail(details: list[JSONValue], status_instance: StatusInstance) -> list[JSONValue]:
    instance_json = status_instance.to_json()
    return [
        *(item for item in details if not (isinstance(item, dict) and item.get("instance_id") == status_instance.instance_id)),
        instance_json,
    ]


def _trigger_ids_by_event(rules: RuleBook, modifier_name: str) -> dict[str, tuple[str, ...]]:
    by_event: dict[str, list[str]] = {}
    for trigger in rules.triggers_for_modifier(modifier_name):
        by_event.setdefault(trigger.event, []).append(trigger.trigger_id)
    return {event: tuple(trigger_ids) for event, trigger_ids in sorted(by_event.items())}


def _status_instance_id(target_id: str, modifier_name: str, effect_id: str, source_id: str) -> str:
    raw = json.dumps(
        {
            "target_id": target_id,
            "modifier_name": modifier_name,
            "effect_id": effect_id,
            "source_id": source_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"status:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"
