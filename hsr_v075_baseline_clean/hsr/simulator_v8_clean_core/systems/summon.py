from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal

from ..core.model import BattleState, GameEvent, JSONValue, Mutation, UnitState
from ..core.settlement import SettlementRecord
from ..rules.ir import ServantDefinitionIR, SummonMonsterEntryIR, SummonMonsterIntentIR
from ..rules.rulebook import RuleBook
from ..rules.value_binding import ValueBindingRequest, ValueContext, ValueResolver
from .timeline import TimelineSystem
from .unit_lifecycle import UnitLifecycleSystem


SUMMON_RUNTIME_SCHEMA_VERSION = "p3_summon_runtime_v2"
SUPPORTED_SUMMON_RUNTIME_SCHEMA_VERSIONS = {SUMMON_RUNTIME_SCHEMA_VERSION, "p1_3_summon_runtime_v1"}


@dataclass(frozen=True)
class SummonRuntimeView:
    schema_version: str
    schema_boundary: dict[str, JSONValue] = field(default_factory=dict)
    entities: dict[str, JSONValue] = field(default_factory=dict)
    by_owner: dict[str, JSONValue] = field(default_factory=dict)
    by_unique_group: dict[str, JSONValue] = field(default_factory=dict)
    last_summon_monsters: tuple[str, ...] = ()
    last_servants: tuple[str, ...] = ()
    servants: dict[str, JSONValue] = field(default_factory=dict)
    assistant_history: tuple[JSONValue, ...] = ()
    blocked: tuple[JSONValue, ...] = ()
    runtime: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "schema_version": self.schema_version,
            "schema_boundary": self.schema_boundary,
            "entities": self.entities,
            "by_owner": self.by_owner,
            "by_unique_group": self.by_unique_group,
            "last_summon_monsters": list(self.last_summon_monsters),
            "last_servants": list(self.last_servants),
            "servants": self.servants,
            "assistant_history": list(self.assistant_history),
            "blocked": list(self.blocked),
            "runtime": self.runtime,
        }


@dataclass(frozen=True)
class SummonTransitionPlan:
    ok: bool
    operation: Literal[
        "spawn_summon",
        "spawn_summoned_monster",
        "remove_summon",
        "expire_summon",
        "owner_removed_cleanup",
        "assistant_enqueue",
        "assistant_execute",
        "servant_spawn",
        "servant_component_update",
        "blocked",
    ]
    actor_id: str = ""
    owner_id: str = ""
    unit_ids: tuple[str, ...] = ()
    intent_id: str = ""
    entry_ids: tuple[str, ...] = ()
    blocked_reason: str = ""
    source_trace: dict[str, JSONValue] = field(default_factory=dict)
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "operation": self.operation,
            "actor_id": self.actor_id,
            "owner_id": self.owner_id,
            "unit_ids": list(self.unit_ids),
            "intent_id": self.intent_id,
            "entry_ids": list(self.entry_ids),
            "blocked_reason": self.blocked_reason,
            "source_trace": self.source_trace,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class SummonTransitionResult:
    plan: SummonTransitionPlan
    mutations: tuple[Mutation, ...]
    events: tuple[GameEvent, ...]
    records: tuple[dict[str, JSONValue], ...]


@dataclass(frozen=True)
class _SummonMonsterSpawnInstance:
    entry: SummonMonsterEntryIR
    entry_index: int
    copy_index: int
    spawn_index: int


