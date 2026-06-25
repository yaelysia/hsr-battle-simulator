from __future__ import annotations

from dataclasses import dataclass, replace

from ..core.model import BattleState, GameEvent, JSONValue, Mutation
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..rules.evaluator import EvaluationContext, NumericEvaluationContext, NumericEvaluationResult, RuleEvaluator
from ..rules.ir import ActionDelayEmissionIR, QueueIntentIR, StatusCallbackIR, StatusCallbackTaskIR, StatusDamageEmissionIR
from ..rules.rulebook import RuleBook
from .damage import DamagePacket, DamageSourceFrame, DamageSystem, DamageWindowLedger
from .dot_formula import DotFormula, DotFormulaInput
from .dynamic_values import binding_source_from_store, find_status_detail, status_binding_sources, store_from_state, upsert_dynamic_value
from .effect import EffectExecutionContext, EffectRegistry
from .queue import QueueEntry, QueueSystem, QueueTargetResolver
from .status import StatusSystem
from .timeline import TimelineSystem


@dataclass(frozen=True)
class StatusCallbackExecutionResult:
    ok: bool
    after_state: BattleState
    mutations: tuple[Mutation, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    events: tuple[GameEvent, ...] = ()
    errors: tuple[str, ...] = ()


class StatusCallbackSystem:
    """Executes admitted modifier-local callbacks from Canonical IR."""

    def __init__(
        self,
        rules: RuleBook,
        *,
        damage: DamageSystem | None = None,
        reducer: MutationReducer | None = None,
        timeline: TimelineSystem | None = None,
        queue: QueueSystem | None = None,
        effect_registry: EffectRegistry | None = None,
    ) -> None:
        self.rules = rules
        self.damage = damage or DamageSystem()
        self.reducer = reducer or MutationReducer()
        self.timeline = timeline or TimelineSystem()
        self.queue = queue or QueueSystem()
        self.queue_targets = QueueTargetResolver()
        self.effect_registry = effect_registry or EffectRegistry(StatusSystem(rules))
        self.evaluator = RuleEvaluator()

    def execute(
        self,
        state: BattleState,
        *,
        unit_id: str,
        modifier_name: str,
        event: str,
        trigger_event: GameEvent | None = None,
        damage_window_ledger: DamageWindowLedger | None = None,
    ) -> StatusCallbackExecutionResult:
        detail = find_status_detail(state, unit_id, modifier_name=modifier_name)
        if detail is None:
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(
                    _callback_blocked_record(
                        modifier_name=modifier_name,
                        event=event,
                        reason="status_detail_missing",
                        trace={},
                    ),
                ),
                errors=("status_detail_missing",),
            )
        callbacks = self.rules.status_callbacks_for_modifier_event(modifier_name, event)
        admitted_callback_ids = _trigger_ids_for_event(detail, event)
        if admitted_callback_ids is not None:
            callbacks = tuple(callback for callback in callbacks if callback.callback_id in admitted_callback_ids)
        if not callbacks:
            return StatusCallbackExecutionResult(
                ok=True,
                after_state=state,
                records=(
                    _callback_blocked_record(
                        modifier_name=modifier_name,
                        event=event,
                        reason="status_callback_missing",
                        trace=_json_dict(detail.get("source_trace")),
                    ),
                ),
            )

        current_state = state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = []
        errors: list[str] = []
        events: list[GameEvent] = []
        for callback in callbacks:
            result = self._execute_callback(current_state, callback, detail, trigger_event, damage_window_ledger)
            current_state = result.after_state
            mutations.extend(result.mutations)
            records.extend(result.records)
            events.extend(result.events)
            errors.extend(result.errors)
        return StatusCallbackExecutionResult(
            ok=not errors,
            after_state=current_state,
            mutations=tuple(mutations),
            records=tuple(records),
            events=tuple(events),
            errors=tuple(errors),
        )

    def _execute_callback(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        damage_window_ledger: DamageWindowLedger | None,
    ) -> StatusCallbackExecutionResult:
        if callback.coverage_status != "executable":
            reason = callback.blocked_reason or f"status_callback_not_executable:{callback.coverage_status}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_callback_blocked_record(callback=callback, detail=detail, reason=reason),),
                errors=(reason,),
            )

        current_state = state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = [
            SettlementRecord(
                record_type="status_callback",
                source="status_callback_system",
                process_only=True,
                payload={
                    "callback_id": callback.callback_id,
                    "modifier_name": callback.modifier_name,
                    "event": callback.event,
                    "task_ids": list(callback.task_ids),
                },
                trace={"callback_source": callback.source.to_json(), "status_source": _json_dict(detail.get("source_trace"))},
            ).to_json()
        ]
        errors: list[str] = []
        events = [
            GameEvent(
                "status.callback",
                source_id=str(detail.get("caster_id") or ""),
                target_id=str(detail.get("owner_id") or ""),
                window=callback.event,
                process_only=True,
                payload={
                    "callback_id": callback.callback_id,
                    "modifier_name": callback.modifier_name,
                    "status_instance_id": str(detail.get("instance_id") or ""),
                },
            )
        ]
        tasks = {task.task_id: task for task in self.rules.status_callback_tasks_for_callback(callback.callback_id)}
        roots = tuple(
            sorted(
                (task for task in tasks.values() if not task.parent_task_id),
                key=lambda item: (item.task_index, item.task_path, item.task_id),
            )
        )
        for task in roots:
            result = self._execute_task(current_state, callback, task, detail, trigger_event, tasks, damage_window_ledger)
            current_state = result.after_state
            mutations.extend(result.mutations)
            records.extend(result.records)
            events.extend(result.events)
            errors.extend(result.errors)
        return StatusCallbackExecutionResult(
            ok=not errors,
            after_state=current_state,
            mutations=tuple(mutations),
            records=tuple(records),
            events=tuple(events),
            errors=tuple(errors),
        )

    def _execute_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        tasks: dict[str, StatusCallbackTaskIR],
        damage_window_ledger: DamageWindowLedger | None,
    ) -> StatusCallbackExecutionResult:
        if task.opcode == "PredicateTaskList":
            return self._execute_predicate_task(state, callback, task, detail, trigger_event, tasks, damage_window_ledger)
        if task.opcode == "Retarget":
            return self._execute_retarget_task(state, callback, task, detail, trigger_event, tasks, damage_window_ledger)
        delay_emissions = [
            emission
            for emission in self.rules.action_delay_emissions_for_callback(callback.callback_id)
            if emission.source_task_id == task.task_id
        ]
        damage_emissions = [
            emission
            for emission in self.rules.status_damage_emissions_for_callback(callback.callback_id)
            if emission.source_task_id == task.task_id
        ]
        queue_intents = [
            intent
            for intent in self.rules.queue_intents_for_callback(callback.callback_id)
            if intent.source_task_id == task.task_id
        ]
        if task.coverage_status != "executable":
            if queue_intents:
                reason = task.blocked_reason or f"status_callback_task_not_executable:{task.coverage_status}"
                return self._blocked_queue_intents(state, callback, task, detail, tuple(queue_intents), reason)
            if delay_emissions:
                return self._execute_delay_emissions(state, callback, task, detail, tuple(delay_emissions))
            if damage_emissions:
                records = tuple(
                    _status_damage_blocked_record(
                        callback,
                        task,
                        detail,
                        emission,
                        emission.blocked_reason or task.blocked_reason or f"status_damage_not_executable:{emission.coverage_status}",
                    )
                    for emission in damage_emissions
                )
                errors = tuple(
                    emission.blocked_reason or task.blocked_reason or f"status_damage_not_executable:{emission.coverage_status}"
                    for emission in damage_emissions
                )
                return StatusCallbackExecutionResult(ok=False, after_state=state, records=records, errors=errors)
            reason = task.blocked_reason or f"status_callback_task_not_executable:{task.coverage_status}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        if damage_emissions:
            return self._execute_damage_emissions(
                state,
                callback,
                task,
                detail,
                tuple(damage_emissions),
                damage_window_ledger,
            )
        if delay_emissions:
            return self._execute_delay_emissions(state, callback, task, detail, tuple(delay_emissions))
        if queue_intents:
            return self._execute_queue_intents(state, callback, task, detail, trigger_event, tuple(queue_intents))
        if task.opcode == "SetDynamicValueByDamageDataProperty":
            return self._execute_set_dynamic_value_by_damage_data_property(state, callback, task, detail, trigger_event, tasks)
        if task.effect_id:
            return self._execute_effect_task(state, callback, task, detail, trigger_event, damage_window_ledger)
        return StatusCallbackExecutionResult(
            ok=True,
            after_state=state,
            records=(_task_blocked_record(callback, task, detail, "status_callback_task_has_no_executable_runtime_effect"),),
        )

    def _execute_predicate_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        tasks: dict[str, StatusCallbackTaskIR],
        damage_window_ledger: DamageWindowLedger | None,
    ) -> StatusCallbackExecutionResult:
        condition = self.rules.condition(task.condition_id) if task.condition_id else None
        if condition is None:
            reason = "missing_predicate_condition"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        result = self.evaluator.evaluate_condition_result(
            condition,
            _condition_context(state, detail, trigger_event),
        )
        if not result.ok or result.result is None:
            reason = f"blocked_condition:{condition.condition_id}:{result.reason}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason, condition_result=result.to_json()),),
                errors=(reason,),
            )
        selected_child_ids = task.success_task_ids if result.result else task.failed_task_ids
        current_state = state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = [
            _task_blocked_record(
                callback,
                task,
                detail,
                "",
                ok=True,
                condition_result=result.to_json(),
                selected_child_ids=selected_child_ids,
            )
        ]
        events: list[GameEvent] = []
        errors: list[str] = []
        precheck_result = self._precheck_selected_queue_group(
            state,
            callback,
            task,
            detail,
            trigger_event,
            selected_child_ids,
            tasks,
        )
        if precheck_result is not None:
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=tuple(records) + precheck_result.records,
                errors=precheck_result.errors,
            )
        for child_id in selected_child_ids:
            child = tasks.get(child_id)
            if child is None:
                reason = f"missing_child_task:{child_id}"
                records.append(_task_blocked_record(callback, task, detail, reason))
                errors.append(reason)
                continue
            child_result = self._execute_task(
                current_state,
                callback,
                child,
                detail,
                trigger_event,
                tasks,
                damage_window_ledger,
            )
            current_state = child_result.after_state
            mutations.extend(child_result.mutations)
            records.extend(child_result.records)
            events.extend(child_result.events)
            errors.extend(child_result.errors)
        return StatusCallbackExecutionResult(
            ok=not errors,
            after_state=current_state,
            mutations=tuple(mutations),
            records=tuple(records),
            events=tuple(events),
            errors=tuple(errors),
        )

    def _execute_retarget_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        tasks: dict[str, StatusCallbackTaskIR],
        damage_window_ledger: DamageWindowLedger | None,
    ) -> StatusCallbackExecutionResult:
        if task.coverage_status != "executable":
            reason = task.blocked_reason or f"retarget_task_not_executable:{task.coverage_status}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        condition = self.rules.condition(task.condition_id) if task.condition_id else None
        if condition is None:
            reason = "missing_retarget_condition"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        candidates = _retarget_candidates(state, task, detail, trigger_event)
        if not candidates:
            return StatusCallbackExecutionResult(
                ok=True,
                after_state=state,
                records=(
                    _task_blocked_record(
                        callback,
                        task,
                        detail,
                        "retarget_candidate_missing",
                        ok=True,
                        selected_child_ids=(),
                    ),
                ),
            )
        max_number = _retarget_max_number(task)
        current_state = state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = []
        events: list[GameEvent] = []
        errors: list[str] = []
        selected_count = 0
        for candidate_id in candidates:
            retarget_event = _retarget_event(trigger_event, candidate_id)
            result = self.evaluator.evaluate_condition_result(
                condition,
                _condition_context(current_state, detail, retarget_event),
            )
            records.append(
                _task_blocked_record(
                    callback,
                    task,
                    detail,
                    "" if result.ok else f"blocked_condition:{condition.condition_id}:{result.reason}",
                    ok=result.ok,
                    condition_result=result.to_json(),
                    selected_child_ids=task.child_task_ids if result.ok and result.result else (),
                )
            )
            if not result.ok or result.result is not True:
                continue
            selected_count += 1
            precheck_result = self._precheck_selected_queue_group(
                current_state,
                callback,
                task,
                detail,
                retarget_event,
                task.child_task_ids,
                tasks,
            )
            if precheck_result is not None:
                return StatusCallbackExecutionResult(
                    ok=False,
                    after_state=current_state,
                    mutations=tuple(mutations),
                    records=tuple(records) + precheck_result.records,
                    events=tuple(events),
                    errors=precheck_result.errors,
                )
            for child_id in task.child_task_ids:
                child = tasks.get(child_id)
                if child is None:
                    reason = f"missing_child_task:{child_id}"
                    records.append(_task_blocked_record(callback, task, detail, reason))
                    errors.append(reason)
                    continue
                child_result = self._execute_task(
                    current_state,
                    callback,
                    child,
                    detail,
                    retarget_event,
                    tasks,
                    damage_window_ledger,
                )
                current_state = child_result.after_state
                mutations.extend(child_result.mutations)
                records.extend(child_result.records)
                events.extend(child_result.events)
                errors.extend(child_result.errors)
            if selected_count >= max_number:
                break
        return StatusCallbackExecutionResult(
            ok=not errors,
            after_state=current_state,
            mutations=tuple(mutations),
            records=tuple(records),
            events=tuple(events),
            errors=tuple(errors),
        )

    def _execute_effect_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        damage_window_ledger: DamageWindowLedger | None,
    ) -> StatusCallbackExecutionResult:
        if task.coverage_status != "executable":
            reason = task.blocked_reason or f"status_callback_task_not_executable:{task.coverage_status}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        effect = self.rules.effect(task.effect_id)
        if effect is None:
            reason = "status_callback_effect_missing"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        list_result = self._execute_list_target_effect_task(state, callback, task, detail, trigger_event, damage_window_ledger, effect)
        if list_result is not None:
            return list_result
        coverage = self.effect_registry.coverage(effect)
        if coverage != "executable":
            reason = f"effect_not_executable:{coverage}"
            result = self.effect_registry.execute(
                effect,
                _effect_context(state, task, detail, trigger_event, damage_window_ledger),
            )
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(*result.records, _task_blocked_record(callback, task, detail, reason)),
                errors=(reason, *result.unsupported),
            )
        result = self.effect_registry.execute(
            effect,
            _effect_context(state, task, detail, trigger_event, damage_window_ledger),
        )
        after_state = self.reducer.apply_all(state, result.mutations)
        records = (
            *result.records,
            _task_blocked_record(
                callback,
                task,
                detail,
                ",".join(result.unsupported),
                ok=not result.unsupported,
                mutation_count=len(result.mutations),
                record_count=len(result.records),
            ),
        )
        return StatusCallbackExecutionResult(
            ok=not result.unsupported,
            after_state=after_state,
            mutations=result.mutations,
            records=records,
            events=result.events,
            errors=result.unsupported,
        )

    def _execute_list_target_effect_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        damage_window_ledger: DamageWindowLedger | None,
        effect,
    ) -> StatusCallbackExecutionResult | None:
        standard = effect.payload.get("standard") if isinstance(effect.payload, dict) else None
        if not isinstance(standard, dict):
            return None
        alias = standard.get("target_alias")
        if alias not in {"ParamEntitySkillTargetEntityList", "AllEnemyWithUnSelectable"}:
            return None
        target_ids = _list_alias_targets(state, detail, trigger_event, str(alias))
        if not target_ids:
            reason = f"list_target_alias_unresolved:{alias}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        current_state = state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = []
        events: list[GameEvent] = []
        errors: list[str] = []
        for target_id in target_ids:
            patched_standard = {**standard, "target_alias": "ParamEntity"}
            patched_effect = replace(effect, payload={**effect.payload, "standard": patched_standard})
            context = _effect_context(current_state, task, detail, trigger_event, damage_window_ledger)
            context = replace(context, param_entity_id=target_id, current_action_target_id=target_id)
            result = self.effect_registry.execute(patched_effect, context)
            current_state = self.reducer.apply_all(current_state, result.mutations)
            mutations.extend(result.mutations)
            records.extend(result.records)
            events.extend(result.events)
            errors.extend(result.unsupported)
        summary = _task_blocked_record(
            callback,
            task,
            detail,
            ",".join(errors),
            ok=not errors,
            mutation_count=len(mutations),
            record_count=len(records),
        )
        payload = summary.get("payload")
        if isinstance(payload, dict):
            payload["target_alias"] = str(alias)
            payload["resolved_target_ids"] = list(target_ids)
        records.append(summary)
        return StatusCallbackExecutionResult(
            ok=not errors,
            after_state=current_state,
            mutations=tuple(mutations),
            records=tuple(records),
            events=tuple(events),
            errors=tuple(errors),
        )

    def _execute_damage_emissions(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        emissions: tuple[StatusDamageEmissionIR, ...],
        damage_window_ledger: DamageWindowLedger | None,
    ) -> StatusCallbackExecutionResult:
        current_state = state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = []
        events: list[GameEvent] = []
        errors: list[str] = []
        for emission in emissions:
            if emission.coverage_status != "executable":
                reason = emission.blocked_reason or f"status_damage_not_executable:{emission.coverage_status}"
                records.append(_status_damage_blocked_record(callback, task, detail, emission, reason))
                errors.append(reason)
                continue
            if emission.damage_formula_family == "dot":
                result = self._execute_dot_damage_emission(current_state, callback, task, detail, emission, damage_window_ledger)
                current_state = result.after_state
                mutations.extend(result.mutations)
                records.extend(result.records)
                events.extend(result.events)
                errors.extend(result.errors)
                continue
            evaluation = self._evaluate_status_damage_amount(current_state, detail, emission)
            if not evaluation.ok or evaluation.value is None:
                reason = evaluation.blocked_reason or "status_damage_numeric_evaluation_failed"
                records.append(_status_damage_blocked_record(callback, task, detail, emission, reason, evaluation=evaluation))
                errors.append(reason)
                continue
            target_id = str(detail.get("owner_id") or "")
            caster_id = str(detail.get("caster_id") or "")
            if target_id not in current_state.units or caster_id not in current_state.units:
                reason = "status_damage_actor_or_target_missing"
                records.append(_status_damage_blocked_record(callback, task, detail, emission, reason, evaluation=evaluation))
                errors.append(reason)
                continue
            if emission.damage_formula_family == "true_damage":
                packet = DamagePacket(
                    attacker_id=caster_id,
                    target_id=target_id,
                    attack_type=emission.attack_type,
                    damage_formula_family="true_damage",
                    amount=float(evaluation.value),
                    element_type=emission.element_type,
                    status_damage_emission_id=emission.status_damage_emission_id,
                    status_callback_id=callback.callback_id,
                    status_instance_id=str(detail.get("instance_id") or ""),
                    modifier_name=callback.modifier_name,
                    source_task_id=task.task_id,
                    source_frame=DamageSourceFrame(
                        owner_id=caster_id,
                        source_id=f"status_damage:{emission.status_damage_emission_id}",
                        source_kind="status_true_damage",
                        sequence_id=f"status_damage:{str(detail.get('instance_id') or '')}:{emission.status_damage_emission_id}",
                        target_id=target_id,
                        can_continue_after_lethal=False,
                        source_trace={
                            "status_damage_source": emission.source.to_json(),
                            "status_callback_source": callback.source.to_json(),
                            "status_task_source": task.source.to_json(),
                            "status_instance_source": _json_dict(detail.get("source_trace")),
                        },
                    ),
                    source_trace={
                        "status_damage_source": emission.source.to_json(),
                        "status_callback_source": callback.source.to_json(),
                        "status_task_source": task.source.to_json(),
                        "status_instance_source": _json_dict(detail.get("source_trace")),
                    },
                    metadata={
                        "damage_formula_family": "true_damage",
                        "record_type": "true_damage",
                        "status_damage_emission_id": emission.status_damage_emission_id,
                        "status_callback_id": callback.callback_id,
                        "status_instance_id": str(detail.get("instance_id") or ""),
                        "modifier_name": callback.modifier_name,
                        "source_task_id": task.task_id,
                        "numeric_evaluation": evaluation.to_json(),
                        "normal_multiplier_terms": [],
                        "bypasses_normal_multipliers": True,
                    },
                )
                damage_result = self.damage.apply_packet(
                    current_state,
                    packet,
                    window_ledger=damage_window_ledger,
                )
                current_state = self.reducer.apply_all(current_state, damage_result.mutations)
                mutations.extend(damage_result.mutations)
                records.extend(damage_result.records)
                events.extend(damage_result.events)
                errors.extend(damage_result.errors)
                continue
            break_template_id = _break_template_id_from_detail(detail)
            if not break_template_id:
                reason = "status_damage_break_template_missing"
                records.append(_status_damage_blocked_record(callback, task, detail, emission, reason, evaluation=evaluation))
                errors.append(reason)
                continue
            packet = DamagePacket(
                attacker_id=caster_id,
                target_id=target_id,
                attack_type=emission.attack_type,
                damage_formula_family="break",
                amount=float(evaluation.value),
                element_type=emission.element_type or _break_element_from_detail(detail),
                status_damage_emission_id=emission.status_damage_emission_id,
                status_callback_id=callback.callback_id,
                status_instance_id=str(detail.get("instance_id") or ""),
                modifier_name=callback.modifier_name,
                break_template_id=break_template_id,
                source_task_id=task.task_id,
                source_frame=DamageSourceFrame(
                    owner_id=caster_id,
                    source_id=f"status_damage:{emission.status_damage_emission_id}",
                    source_kind="status_damage",
                    sequence_id=f"status_damage:{str(detail.get('instance_id') or '')}:{emission.status_damage_emission_id}",
                    target_id=target_id,
                    can_continue_after_lethal=False,
                    source_trace={
                        "status_damage_source": emission.source.to_json(),
                        "status_callback_source": callback.source.to_json(),
                        "status_task_source": task.source.to_json(),
                        "status_instance_source": _json_dict(detail.get("source_trace")),
                    },
                ),
                source_trace={
                    "status_damage_source": emission.source.to_json(),
                    "status_callback_source": callback.source.to_json(),
                    "status_task_source": task.source.to_json(),
                    "status_instance_source": _json_dict(detail.get("source_trace")),
                },
                metadata={
                    "damage_formula_family": "break",
                    "record_type": "break_dot_tick",
                    "status_damage_emission_id": emission.status_damage_emission_id,
                    "status_callback_id": callback.callback_id,
                    "status_instance_id": str(detail.get("instance_id") or ""),
                    "modifier_name": callback.modifier_name,
                    "source_task_id": task.task_id,
                    "damage_source_owner_id": caster_id,
                    "damage_source_id": f"status_damage:{emission.status_damage_emission_id}",
                    "damage_source_kind": "status_damage",
                    "damage_sequence_id": f"status_damage:{str(detail.get('instance_id') or '')}:{emission.status_damage_emission_id}",
                    "can_continue_after_lethal": False,
                    "break_template_id": break_template_id,
                    "numeric_evaluation": evaluation.to_json(),
                    "break_base_damage_source": _break_base_source_from_evaluation(evaluation),
                    "source_trace": {
                        "status_damage_source": emission.source.to_json(),
                        "status_callback_source": callback.source.to_json(),
                        "status_task_source": task.source.to_json(),
                        "status_instance_source": _json_dict(detail.get("source_trace")),
                    },
                },
            )
            damage_result = self.damage.apply_packet(
                current_state,
                packet,
                window_ledger=damage_window_ledger,
            )
            current_state = self.reducer.apply_all(current_state, damage_result.mutations)
            mutations.extend(damage_result.mutations)
            records.extend(damage_result.records)
            events.extend(damage_result.events)
            errors.extend(damage_result.errors)
        return StatusCallbackExecutionResult(
            ok=not errors,
            after_state=current_state,
            mutations=tuple(mutations),
            records=tuple(records),
            events=tuple(events),
            errors=tuple(errors),
        )

    def _execute_set_dynamic_value_by_damage_data_property(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        tasks: dict[str, StatusCallbackTaskIR],
    ) -> StatusCallbackExecutionResult:
        payload = task.source.evidence.get("task") if isinstance(task.source.evidence, dict) else None
        if not isinstance(payload, dict):
            reason = "set_dynamic_value_damage_property_payload_missing"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        dynamic_key = _value_field(payload.get("DynamicKey"))
        property_name = _value_field(payload.get("Property"))
        if not isinstance(dynamic_key, str) or not dynamic_key:
            reason = "dynamic_value_name_required"
            return StatusCallbackExecutionResult(ok=False, after_state=state, records=(_task_blocked_record(callback, task, detail, reason),), errors=(reason,))
        if property_name not in {"Result_FinalDamageBase", "Result_FinalDamage"}:
            reason = f"damage_data_property_not_admitted:{property_name}"
            return StatusCallbackExecutionResult(ok=False, after_state=state, records=(_task_blocked_record(callback, task, detail, reason),), errors=(reason,))
        event_payload = trigger_event.payload if trigger_event is not None and isinstance(trigger_event.payload, dict) else {}
        value = _damage_property_value(event_payload, str(property_name))
        if value is None:
            reason = f"damage_data_property_missing:{property_name}"
            return StatusCallbackExecutionResult(ok=False, after_state=state, records=(_task_blocked_record(callback, task, detail, reason),), errors=(reason,))
        owner_id = str(detail.get("owner_id") or "")
        store_before = store_from_state(state)
        source_trace = {
                "status_callback_source": callback.source.to_json(),
                "status_task_source": task.source.to_json(),
                "status_instance_source": _json_dict(detail.get("source_trace")),
                "trigger_event": trigger_event.to_json() if trigger_event is not None else {},
        }
        aliases = _dynamic_hash_aliases_for_damage_property_task(task, tasks)
        store_after = store_before
        if aliases:
            for alias in aliases:
                store_after = upsert_dynamic_value(
                    store_after,
                    scope="status_callback",
                    owner_id=owner_id,
                    value=float(value),
                    value_name=dynamic_key,
                    hash_key=alias.get("hash"),
                    status_id=str(detail.get("status_id") or ""),
                    status_instance_id=str(detail.get("instance_id") or ""),
                    effect_id=task.task_id,
                    source_trace={**source_trace, "dynamic_hash_alias": alias},
                )
        else:
            store_after = upsert_dynamic_value(
                store_after,
                scope="status_callback",
                owner_id=owner_id,
                value=float(value),
                value_name=dynamic_key,
                status_id=str(detail.get("status_id") or ""),
                status_instance_id=str(detail.get("instance_id") or ""),
                effect_id=task.task_id,
                source_trace=source_trace,
            )
        mutation = Mutation(
            op="set",
            path=("global_flags", "dynamic_value_store"),
            before=store_before,
            after=store_after,
            reason="set dynamic value from damage data property",
            source="status_callback_system",
            metadata={
                "callback_id": callback.callback_id,
                "task_id": task.task_id,
                "modifier_name": callback.modifier_name,
                "dynamic_key": dynamic_key,
                "dynamic_hash_aliases": aliases,
                "property": property_name,
                "value": float(value),
                "source_trace": source_trace,
            },
        )
        after_state = self.reducer.apply_all(state, (mutation,))
        return StatusCallbackExecutionResult(
            ok=True,
            after_state=after_state,
            mutations=(mutation,),
            records=(
                SettlementRecord(
                    record_type="dynamic_value_store",
                    source="status_callback_system",
                    mutation_id=mutation.stable_id(),
                    process_only=False,
                    payload={
                        "callback_id": callback.callback_id,
                        "task_id": task.task_id,
                        "modifier_name": callback.modifier_name,
                        "dynamic_key": dynamic_key,
                        "dynamic_hash_aliases": aliases,
                        "property": property_name,
                        "value": float(value),
                    },
                    trace=mutation.metadata.get("source_trace", {}),
                ).to_json(),
            ),
        )

    def _execute_dot_damage_emission(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        emission: StatusDamageEmissionIR,
        damage_window_ledger: DamageWindowLedger | None,
    ) -> StatusCallbackExecutionResult:
        target_id = str(detail.get("owner_id") or "")
        caster_id = str(detail.get("caster_id") or "")
        if target_id not in state.units or caster_id not in state.units:
            reason = "status_damage_actor_or_target_missing"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_status_damage_blocked_record(callback, task, detail, emission, reason),),
                errors=(reason,),
            )
        trace = {
            "status_damage_source": emission.source.to_json(),
            "status_callback_source": callback.source.to_json(),
            "status_task_source": task.source.to_json(),
            "status_instance_source": _json_dict(detail.get("source_trace")),
        }
        formula_result = DotFormula().calculate(
            DotFormulaInput(
                state=state,
                caster_id=caster_id,
                target_id=target_id,
                status_detail=detail,
                emission=emission,
                source_trace=trace,
            )
        )
        if not formula_result.ok:
            reason = formula_result.blocked_reason or "dot_formula_evaluation_failed"
            records = (
                _status_damage_blocked_record(
                    callback,
                    task,
                    detail,
                    emission,
                    reason,
                    evaluation_payload=formula_result.to_json(),
                ),
            )
            return StatusCallbackExecutionResult(ok=False, after_state=state, records=records, errors=(reason,))
        source_id = f"status_damage:{emission.status_damage_emission_id}"
        sequence_id = f"status_damage:{str(detail.get('instance_id') or '')}:{emission.status_damage_emission_id}"
        packet = DamagePacket(
            attacker_id=caster_id,
            target_id=target_id,
            attack_type=emission.attack_type,
            damage_formula_family="dot",
            amount=formula_result.final_damage,
            element_type=emission.element_type,
            status_damage_emission_id=emission.status_damage_emission_id,
            status_callback_id=callback.callback_id,
            status_instance_id=str(detail.get("instance_id") or ""),
            modifier_name=callback.modifier_name,
            source_task_id=task.task_id,
            source_frame=DamageSourceFrame(
                owner_id=caster_id,
                source_id=source_id,
                source_kind="dot",
                sequence_id=sequence_id,
                target_id=target_id,
                can_continue_after_lethal=False,
                source_trace=trace,
            ),
            source_trace=trace,
            metadata={
                "damage_formula_family": "dot",
                "record_type": "dot_damage",
                "status_damage_emission_id": emission.status_damage_emission_id,
                "status_callback_id": callback.callback_id,
                "status_instance_id": str(detail.get("instance_id") or ""),
                "modifier_name": callback.modifier_name,
                "source_task_id": task.task_id,
                "damage_source_owner_id": caster_id,
                "damage_source_id": source_id,
                "damage_source_kind": "dot",
                "damage_sequence_id": sequence_id,
                "can_continue_after_lethal": False,
                "numeric_evaluation": formula_result.primary_numeric_evaluation,
                "dot_formula_result": formula_result.to_json(),
                "dot_ledger": formula_result.dot_ledger,
                "source_trace": trace,
            },
        )
        damage_result = self.damage.apply_packet(state, packet, window_ledger=damage_window_ledger)
        after_state = self.reducer.apply_all(state, damage_result.mutations)
        return StatusCallbackExecutionResult(
            ok=not damage_result.errors,
            after_state=after_state,
            mutations=damage_result.mutations,
            records=damage_result.records,
            events=damage_result.events,
            errors=damage_result.errors,
        )

    def _execute_delay_emissions(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        emissions: tuple[ActionDelayEmissionIR, ...],
    ) -> StatusCallbackExecutionResult:
        current_state = state
        mutations: list[Mutation] = []
        records = []
        errors = []
        for emission in emissions:
            if emission.coverage_status != "executable":
                reason = emission.blocked_reason or f"action_delay_not_executable:{emission.coverage_status}"
                records.append(_action_delay_blocked_record(callback, task, detail, emission, reason))
                errors.append(reason)
                continue
            if emission.opcode != "SetActionDelay":
                reason = "normalized_action_delay_scale_not_admitted"
                records.append(_action_delay_blocked_record(callback, task, detail, emission, reason))
                errors.append(reason)
                continue
            target_id = _resolve_callback_target_id(detail, emission.target_alias)
            if not target_id or target_id not in current_state.units:
                reason = f"action_delay_target_not_resolved:{emission.target_alias or 'unknown'}"
                records.append(_action_delay_blocked_record(callback, task, detail, emission, reason))
                errors.append(reason)
                continue
            evaluation = RuleEvaluator().evaluate_numeric(
                emission.delay_expr,
                NumericEvaluationContext(
                    binding_sources=(_status_delay_binding_source(detail, emission),),
                    source_trace={
                        "action_delay_source": emission.source.to_json(),
                        "status_callback_source": callback.source.to_json(),
                        "status_instance_source": _json_dict(detail.get("source_trace")),
                    },
                ),
            )
            if not evaluation.ok or evaluation.value is None:
                reason = evaluation.blocked_reason or "action_delay_numeric_evaluation_failed"
                records.append(_action_delay_blocked_record(callback, task, detail, emission, reason, evaluation=evaluation))
                errors.append(reason)
                continue
            mutation = self.timeline.set_action_value(
                current_state,
                target_id,
                float(evaluation.value),
                source="status_callback_system",
                metadata={
                    "callback_id": callback.callback_id,
                    "task_id": task.task_id,
                    "action_delay_emission_id": emission.action_delay_emission_id,
                    "modifier_name": callback.modifier_name,
                    "event": callback.event,
                    "opcode": emission.opcode,
                    "target_alias": emission.target_alias or "",
                    "numeric_evaluation": evaluation.to_json(),
                    "source_trace": {
                        "action_delay_source": emission.source.to_json(),
                        "status_callback_source": callback.source.to_json(),
                        "status_task_source": task.source.to_json(),
                        "status_instance_source": _json_dict(detail.get("source_trace")),
                    },
                },
            )
            current_state = self.reducer.apply_all(current_state, (mutation,))
            mutations.append(mutation)
            records.append(
                SettlementRecord(
                    record_type="action_delay",
                    source="status_callback_system",
                    mutation_id=mutation.stable_id(),
                    process_only=False,
                    payload={
                        "callback_id": callback.callback_id,
                        "task_id": task.task_id,
                        "action_delay_emission_id": emission.action_delay_emission_id,
                        "modifier_name": callback.modifier_name,
                        "event": callback.event,
                        "target_id": target_id,
                        "action_value": float(evaluation.value),
                        "numeric_evaluation": evaluation.to_json(),
                    },
                    trace={
                        "action_delay_source": emission.source.to_json(),
                        "status_callback_source": callback.source.to_json(),
                        "status_instance_source": _json_dict(detail.get("source_trace")),
                    },
                ).to_json()
            )
        return StatusCallbackExecutionResult(
            ok=not errors,
            after_state=current_state,
            mutations=tuple(mutations),
            records=tuple(records),
            errors=tuple(errors),
        )

    def _evaluate_status_damage_amount(
        self,
        state: BattleState,
        detail: dict[str, JSONValue],
        emission: StatusDamageEmissionIR,
    ) -> NumericEvaluationResult:
        caster_id = str(detail.get("caster_id") or "")
        target_id = str(detail.get("owner_id") or "")
        actor = state.units.get(caster_id)
        target = state.units.get(target_id)
        if actor is None or target is None:
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="status_damage",
                bindings={},
                source_trace=emission.source.to_json(),
                blocked_reason="actor_or_target_missing",
            )
        if emission.damage_formula_family == "true_damage":
            sources = (
                *status_binding_sources(state, tuple(unit_id for unit_id in (caster_id, target_id) if unit_id)),
                binding_source_from_store(store_from_state(state)),
            )
            return RuleEvaluator().evaluate_numeric(
                emission.scaling_expr,
                NumericEvaluationContext(
                    binding_sources=sources,
                    source_trace={
                        "status_damage_source": emission.source.to_json(),
                        "status_instance_source": _json_dict(detail.get("source_trace")),
                    },
                ),
            )
        break_base = self.rules.break_base_damage(actor.level)
        if break_base is None or break_base.coverage_status != "executable":
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="status_damage",
                bindings={"actor_level": actor.level},
                source_trace=emission.source.to_json(),
                blocked_reason="break_base_damage_missing_or_not_executable",
            )
        sources = _status_damage_binding_sources(detail, emission, break_base.to_json())
        if not sources:
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="status_damage",
                bindings={"status_instance_id": detail.get("instance_id")},
                source_trace=emission.source.to_json(),
                blocked_reason="status_damage_binding_source_not_admitted",
            )
        return RuleEvaluator().evaluate_numeric(
            emission.scaling_expr,
            NumericEvaluationContext(
                binding_sources=sources,
                source_trace={
                    "status_damage_source": emission.source.to_json(),
                    "status_instance_source": _json_dict(detail.get("source_trace")),
                    "break_base_damage_source": break_base.source.to_json(),
                },
            ),
        )

    def _execute_queue_intents(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        intents: tuple[QueueIntentIR, ...],
    ) -> StatusCallbackExecutionResult:
        current_state = state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = []
        errors: list[str] = []
        for intent in intents:
            if intent.coverage_status != "executable":
                reason = intent.blocked_reason or f"queue_intent_not_executable:{intent.coverage_status}"
                records.append(_queue_intent_blocked_record(callback, task, detail, intent, reason))
                errors.append(reason)
                continue
            window = self.rules.queue_window_for_intent(intent.queue_intent_id)
            if window is None:
                reason = "queue_window_ir_missing"
                records.append(_queue_intent_blocked_record(callback, task, detail, intent, reason))
                errors.append(reason)
                continue
            if window.coverage_status != "executable":
                reason = window.blocked_reason or f"queue_window_not_executable:{window.coverage_status}"
                records.append(_queue_intent_blocked_record(callback, task, detail, intent, reason))
                errors.append(reason)
                continue
            target_resolution = self.queue_targets.resolve(
                current_state,
                detail=detail,
                trigger_event=trigger_event,
                actor_alias=intent.actor_target_alias,
                target_alias=intent.ability_target_alias,
                source_trace={
                    "queue_window_source": window.source.to_json(),
                    "queue_intent_source": intent.source.to_json(),
                },
            )
            if not target_resolution.ok:
                reason = target_resolution.blocked_reason or "queue_target_resolution_failed"
                records.append(_queue_intent_blocked_record(callback, task, detail, intent, reason))
                errors.append(reason)
                continue
            precheck_reason = _queue_insert_precheck_blocked(current_state, intent, target_resolution.actor_id)
            if precheck_reason:
                records.append(_queue_intent_blocked_record(callback, task, detail, intent, precheck_reason))
                errors.append(precheck_reason)
                continue
            lifecycle_policy_id = ""
            extra_action_policy_id = ""
            if isinstance(window.window_policy, dict):
                lifecycle_policy_id = str(window.window_policy.get("queue_lifecycle_policy_id") or "")
                extra_action_policy_id = str(window.window_policy.get("extra_action_policy_id") or "")
            queue_name = intent.queue_kind
            source_trace = {
                "queue_intent_source": intent.source.to_json(),
                "queue_window_source": window.source.to_json(),
                "queue_lifecycle_policy_id": lifecycle_policy_id,
                "extra_action_policy_id": extra_action_policy_id,
                "queue_intent_resource_policy": _queue_resource_policy(intent),
                "status_callback_source": callback.source.to_json(),
                "status_task_source": task.source.to_json(),
                "status_instance_source": _json_dict(detail.get("source_trace")),
            }
            entry = QueueEntry(
                entry_id=f"queue_entry:{intent.queue_intent_id}:{len(current_state.queues.get(queue_name, ()))}",
                queue_name=queue_name,
                queue_kind=intent.queue_kind,
                queue_intent_id=intent.queue_intent_id,
                actor_id=target_resolution.actor_id,
                action_or_ability_ref=intent.action_ref_or_ability_name,
                target_ids=target_resolution.target_ids,
                priority_source=intent.priority_source,
                source_trace=source_trace,
                priority_key=str(intent.priority_source.get("priority_key") or ""),
                priority_value=_json_float(intent.priority_source.get("priority_value")),
                queue_priority_id=str(intent.priority_source.get("queue_priority_id") or ""),
                priority_source_trace=_json_dict(intent.priority_source.get("source_trace")),
                queue_window_id=window.queue_window_id,
                window_family=window.window_family,
                window_policy=window.window_policy,
                target_resolution=target_resolution.to_json(),
                status="pending",
                drain_status="not_admitted",
            )
            mutation = self.queue.enqueue(
                current_state,
                queue_name,
                entry,
                source="queue_system",
                metadata={
                    "queue_intent_id": intent.queue_intent_id,
                    "source_task_id": task.task_id,
                    "callback_id": callback.callback_id,
                    "opcode": intent.opcode,
                    "queue_kind": intent.queue_kind,
                    "queue_priority_id": entry.queue_priority_id,
                    "queue_window_id": entry.queue_window_id,
                    "queue_lifecycle_policy_id": lifecycle_policy_id,
                    "extra_action_policy_id": extra_action_policy_id,
                    "window_family": entry.window_family,
                    "priority_key": entry.priority_key,
                    "priority_value": entry.priority_value,
                    "admission_result": "executable",
                    "target_resolution": target_resolution.to_json(),
                    "source_trace": source_trace,
                },
            )
            current_state = self.reducer.apply_all(current_state, (mutation,))
            mutations.append(mutation)
            records.append(
                SettlementRecord(
                    record_type="queue_enqueue",
                    source="queue_system",
                    mutation_id=mutation.stable_id(),
                    process_only=False,
                    payload={
                        "queue_intent_id": intent.queue_intent_id,
                        "callback_id": callback.callback_id,
                        "task_id": task.task_id,
                        "opcode": intent.opcode,
                        "queue_name": queue_name,
                        "queue_kind": intent.queue_kind,
                        "entry": entry.to_json(),
                        "queue_window": window.to_json(),
                        "drain_candidate": False,
                        "drain_blocked_reason": "queue_drain_pending_resolution",
                    },
                    trace=source_trace,
                ).to_json()
            )
        return StatusCallbackExecutionResult(
            ok=not errors,
            after_state=current_state,
            mutations=tuple(mutations),
            records=tuple(records),
            errors=tuple(errors),
        )

    def _precheck_selected_queue_group(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        parent_task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        selected_child_ids: tuple[str, ...],
        tasks: dict[str, StatusCallbackTaskIR],
    ) -> StatusCallbackExecutionResult | None:
        for child_id in selected_child_ids:
            child = tasks.get(child_id)
            if child is None:
                continue
            intents = tuple(
                intent
                for intent in self.rules.queue_intents_for_callback(callback.callback_id)
                if intent.source_task_id == child.task_id
            )
            if not intents:
                continue
            for intent in intents:
                if intent.coverage_status != "executable":
                    continue
                window = self.rules.queue_window_for_intent(intent.queue_intent_id)
                if window is None or window.coverage_status != "executable":
                    continue
                target_resolution = self.queue_targets.resolve(
                    state,
                    detail=detail,
                    trigger_event=trigger_event,
                    actor_alias=intent.actor_target_alias,
                    target_alias=intent.ability_target_alias,
                    source_trace={
                        "queue_window_source": window.source.to_json(),
                        "queue_intent_source": intent.source.to_json(),
                    },
                )
                if not target_resolution.ok:
                    continue
                reason = _queue_insert_precheck_blocked(state, intent, target_resolution.actor_id)
                if not reason:
                    continue
                records = (
                    _task_blocked_record(
                        callback,
                        parent_task,
                        detail,
                        reason,
                        ok=False,
                        selected_child_ids=selected_child_ids,
                    ),
                    _queue_intent_blocked_record(callback, child, detail, intent, reason),
                )
                return StatusCallbackExecutionResult(
                    ok=False,
                    after_state=state,
                    records=records,
                    errors=(reason,),
                )
        return None

    def _blocked_queue_intents(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        intents: tuple[QueueIntentIR, ...],
        reason: str,
    ) -> StatusCallbackExecutionResult:
        blocked_reason = f"queue_task_not_executable:{reason}"
        return StatusCallbackExecutionResult(
            ok=False,
            after_state=state,
            records=tuple(
                _queue_intent_blocked_record(callback, task, detail, intent, blocked_reason)
                for intent in intents
            ),
            errors=(blocked_reason,),
        )


