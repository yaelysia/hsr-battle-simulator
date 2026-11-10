"""Battle-event birth property sync declarations.

TBGD `BattleEventConfig.OverrideProperty` entries without a `Value` name
properties the created event takes from its property source.  The property
source is the `CreateBattleEvent.PropertyFromTarget` alias when present and
the creating ability's caster otherwise.  A separate
`SyncBattleEventPropertyValues` opcode re-copies the same value family later
(e.g. after selecting the highest-attack teammate), which proves the engine
copies values at explicit moments instead of live-aliasing the owner's panel.

This module only maps declared property names to the runtime channel that can
receive the value.  It is not a formula and it does not infer a value for a
property that has no producer.
"""
from __future__ import annotations


_ELEMENT_NAMES = (
    "Physical",
    "Fire",
    "Ice",
    "Thunder",
    "Wind",
    "Quantum",
    "Imaginary",
)

# (channel, runtime key).  `final_attack` folds every attack-composition
# property into the owner's effective attack because the event panel has no
# separate base/ratio/flat buckets of its own.
BATTLE_EVENT_SYNC_PROPERTY_TARGETS: dict[str, tuple[str, str]] = {}


def _register(property_name: str, channel: str, runtime_key: str) -> None:
    if property_name in BATTLE_EVENT_SYNC_PROPERTY_TARGETS:
        raise RuntimeError(f"duplicate battle event sync property: {property_name}")
    BATTLE_EVENT_SYNC_PROPERTY_TARGETS[property_name] = (channel, runtime_key)


for _name in (
    "Attack",
    "BaseAttack",
    "AttackAddedRatio",
    "AttackDelta",
    "AttackConvert",
):
    _register(_name, "final_attack", "attack")

for _name in (
    "Defence",
    "Defense",
    "BaseDefence",
    "BaseDefense",
    "DefenceAddedRatio",
    "DefenseAddedRatio",
    "DefenceDelta",
    "DefenseDelta",
    "DefenceConvert",
    "DefenseConvert",
):
    _register(_name, "effective_stat", "defense")

for _name in ("CriticalChance", "CriticalChanceBase"):
    _register(_name, "effective_stat", "critical_chance")

for _name in ("CriticalDamage", "CriticalDamageBase"):
    _register(_name, "effective_stat", "critical_damage")

for _name in ("StatusProbability", "StatusProbabilityBase"):
    _register(_name, "effective_stat", "effect_hit_rate")

for _name in ("StatusResistance", "StatusResistanceBase"):
    _register(_name, "effective_stat", "effect_resistance")

_register("AllDamageTypeAddedRatio", "resource", "damage_added_ratio")
_register("BreakDamageAddedRatio", "resource", "break_damage_added_ratio")
_register("BreakDamageAddedRatioBase", "resource", "break_damage_added_ratio")
_register("SPRatio", "resource", "energy_regeneration_rate")
_register("SPRatioBase", "resource", "energy_regeneration_rate")
_register("HealRatio", "resource", "outgoing_healing_ratio")
_register("HealRatioBase", "resource", "outgoing_healing_ratio")
_register("HealTakenRatio", "resource", "incoming_healing_ratio")
_register("ShieldAddedRatio", "resource", "shield_added_ratio")
_register("ShieldTakenRatio", "resource", "shield_added_ratio")
_register("AllDamageTypePenetrate", "resource", "all_res_pen")
_register("AllDamageTypeResistance", "resource", "all_resistance")

for _element in _ELEMENT_NAMES:
    _register(f"{_element}AddedRatio", "resource", f"{_element}_damage_added_ratio")
    _register(f"{_element}Penetrate", "resource", f"{_element}_res_pen")
    _register(f"{_element}Resistance", "resource", f"{_element}_resistance")

del _name, _element


def battle_event_sync_property_target(property_name: object) -> tuple[str, str] | None:
    """Return the runtime channel for one declared sync property."""

    if not isinstance(property_name, str):
        return None
    return BATTLE_EVENT_SYNC_PROPERTY_TARGETS.get(property_name)


def split_battle_event_sync_properties(
    property_names: object,
) -> tuple[list[str], list[str]]:
    """Split declared names into runtime-mapped and unmapped groups, in order."""

    supported: list[str] = []
    unsupported: list[str] = []
    if not isinstance(property_names, (list, tuple)):
        return supported, unsupported
    seen: set[str] = set()
    for name in property_names:
        if not isinstance(name, str) or not name or name in seen:
            continue
        seen.add(name)
        (supported if battle_event_sync_property_target(name) is not None
         else unsupported).append(name)
    return supported, unsupported
