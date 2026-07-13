from __future__ import annotations

import base64
from typing import Any

from ..rules.expression_ir import (
    NUMERIC_EXPRESSION_SCHEMA,
    numeric_dynamic_hash,
    numeric_fixed,
    numeric_missing,
    numeric_unsupported,
)
from ..rules.ir import JSONValue


def lower_numeric_expression(value: Any) -> dict[str, JSONValue]:
    if value is None:
        return numeric_missing()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return numeric_fixed(float(value))
    if not isinstance(value, dict):
        return numeric_unsupported("unsupported_numeric_expression")
    fixed = value.get("FixedValue")
    if isinstance(fixed, dict) and isinstance(fixed.get("Value"), (int, float)):
        return numeric_fixed(float(fixed["Value"]))
    if isinstance(value.get("Value"), (int, float)) and not isinstance(value.get("Value"), bool):
        return numeric_fixed(float(value["Value"]))
    postfix = value.get("PostfixExpr")
    if not isinstance(postfix, dict):
        return numeric_unsupported("unsupported_numeric_expression")
    return _lower_postfix_program(postfix)


def _lower_postfix_program(postfix: dict[str, Any]) -> dict[str, JSONValue]:
    opcodes = _decode_opcodes(postfix.get("OpCodes"))
    if opcodes is None:
        return numeric_unsupported("postfix_opcodes_decode_failed")
    fixed_values = _fixed_values(postfix.get("FixedValues"))
    dynamic_hashes = postfix.get("DynamicHashes") if isinstance(postfix.get("DynamicHashes"), list) else []
    instructions: list[dict[str, JSONValue]] = []
    index = 0
    ended = False
    stack_depth = 0
    while index < len(opcodes):
        opcode = opcodes[index]
        if opcode == 17:
            instructions.append({"opcode": "end"})
            ended = True
            index += 1
            if index != len(opcodes):
                return numeric_unsupported("postfix_tokens_after_end")
            continue
        if opcode in {0, 1}:
            if index + 1 >= len(opcodes):
                return numeric_unsupported("postfix_operand_index_missing")
            operand_index = int(opcodes[index + 1])
            if opcode == 0:
                if operand_index < 0 or operand_index >= len(fixed_values):
                    return numeric_unsupported("fixed_operand_unresolved")
                instructions.append({"opcode": "push_fixed", "value": fixed_values[operand_index]})
            else:
                if operand_index < 0 or operand_index >= len(dynamic_hashes):
                    return numeric_unsupported("dynamic_operand_unresolved")
                instructions.append({"opcode": "push_dynamic", "hash": _json_scalar(dynamic_hashes[operand_index])})
            stack_depth += 1
            index += 2
            continue
        operation = {2: "add", 3: "sub", 4: "mul", 5: "div"}.get(opcode)
        if operation is None:
            return numeric_unsupported(f"unsupported_postfix_opcode:{opcode}")
        if stack_depth < 2:
            return numeric_unsupported("postfix_stack_underflow")
        instructions.append({"opcode": operation})
        stack_depth -= 1
        index += 1
    if not ended:
        return numeric_unsupported("postfix_missing_end_opcode")
    if stack_depth != 1:
        return numeric_unsupported("postfix_final_stack_size")
    if all(item["opcode"] != "push_dynamic" for item in instructions):
        folded = _fold_fixed_program(tuple(instructions))
        if folded is not None:
            return numeric_fixed(folded)
    if len(instructions) == 2 and instructions[0].get("opcode") == "push_dynamic":
        return numeric_dynamic_hash(instructions[0].get("hash"))
    return {
        "schema_version": NUMERIC_EXPRESSION_SCHEMA,
        "kind": "program",
        "supported": True,
        "instructions": instructions,
    }


def _fold_fixed_program(instructions: tuple[dict[str, JSONValue], ...]) -> float | None:
    stack: list[float] = []
    for instruction in instructions:
        opcode = instruction.get("opcode")
        if opcode == "end":
            continue
        if opcode == "push_fixed":
            value = instruction.get("value")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return None
            stack.append(float(value))
            continue
        if len(stack) < 2:
            return None
        rhs = stack.pop()
        lhs = stack.pop()
        if opcode == "add":
            stack.append(lhs + rhs)
        elif opcode == "sub":
            stack.append(lhs - rhs)
        elif opcode == "mul":
            stack.append(lhs * rhs)
        elif opcode == "div" and rhs != 0:
            stack.append(lhs / rhs)
        else:
            return None
    return stack[0] if len(stack) == 1 else None


def _decode_opcodes(value: Any) -> list[int] | None:
    if isinstance(value, list) and all(isinstance(item, int) for item in value):
        return [int(item) for item in value]
    if not isinstance(value, str) or not value:
        return None
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    try:
        return list(base64.b64decode(padded, validate=True))
    except (ValueError, TypeError):
        return None


def _fixed_values(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    result: list[float] = []
    for item in value:
        raw = item.get("Value") if isinstance(item, dict) else item
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            result.append(float(raw))
    return result


def _json_scalar(value: Any) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)
