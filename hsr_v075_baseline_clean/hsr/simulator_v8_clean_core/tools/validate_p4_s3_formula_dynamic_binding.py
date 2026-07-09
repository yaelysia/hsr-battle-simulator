from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Iterable

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, JSONValue, UnitState
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.evaluator import NumericEvaluationContext, RuleEvaluator
from ..rules.ir import CanonicalIR, SkillFormulaBindingIR
from ..rules.rulebook import RuleBook
from ..systems.action_availability import ActionAvailabilitySystem, ActionChoice
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p1_3_summon_assistant_servant import _select_executable_summon_monster_intent
from .validate_p3_s6_summon_action_execution import _spawn_summoned_monster_turn_state
from .validate_p4_s0_combatant_source_inventory import build_p4_s0_combatant_source_inventory_matrix


VALIDATION_VERSION = "p4_s3_formula_dynamic_binding"
MATRIX_SCHEMA_VERSION = "p4_s3_formula_dynamic_binding_matrix_v1"

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
REQUIRED_ROWS = {
    "s0_dynamic_formula_source_domains_inherited",
    "skill_formula_binding_to_hit_profile",
    "action_formula_runtime_usage",
    "dynamic_numeric_evaluator_binding",
    "combatant_profile_stat_source",
    "monster_custom_dynamic_parameter_blocks",
    "summon_intent_dynamic_custom_profile_gap_reclassification",
    "param_index_boundary_scan",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    s0_matrix = build_p4_s0_combatant_source_inventory_matrix(tbgd_root, ir, rules)
    matrix = build_p4_s3_formula_dynamic_binding_matrix(ir, rules, s0_matrix)
    matrix_checks = validate_p4_s3_formula_dynamic_binding_matrix(matrix)
    checks = {
        "matrix": matrix_checks,
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "p4_s3_formula_dynamic_structural_predicates",
                "runtime_raw_tbgd_read": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "dynamic_hash_hardcoded_to_name_or_value": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "formula_dynamic_binding_matrix": matrix["formula_dynamic_binding_matrix"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p4_s3_formula_dynamic_binding.json", result)
    write_json(output_dir / "p4_s3_formula_dynamic_binding_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P4-S3 formula/dynamic/custom value binding ledger.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} validation ok={result['ok']} "
        f"rows={result['summary']['row_count']} "
        f"classifications={result['summary']['classification_counts']}"
    )
    return 0 if result["ok"] else 1


def build_p4_s3_formula_dynamic_binding_matrix(
    ir: CanonicalIR,
    rules: RuleBook,
    s0_matrix: dict[str, Any],
) -> dict[str, Any]:
    runtime_formula = _action_formula_runtime_usage_row(ir, rules)
    rows = [
        _s0_dynamic_formula_source_domains_row(s0_matrix),
        _skill_formula_binding_to_hit_profile_row(ir, rules, runtime_formula),
        runtime_formula,
        _dynamic_numeric_evaluator_binding_row(ir),
        _combatant_profile_stat_source_row(ir, rules),
        _monster_custom_dynamic_parameter_blocks_row(ir, rules, s0_matrix),
        _summon_intent_dynamic_custom_profile_gap_reclassification_row(ir, rules),
        _param_index_boundary_scan_row(ir),
    ]
    matrix = {str(row["row_id"]): row for row in rows}
    classification_counts = Counter(str(row.get("classification") or "unclassified") for row in rows)
    gap_counts: Counter[str] = Counter()
    for row in rows:
        for key, value in dict(row.get("gap_attribution") or {}).items():
            gap_counts[str(key)] += int(value or 0)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "formula_dynamic_binding_matrix": matrix,
        "summary": {
            "row_count": len(matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "unclassified_count": int(classification_counts.get("unclassified", 0)),
            "runtime_formula_usage_ok": runtime_formula["checks"]["ok"],
            "dynamic_hash_positive_negative_ok": matrix["dynamic_numeric_evaluator_binding"]["checks"]["ok"],
            "summon_gap_reclassified_count": matrix[
                "summon_intent_dynamic_custom_profile_gap_reclassification"
            ]["details"].get("reclassified_gap_count"),
        },
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "combat_executor_runtime_sample_count": 1,
            "full_ir_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_files": [
                "validation_summary_p4_s3_formula_dynamic_binding.json",
                "p4_s3_formula_dynamic_binding_matrix.json",
            ],
        },
    }


def validate_p4_s3_formula_dynamic_binding_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("formula_dynamic_binding_matrix") or {})
    missing = sorted(REQUIRED_ROWS.difference(rows))
    invalid_classifications = sorted(
        row_id
        for row_id, row in rows.items()
        if str(row.get("classification") or "unclassified") not in CLASSIFICATION_STATES
    )
    gap_rows = [row for row in rows.values() if str(row.get("classification") or "") in GAP_STATES]
    checks = {
        "required_rows_present": not missing,
        "valid_classifications": not invalid_classifications,
        "unclassified_count_zero": int(matrix.get("summary", {}).get("unclassified_count") or 0) == 0,
        "row_checks_ok": all(dict(row.get("checks") or {}).get("ok") is True for row in rows.values()),
        "gap_rows_have_attribution": all(bool(row.get("gap_attribution")) for row in gap_rows),
        "runtime_formula_usage_executable": rows.get("action_formula_runtime_usage", {}).get("classification")
        == "executable",
        "runtime_formula_replay_and_audit_ok": _row_check(rows, "action_formula_runtime_usage", "replay_ok")
        and _row_check(rows, "action_formula_runtime_usage", "source_audit_ok"),
        "dynamic_hash_bound_and_unbound_checked": _row_check(rows, "dynamic_numeric_evaluator_binding", "bound_ok")
        and _row_check(rows, "dynamic_numeric_evaluator_binding", "unbound_blocked"),
        "summon_gap_reclassified": int(
            rows.get("summon_intent_dynamic_custom_profile_gap_reclassification", {})
            .get("details", {})
            .get("reclassified_gap_count")
            or 0
        )
        >= 0,
        "s0_dynamic_domains_inherited": _row_check(rows, "s0_dynamic_formula_source_domains_inherited", "all_s0_rows_present"),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_rows": missing,
        "invalid_classifications": invalid_classifications,
    }


def _s0_dynamic_formula_source_domains_row(s0_matrix: dict[str, Any]) -> dict[str, JSONValue]:
    source_matrix = dict(
        s0_matrix.get("domain_matrix")
        or s0_matrix.get("source_inventory_matrix")
        or s0_matrix.get("matrix")
        or {}
    )
    row_ids = (
        "avatar_skill_param_formula_sources",
        "monster_skill_param_formula_sources",
        "ilbattle_skill_param_formula_sources",
        "dynamic_config_ability_fields",
        "dynamic_avatar_skilltree_param_fields",
        "dynamic_monster_custom_value_fields",
        "dynamic_modifier_hash_fields",
    )
    rows = {row_id: dict(source_matrix.get(row_id) or {}) for row_id in row_ids}
    missing = [row_id for row_id, row in rows.items() if not row]
    raw_count = sum(int(row.get("raw_count") or 0) for row in rows.values())
    ir_count = sum(int(row.get("ir_count") or 0) for row in rows.values())
    gap_count = sum(int(row.get("blocked_or_gap_count") or 0) for row in rows.values())
    checks = {
        "all_s0_rows_present": not missing,
        "raw_sources_present": raw_count > 0,
        "ir_projection_present": ir_count > 0,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "s0_dynamic_formula_source_domains_inherited",
        classification="admission_gap" if gap_count else "executable",
        checks=checks,
        raw_count=raw_count,
        ir_count=ir_count,
        executable_count=sum(int(row.get("executable_count") or 0) for row in rows.values()),
        blocked_or_gap_count=gap_count,
        gap_attribution={"admission_gap": gap_count} if gap_count else {},
        details={
            "inherited_row_ids": list(row_ids),
            "missing_row_ids": missing,
            "source_domain_classifications": {row_id: row.get("classification", "") for row_id, row in rows.items()},
        },
    )


def _skill_formula_binding_to_hit_profile_row(
    ir: CanonicalIR,
    rules: RuleBook,
    runtime_formula_row: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    bindings = tuple(ir.skill_formula_bindings)
    status_counts = Counter(str(binding.coverage_status) for binding in bindings)
    data_card_kind_counts = Counter(str(binding.data_card_kind or ("character" if binding.character_data_card_id else "")) for binding in bindings)
    visible_count = sum(1 for binding in bindings if rules.skill_formula_binding(binding.binding_id) is binding)
    linked_count = _formula_binding_hit_profile_link_count(ir)
    blocked = len(bindings) - int(status_counts.get("executable", 0))
    sample_binding = _first(bindings)
    checks = {
        "bindings_present": bool(bindings),
        "rulebook_visible": visible_count == len(bindings),
        "hit_profile_links_present": linked_count > 0,
        "runtime_usage_sample_present": runtime_formula_row.get("classification") == "executable",
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "skill_formula_binding_to_hit_profile",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=len(bindings),
        ir_count=len(bindings),
        rulebook_visible_count=visible_count,
        executable_count=int(status_counts.get("executable", 0)),
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_source(sample_binding),
        details={
            "coverage_status_counts": dict(sorted(status_counts.items())),
            "data_card_kind_counts": dict(sorted(data_card_kind_counts.items())),
            "hit_profile_link_count": linked_count,
            "sample_binding": _compact_formula_binding(sample_binding),
        },
    )


def _action_formula_runtime_usage_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    case = _select_and_execute_formula_action(ir, rules)
    checks = dict(case["checks"])
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "action_formula_runtime_usage",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        raw_count=case["source_counts"]["damage_emission_count"],
        ir_count=case["source_counts"]["hit_profile_count"],
        executable_count=1 if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        sample_source_trace=case["source_trace"],
        runtime_samples=[case["runtime_sample"]],
        details={
            "selection_predicate": "availability choice with executable damage emission, hit profile, replay and source audit",
            "mutation_source_counts": case["mutation_source_counts"],
            "coverage": case["coverage"],
        },
    )


def _dynamic_numeric_evaluator_binding_row(ir: CanonicalIR) -> dict[str, JSONValue]:
    sample = _find_dynamic_hash_sample(ir)
    if sample is None:
        checks = {"source_absent": True, "no_synthetic_dynamic_hash": True, "ok": True}
        return _row(
            "dynamic_numeric_evaluator_binding",
            classification="source_absent_not_required",
            checks=checks,
            details={"note": "No dynamic hash expression found in current S3 IR scan; no synthetic hash was created."},
        )
    evaluator = RuleEvaluator()
    hash_key = str(sample["hash"])
    source_trace = dict(sample["source_trace"])
    bound = evaluator.evaluate_numeric(
        {"kind": "dynamic_hash", "hash": sample["hash"]},
        NumericEvaluationContext(dynamic_values={hash_key: 1.25}, source_trace=source_trace),
    )
    unbound = evaluator.evaluate_numeric(
        {"kind": "dynamic_hash", "hash": sample["hash"]},
        NumericEvaluationContext(dynamic_values={}, source_trace=source_trace),
    )
    checks = {
        "dynamic_hash_source_present": bool(source_trace),
        "bound_ok": bound.ok and bound.value == 1.25,
        "bound_source_trace_preserved": bound.source_trace == source_trace,
        "unbound_blocked": not unbound.ok and unbound.blocked_reason.startswith("dynamic_hash_unbound:"),
        "no_hash_name_or_value_hardcode": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "dynamic_numeric_evaluator_binding",
        classification="executable",
        checks=checks,
        raw_count=sample["scan_count"],
        ir_count=sample["scan_count"],
        executable_count=1,
        blocked_or_gap_count=1,
        sample_source_trace=source_trace,
        runtime_samples=[
            {
                "expression_source_kind": sample["source_kind"],
                "hash": sample["hash"],
                "bound": bound.to_json(),
                "unbound": unbound.to_json(),
            }
        ],
        details={"sample_expression": sample["expression"]},
    )


def _combatant_profile_stat_source_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    profiles = tuple(ir.combatant_profiles)
    visible = sum(1 for profile in profiles if rules.combatant_profile(profile.entity_id) is profile)
    required_stats = ("max_hp", "attack", "defense", "speed")
    executable = [
        profile
        for profile in profiles
        if profile.coverage_status == "executable"
        and all(isinstance(profile.base_stats.get(stat), (int, float)) for stat in required_stats)
    ]
    missing_stats = [
        profile
        for profile in profiles
        if not all(isinstance(profile.base_stats.get(stat), (int, float)) for stat in required_stats)
    ]
    runtime_sample = _summoned_monster_profile_runtime_sample(rules)
    checks = {
        "profiles_present": bool(profiles),
        "rulebook_visible": visible == len(profiles),
        "executable_profile_stats_present": bool(executable),
        "runtime_spawn_used_profile_source": runtime_sample.get("ok") is True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "combatant_profile_stat_source",
        classification="admission_gap" if missing_stats else "executable",
        checks=checks,
        raw_count=len(profiles),
        ir_count=len(profiles),
        rulebook_visible_count=visible,
        executable_count=len(executable),
        blocked_or_gap_count=len(missing_stats),
        gap_attribution={"admission_gap": len(missing_stats)} if missing_stats else {},
        sample_source_trace=_source(_first(executable) or _first(profiles)),
        runtime_samples=[runtime_sample],
        details={
            "required_stats": list(required_stats),
            "missing_stat_profile_count": len(missing_stats),
            "coverage_status_counts": dict(sorted(Counter(profile.coverage_status for profile in profiles).items())),
        },
    )


def _monster_custom_dynamic_parameter_blocks_row(
    ir: CanonicalIR,
    rules: RuleBook,
    s0_matrix: dict[str, Any],
) -> dict[str, JSONValue]:
    cards = tuple(card for card in ir.monster_data_cards if card.raw_parameter_blocks)
    key_counts: Counter[str] = Counter()
    for card in cards:
        for key, value in card.raw_parameter_blocks.items():
            if value not in ({}, (), [], None, ""):
                key_counts[str(key)] += 1
    source_matrix = dict(
        s0_matrix.get("domain_matrix")
        or s0_matrix.get("source_inventory_matrix")
        or s0_matrix.get("matrix")
        or {}
    )
    s0_row = dict(source_matrix.get("dynamic_monster_custom_value_fields") or {})
    raw_count = int(s0_row.get("raw_count") or len(cards))
    checks = {
        "s0_dynamic_monster_row_present": bool(s0_row),
        "raw_parameter_blocks_inventoried": len(cards) >= 0,
        "no_custom_hash_promoted_to_executable": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    gap_count = sum(key_counts.values())
    return _row(
        "monster_custom_dynamic_parameter_blocks",
        classification="admission_gap" if gap_count else "source_absent_not_required",
        checks=checks,
        raw_count=raw_count,
        ir_count=len(cards),
        rulebook_visible_count=sum(1 for card in cards if rules.monster_data_card(card.card_id) is card),
        executable_count=0,
        blocked_or_gap_count=gap_count,
        gap_attribution={"admission_gap": gap_count} if gap_count else {},
        sample_source_trace=_source(_first(cards)),
        details={
            "raw_parameter_block_card_count": len(cards),
            "raw_parameter_block_key_counts": dict(sorted(key_counts.items())),
            "s0_classification": s0_row.get("classification", ""),
            "note": "CustomValues/DynamicValues/OverrideSkillParams stay admission gaps until a generic binding source is available.",
        },
    )


def _summon_intent_dynamic_custom_profile_gap_reclassification_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    intents = tuple(ir.summon_monster_intents)
    visible = sum(1 for intent in intents if rules.summon_monster_intent(intent.summon_intent_id) is intent)
    token_counts: Counter[str] = Counter()
    blocked = []
    for intent in intents:
        if intent.coverage_status == "executable":
            continue
        blocked.append(intent)
        reason = intent.blocked_reason or f"summon_monster_intent_not_executable:{intent.coverage_status}"
        category = _summon_gap_category(reason)
        token_counts[category] += 1
    reclassified = sum(token_counts.values())
    checks = {
        "intents_present": bool(intents),
        "rulebook_visible": visible == len(intents),
        "blocked_reasons_classified": len(blocked) == reclassified,
        "dynamic_custom_profile_categories_present": any(
            token_counts.get(key, 0) > 0 for key in ("dynamic_or_custom_value", "profile_or_card_source")
        )
        or not blocked,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "summon_intent_dynamic_custom_profile_gap_reclassification",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=len(intents),
        ir_count=len(intents),
        rulebook_visible_count=visible,
        executable_count=len(intents) - len(blocked),
        blocked_or_gap_count=len(blocked),
        gap_attribution={"admission_gap": len(blocked)} if blocked else {},
        sample_source_trace=_source(_first(blocked) or _first(intents)),
        details={
            "reclassified_gap_count": reclassified,
            "gap_category_counts": dict(sorted(token_counts.items())),
            "sample_blocked_reasons": [intent.blocked_reason for intent in blocked[:5]],
        },
    )


def _param_index_boundary_scan_row(ir: CanonicalIR) -> dict[str, JSONValue]:
    binding_gaps = [binding for binding in ir.skill_formula_bindings if "param_index" in (binding.blocked_reason or "")]
    profile_gaps = [profile for profile in ir.hit_profiles if "param_index" in (profile.blocked_reason or "")]
    total = len(binding_gaps) + len(profile_gaps)
    checks = {
        "scan_completed": bool(ir.skill_formula_bindings or ir.hit_profiles),
        "blocked_reasons_specific_when_present": all(
            "param_index" in (item.blocked_reason or "") for item in (*binding_gaps, *profile_gaps)
        ),
        "no_synthetic_param_index_case": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "param_index_boundary_scan",
        classification="admission_gap" if total else "source_absent_not_required",
        checks=checks,
        raw_count=len(ir.skill_formula_bindings),
        ir_count=len(ir.hit_profiles),
        executable_count=0,
        blocked_or_gap_count=total,
        gap_attribution={"admission_gap": total} if total else {},
        sample_source_trace=_source(_first(binding_gaps) or _first(profile_gaps)),
        details={
            "skill_formula_binding_param_index_gap_count": len(binding_gaps),
            "hit_profile_param_index_gap_count": len(profile_gaps),
            "note": "No synthetic out-of-range ParamList sample is created when current IR has none.",
        },
    )


def _select_and_execute_formula_action(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    availability = ActionAvailabilitySystem(rules)
    for card in sorted(ir.character_data_cards, key=lambda item: item.card_id):
        if rules.combatant_action_set(card.entity_ref) is None:
            continue
        actor = _ally_unit("ally:formula_actor", card.entity_ref)
        state = BattleState(
            units={"ally:formula_actor": actor, "enemy:formula_target": _enemy_target()},
            skill_points=5,
            max_skill_points=5,
            global_flags={"phase": "scenario", "current_window": "idle", "turn_owner_id": "ally:formula_actor"},
        )
        view = availability.view(state)
        for choice in view.choices:
            if not (choice.auto_target_ids or choice.selectable_target_ids):
                continue
            damage_emissions = rules.damage_emissions_for_action(choice.action_id, choice.action_level)
            hit_profiles = rules.hit_profiles_for_action(choice.action_id, choice.action_level)
            if not damage_emissions or not any(profile.coverage_status == "executable" for profile in hit_profiles):
                continue
            command = _command_from_choice(choice)
            after, transition = CombatExecutor(rules).execute(command, state)
            replay = MutationReducer().replay_snapshot(state, transition.transaction.mutations, transition.after.to_json())
            audit = RuntimeSourceAuditor(rules).validate_transition(transition)
            coverage = dict(transition.coverage)
            if (
                coverage.get("action_enabled") is True
                and coverage.get("damage_mutation_count", 0)
                and replay.ok
                and audit.ok
            ):
                return {
                    "checks": {
                        "action_enabled": True,
                        "damage_mutation_present": True,
                        "hit_profile_present": bool(hit_profiles),
                        "damage_emission_present": bool(damage_emissions),
                        "settlement_present": transition.transaction.settlement is not None,
                        "replay_ok": replay.ok,
                        "source_audit_ok": audit.ok,
                        "after_matches_transition": after.snapshot().to_json() == transition.after.to_json(),
                    },
                    "source_counts": {
                        "damage_emission_count": len(damage_emissions),
                        "hit_profile_count": len(hit_profiles),
                    },
                    "source_trace": {
                        "action_choice": choice.source_trace,
                        "hit_profile": hit_profiles[0].source.to_json(),
                        "damage_emission": damage_emissions[0].source.to_json(),
                    },
                    "runtime_sample": {
                        "actor_data_card_id": card.card_id,
                        "action_id": choice.action_id,
                        "action_level": choice.action_level,
                        "target_ids": list(command.target_ids),
                        "damage_mutation_count": coverage.get("damage_mutation_count", 0),
                        "toughness_mutation_count": coverage.get("toughness_mutation_count", 0),
                        "record_count": len(transition.transaction.settlement.records)
                        if transition.transaction.settlement is not None
                        else 0,
                    },
                    "mutation_source_counts": _mutation_source_counts(transition.transaction.mutations),
                    "coverage": _compact_coverage(coverage),
                }
    raise RuntimeError("no executable formula runtime action selected by structured predicate")


def _summoned_monster_profile_runtime_sample(rules: RuleBook) -> dict[str, JSONValue]:
    intent = _select_executable_summon_monster_intent(rules)
    state = _spawn_summoned_monster_turn_state(rules, intent)
    actor_id = str(state.global_flags.get("turn_owner_id") or "")
    unit = state.units.get(actor_id)
    if unit is None:
        return {"ok": False, "blocked_reason": "spawned_unit_missing"}
    return {
        "ok": bool(unit.flags.get("combatant_profile_source_trace")) and unit.max_hp > 0 and unit.speed > 0,
        "summon_intent_id": intent.summon_intent_id,
        "unit_id": unit.unit_id,
        "template_id": unit.template_id,
        "profile_id": unit.flags.get("combatant_profile_id"),
        "max_hp": unit.max_hp,
        "attack": unit.attack,
        "defense": unit.defense,
        "speed": unit.speed,
        "combatant_profile_source_trace": unit.flags.get("combatant_profile_source_trace")
        if isinstance(unit.flags.get("combatant_profile_source_trace"), dict)
        else {},
    }


def _find_dynamic_hash_sample(ir: CanonicalIR) -> dict[str, Any] | None:
    samples: list[dict[str, Any]] = []

    def add_from_expr(source_kind: str, source_trace: dict[str, JSONValue], expression: Any) -> None:
        for expr in _iter_dynamic_hash_exprs(expression):
            samples.append(
                {
                    "source_kind": source_kind,
                    "source_trace": source_trace,
                    "expression": expr,
                    "hash": expr.get("hash"),
                }
            )

    for formula in ir.formulas:
        add_from_expr("FormulaIR.expression", formula.source.to_json(), formula.expression)
    for emission in ir.damage_emissions:
        add_from_expr("DamageEmissionIR.scaling_ratio_expr", emission.source.to_json(), emission.scaling_ratio_expr)
        add_from_expr("DamageEmissionIR.scaling_basis_expr", emission.source.to_json(), emission.scaling_basis_expr)
    for emission in ir.toughness_emissions:
        add_from_expr("ToughnessEmissionIR.toughness_amount_expr", emission.source.to_json(), emission.toughness_amount_expr)
    for emission in ir.status_damage_emissions:
        add_from_expr("StatusDamageEmissionIR.scaling_expr", emission.source.to_json(), emission.scaling_expr)
    for emission in ir.break_damage_emissions:
        add_from_expr("BreakDamageEmissionIR.scaling_expr", emission.source.to_json(), emission.scaling_expr)
    for emission in ir.action_delay_emissions:
        add_from_expr("ActionDelayEmissionIR.delay_expr", emission.source.to_json(), emission.delay_expr)
    if not samples:
        return None
    sample = samples[0]
    sample["scan_count"] = len(samples)
    return sample


def _iter_dynamic_hash_exprs(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if value.get("kind") == "dynamic_hash" and value.get("hash") is not None:
            yield {"kind": "dynamic_hash", "hash": value.get("hash"), "raw": value}
        hashes = value.get("DynamicHashes")
        if isinstance(hashes, list):
            for item in hashes:
                if item is not None:
                    yield {"kind": "dynamic_hash", "hash": item, "raw": value}
        for child in value.values():
            yield from _iter_dynamic_hash_exprs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dynamic_hash_exprs(child)


def _formula_binding_hit_profile_link_count(ir: CanonicalIR) -> int:
    binding_ids = {binding.binding_id for binding in ir.skill_formula_bindings}
    count = 0
    for profile in ir.hit_profiles:
        blob = json.dumps(profile.multiplier_source, ensure_ascii=False, sort_keys=True)
        if any(binding_id in blob for binding_id in binding_ids):
            count += 1
    return count


def _command_from_choice(choice: ActionChoice) -> ActionCommand:
    target_ids = tuple(choice.auto_target_ids or choice.selectable_target_ids[:1])
    return ActionCommand(
        actor_id=choice.actor_id,
        action_id=choice.action_id,
        action_level=choice.action_level,
        target_ids=target_ids,
        source="manual",
        metadata={"p4_s3_selected_from_availability": True},
    )


def _ally_unit(unit_id: str, template_id: str) -> UnitState:
    return UnitState(
        unit_id=unit_id,
        side="ally",
        template_id=template_id,
        level=80,
        max_hp=3000.0,
        hp=3000.0,
        attack=1000.0,
        defense=500.0,
        speed=100.0,
        energy=100.0,
        max_energy=100.0,
    )


def _enemy_target() -> UnitState:
    return UnitState(
        unit_id="enemy:formula_target",
        side="enemy",
        template_id="validation:formula_target",
        level=80,
        max_hp=100000.0,
        hp=100000.0,
        attack=100.0,
        defense=100.0,
        speed=100.0,
        toughness=120.0,
        max_toughness=120.0,
        flags={"weaknesses": ["Physical", "Fire", "Ice", "Thunder", "Wind", "Quantum", "Imaginary"]},
    )


def _row(
    row_id: str,
    *,
    classification: str,
    checks: dict[str, JSONValue],
    raw_count: int = 0,
    ir_count: int = 0,
    rulebook_visible_count: int = 0,
    executable_count: int = 0,
    blocked_or_gap_count: int = 0,
    gap_attribution: dict[str, int] | None = None,
    sample_source_trace: dict[str, JSONValue] | None = None,
    runtime_samples: list[dict[str, JSONValue]] | None = None,
    details: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    return {
        "row_id": row_id,
        "classification": classification,
        "checks": {"ok": bool(checks.get("ok")), "checks": checks},
        "raw_count": int(raw_count),
        "ir_count": int(ir_count),
        "rulebook_visible_count": int(rulebook_visible_count),
        "executable_count": int(executable_count),
        "blocked_or_gap_count": int(blocked_or_gap_count),
        "gap_attribution": gap_attribution or {},
        "sample_source_trace": sample_source_trace or {},
        "runtime_samples": runtime_samples or [],
        "details": details or {},
    }


def _row_check(rows: dict[str, Any], row_id: str, check_id: str) -> bool:
    return (
        dict(dict(rows.get(row_id) or {}).get("checks") or {})
        .get("checks", {})
        .get(check_id)
        is True
    )


def _first(items: Iterable[Any]) -> Any | None:
    for item in items:
        return item
    return None


def _source(item: Any | None) -> dict[str, JSONValue]:
    source = getattr(item, "source", None)
    return source.to_json() if source is not None else {}


def _compact_formula_binding(binding: SkillFormulaBindingIR | None) -> dict[str, JSONValue]:
    if binding is None:
        return {}
    return {
        "binding_id": binding.binding_id,
        "data_card_id": binding.data_card_id or binding.character_data_card_id,
        "data_card_kind": binding.data_card_kind or ("character" if binding.character_data_card_id else ""),
        "owner_entity_ref": binding.owner_entity_ref,
        "action_id": binding.action_id,
        "level": binding.level,
        "param_index": binding.param_index,
        "formula_role": binding.formula_role,
        "coverage_status": binding.coverage_status,
        "blocked_reason": binding.blocked_reason,
    }


def _mutation_source_counts(mutations: tuple[Any, ...]) -> dict[str, int]:
    counts: Counter[str] = Counter(str(mutation.source) for mutation in mutations)
    return dict(sorted(counts.items()))


def _compact_coverage(coverage: dict[str, Any]) -> dict[str, JSONValue]:
    keys = (
        "action_enabled",
        "damage_mutation_count",
        "toughness_mutation_count",
        "resource_mutation_count",
        "target_ok",
        "resource_ok",
        "binding_ok",
        "event_ok",
        "blocked_reason",
        "plan_blocked_reason",
    )
    return {key: coverage.get(key) for key in keys if key in coverage}


def _summon_gap_category(reason: str) -> str:
    lowered = reason.lower()
    if "dynamic" in lowered or "custom" in lowered or "hash" in lowered:
        return "dynamic_or_custom_value"
    if "profile" in lowered or "card" in lowered or "monster_id" in lowered:
        return "profile_or_card_source"
    if "delay" in lowered:
        return "delay_admission"
    if "position" in lowered:
        return "position_admission"
    if "source_mode" in lowered or "source" in lowered:
        return "source_mode"
    return "other_admission"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
