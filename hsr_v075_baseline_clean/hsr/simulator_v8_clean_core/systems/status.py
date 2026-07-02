from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from ..core.model import BattleState, GameEvent, JSONValue, Mutation, RNGEvent, TargetResolution
from ..core.settlement import SettlementRecord
from ..rules.evaluator import NumericEvaluationContext, RuleEvaluator
from ..rules.ir import EffectIR, RuleEntity
from ..rules.rulebook import RuleBook
from .rng import RNGOutcome, RNGRequest, resolve_rng_request, rng_choices_from_payload, rng_mode_from_payload
from .target import TargetSystem
from .unit_lifecycle import UnitLifecycleSystem


SUPPORTED_EFFECT_TARGET_ALIASES = {"Caster", "ModifierOwnerEntity", "ParamEntity", "CurrentActionTarget"}
SUPPORTED_ADD_MODIFIER_SINGLE_TARGET_ALIASES = SUPPORTED_EFFECT_TARGET_ALIASES | {"AbilityTargetEntity"}
SUPPORTED_ADD_MODIFIER_GROUP_TARGET_ALIASES = {"AllEnemy", "AllTeamMember", "AllLightTeam", "AllTeammate"}
SUPPORTED_ADD_MODIFIER_ALIASES = SUPPORTED_ADD_MODIFIER_SINGLE_TARGET_ALIASES | SUPPORTED_ADD_MODIFIER_GROUP_TARGET_ALIASES
STRICT_ATTACHED_STATUS_TARGET_ALIASES = {"AbilityTargetEntity"} | SUPPORTED_ADD_MODIFIER_GROUP_TARGET_ALIASES
SUPPORTED_DURATION_LIFE_STEP_MOMENTS = {"ModifierPhase1End", "ActionPhaseEnd"}


@dataclass(frozen=True)
class StatusInstance:
    instance_id: str
    status_id: str
    modifier_name: str
    owner_id: str
    source_id: str
    caster_id: str
    stacks: int = 1
    max_stacks: int | None = None
    duration: float | None = None
    dynamic_values: dict[str, JSONValue] = field(default_factory=dict)
    formula_bindings: tuple[dict[str, JSONValue], ...] = ()
    source_trace: dict[str, JSONValue] = field(default_factory=dict)
    modifiers: tuple[dict[str, JSONValue], ...] = ()
    trigger_ids_by_event: dict[str, tuple[str, ...]] = field(default_factory=dict)
    unsupported: tuple[str, ...] = ()
    application_operation: str = "add"
    partial: bool = False
    remaining_duration: float | None = None
    duration_unit: str = "unknown"
    life_step_moment: str = ""
    duration_admission: dict[str, JSONValue] = field(default_factory=dict)
    stack_policy: str = "single_instance"
    refresh_policy: str = "replace_partial"
    lifecycle_state: str = "active"
    status_type: str = "Unknown"
    status_category: str = "unknown"
    can_dispel: bool | None = None
    source_stack_key: str = ""
    control_kind: str = ""
    chance_admission: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "instance_id": self.instance_id,
            "status_id": self.status_id,
            "modifier_name": self.modifier_name,
            "owner_id": self.owner_id,
            "source_id": self.source_id,
            "caster_id": self.caster_id,
            "stacks": self.stacks,
            "max_stacks": self.max_stacks,
            "duration": self.duration,
            "dynamic_values": self.dynamic_values,
            "formula_bindings": [dict(item) for item in self.formula_bindings],
            "source_trace": self.source_trace,
            "modifiers": list(self.modifiers),
            "trigger_ids_by_event": {
                event: list(trigger_ids)
                for event, trigger_ids in sorted(self.trigger_ids_by_event.items())
            },
            "unsupported": list(self.unsupported),
            "application_operation": self.application_operation,
            "partial": self.partial,
            "remaining_duration": self.remaining_duration,
            "duration_unit": self.duration_unit,
            "life_step_moment": self.life_step_moment,
            "duration_admission": self.duration_admission,
            "stack_policy": self.stack_policy,
            "refresh_policy": self.refresh_policy,
            "lifecycle_state": self.lifecycle_state,
            "status_type": self.status_type,
            "status_category": self.status_category,
            "can_dispel": self.can_dispel,
            "source_stack_key": self.source_stack_key,
            "control_kind": self.control_kind,
            "chance_admission": self.chance_admission,
        }


@dataclass(frozen=True)
class StatusLifecyclePlan:
    operation: str
    target_id: str
    status_id: str
    source: str
    status_instance: StatusInstance | None = None
    before_details: tuple[JSONValue, ...] = ()
    existing_detail: dict[str, JSONValue] | None = None
    unsupported: tuple[str, ...] = ()
    partial: bool = False
    source_trace: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "operation": self.operation,
            "target_id": self.target_id,
            "status_id": self.status_id,
            "source": self.source,
            "status_instance": self.status_instance.to_json() if self.status_instance else None,
            "before_details": list(self.before_details),
            "existing_detail": self.existing_detail,
            "unsupported": list(self.unsupported),
            "partial": self.partial,
            "source_trace": self.source_trace,
        }


@dataclass(frozen=True)
class StatusLifecycleResult:
    ok: bool
    operation: str
    mutations: tuple[Mutation, ...] = ()
    events: tuple[GameEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    unsupported: tuple[str, ...] = ()
    status_instance: StatusInstance | None = None
    lifecycle_plan: StatusLifecyclePlan | None = None
    lifecycle_state: str = "unknown"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "operation": self.operation,
            "mutations": [mutation.to_json() for mutation in self.mutations],
            "events": [event.to_json() for event in self.events],
            "records": list(self.records),
            "unsupported": list(self.unsupported),
            "status_instance": self.status_instance.to_json() if self.status_instance else None,
            "lifecycle_plan": self.lifecycle_plan.to_json() if self.lifecycle_plan else None,
            "lifecycle_state": self.lifecycle_state,
        }


@dataclass(frozen=True)
class StatusApplicationResult:
    ok: bool
    mutations: tuple[Mutation, ...] = ()
    events: tuple[GameEvent, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    unsupported: tuple[str, ...] = ()
    status_instance: StatusInstance | None = None
    lifecycle_result: StatusLifecycleResult | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "mutations": [mutation.to_json() for mutation in self.mutations],
            "events": [event.to_json() for event in self.events],
            "rng_events": [event.to_json() for event in self.rng_events],
            "records": list(self.records),
            "unsupported": list(self.unsupported),
            "status_instance": self.status_instance.to_json() if self.status_instance else None,
            "lifecycle_result": self.lifecycle_result.to_json() if self.lifecycle_result else None,
        }


@dataclass(frozen=True)
class _ChanceCheck:
    allowed: bool
    record: dict[str, JSONValue] | None = None
    rng_events: tuple[RNGEvent, ...] = ()
    unsupported: tuple[str, ...] = ()


def status_control_gate_for_actor(actor: object) -> dict[str, JSONValue] | None:
    flags = getattr(actor, "flags", None)
    if not isinstance(flags, dict):
        return None
    details = flags.get("status_details", ())
    if not isinstance(details, (list, tuple)):
        return None
    for detail in details:
        if not isinstance(detail, dict):
            continue
        if str(detail.get("lifecycle_state") or "active").startswith(("expired", "removed")):
            continue
        control_kind = str(detail.get("control_kind") or "")
        status_category = str(detail.get("status_category") or "")
        if not control_kind and status_category != "control":
            continue
        source_trace = detail.get("source_trace")
        if not isinstance(source_trace, dict) or not source_trace:
            continue
        status_instance_id = str(detail.get("instance_id") or "")
        reason = f"status_control_gate:{control_kind or status_category}:{status_instance_id}"
        return {
            "reason": reason,
            "scope": "status_control",
            "actor_id": str(getattr(actor, "unit_id", "") or ""),
            "actor_side": str(getattr(actor, "side", "") or ""),
            "metadata": {
                "status_instance_id": status_instance_id,
                "status_id": str(detail.get("status_id") or ""),
                "modifier_name": str(detail.get("modifier_name") or ""),
                "control_kind": control_kind,
                "status_category": status_category,
            },
            "source_trace": source_trace,
        }
    return None


