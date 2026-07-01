from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..core.model import BattleState, GameEvent, JSONValue, Mutation, UnitState
from ..core.settlement import SettlementRecord
from ..rules.ir import WaveDefinitionIR, WaveMonsterEntryIR
from ..rules.rulebook import RuleBook
from .timeline import TimelineSystem
from .unit_lifecycle import UnitLifecycleSystem


WAVE_RUNTIME_SCHEMA_VERSION = "p1_2_wave_runtime_v1"

WaveTransitionStatus = Literal[
    "no_change",
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
        self.timeline = TimelineSystem()

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
        if runtime and _active_ally_count(state, self.lifecycle) == 0:
            return WaveTransitionPlan(
                ok=True,
                status="battle_defeat",
                wave_definition_id=str(runtime.get("wave_definition_id") or "") if runtime else "",
                current_wave_index=_runtime_int(runtime, "current_wave_index", state.wave_index) if runtime else state.wave_index,
                source_trace=_runtime_source_trace(runtime),
            )
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
        current_ids = tuple(_string_items(runtime.get("current_wave_unit_ids")))
        if not current_ids:
            return self._blocked(
                wave_definition_id,
                current_wave_index,
                "current_wave_unit_ids_missing",
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
        for entry in spawn_entries:
            reason = _spawn_entry_blocked_reason(self.rules, entry)
            if reason:
                return self._blocked(
                    wave_definition_id,
                    current_wave_index,
                    reason,
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
        return WaveTransitionPlan(
            ok=True,
            status="advance_to_next_wave",
            wave_definition_id=wave_definition_id,
            current_wave_index=current_wave_index,
            next_wave_index=next_wave_index,
            cleared_unit_ids=cleared_ids,
            spawn_entries=spawn_entries,
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
                ),
                (_plan_record(plan, mutations, process_only=False),),
            )
        if definition is None:
            blocked = self._blocked(
                plan.wave_definition_id,
                plan.current_wave_index,
                "wave_definition_missing",
                source_trace=source_trace,
            )
            return WaveTransitionResult(blocked, (), (), (_plan_record(blocked, (), process_only=True),))
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
                    _wave_cleared_event(state, plan, source_trace),
                    GameEvent(
                        "battle.victory",
                        source_id="wave_system",
                        event_id=f"event:{state.event_index}:battle:victory",
                        window="wave_transition",
                        process_only=True,
                        payload={"wave_transition_plan": plan.to_json(), "source_trace": source_trace},
                    ),
                ),
                (_plan_record(plan, mutations, process_only=False),),
            )
        if plan.status == "advance_to_next_wave":
            next_index = int(plan.next_wave_index) if plan.next_wave_index is not None else plan.current_wave_index + 1
            remove_mutations = _remove_mutations(self.lifecycle, state, plan, source_trace)
            runtime_cleared = _runtime_after_current_cleared(runtime, plan)
            spawn_units = tuple(_unit_from_wave_entry(self.rules, definition, entry) for entry in plan.spawn_entries)
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
                _runtime_mutation(state, runtime_cleared, runtime_after, plan, source_trace),
            )
            events = (
                _wave_cleared_event(state, plan, source_trace),
                GameEvent(
                    "wave.started",
                    source_id="wave_system",
                    event_id=f"event:{state.event_index}:wave:{next_index}:started",
                    window="wave_transition",
                    process_only=True,
                    payload={
                        "wave_definition_id": definition.wave_definition_id,
                        "wave_index": next_index,
                        "unit_ids": [unit.unit_id for unit in spawn_units],
                        "source_trace": source_trace,
                    },
                ),
                *(
                    _wave_monster_event(state, definition, entry, unit)
                    for entry, unit in zip(plan.spawn_entries, spawn_units, strict=True)
                ),
            )
            return WaveTransitionResult(plan, mutations, events, (_plan_record(plan, mutations, process_only=False),))
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


def _spawn_entry_blocked_reason(rules: RuleBook, entry: WaveMonsterEntryIR) -> str:
    if entry.coverage_status != "executable":
        return entry.blocked_reason or f"wave_entry_not_executable:{entry.coverage_status}"
    profile = rules.combatant_profile(entry.monster_entity_ref)
    if profile is None or profile.coverage_status != "executable":
        return "combatant_profile_missing_or_blocked"
    card = rules.monster_data_card_for_entity(entry.monster_entity_ref)
    if card is None:
        return "monster_data_card_missing"
    for key in ("max_hp", "attack", "defense", "speed"):
        value = profile.base_stats.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"combatant_profile_base_stat_missing:{key}"
    for key in ("current_toughness", "max_toughness"):
        value = profile.toughness_profile.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"combatant_profile_toughness_missing:{key}"
    try:
        rules.default_timeline_rule()
    except KeyError:
        return "timeline_rule_missing"
    return ""


