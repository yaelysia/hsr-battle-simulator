"""Canonical entity-local boolean markers with source-bound integer keys."""
from __future__ import annotations
import math
from collections.abc import Mapping
from ..rules.evaluator import NumericEvaluationContext, RuleEvaluator
from ..rules.expression_ir import numeric_dynamic_hash

FLAG_FIELD = "named_boolean_flags"


def resolve_named_key(expression, binding_sources):
    if (not isinstance(expression, Mapping) or set(expression) != {"schema_version", "parts"}
            or expression.get("schema_version") != "hsr.named_key.v1"
            or not isinstance(expression.get("parts"), (list, tuple)) or not expression["parts"]):
        return None, "named_key_expression_invalid"
    pieces = []
    for part in expression["parts"]:
        if not isinstance(part, Mapping) or len(part) != 1:
            return None, "named_key_part_invalid"
        if "literal" in part:
            if not isinstance(part["literal"], str) or not part["literal"]:
                return None, "named_key_literal_invalid"
            pieces.append(part["literal"])
        elif "parameter" in part:
            name = part["parameter"]
            if not isinstance(name, str) or not name:
                return None, "named_key_parameter_invalid"
            result = RuleEvaluator().evaluate_numeric(numeric_dynamic_hash(name),
                NumericEvaluationContext(binding_sources=tuple(binding_sources)))
            if (not result.ok or type(result.value) not in (int, float) or not math.isfinite(result.value)
                    or not float(result.value).is_integer() or abs(result.value) > 2 ** 53):
                return None, result.blocked_reason or "named_key_parameter_not_an_exact_integer"
            pieces.append(str(int(result.value)))
        else:
            return None, "named_key_part_not_admitted"
    return "".join(pieces), ""


def read_named_flag(unit, key):
    if unit is None:
        return None, "named_boolean_target_missing"
    flags = unit.flags.get(FLAG_FIELD, {})
    if not isinstance(flags, dict) or any(not isinstance(name, str) or not name or type(value) is not bool for name, value in flags.items()):
        return None, "named_boolean_state_invalid"
    return flags.get(key, False), ""
