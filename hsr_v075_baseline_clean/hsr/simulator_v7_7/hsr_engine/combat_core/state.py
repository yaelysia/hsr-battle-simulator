from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from hsr_engine.kernel import StateChange


class CombatStateError(RuntimeError):
    """Raised when a clean-core state mutation cannot be applied."""


UnitFactory = Callable[[str, dict[str, Any]], Any]
StatusFactory = Callable[[dict[str, Any]], Any]
RecordChange = Callable[[dict[str, Any] | None, StateChange], None]


@dataclass
class StateStore:
    """Explicit read/write boundary for battle state used by clean combat core."""

    state: Any

    @property
    def units(self) -> dict[str, Any]:
        return self.state.units

    def unit(self, unit_id: str) -> Any:
        return self.state.unit(unit_id)

    def queue(self, queue_name: str) -> Any:
        return getattr(self.state, queue_name)

    def snapshot(self) -> dict[str, Any]:
        if hasattr(self.state, "to_json"):
            return self.state.to_json()
        raise CombatStateError("state object does not expose to_json()")


class StateMutator:
    """Apply canonical StateChange records to StateStore.

    This class is the clean-core owner of state mutation semantics. Legacy
    simulator commit helpers may still construct StateChange records, but the
    actual write path goes through this mutator.
    """

    def __init__(
        self,
        store: StateStore,
        *,
        unit_factory: UnitFactory | None = None,
        status_factory: StatusFactory | None = None,
        record_change: RecordChange | None = None,
        queue_normalizer: Callable[[str], str] | None = None,
        error_type: type[Exception] = CombatStateError,
    ) -> None:
        self.store = store
        self.unit_factory = unit_factory
        self.status_factory = status_factory
        self.record_change = record_change
        self.queue_normalizer = queue_normalizer
        self.error_type = error_type

    def _error(self, message: str) -> Exception:
        return self.error_type(message)

    def _queue_name(self, queue_name: str) -> str:
        if self.queue_normalizer is not None:
            return self.queue_normalizer(queue_name)
        queue_name = str(queue_name or "immediate_queue")
        if queue_name == "extra_turn_queue":
            return "interrupt_queue"
        if queue_name not in {"ultimate_queue", "immediate_queue", "interrupt_queue"}:
            raise self._error(f"Unknown queue {queue_name}")
        return queue_name

    def _unit_from_value(self, unit_id: str, value: Any) -> Any:
        raw = deepcopy(value)
        if hasattr(raw, "to_json") and hasattr(raw, "id"):
            return raw
        if isinstance(raw, dict) and self.unit_factory is not None:
            return self.unit_factory(unit_id, raw)
        if isinstance(raw, dict):
            raise self._error(f"Unit StateChange new_value requires a unit_factory: battle.units.{unit_id}")
        raise self._error(f"Unit StateChange new_value must be a dict: battle.units.{unit_id}")

    def _status_from_value(self, raw_value: Any) -> Any:
        raw = deepcopy(raw_value)
        if hasattr(raw, "to_json") and hasattr(raw, "id"):
            return raw
        if isinstance(raw, dict) and self.status_factory is not None:
            return self.status_factory(raw)
        if isinstance(raw, dict):
            raise self._error("Status StateChange new_value requires a status_factory")
        raise self._error("Status StateChange new_value must be a dict")

    def commit_state_change(self, change: StateChange, ctx: dict[str, Any] | None = None) -> StateChange:
        state = self.store.state
        if change.scope == "global" and change.field_path == "global.skill_points":
            state.skill_points = int(change.new_value)
        elif change.scope == "global" and change.field_path == "global.skill_point_cap":
            state.skill_point_cap = int(change.new_value)
        elif change.scope == "global" and change.field_path == "global.av":
            state.av = float(change.new_value)
        elif change.scope == "global" and change.field_path == "global.wave_index":
            state.wave_index = int(change.new_value)
        elif change.scope == "global" and change.field_path.startswith("global.flags."):
            key = change.field_path[len("global.flags."):]
            if change.delta == "remove":
                state.global_flags.pop(key, None)
            else:
                state.global_flags[key] = deepcopy(change.new_value)
        elif change.scope == "battle" and change.field_path.startswith("battle.queues."):
            queue_name = self._queue_name(change.field_path[len("battle.queues."):])
            queue = self.store.queue(queue_name)
            queue.clear()
            queue.extend(deepcopy(change.new_value or []))
        elif change.scope == "battle" and change.field_path.startswith("battle.trigger_usage."):
            key = change.field_path[len("battle.trigger_usage."):]
            if change.delta == "remove":
                state.trigger_usage.pop(key, None)
            else:
                state.trigger_usage[key] = int(change.new_value)
        elif change.scope == "battle" and change.field_path.startswith("battle.units."):
            unit_id = change.field_path[len("battle.units."):]
            if change.new_value is None:
                state.units.pop(unit_id, None)
            else:
                state.units[unit_id] = self._unit_from_value(unit_id, change.new_value)
        elif change.scope == "unit" and change.field_path == "unit.energy":
            self.store.unit(change.subject_id).energy = float(change.new_value)
        elif change.scope == "unit" and change.field_path == "unit.hp":
            self.store.unit(change.subject_id).hp = float(change.new_value)
        elif change.scope == "unit" and change.field_path == "unit.shield":
            self.store.unit(change.subject_id).shield = float(change.new_value)
        elif change.scope == "unit" and change.field_path == "unit.max_hp":
            self.store.unit(change.subject_id).max_hp = float(change.new_value)
        elif change.scope == "unit" and change.field_path == "unit.hp_bars_remaining":
            self.store.unit(change.subject_id).hp_bars_remaining = int(change.new_value)
        elif change.scope == "unit" and change.field_path == "unit.alive":
            self.store.unit(change.subject_id).alive = bool(change.new_value)
        elif change.scope == "unit" and change.field_path == "unit.toughness":
            self.store.unit(change.subject_id).toughness = None if change.new_value is None else float(change.new_value)
        elif change.scope == "unit" and change.field_path == "unit.max_toughness":
            self.store.unit(change.subject_id).max_toughness = None if change.new_value is None else float(change.new_value)
        elif change.scope == "unit" and change.field_path == "unit.is_broken":
            self.store.unit(change.subject_id).is_broken = bool(change.new_value)
        elif change.scope == "unit" and change.field_path == "unit.remaining_av":
            self.store.unit(change.subject_id).remaining_av = float(change.new_value)
        elif change.scope == "unit" and change.field_path.startswith("unit.flags."):
            unit = self.store.unit(change.subject_id)
            key = change.field_path[len("unit.flags."):]
            if change.delta == "remove":
                unit.flags.pop(key, None)
            else:
                unit.flags[key] = deepcopy(change.new_value)
        elif change.scope == "unit" and change.field_path.startswith("unit.actions."):
            unit = self.store.unit(change.subject_id)
            action_id = change.field_path[len("unit.actions."):]
            if change.delta == "remove":
                unit.action_defs.pop(action_id, None)
            else:
                unit.action_defs[action_id] = deepcopy(change.new_value)
        elif change.scope == "unit" and change.field_path.startswith("unit.statuses."):
            self._commit_status_change(change)
        else:
            raise self._error(f"Unsupported StateChange commit path: {change.scope}:{change.field_path}")

        if self.record_change is not None:
            self.record_change(ctx, change)
        return change

    def _commit_status_change(self, change: StateChange) -> None:
        path = change.field_path[len("unit.statuses."):]
        unit = self.store.unit(change.subject_id)
        if "." not in path:
            status_id = path
            if not status_id:
                raise self._error(f"Unsupported status StateChange path: {change.field_path}")
            if change.new_value is None:
                unit.statuses = [row for row in unit.statuses if row.id != status_id]
                return
            raw = deepcopy(change.new_value)
            if hasattr(raw, "to_json"):
                raw = raw.to_json()
            if not isinstance(raw, dict):
                raise self._error(f"Status StateChange new_value must be a dict: {change.field_path}")
            if str(raw.get("id", status_id)) != status_id:
                raise self._error(f"Status StateChange id mismatch: {status_id} != {raw.get('id')}")
            raw["id"] = status_id
            replacement = self._status_from_value(raw)
            for idx, row in enumerate(unit.statuses):
                if row.id == status_id:
                    unit.statuses[idx] = replacement
                    break
            else:
                unit.statuses.append(replacement)
            return

        status = None
        status_field_path = ""
        for row in sorted(unit.statuses, key=lambda item: len(item.id), reverse=True):
            prefix = f"{row.id}."
            if path.startswith(prefix):
                status = row
                status_field_path = path[len(prefix):]
                break
        if status is None or not status_field_path:
            raise self._error(f"Unsupported status StateChange path: {change.field_path}")
        if status_field_path in {"stacks", "max_stacks"}:
            setattr(status, status_field_path, int(change.new_value))
        elif status_field_path == "duration_value":
            status.duration_value = None if change.new_value is None else int(change.new_value)
        elif status_field_path == "duration_type":
            status.duration_type = None if change.new_value is None else str(change.new_value)
        elif status_field_path == "duration_extra_turn_consumes":
            status.duration_extra_turn_consumes = bool(change.new_value)
        elif status_field_path.startswith("modifiers."):
            key = status_field_path[len("modifiers."):]
            if not key:
                raise self._error(f"Unsupported status modifier StateChange path: {change.field_path}")
            status.modifiers[key] = deepcopy(change.new_value)
        else:
            raise self._error(f"Unsupported status StateChange field: {status_field_path}")
