from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Literal

from .immutable_json import freeze_json, thaw_json
from .model import BattleState, JSONValue, Mutation, UnitState


StateIntegrityStatus = Literal["passed", "failed", "not_run"]
StateIntegrityCheckMode = Literal["touched", "full", "not_run"]

LIFECYCLE_DOMAIN = "lifecycle"
_REGISTERED_DOMAINS = (LIFECYCLE_DOMAIN,)
_DEFEAT_RECORD_PATH = ("flags", "defeat_record")
_REMOVED_RECORD_PATH = ("flags", "removed_record")


@dataclass(frozen=True)
class StateIntegrityIssue:
    domain: str
    code: str
    entity_id: str
    paths: tuple[tuple[str, ...], ...] = ()
    mutation_ids: tuple[str, ...] = ()
    details: dict[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.domain or not self.code or not self.entity_id:
            raise ValueError(
                "state integrity issue requires domain, code, and entity_id"
            )
        paths = _canonical_paths(self.paths)
        mutation_ids = tuple(
            sorted(
                {
                    mutation_id
                    for mutation_id in self.mutation_ids
                    if isinstance(mutation_id, str) and mutation_id
                }
            )
        )
        details = freeze_json(self.details)
        if not isinstance(details, dict):
            raise TypeError("state integrity issue details must be a JSON object")
        object.__setattr__(self, "paths", paths)
        object.__setattr__(self, "mutation_ids", mutation_ids)
        object.__setattr__(self, "details", details)

    def to_json(self) -> dict[str, JSONValue]:
        details = thaw_json(self.details)
        assert isinstance(details, dict)
        return {
            "domain": self.domain,
            "code": self.code,
            "entity_id": self.entity_id,
            "paths": [list(path) for path in self.paths],
            "mutation_ids": list(self.mutation_ids),
            "details": details,
        }


@dataclass(frozen=True)
class StateIntegrityScope:
    domain: str
    entity_ids: tuple[str, ...] = ()
    paths: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        if not self.domain:
            raise ValueError("state integrity scope requires a domain")
        entity_ids = tuple(
            sorted(
                {
                    entity_id
                    for entity_id in self.entity_ids
                    if isinstance(entity_id, str) and entity_id
                }
            )
        )
        object.__setattr__(self, "entity_ids", entity_ids)
        object.__setattr__(self, "paths", _canonical_paths(self.paths))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "domain": self.domain,
            "entity_ids": list(self.entity_ids),
            "paths": [list(path) for path in self.paths],
        }


@dataclass(frozen=True)
class StateIntegrityResult:
    status: StateIntegrityStatus
    check_mode: StateIntegrityCheckMode
    checked_scopes: tuple[StateIntegrityScope, ...] = ()
    issues: tuple[StateIntegrityIssue, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"passed", "failed", "not_run"}:
            raise ValueError(f"unsupported state integrity status {self.status!r}")
        if self.check_mode not in {"touched", "full", "not_run"}:
            raise ValueError(
                f"unsupported state integrity check mode {self.check_mode!r}"
            )
        scopes = tuple(
            sorted(
                self.checked_scopes,
                key=lambda scope: (scope.domain, scope.entity_ids, scope.paths),
            )
        )
        issues = tuple(sorted(self.issues, key=_issue_sort_key))
        if self.status == "not_run":
            if self.check_mode != "not_run" or scopes or issues:
                raise ValueError(
                    "not_run state integrity result cannot contain scopes or issues"
                )
        elif self.check_mode == "not_run":
            raise ValueError("executed state integrity result requires a check mode")
        elif self.status == "passed" and issues:
            raise ValueError("passed state integrity result cannot contain issues")
        elif self.status == "failed" and not issues:
            raise ValueError("failed state integrity result requires issues")
        object.__setattr__(self, "checked_scopes", scopes)
        object.__setattr__(self, "issues", issues)

    @property
    def ok(self) -> bool:
        return self.status == "passed"

    @property
    def checked_domains(self) -> tuple[str, ...]:
        return tuple(
            sorted({scope.domain for scope in self.checked_scopes})
        )

    def to_json(self) -> dict[str, JSONValue]:
        checked_entities: dict[str, list[JSONValue]] = {}
        for domain in self.checked_domains:
            checked_entities[domain] = list(
                sorted(
                    {
                        entity_id
                        for scope in self.checked_scopes
                        if scope.domain == domain
                        for entity_id in scope.entity_ids
                    }
                )
            )
        return {
            "status": self.status,
            "check_mode": self.check_mode,
            "checked_domains": list(self.checked_domains),
            "checked_entities": checked_entities,
            "checked_scopes": [
                scope.to_json() for scope in self.checked_scopes
            ],
            "issues": [issue.to_json() for issue in self.issues],
        }

    @classmethod
    def not_run(cls) -> StateIntegrityResult:
        return cls(status="not_run", check_mode="not_run")


