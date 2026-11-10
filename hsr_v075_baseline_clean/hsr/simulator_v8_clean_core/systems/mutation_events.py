from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace

from ..core.model import GameEvent, JSONValue, Mutation
from ..core.unit_state_codec import unit_state_from_payload
from ..resource_event_contract import (
    TEAM_SKILL_POINT_EVENT_CONTRACT,
    UNIT_ENERGY_EVENT_CONTRACT,
    resource_event_contract_for_path,
    resource_production_event_types,
)
from ..unit_eligibility import runtime_unit_is_battle_event_entity
from ..unit_presence import departure_source_count


MUTATION_BACKED_EVENT_TYPES = frozenset({
    "hp.change",
    "energy.change",
    "heal.after",
    "heal.snapshot.created",
    "shield.change",
    "shield.exhausted",
    "toughness.before_hit",
    "action_delay.changed",
    "unit.created",
    "battle_event.created",
    "unit.removed",
    "unit.departed.started",
    "unit.departed.ended",
    "unit.base_type.changed",
    "weakness.stacked",
    "elation.time.started",
    "elation.time.ended",
    "elation.points.changed",
}) | resource_production_event_types()

PRE_MUTATION_BLOCK_REASON = "pre_mutation_listener_recompute_not_admitted"

_HP_CHANGE_EVENT_FACT_PRODUCER = object()


@dataclass(frozen=True)
class HPChangeEventFact:
    """One issued HP mutation and its exact event; no payload supplies the value."""
    source_mutation: Mutation = field(repr=False)
    event_id: str
    event_source_id: str
    target_id: str
    _producer_token: object = field(repr=False, compare=False)
    _issued_mutation: Mutation = field(repr=False, compare=False)
    _issued_identity: tuple[str, str, str] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        mutation = self.source_mutation
        if self._producer_token is not _HP_CHANGE_EVENT_FACT_PRODUCER or mutation is not self._issued_mutation:
            raise ValueError("HP change fact requires the issued immutable mutation")
        if self._issued_identity != (self.event_id, self.event_source_id, self.target_id):
            raise ValueError("HP change fact event identity was replaced")
        if (type(mutation) is not Mutation or mutation.op != "set"
                or mutation.path != ("units", self.target_id, "hp")
                or not all(isinstance(value, str) and value for value in self._issued_identity)
                or type(mutation.before) not in (int, float) or type(mutation.after) not in (int, float)
                or not math.isfinite(mutation.before) or not math.isfinite(mutation.after)
                or mutation.before == mutation.after):
            raise ValueError("HP change fact requires a finite committed HP change")

    @property
    def delta(self) -> float:
        return float(self.source_mutation.after) - float(self.source_mutation.before)

    def matches_event(self, event: GameEvent) -> bool:
        mutation = self.source_mutation
        payload = event.payload
        return bool(type(event) is GameEvent and event.hp_change_event_fact is self
            and event.event_type == "hp.change" and event.event_id == self.event_id
            and event.source_id == self.event_source_id and event.target_id == self.target_id
            and event.window == "OnHPChange" and event.process_only
            and isinstance(payload, dict) and payload.get("mutation_id") == mutation.stable_id()
            and payload.get("target_id") == self.target_id
            and payload.get("listener_scope") == "being_hit_target_local"
            and payload.get("callback_events") == ["OnHPChange", "OnListenHPChange"]
            and type(payload.get("hp_before")) in (int, float) and payload["hp_before"] == mutation.before
            and type(payload.get("hp_after")) in (int, float) and payload["hp_after"] == mutation.after
            and type(payload.get("hp_change_amount")) in (int, float) and payload["hp_change_amount"] == self.delta)


_ENERGY_CHANGE_EVENT_FACT_PRODUCER = object()


@dataclass(frozen=True)
class EnergyChangeEventFact:
    """One issued energy mutation and its exact event; no payload supplies the value."""
    source_mutation: Mutation = field(repr=False)
    event_id: str
    event_source_id: str
    target_id: str
    _producer_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        mutation = self.source_mutation
        if (self._producer_token is not _ENERGY_CHANGE_EVENT_FACT_PRODUCER
                or type(mutation) is not Mutation or mutation.op != "set"
                or mutation.path != ("units", self.target_id, "energy")
                or type(mutation.before) not in (int, float) or type(mutation.after) not in (int, float)
                or not math.isfinite(mutation.before) or not math.isfinite(mutation.after)
                or mutation.before == mutation.after):
            raise ValueError("energy change fact requires a finite committed energy change")

    @property
    def delta(self) -> float:
        return float(self.source_mutation.after) - float(self.source_mutation.before)

    def matches_event(self, event: GameEvent) -> bool:
        payload = event.payload
        return bool(type(event) is GameEvent and event.energy_change_event_fact is self
            and event.event_type == "energy.change" and event.event_id == self.event_id
            and event.source_id == self.event_source_id and event.target_id == self.target_id
            and event.window == "OnSPChange" and event.process_only
            and isinstance(payload, dict) and payload.get("mutation_id") == self.source_mutation.stable_id()
            and payload.get("sp_change_amount") == self.delta)


