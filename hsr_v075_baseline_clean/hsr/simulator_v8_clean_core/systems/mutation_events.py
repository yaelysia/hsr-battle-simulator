from __future__ import annotations

from dataclasses import replace

from ..core.model import GameEvent, JSONValue, Mutation


MUTATION_BACKED_EVENT_TYPES = {
    "hp.change",
    "heal.after",
    "shield.change",
    "shield.exhausted",
    "sp.change",
    "energy.before_change",
    "energy.change",
    "toughness.before_hit",
    "action_delay.changed",
}

PRE_MUTATION_BLOCK_REASON = "pre_mutation_listener_recompute_not_admitted"


def events_for_mutation(
    mutation: Mutation,
    *,
    actor_id: str = "",
    source_id: str = "",
    event_index: int = 0,
    include_before: bool = True,
    extra_payload: dict[str, JSONValue] | None = None,
) -> tuple[GameEvent, ...]:
    """Create process-only listener events from an already admitted mutation."""

    path = tuple(mutation.path)
    payload = _base_payload(
        mutation,
        actor_id=actor_id,
        source_id=source_id,
        extra_payload=extra_payload,
    )
    event_source_id = source_id or actor_id or _payload_str(payload, "source_id") or mutation.source
    target_id = _target_id_for_path(path)
    event_id_prefix = f"event:{event_index}:mutation_backed:{mutation.stable_id()}"

    if _is_unit_hp_path(path):
        delta = _numeric_delta(mutation.before, mutation.after)
        if delta is None or delta == 0:
            return ()
        if delta > 0 and _is_heal_mutation(mutation):
            callback_events = ["OnHPChange", "OnListenHPChange", "OnAfterBeingHeal", "OnAfterDealHeal"]
            if _heal_overflow_proved(mutation, delta):
                callback_events.append("OnHPOverflow")
            return (
                GameEvent(
                    event_type="heal.after",
                    source_id=event_source_id,
                    target_id=target_id,
                    event_id=f"{event_id_prefix}:heal_after",
                    window="OnAfterBeingHeal",
                    process_only=True,
                    payload={
                        **payload,
                        "callback_events": callback_events,
                        "listener_scope": "being_hit_target_local",
                        "heal_amount": delta,
                        "actual_delta": delta,
                        "overflow_amount": _heal_overflow_amount(mutation, delta),
                    },
                ),
            )
        return (
            GameEvent(
                event_type="hp.change",
                source_id=event_source_id,
                target_id=target_id,
                event_id=f"{event_id_prefix}:hp_change",
                window="OnHPChange",
                process_only=True,
                payload={
                    **payload,
                    "callback_events": ["OnHPChange", "OnListenHPChange"],
                    "listener_scope": "being_hit_target_local",
                },
            ),
        )

    if _is_shield_path(path):
        before_total = _shield_total(mutation.before)
        after_total = _shield_total(mutation.after)
        callback_events = ["OnShieldChange", "OnListenShieldChange"]
        if before_total <= 0 and after_total > 0:
            callback_events.append("OnListenInitShield")
        events = [
            GameEvent(
                event_type="shield.change",
                source_id=event_source_id,
                target_id=target_id,
                event_id=f"{event_id_prefix}:shield_change",
                window="OnShieldChange",
                process_only=True,
                payload={
                    **payload,
                    "callback_events": callback_events,
                    "listener_scope": "being_hit_target_local",
                    "resource": "shield",
                    "aggregate_before": before_total,
                    "aggregate_after": after_total,
                    "exhausted_instance_ids": mutation.metadata.get("exhausted_instance_ids", []),
                },
            ),
        ]
        exhausted_ids = mutation.metadata.get("exhausted_instance_ids")
        if isinstance(exhausted_ids, (list, tuple)) and exhausted_ids:
            events.append(
                GameEvent(
                    event_type="shield.exhausted",
                    source_id=event_source_id,
                    target_id=target_id,
                    event_id=f"{event_id_prefix}:shield_exhausted",
                    window="OnShieldChange",
                    process_only=True,
                    payload={
                        **payload,
                        "callback_events": ["OnShieldChange", "OnListenShieldChange"],
                        "listener_scope": "being_hit_target_local",
                        "resource": "shield",
                        "exhausted_instance_ids": list(exhausted_ids),
                        "aggregate_before": before_total,
                        "aggregate_after": after_total,
                    },
                )
            )
        return tuple(events)

    if path == ("skill_points",):
        sp_target_id = actor_id or target_id
        return (
            GameEvent(
                event_type="sp.change",
                source_id=event_source_id,
                target_id=sp_target_id,
                event_id=f"{event_id_prefix}:sp_change",
                window="OnSPChange",
                process_only=True,
                payload={
                    **payload,
                    "callback_events": ["OnSPChange"],
                    "listener_scope": "being_hit_target_local",
                    "resource": "skill_points",
                    "target_id": sp_target_id,
                },
            ),
        )

    if _is_energy_path(path):
        after_event = GameEvent(
            event_type="energy.change",
            source_id=event_source_id,
            target_id=target_id,
            event_id=f"{event_id_prefix}:energy_change",
            window="OnEnergyPointChange",
            process_only=True,
            payload={
                **payload,
                "callback_events": ["OnEnergyPointChange"],
                "listener_scope": "being_hit_target_local",
                "resource": "energy",
            },
        )
        if not include_before:
            return (after_event,)
        before_event = GameEvent(
            event_type="energy.before_change",
            source_id=event_source_id,
            target_id=target_id,
            event_id=f"{event_id_prefix}:energy_before_change",
            window="OnBeforeEnergyPointChange",
            process_only=True,
            payload={
                **payload,
                "callback_events": ["OnBeforeEnergyPointChange"],
                "listener_scope": "being_hit_target_local",
                "pre_mutation_execution_admission": "blocked",
                "blocked_reason": PRE_MUTATION_BLOCK_REASON,
            },
        )
        return (before_event, after_event)

    if _is_action_value_path(path) and _is_action_delay_mutation(mutation):
        return (
            GameEvent(
                event_type="action_delay.changed",
                source_id=event_source_id,
                target_id=target_id,
                event_id=f"{event_id_prefix}:action_delay_changed",
                window="OnActionDelayEffect",
                process_only=True,
                payload={
                    **payload,
                    "callback_events": [
                        "OnActionDelayEffect",
                        "OnActionDelayEffectAll",
                        "OnListenGlobalActionDelayChanged",
                    ],
                    "listener_scope": "being_hit_target_local",
                },
            ),
        )

    return ()


