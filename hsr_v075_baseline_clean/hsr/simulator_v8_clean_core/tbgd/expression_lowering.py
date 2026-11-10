from __future__ import annotations

import base64
import json
import math
from collections.abc import Mapping
from typing import Any

from ..rules.expression_ir import (
    DYNAMIC_VALUE_OPERATION_SCHEMA,
    NUMERIC_EXPRESSION_SCHEMA,
    NUMERIC_UNARY_OPERATIONS,
    numeric_unary_value,
    NumericOperandIR,
    is_exact_numeric_expression,
    numeric_dynamic_hash,
    numeric_fixed,
    numeric_missing,
    numeric_unsupported,
)
from ..rules.ir import JSONValue
from ..rules.ability_properties import ability_property_is_runtime_readable


_DYNAMIC_RUNTIME_TARGET_ALIASES = frozenset(
    {
        "Caster",
        "CasterServant",
        "CasterSummoner",
        "CurrentActionTarget",
        "LevelEntity",
        "ModifierOwnerEntity",
        "ParamEntity",
        # Battle-event callbacks write values on the event's committed creator.
        "BattleEventCaster",
    }
)


def lower_numeric_expression(value: Any) -> dict[str, JSONValue]:
    if value is None:
        return numeric_missing()
    if _finite_number(value):
        return numeric_fixed(float(value))
    if not isinstance(value, dict):
        return numeric_unsupported("unsupported_numeric_expression")
    fixed = value.get("FixedValue")
    if isinstance(fixed, dict) and _finite_number(fixed.get("Value")):
        return numeric_fixed(float(fixed["Value"]))
    if _finite_number(value.get("Value")):
        return numeric_fixed(float(value["Value"]))
    postfix = value.get("PostfixExpr")
    if not isinstance(postfix, dict):
        return numeric_unsupported("unsupported_numeric_expression")
    return _lower_postfix_program(postfix)


def is_dynamic_value_opcode(opcode: object) -> bool:
    return isinstance(opcode, str) and (
        opcode in {"DefineDynamicValue", "SetModifierDynamicValue"}
        or opcode.startswith("SetDynamicValue")
    )


def lower_dynamic_value_operation_spec(
    opcode: str,
    standard: Mapping[str, Any],
) -> dict[str, JSONValue]:
    """Lower every admitted dynamic-value family to one source-neutral spec."""

    if not is_dynamic_value_opcode(opcode):
        raise ValueError(f"not a dynamic value opcode:{opcode}")
    destination_key = standard.get("value_name", standard.get("target_value_name"))
    if not isinstance(destination_key, str) or not destination_key:
        destination_key = "<missing>"
    destination_hash = standard.get("hash", standard.get("target_hash"))
    if destination_hash is not None:
        destination_hash = str(destination_hash)
    target_alias = standard.get("target_alias")
    if not isinstance(target_alias, str) or not target_alias:
        target_alias = "<missing>"
    scope_kind, lifecycle = _dynamic_scope(
        standard.get("status_scope", standard.get("context_scope"))
    )
    operation_kind = _dynamic_operation_kind(opcode, standard.get("operation"))
    operand = _dynamic_operand(opcode, standard)
    minimum = _optional_expression_operand("minimum", standard.get("min_value"))
    maximum = _optional_expression_operand("maximum", standard.get("max_value"))
    blockers = [
        reason
        for reason in (
            str(standard.get("blocked_reason") or ""),
            "dynamic_value_destination_missing"
            if destination_key == "<missing>"
            else "",
            "dynamic_value_target_alias_missing"
            if target_alias == "<missing>"
            else "",
            f"unsupported_dynamic_target_alias:{target_alias}"
            if target_alias not in _DYNAMIC_RUNTIME_TARGET_ALIASES and not standard.get("target_expression_id")
            else "",
            operand.blocked_reason if operand.coverage_status == "blocked" else "",
            minimum.blocked_reason
            if minimum is not None and minimum.coverage_status == "blocked"
            else "",
            maximum.blocked_reason
            if maximum is not None and maximum.coverage_status == "blocked"
            else "",
        )
        if reason
    ]
    return {
        "schema_version": DYNAMIC_VALUE_OPERATION_SCHEMA,
        "operation_kind": operation_kind,
        "destination_key": destination_key,
        "destination_hash": destination_hash,
        "target_alias": target_alias,
        "scope_kind": scope_kind,
        "lifecycle": lifecycle,
        "operand": operand.to_json(),
        "minimum": minimum.to_json() if minimum is not None else None,
        "maximum": maximum.to_json() if maximum is not None else None,
        "coverage_status": "blocked" if blockers else "executable",
        "blocked_reason": ";".join(dict.fromkeys(blockers)),
    }


