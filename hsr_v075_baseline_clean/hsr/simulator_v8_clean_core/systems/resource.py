from __future__ import annotations

from ..core.model import BattleState, Mutation


class ResourceSystem:
    def set_skill_points(self, state: BattleState, value: int, source: str) -> Mutation:
        clamped = max(0, min(value, state.max_skill_points))
        return Mutation(
            op="set",
            path=("skill_points",),
            before=state.skill_points,
            after=clamped,
            reason="set team skill points",
            source=source,
        )

    def change_unit_hp(self, state: BattleState, unit_id: str, delta: float, source: str) -> Mutation:
        unit = state.units[unit_id]
        new_hp = max(0.0, min(unit.max_hp, unit.hp + delta))
        return Mutation(
            op="set",
            path=("units", unit_id, "hp"),
            before=unit.hp,
            after=new_hp,
            reason="change unit hp",
            source=source,
            metadata={"delta": delta},
        )

    def change_unit_energy(self, state: BattleState, unit_id: str, delta: float, source: str) -> Mutation:
        unit = state.units[unit_id]
        cap = unit.max_energy if unit.max_energy > 0 else unit.energy + delta
        new_energy = max(0.0, min(cap, unit.energy + delta))
        return Mutation(
            op="set",
            path=("units", unit_id, "energy"),
            before=unit.energy,
            after=new_energy,
            reason="change unit energy",
            source=source,
            metadata={"delta": delta},
        )

