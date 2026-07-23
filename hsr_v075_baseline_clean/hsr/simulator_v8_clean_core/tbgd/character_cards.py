from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..build_types import canonical_decimal, static_property_binding
from ..dynamic_key_hash import tbgd_dynamic_key_hash
from ..equipment.models import (
    CharacterEquipmentEligibilityIR,
    EquipmentDefinitionKey,
)
from ..rules.ir import (
    AvatarPromotionTierIR,
    AvatarProfileIR,
    BouncePolicyIR,
    CharacterDataCardIR,
    CharacterEidolonSlotIR,
    CharacterMechanismSlotIR,
    CharacterTraceNodeIR,
    IRSource,
    JSONValue,
    SkillFormulaBindingIR,
    SpecialResourceDefinitionIR,
    SpecialResourceInitializerIR,
)
from ..rules.expression_ir import (
    is_typed_numeric_expression,
    numeric_dynamic_hashes,
    numeric_fixed_value,
)
from .expression_lowering import lower_numeric_expression


SkillTableSpec = tuple[str, str, str]


@dataclass(frozen=True)
class CharacterCardBuildResult:
    avatar_profiles: list[AvatarProfileIR]
    character_data_cards: list[CharacterDataCardIR]
    character_equipment_eligibilities: list[CharacterEquipmentEligibilityIR]
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
        mechanism_slot
        for slots in eidolon_slots_by_card.values()
        for slot in slots
        if slot.linked_mechanism_slot_ids
        for mechanism_slot in _eidolon_mechanism_slots(slot)
    )
    mechanism_slot_ids_by_card: dict[str, list[str]] = {}
    for slot in mechanism_slots:
        if slot.character_data_card_id:
            mechanism_slot_ids_by_card.setdefault(slot.character_data_card_id, []).append(slot.mechanism_slot_id)
    avatar_profiles: list[AvatarProfileIR] = []
    character_cards: list[CharacterDataCardIR] = []
    character_equipment_eligibilities: list[CharacterEquipmentEligibilityIR] = []
    special_resource_skill_rows = _avatar_skill_parameter_rows(
        tbgd_root,
        skill_ids={
            str(skill_id)
            for _relative_path, _row_index, row in avatar_rows
            if "SPNeed" not in row
            for skill_id in row.get("SkillList") or ()
        },
    )
    for relative_path, row_index, row in avatar_rows:
        avatar_id = str(row["AvatarID"])
        promotion_rows = promotion_rows_by_avatar.get(avatar_id, [])
        profile = _avatar_profile_from_row(
            tbgd_root,
            relative_path,
            row_index,
            row,
            promotion_rows,
            special_resource_skill_rows,
        )
        avatar_profiles.append(profile)
        card_id = f"character_data_card:avatar:{avatar_id}"
        equipment_eligibility_id = ""
        if profile.base_type.strip():
            equipment_eligibility_id = card_id
            character_equipment_eligibilities.append(
                CharacterEquipmentEligibilityIR(
                    definition_key=EquipmentDefinitionKey(
                        "character_equipment_eligibility",
                        card_id,
                    ),
                    character_card_id=card_id,
                    character_profile_id=profile.avatar_profile_id,
                    character_path_type=profile.base_type,
                    passive_activation_path_types=(profile.base_type,),
                    source=profile.source,
                    coverage_status="lowered",
                    blocked_reason="",
                )
            )
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
                equipment_eligibility_id=equipment_eligibility_id,
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
                        "base_rank_id_list": _json_safe(
                            row.get("_character_card_base_rank_id_list") or row.get("RankIDList") or []
                        ),
                        "enhanced_rank_id_list": _json_safe(
                            row.get("_character_card_enhanced_rank_id_list") or []
                        ),
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
        character_equipment_eligibilities=character_equipment_eligibilities,
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
            level = int(_number_value(row.get("Level"), 1.0))
            action = {
                "action_id": f"{entity_type}:{raw_id}",
                "raw_skill_id": raw_id,
                "level": level,
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
                        "level": level,
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


def _eidolon_mechanism_slots(slot: CharacterEidolonSlotIR) -> tuple[CharacterMechanismSlotIR, ...]:
    skill_add_level_list = slot.semantics.get("skill_add_level_list")
    rank_ability = slot.semantics.get("rank_ability")
    extra_effect_id_list = slot.semantics.get("extra_effect_id_list")
    common_linked_ids = {
        "eidolon_slot_id": slot.eidolon_slot_id,
        "rank_id": slot.rank_id,
        "rank": slot.rank,
    }
    activation = {
        "kind": "eidolon_prefix_toggle",
        "required_eidolon_level": slot.rank,
        "enabled_when_requested_level_at_least": slot.rank,
        "prefix_closed": True,
    }
    result: list[CharacterMechanismSlotIR] = []
    if isinstance(skill_add_level_list, dict) and skill_add_level_list:
        result.append(
            CharacterMechanismSlotIR(
                mechanism_slot_id=f"character_mechanism_slot:{slot.character_data_card_id}:eidolon:{slot.rank}:skill_level",
                character_data_card_id=slot.character_data_card_id,
                mechanism_kind="eidolon_skill_level",
                runtime_system="character_card_assembly.skill_level_bonus",
                linked_ir_ids=common_linked_ids,
                activation=activation,
                semantics={"skill_add_level_list": skill_add_level_list},
                source=slot.source,
                coverage_status="executable",
            )
        )
    if isinstance(rank_ability, (list, tuple)) and rank_ability:
        result.append(
            CharacterMechanismSlotIR(
                mechanism_slot_id=f"character_mechanism_slot:{slot.character_data_card_id}:eidolon:{slot.rank}:ability",
                character_data_card_id=slot.character_data_card_id,
                mechanism_kind="eidolon_ability_hook",
                runtime_system="event_dispatch_or_effect_registry",
                linked_ir_ids=common_linked_ids,
                activation=activation,
                semantics={
                    "rank_ability": rank_ability,
                    "param_values": slot.semantics.get("param_values") or [],
                    "dynamic_value_bindings": slot.semantics.get("dynamic_value_bindings") or {},
                },
                source=slot.source,
                coverage_status="executable",
            )
        )
    if isinstance(extra_effect_id_list, (list, tuple)) and extra_effect_id_list:
        result.append(
            CharacterMechanismSlotIR(
                mechanism_slot_id=f"character_mechanism_slot:{slot.character_data_card_id}:eidolon:{slot.rank}:extra_effect",
                character_data_card_id=slot.character_data_card_id,
                mechanism_kind="eidolon_extra_effect",
                runtime_system="event_dispatch_or_effect_registry",
                linked_ir_ids=common_linked_ids,
                activation=activation,
                semantics={"extra_effect_id_list": extra_effect_id_list},
                source=slot.source,
                coverage_status="blocked",
                blocked_reason="eidolon_extra_effect_id_runtime_admission_pending",
            )
        )
    if not result:
        result.append(
            CharacterMechanismSlotIR(
                mechanism_slot_id=f"character_mechanism_slot:{slot.character_data_card_id}:eidolon:{slot.rank}:unbound",
                character_data_card_id=slot.character_data_card_id,
                mechanism_kind="eidolon_unbound",
                runtime_system="character_card_assembly",
                linked_ir_ids=common_linked_ids,
                activation=activation,
                semantics={},
                source=slot.source,
                coverage_status="blocked",
                blocked_reason="eidolon_slot_has_no_runtime_effect_source",
            )
        )
    return tuple(result)


def _trace_static_stat_terms(status_add_list: list[Any]) -> tuple[list[dict[str, JSONValue]], str]:
    mapped: list[dict[str, JSONValue]] = []
    for index, item in enumerate(status_add_list):
        if not isinstance(item, dict):
            return mapped, "trace_static_stat_item_not_object"
        property_type = str(item.get("PropertyType") or "")
        raw_value = _value_field(item.get("Value"))
        binding = static_property_binding(property_type)
        if binding is None:
            return mapped, f"trace_static_stat_property_not_admitted:{property_type or 'missing'}"
        if not isinstance(raw_value, (int, float, Decimal)):
            return mapped, f"trace_static_stat_value_not_numeric:{property_type}"
        value = canonical_decimal(raw_value, f"StatusAddList[{index}].Value")
        mapped.append(
            {
                "index": index,
                "property_type": property_type,
                "application_kind": binding.application_kind,
                "target_key": binding.canonical_property_type,
                "value": value,
                "raw_path": f"StatusAddList[{index}]",
            }
        )
    if not mapped:
        return mapped, "trace_static_stat_terms_missing"
    return mapped, ""


def _trace_unlock_requirements(
    row: dict[str, Any],
) -> tuple[int | None, int | None, tuple[str, ...], str]:
    errors: list[str] = []

    def optional_positive_int(field_name: str, *, allow_zero: bool) -> int | None:
        if field_name not in row:
            return None
        value = row.get(field_name)
        minimum = 0 if allow_zero else 1
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            errors.append(f"trace_unlock_{field_name}_invalid")
            return None
        return value

    required_promotion = optional_positive_int("AvatarPromotionLimit", allow_zero=True)
    required_character_level = optional_positive_int("AvatarLevelLimit", allow_zero=False)
    raw_prerequisites = row.get("PrePoint")
    prerequisite_trace_ids: list[str] = []
    if not isinstance(raw_prerequisites, list):
        errors.append("trace_unlock_PrePoint_missing_or_not_list")
    else:
        for value in raw_prerequisites:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, str))
                or not str(value).strip()
            ):
                errors.append("trace_unlock_PrePoint_identity_invalid")
                continue
            prerequisite_trace_ids.append(str(value))
    if len(set(prerequisite_trace_ids)) != len(prerequisite_trace_ids):
        errors.append("trace_unlock_PrePoint_duplicate")
    return (
        required_promotion,
        required_character_level,
        tuple(prerequisite_trace_ids),
        ";".join(sorted(set(errors))),
    )


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
            data = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
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
            default_unlocked = row.get("DefaultUnlock") is True
            (
                required_promotion,
                required_character_level,
                prerequisite_trace_ids,
                unlock_requirement_error,
            ) = _trace_unlock_requirements(row)
            source = IRSource(
                source_path=source.source_path,
                raw_type=source.raw_type,
                raw_id=source.raw_id,
                evidence={
                    **source.evidence,
                    "avatar_promotion_limit_present": "AvatarPromotionLimit" in row,
                    "avatar_promotion_limit": _json_safe(row.get("AvatarPromotionLimit")),
                    "avatar_level_limit_present": "AvatarLevelLimit" in row,
                    "avatar_level_limit": _json_safe(row.get("AvatarLevelLimit")),
                    "pre_point_present": "PrePoint" in row,
                    "pre_point": _json_safe(row.get("PrePoint")),
                },
            )
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
                            "default_enabled": default_unlocked,
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
                            "default_enabled": default_unlocked,
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
            level_up_skill_ids = tuple(str(value) for value in row.get("LevelUpSkillID") or ())
            if level_up_skill_ids:
                slot_id = f"character_mechanism_slot:{card_id}:trace:{point_id}:{level}:skill_level"
                linked_slot_ids.append(slot_id)
                slots.append(
                    CharacterMechanismSlotIR(
                        mechanism_slot_id=slot_id,
                        character_data_card_id=card_id,
                        mechanism_kind="trace_skill_level",
                        runtime_system="character_card_assembly.skill_level",
                        linked_ir_ids={"trace_node_id": trace_node_id},
                        activation={
                            "kind": "trace_unlock",
                            "trace_node_id": trace_node_id,
                            "default_enabled": default_unlocked,
                        },
                        semantics={
                            "node_level": level,
                            "level_up_skill_ids": list(level_up_skill_ids),
                        },
                        source=source,
                        coverage_status="executable",
                        blocked_reason="",
                    )
                )
            extra_effect_ids = tuple(str(value) for value in row.get("ExtraEffectIDList") or ())
            simple_extra_effect_ids = tuple(
                str(value) for value in row.get("SimpleExtraEffectIDList") or ()
            )
            if extra_effect_ids or simple_extra_effect_ids:
                slot_id = f"character_mechanism_slot:{card_id}:trace:{point_id}:{level}:extra_effect"
                linked_slot_ids.append(slot_id)
                slots.append(
                    CharacterMechanismSlotIR(
                        mechanism_slot_id=slot_id,
                        character_data_card_id=card_id,
                        mechanism_kind="trace_extra_effect",
                        runtime_system="event_dispatch_or_effect_registry",
                        linked_ir_ids={"trace_node_id": trace_node_id},
                        activation={
                            "kind": "trace_unlock",
                            "trace_node_id": trace_node_id,
                            "default_enabled": default_unlocked,
                        },
                        semantics={
                            "extra_effect_ids": list(extra_effect_ids),
                            "simple_extra_effect_ids": list(simple_extra_effect_ids),
                        },
                        source=source,
                        coverage_status="blocked",
                        blocked_reason="trace_extra_effect_runtime_admission_pending",
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
                    level=level,
                    max_level=int(_number_value(row.get("MaxLevel"), level)),
                    default_unlocked=default_unlocked,
                    required_promotion=required_promotion,
                    required_character_level=required_character_level,
                    prerequisite_trace_ids=prerequisite_trace_ids,
                    level_up_skill_ids=level_up_skill_ids,
                    extra_effect_ids=extra_effect_ids,
                    simple_extra_effect_ids=simple_extra_effect_ids,
                    source=source,
                    coverage_status="blocked" if unlock_requirement_error else "executable",
                    blocked_reason=unlock_requirement_error,
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
        mechanism_slot_ids: list[str] = []
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
        if rank_row_info is not None:
            if semantics["skill_add_level_list"]:
                mechanism_slot_ids.append(
                    f"character_mechanism_slot:{card_id}:eidolon:{index + 1}:skill_level"
                )
            if semantics["rank_ability"]:
                mechanism_slot_ids.append(
                    f"character_mechanism_slot:{card_id}:eidolon:{index + 1}:ability"
                )
            if semantics["extra_effect_id_list"]:
                mechanism_slot_ids.append(
                    f"character_mechanism_slot:{card_id}:eidolon:{index + 1}:extra_effect"
                )
            if not mechanism_slot_ids:
                mechanism_slot_ids.append(
                    f"character_mechanism_slot:{card_id}:eidolon:{index + 1}:unbound"
                )
        slots.append(
            CharacterEidolonSlotIR(
                eidolon_slot_id=f"character_eidolon_slot:{card_id}:rank:{index + 1}",
                character_data_card_id=card_id,
                avatar_id=avatar_id,
                rank=index + 1,
                rank_id=rank_id,
                linked_mechanism_slot_ids=tuple(mechanism_slot_ids),
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
            data = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
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
                if "SPNeed" in row:
                    copied["_character_card_max_energy_source_path"] = relative_path
                    copied["_character_card_max_energy_source_row_index"] = row_index
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
        merged["_character_card_base_rank_id_list"] = _json_safe(base_row.get("RankIDList") or [])
        merged["_character_card_enhanced_source_path"] = enhanced_relative_path
        merged["_character_card_enhanced_row_index"] = enhanced_row_index
        merged["_character_card_enhanced_id"] = enhanced_row.get("EnhancedID")
        merged["_character_card_enhanced_skill_list"] = _json_safe(enhanced_row.get("SkillList") or [])
        merged["_character_card_enhanced_rank_id_list"] = _json_safe(
            enhanced_row.get("RankIDList") or []
        )
        if "SPNeed" in enhanced_row:
            merged["_character_card_max_energy_source_path"] = enhanced_relative_path
            merged["_character_card_max_energy_source_row_index"] = enhanced_row_index
        elif "SPNeed" in base_row:
            merged["_character_card_max_energy_source_path"] = base_relative_path
            merged["_character_card_max_energy_source_row_index"] = base_row_index
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
        copied["_character_card_enhanced_rank_id_list"] = _json_safe(
            enhanced_row.get("RankIDList") or []
        )
        if "SPNeed" in enhanced_row:
            copied["_character_card_max_energy_source_path"] = enhanced_relative_path
            copied["_character_card_max_energy_source_row_index"] = enhanced_row_index
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
        data = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    rows: list[tuple[str, int, dict[str, Any]]] = []
    for row_index, row in enumerate(_limit_sequence(data, max_records_per_table)):
        if isinstance(row, dict) and row.get("AvatarID") is not None:
            rows.append((relative_path, row_index, dict(row)))
    return rows


def _promotion_rows_by_avatar(
    tbgd_root: Path,
) -> dict[str, list[tuple[str, int, dict[str, Any]]]]:
    rows: dict[str, list[tuple[str, int, dict[str, Any]]]] = {}
    for relative_path in ("ExcelOutput/AvatarPromotionConfig.json", "ExcelOutput/AvatarPromotionConfigLD.json"):
        path = tbgd_root / relative_path
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for row_index, row in enumerate(data):
            if isinstance(row, dict) and row.get("AvatarID") is not None:
                rows.setdefault(str(row["AvatarID"]), []).append(
                    (relative_path, row_index, row)
                )
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
    tbgd_root: Path,
    relative_path: str,
    row_index: int,
    row: dict[str, Any],
    promotion_rows: list[tuple[str, int, dict[str, Any]]],
    special_resource_skill_rows: dict[
        tuple[str, str], tuple[tuple[int, dict[str, Any]], ...]
    ],
) -> AvatarProfileIR:
    avatar_id = str(row["AvatarID"])
    skill_ids = tuple(str(skill_id) for skill_id in row.get("SkillList") or ())
    promotion_tiers, promotion_blocked_reason = _avatar_promotion_tiers(
        avatar_id,
        promotion_rows,
    )
    profile_source = IRSource(
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
            "max_energy_field_present": "SPNeed" in row,
            "max_energy_raw_path": "SPNeed",
            "max_energy_source_path": str(
                row.get("_character_card_max_energy_source_path") or relative_path
            ),
            "max_energy_source_row_index": _json_safe(
                row.get("_character_card_max_energy_source_row_index", row_index)
            ),
            "builder": "character_data_card_p8_s2",
        },
    )
    max_energy, max_energy_reason = _exact_decimal_field(row.get("SPNeed"), "SPNeed")
    special_resource_definition = None
    special_resource_source = None
    resource_mode = "standard_energy"
    if "SPNeed" not in row:
        special_resource_definition = _special_resource_definition_from_avatar_config(
            tbgd_root,
            avatar_id,
            row,
            special_resource_skill_rows,
        )
        if special_resource_definition is not None:
            resource_mode = "special_resource"
            special_resource_source = special_resource_definition.source
            max_energy_reason = (
                special_resource_definition.blocked_reason
                if special_resource_definition.coverage_status != "executable"
                else ""
            )
        else:
            resource_mode = "source_missing"
            max_energy_reason = "avatar_max_energy_source_missing"
    max_energy_source = (
        IRSource(
            source_path=str(
                row.get("_character_card_max_energy_source_path") or relative_path
            ),
            raw_type=Path(
                str(row.get("_character_card_max_energy_source_path") or relative_path)
            ).stem,
            raw_id=f"{avatar_id}:SPNeed",
            evidence={
                "row_index": int(
                    row.get("_character_card_max_energy_source_row_index", row_index)
                ),
                "avatar_id": avatar_id,
                "raw_path": "SPNeed",
                "field_present": "SPNeed" in row,
                "raw_value": _json_safe(row.get("SPNeed")),
            },
        )
        if max_energy is not None
        else None
    )
    blocked_reason = ""
    if not skill_ids:
        blocked_reason = "avatar_skill_list_missing"
    elif promotion_blocked_reason:
        blocked_reason = promotion_blocked_reason
    elif resource_mode == "standard_energy" and (max_energy_reason or max_energy is None):
        blocked_reason = max_energy_reason or "avatar_max_energy_source_missing"
    elif resource_mode == "source_missing":
        blocked_reason = max_energy_reason or "avatar_resource_source_missing"
    elif resource_mode == "special_resource" and max_energy_reason:
        blocked_reason = max_energy_reason
    return AvatarProfileIR(
        avatar_profile_id=f"avatar_profile:{avatar_id}",
        avatar_id=avatar_id,
        base_type=str(row.get("AvatarBaseType") or ""),
        damage_type=str(row.get("DamageType") or ""),
        skill_ids=skill_ids,
        promotion_tiers=promotion_tiers,
        max_energy=max_energy,
        max_energy_source=max_energy_source,
        resource_mode=resource_mode,  # type: ignore[arg-type]
        special_resource_source=special_resource_source,
        special_resource_definition=special_resource_definition,
        source=profile_source,
        coverage_status="blocked" if blocked_reason else "executable",
        blocked_reason=blocked_reason,
    )


def _special_resource_definition_from_avatar_config(
    tbgd_root: Path,
    avatar_id: str,
    avatar_row: dict[str, Any],
    skill_rows: dict[tuple[str, str], tuple[tuple[int, dict[str, Any]], ...]],
) -> SpecialResourceDefinitionIR | None:
    avatar_json_path = avatar_row.get("JsonPath")
    if not isinstance(avatar_json_path, str) or not avatar_json_path:
        return None
    avatar_stem = Path(avatar_json_path).stem.removesuffix("_Config")
    if not avatar_stem:
        return None
    relative_path = f"Config/ConfigAbility/Avatar/{avatar_stem}_Ability.json"
    path = tbgd_root / relative_path
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    object_nodes = tuple(_walk_json_objects(data))
    bar_nodes = tuple(
        (json_path, node)
        for json_path, node in object_nodes
        if _short_raw_type(node) == "SetSummonerEnergyBarState"
    )
    if not bar_nodes:
        return None
    current_properties = {
        value
        for _json_path, node in object_nodes
        for value in (node.get("Property"), node.get("Value"))
        if isinstance(value, str)
        and value.startswith("Current")
        and value.endswith("SpecialSP")
    }
    maximum_properties = {
        value
        for _json_path, node in object_nodes
        for value in (node.get("Property"), node.get("Value"))
        if isinstance(value, str)
        and value.startswith("Max")
        and value.endswith("SpecialSP")
    }
    reasons: list[str] = []
    if len(current_properties) != 1:
        reasons.append("special_resource_current_property_missing_or_ambiguous")
    if len(maximum_properties) != 1:
        reasons.append("special_resource_maximum_property_missing_or_ambiguous")
    current_property = next(iter(current_properties), "")
    maximum_property = next(iter(maximum_properties), "")
    initializer: SpecialResourceInitializerIR | None = None
    initializer_task_names: tuple[str, ...] = ()
    initializer_sources: tuple[IRSource, ...] = ()
    if current_property and maximum_property:
        (
            initializer,
            initializer_task_names,
            initializer_sources,
            initializer_reasons,
        ) = _special_resource_initializer_from_sources(
            tbgd_root=tbgd_root,
            avatar_id=avatar_id,
            avatar_row=avatar_row,
            ability_source_path=relative_path,
            object_nodes=object_nodes,
            current_property=current_property,
            maximum_property=maximum_property,
            skill_rows=skill_rows,
        )
        reasons.extend(initializer_reasons)
    else:
        reasons.append("special_resource_initializer_properties_unresolved")
    bar_sources = tuple(
        _special_resource_node_source(
            relative_path,
            avatar_id,
            json_path,
            node,
        )
        for json_path, node in bar_nodes
    )
    sources = _unique_ir_sources((*bar_sources, *initializer_sources))
    blocked_reason = ";".join(reasons)
    primary_source = IRSource(
        source_path=relative_path,
        raw_type="RPG.GameCore.SetSummonerEnergyBarState",
        raw_id=f"{avatar_id}:special_resource",
        evidence={
            "avatar_id": avatar_id,
            "avatar_json_path": avatar_json_path,
            "ability_path_derived_from_avatar_json_path": True,
            "matched_node_count": len(bar_nodes),
            "matched_json_paths": [path for path, _node in bar_nodes],
            "current_properties": sorted(current_properties),
            "maximum_properties": sorted(maximum_properties),
            "initializer_task_names": list(initializer_task_names),
            "initializer_id": initializer.initializer_id if initializer else "",
            "classification": "typed_special_resource_definition",
        },
    )
    return SpecialResourceDefinitionIR(
        resource_definition_id=f"special_resource_definition:avatar:{avatar_id}",
        current_property=current_property,
        maximum_property=maximum_property,
        current_resource_key=_runtime_resource_key(current_property),
        maximum_resource_key=_runtime_resource_key(maximum_property),
        initial_current_mode="ability_battle_entry_initializer",
        maximum_initialization_mode="ability_initializer",
        initializer_task_names=initializer_task_names,
        initializer=initializer,
        supporting_sources=sources,
        source=primary_source,
        coverage_status="blocked" if blocked_reason else "executable",
        blocked_reason=blocked_reason,
    )


def _avatar_skill_parameter_rows(
    tbgd_root: Path,
    *,
    skill_ids: set[str],
) -> dict[tuple[str, str], tuple[tuple[int, dict[str, Any]], ...]]:
    if not skill_ids:
        return {}
    path = tbgd_root / "ExcelOutput/AvatarSkillConfig.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    except Exception:
        return {}
    grouped: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]] = {}
    if isinstance(data, list):
        for row_index, row in enumerate(data):
            if not isinstance(row, dict) or str(row.get("SkillID")) not in skill_ids:
                continue
            trigger_key = row.get("SkillTriggerKey")
            if not isinstance(trigger_key, str) or not trigger_key:
                continue
            grouped.setdefault((str(row["SkillID"]), trigger_key), []).append(
                (row_index, row)
            )
    return {key: tuple(rows) for key, rows in grouped.items()}


