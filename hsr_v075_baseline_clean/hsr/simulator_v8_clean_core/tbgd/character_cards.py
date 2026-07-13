from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ..rules.ir import (
    AvatarProfileIR,
    BouncePolicyIR,
    CharacterDataCardIR,
    CharacterEidolonSlotIR,
    CharacterMechanismSlotIR,
    CharacterTraceNodeIR,
    IRSource,
    JSONValue,
    SkillFormulaBindingIR,
)


SkillTableSpec = tuple[str, str, str]


@dataclass(frozen=True)
class CharacterCardBuildResult:
    avatar_profiles: list[AvatarProfileIR]
    character_data_cards: list[CharacterDataCardIR]
    character_mechanism_slots: list[CharacterMechanismSlotIR]
    character_trace_nodes: list[CharacterTraceNodeIR]
    character_eidolon_slots: list[CharacterEidolonSlotIR]
    skill_formula_bindings: list[SkillFormulaBindingIR]
    bounce_policies: list[BouncePolicyIR]


SKILL_TEXT_BASIS_WORDS: dict[str, str] = {
    "攻击力": "attack",
    "生命上限": "max_hp",
    "防御力": "defense",
}

TRACE_STATIC_STAT_PROPERTY_MAP: dict[str, tuple[str, str]] = {
    "AttackAddedRatio": ("base_stat_ratio", "attack"),
    "HPAddedRatio": ("base_stat_ratio", "max_hp"),
    "DefenceAddedRatio": ("base_stat_ratio", "defense"),
    "SpeedDelta": ("base_stat_delta", "speed"),
    "CriticalChanceBase": ("resource_delta", "critical_chance"),
    "CriticalDamageBase": ("resource_delta", "critical_damage"),
    "BreakDamageAddedRatioBase": ("resource_delta", "break_damage_added_ratio"),
    "StatusProbabilityBase": ("resource_delta", "effect_hit_rate"),
    "StatusResistanceBase": ("resource_delta", "effect_resistance"),
    "AllDamageTypeAddedRatio": ("resource_delta", "damage_added_ratio"),
    "PhysicalAddedRatio": ("resource_delta", "Physical_damage_added_ratio"),
    "FireAddedRatio": ("resource_delta", "Fire_damage_added_ratio"),
    "IceAddedRatio": ("resource_delta", "Ice_damage_added_ratio"),
    "ThunderAddedRatio": ("resource_delta", "Thunder_damage_added_ratio"),
    "WindAddedRatio": ("resource_delta", "Wind_damage_added_ratio"),
    "QuantumAddedRatio": ("resource_delta", "Quantum_damage_added_ratio"),
    "ImaginaryAddedRatio": ("resource_delta", "Imaginary_damage_added_ratio"),
    "ElationDamageAddedRatioBase": ("resource_delta", "elation_damage_added_ratio"),
}

SKILL_TEXT_DAMAGE_BINDING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?P<matched>(?:造成|受到|附加|追加)[^。；\n]{0,120}?等同于[^。；\n]{0,80}?"
        r"#(?P<param_index>\d+)(?:\[[^\]]+\])?%?[^。；\n]{0,50}?"
        r"(?P<basis>攻击力|生命上限|防御力)[^。；\n]{0,120}?伤害)"
    ),
    re.compile(
        r"(?P<matched>(?:造成|受到|附加|追加)[^。；\n]{0,120}?等同于[^。；\n]{0,50}?"
        r"(?P<basis>攻击力|生命上限|防御力)[^。；\n]{0,50}?"
        r"#(?P<param_index>\d+)(?:\[[^\]]+\])?%?[^。；\n]{0,120}?伤害)"
    ),
)


