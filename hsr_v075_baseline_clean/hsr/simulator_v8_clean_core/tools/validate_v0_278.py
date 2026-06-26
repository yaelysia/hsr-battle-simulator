from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..rules.ir import MonsterDataCardIR
from ..rules.rulebook import RuleBook
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_278"


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
    card = _select_simple_sequence_card(rules)
    example_card = _complete_example_card(rules, card)
    source_mismatch_case = _monster_action_set_source_mismatch_case(rules, card)
    complete_card_case = _complete_card_case(example_card)
    checks = {
        "complete_example_card": complete_card_case["checks"],
        "monster_action_set_source_mismatch": source_mismatch_case["checks"],
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
        "complete_example_card_case": complete_card_case,
        "monster_action_set_source_mismatch_case": source_mismatch_case,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_278.json", result)
    write_json(output_dir / "complete_monster_example_card_v0_278.json", example_card)
    if example_output is not None:
        write_json(example_output, example_card)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and export v8 v0_278 complete monster example card.")
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


def _complete_example_card(rules: RuleBook, card: MonsterDataCardIR) -> dict[str, Any]:
    profile = rules.combatant_profile(card.entity_ref)
    action_set = rules.combatant_action_set(card.entity_ref)
    skill_slot = card.skill_slots[0] if card.skill_slots else {}
    sequence_step = card.action_sequence[0] if card.action_sequence else {}
    monster_config = card.raw_parameter_blocks.get("monster_config")
    template_config = card.raw_parameter_blocks.get("template_config")
    if not isinstance(monster_config, dict):
        monster_config = {}
    if not isinstance(template_config, dict):
        template_config = {}
    return {
        "schema_version": "v8_complete_monster_example_card_v0_278",
        "selection_policy": {
            "mode": "structured_predicate",
            "predicate": [
                "template source is ExcelOutput/MonsterTemplateConfig.json",
                "MonsterDataCardIR.coverage_status is lowered",
                "AI policy admission_status is executable fixed_skill_sequence",
                "exactly one SkillList entry and one AISkillSequence step",
                "no summon refs",
                "no CustomValues/DynamicValues/OverrideSkillParams/AbilityNameList",
                "sequence skill exists in SkillList and MonsterSkillConfig/MonsterSkillUniqueConfig",
            ],
            "fixed_monster_id_used_for_selection": False,
        },
        "identity": {
            "monster_id": card.monster_id,
            "entity_ref": card.entity_ref,
            "template_id": card.template_id,
            "rank": card.rank,
            "card_id": card.card_id,
            "display": card.display,
            "display_name_chs": _localized(card.display, "localized_names", "CHS"),
            "display_name_en": _localized(card.display, "localized_names", "EN"),
        },
        "panel_source": {
            "profile_id": card.profile_id,
            "linked_profile": profile.to_json() if profile else {},
            "template_base_stats": template_config.get("base_stats", {}),
            "monster_modify_ratios": {
                "attack_modify_ratio": monster_config.get("attack_modify_ratio"),
                "defense_modify_ratio": monster_config.get("defense_modify_ratio"),
                "hp_modify_ratio": monster_config.get("hp_modify_ratio"),
                "speed_modify_ratio": monster_config.get("speed_modify_ratio"),
                "stance_modify_ratio": monster_config.get("stance_modify_ratio"),
                "speed_modify_value": monster_config.get("speed_modify_value"),
                "stance_modify_value": monster_config.get("stance_modify_value"),
            },
            "stage_level_and_hard_level_group_admitted": False,
        },
        "weakness_and_resistance": {
            "weaknesses": monster_config.get("weaknesses", []),
            "damage_type_resistance": monster_config.get("damage_type_resistance", []),
            "debuff_resist": monster_config.get("debuff_resist", []),
        },
        "skill_section": {
            "skill_ids": list(card.skill_ids),
            "skill_slots": list(card.skill_slots),
            "selected_skill_slot": skill_slot,
            "selected_skill_name_chs": _localized(skill_slot.get("display"), "localized_names", "CHS"),
            "selected_skill_name_en": _localized(skill_slot.get("display"), "localized_names", "EN"),
            "trigger_key_one_to_one_required": False,
        },
        "ai_and_sequence": {
            "ai_policy": card.ai_policy,
            "action_sequence": list(card.action_sequence),
            "selected_sequence_step": sequence_step,
            "enemy_turn_runtime_execution_admitted": False,
            "target_selection_admitted": False,
        },
        "action_execution_boundary": {
            "action_set_id": card.action_set_id,
            "linked_action_set": action_set.to_json() if action_set else {},
            "monster_skill_action_definition_from_monster_skill_config_admitted": False,
            "ability_binding_admitted": False,
            "damage_mutation_allowed_from_this_card_in_v0_278": False,
        },
        "raw_parameter_blocks": card.raw_parameter_blocks,
        "source_trace": {
            "card": card.source.to_json(),
            "template": card.source.evidence.get("template_source", {}),
            "skill": skill_slot.get("source_trace", {}),
            "sequence": sequence_step.get("source_trace", {}),
            "ai": card.ai_policy.get("source_trace", {}),
        },
        "monster_data_card_ir": card.to_json(),
    }


def _complete_card_case(example_card: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "has_identity": bool(example_card.get("identity", {}).get("monster_id")),
        "has_display_name": bool(example_card.get("identity", {}).get("display_name_chs"))
        and bool(example_card.get("identity", {}).get("display_name_en")),
        "display_is_marked_non_runtime": example_card.get("identity", {}).get("display", {}).get("runtime_rule_source")
        is False,
        "has_panel_source": bool(example_card.get("panel_source", {}).get("linked_profile")),
        "has_weakness_and_resistance": "weaknesses" in example_card.get("weakness_and_resistance", {}),
        "has_skill_section": bool(example_card.get("skill_section", {}).get("skill_slots")),
        "has_skill_display_name": bool(example_card.get("skill_section", {}).get("selected_skill_name_chs"))
        and bool(example_card.get("skill_section", {}).get("selected_skill_name_en")),
        "has_ai_and_sequence": bool(example_card.get("ai_and_sequence", {}).get("action_sequence")),
        "has_action_execution_boundary": bool(example_card.get("action_execution_boundary", {}).get("linked_action_set")),
        "has_source_trace": all(
            example_card.get("source_trace", {}).get(key)
            for key in ("card", "template", "skill", "sequence", "ai")
        ),
        "does_not_claim_runtime_execution": example_card.get("ai_and_sequence", {}).get(
            "enemy_turn_runtime_execution_admitted"
        )
        is False,
        "does_not_claim_damage_mutation": example_card.get("action_execution_boundary", {}).get(
            "damage_mutation_allowed_from_this_card_in_v0_278"
        )
        is False,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "selected_monster_id": example_card.get("identity", {}).get("monster_id", ""),
        "example_card": example_card,
    }


def _monster_action_set_source_mismatch_case(rules: RuleBook, card: MonsterDataCardIR) -> dict[str, Any]:
    action_set = rules.combatant_action_set(card.entity_ref)
    first_action = {}
    if action_set is not None:
        first_action = action_set.skill_index_map.get("0")
        if not isinstance(first_action, dict):
            first_action = {}
    action_ref = str(first_action.get("action_ref") or "")
    skill_id = action_ref.split(":", 1)[1] if ":" in action_ref else ""
    ordinary_definition = rules.action_definition(action_ref, 1) if action_ref else None
    ilbattle_definition = rules.action_definition(f"ilbattle_monster_skill:{skill_id}", 1) if skill_id else None
    checks = {
        "action_set_exists": action_set is not None,
        "action_set_uses_ordinary_monster_skill_namespace": action_ref.startswith("monster_skill:"),
        "monster_skill_action_admitted_from_ordinary_source": first_action.get("coverage_status") == "executable",
        "ordinary_action_definition_source_is_monster_skill_config": bool(
            ordinary_definition
            and ordinary_definition.source.source_path
            in {"ExcelOutput/MonsterSkillConfig.json", "ExcelOutput/MonsterSkillUniqueConfig.json"}
        ),
        "ilbattle_collision_kept_in_separate_namespace": ilbattle_definition is None
        or ilbattle_definition.action_id.startswith("ilbattle_monster_skill:"),
        "action_set_does_not_use_ilbattle_namespace": not action_ref.startswith("ilbattle_monster_skill:"),
        "card_skill_source_is_monster_skill_config": card.skill_slots[0].get("source_trace", {}).get("source_path")
        in {"ExcelOutput/MonsterSkillConfig.json", "ExcelOutput/MonsterSkillUniqueConfig.json"},
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "selected_monster_id": card.monster_id,
        "action_set": action_set.to_json() if action_set else {},
        "first_action_set_slot": first_action,
        "ordinary_definition_source": ordinary_definition.source.to_json() if ordinary_definition else {},
        "ilbattle_definition_source": ilbattle_definition.source.to_json() if ilbattle_definition else {},
    }


def _select_simple_sequence_card(rules: RuleBook) -> MonsterDataCardIR:
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
        if monster_config.get("custom_values") or monster_config.get("dynamic_values"):
            continue
        if monster_config.get("override_skill_params") or monster_config.get("ability_name_list"):
            continue
        step = card.action_sequence[0]
        if step.get("in_skill_list") is True and step.get("skill_definition_exists") is True:
            return card
    raise RuntimeError("simple sequence monster card sample not found")


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