class SummonSystem:
    def __init__(self, rules: RuleBook) -> None:
        self.rules = rules
        self.lifecycle = UnitLifecycleSystem()
        self.timeline = TimelineSystem()
        self.value_resolver = ValueResolver(rules)

    def view(self, state: BattleState) -> SummonRuntimeView:
        runtime = _summon_runtime(state)
        return SummonRuntimeView(
            schema_version=SUMMON_RUNTIME_SCHEMA_VERSION,
            schema_boundary=dict(runtime.get("schema_boundary") or {}),
            entities=dict(runtime.get("entities") or {}),
            by_owner=dict(runtime.get("by_owner") or {}),
            by_unique_group=dict(runtime.get("by_unique_group") or {}),
            last_summon_monsters=tuple(str(item) for item in runtime.get("last_summon_monsters") or () if isinstance(item, str)),
            last_servants=tuple(str(item) for item in runtime.get("last_servants") or () if isinstance(item, str)),
            servants=dict(runtime.get("servants") or {}),
            assistant_history=tuple(runtime.get("assistant_history") or ()),
            blocked=tuple(runtime.get("blocked") or ()),
            runtime=runtime,
        )

    def plan_spawn_from_intent(
        self,
        state: BattleState,
        intent: SummonMonsterIntentIR,
        *,
        owner_id: str,
    ) -> SummonTransitionPlan:
        return self.plan_spawn_summoned_monster(state, intent, owner_id=owner_id)

    def plan_spawn_summoned_monster(
        self,
        state: BattleState,
        intent: SummonMonsterIntentIR,
        *,
        owner_id: str,
    ) -> SummonTransitionPlan:
        if intent.coverage_status != "executable":
            return self._blocked(
                "spawn_summoned_monster",
                intent.blocked_reason or f"summon_monster_intent_not_executable:{intent.coverage_status}",
                owner_id=owner_id,
                intent_id=intent.summon_intent_id,
                source_trace=intent.source.to_json(),
            )
        owner = state.units.get(owner_id)
        if owner is None:
            return self._blocked(
                "spawn_summoned_monster",
                "summon_owner_missing",
                owner_id=owner_id,
                intent_id=intent.summon_intent_id,
                source_trace=intent.source.to_json(),
            )
        if not intent.entries:
            return self._blocked(
                "spawn_summoned_monster",
                "summon_monster_entries_missing",
                owner_id=owner_id,
                intent_id=intent.summon_intent_id,
                source_trace=intent.source.to_json(),
            )
        unit_ids: list[str] = []
        blocked: list[str] = []
        seen_unit_ids: set[str] = set()
        spawn_index = 0
        for entry_index, entry in enumerate(intent.entries):
            if entry.coverage_status != "executable":
                blocked.append(entry.blocked_reason or f"summon_monster_entry_not_executable:{entry.coverage_status}")
                continue
            profile = self.rules.combatant_profile(entry.monster_entity_ref)
            stat_resolutions = _summon_profile_stat_resolutions(self.value_resolver, entry, profile)
            if any(resolution.get("ok") is not True for resolution in stat_resolutions.values()):
                blocked.append("summon_monster_profile_stat_value_resolution_blocked")
                continue
            card = self.rules.monster_data_card_for_entity(entry.monster_entity_ref)
            if not _summon_monster_card_source_available(card):
                blocked.append("summon_monster_data_card_source_blocked")
                continue
            if not _summon_level_policy_executable(entry, profile):
                blocked.append("summon_monster_level_policy_source_blocked")
                continue
            if not isinstance(entry.count, int) or entry.count <= 0:
                blocked.append("summon_monster_entry_count_not_positive")
                continue
            for copy_index in range(entry.count):
                position = _position_for_entry(owner, entry, spawn_index)
                if position is None:
                    blocked.append("summon_monster_position_not_resolved")
                    continue
                unit_id = _summoned_monster_unit_id(state, intent, entry, owner_id, entry_index, copy_index)
                if unit_id in state.units or unit_id in seen_unit_ids:
                    blocked.append("summon_monster_unit_id_already_exists")
                    continue
                unit_ids.append(unit_id)
                seen_unit_ids.add(unit_id)
                spawn_index += 1
        if blocked:
            return self._blocked(
                "spawn_summoned_monster",
                ";".join(dict.fromkeys(blocked)),
                owner_id=owner_id,
                intent_id=intent.summon_intent_id,
                source_trace=intent.source.to_json(),
            )
        return SummonTransitionPlan(
            ok=True,
            operation="spawn_summoned_monster",
            actor_id=owner_id,
            owner_id=owner_id,
            unit_ids=tuple(unit_ids),
            intent_id=intent.summon_intent_id,
            entry_ids=tuple(entry.entry_id for entry in intent.entries),
            source_trace=intent.source.to_json(),
            metadata={
                "intent": intent.to_json(),
                "spawn_instance_count": len(unit_ids),
                "entry_counts": {entry.entry_id: entry.count for entry in intent.entries},
                "entry_value_resolutions": {
                    entry.entry_id: _summon_profile_stat_resolutions(
                        self.value_resolver,
                        entry,
                        self.rules.combatant_profile(entry.monster_entity_ref),
                    )
                    for entry in intent.entries
                },
            },
        )

    def plan_spawn_servant(
        self,
        state: BattleState,
        definition: ServantDefinitionIR,
        *,
        owner_id: str,
    ) -> SummonTransitionPlan:
        if definition.coverage_status != "executable" or definition.representation != "unit":
            return self._blocked(
                "servant_spawn",
                definition.blocked_reason or f"servant_definition_not_executable:{definition.coverage_status}",
                owner_id=owner_id,
                intent_id=definition.servant_definition_id,
                source_trace=definition.source.to_json(),
            )
        owner = state.units.get(owner_id)
        if owner is None:
            return self._blocked(
                "servant_spawn",
                "servant_owner_missing",
                owner_id=owner_id,
                intent_id=definition.servant_definition_id,
                source_trace=definition.source.to_json(),
            )
        if definition.owner_entity_ref and owner.template_id != definition.owner_entity_ref:
            return self._blocked(
                "servant_spawn",
                "servant_owner_entity_mismatch",
                owner_id=owner_id,
                intent_id=definition.servant_definition_id,
                source_trace=definition.source.to_json(),
            )
        blocking = _servant_spawn_blocked_reason(owner, definition)
        if blocking:
            return self._blocked(
                "servant_spawn",
                blocking,
                owner_id=owner_id,
                intent_id=definition.servant_definition_id,
                source_trace=definition.source.to_json(),
            )
        if _active_servant_duplicate(state, owner_id, definition):
            return self._blocked(
                "servant_spawn",
                "servant_duplicate_active_policy_missing",
                owner_id=owner_id,
                intent_id=definition.servant_definition_id,
                source_trace=definition.source.to_json(),
            )
        unit_id = _servant_unit_id(state, definition, owner_id)
        if unit_id in state.units:
            return self._blocked(
                "servant_spawn",
                "servant_unit_id_already_exists",
                owner_id=owner_id,
                intent_id=definition.servant_definition_id,
                source_trace=definition.source.to_json(),
            )
        return SummonTransitionPlan(
            ok=True,
            operation="servant_spawn",
            actor_id=owner_id,
            owner_id=owner_id,
            unit_ids=(unit_id,),
            intent_id=definition.servant_definition_id,
            source_trace=definition.source.to_json(),
            metadata={"servant_definition": definition.to_json()},
        )

    def apply_spawn(
        self,
        state: BattleState,
        plan: SummonTransitionPlan,
    ) -> SummonTransitionResult:
        if not plan.ok:
            return SummonTransitionResult(plan, (), (), (_plan_record(plan, (), process_only=True),))
        intent = self.rules.summon_monster_intent(plan.intent_id)
        if intent is None:
            blocked = self._blocked(
                plan.operation,
                "summon_monster_intent_missing",
                owner_id=plan.owner_id,
                intent_id=plan.intent_id,
                source_trace=plan.source_trace,
            )
            return SummonTransitionResult(blocked, (), (), (_plan_record(blocked, (), process_only=True),))
        instances = _summon_monster_spawn_instances(intent)
        if len(plan.unit_ids) != len(instances):
            blocked = self._blocked(
                plan.operation,
                "summon_plan_entry_instance_unit_mismatch",
                owner_id=plan.owner_id,
                intent_id=plan.intent_id,
                source_trace=plan.source_trace,
            )
            return SummonTransitionResult(blocked, (), (), (_plan_record(blocked, (), process_only=True),))
        owner = state.units.get(plan.owner_id)
        if owner is None:
            blocked = self._blocked(
                plan.operation,
                "summon_owner_missing",
                owner_id=plan.owner_id,
                intent_id=plan.intent_id,
                source_trace=plan.source_trace,
            )
            return SummonTransitionResult(blocked, (), (), (_plan_record(blocked, (), process_only=True),))
        units = tuple(
            self._unit_from_entry(
                state,
                owner,
                intent,
                instance.entry,
                unit_id,
                entry_index=instance.entry_index,
                copy_index=instance.copy_index,
                spawn_index=instance.spawn_index,
            )
            for instance, unit_id in zip(instances, plan.unit_ids, strict=True)
        )
        spawn_mutations = tuple(
            self.lifecycle.spawn_mutation(
                state,
                unit,
                reason="spawn summoned monster",
                source="summon_system",
                source_trace=plan.source_trace,
                metadata={
                    "summon_operation": "spawn_summoned_monster",
                    "summon_intent_id": intent.summon_intent_id,
                    "summon_entry_id": str(unit.flags.get("summon_entry_id") or ""),
                    "summon_entry_index": unit.flags.get("summon_entry_index"),
                    "summon_entry_copy_index": unit.flags.get("summon_entry_copy_index"),
                    "summon_spawn_index": unit.flags.get("summon_spawn_index"),
                    "owner_id": plan.owner_id,
                    "source_trace": plan.source_trace,
                    "summon_entry_source_trace": unit.flags.get("summon_entry_source_trace")
                    if isinstance(unit.flags.get("summon_entry_source_trace"), dict)
                    else {},
                    "summon_position_policy": unit.flags.get("summon_position_policy")
                    if isinstance(unit.flags.get("summon_position_policy"), dict)
                    else {},
                    "summon_delay_policy": intent.delay_policy,
                    "combatant_profile_id": unit.flags.get("combatant_profile_id"),
                    "summon_value_resolutions": unit.flags.get("summon_value_resolutions")
                    if isinstance(unit.flags.get("summon_value_resolutions"), dict)
                    else {},
                    "combatant_profile_source_trace": unit.flags.get("combatant_profile_source_trace")
                    if isinstance(unit.flags.get("combatant_profile_source_trace"), dict)
                    else {},
                    "monster_data_card_id": unit.flags.get("monster_data_card_id"),
                    "monster_data_card_source_trace": unit.flags.get("monster_data_card_source_trace")
                    if isinstance(unit.flags.get("monster_data_card_source_trace"), dict)
                    else {},
                },
            )
            for unit in units
        )
        runtime_before = _summon_runtime(state)
        runtime_after = _runtime_after_spawn(runtime_before, state, plan, units)
        runtime_mutation = _runtime_mutation(state, runtime_before, runtime_after, plan, "record summoned monster spawn")
        mutations = (*spawn_mutations, runtime_mutation)
        events = tuple(_spawn_event(state, plan, unit) for unit in units)
        return SummonTransitionResult(plan, mutations, events, _plan_records(plan, mutations, process_only=False))

    def apply_spawn_servant(
        self,
        state: BattleState,
        plan: SummonTransitionPlan,
    ) -> SummonTransitionResult:
        if not plan.ok:
            return SummonTransitionResult(plan, (), (), (_plan_record(plan, (), process_only=True),))
        definition = self.rules.servant_definition(plan.intent_id)
        if definition is None:
            blocked = self._blocked(
                plan.operation,
                "servant_definition_missing",
                owner_id=plan.owner_id,
                intent_id=plan.intent_id,
                source_trace=plan.source_trace,
            )
            return SummonTransitionResult(blocked, (), (), (_plan_record(blocked, (), process_only=True),))
        owner = state.units.get(plan.owner_id)
        if owner is None:
            blocked = self._blocked(
                plan.operation,
                "servant_owner_missing",
                owner_id=plan.owner_id,
                intent_id=plan.intent_id,
                source_trace=plan.source_trace,
            )
            return SummonTransitionResult(blocked, (), (), (_plan_record(blocked, (), process_only=True),))
        if len(plan.unit_ids) != 1:
            blocked = self._blocked(
                plan.operation,
                "servant_plan_unit_count_invalid",
                owner_id=plan.owner_id,
                intent_id=plan.intent_id,
                source_trace=plan.source_trace,
            )
            return SummonTransitionResult(blocked, (), (), (_plan_record(blocked, (), process_only=True),))
        unit = self._unit_from_servant_definition(state, owner, definition, plan.unit_ids[0])
        servant_stat_values = (
            unit.flags.get("servant_runtime_stat_values")
            if isinstance(unit.flags.get("servant_runtime_stat_values"), dict)
            else {}
        )
        spawn_mutation = self.lifecycle.spawn_mutation(
            state,
            unit,
            reason="spawn servant",
            source="summon_system",
            source_trace=plan.source_trace,
            metadata={
                "summon_operation": "servant_spawn",
                "servant_definition_id": definition.servant_definition_id,
                "servant_ref": definition.servant_ref,
                "owner_id": plan.owner_id,
                "source_trace": plan.source_trace,
                "owner_entity_ref": definition.owner_entity_ref,
                "servant_stat_source": definition.stat_source,
                "servant_timeline_source": definition.timeline_source,
                "servant_lifecycle_source": definition.lifecycle_source,
                "servant_action_set": definition.action_set,
                "servant_ability_graph_ids": list(definition.ability_graph_ids),
                "servant_skipped_slots": definition.action_set.get("skipped_slots", [])
                if isinstance(definition.action_set, dict)
                else [],
                "servant_runtime_stat_values": servant_stat_values,
                "owner_death_policy_admission": unit.flags.get("owner_death_policy_admission")
                if isinstance(unit.flags.get("owner_death_policy_admission"), dict)
                else {},
                "owner_death_policy_source_trace": unit.flags.get("owner_death_policy_source_trace")
                if isinstance(unit.flags.get("owner_death_policy_source_trace"), dict)
                else {},
            },
        )
        runtime_before = _summon_runtime(state)
        runtime_after = _runtime_after_spawn(runtime_before, state, plan, (unit,))
        runtime_mutation = _runtime_mutation(state, runtime_before, runtime_after, plan, "record servant spawn")
        mutations = (spawn_mutation, runtime_mutation)
        events = (_spawn_event(state, plan, unit),)
        return SummonTransitionResult(plan, mutations, events, _plan_records(plan, mutations, process_only=False))

    def plan_remove(
        self,
        state: BattleState,
        unit_id: str,
        reason: str,
        *,
        source_trace: dict[str, JSONValue] | None = None,
        admission: dict[str, JSONValue] | None = None,
    ) -> SummonTransitionPlan:
        unit = state.units.get(unit_id)
        if unit is None:
            return self._blocked("remove_summon", "summon_unit_missing", intent_id="", owner_id="", source_trace={})
        if not unit.flags.get("summon_kind"):
            return self._blocked(
                "remove_summon",
                "unit_is_not_summon_runtime_entity",
                owner_id=str(unit.flags.get("owner_id") or ""),
                source_trace=_source_trace_from_unit(unit),
            )
        if not _remove_source_admitted(source_trace, admission):
            return self._blocked(
                "remove_summon",
                "summon_remove_source_not_admitted",
                owner_id=str(unit.flags.get("owner_id") or ""),
                source_trace=_source_trace_from_unit(unit),
            )
        intent_id = _intent_id_from_unit(unit)
        return SummonTransitionPlan(
            ok=True,
            operation="remove_summon",
            actor_id=str(unit.flags.get("summoner_id") or unit.flags.get("owner_id") or ""),
            owner_id=str(unit.flags.get("owner_id") or ""),
            unit_ids=(unit_id,),
            intent_id=intent_id,
            blocked_reason="",
            source_trace=dict(source_trace or {}),
            metadata={"remove_reason": reason, "remove_admission": dict(admission or {})},
        )

    def apply_remove(self, state: BattleState, plan: SummonTransitionPlan) -> SummonTransitionResult:
        if not plan.ok:
            return SummonTransitionResult(plan, (), (), (_plan_record(plan, (), process_only=True),))
        mutations: list[Mutation] = []
        for unit_id in plan.unit_ids:
            unit = state.units.get(unit_id)
            unit_intent_id = _intent_id_from_unit(unit) if unit is not None else plan.intent_id
            mutations.extend(_remove_cleanup_mutations(state, unit_id, plan, unit_intent_id=unit_intent_id))
            mutations.extend(
                self.lifecycle.remove_mutations(
                    state,
                    unit_id,
                    reason=str(plan.metadata.get("remove_reason") or "remove summon"),
                    source="summon_system",
                    removed_record={
                        "reason": str(plan.metadata.get("remove_reason") or ""),
                        "summon_operation": plan.operation,
                        "intent_id": unit_intent_id,
                        "unit_id": unit_id,
                        "remove_admission": plan.metadata.get("remove_admission")
                        if isinstance(plan.metadata.get("remove_admission"), dict)
                        else {},
                        "source_trace": plan.source_trace,
                    },
                    source_trace=plan.source_trace,
                )
            )
        runtime_before = _summon_runtime(state)
        runtime_after = _runtime_after_remove(runtime_before, state, plan)
        mutations.append(_runtime_mutation(state, runtime_before, runtime_after, plan, "record summon removal"))
        events = tuple(_remove_event(state, plan, unit_id) for unit_id in plan.unit_ids)
        mutation_tuple = tuple(mutations)
        return SummonTransitionResult(plan, mutation_tuple, events, _plan_records(plan, mutation_tuple, process_only=False))

    def plan_owner_cleanup(self, state: BattleState, owner_id: str) -> SummonTransitionPlan:
        runtime = _summon_runtime(state)
        by_owner = runtime.get("by_owner") if isinstance(runtime.get("by_owner"), dict) else {}
        owned = tuple(str(item) for item in by_owner.get(owner_id, ()) if isinstance(item, str))
        removable = tuple(
            unit_id
            for unit_id in owned
            if unit_id in state.units
            and state.units[unit_id].flags.get("owner_death_policy") == "remove"
            and _remove_source_admitted(
                state.units[unit_id].flags.get("owner_death_policy_source_trace")
                if isinstance(state.units[unit_id].flags.get("owner_death_policy_source_trace"), dict)
                else None,
                state.units[unit_id].flags.get("owner_death_policy_admission")
                if isinstance(state.units[unit_id].flags.get("owner_death_policy_admission"), dict)
                else None,
            )
        )
        if not removable:
            return self._blocked(
                "owner_removed_cleanup",
                "owner_death_remove_policy_missing",
                owner_id=owner_id,
                source_trace={},
            )
        intent_ids = tuple(
            dict.fromkeys(
                _intent_id_from_unit(state.units[unit_id])
                for unit_id in removable
                if unit_id in state.units and _intent_id_from_unit(state.units[unit_id])
            )
        )
        return SummonTransitionPlan(
            ok=True,
            operation="owner_removed_cleanup",
            owner_id=owner_id,
            unit_ids=removable,
            intent_id=intent_ids[0] if len(intent_ids) == 1 else "",
            source_trace={
                "owner_death_policy_sources": [
                    dict(state.units[unit_id].flags.get("owner_death_policy_source_trace", {}))
                    for unit_id in removable
                ]
            },
            metadata={
                "remove_reason": "owner_removed_cleanup",
                "intent_ids": list(intent_ids),
                "remove_admissions": [
                    dict(state.units[unit_id].flags.get("owner_death_policy_admission", {}))
                    for unit_id in removable
                    if isinstance(state.units[unit_id].flags.get("owner_death_policy_admission"), dict)
                ],
            },
        )

    def blocked(self, reason: str, *, owner_id: str = "", source_trace: dict[str, JSONValue] | None = None) -> SummonTransitionResult:
        plan = self._blocked("blocked", reason, owner_id=owner_id, source_trace=source_trace or {})
        return SummonTransitionResult(plan, (), (), (_plan_record(plan, (), process_only=True),))

    def _blocked(
        self,
        operation: str,
        reason: str,
        *,
        owner_id: str = "",
        intent_id: str = "",
        source_trace: dict[str, JSONValue] | None = None,
    ) -> SummonTransitionPlan:
        return SummonTransitionPlan(
            ok=False,
            operation="blocked",
            owner_id=owner_id,
            intent_id=intent_id,
            blocked_reason=reason,
            source_trace=source_trace or {},
            metadata={"requested_operation": operation},
        )

    def _unit_from_entry(
        self,
        state: BattleState,
        owner: UnitState,
        intent: SummonMonsterIntentIR,
        entry: SummonMonsterEntryIR,
        unit_id: str,
        *,
        entry_index: int,
        copy_index: int,
        spawn_index: int,
    ) -> UnitState:
        profile = self.rules.require_combatant_profile(entry.monster_entity_ref)
        card = self.rules.monster_data_card_for_entity(entry.monster_entity_ref)
        if card is None:
            raise ValueError(f"summon entry {entry.entry_id}: monster data card missing")
        stat_resolutions = _summon_profile_stat_resolutions(self.value_resolver, entry, profile)
        max_hp = _resolved_value(stat_resolutions, "max_hp")
        attack = _resolved_value(stat_resolutions, "attack")
        defense = _resolved_value(stat_resolutions, "defense")
        speed = _resolved_value(stat_resolutions, "speed")
        timeline_rule = self.rules.default_timeline_rule()
        base_action_value = self.timeline.full_action_value(speed, timeline_rule)
        delay_ratio = _summon_delay_ratio(intent.delay_policy)
        initial_action_value = max(0.0, base_action_value * delay_ratio)
        position = _position_for_entry(owner, entry, spawn_index)
        resources = {
            f"{damage_type}_resistance": float(value)
            for damage_type, value in profile.resistances.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        if isinstance(profile.status_resistance, (int, float)) and not isinstance(profile.status_resistance, bool):
            resources["effect_resistance"] = float(profile.status_resistance)
        flags: dict[str, JSONValue] = {
            "position": position,
            "team_side": "enemy",
            "summon_kind": "summoned_monster",
            "wave_member_kind": "enemy_summon",
            "wave_clear_policy": entry.wave_clear_policy,
            "owner_id": owner.unit_id,
            "summoner_id": owner.unit_id,
            "summon_intent_id": intent.summon_intent_id,
            "summon_entry_id": entry.entry_id,
            "summon_entry_index": entry_index,
            "summon_entry_copy_index": copy_index,
            "summon_spawn_index": spawn_index,
            "summon_entry_count": entry.count,
            "summon_source_trace": intent.source.to_json(),
            "summon_entry_source_trace": entry.source.to_json(),
            "summon_position_policy": entry.position_policy,
            "summon_level_policy": entry.level_policy,
            "summon_value_resolutions": stat_resolutions,
            "summon_level_source_trace": profile.source.to_json(),
            "summon_delay_policy": intent.delay_policy,
            "combatant_profile_id": profile.profile_id,
            "combatant_profile_source_trace": profile.source.to_json(),
            "combatant_profile_coverage_status": profile.coverage_status,
            "monster_data_card_id": card.card_id,
            "monster_data_card_source_trace": card.source.to_json(),
            "monster_passive_mechanism_slot_ids": list(card.passive_mechanism_slot_ids),
            "weaknesses": list(profile.weaknesses),
            "debuff_resistances": list(profile.debuff_resistances),
            "toughness_profile_source_trace": profile.source.to_json(),
            "resistance_source_trace": profile.source.to_json(),
            "status_resistance_source_trace": profile.source.to_json(),
            "timeline_admitted": True,
            "summon_action_admitted": True,
            "summon_action_admission": {
                "coverage_status": "executable",
                "source_trace": {
                    "summon_intent": intent.source.to_json(),
                    "summon_entry": entry.source.to_json(),
                    "monster_data_card": card.source.to_json(),
                    "combatant_profile": profile.source.to_json(),
                },
                "action_set_kind": "enemy_fixed_sequence",
                "monster_data_card_id": card.card_id,
                "action_sequence_count": len(card.action_sequence),
                "executable_action_sequence_count": sum(
                    1 for step in card.action_sequence if isinstance(step, dict) and step.get("coverage_status") == "executable"
                ),
            },
            "initial_action_value_source_trace": {
                "timeline_rule_id": timeline_rule.timeline_rule_id,
                "timeline_rule_source": timeline_rule.source.to_json(),
                "speed_source": profile.source.to_json(),
                "speed": speed,
                "formula": timeline_rule.initial_action_value_rule,
                "summon_delay_policy": intent.delay_policy,
                "summon_delay_application": "initial_action_value_full_av_times_delay_ratio",
                "base_action_value": base_action_value,
                "delay_ratio": delay_ratio,
                "initial_action_value": initial_action_value,
            },
        }
        return UnitState(
            unit_id=unit_id,
            side="enemy",
            template_id=entry.monster_entity_ref,
            level=owner.level,
            max_hp=max_hp,
            hp=max_hp,
            attack=attack,
            defense=defense,
            speed=speed,
            toughness=_number(profile.toughness_profile, "current_toughness"),
            max_toughness=_number(profile.toughness_profile, "max_toughness"),
            action_value=initial_action_value,
            flags=flags,
            resources=resources,
        )

    def _unit_from_servant_definition(
        self,
        state: BattleState,
        owner: UnitState,
        definition: ServantDefinitionIR,
        unit_id: str,
    ) -> UnitState:
        stats = _servant_runtime_stats(owner, definition)
        timeline_rule = self.rules.default_timeline_rule()
        team_side = _team_side_from_owner(owner)
        action_admission_source = _servant_action_admission_source_trace(definition)
        lifecycle_source_trace = _first_source_trace(definition.lifecycle_source, definition.source.to_json())
        timeline_source_trace = _first_source_trace(definition.timeline_source, definition.source.to_json())
        position = _position(owner.flags.get("position"))
        flags: dict[str, JSONValue] = {
            "position": position,
            "team_side": team_side,
            "summon_kind": "servant",
            "owner_id": owner.unit_id,
            "summoner_id": owner.unit_id,
            "owner_entity_ref": definition.owner_entity_ref,
            "servant_definition_id": definition.servant_definition_id,
            "servant_ref": definition.servant_ref,
            "summon_intent_id": definition.servant_definition_id,
            "summon_source_trace": definition.source.to_json(),
            "servant_definition_source_trace": definition.source.to_json(),
            "stat_source": definition.stat_source,
            "servant_owner_source": definition.stat_source.get("owner_source", {})
            if isinstance(definition.stat_source, dict)
            else {},
            "timeline_source": definition.timeline_source,
            "lifecycle_source": definition.lifecycle_source,
            "servant_runtime_stat_values": {
                "max_hp": stats["max_hp"],
                "speed": stats["speed"],
                "attack": float(owner.attack),
                "defense": float(owner.defense),
                "hp_formula": "owner.max_hp * hp_inherit + hp_base",
                "speed_formula": "owner.speed * speed_inherit + speed_base",
                "attack_source_status": "schema_carry_only",
                "defense_source_status": "schema_carry_only",
            },
            "timeline_admitted": True,
            "summon_action_admitted": True,
            "summon_action_admission": {
                "coverage_status": "executable",
                "source_trace": action_admission_source,
                "action_set": definition.action_set,
                "ability_graph_ids": list(definition.ability_graph_ids),
                "skipped_slots": definition.action_set.get("skipped_slots", [])
                if isinstance(definition.action_set, dict)
                else [],
            },
            "owner_death_policy": "remove",
            "owner_death_policy_admission": {
                "coverage_status": "executable",
                "remove_source_admitted": True,
                "lifecycle_source": definition.lifecycle_source,
            },
            "owner_death_policy_source_trace": lifecycle_source_trace,
            "initial_action_value_source_trace": {
                "timeline_rule_id": timeline_rule.timeline_rule_id,
                "timeline_rule_source": timeline_rule.source.to_json(),
                "timeline_source": timeline_source_trace,
                "speed": stats["speed"],
                "formula": timeline_rule.initial_action_value_rule,
            },
            "servant_attack_defense_source_status": {
                "coverage_status": "schema_carry_only",
                "source": "owner_current_unit_state",
                "note": "servant damage stat binding is not admitted by servant spawn",
            },
        }
        return UnitState(
            unit_id=unit_id,
            side="summon",
            template_id=definition.servant_ref,
            level=owner.level,
            max_hp=stats["max_hp"],
            hp=stats["max_hp"],
            attack=float(owner.attack),
            defense=float(owner.defense),
            speed=stats["speed"],
            toughness=0.0,
            max_toughness=0.0,
            action_value=self.timeline.full_action_value(stats["speed"], timeline_rule),
            flags=flags,
            resources={},
        )


def _servant_spawn_blocked_reason(owner: UnitState, definition: ServantDefinitionIR) -> str:
    reasons: list[str] = []
    for label, source in (
        ("action_set", definition.action_set),
        ("stat", definition.stat_source),
        ("timeline", definition.timeline_source),
        ("lifecycle", definition.lifecycle_source),
    ):
        if not isinstance(source, dict) or source.get("admission_status") != "executable":
            reasons.append(str(source.get("blocked_reason") if isinstance(source, dict) else "") or f"servant_{label}_source_blocked")
    stats = _servant_runtime_stats(owner, definition)
    if stats["max_hp"] <= 0:
        reasons.append("servant_runtime_max_hp_non_positive")
    if stats["speed"] <= 0:
        reasons.append("servant_runtime_speed_non_positive")
    return ";".join(dict.fromkeys(reason for reason in reasons if reason))


def _active_servant_duplicate(state: BattleState, owner_id: str, definition: ServantDefinitionIR) -> str:
    runtime = _summon_runtime(state)
    candidates: set[str] = set()
    by_owner = runtime.get("by_owner") if isinstance(runtime.get("by_owner"), dict) else {}
    owned = by_owner.get(owner_id) if isinstance(by_owner, dict) else None
    if isinstance(owned, list):
        candidates.update(str(item) for item in owned if isinstance(item, str))
    for unit_id, unit in state.units.items():
        if unit.flags.get("owner_id") == owner_id:
            candidates.add(unit_id)
    entities = runtime.get("entities") if isinstance(runtime.get("entities"), dict) else {}
    for unit_id in sorted(candidates):
        unit = state.units.get(unit_id)
        entry = entities.get(unit_id) if isinstance(entities, dict) else None
        runtime_active = isinstance(entry, dict) and entry.get("status", "active") == "active"
        unit_active = unit is not None and unit.flags.get("lifecycle_status", "active") == "active"
        if not runtime_active and not unit_active:
            continue
        entry_ref = str(entry.get("servant_ref") or entry.get("template_ref") or "") if isinstance(entry, dict) else ""
        unit_ref = str(unit.flags.get("servant_ref") or unit.template_id) if unit is not None else ""
        entry_intent = str(entry.get("source_intent_id") or "") if isinstance(entry, dict) else ""
        unit_intent = str(unit.flags.get("servant_definition_id") or unit.flags.get("summon_intent_id") or "") if unit is not None else ""
        if (
            entry_ref == definition.servant_ref
            or unit_ref == definition.servant_ref
            or entry_intent == definition.servant_definition_id
            or unit_intent == definition.servant_definition_id
        ):
            return unit_id
    return ""


def _servant_runtime_stats(owner: UnitState, definition: ServantDefinitionIR) -> dict[str, float]:
    components = definition.stat_source.get("components") if isinstance(definition.stat_source, dict) else {}
    if not isinstance(components, dict):
        return {"max_hp": 0.0, "speed": 0.0}
    hp_base = _stat_component_value(components, "hp_base")
    hp_inherit = _stat_component_value(components, "hp_inherit")
    speed_base = _stat_component_value(components, "speed_base")
    speed_inherit = _stat_component_value(components, "speed_inherit")
    return {
        "max_hp": max(0.0, float(owner.max_hp) * hp_inherit + hp_base),
        "speed": max(0.0, float(owner.speed) * speed_inherit + speed_base),
    }


def _stat_component_value(components: dict[str, JSONValue], key: str) -> float:
    component = components.get(key)
    if not isinstance(component, dict):
        return 0.0
    value = component.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _servant_unit_id(state: BattleState, definition: ServantDefinitionIR, owner_id: str) -> str:
    seed = "|".join((definition.servant_definition_id, definition.servant_ref, owner_id, str(state.event_index)))
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"summon:servant:{digest}"


def _team_side_from_owner(owner: UnitState) -> str:
    team_side = owner.flags.get("team_side")
    if team_side in {"ally", "enemy"}:
        return str(team_side)
    if owner.side in {"ally", "enemy"}:
        return owner.side
    return "neutral"


def _servant_action_admission_source_trace(definition: ServantDefinitionIR) -> dict[str, JSONValue]:
    action_set_trace = definition.action_set.get("source_trace") if isinstance(definition.action_set, dict) else None
    return {
        "servant_definition": definition.source.to_json(),
        "action_set_source_trace": list(action_set_trace) if isinstance(action_set_trace, list) else [],
    }


def _first_source_trace(source: dict[str, JSONValue], fallback: dict[str, JSONValue]) -> dict[str, JSONValue]:
    traces = source.get("source_trace") if isinstance(source, dict) else None
    if isinstance(traces, list) and traces:
        first = traces[0]
        if isinstance(first, dict):
            return first
    if isinstance(traces, dict):
        return dict(traces)
    return dict(fallback)


def _summon_runtime(state: BattleState) -> dict[str, JSONValue]:
    runtime = state.global_flags.get("summon_runtime")
    if isinstance(runtime, dict) and runtime.get("schema_version") in SUPPORTED_SUMMON_RUNTIME_SCHEMA_VERSIONS:
        return _normalize_runtime(runtime)
    return _empty_runtime()


def _empty_runtime() -> dict[str, JSONValue]:
    return {
        "schema_version": SUMMON_RUNTIME_SCHEMA_VERSION,
        "schema_boundary": {
            "version": SUMMON_RUNTIME_SCHEMA_VERSION,
            "forward_boundary": "p3 runtime registry keeps removed records for audit and may add optional indexes without changing mutation semantics.",
            "previous_schema_versions": ["p1_3_summon_runtime_v1"],
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


def _normalize_runtime(runtime: dict[str, JSONValue]) -> dict[str, JSONValue]:
    normalized = _empty_runtime()
    normalized.update(dict(runtime))
    normalized["schema_version"] = SUMMON_RUNTIME_SCHEMA_VERSION
    normalized["schema_boundary"] = _empty_runtime()["schema_boundary"]
    entities = dict(normalized.get("entities") or {})
    normalized_entities: dict[str, JSONValue] = {}
    for unit_id, raw_entry in entities.items():
        if not isinstance(unit_id, str) or not isinstance(raw_entry, dict):
            continue
        normalized_entities[unit_id] = _normalize_runtime_entity(unit_id, raw_entry)
    normalized["entities"] = normalized_entities
    normalized["by_owner"] = _normalize_index(normalized.get("by_owner"))
    normalized["by_unique_group"] = _normalize_index(normalized.get("by_unique_group"))
    normalized["last_summon_monsters"] = _normalize_id_list(normalized.get("last_summon_monsters"))
    normalized["last_servants"] = _normalize_id_list(normalized.get("last_servants"))
    normalized["servants"] = _normalize_servants_index(normalized.get("servants"), normalized_entities)
    normalized["assistant_history"] = list(normalized.get("assistant_history") or [])
    normalized["blocked"] = list(normalized.get("blocked") or [])
    return normalized


def _normalize_runtime_entity(unit_id: str, entry: dict[str, JSONValue]) -> dict[str, JSONValue]:
    normalized = dict(entry)
    normalized.setdefault("runtime_id", unit_id)
    normalized.setdefault("unit_id", unit_id)
    normalized.setdefault("template_ref", str(entry.get("template_ref") or entry.get("servant_ref") or ""))
    normalized.setdefault("summon_kind", str(entry.get("summon_kind") or ""))
    normalized.setdefault("owner_id", str(entry.get("owner_id") or ""))
    normalized.setdefault("summoner_id", str(entry.get("summoner_id") or entry.get("owner_id") or ""))
    normalized.setdefault("team_side", str(entry.get("team_side") or ""))
    normalized.setdefault("status", "removed" if entry.get("removed_event_index") is not None else "active")
    normalized.setdefault("created_event_index", entry.get("created_event_index"))
    normalized.setdefault("removed_event_index", entry.get("removed_event_index"))
    normalized.setdefault("removed_reason", str(entry.get("removed_reason") or ""))
    normalized.setdefault("source_trace", entry.get("source_trace") if isinstance(entry.get("source_trace"), dict) else {})
    normalized.setdefault("source_intent_id", str(entry.get("source_intent_id") or ""))
    normalized.setdefault("source_entry_id", str(entry.get("source_entry_id") or ""))
    normalized.setdefault("source_entry_trace", entry.get("source_entry_trace") if isinstance(entry.get("source_entry_trace"), dict) else {})
    normalized.setdefault("targetability", {"targetable": True, "source": normalized.get("source_trace")})
    normalized.setdefault("actionability", {"actionable": False, "source": normalized.get("source_trace")})
    normalized.setdefault("timeline", {"admitted": bool(entry.get("timeline_admitted")), "source": normalized.get("source_trace")})
    normalized.setdefault("lifetime", {"kind": "unknown", "source": normalized.get("source_trace")})
    normalized.setdefault("wave_clear_policy", str(entry.get("wave_clear_policy") or "blocked"))
    return normalized


def _normalize_index(value: JSONValue) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _normalize_id_list(raw) for key, raw in value.items()}


def _normalize_id_list(value: JSONValue) -> list[JSONValue]:
    return [str(item) for item in value or [] if isinstance(item, str)] if isinstance(value, list) else []


def _normalize_servants_index(value: JSONValue, entities: dict[str, JSONValue]) -> dict[str, JSONValue]:
    servants: dict[str, JSONValue] = {}
    if isinstance(value, dict):
        for unit_id, entry in value.items():
            if isinstance(unit_id, str) and isinstance(entry, dict):
                servants[unit_id] = _normalize_runtime_entity(unit_id, entry)
    for unit_id, entry in entities.items():
        if isinstance(entry, dict) and entry.get("summon_kind") == "servant":
            servants.setdefault(unit_id, dict(entry))
    return servants


def _runtime_after_spawn(
    runtime: dict[str, JSONValue],
    state: BattleState,
    plan: SummonTransitionPlan,
    units: tuple[UnitState, ...],
) -> dict[str, JSONValue]:
    after = dict(runtime)
    entities = dict(after.get("entities") or {})
    by_owner = dict(after.get("by_owner") or {})
    by_unique_group = dict(after.get("by_unique_group") or {})
    servants = dict(after.get("servants") or {})
    last_summon_monsters = [str(item) for item in after.get("last_summon_monsters") or [] if isinstance(item, str)]
    last_servants = [str(item) for item in after.get("last_servants") or [] if isinstance(item, str)]
    spawned_monsters: list[str] = []
    spawned_servants: list[str] = []
    for unit in units:
        summon_kind = str(unit.flags.get("summon_kind") or "")
        team_side = str(unit.flags.get("team_side") or "")
        if team_side not in {"ally", "enemy"}:
            team_side = unit.side if unit.side in {"ally", "enemy"} else "neutral"
        lifecycle_source = unit.flags.get("lifecycle_source") if isinstance(unit.flags.get("lifecycle_source"), dict) else {}
        source_trace = plan.source_trace
        template_ref = str(unit.flags.get("servant_ref") or unit.template_id)
        unique_group = str(unit.flags.get("unique_group") or "")
        targetable = bool(lifecycle_source.get("targetable", True))
        action_admission = unit.flags.get("summon_action_admission") if isinstance(unit.flags.get("summon_action_admission"), dict) else {}
        timeline_source = unit.flags.get("initial_action_value_source_trace") if isinstance(unit.flags.get("initial_action_value_source_trace"), dict) else {}
        created = {
            "runtime_id": unit.unit_id,
            "unit_id": unit.unit_id,
            "template_ref": template_ref,
            "summon_kind": summon_kind,
            "owner_id": str(unit.flags.get("owner_id") or ""),
            "summoner_id": str(unit.flags.get("summoner_id") or ""),
            "team_side": team_side,
            "status": "active",
            "source_intent_id": plan.intent_id,
            "source_trace": source_trace,
            "source_entry_id": str(unit.flags.get("summon_entry_id") or ""),
            "source_entry_trace": unit.flags.get("summon_entry_source_trace")
            if isinstance(unit.flags.get("summon_entry_source_trace"), dict)
            else {},
            "source_entry_index": unit.flags.get("summon_entry_index"),
            "source_entry_copy_index": unit.flags.get("summon_entry_copy_index"),
            "source_spawn_index": unit.flags.get("summon_spawn_index"),
            "position_policy": unit.flags.get("summon_position_policy")
            if isinstance(unit.flags.get("summon_position_policy"), dict)
            else {},
            "level_policy": unit.flags.get("summon_level_policy")
            if isinstance(unit.flags.get("summon_level_policy"), dict)
            else {},
            "profile_source_trace": unit.flags.get("combatant_profile_source_trace")
            if isinstance(unit.flags.get("combatant_profile_source_trace"), dict)
            else {},
            "monster_data_card_source_trace": unit.flags.get("monster_data_card_source_trace")
            if isinstance(unit.flags.get("monster_data_card_source_trace"), dict)
            else {},
            "lifetime": {
                "kind": str(lifecycle_source.get("lifetime_policy") or "permanent_until_removed"),
                "source": _first_source_trace(lifecycle_source, source_trace),
            },
            "timeline": {
                "admitted": unit.flags.get("timeline_admitted") is True or unit.action_value > 0.0,
                "initial_action_value": unit.action_value,
                "source": timeline_source or source_trace,
            },
            "targetability": {
                "targetable": targetable,
                "source": _first_source_trace(lifecycle_source, source_trace),
            },
            "actionability": {
                "actionable": unit.flags.get("summon_action_admitted") is True,
                "source": action_admission.get("source_trace") if isinstance(action_admission.get("source_trace"), dict) else source_trace,
            },
            "wave_clear_policy": str(unit.flags.get("wave_clear_policy") or "blocked"),
            "unique_group": unique_group,
            "created_event_index": state.event_index,
            "removed_event_index": None,
            "removed_reason": "",
        }
        entities[unit.unit_id] = created
        owner_id = str(unit.flags.get("owner_id") or "")
        if owner_id:
            owned = [str(item) for item in by_owner.get(owner_id, []) if isinstance(item, str)]
            if unit.unit_id not in owned:
                owned.append(unit.unit_id)
            by_owner[owner_id] = owned
        if unique_group:
            grouped = [str(item) for item in by_unique_group.get(unique_group, []) if isinstance(item, str)]
            if unit.unit_id not in grouped:
                grouped.append(unit.unit_id)
            by_unique_group[unique_group] = grouped
        if summon_kind == "summoned_monster":
            spawned_monsters.append(unit.unit_id)
        if summon_kind == "servant":
            servants[unit.unit_id] = {
                **created,
                "unit_id": unit.unit_id,
                "servant_definition_id": str(unit.flags.get("servant_definition_id") or ""),
                "servant_ref": str(unit.flags.get("servant_ref") or unit.template_id),
                "owner_id": owner_id,
                "team_side": team_side,
                "source_intent_id": plan.intent_id,
                "source_trace": source_trace,
                "created_event_index": state.event_index,
                "removed_event_index": None,
            }
            spawned_servants.append(unit.unit_id)
    after["entities"] = entities
    after["by_owner"] = by_owner
    after["by_unique_group"] = by_unique_group
    after["servants"] = servants
    if spawned_monsters:
        after["last_summon_monsters"] = spawned_monsters
    else:
        after["last_summon_monsters"] = last_summon_monsters
    if spawned_servants:
        after["last_servants"] = spawned_servants
    elif last_servants:
        after["last_servants"] = last_servants
    after["schema_version"] = SUMMON_RUNTIME_SCHEMA_VERSION
    return after


def _runtime_after_remove(
    runtime: dict[str, JSONValue],
    state: BattleState,
    plan: SummonTransitionPlan,
) -> dict[str, JSONValue]:
    after = dict(runtime)
    entities = dict(after.get("entities") or {})
    servants = dict(after.get("servants") or {})
    by_owner = dict(after.get("by_owner") or {})
    by_unique_group = dict(after.get("by_unique_group") or {})
    removed_ids = {unit_id for unit_id in plan.unit_ids}
    for unit_id in plan.unit_ids:
        entry = dict(entities.get(unit_id) or {})
        if entry:
            entry["removed_event_index"] = state.event_index
            entry["removed_reason"] = str(plan.metadata.get("remove_reason") or "")
            entry["status"] = "removed"
            entities[unit_id] = entry
        servant_entry = dict(servants.get(unit_id) or {})
        if servant_entry:
            servant_entry["removed_event_index"] = state.event_index
            servant_entry["removed_reason"] = str(plan.metadata.get("remove_reason") or "")
            servant_entry["status"] = "removed"
            servants[unit_id] = servant_entry
    by_owner = {
        str(owner_id): [str(item) for item in owned if isinstance(item, str) and item not in removed_ids]
        for owner_id, owned in by_owner.items()
        if isinstance(owner_id, str) and isinstance(owned, list)
    }
    by_unique_group = {
        str(group_id): [str(item) for item in grouped if isinstance(item, str) and item not in removed_ids]
        for group_id, grouped in by_unique_group.items()
        if isinstance(group_id, str) and isinstance(grouped, list)
    }
    after["last_summon_monsters"] = [
        str(item)
        for item in after.get("last_summon_monsters", [])
        if isinstance(item, str) and item not in removed_ids
    ]
    after["last_servants"] = [
        str(item)
        for item in after.get("last_servants", [])
        if isinstance(item, str) and item not in removed_ids
    ]
    after["entities"] = entities
    after["servants"] = servants
    after["by_owner"] = by_owner
    after["by_unique_group"] = by_unique_group
    after["schema_version"] = SUMMON_RUNTIME_SCHEMA_VERSION
    return after


def _runtime_mutation(
    state: BattleState,
    before: dict[str, JSONValue],
    after: dict[str, JSONValue],
    plan: SummonTransitionPlan,
    reason: str,
) -> Mutation:
    return Mutation(
        op="set",
        path=("global_flags", "summon_runtime"),
        before=before if state.global_flags.get("summon_runtime") is not None else None,
        after=after,
        reason=reason,
        source="summon_system",
        metadata={
            "summon_operation": plan.operation,
            "summon_plan": plan.to_json(),
            "source_trace": plan.source_trace,
        },
    )


def _remove_cleanup_mutations(
    state: BattleState,
    unit_id: str,
    plan: SummonTransitionPlan,
    *,
    unit_intent_id: str,
) -> tuple[Mutation, ...]:
    unit = state.units.get(unit_id)
    if unit is None:
        return ()
    metadata = {
        "summon_operation": plan.operation,
        "summon_plan": plan.to_json(),
        "unit_id": unit_id,
        "intent_id": unit_intent_id,
        "source_trace": plan.source_trace,
    }
    mutations: list[Mutation] = []
    if unit.statuses:
        mutations.append(
            Mutation(
                op="set",
                path=("units", unit_id, "statuses"),
                before=unit.statuses,
                after=(),
                reason="clear statuses for removed summon",
                source="summon_system",
                metadata={**metadata, "status_cleanup_operation": "clear_statuses"},
                mutation_id=f"mutation:summon_remove_cleanup:{unit_id}:statuses:{plan.operation}",
            )
        )
    if "status_details" in unit.flags:
        mutations.append(
            Mutation(
                op="set",
                path=("units", unit_id, "flags", "status_details"),
                before=unit.flags.get("status_details"),
                after=None,
                reason="clear status details for removed summon",
                source="summon_system",
                metadata={**metadata, "status_cleanup_operation": "clear_status_details"},
                mutation_id=f"mutation:summon_remove_cleanup:{unit_id}:status_details:{plan.operation}",
            )
        )
    mutations.extend(_queue_cleanup_mutations(state, {unit_id}, plan, unit_intent_id=unit_intent_id))
    turn_owner_id = state.global_flags.get("turn_owner_id")
    if turn_owner_id == unit_id:
        mutations.append(
            Mutation(
                op="set",
                path=("global_flags", "turn_owner_id"),
                before=turn_owner_id,
                after=None,
                reason="clear turn owner for removed summon",
                source="summon_system",
                metadata={**metadata, "turn_owner_cleanup_operation": "clear_removed_turn_owner"},
                mutation_id=f"mutation:summon_remove_cleanup:{unit_id}:turn_owner:{plan.operation}",
            )
        )
    return tuple(mutations)


def _queue_cleanup_mutations(
    state: BattleState,
    removed_ids: set[str],
    plan: SummonTransitionPlan,
    *,
    unit_intent_id: str,
) -> tuple[Mutation, ...]:
    mutations: list[Mutation] = []
    for queue_name, entries in sorted(state.queues.items()):
        current = tuple(entries)
        filtered = tuple(entry for entry in current if not _queue_entry_references_removed(entry, removed_ids))
        if filtered == current:
            continue
        mutations.append(
            Mutation(
                op="set",
                path=("queues", queue_name),
                before=list(current),
                after=list(filtered),
                reason="remove queue entries for removed summon",
                source="summon_system",
                metadata={
                    "summon_operation": plan.operation,
                    "summon_plan": plan.to_json(),
                    "unit_id": next(iter(sorted(removed_ids)), ""),
                    "intent_id": unit_intent_id,
                    "source_trace": plan.source_trace,
                    "queue_cleanup_operation": "remove_entries_for_removed_summon",
                    "queue_name": queue_name,
                    "removed_unit_ids": sorted(removed_ids),
                    "removed_entry_count": len(current) - len(filtered),
                },
                mutation_id=f"mutation:summon_remove_cleanup:{queue_name}:{':'.join(sorted(removed_ids))}:{plan.operation}",
            )
        )
    return tuple(mutations)


def _queue_entry_references_removed(entry: JSONValue, removed_ids: set[str]) -> bool:
    if isinstance(entry, str):
        return entry in removed_ids
    if not isinstance(entry, dict):
        return False
    scalar_keys = (
        "actor_id",
        "owner_id",
        "source_id",
        "source_unit_id",
        "unit_id",
        "target_id",
        "turn_owner_id",
    )
    if any(entry.get(key) in removed_ids for key in scalar_keys):
        return True
    list_keys = (
        "target_ids",
        "selected_target_ids",
        "requested_target_ids",
        "legal_target_ids",
    )
    for key in list_keys:
        values = entry.get(key)
        if isinstance(values, list) and any(item in removed_ids for item in values):
            return True
        if isinstance(values, tuple) and any(item in removed_ids for item in values):
            return True
    command = entry.get("command")
    if isinstance(command, dict) and _queue_entry_references_removed(command, removed_ids):
        return True
    target_resolution = entry.get("target_resolution")
    if isinstance(target_resolution, dict) and _queue_entry_references_removed(target_resolution, removed_ids):
        return True
    return False


def _position_for_entry(owner: UnitState, entry: SummonMonsterEntryIR, entry_index: int) -> int | None:
    owner_position = _position(owner.flags.get("position"))
    location_type = str(entry.position_policy.get("location_type") or "")
    if location_type == "BeforeCaster" and owner_position is not None:
        return owner_position - (entry_index + 1)
    if location_type == "AfterCaster" and owner_position is not None:
        return owner_position + (entry_index + 1)
    if location_type in {"First", "KeepOnFirst"}:
        return -1000 + entry_index
    if location_type in {"Last", "KeepOnLast"}:
        return 1000 + entry_index
    return None


def _position(value: JSONValue) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _summoned_monster_unit_id(
    state: BattleState,
    intent: SummonMonsterIntentIR,
    entry: SummonMonsterEntryIR,
    owner_id: str,
    entry_index: int,
    copy_index: int = 0,
) -> str:
    if copy_index <= 0:
        seed = "|".join((intent.summon_intent_id, entry.entry_id, owner_id, str(state.event_index), str(entry_index)))
    else:
        seed = "|".join(
            (
                intent.summon_intent_id,
                entry.entry_id,
                owner_id,
                str(state.event_index),
                str(entry_index),
                str(copy_index),
            )
        )
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    if copy_index <= 0:
        return f"enemy:summon:{digest}:{entry_index}"
    return f"enemy:summon:{digest}:{entry_index}:{copy_index}"


def _source_trace_from_unit(unit: UnitState) -> dict[str, JSONValue]:
    source = unit.flags.get("summon_source_trace")
    return dict(source) if isinstance(source, dict) else {}


def _intent_id_from_unit(unit: UnitState) -> str:
    for key in ("servant_definition_id", "summon_intent_id", "source_intent_id"):
        value = unit.flags.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _remove_source_admitted(
    source_trace: dict[str, JSONValue] | None,
    admission: dict[str, JSONValue] | None,
) -> bool:
    if not isinstance(source_trace, dict) or not source_trace:
        return False
    if not isinstance(admission, dict):
        return False
    return admission.get("coverage_status") == "executable" and admission.get("remove_source_admitted") is True


def _spawn_event(state: BattleState, plan: SummonTransitionPlan, unit: UnitState) -> GameEvent:
    return GameEvent(
        "summon.spawned",
        source_id=plan.owner_id,
        target_id=unit.unit_id,
        event_id=f"event:{state.event_index}:summon:spawned:{unit.unit_id}",
        window="summon",
        process_only=True,
        payload={
            "summon_transition_plan": plan.to_json(),
            "unit_id": unit.unit_id,
            "summon_kind": str(unit.flags.get("summon_kind") or ""),
            "source_trace": plan.source_trace,
        },
    )


def _remove_event(state: BattleState, plan: SummonTransitionPlan, unit_id: str) -> GameEvent:
    return GameEvent(
        "summon.removed",
        source_id=plan.owner_id,
        target_id=unit_id,
        event_id=f"event:{state.event_index}:summon:removed:{unit_id}",
        window="summon",
        process_only=True,
        payload={"summon_transition_plan": plan.to_json(), "unit_id": unit_id},
    )


def _plan_record(
    plan: SummonTransitionPlan,
    mutations: tuple[Mutation, ...],
    *,
    process_only: bool,
    mutation: Mutation | None = None,
    mutation_index: int | None = None,
) -> dict[str, JSONValue]:
    mutation_id = mutation.stable_id() if mutation is not None else mutations[0].stable_id() if mutations else ""
    payload = {
        "operation": plan.operation,
        "ok": plan.ok,
        "blocked_reason": plan.blocked_reason,
        "unit_ids": list(plan.unit_ids),
        "mutation_ids": [item.stable_id() for item in mutations],
        "mutation_count": len(mutations),
        "mutation_index": mutation_index if mutation_index is not None else -1,
        "plan": plan.to_json(),
    }
    record = SettlementRecord(
        record_type="summon_transition",
        source="summon_system",
        mutation_id=mutation_id or None,
        process_only=process_only,
        payload=payload,
        trace=plan.source_trace,
    ).to_json()
    return {
        **record,
        # Backward-compatible observability fields retained for existing reports.
        "record_type": "summon_transition",
        "process_only": process_only,
        "operation": plan.operation,
        "ok": plan.ok,
        "blocked_reason": plan.blocked_reason,
        "unit_ids": list(plan.unit_ids),
        "mutation_ids": [item.stable_id() for item in mutations],
        "source_trace": plan.source_trace,
        "plan": plan.to_json(),
    }


def _plan_records(
    plan: SummonTransitionPlan,
    mutations: tuple[Mutation, ...],
    *,
    process_only: bool,
) -> tuple[dict[str, JSONValue], ...]:
    if process_only or not mutations:
        return (_plan_record(plan, mutations, process_only=process_only),)
    return tuple(
        _plan_record(
            plan,
            mutations,
            process_only=False,
            mutation=mutation,
            mutation_index=index,
        )
        for index, mutation in enumerate(mutations)
    )


def _summon_monster_spawn_instances(intent: SummonMonsterIntentIR) -> tuple[_SummonMonsterSpawnInstance, ...]:
    instances: list[_SummonMonsterSpawnInstance] = []
    spawn_index = 0
    for entry_index, entry in enumerate(intent.entries):
        count = entry.count if isinstance(entry.count, int) and entry.count > 0 else 0
        for copy_index in range(count):
            instances.append(
                _SummonMonsterSpawnInstance(
                    entry=entry,
                    entry_index=entry_index,
                    copy_index=copy_index,
                    spawn_index=spawn_index,
                )
            )
            spawn_index += 1
    return tuple(instances)


def _summon_profile_stat_resolutions(
    resolver: ValueResolver,
    entry: SummonMonsterEntryIR,
    profile: object | None,
) -> dict[str, JSONValue]:
    profile_id = str(getattr(profile, "profile_id", "") or "")
    source_trace = {
        "summon_entry": entry.source.to_json(),
        "combatant_profile": profile.source.to_json() if profile is not None else {},
    }
    return {
        field_name: resolver.resolve(
            ValueBindingRequest(
                binding_kind="combatant_profile_base_stat",
                field_name=field_name,
                required_context_keys=("combatant_profile",),
                source_trace=source_trace,
            ),
            ValueContext(
                combatant_profile_id=profile_id,
                source_trace=source_trace,
            ),
        ).to_json()
        for field_name in ("max_hp", "attack", "defense", "speed")
    }


def _resolved_value(resolutions: dict[str, JSONValue], field_name: str) -> float:
    resolution = resolutions.get(field_name)
    if not isinstance(resolution, dict) or resolution.get("ok") is not True:
        raise ValueError(f"summon profile stat {field_name!r} is not resolved")
    value = resolution.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"summon profile stat {field_name!r} resolved to non numeric value")
    return float(value)


def _summon_level_policy_executable(entry: SummonMonsterEntryIR, profile: object | None) -> bool:
    policy = entry.level_policy
    if policy.get("admission_status") != "executable":
        return False
    kind = str(policy.get("kind") or "")
    if kind == "profile_base_stats_no_runtime_level_scaling":
        profile_id = str(getattr(profile, "profile_id", "") or "")
        return bool(profile_id and policy.get("profile_id") == profile_id)
    return False


def _summon_monster_card_source_available(card: object | None) -> bool:
    if card is None:
        return False
    coverage_status = str(getattr(card, "coverage_status", "") or "")
    return coverage_status in {"lowered", "executable"}


def _summon_delay_ratio(delay_policy: dict[str, JSONValue]) -> float:
    if delay_policy.get("admission_status") != "executable":
        return 1.0
    value = delay_policy.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 1.0
    return max(0.0, float(value))


def _number(mapping: dict[str, JSONValue], key: str) -> float:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"missing numeric {key!r}")
    return float(value)
