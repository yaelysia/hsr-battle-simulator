from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..rules.ir import IRSource, JSONValue, MonsterDataCardIR, PassiveMechanismSlotIR, SkillFormulaBindingIR


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
    skill_formula_bindings: list[SkillFormulaBindingIR]
    passive_mechanism_slots: list[PassiveMechanismSlotIR]


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
    ability_name_index = _monster_ability_name_index(tbgd_root)

    cards: list[MonsterDataCardIR] = []
    skill_formula_bindings: dict[str, SkillFormulaBindingIR] = {}
    passive_mechanism_slots: dict[str, PassiveMechanismSlotIR] = {}
    for monster_id, monster_record in sorted(monster_rows.items()):
        passive_slots = _passive_slots_for_monster(monster_id, monster_record, ability_name_index)
        for slot in passive_slots:
            passive_mechanism_slots.setdefault(slot.passive_slot_id, slot)
        card = _monster_card(
            tbgd_root,
            monster_id,
            monster_record,
            template_rows,
            skill_rows,
            text_maps,
            passive_slot_ids=tuple(slot.passive_slot_id for slot in passive_slots),
        )
        cards.append(card)
        for binding in _skill_formula_bindings_for_monster(
            tbgd_root,
            card=card,
            monster_record=monster_record,
            template_record=template_rows.get(card.template_id),
            skill_rows=skill_rows,
        ):
            skill_formula_bindings.setdefault(binding.binding_id, binding)
    return MonsterCardBuildResult(
        monster_data_cards=cards,
        skill_formula_bindings=list(skill_formula_bindings.values()),
        passive_mechanism_slots=list(passive_mechanism_slots.values()),
    )


def _monster_card(
    tbgd_root: Path,
    monster_id: str,
    monster_record: _RowRecord,
    template_rows: dict[str, _RowRecord],
    skill_rows: dict[str, _RowRecord],
    text_maps: dict[str, dict[str, str]],
    passive_slot_ids: tuple[str, ...] = (),
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
                "builder": "monster_data_card_v0_281",
                "runtime_execution_admitted": False,
                "manual_route_action_execution_admitted": "depends_on_action_ir",
                "enemy_ai_runtime_execution_admitted": False,
            },
        ),
        coverage_status="blocked" if blocked_reasons else "lowered",
        blocked_reason=";".join(blocked_reasons),
        schema_version="v0_281",
        passive_mechanism_slot_ids=passive_slot_ids,
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


