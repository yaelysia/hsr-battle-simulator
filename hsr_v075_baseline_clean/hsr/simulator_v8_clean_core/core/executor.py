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
from .transition_outcome import ExecutionNodeResult, classify_transition_outcome
from ..rules.evaluator import EvaluationContext, NumericEvaluationContext, RuleEvaluator
from ..rules.ir import ActionDefinitionIR
from ..rules.rulebook import RuleBook
from ..rules.value_binding import ValueBindingRequest, ValueContext, ValueResolution, ValueResolver
from ..systems.ability import AbilityTaskExecutionResult, AbilityTaskSystem
from ..systems.action_preflight import (
    action_binding_blocked_reason,
    action_event_blocked_reason,
    action_skill_point_delta,
    combined_blocked_reason,
    target_policy_for_action,
)
from ..systems.break_system import BreakApplicationResult, BreakSystem
from ..systems.damage import DamagePacket, DamageSystem, DamageSourceFrame, DamageWindowLedger
from ..systems.dynamic_values import binding_source_from_store, status_binding_sources, store_from_state
from ..systems.effect import EffectRegistry
from ..systems.resource import ResourcePlan, ResourceSystem
from ..systems.status import StatusSystem
from ..systems.target import TargetSystem
from ..systems.timeline import TimelinePlan, TimelineSystem
from ..systems.unit_lifecycle import UnitLifecycleSystem
from ..systems.toughness import ToughnessPacket, ToughnessSystem
from ..systems.event_dispatch import EventDispatchResult, EventDispatchSystem
from ..systems.mutation_events import MUTATION_BACKED_EVENT_TYPES, before_toughness_event, events_for_mutation


