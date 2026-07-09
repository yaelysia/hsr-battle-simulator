from __future__ import annotations

import argparse
import json
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
from .validate_p4_s3_formula_dynamic_binding import build_p4_s3_formula_dynamic_binding_matrix


VALIDATION_VERSION = "p5_s0_formula_dynamic_source_ledger"
MATRIX_SCHEMA_VERSION = "p5_s0_formula_dynamic_source_ledger_matrix_v1"

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
    "unclassified",
}
DISALLOWED_GAP_STATES = {"implementation_missing", "lowering_gap", "validation_gap", "unclassified"}
REQUIRED_SOURCE_FAMILY_ROWS = {
    "character_skill_formula_param_sources",
    "monster_skill_formula_param_sources",
    "servant_skill_formula_param_sources",
    "summon_intent_dynamic_custom_profile_sources",
    "status_callback_dynamic_numeric_sources",
    "resource_numeric_sources",
    "damage_toughness_consumer_sources",
    "heal_shield_hp_loss_consumer_sources",
}
P4_S3_INHERITED_ROW_IDS = {
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
    matrix = build_p5_s0_formula_dynamic_source_ledger_matrix(package_root, tbgd_root, ir, rules)
    matrix_checks = validate_p5_s0_formula_dynamic_source_ledger_matrix(matrix)
    checks = {
        "matrix": matrix_checks,
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(bool(item["ok"]) for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "p5_s0_current_p4_gap_inheritance_and_source_family_ledger",
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "synthetic_positive_case_created": False,
                "full_ir_written": False,
                "full_rulebook_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
                "p5_aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "source_family_matrix": matrix["source_family_matrix"],
        "p4_gap_inheritance_matrix": matrix["p4_gap_inheritance_matrix"],
        "sample_source_traces": matrix["sample_source_traces"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p5_s0_formula_dynamic_source_ledger.json", result)
    write_json(output_dir / "p5_s0_formula_dynamic_source_family_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P5-S0 formula/dynamic/custom source ledger.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} "
        f"rows={result['summary']['source_family_row_count']} "
        f"classifications={result['summary']['classification_counts']} "
        f"p4_inherited_gaps={result['summary']['p4_inherited_gap_counts']}"
    )
    return 0 if result["ok"] else 1


def build_p5_s0_formula_dynamic_source_ledger_matrix(
    package_root: Path,
    tbgd_root: Path,
    ir: CanonicalIR,
    rules: RuleBook,
) -> dict[str, Any]:
    _ = package_root
    p4_s0_matrix = build_p4_s0_combatant_source_inventory_matrix(tbgd_root, ir, rules)
    p4_s3_matrix = build_p4_s3_formula_dynamic_binding_matrix(ir, rules, p4_s0_matrix)
    source_rows = {str(row_id): _compact_json(row) for row_id, row in dict(p4_s0_matrix.get("domain_matrix") or {}).items()}
    p4_matrix = {"formula_dynamic_binding_matrix": dict(p4_s3_matrix.get("formula_dynamic_binding_matrix") or {})}
    p4_s3_rows = dict(p4_matrix.get("formula_dynamic_binding_matrix") or {})
    p4_gap_inheritance = _p4_gap_inheritance_matrix(p4_matrix)

    rows = [
        _source_family_row(
            "character_skill_formula_param_sources",
            source_rows,
            p4_matrix,
            source_row_ids=(
                "avatar_skill_param_formula_sources",
                "avatar_skill_config_actions",
                "common_avatar_skill_config_actions",
                "config_ability_avatar_graphs",
            ),
            consumer_refs=(
                ("formula_dynamic_binding_matrix", "skill_formula_binding_to_hit_profile"),
                ("formula_dynamic_binding_matrix", "action_formula_runtime_usage"),
            ),
            p4_inherited_row_refs=(
                "p4_s3:skill_formula_binding_to_hit_profile",
                "p4_s3:action_formula_runtime_usage",
            ),
            future_owner="P5-S2 static parameter and level scaling admission",
        ),
        _source_family_row(
            "monster_skill_formula_param_sources",
            source_rows,
            p4_matrix,
            source_row_ids=(
                "monster_skill_param_formula_sources",
                "ilbattle_skill_param_formula_sources",
                "monster_skill_config_actions",
                "ilbattle_monster_skill_actions",
                "config_ability_monster_graphs",
            ),
            consumer_refs=(("monster_action_passive_matrix", "p4_s5:monster_damage_toughness_sources"),),
            p4_inherited_row_refs=("p4_s5:monster_damage_toughness_sources",),
            direct_consumer_counts=_monster_skill_consumer_counts(ir),
            future_owner="P5-S2/P5-S5 monster static formula and damage/toughness consumers",
        ),
        _source_family_row(
            "servant_skill_formula_param_sources",
            source_rows,
            p4_matrix,
            source_row_ids=(
                "avatar_servant_config_subcard_sources",
                "avatar_servant_skill_config_actions",
                "config_character_servant_sources",
                "config_ability_servant_graphs",
            ),
            consumer_refs=(("p3_backlog_recovery_matrix", "p3_regression_gate:foundation_still_green"),),
            p4_inherited_row_refs=("p4_s9:servant_damage_formula_boundary",),
            direct_consumer_counts=_servant_skill_consumer_counts(ir),
            future_owner="P5-S5/P5-S7 servant owner/stat/action numeric binding",
        ),
        _source_family_row(
            "summon_intent_dynamic_custom_profile_sources",
            source_rows,
            p4_matrix,
            source_row_ids=(
                "dynamic_monster_custom_value_fields",
                "monster_config_summon_id_list_refs",
                "p3_summoned_monster_intent_backlog",
            ),
            consumer_refs=(
                ("formula_dynamic_binding_matrix", "summon_intent_dynamic_custom_profile_gap_reclassification"),
                ("p3_backlog_recovery_matrix", "summoned_monster_intent:domain_projection"),
            ),
            p4_inherited_row_refs=(
                "p4_s3:summon_intent_dynamic_custom_profile_gap_reclassification",
                "p4_s10:summoned_monster_intent:domain_projection",
            ),
            direct_consumer_counts=_summon_intent_consumer_counts(ir, rules),
            future_owner="P5-S7 monster custom value and summoned monster profile/card binding",
        ),
        _source_family_row(
            "status_callback_dynamic_numeric_sources",
            source_rows,
            p4_matrix,
            source_row_ids=(
                "dynamic_modifier_hash_fields",
                "config_global_modifier_listener_sources",
                "monster_passive_start_enter_listener_sources",
                "monster_passive_wave_listener_sources",
                "monster_passive_death_listener_sources",
                "monster_passive_hit_attack_listener_sources",
                "monster_passive_phase_skill_trigger_sources",
                "avatar_skilltree_status_add_sources",
            ),
            consumer_refs=(
                ("monster_action_passive_matrix", "p4_s5:monster_status_resource_queue_delay_sources"),
                ("formula_dynamic_binding_matrix", "dynamic_numeric_evaluator_binding"),
            ),
            p4_inherited_row_refs=(
                "p4_s3:dynamic_numeric_evaluator_binding",
                "p4_s5:monster_status_resource_queue_delay_sources",
            ),
            direct_consumer_counts=_status_callback_consumer_counts(ir),
            future_owner="P5-S6 status numeric and callback queue ValueResolver admission",
        ),
        _source_family_row(
            "resource_numeric_sources",
            source_rows,
            p4_matrix,
            source_row_ids=(
                "avatar_skill_resource_fields",
                "monster_skill_resource_fields",
                "dynamic_avatar_skilltree_param_fields",
            ),
            consumer_refs=(
                ("action_availability_matrix", "resource_cost_and_action_query_gate"),
                ("character_action_trace_eidolon_resource_matrix", "p4_s8:trace_eidolon_resource_hook_inventory"),
            ),
            p4_inherited_row_refs=(
                "p4_s8:trace_eidolon_resource_hook_inventory",
                "p4_s11:resource_cost_and_action_query_gate",
            ),
            direct_consumer_counts=_resource_consumer_counts(ir),
            future_owner="P5-S6 skill point, energy and custom resource numeric binding",
        ),
        _source_family_row(
            "damage_toughness_consumer_sources",
            source_rows,
            p4_matrix,
            source_row_ids=(
                "avatar_skill_param_formula_sources",
                "monster_skill_param_formula_sources",
                "ilbattle_skill_param_formula_sources",
                "dynamic_config_ability_fields",
            ),
            consumer_refs=(
                ("formula_dynamic_binding_matrix", "action_formula_runtime_usage"),
                ("monster_action_passive_matrix", "p4_s5:monster_damage_toughness_sources"),
            ),
            p4_inherited_row_refs=(
                "p4_s3:action_formula_runtime_usage",
                "p4_s5:monster_damage_toughness_sources",
            ),
            direct_consumer_counts=_damage_toughness_consumer_counts(ir, rules),
            future_owner="P5-S5 damage and toughness ValueResolver consumer migration",
        ),
        _source_family_row(
            "heal_shield_hp_loss_consumer_sources",
            source_rows,
            p4_matrix,
            source_row_ids=("dynamic_config_ability_fields", "dynamic_modifier_hash_fields"),
            consumer_refs=(("formula_dynamic_binding_matrix", "s0_dynamic_formula_source_domains_inherited"),),
            p4_inherited_row_refs=("p4_s3:s0_dynamic_formula_source_domains_inherited",),
            direct_consumer_counts=_heal_shield_hp_loss_consumer_counts(ir),
            force_gap_when_consumer_present=True,
            future_owner="P5-S5 heal, shield and hp-loss formula-bound consumer admission",
        ),
    ]

    source_family_matrix = {str(row["row_id"]): row for row in rows}
    classification_counts = Counter(str(row["classification"]) for row in rows)
    gap_counts = _gap_counts(rows)
    sample_source_traces = _sample_source_trace_matrix(rows)
    p4_inherited_gap_counts = dict(p4_gap_inheritance["summary"]["gap_attribution_counts"])
    disallowed_gap_count = sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES)

    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "source_family_matrix": source_family_matrix,
        "p4_gap_inheritance_matrix": p4_gap_inheritance,
        "sample_source_traces": sample_source_traces,
        "summary": {
            "source_family_row_count": len(source_family_matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "p4_inherited_gap_counts": p4_inherited_gap_counts,
            "p4_s3_required_row_count": len(P4_S3_INHERITED_ROW_IDS),
            "p4_s3_inherited_row_count": _p4_s3_inherited_row_count(p4_gap_inheritance),
            "unclassified_count": int(classification_counts.get("unclassified", 0)),
            "disallowed_gap_count": disallowed_gap_count,
            "implementation_missing_count": int(gap_counts.get("implementation_missing", 0)),
            "lowering_gap_count": int(gap_counts.get("lowering_gap", 0)),
            "validation_gap_count": int(gap_counts.get("validation_gap", 0)),
            "sample_source_trace_count": sample_source_traces["summary"]["sample_count"],
            "p4_summary": {
                "p4_s0_classification_counts": dict(p4_s0_matrix.get("classification_counts") or {}),
                "p4_s0_gap_attribution_counts": dict(p4_s0_matrix.get("gap_attribution_counts") or {}),
                "p4_s3_classification_counts": dict(dict(p4_s3_matrix.get("summary") or {}).get("classification_counts") or {}),
                "p4_s3_gap_attribution_counts": dict(
                    dict(p4_s3_matrix.get("summary") or {}).get("gap_attribution_counts") or {}
                ),
            },
        },
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "static_check_count": 1,
            "p4_s0_s3_matrices_reused_in_memory": True,
            "subprocess_validation_count": 0,
            "full_ir_written": False,
            "full_rulebook_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_scope": "p5_s0_summary_source_family_matrix_p4_gap_inheritance_samples_only",
            "output_files": [
                "validation_summary_p5_s0_formula_dynamic_source_ledger.json",
                "p5_s0_formula_dynamic_source_family_matrix.json",
            ],
        },
    }


def validate_p5_s0_formula_dynamic_source_ledger_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("source_family_matrix") or {})
    summary = dict(matrix.get("summary") or {})
    p4_gap_inheritance = dict(matrix.get("p4_gap_inheritance_matrix") or {})
    missing_rows = sorted(REQUIRED_SOURCE_FAMILY_ROWS.difference(rows))
    invalid_classifications = sorted(
        row_id
        for row_id, row in rows.items()
        if str(dict(row).get("classification") or "unclassified") not in CLASSIFICATION_STATES
    )
    p4_s3_rows = {
        str(row.get("p4_row_id") or "")
        for row in p4_gap_inheritance.get("rows", [])
        if str(row.get("p4_stage_id") or "") == "p4_s3"
    }
    missing_p4_s3_rows = sorted(P4_S3_INHERITED_ROW_IDS.difference(p4_s3_rows))
    checks = {
        "required_source_family_rows_present": not missing_rows,
        "valid_classifications": not invalid_classifications,
        "unclassified_zero": int(summary.get("unclassified_count") or 0) == 0,
        "disallowed_gap_zero": int(summary.get("disallowed_gap_count") or 0) == 0,
        "p4_s3_rows_inherited": not missing_p4_s3_rows,
        "p4_gap_inheritance_has_allowed_gaps": int(
            dict(p4_gap_inheritance.get("summary") or {}).get("allowed_gap_count") or 0
        )
        > 0,
        "source_family_rows_have_source_or_consumer_evidence": all(
            bool(row.get("source_row_refs") or row.get("consumer_refs") or row.get("direct_consumer_counts"))
            for row in rows.values()
        ),
        "source_family_rows_have_gap_attribution_when_gap": all(
            bool(row.get("gap_attribution"))
            for row in rows.values()
            if str(row.get("classification") or "") in GAP_STATES
        ),
        "sample_source_traces_present": int(summary.get("sample_source_trace_count") or 0) > 0,
        "resource_budget_summary_only": (
            matrix.get("resource_budget", {}).get("full_ir_written") is False
            and matrix.get("resource_budget", {}).get("full_rulebook_written") is False
            and matrix.get("resource_budget", {}).get("full_transition_dump_written") is False
            and matrix.get("resource_budget", {}).get("large_artifacts_written") is False
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_source_family_rows": missing_rows,
        "invalid_classifications": invalid_classifications,
        "missing_p4_s3_inherited_rows": missing_p4_s3_rows,
    }


def _source_family_row(
    row_id: str,
    source_rows: dict[str, Any],
    p4_matrix: dict[str, Any],
    *,
    source_row_ids: tuple[str, ...],
    consumer_refs: tuple[tuple[str, str], ...],
    p4_inherited_row_refs: tuple[str, ...],
    future_owner: str,
    direct_consumer_counts: dict[str, JSONValue] | None = None,
    force_gap_when_consumer_present: bool = False,
) -> dict[str, JSONValue]:
    source_items = {row_id: dict(source_rows.get(row_id) or {}) for row_id in source_row_ids}
    consumer_items = {
        f"{matrix_key}:{consumer_row_id}": _consumer_row(p4_matrix, matrix_key, consumer_row_id)
        for matrix_key, consumer_row_id in consumer_refs
    }
    present_source_items = {key: value for key, value in source_items.items() if value}
    present_consumer_items = {key: value for key, value in consumer_items.items() if value}
    direct_counts = direct_consumer_counts or {}

    raw_count = sum(int(row.get("raw_count") or 0) for row in present_source_items.values())
    ir_count = sum(int(row.get("ir_count") or 0) for row in present_source_items.values())
    rulebook_visible_count = sum(int(row.get("rulebook_visible_count") or 0) for row in present_source_items.values())
    executable_count = sum(int(row.get("executable_count") or 0) for row in present_source_items.values())
    blocked_or_gap_count = sum(_blocked_or_gap_count(row) for row in present_source_items.values())
    consumer_count = sum(_consumer_count(row) for row in present_consumer_items.values()) + int(
        direct_counts.get("total_consumer_count") or 0
    )
    consumer_executable_count = sum(int(row.get("executable_count") or 0) for row in present_consumer_items.values()) + int(
        direct_counts.get("executable_consumer_count") or 0
    )
    gap_attribution = _merge_gap_attribution((*present_source_items.values(), *present_consumer_items.values()))
    if force_gap_when_consumer_present and consumer_count > consumer_executable_count:
        gap_attribution["admission_gap"] += consumer_count - consumer_executable_count
    if not gap_attribution and blocked_or_gap_count:
        gap_attribution["admission_gap"] += blocked_or_gap_count
    if not gap_attribution and (raw_count or ir_count) and consumer_count == 0:
        gap_attribution["admission_gap"] += 1

    classification = _classify_family(
        source_rows=tuple(present_source_items.values()),
        raw_count=raw_count,
        ir_count=ir_count,
        executable_count=executable_count + consumer_executable_count,
        consumer_count=consumer_count,
        gap_attribution=gap_attribution,
    )
    checks = {
        "source_rows_present": bool(present_source_items),
        "all_declared_source_rows_present": len(present_source_items) == len(source_row_ids),
        "source_or_consumer_count_present": raw_count > 0 or ir_count > 0 or consumer_count > 0,
        "sample_source_trace_present_when_source_present": not present_source_items
        or bool(_first_source_trace(present_source_items.values())),
        "no_synthetic_positive_case": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "row_id": row_id,
        "classification": classification,
        "checks": {"ok": checks["ok"], "checks": checks},
        "raw_count": raw_count,
        "ir_count": ir_count,
        "rulebook_visible_count": rulebook_visible_count,
        "consumer_count": consumer_count,
        "executable_count": executable_count + consumer_executable_count,
        "blocked_or_gap_count": blocked_or_gap_count,
        "gap_attribution": dict(sorted((key, int(value)) for key, value in gap_attribution.items() if int(value))),
        "source_row_refs": sorted(present_source_items),
        "missing_source_row_refs": sorted(set(source_row_ids).difference(present_source_items)),
        "consumer_refs": sorted(present_consumer_items),
        "missing_consumer_refs": sorted(
            set(f"{key}:{value}" for key, value in consumer_refs).difference(present_consumer_items)
        ),
        "p4_inherited_row_refs": list(p4_inherited_row_refs),
        "sample_source_trace": _first_source_trace(present_source_items.values())
        or _first_source_trace(present_consumer_items.values()),
        "direct_consumer_counts": direct_counts,
        "future_owner": future_owner,
        "details": {
            "source_classification_counts": dict(
                sorted(Counter(str(row.get("classification") or "") for row in present_source_items.values()).items())
            ),
            "consumer_classification_counts": dict(
                sorted(Counter(str(row.get("classification") or "") for row in present_consumer_items.values()).items())
            ),
            "declared_source_row_refs": list(source_row_ids),
            "declared_consumer_refs": [f"{key}:{value}" for key, value in consumer_refs],
        },
    }


def _p4_gap_inheritance_matrix(p4_matrix: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, JSONValue]] = []
    for stage_id, matrix_key in (("p4_s3", "formula_dynamic_binding_matrix"),):
        for row_id, row in dict(p4_matrix.get(matrix_key) or {}).items():
            row_dict = dict(row)
            gap_attribution = {
                str(key): int(value or 0)
                for key, value in dict(row_dict.get("gap_attribution") or {}).items()
                if str(key) in GAP_STATES and int(value or 0) > 0
            }
            classification = str(row_dict.get("classification") or "")
            if classification in GAP_STATES and not gap_attribution:
                gap_attribution[classification] = _blocked_or_gap_count(row_dict) or 1
            if stage_id == "p4_s3" or _is_p5_relevant_gap_row(str(row_id), row_dict, gap_attribution):
                rows.append(
                    {
                        "p4_stage_id": stage_id,
                        "p4_row_id": str(row_id),
                        "classification": classification,
                        "gap_attribution": gap_attribution,
                        "gap_count": sum(gap_attribution.values()),
                        "raw_count": int(row_dict.get("raw_count") or 0),
                        "ir_count": int(row_dict.get("ir_count") or 0),
                        "rulebook_visible_count": int(row_dict.get("rulebook_visible_count") or 0),
                        "executable_count": int(row_dict.get("executable_count") or 0),
                        "blocked_or_gap_count": _blocked_or_gap_count(row_dict),
                        "sample_source_trace": _compact_json(row_dict.get("sample_source_trace") or {}),
                        "details": _compact_json(row_dict.get("details") or {}),
                    }
                )
    gap_counts = _gap_counts(rows)
    allowed_gap_count = int(gap_counts.get("admission_gap", 0)) + int(gap_counts.get("source_gap_blocked", 0))
    disallowed_gap_count = sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES)
    return {
        "schema_version": "p5_s0_p4_gap_inheritance_matrix_v1",
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "allowed_gap_count": allowed_gap_count,
            "disallowed_gap_count": disallowed_gap_count,
            "p4_s3_row_count": sum(1 for row in rows if row["p4_stage_id"] == "p4_s3"),
            "p4_s3_all_required_rows_inherited": _p4_s3_inherited_row_count({"rows": rows})
            == len(P4_S3_INHERITED_ROW_IDS),
        },
    }


