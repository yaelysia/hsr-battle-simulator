from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Any

from .identity import IdentityResolver
from .schema import InitialStatusSpec, InitialSummonSpec, PanelInput, RNGSetupSpec, ScenarioSpec, UnitSpec
from ..builds.character_assembler import assemble_character_build, validate_character_build_admission
from ..builds.models import CharacterBuildAssemblyResult
from ..core.model import ActionCommand, BattleState, GameEvent, JSONValue, Mutation, RNGEvent, UnitState
from ..core.reducer import MutationReducer
from ..equipment.models import DynamicMechanismSelection
from ..rules.ir import CombatantProfileIR, WaveDefinitionIR, WaveMonsterEntryIR
from ..rules.rulebook import RuleBook
from ..rules.value_binding import ValueBindingRequest, ValueContext, ValueResolver
from ..systems.effect import EffectRegistry
from ..systems.ability_provider import register_dynamic_ability_providers
from ..systems.status import StatusSystem
from ..systems.summon import SummonSystem
from ..systems.unit_lifecycle import UnitLifecycleSystem
from ..systems.unit_spawn import UnitSpawnRequest, UnitSpawnSystem


@dataclass(frozen=True)
class ScenarioBuildResult:
    state: BattleState
    commands: tuple[ActionCommand, ...]
    source_traces: tuple[dict[str, object], ...]
    setup_records: tuple[dict[str, JSONValue], ...] = ()
    setup_mutations: tuple[Mutation, ...] = ()
    setup_events: tuple[GameEvent, ...] = ()
    setup_rng_events: tuple[RNGEvent, ...] = ()
    blocked_setup: tuple[dict[str, JSONValue], ...] = ()
    character_build_results: tuple[CharacterBuildAssemblyResult, ...] = ()