_HP_OVERFLOW_FACT_PRODUCER = object()


@dataclass(frozen=True)
class HPOverflowFact:
    """Damage beyond an HP lock floor; produced only by the lock that rescued the unit."""
    rescue_mutation: Mutation = field(repr=False)
    overflow_amount: float
    event_id: str
    target_id: str
    pending_defeat_id: str
    _producer_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        mutation = self.rescue_mutation
        if (self._producer_token is not _HP_OVERFLOW_FACT_PRODUCER
                or type(mutation) is not Mutation or mutation.op != "set"
                or mutation.path != ("units", self.target_id, "hp")
                or type(self.overflow_amount) is not float
                or not math.isfinite(self.overflow_amount) or self.overflow_amount <= 0):
            raise ValueError("hp overflow fact requires a committed lock rescue and positive overflow")

    def matches_event(self, event: GameEvent) -> bool:
        return bool(type(event) is GameEvent and event.hp_overflow_fact is self
            and event.event_type == "unit.hp_overflow" and event.event_id == self.event_id
            and event.target_id == self.target_id and event.window == "OnHPOverflow")


def hp_overflow_event(
    rescue_mutation: Mutation, overflow_amount: float, *, target_id: str, source_id: str,
    pending_defeat_id: str, metadata: dict[str, JSONValue],
) -> GameEvent:
    event_id = mutation_backed_event_id(rescue_mutation.stable_id(), "unit.hp_overflow")
    fact = HPOverflowFact(rescue_mutation, float(overflow_amount), event_id, target_id,
                          pending_defeat_id, _HP_OVERFLOW_FACT_PRODUCER)
    return GameEvent(
        "unit.hp_overflow", source_id=source_id, target_id=target_id, event_id=event_id,
        window="OnHPOverflow", process_only=True,
        payload={**metadata, "callback_events": ["OnHPOverflow"], "listener_scope": "being_hit_target_local",
                 "overflow_amount": float(overflow_amount), "pending_defeat_id": pending_defeat_id,
                 "mutation_id": rescue_mutation.stable_id()},
        hp_overflow_fact=fact,
    )


def native_energy_change_value(event: GameEvent | None) -> tuple[float | None, str]:
    """Read the signed realized energy difference from the actual domain event."""
    fact = event.energy_change_event_fact if type(event) is GameEvent else None
    if type(fact) is not EnergyChangeEventFact or not fact.matches_event(event):
        return None, "energy_change_event_fact_missing_or_mismatched"
    return fact.delta, ""


def native_hp_change_value(event: GameEvent | None) -> tuple[float | None, str]:
    """Read a signed realized HP difference from the actual domain event."""
    if type(event) is not GameEvent:
        return None, "hp_change_native_event_missing"
    if event.event_type == "unit.hp_overflow":
        # 锁血溢出的变化值为被锁下限截掉的那部分伤害（负值）。
        fact = event.hp_overflow_fact
        if type(fact) is not HPOverflowFact or not fact.matches_event(event):
            return None, "hp_overflow_fact_missing_or_mismatched"
        return -fact.overflow_amount, ""
    if event.event_type == "hp.change":
        fact = event.hp_change_event_fact
        if type(fact) is not HPChangeEventFact or not fact.matches_event(event):
            return None, "hp_change_event_fact_missing_or_mismatched"
        return fact.delta, ""
    if event.event_type == "heal.after":
        fact = event.heal_event_fact
        if type(fact) is not HealEventFact or not fact.matches_heal_after(event):
            return None, "heal_event_fact_missing_or_mismatched"
        return float(fact.heal_amount), ""
    return None, "hp_change_event_kind_not_admitted"


_HEAL_EVENT_FACT_PRODUCER = object()
_HEAL_WINDOW = "OnAfterBeingHeal"
_HEAL_LISTENER_SCOPE = "being_hit_target_local"
_SNAPSHOT_WINDOW = "OnSnapshotCreate"
_SNAPSHOT_LISTENER_SCOPE = "actor_local"