def build_character_card_ir(
    tbgd_root: Path,
    *,
    max_records_per_table: int | None,
    skill_tables: tuple[SkillTableSpec, ...],
) -> CharacterCardBuildResult:
    avatar_rows = _avatar_rows(tbgd_root, max_records_per_table=max_records_per_table)
    rank_rows_by_id = _avatar_rank_rows_by_id(tbgd_root, max_records_per_table=max_records_per_table)
    promotion_rows_by_avatar = _promotion_rows_by_avatar(tbgd_root)
    skill_to_card = _skill_to_card_map(avatar_rows)
    avatar_id_to_card = {str(row["AvatarID"]): f"character_data_card:avatar:{row['AvatarID']}" for _, _, row in avatar_rows}
    action_set_by_card = _action_set_by_card(
        tbgd_root,
        skill_tables=skill_tables,
        skill_to_card=skill_to_card,
        max_records_per_table=max_records_per_table,
    )
    text_map = _load_text_map(tbgd_root)
    skill_formula_bindings: list[SkillFormulaBindingIR] = []
    bounce_policies: list[BouncePolicyIR] = []
    skill_param_slots: list[CharacterMechanismSlotIR] = []
    for relative_path, entity_type, id_key in skill_tables:
        skill_formula_bindings.extend(
            _skill_formula_bindings_for_table(
                tbgd_root,
                relative_path=relative_path,
                entity_type=entity_type,
                id_key=id_key,
                text_map=text_map,
                skill_to_card=skill_to_card,
                max_records_per_table=max_records_per_table,
            )
        )
        skill_param_slots.extend(
            _skill_param_slots_for_table(
                tbgd_root,
                relative_path=relative_path,
                entity_type=entity_type,
                id_key=id_key,
                skill_to_card=skill_to_card,
                max_records_per_table=max_records_per_table,
            )
        )
        bounce_policies.extend(
            _bounce_policies_for_table(
                tbgd_root,
                relative_path=relative_path,
                entity_type=entity_type,
                id_key=id_key,
                text_map=text_map,
                skill_to_card=skill_to_card,
                max_records_per_table=max_records_per_table,
            )
        )
    bounce_policy_by_action = {
        (policy.action_id, policy.level): policy.bounce_policy_id
        for policy in bounce_policies
        if policy.coverage_status == "executable"
    }
    skill_formula_bindings = [
        _attach_bounce_policy_to_formula_binding(binding, bounce_policy_by_action)
        for binding in skill_formula_bindings
    ]
    bindings_by_card: dict[str, list[str]] = {}
    for binding in skill_formula_bindings:
        if binding.character_data_card_id:
            bindings_by_card.setdefault(binding.character_data_card_id, []).append(binding.binding_id)
    bounce_policy_ids_by_card: dict[str, list[str]] = {}
    for policy in bounce_policies:
        if policy.character_data_card_id:
            bounce_policy_ids_by_card.setdefault(policy.character_data_card_id, []).append(policy.bounce_policy_id)
    trace_nodes, trace_slots = _trace_nodes_and_slots(
        tbgd_root,
        avatar_id_to_card=avatar_id_to_card,
        dynamic_value_bindings_by_avatar_version=_character_config_dynamic_value_bindings_by_avatar_version(
            tbgd_root,
            max_records_per_table=max_records_per_table,
        ),
        max_records_per_table=max_records_per_table,
    )
    trace_nodes = list({node.trace_node_id: node for node in trace_nodes}.values())
    trace_slots = list({slot.mechanism_slot_id: slot for slot in trace_slots}.values())
    trace_node_ids_by_card: dict[str, list[str]] = {}
    for node in trace_nodes:
        trace_node_ids_by_card.setdefault(node.character_data_card_id, []).append(node.trace_node_id)
    eidolon_slots_by_card: dict[str, list[CharacterEidolonSlotIR]] = {}
    for relative_path, row_index, row in avatar_rows:
        avatar_id = str(row["AvatarID"])
        card_id = f"character_data_card:avatar:{avatar_id}"
        for slot in _eidolon_slots_from_avatar_row(relative_path, row_index, row, card_id, rank_rows_by_id):
            eidolon_slots_by_card.setdefault(card_id, []).append(slot)
    eidolon_slot_ids_by_card = {
        card_id: [slot.eidolon_slot_id for slot in slots] for card_id, slots in eidolon_slots_by_card.items()
    }
    mechanism_slots: list[CharacterMechanismSlotIR] = []
    mechanism_slots.extend(_formula_mechanism_slot(binding) for binding in skill_formula_bindings)
    mechanism_slots.extend(_bounce_mechanism_slot(policy) for policy in bounce_policies)
    mechanism_slots.extend(skill_param_slots)
    mechanism_slots.extend(trace_slots)
    mechanism_slots.extend(
        _eidolon_mechanism_slot(slot)
        for slots in eidolon_slots_by_card.values()
        for slot in slots
        if slot.linked_mechanism_slot_ids
    )
    mechanism_slot_ids_by_card: dict[str, list[str]] = {}
    for slot in mechanism_slots:
        if slot.character_data_card_id:
            mechanism_slot_ids_by_card.setdefault(slot.character_data_card_id, []).append(slot.mechanism_slot_id)
    avatar_profiles: list[AvatarProfileIR] = []
    character_cards: list[CharacterDataCardIR] = []
    for relative_path, row_index, row in avatar_rows:
        avatar_id = str(row["AvatarID"])
        promotion_rows = promotion_rows_by_avatar.get(avatar_id, [])
        profile = _avatar_profile_from_row(relative_path, row_index, row, promotion_rows)
        avatar_profiles.append(profile)
        card_id = f"character_data_card:avatar:{avatar_id}"
        skill_ids = tuple(str(skill_id) for skill_id in row.get("SkillList") or ())
        binding_ids = tuple(sorted(bindings_by_card.get(card_id, ())))
        bounce_policy_ids = tuple(sorted(bounce_policy_ids_by_card.get(card_id, ())))
        blocked_reason = ""
        if profile.coverage_status != "executable":
            blocked_reason = profile.blocked_reason or "avatar_profile_not_executable"
        elif not binding_ids:
            blocked_reason = "character_data_card_has_no_skill_formula_bindings"
        character_cards.append(
            CharacterDataCardIR(
                card_id=card_id,
                entity_ref=f"avatar:{avatar_id}",
                profile_id=profile.avatar_profile_id,
                skill_ids=skill_ids,
                skill_formula_binding_ids=binding_ids,
                bounce_policy_ids=bounce_policy_ids,
                schema_version="v0_267",
                action_set=action_set_by_card.get(card_id, {"skill_ids": list(skill_ids), "actions": []}),
                mechanism_slot_ids=tuple(sorted(mechanism_slot_ids_by_card.get(card_id, ()))),
                trace_node_ids=tuple(sorted(trace_node_ids_by_card.get(card_id, ()))),
                eidolon_slot_ids=tuple(sorted(eidolon_slot_ids_by_card.get(card_id, ()))),
                card_contract=_character_data_card_contract(),
                dynamic_value_bindings=_json_safe(
                    row.get("_character_config_dynamic_value_bindings") or {}
                ),
                source=IRSource(
                    source_path=relative_path,
                    raw_type=Path(relative_path).stem,
                    raw_id=avatar_id,
                    evidence={
                        "row_index": row_index,
                        "skill_list": _json_safe(row.get("SkillList")),
                        "version_kind": str(row.get("_character_card_version_kind") or "base"),
                        "base_source_path": str(row.get("_character_card_base_source_path") or relative_path),
                        "base_row_index": _json_safe(row.get("_character_card_base_row_index")),
                        "base_skill_list": _json_safe(row.get("_character_card_base_skill_list") or []),
                        "enhanced_source_path": str(row.get("_character_card_enhanced_source_path") or ""),
                        "enhanced_row_index": _json_safe(row.get("_character_card_enhanced_row_index")),
                        "enhanced_id": _json_safe(row.get("_character_card_enhanced_id")),
                        "enhanced_skill_list": _json_safe(row.get("_character_card_enhanced_skill_list") or []),
                        "enhanced_overrides_base": str(row.get("_character_card_version_kind") or "base") == "enhanced",
                        "character_config_dynamic_value_bindings": _json_safe(
                            row.get("_character_config_dynamic_value_bindings") or {}
                        ),
                        "profile_id": profile.avatar_profile_id,
                        "skill_formula_binding_count": len(binding_ids),
                        "bounce_policy_count": len(bounce_policy_ids),
                        "mechanism_slot_count": len(mechanism_slot_ids_by_card.get(card_id, ())),
                        "trace_node_count": len(trace_node_ids_by_card.get(card_id, ())),
                        "eidolon_slot_count": len(eidolon_slot_ids_by_card.get(card_id, ())),
                        "builder": "character_data_card_v0_265",
                    },
                ),
                coverage_status="blocked" if blocked_reason else "executable",
                blocked_reason=blocked_reason,
            )
        )
    return CharacterCardBuildResult(
        avatar_profiles=avatar_profiles,
        character_data_cards=character_cards,
        character_mechanism_slots=mechanism_slots,
        character_trace_nodes=trace_nodes,
        character_eidolon_slots=list(
            {
                slot.eidolon_slot_id: slot
                for slots in eidolon_slots_by_card.values()
                for slot in slots
            }.values()
        ),
        skill_formula_bindings=skill_formula_bindings,
        bounce_policies=bounce_policies,
    )


def _character_data_card_contract() -> dict[str, JSONValue]:
    return {
        "schema_version": "v0_267",
        "runtime_boundary": {
            "runtime_reads": "Canonical IR only",
            "text_map_allowed_in_runtime": False,
            "raw_tbgd_allowed_in_runtime": False,
            "character_name_special_case_allowed": False,
        },
        "required_sections": [
            "identity",
            "base_profile_source",
            "action_set",
            "formula_slots",
            "target_group_slots",
            "bounce_policy",
            "status_and_dynamic_values",
            "listeners",
            "extra_actions",
            "traces",
            "eidolon_interface",
        ],
        "formula_policy": {
            "shape": "basis_value * multiplier + optional_terms",
            "basis_is_declared_by_card": True,
            "attack_default_allowed": False,
        },
        "mechanism_policy": {
            "character_specific_runtime_logic_allowed": False,
            "character_specific_rules_enter_as_card_slots": True,
            "unsupported_slots_must_block": True,
        },
        "eidolon_policy": {
            "configuration_shape": "single_level_0_to_6",
            "enabled_slots": "prefix_closed_ranks_1_through_level",
            "independent_rank_toggle_allowed": False,
            "runtime_effects_must_enter_as_mechanism_slots": True,
        },
        "equipment_boundary": {
            "relics": "external_equipment_card",
            "light_cones": "external_equipment_card",
        },
    }


def _action_set_by_card(
    tbgd_root: Path,
    *,
    skill_tables: tuple[SkillTableSpec, ...],
    skill_to_card: dict[str, str],
    max_records_per_table: int | None,
) -> dict[str, dict[str, JSONValue]]:
    by_card: dict[str, list[dict[str, JSONValue]]] = {}
    for relative_path, entity_type, id_key in skill_tables:
        path = tbgd_root / relative_path
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for row_index, row in enumerate(_limit_sequence(data, max_records_per_table)):
            if not isinstance(row, dict) or row.get(id_key) is None:
                continue
            raw_id = str(row[id_key])
            card_id = skill_to_card.get(raw_id)
            if not card_id:
                continue
            action = {
                "action_id": f"{entity_type}:{raw_id}",
                "raw_skill_id": raw_id,
                "level": int(_number_value(row.get("Level"), 1.0)),
                "skill_trigger_key": str(row.get("SkillTriggerKey") or ""),
                "skill_effect": str(row.get("SkillEffect") or ""),
                "attack_type": str(row.get("AttackType") or ""),
                "max_level": _json_safe(row.get("MaxLevel")),
                "source_trace": IRSource(
                    source_path=relative_path,
                    raw_type=Path(relative_path).stem,
                    raw_id=raw_id,
                    evidence={
                        "row_index": row_index,
                        "id_key": id_key,
                        "builder": "character_action_set_v0_265",
                    },
                ).to_json(),
            }
            by_card.setdefault(card_id, []).append(action)
    result: dict[str, dict[str, JSONValue]] = {}
    for card_id, actions in by_card.items():
        result[card_id] = {
            "actions": sorted(
                actions,
                key=lambda item: (str(item.get("raw_skill_id") or ""), int(item.get("level") or 0)),
            ),
            "selection_policy": "runtime resolves action through ActionDefinitionIR; card only records action evidence",
        }
    return result


