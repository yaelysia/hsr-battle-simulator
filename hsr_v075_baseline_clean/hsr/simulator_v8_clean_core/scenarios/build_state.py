from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .identity import IdentityResolver
from .schema import PanelInput, ScenarioSpec
from ..core.model import ActionCommand, BattleState, UnitState
from ..core.reducer import MutationReducer
from ..rules.ir import CombatantProfileIR
from ..rules.rulebook import RuleBook
from ..systems.effect import EffectRegistry
from ..systems.status import StatusSystem


@dataclass(frozen=True)
class ScenarioBuildResult:
    state: BattleState
    commands: tuple[ActionCommand, ...]
    source_traces: tuple[dict[str, object], ...]


class ScenarioStateBuilder:
    def __init__(self, rules: RuleBook):
        self.rules = rules
        self.identity = IdentityResolver(rules)

    def build(self, scenario: ScenarioSpec) -> ScenarioBuildResult:
        validation = self.identity.validate(scenario)
        if not validation.ok:
            raise ValueError("; ".join(validation.errors))

        units = {}
        source_traces = list(validation.source_traces)
        eidolon_startup_specs: list[dict[str, Any]] = []
        trace_startup_specs: list[dict[str, Any]] = []
        passive_startup_specs: list[dict[str, Any]] = []
        for unit in scenario.units:
            panel = unit.panel
            flags = dict(panel.flags)
            if unit.position is not None:
                flags["position"] = unit.position
            entity = self.rules.require_entity(unit.entity_ref)
            card = None
            if unit.eidolon_level < 0 or unit.eidolon_level > 6:
                raise ValueError(f"unit {unit.unit_id}: eidolon_level must be between 0 and 6")
            if entity.entity_type == "avatar":
                card = self.rules.character_data_card_for_entity(unit.entity_ref)
                if card is not None:
                    eidolon_slots = self.rules.character_eidolon_slots_for_level(card.card_id, unit.eidolon_level)
                    flags["character_data_card_id"] = card.card_id
                    flags["eidolon_level_requested"] = unit.eidolon_level
                    flags["enabled_eidolon_ranks"] = tuple(slot.rank for slot in eidolon_slots)
                    flags["enabled_eidolon_slot_ids"] = tuple(slot.eidolon_slot_id for slot in eidolon_slots)
                    flags["enabled_eidolon_rank_ids"] = tuple(slot.rank_id for slot in eidolon_slots)
                    flags["enabled_eidolon_mechanism_slot_ids"] = tuple(
                        slot_id for slot in eidolon_slots for slot_id in slot.linked_mechanism_slot_ids
                    )
                    flags["eidolon_activation_policy"] = {
                        "kind": "prefix_closed",
                        "requested_level": unit.eidolon_level,
                        "independent_rank_toggle_allowed": False,
                    }
                    flags["eidolon_source_traces"] = tuple(slot.source.to_json() for slot in eidolon_slots)
                    runtime_activation = _eidolon_runtime_activation(eidolon_slots)
                    flags.update(runtime_activation["flags"])
                    for startup_spec in runtime_activation["startup_specs"]:
                        eidolon_startup_specs.append({"unit_id": unit.unit_id, **startup_spec})
                elif unit.eidolon_level:
                    raise ValueError(f"unit {unit.unit_id}: eidolon_level requires a character data card")
            profile = self.rules.combatant_profile(unit.entity_ref) if entity.entity_type in {"monster", "monster_template"} else None
            monster_card = None
            if entity.entity_type == "monster":
                monster_card = self.rules.monster_data_card_for_entity(unit.entity_ref)
                if monster_card is not None:
                    flags["monster_data_card_id"] = monster_card.card_id
                    flags["monster_passive_mechanism_slot_ids"] = tuple(monster_card.passive_mechanism_slot_ids)
            profile_values = _profile_values(profile)
            panel_overrides = _panel_overrides(panel, profile_values)
            if profile is not None:
                flags["combatant_profile_id"] = profile.profile_id
                flags["combatant_profile_source_trace"] = profile.source.to_json()
                flags["combatant_profile_coverage_status"] = profile.coverage_status
                if profile.blocked_reason:
                    flags["combatant_profile_blocked_reason"] = profile.blocked_reason
            if panel_overrides:
                flags["panel_overrides"] = panel_overrides
            if profile is not None and profile.coverage_status == "executable" and not _panel_has_flag(panel, "weaknesses"):
                flags["weaknesses"] = tuple(profile.weaknesses)
            elif entity.entity_type == "monster" and not _panel_has_flag(panel, "weaknesses"):
                weaknesses = entity.fields.get("StanceWeakList")
                if isinstance(weaknesses, list):
                    flags["weaknesses"] = tuple(str(item) for item in weaknesses)
            resources = _resources_with_profile_resistances(panel, profile)
            trace_activation = _trace_runtime_activation(self.rules, card, flags)
            flags.update(trace_activation["flags"])
            for startup_spec in trace_activation["startup_specs"]:
                trace_startup_specs.append({"unit_id": unit.unit_id, **startup_spec})
            passive_activation = _passive_runtime_activation(self.rules, monster_card)
            flags.update(passive_activation["flags"])
            for startup_spec in passive_activation["startup_specs"]:
                passive_startup_specs.append({"unit_id": unit.unit_id, **startup_spec})
            for key, delta in trace_activation["resource_deltas"].items():
                resources[key] = float(resources.get(key, 0.0)) + float(delta)
            max_hp = _panel_or_profile_value(panel, "max_hp", profile_values, required=entity.entity_type in {"monster", "monster_template"})
            attack = _panel_or_profile_value(panel, "attack", profile_values, required=entity.entity_type in {"monster", "monster_template"})
            defense = _panel_or_profile_value(panel, "defense", profile_values, required=entity.entity_type in {"monster", "monster_template"})
            speed = _panel_or_profile_value(panel, "speed", profile_values, required=entity.entity_type in {"monster", "monster_template"})
            max_hp = _apply_trace_base_stat(max_hp, "max_hp", trace_activation)
            attack = _apply_trace_base_stat(attack, "attack", trace_activation)
            defense = _apply_trace_base_stat(defense, "defense", trace_activation)
            speed = _apply_trace_base_stat(speed, "speed", trace_activation)
            hp = panel.hp if _panel_has(panel, "hp") and panel.hp is not None else max_hp
            units[unit.unit_id] = UnitState(
                unit_id=unit.unit_id,
                side=unit.side,
                template_id=unit.entity_ref,
                level=unit.level,
                max_hp=max_hp,
                hp=hp,
                attack=attack,
                defense=defense,
                speed=speed,
                energy=panel.energy,
                max_energy=panel.max_energy,
                toughness=_panel_or_profile_value(panel, "toughness", profile_values, required=entity.entity_type in {"monster", "monster_template"}),
                max_toughness=_panel_or_profile_value(panel, "max_toughness", profile_values, required=entity.entity_type in {"monster", "monster_template"}),
                action_value=panel.action_value,
                statuses=panel.statuses,
                flags=flags,
                resources=resources,
            )

        global_flags = dict(scenario.global_flags)
        if scenario.route:
            global_flags.setdefault("turn_owner_id", scenario.route[0].actor_id)
        global_flags.setdefault("phase", "scenario")
        global_flags.setdefault("current_window", "idle")
        state = BattleState(
            units=units,
            wave_index=scenario.wave_index,
            skill_points=scenario.skill_points,
            max_skill_points=scenario.max_skill_points,
            global_flags=global_flags,
            rng_state=scenario.rng_state,
        )
        state, startup_traces = _apply_startup_ability_effects(
            state,
            self.rules,
            [*eidolon_startup_specs, *trace_startup_specs, *passive_startup_specs],
        )
        source_traces.extend(startup_traces)
        commands = tuple(
            ActionCommand(
                actor_id=step.actor_id,
                action_id=step.action_ref,
                action_level=step.action_level,
                target_ids=step.target_ids,
                source=step.source,
                queue_name=step.queue_name,
                metadata=step.metadata,
            )
            for step in scenario.route
        )
        return ScenarioBuildResult(state=state, commands=commands, source_traces=tuple(source_traces))