def before_toughness_event(
    mutation: Mutation,
    *,
    actor_id: str,
    event_index: int,
    extra_payload: dict[str, JSONValue] | None = None,
) -> GameEvent | None:
    if not _is_toughness_path(tuple(mutation.path)):
        return None
    payload = _base_payload(mutation, actor_id=actor_id, source_id=actor_id, extra_payload=extra_payload)
    target_id = _target_id_for_path(tuple(mutation.path))
    return GameEvent(
        event_type="toughness.before_hit",
        source_id=actor_id,
        target_id=target_id,
        event_id=f"event:{event_index}:mutation_backed:{mutation.stable_id()}:toughness_before_hit",
        window="OnBeforeBeingStanceDamage",
        process_only=True,
        payload={
            **payload,
            "callback_events": ["OnBeforeBeingStanceDamage"],
            "listener_scope": "being_hit_target_local",
            "pre_mutation_execution_admission": "blocked",
            "blocked_reason": PRE_MUTATION_BLOCK_REASON,
        },
    )


def before_toughness_calculation_event(
    *,
    actor_id: str,
    target_id: str,
    event_index: int,
    packet: dict[str, JSONValue],
    extra_payload: dict[str, JSONValue] | None = None,
) -> GameEvent:
    return GameEvent(
        event_type="toughness.before_hit",
        source_id=actor_id,
        target_id=target_id,
        event_id=f"event:{event_index}:toughness_before_calculation:{actor_id}:{target_id}",
        window="OnBeforeBeingStanceDamage",
        process_only=True,
        payload={
            **(extra_payload or {}),
            "callback_events": ["OnBeforeBeingStanceDamage"],
            "listener_scope": "being_hit_target_local",
            "pre_calculation_execution_admission": "executable",
            "calculation_reloads_updated_state": True,
            "toughness_packet": packet,
            "actor_id": actor_id,
            "target_id": target_id,
        },
    )


def enrich_event_with_mutation_payload(event: GameEvent, mutation: Mutation) -> GameEvent:
    payload = _base_payload(
        mutation,
        actor_id=_payload_str(event.payload, "actor_id") or _payload_str(event.payload, "attacker_id"),
        source_id=str(event.source_id or ""),
        extra_payload=dict(event.payload),
    )
    callback_events = event.payload.get("callback_events")
    if isinstance(callback_events, list):
        payload["callback_events"] = list(callback_events)
    return replace(event, payload=payload)


