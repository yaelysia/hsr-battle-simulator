from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..core.model import BattleState, GameEvent, JSONValue, Mutation
from ..core.settlement import SettlementRecord
from ..rules.evaluator import NumericEvaluationContext, NumericEvaluationResult, RuleEvaluator
from ..rules.ir import EffectIR
from .dynamic_values import (
    binding_source_from_store,
    find_status_detail,
    status_binding_sources,
    store_from_state,
    upsert_dynamic_value,
)
from .status import SUPPORTED_ADD_MODIFIER_ALIASES, StatusSystem


@dataclass(frozen=True)
class EffectResult:
    events: tuple[GameEvent, ...] = ()
    mutations: tuple[Mutation, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    unsupported: tuple[str, ...] = ()


@dataclass(frozen=True)
class EffectExecutionContext:
    state: BattleState
    caster_id: str
    source_id: str
    owner_id: str | None = None
    param_entity_id: str | None = None
    current_action_target_id: str | None = None
    dynamic_values: dict[str, float] | None = None
    binding_sources: tuple[dict[str, JSONValue], ...] = ()


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
        self.register("Heal", self._execute_heal)
        self.register("HealHP", self._execute_heal)
        self.register("Shield", self._execute_shield)
        self.register("InitShield", self._execute_shield)
        self.register("StackShield", self._execute_shield)
        self.register("ModifyShield", self._execute_shield)
        self.register("ResourceDelta", self._execute_resource_delta)
        self.register("ModifySPNew", self._execute_resource_delta)
        self.register("SetEnergyBarState", self._execute_mechanism_bar_state)
        self.register("SetMonsterEnergyBarState", self._execute_mechanism_bar_state)
        self.register("SetSummonerEnergyBarState", self._execute_mechanism_bar_state)
        self.register("SetDynamicValue", self._execute_set_dynamic_value)
        self.register("SetDynamicValueByModifierValue", self._execute_set_dynamic_value_by_modifier_value)

    def register(self, opcode: str, handler: EffectHandler) -> None:
        self._handlers[opcode] = handler

    def execute(self, effect: EffectIR, context: EffectExecutionContext | None = None) -> EffectResult:
        handler = self._handlers.get(effect.opcode)
        if not handler:
            return EffectResult(unsupported=(effect.opcode,))
        return handler(effect, context)

    def coverage(self, effect: EffectIR) -> str:
        if effect.opcode not in self._handlers:
            return effect.coverage_status
        if effect.coverage_status != "executable":
            return effect.coverage_status
        if effect.opcode == "AddModifier" and not _add_modifier_payload_is_executable(effect):
            return "blocked"
        if effect.opcode in {"RemoveModifier", "RemoveSelfModifier"} and not _remove_modifier_payload_is_executable(effect):
            return "blocked"
        if effect.opcode in {"Heal", "HealHP", "Shield", "InitShield", "StackShield", "ModifyShield", "ResourceDelta", "ModifySPNew"} and not _fixed_payload_is_executable(effect):
            return "blocked"
        if effect.opcode in {"SetEnergyBarState", "SetMonsterEnergyBarState", "SetSummonerEnergyBarState"} and not _mechanism_bar_payload_is_executable(effect):
            return "blocked"
        if effect.opcode in {"SetDynamicValue", "SetDynamicValueByModifierValue"} and not _dynamic_value_payload_is_executable(effect):
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
            dynamic_values=context.dynamic_values,
            binding_sources=_binding_sources(context),
        )
        return EffectResult(
            mutations=result.mutations,
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
            mutations=result.mutations,
            records=result.records,
            unsupported=result.unsupported,
        )

    def _execute_heal(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        return _execute_fixed_unit_delta(effect, context, kind="heal")

    def _execute_shield(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        return _execute_fixed_unit_delta(effect, context, kind="shield")

    def _execute_resource_delta(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        return _execute_fixed_unit_delta(effect, context, kind="resource_delta")

    def _execute_mechanism_bar_state(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        return _execute_mechanism_bar_state(effect, context)

    def _execute_set_dynamic_value(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        return _execute_set_dynamic_value(effect, context)

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
    return standard.get("target_alias") in SUPPORTED_ADD_MODIFIER_ALIASES


def _remove_modifier_payload_is_executable(effect: EffectIR) -> bool:
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return False
    has_modifier = isinstance(standard.get("modifier_name"), str) and bool(standard.get("modifier_name"))
    has_status = isinstance(standard.get("status_id"), str) and bool(standard.get("status_id"))
    return (has_modifier or has_status) and standard.get("target_alias") in SUPPORTED_ADD_MODIFIER_ALIASES


def _fixed_payload_is_executable(effect: EffectIR) -> bool:
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return False
    if standard.get("target_alias") not in SUPPORTED_ADD_MODIFIER_ALIASES:
        return False
    if not _runtime_numeric_payload_is_executable(standard.get("amount", standard.get("delta"))):
        return False
    if effect.opcode in {"ResourceDelta", "ModifySPNew"}:
        return isinstance(standard.get("resource"), str) and bool(standard.get("resource"))
    return True


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
    if effect.opcode == "SetDynamicValue":
        return (
            standard.get("target_alias") in SUPPORTED_ADD_MODIFIER_ALIASES
            and isinstance(standard.get("value_name"), str)
            and bool(standard.get("value_name"))
            and _runtime_numeric_payload_is_executable(standard.get("value_expr"))
        )
    if effect.opcode == "SetDynamicValueByModifierValue":
        return (
            standard.get("target_alias") in SUPPORTED_ADD_MODIFIER_ALIASES
            and standard.get("source_target_alias") in SUPPORTED_ADD_MODIFIER_ALIASES
            and isinstance(standard.get("source_modifier"), str)
            and bool(standard.get("source_modifier"))
            and standard.get("source_value_name") in {"Layer", "LifeTime"}
            and isinstance(standard.get("target_value_name"), str)
            and bool(standard.get("target_value_name"))
            and _runtime_numeric_payload_is_executable(standard.get("multiplier"))
        )
    return False


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
    amount = amount_result.value
    state = context.state
    if kind == "resource_delta" and standard.get("resource") == "skill_points":
        after = max(0, min(state.max_skill_points, state.skill_points + int(amount)))
        mutation = Mutation(
            op="set",
            path=("skill_points",),
            before=state.skill_points,
            after=after,
            reason="apply numeric skill point delta effect",
            source="effect_system",
            metadata=_effect_metadata(effect, context, standard, amount, amount_result),
        )
        return _mutation_effect_result(effect, kind, mutation, amount, target_id=None, resource="skill_points", evaluation=amount_result)
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
            metadata=_effect_metadata(effect, context, standard, amount, amount_result),
        )
        return _mutation_effect_result(effect, kind, mutation, amount, target_id=target_id, evaluation=amount_result)
    if kind == "shield":
        before = float(unit.resources.get("shield", 0.0))
        after = max(0.0, before + amount)
        mutation = Mutation(
            op="set",
            path=("units", target_id, "resources", "shield"),
            before=before,
            after=after,
            reason="apply numeric shield effect",
            source="effect_system",
            metadata=_effect_metadata(effect, context, standard, amount, amount_result),
        )
        return _mutation_effect_result(effect, kind, mutation, amount, target_id=target_id, resource="shield", evaluation=amount_result)
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
            metadata=_effect_metadata(effect, context, standard, amount, amount_result),
        )
        return _mutation_effect_result(effect, kind, mutation, amount, target_id=target_id, resource="energy", evaluation=amount_result)
    if kind == "resource_delta" and isinstance(resource, str) and resource:
        before = float(unit.resources.get(resource, 0.0))
        after = before + amount
        mutation = Mutation(
            op="set",
            path=("units", target_id, "resources", resource),
            before=before,
            after=after,
            reason=f"apply numeric {resource} delta effect",
            source="effect_system",
            metadata=_effect_metadata(effect, context, standard, amount, amount_result),
        )
        return _mutation_effect_result(effect, kind, mutation, amount, target_id=target_id, resource=resource, evaluation=amount_result)
    return _unsupported_effect(effect, f"unsupported_resource_delta:{resource}")


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
        before=before,
        after=after,
        reason="apply fixed mechanism bar state effect",
        source="effect_system",
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
    if target_id not in context.state.units:
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
    source_detail = find_status_detail(context.state, target_id, modifier_name=effect.source.raw_id)
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
        before=before,
        after=after,
        reason=f"apply {effect.opcode} dynamic value store write",
        source="effect_system",
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
    return EffectResult(mutations=(mutation,), records=(record,))


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
    return EffectResult(mutations=(mutation,), records=(record,))


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


def _formula_type_blocked(effect: EffectIR, standard: dict[str, JSONValue], kind: str) -> str:
    formula_type = standard.get("formula_type")
    if kind == "heal":
        if formula_type in {None, "", "HealByBaseValue"}:
            return ""
        return f"unsupported_formula:formula_type_not_supported:{formula_type}"
    if kind == "shield":
        if formula_type in {None, "", "ShieldByBaseValue"}:
            return ""
        return f"unsupported_formula:formula_type_not_supported:{formula_type}"
    return ""


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
