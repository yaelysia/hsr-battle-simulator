from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

from .immutable_json import thaw_json
from .model import BattleState, JSONValue, Mutation
from .unit_state_codec import (
    UNIT_STATE_MUTABLE_FIELDS,
    unit_state_from_payload,
    unit_state_to_payload,
    validate_canonical_unit_field_value,
)


SUPPORTED_MUTATION_OPS = frozenset({"set", "delete", "spawn"})
_BATTLE_SCALAR_TYPES: dict[str, type[object]] = {
    "skill_points": int,
    "max_skill_points": int,
    "wave_index": int,
    "rng_state": str,
    "event_index": int,
}
@dataclass(frozen=True)
class MutationConflict:
    code: str
    mutation_index: int
    mutation_id: str
    path: tuple[str, ...]
    op: str
    message: str
    expected_exists: bool | None = None
    actual_exists: bool | None = None
    expected: JSONValue = None
    actual: JSONValue = None
    prior_mutation_index: int | None = None
    prior_mutation_id: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "code": self.code,
            "mutation_index": self.mutation_index,
            "mutation_id": self.mutation_id,
            "path": list(self.path),
            "op": self.op,
            "message": self.message,
            "expected_exists": self.expected_exists,
            "actual_exists": self.actual_exists,
            "expected": thaw_json(self.expected),
            "actual": thaw_json(self.actual),
            "prior_mutation_index": self.prior_mutation_index,
            "prior_mutation_id": self.prior_mutation_id,
        }


@dataclass(frozen=True)
class MutationReductionResult:
    ok: bool
    before_state: BattleState
    after_state: BattleState
    applied_count: int = 0
    conflicts: tuple[MutationConflict, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "applied_count": self.applied_count,
            "state_unchanged": self.before_state == self.after_state,
            "conflicts": [conflict.to_json() for conflict in self.conflicts],
        }


class MutationConflictError(ValueError):
    def __init__(self, result: MutationReductionResult):
        self.result = result
        conflict = result.conflicts[0] if result.conflicts else None
        message = (
            f"mutation conflict [{conflict.code}] at index {conflict.mutation_index}: {conflict.message}"
            if conflict is not None
            else "mutation reduction failed without conflict detail"
        )
        super().__init__(message)


@dataclass(frozen=True)
class ReplayResult:
    ok: bool
    expected: dict[str, JSONValue]
    actual: dict[str, JSONValue]
    errors: tuple[str, ...] = ()
    conflicts: tuple[MutationConflict, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "expected": self.expected,
            "actual": self.actual,
            "errors": list(self.errors),
            "conflicts": [conflict.to_json() for conflict in self.conflicts],
        }


@dataclass(frozen=True)
class _PathValue:
    exists: bool
    value: JSONValue
    kind: str


class _ReductionIssue(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        expected_exists: bool | None = None,
        actual_exists: bool | None = None,
        expected: JSONValue = None,
        actual: JSONValue = None,
    ):
        self.code = code
        self.expected_exists = expected_exists
        self.actual_exists = actual_exists
        self.expected = expected
        self.actual = actual
        super().__init__(message)