class CommittedStateIntegrityError(ValueError):
    def __init__(self, result: StateIntegrityResult):
        if result.status != "failed":
            raise ValueError(
                "CommittedStateIntegrityError requires a failed integrity result"
            )
        self.result = result
        codes = ",".join(issue.code for issue in result.issues)
        super().__init__(f"committed state integrity failed: {codes}")


class CommittedStateIntegrityGate:
    """Validate committed state at full-state or atomic transition boundaries."""

    @property
    def registered_domains(self) -> tuple[str, ...]:
        return _REGISTERED_DOMAINS

    def check_touched(
        self,
        before_state: BattleState,
        after_state: BattleState,
        mutations: tuple[Mutation, ...],
    ) -> StateIntegrityResult:
        paths_by_unit: dict[str, set[tuple[str, ...]]] = {}
        mutation_ids_by_unit: dict[str, set[str]] = {}
        for mutation in mutations:
            unit_id = _lifecycle_unit_id_for_path(mutation.path)
            if unit_id is None:
                continue
            paths_by_unit.setdefault(unit_id, set()).add(mutation.path)
            mutation_ids_by_unit.setdefault(unit_id, set()).add(
                mutation.stable_id()
            )

        scopes = tuple(
            StateIntegrityScope(
                domain=LIFECYCLE_DOMAIN,
                entity_ids=(unit_id,),
                paths=tuple(paths_by_unit[unit_id]),
            )
            for unit_id in sorted(paths_by_unit)
        )
        issues: list[StateIntegrityIssue] = []
        for scope in scopes:
            unit_id = scope.entity_ids[0]
            mutation_ids = tuple(mutation_ids_by_unit.get(unit_id, ()))
            after_unit = after_state.units.get(unit_id)
            if after_unit is not None:
                issues.extend(
                    _lifecycle_final_state_issues(
                        after_unit,
                        mutation_ids=mutation_ids,
                    )
                )
            issues.extend(
                _lifecycle_transition_issues(
                    before_state,
                    after_state,
                    unit_id,
                    scope.paths,
                    mutation_ids,
                )
            )
        return StateIntegrityResult(
            status="failed" if issues else "passed",
            check_mode="touched",
            checked_scopes=scopes,
            issues=tuple(issues),
        )

    def check_full(self, state: BattleState) -> StateIntegrityResult:
        scopes = tuple(
            StateIntegrityScope(
                domain=LIFECYCLE_DOMAIN,
                entity_ids=(unit_id,),
            )
            for unit_id in sorted(state.units)
        )
        if not scopes:
            scopes = (StateIntegrityScope(domain=LIFECYCLE_DOMAIN),)
        issues = tuple(
            issue
            for unit_id in sorted(state.units)
            for issue in _lifecycle_final_state_issues(state.units[unit_id])
        )
        return StateIntegrityResult(
            status="failed" if issues else "passed",
            check_mode="full",
            checked_scopes=scopes,
            issues=issues,
        )

    def require_full(self, state: BattleState) -> StateIntegrityResult:
        result = self.check_full(state)
        if not result.ok:
            raise CommittedStateIntegrityError(result)
        return result