def _queue_resource_policy(intent: QueueIntentIR) -> dict[str, JSONValue]:
    policy = intent.abort_policy.get("resource_policy") if isinstance(intent.abort_policy, dict) else None
    return policy if isinstance(policy, dict) else {}


def _queue_insert_precheck_blocked(state: BattleState, intent: QueueIntentIR, actor_id: str) -> str:
    policy = intent.abort_policy.get("insert_once_policy") if isinstance(intent.abort_policy, dict) else None
    if not isinstance(policy, dict):
        return ""
    if policy.get("kind") != "same_tag_insert_unused_count":
        return ""
    used_modifiers = tuple(str(item) for item in policy.get("used_modifier_names", ()) if isinstance(item, str) and item)
    if not used_modifiers:
        return "queue_insert_precheck_used_marker_missing"
    actor = state.units.get(actor_id)
    if actor is None:
        return "queue_insert_precheck_actor_missing"
    active_modifiers = set(actor.statuses)
    detail_modifiers = {
        str(detail.get("modifier_name") or "")
        for detail in actor.flags.get("status_details", ())
        if isinstance(detail, dict)
    }
    for modifier_name in used_modifiers:
        if modifier_name in active_modifiers or f"modifier:{modifier_name}" in active_modifiers or modifier_name in detail_modifiers:
            return "queue_insert_precheck_same_tag_already_used"
    return ""


