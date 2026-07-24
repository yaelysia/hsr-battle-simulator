from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..core.model import JSONValue, UnitState
from ..unit_eligibility import runtime_unit_combat_team


SUMMON_RUNTIME_SCHEMA_VERSION = "p3_summon_runtime_v2"
LEGACY_SUMMON_RUNTIME_SCHEMA_VERSION = "p1_3_summon_runtime_v1"
SUPPORTED_SUMMON_RUNTIME_SCHEMA_VERSIONS = {
    SUMMON_RUNTIME_SCHEMA_VERSION,
    LEGACY_SUMMON_RUNTIME_SCHEMA_VERSION,
}

_REQUIRED_MAPPING_FIELDS = (
    "schema_boundary",
    "entities",
    "by_owner",
    "by_unique_group",
    "servants",
)
_REQUIRED_LIST_FIELDS = (
    "last_summon_monsters",
    "last_servants",
    "assistant_history",
    "blocked",
)


@dataclass(frozen=True)
class SummonRuntimeValidation:
    ok: bool
    reason: str = ""


def empty_summon_runtime() -> dict[str, JSONValue]:
    """Return the one canonical empty runtime used by formal state builders."""

    return {
        "schema_version": SUMMON_RUNTIME_SCHEMA_VERSION,
        "schema_boundary": {
            "version": SUMMON_RUNTIME_SCHEMA_VERSION,
            "forward_boundary": (
                "p3 runtime registry keeps removed records for audit and may "
                "add optional indexes without changing mutation semantics."
            ),
            "previous_schema_versions": [LEGACY_SUMMON_RUNTIME_SCHEMA_VERSION],
        },
        "entities": {},
        "by_owner": {},
        "by_unique_group": {},
        "last_summon_monsters": [],
        "last_servants": [],
        "servants": {},
        "assistant_history": [],
        "blocked": [],
    }


