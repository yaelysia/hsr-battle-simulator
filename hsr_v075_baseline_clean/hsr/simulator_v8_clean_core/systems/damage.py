from __future__ import annotations

from dataclasses import dataclass

from ..core.model import BattleState, Mutation


@dataclass(frozen=True)
class DamagePacket:
    attacker_id: str
    target_id: str
    amount: float
    family: str = "direct"
    element: str | None = None


class DamageSystem:
    def apply_packet(self, state: BattleState, packet: DamagePacket) -> Mutation:
        target = state.units[packet.target_id]
        after = max(0.0, target.hp - packet.amount)
        return Mutation(
            op="set",
            path=("units", packet.target_id, "hp"),
            before=target.hp,
            after=after,
            reason="apply damage packet",
            source="damage_system",
            metadata={
                "attacker_id": packet.attacker_id,
                "amount": packet.amount,
                "family": packet.family,
                "element": packet.element,
            },
        )

