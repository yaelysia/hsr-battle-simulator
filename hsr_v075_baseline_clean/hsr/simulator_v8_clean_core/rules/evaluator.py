from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..unit_eligibility import (
    runtime_unit_is_dark_team,
    runtime_unit_is_light_team,
    runtime_unit_is_target_candidate,
    runtime_unit_is_unselectable,
    runtime_units_are_opposing_combat_teams,
    runtime_units_share_combat_team,
)
from .ir import ConditionIR, FormulaIR, TargetExpressionNodeIR
from .expression_ir import (
    CONDITION_EXPRESSION_NODE_SCHEMA,
    NUMERIC_EXPRESSION_SCHEMA,
    is_typed_numeric_expression,
    numeric_dynamic_hash,
    numeric_fixed,
)


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
    resolved_target_groups: dict[str, tuple[str, ...]] | None = None
    target_resolution_errors: dict[str, str] | None = None


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
    "ByCheckModifierCallBackBehaviorFlag",
    "ByCheckModifierCallBackIsSelf",
    "ByCheckModifierCallBackName",
    "ByCheckModifierCallBackStatusType",
    "ByCompareAbilityProperty",
    "ByCompareCharacterID",
    "ByCompareDynamicValue",
    "ByCompareCharacterNumber",
    "ByCompareCurrentModifierStatusType",
    "ByCompareHPRatio",
    "ByCompareModifierValue",
    "ByCompareMonsterID",
    "ByCompareDamageCustomName",
    "ByCompareTarget",
    "ByCompareTargetCount",
    "ByContainBehaviorFlag",
    "ByContainsParamFlag",
    "ByCurrentSkillName",
    "ByCurrentSkillType",
    "ByIsContainModifier",
    "ByHaveEnemyAlive",
    "ByIsCurrentSkillActive",
    "ByIsInsertAction",
    "ByIsTeammate",
    "ByIsTurnOwnerEntity",
    "ByNot",
    "ByStatusCount",
    "ByTargetAliveState",
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
        if condition.expression_schema_version != CONDITION_EXPRESSION_NODE_SCHEMA:
            return ConditionEvaluationResult(
                ok=False,
                result=None,
                condition_id=condition.condition_id,
                opcode=condition.opcode,
                reason="condition_expression_not_lowered",
                details={"schema_version": condition.expression_schema_version},
                source_trace=source_trace,
            )
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
                numeric_fixed(float(expression.get("Value"))),
                NumericEvaluationContext(
                    dynamic_values=context.dynamic_values,
                    binding_sources=context.binding_sources,
                    source_trace=formula.source.to_json(),
                ),
            )
            return result.value if result.ok else None
        if formula.kind == "dynamic_hash":
            result = self.evaluate_numeric(
                numeric_dynamic_hash(expression.get("hash")),
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
        if not is_typed_numeric_expression(expression):
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="not_lowered",
                bindings={},
                source_trace=source_trace,
                blocked_reason="numeric_expression_not_lowered",
            )
        assert isinstance(expression, dict)
        kind = str(expression.get("kind") or "")
        if kind == "fixed" and isinstance(expression.get("value"), (int, float)) and not isinstance(expression.get("value"), bool):
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
        if kind == "program" and expression.get("schema_version") == NUMERIC_EXPRESSION_SCHEMA:
            return _evaluate_numeric_program(expression, context, source_trace)
        if kind == "unsupported":
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="unsupported",
                bindings={},
                source_trace=source_trace,
                blocked_reason=str(expression.get("reason") or "unsupported_numeric_expression"),
            )

        return NumericEvaluationResult(
            ok=False,
            value=None,
            expression_kind=kind or "unsupported",
            bindings={},
            source_trace=source_trace,
            blocked_reason="typed_numeric_expression_kind_not_supported",
        )


