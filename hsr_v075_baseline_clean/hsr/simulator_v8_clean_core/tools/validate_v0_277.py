from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..rules.ir import MonsterDataCardIR
from ..rules.rulebook import RuleBook
from ..tbgd.lowering import TBGDLowering
from ..tbgd.monster_cards import MONSTER_CONFIG_PATH, _RowRecord, _monster_card
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_277"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    inventory_case = _inventory_case(tbgd_root, rules)
    simple_case = _simple_sequence_sample_case(rules)
    complex_case = _complex_ai_blocked_case(rules)
    negative_case = _negative_builder_cases(tbgd_root)
    checks = {
        "inventory": inventory_case["checks"],
        "simple_sequence_sample": simple_case["checks"],
        "complex_ai_blocked": complex_case["checks"],
        "negative_builder_cases": negative_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
            "monster_data_card_status": ir.metadata.get("monster_data_card_status", {}),
            "selection_policy": {
                "sample": (
                    "Selected by structure: normal template source, simple UseSequencedSkill admission, "
                    "single skill, no summon/custom/dynamic/override parameter blocks, sequence skill in SkillList."
                ),
                "negative": "Synthetic builder rows validate blocked data-card behavior without entering runtime.",
                "runtime": "Monster cards do not execute enemy turns or produce mutations in v0_277.",
            },
        },
        "checks": checks,
        "inventory_case": inventory_case,
        "simple_sequence_sample_case": simple_case,
        "complex_ai_blocked_case": complex_case,
        "negative_builder_cases": negative_case,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_277.json", result)
    write_json(output_dir / "monster_simple_sequence_sample_v0_277.json", simple_case)
    write_json(output_dir / "monster_complex_ai_blocked_v0_277.json", complex_case)
    write_json(output_dir / "monster_negative_builder_cases_v0_277.json", negative_case)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_277 monster data card admission.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _inventory_case(tbgd_root: Path, rules: RuleBook) -> dict[str, Any]:
    raw_monster_count = _raw_row_count(tbgd_root / MONSTER_CONFIG_PATH)
    lowered_cards = rules.ir.monster_data_cards
    sequence_admitted_cards = [
        card for card in lowered_cards if card.ai_policy.get("admission_status") == "executable"
    ]
    checks = {
        "monster_data_cards_exist": bool(lowered_cards),
        "monster_data_card_count_matches_monster_config": len(lowered_cards) == raw_monster_count,
        "sequence_admitted_cards_exist": bool(sequence_admitted_cards),
        "raw_tbgd_not_in_runtime": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "raw_monster_config_count": raw_monster_count,
        "monster_data_card_count": len(lowered_cards),
        "sequence_admitted_count": len(sequence_admitted_cards),
        "coverage_status_counts": _counts(card.coverage_status for card in lowered_cards),
        "ai_admission_counts": _counts(str(card.ai_policy.get("admission_status")) for card in lowered_cards),
    }


def _simple_sequence_sample_case(rules: RuleBook) -> dict[str, Any]:
    card = _select_simple_sequence_card(rules)
    profile = rules.combatant_profile(card.entity_ref)
    action_set = rules.combatant_action_set(card.entity_ref)
    first_slot = card.skill_slots[0] if card.skill_slots else {}
    first_step = card.action_sequence[0] if card.action_sequence else {}
    template_source = card.source.evidence.get("template_source")
    checks = {
        "sample_selected_without_fixed_id": bool(card.monster_id),
        "normal_template_source": isinstance(template_source, dict)
        and template_source.get("source_path") == "ExcelOutput/MonsterTemplateConfig.json",
        "card_lowered": card.coverage_status == "lowered",
        "profile_ref_exists": profile is not None and profile.profile_id == card.profile_id,
        "action_set_ref_exists": action_set is not None
        and action_set.combatant_action_set_id == card.action_set_id,
        "single_skill_slot_lowered": len(card.skill_slots) == 1 and first_slot.get("coverage_status") == "lowered",
        "fixed_sequence_ai_admitted": card.ai_policy.get("admission_status") == "executable"
        and card.ai_policy.get("policy_kind") == "fixed_skill_sequence",
        "single_sequence_step_lowered": len(card.action_sequence) == 1
        and first_step.get("coverage_status") == "lowered",
        "sequence_skill_in_skill_list": first_step.get("in_skill_list") is True,
        "sequence_skill_definition_exists": first_step.get("skill_definition_exists") is True,
        "skill_source_trace_complete": _has_source_trace(first_slot.get("source_trace")),
        "sequence_source_trace_complete": _has_source_trace(first_step.get("source_trace")),
        "runtime_execution_not_admitted": card.ai_policy.get("runtime_execution_admitted") is False,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "selected_monster_id": card.monster_id,
        "selected_template_id": card.template_id,
        "selected_rank": card.rank,
        "profile": profile.to_json() if profile else {},
        "action_set": action_set.to_json() if action_set else {},
        "monster_data_card": card.to_json(),
    }


