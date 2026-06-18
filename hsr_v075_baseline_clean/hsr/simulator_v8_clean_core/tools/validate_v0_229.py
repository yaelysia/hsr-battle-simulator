from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.settlement import SettlementTraceabilityValidator
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..rules.ir import ActionDefinitionIR, CombatantProfileIR, RuleEntity
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_229"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    profile = _select_executable_monster_profile(ir, rules)
    action = _select_mainline_avatar_action(ir, rules)
    avatar = _avatar_for_action(ir, action)
    scenario = ScenarioLoader().load_dict(_scenario_dict(profile, action, avatar, enemy_panel={}))
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    state = build_result.state
    command = build_result.commands[0]
    enemy_unit = state.units["enemy:profile_target"]
    transition_state, transition = CombatExecutor(rules).execute(command, state)

    override_scenario = ScenarioLoader().load_dict(
        _scenario_dict(profile, action, avatar, enemy_panel={"toughness": 12})
    )
    override_state = ScenarioStateBuilder(rules).build(override_scenario).state
    negative = _negative_missing_profile_case(ir, rules, action, avatar)
    coverage = build_coverage_matrix(TBGDDiscovery(tbgd_root).scan(), ir)
    static_result = run_static_checks(package_root)
    snapshot_result = SnapshotCompletenessValidator().validate(state.snapshot())
    transition_contract = TransitionContractValidator().validate(transition)
    traceability = SettlementTraceabilityValidator().validate(transition.transaction.settlement, transition.transaction.mutations)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)

    checks = {
        "combatant_profile": _profile_checks(profile),
        "state_build_from_profile": _state_profile_checks(profile, enemy_unit),
        "panel_override": _override_checks(override_state),
        "negative_missing_profile": negative["checks"],
        "executor_smoke": {
            "ok": all(
                (
                    transition_contract.ok,
                    traceability.ok,
                    source_audit.ok,
                    snapshot_result.ok,
                    transition_state.snapshot().to_json() == transition.after.to_json(),
                )
            ),
            "checks": {
                "transition_contract": transition_contract.ok,
                "settlement_traceability": traceability.ok,
                "source_audit": source_audit.ok,
                "snapshot_completeness": snapshot_result.ok,
                "after_snapshot_matches_returned_state": transition_state.snapshot().to_json() == transition.after.to_json(),
            },
        },
        "coverage": {
            "ok": coverage.combatant_profile_status.get("executable", 0) > 0,
            "combatant_profile_status": coverage.combatant_profile_status,
        },
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all((identity_result.ok, static_result.ok, *(item["ok"] for item in checks.values()))),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selected_profile": _profile_selection(profile),
            "selected_action": _action_selection(action, avatar),
            "sampled": ir.metadata.get("sampled", {}),
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_229.json", result)
    write_json(output_dir / "sample_combatant_profile_v0_229.json", profile.to_json())
    write_json(output_dir / "sample_profile_state_v0_229.json", state.snapshot().to_json())
    write_json(output_dir / "sample_profile_override_state_v0_229.json", override_state.snapshot().to_json())
    write_json(output_dir / "sample_negative_profile_case_v0_229.json", negative)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_229 combatant profile baseline.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _select_executable_monster_profile(ir, rules: RuleBook) -> CombatantProfileIR:
    for profile in sorted(ir.combatant_profiles, key=lambda item: item.entity_id):
        if profile.entity_type != "monster" or profile.coverage_status != "executable":
            continue
        if profile.source.source_path != "ExcelOutput/MonsterConfig.json":
            continue
        if not profile.weaknesses or not profile.resistances:
            continue
        if not _profile_has_required_values(profile):
            continue
        if rules.entity(profile.entity_id) is not None:
            return profile
    raise RuntimeError("no executable mainline monster combatant profile found")


def _select_mainline_avatar_action(ir, rules: RuleBook) -> ActionDefinitionIR:
    for definition in sorted(ir.action_definitions, key=lambda item: (item.action_id, item.level)):
        if not definition.action_id.startswith("avatar_skill:"):
            continue
        if definition.level < 1 or definition.coverage_status != "executable":
            continue
        binding = rules.action_ability_binding(definition.action_id, definition.level)
        event = rules.action_event(definition.action_id, definition.level)
        emissions = rules.damage_emissions_for_action(definition.action_id, definition.level)
        if not (binding and binding.coverage_status == "executable" and event and not event.blocked_reason):
            continue
        if any(emission.coverage_status == "executable" for emission in emissions):
            return definition
    raise RuntimeError("no executable mainline avatar action found")


def _avatar_for_action(ir, action: ActionDefinitionIR) -> RuleEntity:
    raw_skill_id = action.action_id.split(":", 1)[1]
    for entity in sorted(ir.entities, key=lambda item: item.entity_id):
        if entity.entity_type != "avatar" or entity.source.source_path != "ExcelOutput/AvatarConfig.json":
            continue
        skill_list = entity.fields.get("SkillList")
        if isinstance(skill_list, list) and any(str(skill_id) == raw_skill_id for skill_id in skill_list):
            return entity
    raise RuntimeError(f"no avatar entity owns action {action.action_id}")


def _scenario_dict(
    profile: CombatantProfileIR,
    action: ActionDefinitionIR,
    avatar: RuleEntity,
    *,
    enemy_panel: dict[str, object],
) -> dict[str, object]:
    return {
        "scenario_id": f"profile_smoke_{VALIDATION_VERSION}",
        "version": VALIDATION_VERSION,
        "skill_points": 3,
        "max_skill_points": 5,
        "units": [
            {
                "unit_id": "ally:actor",
                "side": "ally",
                "entity_ref": avatar.entity_id,
                "level": 80,
                "position": 1,
                "panel": {
                    "max_hp": 3000,
                    "hp": 3000,
                    "attack": 3200,
                    "defense": 900,
                    "speed": 101,
                    "energy": 60,
                    "max_energy": 120,
                    "resources": {"critical_chance": 0.0, "critical_damage": 0.5},
                },
            },
            {
                "unit_id": "enemy:profile_target",
                "side": "enemy",
                "entity_ref": profile.entity_id,
                "level": 80,
                "position": 1,
                "panel": enemy_panel,
            },
        ],
        "route": [
            {
                "actor_id": "ally:actor",
                "action_ref": action.action_id,
                "action_level": action.level,
                "target_ids": ["enemy:profile_target"],
                "source": "manual",
                "metadata": {"crit_mode": "noncrit"},
            }
        ],
    }


def _negative_missing_profile_case(ir, rules: RuleBook, action: ActionDefinitionIR, avatar: RuleEntity) -> dict[str, object]:
    blocked_profile = next(
        (
            profile
            for profile in sorted(ir.combatant_profiles, key=lambda item: item.entity_id)
            if profile.entity_type == "monster_template" and profile.coverage_status != "executable"
        ),
        None,
    )
    if blocked_profile is None:
        return {"ok": False, "error": "no blocked monster_template profile found", "checks": {"ok": False}}
    scenario = ScenarioLoader().load_dict(_scenario_dict(blocked_profile, action, avatar, enemy_panel={}))
    try:
        ScenarioStateBuilder(rules).build(scenario)
    except ValueError as exc:
        error = str(exc)
    else:
        error = ""
    checks = {
        "ok": bool(error),
        "blocked_profile_selected": blocked_profile.coverage_status != "executable",
        "build_failed": bool(error),
        "error_mentions_missing_panel": "explicit panel field" in error,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "profile": blocked_profile.to_json(),
        "error": error,
        "checks": checks,
    }


def _profile_checks(profile: CombatantProfileIR) -> dict[str, object]:
    checks = {
        "profile_is_executable": profile.coverage_status == "executable",
        "source_is_monster_config": profile.source.source_path == "ExcelOutput/MonsterConfig.json",
        "has_template_id": bool(profile.template_id),
        "has_base_stats": all(key in profile.base_stats for key in ("max_hp", "attack", "defense", "speed")),
        "has_toughness_profile": all(key in profile.toughness_profile for key in ("max_toughness", "current_toughness")),
        "has_weaknesses": bool(profile.weaknesses),
        "has_resistances": bool(profile.resistances),
    }
    return {"ok": all(checks.values()), "checks": checks, "profile": _profile_selection(profile)}


def _state_profile_checks(profile: CombatantProfileIR, enemy_unit) -> dict[str, object]:
    checks = {
        "max_hp_from_profile": enemy_unit.max_hp == float(profile.base_stats["max_hp"]),
        "attack_from_profile": enemy_unit.attack == float(profile.base_stats["attack"]),
        "defense_from_profile": enemy_unit.defense == float(profile.base_stats["defense"]),
        "speed_from_profile": enemy_unit.speed == float(profile.base_stats["speed"]),
        "toughness_from_profile": enemy_unit.toughness == float(profile.toughness_profile["current_toughness"]),
        "max_toughness_from_profile": enemy_unit.max_toughness == float(profile.toughness_profile["max_toughness"]),
        "weaknesses_from_profile": tuple(enemy_unit.flags.get("weaknesses", ())) == tuple(profile.weaknesses),
        "source_trace_present": isinstance(enemy_unit.flags.get("combatant_profile_source_trace"), dict),
        "resistances_in_resources": all(
            f"{key}_resistance" in enemy_unit.resources for key in profile.resistances
        ),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _override_checks(state) -> dict[str, object]:
    enemy = state.units["enemy:profile_target"]
    overrides = tuple(enemy.flags.get("panel_overrides", ()))
    checks = {
        "explicit_toughness_override_applied": enemy.toughness == 12.0,
        "max_toughness_still_from_profile": enemy.max_toughness > 12.0,
        "override_recorded": "toughness" in overrides,
        "profile_trace_preserved": isinstance(enemy.flags.get("combatant_profile_source_trace"), dict),
    }
    return {"ok": all(checks.values()), "checks": checks, "panel_overrides": list(overrides)}


def _profile_selection(profile: CombatantProfileIR) -> dict[str, object]:
    return {
        "selection_mode": "structured_predicate",
        "entity_id": profile.entity_id,
        "profile_id": profile.profile_id,
        "coverage_status": profile.coverage_status,
        "source": profile.source.to_json(),
    }


def _action_selection(action: ActionDefinitionIR, avatar: RuleEntity) -> dict[str, object]:
    return {
        "selection_mode": "structured_predicate",
        "action_id": action.action_id,
        "action_level": action.level,
        "avatar_entity_id": avatar.entity_id,
        "source": action.source.to_json(),
    }


def _profile_has_required_values(profile: CombatantProfileIR) -> bool:
    return all(
        isinstance(profile.base_stats.get(key), (int, float))
        for key in ("max_hp", "attack", "defense", "speed")
    ) and all(
        isinstance(profile.toughness_profile.get(key), (int, float))
        for key in ("max_toughness", "current_toughness")
    )


if __name__ == "__main__":
    raise SystemExit(main())
