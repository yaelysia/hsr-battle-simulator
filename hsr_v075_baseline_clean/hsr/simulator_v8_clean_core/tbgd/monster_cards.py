from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..rules.ir import IRSource, JSONValue, MonsterDataCardIR


MONSTER_CONFIG_PATH = "ExcelOutput/MonsterConfig.json"
MONSTER_TEMPLATE_PATHS: tuple[str, ...] = (
    "ExcelOutput/MonsterTemplateConfig.json",
    "ExcelOutput/MonsterTemplateUniqueConfig.json",
)
MONSTER_SKILL_PATHS: tuple[tuple[str, str], ...] = (
    ("ExcelOutput/MonsterSkillConfig.json", "SkillID"),
    ("ExcelOutput/MonsterSkillUniqueConfig.json", "SkillID"),
)
DISPLAY_TEXT_MAPS: tuple[tuple[str, str], ...] = (
    ("CHS", "TextMap/TextMapCHS.json"),
    ("EN", "TextMap/TextMapEN.json"),
)

SEQUENCED_SKILL_TASK = "RPG.GameCore.UseSequencedSkill"
COMPLEX_AI_TASKS: frozenset[str] = frozenset(
    {
        "RPG.GameCore.UseSkill",
        "RPG.GameCore.SelectAISkillTarget",
        "RPG.GameCore.AIStepperDecisionGroupConfig",
        "RPG.GameCore.RandomConfig",
        "RPG.GameCore.ByRandomChance",
        "RPG.GameCore.CheckSkillUsabilityAxis",
    }
)


@dataclass(frozen=True)
class MonsterCardBuildResult:
    monster_data_cards: list[MonsterDataCardIR]


@dataclass(frozen=True)
class _RowRecord:
    relative_path: str
    row_index: int
    row: dict[str, Any]


def build_monster_card_ir(
    tbgd_root: Path,
    *,
    max_records_per_table: int | None,
) -> MonsterCardBuildResult:
    monster_rows = _rows_by_id(
        tbgd_root,
        MONSTER_CONFIG_PATH,
        "MonsterID",
        max_records_per_table=max_records_per_table,
    )
    template_rows: dict[str, _RowRecord] = {}
    for relative_path in MONSTER_TEMPLATE_PATHS:
        template_rows.update(
            _rows_by_id(
                tbgd_root,
                relative_path,
                "MonsterTemplateID",
                max_records_per_table=max_records_per_table,
            )
        )
    skill_rows: dict[str, _RowRecord] = {}
    for relative_path, id_key in MONSTER_SKILL_PATHS:
        skill_rows.update(
            _rows_by_id(
                tbgd_root,
                relative_path,
                id_key,
                max_records_per_table=max_records_per_table,
            )
        )
    text_maps = _load_display_text_maps(tbgd_root)

    cards: list[MonsterDataCardIR] = []
    for monster_id, monster_record in sorted(monster_rows.items()):
        cards.append(_monster_card(tbgd_root, monster_id, monster_record, template_rows, skill_rows, text_maps))
    return MonsterCardBuildResult(monster_data_cards=cards)


