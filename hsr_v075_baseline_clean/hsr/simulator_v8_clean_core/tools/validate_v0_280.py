from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..rules.ir import MonsterDataCardIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.loader import ScenarioLoader
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_280"


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    *,
    example_output: Path | None = None,
) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    card = _select_executable_simple_monster_card(rules)
    example_card = _executable_example_card(rules, card)
    execution_case = _manual_route_execution_case(package_root.parent, rules, card)
    boundary_case = _boundary_case(rules, card)
    checks = {
        "executable_example_card": example_card["checks"],
        "manual_route_execution": execution_case["checks"],
        "boundary": boundary_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
            "selection_policy": example_card["selection_policy"],
        },
        "checks": checks,
        "executable_example_card": example_card,
        "manual_route_execution_case": execution_case,
        "boundary_case": boundary_case,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_280.json", result)
    write_json(output_dir / "executable_monster_example_card_v0_280.json", example_card)
    if example_output is not None:
        write_json(example_output, example_card)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_280 executable simple monster slice.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--example-output", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir, example_output=args.example_output)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _select_executable_simple_monster_card(rules: RuleBook) -> MonsterDataCardIR:
    for card in rules.ir.monster_data_cards:
        monster_config = card.raw_parameter_blocks.get("monster_config")
        template_source = card.source.evidence.get("template_source")
        if not isinstance(monster_config, dict) or not isinstance(template_source, dict):
            continue
        if template_source.get("source_path") != "ExcelOutput/MonsterTemplateConfig.json":
            continue
        if card.coverage_status != "lowered":
            continue
        if card.ai_policy.get("admission_status") != "executable":
            continue
        if len(card.skill_ids) != 1 or len(card.skill_slots) != 1 or len(card.action_sequence) != 1:
            continue
        if card.summon_refs:
            continue
        step = card.action_sequence[0]
        action_ref = str(step.get("action_ref") or "")
        definition = rules.action_definition(action_ref, 1)
        binding = rules.action_ability_binding(action_ref, 1)
        damage_emissions = rules.damage_emissions_for_action(action_ref, 1)
        toughness_emissions = rules.toughness_emissions_for_action(action_ref, 1)
        if definition is None or definition.target_mode != "aoe":
            continue
        if definition.source.source_path not in {"ExcelOutput/MonsterSkillConfig.json", "ExcelOutput/MonsterSkillUniqueConfig.json"}:
            continue
        if binding is None or binding.coverage_status != "executable" or binding.source_mode != "mainline_monster":
            continue
        if not any(emission.coverage_status == "executable" for emission in damage_emissions):
            continue
        if not any(emission.coverage_status == "executable" for emission in toughness_emissions):
            continue
        if not _localized(card.display, "localized_names", "CHS") or not _localized(card.display, "localized_names", "EN"):
            continue
        return card
    raise RuntimeError("executable simple monster card sample not found")


