from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Callable

from ..core.model import BattleState, GameEvent, JSONValue, Mutation, RNGEvent, TargetResolution
from ..core.settlement import SettlementRecord
from ..core.transition_outcome import ExecutionNodeResult
from ..rules.evaluator import NumericEvaluationContext, NumericEvaluationResult, RuleEvaluator
from ..rules.expression_ir import DynamicValueOperationIR, is_typed_numeric_expression
from ..rules.ir import EffectIR
from ..rules.rulebook import RuleBook
from ..unit_presence import plan_unit_departure_start
from .damage import DamagePacket, DamageSourceFrame, DamageSystem, DamageWindowLedger
from .dynamic_values import (
    DynamicValueExecutionRequest,
    binding_source_from_store,
    execute_dynamic_value_plan,
    find_status_detail,
    plan_dynamic_value_operation,
    status_binding_sources,
    store_from_state,
    upsert_dynamic_value,
)
from .mutation_events import events_for_mutation
from .status import SUPPORTED_ADD_MODIFIER_ALIASES, SUPPORTED_EFFECT_TARGET_ALIASES, StatusSystem
from .shield import NORMAL_SHIELD_FAMILIES, ShieldSystem
from .target import TargetSystem
from .unit_relation import TargetEvaluationContext, committed_turn_owner_id
from .unit_stats import effective_unit_stat


