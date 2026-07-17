from __future__ import annotations

from ..unit_eligibility import (
    RuntimeCombatTeam as CombatTeam,
    runtime_unit_combat_team as combat_team_of,
    runtime_unit_is_dark_team as is_dark_team,
    runtime_unit_is_light_team as is_light_team,
    runtime_units_are_opposing_combat_teams as is_opposing_combat_team,
    runtime_units_share_combat_team as is_same_combat_team,
)


__all__ = [
    "CombatTeam",
    "combat_team_of",
    "is_dark_team",
    "is_light_team",
    "is_opposing_combat_team",
    "is_same_combat_team",
]