def _base_payload(
    mutation: Mutation,
    *,
    actor_id: str,
    source_id: str,
    extra_payload: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    metadata = dict(mutation.metadata)
    path = tuple(mutation.path)
    target_id = _target_id_for_path(path)
    delta = _numeric_delta(mutation.before, mutation.after)
    payload: dict[str, JSONValue] = {
        **(extra_payload or {}),
        "mutation_backed_event": True,
        "mutation_id": mutation.stable_id(),
        "mutation_path": list(path),
        "before": mutation.before,
        "after": mutation.after,
        "delta": delta,
        "source": mutation.source,
        "reason": mutation.reason,
        "source_trace": _source_trace(metadata),
        "target_id": target_id,
        "actor_id": actor_id or _metadata_actor_id(metadata),
        "source_id": source_id or _metadata_source_id(metadata),
        "source_kind": _source_kind(mutation),
        "resource_operation": _payload_str(metadata, "resource_operation"),
        "metadata": metadata,
    }
    resource = _resource_for_path(path, metadata)
    if resource:
        payload["resource"] = resource
    return payload


def _target_id_for_path(path: tuple[str, ...]) -> str:
    if len(path) >= 2 and path[0] == "units":
        return path[1]
    return ""


def _resource_for_path(path: tuple[str, ...], metadata: dict[str, JSONValue]) -> str:
    if path == ("skill_points",):
        return "skill_points"
    if len(path) >= 3 and path[0] == "units" and path[2] == "energy":
        return "energy"
    if len(path) >= 4 and path[0] == "units" and path[2] == "resources":
        return path[3]
    resource = metadata.get("resource")
    return str(resource) if isinstance(resource, str) else ""


def _source_trace(metadata: dict[str, JSONValue]) -> dict[str, JSONValue]:
    for key in ("source_trace", "effect_source", "resource_rule_source", "break_template_source"):
        value = metadata.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _source_kind(mutation: Mutation) -> str:
    metadata = mutation.metadata
    explicit = metadata.get("resource_rule_source_kind")
    if isinstance(explicit, str) and explicit:
        return explicit
    if mutation.source == "effect_system" and isinstance(metadata.get("effect_source"), dict):
        return "tbgd_effect"
    if mutation.source in {"combat_executor.resources", "resource_system"}:
        return "engine_convention"
    if mutation.source == "damage_system":
        return "damage_system"
    if mutation.source == "toughness_system":
        return "toughness_system"
    if mutation.source == "status_callback_system":
        return "status_callback_system"
    return mutation.source


def _metadata_actor_id(metadata: dict[str, JSONValue]) -> str:
    for key in ("actor_id", "caster_id", "attacker_id", "damage_attacker_id"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _metadata_source_id(metadata: dict[str, JSONValue]) -> str:
    value = metadata.get("source_id")
    return str(value) if isinstance(value, str) and value else ""


def _payload_str(payload: dict[str, JSONValue], key: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else ""


def _numeric_value(value: JSONValue) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _numeric_delta(before: JSONValue, after: JSONValue) -> float | None:
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return None
    return float(after) - float(before)


def _is_unit_hp_path(path: tuple[str, ...]) -> bool:
    return len(path) == 3 and path[0] == "units" and path[2] == "hp"


def _is_shield_path(path: tuple[str, ...]) -> bool:
    return (
        len(path) == 3
        and path[0] == "units"
        and path[2] == "shield_instances"
    ) or (
        len(path) == 4
        and path[0] == "units"
        and path[2] == "resources"
        and path[3] == "shield"
    )


def _shield_total(value: JSONValue) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, (list, tuple)):
        return 0.0
    return sum(
        float(item.get("remaining", 0.0))
        for item in value
        if isinstance(item, dict)
        and isinstance(item.get("remaining"), (int, float))
        and not isinstance(item.get("remaining"), bool)
    )


def _is_energy_path(path: tuple[str, ...]) -> bool:
    return len(path) == 3 and path[0] == "units" and path[2] == "energy"


def _is_toughness_path(path: tuple[str, ...]) -> bool:
    return len(path) == 3 and path[0] == "units" and path[2] == "toughness"


def _is_action_value_path(path: tuple[str, ...]) -> bool:
    return len(path) == 3 and path[0] == "units" and path[2] == "action_value"


def _is_heal_mutation(mutation: Mutation) -> bool:
    opcode = mutation.metadata.get("opcode")
    return (
        mutation.reason == "apply numeric heal effect"
        or opcode in {"Heal", "HealHP"}
        or str(mutation.metadata.get("effect_kind") or "") == "heal"
    )


def _heal_overflow_proved(mutation: Mutation, delta: float) -> bool:
    amount = mutation.metadata.get("amount")
    return isinstance(amount, (int, float)) and float(amount) > delta


def _heal_overflow_amount(mutation: Mutation, delta: float) -> float:
    amount = mutation.metadata.get("amount")
    if isinstance(amount, (int, float)):
        return max(0.0, float(amount) - delta)
    return 0.0


def _is_action_delay_mutation(mutation: Mutation) -> bool:
    return (
        mutation.source == "status_callback_system"
        and mutation.metadata.get("opcode") == "SetActionDelay"
        and bool(mutation.metadata.get("action_delay_emission_id"))
    )
