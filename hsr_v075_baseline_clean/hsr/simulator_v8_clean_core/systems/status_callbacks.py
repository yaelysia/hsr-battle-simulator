from __future__ import annotations

from dataclasses import dataclass, replace

from ..core.model import BattleState, GameEvent, JSONValue, Mutation, RNGEvent
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..core.transition_outcome import ExecutionNodeResult
from ..rules.evaluator import (
    ConditionEvaluationResult,
    EvaluationContext,
    NumericEvaluationContext,
    NumericEvaluationResult,
    RuleEvaluator,
    _condition_target_key,
)
from ..rules.engine_rule_registry import EngineRuleRegistry, engine_numeric_binding_source
from ..rules.expression_ir import numeric_dynamic_hashes, numeric_fixed, numeric_missing
from ..rules.ir import ActionDelayEmissionIR, ConditionIR, QueueIntentIR, StatusCallbackIR, StatusCallbackTaskIR, StatusDamageEmissionIR, TargetExpressionNodeIR
from ..rules.rulebook import RuleBook
from ..rules.value_binding import ValueBindingRequest, ValueContext, ValueResolver
from ..unit_eligibility import (
    runtime_unit_is_active,
    runtime_unit_is_dark_team,
    runtime_unit_is_light_team,
    runtime_unit_is_target_candidate,
    runtime_units_are_opposing_combat_teams,
    runtime_units_share_combat_team,
)
from .damage import DamagePacket, DamageSourceFrame, DamageSystem, DamageWindowLedger
from .dot_formula import DotFormula, DotFormulaInput
from .dynamic_values import (
    binding_source_from_status_detail,
    binding_source_from_store,
    find_status_detail,
    status_binding_sources,
    store_from_state,
    upsert_dynamic_value,
)
from .effect import (
    EffectExecutionContext,
    EffectRegistry,
    PreHealDispatchResult,
)
from .mutation_events import events_for_mutation
from .queue import QueueEntry, QueueSystem, QueueTargetResolver
from .rng import (
    RNGOutcome,
    RNGRequest,
    choice_key_for_identity,
    event_id_for_identity,
    resolve_rng_request,
    rng_choices_from_payload,
    rng_mode_from_payload,
)
from .status import StatusSystem
from .target import TargetSystem
from .timeline import TimelineSystem
from .unit_lifecycle import UnitLifecycleSystem
from .unit_stats import effective_unit_stat