class MutationReducer:
    """Apply explicit mutations with checked preconditions and atomic batches."""

    def apply_all_result(
        self,
        state: BattleState,
        mutations: tuple[Mutation, ...],
    ) -> MutationReductionResult:
        current = state
        prior_by_path: dict[tuple[str, ...], tuple[int, str]] = {}
        for index, mutation in enumerate(mutations):
            try:
                current = self._apply_checked(current, mutation)
            except _ReductionIssue as issue:
                prior = prior_by_path.get(mutation.path)
                code = issue.code
                if prior is not None and code in {"before_presence_mismatch", "before_value_mismatch"}:
                    code = f"same_path_{code}"
                conflict = MutationConflict(
                    code=code,
                    mutation_index=index,
                    mutation_id=mutation.stable_id(),
                    path=mutation.path,
                    op=mutation.op,
                    message=str(issue),
                    expected_exists=issue.expected_exists,
                    actual_exists=issue.actual_exists,
                    expected=issue.expected,
                    actual=issue.actual,
                    prior_mutation_index=prior[0] if prior is not None else None,
                    prior_mutation_id=prior[1] if prior is not None else "",
                )
                return MutationReductionResult(False, state, state, 0, (conflict,))
            prior_by_path[mutation.path] = (index, mutation.stable_id())
        return MutationReductionResult(True, state, current, len(mutations), ())

    def apply_all(self, state: BattleState, mutations: tuple[Mutation, ...]) -> BattleState:
        result = self.apply_all_result(state, mutations)
        if not result.ok:
            raise MutationConflictError(result)
        return result.after_state

    def apply(self, state: BattleState, mutation: Mutation) -> BattleState:
        return self.apply_all(state, (mutation,))

    def replay_snapshot(
        self,
        before: BattleState,
        mutations: tuple[Mutation, ...],
        expected_after: dict[str, JSONValue],
    ) -> ReplayResult:
        reduction = self.apply_all_result(before, mutations)
        if not reduction.ok:
            errors = tuple(
                f"mutation_conflict:{conflict.mutation_index}:{conflict.code}"
                for conflict in reduction.conflicts
            )
            return ReplayResult(
                False,
                expected_after,
                before.snapshot().to_json(),
                errors,
                reduction.conflicts,
            )
        actual = reduction.after_state.snapshot().to_json()
        if _typed_equal(actual, expected_after):
            return ReplayResult(True, expected_after, actual)
        mismatch_path = _first_mismatch_path(expected_after, actual)
        suffix = ".".join(mismatch_path) if mismatch_path else "<root>"
        return ReplayResult(False, expected_after, actual, (f"snapshot_mismatch:{suffix}",))

    def _apply_checked(self, state: BattleState, mutation: Mutation) -> BattleState:
        if mutation.op not in SUPPORTED_MUTATION_OPS:
            raise _ReductionIssue("invalid_op", f"unsupported mutation op {mutation.op!r}")
        if not mutation.path:
            raise _ReductionIssue("invalid_path", "empty mutation path")
        if not mutation.before_exists and mutation.before is not None:
            raise _ReductionIssue(
                "invalid_before_declaration",
                "before must be null when before_exists is false",
                expected_exists=False,
                expected=mutation.before,
            )
        if not mutation.after_exists and mutation.after is not None:
            raise _ReductionIssue(
                "invalid_after_declaration",
                "after must be null when after_exists is false",
                expected_exists=False,
                expected=mutation.after,
            )

        current = self._read_path(state, mutation.path)
        if current.exists != mutation.before_exists:
            raise _ReductionIssue(
                "before_presence_mismatch",
                "declared before existence does not match current state",
                expected_exists=mutation.before_exists,
                actual_exists=current.exists,
                expected=mutation.before,
                actual=current.value,
            )
        if current.exists and not _typed_equal(current.value, mutation.before):
            raise _ReductionIssue(
                "before_value_mismatch",
                "declared before value does not match current state",
                expected_exists=True,
                actual_exists=True,
                expected=mutation.before,
                actual=current.value,
            )

        self._validate_operation(mutation, current)
        updated = self._write_path(state, mutation)
        applied = self._read_path(updated, mutation.path)
        if applied.exists != mutation.after_exists:
            raise _ReductionIssue(
                "after_presence_mismatch",
                "applied path existence does not match declared after existence",
                expected_exists=mutation.after_exists,
                actual_exists=applied.exists,
                expected=mutation.after,
                actual=applied.value,
            )
        if applied.exists and not _typed_equal(applied.value, mutation.after):
            raise _ReductionIssue(
                "after_value_mismatch",
                "applied value does not match declared after value",
                expected_exists=True,
                actual_exists=True,
                expected=mutation.after,
                actual=applied.value,
            )
        return updated

    def _validate_operation(self, mutation: Mutation, current: _PathValue) -> None:
        if mutation.op == "set":
            if not mutation.after_exists:
                raise _ReductionIssue("invalid_after_presence", "set requires after_exists=true")
            if current.kind == "unit_root":
                raise _ReductionIssue("invalid_op_path", "unit root creation requires op='spawn'")
            _validate_after_value(mutation.path, current.kind, mutation.after)
            return
        if mutation.op == "delete":
            if current.kind not in {"mapping", "resource_mapping", "queue"}:
                raise _ReductionIssue("invalid_op_path", "delete requires a mapping or queue entry path")
            if not current.exists:
                raise _ReductionIssue("invalid_delete", "delete requires an existing path")
            if mutation.after_exists or mutation.after is not None:
                raise _ReductionIssue("invalid_after_presence", "delete requires absent after state")
            return
        if current.kind != "unit_root":
            raise _ReductionIssue("invalid_op_path", "spawn requires a unit root path")
        if mutation.before_exists or mutation.before is not None:
            raise _ReductionIssue("invalid_spawn_before", "spawn requires an absent before state")
        if not mutation.after_exists:
            raise _ReductionIssue("invalid_after_presence", "spawn requires after_exists=true")
        _validate_spawn_payload(mutation.path, mutation.after)

    def _read_path(self, state: BattleState, path: tuple[str, ...]) -> _PathValue:
        head = path[0]
        if head in _BATTLE_SCALAR_TYPES:
            if len(path) != 1:
                raise _ReductionIssue("invalid_path", f"invalid scalar mutation path {path!r}")
            return _PathValue(True, _json_value(getattr(state, head)), "battle_scalar")
        if head == "global_flags":
            if len(path) != 2:
                raise _ReductionIssue("invalid_path", f"global flag path requires one key: {path!r}")
            key = path[1]
            return _mapping_value(state.global_flags, key, "mapping")
        if head == "queues":
            if len(path) != 2:
                raise _ReductionIssue("invalid_path", f"queue path requires one key: {path!r}")
            key = path[1]
            if key not in state.queues:
                return _PathValue(False, None, "queue")
            return _PathValue(True, _json_value(state.queues[key]), "queue")
        if head != "units":
            raise _ReductionIssue("invalid_path", f"unsupported mutation root {head!r}")
        if len(path) < 2:
            raise _ReductionIssue("invalid_path", f"unit path requires unit id: {path!r}")
        unit_id = path[1]
        if len(path) == 2:
            unit = state.units.get(unit_id)
            return _PathValue(
                unit is not None,
                unit_state_to_payload(unit) if unit is not None else None,
                "unit_root",
            )
        unit = state.units.get(unit_id)
        if unit is None:
            raise _ReductionIssue("invalid_path", f"unknown unit {unit_id!r}")
        field_name = path[2]
        if field_name not in UNIT_STATE_MUTABLE_FIELDS:
            raise _ReductionIssue("invalid_path", f"unsupported mutable unit field {field_name!r}")
        if len(path) == 3:
            return _PathValue(True, _json_value(getattr(unit, field_name)), "unit_field")
        if len(path) != 4 or field_name not in {"flags", "resources"}:
            raise _ReductionIssue("invalid_path", f"invalid nested unit path {path!r}")
        kind = "resource_mapping" if field_name == "resources" else "mapping"
        return _mapping_value(getattr(unit, field_name), path[3], kind)

    def _write_path(self, state: BattleState, mutation: Mutation) -> BattleState:
        head = mutation.path[0]
        after = thaw_json(mutation.after)
        if head in _BATTLE_SCALAR_TYPES:
            return replace(state, **{head: after})
        if head == "global_flags":
            return replace(
                state,
                global_flags=_write_mapping(state.global_flags, mutation.path[1], mutation),
            )
        if head == "queues":
            queues = dict(state.queues)
            key = mutation.path[1]
            if mutation.op == "delete":
                queues.pop(key)
            else:
                assert isinstance(after, list)
                queues[key] = tuple(after)
            return replace(state, queues=queues)

        unit_id = mutation.path[1]
        if len(mutation.path) == 2:
            unit = unit_state_from_payload(after)
            units = dict(state.units)
            units[unit_id] = unit
            return replace(state, units=units)

        unit = state.units[unit_id]
        field_name = mutation.path[2]
        if len(mutation.path) == 3:
            value: Any = after
            if field_name == "statuses":
                assert isinstance(value, list)
                value = tuple(value)
            elif field_name == "shield_instances":
                assert isinstance(value, list)
                value = tuple(value)
            elif field_name in {"flags", "resources"}:
                assert isinstance(value, dict)
                value = dict(value)
            unit = replace(unit, **{field_name: value})
        else:
            mapping = getattr(unit, field_name)
            unit = replace(
                unit,
                **{field_name: _write_mapping(mapping, mutation.path[3], mutation)},
            )
        units = dict(state.units)
        units[unit_id] = unit
        return replace(state, units=units)


