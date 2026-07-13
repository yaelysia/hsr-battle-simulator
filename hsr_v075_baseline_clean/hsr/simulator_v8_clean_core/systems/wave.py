from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..core.model import BattleState, GameEvent, JSONValue, Mutation, UnitState
from ..core.settlement import SettlementRecord
from ..rules.ir import WaveDefinitionIR, WaveMonsterEntryIR
from ..rules.rulebook import RuleBook
from .unit_spawn import UnitSpawnRequest, UnitSpawnSystem, spawn_plans_from_metadata
from .unit_lifecycle import UnitLifecycleSystem


WAVE_RUNTIME_SCHEMA_VERSION = "p1_2_wave_runtime_v1"

WaveTransitionStatus = Literal[
    "no_change",
    "start_current_wave",
    "current_wave_cleared",
    "advance_to_next_wave",
    "battle_victory",
    "battle_defeat",
    "blocked",
]


@dataclass(frozen=True)
class WaveRuntimeView:
    configured: bool
    wave_definition_id: str = ""
    current_wave_index: int = 0
    total_waves: int = 0
    status: str = "not_configured"
    current_wave_unit_ids: tuple[str, ...] = ()
    active_wave_enemy_ids: tuple[str, ...] = ()
    cleared_wave_enemy_ids: tuple[str, ...] = ()
    blocking_enemy_ids: tuple[str, ...] = ()
    blocked_reason: str = ""
    runtime: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "configured": self.configured,
            "wave_definition_id": self.wave_definition_id,
            "current_wave_index": self.current_wave_index,
            "total_waves": self.total_waves,
            "status": self.status,
            "current_wave_unit_ids": list(self.current_wave_unit_ids),
            "active_wave_enemy_ids": list(self.active_wave_enemy_ids),
            "cleared_wave_enemy_ids": list(self.cleared_wave_enemy_ids),
            "blocking_enemy_ids": list(self.blocking_enemy_ids),
            "blocked_reason": self.blocked_reason,
            "runtime": self.runtime,
        }


@dataclass(frozen=True)
class WaveTransitionPlan:
    ok: bool
    status: WaveTransitionStatus
    wave_definition_id: str = ""
    current_wave_index: int = 0
    next_wave_index: int | None = None
    cleared_unit_ids: tuple[str, ...] = ()
    blocking_unit_ids: tuple[str, ...] = ()
    spawn_entries: tuple[WaveMonsterEntryIR, ...] = ()
    spawn_requests: tuple[UnitSpawnRequest, ...] = ()
    spawn_unit_plans: tuple[dict[str, JSONValue], ...] = ()
    remove_unit_ids: tuple[str, ...] = ()
    blocked_reason: str = ""
    source_trace: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "status": self.status,
            "wave_definition_id": self.wave_definition_id,
            "current_wave_index": self.current_wave_index,
            "next_wave_index": self.next_wave_index,
            "cleared_unit_ids": list(self.cleared_unit_ids),
            "blocking_unit_ids": list(self.blocking_unit_ids),
            "spawn_entries": [entry.to_json() for entry in self.spawn_entries],
            "spawn_requests": [request.to_json() for request in self.spawn_requests],
            "spawn_unit_plans": list(self.spawn_unit_plans),
            "remove_unit_ids": list(self.remove_unit_ids),
            "blocked_reason": self.blocked_reason,
            "source_trace": self.source_trace,
        }


@dataclass(frozen=True)
class WaveTransitionResult:
    plan: WaveTransitionPlan
    mutations: tuple[Mutation, ...]
    events: tuple[GameEvent, ...]
    records: tuple[dict[str, JSONValue], ...]


