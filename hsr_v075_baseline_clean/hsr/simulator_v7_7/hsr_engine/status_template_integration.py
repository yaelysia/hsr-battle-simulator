from __future__ import annotations

"""Integrate compiled StatusTemplate bundles into simulator cases.

This module is the boundary between generated compiler output and the battle
kernel input format.  It does not interpret TurnBasedGameData; it only maps
already-canonical status templates/triggers into a case's status definitions and
trigger list.
"""

from copy import deepcopy
from pathlib import Path
from typing import Any
import json
import re

from .schema_normalizer import normalize_status_def
from .core_rules import normalize_triggers


class StatusTemplateIntegrationError(RuntimeError):
    pass


RANK_ID_RE = re.compile(r"(?:^|_)(?:Rank|Rank0)(?P<rank>[1-6])(?:_|$)")


def parse_owner_rank_map(raw: Any) -> dict[int, int]:
    """Parse avatar-id -> active eidolon/rank from a dict/JSON object.

    The same JSON object used by parse_owner_unit_map may provide nested values,
    e.g. {"1102": {"unit_id": "seele", "rank": 3}}.
    """
    if raw in (None, ""):
        return {}
    data = raw
    if isinstance(raw, (str, Path)):
        text = str(raw)
        path = Path(text)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = json.loads(text)
    if not isinstance(data, dict):
        raise StatusTemplateIntegrationError("owner rank map must be a JSON object")
    out: dict[int, int] = {}
    for k, v in data.items():
        try:
            aid = int(k)
        except Exception as exc:
            raise StatusTemplateIntegrationError(f"owner rank map key is not an avatar id: {k!r}") from exc
        rank = None
        if isinstance(v, dict):
            rank = v.get("rank", v.get("eidolon", v.get("eidolons")))
        elif isinstance(v, (int, float)):
            rank = v
        if rank is None:
            continue
        try:
            out[aid] = int(rank)
        except Exception as exc:
            raise StatusTemplateIntegrationError(f"owner rank for avatar {aid} is not numeric: {rank!r}") from exc
    return out


def _required_rank_from_text(text: Any) -> int | None:
    if not isinstance(text, str):
        return None
    m = RANK_ID_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group("rank"))
    except Exception:
        return None


def _rank_active(status_or_trigger: dict[str, Any], owner_rank_map: dict[int, int]) -> tuple[bool, str | None]:
    try:
        aid = int(status_or_trigger.get("owner_avatar_id"))
    except Exception:
        return True, None
    required = None
    for key in ("status_id", "id", "source_trigger_id"):
        required = _required_rank_from_text(status_or_trigger.get(key))
        if required is not None:
            break
    if required is None:
        return True, None
    if aid not in owner_rank_map:
        return False, f"rank_gated_status_without_owner_rank:requires_{required}"
    active_rank = owner_rank_map[aid]
    if active_rank >= required:
        return True, None
    return False, f"rank_gated_status_inactive:requires_{required}_has_{active_rank}"