def _monster_card(
    tbgd_root: Path,
    monster_id: str,
    monster_record: _RowRecord,
    template_rows: dict[str, _RowRecord],
    skill_rows: dict[str, _RowRecord],
    text_maps: dict[str, dict[str, str]],
) -> MonsterDataCardIR:
    monster_row = monster_record.row
    template_id = str(monster_row.get("MonsterTemplateID") or "")
    template_record = template_rows.get(template_id)
    template_row = template_record.row if template_record else {}
    rank = str(template_row.get("Rank") or "")
    skill_ids = tuple(str(skill_id) for skill_id in monster_row.get("SkillList") or ())
    display = _monster_display(monster_row, template_row, text_maps)
    skill_slots = tuple(_skill_slots(skill_ids, skill_rows, text_maps))
    action_sequence, sequence_status = _action_sequence(monster_record, template_record, skill_ids, skill_rows)
    ai_path = str(monster_row.get("OverrideAIPath") or template_row.get("AIPath") or "")
    ai_policy = _ai_policy(tbgd_root, ai_path)

    blocked_reasons = []
    if template_record is None:
        blocked_reasons.append("monster_template_missing")
    if not skill_ids:
        blocked_reasons.append("monster_skill_list_missing")
    if any(slot.get("coverage_status") == "blocked" for slot in skill_slots):
        blocked_reasons.append("monster_skill_definition_missing")
    if not action_sequence:
        blocked_reasons.append("monster_ai_sequence_missing")
    if sequence_status and sequence_status not in blocked_reasons:
        blocked_reasons.append(sequence_status)
    if ai_policy.get("admission_status") != "executable":
        blocked_reasons.append(str(ai_policy.get("blocked_reason") or "monster_ai_policy_not_admitted"))

    return MonsterDataCardIR(
        card_id=f"monster_data_card:monster:{monster_id}",
        entity_ref=f"monster:{monster_id}",
        monster_id=monster_id,
        template_id=template_id,
        rank=rank,
        display=display,
        profile_id=f"combatant_profile:monster:{monster_id}",
        action_set_id=f"combatant_action_set:monster:{monster_id}",
        skill_ids=skill_ids,
        skill_slots=skill_slots,
        ai_policy=ai_policy,
        action_sequence=tuple(action_sequence),
        summon_refs=tuple(str(item) for item in monster_row.get("SummonIDList") or ()),
        raw_parameter_blocks=_raw_parameter_blocks(monster_row, template_row),
        card_contract=_monster_data_card_contract(),
        source=IRSource(
            source_path=monster_record.relative_path,
            raw_type=Path(monster_record.relative_path).stem,
            raw_id=monster_id,
            evidence={
                "row_index": monster_record.row_index,
                "template_id": template_id,
                "template_source": _source_trace(template_record) if template_record else {},
                "raw_paths": {
                    "template_id": "MonsterTemplateID",
                    "skill_list": "SkillList",
                    "weaknesses": "StanceWeakList",
                    "damage_resistances": "DamageTypeResistance",
                    "debuff_resistances": "DebuffResist",
                    "override_ai_path": "OverrideAIPath",
                    "override_ai_sequence": "OverrideAISkillSequence",
                    "summons": "SummonIDList",
                    "custom_values": "CustomValues",
                    "dynamic_values": "DynamicValues",
                    "override_skill_params": "OverrideSkillParams",
                },
                "builder": "monster_data_card_v0_277",
                "runtime_execution_admitted": False,
            },
        ),
        coverage_status="blocked" if blocked_reasons else "lowered",
        blocked_reason=";".join(blocked_reasons),
    )


def _skill_slots(
    skill_ids: tuple[str, ...],
    skill_rows: dict[str, _RowRecord],
    text_maps: dict[str, dict[str, str]],
) -> list[dict[str, JSONValue]]:
    trigger_key_map: dict[str, list[str]] = {}
    slots: list[dict[str, JSONValue]] = []
    for index, skill_id in enumerate(skill_ids):
        skill_record = skill_rows.get(skill_id)
        if skill_record is None:
            slots.append(
                {
                    "slot_index": index,
                    "skill_id": skill_id,
                    "action_ref": f"monster_skill:{skill_id}",
                    "display": {},
                    "coverage_status": "blocked",
                    "blocked_reason": "monster_skill_definition_missing",
                }
            )
            continue
        row = skill_record.row
        trigger_key = str(row.get("SkillTriggerKey") or "")
        if trigger_key:
            trigger_key_map.setdefault(trigger_key, []).append(skill_id)
        slots.append(
            {
                "slot_index": index,
                "skill_id": skill_id,
                "action_ref": f"monster_skill:{skill_id}",
                "skill_trigger_key": trigger_key,
                "display": _skill_display(row, text_maps),
                "trigger_key_alias_count": len(trigger_key_map.get(trigger_key, ())),
                "damage_type": str(row.get("DamageType") or ""),
                "attack_type": str(row.get("AttackType") or ""),
                "sp_hit_base": _json_safe(row.get("SPHitBase")),
                "delay_ratio": _json_safe(row.get("DelayRatio")),
                "ai_cd": _json_safe(row.get("AI_CD")),
                "ai_icd": _json_safe(row.get("AI_ICD")),
                "phase_list": _json_safe(row.get("PhaseList") or []),
                "param_list": _json_safe(row.get("ParamList") or []),
                "modifier_list": _json_safe(row.get("ModifierList") or []),
                "extra_effect_id_list": _json_safe(row.get("ExtraEffectIDList") or []),
                "is_threat": _json_safe(row.get("IsThreat")),
                "source_trace": _source_trace(skill_record),
                "coverage_status": "lowered",
                "blocked_reason": "",
            }
        )
    trigger_groups: dict[str, list[int]] = {}
    for slot_index, slot in enumerate(slots):
        trigger_key = slot.get("skill_trigger_key")
        if isinstance(trigger_key, str) and trigger_key:
            trigger_groups.setdefault(trigger_key, []).append(slot_index)
    for slot in slots:
        trigger_key = slot.get("skill_trigger_key")
        if isinstance(trigger_key, str) and trigger_key:
            slot["same_trigger_skill_ids"] = [
                str(slots[index].get("skill_id")) for index in trigger_groups.get(trigger_key, ())
            ]
    return slots


