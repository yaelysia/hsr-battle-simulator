from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal, cast

from ..immutable_json import freeze_json, thaw_json
from ..ir_types import IRSource, JSONValue


NUMERIC_EXPRESSION_SCHEMA = "hsr.numeric_expression.v1"
NUMERIC_OPERAND_SCHEMA = "hsr.numeric_operand.v1"
DYNAMIC_VALUE_OPERATION_SCHEMA = "hsr.dynamic_value_operation.v1"
TARGET_EXPRESSION_NODE_SCHEMA = "hsr.target_expression_node.v1"
CONDITION_EXPRESSION_NODE_SCHEMA = "hsr.condition_expression_node.v1"


_NUMERIC_OPERAND_KINDS = frozenset(
    {
        "expression",
        "dynamic_value",
        "unit_property",
        "modifier_value",
        "status_count",
        "hp_ratio",
        "shield_value",
        "team_resource",
        "character_count",
        "base_type_count",
        "weakness_count",
        "event_value",
        "skill_property",
        "break_base_damage",
        "status_resistance",
        "precalculated_stance_damage",
        "random_range",
        "formation_index",
        "wave_stage_count",
        "team_center_distance",
        "blocked_external",
    }
)

_NUMERIC_OPERAND_PARAMETER_SCHEMAS: dict[str, dict[str, str]] = {
    "expression": {"formula_role": "str"},
    "dynamic_value": {
        "source_target_alias": "str",
        "source_key": "str",
        "source_hash": "optional_str",
        "source_modifier": "optional_str",
    },
    "unit_property": {"source_target_alias": "str", "property_name": "str"},
    "modifier_value": {
        "source_target_alias": "str",
        "modifier_name": "str",
        "modifier_value_name": "str",
    },
    "status_count": {"source_target_alias": "str", "count_mode": "debuff"},
    "hp_ratio": {"source_target_alias": "str"},
    "shield_value": {"source_target_alias": "str"},
    "team_resource": {"resource_name": "str"},
    "character_count": {
        "source_target_alias": "str",
        "alive_only": "optional_bool",
        "predicate_json": "str",
    },
    "base_type_count": {"base_types": "string_list"},
    "weakness_count": {
        "source_target_alias": "str",
        "weakness_filter_json": "str",
    },
    "event_value": {
        "event_kind": "str",
        "property_name": "optional_str",
        "value_type": "optional_str",
        "source_target_alias": "optional_str",
        "attacker_alias": "optional_str",
    },
    "skill_property": {"property_name": "str", "skill_trigger_json": "str"},
    "break_base_damage": {"source_target_alias": "str"},
    "status_resistance": {"source_target_alias": "str", "status_flag": "str"},
    "precalculated_stance_damage": {"source_descriptor_json": "str"},
    "random_range": {
        "minimum": "numeric_expression",
        "maximum": "numeric_expression",
        "integer_only": "bool",
    },
    "formation_index": {"source_target_alias": "str"},
    "wave_stage_count": {"source_kind": "battle_wave_stage"},
    "team_center_distance": {
        "source_target_alias": "str",
        "alive_only": "optional_bool",
    },
    "blocked_external": {
        "source_family": "str",
        "source_descriptor_json": "str",
    },
}


def _immutable_source(source: IRSource) -> IRSource:
    if not isinstance(source, IRSource):
        raise TypeError("dynamic value operation source must be IRSource")
    if not source.source_path or not source.raw_type or not source.raw_id:
        raise ValueError("dynamic value operation source identity is incomplete")
    evidence = freeze_json(source.evidence)
    if not isinstance(evidence, dict):
        raise TypeError("dynamic value operation source evidence must be an object")
    return IRSource(
        source_path=source.source_path,
        raw_type=source.raw_type,
        raw_id=source.raw_id,
        evidence=evidence,
    )


