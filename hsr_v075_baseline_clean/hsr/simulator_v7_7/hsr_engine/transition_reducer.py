"""Pure replay helpers for canonical action transitions.

The reducer works on the full-scene snapshot dictionaries emitted by the
simulator.  It intentionally reports unsupported paths instead of silently
pretending a transition is fully replayable.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


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


def _sync_hp_percent(entity: dict[str, Any]) -> None:
    resources = entity.setdefault("resources", {})
    max_hp = float(resources.get("max_hp") or 0.0)
    hp = float(resources.get("hp") or 0.0)
    resources["hp_percent"] = 0.0 if max_hp <= 0 else round(hp / max_hp, 6)


def _set_panel_number(entity: dict[str, Any], key: str, value: Any) -> None:
    panel = entity.setdefault("panel", {})
    if value is None or abs(float(value)) <= NUMERIC_TOLERANCE:
        panel.pop(key, None)
    else:
        panel[key] = round(float(value), 6)


def _sync_absolute_av(snapshot: dict[str, Any]) -> None:
    av = float((snapshot.get("global") or {}).get("av", 0.0))
    for rec in snapshot.get("action_axis", []) or []:
        if rec.get("remaining_av") is not None:
            rec["absolute_av"] = round(av + float(rec.get("remaining_av", 0.0)), 6)
    for group in ENTITY_GROUPS:
        for entity in snapshot.get(group, []) or []:
            axis = entity.get("action_axis")
            if isinstance(axis, dict) and axis.get("remaining_av") is not None:
                axis["absolute_av"] = round(av + float(axis.get("remaining_av", 0.0)), 6)


def _sort_axis(snapshot: dict[str, Any]) -> None:
    axis = snapshot.get("action_axis")
    if isinstance(axis, list):
        axis.sort(key=lambda r: (not bool(r.get("alive")), float(r.get("remaining_av") or 0.0), str(r.get("side") or ""), str(r.get("id") or "")))


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
        return "unsupported", field_path

    if scope != "unit":
        return "unsupported", field_path

    entity = _entity_record(snapshot, subject_id)
    if entity is None:
        return "unsupported", field_path

    if field_path in {"unit.hp", "unit.max_hp", "unit.shield", "unit.energy", "unit.toughness", "unit.max_toughness", "unit.is_broken", "unit.hp_bars_remaining"}:
        key = field_path.split(".", 1)[1]
        resources = entity.setdefault("resources", {})
        if key in {"hp", "max_hp", "shield", "energy", "toughness", "max_toughness"} and new_value is not None:
            value = round(float(new_value), 6)
        elif key in {"is_broken"}:
            value = bool(new_value)
        elif key in {"hp_bars_remaining"}:
            value = int(new_value)
        else:
            value = new_value
        resources[key] = value
        if key in {"hp", "max_hp"}:
            _set_panel_number(entity, key, value)
            _sync_hp_percent(entity)
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
        value = round(float(new_value), 6)
        entity.setdefault("action_axis", {})["remaining_av"] = value
        axis = _axis_record(snapshot, subject_id)
        if axis is not None:
            axis["remaining_av"] = value
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
            return "applied", field_path
        if status is None:
            return "unsupported", field_path
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
        else:
            return "unsupported", field_path
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
    result["ok"] = result["direct_match"] and result["unsupported_count"] == 0
    return result
