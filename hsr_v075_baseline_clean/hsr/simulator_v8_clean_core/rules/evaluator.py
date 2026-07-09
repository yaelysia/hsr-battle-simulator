from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from .ir import ConditionIR, FormulaIR


@dataclass(frozen=True)
class EvaluationContext:
    state: Any | None = None
    actor_id: str | None = None
    target_id: str | None = None
    owner_id: str | None = None
    param_entity_id: str | None = None
    current_action_target_id: str | None = None
    status_detail: dict[str, Any] | None = None
    event_payload: dict[str, Any] | None = None
    dynamic_values: dict[str, float] | None = None
    binding_sources: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class NumericEvaluationContext:
    dynamic_values: dict[str, float] | None = None
    binding_sources: tuple[dict[str, Any], ...] = ()
    source_trace: dict[str, Any] | None = None


@dataclass(frozen=True)
class NumericEvaluationResult:
    ok: bool
    value: float | None
    expression_kind: str
    bindings: dict[str, Any]
    source_trace: dict[str, Any]
    blocked_reason: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "value": self.value,
            "expression_kind": self.expression_kind,
            "bindings": self.bindings,
            "source_trace": self.source_trace,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class ConditionEvaluationResult:
    ok: bool
    result: bool | None
    condition_id: str
    opcode: str
    reason: str
    details: dict[str, Any]
    source_trace: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "opcode": self.opcode,
            "ok": self.ok,
            "result": self.result,
            "reason": self.reason,
            "details": self.details,
            "source_trace": self.source_trace,
        }


EXECUTABLE_CONDITION_OPCODES = {
    "AlwaysTrue",
    "ByAnd",
    "ByAny",
    "ByAttackType",
    "ByCompareDynamicValue",
    "ByCompareHPRatio",
    "ByCompareModifierValue",
    "ByCompareMonsterID",
    "ByCompareDamageCustomName",
    "ByCompareTarget",
    "ByContainBehaviorFlag",
    "ByContainsParamFlag",
    "ByCurrentSkillType",
    "ByIsContainModifier",
    "ByHaveEnemyAlive",
    "ByIsCurrentSkillActive",
    "ByIsInsertAction",
    "ByNot",
    "ByTargetListIntersects",
    "ByTargetEntityType",
    "ByTargetTeam",
}


class RuleEvaluator:
    """Conservative evaluator for v0_200.

    Only literal and identity-safe expressions are executable. Everything else
    remains audit-only or unsupported until the corresponding HSR mechanic is
    implemented explicitly.
    """

    def evaluate_condition(self, condition: ConditionIR, context: EvaluationContext) -> bool | None:
        result = self.evaluate_condition_result(condition, context)
        return result.result if result.ok else None

    def evaluate_condition_result(
        self,
        condition: ConditionIR,
        context: EvaluationContext,
    ) -> ConditionEvaluationResult:
        source_trace = condition.source.to_json()
        if condition.opcode not in EXECUTABLE_CONDITION_OPCODES:
            return ConditionEvaluationResult(
                ok=False,
                result=None,
                condition_id=condition.condition_id,
                opcode=condition.opcode,
                reason=f"condition_opcode_not_supported:{condition.opcode}",
                details={"coverage_status": condition.coverage_status},
                source_trace=source_trace,
            )
        result = _evaluate_condition_payload(
            self,
            condition.opcode,
            condition.payload,
            context,
            condition_id=condition.condition_id,
            source_trace=source_trace,
        )
        if condition.coverage_status != "executable" and result.ok:
            return ConditionEvaluationResult(
                ok=False,
                result=None,
                condition_id=condition.condition_id,
                opcode=condition.opcode,
                reason=f"condition_not_executable_in_ir:{condition.coverage_status}",
                details=result.details,
                source_trace=source_trace,
            )
        return result

    def evaluate_formula(self, formula: FormulaIR, context: EvaluationContext) -> float | None:
        expression = formula.expression
        if formula.coverage_status != "executable":
            return None
        if formula.kind == "fixed_value":
            result = self.evaluate_numeric(
                {"kind": "fixed", "value": expression.get("Value")},
                NumericEvaluationContext(
                    dynamic_values=context.dynamic_values,
                    binding_sources=context.binding_sources,
                    source_trace=formula.source.to_json(),
                ),
            )
            return result.value if result.ok else None
        if formula.kind == "dynamic_hash":
            result = self.evaluate_numeric(
                {"kind": "dynamic_hash", "hash": expression.get("hash")},
                NumericEvaluationContext(
                    dynamic_values=context.dynamic_values,
                    binding_sources=context.binding_sources,
                    source_trace=formula.source.to_json(),
                ),
            )
            return result.value if result.ok else None
        return None

    def evaluate_numeric(self, expression: Any, context: NumericEvaluationContext | None = None) -> NumericEvaluationResult:
        context = context or NumericEvaluationContext()
        source_trace = dict(context.source_trace or {})
        if isinstance(expression, (int, float)):
            return NumericEvaluationResult(
                ok=True,
                value=float(expression),
                expression_kind="fixed",
                bindings={},
                source_trace=source_trace,
            )
        if expression is None:
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="missing",
                bindings={},
                source_trace=source_trace,
                blocked_reason="missing",
            )
        if not isinstance(expression, dict):
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="unsupported",
                bindings={"raw": expression},
                source_trace=source_trace,
                blocked_reason="unsupported_numeric_expression",
            )

        kind = str(expression.get("kind") or "")
        if kind == "fixed" and isinstance(expression.get("value"), (int, float)):
            return NumericEvaluationResult(
                ok=True,
                value=float(expression["value"]),
                expression_kind="fixed",
                bindings={},
                source_trace=source_trace,
            )
        if kind == "missing":
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="missing",
                bindings={},
                source_trace=source_trace,
                blocked_reason=str(expression.get("reason") or "missing"),
            )
        if kind == "dynamic_hash":
            return _evaluate_dynamic_hash(expression, context, source_trace)
        if kind == "postfix_expr":
            return _evaluate_postfix_expr(expression.get("raw") or expression, context, source_trace)
        if kind == "unsupported":
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="unsupported",
                bindings={"raw": expression.get("raw")},
                source_trace=source_trace,
                blocked_reason=str(expression.get("reason") or "unsupported_numeric_expression"),
            )

        fixed = expression.get("FixedValue")
        if isinstance(fixed, dict) and isinstance(fixed.get("Value"), (int, float)):
            return self.evaluate_numeric(
                {"kind": "fixed", "value": fixed["Value"]},
                context,
            )
        if isinstance(expression.get("Value"), (int, float)):
            return self.evaluate_numeric(
                {"kind": "fixed", "value": expression["Value"]},
                context,
            )
        postfix = expression.get("PostfixExpr")
        if isinstance(postfix, dict):
            return _evaluate_postfix_expr(expression, context, source_trace)

        return NumericEvaluationResult(
            ok=False,
            value=None,
            expression_kind=kind or "unsupported",
            bindings={"raw": expression},
            source_trace=source_trace,
            blocked_reason="unsupported_numeric_expression",
        )