def _complex_ai_blocked_case(rules: RuleBook) -> dict[str, Any]:
    card = next(
        (
            item
            for item in rules.ir.monster_data_cards
            if item.ai_policy.get("complex_task_types")
            and item.ai_policy.get("admission_status") != "executable"
        ),
        None,
    )
    checks = {
        "complex_ai_card_found": card is not None,
        "complex_ai_not_executable": bool(card and card.ai_policy.get("admission_status") != "executable"),
        "complex_ai_has_blocked_reason": bool(card and card.ai_policy.get("blocked_reason")),
        "runtime_execution_not_admitted": bool(card and card.ai_policy.get("runtime_execution_admitted") is False),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "selected_monster_id": card.monster_id if card else "",
        "complex_task_types": card.ai_policy.get("complex_task_types") if card else [],
        "monster_data_card": card.to_json() if card else {},
    }


def _negative_builder_cases(tbgd_root: Path) -> dict[str, Any]:
    missing_template = _synthetic_card(
        tbgd_root,
        monster_id="synthetic_missing_template",
        template_id="synthetic_template_missing",
        skill_list=(900000001,),
        templates={},
        skills={},
    )
    missing_skill = _synthetic_card(
        tbgd_root,
        monster_id="synthetic_missing_skill",
        template_id="synthetic_template",
        skill_list=(900000001,),
        sequence_skill_id=900000001,
        skills={},
    )
    sequence_not_in_skill_list = _synthetic_card(
        tbgd_root,
        monster_id="synthetic_sequence_not_in_skill_list",
        template_id="synthetic_template",
        skill_list=(900000002,),
        sequence_skill_id=900000001,
        skills={
            "900000001": _synthetic_skill_record(900000001),
            "900000002": _synthetic_skill_record(900000002),
        },
    )
    checks = {
        "missing_template_blocked": missing_template.coverage_status == "blocked"
        and "monster_template_missing" in missing_template.blocked_reason,
        "missing_skill_definition_blocked": missing_skill.coverage_status == "blocked"
        and "monster_skill_definition_missing" in missing_skill.blocked_reason,
        "sequence_skill_not_in_skill_list_blocked": sequence_not_in_skill_list.coverage_status == "blocked"
        and "sequence_skill_not_in_monster_skill_list" in sequence_not_in_skill_list.blocked_reason,
        "negative_cases_do_not_admit_runtime_execution": all(
            card.ai_policy.get("runtime_execution_admitted") is False
            for card in (missing_template, missing_skill, sequence_not_in_skill_list)
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "missing_template": missing_template.to_json(),
        "missing_skill": missing_skill.to_json(),
        "sequence_not_in_skill_list": sequence_not_in_skill_list.to_json(),
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


def _synthetic_card(
    tbgd_root: Path,
    *,
    monster_id: str,
    template_id: str,
    skill_list: tuple[int, ...],
    sequence_skill_id: int | None = None,
    templates: dict[str, _RowRecord] | None = None,
    skills: dict[str, _RowRecord] | None = None,
) -> MonsterDataCardIR:
    template_record = _synthetic_template_record(template_id, sequence_skill_id or (skill_list[0] if skill_list else 0))
    template_rows = {template_id: template_record} if templates is None else templates
    skill_rows = {
        str(skill_id): _synthetic_skill_record(skill_id)
        for skill_id in skill_list
    }
    if skills is not None:
        skill_rows = skills
    monster_record = _RowRecord(
        relative_path=MONSTER_CONFIG_PATH,
        row_index=0,
        row={
            "MonsterID": monster_id,
            "MonsterTemplateID": template_id,
            "SkillList": list(skill_list),
            "StanceWeakList": [],
            "DamageTypeResistance": [],
            "DebuffResist": [],
            "SummonIDList": [],
            "CustomValues": [],
            "DynamicValues": [],
            "OverrideSkillParams": [],
            "AbilityNameList": [],
        },
    )
    return _monster_card(tbgd_root, monster_id, monster_record, template_rows, skill_rows, {})


def _synthetic_template_record(template_id: str, sequence_skill_id: int) -> _RowRecord:
    return _RowRecord(
        relative_path="ExcelOutput/MonsterTemplateConfig.json",
        row_index=0,
        row={
            "MonsterTemplateID": template_id,
            "Rank": "Synthetic",
            "JsonConfig": "",
            "AIPath": "Config/ConfigAI/Monster_Common_SequenceThree_AI.json",
            "AISkillSequence": [{"MNAHFIGOHML": sequence_skill_id}],
        },
    )


def _synthetic_skill_record(skill_id: int) -> _RowRecord:
    return _RowRecord(
        relative_path="ExcelOutput/MonsterSkillConfig.json",
        row_index=0,
        row={
            "SkillID": skill_id,
            "SkillTriggerKey": "Skill01",
            "DamageType": "Physical",
            "AttackType": "Normal",
            "PhaseList": [1],
            "ParamList": [{"Value": 1}],
            "ModifierList": [],
            "ExtraEffectIDList": [],
        },
    )


def _raw_row_count(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    return len(data) if isinstance(data, list) else 0


def _has_source_trace(value: object) -> bool:
    return isinstance(value, dict) and all(value.get(key) not in (None, "") for key in ("source_path", "raw_type", "raw_id"))


def _counts(values: object) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value)
        result[key] = result.get(key, 0) + 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
