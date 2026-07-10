from __future__ import annotations

import math
from typing import Any

from .immutable_json import thaw_json
from .model import JSONValue, UnitState


UNIT_STATE_FLOAT_FIELDS = frozenset(
    {
        "max_hp",
        "hp",
        "attack",
        "defense",
        "speed",
        "energy",
        "max_energy",
        "toughness",
        "max_toughness",
        "action_value",
    }
)
UNIT_STATE_PAYLOAD_FIELDS = frozenset(
    {"unit_id", "side", "template_id", "level", *UNIT_STATE_FLOAT_FIELDS, "statuses", "flags", "resources"}
)
UNIT_STATE_MUTABLE_FIELDS = frozenset({"level", *UNIT_STATE_FLOAT_FIELDS, "statuses", "flags", "resources"})


def unit_state_to_payload(unit: UnitState) -> dict[str, JSONValue]:
    flags = thaw_json(unit.flags)
    if not isinstance(flags, dict):
        raise ValueError("unit state flags must be a JSON object")
    resources = {
        key: _finite_number(value, f"resources.{key}")
        for key, value in unit.resources.items()
        if isinstance(key, str)
    }
    if len(resources) != len(unit.resources):
        raise ValueError("unit state resource keys must be strings")
    payload: dict[str, JSONValue] = {
        "unit_id": unit.unit_id,
        "side": unit.side,
        "template_id": unit.template_id,
        "level": unit.level,
        **{field_name: _finite_number(getattr(unit, field_name), field_name) for field_name in UNIT_STATE_FLOAT_FIELDS},
        "statuses": list(unit.statuses),
        "flags": flags,
        "resources": resources,
    }
    _validate_payload_identity(payload)
    _validate_unit_values(payload)
    return payload


def unit_state_from_payload(payload: Any) -> UnitState:
    raw = thaw_json(payload)
    if not isinstance(raw, dict):
        raise ValueError("unit state payload must be a JSON object")
    if set(raw) != UNIT_STATE_PAYLOAD_FIELDS:
        missing = sorted(UNIT_STATE_PAYLOAD_FIELDS - set(raw))
        extra = sorted(set(raw) - UNIT_STATE_PAYLOAD_FIELDS)
        raise ValueError(f"unit state payload fields mismatch: missing={missing}, extra={extra}")
    _validate_payload_identity(raw)
    _validate_unit_values(raw)
    statuses = raw["statuses"]
    flags = raw["flags"]
    resources = raw["resources"]
    assert isinstance(statuses, list)
    assert isinstance(flags, dict)
    assert isinstance(resources, dict)
    return UnitState(
        unit_id=raw["unit_id"],
        side=raw["side"],  # type: ignore[arg-type]
        template_id=raw["template_id"],
        level=raw["level"],
        **{field_name: _finite_number(raw[field_name], field_name) for field_name in UNIT_STATE_FLOAT_FIELDS},
        statuses=tuple(statuses),
        flags=flags,
        resources={key: _finite_number(value, f"resources.{key}") for key, value in resources.items()},
    )


def validate_canonical_unit_field_value(field_name: str, value: Any) -> None:
    if field_name not in UNIT_STATE_MUTABLE_FIELDS:
        raise ValueError(f"unsupported mutable unit field {field_name!r}")
    if field_name == "level":
        if type(value) is not int:
            raise ValueError("unit level must be an int")
        return
    if field_name in UNIT_STATE_FLOAT_FIELDS:
        if type(value) is not float or not math.isfinite(value):
            raise ValueError(f"unit field {field_name} must be a finite float")
        return
    if field_name == "statuses":
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("unit statuses must be a list of strings")
        return
    if field_name == "flags":
        if not isinstance(thaw_json(value), dict):
            raise ValueError("unit flags must be a JSON object")
        return
    if field_name == "resources":
        resources = thaw_json(value)
        if not isinstance(resources, dict) or not all(
            isinstance(key, str) and type(item) is float and math.isfinite(item)
            for key, item in resources.items()
        ):
            raise ValueError("unit resources must contain finite float values")


def _validate_payload_identity(payload: dict[str, Any]) -> None:
    if not isinstance(payload.get("unit_id"), str) or not payload["unit_id"]:
        raise ValueError("unit state payload requires a non-empty unit_id")
    if payload.get("side") not in {"ally", "enemy", "summon"}:
        raise ValueError("unit state payload requires a supported side")
    if not isinstance(payload.get("template_id"), str) or not payload["template_id"]:
        raise ValueError("unit state payload requires a non-empty template_id")
    if type(payload.get("level")) is not int or payload["level"] <= 0:
        raise ValueError("unit state payload level must be a positive int")


def _validate_unit_values(payload: dict[str, Any]) -> None:
    values = {field_name: _finite_number(payload.get(field_name), field_name) for field_name in UNIT_STATE_FLOAT_FIELDS}
    if values["max_hp"] <= 0 or values["hp"] < 0 or values["hp"] > values["max_hp"]:
        raise ValueError("unit state payload hp range is invalid")
    if values["speed"] <= 0:
        raise ValueError("unit state payload speed must be positive")
    if values["energy"] < 0 or values["max_energy"] < 0:
        raise ValueError("unit state payload energy must be non-negative")
    if values["max_energy"] and values["energy"] > values["max_energy"]:
        raise ValueError("unit state payload energy exceeds max_energy")
    if values["toughness"] < 0 or values["max_toughness"] < 0:
        raise ValueError("unit state payload toughness must be non-negative")
    if values["toughness"] > values["max_toughness"]:
        raise ValueError("unit state payload toughness exceeds max_toughness")
    if values["action_value"] < 0:
        raise ValueError("unit state payload action_value must be non-negative")
    statuses = payload.get("statuses")
    if not isinstance(statuses, list) or not all(isinstance(item, str) for item in statuses):
        raise ValueError("unit state payload statuses must be a list of strings")
    if not isinstance(payload.get("flags"), dict):
        raise ValueError("unit state payload flags must be a JSON object")
    resources = payload.get("resources")
    if not isinstance(resources, dict) or not all(
        isinstance(key, str) and not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
        for key, value in resources.items()
    ):
        raise ValueError("unit state payload resources must contain finite numbers")


def _finite_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"unit state payload {field_name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"unit state payload {field_name} must be finite")
    return number
