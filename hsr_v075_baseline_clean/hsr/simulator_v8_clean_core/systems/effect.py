from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from typing import Callable

from ..core.model import BattleState, GameEvent, JSONValue, Mutation, RNGEvent, TargetResolution, StatusImmunityFact, StatusLifecycleFact, current_max_hp, freeze_json
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..core.transition_outcome import ExecutionNodeResult
from ..rules.evaluator import NumericEvaluationContext, NumericEvaluationResult, RuleEvaluator
from ..rules.expression_ir import DynamicValueOperationIR, is_typed_numeric_expression
from ..rules.ir import ActionDefinitionIR, EffectIR
from ..rules.rulebook import RuleBook
from ..ir_types import IRSource
from ..unit_presence import plan_unit_departure_start
from .damage import DamagePacket, DamageSourceFrame, DamageSystem, DamageWindowLedger
from .dynamic_values import (
    DynamicValueExecutionRequest,
    _resolve_request_alias,
    resolve_operation_target,
    binding_source_from_store,
    binding_source_from_store_for_units,
    execute_dynamic_value_plan,
    find_status_detail,
    plan_dynamic_value_operation,
    status_binding_sources,
    store_from_state,
    upsert_dynamic_value,
)
from .elation import elation_effect_is_executable, execute_elation_operation
from .mutation_events import events_for_mutation
from .action_event_contract import AdmittedActionTargetFact, ActionWindowExpectedScope
from .status import SUPPORTED_ADD_MODIFIER_ALIASES, SUPPORTED_EFFECT_TARGET_ALIASES, StatusApplicationResult, StatusLifecyclePlan, StatusSystem, remove_self_intrinsic_target_admitted
from .shield import NORMAL_SHIELD_FAMILIES, ShieldExhaustionFact, ShieldSystem
from .skill_properties import effective_action_property
from .target import TargetSystem
from .timeline import TimelineSystem
from .unit_relation import EntityRelationResolver, TargetEvaluationContext, committed_turn_owner_id
from .unit_stats import effective_unit_stat
from .unit_lifecycle import UnitLifecycleSystem
from .task_graph import TaskGraphContinuation, TaskGraphStatusScope


# Plans whose OnModifierAdd notification names a still-live instance. Remove-like
# plans never supply the typed triggering fact to the precision path.
_CALLBACK_TRIGGERING_OPERATIONS = frozenset({
    "add", "replace", "refresh", "refresh_or_replace_partial", "replace_partial",
    "stack", "stack_refresh",
})


