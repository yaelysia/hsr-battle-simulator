from __future__ import annotations

from dataclasses import replace

from .action_plan import DamagePlan, ToughnessPlan, build_action_execution_plan
from .model import (
    ActionCommand,
    ActionSettlement,
    ActionTransaction,
    BattleState,
    BattleTransition,
    GameEvent,
    JSONValue,
    Mutation,
)
from .reducer import MutationReducer
from .settlement import SettlementRecord
from ..rules.ir import ActionDefinitionIR
from ..rules.rulebook import RuleBook
from ..systems.ability import AbilityTaskExecutionResult, AbilityTaskSystem
from ..systems.break_system import BreakApplicationResult, BreakSystem
from ..systems.damage import DamagePacket, DamageSystem
from ..systems.effect import EffectRegistry
from ..systems.resource import ResourcePlan, ResourceSystem
from ..systems.status import StatusSystem
from ..systems.target import TargetPolicy, TargetSystem
from ..systems.timeline import TimelinePlan, TimelineSystem
from ..systems.toughness import ToughnessPacket, ToughnessSystem
from ..systems.trigger import TriggerSystem, TriggerWindowResult


class CombatExecutor:
    """v8 action executor boundary."""

    def __init__(self, rules: RuleBook):
        self.rules = rules
        self.reducer = MutationReducer()
        self.resources = ResourceSystem()
        self.targets = TargetSystem()
        self.timeline = TimelineSystem()
        self.damage = DamageSystem()
        self.toughness = ToughnessSystem()
        self.status = StatusSystem(rules)
        self.effects = EffectRegistry(self.status)
        self.breaks = BreakSystem(rules, self.effects, reducer=self.reducer)
        self.ability_tasks = AbilityTaskSystem(rules, self.effects, reducer=self.reducer)
        self.triggers = TriggerSystem(rules, self.effects, reducer=self.reducer)

    def execute(self, command: ActionCommand, state: BattleState) -> tuple[BattleState, BattleTransition]:
        before = state.snapshot()
        action_definition = self.rules.require_action_definition(command.action_id, command.action_level)
        action_event_ir = self.rules.require_action_event(command.action_id, command.action_level)
        action_binding = self.rules.action_ability_binding(command.action_id, command.action_level)
        ability_phases = self.rules.ability_phases_for_action(command.action_id, command.action_level)
        ability_tasks = self.rules.ability_tasks_for_action(command.action_id, command.action_level)
        hit_profiles = self.rules.hit_profiles_for_action(command.action_id, command.action_level)
        damage_emissions = self.rules.damage_emissions_for_action(command.action_id, command.action_level)
        toughness_emissions = self.rules.toughness_emissions_for_action(command.action_id, command.action_level)
        action_definition_trace = self.rules.action_definition_source_trace(command.action_id, command.action_level) or {}
        binding_blocked_reason = _binding_blocked_reason(action_binding)
        action_event_blocked_reason = _action_event_blocked_reason(action_event_ir)
        action_source_metadata = {
            "definition_id": action_definition.definition_id,
            "action_id": action_definition.action_id,
            "action_level": action_definition.level,
            "action_event_id": action_event_ir.action_event_id,
            "source_trace": action_definition_trace,
            "action_event_source_trace": action_event_ir.source.to_json(),
        }
        action_event = GameEvent(
            "action.requested",
            source_id=command.actor_id,
            event_id=f"event:{state.event_index + 1}:action_requested",
            window="action_request",
            process_only=True,
            payload={
                "action_id": command.action_id,
                "action_level": command.action_level,
                "definition_id": action_definition.definition_id,
                "source": command.source,
            },
        )
        target_result = self.targets.resolve_action_targets(
            state,
            command.actor_id,
            command.target_ids,
            policy=_target_policy(action_definition, action_event_ir.target_mode),
        )
        action_execution_plan = build_action_execution_plan(
            action_definition,
            action_event_ir,
            hit_profiles,
            damage_emissions,
            requested_target_ids=command.target_ids,
            resolved_target_groups=_target_groups_from_resolution(target_result.resolution.metadata),
            source_trace={
                **action_definition_trace,
                "action_event_id": action_event_ir.action_event_id,
                "binding_id": action_binding.binding_id if action_binding else "",
                "phase_ids": [phase.phase_id for phase in ability_phases],
                "event_source_status": action_event_ir.event_source_status,
                "hit_profile_ids": [profile.hit_profile_id for profile in hit_profiles],
                "damage_emission_ids": [emission.damage_emission_id for emission in damage_emissions],
                "toughness_emission_ids": [emission.toughness_emission_id for emission in toughness_emissions],
            },
            toughness_emissions=toughness_emissions,
        )
        action_event_plan_payload = _action_event_plan_compat_payload(action_definition, action_event_ir)
        resource_result = self.resources.plan_action_resources(
            state,
            command.actor_id,
            ResourcePlan(
                skill_point_delta=_skill_point_delta(action_definition.bp_need, action_definition.bp_add),
                energy_gain=action_definition.sp_base,
                source="combat_executor.resources",
                metadata=action_source_metadata,
            ),
        )
        plan_blocked_reason = _combined_blocked_reason(
            binding_blocked_reason,
            action_event_blocked_reason,
            action_execution_plan.target_plan.blocked_reason,
        )
        blocked_reason = _action_blocked_reason(
            target_ok=target_result.ok,
            resource_ok=resource_result.ok,
            has_selected_target=bool(target_result.resolution.selected),
            plan_blocked_reason=plan_blocked_reason,
            target_errors=target_result.errors,
            resource_errors=resource_result.errors,
        )
        action_enabled = not blocked_reason
        if action_enabled:
            timeline_result = self.timeline.open_action(
                state,
                command.actor_id,
                TimelinePlan(
                    reset_actor_av=_metadata_bool(command.metadata, "reset_actor_av", False),
                    source="combat_executor.timeline",
                    metadata=action_source_metadata,
                ),
            )
            events: tuple[GameEvent, ...] = (action_event, *timeline_result.events)
            timeline_mutations = timeline_result.mutations
            resource_mutations = resource_result.mutations
        else:
            events = (action_event,)
            timeline_mutations = ()
            resource_mutations = ()
        pre_damage_mutations = (*timeline_mutations, *resource_mutations)
        current_state = self.reducer.apply_all(state, pre_damage_mutations)
        trigger_results: list[TriggerWindowResult] = []
        ordered_mutations: list[Mutation] = list(pre_damage_mutations)
        runtime_records: list[dict[str, JSONValue]] = [
            *(_mutation_record("timeline", mutation) for mutation in timeline_mutations),
            *(_mutation_record("resource", mutation) for mutation in resource_mutations),
        ]
        damage_results = []
        damage_mutations: tuple[Mutation, ...] = ()
        toughness_results = []
        toughness_mutations: tuple[Mutation, ...] = ()
        break_results: list[BreakApplicationResult] = []
        break_mutations: tuple[Mutation, ...] = ()
        ability_task_results: list[AbilityTaskExecutionResult] = []

        if action_enabled:
            for step in action_execution_plan.event_steps:
                if step.kind == "trigger_window":
                    callback_kind = _callback_kind_for_step(step.phase)
                    if callback_kind:
                        ability_result = self.ability_tasks.execute_callback(
                            current_state,
                            phases=ability_phases,
                            callback_kind=callback_kind,
                            command=command,
                            action_definition=action_definition,
                            target_resolution=target_result.resolution,
                        )
                        current_state = ability_result.after_state
                        ability_task_results.append(ability_result)
                        ordered_mutations.extend(ability_result.mutations)
                        runtime_records.extend(ability_result.records)
                    trigger_result = self.triggers.execute_status_window(
                        current_state,
                        canonical_window=step.canonical_window,
                        tbgd_event=step.tbgd_event,
                        command=command,
                        action_definition=action_definition,
                        target_resolution=target_result.resolution,
                        enabled=True,
                        skipped_reason="",
                    )
                    current_state = trigger_result.after_state
                    trigger_results.append(trigger_result)
                    ordered_mutations.extend(trigger_result.mutations)
                    runtime_records.extend(trigger_result.records)
                    continue
                if step.kind == "damage":
                    if not action_execution_plan.damage_plan:
                        runtime_records.append(
                            SettlementRecord(
                                record_type="damage_emission_blocked",
                                source="combat_executor",
                                process_only=True,
                                payload={
                                    "reason": _damage_emission_blocked_reason(action_execution_plan.damage_emissions),
                                    "damage_emission_count": len(action_execution_plan.damage_emissions),
                                    "executable_damage_emission_count": len(
                                        [
                                            emission
                                            for emission in action_execution_plan.damage_emissions
                                            if emission.coverage_status == "executable"
                                        ]
                                    ),
                                    "action_execution_plan": action_execution_plan.to_json(),
                                },
                                trace=action_definition_trace,
                            ).to_json()
                        )
                    if action_execution_plan.toughness_emissions and not action_execution_plan.toughness_plan:
                        runtime_records.append(
                            SettlementRecord(
                                record_type="toughness_emission_blocked",
                                source="combat_executor",
                                process_only=True,
                                payload={
                                    "reason": _toughness_emission_blocked_reason(
                                        action_execution_plan.toughness_emissions
                                    ),
                                    "toughness_emission_count": len(action_execution_plan.toughness_emissions),
                                    "executable_toughness_emission_count": len(
                                        [
                                            emission
                                            for emission in action_execution_plan.toughness_emissions
                                            if emission.coverage_status == "executable"
                                        ]
                                    ),
                                    "action_execution_plan": action_execution_plan.to_json(),
                                },
                                trace=action_definition_trace,
                            ).to_json()
                        )
                    applied_toughness_keys: set[tuple[str, str]] = set()
                    for damage_plan in action_execution_plan.damage_plan:
                        damage_packet = _damage_packet(
                            command,
                            action_definition,
                            action_definition_trace,
                            damage_plan,
                        )
                        if damage_packet is None:
                            continue
                        damage_result = self.damage.apply_packet(current_state, damage_packet)
                        damage_results.append(damage_result)
                        damage_mutations = (*damage_mutations, *damage_result.mutations)
                        current_state = self.reducer.apply_all(current_state, damage_result.mutations)
                        ordered_mutations.extend(damage_result.mutations)
                        runtime_records.extend(damage_result.records)
                        for toughness_plan in _toughness_plans_for_damage_plan(
                            action_execution_plan.toughness_plan,
                            damage_plan,
                        ):
                            applied_toughness_keys.add((toughness_plan.toughness_emission_id, toughness_plan.target_id))
                            toughness_packet = _toughness_packet(command, toughness_plan)
                            toughness_result = self.toughness.apply_packet(current_state, toughness_packet)
                            toughness_results.append(toughness_result)
                            toughness_mutations = (*toughness_mutations, *toughness_result.mutations)
                            current_state = self.reducer.apply_all(current_state, toughness_result.mutations)
                            ordered_mutations.extend(toughness_result.mutations)
                            runtime_records.extend(toughness_result.records)
                            break_result = _enter_break_if_depleted(self.breaks, current_state, toughness_result)
                            if break_result:
                                current_state = break_result.after_state
                                break_results.append(break_result)
                                break_mutations = (*break_mutations, *break_result.mutations)
                                ordered_mutations.extend(break_result.mutations)
                                runtime_records.extend(break_result.records)
                    for toughness_plan in action_execution_plan.toughness_plan:
                        key = (toughness_plan.toughness_emission_id, toughness_plan.target_id)
                        if key in applied_toughness_keys:
                            continue
                        toughness_packet = _toughness_packet(command, toughness_plan)
                        toughness_result = self.toughness.apply_packet(current_state, toughness_packet)
                        toughness_results.append(toughness_result)
                        toughness_mutations = (*toughness_mutations, *toughness_result.mutations)
                        current_state = self.reducer.apply_all(current_state, toughness_result.mutations)
                        ordered_mutations.extend(toughness_result.mutations)
                        runtime_records.extend(toughness_result.records)
                        break_result = _enter_break_if_depleted(self.breaks, current_state, toughness_result)
                        if break_result:
                            current_state = break_result.after_state
                            break_results.append(break_result)
                            break_mutations = (*break_mutations, *break_result.mutations)
                            ordered_mutations.extend(break_result.mutations)
                            runtime_records.extend(break_result.records)
                    ability_result = self.ability_tasks.execute_callback(
                        current_state,
                        phases=ability_phases,
                        callback_kind="OnHit",
                        command=command,
                        action_definition=action_definition,
                        target_resolution=target_result.resolution,
                    )
                    current_state = ability_result.after_state
                    ability_task_results.append(ability_result)
                    ordered_mutations.extend(ability_result.mutations)
                    runtime_records.extend(ability_result.records)
        elif action_execution_plan.target_plan.blocked_reason:
            runtime_records.append(
                SettlementRecord(
                    record_type="damage_blocked",
                    source="combat_executor",
                    process_only=True,
                    payload={
                        "reason": action_execution_plan.target_plan.blocked_reason,
                        "action_execution_plan": action_execution_plan.to_json(),
                    },
                    trace=action_definition_trace,
                ).to_json()
            )

        trigger_mutations = tuple(mutation for result in trigger_results for mutation in result.mutations)
        trigger_events = tuple(event for result in trigger_results for event in result.events)
        trigger_windows = tuple(window for result in trigger_results for window in result.trigger_windows)
        ability_task_mutations = tuple(mutation for result in ability_task_results for mutation in result.mutations)
        ability_task_events = tuple(event for result in ability_task_results for event in result.events)
        ability_task_records = tuple(record for result in ability_task_results for record in result.task_records)
        mutations = tuple(ordered_mutations)
        after_state = current_state
        damage_rng_events = tuple(event for result in damage_results for event in result.rng_events)

        records: list[dict[str, JSONValue]] = [
            SettlementRecord(
                record_type="process",
                source="combat_executor",
                process_only=True,
                payload={
                    "event": "action.requested",
                    "rule_known": self.rules.has_action(command.action_id),
                    "definition_known": True,
                },
                trace={"event_id": action_event.event_id},
            ).to_json(),
            SettlementRecord(
                record_type="action_definition",
                source="rulebook",
                process_only=True,
                payload=action_definition.to_json(),
                trace=action_definition_trace,
            ).to_json(),
            SettlementRecord(
                record_type="action_ability_binding",
                source="rulebook",
                process_only=True,
                payload=action_binding.to_json()
                if action_binding
                else {
                    "action_id": command.action_id,
                    "action_level": command.action_level,
                    "coverage_status": "blocked",
                    "blocked_reason": "action_ability_binding_missing",
                },
                trace=action_binding.source.to_json() if action_binding else action_definition.source.to_json(),
            ).to_json(),
            SettlementRecord(
                record_type="ability_phase_graph",
                source="rulebook",
                process_only=True,
                payload={
                    "binding_id": action_binding.binding_id if action_binding else "",
                    "phase_count": len(ability_phases),
                    "phases": [phase.to_json() for phase in ability_phases],
                },
                trace=action_binding.source.to_json() if action_binding else action_definition.source.to_json(),
            ).to_json(),
            SettlementRecord(
                record_type="ability_task_graph",
                source="rulebook",
                process_only=True,
                payload={
                    "binding_id": action_binding.binding_id if action_binding else "",
                    "task_count": len(ability_tasks),
                    "tasks": [task.to_json() for task in ability_tasks],
                },
                trace=action_binding.source.to_json() if action_binding else action_definition.source.to_json(),
            ).to_json(),
            SettlementRecord(
                record_type="action_event_ir",
                source="rulebook",
                process_only=True,
                payload=action_event_ir.to_json(),
                trace=action_event_ir.source.to_json(),
            ).to_json(),
            SettlementRecord(
                record_type="hit_profiles",
                source="rulebook",
                process_only=True,
                payload={"profiles": [profile.to_json() for profile in hit_profiles]},
                trace={"definition_id": action_definition.definition_id},
            ).to_json(),
            SettlementRecord(
                record_type="damage_emissions",
                source="rulebook",
                process_only=True,
                payload={"emissions": [emission.to_json() for emission in damage_emissions]},
                trace={"definition_id": action_definition.definition_id},
            ).to_json(),
            SettlementRecord(
                record_type="toughness_emissions",
                source="rulebook",
                process_only=True,
                payload={"emissions": [emission.to_json() for emission in toughness_emissions]},
                trace={"definition_id": action_definition.definition_id},
            ).to_json(),
            SettlementRecord(
                record_type="action_execution_plan",
                source="combat_executor",
                process_only=True,
                payload=action_execution_plan.to_json(),
                trace={"definition_id": action_definition.definition_id},
            ).to_json(),
            SettlementRecord(
                record_type="action_preflight",
                source="combat_executor",
                process_only=True,
                payload={
                    "action_enabled": action_enabled,
                    "blocked_reason": blocked_reason,
                    "target_ok": target_result.ok,
                    "resource_ok": resource_result.ok,
                    "binding_ok": bool(action_binding and action_binding.coverage_status == "executable"),
                    "binding_blocked_reason": action_binding.blocked_reason if action_binding else "action_ability_binding_missing",
                    "event_ok": not action_event_blocked_reason,
                    "event_blocked_reason": action_event_blocked_reason,
                    "has_selected_target": bool(target_result.resolution.selected),
                    "plan_blocked_reason": plan_blocked_reason,
                    "target_errors": list(target_result.errors),
                    "resource_errors": list(resource_result.errors),
                },
                trace={"definition_id": action_definition.definition_id},
            ).to_json(),
            SettlementRecord(
                record_type="target_resolution",
                source="target_system",
                process_only=True,
                payload=target_result.resolution.to_json(),
                trace={"errors": list(target_result.errors)},
            ).to_json(),
        ]
        records.extend(runtime_records)
        if not action_enabled:
            records.append(
                SettlementRecord(
                    record_type="action_blocked",
                    source="combat_executor",
                    process_only=True,
                    payload={
                        "reason": blocked_reason,
                        "target_ok": target_result.ok,
                        "resource_ok": resource_result.ok,
                        "plan_blocked_reason": plan_blocked_reason,
                    },
                    trace={"definition_id": action_definition.definition_id},
                ).to_json()
            )
        if not target_result.ok:
            records.append(
                SettlementRecord(
                    record_type="target_error",
                    source="target_system",
                    process_only=True,
                    payload={"errors": list(target_result.errors)},
                ).to_json()
            )
        if not resource_result.ok:
            records.append(
                SettlementRecord(
                    record_type="resource_error",
                    source="resource_system",
                    process_only=True,
                    payload={"errors": list(resource_result.errors)},
                ).to_json()
            )

        settlement = ActionSettlement(
            action_id=command.action_id,
            actor_id=command.actor_id,
            target_ids=target_result.resolution.selected or command.target_ids,
            records=tuple(records),
        )
        transaction = ActionTransaction(
            command=command,
            before=before,
            events=(
                *events,
                *ability_task_events,
                *trigger_events,
                *(event for result in damage_results for event in result.events),
            ),
            mutations=mutations,
            trigger_windows=trigger_windows,
            settlement=settlement,
        )
        transition = BattleTransition(
            transaction=transaction,
            after=after_state.snapshot(),
            target_resolution=target_result.resolution,
            rng_events=damage_rng_events,
            coverage={
                "executor": "v0_221_action_ability_binding",
                "action_ability_binding": action_binding.to_json() if action_binding else None,
                "ability_phase_graph": [phase.to_json() for phase in ability_phases],
                "ability_task_graph": [task.to_json() for task in ability_tasks],
                "ability_task_count": len(ability_tasks),
                "ability_task_record_count": len(ability_task_records),
                "action_execution_plan": action_execution_plan.to_json(),
                "action_event_ir": action_event_ir.to_json(),
                "action_event_id": action_event_ir.action_event_id,
                "binding_id": action_binding.binding_id if action_binding else "",
                "phase_ids": [phase.phase_id for phase in ability_phases],
                "event_source_status": action_event_ir.event_source_status,
                "action_event_plan": action_event_plan_payload,
                "hit_profile_ids": [profile.hit_profile_id for profile in hit_profiles],
                "damage_emission_ids": [emission.damage_emission_id for emission in damage_emissions],
                "damage_emission_count": len(damage_emissions),
                "executable_damage_emission_count": len(
                    [emission for emission in damage_emissions if emission.coverage_status == "executable"]
                ),
                "toughness_emission_ids": [emission.toughness_emission_id for emission in toughness_emissions],
                "toughness_emission_count": len(toughness_emissions),
                "executable_toughness_emission_count": len(
                    [emission for emission in toughness_emissions if emission.coverage_status == "executable"]
                ),
                "definition_id": action_definition.definition_id,
                "target_ok": target_result.ok,
                "resource_ok": resource_result.ok,
                "binding_ok": bool(action_binding and action_binding.coverage_status == "executable"),
                "binding_blocked_reason": binding_blocked_reason,
                "event_ok": not action_event_blocked_reason,
                "event_blocked_reason": action_event_blocked_reason,
                "action_enabled": action_enabled,
                "blocked_reason": blocked_reason,
                "plan_blocked_reason": plan_blocked_reason,
                "primary_action_target_id": action_execution_plan.primary_action_target_id,
                "per_hit_target_context_not_implemented": action_execution_plan.per_hit_target_context_not_implemented,
                "timeline_mutation_count": len(timeline_mutations),
                "resource_mutation_count": len(resource_mutations),
                "trigger_window_count": len(trigger_windows),
                "trigger_mutation_count": len(trigger_mutations),
                "ability_task_mutation_count": len(ability_task_mutations),
                "damage_mutation_count": len(damage_mutations),
                "toughness_mutation_count": len(toughness_mutations),
                "break_mutation_count": len(break_mutations),
                "break_status_mutation_count": len(
                    [mutation for mutation in break_mutations if mutation.source == "status_system"]
                ),
                "break_damage_mutation_count": len(
                    [
                        mutation
                        for mutation in break_mutations
                        if mutation.source == "damage_system"
                        and mutation.metadata.get("damage_formula_family") == "break"
                    ]
                ),
                "damage_ok": all(result.ok for result in damage_results) if damage_results else None,
                "toughness_ok": all(result.ok for result in toughness_results) if toughness_results else None,
                "break_ok": all(result.ok for result in break_results) if break_results else None,
                "damage_formula_family": action_definition.damage_formula_family,
            },
        )
        return after_state, transition


