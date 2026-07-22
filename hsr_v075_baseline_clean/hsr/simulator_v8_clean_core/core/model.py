from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Literal

from .immutable_json import freeze_json, thaw_json
from .transition_outcome import TransitionOutcome, unclassified_transition_outcome


JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
UnitSide = Literal["ally", "enemy", "summon"]
MutationOp = Literal["set", "delete", "spawn"]
UNIT_STAT_POOL_PANEL_FIELDS = frozenset(
    {"max_hp", "attack", "defense", "speed", "max_energy"}
)


@dataclass(frozen=True)
class UnitStatPool:
    """One runtime base-stat pool preserved from the formal build ledger."""

    property_type: str
    base_value: float
    static_percentage: float = 0.0
    static_flat: float = 0.0
    base_contribution_ids: tuple[str, ...] = ()
    percentage_contribution_ids: tuple[str, ...] = ()
    flat_contribution_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.property_type, str) or not self.property_type:
            raise ValueError("unit stat pool requires a non-empty property_type")
        for field_name in ("base_value", "static_percentage", "static_flat"):
            value = getattr(self, field_name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(f"unit stat pool {field_name} must be numeric")
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError(f"unit stat pool {field_name} must be finite")
            object.__setattr__(self, field_name, numeric)
        for field_name in (
            "base_contribution_ids",
            "percentage_contribution_ids",
            "flat_contribution_ids",
        ):
            values = getattr(self, field_name)
            if not isinstance(values, (list, tuple)) or not all(
                isinstance(item, str) and item for item in values
            ):
                raise TypeError(f"unit stat pool {field_name} must contain non-empty strings")
            if len(set(values)) != len(values):
                raise ValueError(f"unit stat pool {field_name} contains duplicate identities")
            object.__setattr__(self, field_name, tuple(sorted(values)))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "property_type": self.property_type,
            "base_value": self.base_value,
            "static_percentage": self.static_percentage,
            "static_flat": self.static_flat,
            "base_contribution_ids": list(self.base_contribution_ids),
            "percentage_contribution_ids": list(self.percentage_contribution_ids),
            "flat_contribution_ids": list(self.flat_contribution_ids),
        }


