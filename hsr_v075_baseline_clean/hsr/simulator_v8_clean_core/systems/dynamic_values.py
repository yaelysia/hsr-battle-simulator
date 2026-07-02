from __future__ import annotations

import hashlib
import json
from typing import Any

from ..core.model import BattleState, JSONValue
from ..rules.rulebook import RuleBook


def empty_dynamic_value_store() -> dict[str, JSONValue]:
    return {"entries": {}, "by_hash": {}, "by_name": {}}


def normalized_dynamic_value_store(value: object) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        return empty_dynamic_value_store()
    entries = value.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    normalized_entries: dict[str, JSONValue] = {}
    for key, item in entries.items():
        if isinstance(item, dict) and isinstance(item.get("value"), (int, float)):
            normalized_entries[str(key)] = {
                **item,
                "value": float(item["value"]),
            }
    return _reindex({"entries": normalized_entries})


def store_from_state(state: BattleState) -> dict[str, JSONValue]:
    return normalized_dynamic_value_store(state.global_flags.get("dynamic_value_store"))


def binding_source_from_store(store: object) -> dict[str, JSONValue]:
    normalized = normalized_dynamic_value_store(store)
    return {
        "source_type": "dynamic_value_store",
        "entries": normalized["entries"],
        "by_hash": normalized["by_hash"],
        "by_name": normalized["by_name"],
    }