def lower_decoded_dynamic_value_operation_spec(
    decoded_kind: str,
    payload: Mapping[str, Any],
) -> dict[str, JSONValue]:
    """Adapt S3 semantic payloads without dispatching on obfuscated families."""

    target_alias = payload.get("target_alias")
    dynamic_key = payload.get("dynamic_key")
    if decoded_kind == "dynamic_value_definition":
        standard: dict[str, Any] = {
            "target_alias": target_alias,
            "value_name": dynamic_key,
            "value_expr": numeric_fixed(0.0),
            "context_scope": None,
        }
        return lower_dynamic_value_operation_spec("DefineDynamicValue", standard)
    if decoded_kind != "dynamic_value_write":
        raise ValueError(f"decoded source is not dynamic:{decoded_kind}")
    operation = payload.get("operation")
    if operation not in {None, "Set", "Add"}:
        raise ValueError(f"decoded dynamic write operation is unresolved:{operation}")
    standard = {
        "target_alias": target_alias,
        "value_name": dynamic_key,
        "value_expr": payload.get("value_expression"),
        "add_value": payload.get("value_expression"),
        "operation": operation or "Set",
        "context_scope": None,
    }
    opcode = "SetDynamicValueByAddValue" if operation == "Add" else "SetDynamicValue"
    return lower_dynamic_value_operation_spec(opcode, standard)


def _dynamic_scope(value: object) -> tuple[str, str]:
    scope = str(value or "")
    if scope in {"ContextAbility", "ContextTaskTemplate"}:
        return "ability", "ability_action"
    if scope == "ContextModifier":
        return "status", "status_instance"
    if scope in {"ContextCaster", "ContextOwner", "TargetEntity", "SummonerEntity"}:
        return "unit", "combat"
    return "contextual", "execution_context"


def _dynamic_operation_kind(opcode: str, raw_operation: object) -> str:
    if opcode == "DefineDynamicValue":
        return "define"
    operation = str(raw_operation or "").lower()
    if operation == "add" or "ByAdd" in opcode:
        return "add"
    if operation == "copy" or "Copying" in opcode:
        return "copy"
    return "set"