def _retarget_candidates(
    state: BattleState,
    task: StatusCallbackTaskIR,
    detail: dict[str, JSONValue],
    trigger_event: GameEvent | None,
) -> tuple[str, ...]:
    evidence = task.source.evidence.get("retarget") if isinstance(task.source.evidence, dict) else None
    if not isinstance(evidence, dict):
        return ()
    alias = str(evidence.get("target_alias") or "")
    if alias != "ParamEntityAttackTargetList.SortByHP":
        return ()
    payload = trigger_event.payload if trigger_event is not None and isinstance(trigger_event.payload, dict) else {}
    candidates = _unique_ids(
        payload.get("param_entity_attack_target_ids"),
        payload.get("selected_target_ids"),
        payload.get("target_ids"),
        payload.get("current_hit_target_id"),
        payload.get("primary_target_id"),
        payload.get("target_id"),
    )
    candidates = tuple(unit_id for unit_id in candidates if unit_id in state.units)
    alive_candidates = tuple(unit_id for unit_id in candidates if _unit_alive(state, unit_id))
    if not alive_candidates:
        alive_candidates = _alive_enemy_ids_for_status_owner(state, detail)
    return tuple(sorted(alive_candidates, key=lambda unit_id: (_hp_ratio(state, unit_id), state.units[unit_id].hp, unit_id)))