class StatusSystem:
    def __init__(self, rules: RuleBook | None = None):
        self.rules = rules

    def add_status(self, state: BattleState, unit_id: str, status_id: str, source: str) -> Mutation:
        unit = state.units[unit_id]
        statuses = tuple(dict.fromkeys((*unit.statuses, status_id)))
        return Mutation(
            op="set",
            path=("units", unit_id, "statuses"),
            before=list(unit.statuses),
            after=list(statuses),
            reason="add status",
            source=source,
            metadata={"status_id": status_id},
        )

    def remove_status(self, state: BattleState, unit_id: str, status_id: str, source: str) -> Mutation:
        unit = state.units[unit_id]
        statuses = tuple(item for item in unit.statuses if item != status_id)
        return Mutation(
            op="set",
            path=("units", unit_id, "statuses"),
            before=list(unit.statuses),
            after=list(statuses),
            reason="remove status",
            source=source,
            metadata={"status_id": status_id},
        )

    def apply_add_modifier(
        self,
        state: BattleState,
        effect: EffectIR,
        *,
        caster_id: str,
        source_id: str,
        owner_id: str | None = None,
        param_entity_id: str | None = None,
        current_action_target_id: str | None = None,
        target_resolution: TargetResolution | None = None,
        event_payload: dict[str, JSONValue] | None = None,
        dynamic_values: dict[str, float] | None = None,
        binding_sources: tuple[dict[str, JSONValue], ...] = (),
    ) -> StatusApplicationResult:
        if effect.opcode != "AddModifier":
            return _unsupported_result(effect, "effect is not AddModifier")
        if self.rules is None:
            return _unsupported_result(effect, "StatusSystem requires RuleBook for AddModifier")

        standard = effect.payload.get("standard")
        if not isinstance(standard, dict):
            return _unsupported_result(effect, "AddModifier effect has no standardized payload")
        modifier_name = standard.get("modifier_name")
        if not isinstance(modifier_name, str) or not modifier_name:
            return _unsupported_result(effect, "AddModifier has no modifier_name")
        target_alias = standard.get("target_alias")
        target_ids, target_blocked_reason, target_expression_trace, target_rng_events = self._resolve_add_modifier_targets(
            state,
            standard,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
        )
        if target_blocked_reason:
            return _unsupported_result(
                effect,
                target_blocked_reason,
                trace={"target_expression": target_expression_trace},
                rng_events=target_rng_events,
            )

        definition = _select_modifier_definition(self.rules, modifier_name, effect.source.source_path)
        if definition is None:
            return _unsupported_result(effect, f"unknown modifier definition {modifier_name!r}")

        plans: list[StatusLifecyclePlan] = []
        lifecycle_results: list[StatusLifecycleResult] = []
        status_instances: list[StatusInstance] = []
        process_records: list[dict[str, JSONValue]] = []
        rng_events: list[RNGEvent] = list(target_rng_events)
        blocked_reasons: list[str] = []
        target_resolution_trace = target_resolution.to_json() if target_resolution is not None else None
        strict_target_admission = target_alias in STRICT_ATTACHED_STATUS_TARGET_ALIASES
        for target_id in target_ids:
            resolved_dynamic_values = _resolve_dynamic_values(
                standard,
                definition,
                dynamic_values,
                binding_sources,
                {"effect_id": effect.effect_id, "effect_source": effect.source.to_json()},
            )
            on_create_dynamic_values = _on_create_define_dynamic_values(
                self.rules,
                modifier_name,
                definition.source.source_path,
                state,
                target_id=target_id,
                caster_id=caster_id,
                owner_id=target_id,
                param_entity_id=param_entity_id,
                current_action_target_id=current_action_target_id,
                binding_sources=binding_sources,
                source_trace={"effect_id": effect.effect_id, "effect_source": effect.source.to_json()},
            )
            if on_create_dynamic_values:
                resolved_dynamic_values = _merge_dynamic_values(resolved_dynamic_values, on_create_dynamic_values)
            modifiers, unsupported = _runtime_modifiers(definition, resolved_dynamic_values)
            formula_bindings = _status_formula_bindings(standard)
            before_details = _status_details(unit_flags=state.units[target_id].flags)
            existing_detail = _matching_status_detail(before_details, target_id, modifier_name, effect.effect_id, source_id)
            status_metadata = _status_metadata(self.rules, modifier_name)
            duration_admission = _runtime_duration_admission(
                standard,
                definition,
                effect,
                binding_sources,
                status_metadata=status_metadata,
            )
            stack_admission = _runtime_stack_admission(
                standard,
                effect,
                binding_sources=binding_sources,
            )
            refresh_admission = _runtime_refresh_admission(
                standard,
                definition,
                duration_admission,
                effect,
            )
            chance_admission = _runtime_chance_admission(
                standard,
                effect,
                state,
                caster_id=caster_id,
                target_id=target_id,
                binding_sources=binding_sources,
            )
            status_id = f"modifier:{modifier_name}"
            same_status_other_source = _same_status_other_source_detail(
                before_details,
                status_id=status_id,
                source_stack_key=_source_stack_key(target_id, modifier_name, effect.effect_id, source_id),
            )
            application_operation, partial_reasons = _application_semantics(
                standard,
                existing_detail,
                duration_admission,
                stack_admission,
                refresh_admission,
                same_status_other_source=same_status_other_source,
            )
            unsupported = [*unsupported, *partial_reasons]
            trigger_ids_by_event = _trigger_ids_by_event(self.rules, modifier_name, definition.source.source_path)
            if strict_target_admission:
                blocked_reason = _strict_attached_status_blocked_reason(
                    standard=standard,
                    resolved_dynamic_values=resolved_dynamic_values,
                    duration_admission=duration_admission,
                    trigger_ids_by_event=trigger_ids_by_event,
                    unsupported=tuple(unsupported),
                )
                if blocked_reason:
                    return _unsupported_result(effect, blocked_reason)
            duration = _status_instance_duration_value(duration_admission)
            life_step_moment = str(duration_admission.get("life_step_moment") or "")
            source_stack_key = _source_stack_key(target_id, modifier_name, effect.effect_id, source_id)
            stack_plan = _status_stack_plan(
                existing_detail,
                stack_admission,
                operation=application_operation,
            )
            if application_operation == "stack_reduce" and _stack_plan_stacks_after(stack_plan) <= 0:
                application_operation = "stack_reduce_remove"
                stack_plan = {**stack_plan, "operation": application_operation, "stack_depleted": True}
            refresh_plan = _status_refresh_plan(
                existing_detail,
                duration,
                operation=application_operation,
            )
            chance_check = _status_chance_check(
                state,
                effect,
                chance_admission,
                caster_id=caster_id,
                target_id=target_id,
                modifier_name=modifier_name,
                status_id=status_id,
                source_stack_key=source_stack_key,
                event_payload=event_payload,
            )
            rng_events.extend(chance_check.rng_events)
            if chance_check.record is not None:
                process_records.append(chance_check.record)
            if chance_check.unsupported:
                blocked_reasons.extend(chance_check.unsupported)
                continue
            if not chance_check.allowed:
                continue
            stacks = _stack_plan_stacks_after(stack_plan)
            remaining_duration = _refresh_plan_remaining_after(refresh_plan, duration)
            status_duration = _refresh_plan_duration(refresh_plan, duration)
            status_instance = StatusInstance(
                instance_id=_status_instance_id(target_id, modifier_name, effect.effect_id, source_id),
                status_id=status_id,
                modifier_name=modifier_name,
                owner_id=target_id,
                source_id=source_id,
                caster_id=caster_id,
                stacks=stacks,
                max_stacks=_stack_plan_max_stacks(stack_plan),
                duration=status_duration,
                dynamic_values=resolved_dynamic_values,
                formula_bindings=formula_bindings,
                source_trace={
                    "effect_id": effect.effect_id,
                    "effect_source": effect.source.to_json(),
                    "modifier_name": modifier_name,
                    "modifier_definition": definition.source.to_json(),
                    "status_config": status_metadata.get("source"),
                    "target_alias": target_alias if isinstance(target_alias, str) else "",
                    "target_expression": target_expression_trace,
                    "resolved_target_ids": list(target_ids),
                    "target_resolution": target_resolution_trace,
                    "duration_admission": duration_admission,
                    "stack_admission": stack_admission,
                    "refresh_admission": refresh_admission,
                    "stack_plan": stack_plan,
                    "refresh_plan": refresh_plan,
                    "chance_admission": chance_admission,
                    "source_stack_key": source_stack_key,
                    "status_formula_bindings": [dict(item) for item in formula_bindings],
                    "status_formula_binding_source": _json_safe(standard.get("status_formula_binding_source", {})),
                },
                modifiers=tuple(modifiers),
                trigger_ids_by_event=trigger_ids_by_event,
                unsupported=tuple(unsupported),
                application_operation=application_operation,
                partial=bool(partial_reasons),
                remaining_duration=remaining_duration,
                duration_unit=life_step_moment if duration is not None else "permanent_or_unknown",
                life_step_moment=life_step_moment,
                duration_admission=duration_admission,
                stack_policy=str(stack_admission.get("stack_policy") or "single_instance"),
                refresh_policy=str(refresh_plan.get("refresh_policy") or "none"),
                lifecycle_state="active_partial" if partial_reasons else "active",
                status_type=str(status_metadata.get("status_type") or "Unknown"),
                status_category=str(status_metadata.get("status_category") or "unknown"),
                can_dispel=status_metadata.get("can_dispel") if isinstance(status_metadata.get("can_dispel"), bool) else None,
                source_stack_key=source_stack_key,
                control_kind=str(status_metadata.get("control_kind") or ""),
                chance_admission=chance_admission,
            )
            plans.append(
                StatusLifecyclePlan(
                    operation=application_operation,
                    target_id=target_id,
                    status_id=status_instance.status_id,
                    source="status_system",
                    status_instance=status_instance,
                    before_details=tuple(before_details),
                    existing_detail=existing_detail,
                    unsupported=tuple(unsupported),
                    partial=status_instance.partial,
                    source_trace=status_instance.source_trace,
                )
            )
            status_instances.append(status_instance)
        for plan in plans:
            lifecycle_results.append(self._apply_lifecycle_plan(state, plan))
        mutations = tuple(mutation for result in lifecycle_results for mutation in result.mutations)
        events = tuple(event for result in lifecycle_results for event in result.events)
        records = (*tuple(process_records), *(record for result in lifecycle_results for record in result.records))
        unsupported = (
            *tuple(blocked_reasons),
            *(reason for result in lifecycle_results for reason in result.unsupported),
        )
        lifecycle_result = lifecycle_results[-1] if lifecycle_results else None
        ok = all(result.ok for result in lifecycle_results) if lifecycle_results else bool(process_records)
        ok = ok and not blocked_reasons
        return StatusApplicationResult(
            ok=ok,
            mutations=mutations,
            events=events,
            rng_events=tuple(rng_events),
            records=records,
            unsupported=unsupported,
            status_instance=status_instances[-1] if status_instances else None,
            lifecycle_result=lifecycle_result,
        )

    def _resolve_add_modifier_targets(
        self,
        state: BattleState,
        standard: dict[str, JSONValue],
        *,
        caster_id: str,
        owner_id: str | None,
        param_entity_id: str | None,
        current_action_target_id: str | None,
        target_resolution: TargetResolution | None,
        event_payload: dict[str, JSONValue] | None,
        dynamic_values: dict[str, float] | None,
        binding_sources: tuple[dict[str, JSONValue], ...],
    ) -> tuple[tuple[str, ...], str, dict[str, JSONValue], tuple[RNGEvent, ...]]:
        target_expression_id = standard.get("target_expression_id")
        if isinstance(target_expression_id, str) and target_expression_id and self.rules is not None:
            expression = self.rules.target_expression(target_expression_id)
            if expression is None:
                return (), f"target_expression_missing:{target_expression_id}", {}, ()
            payload_alias = standard.get("target_alias")
            if (
                isinstance(payload_alias, str)
                and payload_alias
                and expression.alias
                and payload_alias != expression.alias
            ):
                return (), f"target_expression_alias_mismatch:{payload_alias}:{expression.alias}", {
                    "target_expression": expression.to_json(),
                    "target_alias": payload_alias,
                }, ()
            result = TargetSystem().resolve_target_expression(
                state,
                expression,
                caster_id=caster_id,
                owner_id=owner_id,
                param_entity_id=param_entity_id,
                current_action_target_id=current_action_target_id,
                target_resolution=target_resolution,
                event_payload=event_payload,
                dynamic_values=dynamic_values,
                binding_sources=binding_sources,
            )
            trace = result.to_json()
            if not result.ok:
                return (), result.blocked_reason, trace, result.rng_events
            return result.target_ids, "", trace, result.rng_events
        target_alias = standard.get("target_alias")
        target_ids, target_blocked_reason = _resolve_add_modifier_target_ids(
            state,
            target_alias,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
        )
        return target_ids, target_blocked_reason, {
            "legacy_target_alias_resolution": True,
            "target_alias": target_alias if isinstance(target_alias, str) else "",
        }, ()

    def apply_remove_modifier(
        self,
        state: BattleState,
        effect: EffectIR,
        *,
        caster_id: str,
        source_id: str,
        owner_id: str | None = None,
        param_entity_id: str | None = None,
        current_action_target_id: str | None = None,
    ) -> StatusApplicationResult:
        if effect.opcode not in {"RemoveModifier", "RemoveSelfModifier"}:
            return _unsupported_result(effect, "effect is not RemoveModifier or RemoveSelfModifier")
        standard = effect.payload.get("standard")
        if not isinstance(standard, dict):
            return _unsupported_result(effect, f"{effect.opcode} effect has no standardized payload")
        target_id = _resolve_target_alias(
            standard.get("target_alias"),
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
        )
        if target_id is None:
            return _unsupported_result(effect, f"unsupported_or_missing_target_alias:{standard.get('target_alias')}")
        if target_id not in state.units:
            return _unsupported_result(effect, f"target unit {target_id!r} is not in state")
        modifier_name = standard.get("modifier_name")
        status_id_value = standard.get("status_id")
        if isinstance(modifier_name, str) and modifier_name:
            status_id = f"modifier:{modifier_name}"
        elif isinstance(status_id_value, str) and status_id_value:
            status_id = status_id_value
            modifier_name = status_id.removeprefix("modifier:")
        else:
            return _unsupported_result(effect, f"{effect.opcode} has no modifier_name or status_id")
        before_details = _status_details(unit_flags=state.units[target_id].flags)
        existing_detail = _find_status_detail(before_details, status_id)
        plan = StatusLifecyclePlan(
            operation="remove",
            target_id=target_id,
            status_id=status_id,
            source="status_system",
            before_details=tuple(before_details),
            existing_detail=existing_detail,
            source_trace={"effect_id": effect.effect_id, "effect_source": effect.source.to_json()},
        )
        lifecycle_result = self._apply_lifecycle_plan(state, plan)
        return StatusApplicationResult(
            ok=lifecycle_result.ok,
            mutations=lifecycle_result.mutations,
            records=lifecycle_result.records,
            unsupported=lifecycle_result.unsupported,
            lifecycle_result=lifecycle_result,
        )

    def apply_dispel_status(
        self,
        state: BattleState,
        effect: EffectIR,
        *,
        caster_id: str,
        source_id: str,
        owner_id: str | None = None,
        param_entity_id: str | None = None,
        current_action_target_id: str | None = None,
        target_resolution: TargetResolution | None = None,
        event_payload: dict[str, JSONValue] | None = None,
        dynamic_values: dict[str, float] | None = None,
        binding_sources: tuple[dict[str, JSONValue], ...] = (),
    ) -> StatusApplicationResult:
        if effect.opcode != "DispelStatus":
            return _unsupported_result(effect, "effect is not DispelStatus")
        if self.rules is None:
            return _unsupported_result(effect, "StatusSystem requires RuleBook for DispelStatus")
        standard = effect.payload.get("standard")
        if not isinstance(standard, dict):
            return _unsupported_result(effect, "DispelStatus effect has no standardized payload")
        if standard.get("blocked_reason"):
            return _unsupported_result(effect, str(standard.get("blocked_reason")))
        target_ids, target_blocked_reason, target_expression_trace, target_rng_events = self._resolve_add_modifier_targets(
            state,
            standard,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
        )
        if target_blocked_reason:
            return _unsupported_result(
                effect,
                target_blocked_reason,
                trace={"target_expression": target_expression_trace},
                rng_events=target_rng_events,
            )
        count_admission = _runtime_dispel_count_admission(
            standard,
            effect,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
        )
        source_trace = {
            "effect_id": effect.effect_id,
            "effect_source": effect.source.to_json(),
            "source_id": source_id,
            "caster_id": caster_id,
            "target_alias": standard.get("target_alias") if isinstance(standard.get("target_alias"), str) else "",
            "target_expression": target_expression_trace,
            "target_resolution": target_resolution.to_json() if target_resolution is not None else None,
            "dispel_count_admission": count_admission,
            "dispel_filter": {
                "buff_type": standard.get("buff_type") if isinstance(standard.get("buff_type"), str) else "",
                "only_can_dispel": standard.get("only_can_dispel") is not False,
                "order": standard.get("order") if isinstance(standard.get("order"), str) else "",
                "behavior_flags": list(standard.get("behavior_flags") or []) if isinstance(standard.get("behavior_flags"), list) else [],
            },
        }
        if count_admission.get("admission_status") != "executable":
            reason = str(count_admission.get("blocked_reason") or "dispel_count_not_executable")
            return StatusApplicationResult(
                ok=False,
                records=(_status_dispel_process_record("status_dispel_blocked", reason, source_trace),),
                unsupported=(reason,),
            )
        order = str(standard.get("order") or "")
        if order not in {"LastAdded", "Random"}:
            reason = f"dispel_order_not_admitted:{order or 'missing'}"
            return StatusApplicationResult(
                ok=False,
                records=(_status_dispel_process_record("status_dispel_blocked", reason, source_trace),),
                unsupported=(reason,),
            )
        if standard.get("behavior_flags"):
            reason = "dispel_behavior_flags_not_admitted"
            return StatusApplicationResult(
                ok=False,
                records=(_status_dispel_process_record("status_dispel_blocked", reason, source_trace),),
                unsupported=(reason,),
            )
        count = int(count_admission.get("count") or 0)
        lifecycle_results: list[StatusLifecycleResult] = []
        records: list[dict[str, JSONValue]] = []
        rng_events: list[RNGEvent] = list(target_rng_events)
        unsupported: list[str] = []
        for target_id in target_ids:
            before_details = _status_details(state.units[target_id].flags)
            candidates, skipped = _dispel_candidates(before_details, standard)
            target_trace = {**source_trace, "target_id": target_id, "skipped_candidates": skipped}
            if not candidates:
                records.append(
                    _status_dispel_process_record(
                        "status_dispel_skipped",
                        "no_eligible_status",
                        {**target_trace, "candidate_count": 0},
                    )
                )
                continue
            selected = candidates[:count]
            if order == "Random":
                if count != 1:
                    reason = "random_dispel_count_not_one"
                    records.append(_status_dispel_process_record("status_dispel_blocked", reason, target_trace))
                    unsupported.append(reason)
                    continue
                event = _status_choice_rng_event(
                    state,
                    rng_type="status_dispel",
                    source="status_system",
                    purpose="random_dispel_candidate",
                    candidates=tuple(str(item.get("instance_id") or "") for item in candidates),
                    trace=target_trace,
                    event_payload=event_payload,
                )
                rng_events.append(event)
                result = event.result if isinstance(event.result, dict) else {}
                if result.get("blocked_reason"):
                    reason = str(result.get("blocked_reason") or "requires_rng_choice")
                    records.append(_status_dispel_process_record("status_dispel_blocked", reason, {**target_trace, "rng_event": event.to_json()}))
                    unsupported.append(reason)
                    continue
                selected_index = int(result.get("selected_index") or 0)
                selected = [candidates[selected_index]]
            for detail in selected:
                detail_trace = {
                    **target_trace,
                    "selected_status_instance_id": str(detail.get("instance_id") or ""),
                    "selected_status_id": str(detail.get("status_id") or ""),
                    "selected_modifier_name": str(detail.get("modifier_name") or ""),
                    "dispel_plan": {
                        "order": order,
                        "count": count,
                        "candidate_count": len(candidates),
                        "selected_instance_ids": [str(item.get("instance_id") or "") for item in selected],
                    },
                    "modifier_name": str(detail.get("modifier_name") or ""),
                }
                plan = StatusLifecyclePlan(
                    operation="dispel",
                    target_id=target_id,
                    status_id=str(detail.get("status_id") or ""),
                    source="status_system",
                    before_details=tuple(before_details),
                    existing_detail=detail,
                    source_trace=detail_trace,
                )
                lifecycle_results.append(self._apply_lifecycle_plan(state, plan))
                break
        mutations = tuple(mutation for result in lifecycle_results for mutation in result.mutations)
        events = tuple(event for result in lifecycle_results for event in result.events)
        records.extend(record for result in lifecycle_results for record in result.records)
        unsupported.extend(reason for result in lifecycle_results for reason in result.unsupported)
        ok = not unsupported
        return StatusApplicationResult(
            ok=ok,
            mutations=mutations,
            events=events,
            rng_events=tuple(rng_events),
            records=tuple(records),
            unsupported=tuple(unsupported),
            lifecycle_result=lifecycle_results[-1] if lifecycle_results else None,
        )

    def _apply_lifecycle_plan(self, state: BattleState, plan: StatusLifecyclePlan) -> StatusLifecycleResult:
        if plan.operation in {"add", "refresh", "stack", "stack_refresh", "stack_reduce", "refresh_or_replace_partial", "replace_partial"}:
            return _apply_add_lifecycle_plan(state, plan)
        if plan.operation in {"remove", "dispel", "stack_reduce_remove"}:
            return _apply_remove_lifecycle_plan(state, plan)
        if plan.operation == "tick":
            return _apply_tick_lifecycle_plan(state, plan)
        if plan.operation == "expire":
            return _apply_expire_lifecycle_plan(state, plan)
        if plan.operation in {"reapply_blocked", "coexist_blocked"}:
            reason = plan.unsupported[0] if plan.unsupported else f"status_{plan.operation}"
            return _blocked_lifecycle_result(plan, reason)
        return StatusLifecycleResult(
            ok=False,
            operation=plan.operation,
            records=(
                SettlementRecord(
                    record_type="status_lifecycle_unsupported",
                    source="status_system",
                    process_only=True,
                    payload={"reason": f"unsupported_lifecycle_operation:{plan.operation}", "lifecycle_plan": plan.to_json()},
                    trace=plan.source_trace,
                ).to_json(),
            ),
            unsupported=(f"unsupported_lifecycle_operation:{plan.operation}",),
            lifecycle_plan=plan,
            lifecycle_state="unsupported",
        )

    def plan_lifecycle_tick(
        self,
        state: BattleState,
        unit_id: str,
        status_detail: dict[str, JSONValue],
        life_step_moment: str,
    ) -> StatusLifecyclePlan:
        if unit_id not in state.units:
            return _unsupported_lifecycle_plan("tick_blocked", unit_id, "", "unit_missing", {})
        status_id = str(status_detail.get("status_id") or "")
        source_trace = _status_detail_source_trace(status_detail)
        modifier_name = str(status_detail.get("modifier_name") or status_id.removeprefix("modifier:"))
        if modifier_name:
            source_trace.setdefault("modifier_name", modifier_name)
        source_trace.setdefault("status_instance_id", str(status_detail.get("instance_id") or ""))
        detail_moment = str(status_detail.get("life_step_moment") or "")
        if detail_moment != life_step_moment:
            return _unsupported_lifecycle_plan("tick_skipped", unit_id, status_id, "life_step_moment_mismatch", source_trace)
        duration_admission = _status_detail_duration_admission(status_detail)
        source_trace.setdefault("duration_admission", duration_admission)
        if duration_admission.get("admission_status") != "executable":
            reason = str(duration_admission.get("blocked_reason") or "duration_admission_not_executable")
            return _unsupported_lifecycle_plan("tick_blocked", unit_id, status_id, reason, source_trace)
        tick_owner_policy = str(duration_admission.get("tick_owner_policy") or "")
        if tick_owner_policy != "holder":
            return _unsupported_lifecycle_plan(
                "tick_blocked",
                unit_id,
                status_id,
                f"duration_tick_owner_policy_not_admitted:{tick_owner_policy or 'missing'}",
                source_trace,
            )
        detail_owner_id = str(status_detail.get("owner_id") or "")
        if detail_owner_id != unit_id:
            return _unsupported_lifecycle_plan(
                "tick_blocked",
                unit_id,
                status_id,
                "duration_tick_owner_mismatch",
                source_trace,
            )
        remaining = _number_or_none(status_detail.get("remaining_duration"))
        if remaining is None:
            return _unsupported_lifecycle_plan("tick_blocked", unit_id, status_id, "remaining_duration_missing", source_trace)
        if remaining <= 0:
            return _unsupported_lifecycle_plan("tick_blocked", unit_id, status_id, "status_already_expired", source_trace)
        before_details = _status_details(state.units[unit_id].flags)
        operation = "expire" if remaining <= 1 else "tick"
        return StatusLifecyclePlan(
            operation=operation,
            target_id=unit_id,
            status_id=status_id,
            source="status_system",
            before_details=tuple(before_details),
            existing_detail=status_detail,
            source_trace=source_trace,
        )

    def apply_lifecycle_tick(
        self,
        state: BattleState,
        unit_id: str,
        status_detail: dict[str, JSONValue],
        life_step_moment: str,
    ) -> StatusLifecycleResult:
        plan = self.plan_lifecycle_tick(state, unit_id, status_detail, life_step_moment)
        if plan.operation in {"tick", "expire"}:
            return self._apply_lifecycle_plan(state, plan)
        if plan.operation == "tick_skipped":
            return StatusLifecycleResult(
                ok=True,
                operation=plan.operation,
                lifecycle_plan=plan,
                lifecycle_state="skipped",
            )
        reason = plan.unsupported[0] if plan.unsupported else f"unsupported_lifecycle_operation:{plan.operation}"
        return StatusLifecycleResult(
            ok=False,
            operation=plan.operation,
            records=(
                SettlementRecord(
                    record_type="status_lifecycle_blocked",
                    source="status_system",
                    process_only=True,
                    payload={"reason": reason, "lifecycle_plan": plan.to_json()},
                    trace=plan.source_trace,
                ).to_json(),
            ),
            unsupported=(reason,),
            lifecycle_plan=plan,
            lifecycle_state="blocked",
        )