def _lifecycle_final_state_issues(
    unit: UnitState,
    *,
    mutation_ids: tuple[str, ...] = (),
) -> tuple[StateIntegrityIssue, ...]:
    unit_id = unit.unit_id
    issues: list[StateIntegrityIssue] = []
    max_hp_is_finite = _finite_number(unit.max_hp)
    hp_is_finite = _finite_number(unit.hp)
    if not max_hp_is_finite or float(unit.max_hp) <= 0:
        issues.append(
            _issue(
                "lifecycle_max_hp_invalid",
                unit_id,
                (_unit_path(unit_id, "max_hp"),),
                mutation_ids,
            )
        )
    if not hp_is_finite:
        issues.append(
            _issue(
                "lifecycle_hp_not_finite",
                unit_id,
                (_unit_path(unit_id, "hp"),),
                mutation_ids,
            )
        )
    elif (
        max_hp_is_finite
        and float(unit.max_hp) > 0
        and (float(unit.hp) < 0 or float(unit.hp) > float(unit.max_hp))
    ):
        issues.append(
            _issue(
                "lifecycle_hp_out_of_range",
                unit_id,
                (
                    _unit_path(unit_id, "hp"),
                    _unit_path(unit_id, "max_hp"),
                ),
                mutation_ids,
            )
        )

    defeat_present, defeat_valid = _record_presence(
        unit, "defeat_record"
    )
    removed_present, removed_valid = _record_presence(
        unit, "removed_record"
    )
    if defeat_present and not defeat_valid:
        issues.append(
            _issue(
                "lifecycle_defeat_record_invalid",
                unit_id,
                (_unit_flag_path(unit_id, "defeat_record"),),
                mutation_ids,
            )
        )
    if removed_present and not removed_valid:
        issues.append(
            _issue(
                "lifecycle_removed_record_invalid",
                unit_id,
                (_unit_flag_path(unit_id, "removed_record"),),
                mutation_ids,
            )
        )

    lifecycle_path = _unit_path(unit_id, "lifecycle_status")
    if unit.lifecycle_status == "active":
        if hp_is_finite and float(unit.hp) <= 0:
            issues.append(
                _issue(
                    "active_unit_hp_not_positive",
                    unit_id,
                    (_unit_path(unit_id, "hp"), lifecycle_path),
                    mutation_ids,
                )
            )
        if defeat_present:
            issues.append(
                _issue(
                    "active_unit_has_defeat_record",
                    unit_id,
                    (_unit_flag_path(unit_id, "defeat_record"), lifecycle_path),
                    mutation_ids,
                )
            )
        if removed_present:
            issues.append(
                _issue(
                    "active_unit_has_removed_record",
                    unit_id,
                    (_unit_flag_path(unit_id, "removed_record"), lifecycle_path),
                    mutation_ids,
                )
            )
    elif unit.lifecycle_status == "defeated":
        if hp_is_finite and float(unit.hp) != 0:
            issues.append(
                _issue(
                    "defeated_unit_hp_not_zero",
                    unit_id,
                    (_unit_path(unit_id, "hp"), lifecycle_path),
                    mutation_ids,
                )
            )
        if not defeat_valid:
            issues.append(
                _issue(
                    "defeated_unit_missing_defeat_record",
                    unit_id,
                    (_unit_flag_path(unit_id, "defeat_record"), lifecycle_path),
                    mutation_ids,
                )
            )
        if removed_present:
            issues.append(
                _issue(
                    "defeated_unit_has_removed_record",
                    unit_id,
                    (_unit_flag_path(unit_id, "removed_record"), lifecycle_path),
                    mutation_ids,
                )
            )
    elif unit.lifecycle_status == "removed" and not removed_valid:
        issues.append(
            _issue(
                "removed_unit_missing_removed_record",
                unit_id,
                (_unit_flag_path(unit_id, "removed_record"), lifecycle_path),
                mutation_ids,
            )
        )
    return tuple(issues)


