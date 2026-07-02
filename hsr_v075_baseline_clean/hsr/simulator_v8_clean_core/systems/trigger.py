from __future__ import annotations

from dataclasses import dataclass, field

from ..core.model import ActionCommand, BattleState, GameEvent, JSONValue, Mutation, RNGEvent, TargetResolution
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..rules.evaluator import EvaluationContext, RuleEvaluator
from ..rules.ir import ActionDefinitionIR, ConditionIR, TriggerIR
from ..rules.rulebook import RuleBook
from .dynamic_values import binding_source_from_store, status_binding_sources
from .effect import EffectExecutionContext, EffectRegistry, EffectResult


@dataclass(frozen=True)
class TriggerWindowRecord:
    canonical_window: str
    tbgd_event: str
    status_instance_id: str | None = None
    status_id: str | None = None
    modifier_name: str | None = None
    owner_id: str | None = None
    trigger_id: str | None = None
    condition_results: tuple[dict[str, JSONValue], ...] = ()
    effect_results: tuple[dict[str, JSONValue], ...] = ()
    skipped_reason: str = ""
    blocked_reason: str = ""
    mutation_count: int = 0
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "canonical_window": self.canonical_window,
            "tbgd_event": self.tbgd_event,
            "status_instance_id": self.status_instance_id,
            "status_id": self.status_id,
            "modifier_name": self.modifier_name,
            "owner_id": self.owner_id,
            "trigger_id": self.trigger_id,
            "condition_results": list(self.condition_results),
            "effect_results": list(self.effect_results),
            "skipped_reason": self.skipped_reason,
            "blocked_reason": self.blocked_reason,
            "mutation_count": self.mutation_count,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class TriggerWindowResult:
    after_state: BattleState
    mutations: tuple[Mutation, ...] = ()
    events: tuple[GameEvent, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    trigger_windows: tuple[dict[str, JSONValue], ...] = ()


class TriggerSystem:
    def __init__(
        self,
        rules: RuleBook,
        effect_registry: EffectRegistry,
        evaluator: RuleEvaluator | None = None,
        reducer: MutationReducer | None = None,
    ) -> None:
        self.rules = rules
        self.effect_registry = effect_registry
        self.evaluator = evaluator or RuleEvaluator()
        self.reducer = reducer or MutationReducer()

    def match(self, rules: RuleBook, event: GameEvent) -> tuple[str, ...]:
        return tuple(trigger.trigger_id for trigger in rules.triggers_for_event(event.event_type))

    def execute_status_window(
        self,
        state: BattleState,
        *,
        canonical_window: str,
        tbgd_event: str,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        target_resolution: TargetResolution,
        enabled: bool,
        skipped_reason: str = "",
    ) -> TriggerWindowResult:
        if not enabled:
            return self._skipped_window(state, canonical_window, tbgd_event, skipped_reason or "window_disabled")

        current = state
        mutations: list[Mutation] = []
        rng_events: list[RNGEvent] = []
        records: list[dict[str, JSONValue]] = []
        window_records: list[dict[str, JSONValue]] = []
        primary_target = target_resolution.selected[0] if target_resolution.selected else None
        selected_targets = target_resolution.selected
        status_trigger_count = 0

        for unit_id, detail in _iter_status_details(current):
            owner_id = str(detail.get("owner_id") or unit_id)
            modifier_name = str(detail.get("modifier_name") or "")
            trigger_ids = _trigger_ids_for_event(detail, tbgd_event)
            if not trigger_ids:
                continue
            for trigger_id in trigger_ids:
                scope_ok, scope_reason = _status_scope_ok(
                    detail,
                    unit_id=unit_id,
                    command=command,
                    primary_target=primary_target,
                )
                if not scope_ok:
                    record = _window_record(
                        canonical_window,
                        tbgd_event,
                        detail,
                        trigger_id=trigger_id,
                        skipped_reason=scope_reason,
                        metadata=_window_metadata(
                            command=command,
                            action_definition=action_definition,
                            primary_target=primary_target,
                            selected_targets=selected_targets,
                        ),
                    )
                    self._append_process_record(records, window_records, record)
                    continue
                status_trigger_count += 1
                trigger = self.rules.trigger(trigger_id)
                if trigger is None:
                    record = _window_record(
                        canonical_window,
                        tbgd_event,
                        detail,
                        trigger_id=trigger_id,
                        blocked_reason="missing_trigger",
                        metadata=_window_metadata(
                            command=command,
                            action_definition=action_definition,
                            primary_target=primary_target,
                            selected_targets=selected_targets,
                        ),
                    )
                    self._append_process_record(records, window_records, record)
                    continue

                condition_results, blocked_reason = self._evaluate_conditions(
                    trigger,
                    state=current,
                    status_detail=detail,
                    command=command,
                    action_definition=action_definition,
                    owner_id=owner_id,
                    primary_target=primary_target,
                    canonical_window=canonical_window,
                    tbgd_event=tbgd_event,
                )
                if blocked_reason:
                    record = _window_record(
                        canonical_window,
                        tbgd_event,
                        detail,
                        trigger_id=trigger.trigger_id,
                        condition_results=tuple(condition_results),
                        blocked_reason=blocked_reason,
                        metadata=_window_metadata(
                            command=command,
                            action_definition=action_definition,
                            primary_target=primary_target,
                            selected_targets=selected_targets,
                        ),
                    )
                    self._append_process_record(records, window_records, record)
                    continue

                effect_results: list[dict[str, JSONValue]] = []
                trigger_mutation_count = 0
                for effect_index, effect_id in enumerate(trigger.effects):
                    effect = self.rules.effect(effect_id)
                    if effect is None:
                        effect_result_json = {
                            "effect_id": effect_id,
                            "ok": False,
                            "unsupported": ["missing_effect"],
                            "mutation_count": 0,
                        }
                        effect_results.append(effect_result_json)
                        records.append(
                            SettlementRecord(
                                record_type="effect_unsupported",
                                source="trigger_system",
                                process_only=True,
                                payload=effect_result_json,
                                trace=_effect_trace(
                                    trigger,
                                    effect_id,
                                    detail,
                                    canonical_window=canonical_window,
                                    tbgd_event=tbgd_event,
                                ),
                            ).to_json()
                        )
                        continue

                    result = self.effect_registry.execute(
                        effect,
                        EffectExecutionContext(
                            state=current,
                            caster_id=command.actor_id,
                            source_id=f"trigger:{canonical_window}:{trigger.trigger_id}:{effect_index}",
                            owner_id=owner_id,
                            param_entity_id=primary_target or command.actor_id,
                            current_action_target_id=primary_target,
                            target_resolution=target_resolution,
                            event_payload=_condition_event_payload(
                                command=command,
                                action_definition=action_definition,
                                primary_target=primary_target,
                                canonical_window=canonical_window,
                                tbgd_event=tbgd_event,
                            ),
                        ),
                    )
                    current = self.reducer.apply_all(current, result.mutations)
                    mutations.extend(result.mutations)
                    rng_events.extend(result.rng_events)
                    records.extend(result.records)
                    if result.unsupported and not result.records:
                        records.append(
                            _unsupported_effect_record(
                                trigger,
                                effect.effect_id,
                                result,
                                detail,
                                canonical_window=canonical_window,
                                tbgd_event=tbgd_event,
                            )
                        )
                    trigger_mutation_count += len(result.mutations)
                    effect_results.append(
                        {
                            "effect_id": effect.effect_id,
                            "opcode": effect.opcode,
                            "ok": not result.unsupported,
                            "unsupported": list(result.unsupported),
                            "mutation_count": len(result.mutations),
                            "record_count": len(result.records),
                        }
                    )

                record = _window_record(
                    canonical_window,
                    tbgd_event,
                    detail,
                    trigger_id=trigger.trigger_id,
                    condition_results=tuple(condition_results),
                    effect_results=tuple(effect_results),
                    mutation_count=trigger_mutation_count,
                    metadata=_window_metadata(
                        command=command,
                        action_definition=action_definition,
                        primary_target=primary_target,
                        selected_targets=selected_targets,
                    ),
                )
                self._append_process_record(records, window_records, record)

        if not window_records:
            record = TriggerWindowRecord(
                canonical_window=canonical_window,
                tbgd_event=tbgd_event,
                skipped_reason="no_status_local_triggers",
                metadata=_window_metadata(
                    command=command,
                    action_definition=action_definition,
                    primary_target=primary_target,
                    selected_targets=selected_targets,
                ),
            )
            self._append_process_record(records, window_records, record)

        events = (
            GameEvent(
                event_type="trigger.window",
                source_id=command.actor_id,
                target_id=primary_target,
                event_id=f"event:{state.event_index}:{canonical_window}",
                window=canonical_window,
                process_only=True,
                payload={
                    "canonical_window": canonical_window,
                    "tbgd_event": tbgd_event,
                    "trigger_count": status_trigger_count,
                    "mutation_count": len(mutations),
                },
            ),
        )
        return TriggerWindowResult(
            after_state=current,
            mutations=tuple(mutations),
            events=events,
            rng_events=tuple(rng_events),
            records=tuple(records),
            trigger_windows=tuple(window_records),
        )

    def _evaluate_conditions(
        self,
        trigger: TriggerIR,
        *,
        state: BattleState,
        status_detail: dict[str, JSONValue],
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        owner_id: str,
        primary_target: str | None,
        canonical_window: str,
        tbgd_event: str,
    ) -> tuple[list[dict[str, JSONValue]], str]:
        results: list[dict[str, JSONValue]] = []
        for condition_id in trigger.conditions:
            condition = self.rules.condition(condition_id)
            if condition is None:
                results.append({"condition_id": condition_id, "result": None, "reason": "missing_condition"})
                return results, f"blocked_condition:{condition_id}:missing"
            result = self.evaluator.evaluate_condition_result(
                condition,
                EvaluationContext(
                    state=state,
                    actor_id=command.actor_id,
                    target_id=primary_target,
                    owner_id=owner_id,
                    param_entity_id=primary_target or command.actor_id,
                    current_action_target_id=primary_target,
                    status_detail=status_detail,
                    event_payload=_condition_event_payload(
                        command=command,
                        action_definition=action_definition,
                        primary_target=primary_target,
                        canonical_window=canonical_window,
                        tbgd_event=tbgd_event,
                    ),
                    binding_sources=_condition_binding_sources(state, command.actor_id, owner_id, primary_target),
                ),
            )
            results.append(result.to_json())
            if result.ok and result.result is True:
                continue
            if result.ok and result.result is False:
                return results, f"blocked_condition:{condition.condition_id}:false"
            return results, f"blocked_condition:{condition.condition_id}:{result.reason}"
        return results, ""

    def _skipped_window(
        self,
        state: BattleState,
        canonical_window: str,
        tbgd_event: str,
        skipped_reason: str,
    ) -> TriggerWindowResult:
        record = TriggerWindowRecord(
            canonical_window=canonical_window,
            tbgd_event=tbgd_event,
            skipped_reason=skipped_reason,
        )
        record_json = record.to_json()
        return TriggerWindowResult(
            after_state=state,
            records=(
                SettlementRecord(
                    record_type="trigger_window",
                    source="trigger_system",
                    process_only=True,
                    payload=record_json,
                ).to_json(),
            ),
            trigger_windows=(record_json,),
        )

    def _append_process_record(
        self,
        records: list[dict[str, JSONValue]],
        window_records: list[dict[str, JSONValue]],
        record: TriggerWindowRecord,
    ) -> None:
        record_json = record.to_json()
        window_records.append(record_json)
        records.append(
            SettlementRecord(
                record_type="trigger_window",
                source="trigger_system",
                process_only=True,
                payload=record_json,
                trace={"trigger_id": record.trigger_id} if record.trigger_id else {},
            ).to_json()
        )


def _iter_status_details(state: BattleState) -> tuple[tuple[str, dict[str, JSONValue]], ...]:
    pairs: list[tuple[str, dict[str, JSONValue]]] = []
    for unit_id, unit in sorted(state.units.items()):
        details = unit.flags.get("status_details", ())
        if not isinstance(details, (list, tuple)):
            continue
        for detail in details:
            if isinstance(detail, dict):
                pairs.append((unit_id, detail))
    return tuple(pairs)


def _trigger_ids_for_event(detail: dict[str, JSONValue], tbgd_event: str) -> tuple[str, ...]:
    trigger_ids_by_event = detail.get("trigger_ids_by_event")
    if not isinstance(trigger_ids_by_event, dict):
        return ()
    trigger_ids = trigger_ids_by_event.get(tbgd_event, ())
    if not isinstance(trigger_ids, (list, tuple)):
        return ()
    return tuple(str(trigger_id) for trigger_id in trigger_ids if isinstance(trigger_id, str))


def _condition_result_json(condition: ConditionIR, result: bool | None) -> dict[str, JSONValue]:
    if result is True:
        reason = "condition_true"
    elif result is False:
        reason = "condition_false"
    else:
        reason = "condition_unsupported"
    return {
        "condition_id": condition.condition_id,
        "opcode": condition.opcode,
        "coverage_status": condition.coverage_status,
        "result": result,
        "reason": reason,
    }


def _condition_binding_sources(
    state: BattleState,
    actor_id: str,
    owner_id: str,
    primary_target: str | None,
) -> tuple[dict[str, JSONValue], ...]:
    unit_ids = tuple(
        unit_id
        for unit_id in (owner_id, actor_id, primary_target)
        if isinstance(unit_id, str) and unit_id
    )
    return (*status_binding_sources(state, unit_ids), binding_source_from_store(state.global_flags.get("dynamic_value_store")))


def _window_record(
    canonical_window: str,
    tbgd_event: str,
    detail: dict[str, JSONValue],
    *,
    trigger_id: str,
    condition_results: tuple[dict[str, JSONValue], ...] = (),
    effect_results: tuple[dict[str, JSONValue], ...] = (),
    skipped_reason: str = "",
    blocked_reason: str = "",
    mutation_count: int = 0,
    metadata: dict[str, JSONValue] | None = None,
) -> TriggerWindowRecord:
    return TriggerWindowRecord(
        canonical_window=canonical_window,
        tbgd_event=tbgd_event,
        status_instance_id=_optional_str(detail.get("instance_id")),
        status_id=_optional_str(detail.get("status_id")),
        modifier_name=_optional_str(detail.get("modifier_name")),
        owner_id=_optional_str(detail.get("owner_id")),
        trigger_id=trigger_id,
        condition_results=condition_results,
        effect_results=effect_results,
        skipped_reason=skipped_reason,
        blocked_reason=blocked_reason,
        mutation_count=mutation_count,
        metadata=metadata or {},
    )


def _unsupported_effect_record(
    trigger: TriggerIR,
    effect_id: str,
    result: EffectResult,
    detail: dict[str, JSONValue],
    *,
    canonical_window: str,
    tbgd_event: str,
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="effect_unsupported",
        source="trigger_system",
        process_only=True,
        payload={
            "trigger_id": trigger.trigger_id,
            "effect_id": effect_id,
            "unsupported": list(result.unsupported),
            "canonical_window": canonical_window,
            "tbgd_event": tbgd_event,
            "status_instance_id": _optional_str(detail.get("instance_id")),
            "modifier_name": _optional_str(detail.get("modifier_name")),
        },
        trace=_effect_trace(
            trigger,
            effect_id,
            detail,
            canonical_window=canonical_window,
            tbgd_event=tbgd_event,
        ),
    ).to_json()


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _status_scope_ok(
    detail: dict[str, JSONValue],
    *,
    unit_id: str,
    command: ActionCommand,
    primary_target: str | None,
) -> tuple[bool, str]:
    owner_id = _optional_str(detail.get("owner_id")) or unit_id
    if owner_id == command.actor_id:
        return True, ""
    if primary_target is not None and owner_id == primary_target:
        return True, ""
    return False, "scope_mismatch:status_owner_is_not_actor_or_primary_target"


def _condition_event_payload(
    *,
    command: ActionCommand,
    action_definition: ActionDefinitionIR,
    primary_target: str | None,
    canonical_window: str,
    tbgd_event: str,
) -> dict[str, JSONValue]:
    payload: dict[str, JSONValue] = {
        "SkillType": action_definition.skill_effect,
        "AttackType": action_definition.attack_type,
        "canonical_window": canonical_window,
        "tbgd_event": tbgd_event,
        "action_id": command.action_id,
        "action_level": command.action_level,
        "actor_id": command.actor_id,
        "primary_target_id": primary_target,
        "attack_type": action_definition.attack_type,
        "damage_kind": action_definition.damage_kind,
        "damage_formula_family": action_definition.damage_formula_family,
        "skill_effect": action_definition.skill_effect,
    }
    for key in ("rng_choices", "rng_mode", "target_random_choices"):
        value = command.metadata.get(key)
        if isinstance(value, (dict, str)):
            payload[key] = value
    return payload


def _window_metadata(
    *,
    command: ActionCommand,
    action_definition: ActionDefinitionIR,
    primary_target: str | None,
    selected_targets: tuple[str, ...],
) -> dict[str, JSONValue]:
    is_multi_target = len(selected_targets) > 1
    return {
        "actor_id": command.actor_id,
        "primary_target_id": primary_target,
        "primary_action_target_id": primary_target,
        "selected_target_ids": list(selected_targets),
        "selected_target_count": len(selected_targets),
        "multi_target_scope_partial": is_multi_target,
        "per_hit_target_context_available": True,
        "per_hit_listener_admission_partial": is_multi_target,
        "per_hit_target_context_not_implemented": False,
        "action_id": command.action_id,
        "action_level": command.action_level,
        "SkillType": action_definition.skill_effect,
        "AttackType": action_definition.attack_type,
        "damage_kind": action_definition.damage_kind,
        "damage_formula_family": action_definition.damage_formula_family,
    }


def _effect_trace(
    trigger: TriggerIR,
    effect_id: str,
    detail: dict[str, JSONValue],
    *,
    canonical_window: str,
    tbgd_event: str,
) -> dict[str, JSONValue]:
    return {
        "canonical_window": canonical_window,
        "tbgd_event": tbgd_event,
        "trigger_id": trigger.trigger_id,
        "trigger_source": trigger.source.to_json(),
        "effect_id": effect_id,
        "status_instance_id": _optional_str(detail.get("instance_id")),
        "status_id": _optional_str(detail.get("status_id")),
        "modifier_name": _optional_str(detail.get("modifier_name")),
        "owner_id": _optional_str(detail.get("owner_id")),
        "status_source_trace": detail.get("source_trace") if isinstance(detail.get("source_trace"), dict) else {},
    }
