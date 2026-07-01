from __future__ import annotations

from typing import Literal

from ..core.model import UnitState


CombatTeam = Literal["ally", "enemy", "neutral"]


def combat_team_of(unit: UnitState) -> CombatTeam:
    if unit.side == "ally":
        return "ally"
    if unit.side == "enemy":
        return "enemy"
    team_side = unit.flags.get("team_side")
    if team_side in {"ally", "enemy"}:
        return team_side  # type: ignore[return-value]
    return "neutral"


def is_same_combat_team(left: UnitState, right: UnitState) -> bool:
    left_team = combat_team_of(left)
    right_team = combat_team_of(right)
    return left_team != "neutral" and left_team == right_team


def is_opposing_combat_team(left: UnitState, right: UnitState) -> bool:
    left_team = combat_team_of(left)
    right_team = combat_team_of(right)
    return left_team in {"ally", "enemy"} and right_team in {"ally", "enemy"} and left_team != right_team


def is_light_team(unit: UnitState) -> bool:
    return combat_team_of(unit) == "ally"


def is_dark_team(unit: UnitState) -> bool:
    return combat_team_of(unit) == "enemy"