@dataclass(frozen=True)
class _SetupApplyResult:
    state: BattleState
    records: tuple[dict[str, JSONValue], ...] = ()
    mutations: tuple[Mutation, ...] = ()
    events: tuple[GameEvent, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    blocked: tuple[dict[str, JSONValue], ...] = ()
    source_traces: tuple[dict[str, JSONValue], ...] = ()


class ScenarioStateBuilder:
    def __init__(self, rules: RuleBook):
        self.rules = rules
        self.identity = IdentityResolver(rules)
        self.value_resolver = ValueResolver(rules)

    def build(self, scenario: ScenarioSpec) -> ScenarioBuildResult:
        scenario = _with_initial_wave_units(self.rules, scenario)
        validation = self.identity.validate(scenario)
        if not validation.ok:
            raise ValueError("; ".join(validation.errors))

        units = {}
        source_traces = list(validation.source_traces)
        setup_records: list[dict[str, JSONValue]] = []
        eidolon_startup_specs: list[dict[str, Any]] = []
        trace_startup_specs: list[dict[str, Any]] = []
        passive_startup_specs: list[dict[str, Any]] = []
        equipment_provider_specs: list[tuple[str, DynamicMechanismSelection]] = []
        character_build_results: list[CharacterBuildAssemblyResult] = []
        for unit in scenario.units:
            panel = unit.panel
            if unit.build_mode == "assembled_character_build":
                if unit.character_build is None or unit.initial_condition is None or panel is not None:
                    raise ValueError(
                        f"unit {unit.unit_id}: incomplete formal character build boundary"
                    )
                assembly = assemble_character_build(self.rules, unit.character_build)
                admission_errors = validate_character_build_admission(
                    self.rules,
                    unit.character_build,
                    assembly,
                )
                if admission_errors:
                    reasons = (*assembly.blocked_reasons, *admission_errors)
                    raise ValueError(f"unit {unit.unit_id}: {'; '.join(sorted(set(reasons)))}")
                if assembly.base_panel is None:
                    raise ValueError(f"unit {unit.unit_id}: admitted build has no base panel")
                character_build_results.append(assembly)
                (
                    formal_flags,
                    formal_startup_specs,
                    formal_equipment_providers,
                ) = _formal_character_activation(
                    self.rules,
                    unit,
                    assembly,
                )
                if unit.position is not None:
                    formal_flags["position"] = unit.position
                for startup_spec in formal_startup_specs:
                    trace_startup_specs.append({"unit_id": unit.unit_id, **startup_spec})
                equipment_provider_specs.extend(
                    (unit.unit_id, selection)
                    for selection in formal_equipment_providers
                )
                base_panel = assembly.base_panel
                resources = {
                    "critical_chance": float(base_panel.critical_chance),
                    "critical_damage": float(base_panel.critical_damage),
                    "base_aggro": float(base_panel.base_aggro),
                    **{
                        item.property_type: float(item.exact_value)
                        for item in base_panel.additional_resources
                    },
                }
                max_hp = float(base_panel.max_hp)
                max_energy = float(base_panel.max_energy)
                units[unit.unit_id] = UnitState(
                    unit_id=unit.unit_id,
                    side=unit.side,
                    template_id=unit.entity_ref,
                    level=unit.level,
                    max_hp=max_hp,
                    hp=max_hp,
                    attack=float(base_panel.attack),
                    defense=float(base_panel.defense),
                    speed=float(base_panel.speed),
                    energy=float(unit.initial_condition.initial_energy),
                    max_energy=max_energy,
                    toughness=0.0,
                    max_toughness=0.0,
                    action_value=0.0,
                    statuses=(),
                    flags=formal_flags,
                    resources=resources,
                )
                source_traces.extend(
                    contribution.source.to_json() for contribution in assembly.contribution_ledger
                )
                source_traces.extend(
                    source.source.to_json()
                    for level in assembly.effective_skill_levels
                    for source in level.sources
                )
                source_traces.extend(
                    level.action_record_source.to_json()
                    for level in assembly.effective_skill_levels
                )
                source_traces.extend(
                    level.action_definition_source.to_json()
                    for level in assembly.effective_skill_levels
                )
                source_traces.extend(
                    mechanism.source.to_json()
                    for mechanism in assembly.admitted_dynamic_mechanism_refs
                )
                equipment_result = assembly.equipment_assembly_result
                if equipment_result is None:
                    raise ValueError(
                        f"unit {unit.unit_id}: admitted build has no equipment assembly result"
                    )
                if equipment_result.light_cone_selection is not None:
                    selection = equipment_result.light_cone_selection
                    source_traces.extend(
                        source.to_json()
                        for source in (
                            selection.promotion_source,
                            selection.superimposition_source,
                            selection.ability_source,
                        )
                    )
                source_traces.extend(
                    source.to_json()
                    for decision in equipment_result.activation_decisions
                    for source in (
                        decision.basis.character_path_source,
                        decision.basis.light_cone_path_source,
                    )
                )
                source_traces.extend(
                    source.to_json()
                    for mechanism in equipment_result.dynamic_mechanisms
                    for source in (
                        mechanism.source,
                        *(
                            binding_source
                            for binding in mechanism.parameter_bindings
                            for binding_source in (
                                binding.read_source,
                                binding.value_source,
                            )
                        ),
                    )
                )
                setup_records.append(
                    {
                        "record_type": "character_build_assembly",
                        "source_kind": "canonical_ir_character_build",
                        "status": "admitted",
                        "unit_id": unit.unit_id,
                        "input_fingerprint": assembly.input_fingerprint,
                        "result_fingerprint": assembly.result_fingerprint,
                        "equipment_build_fingerprint": equipment_result.build_fingerprint,
                        "equipment_result_fingerprint": equipment_result.result_fingerprint,
                        "equipment_battle_admission_status": (
                            equipment_result.battle_admission_status
                        ),
                        "light_cone_activation_status": (
                            equipment_result.activation_decisions[0].activation_status
                            if equipment_result.activation_decisions
                            else None
                        ),
                        "effective_skill_level_count": len(assembly.effective_skill_levels),
                        "legacy_trace_eidolon_paths_bypassed": True,
                    }
                )
                continue
            if panel is None:
                raise ValueError(f"unit {unit.unit_id}: kernel_fixture requires panel input")
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
                    runtime_activation = _eidolon_runtime_activation(self.value_resolver, eidolon_slots)
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
            trace_activation = _trace_runtime_activation(self.rules, self.value_resolver, card, flags)
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
            hp = _panel_hp(unit.unit_id, panel, max_hp)
            max_energy = panel.max_energy
            energy = _panel_energy(unit.unit_id, panel, max_energy)
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
                energy=energy,
                max_energy=max_energy,
                toughness=_panel_or_profile_value(panel, "toughness", profile_values, required=entity.entity_type in {"monster", "monster_template"}),
                max_toughness=_panel_or_profile_value(panel, "max_toughness", profile_values, required=entity.entity_type in {"monster", "monster_template"}),
                action_value=panel.action_value,
                statuses=panel.statuses,
                flags=flags,
                resources=resources,
            )

        global_flags = dict(scenario.global_flags)
        wave_runtime = _initial_wave_runtime(self.rules, scenario)
        if wave_runtime:
            global_flags["wave_runtime"] = wave_runtime
            source_traces.append(dict(wave_runtime.get("source_trace", {})))
            setup_records.append(
                {
                    "record_type": "setup_wave",
                    "source_kind": "scenario_initial_condition",
                    "status": str(wave_runtime.get("status") or ""),
                    "wave_definition_id": str(wave_runtime.get("wave_definition_id") or ""),
                    "current_wave_index": int(wave_runtime.get("current_wave_index") or 0),
                    "blocked_reason": str(wave_runtime.get("blocked_reason") or ""),
                    "source_trace": dict(wave_runtime.get("source_trace") or {}),
                }
            )
        if scenario.route:
            global_flags.setdefault("turn_owner_id", scenario.route[0].actor_id)
        _apply_pre_state_setup_flags(global_flags, scenario, setup_records)
        global_flags.setdefault("phase", "scenario")
        global_flags.setdefault("current_window", "idle")
        state = BattleState(
            units=units,
            wave_index=_scenario_wave_index(scenario),
            skill_points=_scenario_skill_points(scenario),
            max_skill_points=_scenario_max_skill_points(scenario),
            global_flags=global_flags,
            rng_state=_scenario_rng_state(scenario),
        )
        provider_result = register_dynamic_ability_providers(
            state,
            self.rules,
            tuple(equipment_provider_specs),
        )
        if not provider_result.ok:
            raise ValueError(
                "equipment ability provider startup blocked: "
                f"{provider_result.blocked_reason}"
            )
        state = provider_result.after_state
        setup_records.extend(provider_result.records)
        state, startup_traces = _apply_startup_ability_effects(
            state,
            self.rules,
            [*eidolon_startup_specs, *trace_startup_specs, *passive_startup_specs],
        )
        source_traces.extend(startup_traces)
        setup_result = _apply_battle_setup(self.rules, state, scenario)
        state = setup_result.state
        setup_records.extend(setup_result.records)
        source_traces.extend(setup_result.source_traces)
        route_unit_errors = _validate_route_units_after_setup(scenario, state)
        if route_unit_errors:
            raise ValueError("; ".join(route_unit_errors))
        commands = tuple(
            ActionCommand(
                actor_id=step.actor_id,
                action_id=step.action_ref,
                action_level=step.action_level,
                target_ids=step.target_ids,
                source=step.source,
                queue_name=step.queue_name,
                metadata=_command_metadata(scenario, step.metadata),
            )
            for step in scenario.route
        )
        return ScenarioBuildResult(
            state=state,
            commands=commands,
            source_traces=tuple(source_traces),
            setup_records=tuple(setup_records),
            setup_mutations=(*provider_result.mutations, *setup_result.mutations),
            setup_events=setup_result.events,
            setup_rng_events=setup_result.rng_events,
            blocked_setup=setup_result.blocked,
            character_build_results=tuple(character_build_results),
        )


def _validate_route_units_after_setup(scenario: ScenarioSpec, state: BattleState) -> tuple[str, ...]:
    unit_ids = set(state.units)
    errors: list[str] = []
    for index, step in enumerate(scenario.route):
        if step.actor_id not in unit_ids:
            errors.append(f"route[{index}]: unknown actor_id {step.actor_id!r}")
        for target_id in step.target_ids:
            if target_id not in unit_ids:
                errors.append(f"route[{index}]: unknown target_id {target_id!r}")
    return tuple(errors)