def _monster_skill_consumer_counts(ir: CanonicalIR) -> dict[str, JSONValue]:
    action_ids = {
        definition.action_id
        for definition in ir.action_definitions
        if str(definition.action_id).startswith(("monster_skill:", "ilbattle_monster_skill:"))
    }
    damage = tuple(item for item in ir.damage_emissions if item.action_id in action_ids)
    toughness = tuple(item for item in ir.toughness_emissions if item.action_id in action_ids)
    total = len(damage) + len(toughness)
    executable = sum(1 for item in (*damage, *toughness) if getattr(item, "coverage_status", "") == "executable")
    return {
        "total_consumer_count": total,
        "executable_consumer_count": executable,
        "monster_action_definition_count": len(action_ids),
        "monster_damage_emission_count": len(damage),
        "monster_toughness_emission_count": len(toughness),
    }


def _servant_skill_consumer_counts(ir: CanonicalIR) -> dict[str, JSONValue]:
    servant_actions = [
        definition
        for definition in ir.action_definitions
        if _source_contains(definition, ("AvatarServantSkillConfig", "Config/ConfigAbility/Servant"))
    ]
    executable = sum(1 for item in servant_actions if getattr(item, "coverage_status", "") == "executable")
    return {
        "total_consumer_count": len(servant_actions),
        "executable_consumer_count": executable,
        "servant_action_definition_count": len(servant_actions),
        "servant_definition_count": len(ir.servant_definitions),
    }


