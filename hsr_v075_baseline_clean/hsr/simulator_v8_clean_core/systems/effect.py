from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Callable

from ..core.model import BattleState, GameEvent, JSONValue, Mutation, RNGEvent, TargetResolution
from ..core.settlement import SettlementRecord
from ..core.transition_outcome import ExecutionNodeResult
from ..rules.evaluator import NumericEvaluationContext, NumericEvaluationResult, RuleEvaluator
from ..rules.ir import EffectIR
from .damage import DamagePacket, DamageSourceFrame, DamageSystem, DamageWindowLedger
from .dynamic_values import (
    binding_source_from_store,
    find_status_detail,
    status_binding_sources,
    store_from_state,
    upsert_dynamic_value,
)
from .mutation_events import events_for_mutation
from .status import SUPPORTED_ADD_MODIFIER_ALIASES, SUPPORTED_EFFECT_TARGET_ALIASES, StatusSystem


@dataclass(frozen=True)
class EffectResult:
    events: tuple[GameEvent, ...] = ()
    mutations: tuple[Mutation, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    unsupported: tuple[str, ...] = ()
    node_results: tuple[ExecutionNodeResult, ...] = ()


@dataclass(frozen=True)
class EffectExecutionContext:
    state: BattleState
    caster_id: str
    source_id: str
    owner_id: str | None = None
    param_entity_id: str | None = None
    current_action_target_id: str | None = None
    target_resolution: TargetResolution | None = None
    event_payload: dict[str, JSONValue] | None = None
    dynamic_values: dict[str, float] | None = None
    binding_sources: tuple[dict[str, JSONValue], ...] = ()
    damage_window_ledger: DamageWindowLedger | None = None


EffectHandler = Callable[[EffectIR, EffectExecutionContext | None], EffectResult]


class EffectRegistry:
    """Opcode dispatcher for v8 EffectIR handlers."""

    def __init__(self, status_system: StatusSystem | None = None) -> None:
        self.status_system = status_system
        self._handlers: dict[str, EffectHandler] = {}
        if status_system is not None:
            self.register("AddModifier", self._execute_add_modifier)
            self.register("RemoveModifier", self._execute_remove_modifier)
            self.register("RemoveSelfModifier", self._execute_remove_modifier)
            self.register("DispelStatus", self._execute_dispel_status)
        self.register("Heal", self._execute_heal)
        self.register("HealHP", self._execute_heal)
        self.register("Shield", self._execute_shield)
        self.register("InitShield", self._execute_shield)
        self.register("StackShield", self._execute_shield)
        self.register("ModifyShield", self._execute_shield)
        self.register("ResourceDelta", self._execute_resource_delta)
        self.register("ModifySPNew", self._execute_resource_delta)
        self.register("LoseHPByRatio", self._execute_hp_loss_ratio)
        self.register("SetEnergyBarState", self._execute_mechanism_bar_state)
        self.register("SetMonsterEnergyBarState", self._execute_mechanism_bar_state)
        self.register("SetSummonerEnergyBarState", self._execute_mechanism_bar_state)
        self.register("DefineDynamicValue", self._execute_define_dynamic_value)
        self.register("SetDynamicValue", self._execute_set_dynamic_value)
        self.register("SetDynamicValueByAddValue", self._execute_set_dynamic_value_by_add_value)
        self.register("SetDynamicValueByModifierValue", self._execute_set_dynamic_value_by_modifier_value)

    def register(self, opcode: str, handler: EffectHandler) -> None:
        self._handlers[opcode] = handler

    def execute(self, effect: EffectIR, context: EffectExecutionContext | None = None) -> EffectResult:
        handler = self._handlers.get(effect.opcode)
        if not handler:
            return EffectResult(
                unsupported=(effect.opcode,),
                node_results=(
                    ExecutionNodeResult(
                        node_kind="effect",
                        node_id=effect.effect_id,
                        status="unsupported",
                        reason_code=f"effect_handler_missing:{effect.opcode}",
                    ),
                ),
            )
        coverage = self.coverage(effect)
        if coverage != "executable":
            specific_reason = _effect_payload_blocked_reason(effect)
            reason = f"effect_not_executable:{coverage}"
            if specific_reason:
                reason = f"{reason}:{specific_reason}"
            result = _unsupported_effect(
                effect,
                reason,
                {
                    "coverage_status": effect.coverage_status,
                    "effective_coverage": coverage,
                    "blocked_reason": specific_reason or _effect_blocked_reason(effect),
                },
            )
        else:
            result = handler(effect, context)
        if result.node_results:
            return result
        reason = ",".join(result.unsupported)
        return replace(
            result,
            node_results=(
                ExecutionNodeResult(
                    node_kind="effect",
                    node_id=effect.effect_id,
                    status="unsupported" if result.unsupported else "complete",
                    reason_code=reason,
                ),
            ),
        )

    def coverage(self, effect: EffectIR) -> str:
        if effect.opcode not in self._handlers:
            return effect.coverage_status
        if effect.coverage_status != "executable":
            return effect.coverage_status
        if effect.opcode == "AddModifier" and not _add_modifier_payload_is_executable(effect):
            return "blocked"
        if effect.opcode in {"RemoveModifier", "RemoveSelfModifier"} and not _remove_modifier_payload_is_executable(effect):
            return "blocked"
        if effect.opcode == "DispelStatus" and not _dispel_status_payload_is_executable(effect):
            return "blocked"
        if effect.opcode in {"Heal", "HealHP", "Shield", "InitShield", "StackShield", "ModifyShield", "ResourceDelta", "ModifySPNew"} and not _fixed_payload_is_executable(effect):
            return "blocked"
        if effect.opcode == "LoseHPByRatio" and not _hp_loss_ratio_payload_is_executable(effect):
            return "blocked"
        if effect.opcode in {"SetEnergyBarState", "SetMonsterEnergyBarState", "SetSummonerEnergyBarState"} and not _mechanism_bar_payload_is_executable(effect):
            return "blocked"
        if effect.opcode in {"DefineDynamicValue", "SetDynamicValue", "SetDynamicValueByAddValue", "SetDynamicValueByModifierValue"} and not _dynamic_value_payload_is_executable(effect):
            return "blocked"
        return "executable"

    def _execute_add_modifier(
        self,
        effect: EffectIR,
        context: EffectExecutionContext | None,
    ) -> EffectResult:
        if self.status_system is None:
            return EffectResult(unsupported=("AddModifier requires StatusSystem",))
        if context is None:
            return EffectResult(unsupported=("AddModifier requires EffectExecutionContext",))
        result = self.status_system.apply_add_modifier(
            context.state,
            effect,
            caster_id=context.caster_id,
            source_id=context.source_id,
            owner_id=context.owner_id,
            param_entity_id=context.param_entity_id,
            current_action_target_id=context.current_action_target_id,
            target_resolution=context.target_resolution,
            event_payload=context.event_payload,
            dynamic_values=context.dynamic_values,
            binding_sources=_binding_sources(context),
        )
        return EffectResult(
            events=result.events,
            mutations=result.mutations,
            rng_events=result.rng_events,
            records=result.records,
            unsupported=result.unsupported,
        )

    def _execute_remove_modifier(
        self,
        effect: EffectIR,
        context: EffectExecutionContext | None,
    ) -> EffectResult:
        if self.status_system is None:
            return _unsupported_effect(effect, "RemoveModifier requires StatusSystem")
        if context is None:
            return _unsupported_effect(effect, "RemoveModifier requires EffectExecutionContext")
        result = self.status_system.apply_remove_modifier(
            context.state,
            effect,
            caster_id=context.caster_id,
            source_id=context.source_id,
            owner_id=context.owner_id,
            param_entity_id=context.param_entity_id,
            current_action_target_id=context.current_action_target_id,
        )
        return EffectResult(
            events=result.events,
            mutations=result.mutations,
            rng_events=result.rng_events,
            records=result.records,
            unsupported=result.unsupported,
        )

    def _execute_dispel_status(
        self,
        effect: EffectIR,
        context: EffectExecutionContext | None,
    ) -> EffectResult:
        if self.status_system is None:
            return _unsupported_effect(effect, "DispelStatus requires StatusSystem")
        if context is None:
            return _unsupported_effect(effect, "DispelStatus requires EffectExecutionContext")
        result = self.status_system.apply_dispel_status(
            context.state,
            effect,
            caster_id=context.caster_id,
            source_id=context.source_id,
            owner_id=context.owner_id,
            param_entity_id=context.param_entity_id,
            current_action_target_id=context.current_action_target_id,
            target_resolution=context.target_resolution,
            event_payload=context.event_payload,
            dynamic_values=context.dynamic_values,
            binding_sources=_binding_sources(context),
        )
        return EffectResult(
            events=result.events,
            mutations=result.mutations,
            rng_events=result.rng_events,
            records=result.records,
            unsupported=result.unsupported,
        )

    def _execute_heal(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        return _execute_fixed_unit_delta(effect, context, kind="heal")

    def _execute_shield(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        return _execute_fixed_unit_delta(effect, context, kind="shield")

    def _execute_resource_delta(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        return _execute_fixed_unit_delta(effect, context, kind="resource_delta")

    def _execute_hp_loss_ratio(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        return _execute_hp_loss_ratio(effect, context)

    def _execute_mechanism_bar_state(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        return _execute_mechanism_bar_state(effect, context)

    def _execute_set_dynamic_value(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        return _execute_set_dynamic_value(effect, context)

    def _execute_define_dynamic_value(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        return _execute_set_dynamic_value(effect, context)

    def _execute_set_dynamic_value_by_add_value(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        return _execute_set_dynamic_value_by_add_value(effect, context)

    def _execute_set_dynamic_value_by_modifier_value(
        self,
        effect: EffectIR,
        context: EffectExecutionContext | None,
    ) -> EffectResult:
        return _execute_set_dynamic_value_by_modifier_value(effect, context)


def _add_modifier_payload_is_executable(effect: EffectIR) -> bool:
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return False
    modifier_name = standard.get("modifier_name")
    if not isinstance(modifier_name, str) or not modifier_name:
        return False
    if standard.get("target_expression_coverage_status") == "executable":
        return True
    return standard.get("target_alias") in SUPPORTED_ADD_MODIFIER_ALIASES


def _remove_modifier_payload_is_executable(effect: EffectIR) -> bool:
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return False
    has_modifier = isinstance(standard.get("modifier_name"), str) and bool(standard.get("modifier_name"))
    has_status = isinstance(standard.get("status_id"), str) and bool(standard.get("status_id"))
    return (has_modifier or has_status) and standard.get("target_alias") in SUPPORTED_EFFECT_TARGET_ALIASES


def _dispel_status_payload_is_executable(effect: EffectIR) -> bool:
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return False
    if standard.get("blocked_reason"):
        return False
    if standard.get("target_expression_coverage_status") == "executable":
        return True
    return standard.get("target_alias") in SUPPORTED_ADD_MODIFIER_ALIASES


def _fixed_payload_is_executable(effect: EffectIR) -> bool:
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return False
    if standard.get("blocked_reason"):
        return False
    if standard.get("target_alias") not in SUPPORTED_EFFECT_TARGET_ALIASES:
        return False
    if not _runtime_numeric_payload_is_executable(standard.get("amount", standard.get("delta"))):
        return False
    if effect.opcode in {"ResourceDelta", "ModifySPNew"}:
        return isinstance(standard.get("resource"), str) and bool(standard.get("resource"))
    return True


def _hp_loss_ratio_payload_is_executable(effect: EffectIR) -> bool:
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return False
    if standard.get("blocked_reason"):
        return False
    return (
        standard.get("target_alias") in SUPPORTED_EFFECT_TARGET_ALIASES
        and standard.get("ratio_type") in {"MaxHP", "CurrentHP"}
        and _runtime_numeric_payload_is_executable(standard.get("ratio"))
    )


def _mechanism_bar_payload_is_executable(effect: EffectIR) -> bool:
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return False
    return (
        standard.get("state") is not None
        or standard.get("active") is not None
        or _runtime_numeric_payload_is_executable(standard.get("current_count"))
        or _runtime_numeric_payload_is_executable(standard.get("max_count"))
    )


def _dynamic_value_payload_is_executable(effect: EffectIR) -> bool:
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return False
    dynamic_target_aliases = SUPPORTED_EFFECT_TARGET_ALIASES | {"LevelEntity"}
    if effect.opcode in {"DefineDynamicValue", "SetDynamicValue"}:
        return (
            standard.get("target_alias") in dynamic_target_aliases
            and isinstance(standard.get("value_name"), str)
            and bool(standard.get("value_name"))
            and _runtime_numeric_payload_is_executable(standard.get("value_expr"))
        )
    if effect.opcode == "SetDynamicValueByAddValue":
        return (
            standard.get("target_alias") in dynamic_target_aliases
            and isinstance(standard.get("value_name"), str)
            and bool(standard.get("value_name"))
            and _runtime_numeric_payload_is_executable(standard.get("add_value"))
        )
    if effect.opcode == "SetDynamicValueByModifierValue":
        return (
            standard.get("target_alias") in SUPPORTED_EFFECT_TARGET_ALIASES
            and standard.get("source_target_alias") in SUPPORTED_EFFECT_TARGET_ALIASES
            and isinstance(standard.get("source_modifier"), str)
            and bool(standard.get("source_modifier"))
            and standard.get("source_value_name") in {"Layer", "LifeTime"}
            and isinstance(standard.get("target_value_name"), str)
            and bool(standard.get("target_value_name"))
            and _runtime_numeric_payload_is_executable(standard.get("multiplier"))
        )
    return False


def _effect_blocked_reason(effect: EffectIR) -> str:
    standard = effect.payload.get("standard")
    if isinstance(standard, dict) and isinstance(standard.get("blocked_reason"), str):
        return standard["blocked_reason"]
    reason = effect.payload.get("blocked_reason")
    if isinstance(reason, str):
        return reason
    return ""


def _effect_payload_blocked_reason(effect: EffectIR) -> str:
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return "standard_payload_missing"
    blocked_reason = standard.get("blocked_reason")
    if isinstance(blocked_reason, str) and blocked_reason:
        return blocked_reason
    if effect.opcode == "AddModifier":
        modifier_name = standard.get("modifier_name")
        if not isinstance(modifier_name, str) or not modifier_name:
            return "modifier_name_missing"
        if standard.get("target_expression_coverage_status") == "executable":
            return ""
        target_expression_reason = standard.get("target_expression_blocked_reason")
        if isinstance(target_expression_reason, str) and target_expression_reason:
            return target_expression_reason
        if standard.get("target_alias") not in SUPPORTED_ADD_MODIFIER_ALIASES:
            return f"unsupported_or_missing_target_alias:{standard.get('target_alias')}"
    if effect.opcode in {"RemoveModifier", "RemoveSelfModifier"}:
        has_modifier = isinstance(standard.get("modifier_name"), str) and bool(standard.get("modifier_name"))
        has_status = isinstance(standard.get("status_id"), str) and bool(standard.get("status_id"))
        if not (has_modifier or has_status):
            return "modifier_name_or_status_id_missing"
        if standard.get("target_alias") not in SUPPORTED_EFFECT_TARGET_ALIASES:
            return f"unsupported_or_missing_target_alias:{standard.get('target_alias')}"
    if effect.opcode in {"Heal", "HealHP", "Shield", "InitShield", "StackShield", "ModifyShield", "ResourceDelta", "ModifySPNew"}:
        if standard.get("target_alias") not in SUPPORTED_EFFECT_TARGET_ALIASES:
            return f"unsupported_or_missing_target_alias:{standard.get('target_alias')}"
        if not _runtime_numeric_payload_is_executable(standard.get("amount", standard.get("delta"))):
            return "fixed_or_bound_numeric_required"
        if effect.opcode in {"ResourceDelta", "ModifySPNew"} and not isinstance(standard.get("resource"), str):
            return "resource_missing"
    if effect.opcode == "LoseHPByRatio":
        if standard.get("target_alias") not in SUPPORTED_EFFECT_TARGET_ALIASES:
            return f"unsupported_or_missing_target_alias:{standard.get('target_alias')}"
        if standard.get("ratio_type") not in {"MaxHP", "CurrentHP"}:
            return f"hp_loss_ratio_type_not_supported:{standard.get('ratio_type')}"
        if not _runtime_numeric_payload_is_executable(standard.get("ratio")):
            return "fixed_or_bound_ratio_required"
    if effect.opcode in {"DefineDynamicValue", "SetDynamicValue", "SetDynamicValueByAddValue"}:
        if standard.get("target_alias") not in SUPPORTED_EFFECT_TARGET_ALIASES | {"LevelEntity"}:
            return f"unsupported_or_missing_target_alias:{standard.get('target_alias')}"
        if not isinstance(standard.get("value_name"), str) or not standard.get("value_name"):
            return "dynamic_value_name_required"
        expr_key = "add_value" if effect.opcode == "SetDynamicValueByAddValue" else "value_expr"
        if not _runtime_numeric_payload_is_executable(standard.get(expr_key)):
            return "fixed_or_bound_dynamic_value_required"
    return _effect_blocked_reason(effect)


def _execute_fixed_unit_delta(
    effect: EffectIR,
    context: EffectExecutionContext | None,
    *,
    kind: str,
) -> EffectResult:
    if context is None:
        return _unsupported_effect(effect, f"{kind} requires EffectExecutionContext")
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return _unsupported_effect(effect, f"{kind} effect has no standardized payload")
    blocked_reason = standard.get("blocked_reason")
    if isinstance(blocked_reason, str) and blocked_reason:
        return _unsupported_effect(effect, f"unsupported_formula:{blocked_reason}", {"standard": standard})
    target_id = _resolve_target_alias(
        standard.get("target_alias"),
        caster_id=context.caster_id,
        owner_id=context.owner_id,
        param_entity_id=context.param_entity_id,
        current_action_target_id=context.current_action_target_id,
    )
    if target_id is None:
        return _unsupported_effect(effect, f"unsupported_or_missing_target_alias:{standard.get('target_alias')}")
    formula_blocked = _formula_type_blocked(effect, standard, kind)
    if formula_blocked:
        return _unsupported_effect(effect, formula_blocked, {"standard": standard})
    amount_result = _evaluate_numeric(effect, context, standard.get("amount", standard.get("delta")))
    if not amount_result.ok or amount_result.value is None:
        return _unsupported_effect(
            effect,
            f"unsupported_formula:{amount_result.blocked_reason or 'numeric_evaluation_failed'}",
            {"numeric_evaluation": amount_result.to_json(), "standard": standard},
        )
    amount, formula_details, formula_reason = _resolve_formula_amount(kind, context.state, standard, target_id, context.caster_id, amount_result.value)
    if formula_reason:
        return _unsupported_effect(
            effect,
            formula_reason,
            {"numeric_evaluation": amount_result.to_json(), "standard": standard},
        )
    state = context.state
    if kind == "resource_delta" and standard.get("resource") == "skill_points":
        operation = str(standard.get("operation") or "add")
        after_value = amount if operation == "set" else state.skill_points + amount
        after = max(0, min(state.max_skill_points, int(after_value)))
        mutation = Mutation(
            op="set",
            path=("skill_points",),
            before=state.skill_points,
            after=after,
            reason="apply numeric skill point delta effect",
            source="effect_system",
            metadata=_effect_metadata(effect, context, standard, amount, amount_result, formula_details=formula_details),
        )
        return _mutation_effect_result(
            effect,
            kind,
            mutation,
            amount,
            context=context,
            target_id=None,
            resource="skill_points",
            evaluation=amount_result,
        )
    if target_id not in state.units:
        return _unsupported_effect(effect, f"target unit {target_id!r} is not in state")
    unit = state.units[target_id]
    if kind == "heal":
        after = max(0.0, min(unit.max_hp, unit.hp + amount))
        mutation = Mutation(
            op="set",
            path=("units", target_id, "hp"),
            before=unit.hp,
            after=after,
            reason="apply numeric heal effect",
            source="effect_system",
            metadata=_effect_metadata(effect, context, standard, amount, amount_result, formula_details=formula_details),
        )
        return _mutation_effect_result(
            effect,
            kind,
            mutation,
            amount,
            context=context,
            target_id=target_id,
            evaluation=amount_result,
        )
    if kind == "shield":
        before = float(unit.resources.get("shield", 0.0))
        after = max(0.0, before + amount)
        mutation = Mutation(
            op="set",
            path=("units", target_id, "resources", "shield"),
            before=before if "shield" in unit.resources else None,
            after=after,
            reason="apply numeric shield effect",
            source="effect_system",
            before_exists="shield" in unit.resources,
            metadata=_effect_metadata(effect, context, standard, amount, amount_result, formula_details=formula_details),
        )
        return _mutation_effect_result(
            effect,
            kind,
            mutation,
            amount,
            context=context,
            target_id=target_id,
            resource="shield",
            evaluation=amount_result,
        )
    resource = standard.get("resource")
    if kind == "resource_delta" and resource == "energy":
        cap = unit.max_energy if unit.max_energy > 0 else unit.energy + amount
        after = max(0.0, min(cap, unit.energy + amount))
        mutation = Mutation(
            op="set",
            path=("units", target_id, "energy"),
            before=unit.energy,
            after=after,
            reason="apply numeric energy delta effect",
            source="effect_system",
            metadata=_effect_metadata(effect, context, standard, amount, amount_result, formula_details=formula_details),
        )
        return _mutation_effect_result(
            effect,
            kind,
            mutation,
            amount,
            context=context,
            target_id=target_id,
            resource="energy",
            evaluation=amount_result,
        )
    if kind == "resource_delta" and isinstance(resource, str) and resource:
        before = float(unit.resources.get(resource, 0.0))
        after = before + amount
        mutation = Mutation(
            op="set",
            path=("units", target_id, "resources", resource),
            before=before if resource in unit.resources else None,
            after=after,
            reason=f"apply numeric {resource} delta effect",
            source="effect_system",
            before_exists=resource in unit.resources,
            metadata=_effect_metadata(effect, context, standard, amount, amount_result, formula_details=formula_details),
        )
        return _mutation_effect_result(
            effect,
            kind,
            mutation,
            amount,
            context=context,
            target_id=target_id,
            resource=resource,
            evaluation=amount_result,
        )
    return _unsupported_effect(effect, f"unsupported_resource_delta:{resource}")


def _execute_hp_loss_ratio(effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
    if context is None:
        return _unsupported_effect(effect, "hp_loss_ratio requires EffectExecutionContext")
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return _unsupported_effect(effect, "hp_loss_ratio effect has no standardized payload")
    blocked_reason = standard.get("blocked_reason")
    if isinstance(blocked_reason, str) and blocked_reason:
        return _unsupported_effect(effect, f"unsupported_formula:{blocked_reason}", {"standard": standard})
    target_id = _resolve_target_alias(
        standard.get("target_alias"),
        caster_id=context.caster_id,
        owner_id=context.owner_id,
        param_entity_id=context.param_entity_id,
        current_action_target_id=context.current_action_target_id,
    )
    if target_id is None:
        return _unsupported_effect(effect, f"unsupported_or_missing_target_alias:{standard.get('target_alias')}", {"standard": standard})
    if target_id not in context.state.units:
        return _unsupported_effect(effect, f"target unit {target_id!r} is not in state", {"standard": standard})
    ratio_type = standard.get("ratio_type")
    if ratio_type not in {"MaxHP", "CurrentHP"}:
        return _unsupported_effect(effect, f"unsupported_formula:hp_loss_ratio_type_not_supported:{ratio_type}", {"standard": standard})
    ratio_result = _evaluate_numeric(effect, context, standard.get("ratio"))
    if not ratio_result.ok or ratio_result.value is None:
        return _unsupported_effect(
            effect,
            f"unsupported_formula:{ratio_result.blocked_reason or 'numeric_evaluation_failed'}",
            {"numeric_evaluation": ratio_result.to_json(), "standard": standard},
        )
    ratio = ratio_result.value
    if ratio < 0:
        return _unsupported_effect(effect, "unsupported_formula:hp_loss_ratio_negative", {"numeric_evaluation": ratio_result.to_json(), "standard": standard})
    target = context.state.units[target_id]
    base_hp = target.max_hp if ratio_type == "MaxHP" else target.hp
    amount = base_hp * ratio
    rounding_policy = "none"
    if standard.get("floor") is True:
        amount = float(math.floor(amount))
        rounding_policy = "floor_from_tbgd_flag"
    effect_source = effect.source.to_json()
    packet = DamagePacket(
        attacker_id=context.caster_id,
        target_id=target_id,
        attack_type=str(standard.get("attack_type") or "hp_loss"),
        damage_formula_family="hp_loss",
        amount=amount,
        damage_kind="hp_loss",
        element_type=str(standard.get("damage_type") or "") or None,
        source_frame=DamageSourceFrame(
            owner_id=context.caster_id,
            source_id=f"effect:{effect.effect_id}",
            source_kind="effect_damage",
            sequence_id=f"effect:{context.source_id}:{effect.effect_id}",
            target_id=target_id,
            can_continue_after_lethal=False,
            source_trace={"effect_id": effect.effect_id, "effect_source": effect_source},
        ),
        source_trace={"effect_id": effect.effect_id, "effect_source": effect_source},
        metadata={
            "effect_id": effect.effect_id,
            "opcode": effect.opcode,
            "source_id": context.source_id,
            "caster_id": context.caster_id,
            "damage_source_owner_id": context.caster_id,
            "damage_source_id": f"effect:{effect.effect_id}",
            "damage_source_kind": "effect_damage",
            "damage_sequence_id": f"effect:{context.source_id}:{effect.effect_id}",
            "can_continue_after_lethal": False,
            "standard": standard,
            "effect_source": effect_source,
            "numeric_evaluation": ratio_result.to_json(),
            "ratio": ratio,
            "ratio_type": str(ratio_type),
            "base_hp": base_hp,
            "rounding_policy": rounding_policy,
            "damage_formula_family": "hp_loss",
        },
    )
    return _damage_result_to_effect_result(
        DamageSystem().apply_packet(
            context.state,
            packet,
            window_ledger=context.damage_window_ledger,
        )
    )


def _damage_result_to_effect_result(result) -> EffectResult:
    return EffectResult(
        events=result.events,
        mutations=result.mutations,
        records=result.records,
        unsupported=tuple(result.errors),
    )


def _execute_mechanism_bar_state(effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
    if context is None:
        return _unsupported_effect(effect, "mechanism_bar_state requires EffectExecutionContext")
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return _unsupported_effect(effect, "mechanism_bar_state effect has no standardized payload")

    target_id = _resolve_target_alias(
        standard.get("target_alias"),
        caster_id=context.caster_id,
        owner_id=context.owner_id,
        param_entity_id=context.param_entity_id,
        current_action_target_id=context.current_action_target_id,
    )
    target_id = target_id or context.owner_id or context.caster_id
    state = context.state
    if target_id not in state.units:
        return _unsupported_effect(effect, f"target unit {target_id!r} is not in state")
    unit = state.units[target_id]
    before_bars = unit.flags.get("mechanism_bars", {})
    if not isinstance(before_bars, dict):
        before_bars = {}
    before = {str(key): value for key, value in before_bars.items()}
    bar_key = str(standard.get("bar_type") or effect.opcode)
    bar_state = dict(before.get(bar_key, {})) if isinstance(before.get(bar_key), dict) else {}
    for key in ("state", "active"):
        if standard.get(key) is not None:
            bar_state[key] = standard[key]
    numeric_evaluations: dict[str, JSONValue] = {}
    for key in ("current_count", "max_count"):
        result = _evaluate_numeric(effect, context, standard.get(key))
        numeric_evaluations[key] = result.to_json()
        if result.ok and result.value is not None:
            bar_state[key] = result.value
    if not bar_state:
        return _unsupported_effect(
            effect,
            "unsupported_formula:fixed_or_bound_mechanism_bar_state_or_count_required",
            {"numeric_evaluations": numeric_evaluations, "standard": standard},
        )
    after = {**before, bar_key: bar_state}
    mutation = Mutation(
        op="set",
        path=("units", target_id, "flags", "mechanism_bars"),
        before=before if "mechanism_bars" in unit.flags else None,
        after=after,
        reason="apply fixed mechanism bar state effect",
        source="effect_system",
        before_exists="mechanism_bars" in unit.flags,
        metadata={
            "effect_id": effect.effect_id,
            "opcode": effect.opcode,
            "source_id": context.source_id,
            "caster_id": context.caster_id,
            "standard": standard,
            "numeric_evaluations": numeric_evaluations,
            "effect_source": effect.source.to_json(),
        },
    )
    record = SettlementRecord(
        record_type="mechanism_bar_state",
        source="effect_system",
        mutation_id=mutation.stable_id(),
        process_only=False,
        payload={
            "effect_id": effect.effect_id,
            "opcode": effect.opcode,
            "target_id": target_id,
            "bar_key": bar_key,
            "path": list(mutation.path),
            "before": before,
            "after": after,
            "numeric_evaluations": numeric_evaluations,
        },
        trace={"effect_source": effect.source.to_json()},
    ).to_json()
    return EffectResult(mutations=(mutation,), records=(record,))


def _execute_set_dynamic_value(effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
    if context is None:
        return _unsupported_effect(effect, "dynamic_value_store requires EffectExecutionContext")
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return _unsupported_effect(effect, "SetDynamicValue effect has no standardized payload")
    target_id = _resolve_target_alias(
        standard.get("target_alias"),
        caster_id=context.caster_id,
        owner_id=context.owner_id,
        param_entity_id=context.param_entity_id,
        current_action_target_id=context.current_action_target_id,
    )
    if target_id is None:
        return _unsupported_effect(effect, f"unsupported_or_missing_target_alias:{standard.get('target_alias')}")
    if target_id != "level:global" and target_id not in context.state.units:
        return _unsupported_effect(effect, f"target unit {target_id!r} is not in state")
    value_name = standard.get("value_name")
    if not isinstance(value_name, str) or not value_name:
        return _unsupported_effect(effect, "dynamic_value_name_required", {"standard": standard})
    evaluation = _evaluate_numeric(effect, context, standard.get("value_expr"))
    if not evaluation.ok or evaluation.value is None:
        return _unsupported_effect(
            effect,
            f"unsupported_formula:{evaluation.blocked_reason or 'numeric_evaluation_failed'}",
            {"numeric_evaluation": evaluation.to_json(), "standard": standard},
        )
    return _dynamic_value_store_result(
        effect,
        context,
        target_id=target_id,
        value_name=value_name,
        value=evaluation.value,
        value_hash=standard.get("hash"),
        standard=standard,
        evaluation=evaluation,
        source_value={
            "kind": "value_expr",
            "expression": standard.get("value_expr"),
        },
    )


def _execute_set_dynamic_value_by_add_value(effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
    if context is None:
        return _unsupported_effect(effect, "dynamic_value_store requires EffectExecutionContext")
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return _unsupported_effect(effect, "SetDynamicValueByAddValue effect has no standardized payload")
    target_id = _resolve_target_alias(
        standard.get("target_alias"),
        caster_id=context.caster_id,
        owner_id=context.owner_id,
        param_entity_id=context.param_entity_id,
        current_action_target_id=context.current_action_target_id,
    )
    if target_id is None:
        return _unsupported_effect(effect, f"unsupported_or_missing_target_alias:{standard.get('target_alias')}")
    if target_id != "level:global" and target_id not in context.state.units:
        return _unsupported_effect(effect, f"target unit {target_id!r} is not in state")
    value_name = standard.get("value_name")
    if not isinstance(value_name, str) or not value_name:
        return _unsupported_effect(effect, "dynamic_value_name_required", {"standard": standard})
    add_value = _evaluate_numeric(effect, context, standard.get("add_value"))
    if not add_value.ok or add_value.value is None:
        return _unsupported_effect(
            effect,
            f"unsupported_formula:{add_value.blocked_reason or 'numeric_evaluation_failed'}",
            {"numeric_evaluation": add_value.to_json(), "standard": standard},
        )
    current_value, current_source = _current_dynamic_value(context, target_id, value_name)
    value = current_value + add_value.value
    min_value = _optional_numeric(effect, context, standard.get("min_value"))
    max_value = _optional_numeric(effect, context, standard.get("max_value"))
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return _dynamic_value_store_result(
        effect,
        context,
        target_id=target_id,
        value_name=value_name,
        value=value,
        value_hash=standard.get("hash"),
        standard=standard,
        evaluation=add_value,
        source_value={
            "kind": "add_value",
            "current_value": current_value,
            "current_source": current_source,
            "add_value": add_value.value,
            "min_value": min_value,
            "max_value": max_value,
        },
    )


def _execute_set_dynamic_value_by_modifier_value(effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
    if context is None:
        return _unsupported_effect(effect, "dynamic_value_store requires EffectExecutionContext")
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return _unsupported_effect(effect, "SetDynamicValueByModifierValue effect has no standardized payload")
    source_target_id = _resolve_target_alias(
        standard.get("source_target_alias"),
        caster_id=context.caster_id,
        owner_id=context.owner_id,
        param_entity_id=context.param_entity_id,
        current_action_target_id=context.current_action_target_id,
    )
    target_id = _resolve_target_alias(
        standard.get("target_alias"),
        caster_id=context.caster_id,
        owner_id=context.owner_id,
        param_entity_id=context.param_entity_id,
        current_action_target_id=context.current_action_target_id,
    )
    if source_target_id is None:
        return _unsupported_effect(effect, f"unsupported_or_missing_source_target_alias:{standard.get('source_target_alias')}")
    if target_id is None:
        return _unsupported_effect(effect, f"unsupported_or_missing_target_alias:{standard.get('target_alias')}")
    if source_target_id not in context.state.units or target_id not in context.state.units:
        return _unsupported_effect(effect, "source_or_target_unit_not_in_state", {"standard": standard})
    source_modifier = standard.get("source_modifier")
    if not isinstance(source_modifier, str) or not source_modifier:
        return _unsupported_effect(effect, "source_modifier_required", {"standard": standard})
    detail = find_status_detail(context.state, source_target_id, modifier_name=source_modifier)
    if detail is None:
        return _unsupported_effect(
            effect,
            "source_modifier_status_not_present",
            {"standard": standard, "source_target_id": source_target_id},
        )
    source_value, source_reason = _modifier_value(detail, standard.get("source_value_name"))
    if source_value is None:
        return _unsupported_effect(effect, source_reason, {"standard": standard, "source_status": detail})
    multiplier = _evaluate_numeric(effect, context, standard.get("multiplier"))
    if not multiplier.ok or multiplier.value is None:
        return _unsupported_effect(
            effect,
            f"unsupported_formula:{multiplier.blocked_reason or 'numeric_evaluation_failed'}",
            {"numeric_evaluation": multiplier.to_json(), "standard": standard},
        )
    target_value_name = standard.get("target_value_name")
    if not isinstance(target_value_name, str) or not target_value_name:
        return _unsupported_effect(effect, "target_value_name_required", {"standard": standard})
    return _dynamic_value_store_result(
        effect,
        context,
        target_id=target_id,
        value_name=target_value_name,
        value=source_value * multiplier.value,
        value_hash=standard.get("target_hash"),
        standard=standard,
        evaluation=multiplier,
        source_value={
            "kind": "modifier_value",
            "source_target_id": source_target_id,
            "source_modifier": source_modifier,
            "source_value_name": standard.get("source_value_name"),
            "source_value": source_value,
            "source_status_instance_id": detail.get("instance_id"),
        },
    )


def _dynamic_value_store_result(
    effect: EffectIR,
    context: EffectExecutionContext,
    *,
    target_id: str,
    value_name: str,
    value: float,
    value_hash: JSONValue,
    standard: dict[str, JSONValue],
    evaluation: NumericEvaluationResult,
    source_value: dict[str, JSONValue],
) -> EffectResult:
    before = store_from_state(context.state)
    source_detail = _find_effect_status_detail(context, target_id, effect)
    after = upsert_dynamic_value(
        before,
        scope=str(standard.get("status_scope") or "modifier_local"),
        owner_id=target_id,
        value=float(value),
        value_name=value_name,
        hash_key=value_hash if isinstance(value_hash, (str, int)) else None,
        status_id=str(source_detail.get("status_id")) if isinstance(source_detail, dict) else None,
        status_instance_id=str(source_detail.get("instance_id")) if isinstance(source_detail, dict) else None,
        effect_id=effect.effect_id,
        source_trace={"effect_id": effect.effect_id, "effect_source": effect.source.to_json()},
    )
    mutation = Mutation(
        op="set",
        path=("global_flags", "dynamic_value_store"),
        before=before if "dynamic_value_store" in context.state.global_flags else None,
        after=after,
        reason=f"apply {effect.opcode} dynamic value store write",
        source="effect_system",
        before_exists="dynamic_value_store" in context.state.global_flags,
        metadata={
            "effect_id": effect.effect_id,
            "opcode": effect.opcode,
            "source_id": context.source_id,
            "caster_id": context.caster_id,
            "target_id": target_id,
            "value_name": value_name,
            "hash": value_hash,
            "value": float(value),
            "standard": standard,
            "source_value": source_value,
            "numeric_evaluation": evaluation.to_json(),
            "effect_source": effect.source.to_json(),
        },
    )
    record = SettlementRecord(
        record_type="dynamic_value_store",
        source="effect_system",
        mutation_id=mutation.stable_id(),
        process_only=False,
        payload={
            "effect_id": effect.effect_id,
            "opcode": effect.opcode,
            "target_id": target_id,
            "value_name": value_name,
            "hash": value_hash,
            "value": float(value),
            "path": list(mutation.path),
            "source_value": source_value,
            "numeric_evaluation": evaluation.to_json(),
        },
        trace={"effect_source": effect.source.to_json()},
    ).to_json()
    status_mutation = _status_dynamic_value_mutation(
        context,
        target_id=target_id,
        source_detail=source_detail,
        value_name=value_name,
        value=float(value),
        value_hash=value_hash,
        effect=effect,
        evaluation=evaluation,
    )
    mutations = (status_mutation, mutation) if status_mutation is not None else (mutation,)
    records = (record,)
    if status_mutation is not None:
        records = (
            SettlementRecord(
                record_type="status_dynamic_value",
                source="effect_system",
                mutation_id=status_mutation.stable_id(),
                process_only=False,
                payload={
                    "effect_id": effect.effect_id,
                    "opcode": effect.opcode,
                    "target_id": target_id,
                    "status_instance_id": source_detail.get("instance_id") if isinstance(source_detail, dict) else "",
                    "modifier_name": source_detail.get("modifier_name") if isinstance(source_detail, dict) else "",
                    "value_name": value_name,
                    "hash": value_hash,
                    "value": float(value),
                    "numeric_evaluation": evaluation.to_json(),
                },
                trace={"effect_source": effect.source.to_json()},
            ).to_json(),
            record,
        )
    return EffectResult(mutations=mutations, records=records)


def _find_effect_status_detail(
    context: EffectExecutionContext,
    target_id: str,
    effect: EffectIR,
) -> dict[str, JSONValue] | None:
    if target_id not in context.state.units:
        return None
    direct = find_status_detail(context.state, target_id, modifier_name=effect.source.raw_id)
    if direct is not None:
        return direct
    unit = context.state.units[target_id]
    details = unit.flags.get("status_details", ())
    if not isinstance(details, (list, tuple)):
        return None
    matches: list[dict[str, JSONValue]] = []
    for detail in details:
        if not isinstance(detail, dict):
            continue
        source_trace = detail.get("source_trace")
        if not isinstance(source_trace, dict):
            continue
        modifier_definition = source_trace.get("modifier_definition")
        effect_source = source_trace.get("effect_source")
        paths = []
        if isinstance(modifier_definition, dict):
            paths.append(str(modifier_definition.get("source_path") or ""))
        if isinstance(effect_source, dict):
            paths.append(str(effect_source.get("source_path") or ""))
        if effect.source.source_path in paths:
            matches.append(detail)
    return matches[0] if len(matches) == 1 else None


def _status_dynamic_value_mutation(
    context: EffectExecutionContext,
    *,
    target_id: str,
    source_detail: dict[str, JSONValue] | None,
    value_name: str,
    value: float,
    value_hash: JSONValue,
    effect: EffectIR,
    evaluation: NumericEvaluationResult,
) -> Mutation | None:
    if source_detail is None or target_id not in context.state.units:
        return None
    unit = context.state.units[target_id]
    before_details = list(unit.flags.get("status_details", ()))
    updated_details: list[JSONValue] = []
    found = False
    for detail in before_details:
        if not isinstance(detail, dict) or detail.get("instance_id") != source_detail.get("instance_id"):
            updated_details.append(detail)
            continue
        found = True
        dynamic_values = dict(detail.get("dynamic_values") or {})
        by_name = dict(dynamic_values.get("__by_name") or {})
        by_hash = dict(dynamic_values.get("__by_hash") or {})
        dynamic_values[value_name] = float(value)
        by_name[value_name] = float(value)
        if isinstance(value_hash, (str, int)):
            by_hash[str(value_hash)] = float(value)
            dynamic_values[str(value_hash)] = float(value)
        dynamic_values["__by_name"] = by_name
        dynamic_values["__by_hash"] = by_hash
        evaluations = list(dynamic_values.get("__evaluations") or [])
        evaluations.append(
            {
                "name": value_name,
                "result": evaluation.to_json(),
                "source": {
                    "effect_id": effect.effect_id,
                    "opcode": effect.opcode,
                    "effect_source": effect.source.to_json(),
                },
            }
        )
        dynamic_values["__evaluations"] = evaluations
        updated_details.append({**detail, "dynamic_values": dynamic_values})
    if not found:
        return None
    return Mutation(
        op="set",
        path=("units", target_id, "flags", "status_details"),
        before=before_details if "status_details" in unit.flags else None,
        after=updated_details,
        reason=f"apply {effect.opcode} status dynamic value write",
        source="effect_system",
        before_exists="status_details" in unit.flags,
        metadata={
            "effect_id": effect.effect_id,
            "opcode": effect.opcode,
            "target_id": target_id,
            "status_instance_id": source_detail.get("instance_id"),
            "value_name": value_name,
            "hash": value_hash,
            "value": float(value),
            "numeric_evaluation": evaluation.to_json(),
            "effect_source": effect.source.to_json(),
        },
    )


def _modifier_value(detail: dict[str, JSONValue], value_name: object) -> tuple[float | None, str]:
    if value_name == "Layer":
        value = detail.get("stacks")
        return (float(value), "ok") if isinstance(value, (int, float)) else (None, "source_layer_not_numeric")
    if value_name == "LifeTime":
        for key in ("remaining_duration", "duration"):
            value = detail.get(key)
            if isinstance(value, (int, float)):
                return float(value), "ok"
        return None, "source_lifetime_not_numeric"
    return None, f"unsupported_modifier_value_type:{value_name}"


def _mutation_effect_result(
    effect: EffectIR,
    kind: str,
    mutation: Mutation,
    amount: float,
    *,
    context: EffectExecutionContext,
    target_id: str | None,
    resource: str | None = None,
    evaluation: NumericEvaluationResult | None = None,
) -> EffectResult:
    payload: dict[str, JSONValue] = {
        "effect_id": effect.effect_id,
        "opcode": effect.opcode,
        "amount": amount,
        "target_id": target_id,
        "resource": resource,
        "path": list(mutation.path),
        "before": mutation.before,
        "after": mutation.after,
    }
    if evaluation is not None:
        payload["numeric_evaluation"] = evaluation.to_json()
    record = SettlementRecord(
        record_type=kind,
        source="effect_system",
        mutation_id=mutation.stable_id(),
        process_only=False,
        payload=payload,
        trace={"effect_source": effect.source.to_json()},
    ).to_json()
    return EffectResult(
        events=events_for_mutation(
            mutation,
            actor_id=context.caster_id,
            source_id=context.source_id,
            event_index=context.state.event_index,
        ),
        mutations=(mutation,),
        records=(record,),
    )


def _unsupported_effect(effect: EffectIR, reason: str, details: dict[str, JSONValue] | None = None) -> EffectResult:
    payload: dict[str, JSONValue] = {"effect_id": effect.effect_id, "opcode": effect.opcode, "reason": reason}
    if details:
        payload.update(details)
    return EffectResult(
        records=(
            SettlementRecord(
                record_type="effect_unsupported",
                source="effect_system",
                process_only=True,
                payload=payload,
                trace={"effect_source": effect.source.to_json()},
            ).to_json(),
        ),
        unsupported=(reason,),
    )


def _effect_metadata(
    effect: EffectIR,
    context: EffectExecutionContext,
    standard: dict[str, JSONValue],
    amount: float,
    evaluation: NumericEvaluationResult | None = None,
    *,
    formula_details: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    metadata: dict[str, JSONValue] = {
        "effect_id": effect.effect_id,
        "opcode": effect.opcode,
        "source_id": context.source_id,
        "caster_id": context.caster_id,
        "standard": standard,
        "amount": amount,
        "effect_source": effect.source.to_json(),
    }
    if evaluation is not None:
        metadata["numeric_evaluation"] = evaluation.to_json()
    if formula_details:
        metadata["formula_details"] = formula_details
    return metadata


def _evaluate_numeric(
    effect: EffectIR,
    context: EffectExecutionContext,
    expression: object,
) -> NumericEvaluationResult:
    return RuleEvaluator().evaluate_numeric(
        expression,
        NumericEvaluationContext(
            dynamic_values=_numeric_bindings(context.dynamic_values),
            binding_sources=_binding_sources(context),
            source_trace={"effect_id": effect.effect_id, "effect_source": effect.source.to_json()},
        ),
    )


def _binding_sources(context: EffectExecutionContext) -> tuple[dict[str, JSONValue], ...]:
    unit_ids = tuple(
        unit_id
        for unit_id in (
            context.owner_id,
            context.caster_id,
            context.param_entity_id,
            context.current_action_target_id,
        )
        if isinstance(unit_id, str) and unit_id
    )
    status_sources = status_binding_sources(context.state, unit_ids)
    store_source = binding_source_from_store(context.state.global_flags.get("dynamic_value_store"))
    return (*status_sources, *context.binding_sources, store_source)


def _numeric_bindings(values: dict[str, float] | None) -> dict[str, float]:
    if not isinstance(values, dict):
        return {}
    bindings: dict[str, float] = {}
    for key, value in values.items():
        if isinstance(value, (int, float)):
            bindings[str(key)] = float(value)
    return bindings


def _current_dynamic_value(
    context: EffectExecutionContext,
    target_id: str,
    value_name: str,
) -> tuple[float, dict[str, JSONValue]]:
    sources = _binding_sources(context)
    for index, source in enumerate(sources):
        entries = source.get("entries")
        if not isinstance(entries, dict):
            continue
        by_name = source.get("by_name")
        keys = []
        if isinstance(by_name, dict) and value_name in by_name:
            indexed = by_name[value_name]
            keys = indexed if isinstance(indexed, list) else [indexed]
        for entry_key in keys:
            entry = entries.get(str(entry_key)) if isinstance(entry_key, str) else None
            if not isinstance(entry, dict):
                continue
            if str(entry.get("owner_id") or "") != target_id:
                continue
            value = entry.get("value")
            if isinstance(value, (int, float)):
                return float(value), {
                    "source_type": str(source.get("source_type") or f"binding_source:{index}"),
                    "entry_key": str(entry_key),
                    "entry": entry,
                }
    return 0.0, {"source_type": "implicit_zero_for_add_value_missing"}


def _optional_numeric(
    effect: EffectIR,
    context: EffectExecutionContext,
    expression: object,
) -> float | None:
    if expression is None:
        return None
    result = _evaluate_numeric(effect, context, expression)
    return result.value if result.ok and result.value is not None else None


def _formula_type_blocked(effect: EffectIR, standard: dict[str, JSONValue], kind: str) -> str:
    formula_type = standard.get("formula_type")
    if kind == "heal":
        if formula_type in {None, "", "HealByBaseValue", "HealByTargetMaxHP", "HealByHealerMaxHP"}:
            return ""
        return f"unsupported_formula:formula_type_not_supported:{formula_type}"
    if kind == "shield":
        if formula_type in {None, "", "ShieldByBaseValue", "ShieldByCasterMaxHP", "ShieldByCasterDefence", "ShieldByTargetMaxHP"}:
            return ""
        return f"unsupported_formula:formula_type_not_supported:{formula_type}"
    return ""


def _resolve_formula_amount(
    kind: str,
    state: BattleState,
    standard: dict[str, JSONValue],
    target_id: str | None,
    caster_id: str,
    raw_value: float,
) -> tuple[float, dict[str, JSONValue], str]:
    formula_type = standard.get("formula_type")
    formula_base = str(standard.get("formula_base") or "flat")
    details: dict[str, JSONValue] = {
        "formula_type": str(formula_type or ""),
        "amount_role": str(standard.get("amount_role") or "flat"),
        "formula_base": formula_base,
        "raw_value": raw_value,
    }
    if kind == "resource_delta":
        scale_basis = str(standard.get("scale_basis") or "flat")
        details["operation"] = str(standard.get("operation") or "add")
        details["scale_basis"] = scale_basis
        if scale_basis == "max_skill_points":
            details["base_value"] = state.max_skill_points
            return state.max_skill_points * raw_value, details, ""
        if scale_basis == "max_energy":
            if target_id is None:
                return 0.0, details, "unsupported_formula:resource_target_missing_for_max_energy"
            unit = state.units.get(target_id)
            if unit is None:
                return 0.0, details, f"unsupported_formula:resource_target_missing:{target_id}"
            details["base_value"] = unit.max_energy
            return unit.max_energy * raw_value, details, ""
        if scale_basis == "flat":
            details["base_value"] = 1.0
            return raw_value, details, ""
        return 0.0, details, f"unsupported_formula:resource_scale_basis_not_supported:{scale_basis}"
    if formula_base == "flat":
        details["base_value"] = 1.0
        return raw_value, details, ""
    if target_id is None:
        return 0.0, details, "unsupported_formula:formula_target_missing"
    target = state.units.get(target_id)
    caster = state.units.get(caster_id)
    if target is None:
        return 0.0, details, "unsupported_formula:formula_target_missing"
    if caster is None:
        return 0.0, details, "unsupported_formula:formula_caster_missing"
    if formula_base == "target.max_hp":
        details["base_value"] = target.max_hp
        return target.max_hp * raw_value, details, ""
    if formula_base == "caster.max_hp":
        details["base_value"] = caster.max_hp
        return caster.max_hp * raw_value, details, ""
    if formula_base == "caster.defense":
        details["base_value"] = caster.defense
        return caster.defense * raw_value, details, ""
    return 0.0, details, f"unsupported_formula:formula_base_not_supported:{formula_base}"


def _resolve_target_alias(
    alias: object,
    *,
    caster_id: str,
    owner_id: str | None,
    param_entity_id: str | None,
    current_action_target_id: str | None,
) -> str | None:
    if alias == "Caster":
        return caster_id
    if alias == "ModifierOwnerEntity":
        return owner_id or caster_id
    if alias == "ParamEntity":
        return param_entity_id
    if alias == "CurrentActionTarget":
        return current_action_target_id
    if alias == "LevelEntity":
        return "level:global"
    return None


def _fixed_amount(expr: object) -> float | None:
    if isinstance(expr, (int, float)):
        return float(expr)
    if isinstance(expr, dict) and expr.get("kind") == "fixed" and isinstance(expr.get("value"), (int, float)):
        return float(expr["value"])
    return None


def _runtime_numeric_payload_is_executable(expr: object) -> bool:
    if _fixed_amount(expr) is not None:
        return True
    return isinstance(expr, dict) and expr.get("kind") == "dynamic_hash" and expr.get("hash") is not None