@dataclass(frozen=True)
class UnitState:
    """Runtime state for one combat unit.

    This is deliberately small for v0_200. New mechanics should extend this
    explicit model instead of adding dynamic attributes or legacy context bags.
    """

    unit_id: str
    side: UnitSide
    template_id: str
    level: int = 80
    max_hp: float = 1.0
    hp: float = 1.0
    attack: float = 0.0
    defense: float = 0.0
    speed: float = 100.0
    energy: float = 0.0
    max_energy: float = 0.0
    toughness: float = 0.0
    max_toughness: float = 0.0
    action_value: float = 0.0
    statuses: tuple[str, ...] = ()
    shield_instances: tuple[dict[str, JSONValue], ...] = ()
    flags: dict[str, JSONValue] = field(default_factory=dict)
    resources: dict[str, float] = field(default_factory=dict)
    stat_pools: tuple[UnitStatPool, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.stat_pools, (list, tuple)) or not all(
            isinstance(pool, UnitStatPool) for pool in self.stat_pools
        ):
            raise TypeError("unit stat_pools must contain UnitStatPool values")
        pools = tuple(self.stat_pools)
        property_types = tuple(pool.property_type for pool in pools)
        if len(set(property_types)) != len(property_types):
            raise ValueError("unit stat_pools contain duplicate property types")
        if property_types != tuple(sorted(property_types)):
            raise ValueError("unit stat_pools must use canonical property ordering")
        unsupported = sorted(set(property_types).difference(UNIT_STAT_POOL_PANEL_FIELDS))
        if unsupported:
            raise ValueError(f"unit stat_pools contain unsupported properties: {unsupported}")
        for pool in pools:
            expected = (
                pool.base_value * (1.0 + pool.static_percentage)
                + pool.static_flat
            )
            panel_value = getattr(self, pool.property_type)
            if not isinstance(panel_value, (int, float)) or isinstance(panel_value, bool):
                raise TypeError(
                    f"unit panel field {pool.property_type} must be numeric"
                )
            if not math.isfinite(float(panel_value)) or not math.isclose(
                float(panel_value),
                expected,
                rel_tol=1e-12,
                abs_tol=1e-9,
            ):
                raise ValueError(
                    f"unit panel field {pool.property_type} does not match its stat pool"
                )
        object.__setattr__(self, "stat_pools", pools)

    def to_snapshot(self) -> dict[str, JSONValue]:
        shield = sum(
            float(instance.get("remaining", 0.0))
            for instance in self.shield_instances
            if isinstance(instance.get("remaining"), (int, float))
            and not isinstance(instance.get("remaining"), bool)
        )
        recoverable_hp = float(self.resources.get("recoverable_hp", 0.0))
        lifecycle_status = _unit_lifecycle_status(self)
        lifecycle = {
            "status": lifecycle_status,
            "active": lifecycle_status == "active",
            "defeated": lifecycle_status == "defeated",
            "removed": lifecycle_status == "removed",
            "defeat_record": self.flags.get("defeat_record", {}),
            "removed_record": self.flags.get("removed_record", {}),
        }
        return {
            "unit_id": self.unit_id,
            "side": self.side,
            "template_id": self.template_id,
            "template_source": {"kind": self.template_id.split(":", 1)[0], "id": self.template_id},
            "position": self.flags.get("position"),
            "level": self.level,
            "max_hp": self.max_hp,
            "hp": self.hp,
            "lifecycle_status": lifecycle_status,
            "defeated": lifecycle_status == "defeated",
            "removed": lifecycle_status == "removed",
            "lifecycle": lifecycle,
            "attack": self.attack,
            "defense": self.defense,
            "speed": self.speed,
            "base_stats": {
                "max_hp": self.max_hp,
                "attack": self.attack,
                "defense": self.defense,
                "speed": self.speed,
            },
            "derived_stats": {
                "critical_chance": float(self.resources.get("critical_chance", 0.0)),
                "critical_damage": float(self.resources.get("critical_damage", 0.0)),
                "damage_added_ratio": float(self.resources.get("damage_added_ratio", 0.0)),
                "break_damage_added_ratio": float(self.resources.get("break_damage_added_ratio", 0.0)),
                "effect_hit_rate": float(self.resources.get("effect_hit_rate", 0.0)),
                "effect_resistance": float(self.resources.get("effect_resistance", 0.0)),
            },
            "energy": self.energy,
            "max_energy": self.max_energy,
            "shield": shield,
            "shield_instances": [dict(instance) for instance in self.shield_instances],
            "recoverable_hp": recoverable_hp,
            "toughness": self.toughness,
            "max_toughness": self.max_toughness,
            "toughness_state": {
                "current": self.toughness,
                "maximum": self.max_toughness,
                "weaknesses": list(self.flags.get("weaknesses", ())),
                "weakness_locked": bool(self.flags.get("weakness_locked", False)),
                "broken": bool(self.flags.get("broken", False)),
                "break_delay": float(self.resources.get("break_delay", 0.0)),
            },
            "action_value": self.action_value,
            "statuses": list(self.statuses),
            "status_details": list(self.flags.get("status_details", ())),
            "modifiers": list(self.flags.get("modifiers", ())),
            "flags": dict(sorted(self.flags.items())),
            "resources": dict(sorted(self.resources.items())),
            "stat_pools": [pool.to_json() for pool in self.stat_pools],
        }