def _monster_ability_name_index(tbgd_root: Path) -> dict[str, tuple[str, ...]]:
    root = tbgd_root / "Config/ConfigAbility/Monster"
    indexed: dict[str, list[str]] = {}
    if not root.exists():
        return {}
    for path in sorted(root.rglob("*.json")):
        if path.name.endswith(".layout.json"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        ability_list = data.get("AbilityList")
        if not isinstance(ability_list, list):
            continue
        relative = path.relative_to(tbgd_root).as_posix()
        for ability in ability_list:
            if not isinstance(ability, dict):
                continue
            name = ability.get("Name") or ability.get("AbilityName")
            if isinstance(name, str) and name:
                indexed.setdefault(name, []).append(relative)
    return {name: tuple(paths) for name, paths in indexed.items()}


def _passive_slots_for_monster(
    monster_id: str,
    monster_record: _RowRecord,
    ability_name_index: dict[str, tuple[str, ...]],
) -> list[PassiveMechanismSlotIR]:
    raw_abilities = monster_record.row.get("AbilityNameList")
    if not isinstance(raw_abilities, list):
        return []
    slots: list[PassiveMechanismSlotIR] = []
    card_id = f"monster_data_card:monster:{monster_id}"
    owner_entity_ref = f"monster:{monster_id}"
    for index, raw_name in enumerate(raw_abilities):
        ability_name = raw_name if isinstance(raw_name, str) else ""
        paths = tuple(sorted(ability_name_index.get(ability_name, ()))) if ability_name else ()
        blocked_reason = ""
        if not ability_name:
            blocked_reason = "monster_passive_ability_name_invalid"
        elif not paths:
            blocked_reason = "monster_passive_ability_missing"
        elif len(paths) > 1:
            blocked_reason = "monster_passive_ability_ambiguous"
        source = IRSource(
            source_path=monster_record.relative_path,
            raw_type=Path(monster_record.relative_path).stem,
            raw_id=monster_id,
            evidence={
                "row_index": monster_record.row_index,
                "raw_path": f"AbilityNameList[{index}]",
                "ability_name": ability_name,
                "ability_file_paths": list(paths),
                "ability_resolution_status": "unique" if len(paths) == 1 else "blocked",
                "builder": "monster_passive_slot_v0_281",
            },
        )
        slot_id = f"passive_mechanism_slot:monster:{monster_id}:ability:{index}:{_safe_id(ability_name)}"
        slots.append(
            PassiveMechanismSlotIR(
                passive_slot_id=slot_id,
                data_card_id=card_id,
                data_card_kind="monster",
                owner_entity_ref=owner_entity_ref,
                mechanism_kind="monster_ability_list_passive",
                runtime_system="startup_status_system",
                linked_ir_ids={
                    "monster_id": monster_id,
                    "ability_name": ability_name,
                    "ability_file_path": paths[0] if len(paths) == 1 else "",
                    "ability_file_paths": list(paths),
                },
                activation={
                    "kind": "monster_passive_startup_ability_candidate",
                    "source_field": "AbilityNameList",
                    "source_index": index,
                    "default_enabled": True,
                    "callback_kind": "OnStart",
                },
                semantics={
                    "ability_name": ability_name,
                    "ability_file_paths": list(paths),
                    "admission_policy": "only_root_on_start_add_modifier_without_dynamic_or_event_trigger_v0_281",
                    "event_trigger_execution_admitted": False,
                    "source_field": "AbilityNameList",
                },
                source=source,
                coverage_status="blocked" if blocked_reason else "lowered",
                blocked_reason=blocked_reason,
            )
        )
    return slots


def _skill_formula_bindings_for_monster(
    tbgd_root: Path,
    *,
    card: MonsterDataCardIR,
    monster_record: _RowRecord,
    template_record: _RowRecord | None,
    skill_rows: dict[str, _RowRecord],
) -> list[SkillFormulaBindingIR]:
    if template_record is None:
        return []
    json_config = str(template_record.row.get("JsonConfig") or "")
    character_config = _read_json_dict(tbgd_root, json_config)
    if character_config is None:
        return []
    dynamic_values = _skill_param_dynamic_values_by_trigger(character_config, json_config)
    bindings: list[SkillFormulaBindingIR] = []
    for skill_index, skill_id in enumerate(card.skill_ids):
        skill_record = skill_rows.get(skill_id)
        if skill_record is None:
            continue
        row = skill_record.row
        trigger_key = str(row.get("SkillTriggerKey") or "")
        param_list = row.get("ParamList") if isinstance(row.get("ParamList"), list) else []
        dynamic_by_index = dynamic_values.get(trigger_key, {})
        if not trigger_key or not dynamic_by_index:
            continue
        level = int(_number_value(row.get("Level"), 1.0))
        action_refs: list[tuple[str, int, str, str]] = [
            (f"monster_skill:{skill_id}", level, "monster_skill_action", ""),
        ]
        for ability_name in _standalone_ability_names_for_trigger(character_config, trigger_key):
            action_refs.append(
                (
                    f"standalone_ability:{ability_name}",
                    0,
                    "monster_skill_trigger_standalone_ability",
                    ability_name,
                )
            )
        for param_index, dynamic_source in sorted(dynamic_by_index.items()):
            param_value = param_list[param_index] if 0 <= param_index < len(param_list) else None
            blocked_reason = ""
            if param_index < 0:
                blocked_reason = "monster_skill_param_index_invalid"
            elif param_index >= len(param_list):
                blocked_reason = "monster_skill_param_index_out_of_range"
            elif not isinstance(_value_field(param_value), (int, float)):
                blocked_reason = "monster_skill_param_value_not_numeric"
            for action_id, action_level, action_source_kind, standalone_ability_name in action_refs:
                source = IRSource(
                    source_path=json_config,
                    raw_type="MonsterSkillFormulaBinding",
                    raw_id=skill_id,
                    evidence={
                        "monster_id": card.monster_id,
                        "monster_data_card_id": card.card_id,
                        "owner_entity_ref": card.entity_ref,
                        "monster_source": _source_trace(monster_record),
                        "template_source": _source_trace(template_record),
                        "skill_source": _source_trace(skill_record),
                        "skill_index": skill_index,
                        "skill_trigger_key": trigger_key,
                        "action_source_kind": action_source_kind,
                        "standalone_ability_name": standalone_ability_name,
                        "param_ref": f"ParamList[{param_index}]",
                        "param_value": _json_safe(param_value),
                        "dynamic_hash": dynamic_source.get("hash"),
                        "dynamic_value_source": dynamic_source,
                        "basis_source_kind": "tbgd_opcode_semantics:DamageByAttackProperty",
                        "builder": "monster_skill_formula_binding_v0_282",
                    },
                )
                if blocked_reason:
                    scaling_basis_expr: dict[str, JSONValue] = {
                        "kind": "missing",
                        "supported": False,
                        "reason": blocked_reason,
                        "source_trace": source.to_json(),
                    }
                else:
                    scaling_basis_expr = {
                        "kind": "unit_stat",
                        "unit_ref": "attacker",
                        "stat": "attack",
                        "source_kind": "monster_damage_by_attack_property_opcode_admission",
                        "admission_status": "executable",
                        "data_card_id": card.card_id,
                        "data_card_kind": "monster",
                        "owner_entity_ref": card.entity_ref,
                        "param_index": param_index,
                        "param_value": _json_safe(param_value),
                        "dynamic_hash": dynamic_source.get("hash"),
                        "raw_opcode": "DamageByAttackProperty",
                        "source_trace": source.to_json(),
                    }
                bindings.append(
                    SkillFormulaBindingIR(
                        binding_id=(
                            f"skill_formula_binding:{action_id}:{action_level}:"
                            f"direct_damage:param:{param_index}:monster"
                        ),
                        character_data_card_id="",
                        data_card_id=card.card_id,
                        data_card_kind="monster",
                        owner_entity_ref=card.entity_ref,
                        formula_slot_id=f"formula_slot:{action_id}:{action_level}:direct_damage:monster:{param_index}",
                        action_id=action_id,
                        level=action_level,
                        param_index=param_index,
                        sequence_order=param_index,
                        formula_role="direct_damage",
                        target_group_hint="",
                        param_value=_json_safe(param_value),
                        scaling_basis_expr=scaling_basis_expr,
                        text_hash="",
                        skill_text="",
                        matched_text="DamageByAttackProperty.DamagePercentage",
                        source=source,
                        coverage_status="blocked" if blocked_reason else "executable",
                        blocked_reason=blocked_reason,
                    )
                )
    return bindings


def _skill_param_dynamic_values_by_trigger(
    character_config: dict[str, Any],
    source_path: str,
) -> dict[str, dict[int, dict[str, JSONValue]]]:
    floats = character_config.get("DynamicValues", {}).get("Floats", {})
    if not isinstance(floats, dict):
        return {}
    result: dict[str, dict[int, dict[str, JSONValue]]] = {}
    for raw_hash, item in floats.items():
        if not isinstance(item, dict):
            continue
        read_info = item.get("ReadInfo")
        if not isinstance(read_info, dict):
            continue
        if read_info.get("Type") != "SkillParam":
            continue
        trigger_key = str(read_info.get("TriggerKey") or "")
        index = read_info.get("Index")
        if not trigger_key or not isinstance(index, int):
            continue
        result.setdefault(trigger_key, {})[index] = {
            "hash": str(raw_hash),
            "param_index": index,
            "trigger_key": trigger_key,
            "read_info": _json_safe(read_info),
            "source_path": source_path,
            "raw_path": f"DynamicValues.Floats[{raw_hash}].ReadInfo",
        }
    return result


def _standalone_ability_names_for_trigger(character_config: dict[str, Any], trigger_key: str) -> tuple[str, ...]:
    names: list[str] = []
    skill_entry = _skill_entry_for_trigger(character_config, trigger_key)
    if isinstance(skill_entry, dict):
        names.extend(_ability_names_from_value(skill_entry.get("EntryAbility")))
    skill_ability_list = character_config.get("SkillAbilityList")
    matched: Any = None
    if isinstance(skill_ability_list, dict):
        matched = skill_ability_list.get(trigger_key)
        if matched is None:
            for key, value in skill_ability_list.items():
                if str(key) == trigger_key:
                    matched = value
                    break
    elif isinstance(skill_ability_list, list):
        for item in skill_ability_list:
            if not isinstance(item, dict):
                continue
            item_keys = {
                str(item.get("Name") or ""),
                str(item.get("SkillName") or ""),
                str(item.get("Skill") or ""),
                str(item.get("SkillTriggerKey") or ""),
            }
            if trigger_key in item_keys:
                matched = item
                break
    names.extend(_ability_names_from_value(matched))
    return tuple(dict.fromkeys(name for name in names if name))


def _skill_entry_for_trigger(character_config: dict[str, Any], trigger_key: str) -> dict[str, Any] | None:
    skill_list = character_config.get("SkillList")
    if isinstance(skill_list, list):
        for item in skill_list:
            if not isinstance(item, dict):
                continue
            names = {
                str(item.get("Name") or ""),
                str(item.get("SkillName") or ""),
                str(item.get("Skill") or ""),
                str(item.get("SkillTriggerKey") or ""),
            }
            if trigger_key in names:
                return item
    if isinstance(skill_list, dict):
        item = skill_list.get(trigger_key)
        if isinstance(item, dict):
            return item
        for key, value in skill_list.items():
            if str(key) == trigger_key and isinstance(value, dict):
                return value
    return None


def _ability_names_from_value(value: Any) -> list[str]:
    names: list[str] = []
    if isinstance(value, str):
        names.append(value)
    elif isinstance(value, list):
        for item in value:
            names.extend(_ability_names_from_value(item))
    elif isinstance(value, dict):
        for key in ("AbilityName", "Name", "PhaseAbility", "PhaseAbilityName", "EntryAbility"):
            item = value.get(key)
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                nested = _value_field(item)
                if isinstance(nested, str):
                    names.append(nested)
        for key in ("AbilityList", "AbilityNameList", "PhaseList", "PhaseAbilityList"):
            names.extend(_ability_names_from_value(value.get(key)))
        if not names:
            for item in value.values():
                names.extend(_ability_names_from_value(item))
    return names


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
            "manual_route_action_execution_admitted": "depends_on_action_ir",
            "enemy_ai_runtime_execution_admitted": False,
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
            "manual_route_action_execution_admitted": "depends_on_action_ir",
            "enemy_ai_runtime_execution_admitted": False,
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
            "manual_route_action_execution_admitted": "depends_on_action_ir",
            "enemy_ai_runtime_execution_admitted": False,
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
        "manual_route_action_execution_admitted": "depends_on_action_ir",
        "enemy_ai_runtime_execution_admitted": False,
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
        "schema_version": "v0_281",
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
            "manual_route_action_execution_admitted": "depends_on_action_ir",
            "enemy_ai_runtime_execution_admitted": False,
        },
        "skill_policy": {
            "skill_list_order_preserved": True,
            "skill_trigger_key_one_to_one_required": False,
            "sequence_skill_must_have_skill_definition": True,
            "sequence_skill_must_be_in_skill_list": True,
        },
        "passive_policy": {
            "passive_source_field": "MonsterConfig.AbilityNameList",
            "skill_modifier_list_is_not_passive_source": True,
            "first_executable_scope": "root OnStart AddModifier only",
            "event_trigger_execution_admitted": False,
            "complex_passive_execution_allowed": False,
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


def _read_json_dict(tbgd_root: Path, relative_path: str) -> dict[str, Any] | None:
    path = tbgd_root / relative_path
    if not relative_path or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


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


def _safe_id(value: str) -> str:
    text = "".join(ch if ch.isalnum() else "_" for ch in str(value))
    text = "_".join(part for part in text.split("_") if part)
    return text[:160] or "missing"


def _number_value(value: Any, default: float) -> float:
    if isinstance(value, dict):
        nested = value.get("Value")
        return _number_value(nested, default)
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _value_field(value: Any) -> Any:
    if isinstance(value, dict) and "Value" in value:
        return _json_safe(value.get("Value"))
    return _json_safe(value)


def _json_safe(value: Any) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)