def _evaluate_dynamic_hash(
    expression: dict[str, Any],
    context: NumericEvaluationContext,
    source_trace: dict[str, Any],
) -> NumericEvaluationResult:
    hash_value = expression.get("hash")
    key = str(hash_value)
    sources_checked: list[dict[str, Any]] = []
    matches: list[tuple[float, dict[str, Any]]] = []
    ambiguous_matches: list[dict[str, Any]] = []
    for index, source in enumerate(context.binding_sources):
        value, binding = _lookup_binding_source(source, key)
        sources_checked.append(
            {
                "source_type": str(source.get("source_type") or f"binding_source:{index}"),
                "hit": value is not None,
            }
        )
        if binding.get("ambiguous") is True:
            ambiguous_matches.append(binding)
        if value is not None:
            matches.append((value, binding))
    values = context.dynamic_values or {}
    if key in values and isinstance(values[key], (int, float)):
        matches.append(
            (
                float(values[key]),
                {"source_type": "explicit_dynamic_values", "entry_key": key},
            )
        )
        sources_checked.append({"source_type": "explicit_dynamic_values", "hit": True})
    else:
        sources_checked.append({"source_type": "explicit_dynamic_values", "hit": False})
    if ambiguous_matches or len(matches) > 1:
        return NumericEvaluationResult(
            ok=False,
            value=None,
            expression_kind="dynamic_hash",
            bindings={
                "hash": hash_value,
                "key": key,
                "sources_checked": sources_checked,
                "match_count": len(matches),
                "matches": [binding for _, binding in matches],
                "ambiguous_matches": ambiguous_matches,
            },
            source_trace=source_trace,
            blocked_reason=f"dynamic_hash_binding_ambiguous:{key}",
        )
    if matches:
        value, binding = matches[0]
        return NumericEvaluationResult(
            ok=True,
            value=value,
            expression_kind="dynamic_hash",
            bindings={
                "hash": hash_value,
                "key": key,
                "value": value,
                **binding,
            },
            source_trace=source_trace,
        )
    return NumericEvaluationResult(
        ok=False,
        value=None,
        expression_kind="dynamic_hash",
        bindings={"hash": hash_value, "key": key, "sources_checked": sources_checked},
        source_trace=source_trace,
        blocked_reason=f"dynamic_hash_unbound:{key}",
    )


def _evaluate_numeric_program(
    expression: dict[str, Any],
    context: NumericEvaluationContext,
    source_trace: dict[str, Any],
) -> NumericEvaluationResult:
    instructions = expression.get("instructions")
    if not isinstance(instructions, list):
        return NumericEvaluationResult(
            ok=False,
            value=None,
            expression_kind="program",
            bindings={},
            source_trace=source_trace,
            blocked_reason="numeric_program_instructions_missing",
        )
    stack: list[float] = []
    dynamic_operands: list[dict[str, Any]] = []
    ended = False
    for index, instruction in enumerate(instructions):
        if not isinstance(instruction, dict):
            return _numeric_program_blocked("numeric_program_instruction_invalid", source_trace, index)
        opcode = instruction.get("opcode")
        if opcode == "end":
            if index != len(instructions) - 1:
                return _numeric_program_blocked("numeric_program_tokens_after_end", source_trace, index)
            ended = True
            continue
        if opcode == "push_fixed":
            value = instruction.get("value")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return _numeric_program_blocked("numeric_program_fixed_operand_invalid", source_trace, index)
            stack.append(float(value))
            continue
        if opcode == "push_dynamic":
            result = _evaluate_dynamic_hash(
                numeric_dynamic_hash(instruction.get("hash")),
                context,
                source_trace,
            )
            dynamic_operands.append(result.to_json())
            if not result.ok or result.value is None:
                return _numeric_program_blocked(
                    result.blocked_reason or "numeric_program_dynamic_operand_unresolved",
                    source_trace,
                    index,
                    dynamic_operands=dynamic_operands,
                )
            stack.append(float(result.value))
            continue
        if opcode == "negate":
            if not stack:
                return _numeric_program_blocked(
                    "numeric_program_stack_underflow",
                    source_trace,
                    index,
                )
            stack[-1] = -stack[-1]
            continue
        if opcode not in {"add", "sub", "mul", "div"}:
            return _numeric_program_blocked("numeric_program_opcode_not_admitted", source_trace, index)
        if len(stack) < 2:
            return _numeric_program_blocked("numeric_program_stack_underflow", source_trace, index)
        rhs = stack.pop()
        lhs = stack.pop()
        if opcode == "add":
            stack.append(lhs + rhs)
        elif opcode == "sub":
            stack.append(lhs - rhs)
        elif opcode == "mul":
            stack.append(lhs * rhs)
        elif rhs == 0:
            return _numeric_program_blocked("numeric_program_division_by_zero", source_trace, index)
        else:
            stack.append(lhs / rhs)
    if not ended:
        return _numeric_program_blocked("numeric_program_end_missing", source_trace, len(instructions))
    if len(stack) != 1:
        return _numeric_program_blocked("numeric_program_final_stack_size", source_trace, len(instructions))
    return NumericEvaluationResult(
        ok=True,
        value=stack[0],
        expression_kind="program",
        bindings={"instruction_count": len(instructions), "dynamic_operands": dynamic_operands},
        source_trace=source_trace,
    )


