from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .model import BattleState, JSONValue, Mutation, UnitState


@dataclass(frozen=True)
class ReplayResult:
    ok: bool
    expected: dict[str, JSONValue]
    actual: dict[str, JSONValue]
    errors: tuple[str, ...] = ()


class MutationReducer:
    """Applies explicit mutations to BattleState.

    v8 runtime systems should go through this reducer so snapshots can be
    replayed and audited without relying on hidden side effects.
    """

    def apply_all(self, state: BattleState, mutations: tuple[Mutation, ...]) -> BattleState:
        current = state
        for mutation in mutations:
            current = self.apply(current, mutation)
        return current

    def apply(self, state: BattleState, mutation: Mutation) -> BattleState:
        if len(mutation.path) < 1:
            raise ValueError(f"empty mutation path: {mutation}")
        head = mutation.path[0]
        if head == "units":
            return self._apply_unit(state, mutation)
        if head in {"skill_points", "max_skill_points", "wave_index", "rng_state", "event_index"}:
            if len(mutation.path) != 1:
                raise ValueError(f"invalid scalar mutation path: {mutation.path}")
            return replace(state, **{head: mutation.after})
        if head == "global_flags":
            return replace(state, global_flags=self._apply_mapping(state.global_flags, mutation.path[1:], mutation.after))
        if head == "queues":
            queues = dict(state.queues)
            if len(mutation.path) != 2:
                raise ValueError(f"invalid queue mutation path: {mutation.path}")
            queues[mutation.path[1]] = tuple(mutation.after or ())
            return replace(state, queues=queues)
        raise ValueError(f"unsupported mutation root {head!r}")

    def replay_snapshot(
        self,
        before: BattleState,
        mutations: tuple[Mutation, ...],
        expected_after: dict[str, JSONValue],
    ) -> ReplayResult:
        try:
            actual_state = self.apply_all(before, mutations)
            actual = actual_state.snapshot().to_json()
        except Exception as exc:  # pragma: no cover - validation surface
            return ReplayResult(False, expected_after, {}, (str(exc),))
        if actual == expected_after:
            return ReplayResult(True, expected_after, actual)
        return ReplayResult(False, expected_after, actual, ("snapshot mismatch",))

    def _apply_unit(self, state: BattleState, mutation: Mutation) -> BattleState:
        if len(mutation.path) < 3:
            raise ValueError(f"invalid unit mutation path: {mutation.path}")
        _, unit_id, field_name, *rest = mutation.path
        if unit_id not in state.units:
            raise KeyError(f"unknown unit {unit_id!r}")
        unit = state.units[unit_id]
        if rest:
            unit = self._apply_unit_nested(unit, field_name, rest, mutation.after)
        else:
            if not hasattr(unit, field_name):
                raise ValueError(f"unknown unit field {field_name!r}")
            unit = replace(unit, **{field_name: mutation.after})
        units = dict(state.units)
        units[unit_id] = unit
        return replace(state, units=units)

    def _apply_unit_nested(
        self,
        unit: UnitState,
        field_name: str,
        rest: list[str],
        value: JSONValue,
    ) -> UnitState:
        if field_name not in {"flags", "resources"}:
            raise ValueError(f"unsupported nested unit field {field_name!r}")
        current = dict(getattr(unit, field_name))
        updated = self._apply_mapping(current, rest, value)
        return replace(unit, **{field_name: updated})

    def _apply_mapping(self, mapping: dict[str, Any], path: list[str] | tuple[str, ...], value: JSONValue) -> dict[str, Any]:
        if len(path) != 1:
            raise ValueError(f"mapping mutations require exactly one key, got {path}")
        updated = dict(mapping)
        key = path[0]
        if value is None:
            updated.pop(key, None)
        else:
            updated[key] = value
        return updated

