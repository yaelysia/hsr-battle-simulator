"""Status-instance scoped skill property overrides.

ModifySkillPropertyByType grants one status callback the right to change a
skill property (SPBase energy gain, BPNeed skill point cost) for the skill
types it names. The override lives on the owning status instance detail, so it
disappears atomically with that instance and can never leak into a later
manual skill.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

from ..core.model import BattleState, JSONValue
from ..rules.ir import ActionDefinitionIR

SUPPORTED_SKILL_PROPERTIES = frozenset({"SPBase", "BPNeed"})


@dataclass(frozen=True)
class SkillPropertyOverrides:
    values: Mapping[str, float]
    applied: tuple[dict[str, JSONValue], ...]
    blocked_reason: str = ""

    @property
    def ok(self) -> bool:
        return not self.blocked_reason


def _active_override_entries(
    state: BattleState, unit_id: str
) -> tuple[dict[str, JSONValue], ...]:
    unit = state.units.get(unit_id)
    if unit is None:
        return ()
    details = unit.flags.get("status_details")
    if not isinstance(details, (list, tuple)):
        return ()
    entries: list[dict[str, JSONValue]] = []
    for detail in details:
        if not isinstance(detail, dict):
            continue
        lifecycle = str(detail.get("lifecycle_state") or "active")
        if lifecycle.startswith(("expired", "removed", "inactive")):
            continue
        overrides = detail.get("skill_property_overrides")
        if not isinstance(overrides, (list, tuple)):
            continue
        entries.extend(item for item in overrides if isinstance(item, dict))
    return tuple(entries)


def resolve_skill_property_overrides(
    state: BattleState,
    unit_id: str,
    skill_type: str,
) -> SkillPropertyOverrides:
    """Resolve every active override for one action skill type (Normal/Skill/Ultra)."""

    if not isinstance(skill_type, str) or not skill_type:
        return SkillPropertyOverrides({}, (), "skill_property_skill_type_missing")
    grouped: dict[str, list[dict[str, JSONValue]]] = {}
    for entry in _active_override_entries(state, unit_id):
        property_type = entry.get("property_type")
        skill_types = entry.get("skill_types")
        if (
            not isinstance(property_type, str)
            or property_type not in SUPPORTED_SKILL_PROPERTIES
            or not isinstance(skill_types, (list, tuple))
            or skill_type not in skill_types
        ):
            continue
        grouped.setdefault(property_type, []).append(entry)
    values: dict[str, float] = {}
    applied: list[dict[str, JSONValue]] = []
    for property_type, entries in sorted(grouped.items()):
        candidates: set[float] = set()
        for entry in entries:
            value = entry.get("value")
            if type(value) not in (int, float) or isinstance(value, bool):
                return SkillPropertyOverrides(
                    {}, (), f"skill_property_override_value_invalid:{property_type}"
                )
            number = float(value)
            if not math.isfinite(number):
                return SkillPropertyOverrides(
                    {}, (), f"skill_property_override_value_invalid:{property_type}"
                )
            candidates.add(round(number, 9))
        if len(candidates) != 1:
            return SkillPropertyOverrides(
                {}, (), f"skill_property_override_conflict:{property_type}"
            )
        values[property_type] = candidates.pop()
        applied.extend(entries)
    return SkillPropertyOverrides(values, tuple(applied))


def skill_property_override_plan(
    definition,
    values: Mapping[str, float],
) -> dict[str, float]:
    """Return the overridden bp_need / sp_base values for one action definition."""

    result: dict[str, float] = {}
    if "BPNeed" in values:
        result["bp_need"] = max(float(values["BPNeed"]), 0.0)
    if "SPBase" in values:
        result["sp_base"] = max(float(values["SPBase"]), 0.0)
    return result


def effective_action_property(
    state: BattleState,
    unit_id: str,
    definition: ActionDefinitionIR,
    property_type: str,
    base_value: float,
) -> tuple[float, str]:
    """Effective action property for gates and body formulas.

    Returns the base value together with the override state: a blocked or
    conflicting override must block admission, never silently fall back.
    """

    from .action_event_contract import condition_skill_type

    overrides = resolve_skill_property_overrides(
        state, unit_id, condition_skill_type(definition)
    )
    if not overrides.ok:
        return base_value, overrides.blocked_reason
    values = skill_property_override_plan(definition, overrides.values)
    key = "bp_need" if property_type == "BPNeed" else "sp_base"
    return values.get(key, base_value), ""


def skill_property_override_evidence(
    overrides: SkillPropertyOverrides,
) -> dict[str, JSONValue]:
    return {
        "applied": [
            {
                "property_type": entry.get("property_type"),
                "skill_types": list(entry.get("skill_types") or ()),
                "value": entry.get("value"),
                "value_source": entry.get("value_source", ""),
                "status_instance_id": entry.get("status_instance_id", ""),
                "effect_id": entry.get("effect_id", ""),
            }
            for entry in overrides.applied
        ],
        "values": dict(overrides.values),
        "blocked_reason": overrides.blocked_reason,
    }


__all__ = [
    "SUPPORTED_SKILL_PROPERTIES",
    "SkillPropertyOverrides",
    "resolve_skill_property_overrides",
    "skill_property_override_plan",
    "skill_property_override_evidence",
]