def _evaluate_dynamic_hash(
    expression: dict[str, Any],
    context: NumericEvaluationContext,
    source_trace: dict[str, Any],
) -> NumericEvaluationResult:
    hash_value = expression.get("hash")
    key = str(hash_value)
    sources_checked: list[dict[str, Any]] = []
    for index, source in enumerate(context.binding_sources):
        value, binding = _lookup_binding_source(source, key)
        sources_checked.append(
            {
                "source_type": str(source.get("source_type") or f"binding_source:{index}"),
                "hit": value is not None,
            }
        )
        if value is not None:
            return NumericEvaluationResult(
                ok=True,
                value=value,
                expression_kind="dynamic_hash",
                bindings={"hash": hash_value, "key": key, "value": value, **binding},
                source_trace=source_trace,
            )
    values = context.dynamic_values or {}
    if key in values and isinstance(values[key], (int, float)):
        return NumericEvaluationResult(
            ok=True,
            value=float(values[key]),
            expression_kind="dynamic_hash",
            bindings={
                "hash": hash_value,
                "key": key,
                "value": float(values[key]),
                "source_type": "explicit_dynamic_values",
            },
            source_trace=source_trace,
        )
    sources_checked.append({"source_type": "explicit_dynamic_values", "hit": False})
    return NumericEvaluationResult(
        ok=False,
        value=None,
        expression_kind="dynamic_hash",
        bindings={"hash": hash_value, "key": key, "sources_checked": sources_checked},
        source_trace=source_trace,
        blocked_reason=f"dynamic_hash_unbound:{key}",
    )