def _special_resource_initializer_from_sources(
    *,
    tbgd_root: Path,
    avatar_id: str,
    avatar_row: dict[str, Any],
    ability_source_path: str,
    object_nodes: tuple[tuple[str, dict[str, Any]], ...],
    current_property: str,
    maximum_property: str,
    skill_rows: dict[tuple[str, str], tuple[tuple[int, dict[str, Any]], ...]],
) -> tuple[
    SpecialResourceInitializerIR | None,
    tuple[str, ...],
    tuple[IRSource, ...],
    tuple[str, ...],
]:
    reasons: list[str] = []
    template_candidates: list[tuple[str, dict[str, Any]]] = []
    for json_path, node in object_nodes:
        task_list = node.get("TaskList")
        task_name = node.get("Name")
        if not isinstance(task_name, str) or not task_name or not isinstance(task_list, list):
            continue
        stack_nodes = tuple(
            child
            for _child_path, child in _walk_json_objects(task_list)
            if _short_raw_type(child) == "StackProperty"
            and child.get("Property") == maximum_property
        )
        if stack_nodes:
            template_candidates.append((json_path, node))
    if len(template_candidates) != 1:
        return (
            None,
            (),
            (),
            ("special_resource_maximum_initializer_missing_or_ambiguous",),
        )
    template_path, template = template_candidates[0]
    template_name = str(template["Name"])
    template_nodes = tuple(
        _walk_json_objects(template.get("TaskList"), f"{template_path}.TaskList")
    )
    used_nodes: list[tuple[str, dict[str, Any]]] = [(template_path, template)]

    stack_nodes = tuple(
        (path, node)
        for path, node in template_nodes
        if _short_raw_type(node) == "StackProperty"
        and node.get("Property") == maximum_property
    )
    if len(stack_nodes) != 1:
        reasons.append("special_resource_maximum_stack_missing_or_ambiguous")
        maximum_hash = 0
    else:
        stack_path, stack_node = stack_nodes[0]
        used_nodes.append((stack_path, stack_node))
        stack_expression = lower_numeric_expression(stack_node.get("PropertyValue"))
        stack_hashes = _integer_dynamic_hashes(stack_expression)
        if len(stack_hashes) != 1:
            reasons.append("special_resource_maximum_stack_binding_invalid")
            maximum_hash = 0
        else:
            maximum_hash = stack_hashes[0]

    maximum_key_candidates = {
        key
        for _path, node in template_nodes
        if _short_raw_type(node) == "SetDynamicValue"
        for key in (_dynamic_key_name(node.get("DynamicKey")),)
        if key and tbgd_dynamic_key_hash(key) == maximum_hash
    }
    if len(maximum_key_candidates) != 1:
        reasons.append("special_resource_maximum_dynamic_key_missing_or_ambiguous")
        maximum_key = ""
    else:
        maximum_key = next(iter(maximum_key_candidates))

    world_nodes = tuple(
        (path, node)
        for path, node in template_nodes
        if _short_raw_type(node) == "SetDynamicValueByWorldLevel"
    )
    if len(world_nodes) != 1:
        reasons.append("special_resource_world_level_binding_missing_or_ambiguous")
        world_key = ""
    else:
        world_path, world_node = world_nodes[0]
        used_nodes.append((world_path, world_node))
        world_key = _dynamic_key_name(world_node.get("DynamicKey"))
        if not world_key:
            reasons.append("special_resource_world_level_dynamic_key_missing")

    direct_tasks = tuple(
        (f"{template_path}.TaskList[{index}]", task)
        for index, task in enumerate(template.get("TaskList") or ())
        if isinstance(task, dict)
    )
    world_predicates = tuple(
        (path, node)
        for path, node in direct_tasks
        if _short_raw_type(node) == "PredicateTaskList"
        and _short_raw_type(node.get("Predicate")) == "ByCompareDynamicValue"
        and _dynamic_key_name(node["Predicate"].get("DynamicKey")) == world_key
    )
    world_level_threshold = 0
    low_expression: dict[str, JSONValue] = lower_numeric_expression(None)
    high_expression: dict[str, JSONValue] = lower_numeric_expression(None)
    level_key = ""
    level_hash = 0
    zero_floor_hash = 0
    if len(world_predicates) != 1:
        reasons.append("special_resource_world_level_branch_missing_or_ambiguous")
    else:
        predicate_path, predicate_task = world_predicates[0]
        used_nodes.append((predicate_path, predicate_task))
        predicate = predicate_task["Predicate"]
        threshold = _fixed_integer(predicate.get("CompareValue"))
        if predicate.get("CompareType") != "Less" or threshold is None or threshold < 0:
            reasons.append("special_resource_world_level_predicate_not_admitted")
        else:
            world_level_threshold = threshold
        low_assignments = _dynamic_value_assignments(
            predicate_task.get("SuccessTaskList"), maximum_key, predicate_path + ".SuccessTaskList"
        )
        high_assignments = _dynamic_value_assignments(
            predicate_task.get("FailedTaskList"), maximum_key, predicate_path + ".FailedTaskList"
        )
        if len(low_assignments) != 1 or len(high_assignments) != 1:
            reasons.append("special_resource_world_level_values_missing_or_ambiguous")
        else:
            low_path, low_node = low_assignments[0]
            high_path, high_node = high_assignments[0]
            used_nodes.extend(((low_path, low_node), (high_path, high_node)))
            low_expression = lower_numeric_expression(low_node.get("Value"))
            high_expression = lower_numeric_expression(high_node.get("Value"))
        level_bindings = tuple(
            (path, node)
            for path, node in _walk_json_objects(
                predicate_task.get("SuccessTaskList"),
                predicate_path + ".SuccessTaskList",
            )
            if _short_raw_type(node) == "SetDynamicValueByProperty"
            and node.get("Value") == "Level"
            and _target_alias(node.get("ReadTargetType")) == "ParamEntity"
        )
        if len(level_bindings) != 1:
            reasons.append("special_resource_level_binding_missing_or_ambiguous")
        else:
            level_path, level_node = level_bindings[0]
            used_nodes.append((level_path, level_node))
            level_key = _dynamic_key_name(level_node.get("DynamicKey"))
            level_hash = tbgd_dynamic_key_hash(level_key) if level_key else 0
        if not _highest_alive_non_servant_retarget(predicate_task.get("SuccessTaskList")):
            reasons.append("special_resource_level_source_not_admitted")
        low_hashes = set(_integer_dynamic_hashes(low_expression))
        high_hashes = set(_integer_dynamic_hashes(high_expression))
        zero_candidates = low_hashes - {level_hash}
        if (
            not is_typed_numeric_expression(low_expression)
            or not is_typed_numeric_expression(high_expression)
            or level_hash == 0
            or low_hashes != {level_hash, *zero_candidates}
            or len(zero_candidates) != 1
            or high_hashes != zero_candidates
        ):
            reasons.append("special_resource_maximum_expression_bindings_invalid")
        else:
            zero_floor_hash = next(iter(zero_candidates))

    minimum_predicates = tuple(
        (path, node)
        for path, node in direct_tasks
        if _short_raw_type(node) == "PredicateTaskList"
        and _short_raw_type(node.get("Predicate")) == "ByCompareDynamicValue"
        and _dynamic_key_name(node["Predicate"].get("DynamicKey")) == maximum_key
        and node["Predicate"].get("CompareType") == "LessEqual"
    )
    minimum_expression: dict[str, JSONValue] = lower_numeric_expression(None)
    if len(minimum_predicates) != 1:
        reasons.append("special_resource_minimum_branch_missing_or_ambiguous")
    else:
        minimum_path, minimum_task = minimum_predicates[0]
        used_nodes.append((minimum_path, minimum_task))
        minimum_expression = lower_numeric_expression(
            minimum_task["Predicate"].get("CompareValue")
        )
        assignments = _dynamic_value_assignments(
            minimum_task.get("SuccessTaskList"), maximum_key, minimum_path + ".SuccessTaskList"
        )
        if (
            len(assignments) != 1
            or numeric_fixed_value(minimum_expression) is None
            or numeric_fixed_value(lower_numeric_expression(assignments[0][1].get("Value")))
            != numeric_fixed_value(minimum_expression)
        ):
            reasons.append("special_resource_minimum_assignment_invalid")
        else:
            used_nodes.append(assignments[0])

    (
        initial_expression,
        initial_binding_hash,
        initial_task_name,
        initial_nodes,
        initial_reason,
    ) = _special_resource_initial_current_source(
        object_nodes,
        maximum_hash=maximum_hash,
    )
    used_nodes.extend(initial_nodes)
    if initial_reason:
        reasons.append(initial_reason)
    binding_value, binding_sources, binding_reason = _resolve_special_resource_parameter(
        tbgd_root=tbgd_root,
        avatar_id=avatar_id,
        avatar_row=avatar_row,
        dynamic_hash=initial_binding_hash,
        skill_rows=skill_rows,
    )
    if binding_reason:
        reasons.append(binding_reason)

    sources = _unique_ir_sources(
        tuple(
            _special_resource_node_source(
                ability_source_path,
                avatar_id,
                json_path,
                node,
            )
            for json_path, node in used_nodes
        )
        + binding_sources
    )
    task_names = tuple(sorted({template_name, initial_task_name} - {""}))
    if reasons:
        return None, task_names, sources, tuple(sorted(set(reasons)))
    primary_source = _special_resource_node_source(
        ability_source_path,
        avatar_id,
        template_path,
        template,
        evidence={
            "classification": "special_resource_initializer",
            "maximum_property": maximum_property,
            "current_property": current_property,
            "maximum_value_dynamic_key": maximum_key,
            "maximum_value_dynamic_hash": maximum_hash,
            "level_dynamic_key": level_key,
            "level_dynamic_hash": level_hash,
            "zero_floor_dynamic_hash": zero_floor_hash,
            "world_level_threshold": world_level_threshold,
            "initial_current_binding_hash": initial_binding_hash,
            "initial_current_binding_value": binding_value,
        },
    )
    return (
        SpecialResourceInitializerIR(
            initializer_id=f"special_resource_initializer:avatar:{avatar_id}",
            maximum_value_dynamic_key=maximum_key,
            maximum_value_dynamic_hash=maximum_hash,
            level_dynamic_key=level_key,
            level_dynamic_hash=level_hash,
            zero_floor_dynamic_hash=zero_floor_hash,
            world_level_threshold=world_level_threshold,
            low_world_level_expression=low_expression,
            high_world_level_expression=high_expression,
            minimum_expression=minimum_expression,
            initial_current_expression=initial_expression,
            initial_current_binding_hash=initial_binding_hash,
            initial_current_binding_value=binding_value,
            level_source="highest_alive_non_servant_ally",
            initial_current_trigger="first_wave_battle_entry_without_technique",
            sources=sources,
            source=primary_source,
            coverage_status="executable",
            blocked_reason="",
        ),
        task_names,
        sources,
        (),
    )


