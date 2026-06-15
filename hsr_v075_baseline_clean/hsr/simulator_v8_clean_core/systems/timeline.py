from __future__ import annotations

from ..core.model import BattleState, Mutation


class TimelineSystem:
    def set_action_value(self, state: BattleState, unit_id: str, action_value: float, source: str) -> Mutation:
        unit = state.units[unit_id]
        return Mutation(
            op="set",
            path=("units", unit_id, "action_value"),
            before=unit.action_value,
            after=max(0.0, action_value),
            reason="set action value",
            source=source,
        )

    def advance_action_value(self, state: BattleState, unit_id: str, delta: float, source: str) -> Mutation:
        unit = state.units[unit_id]
        return self.set_action_value(state, unit_id, unit.action_value + delta, source)

