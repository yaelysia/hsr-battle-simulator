from __future__ import annotations


_ABILITY_PROPERTY_STATS: dict[str, str] = {
    "Attack": "attack",
    "BreakDamageAddedRatio": "break_damage_added_ratio",
    "CriticalChance": "critical_chance",
    "CriticalChanceBase": "critical_chance",
    "CriticalDamage": "critical_damage",
    "Defence": "defense",
    "Defense": "defense",
    "ElationDamageAddedRatio": "elation_damage_added_ratio",
    "ElationDamageExtraAddedRatio": "elation_damage_extra_added_ratio",
    "ElationEchoPoint": "elation_echo_point",
    "MaxHP": "max_hp",
    # A flat Max-HP amount produced by HP conversion effects.  The game formula
    # subtracts it from MaxHP before applying percent-of-Max-HP conversions, so
    # it is a separate runtime bucket rather than part of the base panel.
    "HPConvert": "hp_convert",
    "AttackConvert": "attack_convert",
    "CriticalDamageConvert": "critical_damage_convert",
    "CurrentHP": "hp",
    # TBGD uses SP for per-unit ultimate energy; team skill points are BP.
    "CurrentSP": "energy",
    "MaxSP": "max_energy",
    "Speed": "speed",
    # TBGD stance reads are unit toughness; the runtime publishes both the
    # current and the maximum toughness pools.
    "MaxStance": "max_toughness",
    "CurrentStance": "toughness",
    "Stance": "toughness",
    "StatusProbability": "effect_hit_rate",
    "StatusProbabilityBase": "effect_hit_rate",
    "StatusResistance": "effect_resistance",
    "StatusResistanceBase": "effect_resistance",
    # Extra special SP capacity, extended by StackProperty modifiers.
    "MaxExtraSpecialSP": "max_extra_special_sp",
}


def ability_property_stat_name(property_name: object) -> str | None:
    if not isinstance(property_name, str):
        return None
    return _ABILITY_PROPERTY_STATS.get(property_name)


_COMPONENT_PROPERTY_NAMES = frozenset({
    "BaseHP",
    "CriticalDamageBase",
    "HPAddedRatio",
    "HPDelta",
    "BaseAttack",
    "AttackAddedRatio",
    "AttackDelta",
    "BaseDefense",
    "DefenseAddedRatio",
    "DefenseDelta",
    # TBGD spells these native defence components with "Defence".
    "BaseDefence",
    "DefenceAddedRatio",
    "DefenceDelta",
    "DefenceConvert",
    "BaseSpeed",
    "SpeedAddedRatio",
    "SpeedDelta",
    "SpeedConvert",
})


_UNIT_LEVEL_PROPERTY_NAMES = frozenset({"Level"})

# 负生命池：只有 EnableNegativeHP 写入的已提交标记才开启；未开启时读数为 0。
_NEGATIVE_HP_PROPERTY_NAMES = frozenset({"NegativeHP"})


_SPECIAL_RESOURCE_PROPERTY_NAMES = frozenset({
    "CurrentSpecialSP",
    "MaxSpecialSP",
    # Engine-maintained extra special SP pool; modifications are explicit
    # ModifyProperty tasks and the untouched baseline is zero.
    "CurExtraSpecialSP",
})


def ability_property_is_runtime_readable(property_name: object) -> bool:
    return (
        property_name in _COMPONENT_PROPERTY_NAMES
        or property_name in _SPECIAL_RESOURCE_PROPERTY_NAMES
        or property_name in _UNIT_LEVEL_PROPERTY_NAMES
        or property_name in _NEGATIVE_HP_PROPERTY_NAMES
        or property_name == "Shield"
        or ability_property_stat_name(property_name) is not None
    )