def _retarget_max_number(task: StatusCallbackTaskIR) -> int:
    evidence = task.source.evidence.get("retarget") if isinstance(task.source.evidence, dict) else None
    expr = evidence.get("max_number_expr") if isinstance(evidence, dict) else None
    if isinstance(expr, dict) and expr.get("kind") == "fixed":
        value = expr.get("value")
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
    return 1


def _retarget_event(event: GameEvent | None, target_id: str) -> GameEvent:
    payload = dict(event.payload) if event is not None and isinstance(event.payload, dict) else {}
    payload.update(
        {
            "param_entity_id": target_id,
            "current_hit_target_id": target_id,
            "target_id": target_id,
            "retargeted": True,
            "retarget_source_event_id": event.event_id if event is not None else "",
        }
    )
    return GameEvent(
        event.event_type if event is not None else "status.retarget",
        source_id=event.source_id if event is not None else "",
        target_id=target_id,
        event_id=f"{event.event_id}:retarget:{target_id}" if event is not None and event.event_id else f"event:retarget:{target_id}",
        window=event.window if event is not None else "Retarget",
        process_only=True,
        payload=payload,
    )


def _unique_ids(*values: object) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if isinstance(value, str):
            if value and value not in result:
                result.append(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str) and item and item not in result:
                    result.append(item)
    return tuple(result)


