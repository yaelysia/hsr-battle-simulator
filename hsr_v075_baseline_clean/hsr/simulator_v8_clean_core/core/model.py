from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal

from .transition_outcome import TransitionOutcome, unclassified_transition_outcome


JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
UnitSide = Literal["ally", "enemy", "summon"]


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
    flags: dict[str, JSONValue] = field(default_factory=dict)
    resources: dict[str, float] = field(default_factory=dict)

    def to_snapshot(self) -> dict[str, JSONValue]:
        shield = float(self.resources.get("shield", 0.0))
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
        teams = {
            "ally": [unit_id for unit_id, unit in sorted(self.units.items()) if unit.side == "ally"],
            "enemy": [unit_id for unit_id, unit in sorted(self.units.items()) if unit.side == "enemy"],
            "summon": [unit_id for unit_id, unit in sorted(self.units.items()) if unit.side == "summon"],
        }
        active_teams = {
            "ally": [unit_id for unit_id, unit in sorted(self.units.items()) if unit.side == "ally" and _unit_lifecycle_status(unit) == "active"],
            "enemy": [unit_id for unit_id, unit in sorted(self.units.items()) if unit.side == "enemy" and _unit_lifecycle_status(unit) == "active"],
            "summon": [unit_id for unit_id, unit in sorted(self.units.items()) if unit.side == "summon" and _unit_lifecycle_status(unit) == "active"],
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
                        unit_id: unit.action_value for unit_id, unit in sorted(self.units.items())
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
    legal: tuple[str, ...] = ()
    selected: tuple[str, ...] = ()
    rejected: tuple[str, ...] = ()
    reason: str = "not_resolved"
    source: str = "target_system"
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "requested": list(self.requested),
            "legal": list(self.legal),
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

    op: str
    path: tuple[str, ...]
    before: JSONValue
    after: JSONValue
    reason: str
    source: str
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    mutation_id: str = ""

    def stable_id(self) -> str:
        return self.mutation_id or _stable_id(
            "mutation",
            {
                "op": self.op,
                "path": list(self.path),
                "before": self.before,
                "after": self.after,
                "reason": self.reason,
                "source": self.source,
                "metadata": self.metadata,
            },
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "mutation_id": self.stable_id(),
            "op": self.op,
            "path": list(self.path),
            "before": self.before,
            "after": self.after,
            "reason": self.reason,
            "source": self.source,
            "metadata": self.metadata,
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