def _action_sequence(
    monster_record: _RowRecord,
    template_record: _RowRecord | None,
    skill_ids: tuple[str, ...],
    skill_rows: dict[str, _RowRecord],
) -> tuple[list[dict[str, JSONValue]], str]:
    monster_row = monster_record.row
    override_sequence = monster_row.get("OverrideAISkillSequence")
    template_sequence = template_record.row.get("AISkillSequence") if template_record else []
    if isinstance(override_sequence, list) and override_sequence:
        raw_sequence = override_sequence
        sequence_kind = "monster_override"
        source_trace = {
            "source_path": monster_record.relative_path,
            "raw_type": "MonsterConfig",
            "raw_id": str(monster_row.get("MonsterID") or ""),
            "row_index": monster_record.row_index,
            "raw_path": "OverrideAISkillSequence",
        }
    elif isinstance(template_sequence, list) and template_sequence:
        raw_sequence = template_sequence
        sequence_kind = "template_default"
        source_trace = {
            "source_path": template_record.relative_path if template_record else "",
            "raw_type": Path(template_record.relative_path).stem if template_record else "",
            "raw_id": str(template_record.row.get("MonsterTemplateID") or "") if template_record else "",
            "row_index": template_record.row_index if template_record else None,
            "raw_path": "AISkillSequence",
        }
    else:
        return [], "monster_ai_sequence_missing"

    skill_id_set = set(skill_ids)
    steps: list[dict[str, JSONValue]] = []
    blocked_reasons: list[str] = []
    for sequence_index, raw_item in enumerate(raw_sequence):
        raw_key, skill_id = _sequence_skill_id(raw_item)
        in_skill_list = bool(skill_id and skill_id in skill_id_set)
        skill_definition_exists = bool(skill_id and skill_id in skill_rows)
        step_reasons = []
        if not skill_id:
            step_reasons.append("sequence_skill_id_missing")
        if skill_id and not in_skill_list:
            step_reasons.append("sequence_skill_not_in_monster_skill_list")
        if skill_id and not skill_definition_exists:
            step_reasons.append("sequence_skill_definition_missing")
        blocked_reasons.extend(step_reasons)
        steps.append(
            {
                "sequence_index": sequence_index,
                "sequence_kind": sequence_kind,
                "raw_key": raw_key,
                "raw_item": _json_safe(raw_item),
                "skill_id": skill_id,
                "action_ref": f"monster_skill:{skill_id}" if skill_id else "",
                "skill_list_index": skill_ids.index(skill_id) if in_skill_list else None,
                "in_skill_list": in_skill_list,
                "skill_definition_exists": skill_definition_exists,
                "source_trace": source_trace,
                "coverage_status": "blocked" if step_reasons else "lowered",
                "blocked_reason": ";".join(step_reasons),
            }
        )
    return steps, ";".join(sorted(set(blocked_reasons)))


def _ai_policy(tbgd_root: Path, ai_path: str) -> dict[str, JSONValue]:
    if not ai_path:
        return {
            "ai_path": "",
            "policy_kind": "missing",
            "admission_status": "blocked",
            "coverage_status": "blocked",
            "blocked_reason": "monster_ai_path_missing",
            "runtime_execution_admitted": False,
        }
    path = tbgd_root / ai_path
    if not path.exists():
        return {
            "ai_path": ai_path,
            "policy_kind": "missing_file",
            "admission_status": "blocked",
            "coverage_status": "blocked",
            "blocked_reason": "monster_ai_file_missing",
            "runtime_execution_admitted": False,
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "ai_path": ai_path,
            "policy_kind": "unreadable",
            "admission_status": "blocked",
            "coverage_status": "blocked",
            "blocked_reason": "monster_ai_file_unreadable",
            "runtime_execution_admitted": False,
        }
    task_types = sorted(_collect_task_types(data))
    complex_types = sorted(task_type for task_type in task_types if task_type in COMPLEX_AI_TASKS)
    has_sequence_task = SEQUENCED_SKILL_TASK in task_types
    admission_status = "executable" if has_sequence_task and not complex_types else "blocked"
    blocked_reason = "" if admission_status == "executable" else "monster_ai_policy_not_simple_sequence"
    return {
        "ai_path": ai_path,
        "ai_name": str(data.get("AIName") or "") if isinstance(data, dict) else "",
        "policy_kind": "fixed_skill_sequence" if admission_status == "executable" else "complex_or_unsupported_ai",
        "admitted_task": SEQUENCED_SKILL_TASK if admission_status == "executable" else "",
        "task_types": task_types,
        "complex_task_types": complex_types,
        "admission_status": admission_status,
        "coverage_status": "lowered" if admission_status == "executable" else "blocked",
        "blocked_reason": blocked_reason,
        "source_trace": {
            "source_path": ai_path,
            "raw_type": "ConfigAI",
            "raw_id": Path(ai_path).stem,
        },
        "runtime_execution_admitted": False,
    }