def load_status_template_bundle(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise StatusTemplateIntegrationError(f"Failed to read status template bundle {p}: {exc}") from exc
    if not isinstance(data, dict) or data.get("format") != "hsr_status_template_bundle":
        raise StatusTemplateIntegrationError(f"Not a hsr_status_template_bundle: {p}")
    return data


def parse_owner_unit_map(raw: Any) -> dict[int, str]:
    """Parse an avatar-id -> unit-id map from dict, JSON string, or JSON path."""
    if raw in (None, ""):
        return {}
    data = raw
    if isinstance(raw, (str, Path)):
        text = str(raw)
        path = Path(text)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = json.loads(text)
    if not isinstance(data, dict):
        raise StatusTemplateIntegrationError("owner map must be a JSON object mapping avatar ids to unit ids")
    out: dict[int, str] = {}
    for k, v in data.items():
        try:
            aid = int(k)
        except Exception as exc:
            raise StatusTemplateIntegrationError(f"owner map key is not an avatar id: {k!r}") from exc
        if v is None:
            continue
        if isinstance(v, dict):
            unit_id = v.get("unit_id", v.get("unit", v.get("owner_id")))
            if unit_id is None:
                continue
            out[aid] = str(unit_id)
        else:
            out[aid] = str(v)
    return out


def _status_template_to_def(template: dict[str, Any]) -> dict[str, Any]:
    status_id = str(template.get("id") or template.get("status_id"))
    raw = {
        "id": status_id,
        "tags": deepcopy(template.get("tags", [])),
        "stack_rule": deepcopy(template.get("stack_rule", {})),
    }
    if template.get("max_stacks") is not None:
        raw["max_stacks"] = template.get("max_stacks")
    if isinstance(template.get("duration"), dict):
        raw["duration"] = deepcopy(template["duration"])
    if isinstance(template.get("modifiers"), dict):
        raw["modifiers"] = deepcopy(template["modifiers"])
    return normalize_status_def(raw, status_id)


def compile_case_status_template_import(
    bundle: dict[str, Any],
    owner_unit_map: dict[int, str] | None = None,
    *,
    owner_rank_map: dict[int, int] | None = None,
    executable_only: bool = True,
) -> dict[str, Any]:
    """Return case-level status definitions and triggers from a compiled bundle."""
    owner_unit_map = owner_unit_map or {}
    owner_rank_map = owner_rank_map or {}
    status_effects: dict[str, dict[str, Any]] = {}
    skipped_triggers: list[dict[str, Any]] = []
    imported_triggers: list[dict[str, Any]] = []

    templates = bundle.get("status_templates") or {}
    skipped_statuses: list[dict[str, Any]] = []
    if isinstance(templates, dict):
        for sid, tmpl in templates.items():
            if isinstance(tmpl, dict):
                active, reason = _rank_active({**tmpl, "id": tmpl.get("id", sid), "status_id": tmpl.get("id", sid)}, owner_rank_map)
                if not active:
                    skipped_statuses.append({"id": str(sid), "reason": reason})
                    continue
                status_effects[str(sid)] = _status_template_to_def({**tmpl, "id": tmpl.get("id", sid)})
    elif isinstance(templates, list):
        for tmpl in templates:
            if isinstance(tmpl, dict):
                sid = str(tmpl.get("id") or tmpl.get("status_id"))
                active, reason = _rank_active({**tmpl, "status_id": sid}, owner_rank_map)
                if not active:
                    skipped_statuses.append({"id": sid, "reason": reason})
                    continue
                status_effects[sid] = _status_template_to_def(tmpl)

    for trig in bundle.get("triggers", []) or []:
        if not isinstance(trig, dict):
            continue
        if executable_only and not trig.get("executable"):
            continue
        aid_raw = trig.get("owner_avatar_id")
        try:
            aid = int(aid_raw)
        except Exception:
            skipped_triggers.append({"id": trig.get("id"), "reason": "missing_owner_avatar_id", "owner_avatar_id": aid_raw})
            continue
        active, rank_reason = _rank_active(trig, owner_rank_map)
        if not active:
            skipped_triggers.append({"id": trig.get("id"), "reason": rank_reason, "owner_avatar_id": aid})
            continue
        owner_id = owner_unit_map.get(aid)
        if not owner_id:
            skipped_triggers.append({"id": trig.get("id"), "reason": "owner_avatar_unmapped", "owner_avatar_id": aid})
            continue
        rt = deepcopy(trig)
        rt.setdefault("id", trig.get("id") or f"compiled_status_trigger_{len(imported_triggers)}")
        rt["owner"] = owner_id
        rt["owner_id"] = owner_id
        rt["source_unit"] = owner_id
        rt["source"] = "compiled_status_template"
        # Runtime triggers do not need compiler audit fields.
        rt.pop("executable", None)
        rt.pop("unsupported_reasons", None)
        imported_triggers.append(rt)

    return {
        "status_effects": status_effects,
        "triggers": normalize_triggers(imported_triggers),
        "summary": {
            "status_effect_count": len(status_effects),
            "imported_trigger_count": len(imported_triggers),
            "skipped_trigger_count": len(skipped_triggers),
            "skipped_status_count": len(skipped_statuses),
            "skipped_triggers": skipped_triggers[:20],
            "skipped_statuses": skipped_statuses[:20],
        },
    }


def attach_status_template_bundle_to_case(
    case: dict[str, Any],
    bundle: dict[str, Any],
    owner_unit_map: dict[int, str] | None = None,
    *,
    owner_rank_map: dict[int, int] | None = None,
    executable_only: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a copy of case with compiled status templates merged in."""
    merged = deepcopy(case or {})
    compiled = compile_case_status_template_import(bundle, owner_unit_map, owner_rank_map=owner_rank_map, executable_only=executable_only)
    merged.setdefault("status_effects", {})
    if not isinstance(merged["status_effects"], dict):
        merged["status_effects"] = {}
    merged["status_effects"].update(compiled["status_effects"])
    merged.setdefault("triggers", [])
    if not isinstance(merged["triggers"], list):
        merged["triggers"] = []
    merged["triggers"].extend(compiled["triggers"])
    # Expose active rank/eidolon to runtime predicates such as owner.rank.
    # This stays at the integration boundary: the kernel only reads normalized
    # unit flags and never consumes raw TBGD rank hashes.
    if owner_rank_map and isinstance(merged.get("units"), dict):
        for aid, rank in owner_rank_map.items():
            unit_id = (owner_unit_map or {}).get(aid)
            if unit_id and unit_id in merged["units"] and isinstance(merged["units"][unit_id], dict):
                merged["units"][unit_id].setdefault("flags", {})
                if isinstance(merged["units"][unit_id]["flags"], dict):
                    merged["units"][unit_id]["flags"].setdefault("rank", int(rank))
                    merged["units"][unit_id]["flags"].setdefault("eidolon", int(rank))
    merged.setdefault("metadata", {})
    if isinstance(merged["metadata"], dict):
        merged["metadata"]["compiled_status_template_import"] = compiled["summary"]
    return merged, compiled["summary"]