def _mapping_value(mapping: dict[str, Any], key: str, kind: str) -> _PathValue:
    if key not in mapping:
        return _PathValue(False, None, kind)
    return _PathValue(True, _json_value(mapping[key]), kind)


def _write_mapping(mapping: dict[str, Any], key: str, mutation: Mutation) -> dict[str, Any]:
    updated = dict(mapping)
    if mutation.op == "delete":
        updated.pop(key)
    else:
        updated[key] = thaw_json(mutation.after)
    return updated


def _validate_after_value(path: tuple[str, ...], kind: str, value: JSONValue) -> None:
    if not _is_json_value(value):
        raise _ReductionIssue("invalid_after_type", "after value is not a finite JSON value", expected=value)
    if kind == "battle_scalar":
        expected_type = _BATTLE_SCALAR_TYPES[path[0]]
        if type(value) is not expected_type:
            raise _ReductionIssue(
                "invalid_after_type",
                f"{path[0]} requires {expected_type.__name__}, got {type(value).__name__}",
                expected=value,
            )
        return
    if kind == "queue":
        if not isinstance(value, list):
            raise _ReductionIssue("invalid_after_type", "queue mutation requires a JSON list", expected=value)
        return
    if kind == "resource_mapping":
        if type(value) is not float or not math.isfinite(value):
            raise _ReductionIssue("invalid_after_type", "unit resource values must be finite floats", expected=value)
        return
    if kind == "mapping":
        return
    if kind != "unit_field":
        raise _ReductionIssue("invalid_op_path", f"set is not supported for path kind {kind!r}")

    field_name = path[2]
    try:
        validate_canonical_unit_field_value(field_name, value)
    except (TypeError, ValueError) as exc:
        raise _ReductionIssue(
            "invalid_after_type",
            str(exc),
            expected=value,
        ) from exc


