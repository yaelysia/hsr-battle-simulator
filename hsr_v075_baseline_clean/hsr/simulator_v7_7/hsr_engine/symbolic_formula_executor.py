from __future__ import annotations

"""Small, conservative executor for canonical symbolic dynamic expression IR.

The input is the compiler-side ``hsr_symbolic_dynamic_expression_ir`` emitted by
``status_dynamic_expression_binder``.  This module intentionally supports only a
very small set of proven postfix bytecode patterns and returns an audit trace for
all unsupported shapes instead of guessing TurnBasedGameData semantics.
"""

from typing import Any
import base64


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _decode_opcodes(opcodes: Any) -> list[int] | None:
    if not isinstance(opcodes, str) or not opcodes:
        return None
    try:
        return list(base64.b64decode(opcodes))
    except Exception:
        return None


def _runtime_lookup(runtime_values_by_hash: dict[Any, Any] | None, h: Any, runtime_key: Any = None) -> tuple[float | None, str]:
    if not runtime_values_by_hash:
        return None, "runtime_value_missing"
    keys = []
    if runtime_key is not None:
        keys.extend([runtime_key, str(runtime_key)])
    keys.extend([h, str(h)])
    try:
        keys.append(int(h))
    except Exception:
        pass
    seen = set()
    deduped = []
    for k in keys:
        sig = (type(k).__name__, str(k))
        if sig in seen:
            continue
        seen.add(sig)
        deduped.append(k)
    for k in deduped:
        if k in runtime_values_by_hash:
            value = _num(runtime_values_by_hash[k])
            if value is None:
                return None, "runtime_value_non_numeric"
            return value, "runtime_value_resolved_by_key" if runtime_key is not None and str(k) == str(runtime_key) else "runtime_value_resolved"
    return None, "runtime_value_missing"


def _operand_value_map(expr_ir: dict[str, Any], runtime_values_by_hash: dict[Any, Any] | None = None) -> tuple[dict[int, float], list[dict[str, Any]]]:
    values: dict[int, float] = {}
    audit: list[dict[str, Any]] = []
    for i, op in enumerate(expr_ir.get("operands") or []):
        if not isinstance(op, dict):
            audit.append({"index": i, "resolved": False, "reason": "operand_not_object"})
            continue
        kind = op.get("kind")
        if kind == "numeric_binding":
            value = _num(op.get("value"))
            if value is None and isinstance(op.get("binding"), dict):
                value = _num(op["binding"].get("value"))
            if value is None:
                audit.append({"index": i, "kind": kind, "hash": op.get("hash"), "resolved": False, "reason": "numeric_binding_without_value"})
                continue
            values[i] = value
            audit.append({"index": i, "kind": kind, "hash": op.get("hash"), "resolved": True, "value": value, "source": op.get("source")})
            continue
        if kind == "runtime_dynamic_value":
            binding = op.get("binding") if isinstance(op.get("binding"), dict) else {}
            runtime_key = op.get("runtime_value_key") or binding.get("runtime_value_key") or op.get("dynamic_key") or binding.get("dynamic_key")
            value, reason = _runtime_lookup(runtime_values_by_hash, op.get("hash"), runtime_key=runtime_key)
            if value is None:
                audit.append({"index": i, "kind": kind, "hash": op.get("hash"), "runtime_value_key": runtime_key, "resolved": False, "reason": reason})
                continue
            values[i] = value
            audit.append({"index": i, "kind": kind, "hash": op.get("hash"), "runtime_value_key": runtime_key, "resolved": True, "value": value, "reason": reason})
            continue
        audit.append({"index": i, "kind": kind, "hash": op.get("hash"), "resolved": False, "reason": "unsupported_operand_kind"})
    return values, audit


# Compatibility helper used by older tests/importers.
def _operand_values(expr_ir: dict[str, Any], runtime_values_by_hash: dict[Any, Any] | None = None) -> tuple[list[float], list[dict[str, Any]]]:
    value_map, audit = _operand_value_map(expr_ir, runtime_values_by_hash)
    return [value_map[i] for i in sorted(value_map)], audit