def _summon_intent_consumer_counts(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    intents = tuple(ir.summon_monster_intents)
    executable = sum(1 for intent in intents if getattr(intent, "coverage_status", "") == "executable")
    visible = sum(1 for intent in intents if rules.summon_monster_intent(intent.summon_intent_id) is intent)
    return {
        "total_consumer_count": len(intents),
        "executable_consumer_count": executable,
        "rulebook_visible_consumer_count": visible,
        "summon_monster_intent_count": len(intents),
    }


def _status_callback_consumer_counts(ir: CanonicalIR) -> dict[str, JSONValue]:
    items = (
        *ir.status_callbacks,
        *ir.status_callback_tasks,
        *ir.status_damage_emissions,
        *ir.action_delay_emissions,
        *ir.queue_intents,
    )
    executable = sum(1 for item in items if getattr(item, "coverage_status", "") == "executable")
    return {
        "total_consumer_count": len(items),
        "executable_consumer_count": executable,
        "status_callback_count": len(ir.status_callbacks),
        "status_callback_task_count": len(ir.status_callback_tasks),
        "status_damage_emission_count": len(ir.status_damage_emissions),
        "action_delay_emission_count": len(ir.action_delay_emissions),
        "queue_intent_count": len(ir.queue_intents),
    }


def _resource_consumer_counts(ir: CanonicalIR) -> dict[str, JSONValue]:
    resource_rules = tuple(getattr(ir, "resource_rules", ()))
    executable = sum(1 for item in resource_rules if getattr(item, "coverage_status", "") == "executable")
    resource_tasks = [
        task
        for task in (*ir.ability_tasks, *ir.status_callback_tasks)
        if any(token in str(task.opcode).lower() for token in ("resource", "energy", "skillpoint", "skill_point", "sp"))
    ]
    return {
        "total_consumer_count": len(resource_rules) + len(resource_tasks),
        "executable_consumer_count": executable,
        "resource_rule_count": len(resource_rules),
        "resource_opcode_task_count": len(resource_tasks),
    }


def _damage_toughness_consumer_counts(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    damage = tuple(ir.damage_emissions)
    toughness = tuple(ir.toughness_emissions)
    status_damage = tuple(ir.status_damage_emissions)
    break_damage = tuple(ir.break_damage_emissions)
    super_break = tuple(ir.super_break_emissions)
    total = len(damage) + len(toughness) + len(status_damage) + len(break_damage) + len(super_break)
    executable = sum(
        1
        for item in (*damage, *toughness, *status_damage, *break_damage, *super_break)
        if getattr(item, "coverage_status", "") == "executable"
    )
    visible = sum(1 for item in damage if rules.damage_emission(item.damage_emission_id) is item)
    visible += sum(1 for item in toughness if rules.toughness_emission(item.toughness_emission_id) is item)
    visible += sum(1 for item in status_damage if rules.status_damage_emission(item.status_damage_emission_id) is item)
    return {
        "total_consumer_count": total,
        "executable_consumer_count": executable,
        "rulebook_visible_consumer_count": visible,
        "damage_emission_count": len(damage),
        "toughness_emission_count": len(toughness),
        "status_damage_emission_count": len(status_damage),
        "break_damage_emission_count": len(break_damage),
        "super_break_emission_count": len(super_break),
    }


def _source_contains(item: Any, tokens: tuple[str, ...]) -> bool:
    source = getattr(item, "source", None)
    if source is None:
        return False
    blob = json.dumps(source.to_json(), ensure_ascii=False, sort_keys=True)
    return any(token in blob for token in tokens)


def _heal_shield_hp_loss_consumer_counts(ir: CanonicalIR) -> dict[str, JSONValue]:
    opcodes = Counter(str(task.opcode) for task in ir.ability_tasks)
    opcodes.update(str(task.opcode) for task in ir.status_callback_tasks)
    opcodes.update(str(effect.opcode) for effect in ir.effects)
    heal = _opcode_token_count(opcodes, ("heal", "recoverhp", "modifyhp"))
    shield = _opcode_token_count(opcodes, ("shield",))
    hp_loss = _opcode_token_count(opcodes, ("hploss", "hp_loss", "losehp", "consumehp", "deducthp"))
    total = heal + shield + hp_loss
    return {
        "total_consumer_count": total,
        "executable_consumer_count": 0,
        "heal_opcode_count": heal,
        "shield_opcode_count": shield,
        "hp_loss_opcode_count": hp_loss,
        "sample_opcode_counts": dict(sorted(opcodes.items())[:18]),
    }


def _opcode_token_count(opcodes: Counter[str], tokens: tuple[str, ...]) -> int:
    total = 0
    for opcode, count in opcodes.items():
        lowered = opcode.lower()
        if any(token in lowered for token in tokens):
            total += int(count)
    return total


def _consumer_row(p4_matrix: dict[str, Any], matrix_key: str, row_id: str) -> dict[str, Any]:
    rows = dict(p4_matrix.get(matrix_key) or {})
    if row_id in rows:
        return dict(rows[row_id])
    return {}


def _consumer_count(row: dict[str, Any]) -> int:
    return int(
        row.get("consumer_count")
        or row.get("ir_count")
        or row.get("raw_count")
        or row.get("row_count")
        or row.get("executable_count")
        or 0
    )


def _blocked_or_gap_count(row: dict[str, Any]) -> int:
    return int(
        row.get("blocked_or_gap_count")
        or row.get("blocked_count")
        or row.get("gap_count")
        or row.get("inherited_gap_count")
        or 0
    )


def _merge_gap_attribution(rows: Iterable[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter({key: 0 for key in GAP_STATES})
    for row in rows:
        attribution = row.get("gap_attribution") if isinstance(row.get("gap_attribution"), dict) else {}
        for key, value in attribution.items():
            if str(key) in GAP_STATES:
                counts[str(key)] += int(value or 0)
        classification = str(row.get("classification") or "")
        if classification in GAP_STATES and not attribution:
            counts[classification] += _blocked_or_gap_count(row) or 1
    return counts


def _gap_counts(rows: Iterable[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter({key: 0 for key in GAP_STATES})
    for row in rows:
        attribution = row.get("gap_attribution") if isinstance(row.get("gap_attribution"), dict) else {}
        for key, value in attribution.items():
            if str(key) in GAP_STATES:
                counts[str(key)] += int(value or 0)
    return counts


def _classify_family(
    *,
    source_rows: tuple[dict[str, Any], ...],
    raw_count: int,
    ir_count: int,
    executable_count: int,
    consumer_count: int,
    gap_attribution: Counter[str],
) -> str:
    for state in ("implementation_missing", "lowering_gap", "validation_gap", "unclassified"):
        if int(gap_attribution.get(state, 0)) > 0:
            return state
    if int(gap_attribution.get("admission_gap", 0)) > 0:
        return "admission_gap"
    if int(gap_attribution.get("source_gap_blocked", 0)) > 0:
        return "source_gap_blocked"
    if source_rows and all(str(row.get("classification") or "") == "out_of_scope" for row in source_rows):
        return "out_of_scope"
    if raw_count == 0 and ir_count == 0 and consumer_count == 0:
        return "source_gap_blocked"
    if executable_count > 0:
        return "executable"
    return "boundary_only"


def _is_p5_relevant_gap_row(row_id: str, row: dict[str, Any], gap_attribution: dict[str, int]) -> bool:
    blob = json.dumps({"row_id": row_id, "row": row}, ensure_ascii=False, sort_keys=True).lower()
    tokens = (
        "formula",
        "dynamic",
        "custom",
        "param",
        "resource",
        "status",
        "callback",
        "queue",
        "summon",
        "servant",
        "damage",
        "toughness",
        "heal",
        "shield",
        "hp",
    )
    return bool(gap_attribution) and any(token in blob for token in tokens)


def _p4_s3_inherited_row_count(p4_gap_inheritance: dict[str, Any]) -> int:
    return len(
        {
            str(row.get("p4_row_id") or "")
            for row in p4_gap_inheritance.get("rows", [])
            if str(row.get("p4_stage_id") or "") == "p4_s3"
        }
        & P4_S3_INHERITED_ROW_IDS
    )


def _sample_source_trace_matrix(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    samples = [
        {
            "row_id": str(row.get("row_id") or ""),
            "classification": str(row.get("classification") or ""),
            "sample_source_trace": _compact_json(row.get("sample_source_trace") or {}),
        }
        for row in rows
        if row.get("sample_source_trace")
    ]
    return {
        "schema_version": "p5_s0_sample_source_trace_matrix_v1",
        "rows": samples[:24],
        "summary": {"sample_count": len(samples[:24])},
    }


def _first_source_trace(rows: Iterable[dict[str, Any]]) -> dict[str, JSONValue]:
    for row in rows:
        trace = row.get("sample_source_trace")
        if isinstance(trace, dict) and trace:
            return _compact_json(trace)
    return {}


def _compact_json(value: Any, *, depth: int = 0) -> JSONValue:
    if depth > 4:
        return "..."
    if isinstance(value, dict):
        result: dict[str, JSONValue] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 18:
                result["..."] = "truncated"
                break
            result[str(key)] = _compact_json(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_compact_json(item, depth=depth + 1) for item in list(value)[:18]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