@dataclass(frozen=True)
class NumericOperandIR:
    operand_id: str
    operand_kind: str
    parameters: Mapping[str, Any]
    expression: Mapping[str, Any] | None = None
    scale_expression: Mapping[str, Any] | None = None
    coverage_status: Literal["executable", "blocked"] = "blocked"
    blocked_reason: str = ""
    required_producer: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.operand_id, str) or not self.operand_id:
            raise ValueError("numeric operand identity is required")
        if self.operand_kind not in _NUMERIC_OPERAND_KINDS:
            raise ValueError(f"unknown numeric operand kind:{self.operand_kind}")
        if self.coverage_status not in {"executable", "blocked"}:
            raise ValueError("numeric operand coverage status is invalid")
        if not isinstance(self.parameters, Mapping):
            raise TypeError("numeric operand parameters must be an object")
        _validate_numeric_operand_parameters(self.operand_kind, self.parameters)
        parameters = freeze_json(dict(self.parameters))
        if not isinstance(parameters, dict):
            raise TypeError("numeric operand parameters must be an object")
        expression = self.expression
        if expression is not None:
            expression = freeze_json(dict(expression))
            if not is_exact_numeric_expression(expression):
                raise ValueError("numeric operand expression is not canonical")
        scale_expression = self.scale_expression
        if scale_expression is not None:
            scale_expression = freeze_json(dict(scale_expression))
            if not is_exact_numeric_expression(scale_expression):
                raise ValueError("numeric operand scale expression is not canonical")
        if self.operand_kind == "expression" and expression is None:
            raise ValueError("expression operand requires an expression")
        if self.coverage_status == "executable":
            if self.blocked_reason or self.required_producer:
                raise ValueError("executable operand cannot carry a blocker")
        elif not self.blocked_reason or not self.required_producer:
            raise ValueError("blocked operand requires reason and producer")
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "expression", expression)
        object.__setattr__(self, "scale_expression", scale_expression)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "schema_version": NUMERIC_OPERAND_SCHEMA,
            "operand_id": self.operand_id,
            "operand_kind": self.operand_kind,
            "parameters": cast(JSONValue, thaw_json(self.parameters)),
            "expression": cast(JSONValue, thaw_json(self.expression)),
            "scale_expression": cast(
                JSONValue, thaw_json(self.scale_expression)
            ),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "required_producer": self.required_producer,
        }

    @classmethod
    def from_json(cls, value: object) -> "NumericOperandIR":
        if not isinstance(value, Mapping) or set(value) != {
            "schema_version",
            "operand_id",
            "operand_kind",
            "parameters",
            "expression",
            "scale_expression",
            "coverage_status",
            "blocked_reason",
            "required_producer",
        }:
            raise ValueError("numeric operand payload schema is invalid")
        if value.get("schema_version") != NUMERIC_OPERAND_SCHEMA:
            raise ValueError("numeric operand schema version is invalid")
        parameters = value.get("parameters")
        if not isinstance(parameters, Mapping):
            raise TypeError("numeric operand parameters must be an object")
        expression = value.get("expression")
        scale_expression = value.get("scale_expression")
        for field_name in (
            "operand_id",
            "operand_kind",
            "coverage_status",
            "blocked_reason",
            "required_producer",
        ):
            if not isinstance(value.get(field_name), str):
                raise TypeError(f"numeric operand {field_name} must be a string")
        if expression is not None and not isinstance(expression, Mapping):
            raise TypeError("numeric operand expression must be an object or null")
        if scale_expression is not None and not isinstance(scale_expression, Mapping):
            raise TypeError("numeric operand scale expression must be an object or null")
        return cls(
            operand_id=cast(str, value.get("operand_id")),
            operand_kind=cast(str, value.get("operand_kind")),
            parameters=parameters,
            expression=(
                cast(Mapping[str, Any], expression)
                if isinstance(expression, Mapping)
                else None
            ),
            scale_expression=(
                cast(Mapping[str, Any], scale_expression)
                if isinstance(scale_expression, Mapping)
                else None
            ),
            coverage_status=cast(Any, value.get("coverage_status")),
            blocked_reason=cast(str, value.get("blocked_reason")),
            required_producer=cast(str, value.get("required_producer")),
        )


def _validate_numeric_operand_parameters(
    operand_kind: str,
    parameters: Mapping[str, Any],
) -> None:
    schema = _NUMERIC_OPERAND_PARAMETER_SCHEMAS.get(operand_kind)
    if schema is None or set(parameters) != set(schema):
        raise ValueError(f"numeric operand parameter schema is invalid:{operand_kind}")
    for field_name, field_type in schema.items():
        value = parameters[field_name]
        valid = {
            "str": lambda item: isinstance(item, str),
            "optional_str": lambda item: item is None or isinstance(item, str),
            "bool": lambda item: isinstance(item, bool),
            "optional_bool": lambda item: item is None or isinstance(item, bool),
            "debuff": lambda item: item == "debuff",
            "battle_wave_stage": lambda item: item == "battle_wave_stage",
            "string_list": lambda item: isinstance(item, (list, tuple))
            and all(isinstance(member, str) and member for member in item),
            "numeric_expression": is_exact_numeric_expression,
        }[field_type](value)
        if not valid:
            raise TypeError(
                f"numeric operand parameter type is invalid:{operand_kind}:{field_name}"
            )


