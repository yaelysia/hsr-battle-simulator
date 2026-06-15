from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


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
        return {
            "unit_id": self.unit_id,
            "side": self.side,
            "template_id": self.template_id,
            "level": self.level,
            "max_hp": self.max_hp,
            "hp": self.hp,
            "attack": self.attack,
            "defense": self.defense,
            "speed": self.speed,
            "energy": self.energy,
            "max_energy": self.max_energy,
            "toughness": self.toughness,
            "max_toughness": self.max_toughness,
            "action_value": self.action_value,
            "statuses": list(self.statuses),
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
    queues: dict[str, tuple[str, ...]] = field(default_factory=dict)
    rng_state: str = "deterministic"
    event_index: int = 0

    def snapshot(self) -> "Snapshot":
        units = {unit_id: unit.to_snapshot() for unit_id, unit in sorted(self.units.items())}
        return Snapshot(
            {
                "event_index": self.event_index,
                "global_flags": dict(sorted(self.global_flags.items())),
                "max_skill_points": self.max_skill_points,
                "queues": {key: list(value) for key, value in sorted(self.queues.items())},
                "rng_state": self.rng_state,
                "skill_points": self.skill_points,
                "units": units,
                "wave_index": self.wave_index,
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
    target_ids: tuple[str, ...] = ()
    source: Literal["manual", "ai", "queue"] = "manual"
    queue_name: str | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class GameEvent:
    event_type: str
    source_id: str | None = None
    target_id: str | None = None
    payload: dict[str, JSONValue] = field(default_factory=dict)


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

    def to_json(self) -> dict[str, JSONValue]:
        return {
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
    settlement: ActionSettlement | None = None


@dataclass(frozen=True)
class BattleTransition:
    transaction: ActionTransaction
    after: Snapshot
    coverage: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "before": self.transaction.before.to_json(),
            "after": self.after.to_json(),
            "command": {
                "actor_id": self.transaction.command.actor_id,
                "action_id": self.transaction.command.action_id,
                "target_ids": list(self.transaction.command.target_ids),
                "source": self.transaction.command.source,
                "queue_name": self.transaction.command.queue_name,
                "metadata": self.transaction.command.metadata,
            },
            "events": [
                {
                    "event_type": event.event_type,
                    "source_id": event.source_id,
                    "target_id": event.target_id,
                    "payload": event.payload,
                }
                for event in self.transaction.events
            ],
            "mutations": [mutation.to_json() for mutation in self.transaction.mutations],
            "settlement": self.transaction.settlement.to_json()
            if self.transaction.settlement
            else None,
            "coverage": self.coverage,
        }

