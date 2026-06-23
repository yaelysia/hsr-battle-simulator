from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from ..core.model import BattleState, JSONValue, Mutation
from ..core.settlement import SettlementRecord
from ..rules.evaluator import NumericEvaluationContext, RuleEvaluator
from ..rules.ir import EffectIR, RuleEntity
from ..rules.rulebook import RuleBook


SUPPORTED_ADD_MODIFIER_ALIASES = {"Caster", "ModifierOwnerEntity", "ParamEntity", "CurrentActionTarget"}
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
    records: tuple[dict[str, JSONValue], ...] = ()
    unsupported: tuple[str, ...] = ()
    status_instance: StatusInstance | None = None
    lifecycle_result: StatusLifecycleResult | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "mutations": [mutation.to_json() for mutation in self.mutations],
            "records": list(self.records),
            "unsupported": list(self.unsupported),
            "status_instance": self.status_instance.to_json() if self.status_instance else None,
            "lifecycle_result": self.lifecycle_result.to_json() if self.lifecycle_result else None,
        }


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
        target_id = _resolve_target_alias(
            target_alias,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
        )
        if target_id is None:
            return _unsupported_result(effect, f"unsupported_or_missing_target_alias:{target_alias}")
        if target_id not in state.units:
            return _unsupported_result(effect, f"target unit {target_id!r} is not in state")

        definition = self.rules.modifier_definition(modifier_name)
        if definition is None:
            return _unsupported_result(effect, f"unknown modifier definition {modifier_name!r}")

        resolved_dynamic_values = _resolve_dynamic_values(
            standard,
            definition,
            dynamic_values,
            binding_sources,
            {"effect_id": effect.effect_id, "effect_source": effect.source.to_json()},
        )
        modifiers, unsupported = _runtime_modifiers(definition, resolved_dynamic_values)
        before_details = _status_details(unit_flags=state.units[target_id].flags)
        existing_detail = _matching_status_detail(before_details, target_id, modifier_name, effect.effect_id, source_id)
        duration_admission = _runtime_duration_admission(standard, definition, effect)
        application_operation, partial_reasons = _application_semantics(standard, existing_detail, duration_admission)
        unsupported = [*unsupported, *partial_reasons]
        duration = _admitted_duration_value(duration_admission)
        life_step_moment = str(duration_admission.get("life_step_moment") or "")
        status_instance = StatusInstance(
            instance_id=_status_instance_id(target_id, modifier_name, effect.effect_id, source_id),
            status_id=f"modifier:{modifier_name}",
            modifier_name=modifier_name,
            owner_id=target_id,
            source_id=source_id,
            caster_id=caster_id,
            stacks=1,
            max_stacks=_optional_int(standard.get("max_layer")),
            duration=duration,
            dynamic_values=resolved_dynamic_values,
            source_trace={
                "effect_id": effect.effect_id,
                "effect_source": effect.source.to_json(),
                "modifier_name": modifier_name,
                "modifier_definition": definition.source.to_json(),
                "duration_admission": duration_admission,
            },
            modifiers=tuple(modifiers),
            trigger_ids_by_event=_trigger_ids_by_event(self.rules, modifier_name),
            unsupported=tuple(unsupported),
            application_operation=application_operation,
            partial=bool(partial_reasons),
            remaining_duration=duration,
            duration_unit=life_step_moment if duration is not None else "permanent_or_unknown",
            life_step_moment=life_step_moment,
            duration_admission=duration_admission,
            stack_policy="unsupported_partial" if any(reason.startswith("stack_unsupported") for reason in unsupported) else "single_instance",
            refresh_policy="unsupported_partial" if any(reason.startswith("refresh_unsupported") for reason in unsupported) else "replace_partial",
            lifecycle_state="active_partial" if partial_reasons else "active",
        )
        plan = StatusLifecyclePlan(
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
        lifecycle_result = self._apply_lifecycle_plan(state, plan)
        return StatusApplicationResult(
            ok=lifecycle_result.ok,
            mutations=lifecycle_result.mutations,
            records=lifecycle_result.records,
            unsupported=lifecycle_result.unsupported,
            status_instance=lifecycle_result.status_instance,
            lifecycle_result=lifecycle_result,
        )

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

    def _apply_lifecycle_plan(self, state: BattleState, plan: StatusLifecyclePlan) -> StatusLifecycleResult:
        if plan.operation in {"add", "refresh_or_replace_partial", "replace_partial", "stack"}:
            return _apply_add_lifecycle_plan(state, plan)
        if plan.operation == "remove":
            return _apply_remove_lifecycle_plan(state, plan)
        if plan.operation == "tick":
            return _apply_tick_lifecycle_plan(state, plan)
        if plan.operation == "expire":
            return _apply_expire_lifecycle_plan(state, plan)
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


def _unsupported_result(effect: EffectIR, reason: str) -> StatusApplicationResult:
    return StatusApplicationResult(
        ok=False,
        records=(
            SettlementRecord(
                record_type="status_unsupported",
                source="status_system",
                process_only=True,
                payload={"reason": reason, "effect_id": effect.effect_id, "opcode": effect.opcode},
                trace={"effect_source": effect.source.to_json()},
            ).to_json(),
        ),
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
    after_details = _replace_status_detail(before_details, plan.status_instance)
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
    status_id_record = SettlementRecord(
        record_type="status_lifecycle",
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
    detail_record = SettlementRecord(
        record_type="status_lifecycle",
        source="status_system",
        mutation_id=detail_mutation.stable_id(),
        process_only=False,
        payload={
            "operation": plan.operation,
            "status_id": plan.status_id,
            "status_instance": plan.status_instance.to_json(),
            "lifecycle_plan": plan.to_json(),
            "unsupported": list(plan.unsupported),
            "partial": plan.partial,
        },
        trace=plan.source_trace,
    ).to_json()
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
    return StatusLifecycleResult(
        ok=True,
        operation=plan.operation,
        mutations=(status_mutation, detail_mutation),
        records=(status_id_record, detail_record, legacy_record),
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
    after_statuses = [status_id for status_id in before_statuses if status_id != plan.status_id]
    after_details = [
        item
        for item in before_details
        if not (isinstance(item, dict) and item.get("status_id") == plan.status_id)
    ]
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
    status_id_record = SettlementRecord(
        record_type="status_lifecycle",
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
        record_type="status_lifecycle",
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
        records=(status_id_record, detail_record),
        lifecycle_plan=plan,
        lifecycle_state="removed",
    )


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
    after_statuses = [status_id for status_id in before_statuses if status_id != plan.status_id]
    after_details = [
        item
        for item in before_details
        if not (
            isinstance(item, dict)
            and (
                item.get("instance_id") == existing.get("instance_id")
                or item.get("status_id") == plan.status_id
            )
        )
    ]
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
    dynamic_values = standard.get("dynamic_values")
    if not isinstance(dynamic_values, dict):
        return values
    bindings = _numeric_bindings(runtime_bindings)
    by_name: dict[str, JSONValue] = {}
    by_hash: dict[str, JSONValue] = {}
    evaluations: list[JSONValue] = []
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
            by_name[str(key)] = result.value
            values[str(key)] = result.value
            hash_key = result.bindings.get("key")
            if isinstance(hash_key, str):
                by_hash[hash_key] = result.value
                values[hash_key] = result.value
    values["__by_name"] = by_name
    values["__by_hash"] = by_hash
    values["__evaluations"] = evaluations
    return values


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
    )
    if combined_definition.get("admission_status") == "executable":
        return combined_definition
    return combined_standard if combined_standard.get("admission_status") != "not_applicable" else combined_definition


def _duration_admission_from_expr(
    lifetime_expr: object,
    life_step_moment: str,
    *,
    source_kind: str,
    source_trace: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    result = RuleEvaluator().evaluate_numeric(lifetime_expr, NumericEvaluationContext(source_trace=source_trace))
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
    if result.expression_kind != "fixed":
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
            "source_kind": source_kind,
            "source_trace": source_trace,
            "numeric_evaluation": result.to_json(),
        }
    return {
        "admission_status": "executable",
        "blocked_reason": "",
        "life_step_moment": life_step_moment,
        "remaining_duration": float(result.value),
        "source_kind": source_kind,
        "source_trace": source_trace,
        "numeric_evaluation": result.to_json(),
    }


def _admitted_duration_value(duration_admission: dict[str, JSONValue]) -> float | None:
    if duration_admission.get("admission_status") != "executable":
        return None
    value = duration_admission.get("remaining_duration")
    return float(value) if isinstance(value, (int, float)) else None


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


def _replace_status_detail(details: list[JSONValue], status_instance: StatusInstance) -> list[JSONValue]:
    instance_json = status_instance.to_json()
    return [
        *(item for item in details if not (isinstance(item, dict) and item.get("instance_id") == status_instance.instance_id)),
        instance_json,
    ]


def _matching_status_detail(
    details: list[JSONValue],
    target_id: str,
    modifier_name: str,
    effect_id: str,
    source_id: str,
) -> dict[str, JSONValue] | None:
    instance_id = _status_instance_id(target_id, modifier_name, effect_id, source_id)
    status_id = f"modifier:{modifier_name}"
    for item in details:
        if not isinstance(item, dict):
            continue
        if item.get("instance_id") == instance_id:
            return item
        if item.get("status_id") == status_id and item.get("source_id") == source_id:
            return item
    return None


def _find_status_detail(details: list[JSONValue], status_id: str) -> dict[str, JSONValue] | None:
    for item in details:
        if isinstance(item, dict) and item.get("status_id") == status_id:
            return item
    return None


def _application_semantics(
    standard: dict[str, JSONValue],
    existing_detail: dict[str, JSONValue] | None,
    duration_admission: dict[str, JSONValue],
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    operation = "add"
    max_layer = _optional_int(standard.get("max_layer"))
    layer_add = _optional_float(standard.get("layer_add_when_stack"))
    chance_expr = standard.get("chance")
    chance = _optional_float(chance_expr)
    if existing_detail is not None:
        operation = "refresh_or_replace_partial"
        reasons.append("refresh_or_replace_partial:existing_status_instance")
    if max_layer is not None and max_layer > 1:
        reasons.append("stack_unsupported:max_layer")
    if layer_add is not None and layer_add != 0:
        reasons.append("stack_unsupported:layer_add_when_stack")
    if bool(standard.get("is_refresh", False)):
        reasons.append("refresh_unsupported:is_refresh")
    if duration_admission.get("admission_status") == "blocked":
        reasons.append(f"duration_lifecycle_blocked:{duration_admission.get('blocked_reason')}")
    if chance is not None and chance != 1.0:
        reasons.append("chance_unsupported:non_guaranteed_add_modifier")
    if chance is None and not _is_missing_numeric_expr(chance_expr):
        reasons.append("chance_formula_unsupported")
    return operation, reasons


def _is_missing_numeric_expr(expr: object) -> bool:
    return isinstance(expr, dict) and expr.get("kind") == "missing"


def _json_safe(value: object) -> JSONValue:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _trigger_ids_by_event(rules: RuleBook, modifier_name: str) -> dict[str, tuple[str, ...]]:
    by_event: dict[str, list[str]] = {}
    for trigger in rules.triggers_for_modifier(modifier_name):
        by_event.setdefault(trigger.event, []).append(trigger.trigger_id)
    return {event: tuple(trigger_ids) for event, trigger_ids in sorted(by_event.items())}


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