def _mutation_record(record_type: str, mutation: Mutation) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type=record_type,
        source=mutation.source,
        mutation_id=mutation.stable_id(),
        process_only=False,
        payload={
            "path": list(mutation.path),
            "before": mutation.before,
            "after": mutation.after,
            "reason": mutation.reason,
            "metadata": mutation.metadata,
        },
    ).to_json()


def _action_event_plan_compat_payload(action_definition: ActionDefinitionIR, action_event_ir) -> dict[str, JSONValue]:
    steps = [step.to_json() for step in action_event_ir.phase_steps]
    has_attack_windows = any(
        isinstance(step, dict) and step.get("canonical_window") in {"before_attack", "after_attack"}
        for step in steps
    )
    has_damage_step = any(isinstance(step, dict) and step.get("kind") == "damage" for step in steps)
    return {
        "action_id": action_definition.action_id,
        "action_level": action_definition.level,
        "skill_type": action_definition.skill_effect,
        "attack_type": action_definition.attack_type,
        "damage_kind": action_definition.damage_kind,
        "damage_formula_family": action_definition.damage_formula_family,
        "has_attack_windows": has_attack_windows,
        "has_damage_step": has_damage_step,
        "steps": steps,
        "plan_source": "action_event_ir_compat_projection",
        "action_event_id": action_event_ir.action_event_id,
    }