def _trace_runtime_activation(rules: RuleBook, card: object | None, flags: dict[str, Any]) -> dict[str, Any]:
    if card is None:
        return {"flags": {}, "base_stat_ratios": {}, "base_stat_deltas": {}, "resource_deltas": {}, "startup_specs": []}
    card_id = str(getattr(card, "card_id", ""))
    if not card_id:
        return {"flags": {}, "base_stat_ratios": {}, "base_stat_deltas": {}, "resource_deltas": {}, "startup_specs": []}
    explicit_enabled = set(_string_items(flags.get("enabled_trace_node_ids")))
    disabled = set(_string_items(flags.get("disabled_trace_node_ids")))
    nodes = rules.character_trace_nodes_for_card(card_id)
    slots_by_id = {slot.mechanism_slot_id: slot for slot in rules.character_mechanism_slots_for_card(card_id)}
    enabled_node_ids: list[str] = []
    applied_terms: list[dict[str, Any]] = []
    blocked_slots: list[dict[str, Any]] = []
    base_stat_ratios: dict[str, float] = {}
    base_stat_deltas: dict[str, float] = {}
    resource_deltas: dict[str, float] = {}
    source_traces: list[dict[str, Any]] = []
    startup_specs: list[dict[str, Any]] = []
    for node in nodes:
        default_enabled = any(
            bool((slots_by_id.get(slot_id) and slots_by_id[slot_id].activation.get("default_enabled") is True))
            for slot_id in node.linked_mechanism_slot_ids
        )
        enabled = node.trace_node_id in explicit_enabled or (default_enabled and node.trace_node_id not in disabled)
        if not enabled:
            continue
        enabled_node_ids.append(node.trace_node_id)
        source_traces.append(node.source.to_json())
        for slot_id in node.linked_mechanism_slot_ids:
            slot = slots_by_id.get(slot_id)
            if slot is not None and slot.mechanism_kind == "trace_ability_hook":
                if slot.coverage_status != "executable":
                    blocked_slots.append(
                        {
                            "trace_node_id": node.trace_node_id,
                            "mechanism_slot_id": slot_id,
                            "blocked_reason": slot.blocked_reason or f"trace_slot_not_executable:{slot.coverage_status}",
                            "source": slot.source.to_json(),
                        }
                    )
                    continue
                startup_specs.append(
                    {
                        "kind": "trace_startup_ability",
                        "slot": slot,
                        "slot_id": slot.mechanism_slot_id,
                        "slot_id_field": "mechanism_slot_id",
                        "trace_node_id": node.trace_node_id,
                        "ability_name": str(slot.semantics.get("ability_name") or ""),
                        "param_values": tuple(_number_items(slot.semantics.get("param_values"))),
                        "dynamic_value_bindings": slot.semantics.get("dynamic_value_bindings"),
                        "dynamic_value_binding_mode": "configured_by_hash_required",
                    }
                )
                continue
            if slot is None or slot.mechanism_kind != "trace_static_stat_bonus":
                continue
            if slot.coverage_status != "executable":
                blocked_slots.append(
                    {
                        "trace_node_id": node.trace_node_id,
                        "mechanism_slot_id": slot_id,
                        "blocked_reason": slot.blocked_reason or f"trace_slot_not_executable:{slot.coverage_status}",
                        "source": slot.source.to_json(),
                    }
                )
                continue
            for term in _dict_items(slot.semantics.get("mapped_terms")):
                kind = str(term.get("application_kind") or "")
                key = str(term.get("target_key") or "")
                value = _float_or_none(term.get("value"))
                if value is None or not key:
                    blocked_slots.append(
                        {
                            "trace_node_id": node.trace_node_id,
                            "mechanism_slot_id": slot_id,
                            "blocked_reason": "trace_static_stat_term_invalid",
                            "term": term,
                            "source": slot.source.to_json(),
                        }
                    )
                    continue
                applied_terms.append(
                    {
                        "trace_node_id": node.trace_node_id,
                        "mechanism_slot_id": slot_id,
                        "application_kind": kind,
                        "target_key": key,
                        "value": value,
                        "source": slot.source.to_json(),
                    }
                )
                if kind == "base_stat_ratio":
                    base_stat_ratios[key] = base_stat_ratios.get(key, 0.0) + value
                elif kind == "base_stat_delta":
                    base_stat_deltas[key] = base_stat_deltas.get(key, 0.0) + value
                elif kind == "resource_delta":
                    resource_deltas[key] = resource_deltas.get(key, 0.0) + value
                else:
                    blocked_slots.append(
                        {
                            "trace_node_id": node.trace_node_id,
                            "mechanism_slot_id": slot_id,
                            "blocked_reason": f"trace_static_stat_application_kind_not_admitted:{kind}",
                            "term": term,
                            "source": slot.source.to_json(),
                        }
                    )
    trace_flags: dict[str, Any] = {
        "trace_activation_policy": {
            "kind": "trace_toggle",
            "explicit_enabled_trace_node_ids": tuple(sorted(explicit_enabled)),
            "disabled_trace_node_ids": tuple(sorted(disabled)),
            "default_unlock_respected": True,
        },
        "enabled_trace_node_ids": tuple(enabled_node_ids),
        "trace_source_traces": tuple(source_traces),
    }
    if applied_terms:
        trace_flags["trace_static_stat_bonus_terms"] = tuple(applied_terms)
    if blocked_slots:
        trace_flags["trace_static_stat_blocked_slots"] = tuple(blocked_slots)
    if base_stat_ratios or base_stat_deltas:
        trace_flags["trace_panel_adjustments"] = {
            "base_stat_ratios": dict(sorted(base_stat_ratios.items())),
            "base_stat_deltas": dict(sorted(base_stat_deltas.items())),
        }
    if resource_deltas:
        trace_flags["trace_resource_adjustments"] = dict(sorted(resource_deltas.items()))
    return {
        "flags": trace_flags,
        "base_stat_ratios": base_stat_ratios,
        "base_stat_deltas": base_stat_deltas,
        "resource_deltas": resource_deltas,
        "startup_specs": startup_specs,
    }


