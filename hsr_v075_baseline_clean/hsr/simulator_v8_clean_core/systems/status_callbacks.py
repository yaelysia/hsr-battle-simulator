from __future__ import annotations

from dataclasses import dataclass

from ..core.model import BattleState, GameEvent, JSONValue, Mutation
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..rules.evaluator import NumericEvaluationContext, NumericEvaluationResult, RuleEvaluator
from ..rules.ir import ActionDelayEmissionIR, QueueIntentIR, StatusCallbackIR, StatusCallbackTaskIR, StatusDamageEmissionIR
from ..rules.rulebook import RuleBook
from .damage import DamagePacket, DamageSystem
from .dynamic_values import find_status_detail
from .queue import QueueEntry, QueueSystem
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
    ) -> None:
        self.rules = rules
        self.damage = damage or DamageSystem()
        self.reducer = reducer or MutationReducer()
        self.timeline = timeline or TimelineSystem()
        self.queue = queue or QueueSystem()

    def execute(
        self,
        state: BattleState,
        *,
        unit_id: str,
        modifier_name: str,
        event: str,
        trigger_event: GameEvent | None = None,
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
            result = self._execute_callback(current_state, callback, detail, trigger_event)
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
        for task in self.rules.status_callback_tasks_for_callback(callback.callback_id):
            if task.parent_task_id:
                continue
            result = self._execute_task(current_state, callback, task, detail, trigger_event)
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
    ) -> StatusCallbackExecutionResult:
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
            return self._execute_damage_emissions(state, callback, task, detail, tuple(damage_emissions))
        if delay_emissions:
            return self._execute_delay_emissions(state, callback, task, detail, tuple(delay_emissions))
        if queue_intents:
            return self._execute_queue_intents(state, callback, task, detail, trigger_event, tuple(queue_intents))
        return StatusCallbackExecutionResult(
            ok=True,
            after_state=state,
            records=(_task_blocked_record(callback, task, detail, "status_callback_task_has_no_executable_runtime_effect"),),
        )

    def _execute_damage_emissions(
        self,
        state: BattleState,
        callback: StatusCallbackIR,
        task: StatusCallbackTaskIR,
        detail: dict[str, JSONValue],
        emissions: tuple[StatusDamageEmissionIR, ...],
    ) -> StatusCallbackExecutionResult:
        current_state = state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = []
        errors: list[str] = []
        for emission in emissions:
            if emission.coverage_status != "executable":
                reason = emission.blocked_reason or f"status_damage_not_executable:{emission.coverage_status}"
                records.append(_status_damage_blocked_record(callback, task, detail, emission, reason))
                errors.append(reason)
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
            damage_result = self.damage.apply_packet(current_state, packet)
            current_state = self.reducer.apply_all(current_state, damage_result.mutations)
            mutations.extend(damage_result.mutations)
            records.extend(damage_result.records)
            errors.extend(damage_result.errors)
        return StatusCallbackExecutionResult(
            ok=not errors,
            after_state=current_state,
            mutations=tuple(mutations),
            records=tuple(records),
            errors=tuple(errors),
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
            actor_id = _resolve_queue_alias(detail, trigger_event, intent.actor_target_alias)
            target_id = _resolve_queue_alias(detail, trigger_event, intent.ability_target_alias)
            if not actor_id or actor_id not in current_state.units:
                reason = f"queue_actor_not_resolved:{intent.actor_target_alias or 'missing'}"
                records.append(_queue_intent_blocked_record(callback, task, detail, intent, reason))
                errors.append(reason)
                continue
            target_ids = (target_id,) if target_id and target_id in current_state.units else ()
            if intent.ability_target_alias and not target_ids:
                reason = f"queue_target_not_resolved:{intent.ability_target_alias}"
                records.append(_queue_intent_blocked_record(callback, task, detail, intent, reason))
                errors.append(reason)
                continue
            queue_name = intent.queue_kind
            source_trace = {
                "queue_intent_source": intent.source.to_json(),
                "status_callback_source": callback.source.to_json(),
                "status_task_source": task.source.to_json(),
                "status_instance_source": _json_dict(detail.get("source_trace")),
            }
            entry = QueueEntry(
                entry_id=f"queue_entry:{intent.queue_intent_id}:{len(current_state.queues.get(queue_name, ()))}",
                queue_name=queue_name,
                queue_kind=intent.queue_kind,
                queue_intent_id=intent.queue_intent_id,
                actor_id=actor_id,
                action_or_ability_ref=intent.action_ref_or_ability_name,
                target_ids=target_ids,
                priority_source=intent.priority_source,
                source_trace=source_trace,
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
                    "admission_result": "executable",
                    "target_resolution": {
                        "actor_target_alias": intent.actor_target_alias or "",
                        "ability_target_alias": intent.ability_target_alias or "",
                        "actor_id": actor_id,
                        "target_ids": list(target_ids),
                    },
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
                        "drain_candidate": False,
                        "drain_blocked_reason": "queue_drain_not_admitted_v0_240",
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
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="break_dot_tick_blocked",
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
            "numeric_evaluation": evaluation.to_json() if evaluation else {},
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
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="status_callback_task_blocked",
        source="status_callback_system",
        process_only=True,
        payload={
            "reason": reason,
            "callback_id": callback.callback_id,
            "task_id": task.task_id,
            "opcode": task.opcode,
            "modifier_name": callback.modifier_name,
            "event": callback.event,
            "blocking_dependency": reason,
        },
        trace={
            "status_task_source": task.source.to_json(),
            "status_callback_source": callback.source.to_json(),
            "status_instance_source": _json_dict(detail.get("source_trace")),
        },
    ).to_json()


def _json_dict(value: object) -> dict[str, JSONValue]:
    return value if isinstance(value, dict) else {}
