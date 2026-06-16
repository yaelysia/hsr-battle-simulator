from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..core.model import BattleState, GameEvent, JSONValue, Mutation
from ..core.settlement import SettlementRecord


DamageFormulaFamily = Literal[
    "direct",
    "dot",
    "break",
    "super_break",
    "true_damage",
    "hp_loss",
    "elation",
]


EXECUTABLE_DAMAGE_FAMILIES: frozenset[str] = frozenset({"direct", "true_damage", "hp_loss"})
BLOCKED_DAMAGE_FAMILIES: frozenset[str] = frozenset({"dot", "break", "super_break", "elation"})
FOLLOW_UP_ATTACK_TYPE = "follow_up"


@dataclass(frozen=True)
class DamagePacket:
    attacker_id: str
    target_id: str
    amount: float
    attack_type: str
    damage_formula_family: DamageFormulaFamily
    damage_kind: str = "hp_damage"
    element_type: str | None = None
    source_trace: dict[str, JSONValue] = field(default_factory=dict)
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.damage_formula_family == FOLLOW_UP_ATTACK_TYPE:
            raise ValueError("follow_up is an attack type, not a damage formula family")
        if self.amount < 0:
            raise ValueError("damage amount must be non-negative")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "attacker_id": self.attacker_id,
            "target_id": self.target_id,
            "amount": self.amount,
            "attack_type": self.attack_type,
            "damage_kind": self.damage_kind,
            "damage_formula_family": self.damage_formula_family,
            "element_type": self.element_type,
            "source_trace": self.source_trace,
            "metadata": self.metadata,
            "bypasses_normal_multipliers": self.damage_formula_family in {"true_damage", "hp_loss"},
        }


@dataclass(frozen=True)
class DamageApplicationResult:
    packet: DamagePacket
    ok: bool
    events: tuple[GameEvent, ...] = ()
    mutations: tuple[Mutation, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    errors: tuple[str, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "packet": self.packet.to_json(),
            "events": [event.to_json() for event in self.events],
            "mutations": [mutation.to_json() for mutation in self.mutations],
            "records": list(self.records),
            "errors": list(self.errors),
        }


class DamageSystem:
    def apply_packet(self, state: BattleState, packet: DamagePacket) -> DamageApplicationResult:
        if packet.damage_formula_family in EXECUTABLE_DAMAGE_FAMILIES:
            return self._apply_hp_delta(state, packet)
        if packet.damage_formula_family in BLOCKED_DAMAGE_FAMILIES:
            return self._blocked_family(packet)
        return DamageApplicationResult(
            packet=packet,
            ok=False,
            records=(
                SettlementRecord(
                    record_type="damage_error",
                    source="damage_system",
                    process_only=True,
                    payload={
                        "error": "unsupported_damage_formula_family",
                        "damage_formula_family": packet.damage_formula_family,
                    },
                    trace=packet.source_trace,
                ).to_json(),
            ),
            errors=(f"unsupported damage formula family {packet.damage_formula_family!r}",),
        )

    def _apply_hp_delta(self, state: BattleState, packet: DamagePacket) -> DamageApplicationResult:
        target = state.units[packet.target_id]
        after = max(0.0, target.hp - packet.amount)
        mutation = Mutation(
            op="set",
            path=("units", packet.target_id, "hp"),
            before=target.hp,
            after=after,
            reason="apply damage packet",
            source="damage_system",
            metadata=packet.to_json(),
        )
        record_type = "hp_loss" if packet.damage_formula_family == "hp_loss" else "damage"
        bypasses_normal_multipliers = packet.damage_formula_family in {"true_damage", "hp_loss"}
        return DamageApplicationResult(
            packet=packet,
            ok=True,
            mutations=(mutation,),
            records=(
                SettlementRecord(
                    record_type=record_type,
                    source="damage_system",
                    mutation_id=mutation.stable_id(),
                    process_only=False,
                    payload={
                        "amount": packet.amount,
                        "attack_type": packet.attack_type,
                        "damage_kind": packet.damage_kind,
                        "damage_formula_family": packet.damage_formula_family,
                        "element_type": packet.element_type,
                        "bypasses_normal_multipliers": bypasses_normal_multipliers,
                        "normal_multiplier_terms": [],
                        "target_before_hp": target.hp,
                        "target_after_hp": after,
                    },
                    trace=packet.source_trace,
                ).to_json(),
            ),
        )

    def _blocked_family(self, packet: DamagePacket) -> DamageApplicationResult:
        reason = (
            "Elation damage is a mainline 4.0 damage formula family, "
            "but its complete formula is not executable in v0_207"
            if packet.damage_formula_family == "elation"
            else f"{packet.damage_formula_family} damage family is not executable in v0_207"
        )
        return DamageApplicationResult(
            packet=packet,
            ok=False,
            records=(
                SettlementRecord(
                    record_type="damage_blocked",
                    source="damage_system",
                    process_only=True,
                    payload={
                        "damage_formula_family": packet.damage_formula_family,
                        "attack_type": packet.attack_type,
                        "reason": reason,
                    },
                    trace=packet.source_trace,
                ).to_json(),
            ),
            errors=(reason,),
        )