def _special_resource_initial_current_source(
    object_nodes: tuple[tuple[str, dict[str, Any]], ...],
    *,
    maximum_hash: int,
) -> tuple[
    dict[str, JSONValue],
    int,
    str,
    list[tuple[str, dict[str, Any]]],
    str,
]:
    candidates: list[
        tuple[
            dict[str, JSONValue],
            int,
            str,
            list[tuple[str, dict[str, Any]]],
        ]
    ] = []
    for event_path, event_node in object_nodes:
        if event_node.get("Event") != "OnEnterBattle":
            continue
        for predicate_path, task in _walk_json_objects(
            event_node.get("CallbackConfig"), event_path + ".CallbackConfig"
        ):
            if _short_raw_type(task) != "PredicateTaskList":
                continue
            predicates = task.get("Predicate", {}).get("PredicateList") if isinstance(task.get("Predicate"), dict) else None
            if _short_raw_type(task.get("Predicate")) != "ByAnd" or not isinstance(predicates, list):
                continue
            wave_predicates = tuple(
                item
                for item in predicates
                if isinstance(item, dict)
                and _short_raw_type(item) == "ByCompareWaveCount"
                and item.get("CompareType") == "Equal"
                and _fixed_integer(item.get("CompareValue")) == 1
            )
            gate_predicates = tuple(
                item
                for item in predicates
                if isinstance(item, dict)
                and _short_raw_type(item) == "ByCompareDynamicValue"
                and item.get("CompareType") == "LessEqual"
                and numeric_fixed_value(lower_numeric_expression(item.get("CompareValue"))) == 0.0
            )
            if len(wave_predicates) != 1 or len(gate_predicates) != 1 or len(predicates) != 2:
                continue
            for include_path, include in _walk_json_objects(
                task.get("SuccessTaskList"), predicate_path + ".SuccessTaskList"
            ):
                if _short_raw_type(include) != "IncludeTaskListTemplate":
                    continue
                task_name = include.get("Name")
                dynamic_values = include.get("DynamicValues")
                if not isinstance(task_name, str) or not task_name or not isinstance(dynamic_values, dict):
                    continue
                expressions = tuple(
                    lower_numeric_expression(raw_expression)
                    for raw_expression in dynamic_values.values()
                )
                matching = tuple(
                    expression
                    for expression in expressions
                    if maximum_hash in _integer_dynamic_hashes(expression)
                )
                if len(matching) != 1:
                    continue
                hashes = set(_integer_dynamic_hashes(matching[0]))
                binding_hashes = hashes - {maximum_hash}
                if (
                    len(binding_hashes) != 1
                    or hashes != {maximum_hash, *binding_hashes}
                    or not _is_direct_dynamic_product(
                        matching[0],
                        maximum_hash,
                        next(iter(binding_hashes)),
                    )
                ):
                    continue
                candidates.append(
                    (
                        matching[0],
                        next(iter(binding_hashes)),
                        task_name,
                        [(event_path, event_node), (predicate_path, task), (include_path, include)],
                    )
                )
    if len(candidates) != 1:
        return (
            lower_numeric_expression(None),
            0,
            "",
            [],
            "special_resource_initial_current_source_missing_or_ambiguous",
        )
    expression, binding_hash, task_name, nodes = candidates[0]
    return expression, binding_hash, task_name, nodes, ""