def _raw_parameter_blocks(monster_row: dict[str, Any], template_row: dict[str, Any]) -> dict[str, JSONValue]:
    return {
        "monster_config": {
            "hard_level_group": _json_safe(monster_row.get("HardLevelGroup")),
            "attack_modify_ratio": _json_safe(monster_row.get("AttackModifyRatio")),
            "defense_modify_ratio": _json_safe(monster_row.get("DefenceModifyRatio")),
            "hp_modify_ratio": _json_safe(monster_row.get("HPModifyRatio")),
            "speed_modify_ratio": _json_safe(monster_row.get("SpeedModifyRatio")),
            "stance_modify_ratio": _json_safe(monster_row.get("StanceModifyRatio")),
            "stance_modify_value": _json_safe(monster_row.get("StanceModifyValue")),
            "speed_modify_value": _json_safe(monster_row.get("SpeedModifyValue")),
            "weaknesses": _json_safe(monster_row.get("StanceWeakList") or []),
            "damage_type_resistance": _json_safe(monster_row.get("DamageTypeResistance") or []),
            "debuff_resist": _json_safe(monster_row.get("DebuffResist") or []),
            "custom_value_tags": _json_safe(monster_row.get("CustomValueTags") or []),
            "custom_values": _json_safe(monster_row.get("CustomValues") or []),
            "dynamic_values": _json_safe(monster_row.get("DynamicValues") or []),
            "override_skill_params": _json_safe(monster_row.get("OverrideSkillParams") or []),
            "ability_name_list": _json_safe(monster_row.get("AbilityNameList") or []),
        },
        "template_config": {
            "rank": str(template_row.get("Rank") or ""),
            "json_config": str(template_row.get("JsonConfig") or ""),
            "base_stats": {
                "attack": _json_safe(template_row.get("AttackBase")),
                "defense": _json_safe(template_row.get("DefenceBase")),
                "hp": _json_safe(template_row.get("HPBase")),
                "speed": _json_safe(template_row.get("SpeedBase")),
                "stance": _json_safe(template_row.get("StanceBase")),
                "critical_damage": _json_safe(template_row.get("CriticalDamageBase")),
                "status_resistance": _json_safe(template_row.get("StatusResistanceBase")),
            },
            "stance_type": str(template_row.get("StanceType") or ""),
            "initial_delay_ratio": _json_safe(template_row.get("InitialDelayRatio")),
            "minimum_fatigue_ratio": _json_safe(template_row.get("MinimumFatigueRatio")),
            "ai_path": str(template_row.get("AIPath") or ""),
            "ai_skill_sequence": _json_safe(template_row.get("AISkillSequence") or []),
        },
    }


def _monster_data_card_contract() -> dict[str, JSONValue]:
    return {
        "schema_version": "v0_277",
        "runtime_boundary": {
            "runtime_reads": "Canonical IR only",
            "raw_tbgd_allowed_in_runtime": False,
            "text_map_allowed_in_runtime": False,
            "monster_name_special_case_allowed": False,
        },
        "display_policy": {
            "display_text_source": "TextMap CHS/EN at card build time only",
            "display_text_allowed_for_runtime_rules": False,
            "display_text_allowed_for_ui_and_audit": True,
            "missing_display_text_blocks_execution": False,
        },
        "ai_policy": {
            "first_admitted_policy": "UseSequencedSkill with TBGD AISkillSequence",
            "complex_ai_execution_allowed": False,
            "target_selection_is_not_admitted": True,
            "runtime_execution_admitted": False,
        },
        "skill_policy": {
            "skill_list_order_preserved": True,
            "skill_trigger_key_one_to_one_required": False,
            "sequence_skill_must_have_skill_definition": True,
            "sequence_skill_must_be_in_skill_list": True,
        },
        "stage_boundary": {
            "stage_level_and_hard_level_group_assembly_admitted": False,
            "stage_binding_deferred": True,
        },
    }


