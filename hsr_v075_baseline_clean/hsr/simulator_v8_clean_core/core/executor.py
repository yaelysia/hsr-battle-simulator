from __future__ import annotations

from .action_plan import DamagePlan, build_action_execution_plan
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
from ..systems.damage import DamagePacket, DamageSystem
from ..systems.effect import EffectRegistry
from ..systems.resource import ResourcePlan, ResourceSystem
from ..systems.status import StatusSystem
from ..systems.target import TargetPolicy, TargetSystem
from ..systems.timeline import TimelinePlan, TimelineSystem
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
        self.status = StatusSystem(rules)
        self.effects = EffectRegistry(self.status)
        self.triggers = TriggerSystem(rules, self.effects, reducer=self.reducer)

    def execute(self, command: ActionCommand, state: BattleState) -> tuple[BattleState, BattleTransition]:
        before = state.snapshot()
        action_definition = self.rules.require_action_definition(command.action_id, command.action_level)
        action_event_ir = self.rules.require_action_event(command.action_id, command.action_level)
        action_binding = self.rules.action_ability_binding(command.action_id, command.action_level)
        ability_phases = self.rules.ability_phases_for_action(command.action_id, command.action_level)
        hit_profiles = self.rules.hit_profiles_for_action(command.action_id, command.action_level)
        action_definition_trace = self.rules.action_definition_source_trace(command.action_id, command.action_level) or {}
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
            policy=_target_policy(action_definition),
        )
        action_execution_plan = build_action_execution_plan(
            action_definition,
            action_event_ir,
            hit_profiles,
            requested_target_ids=command.target_ids,
            resolved_target_groups=_target_groups_from_resolution(target_result.resolution.metadata),
            source_trace={
                **action_definition_trace,
                "action_event_id": action_event_ir.action_event_id,
                "binding_id": action_binding.binding_id if action_binding else "",
                "phase_ids": [phase.phase_id for phase in ability_phases],
                "event_source_status": action_event_ir.event_source_status,
                "hit_profile_ids": [profile.hit_profile_id for profile in hit_profiles],
            },
        )
        action_event_plan_payload = _action_event_plan_compat_payload(action_definition, action_event_ir)
        resource_result = self.resources.plan_action_resources(
            state,
            command.actor_id,
            ResourcePlan(
                skill_point_delta=_skill_point_delta(action_definition.bp_need, action_definition.bp_add),
                energy_gain=action_definition.sp_base,
                source="combat_executor.resources",
                metadata={
                    "definition_id": action_definition.definition_id,
                    "action_id": action_definition.action_id,
                    "action_level": action_definition.level,
                    "source_trace": action_definition_trace,
                },
            ),
        )
        plan_blocked_reason = action_execution_plan.target_plan.blocked_reason
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

        if action_enabled:
            for step in action_execution_plan.event_steps:
                if step.kind == "trigger_window":
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
            events=(*events, *trigger_events, *(event for result in damage_results for event in result.events)),
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
                "action_execution_plan": action_execution_plan.to_json(),
                "action_event_ir": action_event_ir.to_json(),
                "action_event_id": action_event_ir.action_event_id,
                "binding_id": action_binding.binding_id if action_binding else "",
                "phase_ids": [phase.phase_id for phase in ability_phases],
                "event_source_status": action_event_ir.event_source_status,
                "action_event_plan": action_event_plan_payload,
                "hit_profile_ids": [profile.hit_profile_id for profile in hit_profiles],
                "definition_id": action_definition.definition_id,
                "target_ok": target_result.ok,
                "resource_ok": resource_result.ok,
                "action_enabled": action_enabled,
                "blocked_reason": blocked_reason,
                "plan_blocked_reason": plan_blocked_reason,
                "primary_action_target_id": action_execution_plan.primary_action_target_id,
                "per_hit_target_context_not_implemented": action_execution_plan.per_hit_target_context_not_implemented,
                "timeline_mutation_count": len(timeline_mutations),
                "resource_mutation_count": len(resource_mutations),
                "trigger_window_count": len(trigger_windows),
                "trigger_mutation_count": len(trigger_mutations),
                "damage_mutation_count": len(damage_mutations),
                "damage_ok": all(result.ok for result in damage_results) if damage_results else None,
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


def _target_policy(action_definition: ActionDefinitionIR) -> TargetPolicy:
    if action_definition.target_mode == "self_or_team":
        return TargetPolicy(
            policy_id="self_or_team",
            allow_enemy=False,
            allow_ally=True,
            allow_self=True,
            target_mode=action_definition.target_mode,
            selection_mode="explicit_ally_or_self",
        )
    if action_definition.damage_kind == "hp_damage":
        return TargetPolicy(
            policy_id="enemy_damage",
            allow_enemy=True,
            allow_ally=False,
            allow_self=False,
            target_mode=action_definition.target_mode,
            selection_mode=action_definition.target_mode,
        )
    return TargetPolicy(
        policy_id="explicit_any",
        allow_enemy=True,
        allow_ally=True,
        allow_self=True,
        target_mode=action_definition.target_mode,
        selection_mode=action_definition.target_mode,
    )


def _damage_packet(
    command: ActionCommand,
    action_definition: ActionDefinitionIR,
    source_trace: dict[str, object],
    damage_plan: DamagePlan,
) -> DamagePacket | None:
    if action_definition.damage_kind != "hp_damage":
        return None
    if action_definition.damage_formula_family not in {"direct", "true_damage", "hp_loss", "elation"}:
        return None
    return DamagePacket(
        attacker_id=command.actor_id,
        target_id=damage_plan.target_id,
        attack_type=action_definition.attack_type,
        damage_formula_family=action_definition.damage_formula_family,
        damage_kind=action_definition.damage_kind,
        element_type=action_definition.element_type,
        action_definition=action_definition,
        source_trace={
            "definition_id": action_definition.definition_id,
            "action_id": action_definition.action_id,
            "action_level": action_definition.level,
            "source": source_trace,
            "hit_profile_id": damage_plan.hit_profile_id,
            "hit_source_trace": damage_plan.hit_source_trace,
        },
        hit_profile_id=damage_plan.hit_profile_id,
        scaling_ratio=damage_plan.scaling_ratio,
        hit_source_trace=damage_plan.hit_source_trace,
        metadata={
            **_damage_metadata(command),
            "hit_index": damage_plan.hit_index,
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