def _resolve_special_resource_parameter(
    *,
    tbgd_root: Path,
    avatar_id: str,
    avatar_row: dict[str, Any],
    dynamic_hash: int,
    skill_rows: dict[tuple[str, str], tuple[tuple[int, dict[str, Any]], ...]],
) -> tuple[str, tuple[IRSource, ...], str]:
    character_path = avatar_row.get("JsonPath")
    if not isinstance(character_path, str) or not character_path or dynamic_hash == 0:
        return "", (), "special_resource_initial_parameter_binding_missing"
    try:
        character_data = json.loads(
            (tbgd_root / character_path).read_text(encoding="utf-8")
        )
    except Exception:
        return "", (), "special_resource_character_config_unreadable"
    binding_nodes = tuple(
        (f"{json_path}.{dynamic_hash}", value)
        for json_path, node in _walk_json_objects(character_data)
        for key, value in node.items()
        if key == str(dynamic_hash)
        and isinstance(value, dict)
        and isinstance(value.get("ReadInfo"), dict)
        and value["ReadInfo"].get("Type") == "SkillParam"
    )
    if len(binding_nodes) != 1:
        return "", (), "special_resource_initial_parameter_binding_missing_or_ambiguous"
    binding_path, binding_node = binding_nodes[0]
    read_info = binding_node["ReadInfo"]
    trigger_key = read_info.get("TriggerKey")
    parameter_index = read_info.get("Index")
    if (
        not isinstance(trigger_key, str)
        or not trigger_key
        or not isinstance(parameter_index, int)
        or isinstance(parameter_index, bool)
        or parameter_index < 0
    ):
        return "", (), "special_resource_initial_parameter_read_info_invalid"
    skill_ids = {str(value) for value in avatar_row.get("SkillList") or ()}
    matched_rows = tuple(
        (row_index, row)
        for skill_id in skill_ids
        for row_index, row in skill_rows.get((skill_id, trigger_key), ())
    )
    values: set[str] = set()
    value_rows: list[tuple[int, dict[str, Any]]] = []
    for row_index, row in matched_rows:
        parameters = row.get("ParamList")
        if not isinstance(parameters, list) or parameter_index >= len(parameters):
            continue
        raw_value = parameters[parameter_index]
        raw_value = raw_value.get("Value") if isinstance(raw_value, dict) else raw_value
        try:
            value = canonical_decimal(raw_value, "special_resource_initial_parameter")
        except (TypeError, ValueError):
            continue
        values.add(value)
        value_rows.append((row_index, row))
    if len(values) != 1 or not value_rows:
        return "", (), "special_resource_initial_parameter_value_missing_or_conflicting"
    binding_source = IRSource(
        source_path=character_path,
        raw_type=Path(character_path).stem,
        raw_id=f"{avatar_id}:dynamic:{dynamic_hash}",
        evidence={
            "avatar_id": avatar_id,
            "json_path": binding_path,
            "dynamic_hash": dynamic_hash,
            "read_info": _json_safe(read_info),
        },
    )
    row_sources = tuple(
        IRSource(
            source_path="ExcelOutput/AvatarSkillConfig.json",
            raw_type="AvatarSkillConfig",
            raw_id=f"{row.get('SkillID')}:{row.get('Level')}",
            evidence={
                "row_index": row_index,
                "skill_id": _json_safe(row.get("SkillID")),
                "skill_trigger_key": trigger_key,
                "level": _json_safe(row.get("Level")),
                "parameter_index": parameter_index,
                "parameter_value": next(iter(values)),
            },
        )
        for row_index, row in value_rows
    )
    return next(iter(values)), (binding_source, *row_sources), ""