def _evaluate_postfix_expr(
    expression: dict[str, Any],
    context: NumericEvaluationContext,
    source_trace: dict[str, Any],
) -> NumericEvaluationResult:
    postfix = expression.get("PostfixExpr") if isinstance(expression.get("PostfixExpr"), dict) else expression
    if not isinstance(postfix, dict):
        return NumericEvaluationResult(
            ok=False,
            value=None,
            expression_kind="postfix_expr",
            bindings={"raw": expression},
            source_trace=source_trace,
            blocked_reason="postfix_expr_missing",
        )
    opcodes = _decode_postfix_opcodes(postfix.get("OpCodes"))
    if opcodes is None:
        return NumericEvaluationResult(
            ok=False,
            value=None,
            expression_kind="postfix_expr",
            bindings={"raw": expression},
            source_trace=source_trace,
            blocked_reason="postfix_opcodes_decode_failed",
        )
    fixed_values = _postfix_fixed_values(postfix.get("FixedValues"))
    dynamic_hashes = postfix.get("DynamicHashes") if isinstance(postfix.get("DynamicHashes"), list) else []
    stack: list[float] = []
    tokens: list[dict[str, Any]] = []
    dynamic_operands: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    unsupported: list[int] = []
    ended = False
    index = 0
    while index < len(opcodes):
        opcode = opcodes[index]
        if opcode == 17:
            tokens.append({"op": "end"})
            ended = True
            index += 1
            continue
        if opcode == 0:
            if index + 1 >= len(opcodes):
                errors.append({"op": opcode, "reason": "missing_fixed_index"})
                break
            fixed_index = int(opcodes[index + 1])
            tokens.append({"op": "fixed", "index": fixed_index})
            if fixed_index < 0 or fixed_index >= len(fixed_values):
                errors.append({"op": opcode, "index": fixed_index, "reason": "fixed_operand_unresolved"})
            else:
                stack.append(float(fixed_values[fixed_index]))
            index += 2
            continue
        if opcode == 1:
            if index + 1 >= len(opcodes):
                errors.append({"op": opcode, "reason": "missing_dynamic_index"})
                break
            dynamic_index = int(opcodes[index + 1])
            tokens.append({"op": "dynamic", "index": dynamic_index})
            if dynamic_index < 0 or dynamic_index >= len(dynamic_hashes):
                errors.append({"op": opcode, "index": dynamic_index, "reason": "dynamic_hash_missing"})
            else:
                dynamic_hash = dynamic_hashes[dynamic_index]
                result = _evaluate_dynamic_hash(
                    {"kind": "dynamic_hash", "hash": dynamic_hash, "raw": expression},
                    context,
                    source_trace,
                )
                operand = {
                    "index": dynamic_index,
                    "hash": dynamic_hash,
                    "ok": result.ok,
                    "value": result.value,
                    "bindings": result.bindings,
                    "blocked_reason": result.blocked_reason,
                }
                dynamic_operands.append(operand)
                if not result.ok or result.value is None:
                    errors.append(
                        {
                            "op": opcode,
                            "index": dynamic_index,
                            "hash": dynamic_hash,
                            "reason": result.blocked_reason or "dynamic_operand_unresolved",
                        }
                    )
                else:
                    stack.append(float(result.value))
            index += 2
            continue
        if opcode in {2, 3, 4, 5}:
            op_name = {2: "add", 3: "sub", 4: "mul", 5: "div"}[opcode]
            tokens.append({"op": op_name})
            if len(stack) < 2:
                errors.append({"op": opcode, "reason": "stack_underflow"})
            else:
                rhs = stack.pop()
                lhs = stack.pop()
                if opcode == 2:
                    stack.append(lhs + rhs)
                elif opcode == 3:
                    stack.append(lhs - rhs)
                elif opcode == 4:
                    stack.append(lhs * rhs)
                elif rhs == 0:
                    errors.append({"op": opcode, "reason": "division_by_zero"})
                else:
                    stack.append(lhs / rhs)
            index += 1
            continue
        unsupported.append(opcode)
        tokens.append({"op": f"unsupported_{opcode}", "opcode": opcode})
        index += 1

    bindings = {
        "raw": expression,
        "opcodes_bytes": opcodes,
        "tokens": tokens,
        "fixed_values": fixed_values,
        "dynamic_operands": dynamic_operands,
    }
    if unsupported:
        return NumericEvaluationResult(
            ok=False,
            value=None,
            expression_kind="postfix_expr",
            bindings={**bindings, "unsupported_opcode_bytes": sorted(set(unsupported))},
            source_trace=source_trace,
            blocked_reason="unsupported_postfix_opcode",
        )
    if errors:
        return NumericEvaluationResult(
            ok=False,
            value=None,
            expression_kind="postfix_expr",
            bindings={**bindings, "errors": errors},
            source_trace=source_trace,
            blocked_reason=str(errors[0].get("reason") or "postfix_evaluation_error"),
        )
    if not ended:
        return NumericEvaluationResult(
            ok=False,
            value=None,
            expression_kind="postfix_expr",
            bindings=bindings,
            source_trace=source_trace,
            blocked_reason="postfix_missing_end_opcode",
        )
    if len(stack) != 1:
        return NumericEvaluationResult(
            ok=False,
            value=None,
            expression_kind="postfix_expr",
            bindings={**bindings, "final_stack_size": len(stack)},
            source_trace=source_trace,
            blocked_reason="postfix_final_stack_size",
        )
    return NumericEvaluationResult(
        ok=True,
        value=float(stack[0]),
        expression_kind="postfix_expr",
        bindings={**bindings, "pattern": "postfix_add_sub_mul_div"},
        source_trace=source_trace,
    )


def _decode_postfix_opcodes(value: Any) -> list[int] | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return list(base64.b64decode(value))
    except Exception:
        return None


def _postfix_fixed_values(value: Any) -> list[float]:
    fixed_values: list[float] = []
    if not isinstance(value, list):
        return fixed_values
    for item in value:
        raw = item.get("Value") if isinstance(item, dict) else item
        if isinstance(raw, (int, float)):
            fixed_values.append(float(raw))
    return fixed_values