class WaveSystem:
    def __init__(self, rules: RuleBook) -> None:
        self.rules = rules
        self.lifecycle = UnitLifecycleSystem()
        self.unit_spawn = UnitSpawnSystem()

    def view(self, state: BattleState) -> WaveRuntimeView:
        runtime = _wave_runtime(state)
        if not runtime:
            return WaveRuntimeView(configured=False)
        current_wave_index = _runtime_int(runtime, "current_wave_index", state.wave_index)
        current_ids = tuple(_string_items(runtime.get("current_wave_unit_ids")))
        active_wave_ids: list[str] = []
        cleared_ids: list[str] = []
        blocking_ids: list[str] = []
        for unit_id in current_ids:
            lifecycle = self.lifecycle.view(state, unit_id)
            if lifecycle.is_active:
                active_wave_ids.append(unit_id)
            elif lifecycle.is_defeated or lifecycle.is_removed:
                cleared_ids.append(unit_id)
        for unit_id, unit in sorted(state.units.items()):
            if unit.side != "enemy" or self.lifecycle.status_of(unit) != "active":
                continue
            reason = _active_enemy_block_reason(unit, current_wave_index)
            if reason:
                blocking_ids.append(unit_id)
        return WaveRuntimeView(
            configured=True,
            wave_definition_id=str(runtime.get("wave_definition_id") or ""),
            current_wave_index=current_wave_index,
            total_waves=_runtime_int(runtime, "total_waves", 0),
            status=str(runtime.get("status") or "active"),
            current_wave_unit_ids=current_ids,
            active_wave_enemy_ids=tuple(active_wave_ids),
            cleared_wave_enemy_ids=tuple(cleared_ids),
            blocking_enemy_ids=tuple(blocking_ids),
            blocked_reason=str(runtime.get("blocked_reason") or ""),
            runtime=runtime,
        )

    def plan_transition(self, state: BattleState) -> WaveTransitionPlan:
        runtime = _wave_runtime(state)
        if not runtime:
            return WaveTransitionPlan(ok=True, status="no_change", blocked_reason="wave_runtime_not_configured")
        wave_definition_id = str(runtime.get("wave_definition_id") or "")
        current_wave_index = _runtime_int(runtime, "current_wave_index", state.wave_index)
        if _has_pending_queue(state):
            return self._blocked(
                wave_definition_id,
                current_wave_index,
                "pending_queue_before_wave_transition",
                source_trace=_runtime_source_trace(runtime),
            )
        definition = self.rules.wave_definition(wave_definition_id)
        if definition is None:
            return self._blocked(
                wave_definition_id,
                current_wave_index,
                "wave_definition_missing",
                source_trace=_runtime_source_trace(runtime),
            )
        if definition.coverage_status != "executable":
            return self._blocked(
                wave_definition_id,
                current_wave_index,
                definition.blocked_reason or f"wave_definition_not_executable:{definition.coverage_status}",
                source_trace=definition.source.to_json(),
            )
        definition_reason = _wave_definition_payload_blocked_reason(definition)
        if definition_reason:
            return self._blocked(
                wave_definition_id,
                current_wave_index,
                definition_reason,
                source_trace=definition.source.to_json(),
            )
        if _active_ally_count(state, self.lifecycle) == 0:
            return WaveTransitionPlan(
                ok=True,
                status="battle_defeat",
                wave_definition_id=wave_definition_id,
                current_wave_index=current_wave_index,
                source_trace=definition.source.to_json(),
            )
        current_ids = tuple(_string_items(runtime.get("current_wave_unit_ids")))
        if not current_ids:
            return self._blocked(
                wave_definition_id,
                current_wave_index,
                "current_wave_unit_ids_missing",
                source_trace=definition.source.to_json(),
            )
        if str(runtime.get("status") or "") == "pending_start":
            entries = self.rules.wave_entries_for_wave(wave_definition_id, current_wave_index)
            entry_reason = _wave_entries_payload_blocked_reason(definition, entries, current_wave_index)
            if entry_reason:
                return self._blocked(
                    wave_definition_id,
                    current_wave_index,
                    entry_reason,
                    source_trace=definition.source.to_json(),
                )
            expected_ids = tuple(_wave_unit_id(definition, entry) for entry in entries)
            if current_ids != expected_ids:
                return self._blocked(
                    wave_definition_id,
                    current_wave_index,
                    "current_wave_unit_entry_mismatch",
                    blocking_unit_ids=current_ids,
                    source_trace=definition.source.to_json(),
                )
            missing_ids = tuple(unit_id for unit_id in current_ids if unit_id not in state.units)
            if missing_ids:
                return self._blocked(
                    wave_definition_id,
                    current_wave_index,
                    "current_wave_unit_missing",
                    blocking_unit_ids=missing_ids,
                    source_trace=definition.source.to_json(),
                )
            return WaveTransitionPlan(
                ok=True,
                status="start_current_wave",
                wave_definition_id=wave_definition_id,
                current_wave_index=current_wave_index,
                next_wave_index=current_wave_index,
                spawn_entries=entries,
                source_trace=definition.source.to_json(),
            )
        blocking = _blocking_active_enemies(state, self.lifecycle, current_wave_index)
        if blocking:
            return self._blocked(
                wave_definition_id,
                current_wave_index,
                str(blocking[0]["reason"]),
                blocking_unit_ids=tuple(str(item["unit_id"]) for item in blocking),
                source_trace=definition.source.to_json(),
            )
        active_current = tuple(
            unit_id
            for unit_id in current_ids
            if unit_id in state.units and self.lifecycle.status_of(state.units[unit_id]) == "active"
        )
        if active_current:
            return WaveTransitionPlan(
                ok=True,
                status="no_change",
                wave_definition_id=wave_definition_id,
                current_wave_index=current_wave_index,
                blocking_unit_ids=active_current,
                source_trace=definition.source.to_json(),
            )
        missing_current = tuple(unit_id for unit_id in current_ids if unit_id not in state.units)
        if missing_current:
            return self._blocked(
                wave_definition_id,
                current_wave_index,
                "current_wave_unit_missing",
                blocking_unit_ids=missing_current,
                source_trace=definition.source.to_json(),
            )
        remove_ids = tuple(
            unit_id
            for unit_id in current_ids
            if unit_id in state.units and self.lifecycle.status_of(state.units[unit_id]) != "removed"
        )
        cleared_ids = tuple(unit_id for unit_id in current_ids if unit_id in state.units)
        next_wave_index = current_wave_index + 1
        if next_wave_index >= int(definition.wave_count):
            return WaveTransitionPlan(
                ok=True,
                status="battle_victory",
                wave_definition_id=wave_definition_id,
                current_wave_index=current_wave_index,
                cleared_unit_ids=cleared_ids,
                remove_unit_ids=remove_ids,
                source_trace=definition.source.to_json(),
            )
        spawn_entries = self.rules.wave_entries_for_wave(wave_definition_id, next_wave_index)
        if not spawn_entries:
            return self._blocked(
                wave_definition_id,
                current_wave_index,
                "next_wave_entries_missing",
                blocking_unit_ids=cleared_ids,
                source_trace=definition.source.to_json(),
            )
        spawn_unit_plans: list[dict[str, JSONValue]] = []
        spawn_requests: list[UnitSpawnRequest] = []
        for entry in spawn_entries:
            if entry.coverage_status != "executable":
                return self._blocked(
                    wave_definition_id,
                    current_wave_index,
                    entry.blocked_reason or f"wave_entry_not_executable:{entry.coverage_status}",
                    blocking_unit_ids=cleared_ids,
                    source_trace=entry.source.to_json(),
                )
            entry_reason = _wave_entry_payload_blocked_reason(definition, entry, next_wave_index)
            if entry_reason:
                return self._blocked(
                    wave_definition_id,
                    current_wave_index,
                    entry_reason,
                    blocking_unit_ids=cleared_ids,
                    source_trace=entry.source.to_json(),
                )
            unit_id = _wave_unit_id(definition, entry)
            if unit_id in state.units:
                return self._blocked(
                    wave_definition_id,
                    current_wave_index,
                    "next_wave_unit_id_already_exists",
                    blocking_unit_ids=(unit_id,),
                    source_trace=entry.source.to_json(),
                )
            template = self.rules.unit_birth_template(entry.birth_template_id)
            if template is None:
                return self._blocked(
                    wave_definition_id,
                    current_wave_index,
                    "wave_unit_birth_template_missing",
                    blocking_unit_ids=cleared_ids,
                    source_trace=entry.source.to_json(),
                )
            spawn_request = UnitSpawnRequest(
                spawn_kind="wave_enemy",
                unit_id=unit_id,
                birth_template_id=entry.birth_template_id,
                entity_ref=entry.monster_entity_ref,
                source_id=definition.wave_definition_id,
                entry_id=entry.entry_id,
                wave_definition_id=definition.wave_definition_id,
                stage_id=definition.stage_id,
                wave_index=entry.wave_index,
                position=entry.position,
                source_trace=definition.source.to_json(),
                entry_source_trace=entry.source.to_json(),
            )
            spawn_plan = self.unit_spawn.plan(template, spawn_request)
            if not spawn_plan.ok:
                return self._blocked(
                    wave_definition_id,
                    current_wave_index,
                    spawn_plan.blocked_reason or "wave_unit_spawn_plan_blocked",
                    blocking_unit_ids=cleared_ids,
                    source_trace=spawn_plan.source_trace or entry.source.to_json(),
                )
            spawn_requests.append(spawn_request)
            spawn_unit_plans.append(spawn_plan.to_json())
        return WaveTransitionPlan(
            ok=True,
            status="advance_to_next_wave",
            wave_definition_id=wave_definition_id,
            current_wave_index=current_wave_index,
            next_wave_index=next_wave_index,
            cleared_unit_ids=cleared_ids,
            spawn_entries=spawn_entries,
            spawn_requests=tuple(spawn_requests),
            spawn_unit_plans=tuple(spawn_unit_plans),
            remove_unit_ids=remove_ids,
            source_trace=definition.source.to_json(),
        )

    def apply_transition(self, state: BattleState, plan: WaveTransitionPlan | None = None) -> WaveTransitionResult:
        plan = plan or self.plan_transition(state)
        if plan.status in {"no_change", "blocked", "current_wave_cleared"}:
            return WaveTransitionResult(plan, (), (), (_plan_record(plan, (), process_only=True),))
        runtime = _wave_runtime(state)
        definition = self.rules.wave_definition(plan.wave_definition_id)
        source_trace = plan.source_trace
        if definition is not None:
            source_trace = definition.source.to_json()
        if definition is None:
            blocked = self._blocked(
                plan.wave_definition_id,
                plan.current_wave_index,
                "wave_definition_missing",
                source_trace=source_trace,
            )
            return WaveTransitionResult(blocked, (), (), (_plan_record(blocked, (), process_only=True),))
        if plan.status == "battle_defeat":
            mutations = _battle_end_mutations(state, runtime, plan, outcome="defeat", source_trace=source_trace)
            return WaveTransitionResult(
                plan,
                mutations,
                (
                    GameEvent(
                        "battle.defeat",
                        source_id="wave_system",
                        event_id=f"event:{state.event_index}:battle:defeat",
                        window="wave_transition",
                        process_only=True,
                        payload={"wave_transition_plan": plan.to_json(), "source_trace": source_trace},
                    ),
                    _battle_completed_event(state, definition, plan, "defeat", source_trace),
                ),
                _plan_records(plan, mutations, process_only=False),
            )
        if plan.status == "start_current_wave":
            entries = plan.spawn_entries
            units = tuple(state.units.get(_wave_unit_id(definition, entry)) for entry in entries)
            if not entries or any(unit is None for unit in units):
                blocked = self._blocked(
                    plan.wave_definition_id,
                    plan.current_wave_index,
                    "current_wave_start_payload_incomplete",
                    source_trace=source_trace,
                )
                return WaveTransitionResult(blocked, (), (), (_plan_record(blocked, (), process_only=True),))
            runtime_after = _runtime_after_current_started(runtime, plan)
            mutations = (_runtime_mutation(state, runtime, runtime_after, plan, source_trace),)
            concrete_units = tuple(unit for unit in units if unit is not None)
            events = (
                _wave_started_event(state, definition, plan.current_wave_index, concrete_units, source_trace),
                *(
                    _wave_monster_event(state, definition, entry, unit)
                    for entry, unit in zip(entries, concrete_units, strict=True)
                ),
            )
            return WaveTransitionResult(plan, mutations, events, _plan_records(plan, mutations, process_only=False))
        if plan.status == "battle_victory":
            remove_mutations = _remove_mutations(self.lifecycle, state, plan, source_trace)
            runtime_after = _runtime_after_battle_end(runtime, plan, outcome="victory")
            mutations = (
                *remove_mutations,
                _runtime_mutation(state, runtime, runtime_after, plan, source_trace),
                *_battle_outcome_mutations(state, "victory", source_trace),
            )
            return WaveTransitionResult(
                plan,
                mutations,
                (
                    _wave_cleared_event(state, plan, source_trace, stage_id=definition.stage_id),
                    GameEvent(
                        "battle.victory",
                        source_id="wave_system",
                        event_id=f"event:{state.event_index}:battle:victory",
                        window="wave_transition",
                        process_only=True,
                        payload={"wave_transition_plan": plan.to_json(), "source_trace": source_trace},
                    ),
                    _battle_completed_event(state, definition, plan, "victory", source_trace),
                ),
                _plan_records(plan, mutations, process_only=False),
            )
        if plan.status == "advance_to_next_wave":
            next_index = int(plan.next_wave_index) if plan.next_wave_index is not None else plan.current_wave_index + 1
            remove_mutations = _remove_mutations(self.lifecycle, state, plan, source_trace)
            runtime_cleared = _runtime_after_current_cleared(runtime, plan)
            spawn_plans = spawn_plans_from_metadata({"unit_spawn_plans": list(plan.spawn_unit_plans)})
            if not spawn_plans:
                blocked = self._blocked(
                    plan.wave_definition_id,
                    plan.current_wave_index,
                    "wave_unit_spawn_plan_missing",
                    source_trace=source_trace,
                )
                return WaveTransitionResult(blocked, (), (), (_plan_record(blocked, (), process_only=True),))
            request_reason = _wave_spawn_request_plan_blocked_reason(plan, definition, next_index)
            if request_reason:
                blocked = self._blocked(
                    plan.wave_definition_id,
                    plan.current_wave_index,
                    request_reason,
                    source_trace=source_trace,
                )
                return WaveTransitionResult(blocked, (), (), (_plan_record(blocked, (), process_only=True),))
            try:
                spawn_units = tuple(
                    spawn_plan.to_unit(expected_request=request)
                    for spawn_plan, request in zip(spawn_plans, plan.spawn_requests, strict=True)
                )
            except ValueError as exc:
                blocked = self._blocked(
                    plan.wave_definition_id,
                    plan.current_wave_index,
                    f"wave_unit_spawn_plan_invalid:{exc}",
                    source_trace=source_trace,
                )
                return WaveTransitionResult(blocked, (), (), (_plan_record(blocked, (), process_only=True),))
            if len(spawn_units) != len(plan.spawn_entries):
                blocked = self._blocked(
                    plan.wave_definition_id,
                    plan.current_wave_index,
                    "wave_unit_spawn_plan_entry_mismatch",
                    source_trace=source_trace,
                )
                return WaveTransitionResult(blocked, (), (), (_plan_record(blocked, (), process_only=True),))
            spawn_mutations = tuple(
                self.lifecycle.spawn_mutation(
                    state,
                    unit,
                    reason="spawn next wave enemy",
                    source="wave_system",
                    source_trace=dict(unit.flags.get("wave_entry_source_trace", {}))
                    if isinstance(unit.flags.get("wave_entry_source_trace"), dict)
                    else {},
                    metadata={
                        "wave_definition_id": definition.wave_definition_id,
                        "stage_id": definition.stage_id,
                        "wave_index": next_index,
                        "wave_entry_id": str(unit.flags.get("wave_entry_id") or ""),
                        "source_trace": dict(unit.flags.get("wave_entry_source_trace", {}))
                        if isinstance(unit.flags.get("wave_entry_source_trace"), dict)
                        else {},
                    },
                )
                for unit in spawn_units
            )
            runtime_after = _runtime_after_next_started(runtime_cleared, plan, tuple(unit.unit_id for unit in spawn_units))
            mutations = (
                *remove_mutations,
                _runtime_mutation(state, runtime, runtime_cleared, plan, source_trace),
                _wave_index_mutation(state, next_index, plan, source_trace),
                *spawn_mutations,
                _runtime_mutation(
                    state,
                    runtime_cleared,
                    runtime_after,
                    plan,
                    source_trace,
                    before_exists=True,
                ),
            )
            events = (
                _wave_cleared_event(state, plan, source_trace, stage_id=definition.stage_id),
                _wave_started_event(state, definition, next_index, spawn_units, source_trace),
                *(
                    _wave_monster_event(state, definition, entry, unit)
                    for entry, unit in zip(plan.spawn_entries, spawn_units, strict=True)
                ),
            )
            return WaveTransitionResult(plan, mutations, events, _plan_records(plan, mutations, process_only=False))
        return WaveTransitionResult(plan, (), (), (_plan_record(plan, (), process_only=True),))

    def blocked(self, state: BattleState, reason: str) -> WaveTransitionResult:
        runtime = _wave_runtime(state)
        plan = self._blocked(
            str(runtime.get("wave_definition_id") or "") if runtime else "",
            _runtime_int(runtime, "current_wave_index", state.wave_index) if runtime else state.wave_index,
            reason,
            source_trace=_runtime_source_trace(runtime),
        )
        return WaveTransitionResult(plan, (), (), (_plan_record(plan, (), process_only=True),))

    def _blocked(
        self,
        wave_definition_id: str,
        current_wave_index: int,
        reason: str,
        *,
        blocking_unit_ids: tuple[str, ...] = (),
        source_trace: dict[str, JSONValue] | None = None,
    ) -> WaveTransitionPlan:
        return WaveTransitionPlan(
            ok=False,
            status="blocked",
            wave_definition_id=wave_definition_id,
            current_wave_index=current_wave_index,
            blocking_unit_ids=blocking_unit_ids,
            blocked_reason=reason,
            source_trace=source_trace or {},
        )