def _heal_claim_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _heal_fact_claim_values(
    *,
    source_mutation: Mutation,
    healer_id: str,
    heal_target_id: str,
    heal_amount: float,
    event_index: int,
    heal_event_id: str,
    snapshot_event_id: str,
    event_source_id: str,
    window: str,
    listener_scope: str,
    snapshot_id: str,
) -> tuple[object, ...]:
    """Seal every issued business field of one heal event fact."""

    mutation = source_mutation
    return (
        healer_id,
        heal_target_id,
        float(heal_amount),
        int(event_index),
        heal_event_id,
        snapshot_event_id,
        event_source_id,
        window,
        listener_scope,
        snapshot_id,
        mutation.stable_id(),
        mutation.op,
        tuple(mutation.path),
        mutation.source,
        mutation.reason,
        _heal_claim_json(mutation.before),
        _heal_claim_json(mutation.after),
    )


def _new_heal_event_fact(
    *,
    source_mutation: Mutation,
    healer_id: str,
    heal_target_id: str,
    heal_amount: float,
    event_index: int,
    event_id_prefix: str,
    event_source_id: str,
) -> "HealEventFact":
    heal_event_id = f"{event_id_prefix}:heal_after"
    snapshot_event_id = f"{event_id_prefix}:heal_snapshot_created"
    snapshot_id = f"heal_snapshot:{source_mutation.stable_id()}"
    claims = _heal_fact_claim_values(
        source_mutation=source_mutation,
        healer_id=healer_id,
        heal_target_id=heal_target_id,
        heal_amount=heal_amount,
        event_index=event_index,
        heal_event_id=heal_event_id,
        snapshot_event_id=snapshot_event_id,
        event_source_id=event_source_id,
        window=_HEAL_WINDOW,
        listener_scope=_HEAL_LISTENER_SCOPE,
        snapshot_id=snapshot_id,
    )
    return HealEventFact(
        source_mutation=source_mutation,
        healer_id=healer_id,
        heal_target_id=heal_target_id,
        heal_amount=float(heal_amount),
        event_index=event_index,
        heal_event_id=heal_event_id,
        snapshot_event_id=snapshot_event_id,
        event_source_id=event_source_id,
        window=_HEAL_WINDOW,
        listener_scope=_HEAL_LISTENER_SCOPE,
        snapshot_id=snapshot_id,
        _producer_token=_HEAL_EVENT_FACT_PRODUCER,
        _claims=claims,
    )