def _evaluate_condition_payload(
    evaluator: RuleEvaluator,
    opcode: str,
    payload: dict[str, Any],
    context: EvaluationContext,
    *,
    condition_id: str,
    source_trace: dict[str, Any],
) -> ConditionEvaluationResult:
    if payload.get("Inverse") is True:
        positive_payload = dict(payload)
        positive_payload.pop("Inverse", None)
        positive = _evaluate_condition_payload(
            evaluator,
            opcode,
            positive_payload,
            context,
            condition_id=condition_id,
            source_trace=source_trace,
        )
        if not positive.ok or positive.result is None:
            return positive
        return ConditionEvaluationResult(
            ok=True,
            result=not positive.result,
            condition_id=positive.condition_id,
            opcode=positive.opcode,
            reason=f"inverted:{positive.reason}",
            details={"positive": positive.to_json()},
            source_trace=source_trace,
        )
    if opcode == "AlwaysTrue":
        return _condition_result(True, condition_id, opcode, "condition_true", {}, source_trace)
    if opcode == "ByCurrentSkillType":
        expected = payload.get("SkillType") or "Normal"
        actual = (context.event_payload or {}).get("SkillType") or (context.event_payload or {}).get("skill_type")
        return _condition_result(
            expected == actual,
            condition_id,
            opcode,
            "skill_type_compared",
            {"expected": expected, "actual": actual},
            source_trace,
        )
    if opcode == "ByAttackType":
        expected = payload.get("AttackTypes")
        if not isinstance(expected, list):
            return _condition_blocked(condition_id, opcode, "attack_types_missing", {"payload": payload}, source_trace)
        actual = (context.event_payload or {}).get("AttackType") or (context.event_payload or {}).get("attack_type")
        return _condition_result(
            str(actual) in {str(item) for item in expected},
            condition_id,
            opcode,
            "attack_type_compared",
            {"expected": expected, "actual": actual},
            source_trace,
        )
    if opcode == "ByTargetTeam":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        if target_id is None:
            return _condition_blocked(condition_id, opcode, "target_alias_unresolved", target_details, source_trace)
        unit = _state_unit(context, target_id)
        if unit is None:
            return _condition_blocked(condition_id, opcode, "target_unit_missing", {"target_id": target_id}, source_trace)
        expected = payload.get("Team")
        result, reason = _team_matches(unit, expected)
        if result is None:
            return _condition_blocked(condition_id, opcode, reason, {"expected": expected, "target_id": target_id}, source_trace)
        return _condition_result(
            result,
            condition_id,
            opcode,
            "target_team_compared",
            {"expected": expected, "target_id": target_id, "side": getattr(unit, "side", None)},
            source_trace,
        )
    if opcode == "ByIsContainModifier":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        if target_id is None:
            return _condition_blocked(condition_id, opcode, "target_alias_unresolved", target_details, source_trace)
        modifier_name = _value_field(payload.get("ModifierName"))
        if not isinstance(modifier_name, str) or not modifier_name:
            return _condition_blocked(condition_id, opcode, "modifier_name_missing", {"payload": payload}, source_trace)
        contains = _unit_has_modifier(context, target_id, modifier_name)
        return _condition_result(
            contains,
            condition_id,
            opcode,
            "modifier_presence_compared",
            {"target_id": target_id, "modifier_name": modifier_name, "contains": contains},
            source_trace,
        )
    if opcode == "ByContainBehaviorFlag":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        if target_id is None:
            return _condition_blocked(condition_id, opcode, "target_alias_unresolved", target_details, source_trace)
        flag = payload.get("Flag")
        if not isinstance(flag, str) or not flag:
            return _condition_blocked(condition_id, opcode, "behavior_flag_missing", {"payload": payload}, source_trace)
        matched = _unit_has_behavior_flag(context, target_id, flag)
        if payload.get("Inverse") is True:
            matched = not matched
        return _condition_result(
            matched,
            condition_id,
            opcode,
            "behavior_flag_checked",
            {"target_id": target_id, "flag": flag, "inverse": payload.get("Inverse") is True},
            source_trace,
        )
    if opcode == "ByContainsParamFlag":
        flag = payload.get("Flag")
        if not isinstance(flag, str) or not flag:
            return _condition_blocked(condition_id, opcode, "param_flag_missing", {"payload": payload}, source_trace)
        event_payload = context.event_payload or {}
        flags = _payload_flags(event_payload)
        matched = flag in flags or event_payload.get(flag) is True
        if payload.get("Inverse") is True:
            matched = not matched
        return _condition_result(
            matched,
            condition_id,
            opcode,
            "param_flag_checked",
            {"flag": flag, "flags": sorted(flags), "inverse": payload.get("Inverse") is True},
            source_trace,
        )
    if opcode == "ByIsInsertAction":
        payload_value = (context.event_payload or {}).get("is_insert_action")
        matched = payload_value is True
        if payload.get("Inverse") is True:
            matched = not matched
        return _condition_result(
            matched,
            condition_id,
            opcode,
            "insert_action_flag_checked",
            {"actual": payload_value, "inverse": payload.get("Inverse") is True},
            source_trace,
        )
    if opcode == "ByIsCurrentSkillActive":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        if target_id is None:
            return _condition_blocked(condition_id, opcode, "target_alias_unresolved", target_details, source_trace)
        payload_value = (context.event_payload or {}).get("is_current_skill_active")
        matched = payload_value is True
        if payload.get("Inverse") is True:
            matched = not matched
        return _condition_result(
            matched,
            condition_id,
            opcode,
            "current_skill_active_flag_checked",
            {"target_id": target_id, "actual": payload_value, "inverse": payload.get("Inverse") is True},
            source_trace,
        )
    if opcode == "ByHaveEnemyAlive":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        if target_id is None:
            return _condition_blocked(condition_id, opcode, "target_alias_unresolved", target_details, source_trace)
        state = context.state
        units = getattr(state, "units", None)
        actor = _state_unit(context, target_id)
        if not isinstance(units, dict) or actor is None:
            return _condition_blocked(condition_id, opcode, "state_or_actor_missing", {"target_id": target_id}, source_trace)
        actor_side = getattr(actor, "side", None)
        alive_enemies = [
            unit_id
            for unit_id, unit in units.items()
            if getattr(unit, "side", None) != actor_side and float(getattr(unit, "hp", 0.0) or 0.0) > 0
        ]
        matched = bool(alive_enemies)
        if payload.get("Inverse") is True:
            matched = not matched
        return _condition_result(
            matched,
            condition_id,
            opcode,
            "enemy_alive_checked",
            {"target_id": target_id, "alive_enemy_ids": alive_enemies, "inverse": payload.get("Inverse") is True},
            source_trace,
        )
    if opcode == "ByCompareHPRatio":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        if target_id is None:
            return _condition_blocked(condition_id, opcode, "target_alias_unresolved", target_details, source_trace)
        unit = _state_unit(context, target_id)
        if unit is None:
            return _condition_blocked(condition_id, opcode, "target_unit_missing", {"target_id": target_id}, source_trace)
        max_hp = float(getattr(unit, "max_hp", 0.0) or 0.0)
        if max_hp <= 0:
            return _condition_blocked(condition_id, opcode, "target_max_hp_not_positive", {"target_id": target_id}, source_trace)
        compare_value = evaluator.evaluate_numeric(
            payload.get("CompareValue"),
            NumericEvaluationContext(
                dynamic_values=context.dynamic_values,
                binding_sources=context.binding_sources,
                source_trace=source_trace,
            ),
        )
        if not compare_value.ok or compare_value.value is None:
            return _condition_blocked(
                condition_id,
                opcode,
                f"compare_value_blocked:{compare_value.blocked_reason}",
                {"numeric_evaluation": compare_value.to_json()},
                source_trace,
            )
        actual = float(getattr(unit, "hp", 0.0) or 0.0) / max_hp
        return _comparison_condition(condition_id, opcode, actual, payload.get("CompareType"), compare_value.value, source_trace)
    if opcode == "ByCompareDynamicValue":
        key = _value_field(payload.get("DynamicKey"))
        if not isinstance(key, str) or not key:
            return _condition_blocked(condition_id, opcode, "dynamic_key_missing", {"payload": payload}, source_trace)
        actual = evaluator.evaluate_numeric(
            {"kind": "dynamic_hash", "hash": key},
            NumericEvaluationContext(
                dynamic_values=context.dynamic_values,
                binding_sources=context.binding_sources,
                source_trace=source_trace,
            ),
        )
        if not actual.ok or actual.value is None:
            return _condition_blocked(
                condition_id,
                opcode,
                f"dynamic_value_blocked:{actual.blocked_reason}",
                {"dynamic_key": key, "numeric_evaluation": actual.to_json()},
                source_trace,
            )
        compare_value = evaluator.evaluate_numeric(
            payload.get("CompareValue"),
            NumericEvaluationContext(
                dynamic_values=context.dynamic_values,
                binding_sources=context.binding_sources,
                source_trace=source_trace,
            ),
        )
        if not compare_value.ok or compare_value.value is None:
            return _condition_blocked(
                condition_id,
                opcode,
                f"compare_value_blocked:{compare_value.blocked_reason}",
                {"numeric_evaluation": compare_value.to_json()},
                source_trace,
            )
        return _comparison_condition(condition_id, opcode, actual.value, payload.get("CompareType"), compare_value.value, source_trace)
    if opcode == "ByCompareModifierValue":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        if target_id is None:
            return _condition_blocked(condition_id, opcode, "target_alias_unresolved", target_details, source_trace)
        actual_value, actual_reason = _modifier_value_for_condition(context, target_id, payload.get("ValueType"))
        if actual_value is None:
            return _condition_blocked(condition_id, opcode, actual_reason, {"target_id": target_id}, source_trace)
        compare_value = evaluator.evaluate_numeric(
            payload.get("CompareValue"),
            NumericEvaluationContext(
                dynamic_values=context.dynamic_values,
                binding_sources=context.binding_sources,
                source_trace=source_trace,
            ),
        )
        if not compare_value.ok or compare_value.value is None:
            return _condition_blocked(
                condition_id,
                opcode,
                f"compare_value_blocked:{compare_value.blocked_reason}",
                {"numeric_evaluation": compare_value.to_json()},
                source_trace,
            )
        return _comparison_condition(condition_id, opcode, actual_value, payload.get("CompareType"), compare_value.value, source_trace)
    if opcode == "ByCompareTarget":
        left_id, left_details = _resolve_condition_target(payload.get("TargetType"), context)
        right_id, right_details = _resolve_condition_target(payload.get("CompareType"), context)
        if left_id is None or right_id is None:
            return _condition_blocked(
                condition_id,
                opcode,
                "target_alias_unresolved",
                {"left": left_details, "right": right_details},
                source_trace,
            )
        return _condition_result(
            left_id == right_id,
            condition_id,
            opcode,
            "target_identity_compared",
            {"left_target_id": left_id, "right_target_id": right_id},
            source_trace,
        )
    if opcode == "ByTargetEntityType":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        if target_id is None:
            return _condition_blocked(condition_id, opcode, "target_alias_unresolved", target_details, source_trace)
        unit = _state_unit(context, target_id)
        if unit is None:
            return _condition_blocked(condition_id, opcode, "target_unit_missing", {"target_id": target_id}, source_trace)
        entity_type = payload.get("EntityTypeMask")
        if entity_type != "Servant":
            return _condition_blocked(
                condition_id,
                opcode,
                f"entity_type_not_supported:{entity_type or 'missing'}",
                {"target_id": target_id, "entity_type_mask": entity_type},
                source_trace,
            )
        is_servant = getattr(unit, "side", None) == "summon" and getattr(unit, "flags", {}).get("summon_kind") == "servant"
        if payload.get("Inverse") is True:
            is_servant = not is_servant
        return _condition_result(
            is_servant,
            condition_id,
            opcode,
            "target_entity_type_checked",
            {"target_id": target_id, "entity_type_mask": entity_type, "inverse": payload.get("Inverse") is True},
            source_trace,
        )
    if opcode == "ByCompareMonsterID":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        if target_id is None:
            return _condition_blocked(condition_id, opcode, "target_alias_unresolved", target_details, source_trace)
        unit = _state_unit(context, target_id)
        if unit is None:
            return _condition_blocked(condition_id, opcode, "target_unit_missing", {"target_id": target_id}, source_trace)
        expected = evaluator.evaluate_numeric(
            payload.get("TargetMonsterID"),
            NumericEvaluationContext(
                dynamic_values=context.dynamic_values,
                binding_sources=context.binding_sources,
                source_trace=source_trace,
            ),
        )
        if not expected.ok or expected.value is None:
            return _condition_blocked(
                condition_id,
                opcode,
                f"target_monster_id_blocked:{expected.blocked_reason}",
                {"numeric_evaluation": expected.to_json()},
                source_trace,
            )
        actual = _unit_monster_id(unit)
        if actual is None:
            return _condition_blocked(condition_id, opcode, "target_monster_id_missing", {"target_id": target_id}, source_trace)
        return _comparison_condition(condition_id, opcode, float(actual), payload.get("CompareType") or "Equal", expected.value, source_trace)
    if opcode == "ByCompareDamageCustomName":
        expected = _value_field(payload.get("CustomName"))
        if not isinstance(expected, str) or not expected:
            return _condition_blocked(condition_id, opcode, "damage_custom_name_missing", {"payload": payload}, source_trace)
        event_payload = context.event_payload or {}
        actual = (
            event_payload.get("damage_custom_name")
            or event_payload.get("custom_name")
            or event_payload.get("CustomName")
        )
        return _condition_result(
            str(actual) == expected,
            condition_id,
            opcode,
            "damage_custom_name_compared",
            {"expected": expected, "actual": actual},
            source_trace,
        )
    if opcode == "ByTargetListIntersects":
        first_id, first_details = _resolve_condition_target(payload.get("FirstTargetType"), context)
        if first_id is None:
            return _condition_blocked(condition_id, opcode, "first_target_alias_unresolved", first_details, source_trace)
        second_alias = _target_alias(payload.get("SecondTargetType"))
        second_targets = _target_list_for_alias(second_alias, context)
        if second_targets is None:
            return _condition_blocked(
                condition_id,
                opcode,
                f"second_target_list_alias_not_supported:{second_alias or 'missing'}",
                {"payload": payload},
                source_trace,
            )
        matched = first_id in second_targets
        if payload.get("Inverse") is True:
            matched = not matched
        return _condition_result(
            matched,
            condition_id,
            opcode,
            "target_list_intersection_checked",
            {
                "first_target_id": first_id,
                "second_alias": second_alias,
                "second_target_ids": sorted(second_targets),
                "inverse": payload.get("Inverse") is True,
            },
            source_trace,
        )
    if opcode in {"ByAnd", "ByAny"}:
        predicates = payload.get("PredicateList")
        if not isinstance(predicates, list):
            return _condition_blocked(condition_id, opcode, "predicate_list_missing", {"payload": payload}, source_trace)
        child_results = [
            _evaluate_raw_condition(evaluator, item, context, condition_id=condition_id, source_trace=source_trace)
            for item in predicates
        ]
        if opcode == "ByAnd":
            for child in child_results:
                if not child.ok:
                    return _condition_blocked(condition_id, opcode, f"child_blocked:{child.reason}", {"children": [item.to_json() for item in child_results]}, source_trace)
                if child.result is False:
                    return _condition_result(False, condition_id, opcode, "and_child_false", {"children": [item.to_json() for item in child_results]}, source_trace)
            return _condition_result(True, condition_id, opcode, "and_all_true", {"children": [item.to_json() for item in child_results]}, source_trace)
        for child in child_results:
            if child.ok and child.result is True:
                return _condition_result(True, condition_id, opcode, "any_child_true", {"children": [item.to_json() for item in child_results]}, source_trace)
        blocked = [child for child in child_results if not child.ok]
        if blocked:
            return _condition_blocked(condition_id, opcode, f"child_blocked:{blocked[0].reason}", {"children": [item.to_json() for item in child_results]}, source_trace)
        return _condition_result(False, condition_id, opcode, "any_all_false", {"children": [item.to_json() for item in child_results]}, source_trace)
    if opcode == "ByNot":
        predicate = payload.get("Predicate")
        if not isinstance(predicate, dict):
            return _condition_blocked(condition_id, opcode, "predicate_missing", {"payload": payload}, source_trace)
        child = _evaluate_raw_condition(evaluator, predicate, context, condition_id=condition_id, source_trace=source_trace)
        if not child.ok or child.result is None:
            return _condition_blocked(condition_id, opcode, f"child_blocked:{child.reason}", {"child": child.to_json()}, source_trace)
        return _condition_result(not child.result, condition_id, opcode, "not_child_inverted", {"child": child.to_json()}, source_trace)
    return _condition_blocked(condition_id, opcode, f"condition_opcode_not_supported:{opcode}", {"payload": payload}, source_trace)