def _unit_from_wave_entry(rules: RuleBook, definition: WaveDefinitionIR, entry: WaveMonsterEntryIR) -> UnitState:
    profile = rules.require_combatant_profile(entry.monster_entity_ref)
    card = rules.monster_data_card_for_entity(entry.monster_entity_ref)
    if card is None:
        raise ValueError(f"wave entry {entry.entry_id}: monster data card missing")
    speed = _number(profile.base_stats, "speed")
    timeline_rule = rules.default_timeline_rule()
    action_value = TimelineSystem().full_action_value(speed, timeline_rule)
    resources = {
        f"{damage_type}_resistance": float(value)
        for damage_type, value in profile.resistances.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    flags: dict[str, JSONValue] = {
        "position": entry.position,
        "wave_definition_id": definition.wave_definition_id,
        "stage_id": definition.stage_id,
        "wave_index": entry.wave_index,
        "wave_position": entry.position,
        "wave_entry_id": entry.entry_id,
        "wave_member_kind": "stage_wave_enemy",
        "wave_clear_policy": "counts",
        "wave_entry_source_trace": entry.source.to_json(),
        "wave_definition_source_trace": definition.source.to_json(),
        "combatant_profile_id": profile.profile_id,
        "combatant_profile_source_trace": profile.source.to_json(),
        "combatant_profile_coverage_status": profile.coverage_status,
        "monster_data_card_id": card.card_id,
        "monster_passive_mechanism_slot_ids": list(card.passive_mechanism_slot_ids),
        "weaknesses": list(profile.weaknesses),
        "initial_action_value_source_trace": {
            "timeline_rule_id": timeline_rule.timeline_rule_id,
            "timeline_rule_source": timeline_rule.source.to_json(),
            "speed_source": profile.source.to_json(),
            "speed": speed,
            "formula": timeline_rule.initial_action_value_rule,
        },
    }
    return UnitState(
        unit_id=_wave_unit_id(definition, entry),
        side="enemy",
        template_id=entry.monster_entity_ref,
        level=80,
        max_hp=_number(profile.base_stats, "max_hp"),
        hp=_number(profile.base_stats, "max_hp"),
        attack=_number(profile.base_stats, "attack"),
        defense=_number(profile.base_stats, "defense"),
        speed=speed,
        toughness=_number(profile.toughness_profile, "current_toughness"),
        max_toughness=_number(profile.toughness_profile, "max_toughness"),
        action_value=action_value,
        flags=flags,
        resources=resources,
    )


def _number(mapping: dict[str, JSONValue], key: str) -> float:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"missing numeric {key!r}")
    return float(value)


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
) -> Mutation:
    return Mutation(
        op="set",
        path=("global_flags", "wave_runtime"),
        before=before,
        after=after,
        reason="update wave runtime state",
        source="wave_system",
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
            metadata={"source_trace": source_trace, "outcome": outcome},
            mutation_id=f"mutation:battle_window:{state.event_index}:{outcome}",
        ),
    )


def _wave_cleared_event(
    state: BattleState,
    plan: WaveTransitionPlan,
    source_trace: dict[str, JSONValue],
) -> GameEvent:
    return GameEvent(
        "wave.cleared",
        source_id="wave_system",
        event_id=f"event:{state.event_index}:wave:{plan.current_wave_index}:cleared",
        window="wave_transition",
        process_only=True,
        payload={
            "wave_definition_id": plan.wave_definition_id,
            "wave_index": plan.current_wave_index,
            "cleared_unit_ids": list(plan.cleared_unit_ids),
            "removed_unit_ids": list(plan.remove_unit_ids),
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
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="wave_transition",
        source="wave_system",
        process_only=process_only,
        mutation_id=mutations[0].stable_id() if mutations else "",
        payload={
            "plan": plan.to_json(),
            "mutation_ids": [mutation.stable_id() for mutation in mutations],
            "mutation_count": len(mutations),
        },
        trace=plan.source_trace,
    ).to_json()
