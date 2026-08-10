from __future__ import annotations

from dataclasses import dataclass
import math

from ..core.model import JSONValue, UnitState
from ..rules.ability_properties import ability_property_stat_name
from ..rules.evaluator import NumericEvaluationContext, RuleEvaluator


@dataclass(frozen=True)
class EffectiveUnitStat:
    stat: str
    base_value: float
    static_ratio: float
    ratio_delta: float
    static_flat: float
    flat_delta: float
    value: float
    source_terms: tuple[dict[str, JSONValue], ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "stat": self.stat,
            "base_value": self.base_value,
            "static_ratio": self.static_ratio,
            "ratio_delta": self.ratio_delta,
            "static_flat": self.static_flat,
            "flat_delta": self.flat_delta,
            "value": self.value,
            "source_terms": [dict(term) for term in self.source_terms],
        }


@dataclass(frozen=True)
class EffectiveStatusResistance:
    effect_resistance: float
    control_resistance: float
    specific_resistance: float
    resistance_chance: float

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "effect_resistance": self.effect_resistance,
            "control_resistance": self.control_resistance,
            "specific_resistance": self.specific_resistance,
            "resistance_chance": self.resistance_chance,
        }


_BASE_STAT_MODIFIERS: dict[str, tuple[str, str, str]] = {
    "max_hp": ("attribute", "hp_added_ratio", "hp_delta"),
    "attack": ("attribute", "attack_added_ratio", "attack_delta"),
    "defense": ("attribute", "defense_added_ratio", "defense_delta"),
    "speed": ("attribute", "speed_added_ratio", "speed_delta"),
}

_RESOURCE_STAT_MODIFIERS: dict[str, tuple[str, str]] = {
    "critical_chance": ("crit", "critical_chance"),
    "critical_damage": ("crit", "critical_damage"),
    "effect_hit_rate": ("status_probability", "effect_hit_rate"),
    "effect_resistance": ("status_probability", "effect_resistance"),
    "outgoing_healing_ratio": ("healing", "outgoing_healing_ratio"),
    "incoming_healing_ratio": ("healing", "incoming_healing_ratio"),
    "shield_added_ratio": ("shield", "shield_added_ratio"),
    "energy_regeneration_rate": ("resource", "energy_regeneration_rate"),
    "break_damage_added_ratio": ("break_bonus", "break_damage_added_ratio"),
    "elation_damage_added_ratio": ("damage_bonus", "elation_damage_added_ratio"),
}


def status_modifier_has_direct_combat_consumer(bucket: str, key: str) -> bool:
    """Whether this runtime modifier key is consumed by the S7 stat layer."""
    return any(
        bucket == configured_bucket and key in configured_keys
        for configured_bucket, *configured_keys in (
            *_BASE_STAT_MODIFIERS.values(),
            *_RESOURCE_STAT_MODIFIERS.values(),
        )
    )


def effective_unit_stat(unit: UnitState, stat: str) -> EffectiveUnitStat:
    if stat == "base_aggro":
        base_value = _resource_value(unit, "base_aggro")
        ratio_delta, terms = _status_modifier_total(
            unit,
            "aggro",
            ("aggro_added_ratio",),
        )
        return EffectiveUnitStat(
            stat=stat,
            base_value=base_value,
            static_ratio=0.0,
            ratio_delta=ratio_delta,
            static_flat=0.0,
            flat_delta=0.0,
            value=max(0.0, base_value * (1.0 + ratio_delta)),
            source_terms=terms,
        )

    base_config = _BASE_STAT_MODIFIERS.get(stat)
    if base_config is not None:
        bucket, ratio_key, flat_key = base_config
        stat_pool = {
            pool.property_type: pool for pool in unit.stat_pools
        }.get(stat)
        base_value = (
            stat_pool.base_value
            if stat_pool is not None
            else _direct_base_stat(unit, stat)
        )
        static_ratio = (
            stat_pool.static_percentage if stat_pool is not None else 0.0
        )
        static_flat = stat_pool.static_flat if stat_pool is not None else 0.0
        ratio_delta, ratio_terms = _status_modifier_total(unit, bucket, (ratio_key,))
        flat_delta, flat_terms = _status_modifier_total(unit, bucket, (flat_key,))
        value = (
            base_value * (1.0 + static_ratio + ratio_delta)
            + static_flat
            + flat_delta
        )
        return EffectiveUnitStat(
            stat=stat,
            base_value=base_value,
            static_ratio=static_ratio,
            ratio_delta=ratio_delta,
            static_flat=static_flat,
            flat_delta=flat_delta,
            value=value,
            source_terms=(*ratio_terms, *flat_terms),
        )

    resource_config = _RESOURCE_STAT_MODIFIERS.get(stat)
    if resource_config is not None:
        bucket, key = resource_config
        base_value = _resource_value(unit, stat)
        flat_delta, terms = _status_modifier_total(unit, bucket, (key,))
        return EffectiveUnitStat(
            stat=stat,
            base_value=base_value,
            static_ratio=0.0,
            ratio_delta=0.0,
            static_flat=0.0,
            flat_delta=flat_delta,
            value=base_value + flat_delta,
            source_terms=terms,
        )

    return EffectiveUnitStat(
        stat=stat,
        base_value=_direct_or_resource_value(unit, stat),
        static_ratio=0.0,
        ratio_delta=0.0,
        static_flat=0.0,
        flat_delta=0.0,
        value=_direct_or_resource_value(unit, stat),
    )