def evaluate_symbolic_expression_ir(expr_ir: Any, runtime_values_by_hash: dict[Any, Any] | None = None) -> tuple[float | None, dict[str, Any]]:
    """Evaluate a symbolic dynamic expression only for proven opcode patterns.

    Supported postfix operators:
    - ``0x02``: addition.  Proven by generated counter increments such as
      ``MDF_QuantumCount = MDF_QuantumCount + 1``.
    - ``0x03``: subtraction.  Proven by generated cyclic-counter reset such as
      ``MDF_EffectRandom = MDF_EffectRandom - 4`` when the counter exceeds 4.
    - ``0x04``: multiplication.  Proven by skill multiplier and property-value
      expressions already bound from AvatarSkillConfig/SkillTree parameters.

    The executor is still conservative: every referenced operand must be a
    numeric binding or an explicitly supplied runtime value.  AttackConvert-like
    formulas with unresolved runtime property operands therefore remain audit-only
    even though their arithmetic opcodes are now decoded.
    """
    if not isinstance(expr_ir, dict) or expr_ir.get("format") != "hsr_symbolic_dynamic_expression_ir":
        return None, {"status": "not_symbolic_expression_ir"}
    opcodes = _decode_opcodes(expr_ir.get("opcodes"))
    value_map, operand_audit = _operand_value_map(expr_ir, runtime_values_by_hash)
    fixed_values = []
    for v in expr_ir.get("fixed_values") or []:
        n = _num(v)
        if n is not None:
            fixed_values.append(n)
    if opcodes is None:
        return None, {"status": "unsupported_symbolic_expr", "reason": "opcodes_decode_failed", "operand_audit": operand_audit}

    tokens: list[tuple[str, int | None]] = []
    stack: list[float] = []
    unsupported_ops: list[int] = []
    stack_errors: list[dict[str, Any]] = []
    i = 0
    ended = False
    while i < len(opcodes):
        b = opcodes[i]
        if b == 17:
            tokens.append(("end", None))
            ended = True
            i += 1
            continue
        if b == 1:
            if i + 1 >= len(opcodes):
                stack_errors.append({"op": b, "reason": "missing_dynamic_index"}); break
            idx = int(opcodes[i + 1])
            tokens.append(("dynamic", idx))
            if idx not in value_map:
                stack_errors.append({"op": b, "index": idx, "reason": "dynamic_operand_unresolved"})
            else:
                stack.append(float(value_map[idx]))
            i += 2
            continue
        if b == 0:
            if i + 1 >= len(opcodes):
                stack_errors.append({"op": b, "reason": "missing_fixed_index"}); break
            idx = int(opcodes[i + 1])
            tokens.append(("fixed", idx))
            if idx < 0 or idx >= len(fixed_values):
                stack_errors.append({"op": b, "index": idx, "reason": "fixed_operand_unresolved"})
            else:
                stack.append(float(fixed_values[idx]))
            i += 2
            continue
        if b in {2, 3, 4}:
            op_name = {2: "add", 3: "sub", 4: "mul"}[b]
            tokens.append((op_name, None))
            if len(stack) < 2:
                stack_errors.append({"op": b, "reason": "stack_underflow"})
            else:
                rhs = stack.pop()
                lhs = stack.pop()
                if b == 2:
                    stack.append(lhs + rhs)
                elif b == 3:
                    stack.append(lhs - rhs)
                else:
                    stack.append(lhs * rhs)
            i += 1
            continue
        unsupported_ops.append(b)
        tokens.append((f"unsupported_{b}", None))
        i += 1

    if any(not rec.get("resolved") for rec in operand_audit):
        return None, {"status": "unsupported_symbolic_expr", "reason": "unresolved_operand", "opcodes_bytes": opcodes, "tokens": tokens, "operand_audit": operand_audit, "stack_errors": stack_errors}
    if unsupported_ops:
        return None, {"status": "unsupported_symbolic_expr", "reason": "unsupported_opcode_pattern", "opcodes_bytes": opcodes, "tokens": tokens, "unsupported_opcode_bytes": sorted(set(unsupported_ops)), "operand_audit": operand_audit, "stack_errors": stack_errors}
    if stack_errors:
        return None, {"status": "unsupported_symbolic_expr", "reason": "stack_evaluation_error", "opcodes_bytes": opcodes, "tokens": tokens, "operand_audit": operand_audit, "stack_errors": stack_errors}
    if not ended:
        return None, {"status": "unsupported_symbolic_expr", "reason": "missing_end_opcode", "opcodes_bytes": opcodes, "tokens": tokens, "operand_audit": operand_audit}
    if len(stack) != 1:
        return None, {"status": "unsupported_symbolic_expr", "reason": "final_stack_size", "opcodes_bytes": opcodes, "tokens": tokens, "operand_audit": operand_audit, "final_stack_size": len(stack)}

    pattern = "postfix_add_sub_mul"
    if tokens == [("dynamic", 0), ("end", None)]:
        pattern = "dynamic_passthrough"
    elif tokens == [("dynamic", 0), ("dynamic", 1), ("mul", None), ("end", None)]:
        pattern = "dynamic_times_dynamic"
    elif tokens == [("dynamic", 0), ("fixed", 0), ("mul", None), ("end", None)]:
        pattern = "dynamic_times_fixed"
    elif tokens == [("dynamic", 0), ("fixed", 0), ("add", None), ("end", None)]:
        pattern = "dynamic_plus_fixed"
    elif tokens == [("dynamic", 0), ("fixed", 0), ("sub", None), ("end", None)]:
        pattern = "dynamic_minus_fixed"
    elif tokens == [("dynamic", 0), ("dynamic", 1), ("add", None), ("end", None)]:
        pattern = "dynamic_plus_dynamic"
    elif tokens == [("dynamic", 0), ("dynamic", 1), ("sub", None), ("end", None)]:
        pattern = "dynamic_minus_dynamic"
    return float(stack[0]), {"status": "resolved_symbolic_expr", "pattern": pattern, "opcodes_bytes": opcodes, "tokens": tokens, "fixed_values": fixed_values, "operand_audit": operand_audit}