def _wave_runtime(state: BattleState) -> dict[str, JSONValue]:
    runtime = state.global_flags.get("wave_runtime")
    if isinstance(runtime, dict) and runtime.get("schema_version") == WAVE_RUNTIME_SCHEMA_VERSION:
        return dict(runtime)
    return {}


def _runtime_int(runtime: dict[str, JSONValue] | None, key: str, default: int) -> int:
    if not runtime:
        return default
    value = runtime.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return default


def _runtime_source_trace(runtime: dict[str, JSONValue] | None) -> dict[str, JSONValue]:
    if not runtime:
        return {}
    source_trace = runtime.get("source_trace")
    return dict(source_trace) if isinstance(source_trace, dict) else {}


def _string_items(value: JSONValue) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, list):
        return tuple(str(item) for item in value if isinstance(item, str) and item)
    return ()


def _has_pending_queue(state: BattleState) -> bool:
    return any(bool(entries) for entries in state.queues.values())


def _active_ally_count(state: BattleState, lifecycle: UnitLifecycleSystem) -> int:
    return sum(1 for unit in state.units.values() if unit.side == "ally" and lifecycle.status_of(unit) == "active")


def _blocking_active_enemies(
    state: BattleState,
    lifecycle: UnitLifecycleSystem,
    current_wave_index: int,
) -> tuple[dict[str, JSONValue], ...]:
    blocking: list[dict[str, JSONValue]] = []
    for unit_id, unit in sorted(state.units.items()):
        if unit.side != "enemy" or lifecycle.status_of(unit) != "active":
            continue
        reason = _active_enemy_block_reason(unit, current_wave_index)
        if reason:
            blocking.append({"unit_id": unit_id, "reason": reason})
    return tuple(blocking)