def _action_blocked_reason(
    *,
    target_ok: bool,
    resource_ok: bool,
    has_selected_target: bool,
    plan_blocked_reason: str,
    target_errors: tuple[str, ...],
    resource_errors: tuple[str, ...],
) -> str:
    reasons: list[str] = []
    if plan_blocked_reason:
        reasons.append(plan_blocked_reason)
    if not target_ok:
        reasons.append("target_resolution_failed")
    if not resource_ok:
        reasons.append("resource_plan_failed")
    if target_ok and not has_selected_target:
        reasons.append("no_selected_target")
    reasons.extend(f"target_error:{error}" for error in target_errors)
    reasons.extend(f"resource_error:{error}" for error in resource_errors)
    return ",".join(dict.fromkeys(reasons))


def _damage_emission_blocked_reason(damage_emissions) -> str:
    if not damage_emissions:
        return "damage_emission_missing"
    blocked_reasons = [
        emission.blocked_reason
        for emission in damage_emissions
        if getattr(emission, "blocked_reason", "")
    ]
    if blocked_reasons:
        return ",".join(dict.fromkeys(blocked_reasons))
    return "no_executable_damage_emission"


def _toughness_emission_blocked_reason(toughness_emissions) -> str:
    if not toughness_emissions:
        return "toughness_emission_missing"
    blocked_reasons = [
        emission.blocked_reason
        for emission in toughness_emissions
        if getattr(emission, "blocked_reason", "")
    ]
    if blocked_reasons:
        return ",".join(dict.fromkeys(blocked_reasons))
    return "no_executable_toughness_emission"