def control_kind_from_behavior_flags(behavior_flags: tuple[str, ...]) -> str:
    """Resolve the shared control-resistance key from admitted behavior flags."""

    if not ({"STAT_CTRL", "DisableAction"} & set(behavior_flags)):
        return ""
    for flag in behavior_flags:
        if not flag.startswith("STAT_") or flag == "STAT_CTRL":
            continue
        return flag.removeprefix("STAT_")
    return "control"


def effective_status_resistance(
    unit: UnitState,
    *,
    control_kind: str = "",
    special_resistance_key: str = "",
) -> EffectiveStatusResistance:
    """Return the shared committed resistance terms and combined resist chance."""

    if not isinstance(control_kind, str) or not isinstance(
        special_resistance_key, str
    ):
        raise TypeError("status resistance keys must be strings")
    effect = _clamped_stat_value(unit, "effect_resistance")
    control = (
        _clamped_resource_value(unit, "control_resistance")
        if control_kind
        else 0.0
    )
    specific = 0.0
    if control_kind and control_kind != "control":
        specific = _clamped_resource_value(
            unit, f"control_resistance:{control_kind}"
        )
    elif special_resistance_key:
        specific = _clamped_resource_value(unit, special_resistance_key)
    chance = 1.0 - (1.0 - effect) * (1.0 - control) * (1.0 - specific)
    return EffectiveStatusResistance(
        effect_resistance=effect,
        control_resistance=control,
        specific_resistance=specific,
        resistance_chance=max(0.0, min(1.0, chance)),
    )


def ability_property_value(unit: UnitState, property_name: object) -> float | None:
    if property_name == "Shield":
        return sum(
            float(item.get("remaining", 0.0))
            for item in unit.shield_instances
            if isinstance(item, dict)
            and isinstance(item.get("remaining"), (int, float))
            and not isinstance(item.get("remaining"), bool)
        )
    stat = ability_property_stat_name(property_name)
    return effective_unit_stat(unit, stat).value if stat is not None else None


def _direct_base_stat(unit: UnitState, stat: str) -> float:
    return float(getattr(unit, stat))


def _direct_or_resource_value(unit: UnitState, stat: str) -> float:
    if stat in {"hp", "max_hp", "attack", "defense", "speed", "energy", "max_energy", "toughness", "max_toughness", "action_value"}:
        return float(getattr(unit, stat))
    return _resource_value(unit, stat)


def _resource_value(unit: UnitState, key: str) -> float:
    value = unit.resources.get(key, 0.0)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _clamped_stat_value(unit: UnitState, key: str) -> float:
    value = effective_unit_stat(unit, key).value
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


def _clamped_resource_value(unit: UnitState, key: str) -> float:
    value = _resource_value(unit, key)
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


def _status_modifier_total(
    unit: UnitState,
    bucket: str,
    keys: tuple[str, ...],
) -> tuple[float, tuple[dict[str, JSONValue], ...]]:
    allowed_keys = set(keys)
    total = 0.0
    terms: list[dict[str, JSONValue]] = []
    for detail in _status_details(unit):
        instance_id = str(detail.get("instance_id") or detail.get("status_id") or "")
        modifiers = detail.get("modifiers")
        if not isinstance(modifiers, (list, tuple)):
            continue
        for modifier_index, modifier in enumerate(modifiers):
            if not isinstance(modifier, dict):
                continue
            if modifier.get("bucket") != bucket or modifier.get("key") not in allowed_keys:
                continue
            value = status_modifier_numeric_value(detail, modifier)
            if value is None:
                continue
            numeric_value = value
            total += numeric_value
            terms.append(
                {
                    "status_instance_id": instance_id,
                    "bucket": bucket,
                    "key": str(modifier.get("key") or ""),
                    "value": numeric_value,
                    "raw_path": str(
                        modifier.get("raw_path")
                        or f"status_details.{instance_id}.modifiers[{modifier_index}]"
                    ),
                    "source_trace": (
                        dict(detail.get("source_trace"))
                        if isinstance(detail.get("source_trace"), dict)
                        else {}
                    ),
                }
            )
    return total, tuple(terms)


def status_modifier_numeric_value(
    detail: dict[str, JSONValue],
    modifier: dict[str, JSONValue],
) -> float | None:
    value = modifier.get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    expression = modifier.get("value_expr")
    if not isinstance(expression, dict):
        return None
    dynamic_values = detail.get("dynamic_values")
    if not isinstance(dynamic_values, dict):
        return None
    bindings: dict[str, float] = {}
    for key, item in dynamic_values.items():
        if (
            not str(key).startswith("__")
            and isinstance(item, (int, float))
            and not isinstance(item, bool)
        ):
            bindings[str(key)] = float(item)
    for index_key in ("__by_name", "__by_hash"):
        indexed = dynamic_values.get(index_key)
        if not isinstance(indexed, dict):
            continue
        for key, item in indexed.items():
            if isinstance(item, (int, float)) and not isinstance(item, bool):
                bindings[str(key)] = float(item)
    result = RuleEvaluator().evaluate_numeric(
        expression,
        NumericEvaluationContext(
            dynamic_values=bindings,
            source_trace={
                "status_instance_source": (
                    dict(detail.get("source_trace"))
                    if isinstance(detail.get("source_trace"), dict)
                    else {}
                ),
                "modifier_raw_path": str(modifier.get("raw_path") or ""),
            },
        ),
    )
    return float(result.value) if result.ok and result.value is not None else None


def _status_details(unit: UnitState) -> tuple[dict[str, JSONValue], ...]:
    details = unit.flags.get("status_details", ())
    if not isinstance(details, (list, tuple)):
        return ()
    return tuple(detail for detail in details if isinstance(detail, dict))