def _active_enemy_block_reason(unit: UnitState, current_wave_index: int) -> str:
    kind = unit.flags.get("wave_member_kind")
    if kind == "stage_wave_enemy":
        if unit.flags.get("wave_index") != current_wave_index:
            return "active_enemy_outside_current_wave"
        return ""
    if kind == "enemy_summon":
        return "" if unit.flags.get("wave_clear_policy") == "ignore" else "active_enemy_summon_blocks_wave_clear"
    return "active_enemy_without_wave_membership"


def _wave_definition_payload_blocked_reason(definition: WaveDefinitionIR) -> str:
    if not definition.wave_definition_id:
        return "wave_definition_id_missing"
    if not definition.stage_id:
        return "wave_stage_id_missing"
    return ""


def _wave_entries_payload_blocked_reason(
    definition: WaveDefinitionIR,
    entries: tuple[WaveMonsterEntryIR, ...],
    wave_index: int,
) -> str:
    if not entries:
        return "wave_entries_missing"
    for entry in entries:
        reason = _wave_entry_payload_blocked_reason(definition, entry, wave_index)
        if reason:
            return reason
    return ""


def _wave_entry_payload_blocked_reason(
    definition: WaveDefinitionIR,
    entry: WaveMonsterEntryIR,
    wave_index: int,
) -> str:
    if entry.coverage_status != "executable":
        return entry.blocked_reason or f"wave_entry_not_executable:{entry.coverage_status}"
    if not entry.entry_id:
        return "wave_entry_id_missing"
    if entry.wave_index != wave_index:
        return "wave_entry_index_mismatch"
    if not entry.birth_template_id:
        return "wave_entry_birth_template_missing"
    if not entry.monster_entity_ref:
        return "wave_entry_monster_entity_missing"
    if definition.stage_id == "":
        return "wave_stage_id_missing"
    return ""


