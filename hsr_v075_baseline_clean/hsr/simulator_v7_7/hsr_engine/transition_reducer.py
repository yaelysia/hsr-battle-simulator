"""Pure replay helpers for canonical action transitions.

The reducer works on the full-scene snapshot dictionaries emitted by the
simulator.  It intentionally reports unsupported paths instead of silently
pretending a transition is fully replayable.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from hsr_engine.action_axis_rules import (
    action_interval_for_speed,
    axis_sort_key,
    absolute_av,
    set_snapshot_axis_speed,
    set_snapshot_remaining_av,
    sync_snapshot_absolute_av,
)
from hsr_engine.resource_rules import apply_snapshot_resource_change
from hsr_engine.stat_rules import (
    PANEL_KEYS,
    contextual_entity_stat,
    iter_snapshot_entities,
    modifier_affected_stats,
    panel_from_unit_payload,
    propagate_dirty_stats,
    status_affected_stats,
)


ENTITY_GROUPS = ("allies", "summons", "enemies", "others")
QUEUE_NAMES = {"ultimate_queue", "immediate_queue", "interrupt_queue"}
AUDIT_ONLY_FIELD_PATHS = {
    "unit.hp_or_shield",
    "unit.turn",
}
SPECIAL_MECHANIC_FLAG_KEYS = {
    "current_phase",
    "monster_phase",
    "enemy_action_counter",
    "enemy_ai_sequence_index",
    "enemy_skill_cooldowns",
    "enemy_skill_cooldown_config",
    "enemy_ai_sequence",
    "phase_transition_immediate_action",
    "clear_glory_after_next_savage_action",
    "owner_id",
    "attached_to",
    "corresponding_summon",
    "corresponding_ally",
    "max_restorable_hp_ratio",
    "bondmate",
    "bondmate_target",
}
STATUS_PAYLOAD_KEYS = (
    "armor_layers",
    "titanic_corpus",
    "count_attacks_taken",
    "immediate_action_on_hit_by_element",
    "break_dot",
    "break_delayed_damage",
    "zone_followup_true_damage",
    "souldragon",
    "shield_expire_remove_amount",
)
NUMERIC_TOLERANCE = 1e-5


def _round_number(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    return value


def _copy(value: Any) -> Any:
    return deepcopy(value)


def _json_equal(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) <= NUMERIC_TOLERANCE
    return left == right


def _entity_record(snapshot: dict[str, Any], unit_id: str) -> dict[str, Any] | None:
    for group in ENTITY_GROUPS:
        for rec in snapshot.get(group, []) or []:
            if str(rec.get("id")) == str(unit_id):
                return rec
    return None


def _axis_record(snapshot: dict[str, Any], unit_id: str) -> dict[str, Any] | None:
    for rec in snapshot.get("action_axis", []) or []:
        if str(rec.get("id")) == str(unit_id):
            return rec
    return None


def _status_record(entity: dict[str, Any], status_id: str) -> dict[str, Any] | None:
    for rec in entity.get("statuses", []) or []:
        if str(rec.get("id")) == str(status_id):
            return rec
    return None


def _status_from_value(value: dict[str, Any], fallback_id: str) -> dict[str, Any]:
    mods = _copy(value.get("modifiers") or {})
    duration_type = value.get("duration_type")
    duration_value = value.get("duration_value")
    duration = value.get("duration") if isinstance(value.get("duration"), dict) else {}
    if duration_type is None:
        duration_type = duration.get("type")
    if duration_value is None:
        duration_value = duration.get("value")
    return {
        "id": str(value.get("id") or fallback_id),
        "source_id": value.get("source_id", value.get("source", value.get("owner"))),
        "stacks": int(value.get("stacks", 1)),
        "max_stacks": int(value.get("max_stacks", value.get("stacks", 1))),
        "duration": {
            "type": duration_type,
            "value": duration_value,
            "extra_turn_consumes": bool(value.get("duration_extra_turn_consumes", duration.get("extra_turn_consumes", False))),
            "refresh_duration": bool(value.get("refresh_duration", True)),
        },
        "tags": sorted(str(t) for t in (value.get("tags") or [])),
        "modifier_keys": sorted(str(k) for k in mods.keys()),
        "modifiers": mods,
    }


def _sync_status_modifier_keys(status: dict[str, Any]) -> None:
    mods = status.setdefault("modifiers", {})
    status["modifier_keys"] = sorted(str(k) for k in mods.keys())


def _sync_status_payloads(entity: dict[str, Any]) -> None:
    payloads: dict[str, list[dict[str, Any]]] = {}
    for status in entity.get("statuses", []) or []:
        mods = status.get("modifiers") if isinstance(status.get("modifiers"), dict) else {}
        for key in STATUS_PAYLOAD_KEYS:
            if key in mods:
                payloads.setdefault(key, []).append(
                    {
                        "status_id": status.get("id"),
                        "stacks": status.get("stacks", 1),
                        "payload": _copy(mods.get(key)),
                    }
                )
    mechanics = entity.setdefault("special_mechanics", {})
    if payloads:
        mechanics["status_payloads"] = payloads
    else:
        mechanics.pop("status_payloads", None)


def _sync_absolute_av(snapshot: dict[str, Any]) -> None:
    sync_snapshot_absolute_av(snapshot, entity_groups=ENTITY_GROUPS)


def _sort_axis(snapshot: dict[str, Any]) -> None:
    axis = snapshot.get("action_axis")
    if isinstance(axis, list):
        axis.sort(key=axis_sort_key)


def _sync_global_aliases(snapshot: dict[str, Any]) -> None:
    global_state = snapshot.setdefault("global", {})
    if "skill_points" in global_state:
        global_state["_sp"] = int(global_state["skill_points"])
    if "skill_point_cap" in global_state:
        global_state["_sp_cap"] = int(global_state["skill_point_cap"])


def _sync_special_flag(entity: dict[str, Any], key: str, value: Any, *, remove: bool = False) -> None:
    if key not in SPECIAL_MECHANIC_FLAG_KEYS:
        return
    mechanics = entity.setdefault("special_mechanics", {})
    if remove:
        mechanics.pop(key, None)
    else:
        mechanics[key] = _copy(value)


def _mark_dirty_stats(entity: dict[str, Any], stats: set[str]) -> None:
    stats = {s for s in stats if s in PANEL_KEYS}
    if not stats:
        return
    key = "__reducer_dirty_panel_stats"
    current = set(entity.get(key) or [])
    entity[key] = sorted(current | stats)


def _flush_dirty_derived(snapshot: dict[str, Any]) -> None:
    entities = list(iter_snapshot_entities(snapshot))
    dirty_by_id: dict[str, set[str]] = {}
    for entity in entities:
        unit_id = str(entity.get("id") or "")
        stats = set(entity.get("__reducer_dirty_panel_stats", []) or [])
        if unit_id and stats:
            dirty_by_id[unit_id] = set(stats)

    dirty_by_id = propagate_dirty_stats(entities, dirty_by_id)

    for entity in entities:
        unit_id = str(entity.get("id") or "")
        entity.pop("__reducer_dirty_panel_stats", None)
        stats = dirty_by_id.get(unit_id, set())
        if stats:
            _recompute_entity_derived(snapshot, entity, stats)


def _recompute_entity_derived(snapshot: dict[str, Any], entity: dict[str, Any], affected_stats: set[str]) -> None:
    panel = entity.setdefault("panel", {})
    for stat in sorted(s for s in affected_stats if s in PANEL_KEYS):
        value = contextual_entity_stat(snapshot, entity, stat)
        if abs(value) <= NUMERIC_TOLERANCE:
            panel.pop(stat, None)
        else:
            panel[stat] = round(value, 6)

    speed = contextual_entity_stat(snapshot, entity, "speed") if "speed" in affected_stats else 0.0
    if abs(speed) <= NUMERIC_TOLERANCE:
        speed = float((entity.get("action_axis") or {}).get("speed") or 0.0)
    if "speed" in affected_stats and speed > NUMERIC_TOLERANCE:
        axis_rec = _axis_record(snapshot, str(entity.get("id") or ""))
        set_snapshot_axis_speed(
            entity,
            speed,
            axis_record=axis_rec,
            numeric_tolerance=NUMERIC_TOLERANCE,
        )
    _sync_status_payloads(entity)


def _special_mechanics_from_unit_payload(raw: dict[str, Any], statuses: list[dict[str, Any]]) -> dict[str, Any]:
    flags = raw.get("flags") if isinstance(raw.get("flags"), dict) else {}
    mechanics = {k: _copy(flags.get(k)) for k in SPECIAL_MECHANIC_FLAG_KEYS if k in flags}
    entity = {"statuses": statuses, "special_mechanics": mechanics}
    _sync_status_payloads(entity)
    mechanics = entity.get("special_mechanics", {})
    if raw.get("side") == "enemy":
        mechanics["inferred_next_action"] = None
    return mechanics


def _entity_from_unit_payload(snapshot: dict[str, Any], raw: dict[str, Any], unit_id: str) -> dict[str, Any]:
    statuses = [_status_from_value(row if isinstance(row, dict) else {}, str((row or {}).get("id") or "")) for row in raw.get("statuses", []) or []]
    for status in statuses:
        _sync_status_modifier_keys(status)
    hp = round(float(raw.get("hp", 0.0) or 0.0), 6)
    max_hp = round(float(raw.get("max_hp", hp) or 0.0), 6)
    speed = round(float(raw.get("speed", raw.get("base_speed_field", 100.0)) or 0.0), 6)
    remaining_av = round(float(raw.get("remaining_av", 0.0) or 0.0), 6)
    av = float((snapshot.get("global") or {}).get("av", 0.0) or 0.0)
    alive = bool(raw.get("alive", hp > 0))
    action_interval = action_interval_for_speed(speed, alive=alive, numeric_tolerance=NUMERIC_TOLERANCE)
    entity = {
        "id": str(raw.get("id") or unit_id),
        "name": raw.get("name", unit_id),
        "side": raw.get("side", "ally"),
        "alive": alive,
        "tags": sorted(str(t) for t in (raw.get("tags") or [])),
        "resources": {
            "hp": hp,
            "max_hp": max_hp,
            "hp_percent": 0.0 if max_hp <= 0 else round(hp / max_hp, 6),
            "shield": round(float(raw.get("shield", 0.0) or 0.0), 6),
            "energy": round(float(raw.get("energy", 0.0) or 0.0), 6),
            "max_energy": round(float(raw.get("max_energy", 0.0) or 0.0), 6),
            "toughness": None if raw.get("toughness") is None else round(float(raw.get("toughness", 0.0)), 6),
            "max_toughness": None if raw.get("max_toughness") is None else round(float(raw.get("max_toughness", 0.0)), 6),
            "is_broken": bool(raw.get("is_broken", False)),
            "hp_bars_total": int(raw.get("hp_bars_total", 1) or 1),
            "hp_bars_remaining": int(raw.get("hp_bars_remaining", 1) or 1),
            "hp_model_type": raw.get("hp_model_type", "normal_hp"),
            "hp_carry_over_damage": raw.get("hp_carry_over_damage"),
        },
        "action_axis": {
            "remaining_av": remaining_av,
            "absolute_av": absolute_av(av, remaining_av),
            "speed": speed,
            "action_interval": action_interval,
        },
        "panel": panel_from_unit_payload(raw, numeric_tolerance=NUMERIC_TOLERANCE),
        "stat_parts": {
            "base": _copy(raw.get("stat_base") or {}),
            "pct": _copy(raw.get("stat_pct") or {}),
            "flat": _copy(raw.get("stat_flat") or {}),
            "legacy_stats": _copy(raw.get("stats") or {}),
        },
        "resistance": _copy(raw.get("res") or {}),
        "weaknesses": sorted(str(t) for t in (raw.get("weaknesses") or [])),
        "statuses": statuses,
        "special_mechanics": _special_mechanics_from_unit_payload(raw, statuses),
        "flags": _copy(raw.get("flags") or {}),
    }
    return entity


def _axis_from_entity(snapshot: dict[str, Any], entity: dict[str, Any]) -> dict[str, Any]:
    axis = entity.get("action_axis") or {}
    interval = axis.get("action_interval") if entity.get("alive") else None
    return {
        "id": entity.get("id"),
        "name": entity.get("name"),
        "side": entity.get("side"),
        "alive": bool(entity.get("alive")),
        "speed": axis.get("speed"),
        "action_interval": interval,
        "remaining_av": axis.get("remaining_av"),
        "absolute_av": axis.get("absolute_av"),
        "tags": sorted(str(t) for t in (entity.get("tags") or [])),
    }


def _entity_group_for_record(entity: dict[str, Any]) -> str:
    side = entity.get("side")
    tags = {str(t).lower() for t in (entity.get("tags") or [])}
    flags = entity.get("flags") if isinstance(entity.get("flags"), dict) else {}
    if side == "ally" and ("summon" in tags or flags.get("owner_id")):
        return "summons"
    if side == "ally":
        return "allies"
    if side == "enemy":
        return "enemies"
    return "others"


def _upsert_unit(snapshot: dict[str, Any], unit_id: str, raw: dict[str, Any]) -> None:
    _remove_unit(snapshot, unit_id)
    entity = _entity_from_unit_payload(snapshot, raw, unit_id)
    snapshot.setdefault(_entity_group_for_record(entity), []).append(entity)
    if "not_on_timeline" not in {str(t) for t in entity.get("tags", [])}:
        snapshot.setdefault("action_axis", []).append(_axis_from_entity(snapshot, entity))


def _remove_unit(snapshot: dict[str, Any], unit_id: str) -> None:
    for group in ENTITY_GROUPS:
        rows = snapshot.get(group)
        if isinstance(rows, list):
            snapshot[group] = [row for row in rows if str(row.get("id")) != str(unit_id)]
    axis = snapshot.get("action_axis")
    if isinstance(axis, list):
        snapshot["action_axis"] = [row for row in axis if str(row.get("id")) != str(unit_id)]


def _projection(snapshot: dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    if parts[:2] == ["global", "flags"] and len(parts) >= 3:
        return (snapshot.get("global") or {}).get("flags", {}).get(".".join(parts[2:]))
    if parts[:1] == ["global"] and len(parts) == 2:
        return (snapshot.get("global") or {}).get(parts[1])
    if parts[:1] == ["queues"] and len(parts) == 2:
        return (snapshot.get("queues") or {}).get(parts[1])
    if parts[:1] == ["trigger_usage"] and len(parts) >= 2:
        return (snapshot.get("trigger_usage") or {}).get(".".join(parts[1:]))
    if parts[:1] == ["unit"] and len(parts) >= 3:
        entity = _entity_record(snapshot, parts[1])
        if entity is None:
            return None
        if parts[2] == "resources" and len(parts) == 4:
            return (entity.get("resources") or {}).get(parts[3])
        if parts[2] == "panel" and len(parts) == 4:
            return (entity.get("panel") or {}).get(parts[3])
        if parts[2] == "action_axis" and len(parts) == 4:
            return (entity.get("action_axis") or {}).get(parts[3])
        if parts[2] == "flags" and len(parts) >= 4:
            return (entity.get("flags") or {}).get(".".join(parts[3:]))
        if parts[2] == "alive" and len(parts) == 3:
            return entity.get("alive")
        if parts[2] == "statuses" and len(parts) >= 4:
            status = _status_record(entity, parts[3])
            if len(parts) == 4:
                return status
            if status is None:
                return None
            if parts[4] == "duration" and len(parts) == 6:
                return (status.get("duration") or {}).get(parts[5])
            if parts[4] == "modifiers" and len(parts) >= 6:
                return (status.get("modifiers") or {}).get(".".join(parts[5:]))
            return status.get(parts[4])
    if parts[:1] == ["axis"] and len(parts) == 3:
        rec = _axis_record(snapshot, parts[1])
        return None if rec is None else rec.get(parts[2])
    return None


def _set_projection_paths_for_change(change: dict[str, Any]) -> list[str]:
    field_path = str(change.get("field_path") or "")
    subject_id = str(change.get("subject_id") or "")
    paths: list[str] = []
    if field_path in {"global.skill_points", "global.skill_point_cap", "global.av", "global.wave_index"}:
        paths.append(field_path)
        if field_path == "global.skill_points":
            paths.append("global._sp")
        elif field_path == "global.skill_point_cap":
            paths.append("global._sp_cap")
    elif field_path.startswith("global.flags."):
        paths.append(field_path)
    elif field_path.startswith("battle.queues."):
        paths.append(f"queues.{field_path[len('battle.queues.'): ]}")
    elif field_path.startswith("battle.trigger_usage."):
        paths.append(f"trigger_usage.{field_path[len('battle.trigger_usage.'): ]}")
    elif field_path == "unit.hp":
        paths += [f"unit.{subject_id}.resources.hp", f"unit.{subject_id}.panel.hp", f"unit.{subject_id}.resources.hp_percent"]
    elif field_path == "unit.max_hp":
        paths += [f"unit.{subject_id}.resources.max_hp", f"unit.{subject_id}.panel.max_hp", f"unit.{subject_id}.resources.hp_percent"]
    elif field_path in {"unit.shield", "unit.energy", "unit.toughness", "unit.max_toughness", "unit.is_broken", "unit.hp_bars_remaining"}:
        key = field_path.split(".", 1)[1]
        paths.append(f"unit.{subject_id}.resources.{key}")
    elif field_path == "unit.alive":
        paths += [f"unit.{subject_id}.alive", f"axis.{subject_id}.alive"]
    elif field_path == "unit.remaining_av":
        paths += [f"unit.{subject_id}.action_axis.remaining_av", f"unit.{subject_id}.action_axis.absolute_av", f"axis.{subject_id}.remaining_av", f"axis.{subject_id}.absolute_av"]
    elif field_path.startswith("unit.flags."):
        paths.append(f"unit.{subject_id}.{field_path}")
    elif field_path.startswith("unit.statuses."):
        status_path = field_path[len("unit.statuses."):]
        status_id = status_path.split(".", 1)[0]
        paths.append(f"unit.{subject_id}.statuses.{status_id}")
    return paths


def _apply_change(snapshot: dict[str, Any], change: dict[str, Any]) -> tuple[str, str]:
    field_path = str(change.get("field_path") or "")
    scope = str(change.get("scope") or "")
    subject_id = str(change.get("subject_id") or "")
    delta = change.get("delta")
    new_value = _copy(change.get("new_value"))

    if field_path in AUDIT_ONLY_FIELD_PATHS:
        return "audit_only", field_path

    if scope == "global" and field_path in {"global.skill_points", "global.skill_point_cap", "global.av", "global.wave_index"}:
        key = field_path.split(".", 1)[1]
        value = _round_number(new_value)
        if key in {"skill_points", "skill_point_cap", "cycle", "wave_index"}:
            value = int(value)
        snapshot.setdefault("global", {})[key] = value
        return "applied", field_path

    if scope == "global" and field_path.startswith("global.flags."):
        key = field_path[len("global.flags."):]
        flags = snapshot.setdefault("global", {}).setdefault("flags", {})
        if delta == "remove":
            flags.pop(key, None)
        else:
            flags[key] = new_value
        return "applied", field_path

    if scope == "battle" and field_path.startswith("battle.queues."):
        queue_name = field_path[len("battle.queues."):]
        if queue_name not in QUEUE_NAMES:
            return "unsupported", field_path
        snapshot.setdefault("queues", {})[queue_name] = _copy(new_value or [])
        return "applied", field_path

    if scope == "battle" and field_path.startswith("battle.trigger_usage."):
        key = field_path[len("battle.trigger_usage."):]
        usage = snapshot.setdefault("trigger_usage", {})
        if delta == "remove":
            usage.pop(key, None)
        else:
            usage[key] = int(new_value)
        return "applied", field_path

    if scope == "battle" and field_path.startswith("battle.units."):
        unit_id = field_path[len("battle.units."):]
        if new_value is None:
            _remove_unit(snapshot, unit_id)
            return "applied", field_path
        if not isinstance(new_value, dict):
            return "unsupported", field_path
        _upsert_unit(snapshot, unit_id, new_value)
        return "applied", field_path

    if scope != "unit":
        return "unsupported", field_path

    entity = _entity_record(snapshot, subject_id)
    if entity is None:
        return "unsupported", field_path

    if field_path in {"unit.hp", "unit.max_hp", "unit.shield", "unit.energy", "unit.toughness", "unit.max_toughness", "unit.is_broken", "unit.hp_bars_remaining"}:
        key = field_path.split(".", 1)[1]
        apply_snapshot_resource_change(entity, key, new_value, numeric_tolerance=NUMERIC_TOLERANCE)
        return "applied", field_path

    if field_path == "unit.alive":
        alive = bool(new_value)
        entity["alive"] = alive
        axis = _axis_record(snapshot, subject_id)
        if axis is not None:
            axis["alive"] = alive
            if not alive:
                axis["action_interval"] = None
        action_axis = entity.setdefault("action_axis", {})
        if not alive:
            action_axis["action_interval"] = None
        return "applied", field_path

    if field_path == "unit.remaining_av":
        axis = _axis_record(snapshot, subject_id)
        set_snapshot_remaining_av(entity, new_value, axis_record=axis)
        return "applied", field_path

    if field_path.startswith("unit.flags."):
        key = field_path[len("unit.flags."):]
        flags = entity.setdefault("flags", {})
        if delta == "remove":
            flags.pop(key, None)
            _sync_special_flag(entity, key, None, remove=True)
        else:
            flags[key] = new_value
            _sync_special_flag(entity, key, new_value)
        return "applied", field_path

    if field_path.startswith("unit.actions."):
        return "internal_only", field_path

    if field_path.startswith("unit.statuses."):
        path = field_path[len("unit.statuses."):]
        status_id, _, rest = path.partition(".")
        statuses = entity.setdefault("statuses", [])
        status = _status_record(entity, status_id)
        if not rest:
            affected_stats = (
                status_affected_stats(change.get("old_value"))
                | status_affected_stats(change.get("new_value"))
            )
            if new_value is None:
                entity["statuses"] = [row for row in statuses if str(row.get("id")) != status_id]
            else:
                replacement = _status_from_value(new_value if isinstance(new_value, dict) else {}, status_id)
                for idx, row in enumerate(statuses):
                    if str(row.get("id")) == status_id:
                        statuses[idx] = replacement
                        break
                else:
                    statuses.append(replacement)
            _sync_status_payloads(entity)
            _mark_dirty_stats(entity, affected_stats)
            return "applied", field_path
        if status is None:
            return "unsupported", field_path
        affected_stats = status_affected_stats(status)
        if rest in {"stacks", "max_stacks"}:
            status[rest] = int(new_value)
        elif rest == "duration_value":
            status.setdefault("duration", {})["value"] = None if new_value is None else int(new_value)
        elif rest == "duration_type":
            status.setdefault("duration", {})["type"] = None if new_value is None else str(new_value)
        elif rest == "duration_extra_turn_consumes":
            status.setdefault("duration", {})["extra_turn_consumes"] = bool(new_value)
        elif rest.startswith("modifiers."):
            key = rest[len("modifiers."):]
            status.setdefault("modifiers", {})[key] = new_value
            _sync_status_modifier_keys(status)
            affected_stats |= modifier_affected_stats({key: new_value})
        else:
            return "unsupported", field_path
        affected_stats |= status_affected_stats(status)
        _sync_status_payloads(entity)
        _mark_dirty_stats(entity, affected_stats)
        return "applied", field_path

    return "unsupported", field_path


def reduce_transition_snapshot(transition: dict[str, Any]) -> dict[str, Any]:
    before = transition.get("before_snapshot")
    if not isinstance(before, dict):
        return {"ok": False, "reason": "missing_before_snapshot"}
    snapshot = _copy(before)
    applied: list[str] = []
    audit_only: list[str] = []
    internal_only: list[str] = []
    unsupported: list[str] = []
    projection_paths: list[str] = []
    for change in transition.get("state_changes") or []:
        if not isinstance(change, dict):
            unsupported.append("<non_dict_change>")
            continue
        status, path = _apply_change(snapshot, change)
        if status == "applied":
            applied.append(path)
            projection_paths.extend(_set_projection_paths_for_change(change))
        elif status == "audit_only":
            audit_only.append(path)
        elif status == "internal_only":
            internal_only.append(path)
        else:
            unsupported.append(path)
    _flush_dirty_derived(snapshot)
    _sync_global_aliases(snapshot)
    _sync_absolute_av(snapshot)
    _sort_axis(snapshot)
    return {
        "ok": True,
        "snapshot": snapshot,
        "applied_count": len(applied),
        "audit_only_count": len(audit_only),
        "internal_only_count": len(internal_only),
        "unsupported_count": len(unsupported),
        "applied_paths": applied,
        "audit_only_paths": audit_only,
        "internal_only_paths": internal_only,
        "unsupported_paths": unsupported,
        "projection_paths": sorted(set(projection_paths)),
    }


def _first_diffs(left: Any, right: Any, *, prefix: str = "", limit: int = 20) -> list[dict[str, Any]]:
    if len(prefix) > 500:
        return []
    if type(left) is not type(right):
        return [{"path": prefix or "$", "left": left, "right": right}]
    if isinstance(left, dict):
        out: list[dict[str, Any]] = []
        keys = sorted(set(left) | set(right))
        for key in keys:
            if key not in left or key not in right:
                out.append({"path": f"{prefix}.{key}" if prefix else str(key), "left": left.get(key), "right": right.get(key)})
            else:
                out.extend(_first_diffs(left[key], right[key], prefix=f"{prefix}.{key}" if prefix else str(key), limit=limit - len(out)))
            if len(out) >= limit:
                return out[:limit]
        return out
    if isinstance(left, list):
        out = []
        if len(left) != len(right):
            out.append({"path": f"{prefix}.length" if prefix else "length", "left": len(left), "right": len(right)})
        for idx, (l_item, r_item) in enumerate(zip(left, right)):
            out.extend(_first_diffs(l_item, r_item, prefix=f"{prefix}[{idx}]", limit=limit - len(out)))
            if len(out) >= limit:
                return out[:limit]
        return out
    if not _json_equal(left, right):
        return [{"path": prefix or "$", "left": left, "right": right}]
    return []


def _sequence_id(value: Any) -> int | None:
    try:
        seq = int(value)
    except (TypeError, ValueError):
        return None
    return seq if seq > 0 else None


def _state_changes_by_sequence(transition: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for change in transition.get("state_changes") or []:
        if not isinstance(change, dict):
            continue
        seq = _sequence_id(change.get("sequence"))
        if seq is not None:
            out[seq] = change
    return out


def _validate_process_events(transition: dict[str, Any], *, diff_limit: int = 20) -> dict[str, Any]:
    changes_by_sequence = _state_changes_by_sequence(transition)
    events = [row for row in (transition.get("process_events") or []) if isinstance(row, dict)]
    issues: list[dict[str, Any]] = []
    issue_count = 0
    unsupported_types: set[str] = set()
    supported_event_count = 0
    target_resolution_count = 0
    target_resolution_valid_count = 0
    target_decision_count = 0
    target_decision_valid_count = 0
    timeline_tick_count = 0
    timeline_tick_valid_count = 0
    action_defeat_credit_count = 0
    action_defeat_credit_valid_count = 0
    derived_damage_skip_count = 0
    derived_damage_skip_valid_count = 0
    phase_damage_lock_count = 0
    phase_damage_lock_valid_count = 0
    phase_damage_skip_count = 0
    phase_damage_skip_valid_count = 0
    latest_target_resolution_payload: dict[str, Any] | None = None
    target_decision_payloads_by_index: dict[int, dict[str, Any]] = {}
    defeat_credit_targets: set[str] = set()
    phase_locked_targets: set[str] = set()

    def add_issue(path: str, message: str, *, actual: Any = None, expected: Any = None) -> None:
        nonlocal issue_count
        issue_count += 1
        if len(issues) < diff_limit:
            issue = {"path": path, "message": message}
            if actual is not None or expected is not None:
                issue["actual"] = actual
                issue["expected"] = expected
            issues.append(issue)

    def compare(path: str, actual: Any, expected: Any) -> None:
        if not _json_equal(actual, expected):
            add_issue(path, "value_mismatch", actual=actual, expected=expected)

    def validate_payload_dict(prefix: str, event: dict[str, Any]) -> dict[str, Any] | None:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            add_issue(f"{prefix}.payload", "missing_payload_dict", actual=payload, expected="dict")
            return None
        return payload

    def validate_basic_target_payload(prefix: str, event: dict[str, Any], payload: dict[str, Any]) -> str:
        target_id = str(payload.get("target_id") or "")
        if not target_id:
            add_issue(f"{prefix}.payload.target_id", "missing_target_id", actual=payload.get("target_id"), expected="non-empty string")
        compare(f"{prefix}.subject_id", event.get("subject_id"), target_id)
        return target_id

    def validate_target_payload(prefix: str, event: dict[str, Any], payload: dict[str, Any]) -> str:
        target_id = str(payload.get("target_id") or "")
        if not target_id:
            add_issue(f"{prefix}.payload.target_id", "missing_target_id", actual=payload.get("target_id"), expected="non-empty string")
        compare(f"{prefix}.subject_id", event.get("subject_id"), target_id)
        locked_targets = payload.get("phase_locked_targets")
        if not isinstance(locked_targets, list):
            add_issue(f"{prefix}.payload.phase_locked_targets", "missing_phase_locked_targets_list", actual=locked_targets, expected="list")
        elif target_id and target_id not in {str(x) for x in locked_targets}:
            add_issue(f"{prefix}.payload.phase_locked_targets", "target_missing_from_phase_locked_targets", actual=locked_targets, expected=target_id)
        return target_id

    for event_index, event in enumerate(events):
        event_type = str(event.get("event_type") or "")
        if event_type == "timeline_tick":
            supported_event_count += 1
        elif event_type == "target_resolution":
            supported_event_count += 1
        elif event_type == "target_decision":
            supported_event_count += 1
        elif event_type == "action_defeat_credit":
            supported_event_count += 1
        elif event_type == "derived_damage_target_skip":
            supported_event_count += 1
        elif event_type in {"phase_damage_lock", "damage_target_skip", "effect_damage_target_skip"}:
            supported_event_count += 1
        else:
            unsupported_types.add(event_type or "<empty>")
            continue

        if event_type == "target_resolution":
            target_resolution_count += 1
            before_issue_count = issue_count
            prefix = f"process_events[{event_index}]"
            payload = validate_payload_dict(prefix, event)
            if payload is None:
                continue
            request = transition.get("request")
            if not isinstance(request, dict):
                add_issue(f"{prefix}.request", "missing_action_request", actual=request, expected="dict")
                request = {}
            actor_id = str(payload.get("actor_id") or "")
            action_id = str(payload.get("action_id") or "")
            if not actor_id:
                add_issue(f"{prefix}.payload.actor_id", "missing_actor_id", actual=payload.get("actor_id"), expected="non-empty string")
            if not action_id:
                add_issue(f"{prefix}.payload.action_id", "missing_action_id", actual=payload.get("action_id"), expected="non-empty string")
            compare(f"{prefix}.subject_id", event.get("subject_id"), actor_id)
            compare(f"{prefix}.reason", event.get("reason"), "target:resolution")
            compare(f"{prefix}.payload.actor_id", actor_id, request.get("actor_id"))
            compare(f"{prefix}.payload.action_id", action_id, request.get("action_id"))
            requested_targets = payload.get("requested_target_ids")
            resolved_targets = payload.get("resolved_target_ids")
            if not isinstance(requested_targets, list):
                add_issue(f"{prefix}.payload.requested_target_ids", "missing_requested_target_ids_list", actual=requested_targets, expected="list")
            else:
                compare(f"{prefix}.payload.requested_target_ids", requested_targets, request.get("target_ids") or [])
            if not isinstance(resolved_targets, list):
                add_issue(f"{prefix}.payload.resolved_target_ids", "missing_resolved_target_ids_list", actual=resolved_targets, expected="list")
            method = payload.get("method")
            if not isinstance(method, str) or not method:
                add_issue(f"{prefix}.payload.method", "missing_target_resolution_method", actual=method, expected="non-empty string")
            compare(f"{prefix}.payload.reason", payload.get("reason"), method)
            request_source = request.get("source") if isinstance(request.get("source"), dict) else {}
            compare(f"{prefix}.source", event.get("source"), request_source)
            compare(f"{prefix}.payload.source", payload.get("source"), request_source)
            if issue_count == before_issue_count:
                target_resolution_valid_count += 1
                latest_target_resolution_payload = deepcopy(payload)
            continue

        if event_type == "target_decision":
            target_decision_count += 1
            before_issue_count = issue_count
            prefix = f"process_events[{event_index}]"
            payload = validate_payload_dict(prefix, event)
            if payload is None:
                continue
            request = transition.get("request")
            if not isinstance(request, dict):
                add_issue(f"{prefix}.request", "missing_action_request", actual=request, expected="dict")
                request = {}
            decision_index = _sequence_id(payload.get("decision_index"))
            if decision_index is None:
                add_issue(f"{prefix}.payload.decision_index", "missing_decision_index", actual=payload.get("decision_index"), expected="positive int")
            elif decision_index in target_decision_payloads_by_index:
                add_issue(f"{prefix}.payload.decision_index", "duplicate_decision_index", actual=decision_index, expected="unique target decision index")
            stage = payload.get("stage")
            if not isinstance(stage, str) or not stage:
                add_issue(f"{prefix}.payload.stage", "missing_target_decision_stage", actual=stage, expected="non-empty string")
            actor_id = str(payload.get("actor_id") or "")
            action_id = str(payload.get("action_id") or "")
            compare(f"{prefix}.subject_id", event.get("subject_id"), actor_id)
            compare(f"{prefix}.reason", event.get("reason"), "target:decision")
            compare(f"{prefix}.payload.actor_id", actor_id, request.get("actor_id") or "")
            compare(f"{prefix}.payload.action_id", action_id, request.get("action_id") or "")
            request_source = request.get("source") if isinstance(request.get("source"), dict) else {}
            compare(f"{prefix}.source", event.get("source"), request_source)

            resolved_targets = payload.get("resolved_target_ids")
            if not isinstance(resolved_targets, list):
                add_issue(f"{prefix}.payload.resolved_target_ids", "missing_resolved_target_ids_list", actual=resolved_targets, expected="list")
            decision = payload.get("decision")
            if not isinstance(decision, dict):
                add_issue(f"{prefix}.payload.decision", "missing_decision_dict", actual=decision, expected="dict")
            else:
                compare(f"{prefix}.payload.decision.stage", decision.get("stage"), stage)
                if isinstance(decision.get("resolved_target_ids"), list):
                    compare(f"{prefix}.payload.decision.resolved_target_ids", decision.get("resolved_target_ids"), resolved_targets)

            if issue_count == before_issue_count:
                target_decision_valid_count += 1
                if decision_index is not None:
                    target_decision_payloads_by_index[decision_index] = deepcopy(payload)
            continue

        if event_type == "action_defeat_credit":
            action_defeat_credit_count += 1
            before_issue_count = issue_count
            prefix = f"process_events[{event_index}]"
            payload = validate_payload_dict(prefix, event)
            if payload is None:
                continue
            target_id = str(payload.get("target_id") or "")
            source_id = payload.get("source_id")
            damage_kind = payload.get("damage_kind")
            if not target_id:
                add_issue(f"{prefix}.payload.target_id", "missing_target_id", actual=payload.get("target_id"), expected="non-empty string")
            compare(f"{prefix}.subject_id", event.get("subject_id"), target_id)
            compare(f"{prefix}.reason", event.get("reason"), "action:defeat_credit")
            if source_id is not None:
                compare(f"{prefix}.source.owner_id", (event.get("source") or {}).get("owner_id"), source_id)

            defeated_targets = payload.get("defeated_targets_this_action")
            if not isinstance(defeated_targets, list):
                add_issue(f"{prefix}.payload.defeated_targets_this_action", "missing_defeated_targets_list", actual=defeated_targets, expected="list")
            elif target_id and target_id not in {str(x) for x in defeated_targets}:
                add_issue(f"{prefix}.payload.defeated_targets_this_action", "target_missing_from_defeated_targets", actual=defeated_targets, expected=target_id)

            credits = payload.get("defeat_credits_this_action")
            if not isinstance(credits, dict):
                add_issue(f"{prefix}.payload.defeat_credits_this_action", "missing_defeat_credits_dict", actual=credits, expected="dict")
            else:
                credit = credits.get(target_id)
                if not isinstance(credit, dict):
                    add_issue(f"{prefix}.payload.defeat_credits_this_action.{target_id}", "missing_target_credit", actual=credit, expected="dict")
                else:
                    compare(f"{prefix}.payload.defeat_credits_this_action.{target_id}.source_id", credit.get("source_id"), source_id)
                    compare(f"{prefix}.payload.defeat_credits_this_action.{target_id}.damage_kind", credit.get("damage_kind"), damage_kind)

            alive_changes = [
                change for change in changes_by_sequence.values()
                if change.get("subject_id") == target_id
                and change.get("field_path") == "unit.alive"
                and change.get("old_value") is True
                and change.get("new_value") is False
            ]
            if not alive_changes:
                add_issue(f"{prefix}.state_changes.unit.alive", "missing_target_defeated_state_change", actual=None, expected=f"{target_id} unit.alive True->False")
            damage_changes = [
                change for change in changes_by_sequence.values()
                if change.get("subject_id") == target_id
                and change.get("field_path") == "unit.hp_or_shield"
            ]
            if not damage_changes:
                add_issue(f"{prefix}.state_changes.unit.hp_or_shield", "missing_target_damage_state_change", actual=None, expected=f"{target_id} damage state change")

            if issue_count == before_issue_count:
                action_defeat_credit_valid_count += 1
                if target_id:
                    defeat_credit_targets.add(target_id)
            continue

        if event_type == "derived_damage_target_skip":
            derived_damage_skip_count += 1
            before_issue_count = issue_count
            prefix = f"process_events[{event_index}]"
            payload = validate_payload_dict(prefix, event)
            if payload is None:
                continue
            target_id = validate_basic_target_payload(prefix, event, payload)
            reason = event.get("reason")
            if reason not in {"derived_damage:already_defeated_this_action", "derived_damage:not_alive"}:
                add_issue(f"{prefix}.reason", "unexpected_derived_damage_skip_reason", actual=reason, expected="derived damage skip reason")
            effect = payload.get("effect")
            if not isinstance(effect, str) or not effect:
                add_issue(f"{prefix}.payload.effect", "missing_effect_name", actual=effect, expected="non-empty string")

            if reason == "derived_damage:already_defeated_this_action":
                defeated_targets = payload.get("defeated_targets_this_action")
                if not isinstance(defeated_targets, list):
                    add_issue(f"{prefix}.payload.defeated_targets_this_action", "missing_defeated_targets_list", actual=defeated_targets, expected="list")
                elif target_id and target_id not in {str(x) for x in defeated_targets}:
                    add_issue(f"{prefix}.payload.defeated_targets_this_action", "target_missing_from_defeated_targets", actual=defeated_targets, expected=target_id)
                if target_id and target_id not in defeat_credit_targets:
                    add_issue(f"{prefix}.defeat_credit_order", "missing_prior_action_defeat_credit", actual=target_id, expected="prior valid action_defeat_credit in same transition")
                alive_changes = [
                    change for change in changes_by_sequence.values()
                    if change.get("subject_id") == target_id
                    and change.get("field_path") == "unit.alive"
                    and change.get("old_value") is True
                    and change.get("new_value") is False
                ]
                if not alive_changes:
                    add_issue(f"{prefix}.state_changes.unit.alive", "missing_target_defeated_state_change", actual=None, expected=f"{target_id} unit.alive True->False")
            elif reason == "derived_damage:not_alive":
                target_exists = payload.get("target_exists")
                if not isinstance(target_exists, bool):
                    add_issue(f"{prefix}.payload.target_exists", "missing_target_exists_bool", actual=target_exists, expected="bool")

            if issue_count == before_issue_count:
                derived_damage_skip_valid_count += 1
            continue

        if event_type == "phase_damage_lock":
            phase_damage_lock_count += 1
            before_issue_count = issue_count
            prefix = f"process_events[{event_index}]"
            payload = validate_payload_dict(prefix, event)
            if payload is None:
                continue
            target_id = validate_target_payload(prefix, event, payload)
            if event.get("reason") not in {"damage:phase_boundary_lock", "effect_damage:phase_boundary_lock"}:
                add_issue(f"{prefix}.reason", "unexpected_phase_damage_lock_reason", actual=event.get("reason"), expected="phase boundary lock reason")
            bars_depleted = payload.get("bars_depleted")
            if not isinstance(bars_depleted, int) or bars_depleted <= 0:
                add_issue(f"{prefix}.payload.bars_depleted", "invalid_bars_depleted", actual=bars_depleted, expected="positive int")
            hp_bars_remaining = payload.get("hp_bars_remaining")
            hp_bar_changes = [
                change for change in changes_by_sequence.values()
                if change.get("subject_id") == target_id
                and change.get("field_path") == "unit.hp_bars_remaining"
            ]
            matching_hp_bar_changes = [change for change in hp_bar_changes if _json_equal(change.get("new_value"), hp_bars_remaining)]
            if not matching_hp_bar_changes:
                add_issue(
                    f"{prefix}.state_changes.unit.hp_bars_remaining",
                    "missing_matching_hp_bar_state_change",
                    actual=hp_bars_remaining,
                    expected=f"{target_id} hp_bars_remaining new_value",
                )
            if issue_count == before_issue_count:
                phase_damage_lock_valid_count += 1
                if target_id:
                    phase_locked_targets.add(target_id)
            continue

        if event_type in {"damage_target_skip", "effect_damage_target_skip"}:
            phase_damage_skip_count += 1
            before_issue_count = issue_count
            prefix = f"process_events[{event_index}]"
            payload = validate_payload_dict(prefix, event)
            if payload is None:
                continue
            target_id = validate_target_payload(prefix, event, payload)
            expected_reason = "damage:phase_boundary_locked" if event_type == "damage_target_skip" else "effect_damage:phase_boundary_locked"
            compare(f"{prefix}.reason", event.get("reason"), expected_reason)
            if target_id and target_id not in phase_locked_targets:
                add_issue(f"{prefix}.phase_lock_order", "missing_prior_phase_damage_lock", actual=target_id, expected="prior phase_damage_lock in same transition")
            if event_type == "damage_target_skip" and not payload.get("packet_id"):
                add_issue(f"{prefix}.payload.packet_id", "missing_packet_id", actual=payload.get("packet_id"), expected="non-empty packet id")
            if event_type == "effect_damage_target_skip":
                effect = payload.get("effect")
                if not isinstance(effect, dict):
                    add_issue(f"{prefix}.payload.effect", "missing_effect_dict", actual=effect, expected="dict")
                else:
                    compare(f"{prefix}.payload.effect.type", effect.get("type"), "damage_unit")
            if issue_count == before_issue_count:
                phase_damage_skip_valid_count += 1
            continue

        timeline_tick_count += 1
        before_issue_count = issue_count
        prefix = f"process_events[{event_index}]"
        payload = validate_payload_dict(prefix, event)
        if payload is None:
            continue

        global_seq = _sequence_id(payload.get("global_state_change_sequence"))
        global_change = changes_by_sequence.get(global_seq or -1)
        if global_change is None:
            add_issue(
                f"{prefix}.payload.global_state_change_sequence",
                "missing_global_state_change",
                actual=payload.get("global_state_change_sequence"),
                expected="existing global.av state change sequence",
            )
        else:
            compare(f"{prefix}.payload.global.field_path", global_change.get("field_path"), "global.av")
            compare(f"{prefix}.payload.global.old_value", payload.get("old_global_av"), global_change.get("old_value"))
            compare(f"{prefix}.payload.global.new_value", payload.get("new_global_av"), global_change.get("new_value"))
            compare(f"{prefix}.payload.global.delta", payload.get("delta"), global_change.get("delta"))
            compare(f"{prefix}.reason", event.get("reason"), global_change.get("reason"))

        unit_rows = payload.get("unit_av_changes")
        if not isinstance(unit_rows, list):
            add_issue(f"{prefix}.payload.unit_av_changes", "missing_unit_av_changes_list", actual=unit_rows, expected="list")
            continue

        seen_unit_sequences: set[int] = set()
        for row_index, row in enumerate(unit_rows):
            row_prefix = f"{prefix}.payload.unit_av_changes[{row_index}]"
            if not isinstance(row, dict):
                add_issue(row_prefix, "non_dict_unit_av_change", actual=row, expected="dict")
                continue
            seq = _sequence_id(row.get("state_change_sequence"))
            if seq is None:
                add_issue(f"{row_prefix}.state_change_sequence", "missing_unit_state_change_sequence", actual=row.get("state_change_sequence"), expected="positive int")
                continue
            if seq in seen_unit_sequences:
                add_issue(f"{row_prefix}.state_change_sequence", "duplicate_unit_state_change_sequence", actual=seq, expected="unique sequence")
            seen_unit_sequences.add(seq)
            change = changes_by_sequence.get(seq)
            if change is None:
                add_issue(f"{row_prefix}.state_change_sequence", "missing_unit_state_change", actual=seq, expected="existing unit.remaining_av state change")
                continue
            compare(f"{row_prefix}.field_path", change.get("field_path"), "unit.remaining_av")
            compare(f"{row_prefix}.subject_id", row.get("unit_id"), change.get("subject_id"))
            compare(f"{row_prefix}.old_remaining_av", row.get("old_remaining_av"), change.get("old_value"))
            compare(f"{row_prefix}.new_remaining_av", row.get("new_remaining_av"), change.get("new_value"))
            compare(f"{row_prefix}.delta", row.get("delta"), change.get("delta"))
            compare(f"{row_prefix}.old_absolute_av", row.get("old_absolute_av"), absolute_av(payload.get("old_global_av"), row.get("old_remaining_av")))
            compare(f"{row_prefix}.new_absolute_av", row.get("new_absolute_av"), absolute_av(payload.get("new_global_av"), row.get("new_remaining_av")))

        if issue_count == before_issue_count:
            timeline_tick_valid_count += 1

    if latest_target_resolution_payload is not None:
        target_resolution = transition.get("target_resolution")
        if not isinstance(target_resolution, dict):
            add_issue("target_resolution", "missing_target_resolution", actual=target_resolution, expected="dict")
        else:
            compare("target_resolution.actor_id", target_resolution.get("actor_id"), latest_target_resolution_payload.get("actor_id"))
            compare("target_resolution.action_id", target_resolution.get("action_id"), latest_target_resolution_payload.get("action_id"))
            compare("target_resolution.requested_target_ids", target_resolution.get("requested_target_ids") or [], latest_target_resolution_payload.get("requested_target_ids") or [])
            compare("target_resolution.resolved_target_ids", target_resolution.get("resolved_target_ids") or [], latest_target_resolution_payload.get("resolved_target_ids") or [])
            compare("target_resolution.method", target_resolution.get("method"), latest_target_resolution_payload.get("method"))
            compare("target_resolution.reason", target_resolution.get("reason"), latest_target_resolution_payload.get("reason"))
            compare("target_resolution.source", target_resolution.get("source"), latest_target_resolution_payload.get("source"))

    if target_decision_count:
        target_resolution = transition.get("target_resolution")
        if not isinstance(target_resolution, dict):
            add_issue("target_resolution", "missing_target_resolution", actual=target_resolution, expected="dict")
        else:
            decision_trace = target_resolution.get("decision_trace")
            if not isinstance(decision_trace, list):
                add_issue("target_resolution.decision_trace", "missing_decision_trace_list", actual=decision_trace, expected="list")
            else:
                compare("target_resolution.decision_trace_count", len(decision_trace), target_decision_count)
                for decision_index, payload in sorted(target_decision_payloads_by_index.items()):
                    trace_index = decision_index - 1
                    if trace_index < 0 or trace_index >= len(decision_trace):
                        add_issue(
                            f"target_resolution.decision_trace[{trace_index}]",
                            "missing_matching_target_decision_trace",
                            actual=None,
                            expected=payload.get("decision"),
                        )
                        continue
                    compare(f"target_resolution.decision_trace[{trace_index}]", decision_trace[trace_index], payload.get("decision"))

    return {
        "process_event_count": len(events),
        "process_event_supported_count": supported_event_count,
        "process_event_unsupported_count": len(events) - supported_event_count,
        "process_event_unsupported_types": sorted(unsupported_types),
        "target_resolution_count": target_resolution_count,
        "target_resolution_valid_count": target_resolution_valid_count,
        "target_decision_count": target_decision_count,
        "target_decision_valid_count": target_decision_valid_count,
        "timeline_tick_count": timeline_tick_count,
        "timeline_tick_valid_count": timeline_tick_valid_count,
        "action_defeat_credit_count": action_defeat_credit_count,
        "action_defeat_credit_valid_count": action_defeat_credit_valid_count,
        "derived_damage_skip_count": derived_damage_skip_count,
        "derived_damage_skip_valid_count": derived_damage_skip_valid_count,
        "phase_damage_lock_count": phase_damage_lock_count,
        "phase_damage_lock_valid_count": phase_damage_lock_valid_count,
        "phase_damage_skip_count": phase_damage_skip_count,
        "phase_damage_skip_valid_count": phase_damage_skip_valid_count,
        "process_event_match": issue_count == 0,
        "process_event_mismatch_count": issue_count,
        "process_event_mismatches": issues,
    }


def _validate_damage_state_changes(transition: dict[str, Any], *, diff_limit: int = 20) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    issue_count = 0
    direct_damage_change_count = 0
    direct_damage_change_valid_count = 0
    direct_damage_formula_ledger_count = 0

    def add_issue(path: str, message: str, *, actual: Any = None, expected: Any = None) -> None:
        nonlocal issue_count
        issue_count += 1
        if len(issues) < diff_limit:
            issue = {"path": path, "message": message}
            if actual is not None or expected is not None:
                issue["actual"] = actual
                issue["expected"] = expected
            issues.append(issue)

    def compare(path: str, actual: Any, expected: Any) -> None:
        if not _json_equal(actual, expected):
            add_issue(path, "value_mismatch", actual=actual, expected=expected)

    for change_index, change in enumerate(transition.get("state_changes") or []):
        if not isinstance(change, dict):
            continue
        if change.get("change_type") != "damage" or change.get("field_path") != "unit.hp_or_shield":
            continue
        direct_damage_change_count += 1
        before_issue_count = issue_count
        prefix = f"state_changes[{change_index}]"
        payload = change.get("payload")
        if not isinstance(payload, dict):
            add_issue(f"{prefix}.payload", "missing_damage_payload_dict", actual=payload, expected="dict")
            continue

        target_id = str(payload.get("target_id") or "")
        actor_id = str(payload.get("actor_id") or "")
        source_action_id = str(payload.get("source_action_id") or "")
        damage_type = str(payload.get("damage_type") or "")
        if not target_id:
            add_issue(f"{prefix}.payload.target_id", "missing_target_id", actual=payload.get("target_id"), expected="non-empty string")
        if not actor_id:
            add_issue(f"{prefix}.payload.actor_id", "missing_actor_id", actual=payload.get("actor_id"), expected="non-empty string")
        if not source_action_id:
            add_issue(f"{prefix}.payload.source_action_id", "missing_source_action_id", actual=payload.get("source_action_id"), expected="non-empty string")
        if not damage_type:
            add_issue(f"{prefix}.payload.damage_type", "missing_damage_type", actual=payload.get("damage_type"), expected="non-empty string")
        compare(f"{prefix}.subject_id", change.get("subject_id"), target_id)
        compare(f"{prefix}.reason", change.get("reason"), damage_type)
        compare(f"{prefix}.source.owner_id", (change.get("source") or {}).get("owner_id"), actor_id)
        compare(f"{prefix}.source.source_id", (change.get("source") or {}).get("source_id"), source_action_id)

        damage_applied = payload.get("damage_applied")
        if not isinstance(damage_applied, (int, float)):
            add_issue(f"{prefix}.payload.damage_applied", "missing_numeric_damage_applied", actual=damage_applied, expected="number")
        else:
            compare(f"{prefix}.delta", change.get("delta"), -float(damage_applied))

        final_damage = payload.get("final_damage")
        if not isinstance(final_damage, (int, float)):
            add_issue(f"{prefix}.payload.final_damage", "missing_numeric_final_damage", actual=final_damage, expected="number")

        ledger = payload.get("formula_ledger")
        if not isinstance(ledger, dict) or not ledger:
            add_issue(f"{prefix}.payload.formula_ledger", "missing_formula_ledger_dict", actual=ledger, expected="non-empty dict")
        else:
            direct_damage_formula_ledger_count += 1
            compare(f"{prefix}.payload.formula_ledger.actor_id", ledger.get("actor_id"), actor_id)
            compare(f"{prefix}.payload.formula_ledger.target_id", ledger.get("target_id"), target_id)
            compare(f"{prefix}.payload.formula_ledger.action_id", ledger.get("action_id"), source_action_id)
            if payload.get("packet_id") or ledger.get("packet_id"):
                compare(f"{prefix}.payload.formula_ledger.packet_id", ledger.get("packet_id"), payload.get("packet_id"))
            if isinstance(final_damage, (int, float)) and isinstance(ledger.get("final_damage"), (int, float)):
                compare(f"{prefix}.payload.formula_ledger.final_damage", ledger.get("final_damage"), final_damage)
            if isinstance(payload.get("base_damage"), (int, float)) and isinstance(ledger.get("scaling"), dict):
                compare(f"{prefix}.payload.formula_ledger.scaling.base_damage", ledger.get("scaling", {}).get("base_damage"), payload.get("base_damage"))

        if issue_count == before_issue_count:
            direct_damage_change_valid_count += 1

    return {
        "direct_damage_change_count": direct_damage_change_count,
        "direct_damage_change_valid_count": direct_damage_change_valid_count,
        "direct_damage_formula_ledger_count": direct_damage_formula_ledger_count,
        "damage_record_match": issue_count == 0,
        "damage_record_mismatch_count": issue_count,
        "damage_record_mismatches": issues,
    }


def validate_transition_replay(transition: dict[str, Any], *, diff_limit: int = 20) -> dict[str, Any]:
    reduced = reduce_transition_snapshot(transition)
    if not reduced.get("ok"):
        return reduced
    after = transition.get("after_snapshot")
    if not isinstance(after, dict):
        return {k: v for k, v in reduced.items() if k != "snapshot"} | {"ok": False, "reason": "missing_after_snapshot"}
    snapshot = reduced["snapshot"]
    direct_mismatches = []
    for path in reduced.get("projection_paths") or []:
        actual = _projection(snapshot, path)
        expected = _projection(after, path)
        if not _json_equal(actual, expected):
            direct_mismatches.append({"path": path, "replayed": actual, "expected": expected})
            if len(direct_mismatches) >= diff_limit:
                break
    full_diffs = _first_diffs(snapshot, after, limit=diff_limit)
    result = {k: v for k, v in reduced.items() if k != "snapshot"}
    result.update(
        {
            "direct_match": not direct_mismatches,
            "full_match": not full_diffs,
            "direct_mismatch_count": len(direct_mismatches),
            "direct_mismatches": direct_mismatches[:diff_limit],
            "full_diff_count_sample": len(full_diffs),
            "full_diffs_sample": full_diffs[:diff_limit],
        }
    )
    process_validation = _validate_process_events(transition, diff_limit=diff_limit)
    result.update(process_validation)
    damage_validation = _validate_damage_state_changes(transition, diff_limit=diff_limit)
    result.update(damage_validation)
    result["ok"] = (
        result["direct_match"]
        and result["unsupported_count"] == 0
        and result["process_event_match"]
        and result["damage_record_match"]
    )
    return result