def _dynamic_operand(opcode: str, standard: Mapping[str, Any]) -> NumericOperandIR:
    if opcode in {
        "DefineDynamicValue",
        "SetDynamicValue",
        "SetDynamicValueClientOnly",
        "SetModifierDynamicValue",
    }:
        if opcode == "SetDynamicValueClientOnly":
            lowered = _expression_operand("value", standard.get("value_expr"))
            return NumericOperandIR(
                operand_id=lowered.operand_id,
                operand_kind=lowered.operand_kind,
                parameters=lowered.parameters,
                expression=lowered.expression,
                coverage_status="blocked",
                blocked_reason="client_only_dynamic_value",
                required_producer="non_gameplay_excluded",
            )
        return _expression_operand("value", standard.get("value_expr"))
    if opcode == "SetDynamicValueByAdsorption":
        # Snaps the destination slot to a near integer, removing float noise.
        threshold = standard.get("adsorption_threshold")
        admitted = type(threshold) in (int, float) and math.isfinite(threshold) and threshold > 0
        return NumericOperandIR(
            operand_id="operand:slot_adsorption",
            operand_kind="slot_adsorption",
            parameters={"threshold_json": json.dumps(threshold)},
            coverage_status="executable" if admitted else "blocked",
            blocked_reason="" if admitted else "adsorption_threshold_not_admitted",
            required_producer="" if admitted else "source_lowering",
        )
    if opcode == "SetDynamicValueByAddValue":
        return _expression_operand("add_value", standard.get("add_value"))
    if opcode == "SetDynamicValueByModifierValue":
        parameters = {
            "source_target_alias": str(standard.get("source_target_alias") or ""),
            "modifier_name": str(standard.get("source_modifier") or ""),
            "modifier_value_name": str(standard.get("source_value_name") or ""),
        }
        if standard.get("source_target_expression_id"):
            parameters["source_target_expression_id"] = standard["source_target_expression_id"]
        scale_expression = standard.get("multiplier")
        valid = all(
            isinstance(value, str) and bool(value) for value in parameters.values()
        ) and (
            isinstance(scale_expression, Mapping)
            and is_exact_numeric_expression(scale_expression)
            and scale_expression.get("supported") is True
        )
        return NumericOperandIR(
            operand_id="operand:modifier_value",
            operand_kind="modifier_value",
            parameters=parameters,
            scale_expression=(scale_expression if isinstance(scale_expression, Mapping) else None),
            coverage_status="executable" if valid else "blocked",
            blocked_reason="" if valid else "modifier_value_identity_or_multiplier_missing",
            required_producer="" if valid else "source_lowering",
        )

    operand_kind = _dynamic_operand_kind(opcode)
    raw_parameters = standard.get("operand_parameters")
    if not isinstance(raw_parameters, Mapping):
        raw_parameters = {}
    if opcode == "SetDynamicValueByVariateType" and raw_parameters.get("variate_type") == "TargetCharacterID":
        operand_kind = "unit_identity"
    parameters = _typed_operand_parameters(opcode, operand_kind, raw_parameters)
    if raw_parameters.get("source_target_expression_id") and "source_target_alias" in parameters:
        parameters["source_target_expression_id"] = raw_parameters["source_target_expression_id"]
    source_alias = parameters.get("source_target_alias")
    source_alias_supported = (
        not source_alias or source_alias in _DYNAMIC_RUNTIME_TARGET_ALIASES
        or (operand_kind == "unit_property" and source_alias == "SnapshotPropertyEntity")
        or bool(parameters.get("source_target_expression_id"))
        and (operand_kind == "character_count" or raw_parameters.get("source_target_expression_admitted") is True)
    )
    # The heal-data reader is the first effect-event value producer to close.
    # The formal heal mutation projection publishes the realized heal amount and
    # the healer identity on the event payload consumed through
    # DynamicValueExecutionRequest.event_payload.  Every other event_value
    # family keeps its blocked record until it has a typed producer of its own.
    event_value_producer_admitted = (
        operand_kind == "event_value"
        and (
            opcode == "SetDynamicValueByHealDataProperty"
            # HP-change variate reads publish the committed HP delta.
            or (
                opcode == "SetDynamicValueByVariateType"
                and parameters.get("variate_type") == "ParamValue"
            )
            # Ability-property change callbacks publish the committed delta.
            or opcode == "SetDynamicValueByChangeValue"
            # Hit-window events publish the committed final damage of the hit;
            # the OnAfterHitAll true-damage callbacks read it as their base.
            or (
                opcode == "SetDynamicValueByDamageDataProperty"
                and parameters.get("property_name")
                in {"Result_FinalDamageBase", "Result_FinalDamage"}
            )
        )
    )
    executable = (
        operand_kind in {
            "dynamic_value",
            "unit_property",
            "unit_identity",
            "status_count",
            "hp_ratio",
            "shield_value",
            "team_resource",
            "character_count",
            # Battle setup world level is a typed global fact read by the
            # dynamic value executor.
            "world_level",
        }
        or event_value_producer_admitted
    ) and _generic_operand_parameters_complete(operand_kind, parameters)
    executable = executable and source_alias_supported
    if opcode == "SetDynamicValueByPropertyClientOnly":
        executable = False
        blocked_reason = "client_only_dynamic_value"
        required_producer = "non_gameplay_excluded"
    elif not source_alias_supported:
        blocked_reason = f"unsupported_dynamic_source_target_alias:{source_alias}"
        required_producer = "target_alias_resolution"
    elif operand_kind == "character_count" and parameters.get("predicate_json") != "null":
        executable = False
        blocked_reason = "character_count_predicate_not_admitted"
        required_producer = "target_predicate_lowering"
    elif operand_kind == "character_count" and type(parameters.get("alive_only")) is not bool:
        executable = False
        blocked_reason = "character_count_alive_policy_missing"
        required_producer = "source_lowering"
    elif operand_kind == "unit_property" and not ability_property_is_runtime_readable(
        parameters.get("property_name")
    ):
        executable = False
        blocked_reason = (
            "unit_property_runtime_producer_missing:"
            f"{parameters.get('property_name') or '<missing>'}"
        )
        required_producer = "shared_property_registry"
    elif operand_kind == "event_value" and not event_value_producer_admitted:
        executable = False
        blocked_reason = (
            "event_value_producer_not_closed:"
            f"{opcode}"
        )
        required_producer = "effect_event_value_producer"
    elif not executable:
        blocked_reason = str(
            standard.get("operand_blocked_reason")
            or f"operand_producer_not_closed:{operand_kind}"
        )
        required_producer = "P9-S10-S15_domain_producer"
    else:
        blocked_reason = ""
        required_producer = ""
    return NumericOperandIR(
        operand_id=f"operand:{operand_kind}",
        operand_kind=operand_kind,
        parameters=parameters,
        scale_expression=(
            standard.get("multiplier")
            if isinstance(standard.get("multiplier"), Mapping)
            else None
        ),
        coverage_status="executable" if executable else "blocked",
        blocked_reason=blocked_reason,
        required_producer=required_producer,
    )


