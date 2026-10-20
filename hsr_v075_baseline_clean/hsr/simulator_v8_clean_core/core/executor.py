from __future__ import annotations

from dataclasses import replace

from .action_audit import action_source_records
from .action_plan import DamagePlan, ToughnessPlan, build_action_execution_plan
from .atomic_commit import (
    events_for_atomic_result,
    finalize_selected_execution_graph,
    records_for_atomic_result,
    rng_events_for_atomic_result,
)
from .model import (
    ActionCommand,
    ActionSettlement,
    ActionTransaction,
    BattleState,
    BattleTransition,
    GameEvent,
    JSONValue,
    Mutation,
    RNGEvent,
    TargetResolution,
)
from .reducer import MutationReducer
from .settlement import SettlementRecord
from .transition_outcome import ExecutionNodeResult
from ..rules.evaluator import NumericEvaluationContext, RuleEvaluator
from ..rules.ir import (
    AbilityTaskIR,
    ActionDefinitionIR,
    StatusCallbackIR,
    StatusCallbackTaskIR,
)
from ..rules.rulebook import RuleBook
from ..rules.task_graph import (
    TaskGraphIR,
    TaskGraphNodeIR,
)
from ..rules.value_binding import ValueBindingRequest, ValueContext, ValueResolution, ValueResolver
from ..systems.ability import AbilityTaskExecutionResult, AbilityTaskSystem
from ..systems.action_contract import (
    ActionContractDecision,
    ActionContractSystem,
    ActionSubmissionAuthorization,
)
from ..systems.action_selection import (
    ActionTargetSelectionContext,
    ActionTargetSelectionSystem,
)
from ..systems.action_event_contract import (
    _issue_action_window_expected_scope,
    condition_skill_type as _condition_skill_type,
    damage_listener_window_event as _damage_listener_window_event,
    derived_post_action_listener_event as _derived_post_action_listener_event,
)
from ..systems.action_preflight import (
    action_binding_blocked_reason,
    action_energy_gain,
    action_event_blocked_reason,
    action_skill_point_delta,
    combined_blocked_reason,
)
from ..systems.break_system import BreakApplicationResult, BreakSystem
from ..systems.damage import DamageModifierContribution, DamagePacket, DamageSystem, DamageSourceFrame, DamageWindowLedger
from ..systems.dynamic_values import binding_source_from_store, status_binding_sources, store_from_state
from ..systems.effect import EffectRegistry
from ..systems.resource import ResourcePlan, ResourceSystem
from ..systems.skill_properties import (
    resolve_skill_property_overrides,
    skill_property_override_evidence,
    skill_property_override_plan,
)
from ..systems.rng import rng_choices_from_payload, validate_rng_choice_ledger
from ..systems.status import StatusSystem
from ..systems.summon import SummonSystem
from ..systems.summon_runtime import validate_summon_runtime
from ..systems.target import TargetSystem, resolve_action_bounce_policy
from ..systems.unit_relation import TargetEvaluationContext, committed_turn_owner_id
from ..systems.timeline import TimelinePlan, TimelineSystem
from ..systems.unit_lifecycle import UnitLifecycleSystem
from ..systems.toughness import ToughnessPacket, ToughnessSystem
from ..systems.event_dispatch import (
    MAX_CALLBACK_EMITTED_EVENT_DEPTH,
    EventDispatchResult,
    EventDispatchSystem,
    EventNormalization,
)
from ..systems.mutation_events import (
    MUTATION_BACKED_EVENT_TYPES,
    before_toughness_calculation_event,
    events_for_mutation,
)


class _EventIdentityConflict(ValueError):
    def __init__(self, event_id: str, conflict_field: str) -> None:
        self.event_id = event_id
        self.conflict_field = conflict_field
        self.reason_code = f"event_identity_conflict:{conflict_field}"
        super().__init__(f"{self.reason_code}:{event_id}")