def _scenario_skill_points(scenario: ScenarioSpec) -> int:
    value = scenario.battle_setup.resources.skill_points
    return int(value) if value is not None else int(scenario.skill_points)


def _scenario_max_skill_points(scenario: ScenarioSpec) -> int:
    value = scenario.battle_setup.resources.max_skill_points
    return int(value) if value is not None else int(scenario.max_skill_points)


def _scenario_wave_index(scenario: ScenarioSpec) -> int:
    if scenario.battle_setup.wave is not None:
        return int(scenario.battle_setup.wave.wave_index)
    return int(scenario.wave_index)


def _scenario_rng_setup(scenario: ScenarioSpec) -> RNGSetupSpec:
    rng = scenario.battle_setup.rng
    if rng is None:
        return RNGSetupSpec(rng_state=scenario.rng_state or "deterministic")
    if rng.rng_state is None:
        return replace(rng, rng_state=scenario.rng_state or "deterministic")
    return rng


def _scenario_rng_state(scenario: ScenarioSpec) -> str:
    return str(_scenario_rng_setup(scenario).rng_state or "deterministic")


def _panel_hp(unit_id: str, panel: PanelInput, max_hp: float) -> float:
    if panel.hp is not None and panel.hp_ratio is not None:
        raise ValueError(f"unit {unit_id}: hp and hp_ratio cannot both be set")
    if panel.hp_ratio is not None:
        if panel.hp_ratio < 0.0 or panel.hp_ratio > 1.0:
            raise ValueError(f"unit {unit_id}: hp_ratio must be between 0 and 1")
        return float(max_hp) * float(panel.hp_ratio)
    if _panel_has(panel, "hp") and panel.hp is not None:
        return float(panel.hp)
    return float(max_hp)


def _panel_energy(unit_id: str, panel: PanelInput, max_energy: float) -> float:
    if panel.energy_ratio is not None and _panel_has(panel, "energy"):
        raise ValueError(f"unit {unit_id}: energy and energy_ratio cannot both be set")
    if panel.energy_ratio is not None:
        if panel.energy_ratio < 0.0 or panel.energy_ratio > 1.0:
            raise ValueError(f"unit {unit_id}: energy_ratio must be between 0 and 1")
        if max_energy <= 0.0:
            raise ValueError(f"unit {unit_id}: energy_ratio requires max_energy > 0")
        return float(max_energy) * float(panel.energy_ratio)
    return float(panel.energy)


def _apply_pre_state_setup_flags(
    global_flags: dict[str, JSONValue],
    scenario: ScenarioSpec,
    setup_records: list[dict[str, JSONValue]],
) -> None:
    setup = scenario.battle_setup
    setup_records.append(
        {
            "record_type": "setup_resources",
            "source_kind": "scenario_initial_condition",
            "status": "applied",
            "skill_points": _scenario_skill_points(scenario),
            "max_skill_points": _scenario_max_skill_points(scenario),
        }
    )
    setup_rng = _scenario_rng_setup(scenario)
    if setup.rng is not None and _rng_setup_is_explicit(setup_rng):
        global_flags["scenario_rng_setup"] = _rng_setup_to_json(setup_rng)
        setup_records.append(
            {
                "record_type": "setup_rng",
                "source_kind": "scenario_route_input",
                "status": "applied",
                "rng_state": setup_rng.rng_state or "deterministic",
                "rng_mode": setup_rng.rng_mode or "",
                "rng_choice_keys": sorted(setup_rng.rng_choices),
            }
        )
    if setup.objective is not None:
        global_flags["objective"] = _objective_to_json(setup.objective)
        setup_records.append(
            {
                "record_type": "setup_objective",
                "source_kind": "scenario_search_metadata",
                "status": "recorded",
                "objective_id": setup.objective.objective_id,
                "kind": setup.objective.kind,
                "affects_rules": False,
            }
        )

def _apply_battle_setup(rules: RuleBook, state: BattleState, scenario: ScenarioSpec) -> _SetupApplyResult:
    status = _apply_initial_statuses(rules, state, scenario)
    current = status.state
    summon = _apply_initial_summons(rules, current, scenario)
    current = summon.state
    timeline = _apply_timeline_setup(current, scenario)
    return _SetupApplyResult(
        state=timeline.state,
        records=(*status.records, *summon.records, *timeline.records),
        mutations=(*status.mutations, *summon.mutations, *timeline.mutations),
        events=(*status.events, *summon.events, *timeline.events),
        rng_events=(*status.rng_events, *summon.rng_events, *timeline.rng_events),
        blocked=(*status.blocked, *summon.blocked, *timeline.blocked),
        source_traces=(*status.source_traces, *summon.source_traces, *timeline.source_traces),
    )


def _rng_setup_is_explicit(rng: RNGSetupSpec) -> bool:
    return bool(rng.rng_mode or rng.rng_choices or (rng.rng_state is not None and rng.rng_state != "deterministic"))


