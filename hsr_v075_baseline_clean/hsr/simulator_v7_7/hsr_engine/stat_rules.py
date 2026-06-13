"""Shared stat and panel derivation helpers.

These helpers operate on canonical full-scene snapshot dictionaries.  They are
kept independent from the transition reducer so settlement generation and
snapshot replay can converge on the same rule implementation.
"""

from __future__ import annotations

from typing import Any, Iterable

from hsr_engine.core_rules import coerce_float


ENTITY_GROUPS = ("allies", "summons", "enemies", "others")
PANEL_KEYS = (
    "hp",
    "max_hp",
    "atk",
    "attack",
    "def",
    "defense",
    "speed",
    "crit_rate",
    "crit_dmg",
    "break_effect",
    "effect_hit_rate",
    "effect_res",
    "energy_regeneration_rate",
    "err_bonus",
    "err",
    "all_dmg_bonus",
    "physical_dmg_bonus",
    "fire_dmg_bonus",
    "ice_dmg_bonus",
    "thunder_dmg_bonus",
    "wind_dmg_bonus",
    "quantum_dmg_bonus",
    "imaginary_dmg_bonus",
    "all_res_pen",
    "physical_res_pen",
    "fire_res_pen",
    "ice_res_pen",
    "thunder_res_pen",
    "wind_res_pen",
    "quantum_res_pen",
    "imaginary_res_pen",
    "healing_bonus",
    "outgoing_healing_bonus",
    "damage_taken",
    "damage_reduction",
)


def iter_snapshot_entities(
    snapshot: dict[str, Any],
    groups: Iterable[str] = ENTITY_GROUPS,
):
    for group in groups:
        for entity in snapshot.get(group, []) or []:
            if isinstance(entity, dict):
                yield entity


def snapshot_entity_by_id(snapshot: dict[str, Any], unit_id: str) -> dict[str, Any] | None:
    for entity in iter_snapshot_entities(snapshot):
        if str(entity.get("id")) == str(unit_id):
            return entity
    return None


def entity_stat_value(entity: dict[str, Any], name: str) -> float:
    stat_parts = entity.get("stat_parts") if isinstance(entity.get("stat_parts"), dict) else {}
    stat_base = stat_parts.get("base") if isinstance(stat_parts.get("base"), dict) else {}
    stat_pct = stat_parts.get("pct") if isinstance(stat_parts.get("pct"), dict) else {}
    stat_flat = stat_parts.get("flat") if isinstance(stat_parts.get("flat"), dict) else {}
    stats = stat_parts.get("legacy_stats") if isinstance(stat_parts.get("legacy_stats"), dict) else {}
    return stat_value_from_parts(
        name=name,
        stat_base=stat_base,
        stat_pct=stat_pct,
        stat_flat=stat_flat,
        stats=stats,
        statuses=entity.get("statuses", []) or [],
    )


def unit_stat_value(unit: Any, name: str) -> float:
    return stat_value_from_parts(
        name=name,
        stat_base=getattr(unit, "stat_base", {}),
        stat_pct=getattr(unit, "stat_pct", {}),
        stat_flat=getattr(unit, "stat_flat", {}),
        stats=getattr(unit, "stats", {}),
        statuses=getattr(unit, "statuses", []),
    )


def stat_value_from_parts(
    *,
    name: str,
    stat_base: dict[str, Any],
    stat_pct: dict[str, Any],
    stat_flat: dict[str, Any],
    stats: dict[str, Any],
    statuses: Any,
) -> float:
    add = 0.0
    pct = 0.0
    for status in statuses or []:
        mods = _status_modifiers(status)
        if not isinstance(mods, dict):
            continue
        stacks = int(coerce_float(_status_stacks(status), 1.0))
        add += coerce_float(mods.get(f"{name}_add", 0.0), 0.0) * stacks
        pct += coerce_float(mods.get(f"{name}_pct", 0.0), 0.0) * stacks
    if name in stat_base or name in stat_pct or name in stat_flat:
        base = coerce_float(stat_base.get(name, 0.0), 0.0)
        flat = coerce_float(stat_flat.get(name, 0.0), 0.0)
        base_pct = coerce_float(stat_pct.get(name, 0.0), 0.0)
        return base * (1.0 + base_pct + pct) + flat + add
    base = coerce_float(stats.get(name, 0.0), 0.0)
    return base * (1.0 + pct) + add