@dataclass(frozen=True)
class HealEventFact:
    """One committed heal mutation bound to its complete produced event identity.

    The fact carries the issued event ids, source, top-level target, window,
    listener scope and all mutation business fields.  `_claims` seals those
    values: a copied fact whose mutation or amount was rewritten with
    `dataclasses.replace` keeps the old claims and is rejected.
    """

    source_mutation: Mutation = field(repr=False)
    healer_id: str
    heal_target_id: str
    heal_amount: float
    event_index: int
    heal_event_id: str
    snapshot_event_id: str
    event_source_id: str
    window: str
    listener_scope: str
    snapshot_id: str
    _producer_token: object = field(repr=False, compare=False)
    _claims: tuple[object, ...] = field(default=(), repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._producer_token is not _HEAL_EVENT_FACT_PRODUCER:
            raise ValueError("heal event fact requires the mutation event producer")
        mutation = self.source_mutation
        if type(mutation) is not Mutation:
            raise TypeError("heal event fact requires a committed mutation")
        if (
            not isinstance(self.healer_id, str)
            or not self.healer_id
            or not isinstance(self.heal_target_id, str)
            or not self.heal_target_id
            or not isinstance(self.snapshot_id, str)
            or not self.snapshot_id
            or not isinstance(self.heal_event_id, str)
            or not self.heal_event_id
            or not isinstance(self.snapshot_event_id, str)
            or not self.snapshot_event_id
            or not isinstance(self.event_source_id, str)
            or not self.event_source_id
            or self.window != _HEAL_WINDOW
            or self.listener_scope != _HEAL_LISTENER_SCOPE
            or type(self.event_index) is not int
            or self.event_index < 0
            or type(self.heal_amount) not in (int, float)
            or isinstance(self.heal_amount, bool)
            or not math.isfinite(float(self.heal_amount))
            or float(self.heal_amount) <= 0
        ):
            raise ValueError("heal event fact identity is incomplete")
        before = _numeric_value(mutation.before)
        after = _numeric_value(mutation.after)
        if (
            mutation.op != "set"
            or mutation.path != ("units", self.heal_target_id, "hp")
            or before is None
            or after is None
            or after - before <= 0
            or not math.isclose(after - before, float(self.heal_amount), rel_tol=0.0, abs_tol=1e-9)
        ):
            raise ValueError("heal event fact requires a committed heal mutation")
        if self._claims != self._claim_values():
            raise ValueError("heal event fact claims do not match its issued identity")

    def _claim_values(self) -> tuple[object, ...]:
        return _heal_fact_claim_values(
            source_mutation=self.source_mutation,
            healer_id=self.healer_id,
            heal_target_id=self.heal_target_id,
            heal_amount=self.heal_amount,
            event_index=self.event_index,
            heal_event_id=self.heal_event_id,
            snapshot_event_id=self.snapshot_event_id,
            event_source_id=self.event_source_id,
            window=self.window,
            listener_scope=self.listener_scope,
            snapshot_id=self.snapshot_id,
        )

    @property
    def mutation_id(self) -> str:
        return self.source_mutation.stable_id()

    def _heal_payload_matches(self, payload: dict[str, JSONValue]) -> bool:
        amount = _numeric_value(payload.get("heal_amount"))
        return (
            payload.get("mutation_id") == self.mutation_id
            and payload.get("actor_id") == self.healer_id
            and payload.get("target_id") == self.heal_target_id
            and amount is not None
            and math.isclose(amount, float(self.heal_amount), rel_tol=0.0, abs_tol=1e-9)
        )

    def matches_heal_payload(self, payload: object) -> bool:
        """Validate the consumer-facing payload copy against every issued field."""

        if not isinstance(payload, dict):
            return False
        callback_events = payload.get("callback_events")
        return (
            isinstance(callback_events, (list, tuple))
            and "OnAfterDealHeal" in callback_events
            and payload.get("event_id") == self.heal_event_id
            and payload.get("event_source_id") == self.event_source_id
            and payload.get("event_target_id") == self.heal_target_id
            and payload.get("event_window") == self.window
            and payload.get("listener_scope") == self.listener_scope
            and self._heal_payload_matches(payload)
        )

    def matches_heal_after(self, event: GameEvent) -> bool:
        return (
            event.event_type == "heal.after"
            and event.event_id == self.heal_event_id
            and event.source_id == self.event_source_id
            and event.target_id == self.heal_target_id
            and event.window == self.window
            and isinstance(event.payload, dict)
            and event.payload.get("listener_scope") == self.listener_scope
            and self._heal_payload_matches(event.payload)
        )

    def matches_snapshot(self, event: GameEvent) -> bool:
        payload = event.payload
        if not isinstance(payload, dict):
            return False
        lifetime = payload.get("snapshot_lifetime")
        return (
            event.event_type == "heal.snapshot.created"
            and event.event_id == self.snapshot_event_id
            and event.source_id == self.event_source_id
            and event.window == _SNAPSHOT_WINDOW
            and event.target_id == self.healer_id
            and payload.get("listener_scope") == _SNAPSHOT_LISTENER_SCOPE
            and payload.get("param_entity_id") == self.healer_id
            and payload.get("healer_id") == self.healer_id
            and payload.get("snapshot_id") == self.snapshot_id
            and isinstance(lifetime, dict)
            and lifetime.get("kind") == "source_mutation"
            and lifetime.get("mutation_id") == self.mutation_id
            and self._heal_payload_matches(payload)
        )


def _numeric_value(value: JSONValue) -> float | None:
    if type(value) in (int, float) and not isinstance(value, bool):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    return None


def mutation_backed_event_id(mutation_id: str, event_type: str) -> str:
    """Return the stable business identity for one mutation-backed event."""

    if not mutation_id or not event_type:
        return ""
    return f"event:mutation_backed:{mutation_id}:{event_type.replace('.', '_')}"


def events_for_mutation(
    mutation: Mutation,
    *,
    actor_id: str = "",
    source_id: str = "",
    event_index: int = 0,
    include_before: bool = True,
    extra_payload: dict[str, JSONValue] | None = None,
    include_heal_snapshot: bool = False,
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

    if len(path) == 2 and path[0] == "units" and mutation.op == "spawn":
        events = [
            GameEvent(
                event_type="unit.created",
                source_id=event_source_id,
                target_id=target_id,
                event_id=f"{event_id_prefix}:unit_created",
                window="OnListenCharacterCreate",
                process_only=True,
                payload={
                    **payload,
                    "callback_events": ["OnListenCharacterCreate"],
                    "listener_scope": "global_listener",
                    "unit_id": target_id,
                    "param_entity_id": target_id,
                },
            ),
        ]
        base_type = _spawned_unit_base_type(mutation.after)
        if base_type:
            events.append(
                _unit_base_type_changed_event(
                    mutation,
                    event_source_id=event_source_id,
                    event_id_prefix=event_id_prefix,
                    target_id=target_id,
                    before="",
                    after=base_type,
                    roster_operation="unit_spawn",
                    payload=payload,
                )
            )
        battle_event_unit = _spawned_battle_event_unit(mutation, target_id)
        if battle_event_unit is not None:
            events.append(
                GameEvent(
                    event_type="battle_event.created",
                    source_id=event_source_id,
                    target_id=target_id,
                    event_id=mutation_backed_event_id(
                        mutation.stable_id(),
                        "battle_event.created",
                    ),
                    window="OnListenBattleEventCreate",
                    process_only=True,
                    payload={
                        **payload,
                        "callback_events": ["OnListenBattleEventCreate"],
                        "listener_scope": "global_listener",
                        "unit_id": target_id,
                        "param_entity_id": target_id,
                        "battle_event_subtype": battle_event_unit.flags.get(
                            "battle_event_subtype"
                        ),
                        "battle_event_entity": True,
                    },
                )
            )
        return tuple(events)

    if _is_unit_removed_path(path, mutation):
        events = [
            GameEvent(
                event_type="unit.removed",
                source_id=event_source_id,
                target_id=target_id,
                event_id=f"{event_id_prefix}:unit_removed",
                window="OnListenCharacterEscape",
                process_only=True,
                payload={
                    **payload,
                    "callback_events": ["OnListenCharacterEscape"],
                    "listener_scope": "global_listener",
                    "unit_id": target_id,
                    "param_entity_id": target_id,
                },
            ),
        ]
        base_type = mutation.metadata.get("removed_unit_base_type")
        if isinstance(base_type, str) and base_type:
            events.append(
                _unit_base_type_changed_event(
                    mutation,
                    event_source_id=event_source_id,
                    event_id_prefix=event_id_prefix,
                    target_id=target_id,
                    before=base_type,
                    after="",
                    roster_operation="unit_remove",
                    payload=payload,
                )
            )
        return tuple(events)

    if _is_unit_base_type_path(path) and mutation.before != mutation.after:
        return (
            _unit_base_type_changed_event(
                mutation,
                event_source_id=event_source_id,
                event_id_prefix=event_id_prefix,
                target_id=target_id,
                before=mutation.before,
                after=mutation.after,
                roster_operation="unit_base_type_change",
                payload=payload,
            ),
        )

    departure_event_type = _unit_departure_event_type(path, mutation)
    if departure_event_type:
        callback_event = (
            "OnListenDepartedStart"
            if departure_event_type == "unit.departed.started"
            else "OnListenDepartedEnd"
        )
        return (
            GameEvent(
                event_type=departure_event_type,
                source_id=event_source_id,
                target_id=target_id,
                event_id=mutation_backed_event_id(
                    mutation.stable_id(),
                    departure_event_type,
                ),
                window=callback_event,
                process_only=True,
                payload={
                    **payload,
                    "callback_events": [callback_event],
                    "listener_scope": "global_listener",
                    "unit_id": target_id,
                    "param_entity_id": target_id,
                },
            ),
        )

    added_weaknesses = _added_weaknesses(path, mutation)
    if added_weaknesses:
        return (
            GameEvent(
                event_type="weakness.stacked",
                source_id=event_source_id,
                target_id=target_id,
                event_id=f"{event_id_prefix}:weakness_stacked",
                window="OnStackWeakness",
                process_only=True,
                payload={
                    **payload,
                    "callback_events": ["OnStackWeakness"],
                    "listener_scope": "owner_local",
                    "unit_id": target_id,
                    "param_entity_id": target_id,
                    "added_weaknesses": list(added_weaknesses),
                },
            ),
        )

    if path == ("global_flags", "elation_runtime"):
        from .elation import elation_points_event_for_mutation

        return elation_points_event_for_mutation(mutation, actor_id=actor_id, source_id=source_id)

    elation_event_type = _elation_time_event_type(path, mutation)
    if elation_event_type:
        callback_event = (
            "OnListenElationTimeStart"
            if elation_event_type == "elation.time.started"
            else "OnListenElationTimeEnd"
        )
        return (
            GameEvent(
                event_type=elation_event_type,
                source_id=event_source_id,
                event_id=f"{event_id_prefix}:{elation_event_type.replace('.', '_')}",
                window=callback_event,
                process_only=True,
                payload={
                    **payload,
                    "callback_events": [callback_event],
                    "listener_scope": "global_listener",
                },
            ),
        )

    if len(path) == 3 and path[0] == "units" and path[2] == "energy" and mutation.op == "set":
        delta = _numeric_delta(mutation.before, mutation.after)
        if delta is None or delta == 0:
            return ()
        event_id = f"{event_id_prefix}:energy_change"
        return (
            GameEvent(
                event_type="energy.change",
                energy_change_event_fact=EnergyChangeEventFact(
                    mutation, event_id, event_source_id, target_id,
                    _ENERGY_CHANGE_EVENT_FACT_PRODUCER,
                ),
                source_id=event_source_id,
                target_id=target_id,
                event_id=event_id,
                window="OnSPChange",
                process_only=True,
                payload={
                    **payload,
                    "sp_before": float(mutation.before),
                    "sp_after": float(mutation.after),
                    "sp_change_amount": delta,
                    "callback_events": ["OnSPChange"],
                    "listener_scope": "being_hit_target_local",
                },
            ),
        )
    if _is_unit_hp_path(path):
        delta = _numeric_delta(mutation.before, mutation.after)
        if delta is None or delta == 0:
            return ()
        if delta > 0 and _is_heal_mutation(mutation):
            callback_events = ["OnHPChange", "OnListenHPChange", "OnAfterBeingHeal", "OnAfterDealHeal"]
            if _heal_overflow_proved(mutation, delta):
                callback_events.append("OnHPOverflow")
            healer_id = str(payload.get("actor_id") or event_source_id or "")
            if not healer_id:
                # A heal without the committed healer identity has no producer
                # fact, so only the public heal event can be published.
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
            heal_fact = _new_heal_event_fact(
                source_mutation=mutation,
                healer_id=healer_id,
                heal_target_id=target_id,
                heal_amount=float(delta),
                event_index=event_index,
                event_id_prefix=event_id_prefix,
                event_source_id=event_source_id,
            )
            heal_event = GameEvent(
                event_type="heal.after",
                source_id=event_source_id,
                target_id=target_id,
                event_id=f"{event_id_prefix}:heal_after",
                window="OnAfterBeingHeal",
                process_only=True,
                heal_event_fact=heal_fact,
                payload={
                    **payload,
                    "callback_events": callback_events,
                    "listener_scope": "being_hit_target_local",
                    "heal_amount": delta,
                    "actual_delta": delta,
                    "overflow_amount": _heal_overflow_amount(mutation, delta),
                },
            )
            if not include_heal_snapshot:
                # The public heal event keeps its typed fact; the snapshot
                # protocol is only published when the rulebook declares it.
                return (heal_event,)
            snapshot_event = GameEvent(
                event_type="heal.snapshot.created",
                source_id=event_source_id,
                target_id=healer_id,
                event_id=f"{event_id_prefix}:heal_snapshot_created",
                window="OnSnapshotCreate",
                process_only=True,
                heal_event_fact=heal_fact,
                payload={
                    **payload,
                    "callback_events": ["OnSnapshotCreate"],
                    "listener_scope": "actor_local",
                    # The snapshot belongs to the healer whose committed heal
                    # mutation created it; other wearers are not observers.
                    "param_entity_id": healer_id,
                    "snapshot_kind": "heal_data",
                    "snapshot_id": heal_fact.snapshot_id,
                    "snapshot_lifetime": {
                        "kind": "source_mutation",
                        "mutation_id": mutation.stable_id(),
                    },
                    "healer_id": healer_id,
                    "heal_target_id": target_id,
                    "heal_amount": delta,
                },
            )
            return (heal_event, snapshot_event)
        hp_before = (
            float(mutation.before)
            if isinstance(mutation.before, (int, float))
            and not isinstance(mutation.before, bool)
            else None
        )
        hp_after = (
            float(mutation.after)
            if isinstance(mutation.after, (int, float))
            and not isinstance(mutation.after, bool)
            else None
        )
        hp_fact = HPChangeEventFact(mutation, f"{event_id_prefix}:hp_change", event_source_id, target_id,
            _HP_CHANGE_EVENT_FACT_PRODUCER, mutation,
            (f"{event_id_prefix}:hp_change", event_source_id, target_id))
        hp_change_facts = (
            {
                "hp_before": hp_before,
                "hp_after": hp_after,
                "hp_change_amount": hp_after - hp_before,
            }
            if hp_before is not None and hp_after is not None
            else {}
        )
        return (
            GameEvent(
                event_type="hp.change",
                hp_change_event_fact=hp_fact,
                source_id=event_source_id,
                target_id=target_id,
                event_id=f"{event_id_prefix}:hp_change",
                window="OnHPChange",
                process_only=True,
                payload={
                    **payload,
                    **hp_change_facts,
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

    resource_contract = resource_event_contract_for_path(path)
    if resource_contract is TEAM_SKILL_POINT_EVENT_CONTRACT:
        if payload.get("delta") in {None, 0, 0.0}:
            return ()
        bp_actor_id = actor_id or target_id
        return (
            GameEvent(
                event_type=resource_contract.after_event_type,
                source_id=event_source_id,
                target_id=bp_actor_id,
                event_id=f"{event_id_prefix}:bp_change",
                window=resource_contract.after_callback_events[0],
                process_only=True,
                payload={
                    **payload,
                    "callback_events": list(resource_contract.after_callback_events),
                    "listener_scope": resource_contract.scope_kind,
                    "resource": resource_contract.payload_resource,
                    "resource_event_contract_id": resource_contract.contract_id,
                    "target_id": bp_actor_id,
                    "param_entity_id": bp_actor_id,
                    "change_value": payload.get("delta"),
                },
            ),
        )

    if resource_contract is UNIT_ENERGY_EVENT_CONTRACT:
        if payload.get("delta") in {None, 0, 0.0}:
            return ()
        after_event = GameEvent(
            event_type=resource_contract.after_event_type,
            source_id=event_source_id,
            target_id=target_id,
            event_id=f"{event_id_prefix}:energy_change",
            window=resource_contract.after_callback_events[0],
            process_only=True,
            payload={
                **payload,
                "callback_events": list(resource_contract.after_callback_events),
                "listener_scope": resource_contract.scope_kind,
                "resource": resource_contract.payload_resource,
                "resource_event_contract_id": resource_contract.contract_id,
                "change_value": payload.get("delta"),
            },
        )
        if not include_before:
            return (after_event,)
        before_event = GameEvent(
            event_type=resource_contract.before_event_type,
            source_id=event_source_id,
            target_id=target_id,
            event_id=f"{event_id_prefix}:energy_before_change",
            window=resource_contract.before_callback_events[0],
            process_only=True,
            payload={
                **payload,
                "callback_events": list(resource_contract.before_callback_events),
                "listener_scope": resource_contract.scope_kind,
                "resource": resource_contract.payload_resource,
                "resource_event_contract_id": resource_contract.contract_id,
                "change_value": payload.get("delta"),
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


def _is_unit_removed_path(path: tuple[str, ...], mutation: Mutation) -> bool:
    if (
        len(path) != 3
        or path[0] != "units"
        or path[2] != "lifecycle_status"
    ):
        return False
    return str(mutation.after or "").lower() in {"removed", "escaped"}


def _is_unit_base_type_path(path: tuple[str, ...]) -> bool:
    return (
        len(path) == 4
        and path[0] == "units"
        and path[2] == "flags"
        and path[3] in {"avatar_base_type", "path", "base_type"}
    )


def _unit_departure_event_type(
    path: tuple[str, ...],
    mutation: Mutation,
) -> str:
    if (
        len(path) != 4
        or path[0] != "units"
        or path[2:] != ("flags", "departed_sources")
        or mutation.op != "set"
    ):
        return ""
    before_count = departure_source_count(mutation.before)
    after_count = departure_source_count(mutation.after)
    if before_count is None or after_count is None:
        return ""
    if before_count == 0 and after_count > 0:
        return "unit.departed.started"
    if before_count > 0 and after_count == 0:
        return "unit.departed.ended"
    return ""

def _spawned_unit_base_type(value: JSONValue) -> str:
    if not isinstance(value, dict):
        return ""
    flags = value.get("flags")
    if not isinstance(flags, dict):
        return ""
    for key in ("avatar_base_type", "path", "base_type"):
        base_type = flags.get(key)
        if isinstance(base_type, str) and base_type:
            return base_type
    return ""


def _spawned_battle_event_unit(
    mutation: Mutation,
    target_id: str,
):
    metadata = mutation.metadata
    if (
        metadata.get("lifecycle_operation") != "unit_spawn"
        or not isinstance(metadata.get("source_trace"), dict)
        or not metadata.get("source_trace")
    ):
        return None
    try:
        unit = unit_state_from_payload(mutation.after)
    except (TypeError, ValueError):
        return None
    if (
        unit.unit_id != target_id
        or not runtime_unit_is_battle_event_entity(unit)
    ):
        return None
    return unit


def _unit_base_type_changed_event(
    mutation: Mutation,
    *,
    event_source_id: str,
    event_id_prefix: str,
    target_id: str,
    before: JSONValue,
    after: JSONValue,
    roster_operation: str,
    payload: dict[str, JSONValue],
) -> GameEvent:
    return GameEvent(
        event_type="unit.base_type.changed",
        source_id=event_source_id,
        target_id=target_id,
        event_id=f"{event_id_prefix}:unit_base_type_changed:{roster_operation}",
        window="OnListenAvatarBaseTypeChange",
        process_only=True,
        payload={
            **payload,
            "callback_events": ["OnListenAvatarBaseTypeChange"],
            "listener_scope": "global_listener",
            "unit_id": target_id,
            "param_entity_id": target_id,
            "base_type_before": before,
            "base_type_after": after,
            "roster_operation": roster_operation,
            "source_mutation_id": mutation.stable_id(),
        },
    )


def _added_weaknesses(path: tuple[str, ...], mutation: Mutation) -> tuple[str, ...]:
    if len(path) != 4 or path[0] != "units" or path[2:] != ("flags", "weaknesses"):
        return ()
    before_values = mutation.before if isinstance(mutation.before, (list, tuple)) else ()
    after_values = mutation.after if isinstance(mutation.after, (list, tuple)) else ()
    before = {str(item) for item in before_values if isinstance(item, str) and item}
    after = {str(item) for item in after_values if isinstance(item, str) and item}
    return tuple(sorted(after.difference(before)))


def _elation_time_event_type(path: tuple[str, ...], mutation: Mutation) -> str:
    if len(path) != 2 or path[0] != "global_flags":
        return ""
    if path[1] != "elation_time_active":
        return ""
    metadata = mutation.metadata
    if (
        mutation.source != "battle_state_transition_system"
        or not isinstance(
            metadata.get("battle_state_transition_rule_id"), str
        )
        or not metadata.get("battle_state_transition_rule_id")
        or not isinstance(metadata.get("trigger_kind"), str)
        or not metadata.get("trigger_kind")
        or not isinstance(metadata.get("trigger_identity"), str)
        or not metadata.get("trigger_identity")
        or not isinstance(metadata.get("runtime_event_type"), str)
        or not isinstance(metadata.get("callback_event"), str)
        or not isinstance(metadata.get("source_trace"), dict)
    ):
        return ""
    before = bool(mutation.before) if mutation.before_exists else False
    after = bool(mutation.after) if mutation.after_exists else False
    if before == after:
        return ""
    event_type = "elation.time.started" if after else "elation.time.ended"
    callback_event = (
        "OnListenElationTimeStart"
        if after
        else "OnListenElationTimeEnd"
    )
    if (
        metadata.get("runtime_event_type") != event_type
        or metadata.get("callback_event") != callback_event
    ):
        return ""
    return event_type


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
    packet_identity = str(
        packet.get("toughness_emission_id")
        or packet.get("source_task_id")
        or packet.get("hit_profile_id")
        or ""
    )
    if not packet_identity:
        raise ValueError("toughness_before_calculation_packet_identity_missing")
    metadata = packet.get("metadata")
    execution_path = metadata.get("ability_task_execution_path") if isinstance(metadata, dict) else None
    if isinstance(execution_path, str) and execution_path:
        packet_identity = f"{packet_identity}:{execution_path}"
    return GameEvent(
        event_type="toughness.before_hit",
        source_id=actor_id,
        target_id=target_id,
        event_id=(
            f"event:{event_index}:toughness_before_calculation:"
            f"{actor_id}:{target_id}:{packet_identity}"
        ),
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
    resource_contract = resource_event_contract_for_path(path)
    if resource_contract is not None:
        return resource_contract.payload_resource
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
        mutation.metadata.get("opcode") == "SetActionDelay"
        and (mutation.source == "status_callback_system" and bool(mutation.metadata.get("action_delay_emission_id"))
             or mutation.source == "effect_system" and bool(mutation.metadata.get("effect_id")))
    )