@dataclass(frozen=True)
class StatusCallbackExecutionResult:
    ok: bool
    after_state: BattleState
    mutations: tuple[Mutation, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    events: tuple[GameEvent, ...] = ()
    errors: tuple[str, ...] = ()
    node_results: tuple[ExecutionNodeResult, ...] = ()


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
        self.damage = damage or DamageSystem(rules)
        self.reducer = reducer or MutationReducer()
        self.timeline = timeline or TimelineSystem()
        self.queue = queue or QueueSystem()
        self.queue_targets = QueueTargetResolver()
        self.targets = TargetSystem()
        self.effect_registry = effect_registry or EffectRegistry(StatusSystem(rules))
        self.effect_registry.set_pre_heal_dispatcher(self._dispatch_pre_heal)
        self.evaluator = RuleEvaluator()
        self.value_resolver = ValueResolver(rules)

    def execute(
        self,
        state: BattleState,
        *,
        unit_id: str,
        modifier_name: str,
        event: str,
        trigger_event: GameEvent | None = None,
        damage_window_ledger: DamageWindowLedger | None = None,
        detail_override: dict[str, JSONValue] | None = None,
    ) -> StatusCallbackExecutionResult:
        result = self._execute(
            state,
            unit_id=unit_id,
            modifier_name=modifier_name,
            event=event,
            trigger_event=trigger_event,
            damage_window_ledger=damage_window_ledger,
            detail_override=detail_override,
        )
        if result.node_results:
            return result
        reason = ",".join(result.errors)
        return replace(
            result,
            node_results=(
                ExecutionNodeResult(
                    node_kind="status_callback",
                    node_id=f"{unit_id}:{modifier_name}:{event}",
                    status="complete" if result.ok else "blocked",
                    reason_code=reason or ("" if result.ok else "status_callback_incomplete"),
                ),
            ),
        )

    def _execute(
        self,
        state: BattleState,
        *,
        unit_id: str,
        modifier_name: str,
        event: str,
        trigger_event: GameEvent | None = None,
        damage_window_ledger: DamageWindowLedger | None = None,
        detail_override: dict[str, JSONValue] | None = None,
    ) -> StatusCallbackExecutionResult:
        detail = detail_override
        if detail is not None and (
            str(detail.get("owner_id") or "") != unit_id
            or str(detail.get("modifier_name") or "") != modifier_name
            or not str(detail.get("instance_id") or "")
        ):
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(
                    _callback_blocked_record(
                        modifier_name=modifier_name,
                        event=event,
                        reason="status_detail_override_identity_mismatch",
                        trace={},
                    ),
                ),
                errors=("status_detail_override_identity_mismatch",),
            )
        if detail is None:
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
        callbacks = tuple(sorted(callbacks, key=lambda callback: callback.execution_order))
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
        rng_events: list[RNGEvent] = []
        errors: list[str] = []
        events: list[GameEvent] = []
        for callback in callbacks:
            result = self._execute_callback(current_state, callback, detail, trigger_event, damage_window_ledger)
            current_state = result.after_state
            mutations.extend(result.mutations)
            rng_events.extend(result.rng_events)
            records.extend(result.records)
            events.extend(result.events)
            errors.extend(result.errors)
        if errors:
            reason = f"status_callback_group_atomic_rollback:{errors[0]}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(
                    _callback_blocked_record(
                        modifier_name=modifier_name,
                        event=event,
                        reason=reason,
                        trace=_json_dict(detail.get("source_trace")),
                    ),
                ),
                errors=tuple(errors),
                node_results=(
                    ExecutionNodeResult(
                        node_kind="status_callback_group",
                        node_id=f"{unit_id}:{modifier_name}:{event}",
                        status="blocked",
                        reason_code="status_callback_group_atomic_precheck_failed",
                    ),
                ),
            )
        return StatusCallbackExecutionResult(
            ok=not errors,
            after_state=current_state,
            mutations=tuple(mutations),
            rng_events=tuple(rng_events),
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
        rng_events: list[RNGEvent] = []
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
            rng_events.extend(result.rng_events)
            records.extend(result.records)
            events.extend(result.events)
            errors.extend(result.errors)
        if errors:
            reason = f"status_callback_atomic_rollback:{errors[0]}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(
                    _callback_blocked_record(
                        callback=callback,
                        detail=detail,
                        reason=reason,
                    ),
                ),
                errors=tuple(errors),
                node_results=(
                    ExecutionNodeResult(
                        node_kind="status_callback",
                        node_id=callback.callback_id,
                        status="blocked",
                        reason_code="status_callback_atomic_precheck_failed",
                    ),
                ),
            )
        return StatusCallbackExecutionResult(
            ok=True,
            after_state=current_state,
            mutations=tuple(mutations),
            rng_events=tuple(rng_events),
            records=tuple(records),
            events=tuple(events),
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
        if task.blocked_reason == "equipment_task_family_non_gameplay":
            return StatusCallbackExecutionResult(
                ok=True,
                after_state=state,
                records=(
                    _task_blocked_record(
                        callback,
                        task,
                        detail,
                        "",
                        ok=True,
                        mutation_count=0,
                        record_count=1,
                    ),
                ),
            )
        if task.opcode == "PredicateTaskList":
            return self._execute_predicate_task(state, callback, task, detail, trigger_event, tasks, damage_window_ledger)
        if task.opcode == "Retarget":
            return self._execute_retarget_task(state, callback, task, detail, trigger_event, tasks, damage_window_ledger)
        if task.opcode in {"IncludeTaskListTemplate", "LoopExecuteTaskList", "RandomConfig"}:
            return self._execute_container_task(
                state,
                callback,
                task,
                detail,
                trigger_event,
                tasks,
                damage_window_ledger,
            )
        if task.opcode == "ModifyCurrentSkillDelayCost":
            return self._execute_current_skill_delay_cost_task(
                state,
                callback,
                task,
                detail,
                trigger_event,
            )
        if task.opcode == "Remodifier":
            return self._execute_remodifier_query_task(
                state,
                callback,
                task,
                detail,
                trigger_event,
                tasks,
                damage_window_ledger,
            )
        if task.opcode == "SetResilience":
            return self._execute_shield_resilience_sync_task(
                state,
                callback,
                task,
                detail,
            )
        structured_dynamic_value_opcodes = {
            "StackProperty",
            "SetDynamicValueByCharacterCount",
            "SetDynamicValueByCopying",
            "SetDynamicValueByCountOfBaseType",
            "SetDynamicValueByHPRatio",
            "SetDynamicValueByProperty",
            "SetDynamicValueByStatusCount",
            "SetDynamicValueByWeaknessCount",
            "SetDynamicValue",
            "SetModifierDynamicValue",
            "SetDynamicValueByAttackTargetCount",
            "SetDynamicValueByBPChange",
            "SetDynamicValueByDamageDataProperty",
            "SetDynamicValueByHealDataProperty",
            "SetDynamicValueByMaxBP",
            "SetDynamicValueByVariateType",
        }
        if task.opcode in structured_dynamic_value_opcodes and task.coverage_status != "executable":
            reason = task.blocked_reason or f"status_callback_task_not_executable:{task.coverage_status}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        if task.opcode == "StackProperty":
            return StatusCallbackExecutionResult(
                ok=True,
                after_state=state,
                records=(
                    _task_blocked_record(
                        callback,
                        task,
                        detail,
                        "",
                        ok=True,
                        mutation_count=0,
                        record_count=1,
                    ),
                ),
            )
        if task.opcode in structured_dynamic_value_opcodes:
            return self._execute_context_dynamic_value_task(
                state,
                callback,
                task,
                detail,
                trigger_event,
                tasks,
            )
        if task.opcode == "ModifyHealData":
            return self._execute_modify_heal_data_task(
                state,
                callback,
                task,
                detail,
            )
        if task.opcode == "ModifyDamageData":
            return self._execute_damage_modifier_task(
                state,
                callback,
                task,
                detail,
            )
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
                return self._execute_delay_emissions(state, callback, task, detail, trigger_event, tuple(delay_emissions))
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
                trigger_event,
                tuple(damage_emissions),
                damage_window_ledger,
            )
        if delay_emissions:
            return self._execute_delay_emissions(state, callback, task, detail, trigger_event, tuple(delay_emissions))
        if queue_intents:
            return self._execute_queue_intents(state, callback, task, detail, trigger_event, tuple(queue_intents))
        if task.effect_id:
            return self._execute_effect_task(state, callback, task, detail, trigger_event, damage_window_ledger)
        reason = "status_callback_task_has_no_executable_runtime_effect"
        return StatusCallbackExecutionResult(
            ok=False,
            after_state=state,
            records=(_task_blocked_record(callback, task, detail, reason),),
            errors=(reason,),
        )

    def _execute_container_task(
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
            reason = task.blocked_reason or f"container_task_not_executable:{task.coverage_status}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        if not task.child_task_ids:
            reason = f"container_child_task_missing:{task.opcode}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        if task.opcode == "IncludeTaskListTemplate":
            return self._execute_child_sequence(
                state,
                callback,
                task,
                detail,
                trigger_event,
                tasks,
                damage_window_ledger,
                task.child_task_ids,
                container_metadata={
                    "container_opcode": task.opcode,
                    "template_name": task.task_payload.get("template_name"),
                },
            )
        if task.opcode == "LoopExecuteTaskList":
            evaluation = _evaluate_callback_numeric(
                task.task_payload.get("MaxLoopCount"),
                state,
                detail,
                task,
                self.rules.engine_rule_registry(),
            )
            if not evaluation.ok or evaluation.value is None:
                reason = evaluation.blocked_reason or "loop_count_not_resolved"
                return StatusCallbackExecutionResult(
                    ok=False,
                    after_state=state,
                    records=(_task_blocked_record(callback, task, detail, reason),),
                    errors=(reason,),
                )
            loop_count = int(evaluation.value)
            if float(loop_count) != float(evaluation.value) or loop_count < 0:
                reason = "loop_count_must_be_non_negative_integer"
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
            rng_events: list[RNGEvent] = []
            for loop_index in range(loop_count):
                scoped_event = _callback_scoped_event(
                    trigger_event,
                    callback_scope=f"{task.task_id}:loop",
                    decision_index=loop_index,
                )
                result = self._execute_child_sequence(
                    current_state,
                    callback,
                    task,
                    detail,
                    scoped_event,
                    tasks,
                    damage_window_ledger,
                    task.child_task_ids,
                    container_metadata={
                        "container_opcode": task.opcode,
                        "loop_index": loop_index,
                        "loop_count": loop_count,
                    },
                )
                if not result.ok:
                    reason = result.errors[0] if result.errors else "loop_child_failed"
                    return StatusCallbackExecutionResult(
                        ok=False,
                        after_state=state,
                        records=(_task_blocked_record(callback, task, detail, f"loop_atomic_rollback:{reason}"),),
                        errors=(reason,),
                    )
                current_state = result.after_state
                mutations.extend(result.mutations)
                records.extend(result.records)
                events.extend(result.events)
                rng_events.extend(result.rng_events)
            return StatusCallbackExecutionResult(
                ok=True,
                after_state=current_state,
                mutations=tuple(mutations),
                records=tuple(records),
                events=tuple(events),
                rng_events=tuple(rng_events),
            )
        return self._execute_random_config_task(
            state,
            callback,
            task,
            detail,
            trigger_event,
            tasks,
            damage_window_ledger,
        )

    def _execute_random_config_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        tasks: dict[str, StatusCallbackTaskIR],
        damage_window_ledger: DamageWindowLedger | None,
    ) -> StatusCallbackExecutionResult:
        raw_weights = task.task_payload.get("OddsList")
        if not isinstance(raw_weights, list) or len(raw_weights) != len(task.child_task_ids):
            reason = "random_config_weight_child_count_mismatch"
            return StatusCallbackExecutionResult(False, state, records=(_task_blocked_record(callback, task, detail, reason),), errors=(reason,))
        weights: list[float] = []
        for expression in raw_weights:
            evaluation = _evaluate_callback_numeric(
                expression,
                state,
                detail,
                task,
                self.rules.engine_rule_registry(),
            )
            if not evaluation.ok or evaluation.value is None or evaluation.value < 0:
                reason = evaluation.blocked_reason or "random_config_weight_not_resolved"
                return StatusCallbackExecutionResult(False, state, records=(_task_blocked_record(callback, task, detail, reason),), errors=(reason,))
            weights.append(float(evaluation.value))
        if sum(weights) <= 0:
            reason = "random_config_weights_empty"
            return StatusCallbackExecutionResult(False, state, records=(_task_blocked_record(callback, task, detail, reason),), errors=(reason,))
        event_payload = trigger_event.payload if trigger_event is not None and isinstance(trigger_event.payload, dict) else {}
        decision_index = event_payload.get("callback_decision_index", 0)
        if type(decision_index) is not int or decision_index < 0:
            decision_index = 0
        identity: dict[str, JSONValue] = {
            "decision_scope": f"status_callback:{callback.callback_id}",
            "decision_index": decision_index,
            "task_id": task.task_id,
            "status_id": str(detail.get("instance_id") or detail.get("status_id") or ""),
            "owner_id": str(detail.get("owner_id") or ""),
            "trigger_event_id": trigger_event.event_id if trigger_event is not None else "",
        }
        choice_key = choice_key_for_identity("status_callback_random_config", identity)
        request = RNGRequest(
            rng_type="status_callback_random_config",
            purpose="select exactly one RandomConfig child",
            event_id=event_id_for_identity(
                "status_callback_random_config",
                identity,
                event_index=state.event_index,
            ),
            choice_key=choice_key,
            source=task.task_id,
            before_state=state.rng_state,
            decision_kind="weighted",
            outcomes=tuple(
                RNGOutcome(
                    outcome_id=f"branch:{index}",
                    payload={"child_task_id": child_id, "branch_index": index},
                    weight=weight,
                )
                for index, (child_id, weight) in enumerate(zip(task.child_task_ids, weights, strict=True))
            ),
            source_trace={
                "callback_source": callback.source.to_json(),
                "task_source": task.source.to_json(),
                "status_source": _json_dict(detail.get("source_trace")),
            },
            identity=identity,
        )
        resolution = resolve_rng_request(
            request,
            rng_choices=rng_choices_from_payload(event_payload),
            rng_mode=rng_mode_from_payload(event_payload),
        )
        if not resolution.ok or resolution.selected_outcome is None:
            reason = resolution.blocked_reason or "random_config_choice_unresolved"
            return StatusCallbackExecutionResult(False, state, records=(_task_blocked_record(callback, task, detail, reason),), errors=(reason,))
        child_id = resolution.selected_outcome.payload.get("child_task_id")
        if not isinstance(child_id, str) or child_id not in tasks:
            reason = "random_config_selected_child_missing"
            return StatusCallbackExecutionResult(False, state, records=(_task_blocked_record(callback, task, detail, reason),), errors=(reason,))
        result = self._execute_child_sequence(
            state,
            callback,
            task,
            detail,
            trigger_event,
            tasks,
            damage_window_ledger,
            (child_id,),
            container_metadata={
                "container_opcode": task.opcode,
                "choice_key": choice_key,
                "selected_child_id": child_id,
            },
        )
        if not result.ok:
            return result
        return replace(
            result,
            rng_events=(
                *((resolution.event,) if resolution.event is not None else ()),
                *result.rng_events,
            ),
        )

    def _execute_child_sequence(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        parent_task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        tasks: dict[str, StatusCallbackTaskIR],
        damage_window_ledger: DamageWindowLedger | None,
        child_ids: tuple[str, ...],
        *,
        container_metadata: dict[str, JSONValue],
    ) -> StatusCallbackExecutionResult:
        current_state = state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = [
            _task_blocked_record(
                callback,
                parent_task,
                detail,
                "",
                ok=True,
                selected_child_ids=child_ids,
            )
        ]
        payload = records[0].get("payload")
        if isinstance(payload, dict):
            payload["container"] = container_metadata
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        for child_id in child_ids:
            child = tasks.get(child_id)
            if child is None:
                reason = f"missing_child_task:{child_id}"
                return StatusCallbackExecutionResult(False, state, records=(_task_blocked_record(callback, parent_task, detail, reason),), errors=(reason,))
            result = self._execute_task(
                current_state,
                callback,
                child,
                detail,
                trigger_event,
                tasks,
                damage_window_ledger,
            )
            if not result.ok:
                reason = result.errors[0] if result.errors else "container_child_failed"
                return StatusCallbackExecutionResult(False, state, records=(_task_blocked_record(callback, parent_task, detail, f"container_atomic_rollback:{reason}"),), errors=(reason,))
            current_state = result.after_state
            mutations.extend(result.mutations)
            records.extend(result.records)
            events.extend(result.events)
            rng_events.extend(result.rng_events)
        return StatusCallbackExecutionResult(
            True,
            current_state,
            mutations=tuple(mutations),
            records=tuple(records),
            events=tuple(events),
            rng_events=tuple(rng_events),
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
        result, condition_rng_events, evaluated_event = self._evaluate_callback_condition(
            condition,
            state,
            callback,
            task,
            detail,
            trigger_event,
        )
        if not result.ok or result.result is None:
            reason = f"blocked_condition:{condition.condition_id}:{result.reason}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                rng_events=condition_rng_events,
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
        rng_events: list[RNGEvent] = list(condition_rng_events)
        errors: list[str] = []
        precheck_result = self._precheck_selected_queue_group(
            state,
            callback,
            task,
            detail,
            evaluated_event,
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
                evaluated_event,
                tasks,
                damage_window_ledger,
            )
            current_state = child_result.after_state
            mutations.extend(child_result.mutations)
            rng_events.extend(child_result.rng_events)
            records.extend(child_result.records)
            events.extend(child_result.events)
            errors.extend(child_result.errors)
        if errors:
            reason = f"predicate_child_atomic_rollback:{errors[0]}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(
                    _task_blocked_record(
                        callback,
                        task,
                        detail,
                        reason,
                        condition_result=result.to_json(),
                        selected_child_ids=selected_child_ids,
                    ),
                ),
                errors=tuple(errors),
            )
        return StatusCallbackExecutionResult(
            ok=True,
            after_state=current_state,
            mutations=tuple(mutations),
            rng_events=tuple(rng_events),
            records=tuple(records),
            events=tuple(events),
        )

    def _evaluate_callback_condition(
        self,
        condition,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
    ) -> tuple[ConditionEvaluationResult, tuple[RNGEvent, ...], GameEvent | None]:
        chance_nodes = _condition_random_chance_nodes(condition)
        if not chance_nodes:
            return (
                self.evaluator.evaluate_condition_result(
                    condition,
                    _condition_context(
                        state,
                        detail,
                        trigger_event,
                        condition=condition,
                        targets=self.targets,
                    ),
                ),
                (),
                trigger_event,
            )
        if len(chance_nodes) != 1:
            blocked = ConditionEvaluationResult(
                ok=False,
                result=None,
                condition_id=condition.condition_id,
                opcode=condition.opcode,
                reason="multiple_random_condition_nodes_require_distinct_identity",
                details={"node_paths": [path for path, _ in chance_nodes]},
                source_trace=condition.source.to_json(),
            )
            return blocked, (), trigger_event
        node_path, chance_expr = chance_nodes[0]
        evaluation = _evaluate_callback_numeric(
            chance_expr,
            state,
            detail,
            task,
            self.rules.engine_rule_registry(),
        )
        if not evaluation.ok or evaluation.value is None or not 0.0 <= evaluation.value <= 1.0:
            blocked = ConditionEvaluationResult(
                ok=False,
                result=None,
                condition_id=condition.condition_id,
                opcode=condition.opcode,
                reason=evaluation.blocked_reason or "random_condition_chance_out_of_range",
                details={"node_path": node_path, "numeric_evaluation": evaluation.to_json()},
                source_trace=condition.source.to_json(),
            )
            return blocked, (), trigger_event
        payload = trigger_event.payload if trigger_event is not None and isinstance(trigger_event.payload, dict) else {}
        decision_index = payload.get("callback_decision_index", 0)
        if type(decision_index) is not int or decision_index < 0:
            decision_index = 0
        identity: dict[str, JSONValue] = {
            "decision_scope": f"status_condition:{callback.callback_id}",
            "decision_index": decision_index,
            "task_id": task.task_id,
            "status_id": str(detail.get("instance_id") or detail.get("status_id") or ""),
            "condition_id": condition.condition_id,
            "condition_node_path": node_path,
            "owner_id": str(detail.get("owner_id") or ""),
        }
        choice_key = choice_key_for_identity("status_condition_chance", identity)
        request = RNGRequest(
            rng_type="status_condition_chance",
            purpose="resolve ByRandomChance",
            event_id=event_id_for_identity(
                "status_condition_chance",
                identity,
                event_index=state.event_index,
            ),
            choice_key=choice_key,
            source=condition.condition_id,
            before_state=state.rng_state,
            decision_kind="probability",
            outcomes=(
                RNGOutcome(
                    outcome_id="pass",
                    payload={"condition_result": True},
                    probability=float(evaluation.value),
                ),
                RNGOutcome(
                    outcome_id="fail",
                    payload={"condition_result": False},
                    probability=1.0 - float(evaluation.value),
                ),
            ),
            source_trace={
                "condition_source": condition.source.to_json(),
                "task_source": task.source.to_json(),
                "status_source": _json_dict(detail.get("source_trace")),
            },
            identity=identity,
        )
        resolution = resolve_rng_request(
            request,
            rng_choices=rng_choices_from_payload(payload),
            rng_mode=rng_mode_from_payload(payload),
        )
        if not resolution.ok or resolution.selected_outcome is None:
            blocked = ConditionEvaluationResult(
                ok=False,
                result=None,
                condition_id=condition.condition_id,
                opcode=condition.opcode,
                reason=resolution.blocked_reason or "random_condition_choice_unresolved",
                details=resolution.blocked_payload(),
                source_trace=condition.source.to_json(),
            )
            return blocked, (), trigger_event
        selected = resolution.selected_outcome.payload.get("condition_result")
        if not isinstance(selected, bool):
            blocked = ConditionEvaluationResult(
                ok=False,
                result=None,
                condition_id=condition.condition_id,
                opcode=condition.opcode,
                reason="random_condition_outcome_invalid",
                details={"selected_outcome": resolution.selected_outcome.to_json()},
                source_trace=condition.source.to_json(),
            )
            return blocked, (), trigger_event
        evaluated_event = _condition_rng_event(
            trigger_event,
            selected=selected,
            choice_key=choice_key,
        )
        result = self.evaluator.evaluate_condition_result(
            condition,
            _condition_context(
                state,
                detail,
                evaluated_event,
                condition=condition,
                targets=self.targets,
            ),
        )
        return (
            result,
            ((resolution.event,) if resolution.event is not None else ()),
            evaluated_event,
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
        target_expression_id, target_link_reason = _callback_task_target_expression_id(
            self.rules,
            task,
        )
        if target_link_reason:
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(
                    _status_damage_blocked_record(
                        callback,
                        task,
                        detail,
                        emission,
                        target_link_reason,
                    ),
                ),
                errors=(target_link_reason,),
            )
        expression = (
            self.rules.target_expression(target_expression_id)
            if target_expression_id
            else None
        )
        if target_expression_id and expression is None:
            reason = f"additional_damage_target_expression_missing:{target_expression_id}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(
                    _status_damage_blocked_record(
                        callback,
                        task,
                        detail,
                        emission,
                        reason,
                    ),
                ),
                errors=(reason,),
            )
        if expression is None:
            reason = "missing_retarget_target_expression"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        event_payload = (
            dict(trigger_event.payload)
            if trigger_event is not None and isinstance(trigger_event.payload, dict)
            else {}
        )
        event_payload.update(
            {
                "status_instance_id": str(detail.get("instance_id") or ""),
                "status_id": str(detail.get("status_id") or ""),
                "modifier_name": callback.modifier_name,
            }
        )
        caster_id = str(detail.get("caster_id") or detail.get("owner_id") or "")
        owner_id = str(detail.get("owner_id") or caster_id)
        param_entity_id = _resolve_callback_target_id(
            state,
            detail,
            "ParamEntity",
            trigger_event,
        )
        resolution = self.targets.resolve_target_expression(
            state,
            expression,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id or None,
            current_action_target_id=param_entity_id or None,
            event_payload=event_payload,
            binding_sources=tuple(
                status_binding_sources(
                    state,
                    tuple(unit_id for unit_id in (owner_id, caster_id) if unit_id),
                )
            ),
        )
        if not resolution.ok:
            reason = resolution.blocked_reason or "retarget_resolution_failed"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                rng_events=resolution.rng_events,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        if not resolution.target_ids:
            record = _task_blocked_record(
                callback,
                task,
                detail,
                "",
                ok=True,
                selected_child_ids=(),
            )
            payload = record.get("payload")
            if isinstance(payload, dict):
                payload["target_expression_resolution"] = resolution.to_json()
            return StatusCallbackExecutionResult(
                ok=True,
                after_state=state,
                rng_events=resolution.rng_events,
                records=(record,),
            )
        current_state = state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = list(resolution.rng_events)
        for target_index, candidate_id in enumerate(resolution.target_ids):
            retarget_event = _callback_scoped_event(
                _retarget_event(trigger_event, candidate_id),
                callback_scope=f"{task.task_id}:retarget",
                decision_index=target_index,
            )
            child_result = self._execute_child_sequence(
                current_state,
                callback,
                task,
                detail,
                retarget_event,
                tasks,
                damage_window_ledger,
                task.child_task_ids,
                container_metadata={
                    "container_opcode": task.opcode,
                    "retarget_target_id": candidate_id,
                    "retarget_target_index": target_index,
                    "target_expression_id": task.target_expression_id,
                },
            )
            if not child_result.ok:
                reason = child_result.errors[0] if child_result.errors else "retarget_child_failed"
                return StatusCallbackExecutionResult(
                    ok=False,
                    after_state=state,
                    rng_events=tuple(rng_events),
                    records=(_task_blocked_record(callback, task, detail, f"retarget_atomic_rollback:{reason}"),),
                    errors=(reason,),
                )
            current_state = child_result.after_state
            mutations.extend(child_result.mutations)
            rng_events.extend(child_result.rng_events)
            records.extend(child_result.records)
            events.extend(child_result.events)
        summary = _task_blocked_record(
            callback,
            task,
            detail,
            "",
            ok=True,
            selected_child_ids=task.child_task_ids,
        )
        summary_payload = summary.get("payload")
        if isinstance(summary_payload, dict):
            summary_payload["target_expression_resolution"] = resolution.to_json()
        records.insert(0, summary)
        return StatusCallbackExecutionResult(
            ok=True,
            after_state=current_state,
            mutations=tuple(mutations),
            rng_events=tuple(rng_events),
            records=tuple(records),
            events=tuple(events),
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
                rng_events=result.rng_events,
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
            rng_events=result.rng_events,
            records=records,
            events=result.events,
            errors=result.unsupported,
        )

    def _execute_context_dynamic_value_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        tasks: dict[str, StatusCallbackTaskIR],
    ) -> StatusCallbackExecutionResult:
        if task.coverage_status != "executable":
            reason = task.blocked_reason or "context_dynamic_value_task_not_executable"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        payload = task.task_payload
        dynamic_key = payload.get("DynamicKey") or payload.get("ToDynamicKey")
        if not isinstance(dynamic_key, str) or not dynamic_key:
            reason = "dynamic_value_name_required"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        value, value_source, blocked_reason = _context_dynamic_value(
            state,
            task,
            detail,
            trigger_event,
            self.rules.engine_rule_registry(),
        )
        if value is None:
            reason = blocked_reason or "context_dynamic_value_unresolved"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        explicit_target_alias = (
            payload.get("ToTargetType")
            or payload.get("WriteTargetType")
        )
        target_alias = str(explicit_target_alias or "ModifierOwnerEntity")
        target_id = _resolve_callback_target_id(
            state, detail, target_alias, trigger_event
        )
        if not target_id and explicit_target_alias is None:
            target_id = str(detail.get("owner_id") or "")
        if target_id not in state.units:
            reason = f"context_dynamic_value_target_missing:{target_alias}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        stored_before = state.global_flags.get("dynamic_value_store")
        before = store_from_state(state)
        source_trace = {
            "status_callback_source": callback.source.to_json(),
            "status_task_source": task.source.to_json(),
            "status_instance_source": _json_dict(detail.get("source_trace")),
            "trigger_event": (
                trigger_event.to_json() if trigger_event is not None else {}
            ),
        }
        aliases = _dynamic_hash_aliases_for_context_task(
            detail,
            task=task,
            tasks=tasks,
        )
        after = before
        if aliases:
            for alias in aliases:
                after = upsert_dynamic_value(
                    after,
                    scope="status_callback",
                    owner_id=target_id,
                    value=float(value),
                    value_name=dynamic_key,
                    hash_key=alias.get("hash"),
                    status_id=str(detail.get("status_id") or ""),
                    status_instance_id=str(detail.get("instance_id") or ""),
                    effect_id=task.task_id,
                    source_trace={**source_trace, "dynamic_hash_alias": alias},
                )
        else:
            after = upsert_dynamic_value(
                after,
                scope="status_callback",
                owner_id=target_id,
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
            before=stored_before,
            after=after,
            reason="set context-derived dynamic value",
            source="status_callback_system",
            before_exists="dynamic_value_store" in state.global_flags,
            metadata={
                "callback_id": callback.callback_id,
                "task_id": task.task_id,
                "modifier_name": callback.modifier_name,
                "dynamic_key": dynamic_key,
                "dynamic_hash_aliases": aliases,
                "value": float(value),
                "value_source": value_source,
                "source_trace": source_trace,
            },
        )
        status_mutation = _callback_status_dynamic_value_mutation(
            state,
            target_id=target_id,
            detail=detail,
            callback_id=callback.callback_id,
            dynamic_key=dynamic_key,
            value=float(value),
            aliases=aliases,
            task=task,
            source_trace=source_trace,
        )
        mutations = (
            (status_mutation, mutation)
            if status_mutation is not None
            else (mutation,)
        )
        after_state = self.reducer.apply_all(state, mutations)
        record = SettlementRecord(
            record_type="status_callback_dynamic_value",
            source="status_callback_system",
            mutation_id=mutation.stable_id(),
            process_only=False,
            payload={
                "callback_id": callback.callback_id,
                "task_id": task.task_id,
                "modifier_name": callback.modifier_name,
                "dynamic_key": dynamic_key,
                "dynamic_hash_aliases": aliases,
                "target_id": target_id,
                "value": float(value),
                "value_source": value_source,
            },
            trace=source_trace,
        ).to_json()
        records: tuple[dict[str, JSONValue], ...] = (record,)
        if status_mutation is not None:
            records = (
                SettlementRecord(
                    record_type="status_dynamic_value",
                    source="status_callback_system",
                    mutation_id=status_mutation.stable_id(),
                    process_only=False,
                    payload={
                        "callback_id": callback.callback_id,
                        "task_id": task.task_id,
                        "modifier_name": callback.modifier_name,
                        "dynamic_key": dynamic_key,
                        "dynamic_hash_aliases": aliases,
                        "target_id": target_id,
                        "value": float(value),
                    },
                    trace=source_trace,
                ).to_json(),
                record,
            )
        return StatusCallbackExecutionResult(
            ok=True,
            after_state=after_state,
            mutations=mutations,
            records=records,
        )

    def _execute_current_skill_delay_cost_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
    ) -> StatusCallbackExecutionResult:
        if task.coverage_status != "executable":
            reason = task.blocked_reason or "current_skill_delay_cost_not_executable"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        owner_id = str(detail.get("owner_id") or "")
        event_payload = (
            trigger_event.payload
            if trigger_event is not None and isinstance(trigger_event.payload, dict)
            else {}
        )
        actor_id = _first_payload_str(
            event_payload,
            ("actor_id", "attacker_id", "damage_attacker_id"),
        ) or (str(trigger_event.source_id or "") if trigger_event is not None else "")
        turn_owner_id = str(state.global_flags.get("turn_owner_id") or "")
        if not owner_id or actor_id != owner_id or turn_owner_id != owner_id:
            reason = "current_skill_delay_cost_actor_not_active_owner"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        evaluation = _evaluate_callback_numeric(
            task.task_payload.get("NormalizedValue"),
            state,
            detail,
            task,
            self.rules.engine_rule_registry(),
        )
        if not evaluation.ok or evaluation.value is None:
            reason = evaluation.blocked_reason or "current_skill_delay_cost_value_unresolved"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        registry_key = "turn_action_delay_cost_modifiers"
        raw_before = state.global_flags.get(registry_key)
        if raw_before is not None and not isinstance(raw_before, dict):
            reason = "turn_action_delay_cost_registry_invalid"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        before = dict(raw_before) if isinstance(raw_before, dict) else {}
        identity = ":".join(
            (
                owner_id,
                str(detail.get("instance_id") or ""),
                task.task_id,
                str(trigger_event.event_id or "") if trigger_event is not None else "",
            )
        )
        if identity in before:
            reason = "turn_action_delay_cost_duplicate_identity"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        source_trace = {
            "status_callback_source": callback.source.to_json(),
            "status_task_source": task.source.to_json(),
            "status_instance_source": _json_dict(detail.get("source_trace")),
            "trigger_event": trigger_event.to_json() if trigger_event is not None else {},
        }
        after = {
            **before,
            identity: {
                "actor_id": actor_id,
                "normalized_value": float(evaluation.value),
                "callback_id": callback.callback_id,
                "task_id": task.task_id,
                "status_instance_id": str(detail.get("instance_id") or ""),
                "source_trace": source_trace,
            },
        }
        mutation = Mutation(
            op="set",
            path=("global_flags", registry_key),
            before=raw_before,
            after=after,
            reason="register current skill normalized action delay cost",
            source="status_callback_system",
            before_exists=registry_key in state.global_flags,
            metadata={
                "task_id": task.task_id,
                "callback_id": callback.callback_id,
                "actor_id": actor_id,
                "identity": identity,
                "normalized_value": float(evaluation.value),
                "numeric_evaluation": evaluation.to_json(),
                "source_trace": source_trace,
            },
        )
        after_state = self.reducer.apply_all(state, (mutation,))
        record = SettlementRecord(
            record_type="turn_action_delay_cost_registered",
            source="status_callback_system",
            mutation_id=mutation.stable_id(),
            process_only=False,
            payload={
                "task_id": task.task_id,
                "callback_id": callback.callback_id,
                "actor_id": actor_id,
                "identity": identity,
                "normalized_value": float(evaluation.value),
                "numeric_evaluation": evaluation.to_json(),
            },
            trace=source_trace,
        ).to_json()
        return StatusCallbackExecutionResult(
            ok=True,
            after_state=after_state,
            mutations=(mutation,),
            records=(record,),
        )

    def _execute_remodifier_query_task(
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
            reason = task.blocked_reason or "remodifier_query_not_executable"
            return StatusCallbackExecutionResult(
                False,
                state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        payload = task.task_payload
        target_alias = str(payload.get("TargetType") or "")
        caster_alias = str(payload.get("CasterFilter") or "")
        target_id = _resolve_callback_target_id(
            state, detail, target_alias, trigger_event
        )
        caster_id = _resolve_callback_target_id(
            state, detail, caster_alias, trigger_event
        )
        if target_id not in state.units or caster_id not in state.units:
            reason = "remodifier_query_context_unresolved"
            return StatusCallbackExecutionResult(
                False,
                state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        flags = payload.get("BehaviorFlagFilter")
        if not isinstance(flags, list) or not flags or not all(
            isinstance(flag, str) and flag for flag in flags
        ):
            reason = "remodifier_behavior_flag_filter_missing"
            return StatusCallbackExecutionResult(
                False,
                state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        maximum = _evaluate_callback_numeric(
            payload.get("MaxNumber"),
            state,
            detail,
            task,
            self.rules.engine_rule_registry(),
        )
        if (
            not maximum.ok
            or maximum.value is None
            or maximum.value < 0
            or not float(maximum.value).is_integer()
        ):
            reason = maximum.blocked_reason or "remodifier_max_number_invalid"
            return StatusCallbackExecutionResult(
                False,
                state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        raw_details = state.units[target_id].flags.get("status_details", ())
        if not isinstance(raw_details, (list, tuple)):
            reason = "remodifier_status_details_invalid"
            return StatusCallbackExecutionResult(
                False,
                state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        required_flags = set(flags)
        matches = tuple(
            sorted(
                (
                    item
                    for item in raw_details
                    if isinstance(item, dict)
                    and item.get("caster_id") == caster_id
                    and required_flags.issubset(
                        {
                            str(flag)
                            for flag in item.get("behavior_flags", ())
                            if isinstance(flag, str)
                        }
                    )
                ),
                key=lambda item: str(item.get("instance_id") or ""),
            )[: int(maximum.value)]
        )
        selected_child_ids = task.success_task_ids if matches else task.failed_task_ids
        return self._execute_child_sequence(
            state,
            callback,
            task,
            detail,
            trigger_event,
            tasks,
            damage_window_ledger,
            selected_child_ids,
            container_metadata={
                "container_opcode": task.opcode,
                "target_id": target_id,
                "caster_id": caster_id,
                "behavior_flags": sorted(required_flags),
                "matched_status_instance_ids": [
                    str(item.get("instance_id") or "") for item in matches
                ],
                "branch": "success" if matches else "failed",
            },
        )

    def _execute_shield_resilience_sync_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
    ) -> StatusCallbackExecutionResult:
        if task.coverage_status != "executable":
            reason = task.blocked_reason or "shield_resilience_sync_not_executable"
            return StatusCallbackExecutionResult(
                False,
                state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        owner_id = str(detail.get("owner_id") or "")
        modifier_name = str(detail.get("modifier_name") or callback.modifier_name)
        status_instance_id = str(detail.get("instance_id") or "")
        unit = state.units.get(owner_id)
        if unit is None or not modifier_name or not status_instance_id:
            reason = "shield_resilience_status_identity_missing"
            return StatusCallbackExecutionResult(
                False,
                state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        matching = tuple(
            sorted(
                (
                    item
                    for item in unit.shield_instances
                    if isinstance(item, dict)
                    and item.get("owner_modifier_name") == modifier_name
                    and item.get("status_instance_id") == status_instance_id
                ),
                key=lambda item: str(item.get("instance_id") or ""),
            )
        )
        reset_requested = task.task_payload.get("DoReset") is True
        if (reset_requested and matching) or (
            not reset_requested and not matching
        ):
            reason = (
                "shield_resilience_removed_instance_still_present"
                if reset_requested
                else "shield_resilience_expected_instance_missing"
            )
            return StatusCallbackExecutionResult(
                False,
                state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        source_trace = {
            "status_callback_source": callback.source.to_json(),
            "status_task_source": task.source.to_json(),
            "status_instance_source": _json_dict(detail.get("source_trace")),
        }
        record = SettlementRecord(
            record_type="shield_resilience_synchronized",
            source="status_callback_system",
            process_only=True,
            payload={
                "owner_id": owner_id,
                "modifier_name": modifier_name,
                "status_instance_id": status_instance_id,
                "task_id": task.task_id,
                "opcode": task.opcode,
                "reset_requested": reset_requested,
                "matching_shield_instance_ids": [
                    str(item.get("instance_id") or "") for item in matching
                ],
                "authoritative_state": "shield_instances",
            },
            trace=source_trace,
        ).to_json()
        return StatusCallbackExecutionResult(
            True,
            state,
            records=(record,),
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
        # Status application and dispel already consume the canonical target
        # expression as a complete group.  Re-routing them through the
        # per-target adapter would replace the payload alias with ParamEntity
        # while retaining the original expression identity, producing a
        # contradictory source pair (for example
        # ParamEntity:DamageDefenderEntity).
        if effect.opcode in {
            "AddModifier",
            "RemoveModifier",
            "RemoveSelfModifier",
            "DispelStatus",
        }:
            return None
        alias = standard.get("target_alias")
        if alias in {
            "Caster",
            "CurrentActionTarget",
            "LevelEntity",
            "ModifierOwnerEntity",
            "ParamEntity",
        }:
            return None
        target_expression_id = standard.get("target_expression_id")
        if alias is None and not (
            isinstance(target_expression_id, str) and target_expression_id
        ):
            # Global effects such as team-resource changes intentionally have
            # no target.  They must reach their typed effect executor instead
            # of being mistaken for an unresolved list target.
            return None
        expression = (
            self.rules.target_expression(str(target_expression_id))
            if isinstance(target_expression_id, str) and target_expression_id
            else None
        )
        target_rng_events: tuple[RNGEvent, ...] = ()
        target_resolution_payload: dict[str, JSONValue] = {}
        empty_group_admitted = False
        if expression is not None:
            context = _effect_context(
                state,
                task,
                detail,
                trigger_event,
                damage_window_ledger,
            )
            resolution = self.targets.resolve_target_expression(
                state,
                expression,
                caster_id=context.caster_id,
                owner_id=context.owner_id,
                param_entity_id=context.param_entity_id,
                current_action_target_id=context.current_action_target_id,
                target_resolution=context.target_resolution,
                event_payload=context.event_payload,
                dynamic_values=context.dynamic_values,
                binding_sources=context.binding_sources,
            )
            target_rng_events = resolution.rng_events
            target_resolution_payload = resolution.to_json()
            if not resolution.ok:
                reason = resolution.blocked_reason or "target_expression_resolution_failed"
                if (
                    str(alias)
                    in {
                        "AllDarkTeam",
                        "AllEnemy",
                        "AllEnemyWithUnSelectable",
                        "AllLightTeam",
                        "AllTeamMember",
                        "AllTeamMemberWithUnselectable",
                        "AllTeammate",
                    }
                    and reason == f"target group empty:{alias}"
                ):
                    target_ids = ()
                    empty_group_admitted = True
                    target_resolution_payload["empty_group_admission"] = (
                        "source_resolved_no_effect"
                    )
                else:
                    return StatusCallbackExecutionResult(
                        ok=False,
                        after_state=state,
                        rng_events=target_rng_events,
                        records=(_task_blocked_record(callback, task, detail, reason),),
                        errors=(reason,),
                    )
            else:
                target_ids = resolution.target_ids
        else:
            target_ids = _list_alias_targets(state, detail, trigger_event, str(alias))
        if not target_ids:
            if empty_group_admitted:
                record = _task_blocked_record(
                    callback,
                    task,
                    detail,
                    "source_resolved_empty_group_no_effect",
                    ok=True,
                )
                payload = record.get("payload")
                if isinstance(payload, dict):
                    payload["target_alias"] = str(alias)
                    payload["resolved_target_ids"] = []
                    payload["state_unchanged"] = True
                    payload["target_expression_resolution"] = (
                        target_resolution_payload
                    )
                return StatusCallbackExecutionResult(
                    ok=True,
                    after_state=state,
                    rng_events=target_rng_events,
                    records=(record,),
                )
            reason = f"list_target_alias_unresolved:{alias}"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                rng_events=target_rng_events,
                errors=(reason,),
            )
        current_state = state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = list(target_rng_events)
        errors: list[str] = []
        for target_id in target_ids:
            patched_standard = {**standard, "target_alias": "ParamEntity"}
            patched_effect = replace(effect, payload={**effect.payload, "standard": patched_standard})
            context = _effect_context(current_state, task, detail, trigger_event, damage_window_ledger)
            context = replace(context, param_entity_id=target_id, current_action_target_id=target_id)
            result = self.effect_registry.execute(patched_effect, context)
            if result.unsupported:
                errors.extend(result.unsupported)
                reason = ",".join(errors)
                blocked = _task_blocked_record(callback, task, detail, reason)
                payload = blocked.get("payload")
                if isinstance(payload, dict):
                    payload["target_alias"] = str(alias)
                    payload["resolved_target_ids"] = list(target_ids)
                    payload["failed_target_id"] = target_id
                    payload["target_expression_resolution"] = target_resolution_payload
                return StatusCallbackExecutionResult(
                    ok=False,
                    after_state=state,
                    rng_events=tuple((*rng_events, *result.rng_events)),
                    records=(blocked,),
                    errors=tuple(errors),
                )
            current_state = self.reducer.apply_all(current_state, result.mutations)
            mutations.extend(result.mutations)
            records.extend(result.records)
            events.extend(result.events)
            rng_events.extend(result.rng_events)
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
            payload["target_expression_resolution"] = target_resolution_payload
        records.append(summary)
        return StatusCallbackExecutionResult(
            ok=not errors,
            after_state=current_state,
            mutations=tuple(mutations),
            rng_events=tuple(rng_events),
            records=tuple(records),
            events=tuple(events),
            errors=tuple(errors),
        )

    def _execute_modify_heal_data_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
    ) -> StatusCallbackExecutionResult:
        if task.coverage_status != "executable":
            reason = task.blocked_reason or "modify_heal_data_not_executable"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        evaluation = _evaluate_callback_numeric(
            task.task_payload.get("Healer_HealRatio"),
            state,
            detail,
            task,
            self.rules.engine_rule_registry(),
        )
        if not evaluation.ok or evaluation.value is None:
            reason = (
                evaluation.blocked_reason
                or "healer_heal_ratio_evaluation_failed"
            )
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )
        record = SettlementRecord(
            record_type="heal_modifier",
            source="status_callback_system",
            process_only=True,
            payload={
                "callback_id": callback.callback_id,
                "task_id": task.task_id,
                "modifier_name": callback.modifier_name,
                "heal_ratio": float(evaluation.value),
                "numeric_evaluation": evaluation.to_json(),
            },
            trace={
                "status_callback_source": callback.source.to_json(),
                "status_task_source": task.source.to_json(),
                "status_instance_source": _json_dict(detail.get("source_trace")),
            },
        ).to_json()
        return StatusCallbackExecutionResult(
            ok=True,
            after_state=state,
            records=(record,),
        )

    def _execute_damage_modifier_task(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
    ) -> StatusCallbackExecutionResult:
        """Admit the task only through its exact DamageModifierIR consumer.

        ``ModifyDamageData`` does not mutate BattleState.  The direct-damage
        formula collects its lowered terms later in the same damage window.
        Treating it as a generic EffectIR loses that contract and used to
        fail with ``status_callback_effect_missing`` despite a valid lowered
        modifier.  This record is process-only; it cannot apply a second copy
        of the modifier terms.
        """

        modifiers = tuple(
            modifier
            for modifier in self.rules.damage_modifiers_for_callback(
                callback.callback_id
            )
            if modifier.source_task_id == task.task_id
        )
        reason = ""
        if task.coverage_status != "executable":
            reason = task.blocked_reason or "modify_damage_data_not_executable"
        elif len(modifiers) != 1:
            reason = f"damage_modifier_count:{len(modifiers)}"
        else:
            modifier = modifiers[0]
            if modifier.coverage_status != "executable":
                reason = (
                    modifier.blocked_reason
                    or "damage_modifier_not_executable"
                )
            elif (
                modifier.callback_id != callback.callback_id
                or modifier.modifier_name != callback.modifier_name
                or modifier.event != callback.event
            ):
                reason = "damage_modifier_callback_identity_mismatch"
            elif modifier.source.to_json() != task.source.to_json():
                reason = "damage_modifier_source_identity_mismatch"
            elif not modifier.modifier_terms:
                reason = "damage_modifier_terms_missing"
            elif any(
                term.get("coverage_status") != "executable"
                for term in modifier.modifier_terms
            ):
                reason = "damage_modifier_term_not_executable"
        if reason:
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(_task_blocked_record(callback, task, detail, reason),),
                errors=(reason,),
            )

        modifier = modifiers[0]
        record = SettlementRecord(
            record_type="damage_modifier_task",
            source="status_callback_system",
            process_only=True,
            payload={
                "ok": True,
                "callback_id": callback.callback_id,
                "task_id": task.task_id,
                "modifier_name": callback.modifier_name,
                "damage_modifier_id": modifier.damage_modifier_id,
                "consumer": "direct_damage_modifier_ledger",
                "term_count": len(modifier.modifier_terms),
            },
            trace={
                "status_callback_source": callback.source.to_json(),
                "status_task_source": task.source.to_json(),
                "damage_modifier_source": modifier.source.to_json(),
                "status_instance_source": _json_dict(
                    detail.get("source_trace")
                ),
            },
        ).to_json()
        return StatusCallbackExecutionResult(
            ok=True,
            after_state=state,
            records=(record,),
        )

    def _dispatch_pre_heal(
        self,
        effect,
        context: EffectExecutionContext,
    ) -> PreHealDispatchResult:
        standard = (
            effect.payload.get("standard")
            if isinstance(effect.payload, dict)
            else None
        )
        if not isinstance(standard, dict):
            return PreHealDispatchResult(
                ok=False,
                after_state=context.state,
                errors=("pre_heal_standard_payload_missing",),
            )
        alias = str(standard.get("target_alias") or "")
        target_id = {
            "Caster": context.caster_id,
            "ModifierOwnerEntity": context.owner_id,
            "ParamEntity": context.param_entity_id,
            "CurrentActionTarget": context.current_action_target_id,
        }.get(alias)
        if not isinstance(target_id, str) or target_id not in context.state.units:
            return PreHealDispatchResult(
                ok=False,
                after_state=context.state,
                errors=(f"pre_heal_target_not_resolved:{alias or 'missing'}",),
            )
        actor = context.state.units.get(context.caster_id)
        if actor is None:
            return PreHealDispatchResult(
                ok=False,
                after_state=context.state,
                errors=("pre_heal_actor_missing",),
            )
        parent_payload = {
            key: value
            for key, value in (context.event_payload or {}).items()
            if key
            not in {
                "callback_event",
                "callback_events",
                "listener_scope",
                "tbgd_event",
            }
        }
        trigger_event = GameEvent(
            event_type="heal.before",
            source_id=context.caster_id,
            target_id=target_id,
            event_id=(
                f"{str((context.event_payload or {}).get('event_id') or f'event:{context.state.event_index}')}:"
                f"heal_before:{effect.effect_id}:{target_id}"
            ),
            window="OnBeforeDealHeal",
            process_only=True,
            payload={
                **parent_payload,
                "actor_id": context.caster_id,
                "source_id": context.source_id,
                "target_id": target_id,
                "param_entity_id": target_id,
                "current_action_target_id": target_id,
                "callback_events": ["OnBeforeDealHeal"],
                "listener_scope": "actor_local",
            },
        )
        details = actor.flags.get("status_details", ())
        if not isinstance(details, (list, tuple)):
            details = ()
        current_state = context.state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = []
        events: list[GameEvent] = [trigger_event]
        rng_events: list[RNGEvent] = []
        heal_ratio = 0.0
        for detail in sorted(
            (item for item in details if isinstance(item, dict)),
            key=lambda item: (
                str(item.get("modifier_name") or ""),
                str(item.get("instance_id") or ""),
            ),
        ):
            modifier_name = str(detail.get("modifier_name") or "")
            if not self.rules.status_callbacks_for_modifier_event(
                modifier_name,
                "OnBeforeDealHeal",
            ):
                continue
            result = self.execute(
                current_state,
                unit_id=actor.unit_id,
                modifier_name=modifier_name,
                event="OnBeforeDealHeal",
                trigger_event=trigger_event,
            )
            if not result.ok:
                return PreHealDispatchResult(
                    ok=False,
                    after_state=context.state,
                    rng_events=tuple((*rng_events, *result.rng_events)),
                    records=result.records,
                    errors=result.errors or ("pre_heal_callback_failed",),
                )
            current_state = result.after_state
            mutations.extend(result.mutations)
            records.extend(result.records)
            events.extend(result.events)
            rng_events.extend(result.rng_events)
            for record in result.records:
                if record.get("record_type") != "heal_modifier":
                    continue
                payload = record.get("payload")
                value = payload.get("heal_ratio") if isinstance(payload, dict) else None
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    heal_ratio += float(value)
        return PreHealDispatchResult(
            ok=True,
            after_state=current_state,
            heal_ratio=heal_ratio,
            events=tuple(events),
            mutations=tuple(mutations),
            rng_events=tuple(rng_events),
            records=tuple(records),
        )

    def _execute_damage_emissions(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
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
            if emission.damage_formula_family == "additional":
                result = self._execute_additional_damage_emission(
                    current_state,
                    callback,
                    task,
                    detail,
                    trigger_event,
                    emission,
                    damage_window_ledger,
                )
                current_state = result.after_state
                mutations.extend(result.mutations)
                records.extend(result.records)
                events.extend(result.events)
                errors.extend(result.errors)
                continue
            if emission.damage_formula_family == "dot":
                result = self._execute_dot_damage_emission(
                    current_state,
                    callback,
                    task,
                    detail,
                    trigger_event,
                    emission,
                    damage_window_ledger,
                )
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
                    amount_stage="fixed_final",
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
                amount_stage="family_base",
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

    def _execute_additional_damage_emission(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        trigger_event: GameEvent | None,
        emission: StatusDamageEmissionIR,
        damage_window_ledger: DamageWindowLedger | None,
    ) -> StatusCallbackExecutionResult:
        caster_id = str(detail.get("caster_id") or detail.get("owner_id") or "")
        actor = state.units.get(caster_id)
        if actor is None:
            reason = "status_damage_actor_missing"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(
                    _status_damage_blocked_record(
                        callback,
                        task,
                        detail,
                        emission,
                        reason,
                    ),
                ),
                errors=(reason,),
            )
        expression = (
            self.rules.target_expression(task.target_expression_id)
            if task.target_expression_id
            else None
        )
        if expression is not None:
            context = _effect_context(
                state,
                task,
                detail,
                trigger_event,
                damage_window_ledger,
            )
            resolution = self.targets.resolve_target_expression(
                state,
                expression,
                caster_id=context.caster_id,
                owner_id=context.owner_id,
                param_entity_id=context.param_entity_id,
                current_action_target_id=context.current_action_target_id,
                target_resolution=context.target_resolution,
                event_payload=context.event_payload,
                dynamic_values=context.dynamic_values,
                binding_sources=context.binding_sources,
            )
            if not resolution.ok or not resolution.target_ids:
                reason = (
                    resolution.blocked_reason
                    or "additional_damage_target_resolution_failed"
                )
                return StatusCallbackExecutionResult(
                    ok=False,
                    after_state=state,
                    rng_events=resolution.rng_events,
                    records=(
                        _status_damage_blocked_record(
                            callback,
                            task,
                            detail,
                            emission,
                            reason,
                        ),
                    ),
                    errors=(reason,),
                )
            target_ids = resolution.target_ids
            rng_events = list(resolution.rng_events)
        else:
            alias = str(task.task_payload.get("TargetType") or "")
            target_id = _resolve_callback_target_id(
                state, detail, alias, trigger_event
            )
            target_ids = (target_id,) if target_id else ()
            rng_events = []
        if not target_ids:
            reason = "additional_damage_target_missing"
            return StatusCallbackExecutionResult(
                ok=False,
                after_state=state,
                records=(
                    _status_damage_blocked_record(
                        callback,
                        task,
                        detail,
                        emission,
                        reason,
                    ),
                ),
                errors=(reason,),
            )

        current_state = state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = []
        events: list[GameEvent] = []
        for target_id in target_ids:
            if target_id not in current_state.units:
                reason = f"additional_damage_target_missing:{target_id}"
                return StatusCallbackExecutionResult(
                    ok=False,
                    after_state=state,
                    rng_events=tuple(rng_events),
                    records=(
                        _status_damage_blocked_record(
                            callback,
                            task,
                            detail,
                            emission,
                            reason,
                        ),
                    ),
                    errors=(reason,),
                )
            evaluation = self._evaluate_status_damage_amount(
                current_state,
                detail,
                emission,
                target_id=target_id,
            )
            if not evaluation.ok or evaluation.value is None:
                reason = (
                    evaluation.blocked_reason
                    or "additional_damage_numeric_evaluation_failed"
                )
                return StatusCallbackExecutionResult(
                    ok=False,
                    after_state=state,
                    rng_events=tuple(rng_events),
                    records=(
                        _status_damage_blocked_record(
                            callback,
                            task,
                            detail,
                            emission,
                            reason,
                            evaluation=evaluation,
                        ),
                    ),
                    errors=(reason,),
                )
            trace = {
                "status_damage_source": emission.source.to_json(),
                "status_callback_source": callback.source.to_json(),
                "status_task_source": task.source.to_json(),
                "status_instance_source": _json_dict(detail.get("source_trace")),
            }
            source_id = f"status_damage:{emission.status_damage_emission_id}"
            sequence_id = (
                f"status_damage:{str(detail.get('instance_id') or '')}:"
                f"{emission.status_damage_emission_id}"
            )
            packet = DamagePacket(
                attacker_id=caster_id,
                target_id=target_id,
                attack_type=emission.attack_type,
                damage_formula_family="additional",
                amount=float(evaluation.value),
                amount_stage="family_base",
                element_type=(
                    emission.element_type
                    or str(actor.flags.get("damage_type") or "")
                    or None
                ),
                status_damage_emission_id=emission.status_damage_emission_id,
                status_callback_id=callback.callback_id,
                status_instance_id=str(detail.get("instance_id") or ""),
                modifier_name=callback.modifier_name,
                source_task_id=task.task_id,
                source_frame=DamageSourceFrame(
                    owner_id=caster_id,
                    source_id=source_id,
                    source_kind="status_additional_damage",
                    sequence_id=sequence_id,
                    target_id=target_id,
                    can_continue_after_lethal=False,
                    source_trace=trace,
                ),
                source_trace=trace,
                metadata={
                    "damage_formula_family": "additional",
                    "record_type": "additional_damage",
                    "status_damage_emission_id": emission.status_damage_emission_id,
                    "status_callback_id": callback.callback_id,
                    "status_instance_id": str(detail.get("instance_id") or ""),
                    "modifier_name": callback.modifier_name,
                    "source_task_id": task.task_id,
                    "damage_source_owner_id": caster_id,
                    "damage_source_id": source_id,
                    "damage_source_kind": "status_additional_damage",
                    "damage_sequence_id": sequence_id,
                    "can_continue_after_lethal": False,
                    "numeric_evaluation": evaluation.to_json(),
                    "source_trace": trace,
                },
            )
            damage_result = self.damage.apply_packet(
                current_state,
                packet,
                window_ledger=damage_window_ledger,
            )
            if not damage_result.ok:
                reason = (
                    damage_result.errors[0]
                    if damage_result.errors
                    else "additional_damage_application_failed"
                )
                return StatusCallbackExecutionResult(
                    ok=False,
                    after_state=state,
                    rng_events=tuple((*rng_events, *damage_result.rng_events)),
                    records=damage_result.records,
                    errors=(reason,),
                )
            current_state = self.reducer.apply_all(
                current_state,
                damage_result.mutations,
            )
            mutations.extend(damage_result.mutations)
            records.extend(damage_result.records)
            events.extend(damage_result.events)
            rng_events.extend(damage_result.rng_events)
        return StatusCallbackExecutionResult(
            ok=True,
            after_state=current_state,
            mutations=tuple(mutations),
            rng_events=tuple(rng_events),
            records=tuple(records),
            events=tuple(events),
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
        payload = task.task_payload
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
        aliases = _dynamic_hash_aliases_for_context_task(
            detail,
            task=task,
            tasks=tasks,
        )
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
            before=store_before if "dynamic_value_store" in state.global_flags else None,
            after=store_after,
            reason="set dynamic value from damage data property",
            source="status_callback_system",
            before_exists="dynamic_value_store" in state.global_flags,
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
        trigger_event: GameEvent | None,
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
                event_payload={
                    **(
                        dict(trigger_event.payload)
                        if trigger_event is not None
                        and isinstance(trigger_event.payload, dict)
                        else {}
                    ),
                    "runtime_event_type": (
                        trigger_event.event_type if trigger_event is not None else ""
                    ),
                    "runtime_event_id": (
                        trigger_event.event_id if trigger_event is not None else ""
                    ),
                },
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
            amount_stage="family_base",
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
        trigger_event: GameEvent | None,
        emissions: tuple[ActionDelayEmissionIR, ...],
    ) -> StatusCallbackExecutionResult:
        current_state = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        records = []
        errors = []
        for emission in emissions:
            if emission.coverage_status != "executable":
                reason = emission.blocked_reason or f"action_delay_not_executable:{emission.coverage_status}"
                records.append(_action_delay_blocked_record(callback, task, detail, emission, reason))
                errors.append(reason)
                continue
            if emission.opcode not in {"SetActionDelay", "ModifyActionDelay"}:
                reason = f"action_delay_opcode_not_admitted:{emission.opcode}"
                records.append(_action_delay_blocked_record(callback, task, detail, emission, reason))
                errors.append(reason)
                continue
            target_alias = str(emission.target_alias or "ModifierOwnerEntity")
            target_ids = _callback_target_group(
                current_state,
                detail,
                trigger_event,
                target_alias,
            )
            group_alias = target_alias in {
                "AllEnemy",
                "AllEnemyWithUnSelectable",
                "AllLightTeam",
                "AllLightTeam.RemoveServant",
                "AllDarkTeam",
                "AllTeamMember",
                "AllTeamMemberWithUnselectable",
                "AllTeammate",
            }
            if not target_ids and not group_alias:
                target_id = _resolve_callback_target_id(
                    current_state,
                    detail,
                    target_alias,
                    trigger_event,
                )
                target_ids = (target_id,) if target_id in current_state.units else ()
            if not target_ids and group_alias:
                records.append(
                    _action_delay_blocked_record(
                        callback,
                        task,
                        detail,
                        emission,
                        "",
                    )
                )
                continue
            if not target_ids:
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
            timeline_rule = None
            if emission.opcode == "ModifyActionDelay":
                timeline_rule, rule_reason = self.rules.select_timeline_rule()
                if timeline_rule is None:
                    reason = rule_reason or "timeline_engine_rule_missing"
                    records.append(_action_delay_blocked_record(callback, task, detail, emission, reason, evaluation=evaluation))
                    errors.append(reason)
                    continue
            for target_id in target_ids:
                operation = "set"
                action_value = float(evaluation.value)
                normalized_value: float | None = None
                if timeline_rule is not None:
                    speed = effective_unit_stat(current_state.units[target_id], "speed")
                    normalized_value = float(evaluation.value)
                    action_value = abs(normalized_value) * self.timeline.full_action_value(
                        speed.value,
                        timeline_rule,
                    )
                    # TBGD ModifyActionDelay stores a signed normalized delta:
                    # negative values advance the unit and positive values
                    # delay it.  TimelineSystem exposes those as explicit
                    # operations instead of an ambiguous signed "add".
                    operation = "advance" if normalized_value < 0.0 else "delay"
                adjustment = self.timeline.adjust_action_value(
                    current_state,
                    target_id,
                    operation=operation,
                    amount=action_value,
                    source="status_callback_system",
                    metadata={
                        "callback_id": callback.callback_id,
                        "task_id": task.task_id,
                        "action_delay_emission_id": emission.action_delay_emission_id,
                        "modifier_name": callback.modifier_name,
                        "event": callback.event,
                        "opcode": emission.opcode,
                        "target_alias": target_alias,
                        "normalized_value": normalized_value,
                        "numeric_evaluation": evaluation.to_json(),
                        "source_trace": {
                            "action_delay_source": emission.source.to_json(),
                            "status_callback_source": callback.source.to_json(),
                            "status_task_source": task.source.to_json(),
                            "status_instance_source": _json_dict(detail.get("source_trace")),
                        },
                    },
                    rule=timeline_rule,
                )
                if not adjustment.plan.ok:
                    reason = adjustment.plan.blocked_reason or "action_delay_timeline_adjustment_blocked"
                    records.extend(adjustment.records)
                    records.append(_action_delay_blocked_record(callback, task, detail, emission, reason, evaluation=evaluation))
                    errors.append(reason)
                    break
                current_state = self.reducer.apply_all(current_state, adjustment.mutations)
                mutations.extend(adjustment.mutations)
                events.extend(adjustment.events)
                records.extend(adjustment.records)
                mutation = adjustment.mutations[0] if adjustment.mutations else None
                if mutation is not None:
                    events.extend(
                        events_for_mutation(
                            mutation,
                            actor_id=str(detail.get("caster_id") or detail.get("owner_id") or ""),
                            source_id=str(detail.get("source_id") or callback.callback_id),
                            event_index=current_state.event_index,
                        )
                    )
                records.append(
                    SettlementRecord(
                        record_type="action_delay",
                        source="status_callback_system",
                        mutation_id=mutation.stable_id() if mutation is not None else None,
                        process_only=mutation is None,
                        payload={
                            "callback_id": callback.callback_id,
                            "task_id": task.task_id,
                            "action_delay_emission_id": emission.action_delay_emission_id,
                            "modifier_name": callback.modifier_name,
                            "event": callback.event,
                            "target_id": target_id,
                            "operation": operation,
                            "action_value": action_value,
                            "normalized_value": normalized_value,
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
            events=tuple(events),
            records=tuple(records),
            errors=tuple(errors),
        )

    def _evaluate_status_damage_amount(
        self,
        state: BattleState,
        detail: dict[str, JSONValue],
        emission: StatusDamageEmissionIR,
        *,
        target_id: str | None = None,
    ) -> NumericEvaluationResult:
        caster_id = str(detail.get("caster_id") or "")
        target_id = target_id or str(detail.get("owner_id") or "")
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
        if emission.damage_formula_family in {"additional", "true_damage"}:
            modifier_owner_id = str(detail.get("owner_id") or "")
            source_unit_ids = tuple(
                dict.fromkeys(
                    unit_id
                    for unit_id in (
                        caster_id,
                        modifier_owner_id,
                        target_id,
                    )
                    if unit_id
                )
            )
            status_sources = status_binding_sources(state, source_unit_ids)
            mirrored_status_instance_ids = tuple(
                str(source.get("status_instance_id") or "")
                for source in status_sources
                if str(source.get("status_instance_id") or "")
            )
            sources = (
                *status_sources,
                binding_source_from_store(
                    store_from_state(state),
                    excluded_status_instance_ids=mirrored_status_instance_ids,
                ),
            )
            expression = emission.scaling_expr
            additional_mode = ""
            if emission.damage_formula_family == "additional":
                percentage = expression.get("damage_percentage")
                value = expression.get("damage_value")
                if isinstance(percentage, dict) and percentage.get("supported") is True:
                    expression = percentage
                    additional_mode = "attack_percentage"
                elif isinstance(value, dict) and value.get("supported") is True:
                    expression = value
                    additional_mode = "fixed_value"
                else:
                    return NumericEvaluationResult(
                        ok=False,
                        value=None,
                        expression_kind="additional_attack_property",
                        bindings={},
                        source_trace=emission.source.to_json(),
                        blocked_reason="additional_damage_numeric_expression_missing",
                    )
            evaluated = RuleEvaluator().evaluate_numeric(
                expression,
                NumericEvaluationContext(
                    binding_sources=sources,
                    source_trace={
                        "status_damage_source": emission.source.to_json(),
                        "status_instance_source": _json_dict(detail.get("source_trace")),
                    },
                ),
            )
            if (
                emission.damage_formula_family != "additional"
                or not evaluated.ok
                or evaluated.value is None
            ):
                return evaluated
            if additional_mode == "attack_percentage":
                attack = effective_unit_stat(actor, "attack")
                amount = attack.value * float(evaluated.value)
                bindings = {
                    **evaluated.bindings,
                    "additional_damage_mode": additional_mode,
                    "attack": attack.to_json(),
                    "ratio": float(evaluated.value),
                }
            else:
                amount = float(evaluated.value)
                bindings = {
                    **evaluated.bindings,
                    "additional_damage_mode": additional_mode,
                }
            return NumericEvaluationResult(
                ok=True,
                value=amount,
                expression_kind="additional_attack_property",
                bindings=bindings,
                source_trace=evaluated.source_trace,
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
            priority_resolution = _queue_priority_value_resolution(
                self.value_resolver,
                intent,
                callback,
                task,
                detail,
            )
            if not priority_resolution.get("ok"):
                reason = (
                    "queue_priority_value_resolution_blocked:"
                    f"{priority_resolution.get('blocked_reason') or 'unknown'}"
                )
                records.append(_queue_intent_blocked_record(callback, task, detail, intent, reason))
                errors.append(reason)
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
                "queue_priority_value_resolution": priority_resolution,
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
                resource_policy=_queue_resource_policy(intent),
                priority_key=str(intent.priority_source.get("priority_key") or ""),
                priority_value=_json_float(priority_resolution.get("value")),
                queue_priority_id=str(intent.priority_source.get("queue_priority_id") or ""),
                priority_source_trace=_json_dict(intent.priority_source.get("source_trace")),
                queue_window_id=window.queue_window_id,
                window_family=window.window_family,
                window_policy=window.window_policy,
                target_resolution=target_resolution.to_json(),
                owner_id=str(detail.get("owner_id") or ""),
                source_id=str(detail.get("source_id") or callback.callback_id),
                expiration_policy={
                    "status": "source_gap_blocked",
                    "blocked_reason": "queue_expiration_policy_source_missing",
                },
                cancel_policy={
                    "actor_removed": "blocked_process_only",
                    "actor_defeated": "blocked_process_only",
                    "target_invalid": "blocked_process_only",
                    "retarget": "source_gap_blocked",
                },
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
                    "priority_value_resolution": priority_resolution,
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
                        "priority_value_resolution": priority_resolution,
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


def _queue_priority_value_resolution(
    value_resolver: ValueResolver,
    intent: QueueIntentIR,
    callback: StatusCallbackIR,
    task: StatusCallbackTaskIR,
    detail: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    source_trace = {
        "queue_intent_source": intent.source.to_json(),
        "queue_priority_source": _json_dict(intent.priority_source.get("source_trace")),
        "status_callback_source": callback.source.to_json(),
        "status_task_source": task.source.to_json(),
        "status_instance_source": _json_dict(detail.get("source_trace")),
    }
    priority_value = intent.priority_source.get("priority_value")
    priority_expression = (
        numeric_fixed(float(priority_value))
        if isinstance(priority_value, (int, float)) and not isinstance(priority_value, bool)
        else numeric_missing("queue_priority_value_not_numeric")
    )
    resolution = value_resolver.resolve(
        ValueBindingRequest(
            binding_kind="runtime_numeric_expression",
            expression=priority_expression,
            required_context_keys=("status_modifier",),
            source_trace=source_trace,
        ),
        ValueContext(
            owner_id=str(detail.get("owner_id") or ""),
            status_id=str(detail.get("status_id") or ""),
            modifier_name=str(detail.get("modifier_name") or callback.modifier_name),
            source_trace=source_trace,
        ),
    )
    return resolution.to_json()


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
    policy = task.retarget_policy
    if not isinstance(policy, dict):
        return ()
    alias = str(policy.get("target_alias") or "")
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
    policy = task.retarget_policy
    expr = policy.get("max_number_expr") if isinstance(policy, dict) else None
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


def _callback_scoped_event(
    event: GameEvent | None,
    *,
    callback_scope: str,
    decision_index: int,
) -> GameEvent:
    payload = dict(event.payload) if event is not None and isinstance(event.payload, dict) else {}
    payload.update(
        {
            "callback_decision_scope": callback_scope,
            "callback_decision_index": decision_index,
        }
    )
    base_id = event.event_id if event is not None else ""
    return GameEvent(
        event.event_type if event is not None else "status.callback.scope",
        source_id=event.source_id if event is not None else "",
        target_id=event.target_id if event is not None else "",
        event_id=(
            f"{base_id}:scope:{callback_scope}:{decision_index}"
            if base_id
            else f"event:scope:{callback_scope}:{decision_index}"
        ),
        window=event.window if event is not None else "status_callback",
        process_only=True,
        payload=payload,
    )


def _condition_rng_event(
    event: GameEvent | None,
    *,
    selected: bool,
    choice_key: str,
) -> GameEvent:
    payload = dict(event.payload) if event is not None and isinstance(event.payload, dict) else {}
    payload.update(
        {
            "condition_random_result": selected,
            "condition_random_choice_key": choice_key,
        }
    )
    return GameEvent(
        event.event_type if event is not None else "status.condition.random",
        source_id=event.source_id if event is not None else "",
        target_id=event.target_id if event is not None else "",
        event_id=event.event_id if event is not None else "",
        window=event.window if event is not None else "status_condition",
        process_only=True,
        payload=payload,
    )


def _condition_random_chance_nodes(condition) -> tuple[tuple[str, object], ...]:
    found: list[tuple[str, object]] = []
    if getattr(condition, "opcode", "") == "ByRandomChance":
        found.append(("$", condition.payload.get("Chance")))

    def visit(value: object, path: str) -> None:
        if isinstance(value, dict):
            opcode = value.get("opcode") or value.get("expression_kind")
            if opcode == "ByRandomChance":
                found.append((path, value.get("Chance")))
            for key, item in value.items():
                visit(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")

    visit(getattr(condition, "payload", {}), "$.payload")
    deduped: list[tuple[str, object]] = []
    seen: set[str] = set()
    for path, expression in found:
        if path not in seen:
            seen.add(path)
            deduped.append((path, expression))
    return tuple(deduped)


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
    return bool(
        unit is not None and runtime_unit_is_target_candidate(unit)
    )


def _alive_enemy_ids_for_status_owner(state: BattleState, detail: dict[str, JSONValue]) -> tuple[str, ...]:
    owner_id = str(detail.get("owner_id") or "")
    owner = state.units.get(owner_id)
    if owner is None:
        return ()
    return tuple(
        unit_id
        for unit_id, unit in sorted(state.units.items())
        if runtime_units_are_opposing_combat_teams(owner, unit)
        and runtime_unit_is_target_candidate(unit)
    )


def _hp_ratio(state: BattleState, unit_id: str) -> float:
    unit = state.units[unit_id]
    return float(unit.hp / unit.max_hp) if unit.max_hp > 0 else float("inf")


def _status_damage_binding_sources(
    detail: dict[str, JSONValue],
    emission: StatusDamageEmissionIR,
    break_base_damage: dict[str, JSONValue],
) -> tuple[dict[str, JSONValue], ...]:
    hashes = numeric_dynamic_hashes(emission.scaling_expr)
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
    hashes = numeric_dynamic_hashes(emission.delay_expr)
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
    value = detail.get("break_template_id")
    return str(value) if isinstance(value, str) else ""


def _break_element_from_detail(detail: dict[str, JSONValue]) -> str | None:
    value = detail.get("break_element_type")
    return str(value) if isinstance(value, str) and value else None


def _resolve_callback_target_id(
    state: BattleState,
    detail: dict[str, JSONValue],
    target_alias: str | None,
    event: GameEvent | None,
) -> str:
    alias = target_alias or "ModifierOwnerEntity"
    if alias == "ModifierOwnerEntity":
        return str(detail.get("owner_id") or "")
    if alias == "Caster":
        return str(detail.get("caster_id") or "")
    if alias in {
        "ActualOwner",
        "ModifierOwnerSummoner",
        "ModifierOwnerEntity.GetSummoner",
    }:
        owner_id = str(detail.get("owner_id") or "")
        relation_id = _unit_relation_id_from_state(state, owner_id)
        if relation_id:
            return relation_id
        return _unit_relation_id_from_detail(
            detail,
            owner_id,
            "summoner_id",
            "owner_id",
        )
    if alias in {
        "ParamEntity",
        "CurrentActionTarget",
        "AbilityTargetEntity",
        "DamageDefenderEntity",
    }:
        payload = event.payload if event is not None and isinstance(event.payload, dict) else {}
        return _first_payload_str(payload, ("param_entity_id", "current_hit_target_id", "damage_defender_id", "primary_target_id", "target_id")) or (
            str(event.target_id or "") if event is not None else ""
        )
    if alias == "DamageAttackerEntity":
        payload = event.payload if event is not None and isinstance(event.payload, dict) else {}
        return _first_payload_str(payload, ("damage_attacker_id", "actor_id", "source_id")) or (
            str(event.source_id or "") if event is not None else ""
        )
    if alias == "CurrentTurnOwnerEntity":
        payload = event.payload if event is not None and isinstance(event.payload, dict) else {}
        return _first_payload_str(payload, ("turn_owner_id", "actor_id")) or (
            str(event.source_id or "") if event is not None else ""
        )
    if alias == "ParamEntity2":
        payload = event.payload if event is not None and isinstance(event.payload, dict) else {}
        return _first_payload_str(payload, ("param_entity_2_id", "param_entity2_id", "secondary_target_id"))
    return ""


def _callback_task_target_expression_id(
    rules: RuleBook,
    task: StatusCallbackTaskIR,
) -> tuple[str, str]:
    if task.target_expression_id:
        return task.target_expression_id, ""
    if not task.effect_id:
        return "", ""
    effect = rules.effect(task.effect_id)
    if effect is None:
        return "", ""
    task_evidence = task.source.evidence
    effect_evidence = effect.source.evidence
    if (
        effect.source.source_path != task.source.source_path
        or effect.source.raw_id != task.source.raw_id
        or any(
            task_evidence.get(key) != effect_evidence.get(key)
            for key in ("callback_id", "task_path", "opcode")
        )
    ):
        return "", "status_callback_target_effect_source_mismatch"
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return "", ""
    expression_id = standard.get("target_expression_id")
    if not isinstance(expression_id, str) or not expression_id:
        return "", ""
    expression = rules.target_expression(expression_id)
    if expression is None:
        return expression_id, ""
    expression_evidence = expression.source.evidence
    if (
        expression.source.source_path != task.source.source_path
        or expression_evidence.get("source_raw_id") != task.source.raw_id
        or any(
            task_evidence.get(key) != expression_evidence.get(key)
            for key in ("callback_id", "task_path", "opcode")
        )
    ):
        return "", "status_callback_target_expression_source_mismatch"
    return expression_id, ""


def _context_dynamic_value(
    state: BattleState,
    task: StatusCallbackTaskIR,
    detail: dict[str, JSONValue],
    event: GameEvent | None,
    engine_rules: EngineRuleRegistry,
) -> tuple[float | None, dict[str, JSONValue], str]:
    payload = task.task_payload
    opcode = task.opcode
    event_payload = (
        event.payload
        if event is not None and isinstance(event.payload, dict)
        else {}
    )
    if opcode == "SetModifierDynamicValue":
        evaluation = _evaluate_callback_numeric(
            payload.get("NewValue"),
            state,
            detail,
            task,
            engine_rules,
        )
        if not evaluation.ok or evaluation.value is None:
            return None, {"numeric_evaluation": evaluation.to_json()}, (
                evaluation.blocked_reason or "new_dynamic_value_unresolved"
            )
        return evaluation.value, {"numeric_evaluation": evaluation.to_json()}, ""

    if opcode == "SetDynamicValue":
        evaluation = _evaluate_callback_numeric(
            payload.get("Value"),
            state,
            detail,
            task,
            engine_rules,
        )
        if not evaluation.ok or evaluation.value is None:
            return None, {"numeric_evaluation": evaluation.to_json()}, (
                evaluation.blocked_reason or "dynamic_value_unresolved"
            )
        return evaluation.value, {"numeric_evaluation": evaluation.to_json()}, ""

    if opcode == "SetDynamicValueByAttackTargetCount":
        attacker_alias = str(payload.get("Attacker") or "ModifierOwnerEntity")
        expected_attacker = _resolve_callback_target_id(
            state, detail, attacker_alias, event
        )
        actual_attacker = _first_payload_str(
            event_payload,
            ("damage_attacker_id", "attacker_id", "actor_id", "source_id"),
        ) or (str(event.source_id or "") if event is not None else "")
        if not expected_attacker or expected_attacker not in state.units:
            return None, {"attacker_alias": attacker_alias}, "attack_target_count_attacker_unresolved"
        if actual_attacker and actual_attacker != expected_attacker:
            return 0.0, {
                "kind": "attack_target_count",
                "expected_attacker_id": expected_attacker,
                "actual_attacker_id": actual_attacker,
                "target_ids": [],
            }, ""
        target_values = next(
            (
                event_payload.get(key)
                for key in (
                    "selected_target_ids",
                    "attack_target_ids",
                    "skill_target_ids",
                    "target_ids",
                )
                if isinstance(event_payload.get(key), (list, tuple))
            ),
            None,
        )
        if target_values is None:
            return None, {
                "expected_attacker_id": expected_attacker,
            }, "attack_target_count_event_targets_missing"
        target_ids = tuple(
            dict.fromkeys(
                str(item)
                for item in target_values
                if isinstance(item, str) and item in state.units
            )
        )
        return float(len(target_ids)), {
            "kind": "attack_target_count",
            "expected_attacker_id": expected_attacker,
            "actual_attacker_id": actual_attacker,
            "target_ids": list(target_ids),
        }, ""

    if opcode == "SetDynamicValueByBPChange":
        metadata = event_payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        value_type = payload.get("ValueType")
        candidate = (
            metadata.get("unclamped_delta")
            if value_type == "UnclampedDelta"
            else event_payload.get("change_value")
        )
        if not _is_runtime_number(candidate):
            candidate = event_payload.get("delta")
        if not _is_runtime_number(candidate):
            return None, {
                "value_type": value_type,
                "event_type": event.event_type if event is not None else "",
            }, "bp_change_value_missing"
        return float(candidate), {
            "kind": "battle_skill_point_change",
            "value_type": value_type or "actual_delta",
            "event_type": event.event_type if event is not None else "",
            "mutation_id": event_payload.get("mutation_id"),
        }, ""

    if opcode == "SetDynamicValueByDamageDataProperty":
        value = _damage_property_value(event_payload, "Result_FinalDamage")
        if value is None:
            return None, {
                "event_type": event.event_type if event is not None else "",
            }, "damage_data_property_missing:Result_FinalDamage"
        return value, {
            "kind": "damage_data_property",
            "property": "Result_FinalDamage",
            "event_id": event.event_id if event is not None else "",
        }, ""

    if opcode == "SetDynamicValueByHealDataProperty":
        candidate = event_payload.get("heal_amount")
        if not _is_runtime_number(candidate):
            candidate = event_payload.get("actual_delta")
        if not _is_runtime_number(candidate):
            return None, {
                "event_type": event.event_type if event is not None else "",
            }, "heal_data_property_missing:actual_heal"
        return float(candidate), {
            "kind": "heal_data_property",
            "property": "actual_heal",
            "event_id": event.event_id if event is not None else "",
        }, ""

    if opcode == "SetDynamicValueByMaxBP":
        return float(state.max_skill_points), {
            "kind": "battle_skill_point_maximum",
            "max_skill_points": state.max_skill_points,
        }, ""

    if opcode == "SetDynamicValueByVariateType":
        if payload.get("VariateType") != "ParamValue":
            return None, {
                "variate_type": payload.get("VariateType"),
            }, "context_variate_type_not_admitted"
        candidate = event_payload.get("param_value")
        if not _is_runtime_number(candidate):
            candidate = event_payload.get("change_value")
        if not _is_runtime_number(candidate):
            candidate = event_payload.get("delta")
        if not _is_runtime_number(candidate):
            return None, {
                "event_type": event.event_type if event is not None else "",
            }, "context_param_value_missing"
        return float(candidate), {
            "kind": "event_param_value",
            "event_type": event.event_type if event is not None else "",
            "mutation_id": event_payload.get("mutation_id"),
        }, ""

    if opcode == "SetDynamicValueByCountOfBaseType":
        group_alias = str(payload.get("TargetType") or "AllLightTeam.RemoveServant")
        target_ids = _callback_target_group(state, detail, event, group_alias)
        raw_base_types = payload.get("BaseTypeList")
        if raw_base_types is not None:
            if (
                not isinstance(raw_base_types, (list, tuple))
                or not raw_base_types
                or any(not isinstance(item, str) or not item for item in raw_base_types)
            ):
                return None, {"target_alias": group_alias}, "base_type_list_invalid"
            base_types = tuple(dict.fromkeys(raw_base_types))
            source_metadata: dict[str, JSONValue] = {
                "base_type_source_kind": "explicit_list",
                "base_types": list(base_types),
            }
        else:
            source_alias = str(payload.get("BaseTypeSourceTarget") or "")
            if not source_alias:
                return None, {"target_alias": group_alias}, "base_type_source_missing"
            source_target_id = _resolve_callback_target_id(
                state, detail, source_alias, event
            )
            source_target = state.units.get(source_target_id)
            if source_target is None:
                return None, {
                    "target_alias": group_alias,
                    "base_type_source_alias": source_alias,
                }, "base_type_source_target_missing"
            base_type = _unit_base_type(source_target)
            if not base_type:
                return None, {
                    "target_alias": group_alias,
                    "base_type_source_target_id": source_target_id,
                }, "base_type_source_missing"
            base_types = (base_type,)
            source_metadata = {
                "base_type_source_kind": "target",
                "base_type_source_alias": source_alias,
                "base_type_source_target_id": source_target_id,
                "base_types": [base_type],
            }
        matches = tuple(
            unit_id
            for unit_id in target_ids
            if _unit_base_type(state.units[unit_id]) in base_types
        )
        return float(len(matches)), {
            "kind": "matching_base_type_count",
            "target_alias": group_alias,
            "target_ids": list(target_ids),
            "matching_target_ids": list(matches),
            **source_metadata,
        }, ""

    explicit_read_alias = (
        payload.get("ReadTargetType")
        or payload.get("FromTargetType")
        or payload.get("BaseTypeSourceTarget")
        or payload.get("TargetType")
    )
    read_alias = str(explicit_read_alias or "ModifierOwnerEntity")
    if opcode == "SetDynamicValueByCharacterCount" and read_alias in {
        "AllEnemy",
        "AllEnemyWithUnSelectable",
        "AllLightTeam",
        "AllLightTeam.RemoveServant",
        "AllTeamMember",
        "AllTeamMemberWithUnselectable",
    }:
        target_ids = _callback_target_group(state, detail, event, read_alias)
        if not target_ids and not state.units.get(
            str(detail.get("owner_id") or detail.get("caster_id") or "")
        ):
            return None, {"target_alias": read_alias}, "character_count_owner_missing"
        if payload.get("AliveOnly") is True:
            target_ids = tuple(
                unit_id
                for unit_id in target_ids
                if runtime_unit_is_active(state.units[unit_id])
            )
        return float(len(target_ids)), {
            "kind": "character_count",
            "target_alias": read_alias,
            "target_ids": list(target_ids),
        }, ""
    target_id = _resolve_callback_target_id(state, detail, read_alias, event)
    if not target_id and explicit_read_alias is None:
        target_id = str(detail.get("owner_id") or "")
    if not target_id:
        return None, {"target_alias": read_alias}, f"context_dynamic_value_target_unresolved:{read_alias}"
    target = state.units.get(target_id)

    if opcode == "SetDynamicValueByHPRatio":
        if target is None or target.max_hp <= 0:
            return None, {"target_id": target_id}, "hp_ratio_target_missing"
        return (
            float(target.hp) / float(target.max_hp),
            {"kind": "hp_ratio", "target_id": target_id},
            "",
        )
    if opcode == "SetDynamicValueByProperty":
        if target is None:
            return None, {"target_id": target_id}, "property_target_missing"
        property_name = payload.get("SourceProperty")
        value = _unit_property_value(target, property_name)
        if value is None:
            return None, {
                "target_id": target_id,
                "property": property_name,
            }, "unit_property_not_available"
        return value, {
            "kind": "unit_property",
            "target_id": target_id,
            "property": property_name,
        }, ""
    if opcode == "SetDynamicValueByCharacterCount":
        target_ids = _callback_target_group(
            state,
            detail,
            event,
            read_alias,
        )
        if payload.get("AliveOnly") is True:
            target_ids = tuple(
                unit_id
                for unit_id in target_ids
                if runtime_unit_is_active(state.units[unit_id])
            )
        return float(len(target_ids)), {
            "kind": "character_count",
            "target_alias": read_alias,
            "target_ids": list(target_ids),
        }, ""
    if opcode == "SetDynamicValueByStatusCount":
        if target is None:
            return None, {"target_id": target_id}, "status_count_target_missing"
        details = target.flags.get("status_details", ())
        if not isinstance(details, (list, tuple)):
            return None, {"target_id": target_id}, "status_details_invalid"
        admitted = tuple(
            item
            for item in details
            if isinstance(item, dict)
            and item.get("status_category") == "debuff"
        )
        return float(len(admitted)), {
            "kind": "debuff_status_count",
            "target_id": target_id,
            "status_instance_ids": [
                str(item.get("instance_id") or "") for item in admitted
            ],
        }, ""
    if opcode == "SetDynamicValueByWeaknessCount":
        if target is None:
            return None, {"target_id": target_id}, "weakness_target_missing"
        weaknesses = target.flags.get("weaknesses", ())
        if not isinstance(weaknesses, (list, tuple)):
            return None, {"target_id": target_id}, "weaknesses_invalid"
        return float(len(tuple(dict.fromkeys(str(item) for item in weaknesses)))), {
            "kind": "weakness_count",
            "target_id": target_id,
            "weaknesses": list(weaknesses),
        }, ""
    if opcode == "SetDynamicValueByCopying":
        source_modifier = payload.get("FromModifierName")
        source_key = payload.get("FromDynamicKey")
        if not isinstance(source_modifier, str) or not source_modifier:
            return None, {}, "copy_source_modifier_missing"
        if not isinstance(source_key, str) or not source_key:
            return None, {}, "copy_source_dynamic_key_missing"
        source_detail = find_status_detail(
            state,
            target_id,
            modifier_name=source_modifier,
        )
        if source_detail is None:
            return None, {"target_id": target_id}, "copy_source_modifier_missing"
        value = _status_dynamic_value(source_detail, source_key)
        if value is None:
            return None, {
                "target_id": target_id,
                "source_modifier": source_modifier,
                "source_key": source_key,
            }, "copy_source_dynamic_value_missing"
        return value, {
            "kind": "copy_status_dynamic_value",
            "target_id": target_id,
            "source_modifier": source_modifier,
            "source_key": source_key,
            "source_instance_id": source_detail.get("instance_id"),
        }, ""
    return None, {"opcode": opcode}, "context_dynamic_value_opcode_not_supported"


def _evaluate_callback_numeric(
    expression: object,
    state: BattleState,
    detail: dict[str, JSONValue],
    task: StatusCallbackTaskIR,
    engine_rules: EngineRuleRegistry,
) -> NumericEvaluationResult:
    owner_id = str(detail.get("owner_id") or "")
    caster_id = str(detail.get("caster_id") or owner_id)
    engine_binding, engine_reason = engine_numeric_binding_source(
        expression,
        engine_rules,
    )
    if engine_reason:
        return NumericEvaluationResult(
            ok=False,
            value=None,
            expression_kind=(
                str(expression.get("kind") or "unsupported")
                if isinstance(expression, dict)
                else "unsupported"
            ),
            bindings={},
            source_trace={
                "status_task_source": task.source.to_json(),
                "status_instance_source": _json_dict(detail.get("source_trace")),
            },
            blocked_reason=engine_reason,
        )
    all_local_status_sources = status_binding_sources(
        state,
        tuple(dict.fromkeys(
            unit_id
            for unit_id in (owner_id, caster_id)
            if unit_id
        )),
    )
    live_detail = _status_detail_by_instance(
        state,
        owner_id,
        str(detail.get("instance_id") or ""),
    ) or detail
    current_status_source = binding_source_from_status_detail(
        live_detail,
        live_detail.get("dynamic_values"),
    )
    current_instance_id = str(detail.get("instance_id") or "")
    claimed_hashes = {
        str(key)
        for key in (
            current_status_source.get("by_hash", {}).keys()
            if isinstance(current_status_source, dict)
            and isinstance(current_status_source.get("by_hash"), dict)
            else ()
        )
    }
    claimed_names = {
        str(key)
        for key in (
            current_status_source.get("by_name", {}).keys()
            if isinstance(current_status_source, dict)
            and isinstance(current_status_source.get("by_name"), dict)
            else ()
        )
    }
    other_status_sources = tuple(
        filtered
        for source in all_local_status_sources
        if str(source.get("status_instance_id") or "") != current_instance_id
        if (
            filtered := _binding_source_without_keys(
                source,
                excluded_hashes=claimed_hashes,
                excluded_names=claimed_names,
            )
        )
    )
    local_status_sources = (
        *((current_status_source,) if current_status_source is not None else ()),
        *other_status_sources,
    )
    store_source = _store_binding_source_without_status_mirrors(
        binding_source_from_store(store_from_state(state)),
        local_status_sources,
    )
    return RuleEvaluator().evaluate_numeric(
        expression,
        NumericEvaluationContext(
            binding_sources=(
                *local_status_sources,
                store_source,
                *((engine_binding,) if engine_binding is not None else ()),
            ),
            source_trace={
                "status_task_source": task.source.to_json(),
                "status_instance_source": _json_dict(detail.get("source_trace")),
            },
        ),
    )


def _status_detail_by_instance(
    state: BattleState,
    unit_id: str,
    instance_id: str,
) -> dict[str, JSONValue] | None:
    if not unit_id or not instance_id:
        return None
    unit = state.units.get(unit_id)
    details = unit.flags.get("status_details", ()) if unit is not None else ()
    if not isinstance(details, (list, tuple)):
        return None
    return next(
        (
            item
            for item in details
            if isinstance(item, dict)
            and str(item.get("instance_id") or "") == instance_id
        ),
        None,
    )


def _store_binding_source_without_status_mirrors(
    store_source: dict[str, JSONValue],
    status_sources: tuple[dict[str, JSONValue], ...],
) -> dict[str, JSONValue]:
    """Keep the global store as a cross-instance source, not a second local copy."""

    local_instance_ids = {
        str(source.get("status_instance_id") or "")
        for source in status_sources
        if source.get("status_instance_id")
    }
    if not local_instance_ids:
        return store_source
    entries = store_source.get("entries")
    if not isinstance(entries, dict):
        return store_source
    filtered_entries = {
        key: entry
        for key, entry in entries.items()
        if not isinstance(entry, dict)
        or str(entry.get("status_instance_id") or "")
        not in local_instance_ids
    }
    return binding_source_from_store({"entries": filtered_entries})


def _binding_source_without_keys(
    source: dict[str, JSONValue],
    *,
    excluded_hashes: set[str],
    excluded_names: set[str],
) -> dict[str, JSONValue] | None:
    entries = source.get("entries")
    if not isinstance(entries, dict):
        return source
    filtered_entries = {
        key: entry
        for key, entry in entries.items()
        if not isinstance(entry, dict)
        or (
            str(entry.get("hash") or "") not in excluded_hashes
            and str(entry.get("name") or "") not in excluded_names
        )
    }
    if not filtered_entries:
        return None
    filtered = binding_source_from_store({"entries": filtered_entries})
    return {
        **filtered,
        "source_type": source.get("source_type") or "status_instance",
        "status_instance_id": source.get("status_instance_id"),
        "status_id": source.get("status_id"),
    }


def _callback_target_group(
    state: BattleState,
    detail: dict[str, JSONValue],
    event: GameEvent | None,
    alias: str,
) -> tuple[str, ...]:
    owner_id = str(detail.get("owner_id") or detail.get("caster_id") or "")
    owner = state.units.get(owner_id)
    if alias in {"AllEnemy", "AllEnemyWithUnSelectable"} and owner is not None:
        include_unselectable = alias == "AllEnemyWithUnSelectable"
        return tuple(
            unit_id
            for unit_id, unit in sorted(state.units.items())
            if runtime_units_are_opposing_combat_teams(owner, unit)
            and runtime_unit_is_target_candidate(
                unit,
                include_unselectable=include_unselectable,
            )
        )
    if alias in {
        "AllLightTeam",
        "AllLightTeam.RemoveServant",
        "AllLightTeamWithUnselectable",
        "AllLightTeamWithAllLightTeamUnselectable",
        "AllLightTeamWithAllUnselectableLightTeam",
    }:
        include_unselectable = "WithUnselectable" in alias or "WithAll" in alias
        return tuple(
            unit_id
            for unit_id, unit in sorted(state.units.items())
            if runtime_unit_is_light_team(unit)
            and runtime_unit_is_target_candidate(
                unit,
                include_unselectable=include_unselectable,
            )
            and (
                "RemoveServant" not in alias
                or unit.flags.get("summon_kind") != "servant"
            )
        )
    if alias == "AllDarkTeam":
        return tuple(
            unit_id
            for unit_id, unit in sorted(state.units.items())
            if runtime_unit_is_dark_team(unit)
            and runtime_unit_is_target_candidate(unit)
        )
    if alias in {
        "AllTeamMember",
        "AllTeamMemberWithUnselectable",
        "AllTeammate",
        "AllTeammateWithUnselectable",
    } and owner is not None:
        include_unselectable = alias in {
            "AllTeamMemberWithUnselectable",
            "AllTeammateWithUnselectable",
        }
        return tuple(
            unit_id
            for unit_id, unit in sorted(state.units.items())
            if runtime_units_share_combat_team(owner, unit)
            and runtime_unit_is_target_candidate(
                unit,
                include_unselectable=include_unselectable,
            )
            and (
                alias not in {"AllTeammate", "AllTeammateWithUnselectable"}
                or unit_id != owner_id
            )
        )
    resolved = _resolve_callback_target_id(state, detail, alias, event)
    return (resolved,) if resolved in state.units else ()


def _unit_property_value(unit, property_name: object) -> float | None:
    direct = {
        "CurrentHP": unit.hp,
        "Defence": effective_unit_stat(unit, "defense").value,
        "MaxHP": unit.max_hp,
        "MaxSP": unit.max_energy,
        "Speed": effective_unit_stat(unit, "speed").value,
    }
    if property_name in direct:
        return float(direct[property_name])
    resource_keys = {
        "BreakDamageAddedRatio": "break_damage_added_ratio",
        "CriticalDamage": "critical_damage",
        "StatusResistanceBase": "effect_resistance",
    }
    resource_key = resource_keys.get(property_name)
    if resource_key:
        return effective_unit_stat(unit, resource_key).value
    return None


def _unit_base_type(unit) -> str:
    for key in ("avatar_base_type", "path", "base_type"):
        value = unit.flags.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _status_dynamic_value(detail: dict[str, JSONValue], key: str) -> float | None:
    values = detail.get("dynamic_values")
    if not isinstance(values, dict):
        return None
    direct = values.get(key)
    if isinstance(direct, (int, float)):
        return float(direct)
    by_name = values.get("__by_name")
    if isinstance(by_name, dict):
        value = by_name.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _unit_relation_id_from_detail(
    detail: dict[str, JSONValue],
    owner_id: str,
    *keys: str,
) -> str:
    source_trace = detail.get("source_trace")
    for container in (detail, source_trace if isinstance(source_trace, dict) else {}):
        for key in keys:
            value = container.get(key)
            if isinstance(value, str) and value:
                return value
    return owner_id


def _unit_relation_id_from_state(state: BattleState, unit_id: str) -> str:
    unit = state.units.get(unit_id)
    if unit is None:
        return ""
    for key in ("summoner_id", "owner_id"):
        value = unit.flags.get(key)
        if isinstance(value, str) and value in state.units:
            return value
    runtime = state.global_flags.get("summon_runtime")
    if not isinstance(runtime, dict):
        return ""
    for collection_key in ("entities", "servants"):
        collection = runtime.get(collection_key)
        if not isinstance(collection, dict):
            continue
        entry = collection.get(unit_id)
        if not isinstance(entry, dict):
            continue
        owner_id = entry.get("owner_id")
        if isinstance(owner_id, str) and owner_id in state.units:
            return owner_id
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
        return str(event.target_id or "") if event is not None else ""
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
    *,
    condition: ConditionIR | None = None,
    targets: TargetSystem | None = None,
) -> EvaluationContext:
    detail = _current_status_detail(state, detail)
    payload = dict(event.payload) if event is not None and isinstance(event.payload, dict) else {}
    if event is not None:
        payload.setdefault("event_id", event.event_id)
        payload.setdefault("event_source_id", event.source_id)
        payload.setdefault("event_target_id", event.target_id)
        payload.setdefault("event_window", event.window)
    owner_id = str(detail.get("owner_id") or "")
    caster_id = str(detail.get("caster_id") or owner_id)
    target_id = _first_payload_str(payload, ("current_hit_target_id", "primary_target_id", "target_id")) or (
        str(event.target_id or "") if event is not None else ""
    )
    param_entity_id = _first_payload_str(payload, ("param_entity_id",)) or target_id
    current_status_binding_source = binding_source_from_status_detail(
        detail,
        detail.get("dynamic_values"),
    )
    current_status_instance_id = str(detail.get("instance_id") or "")
    current_hashes = tuple(
        str(key)
        for key in (
            current_status_binding_source.get("by_hash", {}).keys()
            if current_status_binding_source is not None
            and isinstance(current_status_binding_source.get("by_hash"), dict)
            else ()
        )
    )
    current_names = tuple(
        str(key)
        for key in (
            current_status_binding_source.get("by_name", {}).keys()
            if current_status_binding_source is not None
            and isinstance(current_status_binding_source.get("by_name"), dict)
            else ()
        )
    )
    callback_binding_sources = (
        *((current_status_binding_source,) if current_status_binding_source is not None else ()),
        binding_source_from_store(
            store_from_state(state),
            excluded_status_instance_ids=(current_status_instance_id,),
            excluded_hashes=current_hashes,
            excluded_names=current_names,
        ),
    )
    resolved_target_groups: dict[str, tuple[str, ...]] = {}
    target_resolution_errors: dict[str, str] = {}
    if condition is not None and targets is not None:
        for node in _condition_target_nodes(condition):
            key = _condition_target_key(node)
            if key in resolved_target_groups or key in target_resolution_errors:
                continue
            resolution = targets.resolve_expression_node(
                state,
                node,
                caster_id=caster_id,
                owner_id=owner_id or None,
                param_entity_id=param_entity_id or None,
                current_action_target_id=target_id or None,
                event_payload=payload,
                binding_sources=callback_binding_sources,
            )
            if resolution.ok:
                resolved_target_groups[key] = resolution.target_ids
            else:
                target_resolution_errors[key] = resolution.blocked_reason
    return EvaluationContext(
        state=state,
        actor_id=caster_id,
        target_id=target_id or None,
        owner_id=owner_id,
        param_entity_id=param_entity_id or None,
        current_action_target_id=target_id or None,
        status_detail=detail,
        event_payload=payload,
        # Status parameters are source-backed runtime bindings.  Passing the
        # same values through ``dynamic_values`` would make the evaluator label
        # them as unauditable ``explicit_dynamic_values`` and would let that
        # ad-hoc channel shadow the real status-instance source.
        dynamic_values=None,
        resolved_target_groups=resolved_target_groups,
        target_resolution_errors=target_resolution_errors,
        binding_sources=callback_binding_sources,
    )


def _condition_target_nodes(condition: ConditionIR) -> tuple[TargetExpressionNodeIR, ...]:
    nodes: list[TargetExpressionNodeIR] = []

    def visit(value: object) -> None:
        if isinstance(value, TargetExpressionNodeIR):
            nodes.append(value)
            return
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(condition.payload)
    return tuple(nodes)


def _effect_context(
    state: BattleState,
    task: StatusCallbackTaskIR,
    detail: dict[str, JSONValue],
    event: GameEvent | None,
    damage_window_ledger: DamageWindowLedger | None = None,
) -> EffectExecutionContext:
    detail = _current_status_detail(state, detail)
    payload = dict(event.payload) if event is not None and isinstance(event.payload, dict) else {}
    if event is not None:
        payload.setdefault("event_source_id", event.source_id)
        payload.setdefault("event_target_id", event.target_id)
        payload.setdefault("event_window", event.window)
    payload.setdefault("status_instance_id", str(detail.get("instance_id") or ""))
    payload.setdefault("status_id", str(detail.get("status_id") or ""))
    payload.setdefault("modifier_name", str(detail.get("modifier_name") or ""))
    payload.setdefault(
        "status_instance_source",
        _json_dict(detail.get("source_trace")),
    )
    owner_id = str(detail.get("owner_id") or "")
    caster_id = str(detail.get("caster_id") or owner_id)
    target_id = _first_payload_str(payload, ("current_hit_target_id", "primary_target_id", "target_id")) or (
        str(event.target_id or "") if event is not None else ""
    )
    param_entity_id = _first_payload_str(payload, ("param_entity_id",)) or target_id
    current_status_instance_id = str(detail.get("instance_id") or "")
    current_status_binding_source = binding_source_from_status_detail(
        detail,
        detail.get("dynamic_values"),
    )
    return EffectExecutionContext(
        state=state,
        caster_id=caster_id,
        # The callback task remains part of the audit trace, but it is not the
        # semantic owner of a child status.  All callbacks emitted by the same
        # status instance must therefore share the parent status identity;
        # otherwise OnStack and a later listener can manufacture two sources
        # for the same equipment effect.
        source_id=(
            f"status_callback_status:{current_status_instance_id}"
            if current_status_instance_id
            else f"status_callback_task:{task.task_id}"
        ),
        owner_id=owner_id,
        param_entity_id=param_entity_id or None,
        current_action_target_id=target_id or None,
        event_payload=payload,
        dynamic_values=None,
        binding_sources=(
            (current_status_binding_source,)
            if current_status_binding_source is not None
            else ()
        ),
        include_ambient_status_bindings=False,
        shadowed_status_instance_ids=(
            (current_status_instance_id,) if current_status_instance_id else ()
        ),
        damage_window_ledger=damage_window_ledger,
    )
def _current_status_detail(
    state: BattleState,
    detail: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    owner_id = str(detail.get("owner_id") or "")
    instance_id = str(detail.get("instance_id") or "")
    unit = state.units.get(owner_id)
    if unit is None or not instance_id:
        return detail
    current_details = unit.flags.get("status_details", ())
    if not isinstance(current_details, (list, tuple)):
        return detail
    return next(
        (
            item
            for item in current_details
            if isinstance(item, dict) and item.get("instance_id") == instance_id
        ),
        detail,
    )


def _definition_dynamic_hash_aliases(
    detail: dict[str, JSONValue],
    *,
    dynamic_key: str,
    source_task_id: str,
) -> tuple[dict[str, JSONValue], ...]:
    dynamic_values = detail.get("dynamic_values")
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
        by_name.get(dynamic_key) if isinstance(by_name, dict) else None
    )
    named_hashes = (
        named_binding.get("hashes")
        if isinstance(named_binding, dict)
        else None
    )
    if isinstance(named_hashes, (list, tuple)) and named_hashes:
        return tuple(
            {
                "hash": str(hash_key),
                "dynamic_key": dynamic_key,
                "source_kind": "document_unique_dynamic_key_hash_evidence",
                "source_task_id": source_task_id,
                "definition_binding": named_binding,
            }
            for hash_key in named_hashes
            if isinstance(hash_key, (str, int))
        )
    if not isinstance(by_hash, dict):
        return ()
    candidates: list[tuple[str, dict[str, JSONValue]]] = []
    for hash_key, binding in by_hash.items():
        if not isinstance(binding, dict):
            continue
        read_info = binding.get("read_info")
        if (
            isinstance(read_info, dict)
            and str(read_info.get("Type") or "") == "None"
        ):
            candidates.append((str(hash_key), binding))
    if len(candidates) != 1:
        return ()
    hash_key, binding = candidates[0]
    return (
        {
            "hash": hash_key,
            "dynamic_key": dynamic_key,
            "source_kind": "unique_modifier_internal_dynamic_slot",
            "source_task_id": source_task_id,
            "definition_binding": binding,
        },
    )


def _dynamic_hash_aliases_for_context_task(
    detail: dict[str, JSONValue],
    *,
    task: StatusCallbackTaskIR,
    tasks: dict[str, StatusCallbackTaskIR],
) -> tuple[dict[str, JSONValue], ...]:
    """Bind a callback-local dynamic name to its exact definition hash.

    Some TBGD modifier definitions expose several ``Type=None`` hash slots
    without a named table.  In those records the task graph itself carries
    the lossless relationship: every writer of the same DynamicKey refers to
    that slot in its typed numeric expression.  We admit the relationship
    only when the graph and definition intersect in exactly one hash.
    """

    payload = task.task_payload
    dynamic_key = payload.get("DynamicKey") or payload.get("ToDynamicKey")
    if not isinstance(dynamic_key, str) or not dynamic_key:
        return ()
    direct = _definition_dynamic_hash_aliases(
        detail,
        dynamic_key=dynamic_key,
        source_task_id=task.task_id,
    )
    if direct:
        return direct

    dynamic_values = detail.get("dynamic_values")
    definition_bindings = (
        dynamic_values.get("__definition_bindings")
        if isinstance(dynamic_values, dict)
        else None
    )
    definition_by_hash = (
        definition_bindings.get("by_hash")
        if isinstance(definition_bindings, dict)
        else None
    )
    callback_by_hash = (
        definition_bindings.get("callback_by_hash")
        if isinstance(definition_bindings, dict)
        else None
    )
    if not isinstance(definition_by_hash, dict) and not isinstance(
        callback_by_hash,
        dict,
    ):
        return ()

    referenced_hashes: set[str] = set()
    contributing_task_ids: list[str] = []
    for candidate in tasks.values():
        candidate_payload = candidate.task_payload
        candidate_key = candidate_payload.get("DynamicKey") or candidate_payload.get(
            "ToDynamicKey"
        )
        if candidate_key != dynamic_key:
            continue
        candidate_hashes = _numeric_hashes_in_payload(candidate_payload)
        if candidate_hashes:
            contributing_task_ids.append(candidate.task_id)
            referenced_hashes.update(candidate_hashes)

    candidates: dict[str, dict[str, JSONValue]] = {}
    for hash_key, binding in (
        definition_by_hash.items()
        if isinstance(definition_by_hash, dict)
        else ()
    ):
        if str(hash_key) not in referenced_hashes or not isinstance(binding, dict):
            continue
        read_info = binding.get("read_info")
        if (
            isinstance(read_info, dict)
            and str(read_info.get("Type") or "") == "None"
        ):
            candidates[str(hash_key)] = binding
    resolved_hashes = {
        str(hash_key)
        for hash_key in (
            dynamic_values.get("__by_hash", {}).keys()
            if isinstance(dynamic_values, dict)
            and isinstance(dynamic_values.get("__by_hash"), dict)
            else ()
        )
    }
    for hash_key, binding in (
        callback_by_hash.items()
        if isinstance(callback_by_hash, dict)
        else ()
    ):
        if (
            str(hash_key) in referenced_hashes
            and str(hash_key) not in resolved_hashes
            and isinstance(binding, dict)
        ):
            candidates[str(hash_key)] = binding
    used_unique_unresolved_fallback = False
    if not candidates and isinstance(callback_by_hash, dict):
        unresolved_callback_hashes = {
            str(hash_key): binding
            for hash_key, binding in callback_by_hash.items()
            if str(hash_key) not in resolved_hashes and isinstance(binding, dict)
        }
        if len(unresolved_callback_hashes) == 1:
            candidates.update(unresolved_callback_hashes)
            used_unique_unresolved_fallback = True
    if len(candidates) != 1:
        return ()
    hash_key, binding = next(iter(candidates.items()))
    source_kind = (
        "unique_unresolved_modifier_callback_dynamic_slot"
        if used_unique_unresolved_fallback
        else "callback_task_graph_unique_dynamic_slot"
    )
    return (
        {
            "hash": hash_key,
            "dynamic_key": dynamic_key,
            "source_kind": source_kind,
            "source_task_id": task.task_id,
            "contributing_task_ids": sorted(contributing_task_ids),
            "definition_binding": binding,
        },
    )


def _numeric_hashes_in_payload(value: JSONValue) -> set[str]:
    hashes = {
        str(hash_key)
        for hash_key in numeric_dynamic_hashes(value)
        if isinstance(hash_key, (str, int)) and not isinstance(hash_key, bool)
    }
    if isinstance(value, dict):
        for child in value.values():
            hashes.update(_numeric_hashes_in_payload(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            hashes.update(_numeric_hashes_in_payload(child))
    return hashes


def _callback_status_dynamic_value_mutation(
    state: BattleState,
    *,
    target_id: str,
    detail: dict[str, JSONValue],
    callback_id: str,
    dynamic_key: str,
    value: float,
    aliases: tuple[dict[str, JSONValue], ...],
    task: StatusCallbackTaskIR,
    source_trace: dict[str, JSONValue],
) -> Mutation | None:
    unit = state.units.get(target_id)
    if unit is None:
        return None
    raw_details = unit.flags.get("status_details", ())
    if not isinstance(raw_details, (list, tuple)):
        return None
    instance_id = str(detail.get("instance_id") or "")
    if not instance_id:
        return None
    before_details = list(raw_details)
    after_details: list[JSONValue] = []
    found = False
    for item in before_details:
        if not isinstance(item, dict) or item.get("instance_id") != instance_id:
            after_details.append(item)
            continue
        found = True
        dynamic_values = dict(item.get("dynamic_values") or {})
        by_name = dict(dynamic_values.get("__by_name") or {})
        by_hash = dict(dynamic_values.get("__by_hash") or {})
        dynamic_values[dynamic_key] = value
        by_name[dynamic_key] = value
        for alias in aliases:
            hash_key = alias.get("hash")
            if isinstance(hash_key, (str, int)):
                dynamic_values[str(hash_key)] = value
                by_hash[str(hash_key)] = value
        dynamic_values["__by_name"] = by_name
        dynamic_values["__by_hash"] = by_hash
        evaluations = list(dynamic_values.get("__evaluations") or [])
        evaluations.append(
            {
                "name": dynamic_key,
                "result": {
                    "ok": True,
                    "value": value,
                    "expression_kind": "status_callback_context_value",
                    "bindings": {
                        "dynamic_hash_aliases": list(aliases),
                        "source_task_id": task.task_id,
                    },
                    "source_trace": source_trace,
                },
            }
        )
        dynamic_values["__evaluations"] = evaluations
        after_details.append({**item, "dynamic_values": dynamic_values})
    if not found:
        return None
    return Mutation(
        op="set",
        path=("units", target_id, "flags", "status_details"),
        before=before_details if "status_details" in unit.flags else None,
        after=after_details,
        reason="bind context-derived value to status instance",
        source="status_callback_system",
        before_exists="status_details" in unit.flags,
        metadata={
            "callback_id": callback_id,
            "task_id": task.task_id,
            "modifier_name": str(detail.get("modifier_name") or ""),
            "status_instance_id": instance_id,
            "dynamic_key": dynamic_key,
            "dynamic_hash_aliases": aliases,
            "value": value,
            "source_trace": source_trace,
        },
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
        return _callback_target_group(state, detail, event, alias)
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


def _is_runtime_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parent_child_sequence(parent: StatusCallbackTaskIR, task_id: str) -> tuple[str, ...]:
    for candidate in (parent.success_task_ids, parent.failed_task_ids, parent.child_task_ids):
        if task_id in candidate:
            return tuple(candidate)
    return ()


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