def _evaluate_raw_condition(
    evaluator: RuleEvaluator,
    raw: object,
    context: EvaluationContext,
    *,
    condition_id: str,
    source_trace: dict[str, Any],
) -> ConditionEvaluationResult:
    if not isinstance(raw, dict):
        return _condition_blocked(condition_id, "Unknown", "raw_condition_not_object", {"raw": raw}, source_trace)
    opcode = _short_gamecore_type(raw.get("$type"))
    payload = {key: value for key, value in raw.items() if key != "$type"}
    return _evaluate_condition_payload(
        evaluator,
        opcode,
        payload,
        context,
        condition_id=condition_id,
        source_trace=source_trace,
    )


def _condition_result(
    result: bool,
    condition_id: str,
    opcode: str,
    reason: str,
    details: dict[str, Any],
    source_trace: dict[str, Any],
) -> ConditionEvaluationResult:
    return ConditionEvaluationResult(
        ok=True,
        result=result,
        condition_id=condition_id,
        opcode=opcode,
        reason=reason,
        details=details,
        source_trace=source_trace,
    )


def _condition_blocked(
    condition_id: str,
    opcode: str,
    reason: str,
    details: dict[str, Any],
    source_trace: dict[str, Any],
) -> ConditionEvaluationResult:
    return ConditionEvaluationResult(
        ok=False,
        result=None,
        condition_id=condition_id,
        opcode=opcode,
        reason=reason,
        details=details,
        source_trace=source_trace,
    )


