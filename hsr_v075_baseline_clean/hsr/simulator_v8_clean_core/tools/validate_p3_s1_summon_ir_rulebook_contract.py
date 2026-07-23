from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..rules.ir import CanonicalIR, IRSource
from ..rules.rulebook import RuleBook
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p3_s0_summon_source_inventory import build_p3_summon_source_inventory_matrix


VALIDATION_VERSION = "p3_s1_summon_ir_rulebook_contract"
MATRIX_SCHEMA_VERSION = "p3_summon_ir_rulebook_contract_matrix_s1"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    s0_matrix = build_p3_summon_source_inventory_matrix(tbgd_root, ir, rules)
    contract_matrix = build_p3_s1_contract_matrix(ir, rules, s0_matrix)
    contract_checks = validate_p3_s1_contract_matrix(contract_matrix)
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
                "mode": "p3_s1_ir_rulebook_contract_structural_audit",
                "runtime_behavior_changed": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "textmap_read": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "s0_matrix_reused_as_raw_inventory": True,
            },
        },
        "checks": checks,
        "summary": contract_matrix["summary"],
        "contract_groups": contract_matrix["contract_groups"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p3_s1_summon_ir_rulebook_contract.json", result)
    write_json(output_dir / "p3_summon_ir_rulebook_contract_matrix_s1.json", contract_matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate P3-S1 summon/servant IR and RuleBook contracts with AssistantAvatar scope exclusion."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def build_p3_s1_contract_matrix(ir: CanonicalIR, rules: RuleBook, s0_matrix: dict[str, Any]) -> dict[str, Any]:
    groups = {
        "summon_unit_definition_contract": _summon_unit_contract(ir, rules, s0_matrix),
        "summon_monster_intent_contract": _summon_monster_contract(ir, rules, s0_matrix),
        "servant_definition_contract": _servant_definition_contract(ir, rules, s0_matrix),
        "assistant_resolution_contract": _assistant_resolution_contract(ir, rules, s0_matrix),
        "queue_lifecycle_and_action_admission_contract": _queue_lifecycle_action_contract(ir, rules, s0_matrix),
        "target_and_cross_system_source_trace_contract": _target_cross_system_contract(ir, rules, s0_matrix),
    }
    classification_counts = Counter(str(item["classification"]) for item in groups.values())
    gap_counts = Counter()
    for item in groups.values():
        gap_counts.update({str(key): int(value) for key, value in item.get("gap_attribution", {}).items()})
    failed_checks = {
        group_id: [key for key, value in group["checks"].items() if value is False]
        for group_id, group in groups.items()
        if any(value is False for value in group["checks"].values())
    }
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "coverage_scope": {
            "runtime_behavior_changed": False,
            "raw_sources_allowed_only_in_tools": True,
            "textmap_read": False,
            "full_ir_written": False,
            "full_transition_dump_written": False,
            "s0_matrix_schema": s0_matrix["schema_version"],
        },
        "s0_summary": {
            "domain_count": len(s0_matrix["domain_matrix"]),
            "classification_counts": s0_matrix["classification_counts"],
            "unclassified_count": s0_matrix["unclassified_count"],
        },
        "contract_groups": groups,
        "summary": {
            "contract_group_count": len(groups),
            "classification_counts": dict(sorted(classification_counts.items())),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "failed_group_count": len(failed_checks),
            "failed_checks": failed_checks,
            "summon_unit_definition_count": len(ir.summon_unit_definitions),
            "summon_monster_intent_count": len(ir.summon_monster_intents),
            "servant_definition_count": len(ir.servant_definitions),
            "assistant_resolution_count": len(ir.assistant_ability_resolutions),
            "assistant_queue_intent_count": sum(1 for item in ir.queue_intents if item.opcode == "TurnInsertAssistantAbility"),
            "assistant_queue_window_count": len(rules.queue_windows_by_family("assistant")),
        },
    }


def validate_p3_s1_contract_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    groups = matrix["contract_groups"]
    checks = {
        "s0_inventory_classified": matrix["s0_summary"]["unclassified_count"] == 0,
        "summon_unit_contract_ok": groups["summon_unit_definition_contract"]["ok"],
        "summon_monster_contract_ok": groups["summon_monster_intent_contract"]["ok"],
        "servant_contract_ok": groups["servant_definition_contract"]["ok"],
        "assistant_contract_ok": groups["assistant_resolution_contract"]["ok"],
        "queue_lifecycle_action_contract_ok": groups["queue_lifecycle_and_action_admission_contract"]["ok"],
        "target_cross_system_contract_ok": groups["target_and_cross_system_source_trace_contract"]["ok"],
        "all_existing_ir_rulebook_visible": matrix["summary"]["failed_group_count"] == 0,
        "matrix_is_summary_only": (
            matrix["coverage_scope"]["full_ir_written"] is False
            and matrix["coverage_scope"]["full_transition_dump_written"] is False
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"ok": checks["ok"], "checks": checks}


def _summon_unit_contract(ir: CanonicalIR, rules: RuleBook, s0_matrix: dict[str, Any]) -> dict[str, Any]:
    definitions = tuple(sorted(ir.summon_unit_definitions, key=lambda item: item.summon_definition_id))
    required_fields = {
        "summon_definition_id": lambda item: bool(item.summon_definition_id),
        "summon_unit_id": lambda item: bool(item.summon_unit_id),
        "summon_kind": lambda item: bool(item.summon_kind),
        "battle_admission": lambda item: isinstance(item.battle_admission, dict),
        "skill_config": lambda item: isinstance(item.skill_config, dict),
        "source": lambda item: _source_trace_complete(item.source),
    }
    missing = _missing_required_counts(definitions, required_fields)
    by_id_visible = sum(1 for item in definitions if rules.summon_unit_definition(item.summon_definition_id) == item)
    by_unit_visible = sum(1 for item in definitions if rules.summon_unit_definition_for_unit_id(item.summon_unit_id) == item)
    blocked_without_reason = sum(1 for item in definitions if item.coverage_status == "blocked" and not item.blocked_reason)
    runtime_spawn_without_intent = sum(
        1
        for item in definitions
        if isinstance(item.battle_admission, dict)
        and item.battle_admission.get("runtime_spawn_requires_explicit_intent") is not True
    )
    checks = {
        "raw_ir_count_matches_s0": s0_matrix["summon_unit_definitions"]["raw_count"] == len(definitions),
        "required_fields_present": not missing,
        "rulebook_by_definition_id_visible": by_id_visible == len(definitions),
        "rulebook_by_unit_id_visible": by_unit_visible == len(definitions),
        "blocked_definitions_have_reason": blocked_without_reason == 0,
        "runtime_spawn_requires_explicit_intent": runtime_spawn_without_intent == 0,
    }
    return _contract_group(
        checks=checks,
        classification="boundary_only",
        raw_count=s0_matrix["summon_unit_definitions"]["raw_count"],
        ir_count=len(definitions),
        rulebook_visible_count=min(by_id_visible, by_unit_visible),
        gap_attribution=_gap_from_missing_and_lookup(missing, len(definitions) - min(by_id_visible, by_unit_visible)),
        details={
            "summon_kind_counts": s0_matrix["summon_unit_definitions"]["summon_kind_counts"],
            "blocked_reason_counts_top": s0_matrix["summon_unit_definitions"]["blocked_reason_counts_top"],
            "missing_required_counts": missing,
            "blocked_without_reason": blocked_without_reason,
            "runtime_spawn_without_explicit_intent": runtime_spawn_without_intent,
        },
    )


def _summon_monster_contract(ir: CanonicalIR, rules: RuleBook, s0_matrix: dict[str, Any]) -> dict[str, Any]:
    intents = tuple(sorted(ir.summon_monster_intents, key=lambda item: item.summon_intent_id))
    required_fields = {
        "summon_intent_id": lambda item: bool(item.summon_intent_id),
        "source_task_id": lambda item: bool(item.source_task_id),
        "owner_scope": lambda item: bool(item.owner_scope),
        "target_scope": lambda item: bool(item.target_scope),
        "delay_policy": lambda item: isinstance(item.delay_policy, dict),
        "entries": lambda item: bool(item.entries),
        "source_event": lambda item: bool(item.source_event),
        "source": lambda item: _source_trace_complete(item.source),
    }
    entry_required = {
        "entry_id": lambda item: bool(item.entry_id),
        "position_policy": lambda item: isinstance(item.position_policy, dict) and bool(item.position_policy.get("source_field")),
        "count": lambda item: isinstance(item.count, int) and item.count > 0,
        "level_policy": lambda item: isinstance(item.level_policy, dict),
        "wave_clear_policy": lambda item: item.wave_clear_policy in {"counts", "ignore", "blocked"},
        "source": lambda item: _source_trace_complete(item.source),
    }
    missing = _missing_required_counts(intents, required_fields)
    entries = tuple(entry for intent in intents for entry in intent.entries)
    entry_missing = _missing_required_counts(entries, entry_required)
    by_id_visible = sum(1 for item in intents if rules.summon_monster_intent(item.summon_intent_id) == item)
    by_task_visible = sum(1 for item in intents if item in rules.summon_monster_intents_for_task(item.source_task_id))
    executable_entries = tuple(entry for entry in entries if entry.coverage_status == "executable")
    executable_entry_profiles_visible = sum(
        1
        for entry in executable_entries
        if rules.combatant_profile(entry.monster_entity_ref) is not None
        and rules.monster_data_card_for_entity(entry.monster_entity_ref) is not None
    )
    blocked_without_reason = sum(1 for item in intents if item.coverage_status == "blocked" and not item.blocked_reason)
    checks = {
        "raw_sources_present": s0_matrix["summon_monster_intents"]["raw_count"] > 0,
        "ir_intents_present": bool(intents),
        "required_fields_present": not missing and not entry_missing,
        "rulebook_by_intent_id_visible": by_id_visible == len(intents),
        "rulebook_by_source_task_visible": by_task_visible == len(intents),
        "executable_entry_profile_and_card_visible": executable_entry_profiles_visible == len(executable_entries),
        "blocked_intents_have_reason": blocked_without_reason == 0,
    }
    return _contract_group(
        checks=checks,
        classification="executable",
        raw_count=s0_matrix["summon_monster_intents"]["raw_count"],
        ir_count=len(intents),
        rulebook_visible_count=min(by_id_visible, by_task_visible),
        gap_attribution=_gap_from_missing_and_lookup(
            Counter({**missing, **{f"entry.{key}": value for key, value in entry_missing.items()}}),
            len(intents) - min(by_id_visible, by_task_visible),
        ),
        details={
            "coverage_status_counts": s0_matrix["summon_monster_intents"]["coverage_status_counts"],
            "entry_coverage_status_counts": s0_matrix["summon_monster_intents"]["entry_coverage_status_counts"],
            "missing_required_counts": missing,
            "entry_missing_required_counts": entry_missing,
            "executable_entry_count": len(executable_entries),
            "executable_entry_profiles_visible": executable_entry_profiles_visible,
            "blocked_without_reason": blocked_without_reason,
        },
    )


def _servant_definition_contract(ir: CanonicalIR, rules: RuleBook, s0_matrix: dict[str, Any]) -> dict[str, Any]:
    definitions = tuple(sorted(ir.servant_definitions, key=lambda item: item.servant_definition_id))
    required_fields = {
        "servant_definition_id": lambda item: bool(item.servant_definition_id),
        "servant_ref": lambda item: bool(item.servant_ref),
        "owner_relations": lambda item: bool(item.owner_relations)
        and len({relation.owner_relation_id for relation in item.owner_relations})
        == len(item.owner_relations)
        and all(
            relation.owner_entity_ref
            and relation.owner_character_card_id
            and relation.auxiliary_skill_ids
            and relation.sources
            and relation.coverage_status == "executable"
            and all(_source_trace_complete(source) for source in relation.sources)
            for relation in item.owner_relations
        ),
        "representation": lambda item: item.representation in {"unit", "component", "blocked"},
        "action_set": lambda item: isinstance(item.action_set, dict),
        "stat_source": lambda item: isinstance(item.stat_source, dict) and _dict_has_source(item.stat_source),
        "timeline_source": lambda item: isinstance(item.timeline_source, dict) and _dict_has_source(item.timeline_source),
        "lifecycle_source": lambda item: isinstance(item.lifecycle_source, dict) and _dict_has_source(item.lifecycle_source),
        "source": lambda item: _source_trace_complete(item.source),
    }
    missing = _missing_required_counts(definitions, required_fields)
    by_id_visible = sum(1 for item in definitions if rules.servant_definition(item.servant_definition_id) == item)
    by_ref_visible = sum(1 for item in definitions if rules.servant_definition(item.servant_ref) == item)
    by_owner_visible = sum(
        1
        for item in definitions
        if item.owner_entity_refs
        and all(
            item in rules.servant_definitions_for_owner(owner_entity_ref)
            for owner_entity_ref in item.owner_entity_refs
        )
    )
    owner_relation_count = sum(
        len(item.owner_entity_refs) for item in definitions
    )
    owner_relation_visible_count = sum(
        item in rules.servant_definitions_for_owner(owner_entity_ref)
        for item in definitions
        for owner_entity_ref in item.owner_entity_refs
    )
    action_set_visible = sum(1 for item in definitions if rules.combatant_action_set(item.servant_ref) is not None)
    binding_ids = tuple(binding_id for definition in definitions for binding_id in definition.ability_graph_ids)
    binding_visible = sum(1 for binding_id in binding_ids if rules.action_ability_binding_by_id(binding_id) is not None)
    blocked_without_reason = sum(1 for item in definitions if item.coverage_status == "blocked" and not item.blocked_reason)
    checks = {
        "raw_ir_count_matches_s0": s0_matrix["servant_sources"]["raw_servant_config_count"] == len(definitions),
        "required_fields_present": not missing,
        "rulebook_by_definition_ref_owner_visible": (
            by_id_visible == len(definitions)
            and by_ref_visible == len(definitions)
            and by_owner_visible == len(definitions)
        ),
        "combatant_action_set_visible": action_set_visible == len(definitions),
        "ability_graph_bindings_visible": binding_visible == len(binding_ids),
        "blocked_definitions_have_reason": blocked_without_reason == 0,
    }
    lookup_miss = (len(definitions) - min(by_id_visible, by_ref_visible, by_owner_visible)) + (len(binding_ids) - binding_visible)
    return _contract_group(
        checks=checks,
        classification="executable",
        raw_count=s0_matrix["servant_sources"]["raw_servant_config_count"],
        ir_count=len(definitions),
        rulebook_visible_count=min(by_id_visible, by_ref_visible, by_owner_visible),
        gap_attribution=_gap_from_missing_and_lookup(missing, lookup_miss),
        details={
            "coverage_status_counts": s0_matrix["servant_sources"]["coverage_status_counts"],
            "missing_required_counts": missing,
            "action_set_visible_count": action_set_visible,
            "ability_graph_binding_count": len(binding_ids),
            "ability_graph_binding_visible_count": binding_visible,
            "blocked_without_reason": blocked_without_reason,
            "owner_relation_count": owner_relation_count,
            "owner_relation_visible_count": owner_relation_visible_count,
        },
    )


def _assistant_resolution_contract(ir: CanonicalIR, rules: RuleBook, s0_matrix: dict[str, Any]) -> dict[str, Any]:
    resolutions = tuple(sorted(ir.assistant_ability_resolutions, key=lambda item: item.assistant_resolution_id))
    assistant_intents = tuple(intent for intent in ir.queue_intents if intent.opcode == "TurnInsertAssistantAbility")
    required_fields = {
        "assistant_resolution_id": lambda item: bool(item.assistant_resolution_id),
        "queue_intent_id": lambda item: bool(item.queue_intent_id),
        "owner_alias": lambda item: isinstance(item.owner_alias, str),
        "target_alias": lambda item: isinstance(item.target_alias, str),
        "attribution_policy": lambda item: isinstance(item.attribution_policy, dict),
        "source": lambda item: _source_trace_complete(item.source),
    }
    missing = _missing_required_counts(resolutions, required_fields)
    by_id_visible = sum(1 for item in resolutions if rules.assistant_ability_resolution(item.assistant_resolution_id) == item)
    by_intent_visible = sum(1 for item in resolutions if rules.assistant_ability_resolution_for_intent(item.queue_intent_id) == item)
    intent_visible = sum(1 for item in resolutions if rules.queue_intent(item.queue_intent_id) is not None)
    queue_window_visible = sum(1 for item in resolutions if rules.queue_window_for_intent(item.queue_intent_id) is not None)
    ability_lookup_count = sum(
        1
        for item in resolutions
        if item.assistant_ability_id
        and item in rules.assistant_ability_resolutions_for_ability(item.assistant_ability_id)
    )
    resolutions_with_ability_id = sum(1 for item in resolutions if item.assistant_ability_id)
    blocked_without_reason = sum(1 for item in resolutions if item.coverage_status == "blocked" and not item.blocked_reason)
    blocked_without_attribution = sum(
        1
        for item in resolutions
        if item.coverage_status == "blocked"
        and str(item.attribution_policy.get("kind") or "") != "blocked"
    )
    checks = {
        "raw_queue_intent_resolution_counts_match_s0": (
            s0_matrix["assistant_sources"]["raw_count"]
            == len(assistant_intents)
            == len(resolutions)
        ),
        "required_fields_present": not missing,
        "rulebook_by_resolution_and_intent_visible": (
            by_id_visible == len(resolutions)
            and by_intent_visible == len(resolutions)
            and intent_visible == len(resolutions)
        ),
        "queue_window_visible_for_each_resolution": queue_window_visible == len(resolutions),
        "ability_id_lookup_visible_when_fixed": ability_lookup_count == resolutions_with_ability_id,
        "blocked_resolutions_have_reason": blocked_without_reason == 0,
        "blocked_resolutions_are_process_boundary": blocked_without_attribution == 0,
    }
    return _contract_group(
        checks=checks,
        classification="out_of_scope",
        raw_count=s0_matrix["assistant_sources"]["raw_count"],
        ir_count=len(resolutions),
        rulebook_visible_count=min(by_id_visible, by_intent_visible, intent_visible, queue_window_visible),
        gap_attribution={},
        details={
            "scope_exclusion_reason": (
                "AssistantAbilityResolutionIR is Avatar Assistant / AssistantAvatar queue evidence, "
                "not summon monster or servant runtime contract."
            ),
            "queue_intent_count": len(assistant_intents),
            "queue_window_count": len(rules.queue_windows_by_family("assistant")),
            "resolution_coverage_status_counts": s0_matrix["assistant_sources"]["resolution_coverage_status_counts"],
            "blocked_reason_counts_top": s0_matrix["assistant_sources"]["blocked_reason_counts_top"],
            "missing_required_counts": missing,
            "fixed_ability_id_resolution_count": resolutions_with_ability_id,
            "fixed_ability_id_lookup_count": ability_lookup_count,
            "blocked_without_reason": blocked_without_reason,
        },
    )


def _queue_lifecycle_action_contract(ir: CanonicalIR, rules: RuleBook, s0_matrix: dict[str, Any]) -> dict[str, Any]:
    assistant_windows = rules.queue_windows_by_family("assistant")
    extra_turn_lifecycle = rules.queue_lifecycle_policies_by_family("extra_turn")
    servant_action_sets = tuple(
        action_set
        for action_set in rules.combatant_action_sets()
        if action_set.entity_ref.startswith("servant:")
    )
    servant_bindings = tuple(
        binding_id
        for definition in ir.servant_definitions
        for binding_id in definition.ability_graph_ids
    )
    servant_binding_visible = sum(1 for binding_id in servant_bindings if rules.action_ability_binding_by_id(binding_id) is not None)
    assistant_window_by_intent_visible = sum(
        1
        for intent in ir.queue_intents
        if intent.opcode == "TurnInsertAssistantAbility" and rules.queue_window_for_intent(intent.queue_intent_id) is not None
    )
    extra_action_policies = rules.extra_action_policies()
    checks = {
        "assistant_windows_visible_by_family": len(assistant_windows) == s0_matrix["assistant_sources"]["assistant_queue_window_ir_count"],
        "extra_turn_lifecycle_policy_collection_visible": bool(extra_turn_lifecycle),
        "extra_action_policy_collection_visible": len(extra_action_policies) == len(ir.extra_action_policies),
        "servant_action_sets_visible": len(servant_action_sets) == len(ir.servant_definitions),
        "servant_action_bindings_visible": servant_binding_visible == len(servant_bindings),
        "assistant_queue_window_by_intent_visible": assistant_window_by_intent_visible == len(
            [intent for intent in ir.queue_intents if intent.opcode == "TurnInsertAssistantAbility"]
        ),
    }
    lookup_miss = (len(servant_bindings) - servant_binding_visible) + (
        len([intent for intent in ir.queue_intents if intent.opcode == "TurnInsertAssistantAbility"])
        - assistant_window_by_intent_visible
    )
    return _contract_group(
        checks=checks,
        classification="boundary_only",
        raw_count=s0_matrix["lifecycle_sources"]["raw_count"],
        ir_count=s0_matrix["lifecycle_sources"]["ir_count"],
        rulebook_visible_count=len(extra_turn_lifecycle) + len(servant_action_sets) + len(assistant_windows),
        gap_attribution=_gap_from_missing_and_lookup(Counter(), lookup_miss),
        details={
            "assistant_queue_window_count": len(assistant_windows),
            "extra_turn_lifecycle_policy_count": len(extra_turn_lifecycle),
            "extra_action_policy_count": len(extra_action_policies),
            "servant_action_set_count": len(servant_action_sets),
            "servant_action_binding_count": len(servant_bindings),
            "servant_action_binding_visible_count": servant_binding_visible,
        },
    )


def _target_cross_system_contract(ir: CanonicalIR, rules: RuleBook, s0_matrix: dict[str, Any]) -> dict[str, Any]:
    p3_target_ids = {
        str(sample.get("target_expression_id"))
        for sample in (
            s0_matrix["target_relation_sources"].get("sample_target_expression"),
        )
        if isinstance(sample, dict) and sample.get("target_expression_id")
    }
    p3_target_expressions = tuple(
        expression
        for expression in ir.target_expressions
        if _is_p3_target_expression(expression) or expression.target_expression_id in p3_target_ids
    )
    target_source_trace_complete = sum(1 for item in p3_target_expressions if _source_trace_complete(item.source))
    target_rulebook_visible = sum(1 for item in p3_target_expressions if rules.target_expression(item.target_expression_id) == item)
    servant_action_definitions = tuple(
        definition
        for definition in ir.action_definitions
        if definition.action_id.startswith("servant_skill:")
        or definition.source.source_path == "ExcelOutput/AvatarServantSkillConfig.json"
    )
    servant_action_source_trace_complete = sum(1 for item in servant_action_definitions if _source_trace_complete(item.source))
    servant_damage_formula_source_count = sum(1 for item in servant_action_definitions if item.damage_formula_family)
    resource_rules_visible = sum(1 for item in ir.resource_rules if rules.resource_rule(item.resource_rule_id) == item)
    checks = {
        "p3_target_expressions_visible": (
            target_rulebook_visible == len(p3_target_expressions)
            and len(p3_target_expressions) == s0_matrix["target_relation_sources"]["ir_count"]
        ),
        "p3_target_source_trace_complete": target_source_trace_complete == len(p3_target_expressions),
        "servant_action_source_trace_complete": servant_action_source_trace_complete == len(servant_action_definitions),
        "servant_damage_formula_classified": servant_damage_formula_source_count == len(servant_action_definitions),
        "resource_rules_rulebook_visible": resource_rules_visible == len(ir.resource_rules),
    }
    lookup_miss = (len(p3_target_expressions) - target_rulebook_visible) + (len(ir.resource_rules) - resource_rules_visible)
    missing = Counter()
    if target_source_trace_complete != len(p3_target_expressions):
        missing["target_expression.source"] = len(p3_target_expressions) - target_source_trace_complete
    if servant_action_source_trace_complete != len(servant_action_definitions):
        missing["servant_action.source"] = len(servant_action_definitions) - servant_action_source_trace_complete
    return _contract_group(
        checks=checks,
        classification="executable",
        raw_count=s0_matrix["target_relation_sources"]["raw_count"],
        ir_count=len(p3_target_expressions),
        rulebook_visible_count=target_rulebook_visible,
        gap_attribution=_gap_from_missing_and_lookup(missing, lookup_miss),
        details={
            "p3_target_expression_count": len(p3_target_expressions),
            "p3_target_rulebook_visible_count": target_rulebook_visible,
            "servant_action_definition_count": len(servant_action_definitions),
            "servant_action_source_trace_complete_count": servant_action_source_trace_complete,
            "resource_rule_count": len(ir.resource_rules),
            "resource_rule_visible_count": resource_rules_visible,
        },
    )


def _contract_group(
    *,
    checks: dict[str, bool],
    classification: str,
    raw_count: int,
    ir_count: int,
    rulebook_visible_count: int,
    gap_attribution: dict[str, int],
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ok": all(checks.values()),
        "classification": classification,
        "raw_count": int(raw_count),
        "ir_count": int(ir_count),
        "rulebook_visible_count": int(rulebook_visible_count),
        "gap_attribution": dict(sorted((key, int(value)) for key, value in gap_attribution.items() if value)),
        "checks": checks,
        "details": details,
    }


def _missing_required_counts(items: tuple[Any, ...], required_fields: dict[str, Any]) -> Counter[str]:
    missing: Counter[str] = Counter()
    for item in items:
        for field_name, predicate in required_fields.items():
            try:
                present = bool(predicate(item))
            except Exception:
                present = False
            if not present:
                missing[field_name] += 1
    return missing


def _gap_from_missing_and_lookup(missing: Counter[str], lookup_miss_count: int) -> dict[str, int]:
    gaps = Counter()
    if missing:
        gaps["lowering_gap"] += sum(missing.values())
    if lookup_miss_count:
        gaps["admission_gap"] += lookup_miss_count
    return dict(sorted(gaps.items()))


def _source_trace_complete(source: IRSource | None) -> bool:
    return (
        isinstance(source, IRSource)
        and bool(source.source_path)
        and bool(source.raw_type)
        and bool(source.raw_id)
        and isinstance(source.evidence, dict)
    )


def _dict_has_source(value: dict[str, Any]) -> bool:
    if isinstance(value.get("source_trace"), (list, tuple)):
        return bool(value.get("source_trace"))
    if isinstance(value.get("source"), dict):
        return bool(value["source"].get("source_path"))
    if isinstance(value.get("owner_source"), dict):
        return bool(value["owner_source"].get("source_path"))
    return bool(value)


P3_TARGET_ALIASES = {
    "CasterServant",
    "CasterSummonedMinions",
    "LastSummonMonsters",
    "ServantEntityList",
}

ASSISTANT_AVATAR_TARGET_ALIASES = {
    "AssistantAvatar",
    "FriendServantSelect",
}


def _is_p3_target_expression(expression: Any) -> bool:
    alias = str(getattr(expression, "alias", "") or "")
    kind = str(getattr(expression, "expression_kind", "") or "")
    source = getattr(expression, "source", None)
    evidence = source.evidence if isinstance(source, IRSource) and isinstance(source.evidence, dict) else {}
    operation = str(evidence.get("operation") or "")
    base_alias = str(evidence.get("base_alias") or "")
    if _is_assistant_avatar_target_alias(alias) or _is_assistant_avatar_target_alias(base_alias):
        return False
    return (
        alias in P3_TARGET_ALIASES
        or any(term in alias.lower() for term in ("servant", "summon", "summoner"))
        or kind in {"TargetFetchModifierOwner", "TargetFetchOwner", "TargetQuery"}
        or operation in {"GetServant", "GetSummoner", "RemoveServant"}
        or base_alias in P3_TARGET_ALIASES
        or any(term in operation.lower() for term in ("servant", "summon", "summoner"))
    )


def _is_assistant_avatar_target_alias(alias: str) -> bool:
    return alias in ASSISTANT_AVATAR_TARGET_ALIASES


if __name__ == "__main__":
    raise SystemExit(main())
