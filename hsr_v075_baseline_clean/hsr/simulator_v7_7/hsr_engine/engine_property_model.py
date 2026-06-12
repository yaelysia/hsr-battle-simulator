from __future__ import annotations

"""Simulator-facing model for engine-side TBGD property names.

This module is intentionally small and conservative.  It separates three cases:

* properties with a proven simulator stat alias, which may be read at runtime;
* known engine-derived properties, which must stay audit/unresolved until their
  formula bucket is proven;
* unknown properties, which also fail closed.

The combat kernel should use these normalized descriptions instead of treating
raw TBGD property strings as simulator stat names.
"""

from dataclasses import dataclass, asdict
from typing import Any


SIMULATOR_PROPERTY_ALIASES: dict[str, str] = {
    "Attack": "atk", "ATK": "atk", "atk": "atk",
    "Defence": "def", "Defense": "def", "DEF": "def", "def": "def",
    "MaxHP": "max_hp", "HP": "hp", "CurrentHP": "hp",
    "Speed": "speed", "SPD": "speed", "speed": "speed",
    "Energy": "energy", "MaxEnergy": "max_energy",
    "Toughness": "toughness", "MaxToughness": "max_toughness",
    "StatusProbabilityBase": "effect_hit", "StatusProbability": "effect_hit", "EffectHit": "effect_hit",
    "StatusResistanceBase": "effect_res", "StatusResistance": "effect_res", "EffectRes": "effect_res",
}

# Properties seen in ConfigAbility as both StackProperty writes and
# SetDynamicValueByProperty reads.  They are engine-side derived properties, not
# normal simulator stat aliases.  Keep them explicit so audit output can say why
# they were rejected.
DERIVED_ENGINE_PROPERTIES: dict[str, dict[str, Any]] = {
    "AttackConvert": {
        "category": "derived_flat_atk_modifier",
        "read_policy": "derived_status_property",
        "formula_bucket": "atk_add",
        "reason": "Dan Heng PT Fellow trace + public kit: AttackConvert is a non-snapshot flat ATK add for Fellow, derived from source Attack and a SkillTree scale; it must refresh when the source Attack changes",
    }
}

