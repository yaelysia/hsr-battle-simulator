from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..core.model import BattleState, GameEvent, JSONValue, Mutation
from ..core.settlement import SettlementRecord
from ..rules.ir import EffectIR
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


EffectHandler = Callable[[EffectIR, EffectExecutionContext | None], EffectResult]


class EffectRegistry:
    """Opcode dispatcher for v8 EffectIR handlers."""

    def __init__(self, status_system: StatusSystem | None = None) -> None:
        self.status_system = status_system
        self._handlers: dict[str, EffectHandler] = {}
        if status_system is not None:
            self.register("AddModifier", self._execute_add_modifier)
            self.register("RemoveModifier", self._execute_remove_modifier)
        self.register("Heal", self._execute_heal)
        self.register("HealHP", self._execute_heal)
        self.register("Shield", self._execute_shield)
        self.register("InitShield", self._execute_shield)
        self.register("ResourceDelta", self._execute_resource_delta)

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
        if effect.opcode == "RemoveModifier" and not _remove_modifier_payload_is_executable(effect):
            return "blocked"
        if effect.opcode in {"Heal", "HealHP", "Shield", "InitShield", "ResourceDelta"} and not _fixed_payload_is_executable(effect):
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
    if _fixed_amount(standard.get("amount", standard.get("delta"))) is None:
        return False
    if effect.opcode == "ResourceDelta":
        return isinstance(standard.get("resource"), str) and bool(standard.get("resource"))
    return True


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
    amount = _fixed_amount(standard.get("amount", standard.get("delta")))
    if amount is None:
        return _unsupported_effect(effect, "unsupported_formula:fixed_amount_required")
    state = context.state
    if kind == "resource_delta" and standard.get("resource") == "skill_points":
        after = max(0, min(state.max_skill_points, state.skill_points + int(amount)))
        mutation = Mutation(
            op="set",
            path=("skill_points",),
            before=state.skill_points,
            after=after,
            reason="apply fixed skill point delta effect",
            source="effect_system",
            metadata=_effect_metadata(effect, context, standard, amount),
        )
        return _mutation_effect_result(effect, kind, mutation, amount, target_id=None, resource="skill_points")
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
            reason="apply fixed heal effect",
            source="effect_system",
            metadata=_effect_metadata(effect, context, standard, amount),
        )
        return _mutation_effect_result(effect, kind, mutation, amount, target_id=target_id)
    if kind == "shield":
        before = float(unit.resources.get("shield", 0.0))
        after = max(0.0, before + amount)
        mutation = Mutation(
            op="set",
            path=("units", target_id, "resources", "shield"),
            before=before,
            after=after,
            reason="apply fixed shield effect",
            source="effect_system",
            metadata=_effect_metadata(effect, context, standard, amount),
        )
        return _mutation_effect_result(effect, kind, mutation, amount, target_id=target_id, resource="shield")
    resource = standard.get("resource")
    if kind == "resource_delta" and resource == "energy":
        cap = unit.max_energy if unit.max_energy > 0 else unit.energy + amount
        after = max(0.0, min(cap, unit.energy + amount))
        mutation = Mutation(
            op="set",
            path=("units", target_id, "energy"),
            before=unit.energy,
            after=after,
            reason="apply fixed energy delta effect",
            source="effect_system",
            metadata=_effect_metadata(effect, context, standard, amount),
        )
        return _mutation_effect_result(effect, kind, mutation, amount, target_id=target_id, resource="energy")
    if kind == "resource_delta" and isinstance(resource, str) and resource:
        before = float(unit.resources.get(resource, 0.0))
        after = before + amount
        mutation = Mutation(
            op="set",
            path=("units", target_id, "resources", resource),
            before=before,
            after=after,
            reason=f"apply fixed {resource} delta effect",
            source="effect_system",
            metadata=_effect_metadata(effect, context, standard, amount),
        )
        return _mutation_effect_result(effect, kind, mutation, amount, target_id=target_id, resource=resource)
    return _unsupported_effect(effect, f"unsupported_resource_delta:{resource}")


def _mutation_effect_result(
    effect: EffectIR,
    kind: str,
    mutation: Mutation,
    amount: float,
    *,
    target_id: str | None,
    resource: str | None = None,
) -> EffectResult:
    record = SettlementRecord(
        record_type=kind,
        source="effect_system",
        mutation_id=mutation.stable_id(),
        process_only=False,
        payload={
            "effect_id": effect.effect_id,
            "opcode": effect.opcode,
            "amount": amount,
            "target_id": target_id,
            "resource": resource,
            "path": list(mutation.path),
            "before": mutation.before,
            "after": mutation.after,
        },
        trace={"effect_source": effect.source.to_json()},
    ).to_json()
    return EffectResult(mutations=(mutation,), records=(record,))


def _unsupported_effect(effect: EffectIR, reason: str) -> EffectResult:
    return EffectResult(
        records=(
            SettlementRecord(
                record_type="effect_unsupported",
                source="effect_system",
                process_only=True,
                payload={"effect_id": effect.effect_id, "opcode": effect.opcode, "reason": reason},
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
) -> dict[str, JSONValue]:
    return {
        "effect_id": effect.effect_id,
        "opcode": effect.opcode,
        "source_id": context.source_id,
        "caster_id": context.caster_id,
        "standard": standard,
        "amount": amount,
        "effect_source": effect.source.to_json(),
    }


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
