from __future__ import annotations

from dataclasses import dataclass

from ..core.model import ActionCommand, BattleState, GameEvent, JSONValue, Mutation, TargetResolution
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..rules.evaluator import EvaluationContext, RuleEvaluator
from ..rules.ir import AbilityPhaseIR, AbilityTaskIR, ActionDefinitionIR, IRSource
from ..rules.rulebook import RuleBook
from .dynamic_values import (
    binding_source_from_store,
    character_skill_param_binding_sources,
    status_binding_sources,
    store_from_state,
)
from .effect import EffectExecutionContext, EffectRegistry


@dataclass(frozen=True)
class AbilityTaskExecutionResult:
    after_state: BattleState
    mutations: tuple[Mutation, ...] = ()
    events: tuple[GameEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    task_records: tuple[dict[str, JSONValue], ...] = ()


class AbilityTaskSystem:
    """Executes Canonical IR ability tasks conservatively."""

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

    def execute_callback(
        self,
        state: BattleState,
        *,
        phases: tuple[AbilityPhaseIR, ...],
        callback_kind: str,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        target_resolution: TargetResolution,
    ) -> AbilityTaskExecutionResult:
        current = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        records: list[dict[str, JSONValue]] = []
        task_records: list[dict[str, JSONValue]] = []
        primary_target = target_resolution.selected[0] if target_resolution.selected else None

        for phase in phases:
            tasks = {
                task.task_id: task
                for task in self.rules.ability_tasks_for_phase(phase.phase_id)
                if task.callback_kind == callback_kind
            }
            roots = tuple(
                sorted(
                    (task for task in tasks.values() if not task.parent_task_id),
                    key=lambda item: (item.task_index, item.task_path, item.task_id),
                )
            )
            for task in roots:
                current, task_mutations, task_records_for_root = self._execute_task(
                    current,
                    task,
                    tasks,
                    command=command,
                    action_definition=action_definition,
                    primary_target=primary_target,
                    target_resolution=target_resolution,
                )
                mutations.extend(task_mutations)
                records.extend(task_records_for_root)
                task_records.extend(
                    record.get("payload", {})
                    for record in task_records_for_root
                    if isinstance(record, dict) and record.get("record_type") == "ability_task"
                )

        if task_records:
            events.append(
                GameEvent(
                    event_type="ability_task.callback",
                    source_id=command.actor_id,
                    target_id=primary_target,
                    event_id=f"event:{state.event_index}:ability_task:{callback_kind}",
                    window=callback_kind,
                    process_only=True,
                    payload={
                        "callback_kind": callback_kind,
                        "task_record_count": len(task_records),
                        "mutation_count": len(mutations),
                    },
                )
            )
        return AbilityTaskExecutionResult(
            after_state=current,
            mutations=tuple(mutations),
            events=tuple(events),
            records=tuple(records),
            task_records=tuple(task_records),
        )

    def execute_standalone(
        self,
        state: BattleState,
        *,
        phases: tuple[AbilityPhaseIR, ...],
        actor_id: str,
        target_ids: tuple[str, ...],
        queue_entry: dict[str, JSONValue],
        queue_resolution: dict[str, JSONValue],
    ) -> AbilityTaskExecutionResult:
        if not phases:
            return AbilityTaskExecutionResult(
                after_state=state,
                records=(
                    SettlementRecord(
                        record_type="standalone_ability_blocked",
                        source="ability_task_system",
                        process_only=True,
                        payload={
                            "reason": "standalone_ability_phases_missing",
                            "queue_entry": queue_entry,
                            "queue_resolution": queue_resolution,
                        },
                        trace={},
                    ).to_json(),
                ),
            )
        ability_name = phases[0].ability_name
        action_id = f"standalone_ability:{ability_name}"
        action_definition = ActionDefinitionIR(
            definition_id=f"standalone_action_def:{ability_name}",
            action_id=action_id,
            level=0,
            attack_type="StandaloneAbility",
            skill_effect="standalone_ability",
            target_mode="single" if target_ids else "none",
            bp_need=0.0,
            bp_add=0.0,
            sp_base=0.0,
            sp_multiple_ratio=0.0,
            param_list=(),
            show_stance_list=(),
            show_damage_list=(),
            stance_damage_type=None,
            source=phases[0].source if phases else IRSource("", "", ""),
            coverage_status="executable",
            damage_kind="none",
            damage_formula_family="none",
            element_type=None,
            source_mode="queue_standalone",
        )
        command = ActionCommand(
            actor_id=actor_id,
            action_id=action_id,
            action_level=0,
            target_ids=target_ids,
            source="queue",
            queue_name=str(queue_entry.get("queue_name") or ""),
            metadata={
                "parent_queue_entry_id": str(queue_entry.get("entry_id") or ""),
                "queue_intent_id": str(queue_entry.get("queue_intent_id") or ""),
                "queue_resolution_id": str(queue_resolution.get("queue_resolution_id") or ""),
                "standalone_ability_name": ability_name,
            },
        )
        target_resolution = TargetResolution(
            requested=target_ids,
            legal=target_ids,
            selected=target_ids,
            rejected=(),
            reason="queue_standalone_targets_from_queue_entry",
            source="queue_resolution",
            metadata={
                "queue_entry_id": str(queue_entry.get("entry_id") or ""),
                "queue_resolution_id": str(queue_resolution.get("queue_resolution_id") or ""),
            },
        )
        current = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        records: list[dict[str, JSONValue]] = [
            SettlementRecord(
                record_type="standalone_ability_execution",
                source="ability_task_system",
                process_only=True,
                payload={
                    "ability_name": ability_name,
                    "phase_ids": [phase.phase_id for phase in phases],
                    "queue_entry": queue_entry,
                    "queue_resolution": queue_resolution,
                },
                trace={"standalone_phase_source": phases[0].source.to_json()},
            ).to_json()
        ]
        task_records: list[dict[str, JSONValue]] = []
        for callback_kind in ("OnStart", "OnAttack", "OnHit", "OnEnd"):
            result = self.execute_callback(
                current,
                phases=phases,
                callback_kind=callback_kind,
                command=command,
                action_definition=action_definition,
                target_resolution=target_resolution,
            )
            current = result.after_state
            mutations.extend(result.mutations)
            events.extend(result.events)
            records.extend(result.records)
            task_records.extend(result.task_records)
        return AbilityTaskExecutionResult(
            after_state=current,
            mutations=tuple(mutations),
            events=tuple(events),
            records=tuple(records),
            task_records=tuple(task_records),
        )

    def _execute_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        tasks: dict[str, AbilityTaskIR],
        *,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        primary_target: str | None,
        target_resolution: TargetResolution,
    ) -> tuple[BattleState, list[Mutation], list[dict[str, JSONValue]]]:
        if task.opcode == "PredicateTaskList":
            return self._execute_predicate_task(
                state,
                task,
                tasks,
                command=command,
                action_definition=action_definition,
                primary_target=primary_target,
                target_resolution=target_resolution,
            )
        if task.coverage_status != "executable":
            record = _task_process_record(task, ok=False, blocked_reason=task.blocked_reason or "task_not_executable")
            return state, [], [record]
        if not task.effect_id:
            record = _task_process_record(task, ok=False, blocked_reason="task_has_no_effect")
            return state, [], [record]
        effect = self.rules.effect(task.effect_id)
        if effect is None:
            record = _task_process_record(task, ok=False, blocked_reason="missing_effect")
            return state, [], [record]
        effect_coverage = self.effect_registry.coverage(effect)
        if effect_coverage != "executable":
            record = _task_process_record(
                task,
                ok=False,
                blocked_reason=f"effect_not_executable:{effect_coverage}",
                effect_id=effect.effect_id,
                effect_opcode=effect.opcode,
                effect_coverage=effect_coverage,
            )
            return state, [], [record]

        result = self.effect_registry.execute(
            effect,
            EffectExecutionContext(
                state=state,
                caster_id=command.actor_id,
                source_id=f"ability_task:{task.task_id}",
                owner_id=command.actor_id,
                param_entity_id=primary_target or command.actor_id,
                current_action_target_id=primary_target,
                binding_sources=_binding_sources(
                    self.rules,
                    state,
                    command.actor_id,
                    primary_target,
                    action_level=command.action_level,
                    current_action_trigger_key=_action_trigger_key(action_definition),
                ),
            ),
        )
        after = self.reducer.apply_all(state, result.mutations)
        records = list(result.records)
        records.append(
            _task_process_record(
                task,
                ok=not result.unsupported,
                blocked_reason=",".join(result.unsupported),
                effect_id=effect.effect_id,
                effect_opcode=effect.opcode,
                effect_coverage=effect_coverage,
                mutation_count=len(result.mutations),
                record_count=len(result.records),
            )
        )
        return after, list(result.mutations), records

    def _execute_predicate_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        tasks: dict[str, AbilityTaskIR],
        *,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        primary_target: str | None,
        target_resolution: TargetResolution,
    ) -> tuple[BattleState, list[Mutation], list[dict[str, JSONValue]]]:
        condition = self.rules.condition(task.condition_id) if task.condition_id else None
        if condition is None:
            record = _task_process_record(task, ok=False, blocked_reason="missing_predicate_condition")
            return state, [], [record]
        result = self.evaluator.evaluate_condition_result(
            condition,
            EvaluationContext(
                state=state,
                actor_id=command.actor_id,
                target_id=primary_target,
                owner_id=command.actor_id,
                param_entity_id=primary_target or command.actor_id,
                current_action_target_id=primary_target,
                event_payload=_event_payload(command, action_definition, primary_target, target_resolution),
                binding_sources=_binding_sources(
                    self.rules,
                    state,
                    command.actor_id,
                    primary_target,
                    action_level=command.action_level,
                    current_action_trigger_key=_action_trigger_key(action_definition),
                ),
            ),
        )
        if not result.ok or result.result is None:
            record = _task_process_record(
                task,
                ok=False,
                blocked_reason=f"blocked_condition:{condition.condition_id}:{result.reason}",
                condition_result=result.to_json(),
            )
            return state, [], [record]

        selected_child_ids = task.success_task_ids if result.result else task.failed_task_ids
        current = state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = [
            _task_process_record(
                task,
                ok=True,
                condition_result=result.to_json(),
                selected_child_ids=selected_child_ids,
            )
        ]
        for child_id in selected_child_ids:
            child = tasks.get(child_id)
            if child is None:
                records.append(_task_process_record(task, ok=False, blocked_reason=f"missing_child_task:{child_id}"))
                continue
            current, child_mutations, child_records = self._execute_task(
                current,
                child,
                tasks,
                command=command,
                action_definition=action_definition,
                primary_target=primary_target,
                target_resolution=target_resolution,
            )
            mutations.extend(child_mutations)
            records.extend(child_records)
        return current, mutations, records