class CombatExecutor:
    """v8 action executor boundary."""

    def __init__(self, rules: RuleBook):
        self.rules = rules
        self.reducer = MutationReducer()
        self.resources = ResourceSystem()
        self.targets = TargetSystem()
        self.timeline = TimelineSystem()
        self.lifecycle = UnitLifecycleSystem()
        self.damage = DamageSystem()
        self.toughness = ToughnessSystem()
        self.status = StatusSystem(rules)
        self.effects = EffectRegistry(self.status)
        self.breaks = BreakSystem(rules, self.effects, reducer=self.reducer)
        self.ability_tasks = AbilityTaskSystem(rules, self.effects, reducer=self.reducer)
        self.event_dispatcher = EventDispatchSystem(rules, self.effects, reducer=self.reducer)
        self.value_resolver = ValueResolver(rules)

    def execute(self, command: ActionCommand, state: BattleState) -> tuple[BattleState, BattleTransition]:
        before = state.snapshot()
        command = _command_with_character_card_level_bonus(command, state, self.rules)
        action_definition = self.rules.require_action_definition(command.action_id, command.action_level)
        action_event_ir = self.rules.require_action_event(command.action_id, command.action_level)
        action_binding = self.rules.action_ability_binding(command.action_id, command.action_level)
        ability_phases = self.rules.ability_phases_for_action(command.action_id, command.action_level)
        ability_tasks = self.rules.ability_tasks_for_action(command.action_id, command.action_level)
        hit_profiles = self.rules.hit_profiles_for_action(command.action_id, command.action_level)
        damage_emissions = self.rules.damage_emissions_for_action(command.action_id, command.action_level)
        toughness_emissions = self.rules.toughness_emissions_for_action(command.action_id, command.action_level)
        bounce_policy = _bounce_policy_for_profiles(self.rules, hit_profiles)
        action_definition_trace = self.rules.action_definition_source_trace(command.action_id, command.action_level) or {}
        binding_blocked_reason = action_binding_blocked_reason(action_binding)
        action_event_reason = action_event_blocked_reason(action_event_ir)
        action_source_metadata = {
            "definition_id": action_definition.definition_id,
            "action_id": action_definition.action_id,
            "action_level": action_definition.level,
            "action_event_id": action_event_ir.action_event_id,
            "source_trace": action_definition_trace,
            "action_event_source_trace": action_event_ir.source.to_json(),
            "effective_action_level_source": command.metadata.get("effective_action_level_source", {}),
        }
        actor_lifecycle_ok, actor_lifecycle_reason = self.lifecycle.can_act(state, command.actor_id)
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
            policy=target_policy_for_action(
                self.rules,
                action_definition,
                action_event_ir.target_mode,
                action_event=action_event_ir,
            ),
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
                "bounce_policy_id": bounce_policy.get("bounce_policy_id", "") if bounce_policy else "",
            },
            toughness_emissions=toughness_emissions,
        )
        action_event_plan_payload = _action_event_plan_compat_payload(action_definition, action_event_ir)
        queue_resource_policy = _queue_action_resource_policy(command)
        resource_plan, resource_value_blocked_reasons = _action_resource_plan_with_value_resolution(
            self.value_resolver,
            command,
            action_definition,
            metadata={
                **action_source_metadata,
                "queue_resource_policy": queue_resource_policy,
            },
            queue_resource_policy=queue_resource_policy,
        )
        resource_result = self.resources.plan_action_resources(
            state,
            command.actor_id,
            resource_plan,
        )
        execution_binding_blocked_reason = _execution_source_blocked_reason(binding_blocked_reason, action_execution_plan)
        execution_event_blocked_reason = _execution_source_blocked_reason(action_event_reason, action_execution_plan)
        summon_execution_blocked_reason = _summon_execution_blocked_reason(state, command)
        use_action_damage_plan_fallback = _uses_action_damage_plan_fallback(
            binding_blocked_reason,
            action_event_reason,
            action_execution_plan,
        )
        summon_damage_stat_blocked_reason = _summon_damage_stat_blocked_reason(
            state,
            command,
            action_definition,
            action_execution_plan,
        )
        plan_blocked_reason = combined_blocked_reason(
            actor_lifecycle_reason if not actor_lifecycle_ok else "",
            summon_execution_blocked_reason,
            summon_damage_stat_blocked_reason,
            execution_binding_blocked_reason,
            execution_event_blocked_reason,
            action_execution_plan.target_plan.blocked_reason,
        )
        blocked_reason = _action_blocked_reason(
            target_ok=target_result.ok,
            resource_ok=resource_result.ok,
            has_selected_target=bool(target_result.resolution.selected),
            plan_blocked_reason=plan_blocked_reason,
            target_errors=target_result.errors,
            resource_errors=(*resource_result.errors, *resource_value_blocked_reasons),
        )
        action_enabled = not blocked_reason
        execution_node_results: list[ExecutionNodeResult] = [
            ExecutionNodeResult(
                node_kind="target_resolution",
                node_id=action_definition.definition_id,
                status="complete" if target_result.ok else "blocked",
                reason_code="" if target_result.ok else ",".join(target_result.errors) or "action_target_blocked",
            ),
            ExecutionNodeResult(
                node_kind="target_selection",
                node_id=action_definition.definition_id,
                status="complete" if target_result.resolution.selected else "blocked",
                reason_code="" if target_result.resolution.selected else "no_selected_target",
            ),
            ExecutionNodeResult(
                node_kind="resource_plan",
                node_id=f"{command.actor_id}:{command.action_id}:{command.action_level}",
                status="complete" if resource_result.ok else "blocked",
                reason_code=""
                if resource_result.ok
                else ",".join((*resource_result.errors, *resource_value_blocked_reasons)) or "action_resource_blocked",
            ),
            ExecutionNodeResult(
                node_kind="action_binding",
                node_id=action_binding.binding_id if action_binding else f"{command.action_id}:{command.action_level}",
                status="complete" if not execution_binding_blocked_reason else "unsupported",
                reason_code=execution_binding_blocked_reason,
            ),
            ExecutionNodeResult(
                node_kind="action_event",
                node_id=action_event_ir.action_event_id,
                status="complete" if not execution_event_blocked_reason else "unsupported",
                reason_code=execution_event_blocked_reason,
            ),
            ExecutionNodeResult(
                node_kind="action_plan",
                node_id=action_definition.definition_id,
                status="complete" if not plan_blocked_reason else "blocked",
                reason_code=plan_blocked_reason,
            ),
        ]
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
        trigger_results: list[EventDispatchResult] = []
        listener_dispatch_results: list[EventDispatchResult] = []
        current_state = self.reducer.apply_all(state, timeline_mutations)
        ordered_mutations: list[Mutation] = list(timeline_mutations)
        runtime_records: list[dict[str, JSONValue]] = [
            *(_mutation_record("timeline", mutation) for mutation in timeline_mutations),
        ]
        for mutation in resource_mutations:
            current_state = self.reducer.apply_all(current_state, (mutation,))
            ordered_mutations.append(mutation)
            runtime_records.append(_mutation_record("resource", mutation))
            for emitted_event in events_for_mutation(
                mutation,
                actor_id=command.actor_id,
                source_id=command.actor_id,
                event_index=current_state.event_index,
                extra_payload={
                    "action_id": command.action_id,
                    "action_level": command.action_level,
                    "actor_id": command.actor_id,
                    "source_trace": action_source_metadata.get("source_trace", {}),
                },
            ):
                dispatch_result = self.event_dispatcher.dispatch_event(current_state, event=emitted_event)
                current_state = dispatch_result.after_state
                listener_dispatch_results.append(dispatch_result)
                ordered_mutations.extend(dispatch_result.mutations)
                runtime_records.extend(dispatch_result.records)
        damage_results = []
        target_rng_events = []
        damage_mutations: tuple[Mutation, ...] = ()
        toughness_results = []
        toughness_mutations: tuple[Mutation, ...] = ()
        break_results: list[BreakApplicationResult] = []
        break_mutations: tuple[Mutation, ...] = ()
        ability_task_results: list[AbilityTaskExecutionResult] = []
        damage_window_ledger = DamageWindowLedger()
        action_hit_targets: list[str] = []

        if action_enabled:
            for step in action_execution_plan.event_steps:
                if step.kind == "trigger_window":
                    callback_kind = _callback_kind_for_step(step.phase)
                    if callback_kind and not use_action_damage_plan_fallback:
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
                        for emitted_event in ability_result.events:
                            if emitted_event.event_type not in {
                                "status.lifecycle",
                                "damage.hit",
                                "toughness.hit",
                                "break.triggered",
                                "unit.defeated",
                                *MUTATION_BACKED_EVENT_TYPES,
                            }:
                                continue
                            dispatch_result = self.event_dispatcher.dispatch_event(
                                current_state,
                                event=emitted_event,
                                damage_window_ledger=damage_window_ledger,
                            )
                            current_state = dispatch_result.after_state
                            listener_dispatch_results.append(dispatch_result)
                            ordered_mutations.extend(dispatch_result.mutations)
                            runtime_records.extend(dispatch_result.records)
                    dispatch_event = GameEvent(
                        event_type=f"action.window.{step.canonical_window}",
                        source_id=command.actor_id,
                        target_id=target_result.resolution.selected[0] if target_result.resolution.selected else None,
                        event_id=f"event:{current_state.event_index}:{step.canonical_window}:dispatch",
                        window=step.canonical_window,
                        process_only=True,
                        payload={
                            "tbgd_event": step.tbgd_event,
                            "phase": step.phase,
                            "action_id": command.action_id,
                            "action_level": command.action_level,
                            "actor_id": command.actor_id,
                            "attacker_id": command.actor_id,
                            "damage_attacker_id": command.actor_id,
                            "selected_target_ids": list(target_result.resolution.selected),
                            "target_ids": list(target_result.resolution.selected),
                            "primary_action_target_id": action_execution_plan.primary_action_target_id,
                            "primary_target_id": action_execution_plan.primary_action_target_id,
                            "current_hit_target_id": action_execution_plan.primary_action_target_id,
                            "target_id": action_execution_plan.primary_action_target_id,
                            "attack_type": action_definition.attack_type,
                            "AttackType": action_definition.attack_type,
                            "skill_type": _condition_skill_type(action_definition),
                            "SkillType": _condition_skill_type(action_definition),
                            "skill_effect": action_definition.skill_effect,
                            "is_current_skill_active": True,
                            "is_insert_action": _metadata_bool(command.metadata, "is_insert_action", False),
                        },
                    )
                    trigger_result = self.event_dispatcher.dispatch_action_window(
                        current_state,
                        event=dispatch_event,
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
                    listener_result = self.event_dispatcher.dispatch_event(
                        current_state,
                        event=dispatch_event,
                        damage_window_ledger=damage_window_ledger,
                    )
                    current_state = listener_result.after_state
                    trigger_results.append(listener_result)
                    ordered_mutations.extend(listener_result.mutations)
                    runtime_records.extend(listener_result.records)
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
                        if damage_plan.target_group.startswith("bounce:"):
                            bounce_result = self.targets.resolve_bounce_hit_target(
                                current_state,
                                actor_id=command.actor_id,
                                primary_target_id=action_execution_plan.primary_action_target_id
                                or (target_result.resolution.selected[0] if target_result.resolution.selected else ""),
                                bounce_policy=_bounce_policy_from_damage_plan(damage_plan),
                                hit_index=damage_plan.hit_index,
                                previous_hit_targets=tuple(action_hit_targets),
                                action_id=command.action_id,
                                action_level=command.action_level,
                                event_payload=command.metadata,
                            )
                            if not bounce_result.ok:
                                execution_node_results.append(
                                    ExecutionNodeResult(
                                        node_kind="target_selection",
                                        node_id=damage_plan.damage_emission_id or damage_plan.source_task_id,
                                        status="blocked",
                                        reason_code=bounce_result.error or "bounce_target_resolution_blocked",
                                    )
                                )
                                runtime_records.append(
                                    SettlementRecord(
                                        record_type="bounce_target_blocked",
                                        source="target_system",
                                        process_only=True,
                                        payload={
                                            "reason": bounce_result.error,
                                            "damage_plan": damage_plan.to_json(),
                                            "metadata": bounce_result.metadata,
                                        },
                                        trace=damage_plan.hit_source_trace,
                                    ).to_json()
                                )
                                continue
                            if bounce_result.rng_event is not None:
                                target_rng_events.append(bounce_result.rng_event)
                            damage_plan = replace(
                                damage_plan,
                                target_id=bounce_result.target_id,
                                target_selection_policy={
                                    **(damage_plan.target_selection_policy or {}),
                                    "resolved_bounce_target": bounce_result.metadata,
                                    "rng_event": bounce_result.rng_event.to_json()
                                    if bounce_result.rng_event is not None
                                    else {},
                                },
                            )
                        damage_value_resolution = _damage_value_resolution(
                            self.value_resolver,
                            command,
                            action_definition,
                            damage_plan,
                        )
                        if not damage_value_resolution.ok or damage_value_resolution.value is None:
                            execution_node_results.append(
                                _value_resolution_node_result(
                                    node_kind="damage_formula",
                                    node_id=damage_plan.damage_emission_id or damage_plan.source_task_id,
                                    ok=False,
                                    reason=damage_value_resolution.blocked_reason or "damage_value_resolution_blocked",
                                )
                            )
                            runtime_records.append(
                                SettlementRecord(
                                    record_type="damage_value_resolution_blocked",
                                    source="combat_executor.value_resolver",
                                    process_only=True,
                                    payload={
                                        "reason": damage_value_resolution.blocked_reason,
                                        "damage_plan": damage_plan.to_json(),
                                        "value_resolution": damage_value_resolution.to_json(),
                                    },
                                    trace=damage_plan.hit_source_trace,
                                ).to_json()
                            )
                            continue
                        execution_node_results.append(
                            _value_resolution_node_result(
                                node_kind="damage_formula",
                                node_id=damage_plan.damage_emission_id or damage_plan.source_task_id,
                                ok=True,
                            )
                        )
                        damage_plan = replace(damage_plan, scaling_ratio=float(damage_value_resolution.value))
                        damage_packet = _damage_packet(
                            command,
                            action_definition,
                            action_definition_trace,
                            damage_plan,
                            value_resolution=damage_value_resolution.to_json(),
                        )
                        if damage_packet is None:
                            execution_node_results.append(
                                ExecutionNodeResult(
                                    node_kind="damage_packet",
                                    node_id=damage_plan.damage_emission_id or damage_plan.source_task_id,
                                    status="error",
                                    reason_code="damage_packet_not_constructed",
                                )
                            )
                            continue
                        modifier_terms, modifier_records = _collect_direct_damage_modifiers(
                            current_state,
                            self.rules,
                            command.actor_id,
                            damage_packet.target_id,
                            damage_packet,
                        )
                        if modifier_terms or modifier_records:
                            damage_packet = replace(
                                damage_packet,
                                metadata={
                                    **damage_packet.metadata,
                                    "direct_modifier_terms": [term for term in modifier_terms],
                                },
                            )
                            runtime_records.extend(modifier_records)
                        before_hit_event = GameEvent(
                            "damage.before_hit",
                            source_id=command.actor_id,
                            target_id=damage_packet.target_id,
                            event_id=(
                                f"event:{current_state.event_index}:damage_before_hit:"
                                f"{command.actor_id}:{damage_packet.target_id}:{damage_plan.hit_index}"
                            ),
                            window="OnBeforeHit",
                            process_only=True,
                            payload={
                                **damage_packet.metadata,
                                "callback_events": ["OnBeforeHitAll", "OnBeforeHit"],
                                "action_id": command.action_id,
                                "action_level": command.action_level,
                                "actor_id": command.actor_id,
                                "attacker_id": command.actor_id,
                                "damage_attacker_id": command.actor_id,
                                "primary_target_id": damage_plan.primary_action_target_id,
                                "primary_action_target_id": damage_plan.primary_action_target_id,
                                "current_hit_target_id": damage_packet.target_id,
                                "target_id": damage_packet.target_id,
                                "selected_target_ids": list(target_result.resolution.selected),
                                "target_ids": list(target_result.resolution.selected),
                                "attack_type": action_definition.attack_type,
                                "skill_effect": action_definition.skill_effect,
                                "damage_packet": damage_packet.to_json(),
                                "source_trace": damage_packet.source_trace,
                            },
                        )
                        dispatch_result = self.event_dispatcher.dispatch_event(
                            current_state,
                            event=before_hit_event,
                            damage_window_ledger=damage_window_ledger,
                        )
                        current_state = dispatch_result.after_state
                        listener_dispatch_results.append(dispatch_result)
                        ordered_mutations.extend(dispatch_result.mutations)
                        runtime_records.extend(dispatch_result.records)
                        damage_result = self.damage.apply_packet(
                            current_state,
                            damage_packet,
                            window_ledger=damage_window_ledger,
                        )
                        damage_results.append(damage_result)
                        damage_mutations = (*damage_mutations, *damage_result.mutations)
                        current_state = self.reducer.apply_all(current_state, damage_result.mutations)
                        ordered_mutations.extend(damage_result.mutations)
                        runtime_records.extend(damage_result.records)
                        for mutation in damage_result.mutations:
                            for hp_event in events_for_mutation(
                                mutation,
                                actor_id=command.actor_id,
                                source_id=command.actor_id,
                                event_index=current_state.event_index,
                                extra_payload={
                                    "action_id": command.action_id,
                                    "action_level": command.action_level,
                                    "actor_id": command.actor_id,
                                    "attacker_id": command.actor_id,
                                    "primary_action_target_id": damage_plan.primary_action_target_id,
                                    "current_hit_target_id": damage_packet.target_id,
                                    "attack_type": action_definition.attack_type,
                                    "skill_effect": action_definition.skill_effect,
                                    "source_trace": damage_packet.source_trace,
                                },
                            ):
                                dispatch_result = self.event_dispatcher.dispatch_event(
                                    current_state,
                                    event=hp_event,
                                    damage_window_ledger=damage_window_ledger,
                                )
                                current_state = dispatch_result.after_state
                                listener_dispatch_results.append(dispatch_result)
                                ordered_mutations.extend(dispatch_result.mutations)
                                runtime_records.extend(dispatch_result.records)
                        for emitted_event in damage_result.events:
                            kill_energy_mutation = self._kill_energy_mutation_for_event(
                                current_state,
                                emitted_event,
                                action_source_metadata,
                            )
                            if kill_energy_mutation is not None:
                                current_state = self.reducer.apply_all(current_state, (kill_energy_mutation,))
                                ordered_mutations.append(kill_energy_mutation)
                                runtime_records.append(_mutation_record("resource", kill_energy_mutation))
                                for resource_event in events_for_mutation(
                                    kill_energy_mutation,
                                    actor_id=str(kill_energy_mutation.path[1]) if len(kill_energy_mutation.path) > 1 else command.actor_id,
                                    source_id=command.actor_id,
                                    event_index=current_state.event_index,
                                    extra_payload={
                                        "action_id": command.action_id,
                                        "action_level": command.action_level,
                                        "actor_id": command.actor_id,
                                        "source_trace": kill_energy_mutation.metadata.get("source_trace", {}),
                                    },
                                ):
                                    resource_dispatch = self.event_dispatcher.dispatch_event(
                                        current_state,
                                        event=resource_event,
                                    )
                                    current_state = resource_dispatch.after_state
                                    listener_dispatch_results.append(resource_dispatch)
                                    ordered_mutations.extend(resource_dispatch.mutations)
                                    runtime_records.extend(resource_dispatch.records)
                            dispatch_result = self.event_dispatcher.dispatch_event(
                                current_state,
                                event=emitted_event,
                                damage_window_ledger=damage_window_ledger,
                            )
                            current_state = dispatch_result.after_state
                            listener_dispatch_results.append(dispatch_result)
                            ordered_mutations.extend(dispatch_result.mutations)
                            runtime_records.extend(dispatch_result.records)
                        for toughness_plan in _toughness_plans_for_damage_plan(
                            action_execution_plan.toughness_plan,
                            damage_plan,
                        ):
                            applied_toughness_keys.add((toughness_plan.toughness_emission_id, toughness_plan.target_id))
                            toughness_value_resolution = _toughness_value_resolution(
                                self.value_resolver,
                                command,
                                action_definition,
                                toughness_plan,
                            )
                            execution_node_results.append(
                                _value_resolution_node_result(
                                    node_kind="toughness_formula",
                                    node_id=toughness_plan.toughness_emission_id or toughness_plan.source_task_id,
                                    ok=toughness_value_resolution.ok and toughness_value_resolution.value is not None,
                                    reason=toughness_value_resolution.blocked_reason,
                                )
                            )
                            toughness_packet = _toughness_packet(
                                command,
                                toughness_plan,
                                value_resolution=toughness_value_resolution.to_json(),
                            )
                            toughness_result = self.toughness.apply_packet(current_state, toughness_packet)
                            toughness_results.append(toughness_result)
                            toughness_mutations = (*toughness_mutations, *toughness_result.mutations)
                            for mutation in toughness_result.mutations:
                                stance_before_event = before_toughness_event(
                                    mutation,
                                    actor_id=command.actor_id,
                                    event_index=current_state.event_index,
                                    extra_payload={
                                        "action_id": command.action_id,
                                        "action_level": command.action_level,
                                        "actor_id": command.actor_id,
                                        "attacker_id": command.actor_id,
                                        "primary_action_target_id": toughness_plan.primary_action_target_id,
                                        "current_hit_target_id": toughness_plan.target_id,
                                        "source_trace": toughness_plan.source_trace,
                                    },
                                )
                                if stance_before_event is None:
                                    continue
                                dispatch_result = self.event_dispatcher.dispatch_event(
                                    current_state,
                                    event=stance_before_event,
                                )
                                current_state = dispatch_result.after_state
                                listener_dispatch_results.append(dispatch_result)
                                ordered_mutations.extend(dispatch_result.mutations)
                                runtime_records.extend(dispatch_result.records)
                            current_state = self.reducer.apply_all(current_state, toughness_result.mutations)
                            ordered_mutations.extend(toughness_result.mutations)
                            runtime_records.extend(toughness_result.records)
                            for emitted_event in toughness_result.events:
                                dispatch_result = self.event_dispatcher.dispatch_event(current_state, event=emitted_event)
                                current_state = dispatch_result.after_state
                                listener_dispatch_results.append(dispatch_result)
                                ordered_mutations.extend(dispatch_result.mutations)
                                runtime_records.extend(dispatch_result.records)
                            break_result = _enter_break_if_depleted(self.breaks, current_state, toughness_result)
                            if break_result:
                                current_state = break_result.after_state
                                break_results.append(break_result)
                                break_mutations = (*break_mutations, *break_result.mutations)
                                ordered_mutations.extend(break_result.mutations)
                                runtime_records.extend(break_result.records)
                                for emitted_event in break_result.events:
                                    dispatch_result = self.event_dispatcher.dispatch_event(current_state, event=emitted_event)
                                    current_state = dispatch_result.after_state
                                    listener_dispatch_results.append(dispatch_result)
                                    ordered_mutations.extend(dispatch_result.mutations)
                                    runtime_records.extend(dispatch_result.records)
                        action_hit_targets.append(damage_plan.target_id)
                    for toughness_plan in action_execution_plan.toughness_plan:
                        key = (toughness_plan.toughness_emission_id, toughness_plan.target_id)
                        if key in applied_toughness_keys:
                            continue
                        toughness_value_resolution = _toughness_value_resolution(
                            self.value_resolver,
                            command,
                            action_definition,
                            toughness_plan,
                        )
                        execution_node_results.append(
                            _value_resolution_node_result(
                                node_kind="toughness_formula",
                                node_id=toughness_plan.toughness_emission_id or toughness_plan.source_task_id,
                                ok=toughness_value_resolution.ok and toughness_value_resolution.value is not None,
                                reason=toughness_value_resolution.blocked_reason,
                            )
                        )
                        toughness_packet = _toughness_packet(
                            command,
                            toughness_plan,
                            value_resolution=toughness_value_resolution.to_json(),
                        )
                        toughness_result = self.toughness.apply_packet(current_state, toughness_packet)
                        toughness_results.append(toughness_result)
                        toughness_mutations = (*toughness_mutations, *toughness_result.mutations)
                        for mutation in toughness_result.mutations:
                            stance_before_event = before_toughness_event(
                                mutation,
                                actor_id=command.actor_id,
                                event_index=current_state.event_index,
                                extra_payload={
                                    "action_id": command.action_id,
                                    "action_level": command.action_level,
                                    "actor_id": command.actor_id,
                                    "attacker_id": command.actor_id,
                                    "primary_action_target_id": toughness_plan.primary_action_target_id,
                                    "current_hit_target_id": toughness_plan.target_id,
                                    "source_trace": toughness_plan.source_trace,
                                },
                            )
                            if stance_before_event is None:
                                continue
                            dispatch_result = self.event_dispatcher.dispatch_event(
                                current_state,
                                event=stance_before_event,
                            )
                            current_state = dispatch_result.after_state
                            listener_dispatch_results.append(dispatch_result)
                            ordered_mutations.extend(dispatch_result.mutations)
                            runtime_records.extend(dispatch_result.records)
                        current_state = self.reducer.apply_all(current_state, toughness_result.mutations)
                        ordered_mutations.extend(toughness_result.mutations)
                        runtime_records.extend(toughness_result.records)
                        for emitted_event in toughness_result.events:
                            dispatch_result = self.event_dispatcher.dispatch_event(current_state, event=emitted_event)
                            current_state = dispatch_result.after_state
                            listener_dispatch_results.append(dispatch_result)
                            ordered_mutations.extend(dispatch_result.mutations)
                            runtime_records.extend(dispatch_result.records)
                        break_result = _enter_break_if_depleted(self.breaks, current_state, toughness_result)
                        if break_result:
                            current_state = break_result.after_state
                            break_results.append(break_result)
                            break_mutations = (*break_mutations, *break_result.mutations)
                            ordered_mutations.extend(break_result.mutations)
                            runtime_records.extend(break_result.records)
                            for emitted_event in break_result.events:
                                dispatch_result = self.event_dispatcher.dispatch_event(current_state, event=emitted_event)
                                current_state = dispatch_result.after_state
                                listener_dispatch_results.append(dispatch_result)
                                ordered_mutations.extend(dispatch_result.mutations)
                                runtime_records.extend(dispatch_result.records)
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
                    for emitted_event in ability_result.events:
                        if emitted_event.event_type not in {
                            "status.lifecycle",
                            "damage.hit",
                            "toughness.hit",
                            "break.triggered",
                            "unit.defeated",
                            *MUTATION_BACKED_EVENT_TYPES,
                        }:
                            continue
                        dispatch_result = self.event_dispatcher.dispatch_event(current_state, event=emitted_event)
                        current_state = dispatch_result.after_state
                        listener_dispatch_results.append(dispatch_result)
                        ordered_mutations.extend(dispatch_result.mutations)
                        runtime_records.extend(dispatch_result.records)
            for hit_target_id in dict.fromkeys(action_hit_targets):
                after_attack_event = GameEvent(
                    "action.after_attack",
                    source_id=command.actor_id,
                    target_id=hit_target_id,
                    event_id=f"event:{current_state.event_index}:action_after_attack:{hit_target_id}",
                    window="OnListenAfterAttack",
                    process_only=True,
                    payload={
                        "action_id": command.action_id,
                        "action_level": command.action_level,
                        "actor_id": command.actor_id,
                        "attacker_id": command.actor_id,
                        "damage_attacker_id": command.actor_id,
                        "param_entity_id": command.actor_id,
                        "primary_target_id": action_execution_plan.primary_action_target_id,
                        "current_hit_target_id": hit_target_id,
                        "target_id": hit_target_id,
                        "selected_target_ids": list(target_result.resolution.selected),
                        "target_ids": list(target_result.resolution.selected),
                        "attack_type": action_definition.attack_type,
                        "skill_effect": action_definition.skill_effect,
                        "source_trace": action_source_metadata.get("source_trace", {}),
                    },
                )
                dispatch_result = self.event_dispatcher.dispatch_event(current_state, event=after_attack_event)
                current_state = dispatch_result.after_state
                listener_dispatch_results.append(dispatch_result)
                ordered_mutations.extend(dispatch_result.mutations)
                runtime_records.extend(dispatch_result.records)
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
        trigger_rng_events = tuple(event for result in trigger_results for event in result.rng_events)
        trigger_windows = tuple(window for result in trigger_results for window in result.trigger_windows)
        ability_task_mutations = tuple(mutation for result in ability_task_results for mutation in result.mutations)
        ability_task_events = tuple(event for result in ability_task_results for event in result.events)
        ability_task_rng_events = tuple(event for result in ability_task_results for event in result.rng_events)
        ability_task_records = tuple(record for result in ability_task_results for record in result.task_records)
        listener_dispatch_mutations = tuple(mutation for result in listener_dispatch_results for mutation in result.mutations)
        listener_dispatch_events = tuple(event for result in listener_dispatch_results for event in result.events)
        listener_dispatch_rng_events = tuple(event for result in listener_dispatch_results for event in result.rng_events)
        listener_dispatch_records = tuple(record for result in listener_dispatch_results for record in result.records)
        execution_node_results.extend(
            node
            for result in ability_task_results
            for node in result.node_results
        )
        execution_node_results.extend(
            node
            for result in (*trigger_results, *listener_dispatch_results)
            for node in result.node_results
        )
        execution_node_results.extend(_damage_node_results(damage_results))
        execution_node_results.extend(_toughness_node_results(toughness_results))
        execution_node_results.extend(_break_node_results(break_results))
        mutations = tuple(ordered_mutations)
        after_state = current_state
        damage_rng_events = (
            *tuple(target_rng_events),
            *ability_task_rng_events,
            *trigger_rng_events,
            *listener_dispatch_rng_events,
            *tuple(event for result in damage_results for event in result.rng_events),
        )

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
                    "event_ok": not action_event_reason,
                    "event_blocked_reason": action_event_reason,
                    "summon_execution_blocked_reason": summon_execution_blocked_reason,
                    "summon_damage_stat_blocked_reason": summon_damage_stat_blocked_reason,
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
            events=_dedupe_events(
                *events,
                *ability_task_events,
                *trigger_events,
                *listener_dispatch_events,
                *(event for result in damage_results for event in result.events),
                *(event for result in toughness_results for event in result.events),
                *(event for result in break_results for event in result.events),
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
            outcome=classify_transition_outcome(
                tuple(execution_node_results),
                state_changed=before.to_json() != after_state.snapshot().to_json(),
                mutation_count=len(mutations),
                preflight_blocked=not action_enabled,
                preflight_reason=blocked_reason,
            ),
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
                "event_ok": not action_event_reason,
                "event_blocked_reason": action_event_reason,
                "summon_execution_blocked_reason": summon_execution_blocked_reason,
                "summon_damage_stat_blocked_reason": summon_damage_stat_blocked_reason,
                "action_enabled": action_enabled,
                "blocked_reason": blocked_reason,
                "plan_blocked_reason": plan_blocked_reason,
                "primary_action_target_id": action_execution_plan.primary_action_target_id,
                "per_hit_target_context_available": action_execution_plan.per_hit_target_context_available,
                "per_hit_listener_admission_partial": action_execution_plan.per_hit_listener_admission_partial,
                "per_hit_target_context_not_implemented": not action_execution_plan.per_hit_target_context_available,
                "timeline_mutation_count": len(timeline_mutations),
                "resource_mutation_count": len(resource_mutations),
                "trigger_window_count": len(trigger_windows),
                "trigger_mutation_count": len(trigger_mutations),
                "listener_dispatch_record_count": len(listener_dispatch_records),
                "listener_dispatch_mutation_count": len(listener_dispatch_mutations),
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
        return (after_state if transition.outcome.successor_eligible else state), transition

    def _kill_energy_mutation_for_event(
        self,
        state: BattleState,
        event: GameEvent,
        action_source_metadata: dict[str, JSONValue],
    ) -> Mutation | None:
        if event.event_type != "unit.defeated":
            return None
        payload = event.payload if isinstance(event.payload, dict) else {}
        owner_id = str(payload.get("kill_credit_owner_id") or payload.get("killer_id") or "")
        if not owner_id or owner_id not in state.units:
            return None
        owner = state.units[owner_id]
        if owner.max_energy <= 0:
            return None
        rule = self.rules.default_kill_energy_gain_rule()
        metadata = {
            **action_source_metadata,
            "source_trace": {
                **(action_source_metadata.get("source_trace") if isinstance(action_source_metadata.get("source_trace"), dict) else {}),
                "unit_defeated_event": event.to_json(),
                "resource_rule_source": rule.source.to_json(),
            },
        }
        mutation = self.resources.gain_kill_energy(
            state,
            owner_id,
            rule,
            defeated_event_payload=payload,
            metadata=metadata,
        )
        if mutation.before == mutation.after:
            return None
        return mutation


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


def _value_resolution_node_result(
    *,
    node_kind: str,
    node_id: str,
    ok: bool,
    reason: str = "",
) -> ExecutionNodeResult:
    return ExecutionNodeResult(
        node_kind=node_kind,
        node_id=node_id,
        status="complete" if ok else "blocked",
        reason_code="" if ok else reason or f"{node_kind}_blocked",
    )


def _damage_node_results(results: list) -> tuple[ExecutionNodeResult, ...]:
    return tuple(
        ExecutionNodeResult(
            node_kind="damage_application",
            node_id=result.packet.damage_emission_id or result.packet.source_task_id or f"damage:{index}",
            status="complete" if result.ok else "blocked",
            reason_code="" if result.ok else ",".join(result.errors) or "damage_application_blocked",
        )
        for index, result in enumerate(results)
    )


def _toughness_node_results(results: list) -> tuple[ExecutionNodeResult, ...]:
    return tuple(
        ExecutionNodeResult(
            node_kind="toughness_application",
            node_id=result.packet.toughness_emission_id or result.packet.source_task_id or f"toughness:{index}",
            status="complete" if result.ok else "blocked",
            reason_code="" if result.ok else ",".join(result.errors) or "toughness_application_blocked",
        )
        for index, result in enumerate(results)
    )


def _break_node_results(results: list[BreakApplicationResult]) -> tuple[ExecutionNodeResult, ...]:
    return tuple(
        ExecutionNodeResult(
            node_kind="break_application",
            node_id=f"break:{index}",
            status="complete" if result.ok else "blocked",
            reason_code="" if result.ok else ",".join(result.errors) or "break_application_blocked",
        )
        for index, result in enumerate(results)
    )


def _dedupe_events(*events: GameEvent) -> tuple[GameEvent, ...]:
    seen: set[str] = set()
    deduped: list[GameEvent] = []
    for event in events:
        event_id = str(event.to_json().get("event_id") or "")
        key = event_id or repr(event.to_json())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)
    return tuple(deduped)


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


def _execution_source_blocked_reason(reason: str, action_execution_plan) -> str:
    if reason == "missing_ability_phase_in_ability_file" and (
        action_execution_plan.damage_plan or action_execution_plan.toughness_plan
    ):
        return ""
    return reason


def _summon_execution_blocked_reason(state: BattleState, command: ActionCommand) -> str:
    actor = state.units.get(command.actor_id)
    if actor is None or not actor.flags.get("summon_kind"):
        return ""
    if actor.flags.get("timeline_admitted") is not True:
        return "summon_timeline_not_admitted"
    if actor.flags.get("summon_action_admitted") is not True:
        return "summon_action_admission_missing"
    runtime = state.global_flags.get("summon_runtime")
    if not isinstance(runtime, dict) or runtime.get("schema_version") != "p3_summon_runtime_v2":
        return "summon_runtime_state_missing"
    entities = runtime.get("entities")
    if not isinstance(entities, dict):
        return "summon_runtime_entities_missing"
    runtime_entity = entities.get(actor.unit_id)
    if not isinstance(runtime_entity, dict):
        return "summon_runtime_entity_missing"
    if runtime_entity.get("status", "active") != "active":
        return "summon_runtime_entity_not_active"
    runtime_source_trace = runtime_entity.get("source_trace")
    if not isinstance(runtime_source_trace, dict) or not runtime_source_trace:
        return "summon_runtime_source_trace_missing"
    source_intent_id = actor.flags.get("summon_intent_id")
    if source_intent_id is not None and runtime_entity.get("source_intent_id") != source_intent_id:
        return "summon_runtime_source_binding_mismatch"
    admission = actor.flags.get("summon_action_admission")
    if not isinstance(admission, dict) or admission.get("coverage_status") != "executable":
        return "summon_action_source_not_admitted"
    admission_source_trace = admission.get("source_trace")
    if not isinstance(admission_source_trace, dict) or not admission_source_trace:
        return "summon_action_source_trace_missing"
    return ""


def _summon_damage_stat_blocked_reason(
    state: BattleState,
    command: ActionCommand,
    action_definition: ActionDefinitionIR,
    action_execution_plan,
) -> str:
    actor = state.units.get(command.actor_id)
    if actor is None or not actor.flags.get("summon_kind"):
        return ""
    has_hp_damage_surface = (
        action_definition.damage_kind == "hp_damage"
        or bool(action_execution_plan.damage_emissions)
        or bool(action_execution_plan.damage_plan)
    )
    if not has_hp_damage_surface:
        return ""
    summon_kind = str(actor.flags.get("summon_kind") or "")
    if summon_kind == "summoned_monster":
        source_trace = actor.flags.get("combatant_profile_source_trace")
        if (
            actor.flags.get("combatant_profile_coverage_status") == "executable"
            and isinstance(source_trace, dict)
            and source_trace
        ):
            return ""
        return "summon_damage_stat_source_not_admitted"
    admission = actor.flags.get("summon_damage_stat_admission")
    if not isinstance(admission, dict):
        admission = actor.flags.get("servant_damage_stat_admission")
    if not isinstance(admission, dict) or admission.get("coverage_status") != "executable":
        return "summon_damage_stat_binding_not_admitted"
    source_trace = admission.get("source_trace")
    if not isinstance(source_trace, dict) or not source_trace:
        return "summon_damage_stat_source_trace_missing"
    return ""


def _uses_action_damage_plan_fallback(binding_reason: str, event_reason: str, action_execution_plan) -> bool:
    if not (action_execution_plan.damage_plan or action_execution_plan.toughness_plan):
        return False
    return "missing_ability_phase_in_ability_file" in {binding_reason, event_reason}


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


def _action_resource_plan_with_value_resolution(
    resolver: ValueResolver,
    command: ActionCommand,
    action_definition: ActionDefinitionIR,
    *,
    metadata: dict[str, JSONValue],
    queue_resource_policy: dict[str, JSONValue],
) -> tuple[ResourcePlan, tuple[str, ...]]:
    resolutions: dict[str, dict[str, JSONValue]] = {}
    blocked_reasons: list[str] = []
    values: dict[str, float] = {}
    for field_name in ("bp_need", "bp_add", "sp_base"):
        resolution = _action_definition_numeric_field_resolution(
            resolver,
            command,
            action_definition,
            field_name,
        )
        resolutions[field_name] = resolution.to_json()
        if resolution.ok and resolution.value is not None:
            values[field_name] = float(resolution.value)
        else:
            blocked_reasons.append(
                "resource_value_resolution_blocked:"
                f"{field_name}:{resolution.blocked_reason or 'unknown'}"
            )
    skill_point_delta = action_skill_point_delta(values.get("bp_need", 0.0), values.get("bp_add", 0.0))
    energy_gain = values.get("sp_base", 0.0)
    if queue_resource_policy.get("ignore_skill_point_delta") is True:
        skill_point_delta = 0
    if queue_resource_policy.get("ignore_energy_gain") is True:
        energy_gain = 0.0
    return (
        ResourcePlan(
            skill_point_delta=skill_point_delta,
            energy_gain=energy_gain,
            source="combat_executor.resources",
            metadata={
                **metadata,
                "resource_value_resolutions": resolutions,
                "value_resolver_admitted": not blocked_reasons,
            },
        ),
        tuple(blocked_reasons),
    )


def _action_definition_numeric_field_resolution(
    resolver: ValueResolver,
    command: ActionCommand,
    action_definition: ActionDefinitionIR,
    field_name: str,
) -> ValueResolution:
    return resolver.resolve(
        ValueBindingRequest(
            binding_kind="action_definition_numeric_field",
            field_name=field_name,
            required_context_keys=("action",),
            source_trace=action_definition.source.to_json(),
        ),
        ValueContext(
            actor_id=command.actor_id,
            owner_id=command.actor_id,
            action_id=action_definition.action_id,
            action_level=action_definition.level,
            source_trace=action_definition.source.to_json(),
        ),
    )


def _queue_action_resource_policy(command: ActionCommand) -> dict[str, JSONValue]:
    queue_parent = command.metadata.get("queue_parent") if isinstance(command.metadata, dict) else None
    if not isinstance(queue_parent, dict):
        return {}
    queue_entry = queue_parent.get("queue_entry")
    if not isinstance(queue_entry, dict):
        return {}
    source_trace = queue_entry.get("source_trace")
    if not isinstance(source_trace, dict):
        return {}
    policy = source_trace.get("queue_intent_resource_policy")
    return policy if isinstance(policy, dict) else {}


def _condition_skill_type(action_definition: ActionDefinitionIR) -> str:
    text = f"{action_definition.attack_type} {action_definition.skill_effect}".lower()
    if any(token in text for token in ("ultra", "ultimate")):
        return "Ultra"
    if any(token in text for token in ("bpskill", "skill")):
        return "Skill"
    return "Normal"


def _callback_kind_for_step(phase: str) -> str:
    if phase == "before_skill_use":
        return "OnStart"
    if phase == "before_attack":
        return "OnAttack"
    if phase == "after_skill_use":
        return "OnEnd"
    return ""


def _bounce_policy_for_profiles(rules: RuleBook, hit_profiles) -> dict[str, JSONValue]:
    for profile in hit_profiles:
        policy_id = getattr(profile, "bounce_policy_id", "")
        if not policy_id:
            continue
        policy = rules.bounce_policy(policy_id)
        if policy is not None:
            return policy.to_json()
    return {}


def _damage_packet(
    command: ActionCommand,
    action_definition: ActionDefinitionIR,
    source_trace: dict[str, object],
    damage_plan: DamagePlan,
    *,
    value_resolution: dict[str, JSONValue] | None = None,
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
        scaling_basis=damage_plan.scaling_basis,
        hit_source_trace=damage_plan.hit_source_trace,
        source_frame=DamageSourceFrame(
            owner_id=command.actor_id,
            source_id=f"action:{command.action_id}:level:{command.action_level}",
            source_kind="primary_action_damage",
            sequence_id=f"action:{command.actor_id}:{command.action_id}:level:{command.action_level}",
            target_id=damage_plan.target_id,
            can_continue_after_lethal=True,
            source_trace={
                "definition_id": action_definition.definition_id,
                "action_id": action_definition.action_id,
                "action_level": action_definition.level,
                "damage_emission_id": damage_plan.damage_emission_id,
                "source_task_id": damage_plan.source_task_id,
                "hit_profile_id": damage_plan.hit_profile_id,
            },
        ),
        metadata={
            **_damage_metadata(command),
            "value_resolution": value_resolution or {},
            "value_resolver_admitted": bool((value_resolution or {}).get("ok")),
            "damage_source_owner_id": command.actor_id,
            "damage_source_id": f"action:{command.action_id}:level:{command.action_level}",
            "damage_source_kind": "primary_action_damage",
            "damage_sequence_id": f"action:{command.actor_id}:{command.action_id}:level:{command.action_level}",
            "can_continue_after_lethal": True,
            "damage_custom_name": _damage_custom_name_from_trace(damage_plan.hit_source_trace),
            "hit_index": damage_plan.hit_index,
            "damage_emission_id": damage_plan.damage_emission_id,
            "source_task_id": damage_plan.source_task_id,
            "hit_profile_id": damage_plan.hit_profile_id,
            "target_group": damage_plan.target_group,
            "multiplier_source": damage_plan.multiplier_source,
            "scaling_ratio": damage_plan.scaling_ratio,
            "scaling_basis": damage_plan.scaling_basis,
            "hit_source_trace": damage_plan.hit_source_trace,
            "SkillType": _condition_skill_type(action_definition),
            "skill_type": _condition_skill_type(action_definition),
            "is_current_skill_active": True,
            "numeric_fidelity_status": damage_plan.numeric_fidelity_status,
            "hit_formula_slot_admitted": damage_plan.multiplier_source.get("source_kind")
            == "character_data_card_skill_formula",
            "multi_hit_source_status": (
                "character_data_card_slot"
                if damage_plan.multiplier_source.get("source_kind") == "character_data_card_skill_formula"
                else "non_card_or_blocked_source"
            ),
            "primary_action_target_id": damage_plan.primary_action_target_id,
            "current_hit_target_id": damage_plan.target_id,
            "per_hit_target_context_available": True,
            "per_hit_listener_admission_partial": True,
            "per_hit_target_context_not_implemented": False,
            "target_group_multiplier_not_implemented": damage_plan.target_group_multiplier_not_implemented,
            "target_selection_policy": damage_plan.target_selection_policy or {},
        },
    )


def _damage_value_resolution(
    resolver: ValueResolver,
    command: ActionCommand,
    action_definition: ActionDefinitionIR,
    damage_plan: DamagePlan,
) -> ValueResolution:
    value_context = damage_plan.value_context if isinstance(damage_plan.value_context, dict) else {}
    context = ValueContext(
        actor_id=command.actor_id,
        target_id=damage_plan.target_id,
        owner_id=command.actor_id,
        action_id=command.action_id,
        action_level=command.action_level,
        hit_id=damage_plan.hit_profile_id,
        hit_index=damage_plan.hit_index,
        data_card_id=str(value_context.get("data_card_id") or ""),
        data_card_kind=str(value_context.get("data_card_kind") or ""),
        source_trace=damage_plan.hit_source_trace,
    )
    return _resolve_plan_value_request(
        resolver,
        damage_plan.value_request,
        context,
        blocked_reason="damage_value_request_missing",
        fallback_source_trace=damage_plan.hit_source_trace,
    )


def _collect_direct_damage_modifiers(
    state: BattleState,
    rules: RuleBook,
    actor_id: str,
    target_id: str,
    packet: DamagePacket,
) -> tuple[tuple[dict[str, JSONValue], ...], tuple[dict[str, JSONValue], ...]]:
    if packet.damage_formula_family != "direct":
        return (), ()
    actor = state.units.get(actor_id)
    target = state.units.get(target_id)
    if actor is None or target is None:
        return (), ()
    details = actor.flags.get("status_details", ())
    if not isinstance(details, (list, tuple)):
        return (), ()
    evaluator = RuleEvaluator()
    terms: list[dict[str, JSONValue]] = []
    records: list[dict[str, JSONValue]] = []
    event_payload = {
        **packet.metadata,
        "target_id": target_id,
        "current_hit_target_id": target_id,
        "param_entity_id": target_id,
        "damage_custom_name": packet.metadata.get("damage_custom_name"),
        "attack_type": packet.attack_type,
        "AttackType": packet.attack_type,
        "SkillType": packet.metadata.get("SkillType"),
        "skill_type": packet.metadata.get("skill_type"),
    }
    for detail in details:
        if not isinstance(detail, dict):
            continue
        modifier_name = str(detail.get("modifier_name") or "")
        owner_id = str(detail.get("owner_id") or actor_id)
        callback_ids = _trigger_ids_for_detail_event(detail, "OnBeforeHitAll")
        callbacks = rules.status_callbacks_for_modifier_event_scope(modifier_name, "OnBeforeHitAll", "actor_local")
        if callback_ids is not None:
            callbacks = tuple(callback for callback in callbacks if callback.callback_id in callback_ids)
        for callback in callbacks:
            callback_terms, callback_records = _collect_callback_damage_modifiers(
                state,
                rules,
                evaluator,
                callback_id=callback.callback_id,
                actor_id=actor_id,
                owner_id=owner_id,
                target_id=target_id,
                detail=detail,
                event_payload=event_payload,
            )
            terms.extend(callback_terms)
            records.extend(callback_records)
    return tuple(terms), tuple(records)


def _collect_callback_damage_modifiers(
    state: BattleState,
    rules: RuleBook,
    evaluator: RuleEvaluator,
    *,
    callback_id: str,
    actor_id: str,
    owner_id: str,
    target_id: str,
    detail: dict[str, JSONValue],
    event_payload: dict[str, JSONValue],
) -> tuple[tuple[dict[str, JSONValue], ...], tuple[dict[str, JSONValue], ...]]:
    tasks = {task.task_id: task for task in rules.status_callback_tasks_for_callback(callback_id)}
    roots = tuple(sorted((task for task in tasks.values() if not task.parent_task_id), key=lambda item: (item.task_index, item.task_id)))
    terms: list[dict[str, JSONValue]] = []
    records: list[dict[str, JSONValue]] = []
    binding_sources = (
        *status_binding_sources(state, tuple(unit_id for unit_id in (actor_id, owner_id, target_id) if unit_id)),
        binding_source_from_store(store_from_state(state)),
    )
    for root in roots:
        selected_ids: tuple[str, ...]
        condition_result: dict[str, JSONValue] = {}
        if root.opcode == "PredicateTaskList":
            condition = rules.condition(root.condition_id) if root.condition_id else None
            if condition is None:
                records.append(_damage_modifier_record(root.task_id, "blocked", "missing_predicate_condition", {}, ()))
                continue
            result = evaluator.evaluate_condition_result(
                condition,
                EvaluationContext(
                    state=state,
                    actor_id=actor_id,
                    owner_id=owner_id,
                    target_id=target_id,
                    param_entity_id=target_id,
                    current_action_target_id=target_id,
                    status_detail=detail,
                    event_payload=dict(event_payload),
                    binding_sources=binding_sources,
                ),
            )
            condition_result = result.to_json()
            if not result.ok or result.result is None:
                records.append(_damage_modifier_record(root.task_id, "blocked", result.reason, condition_result, ()))
                continue
            if not result.result:
                records.append(_damage_modifier_record(root.task_id, "skipped", "condition_false", condition_result, ()))
                continue
            selected_ids = root.success_task_ids
        else:
            selected_ids = (root.task_id,)
        for child_id in selected_ids:
            child = tasks.get(child_id)
            if child is None:
                continue
            for modifier in rules.damage_modifiers_for_callback(callback_id):
                if modifier.source_task_id != child.task_id:
                    continue
                if modifier.coverage_status != "executable":
                    records.append(_damage_modifier_record(child.task_id, "blocked", modifier.blocked_reason or "damage_modifier_not_executable", condition_result, (modifier.to_json(),)))
                    continue
                applied_terms: list[dict[str, JSONValue]] = []
                for term in modifier.modifier_terms:
                    evaluation = evaluator.evaluate_numeric(
                        term.get("numeric_expr"),
                        NumericEvaluationContext(
                            binding_sources=binding_sources,
                            source_trace=modifier.source.to_json(),
                        ),
                    )
                    if not evaluation.ok or evaluation.value is None:
                        records.append(_damage_modifier_record(child.task_id, "blocked", evaluation.blocked_reason or "damage_modifier_numeric_blocked", condition_result, (modifier.to_json(),)))
                        continue
                    applied = {
                        **term,
                        "value": evaluation.value,
                        "source_type": "damage_modifier_ir",
                        "source_id": modifier.damage_modifier_id,
                        "damage_modifier_id": modifier.damage_modifier_id,
                        "callback_id": callback_id,
                        "source_task_id": child.task_id,
                        "condition": "OnBeforeHitAll_condition_passed",
                        "numeric_evaluation": evaluation.to_json(),
                        "source_trace": modifier.source.to_json(),
                    }
                    terms.append(applied)
                    applied_terms.append(applied)
                records.append(_damage_modifier_record(child.task_id, "applied" if applied_terms else "skipped", "", condition_result, tuple(applied_terms)))
    return tuple(terms), tuple(records)


def _damage_modifier_record(
    task_id: str,
    status: str,
    reason: str,
    condition_result: dict[str, JSONValue],
    terms: tuple[dict[str, JSONValue], ...],
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="damage_modifier",
        source="damage_modifier_system",
        process_only=True,
        payload={
            "task_id": task_id,
            "status": status,
            "reason": reason,
            "condition_result": condition_result,
            "terms": list(terms),
        },
        trace={
            "task_id": task_id,
            "terms": [term.get("source_trace") for term in terms],
        },
    ).to_json()


def _trigger_ids_for_detail_event(detail: dict[str, JSONValue], event: str) -> tuple[str, ...] | None:
    mapping = detail.get("trigger_ids_by_event")
    if not isinstance(mapping, dict):
        return None
    value = mapping.get(event)
    if not isinstance(value, list):
        return None
    return tuple(str(item) for item in value if isinstance(item, str) and item)


def _bounce_policy_from_damage_plan(damage_plan: DamagePlan) -> dict[str, JSONValue]:
    policy = (damage_plan.target_selection_policy or {}).get("bounce_policy")
    return policy if isinstance(policy, dict) else {}


def _damage_custom_name_from_trace(trace: dict[str, object]) -> str:
    evidence = trace.get("evidence")
    if isinstance(evidence, dict):
        value = evidence.get("damage_custom_name")
        if isinstance(value, str):
            return value
    return ""


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


def _toughness_packet(
    command: ActionCommand,
    toughness_plan: ToughnessPlan,
    *,
    value_resolution: dict[str, JSONValue] | None = None,
) -> ToughnessPacket:
    amount = value_resolution.get("value") if isinstance(value_resolution, dict) else None
    amount_value = float(amount) if isinstance(amount, (int, float)) and not isinstance(amount, bool) else None
    coverage_status = "executable" if not toughness_plan.blocked_reason and bool((value_resolution or {}).get("ok")) else "blocked"
    return ToughnessPacket(
        attacker_id=command.actor_id,
        target_id=toughness_plan.target_id,
        toughness_emission_id=toughness_plan.toughness_emission_id,
        source_task_id=toughness_plan.source_task_id,
        hit_profile_id=toughness_plan.hit_profile_id,
        element_type=toughness_plan.element_type,
        amount=amount_value,
        amount_expr=toughness_plan.toughness_amount_expr,
        target_group=toughness_plan.target_group,
        coverage_status=coverage_status,
        source_trace=toughness_plan.source_trace,
        metadata={
            "primary_action_target_id": toughness_plan.primary_action_target_id,
            "toughness_amount_expr": toughness_plan.toughness_amount_expr,
            "value_resolution": value_resolution or {},
            "value_resolver_admitted": bool((value_resolution or {}).get("ok")),
            "source_trace": toughness_plan.source_trace,
        },
    )


def _toughness_value_resolution(
    resolver: ValueResolver,
    command: ActionCommand,
    action_definition: ActionDefinitionIR,
    toughness_plan: ToughnessPlan,
) -> ValueResolution:
    context = ValueContext(
        actor_id=command.actor_id,
        target_id=toughness_plan.target_id,
        owner_id=command.actor_id,
        action_id=action_definition.action_id,
        action_level=action_definition.level,
        hit_id=toughness_plan.hit_profile_id,
        hit_index=toughness_plan.hit_index,
        dynamic_values={} if toughness_plan.value_binding_sources else None,
        binding_sources=toughness_plan.value_binding_sources,
        source_trace=toughness_plan.source_trace,
    )
    return _resolve_plan_value_request(
        resolver,
        toughness_plan.value_request,
        context,
        blocked_reason="toughness_value_request_missing",
        fallback_source_trace=toughness_plan.source_trace,
    )


def _resolve_plan_value_request(
    resolver: ValueResolver,
    request_data: object,
    context: ValueContext,
    *,
    blocked_reason: str,
    fallback_source_trace: dict[str, JSONValue],
) -> ValueResolution:
    request_dict = request_data if isinstance(request_data, dict) else {}
    binding_kind = str(request_dict.get("binding_kind") or "")
    if not binding_kind or binding_kind == "blocked":
        return _blocked_plan_value_resolution(
            request_dict,
            context,
            reason=str(request_dict.get("blocked_reason") or blocked_reason),
            source_trace=_request_source_trace(request_dict, fallback_source_trace),
        )
    request = ValueBindingRequest(
        binding_kind=binding_kind,
        binding_id=str(request_dict.get("binding_id") or ""),
        param_index=_int_or_none(request_dict.get("param_index")),
        formula_role=str(request_dict.get("formula_role") or ""),
        field_name=str(request_dict.get("field_name") or ""),
        expression=request_dict.get("expression"),
        required_context_keys=tuple(str(item) for item in request_dict.get("required_context_keys") or ()),
        source_trace=_request_source_trace(request_dict, fallback_source_trace),
    )
    return resolver.resolve(request, context)


def _blocked_plan_value_resolution(
    request_data: dict[str, object],
    context: ValueContext,
    *,
    reason: str,
    source_trace: dict[str, JSONValue],
) -> ValueResolution:
    safe_request = _json_safe(request_data)
    return ValueResolution(
        ok=False,
        value=None,
        binding_kind=str(request_data.get("binding_kind") or "blocked"),
        source_trace=source_trace,
        context_trace=context.to_trace(),
        blocked_reason=reason,
        request=safe_request if isinstance(safe_request, dict) else {},
        delegate_resolution={},
        context_keys=context.available_keys(),
    )


def _request_source_trace(
    request_data: dict[str, object],
    fallback_source_trace: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    trace = request_data.get("source_trace")
    if isinstance(trace, dict):
        safe_trace = _json_safe(trace)
        return safe_trace if isinstance(safe_trace, dict) else fallback_source_trace
    return fallback_source_trace


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _json_safe(value: object) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _command_with_character_card_level_bonus(
    command: ActionCommand,
    state: BattleState,
    rules: RuleBook,
) -> ActionCommand:
    unit = state.units.get(command.actor_id)
    if unit is None:
        return command
    bonuses = unit.flags.get("eidolon_skill_level_bonus_by_action_id")
    if not isinstance(bonuses, dict):
        return command
    raw_bonus = bonuses.get(command.action_id)
    if not isinstance(raw_bonus, (int, float)) or raw_bonus <= 0:
        return command
    levels = rules.action_levels(command.action_id)
    if not levels:
        return command
    requested_level = command.action_level
    effective_level = min(max(levels), requested_level + int(raw_bonus))
    if effective_level == requested_level:
        return command
    sources = unit.flags.get("eidolon_skill_level_bonus_sources")
    source_payload = sources.get(command.action_id, []) if isinstance(sources, dict) else []
    metadata = {
        **command.metadata,
        "requested_action_level": requested_level,
        "effective_action_level": effective_level,
        "effective_action_level_bonus": int(raw_bonus),
        "effective_action_level_source": {
            "source_kind": "character_data_card_eidolon_skill_level_bonus",
            "action_id": command.action_id,
            "requested_level": requested_level,
            "effective_level": effective_level,
            "bonus": int(raw_bonus),
            "sources": source_payload if isinstance(source_payload, list) else [],
        },
    }
    return replace(command, action_level=effective_level, metadata=metadata)


def _damage_metadata(command: ActionCommand) -> dict[str, JSONValue]:
    metadata: dict[str, JSONValue] = {}
    crit_mode = command.metadata.get("crit_mode")
    if isinstance(crit_mode, str):
        metadata["crit_mode"] = crit_mode
    rng_choices = command.metadata.get("rng_choices")
    if isinstance(rng_choices, dict):
        metadata["rng_choices"] = {str(key): value for key, value in rng_choices.items()}
    rng_mode = command.metadata.get("rng_mode")
    if isinstance(rng_mode, str):
        metadata["rng_mode"] = rng_mode
    metadata["is_current_skill_active"] = True
    metadata["is_insert_action"] = command.source == "queue"
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
