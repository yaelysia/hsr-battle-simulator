from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from .immutable_json import thaw_json

if TYPE_CHECKING:
    from .core.model import BattleState, JSONValue, Mutation, UnitState


DEPARTED_SOURCES_FLAG = "departed_sources"
_DEPARTED_SOURCE_FIELDS = frozenset(
    {
        "departure_source_id",
        "source_status_instance_id",
        "source_effect_id",
        "config_group_name",
        "admission_status",
        "source_trace",
    }
)
_DEPARTURE_TRACE_FIELDS = frozenset(
    {
        "effect_id",
        "effect_source",
        "status_instance_id",
        "status_instance_source",
    }
)


def unit_departure_sources(
    unit: UnitState,
) -> tuple[dict[str, JSONValue], ...] | None:
    raw = unit.flags.get(DEPARTED_SOURCES_FLAG)
    if raw is None:
        return ()
    return _normalized_departure_sources(raw)


def departure_source_count(value: object) -> int | None:
    """Count only fully admitted departure-source payloads."""

    if value is None:
        return 0
    entries = _normalized_departure_sources(value)
    return None if entries is None else len(entries)


def _normalized_departure_sources(
    raw: object,
) -> tuple[dict[str, JSONValue], ...] | None:
    if not isinstance(raw, (list, tuple)):
        return None
    entries: list[dict[str, JSONValue]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != _DEPARTED_SOURCE_FIELDS:
            return None
        source_id = item.get("departure_source_id")
        status_instance_id = item.get("source_status_instance_id")
        effect_id = item.get("source_effect_id")
        config_group_name = item.get("config_group_name")
        source_trace = item.get("source_trace")
        if (
            not isinstance(source_id, str)
            or not source_id
            or source_id in seen
            or not isinstance(status_instance_id, str)
            or not status_instance_id
            or not isinstance(effect_id, str)
            or not effect_id
            or not isinstance(config_group_name, str)
            or item.get("admission_status") != "executable"
            or not _departure_trace_is_valid(
                source_trace,
                source_status_instance_id=status_instance_id,
                source_effect_id=effect_id,
            )
        ):
            return None
        seen.add(source_id)
        entries.append(
            {
                "departure_source_id": source_id,
                "source_status_instance_id": status_instance_id,
                "source_effect_id": effect_id,
                "config_group_name": config_group_name,
                "admission_status": "executable",
                "source_trace": thaw_json(source_trace),
            }
        )
    return tuple(
        sorted(
            entries,
            key=lambda entry: str(entry["departure_source_id"]),
        )
    )


def unit_is_departed(unit: UnitState) -> bool:
    sources = unit_departure_sources(unit)
    return sources is None or bool(sources)


def unit_departure_blocked_reason(unit: UnitState) -> str:
    return (
        "unit_departure_sources_invalid"
        if unit_departure_sources(unit) is None
        else ""
    )


def plan_unit_departure_start(
    state: BattleState,
    *,
    unit_id: str,
    source_status_instance_id: str,
    source_effect_id: str,
    config_group_name: str,
    source_trace: Mapping[str, object],
    mutation_source: str,
    mutation_metadata: Mapping[str, object],
) -> tuple[Mutation | None, str]:
    from .core.model import Mutation

    unit = state.units.get(unit_id)
    if unit is None:
        return None, "unit_departure_target_missing"
    if (
        not source_status_instance_id
        or not source_effect_id
        or not isinstance(config_group_name, str)
        or not mutation_source
        or not mutation_metadata
        or not _departure_trace_is_valid(
            source_trace,
            source_status_instance_id=source_status_instance_id,
            source_effect_id=source_effect_id,
        )
    ):
        return None, "unit_departure_source_incomplete"
    before = unit_departure_sources(unit)
    if before is None:
        return None, "unit_departure_sources_invalid"
    departure_source_id = (
        f"{source_status_instance_id}:{source_effect_id}"
    )
    entry: dict[str, JSONValue] = {
        "departure_source_id": departure_source_id,
        "source_status_instance_id": source_status_instance_id,
        "source_effect_id": source_effect_id,
        "config_group_name": config_group_name,
        "admission_status": "executable",
        "source_trace": thaw_json(source_trace),
    }
    existing = next(
        (
            candidate
            for candidate in before
            if candidate["departure_source_id"] == departure_source_id
        ),
        None,
    )
    if existing is not None:
        return (
            (None, "")
            if existing == entry
            else (None, "unit_departure_source_identity_conflict")
        )
    after = tuple(
        sorted(
            (*before, entry),
            key=lambda candidate: str(
                candidate["departure_source_id"]
            ),
        )
    )
    return (
        Mutation(
            op="set",
            path=(
                "units",
                unit_id,
                "flags",
                DEPARTED_SOURCES_FLAG,
            ),
            before=[dict(item) for item in before]
            if DEPARTED_SOURCES_FLAG in unit.flags
            else None,
            after=[dict(item) for item in after],
            reason="attach source-backed departed presence",
            source=mutation_source,
            before_exists=DEPARTED_SOURCES_FLAG in unit.flags,
            metadata={
                **thaw_json(mutation_metadata),
                "presence_operation": "unit_departed_start",
                "unit_id": unit_id,
                "departure_source_id": departure_source_id,
                "source_status_instance_id": source_status_instance_id,
                "source_effect_id": source_effect_id,
                "source_trace": thaw_json(source_trace),
            },
        ),
        "",
    )


def plan_unit_departure_end(
    state: BattleState,
    *,
    unit_id: str,
    source_status_instance_id: str,
    source_trace: Mapping[str, object],
    mutation_source: str,
    mutation_metadata: Mapping[str, object],
) -> tuple[Mutation | None, str]:
    from .core.model import Mutation

    unit = state.units.get(unit_id)
    if unit is None:
        return None, "unit_departure_target_missing"
    if (
        not source_status_instance_id
        or not source_trace
        or not mutation_source
        or not mutation_metadata
    ):
        return None, "unit_departure_source_incomplete"
    before = unit_departure_sources(unit)
    if before is None:
        return None, "unit_departure_sources_invalid"
    removed = tuple(
        entry
        for entry in before
        if entry["source_status_instance_id"]
        == source_status_instance_id
    )
    if not removed:
        return None, ""
    after = tuple(entry for entry in before if entry not in removed)
    return (
        Mutation(
            op="set",
            path=(
                "units",
                unit_id,
                "flags",
                DEPARTED_SOURCES_FLAG,
            ),
            before=[dict(item) for item in before],
            after=[dict(item) for item in after],
            reason="detach source-backed departed presence",
            source=mutation_source,
            metadata={
                **thaw_json(mutation_metadata),
                "presence_operation": "unit_departed_end",
                "unit_id": unit_id,
                "source_status_instance_id": source_status_instance_id,
                "removed_departure_source_ids": [
                    str(item["departure_source_id"])
                    for item in removed
                ],
                "source_trace": thaw_json(source_trace),
            },
        ),
        "",
    )


def _departure_trace_is_valid(
    value: object,
    *,
    source_status_instance_id: str,
    source_effect_id: str,
) -> bool:
    if not isinstance(value, Mapping) or set(value) != _DEPARTURE_TRACE_FIELDS:
        return False
    effect_source = value.get("effect_source")
    status_source = value.get("status_instance_source")
    return bool(
        value.get("effect_id") == source_effect_id
        and value.get("status_instance_id") == source_status_instance_id
        and isinstance(effect_source, Mapping)
        and effect_source
        and isinstance(status_source, Mapping)
        and status_source
    )