def upsert_dynamic_value(
    store: object,
    *,
    scope: str,
    owner_id: str,
    value: float,
    value_name: str | None = None,
    hash_key: str | int | None = None,
    status_id: str | None = None,
    status_instance_id: str | None = None,
    effect_id: str | None = None,
    source_trace: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    normalized = normalized_dynamic_value_store(store)
    entries = dict(normalized["entries"]) if isinstance(normalized.get("entries"), dict) else {}
    entry = {
        "scope": scope,
        "owner_id": owner_id,
        "status_id": status_id,
        "status_instance_id": status_instance_id,
        "effect_id": effect_id,
        "name": value_name,
        "hash": str(hash_key) if hash_key is not None else None,
        "value": float(value),
        "source_trace": source_trace or {},
    }
    entries[_entry_key(entry)] = entry
    return _reindex({"entries": entries})


def status_binding_sources(state: BattleState, unit_ids: tuple[str, ...]) -> tuple[dict[str, JSONValue], ...]:
    sources: list[dict[str, JSONValue]] = []
    seen: set[str] = set()
    for unit_id in unit_ids:
        if unit_id in seen:
            continue
        seen.add(unit_id)
        unit = state.units.get(unit_id)
        if unit is None:
            continue
        details = unit.flags.get("status_details", ())
        if not isinstance(details, (list, tuple)):
            continue
        for detail in details:
            if not isinstance(detail, dict):
                continue
            dynamic_values = detail.get("dynamic_values")
            source = binding_source_from_status_detail(detail, dynamic_values)
            if source is not None:
                sources.append(source)
    return tuple(sources)


def character_skill_param_binding_sources(
    rules: RuleBook,
    state: BattleState,
    unit_ids: tuple[str, ...],
    *,
    action_level: int | None = None,
    current_action_trigger_key: str | None = None,
) -> tuple[dict[str, JSONValue], ...]:
    sources: list[dict[str, JSONValue]] = []
    seen: set[str] = set()
    for unit_id in unit_ids:
        if unit_id in seen:
            continue
        seen.add(unit_id)
        unit = state.units.get(unit_id)
        if unit is None:
            continue
        source = character_skill_param_binding_source(
            rules,
            state,
            unit_id,
            action_level=action_level,
            current_action_trigger_key=current_action_trigger_key,
        )
        if source is not None:
            sources.append(source)
    return tuple(sources)


def character_skill_param_binding_source(
    rules: RuleBook,
    state: BattleState,
    unit_id: str,
    *,
    action_level: int | None = None,
    current_action_trigger_key: str | None = None,
) -> dict[str, JSONValue] | None:
    unit = state.units.get(unit_id)
    if unit is None:
        return None
    card_id = unit.flags.get("character_data_card_id")
    card = rules.character_data_card(str(card_id)) if isinstance(card_id, str) and card_id else None
    if card is None:
        card = rules.character_data_card_for_entity(unit.template_id)
    if card is None:
        return None
    config_bindings = card.source.evidence.get("character_config_dynamic_value_bindings")
    if not isinstance(config_bindings, dict):
        return None
    by_hash = config_bindings.get("by_hash")
    if not isinstance(by_hash, dict):
        return None

    skill_levels_by_trigger_key = unit.flags.get("skill_levels_by_trigger_key")
    if not isinstance(skill_levels_by_trigger_key, dict):
        skill_levels_by_trigger_key = {}
    param_slots = tuple(
        slot
        for slot in rules.character_mechanism_slots_for_card(card.card_id)
        if slot.mechanism_kind == "skill_param_slot" and slot.coverage_status == "executable"
    )
    entries: dict[str, JSONValue] = {}
    for raw_hash, binding in by_hash.items():
        if not isinstance(binding, dict):
            continue
        read_info = binding.get("read_info")
        if not isinstance(read_info, dict):
            continue
        if read_info.get("Type") != "SkillParam":
            continue
        trigger_key = read_info.get("TriggerKey")
        param_index = read_info.get("Index")
        if not isinstance(trigger_key, str) or not isinstance(param_index, int):
            continue
        selected_level, level_source = _skill_param_level_for_trigger(
            trigger_key,
            action_level=action_level,
            current_action_trigger_key=current_action_trigger_key,
            skill_levels_by_trigger_key=skill_levels_by_trigger_key,
        )
        if selected_level is None:
            continue
        slot = _select_skill_param_slot(param_slots, trigger_key, param_index, selected_level)
        if slot is None:
            continue
        value = _slot_param_value(slot)
        if value is None:
            continue
        entry = {
            "scope": "character_skill_param",
            "owner_id": unit_id,
            "status_id": None,
            "status_instance_id": None,
            "effect_id": None,
            "name": None,
            "hash": str(raw_hash),
            "value": value,
            "source_trace": {
                "character_data_card_id": card.card_id,
                "character_data_card_source": card.source.to_json(),
                "skill_param_slot_id": slot.mechanism_slot_id,
                "skill_param_slot_source": slot.source.to_json(),
                "dynamic_value_binding": binding,
                "skill_level": selected_level,
                "skill_level_source": level_source,
            },
        }
        entries[_entry_key(entry)] = entry
    if not entries:
        return None
    indexed = _reindex({"entries": entries})
    return {
        "source_type": "character_skill_param_slot",
        "unit_id": unit_id,
        "character_data_card_id": card.card_id,
        "entries": indexed["entries"],
        "by_hash": indexed["by_hash"],
        "by_name": indexed["by_name"],
    }


def _skill_param_level_for_trigger(
    trigger_key: str,
    *,
    action_level: int | None,
    current_action_trigger_key: str | None,
    skill_levels_by_trigger_key: dict[object, object],
) -> tuple[int | None, str]:
    configured_level = skill_levels_by_trigger_key.get(trigger_key)
    if isinstance(configured_level, int):
        return configured_level, "unit.skill_levels_by_trigger_key"
    if trigger_key == current_action_trigger_key and isinstance(action_level, int):
        return action_level, "current_action_level"
    return None, "skill_level_missing_for_trigger_key"


def _select_skill_param_slot(
    slots: tuple[Any, ...],
    trigger_key: str,
    param_index: int,
    action_level: int,
) -> Any | None:
    matches = [
        slot
        for slot in slots
        if slot.semantics.get("skill_trigger_key") == trigger_key
        and slot.semantics.get("param_index") == param_index
    ]
    if not matches:
        return None
    level_matches = [slot for slot in matches if slot.semantics.get("level") == action_level]
    if not level_matches:
        return None
    return sorted(level_matches, key=lambda item: str(item.mechanism_slot_id))[0]


def _slot_param_value(slot: Any) -> float | None:
    value = slot.semantics.get("param_value")
    if isinstance(value, dict):
        value = value.get("Value")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def binding_source_from_status_detail(
    detail: dict[str, Any],
    dynamic_values: object,
) -> dict[str, JSONValue] | None:
    entries: dict[str, JSONValue] = {}
    source_trace = detail.get("source_trace", {})
    owner_id = str(detail.get("owner_id") or "")
    status_id = str(detail.get("status_id") or "")
    status_instance_id = str(detail.get("instance_id") or "")
    stacks = detail.get("stacks")
    if isinstance(stacks, (int, float)) and not isinstance(stacks, bool):
        for key in ("Layer", "layer", "stacks"):
            entry = {
                "scope": "status_layer",
                "owner_id": owner_id,
                "status_id": status_id,
                "status_instance_id": status_instance_id,
                "name": key,
                "hash": key,
                "value": float(stacks),
                "source_trace": source_trace,
            }
            entries[_entry_key(entry)] = entry
    if isinstance(dynamic_values, dict):
        for key, value in dynamic_values.items():
            if key.startswith("__") or not isinstance(value, (int, float)):
                continue
            entry = {
                "scope": "status",
                "owner_id": owner_id,
                "status_id": status_id,
                "status_instance_id": status_instance_id,
                "name": str(key),
                "hash": str(key),
                "value": float(value),
                "source_trace": source_trace,
            }
            entries[_entry_key(entry)] = entry
        by_hash = dynamic_values.get("__by_hash")
        if isinstance(by_hash, dict):
            for key, value in by_hash.items():
                if not isinstance(value, (int, float)):
                    continue
                entry = {
                    "scope": "status",
                    "owner_id": owner_id,
                    "status_id": status_id,
                    "status_instance_id": status_instance_id,
                    "name": None,
                    "hash": str(key),
                    "value": float(value),
                    "source_trace": source_trace,
                }
                entries[_entry_key(entry)] = entry
    if not entries:
        return None
    indexed = _reindex({"entries": entries})
    return {
        "source_type": "status_instance",
        "status_instance_id": str(detail.get("instance_id") or ""),
        "status_id": str(detail.get("status_id") or ""),
        "entries": indexed["entries"],
        "by_hash": indexed["by_hash"],
        "by_name": indexed["by_name"],
    }


def find_status_detail(
    state: BattleState,
    unit_id: str,
    modifier_name: str | None = None,
    status_id: str | None = None,
) -> dict[str, JSONValue] | None:
    unit = state.units.get(unit_id)
    if unit is None:
        return None
    details = unit.flags.get("status_details", ())
    if not isinstance(details, (list, tuple)):
        return None
    expected_status_id = status_id or (f"modifier:{modifier_name}" if modifier_name else None)
    for detail in details:
        if not isinstance(detail, dict):
            continue
        if expected_status_id is not None and detail.get("status_id") == expected_status_id:
            return detail
        if modifier_name is not None and detail.get("modifier_name") == modifier_name:
            return detail
    return None


def _entry_key(entry: dict[str, Any]) -> str:
    payload = {
        "scope": entry.get("scope"),
        "owner_id": entry.get("owner_id"),
        "status_id": entry.get("status_id"),
        "status_instance_id": entry.get("status_instance_id"),
        "effect_id": entry.get("effect_id"),
        "name": entry.get("name"),
        "hash": entry.get("hash"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "dyn:" + hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:16]


def _reindex(store: dict[str, JSONValue]) -> dict[str, JSONValue]:
    entries = store.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    by_hash: dict[str, list[str]] = {}
    by_name: dict[str, list[str]] = {}
    for key, item in entries.items():
        if not isinstance(item, dict):
            continue
        hash_key = item.get("hash")
        if isinstance(hash_key, str) and hash_key:
            by_hash.setdefault(hash_key, []).append(str(key))
        name = item.get("name")
        if isinstance(name, str) and name:
            by_name.setdefault(name, []).append(str(key))
    return {
        "entries": dict(sorted(entries.items())),
        "by_hash": {key: value for key, value in sorted(by_hash.items())},
        "by_name": {key: value for key, value in sorted(by_name.items())},
    }
