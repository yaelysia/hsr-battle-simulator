from __future__ import annotations

from dataclasses import dataclass, replace

from ..core.model import ActionCommand, BattleState, GameEvent, JSONValue, Mutation, RNGEvent, TargetResolution
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..core.transition_outcome import ExecutionNodeResult
from ..rules.evaluator import EvaluationContext, NumericEvaluationContext, RuleEvaluator
from ..rules.ir import AbilityPhaseIR, AbilityTaskIR, ActionDefinitionIR, IRSource, TargetExpressionNodeIR
from ..rules.rulebook import RuleBook
from .damage import DamagePacket, DamageSourceFrame, DamageSystem, DamageWindowLedger
from .dynamic_values import (
    binding_source_from_store,
    character_skill_param_binding_sources,
    status_binding_sources,
    store_from_state,
)
from .effect import EffectExecutionContext, EffectRegistry
from .event_dispatch import EventDispatchResult, EventDispatchSystem
from .action_event_contract import damage_listener_window_event
from .summon import SummonSystem
from .toughness import ToughnessPacket, ToughnessSystem
from .ability_task_contract import (
    ability_task_runtime_blocked_reason,
    is_process_only_ability_task,
)
from .target import TargetSystem


@dataclass(frozen=True)
class AbilityTaskExecutionResult:
    after_state: BattleState
    mutations: tuple[Mutation, ...] = ()
    events: tuple[GameEvent, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    task_records: tuple[dict[str, JSONValue], ...] = ()
    node_results: tuple[ExecutionNodeResult, ...] = ()


class AbilityTaskSystem:
    """Executes Canonical IR ability tasks conservatively."""

    def __init__(
        self,
        rules: RuleBook,
        effect_registry: EffectRegistry,
        evaluator: RuleEvaluator | None = None,
        reducer: MutationReducer | None = None,
        damage: DamageSystem | None = None,
        event_dispatcher: EventDispatchSystem | None = None,
    ) -> None:
        self.rules = rules
        self.effect_registry = effect_registry
        self.evaluator = evaluator or RuleEvaluator()
        self.reducer = reducer or MutationReducer()
        self.damage = damage or DamageSystem(rules)
        self.event_dispatcher = event_dispatcher
        self.toughness = ToughnessSystem(rules)
        self.summons = SummonSystem(rules)
        self.targets = TargetSystem()

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
        rng_events: list[RNGEvent] = []
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
                current, task_mutations, task_events, task_rng_events, task_records_for_root = self._execute_task(
                    current,
                    task,
                    tasks,
                    command=command,
                    action_definition=action_definition,
                    primary_target=primary_target,
                    target_resolution=target_resolution,
                )
                mutations.extend(task_mutations)
                events.extend(task_events)
                rng_events.extend(task_rng_events)
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
            rng_events=tuple(rng_events),
            records=tuple(records),
            task_records=tuple(task_records),
            node_results=_node_results_from_task_records(task_records),
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
        depth: int = 0,
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
                node_results=(
                    ExecutionNodeResult(
                        node_kind="ability_graph",
                        node_id=str(queue_entry.get("entry_id") or "standalone_ability"),
                        status="blocked",
                        reason_code="standalone_ability_phases_missing",
                    ),
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
                "standalone_depth": depth,
                "is_insert_action": True,
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
        rng_events: list[RNGEvent] = []
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
        node_results: list[ExecutionNodeResult] = []
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
            rng_events.extend(result.rng_events)
            records.extend(result.records)
            task_records.extend(result.task_records)
            node_results.extend(result.node_results)
        return AbilityTaskExecutionResult(
            after_state=current,
            mutations=tuple(mutations),
            events=tuple(events),
            rng_events=tuple(rng_events),
            records=tuple(records),
            task_records=tuple(task_records),
            node_results=tuple(node_results),
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
    ) -> tuple[BattleState, list[Mutation], list[GameEvent], list[RNGEvent], list[dict[str, JSONValue]]]:
        admission_reason = ability_task_runtime_blocked_reason(self.rules, task)
        if admission_reason:
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason=admission_reason,
                )
            ]
        if is_process_only_ability_task(task):
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=True,
                    blocked_reason="process_only_ability_task",
                    effect_id=task.effect_id,
                    effect_opcode=task.opcode,
                    effect_coverage="process_only",
                )
            ]
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
        if task.opcode == "LoopExecuteTaskListWithInterval":
            return self._execute_fixed_task_loop(
                state,
                task,
                tasks,
                command=command,
                action_definition=action_definition,
                primary_target=primary_target,
                target_resolution=target_resolution,
            )
        if task.opcode == "TriggerAbility":
            return self._execute_trigger_ability_task(
                state,
                task,
                command=command,
                action_definition=action_definition,
                primary_target=primary_target,
                target_resolution=target_resolution,
            )
        if task.opcode == "SummonMonster":
            return self.execute_summon_monster_task(
                state,
                task,
                command=command,
            )
        if self.rules.damage_emissions_for_task(task.task_id):
            return self._execute_damage_task(
                state,
                task,
                command=command,
                action_definition=action_definition,
                primary_target=primary_target,
                target_resolution=target_resolution,
            )
        if not task.effect_id:
            record = _task_process_record(task, ok=False, blocked_reason="task_has_no_effect")
            return state, [], [], [], [record]
        effect = self.rules.effect(task.effect_id)
        if effect is None:
            record = _task_process_record(task, ok=False, blocked_reason="missing_effect")
            return state, [], [], [], [record]
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
            return state, [], [], [], [record]

        result = self.effect_registry.execute(
            effect,
            EffectExecutionContext(
                state=state,
                caster_id=command.actor_id,
                source_id=f"ability_task:{task.task_id}",
                owner_id=command.actor_id,
                param_entity_id=primary_target or command.actor_id,
                current_action_target_id=primary_target,
                target_resolution=target_resolution,
                event_payload={
                    **_rng_event_payload_from_command(command),
                    "actor_id": command.actor_id,
                    "action_id": command.action_id,
                    "action_level": command.action_level,
                    "task_id": task.task_id,
                    "hit_index": task.task_index,
                    "rng_decision_index": task.task_index,
                    "ability_instance_id": (
                        f"ability_action:{state.event_index}:"
                        f"{command.actor_id}:{command.action_id}:{command.action_level}"
                    ),
                    "operation_event_id": (
                        f"ability_task:{state.event_index}:{command.actor_id}:"
                        f"{command.action_id}:{task.task_id}:"
                        f"{command.metadata.get('ability_task_execution_path', task.task_index)}"
                    ),
                },
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
        return after, list(result.mutations), list(result.events), list(result.rng_events), records

    def _execute_fixed_task_loop(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        tasks: dict[str, AbilityTaskIR],
        *,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        primary_target: str | None,
        target_resolution: TargetResolution,
    ) -> tuple[BattleState, list[Mutation], list[GameEvent], list[RNGEvent], list[dict[str, JSONValue]]]:
        if task.coverage_status != "executable" or task.repeat_count <= 0:
            reason = task.blocked_reason or "fixed_positive_loop_count_required"
            return state, [], [], [], [_task_process_record(task, ok=False, blocked_reason=reason)]
        current = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        records: list[dict[str, JSONValue]] = []
        failure_reason = ""
        for iteration_index in range(task.repeat_count):
            parent_path = str(
                command.metadata.get("ability_task_execution_path") or ""
            )
            iteration_path = (
                f"{parent_path}/{task.task_id}[{iteration_index}]"
                if parent_path
                else f"{task.task_id}[{iteration_index}]"
            )
            iteration_command = replace(
                command,
                metadata={
                    **command.metadata,
                    "ability_task_execution_path": iteration_path,
                    "ability_loop_task_id": task.task_id,
                    "ability_loop_iteration": iteration_index,
                },
            )
            for child_id in task.child_task_ids:
                child = tasks.get(child_id)
                if child is None or child.parent_task_id != task.task_id:
                    failure_reason = f"loop_child_missing_or_mismatched:{child_id}"
                    break
                current, child_mutations, child_events, child_rng_events, child_records = self._execute_task(
                    current,
                    child,
                    tasks,
                    command=iteration_command,
                    action_definition=action_definition,
                    primary_target=primary_target,
                    target_resolution=target_resolution,
                )
                mutations.extend(child_mutations)
                events.extend(child_events)
                rng_events.extend(child_rng_events)
                records.extend(child_records)
                if any(
                    isinstance(record.get("payload"), dict)
                    and record["payload"].get("ok") is False
                    for record in child_records
                    if isinstance(record, dict)
                    and record.get("record_type") == "ability_task"
                ):
                    failure_reason = f"loop_child_incomplete:{child_id}"
                    break
            if failure_reason:
                break
        records.insert(
            0,
            _task_process_record(
                task,
                ok=not failure_reason,
                blocked_reason=failure_reason,
                selected_child_ids=task.child_task_ids,
                mutation_count=len(mutations),
                record_count=len(records),
            ),
        )
        return current, mutations, events, rng_events, records

    def execute_summon_monster_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        *,
        command: ActionCommand,
    ) -> tuple[BattleState, list[Mutation], list[GameEvent], list[RNGEvent], list[dict[str, JSONValue]]]:
        intents = tuple(
            intent
            for intent in self.rules.summon_monster_intents()
            if intent.source_task_id == task.task_id
        )
        if len(intents) != 1:
            reason = "summon_monster_intent_missing" if not intents else "summon_monster_intent_ambiguous"
            return state, [], [], [], [_task_process_record(task, ok=False, blocked_reason=reason)]
        intent = intents[0]
        if intent.coverage_status != "executable":
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason=intent.blocked_reason
                    or f"summon_monster_intent_not_executable:{intent.coverage_status}",
                )
            ]
        if intent.source_task_id != task.task_id or intent.owner_scope != "caster":
            return state, [], [], [], [
                _task_process_record(task, ok=False, blocked_reason="summon_monster_intent_task_binding_mismatch")
            ]
        plan = self.summons.plan_spawn_from_intent(state, intent, owner_id=command.actor_id)
        result = self.summons.apply_spawn(state, plan)
        if not result.plan.ok:
            return state, [], [], [], [
                *result.records,
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason=result.plan.blocked_reason or "summon_monster_spawn_blocked",
                ),
            ]
        reduction = self.reducer.apply_all_result(state, result.mutations)
        if not reduction.ok:
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason=f"summon_monster_reducer_conflict:{reduction.conflicts[0].code}",
                )
            ]
        records = [
            *result.records,
            _task_process_record(
                task,
                ok=True,
                effect_id=task.effect_id,
                effect_opcode=task.opcode,
                effect_coverage="executable",
                mutation_count=len(result.mutations),
                record_count=len(result.records),
            ),
        ]
        return (
            reduction.after_state,
            list(result.mutations),
            list(result.events),
            list(result.rng_events),
            records,
        )

    def _execute_trigger_ability_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        *,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        primary_target: str | None,
        target_resolution: TargetResolution,
    ) -> tuple[BattleState, list[Mutation], list[GameEvent], list[RNGEvent], list[dict[str, JSONValue]]]:
        if task.coverage_status != "executable":
            return state, [], [], [], [_task_process_record(task, ok=False, blocked_reason=task.blocked_reason or "task_not_executable")]
        effect = self.rules.effect(task.effect_id) if task.effect_id else None
        standard = effect.payload.get("standard") if effect is not None else None
        if effect is None or not isinstance(standard, dict):
            return state, [], [], [], [_task_process_record(task, ok=False, blocked_reason="trigger_ability_effect_missing")]
        ability_name = standard.get("ability_name")
        if not isinstance(ability_name, str) or not ability_name:
            return state, [], [], [], [_task_process_record(task, ok=False, blocked_reason="trigger_ability_name_missing", effect_id=effect.effect_id, effect_opcode=effect.opcode)]
        if not command.action_id.startswith("standalone_ability:"):
            action_phase_names = {
                phase.ability_name
                for phase in self.rules.ability_phases_for_action(command.action_id, command.action_level)
            }
            if ability_name in action_phase_names:
                return state, [], [], [], [
                    _task_process_record(
                        task,
                        ok=True,
                        blocked_reason="trigger_ability_child_already_bound_to_action",
                        effect_id=effect.effect_id,
                        effect_opcode=effect.opcode,
                        effect_coverage="executable",
                    )
                ]
        depth = int(command.metadata.get("standalone_depth") or 0)
        if depth >= 4:
            return state, [], [], [], [_task_process_record(task, ok=False, blocked_reason="trigger_ability_depth_limit", effect_id=effect.effect_id, effect_opcode=effect.opcode)]
        graph = self.rules.standalone_ability_graph(task.linked_standalone_graph_id)
        if graph is None or graph.ability_name != ability_name:
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason="standalone_ability_graph_link_missing_or_mismatched",
                    effect_id=effect.effect_id,
                    effect_opcode=effect.opcode,
                )
            ]
        phases = tuple(
            phase
            for phase_id in graph.phase_ids
            if (phase := self.rules.ability_phase(phase_id)) is not None
        )
        result = self.execute_standalone(
            state,
            phases=phases,
            actor_id=command.actor_id,
            target_ids=target_resolution.selected,
            queue_entry={
                "entry_id": command.metadata.get("parent_queue_entry_id") or "",
                "queue_name": command.queue_name,
                "queue_intent_id": command.metadata.get("queue_intent_id") or "",
                "trigger_task_id": task.task_id,
            },
            queue_resolution={
                "queue_resolution_id": command.metadata.get("queue_resolution_id") or "",
                "trigger_task_id": task.task_id,
                "trigger_ability_name": ability_name,
            },
            depth=depth + 1,
        )
        records = list(result.records)
        records.append(
            _task_process_record(
                task,
                ok=not result.errors if hasattr(result, "errors") else True,
                effect_id=effect.effect_id,
                effect_opcode=effect.opcode,
                effect_coverage="executable",
                mutation_count=len(result.mutations),
                record_count=len(result.records),
            )
        )
        return result.after_state, list(result.mutations), list(result.events), list(result.rng_events), records

    def _execute_damage_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        *,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        primary_target: str | None,
        target_resolution: TargetResolution,
    ) -> tuple[BattleState, list[Mutation], list[GameEvent], list[RNGEvent], list[dict[str, JSONValue]]]:
        emissions = tuple(
            emission
            for emission in self.rules.damage_emissions_for_task(task.task_id)
            if emission.action_id == task.action_id and emission.level == task.level
        )
        if not emissions:
            return state, [], [], [], [_task_process_record(task, ok=False, blocked_reason="damage_emission_missing")]
        current = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        records: list[dict[str, JSONValue]] = []
        ledger = DamageWindowLedger()
        sequence_order: list[tuple[str, str]] = []
        sequence_context: dict[
            tuple[str, str],
            dict[str, JSONValue],
        ] = {}

        def dispatch_damage_event(event: GameEvent) -> tuple[str, ...]:
            nonlocal current
            if self.event_dispatcher is None:
                events.append(event)
                return ()
            result: EventDispatchResult = self.event_dispatcher.dispatch_event(
                current,
                event=event,
                damage_window_ledger=ledger,
            )
            current = result.after_state
            mutations.extend(result.mutations)
            events.extend(result.events)
            rng_events.extend(result.rng_events)
            records.extend(result.records)
            return result.errors

        for emission in emissions:
            if emission.coverage_status != "executable":
                records.append(
                    _task_process_record(
                        task,
                        ok=False,
                        blocked_reason=emission.blocked_reason or f"damage_emission_not_executable:{emission.coverage_status}",
                    )
                )
                continue
            profile = self.rules.hit_profile(emission.hit_profile_id)
            if profile is None or profile.coverage_status != "executable":
                records.append(
                    _task_process_record(
                        task,
                        ok=False,
                        blocked_reason="hit_profile_missing_or_not_executable",
                    )
                )
                continue
            ratio_eval = self.evaluator.evaluate_numeric(
                emission.scaling_ratio_expr,
                NumericEvaluationContext(
                    binding_sources=(
                        *_binding_sources(
                            self.rules,
                            current,
                            command.actor_id,
                            primary_target,
                            action_level=command.action_level,
                            current_action_trigger_key=_action_trigger_key(action_definition),
                        ),
                        *_expression_binding_sources(emission.scaling_ratio_expr),
                    ),
                    source_trace=emission.source.to_json(),
                ),
            )
            if not ratio_eval.ok or ratio_eval.value is None:
                records.append(
                    _task_process_record(
                        task,
                        ok=False,
                        blocked_reason=f"damage_scaling_ratio_blocked:{ratio_eval.blocked_reason}",
                    )
                )
                continue
            target_ids = _damage_targets_for_emission(emission.target_group, target_resolution)
            if not target_ids:
                optional_group = emission.target_group == "adjacent"
                records.append(
                    _task_process_record(
                        task,
                        ok=optional_group,
                        blocked_reason=(
                            "damage_optional_target_group_empty"
                            if optional_group
                            else "damage_target_missing"
                        ),
                    )
                )
                continue
            for target_id in target_ids:
                toughness_blocked_reason = ""
                for toughness_emission in self.rules.toughness_emissions_for_task(
                    task.task_id
                ):
                    if toughness_emission.hit_profile_id != profile.hit_profile_id:
                        continue
                    binding_sources = (
                        *_binding_sources(
                            self.rules,
                            current,
                            command.actor_id,
                            primary_target,
                            action_level=command.action_level,
                            current_action_trigger_key=_action_trigger_key(
                                action_definition
                            ),
                        ),
                        *_expression_binding_sources(
                            toughness_emission.toughness_amount_expr
                        ),
                    )
                    toughness_packet = ToughnessPacket(
                        attacker_id=command.actor_id,
                        target_id=target_id,
                        toughness_emission_id=(
                            toughness_emission.toughness_emission_id
                        ),
                        source_task_id=task.task_id,
                        hit_profile_id=profile.hit_profile_id,
                        element_type=toughness_emission.element_type,
                        amount=None,
                        amount_expr=toughness_emission.toughness_amount_expr,
                        target_group=toughness_emission.target_group,
                        coverage_status=toughness_emission.coverage_status,
                        source_trace=toughness_emission.source.to_json(),
                        metadata={
                            "primary_action_target_id": primary_target,
                            "value_binding_sources": list(binding_sources),
                            "ability_task_execution_path": command.metadata.get(
                                "ability_task_execution_path",
                                "",
                            ),
                        },
                    )
                    toughness_result = self.toughness.apply_packet(
                        current,
                        toughness_packet,
                    )
                    records.extend(toughness_result.records)
                    if not toughness_result.ok:
                        toughness_blocked_reason = (
                            toughness_result.errors[0]
                            if toughness_result.errors
                            else "ability_task_toughness_blocked"
                        )
                        break
                    if toughness_result.mutations:
                        toughness_blocked_reason = (
                            "ability_task_toughness_pre_mutation_listener_not_admitted"
                        )
                        break
                if toughness_blocked_reason:
                    records.append(
                        _task_process_record(
                            task,
                            ok=False,
                            blocked_reason=toughness_blocked_reason,
                        )
                    )
                    continue
                execution_path = str(
                    command.metadata.get("ability_task_execution_path") or ""
                )
                is_standalone = (
                    action_definition.source_mode == "queue_standalone"
                )
                damage_source_id = (
                    task.task_id
                    if is_standalone
                    else (
                        f"action:{command.action_id}:"
                        f"level:{command.action_level}"
                    )
                )
                damage_source_kind = (
                    "standalone_ability_damage"
                    if is_standalone
                    else "primary_action_damage"
                )
                damage_sequence_id = (
                    f"{command.action_id}:{task.task_id}"
                    if is_standalone
                    else (
                        f"action:{command.actor_id}:{command.action_id}:"
                        f"level:{command.action_level}:task:{task.task_id}"
                    )
                )
                packet = DamagePacket(
                    attacker_id=command.actor_id,
                    target_id=target_id,
                    attack_type=action_definition.attack_type,
                    damage_formula_family=emission.damage_formula_family,
                    damage_kind="hp_damage",
                    element_type=emission.element_type,
                    action_definition=action_definition,
                    damage_emission_id=emission.damage_emission_id,
                    source_task_id=task.task_id,
                    hit_profile_id=profile.hit_profile_id,
                    scaling_ratio=ratio_eval.value,
                    scaling_basis=emission.scaling_basis_expr,
                    hit_source_trace=profile.source.to_json(),
                    source_trace=emission.source.to_json(),
                    source_frame=DamageSourceFrame(
                        owner_id=command.actor_id,
                        source_id=damage_source_id,
                        source_kind=damage_source_kind,
                        sequence_id=damage_sequence_id,
                        target_id=target_id,
                        can_continue_after_lethal=True,
                        source_trace=emission.source.to_json(),
                    ),
                    metadata={
                        **command.metadata,
                        "SkillType": action_definition.skill_effect,
                        "skill_type": action_definition.skill_effect,
                        "attack_type": action_definition.attack_type,
                        "is_current_skill_active": not is_standalone,
                        "is_insert_action": command.source == "queue",
                        "primary_action_target_id": primary_target,
                        "hit_index": profile.hit_index,
                        "target_group": emission.target_group,
                        "numeric_evaluation": ratio_eval.to_json(),
                        "phase_id": task.phase_id,
                        "derived_event_id": (
                            f"{emission.damage_emission_id}:{execution_path}"
                            if execution_path
                            else emission.damage_emission_id
                        ),
                    },
                )
                sequence_id = (
                    f"{task.task_id}:{execution_path}"
                    if execution_path
                    else task.task_id
                )
                sequence_key = (sequence_id, target_id)
                if (
                    self.event_dispatcher is not None
                    and sequence_key not in sequence_context
                ):
                    before_errors = dispatch_damage_event(
                        damage_listener_window_event(
                            current,
                            command,
                            action_definition,
                            event_type="damage.hit_sequence.before",
                            target_id=target_id,
                            selected_target_ids=target_resolution.selected,
                            primary_target_id=primary_target,
                            source_trace=emission.source.to_json(),
                            damage_custom_name=emission.damage_custom_name,
                            damage_tags=emission.damage_tags,
                            sequence_id=sequence_id,
                        )
                    )
                    if before_errors:
                        records.append(
                            _task_process_record(
                                task,
                                ok=False,
                                blocked_reason=(
                                    "ability_task_damage_before_window_blocked:"
                                    + ",".join(before_errors)
                                ),
                            )
                        )
                        return (
                            current,
                            mutations,
                            events,
                            rng_events,
                            records,
                        )
                    sequence_order.append(sequence_key)
                    sequence_context[sequence_key] = {
                        "target_id": target_id,
                        "source_trace": emission.source.to_json(),
                        "damage_custom_name": emission.damage_custom_name,
                        "damage_tags": list(emission.damage_tags),
                        "is_critical": False,
                        "final_damage": 0.0,
                    }
                damage_result = self.damage.apply_packet(current, packet, window_ledger=ledger)
                current = self.reducer.apply_all(current, damage_result.mutations)
                mutations.extend(damage_result.mutations)
                rng_events.extend(damage_result.rng_events)
                records.extend(damage_result.records)
                for damage_event in damage_result.events:
                    if damage_event.event_type == "damage.hit":
                        amount = damage_event.payload.get("final_damage")
                        if not isinstance(amount, (int, float)) or isinstance(
                            amount,
                            bool,
                        ):
                            amount = damage_event.payload.get("amount")
                        if isinstance(amount, (int, float)) and not isinstance(
                            amount,
                            bool,
                        ):
                            context = sequence_context.get(sequence_key)
                            if context is not None:
                                context["final_damage"] = float(
                                    context.get("final_damage") or 0.0
                                ) + float(amount)
                                context["is_critical"] = bool(
                                    context.get("is_critical")
                                ) or damage_event.payload.get(
                                    "is_critical"
                                ) is True
                    dispatch_errors = dispatch_damage_event(damage_event)
                    if dispatch_errors:
                        records.append(
                            _task_process_record(
                                task,
                                ok=False,
                                blocked_reason=(
                                    "ability_task_damage_event_blocked:"
                                    + ",".join(dispatch_errors)
                                ),
                            )
                        )
                        return (
                            current,
                            mutations,
                            events,
                            rng_events,
                            records,
                        )
                records.append(
                    _task_process_record(
                        task,
                        ok=damage_result.ok,
                        blocked_reason=",".join(damage_result.errors),
                        effect_id=task.effect_id,
                        effect_opcode=task.opcode,
                        effect_coverage="executable",
                        mutation_count=len(damage_result.mutations),
                        record_count=len(damage_result.records),
                    )
                )
        if self.event_dispatcher is not None:
            for sequence_key in sequence_order:
                context = sequence_context[sequence_key]
                sequence_tags = context.get("damage_tags")
                after_errors = dispatch_damage_event(
                    damage_listener_window_event(
                        current,
                        command,
                        action_definition,
                        event_type="damage.hit_sequence.after",
                        target_id=str(context["target_id"]),
                        selected_target_ids=target_resolution.selected,
                        primary_target_id=primary_target,
                        source_trace=(
                            context["source_trace"]
                            if isinstance(context.get("source_trace"), dict)
                            else {}
                        ),
                        is_critical=bool(context.get("is_critical")),
                        final_damage=float(
                            context.get("final_damage") or 0.0
                        ),
                        damage_custom_name=str(
                            context.get("damage_custom_name") or ""
                        ),
                        damage_tags=tuple(
                            tag
                            for tag in (
                                sequence_tags
                                if isinstance(sequence_tags, (list, tuple))
                                else ()
                            )
                            if isinstance(tag, str) and tag
                        ),
                        sequence_id=sequence_key[0],
                    )
                )
                if after_errors:
                    records.append(
                        _task_process_record(
                            task,
                            ok=False,
                            blocked_reason=(
                                "ability_task_damage_after_window_blocked:"
                                + ",".join(after_errors)
                            ),
                        )
                    )
                    return (
                        current,
                        mutations,
                        events,
                        rng_events,
                        records,
                    )
        return current, mutations, events, rng_events, records

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
    ) -> tuple[BattleState, list[Mutation], list[GameEvent], list[RNGEvent], list[dict[str, JSONValue]]]:
        condition = self.rules.condition(task.condition_id) if task.condition_id else None
        if condition is None:
            record = _task_process_record(task, ok=False, blocked_reason="missing_predicate_condition")
            return state, [], [], [], [record]
        binding_sources = _binding_sources(
            self.rules,
            state,
            command.actor_id,
            primary_target,
            action_level=command.action_level,
            current_action_trigger_key=_action_trigger_key(action_definition),
        )
        event_payload = {
            **_event_payload(command, action_definition, primary_target, target_resolution),
            "task_id": task.task_id,
            "hit_index": task.task_index,
            "rng_decision_index": task.task_index,
        }
        resolved_target_groups: dict[str, tuple[str, ...]] = {}
        target_resolution_errors: dict[str, str] = {}
        for field_name, node in condition.payload.items():
            if not isinstance(node, TargetExpressionNodeIR):
                continue
            target_result = self.targets.resolve_expression_node(
                state,
                node,
                caster_id=command.actor_id,
                owner_id=command.actor_id,
                param_entity_id=primary_target or command.actor_id,
                current_action_target_id=primary_target,
                target_resolution=target_resolution,
                event_payload=event_payload,
                binding_sources=binding_sources,
            )
            if target_result.ok:
                resolved_target_groups[field_name] = target_result.target_ids
            else:
                target_resolution_errors[field_name] = target_result.blocked_reason
        result = self.evaluator.evaluate_condition_result(
            condition,
            EvaluationContext(
                state=state,
                actor_id=command.actor_id,
                target_id=primary_target,
                owner_id=command.actor_id,
                param_entity_id=primary_target or command.actor_id,
                current_action_target_id=primary_target,
                event_payload=event_payload,
                binding_sources=binding_sources,
                resolved_target_groups=resolved_target_groups,
                target_resolution_errors=target_resolution_errors,
            ),
        )
        if not result.ok or result.result is None:
            record = _task_process_record(
                task,
                ok=False,
                blocked_reason=f"blocked_condition:{condition.condition_id}:{result.reason}",
                condition_result=result.to_json(),
            )
            return state, [], [], [], [record]

        selected_child_ids = task.success_task_ids if result.result else task.failed_task_ids
        current = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
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
            current, child_mutations, child_events, child_rng_events, child_records = self._execute_task(
                current,
                child,
                tasks,
                command=command,
                action_definition=action_definition,
                primary_target=primary_target,
                target_resolution=target_resolution,
            )
            mutations.extend(child_mutations)
            events.extend(child_events)
            rng_events.extend(child_rng_events)
            records.extend(child_records)
        return current, mutations, events, rng_events, records


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