def _dynamic_value_assignments(
    value: object,
    dynamic_key: str,
    json_path: str,
) -> tuple[tuple[str, dict[str, Any]], ...]:
    return tuple(
        (path, node)
        for path, node in _walk_json_objects(value, json_path)
        if _short_raw_type(node) == "SetDynamicValue"
        and _dynamic_key_name(node.get("DynamicKey")) == dynamic_key
    )


def _highest_alive_non_servant_retarget(value: object) -> bool:
    candidates = tuple(
        node
        for _path, node in _walk_json_objects(value)
        if _short_raw_type(node) == "Retarget"
    )
    if len(candidates) != 1:
        return False
    retarget = candidates[0]
    if _fixed_integer(retarget.get("MaxNumber")) != 1:
        return False
    target = retarget.get("TargetType")
    if not isinstance(target, dict) or _short_raw_type(target) != "TargetSequence":
        return False
    sequence = target.get("Sequence")
    if not isinstance(sequence, list) or len(sequence) != 2:
        return False
    alias, ordering = sequence
    return bool(
        _target_alias(alias) == "AllLightTeam.RemoveServant"
        and isinstance(ordering, dict)
        and _short_raw_type(ordering) == "TargetSortByProperty"
        and ordering.get("PropertyType") == "Level"
        and ordering.get("HighestFirst") is True
        and ordering.get("AliveOnly") is True
    )