def _dynamic_operand_kind(opcode: str) -> str:
    ordered = (
        ("PreCalcStanceDamage", "precalculated_stance_damage"),
        ("DamageDataProperty", "event_value"),
        ("HealDataProperty", "event_value"),
        ("BreakBaseDamage", "break_base_damage"),
        ("StatusResistance", "status_resistance"),
        ("SkillProperty", "skill_property"),
        ("ModifierValue", "modifier_value"),
        ("StatusCount", "status_count"),
        ("HPRatio", "hp_ratio"),
        ("Shield", "shield_value"),
        ("Property", "unit_property"),
        ("Copying", "dynamic_value"),
        ("CharacterCount", "character_count"),
        ("CountOfBaseType", "base_type_count"),
        ("FormationIndex", "formation_index"),
        ("WaveStageCount", "wave_stage_count"),
        ("TargetToTeamCenterDistance", "team_center_distance"),
        ("WeaknessCount", "weakness_count"),
        ("AttackTargetCount", "event_value"),
        ("Random", "random_range"),
        ("BPChange", "event_value"),
        ("CurrentBP", "team_resource"),
        ("MaxBP", "team_resource"),
        ("WorldLevel", "world_level"),
        ("ChangeValue", "event_value"),
        ("VariateType", "event_value"),
    )
    return next((kind for marker, kind in ordered if marker in opcode), "blocked_external")