def _apply_timeline_setup(state: BattleState, scenario: ScenarioSpec) -> _SetupApplyResult:
    timeline = scenario.battle_setup.timeline
    if timeline is None:
        return _SetupApplyResult(state=state)
    records: list[dict[str, JSONValue]] = [
        {
            "record_type": "setup_timeline",
            "source_kind": "scenario_initial_condition",
            "status": "applied",
            "mode": timeline.mode,
            "global_av": timeline.global_av,
            "turn_owner_id": timeline.turn_owner_id or "",
        }
    ]
    blocked = _timeline_setup_blocked(state, timeline)
    if blocked is not None:
        return _SetupApplyResult(state=state, records=(*records, blocked), blocked=(blocked,))
    mutations: list[Mutation] = []
    policy = {
        "mode": timeline.mode,
        "source_kind": "scenario_initial_condition",
        "explicit_action_value_unit_ids": sorted(timeline.action_values),
        "explicit_overrides": list(timeline.explicit_overrides),
    }
    mutations.append(
        Mutation(
            op="set",
            path=("global_flags", "global_av"),
            before=state.global_flags.get("global_av"),
            after=float(timeline.global_av),
            reason="scenario timeline global action value",
            source="scenario_setup",
            before_exists="global_av" in state.global_flags,
            metadata={"setup_operation": "timeline_global_av", "source_kind": "scenario_initial_condition"},
        )
    )
    mutations.append(
        Mutation(
            op="set",
            path=("global_flags", "timeline_setup_policy"),
            before=state.global_flags.get("timeline_setup_policy"),
            after=policy,
            reason="scenario timeline setup policy",
            source="scenario_setup",
            before_exists="timeline_setup_policy" in state.global_flags,
            metadata={"setup_operation": "timeline_policy", "source_kind": "scenario_initial_condition"},
        )
    )
    if timeline.turn_owner_id is not None:
        mutations.append(
            Mutation(
                op="set",
                path=("global_flags", "turn_owner_id"),
                before=state.global_flags.get("turn_owner_id"),
                after=timeline.turn_owner_id,
                reason="scenario timeline turn owner",
                source="scenario_setup",
                before_exists="turn_owner_id" in state.global_flags,
                metadata={"setup_operation": "timeline_turn_owner", "source_kind": "scenario_initial_condition"},
            )
        )
    if timeline.mode == "runtime_initialize":
        after = MutationReducer().apply_all(state, tuple(mutations))
        return _SetupApplyResult(state=after, records=tuple(records), mutations=tuple(mutations))
    for unit_id, action_value in sorted(timeline.action_values.items()):
        unit = state.units[unit_id]
        mutation = Mutation(
            op="set",
            path=("units", unit_id, "action_value"),
            before=unit.action_value,
            after=float(action_value),
            reason="scenario explicit action value",
            source="scenario_setup",
            metadata={
                "setup_operation": "explicit_action_value",
                "source_kind": "scenario_initial_condition",
                "unit_id": unit_id,
            },
        )
        mutations.append(mutation)
        records.append(
            {
                "record_type": "setup_timeline_action_value",
                "source_kind": "scenario_initial_condition",
                "status": "applied",
                "unit_id": unit_id,
                "before": unit.action_value,
                "after": float(action_value),
                "mutation_id": mutation.stable_id(),
            }
        )
    after = MutationReducer().apply_all(state, tuple(mutations))
    return _SetupApplyResult(state=after, records=tuple(records), mutations=tuple(mutations))


def _timeline_setup_blocked(state: BattleState, timeline: object) -> dict[str, JSONValue] | None:
    turn_owner_id = getattr(timeline, "turn_owner_id", None)
    lifecycle = UnitLifecycleSystem()
    if turn_owner_id is not None:
        view = lifecycle.view(state, str(turn_owner_id))
        if not view.is_active:
            return _setup_blocked_record(
                "setup_timeline",
                view.blocked_reason or "timeline_turn_owner_not_active",
                {"turn_owner_id": str(turn_owner_id), "owner_lifecycle": view.to_json()},
            )
    action_values = getattr(timeline, "action_values", {})
    if isinstance(action_values, dict):
        for unit_id in action_values:
            if unit_id not in state.units:
                return _setup_blocked_record(
                    "setup_timeline",
                    "timeline_action_value_unit_missing",
                    {"unit_id": str(unit_id)},
                )
    return None


def _apply_initial_statuses(rules: RuleBook, state: BattleState, scenario: ScenarioSpec) -> _SetupApplyResult:
    if not scenario.battle_setup.initial_statuses:
        return _SetupApplyResult(state=state)
    reducer = MutationReducer()
    system = StatusSystem(rules)
    registry = EffectRegistry(system)
    current = state
    records: list[dict[str, JSONValue]] = []
    mutations: list[Mutation] = []
    events: list[GameEvent] = []
    rng_events: list[RNGEvent] = []
    blocked: list[dict[str, JSONValue]] = []
    traces: list[dict[str, JSONValue]] = []
    for index, spec in enumerate(scenario.battle_setup.initial_statuses):
        effect = rules.effect(spec.effect_ref or "")
        if effect is None:
            raise ValueError(f"battle_setup.initial_statuses[{index}]: unknown effect_ref {spec.effect_ref!r}")
        if effect.opcode != "AddModifier":
            raise ValueError(
                f"battle_setup.initial_statuses[{index}]: effect_ref {spec.effect_ref!r} opcode is "
                f"{effect.opcode!r}, expected 'AddModifier'"
            )
        traces.append(effect.source.to_json())
        coverage = registry.coverage(effect)
        if coverage != "executable":
            record = _setup_blocked_record(
                "setup_initial_status",
                f"effect_not_executable:{coverage}",
                {
                    "effect_ref": effect.effect_id,
                    "effect_opcode": effect.opcode,
                    "effect_coverage_status": effect.coverage_status,
                    "source_trace": effect.source.to_json(),
                },
            )
            records.append(record)
            blocked.append(record)
            continue
        result = system.apply_add_modifier(
            current,
            effect,
            caster_id=spec.caster_id or spec.source_id,
            source_id=spec.source_id,
            owner_id=spec.owner_id or spec.target_id,
            param_entity_id=spec.param_entity_id or spec.source_id,
            current_action_target_id=spec.current_action_target_id or spec.target_id,
            event_payload=_status_event_payload(scenario, spec),
            dynamic_values=spec.dynamic_values,
            binding_sources=(_status_setup_binding_source(spec, effect.effect_id),),
        )
        current = reducer.apply_all(current, result.mutations)
        mutations.extend(result.mutations)
        events.extend(result.events)
        rng_events.extend(result.rng_events)
        records.extend(result.records)
        setup_record = {
            "record_type": "setup_initial_status",
            "source_kind": "scenario_initial_condition",
            "status": "applied" if result.mutations else ("process_only" if result.records else "blocked"),
            "ok": result.ok,
            "target_id": spec.target_id,
            "source_id": spec.source_id,
            "effect_ref": effect.effect_id,
            "mutation_count": len(result.mutations),
            "rng_event_count": len(result.rng_events),
            "unsupported": list(result.unsupported),
            "status_instance": result.status_instance.to_json() if result.status_instance else None,
            "source_trace": effect.source.to_json(),
        }
        records.append(setup_record)
        if result.unsupported:
            blocked.append({**setup_record, "blocked_reason": ";".join(result.unsupported)})
    return _SetupApplyResult(
        state=current,
        records=tuple(records),
        mutations=tuple(mutations),
        events=tuple(events),
        rng_events=tuple(rng_events),
        blocked=tuple(blocked),
        source_traces=tuple(traces),
    )