def _comparison_condition(
    condition_id: str,
    opcode: str,
    actual: float,
    compare_type: object,
    expected: float,
    source_trace: dict[str, Any],
) -> ConditionEvaluationResult:
    result = _compare(actual, compare_type, expected)
    if result is None:
        return _condition_blocked(
            condition_id,
            opcode,
            f"compare_type_not_supported:{compare_type}",
            {"actual": actual, "expected": expected, "compare_type": compare_type},
            source_trace,
        )
    return _condition_result(
        result,
        condition_id,
        opcode,
        "numeric_comparison",
        {"actual": actual, "expected": expected, "compare_type": compare_type},
        source_trace,
    )


def _compare(actual: float, compare_type: object, expected: float) -> bool | None:
    if compare_type == "Less":
        return actual < expected
    if compare_type == "LessEqual":
        return actual <= expected
    if compare_type == "Greater":
        return actual > expected
    if compare_type == "GreaterEqual":
        return actual >= expected
    if compare_type == "Equal":
        return actual == expected
    if compare_type == "NotEqual":
        return actual != expected
    return None


def _resolve_condition_target(alias_value: object, context: EvaluationContext) -> tuple[str | None, dict[str, Any]]:
    alias = _target_alias(alias_value)
    mapping = {
        "Caster": context.actor_id,
        "ModifierOwnerEntity": context.owner_id or context.actor_id,
        "ParamEntity": context.param_entity_id or context.target_id,
        "CurrentActionTarget": context.current_action_target_id or context.target_id,
    }
    if alias in mapping and mapping[alias] is not None:
        return str(mapping[alias]), {"alias": alias}
    return None, {"alias": alias, "supported_aliases": sorted(mapping)}


