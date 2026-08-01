from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .immutable_json import FrozenJSONDict, freeze_json, thaw_json
from .model import BattleState, JSONValue
from .unit_state_codec import unit_state_to_payload


COMPACT_STATE_SCHEMA_VERSION = "p8_s19_compact_semantic_state_v2"

# These keys are provenance or derived report material. Runtime behavior must
# never depend on them; their full values remain available through audit_details.
AUDIT_ONLY_KEYS = frozenset(
    {
        "audit",
        "audit_detail",
        "audit_details",
        "audit_log",
        "coverage",
        "evidence",
        "provenance",
        "priority_audit",
        "raw_evidence",
        "settlement",
        "source_trace",
        "source_traces",
        "source_status_policy_source",
        "wait_policy_source",
        "retarget_policy_source",
        "priority_source_trace",
        "trace",
        "formal_build_manifest",
        "effective_skill_level_sources",
        "effective_skill_level_action_definitions",
        "owned_combatant_build_results",
        "character_resource_bindings",
        "damage_type_source",
        "avatar_base_type_source",
    }
)


@dataclass(frozen=True)
class CompactSemanticState:
    semantic_key: str
    _payload: FrozenJSONDict = field(repr=False)
    schema_version: str = COMPACT_STATE_SCHEMA_VERSION

    @property
    def byte_size(self) -> int:
        return len(_canonical_json_bytes(self._payload))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "schema_version": self.schema_version,
            "semantic_key": self.semantic_key,
            "payload": thaw_json(self._payload),
        }

    def payload_copy(self) -> dict[str, JSONValue]:
        """Return a detached copy; the stored semantic view stays immutable."""

        return thaw_json(self._payload)

    @classmethod
    def from_json(cls, value: dict[str, JSONValue]) -> "CompactSemanticState":
        if set(value) != {"schema_version", "semantic_key", "payload"}:
            raise ValueError("compact_state_fields_mismatch")
        if value.get("schema_version") != COMPACT_STATE_SCHEMA_VERSION:
            raise ValueError("compact_state_schema_version_unsupported")
        payload = value.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("compact_state_payload_missing")
        frozen = freeze_json(payload)
        if not isinstance(frozen, FrozenJSONDict):
            raise TypeError("compact state payload must be an object")
        expected_key = _semantic_key(frozen)
        supplied_key = str(value.get("semantic_key") or "")
        if supplied_key != expected_key:
            raise ValueError("compact_state_semantic_key_mismatch")
        return cls(semantic_key=expected_key, _payload=frozen)


class CompactStateQuery:
    """Read-only projection for search-tree identity, never a mutation API."""

    def project(self, state: BattleState) -> CompactSemanticState:
        payload = _semantic_payload(state)
        frozen = freeze_json(payload)
        if not isinstance(frozen, FrozenJSONDict):
            raise TypeError("compact semantic payload must be an object")
        return CompactSemanticState(semantic_key=_semantic_key(frozen), _payload=frozen)

    def audit_details(self, state: BattleState) -> dict[str, JSONValue]:
        """Expand the authoritative snapshot only when an audit consumer asks."""

        compact = self.project(state)
        return {
            "semantic_key": compact.semantic_key,
            "audit_materialization": "on_demand_full_snapshot",
            "snapshot": state.snapshot().to_json(),
        }


def _semantic_payload(state: BattleState) -> dict[str, JSONValue]:
    units = {
        unit_id: _compact_unit_payload(unit_state_to_payload(unit))
        for unit_id, unit in sorted(state.units.items())
    }
    queues = {
        name: _strip_audit_only(list(entries))
        for name, entries in sorted(state.queues.items())
    }
    raw_global_flags = dict(sorted(state.global_flags.items()))
    build_manifest_identity = _compact_build_manifest_identity(
        raw_global_flags.get("formal_build_manifest")
    )
    global_flags = _strip_audit_only(raw_global_flags)
    if not isinstance(global_flags, dict):
        raise TypeError("compact global flags must be an object")
    if build_manifest_identity is not None:
        global_flags["formal_build_manifest_identity"] = build_manifest_identity
    return {
        "state_schema": "battle_state_semantics_v1",
        "units": units,
        "wave_index": state.wave_index,
        "skill_points": state.skill_points,
        "max_skill_points": state.max_skill_points,
        "global_flags": global_flags,
        "queues": queues,
        "rng_state": state.rng_state,
        "event_index": state.event_index,
    }


def _compact_unit_payload(payload: dict[str, JSONValue]) -> JSONValue:
    copied = dict(payload)
    raw_flags = copied.get("flags")
    if isinstance(raw_flags, dict):
        flags = dict(raw_flags)
        raw_providers = flags.get("ability_providers")
        if isinstance(raw_providers, (list, tuple)):
            providers = tuple(
                _compact_provider_identity(item)
                for item in raw_providers
            )
            flags["ability_providers"] = list(
                sorted(providers, key=lambda item: str(item["provider_id"]))
            )
        copied["flags"] = flags
    return _strip_audit_only(copied)


def _compact_provider_identity(value: object) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        raise TypeError("compact state ability provider must be an object")
    required = (
        "provider_id",
        "selection_id",
        "owner_unit_id",
        "graph_ref_id",
    )
    if any(not isinstance(value.get(key), str) or not value.get(key) for key in required):
        raise ValueError("compact state ability provider identity is incomplete")
    return {key: str(value[key]) for key in required}


def _compact_build_manifest_identity(value: object) -> dict[str, JSONValue] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("formal build manifest must be an object")
    schema_version = value.get("schema_version")
    fingerprint = value.get("manifest_fingerprint")
    entries = value.get("entries")
    if (
        not isinstance(schema_version, str)
        or not schema_version
        or not _is_sha256(fingerprint)
        or not isinstance(entries, (list, tuple))
    ):
        raise ValueError("formal build manifest identity is incomplete")
    compact_entries: list[dict[str, JSONValue]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise TypeError("formal build manifest entry must be an object")
        build_input = entry.get("build_input")
        if not isinstance(build_input, dict):
            raise ValueError("formal build manifest entry identity is incomplete")
        unit_id = entry.get("unit_id")
        input_fingerprint = build_input.get("input_fingerprint")
        result_fingerprint = entry.get("result_fingerprint")
        equipment_result_fingerprint = entry.get("equipment_result_fingerprint")
        if (
            not isinstance(unit_id, str)
            or not unit_id
            or not _is_sha256(input_fingerprint)
            or not _is_sha256(result_fingerprint)
            or not _is_sha256(equipment_result_fingerprint)
        ):
            raise ValueError("formal build manifest entry fingerprint is incomplete")
        compact_entries.append(
            {
                "unit_id": unit_id,
                "input_fingerprint": input_fingerprint,
                "result_fingerprint": result_fingerprint,
                "equipment_result_fingerprint": equipment_result_fingerprint,
            }
        )
    return {
        "schema_version": schema_version,
        "manifest_fingerprint": fingerprint,
        "entries": sorted(compact_entries, key=lambda item: str(item["unit_id"])),
    }


def _is_sha256(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _strip_audit_only(value: Any) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_strip_audit_only(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _strip_audit_only(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in AUDIT_ONLY_KEYS
        }
    raise TypeError(f"compact state encountered non-JSON value: {type(value).__name__}")


def _semantic_key(payload: FrozenJSONDict) -> str:
    return "compact:" + hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        thaw_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