def _wave_spawn_request_plan_blocked_reason(
    plan: WaveTransitionPlan,
    definition: WaveDefinitionIR,
    next_wave_index: int,
) -> str:
    if len(plan.spawn_requests) != len(plan.spawn_entries) or len(plan.spawn_requests) != len(plan.spawn_unit_plans):
        return "wave_spawn_request_count_mismatch"
    for request, entry in zip(plan.spawn_requests, plan.spawn_entries, strict=True):
        if request.spawn_kind != "wave_enemy":
            return "wave_spawn_request_kind_mismatch"
        if request.unit_id != _wave_unit_id(definition, entry):
            return "wave_spawn_request_unit_id_mismatch"
        if request.birth_template_id != entry.birth_template_id or request.entity_ref != entry.monster_entity_ref:
            return "wave_spawn_request_birth_template_mismatch"
        if request.source_id != definition.wave_definition_id or request.wave_definition_id != definition.wave_definition_id:
            return "wave_spawn_request_definition_mismatch"
        if request.stage_id != definition.stage_id or request.wave_index != next_wave_index:
            return "wave_spawn_request_stage_mismatch"
        if request.entry_id != entry.entry_id or request.position != entry.position:
            return "wave_spawn_request_entry_mismatch"
    return ""


def _wave_unit_id(definition: WaveDefinitionIR, entry: WaveMonsterEntryIR) -> str:
    return f"enemy:stage:{definition.stage_id}:wave:{entry.wave_index}:pos:{entry.position}"