# StackProperty names that are proven to lower into existing simulator formula
# buckets only when their numeric DynamicValue is unambiguous.  They remain
# non-readable through SetDynamicValueByProperty unless a dedicated runtime
# property implementation is later added.
FORMULA_BUCKET_PROPERTY_HINTS: dict[str, dict[str, Any]] = {
    # Direct formula-bucket StackProperty mappings.  These are consumed only when
    # the generated status has exactly one unambiguous numeric DynamicValue.
    # Reads through SetDynamicValueByProperty still require explicit simulator
    # property models and therefore keep read_policy=audit_unresolved here.
    "AllDamageTypeAddedRatio": {"formula_bucket": "dmg_bonus_add", "reason": "StackProperty maps to HSR damage bonus bucket when value is unambiguous"},
    "AllDamageTypePenetrate": {"formula_bucket": "all_res_pen", "reason": "StackProperty maps to all-element resistance penetration when value is unambiguous"},
    "AttackAddedRatio": {"formula_bucket": "atk_pct", "reason": "StackProperty maps to attack percent stat bucket when value is unambiguous"},
    "DefenceAddedRatio": {"formula_bucket": "def_pct", "reason": "StackProperty maps to defense percent stat bucket when value is unambiguous"},
    "SpeedAddedRatio": {"formula_bucket": "speed_pct", "reason": "StackProperty maps to speed percent stat bucket when value is unambiguous"},
    "CriticalChanceBase": {"formula_bucket": "crit_rate_add", "reason": "StackProperty maps to crit-rate additive stat bucket when value is unambiguous"},
    "CriticalDamageBase": {"formula_bucket": "crit_dmg_add", "reason": "StackProperty maps to crit-damage additive stat bucket when value is unambiguous"},
    "AllDamageTypeTakenRatio": {"formula_bucket": "damage_taken_add", "reason": "StackProperty maps to all-damage taken additive bucket on the holder when value is unambiguous"},
    "AllDamageReduce": {"formula_bucket": "damage_reduction", "reason": "StackProperty maps to universal damage-reduction bucket on the holder when value is unambiguous"},
    "HPAddedRatio": {"formula_bucket": "max_hp_pct_delta", "reason": "In-combat max-HP percent increase: max HP increases and current HP increases by the same delta"},
    "MaxSP": {"formula_bucket": "skill_point_cap_add", "reason": "Team skill-point cap increase; current SP does not increase when cap increases and is clamped when cap decreases"},
    "StatusProbabilityBase": {"formula_bucket": "effect_hit_add", "reason": "StackProperty maps to effect-hit additive stat bucket when value is unambiguous"},
    "StatusResistanceBase": {"formula_bucket": "effect_res_add", "reason": "StackProperty maps to effect-resistance additive stat bucket when value is unambiguous"},
    "BreakDamageAddedRatioBase": {"formula_bucket": "break_damage_bonus", "reason": "StackProperty maps to break/super-break damage bonus bucket when value is unambiguous"},

    # Element-specific variants.  These lower into the simulator's nested
    # modifier maps (dmg_bonus.<element>, res_pen.<element>, damage_taken.<element>)
    # only when the value is unambiguous.  They are write-only StackProperty
    # patterns in the inventory and should not be treated as readable unit stats.
    "PhysicalAddedRatio": {"formula_bucket": "dmg_bonus.physical", "reason": "StackProperty maps to physical damage bonus when value is unambiguous"},
    "FireAddedRatio": {"formula_bucket": "dmg_bonus.fire", "reason": "StackProperty maps to fire damage bonus when value is unambiguous"},
    "IceAddedRatio": {"formula_bucket": "dmg_bonus.ice", "reason": "StackProperty maps to ice damage bonus when value is unambiguous"},
    "ThunderAddedRatio": {"formula_bucket": "dmg_bonus.thunder", "reason": "StackProperty maps to lightning/thunder damage bonus when value is unambiguous"},
    "WindAddedRatio": {"formula_bucket": "dmg_bonus.wind", "reason": "StackProperty maps to wind damage bonus when value is unambiguous"},
    "QuantumAddedRatio": {"formula_bucket": "dmg_bonus.quantum", "reason": "StackProperty maps to quantum damage bonus when value is unambiguous"},
    "ImaginaryAddedRatio": {"formula_bucket": "dmg_bonus.imaginary", "reason": "StackProperty maps to imaginary damage bonus when value is unambiguous"},

    "PhysicalPenetrate": {"formula_bucket": "res_pen.physical", "reason": "StackProperty maps to physical resistance penetration when value is unambiguous"},
    "FirePenetrate": {"formula_bucket": "res_pen.fire", "reason": "StackProperty maps to fire resistance penetration when value is unambiguous"},
    "IcePenetrate": {"formula_bucket": "res_pen.ice", "reason": "StackProperty maps to ice resistance penetration when value is unambiguous"},
    "ThunderPenetrate": {"formula_bucket": "res_pen.thunder", "reason": "StackProperty maps to lightning/thunder resistance penetration when value is unambiguous"},
    "WindPenetrate": {"formula_bucket": "res_pen.wind", "reason": "StackProperty maps to wind resistance penetration when value is unambiguous"},
    "QuantumPenetrate": {"formula_bucket": "res_pen.quantum", "reason": "StackProperty maps to quantum resistance penetration when value is unambiguous"},
    "ImaginaryPenetrate": {"formula_bucket": "res_pen.imaginary", "reason": "StackProperty maps to imaginary resistance penetration when value is unambiguous"},

    "PhysicalTakenRatio": {"formula_bucket": "damage_taken.physical", "reason": "StackProperty maps to physical damage-taken bucket when value is unambiguous"},
    "FireTakenRatio": {"formula_bucket": "damage_taken.fire", "reason": "StackProperty maps to fire damage-taken bucket when value is unambiguous"},
    "IceTakenRatio": {"formula_bucket": "damage_taken.ice", "reason": "StackProperty maps to ice damage-taken bucket when value is unambiguous"},
    "ThunderTakenRatio": {"formula_bucket": "damage_taken.thunder", "reason": "StackProperty maps to lightning/thunder damage-taken bucket when value is unambiguous"},
    "WindTakenRatio": {"formula_bucket": "damage_taken.wind", "reason": "StackProperty maps to wind damage-taken bucket when value is unambiguous"},
    "QuantumTakenRatio": {"formula_bucket": "damage_taken.quantum", "reason": "StackProperty maps to quantum damage-taken bucket when value is unambiguous"},
    "ImaginaryTakenRatio": {"formula_bucket": "damage_taken.imaginary", "reason": "StackProperty maps to imaginary damage-taken bucket when value is unambiguous"},
}


@dataclass(frozen=True)
class EnginePropertyDescription:
    property: str
    category: str
    read_policy: str
    simulator_key: str | None = None
    formula_bucket: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def describe_engine_property(prop: Any) -> EnginePropertyDescription:
    prop_s = str(prop or "")
    if prop_s in SIMULATOR_PROPERTY_ALIASES:
        return EnginePropertyDescription(
            property=prop_s,
            category="simulator_property_alias",
            read_policy="read_simulator_stat",
            simulator_key=SIMULATOR_PROPERTY_ALIASES[prop_s],
            reason="explicit simulator alias",
        )
    formula_hint = FORMULA_BUCKET_PROPERTY_HINTS.get(prop_s)
    if formula_hint:
        return EnginePropertyDescription(
            property=prop_s,
            category="formula_bucket_property_hint",
            read_policy="audit_unresolved",
            simulator_key=None,
            formula_bucket=str(formula_hint.get("formula_bucket") or ""),
            reason=str(formula_hint.get("reason") or "formula bucket hint requires property-hint consumer and explicit value"),
        )
    derived = DERIVED_ENGINE_PROPERTIES.get(prop_s)
    if derived:
        return EnginePropertyDescription(
            property=prop_s,
            category=str(derived.get("category") or "engine_derived_property"),
            read_policy=str(derived.get("read_policy") or "audit_unresolved"),
            simulator_key=None,
            formula_bucket=derived.get("formula_bucket"),
            reason=str(derived.get("reason") or "engine-side property has no proven simulator formula bucket"),
        )
    return EnginePropertyDescription(
        property=prop_s,
        category="unknown_engine_property",
        read_policy="audit_unresolved",
        simulator_key=None,
        reason="no simulator alias or proven engine-derived property model",
    )


def is_audit_only_property(prop: Any) -> bool:
    return describe_engine_property(prop).read_policy == "audit_unresolved"
