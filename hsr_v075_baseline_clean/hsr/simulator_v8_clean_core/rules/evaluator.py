from __future__ import annotations

import math
import json
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.model import GameEvent

from ..dynamic_key_hash import tbgd_dynamic_key_hash
from ..unit_eligibility import (
    runtime_unit_combat_team,
    runtime_unit_is_active,
    runtime_unit_is_battle_event_entity,
    runtime_unit_is_on_field,
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
    NUMERIC_UNARY_OPERATIONS,
    numeric_unary_value,
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
    trigger_event: GameEvent | None = None


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
    "ByCheckCustomValueBool",
    "ByCompareAbilityProperty",
    "ByCompareAliveEnemyNumber",
    "ByCompareCharacterID",
    "ByCompareDynamicValue",
    "ByNamedBooleanFlag",
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
    "ByIsTeamLocationIndexType",
    "ByIsTopActionDelayTarget",
    "ByRandomChance",
    "ByRankActivated",
    "BySkillPointActivated",
    "ByCurrentSkillName",
    "ByCurrentSkillType",
    "ByIsContainModifier",
    "ByTargetLockHP",
    "ByIsEnableNegativeHP",
    "ByIsInCharacterIDGroup",
    "ByIsAutoBattle",
    "ByHaveEnemyAlive",
    "ByDieAnimFinished",
    "ByCheckFightFinish",
    "ByIsCurrentSkillActive",
    "ByIsInsertAction",
    "ByIsHitAllCallBackStack",
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

_TEAM_LOCATION_INDEX_TEAM_SIDES = MappingProxyType({
    "TeamLight": "ally",
    "TeamDark": "enemy",
})
_TEAM_LOCATION_INDEX_TYPES = frozenset({"Left", "Right", "Medium", "Max"})


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
    # Declared mutable slots carry an initial-zero baseline, not a committed
    # write. A compiled expression fallback is the authored formula value and
    # must win while no committed runtime writer exists.
    declared_default_matches = [
        match
        for match in matches
        if match[1].get("binding_role") == "declared_mutable_slot_default"
    ]
    committed_matches = [
        match
        for match in matches
        if match[1].get("binding_role") != "declared_mutable_slot_default"
    ]
    declared_default_conflict = bool(
        not committed_matches
        and len(declared_default_matches) > 1
        and len({value for value, _ in declared_default_matches}) > 1
    )
    if len(committed_matches) > 1:
        # 同一条已提交记录经多个来源到达时仍是一个事实，不构成冲突。
        unique_matches: dict[tuple[float, str], tuple[float, dict[str, Any]]] = {}
        for match in committed_matches:
            entry_key = str(match[1].get("entry_key") or "")
            unique_matches.setdefault(
                (match[0], entry_key or f"anonymous:{len(unique_matches)}"), match
            )
        committed_matches = list(unique_matches.values())
    if len(committed_matches) > 1:
        # The same dynamic slot name can exist both as the context-local
        # status/ability value and as another unit's committed unit-scope
        # value (servants share slot names with their owner's bookkeeping
        # modifiers). A contextual read belongs to the current unit, so
        # foreign unit entries are not competitors of the local value.
        preferred_owner = str(
            getattr(context, "owner_id", None)
            or getattr(context, "target_id", None)
            or ""
        )
        local_matches = [
            match
            for match in committed_matches
            if _binding_context_rank(match[1], preferred_owner) == 0
        ]
        if local_matches:
            committed_matches = local_matches
    sources_checked.append({"source_type": "explicit_dynamic_values", "hit": False})
    if (
        ambiguous_matches
        or len(committed_matches) > 1
        or len(fallback_matches) > 1
        or declared_default_conflict
    ):
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
    if committed_matches:
        value, binding = committed_matches[0]
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
    if declared_default_matches:
        value, binding = declared_default_matches[0]
        return NumericEvaluationResult(
            ok=True,
            value=value,
            expression_kind="dynamic_hash",
            bindings={
                "hash": hash_value,
                "key": key,
                "value": value,
                **binding,
                "binding_role": "declared_mutable_slot_default",
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
        if opcode in NUMERIC_UNARY_OPERATIONS:
            if not stack:
                return _numeric_program_blocked(
                    "numeric_program_stack_underflow",
                    source_trace,
                    index,
                )
            try:
                stack[-1] = numeric_unary_value(opcode, stack[-1])
            except (OverflowError, ValueError):
                return _numeric_program_blocked(
                    "numeric_program_non_finite_result",
                    source_trace,
                    index,
                )
            continue
        if opcode in {"min", "max"}:
            operand_count = instruction.get("operand_count")
            if (
                not isinstance(operand_count, int)
                or isinstance(operand_count, bool)
                or operand_count < 1
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
            stack.append(max(operands) if opcode == "max" else min(operands))
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


def _dynamic_key_identity(key: str) -> int:
    """Resolve a TBGD DynamicKey name to its numeric dynamic hash.

    Source conditions name dynamic values; binding sources index them by the
    TBGD hash. A key already written as a numeric hash string is kept as that
    number.
    """

    stripped = key.strip()
    try:
        return int(stripped)
    except ValueError:
        return tbgd_dynamic_key_hash(key)


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
    if opcode in {"ByRankActivated", "BySkillPointActivated"}:
        selector = payload.get("build_selector")
        actor_id = context.actor_id
        if "TargetType" in payload:
            actor_id, target_details = _condition_single_target(payload["TargetType"], context)
            if actor_id is None:
                return _condition_blocked(condition_id, opcode, "character_build_selector_target_unresolved", target_details, source_trace)
        if not isinstance(selector, dict) or not actor_id:
            return _condition_blocked(
                condition_id, opcode, "character_build_selector_context_missing", {}, source_trace
            )
        operand = _condition_operand(
            context, "unit.build_selector", subject_ids=(actor_id,), parameters=selector
        )
        if operand.status != "resolved" or operand.value_type != "boolean":
            return _condition_operand_blocked(condition_id, opcode, operand, source_trace)
        return _condition_result(
            bool(operand.value), condition_id, opcode, "character_build_selector",
            {"operand": operand.to_json()}, source_trace,
        )
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
    from ..core.model import GameEvent, StatusLifecycleFact

    trigger_event = context.trigger_event
    lifecycle_fact = (
        trigger_event.status_lifecycle_fact
        if trigger_event is not None
        and type(trigger_event) is GameEvent
        and type(trigger_event.status_lifecycle_fact) is StatusLifecycleFact
        else None
    )
    if opcode == "ByCheckModifierCallBackIsSelf":
        explicit = event_payload.get("is_self")
        detail = context.status_detail or {}
        event_instance_id = (
            lifecycle_fact.status_instance_id
            if lifecycle_fact is not None
            else event_payload.get("status_instance_id")
        )
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
        actual = (lifecycle_fact.modifier_name if lifecycle_fact is not None
                  else event_payload.get("modifier_name"))
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
        actual = (lifecycle_fact.status_type if lifecycle_fact is not None
                  else event_payload.get("status_type"))
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
        from ..core.model import StatusImmunityFact

        expected = payload.get("Flag")
        if not isinstance(expected, str) or not expected:
            return _condition_blocked(condition_id, opcode, "behavior_flag_missing", {}, source_trace)
        trigger = trigger_event
        if trigger is not None and type(trigger) is not GameEvent:
            return _condition_blocked(condition_id, opcode, "callback_trigger_event_invalid", {}, source_trace)
        if (trigger is not None and (trigger.event_type == "status.immunity" or trigger.status_immunity_fact is not None)
                or event_payload.get("event_window") == "OnImmuneDebuff"):
            fact = trigger.status_immunity_fact if trigger is not None else None
            detail = context.status_detail or {}
            # Callback leaves can already have changed current state. Validate
            # this event against the producer's original immutable boundary.
            if (type(fact) is not StatusImmunityFact or trigger.window != "OnImmuneDebuff"
                    or not fact.matches(fact._state, trigger)
                    or detail.get("instance_id") != fact.protection_instance_id
                    or detail.get("modifier_name") != fact.protection_modifier_name
                    or detail.get("owner_id") != fact.target_id):
                return _condition_blocked(condition_id, opcode,
                    "status_immunity_condition_fact_missing_or_mismatched", {}, source_trace)
            raw_flags = fact.incoming_behavior_flags
        else:
            raw_flags = (
                list(lifecycle_fact.behavior_flags)
                if lifecycle_fact is not None
                else event_payload.get("behavior_flags")
            )
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
    if opcode == "ByCheckCustomValueBool":
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        if target_id is None:
            return _condition_blocked(
                condition_id,
                opcode,
                "target_alias_unresolved",
                target_details,
                source_trace,
            )
        unit = _state_unit(context, target_id)
        if unit is None:
            return _condition_blocked(
                condition_id,
                opcode,
                "target_unit_missing",
                {"target_id": target_id},
                source_trace,
            )
        key = payload.get("Key")
        hash_value = key.get("Hash") if isinstance(key, dict) else None
        if isinstance(hash_value, bool) or not isinstance(hash_value, int):
            return _condition_blocked(
                condition_id,
                opcode,
                "custom_value_key_hash_missing",
                {"target_id": target_id, "key": key},
                source_trace,
            )
        flags = getattr(unit, "flags", None)
        raw_tags = flags.get("custom_value_tags") if isinstance(flags, dict) else None
        if not isinstance(raw_tags, (list, tuple)):
            # The unit's formal card kind never declared a tag list, or the
            # declaration was not admitted into the birth template.
            return _condition_blocked(
                condition_id,
                opcode,
                "custom_value_tag_source_missing",
                {"target_id": target_id},
                source_trace,
            )
        tag_hashes: list[tuple[str, int]] = []
        invalid_tags: list[object] = []
        for tag in raw_tags:
            if not isinstance(tag, str) or not tag:
                invalid_tags.append(tag)
                continue
            tag_hashes.append((tag, tbgd_dynamic_key_hash(tag)))
        if invalid_tags:
            return _condition_blocked(
                condition_id,
                opcode,
                "custom_value_tag_entry_invalid",
                {"target_id": target_id, "invalid_tags": invalid_tags},
                source_trace,
            )
        matched = hash_value in {value for _, value in tag_hashes}
        return _condition_result(
            matched,
            condition_id,
            opcode,
            "custom_value_tag_checked",
            {
                "target_id": target_id,
                "key_hash": hash_value,
                "declared_tags": [tag for tag, _ in tag_hashes],
                "matched_tag": next(
                    (tag for tag, value in tag_hashes if value == hash_value), ""
                ),
                "tag_source": (
                    flags.get("custom_value_tag_source_trace")
                    if isinstance(flags, dict)
                    else None
                ),
            },
            source_trace,
        )
    if opcode == "ByIsTeamLocationIndexType":
        team_type = payload.get("TeamType")
        index_type = payload.get("Type")
        if index_type is None:
            index_type = "Left"
        details: dict[str, Any] = {
            "team_type": team_type,
            "index_type": index_type,
            "target_position": None,
            "team_positions": [],
            "team_member_ids": [],
        }
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        if target_id is None:
            return _condition_blocked(
                condition_id,
                opcode,
                "target_alias_unresolved",
                {**details, "target_resolution": target_details},
                source_trace,
            )
        details["target_id"] = target_id
        target = _state_unit(context, target_id)
        if target is None:
            return _condition_blocked(condition_id, opcode, "target_unit_missing", details, source_trace)
        expected_side = (
            _TEAM_LOCATION_INDEX_TEAM_SIDES.get(team_type)
            if isinstance(team_type, str)
            else None
        )
        if expected_side is None:
            return _condition_blocked(
                condition_id,
                opcode,
                f"team_type_not_admitted:{team_type}",
                {**details, "admitted_team_types": sorted(_TEAM_LOCATION_INDEX_TEAM_SIDES)},
                source_trace,
            )
        if not isinstance(index_type, str) or index_type not in _TEAM_LOCATION_INDEX_TYPES:
            return _condition_blocked(
                condition_id,
                opcode,
                f"team_location_index_type_not_admitted:{index_type}",
                {**details, "admitted_index_types": sorted(_TEAM_LOCATION_INDEX_TYPES)},
                source_trace,
            )
        target_side = getattr(target, "side", None)
        if target_side != expected_side:
            return _condition_result(
                False,
                condition_id,
                opcode,
                "team_location_target_side_mismatch",
                {**details, "expected_side": expected_side, "target_side": target_side},
                source_trace,
            )
        units = getattr(getattr(context, "state", None), "units", None)
        if not isinstance(units, dict):
            return _condition_blocked(
                condition_id, opcode, "team_location_state_units_missing", details, source_trace
            )
        target_position = _team_location_position(target)
        details["target_position"] = target_position
        if target_position is None:
            return _condition_blocked(
                condition_id,
                opcode,
                "team_location_position_missing",
                {**details, "missing_position_unit_ids": [target_id]},
                source_trace,
            )
        member_ids: list[str] = []
        member_positions: dict[str, int] = {}
        missing_position_ids: list[str] = []
        for unit_id in sorted(units):
            unit = units[unit_id]
            if getattr(unit, "side", None) != expected_side:
                continue
            if not _unit_is_alive(unit):
                continue
            hp = getattr(unit, "hp", None)
            if not _finite_number(hp) or float(hp) <= 0:
                continue
            position = _team_location_position(unit)
            if position is None:
                missing_position_ids.append(unit_id)
                continue
            member_ids.append(unit_id)
            member_positions[unit_id] = position
        details["team_member_ids"] = list(member_ids)
        details["team_positions"] = [member_positions[unit_id] for unit_id in member_ids]
        if missing_position_ids:
            return _condition_blocked(
                condition_id,
                opcode,
                "team_location_position_missing",
                {**details, "missing_position_unit_ids": missing_position_ids},
                source_trace,
            )
        if target_id not in member_positions:
            return _condition_result(
                False,
                condition_id,
                opcode,
                "team_location_target_not_alive_in_team",
                {**details, "target_side": target_side},
                source_trace,
            )
        team_positions = details["team_positions"]
        minimum = min(team_positions)
        maximum = max(team_positions)
        if index_type == "Left":
            matched = target_position == minimum
        elif index_type in {"Right", "Max"}:
            matched = target_position == maximum
        else:
            matched = minimum < target_position < maximum
        return _condition_result(
            matched,
            condition_id,
            opcode,
            "team_location_index_checked",
            {
                **details,
                "expected_side": expected_side,
                "target_side": target_side,
                "team_min_position": minimum,
                "team_max_position": maximum,
            },
            source_trace,
        )
    if opcode == "ByIsAutoBattle":
        # 模拟器由外部推演器逐步提交操作，等同玩家手动操作，不存在客户端自动战斗。
        if set(payload) - {"$type"}:
            return _condition_blocked(condition_id, opcode, "auto_battle_payload_not_admitted", {"payload": payload}, source_trace)
        return _condition_result(False, condition_id, opcode, "externally_controlled_battle_is_manual",
            {"control": "external_command"}, source_trace)
    if opcode == "ByIsInCharacterIDGroup":
        # 角色 ID 组由编译期从 GameCoreConstValue.CharacterIDGroups 附加；缺失即阻断。
        ids = payload.get("CharacterIDList")
        if not isinstance(ids, list) or any(type(item) is not int for item in ids):
            return _condition_blocked(condition_id, opcode, "character_id_group_not_compiled", {"group": payload.get("Group")}, source_trace)
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        unit = _state_unit(context, target_id) if target_id else None
        if unit is None:
            return _condition_blocked(condition_id, opcode, "character_id_group_target_missing", target_details, source_trace)
        actual = _unit_character_id(unit)
        member = actual is not None and actual in ids
        if payload.get("Inverse") is True:
            member = not member
        return _condition_result(member, condition_id, opcode, "character_id_group_checked",
            {"target_id": target_id, "character_id": actual, "group": payload.get("Group"),
             "inverse": payload.get("Inverse") is True}, source_trace)
    if opcode == "ByIsEnableNegativeHP":
        # 负生命只能由 EnableNegativeHP 写入的已提交标记开启；该效果尚未接入，
        # 因而所有单位均读到未开启，不会伪造负生命值。
        if set(payload) - {"$type", "TargetType", "Inverse"} or type(payload.get("Inverse", False)) is not bool:
            return _condition_blocked(condition_id, opcode, "negative_hp_payload_not_admitted", {"payload": payload}, source_trace)
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        unit = _state_unit(context, target_id) if target_id else None
        if unit is None:
            return _condition_blocked(condition_id, opcode, "negative_hp_target_missing", target_details, source_trace)
        enabled = getattr(unit, "flags", {}).get("negative_hp_enabled") is True
        if payload.get("Inverse") is True:
            enabled = not enabled
        return _condition_result(enabled, condition_id, opcode, "negative_hp_checked",
            {"target_id": target_id, "inverse": payload.get("Inverse") is True}, source_trace)
    if opcode == "ByTargetLockHP":
        # 读取已提交的锁血记录；可选 LockKey 限定某一把锁。
        lock_key = payload.get("LockKey")
        if lock_key is not None and (not isinstance(lock_key, str) or not lock_key):
            return _condition_blocked(condition_id, opcode, "hp_lock_key_invalid", {"payload": payload}, source_trace)
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        unit = _state_unit(context, target_id) if target_id else None
        if unit is None:
            return _condition_blocked(condition_id, opcode, "hp_lock_target_missing", target_details, source_trace)
        locks = getattr(unit, "flags", {}).get("hp_locks")
        locks = locks if isinstance(locks, dict) else {}
        locked = bool(locks) if lock_key is None else lock_key in locks
        if payload.get("Inverse") is True:
            locked = not locked
        return _condition_result(locked, condition_id, opcode, "hp_lock_checked",
            {"target_id": target_id, "lock_key": lock_key, "inverse": payload.get("Inverse") is True},
            source_trace)
    if opcode == "ByIsContainModifier":
        modifier_name = _value_field(payload.get("ModifierName"))
        if not isinstance(modifier_name, str) or not modifier_name:
            return _condition_blocked(condition_id, opcode, "modifier_name_missing", {"payload": payload}, source_trace)
        target_ids, details = _condition_target_ids(payload.get("TargetType"), context)
        if target_ids == ():
            return _condition_result(False, condition_id, opcode, "modifier_presence_on_empty_group", details, source_trace)
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        if target_id is None:
            return _condition_blocked(condition_id, opcode, "target_alias_unresolved", target_details, source_trace)
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
        trigger = context.trigger_event
        if opcode == "ByCompareChangeValue" and (
                (trigger is not None and trigger.ability_property_change_fact is not None)
                or "ability_property_change_value" in event_payload):
            from ..systems.ability_property_watchers import AbilityPropertyChangeFact
            fact = trigger.ability_property_change_fact if trigger is not None else None
            if type(fact) is not AbilityPropertyChangeFact or not fact.matches_event(trigger):
                return _condition_blocked(condition_id, opcode, "property_change_fact_missing_or_mismatched", {}, source_trace)
            actual = fact.delta
        elif ((trigger is not None and trigger.event_type in {"hp.change", "heal.after", "unit.hp_overflow"})
                or event_payload.get("event_type") in {"hp.change", "heal.after"}):
            from ..systems.mutation_events import native_hp_change_value
            actual, reason = native_hp_change_value(trigger)
            if reason:
                return _condition_blocked(condition_id, opcode, reason, {}, source_trace)
        else:
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
        target_ids, target_details = _condition_target_ids(payload.get("TargetType"), context)
        if target_ids is None or len(target_ids) > 1:
            return _condition_blocked(condition_id, opcode, "target_validity_target_unresolved_or_ambiguous", target_details, source_trace)
        target_id = target_ids[0] if target_ids else None
        unit = _state_unit(context, target_id) if target_id else None
        if unit is None:
            return _condition_result(False, condition_id, opcode, "target_missing", target_details, source_trace)
        # Validity is entity existence, not selectability: unselectable or
        # untargetable entities such as battle events remain valid while alive.
        valid = runtime_unit_is_active(unit) and (
            runtime_unit_is_on_field(unit) or runtime_unit_is_battle_event_entity(unit)
        )
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
        target_ids, details = _condition_target_ids(payload.get("TargetType"), context)
        if target_ids == ():
            return _condition_result(False, condition_id, opcode, "enemy_presence_on_empty_group", details, source_trace)
        target_id, target_details = _resolve_condition_target(payload.get("TargetType"), context)
        if target_id is None:
            return _condition_blocked(condition_id, opcode, "target_alias_unresolved", target_details, source_trace)
        state = context.state
        units = getattr(state, "units", None)
        actor = _state_unit(context, target_id)
        if not isinstance(units, dict) or actor is None:
            return _condition_blocked(condition_id, opcode, "state_or_actor_missing", {"target_id": target_id}, source_trace)
        alive_enemies = [
            unit_id
            for unit_id, unit in units.items()
            if runtime_units_are_opposing_combat_teams(actor, unit)
            and _unit_is_alive(unit) and float(getattr(unit, "hp", 0.0) or 0.0) > 0
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
    if opcode == "ByDieAnimFinished":
        team = payload.get("TeamTypeMask")
        entity = payload.get("EntityTypeMask")
        side = _TEAM_LOCATION_INDEX_TEAM_SIDES.get(str(team or ""))
        if side is None or entity != "Mask_TeamCharacters":
            return _condition_blocked(
                condition_id, opcode, "die_anim_masks_not_admitted",
                {"team_type_mask": team, "entity_type_mask": entity}, source_trace,
            )
        state = context.state
        units = getattr(state, "units", None)
        if not isinstance(units, dict):
            return _condition_blocked(condition_id, opcode, "state_units_missing", {}, source_trace)
        pending = [
            unit_id
            for unit_id, unit in units.items()
            if getattr(unit, "side", None) == side
            and not unit.flags.get("owner_id")
            and not unit.flags.get("servant_definition_id")
            and getattr(unit, "lifecycle_status", "active") == "limbo"
        ]
        finished = not pending
        if payload.get("Inverse") is True:
            finished = not finished
        return _condition_result(
            finished, condition_id, opcode, "die_animation_finished_checked",
            {"side": side, "pending_unit_ids": pending,
             "inverse": payload.get("Inverse") is True}, source_trace,
        )
    if opcode == "ByCheckFightFinish":
        state = context.state
        units = getattr(state, "units", None)
        actor = _state_unit(context, context.actor_id)
        if not isinstance(units, dict) or actor is None:
            return _condition_blocked(
                condition_id, opcode, "state_or_actor_missing",
                {"actor_id": context.actor_id}, source_trace,
            )
        # Opposition is the shared combat-team relation: an owner's servant
        # and neutral containers differ in side but are not enemies.
        if runtime_unit_combat_team(actor) == "neutral":
            return _condition_blocked(
                condition_id, opcode, "fight_finish_actor_team_not_admitted",
                {"actor_id": context.actor_id}, source_trace,
            )
        alive_opponents = [
            unit_id
            for unit_id, unit in units.items()
            if runtime_units_are_opposing_combat_teams(actor, unit)
            and not runtime_unit_is_battle_event_entity(unit)
            and runtime_unit_is_active(unit)
            and runtime_unit_is_on_field(unit)
            and float(getattr(unit, "hp", 0.0) or 0.0) > 0
        ]
        finished = not alive_opponents
        if payload.get("Inverse") is True:
            finished = not finished
        return _condition_result(
            finished, condition_id, opcode, "fight_finish_checked",
            {"alive_opponent_ids": alive_opponents,
             "inverse": payload.get("Inverse") is True}, source_trace,
        )
    if opcode == "ByCompareAliveEnemyNumber":
        target_id, target_details = _resolve_condition_target(
            payload.get("TargetType"), context
        )
        if target_id is None:
            return _condition_blocked(
                condition_id, opcode, "target_alias_unresolved", target_details, source_trace
            )
        operand = _condition_operand(
            context,
            "relation.alive_opposing_count",
            subject_ids=(target_id,),
        )
        if operand.status != "resolved" or operand.value_type != "number":
            return _condition_operand_blocked(condition_id, opcode, operand, source_trace)
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
        return _comparison_condition(
            condition_id,
            opcode,
            float(operand.value),
            payload.get("CompareType"),
            compare_value.value,
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
        from ..core.model import current_max_hp

        max_hp = current_max_hp(unit)
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
    if opcode == "ByNamedBooleanFlag":
        from ..systems.named_boolean_flags import read_named_flag, resolve_named_key
        target_id, details = _resolve_condition_target(payload.get("TargetType"), context)
        key, reason = resolve_named_key(payload.get("KeyExpression"), context.binding_sources)
        if reason:
            return _condition_blocked(condition_id, opcode, reason, details, source_trace)
        value, reason = read_named_flag(_state_unit(context, target_id) if target_id else None, key)
        if reason:
            return _condition_blocked(condition_id, opcode, reason, details, source_trace)
        return _condition_result(value, condition_id, opcode, "named_boolean_read",
            {"target_id": target_id, "key": key, "value": value}, source_trace)
    if opcode == "ByCompareDynamicValue":
        key = _value_field(payload.get("DynamicKey"))
        if not isinstance(key, str) or not key:
            return _condition_blocked(condition_id, opcode, "dynamic_key_missing", {"payload": payload}, source_trace)
        target_alias_value = _target_alias(payload.get("TargetType")) if payload.get("TargetType") is not None else None
        if str(payload.get("ContextScope") or "") == "TargetEntity" or (
            # An explicit non-owner target without a scope reads that entity too;
            # the owner form remains the status-local read handled below.
            not payload.get("ContextScope")
            and payload.get("TargetType") is not None
            and target_alias_value != "ModifierOwnerEntity"
        ):
            # TargetEntity names one formal unit scope.  An explicitly present
            # target that cannot resolve to exactly one entity is not a licence
            # to read the owner, a status instance, or ambient dynamic values.
            # An omitted TargetType keeps the formal modifier-owner default
            # already used by ByCompareModifierValue (the owner in status
            # scopes, the caster in action/startup scopes).
            target_type = payload.get("TargetType")
            if target_type is None:
                target_id = context.owner_id or context.actor_id
                target_details = {
                    "alias": "ModifierOwnerEntity",
                    "source": "tbgd_condition_default",
                }
            else:
                target_id, target_details = _condition_single_target(
                    target_type, context
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
                "unit.dynamic_value",
                subject_ids=(target_id,),
                parameters={"name": key},
            )
            if operand.status != "resolved" or operand.value_type != "number":
                return _condition_operand_blocked(
                    condition_id, opcode, operand, source_trace
                )
            actual_value = float(operand.value)
        else:
            scoped_sources = _scope_filtered_binding_sources(
                context.binding_sources, str(payload.get("ContextScope") or "")
            )
            numeric_context = NumericEvaluationContext(
                dynamic_values=context.dynamic_values,
                binding_sources=scoped_sources,
                source_trace=source_trace,
            )
            if scoped_sources != tuple(context.binding_sources or ()):
                # 能力实例内优先读本实例条目；没有能力实例（如装配监听）时
                # 模板槽位写在单位作用域，退回原来源读取。
                probe = evaluator.evaluate_numeric(
                    numeric_dynamic_hash(_dynamic_key_identity(key)), numeric_context,
                )
                by_name = evaluator.evaluate_numeric(numeric_dynamic_hash(key), numeric_context)
                if not (probe.ok or by_name.ok):
                    numeric_context = replace(numeric_context, binding_sources=tuple(context.binding_sources or ()))
            # An explicitly supplied dynamic value keeps its source name; a
            # source condition naming a TBGD dynamic key additionally resolves
            # through the numeric hash used by binding sources.
            actual = evaluator.evaluate_numeric(numeric_dynamic_hash(key), numeric_context)
            if not actual.ok:
                hashed_key = _dynamic_key_identity(key)
                if str(hashed_key) != key:
                    retried = evaluator.evaluate_numeric(
                        numeric_dynamic_hash(hashed_key), numeric_context,
                    )
                    if retried.ok:
                        actual = retried
            if (
                (not actual.ok or actual.value is None)
                and str(payload.get("ContextScope") or "") == "AITag"
                and str(actual.blocked_reason or "").startswith(
                    "dynamic_hash_unbound:"
                )
            ):
                # AI tag variables are engine AI metadata, not a battle
                # producer.  The source uses the read-then-set pattern as an
                # initialize-once guard, so an unset tag is its default zero.
                actual_value = 0.0
            else:
                if not actual.ok or actual.value is None:
                    return _condition_blocked(
                        condition_id,
                        opcode,
                        f"dynamic_value_blocked:{actual.blocked_reason}",
                        {"dynamic_key": key, "numeric_evaluation": actual.to_json()},
                        source_trace,
                    )
                actual_value = float(actual.value)
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
    if opcode == "ByCompareModifierValue":
        if payload.get("TargetType") is None:
            alias = payload.get("default_target_alias", "ModifierOwnerEntity")
            if alias not in {"Caster", "ModifierOwnerEntity"}:
                return _condition_blocked(condition_id, opcode, "modifier_value_default_target_not_admitted", {}, source_trace)
            target_id = context.actor_id if alias == "Caster" else context.owner_id or context.actor_id
            target_details = {
                "alias": alias,
                "source": "canonical_condition_target" if "default_target_alias" in payload else "tbgd_condition_default",
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
    if opcode == "ByIsHitAllCallBackStack":
        # Re-entrancy guard used by OnAfterHitAll callbacks that deal an extra
        # hit.  Only the damage-window producer establishes the stack position,
        # through the typed fact bound to this invocation and event.  The
        # payload marker is a transport copy that must agree, never an input.
        if payload:
            return _condition_blocked(
                condition_id,
                opcode,
                "hit_all_callback_stack_shape_not_admitted",
                {"payload": payload},
                source_trace,
            )
        from ..core.model import HitWindowInvocationFact

        trigger_event = context.trigger_event
        fact = trigger_event.hit_window_invocation_fact if trigger_event is not None else None
        if type(fact) is not HitWindowInvocationFact or not fact.matches(trigger_event):
            return _condition_blocked(
                condition_id,
                opcode,
                "hit_all_callback_stack_native_fact_missing_or_mismatched",
                {"event_id": trigger_event.event_id if trigger_event is not None else None},
                source_trace,
            )
        in_stack = fact.in_callback_stack
        if (context.event_payload or {}).get("hit_all_callback_stack", False) is not in_stack:
            return _condition_blocked(
                condition_id,
                opcode,
                "hit_all_callback_stack_transport_mismatch",
                {"event_id": trigger_event.event_id},
                source_trace,
            )
        return _condition_result(
            in_stack,
            condition_id,
            opcode,
            "hit_all_callback_stack_compared",
            {"hit_all_callback_stack": in_stack},
            source_trace,
        )
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
        if (payload.get("ValueType") == "LifeTime" and operand.status == "resolved"
                and operand.value_type == "string" and operand.value == "permanent"):
            expected = evaluator.evaluate_numeric(payload.get("CompareValue"), NumericEvaluationContext(
                dynamic_values=context.dynamic_values, binding_sources=context.binding_sources,
                source_trace=source_trace,
            ))
            # The canonical permanent kind has no countdown. Do not invent a
            # native numeric sentinel for comparisons beyond this timed filter.
            if expected.ok and expected.value == 0 and payload.get("CompareType") == "Greater":
                return _condition_result(False, condition_id, opcode,
                    "permanent_modifier_has_no_positive_lifetime", {"operand": operand.to_json()}, source_trace)
            return _condition_blocked(condition_id, opcode, "permanent_lifetime_comparison_not_admitted",
                {"operand": operand.to_json()}, source_trace)
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
    key = _condition_target_key(alias_value)
    if key in (context.target_resolution_errors or {}):
        return None, {"target_key": key, "reason": context.target_resolution_errors[key],
                      "source": "pre_resolved_target_expression"}
    if key in (context.resolved_target_groups or {}):
        targets = context.resolved_target_groups[key]
        return (targets[0] if len(targets) == 1 else None), {
            "target_key": key, "target_ids": list(targets), "source": "pre_resolved_target_expression",
        }
    alias = _target_alias(alias_value)
    if alias == "CasterSelfCreateBattleEvent":
        # The battle event this caster created, through the committed
        # entity.created_battle_events relation, matching the runtime
        # TargetAlias semantics used by status callbacks and effects.
        state = context.state
        caster_id = context.actor_id
        if state is None or not isinstance(caster_id, str) or caster_id not in state.units:
            return None, {"alias": alias, "reason": "caster_missing"}
        from ..systems.target import resolve_created_battle_event_targets

        target_ids = resolve_created_battle_event_targets(state, caster_id)
        if len(target_ids) == 1:
            return target_ids[0], {"alias": alias, "source": "entity.created_battle_events"}
        return None, {
            "alias": alias,
            "target_ids": list(target_ids),
            "blocked_reason": "created_battle_event_missing" if not target_ids else "created_battle_event_ambiguous",
        }
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
        "CurrentTurnActionEntity": _first_string(
            payload,
            "turn_owner_id",
            "turn_action_entity_id",
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
        from ..core.model import current_max_hp

        maximum = current_max_hp(unit)
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
    from .combatant_identity import combatant_character_id
    return combatant_character_id(unit)


def _unit_is_alive(unit: Any | None) -> bool:
    if unit is None:
        return False
    return getattr(unit, "lifecycle_status", None) == "active"


def _team_location_position(unit: Any) -> int | None:
    flags = getattr(unit, "flags", None)
    if not isinstance(flags, dict):
        return None
    position = flags.get("position")
    if isinstance(position, int) and not isinstance(position, bool):
        return position
    return None


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
    if (isinstance(context.status_detail, dict)
            and context.status_detail.get("owner_id", context.owner_id) == target_id):
        details.append(context.status_detail)
    unit = _state_unit(context, target_id)
    flags = getattr(unit, "flags", {}) if unit is not None else {}
    raw_details = flags.get("status_details", ()) if isinstance(flags, dict) else ()
    if isinstance(raw_details, (list, tuple)):
        details.extend(item for item in raw_details if isinstance(item, dict))
    matched = False
    for detail in details:
        if (
            isinstance(modifier_name, str)
            and modifier_name
            and detail.get("modifier_name") != modifier_name
        ):
            continue
        matched = True
        if value_type == "Layer" and type(detail.get("stacks")) in (int, float):
            return float(detail["stacks"]), "ok"
        if value_type == "LifeTime":
            for key in ("remaining_duration", "duration"):
                if isinstance(detail.get(key), (int, float)):
                    return float(detail[key]), "ok"
        if value_type == "MaxLayer" and isinstance(detail.get("max_stacks"), (int, float)):
            return float(detail["max_stacks"]), "ok"
    if (value_type == "Layer" and isinstance(modifier_name, str) and modifier_name
            and unit is not None and isinstance(raw_details, (list, tuple)) and not matched):
        # A count over the actual target's empty matching instance set is zero.
        # This is not a fallback for missing units, malformed instances, or
        # scalar lifetime/max-layer fields whose definition is still required.
        return 0.0, "ok"
    return None, f"modifier_value_not_available:{modifier_name}:{value_type}"


# 声明了能力/模板作用域的读取只看能力作用域条目；同名单位槽位属于另一作用域。
_ABILITY_CONTEXT_SCOPES = frozenset({"ContextAbility", "ContextTaskTemplate"})


def _scope_filtered_binding_sources(
    sources: tuple[dict[str, Any], ...] | None, context_scope: str,
) -> tuple[dict[str, Any], ...]:
    if context_scope not in _ABILITY_CONTEXT_SCOPES:
        return tuple(sources or ())
    filtered: list[dict[str, Any]] = []
    for source in sources or ():
        entries = source.get("entries") if isinstance(source, dict) else None
        if not isinstance(entries, dict) or not any(
            isinstance(entry, dict) and "scope" in entry for entry in entries.values()
        ):
            filtered.append(source)
            continue
        kept = {
            key: entry for key, entry in entries.items()
            if isinstance(entry, dict) and entry.get("scope") == "ability"
        }
        by_hash: dict[str, list[str]] = {}
        by_name: dict[str, list[str]] = {}
        for key, entry in kept.items():
            if entry.get("hash") is not None:
                by_hash.setdefault(str(entry["hash"]), []).append(key)
            if entry.get("name"):
                by_name.setdefault(str(entry["name"]), []).append(key)
        filtered.append({
            **{name: value for name, value in source.items()
               if name not in {"entries", "by_hash", "by_name", "values"}},
            "entries": kept, "by_hash": by_hash, "by_name": by_name,
        })
    return tuple(filtered)


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


def _binding_context_rank(binding: dict[str, Any], owner_id: str) -> int:
    """Prefer context-local values over another unit's unit-scope entry."""

    entry = binding.get("entry")
    if not isinstance(entry, dict):
        return 0
    scope_kind = str(entry.get("scope_kind") or entry.get("scope") or "")
    if scope_kind not in {"unit", "combat"}:
        return 0
    target_id = str(entry.get("target_id") or entry.get("owner_id") or "")
    if not target_id:
        return 0
    return 0 if owner_id and target_id == owner_id else 1


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
    if isinstance(source.get("binding_role"), str):
        metadata["binding_role"] = source["binding_role"]
    if entry_key is not None:
        metadata["entry_key"] = entry_key
    if entry is not None:
        metadata["entry"] = entry
    return metadata