def _lifecycle_transition_issues(
    before_state: BattleState,
    after_state: BattleState,
    unit_id: str,
    touched_paths: tuple[tuple[str, ...], ...],
    mutation_ids: tuple[str, ...],
) -> tuple[StateIntegrityIssue, ...]:
    before = before_state.units.get(unit_id)
    after = after_state.units.get(unit_id)
    if before is not None and after is None:
        return (
            _issue(
                "unit_deletion_not_admitted",
                unit_id,
                (("units", unit_id),),
                mutation_ids,
            ),
        )
    if before is None:
        if after is None:
            return ()
        if (
            after.lifecycle_status != "active"
            or not _path_was_touched(touched_paths, ("units", unit_id))
        ):
            return (
                _issue(
                    "lifecycle_spawn_state_invalid",
                    unit_id,
                    (("units", unit_id),),
                    mutation_ids,
                    details={"after": after.lifecycle_status},
                ),
            )
        return ()
    if after is None or before.lifecycle_status == after.lifecycle_status:
        return ()

    transition = (before.lifecycle_status, after.lifecycle_status)
    status_path = _unit_path(unit_id, "lifecycle_status")
    hp_path = _unit_path(unit_id, "hp")
    defeat_record_path = _unit_flag_path(unit_id, "defeat_record")
    removed_record_path = _unit_flag_path(unit_id, "removed_record")
    if transition == ("active", "defeated"):
        required = (hp_path, status_path, defeat_record_path)
        missing = tuple(
            path
            for path in required
            if not _path_was_touched(touched_paths, path)
        )
        if missing:
            return (
                _issue(
                    "defeat_transition_not_atomic",
                    unit_id,
                    required,
                    mutation_ids,
                    details={"missing_paths": [list(path) for path in missing]},
                ),
            )
        return ()
    if transition in {
        ("active", "removed"),
        ("defeated", "removed"),
    }:
        required = (status_path, removed_record_path)
        missing = tuple(
            path
            for path in required
            if not _path_was_touched(touched_paths, path)
        )
        if missing:
            return (
                _issue(
                    "remove_transition_not_atomic",
                    unit_id,
                    required,
                    mutation_ids,
                    details={"missing_paths": [list(path) for path in missing]},
                ),
            )
        return ()
    return (
        _issue(
            "lifecycle_transition_not_admitted",
            unit_id,
            (status_path,),
            mutation_ids,
            details={
                "before": before.lifecycle_status,
                "after": after.lifecycle_status,
            },
        ),
    )

def _lifecycle_unit_id_for_path(path: tuple[str, ...]) -> str | None:
    if len(path) < 2 or path[0] != "units" or not path[1]:
        return None
    if len(path) == 2:
        return path[1]
    field_name = path[2]
    if field_name in {"hp", "max_hp", "lifecycle_status"} and len(path) == 3:
        return path[1]
    if field_name != "flags":
        return None
    if len(path) == 3:
        return path[1]
    if len(path) == 4 and path[3] in {
        "defeat_record",
        "removed_record",
        "lifecycle_status",
        "lifecycle_state",
    }:
        return path[1]
    return None


def _path_was_touched(
    touched_paths: tuple[tuple[str, ...], ...],
    required_path: tuple[str, ...],
) -> bool:
    unit_root = required_path[:2]
    if unit_root in touched_paths:
        return True
    if required_path in touched_paths:
        return True
    if (
        len(required_path) == 4
        and required_path[2] == "flags"
        and required_path[:3] in touched_paths
    ):
        return True
    return False


def _record_presence(unit: UnitState, key: str) -> tuple[bool, bool]:
    if key not in unit.flags:
        return False, False
    value = unit.flags.get(key)
    return True, isinstance(value, dict) and bool(value)


def _issue(
    code: str,
    unit_id: str,
    paths: tuple[tuple[str, ...], ...],
    mutation_ids: tuple[str, ...],
    *,
    details: dict[str, JSONValue] | None = None,
) -> StateIntegrityIssue:
    return StateIntegrityIssue(
        domain=LIFECYCLE_DOMAIN,
        code=code,
        entity_id=unit_id,
        paths=paths,
        mutation_ids=mutation_ids,
        details=details or {},
    )


def _unit_path(unit_id: str, field_name: str) -> tuple[str, ...]:
    return ("units", unit_id, field_name)


def _unit_flag_path(unit_id: str, key: str) -> tuple[str, ...]:
    return ("units", unit_id, "flags", key)


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _canonical_paths(
    paths: tuple[tuple[str, ...], ...],
) -> tuple[tuple[str, ...], ...]:
    normalized: set[tuple[str, ...]] = set()
    for path in paths:
        if (
            not isinstance(path, (list, tuple))
            or not path
            or not all(isinstance(part, str) and part for part in path)
        ):
            raise ValueError(f"invalid canonical state integrity path {path!r}")
        normalized.add(tuple(path))
    return tuple(sorted(normalized))


def _issue_sort_key(issue: StateIntegrityIssue) -> tuple[object, ...]:
    return (
        issue.domain,
        issue.entity_id,
        issue.code,
        issue.paths,
        issue.mutation_ids,
        json.dumps(
            thaw_json(issue.details),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
