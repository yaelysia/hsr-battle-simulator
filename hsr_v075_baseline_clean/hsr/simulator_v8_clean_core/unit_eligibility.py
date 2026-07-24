from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol


RuntimeCombatTeam = Literal["ally", "enemy", "neutral"]


class RuntimeUnitView(Protocol):
    side: str
    lifecycle_status: str
    flags: Mapping[str, object]


def runtime_unit_combat_team(unit: RuntimeUnitView) -> RuntimeCombatTeam:
    """Return the source-backed combat allegiance used by every consumer."""
    flags = getattr(unit, "flags", {})
    if isinstance(flags, Mapping) and flags.get("system_entity_kind"):
        return "neutral"
    side = getattr(unit, "side", None)
    if side == "ally":
        return "ally"
    if side == "enemy":
        return "enemy"
    team_side = flags.get("team_side") if isinstance(flags, Mapping) else None
    if team_side == "ally":
        return "ally"
    if team_side == "enemy":
        return "enemy"
    return "neutral"


def runtime_units_share_combat_team(
    left: RuntimeUnitView,
    right: RuntimeUnitView,
) -> bool:
    left_team = runtime_unit_combat_team(left)
    right_team = runtime_unit_combat_team(right)
    return left_team != "neutral" and left_team == right_team


def runtime_units_are_opposing_combat_teams(
    left: RuntimeUnitView,
    right: RuntimeUnitView,
) -> bool:
    left_team = runtime_unit_combat_team(left)
    right_team = runtime_unit_combat_team(right)
    return (
        left_team in {"ally", "enemy"}
        and right_team in {"ally", "enemy"}
        and left_team != right_team
    )


def runtime_unit_is_light_team(unit: RuntimeUnitView) -> bool:
    return runtime_unit_combat_team(unit) == "ally"


def runtime_unit_is_dark_team(unit: RuntimeUnitView) -> bool:
    return runtime_unit_combat_team(unit) == "enemy"


def runtime_unit_lifecycle_status(unit: RuntimeUnitView) -> str:
    """Return the canonical lifecycle status used by runtime target consumers."""
    return unit.lifecycle_status


def runtime_unit_is_active(unit: RuntimeUnitView) -> bool:
    """Whether the typed lifecycle marks a unit as alive and active."""
    return runtime_unit_lifecycle_status(unit) == "active"


def runtime_unit_is_on_field(unit: RuntimeUnitView) -> bool:
    """Whether a non-removed unit has an admitted on-field presence."""
    if unit.flags.get("system_entity_kind"):
        return False
    if runtime_unit_lifecycle_status(unit) == "removed":
        return False
    summon_kind = unit.flags.get("summon_kind")
    if not isinstance(summon_kind, str) or not summon_kind:
        return True
    lifecycle_source = unit.flags.get("lifecycle_source")
    if not isinstance(lifecycle_source, Mapping):
        return False
    return (
        lifecycle_source.get("admission_status") == "executable"
        and lifecycle_source.get("presence") == "field"
    )


def runtime_unit_source_is_targetable(unit: RuntimeUnitView) -> bool:
    """Return the source-backed targetability bit for summoned units."""
    if unit.flags.get("system_entity_kind"):
        return False
    summon_kind = unit.flags.get("summon_kind")
    if not isinstance(summon_kind, str) or not summon_kind:
        return True
    lifecycle_source = unit.flags.get("lifecycle_source")
    return bool(
        isinstance(lifecycle_source, Mapping)
        and lifecycle_source.get("targetable") is True
    )


def runtime_unit_is_unselectable(unit: RuntimeUnitView) -> bool:
    """Normalize all admitted runtime spellings of the unselectable flag."""
    return bool(
        unit.flags.get("unselectable") is True
        or unit.flags.get("target_unselectable") is True
        or unit.flags.get("is_unselectable") is True
        or unit.flags.get("selectable") is False
    )


def runtime_unit_is_target_candidate(
    unit: RuntimeUnitView,
    *,
    include_unselectable: bool = False,
) -> bool:
    """Shared participation gate for target, condition and callback traversals."""
    return (
        runtime_unit_is_active(unit)
        and runtime_unit_is_on_field(unit)
        and runtime_unit_source_is_targetable(unit)
        and (
            include_unselectable or not runtime_unit_is_unselectable(unit)
        )
    )