def _passive_runtime_activation(rules: RuleBook, card: object | None) -> dict[str, Any]:
    if card is None:
        return {"flags": {}, "startup_specs": []}
    card_id = str(getattr(card, "card_id", ""))
    if not card_id:
        return {"flags": {}, "startup_specs": []}
    slots = rules.passive_mechanism_slots_for_card(card_id)
    enabled_slot_ids: list[str] = []
    blocked_slots: list[dict[str, Any]] = []
    source_traces: list[dict[str, Any]] = []
    startup_specs: list[dict[str, Any]] = []
    for slot in slots:
        source_traces.append(slot.source.to_json())
        if slot.coverage_status != "executable":
            blocked_slots.append(
                {
                    "passive_slot_id": slot.passive_slot_id,
                    "blocked_reason": slot.blocked_reason or f"passive_slot_not_executable:{slot.coverage_status}",
                    "source": slot.source.to_json(),
                }
            )
            continue
        startup_admission = slot.semantics.get("startup_admission")
        if not isinstance(startup_admission, dict) or startup_admission.get("admission_status") != "executable":
            blocked_slots.append(
                {
                    "passive_slot_id": slot.passive_slot_id,
                    "blocked_reason": "passive_startup_admission_not_executable",
                    "source": slot.source.to_json(),
                }
            )
            continue
        ability_name = str(slot.semantics.get("ability_name") or slot.linked_ir_ids.get("ability_name") or "")
        admitted_task_ids = tuple(
            str(item.get("task_id"))
            for item in _dict_items(startup_admission.get("admitted_tasks"))
            if item.get("task_id")
        )
        enabled_slot_ids.append(slot.passive_slot_id)
        startup_specs.append(
            {
                "kind": "monster_passive_startup_ability",
                "slot": slot,
                "slot_id": slot.passive_slot_id,
                "slot_id_field": "passive_slot_id",
                "ability_name": ability_name,
                "param_values": (),
                "dynamic_value_bindings": {},
                "dynamic_value_binding_mode": "no_dynamic_values_admitted",
                "admitted_task_ids": admitted_task_ids,
            }
        )
    flags: dict[str, Any] = {
        "passive_activation_policy": {
            "kind": "monster_ability_name_list_startup",
            "source_field": "MonsterConfig.AbilityNameList",
            "event_trigger_execution_admitted": False,
        },
        "passive_source_traces": tuple(source_traces),
    }
    if enabled_slot_ids:
        flags["enabled_passive_mechanism_slot_ids"] = tuple(enabled_slot_ids)
    if blocked_slots:
        flags["blocked_passive_mechanism_slots"] = tuple(blocked_slots)
    return {"flags": flags, "startup_specs": startup_specs}


