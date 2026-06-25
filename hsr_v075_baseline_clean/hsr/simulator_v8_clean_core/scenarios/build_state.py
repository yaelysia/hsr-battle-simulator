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
        for unit in scenario.units:
            panel = unit.panel
            flags = dict(panel.flags)
            if unit.position is not None:
                flags["position"] = unit.position
            entity = self.rules.require_entity(unit.entity_ref)
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
            max_hp = _panel_or_profile_value(panel, "max_hp", profile_values, required=entity.entity_type in {"monster", "monster_template"})
            hp = panel.hp if _panel_has(panel, "hp") and panel.hp is not None else max_hp
            units[unit.unit_id] = UnitState(
                unit_id=unit.unit_id,
                side=unit.side,
                template_id=unit.entity_ref,
                level=unit.level,
                max_hp=max_hp,
                hp=hp,
                attack=_panel_or_profile_value(panel, "attack", profile_values, required=entity.entity_type in {"monster", "monster_template"}),
                defense=_panel_or_profile_value(panel, "defense", profile_values, required=entity.entity_type in {"monster", "monster_template"}),
                speed=_panel_or_profile_value(panel, "speed", profile_values, required=entity.entity_type in {"monster", "monster_template"}),
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
        state, eidolon_startup_traces = _apply_eidolon_startup_effects(state, self.rules, eidolon_startup_specs)
        source_traces.extend(eidolon_startup_traces)
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
                            "slot": slot,
                            "ability_name": item,
                            "param_values": tuple(_number_items(semantics.get("param_values"))),
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


def _apply_eidolon_startup_effects(
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
        slot_id = str(getattr(slot, "eidolon_slot_id", ""))
        graphs = tuple(
            graph
            for graph in rules.standalone_ability_graphs_by_name(ability_name)
            if graph.coverage_status == "executable"
        )
        if len(graphs) != 1:
            traces.append(
                {
                    "kind": "eidolon_startup_rank_ability",
                    "unit_id": unit_id,
                    "ability_name": ability_name,
                    "eidolon_slot_id": slot_id,
                    "status": "blocked",
                    "reason": "rank_ability_graph_missing_or_ambiguous",
                    "graph_count": len(graphs),
                }
            )
            continue
        graph = graphs[0]
        applied_count = 0
        for phase_id in graph.phase_ids:
            for task in rules.ability_tasks_for_phase(phase_id):
                if task.callback_kind != "OnStart" or task.parent_task_id or task.opcode != "AddModifier" or not task.effect_id:
                    continue
                effect = rules.effect(task.effect_id)
                if effect is None:
                    traces.append(_eidolon_startup_blocked_trace(unit_id, ability_name, slot_id, graph, task.task_id, "startup_effect_missing"))
                    continue
                coverage = effect_registry.coverage(effect)
                if coverage != "executable":
                    traces.append(
                        _eidolon_startup_blocked_trace(
                            unit_id,
                            ability_name,
                            slot_id,
                            graph,
                            task.task_id,
                            f"startup_effect_not_executable:{coverage}",
                        )
                    )
                    continue
                dynamic_values, binding_trace = _eidolon_startup_dynamic_values(effect.payload.get("standard"), spec)
                if binding_trace.get("admission_status") == "blocked":
                    traces.append(
                        _eidolon_startup_blocked_trace(
                            unit_id,
                            ability_name,
                            slot_id,
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
                    source_id=f"eidolon_startup:{slot_id}:{ability_name}:{task.task_id}",
                    owner_id=unit_id,
                    param_entity_id=unit_id,
                    current_action_target_id=unit_id,
                    dynamic_values=dynamic_values,
                    binding_sources=(),
                )
                current = reducer.apply_all(current, result.mutations)
                applied_count += len(result.mutations)
                traces.append(
                    {
                        "kind": "eidolon_startup_rank_ability",
                        "unit_id": unit_id,
                        "ability_name": ability_name,
                        "eidolon_slot_id": slot_id,
                        "standalone_ability_graph_id": graph.standalone_ability_graph_id,
                        "task_id": task.task_id,
                        "effect_id": effect.effect_id,
                        "status": "applied" if result.ok else "blocked",
                        "mutation_count": len(result.mutations),
                        "unsupported": list(result.unsupported),
                        "dynamic_value_binding": binding_trace,
                        "source": getattr(slot, "source", None).to_json() if getattr(slot, "source", None) else {},
                    }
                )
        if applied_count == 0:
            traces.append(
                {
                    "kind": "eidolon_startup_rank_ability",
                    "unit_id": unit_id,
                    "ability_name": ability_name,
                    "eidolon_slot_id": slot_id,
                    "standalone_ability_graph_id": graph.standalone_ability_graph_id,
                    "status": "blocked",
                    "reason": "rank_ability_has_no_admitted_on_start_add_modifier",
                }
            )
    return current, tuple(traces)


def _eidolon_startup_dynamic_values(
    standard: object,
    spec: dict[str, Any],
) -> tuple[dict[str, float], dict[str, object]]:
    if not isinstance(standard, dict):
        return {}, {"admission_status": "not_applicable", "reason": "standard_payload_missing"}
    requests = standard.get("dynamic_value_requests")
    if not isinstance(requests, dict) or not requests:
        return {}, {"admission_status": "not_applicable", "reason": "no_dynamic_value_requests"}
    params = tuple(_number_items(spec.get("param_values")))
    request_items = [(str(name), request) for name, request in requests.items() if isinstance(request, dict)]
    if len(params) != len(request_items):
        return {}, {
            "admission_status": "blocked",
            "blocked_reason": "eidolon_rank_param_count_does_not_match_dynamic_value_requests",
            "param_count": len(params),
            "request_count": len(request_items),
            "request_names": [name for name, _ in request_items],
        }
    dynamic_values: dict[str, float] = {}
    bindings: list[dict[str, object]] = []
    for index, (name, request) in enumerate(request_items):
        raw_hash = request.get("hash")
        if raw_hash is None:
            return {}, {
                "admission_status": "blocked",
                "blocked_reason": "eidolon_dynamic_value_request_hash_missing",
                "request_name": name,
            }
        value = float(params[index])
        dynamic_values[name] = value
        dynamic_values[str(raw_hash)] = value
        bindings.append({"name": name, "hash": str(raw_hash), "param_index": index, "value": value})
    return dynamic_values, {
        "admission_status": "executable",
        "source_kind": "eidolon_rank_param_to_rank_ability_dynamic_value_request",
        "bindings": bindings,
        "eidolon_slot_id": str(getattr(spec.get("slot"), "eidolon_slot_id", "")),
        "rank_id": str(getattr(spec.get("slot"), "rank_id", "")),
    }


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
    return {
        "kind": "eidolon_startup_rank_ability",
        "unit_id": unit_id,
        "ability_name": ability_name,
        "eidolon_slot_id": slot_id,
        "standalone_ability_graph_id": str(getattr(graph, "standalone_ability_graph_id", "")),
        "task_id": task_id,
        "status": "blocked",
        "reason": reason,
        "dynamic_value_binding": binding_trace or {},
    }


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