def _generic_operand_parameters_complete(
    operand_kind: str,
    parameters: Mapping[str, Any],
) -> bool:
    required = {
        "dynamic_value": ("source_key", "source_target_alias"),
        "unit_property": ("property_name", "source_target_alias"),
        "unit_identity": ("identity_kind", "source_target_alias"),
        "status_count": ("count_mode", "source_target_alias"),
        "hp_ratio": ("source_target_alias",),
        "shield_value": ("source_target_alias",),
        "team_resource": ("resource_name",),
        "character_count": ("source_target_expression_id",),
        "event_value": ("event_kind", "source_target_alias"),
        "world_level": (),
    }[operand_kind]
    return all(isinstance(parameters.get(key), str) and parameters.get(key) for key in required)


def _typed_operand_parameters(
    opcode: str,
    operand_kind: str,
    raw: Mapping[str, Any],
) -> dict[str, Any]:
    string = lambda key: str(raw.get(key) or "")
    optional_string = lambda key: (
        str(raw[key]) if raw.get(key) is not None else None
    )
    source_alias = string("source_target_alias")
    if operand_kind == "dynamic_value":
        return {
            "source_target_alias": source_alias,
            "source_key": string("source_key"),
            "source_hash": optional_string("source_hash"),
            "source_modifier": optional_string("source_modifier"),
        }
    if operand_kind == "unit_property":
        return {"source_target_alias": source_alias, "property_name": string("property_name")}
    if operand_kind == "unit_identity":
        return {"source_target_alias": source_alias, "identity_kind": "character_id"}
    if operand_kind == "modifier_value":
        return {"source_target_alias": source_alias, "modifier_name": string("modifier_name"),
                "modifier_value_name": string("modifier_value_name")}
    if operand_kind == "status_count":
        return {"source_target_alias": source_alias, "count_mode": "debuff"}
    if operand_kind in {"hp_ratio", "shield_value", "break_base_damage", "formation_index"}:
        return {"source_target_alias": source_alias}
    if operand_kind == "team_resource":
        return {"resource_name": string("resource_name")}
    if operand_kind == "character_count":
        alive_only = raw.get("alive_only")
        return {
            "source_target_alias": source_alias,
            "source_target_expression_id": string("source_target_expression_id"),
            "alive_only": alive_only if isinstance(alive_only, bool) else None,
            "predicate_json": _canonical_source_json(raw.get("predicate")),
        }
    if operand_kind == "base_type_count":
        base_types = raw.get("base_types")
        return {
            "base_types": [
                item for item in (base_types if isinstance(base_types, (list, tuple)) else ())
                if isinstance(item, str) and item
            ]
        }
    if operand_kind == "weakness_count":
        return {
            "source_target_alias": source_alias,
            "weakness_filter_json": _canonical_source_json(raw.get("weakness_filter")),
        }
    if operand_kind == "event_value":
        return {
            "event_kind": opcode,
            "property_name": optional_string("event_property"),
            "value_type": optional_string("value_type"),
            "variate_type": optional_string("variate_type"),
            "source_target_alias": optional_string("source_target_alias"),
            "attacker_alias": optional_string("attacker_alias"),
        }
    if operand_kind == "skill_property":
        return {
            "property_name": string("property_name"),
            "skill_trigger_json": _canonical_source_json(raw.get("skill_trigger_key")),
        }
    if operand_kind == "status_resistance":
        return {"source_target_alias": source_alias, "status_flag": string("status_flag")}
    if operand_kind == "precalculated_stance_damage":
        return {"source_descriptor_json": _canonical_source_json(raw)}
    if operand_kind == "random_range":
        minimum = raw.get("minimum")
        maximum = raw.get("maximum")
        return {
            "minimum": minimum if isinstance(minimum, Mapping) else numeric_missing("random_minimum_missing"),
            "maximum": maximum if isinstance(maximum, Mapping) else numeric_missing("random_maximum_missing"),
            "integer_only": raw.get("integer_only") is True,
        }
    if operand_kind == "world_level":
        return {}
    if operand_kind == "wave_stage_count":
        return {"source_kind": "battle_wave_stage"}
    if operand_kind == "team_center_distance":
        alive_only = raw.get("alive_only")
        return {
            "source_target_alias": source_alias,
            "alive_only": alive_only if isinstance(alive_only, bool) else None,
        }
    return {
        "source_family": opcode,
        "source_descriptor_json": _canonical_source_json(raw),
    }