def _unit_alive(state: BattleState, unit_id: str) -> bool:
    unit = state.units.get(unit_id)
    return unit is not None and unit.hp > 0


def _alive_enemy_ids_for_status_owner(state: BattleState, detail: dict[str, JSONValue]) -> tuple[str, ...]:
    owner_id = str(detail.get("owner_id") or "")
    owner = state.units.get(owner_id)
    if owner is None:
        return ()
    return tuple(
        unit_id
        for unit_id, unit in state.units.items()
        if unit.side != owner.side and unit.hp > 0
    )


def _hp_ratio(state: BattleState, unit_id: str) -> float:
    unit = state.units[unit_id]
    return float(unit.hp / unit.max_hp) if unit.max_hp > 0 else float("inf")


def _status_damage_binding_sources(
    detail: dict[str, JSONValue],
    emission: StatusDamageEmissionIR,
    break_base_damage: dict[str, JSONValue],
) -> tuple[dict[str, JSONValue], ...]:
    hashes = _postfix_dynamic_hashes(emission.scaling_expr)
    if not hashes:
        return ()
    base_source = _single_entry_source(
        source_type="break_template_runtime_value",
        entry_key="break_base_damage",
        hash_key=str(hashes[0]),
        name="CasterBreakBaseDamage",
        owner_id=str(detail.get("caster_id") or ""),
        value=float(break_base_damage.get("break_base_damage") or 0.0),
        source_trace={
            "dynamic_key": "CasterBreakBaseDamage",
            "break_base_damage": break_base_damage,
            "status_instance_source": _json_dict(detail.get("source_trace")),
        },
    )
    if len(hashes) == 1:
        return (base_source,)
    if len(hashes) != 2:
        return ()
    status_entry = _single_status_dynamic_entry(detail, str(hashes[1]))
    if status_entry is None:
        return ()
    return (base_source, status_entry)