def _apply_initial_summons(rules: RuleBook, state: BattleState, scenario: ScenarioSpec) -> _SetupApplyResult:
    if not scenario.battle_setup.initial_summons:
        return _SetupApplyResult(state=state)
    reducer = MutationReducer()
    lifecycle = UnitLifecycleSystem()
    system = SummonSystem(rules)
    current = state
    records: list[dict[str, JSONValue]] = []
    mutations: list[Mutation] = []
    events: list[GameEvent] = []
    blocked: list[dict[str, JSONValue]] = []
    traces: list[dict[str, JSONValue]] = []
    for index, spec in enumerate(scenario.battle_setup.initial_summons):
        owner_view = lifecycle.view(current, spec.owner_id)
        if not owner_view.is_active:
            record = _setup_blocked_record(
                "setup_initial_summon",
                owner_view.blocked_reason or "summon_owner_inactive",
                {"owner_id": spec.owner_id, "owner_lifecycle": owner_view.to_json(), "kind": spec.kind},
            )
            records.append(record)
            blocked.append(record)
            continue
        if spec.kind == "summoned_monster":
            result = _apply_initial_summoned_monster(rules, current, system, spec, index)
        elif spec.kind == "battle_unit_summon":
            result = _blocked_initial_battle_unit_summon(rules, current, spec)
        else:
            result = _apply_initial_servant(rules, current, system, spec, index)
        current = reducer.apply_all(current, result.mutations)
        mutations.extend(result.mutations)
        events.extend(result.events)
        records.extend(result.records)
        blocked.extend(result.blocked)
        traces.extend(result.source_traces)
    return _SetupApplyResult(
        state=current,
        records=tuple(records),
        mutations=tuple(mutations),
        events=tuple(events),
        blocked=tuple(blocked),
        source_traces=tuple(traces),
    )


def _apply_initial_summoned_monster(
    rules: RuleBook,
    state: BattleState,
    system: SummonSystem,
    spec: InitialSummonSpec,
    index: int,
) -> _SetupApplyResult:
    intent = rules.summon_monster_intent(spec.summon_intent_ref or "")
    if intent is None:
        raise ValueError(f"battle_setup.initial_summons[{index}]: unknown summon_intent_ref {spec.summon_intent_ref!r}")
    plan = system.plan_spawn_summoned_monster(state, intent, owner_id=spec.owner_id)
    result = system.apply_spawn(state, plan)
    override_reason = _summon_override_blocked_reason(spec, result.mutations)
    if override_reason:
        blocked_result = system.blocked(override_reason, owner_id=spec.owner_id, source_trace=intent.source.to_json())
        result = blocked_result
    records = list(result.records)
    setup_record = {
        "record_type": "setup_initial_summon",
        "source_kind": "scenario_initial_condition",
        "status": "applied" if result.mutations else "blocked",
        "ok": result.plan.ok,
        "kind": spec.kind,
        "owner_id": spec.owner_id,
        "summon_intent_ref": intent.summon_intent_id,
        "unit_ids": list(result.plan.unit_ids),
        "mutation_count": len(result.mutations),
        "blocked_reason": result.plan.blocked_reason,
        "source_trace": intent.source.to_json(),
    }
    records.append(setup_record)
    blocked = (setup_record,) if not result.plan.ok else ()
    return _SetupApplyResult(
        state=state,
        records=tuple(records),
        mutations=result.mutations,
        events=result.events,
        blocked=blocked,
        source_traces=(intent.source.to_json(),),
    )


def _blocked_initial_battle_unit_summon(
    rules: RuleBook,
    state: BattleState,
    spec: InitialSummonSpec,
) -> _SetupApplyResult:
    source_trace: dict[str, JSONValue] = {}
    if spec.summon_intent_ref:
        definition = rules.summon_unit_definition(spec.summon_intent_ref)
        if definition is not None:
            source_trace = definition.source.to_json()
    record = _setup_blocked_record(
        "setup_initial_summon",
        "battle_unit_summon_initial_setup_boundary_only",
        {
            "kind": spec.kind,
            "owner_id": spec.owner_id,
            "summon_intent_ref": spec.summon_intent_ref or "",
            "entity_ref": spec.entity_ref or "",
            "source_trace": source_trace,
        },
    )
    return _SetupApplyResult(state=state, records=(record,), blocked=(record,), source_traces=(source_trace,) if source_trace else ())


def _apply_initial_servant(
    rules: RuleBook,
    state: BattleState,
    system: SummonSystem,
    spec: InitialSummonSpec,
    index: int,
) -> _SetupApplyResult:
    servant_ref = spec.summon_intent_ref or spec.entity_ref or ""
    definition = rules.servant_definition(servant_ref)
    if definition is None:
        raise ValueError(f"battle_setup.initial_summons[{index}]: unknown servant definition/ref {servant_ref!r}")
    plan = system.plan_spawn_servant(state, definition, owner_id=spec.owner_id)
    result = system.apply_spawn_servant(state, plan)
    override_reason = _servant_override_blocked_reason(spec, definition.servant_ref, definition.servant_definition_id, result.mutations)
    if override_reason:
        result = system.blocked(override_reason, owner_id=spec.owner_id, source_trace=definition.source.to_json())
    records = list(result.records)
    setup_record = {
        "record_type": "setup_initial_summon",
        "source_kind": "scenario_initial_condition",
        "status": "applied" if result.mutations else "blocked",
        "ok": result.plan.ok,
        "kind": spec.kind,
        "owner_id": spec.owner_id,
        "servant_ref": definition.servant_ref,
        "servant_definition_id": definition.servant_definition_id,
        "unit_ids": list(result.plan.unit_ids),
        "mutation_count": len(result.mutations),
        "blocked_reason": result.plan.blocked_reason,
        "source_trace": definition.source.to_json(),
    }
    records.append(setup_record)
    blocked = (setup_record,) if not result.plan.ok else ()
    return _SetupApplyResult(
        state=state,
        records=tuple(records),
        mutations=result.mutations,
        events=result.events,
        blocked=blocked,
        source_traces=(definition.source.to_json(),),
    )