def _integer_dynamic_hashes(expression: object) -> tuple[int, ...]:
    values: list[int] = []
    for value in numeric_dynamic_hashes(expression):
        if isinstance(value, int) and not isinstance(value, bool):
            values.append(value)
        elif isinstance(value, float) and value.is_integer():
            values.append(int(value))
    return tuple(values)


def _is_direct_dynamic_product(
    expression: object,
    left_hash: int,
    right_hash: int,
) -> bool:
    if not isinstance(expression, dict) or expression.get("kind") != "program":
        return False
    instructions = expression.get("instructions")
    if not isinstance(instructions, list) or len(instructions) != 4:
        return False
    return bool(
        {
            instruction.get("hash")
            for instruction in instructions[:2]
            if isinstance(instruction, dict)
            and instruction.get("opcode") == "push_dynamic"
        }
        == {left_hash, right_hash}
        and isinstance(instructions[2], dict)
        and instructions[2].get("opcode") == "mul"
        and isinstance(instructions[3], dict)
        and instructions[3].get("opcode") == "end"
    )


def _fixed_integer(value: object) -> int | None:
    fixed = numeric_fixed_value(lower_numeric_expression(value))
    if fixed is None or not float(fixed).is_integer():
        return None
    return int(fixed)


def _dynamic_key_name(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("Value"), str):
        return str(value["Value"])
    return ""