def _status_delay_binding_source(
    detail: dict[str, JSONValue],
    emission: ActionDelayEmissionIR,
) -> dict[str, JSONValue]:
    hashes = _postfix_dynamic_hashes(emission.delay_expr)
    if len(hashes) != 1:
        return {
            "source_type": "status_instance",
            "entries": {},
            "by_hash": {},
            "by_name": {},
        }
    status_entry = _single_status_dynamic_entry(detail, str(hashes[0]))
    if status_entry is not None:
        return status_entry
    return {
        "source_type": "status_instance",
        "entries": {},
        "by_hash": {},
        "by_name": {},
    }


def _single_status_dynamic_entry(detail: dict[str, JSONValue], hash_key: str) -> dict[str, JSONValue] | None:
    dynamic_values = detail.get("dynamic_values")
    if not isinstance(dynamic_values, dict):
        return None
    by_hash = dynamic_values.get("__by_hash")
    if isinstance(by_hash, dict) and isinstance(by_hash.get(hash_key), (int, float)):
        return _single_entry_source(
            source_type="status_instance",
            entry_key=f"status_hash:{hash_key}",
            hash_key=hash_key,
            name=None,
            owner_id=str(detail.get("owner_id") or ""),
            value=float(by_hash[hash_key]),
            source_trace=_json_dict(detail.get("source_trace")),
            status_id=str(detail.get("status_id") or ""),
            status_instance_id=str(detail.get("instance_id") or ""),
        )
    candidates = [
        (str(key), float(value))
        for key, value in dynamic_values.items()
        if not str(key).startswith("__") and isinstance(value, (int, float))
    ]
    if len(candidates) != 1:
        return None
    name, value = candidates[0]
    return _single_entry_source(
        source_type="status_instance",
        entry_key=f"status_dynamic:{name}:{hash_key}",
        hash_key=hash_key,
        name=name,
        owner_id=str(detail.get("owner_id") or ""),
        value=value,
        source_trace={
            **_json_dict(detail.get("source_trace")),
            "binding_reason": "single_remaining_status_dynamic_value",
            "source_dynamic_name": name,
        },
        status_id=str(detail.get("status_id") or ""),
        status_instance_id=str(detail.get("instance_id") or ""),
    )


