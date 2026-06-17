from __future__ import annotations

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
        timeline_result = self.timeline.open_action(
            state,
            command.actor_id,
            TimelinePlan(
                reset_actor_av=_metadata_bool(command.metadata, "reset_actor_av", False),
                source="combat_executor.timeline",
            ),
        )
        target_result = self.targets.resolve_explicit_targets(
            state,
            command.actor_id,
            command.target_ids,
            policy=_target_policy(action_definition),
        )
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
        events: tuple[GameEvent, ...] = (action_event, *timeline_result.events)
        timeline_mutations = timeline_result.mutations
        resource_mutations = resource_result.mutations
        pre_damage_mutations = (*timeline_mutations, *resource_mutations)
        current_state = self.reducer.apply_all(state, pre_damage_mutations)
        action_enabled = target_result.ok and resource_result.ok and bool(target_result.resolution.selected)
        skipped_reason = "" if action_enabled else _trigger_skip_reason(target_result.ok, resource_result.ok)
        trigger_results: list[TriggerWindowResult] = []
        for canonical_window, tbgd_event, needs_enabled in (
            ("before_skill_use", "OnBeforeSkillUse", True),
            ("before_attack", "OnBeforeAttack", True),
        ):
            trigger_result = self.triggers.execute_status_window(
                current_state,
                canonical_window=canonical_window,
                tbgd_event=tbgd_event,
                command=command,
                target_resolution=target_result.resolution,
                enabled=action_enabled if needs_enabled else True,
                skipped_reason=skipped_reason,
            )
            current_state = trigger_result.after_state
            trigger_results.append(trigger_result)

        damage_result = None
        damage_mutations: tuple[Mutation, ...] = ()
        if action_enabled:
            damage_packet = _damage_packet(command, action_definition, action_definition_trace)
            if damage_packet:
                damage_result = self.damage.apply_packet(current_state, damage_packet)
                damage_mutations = damage_result.mutations
                current_state = self.reducer.apply_all(current_state, damage_mutations)

        for canonical_window, tbgd_event in (
            ("after_attack", "OnAfterAttack"),
            ("after_skill_use", "OnAfterSkillUse"),
        ):
            trigger_result = self.triggers.execute_status_window(
                current_state,
                canonical_window=canonical_window,
                tbgd_event=tbgd_event,
                command=command,
                target_resolution=target_result.resolution,
                enabled=action_enabled,
                skipped_reason=skipped_reason,
            )
            current_state = trigger_result.after_state
            trigger_results.append(trigger_result)

        trigger_mutations = tuple(mutation for result in trigger_results for mutation in result.mutations)
        trigger_events = tuple(event for result in trigger_results for event in result.events)
        before_damage_trigger_records = tuple(record for result in trigger_results[:2] for record in result.records)
        after_damage_trigger_records = tuple(record for result in trigger_results[2:] for record in result.records)
        trigger_windows = tuple(window for result in trigger_results for window in result.trigger_windows)
        # Trigger mutations before and after damage are already ordered in current_state,
        # but the flat mutation list must preserve the real execution order for replay.
        mutations = _ordered_action_mutations(pre_damage_mutations, trigger_results, damage_mutations)
        after_state = current_state
        damage_rng_events = damage_result.rng_events if damage_result else ()

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
                record_type="target_resolution",
                source="target_system",
                process_only=True,
                payload=target_result.resolution.to_json(),
                trace={"errors": list(target_result.errors)},
            ).to_json(),
        ]
        records.extend(_mutation_record("timeline", mutation) for mutation in timeline_mutations)
        records.extend(_mutation_record("resource", mutation) for mutation in resource_mutations)
        records.extend(before_damage_trigger_records)
        if damage_result:
            records.extend(damage_result.records)
        records.extend(after_damage_trigger_records)
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
            target_ids=command.target_ids,
            records=tuple(records),
        )
        transaction = ActionTransaction(
            command=command,
            before=before,
            events=(*events, *trigger_events, *(damage_result.events if damage_result else ())),
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
                "executor": "v0_211_trigger_effect_spine",
                "definition_id": action_definition.definition_id,
                "target_ok": target_result.ok,
                "resource_ok": resource_result.ok,
                "timeline_mutation_count": len(timeline_mutations),
                "resource_mutation_count": len(resource_mutations),
                "trigger_window_count": len(trigger_windows),
                "trigger_mutation_count": len(trigger_mutations),
                "damage_mutation_count": len(damage_mutations),
                "damage_ok": bool(damage_result.ok) if damage_result else None,
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


def _ordered_action_mutations(
    pre_damage_mutations: tuple[Mutation, ...],
    trigger_results: list[TriggerWindowResult],
    damage_mutations: tuple[Mutation, ...],
) -> tuple[Mutation, ...]:
    before_damage = tuple(
        mutation
        for result in trigger_results[:2]
        for mutation in result.mutations
    )
    after_damage = tuple(
        mutation
        for result in trigger_results[2:]
        for mutation in result.mutations
    )
    return (*pre_damage_mutations, *before_damage, *damage_mutations, *after_damage)


def _trigger_skip_reason(target_ok: bool, resource_ok: bool) -> str:
    reasons: list[str] = []
    if not target_ok:
        reasons.append("target_resolution_failed")
    if not resource_ok:
        reasons.append("resource_plan_failed")
    return ",".join(reasons) or "action_not_executable"


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
        return TargetPolicy(policy_id="self_or_team", allow_enemy=False, allow_ally=True, allow_self=True)
    if action_definition.damage_kind == "hp_damage":
        return TargetPolicy(policy_id="enemy_damage", allow_enemy=True, allow_ally=False, allow_self=False)
    return TargetPolicy(policy_id="explicit_any", allow_enemy=True, allow_ally=True, allow_self=True)


def _damage_packet(
    command: ActionCommand,
    action_definition: ActionDefinitionIR,
    source_trace: dict[str, object],
) -> DamagePacket | None:
    if action_definition.damage_kind != "hp_damage":
        return None
    if action_definition.damage_formula_family not in {"direct", "true_damage", "hp_loss", "elation"}:
        return None
    return DamagePacket(
        attacker_id=command.actor_id,
        target_id=command.target_ids[0],
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
        },
        metadata=_damage_metadata(command),
    )


def _damage_metadata(command: ActionCommand) -> dict[str, JSONValue]:
    metadata: dict[str, JSONValue] = {}
    crit_mode = command.metadata.get("crit_mode")
    if isinstance(crit_mode, str):
        metadata["crit_mode"] = crit_mode
    return metadata