@dataclass(frozen=True)
class DynamicValueOperationIR:
    operation_id: str
    operation_kind: Literal["define", "set", "add", "copy"]
    destination_key: str
    destination_hash: str | None
    target_alias: str
    scope_kind: Literal["unit", "ability", "status", "event", "contextual"]
    lifecycle: Literal[
        "combat",
        "ability_action",
        "status_instance",
        "event",
        "execution_context",
    ]
    operand: NumericOperandIR
    source: IRSource
    minimum: NumericOperandIR | None = None
    maximum: NumericOperandIR | None = None
    coverage_status: Literal["executable", "blocked"] = "blocked"
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        for field_name in ("operation_id", "destination_key", "target_alias"):
            if not isinstance(getattr(self, field_name), str) or not getattr(
                self, field_name
            ):
                raise ValueError(f"dynamic value {field_name} is required")
        if self.destination_hash is not None and (
            not isinstance(self.destination_hash, str) or not self.destination_hash
        ):
            raise ValueError("dynamic value destination hash is invalid")
        if self.operation_kind not in {"define", "set", "add", "copy"}:
            raise ValueError("dynamic value operation kind is invalid")
        lifecycle_by_scope = {
            "unit": "combat",
            "ability": "ability_action",
            "status": "status_instance",
            "event": "event",
            "contextual": "execution_context",
        }
        if self.scope_kind not in lifecycle_by_scope:
            raise ValueError("dynamic value scope kind is invalid")
        expected_lifecycle = lifecycle_by_scope[self.scope_kind]
        if self.lifecycle != expected_lifecycle:
            raise ValueError("dynamic value scope and lifecycle disagree")
        if type(self.operand) is not NumericOperandIR:
            raise TypeError("dynamic value operation operand must be typed")
        if self.minimum is not None and type(self.minimum) is not NumericOperandIR:
            raise TypeError("dynamic value minimum must be a typed operand")
        if self.maximum is not None and type(self.maximum) is not NumericOperandIR:
            raise TypeError("dynamic value maximum must be a typed operand")
        if self.operation_kind == "copy" and self.operand.operand_kind != "dynamic_value":
            raise ValueError("dynamic copy operation requires a dynamic-value operand")
        source = _immutable_source(self.source)
        if self.coverage_status == "executable":
            operands = tuple(
                item
                for item in (self.operand, self.minimum, self.maximum)
                if item is not None
            )
            if self.blocked_reason or any(
                item.coverage_status != "executable" for item in operands
            ):
                raise ValueError("executable dynamic operation has a blocker")
        elif self.coverage_status != "blocked" or not self.blocked_reason:
            raise ValueError("blocked dynamic operation requires a reason")
        expected_id = dynamic_value_operation_id(source, self.to_spec_json())
        if self.operation_id != expected_id:
            raise ValueError("dynamic value operation identity is inconsistent")
        object.__setattr__(self, "source", source)

    def to_spec_json(self) -> dict[str, JSONValue]:
        return {
            "schema_version": DYNAMIC_VALUE_OPERATION_SCHEMA,
            "operation_kind": self.operation_kind,
            "destination_key": self.destination_key,
            "destination_hash": self.destination_hash,
            "target_alias": self.target_alias,
            "scope_kind": self.scope_kind,
            "lifecycle": self.lifecycle,
            "operand": self.operand.to_json(),
            "minimum": self.minimum.to_json() if self.minimum is not None else None,
            "maximum": self.maximum.to_json() if self.maximum is not None else None,
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }

    def to_json(self) -> dict[str, JSONValue]:
        return {
            **self.to_spec_json(),
            "operation_id": self.operation_id,
            "source": self.source.to_json(),
        }

    @classmethod
    def from_spec(
        cls,
        value: object,
        source: IRSource,
    ) -> "DynamicValueOperationIR":
        if not isinstance(value, Mapping) or set(value) != {
            "schema_version",
            "operation_kind",
            "destination_key",
            "destination_hash",
            "target_alias",
            "scope_kind",
            "lifecycle",
            "operand",
            "minimum",
            "maximum",
            "coverage_status",
            "blocked_reason",
        }:
            raise ValueError("dynamic value operation spec schema is invalid")
        if value.get("schema_version") != DYNAMIC_VALUE_OPERATION_SCHEMA:
            raise ValueError("dynamic value operation schema version is invalid")
        operand = NumericOperandIR.from_json(value.get("operand"))
        minimum_value = value.get("minimum")
        maximum_value = value.get("maximum")
        for field_name in (
            "operation_kind",
            "destination_key",
            "target_alias",
            "scope_kind",
            "lifecycle",
            "coverage_status",
            "blocked_reason",
        ):
            if not isinstance(value.get(field_name), str):
                raise TypeError(f"dynamic value {field_name} must be a string")
        destination_hash = value.get("destination_hash")
        if destination_hash is not None and not isinstance(destination_hash, str):
            raise TypeError("dynamic value destination hash must be a string or null")
        immutable_source = _immutable_source(source)
        spec = cast(dict[str, JSONValue], thaw_json(value))
        return cls(
            operation_id=dynamic_value_operation_id(immutable_source, spec),
            operation_kind=cast(Any, value.get("operation_kind")),
            destination_key=cast(str, value.get("destination_key")),
            destination_hash=cast(str | None, destination_hash),
            target_alias=cast(str, value.get("target_alias")),
            scope_kind=cast(Any, value.get("scope_kind")),
            lifecycle=cast(Any, value.get("lifecycle")),
            operand=operand,
            source=immutable_source,
            minimum=(
                NumericOperandIR.from_json(minimum_value)
                if minimum_value is not None
                else None
            ),
            maximum=(
                NumericOperandIR.from_json(maximum_value)
                if maximum_value is not None
                else None
            ),
            coverage_status=cast(Any, value.get("coverage_status")),
            blocked_reason=cast(str, value.get("blocked_reason")),
        )