def _formula_mechanism_slot(binding: SkillFormulaBindingIR) -> CharacterMechanismSlotIR:
    return CharacterMechanismSlotIR(
        mechanism_slot_id=f"character_mechanism_slot:{binding.formula_slot_id}",
        character_data_card_id=binding.character_data_card_id,
        mechanism_kind="formula_slot",
        runtime_system="damage_formula",
        linked_ir_ids={
            "skill_formula_binding_id": binding.binding_id,
            "formula_slot_id": binding.formula_slot_id,
            "action_id": binding.action_id,
            "level": binding.level,
            "bounce_policy_id": binding.bounce_policy_id,
        },
        activation={
            "kind": "always_when_action_executes",
            "requires_trace_enabled": False,
        },
        semantics={
            "formula_role": binding.formula_role,
            "basis_expr": binding.scaling_basis_expr,
            "multiplier_param_index": binding.param_index,
            "multiplier_param_value": binding.param_value,
            "target_group_hint": binding.target_group_hint,
            "hit_sequence_order": binding.sequence_order,
        },
        source=binding.source,
        coverage_status=binding.coverage_status,
        blocked_reason=binding.blocked_reason,
    )


def _bounce_mechanism_slot(policy: BouncePolicyIR) -> CharacterMechanismSlotIR:
    return CharacterMechanismSlotIR(
        mechanism_slot_id=f"character_mechanism_slot:{policy.bounce_policy_id}",
        character_data_card_id=policy.character_data_card_id,
        mechanism_kind="bounce_policy",
        runtime_system="target_system",
        linked_ir_ids={
            "bounce_policy_id": policy.bounce_policy_id,
            "action_id": policy.action_id,
            "level": policy.level,
        },
        activation={
            "kind": "when_action_target_mode_is_bounce",
            "requires_trace_enabled": False,
        },
        semantics={
            "bounce_count": policy.bounce_count,
            "candidate_scope": policy.candidate_scope,
            "selection_strategy": policy.selection_strategy,
            "live_target_priority": policy.live_target_priority,
            "continue_on_all_defeated": policy.continue_on_all_defeated,
            "rng_source_kind": policy.rng_source_kind,
        },
        source=policy.source,
        coverage_status=policy.coverage_status,
        blocked_reason=policy.blocked_reason,
    )


def _eidolon_mechanism_slot(slot: CharacterEidolonSlotIR) -> CharacterMechanismSlotIR:
    mechanism_slot_id = slot.linked_mechanism_slot_ids[0]
    skill_add_level_list = slot.semantics.get("skill_add_level_list")
    rank_ability = slot.semantics.get("rank_ability")
    extra_effect_id_list = slot.semantics.get("extra_effect_id_list")
    if isinstance(skill_add_level_list, dict) and skill_add_level_list:
        coverage_status = "executable"
        blocked_reason = ""
        runtime_system = "character_card_assembly.skill_level_bonus"
    elif isinstance(rank_ability, (list, tuple)) and rank_ability:
        coverage_status = "executable"
        blocked_reason = ""
        runtime_system = "event_dispatch_or_effect_registry"
    elif isinstance(extra_effect_id_list, (list, tuple)) and extra_effect_id_list:
        coverage_status = "blocked"
        blocked_reason = "eidolon_extra_effect_id_runtime_admission_pending"
        runtime_system = "event_dispatch_or_effect_registry"
    else:
        coverage_status = "blocked"
        blocked_reason = "eidolon_slot_has_no_runtime_effect_source"
        runtime_system = "character_card_assembly"
    return CharacterMechanismSlotIR(
        mechanism_slot_id=mechanism_slot_id,
        character_data_card_id=slot.character_data_card_id,
        mechanism_kind="eidolon_rank_effect",
        runtime_system=runtime_system,
        linked_ir_ids={
            "eidolon_slot_id": slot.eidolon_slot_id,
            "rank_id": slot.rank_id,
            "rank": slot.rank,
        },
        activation={
            "kind": "eidolon_prefix_toggle",
            "required_eidolon_level": slot.rank,
            "enabled_when_requested_level_at_least": slot.rank,
            "prefix_closed": True,
        },
        semantics=slot.semantics,
        source=slot.source,
        coverage_status=coverage_status,
        blocked_reason=blocked_reason,
    )


def _trace_static_stat_terms(status_add_list: list[Any]) -> tuple[list[dict[str, JSONValue]], str]:
    mapped: list[dict[str, JSONValue]] = []
    for index, item in enumerate(status_add_list):
        if not isinstance(item, dict):
            return mapped, "trace_static_stat_item_not_object"
        property_type = str(item.get("PropertyType") or "")
        raw_value = _value_field(item.get("Value"))
        if property_type not in TRACE_STATIC_STAT_PROPERTY_MAP:
            return mapped, f"trace_static_stat_property_not_admitted:{property_type or 'missing'}"
        if not isinstance(raw_value, (int, float)):
            return mapped, f"trace_static_stat_value_not_numeric:{property_type}"
        value = float(raw_value)
        application_kind, target_key = TRACE_STATIC_STAT_PROPERTY_MAP[property_type]
        mapped.append(
            {
                "index": index,
                "property_type": property_type,
                "application_kind": application_kind,
                "target_key": target_key,
                "value": value,
                "raw_path": f"StatusAddList[{index}]",
            }
        )
    if not mapped:
        return mapped, "trace_static_stat_terms_missing"
    return mapped, ""


