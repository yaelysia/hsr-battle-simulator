from __future__ import annotations

from dataclasses import dataclass

from .model import JSONValue, Snapshot


REQUIRED_SNAPSHOT_PATHS: tuple[tuple[str, ...], ...] = (
    ("battle",),
    ("battle", "wave_index"),
    ("battle", "phase"),
    ("battle", "current_window"),
    ("battle", "action_index"),
    ("teams",),
    ("units",),
    ("resources",),
    ("timeline",),
    ("queues",),
    ("pending_events",),
    ("rng_state",),
    ("rng_events",),
    ("targeting",),
    ("settlement",),
    ("coverage",),
    ("global_flags",),
    ("global_flags", "dynamic_value_store"),
)

REQUIRED_UNIT_PATHS: tuple[tuple[str, ...], ...] = (
    ("unit_id",),
    ("side",),
    ("template_id",),
    ("template_source",),
    ("position",),
    ("level",),
    ("hp",),
    ("max_hp",),
    ("lifecycle_status",),
    ("defeated",),
    ("removed",),
    ("lifecycle",),
    ("lifecycle", "status"),
    ("lifecycle", "active"),
    ("lifecycle", "defeated"),
    ("lifecycle", "removed"),
    ("shield",),
    ("shield_instances",),
    ("recoverable_hp",),
    ("energy",),
    ("max_energy",),
    ("base_stats",),
    ("derived_stats",),
    ("toughness_state",),
    ("action_value",),
    ("statuses",),
    ("status_details",),
    ("modifiers",),
    ("flags",),
    ("resources",),
)


@dataclass(frozen=True)
class ContractCheckResult:
    ok: bool
    missing_paths: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "missing_paths": list(self.missing_paths),
            "errors": list(self.errors),
        }


class SnapshotCompletenessValidator:
    def validate(self, snapshot: Snapshot | dict[str, JSONValue]) -> ContractCheckResult:
        data = snapshot.to_json() if isinstance(snapshot, Snapshot) else snapshot
        missing: list[str] = []
        errors: list[str] = []
        for path in REQUIRED_SNAPSHOT_PATHS:
            if not _has_path(data, path):
                missing.append(_format_path(path))

        units = data.get("units")
        if not isinstance(units, dict):
            errors.append("snapshot.units must be an object")
        else:
            for unit_id, unit_snapshot in sorted(units.items()):
                if not isinstance(unit_snapshot, dict):
                    errors.append(f"snapshot.units.{unit_id} must be an object")
                    continue
                for path in REQUIRED_UNIT_PATHS:
                    if not _has_path(unit_snapshot, path):
                        missing.append(f"units.{unit_id}.{_format_path(path)}")

        return ContractCheckResult(ok=not missing and not errors, missing_paths=tuple(missing), errors=tuple(errors))


def _has_path(data: dict[str, JSONValue], path: tuple[str, ...]) -> bool:
    current: object = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return False
        current = current[key]
    return True


def _format_path(path: tuple[str, ...]) -> str:
    return ".".join(path)
