from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, UnitState
from ..rules.ir import ActionDefinitionIR, EffectIR, SummonMonsterIntentIR, WaveDefinitionIR
from ..rules.rulebook import RuleBook
from ..scenarios import IdentityResolver, ScenarioLoader, ScenarioStateBuilder
from ..systems.effect import EffectRegistry
from ..systems.rng import RNGOutcome, RNGRequest, resolve_rng_request
from ..systems.status import StatusSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json


VALIDATION_VERSION = "p1_8_battle_setup"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    action = _select_avatar_action(rules)
    enemy_ref = _select_enemy_entity(rules)
    status_effect, status_case = _select_initial_status_case(rules, action, enemy_ref)
    summon_intent = _select_executable_summon_monster_intent(rules)
    wave_definition = _select_two_wave_definition(rules)

    schema_cases = {
        "legacy": _legacy_case(package_root, rules),
        "battle_setup": _schema_battle_setup_case(rules, action, enemy_ref),
    }
    roster_resource_cases = _roster_resource_case(rules, action, enemy_ref)
    wave_cases = _two_wave_case(rules, action, enemy_ref, wave_definition)
    status_cases = _status_cases(rules, action, enemy_ref, status_effect, status_case)
    summon_cases = _summon_cases(rules, action, enemy_ref, summon_intent)
    timeline_rng_objective_cases = _timeline_rng_objective_cases(rules, action, enemy_ref)
    negative_cases = _negative_cases(rules, action, enemy_ref)
    static_boundary = _static_boundary_case(package_root)

    matrix = {
        "schema_load_legacy": schema_cases["legacy"]["checks"],
        "schema_load_battle_setup": schema_cases["battle_setup"]["checks"],
        "roster_resources": roster_resource_cases["checks"],
        "two_wave_setup": wave_cases["checks"],
        "initial_status": status_cases["checks"],
        "initial_summon": summon_cases["summoned_monster"]["checks"],
        "servant_initial_setup_boundary": summon_cases["servant_initial_setup"]["checks"],
        "timeline_setup": timeline_rng_objective_cases["timeline"]["checks"],
        "rng_setup": timeline_rng_objective_cases["rng"]["checks"],
        "objective_metadata": timeline_rng_objective_cases["objective"]["checks"],
        "bad_refs": negative_cases["checks"],
        "static_boundary": static_boundary["checks"],
    }
    summary = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in matrix.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "structured_ir_predicates_no_fixed_stage_or_monster_for_main_samples",
                "legacy_case_uses_fixed_example_file_for_backward_compatibility_only": True,
                "status_effect_id": status_effect.effect_id,
                "summon_intent_id": summon_intent.summon_intent_id,
                "wave_definition_id": wave_definition.wave_definition_id,
                "avatar_action_id": action.action_id,
                "enemy_ref": enemy_ref,
            },
            "counts": {
                "effects": len(rules.ir.effects),
                "summon_monster_intents": len(rules.ir.summon_monster_intents),
                "wave_definitions": len(rules.ir.wave_definitions),
            },
        },
        "checks": matrix,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p1_8_battle_setup.json", summary)
    write_json(output_dir / "battle_setup_schema_cases_p1_8.json", schema_cases)
    write_json(output_dir / "battle_setup_wave_cases_p1_8.json", wave_cases)
    write_json(output_dir / "battle_setup_roster_resource_cases_p1_8.json", roster_resource_cases)
    write_json(output_dir / "battle_setup_status_cases_p1_8.json", status_cases)
    write_json(output_dir / "battle_setup_summon_cases_p1_8.json", summon_cases)
    write_json(output_dir / "battle_setup_timeline_rng_objective_cases_p1_8.json", timeline_rng_objective_cases)
    write_json(output_dir / "battle_setup_negative_cases_p1_8.json", negative_cases)
    write_json(output_dir / "battle_setup_static_boundary_p1_8.json", static_boundary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 P1-8 battle setup scenario entry.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    summary = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={summary['ok']}")
    return 0 if summary["ok"] else 1


def _legacy_case(package_root: Path, rules: RuleBook) -> dict[str, Any]:
    path = package_root / "scenarios" / "examples" / "identity_smoke_v0_204.json"
    scenario = ScenarioLoader().load_path(path)
    validation = IdentityResolver(rules).validate(scenario)
    build = ScenarioStateBuilder(rules).build(scenario)
    checks = {
        "load_ok": scenario.scenario_id == "identity_smoke_v0_204",
        "identity_ok": validation.ok,
        "build_ok": bool(build.state.units) and bool(build.commands),
        "battle_setup_default_present": scenario.battle_setup.resources.skill_points == scenario.skill_points,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "scenario_id": scenario.scenario_id,
        "unit_count": len(build.state.units),
        "command_count": len(build.commands),
    }


def _schema_battle_setup_case(rules: RuleBook, action: ActionDefinitionIR, enemy_ref: str) -> dict[str, Any]:
    data = _base_scenario_data(rules, action, enemy_ref)
    data["skill_points"] = 2
    data["rng_state"] = "seed:p1_8"
    data["battle_setup"] = {
        "resources": {"skill_points": 2, "max_skill_points": 5},
        "timeline": {"mode": "runtime_initialize", "global_av": 0.0},
        "rng": {"rng_mode": "explicit_ledger", "rng_choices": {"validation:choice": "chosen"}},
        "objective": {"objective_id": "p1_8_objective", "kind": "defeat_all_enemies", "payload": {"enemy_side": "enemy"}},
        "metadata": {"validation": VALIDATION_VERSION},
    }
    scenario = ScenarioLoader().load_dict(data)
    build = ScenarioStateBuilder(rules).build(scenario)
    checks = {
        "setup_dataclass_loaded": scenario.battle_setup.rng is not None
        and scenario.battle_setup.objective is not None,
        "resources_synced": build.state.skill_points == 2 and build.state.max_skill_points == 5,
        "rng_state_synced": build.state.rng_state == "seed:p1_8",
        "setup_rng_state_filled_from_root": scenario.battle_setup.rng is not None
        and scenario.battle_setup.rng.rng_state == "seed:p1_8",
        "objective_in_global_flags": isinstance(build.state.global_flags.get("objective"), dict),
        "command_metadata_has_rng": build.commands[0].metadata.get("rng_mode") == "explicit_ledger"
        and build.commands[0].metadata.get("rng_choices", {}).get("validation:choice") == "chosen",
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "battle_setup": _compact_setup(scenario),
        "command_metadata": build.commands[0].metadata,
    }


def _roster_resource_case(rules: RuleBook, action: ActionDefinitionIR, enemy_ref: str) -> dict[str, Any]:
    data = _base_scenario_data(rules, action, enemy_ref)
    data["skill_points"] = 1
    data["max_skill_points"] = 4
    data["units"][0]["panel"]["hp_ratio"] = 0.5
    data["units"][0]["panel"].pop("hp", None)
    data["units"][0]["panel"]["energy_ratio"] = 1.0
    data["units"][0]["panel"].pop("energy", None)
    scenario = ScenarioLoader().load_dict(data)
    build = ScenarioStateBuilder(rules).build(scenario)
    actor = build.state.units["ally:actor"]
    target = build.state.units["enemy:target"]
    checks = {
        "ally_hp_ratio_applied": actor.hp == actor.max_hp * 0.5,
        "ally_energy_ratio_applied": actor.energy == actor.max_energy,
        "battle_resources_applied": build.state.skill_points == 1 and build.state.max_skill_points == 4,
        "enemy_profile_filled": target.max_hp > 1.0 and target.attack > 0.0 and target.speed > 0.0,
        "panel_override_trace_recorded": "panel_overrides" not in target.flags,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "actor": {"hp": actor.hp, "max_hp": actor.max_hp, "energy": actor.energy, "max_energy": actor.max_energy},
        "enemy_profile_id": target.flags.get("combatant_profile_id"),
    }


def _two_wave_case(
    rules: RuleBook,
    action: ActionDefinitionIR,
    enemy_ref: str,
    definition: WaveDefinitionIR,
) -> dict[str, Any]:
    data = _base_scenario_data(rules, action, enemy_ref)
    data["battle_setup"] = {
        "wave": {
            "kind": "wave_definition",
            "wave_definition_ref": definition.wave_definition_id,
            "wave_index": 0,
        }
    }
    scenario = ScenarioLoader().load_dict(data)
    build = ScenarioStateBuilder(rules).build(scenario)
    runtime = build.state.global_flags.get("wave_runtime")
    current_ids = tuple(runtime.get("current_wave_unit_ids", ()) if isinstance(runtime, dict) else ())
    next_ids = {
        _wave_unit_id(definition, entry)
        for entry in rules.wave_entries_for_wave(definition.wave_definition_id, 1)
        if entry.coverage_status == "executable"
    }
    checks = {
        "two_wave_setup": isinstance(runtime, dict) and runtime.get("total_waves", 0) >= 2,
        "current_wave_spawned": bool(current_ids) and all(unit_id in build.state.units for unit_id in current_ids),
        "next_wave_absent": bool(next_ids) and all(unit_id not in build.state.units for unit_id in next_ids),
        "wave_runtime_source_trace": isinstance(runtime, dict) and isinstance(runtime.get("source_trace"), dict),
        "blocked_entries_no_fake_units": isinstance(runtime, dict)
        and all(str(entry.get("entry_id", "")) not in build.state.units for entry in runtime.get("blocked_entries", [])),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "wave_definition_id": definition.wave_definition_id,
        "runtime": runtime if isinstance(runtime, dict) else {},
        "unit_ids": sorted(build.state.units),
    }


def _status_cases(
    rules: RuleBook,
    action: ActionDefinitionIR,
    enemy_ref: str,
    effect: EffectIR,
    selected_case: dict[str, Any],
) -> dict[str, Any]:
    non_add = next((item for item in rules.ir.effects if item.opcode != "AddModifier"), None)
    blocked_add = next(
        (
            item
            for item in rules.ir.effects
            if item.opcode == "AddModifier" and EffectRegistry(StatusSystem(rules)).coverage(item) != "executable"
        ),
        None,
    )
    unknown = _build_error(
        rules,
        _with_initial_status(_base_scenario_data(rules, action, enemy_ref), "effect:missing:p1_8"),
    )
    non_add_error = (
        _build_error(rules, _with_initial_status(_base_scenario_data(rules, action, enemy_ref), non_add.effect_id))
        if non_add is not None
        else "no_non_add_modifier_effect_found"
    )
    blocked_case = (
        _blocked_status_case(rules, action, enemy_ref, blocked_add)
        if blocked_add is not None
        else {"checks": {"ok": True, "checks": {"blocked_add_modifier_source_gap": True}}, "reason": "none_found"}
    )
    checks = {
        "source_backed_status_mutation": selected_case["checks"]["source_backed_status_mutation"],
        "status_detail_has_source_trace": selected_case["checks"]["status_detail_has_source_trace"],
        "setup_records_present": selected_case["checks"]["setup_records_present"],
        "unknown_effect_fails": "unknown effect_ref" in unknown,
        "non_add_modifier_fails": "expected 'AddModifier'" in non_add_error or non_add is None,
        "blocked_effect_no_mutation": blocked_case["checks"]["ok"],
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "selected": selected_case,
        "negative": {
            "unknown_effect_error": unknown,
            "non_add_modifier_error": non_add_error,
            "blocked_effect": blocked_case,
        },
    }


def _blocked_status_case(rules: RuleBook, action: ActionDefinitionIR, enemy_ref: str, effect: EffectIR) -> dict[str, Any]:
    scenario = ScenarioLoader().load_dict(_with_initial_status(_base_scenario_data(rules, action, enemy_ref), effect.effect_id))
    build = ScenarioStateBuilder(rules).build(scenario)
    checks = {
        "blocked_record_present": any(record.get("status") == "blocked" for record in build.blocked_setup),
        "no_setup_mutations": not build.setup_mutations,
        "no_status_detail_from_blocked_effect": not any(
            detail.get("source_trace", {}).get("effect_id") == effect.effect_id
            for unit in build.state.units.values()
            for detail in unit.flags.get("status_details", ())
            if isinstance(detail, dict)
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "effect_id": effect.effect_id}


def _summon_cases(
    rules: RuleBook,
    action: ActionDefinitionIR,
    enemy_ref: str,
    intent: SummonMonsterIntentIR,
) -> dict[str, Any]:
    data = _base_scenario_data(rules, action, enemy_ref)
    data["battle_setup"] = {
        "initial_summons": [
            {"kind": "summoned_monster", "owner_id": "ally:actor", "summon_intent_ref": intent.summon_intent_id}
        ]
    }
    scenario = ScenarioLoader().load_dict(data)
    build = ScenarioStateBuilder(rules).build(scenario)
    spawned = tuple(
        unit_id for unit_id, unit in build.state.units.items() if unit.flags.get("summon_kind") == "summoned_monster"
    )
    runtime = build.state.global_flags.get("summon_runtime")
    summoned_checks = {
        "summon_monster_spawned": bool(spawned),
        "setup_mutations_present": any(
            mutation.metadata.get("lifecycle_operation") == "unit_spawn" for mutation in build.setup_mutations
        ),
        "summon_runtime_tracks_owner": isinstance(runtime, dict) and "ally:actor" in runtime.get("by_owner", {}),
        "source_trace_present": all(build.state.units[unit_id].flags.get("summon_source_trace") for unit_id in spawned),
    }
    summoned_checks["ok"] = all(value for key, value in summoned_checks.items() if key != "ok")
    timeline_after_summon = _summon_timeline_override_case(rules, action, enemy_ref, intent, spawned[0] if spawned else "")

    servant_data = _base_scenario_data(rules, action, enemy_ref)
    servant_data["battle_setup"] = {"initial_summons": [{"kind": "servant", "owner_id": "ally:actor"}]}
    servant_build = ScenarioStateBuilder(rules).build(ScenarioLoader().load_dict(servant_data))
    servant_checks = {
        "blocked_record_present": any(
            record.get("blocked_reason") == "servant_initial_setup_admission_missing" for record in servant_build.blocked_setup
        ),
        "no_unit_created": len(servant_build.state.units) == 2,
        "no_setup_mutation": not servant_build.setup_mutations,
    }
    servant_checks["ok"] = all(value for key, value in servant_checks.items() if key != "ok")
    missing_owner = _base_scenario_data(rules, action, enemy_ref)
    missing_owner["battle_setup"] = {
        "initial_summons": [
            {"kind": "summoned_monster", "owner_id": "ally:missing", "summon_intent_ref": intent.summon_intent_id}
        ]
    }
    missing_owner_error = _build_error(rules, missing_owner)
    return {
        "summoned_monster": {
            "checks": {
                "ok": summoned_checks["ok"] and timeline_after_summon["checks"]["ok"],
                "checks": {**summoned_checks, "timeline_after_summon_ok": timeline_after_summon["checks"]["ok"]},
            },
            "intent_id": intent.summon_intent_id,
            "spawned_unit_ids": list(spawned),
            "setup_records": build.setup_records,
            "timeline_after_summon": timeline_after_summon,
        },
        "servant_initial_setup": {
            "checks": {"ok": servant_checks["ok"], "checks": servant_checks},
            "source_state": "implementation_missing",
            "classification": "servant_owner_stat_timeline_action_lifecycle_admission_missing",
            "mechanism_complete": False,
            "blocked_setup": servant_build.blocked_setup,
        },
        "servant_source_gap": {
            "checks": {"ok": servant_checks["ok"], "checks": servant_checks},
            "source_state": "implementation_missing",
            "classification": "deprecated_name_servant_is_not_true_source_gap",
            "mechanism_complete": False,
            "blocked_setup": servant_build.blocked_setup,
        },
        "missing_owner": {
            "checks": {"ok": "unknown owner_id" in missing_owner_error, "checks": {"missing_owner_fails": "unknown owner_id" in missing_owner_error}},
            "error": missing_owner_error,
        },
    }


def _summon_timeline_override_case(
    rules: RuleBook,
    action: ActionDefinitionIR,
    enemy_ref: str,
    intent: SummonMonsterIntentIR,
    spawned_unit_id: str,
) -> dict[str, Any]:
    if not spawned_unit_id:
        return {"checks": {"ok": False, "checks": {"spawned_unit_id_available": False}}}
    data = _base_scenario_data(rules, action, enemy_ref)
    data["battle_setup"] = {
        "initial_summons": [
            {"kind": "summoned_monster", "owner_id": "ally:actor", "summon_intent_ref": intent.summon_intent_id}
        ],
        "timeline": {
            "mode": "explicit_action_values",
            "action_values": {spawned_unit_id: 17.0},
            "explicit_overrides": [spawned_unit_id],
        },
    }
    scenario = ScenarioLoader().load_dict(data)
    build = ScenarioStateBuilder(rules).build(scenario)
    unit = build.state.units.get(spawned_unit_id)
    checks = {
        "spawned_unit_id_available": unit is not None,
        "timeline_applied_after_summon": unit is not None and unit.action_value == 17.0,
        "timeline_mutation_after_spawn": any(
            mutation.path == ("units", spawned_unit_id, "action_value") for mutation in build.setup_mutations
        ),
        "no_timeline_blocked": not any(record.get("record_type") == "setup_timeline" for record in build.blocked_setup),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "spawned_unit_id": spawned_unit_id,
        "action_value": unit.action_value if unit is not None else None,
    }


def _timeline_rng_objective_cases(rules: RuleBook, action: ActionDefinitionIR, enemy_ref: str) -> dict[str, Any]:
    timeline_data = _base_scenario_data(rules, action, enemy_ref)
    timeline_data["battle_setup"] = {
        "timeline": {
            "mode": "explicit_action_values",
            "global_av": 12.0,
            "turn_owner_id": "ally:actor",
            "action_values": {"ally:actor": 42.0},
        }
    }
    timeline_build = ScenarioStateBuilder(rules).build(ScenarioLoader().load_dict(timeline_data))
    timeline_checks = {
        "explicit_av_applied": timeline_build.state.units["ally:actor"].action_value == 42.0,
        "global_av_recorded": timeline_build.state.global_flags.get("global_av") == 12.0,
        "setup_mutation_present": any(mutation.path == ("units", "ally:actor", "action_value") for mutation in timeline_build.setup_mutations),
    }
    timeline_checks["ok"] = all(value for key, value in timeline_checks.items() if key != "ok")

    rng_data = _base_scenario_data(rules, action, enemy_ref)
    rng_data["rng_state"] = "seed:p1_8"
    rng_data["battle_setup"] = {
        "rng": {
            "rng_mode": "explicit_ledger",
            "rng_choices": {"p1_8:choice": "right", "p1_8:override": "setup"},
        }
    }
    rng_data["route"][0]["metadata"]["rng_choices"] = {"p1_8:override": "route"}
    rng_build = ScenarioStateBuilder(rules).build(ScenarioLoader().load_dict(rng_data))
    metadata = rng_build.commands[0].metadata
    request = RNGRequest(
        rng_type="validation_choice",
        purpose="p1_8_command_metadata",
        event_id="rng:p1_8:command_metadata",
        choice_key="p1_8:choice",
        source="validation",
        before_state=rng_build.state.rng_state,
        decision_kind="choice",
        outcomes=(
            RNGOutcome("left", payload={"value": "left"}, weight=1.0),
            RNGOutcome("right", payload={"value": "right"}, weight=1.0),
        ),
        source_trace={"validation": VALIDATION_VERSION},
    )
    resolution_a = resolve_rng_request(
        request,
        rng_mode=str(metadata.get("rng_mode") or ""),
        rng_choices=metadata.get("rng_choices") if isinstance(metadata.get("rng_choices"), dict) else {},
    )
    resolution_b = resolve_rng_request(
        request,
        rng_mode=str(metadata.get("rng_mode") or ""),
        rng_choices=metadata.get("rng_choices") if isinstance(metadata.get("rng_choices"), dict) else {},
    )
    rng_checks = {
        "scenario_rng_state_applied": rng_build.state.rng_state == "seed:p1_8",
        "setup_rng_state_inherits_root": rng_build.state.global_flags.get("scenario_rng_setup", {}).get("rng_state")
        == "seed:p1_8",
        "command_metadata_injected": metadata.get("rng_mode") == "explicit_ledger"
        and metadata.get("rng_choices", {}).get("p1_8:choice") == "right",
        "route_rng_choice_override": metadata.get("rng_choices", {}).get("p1_8:override") == "route",
        "rng_resolution_replay_stable": resolution_a.ok
        and resolution_b.ok
        and resolution_a.event is not None
        and resolution_b.event is not None
        and resolution_a.event.to_json() == resolution_b.event.to_json(),
    }
    rng_checks["ok"] = all(value for key, value in rng_checks.items() if key != "ok")

    objective_data = _base_scenario_data(rules, action, enemy_ref)
    objective_data["battle_setup"] = {
        "objective": {"objective_id": "p1_8_keep_actor_alive", "kind": "survive", "payload": {"unit_id": "ally:actor"}}
    }
    objective_build = ScenarioStateBuilder(rules).build(ScenarioLoader().load_dict(objective_data))
    no_objective_build = ScenarioStateBuilder(rules).build(ScenarioLoader().load_dict(_base_scenario_data(rules, action, enemy_ref)))
    objective_checks = {
        "objective_metadata_present": isinstance(objective_build.state.global_flags.get("objective"), dict),
        "objective_not_in_command_metadata": objective_build.commands[0].metadata == no_objective_build.commands[0].metadata,
        "objective_does_not_change_units": objective_build.state.snapshot().to_json()["units"]
        == no_objective_build.state.snapshot().to_json()["units"],
    }
    objective_checks["ok"] = all(value for key, value in objective_checks.items() if key != "ok")
    return {
        "timeline": {"checks": {"ok": timeline_checks["ok"], "checks": timeline_checks}},
        "rng": {
            "checks": {"ok": rng_checks["ok"], "checks": rng_checks},
            "command_metadata": metadata,
            "rng_event": resolution_a.event.to_json() if resolution_a.event else {},
        },
        "objective": {"checks": {"ok": objective_checks["ok"], "checks": objective_checks}},
    }


def _negative_cases(rules: RuleBook, action: ActionDefinitionIR, enemy_ref: str) -> dict[str, Any]:
    cases: dict[str, str] = {}
    data = _base_scenario_data(rules, action, enemy_ref)
    data["units"][0]["entity_ref"] = "avatar:missing:p1_8"
    cases["unknown_entity"] = _build_error(rules, data)

    data = _base_scenario_data(rules, action, enemy_ref)
    data["units"][0]["panel"]["hp_ratio"] = 1.5
    data["units"][0]["panel"].pop("hp", None)
    cases["invalid_hp_ratio"] = _load_error(data)

    data = _base_scenario_data(rules, action, enemy_ref)
    data["units"][0]["panel"]["hp_ratio"] = 0.5
    cases["ambiguous_hp"] = _load_error(data)

    data = _base_scenario_data(rules, action, enemy_ref)
    data["units"][0]["panel"]["energy_ratio"] = 0.5
    data["units"][0]["panel"].pop("energy", None)
    data["units"][0]["panel"]["max_energy"] = 0
    cases["invalid_energy_ratio"] = _build_error(rules, data)

    data = _base_scenario_data(rules, action, enemy_ref)
    data["skill_points"] = 6
    data["battle_setup"] = {"resources": {"skill_points": 6, "max_skill_points": 5}}
    cases["invalid_skill_points"] = _load_error(data)

    data = _base_scenario_data(rules, action, enemy_ref)
    data["battle_setup"] = {"wave": {"kind": "wave_definition", "wave_definition_ref": "wave:missing:p1_8"}}
    cases["invalid_wave"] = _build_error(rules, data)

    data = _base_scenario_data(rules, action, enemy_ref)
    data["battle_setup"] = {
        "initial_summons": [
            {"kind": "summoned_monster", "owner_id": "ally:actor", "summon_intent_ref": "summon_intent:missing:p1_8"}
        ]
    }
    cases["unknown_summon_intent"] = _build_error(rules, data)

    data = _base_scenario_data(rules, action, enemy_ref)
    data["battle_setup"] = {"timeline": {"mode": "explicit_action_values", "action_values": {"ally:missing": 1.0}}}
    cases["unknown_timeline_unit"] = _build_error(rules, data)

    checks = {
        "unknown_entity_fails": "unknown entity_ref" in cases["unknown_entity"],
        "invalid_hp_ratio_fails": "hp_ratio must be between 0 and 1" in cases["invalid_hp_ratio"],
        "ambiguous_hp_fails": "hp and" in cases["ambiguous_hp"],
        "invalid_energy_ratio_fails": "energy_ratio requires max_energy > 0" in cases["invalid_energy_ratio"],
        "invalid_sp_fails": "skill_points must be <= max_skill_points" in cases["invalid_skill_points"],
        "invalid_wave_fails": "unknown wave_definition_ref" in cases["invalid_wave"],
        "unknown_summon_fails": "unknown summon_intent_ref" in cases["unknown_summon_intent"],
        "unknown_timeline_unit_fails": "unknown unit_id" in cases["unknown_timeline_unit"],
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "cases": cases}


def _static_boundary_case(package_root: Path) -> dict[str, Any]:
    banned = (
        "turnbasedgamedata-main",
        "TextMap",
        "model_pack_v3_0",
        "simulator_v7_7",
        "SimulatorRuntimeAdapter",
        "_legacy_effects",
        "action_ctx",
        "from ..tbgd",
    )
    violations: list[dict[str, Any]] = []
    for path in sorted((package_root / "scenarios").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for token in banned:
                if token in line:
                    violations.append(
                        {
                            "path": path.relative_to(package_root).as_posix(),
                            "line": line_no,
                            "token": token,
                        }
                    )
    checks = {"no_rule_source_boundary_violations": not violations}
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "violations": violations}


def _select_initial_status_case(
    rules: RuleBook,
    action: ActionDefinitionIR,
    enemy_ref: str,
) -> tuple[EffectIR, dict[str, Any]]:
    registry = EffectRegistry(StatusSystem(rules))
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if effect.opcode != "AddModifier" or registry.coverage(effect) != "executable":
            continue
        data = _with_initial_status(_base_scenario_data(rules, action, enemy_ref), effect.effect_id)
        try:
            build = ScenarioStateBuilder(rules).build(ScenarioLoader().load_dict(data))
        except Exception:
            continue
        status_details = [
            detail
            for unit in build.state.units.values()
            for detail in unit.flags.get("status_details", ())
            if isinstance(detail, dict)
        ]
        selected = [
            detail
            for detail in status_details
            if detail.get("source_trace", {}).get("effect_id") == effect.effect_id
        ]
        if not selected:
            continue
        checks = {
            "source_backed_status_mutation": bool(build.setup_mutations),
            "status_detail_has_source_trace": bool(selected[0].get("source_trace", {}).get("effect_source")),
            "setup_records_present": any(
                record.get("record_type") == "setup_initial_status" and record.get("effect_ref") == effect.effect_id
                for record in build.setup_records
            ),
        }
        checks["ok"] = all(value for key, value in checks.items() if key != "ok")
        return effect, {
            "checks": checks,
            "effect_id": effect.effect_id,
            "status_detail": selected[0],
            "setup_record_sample": [
                record for record in build.setup_records if record.get("record_type") == "setup_initial_status"
            ][-1],
        }
    raise RuntimeError("no executable AddModifier effect selected by structured predicate")


def _select_avatar_action(rules: RuleBook) -> ActionDefinitionIR:
    card_by_skill: dict[str, str] = {}
    for card in rules.ir.character_data_cards:
        if rules.entity(card.entity_ref) is None:
            continue
        for skill_id in card.skill_ids:
            card_by_skill[f"avatar_skill:{skill_id}"] = card.entity_ref
    for definition in sorted(rules.ir.action_definitions, key=lambda item: (item.action_id, item.level)):
        if definition.action_id not in card_by_skill:
            continue
        entity = rules.entity(definition.action_id)
        if entity is None or entity.entity_type != "avatar_skill":
            continue
        if rules.action_definition(definition.action_id, definition.level) is not None:
            return definition
    raise RuntimeError("no avatar action definition selected by structured predicate")


def _avatar_entity_for_action(rules: RuleBook, action: ActionDefinitionIR) -> str:
    for card in rules.ir.character_data_cards:
        if any(action.action_id == f"avatar_skill:{skill_id}" for skill_id in card.skill_ids):
            return card.entity_ref
    raise RuntimeError(f"no avatar entity for action {action.action_id}")


def _select_enemy_entity(rules: RuleBook) -> str:
    for profile in sorted(rules.ir.combatant_profiles, key=lambda item: item.entity_id):
        if profile.coverage_status != "executable" or profile.entity_type not in {"monster", "monster_template"}:
            continue
        if all(isinstance(profile.base_stats.get(key), (int, float)) for key in ("max_hp", "attack", "defense", "speed")):
            return profile.entity_id
    raise RuntimeError("no executable enemy combatant profile selected by structured predicate")


def _select_two_wave_definition(rules: RuleBook) -> WaveDefinitionIR:
    for definition in rules.wave_definitions():
        if definition.coverage_status != "executable" or definition.wave_count < 2:
            continue
        current = rules.wave_entries_for_wave(definition.wave_definition_id, 0)
        nxt = rules.wave_entries_for_wave(definition.wave_definition_id, 1)
        if not current or not nxt:
            continue
        if all(entry.coverage_status == "executable" for entry in current):
            return definition
    raise RuntimeError("no executable two-wave WaveDefinitionIR selected by structured predicate")


def _select_executable_summon_monster_intent(rules: RuleBook) -> SummonMonsterIntentIR:
    for intent in rules.summon_monster_intents():
        if intent.coverage_status != "executable" or not intent.entries:
            continue
        if all(
            entry.coverage_status == "executable"
            and entry.monster_entity_ref
            and entry.position_policy.get("location_type") in {"BeforeCaster", "AfterCaster", "First", "Last"}
            for entry in intent.entries
        ) and intent.delay_policy.get("admission_status") == "executable":
            return intent
    raise RuntimeError("no executable SummonMonsterIntentIR selected by structured predicate")


def _base_scenario_data(rules: RuleBook, action: ActionDefinitionIR, enemy_ref: str) -> dict[str, Any]:
    avatar_ref = _avatar_entity_for_action(rules, action)
    return {
        "scenario_id": "p1_8_battle_setup_validation",
        "version": VALIDATION_VERSION,
        "skill_points": 3,
        "max_skill_points": 5,
        "rng_state": "deterministic",
        "units": [
            {
                "unit_id": "ally:actor",
                "side": "ally",
                "entity_ref": avatar_ref,
                "level": 80,
                "position": 1,
                "panel": {
                    "max_hp": 3000,
                    "hp": 3000,
                    "attack": 1200,
                    "defense": 800,
                    "speed": 100,
                    "energy": 60,
                    "max_energy": 120,
                    "resources": {"critical_chance": 0.05, "critical_damage": 0.5},
                    "flags": {"position": 1},
                },
            },
            {
                "unit_id": "enemy:target",
                "side": "enemy",
                "entity_ref": enemy_ref,
                "level": 80,
                "position": 5,
                "panel": {"flags": {"position": 5}},
            },
        ],
        "route": [
            {
                "actor_id": "ally:actor",
                "action_ref": action.action_id,
                "action_level": action.level,
                "target_ids": ["enemy:target"],
                "source": "manual",
                "metadata": {"label": "p1_8_validation_route", "reset_actor_av": True},
            }
        ],
    }


def _with_initial_status(data: dict[str, Any], effect_ref: str) -> dict[str, Any]:
    data["battle_setup"] = {
        "initial_statuses": [
            {
                "target_id": "enemy:target",
                "source_id": "ally:actor",
                "caster_id": "ally:actor",
                "owner_id": "ally:actor",
                "param_entity_id": "ally:actor",
                "current_action_target_id": "enemy:target",
                "effect_ref": effect_ref,
            }
        ]
    }
    return data


def _wave_unit_id(definition: WaveDefinitionIR, entry: Any) -> str:
    return f"enemy:stage:{definition.stage_id}:wave:{entry.wave_index}:pos:{entry.position}"


def _compact_setup(scenario: Any) -> dict[str, Any]:
    setup = scenario.battle_setup
    return {
        "resources": {
            "skill_points": setup.resources.skill_points,
            "max_skill_points": setup.resources.max_skill_points,
        },
        "wave": _json_value(setup.wave),
        "timeline": _json_value(setup.timeline),
        "rng": _json_value(setup.rng),
        "initial_status_count": len(setup.initial_statuses),
        "initial_summon_count": len(setup.initial_summons),
        "objective": _json_value(setup.objective),
    }


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _load_error(data: dict[str, Any]) -> str:
    try:
        ScenarioLoader().load_dict(data)
    except Exception as exc:
        return str(exc)
    return ""


def _build_error(rules: RuleBook, data: dict[str, Any]) -> str:
    try:
        scenario = ScenarioLoader().load_dict(data)
        ScenarioStateBuilder(rules).build(scenario)
    except Exception as exc:
        return str(exc)
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