class CombatExecutor:
    """v8 action executor boundary."""

    def __init__(self, rules: RuleBook):
        self.rules = rules
        self.reducer = MutationReducer()
        self.resources = ResourceSystem()
        self.targets = TargetSystem(rules)
        self.action_targets = ActionTargetSelectionSystem(rules)
        self.timeline = TimelineSystem()
        self.lifecycle = UnitLifecycleSystem()
        self.damage = DamageSystem(rules)
        self.toughness = ToughnessSystem(rules)
        self.status = StatusSystem(rules)
        self.summons = SummonSystem(rules)
        self.effects = EffectRegistry(self.status)
        self.breaks = BreakSystem(rules, self.effects, reducer=self.reducer, damage=self.damage)
        self.event_dispatcher = EventDispatchSystem(rules, self.effects, reducer=self.reducer, damage=self.damage)
        self.ability_tasks = AbilityTaskSystem(
            rules,
            self.effects,
            reducer=self.reducer,
            damage=self.damage,
            event_dispatcher=self.event_dispatcher,
        )
        self.value_resolver = ValueResolver(rules)
        self.action_contract = ActionContractSystem(rules)

    def commit_eventful_transition(
        self,
        state: BattleState,
        *,
        mutations: tuple[Mutation, ...],
        events: tuple[GameEvent, ...],
        records: tuple[dict[str, JSONValue], ...] = (),
        rng_events: tuple[RNGEvent, ...] = (),
        producer_kind: str,
        producer_id: str,
        actor_id: str | None = None,
        producer_ok: bool = True,
        blocked_reason: str = "",
        dispatched_event_ids: frozenset[str] = frozenset(),
        event_normalizations: tuple[EventNormalization, ...] = (),
    ) -> EventDispatchResult:
        """Publish a system result only after its events complete on the candidate."""

        producer_reason = (
            ""
            if producer_ok
            else blocked_reason or f"{producer_kind or 'eventful_transition'}_blocked"
        )
        identity_conflict: _EventIdentityConflict | None = None
        try:
            events = _eventful_transition_events(
                state,
                mutations,
                events,
                producer_id=producer_id,
                actor_id=actor_id,
                event_normalizations=event_normalizations,
            )
        except _EventIdentityConflict as conflict:
            events = ()
            identity_conflict = conflict
        events = tuple(
            event
            if event.event_id
            else replace(
                event,
                event_id=(
                    f"event:{state.event_index}:eventful:"
                    f"{producer_kind or 'transition'}:{producer_id or 'unknown'}:"
                    f"{index}:{event.event_type}"
                ),
            )
            for index, event in enumerate(events)
        )
        producer_node = ExecutionNodeResult(
            node_kind=producer_kind or "eventful_transition",
            node_id=producer_id or producer_kind or "unknown",
            status="complete" if producer_ok else "blocked",
            reason_code=producer_reason,
        )
        reduction = self.reducer.apply_all_result(state, mutations)
        current_state = (
            reduction.after_state
            if producer_ok and reduction.ok and identity_conflict is None
            else state
        )
        node_results: list[ExecutionNodeResult] = [producer_node]
        dispatch_mutations: list[Mutation] = []
        dispatch_events: list[GameEvent] = []
        dispatch_rng_events: list[RNGEvent] = []
        dispatch_records: list[dict[str, JSONValue]] = []
        listener_records: list[dict[str, JSONValue]] = []
        all_event_normalizations = list(event_normalizations)
        errors: list[str] = []
        creation_targets: set[str] = set()
        consumed_event_ids = set(dispatched_event_ids)

        if identity_conflict is not None:
            errors.append(identity_conflict.reason_code)
            node_results.append(
                ExecutionNodeResult(
                    node_kind="event_identity",
                    node_id=identity_conflict.event_id,
                    status="blocked",
                    reason_code=identity_conflict.reason_code,
                )
            )
        elif producer_ok and not reduction.ok:
            conflict = reduction.conflicts[0].code if reduction.conflicts else "unknown"
            reason = f"eventful_transition_reducer_conflict:{conflict}"
            errors.append(reason)
            node_results.append(
                ExecutionNodeResult(
                    node_kind="mutation_reducer",
                    node_id=producer_id or producer_kind or "unknown",
                    status="blocked",
                    reason_code=reason,
                )
            )
        elif producer_ok:
            for event in events:
                callback_events = event.payload.get("callback_events")
                is_creation_event = (
                    event.event_type in {"unit.created", "summon.spawned"}
                    or (
                        isinstance(callback_events, (list, tuple))
                        and "OnListenCharacterCreate" in callback_events
                    )
                )
                creation_target = str(event.target_id or "") if is_creation_event else ""
                if creation_target and creation_target in creation_targets:
                    reason = "duplicate_unit_creation_event"
                    errors.append(reason)
                    node_results.append(
                        ExecutionNodeResult(
                            node_kind="event_dispatch",
                            node_id=event.event_id or event.event_type,
                            status="blocked",
                            reason_code=reason,
                        )
                    )
                    break
                if creation_target:
                    creation_targets.add(creation_target)
                if str(event.to_json()["event_id"]) in consumed_event_ids:
                    continue
                dispatched = self.event_dispatcher.dispatch_event(
                    current_state,
                    event=event,
                )
                current_state = dispatched.after_state
                consumed_event_ids.update(dispatched.dispatched_event_ids)
                dispatch_mutations.extend(dispatched.mutations)
                dispatch_events.extend(dispatched.events)
                dispatch_rng_events.extend(dispatched.rng_events)
                dispatch_records.extend(dispatched.records)
                listener_records.extend(dispatched.listener_records)
                all_event_normalizations.extend(
                    dispatched.event_normalizations
                )
                errors.extend(dispatched.errors)
                node_results.extend(dispatched.node_results)
                if dispatched.errors:
                    break

        transaction_events: tuple[GameEvent, ...] = ()
        if identity_conflict is None:
            try:
                transaction_events = _dedupe_events(
                    *events,
                    *dispatch_events,
                    event_normalizations=tuple(
                        all_event_normalizations
                    ),
                )
            except _EventIdentityConflict as conflict:
                identity_conflict = conflict
                errors.append(conflict.reason_code)
                node_results.append(
                    ExecutionNodeResult(
                        node_kind="event_identity",
                        node_id=conflict.event_id,
                        status="blocked",
                        reason_code=conflict.reason_code,
                    )
                )
        planned_mutations = (*mutations, *dispatch_mutations)
        identity_blocked_reason = (
            identity_conflict.reason_code
            if identity_conflict is not None
            else ""
        )
        atomic_commit = finalize_selected_execution_graph(
            state,
            current_state,
            planned_mutations,
            tuple(node_results),
            reducer=self.reducer,
            preflight_blocked=(
                not producer_ok or identity_conflict is not None
            ),
            preflight_reason=(
                producer_reason
                if not producer_ok
                else identity_blocked_reason
            ),
        )
        atomic_record = SettlementRecord(
            record_type="eventful_transition_atomic_commit",
            source="combat_executor",
            process_only=True,
            payload={
                "producer_kind": producer_kind,
                "producer_id": producer_id,
                "outcome": atomic_commit.outcome.to_json(),
                "evidence": atomic_commit.evidence,
            },
        ).to_json()
        if not atomic_commit.outcome.successor_eligible:
            errors.extend(atomic_commit.outcome.reason_codes)
        return EventDispatchResult(
            after_state=atomic_commit.after_state,
            mutations=atomic_commit.committed_mutations,
            events=(
                ()
                if identity_conflict is not None
                else events_for_atomic_result(
                    transaction_events,
                    atomic_commit,
                )
            ),
            rng_events=rng_events_for_atomic_result(
                (*rng_events, *dispatch_rng_events),
                atomic_commit,
            ),
            records=records_for_atomic_result(
                (*records, *dispatch_records, atomic_record),
                atomic_commit,
            ),
            listener_records=tuple(listener_records),
            errors=tuple(dict.fromkeys(error for error in errors if error)),
            node_results=atomic_commit.outcome.node_results,
            dispatched_event_ids=frozenset(consumed_event_ids) if atomic_commit.outcome.successor_eligible else frozenset(),
            event_normalizations=tuple(all_event_normalizations) if atomic_commit.outcome.successor_eligible else (),
        )

    def execute(
        self,
        command: ActionCommand,
        state: BattleState,
        *,
        submission_authorization: ActionSubmissionAuthorization | None = None,
        target_selection_context: ActionTargetSelectionContext | None = None,
    ) -> tuple[BattleState, BattleTransition]:
        before = state.snapshot()
        target_context_reason = self.action_targets.context_identity_blocked_reason(
            command,
            target_selection_context,
        )
        if target_context_reason:
            return state, _action_target_context_blocked_transition(
                state,
                command,
                target_context_reason,
            )
        assert target_selection_context is not None
        queue_resource_policy = _queue_action_resource_policy(command)
        action_contract = self.action_contract.evaluate(
            state,
            command,
            authorization=submission_authorization,
            target_selection_fingerprint=target_selection_context.context_fingerprint,
            queue_resource_policy=queue_resource_policy,
        )
        if not action_contract.ok:
            return state, _action_contract_blocked_transition(
                state,
                command,
                action_contract,
            )
        action_execution_token = object()
        action_definition = self.rules.require_action_definition(command.action_id, command.action_level)
        action_event_ir = self.rules.require_action_event(command.action_id, command.action_level)
        action_binding = self.rules.action_ability_binding(command.action_id, command.action_level)
        ability_phases = self.rules.ability_phases_for_action(command.action_id, command.action_level)
        ability_tasks = self.rules.ability_tasks_for_action(command.action_id, command.action_level)
        hit_profiles = self.rules.hit_profiles_for_action(command.action_id, command.action_level)
        damage_emissions = self.rules.damage_emissions_for_action(command.action_id, command.action_level)
        toughness_emissions = self.rules.toughness_emissions_for_action(command.action_id, command.action_level)
        bounce_expected = bool(
            action_event_ir.target_mode == "bounce"
            or any(profile.bounce_policy_id for profile in hit_profiles)
        )
        bounce_resolution = (
            resolve_action_bounce_policy(
                self.rules,
                command.action_id,
                command.action_level,
                hit_profiles=hit_profiles,
                actor_entity_ref=(
                    state.units[command.actor_id].template_id
                    if command.actor_id in state.units
                    else ""
                ),
            )
            if bounce_expected
            else None
        )
        bounce_policy = (
            bounce_resolution.policy
            if bounce_resolution is not None and bounce_resolution.resolved
            else None
        )
        bounce_policy_blocked_reason = (
            bounce_resolution.blocked_reason
            if bounce_resolution is not None and not bounce_resolution.resolved
            else "bounce_action_target_mode_mismatch"
            if bounce_policy is not None and action_event_ir.target_mode != "bounce"
            else ""
        )
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
        target_result = self.action_targets.resolve_impact(
            state,
            command,
            target_selection_context,
            action_event_ir,
        )
        action_target_fact = target_result.admitted_action_target_fact
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
                "bounce_policy_id": bounce_policy.bounce_policy_id if bounce_policy else "",
            },
            toughness_emissions=toughness_emissions,
        )
        action_event_plan_payload = _action_event_plan_compat_payload(action_definition, action_event_ir)
        ultimate_rule, ultimate_rule_reason = (
            self.rules.select_resource_rule("ultimate_energy_cost")
            if action_definition.attack_type == "Ultra" else (None, "")
        )
        resource_plan, resource_value_blocked_reasons = _action_resource_plan_with_value_resolution(
            self.value_resolver,
            command,
            action_definition,
            state=state,
            metadata={
                **action_source_metadata,
                "queue_resource_policy": queue_resource_policy,
                **({
                    "resource_rule_id": ultimate_rule.resource_rule_id,
                    "resource_rule_source": ultimate_rule.source.to_json(),
                } if ultimate_rule is not None else {}),
            },
            queue_resource_policy=queue_resource_policy,
        )
        if ultimate_rule_reason:
            resource_value_blocked_reasons += (ultimate_rule_reason,)
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
        ability_task_damage_authoritative = _ability_task_damage_graph_authoritative(
            self.rules,
            ability_phases,
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
            bounce_policy_blocked_reason,
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
                    preserve_turn_owner=(
                        submission_authorization is not None
                        and submission_authorization.submission_mode == "queue"
                        and submission_authorization.window in {"ultimate", "insert_action"}
                    ),
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
        if action_enabled and action_definition.attack_type == "Ultra":
            prepare_event = GameEvent(
                event_type="action.ultimate.prepare",
                source_id=command.actor_id,
                target_id=command.actor_id,
                event_id=(
                    f"event:{current_state.event_index}:ultimate_prepare:"
                    f"{command.actor_id}:{command.action_id}:{command.action_level}"
                ),
                window="OnUltraSkillPrepare",
                process_only=True,
                payload={
                    "callback_events": ["OnUltraSkillPrepare"],
                    "listener_scope": "owner_local",
                    "action_id": command.action_id,
                    "action_level": command.action_level,
                    "actor_id": command.actor_id,
                    "attacker_id": command.actor_id,
                    "target_id": command.actor_id,
                    "param_entity_id": command.actor_id,
                    "selected_target_ids": list(target_result.resolution.selected),
                    "attack_type": action_definition.attack_type,
                    "skill_type": _condition_skill_type(action_definition),
                    "source_trace": action_definition_trace,
                },
            )
            prepare_result = self.event_dispatcher.dispatch_event(
                current_state,
                event=prepare_event,
            )
            current_state = prepare_result.after_state
            listener_dispatch_results.append(prepare_result)
            ordered_mutations.extend(prepare_result.mutations)
            runtime_records.extend(prepare_result.records)
            events = (*events, prepare_event, *prepare_result.events)
        applied_resource_mutations: list[Mutation] = []
        if action_enabled:
            # Each grant samples the state after earlier resource listeners finish.
            resource_steps = (
                replace(resource_plan, energy_cost=0.0, energy_gain=0.0),
                replace(resource_plan, skill_point_delta=0, energy_gain=0.0),
                replace(resource_plan, skill_point_delta=0, energy_cost=0.0),
            )
            for resource_step in resource_steps:
                step_result = self.resources.plan_action_resources(current_state, command.actor_id, resource_step)
                if not step_result.ok:
                    resource_result = step_result
                    action_enabled = False
                    blocked_reason = ",".join(step_result.errors)
                    execution_node_results.append(ExecutionNodeResult(
                        node_kind="resource_plan", node_id=action_definition.definition_id,
                        status="blocked", reason_code=blocked_reason,
                    ))
                    break
                for mutation in step_result.mutations:
                    applied_resource_mutations.append(mutation)
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
        resource_mutations = tuple(applied_resource_mutations)
        damage_results = []
        target_rng_events = list(target_result.rng_events)
        damage_mutations: tuple[Mutation, ...] = ()
        toughness_results = []
        toughness_mutations: tuple[Mutation, ...] = ()
        break_results: list[BreakApplicationResult] = []
        break_mutations: tuple[Mutation, ...] = ()
        ability_task_results: list[AbilityTaskExecutionResult] = []
        damage_window_ledger = DamageWindowLedger()
        action_damage_modifiers: list[DamageModifierContribution] = []
        sequence_modifiers: dict[tuple[str, str], tuple[DamageModifierContribution, ...]] = {}
        target_modifiers: dict[str, tuple[DamageModifierContribution, ...]] = {}
        action_hit_targets: list[str] = []
        hit_sequence_order: list[tuple[str, str]] = []
        hit_sequence_context: dict[
            tuple[str, str],
            dict[str, JSONValue],
        ] = {}
        hit_sequence_is_critical: dict[tuple[str, str], bool] = {}
        hit_sequence_final_damage: dict[tuple[str, str], float] = {}
        target_hit_sequence_is_critical: dict[str, bool] = {}
        target_hit_sequence_final_damage: dict[str, float] = {}
        target_hit_sequences_started: set[str] = set()

        def dispatch_listener_window(event: GameEvent) -> tuple[DamageModifierContribution, ...]:
            nonlocal current_state
            result = self.event_dispatcher.dispatch_event(
                current_state,
                event=event,
                damage_window_ledger=damage_window_ledger,
            )
            current_state = result.after_state
            listener_dispatch_results.append(result)
            ordered_mutations.extend(result.mutations)
            runtime_records.extend(result.records)
            return result.damage_modifiers

        def dispatch_ability_events(
            ability_result: AbilityTaskExecutionResult,
        ) -> None:
            nonlocal current_state, action_target_fact
            action_hit_targets.extend(ability_result.hit_target_ids)
            if ability_result.hit_target_ids and (
                target_selection_context.dynamic_target or action_event_ir.target_mode == "bounce"
            ):
                action_target_fact = action_target_fact.with_resolved_targets(tuple(dict.fromkeys(action_hit_targets)))
            dispatched_event_ids = (
                ability_result.dispatched_event_ids
                if ability_result.dispatched_event_ids is not None
                else _dispatched_event_ids(ability_result.records)
            )
            for emitted_event in ability_result.events:
                if str(emitted_event.to_json()["event_id"]) in dispatched_event_ids:
                    continue
                if emitted_event.event_type not in {
                    "status.lifecycle",
                    "damage.hit",
                    "toughness.hit",
                    "break.triggered",
                    "unit.defeated",
                    "custom.event",
                    "summon.spawned",
                    "summon.removed",
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

        if action_enabled:
            pending_before_callbacks: list[str] = []
            for step_index, step in enumerate(action_execution_plan.event_steps):
                callback_kinds: tuple[str, ...] = ()
                if step.kind == "trigger_window":
                    callback_kind = _callback_kind_for_step(step.phase)
                    if callback_kind and not use_action_damage_plan_fallback:
                        if step.phase in {"before_skill_use", "before_attack"}:
                            pending_before_callbacks.append(callback_kind)
                        else:
                            callback_kinds = (callback_kind,)
                if step.kind == "damage" or (
                    step.kind == "trigger_window"
                    and step.phase not in {"before_skill_use", "before_attack"}
                ):
                    # OnStart can run the complete damage graph. Finish both
                    # action pre-windows before invoking it, including for
                    # actions whose source graph contains no damage stage.
                    callback_kinds = (*pending_before_callbacks, *callback_kinds)
                    pending_before_callbacks.clear()
                for callback_kind in callback_kinds:
                    ability_result = self.ability_tasks.execute_callback(
                        current_state,
                        phases=ability_phases,
                        callback_kind=callback_kind,
                        command=command,
                        action_definition=action_definition,
                        target_resolution=target_result.resolution,
                        action_damage_modifiers=tuple(action_damage_modifiers),
                        admitted_action_target_fact=action_target_fact,
                        action_execution_token=action_execution_token,
                    )
                    current_state = ability_result.after_state
                    ability_task_results.append(ability_result)
                    ordered_mutations.extend(ability_result.mutations)
                    runtime_records.extend(ability_result.records)
                    dispatch_ability_events(ability_result)
                if step.kind == "trigger_window":
                    dispatch_event, expected_window_scope = _action_window_dispatch_event(
                        current_state,
                        command,
                        action_definition,
                        action_event_id=action_event_ir.action_event_id,
                        action_event_source=action_event_ir.source.to_json(),
                        step=step,
                        target_resolution=target_result.resolution,
                        action_target_fact=action_target_fact,
                        action_execution_token=action_execution_token,
                        impact_fingerprint=target_result.impact_fingerprint,
                        step_index=step_index,
                        primary_target_id=(
                            action_execution_plan.primary_action_target_id
                        ),
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
                    listener_result = self.event_dispatcher.dispatch_action_window_listeners(
                        current_state,
                        event=dispatch_event,
                        damage_window_ledger=damage_window_ledger,
                        nested_ability_provider=(
                            self.ability_tasks.formal_status_nested_ability_provider()
                        ),
                        expected_window_scope=expected_window_scope,
                    )
                    current_state = listener_result.after_state
                    trigger_results.append(listener_result)
                    ordered_mutations.extend(listener_result.mutations)
                    runtime_records.extend(listener_result.records)
                    if step.phase == "before_attack":
                        action_damage_modifiers.extend(listener_result.damage_modifiers)
                    continue
                if step.kind == "damage":
                    if ability_task_damage_authoritative:
                        runtime_records.append(
                            SettlementRecord(
                                record_type="action_damage_plan_delegated",
                                source="combat_executor",
                                process_only=True,
                                payload={
                                    "reason": "source_bound_ability_task_graph_authoritative",
                                    "action_id": command.action_id,
                                    "action_level": command.action_level,
                                    "binding_id": (
                                        action_binding.binding_id
                                        if action_binding is not None
                                        else ""
                                    ),
                                    "damage_emission_count": len(
                                        action_execution_plan.damage_emissions
                                    ),
                                },
                                trace=action_definition_trace,
                            ).to_json()
                        )
                        ability_result = self.ability_tasks.execute_callback(
                            current_state,
                            phases=ability_phases,
                            callback_kind="OnHit",
                            command=command,
                            action_definition=action_definition,
                            target_resolution=target_result.resolution,
                            action_damage_modifiers=tuple(action_damage_modifiers),
                            admitted_action_target_fact=action_target_fact,
                            action_execution_token=action_execution_token,
                        )
                        current_state = ability_result.after_state
                        ability_task_results.append(ability_result)
                        ordered_mutations.extend(ability_result.mutations)
                        runtime_records.extend(ability_result.records)
                        dispatch_ability_events(ability_result)
                        continue
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
                            bounce_result = (
                                self.targets.resolve_bounce_hit_target(
                                    current_state,
                                    actor_id=command.actor_id,
                                    primary_target_id=action_execution_plan.primary_action_target_id
                                    or (
                                        target_result.resolution.selected[0]
                                        if target_result.resolution.selected
                                        else ""
                                    ),
                                    bounce_policy=bounce_policy,
                                    hit_index=damage_plan.hit_index,
                                    previous_hit_targets=tuple(action_hit_targets),
                                    action_id=command.action_id,
                                    action_level=command.action_level,
                                    source_task_id=damage_plan.source_task_id,
                                    hit_profile_id=damage_plan.hit_profile_id,
                                    event_payload=command.metadata,
                                )
                                if bounce_policy is not None
                                else None
                            )
                            if bounce_result is None:
                                execution_node_results.append(
                                    ExecutionNodeResult(
                                        node_kind="target_selection",
                                        node_id=damage_plan.damage_emission_id
                                        or damage_plan.source_task_id,
                                        status="blocked",
                                        reason_code="bounce_policy_missing_at_execution",
                                    )
                                )
                                continue
                            if bounce_result.sequence_exhausted:
                                execution_node_results.append(
                                    ExecutionNodeResult(
                                        node_kind="target_selection",
                                        node_id=damage_plan.damage_emission_id
                                        or damage_plan.source_task_id,
                                        status="complete",
                                    )
                                )
                                runtime_records.append(
                                    SettlementRecord(
                                        record_type="bounce_sequence_exhausted",
                                        source="target_system",
                                        process_only=True,
                                        payload=bounce_result.metadata,
                                        trace=damage_plan.hit_source_trace,
                                    ).to_json()
                                )
                                break
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
                        hit_sequence_key = (
                            damage_plan.source_task_id
                            or damage_plan.damage_emission_id,
                            damage_packet.target_id,
                        )
                        if hit_sequence_key not in hit_sequence_context:
                            sequence_modifiers[hit_sequence_key] = dispatch_listener_window(
                                _damage_listener_window_event(
                                    current_state,
                                    command,
                                    action_definition,
                                    event_type="damage.hit_sequence.before",
                                    target_id=(
                                        damage_packet.target_id
                                    ),
                                    selected_target_ids=target_result.resolution.selected,
                                    primary_target_id=action_execution_plan.primary_action_target_id,
                                    source_trace=damage_packet.source_trace,
                                    damage_custom_name=str(
                                        damage_packet.metadata.get(
                                            "damage_custom_name"
                                        )
                                        or ""
                                    ),
                                    damage_tags=damage_plan.damage_tags,
                                    sequence_id=hit_sequence_key[0],
                                )
                            )
                            hit_sequence_order.append(hit_sequence_key)
                            hit_sequence_context[hit_sequence_key] = {
                                "target_id": damage_packet.target_id,
                                "source_trace": damage_packet.source_trace,
                                "damage_custom_name": str(
                                    damage_packet.metadata.get(
                                        "damage_custom_name"
                                    )
                                    or ""
                                ),
                                "damage_tags": list(
                                    damage_plan.damage_tags
                                ),
                            }
                        if damage_packet.target_id not in target_hit_sequences_started:
                            target_modifiers[damage_packet.target_id] = ()
                            for event_type in (
                                "damage.target_attack.before",
                                "damage.target_hit_sequence.before",
                            ):
                                target_modifiers[damage_packet.target_id] += dispatch_listener_window(
                                    _damage_listener_window_event(
                                        current_state,
                                        command,
                                        action_definition,
                                        event_type=event_type,
                                        target_id=damage_packet.target_id,
                                        selected_target_ids=target_result.resolution.selected,
                                        primary_target_id=action_execution_plan.primary_action_target_id,
                                        source_trace=damage_packet.source_trace,
                                    )
                                )
                            target_hit_sequences_started.add(damage_packet.target_id)
                        before_hit_event = GameEvent(
                            "damage.before_hit",
                            source_id=command.actor_id,
                            target_id=damage_packet.target_id,
                            event_id=(
                                f"event:{current_state.event_index}:damage_before_hit:"
                                f"{command.actor_id}:{damage_packet.target_id}:{damage_plan.hit_index}"
                            ),
                            window="damage.before_hit",
                            process_only=True,
                            payload={
                                **damage_packet.metadata,
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
                        damage_packet = replace(damage_packet, modifier_contributions=(
                            *action_damage_modifiers,
                            *sequence_modifiers.get(hit_sequence_key, ()),
                            *target_modifiers.get(damage_packet.target_id, ()),
                            *dispatch_result.damage_modifiers,
                        ))
                        damage_result = self.damage.apply_packet(
                            current_state,
                            damage_packet,
                            window_ledger=damage_window_ledger,
                        )
                        damage_results.append(damage_result)
                        hit_is_critical = any(
                            emitted_event.event_type == "damage.hit"
                            and emitted_event.payload.get("is_critical") is True
                            for emitted_event in damage_result.events
                        )
                        hit_final_damage = sum(
                            float(amount)
                            for emitted_event in damage_result.events
                            if emitted_event.event_type == "damage.hit"
                            and isinstance(
                                (amount := emitted_event.payload.get("amount")),
                                (int, float),
                            )
                            and not isinstance(amount, bool)
                        )
                        hit_sequence_final_damage[hit_sequence_key] = (
                            hit_sequence_final_damage.get(
                                hit_sequence_key,
                                0.0,
                            )
                            + hit_final_damage
                        )
                        target_hit_sequence_final_damage[damage_packet.target_id] = (
                            target_hit_sequence_final_damage.get(
                                damage_packet.target_id,
                                0.0,
                            )
                            + hit_final_damage
                        )
                        hit_sequence_is_critical[hit_sequence_key] = (
                            hit_sequence_is_critical.get(
                                hit_sequence_key,
                                False,
                            )
                            or hit_is_critical
                        )
                        target_hit_sequence_is_critical[damage_packet.target_id] = (
                            target_hit_sequence_is_critical.get(
                                damage_packet.target_id,
                                False,
                            )
                            or hit_is_critical
                        )
                        damage_mutations = (*damage_mutations, *damage_result.mutations)
                        current_state = self.reducer.apply_all(current_state, damage_result.mutations)
                        ordered_mutations.extend(damage_result.mutations)
                        runtime_records.extend(damage_result.records)
                        for emitted_event in damage_result.events:
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
                            stance_before_event = before_toughness_calculation_event(
                                actor_id=command.actor_id,
                                target_id=toughness_plan.target_id,
                                event_index=current_state.event_index,
                                packet=toughness_packet.to_json(),
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
                            dispatch_result = self.event_dispatcher.dispatch_event(
                                current_state,
                                event=stance_before_event,
                            )
                            current_state = dispatch_result.after_state
                            listener_dispatch_results.append(dispatch_result)
                            ordered_mutations.extend(dispatch_result.mutations)
                            runtime_records.extend(dispatch_result.records)
                            toughness_result = self.toughness.apply_packet(current_state, toughness_packet)
                            toughness_results.append(toughness_result)
                            toughness_mutations = (*toughness_mutations, *toughness_result.mutations)
                            current_state = self.reducer.apply_all(current_state, toughness_result.mutations)
                            ordered_mutations.extend(toughness_result.mutations)
                            runtime_records.extend(toughness_result.records)
                            for emitted_event in toughness_result.events:
                                dispatch_result = self.event_dispatcher.dispatch_event(current_state, event=emitted_event)
                                current_state = dispatch_result.after_state
                                listener_dispatch_results.append(dispatch_result)
                                ordered_mutations.extend(dispatch_result.mutations)
                                runtime_records.extend(dispatch_result.records)
                            break_result = self.breaks.enter_if_depleted(current_state, toughness_result)
                            if break_result:
                                current_state = break_result.after_state
                                break_results.append(break_result)
                                break_mutations = (*break_mutations, *break_result.mutations)
                                ordered_mutations.extend(break_result.mutations)
                                runtime_records.extend(break_result.records)
                                for emitted_event in break_result.events:
                                    if str(emitted_event.to_json()["event_id"]) in break_result.dispatched_event_ids:
                                        continue
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
                        stance_before_event = before_toughness_calculation_event(
                            actor_id=command.actor_id,
                            target_id=toughness_plan.target_id,
                            event_index=current_state.event_index,
                            packet=toughness_packet.to_json(),
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
                        dispatch_result = self.event_dispatcher.dispatch_event(
                            current_state,
                            event=stance_before_event,
                        )
                        current_state = dispatch_result.after_state
                        listener_dispatch_results.append(dispatch_result)
                        ordered_mutations.extend(dispatch_result.mutations)
                        runtime_records.extend(dispatch_result.records)
                        toughness_result = self.toughness.apply_packet(current_state, toughness_packet)
                        toughness_results.append(toughness_result)
                        toughness_mutations = (*toughness_mutations, *toughness_result.mutations)
                        current_state = self.reducer.apply_all(current_state, toughness_result.mutations)
                        ordered_mutations.extend(toughness_result.mutations)
                        runtime_records.extend(toughness_result.records)
                        for emitted_event in toughness_result.events:
                            dispatch_result = self.event_dispatcher.dispatch_event(current_state, event=emitted_event)
                            current_state = dispatch_result.after_state
                            listener_dispatch_results.append(dispatch_result)
                            ordered_mutations.extend(dispatch_result.mutations)
                            runtime_records.extend(dispatch_result.records)
                        break_result = self.breaks.enter_if_depleted(current_state, toughness_result)
                        if break_result:
                            current_state = break_result.after_state
                            break_results.append(break_result)
                            break_mutations = (*break_mutations, *break_result.mutations)
                            ordered_mutations.extend(break_result.mutations)
                            runtime_records.extend(break_result.records)
                            for emitted_event in break_result.events:
                                if str(emitted_event.to_json()["event_id"]) in break_result.dispatched_event_ids:
                                    continue
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
                        action_damage_modifiers=tuple(action_damage_modifiers),
                        admitted_action_target_fact=action_target_fact,
                        action_execution_token=action_execution_token,
                    )
                    current_state = ability_result.after_state
                    ability_task_results.append(ability_result)
                    ordered_mutations.extend(ability_result.mutations)
                    runtime_records.extend(ability_result.records)
                    for emitted_event in ability_result.events:
                        if (ability_result.dispatched_event_ids is not None
                                and str(emitted_event.to_json()["event_id"]) in ability_result.dispatched_event_ids):
                            continue
                        if emitted_event.event_type not in {
                            "status.lifecycle",
                            "damage.hit",
                            "toughness.hit",
                            "break.triggered",
                            "unit.defeated",
                            "custom.event",
                            "summon.spawned",
                            "summon.removed",
                            *MUTATION_BACKED_EVENT_TYPES,
                        }:
                            continue
                        dispatch_result = self.event_dispatcher.dispatch_event(current_state, event=emitted_event)
                        current_state = dispatch_result.after_state
                        listener_dispatch_results.append(dispatch_result)
                        ordered_mutations.extend(dispatch_result.mutations)
                        runtime_records.extend(dispatch_result.records)
            for hit_target_id in dict.fromkeys(action_hit_targets):
                for event_type in (
                    "damage.target_hit_sequence.after",
                    "damage.target_attack.after",
                ):
                    dispatch_listener_window(
                        _damage_listener_window_event(
                            current_state,
                            command,
                            action_definition,
                            event_type=event_type,
                            target_id=hit_target_id,
                            selected_target_ids=target_result.resolution.selected,
                            primary_target_id=action_execution_plan.primary_action_target_id,
                            source_trace=action_source_metadata.get("source_trace", {}),
                            is_critical=target_hit_sequence_is_critical.get(
                                hit_target_id,
                                False,
                            ),
                            final_damage=target_hit_sequence_final_damage.get(
                                hit_target_id,
                                0.0,
                            ),
                        )
                    )
            for hit_sequence_key in hit_sequence_order:
                sequence_context = hit_sequence_context[
                    hit_sequence_key
                ]
                sequence_target_id = str(
                    sequence_context["target_id"]
                )
                sequence_tags = sequence_context.get("damage_tags")
                dispatch_listener_window(
                    _damage_listener_window_event(
                        current_state,
                        command,
                        action_definition,
                        event_type="damage.hit_sequence.after",
                        target_id=sequence_target_id,
                        selected_target_ids=target_result.resolution.selected,
                        primary_target_id=action_execution_plan.primary_action_target_id,
                        source_trace=(
                            sequence_context["source_trace"]
                            if isinstance(
                                sequence_context.get("source_trace"),
                                dict,
                            )
                            else {}
                        ),
                        is_critical=hit_sequence_is_critical.get(
                            hit_sequence_key,
                            False,
                        ),
                        final_damage=hit_sequence_final_damage.get(
                            hit_sequence_key,
                            0.0,
                        ),
                        damage_custom_name=str(
                            sequence_context.get(
                                "damage_custom_name"
                            )
                            or ""
                        ),
                        damage_tags=tuple(
                            tag
                            for tag in (
                                sequence_tags
                                if isinstance(
                                    sequence_tags,
                                    (list, tuple),
                                )
                                else ()
                            )
                            if isinstance(tag, str) and tag
                        ),
                        sequence_id=hit_sequence_key[0],
                    )
                )
            for notice_index, hit_target_id in enumerate(
                dict.fromkeys(action_hit_targets)
            ):
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
                        "is_critical": target_hit_sequence_is_critical.get(
                            hit_target_id,
                            False,
                        ),
                        "source_trace": action_source_metadata.get("source_trace", {}),
                    },
                )
                if action_target_fact is not None:
                    # The post-action notice is produced by this owning
                    # execution. It carries the accepted action's target fact
                    # under its own invocation identity; listeners still have
                    # to pass the contract check before consuming it.
                    after_attack_event = _derived_post_action_listener_event(
                        action_target_fact=action_target_fact,
                        execution_token=action_execution_token,
                        command=command,
                        canonical_action_event_id=action_event_ir.action_event_id,
                        impact_fingerprint=target_result.impact_fingerprint,
                        event=after_attack_event,
                        step_id=(
                            f"after_attack_notice:{notice_index}:{hit_target_id}"
                        ),
                        step_index=notice_index,
                    )
                dispatch_result = self.event_dispatcher.dispatch_event(current_state, event=after_attack_event)
                current_state = dispatch_result.after_state
                listener_dispatch_results.append(dispatch_result)
                ordered_mutations.extend(dispatch_result.mutations)
                runtime_records.extend(dispatch_result.records)
            if action_hit_targets:
                attack_end_event = GameEvent(
                    "action.attack_end",
                    source_id=command.actor_id,
                    target_id=command.actor_id,
                    event_id=(
                        f"event:{current_state.event_index}:"
                        f"action_attack_end:{command.actor_id}:"
                        f"{command.action_id}"
                    ),
                    window="OnAfterAttackEnd",
                    process_only=True,
                    payload={
                        "action_id": command.action_id,
                        "action_level": command.action_level,
                        "actor_id": command.actor_id,
                        "attacker_id": command.actor_id,
                        "param_entity_id": command.actor_id,
                        "primary_target_id": (
                            action_execution_plan.primary_action_target_id
                        ),
                        "selected_target_ids": list(
                            target_result.resolution.selected
                        ),
                        "target_ids": list(
                            dict.fromkeys(action_hit_targets)
                        ),
                        "attack_type": action_definition.attack_type,
                        "skill_type": _condition_skill_type(
                            action_definition
                        ),
                        "skill_effect": action_definition.skill_effect,
                        "source_trace": action_source_metadata.get(
                            "source_trace",
                            {},
                        ),
                    },
                )
                dispatch_result = self.event_dispatcher.dispatch_event(
                    current_state,
                    event=attack_end_event,
                )
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

        owner_cleanup_node_results: list[ExecutionNodeResult] = []
        owner_cleanup_rng_events: list[RNGEvent] = []
        for owner_id, owner in sorted(current_state.units.items()):
            if self.lifecycle.status_of(owner) == "active":
                continue
            cleanup_plan = self.summons.plan_owner_cleanup(current_state, owner_id)
            if not cleanup_plan.ok:
                continue
            cleanup_result = self.summons.apply_remove(current_state, cleanup_plan)
            cleanup_reduction = self.reducer.apply_all_result(current_state, cleanup_result.mutations)
            if not cleanup_reduction.ok:
                owner_cleanup_node_results.append(
                    ExecutionNodeResult(
                        node_kind="summon_owner_cleanup",
                        node_id=f"summon_owner_cleanup:{owner_id}",
                        status="blocked",
                        reason_code=f"summon_owner_cleanup_reducer_conflict:{cleanup_reduction.conflicts[0].code}",
                    )
                )
                continue
            current_state = cleanup_reduction.after_state
            ordered_mutations.extend(cleanup_result.mutations)
            events = (*events, *cleanup_result.events)
            owner_cleanup_rng_events.extend(cleanup_result.rng_events)
            runtime_records.extend(cleanup_result.records)
            for cleanup_event in cleanup_result.events:
                dispatch_listener_window(cleanup_event)
            owner_cleanup_node_results.append(
                ExecutionNodeResult(
                    node_kind="summon_owner_cleanup",
                    node_id=f"summon_owner_cleanup:{owner_id}",
                    status="complete",
                )
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
        execution_node_results.extend(owner_cleanup_node_results)
        halo_dispatch_results: list[EventDispatchResult] = []
        halo_reconciliation = self.status.reconcile_halo_relations(
            current_state,
        )
        if halo_reconciliation.ok:
            halo_reduction = self.reducer.apply_all_result(
                current_state,
                halo_reconciliation.mutations,
            )
            if halo_reduction.ok:
                current_state = halo_reduction.after_state
                ordered_mutations.extend(halo_reconciliation.mutations)
                events = (*events, *halo_reconciliation.events)
                runtime_records.extend(halo_reconciliation.records)
                for halo_event in halo_reconciliation.events:
                    dispatch_result = self.event_dispatcher.dispatch_event(
                        current_state,
                        event=halo_event,
                        damage_window_ledger=damage_window_ledger,
                    )
                    current_state = dispatch_result.after_state
                    halo_dispatch_results.append(dispatch_result)
                    ordered_mutations.extend(dispatch_result.mutations)
                    runtime_records.extend(dispatch_result.records)
                    events = (*events, *dispatch_result.events)
                execution_node_results.extend(
                    node
                    for result in halo_dispatch_results
                    for node in result.node_results
                )
                execution_node_results.append(
                    ExecutionNodeResult(
                        node_kind="status_halo_reconciliation",
                        node_id=(
                            f"status_halo_reconciliation:{state.event_index}"
                        ),
                        status="complete",
                    )
                )
            else:
                execution_node_results.append(
                    ExecutionNodeResult(
                        node_kind="status_halo_reconciliation",
                        node_id=(
                            f"status_halo_reconciliation:{state.event_index}"
                        ),
                        status="blocked",
                        reason_code=(
                            "status_halo_reconciliation_reducer_conflict:"
                            f"{halo_reduction.conflicts[0].code}"
                        ),
                    )
                )
        else:
            runtime_records.extend(halo_reconciliation.records)
            execution_node_results.append(
                ExecutionNodeResult(
                    node_kind="status_halo_reconciliation",
                    node_id=f"status_halo_reconciliation:{state.event_index}",
                    status="blocked",
                    reason_code=(
                        ";".join(halo_reconciliation.unsupported)
                        or "status_halo_reconciliation_blocked"
                    ),
                )
            )
        damage_rng_events = (
            *tuple(target_rng_events),
            *ability_task_rng_events,
            *trigger_rng_events,
            *listener_dispatch_rng_events,
            *tuple(owner_cleanup_rng_events),
            *halo_reconciliation.rng_events,
            *tuple(
                event
                for result in halo_dispatch_results
                for event in result.rng_events
            ),
            *tuple(event for result in damage_results for event in result.rng_events),
            *tuple(event for result in break_results for event in result.rng_events),
        )
        rng_ledger_validation = validate_rng_choice_ledger(command.metadata, damage_rng_events)
        execution_node_results.append(
            ExecutionNodeResult(
                node_kind="rng_ledger",
                node_id=f"rng_ledger:{command.actor_id}:{command.action_id}:{state.event_index}",
                status="complete" if rng_ledger_validation.ok else "blocked",
                reason_code="" if rng_ledger_validation.ok else _rng_ledger_blocked_reason(rng_ledger_validation.to_json()),
            )
        )
        raw_transaction_events = (
            *events,
            *ability_task_events,
            *trigger_events,
            *listener_dispatch_events,
            *(event for result in damage_results for event in result.events),
            *(event for result in toughness_results for event in result.events),
            *(event for result in break_results for event in result.events),
        )
        event_normalizations = tuple(
            normalization
            for result in (
                *trigger_results,
                *listener_dispatch_results,
                *halo_dispatch_results,
                *break_results,
            )
            for normalization in result.event_normalizations
        )
        event_identity_conflict: _EventIdentityConflict | None = None
        try:
            transaction_events = _dedupe_events(
                *raw_transaction_events,
                event_normalizations=event_normalizations,
            )
        except _EventIdentityConflict as conflict:
            transaction_events = ()
            event_identity_conflict = conflict
            execution_node_results.append(
                ExecutionNodeResult(
                    node_kind="event_identity",
                    node_id=conflict.event_id,
                    status="blocked",
                    reason_code=conflict.reason_code,
                )
            )
        planned_mutations = tuple(ordered_mutations)
        atomic_commit = finalize_selected_execution_graph(
            state,
            current_state,
            planned_mutations,
            tuple(execution_node_results),
            reducer=self.reducer,
            preflight_blocked=(
                not action_enabled
                or event_identity_conflict is not None
            ),
            preflight_reason=(
                blocked_reason
                if not action_enabled
                else (
                    event_identity_conflict.reason_code
                    if event_identity_conflict is not None
                    else ""
                )
            ),
        )
        mutations = atomic_commit.committed_mutations
        after_state = atomic_commit.after_state

        records = action_source_records(
            self.rules, command, action_event, target_selection_context,
            target_result, action_execution_plan,
        )
        records.extend([
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
                source="action_target_selection_system",
                process_only=True,
                payload=target_result.resolution.to_json(),
                trace={"errors": list(target_result.errors)},
            ).to_json(),
        ])
        records.extend(runtime_records)
        if atomic_commit.outcome.successor_eligible:
            records.extend(
                SettlementRecord(
                    record_type="target_random_choice",
                    source="target_random_sampler",
                    process_only=True,
                    payload=event.to_json(),
                    trace=(
                        dict(event.metadata.get("source_trace") or {})
                        if isinstance(event.metadata.get("source_trace"), dict)
                        else {}
                    ),
                ).to_json()
                for event in target_rng_events
            )
        records.append(
            SettlementRecord(
                record_type="rng_choice_ledger",
                source="rng_system",
                process_only=True,
                payload=rng_ledger_validation.to_json(),
                trace={"command_source": command.source, "action_id": command.action_id},
            ).to_json()
        )
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
                    source="action_target_selection_system",
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

        records = list(records_for_atomic_result(tuple(records), atomic_commit))
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
                ()
                if event_identity_conflict is not None
                else events_for_atomic_result(
                    transaction_events,
                    atomic_commit,
                )
            ),
            mutations=mutations,
            trigger_windows=trigger_windows,
            settlement=settlement,
        )
        transition = BattleTransition(
            transaction=transaction,
            after=after_state.snapshot(),
            target_resolution=target_result.resolution,
            rng_events=rng_events_for_atomic_result(
                damage_rng_events,
                atomic_commit,
            ),
            outcome=atomic_commit.outcome,
            coverage={
                "executor": "v0_221_action_ability_binding",
                "action_contract": action_contract.to_json(),
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
                "target_query_fingerprint": target_selection_context.accepted.query_fingerprint,
                "target_selection_fingerprint": target_selection_context.accepted.selection_fingerprint,
                "target_selection_context_fingerprint": target_selection_context.context_fingerprint,
                "target_impact_fingerprint": target_result.impact_fingerprint,
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
                "atomic_commit": atomic_commit.evidence,
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


def _dedupe_events(
    *events: GameEvent,
    event_normalizations: tuple[EventNormalization, ...] = (),
) -> tuple[GameEvent, ...]:
    normalized_events = list(events)
    for normalization in event_normalizations:
        normalized = _validated_dispatch_normalization(
            normalization
        )
        normalized_events = [
            normalized if event == normalization.before else event
            for event in normalized_events
        ]

    deduped: list[GameEvent] = []
    index_by_key: dict[str, int] = {}
    for event in normalized_events:
        key = _resolved_event_id(event)
        if key in index_by_key:
            index = index_by_key[key]
            deduped[index] = _strict_duplicate_event(
                deduped[index],
                event,
                event_id=key,
            )
            continue
        index_by_key[key] = len(deduped)
        deduped.append(event)
    return tuple(deduped)


def _resolved_event_id(event: GameEvent) -> str:
    return str(event.to_json().get("event_id") or "")


def _strict_duplicate_event(
    existing: GameEvent,
    candidate: GameEvent,
    *,
    event_id: str,
) -> GameEvent:
    fields = (
        ("event_type", existing.event_type, candidate.event_type),
        ("source_id", existing.source_id, candidate.source_id),
        ("target_id", existing.target_id, candidate.target_id),
        ("window", existing.window, candidate.window),
        ("process_only", existing.process_only, candidate.process_only),
        ("payload", existing.payload, candidate.payload),
    )
    for field_name, existing_value, candidate_value in fields:
        if existing_value != candidate_value:
            raise _EventIdentityConflict(
                event_id,
                field_name,
            )
    if candidate.event_id and not existing.event_id:
        return candidate
    return existing


def _validated_dispatch_normalization(
    normalization: EventNormalization,
) -> GameEvent:
    before = normalization.before
    after = normalization.after
    event_id = _resolved_event_id(before)
    if (
        event_id != _resolved_event_id(after)
    ):
        raise _EventIdentityConflict(
            event_id or _resolved_event_id(after),
            "dispatcher_normalization",
        )
    fields = (
        (before.event_type, after.event_type),
        (before.source_id, after.source_id),
        (before.target_id, after.target_id),
        (before.window, after.window),
        (before.process_only, after.process_only),
    )
    if any(existing != candidate for existing, candidate in fields):
        raise _EventIdentityConflict(
            event_id,
            "dispatcher_normalization",
        )
    if normalization.kind == "typed_param_entity":
        expected_param_entity_id = before.target_id
        payload_ok = bool(
            isinstance(expected_param_entity_id, str)
            and expected_param_entity_id
            and "param_entity_id" not in before.payload
            and after.payload
            == {
                **before.payload,
                "param_entity_id": expected_param_entity_id,
            }
        )
    elif normalization.kind == "mutation_event_depth":
        depth = after.payload.get("mutation_event_depth")
        payload_ok = bool(
            "mutation_event_depth" not in before.payload
            and type(depth) is int
            and 1 <= depth <= MAX_CALLBACK_EMITTED_EVENT_DEPTH
            and after.payload
            == {
                **before.payload,
                "mutation_event_depth": depth,
            }
        )
    else:
        payload_ok = False
    if not payload_ok:
        raise _EventIdentityConflict(
            event_id,
            "dispatcher_normalization",
        )
    return after


def _eventful_transition_events(
    state: BattleState,
    mutations: tuple[Mutation, ...],
    explicit_events: tuple[GameEvent, ...],
    *,
    producer_id: str,
    actor_id: str | None = None,
    event_normalizations: tuple[EventNormalization, ...] = (),
) -> tuple[GameEvent, ...]:
    """Add mutation-backed events without duplicating an explicit birth event."""

    explicit_creation_targets = {
        str(event.target_id)
        for event in explicit_events
        if event.target_id
        and (
            event.event_type in {"unit.created", "summon.spawned"}
            or (
                isinstance(event.payload.get("callback_events"), (list, tuple))
                and "OnListenCharacterCreate"
                in event.payload.get("callback_events", ())
            )
        )
    }
    source_ids_by_target = {
        str(event.target_id): str(event.source_id or producer_id)
        for event in explicit_events
        if event.target_id
    }
    source_ids_by_mutation = {
        str(event.payload["mutation_id"]): str(event.source_id or producer_id)
        for event in explicit_events
        if event.payload.get("mutation_backed_event") is True
        and isinstance(event.payload.get("mutation_id"), str)
        and event.payload["mutation_id"]
    }
    supplements: list[GameEvent] = []
    for mutation in mutations:
        target_id = (
            str(mutation.path[1])
            if len(mutation.path) >= 2 and mutation.path[0] == "units"
            else ""
        )
        event_source_id = source_ids_by_mutation.get(
            mutation.stable_id(), source_ids_by_target.get(target_id, producer_id)
        )
        for event in events_for_mutation(
            mutation,
            actor_id=actor_id if actor_id is not None else event_source_id,
            source_id=event_source_id,
            event_index=state.event_index,
        ):
            if (
                event.event_type == "unit.created"
                and str(event.target_id or "") in explicit_creation_targets
            ):
                continue
            supplements.append(event)
    return _dedupe_events(*explicit_events, *supplements, event_normalizations=event_normalizations)


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
    runtime_validation = validate_summon_runtime(runtime, units=state.units)
    if not runtime_validation.ok:
        return runtime_validation.reason or "summon_runtime_state_missing"
    assert isinstance(runtime, dict)
    entities = runtime.get("entities")
    if not isinstance(entities, dict):
        return "summon_runtime_entities_missing"
    runtime_entity = entities.get(actor.unit_id)
    if not isinstance(runtime_entity, dict):
        return "summon_runtime_entity_missing"
    if runtime_entity.get("status", "active") != "active":
        return "summon_runtime_entity_not_active"
    source_intent_id = actor.flags.get("summon_intent_id")
    if source_intent_id is not None and runtime_entity.get("source_intent_id") != source_intent_id:
        return "summon_runtime_source_binding_mismatch"
    admission = actor.flags.get("summon_action_admission")
    if not isinstance(admission, dict) or admission.get("coverage_status") != "executable":
        return "summon_action_source_not_admitted"
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
        if actor.flags.get("combatant_profile_coverage_status") == "executable":
            return ""
        return "summon_damage_stat_source_not_admitted"
    admission = actor.flags.get("summon_damage_stat_admission")
    if not isinstance(admission, dict):
        admission = actor.flags.get("servant_damage_stat_admission")
    if not isinstance(admission, dict) or admission.get("coverage_status") != "executable":
        return "summon_damage_stat_binding_not_admitted"
    return ""


def _uses_action_damage_plan_fallback(binding_reason: str, event_reason: str, action_execution_plan) -> bool:
    if not (action_execution_plan.damage_plan or action_execution_plan.toughness_plan):
        return False
    return "missing_ability_phase_in_ability_file" in {binding_reason, event_reason}


def _legacy_ability_task_damage_reachable_ids(
    phase_tasks: tuple[AbilityTaskIR, ...],
) -> set[str]:
    tasks_by_id = {task.task_id: task for task in phase_tasks}
    reachable: set[str] = set()
    pending = [task.task_id for task in phase_tasks if not task.parent_task_id]
    while pending:
        task_id = pending.pop()
        if task_id in reachable:
            continue
        task = tasks_by_id.get(task_id)
        if task is None:
            continue
        reachable.add(task_id)
        pending.extend(
            child_id
            for child_id in (
                *task.child_task_ids,
                *task.success_task_ids,
                *task.failed_task_ids,
            )
            if child_id in tasks_by_id
        )
    return reachable


def _ability_task_damage_graph_authoritative(rules: RuleBook, phases, action_execution_plan) -> bool:
    if not phases or not action_execution_plan.damage_emissions:
        return False
    reachable_task_ids: set[str] = set()
    for phase in phases:
        phase_tasks = tuple(rules.ability_tasks_for_phase(phase.phase_id))
        if phase.invocation_role == "external_legacy":
            reachable_task_ids.update(
                _legacy_ability_task_damage_reachable_ids(phase_tasks)
            )
            continue
        if phase.invocation_role not in {
            "action_root",
            "nested_only",
            "standalone_root",
            "unbound_definition",
        }:
            return False
        callback_kinds = tuple(
            dict.fromkeys(task.callback_kind for task in phase_tasks)
        )
        if not callback_kinds:
            return False
        for callback_kind in callback_kinds:
            selected_ids = {
                task.task_id
                for task in phase_tasks
                if task.callback_kind == callback_kind
            }
            graph_result = rules.query_formal_task_graph(
                "ability_phase_callback",
                phase.phase_id,
                callback_kind,
                selected_ids,
            )
            graph = graph_result.value
            if (
                graph_result.status != "resolved"
                or type(graph) is not TaskGraphIR
            ):
                return False
            reachable_task_ids.update(selected_ids)
    return all(
        emission.source_task_id in reachable_task_ids
        and any(
            candidate.damage_emission_id == emission.damage_emission_id
            for candidate in rules.damage_emissions_for_task(emission.source_task_id)
        )
        for emission in action_execution_plan.damage_emissions
    )


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
    state: BattleState | None = None,
    metadata: dict[str, JSONValue],
    queue_resource_policy: dict[str, JSONValue],
) -> tuple[ResourcePlan, tuple[str, ...]]:
    resolutions: dict[str, dict[str, JSONValue]] = {}
    blocked_reasons: list[str] = []
    values: dict[str, float] = {}
    fields = ("bp_need", "bp_add", "sp_base")
    if action_definition.attack_type == "Ultra":
        fields += ("sp_need",)
    for field_name in fields:
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
    if action_definition.attack_type == "Ultra" and values.get("sp_need", 0.0) <= 0.0:
        blocked_reasons.append("ultimate_energy_cost_invalid")
    overrides = resolve_skill_property_overrides(
        state, command.actor_id, _condition_skill_type(action_definition)
    ) if state is not None else None
    override_values = skill_property_override_plan(
        action_definition,
        overrides.values if overrides is not None and overrides.ok else {},
    )
    override_blocked_reason = (
        "resource_skill_property_override_blocked:" + overrides.blocked_reason
        if overrides is not None and not overrides.ok else ""
    )
    bp_need = override_values.get("bp_need", values.get("bp_need", 0.0))
    skill_point_delta = action_skill_point_delta(bp_need, values.get("bp_add", 0.0))
    energy_gain = action_energy_gain(
        resolver.rules,
        action_definition,
        override_values,
        base_value=values.get("sp_base", 0.0),
    )
    if queue_resource_policy.get("ignore_skill_point_delta") is True:
        skill_point_delta = 0
    if queue_resource_policy.get("ignore_energy_gain") is True:
        energy_gain = 0.0
    return (
        ResourcePlan(
            skill_point_delta=skill_point_delta,
            energy_gain=energy_gain,
            energy_cost=values.get("sp_need") if action_definition.attack_type == "Ultra" else 0.0,
            source="combat_executor.resources",
            metadata={
                **metadata,
                "resource_value_resolutions": resolutions,
                "skill_property_override_plan": override_values,
                "skill_property_overrides": (
                    skill_property_override_evidence(overrides)
                    if overrides is not None else {}
                ),
                "value_resolver_admitted": not blocked_reasons,
            },
            blocked_reason=override_blocked_reason,
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
    policy = queue_entry.get("resource_policy")
    return policy if isinstance(policy, dict) else {}


def _callback_kind_for_step(phase: str) -> str:
    if phase == "before_skill_use":
        return "OnStart"
    if phase == "before_attack":
        return "OnAttack"
    if phase == "after_skill_use":
        return "OnEnd"
    return ""


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
        hit_energy_gain=damage_plan.hit_energy_gain,
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
            "damage_custom_name": damage_plan.damage_custom_name,
            "damage_tags": list(damage_plan.damage_tags),
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


def _legacy_callback_damage_roots(
    tasks: dict[str, StatusCallbackTaskIR],
) -> tuple[StatusCallbackTaskIR, ...]:
    return tuple(
        sorted(
            (task for task in tasks.values() if not task.parent_task_id),
            key=lambda item: (item.task_index, item.task_id),
        )
    )


def _callback_damage_topology(
    rules: RuleBook,
    callback: StatusCallbackIR,
    tasks: dict[str, StatusCallbackTaskIR],
) -> tuple[
    tuple[StatusCallbackTaskIR, ...],
    dict[str, TaskGraphNodeIR],
    str,
]:
    if callback.source_mode != "mainline_avatar_ability":
        if callback.source_mode not in {
            "mainline_equipment_ability",
            "mainline_monster_ability",
            "mainline_global_modifier",
        }:
            return (), {}, "status_callback_damage_topology_source_not_admitted"
        return _legacy_callback_damage_roots(tasks), {}, ""
    graph_result = rules.query_formal_task_graph(
        "status_callback",
        callback.callback_id,
        callback.event,
        tasks,
    )
    graph = graph_result.value
    if graph_result.status != "resolved" or type(graph) is not TaskGraphIR:
        return (), {}, (
            graph_result.blocked_reason
            or "formal_status_damage_task_graph_missing"
        )
    nodes_by_task = {node.formal_task_id: node for node in graph.nodes}
    roots = tuple(
        tasks[task_id] for task_id in graph.root_formal_task_ids
    )
    return roots, nodes_by_task, ""


def _callback_damage_selected_branch(
    task: StatusCallbackTaskIR,
    condition_value: bool,
    graph_nodes_by_task: dict[str, TaskGraphNodeIR],
) -> tuple[str, ...]:
    if not graph_nodes_by_task:
        return task.success_task_ids if condition_value else task.failed_task_ids
    node = graph_nodes_by_task.get(task.task_id)
    if node is None:
        return ()
    nodes_by_id = {
        candidate.graph_node_id: candidate
        for candidate in graph_nodes_by_task.values()
    }
    branch_kind = "success" if condition_value else "failed"
    return tuple(
        nodes_by_id[child_id].formal_task_id
        for branch in node.branches
        if branch.branch_kind == branch_kind
        for child_id in branch.child_node_ids
        if child_id in nodes_by_id
    )


def _collect_callback_damage_modifiers(
    state: BattleState,
    rules: RuleBook,
    evaluator: RuleEvaluator,
    targets: TargetSystem,
    *,
    callback: StatusCallbackIR,
    actor_id: str,
    owner_id: str,
    target_id: str,
    detail: dict[str, JSONValue],
    event_payload: dict[str, JSONValue],
) -> tuple[
    tuple[dict[str, JSONValue], ...],
    tuple[dict[str, JSONValue], ...],
    tuple[str, ...],
]:
    callback_id = callback.callback_id
    callback_event = callback.event
    tasks = {
        task.task_id: task
        for task in rules.status_callback_tasks_for_callback(callback_id)
    }
    roots, graph_nodes_by_task, topology_reason = _callback_damage_topology(
        rules,
        callback,
        tasks,
    )
    terms: list[dict[str, JSONValue]] = []
    records: list[dict[str, JSONValue]] = []
    blockers: list[str] = []
    if topology_reason:
        return (), (), (f"damage_modifier:{callback_id}:{topology_reason}",)
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
                reason = "missing_predicate_condition"
                records.append(_damage_modifier_record(root.task_id, "blocked", reason, {}, ()))
                blockers.append(f"damage_modifier:{root.task_id}:{reason}")
                continue
            result = evaluator.evaluate_condition_result(
                condition,
                targets.condition_evaluation_context(
                    state,
                    condition,
                    context=TargetEvaluationContext(
                        caster_id=actor_id,
                        effect_owner_id=owner_id,
                        parameter_entity_ids=(target_id,),
                        selected_target_ids=(target_id,),
                        current_target_id=target_id,
                        turn_owner_id=committed_turn_owner_id(state),
                    ),
                    condition_event_payload=dict(event_payload),
                    binding_sources=binding_sources,
                    status_detail=detail,
                ),
            )
            condition_result = result.to_json()
            if not result.ok or result.result is None:
                records.append(_damage_modifier_record(root.task_id, "blocked", result.reason, condition_result, ()))
                blockers.append(f"damage_modifier:{root.task_id}:{result.reason}")
                continue
            selected_ids = _callback_damage_selected_branch(
                root,
                bool(result.result),
                graph_nodes_by_task,
            )
            if not selected_ids:
                reason = "selected_condition_branch_empty"
                records.append(_damage_modifier_record(root.task_id, "skipped", reason, condition_result, ()))
                continue
        else:
            selected_ids = (root.task_id,)
        for child_id in selected_ids:
            child = tasks.get(child_id)
            if child is None:
                reason = f"missing_child_task:{child_id}"
                records.append(_damage_modifier_record(root.task_id, "blocked", reason, condition_result, ()))
                blockers.append(f"damage_modifier:{root.task_id}:{reason}")
                continue
            for modifier in rules.damage_modifiers_for_callback(callback_id):
                if modifier.source_task_id != child.task_id:
                    continue
                if modifier.coverage_status != "executable":
                    reason = modifier.blocked_reason or "damage_modifier_not_executable"
                    records.append(_damage_modifier_record(child.task_id, "blocked", reason, condition_result, (modifier.to_json(),)))
                    blockers.append(f"damage_modifier:{child.task_id}:{reason}")
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
                        reason = evaluation.blocked_reason or "damage_modifier_numeric_blocked"
                        records.append(_damage_modifier_record(child.task_id, "blocked", reason, condition_result, (modifier.to_json(),)))
                        blockers.append(f"damage_modifier:{child.task_id}:{reason}")
                        continue
                    applied = {
                        **term,
                        "value": evaluation.value,
                        "source_type": "damage_modifier_ir",
                        "source_id": modifier.damage_modifier_id,
                        "damage_modifier_id": modifier.damage_modifier_id,
                        "callback_id": callback_id,
                        "source_task_id": child.task_id,
                        "condition": f"{callback_event}_condition_passed",
                        "numeric_evaluation": evaluation.to_json(),
                        "source_trace": modifier.source.to_json(),
                    }
                    terms.append(applied)
                    applied_terms.append(applied)
                records.append(_damage_modifier_record(child.task_id, "applied" if applied_terms else "skipped", "", condition_result, tuple(applied_terms)))
    return tuple(terms), tuple(records), tuple(blockers)


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


def _toughness_plans_for_damage_plan(
    toughness_plans: tuple[ToughnessPlan, ...],
    damage_plan: DamagePlan,
) -> tuple[ToughnessPlan, ...]:
    return tuple(
        plan
        for plan in toughness_plans
        if plan.hit_profile_id == damage_plan.hit_profile_id and plan.target_id == damage_plan.target_id
    )


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


def _action_contract_blocked_transition(
    state: BattleState,
    command: ActionCommand,
    decision: ActionContractDecision,
) -> BattleTransition:
    reason = decision.blocked_reason or "action_contract_blocked"
    node = ExecutionNodeResult(
        node_kind="action_contract",
        node_id=f"{command.actor_id}:{command.action_id}:{command.action_level}",
        status="blocked",
        reason_code=reason,
    )
    atomic = finalize_selected_execution_graph(
        state,
        state,
        (),
        (node,),
        preflight_blocked=True,
        preflight_reason=reason,
    )
    trace = (
        decision.admission.source.to_json()
        if decision.admission is not None
        else {}
    )
    record = SettlementRecord(
        record_type="action_contract_blocked",
        source="action_contract",
        process_only=True,
        payload={
            "reason": reason,
            "decision": decision.to_json(),
            "state_unchanged": True,
        },
        trace=trace,
    ).to_json()
    return BattleTransition(
        transaction=ActionTransaction(
            command=command,
            before=state.snapshot(),
            mutations=(),
            settlement=ActionSettlement(
                action_id=command.action_id,
                actor_id=command.actor_id,
                target_ids=command.target_ids,
                records=(record,),
            ),
        ),
        after=state.snapshot(),
        target_resolution=TargetResolution(
            requested=command.target_ids,
            selected=(),
            rejected=command.target_ids,
            reason=reason,
            metadata={"action_contract": decision.to_json()},
        ),
        outcome=atomic.outcome,
        coverage={
            "action_contract": decision.to_json(),
            "action_enabled": False,
            "blocked_reason": reason,
            "atomic_commit": atomic.evidence,
        },
    )


def _action_target_context_blocked_transition(
    state: BattleState,
    command: ActionCommand,
    reason: str,
) -> BattleTransition:
    node = ExecutionNodeResult(
        node_kind="action_target_selection_context",
        node_id=f"{command.actor_id}:{command.action_id}:{command.action_level}",
        status="blocked",
        reason_code=reason,
    )
    atomic = finalize_selected_execution_graph(
        state,
        state,
        (),
        (node,),
        preflight_blocked=True,
        preflight_reason=reason,
    )
    record = SettlementRecord(
        record_type="action_target_selection_context_blocked",
        source="action_target_selection_system",
        process_only=True,
        payload={"reason": reason, "state_unchanged": True},
    ).to_json()
    return BattleTransition(
        transaction=ActionTransaction(
            command=command,
            before=state.snapshot(),
            mutations=(),
            settlement=ActionSettlement(
                action_id=command.action_id,
                actor_id=command.actor_id,
                target_ids=(),
                records=(record,),
            ),
        ),
        after=state.snapshot(),
        target_resolution=TargetResolution(
            requested=command.target_ids,
            selected=(),
            rejected=command.target_ids,
            reason=reason,
            source="action_target_selection_system",
        ),
        outcome=atomic.outcome,
        coverage={
            "action_enabled": False,
            "blocked_reason": reason,
            "target_selection_context_valid": False,
            "atomic_commit": atomic.evidence,
        },
    )


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


def _damage_metadata(command: ActionCommand) -> dict[str, JSONValue]:
    metadata: dict[str, JSONValue] = {}
    crit_mode = command.metadata.get("crit_mode")
    if isinstance(crit_mode, str):
        metadata["crit_mode"] = crit_mode
    rng_choices = rng_choices_from_payload(command.metadata)
    if rng_choices:
        metadata["rng_choices"] = rng_choices
    rng_mode = command.metadata.get("rng_mode")
    if isinstance(rng_mode, str):
        metadata["rng_mode"] = rng_mode
    metadata["is_current_skill_active"] = True
    metadata["is_insert_action"] = command.source == "queue"
    return metadata


def _action_window_dispatch_event(
    state: BattleState,
    command: ActionCommand,
    action_definition: ActionDefinitionIR,
    *,
    action_event_id: str,
    action_event_source: dict[str, JSONValue],
    step,
    target_resolution: TargetResolution,
    action_target_fact,
    action_execution_token: object,
    impact_fingerprint: str,
    step_index: int,
    primary_target_id: str | None,
) -> tuple[GameEvent, object]:
    event = GameEvent(
        event_type=f"action.window.{step.canonical_window}",
        source_id=command.actor_id,
        target_id=(
            target_resolution.selected[0]
            if target_resolution.selected
            else None
        ),
        event_id=(
            f"event:{state.event_index}:{step.canonical_window}:dispatch"
        ),
        window=step.canonical_window,
        process_only=True,
        payload={
            "tbgd_event": step.tbgd_event,
            "phase": step.phase,
            "action_id": command.action_id,
            "action_level": command.action_level,
            "action_event_id": action_event_id,
            "action_event_source": action_event_source,
            "actor_id": command.actor_id,
            "attacker_id": command.actor_id,
            "damage_attacker_id": command.actor_id,
            "selected_target_ids": list(target_resolution.selected),
            "target_ids": list(target_resolution.selected),
            "primary_action_target_id": primary_target_id,
            "primary_target_id": primary_target_id,
            "current_hit_target_id": primary_target_id,
            "target_id": primary_target_id,
            "attack_type": action_definition.attack_type,
            "AttackType": action_definition.attack_type,
            "skill_type": _condition_skill_type(action_definition),
            "SkillType": _condition_skill_type(action_definition),
            "skill_effect": action_definition.skill_effect,
            "is_current_skill_active": True,
            "is_insert_action": _metadata_bool(
                command.metadata,
                "is_insert_action",
                False,
            ),
            "source_trace": action_event_source,
        },
    )
    expected_scope = _issue_action_window_expected_scope(
        execution_token=action_execution_token,
        actor_id=command.actor_id,
        action_id=command.action_id,
        action_level=command.action_level,
        canonical_action_event_id=action_event_id,
        impact_fingerprint=impact_fingerprint,
        event_id=event.event_id,
        window=event.window,
        step_id=(
            f"{step_index}:{step.phase}:{step.canonical_window}:{step.tbgd_event}"
        ),
        step_index=step_index,
    )
    return replace(
        event,
        admitted_action_target_fact=action_target_fact.bind_invocation(expected_scope),
    ), expected_scope


def _dispatched_event_ids(
    records: tuple[dict[str, JSONValue], ...],
) -> frozenset[str]:
    event_ids: set[str] = set()
    for record in records:
        if record.get("record_type") != "event_dispatch":
            continue
        payload = record.get("payload")
        event = payload.get("event") if isinstance(payload, dict) else None
        event_id = event.get("event_id") if isinstance(event, dict) else None
        if isinstance(event_id, str) and event_id:
            event_ids.add(event_id)
    return frozenset(event_ids)


def _rng_ledger_blocked_reason(validation: dict[str, JSONValue]) -> str:
    for key, code in (
        ("duplicate_provided_keys", "rng_choice_ledger_duplicate_key"),
        ("duplicate_consumed_keys", "rng_decision_identity_collision"),
        ("invalid_identity_event_ids", "rng_decision_identity_incomplete"),
        ("missing_keys", "rng_choice_ledger_missing_choice"),
        ("extra_keys", "rng_choice_ledger_extra_choice"),
    ):
        values = validation.get(key)
        if isinstance(values, list) and values:
            return f"{code}:{','.join(str(item) for item in values)}"
    return "rng_choice_ledger_invalid"


def _target_groups_from_resolution(metadata: dict[str, JSONValue]) -> dict[str, tuple[str, ...]]:
    groups = metadata.get("target_groups")
    if not isinstance(groups, dict):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for key, value in groups.items():
        if isinstance(value, (list, tuple)):
            result[str(key)] = tuple(str(item) for item in value if isinstance(item, str))
    return result