def _canonical_source_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _expression_operand(operand_id: str, expression: object) -> NumericOperandIR:
    exact = isinstance(expression, Mapping) and is_exact_numeric_expression(expression)
    supported = exact and expression.get("supported") is True
    return NumericOperandIR(
        operand_id=f"operand:{operand_id}",
        operand_kind="expression",
        parameters={"formula_role": operand_id},
        expression=expression if exact else numeric_unsupported("numeric_operand_not_lowered"),
        coverage_status="executable" if supported else "blocked",
        blocked_reason=(
            ""
            if supported
            else str(
                expression.get("reason")
                if isinstance(expression, Mapping)
                else "numeric_operand_not_lowered"
            )
        ),
        required_producer="" if supported else "source_lowering",
    )


def _optional_expression_operand(
    operand_id: str,
    expression: object,
) -> NumericOperandIR | None:
    if not isinstance(expression, Mapping) or expression.get("kind") == "missing":
        return None
    return _expression_operand(operand_id, expression)


def _lower_postfix_program(postfix: dict[str, Any]) -> dict[str, JSONValue]:
    from ..dynamic_key_hash import tbgd_dynamic_key_hash

    opcodes = _decode_opcodes(postfix.get("OpCodes"))
    if opcodes is None:
        return numeric_unsupported("postfix_opcodes_decode_failed")
    fixed_values = _fixed_values(postfix.get("FixedValues"))
    if fixed_values is None:
        return numeric_unsupported("fixed_operand_non_finite_or_invalid")
    dynamic_hashes = postfix.get("DynamicHashes") if isinstance(postfix.get("DynamicHashes"), list) else []
    # Opcode 16 calls the function symbol below N numeric arguments. Its first
    # stack operand is NOT a numeric variable or a zero-floor placeholder.
    # Resolve the TBGD-hashed symbol at this L0 boundary, never in runtime.
    functions = {tbgd_dynamic_key_hash(name): (operation, arity) for name, operation, arity in (
        ("max", "max", None), ("min", "min", None),
        ("floor", "floor", 1), ("ceil", "ceil", 1),
        ("int", "truncate", 1), ("abs", "absolute", 1),
    )}
    stack: list[list[dict[str, JSONValue]]] = []
    index = 0
    ended = False
    while index < len(opcodes):
        opcode = opcodes[index]
        if opcode == 17:
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
                stack.append([{"opcode": "push_fixed", "value": fixed_values[operand_index]}])
            else:
                if operand_index < 0 or operand_index >= len(dynamic_hashes):
                    return numeric_unsupported("dynamic_operand_unresolved")
                hash_value = _json_scalar(dynamic_hashes[operand_index])
                if isinstance(hash_value, bool):
                    return numeric_unsupported("dynamic_operand_hash_bool")
                stack.append([{"opcode": "push_dynamic", "hash": hash_value}])
            index += 2
            continue
        if opcode == 16:
            if index + 1 >= len(opcodes):
                return numeric_unsupported("postfix_call_operand_count_missing")
            operand_count = int(opcodes[index + 1])
            if operand_count < 1:
                return numeric_unsupported("postfix_call_operand_count_invalid")
            if len(stack) < operand_count + 1:
                return numeric_unsupported("postfix_stack_underflow")
            symbol = stack[-operand_count - 1]
            if len(symbol) != 1 or symbol[0].get("opcode") != "push_dynamic":
                return numeric_unsupported("postfix_call_function_symbol_missing")
            function = functions.get(symbol[0].get("hash"))
            if function is None:
                return numeric_unsupported("postfix_call_function_not_admitted")
            operation, arity = function
            if arity is not None and operand_count != arity:
                return numeric_unsupported("postfix_call_function_arity_mismatch")
            operands = stack[-operand_count:]
            del stack[-operand_count - 1:]
            instruction = {"opcode": operation}
            if operation in {"min", "max"}:
                instruction["operand_count"] = operand_count
            stack.append([item for operand in operands for item in operand] + [instruction])
            index += 2
            continue
        operation = {2: "add", 3: "sub", 4: "mul", 5: "div", 14: "negate"}.get(opcode)
        if operation is None:
            return numeric_unsupported(f"unsupported_postfix_opcode:{opcode}")
        if operation == "negate":
            if not stack:
                return numeric_unsupported("postfix_stack_underflow")
            stack[-1] = [*stack[-1], {"opcode": operation}]
        else:
            if len(stack) < 2:
                return numeric_unsupported("postfix_stack_underflow")
            rhs = stack.pop()
            lhs = stack.pop()
            stack.append([*lhs, *rhs, {"opcode": operation}])
        index += 1
    if not ended:
        return numeric_unsupported("postfix_missing_end_opcode")
    if len(stack) != 1:
        return numeric_unsupported("postfix_final_stack_size")
    instructions = [*stack[0], {"opcode": "end"}]
    if all(item["opcode"] != "push_dynamic" for item in instructions):
        folded = _fold_fixed_program(tuple(instructions))
        if folded is not None:
            return numeric_fixed(folded)
    if len(instructions) == 2 and instructions[0].get("opcode") == "push_dynamic":
        return numeric_dynamic_hash(instructions[0].get("hash"))
    return {"schema_version": NUMERIC_EXPRESSION_SCHEMA, "kind": "program",
            "supported": True, "instructions": instructions}

