from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal

from ..core.model import BattleState, GameEvent, JSONValue, Mutation, UnitState
from ..rules.ir import ServantDefinitionIR, SummonMonsterEntryIR, SummonMonsterIntentIR
from ..rules.rulebook import RuleBook
from .timeline import TimelineSystem
from .unit_lifecycle import UnitLifecycleSystem


SUMMON_RUNTIME_SCHEMA_VERSION = "p1_3_summon_runtime_v1"


@dataclass(frozen=True)
class SummonRuntimeView:
    schema_version: str
    entities: dict[str, JSONValue] = field(default_factory=dict)
    by_owner: dict[str, JSONValue] = field(default_factory=dict)
    by_unique_group: dict[str, JSONValue] = field(default_factory=dict)
    last_summon_monsters: tuple[str, ...] = ()
    servants: dict[str, JSONValue] = field(default_factory=dict)
    assistant_history: tuple[JSONValue, ...] = ()
    blocked: tuple[JSONValue, ...] = ()
    runtime: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "schema_version": self.schema_version,
            "entities": self.entities,
            "by_owner": self.by_owner,
            "by_unique_group": self.by_unique_group,
            "last_summon_monsters": list(self.last_summon_monsters),
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


class SummonSystem:
    def __init__(self, rules: RuleBook) -> None:
        self.rules = rules
        self.lifecycle = UnitLifecycleSystem()
        self.timeline = TimelineSystem()

    def view(self, state: BattleState) -> SummonRuntimeView:
        runtime = _summon_runtime(state)
        return SummonRuntimeView(
            schema_version=SUMMON_RUNTIME_SCHEMA_VERSION,
            entities=dict(runtime.get("entities") or {}),
            by_owner=dict(runtime.get("by_owner") or {}),
            by_unique_group=dict(runtime.get("by_unique_group") or {}),
            last_summon_monsters=tuple(str(item) for item in runtime.get("last_summon_monsters") or () if isinstance(item, str)),
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
        for entry_index, entry in enumerate(intent.entries):
            if entry.coverage_status != "executable":
                blocked.append(entry.blocked_reason or f"summon_monster_entry_not_executable:{entry.coverage_status}")
                continue
            position = _position_for_entry(owner, entry, entry_index)
            if position is None:
                blocked.append("summon_monster_position_not_resolved")
                continue
            unit_id = _summoned_monster_unit_id(state, intent, entry, owner_id, entry_index)
            if unit_id in state.units:
                blocked.append("summon_monster_unit_id_already_exists")
                continue
            unit_ids.append(unit_id)
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
            metadata={"intent": intent.to_json()},
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
        if len(plan.unit_ids) != len(intent.entries):
            blocked = self._blocked(
                plan.operation,
                "summon_plan_entry_unit_mismatch",
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
            self._unit_from_entry(state, owner, intent, entry, unit_id, index)
            for index, (entry, unit_id) in enumerate(zip(intent.entries, plan.unit_ids, strict=True))
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
                    "owner_id": plan.owner_id,
                    "source_trace": plan.source_trace,
                },
            )
            for unit in units
        )
        runtime_before = _summon_runtime(state)
        runtime_after = _runtime_after_spawn(runtime_before, state, plan, units)
        runtime_mutation = _runtime_mutation(state, runtime_before, runtime_after, plan, "record summoned monster spawn")
        mutations = (*spawn_mutations, runtime_mutation)
        events = tuple(_spawn_event(state, plan, unit) for unit in units)
        return SummonTransitionResult(plan, mutations, events, (_plan_record(plan, mutations, process_only=False),))

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
            },
        )
        runtime_before = _summon_runtime(state)
        runtime_after = _runtime_after_spawn(runtime_before, state, plan, (unit,))
        runtime_mutation = _runtime_mutation(state, runtime_before, runtime_after, plan, "record servant spawn")
        mutations = (spawn_mutation, runtime_mutation)
        events = (_spawn_event(state, plan, unit),)
        return SummonTransitionResult(plan, mutations, events, (_plan_record(plan, mutations, process_only=False),))

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
        return SummonTransitionPlan(
            ok=True,
            operation="remove_summon",
            actor_id=str(unit.flags.get("summoner_id") or unit.flags.get("owner_id") or ""),
            owner_id=str(unit.flags.get("owner_id") or ""),
            unit_ids=(unit_id,),
            blocked_reason="",
            source_trace=dict(source_trace or {}),
            metadata={"remove_reason": reason, "remove_admission": dict(admission or {})},
        )

    def apply_remove(self, state: BattleState, plan: SummonTransitionPlan) -> SummonTransitionResult:
        if not plan.ok:
            return SummonTransitionResult(plan, (), (), (_plan_record(plan, (), process_only=True),))
        mutations: list[Mutation] = []
        for unit_id in plan.unit_ids:
            mutations.extend(
                self.lifecycle.remove_mutations(
                    state,
                    unit_id,
                    reason=str(plan.metadata.get("remove_reason") or "remove summon"),
                    source="summon_system",
                    removed_record={
                        "reason": str(plan.metadata.get("remove_reason") or ""),
                        "summon_operation": plan.operation,
                        "source_trace": plan.source_trace,
                    },
                    source_trace=plan.source_trace,
                )
            )
        runtime_before = _summon_runtime(state)
        runtime_after = _runtime_after_remove(runtime_before, state, plan)
        mutations.append(_runtime_mutation(state, runtime_before, runtime_after, plan, "record summon removal"))
        events = tuple(_remove_event(state, plan, unit_id) for unit_id in plan.unit_ids)
        return SummonTransitionResult(plan, tuple(mutations), events, (_plan_record(plan, tuple(mutations), process_only=False),))

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
        return SummonTransitionPlan(
            ok=True,
            operation="owner_removed_cleanup",
            owner_id=owner_id,
            unit_ids=removable,
            source_trace={
                "owner_death_policy_sources": [
                    dict(state.units[unit_id].flags.get("owner_death_policy_source_trace", {}))
                    for unit_id in removable
                ]
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
        entry_index: int,
    ) -> UnitState:
        profile = self.rules.require_combatant_profile(entry.monster_entity_ref)
        card = self.rules.monster_data_card_for_entity(entry.monster_entity_ref)
        if card is None:
            raise ValueError(f"summon entry {entry.entry_id}: monster data card missing")
        speed = _number(profile.base_stats, "speed")
        timeline_rule = self.rules.default_timeline_rule()
        position = _position_for_entry(owner, entry, entry_index)
        resources = {
            f"{damage_type}_resistance": float(value)
            for damage_type, value in profile.resistances.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        if isinstance(profile.status_resistance, (int, float)) and not isinstance(profile.status_resistance, bool):
            resources["effect_resistance"] = float(profile.status_resistance)
        flags: dict[str, JSONValue] = {
            "position": position,
            "summon_kind": "summoned_monster",
            "wave_member_kind": "enemy_summon",
            "wave_clear_policy": entry.wave_clear_policy,
            "owner_id": owner.unit_id,
            "summoner_id": owner.unit_id,
            "summon_intent_id": intent.summon_intent_id,
            "summon_entry_id": entry.entry_id,
            "summon_source_trace": intent.source.to_json(),
            "summon_entry_source_trace": entry.source.to_json(),
            "summon_delay_policy": intent.delay_policy,
            "combatant_profile_id": profile.profile_id,
            "combatant_profile_source_trace": profile.source.to_json(),
            "combatant_profile_coverage_status": profile.coverage_status,
            "monster_data_card_id": card.card_id,
            "monster_passive_mechanism_slot_ids": list(card.passive_mechanism_slot_ids),
            "weaknesses": list(profile.weaknesses),
            "debuff_resistances": list(profile.debuff_resistances),
            "initial_action_value_source_trace": {
                "timeline_rule_id": timeline_rule.timeline_rule_id,
                "timeline_rule_source": timeline_rule.source.to_json(),
                "speed_source": profile.source.to_json(),
                "speed": speed,
                "formula": timeline_rule.initial_action_value_rule,
                "summon_delay_policy": intent.delay_policy,
                "summon_delay_application": "no_additional_initial_action_value_offset",
            },
        }
        return UnitState(
            unit_id=unit_id,
            side="enemy",
            template_id=entry.monster_entity_ref,
            level=owner.level,
            max_hp=_number(profile.base_stats, "max_hp"),
            hp=_number(profile.base_stats, "max_hp"),
            attack=_number(profile.base_stats, "attack"),
            defense=_number(profile.base_stats, "defense"),
            speed=speed,
            toughness=_number(profile.toughness_profile, "current_toughness"),
            max_toughness=_number(profile.toughness_profile, "max_toughness"),
            action_value=self.timeline.full_action_value(speed, timeline_rule),
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
            "servant_definition_id": definition.servant_definition_id,
            "servant_ref": definition.servant_ref,
            "summon_intent_id": definition.servant_definition_id,
            "summon_source_trace": definition.source.to_json(),
            "servant_definition_source_trace": definition.source.to_json(),
            "stat_source": definition.stat_source,
            "timeline_source": definition.timeline_source,
            "lifecycle_source": definition.lifecycle_source,
            "timeline_admitted": True,
            "summon_action_admitted": True,
            "summon_action_admission": {
                "coverage_status": "executable",
                "source_trace": action_admission_source,
                "action_set": definition.action_set,
                "ability_graph_ids": list(definition.ability_graph_ids),
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
    if isinstance(runtime, dict) and runtime.get("schema_version") == SUMMON_RUNTIME_SCHEMA_VERSION:
        return dict(runtime)
    return _empty_runtime()


def _empty_runtime() -> dict[str, JSONValue]:
    return {
        "schema_version": SUMMON_RUNTIME_SCHEMA_VERSION,
        "entities": {},
        "by_owner": {},
        "by_unique_group": {},
        "last_summon_monsters": [],
        "servants": {},
        "assistant_history": [],
        "blocked": [],
    }


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
        created = {
            "summon_kind": summon_kind,
            "owner_id": str(unit.flags.get("owner_id") or ""),
            "summoner_id": str(unit.flags.get("summoner_id") or ""),
            "team_side": team_side,
            "source_intent_id": plan.intent_id,
            "source_trace": plan.source_trace,
            "lifetime": {
                "kind": str(lifecycle_source.get("lifetime_policy") or "permanent_until_removed"),
                "source": _first_source_trace(lifecycle_source, plan.source_trace),
            },
            "timeline_admitted": unit.flags.get("timeline_admitted") is True,
            "targetability": {
                "targetable": bool(lifecycle_source.get("targetable", True)),
                "source": _first_source_trace(lifecycle_source, plan.source_trace),
            },
            "wave_clear_policy": str(unit.flags.get("wave_clear_policy") or "blocked"),
            "unique_group": "",
            "created_event_index": state.event_index,
            "removed_event_index": None,
        }
        entities[unit.unit_id] = created
        owner_id = str(unit.flags.get("owner_id") or "")
        if owner_id:
            owned = [str(item) for item in by_owner.get(owner_id, []) if isinstance(item, str)]
            if unit.unit_id not in owned:
                owned.append(unit.unit_id)
            by_owner[owner_id] = owned
        unique_group = str(unit.flags.get("unique_group") or "")
        if unique_group:
            grouped = [str(item) for item in by_unique_group.get(unique_group, []) if isinstance(item, str)]
            if unit.unit_id not in grouped:
                grouped.append(unit.unit_id)
            by_unique_group[unique_group] = grouped
        if summon_kind == "summoned_monster":
            spawned_monsters.append(unit.unit_id)
        if summon_kind == "servant":
            servants[unit.unit_id] = {
                "unit_id": unit.unit_id,
                "servant_definition_id": str(unit.flags.get("servant_definition_id") or ""),
                "servant_ref": str(unit.flags.get("servant_ref") or unit.template_id),
                "owner_id": owner_id,
                "team_side": team_side,
                "source_intent_id": plan.intent_id,
                "source_trace": plan.source_trace,
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
    for unit_id in plan.unit_ids:
        entry = dict(entities.get(unit_id) or {})
        if entry:
            entry["removed_event_index"] = state.event_index
            entry["removed_reason"] = str(plan.metadata.get("remove_reason") or "")
            entities[unit_id] = entry
        servant_entry = dict(servants.get(unit_id) or {})
        if servant_entry:
            servant_entry["removed_event_index"] = state.event_index
            servant_entry["removed_reason"] = str(plan.metadata.get("remove_reason") or "")
            servants[unit_id] = servant_entry
    after["entities"] = entities
    after["servants"] = servants
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


def _position_for_entry(owner: UnitState, entry: SummonMonsterEntryIR, entry_index: int) -> int | None:
    owner_position = _position(owner.flags.get("position"))
    location_type = str(entry.position_policy.get("location_type") or "")
    if location_type == "BeforeCaster" and owner_position is not None:
        return owner_position - (entry_index + 1)
    if location_type == "AfterCaster" and owner_position is not None:
        return owner_position + (entry_index + 1)
    if location_type == "First":
        return -1000 + entry_index
    if location_type == "Last":
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
) -> str:
    seed = "|".join((intent.summon_intent_id, entry.entry_id, owner_id, str(state.event_index), str(entry_index)))
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"enemy:summon:{digest}:{entry_index}"


def _source_trace_from_unit(unit: UnitState) -> dict[str, JSONValue]:
    source = unit.flags.get("summon_source_trace")
    return dict(source) if isinstance(source, dict) else {}


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
) -> dict[str, JSONValue]:
    return {
        "record_type": "summon_transition",
        "process_only": process_only,
        "operation": plan.operation,
        "ok": plan.ok,
        "blocked_reason": plan.blocked_reason,
        "unit_ids": list(plan.unit_ids),
        "mutation_ids": [mutation.stable_id() for mutation in mutations],
        "source_trace": plan.source_trace,
        "plan": plan.to_json(),
    }


def _number(mapping: dict[str, JSONValue], key: str) -> float:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"missing numeric {key!r}")
    return float(value)