def _trace_nodes_and_slots(
    tbgd_root: Path,
    *,
    avatar_id_to_card: dict[str, str],
    dynamic_value_bindings_by_avatar_version: dict[tuple[str, str], dict[str, JSONValue]],
    max_records_per_table: int | None,
) -> tuple[list[CharacterTraceNodeIR], list[CharacterMechanismSlotIR]]:
    trace_nodes: list[CharacterTraceNodeIR] = []
    slots: list[CharacterMechanismSlotIR] = []
    for relative_path in ("ExcelOutput/AvatarSkillTreeConfig.json", "ExcelOutput/AvatarSkillTreeConfigLD.json"):
        path = tbgd_root / relative_path
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for row_index, row in enumerate(_limit_sequence(data, max_records_per_table)):
            if not isinstance(row, dict) or row.get("AvatarID") is None or row.get("PointID") is None:
                continue
            avatar_id = str(row["AvatarID"])
            card_id = avatar_id_to_card.get(avatar_id)
            if not card_id:
                continue
            point_id = str(row["PointID"])
            level = int(_number_value(row.get("Level"), 1.0))
            enhanced_id = row.get("EnhancedID")
            enhanced_key = str(enhanced_id) if enhanced_id is not None else ""
            config_dynamic_value_bindings = dynamic_value_bindings_by_avatar_version.get((avatar_id, enhanced_key), {})
            trace_node_id = f"character_trace_node:{card_id}:{point_id}:{level}"
            source = IRSource(
                source_path=relative_path,
                raw_type=Path(relative_path).stem,
                raw_id=f"{point_id}:{level}",
                evidence={
                    "row_index": row_index,
                    "avatar_id": avatar_id,
                    "enhanced_id": _json_safe(enhanced_id),
                    "point_id": point_id,
                    "level": level,
                    "point_type": _json_safe(row.get("PointType")),
                    "anchor_type": str(row.get("AnchorType") or ""),
                    "point_trigger_key": str(row.get("PointTriggerKey") or ""),
                    "ability_name": str(row.get("AbilityName") or ""),
                    "status_add_list": _json_safe(row.get("StatusAddList") or []),
                    "extra_effect_id_list": _json_safe(row.get("ExtraEffectIDList") or []),
                    "builder": "character_trace_node_v0_265",
                },
            )
            linked_slot_ids: list[str] = []
            status_add_list = row.get("StatusAddList")
            if isinstance(status_add_list, list) and status_add_list:
                slot_id = f"character_mechanism_slot:{card_id}:trace:{point_id}:{level}:static_status_add"
                linked_slot_ids.append(slot_id)
                mapped_terms, blocked_reason = _trace_static_stat_terms(status_add_list)
                slots.append(
                    CharacterMechanismSlotIR(
                        mechanism_slot_id=slot_id,
                        character_data_card_id=card_id,
                        mechanism_kind="trace_static_stat_bonus",
                        runtime_system="avatar_profile_assembly",
                        linked_ir_ids={"trace_node_id": trace_node_id},
                        activation={
                            "kind": "trace_toggle",
                            "trace_node_id": trace_node_id,
                            "default_enabled": bool(row.get("DefaultUnlock") is True),
                        },
                        semantics={
                            "status_add_list": _json_safe(status_add_list),
                            "mapped_terms": mapped_terms,
                            "application_boundary": "character_panel_assembly",
                        },
                        source=source,
                        coverage_status="blocked" if blocked_reason else "executable",
                        blocked_reason=blocked_reason,
                    )
                )
            ability_name = str(row.get("AbilityName") or "")
            if ability_name:
                slot_id = f"character_mechanism_slot:{card_id}:trace:{point_id}:{level}:ability"
                linked_slot_ids.append(slot_id)
                slots.append(
                    CharacterMechanismSlotIR(
                        mechanism_slot_id=slot_id,
                        character_data_card_id=card_id,
                        mechanism_kind="trace_ability_hook",
                        runtime_system="event_dispatch_or_effect_registry",
                        linked_ir_ids={"trace_node_id": trace_node_id, "ability_name": ability_name},
                        activation={
                            "kind": "trace_toggle",
                            "trace_node_id": trace_node_id,
                            "default_enabled": bool(row.get("DefaultUnlock") is True),
                        },
                        semantics={
                            "ability_name": ability_name,
                            "point_trigger_key": str(row.get("PointTriggerKey") or ""),
                            "param_values": list(_number_items(row.get("ParamList"))),
                            "dynamic_value_bindings": _trace_dynamic_value_bindings_for_row(
                                row,
                                config_dynamic_value_bindings,
                            ),
                            "startup_admission_boundary": "standalone_graph_on_start_add_modifier",
                            "admission_boundary": "must resolve to admitted ability graph/effect before executable",
                        },
                        source=source,
                        coverage_status="blocked",
                        blocked_reason="trace_ability_effect_not_admitted_v0_265",
                    )
                )
            trace_nodes.append(
                CharacterTraceNodeIR(
                    trace_node_id=trace_node_id,
                    character_data_card_id=card_id,
                    avatar_id=avatar_id,
                    trace_id=point_id,
                    trace_kind=str(row.get("PointType") or ""),
                    linked_mechanism_slot_ids=tuple(linked_slot_ids),
                    source=source,
                    coverage_status="executable",
                )
            )
    return trace_nodes, slots


def _character_config_dynamic_value_bindings_by_avatar_version(
    tbgd_root: Path,
    *,
    max_records_per_table: int | None,
) -> dict[tuple[str, str], dict[str, JSONValue]]:
    result: dict[tuple[str, str], dict[str, JSONValue]] = {}
    for relative_path in (
        "ExcelOutput/AvatarConfig.json",
        "ExcelOutput/AvatarConfigLD.json",
        "ExcelOutput/AvatarConfigEnhanced.json",
    ):
        path = tbgd_root / relative_path
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for row in _limit_sequence(data, max_records_per_table):
            if not isinstance(row, dict) or row.get("AvatarID") is None:
                continue
            avatar_id = str(row["AvatarID"])
            enhanced_id = row.get("EnhancedID") if "Enhanced" in relative_path else None
            enhanced_key = str(enhanced_id) if enhanced_id is not None else ""
            augmented = _augment_avatar_row_with_config_dynamic_values(tbgd_root, dict(row))
            bindings = augmented.get("_character_config_dynamic_value_bindings")
            if isinstance(bindings, dict):
                result[(avatar_id, enhanced_key)] = _json_safe(bindings)
    return result


