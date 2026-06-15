from __future__ import annotations

from ..core.model import BattleState


class TargetSystem:
    def resolve_explicit_targets(self, state: BattleState, target_ids: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(unit_id for unit_id in target_ids if unit_id in state.units)

    def enemies_of(self, state: BattleState, actor_id: str) -> tuple[str, ...]:
        actor = state.units[actor_id]
        return tuple(unit_id for unit_id, unit in state.units.items() if unit.side != actor.side)