def _node_results_from_task_records(
    task_records: list[dict[str, JSONValue]] | tuple[dict[str, JSONValue], ...],
) -> tuple[ExecutionNodeResult, ...]:
    results: list[ExecutionNodeResult] = []
    for index, payload in enumerate(task_records):
        task_id = str(payload.get("task_id") or f"ability_task:{index}")
        ok = payload.get("ok") is True
        reason = str(payload.get("blocked_reason") or "")
        coverage_status = str(payload.get("coverage_status") or "")
        if ok:
            status = "complete"
        elif "partial" in reason or "partial" in coverage_status:
            status = "partial"
        elif coverage_status and coverage_status != "executable":
            status = "unsupported"
        elif "not_executable" in reason or "unsupported" in reason:
            status = "unsupported"
        else:
            status = "blocked"
        results.append(
            ExecutionNodeResult(
                node_kind="ability_task",
                node_id=task_id,
                status=status,
                reason_code=reason or ("" if ok else "ability_task_incomplete"),
            )
        )
    return tuple(results)


def _rng_event_payload_from_command(command: ActionCommand) -> dict[str, JSONValue]:
    payload: dict[str, JSONValue] = {}
    for key in ("rng_choices", "rng_mode", "target_random_choices"):
        value = command.metadata.get(key)
        if isinstance(value, (dict, str)):
            payload[key] = value
    return payload


def _event_payload(
    command: ActionCommand,
    action_definition: ActionDefinitionIR,
    primary_target: str | None,
    target_resolution: TargetResolution,
) -> dict[str, JSONValue]:
    return {
        **_rng_event_payload_from_command(command),
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
    return action_definition.skill_trigger_key


def _damage_targets_for_emission(
    target_group: str,
    target_resolution: TargetResolution,
) -> tuple[str, ...]:
    selected = tuple(target_resolution.selected)
    primary = target_resolution.primary or (selected[0] if selected else None)
    impact_group = tuple(target_resolution.impact_group) or selected
    if target_group in {"selected", "single"}:
        return selected
    if target_group == "primary":
        return (primary,) if primary else ()
    if target_group == "adjacent":
        return tuple(target_id for target_id in impact_group if target_id != primary)
    if target_group in {"aoe", "all_enemy"}:
        return impact_group
    return ()


def _expression_binding_sources(expression: object) -> tuple[dict[str, JSONValue], ...]:
    if not isinstance(expression, dict):
        return ()
    source = expression.get("binding_source")
    return (
        ({**source, "binding_role": "compiled_expression_fallback"},)
        if isinstance(source, dict)
        else ()
    )