def _summon_override_blocked_reason(spec: InitialSummonSpec, mutations: tuple[Mutation, ...]) -> str:
    spawned = tuple(
        mutation.after
        for mutation in mutations
        if mutation.metadata.get("lifecycle_operation") == "unit_spawn" and isinstance(mutation.after, dict)
    )
    if spec.unit_id and spec.unit_id not in {str(unit.get("unit_id") or "") for unit in spawned}:
        return "summoned_monster_unit_id_override_not_admitted"
    if spec.entity_ref and any(unit.get("template_id") != spec.entity_ref for unit in spawned):
        return "summoned_monster_entity_ref_override_not_admitted"
    if spec.position is not None:
        for unit in spawned:
            flags = unit.get("flags") if isinstance(unit.get("flags"), dict) else {}
            if int(flags.get("position") or -1) != spec.position:
                return "summoned_monster_position_override_not_admitted"
    return ""


def _servant_override_blocked_reason(
    spec: InitialSummonSpec,
    servant_ref: str,
    servant_definition_id: str,
    mutations: tuple[Mutation, ...],
) -> str:
    spawned = tuple(
        mutation.after
        for mutation in mutations
        if mutation.metadata.get("lifecycle_operation") == "unit_spawn" and isinstance(mutation.after, dict)
    )
    if spec.unit_id:
        return "servant_unit_id_override_not_admitted"
    if spec.position is not None:
        return "servant_position_override_not_admitted"
    if (
        spec.entity_ref
        and spec.entity_ref not in {servant_ref, servant_definition_id}
        and any(unit.get("template_id") != spec.entity_ref for unit in spawned)
    ):
        return "servant_entity_ref_override_not_admitted"
    return ""


def _status_event_payload(scenario: ScenarioSpec, spec: InitialStatusSpec) -> dict[str, JSONValue]:
    setup_rng = _scenario_rng_setup(scenario)
    payload: dict[str, JSONValue] = {}
    rng_choices = {**setup_rng.rng_choices, **spec.rng_choices}
    if rng_choices:
        payload["rng_choices"] = rng_choices
    rng_mode = spec.rng_mode or setup_rng.rng_mode
    if rng_mode:
        payload["rng_mode"] = rng_mode
    return payload


def _status_setup_binding_source(spec: InitialStatusSpec, effect_ref: str) -> dict[str, JSONValue]:
    return {
        "source_kind": "scenario_initial_condition",
        "effect_ref": effect_ref,
        "target_id": spec.target_id,
        "source_id": spec.source_id,
        "metadata": spec.metadata,
    }