def _remove_mutations(
    lifecycle: UnitLifecycleSystem,
    state: BattleState,
    plan: WaveTransitionPlan,
    source_trace: dict[str, JSONValue],
) -> tuple[Mutation, ...]:
    mutations: list[Mutation] = []
    for unit_id in plan.remove_unit_ids:
        mutations.extend(_status_cleanup_mutations(state, unit_id, plan, source_trace))
        mutations.extend(
            lifecycle.remove_mutations(
                state,
                unit_id,
                reason="remove cleared wave enemy",
                source="wave_system",
                removed_record={
                    "reason": "wave_cleared",
                    "wave_definition_id": plan.wave_definition_id,
                    "wave_index": plan.current_wave_index,
                    "source_trace": source_trace,
                },
                source_trace=source_trace,
            )
        )
    return tuple(mutations)


def _status_cleanup_mutations(
    state: BattleState,
    unit_id: str,
    plan: WaveTransitionPlan,
    source_trace: dict[str, JSONValue],
) -> tuple[Mutation, ...]:
    unit = state.units.get(unit_id)
    if unit is None:
        return ()
    mutations: list[Mutation] = []
    metadata = {
        "wave_transition_plan": plan.to_json(),
        "lifecycle_operation": "wave_status_cleanup",
        "unit_id": unit_id,
        "source_trace": source_trace,
    }
    if unit.statuses:
        mutations.append(
            Mutation(
                op="set",
                path=("units", unit_id, "statuses"),
                before=list(unit.statuses),
                after=[],
                reason="clear statuses for removed wave unit",
                source="wave_system",
                metadata={**metadata, "status_cleanup_operation": "clear_statuses"},
                mutation_id=f"mutation:wave_status_cleanup:{unit_id}:statuses:{plan.current_wave_index}",
            )
        )
    if "status_details" in unit.flags:
        mutations.append(
            Mutation(
                op="delete",
                path=("units", unit_id, "flags", "status_details"),
                before=unit.flags.get("status_details"),
                after=None,
                reason="clear status details for removed wave unit",
                source="wave_system",
                after_exists=False,
                metadata={**metadata, "status_cleanup_operation": "clear_status_details"},
                mutation_id=f"mutation:wave_status_cleanup:{unit_id}:status_details:{plan.current_wave_index}",
            )
        )
    return tuple(mutations)


def _runtime_after_current_cleared(runtime: dict[str, JSONValue], plan: WaveTransitionPlan) -> dict[str, JSONValue]:
    after = dict(runtime)
    cleared = set(_runtime_int_items(after.get("cleared_wave_indices")))
    cleared.add(plan.current_wave_index)
    after["cleared_wave_indices"] = sorted(cleared)
    removed = dict(after.get("removed_unit_ids_by_wave")) if isinstance(after.get("removed_unit_ids_by_wave"), dict) else {}
    removed[str(plan.current_wave_index)] = list(plan.remove_unit_ids)
    after["removed_unit_ids_by_wave"] = removed
    after["status"] = "between_waves"
    after["blocked_reason"] = ""
    return after


