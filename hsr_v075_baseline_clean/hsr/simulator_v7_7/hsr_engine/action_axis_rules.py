"""Shared action-axis normalization and snapshot projection helpers."""

from __future__ import annotations

from typing import Any

from hsr_engine.core_rules import coerce_float


def normalize_av(value: Any, old: Any = 0.0) -> float:
    return max(0.0, coerce_float(value, coerce_float(old, 0.0)))


def round_axis_value(value: Any, old: Any = 0.0) -> float:
    return round(coerce_float(value, coerce_float(old, 0.0)), 6)


def action_interval_for_speed(
    speed: Any,
    *,
    alive: bool = True,
    numeric_tolerance: float = 1e-5,
) -> float | None:
    speed_f = coerce_float(speed, 0.0)
    if not alive or speed_f <= numeric_tolerance:
        return None
    return round(10000.0 / speed_f, 6)


def absolute_av(global_av: Any, remaining_av: Any) -> float:
    return round(coerce_float(global_av, 0.0) + coerce_float(remaining_av, 0.0), 6)


def axis_sort_key(record: dict[str, Any]) -> tuple[bool, float, str, str]:
    return (
        not bool(record.get("alive")),
        coerce_float(record.get("remaining_av") or 0.0, 0.0),
        str(record.get("side") or ""),
        str(record.get("id") or ""),
    )


def sync_snapshot_absolute_av(
    snapshot: dict[str, Any],
    *,
    entity_groups: tuple[str, ...] = ("allies", "summons", "enemies", "others"),
) -> None:
    global_av = (snapshot.get("global") or {}).get("av", 0.0)
    for record in snapshot.get("action_axis", []) or []:
        if record.get("remaining_av") is not None:
            record["absolute_av"] = absolute_av(global_av, record.get("remaining_av"))
    for group in entity_groups:
        for entity in snapshot.get(group, []) or []:
            axis = entity.get("action_axis")
            if isinstance(axis, dict) and axis.get("remaining_av") is not None:
                axis["absolute_av"] = absolute_av(global_av, axis.get("remaining_av"))


def set_snapshot_remaining_av(
    entity: dict[str, Any],
    value: Any,
    *,
    axis_record: dict[str, Any] | None = None,
) -> float:
    remaining_av = round_axis_value(value)
    entity.setdefault("action_axis", {})["remaining_av"] = remaining_av
    if axis_record is not None:
        axis_record["remaining_av"] = remaining_av
    return remaining_av


def set_snapshot_axis_speed(
    entity: dict[str, Any],
    speed: Any,
    *,
    axis_record: dict[str, Any] | None = None,
    numeric_tolerance: float = 1e-5,
) -> float | None:
    speed_f = coerce_float(speed, 0.0)
    if speed_f <= numeric_tolerance:
        return None
    speed_value = round(speed_f, 6)
    panel = entity.setdefault("panel", {})
    if "speed" in panel:
        panel["speed"] = speed_value
    axis = entity.setdefault("action_axis", {})
    axis["speed"] = speed_value
    interval = action_interval_for_speed(
        speed_f,
        alive=bool(entity.get("alive")),
        numeric_tolerance=numeric_tolerance,
    )
    axis["action_interval"] = interval
    if axis_record is not None:
        axis_record["speed"] = speed_value
        axis_record["action_interval"] = interval
    return interval