def _trace_dynamic_value_bindings_for_row(
    row: dict[str, Any],
    config_dynamic_value_bindings: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    by_hash = config_dynamic_value_bindings.get("by_hash")
    if not isinstance(by_hash, dict):
        return {
            "by_hash": {},
            "trigger_key": str(row.get("PointTriggerKey") or ""),
            "source_path": _json_safe(config_dynamic_value_bindings.get("source_path")),
        }
    trigger_key = str(row.get("PointTriggerKey") or "")
    result: dict[str, JSONValue] = {}
    for raw_hash, item in by_hash.items():
        if not isinstance(item, dict):
            continue
        read_info = item.get("read_info")
        if not isinstance(read_info, dict):
            continue
        if read_info.get("Type") != "SkillTreeParam" or read_info.get("TriggerKey") != trigger_key:
            continue
        index = read_info.get("Index")
        if not isinstance(index, int):
            continue
        result[str(raw_hash)] = {
            "hash": str(raw_hash),
            "trigger_key": trigger_key,
            "param_index": index,
            "read_info": _json_safe(read_info),
            "source_path": _json_safe(item.get("source_path")),
            "raw_path": _json_safe(item.get("raw_path")),
        }
    return {
        "by_hash": result,
        "trigger_key": trigger_key,
        "source_path": _json_safe(config_dynamic_value_bindings.get("source_path")),
        "binding_source_kind": "character_config_skill_tree_param_read_info",
    }


def _eidolon_slots_from_avatar_row(
    relative_path: str,
    row_index: int,
    row: dict[str, Any],
    card_id: str,
    rank_rows_by_id: dict[str, tuple[str, int, dict[str, Any]]],
) -> list[CharacterEidolonSlotIR]:
    avatar_id = str(row["AvatarID"])
    rank_ids = row.get("RankIDList")
    if not isinstance(rank_ids, list):
        rank_ids = []
    slots: list[CharacterEidolonSlotIR] = []
    for index in range(6):
        rank_id = str(rank_ids[index]) if index < len(rank_ids) else ""
        rank_row_info = rank_rows_by_id.get(rank_id)
        rank_relative_path = ""
        rank_row_index = -1
        rank_row: dict[str, Any] = {}
        if rank_row_info is not None:
            rank_relative_path, rank_row_index, rank_row = rank_row_info
        mechanism_slot_id = f"character_mechanism_slot:{card_id}:eidolon:{index + 1}" if rank_row_info else ""
        coverage_status = "executable" if rank_id and rank_row_info else "blocked"
        blocked_reason = ""
        if not rank_id:
            blocked_reason = "eidolon_rank_id_missing"
        elif rank_row_info is None:
            blocked_reason = "eidolon_rank_config_missing"
        semantics = {
            "rank": index + 1,
            "rank_id": rank_id,
            "rank_ability": _json_safe(rank_row.get("RankAbility") or []),
            "skill_add_level_list": _json_safe(rank_row.get("SkillAddLevelList") or {}),
            "extra_effect_id_list": _json_safe(rank_row.get("ExtraEffectIDList") or []),
            "param_values": _json_safe(_param_values(rank_row.get("Param") or [])),
            "dynamic_value_bindings": _eidolon_dynamic_value_bindings_for_rank(
                row.get("_character_config_dynamic_value_bindings"),
                index + 1,
            ),
            "effect_application_boundary": "character_mechanism_slot",
            "runtime_effects_are_not_implicit": True,
        }
        slots.append(
            CharacterEidolonSlotIR(
                eidolon_slot_id=f"character_eidolon_slot:{card_id}:rank:{index + 1}",
                character_data_card_id=card_id,
                avatar_id=avatar_id,
                rank=index + 1,
                rank_id=rank_id,
                linked_mechanism_slot_ids=(mechanism_slot_id,) if mechanism_slot_id else (),
                source=IRSource(
                    source_path=rank_relative_path or relative_path,
                    raw_type=Path(rank_relative_path or relative_path).stem,
                    raw_id=rank_id or f"{avatar_id}:rank:{index + 1}",
                    evidence={
                        "row_index": row_index,
                        "avatar_config_source_path": relative_path,
                        "avatar_config_row_index": row_index,
                        "rank_id": rank_id,
                        "rank_id_list": _json_safe(rank_ids),
                        "rank_config_source_path": rank_relative_path,
                        "rank_config_row_index": rank_row_index,
                        "rank_config_rank": _json_safe(rank_row.get("Rank")),
                        "rank_name": _json_safe(rank_row.get("Name")),
                        "rank_desc": _json_safe(rank_row.get("Desc")),
                        "rank_ability": _json_safe(rank_row.get("RankAbility") or []),
                        "skill_add_level_list": _json_safe(rank_row.get("SkillAddLevelList") or {}),
                        "extra_effect_id_list": _json_safe(rank_row.get("ExtraEffectIDList") or []),
                        "param_values": semantics["param_values"],
                        "dynamic_value_bindings": semantics["dynamic_value_bindings"],
                        "builder": "character_eidolon_interface_v0_267",
                    },
                ),
                coverage_status=coverage_status,
                blocked_reason=blocked_reason,
                activation={
                    "kind": "eidolon_prefix_toggle",
                    "rank": index + 1,
                    "prefix_closed": True,
                    "selection_source": "scenario_unit_eidolon_level",
                },
                semantics=semantics,
            )
        )
    return slots


def _eidolon_dynamic_value_bindings_for_rank(value: object, rank: int) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        return {"by_hash": {}, "rank": rank}
    by_hash = value.get("by_hash")
    if not isinstance(by_hash, dict):
        return {"by_hash": {}, "rank": rank, "source_path": _json_safe(value.get("source_path"))}
    trigger_key = f"Rank{rank:02d}"
    result: dict[str, JSONValue] = {}
    for raw_hash, item in by_hash.items():
        if not isinstance(item, dict):
            continue
        read_info = item.get("read_info")
        if not isinstance(read_info, dict):
            continue
        if read_info.get("Type") != "SkillRank" or read_info.get("TriggerKey") != trigger_key:
            continue
        index = read_info.get("Index")
        if not isinstance(index, int):
            continue
        result[str(raw_hash)] = {
            "hash": str(raw_hash),
            "rank": rank,
            "trigger_key": trigger_key,
            "param_index": index,
            "read_info": _json_safe(read_info),
            "source_path": _json_safe(item.get("source_path")),
            "raw_path": _json_safe(item.get("raw_path")),
        }
    return {
        "by_hash": result,
        "rank": rank,
        "trigger_key": trigger_key,
        "source_path": _json_safe(value.get("source_path")),
    }


def skill_formula_bindings_from_row(
    *,
    relative_path: str,
    entity_type: str,
    id_key: str,
    row_index: int,
    row: dict[str, Any],
    text_map: dict[str, str],
    skill_to_card: dict[str, str] | None = None,
) -> list[SkillFormulaBindingIR]:
    raw_id = str(row[id_key])
    action_id = f"{entity_type}:{raw_id}"
    character_data_card_id = (skill_to_card or {}).get(raw_id, "")
    level = int(_number_value(row.get("Level"), 1.0))
    text_hash = _text_hash(row.get("SkillDesc"))
    skill_text = text_map.get(text_hash, "") if text_hash else ""
    normalized_text = _normalize_skill_text(skill_text)
    param_list = tuple(_list_json_values(row.get("ParamList")))
    matches = _skill_formula_text_matches(normalized_text)
    bindings: list[SkillFormulaBindingIR] = []
    for sequence_order, match in enumerate(matches):
        param_index = int(match["param_index"]) - 1
        basis_word = str(match["basis_word"])
        target_group_hint = str(match.get("target_group_hint") or "")
        param_value = param_list[param_index] if 0 <= param_index < len(param_list) else None
        blocked_reason = ""
        if not character_data_card_id and entity_type == "avatar_skill":
            blocked_reason = "character_data_card_missing_for_avatar_skill"
        elif param_index < 0:
            blocked_reason = "skill_text_param_index_invalid"
        elif param_index >= len(param_list):
            blocked_reason = "skill_text_param_index_out_of_range"
        elif not isinstance(_value_field(param_value), (int, float)):
            blocked_reason = "skill_text_param_value_not_numeric"
        stat = SKILL_TEXT_BASIS_WORDS.get(basis_word, "")
        if not stat and not blocked_reason:
            blocked_reason = "skill_text_scaling_basis_not_supported"
        role = _skill_formula_role(str(match["matched_text"]))
        source = IRSource(
            source_path=relative_path,
            raw_type=Path(relative_path).stem,
            raw_id=raw_id,
            evidence={
                "row_index": row_index,
                "id_key": id_key,
                "level": level,
                "skill_desc_hash": text_hash,
                "matched_text": str(match["matched_text"]),
                "basis_word": basis_word,
                "param_ref": f"ParamList[{param_index}]",
                "match_index": sequence_order,
                "sequence_order": sequence_order,
                "target_group_hint": target_group_hint,
                "character_data_card_id": character_data_card_id,
                "builder": "character_data_card_v0_262",
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
                "stat": stat,
                "source_kind": "character_data_card_skill_formula",
                "admission_status": "executable",
                "character_data_card_id": character_data_card_id,
                "param_index": param_index,
                "param_value": _json_safe(param_value),
                "text_hash": text_hash,
                "matched_text": str(match["matched_text"]),
                "source_trace": source.to_json(),
            }
        bindings.append(
            SkillFormulaBindingIR(
                binding_id=f"skill_formula_binding:{action_id}:{level}:{role}:param:{param_index}:{sequence_order}",
                character_data_card_id=character_data_card_id,
                formula_slot_id=f"formula_slot:{action_id}:{level}:{role}:{sequence_order}",
                action_id=action_id,
                level=level,
                param_index=param_index,
                sequence_order=sequence_order,
                formula_role=role,
                target_group_hint=target_group_hint,
                param_value=_json_safe(param_value),
                scaling_basis_expr=scaling_basis_expr,
                text_hash=text_hash,
                skill_text=skill_text,
                matched_text=str(match["matched_text"]),
                source=source,
                coverage_status="blocked" if blocked_reason else "executable",
                blocked_reason=blocked_reason,
            )
        )
    if not bindings and param_list:
        source = IRSource(
            source_path=relative_path,
            raw_type=Path(relative_path).stem,
            raw_id=raw_id,
            evidence={
                "row_index": row_index,
                "id_key": id_key,
                "level": level,
                "skill_desc_hash": text_hash,
                "character_data_card_id": character_data_card_id,
                "builder": "character_data_card_v0_262",
                "reason": "no supported damage scaling phrase found in skill text",
            },
        )
        bindings.append(
            SkillFormulaBindingIR(
                binding_id=f"skill_formula_binding:{action_id}:{level}:direct_damage:param:0:blocked",
                character_data_card_id=character_data_card_id,
                formula_slot_id=f"formula_slot:{action_id}:{level}:direct_damage:blocked",
                action_id=action_id,
                level=level,
                param_index=0,
                sequence_order=0,
                formula_role="direct_damage",
                target_group_hint="unknown",
                param_value=_json_safe(param_list[0]),
                scaling_basis_expr={
                    "kind": "missing",
                    "supported": False,
                    "reason": "skill_text_scaling_basis_binding_missing",
                    "source_trace": source.to_json(),
                },
                text_hash=text_hash,
                skill_text=skill_text,
                matched_text="",
                source=source,
                coverage_status="blocked",
                blocked_reason="skill_text_scaling_basis_binding_missing",
            )
        )
    return bindings


def _avatar_rows(tbgd_root: Path, *, max_records_per_table: int | None) -> list[tuple[str, int, dict[str, Any]]]:
    base_rows: list[tuple[str, int, dict[str, Any]]] = []
    for relative_path in ("ExcelOutput/AvatarConfig.json", "ExcelOutput/AvatarConfigLD.json"):
        path = tbgd_root / relative_path
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for row_index, row in enumerate(_limit_sequence(data, max_records_per_table)):
            if isinstance(row, dict) and row.get("AvatarID") is not None:
                copied = _augment_avatar_row_with_config_dynamic_values(tbgd_root, dict(row))
                copied["_character_card_version_kind"] = "base"
                copied["_character_card_base_source_path"] = relative_path
                copied["_character_card_base_row_index"] = row_index
                base_rows.append((relative_path, row_index, copied))
    enhanced_rows = _enhanced_avatar_rows(tbgd_root, max_records_per_table=max_records_per_table)
    enhanced_by_avatar = {str(row["AvatarID"]): (relative_path, row_index, row) for relative_path, row_index, row in enhanced_rows}
    rows: list[tuple[str, int, dict[str, Any]]] = []
    seen: set[str] = set()
    for base_relative_path, base_row_index, base_row in base_rows:
        avatar_id = str(base_row["AvatarID"])
        enhanced = enhanced_by_avatar.get(avatar_id)
        if enhanced is None:
            rows.append((base_relative_path, base_row_index, base_row))
            seen.add(avatar_id)
            continue
        enhanced_relative_path, enhanced_row_index, enhanced_row = enhanced
        merged = _augment_avatar_row_with_config_dynamic_values(tbgd_root, {**base_row, **enhanced_row})
        for key in ("DamageType", "AvatarBaseType", "Rarity"):
            if not merged.get(key):
                merged[key] = base_row.get(key)
        merged["_character_card_version_kind"] = "enhanced"
        merged["_character_card_base_source_path"] = base_relative_path
        merged["_character_card_base_row_index"] = base_row_index
        merged["_character_card_base_skill_list"] = _json_safe(base_row.get("SkillList") or [])
        merged["_character_card_enhanced_source_path"] = enhanced_relative_path
        merged["_character_card_enhanced_row_index"] = enhanced_row_index
        merged["_character_card_enhanced_id"] = enhanced_row.get("EnhancedID")
        merged["_character_card_enhanced_skill_list"] = _json_safe(enhanced_row.get("SkillList") or [])
        rows.append((enhanced_relative_path, enhanced_row_index, merged))
        seen.add(avatar_id)
    for enhanced_relative_path, enhanced_row_index, enhanced_row in enhanced_rows:
        avatar_id = str(enhanced_row["AvatarID"])
        if avatar_id in seen:
            continue
        copied = _augment_avatar_row_with_config_dynamic_values(tbgd_root, dict(enhanced_row))
        copied["_character_card_version_kind"] = "enhanced"
        copied["_character_card_enhanced_source_path"] = enhanced_relative_path
        copied["_character_card_enhanced_row_index"] = enhanced_row_index
        copied["_character_card_enhanced_id"] = enhanced_row.get("EnhancedID")
        copied["_character_card_enhanced_skill_list"] = _json_safe(enhanced_row.get("SkillList") or [])
        rows.append((enhanced_relative_path, enhanced_row_index, copied))
    return rows


def _augment_avatar_row_with_config_dynamic_values(tbgd_root: Path, row: dict[str, Any]) -> dict[str, Any]:
    json_path = row.get("JsonPath")
    if not isinstance(json_path, str) or not json_path:
        row["_character_config_dynamic_value_bindings"] = {"by_hash": {}, "source_path": ""}
        return row
    config_path = tbgd_root / json_path
    if not config_path.exists():
        row["_character_config_dynamic_value_bindings"] = {"by_hash": {}, "source_path": json_path, "blocked_reason": "character_config_missing"}
        return row
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        row["_character_config_dynamic_value_bindings"] = {"by_hash": {}, "source_path": json_path, "blocked_reason": "character_config_unreadable"}
        return row
    floats = data.get("DynamicValues", {}).get("Floats") if isinstance(data, dict) else None
    by_hash: dict[str, JSONValue] = {}
    if isinstance(floats, dict):
        for raw_hash, item in floats.items():
            if not isinstance(item, dict):
                continue
            by_hash[str(raw_hash)] = {
                "hash": str(raw_hash),
                "read_info": _json_safe(item.get("ReadInfo")),
                "source_path": json_path,
                "raw_path": f"DynamicValues.Floats[{raw_hash}]",
            }
    row["_character_config_dynamic_value_bindings"] = {"by_hash": by_hash, "source_path": json_path}
    return row


def _avatar_rank_rows_by_id(
    tbgd_root: Path,
    *,
    max_records_per_table: int | None,
) -> dict[str, tuple[str, int, dict[str, Any]]]:
    rows: dict[str, tuple[str, int, dict[str, Any]]] = {}
    for relative_path in ("ExcelOutput/AvatarRankConfig.json", "ExcelOutput/AvatarRankConfigLD.json"):
        path = tbgd_root / relative_path
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for row_index, row in enumerate(_limit_sequence(data, max_records_per_table)):
            if not isinstance(row, dict) or row.get("RankID") is None:
                continue
            rows.setdefault(str(row["RankID"]), (relative_path, row_index, row))
    return rows


def _enhanced_avatar_rows(tbgd_root: Path, *, max_records_per_table: int | None) -> list[tuple[str, int, dict[str, Any]]]:
    relative_path = "ExcelOutput/AvatarConfigEnhanced.json"
    path = tbgd_root / relative_path
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    rows: list[tuple[str, int, dict[str, Any]]] = []
    for row_index, row in enumerate(_limit_sequence(data, max_records_per_table)):
        if isinstance(row, dict) and row.get("AvatarID") is not None:
            rows.append((relative_path, row_index, dict(row)))
    return rows


def _promotion_rows_by_avatar(tbgd_root: Path) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for relative_path in ("ExcelOutput/AvatarPromotionConfig.json", "ExcelOutput/AvatarPromotionConfigLD.json"):
        path = tbgd_root / relative_path
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for row in data:
            if isinstance(row, dict) and row.get("AvatarID") is not None:
                rows.setdefault(str(row["AvatarID"]), []).append(row)
    return rows


def _skill_to_card_map(avatar_rows: list[tuple[str, int, dict[str, Any]]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for _, _, row in avatar_rows:
        avatar_id = str(row["AvatarID"])
        card_id = f"character_data_card:avatar:{avatar_id}"
        for skill_id in row.get("SkillList") or ():
            mapping[str(skill_id)] = card_id
    return mapping


def _skill_formula_bindings_for_table(
    tbgd_root: Path,
    *,
    relative_path: str,
    entity_type: str,
    id_key: str,
    text_map: dict[str, str],
    skill_to_card: dict[str, str],
    max_records_per_table: int | None,
) -> list[SkillFormulaBindingIR]:
    path = tbgd_root / relative_path
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    bindings: list[SkillFormulaBindingIR] = []
    for row_index, row in enumerate(_limit_sequence(data, max_records_per_table)):
        if not isinstance(row, dict) or id_key not in row:
            continue
        bindings.extend(
            skill_formula_bindings_from_row(
                relative_path=relative_path,
                entity_type=entity_type,
                id_key=id_key,
                row_index=row_index,
                row=row,
                text_map=text_map,
                skill_to_card=skill_to_card,
            )
        )
    return bindings


def _skill_param_slots_for_table(
    tbgd_root: Path,
    *,
    relative_path: str,
    entity_type: str,
    id_key: str,
    skill_to_card: dict[str, str],
    max_records_per_table: int | None,
) -> list[CharacterMechanismSlotIR]:
    if entity_type != "avatar_skill":
        return []
    path = tbgd_root / relative_path
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    slots: list[CharacterMechanismSlotIR] = []
    for row_index, row in enumerate(_limit_sequence(data, max_records_per_table)):
        if not isinstance(row, dict) or id_key not in row:
            continue
        raw_id = str(row[id_key])
        card_id = skill_to_card.get(raw_id, "")
        if not card_id:
            continue
        level = int(_number_value(row.get("Level"), 1.0))
        param_list = _list_json_values(row.get("ParamList"))
        for param_index, param_value in enumerate(param_list):
            blocked_reason = ""
            if not isinstance(_value_field(param_value), (int, float)):
                blocked_reason = "skill_param_value_not_numeric"
            source = IRSource(
                source_path=relative_path,
                raw_type=Path(relative_path).stem,
                raw_id=raw_id,
                evidence={
                    "row_index": row_index,
                    "id_key": id_key,
                    "level": level,
                    "skill_trigger_key": str(row.get("SkillTriggerKey") or ""),
                    "skill_effect": str(row.get("SkillEffect") or ""),
                    "attack_type": str(row.get("AttackType") or ""),
                    "param_ref": f"ParamList[{param_index}]",
                    "param_value": _json_safe(param_value),
                    "character_data_card_id": card_id,
                    "builder": "character_data_card_skill_param_slot_v0_266",
                },
            )
            slots.append(
                CharacterMechanismSlotIR(
                    mechanism_slot_id=f"character_mechanism_slot:{card_id}:skill_param:{raw_id}:{level}:{param_index}",
                    character_data_card_id=card_id,
                    mechanism_kind="skill_param_slot",
                    runtime_system="character_data_card_builder",
                    linked_ir_ids={
                        "action_id": f"{entity_type}:{raw_id}",
                        "level": level,
                        "param_index": param_index,
                    },
                    activation={"kind": "character_card_evidence_only"},
                    semantics={
                        "skill_id": raw_id,
                        "level": level,
                        "param_index": param_index,
                        "param_ref": f"ParamList[{param_index}]",
                        "param_value": _json_safe(param_value),
                        "skill_trigger_key": str(row.get("SkillTriggerKey") or ""),
                        "skill_effect": str(row.get("SkillEffect") or ""),
                        "attack_type": str(row.get("AttackType") or ""),
                    },
                    source=source,
                    coverage_status="blocked" if blocked_reason else "executable",
                    blocked_reason=blocked_reason,
                )
            )
    return slots


def _bounce_policies_for_table(
    tbgd_root: Path,
    *,
    relative_path: str,
    entity_type: str,
    id_key: str,
    text_map: dict[str, str],
    skill_to_card: dict[str, str],
    max_records_per_table: int | None,
) -> list[BouncePolicyIR]:
    path = tbgd_root / relative_path
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    policies: list[BouncePolicyIR] = []
    for row_index, row in enumerate(_limit_sequence(data, max_records_per_table)):
        if not isinstance(row, dict) or id_key not in row:
            continue
        policy = _bounce_policy_from_row(
            relative_path=relative_path,
            entity_type=entity_type,
            id_key=id_key,
            row_index=row_index,
            row=row,
            text_map=text_map,
            skill_to_card=skill_to_card,
        )
        if policy is not None:
            policies.append(policy)
    return policies


def _bounce_policy_from_row(
    *,
    relative_path: str,
    entity_type: str,
    id_key: str,
    row_index: int,
    row: dict[str, Any],
    text_map: dict[str, str],
    skill_to_card: dict[str, str],
) -> BouncePolicyIR | None:
    skill_effect = str(row.get("SkillEffect") or "")
    if skill_effect.lower() != "bounce":
        return None
    raw_id = str(row[id_key])
    action_id = f"{entity_type}:{raw_id}"
    character_data_card_id = skill_to_card.get(raw_id, "")
    level = int(_number_value(row.get("Level"), 1.0))
    text_hash = _text_hash(row.get("SkillDesc"))
    skill_text = text_map.get(text_hash, "") if text_hash else ""
    normalized_text = _normalize_skill_text(skill_text)
    bounce_count = _bounce_count_from_text(normalized_text)
    selection_strategy = _bounce_selection_strategy(normalized_text)
    candidate_scope = _bounce_candidate_scope(normalized_text)
    blocked_reason = ""
    if entity_type != "avatar_skill":
        blocked_reason = "bounce_policy_only_avatar_skill_admitted"
    elif not character_data_card_id:
        blocked_reason = "character_data_card_missing_for_bounce_policy"
    elif bounce_count <= 0:
        blocked_reason = "bounce_count_not_admitted_from_skill_text"
    elif not candidate_scope:
        blocked_reason = "bounce_candidate_scope_not_admitted_from_skill_text"
    elif not selection_strategy:
        blocked_reason = "bounce_selection_strategy_not_admitted_from_skill_text"
    source = IRSource(
        source_path=relative_path,
        raw_type=Path(relative_path).stem,
        raw_id=raw_id,
        evidence={
            "row_index": row_index,
            "id_key": id_key,
            "level": level,
            "skill_effect": skill_effect,
            "skill_desc_hash": text_hash,
            "skill_text_excerpt": normalized_text[:240],
            "bounce_count": bounce_count,
            "candidate_scope": candidate_scope,
            "selection_strategy": selection_strategy,
            "live_target_priority_source_kind": "engine_convention",
            "continue_on_all_defeated_source_kind": "engine_convention",
            "character_data_card_id": character_data_card_id,
            "builder": "character_data_card_v0_264",
        },
    )
    return BouncePolicyIR(
        bounce_policy_id=f"bounce_policy:{action_id}:{level}",
        character_data_card_id=character_data_card_id,
        action_id=action_id,
        level=level,
        bounce_count=bounce_count,
        initial_target_group="primary",
        bounce_target_group="bounce",
        candidate_scope=candidate_scope or "unknown",
        selection_strategy=selection_strategy or "unknown",
        live_target_priority=True,
        continue_on_all_defeated=True,
        allow_repeat_after_all_hit=True,
        rng_source_kind="battle_rng",
        source=source,
        coverage_status="blocked" if blocked_reason else "executable",
        blocked_reason=blocked_reason,
    )


def _attach_bounce_policy_to_formula_binding(
    binding: SkillFormulaBindingIR,
    policy_by_action: dict[tuple[str, int], str],
) -> SkillFormulaBindingIR:
    policy_id = policy_by_action.get((binding.action_id, binding.level), "")
    if not policy_id:
        return binding
    return replace(binding, bounce_policy_id=policy_id)


def _avatar_profile_from_row(
    relative_path: str,
    row_index: int,
    row: dict[str, Any],
    promotion_rows: list[dict[str, Any]],
) -> AvatarProfileIR:
    avatar_id = str(row["AvatarID"])
    skill_ids = tuple(str(skill_id) for skill_id in row.get("SkillList") or ())
    base_stats_by_promotion = _avatar_base_stats_by_promotion(promotion_rows)
    blocked_reason = ""
    if not skill_ids:
        blocked_reason = "avatar_skill_list_missing"
    elif not base_stats_by_promotion:
        blocked_reason = "avatar_promotion_base_stats_missing"
    return AvatarProfileIR(
        avatar_profile_id=f"avatar_profile:{avatar_id}",
        avatar_id=avatar_id,
        base_type=str(row.get("AvatarBaseType") or ""),
        damage_type=str(row.get("DamageType") or ""),
        skill_ids=skill_ids,
        base_stats_by_promotion=base_stats_by_promotion,
        source=IRSource(
            source_path=relative_path,
            raw_type=Path(relative_path).stem,
            raw_id=avatar_id,
            evidence={
                "row_index": row_index,
                "skill_list": _json_safe(row.get("SkillList")),
                "json_path": str(row.get("JsonPath") or ""),
                "version_kind": str(row.get("_character_card_version_kind") or "base"),
                "base_source_path": str(row.get("_character_card_base_source_path") or relative_path),
                "base_row_index": _json_safe(row.get("_character_card_base_row_index")),
                "base_skill_list": _json_safe(row.get("_character_card_base_skill_list") or []),
                "enhanced_source_path": str(row.get("_character_card_enhanced_source_path") or ""),
                "enhanced_row_index": _json_safe(row.get("_character_card_enhanced_row_index")),
                "enhanced_id": _json_safe(row.get("_character_card_enhanced_id")),
                "enhanced_skill_list": _json_safe(row.get("_character_card_enhanced_skill_list") or []),
                "enhanced_overrides_base": str(row.get("_character_card_version_kind") or "base") == "enhanced",
                "promotion_row_count": len(promotion_rows),
                "builder": "character_data_card_v0_262",
            },
        ),
        coverage_status="blocked" if blocked_reason else "executable",
        blocked_reason=blocked_reason,
    )


def _load_text_map(tbgd_root: Path) -> dict[str, str]:
    for relative_path in ("TextMap/TextMapCHS.json", "TextMap/TextMapCN.json"):
        path = tbgd_root / relative_path
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            return {str(key): str(value) for key, value in data.items() if isinstance(value, str)}
    return {}


def _avatar_base_stats_by_promotion(rows: list[dict[str, Any]]) -> dict[str, JSONValue]:
    result: dict[str, JSONValue] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        max_level = row.get("MaxLevel")
        key = str(max_level if isinstance(max_level, int) else index)
        stats = {
            "max_level": _json_safe(row.get("MaxLevel")),
            "attack_base": _value_field(row.get("AttackBase")),
            "attack_add": _value_field(row.get("AttackAdd")),
            "defense_base": _value_field(row.get("DefenceBase")),
            "defense_add": _value_field(row.get("DefenceAdd")),
            "hp_base": _value_field(row.get("HPBase")),
            "hp_add": _value_field(row.get("HPAdd")),
            "speed_base": _value_field(row.get("SpeedBase")),
            "critical_chance": _value_field(row.get("CriticalChance")),
            "critical_damage": _value_field(row.get("CriticalDamage")),
            "base_aggro": _value_field(row.get("BaseAggro")),
        }
        if any(isinstance(value, (int, float)) for value in stats.values()):
            result[key] = stats
    return result


def _text_hash(value: Any) -> str:
    if isinstance(value, dict) and value.get("Hash") is not None:
        return str(value["Hash"])
    return ""


def _normalize_skill_text(text: str) -> str:
    normalized = re.sub(r"<[^>]+>", "", text)
    return normalized.replace("\\n", "。").replace("\n", "。")


def _skill_formula_text_matches(text: str) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for pattern in SKILL_TEXT_DAMAGE_BINDING_PATTERNS:
        for match in pattern.finditer(text):
            target_group_hint = _target_group_hint_for_match(text, match.start("matched"), match.end("matched"))
            key = (
                match.group("param_index"),
                match.group("basis"),
                _skill_formula_role(match.group("matched")),
                target_group_hint,
            )
            if key in seen:
                continue
            seen.add(key)
            matches.append(
                {
                    "param_index": match.group("param_index"),
                    "basis_word": match.group("basis"),
                    "matched_text": match.group("matched"),
                    "target_group_hint": target_group_hint,
                    "match_start": str(match.start("matched")),
                }
            )
    return sorted(matches, key=lambda item: int(item.get("match_start") or 0))


def _skill_formula_role(matched_text: str) -> str:
    if "持续伤害" in matched_text:
        return "dot_damage"
    if "附加伤害" in matched_text:
        return "additional_damage"
    return "direct_damage"


def _target_group_hint_for_match(text: str, start: int, end: int) -> str:
    context = _formula_match_clause(text, start, end)
    if "相邻" in context:
        return "adjacent"
    if "全体" in context or "所有敌方" in context:
        return "all_enemy"
    if "随机" in context:
        return "random"
    if "自身" in context or "我方" in context:
        return "team_or_self"
    return "primary"


def _formula_match_clause(text: str, start: int, end: int) -> str:
    left = start
    while left > 0 and text[left - 1] not in "，,。.;；：:":
        left -= 1
    right = end
    while right < len(text) and text[right] not in "，,。.;；：:":
        right += 1
    return text[left:right]


def _bounce_count_from_text(text: str) -> int:
    match = re.search(r"额外造成(?P<count>\d+)次伤害", text)
    if match:
        return int(match.group("count"))
    match = re.search(r"弹射(?P<count>\d+)次", text)
    if match:
        return int(match.group("count"))
    return 0


def _bounce_candidate_scope(text: str) -> str:
    if "随机敌方单体" in text or "敌方随机单体" in text or "随机对敌方单体" in text:
        return "enemy_single"
    return ""


def _bounce_selection_strategy(text: str) -> str:
    prefer_unhit_terms = ("未受到过", "未命中", "未被命中", "未被攻击", "优先攻击", "优先对")
    if any(term in text for term in prefer_unhit_terms):
        return "prefer_unhit_then_random"
    if "随机" in text:
        return "random_live_targets"
    return ""


def _limit_sequence(items: list[Any], limit: int | None) -> list[Any]:
    if limit is None:
        return items
    return items[: max(0, limit)]


def _number_value(value: Any, default: float = 0.0) -> float:
    extracted = _value_field(value)
    if isinstance(extracted, (int, float)):
        return float(extracted)
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _number_items(value: Any) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[float] = []
    for item in value:
        extracted = _value_field(item)
        if isinstance(extracted, (int, float)):
            result.append(float(extracted))
    return tuple(result)


def _value_field(value: Any) -> float | int | None:
    if isinstance(value, dict):
        inner = value.get("Value")
        return inner if isinstance(inner, (int, float)) else None
    return value if isinstance(value, (int, float)) else None


def _list_json_values(value: Any) -> list[JSONValue]:
    if not isinstance(value, list):
        return []
    return [_json_safe(item) for item in value]


def _param_values(value: Any) -> list[JSONValue]:
    if not isinstance(value, list):
        return []
    result: list[JSONValue] = []
    for item in value:
        extracted = _value_field(item)
        result.append(extracted if extracted is not None else _json_safe(item))
    return result


def _json_safe(value: Any) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)