@dataclass(frozen=True)
class EffectResult:
    events: tuple[GameEvent, ...] = ()
    mutations: tuple[Mutation, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    unsupported: tuple[str, ...] = ()
    node_results: tuple[ExecutionNodeResult, ...] = ()


@dataclass(frozen=True)
class PreHealDispatchResult:
    ok: bool
    after_state: BattleState
    heal_ratio: float = 0.0
    events: tuple[GameEvent, ...] = ()
    mutations: tuple[Mutation, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    errors: tuple[str, ...] = ()


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
    include_ambient_status_bindings: bool = True
    shadowed_status_instance_ids: tuple[str, ...] = ()
    damage_window_ledger: DamageWindowLedger | None = None


EffectHandler = Callable[[EffectIR, EffectExecutionContext | None], EffectResult]
PreHealDispatcher = Callable[
    [EffectIR, EffectExecutionContext],
    PreHealDispatchResult,
]


class EffectRegistry:
    """Opcode dispatcher for v8 EffectIR handlers."""

    def __init__(self, status_system: StatusSystem | None = None) -> None:
        self.status_system = status_system
        self.targets = status_system.targets if status_system is not None else None
        self.damage_system = DamageSystem(status_system.rules) if status_system is not None else DamageSystem()
        self.shield_system = ShieldSystem(self.damage_system.engine_rules)
        self._pre_heal_dispatcher: PreHealDispatcher | None = None
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
        self.register("RemoveShield", self._execute_remove_shield)
        self.register("ResourceDelta", self._execute_resource_delta)
        self.register("ModifySPNew", self._execute_resource_delta)
        self.register("ModifyTeamBoostPoint", self._execute_resource_delta)
        self.register("ModifyTeamBoostPointMax", self._execute_resource_delta)
        self.register("LoseHPByRatio", self._execute_hp_loss_ratio)
        self.register("SetEnergyBarState", self._execute_mechanism_bar_state)
        self.register("SetMonsterEnergyBarState", self._execute_mechanism_bar_state)
        self.register("SetSummonerEnergyBarState", self._execute_mechanism_bar_state)
        for opcode in (
            "DefineDynamicValue",
            "SetDynamicValue",
            "SetDynamicValueByAddValue",
            "SetDynamicValueByModifierValue",
        ):
            self.register(opcode, self._execute_dynamic_value_operation)
        self.register("OwnerEntityAddAbility", self._execute_owner_entity_add_ability)
        self.register("AttachEntityDeparted", self._execute_attach_entity_departed)
        self.register("TriggerModifierCustomEvent", self._execute_trigger_modifier_custom_event)
        self.register("StackWeakness", self._execute_stack_weakness)

    def register(self, opcode: str, handler: EffectHandler) -> None:
        self._handlers[opcode] = handler

    def set_pre_heal_dispatcher(
        self,
        dispatcher: PreHealDispatcher,
    ) -> None:
        self._pre_heal_dispatcher = dispatcher

    def execute(self, effect: EffectIR, context: EffectExecutionContext | None = None) -> EffectResult:
        handler = self._handlers.get(effect.opcode)
        if handler is None and _is_dynamic_value_effect(effect.opcode):
            handler = self._execute_dynamic_value_operation
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
            result = (
                _blocked_dynamic_value_effect(reason)
                if _is_dynamic_value_effect(effect.opcode)
                else _unsupported_effect(
                    effect,
                    reason,
                    {
                        "coverage_status": effect.coverage_status,
                        "effective_coverage": coverage,
                        "blocked_reason": specific_reason or _effect_blocked_reason(effect),
                    },
                )
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
        dynamic_operation = _dynamic_value_operation_spec(effect)
        if dynamic_operation is not None:
            return dynamic_operation.coverage_status
        if _is_dynamic_value_effect(effect.opcode):
            return "blocked"
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
        if effect.opcode in {"Heal", "HealHP", "Shield", "InitShield", "StackShield", "ModifyShield", "ResourceDelta", "ModifySPNew", "ModifyTeamBoostPoint", "ModifyTeamBoostPointMax"} and not _fixed_payload_is_executable(effect):
            return "blocked"
        if effect.opcode == "RemoveShield" and not _remove_shield_payload_is_executable(effect):
            return "blocked"
        if effect.opcode == "LoseHPByRatio" and not _hp_loss_ratio_payload_is_executable(effect):
            return "blocked"
        if effect.opcode in {"SetEnergyBarState", "SetMonsterEnergyBarState", "SetSummonerEnergyBarState"} and not _mechanism_bar_payload_is_executable(effect):
            return "blocked"
        if effect.opcode == "OwnerEntityAddAbility" and not _ability_attachment_payload_is_executable(effect):
            return "blocked"
        if effect.opcode == "AttachEntityDeparted" and not _entity_departure_payload_is_executable(effect):
            return "blocked"
        if effect.opcode == "TriggerModifierCustomEvent" and not _custom_event_payload_is_executable(effect):
            return "blocked"
        if effect.opcode == "StackWeakness" and not _stack_weakness_payload_is_executable(effect):
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
            target_resolution=context.target_resolution,
            event_payload=context.event_payload,
            dynamic_values=context.dynamic_values,
            binding_sources=_binding_sources(context),
        )
        # RemoveModifier / RemoveSelfModifier are idempotent at the ability
        # effect boundary.  Keep the lifecycle record for audit, but do not
        # turn the single well-known "already absent" outcome into a failed
        # callback.  Every other removal failure remains fail-closed.
        unsupported = (
            ()
            if result.unsupported == ("status_not_present",)
            else result.unsupported
        )
        return EffectResult(
            events=result.events,
            mutations=result.mutations,
            rng_events=result.rng_events,
            records=result.records,
            unsupported=unsupported,
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
        if context is None:
            return _execute_fixed_unit_delta(effect, context, kind="heal")
        payload = context.event_payload or {}
        if self._pre_heal_dispatcher is None or payload.get(
            "pre_heal_dispatch_active"
        ) is True:
            return _execute_fixed_unit_delta(effect, context, kind="heal")
        pre = self._pre_heal_dispatcher(effect, context)
        if not pre.ok:
            return EffectResult(
                events=pre.events,
                rng_events=pre.rng_events,
                records=pre.records,
                unsupported=pre.errors or ("pre_heal_dispatch_failed",),
            )
        heal_context = replace(
            context,
            state=pre.after_state,
            event_payload={
                **payload,
                "pre_heal_dispatch_active": True,
                "heal_modifier_ratio": pre.heal_ratio,
            },
        )
        healed = _execute_fixed_unit_delta(effect, heal_context, kind="heal")
        if healed.unsupported:
            return EffectResult(
                events=pre.events,
                rng_events=(*pre.rng_events, *healed.rng_events),
                records=(*pre.records, *healed.records),
                unsupported=healed.unsupported,
            )
        return EffectResult(
            events=(*pre.events, *healed.events),
            mutations=(*pre.mutations, *healed.mutations),
            rng_events=(*pre.rng_events, *healed.rng_events),
            records=(*pre.records, *healed.records),
        )

    def _execute_shield(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        return _execute_fixed_unit_delta(effect, context, kind="shield", shield_system=self.shield_system)

    def _execute_remove_shield(
        self,
        effect: EffectIR,
        context: EffectExecutionContext | None,
    ) -> EffectResult:
        return _execute_remove_shield(
            effect,
            context,
            shield_system=self.shield_system,
        )

    def _execute_resource_delta(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        return _execute_fixed_unit_delta(effect, context, kind="resource_delta")

    def _execute_hp_loss_ratio(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        return _execute_hp_loss_ratio(effect, context, damage_system=self.damage_system)

    def _execute_mechanism_bar_state(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        return _execute_mechanism_bar_state(effect, context)

    def _execute_dynamic_value_operation(
        self,
        effect: EffectIR,
        context: EffectExecutionContext | None,
    ) -> EffectResult:
        return _execute_dynamic_value_operation(effect, context)

    def _execute_owner_entity_add_ability(
        self,
        effect: EffectIR,
        context: EffectExecutionContext | None,
    ) -> EffectResult:
        return _execute_owner_entity_add_ability(effect, context)

    def _execute_attach_entity_departed(
        self,
        effect: EffectIR,
        context: EffectExecutionContext | None,
    ) -> EffectResult:
        return _execute_attach_entity_departed(effect, context)

    def _execute_trigger_modifier_custom_event(
        self,
        effect: EffectIR,
        context: EffectExecutionContext | None,
    ) -> EffectResult:
        rules = self.status_system.rules if self.status_system is not None else None
        return _execute_trigger_modifier_custom_event(
            effect, context, rules=rules, targets=self.targets
        )

    def _execute_stack_weakness(
        self,
        effect: EffectIR,
        context: EffectExecutionContext | None,
    ) -> EffectResult:
        rules = self.status_system.rules if self.status_system is not None else None
        return _execute_stack_weakness(
            effect, context, rules=rules, targets=self.targets
        )


def _add_modifier_payload_is_executable(effect: EffectIR) -> bool:
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return False
    modifier_name = standard.get("modifier_name")
    if not isinstance(modifier_name, str) or not modifier_name:
        return False
    return _typed_target_reference_admitted(standard)


def _remove_modifier_payload_is_executable(effect: EffectIR) -> bool:
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return False
    has_modifier = isinstance(standard.get("modifier_name"), str) and bool(standard.get("modifier_name"))
    has_status = isinstance(standard.get("status_id"), str) and bool(standard.get("status_id"))
    return (has_modifier or has_status) and _typed_target_reference_admitted(standard)


def _remove_shield_payload_is_executable(effect: EffectIR) -> bool:
    standard = effect.payload.get("standard")
    return bool(
        isinstance(standard, dict)
        and standard.get("removal_identity") == "current_status_instance"
        and _typed_target_reference_admitted(standard)
    )


def _dispel_status_payload_is_executable(effect: EffectIR) -> bool:
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return False
    if standard.get("blocked_reason"):
        return False
    return _typed_target_reference_admitted(standard)


def _typed_target_reference_admitted(standard: dict[str, JSONValue]) -> bool:
    return (
        isinstance(standard.get("target_expression_id"), str)
        and bool(standard.get("target_expression_id"))
        and standard.get("target_expression_coverage_status") == "executable"
    )


def _fixed_payload_is_executable(effect: EffectIR) -> bool:
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return False
    if standard.get("blocked_reason"):
        return False
    resource = standard.get("resource")
    team_resource = resource in {"skill_points", "max_skill_points"}
    if not team_resource and standard.get("target_alias") not in SUPPORTED_EFFECT_TARGET_ALIASES:
        return False
    if not _runtime_numeric_payload_is_executable(standard.get("amount", standard.get("delta"))):
        return False
    if effect.opcode in {
        "ResourceDelta",
        "ModifySPNew",
        "ModifyTeamBoostPoint",
        "ModifyTeamBoostPointMax",
    }:
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
    operation = _dynamic_value_operation_spec(effect)
    return operation is not None and operation.coverage_status == "executable"


def _dynamic_value_operation_spec(
    effect: EffectIR,
) -> DynamicValueOperationIR | None:
    standard = effect.payload.get("standard")
    spec = standard.get("dynamic_operation") if isinstance(standard, dict) else None
    if not isinstance(spec, dict):
        return None
    try:
        return DynamicValueOperationIR.from_spec(spec, effect.source)
    except (TypeError, ValueError):
        return None


def _is_dynamic_value_effect(opcode: object) -> bool:
    return isinstance(opcode, str) and (
        opcode in {"DefineDynamicValue", "SetModifierDynamicValue"}
        or opcode.startswith("SetDynamicValue")
    )


def _ability_attachment_payload_is_executable(effect: EffectIR) -> bool:
    standard = effect.payload.get("standard")
    return (
        isinstance(standard, dict)
        and standard.get("target_relation") == "status_owner_entity"
        and isinstance(standard.get("ability_name"), str)
        and bool(standard.get("ability_name"))
    )


def _entity_departure_payload_is_executable(effect: EffectIR) -> bool:
    standard = effect.payload.get("standard")
    return bool(
        isinstance(standard, dict)
        and standard.get("schema_version")
        == "hsr.entity_departure_attachment.v1"
        and standard.get("target_alias") == "ModifierOwnerEntity"
        and standard.get("target_source_mode")
        in {"explicit_target_expression", "opcode_omitted_modifier_owner"}
        and isinstance(standard.get("config_group_name"), str)
        and _typed_target_reference_admitted(standard)
    )


def _custom_event_payload_is_executable(effect: EffectIR) -> bool:
    standard = effect.payload.get("standard")
    return bool(
        isinstance(standard, dict)
        and not standard.get("blocked_reason")
        and _typed_target_reference_admitted(standard)
        and isinstance(standard.get("dynamic_key"), str)
        and standard.get("dynamic_key")
        and isinstance(standard.get("event_type"), (int, str))
        and not isinstance(standard.get("event_type"), bool)
        and _runtime_numeric_payload_is_executable(standard.get("value_expr"))
    )


def _stack_weakness_payload_is_executable(effect: EffectIR) -> bool:
    standard = effect.payload.get("standard")
    weaknesses = standard.get("weaknesses") if isinstance(standard, dict) else None
    return bool(
        isinstance(standard, dict)
        and not standard.get("blocked_reason")
        and standard.get("operation_type") == "Attach"
        and isinstance(weaknesses, list)
        and weaknesses
        and len(weaknesses) == len(set(weaknesses))
        and all(isinstance(item, str) and item for item in weaknesses)
        and _typed_target_reference_admitted(standard)
    )


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
    operation_spec = standard.get("dynamic_operation")
    if _is_dynamic_value_effect(effect.opcode) and _dynamic_value_operation_spec(effect) is None:
        return "typed_dynamic_value_operation_missing_or_invalid"
    if isinstance(operation_spec, dict):
        operation_reason = operation_spec.get("blocked_reason")
        if isinstance(operation_reason, str) and operation_reason:
            return operation_reason
    if effect.opcode == "AddModifier":
        modifier_name = standard.get("modifier_name")
        if not isinstance(modifier_name, str) or not modifier_name:
            return "modifier_name_missing"
        if _typed_target_reference_admitted(standard):
            return ""
        target_expression_reason = standard.get("target_expression_blocked_reason")
        if isinstance(target_expression_reason, str) and target_expression_reason:
            return target_expression_reason
        return "target_expression_id_missing_or_not_executable"
    if effect.opcode in {"RemoveModifier", "RemoveSelfModifier"}:
        has_modifier = isinstance(standard.get("modifier_name"), str) and bool(standard.get("modifier_name"))
        has_status = isinstance(standard.get("status_id"), str) and bool(standard.get("status_id"))
        if not (has_modifier or has_status):
            return "modifier_name_or_status_id_missing"
        if not _typed_target_reference_admitted(standard):
            return "target_expression_id_missing_or_not_executable"
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
        if "dynamic_result_name" in standard and (
            not isinstance(standard.get("dynamic_result_name"), str)
            or not standard.get("dynamic_result_name")
        ):
            return "hp_loss_dynamic_result_name_invalid"
    if effect.opcode in {"DefineDynamicValue", "SetDynamicValue", "SetDynamicValueByAddValue"}:
        if standard.get("target_alias") not in SUPPORTED_EFFECT_TARGET_ALIASES | {"LevelEntity"}:
            return f"unsupported_or_missing_target_alias:{standard.get('target_alias')}"
        if not isinstance(standard.get("value_name"), str) or not standard.get("value_name"):
            return "dynamic_value_name_required"
        expr_key = "add_value" if effect.opcode == "SetDynamicValueByAddValue" else "value_expr"
        if not _runtime_numeric_payload_is_executable(standard.get(expr_key)):
            return "fixed_or_bound_dynamic_value_required"
    if effect.opcode == "TriggerModifierCustomEvent":
        if not isinstance(standard.get("dynamic_key"), str) or not standard.get("dynamic_key"):
            return "custom_event_dynamic_key_required"
        if not isinstance(standard.get("event_type"), (int, str)) or isinstance(
            standard.get("event_type"), bool
        ):
            return "custom_event_type_required"
        if not _typed_target_reference_admitted(standard):
            return "custom_event_target_expression_missing_or_not_executable"
        if not _runtime_numeric_payload_is_executable(standard.get("value_expr")):
            return "custom_event_value_not_executable"
    return _effect_blocked_reason(effect)


def _execute_fixed_unit_delta(
    effect: EffectIR,
    context: EffectExecutionContext | None,
    *,
    kind: str,
    shield_system: ShieldSystem | None = None,
) -> EffectResult:
    if context is None:
        return _unsupported_effect(effect, f"{kind} requires EffectExecutionContext")
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return _unsupported_effect(effect, f"{kind} effect has no standardized payload")
    blocked_reason = standard.get("blocked_reason")
    if isinstance(blocked_reason, str) and blocked_reason:
        return _unsupported_effect(effect, f"unsupported_formula:{blocked_reason}", {"standard": standard})
    resource = standard.get("resource")
    team_resource = kind == "resource_delta" and resource in {
        "skill_points",
        "max_skill_points",
    }
    target_id = (
        context.owner_id or context.caster_id
        if team_resource
        else _resolve_target_alias(
            standard.get("target_alias"),
            caster_id=context.caster_id,
            owner_id=context.owner_id,
            param_entity_id=context.param_entity_id,
            current_action_target_id=context.current_action_target_id,
        )
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
    flat_addition_result = None
    if kind == "heal" and _runtime_numeric_payload_is_executable(
        standard.get("flat_addition")
    ):
        flat_addition_result = _evaluate_numeric(
            effect,
            context,
            standard.get("flat_addition"),
        )
        if not flat_addition_result.ok or flat_addition_result.value is None:
            return _unsupported_effect(
                effect,
                "unsupported_formula:heal_flat_addition_evaluation_failed",
                {
                    "numeric_evaluation": amount_result.to_json(),
                    "flat_addition_evaluation": flat_addition_result.to_json(),
                    "standard": standard,
                },
            )
        amount += float(flat_addition_result.value)
        formula_details["flat_addition"] = float(flat_addition_result.value)
    state = context.state
    if team_resource:
        return _team_resource_delta_result(
            effect,
            context,
            standard,
            amount,
            amount_result,
            formula_details,
        )
    if target_id not in state.units:
        return _unsupported_effect(effect, f"target unit {target_id!r} is not in state")
    unit = state.units[target_id]
    if kind == "heal":
        caster = state.units.get(context.caster_id)
        if caster is None:
            return _unsupported_effect(effect, "heal caster is not in state")
        outgoing = effective_unit_stat(caster, "outgoing_healing_ratio")
        incoming = effective_unit_stat(unit, "incoming_healing_ratio")
        transient_ratio_raw = (context.event_payload or {}).get(
            "heal_modifier_ratio",
            0.0,
        )
        transient_ratio = (
            float(transient_ratio_raw)
            if isinstance(transient_ratio_raw, (int, float))
            and not isinstance(transient_ratio_raw, bool)
            else 0.0
        )
        healing_multiplier = max(
            0.0,
            1.0 + outgoing.value + incoming.value + transient_ratio,
        )
        amount *= healing_multiplier
        formula_details["healing_multiplier"] = healing_multiplier
        formula_details["outgoing_healing_ratio"] = outgoing.to_json()
        formula_details["incoming_healing_ratio"] = incoming.to_json()
        formula_details["transient_heal_ratio"] = transient_ratio
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
        caster = state.units.get(context.caster_id)
        if caster is None:
            return _unsupported_effect(effect, "shield caster is not in state")
        shield_bonus = effective_unit_stat(caster, "shield_added_ratio")
        shield_multiplier = max(0.0, 1.0 + shield_bonus.value)
        amount *= shield_multiplier
        formula_details["shield_multiplier"] = shield_multiplier
        formula_details["shield_added_ratio"] = shield_bonus.to_json()
        effect_source = effect.source.to_json()
        raw_families = standard.get("absorb_families")
        absorb_families = (
            tuple(str(item) for item in raw_families if isinstance(item, str) and item)
            if isinstance(raw_families, list)
            else NORMAL_SHIELD_FAMILIES
        )
        raw_priority = standard.get("priority")
        priority = raw_priority if type(raw_priority) is int else 0
        priority_source = standard.get("priority_source")
        result = (shield_system or ShieldSystem()).apply_effect(
            state,
            target_id=target_id,
            shield_id=f"effect:{effect.effect_id}",
            source_id=effect.effect_id,
            source_kind="effect_ir",
            opcode=effect.opcode,
            amount=amount,
            source_trace={"effect_id": effect.effect_id, "effect_source": effect_source},
            actor_id=context.caster_id,
            event_source_id=context.source_id,
            priority=priority,
            priority_source=priority_source if isinstance(priority_source, dict) else None,
            absorb_families=absorb_families,
            owner_modifier_name=str(
                (context.event_payload or {}).get("modifier_name") or ""
            ),
            status_instance_id=str(
                (context.event_payload or {}).get("status_instance_id") or ""
            ),
            mutation_metadata=_effect_metadata(
                effect,
                context,
                standard,
                amount,
                amount_result,
                formula_details=formula_details,
            ),
        )
        if not result.ok or result.mutation is None:
            return _unsupported_effect(
                effect,
                result.blocked_reason or "shield_application_blocked",
                {"standard": standard, "numeric_evaluation": amount_result.to_json()},
            )
        return EffectResult(
            events=result.events,
            mutations=(result.mutation,),
            records=result.records,
        )
    if kind == "resource_delta" and resource == "energy":
        raw_amount = amount
        energy_regeneration = effective_unit_stat(
            unit,
            "energy_regeneration_rate",
        )
        energy_multiplier = (
            max(0.0, 1.0 + energy_regeneration.value)
            if raw_amount > 0.0
            else 1.0
        )
        amount = raw_amount * energy_multiplier
        formula_details["raw_energy_delta"] = raw_amount
        formula_details["energy_regeneration_multiplier"] = energy_multiplier
        formula_details["energy_regeneration_rate"] = (
            energy_regeneration.to_json()
        )
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


def _execute_remove_shield(
    effect: EffectIR,
    context: EffectExecutionContext | None,
    *,
    shield_system: ShieldSystem,
) -> EffectResult:
    if context is None:
        return _unsupported_effect(effect, "RemoveShield requires EffectExecutionContext")
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return _unsupported_effect(effect, "RemoveShield standardized payload missing")
    target_id = _resolve_target_alias(
        standard.get("target_alias"),
        caster_id=context.caster_id,
        owner_id=context.owner_id,
        param_entity_id=context.param_entity_id,
        current_action_target_id=context.current_action_target_id,
    )
    if target_id is None:
        return _unsupported_effect(
            effect,
            f"unsupported_or_missing_target_alias:{standard.get('target_alias')}",
        )
    event_payload = context.event_payload or {}
    owner_modifier_name = str(event_payload.get("modifier_name") or "")
    status_instance_id = str(event_payload.get("status_instance_id") or "")
    source_trace = {
        "effect_source": effect.source.to_json(),
        "status_instance_source": (
            event_payload.get("status_instance_source")
            if isinstance(event_payload.get("status_instance_source"), dict)
            else {}
        ),
    }
    result = shield_system.remove_status_instance_shields(
        context.state,
        target_id=target_id,
        owner_modifier_name=owner_modifier_name,
        status_instance_id=status_instance_id,
        actor_id=context.caster_id,
        event_source_id=context.source_id,
        source_trace=source_trace,
        mutation_metadata={
            "effect_id": effect.effect_id,
            "opcode": effect.opcode,
            "source_id": context.source_id,
            "caster_id": context.caster_id,
            "effect_source": effect.source.to_json(),
        },
    )
    if not result.ok or result.mutation is None:
        return _unsupported_effect(
            effect,
            result.blocked_reason or "shield_removal_blocked",
            {
                "target_id": target_id,
                "owner_modifier_name": owner_modifier_name,
                "status_instance_id": status_instance_id,
            },
        )
    return EffectResult(
        events=result.events,
        mutations=(result.mutation,),
        records=result.records,
    )


def _execute_hp_loss_ratio(
    effect: EffectIR,
    context: EffectExecutionContext | None,
    *,
    damage_system: DamageSystem | None = None,
) -> EffectResult:
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
        amount_stage="fixed_final",
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
    damage_result = (damage_system or DamageSystem()).apply_packet(
        context.state,
        packet,
        window_ledger=context.damage_window_ledger,
    )
    damage_effect_result = _damage_result_to_effect_result(damage_result)
    dynamic_result_name = standard.get("dynamic_result_name")
    if not isinstance(dynamic_result_name, str) or not dynamic_result_name:
        return damage_effect_result
    if not damage_result.ok:
        return damage_effect_result

    hp_mutations = tuple(
        mutation
        for mutation in damage_result.mutations
        if mutation.path == ("units", target_id, "hp")
    )
    if len(hp_mutations) > 1:
        return _unsupported_effect(
            effect,
            "hp_loss_dynamic_result_hp_mutation_ambiguous",
            {"standard": standard, "mutation_count": len(hp_mutations)},
        )
    before_hp = float(target.hp)
    after_hp = before_hp
    hp_mutation_id = ""
    if hp_mutations:
        hp_mutation = hp_mutations[0]
        if (
            not isinstance(hp_mutation.before, (int, float))
            or isinstance(hp_mutation.before, bool)
            or not isinstance(hp_mutation.after, (int, float))
            or isinstance(hp_mutation.after, bool)
            or float(hp_mutation.before) != before_hp
        ):
            return _unsupported_effect(
                effect,
                "hp_loss_dynamic_result_hp_mutation_invalid",
                {"standard": standard, "mutation": hp_mutation.to_json()},
            )
        after_hp = float(hp_mutation.after)
        hp_mutation_id = hp_mutation.stable_id()
    if target.max_hp <= 0:
        return _unsupported_effect(
            effect,
            "hp_loss_dynamic_result_max_hp_not_positive",
            {"standard": standard, "target_id": target_id},
        )
    actual_loss = max(0.0, before_hp - after_hp)
    applied_ratio = actual_loss / float(target.max_hp)
    dynamic_owner_id = context.owner_id or context.caster_id
    source_detail = _find_hp_loss_owner_status_detail(context, dynamic_owner_id, effect)
    dynamic_result_hash = _hp_loss_status_dynamic_hash(
        source_detail,
        dynamic_result_name,
    )
    if source_detail is None or dynamic_result_hash is None:
        return _unsupported_effect(
            effect,
            "hp_loss_dynamic_result_binding_missing",
            {
                "standard": standard,
                "dynamic_owner_id": dynamic_owner_id,
                "dynamic_result_name": dynamic_result_name,
            },
        )
    applied_ratio_evaluation = NumericEvaluationResult(
        ok=True,
        value=applied_ratio,
        expression_kind="applied_hp_loss_ratio",
        bindings={
            "target_id": target_id,
            "before_hp": before_hp,
            "after_hp": after_hp,
            "max_hp": float(target.max_hp),
            "actual_loss": actual_loss,
            "hp_mutation_id": hp_mutation_id,
        },
        source_trace={
            "effect_id": effect.effect_id,
            "effect_source": effect.source.to_json(),
            "hp_mutation_id": hp_mutation_id,
        },
    )
    dynamic_result = _hp_loss_dynamic_result(
        effect,
        context,
        target_id=dynamic_owner_id,
        value_name=dynamic_result_name,
        value=applied_ratio,
        value_hash=dynamic_result_hash,
        standard=standard,
        evaluation=applied_ratio_evaluation,
        source_value={
            "kind": "applied_hp_loss_ratio",
            "target_id": target_id,
            "before_hp": before_hp,
            "after_hp": after_hp,
            "max_hp": float(target.max_hp),
            "actual_loss": actual_loss,
            "hp_mutation_id": hp_mutation_id,
        },
    )
    if dynamic_result.unsupported:
        return dynamic_result
    return EffectResult(
        events=damage_effect_result.events + dynamic_result.events,
        mutations=damage_effect_result.mutations + dynamic_result.mutations,
        rng_events=damage_effect_result.rng_events + dynamic_result.rng_events,
        records=damage_effect_result.records + dynamic_result.records,
        node_results=damage_effect_result.node_results + dynamic_result.node_results,
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


def _execute_owner_entity_add_ability(
    effect: EffectIR,
    context: EffectExecutionContext | None,
) -> EffectResult:
    if context is None:
        return _unsupported_effect(effect, "OwnerEntityAddAbility requires EffectExecutionContext")
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return _unsupported_effect(effect, "OwnerEntityAddAbility effect has no standardized payload")
    ability_name = standard.get("ability_name")
    if not isinstance(ability_name, str) or not ability_name:
        return _unsupported_effect(effect, "owner entity ability name required", {"standard": standard})
    target_id = context.owner_id
    if not isinstance(target_id, str) or not target_id:
        return _unsupported_effect(effect, "status owner entity required", {"standard": standard})
    unit = context.state.units.get(target_id)
    if unit is None:
        return _unsupported_effect(effect, f"target unit {target_id!r} is not in state")
    registry_key = "attached_ability_names"
    raw_before = unit.flags.get(registry_key)
    if raw_before is None:
        before: list[str] = []
    elif isinstance(raw_before, (list, tuple)) and all(isinstance(item, str) and item for item in raw_before):
        before = list(raw_before)
    else:
        return _unsupported_effect(effect, "attached ability registry is malformed")
    if ability_name in before:
        record = SettlementRecord(
            record_type="owner_entity_ability_attachment",
            source="effect_system",
            process_only=True,
            payload={
                "effect_id": effect.effect_id,
                "target_id": target_id,
                "ability_name": ability_name,
                "already_attached": True,
            },
            trace={"effect_source": effect.source.to_json()},
        ).to_json()
        return EffectResult(records=(record,))
    after = [*before, ability_name]
    mutation = Mutation(
        op="set",
        path=("units", target_id, "flags", registry_key),
        before=before if registry_key in unit.flags else None,
        after=after,
        reason="attach canonical ability to status owner entity",
        source="effect_system",
        before_exists=registry_key in unit.flags,
        metadata={
            "effect_id": effect.effect_id,
            "opcode": effect.opcode,
            "source_id": context.source_id,
            "caster_id": context.caster_id,
            "target_id": target_id,
            "ability_name": ability_name,
            "effect_source": effect.source.to_json(),
        },
    )
    record = SettlementRecord(
        record_type="owner_entity_ability_attachment",
        source="effect_system",
        mutation_id=mutation.stable_id(),
        process_only=False,
        payload={
            "effect_id": effect.effect_id,
            "target_id": target_id,
            "ability_name": ability_name,
            "path": list(mutation.path),
            "before": before,
            "after": after,
        },
        trace={"effect_source": effect.source.to_json()},
    ).to_json()
    return EffectResult(mutations=(mutation,), records=(record,))


def _execute_attach_entity_departed(
    effect: EffectIR,
    context: EffectExecutionContext | None,
) -> EffectResult:
    if context is None:
        return _unsupported_effect(
            effect,
            "AttachEntityDeparted requires EffectExecutionContext",
        )
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return _unsupported_effect(
            effect,
            "AttachEntityDeparted effect has no standardized payload",
        )
    target_id = _resolve_target_alias(
        standard.get("target_alias"),
        caster_id=context.caster_id,
        owner_id=context.owner_id,
        param_entity_id=context.param_entity_id,
        current_action_target_id=context.current_action_target_id,
    )
    if not target_id or target_id not in context.state.units:
        return _unsupported_effect(
            effect,
            "entity departure target is missing",
            {"standard": standard},
        )
    event_payload = context.event_payload or {}
    status_instance_id = event_payload.get("status_instance_id")
    status_instance_source = event_payload.get("status_instance_source")
    if (
        not isinstance(status_instance_id, str)
        or not status_instance_id
        or not isinstance(status_instance_source, dict)
        or not status_instance_source
    ):
        return _unsupported_effect(
            effect,
            "entity departure requires a source-backed status instance",
            {"standard": standard},
        )
    source_trace: dict[str, JSONValue] = {
        "effect_id": effect.effect_id,
        "effect_source": effect.source.to_json(),
        "status_instance_id": status_instance_id,
        "status_instance_source": status_instance_source,
    }
    mutation_metadata: dict[str, JSONValue] = {
        "effect_id": effect.effect_id,
        "opcode": effect.opcode,
        "source_id": context.source_id,
        "caster_id": context.caster_id,
        "target_id": target_id,
        "standard": standard,
        "effect_source": effect.source.to_json(),
    }
    mutation, blocked_reason = plan_unit_departure_start(
        context.state,
        unit_id=target_id,
        source_status_instance_id=status_instance_id,
        source_effect_id=effect.effect_id,
        config_group_name=str(standard.get("config_group_name") or ""),
        source_trace=source_trace,
        mutation_source="effect_system",
        mutation_metadata=mutation_metadata,
    )
    if blocked_reason:
        return _unsupported_effect(
            effect,
            blocked_reason,
            {"target_id": target_id, "standard": standard},
        )
    if mutation is None:
        return EffectResult(
            records=(
                SettlementRecord(
                    record_type="unit_departure_attachment",
                    source="effect_system",
                    process_only=True,
                    payload={
                        "effect_id": effect.effect_id,
                        "target_id": target_id,
                        "status_instance_id": status_instance_id,
                        "already_attached": True,
                    },
                    trace=source_trace,
                ).to_json(),
            ),
        )
    record = SettlementRecord(
        record_type="unit_departure_attachment",
        source="effect_system",
        mutation_id=mutation.stable_id(),
        process_only=False,
        payload={
            "effect_id": effect.effect_id,
            "target_id": target_id,
            "status_instance_id": status_instance_id,
            "config_group_name": standard.get("config_group_name"),
            "path": list(mutation.path),
            "before": mutation.before,
            "after": mutation.after,
        },
        trace=source_trace,
    ).to_json()
    return EffectResult(
        events=events_for_mutation(
            mutation,
            actor_id=context.caster_id,
            source_id=context.source_id,
            event_index=context.state.event_index,
            extra_payload={
                "effect_id": effect.effect_id,
                "status_instance_id": status_instance_id,
                "source_trace": source_trace,
            },
        ),
        mutations=(mutation,),
        records=(record,),
    )


def _execute_trigger_modifier_custom_event(
    effect: EffectIR,
    context: EffectExecutionContext | None,
    *,
    rules: RuleBook | None,
    targets: TargetSystem | None,
) -> EffectResult:
    if context is None:
        return _unsupported_effect(
            effect,
            "TriggerModifierCustomEvent requires EffectExecutionContext",
        )
    if rules is None:
        return _unsupported_effect(
            effect,
            "TriggerModifierCustomEvent requires RuleBook-backed StatusSystem",
        )
    if targets is None:
        return _unsupported_effect(effect, "TriggerModifierCustomEvent target system missing")
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return _unsupported_effect(
            effect,
            "TriggerModifierCustomEvent effect has no standardized payload",
        )
    dynamic_key = standard.get("dynamic_key")
    event_type = standard.get("event_type")
    expression_id = standard.get("target_expression_id")
    if not isinstance(dynamic_key, str) or not dynamic_key:
        return _unsupported_effect(effect, "custom_event_dynamic_key_required")
    if not isinstance(event_type, (int, str)) or isinstance(event_type, bool):
        return _unsupported_effect(effect, "custom_event_type_required")
    if not isinstance(expression_id, str) or not expression_id:
        return _unsupported_effect(effect, "custom_event_target_expression_required")

    numeric = _evaluate_numeric(effect, context, standard.get("value_expr"))
    if not numeric.ok or numeric.value is None:
        return _unsupported_effect(
            effect,
            numeric.blocked_reason or "custom_event_value_not_resolved",
            {"numeric_evaluation": numeric.to_json()},
        )
    expression = rules.target_expression(expression_id)
    if expression is None:
        return _unsupported_effect(
            effect,
            f"custom_event_target_expression_missing:{expression_id}",
        )
    payload_alias = standard.get("target_alias")
    if (
        isinstance(payload_alias, str)
        and payload_alias
        and expression.alias
        and payload_alias != expression.alias
    ):
        return _unsupported_effect(
            effect,
            f"custom_event_target_expression_alias_mismatch:{payload_alias}:{expression.alias}",
        )
    target_result = targets.resolve_target_expression(
        context.state,
        expression,
        context=TargetEvaluationContext(
            caster_id=context.caster_id,
            effect_owner_id=context.owner_id,
            parameter_entity_ids=((context.param_entity_id,) if context.param_entity_id else ()),
            selected_target_ids=(
                tuple(context.target_resolution.selected)
                if context.target_resolution is not None and context.target_resolution.selected
                else ((context.current_action_target_id,) if context.current_action_target_id else ())
            ),
            current_target_id=context.current_action_target_id,
            turn_owner_id=committed_turn_owner_id(context.state),
        ),
        target_resolution=context.target_resolution,
        condition_event_payload=context.event_payload,
        dynamic_values=context.dynamic_values,
        binding_sources=_binding_sources(context),
    )
    if not target_result.resolved:
        return EffectResult(
            rng_events=target_result.rng_events,
            unsupported=(
                target_result.blocked_reason
                or "custom_event_target_resolution_failed",
            ),
            records=(
                SettlementRecord(
                    record_type="modifier_custom_event",
                    source="effect_system",
                    process_only=True,
                    payload={
                        "effect_id": effect.effect_id,
                        "status": "blocked",
                        "blocked_reason": target_result.blocked_reason,
                        "target_resolution": target_result.to_json(),
                        "numeric_evaluation": numeric.to_json(),
                    },
                    trace={"effect_source": effect.source.to_json()},
                ).to_json(),
            ),
        )

    events: list[GameEvent] = []
    records: list[dict[str, JSONValue]] = []
    for target_index, target_id in enumerate(target_result.target_ids):
        if target_id not in context.state.units:
            return _unsupported_effect(
                effect,
                f"custom_event_target_not_in_state:{target_id}",
                {"target_resolution": target_result.to_json()},
            )
        event = GameEvent(
            event_type="custom.event",
            source_id=context.caster_id,
            target_id=target_id,
            event_id=(
                f"event:{context.state.event_index}:modifier_custom:"
                f"{effect.effect_id}:{target_index}:{target_id}"
            ),
            window="OnCustomEvent",
            process_only=True,
            payload={
                "callback_events": ["OnCustomEvent"],
                "listener_scope": "owner_local",
                "custom_event_type": event_type,
                "custom_event_dynamic_key": dynamic_key,
                "custom_event_value": float(numeric.value),
                "param_value": float(numeric.value),
                "param_entity_id": target_id,
                "primary_target_id": target_id,
                "current_hit_target_id": target_id,
                "target_id": target_id,
                "producer_effect_id": effect.effect_id,
                "producer_source_id": context.source_id,
                "producer_effect_source": effect.source.to_json(),
                "numeric_evaluation": numeric.to_json(),
                "target_resolution": target_result.to_json(),
            },
        )
        events.append(event)
        records.append(
            SettlementRecord(
                record_type="modifier_custom_event",
                source="effect_system",
                process_only=True,
                payload={
                    "effect_id": effect.effect_id,
                    "event_id": event.event_id,
                    "event_type": event_type,
                    "dynamic_key": dynamic_key,
                    "value": float(numeric.value),
                    "target_id": target_id,
                    "target_index": target_index,
                    "target_resolution": target_result.to_json(),
                    "numeric_evaluation": numeric.to_json(),
                },
                trace={"effect_source": effect.source.to_json()},
            ).to_json()
        )
    if not events:
        records.append(
            SettlementRecord(
                record_type="modifier_custom_event",
                source="effect_system",
                process_only=True,
                payload={
                    "effect_id": effect.effect_id,
                    "event_type": event_type,
                    "dynamic_key": dynamic_key,
                    "value": float(numeric.value),
                    "target_count": 0,
                    "target_resolution": target_result.to_json(),
                    "numeric_evaluation": numeric.to_json(),
                },
                trace={"effect_source": effect.source.to_json()},
            ).to_json()
        )
    return EffectResult(
        events=tuple(events),
        rng_events=target_result.rng_events,
        records=tuple(records),
    )


def _execute_stack_weakness(
    effect: EffectIR,
    context: EffectExecutionContext | None,
    *,
    rules: RuleBook | None,
    targets: TargetSystem | None,
) -> EffectResult:
    if context is None:
        return _unsupported_effect(
            effect,
            "StackWeakness requires EffectExecutionContext",
        )
    if rules is None:
        return _unsupported_effect(
            effect,
            "StackWeakness requires RuleBook-backed StatusSystem",
        )
    if targets is None:
        return _unsupported_effect(effect, "StackWeakness target system missing")
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return _unsupported_effect(
            effect,
            "StackWeakness effect has no standardized payload",
        )
    if standard.get("operation_type") != "Attach":
        return _unsupported_effect(
            effect,
            f"stack_weakness_operation_not_admitted:{standard.get('operation_type') or 'missing'}",
        )
    weaknesses = standard.get("weaknesses")
    if (
        not isinstance(weaknesses, list)
        or not weaknesses
        or not all(isinstance(item, str) and item for item in weaknesses)
        or len(weaknesses) != len(set(weaknesses))
    ):
        return _unsupported_effect(effect, "stack_weakness_list_invalid")
    expression_id = standard.get("target_expression_id")
    if not isinstance(expression_id, str) or not expression_id:
        return _unsupported_effect(effect, "stack_weakness_target_expression_required")
    expression = rules.target_expression(expression_id)
    if expression is None:
        return _unsupported_effect(
            effect,
            f"stack_weakness_target_expression_missing:{expression_id}",
        )
    payload_alias = standard.get("target_alias")
    if (
        isinstance(payload_alias, str)
        and payload_alias
        and expression.alias
        and payload_alias != expression.alias
    ):
        return _unsupported_effect(
            effect,
            f"stack_weakness_target_expression_alias_mismatch:{payload_alias}:{expression.alias}",
        )
    target_result = targets.resolve_target_expression(
        context.state,
        expression,
        context=TargetEvaluationContext(
            caster_id=context.caster_id,
            effect_owner_id=context.owner_id,
            parameter_entity_ids=((context.param_entity_id,) if context.param_entity_id else ()),
            selected_target_ids=(
                tuple(context.target_resolution.selected)
                if context.target_resolution is not None and context.target_resolution.selected
                else ((context.current_action_target_id,) if context.current_action_target_id else ())
            ),
            current_target_id=context.current_action_target_id,
            turn_owner_id=committed_turn_owner_id(context.state),
        ),
        target_resolution=context.target_resolution,
        condition_event_payload=context.event_payload,
        dynamic_values=context.dynamic_values,
        binding_sources=_binding_sources(context),
    )
    if not target_result.resolved:
        return EffectResult(
            rng_events=target_result.rng_events,
            unsupported=(
                target_result.blocked_reason
                or "stack_weakness_target_resolution_failed",
            ),
        )

    prepared: list[tuple[str, tuple[str, ...], tuple[str, ...], bool]] = []
    for target_id in target_result.target_ids:
        unit = context.state.units.get(target_id)
        if unit is None:
            return _unsupported_effect(
                effect,
                f"stack_weakness_target_not_in_state:{target_id}",
            )
        raw_before = unit.flags.get("weaknesses")
        if raw_before is None:
            before: tuple[str, ...] = ()
            before_exists = False
        elif isinstance(raw_before, (list, tuple)) and all(
            isinstance(item, str) and item for item in raw_before
        ):
            before = tuple(raw_before)
            before_exists = True
        else:
            return _unsupported_effect(
                effect,
                f"stack_weakness_registry_malformed:{target_id}",
            )
        after = tuple(sorted({*before, *weaknesses}))
        prepared.append((target_id, before, after, before_exists))

    mutations: list[Mutation] = []
    records: list[dict[str, JSONValue]] = []
    events: list[GameEvent] = []
    for target_index, (target_id, before, after, before_exists) in enumerate(prepared):
        if after == before:
            records.append(
                SettlementRecord(
                    record_type="weakness_stack",
                    source="effect_system",
                    process_only=True,
                    payload={
                        "effect_id": effect.effect_id,
                        "target_id": target_id,
                        "weaknesses": list(weaknesses),
                        "already_attached": True,
                    },
                    trace={"effect_source": effect.source.to_json()},
                ).to_json()
            )
            continue
        mutation = Mutation(
            op="set",
            path=("units", target_id, "flags", "weaknesses"),
            before=before if before_exists else None,
            after=after,
            reason="attach source-backed weakness",
            source="effect_system",
            before_exists=before_exists,
            metadata={
                "effect_id": effect.effect_id,
                "opcode": effect.opcode,
                "source_id": context.source_id,
                "caster_id": context.caster_id,
                "target_id": target_id,
                "operation_type": "Attach",
                "weaknesses": list(weaknesses),
                "effect_source": effect.source.to_json(),
                "target_resolution": target_result.to_json(),
            },
        )
        mutations.append(mutation)
        events.extend(
            events_for_mutation(
                mutation,
                actor_id=context.caster_id,
                source_id=context.source_id,
                event_index=context.state.event_index + target_index,
                extra_payload={
                    "producer_effect_id": effect.effect_id,
                    "producer_effect_source": effect.source.to_json(),
                },
            )
        )
        records.append(
            SettlementRecord(
                record_type="weakness_stack",
                source="effect_system",
                mutation_id=mutation.stable_id(),
                process_only=False,
                payload={
                    "effect_id": effect.effect_id,
                    "target_id": target_id,
                    "weaknesses": list(weaknesses),
                    "before": list(before),
                    "after": list(after),
                    "target_resolution": target_result.to_json(),
                },
                trace={"effect_source": effect.source.to_json()},
            ).to_json()
        )
    return EffectResult(
        events=tuple(events),
        mutations=tuple(mutations),
        rng_events=target_result.rng_events,
        records=tuple(records),
    )


def _execute_dynamic_value_operation(
    effect: EffectIR,
    context: EffectExecutionContext | None,
) -> EffectResult:
    if context is None:
        return _blocked_dynamic_value_effect(
            "dynamic_value_operation requires EffectExecutionContext",
        )
    operation = _dynamic_value_operation_spec(effect)
    if operation is None:
        return _blocked_dynamic_value_effect("typed_dynamic_value_operation_missing")
    payload = context.event_payload or {}
    target_id = _resolve_target_alias(
        operation.target_alias,
        caster_id=context.caster_id,
        owner_id=context.owner_id,
        param_entity_id=context.param_entity_id,
        current_action_target_id=context.current_action_target_id,
    )
    status_instance_id = str(payload.get("status_instance_id") or "")
    if not status_instance_id and effect.owner_modifier_name and target_id in context.state.units:
        details = context.state.units[target_id].flags.get("status_details", ())
        candidates = tuple(
            str(detail.get("instance_id") or "")
            for detail in details
            if isinstance(detail, dict)
            and detail.get("modifier_name") == effect.owner_modifier_name
            and isinstance(detail.get("instance_id"), str)
            and detail.get("instance_id")
        ) if isinstance(details, (list, tuple)) else ()
        if len(candidates) > 1:
            return _blocked_dynamic_value_effect("dynamic_status_instance_ambiguous")
        status_instance_id = candidates[0] if candidates else ""
    selected_status_detail: dict[str, JSONValue] | None = None
    if status_instance_id and target_id in context.state.units:
        details = context.state.units[target_id].flags.get("status_details", ())
        matches = tuple(
            detail
            for detail in (details if isinstance(details, (list, tuple)) else ())
            if isinstance(detail, dict) and detail.get("instance_id") == status_instance_id
        )
        if len(matches) > 1:
            return _blocked_dynamic_value_effect("dynamic_status_instance_ambiguous")
        selected_status_detail = matches[0] if matches else None
    request = DynamicValueExecutionRequest(
        caster_id=context.caster_id,
        source_id=context.source_id,
        effect_id=effect.effect_id,
        opcode=effect.opcode,
        owner_id=context.owner_id or context.caster_id,
        param_entity_id=context.param_entity_id or "",
        current_action_target_id=context.current_action_target_id or "",
        ability_instance_id=str(payload.get("ability_instance_id") or ""),
        status_instance_id=status_instance_id,
        event_id=str(payload.get("event_id") or ""),
        operation_event_id=str(payload.get("operation_event_id") or ""),
        task_id=str(payload.get("task_id") or ""),
        status_modifier_name=effect.owner_modifier_name,
        status_id=str(
            payload.get("status_id")
            or (selected_status_detail or {}).get("status_id")
            or ""
        ),
        status_source_id=str(
            payload.get("status_source_id")
            or (selected_status_detail or {}).get("source_id")
            or ""
        ),
        binding_sources=_binding_sources(context),
    )
    plan = plan_dynamic_value_operation(context.state, operation, request)
    if not plan.ok:
        return _blocked_dynamic_value_effect(plan.blocked_reason)
    executed = execute_dynamic_value_plan(context.state, plan)
    if not executed.ok:
        return _blocked_dynamic_value_effect(executed.blocked_reason)
    return EffectResult(
        mutations=executed.mutations,
        records=tuple(dict(record) for record in executed.records),
    )


def _blocked_dynamic_value_effect(reason: str) -> EffectResult:
    return EffectResult(unsupported=(reason,))


def _hp_loss_dynamic_result(
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
    source_detail = _find_hp_loss_owner_status_detail(context, target_id, effect)
    resolved_value_hash = (
        value_hash
        if isinstance(value_hash, (str, int))
        else _hp_loss_status_dynamic_hash(source_detail, value_name)
    )
    after = upsert_dynamic_value(
        before,
        scope=str(standard.get("status_scope") or "modifier_local"),
        owner_id=target_id,
        value=float(value),
        value_name=value_name,
        hash_key=(
            resolved_value_hash
            if isinstance(resolved_value_hash, (str, int))
            else None
        ),
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
            "hash": resolved_value_hash,
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
            "hash": resolved_value_hash,
            "value": float(value),
            "path": list(mutation.path),
            "source_value": source_value,
            "numeric_evaluation": evaluation.to_json(),
        },
        trace={"effect_source": effect.source.to_json()},
    ).to_json()
    status_mutation = _hp_loss_status_dynamic_result_mutation(
        context,
        target_id=target_id,
        source_detail=source_detail,
        value_name=value_name,
        value=float(value),
        value_hash=resolved_value_hash,
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
                    "hash": resolved_value_hash,
                    "value": float(value),
                    "numeric_evaluation": evaluation.to_json(),
                },
                trace={"effect_source": effect.source.to_json()},
            ).to_json(),
            record,
        )
    return EffectResult(mutations=mutations, records=records)


def _hp_loss_status_dynamic_hash(
    source_detail: dict[str, JSONValue] | None,
    value_name: str,
) -> str | None:
    dynamic_values = (
        source_detail.get("dynamic_values")
        if isinstance(source_detail, dict)
        else None
    )
    definition_bindings = (
        dynamic_values.get("__definition_bindings")
        if isinstance(dynamic_values, dict)
        else None
    )
    by_hash = (
        definition_bindings.get("by_hash")
        if isinstance(definition_bindings, dict)
        else None
    )
    by_name = (
        definition_bindings.get("by_name")
        if isinstance(definition_bindings, dict)
        else None
    )
    named_binding = (
        by_name.get(value_name) if isinstance(by_name, dict) else None
    )
    named_hashes = (
        named_binding.get("hashes")
        if isinstance(named_binding, dict)
        else None
    )
    if isinstance(named_hashes, (list, tuple)):
        candidates = [
            str(item)
            for item in named_hashes
            if isinstance(item, (str, int))
        ]
        if len(candidates) == 1:
            return candidates[0]
    if not isinstance(by_hash, dict):
        return None
    candidates = [
        str(hash_key)
        for hash_key, binding in by_hash.items()
        if isinstance(binding, dict)
        and isinstance(binding.get("read_info"), dict)
        and str(binding["read_info"].get("Type") or "") == "None"
    ]
    return candidates[0] if len(candidates) == 1 else None


def _find_hp_loss_owner_status_detail(
    context: EffectExecutionContext,
    target_id: str,
    effect: EffectIR,
) -> dict[str, JSONValue] | None:
    if target_id not in context.state.units:
        return None
    if not effect.owner_modifier_name:
        return None
    return find_status_detail(context.state, target_id, modifier_name=effect.owner_modifier_name)


def _hp_loss_status_dynamic_result_mutation(
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


def _team_resource_delta_result(
    effect: EffectIR,
    context: EffectExecutionContext,
    standard: dict[str, JSONValue],
    amount: float,
    evaluation: NumericEvaluationResult,
    formula_details: dict[str, JSONValue],
) -> EffectResult:
    if not math.isfinite(amount) or not float(amount).is_integer():
        return _unsupported_effect(
            effect,
            "team_resource_delta_must_be_finite_integer",
            {"amount": amount, "standard": standard},
        )
    resource = str(standard.get("resource") or "")
    operation = str(standard.get("operation") or "add")
    if operation not in {"add", "set"}:
        return _unsupported_effect(
            effect,
            f"team_resource_operation_not_supported:{operation}",
            {"standard": standard},
        )
    state = context.state
    delta = int(amount)
    metadata = _effect_metadata(
        effect,
        context,
        standard,
        amount,
        evaluation,
        formula_details=formula_details,
    )
    mutations: list[Mutation] = []
    if resource == "skill_points":
        requested_after = delta if operation == "set" else state.skill_points + delta
        after = max(0, min(state.max_skill_points, requested_after))
        mutations.append(
            Mutation(
                op="set",
                path=("skill_points",),
                before=state.skill_points,
                after=after,
                reason="apply source-backed team skill point change",
                source="effect_system",
                metadata={
                    **metadata,
                    "resource": resource,
                    "unclamped_delta": (
                        delta if operation == "add" else requested_after - state.skill_points
                    ),
                    "requested_after": requested_after,
                },
            )
        )
    elif resource == "max_skill_points":
        requested_after = delta if operation == "set" else state.max_skill_points + delta
        after_maximum = max(0, requested_after)
        mutations.append(
            Mutation(
                op="set",
                path=("max_skill_points",),
                before=state.max_skill_points,
                after=after_maximum,
                reason="apply source-backed maximum team skill point change",
                source="effect_system",
                metadata={
                    **metadata,
                    "resource": resource,
                    "unclamped_delta": (
                        delta if operation == "add" else requested_after - state.max_skill_points
                    ),
                    "requested_after": requested_after,
                },
            )
        )
        if state.skill_points > after_maximum:
            mutations.append(
                Mutation(
                    op="set",
                    path=("skill_points",),
                    before=state.skill_points,
                    after=after_maximum,
                    reason="clamp team skill points to changed maximum",
                    source="effect_system",
                    metadata={
                        **metadata,
                        "resource": "skill_points",
                        "maximum_resource_mutation_id": mutations[0].stable_id(),
                    },
                )
            )
    else:
        return _unsupported_effect(
            effect,
            f"unsupported_team_resource_delta:{resource}",
            {"standard": standard},
        )
    events: list[GameEvent] = []
    records: list[dict[str, JSONValue]] = []
    for mutation in mutations:
        events.extend(
            events_for_mutation(
                mutation,
                actor_id=context.caster_id,
                source_id=context.source_id,
                event_index=state.event_index,
                extra_payload={
                    "param_entity_id": context.caster_id,
                    "unclamped_delta": mutation.metadata.get(
                        "unclamped_delta",
                        float(mutation.after) - float(mutation.before),
                    ),
                },
            )
        )
        records.append(
            SettlementRecord(
                record_type="resource_delta",
                source="effect_system",
                mutation_id=mutation.stable_id(),
                process_only=False,
                payload={
                    "effect_id": effect.effect_id,
                    "opcode": effect.opcode,
                    "resource": mutation.metadata.get("resource", resource),
                    "path": list(mutation.path),
                    "before": mutation.before,
                    "after": mutation.after,
                    "amount": amount,
                    "operation": operation,
                    "numeric_evaluation": evaluation.to_json(),
                },
                trace={"effect_source": effect.source.to_json()},
            ).to_json()
        )
    return EffectResult(
        events=tuple(events),
        mutations=tuple(mutations),
        records=tuple(records),
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
    shadowed_status_instance_ids = set(context.shadowed_status_instance_ids)
    status_sources = (
        tuple(
            source
            for source in status_binding_sources(context.state, unit_ids)
            if source.get("status_instance_id") not in shadowed_status_instance_ids
        )
        if context.include_ambient_status_bindings
        else ()
    )
    explicit_sources = (*status_sources, *context.binding_sources)
    shadowed_hashes = tuple(
        sorted(
            {
                str(key)
                for source in explicit_sources
                for key in (
                    source.get("by_hash", {}).keys()
                    if isinstance(source.get("by_hash"), dict)
                    else ()
                )
            }
        )
    )
    shadowed_names = tuple(
        sorted(
            {
                str(key)
                for source in explicit_sources
                for key in (
                    source.get("by_name", {}).keys()
                    if isinstance(source.get("by_name"), dict)
                    else ()
                )
            }
        )
    )
    store_source = binding_source_from_store(
        context.state.global_flags.get("dynamic_value_store"),
        excluded_status_instance_ids=tuple(
            sorted(shadowed_status_instance_ids)
        ),
        excluded_hashes=shadowed_hashes,
        excluded_names=shadowed_names,
    )
    return (*explicit_sources, store_source)


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
        if formula_type in {None, "", "HealByBaseValue", "HealByTargetLostHP", "HealByTargetMaxHP", "HealByHealerMaxHP"}:
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
    if formula_base == "target.lost_hp":
        lost_hp = max(0.0, target.max_hp - target.hp)
        details["base_value"] = lost_hp
        return lost_hp * raw_value, details, ""
    if formula_base == "caster.max_hp":
        details["base_value"] = caster.max_hp
        return caster.max_hp * raw_value, details, ""
    if formula_base == "caster.defense":
        effective_defense = effective_unit_stat(caster, "defense")
        details["base_value"] = effective_defense.value
        details["effective_stat"] = effective_defense.to_json()
        return effective_defense.value * raw_value, details, ""
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
    if not is_typed_numeric_expression(expr) or not isinstance(expr, dict):
        return False
    if expr.get("kind") == "dynamic_hash":
        return expr.get("hash") is not None
    return expr.get("kind") == "program" and expr.get("supported") is True