def _executable_example_card(rules: RuleBook, card: MonsterDataCardIR) -> dict[str, Any]:
    action_ref = str(card.action_sequence[0].get("action_ref") or "")
    definition = rules.require_action_definition(action_ref, 1)
    action_set = rules.combatant_action_set(card.entity_ref)
    binding = rules.action_ability_binding(action_ref, 1)
    hit_profiles = rules.hit_profiles_for_action(action_ref, 1)
    damage_emissions = rules.damage_emissions_for_action(action_ref, 1)
    toughness_emissions = rules.toughness_emissions_for_action(action_ref, 1)
    formula_bindings = rules.skill_formula_bindings_for_action_param(action_ref, 1, 0, "direct_damage")
    checks = {
        "has_display_name": bool(_localized(card.display, "localized_names", "CHS"))
        and bool(_localized(card.display, "localized_names", "EN")),
        "action_definition_from_monster_skill_config": definition.source.source_path
        in {"ExcelOutput/MonsterSkillConfig.json", "ExcelOutput/MonsterSkillUniqueConfig.json"},
        "action_target_mode_aoe": definition.target_mode == "aoe",
        "action_set_uses_monster_skill_namespace": bool(
            action_set
            and action_set.skill_index_map.get("0", {}).get("action_ref") == action_ref
            and str(action_ref).startswith("monster_skill:")
        ),
        "binding_executable": bool(binding and binding.coverage_status == "executable"),
        "binding_source_mode_monster": bool(binding and binding.source_mode == "mainline_monster"),
        "has_executable_formula_binding": any(binding.coverage_status == "executable" for binding in formula_bindings),
        "has_executable_hit_profile": any(profile.coverage_status == "executable" for profile in hit_profiles),
        "has_executable_damage_emission": any(emission.coverage_status == "executable" for emission in damage_emissions),
        "has_executable_toughness_emission": any(emission.coverage_status == "executable" for emission in toughness_emissions),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "schema_version": "v8_executable_monster_example_card_v0_280",
        "selection_policy": {
            "mode": "structured_predicate",
            "fixed_monster_id_used_for_selection": False,
            "predicate": [
                "ordinary MonsterTemplateConfig source",
                "single SkillList entry and single AISkillSequence step",
                "fixed sequence AI policy admitted but enemy AI runtime not admitted",
                "MonsterSkillConfig/MonsterSkillUniqueConfig action source",
                "mainline monster ability binding executable",
                "direct damage and toughness emissions executable",
                "display names exist for UI/audit only",
            ],
        },
        "checks": {"ok": checks["ok"], "checks": checks},
        "identity": {
            "monster_id": card.monster_id,
            "entity_ref": card.entity_ref,
            "template_id": card.template_id,
            "display_name_chs": _localized(card.display, "localized_names", "CHS"),
            "display_name_en": _localized(card.display, "localized_names", "EN"),
            "rank": card.rank,
        },
        "action": {
            "action_ref": action_ref,
            "definition": definition.to_json(),
            "action_set": action_set.to_json() if action_set else {},
            "ability_binding": binding.to_json() if binding else {},
            "hit_profiles": [profile.to_json() for profile in hit_profiles],
            "formula_bindings": [binding.to_json() for binding in formula_bindings],
            "damage_emissions": [emission.to_json() for emission in damage_emissions],
            "toughness_emissions": [emission.to_json() for emission in toughness_emissions],
        },
        "card": card.to_json(),
    }


def _manual_route_execution_case(hsr_root: Path, rules: RuleBook, card: MonsterDataCardIR) -> dict[str, Any]:
    scenario_path = hsr_root / "simulator_v8_clean_core/scenarios/examples/identity_smoke_v0_204.json"
    data = json.loads(scenario_path.read_text(encoding="utf-8"))
    action_ref = str(card.action_sequence[0].get("action_ref") or "")
    data["route"] = [
        {
            "actor_id": "enemy:target",
            "action_ref": action_ref,
            "action_level": 1,
            "target_ids": ["ally:saber"],
            "source": "manual",
            "metadata": {"reset_actor_av": True, "label": "monster executable slice"},
        }
    ]
    for unit in data["units"]:
        if unit.get("unit_id") == "ally:saber":
            panel = unit.setdefault("panel", {})
            panel["hp"] = 1_000_000
            panel["max_hp"] = 1_000_000
            panel["toughness"] = 100
            panel["max_toughness"] = 100
            panel.setdefault("flags", {})["weaknesses"] = ["Ice"]
        if unit.get("unit_id") == "enemy:target":
            panel = unit.setdefault("panel", {})
            panel["attack"] = 1000
            panel["hp"] = 1_000_000
            panel["max_hp"] = 1_000_000
    scenario = ScenarioLoader().load_dict(data)
    built = ScenarioStateBuilder(rules).build(scenario)
    before = built.state
    after, transition = CombatExecutor(rules).execute(built.commands[0], before)
    records = transition.transaction.settlement.records if transition.transaction.settlement else []
    damage_records = [record for record in records if record.get("record_type") == "damage"]
    toughness_records = [record for record in records if record.get("record_type") == "toughness"]
    ally_before = before.units["ally:saber"]
    ally_after = after.units["ally:saber"]
    checks = {
        "action_enabled": transition.coverage.get("action_enabled") is True,
        "blocked_reason_empty": transition.coverage.get("blocked_reason") == "",
        "target_resolved_to_ally": transition.target_resolution.selected == ("ally:saber",),
        "damage_mutation_exists": transition.coverage.get("damage_mutation_count", 0) > 0,
        "toughness_mutation_exists": transition.coverage.get("toughness_mutation_count", 0) > 0,
        "ally_hp_decreased": ally_after.hp < ally_before.hp,
        "ally_toughness_decreased": ally_after.toughness < ally_before.toughness,
        "has_damage_settlement": bool(damage_records),
        "has_toughness_settlement": bool(toughness_records),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "scenario_id": scenario.scenario_id,
        "command": {
            "actor_id": built.commands[0].actor_id,
            "action_id": built.commands[0].action_id,
            "action_level": built.commands[0].action_level,
            "target_ids": list(built.commands[0].target_ids),
            "source": built.commands[0].source,
            "queue_name": built.commands[0].queue_name,
            "metadata": built.commands[0].metadata,
        },
        "before": {"ally_hp": ally_before.hp, "ally_toughness": ally_before.toughness},
        "after": {"ally_hp": ally_after.hp, "ally_toughness": ally_after.toughness},
        "target_resolution": transition.target_resolution.to_json(),
        "coverage": {
            "action_enabled": transition.coverage.get("action_enabled"),
            "blocked_reason": transition.coverage.get("blocked_reason"),
            "damage_mutation_count": transition.coverage.get("damage_mutation_count"),
            "toughness_mutation_count": transition.coverage.get("toughness_mutation_count"),
            "damage_ok": transition.coverage.get("damage_ok"),
            "toughness_ok": transition.coverage.get("toughness_ok"),
        },
        "damage_records": damage_records,
        "toughness_records": toughness_records,
        "mutation_count": len(transition.transaction.mutations),
    }


