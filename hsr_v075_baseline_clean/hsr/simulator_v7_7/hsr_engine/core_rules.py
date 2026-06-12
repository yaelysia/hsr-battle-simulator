from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional
import math

EPS = 1e-9


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def coerce_bool(value: Any, default: bool = False) -> bool:
    """Parse booleans safely from native YAML values, strings, and numbers."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "yes", "y", "1", "on"}:
            return True
        if text in {"false", "no", "n", "0", "off"}:
            return False
    return bool(value)


def normalize_str_list(value: Any) -> list[str]:
    """Return a list of strings without iterating scalar strings by character."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]
    return [str(value)]


def coerce_float(value: Any, default: float = 0.0) -> float:
    """Parse numeric model fields, including quoted numbers and percentages."""
    if value is None:
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return default
        if text.endswith("%"):
            return float(text[:-1].strip()) / 100.0
        lowered = text.lower()
        if lowered in {"inf", "infinite", "infinity", "∞"}:
            return math.inf
        return float(text)
    return float(value)


def maybe_float(value: Any) -> Optional[float]:
    try:
        return coerce_float(value)
    except (TypeError, ValueError):
        return None


def is_infinite_marker(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (int, float)):
        return math.isinf(float(value))
    if isinstance(value, str):
        return value.strip().lower() in {"infinite", "inf", "infinity", "∞", "none", "null"}
    return False


def coerce_numeric_value(value: Any) -> Any:
    parsed = maybe_float(value)
    return parsed if parsed is not None else value


def coerce_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    return int(coerce_float(value, float(default)))


def maybe_int(value: Any) -> Optional[int]:
    parsed = maybe_float(value)
    return int(parsed) if parsed is not None else None


def numeric_dict(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        parsed = maybe_float(v)
        if parsed is not None:
            out[str(k)] = parsed
    return out


def coerce_comparison_value(value: Any) -> Any:
    """Normalize common quoted booleans and numeric strings for conditions."""
    if isinstance(value, str):
        text = value.strip()
        lowered = text.lower()
        if lowered in {"true", "yes", "y", "1", "on"}:
            return True
        if lowered in {"false", "no", "n", "0", "off"}:
            return False
        parsed = maybe_float(text)
        if parsed is not None:
            return parsed
    return value


def normalize_flag_values(raw: Any) -> Any:
    """Recursively normalize generated YAML flag/checkpoint values."""
    if isinstance(raw, dict):
        return {k: normalize_flag_values(v) for k, v in raw.items()}
    if isinstance(raw, list):
        return [normalize_flag_values(v) for v in raw]
    return coerce_comparison_value(raw)


def normalize_effect_list(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [deepcopy(raw)]
    if isinstance(raw, list):
        return [deepcopy(e) for e in raw if isinstance(e, dict)]
    return []


def normalize_triggers(raw: Any) -> list[dict[str, Any]]:
    """Accept both simulator-list and model-pack dict trigger styles."""
    if raw is None:
        return []
    items = []
    if isinstance(raw, dict):
        for tid, trig in raw.items():
            if not isinstance(trig, dict):
                continue
            t = deepcopy(trig)
            t.setdefault("id", str(tid))
            items.append(t)
    elif isinstance(raw, list):
        for i, trig in enumerate(raw):
            if not isinstance(trig, dict):
                continue
            t = deepcopy(trig)
            t.setdefault("id", t.get("id", f"trigger_{i}"))
            items.append(t)
    else:
        return []
    out = []
    for t in items:
        if "effects" not in t and "effect" in t:
            t["effects"] = normalize_effect_list(t.get("effect"))
        elif "effects" in t:
            t["effects"] = normalize_effect_list(t.get("effects"))
        out.append(t)
    return out


def deep_get(obj: Any, path: str, default: Any = None) -> Any:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part, default)
        else:
            cur = getattr(cur, part, default)
        if cur is default:
            return default
    return cur