def _metadata_bool(metadata: dict[str, JSONValue], key: str, default: bool) -> bool:
    value = metadata.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _skill_point_delta(bp_need: float, bp_add: float) -> int:
    if bp_need > 0:
        return -int(bp_need)
    if bp_add > 0:
        return int(bp_add)
    return 0


def _binding_blocked_reason(action_binding) -> str:
    if action_binding is None:
        return "action_ability_binding_missing"
    if action_binding.coverage_status != "executable":
        return action_binding.blocked_reason or f"action_ability_binding_not_executable:{action_binding.coverage_status}"
    if not action_binding.phase_ids:
        return "action_ability_binding_has_no_phase_ids"
    return ""


def _action_event_blocked_reason(action_event_ir) -> str:
    if action_event_ir.blocked_reason:
        return action_event_ir.blocked_reason
    if action_event_ir.event_source_status != "ability_phase_graph_bound":
        return f"action_event_source_not_bound:{action_event_ir.event_source_status}"
    return ""


def _combined_blocked_reason(*reasons: str) -> str:
    return ",".join(dict.fromkeys(reason for reason in reasons if reason))


def _callback_kind_for_step(phase: str) -> str:
    if phase == "before_skill_use":
        return "OnStart"
    if phase == "before_attack":
        return "OnAttack"
    if phase == "after_skill_use":
        return "OnEnd"
    return ""


