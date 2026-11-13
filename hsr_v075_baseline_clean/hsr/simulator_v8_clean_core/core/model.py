from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from ..immutable_json import FrozenJSONDict, FrozenJSONList, freeze_json, thaw_json, json_tree_digest
from .transition_outcome import TransitionOutcome, unclassified_transition_outcome

def current_max_hp(unit: Any) -> float:
    """Return the authoritative current Max-HP ceiling for a unit.

    The units stat layer owns active construction (birth panel + status
    modifiers + conversion bucket).  Resolve it directly instead of relying on
    a registration side effect, so conditions, healing and integrity checks see
    the same ceiling in every process.
    """

    from ..systems.unit_stats import effective_unit_stat

    value = effective_unit_stat(unit, "max_hp").value
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("current_max_hp_result_not_numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("current_max_hp_result_not_finite")
    return numeric


if TYPE_CHECKING:
    from ..rules.ir import ActionDefinitionIR
    from ..systems.battle_event import BattleEventExecutionFact, BattleEventRetirementFact
    from ..systems.unit_spawn import UnitBirthFact
    from ..systems.effect import EffectExecutionFact
    from ..systems.mutation_events import EnergyChangeEventFact, HealEventFact, HPChangeEventFact, HPOverflowFact
    from ..systems.dynamic_values import DynamicValueChangeFact
    from ..systems.ability_property_watchers import AbilityPropertyChangeFact
    from ..systems.shield import ShieldExhaustionFact
    from ..systems.status import StatusLifecyclePlan
    from ..systems.action_event_contract import (
        AdmittedActionTargetFact,
        ActionWindowExpectedScope,
    )


JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
UnitSide = Literal["ally", "enemy", "summon"]
UnitLifecycleStatus = Literal["active", "limbo", "defeated", "removed"]
MutationOp = Literal["set", "delete", "spawn"]
UNIT_LIFECYCLE_STATUSES = frozenset({"active", "limbo", "defeated", "removed"})
LEGACY_UNIT_LIFECYCLE_FLAG_KEYS = frozenset(
    {"lifecycle_status", "lifecycle_state"}
)
UNIT_STAT_POOL_PANEL_FIELDS = frozenset(
    {"max_hp", "attack", "defense", "speed", "max_energy"}
)

_KeyT = TypeVar("_KeyT")
_ValueT = TypeVar("_ValueT")


class _FrozenStateDict(dict[_KeyT, _ValueT]):
    """Shallow immutable mapping for already-normalized committed state values."""

    def __init__(self, values: Mapping[_KeyT, _ValueT] | None = None):
        dict.__init__(self, values or {})

    def _immutable(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("frozen state mapping cannot be mutated")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable

    def __copy__(self) -> _FrozenStateDict[_KeyT, _ValueT]:
        return self

    def __deepcopy__(
        self,
        _memo: dict[int, object],
    ) -> _FrozenStateDict[_KeyT, _ValueT]:
        return self


class _FrozenResourceDict(_FrozenStateDict[str, float]):
    """Validated immutable resource mapping owned by UnitState."""

    def __init__(self, values: Mapping[str, float] | None = None):
        if values is None:
            source: Mapping[object, object] = {}
        elif isinstance(values, Mapping):
            source = values
        else:
            raise TypeError("unit resources must be a mapping")

        resources: dict[str, float] = {}
        for key, value in source.items():
            if not isinstance(key, str):
                raise TypeError("unit resource keys must be strings")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError("unit resource values must be numeric")
            try:
                numeric = float(value)
            except OverflowError as exc:
                raise ValueError(
                    "unit resource values must be finite"
                ) from exc
            if not math.isfinite(numeric):
                raise ValueError("unit resource values must be finite")
            resources[key] = numeric
        super().__init__(resources)


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
    lifecycle_status: UnitLifecycleStatus = "active"
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
        if (
            not isinstance(self.lifecycle_status, str)
            or self.lifecycle_status not in UNIT_LIFECYCLE_STATUSES
        ):
            raise ValueError(
                "unit lifecycle_status must be active, limbo, defeated, or removed"
            )
        if not isinstance(self.statuses, (list, tuple)) or not all(
            isinstance(status, str) for status in self.statuses
        ):
            raise TypeError("unit statuses must contain string values")
        statuses = tuple(self.statuses)

        if not isinstance(self.shield_instances, (list, tuple)):
            raise TypeError("unit shield_instances must be a list or tuple")
        if type(self.shield_instances) is tuple and all(
            type(instance) is FrozenJSONDict
            for instance in self.shield_instances
        ):
            shield_instances = self.shield_instances
        else:
            normalized_shields: list[dict[str, JSONValue]] = []
            for instance in self.shield_instances:
                frozen_instance = freeze_json(instance)
                if not isinstance(frozen_instance, dict):
                    raise TypeError(
                        "unit shield_instances must contain JSON objects"
                    )
                normalized_shields.append(frozen_instance)
            shield_instances = tuple(normalized_shields)

        flags = freeze_json(self.flags)
        if not isinstance(flags, dict):
            raise TypeError("unit flags must be a JSON object")
        legacy_lifecycle_flags = sorted(
            LEGACY_UNIT_LIFECYCLE_FLAG_KEYS.intersection(flags)
        )
        if legacy_lifecycle_flags:
            raise ValueError(
                "unit flags contain reserved lifecycle keys: "
                f"{legacy_lifecycle_flags}"
            )

        if type(self.resources) is _FrozenResourceDict:
            frozen_resources = self.resources
        else:
            frozen_resources = _FrozenResourceDict(self.resources)

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
        object.__setattr__(self, "statuses", statuses)
        object.__setattr__(self, "shield_instances", shield_instances)
        object.__setattr__(self, "flags", flags)
        object.__setattr__(self, "resources", frozen_resources)
        object.__setattr__(self, "stat_pools", pools)

    def to_snapshot(self, *, detach: bool = True) -> dict[str, JSONValue]:
        shield = sum(
            float(instance.get("remaining", 0.0))
            for instance in self.shield_instances
            if isinstance(instance.get("remaining"), (int, float))
            and not isinstance(instance.get("remaining"), bool)
        )
        recoverable_hp = float(self.resources.get("recoverable_hp", 0.0))
        lifecycle_status = self.lifecycle_status
        lifecycle = {
            "status": lifecycle_status,
            "active": lifecycle_status == "active",
            "limbo": lifecycle_status == "limbo",
            "defeated": lifecycle_status == "defeated",
            "removed": lifecycle_status == "removed",
            "defeat_record": self.flags.get("defeat_record", {}),
            "removed_record": self.flags.get("removed_record", {}),
        }
        snapshot = {
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
        # Internal snapshots can share frozen subtrees; public exports stay detached.
        if not detach:
            return snapshot
        detached = thaw_json(snapshot)
        assert isinstance(detached, dict)
        return detached


class _FrozenUnitStateDict(_FrozenStateDict[str, UnitState]):
    """Validated immutable UnitState mapping owned by BattleState."""

    def __init__(self, values: Mapping[str, UnitState] | None = None):
        if values is None:
            source: Mapping[object, object] = {}
        elif isinstance(values, Mapping):
            source = values
        else:
            raise TypeError("battle units must be a mapping")

        units: dict[str, UnitState] = {}
        for unit_id, unit in source.items():
            if not isinstance(unit_id, str):
                raise TypeError("battle unit ids must be strings")
            if not unit_id:
                raise ValueError("battle unit ids must be non-empty")
            if not isinstance(unit, UnitState):
                raise TypeError("battle units must contain UnitState values")
            units[unit_id] = unit
        super().__init__(units)


class _FrozenQueueStateDict(
    _FrozenStateDict[str, tuple[JSONValue, ...]]
):
    """Validated immutable queue mapping owned by BattleState."""

    def __init__(
        self,
        values: Mapping[str, tuple[JSONValue, ...]] | None = None,
    ):
        if values is None:
            source: Mapping[object, object] = {}
        elif isinstance(values, Mapping):
            source = values
        else:
            raise TypeError("battle queues must be a mapping")

        queues: dict[str, tuple[JSONValue, ...]] = {}
        for queue_name, queue in source.items():
            if not isinstance(queue_name, str):
                raise TypeError("battle queue names must be strings")
            if not queue_name:
                raise ValueError("battle queue names must be non-empty")
            if not isinstance(queue, (list, tuple)):
                raise TypeError(
                    "battle queues must contain list or tuple values"
                )
            if type(queue) is tuple and all(
                _is_frozen_json_value(item) for item in queue
            ):
                queues[queue_name] = queue
            else:
                queues[queue_name] = tuple(
                    freeze_json(item) for item in queue
                )
        super().__init__(queues)


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

    def __post_init__(self) -> None:
        if type(self.units) is _FrozenUnitStateDict:
            frozen_units = self.units
        else:
            frozen_units = _FrozenUnitStateDict(self.units)

        global_flags = freeze_json(self.global_flags)
        if not isinstance(global_flags, dict):
            raise TypeError("battle global_flags must be a JSON object")

        if type(self.queues) is _FrozenQueueStateDict:
            frozen_queues = self.queues
        else:
            frozen_queues = _FrozenQueueStateDict(self.queues)

        object.__setattr__(self, "units", frozen_units)
        object.__setattr__(self, "global_flags", global_flags)
        object.__setattr__(self, "queues", frozen_queues)

    def snapshot(self) -> "Snapshot":
        units = {unit_id: unit.to_snapshot(detach=False) for unit_id, unit in sorted(self.units.items())}
        global_flags = {
            "dynamic_value_store": {
                "entries": {},
                "by_hash": {},
                "by_name": {},
                "operation_ledger": {},
            },
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
            "ally": [unit_id for unit_id, unit in sorted(combat_units.items()) if unit.side == "ally" and unit.lifecycle_status == "active"],
            "enemy": [unit_id for unit_id, unit in sorted(combat_units.items()) if unit.side == "enemy" and unit.lifecycle_status == "active"],
            "summon": [unit_id for unit_id, unit in sorted(combat_units.items()) if unit.side == "summon" and unit.lifecycle_status == "active"],
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


def battle_state_revision(state: BattleState) -> str:
    """Shared short state revision, cached on the immutable state instance.

    Decision, contract, scheduler, selection and dynamic values share the
    full digest. BattleState is immutable, so the cache cannot go stale.
    """
    return battle_state_full_fingerprint(state)[:30]


def battle_state_full_fingerprint(state: BattleState) -> str:
    """Full-length state fingerprint (dynamic value store), cached per state."""
    cached = getattr(state, "_state_full_fingerprint_cache", None)
    if cached is not None:
        return cached
    fingerprint = "state:" + json_tree_digest(state.snapshot().to_json(detach=False)).hex()
    object.__setattr__(state, "_state_full_fingerprint_cache", fingerprint)
    return fingerprint


@dataclass(frozen=True)
class Snapshot:
    data: dict[str, JSONValue]

    def __post_init__(self) -> None:
        frozen = freeze_json(self.data)
        if not isinstance(frozen, dict):
            raise TypeError("snapshot data must be a JSON object")
        object.__setattr__(self, "data", frozen)

    def to_json(self, *, detach: bool = True) -> dict[str, JSONValue]:
        detached = thaw_json(self.data) if detach else self.data
        assert isinstance(detached, dict)
        return detached


@dataclass(frozen=True)
class ActionCommand:
    """External input to one action transaction."""

    actor_id: str
    action_id: str
    action_level: int
    target_ids: tuple[str, ...] = ()
    source: Literal["manual", "ai", "queue", "system"] = "manual"
    queue_name: str | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self) is not ActionCommand:
            raise TypeError("action command must not be subclassed")
        if not isinstance(self.actor_id, str) or not self.actor_id:
            raise ValueError("action command actor identity is required")
        if not isinstance(self.action_id, str) or not self.action_id:
            raise ValueError("action command action identity is required")
        if (
            not isinstance(self.action_level, int)
            or isinstance(self.action_level, bool)
            or self.action_level < 0
        ):
            raise ValueError("action command level is invalid")
        if isinstance(self.target_ids, str):
            raise TypeError("action command target identifiers must be a tuple")
        targets = tuple(self.target_ids)
        if any(not isinstance(item, str) or not item for item in targets):
            raise ValueError("action command target identity is invalid")
        if len(targets) != len(set(targets)):
            raise ValueError("action command target identities must be unique")
        if self.source not in {"manual", "ai", "queue", "system"}:
            raise ValueError("action command source is invalid")
        if self.queue_name is not None and (
            not isinstance(self.queue_name, str) or not self.queue_name
        ):
            raise ValueError("action command queue name must be non-empty or null")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("action command metadata must be an object")
        forbidden = {
            "accepted_selection",
            "impact",
            "impact_groups",
            "impact_target_ids",
            "primary_target_ids",
            "query_fingerprint",
            "selection_context",
            "selection_fingerprint",
            "target_contract",
            "target_policy",
            "target_query",
            "target_selection_context",
        }
        injected = tuple(sorted(forbidden & set(self.metadata)))
        if injected:
            raise ValueError(
                "action command metadata contains reserved target fields:"
                + ",".join(injected)
            )
        metadata = freeze_json(dict(self.metadata))
        if not isinstance(metadata, dict):
            raise TypeError("action command metadata freeze failed")
        object.__setattr__(self, "target_ids", targets)
        object.__setattr__(self, "metadata", metadata)


_BREAK_NOTIFICATION_PRODUCER = object()
_QUEUE_ACTION_TERMINAL_PRODUCER = object()
_QUEUE_ACTION_START_PRODUCER = object()
_STANCE_COUNT_DOWN_PRODUCER = object()
_STATUS_IMMUNITY_PRODUCER = object()
_HIT_WINDOW_INVOCATION_PRODUCER = object()


@dataclass(frozen=True)
class HitWindowInvocationFact:
    """One natively produced hit window and its hit-all callback-stack position.

    The damage-window producers are the only authority. The payload marker stays
    a transport copy for the archived event and can never establish the fact.
    """

    event_id: str
    event_type: str
    attacker_id: str
    target_id: str
    sequence_id: str
    in_callback_stack: bool
    _producer_token: object = field(repr=False, compare=False)
    target_status_instance_ids: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self._producer_token is not _HIT_WINDOW_INVOCATION_PRODUCER:
            raise ValueError("hit window fact requires its damage window producer")
        if (
            not all(isinstance(value, str) and value for value in
                    (self.event_id, self.event_type, self.attacker_id, self.target_id))
            or not isinstance(self.sequence_id, str)
            or type(self.in_callback_stack) is not bool
        ):
            raise ValueError("hit window fact identity is invalid")
        if self.target_status_instance_ids is not None and (
                type(self.target_status_instance_ids) is not tuple
                or any(not isinstance(value, str) or not value for value in self.target_status_instance_ids)):
            raise ValueError("hit window status snapshot is invalid")

    def matches(self, event: GameEvent) -> bool:
        """Bind the fact to this exact event, invocation and transport copy."""

        payload = event.payload if isinstance(event.payload, dict) else {}
        return (
            event.event_id == self.event_id
            and event.event_type == self.event_type
            and event.window == self.event_type
            and event.source_id == self.attacker_id
            and event.target_id == self.target_id
            and (payload.get("damage_sequence_source_task_id") or "") == self.sequence_id
            and payload.get("hit_all_callback_stack", False) is self.in_callback_stack
        )


def with_hit_window_invocation_fact(
    event: GameEvent,
    *,
    sequence_id: str,
    in_callback_stack: bool,
    target_status_instance_ids: tuple[str, ...] | None = None,
) -> GameEvent:
    """Attach the native hit-window fact; called only by window producers."""

    return replace(event, hit_window_invocation_fact=HitWindowInvocationFact(
        event_id=event.event_id,
        event_type=event.event_type,
        attacker_id=str(event.source_id or ""),
        target_id=str(event.target_id or ""),
        sequence_id=sequence_id,
        in_callback_stack=in_callback_stack,
        _producer_token=_HIT_WINDOW_INVOCATION_PRODUCER,
        target_status_instance_ids=target_status_instance_ids,
    ))


@dataclass(frozen=True)
class QueueActionTerminalFact:
    """Actor and selected targets of one completed or cancelled queue entry."""

    source_mutation: Mutation = field(repr=False)
    event_id: str
    event_index: int
    event_type: str
    actor_id: str
    target_ids: tuple[str, ...] = field(init=False)
    custom_tag: str = field(init=False)
    queue_intent_id: str = field(init=False)
    _producer_token: object = field(repr=False, compare=False)
    completed_command: ActionCommand | None = field(default=None, repr=False)
    completed_target_resolution: TargetResolution | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        mutation = self.source_mutation
        entry = mutation.metadata.get("queue_entry")
        command = self.completed_command
        resolution = self.completed_target_resolution
        if command is not None and type(command) is not ActionCommand:
            raise ValueError("queue completion requires a typed action command")
        if command is not None:
            if (type(resolution) is not TargetResolution
                    or resolution.source != "action_target_selection_system"
                    or resolution.requested != command.target_ids
                    or not resolution.selected or not resolution.impact_group
                    or not set(resolution.selected).issubset(resolution.impact_group)):
                raise ValueError("queue completion requires the accepted action impact resolution")
            target_ids = resolution.impact_group
        else:
            if resolution is not None:
                raise ValueError("queue action target resolution requires a completed command")
            target_ids = self.accepted_entry_target_ids(entry) if isinstance(entry, dict) else None
        if target_ids is None:
            raise ValueError("queue terminal accepted targets are invalid")
        object.__setattr__(self, "target_ids", target_ids)
        if (
            self._producer_token is not _QUEUE_ACTION_TERMINAL_PRODUCER
            or mutation.source != "queue_system"
            or mutation.op != "set"
            or len(mutation.path) != 2 or mutation.path[0] != "queues"
            or not isinstance(entry, dict)
            or entry.get("actor_id") != self.actor_id
            or (command is not None and (
                command.actor_id != self.actor_id
                or command.source != "queue" or self.event_type != "queue.action.after"
            ))
            or not self.actor_id or not self.event_id
            or self.event_type not in {"queue.action.after", "queue.action.abort"}
            or not isinstance(self.target_ids, tuple)
            or any(not isinstance(target, str) or not target for target in self.target_ids)
            or len(self.target_ids) != len(set(self.target_ids))
            or not isinstance(mutation.before, (list, tuple)) or entry not in mutation.before
            or not isinstance(mutation.after, (list, tuple)) or entry in mutation.after
        ):
            raise ValueError("queue terminal fact requires a QueueSystem removal")
        custom_tag = entry.get("custom_tag", "")
        queue_intent_id = entry.get("queue_intent_id", "")
        if not isinstance(custom_tag, str) or not isinstance(queue_intent_id, str):
            raise ValueError("queue terminal fact requires the entry intent and typed tag")
        object.__setattr__(self, "custom_tag", custom_tag)
        object.__setattr__(self, "queue_intent_id", queue_intent_id)

    @staticmethod
    def accepted_entry_target_ids(entry: dict[str, JSONValue]) -> tuple[str, ...] | None:
        """Read the accepted queue input, including automatic manual-action targets."""
        targets = entry.get("target_ids", ())
        resolution = entry.get("target_resolution")
        if isinstance(resolution, dict) and "selected_target_ids" in resolution:
            if (resolution.get("ok") is not True
                    or resolution.get("actor_id") != entry.get("actor_id")
                    or resolution.get("submitted_target_ids") != targets):
                return None
            targets = resolution["selected_target_ids"]
        if (not isinstance(targets, (list, tuple))
                or any(not isinstance(target, str) or not target for target in targets)
                or len(targets) != len(set(targets))):
            return None
        return tuple(targets)

    def matches(self, state: BattleState, event: GameEvent) -> bool:
        return self.matches_dispatch(state, event)

    def matches_dispatch(self, state: BattleState, event: GameEvent) -> bool:
        entry = self.source_mutation.metadata["queue_entry"]
        return (
            event.event_type == self.event_type and event.event_id == self.event_id
            and event.source_id == self.actor_id and state.event_index == self.event_index
            and self.actor_id in state.units
            and all(target_id in state.units for target_id in self.target_ids)
            and entry not in state.queues.get(self.source_mutation.path[1], ())
        )


@dataclass(frozen=True)
class QueueActionStartFact:
    """Accepted primary selections immediately before one dequeued body starts."""

    source_mutation: Mutation = field(repr=False)
    event_id: str
    event_index: int
    actor_id: str
    target_ids: tuple[str, ...]
    _state: BattleState = field(repr=False, compare=False)
    _producer_token: object = field(repr=False, compare=False)
    accepted_command: ActionCommand | None = field(default=None, repr=False)
    queue_kind: str = field(init=False)
    window_family: str = field(init=False)
    custom_tag: str = field(init=False)
    queue_intent_id: str = field(init=False)

    def __post_init__(self) -> None:
        mutation = self.source_mutation
        if (self._producer_token is not _QUEUE_ACTION_START_PRODUCER
                or type(self._state) is not BattleState or type(mutation) is not Mutation):
            raise ValueError("queue start fact requires its QueueSystem producer")
        entry = mutation.metadata.get("queue_entry")
        command = self.accepted_command
        if (
            mutation.source != "queue_system" or mutation.op != "set"
            or len(mutation.path) != 2 or mutation.path[0] != "queues"
            or not isinstance(entry, dict) or entry.get("queue_name") != mutation.path[1]
            or entry.get("actor_id") != self.actor_id
            or not isinstance(self.actor_id, str) or not self.actor_id
            or not isinstance(self.event_id, str) or not self.event_id
            or self.event_index != self._state.event_index
            or not isinstance(self.target_ids, tuple)
            or any(not isinstance(target, str) or not target for target in self.target_ids)
            or len(self.target_ids) != len(set(self.target_ids))
            or not isinstance(mutation.before, (list, tuple)) or entry not in mutation.before
            or not isinstance(mutation.after, (list, tuple)) or entry in mutation.after
            or entry in self._state.queues.get(mutation.path[1], ())
            or self.actor_id not in self._state.units
            or any(target not in self._state.units for target in self.target_ids)
            or (command is not None and (type(command) is not ActionCommand
                or command.source != "queue" or command.actor_id != self.actor_id))
            or (command is None and self.target_ids != QueueActionTerminalFact.accepted_entry_target_ids(entry))
            or not isinstance(entry.get("queue_kind"), str) or not entry["queue_kind"]
            or not isinstance(entry.get("window_family"), str) or not entry["window_family"]
        ):
            raise ValueError("queue start fact requires a removed entry and accepted selections")
        custom_tag = entry.get("custom_tag", "")
        queue_intent_id = entry.get("queue_intent_id", "")
        if not isinstance(custom_tag, str) or not isinstance(queue_intent_id, str):
            raise ValueError("queue start fact requires the entry intent and typed tag")
        object.__setattr__(self, "queue_kind", entry["queue_kind"])
        object.__setattr__(self, "window_family", entry["window_family"])
        object.__setattr__(self, "custom_tag", custom_tag)
        object.__setattr__(self, "queue_intent_id", queue_intent_id)

    def matches(self, state: BattleState, event: GameEvent) -> bool:
        return state is self._state and self.matches_dispatch(state, event)

    def matches_dispatch(self, state: BattleState, event: GameEvent) -> bool:
        """Validate the typed fact across one atomic listener dispatch.

        Earlier listeners of the same dispatch may have applied their own
        mutations, so the consuming state need not be the producing object.
        Identity comes from the event binding, the event index and the removed
        queue entry; a replayed or foreign fact still fails here.
        """

        return (
            state.event_index == self.event_index
            and event.event_type == "queue.action.before" and event.event_id == self.event_id
            and event.source_id == self.actor_id and event.target_id is None and event.window == "queue"
            and self.actor_id in state.units
            and all(target in state.units for target in self.target_ids)
            and self.source_mutation.metadata["queue_entry"] not in state.queues.get(self.source_mutation.path[1], ())
        )


@dataclass(frozen=True)
class BreakNotificationFact:
    """One ordinary break notification, owned by its committed source mutation."""

    source_mutation: Mutation = field(repr=False)
    event_id: str
    event_index: int
    target_id: str
    _producer_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._producer_token is not _BREAK_NOTIFICATION_PRODUCER:
            raise ValueError("break notification fact requires BreakSystem producer")
        if (
            self.source_mutation.source != "break_system"
            or self.source_mutation.path != ("units", self.target_id, "flags", "break_source")
            or self.source_mutation.op != "set"
            or not isinstance(self.source_mutation.after, dict)
            or not self.event_id
        ):
            raise ValueError("break notification fact requires a break source mutation")

    def matches(self, state: BattleState, target_id: str) -> bool:
        target = state.units.get(target_id)
        return (
            target_id == self.target_id
            and state.event_index == self.event_index
            and target is not None
            and target.toughness <= 0
            and target.flags.get("broken") is True
            and target.flags.get("break_source") == self.source_mutation.after
        )


@dataclass(frozen=True)
class StanceCountDownFact:
    """One committed intermediate toughness-layer depletion."""

    source_mutation: Mutation = field(repr=False)
    event_id: str
    event_index: int
    target_id: str
    attacker_id: str
    element_type: str
    template_id: str
    _state: BattleState = field(repr=False, compare=False)
    _producer_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        mutation = self.source_mutation
        if (self._producer_token is not _STANCE_COUNT_DOWN_PRODUCER
                or type(mutation) is not Mutation or type(self._state) is not BattleState):
            raise ValueError("stance count down fact requires its BreakSystem producer")
        target = self._state.units.get(self.target_id)
        if (
            not all(isinstance(value, str) and value for value in
                    (self.event_id, self.target_id, self.attacker_id, self.template_id))
            or self.element_type not in {"Physical", "Fire", "Ice", "Thunder", "Wind", "Quantum", "Imaginary"}
            or self.event_index != self._state.event_index
            or mutation.source != "break_system" or mutation.op != "set"
            or mutation.path != ("units", self.target_id, "flags", "stance_segments_remaining")
            or type(mutation.before) is not int or mutation.before <= 1
            or type(mutation.after) is not int or mutation.after != mutation.before - 1
            or mutation.after < 1
            or target is None or self.attacker_id not in self._state.units
            or target.flags.get("stance_segments_remaining") != mutation.after
            or mutation.metadata.get("attacker_id") != self.attacker_id
            or mutation.metadata.get("target_id") != self.target_id
            or mutation.metadata.get("element_type") != self.element_type
            or mutation.metadata.get("break_template_id") != self.template_id
        ):
            raise ValueError("stance count down fact requires its committed layer decrement")

    def matches(self, state: BattleState, event: GameEvent) -> bool:
        target = state.units.get(self.target_id)
        return (
            state.event_index == self.event_index
            and event.event_type == "toughness.segment_depleted" and event.event_id == self.event_id
            and event.source_id == self.attacker_id and event.target_id == self.target_id
            and event.window == "toughness_segment"
            and self.attacker_id in state.units and target is not None
            and type(target.flags.get("stance_segments_remaining")) is int
            and target.flags["stance_segments_remaining"] == self.source_mutation.after
        )


@dataclass(frozen=True)
class StatusImmunityFact:
    """One rejected debuff and the exact installed protection that rejected it."""

    effect_id: str
    target_id: str
    caster_id: str
    incoming_modifier_name: str
    incoming_behavior_flags: tuple[str, ...]
    protection_instance_id: str
    protection_modifier_name: str
    event_id: str
    _state: BattleState = field(repr=False, compare=False)
    _producer_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._producer_token is not _STATUS_IMMUNITY_PRODUCER:
            raise ValueError("status immunity fact requires StatusSystem producer")
        if type(self._state) is not BattleState or any(not isinstance(value, str) or not value for value in (
            self.effect_id, self.target_id, self.caster_id, self.incoming_modifier_name,
            self.protection_instance_id, self.protection_modifier_name, self.event_id,
        )):
            raise ValueError("status immunity fact requires its state and complete identities")
        if not isinstance(self.incoming_behavior_flags, tuple) or any(
            not isinstance(value, str) or not value for value in self.incoming_behavior_flags
        ):
            raise TypeError("status immunity behavior flags must be a tuple of non-empty strings")

    def matches(self, state: BattleState, event: GameEvent) -> bool:
        if (state is not self._state or event.event_type != "status.immunity"
                or event.source_id != self.caster_id or event.target_id != self.target_id
                or event.event_id != self.event_id):
            return False
        target = state.units.get(self.target_id)
        details = target.flags.get("status_details") if target is not None else None
        if not isinstance(details, (list, tuple)):
            return False
        matches = [detail for detail in details if isinstance(detail, Mapping)
                   and detail.get("instance_id") == self.protection_instance_id]
        return (len(matches) == 1 and matches[0].get("owner_id") == self.target_id
                and matches[0].get("modifier_name") == self.protection_modifier_name
                and matches[0].get("lifecycle_state") == "active"
                and isinstance(matches[0].get("status_id"), str)
                and bool(matches[0]["status_id"]) and matches[0]["status_id"] in target.statuses)


_STATUS_LIFECYCLE_PRODUCER = object()


@dataclass(frozen=True)
class StatusLifecycleFact:
    """One produced status.lifecycle notification and its exact live instance.

    The identity fields above are authoritative; ordinary event payload fields
    are only a transport copy and must never be used to select the instance.
    """

    operation: str
    callback_event: str
    target_id: str
    owner_id: str
    modifier_name: str
    status_id: str
    status_instance_id: str
    caster_id: str
    event_id: str
    behavior_flags: tuple[str, ...]
    status_type: str
    status_category: str
    stack_change: dict[str, JSONValue]
    instance_detail: dict[str, JSONValue]
    _producer_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._producer_token is not _STATUS_LIFECYCLE_PRODUCER:
            raise ValueError("status lifecycle fact requires StatusSystem producer")
        if (
            any(
                not isinstance(value, str) or not value
                for value in (
                    self.operation,
                    self.callback_event,
                    self.target_id,
                    self.owner_id,
                    self.modifier_name,
                    self.status_id,
                    self.status_instance_id,
                    self.event_id,
                    self.status_type,
                )
            )
            or not isinstance(self.caster_id, str)
            or not isinstance(self.status_category, str)
        ):
            raise ValueError("status lifecycle fact requires complete identities")
        if any(not isinstance(flag, str) or not flag for flag in self.behavior_flags):
            raise ValueError("status lifecycle fact behavior flags are invalid")
        object.__setattr__(self, "behavior_flags", tuple(self.behavior_flags))
        detail = freeze_json(dict(self.instance_detail))
        stack_change = freeze_json(dict(self.stack_change))
        if not isinstance(detail, dict) or not isinstance(stack_change, dict):
            raise TypeError("status lifecycle fact detail must be an object")
        if (
            detail.get("instance_id") != self.status_instance_id
            or detail.get("owner_id") != self.owner_id
            or detail.get("modifier_name") != self.modifier_name
            or detail.get("status_id") != self.status_id
        ):
            raise ValueError("status lifecycle fact detail identity mismatch")
        object.__setattr__(self, "instance_detail", detail)
        object.__setattr__(self, "stack_change", stack_change)

    def matches_state(self, state: BattleState) -> bool:
        unit = state.units.get(self.owner_id)
        details = unit.flags.get("status_details") if unit is not None else None
        if not isinstance(details, (list, tuple)):
            return False
        matches = [
            detail
            for detail in details
            if isinstance(detail, Mapping)
            and detail.get("instance_id") == self.status_instance_id
        ]
        if len(matches) != 1:
            return False
        detail = matches[0]
        return (
            detail.get("owner_id") == self.owner_id
            and detail.get("modifier_name") == self.modifier_name
            and detail.get("status_id") == self.status_id
            and detail.get("caster_id") == self.caster_id
            and tuple(detail.get("behavior_flags") or ()) == self.behavior_flags
            and detail.get("status_type") == self.status_type
            and detail.get("status_category") == self.status_category
            and detail.get("lifecycle_state") == "active"
            and self.status_id in unit.statuses
        )

    def matches_event(self, event: GameEvent) -> bool:
        """Return whether the event is the produced notification itself.

        This is the immutable event/fact identity contract. It deliberately
        does not consult the live battle state; a status that a synchronous
        listener removed later in the same dispatch chain still produced this
        notification, and the dispatcher marks that case explicitly.
        """

        return (
            event.event_type == "status.lifecycle"
            and event.event_id == self.event_id
            and event.window == self.callback_event
            and event.target_id == self.target_id
            and isinstance(event.payload, dict)
            and event.payload.get("callback_event") == self.callback_event
            and event.payload.get("status_instance_id") == self.status_instance_id
            and event.payload.get("owner_id") == self.owner_id
            and event.payload.get("modifier_name") == self.modifier_name
            and event.payload.get("status_id") == self.status_id
            and event.payload.get("caster_id") == self.caster_id
            and event.payload.get("param_entity_2_id") == self.caster_id
            and event.payload.get("lifecycle_operation") == self.operation
            and event.payload.get("behavior_flags") == list(self.behavior_flags)
            and event.payload.get("status_type") == self.status_type
            and event.payload.get("status_category") == self.status_category
            and all(
                event.payload.get(key) == value
                for key, value in self.stack_change.items()
            )
        )

    def matches(self, state: BattleState, event: GameEvent) -> bool:
        return self.matches_event(event) and self.matches_state(state)


@dataclass(frozen=True)
class GameEvent:
    event_type: str
    source_id: str | None = None
    target_id: str | None = None
    event_id: str = ""
    window: str = "unspecified"
    process_only: bool = True
    payload: dict[str, JSONValue] = field(default_factory=dict)
    # The executing action supplies this to synchronous child callbacks. It is
    # transient context, never reconstructed from exported event payloads.
    action_definition: ActionDefinitionIR | None = field(default=None, repr=False, compare=False)
    admitted_action_target_fact: AdmittedActionTargetFact | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    expected_action_window_scope: ActionWindowExpectedScope | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    shield_exhaustion_fact: ShieldExhaustionFact | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    break_notification_fact: BreakNotificationFact | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    queue_action_terminal_fact: QueueActionTerminalFact | None = field(
        default=None, repr=False, compare=False,
    )
    status_lifecycle_plan: StatusLifecyclePlan | None = field(
        default=None, repr=False, compare=False,
    )
    status_lifecycle_fact: StatusLifecycleFact | None = field(
        default=None, repr=False, compare=False,
    )
    # Set by the dispatcher only when a listener removed this event's status
    # instance earlier in the same synchronous dispatch chain. The produced
    # fact stays authoritative; the mark lets the remaining lifecycle
    # notifications fire as the game queues them instead of treating the
    # already-removed instance as a forged event.
    lifecycle_instance_gone: bool = field(default=False, repr=False, compare=False)
    status_immunity_fact: StatusImmunityFact | None = field(
        default=None, repr=False, compare=False,
    )
    queue_action_start_fact: QueueActionStartFact | None = field(
        default=None, repr=False, compare=False,
    )
    stance_count_down_fact: StanceCountDownFact | None = field(
        default=None, repr=False, compare=False,
    )
    pending_defeat_plan: PendingDefeatPlan | None = field(
        default=None, repr=False, compare=False,
    )
    heal_event_fact: HealEventFact | None = field(
        default=None, repr=False, compare=False,
    )
    hp_change_event_fact: HPChangeEventFact | None = field(
        default=None, repr=False, compare=False,
    )
    dynamic_value_change_fact: DynamicValueChangeFact | None = field(
        default=None, repr=False, compare=False,
    )
    ability_property_change_fact: AbilityPropertyChangeFact | None = field(
        default=None, repr=False, compare=False,
    )
    hit_window_invocation_fact: HitWindowInvocationFact | None = field(
        default=None, repr=False, compare=False,
    )
    energy_change_event_fact: EnergyChangeEventFact | None = field(
        default=None, repr=False, compare=False,
    )
    hp_overflow_fact: HPOverflowFact | None = field(
        default=None, repr=False, compare=False,
    )

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

    def __post_init__(self) -> None:
        if type(self) is not TargetResolution:
            raise TypeError("target resolution must not be subclassed")
        for name in (
            "requested",
            "selectable",
            "legal",
            "impact_group",
            "selected",
            "rejected",
        ):
            raw = getattr(self, name)
            if isinstance(raw, str):
                raise TypeError(f"target resolution {name} must be a tuple")
            values = tuple(raw)
            if any(not isinstance(item, str) or not item for item in values):
                raise ValueError(f"target resolution {name} contains an invalid identity")
            if len(values) != len(set(values)):
                raise ValueError(f"target resolution {name} contains duplicate identities")
            object.__setattr__(self, name, values)
        if self.primary is not None and (
            not isinstance(self.primary, str) or not self.primary
        ):
            raise ValueError("target resolution primary identity is invalid")
        if not isinstance(self.reason, str) or not isinstance(self.source, str):
            raise TypeError("target resolution reason and source must be strings")
        metadata = freeze_json(self.metadata)
        if not isinstance(metadata, dict):
            raise TypeError("target resolution metadata must be an object")
        object.__setattr__(self, "metadata", metadata)

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


_STATUS_HP_CLAMP_PRODUCER = object()


@dataclass(frozen=True)
class StatusHPClampFact:
    """Immutable producer inputs for auditing a status-derived HP clamp.

    This fact is local to native execution, like lifecycle event facts. It is
    not reconstructed from settlement copies or serialized mutation metadata.
    """

    before_unit: UnitState
    after_unit: UnitState
    metadata: dict[str, JSONValue]
    _producer_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._producer_token is not _STATUS_HP_CLAMP_PRODUCER:
            raise ValueError("HP clamp fact requires StatusSystem producer")
        if (type(self.before_unit) is not UnitState or type(self.after_unit) is not UnitState
                or self.before_unit.unit_id != self.after_unit.unit_id):
            raise ValueError("HP clamp fact requires one exact unit")
        metadata = freeze_json(self.metadata)
        if not isinstance(metadata, dict):
            raise TypeError("HP clamp fact metadata must be an object")
        object.__setattr__(self, "metadata", metadata)


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
    status_hp_clamp_fact: StatusHPClampFact | None = field(default=None, repr=False, compare=False)
    unit_birth_fact: UnitBirthFact | None = field(default=None, repr=False, compare=False)
    battle_event_fact: BattleEventExecutionFact | BattleEventRetirementFact | None = field(default=None, repr=False, compare=False)
    effect_execution_fact: EffectExecutionFact | None = field(default=None, repr=False, compare=False)
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
        if self.status_hp_clamp_fact is not None and type(self.status_hp_clamp_fact) is not StatusHPClampFact:
            raise TypeError("mutation HP clamp fact must be produced by StatusSystem")
        if self.unit_birth_fact is not None:
            from ..systems.unit_spawn import UnitBirthFact

            if type(self.unit_birth_fact) is not UnitBirthFact:
                raise TypeError("mutation birth fact must be produced by UnitSpawnSystem")
        if self.battle_event_fact is not None:
            from ..systems.battle_event import BattleEventExecutionFact, BattleEventRetirementFact

            if type(self.battle_event_fact) not in {BattleEventExecutionFact, BattleEventRetirementFact}:
                raise TypeError("mutation event fact must be produced by BattleEventSystem")
        if self.effect_execution_fact is not None:
            from ..systems.effect import EffectExecutionFact

            if type(self.effect_execution_fact) is not EffectExecutionFact:
                raise TypeError("mutation effect fact must be produced by EffectRegistry")
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
                "before": before,
                "before_exists": self.before_exists,
                "after": after,
                "after_exists": self.after_exists,
                "reason": self.reason,
                "source": self.source,
                "metadata": metadata,
            },
        )
        object.__setattr__(self, "_stable_id_cache", stable_id)

    def stable_id(self) -> str:
        return self._stable_id_cache

    def to_json(self, *, detach: bool = True) -> dict[str, JSONValue]:
        return {
            "mutation_id": self.stable_id(),
            "op": self.op,
            "path": list(self.path),
            "before": thaw_json(self.before) if detach else self.before,
            "before_exists": self.before_exists,
            "after": thaw_json(self.after) if detach else self.after,
            "after_exists": self.after_exists,
            "reason": self.reason,
            "source": self.source,
            "metadata": thaw_json(self.metadata) if detach else self.metadata,
        }


@dataclass(frozen=True)
class PendingDefeatPlan:
    """Persisted lethal cause, produced from the actual HP mutation and source frame.

    This is lifecycle state, never reconstructed from a displayed event or audit log.
    ``source_frame`` and ``source_trace`` preserve provenance; only the explicit
    owner identity is used by the eventual kill-credit consumer.
    """

    unit_id: str
    event_index: int
    hp_mutation: Mutation
    kill_credit_owner_id: str
    source_frame: dict[str, JSONValue]
    source_trace: dict[str, JSONValue]
    terminal_event: GameEvent | None = None

    def __post_init__(self) -> None:
        hp = self.hp_mutation
        if (not isinstance(self.unit_id, str) or not self.unit_id
                or type(self.event_index) is not int or self.event_index < 0
                or not isinstance(self.kill_credit_owner_id, str) or not self.kill_credit_owner_id
                or type(hp) is not Mutation or hp.source != "damage_system" or hp.op != "set"
                or hp.path != ("units", self.unit_id, "hp")
                or not hp.before_exists or not hp.after_exists
                or type(hp.before) not in (int, float) or not math.isfinite(hp.before) or hp.before <= 0
                or type(hp.after) not in (int, float) or hp.after != 0):
            raise ValueError("pending_defeat_requires_a_native_lethal_hp_mutation")
        for key in ("source_frame", "source_trace"):
            value = freeze_json(getattr(self, key))
            if not isinstance(value, dict) or not value:
                raise ValueError("pending_defeat_source_missing:" + key)
            object.__setattr__(self, key, value)
        if self.source_frame.get("owner_id") != self.kill_credit_owner_id:
            raise ValueError("pending_defeat_source_owner_mismatch")
        if (hp.metadata.get("source_frame") != self.source_frame
                or hp.metadata.get("source_trace") != self.source_trace):
            raise ValueError("pending_defeat_native_source_mismatch")
        if self.terminal_event is not None:
            event = self.terminal_event
            if (type(event) is not GameEvent or event.event_type != "unit.defeated"
                    or event.source_id != self.kill_credit_owner_id or event.target_id != self.unit_id
                    or event.window != "unit.defeated"
                    or event.payload.get("target_id") != self.unit_id
                    or event.payload.get("defeated_unit_id") != self.unit_id
                    or event.payload.get("kill_credit_owner_id") != self.kill_credit_owner_id
                    or event.payload.get("source_frame") != self.source_frame
                    or event.payload.get("source_trace") != self.source_trace
                    or event.payload.get("target_before_hp") != hp.before
                    or event.payload.get("target_after_hp") != hp.after):
                raise ValueError("pending_defeat_terminal_event_mismatch")
            # Retain the producer's complete context, including skill/hit identity.
            # A later finalizer must not rebuild it from a displayed event or log.
            object.__setattr__(self, "terminal_event", replace(event,
                event_id=str(event.to_json()["event_id"]), payload=freeze_json(event.payload)))

    @property
    def pending_id(self) -> str:
        return f"pending_defeat:{self.event_index}:{self.hp_mutation.stable_id()}"

    def to_json(self) -> dict[str, JSONValue]:
        return {"unit_id": self.unit_id, "event_index": self.event_index,
                "hp_mutation": self.hp_mutation.to_json(),
                "kill_credit_owner_id": self.kill_credit_owner_id,
                "source_frame": thaw_json(self.source_frame), "source_trace": thaw_json(self.source_trace),
                "terminal_event": self.terminal_event.to_json() if self.terminal_event is not None else None}

    @classmethod
    def from_json(cls, value: object) -> PendingDefeatPlan:
        cached = getattr(value, "_pending_defeat_plan_cache", None) if type(value) is FrozenJSONDict else None
        if cached is not None:
            return cached
        # The decoder only reads its input. Keep frozen evidence shared instead
        # of thawing and refreezing the same cause at every limbo window.
        raw = value
        fields = {"unit_id", "event_index", "hp_mutation", "kill_credit_owner_id", "source_frame", "source_trace", "terminal_event"}
        if not isinstance(raw, dict) or set(raw) != fields or not isinstance(raw["hp_mutation"], dict):
            raise ValueError("pending_defeat_payload_invalid")
        hp = dict(raw["hp_mutation"])
        claimed_id = hp.pop("mutation_id", None)
        try:
            mutation = Mutation(**hp)
            if mutation.stable_id() != claimed_id:
                raise ValueError("pending_defeat_hp_identity_mismatch")
            plan = cls(raw["unit_id"], raw["event_index"], mutation, raw["kill_credit_owner_id"],
                       raw["source_frame"], raw["source_trace"],
                       GameEvent(**raw["terminal_event"]) if raw["terminal_event"] is not None else None)
            if type(value) is FrozenJSONDict:
                value._pending_defeat_plan_cache = plan
            return plan
        except (TypeError, KeyError) as exc:
            raise ValueError("pending_defeat_payload_invalid") from exc


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

    def to_json(self, *, detach: bool = True) -> dict[str, JSONValue]:
        return {
            "before": self.transaction.before.to_json(detach=detach),
            "after": self.after.to_json(detach=detach),
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
            "mutations": [mutation.to_json(detach=detach) for mutation in self.transaction.mutations],
            "trigger_windows": list(self.transaction.trigger_windows),
            "settlement": self.transaction.settlement.to_json()
            if self.transaction.settlement
            else None,
            "coverage": self.coverage,
            "contract_validation": self.contract_validation,
        }


def _stable_id(prefix: str, payload: dict[str, JSONValue]) -> str:
    if prefix == "mutation":
        return f"{prefix}:{json_tree_digest(payload).hex()[:16]}"
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _is_frozen_json_value(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int, str)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return type(value) in (FrozenJSONDict, FrozenJSONList)