def _runtime_after_current_started(runtime: dict[str, JSONValue], plan: WaveTransitionPlan) -> dict[str, JSONValue]:
    after = dict(runtime)
    started = set(_runtime_int_items(after.get("started_wave_indices")))
    started.add(plan.current_wave_index)
    after["started_wave_indices"] = sorted(started)
    after["status"] = "active"
    after["blocked_reason"] = ""
    return after


def _runtime_after_next_started(
    runtime: dict[str, JSONValue],
    plan: WaveTransitionPlan,
    spawned_unit_ids: tuple[str, ...],
) -> dict[str, JSONValue]:
    next_wave_index = int(plan.next_wave_index) if plan.next_wave_index is not None else plan.current_wave_index + 1
    after = dict(runtime)
    started = set(_runtime_int_items(after.get("started_wave_indices")))
    started.add(next_wave_index)
    spawned = dict(after.get("spawned_unit_ids_by_wave")) if isinstance(after.get("spawned_unit_ids_by_wave"), dict) else {}
    spawned[str(next_wave_index)] = list(spawned_unit_ids)
    after["current_wave_index"] = next_wave_index
    after["started_wave_indices"] = sorted(started)
    after["current_wave_unit_ids"] = list(spawned_unit_ids)
    after["spawned_unit_ids_by_wave"] = spawned
    after["status"] = "active"
    after["blocked_reason"] = ""
    return after


def _runtime_after_battle_end(
    runtime: dict[str, JSONValue],
    plan: WaveTransitionPlan,
    *,
    outcome: str,
) -> dict[str, JSONValue]:
    after = _runtime_after_current_cleared(runtime, plan) if runtime else {}
    after["status"] = outcome
    after["current_wave_unit_ids"] = []
    after["blocked_reason"] = ""
    return after


def _runtime_int_items(value: JSONValue) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    items: list[int] = []
    for item in value:
        if isinstance(item, int) and not isinstance(item, bool):
            items.append(item)
    return tuple(items)


def _runtime_mutation(
    state: BattleState,
    before: dict[str, JSONValue],
    after: dict[str, JSONValue],
    plan: WaveTransitionPlan,
    source_trace: dict[str, JSONValue],
    *,
    before_exists: bool | None = None,
) -> Mutation:
    path_exists = "wave_runtime" in state.global_flags if before_exists is None else before_exists
    return Mutation(
        op="set",
        path=("global_flags", "wave_runtime"),
        before=before if path_exists else None,
        after=after,
        reason="update wave runtime state",
        source="wave_system",
        before_exists=path_exists,
        metadata={
            "wave_transition_plan": plan.to_json(),
            "source_trace": source_trace,
        },
        mutation_id=(
            f"mutation:wave_runtime:{state.event_index}:{plan.status}:"
            f"{plan.current_wave_index}:{plan.next_wave_index}:{after.get('status', '')}:"
            f"{after.get('current_wave_index', '')}"
        ),
    )


def _wave_index_mutation(
    state: BattleState,
    next_wave_index: int,
    plan: WaveTransitionPlan,
    source_trace: dict[str, JSONValue],
) -> Mutation:
    return Mutation(
        op="set",
        path=("wave_index",),
        before=state.wave_index,
        after=next_wave_index,
        reason="advance to next wave",
        source="wave_system",
        metadata={
            "wave_transition_plan": plan.to_json(),
            "source_trace": source_trace,
        },
        mutation_id=f"mutation:wave_index:{state.event_index}:{plan.current_wave_index}:{next_wave_index}",
    )


def _battle_end_mutations(
    state: BattleState,
    runtime: dict[str, JSONValue],
    plan: WaveTransitionPlan,
    *,
    outcome: str,
    source_trace: dict[str, JSONValue],
) -> tuple[Mutation, ...]:
    mutations: list[Mutation] = []
    if runtime:
        runtime_after = dict(runtime)
        runtime_after["status"] = outcome
        runtime_after["blocked_reason"] = ""
        mutations.append(_runtime_mutation(state, runtime, runtime_after, plan, source_trace))
    mutations.extend(_battle_outcome_mutations(state, outcome, source_trace))
    return tuple(mutations)