def _apply_trace_base_stat(value: float, key: str, activation: dict[str, Any]) -> float:
    ratio = float(activation["base_stat_ratios"].get(key, 0.0))
    delta = float(activation["base_stat_deltas"].get(key, 0.0))
    return max(0.0, value * (1.0 + ratio) + delta)


def _string_items(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item))
    return ()


def _dict_items(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def _float_or_none(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _profile_values(profile: CombatantProfileIR | None) -> dict[str, float]:
    if profile is None or profile.coverage_status != "executable":
        return {}
    values: dict[str, float] = {}
    base_stats = profile.base_stats
    toughness_profile = profile.toughness_profile
    for key in ("max_hp", "attack", "defense", "speed"):
        value = base_stats.get(key)
        if isinstance(value, (int, float)):
            values[key] = float(value)
    toughness = toughness_profile.get("current_toughness")
    max_toughness = toughness_profile.get("max_toughness")
    if isinstance(toughness, (int, float)):
        values["toughness"] = float(toughness)
    if isinstance(max_toughness, (int, float)):
        values["max_toughness"] = float(max_toughness)
    return values


def _panel_or_profile_value(
    panel: PanelInput,
    key: str,
    profile_values: dict[str, float],
    *,
    required: bool,
) -> float:
    if _panel_has(panel, key):
        return float(getattr(panel, key))
    if key in profile_values:
        return profile_values[key]
    if required:
        raise ValueError(f"missing combatant profile value and explicit panel field {key!r}")
    return float(getattr(panel, key))


def _panel_has(panel: PanelInput, key: str) -> bool:
    return key in set(panel.explicit_fields)


def _panel_has_flag(panel: PanelInput, key: str) -> bool:
    return _panel_has(panel, "flags") and key in panel.flags


def _panel_overrides(panel: PanelInput, profile_values: dict[str, float]) -> tuple[str, ...]:
    return tuple(
        key
        for key in ("max_hp", "attack", "defense", "speed", "toughness", "max_toughness")
        if key in profile_values and _panel_has(panel, key)
    )


def _resources_with_profile_resistances(
    panel: PanelInput,
    profile: CombatantProfileIR | None,
) -> dict[str, float]:
    resources = dict(panel.resources)
    if profile is None or profile.coverage_status != "executable":
        return resources
    for damage_type, value in profile.resistances.items():
        if not isinstance(value, (int, float)):
            continue
        resources.setdefault(f"{damage_type}_resistance", float(value))
    return resources


def _eidolon_runtime_activation(eidolon_slots: tuple[object, ...]) -> dict[str, Any]:
    flags: dict[str, object] = {}
    startup_specs: list[dict[str, Any]] = []
    skill_level_bonus_by_action_id: dict[str, int] = {}
    skill_level_bonus_sources: dict[str, list[dict[str, object]]] = {}
    startup_ability_names: list[str] = []
    for slot in eidolon_slots:
        semantics = getattr(slot, "semantics", {})
        if not isinstance(semantics, dict):
            continue
        rank_ability = semantics.get("rank_ability")
        if isinstance(rank_ability, (list, tuple)):
            for item in rank_ability:
                if isinstance(item, str) and item:
                    startup_ability_names.append(item)
                    startup_specs.append(
                        {
                            "kind": "eidolon_startup_rank_ability",
                            "slot": slot,
                            "slot_id": getattr(slot, "eidolon_slot_id", ""),
                            "slot_id_field": "eidolon_slot_id",
                            "ability_name": item,
                            "param_values": tuple(_number_items(semantics.get("param_values"))),
                            "dynamic_value_bindings": semantics.get("dynamic_value_bindings"),
                            "dynamic_value_binding_mode": "request_order_fallback",
                        }
                    )
        skill_add_level_list = semantics.get("skill_add_level_list")
        if isinstance(skill_add_level_list, dict):
            for raw_skill_id, raw_bonus in skill_add_level_list.items():
                raw_skill_id = str(raw_skill_id)
                bonus = _int_or_none(raw_bonus)
                if bonus is None:
                    continue
                action_id = f"avatar_skill:{raw_skill_id}"
                skill_level_bonus_by_action_id[action_id] = skill_level_bonus_by_action_id.get(action_id, 0) + bonus
                skill_level_bonus_sources.setdefault(action_id, []).append(
                    {
                        "eidolon_slot_id": getattr(slot, "eidolon_slot_id", ""),
                        "rank": getattr(slot, "rank", 0),
                        "rank_id": getattr(slot, "rank_id", ""),
                        "raw_skill_id": raw_skill_id,
                        "bonus": bonus,
                        "source": getattr(slot, "source", None).to_json() if getattr(slot, "source", None) else {},
                    }
                )
    if skill_level_bonus_by_action_id:
        flags["eidolon_skill_level_bonus_by_action_id"] = skill_level_bonus_by_action_id
        flags["eidolon_skill_level_bonus_sources"] = skill_level_bonus_sources
    if startup_ability_names:
        flags["eidolon_startup_rank_abilities"] = tuple(startup_ability_names)
    return {"flags": flags, "startup_specs": startup_specs}


def _apply_startup_ability_effects(
    state: BattleState,
    rules: RuleBook,
    startup_specs: list[dict[str, Any]],
) -> tuple[BattleState, tuple[dict[str, object], ...]]:
    if not startup_specs:
        return state, ()
    reducer = MutationReducer()
    status_system = StatusSystem(rules)
    effect_registry = EffectRegistry(status_system)
    current = state
    traces: list[dict[str, object]] = []
    for spec in startup_specs:
        unit_id = str(spec.get("unit_id") or "")
        ability_name = str(spec.get("ability_name") or "")
        slot = spec.get("slot")
        kind = str(spec.get("kind") or "startup_ability")
        slot_id = str(spec.get("slot_id") or getattr(slot, "eidolon_slot_id", "") or getattr(slot, "mechanism_slot_id", ""))
        slot_id_field = str(spec.get("slot_id_field") or "slot_id")
        trace_node_id = str(spec.get("trace_node_id") or "")
        graphs = tuple(
            graph
            for graph in rules.standalone_ability_graphs_by_name(ability_name)
            if graph.coverage_status == "executable"
        )
        if len(graphs) != 1:
            traces.append(
                _startup_trace_payload(
                    kind=kind,
                    unit_id=unit_id,
                    ability_name=ability_name,
                    slot_id=slot_id,
                    slot_id_field=slot_id_field,
                    trace_node_id=trace_node_id,
                    status="blocked",
                    reason="startup_ability_graph_missing_or_ambiguous",
                    extra={"graph_count": len(graphs)},
                )
            )
            continue
        graph = graphs[0]
        admitted_task_ids = set(_string_items(spec.get("admitted_task_ids")))
        applied_count = 0
        for phase_id in graph.phase_ids:
            for task in rules.ability_tasks_for_phase(phase_id):
                if admitted_task_ids and task.task_id not in admitted_task_ids:
                    continue
                if task.callback_kind != "OnStart" or task.parent_task_id or task.opcode != "AddModifier" or not task.effect_id:
                    continue
                effect = rules.effect(task.effect_id)
                if effect is None:
                    traces.append(
                        _startup_blocked_trace(
                            kind,
                            unit_id,
                            ability_name,
                            slot_id,
                            slot_id_field,
                            trace_node_id,
                            graph,
                            task.task_id,
                            "startup_effect_missing",
                        )
                    )
                    continue
                coverage = effect_registry.coverage(effect)
                if coverage != "executable":
                    traces.append(
                        _startup_blocked_trace(
                            kind,
                            unit_id,
                            ability_name,
                            slot_id,
                            slot_id_field,
                            trace_node_id,
                            graph,
                            task.task_id,
                            f"startup_effect_not_executable:{coverage}",
                        )
                    )
                    continue
                dynamic_values, binding_trace = _startup_dynamic_values(effect.payload.get("standard"), spec)
                if binding_trace.get("admission_status") == "blocked":
                    traces.append(
                        _startup_blocked_trace(
                            kind,
                            unit_id,
                            ability_name,
                            slot_id,
                            slot_id_field,
                            trace_node_id,
                            graph,
                            task.task_id,
                            str(binding_trace.get("blocked_reason") or "startup_dynamic_value_binding_blocked"),
                            binding_trace=binding_trace,
                        )
                    )
                    continue
                result = status_system.apply_add_modifier(
                    current,
                    effect,
                    caster_id=unit_id,
                    source_id=f"{kind}:{slot_id}:{ability_name}:{task.task_id}",
                    owner_id=unit_id,
                    param_entity_id=unit_id,
                    current_action_target_id=unit_id,
                    dynamic_values=dynamic_values,
                    binding_sources=(),
                )
                current = reducer.apply_all(current, result.mutations)
                applied_count += len(result.mutations)
                traces.append(
                    _startup_trace_payload(
                        kind=kind,
                        unit_id=unit_id,
                        ability_name=ability_name,
                        slot_id=slot_id,
                        slot_id_field=slot_id_field,
                        trace_node_id=trace_node_id,
                        status="applied" if result.ok else "blocked",
                        extra={
                            "standalone_ability_graph_id": graph.standalone_ability_graph_id,
                            "task_id": task.task_id,
                            "effect_id": effect.effect_id,
                            "mutation_count": len(result.mutations),
                            "unsupported": list(result.unsupported),
                            "dynamic_value_binding": binding_trace,
                            "source": getattr(slot, "source", None).to_json() if getattr(slot, "source", None) else {},
                        },
                    )
                )
        if applied_count == 0:
            traces.append(
                _startup_trace_payload(
                    kind=kind,
                    unit_id=unit_id,
                    ability_name=ability_name,
                    slot_id=slot_id,
                    slot_id_field=slot_id_field,
                    trace_node_id=trace_node_id,
                    status="blocked",
                    reason="startup_ability_has_no_admitted_on_start_add_modifier",
                    extra={"standalone_ability_graph_id": graph.standalone_ability_graph_id},
                )
            )
    return current, tuple(traces)


def _startup_dynamic_values(
    standard: object,
    spec: dict[str, Any],
) -> tuple[dict[str, float], dict[str, object]]:
    if not isinstance(standard, dict):
        return {}, {"admission_status": "not_applicable", "reason": "standard_payload_missing"}
    params = tuple(_number_items(spec.get("param_values")))
    configured_bindings = spec.get("dynamic_value_bindings")
    configured_by_hash = configured_bindings.get("by_hash") if isinstance(configured_bindings, dict) else None
    if not isinstance(configured_by_hash, dict):
        configured_by_hash = {}
    requests = standard.get("dynamic_value_requests")
    if not isinstance(requests, dict) or not requests:
        if configured_by_hash:
            return _eidolon_configured_dynamic_values(params, configured_by_hash, spec)
        return {}, {"admission_status": "not_applicable", "reason": "no_dynamic_value_requests"}
    request_items = [(str(name), request) for name, request in requests.items() if isinstance(request, dict)]
    dynamic_values: dict[str, float] = {}
    bindings: list[dict[str, object]] = []
    for index, (name, request) in enumerate(request_items):
        raw_hash = request.get("hash")
        if raw_hash is None:
            return {}, {
                "admission_status": "blocked",
                "blocked_reason": "startup_dynamic_value_request_hash_missing",
                "request_name": name,
            }
        configured = configured_by_hash.get(str(raw_hash))
        param_index = index
        binding_source_kind = "startup_param_request_order"
        if isinstance(configured, dict):
            configured_index = configured.get("param_index")
            if not isinstance(configured_index, int):
                return {}, {
                    "admission_status": "blocked",
                    "blocked_reason": "startup_dynamic_value_binding_param_index_missing",
                    "request_name": name,
                    "hash": str(raw_hash),
                    "binding": configured,
                }
            param_index = configured_index
            binding_source_kind = "character_config_dynamic_value_read_info"
        elif spec.get("dynamic_value_binding_mode") == "configured_by_hash_required":
            return {}, {
                "admission_status": "blocked",
                "blocked_reason": "startup_dynamic_value_binding_hash_missing",
                "request_name": name,
                "hash": str(raw_hash),
            }
        elif len(params) != len(request_items):
            return {}, {
                "admission_status": "blocked",
                "blocked_reason": "startup_param_binding_missing",
                "param_count": len(params),
                "request_count": len(request_items),
                "request_names": [item_name for item_name, _ in request_items],
                "hash": str(raw_hash),
            }
        if param_index < 0 or param_index >= len(params):
            return {}, {
                "admission_status": "blocked",
                "blocked_reason": "startup_dynamic_value_binding_param_index_out_of_range",
                "request_name": name,
                "hash": str(raw_hash),
                "param_index": param_index,
                "param_count": len(params),
            }
        value = float(params[param_index])
        dynamic_values[name] = value
        dynamic_values[str(raw_hash)] = value
        bindings.append(
            {
                "name": name,
                "hash": str(raw_hash),
                "param_index": param_index,
                "value": value,
                "binding_source_kind": binding_source_kind,
                "binding_source": configured if isinstance(configured, dict) else {},
            }
        )
    return dynamic_values, {
        "admission_status": "executable",
        "source_kind": f"{str(spec.get('kind') or 'startup_ability')}_param_to_dynamic_value_request",
        "bindings": bindings,
        "slot_id": str(spec.get("slot_id") or ""),
        "trace_node_id": str(spec.get("trace_node_id") or ""),
        "eidolon_slot_id": str(getattr(spec.get("slot"), "eidolon_slot_id", "")),
        "rank_id": str(getattr(spec.get("slot"), "rank_id", "")),
    }


def _eidolon_configured_dynamic_values(
    params: tuple[float, ...],
    configured_by_hash: dict[str, object],
    spec: dict[str, Any],
) -> tuple[dict[str, float], dict[str, object]]:
    dynamic_values: dict[str, float] = {}
    bindings: list[dict[str, object]] = []
    for hash_key, configured in configured_by_hash.items():
        if not isinstance(configured, dict):
            continue
        param_index = configured.get("param_index")
        if not isinstance(param_index, int):
            return {}, {
                "admission_status": "blocked",
                "blocked_reason": "eidolon_configured_dynamic_value_param_index_missing",
                "hash": str(hash_key),
                "binding": configured,
            }
        if param_index < 0 or param_index >= len(params):
            return {}, {
                "admission_status": "blocked",
                "blocked_reason": "eidolon_configured_dynamic_value_param_index_out_of_range",
                "hash": str(hash_key),
                "param_index": param_index,
                "param_count": len(params),
            }
        value = float(params[param_index])
        dynamic_values[str(hash_key)] = value
        bindings.append(
            {
                "hash": str(hash_key),
                "param_index": param_index,
                "value": value,
                "binding_source_kind": "character_config_dynamic_value_read_info",
                "binding_source": configured,
            }
        )
    return dynamic_values, {
        "admission_status": "executable",
        "source_kind": "eidolon_rank_param_to_rank_ability_configured_dynamic_values",
        "bindings": bindings,
        "eidolon_slot_id": str(getattr(spec.get("slot"), "eidolon_slot_id", "")),
        "rank_id": str(getattr(spec.get("slot"), "rank_id", "")),
    }


def _startup_trace_payload(
    *,
    kind: str,
    unit_id: str,
    ability_name: str,
    slot_id: str,
    slot_id_field: str,
    trace_node_id: str,
    status: str,
    reason: str = "",
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": kind,
        "unit_id": unit_id,
        "ability_name": ability_name,
        "slot_id": slot_id,
        slot_id_field: slot_id,
        "status": status,
    }
    if trace_node_id:
        payload["trace_node_id"] = trace_node_id
    if reason:
        payload["reason"] = reason
    if extra:
        payload.update(extra)
    return payload


def _startup_blocked_trace(
    kind: str,
    unit_id: str,
    ability_name: str,
    slot_id: str,
    slot_id_field: str,
    trace_node_id: str,
    graph: object,
    task_id: str,
    reason: str,
    *,
    binding_trace: dict[str, object] | None = None,
) -> dict[str, object]:
    return _startup_trace_payload(
        kind=kind,
        unit_id=unit_id,
        ability_name=ability_name,
        slot_id=slot_id,
        slot_id_field=slot_id_field,
        trace_node_id=trace_node_id,
        status="blocked",
        reason=reason,
        extra={
            "standalone_ability_graph_id": str(getattr(graph, "standalone_ability_graph_id", "")),
            "task_id": task_id,
            "dynamic_value_binding": binding_trace or {},
        },
    )


def _eidolon_startup_blocked_trace(
    unit_id: str,
    ability_name: str,
    slot_id: str,
    graph: object,
    task_id: str,
    reason: str,
    *,
    binding_trace: dict[str, object] | None = None,
) -> dict[str, object]:
    return _startup_blocked_trace(
        "eidolon_startup_rank_ability",
        unit_id,
        ability_name,
        slot_id,
        "eidolon_slot_id",
        "",
        graph,
        task_id,
        reason,
        binding_trace=binding_trace,
    )


def _number_items(value: object) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[float] = []
    for item in value:
        if isinstance(item, bool):
            continue
        if isinstance(item, (int, float)):
            result.append(float(item))
    return tuple(result)


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None