def _setup_blocked_record(
    record_type: str,
    reason: str,
    payload: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    return {
        "record_type": record_type,
        "source_kind": "scenario_initial_condition",
        "status": "blocked",
        "blocked_reason": reason,
        "process_only": True,
        "produced_mutation": False,
        **payload,
    }


def _command_metadata(scenario: ScenarioSpec, route_metadata: dict[str, JSONValue]) -> dict[str, JSONValue]:
    setup_rng = _scenario_rng_setup(scenario)
    metadata = dict(route_metadata)
    if setup_rng.rng_mode and "rng_mode" not in metadata:
        metadata["rng_mode"] = setup_rng.rng_mode
    if setup_rng.rng_choices:
        route_choices = metadata.get("rng_choices")
        merged = dict(setup_rng.rng_choices)
        if isinstance(route_choices, dict):
            merged.update(route_choices)
        elif route_choices is not None:
            return metadata
        metadata["rng_choices"] = merged
    return metadata


def _rng_setup_to_json(rng: RNGSetupSpec) -> dict[str, JSONValue]:
    return {
        "rng_state": rng.rng_state or "deterministic",
        "rng_mode": rng.rng_mode,
        "rng_choices": dict(rng.rng_choices),
    }


def _objective_to_json(objective: object) -> dict[str, JSONValue]:
    return {
        "objective_id": str(getattr(objective, "objective_id", "")),
        "kind": str(getattr(objective, "kind", "")),
        "payload": dict(getattr(objective, "payload", {}) or {}),
        "source_kind": "scenario_search_metadata",
        "affects_rules": False,
    }


def _with_initial_wave_units(rules: RuleBook, scenario: ScenarioSpec) -> ScenarioSpec:
    definition = _scenario_wave_definition(rules, scenario)
    if definition is None:
        return scenario
    current_wave_index = _scenario_wave_index(scenario)
    existing_ids = {unit.unit_id for unit in scenario.units}
    generated: list[UnitSpec] = []
    for entry in rules.wave_entries_for_wave(definition.wave_definition_id, current_wave_index):
        if entry.coverage_status != "executable":
            continue
        unit_id = _wave_unit_id(definition, entry)
        if unit_id in existing_ids:
            continue
        generated.append(_wave_unit_spec(rules, definition, entry, unit_id))
        existing_ids.add(unit_id)
    if not generated:
        return scenario
    return replace(scenario, units=(*scenario.units, *generated))


def _scenario_wave_definition(rules: RuleBook, scenario: ScenarioSpec) -> WaveDefinitionIR | None:
    wave = scenario.battle_setup.wave
    if wave is not None:
        if wave.kind == "wave_definition" and wave.wave_definition_ref:
            return rules.wave_definition(wave.wave_definition_ref)
        if wave.kind == "stage" and wave.stage_ref:
            return rules.wave_definition_for_stage(wave.stage_ref)
        if wave.kind == "none":
            return None
    if scenario.wave_definition_ref:
        return rules.wave_definition(scenario.wave_definition_ref)
    if scenario.stage_ref:
        return rules.wave_definition_for_stage(scenario.stage_ref)
    return None


def _wave_unit_id(definition: WaveDefinitionIR, entry: WaveMonsterEntryIR) -> str:
    return f"enemy:stage:{definition.stage_id}:wave:{entry.wave_index}:pos:{entry.position}"


def _wave_unit_spec(
    rules: RuleBook,
    definition: WaveDefinitionIR,
    entry: WaveMonsterEntryIR,
    unit_id: str,
) -> UnitSpec:
    template = rules.unit_birth_template(entry.birth_template_id)
    if template is None:
        raise ValueError(f"wave entry {entry.entry_id}: unit birth template missing")
    request = UnitSpawnRequest(
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
    plan = UnitSpawnSystem().plan(template, request)
    if not plan.ok:
        raise ValueError(f"wave entry {entry.entry_id}: {plan.blocked_reason or 'unit birth template blocked'}")
    unit = plan.to_unit(
        expected_request=request,
        expected_template=template,
        owner=None,
    )
    return UnitSpec(
        unit_id=unit_id,
        side="enemy",
        build_mode="kernel_fixture",
        entity_ref=entry.monster_entity_ref,
        level=unit.level,
        position=entry.position,
        panel=PanelInput(
            explicit_fields=(
                "max_hp",
                "hp",
                "attack",
                "defense",
                "speed",
                "energy",
                "max_energy",
                "toughness",
                "max_toughness",
                "action_value",
                "resources",
                "flags",
            ),
            max_hp=unit.max_hp,
            hp=unit.hp,
            attack=unit.attack,
            defense=unit.defense,
            speed=unit.speed,
            energy=unit.energy,
            max_energy=unit.max_energy,
            toughness=unit.toughness,
            max_toughness=unit.max_toughness,
            action_value=unit.action_value,
            resources=unit.resources,
            flags=unit.flags,
        ),
    )


def _initial_wave_runtime(rules: RuleBook, scenario: ScenarioSpec) -> dict[str, JSONValue]:
    definition = _scenario_wave_definition(rules, scenario)
    if definition is None:
        return {}
    current_wave_index = _scenario_wave_index(scenario)
    entries = rules.wave_entries_for_wave(definition.wave_definition_id, current_wave_index)
    executable_entries = tuple(entry for entry in entries if entry.coverage_status == "executable")
    blocked_entries = tuple(entry for entry in entries if entry.coverage_status != "executable")
    current_unit_ids = tuple(_wave_unit_id(definition, entry) for entry in executable_entries)
    blocked_reason = ""
    status = "pending_start"
    if definition.coverage_status != "executable":
        blocked_reason = definition.blocked_reason or f"wave_definition_not_executable:{definition.coverage_status}"
        status = "blocked"
    if not entries:
        blocked_reason = "current_wave_entries_missing"
        status = "blocked"
    if blocked_entries:
        blocked_reason = "current_wave_has_blocked_entries"
        status = "blocked"
    if not current_unit_ids:
        blocked_reason = blocked_reason or "current_wave_executable_units_missing"
        status = "blocked"
    return {
        "schema_version": "p1_2_wave_runtime_v1",
        "wave_definition_id": definition.wave_definition_id,
        "stage_id": definition.stage_id,
        "current_wave_index": current_wave_index,
        "total_waves": definition.wave_count,
        "started_wave_indices": [],
        "cleared_wave_indices": [],
        "current_wave_unit_ids": list(current_unit_ids),
        "spawned_unit_ids_by_wave": {str(current_wave_index): list(current_unit_ids)} if current_unit_ids else {},
        "removed_unit_ids_by_wave": {},
        "status": status,
        "blocked_reason": blocked_reason,
        "blocked_entries": [entry.to_json() for entry in blocked_entries],
        "source_trace": definition.source.to_json(),
    }


def _trace_runtime_activation(
    rules: RuleBook,
    value_resolver: ValueResolver,
    card: object | None,
    flags: dict[str, Any],
) -> dict[str, Any]:
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
                value_resolution = _fixed_numeric_value_resolution(
                    value_resolver,
                    _kernel_fixture_exact_numeric(term.get("value")),
                    data_card_id=card_id,
                    data_card_kind="character",
                    source_trace=slot.source.to_json(),
                )
                value = _resolution_float_or_none(value_resolution)
                if value is None or not key:
                    blocked_slots.append(
                        {
                            "trace_node_id": node.trace_node_id,
                            "mechanism_slot_id": slot_id,
                            "blocked_reason": value_resolution.get("blocked_reason") or "trace_static_stat_term_invalid",
                            "term": term,
                            "value_resolution": value_resolution,
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
                        "value_resolution": value_resolution,
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


def _kernel_fixture_exact_numeric(value: object) -> object:
    if not isinstance(value, str):
        return value
    try:
        number = Decimal(value)
    except InvalidOperation:
        return value
    return float(number) if number.is_finite() else value


def _formal_character_activation(
    rules: RuleBook,
    unit: UnitSpec,
    assembly: CharacterBuildAssemblyResult,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    tuple[DynamicMechanismSelection, ...],
]:
    if unit.character_build is None:
        raise ValueError("formal character activation requires character_build")
    flags: dict[str, Any] = {
        "build_mode": "assembled_character_build",
        "character_data_card_id": unit.character_build.character_card_id,
        "character_build_input_fingerprint": assembly.input_fingerprint,
        "character_build_result_fingerprint": assembly.result_fingerprint,
        "character_build_battle_admission_status": assembly.battle_admission_status,
        "legacy_trace_runtime_activation_bypassed": True,
        "legacy_eidolon_runtime_activation_bypassed": True,
        "admitted_character_mechanism_ref_ids": tuple(
            ref.mechanism_ref_id for ref in assembly.admitted_dynamic_mechanism_refs
        ),
        "effective_skill_levels_by_action_id": {
            level.action_id: level.effective_level
            for level in assembly.effective_skill_levels
        },
        "effective_skill_level_sources": {
            level.action_id: tuple(source.to_json() for source in level.sources)
            for level in assembly.effective_skill_levels
        },
        "effective_skill_level_action_definitions": {
            level.action_id: {
                "definition_id": level.action_definition_id,
                "level": level.effective_level,
                "action_record_source": level.action_record_source.to_json(),
                "source": level.action_definition_source.to_json(),
            }
            for level in assembly.effective_skill_levels
        },
    }
    startup_specs: list[dict[str, Any]] = []
    for mechanism in assembly.admitted_dynamic_mechanism_refs:
        slot = rules.character_mechanism_slot(mechanism.source_ref.definition_identity)
        if slot is None:
            raise ValueError(f"admitted character mechanism slot disappeared: {mechanism.mechanism_ref_id}")
        if mechanism.mechanism_kind in {"trace_ability", "eidolon_ability"}:
            graph = rules.standalone_ability_graph(mechanism.target_ref_id)
            if graph is None or graph.coverage_status != "executable":
                raise ValueError(f"admitted character mechanism graph disappeared: {mechanism.mechanism_ref_id}")
            admission = slot.semantics.get("startup_admission")
            admitted_task_ids: tuple[str, ...] = ()
            if isinstance(admission, dict):
                raw_tasks = admission.get("admitted_tasks")
                if isinstance(raw_tasks, (list, tuple)):
                    admitted_task_ids = tuple(
                        str(item.get("task_id"))
                        for item in raw_tasks
                        if isinstance(item, dict) and item.get("task_id")
                    )
            startup_specs.append(
                {
                    "kind": f"formal_{mechanism.mechanism_kind}",
                    "slot": slot,
                    "slot_id": slot.mechanism_slot_id,
                    "slot_id_field": "mechanism_slot_id",
                    "graph_ref_id": graph.standalone_ability_graph_id,
                    "ability_name": graph.ability_name,
                    "param_values": tuple(_number_items(slot.semantics.get("param_values"))),
                    "dynamic_value_bindings": slot.semantics.get("dynamic_value_bindings"),
                    "dynamic_value_binding_mode": (
                        "configured_by_hash_required"
                        if mechanism.mechanism_kind == "trace_ability"
                        else "request_order_fallback"
                    ),
                    "admitted_task_ids": admitted_task_ids,
                }
            )
        else:
            raise ValueError(f"unsupported admitted character mechanism kind: {mechanism.mechanism_kind}")
    equipment_result = assembly.equipment_assembly_result
    if equipment_result is None:
        raise ValueError("formal character activation requires equipment assembly result")
    equipment_providers = tuple(equipment_result.dynamic_mechanisms)
    if any(
        selection.coverage_status != "executable" or selection.blocked_reason
        for selection in equipment_providers
    ):
        raise ValueError("battle-admitted character build contains blocked equipment mechanism")
    return flags, startup_specs, equipment_providers


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


def _fixed_numeric_value_resolution(
    value_resolver: ValueResolver,
    expression: object,
    *,
    data_card_id: str,
    data_card_kind: str,
    source_trace: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    return value_resolver.resolve(
        ValueBindingRequest(
            binding_kind="fixed_numeric_expression",
            expression=expression if isinstance(expression, (bool, int, float, str, list, tuple, dict)) else str(expression),
            required_context_keys=("data_card_source",),
            source_trace=source_trace,
        ),
        ValueContext(
            data_card_id=data_card_id,
            data_card_kind=data_card_kind,
            source_trace=source_trace,
        ),
    ).to_json()


def _resolution_float_or_none(resolution: dict[str, JSONValue]) -> float | None:
    if resolution.get("ok") is not True:
        return None
    value = resolution.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _resolution_int_or_none(resolution: dict[str, JSONValue]) -> int | None:
    value = _resolution_float_or_none(resolution)
    if value is None or int(value) != value:
        return None
    return int(value)


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


def _eidolon_runtime_activation(value_resolver: ValueResolver, eidolon_slots: tuple[object, ...]) -> dict[str, Any]:
    flags: dict[str, object] = {}
    startup_specs: list[dict[str, Any]] = []
    skill_level_bonus_by_action_id: dict[str, int] = {}
    skill_level_bonus_sources: dict[str, list[dict[str, object]]] = {}
    skill_level_bonus_resolutions: dict[str, list[dict[str, object]]] = {}
    skill_level_bonus_blocked: list[dict[str, object]] = []
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
                value_resolution = _fixed_numeric_value_resolution(
                    value_resolver,
                    raw_bonus,
                    data_card_id=str(getattr(slot, "character_data_card_id", "") or ""),
                    data_card_kind="character",
                    source_trace=getattr(slot, "source", None).to_json() if getattr(slot, "source", None) else {},
                )
                bonus = _resolution_int_or_none(value_resolution)
                if bonus is None:
                    skill_level_bonus_blocked.append(
                        {
                            "eidolon_slot_id": getattr(slot, "eidolon_slot_id", ""),
                            "rank": getattr(slot, "rank", 0),
                            "rank_id": getattr(slot, "rank_id", ""),
                            "raw_skill_id": raw_skill_id,
                            "blocked_reason": value_resolution.get("blocked_reason")
                            or "eidolon_skill_level_bonus_not_integer",
                            "value_resolution": value_resolution,
                            "source": getattr(slot, "source", None).to_json() if getattr(slot, "source", None) else {},
                        }
                    )
                    continue
                action_id = f"avatar_skill:{raw_skill_id}"
                skill_level_bonus_by_action_id[action_id] = skill_level_bonus_by_action_id.get(action_id, 0) + bonus
                skill_level_bonus_resolutions.setdefault(action_id, []).append(value_resolution)
                skill_level_bonus_sources.setdefault(action_id, []).append(
                    {
                        "eidolon_slot_id": getattr(slot, "eidolon_slot_id", ""),
                        "rank": getattr(slot, "rank", 0),
                        "rank_id": getattr(slot, "rank_id", ""),
                        "raw_skill_id": raw_skill_id,
                        "bonus": bonus,
                        "value_resolution": value_resolution,
                        "source": getattr(slot, "source", None).to_json() if getattr(slot, "source", None) else {},
                    }
                )
    if skill_level_bonus_by_action_id:
        flags["eidolon_skill_level_bonus_by_action_id"] = skill_level_bonus_by_action_id
        flags["eidolon_skill_level_bonus_sources"] = skill_level_bonus_sources
        flags["eidolon_skill_level_bonus_value_resolutions"] = skill_level_bonus_resolutions
    if skill_level_bonus_blocked:
        flags["eidolon_skill_level_bonus_blocked"] = tuple(skill_level_bonus_blocked)
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
        graph_ref_id = spec.get("graph_ref_id")
        if isinstance(graph_ref_id, str) and graph_ref_id:
            referenced_graph = rules.standalone_ability_graph(graph_ref_id)
            graphs = (
                (referenced_graph,)
                if referenced_graph is not None
                and referenced_graph.coverage_status == "executable"
                and referenced_graph.ability_name == ability_name
                else ()
            )
        else:
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