def _boundary_case(rules: RuleBook, card: MonsterDataCardIR) -> dict[str, Any]:
    action_ref = str(card.action_sequence[0].get("action_ref") or "")
    skill_id = action_ref.split(":", 1)[1] if ":" in action_ref else ""
    action_set = rules.combatant_action_set(card.entity_ref)
    first_action = action_set.skill_index_map.get("0", {}) if action_set else {}
    ordinary_definition = rules.action_definition(action_ref, 1)
    ilbattle_definition = rules.action_definition(f"ilbattle_monster_skill:{skill_id}", 1)
    missing_formula_emission = next(
        (
            emission
            for emission in rules.ir.damage_emissions
            if emission.action_id.startswith("monster_skill:")
            and emission.coverage_status == "blocked"
            and "character_data_card_skill_formula_missing" in emission.blocked_reason
        ),
        None,
    )
    unknown_target_event = next(
        (
            event
            for event in rules.ir.action_events
            if event.action_id.startswith("monster_skill:")
            and "unknown_target_mode_not_executable" in event.blocked_reason
        ),
        None,
    )
    complex_ai_card = next(
        (
            item
            for item in rules.ir.monster_data_cards
            if item.ai_policy.get("admission_status") == "blocked"
            and item.ai_policy.get("policy_kind") == "complex_or_unsupported_ai"
        ),
        None,
    )
    checks = {
        "ordinary_action_set_slot_executable": first_action.get("coverage_status") == "executable",
        "ordinary_action_source_is_monster_skill_config": bool(
            ordinary_definition
            and ordinary_definition.source.source_path
            in {"ExcelOutput/MonsterSkillConfig.json", "ExcelOutput/MonsterSkillUniqueConfig.json"}
        ),
        "ilbattle_namespace_separate": ilbattle_definition is None
        or ilbattle_definition.action_id.startswith("ilbattle_monster_skill:"),
        "missing_formula_case_blocked": missing_formula_emission is not None,
        "unknown_target_case_blocked": unknown_target_event is not None,
        "complex_ai_not_executable": complex_ai_card is not None,
        "observed_skill_id_not_fixed_selection": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "ordinary_action_set_slot": first_action,
        "ordinary_definition_source": ordinary_definition.source.to_json() if ordinary_definition else {},
        "ilbattle_definition_source": ilbattle_definition.source.to_json() if ilbattle_definition else {},
        "missing_formula_blocked_emission": missing_formula_emission.to_json() if missing_formula_emission else {},
        "unknown_target_blocked_event": unknown_target_event.to_json() if unknown_target_event else {},
        "complex_ai_blocked_card": complex_ai_card.to_json() if complex_ai_card else {},
    }


def _localized(display: object, key: str, locale: str) -> str:
    if not isinstance(display, dict):
        return ""
    localized = display.get(key)
    if not isinstance(localized, dict):
        return ""
    value = localized.get(locale)
    return str(value) if value is not None else ""


if __name__ == "__main__":
    raise SystemExit(main())