def _target_alias(value: object) -> str | None:
    if isinstance(value, dict):
        alias = value.get("Alias")
        if isinstance(alias, str):
            return alias
    return None


def _value_field(value: object) -> Any:
    if isinstance(value, dict) and "Value" in value:
        return value.get("Value")
    return value


def _state_unit(context: EvaluationContext, unit_id: str) -> Any | None:
    state = context.state
    units = getattr(state, "units", None)
    if isinstance(units, dict):
        return units.get(unit_id)
    return None


def _team_matches(unit: Any, expected: object) -> tuple[bool | None, str]:
    side = getattr(unit, "side", None)
    if expected == "TeamLight":
        return side in {"ally", "summon"}, "ok"
    if expected == "TeamDark":
        return side == "enemy", "ok"
    return None, f"team_not_supported:{expected}"


def _unit_has_modifier(context: EvaluationContext, unit_id: str, modifier_name: str) -> bool:
    unit = _state_unit(context, unit_id)
    if unit is None:
        return False
    flags = getattr(unit, "flags", {})
    details = flags.get("status_details", ()) if isinstance(flags, dict) else ()
    if not isinstance(details, (list, tuple)):
        return False
    for detail in details:
        if not isinstance(detail, dict):
            continue
        if detail.get("modifier_name") == modifier_name or detail.get("status_id") == f"modifier:{modifier_name}":
            return True
    return False