def _target_alias(value: object) -> str:
    if not isinstance(value, dict) or _short_raw_type(value) != "TargetAlias":
        return ""
    alias = value.get("Alias")
    return alias if isinstance(alias, str) else ""


def _short_raw_type(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    return str(value.get("$type") or "").removeprefix("RPG.GameCore.")


def _walk_json_objects(
    value: object,
    json_path: str = "$",
):
    if isinstance(value, dict):
        yield json_path, value
        for key, child in value.items():
            yield from _walk_json_objects(child, f"{json_path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_json_objects(child, f"{json_path}[{index}]")


def _special_resource_node_source(
    source_path: str,
    avatar_id: str,
    json_path: str,
    node: dict[str, Any],
    *,
    evidence: dict[str, JSONValue] | None = None,
) -> IRSource:
    return IRSource(
        source_path=source_path,
        raw_type=_short_raw_type(node) or "SpecialResourceNode",
        raw_id=f"{avatar_id}:special_resource:{json_path}",
        evidence={
            "avatar_id": avatar_id,
            "json_path": json_path,
            "payload_keys": sorted(str(key) for key in node),
            **(evidence or {}),
        },
    )


def _unique_ir_sources(sources: tuple[IRSource, ...]) -> tuple[IRSource, ...]:
    unique: dict[tuple[str, str, str], IRSource] = {}
    for source in sources:
        unique[(source.source_path, source.raw_type, source.raw_id)] = source
    return tuple(unique[key] for key in sorted(unique))


def _runtime_resource_key(property_name: str) -> str:
    if not property_name:
        return ""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", property_name).lower()


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


_PROMOTION_DECIMAL_FIELDS = (
    "HPBase",
    "HPAdd",
    "AttackBase",
    "AttackAdd",
    "DefenceBase",
    "DefenceAdd",
    "SpeedBase",
    "CriticalChance",
    "CriticalDamage",
    "BaseAggro",
)


def _exact_decimal_field(value: Any, field_name: str) -> tuple[str | None, str]:
    raw_value = value.get("Value") if isinstance(value, dict) else value
    if not isinstance(raw_value, (int, Decimal)) or isinstance(raw_value, bool):
        return None, f"{field_name}_missing_or_not_exact_numeric"
    try:
        return canonical_decimal(raw_value, field_name), ""
    except (TypeError, ValueError):
        return None, f"{field_name}_invalid_decimal"


def _avatar_promotion_tiers(
    avatar_id: str,
    rows: list[tuple[str, int, dict[str, Any]]],
) -> tuple[tuple[AvatarPromotionTierIR, ...], str]:
    tiers: list[AvatarPromotionTierIR] = []
    row_signatures: dict[int, list[tuple[object, ...]]] = {}
    integrity_errors: list[str] = []
    for relative_path, row_index, row in rows:
        field_present = "Promotion" in row
        raw_promotion = row.get("Promotion")
        if field_present and (not isinstance(raw_promotion, int) or isinstance(raw_promotion, bool)):
            promotion = -1
            row_errors = ["promotion_not_integer"]
        else:
            promotion = int(raw_promotion) if field_present else 0
            row_errors = []
        if promotion < 0:
            row_errors.append("promotion_negative")
        max_level = row.get("MaxLevel")
        if not isinstance(max_level, int) or isinstance(max_level, bool) or max_level <= 0:
            row_errors.append("promotion_max_level_invalid")
            typed_max_level = 0
        else:
            typed_max_level = max_level
        exact_values: dict[str, str] = {}
        for field_name in _PROMOTION_DECIMAL_FIELDS:
            exact_value, error = _exact_decimal_field(row.get(field_name), field_name)
            if error or exact_value is None:
                row_errors.append(error or f"{field_name}_missing")
                exact_values[field_name] = "0"
            else:
                exact_values[field_name] = exact_value
        source = IRSource(
            source_path=relative_path,
            raw_type=Path(relative_path).stem,
            raw_id=f"{avatar_id}:{promotion}:{row_index}",
            evidence={
                "row_index": row_index,
                "avatar_id": avatar_id,
                "promotion_raw_path": "Promotion",
                "promotion_field_present": field_present,
                "promotion_zero_semantic_from_missing_field": not field_present,
                "raw_promotion": _json_safe(raw_promotion),
                "max_level_raw_path": "MaxLevel",
                "stat_raw_paths": list(_PROMOTION_DECIMAL_FIELDS),
            },
        )
        signature = (
            typed_max_level,
            *(exact_values[name] for name in _PROMOTION_DECIMAL_FIELDS),
        )
        row_signatures.setdefault(promotion, []).append(signature)
        tiers.append(
            AvatarPromotionTierIR(
                promotion_tier_id=f"avatar_promotion_tier:{avatar_id}:{promotion}",
                avatar_id=avatar_id,
                promotion=promotion,
                promotion_field_present=field_present,
                max_level=typed_max_level,
                hp_base=exact_values["HPBase"],
                hp_add=exact_values["HPAdd"],
                attack_base=exact_values["AttackBase"],
                attack_add=exact_values["AttackAdd"],
                defense_base=exact_values["DefenceBase"],
                defense_add=exact_values["DefenceAdd"],
                speed_base=exact_values["SpeedBase"],
                critical_chance=exact_values["CriticalChance"],
                critical_damage=exact_values["CriticalDamage"],
                base_aggro=exact_values["BaseAggro"],
                source=source,
                coverage_status="blocked" if row_errors else "executable",
                blocked_reason=";".join(sorted(set(row_errors))),
            )
        )
        integrity_errors.extend(row_errors)
    if not tiers:
        integrity_errors.append("avatar_promotion_tiers_missing")
    duplicate_promotions = sorted(
        promotion for promotion, signatures in row_signatures.items() if len(signatures) > 1
    )
    if duplicate_promotions:
        conflict_promotions = [
            promotion
            for promotion in duplicate_promotions
            if len(set(row_signatures[promotion])) > 1
        ]
        integrity_errors.append(
            "promotion_tier_conflict" if conflict_promotions else "promotion_tier_duplicate"
        )
    non_negative_promotions = sorted(promotion for promotion in row_signatures if promotion >= 0)
    if non_negative_promotions:
        expected = list(range(non_negative_promotions[-1] + 1))
        if non_negative_promotions != expected:
            integrity_errors.append("promotion_tier_missing_or_non_contiguous")
    ordered = tuple(sorted(tiers, key=lambda tier: (tier.promotion, tier.source.source_path, tier.source.raw_id)))
    return ordered, ";".join(sorted(set(error for error in integrity_errors if error)))


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
    if isinstance(extracted, (int, float, Decimal)):
        return float(extracted)
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    return default


def _number_items(value: Any) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[float] = []
    for item in value:
        extracted = _value_field(item)
        if isinstance(extracted, (int, float, Decimal)):
            result.append(float(extracted))
    return tuple(result)


def _value_field(value: Any) -> Decimal | float | int | None:
    if isinstance(value, dict):
        inner = value.get("Value")
        return inner if isinstance(inner, (int, float, Decimal)) else None
    return value if isinstance(value, (int, float, Decimal)) else None


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
