from __future__ import annotations

from ..ir_types import JSONValue


NUMERIC_EXPRESSION_SCHEMA = "hsr.numeric_expression.v1"
TARGET_EXPRESSION_NODE_SCHEMA = "hsr.target_expression_node.v1"
CONDITION_EXPRESSION_NODE_SCHEMA = "hsr.condition_expression_node.v1"


def numeric_fixed(value: float) -> dict[str, JSONValue]:
    return {
        "schema_version": NUMERIC_EXPRESSION_SCHEMA,
        "kind": "fixed",
        "value": float(value),
        "supported": True,
    }


def numeric_dynamic_hash(hash_value: JSONValue) -> dict[str, JSONValue]:
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
        )
    if kind == "dynamic_hash":
        hash_value = value.get("hash")
        return (
            set(value) == {"schema_version", "kind", "hash", "supported"}
            and supported is True
            and (
                hash_value is None
                or isinstance(hash_value, (bool, int, float, str))
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
            ):
                return False
            stack_depth += 1
            continue
        if opcode == "push_dynamic":
            hash_value = instruction.get("hash")
            if set(instruction) != {"opcode", "hash"} or not (
                hash_value is None
                or isinstance(hash_value, (bool, int, float, str))
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
    if isinstance(fixed, bool) or not isinstance(fixed, (int, float)):
        return None
    return float(fixed)
