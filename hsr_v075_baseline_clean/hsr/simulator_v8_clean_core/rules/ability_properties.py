from __future__ import annotations


_ABILITY_PROPERTY_STATS: dict[str, str] = {
    "Attack": "attack",
    "BreakDamageAddedRatio": "break_damage_added_ratio",
    "CriticalChance": "critical_chance",
    "CriticalDamage": "critical_damage",
    "Defence": "defense",
    "Defense": "defense",
    "ElationDamageAddedRatio": "elation_damage_added_ratio",
    "MaxHP": "max_hp",
    # TBGD uses SP for per-unit ultimate energy; team skill points are BP.
    "MaxSP": "max_energy",
    "Speed": "speed",
    "StatusProbability": "effect_hit_rate",
    "StatusProbabilityBase": "effect_hit_rate",
    "StatusResistance": "effect_resistance",
}


def ability_property_stat_name(property_name: object) -> str | None:
    if not isinstance(property_name, str):
        return None
    return _ABILITY_PROPERTY_STATS.get(property_name)


def ability_property_is_runtime_readable(property_name: object) -> bool:
    return property_name == "Shield" or ability_property_stat_name(property_name) is not None