def _single_entry_source(
    *,
    source_type: str,
    entry_key: str,
    hash_key: str,
    name: str | None,
    owner_id: str,
    value: float,
    source_trace: dict[str, JSONValue],
    status_id: str = "",
    status_instance_id: str = "",
) -> dict[str, JSONValue]:
    entry = {
        "scope": source_type,
        "owner_id": owner_id,
        "status_id": status_id,
        "status_instance_id": status_instance_id,
        "name": name,
        "hash": hash_key,
        "value": value,
        "source_trace": source_trace,
    }
    return {
        "source_type": source_type,
        "entries": {entry_key: entry},
        "by_hash": {hash_key: [entry_key]},
        "by_name": {name: [entry_key]} if name else {},
    }


def _postfix_dynamic_hashes(expression: dict[str, JSONValue]) -> list[JSONValue]:
    raw = expression.get("raw")
    if not isinstance(raw, dict):
        return []
    postfix = raw.get("PostfixExpr")
    if not isinstance(postfix, dict):
        return []
    hashes = postfix.get("DynamicHashes")
    return list(hashes) if isinstance(hashes, list) else []


def _break_base_source_from_evaluation(evaluation: NumericEvaluationResult) -> dict[str, JSONValue]:
    bindings = evaluation.bindings
    operands = bindings.get("dynamic_operands") if isinstance(bindings, dict) else None
    if not isinstance(operands, list):
        return {}
    for operand in operands:
        if not isinstance(operand, dict):
            continue
        binding = operand.get("bindings")
        if not isinstance(binding, dict):
            continue
        entry = binding.get("entry")
        if not isinstance(entry, dict) or entry.get("name") != "CasterBreakBaseDamage":
            continue
        source_trace = entry.get("source_trace")
        if isinstance(source_trace, dict):
            break_base = source_trace.get("break_base_damage")
            return break_base if isinstance(break_base, dict) else source_trace
    return {}


def _break_template_id_from_detail(detail: dict[str, JSONValue]) -> str:
    source = _json_dict(detail.get("source_trace"))
    effect_source = source.get("effect_source")
    evidence = effect_source.get("evidence") if isinstance(effect_source, dict) else None
    emission_id = evidence.get("break_status_emission_id") if isinstance(evidence, dict) else None
    if not isinstance(emission_id, str) or not emission_id:
        return ""
    parts = emission_id.split(":")
    if len(parts) < 3:
        return ""
    template_name = parts[1]
    return f"break_template:{template_name}"


def _break_element_from_detail(detail: dict[str, JSONValue]) -> str | None:
    source = _json_dict(detail.get("source_trace"))
    effect_source = source.get("effect_source")
    evidence = effect_source.get("evidence") if isinstance(effect_source, dict) else None
    emission_id = evidence.get("break_status_emission_id") if isinstance(evidence, dict) else None
    if not isinstance(emission_id, str) or not emission_id:
        return None
    parts = emission_id.split(":")
    if len(parts) < 3:
        return None
    template = parts[1]
    return template.removeprefix("StanceBreak_") or None


def _resolve_callback_target_id(detail: dict[str, JSONValue], target_alias: str | None) -> str:
    alias = target_alias or "ModifierOwnerEntity"
    if alias == "ModifierOwnerEntity":
        return str(detail.get("owner_id") or "")
    if alias == "Caster":
        return str(detail.get("caster_id") or "")
    if alias in {"ParamEntity", "CurrentActionTarget"}:
        return str(detail.get("owner_id") or "")
    return ""