def _target_policy(action_definition: ActionDefinitionIR, target_mode: str) -> TargetPolicy:
    if target_mode == "self_or_team":
        return TargetPolicy(
            policy_id="self_or_team",
            allow_enemy=False,
            allow_ally=True,
            allow_self=True,
            target_mode=target_mode,
            selection_mode="explicit_ally_or_self",
        )
    if action_definition.damage_kind == "hp_damage":
        return TargetPolicy(
            policy_id="enemy_damage",
            allow_enemy=True,
            allow_ally=False,
            allow_self=False,
            target_mode=target_mode,
            selection_mode=target_mode,
        )
    return TargetPolicy(
        policy_id="explicit_any",
        allow_enemy=True,
        allow_ally=True,
        allow_self=True,
        target_mode=target_mode,
        selection_mode=target_mode,
    )


def _damage_packet(
    command: ActionCommand,
    action_definition: ActionDefinitionIR,
    source_trace: dict[str, object],
    damage_plan: DamagePlan,
) -> DamagePacket | None:
    if action_definition.damage_kind != "hp_damage":
        return None
    if damage_plan.damage_formula_family not in {"direct", "true_damage", "hp_loss", "elation"}:
        return None
    return DamagePacket(
        attacker_id=command.actor_id,
        target_id=damage_plan.target_id,
        attack_type=action_definition.attack_type,
        damage_formula_family=damage_plan.damage_formula_family,
        damage_kind=action_definition.damage_kind,
        element_type=action_definition.element_type,
        action_definition=action_definition,
        source_trace={
            "definition_id": action_definition.definition_id,
            "action_id": action_definition.action_id,
            "action_level": action_definition.level,
            "source": source_trace,
            "damage_emission_id": damage_plan.damage_emission_id,
            "source_task_id": damage_plan.source_task_id,
            "hit_profile_id": damage_plan.hit_profile_id,
            "hit_source_trace": damage_plan.hit_source_trace,
        },
        damage_emission_id=damage_plan.damage_emission_id,
        source_task_id=damage_plan.source_task_id,
        hit_profile_id=damage_plan.hit_profile_id,
        scaling_ratio=damage_plan.scaling_ratio,
        hit_source_trace=damage_plan.hit_source_trace,
        metadata={
            **_damage_metadata(command),
            "hit_index": damage_plan.hit_index,
            "damage_emission_id": damage_plan.damage_emission_id,
            "source_task_id": damage_plan.source_task_id,
            "hit_profile_id": damage_plan.hit_profile_id,
            "target_group": damage_plan.target_group,
            "multiplier_source": damage_plan.multiplier_source,
            "scaling_ratio": damage_plan.scaling_ratio,
            "hit_source_trace": damage_plan.hit_source_trace,
            "numeric_fidelity_status": damage_plan.numeric_fidelity_status,
            "multi_hit_not_implemented": True,
            "primary_action_target_id": damage_plan.primary_action_target_id,
            "per_hit_target_context_not_implemented": True,
            "target_group_multiplier_not_implemented": damage_plan.target_group_multiplier_not_implemented,
        },
    )


