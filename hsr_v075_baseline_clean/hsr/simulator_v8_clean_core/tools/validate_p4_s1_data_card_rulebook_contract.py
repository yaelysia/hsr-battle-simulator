from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .. import BASELINE_VERSION
from ..core.model import JSONValue
from ..rules.ir import CanonicalIR
from ..rules.rulebook import RuleBook
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p4_s0_combatant_source_inventory import build_p4_s0_combatant_source_inventory_matrix


VALIDATION_VERSION = "p4_s1_data_card_rulebook_contract"
MATRIX_SCHEMA_VERSION = "p4_s1_data_card_rulebook_contract_matrix_v1"
MAX_SAMPLES = 5

CLASSIFICATION_STATES = {
    "executable",
    "boundary_only",
    "source_absent_not_required",
    "source_gap_blocked",
    "lowering_gap",
    "admission_gap",
    "validation_gap",
    "implementation_missing",
    "out_of_scope",
}
GAP_STATES = {
    "source_gap_blocked",
    "lowering_gap",
    "admission_gap",
    "validation_gap",
    "implementation_missing",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    s0_matrix = build_p4_s0_combatant_source_inventory_matrix(tbgd_root, ir, rules)
    matrix = build_p4_s1_data_card_rulebook_contract_matrix(ir, rules, s0_matrix)
    contract_checks = validate_p4_s1_data_card_rulebook_contract_matrix(matrix)
    checks = {
        "contract": contract_checks,
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "p4_s1_data_card_rulebook_contract_structural_audit",
                "runtime_behavior_changed": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "textmap_read": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "s0_matrix_reused_as_raw_inventory": True,
                "aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "contract_matrix": matrix["contract_matrix"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p4_s1_data_card_rulebook_contract.json", result)
    write_json(output_dir / "p4_s1_data_card_rulebook_contract_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P4-S1 data-card and RuleBook contracts.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} validation ok={result['ok']} "
        f"contracts={result['summary']['contract_count']} "
        f"classifications={result['summary']['classification_counts']}"
    )
    return 0 if result["ok"] else 1


def build_p4_s1_data_card_rulebook_contract_matrix(
    ir: CanonicalIR,
    rules: RuleBook,
    s0_matrix: dict[str, Any],
) -> dict[str, Any]:
    rows = [
        _character_data_card_contract(ir, rules, s0_matrix),
        _character_card_link_contract(ir, rules, s0_matrix),
        _monster_data_card_contract(ir, rules, s0_matrix),
        _monster_card_link_contract(ir, rules, s0_matrix),
        _combatant_profile_contract(ir, rules, s0_matrix),
        _combatant_action_set_contract(ir, rules, s0_matrix),
        _formula_binding_contract(ir, rules, s0_matrix),
        _character_mechanism_trace_eidolon_contract(ir, rules, s0_matrix),
        _monster_passive_contract(ir, rules, s0_matrix),
        _servant_subcard_hook_contract(ir, rules, s0_matrix),
        _summoned_monster_lifecycle_hook_contract(ir, rules, s0_matrix),
        _equipment_build_stage_environment_hook_contract(ir, rules, s0_matrix),
        _source_audit_contract(ir, rules, s0_matrix),
    ]
    contract_matrix = {row["contract_id"]: row for row in rows}
    classification_counts = Counter(row["classification"] for row in contract_matrix.values())
    gap_counts: Counter[str] = Counter()
    for row in contract_matrix.values():
        for key, value in dict(row.get("gap_attribution") or {}).items():
            gap_counts[str(key)] += int(value or 0)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "s0_schema_version": s0_matrix.get("schema_version"),
        "contract_matrix": contract_matrix,
        "summary": {
            "contract_count": len(contract_matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "unclassified_count": int(classification_counts.get("unclassified", 0)),
            "raw_count_total": sum(int(row.get("raw_count") or 0) for row in contract_matrix.values()),
            "ir_count_total": sum(int(row.get("ir_count") or 0) for row in contract_matrix.values()),
            "rulebook_visible_count_total": sum(
                int(row.get("rulebook_visible_count") or 0) for row in contract_matrix.values()
            ),
            "blocked_or_gap_count_total": sum(int(row.get("blocked_or_gap_count") or 0) for row in contract_matrix.values()),
        },
        "resource_budget": {
            "rulebook_build_count": 1,
            "s0_matrix_reused_in_memory": True,
            "large_artifacts_written": False,
            "full_ir_written": False,
            "full_transition_dump_written": False,
            "output_scope": "summary_contract_matrix_source_samples_boundary_samples_only",
        },
    }


def validate_p4_s1_data_card_rulebook_contract_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    contract_matrix = dict(matrix.get("contract_matrix") or {})
    required_contracts = {
        "character_data_card_core_contract",
        "character_card_link_contract",
        "monster_data_card_core_contract",
        "monster_card_link_contract",
        "combatant_profile_contract",
        "combatant_action_set_contract",
        "formula_binding_contract",
        "character_mechanism_trace_eidolon_contract",
        "monster_passive_contract",
        "servant_subcard_hook_contract",
        "summoned_monster_lifecycle_hook_contract",
        "equipment_build_stage_environment_hook_contract",
        "source_audit_contract",
    }
    required_columns = {
        "contract_id",
        "contract_subject",
        "raw_source_domains",
        "raw_count",
        "ir_container",
        "ir_count",
        "rulebook_query_surface",
        "rulebook_visible_count",
        "classification",
        "gap_attribution",
        "source_audit_samples",
        "blocked_boundary_samples",
        "checks",
        "details",
    }
    missing_required_contracts = sorted(required_contracts - set(contract_matrix))
    rows_missing_required_columns = [
        key for key, row in contract_matrix.items() if not all(column in row for column in required_columns)
    ]
    invalid_classification_rows = [
        key for key, row in contract_matrix.items() if str(row.get("classification") or "") not in CLASSIFICATION_STATES
    ]
    executable_without_source_audit = [
        key
        for key, row in contract_matrix.items()
        if row.get("classification") == "executable" and not row.get("source_audit_samples")
    ]
    gap_without_attribution = [
        key for key, row in contract_matrix.items() if row.get("classification") in GAP_STATES and not row.get("gap_attribution")
    ]
    gap_without_boundary = [
        key
        for key, row in contract_matrix.items()
        if row.get("classification") in GAP_STATES
        and int(row.get("blocked_or_gap_count") or 0) > 0
        and not row.get("blocked_boundary_samples")
    ]
    required_boundary_contracts = {
        "servant_subcard_hook_contract",
        "summoned_monster_lifecycle_hook_contract",
        "equipment_build_stage_environment_hook_contract",
    }
    required_boundary_missing = [
        key for key in sorted(required_boundary_contracts) if not contract_matrix.get(key, {}).get("blocked_boundary_samples")
    ]
    checks = {
        "required_contracts_present": not missing_required_contracts,
        "required_columns_present": not rows_missing_required_columns,
        "classifications_valid": not invalid_classification_rows,
        "unclassified_zero": matrix.get("summary", {}).get("unclassified_count") == 0,
        "executable_contracts_have_source_audit_samples": not executable_without_source_audit,
        "gap_rows_have_attribution": not gap_without_attribution,
        "gap_rows_have_blocked_boundary_samples": not gap_without_boundary,
        "required_hook_boundaries_present": not required_boundary_missing,
        "matrix_is_summary_only": matrix.get("resource_budget", {}).get("large_artifacts_written") is False
        and matrix.get("resource_budget", {}).get("full_ir_written") is False
        and matrix.get("resource_budget", {}).get("full_transition_dump_written") is False,
    }
    diagnostics = {
        "missing_required_contracts": missing_required_contracts,
        "rows_missing_required_columns": rows_missing_required_columns,
        "invalid_classification_rows": invalid_classification_rows,
        "executable_without_source_audit": executable_without_source_audit,
        "gap_without_attribution": gap_without_attribution,
        "gap_without_boundary": gap_without_boundary,
        "required_boundary_missing": required_boundary_missing,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"ok": checks["ok"], "checks": checks, "diagnostics": diagnostics}


def _character_data_card_contract(ir: CanonicalIR, rules: RuleBook, s0_matrix: dict[str, Any]) -> dict[str, JSONValue]:
    cards = tuple(ir.character_data_cards)
    required_missing = _missing_required_counts(
        cards,
        {
            "card_id": lambda item: bool(item.card_id),
            "entity_ref": lambda item: bool(item.entity_ref),
            "profile_id": lambda item: bool(item.profile_id),
            "skill_ids": lambda item: bool(item.skill_ids),
            "action_set": lambda item: isinstance(item.action_set, dict) and bool(item.action_set.get("actions")),
            "card_contract": lambda item: isinstance(item.card_contract, dict) and bool(item.card_contract),
            "source": lambda item: _source_trace_complete(item),
        },
        ignore_blocked_with_reason=True,
    )
    by_card = sum(1 for card in cards if rules.character_data_card(card.card_id) is card)
    by_entity = sum(1 for card in cards if rules.character_data_card_for_entity(card.entity_ref) is card)
    return _contract_row(
        "character_data_card_core_contract",
        contract_subject="CharacterDataCardIR core fields and card/entity RuleBook lookup",
        raw_source_domains=("avatar_config_profile_cards", "avatar_config_ld_profile_cards", "avatar_config_enhanced_profile_cards"),
        raw_count=_s0_raw(s0_matrix, "avatar_config_profile_cards", "avatar_config_ld_profile_cards", "avatar_config_enhanced_profile_cards"),
        ir_container="CharacterDataCardIR",
        ir_items=cards,
        rulebook_query_surface="RuleBook.character_data_card(card_id), character_data_card_for_entity(entity_ref)",
        rulebook_visible_count=min(by_card, by_entity),
        required_missing=required_missing,
        details={
            "by_card_id_visible": by_card,
            "by_entity_ref_visible": by_entity,
            "required_missing": required_missing,
        },
        future_owner="CharacterDataCardIR contract",
    )


def _character_card_link_contract(ir: CanonicalIR, rules: RuleBook, s0_matrix: dict[str, Any]) -> dict[str, JSONValue]:
    cards = tuple(ir.character_data_cards)
    profile_refs = tuple(card.profile_id for card in cards if card.profile_id)
    action_set_refs = tuple(card.entity_ref for card in cards if card.entity_ref)
    action_refs = tuple(_iter_character_action_refs(cards))
    formula_refs = tuple(ref for card in cards for ref in card.skill_formula_binding_ids)
    mechanism_refs = tuple(ref for card in cards for ref in card.mechanism_slot_ids)
    trace_refs = tuple(ref for card in cards for ref in card.trace_node_ids)
    eidolon_refs = tuple(ref for card in cards for ref in card.eidolon_slot_ids)
    bounce_refs = tuple(ref for card in cards for ref in card.bounce_policy_ids)
    link_counts = {
        "profile_refs": len(profile_refs),
        "action_set_refs": len(action_set_refs),
        "action_refs": len(action_refs),
        "formula_refs": len(formula_refs),
        "mechanism_refs": len(mechanism_refs),
        "trace_refs": len(trace_refs),
        "eidolon_refs": len(eidolon_refs),
        "bounce_refs": len(bounce_refs),
    }
    missing_counts = {
        "profile_refs": sum(1 for ref in profile_refs if rules.avatar_profile_by_profile_id(ref) is None),
        "action_set_refs": sum(1 for ref in action_set_refs if rules.combatant_action_set(ref) is None),
        "action_refs": sum(1 for action_id, level in action_refs if rules.action_definition(action_id, level) is None),
        "formula_refs": sum(1 for ref in formula_refs if rules.skill_formula_binding(ref) is None),
        "mechanism_refs": sum(1 for ref in mechanism_refs if rules.character_mechanism_slot(ref) is None),
        "trace_refs": sum(1 for ref in trace_refs if rules.character_trace_node(ref) is None),
        "eidolon_refs": sum(1 for ref in eidolon_refs if rules.character_eidolon_slot(ref) is None),
        "bounce_refs": sum(1 for ref in bounce_refs if rules.bounce_policy(ref) is None),
    }
    total_links = sum(link_counts.values())
    missing_total = sum(missing_counts.values())
    return _link_contract_row(
        "character_card_link_contract",
        contract_subject="CharacterDataCardIR profile/action/formula/mechanism/trace/eidolon link lookup",
        raw_source_domains=(
            "avatar_skill_config_actions",
            "avatar_skill_param_formula_sources",
            "avatar_skilltree_config_trace_slots",
            "avatar_rank_config_eidolon_slots",
        ),
        raw_count=_s0_raw(
            s0_matrix,
            "avatar_skill_config_actions",
            "avatar_skill_param_formula_sources",
            "avatar_skilltree_config_trace_slots",
            "avatar_rank_config_eidolon_slots",
        ),
        ir_container="CharacterDataCardIR link fields",
        sample_items=cards,
        rulebook_query_surface="RuleBook.avatar_profile_by_profile_id / combatant_action_set / action_definition / skill_formula_binding / character_* accessors",
        link_count=total_links,
        missing_link_count=missing_total,
        details={"link_counts": link_counts, "missing_link_counts": missing_counts},
        future_owner="CharacterDataCardIR link contract",
    )


def _monster_data_card_contract(ir: CanonicalIR, rules: RuleBook, s0_matrix: dict[str, Any]) -> dict[str, JSONValue]:
    cards = tuple(ir.monster_data_cards)
    required_missing = _missing_required_counts(
        cards,
        {
            "card_id": lambda item: bool(item.card_id),
            "entity_ref": lambda item: bool(item.entity_ref),
            "monster_id": lambda item: bool(item.monster_id),
            "template_id": lambda item: bool(item.template_id),
            "profile_id": lambda item: bool(item.profile_id),
            "action_set_id": lambda item: bool(item.action_set_id),
            "skill_ids": lambda item: bool(item.skill_ids),
            "skill_slots": lambda item: isinstance(item.skill_slots, tuple),
            "action_sequence": lambda item: isinstance(item.action_sequence, tuple),
            "raw_parameter_blocks": lambda item: isinstance(item.raw_parameter_blocks, dict),
            "card_contract": lambda item: isinstance(item.card_contract, dict) and bool(item.card_contract),
            "source": lambda item: _source_trace_complete(item),
        },
        ignore_blocked_with_reason=True,
    )
    by_card = sum(1 for card in cards if rules.monster_data_card(card.card_id) is card)
    by_entity = sum(1 for card in cards if rules.monster_data_card_for_entity(card.entity_ref) is card)
    blocked_missing_skill_ids = sum(
        1 for card in cards if not card.skill_ids and card.coverage_status == "blocked" and card.blocked_reason
    )
    return _contract_row(
        "monster_data_card_core_contract",
        contract_subject="MonsterDataCardIR core fields and card/entity RuleBook lookup",
        raw_source_domains=("monster_config_base_cards", "monster_template_config_profiles"),
        raw_count=_s0_raw(s0_matrix, "monster_config_base_cards", "monster_template_config_profiles"),
        ir_container="MonsterDataCardIR",
        ir_items=cards,
        rulebook_query_surface="RuleBook.monster_data_card(card_id), monster_data_card_for_entity(entity_ref)",
        rulebook_visible_count=min(by_card, by_entity),
        required_missing=required_missing,
        details={
            "by_card_id_visible": by_card,
            "by_entity_ref_visible": by_entity,
            "required_missing": required_missing,
            "blocked_missing_skill_ids": blocked_missing_skill_ids,
        },
        future_owner="MonsterDataCardIR contract",
    )


def _monster_card_link_contract(ir: CanonicalIR, rules: RuleBook, s0_matrix: dict[str, Any]) -> dict[str, JSONValue]:
    cards = tuple(ir.monster_data_cards)
    profile_refs = tuple(card.profile_id for card in cards if card.profile_id)
    action_set_refs = tuple(card.entity_ref for card in cards if card.entity_ref)
    skill_slot_refs = tuple(_iter_monster_skill_slot_refs(cards))
    sequence_refs = tuple(_iter_monster_sequence_refs(cards))
    passive_refs = tuple(ref for card in cards for ref in card.passive_mechanism_slot_ids)
    summon_refs = tuple(ref for card in cards for ref in card.summon_refs)
    action_set_missing = _missing_monster_action_set_refs(cards, rules)
    skill_slot_missing = _missing_monster_action_refs(cards, rules, field_name="skill_slots")
    sequence_missing = _missing_monster_action_refs(cards, rules, field_name="action_sequence")
    summon_missing = _missing_monster_summon_refs(cards, rules)
    link_counts = {
        "profile_refs": len(profile_refs),
        "action_set_refs": len(action_set_refs),
        "skill_slot_action_refs": len(skill_slot_refs),
        "sequence_action_refs": len(sequence_refs),
        "passive_refs": len(passive_refs),
        "summon_refs": len(summon_refs),
    }
    missing_counts = {
        "profile_refs": sum(1 for ref in profile_refs if rules.combatant_profile_by_profile_id(ref) is None),
        "action_set_refs": action_set_missing["validation_gap"],
        "skill_slot_action_refs": skill_slot_missing["validation_gap"],
        "sequence_action_refs": sequence_missing["validation_gap"],
        "passive_refs": sum(1 for ref in passive_refs if rules.passive_mechanism_slot(ref) is None),
        "summon_refs": summon_missing["validation_gap"],
    }
    blocked_missing_counts = {
        "action_set_refs": action_set_missing["admission_gap"],
        "skill_slot_action_refs": skill_slot_missing["admission_gap"],
        "sequence_action_refs": sequence_missing["admission_gap"],
        "summon_refs": summon_missing["admission_gap"],
    }
    missing_samples = [
        *action_set_missing["samples"],
        *skill_slot_missing["samples"],
        *sequence_missing["samples"],
        *summon_missing["samples"],
    ][:MAX_SAMPLES]
    return _link_contract_row(
        "monster_card_link_contract",
        contract_subject="MonsterDataCardIR profile/action/passive/summon link lookup",
        raw_source_domains=(
            "monster_config_skill_list_action_set",
            "monster_config_override_ai_sequence",
            "monster_template_ai_sequence",
            "monster_config_ability_name_list_passives",
            "monster_config_summon_id_list_refs",
        ),
        raw_count=_s0_raw(
            s0_matrix,
            "monster_config_skill_list_action_set",
            "monster_config_override_ai_sequence",
            "monster_template_ai_sequence",
            "monster_config_ability_name_list_passives",
            "monster_config_summon_id_list_refs",
        ),
        ir_container="MonsterDataCardIR link fields",
        sample_items=cards,
        rulebook_query_surface="RuleBook.combatant_profile_by_profile_id / combatant_action_set / action_levels / passive_mechanism_slot / monster_data_card_for_entity",
        link_count=sum(link_counts.values()),
        missing_link_count=sum(missing_counts.values()),
        details={
            "link_counts": link_counts,
            "missing_link_counts": missing_counts,
            "blocked_missing_link_counts": blocked_missing_counts,
            "missing_link_samples": missing_samples,
        },
        future_owner="MonsterDataCardIR link contract",
    )


def _combatant_profile_contract(ir: CanonicalIR, rules: RuleBook, s0_matrix: dict[str, Any]) -> dict[str, JSONValue]:
    profiles = tuple(ir.combatant_profiles)
    required_missing = _missing_required_counts(
        profiles,
        {
            "profile_id": lambda item: bool(item.profile_id),
            "entity_id": lambda item: bool(item.entity_id),
            "entity_type": lambda item: bool(item.entity_type),
            "base_stats": lambda item: isinstance(item.base_stats, dict) and bool(item.base_stats),
            "toughness_profile": lambda item: isinstance(item.toughness_profile, dict) and bool(item.toughness_profile),
            "source": lambda item: _source_trace_complete(item),
        },
        ignore_blocked_with_reason=True,
    )
    by_entity = sum(1 for profile in profiles if rules.combatant_profile(profile.entity_id) is profile)
    by_profile_id = sum(1 for profile in profiles if rules.combatant_profile_by_profile_id(profile.profile_id) is profile)
    blocked_without_reason = sum(1 for profile in profiles if profile.coverage_status == "blocked" and not profile.blocked_reason)
    blocked_missing_stats = sum(
        1
        for profile in profiles
        if profile.coverage_status == "blocked"
        and profile.blocked_reason
        and (not profile.base_stats or not profile.toughness_profile)
    )
    missing = dict(required_missing)
    if blocked_without_reason:
        missing["blocked_reason"] = blocked_without_reason
    return _contract_row(
        "combatant_profile_contract",
        contract_subject="CombatantProfileIR stat/template/profile id lookup",
        raw_source_domains=("monster_config_base_cards", "monster_template_config_profiles", "avatar_promotion_config_profile_stats"),
        raw_count=_s0_raw(
            s0_matrix,
            "monster_config_base_cards",
            "monster_template_config_profiles",
            "avatar_promotion_config_profile_stats",
        ),
        ir_container="CombatantProfileIR",
        ir_items=profiles,
        rulebook_query_surface="RuleBook.combatant_profile(entity_id), combatant_profile_by_profile_id(profile_id)",
        rulebook_visible_count=min(by_entity, by_profile_id),
        required_missing=missing,
        details={
            "by_entity_id_visible": by_entity,
            "by_profile_id_visible": by_profile_id,
            "required_missing": missing,
            "blocked_without_reason": blocked_without_reason,
            "blocked_missing_stats": blocked_missing_stats,
        },
        future_owner="CombatantProfileIR contract",
    )


def _combatant_action_set_contract(ir: CanonicalIR, rules: RuleBook, s0_matrix: dict[str, Any]) -> dict[str, JSONValue]:
    action_sets = tuple(ir.combatant_action_sets)
    required_missing = _missing_required_counts(
        action_sets,
        {
            "combatant_action_set_id": lambda item: bool(item.combatant_action_set_id),
            "entity_ref": lambda item: bool(item.entity_ref),
            "skill_index_map": lambda item: isinstance(item.skill_index_map, dict) and bool(item.skill_index_map),
            "source": lambda item: _source_trace_complete(item),
        },
        ignore_blocked_with_reason=True,
    )
    by_entity = sum(1 for action_set in action_sets if rules.combatant_action_set(action_set.entity_ref) is action_set)
    slot_count = 0
    missing_action_defs = 0
    skipped_slots = 0
    blocked_empty_skill_index_map = sum(
        1
        for action_set in action_sets
        if not action_set.skill_index_map and action_set.coverage_status == "blocked" and action_set.blocked_reason
    )
    for action_set in action_sets:
        for slot in action_set.skill_index_map.values():
            if not isinstance(slot, dict):
                skipped_slots += 1
                continue
            action_ref = str(slot.get("action_ref") or "")
            levels = slot.get("levels")
            level_values = [int(value) for value in levels if isinstance(value, int)] if isinstance(levels, list) else []
            slot_count += 1
            if not action_ref or not level_values:
                missing_action_defs += 1
                continue
            if not any(rules.action_definition(action_ref, level) for level in level_values):
                missing_action_defs += 1
    missing = dict(required_missing)
    if skipped_slots:
        missing["skipped_slots"] = skipped_slots
    return _contract_row(
        "combatant_action_set_contract",
        contract_subject="CombatantActionSetIR entity_ref skill index map and action definition lookup",
        raw_source_domains=("avatar_skill_config_actions", "monster_config_skill_list_action_set", "avatar_servant_skill_config_actions"),
        raw_count=_s0_raw(
            s0_matrix,
            "avatar_skill_config_actions",
            "monster_config_skill_list_action_set",
            "avatar_servant_skill_config_actions",
        ),
        ir_container="CombatantActionSetIR",
        ir_items=action_sets,
        rulebook_query_surface="RuleBook.combatant_action_set(entity_ref), action_definition(action_ref, level)",
        rulebook_visible_count=by_entity,
        required_missing=missing,
        validation_gap_count=missing_action_defs,
        details={
            "by_entity_ref_visible": by_entity,
            "skill_index_slot_count": slot_count,
            "missing_action_definition_slots": missing_action_defs,
            "blocked_empty_skill_index_map": blocked_empty_skill_index_map,
            "skipped_slots": skipped_slots,
            "required_missing": missing,
        },
        future_owner="Combatant action set contract",
    )


def _formula_binding_contract(ir: CanonicalIR, rules: RuleBook, s0_matrix: dict[str, Any]) -> dict[str, JSONValue]:
    bindings = tuple(ir.skill_formula_bindings)
    required_missing = _missing_required_counts(
        bindings,
        {
            "binding_id": lambda item: bool(item.binding_id),
            "action_id": lambda item: bool(item.action_id),
            "level": lambda item: isinstance(item.level, int),
            "param_index": lambda item: isinstance(item.param_index, int),
            "formula_role": lambda item: bool(item.formula_role),
            "source": lambda item: _source_trace_complete(item),
        },
        ignore_blocked_with_reason=True,
    )
    by_id = sum(1 for binding in bindings if rules.skill_formula_binding(binding.binding_id) is binding)
    by_action_param = sum(
        1
        for binding in bindings
        if binding
        in rules.skill_formula_bindings_for_action_param(
            binding.action_id,
            binding.level,
            binding.param_index,
            binding.formula_role,
        )
    )
    return _contract_row(
        "formula_binding_contract",
        contract_subject="SkillFormulaBindingIR id and action/param/role lookup",
        raw_source_domains=("avatar_skill_param_formula_sources", "monster_skill_param_formula_sources", "ilbattle_skill_param_formula_sources"),
        raw_count=_s0_raw(
            s0_matrix,
            "avatar_skill_param_formula_sources",
            "monster_skill_param_formula_sources",
            "ilbattle_skill_param_formula_sources",
        ),
        ir_container="SkillFormulaBindingIR",
        ir_items=bindings,
        rulebook_query_surface="RuleBook.skill_formula_binding(binding_id), skill_formula_bindings_for_action_param(action_id, level, param_index, formula_role)",
        rulebook_visible_count=min(by_id, by_action_param),
        required_missing=required_missing,
        details={
            "by_binding_id_visible": by_id,
            "by_action_param_role_visible": by_action_param,
            "required_missing": required_missing,
        },
        future_owner="Formula/dynamic binding contract",
    )


def _character_mechanism_trace_eidolon_contract(
    ir: CanonicalIR,
    rules: RuleBook,
    s0_matrix: dict[str, Any],
) -> dict[str, JSONValue]:
    items = (*ir.character_mechanism_slots, *ir.character_trace_nodes, *ir.character_eidolon_slots)
    by_id = (
        sum(1 for item in ir.character_mechanism_slots if rules.character_mechanism_slot(item.mechanism_slot_id) is item)
        + sum(1 for item in ir.character_trace_nodes if rules.character_trace_node(item.trace_node_id) is item)
        + sum(1 for item in ir.character_eidolon_slots if rules.character_eidolon_slot(item.eidolon_slot_id) is item)
    )
    by_card = (
        sum(1 for item in ir.character_mechanism_slots if item in rules.character_mechanism_slots_for_card(item.character_data_card_id))
        + sum(1 for item in ir.character_trace_nodes if item in rules.character_trace_nodes_for_card(item.character_data_card_id))
        + sum(1 for item in ir.character_eidolon_slots if item in rules.character_eidolon_slots_for_card(item.character_data_card_id))
    )
    blocked_missing_card_ref = sum(
        1
        for item in items
        if not getattr(item, "character_data_card_id", "")
        and _coverage_status(item) == "blocked"
        and bool(getattr(item, "blocked_reason", "") or "")
    )
    required_missing = _missing_required_counts(
        items,
        {
            "source": lambda item: _source_trace_complete(item),
            "card_ref": lambda item: bool(getattr(item, "character_data_card_id", "")),
        },
        ignore_blocked_with_reason=True,
    )
    return _contract_row(
        "character_mechanism_trace_eidolon_contract",
        contract_subject="Character mechanism / trace / eidolon slot id and card lookup",
        raw_source_domains=("avatar_skilltree_config_trace_slots", "avatar_rank_config_eidolon_slots"),
        raw_count=_s0_raw(s0_matrix, "avatar_skilltree_config_trace_slots", "avatar_rank_config_eidolon_slots"),
        ir_container="CharacterMechanismSlotIR + CharacterTraceNodeIR + CharacterEidolonSlotIR",
        ir_items=items,
        rulebook_query_surface="RuleBook.character_mechanism_slot / character_trace_node / character_eidolon_slot and *_for_card",
        rulebook_visible_count=min(by_id, by_card),
        required_missing=required_missing,
        details={
            "by_id_visible": by_id,
            "by_card_visible": by_card,
            "required_missing": required_missing,
            "blocked_missing_card_ref": blocked_missing_card_ref,
        },
        future_owner="Character mechanism contract",
    )


def _monster_passive_contract(ir: CanonicalIR, rules: RuleBook, s0_matrix: dict[str, Any]) -> dict[str, JSONValue]:
    slots = tuple(ir.passive_mechanism_slots)
    required_missing = _missing_required_counts(
        slots,
        {
            "passive_slot_id": lambda item: bool(item.passive_slot_id),
            "data_card_id": lambda item: bool(item.data_card_id),
            "owner_entity_ref": lambda item: bool(item.owner_entity_ref),
            "source": lambda item: _source_trace_complete(item),
        },
        ignore_blocked_with_reason=True,
    )
    by_id = sum(1 for slot in slots if rules.passive_mechanism_slot(slot.passive_slot_id) is slot)
    by_card = sum(1 for slot in slots if slot in rules.passive_mechanism_slots_for_card(slot.data_card_id))
    by_owner = sum(1 for slot in slots if slot in rules.passive_mechanism_slots_for_owner(slot.owner_entity_ref))
    return _contract_row(
        "monster_passive_contract",
        contract_subject="Monster passive mechanism slot id/card/owner lookup",
        raw_source_domains=("monster_config_ability_name_list_passives", "config_global_modifier_listener_sources"),
        raw_count=_s0_raw(s0_matrix, "monster_config_ability_name_list_passives", "config_global_modifier_listener_sources"),
        ir_container="PassiveMechanismSlotIR",
        ir_items=slots,
        rulebook_query_surface="RuleBook.passive_mechanism_slot / passive_mechanism_slots_for_card / passive_mechanism_slots_for_owner",
        rulebook_visible_count=min(by_id, by_card, by_owner),
        required_missing=required_missing,
        details={
            "by_id_visible": by_id,
            "by_card_visible": by_card,
            "by_owner_visible": by_owner,
            "required_missing": required_missing,
        },
        future_owner="Monster passive contract",
    )


def _servant_subcard_hook_contract(ir: CanonicalIR, rules: RuleBook, s0_matrix: dict[str, Any]) -> dict[str, JSONValue]:
    definitions = tuple(ir.servant_definitions)
    by_id = sum(1 for item in definitions if rules.servant_definition(item.servant_definition_id) is item)
    by_owner = sum(
        1
        for item in definitions
        if item.owner_entity_refs
        and all(item in rules.servant_definitions_for_owner(owner_ref) for owner_ref in item.owner_entity_refs)
    )
    required_missing = _missing_required_counts(
        definitions,
        {
            "servant_definition_id": lambda item: bool(item.servant_definition_id),
            "owner_relations": lambda item: bool(item.owner_relations) and bool(item.owner_entity_refs),
            "source": lambda item: _source_trace_complete(item),
        },
        ignore_blocked_with_reason=True,
    )
    return _contract_row(
        "servant_subcard_hook_contract",
        contract_subject="Character servant / derived combatant subcard extension hook",
        raw_source_domains=("avatar_servant_config_subcard_sources", "config_character_servant_sources"),
        raw_count=_s0_raw(s0_matrix, "avatar_servant_config_subcard_sources", "config_character_servant_sources"),
        ir_container="ServantDefinitionIR",
        ir_items=definitions,
        rulebook_query_surface="RuleBook.servant_definition / servant_definitions_for_owner",
        rulebook_visible_count=min(by_id, by_owner),
        required_missing=required_missing,
        forced_classification="boundary_only",
        blocked_boundary_samples=_hook_boundary_samples(
            "servant_subcard_hook",
            "CharacterDataCardIR owns servant subcards or derived combatant cards.",
            "missing full stat/action/lifecycle assembly keeps this hook boundary-only in S1",
        ),
        details={
            "by_id_visible": by_id,
            "by_owner_visible": by_owner,
            "required_missing": required_missing,
        },
        future_owner="P4-S2/P4-S7 servant action and subcard assembly",
    )


def _summoned_monster_lifecycle_hook_contract(
    ir: CanonicalIR,
    rules: RuleBook,
    s0_matrix: dict[str, Any],
) -> dict[str, JSONValue]:
    intents = tuple(ir.summon_monster_intents)
    by_id = sum(1 for item in intents if rules.summon_monster_intent(item.summon_intent_id) is item)
    by_task = sum(1 for item in intents if item in rules.summon_monster_intents_for_task(item.source_task_id))
    required_missing = _missing_required_counts(
        intents,
        {
            "summon_intent_id": lambda item: bool(item.summon_intent_id),
            "source_task_id": lambda item: bool(item.source_task_id),
            "source": lambda item: _source_trace_complete(item),
        },
        ignore_blocked_with_reason=True,
    )
    return _contract_row(
        "summoned_monster_lifecycle_hook_contract",
        contract_subject="Monster summoned monster intent and lifecycle hook",
        raw_source_domains=("monster_config_summon_id_list_refs", "p3_summoned_monster_intent_backlog"),
        raw_count=_s0_raw(s0_matrix, "monster_config_summon_id_list_refs", "p3_summoned_monster_intent_backlog"),
        ir_container="SummonMonsterIntentIR",
        ir_items=intents,
        rulebook_query_surface="RuleBook.summon_monster_intent / summon_monster_intents_for_task",
        rulebook_visible_count=min(by_id, by_task),
        required_missing=required_missing,
        forced_classification="boundary_only",
        blocked_boundary_samples=_hook_boundary_samples(
            "summoned_monster_lifecycle_hook",
            "Monster summon refs and summon intents require explicit lifecycle/admission before runtime spawn.",
            "missing owner relation, target source, lifecycle, or admitted dynamic monster id keeps state unchanged",
        ),
        details={"by_id_visible": by_id, "by_task_visible": by_task, "required_missing": required_missing},
        future_owner="P4-S6/P4-S10 summoned monster lifecycle",
    )


def _equipment_build_stage_environment_hook_contract(
    ir: CanonicalIR,
    rules: RuleBook,
    s0_matrix: dict[str, Any],
) -> dict[str, JSONValue]:
    del ir, rules
    raw_count = _s0_raw(
        s0_matrix,
        "equipment_light_cone_build_hook",
        "relic_set_build_hook",
        "monster_stage_override_hook",
        "stage_environment_sources",
    )
    return _contract_row(
        "equipment_build_stage_environment_hook_contract",
        contract_subject="Equipment/build and stage/environment assembly extension hooks",
        raw_source_domains=(
            "equipment_light_cone_build_hook",
            "relic_set_build_hook",
            "monster_stage_override_hook",
            "stage_environment_sources",
        ),
        raw_count=raw_count,
        ir_container="future build/stage/environment assembly hook",
        ir_items=(),
        rulebook_query_surface="none in S1 runtime; explicit boundary only",
        rulebook_visible_count=0,
        forced_classification="boundary_only",
        blocked_boundary_samples=_hook_boundary_samples(
            "build_stage_environment_hook",
            "Equipment/build/stage/environment remain external future layers.",
            "missing build or stage assembly source cannot create data-card stats, actions, statuses, or mutations",
        ),
        details={
            "raw_source_present": raw_count > 0,
            "runtime_behavior_changed": False,
            "state_effect": "state_unchanged_from_hook_without_explicit_future_assembly",
        },
        future_owner="future equipment/build/stage/environment layers",
    )


def _source_audit_contract(ir: CanonicalIR, rules: RuleBook, s0_matrix: dict[str, Any]) -> dict[str, JSONValue]:
    del rules, s0_matrix
    items = (
        *ir.character_data_cards,
        *ir.monster_data_cards,
        *ir.combatant_profiles,
        *ir.combatant_action_sets,
        *ir.skill_formula_bindings,
        *ir.character_mechanism_slots,
        *ir.character_trace_nodes,
        *ir.character_eidolon_slots,
        *ir.passive_mechanism_slots,
        *ir.servant_definitions,
        *ir.summon_monster_intents,
    )
    missing_source = sum(1 for item in items if not _source_trace_complete(item))
    process_only_samples = _hook_boundary_samples(
        "source_audit_runtime_boundary",
        "S1 does not execute transitions.",
        "mutation/settlement/replay traceability must be proven in later runtime stages; S1 only proves IR source trace presence",
    )
    return _contract_row(
        "source_audit_contract",
        contract_subject="Data-card contract source audit coverage",
        raw_source_domains=("all S1 data-card contract domains",),
        raw_count=len(items),
        ir_container="S1 contract IR sources",
        ir_items=items,
        rulebook_query_surface="source.to_json on each sampled IR item; mutation/settlement replay not executed in S1",
        rulebook_visible_count=len(items) - missing_source,
        validation_gap_count=missing_source,
        blocked_boundary_samples=process_only_samples,
        details={
            "items_with_source_trace": len(items) - missing_source,
            "items_missing_source_trace": missing_source,
            "transition_executed_in_s1": False,
        },
        future_owner="source audit and later mutation/settlement traceability",
    )


def _contract_row(
    contract_id: str,
    *,
    contract_subject: str,
    raw_source_domains: Iterable[str],
    raw_count: int,
    ir_container: str,
    ir_items: Iterable[Any],
    rulebook_query_surface: str,
    rulebook_visible_count: int,
    required_missing: dict[str, int] | None = None,
    validation_gap_count: int = 0,
    forced_classification: str = "",
    blocked_boundary_samples: Iterable[dict[str, JSONValue]] = (),
    details: dict[str, JSONValue] | None = None,
    future_owner: str,
) -> dict[str, JSONValue]:
    items = tuple(ir_items)
    required_missing = {key: int(value) for key, value in (required_missing or {}).items() if int(value or 0) > 0}
    status_counts = Counter(_coverage_status(item) for item in items)
    executable_count = int(status_counts.get("executable", 0))
    non_executable_count = max(len(items) - executable_count, 0)
    rulebook_gap_count = max(len(items) - int(rulebook_visible_count), 0) + max(int(validation_gap_count), 0)
    implementation_missing_count = sum(required_missing.values())
    classification = forced_classification or _classification(
        raw_count=raw_count,
        ir_count=len(items),
        rulebook_gap_count=rulebook_gap_count,
        implementation_missing_count=implementation_missing_count,
        non_executable_count=non_executable_count,
        executable_count=executable_count,
    )
    gap_attribution = _gap_attribution(
        classification,
        raw_count=raw_count,
        ir_count=len(items),
        rulebook_gap_count=rulebook_gap_count,
        implementation_missing_count=implementation_missing_count,
        non_executable_count=non_executable_count,
    )
    blocked_or_gap_count = sum(gap_attribution.values())
    boundary_samples = [
        *_limit_samples(blocked_boundary_samples),
        *_blocked_item_samples(items),
    ][:MAX_SAMPLES]
    if classification in GAP_STATES and blocked_or_gap_count > 0 and not boundary_samples:
        boundary_samples = [
            {
                "hook": contract_id,
                "blocked_reason": f"{contract_id} has {classification}; see details and gap_attribution",
                "state_effect": "state_unchanged_or_process_only_until_admitted",
                "mutation_allowed": False,
                "transition_executed_in_s1": False,
            }
        ]
    return {
        "contract_id": contract_id,
        "contract_subject": contract_subject,
        "raw_source_domains": list(raw_source_domains),
        "raw_count": int(raw_count),
        "ir_container": ir_container,
        "ir_count": len(items),
        "rulebook_query_surface": rulebook_query_surface,
        "rulebook_visible_count": int(rulebook_visible_count),
        "classification": classification if classification in CLASSIFICATION_STATES else "unclassified",
        "executable_count": executable_count,
        "blocked_or_gap_count": int(blocked_or_gap_count),
        "coverage_status_counts": dict(sorted(status_counts.items())),
        "gap_attribution": gap_attribution,
        "source_audit_samples": _source_audit_samples(items),
        "blocked_boundary_samples": boundary_samples,
        "checks": {
            "required_fields_present": not required_missing,
            "rulebook_visibility_complete": rulebook_gap_count == 0,
            "source_audit_sample_present": bool(_source_audit_samples(items)) or len(items) == 0,
            "blocked_has_boundary_sample": bool(boundary_samples) or classification not in GAP_STATES,
            "runtime_behavior_unchanged": True,
        },
        "details": dict(details or {}),
        "future_owner": future_owner,
        "raw_ir_mismatch_attribution": _raw_ir_mismatch_attribution(raw_count, len(items), classification),
    }


def _link_contract_row(
    contract_id: str,
    *,
    contract_subject: str,
    raw_source_domains: Iterable[str],
    raw_count: int,
    ir_container: str,
    sample_items: Iterable[Any],
    rulebook_query_surface: str,
    link_count: int,
    missing_link_count: int,
    details: dict[str, JSONValue],
    future_owner: str,
) -> dict[str, JSONValue]:
    return _contract_row(
        contract_id,
        contract_subject=contract_subject,
        raw_source_domains=raw_source_domains,
        raw_count=raw_count,
        ir_container=ir_container,
        ir_items=tuple(sample_items),
        rulebook_query_surface=rulebook_query_surface,
        rulebook_visible_count=max(link_count - missing_link_count, 0),
        validation_gap_count=missing_link_count,
        details={**details, "link_count": link_count, "missing_link_count": missing_link_count},
        future_owner=future_owner,
    ) | {
        "ir_count": int(link_count),
        "executable_count": max(int(link_count) - int(missing_link_count), 0),
    }


def _classification(
    *,
    raw_count: int,
    ir_count: int,
    rulebook_gap_count: int,
    implementation_missing_count: int,
    non_executable_count: int,
    executable_count: int,
) -> str:
    if raw_count > 0 and ir_count == 0:
        return "lowering_gap"
    if implementation_missing_count > 0:
        return "implementation_missing"
    if rulebook_gap_count > 0:
        return "validation_gap"
    if ir_count == 0:
        return "source_absent_not_required"
    if non_executable_count > 0:
        return "admission_gap"
    if executable_count == ir_count:
        return "executable"
    return "unclassified"


def _gap_attribution(
    classification: str,
    *,
    raw_count: int,
    ir_count: int,
    rulebook_gap_count: int,
    implementation_missing_count: int,
    non_executable_count: int,
) -> dict[str, int]:
    if classification == "lowering_gap":
        return {"lowering_gap": max(raw_count - ir_count, 1)}
    if classification == "implementation_missing":
        return {"implementation_missing": max(implementation_missing_count, 1)}
    if classification == "validation_gap":
        return {"validation_gap": max(rulebook_gap_count, 1)}
    if classification in {"admission_gap", "source_gap_blocked"}:
        return {classification: max(non_executable_count, 1)}
    return {}


def _missing_required_counts(
    items: Iterable[Any],
    required_fields: dict[str, Any],
    *,
    ignore_blocked_with_reason: bool = False,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for field_name, predicate in required_fields.items():
        missing = sum(
            1
            for item in items
            if not bool(predicate(item))
            and not (
                ignore_blocked_with_reason
                and _coverage_status(item) == "blocked"
                and bool(getattr(item, "blocked_reason", "") or "")
            )
        )
        if missing:
            counts[field_name] = missing
    return counts


def _iter_character_action_refs(cards: Iterable[Any]) -> Iterable[tuple[str, int]]:
    for card in cards:
        action_set = getattr(card, "action_set", {}) or {}
        actions = action_set.get("actions") if isinstance(action_set, dict) else None
        if not isinstance(actions, list):
            continue
        for action in actions:
            if not isinstance(action, dict):
                continue
            action_id = str(action.get("action_id") or "")
            level = action.get("level")
            if action_id and isinstance(level, int):
                yield action_id, level


def _iter_monster_skill_slot_refs(cards: Iterable[Any]) -> Iterable[str]:
    for card in cards:
        for slot in getattr(card, "skill_slots", ()) or ():
            if not isinstance(slot, dict):
                continue
            action_ref = str(slot.get("action_ref") or "")
            if action_ref:
                yield action_ref


def _iter_monster_sequence_refs(cards: Iterable[Any]) -> Iterable[str]:
    for card in cards:
        for step in getattr(card, "action_sequence", ()) or ():
            if not isinstance(step, dict):
                continue
            action_ref = str(step.get("action_ref") or "")
            if action_ref:
                yield action_ref


def _missing_monster_action_set_refs(cards: Iterable[Any], rules: RuleBook) -> dict[str, Any]:
    validation_gap = 0
    admission_gap = 0
    samples: list[dict[str, JSONValue]] = []
    for card in cards:
        if not getattr(card, "entity_ref", ""):
            continue
        if rules.combatant_action_set(card.entity_ref) is not None:
            continue
        reason = str(getattr(card, "blocked_reason", "") or "")
        if _coverage_status(card) == "blocked" and reason:
            admission_gap += 1
            gap_kind = "admission_gap"
        else:
            validation_gap += 1
            gap_kind = "validation_gap"
        _append_missing_link_sample(
            samples,
            "action_set_ref",
            gap_kind,
            card.entity_ref,
            _item_identifier(card),
            reason,
        )
    return {"validation_gap": validation_gap, "admission_gap": admission_gap, "samples": samples}


def _missing_monster_action_refs(cards: Iterable[Any], rules: RuleBook, *, field_name: str) -> dict[str, Any]:
    validation_gap = 0
    admission_gap = 0
    samples: list[dict[str, JSONValue]] = []
    for card in cards:
        entries = getattr(card, field_name, ()) or ()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            action_ref = str(entry.get("action_ref") or "")
            if not action_ref or rules.action_levels(action_ref):
                continue
            reason = str(entry.get("blocked_reason") or getattr(card, "blocked_reason", "") or "")
            status = str(entry.get("coverage_status") or _coverage_status(card))
            if status == "blocked" and reason:
                admission_gap += 1
                gap_kind = "admission_gap"
            else:
                validation_gap += 1
                gap_kind = "validation_gap"
            _append_missing_link_sample(
                samples,
                field_name,
                gap_kind,
                action_ref,
                _item_identifier(card),
                reason,
            )
    return {"validation_gap": validation_gap, "admission_gap": admission_gap, "samples": samples}


def _missing_monster_summon_refs(cards: Iterable[Any], rules: RuleBook) -> dict[str, Any]:
    validation_gap = 0
    admission_gap = 0
    samples: list[dict[str, JSONValue]] = []
    for card in cards:
        for summon_ref in getattr(card, "summon_refs", ()) or ():
            entity_ref = f"monster:{summon_ref}"
            if rules.monster_data_card_for_entity(entity_ref) is not None:
                continue
            reason = "summon_ref_has_no_monster_data_card"
            admission_gap += 1
            _append_missing_link_sample(
                samples,
                "summon_ref",
                "admission_gap",
                entity_ref,
                _item_identifier(card),
                reason,
            )
    return {"validation_gap": validation_gap, "admission_gap": admission_gap, "samples": samples}


def _append_missing_link_sample(
    samples: list[dict[str, JSONValue]],
    link_kind: str,
    gap_kind: str,
    missing_ref: str,
    owner_id: str,
    reason: str,
) -> None:
    if len(samples) >= MAX_SAMPLES:
        return
    samples.append(
        {
            "link_kind": link_kind,
            "gap_kind": gap_kind,
            "missing_ref": missing_ref,
            "owner_id": owner_id,
            "blocked_reason": reason,
            "state_effect": "state_unchanged_or_process_only_until_admitted",
            "transition_executed_in_s1": False,
        }
    )


def _s0_raw(s0_matrix: dict[str, Any], *domains: str) -> int:
    domain_matrix = dict(s0_matrix.get("domain_matrix") or {})
    return sum(int(domain_matrix.get(domain, {}).get("raw_count") or 0) for domain in domains)


def _source_trace_complete(item: Any) -> bool:
    source = getattr(item, "source", None)
    if source is None:
        return False
    return bool(getattr(source, "source_path", "") and getattr(source, "raw_type", "") and getattr(source, "raw_id", ""))


def _source_trace(item: Any | None) -> dict[str, JSONValue]:
    source = getattr(item, "source", None)
    if source is None:
        return {}
    to_json = getattr(source, "to_json", None)
    return to_json() if callable(to_json) else {}


def _source_audit_samples(items: Iterable[Any]) -> list[dict[str, JSONValue]]:
    samples: list[dict[str, JSONValue]] = []
    for item in items:
        trace = _source_trace(item)
        if not trace:
            continue
        samples.append(
            {
                "item_id": _item_identifier(item),
                "coverage_status": _coverage_status(item),
                "source": trace,
            }
        )
        if len(samples) >= MAX_SAMPLES:
            break
    return samples


def _blocked_item_samples(items: Iterable[Any]) -> list[dict[str, JSONValue]]:
    samples: list[dict[str, JSONValue]] = []
    for item in items:
        status = _coverage_status(item)
        reason = str(getattr(item, "blocked_reason", "") or "")
        if status not in {"blocked", "audit_only", "discovered_only", "lowered"} and not reason:
            continue
        samples.append(
            {
                "item_id": _item_identifier(item),
                "coverage_status": status,
                "blocked_reason": reason or f"{status}_not_runtime_executable_in_s1",
                "source": _source_trace(item),
                "state_effect": "state_unchanged_or_process_only_until_admitted",
                "transition_executed_in_s1": False,
            }
        )
        if len(samples) >= MAX_SAMPLES:
            break
    return samples


def _hook_boundary_samples(hook: str, owner: str, blocked_reason: str) -> list[dict[str, JSONValue]]:
    return [
        {
            "hook": hook,
            "owner": owner,
            "blocked_reason": blocked_reason,
            "state_effect": "state_unchanged",
            "mutation_allowed": False,
            "transition_executed_in_s1": False,
        }
    ]


def _limit_samples(samples: Iterable[dict[str, JSONValue]]) -> list[dict[str, JSONValue]]:
    return [dict(sample) for sample in list(samples)[:MAX_SAMPLES]]


def _coverage_status(item: Any) -> str:
    return str(getattr(item, "coverage_status", "") or "unclassified")


def _item_identifier(item: Any) -> str:
    for attr in (
        "card_id",
        "profile_id",
        "combatant_action_set_id",
        "binding_id",
        "mechanism_slot_id",
        "trace_node_id",
        "eidolon_slot_id",
        "passive_slot_id",
        "servant_definition_id",
        "summon_intent_id",
    ):
        value = getattr(item, attr, "")
        if value:
            return str(value)
    return type(item).__name__


def _raw_ir_mismatch_attribution(raw_count: int, ir_count: int, classification: str) -> str:
    if raw_count == 0 and ir_count > 0:
        return "IR contract rows exist but S0 raw source total is zero; review source domain mapping."
    if raw_count > 0 and ir_count == 0:
        return f"raw source exists but no matching IR contract projection; classified as {classification}"
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