def _battle_outcome_mutations(
    state: BattleState,
    outcome: str,
    source_trace: dict[str, JSONValue],
) -> tuple[Mutation, ...]:
    return (
        Mutation(
            op="set",
            path=("global_flags", "battle_outcome"),
            before=state.global_flags.get("battle_outcome"),
            after=outcome,
            reason="battle ended by wave system",
            source="wave_system",
            before_exists="battle_outcome" in state.global_flags,
            metadata={"source_trace": source_trace, "outcome": outcome},
            mutation_id=f"mutation:battle_outcome:{state.event_index}:{outcome}",
        ),
        Mutation(
            op="set",
            path=("global_flags", "phase"),
            before=state.global_flags.get("phase"),
            after="ended",
            reason="battle ended by wave system",
            source="wave_system",
            before_exists="phase" in state.global_flags,
            metadata={"source_trace": source_trace, "outcome": outcome},
            mutation_id=f"mutation:battle_phase:{state.event_index}:{outcome}",
        ),
        Mutation(
            op="set",
            path=("global_flags", "current_window"),
            before=state.global_flags.get("current_window"),
            after="battle_end",
            reason="battle ended by wave system",
            source="wave_system",
            before_exists="current_window" in state.global_flags,
            metadata={"source_trace": source_trace, "outcome": outcome},
            mutation_id=f"mutation:battle_window:{state.event_index}:{outcome}",
        ),
    )


def _wave_cleared_event(
    state: BattleState,
    plan: WaveTransitionPlan,
    source_trace: dict[str, JSONValue],
    *,
    stage_id: str,
) -> GameEvent:
    return GameEvent(
        "wave.cleared",
        source_id="wave_system",
        event_id=f"event:{state.event_index}:wave:{plan.current_wave_index}:cleared",
        window="wave_transition",
        process_only=True,
        payload={
            "wave_definition_id": plan.wave_definition_id,
            "stage_id": stage_id,
            "wave_index": plan.current_wave_index,
            "cleared_unit_ids": list(plan.cleared_unit_ids),
            "removed_unit_ids": list(plan.remove_unit_ids),
            "source_trace": source_trace,
        },
    )


def _wave_started_event(
    state: BattleState,
    definition: WaveDefinitionIR,
    wave_index: int,
    units: tuple[UnitState, ...],
    source_trace: dict[str, JSONValue],
) -> GameEvent:
    return GameEvent(
        "wave.started",
        source_id="wave_system",
        event_id=f"event:{state.event_index}:wave:{wave_index}:started",
        window="wave_transition",
        process_only=True,
        payload={
            "wave_definition_id": definition.wave_definition_id,
            "stage_id": definition.stage_id,
            "wave_index": wave_index,
            "unit_ids": [unit.unit_id for unit in units],
            "source_trace": source_trace,
        },
    )


def _battle_completed_event(
    state: BattleState,
    definition: WaveDefinitionIR,
    plan: WaveTransitionPlan,
    outcome: str,
    source_trace: dict[str, JSONValue],
) -> GameEvent:
    return GameEvent(
        "battle.completed",
        source_id="wave_system",
        event_id=f"event:{state.event_index}:battle:completed:{outcome}",
        window="wave_transition",
        process_only=True,
        payload={
            "outcome": outcome,
            "wave_definition_id": definition.wave_definition_id,
            "stage_id": definition.stage_id,
            "wave_index": plan.current_wave_index,
            "source_trace": source_trace,
        },
    )


def _wave_monster_event(
    state: BattleState,
    definition: WaveDefinitionIR,
    entry: WaveMonsterEntryIR,
    unit: UnitState,
) -> GameEvent:
    return GameEvent(
        "wave.monster",
        source_id="wave_system",
        target_id=unit.unit_id,
        event_id=f"event:{state.event_index}:wave:{entry.wave_index}:monster:{entry.position}",
        window="wave_transition",
        process_only=True,
        payload={
            "wave_definition_id": definition.wave_definition_id,
            "stage_id": definition.stage_id,
            "wave_index": entry.wave_index,
            "unit_id": unit.unit_id,
            "entry_id": entry.entry_id,
            "position": entry.position,
            "monster_entity_ref": entry.monster_entity_ref,
            "monster_raw_id": entry.monster_raw_id,
            "source_trace": entry.source.to_json(),
        },
    )


def _plan_record(
    plan: WaveTransitionPlan,
    mutations: tuple[Mutation, ...],
    *,
    process_only: bool,
    mutation: Mutation | None = None,
    mutation_index: int | None = None,
) -> dict[str, JSONValue]:
    mutation_id = mutation.stable_id() if mutation is not None else mutations[0].stable_id() if mutations else ""
    return SettlementRecord(
        record_type="wave_transition",
        source="wave_system",
        process_only=process_only,
        mutation_id=mutation_id,
        payload={
            "plan": plan.to_json(),
            "mutation_ids": [mutation.stable_id() for mutation in mutations],
            "mutation_count": len(mutations),
            "mutation_index": mutation_index if mutation_index is not None else -1,
        },
        trace=plan.source_trace,
    ).to_json()


def _plan_records(
    plan: WaveTransitionPlan,
    mutations: tuple[Mutation, ...],
    *,
    process_only: bool,
) -> tuple[dict[str, JSONValue], ...]:
    if not mutations:
        return (_plan_record(plan, mutations, process_only=process_only),)
    return tuple(
        _plan_record(plan, mutations, process_only=process_only, mutation=mutation, mutation_index=index)
        for index, mutation in enumerate(mutations)
    )