def _resolve_queue_alias(detail: dict[str, JSONValue], event: GameEvent | None, target_alias: str | None) -> str:
    alias = target_alias or ""
    payload = event.payload if event is not None else {}
    if alias == "ModifierOwnerEntity":
        return str(detail.get("owner_id") or "")
    if alias == "Caster":
        return str(detail.get("caster_id") or "")
    if alias in {"ParamEntity", "CurrentActionTarget", "AbilityTargetEntity"}:
        for key in ("current_hit_target_id", "target_id", "primary_action_target_id"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        return str(event.target_id or "") if event is not None else str(detail.get("owner_id") or "")
    if alias == "DamageAttackerEntity":
        for key in ("attacker_id", "actor_id"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        return str(event.source_id or "") if event is not None else ""
    return ""


def _queue_intent_blocked_record(
    callback: StatusCallbackIR,
    task: StatusCallbackTaskIR,
    detail: dict[str, JSONValue],
    intent: QueueIntentIR,
    reason: str,
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="queue_intent_blocked",
        source="status_callback_system",
        process_only=True,
        payload={
            "reason": reason,
            "callback_id": callback.callback_id,
            "task_id": task.task_id,
            "queue_intent_id": intent.queue_intent_id,
            "modifier_name": callback.modifier_name,
            "event": callback.event,
            "opcode": intent.opcode,
            "queue_kind": intent.queue_kind,
            "blocking_dependency": reason,
        },
        trace={
            "queue_intent_source": intent.source.to_json(),
            "status_callback_source": callback.source.to_json(),
            "status_task_source": task.source.to_json(),
            "status_instance_source": _json_dict(detail.get("source_trace")),
        },
    ).to_json()


def _action_delay_blocked_record(
    callback: StatusCallbackIR,
    task: StatusCallbackTaskIR,
    detail: dict[str, JSONValue],
    emission: ActionDelayEmissionIR,
    reason: str,
    *,
    evaluation: NumericEvaluationResult | None = None,
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="action_delay_blocked",
        source="status_callback_system",
        process_only=True,
        payload={
            "reason": reason,
            "callback_id": callback.callback_id,
            "task_id": task.task_id,
            "action_delay_emission_id": emission.action_delay_emission_id,
            "modifier_name": callback.modifier_name,
            "event": callback.event,
            "opcode": emission.opcode,
            "target_alias": emission.target_alias or "",
            "numeric_evaluation": evaluation.to_json() if evaluation else {},
            "blocking_dependency": reason,
        },
        trace={
            "action_delay_source": emission.source.to_json(),
            "status_callback_source": callback.source.to_json(),
            "status_task_source": task.source.to_json(),
            "status_instance_source": _json_dict(detail.get("source_trace")),
        },
    ).to_json()


def _status_damage_blocked_record(
    callback: StatusCallbackIR,
    task: StatusCallbackTaskIR,
    detail: dict[str, JSONValue],
    emission: StatusDamageEmissionIR,
    reason: str,
    *,
    evaluation: NumericEvaluationResult | None = None,
    evaluation_payload: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="dot_damage_blocked" if emission.damage_formula_family == "dot" else "break_dot_tick_blocked",
        source="status_callback_system",
        process_only=True,
        payload={
            "reason": reason,
            "callback_id": callback.callback_id,
            "task_id": task.task_id,
            "status_damage_emission_id": emission.status_damage_emission_id,
            "modifier_name": callback.modifier_name,
            "event": callback.event,
            "attack_type": emission.attack_type,
            "damage_formula_family": emission.damage_formula_family,
            "numeric_evaluation": evaluation_payload or (evaluation.to_json() if evaluation else {}),
            "blocking_dependency": reason,
        },
        trace={
            "status_damage_source": emission.source.to_json(),
            "status_callback_source": callback.source.to_json(),
            "status_instance_source": _json_dict(detail.get("source_trace")),
        },
    ).to_json()


def _callback_blocked_record(
    *,
    reason: str,
    modifier_name: str = "",
    event: str = "",
    trace: dict[str, JSONValue] | None = None,
    callback: StatusCallbackIR | None = None,
    detail: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="status_callback_blocked",
        source="status_callback_system",
        process_only=True,
        payload={
            "reason": reason,
            "callback_id": callback.callback_id if callback else "",
            "modifier_name": callback.modifier_name if callback else modifier_name,
            "event": callback.event if callback else event,
            "blocking_dependency": reason,
        },
        trace={
            "status_callback_source": callback.source.to_json() if callback else {},
            "status_instance_source": _json_dict(detail.get("source_trace")) if detail else (trace or {}),
        },
    ).to_json()


def _task_blocked_record(
    callback: StatusCallbackIR,
    task: StatusCallbackTaskIR,
    detail: dict[str, JSONValue],
    reason: str,
    *,
    ok: bool = False,
    condition_result: dict[str, JSONValue] | None = None,
    selected_child_ids: tuple[str, ...] = (),
    mutation_count: int = 0,
    record_count: int = 0,
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="status_callback_task_blocked",
        source="status_callback_system",
        process_only=True,
        payload={
            "reason": reason,
            "ok": ok,
            "callback_id": callback.callback_id,
            "task_id": task.task_id,
            "opcode": task.opcode,
            "modifier_name": callback.modifier_name,
            "event": callback.event,
            "condition_id": task.condition_id,
            "condition_result": condition_result or {},
            "selected_child_ids": list(selected_child_ids),
            "mutation_count": mutation_count,
            "record_count": record_count,
            "blocking_dependency": reason,
        },
        trace={
            "status_task_source": task.source.to_json(),
            "status_callback_source": callback.source.to_json(),
            "status_instance_source": _json_dict(detail.get("source_trace")),
        },
    ).to_json()


def _condition_context(
    state: BattleState,
    detail: dict[str, JSONValue],
    event: GameEvent | None,
) -> EvaluationContext:
    payload = event.payload if event is not None and isinstance(event.payload, dict) else {}
    owner_id = str(detail.get("owner_id") or "")
    caster_id = str(detail.get("caster_id") or owner_id)
    target_id = _first_payload_str(payload, ("current_hit_target_id", "primary_target_id", "target_id")) or (
        str(event.target_id or "") if event is not None else ""
    )
    param_entity_id = _first_payload_str(payload, ("param_entity_id",)) or target_id or owner_id
    unit_ids = tuple(unit_id for unit_id in (owner_id, caster_id, param_entity_id) if unit_id)
    return EvaluationContext(
        state=state,
        actor_id=caster_id,
        target_id=target_id or None,
        owner_id=owner_id,
        param_entity_id=param_entity_id or None,
        current_action_target_id=target_id or None,
        status_detail=detail,
        event_payload=dict(payload),
        binding_sources=(
            *status_binding_sources(state, unit_ids),
            binding_source_from_store(store_from_state(state)),
        ),
    )


def _effect_context(
    state: BattleState,
    task: StatusCallbackTaskIR,
    detail: dict[str, JSONValue],
    event: GameEvent | None,
    damage_window_ledger: DamageWindowLedger | None = None,
) -> EffectExecutionContext:
    payload = event.payload if event is not None and isinstance(event.payload, dict) else {}
    owner_id = str(detail.get("owner_id") or "")
    caster_id = str(detail.get("caster_id") or owner_id)
    target_id = _first_payload_str(payload, ("current_hit_target_id", "primary_target_id", "target_id")) or (
        str(event.target_id or "") if event is not None else ""
    )
    param_entity_id = _first_payload_str(payload, ("param_entity_id",)) or target_id or owner_id
    unit_ids = tuple(unit_id for unit_id in (owner_id, caster_id, param_entity_id) if unit_id)
    return EffectExecutionContext(
        state=state,
        caster_id=caster_id,
        source_id=f"status_callback_task:{task.task_id}",
        owner_id=owner_id,
        param_entity_id=param_entity_id or None,
        current_action_target_id=target_id or None,
        binding_sources=(
            *status_binding_sources(state, unit_ids),
            binding_source_from_store(store_from_state(state)),
        ),
        damage_window_ledger=damage_window_ledger,
    )


def _first_payload_str(payload: dict[str, JSONValue], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _list_alias_targets(
    state: BattleState,
    detail: dict[str, JSONValue],
    event: GameEvent | None,
    alias: str,
) -> tuple[str, ...]:
    payload = event.payload if event is not None and isinstance(event.payload, dict) else {}
    if alias == "ParamEntitySkillTargetEntityList":
        for key in ("selected_target_ids", "target_ids", "skill_target_ids", "requested_target_ids"):
            value = payload.get(key)
            if isinstance(value, (list, tuple)):
                result = tuple(str(item) for item in value if isinstance(item, str) and item in state.units)
                if result:
                    return result
        fallback = _first_payload_str(payload, ("current_hit_target_id", "primary_target_id", "target_id"))
        return (fallback,) if fallback and fallback in state.units else ()
    if alias == "AllEnemyWithUnSelectable":
        owner_id = str(detail.get("owner_id") or detail.get("caster_id") or "")
        owner = state.units.get(owner_id)
        if owner is None:
            return ()
        return tuple(
            unit_id
            for unit_id, unit in state.units.items()
            if unit.side != owner.side
        )
    return ()


def _value_field(value: object) -> object:
    if isinstance(value, dict) and "Value" in value:
        return value.get("Value")
    return value


def _damage_property_value(payload: dict[str, JSONValue], property_name: str) -> float | None:
    candidates: tuple[object, ...]
    if property_name == "Result_FinalDamageBase":
        candidates = (
            payload.get("final_damage"),
            payload.get("amount"),
            (payload.get("formula_result") if isinstance(payload.get("formula_result"), dict) else {}).get("final_damage"),
        )
    elif property_name == "Result_FinalDamage":
        candidates = (
            payload.get("final_damage"),
            payload.get("amount"),
        )
    else:
        candidates = ()
    for value in candidates:
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _dynamic_hash_aliases_for_damage_property_task(
    task: StatusCallbackTaskIR,
    tasks: dict[str, StatusCallbackTaskIR],
) -> tuple[dict[str, JSONValue], ...]:
    if not task.parent_task_id:
        return ()
    parent = tasks.get(task.parent_task_id)
    if parent is None:
        return ()
    sibling_ids = _parent_child_sequence(parent, task.task_id)
    if not sibling_ids:
        return ()
    try:
        task_index = sibling_ids.index(task.task_id)
    except ValueError:
        return ()
    for sibling_id in sibling_ids[task_index + 1 :]:
        sibling = tasks.get(sibling_id)
        if sibling is None or sibling.opcode != "SetDynamicValue":
            continue
        payload = sibling.source.evidence.get("task") if isinstance(sibling.source.evidence, dict) else None
        if not isinstance(payload, dict):
            continue
        hashes = _numeric_dynamic_hashes(payload.get("Value"))
        if not hashes:
            continue
        return (
            {
                "hash": str(hashes[0]),
                "source_kind": "same_predicate_branch_following_set_dynamic_value",
                "source_task_id": sibling.task_id,
                "source_task_opcode": sibling.opcode,
                "raw_path": "Value.PostfixExpr.DynamicHashes[0]",
            },
        )
    return ()


def _parent_child_sequence(parent: StatusCallbackTaskIR, task_id: str) -> tuple[str, ...]:
    for candidate in (parent.success_task_ids, parent.failed_task_ids, parent.child_task_ids):
        if task_id in candidate:
            return tuple(candidate)
    return ()


def _numeric_dynamic_hashes(value: object) -> tuple[int, ...]:
    if not isinstance(value, dict):
        return ()
    postfix = value.get("PostfixExpr")
    if not isinstance(postfix, dict):
        return ()
    hashes = postfix.get("DynamicHashes")
    if not isinstance(hashes, list):
        return ()
    return tuple(item for item in hashes if isinstance(item, int))


def _trigger_ids_for_event(detail: dict[str, JSONValue], event: str) -> tuple[str, ...] | None:
    mapping = detail.get("trigger_ids_by_event")
    if not isinstance(mapping, dict):
        return None
    value = mapping.get(event)
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str) and item)


def _json_dict(value: object) -> dict[str, JSONValue]:
    return value if isinstance(value, dict) else {}


def _json_float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None