def _task_process_record(
    task: AbilityTaskIR,
    *,
    ok: bool,
    blocked_reason: str = "",
    effect_id: str = "",
    effect_opcode: str = "",
    effect_coverage: str = "",
    condition_result: dict[str, JSONValue] | None = None,
    selected_child_ids: tuple[str, ...] = (),
    mutation_count: int = 0,
    record_count: int = 0,
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="ability_task",
        source="ability_task_system",
        process_only=True,
        payload={
            "task_id": task.task_id,
            "phase_id": task.phase_id,
            "ability_name": task.ability_name,
            "callback_kind": task.callback_kind,
            "task_path": task.task_path,
            "branch": task.branch,
            "opcode": task.opcode,
            "ok": ok,
            "coverage_status": task.coverage_status,
            "blocked_reason": blocked_reason,
            "effect_id": effect_id or task.effect_id,
            "effect_opcode": effect_opcode,
            "effect_coverage": effect_coverage,
            "condition_id": task.condition_id,
            "condition_result": condition_result or {},
            "selected_child_ids": list(selected_child_ids),
            "mutation_count": mutation_count,
            "record_count": record_count,
        },
        trace=task.source.to_json(),
    ).to_json()


def _event_payload(
    command: ActionCommand,
    action_definition: ActionDefinitionIR,
    primary_target: str | None,
    target_resolution: TargetResolution,
) -> dict[str, JSONValue]:
    return {
        "SkillType": action_definition.skill_effect,
        "skill_type": action_definition.skill_effect,
        "attack_type": action_definition.attack_type,
        "damage_kind": action_definition.damage_kind,
        "damage_formula_family": action_definition.damage_formula_family,
        "action_id": action_definition.action_id,
        "action_level": action_definition.level,
        "actor_id": command.actor_id,
        "primary_target_id": primary_target,
        "selected_target_ids": list(target_resolution.selected),
    }


def _binding_sources(
    rules: RuleBook,
    state: BattleState,
    actor_id: str,
    primary_target: str | None,
    *,
    action_level: int | None = None,
    current_action_trigger_key: str | None = None,
) -> tuple[dict[str, JSONValue], ...]:
    unit_ids = tuple(dict.fromkeys(unit_id for unit_id in (actor_id, primary_target) if unit_id))
    return (
        binding_source_from_store(store_from_state(state)),
        *character_skill_param_binding_sources(
            rules,
            state,
            (actor_id,),
            action_level=action_level,
            current_action_trigger_key=current_action_trigger_key,
        ),
        *status_binding_sources(state, unit_ids),
    )


def _action_trigger_key(action_definition: ActionDefinitionIR) -> str:
    value = action_definition.source.evidence.get("skill_trigger_key")
    return str(value) if isinstance(value, str) else ""