def _unsupported_result(
    effect: EffectIR,
    reason: str,
    *,
    trace: dict[str, JSONValue] | None = None,
    rng_events: tuple[RNGEvent, ...] = (),
) -> StatusApplicationResult:
    full_trace = {"effect_source": effect.source.to_json(), **(trace or {})}
    return StatusApplicationResult(
        ok=False,
        records=(
            SettlementRecord(
                record_type="status_unsupported",
                source="status_system",
                process_only=True,
                payload={"reason": reason, "effect_id": effect.effect_id, "opcode": effect.opcode},
                trace=full_trace,
            ).to_json(),
        ),
        rng_events=rng_events,
        unsupported=(reason,),
    )


def _apply_add_lifecycle_plan(state: BattleState, plan: StatusLifecyclePlan) -> StatusLifecycleResult:
    if plan.status_instance is None:
        reason = "add lifecycle requires status_instance"
        return StatusLifecycleResult(
            ok=False,
            operation=plan.operation,
            records=(
                SettlementRecord(
                    record_type="status_lifecycle_unsupported",
                    source="status_system",
                    process_only=True,
                    payload={"reason": reason, "lifecycle_plan": plan.to_json()},
                    trace=plan.source_trace,
                ).to_json(),
            ),
            unsupported=(reason,),
            lifecycle_plan=plan,
            lifecycle_state="unsupported",
        )
    unit = state.units[plan.target_id]
    before_statuses = list(unit.statuses)
    after_statuses = list(dict.fromkeys((*unit.statuses, plan.status_id)))
    before_details = list(plan.before_details)
    after_details = _replace_status_detail(before_details, plan.status_instance, plan.existing_detail)
    status_mutation = None
    if before_statuses != after_statuses:
        status_mutation = Mutation(
            op="set",
            path=("units", plan.target_id, "statuses"),
            before=before_statuses,
            after=after_statuses,
            reason=f"status lifecycle {plan.operation} status id",
            source="status_system",
            metadata={
                "status_id": plan.status_id,
                "operation": plan.operation,
                "lifecycle_plan": plan.to_json(),
            },
        )
    detail_mutation = Mutation(
        op="set",
        path=("units", plan.target_id, "flags", "status_details"),
        before=before_details,
        after=after_details,
        reason=f"status lifecycle {plan.operation} status details",
        source="status_system",
        metadata={
            "status_instance": plan.status_instance.to_json(),
            "lifecycle_plan": plan.to_json(),
        },
    )
    records: list[dict[str, JSONValue]] = []
    mutation_ids: list[str] = []
    if status_mutation is not None:
        mutation_ids.append(status_mutation.stable_id())
        records.append(
            SettlementRecord(
                record_type="status_apply_success" if plan.operation == "add" else "status_lifecycle",
                source="status_system",
                mutation_id=status_mutation.stable_id(),
                process_only=False,
                payload={
                    "operation": plan.operation,
                    "status_id": plan.status_id,
                    "lifecycle_result": {
                        "operation": plan.operation,
                        "partial": plan.partial,
                        "unsupported": list(plan.unsupported),
                    },
                    "lifecycle_plan": plan.to_json(),
                    "unsupported": list(plan.unsupported),
                    "partial": plan.partial,
                },
                trace=plan.source_trace,
            ).to_json()
        )
    mutation_ids.append(detail_mutation.stable_id())
    specific_record_type = {
        "add": "status_apply_success",
        "stack": "status_stack",
        "stack_refresh": "status_stack_refresh",
        "stack_reduce": "status_stack_reduce",
        "refresh": "status_refresh",
        "refresh_or_replace_partial": "status_lifecycle",
        "replace_partial": "status_lifecycle",
    }.get(plan.operation, "status_lifecycle")
    detail_record = SettlementRecord(
        record_type=specific_record_type,
        source="status_system",
        mutation_id=detail_mutation.stable_id(),
        process_only=False,
        payload={
            "operation": plan.operation,
            "status_id": plan.status_id,
            "status_instance": plan.status_instance.to_json(),
            "lifecycle_plan": plan.to_json(),
            "stack_plan": plan.source_trace.get("stack_plan") if isinstance(plan.source_trace.get("stack_plan"), dict) else {},
            "refresh_plan": plan.source_trace.get("refresh_plan") if isinstance(plan.source_trace.get("refresh_plan"), dict) else {},
            "unsupported": list(plan.unsupported),
            "partial": plan.partial,
        },
        trace=plan.source_trace,
    ).to_json()
    records.append(detail_record)
    legacy_record = SettlementRecord(
        record_type="status",
        source="status_system",
        mutation_id=detail_mutation.stable_id(),
        process_only=False,
        payload={
            "operation": plan.operation,
            "status_instance": plan.status_instance.to_json(),
            "lifecycle_result": {
                "operation": plan.operation,
                "partial": plan.partial,
                "unsupported": list(plan.unsupported),
            },
            "unsupported": list(plan.unsupported),
            "partial": plan.partial,
        },
        trace=plan.source_trace,
    ).to_json()
    records.append(legacy_record)
    mutations = (status_mutation, detail_mutation) if status_mutation is not None else (detail_mutation,)
    return StatusLifecycleResult(
        ok=True,
        operation=plan.operation,
        mutations=mutations,
        events=_status_lifecycle_events(
            plan,
            state,
            mutation_ids=tuple(mutation_ids),
        ),
        records=tuple(records),
        unsupported=plan.unsupported,
        status_instance=plan.status_instance,
        lifecycle_plan=plan,
        lifecycle_state=plan.status_instance.lifecycle_state,
    )