def _toughness_plans_for_damage_plan(
    toughness_plans: tuple[ToughnessPlan, ...],
    damage_plan: DamagePlan,
) -> tuple[ToughnessPlan, ...]:
    return tuple(
        plan
        for plan in toughness_plans
        if plan.hit_profile_id == damage_plan.hit_profile_id and plan.target_id == damage_plan.target_id
    )


def _enter_break_if_depleted(breaks: BreakSystem, state: BattleState, toughness_result) -> BreakApplicationResult | None:
    if not toughness_result.ok or not toughness_result.mutations:
        return None
    target = state.units.get(toughness_result.packet.target_id)
    if target is None:
        return None
    if target.toughness > 0 or bool(target.flags.get("broken", False)):
        return None
    metadata = dict(toughness_result.packet.metadata)
    for mutation in toughness_result.mutations:
        if mutation.source != "toughness_system":
            continue
        for key in ("numeric_evaluation", "weakness_check", "amount"):
            if key in mutation.metadata:
                metadata[key] = mutation.metadata[key]
    return breaks.enter_break(state, replace(toughness_result.packet, metadata=metadata))


def _toughness_packet(command: ActionCommand, toughness_plan: ToughnessPlan) -> ToughnessPacket:
    return ToughnessPacket(
        attacker_id=command.actor_id,
        target_id=toughness_plan.target_id,
        toughness_emission_id=toughness_plan.toughness_emission_id,
        source_task_id=toughness_plan.source_task_id,
        hit_profile_id=toughness_plan.hit_profile_id,
        element_type=toughness_plan.element_type,
        amount=None,
        amount_expr=toughness_plan.toughness_amount_expr,
        target_group=toughness_plan.target_group,
        coverage_status="executable" if not toughness_plan.blocked_reason else "blocked",
        source_trace=toughness_plan.source_trace,
        metadata={
            "primary_action_target_id": toughness_plan.primary_action_target_id,
            "toughness_amount_expr": toughness_plan.toughness_amount_expr,
            "source_trace": toughness_plan.source_trace,
        },
    )


def _damage_metadata(command: ActionCommand) -> dict[str, JSONValue]:
    metadata: dict[str, JSONValue] = {}
    crit_mode = command.metadata.get("crit_mode")
    if isinstance(crit_mode, str):
        metadata["crit_mode"] = crit_mode
    return metadata


def _target_groups_from_resolution(metadata: dict[str, JSONValue]) -> dict[str, tuple[str, ...]]:
    groups = metadata.get("target_groups")
    if not isinstance(groups, dict):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for key, value in groups.items():
        if isinstance(value, (list, tuple)):
            result[str(key)] = tuple(str(item) for item in value if isinstance(item, str))
    return result