def _fold_fixed_program(instructions: tuple[dict[str, JSONValue], ...]) -> float | None:
    stack: list[float] = []
    for instruction in instructions:
        opcode = instruction.get("opcode")
        if opcode == "end":
            continue
        if opcode == "push_fixed":
            value = instruction.get("value")
            if not _finite_number(value):
                return None
            stack.append(float(value))
            continue
        if opcode in NUMERIC_UNARY_OPERATIONS:
            if not stack:
                return None
            try:
                stack[-1] = numeric_unary_value(opcode, stack[-1])
            except (OverflowError, ValueError):
                return None
            continue
        if opcode in {"min", "max"}:
            operand_count = instruction.get("operand_count")
            if (
                not isinstance(operand_count, int)
                or isinstance(operand_count, bool)
                or operand_count < 1
                or len(stack) < operand_count
            ):
                return None
            operands = stack[-operand_count:]
            del stack[-operand_count:]
            stack.append(max(operands) if opcode == "max" else min(operands))
            continue
        if len(stack) < 2:
            return None
        rhs = stack.pop()
        lhs = stack.pop()
        if opcode == "add":
            result = lhs + rhs
        elif opcode == "sub":
            result = lhs - rhs
        elif opcode == "mul":
            result = lhs * rhs
        elif opcode == "div" and rhs != 0:
            result = lhs / rhs
        else:
            return None
        if not math.isfinite(result):
            return None
        stack.append(result)
    return stack[0] if len(stack) == 1 else None


def _decode_opcodes(value: Any) -> list[int] | None:
    if isinstance(value, list) and all(
        isinstance(item, int) and not isinstance(item, bool) for item in value
    ):
        return [int(item) for item in value]
    if not isinstance(value, str) or not value:
        return None
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    try:
        return list(base64.b64decode(padded, validate=True))
    except (ValueError, TypeError):
        return None


def _fixed_values(value: Any) -> list[float] | None:
    if not isinstance(value, list):
        return []
    result: list[float] = []
    for item in value:
        raw = item.get("Value") if isinstance(item, dict) else item
        if _finite_number(raw):
            result.append(float(raw))
        else:
            return None
    return result


def _json_scalar(value: Any) -> JSONValue:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return str(value)


def _finite_number(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False