def dynamic_value_operation_id(
    source: IRSource,
    spec: Mapping[str, Any],
) -> str:
    payload = {
        "source_path": source.source_path,
        "raw_type": source.raw_type,
        "raw_id": source.raw_id,
        "spec": thaw_json(spec),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"dynamic_value_operation:{sha256(encoded).hexdigest()}"


def numeric_fixed(value: float) -> dict[str, JSONValue]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("fixed numeric expression requires a number")
    try:
        numeric_value = float(value)
    except OverflowError as exc:
        raise ValueError("fixed numeric expression must be finite") from exc
    if not math.isfinite(numeric_value):
        raise ValueError("fixed numeric expression must be finite")
    return {
        "schema_version": NUMERIC_EXPRESSION_SCHEMA,
        "kind": "fixed",
        "value": numeric_value,
        "supported": True,
    }


def numeric_dynamic_hash(hash_value: JSONValue) -> dict[str, JSONValue]:
    if isinstance(hash_value, bool):
        raise TypeError("dynamic numeric hash cannot be bool")
    if isinstance(hash_value, float) and not math.isfinite(hash_value):
        raise ValueError("dynamic numeric hash must be finite")
    if hash_value is not None and not isinstance(hash_value, (int, float, str)):
        raise TypeError("dynamic numeric hash must be scalar")
    return {
        "schema_version": NUMERIC_EXPRESSION_SCHEMA,
        "kind": "dynamic_hash",
        "hash": hash_value,
        "supported": True,
    }


def numeric_missing(reason: str = "missing") -> dict[str, JSONValue]:
    return {
        "schema_version": NUMERIC_EXPRESSION_SCHEMA,
        "kind": "missing",
        "supported": False,
        "reason": reason,
    }


def numeric_unsupported(reason: str) -> dict[str, JSONValue]:
    return {
        "schema_version": NUMERIC_EXPRESSION_SCHEMA,
        "kind": "unsupported",
        "supported": False,
        "reason": reason,
    }


def is_typed_numeric_expression(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    kind = value.get("kind")
    if value.get("schema_version") == NUMERIC_EXPRESSION_SCHEMA:
        return kind in {"fixed", "dynamic_hash", "program", "missing", "unsupported"}
    return kind in {"fixed", "dynamic_hash", "missing", "unsupported"} and not any(
        key in value for key in ("PostfixExpr", "OpCodes", "FixedValue", "raw")
    )


def is_exact_numeric_expression(value: object) -> bool:
    """Validate the canonical numeric-expression schema without extensions."""

    if not isinstance(value, dict) or value.get("schema_version") != NUMERIC_EXPRESSION_SCHEMA:
        return False
    kind = value.get("kind")
    supported = value.get("supported")
    if kind == "fixed":
        fixed = value.get("value")
        return (
            set(value) == {"schema_version", "kind", "value", "supported"}
            and supported is True
            and isinstance(fixed, (int, float))
            and not isinstance(fixed, bool)
            and _finite_number(fixed)
        )
    if kind == "dynamic_hash":
        hash_value = value.get("hash")
        return (
            set(value) == {"schema_version", "kind", "hash", "supported"}
            and supported is True
            and (
                hash_value is None
                or (
                    isinstance(hash_value, (int, str))
                    and not isinstance(hash_value, bool)
                )
                or (
                    isinstance(hash_value, float)
                    and math.isfinite(hash_value)
                )
            )
        )
    if kind in {"missing", "unsupported"}:
        reason = value.get("reason")
        return (
            set(value) == {"schema_version", "kind", "supported", "reason"}
            and supported is False
            and isinstance(reason, str)
            and bool(reason)
        )
    if kind != "program" or supported is not True or set(value) != {
        "schema_version",
        "kind",
        "supported",
        "instructions",
    }:
        return False
    instructions = value.get("instructions")
    if not isinstance(instructions, list) or not instructions:
        return False
    stack_depth = 0
    ended = False
    for index, instruction in enumerate(instructions):
        if not isinstance(instruction, dict):
            return False
        opcode = instruction.get("opcode")
        if opcode == "end":
            if set(instruction) != {"opcode"} or ended or index != len(instructions) - 1:
                return False
            ended = True
            continue
        if ended:
            return False
        if opcode == "push_fixed":
            fixed = instruction.get("value")
            if (
                set(instruction) != {"opcode", "value"}
                or not isinstance(fixed, (int, float))
                or isinstance(fixed, bool)
                or not _finite_number(fixed)
            ):
                return False
            stack_depth += 1
            continue
        if opcode == "push_dynamic":
            hash_value = instruction.get("hash")
            if set(instruction) != {"opcode", "hash"} or not (
                hash_value is None
                or (
                    isinstance(hash_value, (int, str))
                    and not isinstance(hash_value, bool)
                )
                or (
                    isinstance(hash_value, float)
                    and math.isfinite(hash_value)
                )
            ):
                return False
            stack_depth += 1
            continue
        if opcode == "negate":
            if set(instruction) != {"opcode"} or stack_depth < 1:
                return False
            continue
        if opcode in {"add", "sub", "mul", "div"}:
            if set(instruction) != {"opcode"} or stack_depth < 2:
                return False
            stack_depth -= 1
            continue
        if opcode == "max":
            operand_count = instruction.get("operand_count")
            if (
                set(instruction) != {"opcode", "operand_count"}
                or not isinstance(operand_count, int)
                or isinstance(operand_count, bool)
                or operand_count < 2
                or stack_depth < operand_count
            ):
                return False
            stack_depth -= operand_count - 1
            continue
        return False
    return ended and stack_depth == 1


def _finite_number(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def numeric_dynamic_hashes(value: object) -> tuple[JSONValue, ...]:
    """Return operands from admitted numeric IR without inspecting source syntax."""

    if not is_typed_numeric_expression(value) or not isinstance(value, dict):
        return ()
    if value.get("kind") == "dynamic_hash":
        return (value.get("hash"),)
    if value.get("kind") != "program" or value.get("schema_version") != NUMERIC_EXPRESSION_SCHEMA:
        return ()
    instructions = value.get("instructions")
    if not isinstance(instructions, list):
        return ()
    return tuple(
        instruction.get("hash")
        for instruction in instructions
        if isinstance(instruction, dict) and instruction.get("opcode") == "push_dynamic"
    )


def numeric_fixed_value(value: object) -> float | None:
    if not is_typed_numeric_expression(value) or not isinstance(value, dict):
        return None
    if value.get("kind") != "fixed":
        return None
    fixed = value.get("value")
    if not _finite_number(fixed):
        return None
    return float(fixed)