@dataclass(frozen=True)
class BattleState:
    """Complete combat state owned by v8 runtime."""

    units: dict[str, UnitState] = field(default_factory=dict)
    wave_index: int = 0
    skill_points: int = 3
    max_skill_points: int = 5
    global_flags: dict[str, JSONValue] = field(default_factory=dict)
    queues: dict[str, tuple[JSONValue, ...]] = field(default_factory=dict)
    rng_state: str = "deterministic"
    event_index: int = 0

    def snapshot(self) -> "Snapshot":
        units = {unit_id: unit.to_snapshot() for unit_id, unit in sorted(self.units.items())}
        global_flags = {
            "dynamic_value_store": {"entries": {}, "by_hash": {}, "by_name": {}},
            **self.global_flags,
        }
        combat_units = {
            unit_id: unit
            for unit_id, unit in self.units.items()
            if not unit.flags.get("system_entity_kind")
        }
        teams = {
            "ally": [unit_id for unit_id, unit in sorted(combat_units.items()) if unit.side == "ally"],
            "enemy": [unit_id for unit_id, unit in sorted(combat_units.items()) if unit.side == "enemy"],
            "summon": [unit_id for unit_id, unit in sorted(combat_units.items()) if unit.side == "summon"],
        }
        active_teams = {
            "ally": [unit_id for unit_id, unit in sorted(combat_units.items()) if unit.side == "ally" and _unit_lifecycle_status(unit) == "active"],
            "enemy": [unit_id for unit_id, unit in sorted(combat_units.items()) if unit.side == "enemy" and _unit_lifecycle_status(unit) == "active"],
            "summon": [unit_id for unit_id, unit in sorted(combat_units.items()) if unit.side == "summon" and _unit_lifecycle_status(unit) == "active"],
        }
        return Snapshot(
            {
                "battle": {
                    "wave_index": self.wave_index,
                    "phase": str(global_flags.get("phase", "setup")),
                    "current_window": str(global_flags.get("current_window", "idle")),
                    "action_index": self.event_index,
                    "turn_owner_id": global_flags.get("turn_owner_id"),
                },
                "event_index": self.event_index,
                "global_flags": dict(sorted(global_flags.items())),
                "max_skill_points": self.max_skill_points,
                "metadata": {
                    "snapshot_contract": "v0_203",
                    "rng_state": self.rng_state,
                },
                "pending_events": list(global_flags.get("pending_events", ())),
                "queues": {key: list(value) for key, value in sorted(self.queues.items())},
                "resources": {
                    "skill_points": self.skill_points,
                    "max_skill_points": self.max_skill_points,
                },
                "rng_state": self.rng_state,
                "rng_events": list(global_flags.get("rng_events", ())),
                "skill_points": self.skill_points,
                "targeting": dict(global_flags.get("targeting", {})),
                "teams": teams,
                "active_teams": active_teams,
                "timeline": {
                    "global_av": float(global_flags.get("global_av", 0.0)),
                    "turn_owner_id": global_flags.get("turn_owner_id"),
                    "active_turn": dict(global_flags.get("active_turn", {})),
                    "turn_queue_policy": dict(global_flags.get("turn_queue_policy", {})),
                    "last_advanced_delta": float(global_flags.get("last_advanced_delta", 0.0)),
                    "turn_sequence_index": int(global_flags.get("turn_sequence_index", 0)),
                    "action_values": {
                        unit_id: unit.action_value for unit_id, unit in sorted(combat_units.items())
                    },
                    "queues": {key: list(value) for key, value in sorted(self.queues.items())},
                },
                "units": units,
                "wave_index": self.wave_index,
                "settlement": dict(global_flags.get("settlement", {})),
                "coverage": dict(global_flags.get("coverage", {})),
            }
        )


@dataclass(frozen=True)
class Snapshot:
    data: dict[str, JSONValue]

    def to_json(self) -> dict[str, JSONValue]:
        return self.data