def _apply_remove_lifecycle_plan(state: BattleState, plan: StatusLifecyclePlan) -> StatusLifecycleResult:
    unit = state.units[plan.target_id]
    before_statuses = list(unit.statuses)
    before_details = list(plan.before_details)
    if plan.status_id not in unit.statuses and plan.existing_detail is None:
        reason = "status_not_present"
        record = SettlementRecord(
            record_type="status_lifecycle",
            source="status_system",
            process_only=True,
            payload={"operation": plan.operation, "reason": reason, "lifecycle_plan": plan.to_json()},
            trace=plan.source_trace,
        ).to_json()
        return StatusLifecycleResult(
            ok=False,
            operation=plan.operation,
            records=(record,),
            unsupported=(reason,),
            lifecycle_plan=plan,
            lifecycle_state="missing",
        )
    after_details = _remove_status_detail(before_details, plan.status_id, plan.existing_detail)
    after_statuses = (
        before_statuses
        if _status_detail_present(after_details, plan.status_id)
        else [status_id for status_id in before_statuses if status_id != plan.status_id]
    )
    status_mutation = Mutation(
        op="set",
        path=("units", plan.target_id, "statuses"),
        before=before_statuses,
        after=after_statuses,
        reason="status lifecycle remove status id",
        source="status_system",
        metadata={"status_id": plan.status_id, "operation": plan.operation, "lifecycle_plan": plan.to_json()},
    )
    detail_mutation = Mutation(
        op="set",
        path=("units", plan.target_id, "flags", "status_details"),
        before=before_details,
        after=after_details,
        reason="status lifecycle remove status details",
        source="status_system",
        metadata={"status_id": plan.status_id, "operation": plan.operation, "lifecycle_plan": plan.to_json()},
    )
    record_type = "status_dispel" if plan.operation == "dispel" else "status_lifecycle"
    status_id_record = SettlementRecord(
        record_type=_remove_lifecycle_record_type(plan.operation, record_type),
        source="status_system",
        mutation_id=status_mutation.stable_id(),
        process_only=False,
        payload={
            "operation": plan.operation,
            "status_id": plan.status_id,
            "lifecycle_plan": plan.to_json(),
        },
        trace=plan.source_trace,
    ).to_json()
    detail_record = SettlementRecord(
        record_type=_remove_lifecycle_record_type(plan.operation, record_type),
        source="status_system",
        mutation_id=detail_mutation.stable_id(),
        process_only=False,
        payload={
            "operation": plan.operation,
            "status_id": plan.status_id,
            "removed_detail": plan.existing_detail,
            "lifecycle_plan": plan.to_json(),
        },
        trace=plan.source_trace,
    ).to_json()
    return StatusLifecycleResult(
        ok=True,
        operation=plan.operation,
        mutations=(status_mutation, detail_mutation),
        events=_status_lifecycle_events(
            plan,
            state,
            mutation_ids=(status_mutation.stable_id(), detail_mutation.stable_id()),
        ),
        records=(status_id_record, detail_record),
        lifecycle_plan=plan,
        lifecycle_state="removed",
    )


def _remove_lifecycle_record_type(operation: str, fallback: str) -> str:
    if operation == "stack_reduce_remove":
        return "status_stack_reduce_remove"
    return fallback


def _apply_tick_lifecycle_plan(state: BattleState, plan: StatusLifecyclePlan) -> StatusLifecycleResult:
    unit = state.units[plan.target_id]
    before_details = list(plan.before_details)
    existing = plan.existing_detail if isinstance(plan.existing_detail, dict) else None
    if existing is None:
        return _blocked_lifecycle_result(plan, "status_detail_missing_for_tick")
    remaining = _number_or_none(existing.get("remaining_duration"))
    if remaining is None or remaining <= 1:
        return _blocked_lifecycle_result(plan, "tick_requires_remaining_duration_above_one")
    updated_detail = {**existing, "remaining_duration": float(remaining - 1), "lifecycle_state": "active"}
    after_details = [
        updated_detail
        if isinstance(item, dict) and item.get("instance_id") == existing.get("instance_id")
        else item
        for item in before_details
    ]
    detail_mutation = Mutation(
        op="set",
        path=("units", plan.target_id, "flags", "status_details"),
        before=before_details,
        after=after_details,
        reason="status lifecycle tick duration",
        source="status_system",
        metadata={
            "status_id": plan.status_id,
            "operation": plan.operation,
            "lifecycle_plan": plan.to_json(),
        },
    )
    record = SettlementRecord(
        record_type="status_lifecycle",
        source="status_system",
        mutation_id=detail_mutation.stable_id(),
        process_only=False,
        payload={
            "operation": plan.operation,
            "status_id": plan.status_id,
            "remaining_before": remaining,
            "remaining_after": float(remaining - 1),
            "lifecycle_plan": plan.to_json(),
        },
        trace=plan.source_trace,
    ).to_json()
    return StatusLifecycleResult(
        ok=True,
        operation=plan.operation,
        mutations=(detail_mutation,),
        events=_status_lifecycle_events(plan, state, mutation_ids=(detail_mutation.stable_id(),)),
        records=(record,),
        lifecycle_plan=plan,
        lifecycle_state="active",
    )


def _apply_expire_lifecycle_plan(state: BattleState, plan: StatusLifecyclePlan) -> StatusLifecycleResult:
    unit = state.units[plan.target_id]
    before_statuses = list(unit.statuses)
    before_details = list(plan.before_details)
    existing = plan.existing_detail if isinstance(plan.existing_detail, dict) else None
    if existing is None:
        return _blocked_lifecycle_result(plan, "status_detail_missing_for_expire")
    after_details = _remove_status_detail(before_details, plan.status_id, existing)
    after_statuses = (
        before_statuses
        if _status_detail_present(after_details, plan.status_id)
        else [status_id for status_id in before_statuses if status_id != plan.status_id]
    )
    status_mutation = Mutation(
        op="set",
        path=("units", plan.target_id, "statuses"),
        before=before_statuses,
        after=after_statuses,
        reason="status lifecycle expire status id",
        source="status_system",
        metadata={"status_id": plan.status_id, "operation": plan.operation, "lifecycle_plan": plan.to_json()},
    )
    detail_mutation = Mutation(
        op="set",
        path=("units", plan.target_id, "flags", "status_details"),
        before=before_details,
        after=after_details,
        reason="status lifecycle expire status details",
        source="status_system",
        metadata={"status_id": plan.status_id, "operation": plan.operation, "lifecycle_plan": plan.to_json()},
    )
    status_record = SettlementRecord(
        record_type="status_lifecycle",
        source="status_system",
        mutation_id=status_mutation.stable_id(),
        process_only=False,
        payload={
            "operation": plan.operation,
            "status_id": plan.status_id,
            "expired_detail": existing,
            "lifecycle_plan": plan.to_json(),
        },
        trace=plan.source_trace,
    ).to_json()
    detail_record = SettlementRecord(
        record_type="status_lifecycle",
        source="status_system",
        mutation_id=detail_mutation.stable_id(),
        process_only=False,
        payload={
            "operation": plan.operation,
            "status_id": plan.status_id,
            "expired_detail": existing,
            "lifecycle_plan": plan.to_json(),
        },
        trace=plan.source_trace,
    ).to_json()
    return StatusLifecycleResult(
        ok=True,
        operation=plan.operation,
        mutations=(status_mutation, detail_mutation),
        events=_status_lifecycle_events(
            plan,
            state,
            mutation_ids=(status_mutation.stable_id(), detail_mutation.stable_id()),
        ),
        records=(status_record, detail_record),
        lifecycle_plan=plan,
        lifecycle_state="expired",
    )


def _blocked_lifecycle_result(plan: StatusLifecyclePlan, reason: str) -> StatusLifecycleResult:
    return StatusLifecycleResult(
        ok=False,
        operation=plan.operation,
        records=(
            SettlementRecord(
                record_type="status_lifecycle_blocked",
                source="status_system",
                process_only=True,
                payload={"reason": reason, "lifecycle_plan": plan.to_json()},
                trace=plan.source_trace,
            ).to_json(),
        ),
        unsupported=(reason,),
        lifecycle_plan=plan,
        lifecycle_state="blocked",
    )


def _status_lifecycle_events(
    plan: StatusLifecyclePlan,
    state: BattleState,
    *,
    mutation_ids: tuple[str, ...],
) -> tuple[GameEvent, ...]:
    callback_events = _status_lifecycle_callback_events(plan)
    if not callback_events:
        return ()
    modifier_name = ""
    status_instance_id = ""
    caster_id = ""
    remove_like = plan.operation in {"remove", "expire", "dispel", "stack_reduce_remove"}
    if remove_like and isinstance(plan.existing_detail, dict):
        modifier_name = str(plan.existing_detail.get("modifier_name") or "")
        status_instance_id = str(plan.existing_detail.get("instance_id") or "")
        caster_id = str(plan.existing_detail.get("caster_id") or "")
    elif plan.status_instance is not None:
        modifier_name = plan.status_instance.modifier_name
        status_instance_id = plan.status_instance.instance_id
        caster_id = plan.status_instance.caster_id
    if not modifier_name and isinstance(plan.existing_detail, dict):
        modifier_name = str(plan.existing_detail.get("modifier_name") or "")
        status_instance_id = str(plan.existing_detail.get("instance_id") or "")
        caster_id = str(plan.existing_detail.get("caster_id") or "")
    events: list[GameEvent] = []
    for callback_event in callback_events:
        events.append(
            GameEvent(
                event_type="status.lifecycle",
                source_id=caster_id or plan.source,
                target_id=plan.target_id,
                event_id=(
                    f"event:{state.event_index}:status_lifecycle:"
                    f"{plan.operation}:{plan.target_id}:{_status_id_fragment(plan.status_id)}:{callback_event}"
                ),
                window=callback_event,
                process_only=True,
                payload={
                    "callback_event": callback_event,
                    "listener_scope": "status_local",
                    "lifecycle_operation": plan.operation,
                    "target_id": plan.target_id,
                    "owner_id": plan.target_id,
                    "modifier_name": modifier_name,
                    "status_id": plan.status_id,
                    "status_instance_id": status_instance_id,
                    "mutation_ids": list(mutation_ids),
                    "source_trace": plan.source_trace,
                },
            )
        )
    return tuple(events)


def _status_lifecycle_callback_events(plan: StatusLifecyclePlan) -> tuple[str, ...]:
    dot_add_events = ("OnModifierDotAdd",) if _plan_is_dot_status(plan) else ()
    if plan.operation == "add":
        return ("OnCreate", "OnModifierAdd", "OnAddModifierSuc", "OnListenModifierAdd", *dot_add_events)
    if plan.operation in {"stack", "stack_reduce"}:
        return ("OnStack", "OnModifierAdd", "OnModifierOnStack", "OnListenModifierOnStack")
    if plan.operation in {"refresh", "refresh_or_replace_partial", "replace_partial"}:
        return ("OnModifierAdd", "OnListenModifierAdd")
    if plan.operation in {"remove", "expire", "dispel", "stack_reduce_remove"}:
        return ("OnDestroy", "OnModifierRemove", "OnListenModifierRemove")
    return ()


def _plan_is_dot_status(plan: StatusLifecyclePlan) -> bool:
    sources: list[dict[str, JSONValue]] = []
    if plan.status_instance is not None:
        sources.append(plan.status_instance.to_json())
    if isinstance(plan.existing_detail, dict):
        sources.append(plan.existing_detail)
    for source in sources:
        status_type = str(source.get("status_type") or "").lower()
        status_category = str(source.get("status_category") or "").lower()
        fields = source.get("fields")
        if "dot" in {status_type, status_category}:
            return True
        if "dot" in status_type or "dot" in status_category:
            return True
        if isinstance(fields, dict):
            if str(fields.get("status_type") or "").lower() == "dot":
                return True
            if str(fields.get("status_category") or "").lower() == "dot":
                return True
    return False


def _status_id_fragment(status_id: str) -> str:
    return status_id.replace(":", "_").replace("/", "_")


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
    if alias in {"CurrentActionTarget", "AbilityTargetEntity"}:
        return current_action_target_id
    return None


def _resolve_add_modifier_target_ids(
    state: BattleState,
    alias: object,
    *,
    caster_id: str,
    owner_id: str | None,
    param_entity_id: str | None,
    current_action_target_id: str | None,
    target_resolution: TargetResolution | None,
) -> tuple[tuple[str, ...], str]:
    if alias in SUPPORTED_ADD_MODIFIER_SINGLE_TARGET_ALIASES:
        target_id = _resolve_target_alias(
            alias,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
        )
        if target_id is None and alias == "AbilityTargetEntity" and target_resolution is not None and target_resolution.selected:
            target_id = target_resolution.selected[0]
        if target_id is None:
            return (), f"unsupported_or_missing_target_alias:{alias}"
        if target_id not in state.units:
            return (), f"target unit {target_id!r} is not in state"
        return (target_id,), ""
    if alias in SUPPORTED_ADD_MODIFIER_GROUP_TARGET_ALIASES:
        targets, reason = _resolve_add_modifier_group_targets(state, caster_id, str(alias))
        if reason:
            return (), reason
        if not targets:
            return (), f"target group empty:{alias}"
        missing = tuple(target_id for target_id in targets if target_id not in state.units)
        if missing:
            return (), f"target group contains missing unit:{','.join(missing)}"
        return targets, ""
    return (), f"unsupported_or_missing_target_alias:{alias}"


def _resolve_add_modifier_group_targets(
    state: BattleState,
    caster_id: str,
    alias: str,
) -> tuple[tuple[str, ...], str]:
    caster = state.units.get(caster_id)
    if caster is None:
        return (), "caster_missing_for_group_target"
    targets: list[str] = []
    lifecycle = UnitLifecycleSystem()
    for unit_id, unit in sorted(state.units.items()):
        if not lifecycle.can_target(state, unit_id)[0]:
            continue
        if alias == "AllEnemy" and unit.side != caster.side:
            targets.append(unit_id)
        elif alias in {"AllTeamMember", "AllLightTeam"} and unit.side == caster.side:
            targets.append(unit_id)
        elif alias == "AllTeammate" and unit.side == caster.side and unit_id != caster_id:
            targets.append(unit_id)
    return tuple(dict.fromkeys(targets)), ""