def _unit_has_behavior_flag(context: EvaluationContext, unit_id: str, flag: str) -> bool:
    unit = _state_unit(context, unit_id)
    if unit is None:
        return False
    flags = getattr(unit, "flags", {})
    if not isinstance(flags, dict):
        return False
    if flag == "Break" and bool(flags.get("broken", False)):
        return True
    direct = flags.get(flag)
    if direct is True:
        return True
    for key in ("behavior_flags", "control_flags", "status_flags"):
        values = flags.get(key)
        if isinstance(values, (list, tuple, set)) and flag in {str(item) for item in values}:
            return True
    statuses = getattr(unit, "statuses", ())
    if isinstance(statuses, (list, tuple, set)) and flag in {str(item) for item in statuses}:
        return True
    details = flags.get("status_details", ())
    if isinstance(details, (list, tuple)):
        for detail in details:
            if not isinstance(detail, dict):
                continue
            if detail.get("modifier_name") == flag or detail.get("status_id") == flag or detail.get("status_id") == f"modifier:{flag}":
                return True
            detail_flags = detail.get("behavior_flags")
            if isinstance(detail_flags, (list, tuple, set)) and flag in {str(item) for item in detail_flags}:
                return True
    return False


def _payload_flags(payload: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for key in ("param_flags", "flags", "ParamFlags", "FlagList"):
        values = payload.get(key)
        if isinstance(values, str) and values:
            result.add(values)
        elif isinstance(values, (list, tuple, set)):
            result.update(str(item) for item in values if isinstance(item, (str, int)))
    return result


def _target_list_for_alias(alias: str | None, context: EvaluationContext) -> set[str] | None:
    payload = context.event_payload or {}
    if alias == "GridFight_AllBackEnd":
        values = (
            payload.get("gridfight_backend_target_ids")
            or payload.get("backend_target_ids")
            or payload.get("GridFight_AllBackEnd")
            or ()
        )
        if isinstance(values, str):
            return {values} if values else set()
        if isinstance(values, (list, tuple, set)):
            return {str(item) for item in values if isinstance(item, (str, int))}
        return set()
    return None


def _unit_monster_id(unit: Any) -> int | None:
    flags = getattr(unit, "flags", {})
    if isinstance(flags, dict):
        for key in ("monster_id", "MonsterID"):
            value = flags.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
    template_id = str(getattr(unit, "template_id", "") or "")
    tail = template_id.rsplit(":", 1)[-1]
    return int(tail) if tail.isdigit() else None


def _modifier_value_for_condition(
    context: EvaluationContext,
    target_id: str,
    value_type: object,
) -> tuple[float | None, str]:
    details: list[dict[str, Any]] = []
    if isinstance(context.status_detail, dict):
        details.append(context.status_detail)
    unit = _state_unit(context, target_id)
    flags = getattr(unit, "flags", {}) if unit is not None else {}
    raw_details = flags.get("status_details", ()) if isinstance(flags, dict) else ()
    if isinstance(raw_details, (list, tuple)):
        details.extend(item for item in raw_details if isinstance(item, dict))
    for detail in details:
        if value_type == "Layer" and isinstance(detail.get("stacks"), (int, float)):
            return float(detail["stacks"]), "ok"
        if value_type == "LifeTime":
            for key in ("remaining_duration", "duration"):
                if isinstance(detail.get(key), (int, float)):
                    return float(detail[key]), "ok"
    return None, f"modifier_value_not_available:{value_type}"


def _short_gamecore_type(raw_type: object) -> str:
    if not isinstance(raw_type, str):
        return "Unknown"
    return raw_type.removeprefix("RPG.GameCore.")


def _lookup_binding_source(source: dict[str, Any], key: str) -> tuple[float | None, dict[str, Any]]:
    entries = source.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    by_hash = source.get("by_hash")
    value, entry_key, entry = _lookup_index(entries, by_hash, key)
    if value is not None:
        return value, _binding_metadata(source, entry_key, entry, matched_by="hash")
    by_name = source.get("by_name")
    value, entry_key, entry = _lookup_index(entries, by_name, key)
    if value is not None:
        return value, _binding_metadata(source, entry_key, entry, matched_by="name")
    values = source.get("values")
    if isinstance(values, dict) and isinstance(values.get(key), (int, float)):
        return float(values[key]), {
            "source_type": str(source.get("source_type") or "binding_source"),
            "matched_by": "values",
        }
    if isinstance(source.get(key), (int, float)):
        return float(source[key]), {
            "source_type": str(source.get("source_type") or "binding_source"),
            "matched_by": "direct_key",
        }
    return None, {}


def _lookup_index(
    entries: dict[str, Any],
    index: object,
    key: str,
) -> tuple[float | None, str | None, dict[str, Any] | None]:
    if not isinstance(index, dict) or key not in index:
        return None, None, None
    indexed = index[key]
    if isinstance(indexed, (int, float)):
        return float(indexed), None, None
    if isinstance(indexed, dict) and isinstance(indexed.get("value"), (int, float)):
        return float(indexed["value"]), None, indexed
    keys = indexed if isinstance(indexed, list) else [indexed]
    for entry_key in keys:
        if not isinstance(entry_key, str):
            continue
        entry = entries.get(entry_key)
        if isinstance(entry, dict) and isinstance(entry.get("value"), (int, float)):
            return float(entry["value"]), entry_key, entry
    return None, None, None


def _binding_metadata(
    source: dict[str, Any],
    entry_key: str | None,
    entry: dict[str, Any] | None,
    *,
    matched_by: str,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source_type": str(source.get("source_type") or "binding_source"),
        "matched_by": matched_by,
    }
    if entry_key is not None:
        metadata["entry_key"] = entry_key
    if entry is not None:
        metadata["entry"] = entry
    return metadata