def validate_summon_runtime(
    value: JSONValue,
    *,
    units: Mapping[str, UnitState] | None = None,
) -> SummonRuntimeValidation:
    """Validate the current runtime without repairing or defaulting any field."""

    if not isinstance(value, dict):
        return SummonRuntimeValidation(False, "summon_runtime_missing")
    if value.get("schema_version") != SUMMON_RUNTIME_SCHEMA_VERSION:
        return SummonRuntimeValidation(False, "summon_runtime_schema_mismatch")
    for field_name in _REQUIRED_MAPPING_FIELDS:
        if not isinstance(value.get(field_name), dict):
            return SummonRuntimeValidation(
                False,
                f"summon_runtime_{field_name}_malformed",
            )
    for field_name in _REQUIRED_LIST_FIELDS:
        if not isinstance(value.get(field_name), list):
            return SummonRuntimeValidation(
                False,
                f"summon_runtime_{field_name}_malformed",
            )
    boundary = value["schema_boundary"]
    if boundary.get("version") != SUMMON_RUNTIME_SCHEMA_VERSION:
        return SummonRuntimeValidation(
            False,
            "summon_runtime_schema_boundary_mismatch",
        )

    entities = value["entities"]
    for unit_id, raw_entry in entities.items():
        if not isinstance(unit_id, str) or not unit_id or not isinstance(raw_entry, dict):
            return SummonRuntimeValidation(
                False,
                "summon_runtime_entity_identity_malformed",
            )
        if raw_entry.get("runtime_id") != unit_id or raw_entry.get("unit_id") != unit_id:
            return SummonRuntimeValidation(
                False,
                "summon_runtime_entity_identity_mismatch",
            )
        if raw_entry.get("summon_kind") not in {
            "servant",
            "summoned_monster",
        }:
            return SummonRuntimeValidation(
                False,
                "summon_runtime_entity_kind_malformed",
            )
        if (
            not isinstance(raw_entry.get("owner_id"), str)
            or not raw_entry.get("owner_id")
        ):
            return SummonRuntimeValidation(
                False,
                "summon_runtime_entity_owner_malformed",
            )
        if (
            not isinstance(raw_entry.get("summoner_id"), str)
            or not raw_entry.get("summoner_id")
        ):
            return SummonRuntimeValidation(
                False,
                "summon_runtime_entity_summoner_malformed",
            )
        if raw_entry.get("team_side") not in {"ally", "enemy"}:
            return SummonRuntimeValidation(
                False,
                "summon_runtime_entity_team_side_malformed",
            )
        if raw_entry.get("status") not in {"active", "removed"}:
            return SummonRuntimeValidation(
                False,
                "summon_runtime_entity_status_malformed",
            )
        targetability = raw_entry.get("targetability")
        if (
            not isinstance(targetability, dict)
            or not isinstance(targetability.get("targetable"), bool)
        ):
            return SummonRuntimeValidation(
                False,
                "summon_runtime_entity_targetability_malformed",
            )
        if units is not None and raw_entry.get("status") == "active":
            unit = units.get(unit_id)
            if unit is None:
                return SummonRuntimeValidation(
                    False,
                    "summon_runtime_active_entity_unit_missing",
                )
            owner_id = str(raw_entry.get("owner_id") or "")
            if str(unit.flags.get("owner_id") or "") != owner_id:
                return SummonRuntimeValidation(
                    False,
                    "summon_runtime_entity_unit_owner_mismatch",
                )
            summoner_id = str(raw_entry.get("summoner_id") or "")
            if str(unit.flags.get("summoner_id") or "") != summoner_id:
                return SummonRuntimeValidation(
                    False,
                    "summon_runtime_entity_unit_summoner_mismatch",
                )
            if (
                str(unit.flags.get("summon_kind") or "")
                != raw_entry.get("summon_kind")
            ):
                return SummonRuntimeValidation(
                    False,
                    "summon_runtime_entity_unit_kind_mismatch",
                )
            if unit.lifecycle_status == "removed":
                return SummonRuntimeValidation(
                    False,
                    "summon_runtime_active_entity_unit_removed",
                )
            owner = units.get(owner_id)
            if owner is None:
                return SummonRuntimeValidation(
                    False,
                    "summon_runtime_active_entity_owner_unit_missing",
                )
            summoner = units.get(summoner_id)
            if summoner is None:
                return SummonRuntimeValidation(
                    False,
                    "summon_runtime_active_entity_summoner_unit_missing",
                )
            team_side = str(raw_entry.get("team_side") or "")
            if str(unit.flags.get("team_side") or "") != team_side:
                return SummonRuntimeValidation(
                    False,
                    "summon_runtime_entity_unit_team_side_mismatch",
                )
            if runtime_unit_combat_team(unit) != team_side:
                return SummonRuntimeValidation(
                    False,
                    "summon_runtime_entity_unit_combat_team_mismatch",
                )
            if runtime_unit_combat_team(owner) != team_side:
                return SummonRuntimeValidation(
                    False,
                    "summon_runtime_entity_owner_combat_team_mismatch",
                )
            if runtime_unit_combat_team(summoner) != team_side:
                return SummonRuntimeValidation(
                    False,
                    "summon_runtime_entity_summoner_combat_team_mismatch",
                )

    if units is not None:
        for unit_id, unit in sorted(units.items()):
            summon_kind = str(unit.flags.get("summon_kind") or "")
            if summon_kind not in {"servant", "summoned_monster"}:
                continue
            if unit.lifecycle_status == "removed":
                continue
            raw_entry = entities.get(unit_id)
            if not isinstance(raw_entry, dict):
                return SummonRuntimeValidation(
                    False,
                    "summon_runtime_active_unit_entity_missing",
                )
            if raw_entry.get("status") != "active":
                return SummonRuntimeValidation(
                    False,
                    "summon_runtime_active_unit_entity_not_active",
                )
            if raw_entry.get("summon_kind") != summon_kind:
                return SummonRuntimeValidation(
                    False,
                    "summon_runtime_active_unit_entity_kind_mismatch",
                )
            if raw_entry.get("owner_id") != unit.flags.get("owner_id"):
                return SummonRuntimeValidation(
                    False,
                    "summon_runtime_active_unit_entity_owner_mismatch",
                )
            if raw_entry.get("summoner_id") != unit.flags.get("summoner_id"):
                return SummonRuntimeValidation(
                    False,
                    "summon_runtime_active_unit_entity_summoner_mismatch",
                )
            if raw_entry.get("team_side") != unit.flags.get("team_side"):
                return SummonRuntimeValidation(
                    False,
                    "summon_runtime_active_unit_entity_team_side_mismatch",
                )

    by_owner = value["by_owner"]
    for owner_id, raw_ids in by_owner.items():
        reason = _validate_index_entry(owner_id, raw_ids, entities)
        if reason:
            return SummonRuntimeValidation(False, reason)
        for unit_id in raw_ids:
            entry = entities[unit_id]
            if (
                entry.get("owner_id") != owner_id
                or entry.get("status") != "active"
            ):
                return SummonRuntimeValidation(
                    False,
                    "summon_runtime_by_owner_identity_mismatch",
                )

    by_unique_group = value["by_unique_group"]
    for group_id, raw_ids in by_unique_group.items():
        reason = _validate_index_entry(group_id, raw_ids, entities)
        if reason:
            return SummonRuntimeValidation(False, reason)
        for unit_id in raw_ids:
            entry = entities[unit_id]
            if (
                entry.get("unique_group") != group_id
                or entry.get("status") != "active"
            ):
                return SummonRuntimeValidation(
                    False,
                    "summon_runtime_by_unique_group_identity_mismatch",
                )

    for unit_id, raw_entry in entities.items():
        if raw_entry.get("status") != "active":
            continue
        owner_id = str(raw_entry.get("owner_id") or "")
        if owner_id and unit_id not in by_owner.get(owner_id, []):
            return SummonRuntimeValidation(
                False,
                "summon_runtime_active_entity_owner_index_missing",
            )
        unique_group = str(raw_entry.get("unique_group") or "")
        if unique_group and unit_id not in by_unique_group.get(unique_group, []):
            return SummonRuntimeValidation(
                False,
                "summon_runtime_active_entity_unique_group_index_missing",
            )

    servants = value["servants"]
    if any(
        raw_entry.get("summon_kind") == "servant"
        and unit_id not in servants
        for unit_id, raw_entry in entities.items()
    ):
        return SummonRuntimeValidation(
            False,
            "summon_runtime_servant_index_missing",
        )
    for unit_id, raw_entry in servants.items():
        entity = entities.get(unit_id)
        if (
            not isinstance(unit_id, str)
            or not isinstance(raw_entry, dict)
            or not isinstance(entity, dict)
            or raw_entry.get("summon_kind") != "servant"
            or entity.get("summon_kind") != "servant"
            or raw_entry.get("status") != entity.get("status")
            or any(
                raw_entry.get(field_name) != entity.get(field_name)
                for field_name in (
                    "runtime_id",
                    "unit_id",
                    "owner_id",
                    "summoner_id",
                    "team_side",
                    "status",
                    "source_intent_id",
                    "created_event_index",
                    "removed_event_index",
                )
            )
        ):
            return SummonRuntimeValidation(
                False,
                "summon_runtime_servant_index_mismatch",
            )

    for field_name in ("last_summon_monsters", "last_servants"):
        raw_ids = value[field_name]
        if (
            any(not isinstance(unit_id, str) or unit_id not in entities for unit_id in raw_ids)
            or len(raw_ids) != len(set(raw_ids))
            or (
                field_name == "last_servants"
                and any(
                    entities[unit_id].get("summon_kind") != "servant"
                    for unit_id in raw_ids
                )
            )
            or (
                field_name == "last_summon_monsters"
                and any(
                    entities[unit_id].get("summon_kind") != "summoned_monster"
                    for unit_id in raw_ids
                )
            )
        ):
            return SummonRuntimeValidation(
                False,
                f"summon_runtime_{field_name}_identity_mismatch",
            )
    return SummonRuntimeValidation(True)


def _validate_index_entry(
    index_id: object,
    raw_ids: object,
    entities: dict[str, JSONValue],
) -> str:
    if not isinstance(index_id, str) or not index_id or not isinstance(raw_ids, list):
        return "summon_runtime_index_malformed"
    if (
        any(not isinstance(unit_id, str) or unit_id not in entities for unit_id in raw_ids)
        or len(raw_ids) != len(set(raw_ids))
    ):
        return "summon_runtime_index_identity_mismatch"
    return ""