def _strict_attached_status_blocked_reason(
    *,
    standard: dict[str, JSONValue],
    resolved_dynamic_values: dict[str, JSONValue],
    duration_admission: dict[str, JSONValue],
    trigger_ids_by_event: dict[str, tuple[str, ...]],
    unsupported: tuple[str, ...],
) -> str:
    requests = standard.get("dynamic_value_requests")
    if isinstance(requests, dict):
        missing = tuple(str(key) for key in requests if str(key) not in resolved_dynamic_values)
        if missing:
            return f"attached_status_dynamic_value_unresolved:{','.join(missing)}"
    if duration_admission.get("admission_status") == "blocked":
        return f"attached_status_duration_blocked:{duration_admission.get('blocked_reason')}"
    if any(trigger_ids for trigger_ids in trigger_ids_by_event.values()):
        return "attached_status_listener_not_admitted"
    if unsupported:
        return f"attached_status_partial_not_admitted:{unsupported[0]}"
    return ""


def _resolve_dynamic_values(
    standard: dict[str, JSONValue],
    definition: RuleEntity,
    runtime_bindings: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    source_trace: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    values: dict[str, JSONValue] = {
        "__by_name": {},
        "__by_hash": {},
        "__evaluations": [],
        "__definition_bindings": _json_safe(definition.fields.get("dynamic_value_bindings", {})),
        "__dynamic_value_requests": _json_safe(standard.get("dynamic_value_requests", {})),
    }
    bindings = _numeric_bindings(runtime_bindings)
    by_name: dict[str, JSONValue] = {}
    by_hash: dict[str, JSONValue] = {}
    evaluations: list[JSONValue] = []
    resolved_values_in_order: list[float] = []
    for key, value in bindings.items():
        by_hash[str(key)] = value
        values[str(key)] = value
        evaluations.append(
            {
                "name": f"runtime_binding:{key}",
                "result": {
                    "ok": True,
                    "value": value,
                    "expression_kind": "runtime_dynamic_value_binding",
                    "bindings": {"hash": str(key), "source_type": "runtime_add_modifier_binding"},
                    "source_trace": source_trace,
                },
            }
        )
    dynamic_values = standard.get("dynamic_values")
    if not isinstance(dynamic_values, dict):
        values["__by_name"] = by_name
        values["__by_hash"] = by_hash
        values["__evaluations"] = evaluations
        return values
    for key, expr in dynamic_values.items():
        result = RuleEvaluator().evaluate_numeric(
            expr,
            NumericEvaluationContext(
                dynamic_values=bindings,
                binding_sources=binding_sources,
                source_trace=source_trace,
            ),
        )
        result_json = result.to_json()
        evaluations.append({"name": str(key), "result": result_json})
        if result.ok and result.value is not None:
            resolved_values_in_order.append(float(result.value))
            by_name[str(key)] = result.value
            values[str(key)] = result.value
            hash_key = result.bindings.get("key")
            if isinstance(hash_key, str):
                by_hash[hash_key] = result.value
                values[hash_key] = result.value
    definition_bindings = definition.fields.get("dynamic_value_bindings")
    if isinstance(definition_bindings, dict):
        for hash_key, binding in _definition_dynamic_hash_bindings(definition_bindings).items():
            index = binding.get("index")
            if isinstance(index, int) and 0 <= index < len(resolved_values_in_order):
                value = resolved_values_in_order[index]
                by_hash[str(hash_key)] = value
                values[str(hash_key)] = value
                evaluations.append(
                    {
                        "name": f"definition_hash:{hash_key}",
                        "result": {
                            "ok": True,
                            "value": value,
                            "expression_kind": "definition_dynamic_value_binding",
                            "bindings": {
                                "hash": str(hash_key),
                                "index": index,
                                "source_type": "modifier_definition_dynamic_value_binding",
                            },
                            "source_trace": source_trace,
                        },
                    }
                )
    callback_bindings = definition.fields.get("callback_dynamic_hashes")
    callback_hashes = _definition_callback_dynamic_hashes(callback_bindings)
    if len(resolved_values_in_order) == 1 and len(callback_hashes) == 1:
        hash_key, binding = next(iter(callback_hashes.items()))
        if str(hash_key) not in by_hash:
            value = resolved_values_in_order[0]
            by_hash[str(hash_key)] = value
            values[str(hash_key)] = value
            evaluations.append(
                {
                    "name": f"callback_hash:{hash_key}",
                    "result": {
                        "ok": True,
                        "value": value,
                        "expression_kind": "single_status_dynamic_value_callback_hash_binding",
                        "bindings": {
                            "hash": str(hash_key),
                            "source_type": "modifier_callback_dynamic_hash_single_binding",
                            "binding": _json_safe(binding),
                        },
                        "source_trace": source_trace,
                    },
                }
            )
    values["__by_name"] = by_name
    values["__by_hash"] = by_hash
    values["__evaluations"] = evaluations
    return values


def _on_create_define_dynamic_values(
    rules: RuleBook,
    modifier_name: str,
    source_path: str,
    state: BattleState,
    *,
    target_id: str,
    caster_id: str,
    owner_id: str,
    param_entity_id: str | None,
    current_action_target_id: str | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    source_trace: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    values: dict[str, JSONValue] = {"__by_name": {}, "__by_hash": {}, "__evaluations": []}
    for callback in rules.status_callbacks_for_modifier_event(modifier_name, "OnCreate"):
        if callback.source.source_path != source_path:
            continue
        for task in rules.status_callback_tasks_for_callback(callback.callback_id):
            if task.parent_task_id or task.opcode != "DefineDynamicValue" or not task.effect_id:
                continue
            effect = rules.effect(task.effect_id)
            standard = effect.payload.get("standard") if effect is not None else None
            if effect is None or not isinstance(standard, dict):
                continue
            target_alias = standard.get("target_alias")
            resolved_target = _resolve_target_alias(
                target_alias,
                caster_id=caster_id,
                owner_id=owner_id,
                param_entity_id=param_entity_id,
                current_action_target_id=current_action_target_id,
            )
            if resolved_target != target_id:
                continue
            value_name = standard.get("value_name")
            if not isinstance(value_name, str) or not value_name:
                continue
            result = RuleEvaluator().evaluate_numeric(
                standard.get("value_expr"),
                NumericEvaluationContext(
                    dynamic_values={},
                    binding_sources=binding_sources,
                    source_trace={
                        **source_trace,
                        "on_create_callback_id": callback.callback_id,
                        "on_create_task_id": task.task_id,
                        "effect_source": effect.source.to_json(),
                        "partial_admission": "on_create_define_dynamic_value_only",
                    },
                ),
            )
            evaluations = list(values.get("__evaluations") or [])
            evaluations.append({"name": value_name, "result": result.to_json()})
            values["__evaluations"] = evaluations
            if not result.ok or result.value is None:
                continue
            by_name = dict(values.get("__by_name") or {})
            by_hash = dict(values.get("__by_hash") or {})
            values[value_name] = float(result.value)
            by_name[value_name] = float(result.value)
            value_hash = standard.get("hash")
            if isinstance(value_hash, (str, int)):
                values[str(value_hash)] = float(result.value)
                by_hash[str(value_hash)] = float(result.value)
            values["__by_name"] = by_name
            values["__by_hash"] = by_hash
    return values


def _merge_dynamic_values(
    base: dict[str, JSONValue],
    extra: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    merged = dict(base)
    for key, value in extra.items():
        if key in {"__by_name", "__by_hash"}:
            current = dict(merged.get(key) or {})
            current.update(value if isinstance(value, dict) else {})
            merged[key] = current
        elif key == "__evaluations":
            merged[key] = [*(merged.get(key) if isinstance(merged.get(key), list) else []), *(value if isinstance(value, list) else [])]
        elif key not in merged:
            merged[key] = value
    return merged


def _status_formula_bindings(standard: dict[str, JSONValue]) -> tuple[dict[str, JSONValue], ...]:
    bindings = standard.get("status_formula_bindings")
    if not isinstance(bindings, list):
        return ()
    result: list[dict[str, JSONValue]] = []
    for item in bindings:
        if isinstance(item, dict):
            result.append(_json_safe(item))
    return tuple(result)


def _runtime_modifiers(
    definition: RuleEntity,
    dynamic_values: dict[str, JSONValue],
) -> tuple[list[dict[str, JSONValue]], list[str]]:
    modifiers: list[dict[str, JSONValue]] = []
    unsupported: list[str] = []
    stack_properties = definition.fields.get("stack_properties")
    if not isinstance(stack_properties, list):
        return modifiers, unsupported
    for index, item in enumerate(stack_properties):
        if not isinstance(item, dict):
            continue
        if item.get("event") != "OnStack":
            continue
        property_name = str(item.get("property") or "")
        mapped = _map_stack_property(property_name)
        if mapped is None:
            unsupported.append(f"unsupported_property:{property_name}")
            continue
        value, reason = _resolve_stack_property_value(item.get("value_expr"), dynamic_values)
        if value is None:
            unsupported.append(f"unsupported_formula:{property_name}:{reason}")
            continue
        bucket, key, scope = mapped
        modifiers.append(
            {
                "bucket": bucket,
                "key": key,
                "value": value,
                "scope": scope,
                "property": property_name,
                "raw_path": str(item.get("raw_path") or f"stack_properties[{index}]"),
                "applied_reason": "status_stack_property",
                "condition": f"property={property_name}",
            }
        )
    return modifiers, unsupported


def _resolve_stack_property_value(
    value_expr: object,
    dynamic_values: dict[str, JSONValue],
) -> tuple[float | None, str]:
    result = RuleEvaluator().evaluate_numeric(
        value_expr,
        NumericEvaluationContext(dynamic_values=_numeric_bindings(dynamic_values)),
    )
    if result.ok and result.value is not None:
        return result.value, result.expression_kind
    return None, result.blocked_reason or "unsupported_numeric_expression"


def _numeric_bindings(values: dict[str, JSONValue] | dict[str, float] | None) -> dict[str, float]:
    if not isinstance(values, dict):
        return {}
    bindings: dict[str, float] = {}
    for key, value in values.items():
        if isinstance(value, (int, float)):
            bindings[str(key)] = float(value)
    by_hash = values.get("__by_hash")
    if isinstance(by_hash, dict):
        for key, value in by_hash.items():
            if isinstance(value, (int, float)):
                bindings[str(key)] = float(value)
    return bindings


def _runtime_stack_admission(
    standard: dict[str, JSONValue],
    effect: EffectIR,
    *,
    binding_sources: tuple[dict[str, JSONValue], ...],
) -> dict[str, JSONValue]:
    source_trace = {"effect_id": effect.effect_id, "effect_source": effect.source.to_json()}
    max_result = RuleEvaluator().evaluate_numeric(
        standard.get("max_layer"),
        NumericEvaluationContext(binding_sources=binding_sources, source_trace=source_trace),
    )
    layer_result = RuleEvaluator().evaluate_numeric(
        standard.get("layer_add_when_stack"),
        NumericEvaluationContext(binding_sources=binding_sources, source_trace=source_trace),
    )
    if _is_missing_numeric_expr(standard.get("max_layer")):
        max_stacks = 1
        max_status = "not_applicable"
    elif not max_result.ok or max_result.value is None:
        return {
            "admission_status": "blocked",
            "blocked_reason": max_result.blocked_reason or "max_layer_not_executable",
            "stack_policy": "blocked",
            "numeric_evaluation": max_result.to_json(),
            "layer_add_evaluation": layer_result.to_json(),
            "source_trace": source_trace,
        }
    else:
        if max_result.expression_kind not in {"fixed", "dynamic_hash", "postfix_expr"}:
            return {
                "admission_status": "blocked",
                "blocked_reason": f"max_layer_not_admitted:{max_result.expression_kind}",
                "stack_policy": "blocked",
                "numeric_evaluation": max_result.to_json(),
                "layer_add_evaluation": layer_result.to_json(),
                "source_trace": source_trace,
            }
        if max_result.value <= 0 or int(max_result.value) != float(max_result.value):
            return {
                "admission_status": "blocked",
                "blocked_reason": "max_layer_non_positive_or_non_integer",
                "stack_policy": "blocked",
                "numeric_evaluation": max_result.to_json(),
                "layer_add_evaluation": layer_result.to_json(),
                "source_trace": source_trace,
            }
        max_stacks = int(max_result.value)
        max_status = "executable"

    layer_delta = 0
    layer_status = "not_applicable"
    if not _is_missing_numeric_expr(standard.get("layer_add_when_stack")):
        if not layer_result.ok or layer_result.value is None:
            return {
                "admission_status": "blocked",
                "blocked_reason": layer_result.blocked_reason or "layer_add_when_stack_not_executable",
                "stack_policy": "blocked",
                "numeric_evaluation": max_result.to_json(),
                "layer_add_evaluation": layer_result.to_json(),
                "source_trace": source_trace,
            }
        if layer_result.expression_kind not in {"fixed", "dynamic_hash", "postfix_expr"}:
            return {
                "admission_status": "blocked",
                "blocked_reason": f"layer_add_when_stack_not_admitted:{layer_result.expression_kind}",
                "stack_policy": "blocked",
                "numeric_evaluation": max_result.to_json(),
                "layer_add_evaluation": layer_result.to_json(),
                "source_trace": source_trace,
            }
        if int(layer_result.value) != float(layer_result.value):
            return {
                "admission_status": "blocked",
                "blocked_reason": "layer_add_when_stack_non_integer",
                "stack_policy": "blocked",
                "numeric_evaluation": max_result.to_json(),
                "layer_add_evaluation": layer_result.to_json(),
                "source_trace": source_trace,
            }
        layer_delta = int(layer_result.value)
        layer_status = "executable"

    if max_stacks > 1 and layer_status != "executable":
        stack_policy = "stackable_delta_missing"
    elif layer_status == "executable" and layer_delta < 0:
        stack_policy = "stack_reduce"
    elif max_stacks > 1 and layer_delta > 0:
        stack_policy = "additive_stack"
    else:
        stack_policy = "single_instance"
    return {
        "admission_status": "executable",
        "blocked_reason": "",
        "stack_policy": stack_policy,
        "max_stacks": max_stacks,
        "max_layer_status": max_status,
        "layer_delta": layer_delta,
        "layer_add_status": layer_status,
        "numeric_evaluation": max_result.to_json(),
        "layer_add_evaluation": layer_result.to_json(),
        "source_trace": source_trace,
    }


def _stack_admission_max_stacks(stack_admission: dict[str, JSONValue]) -> int | None:
    value = stack_admission.get("max_stacks")
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _stack_plan_max_stacks(stack_plan: dict[str, JSONValue]) -> int | None:
    value = stack_plan.get("max_stacks")
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _runtime_refresh_admission(
    standard: dict[str, JSONValue],
    definition: RuleEntity,
    duration_admission: dict[str, JSONValue],
    effect: EffectIR,
) -> dict[str, JSONValue]:
    source_trace = {"effect_id": effect.effect_id, "effect_source": effect.source.to_json()}
    explicit_refresh = bool(standard.get("is_refresh", False))
    stacking = str(definition.fields.get("stacking") or "")
    if not explicit_refresh and stacking != "Refresh":
        return {
            "admission_status": "not_applicable",
            "blocked_reason": "refresh_source_missing",
            "refresh_policy": "none",
            "stacking": stacking,
            "source_trace": source_trace,
        }
    if duration_admission.get("admission_status") != "executable":
        return {
            "admission_status": "blocked",
            "blocked_reason": f"refresh_duration_not_executable:{duration_admission.get('blocked_reason') or 'unknown'}",
            "refresh_policy": "blocked",
            "stacking": stacking,
            "source_trace": {
                **source_trace,
                "modifier_definition": definition.source.to_json(),
                "duration_admission": duration_admission,
            },
        }
    source_kind = "effect_is_refresh" if explicit_refresh else "modifier_definition_stacking"
    return {
        "admission_status": "executable",
        "blocked_reason": "",
        "refresh_policy": "duration_reset",
        "source_kind": source_kind,
        "stacking": stacking,
        "source_trace": {
            **source_trace,
            "modifier_definition": definition.source.to_json(),
        },
    }


def _status_stack_plan(
    existing_detail: dict[str, JSONValue] | None,
    stack_admission: dict[str, JSONValue],
    *,
    operation: str,
) -> dict[str, JSONValue]:
    admitted_max_stacks = _stack_admission_max_stacks(stack_admission)
    existing_max_stacks = _detail_int(existing_detail, "max_stacks", default=1) if existing_detail is not None else 1
    max_stacks = admitted_max_stacks or existing_max_stacks or 1
    before = _detail_int(existing_detail, "stacks", default=1) if existing_detail is not None else 0
    if operation not in {"stack", "stack_refresh", "stack_reduce"}:
        after = before if existing_detail is not None else 1
        return {
            "operation": operation,
            "stacks_before": before,
            "stack_delta": 0,
            "uncapped_stacks_after": after,
            "stacks_after": after,
            "max_stacks": max_stacks,
            "stack_capped": False,
            "stack_depleted": False,
            "stack_policy": stack_admission.get("stack_policy"),
            "admission": stack_admission,
        }
    delta = int(stack_admission.get("layer_delta") or 0)
    uncapped = before + delta
    after = max(0, min(max_stacks, uncapped))
    return {
        "operation": operation,
        "stacks_before": before,
        "stack_delta": delta,
        "uncapped_stacks_after": uncapped,
        "stacks_after": after,
        "max_stacks": max_stacks,
        "stack_capped": delta > 0 and uncapped != after,
        "stack_depleted": delta < 0 and after <= 0,
        "stack_policy": stack_admission.get("stack_policy"),
        "admission": stack_admission,
    }


def _status_refresh_plan(
    existing_detail: dict[str, JSONValue] | None,
    new_duration: float | None,
    *,
    operation: str,
) -> dict[str, JSONValue]:
    before = _number_or_none(existing_detail.get("remaining_duration")) if isinstance(existing_detail, dict) else None
    if operation == "refresh":
        return {
            "operation": operation,
            "refresh_policy": "duration_reset",
            "remaining_duration_before": before,
            "remaining_duration_after": new_duration,
            "duration_unchanged": before == new_duration,
        }
    if operation == "stack_refresh":
        return {
            "operation": operation,
            "refresh_policy": "stack_duration_reset",
            "remaining_duration_before": before,
            "remaining_duration_after": new_duration,
            "duration_unchanged": before == new_duration,
        }
    if operation == "stack":
        return {
            "operation": operation,
            "refresh_policy": "stack_only",
            "remaining_duration_before": before,
            "remaining_duration_after": before,
            "duration_unchanged": True,
        }
    return {
        "operation": operation,
        "refresh_policy": "none",
        "remaining_duration_before": before,
        "remaining_duration_after": new_duration if existing_detail is None else before,
        "duration_unchanged": existing_detail is not None,
    }


def _stack_plan_stacks_after(stack_plan: dict[str, JSONValue]) -> int:
    value = stack_plan.get("stacks_after")
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 1


def _refresh_plan_remaining_after(refresh_plan: dict[str, JSONValue], fallback: float | None) -> float | None:
    value = refresh_plan.get("remaining_duration_after")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else fallback


def _refresh_plan_duration(refresh_plan: dict[str, JSONValue], fallback: float | None) -> float | None:
    value = refresh_plan.get("remaining_duration_after")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else fallback


def _detail_int(detail: dict[str, JSONValue] | None, key: str, *, default: int) -> int:
    if not isinstance(detail, dict):
        return default
    value = detail.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return default


def _runtime_chance_admission(
    standard: dict[str, JSONValue],
    effect: EffectIR,
    state: BattleState,
    *,
    caster_id: str,
    target_id: str,
    binding_sources: tuple[dict[str, JSONValue], ...],
) -> dict[str, JSONValue]:
    source_trace = {"effect_id": effect.effect_id, "effect_source": effect.source.to_json()}
    chance_expr = standard.get("chance")
    if _is_missing_numeric_expr(chance_expr):
        base_chance = 1.0
        chance_result = {
            "ok": True,
            "value": 1.0,
            "expression_kind": "missing_as_guaranteed",
            "bindings": {},
            "source_trace": source_trace,
            "blocked_reason": "",
        }
        source_kind = "chance_omitted_guaranteed"
    else:
        result = RuleEvaluator().evaluate_numeric(
            chance_expr,
            NumericEvaluationContext(binding_sources=binding_sources, source_trace=source_trace),
        )
        if not result.ok or result.value is None:
            return {
                "admission_status": "blocked",
                "blocked_reason": result.blocked_reason or "chance_not_executable",
                "source_trace": source_trace,
                "numeric_evaluation": result.to_json(),
            }
        if result.expression_kind not in {"fixed", "dynamic_hash", "postfix_expr"}:
            return {
                "admission_status": "blocked",
                "blocked_reason": f"chance_not_admitted:{result.expression_kind}",
                "source_trace": source_trace,
                "numeric_evaluation": result.to_json(),
            }
        if result.value < 0 or result.value > 1:
            return {
                "admission_status": "blocked",
                "blocked_reason": "chance_out_of_range",
                "source_trace": source_trace,
                "numeric_evaluation": result.to_json(),
            }
        base_chance = float(result.value)
        chance_result = result.to_json()
        source_kind = "effect_chance"
    effect_hit = _unit_resource(state, caster_id, "effect_hit_rate")
    effect_resistance = _unit_resource(state, target_id, "effect_resistance")
    base_success_probability = max(0.0, min(1.0, base_chance * (1.0 + effect_hit)))
    resist_probability = max(0.0, min(1.0, effect_resistance))
    return {
        "admission_status": "executable",
        "blocked_reason": "",
        "source_kind": source_kind,
        "base_chance": base_chance,
        "effect_hit_rate": effect_hit,
        "effect_resistance": effect_resistance,
        "base_success_probability": base_success_probability,
        "resist_probability": resist_probability,
        "guaranteed": base_success_probability >= 1.0 and resist_probability <= 0.0,
        "numeric_evaluation": chance_result,
        "source_trace": source_trace,
    }


def _status_chance_check(
    state: BattleState,
    effect: EffectIR,
    chance_admission: dict[str, JSONValue],
    *,
    caster_id: str,
    target_id: str,
    modifier_name: str,
    status_id: str,
    source_stack_key: str,
    event_payload: dict[str, JSONValue] | None,
) -> _ChanceCheck:
    trace = {
        "effect_id": effect.effect_id,
        "effect_source": effect.source.to_json(),
        "modifier_name": modifier_name,
        "status_id": status_id,
        "target_id": target_id,
        "caster_id": caster_id,
        "source_stack_key": source_stack_key,
        "chance_admission": chance_admission,
    }
    if chance_admission.get("admission_status") != "executable":
        reason = str(chance_admission.get("blocked_reason") or "chance_admission_not_executable")
        return _ChanceCheck(
            allowed=False,
            record=_status_apply_process_record("status_blocked", reason, trace),
            unsupported=(reason,),
        )
    immunity = _status_immunity_source(state, target_id, status_id=status_id)
    if immunity is not None:
        return _ChanceCheck(
            allowed=False,
            record=_status_apply_process_record(
                "status_immunity",
                "status_immunity",
                {**trace, "immunity_source": immunity},
            ),
        )
    rng_events: list[RNGEvent] = []
    base_probability = _probability(chance_admission.get("base_success_probability"), default=1.0)
    if base_probability < 1.0:
        event = _status_rng_event(
            state,
            rng_type="status_apply",
            source="status_system",
            purpose="base_chance",
            probability=base_probability,
            trace=trace,
            event_payload=event_payload,
            success_outcome_id="success",
            fail_outcome_id="fail",
        )
        rng_events.append(event)
        result = event.result if isinstance(event.result, dict) else {}
        if result.get("blocked_reason"):
            reason = str(result.get("blocked_reason") or "requires_rng_choice")
            return _ChanceCheck(
                allowed=False,
                record=_status_apply_process_record(
                    "status_blocked",
                    reason,
                    {**trace, "rng_event": event.to_json()},
                ),
                rng_events=tuple(rng_events),
                unsupported=(reason,),
            )
        if result.get("success") is not True:
            return _ChanceCheck(
                allowed=False,
                record=_status_apply_process_record(
                    "status_apply_failed",
                    "chance_failed",
                    {**trace, "rng_event": event.to_json()},
                ),
                rng_events=tuple(rng_events),
            )
    resist_probability = _probability(chance_admission.get("resist_probability"), default=0.0)
    if resist_probability > 0.0:
        event = _status_rng_event(
            state,
            rng_type="status_resist",
            source="status_system",
            purpose="effect_resistance",
            probability=resist_probability,
            trace=trace,
            event_payload=event_payload,
            success_outcome_id="resisted",
            fail_outcome_id="not_resisted",
        )
        rng_events.append(event)
        result = event.result if isinstance(event.result, dict) else {}
        if result.get("blocked_reason"):
            reason = str(result.get("blocked_reason") or "requires_rng_choice")
            return _ChanceCheck(
                allowed=False,
                record=_status_apply_process_record(
                    "status_blocked",
                    reason,
                    {**trace, "rng_event": event.to_json()},
                ),
                rng_events=tuple(rng_events),
                unsupported=(reason,),
            )
        if result.get("success") is True:
            return _ChanceCheck(
                allowed=False,
                record=_status_apply_process_record(
                    "status_resisted",
                    "effect_resisted",
                    {**trace, "rng_event": event.to_json()},
                ),
                rng_events=tuple(rng_events),
            )
    return _ChanceCheck(allowed=True, rng_events=tuple(rng_events))


def _status_apply_process_record(
    record_type: str,
    reason: str,
    trace: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type=record_type,
        source="status_system",
        process_only=True,
        payload={"reason": reason, **trace},
        trace=trace,
    ).to_json()


def _status_dispel_process_record(
    record_type: str,
    reason: str,
    trace: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type=record_type,
        source="status_system",
        process_only=True,
        payload={"reason": reason, **trace},
        trace=trace,
    ).to_json()


def _runtime_dispel_count_admission(
    standard: dict[str, JSONValue],
    effect: EffectIR,
    *,
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
) -> dict[str, JSONValue]:
    source_trace = {"effect_id": effect.effect_id, "effect_source": effect.source.to_json()}
    count_expr = standard.get("numbers")
    result = RuleEvaluator().evaluate_numeric(
        count_expr,
        NumericEvaluationContext(
            dynamic_values=_numeric_bindings(dynamic_values),
            binding_sources=binding_sources,
            source_trace=source_trace,
        ),
    )
    if _is_missing_numeric_expr(count_expr):
        return {
            "admission_status": "blocked",
            "blocked_reason": "dispel_count_missing",
            "numeric_evaluation": result.to_json(),
            "source_trace": source_trace,
        }
    if not result.ok or result.value is None:
        return {
            "admission_status": "blocked",
            "blocked_reason": result.blocked_reason or "dispel_count_not_executable",
            "numeric_evaluation": result.to_json(),
            "source_trace": source_trace,
        }
    if result.expression_kind not in {"fixed", "dynamic_hash", "postfix_expr"}:
        return {
            "admission_status": "blocked",
            "blocked_reason": f"dispel_count_not_admitted:{result.expression_kind}",
            "numeric_evaluation": result.to_json(),
            "source_trace": source_trace,
        }
    if int(result.value) != float(result.value) or result.value <= 0:
        return {
            "admission_status": "blocked",
            "blocked_reason": "dispel_count_non_positive_or_non_integer",
            "numeric_evaluation": result.to_json(),
            "source_trace": source_trace,
        }
    if int(result.value) != 1:
        return {
            "admission_status": "blocked",
            "blocked_reason": "dispel_count_not_one_first_phase",
            "numeric_evaluation": result.to_json(),
            "source_trace": source_trace,
        }
    return {
        "admission_status": "executable",
        "blocked_reason": "",
        "count": 1,
        "numeric_evaluation": result.to_json(),
        "source_trace": source_trace,
    }


def _dispel_candidates(
    details: tuple[JSONValue, ...],
    standard: dict[str, JSONValue],
) -> tuple[list[dict[str, JSONValue]], list[dict[str, JSONValue]]]:
    candidates: list[dict[str, JSONValue]] = []
    skipped: list[dict[str, JSONValue]] = []
    for index, detail in enumerate(details):
        if not isinstance(detail, dict):
            continue
        reason = _dispel_detail_skipped_reason(detail, standard)
        if reason:
            skipped.append(
                {
                    "index": index,
                    "status_id": str(detail.get("status_id") or ""),
                    "instance_id": str(detail.get("instance_id") or ""),
                    "reason": reason,
                }
            )
            continue
        candidates.append({**detail, "__status_detail_index": index})
    order = str(standard.get("order") or "")
    if order == "LastAdded":
        candidates.sort(key=lambda item: int(item.get("__status_detail_index") or 0), reverse=True)
    else:
        candidates.sort(key=lambda item: str(item.get("instance_id") or ""))
    return candidates, skipped


def _dispel_detail_skipped_reason(detail: dict[str, JSONValue], standard: dict[str, JSONValue]) -> str:
    if detail.get("can_dispel") is not True:
        return "can_dispel_not_true"
    source_trace = detail.get("source_trace")
    if not isinstance(source_trace, dict) or not source_trace:
        return "source_trace_missing"
    buff_type = str(standard.get("buff_type") or "")
    if not buff_type:
        return ""
    category = str(detail.get("status_category") or "").lower()
    status_type = str(detail.get("status_type") or "").lower()
    if buff_type == "Buff" and "buff" not in {category, status_type}:
        return "buff_type_mismatch:Buff"
    if buff_type == "Debuff" and "debuff" not in {category, status_type}:
        return "buff_type_mismatch:Debuff"
    if buff_type == "Other" and "other" not in {category, status_type}:
        return "buff_type_mismatch:Other"
    if buff_type not in {"Buff", "Debuff", "Other"}:
        return f"buff_type_not_admitted:{buff_type}"
    return ""


def _status_rng_event(
    state: BattleState,
    *,
    rng_type: str,
    source: str,
    purpose: str,
    probability: float,
    trace: dict[str, JSONValue],
    event_payload: dict[str, JSONValue] | None,
    success_outcome_id: str,
    fail_outcome_id: str,
) -> RNGEvent:
    event_id = (
        f"rng:{state.event_index}:{rng_type}:{purpose}:"
        f"{trace.get('caster_id')}:{trace.get('target_id')}:{_status_id_fragment(str(trace.get('status_id') or ''))}"
    )
    request = RNGRequest(
        rng_type=rng_type,
        purpose=purpose,
        event_id=event_id,
        choice_key=f"{rng_type}:{purpose}:{trace.get('caster_id')}:{trace.get('target_id')}:{_status_id_fragment(str(trace.get('status_id') or ''))}",
        source=source,
        before_state=state.rng_state,
        decision_kind="probability",
        outcomes=(
            RNGOutcome(success_outcome_id, payload={"success": True, "value": success_outcome_id}, probability=probability),
            RNGOutcome(fail_outcome_id, payload={"success": False, "value": fail_outcome_id}, probability=1.0 - probability),
        ),
        source_trace=trace,
        metadata={"probability": probability},
    )
    resolution = resolve_rng_request(
        request,
        rng_choices=rng_choices_from_payload(event_payload),
        rng_mode=rng_mode_from_payload(event_payload, default="deterministic_seed"),
    )
    if resolution.ok and resolution.event is not None:
        return resolution.event
    return RNGEvent(
        rng_type=rng_type,
        source=source,
        event_id=event_id,
        before_state=state.rng_state,
        after_state=state.rng_state,
        result={
            "schema": "v8_rng_decision_v1",
            "purpose": purpose,
            "blocked_reason": resolution.blocked_reason,
            "available_rng_outcomes": resolution.available_rng_outcomes(),
            "choice_key": request.choice_key,
            "source_trace": trace,
        },
        metadata={"source_trace": trace, "available_rng_outcomes": resolution.available_rng_outcomes()},
    )


def _status_choice_rng_event(
    state: BattleState,
    *,
    rng_type: str,
    source: str,
    purpose: str,
    candidates: tuple[str, ...],
    trace: dict[str, JSONValue],
    event_payload: dict[str, JSONValue] | None,
) -> RNGEvent:
    event_id = (
        f"rng:{state.event_index}:{rng_type}:{purpose}:"
        f"{trace.get('caster_id')}:{trace.get('target_id')}:{len(candidates)}"
    )
    request = RNGRequest(
        rng_type=rng_type,
        purpose=purpose,
        event_id=event_id,
        choice_key=f"{rng_type}:{purpose}:{trace.get('caster_id')}:{trace.get('target_id')}",
        source=source,
        before_state=state.rng_state,
        decision_kind="choice",
        outcomes=tuple(
            RNGOutcome(
                outcome_id=candidate,
                payload={
                    "candidate_count": len(candidates),
                    "selected_index": index,
                    "selected": candidate,
                    "selected_status_instance_id": candidate,
                    "value": candidate,
                },
                weight=1.0,
            )
            for index, candidate in enumerate(candidates)
        ),
        source_trace=trace,
        metadata={"candidate_count": len(candidates), "candidates": list(candidates)},
    )
    resolution = resolve_rng_request(
        request,
        rng_choices=rng_choices_from_payload(event_payload),
        rng_mode=rng_mode_from_payload(event_payload, default="deterministic_seed"),
    )
    if resolution.ok and resolution.event is not None:
        return resolution.event
    return RNGEvent(
        rng_type=rng_type,
        source=source,
        event_id=event_id,
        before_state=state.rng_state,
        after_state=state.rng_state,
        result={
            "schema": "v8_rng_decision_v1",
            "purpose": purpose,
            "blocked_reason": resolution.blocked_reason,
            "available_rng_outcomes": resolution.available_rng_outcomes(),
            "choice_key": request.choice_key,
            "candidate_count": len(candidates),
            "source_trace": trace,
        },
        metadata={"source_trace": trace, "available_rng_outcomes": resolution.available_rng_outcomes()},
    )


def _deterministic_unit_roll(rng_state: str, event_id: str) -> float:
    raw = f"{rng_state}:{event_id}".encode("utf-8")
    digest = hashlib.sha1(raw).hexdigest()[:12]
    return int(digest, 16) / float(0xFFFFFFFFFFFF)


def _probability(value: object, *, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    return default


def _unit_resource(state: BattleState, unit_id: str, key: str) -> float:
    unit = state.units.get(unit_id)
    if unit is None:
        return 0.0
    value = unit.resources.get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _status_immunity_source(
    state: BattleState,
    target_id: str,
    *,
    status_id: str,
) -> dict[str, JSONValue] | None:
    unit = state.units.get(target_id)
    if unit is None:
        return None
    immunities = unit.flags.get("status_immunities")
    if isinstance(immunities, dict):
        values = immunities.get(status_id) or immunities.get(status_id.removeprefix("modifier:"))
        if isinstance(values, dict) and values.get("admission_status") == "executable":
            return _json_safe(values) if isinstance(_json_safe(values), dict) else {"raw": str(values)}
    details = unit.flags.get("status_details", ())
    if not isinstance(details, (list, tuple)):
        return None
    for detail in details:
        if not isinstance(detail, dict):
            continue
        values = detail.get("immunity_status_ids")
        if isinstance(values, (list, tuple)) and status_id in {str(item) for item in values}:
            source_trace = detail.get("source_trace") if isinstance(detail.get("source_trace"), dict) else {}
            return {
                "status_instance_id": str(detail.get("instance_id") or ""),
                "status_id": str(detail.get("status_id") or ""),
                "source_trace": source_trace,
            }
    return None


def _map_stack_property(property_name: str) -> tuple[str, str, str] | None:
    element_prefixes = {
        "Physical": "Physical",
        "Fire": "Fire",
        "Ice": "Ice",
        "Thunder": "Thunder",
        "Wind": "Wind",
        "Quantum": "Quantum",
        "Imaginary": "Imaginary",
    }
    if property_name == "AllDamageTypeAddedRatio":
        return ("damage_bonus", "damage_added_ratio", "actor")
    for prefix in element_prefixes:
        if property_name == f"{prefix}AddedRatio":
            return ("damage_bonus", f"{prefix}_damage_added_ratio", "actor")
        if property_name == f"{prefix}ResistanceDelta":
            return ("resistance", f"{prefix}_resistance_delta", "target")
    if property_name == "AllResistanceDelta":
        return ("resistance", "all_resistance_delta", "target")
    if property_name in {"DamageTakenRatio", "AllDamageTakenRatio"}:
        return ("damage_taken", "damage_taken_ratio", "target")
    if property_name in {"DefenceReduce", "DefenseReduce", "DefenceReduction", "DefenseReduction"}:
        return ("defense", "def_reduction", "target")
    if property_name in {"DefenceIgnore", "DefenseIgnore"}:
        return ("defense", "def_ignore", "actor")
    return None


def _optional_float(expr: object) -> float | None:
    result = RuleEvaluator().evaluate_numeric(expr, NumericEvaluationContext())
    return result.value if result.ok and result.value is not None else None


def _optional_int(expr: object) -> int | None:
    value = _optional_float(expr)
    return int(value) if value is not None else None


def _runtime_duration_admission(
    standard: dict[str, JSONValue],
    definition: RuleEntity,
    effect: EffectIR,
    binding_sources: tuple[dict[str, JSONValue], ...] = (),
    *,
    status_metadata: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    source_mode = _duration_source_mode(effect.source.source_path)
    if source_mode != "mainline":
        return {
            "admission_status": "blocked",
            "blocked_reason": f"duration_source_mode_not_admitted:{source_mode}",
            "source_mode": source_mode,
            "effect_source": effect.source.to_json(),
        }
    standard_lifetime = standard.get("lifetime")
    definition_lifetime = definition.fields.get("lifetime_expr")
    standard_moment = str(standard.get("life_step_moment") or "")
    definition_moment = str(definition.fields.get("life_step_moment") or "")
    combined_standard = _duration_admission_from_expr(
        standard_lifetime,
        standard_moment or definition_moment,
        source_kind="effect",
        source_trace={"effect_id": effect.effect_id, "effect_source": effect.source.to_json()},
        binding_sources=binding_sources,
    )
    combined_standard = _admit_default_unit_status_lifecycle(
        combined_standard,
        status_metadata=status_metadata or {},
    )
    if combined_standard.get("admission_status") == "executable":
        return combined_standard
    if not _is_missing_numeric_expr(standard_lifetime):
        return combined_standard
    combined_definition = _duration_admission_from_expr(
        definition_lifetime,
        definition_moment,
        source_kind="modifier_definition",
        source_trace={"modifier_definition": definition.source.to_json()},
        binding_sources=binding_sources,
    )
    combined_definition = _admit_default_unit_status_lifecycle(
        combined_definition,
        status_metadata=status_metadata or {},
    )
    if combined_definition.get("admission_status") == "executable":
        return combined_definition
    return combined_standard if combined_standard.get("admission_status") != "not_applicable" else combined_definition


def _admit_default_unit_status_lifecycle(
    admission: dict[str, JSONValue],
    *,
    status_metadata: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    if admission.get("admission_status") != "blocked":
        return admission
    if admission.get("blocked_reason") != "life_step_moment_missing":
        return admission
    status_category = str(status_metadata.get("status_category") or "")
    if status_category not in {"buff", "debuff"}:
        return admission
    if _number_or_none(admission.get("remaining_duration")) is None:
        return admission
    source_trace = admission.get("source_trace") if isinstance(admission.get("source_trace"), dict) else {}
    return {
        **admission,
        "admission_status": "executable",
        "blocked_reason": "",
        "life_step_moment": "ModifierPhase1End",
        "tick_owner_policy": "holder",
        "tick_owner_source": "status_owner",
        "source_trace": {
            **source_trace,
            "default_life_step_moment": {
                "rule": "unit_status_defaults_to_modifier_phase_end",
                "status_type": status_metadata.get("status_type"),
                "status_category": status_category,
                "status_config": status_metadata.get("source"),
            },
        },
    }


def _duration_admission_from_expr(
    lifetime_expr: object,
    life_step_moment: str,
    *,
    source_kind: str,
    source_trace: dict[str, JSONValue],
    binding_sources: tuple[dict[str, JSONValue], ...] = (),
) -> dict[str, JSONValue]:
    result = RuleEvaluator().evaluate_numeric(
        lifetime_expr,
        NumericEvaluationContext(binding_sources=binding_sources, source_trace=source_trace),
    )
    if _is_missing_numeric_expr(lifetime_expr):
        return {
            "admission_status": "not_applicable",
            "blocked_reason": "lifetime_missing",
            "life_step_moment": life_step_moment,
            "source_kind": source_kind,
            "source_trace": source_trace,
            "numeric_evaluation": result.to_json(),
        }
    if not result.ok or result.value is None:
        return {
            "admission_status": "blocked",
            "blocked_reason": result.blocked_reason or f"lifetime_not_executable:{result.expression_kind}",
            "life_step_moment": life_step_moment,
            "source_kind": source_kind,
            "source_trace": source_trace,
            "numeric_evaluation": result.to_json(),
        }
    if result.expression_kind not in {"fixed", "dynamic_hash", "postfix_expr"}:
        return {
            "admission_status": "blocked",
            "blocked_reason": f"lifetime_not_fixed:{result.expression_kind}",
            "life_step_moment": life_step_moment,
            "source_kind": source_kind,
            "source_trace": source_trace,
            "numeric_evaluation": result.to_json(),
        }
    if result.value <= 0:
        return {
            "admission_status": "blocked",
            "blocked_reason": "lifetime_non_positive_or_missing",
            "life_step_moment": life_step_moment,
            "source_kind": source_kind,
            "source_trace": source_trace,
            "numeric_evaluation": result.to_json(),
        }
    if life_step_moment not in SUPPORTED_DURATION_LIFE_STEP_MOMENTS:
        reason = "life_step_moment_missing" if not life_step_moment else f"unsupported_life_step_moment:{life_step_moment}"
        return {
            "admission_status": "blocked",
            "blocked_reason": reason,
            "life_step_moment": life_step_moment,
            "remaining_duration": float(result.value),
            "source_kind": source_kind,
            "source_trace": source_trace,
            "numeric_evaluation": result.to_json(),
        }
    return {
        "admission_status": "executable",
        "blocked_reason": "",
        "life_step_moment": life_step_moment,
        "remaining_duration": float(result.value),
        "tick_owner_policy": "holder",
        "tick_owner_source": "status_owner",
        "source_kind": source_kind,
        "source_trace": source_trace,
        "numeric_evaluation": result.to_json(),
    }


def _admitted_duration_value(duration_admission: dict[str, JSONValue]) -> float | None:
    if duration_admission.get("admission_status") != "executable":
        return None
    value = duration_admission.get("remaining_duration")
    return float(value) if isinstance(value, (int, float)) else None


def _status_instance_duration_value(duration_admission: dict[str, JSONValue]) -> float | None:
    value = _admitted_duration_value(duration_admission)
    if value is not None:
        return value
    if duration_admission.get("admission_status") == "blocked":
        reason = str(duration_admission.get("blocked_reason") or "")
        if reason.startswith("life_step_moment_missing") or reason.startswith("unsupported_life_step_moment"):
            raw_value = duration_admission.get("remaining_duration")
            return float(raw_value) if isinstance(raw_value, (int, float)) else None
    return None


def _duration_source_mode(source_path: str) -> str:
    blocked_markers = (
        "/Activity/",
        "/Rogue/",
        "/GridFight/",
        "/Fate/",
        "/Story/",
        "/Level/",
        "/SubLevelGraph/",
        "/ElationBattle/",
        "Config/Level/",
        "Config/Gameplays/",
    )
    return "special_mode" if any(marker in source_path for marker in blocked_markers) else "mainline"


def _number_or_none(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _status_detail_source_trace(status_detail: dict[str, JSONValue]) -> dict[str, JSONValue]:
    source_trace = status_detail.get("source_trace")
    return dict(source_trace) if isinstance(source_trace, dict) else {}


def _status_detail_duration_admission(status_detail: dict[str, JSONValue]) -> dict[str, JSONValue]:
    admission = status_detail.get("duration_admission")
    if isinstance(admission, dict):
        return dict(admission)
    source_trace = _status_detail_source_trace(status_detail)
    nested = source_trace.get("duration_admission")
    return dict(nested) if isinstance(nested, dict) else {}


def _unsupported_lifecycle_plan(
    operation: str,
    target_id: str,
    status_id: str,
    reason: str,
    source_trace: dict[str, JSONValue],
) -> StatusLifecyclePlan:
    return StatusLifecyclePlan(
        operation=operation,
        target_id=target_id,
        status_id=status_id,
        source="status_system",
        unsupported=(reason,),
        source_trace=source_trace,
    )


def _status_details(unit_flags: dict[str, JSONValue]) -> list[JSONValue]:
    details = unit_flags.get("status_details", ())
    if isinstance(details, list):
        return list(details)
    if isinstance(details, tuple):
        return list(details)
    return []


def _replace_status_detail(
    details: list[JSONValue],
    status_instance: StatusInstance,
    existing_detail: dict[str, JSONValue] | None = None,
) -> list[JSONValue]:
    instance_json = status_instance.to_json()
    existing_instance_id = str(existing_detail.get("instance_id") or "") if isinstance(existing_detail, dict) else ""
    result: list[JSONValue] = []
    replaced = False
    for item in details:
        if isinstance(item, dict) and (
            item.get("instance_id") == status_instance.instance_id
            or (existing_instance_id and item.get("instance_id") == existing_instance_id)
        ):
            if not replaced:
                result.append(instance_json)
                replaced = True
            continue
        result.append(item)
    if not replaced:
        result.append(instance_json)
    return result


def _remove_status_detail(
    details: list[JSONValue],
    status_id: str,
    existing_detail: dict[str, JSONValue] | None,
) -> list[JSONValue]:
    instance_id = str(existing_detail.get("instance_id") or "") if isinstance(existing_detail, dict) else ""
    if instance_id:
        return [
            item
            for item in details
            if not (isinstance(item, dict) and item.get("instance_id") == instance_id)
        ]
    return [
        item
        for item in details
        if not (isinstance(item, dict) and item.get("status_id") == status_id)
    ]


def _status_detail_present(details: list[JSONValue], status_id: str) -> bool:
    return any(isinstance(item, dict) and item.get("status_id") == status_id for item in details)


def _matching_status_detail(
    details: list[JSONValue],
    target_id: str,
    modifier_name: str,
    effect_id: str,
    source_id: str,
) -> dict[str, JSONValue] | None:
    instance_id = _status_instance_id(target_id, modifier_name, effect_id, source_id)
    status_id = f"modifier:{modifier_name}"
    source_stack_key = _source_stack_key(target_id, modifier_name, effect_id, source_id)
    for item in details:
        if not isinstance(item, dict):
            continue
        if item.get("instance_id") == instance_id:
            return item
        if item.get("source_stack_key") == source_stack_key:
            return item
        if item.get("status_id") == status_id and item.get("source_id") == source_id:
            return item
    return None


def _same_status_other_source_detail(
    details: list[JSONValue],
    *,
    status_id: str,
    source_stack_key: str,
) -> dict[str, JSONValue] | None:
    for item in details:
        if not isinstance(item, dict):
            continue
        if item.get("status_id") != status_id:
            continue
        if item.get("source_stack_key") == source_stack_key:
            continue
        return item
    return None


def _find_status_detail(details: list[JSONValue], status_id: str) -> dict[str, JSONValue] | None:
    for item in details:
        if isinstance(item, dict) and item.get("status_id") == status_id:
            return item
    return None


def _source_stack_key(target_id: str, modifier_name: str, effect_id: str, source_id: str) -> str:
    raw = json.dumps(
        {
            "target_id": target_id,
            "modifier_name": modifier_name,
            "effect_id": effect_id,
            "source_id": source_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"status_stack:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"


def _application_semantics(
    standard: dict[str, JSONValue],
    existing_detail: dict[str, JSONValue] | None,
    duration_admission: dict[str, JSONValue],
    stack_admission: dict[str, JSONValue],
    refresh_admission: dict[str, JSONValue],
    *,
    same_status_other_source: dict[str, JSONValue] | None,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    operation = "add"
    if same_status_other_source is not None and existing_detail is None:
        return "coexist_blocked", ["coexist_unsupported:different_source_same_status"]
    if stack_admission.get("admission_status") == "blocked":
        reasons.append(f"stack_blocked:{stack_admission.get('blocked_reason')}")
    if existing_detail is not None:
        max_stacks = _stack_admission_max_stacks(stack_admission) or 1
        layer_delta = stack_admission.get("layer_delta")
        stack_executable = (
            not reasons
            and max_stacks > 1
            and isinstance(layer_delta, int)
            and layer_delta > 0
            and stack_admission.get("stack_policy") == "additive_stack"
        )
        stack_reduce_executable = (
            not reasons
            and isinstance(layer_delta, int)
            and layer_delta < 0
            and stack_admission.get("stack_policy") == "stack_reduce"
        )
        refresh_status = str(refresh_admission.get("admission_status") or "")
        refresh_executable = refresh_status == "executable"
        if stack_executable and refresh_executable:
            operation = "stack_refresh"
        elif stack_executable:
            operation = "stack"
        elif stack_reduce_executable:
            operation = "stack_reduce"
        elif refresh_executable:
            operation = "refresh"
        elif refresh_status == "blocked":
            operation = "reapply_blocked"
            reasons.append(f"refresh_blocked:{refresh_admission.get('blocked_reason')}")
        else:
            operation = "reapply_blocked"
            reasons.append("reapply_unsupported:no_admitted_stack_or_refresh_policy")
    else:
        if stack_admission.get("stack_policy") == "stackable_delta_missing":
            reasons.append("stack_partial:layer_add_when_stack_missing")
        if stack_admission.get("stack_policy") == "stack_reduce":
            operation = "reapply_blocked"
            reasons.append("stack_reduce_blocked:status_detail_missing")
    if duration_admission.get("admission_status") == "blocked":
        reasons.append(f"duration_lifecycle_blocked:{duration_admission.get('blocked_reason')}")
    return operation, reasons


def _is_missing_numeric_expr(expr: object) -> bool:
    return isinstance(expr, dict) and expr.get("kind") == "missing"


def _status_metadata(rules: RuleBook, modifier_name: str) -> dict[str, JSONValue]:
    entity = rules.status_entity_for_modifier(modifier_name)
    if entity is None:
        return {
            "status_type": "Unknown",
            "status_category": "unknown",
            "can_dispel": None,
            "control_kind": "",
            "source": None,
        }
    status_type = str(entity.fields.get("StatusType") or entity.fields.get("status_type") or "Unknown")
    can_dispel = entity.fields.get("CanDispel")
    control_kind = str(entity.fields.get("ControlKind") or entity.fields.get("control_kind") or "")
    return {
        "status_type": status_type,
        "status_category": _status_category(status_type),
        "can_dispel": can_dispel if isinstance(can_dispel, bool) else None,
        "control_kind": control_kind,
        "source": entity.source.to_json(),
    }


def _status_category(status_type: str) -> str:
    normalized = status_type.strip().lower()
    if normalized == "buff":
        return "buff"
    if normalized == "debuff":
        return "debuff"
    if normalized == "other":
        return "other"
    if normalized == "control":
        return "control"
    return "unknown"


def _json_safe(value: object) -> JSONValue:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _definition_dynamic_hash_bindings(definition_bindings: dict[str, JSONValue]) -> dict[str, dict[str, int]]:
    by_hash = definition_bindings.get("by_hash")
    if not isinstance(by_hash, dict):
        return {}
    result: dict[str, dict[str, int]] = {}
    for hash_key, binding in by_hash.items():
        if not isinstance(binding, dict):
            continue
        read_info = binding.get("read_info")
        if not isinstance(read_info, dict):
            continue
        if str(read_info.get("Type") or "") != "None":
            continue
        index = read_info.get("Index")
        if isinstance(index, bool) or not isinstance(index, int):
            continue
        result[str(hash_key)] = {"index": index}
    return result


def _definition_callback_dynamic_hashes(callback_bindings: object) -> dict[str, dict[str, JSONValue]]:
    if not isinstance(callback_bindings, dict):
        return {}
    by_hash = callback_bindings.get("by_hash")
    if not isinstance(by_hash, dict):
        return {}
    result: dict[str, dict[str, JSONValue]] = {}
    for hash_key, binding in by_hash.items():
        if not isinstance(binding, dict):
            continue
        result[str(hash_key)] = _json_safe(binding)
    return result


def _select_modifier_definition(rules: RuleBook, modifier_name: str, source_path: str) -> RuleEntity | None:
    definitions = rules.modifier_definitions(modifier_name)
    if not definitions:
        return rules.modifier_definition(modifier_name)
    exact = tuple(definition for definition in definitions if definition.source.source_path == source_path)
    if exact:
        return exact[0]
    if "/Advanced/" in source_path:
        advanced = tuple(definition for definition in definitions if "/Advanced/" in definition.source.source_path)
        if len(advanced) == 1:
            return advanced[0]
    return definitions[0]


def _trigger_ids_by_event(rules: RuleBook, modifier_name: str, source_path: str = "") -> dict[str, tuple[str, ...]]:
    by_event: dict[str, list[str]] = {}
    for event in sorted({callback.event for callback in rules.ir.status_callbacks if callback.modifier_name == modifier_name}):
        callbacks = tuple(
            callback
            for callback in rules.status_callbacks_for_modifier_event(modifier_name, event)
            if not source_path or callback.source.source_path == source_path
        )
        by_event[event] = [callback.callback_id for callback in callbacks]
    return {event: tuple(callback_ids) for event, callback_ids in sorted(by_event.items())}


def _status_instance_id(target_id: str, modifier_name: str, effect_id: str, source_id: str) -> str:
    raw = json.dumps(
        {
            "target_id": target_id,
            "modifier_name": modifier_name,
            "effect_id": effect_id,
            "source_id": source_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"status:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"