def _validate_spawn_payload(path: tuple[str, ...], payload: JSONValue) -> None:
    try:
        mutable_payload = thaw_json(payload)
        unit = unit_state_from_payload(mutable_payload)
    except (TypeError, ValueError) as exc:
        raise _ReductionIssue("invalid_spawn_payload", str(exc), expected=payload) from exc
    if unit.unit_id != path[1]:
        raise _ReductionIssue(
            "invalid_spawn_payload",
            f"spawn payload unit_id {unit.unit_id!r} does not match path {path[1]!r}",
            expected=payload,
        )
    canonical = unit_state_to_payload(unit)
    if not _typed_equal(canonical, mutable_payload):
        raise _ReductionIssue(
            "invalid_spawn_payload",
            "spawn payload must explicitly and exactly describe the resulting unit",
            expected=payload,
            actual=canonical,
        )


def _json_value(value: Any) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, float) and not math.isfinite(value):
            raise _ReductionIssue("invalid_state_value", "state contains a non-finite float")
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise _ReductionIssue("invalid_state_value", "state mapping contains a non-string key")
        return {key: _json_value(item) for key, item in value.items()}
    raise _ReductionIssue("invalid_state_value", f"state contains non-JSON value {type(value).__name__}")


def _is_json_value(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int, str)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_value(item) for key, item in value.items())
    return False


def _typed_equal(left: Any, right: Any) -> bool:
    return _typed_equal_plain(thaw_json(left), thaw_json(right))


def _typed_equal_plain(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(_typed_equal_plain(a, b) for a, b in zip(left, right))
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_typed_equal_plain(left[key], right[key]) for key in left)
    return bool(left == right)


def _first_mismatch_path(expected: Any, actual: Any, path: tuple[str, ...] = ()) -> tuple[str, ...]:
    if type(expected) is not type(actual):
        return path
    if isinstance(expected, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in expected or key not in actual:
                return (*path, str(key))
            mismatch = _first_mismatch_path(expected[key], actual[key], (*path, str(key)))
            if mismatch:
                return mismatch
        return ()
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return (*path, "length")
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            mismatch = _first_mismatch_path(expected_item, actual_item, (*path, str(index)))
            if mismatch:
                return mismatch
        return ()
    return () if expected == actual else path or ("<root>",)
