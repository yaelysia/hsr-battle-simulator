"""Shared resource normalization and snapshot projection helpers."""

from __future__ import annotations

from typing import Any

from hsr_engine.core_rules import coerce_float, coerce_int


def hp_percent(hp: Any, max_hp: Any) -> float:
    max_hp_f = coerce_float(max_hp, 0.0)
    hp_f = coerce_float(hp, 0.0)
    return 0.0 if max_hp_f <= 0 else round(hp_f / max_hp_f, 6)


def normalize_max_hp(value: Any, old: Any) -> float:
    return max(1.0, coerce_float(value, coerce_float(old, 1.0)))


def normalize_hp(value: Any, old: Any, max_hp: Any) -> float:
    value_f = coerce_float(value, coerce_float(old, 0.0))
    return max(0.0, min(value_f, coerce_float(max_hp, 0.0)))


def normalize_nonnegative(value: Any, old: Any = 0.0) -> float:
    return max(0.0, coerce_float(value, coerce_float(old, 0.0)))


def normalize_energy(value: Any, old: Any, max_energy: Any) -> float:
    value_f = coerce_float(value, coerce_float(old, 0.0))
    return max(0.0, min(value_f, coerce_float(max_energy, 0.0)))


def normalize_optional_nonnegative(value: Any, old: Any = 0.0) -> float | None:
    if value is None:
        return None
    return normalize_nonnegative(value, old)


def normalize_hp_bars_remaining(value: Any, old: Any, total: Any) -> int:
    old_i = coerce_int(old, 0)
    total_i = max(0, coerce_int(total, old_i))
    value_i = coerce_int(value, old_i)
    if total_i > 0:
        return max(0, min(total_i, value_i))
    return max(0, value_i)


def snapshot_resource_value(key: str, value: Any) -> Any:
    if key in {"hp", "max_hp", "shield", "energy", "toughness", "max_toughness"} and value is not None:
        return round(coerce_float(value, 0.0), 6)
    if key == "is_broken":
        return bool(value)
    if key == "hp_bars_remaining":
        return coerce_int(value, 0)
    return value


def apply_snapshot_resource_change(
    entity: dict[str, Any],
    key: str,
    value: Any,
    *,
    numeric_tolerance: float = 1e-5,
) -> Any:
    resources = entity.setdefault("resources", {})
    normalized = snapshot_resource_value(key, value)
    resources[key] = normalized
    if key in {"hp", "max_hp"}:
        set_panel_number(entity, key, normalized, numeric_tolerance=numeric_tolerance)
        sync_snapshot_hp_percent(entity)
    return normalized


def sync_snapshot_hp_percent(entity: dict[str, Any]) -> None:
    resources = entity.setdefault("resources", {})
    resources["hp_percent"] = hp_percent(resources.get("hp"), resources.get("max_hp"))


def set_panel_number(
    entity: dict[str, Any],
    key: str,
    value: Any,
    *,
    numeric_tolerance: float = 1e-5,
) -> None:
    panel = entity.setdefault("panel", {})
    if value is None or abs(coerce_float(value, 0.0)) <= numeric_tolerance:
        panel.pop(key, None)
    else:
        panel[key] = round(coerce_float(value, 0.0), 6)