@dataclass(frozen=True)
class ActionCommand:
    """External input to one action transaction."""

    actor_id: str
    action_id: str
    action_level: int
    target_ids: tuple[str, ...] = ()
    source: Literal["manual", "ai", "queue"] = "manual"
    queue_name: str | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class GameEvent:
    event_type: str
    source_id: str | None = None
    target_id: str | None = None
    event_id: str = ""
    window: str = "unspecified"
    process_only: bool = True
    payload: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        event_id = self.event_id or _stable_id(
            "event",
            {
                "event_type": self.event_type,
                "source_id": self.source_id,
                "target_id": self.target_id,
                "window": self.window,
                "payload": self.payload,
            },
        )
        return {
            "event_id": event_id,
            "event_type": self.event_type,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "window": self.window,
            "process_only": self.process_only,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class RNGEvent:
    rng_type: str
    source: str
    result: JSONValue
    event_id: str = ""
    before_state: str | None = None
    after_state: str | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        event_id = self.event_id or _stable_id(
            "rng",
            {
                "rng_type": self.rng_type,
                "source": self.source,
                "result": self.result,
                "before_state": self.before_state,
                "after_state": self.after_state,
                "metadata": self.metadata,
            },
        )
        return {
            "event_id": event_id,
            "rng_type": self.rng_type,
            "source": self.source,
            "before_state": self.before_state,
            "after_state": self.after_state,
            "result": self.result,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class TargetResolution:
    requested: tuple[str, ...] = ()
    selectable: tuple[str, ...] = ()
    legal: tuple[str, ...] = ()
    primary: str | None = None
    impact_group: tuple[str, ...] = ()
    selected: tuple[str, ...] = ()
    rejected: tuple[str, ...] = ()
    reason: str = "not_resolved"
    source: str = "target_system"
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "requested": list(self.requested),
            "selectable": list(self.selectable),
            "legal": list(self.legal),
            "primary": self.primary,
            "impact_group": list(self.impact_group),
            "selected": list(self.selected),
            "rejected": list(self.rejected),
            "reason": self.reason,
            "source": self.source,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class Mutation:
    """Single authoritative state change.

    All runtime systems must emit mutations instead of mutating BattleState
    directly. Process-only records should be represented as GameEvent.
    """

    op: MutationOp | str
    path: tuple[str, ...]
    before: JSONValue
    after: JSONValue
    reason: str
    source: str
    before_exists: bool = True
    after_exists: bool = True
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    mutation_id: str = ""
    _stable_id_cache: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.op, str):
            raise TypeError("mutation op must be a string")
        path = tuple(self.path)
        if not all(isinstance(item, str) for item in path):
            raise TypeError("mutation path segments must be strings")
        if type(self.before_exists) is not bool or type(self.after_exists) is not bool:
            raise TypeError("mutation existence markers must be bool values")
        if not isinstance(self.reason, str) or not isinstance(self.source, str):
            raise TypeError("mutation reason and source must be strings")
        if not isinstance(self.mutation_id, str):
            raise TypeError("mutation_id must be a string")
        before = freeze_json(self.before)
        after = freeze_json(self.after)
        metadata = freeze_json(self.metadata)
        if not isinstance(metadata, dict):
            raise TypeError("mutation metadata must be a JSON object")
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "before", before)
        object.__setattr__(self, "after", after)
        object.__setattr__(self, "metadata", metadata)
        stable_id = self.mutation_id or _stable_id(
            "mutation",
            {
                "op": self.op,
                "path": list(path),
                "before": thaw_json(before),
                "before_exists": self.before_exists,
                "after": thaw_json(after),
                "after_exists": self.after_exists,
                "reason": self.reason,
                "source": self.source,
                "metadata": thaw_json(metadata),
            },
        )
        object.__setattr__(self, "_stable_id_cache", stable_id)

    def stable_id(self) -> str:
        return self._stable_id_cache

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "mutation_id": self.stable_id(),
            "op": self.op,
            "path": list(self.path),
            "before": thaw_json(self.before),
            "before_exists": self.before_exists,
            "after": thaw_json(self.after),
            "after_exists": self.after_exists,
            "reason": self.reason,
            "source": self.source,
            "metadata": thaw_json(self.metadata),
        }


@dataclass(frozen=True)
class ActionSettlement:
    action_id: str
    actor_id: str
    target_ids: tuple[str, ...]
    records: tuple[dict[str, JSONValue], ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "action_id": self.action_id,
            "actor_id": self.actor_id,
            "target_ids": list(self.target_ids),
            "records": list(self.records),
        }


@dataclass(frozen=True)
class ActionTransaction:
    command: ActionCommand
    before: Snapshot
    events: tuple[GameEvent, ...] = ()
    mutations: tuple[Mutation, ...] = ()
    trigger_windows: tuple[dict[str, JSONValue], ...] = ()
    settlement: ActionSettlement | None = None


@dataclass(frozen=True)
class BattleTransition:
    transaction: ActionTransaction
    after: Snapshot
    target_resolution: TargetResolution = field(default_factory=TargetResolution)
    rng_events: tuple[RNGEvent, ...] = ()
    outcome: TransitionOutcome = field(default_factory=unclassified_transition_outcome)
    coverage: dict[str, JSONValue] = field(default_factory=dict)
    contract_validation: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "before": self.transaction.before.to_json(),
            "after": self.after.to_json(),
            "command": {
                "actor_id": self.transaction.command.actor_id,
                "action_id": self.transaction.command.action_id,
                "action_level": self.transaction.command.action_level,
                "target_ids": list(self.transaction.command.target_ids),
                "source": self.transaction.command.source,
                "queue_name": self.transaction.command.queue_name,
                "metadata": self.transaction.command.metadata,
            },
            "target_resolution": self.target_resolution.to_json(),
            "events": [event.to_json() for event in self.transaction.events],
            "rng_events": [event.to_json() for event in self.rng_events],
            "outcome": self.outcome.to_json(),
            "mutations": [mutation.to_json() for mutation in self.transaction.mutations],
            "trigger_windows": list(self.transaction.trigger_windows),
            "settlement": self.transaction.settlement.to_json()
            if self.transaction.settlement
            else None,
            "coverage": self.coverage,
            "contract_validation": self.contract_validation,
        }


def _stable_id(prefix: str, payload: dict[str, JSONValue]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _unit_lifecycle_status(unit: UnitState) -> str:
    raw = unit.flags.get("lifecycle_status")
    if isinstance(raw, str) and raw in {"active", "defeated", "removed"}:
        return raw
    return "defeated" if unit.hp <= 0 else "active"