def _numeric_program_blocked(
    reason: str,
    source_trace: dict[str, Any],
    instruction_index: int,
    *,
    dynamic_operands: list[dict[str, Any]] | None = None,
) -> NumericEvaluationResult:
    return NumericEvaluationResult(
        ok=False,
        value=None,
        expression_kind="program",
        bindings={
            "instruction_index": instruction_index,
            "dynamic_operands": dynamic_operands or [],
        },
        source_trace=source_trace,
        blocked_reason=reason,
    )


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
    event_payload = context.event_payload or {}
    if opcode == "ByCheckModifierCallBackIsSelf":
        explicit = event_payload.get("is_self")
        detail = context.status_detail or {}
        event_instance_id = event_payload.get("status_instance_id")
        listener_instance_id = detail.get("instance_id")
        if isinstance(explicit, bool):
            matched = explicit
        elif isinstance(event_instance_id, str) and isinstance(listener_instance_id, str):
            matched = bool(event_instance_id) and event_instance_id == listener_instance_id
        else:
            return _condition_blocked(
                condition_id,
                opcode,
                "modifier_callback_self_identity_missing",
                {"event_instance_id": event_instance_id, "listener_instance_id": listener_instance_id},
                source_trace,
            )
        return _condition_result(
            matched,
            condition_id,
            opcode,
            "modifier_callback_self_identity_compared",
            {"event_instance_id": event_instance_id, "listener_instance_id": listener_instance_id},
            source_trace,
        )
    if opcode == "ByCheckModifierCallBackName":
        expected = _value_field(payload.get("ModifierName"))
        actual = event_payload.get("modifier_name")
        if not isinstance(expected, str) or not expected:
            return _condition_blocked(condition_id, opcode, "modifier_name_missing", {}, source_trace)
        if not isinstance(actual, str) or not actual:
            return _condition_blocked(condition_id, opcode, "callback_modifier_name_missing", {}, source_trace)
        return _condition_result(
            actual == expected,
            condition_id,
            opcode,
            "modifier_callback_name_compared",
            {"expected": expected, "actual": actual},
            source_trace,
        )
    if opcode in {
        "ByCheckModifierCallBackStatusType",
        "ByCompareCurrentModifierStatusType",
    }:
        expected = _value_field(payload.get("TargetStatusType"))
        actual = event_payload.get("status_type")
        if not isinstance(expected, str) or not expected:
            return _condition_blocked(condition_id, opcode, "target_status_type_missing", {}, source_trace)
        if not isinstance(actual, str) or not actual:
            return _condition_blocked(condition_id, opcode, "callback_status_type_missing", {}, source_trace)
        return _condition_result(
            actual == expected,
            condition_id,
            opcode,
            "modifier_callback_status_type_compared",
            {"expected": expected, "actual": actual},
            source_trace,
        )
    if opcode == "ByCheckModifierCallBackBehaviorFlag":
        expected = payload.get("Flag")
        if not isinstance(expected, str) or not expected:
            return _condition_blocked(condition_id, opcode, "behavior_flag_missing", {}, source_trace)
        raw_flags = event_payload.get("behavior_flags")
        if not isinstance(raw_flags, (list, tuple)):
            return _condition_blocked(condition_id, opcode, "callback_behavior_flags_missing", {}, source_trace)
        flags = tuple(str(item) for item in raw_flags if isinstance(item, str))
        return _condition_result(
            expected in flags,
            condition_id,
            opcode,
            "modifier_callback_behavior_flag_checked",
            {"expected": expected, "behavior_flags": list(flags)},
            source_trace,
        )
    if opcode == "ByCompareAbilityProperty":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        if target_id is None:
            return _condition_blocked(condition_id, opcode, "target_alias_unresolved", target_details, source_trace)
        unit = _state_unit(context, target_id)
        actual = _unit_ability_property(unit, payload.get("Property"))
        if actual is None:
            return _condition_blocked(
                condition_id,
                opcode,
                "ability_property_not_available",
                {"target_id": target_id, "property": payload.get("Property")},
                source_trace,
            )
        expected = evaluator.evaluate_numeric(
            payload.get("CompareValue"),
            NumericEvaluationContext(
                dynamic_values=context.dynamic_values,
                binding_sources=context.binding_sources,
                source_trace=source_trace,
            ),
        )
        if not expected.ok or expected.value is None:
            return _condition_blocked(condition_id, opcode, expected.blocked_reason or "compare_value_blocked", {}, source_trace)
        return _comparison_condition(condition_id, opcode, actual, payload.get("CompareType"), expected.value, source_trace)
    if opcode == "ByCompareCharacterID":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        if target_id is None:
            return _condition_blocked(condition_id, opcode, "target_alias_unresolved", target_details, source_trace)
        unit = _state_unit(context, target_id)
        actual = _unit_character_id(unit)
        if actual is None:
            return _condition_blocked(condition_id, opcode, "target_character_id_missing", {"target_id": target_id}, source_trace)
        expected = evaluator.evaluate_numeric(
            payload.get("TargetCharacterID"),
            NumericEvaluationContext(binding_sources=context.binding_sources, source_trace=source_trace),
        )
        if not expected.ok or expected.value is None:
            return _condition_blocked(condition_id, opcode, expected.blocked_reason or "target_character_id_blocked", {}, source_trace)
        return _comparison_condition(
            condition_id,
            opcode,
            float(actual),
            payload.get("CompareType") or "Equal",
            expected.value,
            source_trace,
        )
    if opcode == "ByCompareTargetCount":
        target_ids, target_details = _condition_target_ids(payload.get("TargetType"), context)
        if target_ids is None:
            return _condition_blocked(condition_id, opcode, "target_group_unresolved", target_details, source_trace)
        if payload.get("AliveOnly") is True:
            target_ids = tuple(
                target_id
                for target_id in target_ids
                if _unit_is_alive(_state_unit(context, target_id))
            )
        expected = evaluator.evaluate_numeric(
            payload.get("Number"),
            NumericEvaluationContext(binding_sources=context.binding_sources, source_trace=source_trace),
        )
        if not expected.ok or expected.value is None:
            return _condition_blocked(condition_id, opcode, expected.blocked_reason or "target_count_blocked", {}, source_trace)
        return _comparison_condition(
            condition_id,
            opcode,
            float(len(target_ids)),
            payload.get("CompareType"),
            expected.value,
            source_trace,
        )
    if opcode == "ByCurrentSkillName":
        expected = _value_field(payload.get("SkillName"))
        actual = event_payload.get("skill_name") or event_payload.get("SkillName")
        if not isinstance(expected, str) or not expected:
            return _condition_blocked(condition_id, opcode, "skill_name_missing", {}, source_trace)
        if not isinstance(actual, str) or not actual:
            return _condition_blocked(condition_id, opcode, "current_skill_name_missing", {}, source_trace)
        return _condition_result(actual == expected, condition_id, opcode, "skill_name_compared", {"expected": expected, "actual": actual}, source_trace)
    if opcode == "ByIsTeammate":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        owner_id = context.owner_id or context.actor_id
        target = _state_unit(context, target_id) if target_id else None
        owner = _state_unit(context, str(owner_id)) if owner_id else None
        if target is None or owner is None:
            return _condition_blocked(condition_id, opcode, "teammate_identity_missing", target_details, source_trace)
        matched = runtime_units_share_combat_team(owner, target)
        return _condition_result(matched, condition_id, opcode, "teammate_checked", {"owner_id": owner_id, "target_id": target_id}, source_trace)
    if opcode == "ByIsTurnOwnerEntity":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        turn_owner_id = event_payload.get("turn_owner_id") or event_payload.get("actor_id") or event_payload.get("event_source_id")
        if target_id is None or not isinstance(turn_owner_id, str) or not turn_owner_id:
            return _condition_blocked(condition_id, opcode, "turn_owner_identity_missing", target_details, source_trace)
        return _condition_result(target_id == turn_owner_id, condition_id, opcode, "turn_owner_compared", {"target_id": target_id, "turn_owner_id": turn_owner_id}, source_trace)
    if opcode == "ByStatusCount":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        unit = _state_unit(context, target_id) if target_id else None
        if unit is None:
            return _condition_blocked(condition_id, opcode, "status_count_target_missing", target_details, source_trace)
        details = getattr(unit, "flags", {}).get("status_details", ())
        if not isinstance(details, (list, tuple)):
            return _condition_blocked(condition_id, opcode, "status_details_invalid", {"target_id": target_id}, source_trace)
        debuffs = tuple(
            detail
            for detail in details
            if isinstance(detail, dict)
            and str(detail.get("status_category") or "").lower() == "debuff"
        )
        expected = evaluator.evaluate_numeric(
            payload.get("CompareValue"),
            NumericEvaluationContext(
                dynamic_values=context.dynamic_values,
                binding_sources=context.binding_sources,
                source_trace=source_trace,
            ),
        )
        if not expected.ok or expected.value is None:
            return _condition_blocked(condition_id, opcode, expected.blocked_reason or "status_count_compare_blocked", {}, source_trace)
        return _comparison_condition(condition_id, opcode, float(len(debuffs)), payload.get("CompareType"), expected.value, source_trace)
    if opcode == "ByTargetAliveState":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        unit = _state_unit(context, target_id) if target_id else None
        if unit is None:
            return _condition_blocked(condition_id, opcode, "alive_state_target_missing", target_details, source_trace)
        if payload.get("AliveStateMask") != "Mask_AliveOrRevivable":
            return _condition_blocked(condition_id, opcode, "alive_state_mask_not_supported", {"mask": payload.get("AliveStateMask")}, source_trace)
        return _condition_blocked(
            condition_id,
            opcode,
            "revivable_lifecycle_state_not_available",
            {
                "target_id": target_id,
                "alive": _unit_is_alive(unit),
                "mask": "Mask_AliveOrRevivable",
            },
            source_trace,
        )
    if opcode == "ByCurrentSkillType":
        expected = payload.get("SkillType")
        if not isinstance(expected, str) or not expected:
            return _condition_blocked(condition_id, opcode, "skill_type_expected_missing", {"payload": payload}, source_trace)
        actual = (context.event_payload or {}).get("SkillType") or (context.event_payload or {}).get("skill_type")
        if not isinstance(actual, str) or not actual:
            return _condition_blocked(condition_id, opcode, "skill_type_context_missing", {"expected": expected}, source_trace)
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
        if not isinstance(expected, list) or not expected or any(not isinstance(item, str) or not item for item in expected):
            return _condition_blocked(condition_id, opcode, "attack_types_missing", {"payload": payload}, source_trace)
        actual = (context.event_payload or {}).get("AttackType") or (context.event_payload or {}).get("attack_type")
        if not isinstance(actual, str) or not actual:
            return _condition_blocked(condition_id, opcode, "attack_type_context_missing", {"expected": expected}, source_trace)
        return _condition_result(
            str(actual) in {str(item) for item in expected},
            condition_id,
            opcode,
            "attack_type_compared",
            {"expected": expected, "actual": actual},
            source_trace,
        )
    if opcode == "ByTargetTeam":
        target_ids, target_details = _condition_target_ids(payload.get("TargetType"), context)
        if target_ids is None:
            return _condition_blocked(condition_id, opcode, "target_alias_unresolved", target_details, source_trace)
        expected = payload.get("Team")
        checked: list[dict[str, Any]] = []
        for target_id in target_ids:
            unit = _state_unit(context, target_id)
            if unit is None:
                return _condition_blocked(condition_id, opcode, "target_unit_missing", {"target_id": target_id}, source_trace)
            result, reason = _team_matches(unit, expected)
            if result is None:
                return _condition_blocked(condition_id, opcode, reason, {"expected": expected, "target_id": target_id}, source_trace)
            checked.append({"target_id": target_id, "side": getattr(unit, "side", None), "matched": result})
        return _condition_result(
            bool(checked) and all(item["matched"] is True for item in checked),
            condition_id,
            opcode,
            "target_team_compared",
            {"expected": expected, "targets": checked},
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
    if opcode == "ByCompareCharacterNumber":
        errors = context.target_resolution_errors or {}
        if errors.get("TargetType"):
            return _condition_blocked(
                condition_id,
                opcode,
                f"target_group_blocked:{errors['TargetType']}",
                {"target_field": "TargetType"},
                source_trace,
            )
        groups = context.resolved_target_groups or {}
        if "TargetType" not in groups:
            return _condition_blocked(
                condition_id,
                opcode,
                "target_group_not_resolved",
                {"target_field": "TargetType"},
                source_trace,
            )
        expected = evaluator.evaluate_numeric(
            payload.get("CompareNumber"),
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
                f"compare_number_blocked:{expected.blocked_reason}",
                {"numeric_evaluation": expected.to_json()},
                source_trace,
            )
        return _comparison_condition(
            condition_id,
            opcode,
            float(len(groups["TargetType"])),
            payload.get("CompareType"),
            expected.value,
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
            numeric_dynamic_hash(key),
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
        target_id, target_details = _resolve_condition_target(
            payload.get("TargetType") or "ModifierOwnerEntity",
            context,
        )
        if target_id is None:
            return _condition_blocked(condition_id, opcode, "target_alias_unresolved", target_details, source_trace)
        actual_value, actual_reason = _modifier_value_for_condition(
            context,
            target_id,
            _value_field(payload.get("ModifierName")),
            payload.get("ValueType") or "Layer",
        )
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
        first_targets, first_details = _condition_target_ids(payload.get("FirstTargetType"), context)
        if first_targets is None:
            return _condition_blocked(condition_id, opcode, "first_target_alias_unresolved", first_details, source_trace)
        second_targets, second_details = _condition_target_ids(payload.get("SecondTargetType"), context)
        if second_targets is None:
            return _condition_blocked(
                condition_id,
                opcode,
                "second_target_alias_unresolved",
                second_details,
                source_trace,
            )
        matched = bool(set(first_targets) & set(second_targets))
        if payload.get("Inverse") is True:
            matched = not matched
        return _condition_result(
            matched,
            condition_id,
            opcode,
            "target_list_intersection_checked",
            {
                "first_target_ids": sorted(first_targets),
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
            _evaluate_typed_condition_node(evaluator, item, context, condition_id=condition_id, source_trace=source_trace)
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
        child = _evaluate_typed_condition_node(evaluator, predicate, context, condition_id=condition_id, source_trace=source_trace)
        if not child.ok or child.result is None:
            return _condition_blocked(condition_id, opcode, f"child_blocked:{child.reason}", {"child": child.to_json()}, source_trace)
        return _condition_result(not child.result, condition_id, opcode, "not_child_inverted", {"child": child.to_json()}, source_trace)
    return _condition_blocked(condition_id, opcode, f"condition_opcode_not_supported:{opcode}", {"payload": payload}, source_trace)


def _evaluate_typed_condition_node(
    evaluator: RuleEvaluator,
    node: object,
    context: EvaluationContext,
    *,
    condition_id: str,
    source_trace: dict[str, Any],
) -> ConditionEvaluationResult:
    if not isinstance(node, dict):
        return _condition_blocked(condition_id, "Unknown", "condition_node_not_object", {}, source_trace)
    if node.get("schema_version") != CONDITION_EXPRESSION_NODE_SCHEMA:
        return _condition_blocked(condition_id, "Unknown", "condition_node_schema_missing", {}, source_trace)
    if node.get("supported") is not True:
        return _condition_blocked(
            condition_id,
            str(node.get("opcode") or "Unknown"),
            str(node.get("blocked_reason") or "condition_node_not_admitted"),
            {},
            source_trace,
        )
    opcode = str(node.get("opcode") or "")
    metadata_keys = {
        "schema_version",
        "expression_kind",
        "opcode",
        "supported",
        "blocked_reason",
    }
    payload = {key: value for key, value in node.items() if key not in metadata_keys}
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
    payload = context.event_payload or {}
    mapping = {
        "Caster": context.actor_id,
        "ModifierOwnerEntity": context.owner_id or context.actor_id,
        "ParamEntity": context.param_entity_id or context.target_id,
        "CurrentActionTarget": context.current_action_target_id or context.target_id,
        "AbilityTargetEntity": context.current_action_target_id or context.target_id,
        "DamageDefenderEntity": _first_string(
            payload,
            "current_hit_target_id",
            "damage_defender_id",
            "primary_target_id",
            "target_id",
            "event_target_id",
        )
        or context.target_id,
        "DamageAttackerEntity": _first_string(
            payload,
            "damage_attacker_id",
            "actor_id",
            "source_id",
            "event_source_id",
        )
        or context.actor_id,
        "CurrentTurnOwnerEntity": _first_string(
            payload,
            "turn_owner_id",
            "actor_id",
            "event_source_id",
        ),
        "ParamEntity2": _first_string(
            payload,
            "param_entity_2_id",
            "param_entity2_id",
            "secondary_target_id",
        ),
    }
    if alias in mapping and mapping[alias] is not None:
        return str(mapping[alias]), {"alias": alias}
    return None, {"alias": alias, "supported_aliases": sorted(mapping)}


def _condition_target_ids(
    alias_value: object,
    context: EvaluationContext,
) -> tuple[tuple[str, ...] | None, dict[str, Any]]:
    alias = _target_alias(alias_value)
    target_id, details = _resolve_condition_target(alias_value, context)
    if target_id is not None:
        return (target_id,), details
    payload = context.event_payload or {}
    key_groups = {
        "AttackTargetList": (
            "attack_target_ids",
            "selected_target_ids",
            "target_ids",
        ),
        "ParamEntityAttackTargetList": (
            "param_entity_attack_target_ids",
            "attack_target_ids",
            "selected_target_ids",
        ),
        "SkillTargetEntityList": (
            "skill_target_ids",
            "selected_target_ids",
            "target_ids",
        ),
        "ParamEntitySkillTargetEntityList": (
            "param_entity_skill_target_ids",
            "skill_target_ids",
            "selected_target_ids",
        ),
        "SkillSubTargetEntityList": (
            "skill_sub_target_ids",
            "sub_target_ids",
        ),
    }
    if alias in key_groups:
        result = _payload_unit_ids(payload, key_groups[alias])
        if result:
            return result, {"alias": alias, "source": "event_payload"}
        return None, {"alias": alias, "reason": "event_target_list_missing"}
    state = context.state
    units = getattr(state, "units", None)
    if not isinstance(units, dict):
        return None, {"alias": alias, "reason": "state_units_missing"}
    owner_id = context.owner_id or context.actor_id
    owner = units.get(owner_id) if owner_id else None
    if alias in {
        "AllDarkTeam",
        "AllEnemy",
        "AllEnemyWithUnSelectable",
        "AllLightTeam",
        "AllTeamMember",
        "AllTeammate",
        "AllUnselectable",
    }:
        result: list[str] = []
        include_unselectable = alias in {
            "AllEnemyWithUnSelectable",
            "AllUnselectable",
        }
        for unit_id, unit in sorted(units.items()):
            if not runtime_unit_is_target_candidate(
                unit,
                include_unselectable=include_unselectable,
            ):
                continue
            if alias == "AllDarkTeam" and runtime_unit_is_dark_team(unit):
                result.append(unit_id)
            elif alias == "AllLightTeam" and runtime_unit_is_light_team(unit):
                result.append(unit_id)
            elif (
                alias in {"AllEnemy", "AllEnemyWithUnSelectable"}
                and owner is not None
                and runtime_units_are_opposing_combat_teams(owner, unit)
            ):
                result.append(unit_id)
            elif (
                alias == "AllTeamMember"
                and owner is not None
                and runtime_units_share_combat_team(owner, unit)
            ):
                result.append(unit_id)
            elif (
                alias == "AllTeammate"
                and owner is not None
                and unit_id != owner_id
                and runtime_units_share_combat_team(owner, unit)
            ):
                result.append(unit_id)
            elif alias == "AllUnselectable" and runtime_unit_is_unselectable(unit):
                result.append(unit_id)
        return tuple(result), {"alias": alias, "source": "battle_state"}
    if alias == "GridFight_AllBackEnd":
        result = _target_list_for_alias(alias, context)
        return (result, {"alias": alias}) if result is not None else (None, {"alias": alias})
    return None, {"alias": alias, "reason": "target_alias_not_admitted"}


def _payload_unit_ids(
    payload: dict[str, Any],
    keys: tuple[str, ...],
) -> tuple[str, ...]:
    result: list[str] = []
    for key in keys:
        value = payload.get(key)
        values = value if isinstance(value, (list, tuple)) else (value,)
        for item in values:
            if isinstance(item, str) and item and item not in result:
                result.append(item)
    return tuple(result)


def _first_string(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _target_alias(value: object) -> str | None:
    if isinstance(value, TargetExpressionNodeIR):
        return value.alias or None
    if isinstance(value, dict):
        alias = value.get("alias")
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


def _unit_ability_property(unit: Any | None, property_name: object) -> float | None:
    if unit is None or not isinstance(property_name, str):
        return None
    if property_name == "Shield":
        shields = getattr(unit, "shield_instances", ())
        if not isinstance(shields, (list, tuple)):
            return None
        return sum(
            float(item.get("remaining", 0.0))
            for item in shields
            if isinstance(item, dict)
            and isinstance(item.get("remaining"), (int, float))
            and not isinstance(item.get("remaining"), bool)
        )
    if property_name == "BreakDamageAddedRatio":
        resources = getattr(unit, "resources", {})
        if not isinstance(resources, dict):
            return None
        for key in ("BreakDamageAddedRatio", "break_damage_added_ratio"):
            value = resources.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        return None
    return None


def _unit_character_id(unit: Any | None) -> int | None:
    if unit is None:
        return None
    flags = getattr(unit, "flags", {})
    if isinstance(flags, dict):
        for key in ("character_id", "avatar_id", "profile_id"):
            value = flags.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
    template_id = str(getattr(unit, "template_id", "") or "")
    if template_id.startswith("avatar:"):
        tail = template_id.rsplit(":", 1)[-1]
        if tail.isdigit():
            return int(tail)
    return None


def _unit_is_alive(unit: Any | None) -> bool:
    if unit is None:
        return False
    flags = getattr(unit, "flags", {})
    lifecycle = str(flags.get("lifecycle_status") or "") if isinstance(flags, dict) else ""
    return lifecycle not in {"defeated", "removed"} and float(getattr(unit, "hp", 0.0) or 0.0) > 0


def _team_matches(unit: Any, expected: object) -> tuple[bool | None, str]:
    if expected == "TeamLight":
        return runtime_unit_is_light_team(unit), "ok"
    if expected == "TeamDark":
        return runtime_unit_is_dark_team(unit), "ok"
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
    modifier_name: object,
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
        if (
            isinstance(modifier_name, str)
            and modifier_name
            and detail.get("modifier_name") != modifier_name
        ):
            continue
        if value_type == "Layer" and isinstance(detail.get("stacks"), (int, float)):
            return float(detail["stacks"]), "ok"
        if value_type == "LifeTime":
            for key in ("remaining_duration", "duration"):
                if isinstance(detail.get(key), (int, float)):
                    return float(detail[key]), "ok"
        if value_type == "MaxLayer" and isinstance(detail.get("max_stacks"), (int, float)):
            return float(detail["max_stacks"]), "ok"
    return None, f"modifier_value_not_available:{modifier_name}:{value_type}"


def _lookup_binding_source(source: dict[str, Any], key: str) -> tuple[float | None, dict[str, Any]]:
    entries = source.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    by_hash = source.get("by_hash")
    value, entry_key, entry, conflicts = _lookup_index(entries, by_hash, key)
    if conflicts:
        return None, _ambiguous_binding_metadata(source, conflicts, matched_by="hash")
    if value is not None:
        return value, _binding_metadata(source, entry_key, entry, matched_by="hash")
    by_name = source.get("by_name")
    value, entry_key, entry, conflicts = _lookup_index(entries, by_name, key)
    if conflicts:
        return None, _ambiguous_binding_metadata(source, conflicts, matched_by="name")
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
) -> tuple[float | None, str | None, dict[str, Any] | None, tuple[str, ...]]:
    if not isinstance(index, dict) or key not in index:
        return None, None, None, ()
    indexed = index[key]
    if isinstance(indexed, (int, float)):
        return float(indexed), None, None, ()
    if isinstance(indexed, dict) and isinstance(indexed.get("value"), (int, float)):
        return float(indexed["value"]), None, indexed, ()
    keys = indexed if isinstance(indexed, list) else [indexed]
    resolved = tuple(
        entry_key
        for entry_key in keys
        if isinstance(entry_key, str)
        and isinstance(entries.get(entry_key), dict)
        and isinstance(entries[entry_key].get("value"), (int, float))
    )
    if len(resolved) > 1:
        return None, None, None, resolved
    for entry_key in keys:
        if not isinstance(entry_key, str):
            continue
        entry = entries.get(entry_key)
        if isinstance(entry, dict) and isinstance(entry.get("value"), (int, float)):
            return float(entry["value"]), entry_key, entry, ()
    return None, None, None, ()


def _ambiguous_binding_metadata(
    source: dict[str, Any],
    entry_keys: tuple[str, ...],
    *,
    matched_by: str,
) -> dict[str, Any]:
    return {
        "source_type": str(source.get("source_type") or "binding_source"),
        "matched_by": matched_by,
        "ambiguous": True,
        "candidate_entry_keys": list(entry_keys),
    }


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
