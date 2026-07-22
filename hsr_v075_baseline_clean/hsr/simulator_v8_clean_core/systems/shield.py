from __future__ import annotations

from dataclasses import dataclass, field

from ..core.model import BattleState, GameEvent, JSONValue, Mutation
from ..core.settlement import SettlementRecord
from ..rules.engine_rule_registry import (
    ENGINE_RULE_REGISTRY_VERSION,
    EngineRuleRegistry,
    SHIELD_PRIORITY_RULE_ID,
    build_engine_rule_registry,
    select_damage_route_rule,
    select_shield_priority_rule,
)
from .mutation_events import events_for_mutation


NORMAL_SHIELD_FAMILIES = ("direct", "dot", "break", "super_break", "true_damage")
SHIELD_OPCODE_POLICIES = {
    "Shield": "replace_same_source",
    "InitShield": "replace_same_source",
    "StackShield": "stack_same_source",
    "ModifyShield": "modify_same_source",
}


@dataclass(frozen=True)
class ShieldApplicationResult:
    ok: bool
    mutation: Mutation | None = None
    events: tuple[GameEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    blocked_reason: str = ""


@dataclass(frozen=True)
class HPDamageRoute:
    ok: bool
    target_id: str
    incoming_damage: float
    absorbed_damage: float = 0.0
    hp_damage: float = 0.0
    hp_after: float = 0.0
    shield_mutation: Mutation | None = None
    events: tuple[GameEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    exhausted_instance_ids: tuple[str, ...] = ()
    route_policy: str = ""
    blocked_reason: str = ""
    evidence: dict[str, JSONValue] = field(default_factory=dict)


class ShieldSystem:
    """Owns source-distinguished shield instances and HP routing."""

    def __init__(self, engine_rules: EngineRuleRegistry | None = None) -> None:
        self.engine_rules = engine_rules or build_engine_rule_registry()

    def apply_effect(
        self,
        state: BattleState,
        *,
        target_id: str,
        shield_id: str,
        source_id: str,
        source_kind: str,
        opcode: str,
        amount: float,
        source_trace: dict[str, JSONValue],
        actor_id: str,
        event_source_id: str,
        priority: int = 0,
        priority_source: dict[str, JSONValue] | None = None,
        priority_rule_id: str = SHIELD_PRIORITY_RULE_ID,
        priority_rule_version: str = ENGINE_RULE_REGISTRY_VERSION,
        absorb_families: tuple[str, ...] = NORMAL_SHIELD_FAMILIES,
        owner_modifier_name: str = "",
        status_instance_id: str = "",
        mutation_source: str = "effect_system",
        mutation_metadata: dict[str, JSONValue] | None = None,
    ) -> ShieldApplicationResult:
        target = state.units.get(target_id)
        if target is None:
            return ShieldApplicationResult(False, blocked_reason="shield_target_missing")
        policy = SHIELD_OPCODE_POLICIES.get(opcode)
        if policy is None:
            return ShieldApplicationResult(False, blocked_reason=f"shield_opcode_policy_missing:{opcode}")
        if not shield_id or not source_id or not actor_id:
            return ShieldApplicationResult(False, blocked_reason="shield_source_identity_incomplete")
        if not absorb_families:
            return ShieldApplicationResult(False, blocked_reason="shield_absorb_family_policy_missing")
        priority_rule, priority_reason = select_shield_priority_rule(
            priority_rule_id,
            priority_rule_version,
            self.engine_rules,
        )
        if priority_rule is None:
            return ShieldApplicationResult(False, blocked_reason=priority_reason)
        resolved_priority_source = priority_source if isinstance(priority_source, dict) else {}

        before = [dict(item) for item in target.shield_instances]
        after = [dict(item) for item in target.shield_instances]
        existing_index = next(
            (
                index
                for index, item in enumerate(after)
                if item.get("shield_id") == shield_id
                and item.get("source_id") == source_id
                and item.get("source_actor_id") == actor_id
            ),
            None,
        )
        if policy == "modify_same_source" and existing_index is None:
            return ShieldApplicationResult(False, blocked_reason="shield_modify_source_instance_missing")
        if policy != "modify_same_source" and amount <= 0:
            return ShieldApplicationResult(False, blocked_reason="shield_creation_amount_not_positive")

        if existing_index is None:
            instance = _instance(
                shield_id=shield_id,
                source_id=source_id,
                source_actor_id=actor_id,
                source_kind=source_kind,
                remaining=amount,
                capacity=amount,
                priority=priority,
                stack_policy=policy,
                absorb_families=absorb_families,
                created_event_index=state.event_index,
                source_trace=source_trace,
                priority_source=resolved_priority_source,
                priority_rule={
                    "shield_priority_rule_id": priority_rule.shield_priority_rule_id,
                    "registry_version": priority_rule.registry_version,
                },
                owner_modifier_name=owner_modifier_name,
                status_instance_id=status_instance_id,
            )
            after.append(instance)
        else:
            current = after[existing_index]
            current_remaining = float(current["remaining"])
            if policy == "replace_same_source":
                next_remaining = amount
                next_capacity = amount
            else:
                next_remaining = current_remaining + amount
                next_capacity = max(float(current["capacity"]), next_remaining)
            if next_remaining <= 0:
                after.pop(existing_index)
            else:
                after[existing_index] = {
                    **current,
                    "remaining": next_remaining,
                    "capacity": next_capacity,
                    "stack_policy": policy,
                    "source_trace": source_trace,
                }
        after = _ordered(after)
        if after == before:
            return ShieldApplicationResult(False, blocked_reason="shield_effect_no_state_change")
        mutation = Mutation(
            op="set",
            path=("units", target_id, "shield_instances"),
            before=before,
            after=after,
            reason="apply source-distinguished shield effect",
            source=mutation_source,
            metadata={
                **(mutation_metadata or {}),
                "shield_id": shield_id,
                "source_id": source_id,
                "source_actor_id": actor_id,
                "source_kind": source_kind,
                "opcode": opcode,
                "stack_policy": policy,
                "amount": amount,
                "aggregate_before": _aggregate(before),
                "aggregate_after": _aggregate(after),
                "source_trace": source_trace,
                "priority_source": resolved_priority_source,
                "priority_rule": priority_rule.to_json(),
                "owner_modifier_name": owner_modifier_name,
                "status_instance_id": status_instance_id,
            },
        )
        record = SettlementRecord(
            record_type="shield",
            source="shield_system",
            mutation_id=mutation.stable_id(),
            process_only=False,
            payload={
                "target_id": target_id,
                "shield_id": shield_id,
                "opcode": opcode,
                "stack_policy": policy,
                "amount": amount,
                "aggregate_before": _aggregate(before),
                "aggregate_after": _aggregate(after),
                "instance_count_before": len(before),
                "instance_count_after": len(after),
                "numeric_evaluation": (mutation_metadata or {}).get("numeric_evaluation", {}),
            },
            trace=source_trace,
        ).to_json()
        return ShieldApplicationResult(
            True,
            mutation=mutation,
            events=events_for_mutation(
                mutation,
                actor_id=actor_id,
                source_id=event_source_id,
                event_index=state.event_index,
            ),
            records=(record,),
        )

    def remove_status_instance_shields(
        self,
        state: BattleState,
        *,
        target_id: str,
        owner_modifier_name: str,
        status_instance_id: str,
        actor_id: str,
        event_source_id: str,
        source_trace: dict[str, JSONValue],
        mutation_source: str = "effect_system",
        mutation_metadata: dict[str, JSONValue] | None = None,
    ) -> ShieldApplicationResult:
        target = state.units.get(target_id)
        if target is None:
            return ShieldApplicationResult(False, blocked_reason="shield_target_missing")
        if not owner_modifier_name or not status_instance_id or not actor_id:
            return ShieldApplicationResult(
                False,
                blocked_reason="shield_removal_source_identity_incomplete",
            )
        before = [dict(item) for item in target.shield_instances]
        matched = [
            item
            for item in before
            if item.get("owner_modifier_name") == owner_modifier_name
            and item.get("status_instance_id") == status_instance_id
        ]
        if not matched:
            return ShieldApplicationResult(
                False,
                blocked_reason="shield_removal_source_instance_missing",
            )
        after = _ordered([item for item in before if item not in matched])
        removed_instance_ids = tuple(
            sorted(str(item.get("instance_id") or "") for item in matched)
        )
        mutation = Mutation(
            op="set",
            path=("units", target_id, "shield_instances"),
            before=before,
            after=after,
            reason="remove shields owned by current status instance",
            source=mutation_source,
            metadata={
                **(mutation_metadata or {}),
                "owner_modifier_name": owner_modifier_name,
                "status_instance_id": status_instance_id,
                "removed_instance_ids": list(removed_instance_ids),
                "aggregate_before": _aggregate(before),
                "aggregate_after": _aggregate(after),
                "source_trace": source_trace,
            },
        )
        record = SettlementRecord(
            record_type="shield_remove",
            source="shield_system",
            mutation_id=mutation.stable_id(),
            process_only=False,
            payload={
                "target_id": target_id,
                "owner_modifier_name": owner_modifier_name,
                "status_instance_id": status_instance_id,
                "removed_instance_ids": list(removed_instance_ids),
                "aggregate_before": _aggregate(before),
                "aggregate_after": _aggregate(after),
            },
            trace=source_trace,
        ).to_json()
        return ShieldApplicationResult(
            True,
            mutation=mutation,
            events=events_for_mutation(
                mutation,
                actor_id=actor_id,
                source_id=event_source_id,
                event_index=state.event_index,
            ),
            records=(record,),
        )

    def route_damage(
        self,
        state: BattleState,
        *,
        target_id: str,
        incoming_damage: float,
        damage_family: str,
        damage_route_rule_id: str,
        damage_route_rule_version: str,
        actor_id: str,
        source_id: str,
        mutation_source: str = "damage_system",
        mutation_metadata: dict[str, JSONValue] | None = None,
    ) -> HPDamageRoute:
        target = state.units.get(target_id)
        if target is None:
            return HPDamageRoute(False, target_id, incoming_damage, blocked_reason="shield_route_target_missing")
        if incoming_damage < 0:
            return HPDamageRoute(False, target_id, incoming_damage, blocked_reason="shield_route_damage_negative")
        route_rule, route_reason = select_damage_route_rule(damage_family, self.engine_rules)
        if route_rule is None:
            return HPDamageRoute(False, target_id, incoming_damage, blocked_reason=route_reason)
        if route_rule.damage_route_rule_id != damage_route_rule_id:
            return HPDamageRoute(False, target_id, incoming_damage, blocked_reason="damage_route_engine_rule_id_mismatch")
        if route_rule.registry_version != damage_route_rule_version:
            return HPDamageRoute(False, target_id, incoming_damage, blocked_reason="damage_route_engine_rule_version_mismatch")
        route_policy = route_rule.route_policy
        route_source = route_rule.to_json()
        instances = [dict(item) for item in target.shield_instances]
        if route_policy == "bypass":
            return HPDamageRoute(
                True,
                target_id,
                incoming_damage,
                hp_damage=incoming_damage,
                hp_after=max(0.0, target.hp - incoming_damage),
                route_policy=route_policy,
                evidence={"route_source": route_source, "shield_instance_count": len(instances)},
            )
        legacy_aggregate = float(target.resources.get("shield", 0.0))
        if legacy_aggregate > 0 and not instances:
            return HPDamageRoute(
                False,
                target_id,
                incoming_damage,
                blocked_reason="aggregate_shield_without_source_instances",
            )
        before = [dict(item) for item in instances]
        remaining_damage = incoming_damage
        exhausted: list[str] = []
        consumed: list[dict[str, JSONValue]] = []
        after: list[dict[str, JSONValue]] = []
        for instance in instances:
            priority_rule_value = instance.get("priority_rule")
            if not isinstance(priority_rule_value, dict):
                return HPDamageRoute(
                    False,
                    target_id,
                    incoming_damage,
                    blocked_reason="shield_instance_priority_rule_missing",
                )
            admitted_priority, priority_reason = select_shield_priority_rule(
                str(priority_rule_value.get("shield_priority_rule_id") or ""),
                str(priority_rule_value.get("registry_version") or ""),
                self.engine_rules,
            )
            if admitted_priority is None:
                return HPDamageRoute(False, target_id, incoming_damage, blocked_reason=priority_reason)
        for instance in _ordered(instances):
            if damage_family not in instance["absorb_families"] or remaining_damage <= 0:
                after.append(instance)
                continue
            available = float(instance["remaining"])
            absorbed = min(available, remaining_damage)
            remaining_damage -= absorbed
            next_remaining = available - absorbed
            consumed.append(
                {
                    "shield_id": instance["shield_id"],
                    "instance_id": instance["instance_id"],
                    "before": available,
                    "absorbed": absorbed,
                    "after": next_remaining,
                    "priority": instance["priority"],
                    "priority_audit": instance["priority_audit"],
                }
            )
            if next_remaining > 0:
                after.append({**instance, "remaining": next_remaining})
            else:
                exhausted.append(str(instance["instance_id"]))
        after = _ordered(after)
        shield_mutation = None
        events: tuple[GameEvent, ...] = ()
        records: tuple[dict[str, JSONValue], ...] = ()
        if after != before:
            shield_mutation = Mutation(
                op="set",
                path=("units", target_id, "shield_instances"),
                before=before,
                after=after,
                reason="route damage through shield instances",
                source=mutation_source,
                metadata={
                    **(mutation_metadata or {}),
                    "damage_family": damage_family,
                    "incoming_damage": incoming_damage,
                    "absorbed_damage": incoming_damage - remaining_damage,
                    "hp_damage": remaining_damage,
                    "consumed_instances": consumed,
                    "exhausted_instance_ids": exhausted,
                    "route_policy": route_policy,
                    "route_source": route_source,
                },
            )
            events = events_for_mutation(
                shield_mutation,
                actor_id=actor_id,
                source_id=source_id,
                event_index=state.event_index,
            )
            records = (
                SettlementRecord(
                    record_type="shield_absorption",
                    source="shield_system",
                    mutation_id=shield_mutation.stable_id(),
                    process_only=False,
                    payload={
                        "target_id": target_id,
                        "damage_family": damage_family,
                        "incoming_damage": incoming_damage,
                        "absorbed_damage": incoming_damage - remaining_damage,
                        "hp_damage": remaining_damage,
                        "consumed_instances": consumed,
                        "exhausted_instance_ids": exhausted,
                        "aggregate_before": _aggregate(before),
                        "aggregate_after": _aggregate(after),
                    },
                    trace=route_source,
                ).to_json(),
            )
        return HPDamageRoute(
            True,
            target_id,
            incoming_damage,
            absorbed_damage=incoming_damage - remaining_damage,
            hp_damage=remaining_damage,
            hp_after=max(0.0, target.hp - remaining_damage),
            shield_mutation=shield_mutation,
            events=events,
            records=records,
            exhausted_instance_ids=tuple(exhausted),
            route_policy=route_policy,
            evidence={"route_source": route_source, "consumed_instances": consumed},
        )


def aggregate_shield(instances: tuple[dict[str, JSONValue], ...]) -> float:
    return _aggregate([dict(item) for item in instances])


def _instance(
    *,
    shield_id: str,
    source_id: str,
    source_actor_id: str,
    source_kind: str,
    remaining: float,
    capacity: float,
    priority: int,
    stack_policy: str,
    absorb_families: tuple[str, ...],
    created_event_index: int,
    source_trace: dict[str, JSONValue],
    priority_source: dict[str, JSONValue],
    priority_rule: dict[str, JSONValue],
    owner_modifier_name: str,
    status_instance_id: str,
) -> dict[str, JSONValue]:
    return {
        "instance_id": f"{shield_id}:source:{source_id}:actor:{source_actor_id}",
        "shield_id": shield_id,
        "source_id": source_id,
        "source_actor_id": source_actor_id,
        "source_kind": source_kind,
        "remaining": float(remaining),
        "capacity": float(capacity),
        "priority": priority,
        "stack_policy": stack_policy,
        "absorb_families": list(absorb_families),
        "created_event_index": created_event_index,
        "source_trace": source_trace,
        "priority_audit": priority_source,
        "priority_rule": priority_rule,
        "owner_modifier_name": owner_modifier_name,
        "status_instance_id": status_instance_id,
    }


def _ordered(instances: list[dict[str, JSONValue]]) -> list[dict[str, JSONValue]]:
    return sorted(
        instances,
        key=lambda item: (
            -int(item.get("priority", 0)),
            int(item.get("created_event_index", 0)),
            str(item.get("shield_id") or ""),
        ),
    )


def _aggregate(instances: list[dict[str, JSONValue]]) -> float:
    return sum(float(item.get("remaining", 0.0)) for item in instances)
