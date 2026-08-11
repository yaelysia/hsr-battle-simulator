from __future__ import annotations

import math
import json
from dataclasses import dataclass, replace
from types import MappingProxyType
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
from .condition_state import (
    ConditionOperandProvider,
    ConditionOperandRequest,
    ConditionOperandResolution,
    TransientConditionOperandProvider,
    TransientConditionOperandRequest,
    TransientConditionOperandResolution,
)
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
    committed_condition_provider: ConditionOperandProvider | None = None
    transient_invocation_id: str | None = None
    transient_window: str | None = None
    transient_condition_provider: TransientConditionOperandProvider | None = None


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


_PRE_P9_EXECUTABLE_CONDITION_OPCODES = {
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
    "ByCompareDamageTag",
    "ByCompareTarget",
    "ByCompareTargetCount",
    "ByContainBehaviorFlag",
    "ByContainsParamFlag",
    "ByCharacterDamageType",
    "ByCompareChangeValue",
    "ByCompareParamValue",
    "ByCompareSPRatio",
    "ByCompareWaveCount",
    "ByHasStanceWeak",
    "ByInTurnBasedGameModeState",
    "ByIsDamageCritical",
    "ByIsPropertyValueMinOrMax",
    "ByIsTargetValid",
    "ByIsTopActionDelayTarget",
    "ByRandomChance",
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

COMMITTED_STATE_CONDITION_OPCODES = frozenset(
    {
        "ByAvatarBaseType",
        "ByCasterAliveOrLimbo",
        "ByCompareBP",
        "ByCompareBattleEventID",
        "ByCompareHP",
        "ByCompareMonsterRank",
        "ByCompareResistChance",
        "ByCompareSpecialSPRatio",
        "ByCompareStance",
        "ByCompareStanceCount",
        "ByCompareStanceRatio",
        "ByContainsRedStance",
        "ByHasSummonRelation",
        "ByIsBattleEventEntity",
        "ByIsBodyPart",
        "ByIsEnemy",
        "ByIsSubTargetOfHpSharedGroup",
        "ByIsTargetUnselectable",
        "ByTargetIsStanceWeak",
        "ByTargetListAll",
        "ByTargetListAny",
    }
)

CONTEXTUAL_CONDITION_FACTS_BY_OPCODE = MappingProxyType({
    "ByCheckModifierCallBackModifierValue": ("status_callback.modifier_value",),
    "ByCompareNextUnusedInsertAction": ("queue.next_unused_insert_action_matches",),
    "ByCompareParamString": ("event.param_string",),
    "ByCompareSPChangeTag": ("resource_change.tags",),
    "ByCompareTurnActionEntityTeamType": ("turn.action_entity.team",),
    "ByCompareUnusedInsertAbilityCount": ("queue.unused_insert_ability_count",),
    "ByCompareUnusedUltraSkillCount": ("queue.unused_ultimate_count",),
    "ByCurrentSkillTargetType": ("action.target_type", "action.dynamic_target"),
    "ByDamageSourceContainBehaviorFlag": ("damage.source_behavior_flags",),
    "ByHasInsertActionByTarget": ("queue.has_insert_action_by_target",),
    "ByIsDamageType": ("damage.type",),
    "ByIsInCharmAction": ("action.charm_phase",),
    "ByIsSplitDamage": ("damage.is_split",),
    "ByIsTurnActionEntity": ("turn.action_entity.identity",),
    "ByTurnOwnerActionPhaseEnd": ("turn.owner.action_phase_end",),
    "ByTurnOwnerHasActionInTurn": ("turn.owner.has_action",),
    "ByTurnOwnerHasPendingOneMore": ("turn.owner.pending_one_more",),
})
CONTEXTUAL_CONDITION_OPCODES = frozenset(
    CONTEXTUAL_CONDITION_FACTS_BY_OPCODE
)

EXECUTABLE_CONDITION_OPCODES = frozenset(
    _PRE_P9_EXECUTABLE_CONDITION_OPCODES
) | COMMITTED_STATE_CONDITION_OPCODES | CONTEXTUAL_CONDITION_OPCODES


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
        if (
            kind == "fixed"
            and _finite_number(expression.get("value"))
        ):
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
    if (
        isinstance(hash_value, bool)
        or isinstance(hash_value, float) and not math.isfinite(hash_value)
        or hash_value is not None and not isinstance(hash_value, (int, float, str))
    ):
        return NumericEvaluationResult(
            ok=False,
            value=None,
            expression_kind="dynamic_hash",
            bindings={"hash": hash_value},
            source_trace=source_trace,
            blocked_reason="dynamic_hash_identity_invalid",
        )
    key = str(hash_value)
    values = context.dynamic_values or {}
    explicit_value = values.get(key)
    if _finite_number(explicit_value):
        return NumericEvaluationResult(
            ok=True,
            value=float(explicit_value),
            expression_kind="dynamic_hash",
            bindings={
                "hash": hash_value,
                "key": key,
                "value": float(explicit_value),
                "source_type": "explicit_dynamic_values",
                "entry_key": key,
            },
            source_trace=source_trace,
        )
    sources_checked: list[dict[str, Any]] = []
    matches: list[tuple[float, dict[str, Any]]] = []
    fallback_matches: list[tuple[float, dict[str, Any]]] = []
    ambiguous_matches: list[dict[str, Any]] = []
    for index, source in enumerate(context.binding_sources):
        value, binding = _lookup_binding_source(source, key)
        is_fallback = (
            source.get("binding_role") == "compiled_expression_fallback"
        )
        sources_checked.append(
            {
                "source_type": str(source.get("source_type") or f"binding_source:{index}"),
                "hit": value is not None,
                "binding_role": (
                    "compiled_expression_fallback"
                    if is_fallback
                    else "runtime"
                ),
            }
        )
        if binding.get("ambiguous") is True:
            ambiguous_matches.append(binding)
        if value is not None:
            target = fallback_matches if is_fallback else matches
            target.append((value, binding))
    sources_checked.append({"source_type": "explicit_dynamic_values", "hit": False})
    if ambiguous_matches or len(matches) > 1 or len(fallback_matches) > 1:
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
                "fallback_match_count": len(fallback_matches),
                "fallback_matches": [
                    binding for _, binding in fallback_matches
                ],
                "ambiguous_matches": ambiguous_matches,
            },
            source_trace=source_trace,
            blocked_reason=f"dynamic_hash_binding_ambiguous:{key}",
        )
    if matches:
        value, binding = matches[0]
        if fallback_matches and fallback_matches[0][0] != value:
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="dynamic_hash",
                bindings={
                    "hash": hash_value,
                    "key": key,
                    "sources_checked": sources_checked,
                    "runtime_match": binding,
                    "fallback_match": fallback_matches[0][1],
                    "runtime_value": value,
                    "fallback_value": fallback_matches[0][0],
                },
                source_trace=source_trace,
                blocked_reason=f"dynamic_hash_binding_fallback_conflict:{key}",
            )
        return NumericEvaluationResult(
            ok=True,
            value=value,
            expression_kind="dynamic_hash",
            bindings={
                "hash": hash_value,
                "key": key,
                "value": value,
                **binding,
                **(
                    {"verified_fallback": fallback_matches[0][1]}
                    if fallback_matches
                    else {}
                ),
            },
            source_trace=source_trace,
        )
    if fallback_matches:
        value, binding = fallback_matches[0]
        return NumericEvaluationResult(
            ok=True,
            value=value,
            expression_kind="dynamic_hash",
            bindings={
                "hash": hash_value,
                "key": key,
                "value": value,
                **binding,
                "binding_role": "compiled_expression_fallback",
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
            if not _finite_number(value):
                return _numeric_program_blocked("numeric_program_fixed_operand_invalid", source_trace, index)
            stack.append(float(value))
            continue
        if opcode == "push_dynamic":
            try:
                dynamic_expression = numeric_dynamic_hash(instruction.get("hash"))
            except (TypeError, ValueError):
                return _numeric_program_blocked(
                    "numeric_program_dynamic_hash_invalid",
                    source_trace,
                    index,
                )
            result = _evaluate_dynamic_hash(dynamic_expression, context, source_trace)
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
            if not math.isfinite(stack[-1]):
                return _numeric_program_blocked(
                    "numeric_program_non_finite_result",
                    source_trace,
                    index,
                )
            continue
        if opcode == "max":
            operand_count = instruction.get("operand_count")
            if (
                not isinstance(operand_count, int)
                or isinstance(operand_count, bool)
                or operand_count < 2
            ):
                return _numeric_program_blocked(
                    "numeric_program_variadic_operand_count_invalid",
                    source_trace,
                    index,
                )
            if len(stack) < operand_count:
                return _numeric_program_blocked(
                    "numeric_program_stack_underflow",
                    source_trace,
                    index,
                )
            operands = stack[-operand_count:]
            del stack[-operand_count:]
            stack.append(max(operands))
            continue
        if opcode not in {"add", "sub", "mul", "div"}:
            return _numeric_program_blocked("numeric_program_opcode_not_admitted", source_trace, index)
        if len(stack) < 2:
            return _numeric_program_blocked("numeric_program_stack_underflow", source_trace, index)
        rhs = stack.pop()
        lhs = stack.pop()
        if opcode == "add":
            result = lhs + rhs
        elif opcode == "sub":
            result = lhs - rhs
        elif opcode == "mul":
            result = lhs * rhs
        elif rhs == 0:
            return _numeric_program_blocked("numeric_program_division_by_zero", source_trace, index)
        else:
            result = lhs / rhs
        if not math.isfinite(result):
            return _numeric_program_blocked(
                "numeric_program_non_finite_result",
                source_trace,
                index,
            )
        stack.append(result)
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
    if opcode in COMMITTED_STATE_CONDITION_OPCODES:
        return _evaluate_committed_state_condition(
            evaluator,
            opcode,
            payload,
            context,
            condition_id=condition_id,
            source_trace=source_trace,
        )
    if opcode in CONTEXTUAL_CONDITION_OPCODES:
        return _evaluate_contextual_condition(
            evaluator,
            opcode,
            payload,
            context,
            condition_id=condition_id,
            source_trace=source_trace,
        )
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
        alive_mask = payload.get("AliveStateMask")
        if alive_mask == "Mask_AliveOnly":
            operand = _condition_operand(
                context,
                "unit.lifecycle_mask",
                subject_ids=(target_id,),
                parameters={"mask": alive_mask},
            )
            if operand.status != "resolved" or operand.value_type != "boolean":
                return _condition_operand_blocked(
                    condition_id, opcode, operand, source_trace
                )
            return _condition_result(
                bool(operand.value),
                condition_id,
                opcode,
                "target_alive_state_checked",
                {"operand": operand.to_json()},
                source_trace,
            )
        if alive_mask != "Mask_AliveOrRevivable":
            return _condition_blocked(condition_id, opcode, "alive_state_mask_not_supported", {"mask": payload.get("AliveStateMask")}, source_trace)
        if _unit_is_alive(unit):
            return _condition_result(
                True,
                condition_id,
                opcode,
                "target_alive",
                {"target_id": target_id, "revive_charges": None},
                source_trace,
            )
        resources = getattr(unit, "resources", None)
        revive_charges = (
            resources.get("revive_charges")
            if isinstance(resources, dict)
            else None
        )
        if not _finite_number(revive_charges):
            return _condition_blocked(
                condition_id,
                opcode,
                "revivable_resource_state_missing",
                {"target_id": target_id, "alive": False},
                source_trace,
            )
        return _condition_result(
            float(revive_charges) > 0,
            condition_id,
            opcode,
            "revivable_resource_checked",
            {"target_id": target_id, "revive_charges": float(revive_charges)},
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
        flags = _condition_behavior_flags(payload)
        if not flags:
            return _condition_blocked(condition_id, opcode, "behavior_flag_missing", {"payload": payload}, source_trace)
        matched = any(
            _unit_has_behavior_flag(context, target_id, flag)
            for flag in flags
        )
        if payload.get("Inverse") is True:
            matched = not matched
        return _condition_result(
            matched,
            condition_id,
            opcode,
            "behavior_flag_checked",
            {
                "target_id": target_id,
                "flags": list(flags),
                "match_policy": "any",
                "inverse": payload.get("Inverse") is True,
            },
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
    if opcode == "ByCharacterDamageType":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        unit = _state_unit(context, target_id) if target_id else None
        expected = payload.get("DamageType")
        actual = _unit_damage_type(unit)
        if unit is None or not isinstance(expected, str) or not expected:
            return _condition_blocked(condition_id, opcode, "character_damage_type_identity_missing", target_details, source_trace)
        if actual is None:
            return _condition_blocked(condition_id, opcode, "character_damage_type_source_missing", {"target_id": target_id}, source_trace)
        return _condition_result(actual == expected, condition_id, opcode, "character_damage_type_compared", {"target_id": target_id, "expected": expected, "actual": actual}, source_trace)
    if opcode in {"ByCompareChangeValue", "ByCompareParamValue"}:
        keys = (
            ("change_value", "delta", "value")
            if opcode == "ByCompareChangeValue"
            else ("param_value", "change_value", "delta", "value")
        )
        actual = _first_event_number(event_payload, keys)
        expected = evaluator.evaluate_numeric(
            payload.get("CompareValue"),
            NumericEvaluationContext(
                dynamic_values=context.dynamic_values,
                binding_sources=context.binding_sources,
                source_trace=source_trace,
            ),
        )
        if actual is None:
            return _condition_blocked(condition_id, opcode, "event_change_value_missing", {"keys": list(keys)}, source_trace)
        if not expected.ok or expected.value is None:
            return _condition_blocked(condition_id, opcode, expected.blocked_reason or "compare_value_blocked", {}, source_trace)
        return _comparison_condition(condition_id, opcode, actual, payload.get("CompareType"), expected.value, source_trace)
    if opcode == "ByCompareSPRatio":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        unit = _state_unit(context, target_id) if target_id else None
        if unit is None:
            return _condition_blocked(condition_id, opcode, "sp_ratio_target_missing", target_details, source_trace)
        maximum = getattr(unit, "max_energy", None)
        current = getattr(unit, "energy", None)
        if not _finite_number(maximum) or float(maximum) <= 0 or not _finite_number(current):
            return _condition_blocked(condition_id, opcode, "sp_ratio_resource_missing", {"target_id": target_id}, source_trace)
        expected = evaluator.evaluate_numeric(payload.get("CompareValue"), NumericEvaluationContext(dynamic_values=context.dynamic_values, binding_sources=context.binding_sources, source_trace=source_trace))
        if not expected.ok or expected.value is None:
            return _condition_blocked(condition_id, opcode, expected.blocked_reason or "compare_value_blocked", {}, source_trace)
        return _comparison_condition(condition_id, opcode, float(current) / float(maximum), payload.get("CompareType"), expected.value, source_trace)
    if opcode == "ByCompareWaveCount":
        state = context.state
        if state is None or not isinstance(getattr(state, "wave_index", None), int):
            return _condition_blocked(condition_id, opcode, "wave_count_state_missing", {}, source_trace)
        explicit = getattr(state, "global_flags", {}).get("wave_count")
        actual = float(explicit) if _finite_number(explicit) else float(state.wave_index + 1)
        expected = evaluator.evaluate_numeric(payload.get("CompareValue"), NumericEvaluationContext(dynamic_values=context.dynamic_values, binding_sources=context.binding_sources, source_trace=source_trace))
        if not expected.ok or expected.value is None:
            return _condition_blocked(condition_id, opcode, expected.blocked_reason or "compare_value_blocked", {}, source_trace)
        return _comparison_condition(condition_id, opcode, actual, payload.get("CompareType"), expected.value, source_trace)
    if opcode == "ByHasStanceWeak":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        unit = _state_unit(context, target_id) if target_id else None
        weak_type = payload.get("WeakType")
        expected = weak_type.get("DamageType") if isinstance(weak_type, dict) else None
        if unit is None or not isinstance(expected, str) or not expected:
            return _condition_blocked(condition_id, opcode, "stance_weakness_identity_missing", target_details, source_trace)
        weaknesses = _unit_weaknesses(unit)
        if weaknesses is None:
            return _condition_blocked(condition_id, opcode, "stance_weakness_source_missing", {"target_id": target_id}, source_trace)
        return _condition_result(expected in weaknesses, condition_id, opcode, "stance_weakness_checked", {"target_id": target_id, "expected": expected, "weaknesses": sorted(weaknesses)}, source_trace)
    if opcode == "ByInTurnBasedGameModeState":
        state = context.state
        mode = getattr(state, "global_flags", {}).get("turn_based_game_mode_state") if state is not None else None
        if not isinstance(mode, (bool, str)):
            return _condition_blocked(condition_id, opcode, "turn_based_game_mode_state_missing", {}, source_trace)
        active = mode is True or mode in {"active", "running", "entered"}
        return _condition_result(active, condition_id, opcode, "turn_based_game_mode_state_checked", {"mode": mode}, source_trace)
    if opcode == "ByIsDamageCritical":
        critical = event_payload.get("is_critical")
        if not isinstance(critical, bool):
            return _condition_blocked(condition_id, opcode, "damage_critical_context_missing", {}, source_trace)
        return _condition_result(critical, condition_id, opcode, "damage_critical_checked", {"is_critical": critical}, source_trace)
    if opcode == "ByIsPropertyValueMinOrMax":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        compare_ids, compare_details = _condition_target_ids(payload.get("CompareTargetType"), context)
        if target_id is None or compare_ids is None:
            return _condition_blocked(condition_id, opcode, "property_compare_targets_missing", {**target_details, **compare_details}, source_trace)
        values = _unit_property_ratios(context, compare_ids, payload.get("PropertyRatioType"))
        if values is None or target_id not in values:
            return _condition_blocked(condition_id, opcode, "property_ratio_not_available", {"target_id": target_id}, source_trace)
        minimum = min(values.values())
        matched = abs(values[target_id] - minimum) <= 1e-12
        return _condition_result(matched, condition_id, opcode, "minimum_property_ratio_checked", {"target_id": target_id, "values": values, "minimum": minimum}, source_trace)
    if opcode == "ByIsTargetValid":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        unit = _state_unit(context, target_id) if target_id else None
        if unit is None:
            return _condition_result(False, condition_id, opcode, "target_missing", target_details, source_trace)
        valid = runtime_unit_is_target_candidate(unit)
        return _condition_result(valid, condition_id, opcode, "target_validity_checked", {"target_id": target_id}, source_trace)
    if opcode == "ByIsTopActionDelayTarget":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        compare_ids, compare_details = _condition_target_ids(payload.get("CompareTargetType"), context)
        exclude_ids: tuple[str, ...] = ()
        if payload.get("ExcludeTargetType") is not None:
            resolved_exclude, exclude_details = _condition_target_ids(payload.get("ExcludeTargetType"), context)
            if resolved_exclude is None:
                return _condition_blocked(condition_id, opcode, "action_delay_exclude_targets_missing", exclude_details, source_trace)
            exclude_ids = resolved_exclude
        if target_id is None or compare_ids is None:
            return _condition_blocked(condition_id, opcode, "action_delay_compare_targets_missing", {**target_details, **compare_details}, source_trace)
        candidates = tuple(unit_id for unit_id in compare_ids if unit_id not in set(exclude_ids))
        values = {
            unit_id: float(getattr(_state_unit(context, unit_id), "action_value"))
            for unit_id in candidates
            if _finite_number(getattr(_state_unit(context, unit_id), "action_value", None))
        }
        if target_id not in values or not values:
            return _condition_blocked(condition_id, opcode, "action_delay_value_missing", {"target_id": target_id, "candidates": list(candidates)}, source_trace)
        top = min(values.values())
        return _condition_result(abs(values[target_id] - top) <= 1e-12, condition_id, opcode, "top_action_delay_target_checked", {"target_id": target_id, "values": values, "top": top}, source_trace)
    if opcode == "ByRandomChance":
        selected = event_payload.get("condition_random_result")
        if not isinstance(selected, bool):
            return _condition_blocked(condition_id, opcode, "random_condition_requires_rng_context", {}, source_trace)
        return _condition_result(
            selected,
            condition_id,
            opcode,
            "random_condition_result_consumed",
            {
                "choice_key": event_payload.get("condition_random_choice_key"),
                "selected": selected,
            },
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
        target_ids, target_details = _condition_target_ids(
            payload.get("TargetType"),
            context,
        )
        if target_ids is None:
            return _condition_blocked(
                condition_id,
                opcode,
                "target_group_not_resolved",
                target_details,
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
            float(len(target_ids)),
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
        if payload.get("TargetType") is None:
            target_id = context.owner_id or context.actor_id
            target_details = {
                "alias": "ModifierOwnerEntity",
                "source": "tbgd_condition_default",
            }
        else:
            target_id, target_details = _resolve_condition_target(
                payload.get("TargetType"),
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
        left_ids, left_details = _condition_target_ids(payload.get("TargetType"), context)
        right_ids, right_details = _condition_target_ids(payload.get("CompareType"), context)
        if left_ids is None or right_ids is None:
            return _condition_blocked(
                condition_id,
                opcode,
                "target_alias_unresolved",
                {"left": left_details, "right": right_details},
                source_trace,
            )
        if len(left_ids) > 1 or len(right_ids) > 1:
            return _condition_blocked(
                condition_id,
                opcode,
                "target_identity_requires_singleton",
                {"left_target_ids": list(left_ids), "right_target_ids": list(right_ids)},
                source_trace,
            )
        if not left_ids or not right_ids:
            return _condition_result(
                False,
                condition_id,
                opcode,
                "target_identity_empty_operand",
                {
                    "left_target_ids": list(left_ids),
                    "right_target_ids": list(right_ids),
                },
                source_trace,
            )
        left_id = left_ids[0]
        right_id = right_ids[0]
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
    if opcode == "ByCompareDamageTag":
        expected = _condition_damage_tags(payload.get("DamageTagList"))
        if expected is None:
            return _condition_blocked(
                condition_id,
                opcode,
                "damage_tag_list_not_lowered",
                {"payload": payload},
                source_trace,
            )
        event_payload = context.event_payload or {}
        has_tag_payload = any(
            key in event_payload
            for key in (
                "damage_tags",
                "damage_tag",
            )
        )
        if not has_tag_payload:
            return _condition_blocked(
                condition_id,
                opcode,
                "damage_tag_event_payload_missing",
                {},
                source_trace,
            )
        actual = _event_damage_tags(event_payload)
        matched = bool(set(expected) & set(actual))
        return _condition_result(
            matched,
            condition_id,
            opcode,
            "damage_tag_compared",
            {
                "expected": list(expected),
                "actual": list(actual),
                "match_policy": "any",
            },
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
        child_results: list[ConditionEvaluationResult] = []
        blocked: ConditionEvaluationResult | None = None
        for item in predicates:
            child = _evaluate_typed_condition_node(
                evaluator,
                item,
                context,
                condition_id=condition_id,
                source_trace=source_trace,
            )
            child_results.append(child)
            if opcode == "ByAnd" and child.ok and child.result is False:
                return _condition_result(False, condition_id, opcode, "and_child_false", {"children": [value.to_json() for value in child_results]}, source_trace)
            if opcode == "ByAny" and child.ok and child.result is True:
                return _condition_result(True, condition_id, opcode, "any_child_true", {"children": [value.to_json() for value in child_results]}, source_trace)
            if not child.ok and blocked is None:
                blocked = child
        if blocked is not None:
            return _condition_blocked(condition_id, opcode, f"child_blocked:{blocked.reason}", {"children": [value.to_json() for value in child_results]}, source_trace)
        return _condition_result(
            opcode == "ByAnd",
            condition_id,
            opcode,
            "and_all_true" if opcode == "ByAnd" else "any_all_false",
            {"children": [value.to_json() for value in child_results]},
            source_trace,
        )
    if opcode == "ByNot":
        predicate = payload.get("Predicate")
        if not isinstance(predicate, dict):
            return _condition_blocked(condition_id, opcode, "predicate_missing", {"payload": payload}, source_trace)
        child = _evaluate_typed_condition_node(evaluator, predicate, context, condition_id=condition_id, source_trace=source_trace)
        if not child.ok or child.result is None:
            return _condition_blocked(condition_id, opcode, f"child_blocked:{child.reason}", {"child": child.to_json()}, source_trace)
        return _condition_result(not child.result, condition_id, opcode, "not_child_inverted", {"child": child.to_json()}, source_trace)
    return _condition_blocked(condition_id, opcode, f"condition_opcode_not_supported:{opcode}", {"payload": payload}, source_trace)


_COMMITTED_NUMERIC_FACTS = {
    "ByCompareBP": ("battle.skill_points", "", "CompareValue"),
    "ByCompareBattleEventID": (
        "unit.battle_event_id",
        "TargetType",
        "TargetBattleEventID",
    ),
    "ByCompareHP": ("unit.hp", "TargetType", "CompareValue"),
    "ByCompareMonsterRank": (
        "unit.monster_rank",
        "TargetType",
        "CompareValue",
    ),
    "ByCompareSpecialSPRatio": (
        "unit.special_resource_ratio",
        "TargetType",
        "CompareValue",
    ),
    "ByCompareStance": (
        "unit.stance_current",
        "TargetType",
        "CompareValue",
    ),
    "ByCompareStanceCount": (
        "unit.stance_segment_count",
        "TargetType",
        "CompareValue",
    ),
    "ByCompareStanceRatio": (
        "unit.stance_ratio",
        "TargetType",
        "CompareValue",
    ),
}

_COMMITTED_BOOLEAN_FACTS = {
    "ByContainsRedStance": ("unit.red_stance", "TargetType"),
    "ByIsBattleEventEntity": ("unit.is_battle_event_entity", "TargetType"),
    "ByIsBodyPart": ("relation.body_part", "TargetType"),
    "ByIsSubTargetOfHpSharedGroup": (
        "relation.hp_shared_group",
        "TargetType",
    ),
}

_COMMITTED_SPECIAL_OPCODES = {
    "ByAvatarBaseType",
    "ByCasterAliveOrLimbo",
    "ByCompareResistChance",
    "ByHasSummonRelation",
    "ByIsEnemy",
    "ByIsTargetUnselectable",
    "ByTargetIsStanceWeak",
    "ByTargetListAll",
    "ByTargetListAny",
}

if (
    set(_COMMITTED_NUMERIC_FACTS)
    | set(_COMMITTED_BOOLEAN_FACTS)
    | _COMMITTED_SPECIAL_OPCODES
) != set(COMMITTED_STATE_CONDITION_OPCODES):
    raise RuntimeError("committed condition evaluator registry is incomplete")


def _evaluate_committed_state_condition(
    evaluator: RuleEvaluator,
    opcode: str,
    payload: dict[str, Any],
    context: EvaluationContext,
    *,
    condition_id: str,
    source_trace: dict[str, Any],
) -> ConditionEvaluationResult:
    numeric_fact = _COMMITTED_NUMERIC_FACTS.get(opcode)
    if numeric_fact is not None:
        fact_kind, target_field, value_field = numeric_fact
        subject_ids: tuple[str, ...] = ()
        if target_field:
            target_id, target_details = _condition_single_target(
                payload.get(target_field), context
            )
            if target_id is None:
                return _condition_blocked(
                    condition_id,
                    opcode,
                    "condition_fact_target_requires_singleton",
                    target_details,
                    source_trace,
                )
            subject_ids = (target_id,)
        parameters: dict[str, Any] = {}
        if opcode == "ByCompareStanceRatio":
            parameters["include_red_stance"] = payload.get("IncludeRedStance", False)
        operand = _condition_operand(
            context, fact_kind, subject_ids=subject_ids, parameters=parameters
        )
        if operand.status != "resolved" or operand.value_type != "number":
            return _condition_operand_blocked(
                condition_id, opcode, operand, source_trace
            )
        expected = evaluator.evaluate_numeric(
            payload.get(value_field),
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
                expected.blocked_reason or "compare_value_blocked",
                {"numeric_evaluation": expected.to_json()},
                source_trace,
            )
        return _comparison_condition(
            condition_id,
            opcode,
            float(operand.value),
            payload.get("CompareType") or "Equal",
            expected.value,
            source_trace,
        )
    if opcode == "ByCompareResistChance":
        target_id, target_details = _condition_single_target(
            payload.get("TargetType"), context
        )
        if target_id is None:
            return _condition_blocked(
                condition_id,
                opcode,
                "condition_fact_target_requires_singleton",
                target_details,
                source_trace,
            )
        operand = _condition_operand(
            context,
            "unit.status_resist_chance",
            subject_ids=(target_id,),
            parameters={"behavior_flags": payload.get("BehaviorFlagList")},
        )
        if operand.status != "resolved" or operand.value_type != "number":
            return _condition_operand_blocked(
                condition_id, opcode, operand, source_trace
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
            return _condition_blocked(
                condition_id,
                opcode,
                expected.blocked_reason or "compare_value_blocked",
                {"numeric_evaluation": expected.to_json()},
                source_trace,
            )
        return _comparison_condition(
            condition_id,
            opcode,
            float(operand.value),
            payload.get("CompareType"),
            expected.value,
            source_trace,
        )
    if opcode == "ByAvatarBaseType":
        target_id, target_details = _condition_single_target(
            payload.get("TargetType"), context
        )
        base_types = payload.get("BaseTypeList")
        if target_id is None:
            return _condition_blocked(
                condition_id,
                opcode,
                "condition_fact_target_requires_singleton",
                target_details,
                source_trace,
            )
        if not isinstance(base_types, list) or not base_types:
            return _condition_blocked(
                condition_id, opcode, "avatar_base_type_list_invalid", {}, source_trace
            )
        operand = _condition_operand(
            context, "unit.avatar_base_type", subject_ids=(target_id,)
        )
        if operand.status != "resolved" or operand.value_type != "string":
            return _condition_operand_blocked(
                condition_id, opcode, operand, source_trace
            )
        return _condition_result(
            operand.value in base_types,
            condition_id,
            opcode,
            "avatar_base_type_compared",
            {"operand": operand.to_json(), "expected": base_types},
            source_trace,
        )
    if opcode == "ByCasterAliveOrLimbo":
        if not isinstance(context.actor_id, str) or not context.actor_id:
            return _condition_blocked(
                condition_id, opcode, "condition_caster_identity_missing", {}, source_trace
            )
        operand = _condition_operand(
            context,
            "unit.lifecycle_mask",
            subject_ids=(context.actor_id,),
            parameters={"mask": payload.get("AliveStateMask")},
        )
        if operand.status != "resolved" or operand.value_type != "boolean":
            return _condition_operand_blocked(
                condition_id, opcode, operand, source_trace
            )
        return _condition_result(
            bool(operand.value),
            condition_id,
            opcode,
            "caster_lifecycle_checked",
            {"operand": operand.to_json()},
            source_trace,
        )
    if opcode == "ByHasSummonRelation":
        servant_id, servant_details = _condition_single_target(
            payload.get("ServantType"), context
        )
        summoner_id, summoner_details = _condition_single_target(
            payload.get("SummonerType"), context
        )
        if servant_id is None or summoner_id is None:
            return _condition_blocked(
                condition_id,
                opcode,
                "summon_relation_requires_singleton_targets",
                {"servant": servant_details, "summoner": summoner_details},
                source_trace,
            )
        operand = _condition_operand(
            context, "relation.summoner", subject_ids=(servant_id,)
        )
        if operand.status != "resolved" or operand.value_type != "identity_set":
            return _condition_operand_blocked(
                condition_id, opcode, operand, source_trace
            )
        return _condition_result(
            summoner_id in tuple(operand.value),
            condition_id,
            opcode,
            "summon_relation_checked",
            {"operand": operand.to_json(), "summoner_id": summoner_id},
            source_trace,
        )
    if opcode == "ByIsEnemy":
        left_id, left_details = _condition_single_target(
            payload.get("TargetTypeA"), context
        )
        right_id, right_details = _condition_single_target(
            payload.get("TargetTypeB"), context
        )
        if left_id is None or right_id is None:
            return _condition_blocked(
                condition_id,
                opcode,
                "enemy_relation_requires_singleton_targets",
                {"left": left_details, "right": right_details},
                source_trace,
            )
        operand = _condition_operand(
            context, "relation.opposing", subject_ids=(left_id, right_id)
        )
        if operand.status != "resolved" or operand.value_type != "boolean":
            return _condition_operand_blocked(
                condition_id, opcode, operand, source_trace
            )
        return _condition_result(
            bool(operand.value),
            condition_id,
            opcode,
            "enemy_relation_checked",
            {"operand": operand.to_json(), "left_id": left_id, "right_id": right_id},
            source_trace,
        )
    if opcode == "ByIsTargetUnselectable":
        target_ids, target_details = _condition_target_ids(
            payload.get("TargetType"), context
        )
        if target_ids is None:
            return _condition_blocked(
                condition_id,
                opcode,
                "target_collection_unresolved",
                target_details,
                source_trace,
            )
        source_id = ""
        if payload.get("SourceEntity") is not None:
            source_id, source_details = _condition_single_target(
                payload.get("SourceEntity"), context
            )
            if source_id is None:
                return _condition_blocked(
                    condition_id,
                    opcode,
                    "targetability_source_requires_singleton",
                    source_details,
                    source_trace,
                )
        operands = tuple(
            _condition_operand(
                context,
                "unit.target_unselectable",
                subject_ids=(target_id,),
                parameters={"source_id": source_id},
            )
            for target_id in target_ids
        )
        blocked = next(
            (
                operand
                for operand in operands
                if operand.status != "resolved" or operand.value_type != "boolean"
            ),
            None,
        )
        if blocked is not None:
            return _condition_operand_blocked(
                condition_id, opcode, blocked, source_trace
            )
        return _condition_result(
            any(bool(operand.value) for operand in operands),
            condition_id,
            opcode,
            "target_unselectable_checked",
            {"operands": [operand.to_json() for operand in operands]},
            source_trace,
        )
    if opcode in {"ByTargetListAll", "ByTargetListAny"}:
        return _evaluate_committed_quantifier(
            evaluator,
            opcode,
            payload,
            context,
            condition_id=condition_id,
            source_trace=source_trace,
        )
    boolean_fact = _COMMITTED_BOOLEAN_FACTS.get(opcode)
    if boolean_fact is not None:
        fact_kind, target_field = boolean_fact
        target_id, target_details = _condition_single_target(
            payload.get(target_field), context
        )
        if target_id is None:
            return _condition_blocked(
                condition_id,
                opcode,
                "condition_fact_target_requires_singleton",
                target_details,
                source_trace,
            )
        parameters: dict[str, Any] = {}
        if opcode == "ByIsBattleEventEntity":
            parameters["expect_sub_type"] = payload.get("ExpectSubType") or ""
        operand = _condition_operand(
            context, fact_kind, subject_ids=(target_id,), parameters=parameters
        )
        if operand.status != "resolved" or operand.value_type != "boolean":
            return _condition_operand_blocked(
                condition_id, opcode, operand, source_trace
            )
        return _condition_result(
            bool(operand.value),
            condition_id,
            opcode,
            "committed_boolean_fact_checked",
            {"operand": operand.to_json()},
            source_trace,
        )
    if opcode == "ByTargetIsStanceWeak":
        target_id, target_details = _condition_single_target(
            payload.get("TargetType"), context
        )
        attacker_id, attacker_details = _condition_single_target(
            payload.get("AttackerType"), context
        )
        if target_id is None or attacker_id is None:
            return _condition_blocked(
                condition_id,
                opcode,
                "stance_weak_requires_singleton_targets",
                {"target": target_details, "attacker": attacker_details},
                source_trace,
            )
        operand = _condition_operand(
            context,
            "unit.stance_weak",
            subject_ids=(target_id, attacker_id),
        )
        if operand.status != "resolved" or operand.value_type != "boolean":
            return _condition_operand_blocked(
                condition_id, opcode, operand, source_trace
            )
        return _condition_result(
            bool(operand.value),
            condition_id,
            opcode,
            "stance_weak_checked",
            {"operand": operand.to_json()},
            source_trace,
        )
    return _condition_blocked(
        condition_id,
        opcode,
        f"committed_condition_handler_missing:{opcode}",
        {},
        source_trace,
    )


def _evaluate_committed_quantifier(
    evaluator: RuleEvaluator,
    opcode: str,
    payload: dict[str, Any],
    context: EvaluationContext,
    *,
    condition_id: str,
    source_trace: dict[str, Any],
) -> ConditionEvaluationResult:
    target_ids, target_details = _condition_target_ids(
        payload.get("TargetType"), context
    )
    predicate = payload.get("Predicate")
    if target_ids is None:
        return _condition_blocked(
            condition_id,
            opcode,
            "quantifier_collection_unresolved",
            target_details,
            source_trace,
        )
    if not isinstance(predicate, dict):
        return _condition_blocked(
            condition_id, opcode, "quantifier_predicate_missing", {}, source_trace
        )
    children: list[ConditionEvaluationResult] = []
    blocked: ConditionEvaluationResult | None = None
    for target_id in target_ids:
        child = _evaluate_typed_condition_node(
            evaluator,
            predicate,
            replace(
                context,
                target_id=target_id,
                param_entity_id=target_id,
                resolved_target_groups={},
                target_resolution_errors={},
            ),
            condition_id=condition_id,
            source_trace=source_trace,
        )
        children.append(child)
        if opcode == "ByTargetListAny" and child.ok and child.result is True:
            return _condition_result(
                True,
                condition_id,
                opcode,
                "quantifier_any_true",
                {"target_ids": list(target_ids), "children": [item.to_json() for item in children]},
                source_trace,
            )
        if opcode == "ByTargetListAll" and child.ok and child.result is False:
            return _condition_result(
                False,
                condition_id,
                opcode,
                "quantifier_all_false",
                {"target_ids": list(target_ids), "children": [item.to_json() for item in children]},
                source_trace,
            )
        if not child.ok and blocked is None:
            blocked = child
    if blocked is not None:
        return _condition_blocked(
            condition_id,
            opcode,
            f"quantifier_child_blocked:{blocked.reason}",
            {"target_ids": list(target_ids), "children": [item.to_json() for item in children]},
            source_trace,
        )
    result = opcode == "ByTargetListAll"
    return _condition_result(
        result,
        condition_id,
        opcode,
        "quantifier_empty_or_complete",
        {"target_ids": list(target_ids), "children": [item.to_json() for item in children]},
        source_trace,
    )


def _evaluate_contextual_condition(
    evaluator: RuleEvaluator,
    opcode: str,
    payload: dict[str, Any],
    context: EvaluationContext,
    *,
    condition_id: str,
    source_trace: dict[str, Any],
) -> ConditionEvaluationResult:
    if opcode == "ByCheckModifierCallBackModifierValue":
        operand = _transient_operand(
            context,
            "status_callback.modifier_value",
            parameters={"value_type": payload.get("ValueType")},
        )
        return _contextual_numeric_comparison(
            evaluator, condition_id, opcode, payload, context, operand, source_trace
        )
    if opcode == "ByCompareNextUnusedInsertAction":
        parameters: dict[str, Any] = {}
        if "ActionTypeIs" in payload:
            caster_ids, details = _condition_target_ids(payload.get("CasterIs"), context)
            if caster_ids is None:
                return _condition_blocked(
                    condition_id, opcode, "insert_action_caster_unresolved", details, source_trace
                )
            parameters = {
                "action_type": payload.get("ActionTypeIs"),
                "caster_ids": list(caster_ids),
            }
        else:
            parameters = {"custom_tag": payload.get("CustomTagIs")}
        return _contextual_boolean_result(
            condition_id,
            opcode,
            _transient_operand(
                context,
                "queue.next_unused_insert_action_matches",
                parameters=parameters,
            ),
            "next_unused_insert_action_checked",
            source_trace,
        )
    if opcode == "ByCompareParamString":
        operand = _transient_operand(context, "event.param_string")
        expected = payload.get("CompareValue")
        if operand.status != "resolved" or operand.value_type != "string":
            return _transient_operand_blocked(condition_id, opcode, operand, source_trace)
        return _condition_result(
            operand.value == expected,
            condition_id,
            opcode,
            "event_param_string_compared",
            {"operand": operand.to_json(), "expected": expected},
            source_trace,
        )
    if opcode == "ByCompareSPChangeTag":
        operand = _transient_operand(context, "resource_change.tags")
        expected = payload.get("TagList")
        if operand.status != "resolved" or operand.value_type != "identity_set":
            return _transient_operand_blocked(condition_id, opcode, operand, source_trace)
        if not isinstance(expected, list):
            return _condition_blocked(
                condition_id, opcode, "resource_change_tag_list_invalid", {}, source_trace
            )
        actual_tags = tuple(operand.value)
        return _condition_result(
            all(tag in actual_tags for tag in expected),
            condition_id,
            opcode,
            "resource_change_tags_checked",
            {"operand": operand.to_json(), "expected": expected},
            source_trace,
        )
    if opcode == "ByCompareTurnActionEntityTeamType":
        return _contextual_string_comparison(
            condition_id,
            opcode,
            _transient_operand(context, "turn.action_entity.team"),
            payload.get("Team"),
            "turn_action_entity_team_compared",
            source_trace,
        )
    if opcode in {
        "ByCompareUnusedInsertAbilityCount",
        "ByCompareUnusedUltraSkillCount",
    }:
        fact_kind = (
            "queue.unused_insert_ability_count"
            if opcode == "ByCompareUnusedInsertAbilityCount"
            else "queue.unused_ultimate_count"
        )
        parameters: dict[str, Any] = {}
        if opcode == "ByCompareUnusedUltraSkillCount":
            parameters["include_insert_action"] = payload.get(
                "IncludeInsertAction", False
            )
            if payload.get("SkillOwnerType") is not None:
                owner_ids, details = _condition_target_ids(
                    payload.get("SkillOwnerType"), context
                )
                if owner_ids is None:
                    return _condition_blocked(
                        condition_id,
                        opcode,
                        "unused_ultimate_owner_unresolved",
                        details,
                        source_trace,
                    )
                parameters["skill_owner_ids"] = list(owner_ids)
        return _contextual_numeric_comparison(
            evaluator,
            condition_id,
            opcode,
            payload,
            context,
            _transient_operand(context, fact_kind, parameters=parameters),
            source_trace,
        )
    if opcode == "ByCurrentSkillTargetType":
        fact_kind = (
            "action.dynamic_target" if "IsDynamic" in payload else "action.target_type"
        )
        operand = _transient_operand(context, fact_kind)
        if fact_kind == "action.dynamic_target":
            if operand.status != "resolved" or operand.value_type != "boolean":
                return _transient_operand_blocked(condition_id, opcode, operand, source_trace)
            matched = operand.value is payload.get("IsDynamic")
        else:
            if operand.status != "resolved" or operand.value_type != "string":
                return _transient_operand_blocked(condition_id, opcode, operand, source_trace)
            matched = operand.value == payload.get("TargetType")
        return _condition_result(
            matched,
            condition_id,
            opcode,
            "current_skill_target_contract_checked",
            {"operand": operand.to_json()},
            source_trace,
        )
    if opcode == "ByDamageSourceContainBehaviorFlag":
        operand = _transient_operand(context, "damage.source_behavior_flags")
        expected = payload.get("BehaviorFlags")
        if operand.status != "resolved" or operand.value_type != "identity_set":
            return _transient_operand_blocked(condition_id, opcode, operand, source_trace)
        if not isinstance(expected, list):
            return _condition_blocked(
                condition_id, opcode, "damage_behavior_flags_invalid", {}, source_trace
            )
        actual_flags = tuple(operand.value)
        return _condition_result(
            all(flag in actual_flags for flag in expected),
            condition_id,
            opcode,
            "damage_source_behavior_flags_checked",
            {"operand": operand.to_json(), "expected": expected},
            source_trace,
        )
    if opcode == "ByHasInsertActionByTarget":
        target_ids, details = _condition_target_ids(payload.get("TargetType"), context)
        if target_ids is None:
            return _condition_blocked(
                condition_id, opcode, "insert_action_targets_unresolved", details, source_trace
            )
        return _contextual_boolean_result(
            condition_id,
            opcode,
            _transient_operand(
                context,
                "queue.has_insert_action_by_target",
                subject_ids=target_ids,
            ),
            "insert_action_targets_checked",
            source_trace,
        )
    if opcode == "ByIsDamageType":
        target_id, details = _condition_single_target(payload.get("TargetType"), context)
        if target_id is None:
            return _condition_blocked(
                condition_id, opcode, "damage_type_target_requires_singleton", details, source_trace
            )
        operand = _transient_operand(
            context, "damage.type", subject_ids=(target_id,)
        )
        expected = payload.get("DamageTypeList")
        if operand.status != "resolved" or operand.value_type != "string":
            return _transient_operand_blocked(condition_id, opcode, operand, source_trace)
        return _condition_result(
            isinstance(expected, list) and operand.value in expected,
            condition_id,
            opcode,
            "damage_type_checked",
            {"operand": operand.to_json(), "expected": expected},
            source_trace,
        )
    if opcode == "ByIsInCharmAction":
        return _contextual_boolean_result(
            condition_id,
            opcode,
            _transient_operand(context, "action.charm_phase"),
            "charm_action_checked",
            source_trace,
        )
    if opcode == "ByIsSplitDamage":
        target_id, details = _condition_single_target(payload.get("TargetType"), context)
        if target_id is None:
            return _condition_blocked(
                condition_id, opcode, "split_damage_target_requires_singleton", details, source_trace
            )
        return _contextual_boolean_result(
            condition_id,
            opcode,
            _transient_operand(
                context, "damage.is_split", subject_ids=(target_id,)
            ),
            "split_damage_checked",
            source_trace,
        )
    if opcode == "ByIsTurnActionEntity":
        target_ids, details = _condition_target_ids(payload.get("TargetType"), context)
        if target_ids is None:
            return _condition_blocked(
                condition_id, opcode, "turn_action_targets_unresolved", details, source_trace
            )
        operand = _transient_operand(context, "turn.action_entity.identity")
        if operand.status != "resolved" or operand.value_type != "string":
            return _transient_operand_blocked(condition_id, opcode, operand, source_trace)
        return _condition_result(
            operand.value in target_ids,
            condition_id,
            opcode,
            "turn_action_entity_checked",
            {"operand": operand.to_json(), "target_ids": list(target_ids)},
            source_trace,
        )
    boolean_facts = {
        "ByTurnOwnerActionPhaseEnd": "turn.owner.action_phase_end",
        "ByTurnOwnerHasActionInTurn": "turn.owner.has_action",
        "ByTurnOwnerHasPendingOneMore": "turn.owner.pending_one_more",
    }
    if opcode in boolean_facts:
        return _contextual_boolean_result(
            condition_id,
            opcode,
            _transient_operand(context, boolean_facts[opcode]),
            "turn_owner_fact_checked",
            source_trace,
        )
    return _condition_blocked(
        condition_id,
        opcode,
        f"contextual_condition_handler_missing:{opcode}",
        {},
        source_trace,
    )


def _contextual_numeric_comparison(
    evaluator: RuleEvaluator,
    condition_id: str,
    opcode: str,
    payload: dict[str, Any],
    context: EvaluationContext,
    operand: TransientConditionOperandResolution,
    source_trace: dict[str, Any],
) -> ConditionEvaluationResult:
    if operand.status != "resolved" or operand.value_type != "number":
        return _transient_operand_blocked(condition_id, opcode, operand, source_trace)
    expected = evaluator.evaluate_numeric(
        payload.get("CompareValue"),
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
            expected.blocked_reason or "compare_value_blocked",
            {"numeric_evaluation": expected.to_json()},
            source_trace,
        )
    return _comparison_condition(
        condition_id,
        opcode,
        float(operand.value),
        payload.get("CompareType"),
        expected.value,
        source_trace,
    )


def _contextual_boolean_result(
    condition_id: str,
    opcode: str,
    operand: TransientConditionOperandResolution,
    reason: str,
    source_trace: dict[str, Any],
) -> ConditionEvaluationResult:
    if operand.status != "resolved" or operand.value_type != "boolean":
        return _transient_operand_blocked(condition_id, opcode, operand, source_trace)
    return _condition_result(
        bool(operand.value),
        condition_id,
        opcode,
        reason,
        {"operand": operand.to_json()},
        source_trace,
    )


def _contextual_string_comparison(
    condition_id: str,
    opcode: str,
    operand: TransientConditionOperandResolution,
    expected: object,
    reason: str,
    source_trace: dict[str, Any],
) -> ConditionEvaluationResult:
    if operand.status != "resolved" or operand.value_type != "string":
        return _transient_operand_blocked(condition_id, opcode, operand, source_trace)
    return _condition_result(
        operand.value == expected,
        condition_id,
        opcode,
        reason,
        {"operand": operand.to_json(), "expected": expected},
        source_trace,
    )


def _transient_operand(
    context: EvaluationContext,
    fact_kind: str,
    *,
    subject_ids: tuple[str, ...] = (),
    parameters: dict[str, Any] | None = None,
) -> TransientConditionOperandResolution:
    invocation_id = context.transient_invocation_id
    if not isinstance(invocation_id, str) or not invocation_id:
        return TransientConditionOperandResolution.blocked(
            "transient_condition_invocation_missing",
            fact_kind=fact_kind,
            invocation_id="unbound",
        )
    window = context.transient_window
    if not isinstance(window, str) or not window:
        return TransientConditionOperandResolution.blocked(
            "transient_condition_window_missing",
            fact_kind=fact_kind,
            invocation_id=invocation_id,
        )
    provider = context.transient_condition_provider
    if provider is None:
        return TransientConditionOperandResolution.blocked(
            "transient_condition_provider_missing",
            fact_kind=fact_kind,
            invocation_id=invocation_id,
        )
    resolver = getattr(provider, "resolve_transient", None)
    if not callable(resolver):
        return TransientConditionOperandResolution.blocked(
            "transient_condition_provider_contract_rejected",
            fact_kind=fact_kind,
            invocation_id=invocation_id,
        )
    try:
        request = TransientConditionOperandRequest(
            fact_kind=fact_kind,
            invocation_id=invocation_id,
            window=window,
            subject_ids=subject_ids,
            parameters=parameters,
        )
        result = resolver(request)
    except (AttributeError, KeyError, TypeError, ValueError):
        return TransientConditionOperandResolution.blocked(
            "transient_condition_provider_contract_rejected",
            fact_kind=fact_kind,
            invocation_id=invocation_id,
        )
    if type(result) is not TransientConditionOperandResolution:
        return TransientConditionOperandResolution.blocked(
            "transient_condition_provider_result_invalid",
            fact_kind=fact_kind,
            invocation_id=invocation_id,
        )
    if (
        result.fact_kind != fact_kind
        or result.invocation_id != invocation_id
        or (result.status == "resolved" and result.window != window)
    ):
        return TransientConditionOperandResolution.blocked(
            "transient_condition_provider_identity_mismatch",
            fact_kind=fact_kind,
            invocation_id=invocation_id,
        )
    return result


def _transient_operand_blocked(
    condition_id: str,
    opcode: str,
    operand: TransientConditionOperandResolution,
    source_trace: dict[str, Any],
) -> ConditionEvaluationResult:
    reason = (
        operand.blocked_reason
        if operand.status == "blocked"
        else "transient_condition_operand_type_mismatch"
    )
    return _condition_blocked(
        condition_id,
        opcode,
        reason,
        {"operand": operand.to_json()},
        source_trace,
    )


def _condition_single_target(
    value: object,
    context: EvaluationContext,
) -> tuple[str | None, dict[str, Any]]:
    target_ids, details = _condition_target_ids(value, context)
    if target_ids is None:
        return None, details
    if len(target_ids) != 1:
        return None, {**details, "target_ids": list(target_ids)}
    return target_ids[0], details


def _condition_operand(
    context: EvaluationContext,
    fact_kind: str,
    *,
    subject_ids: tuple[str, ...] = (),
    parameters: dict[str, Any] | None = None,
) -> ConditionOperandResolution:
    provider = context.committed_condition_provider
    if provider is None or context.state is None:
        return ConditionOperandResolution.blocked(
            "committed_condition_provider_missing",
            fact_kind=fact_kind,
            authority="committed_condition_provider",
        )
    try:
        request = ConditionOperandRequest(
            fact_kind=fact_kind,
            subject_ids=subject_ids,
            parameters=parameters,
        )
        result = provider.resolve(context.state, request)
    except (TypeError, ValueError):
        return ConditionOperandResolution.blocked(
            "committed_condition_provider_contract_rejected",
            fact_kind=fact_kind,
            authority="committed_condition_provider",
        )
    if type(result) is not ConditionOperandResolution:
        return ConditionOperandResolution.blocked(
            "committed_condition_provider_result_invalid",
            fact_kind=fact_kind,
            authority="committed_condition_provider",
        )
    if result.fact_kind != request.fact_kind:
        return ConditionOperandResolution.blocked(
            "committed_condition_provider_fact_mismatch",
            fact_kind=fact_kind,
            authority="committed_condition_provider",
        )
    return result


def _condition_operand_blocked(
    condition_id: str,
    opcode: str,
    operand: ConditionOperandResolution,
    source_trace: dict[str, Any],
) -> ConditionEvaluationResult:
    reason = (
        operand.blocked_reason
        if operand.status == "blocked"
        else "condition_operand_type_mismatch"
    )
    return _condition_blocked(
        condition_id,
        opcode,
        reason,
        {"operand": operand.to_json()},
        source_trace,
    )


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
    target_key = _condition_target_key(alias_value)
    errors = context.target_resolution_errors or {}
    if target_key in errors:
        return None, {
            "target_key": target_key,
            "reason": errors[target_key],
            "source": "pre_resolved_target_expression",
        }
    groups = context.resolved_target_groups or {}
    if target_key in groups:
        return groups[target_key], {
            "target_key": target_key,
            "source": "pre_resolved_target_expression",
        }
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
        "ParamEntitySkillSubTargetEntityList": (
            "param_entity_skill_sub_target_ids",
            "skill_sub_target_ids",
            "sub_target_ids",
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
        "AllLightTeamWithUnselectable",
        "AllLightTeamWithAllLightTeamUnselectable",
        "AllLightTeamWithAllUnselectableLightTeam",
        "AllTeamMember",
        "AllTeamMemberWithUnselectable",
        "AllTeammate",
        "AllTeammateWithUnselectable",
        "AllUnselectable",
    }:
        result: list[str] = []
        include_unselectable = alias in {
            "AllEnemyWithUnSelectable",
            "AllLightTeamWithUnselectable",
            "AllLightTeamWithAllLightTeamUnselectable",
            "AllLightTeamWithAllUnselectableLightTeam",
            "AllTeamMemberWithUnselectable",
            "AllTeammateWithUnselectable",
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
            elif alias in {
                "AllLightTeam",
                "AllLightTeamWithUnselectable",
                "AllLightTeamWithAllLightTeamUnselectable",
                "AllLightTeamWithAllUnselectableLightTeam",
            } and runtime_unit_is_light_team(unit):
                result.append(unit_id)
            elif (
                alias in {"AllEnemy", "AllEnemyWithUnSelectable"}
                and owner is not None
                and runtime_units_are_opposing_combat_teams(owner, unit)
            ):
                result.append(unit_id)
            elif (
                alias in {"AllTeamMember", "AllTeamMemberWithUnselectable"}
                and owner is not None
                and runtime_units_share_combat_team(owner, unit)
            ):
                result.append(unit_id)
            elif (
                alias in {"AllTeammate", "AllTeammateWithUnselectable"}
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


def _condition_target_key(value: object) -> str:
    if isinstance(value, TargetExpressionNodeIR):
        return "node:" + json.dumps(
            value.to_json(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    alias = _target_alias(value)
    return f"alias:{alias}" if alias else "target:missing"


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


def _finite_number(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def _first_event_number(
    payload: dict[str, Any],
    keys: tuple[str, ...],
) -> float | None:
    for key in keys:
        value = payload.get(key)
        if _finite_number(value):
            return float(value)
    return None


def _unit_damage_type(unit: Any | None) -> str | None:
    flags = getattr(unit, "flags", None)
    if not isinstance(flags, dict):
        return None
    for key in ("damage_type", "element", "DamageType"):
        value = flags.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _unit_weaknesses(unit: Any | None) -> set[str] | None:
    if unit is None:
        return None
    flags = getattr(unit, "flags", None)
    if not isinstance(flags, dict):
        return None
    values = flags.get("weaknesses")
    if not isinstance(values, (list, tuple, set)):
        return None
    return {str(item) for item in values if isinstance(item, str) and item}


def _unit_property_ratios(
    context: EvaluationContext,
    unit_ids: tuple[str, ...],
    property_ratio_type: object,
) -> dict[str, float] | None:
    if property_ratio_type != "HPRatio":
        return None
    values: dict[str, float] = {}
    for unit_id in unit_ids:
        unit = _state_unit(context, unit_id)
        hp = getattr(unit, "hp", None)
        maximum = getattr(unit, "max_hp", None)
        if not _finite_number(hp) or not _finite_number(maximum) or float(maximum) <= 0:
            return None
        values[unit_id] = float(hp) / float(maximum)
    return values
    return None


def _unit_ability_property(unit: Any | None, property_name: object) -> float | None:
    if unit is None or not isinstance(property_name, str):
        return None
    from ..systems.unit_stats import ability_property_value

    return ability_property_value(unit, property_name)


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
    return getattr(unit, "lifecycle_status", None) == "active"


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


def _condition_behavior_flags(payload: dict[str, Any]) -> tuple[str, ...]:
    singular = payload.get("Flag")
    plural = payload.get("Flags")
    if singular is not None and plural is not None:
        return ()
    if isinstance(singular, str) and singular:
        return (singular,)
    if (
        isinstance(plural, list)
        and plural
        and all(isinstance(flag, str) and flag for flag in plural)
        and len(plural) == len(set(plural))
    ):
        return tuple(plural)
    return ()


def _condition_damage_tags(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list) or not value:
        return None
    tags: list[str] = []
    for item in value:
        if (
            not isinstance(item, dict)
            or item.get("blocked_reason")
            or not isinstance(item.get("name"), str)
            or not item["name"]
        ):
            return None
        name = str(item["name"])
        if name in tags:
            return None
        tags.append(name)
    return tuple(tags)


def _event_damage_tags(payload: dict[str, Any]) -> tuple[str, ...]:
    tags: list[str] = []
    for key in ("damage_tags", "damage_tag"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            tags.append(value)
        elif isinstance(value, (list, tuple, set)):
            tags.extend(
                item
                for item in value
                if isinstance(item, str) and item
            )
    return tuple(dict.fromkeys(tags))


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
    if isinstance(values, dict) and _finite_number(values.get(key)):
        return float(values[key]), {
            "source_type": str(source.get("source_type") or "binding_source"),
            "matched_by": "values",
        }
    if _finite_number(source.get(key)):
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
    if _finite_number(indexed):
        return float(indexed), None, None, ()
    if isinstance(indexed, dict) and _finite_number(indexed.get("value")):
        return float(indexed["value"]), None, indexed, ()
    keys = indexed if isinstance(indexed, list) else [indexed]
    resolved = tuple(
        entry_key
        for entry_key in keys
        if isinstance(entry_key, str)
        and isinstance(entries.get(entry_key), dict)
        and _finite_number(entries[entry_key].get("value"))
    )
    if len(resolved) > 1:
        return None, None, None, resolved
    for entry_key in keys:
        if not isinstance(entry_key, str):
            continue
        entry = entries.get(entry_key)
        if isinstance(entry, dict) and _finite_number(entry.get("value")):
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