@dataclass(frozen=True)
class EffectResult:
    events: tuple[GameEvent, ...] = ()
    mutations: tuple[Mutation, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    unsupported: tuple[str, ...] = ()
    node_results: tuple[ExecutionNodeResult, ...] = ()
    dispatched_event_ids: frozenset[str] = frozenset()
    created_unit_ids: tuple[str, ...] = ()


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
    dispatched_event_ids: frozenset[str] = frozenset()


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
    # Typed producer fact for an admitted heal mutation.  Event-value operands
    # read this fact; the transport payload alone never authorizes an amount.
    heal_event_fact: "HealEventFact" = None  # type: ignore[assignment]
    trigger_event: GameEvent | None = None
    # Formal final-death identity travelling with a Deathrattle consumer. Only
    # the producer of the committed unit.defeated fact may populate it; a
    # generic event payload or audit trace is not a substitute.
    death_instance_id: str = ""
    dynamic_values: dict[str, float] | None = None
    binding_sources: tuple[dict[str, JSONValue], ...] = ()
    include_ambient_status_bindings: bool = True
    shadowed_status_instance_ids: tuple[str, ...] = ()
    damage_window_ledger: DamageWindowLedger | None = None
    admitted_action_target_fact: AdmittedActionTargetFact | None = None
    expected_action_window_scope: ActionWindowExpectedScope | None = None
    shield_exhaustion_fact: ShieldExhaustionFact | None = None
    status_lifecycle_fact: StatusLifecycleFact | None = None
    action_definition: ActionDefinitionIR | None = None
    heal_ratio_delta: float = 0.0
    ability_instance_id: str = ""
    status_lifecycle_plan: StatusLifecyclePlan | None = None
    param_status_scope: TaskGraphStatusScope | None = None
    template_target_ids: tuple[str, ...] | None = None
    task_graph_continuation: TaskGraphContinuation | None = None
    application_instance_id: str = ""
    include_heal_snapshot_protocol: bool = False


@dataclass(frozen=True)
class EffectExecutionFact:
    """Native state-effect invocation, retained for audit only, never serialized."""
    effect_id: str
    context: EffectExecutionContext

    def __post_init__(self) -> None:
        if not self.effect_id or type(self.context) is not EffectExecutionContext:
            raise TypeError("effect fact requires a native invocation")
        context = self.context
        object.__setattr__(self, "context", replace(context,
            event_payload=freeze_json(context.event_payload) if context.event_payload is not None else None,
            dynamic_values=freeze_json(context.dynamic_values) if context.dynamic_values is not None else None,
            binding_sources=tuple(freeze_json(source) for source in context.binding_sources),
        ))


def effect_requires_native_fact(effect: EffectIR | None) -> bool:
    return effect is not None and (
        _is_dynamic_value_effect(effect.opcode) or effect.opcode in {
            "CreateServant", "SetControlSkillMapping", "AutoUseUltraSkill", "ModifySP", "ModifySpecialSP",
            "ModifySpecialSPRatio", "ModifySpecialSPAddValue", "ModifyProperty",
            "LockActionDelayChange", "LockActionDelayChangeExceptTurnAdvance",
            "SetEnergyBarState", "SetMonsterEnergyBarState", "SetSummonerEnergyBarState", "SetNamedBooleanFlag",
        }
    )


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
            self.register("SetModifierValueByBehaviorFlag", self._execute_modifier_lifetime)
            self.register("SetModifierValue", self._execute_modifier_value)
            self.register("InfectModifier", self._execute_infect_modifier)
            self.register("ModifySkillPropertyByType", self._execute_modify_skill_property)
        self.register("SetNamedBooleanFlag", self._execute_named_boolean_flag)
        self.register("SetHP", self._execute_set_hp)
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
        self.register("LoseHP", self._execute_hp_loss_ratio)
        self.register("TriggerSkipDeadHandler", self._execute_death_settlement_barrier)
        self.register("SetEnergyBarState", self._execute_mechanism_bar_state)
        self.register("SetMonsterEnergyBarState", self._execute_mechanism_bar_state)
        self.register("SetSummonerEnergyBarState", self._execute_mechanism_bar_state)
        for opcode in (
            "DefineDynamicValue",
            "SetDynamicValue",
            "SetDynamicValueByAddValue",
            "SetDynamicValueByModifierValue",
            "SetDynamicValueByCharacterCount",
        ):
            self.register(opcode, self._execute_dynamic_value_operation)
        self.register("OwnerEntityAddAbility", self._execute_owner_entity_add_ability)
        self.register("AttachEntityDeparted", self._execute_attach_entity_departed)
        self.register(
            "AttachEntityUnselectable",
            self._execute_attach_entity_unselectable,
        )
        self.register("AddRegardAsAttackType", self._execute_regard_attack_type)
        self.register("ClearRegardAsAttackType", self._execute_regard_attack_type)
        self.register("TriggerModifierCustomEvent", self._execute_trigger_modifier_custom_event)
        self.register("StackWeakness", self._execute_stack_weakness)
        self.register("CreateServant", self._execute_create_servant)
        self.register("CreateBattleEvent", self._execute_create_battle_event)
        self.register("ChangeBattleEventOwner", self._execute_change_battle_event_owner)
        self.register("ModifyActionDelay", self._execute_modify_action_delay)
        self.register("ForceKill", self._execute_force_kill)
        self.register("SetDieImmediately", self._execute_finish_retirement)
        self.register("LockActionDelayChange", self._execute_action_delay_lock)
        self.register(
            "ProcessModifierLifeStep",
            self._execute_process_modifier_life_step,
        )
        self.register("AutoUseUltraSkill", self._execute_auto_use_ultra_skill)
        self.register("ModifyProperty", self._execute_modify_unit_property)
        self.register("ModifySP", self._execute_modify_special_sp)
        self.register(
            "ModifySpecialSP",
            self._execute_modify_special_sp_pool,
        )
        self.register(
            "SwitchByCommandType",
            self._execute_command_type_switch_marker,
        )
        self.register("SetControlSkillMapping", self._execute_control_skill_mapping)
        self.register("StackStatusResistance", self._execute_stack_status_resistance)
        self.register("SetActionDelay", self._execute_set_action_delay)
        self.register("SetActionDelayNearTarget", self._execute_set_action_delay_near_target)
        self.register("StackCustomUnselectable", _execute_stack_custom_unselectable)
        self.register("ReinitProperty", self._execute_reinit_property)
        self.register("LockTargetHP", self._execute_lock_target_hp)
        self.register("UnlockTargetHP", self._execute_unlock_target_hp)
        self.register("ExitBreakState", self._execute_exit_break_state)
        self.register("ModifyCurrentSkillDelayCost", self._execute_current_skill_delay_cost)
        self.register("ElationOperation", self._execute_elation_operation)

    def register(self, opcode: str, handler: EffectHandler) -> None:
        self._handlers[opcode] = handler

    def _execute_named_boolean_flag(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        from .named_boolean_flags import FLAG_FIELD, read_named_flag, resolve_named_key
        standard = effect.payload.get("standard", {})
        if context is None or self.status_system is None or standard.get("operation") != "set_named_boolean_flag" or standard.get("blocked_reason") or type(standard.get("value")) is not bool:
            return _unsupported_effect(effect, "named_boolean_context_or_definition_missing")
        target_id = _resolve_target_alias(standard.get("target_alias"), caster_id=context.caster_id,
            owner_id=context.owner_id, param_entity_id=context.param_entity_id,
            current_action_target_id=context.current_action_target_id, state=context.state,
            target_resolution=context.target_resolution)
        if standard.get("target_expression_id"):
            expression = self.status_system.rules.target_expression(standard["target_expression_id"])
            if expression is None:
                return _unsupported_effect(effect, "named_boolean_target_expression_missing")
            resolved = self.targets.resolve_target_expression(context.state, expression,
                context=TargetEvaluationContext(caster_id=context.caster_id, effect_owner_id=context.owner_id,
                    parameter_entity_ids=((context.param_entity_id,) if context.param_entity_id else ()),
                    selected_target_ids=context.target_resolution.selected if context.target_resolution else (),
                    current_target_id=context.current_action_target_id, template_entity_ids=context.template_target_ids,
                    admitted_action_target_fact=context.admitted_action_target_fact,
                    expected_action_window_scope=context.expected_action_window_scope),
                target_resolution=context.target_resolution, binding_sources=_binding_sources(context))
            if not resolved.resolved or resolved.rng_events or len(resolved.target_ids) != 1:
                return _unsupported_effect(effect, resolved.blocked_reason or "named_boolean_target_not_unique")
            target_id = resolved.target_ids[0]
        unit = context.state.units.get(target_id)
        key, reason = resolve_named_key(standard.get("key_expression"), _binding_sources(context))
        if reason:
            return _unsupported_effect(effect, reason)
        _, reason = read_named_flag(unit, key)
        if reason:
            return _unsupported_effect(effect, reason)
        before = unit.flags.get(FLAG_FIELD)
        after = {**(before or {}), key: standard["value"]}
        metadata = {"effect_id": effect.effect_id, "opcode": effect.opcode, "key": key,
                    "value": standard["value"], "target_id": target_id, "source_trace": effect.source.to_json()}
        mutation = None if before == after else Mutation("set", ("units", target_id, "flags", FLAG_FIELD),
            before, after, "set named boolean flag", "effect_system", before_exists=FLAG_FIELD in unit.flags,
            metadata=metadata)
        return EffectResult(mutations=(mutation,) if mutation else (), records=(SettlementRecord(
            "named_boolean_flag", "effect_system", mutation_id=mutation.stable_id() if mutation else None,
            process_only=mutation is None, payload=metadata, trace=effect.source.to_json()).to_json(),))

    def _execute_control_skill_mapping(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        standard = effect.payload.get("standard")
        if (context is None or self.status_system is None or not isinstance(standard, dict)
                or standard.get("operation") != "set_control_skill_mapping" or standard.get("blocked_reason")
                or standard.get("control_slot") not in {"basic", "skill", "ultimate"}
                or not isinstance(standard.get("skill_trigger_key"), str) or not standard["skill_trigger_key"]):
            return _unsupported_effect(effect, "control_skill_mapping_context_or_definition_missing")
        target_id = _resolve_target_alias(standard.get("target_alias"), caster_id=context.caster_id,
            owner_id=context.owner_id, param_entity_id=context.param_entity_id,
            current_action_target_id=context.current_action_target_id)
        if standard.get("target_expression_id") and self.targets is not None:
            expression = self.status_system.rules.target_expression(standard["target_expression_id"])
            if expression is None:
                return _unsupported_effect(effect, "control_skill_mapping_target_expression_missing")
            resolved = self.targets.resolve_target_expression(context.state, expression,
                context=TargetEvaluationContext(caster_id=context.caster_id, effect_owner_id=context.owner_id,
                    template_entity_ids=context.template_target_ids,
                    parameter_entity_ids=((context.param_entity_id,) if context.param_entity_id else ()),
                    selected_target_ids=context.target_resolution.selected if context.target_resolution else (),
                    current_target_id=context.current_action_target_id,
                    admitted_action_target_fact=context.admitted_action_target_fact,
                    expected_action_window_scope=context.expected_action_window_scope),
                target_resolution=context.target_resolution, condition_event_payload=context.event_payload,
                binding_sources=context.binding_sources)
            if not resolved.resolved or len(resolved.target_ids) > 1:
                return _unsupported_effect(effect, resolved.blocked_reason or "control_skill_mapping_target_ambiguous")
            if not resolved.target_ids:
                return EffectResult(records=(SettlementRecord("control_skill_mapping", "effect_system", process_only=True,
                    payload={"target_count": 0}, trace=effect.source.to_json()).to_json(),), rng_events=resolved.rng_events)
            target_id = resolved.target_ids[0]
        unit = context.state.units.get(target_id)
        action_set = self.status_system.rules.combatant_action_set(unit.template_id) if unit else None
        levels = unit.flags.get("effective_skill_levels_by_action_id", {}) if unit else {}
        if not isinstance(levels, dict):
            return _unsupported_effect(effect, "control_skill_mapping_skill_levels_invalid")
        if action_set is None or not any(
            (definition := self.status_system.rules.action_definition(entry.get("action_ref"),
                levels.get(entry.get("action_ref"), 1))) is not None
            and definition.skill_trigger_key == standard["skill_trigger_key"]
            for entry in action_set.skill_index_map.values()
        ):
            return _unsupported_effect(effect, "control_skill_mapping_action_not_declared")
        before = unit.flags.get("control_skill_mappings")
        if before is not None and not isinstance(before, dict):
            return _unsupported_effect(effect, "control_skill_mapping_state_invalid")
        after = {**(before or {}), standard["control_slot"]: standard["skill_trigger_key"]}
        metadata = {"effect_id": effect.effect_id, "opcode": effect.opcode,
                    "control_slot": standard["control_slot"], "skill_trigger_key": standard["skill_trigger_key"],
                    "source_trace": effect.source.to_json()}
        mutation = None if after == before else Mutation(op="set",
            path=("units", target_id, "flags", "control_skill_mappings"), before=before, after=after,
            before_exists="control_skill_mappings" in unit.flags, source="effect_system",
            reason="replace control skill", metadata=metadata)
        return EffectResult(mutations=(mutation,) if mutation else (), records=(SettlementRecord(
            record_type="control_skill_mapping", source="effect_system",
            mutation_id=mutation.stable_id() if mutation else None, process_only=mutation is None,
            payload=metadata, trace=effect.source.to_json(),
        ).to_json(),))

    def _execute_stack_status_resistance(
        self, effect: EffectIR, context: EffectExecutionContext | None
    ) -> EffectResult:
        standard = effect.payload.get("standard")
        if (
            context is None
            or self.status_system is None
            or not isinstance(standard, dict)
            or standard.get("operation") != "stack_status_resistance"
            or standard.get("blocked_reason")
            or not isinstance(standard.get("behavior_flag"), str)
            or not standard["behavior_flag"]
            or standard.get("target_alias") not in {"Caster", "ModifierOwnerEntity"}
        ):
            return _unsupported_effect(
                effect, "status_resistance_context_or_definition_missing"
            )
        target_id = _resolve_target_alias(
            standard.get("target_alias"),
            caster_id=context.caster_id,
            owner_id=context.owner_id,
            param_entity_id=context.param_entity_id,
            current_action_target_id=context.current_action_target_id,
        )
        if (
            not isinstance(target_id, str)
            or not target_id
            or target_id not in context.state.units
        ):
            return _unsupported_effect(effect, "status_resistance_target_missing")
        evaluation = _evaluate_numeric(effect, context, standard.get("resistance"))
        if not evaluation.ok or evaluation.value is None:
            return _unsupported_effect(
                effect,
                evaluation.blocked_reason or "status_resistance_value_unresolved",
            )
        value = float(evaluation.value)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            return _unsupported_effect(
                effect, "status_resistance_value_not_admitted"
            )
        unit = context.state.units[target_id]
        before = unit.flags.get("status_resistance_stacks")
        if before is not None and not isinstance(before, (list, tuple)):
            return _unsupported_effect(effect, "status_resistance_state_invalid")
        entries = [
            dict(entry) for entry in (before or ()) if isinstance(entry, dict)
        ]
        kept = [
            entry
            for entry in entries
            if entry.get("producer_effect_id") != effect.effect_id
        ]
        installed = {
            "bucket": "status_resistance",
            "scope": "target",
            "behavior_flag": standard["behavior_flag"],
            "value": value,
            "opcode": effect.opcode,
            "producer_effect_id": effect.effect_id,
            "owner_id": target_id,
            "effect_source": effect.source.to_json(),
            "numeric_evaluation": evaluation.to_json(),
        }
        after = [*kept, installed]
        changed = after != entries
        mutation = (
            Mutation(
                "set",
                ("units", target_id, "flags", "status_resistance_stacks"),
                before,
                after,
                "install a behavior-flag status resistance stack",
                "effect_system",
                before_exists="status_resistance_stacks" in unit.flags,
                metadata={
                    "effect_id": effect.effect_id,
                    "opcode": effect.opcode,
                    "behavior_flag": installed["behavior_flag"],
                    "value": value,
                    "owner_id": target_id,
                    "effect_source": effect.source.to_json(),
                },
            )
            if changed
            else None
        )
        return EffectResult(
            mutations=(mutation,) if mutation is not None else (),
            records=(
                SettlementRecord(
                    record_type="status_resistance_stack",
                    source="effect_system",
                    mutation_id=mutation.stable_id() if mutation is not None else None,
                    process_only=mutation is None,
                    payload={
                        "owner_id": target_id,
                        "behavior_flag": installed["behavior_flag"],
                        "value": value,
                        "previous_value": next(
                            (
                                entry.get("value")
                                for entry in entries
                                if entry.get("producer_effect_id")
                                == effect.effect_id
                            ),
                            None,
                        ),
                        "numeric_evaluation": evaluation.to_json(),
                    },
                    trace=effect.source.to_json(),
                ).to_json(),
            ),
        )

    def _execute_modify_skill_property(
        self, effect: EffectIR, context: EffectExecutionContext | None
    ) -> EffectResult:
        standard = effect.payload.get("standard")
        if (
            context is None
            or self.status_system is None
            or not isinstance(standard, dict)
            or standard.get("operation") != "modify_skill_property_by_type"
            or standard.get("source_shape_admitted") is not True
            or standard.get("blocked_reason")
        ):
            return _unsupported_effect(
                effect, "skill_property_context_or_definition_missing"
            )
        payload = context.event_payload if isinstance(context.event_payload, dict) else {}
        instance_id = str(payload.get("status_instance_id") or "")
        owner_id = context.owner_id
        skill_types = standard.get("skill_types")
        properties = standard.get("properties")
        if (
            not isinstance(instance_id, str)
            or not instance_id
            or not isinstance(owner_id, str)
            or not owner_id
            or not isinstance(skill_types, list)
            or not skill_types
            or not isinstance(properties, list)
            or not properties
        ):
            return _unsupported_effect(effect, "skill_property_status_scope_missing")
        target_id = _resolve_target_alias(
            standard.get("target_alias"),
            caster_id=context.caster_id,
            owner_id=owner_id,
            param_entity_id=context.param_entity_id,
            current_action_target_id=context.current_action_target_id,
        )
        if target_id != owner_id:
            return _unsupported_effect(
                effect, "skill_property_override_requires_status_owner_target"
            )
        unit = context.state.units.get(owner_id)
        details = unit.flags.get("status_details") if unit is not None else None
        if unit is None or not isinstance(details, (list, tuple)):
            return _unsupported_effect(effect, "skill_property_status_detail_missing")
        index = next(
            (
                position
                for position, detail in enumerate(details)
                if isinstance(detail, dict) and detail.get("instance_id") == instance_id
            ),
            -1,
        )
        if index < 0:
            return _unsupported_effect(effect, "skill_property_status_detail_missing")
        applied: list[dict[str, JSONValue]] = []
        evaluations: dict[str, JSONValue] = {}
        for item in properties:
            if not isinstance(item, dict):
                return _unsupported_effect(effect, "skill_property_entry_invalid")
            property_type = str(item.get("property_type") or "")
            raw_value = item.get("value")
            if raw_value is None:
                value = 0.0
            else:
                evaluation = _evaluate_numeric(effect, context, raw_value)
                if not evaluation.ok or evaluation.value is None:
                    return _unsupported_effect(
                        effect,
                        evaluation.blocked_reason
                        or "skill_property_value_unresolved",
                    )
                value = float(evaluation.value)
                # Explicit property values retain their runtime evaluation as
                # the native audit fact of this mutation.
                evaluations[property_type] = evaluation.to_json()
            if not math.isfinite(value):
                return _unsupported_effect(effect, "skill_property_value_not_finite")
            applied.append({
                "property_type": property_type,
                "skill_types": list(skill_types),
                "value": value,
                "value_source": str(item.get("value_source") or ""),
                "status_instance_id": instance_id,
                "effect_id": effect.effect_id,
            })
        detail = details[index]
        existing = detail.get("skill_property_overrides")
        if existing is not None and not isinstance(existing, list):
            return _unsupported_effect(effect, "skill_property_status_detail_state_invalid")
        kept = [
            entry
            for entry in (existing or ())
            if not (
                isinstance(entry, dict)
                and (entry.get("property_type"), tuple(entry.get("skill_types") or ()))
                in {(entry_new["property_type"], tuple(entry_new["skill_types"])) for entry_new in applied}
            )
        ]
        updated_detail = {**detail, "skill_property_overrides": [*kept, *applied]}
        before = [dict(item) if isinstance(item, dict) else item for item in details]
        after = [
            updated_detail if position == index else dict(item) if isinstance(item, dict) else item
            for position, item in enumerate(details)
        ]
        mutation = Mutation(
            "set",
            ("units", owner_id, "flags", "status_details"),
            before,
            after,
            "modify skill property for the owning status instance",
            "effect_system",
            metadata={
                "effect_id": effect.effect_id,
                "opcode": effect.opcode,
                "status_instance_id": instance_id,
                "skill_property_overrides": applied,
                "numeric_evaluations": evaluations,
                "effect_source": effect.source.to_json(),
                "source_trace": effect.source.to_json(),
            },
        )
        return EffectResult(
            mutations=(mutation,),
            records=(
                SettlementRecord(
                    record_type="skill_property_modified",
                    source="effect_system",
                    mutation_id=mutation.stable_id(),
                    process_only=False,
                    payload={
                        "status_instance_id": instance_id,
                        "owner_id": owner_id,
                        "overrides": applied,
                        "target_alias": standard.get("target_alias"),
                    },
                    trace=effect.source.to_json(),
                ).to_json(),
            ),
        )

    def _execute_exit_break_state(
        self, effect: EffectIR, context: EffectExecutionContext | None
    ) -> EffectResult:
        """Formal ExitBreakState: an unbroken target is a no-op.

        A broken live target keeps the ordinary recovery branch fail-closed.
        A broken unit runs the corpse cleanup only when it already committed the
        final death instance carried by this effect context; limbo and pending
        defeats stay blocked.
        """

        if context is None:
            return _unsupported_effect(effect, "exit_break_state_context_missing")
        standard = effect.payload.get("standard")
        if (
            not isinstance(standard, dict)
            or standard.get("operation") != "exit_break_state"
            or standard.get("blocked_reason")
            or standard.get("target_alias") != "Caster"
        ):
            return _unsupported_effect(effect, "exit_break_state_contract_missing")
        target_id = _resolve_target_alias(
            "Caster",
            caster_id=context.caster_id,
            owner_id=context.owner_id,
            param_entity_id=context.param_entity_id,
            current_action_target_id=context.current_action_target_id,
        )
        unit = context.state.units.get(target_id)
        if unit is None:
            return _unsupported_effect(effect, "exit_break_state_target_missing")
        if unit.flags.get("broken") is True:
            # A unit that dies while broken runs the same source task from its
            # inserted death animation. Only the committed final death instance
            # carried by the callback may run the corpse cleanup; a limbo that
            # can still be rescued is not a corpse. A live broken unit keeps the
            # ordinary recovery branch fail-closed.
            death_instance_id = context.death_instance_id
            if (
                unit.lifecycle_status != "defeated"
                or float(unit.hp) != 0.0
                or not death_instance_id
                or self.status_system is None
            ):
                return _unsupported_effect(
                    effect, "exit_break_state_broken_target_branch_not_admitted"
                )
            from .break_system import clear_death_break_state

            cleared = clear_death_break_state(
                self.status_system.rules,
                context.state,
                unit_id=target_id,
                effect_id=effect.effect_id,
                death_instance_id=death_instance_id,
            )
            if not cleared.ok:
                return _unsupported_effect(
                    effect, ",".join(cleared.errors) or "exit_break_state_death_cleanup_blocked"
                )
            records = (
                *cleared.records,
                SettlementRecord(
                    record_type="exit_break_state",
                    source="effect_system",
                    process_only=True,
                    payload={
                        "target_id": target_id,
                        "death_instance_id": death_instance_id,
                        "applied": True,
                        "reason": "deathrattle_exit_break_state",
                        "cancel_recover_anim": standard.get("cancel_recover_anim") is True,
                    },
                    trace=effect.source.to_json(),
                ).to_json(),
            )
            return EffectResult(
                events=cleared.events,
                mutations=cleared.mutations,
                rng_events=cleared.rng_events,
                records=records,
            )
        payload = {
            "target_id": target_id,
            "applied": False,
            "reason": "target_not_broken",
            "cancel_recover_anim": standard.get("cancel_recover_anim") is True,
        }
        return EffectResult(
            records=(
                SettlementRecord(
                    record_type="exit_break_state",
                    source="effect_system",
                    process_only=True,
                    payload=payload,
                    trace=effect.source.to_json(),
                ).to_json(),
            )
        )

    def _execute_set_action_delay(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        if context is None:
            return _unsupported_effect(effect, "action_delay_context_missing")
        standard = effect.payload["standard"]
        if isinstance(standard, dict) and standard.get("operation") == "set_action_delay_zero":
            normalized = standard.get("normalized_value")
            if (
                standard.get("target_alias") != "Caster"
                or not isinstance(normalized, dict)
                or normalized.get("value") != 0.0
            ):
                return _unsupported_effect(effect, "set_action_delay_zero_shape_invalid")
            target_id = _resolve_target_alias(
                "Caster",
                caster_id=context.caster_id,
                owner_id=context.owner_id,
                param_entity_id=context.param_entity_id,
                current_action_target_id=context.current_action_target_id,
            )
            return EffectResult(
                records=(
                    SettlementRecord(
                        record_type="set_action_delay_zero",
                        source="effect_system",
                        process_only=True,
                        payload={
                            "target_id": target_id,
                            "normalized_value": 0.0,
                            "applied": False,
                            "reason": "zero_delay_is_noop",
                        },
                        trace=effect.source.to_json(),
                    ).to_json(),
                )
            )
        if isinstance(standard, dict) and standard.get("operation") == "set_action_delay_normalized":
            return self._execute_set_action_delay_normalized(effect, context, standard)
        target_id = _resolve_target_alias(standard["target_alias"], caster_id=context.caster_id,
            owner_id=context.owner_id, param_entity_id=context.param_entity_id,
            current_action_target_id=context.current_action_target_id,
            target_resolution=context.target_resolution)
        value = _evaluate_numeric(effect, context, standard["value"])
        if target_id not in context.state.units or not value.ok or value.value is None:
            return _unsupported_effect(effect, value.blocked_reason or "action_delay_target_or_value_unresolved")
        result = TimelineSystem().adjust_action_value(context.state, target_id,
            operation="set", amount=value.value, source="effect_system",
            metadata={"effect_id": effect.effect_id, "opcode": effect.opcode,
                      "effect_source": effect.source.to_json(),
                      "numeric_evaluation": value.to_json(), "source_trace": effect.source.to_json()})
        events = tuple(event for mutation in result.mutations for event in events_for_mutation(
            mutation, actor_id=context.caster_id, source_id=context.source_id, event_index=context.state.event_index,
        ))
        return EffectResult(mutations=result.mutations, events=events, records=result.records)

    def _execute_set_action_delay_near_target(
        self, effect: EffectIR, context: EffectExecutionContext | None,
    ) -> EffectResult:
        """Place one unit's action value at another unit's, ordered after/before it."""

        standard = effect.payload.get("standard") if isinstance(effect.payload, dict) else None
        if context is None or not isinstance(standard, dict) or standard.get("blocked_reason"):
            return _unsupported_effect(effect, "set_action_delay_near_target_context_missing")
        resolved: dict[str, str] = {}
        for field in ("target_alias", "near_alias"):
            unit_id = _resolve_target_alias(
                standard.get(field), caster_id=context.caster_id, owner_id=context.owner_id,
                param_entity_id=context.param_entity_id,
                current_action_target_id=context.current_action_target_id,
                target_resolution=context.target_resolution, state=context.state,
            )
            if unit_id is None or unit_id not in context.state.units:
                return _unsupported_effect(effect, f"set_action_delay_near_target_unresolved:{field}")
            resolved[field] = unit_id
        target_id, near_id = resolved["target_alias"], resolved["near_alias"]
        if target_id == near_id:
            return _unsupported_effect(effect, "set_action_delay_near_target_self_reference")
        near_value = max(0.0, float(context.state.units[near_id].action_value))
        metadata = {"effect_id": effect.effect_id, "opcode": effect.opcode, "target_id": target_id,
                    "near_target_id": near_id, "near_type": standard.get("near_type"),
                    "effect_source": effect.source.to_json(), "source_trace": effect.source.to_json()}
        result = TimelineSystem().adjust_action_value(context.state, target_id,
            operation="set", amount=near_value, source="effect_system", metadata=metadata)
        if not result.plan.ok:
            return _unsupported_effect(effect, result.plan.blocked_reason or "set_action_delay_near_target_blocked")
        target = context.state.units[target_id]
        order = {"anchor_id": near_id, "near_type": str(standard.get("near_type")),
                 "effect_id": effect.effect_id, "source_trace": effect.source.to_json()}
        order_mutation = Mutation("set", ("units", target_id, "flags", "timeline_near_target"),
            target.flags.get("timeline_near_target"), order,
            before_exists="timeline_near_target" in target.flags,
            reason="order the action value tie against the near target", source="effect_system",
            metadata=metadata)
        mutations = (*result.mutations, order_mutation)
        events = tuple(event for mutation in result.mutations for event in events_for_mutation(
            mutation, actor_id=context.caster_id, source_id=context.source_id, event_index=context.state.event_index,
        ))
        return EffectResult(mutations=mutations, events=events, records=result.records)

    def _execute_lock_target_hp(
        self, effect: EffectIR, context: EffectExecutionContext | None,
    ) -> EffectResult:
        """Lock a mortally wounded owner at the HP floor; publish the excess as overflow."""

        from .mutation_events import hp_overflow_event
        from .unit_lifecycle import MORTAL_WOUND_EVENT

        standard = effect.payload.get("standard") if isinstance(effect.payload, dict) else None
        if (context is None or not isinstance(standard, dict)
                or standard.get("operation") != "lock_target_hp" or standard.get("blocked_reason")):
            return _unsupported_effect(effect, "hp_lock_source_not_admitted")
        trigger = context.trigger_event
        plan = trigger.pending_defeat_plan if trigger is not None else None
        owner_id = context.owner_id or ""
        if (trigger is None or trigger.event_type != MORTAL_WOUND_EVENT or plan is None
                or plan.unit_id != owner_id or owner_id not in context.state.units):
            return _unsupported_effect(effect, "hp_lock_requires_mortal_wound_window")
        lifecycle = UnitLifecycleSystem()
        try:
            current = lifecycle.pending_defeat(context.state, owner_id)
        except ValueError as exc:
            return _unsupported_effect(effect, "hp_lock_pending_defeat_invalid:" + str(exc))
        if current != plan:
            return _unsupported_effect(effect, "hp_lock_pending_defeat_mismatch")
        floor = float(standard.get("hp_floor") or 1.0)
        before_hp = plan.hp_mutation.before if plan.hp_mutation is not None else None
        final_damage = (plan.hp_mutation.metadata or {}).get("final_damage") if plan.hp_mutation is not None else None
        if (type(before_hp) not in (int, float) or type(final_damage) not in (int, float)
                or not math.isfinite(float(final_damage))):
            return _unsupported_effect(effect, "hp_lock_lethal_damage_amount_missing")
        overflow = float(final_damage) - max(0.0, float(before_hp) - floor)
        if overflow <= 0:
            return _unsupported_effect(effect, "hp_lock_overflow_not_positive")
        unit = context.state.units[owner_id]
        metadata = {"effect_id": effect.effect_id, "opcode": effect.opcode, "lock_key": standard["lock_key"],
                    "pending_defeat_id": plan.pending_id, "hp_floor": floor, "overflow_amount": overflow,
                    "effect_source": effect.source.to_json()}
        hp_mutation = Mutation("set", ("units", owner_id, "hp"), unit.hp, floor,
            reason="lock mortally wounded HP at its floor", source="effect_system", metadata=metadata)
        try:
            rescue = lifecycle.rescue_from_limbo_mutations(context.state, plan, hp_mutation)
        except ValueError as exc:
            return _unsupported_effect(effect, "hp_lock_rescue_blocked:" + str(exc))
        locks = dict(unit.flags.get("hp_locks") or {})
        locks[str(standard["lock_key"])] = {"threshold": standard.get("threshold"), "hp_floor": floor,
                                            "effect_id": effect.effect_id}
        lock_mutation = Mutation("set", ("units", owner_id, "flags", "hp_locks"), unit.flags.get("hp_locks"),
            locks, before_exists="hp_locks" in unit.flags, reason="record HP lock",
            source="effect_system", metadata=metadata)
        rescue_hp = next(item for item in rescue if item.path == ("units", owner_id, "hp"))
        overflow_event = hp_overflow_event(rescue_hp, overflow, target_id=owner_id,
            source_id=str(plan.kill_credit_owner_id or ""), pending_defeat_id=plan.pending_id,
            metadata={"effect_id": effect.effect_id, "lock_key": standard["lock_key"]})
        mutations = (*rescue, lock_mutation)
        records = tuple(SettlementRecord(
            record_type="hp_lock_rescue" if item.path[-1] == "hp" else "hp_lock",
            source="effect_system", mutation_id=item.stable_id(), process_only=False,
            payload={**metadata, "mutation_path": list(item.path)},
            trace={"effect_source": effect.source.to_json(), "floor_source": standard.get("floor_source", {})},
        ).to_json() for item in mutations)
        return EffectResult(mutations=mutations, events=(overflow_event,), records=records)

    def _execute_unlock_target_hp(
        self, effect: EffectIR, context: EffectExecutionContext | None,
    ) -> EffectResult:
        standard = effect.payload.get("standard") if isinstance(effect.payload, dict) else None
        if (context is None or not isinstance(standard, dict)
                or standard.get("operation") != "unlock_target_hp" or standard.get("blocked_reason")):
            return _unsupported_effect(effect, "hp_unlock_source_not_admitted")
        owner_id = context.owner_id or ""
        unit = context.state.units.get(owner_id)
        if unit is None:
            return _unsupported_effect(effect, "hp_unlock_target_missing")
        locks = unit.flags.get("hp_locks")
        key = str(standard["lock_key"])
        trace = {"effect_source": effect.source.to_json()}
        if not isinstance(locks, dict) or key not in locks:
            # 锁已不存在（例如修饰器销毁时）：解锁结果已成立，不改变状态。
            return EffectResult(records=(SettlementRecord(
                record_type="hp_unlock_idempotent", source="effect_system", process_only=True,
                payload={"effect_id": effect.effect_id, "target_id": owner_id, "lock_key": key,
                         "state_unchanged": True}, trace=trace).to_json(),))
        remaining = {name: value for name, value in locks.items() if name != key}
        mutation = (Mutation("set", ("units", owner_id, "flags", "hp_locks"), locks, remaining,
                             reason="release HP lock", source="effect_system",
                             metadata={"effect_id": effect.effect_id, "lock_key": key})
                    if remaining else
                    Mutation("delete", ("units", owner_id, "flags", "hp_locks"), locks, None,
                             after_exists=False, reason="release last HP lock", source="effect_system",
                             metadata={"effect_id": effect.effect_id, "lock_key": key}))
        return EffectResult(mutations=(mutation,), records=(SettlementRecord(
            record_type="hp_unlock", source="effect_system", mutation_id=mutation.stable_id(),
            process_only=False, payload={"effect_id": effect.effect_id, "target_id": owner_id, "lock_key": key},
            trace=trace).to_json(),))

    def _execute_reinit_property(
        self, effect: EffectIR, context: EffectExecutionContext | None,
    ) -> EffectResult:
        """Reinitialize one property component of the modifier owner and lock its bounds."""

        standard = effect.payload.get("standard") if isinstance(effect.payload, dict) else None
        if (context is None or not isinstance(standard, dict)
                or standard.get("operation") != "reinit_property" or standard.get("blocked_reason")):
            return _unsupported_effect(effect, "reinit_property_source_not_admitted")
        target_id = context.owner_id or ""
        if target_id not in context.state.units:
            return _unsupported_effect(effect, "reinit_property_target_missing")
        evaluated = _evaluate_numeric(effect, context, standard.get("init_value"))
        if not evaluated.ok or evaluated.value is None or not math.isfinite(float(evaluated.value)):
            return _unsupported_effect(effect, evaluated.blocked_reason or "reinit_property_value_unresolved")
        unit = context.state.units[target_id]
        before = unit.flags.get("property_reinit")
        entries = dict(before) if isinstance(before, dict) else {}
        entries[str(standard["property"])] = {
            "stat": standard["stat"], "component": standard["component"],
            "value": float(evaluated.value),
            "min": standard.get("min_value"), "max": standard.get("max_value"),
            "effect_id": effect.effect_id,
        }
        mutation = Mutation("set", ("units", target_id, "flags", "property_reinit"), before, entries,
            before_exists="property_reinit" in unit.flags, reason="reinitialize property component",
            source="effect_system", metadata={"effect_id": effect.effect_id, "opcode": effect.opcode,
                "property": standard["property"], "numeric_evaluation": evaluated.to_json(),
                "effect_source": effect.source.to_json()})
        record = SettlementRecord(
            record_type="reinit_property", source="effect_system",
            mutation_id=mutation.stable_id(), process_only=False,
            payload={"effect_id": effect.effect_id, "target_id": target_id,
                     "property": standard["property"], "value": float(evaluated.value)},
            trace={"effect_source": effect.source.to_json()},
        ).to_json()
        return EffectResult(mutations=(mutation,), records=(record,))

    def _execute_set_action_delay_normalized(
        self, effect: EffectIR, context: EffectExecutionContext, standard: dict[str, JSONValue],
    ) -> EffectResult:
        if self.status_system is None or standard.get("target_alias") != "Caster":
            return _unsupported_effect(effect, "set_action_delay_normalized_context_missing")
        target_id = context.caster_id
        evaluated = _evaluate_numeric(effect, context, standard.get("normalized_value"))
        if (target_id not in context.state.units or not evaluated.ok or evaluated.value is None
                or not math.isfinite(float(evaluated.value)) or float(evaluated.value) <= 0.0):
            return _unsupported_effect(effect, evaluated.blocked_reason or "set_action_delay_normalized_value_invalid")
        rule, rule_reason = self.status_system.rules.select_timeline_rule()
        if rule is None:
            return _unsupported_effect(effect, rule_reason or "timeline_engine_rule_missing")
        speed = effective_unit_stat(context.state.units[target_id], "speed")
        action_value = float(evaluated.value) * TimelineSystem().full_action_value(speed.value, rule)
        result = TimelineSystem().adjust_action_value(context.state, target_id,
            operation="set", amount=action_value, source="effect_system", rule=rule,
            metadata={"effect_id": effect.effect_id, "opcode": effect.opcode, "target_id": target_id,
                      "normalized_value": float(evaluated.value), "action_value": action_value,
                      "effect_source": effect.source.to_json(),
                      "numeric_evaluation": evaluated.to_json(), "source_trace": effect.source.to_json()})
        if not result.plan.ok:
            return _unsupported_effect(effect, result.plan.blocked_reason or "set_action_delay_timeline_adjustment_blocked")
        events = tuple(event for mutation in result.mutations for event in events_for_mutation(
            mutation, actor_id=context.caster_id, source_id=context.source_id, event_index=context.state.event_index,
        ))
        return EffectResult(mutations=result.mutations, events=events, records=result.records)

    def _execute_current_skill_delay_cost(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        if context is None or not context.ability_instance_id:
            return _unsupported_effect(effect, "current_skill_delay_cost_action_context_missing")
        standard = effect.payload["standard"]
        value = _evaluate_numeric(effect, context, standard["normalized_value"])
        if not value.ok or value.value is None:
            return _unsupported_effect(effect, value.blocked_reason or "current_skill_delay_cost_value_unresolved")
        try:
            mutation = TimelineSystem().register_current_skill_delay_cost(context.state,
                actor_id=context.caster_id, identity=f"{context.ability_instance_id}:{effect.effect_id}",
                modify_function=standard["modify_function"], normalized_value=value.value,
                source="effect_system", metadata={"effect_id": effect.effect_id,
                    "task_id": effect.effect_id, "numeric_evaluation": value.to_json(),
                    "source_trace": {"effect_source": effect.source.to_json(),
                                     "adopted_rule_source": standard.get("adopted_rule_source", {})}})
        except ValueError as exc:
            return _unsupported_effect(effect, str(exc))
        return EffectResult(mutations=(mutation,), records=(SettlementRecord(
            record_type="turn_action_delay_cost_registered", source="effect_system",
            mutation_id=mutation.stable_id(), payload=mutation.metadata,
            trace=mutation.metadata["source_trace"],
        ).to_json(),))

    def _execute_create_battle_event(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        from .battle_event import create_battle_event
        return create_battle_event(effect, context, self)

    _MUTABLE_UNIT_PROPERTY_KEYS = {
        # Engine-maintained unit properties with an explicit ModifyProperty
        # writer; the store starts at zero when no task modified it yet.
        "CurExtraSpecialSP": "cur_extra_special_sp",
    }

    def _execute_command_type_switch_marker(
        self,
        effect: EffectIR,
        context: EffectExecutionContext | None,
    ) -> EffectResult:
        standard = (
            effect.payload.get("standard", {})
            if isinstance(effect.payload, dict)
            else {}
        )
        if (
            not isinstance(standard, dict)
            or standard.get("blocked_reason")
            or standard.get("operation") != "command_type_switch_marker"
        ):
            return _unsupported_effect(
                effect, "command_type_switch_marker_not_admitted",
            )
        record = SettlementRecord(
            record_type="command_type_switch_marker",
            source="effect_system",
            process_only=True,
            payload={"operation": "command_type_switch_marker"},
            trace=effect.source.to_json(),
        ).to_json()
        node = ExecutionNodeResult(
            node_kind="effect",
            node_id=effect.effect_id,
            status="complete",
        )
        return EffectResult(records=(record,), node_results=(node,))

    def _execute_modify_special_sp(
        self,
        effect: EffectIR,
        context: EffectExecutionContext | None,
    ) -> EffectResult:
        standard = (
            effect.payload.get("standard", {})
            if isinstance(effect.payload, dict)
            else {}
        )
        if (
            context is None
            or not isinstance(standard, dict)
            or standard.get("blocked_reason")
            or standard.get("operation") != "modify_special_sp"
        ):
            return _unsupported_effect(effect, "modify_special_sp_context_missing")
        target_id = _resolve_target_alias(
            standard.get("target_alias"),
            caster_id=str(context.caster_id or ""),
            owner_id=context.owner_id,
            param_entity_id=context.param_entity_id,
            current_action_target_id=context.current_action_target_id,
            target_resolution=context.target_resolution,
            state=context.state,
        )
        unit = context.state.units.get(str(target_id or ""))
        if unit is None:
            return _unsupported_effect(effect, "modify_special_sp_target_missing")
        current_key = unit.flags.get("special_resource_current_key")
        maximum_key = unit.flags.get("special_resource_maximum_key")
        if not isinstance(current_key, str) or not current_key:
            # Profiles without a bound special resource still carry the engine
            # special-SP pool under the generic keys.
            current_key = "special_sp"
        if not isinstance(maximum_key, str) or not maximum_key:
            maximum_key = "max_special_sp"
        evaluation = _evaluate_numeric(
            effect, context, standard.get("amount"),
        )
        if not evaluation.ok or evaluation.value is None:
            return _unsupported_effect(
                effect,
                evaluation.blocked_reason
                or "modify_special_sp_value_unresolved",
            )
        before_value = unit.resources.get(current_key, 0.0)
        before = (
            float(before_value)
            if isinstance(before_value, (int, float))
            and not isinstance(before_value, bool)
            else 0.0
        )
        modify_function = str(standard.get("modify_function") or "Add")
        if modify_function == "Set":
            after = float(evaluation.value)
        elif modify_function == "Sub":
            after = before - float(evaluation.value)
        else:
            after = before + float(evaluation.value)
        after = max(0.0, after)
        maximum_value = (
            unit.resources.get(maximum_key, 0.0)
            if isinstance(maximum_key, str) and maximum_key
            else 0.0
        )
        if (
            isinstance(maximum_value, (int, float))
            and not isinstance(maximum_value, bool)
            and float(maximum_value) > 0
        ):
            after = min(after, float(maximum_value))
        mutation = Mutation(
            op="set",
            path=("units", unit.unit_id, "resources", current_key),
            before=before if current_key in unit.resources else None,
            after=after,
            reason="modify special sp",
            source="effect_system",
            before_exists=current_key in unit.resources,
            metadata={
                "effect_id": effect.effect_id,
                "opcode": effect.opcode,
                "resource_key": current_key,
                "modify_function": modify_function,
                "amount": float(evaluation.value),
                "before": before,
                "after": after,
                "ignore_block": standard.get("ignore_block") is True,
                "numeric_evaluation": evaluation.to_json(),
                "source_trace": effect.source.to_json(),
            },
        )
        record = SettlementRecord(
            record_type="modify_special_sp",
            source="effect_system",
            mutation_id=mutation.stable_id(),
            process_only=False,
            payload={
                "target_id": unit.unit_id,
                "target_alias": str(standard.get("target_alias") or ""),
                "resource_key": current_key,
                "modify_function": modify_function,
                "amount": float(evaluation.value),
                "before": before,
                "after": after,
            },
            trace=effect.source.to_json(),
        ).to_json()
        node = ExecutionNodeResult(
            node_kind="effect",
            node_id=effect.effect_id,
            status="complete",
        )
        return EffectResult(
            mutations=(mutation,),
            records=(record,),
            node_results=(node,),
        )

    def _execute_modify_special_sp_pool(
        self,
        effect: EffectIR,
        context: EffectExecutionContext | None,
    ) -> EffectResult:
        standard = (
            effect.payload.get("standard", {})
            if isinstance(effect.payload, dict)
            else {}
        )
        if (
            context is None
            or not isinstance(standard, dict)
            or standard.get("blocked_reason")
            or standard.get("operation")
            not in {"modify_special_sp_ratio", "modify_special_sp_add"}
        ):
            return _unsupported_effect(
                effect, "modify_special_sp_pool_context_missing",
            )
        caster_id = str(context.caster_id or "")
        alias = str(standard.get("target_alias") or "")
        if alias == "Caster":
            targets: tuple[str, ...] = (caster_id,)
        elif alias == "CasterSummoner":
            summoner = _resolve_target_alias(
                alias, caster_id=caster_id, owner_id=None,
                param_entity_id=None, current_action_target_id=None,
                state=context.state,
            )
            targets = (summoner,) if summoner else ()
        elif alias == "AllTeammateOnlyAddSPOnceForServant":
            resolved = EntityRelationResolver().resolve(
                context.state,
                "team.same",
                TargetEvaluationContext(caster_id=caster_id),
                subject_ids=(caster_id,),
                options={"include_self": True},
            )
            targets = tuple(resolved.target_ids) if resolved.resolved else ()
        else:
            targets = ()
        if not targets or any(item not in context.state.units for item in targets):
            return _unsupported_effect(
                effect, "modify_special_sp_pool_target_missing",
            )
        evaluation = _evaluate_numeric(
            effect, context, standard.get("amount"),
        )
        if not evaluation.ok or evaluation.value is None:
            return _unsupported_effect(
                effect,
                evaluation.blocked_reason
                or "modify_special_sp_pool_value_unresolved",
            )
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = []
        for unit_id in dict.fromkeys(targets):
            unit = context.state.units[unit_id]
            current_key = unit.flags.get("special_resource_current_key")
            maximum_key = unit.flags.get("special_resource_maximum_key")
            if not isinstance(current_key, str) or not current_key:
                current_key = "special_sp"
            if not isinstance(maximum_key, str) or not maximum_key:
                maximum_key = "max_special_sp"
            before_value = unit.resources.get(current_key, 0.0)
            before = (
                float(before_value)
                if isinstance(before_value, (int, float))
                and not isinstance(before_value, bool)
                else 0.0
            )
            maximum_raw = unit.resources.get(maximum_key, 0.0)
            maximum = (
                float(maximum_raw)
                if isinstance(maximum_raw, (int, float))
                and not isinstance(maximum_raw, bool)
                else 0.0
            )
            extra = effective_unit_stat(unit, "max_extra_special_sp").value
            maximum = maximum + (extra if isinstance(extra, float) else 0.0)
            if standard.get("operation") == "modify_special_sp_ratio":
                after = maximum * float(evaluation.value)
            else:
                after = before + float(evaluation.value)
            after = max(0.0, after)
            if maximum > 0:
                after = min(after, maximum)
            mutation = Mutation(
                op="set",
                path=("units", unit_id, "resources", current_key),
                before=before if current_key in unit.resources else None,
                after=after,
                reason="modify special sp pool",
                source="effect_system",
                before_exists=current_key in unit.resources,
                metadata={
                    "effect_id": effect.effect_id,
                    "opcode": effect.opcode,
                    "resource_key": current_key,
                    "operation": standard.get("operation"),
                    "amount": float(evaluation.value),
                    "before": before,
                    "after": after,
                    "maximum": maximum,
                    "numeric_evaluation": evaluation.to_json(),
                    "source_trace": effect.source.to_json(),
                },
            )
            mutations.append(mutation)
            records.append(
                SettlementRecord(
                    record_type="modify_special_sp_pool",
                    source="effect_system",
                    mutation_id=mutation.stable_id(),
                    process_only=False,
                    payload={
                        "target_id": unit_id,
                        "target_alias": alias,
                        "resource_key": current_key,
                        "operation": standard.get("operation"),
                        "amount": float(evaluation.value),
                        "before": before,
                        "after": after,
                        "maximum": maximum,
                    },
                    trace=effect.source.to_json(),
                ).to_json()
            )
        node = ExecutionNodeResult(
            node_kind="effect",
            node_id=effect.effect_id,
            status="complete",
        )
        return EffectResult(
            mutations=tuple(mutations),
            records=tuple(records),
            node_results=(node,),
        )

    def _execute_modify_unit_property(
        self,
        effect: EffectIR,
        context: EffectExecutionContext | None,
    ) -> EffectResult:
        standard = (
            effect.payload.get("standard", {})
            if isinstance(effect.payload, dict)
            else {}
        )
        if (
            context is None
            or not isinstance(standard, dict)
            or standard.get("blocked_reason")
            or standard.get("operation") != "modify_unit_property"
        ):
            return _unsupported_effect(
                effect, "modify_unit_property_context_missing",
            )
        property_name = str(standard.get("property_name") or "")
        store_key = self._MUTABLE_UNIT_PROPERTY_KEYS.get(property_name)
        if not store_key:
            return _unsupported_effect(
                effect, "modify_unit_property_not_admitted",
            )
        target_id = _resolve_target_alias(
            standard.get("target_alias"),
            caster_id=str(context.caster_id or ""),
            owner_id=context.owner_id,
            param_entity_id=context.param_entity_id,
            current_action_target_id=context.current_action_target_id,
            target_resolution=context.target_resolution,
            state=context.state,
        )
        unit = context.state.units.get(str(target_id or ""))
        if unit is None:
            return _unsupported_effect(
                effect, "modify_unit_property_target_missing",
            )
        evaluation = _evaluate_numeric(
            effect, context, standard.get("amount"),
        )
        if not evaluation.ok or evaluation.value is None:
            return _unsupported_effect(
                effect,
                evaluation.blocked_reason
                or "modify_unit_property_value_unresolved",
            )
        before_value = unit.resources.get(store_key, 0.0)
        before = (
            float(before_value)
            if isinstance(before_value, (int, float))
            and not isinstance(before_value, bool)
            else 0.0
        )
        modify_function = str(standard.get("modify_function") or "Add")
        after = (
            float(evaluation.value)
            if modify_function == "Set"
            else before + float(evaluation.value)
        )
        mutation = Mutation(
            op="set" if store_key in unit.resources else "set",
            path=("units", unit.unit_id, "resources", store_key),
            before=before if store_key in unit.resources else None,
            after=after,
            reason=f"modify unit property {property_name}",
            source="effect_system",
            before_exists=store_key in unit.resources,
            metadata={
                "effect_id": effect.effect_id,
                "opcode": effect.opcode,
                "property_name": property_name,
                "modify_function": modify_function,
                "amount": float(evaluation.value),
                "before": before,
                "after": after,
                "numeric_evaluation": evaluation.to_json(),
                "source_trace": effect.source.to_json(),
            },
        )
        record = SettlementRecord(
            record_type="modify_unit_property",
            source="effect_system",
            mutation_id=mutation.stable_id(),
            process_only=False,
            payload={
                "target_id": unit.unit_id,
                "target_alias": str(standard.get("target_alias") or ""),
                "property_name": property_name,
                "store_key": store_key,
                "modify_function": modify_function,
                "amount": float(evaluation.value),
                "before": before,
                "after": after,
            },
            trace=effect.source.to_json(),
        ).to_json()
        node = ExecutionNodeResult(
            node_kind="effect",
            node_id=effect.effect_id,
            status="complete",
        )
        return EffectResult(
            mutations=(mutation,),
            records=(record,),
            node_results=(node,),
        )

    def _execute_auto_use_ultra_skill(
        self,
        effect: EffectIR,
        context: EffectExecutionContext | None,
    ) -> EffectResult:
        standard = (
            effect.payload.get("standard", {})
            if isinstance(effect.payload, dict)
            else {}
        )
        if (
            context is None
            or not isinstance(standard, dict)
            or standard.get("blocked_reason")
            or standard.get("operation") != "auto_use_ultra_skill"
            or standard.get("target_alias") != "Caster"
        ):
            return _unsupported_effect(effect, "auto_use_ultra_skill_context_missing")
        target_id = str(context.caster_id or "")
        unit = context.state.units.get(target_id)
        if unit is None:
            return _unsupported_effect(effect, "auto_use_ultra_skill_target_missing")
        before = unit.flags.get("auto_use_ultra_skill")
        if before is True:
            record_value = True
        else:
            record_value = False
        mutation = Mutation(
            op="set",
            path=("units", target_id, "flags", "auto_use_ultra_skill"),
            before=before,
            after=True,
            reason="auto use ultra skill marker",
            source="effect_system",
            before_exists="auto_use_ultra_skill" in unit.flags,
            metadata={
                "effect_id": effect.effect_id,
                "operation": "auto_use_ultra_skill",
            },
        )
        record = SettlementRecord(
            record_type="auto_use_ultra_skill_marker",
            source="effect_system",
            mutation_id=mutation.stable_id(),
            process_only=False,
            payload={
                "target_id": target_id,
                "target_alias": "Caster",
                "before": record_value,
                "after": True,
            },
            trace=effect.source.to_json(),
        ).to_json()
        node = ExecutionNodeResult(
            node_kind="effect",
            node_id=effect.effect_id,
            status="complete",
        )
        return EffectResult(
            mutations=(mutation,),
            records=(record,),
            node_results=(node,),
        )

    def _execute_process_modifier_life_step(
        self,
        effect: EffectIR,
        context: EffectExecutionContext | None,
    ) -> EffectResult:
        standard = (
            effect.payload.get("standard", {})
            if isinstance(effect.payload, dict)
            else {}
        )
        if (
            context is None
            or self.status_system is None
            or not isinstance(standard, dict)
            or standard.get("blocked_reason")
        ):
            return _unsupported_effect(
                effect, "process_modifier_life_step_context_missing",
            )
        alias = str(standard.get("target_alias") or "")
        target_id = (
            str(context.owner_id or "")
            if alias == "ModifierOwnerEntity"
            else str(context.caster_id or "")
        )
        unit = context.state.units.get(target_id)
        if unit is None:
            return _unsupported_effect(
                effect, "process_modifier_life_step_target_missing",
            )
        moment = str(standard.get("life_step_moment") or "")
        if not moment:
            return _unsupported_effect(
                effect, "process_modifier_life_step_moment_missing",
            )
        instance_ids = tuple(
            str(detail.get("instance_id") or "")
            for detail in unit.flags.get("status_details", ())
            if isinstance(detail, dict) and detail.get("instance_id")
        )
        current = context.state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        records: list[dict[str, JSONValue]] = []
        rng_events: list[RNGEvent] = []
        nodes: list[ExecutionNodeResult] = []
        applied = 0
        for instance_id in instance_ids:
            current_unit = current.units.get(target_id)
            if current_unit is None:
                break
            detail = next(
                (
                    item
                    for item in current_unit.flags.get("status_details", ())
                    if isinstance(item, dict)
                    and str(item.get("instance_id") or "") == instance_id
                ),
                None,
            )
            if detail is None:
                continue
            result = self.status_system.apply_lifecycle_tick(
                current, target_id, detail, moment,
            )
            if not result.ok:
                return EffectResult(
                    mutations=tuple(mutations),
                    events=tuple(events),
                    records=tuple(
                        (*records, *result.records)
                    ),
                    rng_events=tuple(rng_events),
                    node_results=tuple(nodes),
                    unsupported=result.unsupported,
                )
            if result.operation not in {"tick", "expire"}:
                continue
            applied += 1
            current = MutationReducer().apply_all(
                current, result.mutations,
            )
            mutations.extend(result.mutations)
            events.extend(result.events)
            records.extend(result.records)
        records.append(
            SettlementRecord(
                record_type="process_modifier_life_step",
                source="effect_system",
                mutation_id=None,
                process_only=True,
                payload={
                    "target_id": target_id,
                    "target_alias": alias,
                    "life_step_moment": moment,
                    "processed_status_count": applied,
                },
                trace=effect.source.to_json(),
            ).to_json()
        )
        nodes.append(
            ExecutionNodeResult(
                node_kind="effect",
                node_id=effect.effect_id,
                status="complete",
            )
        )
        return EffectResult(
            mutations=tuple(mutations),
            events=tuple(events),
            records=tuple(records),
            rng_events=tuple(rng_events),
            node_results=tuple(nodes),
        )

    def _execute_action_delay_lock(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        standard = (
            effect.payload.get("standard", {})
            if isinstance(effect.payload, dict)
            else {}
        )
        if context is None or standard.get("blocked_reason"):
            return _unsupported_effect(effect, "action_delay_lock_context_or_contract_missing")
        operation = str(standard.get("operation") or "")
        if operation == "lock_action_delay_change":
            alias = str(standard.get("target_alias") or "")
            target_id = (
                str(context.owner_id or "")
                if alias == "ModifierOwnerEntity"
                else str(context.caster_id or "")
            )
            unit = context.state.units.get(target_id)
            if unit is None:
                return _unsupported_effect(effect, "action_delay_lock_target_missing")
            before = unit.flags.get("action_delay_locked")
            metadata = {
                "effect_id": effect.effect_id,
                "lock_operation": operation,
                "target_alias": alias,
                "source_trace": effect.source.to_json(),
            }
            mutation = Mutation(
                "set",
                ("units", unit.unit_id, "flags", "action_delay_locked"),
                before,
                True,
                "lock owner action delay changes",
                "effect_system",
                before_exists="action_delay_locked" in unit.flags,
                metadata=metadata,
            )
            return EffectResult(
                mutations=(mutation,),
                records=(
                    SettlementRecord(
                        "action_delay_lock",
                        "effect_system",
                        mutation.stable_id(),
                        False,
                        {
                            "unit_id": unit.unit_id,
                            "allowed_change": "none",
                            "lock_operation": operation,
                        },
                        effect.source.to_json(),
                    ).to_json(),
                ),
            )
        if operation != "lock_action_delay_except_turn_advance":
            return _unsupported_effect(effect, "action_delay_lock_operation_not_admitted")
        unit = context.state.units.get(context.caster_id)
        if unit is None or unit.flags.get("entity_type") != "battle_event":
            return _unsupported_effect(effect, "action_delay_lock_requires_battle_event")
        before = unit.flags.get("action_delay_locked")
        mutation = Mutation("set", ("units", unit.unit_id, "flags", "action_delay_locked"), before, True,
                            "lock source battle event action delay", "effect_system",
                            before_exists="action_delay_locked" in unit.flags,
                            metadata={"effect_id": effect.effect_id, "source_trace": effect.source.to_json()})
        return EffectResult(mutations=(mutation,), records=(SettlementRecord(
            "action_delay_lock", "effect_system", mutation.stable_id(), False,
            {"unit_id": unit.unit_id, "allowed_change": "turn_based_advance"}, effect.source.to_json(),
        ).to_json(),))

    def _execute_force_kill(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        from .unit_lifecycle import UnitLifecycleSystem
        if context is None or self.status_system is None or self.targets is None:
            return _unsupported_effect(effect, "force_kill_context_missing")
        standard = effect.payload.get("standard", {})
        if standard.get("operation") == "formal_forced_death":
            return self._execute_formal_forced_death(effect, context, standard)
        expression = self.status_system.rules.target_expression(str(standard.get("target_expression_id") or ""))
        if standard.get("operation") != "muted_unit_retirement" or expression is None:
            return _unsupported_effect(effect, "force_kill_contract_missing")
        result = self.targets.resolve_target_expression(
            context.state, expression, context=TargetEvaluationContext(
                caster_id=context.caster_id, effect_owner_id=context.owner_id,
                template_entity_ids=context.template_target_ids,
                parameter_entity_ids=((context.param_entity_id,) if context.param_entity_id else ()),
                selected_target_ids=context.target_resolution.selected if context.target_resolution else (),
                current_target_id=context.current_action_target_id,
                admitted_action_target_fact=context.admitted_action_target_fact,
                expected_action_window_scope=context.expected_action_window_scope,
            ), target_resolution=context.target_resolution, condition_event_payload=context.event_payload,
            binding_sources=context.binding_sources,
        )
        if not result.resolved:
            return _unsupported_effect(effect, result.blocked_reason or "force_kill_targets_unresolved")
        units = [context.state.units[target] for target in result.target_ids]
        if any(u.flags.get("entity_type") != "battle_event" and u.flags.get("summon_kind") != "servant" for u in units):
            return _unsupported_effect(effect, "muted_force_kill_requires_battle_event_or_servant")
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        records: list[dict[str, JSONValue]] = []
        for unit in units:
            if unit.flags.get("entity_type") == "battle_event":
                removed = UnitLifecycleSystem().remove_mutations(context.state, unit.unit_id,
                    reason="remove source battle event without HP/death triggers", source="effect_system",
                    removed_record={"effect_id": effect.effect_id}, source_trace=effect.source.to_json())
                mutations.extend(removed)
                events.extend(event for mutation in removed for event in events_for_mutation(
                    mutation, actor_id=context.caster_id, source_id=effect.effect_id, event_index=context.state.event_index))
                continue
            if unit.lifecycle_status == "defeated":
                # 已被正式击杀的目标退场结果已成立，常规死亡链负责移除。
                continue
            if unit.lifecycle_status != "active":
                return _unsupported_effect(effect, "forced_retirement_requires_active_servant")
            metadata = {"effect_id": effect.effect_id, "effect_source": effect.source.to_json()}
            # Muted forced departure still runs the unit's own departure talent,
            # but produces no hit, HP-change, kill-credit or global death event.
            for field, before, after in (("hp", unit.hp, 0.0), ("lifecycle_status", unit.lifecycle_status, "defeated")):
                mutations.append(Mutation("set", ("units", unit.unit_id, field), before, after,
                    reason="begin forced servant retirement", source="effect_system", metadata=metadata))
            mutations.append(Mutation("set", ("units", unit.unit_id, "flags", "forced_retirement"),
                unit.flags.get("forced_retirement"), True, before_exists="forced_retirement" in unit.flags,
                reason="retain forced retirement until immediate removal", source="effect_system", metadata=metadata))
            events.append(GameEvent("summon.retiring", source_id=unit.unit_id, target_id=unit.unit_id,
                event_id=f"event:{mutations[-1].stable_id()}:retiring", window="summon.retiring",
                payload={"param_entity_id": unit.unit_id, "target_id": unit.unit_id,
                         "mutation_ids": [m.stable_id() for m in mutations[-3:]], **metadata}))
        records = [
            SettlementRecord("unit_retirement", "effect_system", mutation.stable_id(), False,
                             {"target_id": mutation.path[1]}, effect.source.to_json()).to_json()
            for mutation in mutations
        ]
        if standard.get("abort_unused_insert_ability") is True:
            # The muted departure still aborts pending insert abilities of the
            # removed battle event / servant, exactly like the formal forced
            # death path; no HP, hit or death-trigger semantics are produced.
            from .queue import QueueSystem
            for unit in units:
                queue_mutations, queue_events, queue_records = (
                    QueueSystem().abort_unused_insert_entries_for_unit(
                        context.state,
                        unit.unit_id,
                        reason="queue_action_actor_unit_retired",
                        source_trace={
                            "muted_retirement_effect_id": effect.effect_id,
                            "muted_retirement_source": effect.source.to_json(),
                        },
                    )
                )
                mutations.extend(queue_mutations)
                events.extend(queue_events)
                records.extend(queue_records)
        return EffectResult(mutations=tuple(mutations), events=tuple(events),
                            records=tuple(records), rng_events=result.rng_events)

    def _execute_formal_forced_death(
        self,
        effect: EffectIR,
        context: EffectExecutionContext,
        standard: dict[str, JSONValue],
    ) -> EffectResult:
        """Kill one active unit without a hit, damage packet or kill credit."""

        from .mutation_events import mutation_backed_event_id
        from .queue import QueueSystem

        alias = str(standard.get("target_alias") or "")
        if alias == "AbilityTargetEntity":
            selected = (
                tuple(context.target_resolution.selected)
                if context.target_resolution is not None
                else ()
            )
            target_ids = selected
        elif alias == "Caster":
            target_ids = (context.caster_id,)
        else:
            return _unsupported_effect(effect, "formal_forced_death_target_alias_not_admitted")
        if len(target_ids) != 1:
            return _unsupported_effect(effect, "formal_forced_death_requires_single_target")
        unit_id = target_ids[0]
        lifecycle = UnitLifecycleSystem()
        source_trace = effect.source.to_json()
        try:
            mutations, record = lifecycle.forced_death_mutations(
                context.state,
                unit_id,
                effect_id=effect.effect_id,
                effect_source=source_trace,
                source_trace=source_trace,
                target_alias=alias,
            )
        except ValueError as exc:
            return _unsupported_effect(effect, str(exc))
        mutations = list(mutations)
        lifecycle_mutation = mutations[1]
        events: list[GameEvent] = [
            GameEvent(
                "unit.defeated",
                source_id="",
                target_id=unit_id,
                event_id=mutation_backed_event_id(
                    lifecycle_mutation.stable_id(), "unit.defeated"
                ),
                window="unit.defeated",
                process_only=True,
                payload={
                    "record_type": "formal_forced_death",
                    "target_id": unit_id,
                    "defeated_unit_id": unit_id,
                    "param_entity_id": unit_id,
                    "lifecycle_mutation_id": lifecycle_mutation.stable_id(),
                    "hp_mutation_id": record["hp_mutation_id"],
                    "target_before_hp": record["target_before_hp"],
                    "target_after_hp": record["target_after_hp"],
                    "forced_death_kind": record["forced_death_kind"],
                    "forced_death_target_alias": alias,
                    "effect_id": effect.effect_id,
                    "effect_source": source_trace,
                    "source_trace": source_trace,
                    "kill_credit_owner_id": "",
                    "damage_event_id": "",
                    "per_hit_target_context_available": False,
                },
            )
        ]
        death_payload: dict[str, JSONValue] = {
            "unit_id": unit_id,
            "target_alias": alias,
            "forced_death_kind": record["forced_death_kind"],
            "before_hp": record["target_before_hp"],
            "after_hp": record["target_after_hp"],
            "lifecycle_mutation_id": lifecycle_mutation.stable_id(),
            "hp_mutation_id": record["hp_mutation_id"],
            "kill_credit": None,
            "damage": None,
            "effect_id": effect.effect_id,
        }
        hp_mutation = mutations[0]
        record_mutation = mutations[2]
        records: list[dict[str, JSONValue]] = [
            SettlementRecord(
                record_type="unit_forced_death_hp",
                source="effect_system",
                mutation_id=hp_mutation.stable_id(),
                process_only=False,
                payload=death_payload,
                trace=source_trace,
            ).to_json(),
            SettlementRecord(
                record_type="unit_forced_death",
                source="effect_system",
                mutation_id=lifecycle_mutation.stable_id(),
                process_only=False,
                payload=death_payload,
                trace=source_trace,
            ).to_json(),
            SettlementRecord(
                record_type="unit_forced_death_record",
                source="effect_system",
                mutation_id=record_mutation.stable_id(),
                process_only=False,
                payload=death_payload,
                trace=source_trace,
            ).to_json(),
        ]
        if standard.get("abort_unused_insert_ability") is True:
            queue_mutations, queue_events, queue_records = (
                QueueSystem().abort_unused_insert_entries_for_unit(
                    context.state,
                    unit_id,
                    reason="queue_action_actor_unit_defeated",
                    source_trace={
                        "forced_death_effect_id": effect.effect_id,
                        "forced_death_source": source_trace,
                    },
                )
            )
            mutations.extend(queue_mutations)
            events.extend(queue_events)
            records.extend(queue_records)
        return EffectResult(
            mutations=tuple(mutations),
            events=tuple(events),
            records=tuple(records),
        )

    def _execute_finish_retirement(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        from .summon import SummonSystem
        if context is None or self.status_system is None:
            return _unsupported_effect(effect, "immediate_retirement_context_missing")
        standard = effect.payload.get("standard", {})
        if standard.get("operation") == "disable_immediate_death":
            # SetDieImmediately(Enable=false) restores the normal death path.
            # The kernel never latches an "immediate death" mode, so this typed
            # assertion is a process-only settlement record.
            if standard.get("target_alias") != "Caster":
                return _unsupported_effect(
                    effect, "disable_immediate_death_target_not_admitted",
                )
            return EffectResult(
                records=(
                    SettlementRecord(
                        record_type="immediate_death_mode_disabled",
                        source="effect_system",
                        process_only=True,
                        payload={
                            "target_id": context.caster_id,
                            "effect_id": effect.effect_id,
                            "operation": "disable_immediate_death",
                            "source_trace": effect.source.to_json(),
                        },
                    ).to_json(),
                ),
            )
        # Ponytail: admit self retirement first; arbitrary target lists require
        # the same formal target resolver and a multi-unit atomic cleanup.
        if standard.get("operation") != "finish_unit_retirement" or standard.get("target_alias") != "Caster":
            return _unsupported_effect(effect, "immediate_retirement_target_not_admitted")
        unit = context.state.units.get(context.caster_id)
        if standard.get("deathrattle_source") is True:
            # SetDieImmediately inside OnDeathrattle confirms the death instance
            # that the lethal producer already committed. A unit that is still
            # in limbo has an unfinished death and must not be relabeled here;
            # the deathrattle insert itself is paced by its admitted queue entry.
            payload = (
                context.event_payload
                if isinstance(context.event_payload, dict)
                else {}
            )
            death_instance_id = str(payload.get("lifecycle_mutation_id") or "")
            record = unit.flags.get("defeat_record") if unit is not None else None
            if (
                unit is None
                or unit.hp > 0
                or unit.lifecycle_status not in {"defeated", "retiring"}
                or not isinstance(record, dict)
                or not death_instance_id
                or str(record.get("lifecycle_mutation_id") or "")
                != death_instance_id
            ):
                return _unsupported_effect(
                    effect,
                    "deathrattle_immediate_requires_finalized_death_instance",
                )
            return EffectResult(
                records=(
                    SettlementRecord(
                        record_type="deathrattle_immediate_retirement",
                        source="effect_system",
                        process_only=True,
                        payload={
                            "target_id": context.caster_id,
                            "effect_id": effect.effect_id,
                            "death_instance_id": death_instance_id,
                            "lifecycle_status": unit.lifecycle_status,
                            "lifecycle_operation": "deathrattle_die_immediately",
                            "death_already_final": True,
                            "deathrattle_insert_pending": True,
                        },
                        trace=effect.source.to_json(),
                    ).to_json(),
                )
            )
        if (
            unit is not None
            and unit.flags.get("summon_kind") == "summoned_monster"
            and unit.hp <= 0
            and unit.lifecycle_status in {"defeated", "retiring"}
        ):
            return EffectResult(
                records=(
                    SettlementRecord(
                        record_type="immediate_retirement",
                        source="effect_system",
                        process_only=True,
                        payload={
                            "target_id": context.caster_id,
                            "applied": False,
                            "reason": "death_already_settled",
                        },
                        trace=effect.source.to_json(),
                    ).to_json(),
                )
            )
        # 静默强制退场或已提交的正式死亡记录都表示退场结果已成立。
        departure_final = (
            unit is not None
            and (unit.flags.get("forced_retirement") is True
                 or isinstance(unit.flags.get("defeat_record"), dict))
        )
        if (unit is None or unit.flags.get("summon_kind") != "servant" or unit.hp != 0
                or unit.lifecycle_status != "defeated" or not departure_final):
            return _unsupported_effect(effect, "immediate_retirement_requires_forced_servant_departure")
        current = context.state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = []
        events: list[GameEvent] = []
        reducer = MutationReducer()
        for detail in unit.flags.get("status_details", ()):
            plan = StatusLifecyclePlan("remove", unit.unit_id, str(detail["status_id"]), "status_system",
                before_details=tuple(current.units[unit.unit_id].flags.get("status_details", ())),
                existing_detail=detail, source_trace={"effect_source": effect.source.to_json()})
            removed = self.status_system._apply_lifecycle_plan(current, plan)
            if not removed.ok:
                return _unsupported_effect(effect, ",".join(removed.unsupported))
            current = reducer.apply_all(current, removed.mutations)
            mutations.extend(removed.mutations)
            records.extend(removed.records)
            events.extend(removed.events)
        system = SummonSystem(self.status_system.rules)
        plan = system.plan_remove(current, unit.unit_id, "forced_retirement",
            source_trace={"effect_source": effect.source.to_json()},
            admission={"coverage_status": "executable", "remove_source_admitted": True})
        removed = system.apply_remove(current, plan)
        if not removed.plan.ok:
            return _unsupported_effect(effect, removed.plan.blocked_reason)
        return EffectResult(mutations=(*mutations, *removed.mutations), events=(*events, *removed.events),
                            records=(*records, *removed.records))

    def _execute_create_servant(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        from .summon import SummonSystem

        if context is None or self.status_system is None:
            return _unsupported_effect(effect, "servant_create_rulebook_or_context_missing")
        standard = effect.payload["standard"]
        if standard.get("creation_callback_required"):
            continuation = context.task_graph_continuation
            if type(continuation) is not TaskGraphContinuation:
                return _unsupported_effect(effect, "servant_create_continuation_required")
            node_query = self.status_system.rules.query_task_graph_node(continuation.parent_graph_node_id)
            node = node_query.value
            if (node_query.status != "resolved" or node is None
                    or node.graph_id != continuation.parent_graph_id
                    or node.formal_task_id != continuation.parent_formal_task_id
                    or node.opcode != "CreateServant" or node.materialization_status != "materialized"
                    or not any(branch.branch_kind == "servant_created" for branch in node.branches)
                    or not any(ref.reference_kind == "effect" and ref.definition_id == effect.effect_id
                               and ref.resolution_status == "resolved" for ref in node.references)):
                return _unsupported_effect(effect, "servant_create_continuation_not_admitted")
        evaluated_id = _evaluate_numeric(effect, context, standard["servant_id"])
        servant_id = evaluated_id.value
        if (not evaluated_id.ok or type(servant_id) not in (int, float)
                or not math.isfinite(servant_id) or servant_id <= 0 or servant_id != int(servant_id)):
            return _unsupported_effect(effect, "servant_create_id_unresolved_or_invalid")
        definition = self.status_system.rules.servant_definition(f"servant:{int(servant_id)}")
        if definition is None:
            return _unsupported_effect(effect, "servant_create_definition_missing")
        initial_values: dict[str, JSONValue] = {}
        for name, entry in standard["dynamic_values"].items():
            evaluated = _evaluate_numeric(effect, context, entry["expression"])
            if not evaluated.ok or type(evaluated.value) not in (int, float) or not math.isfinite(evaluated.value):
                return _unsupported_effect(effect, "servant_create_parameter_unresolved:" + name)
            initial_values[name] = {"value": float(evaluated.value), "hash": entry["hash"]}
        try:
            spawn_source = IRSource(**standard["spawn_source"])
        except (TypeError, ValueError):
            return _unsupported_effect(effect, "servant_create_spawn_source_invalid")
        summons = SummonSystem(self.status_system.rules)
        plan = summons.plan_spawn_servant(
            context.state,
            definition,
            owner_id=context.caster_id,
            spawn_source=spawn_source,
            initial_values=initial_values,
        )
        result = summons.apply_spawn_servant(context.state, plan, initial_values=initial_values)
        if not result.plan.ok:
            return _unsupported_effect(effect, result.plan.blocked_reason)
        return EffectResult(mutations=result.mutations, events=result.events, rng_events=result.rng_events,
                            records=result.records, dispatched_event_ids=result.dispatched_event_ids,
                            created_unit_ids=result.plan.unit_ids)

    def _execute_change_battle_event_owner(
        self, effect: EffectIR, context: EffectExecutionContext | None,
    ) -> EffectResult:
        standard = effect.payload.get("standard")
        if (
            context is None
            or self.status_system is None
            or self.targets is None
            or not isinstance(standard, dict)
            or standard.get("operation") != "change_battle_event_owner"
            or standard.get("blocked_reason")
        ):
            return _unsupported_effect(
                effect, "change_battle_event_owner_context_or_definition_missing",
            )
        refs = standard.get("target_expression_refs")
        if not isinstance(refs, dict):
            return _unsupported_effect(
                effect, "change_battle_event_owner_target_expression_missing",
            )

        def resolve(field_name: str) -> tuple[tuple[str, ...], str]:
            ref = refs.get(field_name)
            if not isinstance(ref, dict) or ref.get("coverage_status") != "executable":
                return (), "change_battle_event_owner_target_expression_not_admitted"
            expression = self.status_system.rules.target_expression(
                str(ref.get("target_expression_id") or ""),
            )
            if expression is None:
                return (), "change_battle_event_owner_target_expression_missing"
            resolved = self.targets.resolve_target_expression(
                context.state,
                expression,
                context=TargetEvaluationContext(
                    caster_id=context.caster_id,
                    effect_owner_id=context.owner_id,
                    template_entity_ids=context.template_target_ids,
                    parameter_entity_ids=((context.param_entity_id,) if context.param_entity_id else ()),
                    selected_target_ids=context.target_resolution.selected if context.target_resolution else (),
                    current_target_id=context.current_action_target_id,
                    admitted_action_target_fact=context.admitted_action_target_fact,
                    expected_action_window_scope=context.expected_action_window_scope,
                ),
                target_resolution=context.target_resolution,
                condition_event_payload=context.event_payload,
                binding_sources=context.binding_sources,
            )
            if not resolved.resolved:
                return (), resolved.blocked_reason or "change_battle_event_owner_target_unresolved"
            return tuple(resolved.target_ids), ""

        event_ids, event_reason = resolve("BattleEvent")
        if event_reason or len(event_ids) != 1:
            return _unsupported_effect(
                effect, event_reason or "change_battle_event_owner_event_ambiguous",
            )
        owner_ids, owner_reason = resolve("Owner")
        if owner_reason or len(owner_ids) != 1:
            return _unsupported_effect(
                effect, owner_reason or "change_battle_event_owner_owner_ambiguous",
            )
        event_unit_id = event_ids[0]
        new_owner_id = owner_ids[0]
        event_unit = context.state.units.get(event_unit_id)
        new_owner = context.state.units.get(new_owner_id)
        if (
            event_unit is None
            or event_unit.flags.get("entity_type") != "battle_event"
            or event_unit.lifecycle_status != "active"
            or new_owner is None
            or new_owner.lifecycle_status != "active"
            or new_owner_id == event_unit_id
        ):
            return _unsupported_effect(effect, "change_battle_event_owner_units_not_admitted")
        store = store_from_state(context.state)
        evaluated: dict[str, dict[str, JSONValue]] = {}
        for name, entry in (standard.get("dynamic_values") or {}).items():
            evaluated_value = _evaluate_numeric(effect, context, entry["expression"])
            if (
                not evaluated_value.ok
                or type(evaluated_value.value) not in (int, float)
                or not math.isfinite(evaluated_value.value)
            ):
                return _unsupported_effect(
                    effect, "change_battle_event_owner_parameter_unresolved:" + str(name),
                )
            evaluated[str(name)] = {"value": float(evaluated_value.value), "hash": entry.get("hash")}
            store = upsert_dynamic_value(
                store, scope="unit", owner_id=event_unit_id, value_name=str(name),
                hash_key=entry.get("hash"), value=float(evaluated_value.value),
                source_id=effect.effect_id, source_trace=effect.source.to_json(),
            )
        previous_owner_id = str(event_unit.flags.get("owner_id") or "")
        metadata = {
            "effect_id": effect.effect_id,
            "opcode": effect.opcode,
            "battle_event_unit_id": event_unit_id,
            "previous_owner_id": previous_owner_id,
            "previous_summoner_id": str(event_unit.flags.get("summoner_id") or ""),
            "effect_source": effect.source.to_json(),
            "owner_id": new_owner_id,
            "dynamic_values": evaluated,
            "source_trace": effect.source.to_json(),
        }
        owner_before = event_unit.flags.get("owner_id")
        summoner_before = event_unit.flags.get("summoner_id")
        mutations = (
            Mutation("set", ("units", event_unit_id, "flags", "owner_id"), owner_before, new_owner_id,
                     "change battle event owner", "effect_system",
                     before_exists="owner_id" in event_unit.flags, metadata=metadata),
            Mutation("set", ("units", event_unit_id, "flags", "summoner_id"), summoner_before, new_owner_id,
                     "change battle event summoner", "effect_system",
                     before_exists="summoner_id" in event_unit.flags, metadata=metadata),
            Mutation("set", ("global_flags", "dynamic_value_store"),
                     context.state.global_flags.get("dynamic_value_store"), store,
                     "rebind battle event owner parameters", "effect_system",
                     before_exists="dynamic_value_store" in context.state.global_flags, metadata=metadata),
        )
        records = tuple(
            SettlementRecord("battle_event_owner_change", "effect_system", mutation.stable_id(), False,
                             {"unit_id": event_unit_id, "owner_id": new_owner_id,
                              "previous_owner_id": previous_owner_id},
                             effect.source.to_json()).to_json()
            for mutation in mutations
        )
        from .battle_event import bind_battle_event_fact

        return bind_battle_event_fact(
            effect, context, EffectResult(mutations=mutations, records=records),
            source="effect_system",
        )

    def _execute_modify_action_delay(
        self, effect: EffectIR, context: EffectExecutionContext | None,
    ) -> EffectResult:
        standard = effect.payload.get("standard")
        if (
            context is None
            or self.status_system is None
            or not isinstance(standard, dict)
            or standard.get("operation") != "modify_action_delay"
            or standard.get("blocked_reason")
        ):
            return _unsupported_effect(
                effect, "modify_action_delay_context_or_definition_missing",
            )
        target_ids: tuple[str, ...] = ()
        target_expression_id = standard.get("target_expression_id")
        if (
            isinstance(target_expression_id, str)
            and target_expression_id
            and self.targets is not None
        ):
            expression = self.status_system.rules.target_expression(target_expression_id)
            if expression is None or expression.coverage_status != "executable":
                return _unsupported_effect(
                    effect, "modify_action_delay_target_expression_not_admitted",
                )
            resolved = self.targets.resolve_target_expression(
                context.state,
                expression,
                context=TargetEvaluationContext(
                    caster_id=context.caster_id,
                    effect_owner_id=context.owner_id,
                    template_entity_ids=context.template_target_ids,
                    parameter_entity_ids=((context.param_entity_id,) if context.param_entity_id else ()),
                    selected_target_ids=context.target_resolution.selected if context.target_resolution else (),
                    current_target_id=context.current_action_target_id,
                    admitted_action_target_fact=context.admitted_action_target_fact,
                    expected_action_window_scope=context.expected_action_window_scope,
                ),
                target_resolution=context.target_resolution,
                condition_event_payload=context.event_payload,
                binding_sources=context.binding_sources,
            )
            if not resolved.resolved:
                return _unsupported_effect(
                    effect, resolved.blocked_reason or "modify_action_delay_target_unresolved",
                )
            target_ids = tuple(resolved.target_ids)
        else:
            target_id = _resolve_target_alias(
                standard.get("target_alias"),
                caster_id=context.caster_id,
                owner_id=context.owner_id,
                param_entity_id=context.param_entity_id,
                current_action_target_id=context.current_action_target_id,
                state=context.state,
            )
            if target_id in context.state.units:
                target_ids = (target_id,)
        if len(target_ids) != 1 or target_ids[0] not in context.state.units:
            return _unsupported_effect(
                effect, "modify_action_delay_target_ambiguous_or_missing",
            )
        target_id = target_ids[0]
        evaluated = _evaluate_numeric(effect, context, standard.get("normalized_value"))
        if (
            not evaluated.ok
            or evaluated.value is None
            or type(evaluated.value) not in (int, float)
            or not math.isfinite(float(evaluated.value))
        ):
            return _unsupported_effect(
                effect, evaluated.blocked_reason or "modify_action_delay_value_unresolved",
            )
        rule, rule_reason = self.status_system.rules.select_timeline_rule()
        if rule is None:
            return _unsupported_effect(effect, rule_reason or "timeline_engine_rule_missing")
        normalized_value = float(evaluated.value)
        speed = effective_unit_stat(context.state.units[target_id], "speed")
        action_value = abs(normalized_value) * TimelineSystem().full_action_value(speed.value, rule)
        operation = "advance" if normalized_value < 0.0 else "delay"
        metadata = {
            "effect_id": effect.effect_id,
            "opcode": effect.opcode,
            "target_id": target_id,
            "target_alias": str(standard.get("target_alias") or ""),
            "operation": operation,
            "normalized_value": normalized_value,
            "action_value": action_value,
            "numeric_evaluation": evaluated.to_json(),
            "source_trace": effect.source.to_json(),
            "effect_source": effect.source.to_json(),
        }
        adjustment = TimelineSystem().adjust_action_value(
            context.state,
            target_id,
            operation=operation,
            amount=action_value,
            source="effect_system",
            metadata=metadata,
            rule=rule,
        )
        if not adjustment.plan.ok:
            return _unsupported_effect(
                effect,
                adjustment.plan.blocked_reason or "action_delay_timeline_adjustment_blocked",
            )
        after_state = MutationReducer().apply_all(context.state, adjustment.mutations)
        mutation = adjustment.mutations[0] if adjustment.mutations else None
        events = (
            events_for_mutation(
                mutation,
                actor_id=context.caster_id,
                source_id=effect.effect_id,
                event_index=context.state.event_index,
            )
            if mutation is not None
            else ()
        )
        records = (
            *adjustment.records,
            SettlementRecord(
                "action_delay", "effect_system",
                mutation.stable_id() if mutation is not None else None,
                process_only=mutation is None,
                payload={
                    **metadata,
                    "after_action_value": after_state.units[target_id].action_value
                    if target_id in after_state.units
                    else None,
                },
                trace=effect.source.to_json(),
            ).to_json(),
        )
        return EffectResult(
            mutations=adjustment.mutations,
            events=events,
            records=records,
        )

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
            heal_snapshot_protocol = (
                effect.opcode in {"Heal", "HealHP"}
                and self.status_system is not None
                and self.status_system.rules.status_event_family(
                    "OnSnapshotCreate"
                )
                is not None
            )
            if heal_snapshot_protocol and context is not None:
                context = replace(
                    context, include_heal_snapshot_protocol=True
                )
            result = handler(effect, context)
        if context is not None and not result.unsupported and effect_requires_native_fact(effect):
            fact = EffectExecutionFact(effect.effect_id, context)
            result = replace(result, mutations=tuple(
                replace(mutation, effect_execution_fact=fact)
                if (mutation.source == "effect_system" or effect.opcode == "CreateServant")
                and mutation.effect_execution_fact is None
                else mutation for mutation in result.mutations
            ))
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
        if effect.opcode == "ElationOperation" and not elation_effect_is_executable(effect):
            return "blocked"
        if effect.opcode in {"SetActionDelay", "ModifyCurrentSkillDelayCost"}:
            standard = effect.payload.get("standard")
            setting = effect.opcode == "SetActionDelay"
            if (
                setting
                and isinstance(standard, dict)
                and standard.get("operation") == "set_action_delay_zero"
            ):
                normalized = standard.get("normalized_value")
                if (
                    standard.get("blocked_reason")
                    or standard.get("target_alias") != "Caster"
                    or not isinstance(normalized, dict)
                    or normalized.get("value") != 0.0
                ):
                    return "blocked"
            elif (
                setting
                and isinstance(standard, dict)
                and standard.get("operation") == "set_action_delay_normalized"
            ):
                if (
                    standard.get("blocked_reason")
                    or standard.get("target_alias") != "Caster"
                    or not _runtime_numeric_payload_is_executable(standard.get("normalized_value"))
                ):
                    return "blocked"
            elif (not isinstance(standard, dict) or standard.get("blocked_reason")
                    or standard.get("operation") != ("set_action_value" if setting else "current_skill_delay_cost")
                    or not _runtime_numeric_payload_is_executable(standard.get("value" if setting else "normalized_value"))
                    or (setting and standard.get("target_alias") not in {"Caster", "ModifierOwnerEntity", "ParamEntity", "CurrentActionTarget", "AbilityTargetEntity"})
                    or (not setting and standard.get("modify_function") not in {"Set", "Add"})):
                return "blocked"
        if effect.opcode == "CreateServant":
            standard = effect.payload.get("standard")
            if (not isinstance(standard, dict) or standard.get("operation") != "create_servant"
                    or standard.get("blocked_reason") or not _runtime_numeric_payload_is_executable(standard.get("servant_id"))
                    or type(standard.get("creation_callback_required", False)) is not bool
                    or not isinstance(standard.get("spawn_source"), dict) or not standard["spawn_source"]
                    or not isinstance(standard.get("dynamic_values"), dict)
                    or any(not isinstance(name, str) or not name or not isinstance(entry, dict)
                           or not isinstance(entry.get("hash"), str) or not entry["hash"]
                           or not _runtime_numeric_payload_is_executable(entry.get("expression"))
                           for name, entry in standard["dynamic_values"].items())):
                return "blocked"
        if effect.opcode == "TriggerSkipDeadHandler" and effect.payload.get("standard") != {
            "operation": "verify_death_settlement", "source_shape_admitted": True,
        }:
            return "blocked"
        if effect.opcode == "StackStatusResistance":
            standard = effect.payload.get("standard")
            if not (
                isinstance(standard, dict)
                and not standard.get("blocked_reason")
                and standard.get("operation") == "stack_status_resistance"
                and standard.get("target_alias") in {"Caster", "ModifierOwnerEntity"}
                and isinstance(standard.get("behavior_flag"), str)
                and bool(standard["behavior_flag"])
                and _runtime_numeric_payload_is_executable(
                    standard.get("resistance")
                )
            ):
                return "blocked"
        if effect.opcode == "AddModifier" and not _add_modifier_payload_is_executable(effect):
            return "blocked"
        if effect.opcode in {"RemoveModifier", "RemoveSelfModifier"} and not _remove_modifier_payload_is_executable(effect):
            return "blocked"
        if effect.opcode == "DispelStatus" and not _dispel_status_payload_is_executable(effect):
            return "blocked"
        if effect.opcode == "SetModifierValue":
            standard = effect.payload.get("standard")
            if not (isinstance(standard, dict) and not standard.get("blocked_reason")
                    and standard.get("operation") == "modify_modifier_value"
                    and (
                        standard.get("target_alias") in {"Caster", "ModifierOwnerEntity", "ParamEntity", "CurrentTurnOwnerEntity"}
                        or standard.get("target_source") == "callback_triggering_modifier_instance"
                        and standard.get("callback_target_event") == "OnModifierAdd"
                    )
                    and isinstance(standard.get("modifier_name"), str) and standard["modifier_name"]
                    and standard.get("modify_function") in {"Set", "Add"}
                    and standard.get("remove_when_zero") is True
                    and _runtime_numeric_payload_is_executable(standard.get("amount"))
                    and (standard.get("value_kind") in {"Layer", "independent_count"}
                         and not standard.get("modifier_selector")
                         or standard.get("value_kind") == "LifeTime"
                         and standard.get("modifier_selector") == "param_modifier"
                         and standard["modifier_name"] == "ParamModifier"
                         and standard["modify_function"] == "Add")):
                return "blocked"
        if effect.opcode == "InfectModifier":
            standard = effect.payload.get("standard")
            if not (
                isinstance(standard, dict) and not standard.get("blocked_reason")
                and standard.get("operation") == "infect_modifier"
                and standard.get("source_shape_admitted") is True
                and standard.get("use_param_modifier") is True
                and standard.get("source_alias") == "Caster"
                and standard.get("target_alias") == "CasterServant"
                and standard.get("status_dispel_filter") == "AnyStatus"
                and standard.get("infect_type") == "Override"
                and _typed_target_reference_admitted(standard)
            ):
                return "blocked"
        if effect.opcode == "SetModifierValueByBehaviorFlag":
            standard = effect.payload.get("standard")
            flags = standard.get("behavior_flags") if isinstance(standard, dict) else None
            if not (isinstance(standard, dict) and not standard.get("blocked_reason")
                    and standard.get("operation") == "extend_modifier_lifetime"
                    and standard.get("target_alias") == "ParamEntity" and _typed_target_reference_admitted(standard)
                    and isinstance(flags, list) and len(flags) == 1 and isinstance(flags[0], str) and bool(flags[0])
                    and _runtime_numeric_payload_is_executable(standard.get("amount"))):
                return "blocked"
        if effect.opcode in {"Heal", "HealHP", "Shield", "InitShield", "StackShield", "ModifyShield", "ResourceDelta", "ModifySPNew", "ModifyTeamBoostPoint", "ModifyTeamBoostPointMax"} and not _fixed_payload_is_executable(effect):
            return "blocked"
        if effect.opcode == "RemoveShield" and not _remove_shield_payload_is_executable(effect):
            return "blocked"
        if effect.opcode in {"LoseHPByRatio", "LoseHP"} and not _hp_loss_ratio_payload_is_executable(effect):
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

    def _execute_death_settlement_barrier(
        self, effect: EffectIR, context: EffectExecutionContext | None,
    ) -> EffectResult:
        if context is None:
            return _unsupported_effect(effect, "death_settlement_context_missing")
        reason = UnitLifecycleSystem().death_settlement_blocked_reason(context.state)
        if reason:
            return _unsupported_effect(effect, reason)
        return EffectResult(records=(SettlementRecord(
            record_type="unit_lifecycle_barrier", source="unit_lifecycle", process_only=True,
            payload={"effect_id": effect.effect_id, "operation": "verify_death_settlement",
                     "settled_unit_ids": [unit.unit_id for unit in context.state.units.values() if unit.hp <= 0]},
            trace={"effect_source": effect.source.to_json()},
        ).to_json(),))

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
            admitted_action_target_fact=context.admitted_action_target_fact,
            expected_action_window_scope=context.expected_action_window_scope,
            template_target_ids=context.template_target_ids,
            application_instance_id=context.application_instance_id,
            immunity_dispatcher=lambda state, fact: self._dispatch_status_immunity(
                state, fact, event_payload=context.event_payload,
            ),
        )
        return EffectResult(
            events=result.events,
            mutations=result.mutations,
            rng_events=result.rng_events,
            records=result.records,
            unsupported=result.unsupported,
            dispatched_event_ids=result.dispatched_event_ids,
        )

    def _dispatch_status_immunity(
        self, state: BattleState, fact: StatusImmunityFact, *,
        event_payload: dict[str, JSONValue] | None = None,
    ) -> StatusApplicationResult:
        from .event_dispatch import EventDispatchSystem, MAX_CALLBACK_EMITTED_EVENT_DEPTH

        depth = (event_payload or {}).get("mutation_event_depth", 0)
        if type(depth) is not int or depth < 0 or depth >= MAX_CALLBACK_EMITTED_EVENT_DEPTH:
            return StatusApplicationResult(ok=False, unsupported=("status_immunity_event_depth_exceeded",))
        event = GameEvent(
            "status.immunity", source_id=fact.caster_id, target_id=fact.target_id,
            event_id=fact.event_id, window="OnImmuneDebuff", process_only=True,
            status_immunity_fact=fact, payload={"mutation_event_depth": depth + 1},
        )
        result = EventDispatchSystem(self.status_system.rules, self).dispatch_event(
            state, event=event, unit_id=fact.target_id,
            modifier_name=fact.protection_modifier_name,
        )
        if result.errors:
            return StatusApplicationResult(ok=False, records=result.records, unsupported=result.errors)
        return StatusApplicationResult(
            ok=True, mutations=result.mutations, events=result.events,
            rng_events=result.rng_events, records=result.records,
            dispatched_event_ids=result.dispatched_event_ids,
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
            admitted_action_target_fact=context.admitted_action_target_fact,
            expected_action_window_scope=context.expected_action_window_scope,
            template_target_ids=context.template_target_ids,
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
        standard = effect.payload.get("standard")
        if (
            isinstance(standard, dict)
            and standard.get("operation") == "deathrattle_status_cleanup"
        ):
            # The OnDeathrattle cleanup is a real lifecycle transaction: the
            # dying unit's statuses are removed (KeepOnDeathrattle and the
            # callback's own status survive) instead of being relabeled as
            # already settled by an unrelated retirement path.
            cleanup = self.status_system.apply_deathrattle_status_cleanup(
                context.state,
                effect,
                caster_id=context.caster_id,
                source_id=context.source_id,
                owner_id=context.owner_id,
                event_payload=context.event_payload,
            )
            return EffectResult(
                events=cleanup.events,
                mutations=cleanup.mutations,
                rng_events=cleanup.rng_events,
                records=cleanup.records,
                unsupported=cleanup.unsupported,
            )
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
            admitted_action_target_fact=context.admitted_action_target_fact,
            expected_action_window_scope=context.expected_action_window_scope,
            template_target_ids=context.template_target_ids,
        )
        return EffectResult(
            events=result.events,
            mutations=result.mutations,
            rng_events=result.rng_events,
            records=result.records,
            unsupported=result.unsupported,
        )

    def _execute_modifier_value(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        if self.status_system is None or context is None:
            return _unsupported_effect(effect, "modifier_value_context_missing")
        standard = effect.payload["standard"]
        status_instance_id: str | None = None
        if standard.get("target_source") == "callback_triggering_modifier_instance":
            # ParamModifier names the modifier instance supplied by the formal
            # callback producer; only the OnModifierAdd producer carries the
            # added instance identity in its typed payload.
            if (standard.get("modifier_selector") != "param_modifier"
                    or standard.get("modifier_name") != "ParamModifier"
                    or standard.get("callback_target_event") != "OnModifierAdd"):
                return _unsupported_effect(
                    effect, "callback_triggering_modifier_contract_not_admitted")
            fact = context.status_lifecycle_fact
            payload = context.event_payload if isinstance(context.event_payload, dict) else {}
            if (
                type(fact) is not StatusLifecycleFact
                or fact.callback_event != "OnModifierAdd"
                or standard.get("callback_target_event") != fact.callback_event
                or fact.operation not in _CALLBACK_TRIGGERING_OPERATIONS
                or not fact.matches_state(context.state)
                or payload.get("event_id") != fact.event_id
                or payload.get("status_instance_id") != fact.status_instance_id
                or payload.get("target_id") != fact.target_id
                or payload.get("owner_id") != fact.owner_id
            ):
                return _unsupported_effect(
                    effect, "callback_triggering_modifier_fact_missing_or_mismatched")
            target_id = fact.target_id
            status_instance_id = fact.status_instance_id
        else:
            target_id = _resolve_target_alias(standard["target_alias"], caster_id=context.caster_id,
                owner_id=context.owner_id, param_entity_id=context.param_entity_id,
                current_action_target_id=context.current_action_target_id, state=context.state)
            scope = context.param_status_scope if standard.get("modifier_selector") == "param_modifier" else None
            if standard.get("modifier_selector") == "param_modifier" and (
                type(scope) is not TaskGraphStatusScope or scope.owner_id != target_id
            ):
                return _unsupported_effect(effect, "param_modifier_value_scope_missing_or_mismatched")
            status_instance_id = scope.instance_id if scope is not None else None
        evaluation = _evaluate_numeric(effect, context, standard["amount"])
        if not evaluation.ok or evaluation.value is None:
            return _unsupported_effect(effect, evaluation.blocked_reason or "modifier_value_amount_not_bound")
        result = self.status_system.modify_modifier_value(
            context.state, target_id, standard["modifier_name"], standard["value_kind"],
            standard["modify_function"], evaluation.value, caster_id=context.caster_id,
            metadata=_effect_metadata(effect, context, standard, evaluation.value, evaluation),
            status_instance_id=status_instance_id,
        )
        return EffectResult(events=result.events, mutations=result.mutations,
                            records=result.records, unsupported=result.unsupported)

    def _execute_modifier_lifetime(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        if self.status_system is None or self.targets is None or context is None:
            return _unsupported_effect(effect, "modifier_lifetime_context_missing")
        standard = effect.payload["standard"]
        expression, reason = self.status_system.rules.target_expression_resolution(standard["target_expression_id"])
        if expression is None or expression.alias != standard["target_alias"]:
            return _unsupported_effect(effect, reason or "modifier_lifetime_target_inconsistent")
        resolution = self.targets.resolve_target_expression(
            context.state, expression,
            context=TargetEvaluationContext(
                caster_id=context.caster_id, effect_owner_id=context.owner_id,
                template_entity_ids=context.template_target_ids,
                parameter_entity_ids=(context.target_resolution.selected if context.target_resolution else
                                      ((context.param_entity_id,) if context.param_entity_id else ())),
                selected_target_ids=(context.target_resolution.selected if context.target_resolution else ()),
                current_target_id=context.current_action_target_id,
                turn_owner_id=committed_turn_owner_id(context.state),
                admitted_action_target_fact=context.admitted_action_target_fact,
                expected_action_window_scope=context.expected_action_window_scope,
            ), target_resolution=context.target_resolution,
        )
        if not resolution.resolved:
            return _unsupported_effect(effect, resolution.blocked_reason)
        mutations, events, records = [], [], []
        for target_id in resolution.target_ids:
            target_context = replace(context, param_entity_id=target_id, current_action_target_id=target_id)
            evaluation = _evaluate_numeric(effect, target_context, standard["amount"])
            if not evaluation.ok or evaluation.value is None:
                return _unsupported_effect(effect, "modifier_lifetime_amount_not_bound")
            result = self.status_system.extend_modifier_lifetimes(
                context.state, target_id, tuple(standard["behavior_flags"]), evaluation.value,
                metadata=_effect_metadata(effect, target_context, standard, evaluation.value, evaluation),
            )
            if result.unsupported:
                return EffectResult(unsupported=result.unsupported, records=result.records)
            mutations.extend(result.mutations)
            events.extend(result.events)
            records.extend(result.records)
        return EffectResult(events=tuple(events), mutations=tuple(mutations), records=tuple(records),
                            rng_events=resolution.rng_events)

    def _execute_set_hp(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        if context is None:
            return _unsupported_effect(effect, "set_hp requires EffectExecutionContext")
        standard = effect.payload.get("standard")
        if not isinstance(standard, dict):
            return _unsupported_effect(effect, "set_hp effect has no standardized payload")
        blocked_reason = standard.get("blocked_reason")
        if isinstance(blocked_reason, str) and blocked_reason:
            return _unsupported_effect(
                effect,
                f"unsupported_formula:{blocked_reason}",
                {"standard": standard},
            )
        target_id = _resolve_target_alias(
            standard.get("target_alias"),
            caster_id=context.caster_id,
            owner_id=context.owner_id,
            param_entity_id=context.param_entity_id,
            current_action_target_id=context.current_action_target_id,
            target_resolution=context.target_resolution,
        )
        if target_id is None:
            return _unsupported_effect(
                effect,
                "unsupported_or_missing_target_alias:" + str(standard.get("target_alias")),
            )
        amount_result = _evaluate_numeric(effect, context, standard.get("amount"))
        if not amount_result.ok or amount_result.value is None:
            return _unsupported_effect(
                effect,
                "unsupported_formula:" + str(amount_result.blocked_reason or "numeric_evaluation_failed"),
                {"numeric_evaluation": amount_result.to_json(), "standard": standard},
            )
        requested = float(amount_result.value)
        if not math.isfinite(requested) or requested < 0:
            return _unsupported_effect(effect, "unsupported_formula:set_hp_amount_invalid")
        state = context.state
        unit = state.units.get(target_id)
        if unit is None:
            return _unsupported_effect(effect, "target unit is not in state")
        maximum = current_max_hp(unit)
        hp_after = min(requested, maximum) if maximum > 0 else requested
        source_trace = {
            "effect_id": effect.effect_id,
            "effect_source": effect.source.to_json(),
            "set_hp_request": requested,
            "target_id": target_id,
            "current_max_hp": maximum,
        }
        metadata = {
            **source_trace,
            "target_before_hp": unit.hp,
            "target_after_hp": hp_after,
            "hp_adjustment": "set",
        }
        if unit.lifecycle_status == "limbo":
            lifecycle = UnitLifecycleSystem()
            try:
                plan = lifecycle.pending_defeat(state, target_id)
            except ValueError as exc:
                return _unsupported_effect(effect, "set_hp_pending_defeat_invalid:" + str(exc))
            if plan is None:
                return _unsupported_effect(effect, "set_hp_limbo_pending_defeat_missing")
            hp_mutation = Mutation(
                "set",
                ("units", target_id, "hp"),
                unit.hp,
                hp_after,
                "restore a pending unit through SetHP",
                "effect_system",
                metadata={**metadata, "pending_defeat_id": plan.pending_id},
            )
            try:
                rescue = lifecycle.rescue_from_limbo_mutations(state, plan, hp_mutation)
            except ValueError as exc:
                return _unsupported_effect(effect, "set_hp_limbo_rescue_blocked:" + str(exc))
            records = tuple(
                SettlementRecord(
                    record_type="unit_revived" if mutation.path[-1] == "hp" else "unit_lifecycle",
                    source="effect_system",
                    mutation_id=mutation.stable_id(),
                    process_only=False,
                    payload={
                        **metadata,
                        "pending_defeat_id": plan.pending_id,
                        "lifecycle_operation": "unit_limbo_rescued",
                        "mutation_path": list(mutation.path),
                    },
                    trace=source_trace,
                ).to_json()
                for mutation in rescue
            )
            return EffectResult(mutations=rescue, records=records)
        if hp_after == unit.hp:
            return EffectResult(
                records=(
                    SettlementRecord(
                        record_type="set_hp_idempotent",
                        source="effect_system",
                        process_only=True,
                        payload={**metadata, "state_unchanged": True},
                        trace=source_trace,
                    ).to_json(),
                ),
            )
        mutation = Mutation(
            "set",
            ("units", target_id, "hp"),
            unit.hp,
            hp_after,
            "set current HP through SetHP",
            "effect_system",
            metadata=metadata,
        )
        record = SettlementRecord(
            record_type="hp_set",
            source="effect_system",
            mutation_id=mutation.stable_id(),
            process_only=False,
            payload={**metadata, "mutation_path": ["units", target_id, "hp"]},
            trace=source_trace,
        ).to_json()
        events = events_for_mutation(
            mutation,
            actor_id=context.caster_id,
            source_id=context.caster_id,
            event_index=state.event_index,
        )
        return EffectResult(mutations=(mutation,), events=events, records=(record,))
    def _execute_heal(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        return self._execute_targeted_unit_delta(effect, context, self._execute_single_heal)

    def _execute_targeted_unit_delta(
        self, effect: EffectIR, context: EffectExecutionContext | None, worker: EffectHandler,
    ) -> EffectResult:
        standard = effect.payload.get("standard")
        if (not isinstance(standard, dict) or not (
                _group_heal_target_alias_admitted(standard.get("target_alias"))
                or _typed_target_reference_admitted(standard)
                and standard.get("target_alias") not in _FIXED_DELTA_TARGET_ALIASES)):
            return worker(effect, context)
        if context is None or self.targets is None or self.status_system is None:
            return _unsupported_effect(effect, "group_heal_requires_rulebook_target_context")
        expression = self.status_system.rules.target_expression(str(standard.get("target_expression_id") or ""))
        if expression is None or expression.alias != standard["target_alias"]:
            return _unsupported_effect(effect, "group_heal_target_expression_missing_or_inconsistent")
        resolution = self.targets.resolve_target_expression(
            context.state, expression,
            context=TargetEvaluationContext(
                caster_id=context.caster_id, effect_owner_id=context.owner_id,
                template_entity_ids=context.template_target_ids,
                parameter_entity_ids=((context.param_entity_id,) if context.param_entity_id else ()),
                selected_target_ids=(context.target_resolution.selected if context.target_resolution else ()),
                current_target_id=context.current_action_target_id,
                turn_owner_id=committed_turn_owner_id(context.state),
                admitted_action_target_fact=context.admitted_action_target_fact,
                expected_action_window_scope=context.expected_action_window_scope,
            ),
            target_resolution=context.target_resolution,
            condition_event_payload=context.event_payload,
            dynamic_values=context.dynamic_values, binding_sources=_binding_sources(context),
        )
        if not resolution.resolved or not resolution.target_ids:
            return _unsupported_effect(effect, resolution.blocked_reason or "group_heal_targets_missing")
        current = context.state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        rng_events = list(resolution.rng_events)
        records: list[dict[str, JSONValue]] = []
        node_results: list[ExecutionNodeResult] = []
        dispatched: set[str] = set()
        for target_id in resolution.target_ids:
            target = TargetResolution(
                selected=(target_id,), primary=target_id, impact_group=(target_id,),
                reason="resolved", metadata={"group_target_resolution": resolution.to_json()},
            )
            target_context = replace(context, state=current, target_resolution=target,
                param_entity_id=target_id if effect.opcode in {"Heal", "HealHP"} else context.param_entity_id,
                current_action_target_id=target_id)
            worker_effect = effect
            if _resolve_target_alias(standard.get("target_alias"), caster_id=context.caster_id,
                    owner_id=context.owner_id, param_entity_id=context.param_entity_id,
                    current_action_target_id=target_id, target_resolution=target, state=current) is None:
                worker_effect = replace(effect, payload={**effect.payload, "standard": {
                    **standard, "target_alias": "CurrentActionTarget",
                    "resolved_source_target_alias": standard.get("target_alias")}})
            result = worker(worker_effect, target_context)
            if result.unsupported:
                return EffectResult(unsupported=result.unsupported, records=result.records, node_results=result.node_results)
            current = MutationReducer().apply_all(current, result.mutations)
            mutations.extend(result.mutations)
            events.extend(result.events)
            rng_events.extend(result.rng_events)
            records.extend(result.records)
            node_results.extend(result.node_results)
            dispatched.update(result.dispatched_event_ids)
        return EffectResult(
            events=tuple(events), mutations=tuple(mutations), rng_events=tuple(rng_events),
            records=tuple(records), node_results=tuple(node_results),
            dispatched_event_ids=frozenset(dispatched),
        )

    def _execute_single_heal(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
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
            heal_ratio_delta=pre.heal_ratio,
            event_payload={
                **payload,
                "pre_heal_dispatch_active": True,
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
            dispatched_event_ids=pre.dispatched_event_ids | healed.dispatched_event_ids,
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
        return self._execute_targeted_unit_delta(effect, context,
            lambda item, invocation: _execute_fixed_unit_delta(item, invocation, kind="resource_delta"))

    def _execute_hp_loss_ratio(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        return self._execute_targeted_unit_delta(effect, context,
            lambda item, invocation: _execute_hp_loss_ratio(item, invocation, damage_system=self.damage_system))

    def _execute_mechanism_bar_state(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        return _execute_mechanism_bar_state(effect, context)

    def _execute_infect_modifier(self, effect: EffectIR, context: EffectExecutionContext | None) -> EffectResult:
        if self.status_system is None or self.targets is None or context is None:
            return _unsupported_effect(effect, "infect_modifier_context_missing")
        standard = effect.payload.get("standard")
        if not (
            isinstance(standard, dict)
            and not standard.get("blocked_reason")
            and standard.get("operation") == "infect_modifier"
            and standard.get("source_shape_admitted") is True
            and standard.get("use_param_modifier") is True
            and standard.get("source_alias") == "Caster"
            and standard.get("target_alias") == "CasterServant"
        ):
            return _unsupported_effect(effect, "infect_modifier_contract_not_admitted")
        scope = context.param_status_scope
        if type(scope) is not TaskGraphStatusScope:
            return _unsupported_effect(effect, "infect_modifier_param_status_scope_missing")
        if scope.owner_id != context.caster_id:
            return _unsupported_effect(effect, "infect_modifier_source_scope_mismatch")
        expression = self.status_system.rules.target_expression(
            str(standard.get("target_expression_id") or ""))
        if expression is None or expression.alias != standard.get("target_alias"):
            return _unsupported_effect(effect, "infect_modifier_target_expression_missing_or_inconsistent")
        resolution = self.targets.resolve_target_expression(
            context.state,
            expression,
            context=TargetEvaluationContext(
                caster_id=context.caster_id,
                effect_owner_id=context.owner_id,
                template_entity_ids=context.template_target_ids,
                parameter_entity_ids=((context.param_entity_id,) if context.param_entity_id else ()),
                selected_target_ids=(context.target_resolution.selected
                                     if context.target_resolution else ()),
                current_target_id=context.current_action_target_id,
                turn_owner_id=committed_turn_owner_id(context.state),
                admitted_action_target_fact=context.admitted_action_target_fact,
                expected_action_window_scope=context.expected_action_window_scope,
            ),
            target_resolution=context.target_resolution,
            condition_event_payload=context.event_payload,
            dynamic_values=context.dynamic_values,
            binding_sources=_binding_sources(context),
        )
        if not resolution.resolved:
            return _unsupported_effect(effect,
                resolution.blocked_reason or "infect_modifier_target_resolution_failed")
        if not resolution.target_ids:
            return EffectResult(
                rng_events=resolution.rng_events,
                records=(SettlementRecord(
                    record_type="status_infection_empty_group",
                    source="effect_system",
                    process_only=True,
                    payload={
                        "effect_id": effect.effect_id,
                        "source_owner_id": scope.owner_id,
                        "source_instance_id": scope.instance_id,
                        "target_alias": standard.get("target_alias"),
                        "state_unchanged": True,
                    },
                    trace={"effect_source": effect.source.to_json(),
                           "target_expression": resolution.to_json()},
                ).to_json(),),
            )
        result = self.status_system.infect_modifier(
            context.state,
            effect,
            source_owner_id=scope.owner_id,
            source_instance_id=scope.instance_id,
            target_ids=resolution.target_ids,
            caster_id=context.caster_id,
        )
        return EffectResult(
            events=result.events,
            mutations=result.mutations,
            rng_events=resolution.rng_events,
            records=result.records,
            unsupported=result.unsupported,
        )

    def _execute_elation_operation(
        self, effect: EffectIR, context: EffectExecutionContext | None,
    ) -> EffectResult:
        if context is None:
            return _unsupported_effect(effect, "elation_execution_context_missing")
        return execute_elation_operation(context.state,
            self.status_system.rules if self.status_system is not None else None, effect, context)

    def _execute_dynamic_value_operation(
        self,
        effect: EffectIR,
        context: EffectExecutionContext | None,
    ) -> EffectResult:
        return _execute_dynamic_value_operation(
            effect, context, rules=self.status_system.rules if self.status_system is not None else None,
        )

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

    def _execute_regard_attack_type(
        self, effect: EffectIR, context: EffectExecutionContext | None,
    ) -> EffectResult:
        standard = effect.payload.get("standard")
        if (
            context is None or not isinstance(standard, dict) or standard.get("blocked_reason")
            or standard.get("operation") not in {"add_regard_attack_type", "clear_regard_attack_type"}
            or standard.get("target_alias") != "ModifierOwnerEntity"
            or context.owner_id not in context.state.units
        ):
            return _unsupported_effect(effect, "regard_attack_type_context_or_definition_missing")
        unit = context.state.units[context.owner_id]
        before = unit.flags.get("regard_attack_types")
        mapping = dict(before) if isinstance(before, dict) else {}
        original = str(standard["original_attack_type"])
        if standard["operation"] == "add_regard_attack_type":
            mapping[original] = str(standard["regard_attack_type"])
        else:
            mapping.pop(original, None)
        if mapping == (before if isinstance(before, dict) else {}):
            return EffectResult()
        mutation = Mutation(
            op="set", path=("units", context.owner_id, "flags", "regard_attack_types"),
            before=before, after=mapping, reason="change regarded attack types", source="effect_system",
            before_exists="regard_attack_types" in unit.flags,
            metadata={"effect_id": effect.effect_id, "opcode": effect.opcode,
                      "operation": standard["operation"], "effect_source": effect.source.to_json()},
        )
        return EffectResult(mutations=(mutation,), records=(SettlementRecord(
            record_type="regard_attack_type", source="effect_system", mutation_id=mutation.stable_id(),
            process_only=False, payload={"effect_id": effect.effect_id, "target_id": context.owner_id,
                                         "before": before, "after": mapping},
            trace={"effect_source": effect.source.to_json()},
        ).to_json(),))

    def _execute_attach_entity_unselectable(
        self,
        effect: EffectIR,
        context: EffectExecutionContext | None,
    ) -> EffectResult:
        return _execute_attach_entity_unselectable(effect, context)

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
        standard = effect.payload.get("standard")
        if (
            isinstance(standard, dict)
            and standard.get("operation_type") == "Protected"
        ):
            return _execute_protected_weakness(
                effect, context, rules=rules, status_system=self.status_system
            )
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
    if standard.get("blocked_reason") or type(standard.get("only_remove_caster_added", False)) is not bool:
        return False
    has_modifier = isinstance(standard.get("modifier_name"), str) and bool(standard.get("modifier_name"))
    has_status = isinstance(standard.get("status_id"), str) and bool(standard.get("status_id"))
    if effect.opcode == "RemoveSelfModifier":
        return remove_self_intrinsic_target_admitted(standard)
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


_FIXED_DELTA_TARGET_ALIASES = SUPPORTED_EFFECT_TARGET_ALIASES | {
    "AbilityTargetEntity",
    # Servant passives grant resources to their summoner.
    "CasterSummoner",
}
_GROUP_HEAL_TARGET_ALIASES = {"AllTeamMember", "AllLightTeam", "CasterServant"}
_GROUP_HEAL_ALIAS_TOKENS = _GROUP_HEAL_TARGET_ALIASES | {
    "AbilityTargetEntity",
    "AllEnemy",
}
_DOTTED_RELATION_TOKEN = re.compile(
    r"^(Caster|ModifierOwnerEntity|ParamEntity|AbilityTargetEntity)"
    r"\.(GetServant|GetSummoner)$"
)
# A dotted target alias starts from one committed entity and follows the
# summon ownership relation. GetServant and GetSummoner name the two
# directions of the same structural relation, not a second owner concept.
_DOTTED_TARGET_RELATION = {
    "GetServant": "summon.owned",
    "GetSummoner": "summon.summoner",
}


def _group_heal_target_alias_admitted(alias: object) -> bool:
    """Admit plain group aliases and set expressions of admitted aliases."""

    if not isinstance(alias, str) or not alias:
        return False
    if alias in _GROUP_HEAL_TARGET_ALIASES:
        return True
    if not any(operator in alias for operator in (" - ", "+", "|")):
        return False
    tokens = [
        token.strip()
        for token in re.split(r"\s*(?:-|\+|\|)\s*", alias)
        if token.strip()
    ]
    if len(tokens) < 2:
        return False
    return all(
        token in _GROUP_HEAL_ALIAS_TOKENS
        or _DOTTED_RELATION_TOKEN.fullmatch(token) is not None
        for token in tokens
    )


def _fixed_delta_target_admitted(standard: dict[str, JSONValue]) -> bool:
    return (standard.get("target_alias") in _FIXED_DELTA_TARGET_ALIASES
            or _typed_target_reference_admitted(standard))


def _fixed_payload_is_executable(effect: EffectIR) -> bool:
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return False
    if standard.get("blocked_reason"):
        return False
    resource = standard.get("resource")
    kind = str(standard.get("kind") or "")
    if _formula_type_blocked(effect, standard, kind):
        return False
    if kind in {"heal", "shield"} and "flat_addition" in standard:
        if not _runtime_numeric_payload_is_executable(standard["flat_addition"]):
            return False
    if kind == "shield" and "max_capacity" in standard:
        if not _runtime_numeric_payload_is_executable(standard["max_capacity"]):
            return False
    team_resource = resource in {"skill_points", "max_skill_points"}
    if not team_resource and not _fixed_delta_target_admitted(standard):
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
        (standard.get("target_alias") in SUPPORTED_EFFECT_TARGET_ALIASES
         or _typed_target_reference_admitted(standard))
        and standard.get("ratio_type") in {"MaxHP", "CurrentHP", "Fixed"}
        and _runtime_numeric_payload_is_executable(standard.get("ratio"))
        and (
            "minimum_hp" not in standard
            or _runtime_numeric_payload_is_executable(standard["minimum_hp"])
        )
    )


def _mechanism_bar_payload_is_executable(effect: EffectIR) -> bool:
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict) or standard.get("blocked_reason"):
        return False
    if standard.get("bar_type") is not None and not (
        type(standard["bar_type"]) is int or isinstance(standard["bar_type"], str) and standard["bar_type"]
    ):
        return False
    numeric = [standard[key] for key in ("current_count", "max_count", "active_count", "cooldown") if key in standard]
    return (
        all(_runtime_numeric_payload_is_executable(value) for value in numeric)
        and (standard.get("state") is not None
        or standard.get("active") is not None
        or bool(numeric))
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
        and standard.get("operation_type") in {"Attach", "Protected"}
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
    formula_reason = _formula_type_blocked(effect, standard, str(standard.get("kind") or ""))
    if formula_reason:
        return formula_reason
    if standard.get("kind") in {"heal", "shield"} and "flat_addition" in standard:
        if not _runtime_numeric_payload_is_executable(standard["flat_addition"]):
            return "flat_addition_not_executable"
    if standard.get("kind") == "shield" and "max_capacity" in standard:
        if not _runtime_numeric_payload_is_executable(standard["max_capacity"]):
            return "shield_max_capacity_not_executable"
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
        if effect.opcode == "RemoveSelfModifier":
            if not remove_self_intrinsic_target_admitted(standard):
                return "remove_self_intrinsic_target_invalid"
        elif not _typed_target_reference_admitted(standard):
            return "target_expression_id_missing_or_not_executable"
    if effect.opcode in {"Heal", "HealHP", "Shield", "InitShield", "StackShield", "ModifyShield", "ResourceDelta", "ModifySPNew"}:
        if not _fixed_delta_target_admitted(standard):
            return f"unsupported_or_missing_target_alias:{standard.get('target_alias')}"
        if not _runtime_numeric_payload_is_executable(standard.get("amount", standard.get("delta"))):
            return "fixed_or_bound_numeric_required"
        if effect.opcode in {"ResourceDelta", "ModifySPNew"} and not isinstance(standard.get("resource"), str):
            return "resource_missing"
    if effect.opcode in {"LoseHPByRatio", "LoseHP"}:
        if standard.get("target_alias") not in SUPPORTED_EFFECT_TARGET_ALIASES:
            return f"unsupported_or_missing_target_alias:{standard.get('target_alias')}"
        if standard.get("ratio_type") not in {"MaxHP", "CurrentHP", "Fixed"}:
            return f"hp_loss_ratio_type_not_supported:{standard.get('ratio_type')}"
        if not _runtime_numeric_payload_is_executable(standard.get("ratio")):
            return "fixed_or_bound_ratio_required"
        if "minimum_hp" in standard and not _runtime_numeric_payload_is_executable(standard["minimum_hp"]):
            return "fixed_or_bound_hp_loss_minimum_required"
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
            target_resolution=context.target_resolution,
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
    amount, formula_details, formula_reason = _resolve_formula_amount(
        kind, context.state, standard, target_id, context.caster_id, amount_result.value,
        action_definition=context.action_definition,
    )
    if formula_reason:
        return _unsupported_effect(
            effect,
            formula_reason,
            {"numeric_evaluation": amount_result.to_json(), "standard": standard},
        )
    flat_addition_result = None
    if kind in {"heal", "shield"} and "flat_addition" in standard:
        flat_addition_result = _evaluate_numeric(
            effect,
            context,
            standard.get("flat_addition"),
        )
        if not flat_addition_result.ok or flat_addition_result.value is None:
            return _unsupported_effect(
                effect,
                f"unsupported_formula:{kind}_flat_addition_evaluation_failed",
                {
                    "numeric_evaluation": amount_result.to_json(),
                    "flat_addition_evaluation": flat_addition_result.to_json(),
                    "standard": standard,
                },
            )
        amount += float(flat_addition_result.value)
        formula_details["flat_addition"] = float(flat_addition_result.value)
        formula_details["flat_addition_evaluation"] = flat_addition_result.to_json()
    if not math.isfinite(amount) or (kind == "heal" and amount < 0.0):
        return _unsupported_effect(effect, f"unsupported_formula:{kind}_amount_invalid")
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
        transient_ratio_raw = context.heal_ratio_delta
        transient_ratio = (
            float(transient_ratio_raw)
            if isinstance(transient_ratio_raw, (int, float))
            and not isinstance(transient_ratio_raw, bool)
            else None
        )
        if transient_ratio is None or not math.isfinite(transient_ratio):
            return _unsupported_effect(effect, "heal_ratio_delta_invalid")
        healing_multiplier = max(
            0.0,
            1.0 + outgoing.value + incoming.value + transient_ratio,
        )
        formula_details["base_amount"] = amount
        amount *= healing_multiplier
        formula_details["healing_multiplier"] = healing_multiplier
        formula_details["outgoing_healing_ratio"] = outgoing.to_json()
        formula_details["incoming_healing_ratio"] = incoming.to_json()
        formula_details["transient_heal_ratio"] = transient_ratio
        after = max(0.0, min(current_max_hp(unit), unit.hp + amount))
        formula_details["offered_healing"] = amount
        formula_details["realized_healing"] = after - unit.hp
        formula_details["overheal"] = max(0.0, amount - (after - unit.hp))
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
            include_heal_snapshot=(
                kind == "heal" and context.include_heal_snapshot_protocol
            ),
        )
    if kind == "shield":
        caster = state.units.get(context.caster_id)
        if caster is None:
            return _unsupported_effect(effect, "shield caster is not in state")
        shield_bonus = effective_unit_stat(caster, "shield_added_ratio")
        shield_multiplier = max(0.0, 1.0 + shield_bonus.value)
        formula_details["base_amount"] = amount
        amount *= shield_multiplier
        formula_details["shield_multiplier"] = shield_multiplier
        formula_details["shield_added_ratio"] = shield_bonus.to_json()
        max_capacity = None
        if "max_capacity" in standard:
            capacity_result = _evaluate_numeric(effect, context, standard["max_capacity"])
            if not capacity_result.ok or capacity_result.value is None:
                return _unsupported_effect(effect, "unsupported_formula:shield_max_capacity_evaluation_failed")
            # PR8 leaves bonus participation in the stack cap disputed; do not choose a policy.
            if shield_bonus.value != 0.0:
                return _unsupported_effect(effect, "shield_bonus_stack_cap_policy_unconfirmed", {
                    "research_source": "https://github.com/yaelysia/hsr-battle-simulator/blob/bd417912e57f1e8196ae6a6ebbdf7b2e4509675b/docs/tbgd_evidence/shared/shield_depletion_callbacks_and_stack_cap_evidence_v1.md#6-shield-bonus-and-cap-useful-public-model-unresolved-contradiction",
                })
            max_capacity = capacity_result.value
            formula_details["max_capacity"] = max_capacity
            formula_details["max_capacity_evaluation"] = capacity_result.to_json()
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
            max_capacity=max_capacity,
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
        if not result.ok:
            return _unsupported_effect(
                effect,
                result.blocked_reason or "shield_application_blocked",
                {"standard": standard, "numeric_evaluation": amount_result.to_json()},
            )
        return EffectResult(
            events=result.events,
            mutations=(result.mutation,) if result.mutation is not None else (),
            records=result.records,
        )
    if kind == "resource_delta" and resource == "energy":
        raw_amount = amount
        operation = standard.get("operation", "add")
        if operation not in {"add", "set"}:
            return _unsupported_effect(effect, "unsupported_formula:energy_operation_invalid")
        affected_by_regeneration = standard.get(
            "affected_by_energy_regeneration",
            True if effect.opcode == "ResourceDelta" else None,
        )
        if type(affected_by_regeneration) is not bool:
            return _unsupported_effect(effect, "unsupported_formula:energy_regeneration_policy_missing")
        energy_regeneration = effective_unit_stat(
            unit,
            "energy_regeneration_rate",
        )
        energy_multiplier = (
            max(0.0, 1.0 + energy_regeneration.value)
            if raw_amount > 0.0 and operation == "add" and affected_by_regeneration
            else 1.0
        )
        amount = raw_amount * energy_multiplier
        formula_details["raw_energy_delta"] = raw_amount
        formula_details["affected_by_energy_regeneration"] = affected_by_regeneration
        formula_details["energy_regeneration_multiplier"] = energy_multiplier
        formula_details["energy_regeneration_rate"] = (
            energy_regeneration.to_json()
        )
        cap = unit.max_energy if unit.max_energy > 0 else unit.energy + amount
        after = max(0.0, min(cap, amount if operation == "set" else unit.energy + amount))
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
        fact = context.shield_exhaustion_fact
        if (
            result.blocked_reason == "shield_removal_source_instance_missing"
            and type(fact) is ShieldExhaustionFact
            and event_payload.get("lifecycle_operation") == "remove"
            and event_payload.get("event_window") == "OnDestroy"
            and fact.owns(target_id, owner_modifier_name, status_instance_id, context.caster_id)
        ):
            return EffectResult(records=(
                SettlementRecord(
                    record_type="shield_remove",
                    source="shield_system",
                    process_only=True,
                    payload={
                        "target_id": target_id,
                        "owner_modifier_name": owner_modifier_name,
                        "status_instance_id": status_instance_id,
                        "reason": "already_exhausted_by_same_shield_mutation",
                        "exhaustion_mutation_id": fact.mutation.stable_id(),
                    },
                    trace=source_trace,
                ).to_json(),
            ))
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
        target_resolution=context.target_resolution, state=context.state,
    )
    if target_id is None:
        return _unsupported_effect(effect, f"unsupported_or_missing_target_alias:{standard.get('target_alias')}", {"standard": standard})
    if target_id not in context.state.units:
        return _unsupported_effect(effect, f"target unit {target_id!r} is not in state", {"standard": standard})
    ratio_type = standard.get("ratio_type")
    if ratio_type not in {"MaxHP", "CurrentHP", "Fixed"}:
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
    # Fixed：LoseHP 的 DamageValue 即扣减量；比例类型仍按生命基数相乘。
    base_hp = 1.0 if ratio_type == "Fixed" else current_max_hp(target) if ratio_type == "MaxHP" else target.hp
    amount = base_hp * ratio
    requested_amount = amount
    minimum_hp = None
    minimum_hp_evaluation = None
    if "minimum_hp" in standard:
        floor_result = _evaluate_numeric(effect, context, standard["minimum_hp"])
        if not floor_result.ok or floor_result.value is None or floor_result.value < 0:
            return _unsupported_effect(
                effect,
                f"unsupported_formula:{floor_result.blocked_reason or 'hp_loss_minimum_invalid'}",
                {"minimum_hp_evaluation": floor_result.to_json(), "standard": standard},
            )
        minimum_hp = floor_result.value
        minimum_hp_evaluation = floor_result.to_json()
        # PR8: Floor bounds remaining HP; it does not round the loss to an integer.
        amount = min(amount, max(0.0, target.hp - minimum_hp))
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
            "rounding_policy": "none",
            "requested_hp_loss": requested_amount,
            "minimum_hp": minimum_hp,
            "minimum_hp_evaluation": minimum_hp_evaluation,
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
    target_max_hp = current_max_hp(target)
    if target_max_hp <= 0:
        return _unsupported_effect(
            effect,
            "hp_loss_dynamic_result_max_hp_not_positive",
            {"standard": standard, "target_id": target_id},
        )
    actual_loss = max(0.0, before_hp - after_hp)
    applied_ratio = actual_loss / float(target_max_hp)
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
            "max_hp": float(target_max_hp),
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
            "max_hp": float(target_max_hp),
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
        target_resolution=context.target_resolution,
        state=context.state,
    )
    state = context.state
    if target_id not in state.units:
        return _unsupported_effect(effect, f"target unit {target_id!r} is not in state")
    unit = state.units[target_id]
    before_bars = unit.flags.get("mechanism_bars", {})
    if not isinstance(before_bars, dict):
        return _unsupported_effect(effect, "mechanism_bar_state_invalid")
    before = {str(key): value for key, value in before_bars.items()}
    if (not before and standard.get("bar_type") is None and standard.get("active") == "False"
            and standard.get("state") is None
            and not any(key in standard for key in ("current_count", "max_count", "active_count", "cooldown"))):
        # Hiding an absent presentation bar has no state or resource effect.
        # Do not invent an identity, or block gameplay on an uncreated display.
        return EffectResult(records=(SettlementRecord(
            "mechanism_bar_hide_absent", "effect_system", process_only=True,
            payload={"target_id": target_id, "active": False}, trace=effect.source.to_json(),
        ).to_json(),))
    if standard.get("bar_type") is None:
        # Source partial updates omit BarType. ponytail: resolve only one already
        # initialized owner bar; multiple bars need an explicit source identity.
        if len(before) != 1:
            return _unsupported_effect(effect, "mechanism_bar_identity_ambiguous" if before else "mechanism_bar_identity_missing")
        bar_key = next(iter(before))
        if not bar_key or not isinstance(before[bar_key], dict) or not before[bar_key]:
            return _unsupported_effect(effect, "mechanism_bar_state_invalid")
    else:
        bar_key = str(standard["bar_type"])
    bar_state = dict(before.get(bar_key, {})) if isinstance(before.get(bar_key), dict) else {}
    for key in ("state", "active"):
        if standard.get(key) is not None:
            bar_state[key] = standard[key]
    numeric_evaluations: dict[str, JSONValue] = {}
    for key in ("current_count", "max_count", "active_count", "cooldown"):
        if key not in standard:
            continue
        result = _evaluate_numeric(effect, context, standard[key])
        numeric_evaluations[key] = result.to_json()
        if not result.ok or result.value is None:
            return _unsupported_effect(effect, result.blocked_reason or f"mechanism_bar_numeric_failed:{key}",
                                       {"numeric_evaluations": numeric_evaluations})
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
        reason="apply mechanism bar state effect",
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
        mutation_id=mutation.stable_id() if before != after else None,
        process_only=before == after,
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
    return EffectResult(mutations=(mutation,) if before != after else (), records=(record,))


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


def _execute_stack_custom_unselectable(
    effect: EffectIR,
    context: EffectExecutionContext | None,
) -> EffectResult:
    """Make the modifier owner unselectable for one team (or every team)."""

    standard = effect.payload.get("standard") if isinstance(effect.payload, dict) else None
    if (
        context is None or not isinstance(standard, dict)
        or standard.get("operation") != "stack_custom_unselectable"
        or standard.get("blocked_reason")
        or standard.get("selector_team") not in {"all", "TeamDark", "TeamLight"}
    ):
        return _unsupported_effect(effect, "stack_custom_unselectable_source_not_admitted")
    target_id = context.owner_id or ""
    if target_id not in context.state.units:
        return _unsupported_effect(effect, "stack_custom_unselectable_target_missing")
    unit = context.state.units[target_id]
    before = unit.flags.get("custom_unselectable_teams")
    teams = sorted({*(before if isinstance(before, (list, tuple)) else ()), str(standard["selector_team"])})
    mutation = Mutation(
        op="set",
        path=("units", target_id, "flags", "custom_unselectable_teams"),
        before=before,
        after=teams,
        reason="stack custom unselectable for selector team",
        source="effect_system",
        before_exists="custom_unselectable_teams" in unit.flags,
        metadata={"effect_id": effect.effect_id, "opcode": effect.opcode,
                  "operation": "stack_custom_unselectable", "selector_team": standard["selector_team"],
                  "effect_source": effect.source.to_json()},
    )
    record = SettlementRecord(
        record_type="stack_custom_unselectable", source="effect_system",
        mutation_id=mutation.stable_id(), process_only=False,
        payload={"effect_id": effect.effect_id, "target_id": target_id,
                 "selector_team": standard["selector_team"]},
        trace={"effect_source": effect.source.to_json()},
    ).to_json()
    return EffectResult(mutations=(mutation,), records=(record,))


def _execute_attach_entity_unselectable(
    effect: EffectIR,
    context: EffectExecutionContext | None,
) -> EffectResult:
    if context is None:
        return _unsupported_effect(
            effect,
            "AttachEntityUnselectable requires EffectExecutionContext",
        )
    standard = effect.payload.get("standard")
    if (
        not isinstance(standard, dict)
        or standard.get("operation") != "attach_entity_unselectable"
        or standard.get("blocked_reason")
        or standard.get("target_alias") != "ModifierOwnerEntity"
    ):
        return _unsupported_effect(
            effect,
            "attach_entity_unselectable_source_not_admitted",
        )
    target_id = _resolve_target_alias(
        standard.get("target_alias"),
        caster_id=context.caster_id,
        owner_id=context.owner_id,
        param_entity_id=context.param_entity_id,
        current_action_target_id=context.current_action_target_id,
        target_resolution=context.target_resolution,
        state=context.state,
    )
    if not target_id or target_id not in context.state.units:
        return _unsupported_effect(
            effect,
            "attach_entity_unselectable_target_missing",
        )
    unit = context.state.units[target_id]
    before = unit.flags.get("target_unselectable")
    mutation = Mutation(
        op="set",
        path=("units", target_id, "flags", "target_unselectable"),
        before=before,
        after=True,
        reason="attach entity unselectable",
        source="effect_system",
        before_exists="target_unselectable" in unit.flags,
        metadata={
            "effect_id": effect.effect_id,
            "opcode": effect.opcode,
            "operation": "attach_entity_unselectable",
            "target_alias": "ModifierOwnerEntity",
            "effect_source": effect.source.to_json(),
        },
    )
    record = SettlementRecord(
        record_type="attach_entity_unselectable",
        source="effect_system",
        mutation_id=mutation.stable_id(),
        process_only=False,
        payload={
            "effect_id": effect.effect_id,
            "target_id": target_id,
            "target_alias": "ModifierOwnerEntity",
            "path": list(mutation.path),
            "before": before,
            "after": True,
        },
        trace={"effect_source": effect.source.to_json()},
    ).to_json()
    return EffectResult(mutations=(mutation,), records=(record,))


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
            template_entity_ids=context.template_target_ids,
            effect_owner_id=context.owner_id,
            parameter_entity_ids=((context.param_entity_id,) if context.param_entity_id else ()),
            selected_target_ids=(
                tuple(context.target_resolution.selected)
                if context.target_resolution is not None and context.target_resolution.selected
                else ((context.current_action_target_id,) if context.current_action_target_id else ())
            ),
            current_target_id=context.current_action_target_id,
            turn_owner_id=committed_turn_owner_id(context.state),
            admitted_action_target_fact=context.admitted_action_target_fact,
            expected_action_window_scope=context.expected_action_window_scope,
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


def _execute_protected_weakness(
    effect: EffectIR,
    context: EffectExecutionContext | None,
    *,
    rules: RuleBook | None,
    status_system: StatusSystem | None,
) -> EffectResult:
    """Record the source-declared protected weakness types on its own status.

    OPType Protected marks existing weakness types as protected through the
    status that declares them; it is not a weakness attachment. The exact
    ModifierOwnerEntity source instance has to match the callback's own status
    detail, so no other unit or status can borrow the protection.
    """

    if context is None or status_system is None or rules is None:
        return _unsupported_effect(
            effect, "stack_weakness_protected_context_missing"
        )
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return _unsupported_effect(
            effect, "stack_weakness_protected_payload_missing"
        )
    if standard.get("target_alias") != "ModifierOwnerEntity":
        return _unsupported_effect(
            effect, "stack_weakness_protected_target_not_admitted"
        )
    weaknesses = standard.get("weaknesses")
    if (
        not isinstance(weaknesses, list)
        or not weaknesses
        or not all(isinstance(item, str) and item for item in weaknesses)
        or len(weaknesses) != len(set(weaknesses))
    ):
        return _unsupported_effect(
            effect, "stack_weakness_protected_list_invalid"
        )
    payload = context.event_payload if isinstance(context.event_payload, dict) else {}
    status_instance_id = str(payload.get("status_instance_id") or "")
    owner_id = str(context.owner_id or "")
    if not status_instance_id or not owner_id:
        return _unsupported_effect(
            effect, "stack_weakness_protected_source_status_missing"
        )
    source_trace = {
        "effect_id": effect.effect_id,
        "effect_source": effect.source.to_json(),
        "status_instance_id": status_instance_id,
        "modifier_name": str(payload.get("modifier_name") or ""),
        "operation_type": str(standard.get("operation_type") or ""),
        "weaknesses": list(weaknesses),
    }
    result = status_system.apply_weakness_protection(
        context.state,
        unit_id=owner_id,
        status_instance_id=status_instance_id,
        elements=tuple(weaknesses),
        effect_id=effect.effect_id,
        source_trace=source_trace,
    )
    return EffectResult(
        events=result.events,
        mutations=result.mutations,
        rng_events=result.rng_events,
        records=result.records,
        unsupported=result.unsupported,
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
            template_entity_ids=context.template_target_ids,
            effect_owner_id=context.owner_id,
            parameter_entity_ids=((context.param_entity_id,) if context.param_entity_id else ()),
            selected_target_ids=(
                tuple(context.target_resolution.selected)
                if context.target_resolution is not None and context.target_resolution.selected
                else ((context.current_action_target_id,) if context.current_action_target_id else ())
            ),
            current_target_id=context.current_action_target_id,
            turn_owner_id=committed_turn_owner_id(context.state),
            admitted_action_target_fact=context.admitted_action_target_fact,
            expected_action_window_scope=context.expected_action_window_scope,
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
    *,
    rules: RuleBook | None = None,
) -> EffectResult:
    if context is None:
        return _blocked_dynamic_value_effect(
            "dynamic_value_operation requires EffectExecutionContext",
        )
    operation = _dynamic_value_operation_spec(effect)
    if operation is None:
        return _blocked_dynamic_value_effect("typed_dynamic_value_operation_missing")
    payload = context.event_payload or {}
    request = DynamicValueExecutionRequest(
        caster_id=context.caster_id,
        source_id=context.source_id,
        effect_id=effect.effect_id,
        opcode=effect.opcode,
        owner_id=context.owner_id or context.caster_id,
        param_entity_id=context.param_entity_id or "",
        current_action_target_id=context.current_action_target_id or "",
        param_status_scope=context.param_status_scope,
        template_target_ids=context.template_target_ids,
        event_payload=payload,
        heal_event_fact=context.heal_event_fact,
        trigger_event=context.trigger_event,
        target_resolution=context.target_resolution,
        admitted_action_target_fact=context.admitted_action_target_fact,
        expected_action_window_scope=context.expected_action_window_scope,
    )
    target_id = resolve_operation_target(context.state, operation, request, rules=rules)
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
    request = replace(
        request,
        ability_instance_id=context.ability_instance_id or str(payload.get("ability_instance_id") or ""),
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
        status_lifecycle_plan=context.status_lifecycle_plan,
    )
    plan = plan_dynamic_value_operation(context.state, operation, request, rules=rules)
    if not plan.ok:
        return _blocked_dynamic_value_effect(plan.blocked_reason)
    executed = execute_dynamic_value_plan(context.state, plan, rules=rules)
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
    include_heal_snapshot: bool = False,
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
            include_heal_snapshot=include_heal_snapshot,
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
    store_source = binding_source_from_store_for_units(
        context.state.global_flags.get("dynamic_value_store"),
        unit_ids,
        excluded_status_instance_ids=tuple(
            sorted(shadowed_status_instance_ids)
        ),
        excluded_hashes=shadowed_hashes,
        excluded_names=shadowed_names,
        # 能力作用域的值只对同一能力实例可见；没有能力实例的读取者（状态回调等）
        # 不得读到已结束能力遗留的槽位。
        excluded_scopes=(
            *(("status",) if not context.include_ambient_status_bindings else ()),
            *(("ability",) if not context.ability_instance_id else ()),
        ),
        visible_scope=(
            {"target_id": context.caster_id, "ability_instance_id": context.ability_instance_id}
            if context.ability_instance_id else None
        ),
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
        bases = {
            "HealByBaseValue": "flat",
            "HealByTargetLostHP": "target.lost_hp",
            "HealByTargetMaxHP": "target.max_hp",
            "HealByHealerMaxHP": "caster.max_hp",
            "HealByHealerAttack": "caster.attack",
        }
        # Internal Heal's fixed-amount contract is independent of raw HealHP.
        if formula_type is None and effect.opcode == "Heal":
            formula_type = "HealByBaseValue"
    elif kind == "shield":
        bases = {
            None: "flat",
            "": "flat",
            "ShieldByBaseValue": "flat",
            "ShieldByCasterMaxHP": "caster.max_hp",
            "ShieldByCasterDefence": "caster.defense",
            "ShieldByTargetMaxHP": "target.max_hp",
        }
    else:
        return ""
    if not isinstance(formula_type, (str, type(None))) or formula_type not in bases:
        return f"unsupported_formula:formula_type_not_supported:{formula_type}"
    base = bases[formula_type]
    if standard.get("formula_base", "flat") != base:
        return "unsupported_formula:formula_base_mismatch"
    if standard.get("amount_role", "flat") != ("flat" if base == "flat" else "ratio"):
        return "unsupported_formula:amount_role_mismatch"
    return ""


def _resolve_formula_amount(
    kind: str,
    state: BattleState,
    standard: dict[str, JSONValue],
    target_id: str | None,
    caster_id: str,
    raw_value: float,
    *,
    action_definition: ActionDefinitionIR | None = None,
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
        if scale_basis == "action_sp_base":
            if type(action_definition) is not ActionDefinitionIR:
                return 0.0, details, "unsupported_formula:resource_action_context_missing"
            base, override_blocked = effective_action_property(
                state,
                caster_id,
                action_definition,
                "SPBase",
                float(action_definition.sp_base),
            )
            if override_blocked:
                return 0.0, details, (
                    "unsupported_formula:resource_action_sp_base_override_blocked:"
                    + override_blocked
                )
            if type(base) not in (int, float) or not math.isfinite(base) or base < 0:
                return 0.0, details, "unsupported_formula:resource_action_sp_base_invalid"
            details["base_value"] = base
            details["base_value_source"] = (
                "skill_property_override"
                if base != action_definition.sp_base
                else "action_definition"
            )
            details["definition_id"] = action_definition.definition_id
            return base * raw_value, details, ""
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
        target_max_hp = current_max_hp(target)
        details["base_value"] = target_max_hp
        return target_max_hp * raw_value, details, ""
    if formula_base == "target.lost_hp":
        lost_hp = max(0.0, current_max_hp(target) - target.hp)
        details["base_value"] = lost_hp
        return lost_hp * raw_value, details, ""
    if formula_base == "caster.max_hp":
        caster_max_hp = current_max_hp(caster)
        details["base_value"] = caster_max_hp
        return caster_max_hp * raw_value, details, ""
    if formula_base == "caster.attack":
        effective_attack = effective_unit_stat(caster, "attack")
        details["base_value"] = effective_attack.value
        details["effective_stat"] = effective_attack.to_json()
        return effective_attack.value * raw_value, details, ""
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
    target_resolution: TargetResolution | None = None,
    state: BattleState | None = None,
) -> str | None:
    if alias == "CasterSummoner" and state is not None:
        resolved = EntityRelationResolver().resolve(state, "summon.summoner",
            TargetEvaluationContext(caster_id=caster_id), subject_ids=(caster_id,))
        return resolved.target_ids[0] if resolved.resolved and len(resolved.target_ids) == 1 else None
    if alias == "Caster":
        return caster_id
    if alias == "ModifierOwnerEntity":
        return owner_id or caster_id
    if alias == "ParamEntity":
        return param_entity_id
    if alias == "CurrentActionTarget":
        return current_action_target_id
    if alias in {"CurrentTurnOwnerEntity", "CurrentTurnActionEntity"} and state is not None:
        # The scheduler executes every action as its committed turn owner, so
        # the turn action entity shares the same committed identity.
        return committed_turn_owner_id(state)
    if alias == "AbilityTargetEntity" or (
        isinstance(alias, str) and alias in _GROUP_HEAL_TARGET_ALIASES
    ):
        selected = target_resolution.selected if target_resolution is not None else ()
        return selected[0] if len(selected) == 1 else None
    if isinstance(alias, str) and _group_heal_target_alias_admitted(alias):
        # Composite group aliases resolve through the group heal executor; each
        # per-target pass carries exactly that target in the resolution.
        selected = target_resolution.selected if target_resolution is not None else ()
        return selected[0] if len(selected) == 1 else None
    if alias == "BattleEventCaster" and state is not None:
        caster = state.units.get(caster_id)
        if caster is None or caster.flags.get("entity_type") != "battle_event":
            return None
        resolved = EntityRelationResolver().resolve(
            state, "entity.creator", TargetEvaluationContext(caster_id=caster_id),
            subject_ids=(caster_id,),
        )
        return resolved.target_ids[0] if resolved.resolved and len(resolved.target_ids) == 1 else None
    if alias == "CasterSelfCreateBattleEvent" and state is not None:
        from .target import resolve_created_battle_event_targets

        created = resolve_created_battle_event_targets(state, caster_id)
        return created[0] if len(created) == 1 else None
    if alias == "LevelEntity":
        return "level:global"
    if state is not None and isinstance(alias, str) and "." in alias:
        base_alias, _, relation_token = alias.partition(".")
        relation = _DOTTED_TARGET_RELATION.get(relation_token)
        if relation is not None:
            base_id = _resolve_target_alias(
                base_alias,
                caster_id=caster_id,
                owner_id=owner_id,
                param_entity_id=param_entity_id,
                current_action_target_id=current_action_target_id,
                target_resolution=target_resolution,
                state=state,
            )
            if base_id is None or base_id not in state.units:
                return None
            # 召唤者关系是结构身份：退场中的忆灵仍能定位其召唤者。
            resolved = EntityRelationResolver().resolve(
                state, relation,
                TargetEvaluationContext(caster_id=base_id),
                subject_ids=(base_id,),
                options={"allow_defeated": True} if relation == "summon.summoner" else None,
            )
            return (resolved.target_ids[0]
                    if resolved.resolved and len(resolved.target_ids) == 1 else None)
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