def _monster_display(
    monster_row: dict[str, Any],
    template_row: dict[str, Any],
    text_maps: dict[str, dict[str, str]],
) -> dict[str, JSONValue]:
    name_hash = _hash_value(monster_row.get("MonsterName")) or _hash_value(template_row.get("MonsterName"))
    intro_hash = _hash_value(monster_row.get("MonsterIntroduction"))
    return {
        "display_only": True,
        "runtime_rule_source": False,
        "source": "TextMap CHS/EN loaded in monster card builder",
        "name_hash": name_hash,
        "localized_names": _localized_text(name_hash, text_maps),
        "introduction_hash": intro_hash,
        "localized_introductions": _localized_text(intro_hash, text_maps),
    }


def _skill_display(row: dict[str, Any], text_maps: dict[str, dict[str, str]]) -> dict[str, JSONValue]:
    name_hash = _hash_value(row.get("SkillName"))
    type_hash = _hash_value(row.get("SkillTypeDesc"))
    tag_hash = _hash_value(row.get("SkillTag"))
    desc_hash = _hash_value(row.get("SkillDesc"))
    return {
        "display_only": True,
        "runtime_rule_source": False,
        "source": "TextMap CHS/EN loaded in monster card builder",
        "name_hash": name_hash,
        "localized_names": _localized_text(name_hash, text_maps),
        "type_hash": type_hash,
        "localized_types": _localized_text(type_hash, text_maps),
        "tag_hash": tag_hash,
        "localized_tags": _localized_text(tag_hash, text_maps),
        "description_hash": desc_hash,
        "localized_descriptions": _localized_text(desc_hash, text_maps),
    }


def _load_display_text_maps(tbgd_root: Path) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for locale, relative_path in DISPLAY_TEXT_MAPS:
        path = tbgd_root / relative_path
        if not path.exists():
            result[locale] = {}
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            result[locale] = {}
            continue
        result[locale] = {str(key): str(value) for key, value in data.items()} if isinstance(data, dict) else {}
    return result


def _localized_text(hash_value: str, text_maps: dict[str, dict[str, str]]) -> dict[str, JSONValue]:
    if not hash_value:
        return {}
    return {
        locale: value
        for locale, text_map in text_maps.items()
        if (value := text_map.get(hash_value))
    }


def _hash_value(value: Any) -> str:
    if isinstance(value, dict) and value.get("Hash") is not None:
        return str(value["Hash"])
    return ""


def _rows_by_id(
    tbgd_root: Path,
    relative_path: str,
    id_key: str,
    *,
    max_records_per_table: int | None,
) -> dict[str, _RowRecord]:
    path = tbgd_root / relative_path
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, list):
        return {}
    rows: dict[str, _RowRecord] = {}
    for row_index, row in enumerate(_limit_sequence(data, max_records_per_table)):
        if isinstance(row, dict) and row.get(id_key) is not None:
            rows[str(row[id_key])] = _RowRecord(relative_path=relative_path, row_index=row_index, row=row)
    return rows


def _sequence_skill_id(raw_item: Any) -> tuple[str, str]:
    if not isinstance(raw_item, dict):
        return "", ""
    for key, value in raw_item.items():
        if isinstance(value, (int, str)) and str(value):
            return str(key), str(value)
    return "", ""


def _collect_task_types(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        task_type = value.get("$type")
        if isinstance(task_type, str) and task_type:
            result.add(task_type)
        for item in value.values():
            result.update(_collect_task_types(item))
    elif isinstance(value, list):
        for item in value:
            result.update(_collect_task_types(item))
    return result


def _source_trace(record: _RowRecord | None) -> dict[str, JSONValue]:
    if record is None:
        return {}
    raw_id = ""
    for key in ("MonsterID", "MonsterTemplateID", "SkillID", "ID"):
        if record.row.get(key) is not None:
            raw_id = str(record.row[key])
            break
    return {
        "source_path": record.relative_path,
        "raw_type": Path(record.relative_path).stem,
        "raw_id": raw_id,
        "row_index": record.row_index,
    }


def _limit_sequence(items: list[Any], limit: int | None) -> list[Any]:
    if limit is None:
        return items
    return items[: max(0, limit)]


def _json_safe(value: Any) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)