def contextual_entity_stat(
    snapshot: dict[str, Any],
    entity: dict[str, Any],
    name: str,
    seen: set[tuple[str, str]] | None = None,
) -> float:
    if name in {"hp", "max_hp"}:
        return coerce_float((entity.get("resources") or {}).get("max_hp"), 0.0)
    if name in {"current_hp", "currenthp"}:
        return coerce_float((entity.get("resources") or {}).get("hp"), 0.0)
    unit_id = str(entity.get("id") or "")
    seen = set(seen or set())
    key_seen = (unit_id, str(name))
    if key_seen in seen:
        return entity_stat_value(entity, name)
    seen.add(key_seen)

    value = entity_stat_value(entity, name)
    for status in entity.get("statuses", []) or []:
        if not isinstance(status, dict):
            continue
        mods = status.get("modifiers") if isinstance(status.get("modifiers"), dict) else {}
        for entry in _derived_stat_entries(mods):
            if str(entry.get("stat")) != str(name):
                continue
            source_id = str(entry.get("source", entry.get("source_id", status.get("source_id", ""))) or "")
            source = snapshot_entity_by_id(snapshot, source_id)
            source_stat = str(entry.get("source_stat", name))
            if source is None:
                continue
            if str(source.get("id")) == unit_id and source_stat == name:
                continue
            source_value = contextual_entity_stat(snapshot, source, source_stat, seen)
            scale = coerce_float(entry.get("scale", entry.get("ratio", 1.0)), 1.0)
            value += source_value * scale + coerce_float(entry.get("flat", 0.0), 0.0)
    return value


def derived_stat_dependencies(
    entity: dict[str, Any],
    panel_keys: tuple[str, ...] = PANEL_KEYS,
) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for status in entity.get("statuses", []) or []:
        if not isinstance(status, dict):
            continue
        mods = status.get("modifiers") if isinstance(status.get("modifiers"), dict) else {}
        for entry in _derived_stat_entries(mods):
            target_stat = str(entry.get("stat") or "")
            source_stat = str(entry.get("source_stat", target_stat) or "")
            source_id = str(entry.get("source", entry.get("source_id", status.get("source_id", ""))) or "")
            if target_stat in panel_keys and source_stat and source_id:
                out.append((target_stat, source_id, source_stat))
    return out


def modifier_affected_stats(
    mods: Any,
    panel_keys: tuple[str, ...] = PANEL_KEYS,
) -> set[str]:
    if not isinstance(mods, dict):
        return set()
    out: set[str] = set()
    for key in mods:
        key_s = str(key)
        if key_s.endswith("_add"):
            stat = key_s[:-4]
            if stat in panel_keys:
                out.add(stat)
        elif key_s.endswith("_pct"):
            stat = key_s[:-4]
            if stat in panel_keys:
                out.add(stat)
    for entry in _derived_stat_entries(mods):
        stat = str(entry.get("stat") or "")
        if stat in panel_keys:
            out.add(stat)
    return out


def status_affected_stats(
    status: Any,
    panel_keys: tuple[str, ...] = PANEL_KEYS,
) -> set[str]:
    if not isinstance(status, dict):
        return set()
    return modifier_affected_stats(status.get("modifiers"), panel_keys=panel_keys)


def propagate_dirty_stats(
    entities: list[dict[str, Any]],
    dirty_by_id: dict[str, set[str]],
) -> dict[str, set[str]]:
    out = {str(unit_id): set(stats) for unit_id, stats in dirty_by_id.items()}
    changed = True
    while changed:
        changed = False
        for entity in entities:
            unit_id = str(entity.get("id") or "")
            if not unit_id:
                continue
            target_dirty = out.setdefault(unit_id, set())
            for target_stat, source_id, source_stat in derived_stat_dependencies(entity):
                if source_stat in out.get(source_id, set()) and target_stat not in target_dirty:
                    target_dirty.add(target_stat)
                    changed = True
    return out


def _derived_stat_entries(mods: dict[str, Any]) -> list[dict[str, Any]]:
    entries = mods.get("derived_stat_add")
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _status_modifiers(status: Any) -> dict[str, Any]:
    if isinstance(status, dict):
        return status.get("modifiers") if isinstance(status.get("modifiers"), dict) else {}
    mods = getattr(status, "modifiers", {})
    return mods if isinstance(mods, dict) else {}


def _status_stacks(status: Any) -> Any:
    if isinstance(status, dict):
        return status.get("stacks", 1) or 1
    return getattr(status, "stacks", 1) or 1
