from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from .. import BASELINE_VERSION
from ..core.model import JSONValue
from ..rules.rulebook import RuleBook
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p1_4_status_system import _refresh_case
from .validate_p2_s3_status_application_semantics import _replace_case
from .validate_p2_s8_status_damage import (
    _break_dot_case,
    _dead_target_skip_case,
    _missing_status_negative_case,
    _multi_dot_case,
    _ordinary_dot_lifecycle_case,
    _true_damage_case,
)
from .validate_p2_s9_status_removal_dispel import _remove_modifier_case
from .validate_p3_s10_summon_status_resource_damage import (
    _kill_attribution_source_frame_case,
    _removed_summon_damage_negative_case,
    _servant_status_holder_case,
)
from .validate_p1_3_summon_assistant_servant import _select_executable_servant_definition
from .validate_p3_s8_summon_target_relations import _combined_summon_state, _target_relation_negative_cases
from .validate_v0_231 import _execute_toughness_case, _select_toughness_case
from .validate_v0_235 import (
    _execute_action_delay_case,
    _execute_break_setup,
    _execute_super_break_case,
    _negative_cases as _break_family_negative_cases,
    _select_break_family_case,
)
from .validate_v0_248 import _manual_ultimate_execution_case
from .validate_v0_249 import _positive_effect_case, _select_hp_loss_floor_effect, _select_modify_sp_effect
from .validate_v0_255 import _automatic_kill_to_extra_turn_case


VALIDATION_VERSION = "p4_s9_data_card_mutation_source_linkage"
MATRIX_SCHEMA_VERSION = "p4_s9_data_card_mutation_source_linkage_matrix_v1"

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
    "data_card_direct_damage_resource_linkage",
    "data_card_break_linkage",
    "data_card_super_break_linkage",
    "data_card_hp_loss_linkage",
    "data_card_status_apply_linkage",
    "status_refresh_replace_linkage",
    "status_remove_linkage",
    "status_damage_dot_break_true_linkage",
    "listener_queue_action_delay_resource_linkage",
    "kill_attribution_source_frame_linkage",
    "removed_defeated_untargetable_negative",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p4_s9_data_card_mutation_source_linkage_matrix(ir, rules)
    matrix_checks = validate_p4_s9_data_card_mutation_source_linkage_matrix(matrix)
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
                "mode": "p4_s9_data_card_mutation_source_structural_predicates",
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "data_card_mutation_source_matrix": matrix["data_card_mutation_source_matrix"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p4_s9_data_card_mutation_source_linkage.json", result)
    write_json(output_dir / "p4_s9_data_card_mutation_source_linkage_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P4-S9 data-card mutation/source linkage.")
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


def build_p4_s9_data_card_mutation_source_linkage_matrix(ir, rules: RuleBook) -> dict[str, Any]:
    toughness_case = _select_toughness_case(ir, rules)
    direct_case = _execute_toughness_case(rules, toughness_case, deplete=False)
    break_case = _execute_toughness_case(rules, toughness_case, deplete=True)

    break_family_case = _select_break_family_case(ir, rules)
    break_setup = _execute_break_setup(rules, break_family_case)
    action_delay_case = _execute_action_delay_case(rules, break_setup["initial_state"])
    super_break_case = _execute_super_break_case(rules, break_setup["after_state"])
    break_negative_case = _break_family_negative_cases(rules, break_setup["after_state"], break_family_case)

    servant_definition = _select_executable_servant_definition(rules)
    servant_status_case = _servant_status_holder_case(rules, servant_definition)
    servant_kill_case = _kill_attribution_source_frame_case(rules, servant_definition)
    removed_summon_case = _removed_summon_damage_negative_case(rules, servant_definition)
    summon_negative_case = _target_relation_negative_cases(rules, _combined_summon_state(rules))

    refresh_case = _refresh_case(rules)
    replace_case = _replace_case(rules)
    remove_case = _remove_modifier_case(ir, rules, "RemoveModifier")
    remove_self_case = _remove_modifier_case(ir, rules, "RemoveSelfModifier")

    ordinary_dot_case = _ordinary_dot_lifecycle_case(ir, rules)
    break_dot_case = _break_dot_case(ir, rules)
    true_damage_case = _true_damage_case(ir, rules)
    multi_dot_case = _multi_dot_case(ir, rules)
    dead_target_case = _dead_target_skip_case(ir, rules)
    missing_status_case = _missing_status_negative_case(ir, rules)

    manual_ultimate = _manual_ultimate_execution_case(ir, rules)
    resource_case = _positive_effect_case(
        rules,
        replace(manual_ultimate["initial_state"], skill_points=1, max_skill_points=5),
        manual_ultimate["command"],
        _select_modify_sp_effect(ir),
        "p4_s9_modify_sp_new",
        dynamic_value=0.50,
    )
    hp_loss_case = _positive_effect_case(
        rules,
        replace(manual_ultimate["initial_state"], skill_points=1, max_skill_points=5),
        manual_ultimate["command"],
        _select_hp_loss_floor_effect(ir),
        "p4_s9_hp_loss_floor",
        dynamic_value=0.333,
        actor_overrides={"max_hp": 1001.0, "hp": 777.0},
    )

    automatic_extra_turn_case = _automatic_kill_to_extra_turn_case(ir, rules)

    rows = [
        _direct_damage_resource_row(toughness_case, direct_case, resource_case),
        _break_row(toughness_case, break_case),
        _super_break_row(super_break_case, break_negative_case),
        _hp_loss_row(hp_loss_case),
        _status_apply_row(servant_status_case),
        _status_refresh_replace_row(refresh_case, replace_case),
        _status_remove_row(remove_case, remove_self_case),
        _status_damage_row(ordinary_dot_case, break_dot_case, true_damage_case, multi_dot_case, dead_target_case, missing_status_case),
        _listener_queue_action_delay_resource_row(action_delay_case, automatic_extra_turn_case, resource_case),
        _kill_attribution_row(automatic_extra_turn_case, servant_kill_case),
        _negative_lifecycle_targetability_row(removed_summon_case, dead_target_case, summon_negative_case),
    ]
    matrix = {str(row["row_id"]): row for row in rows}
    classification_counts = Counter(str(row.get("classification") or "unclassified") for row in rows)
    gap_counts: Counter[str] = Counter()
    for row in rows:
        for key, value in dict(row.get("gap_attribution") or {}).items():
            gap_counts[str(key)] += int(value or 0)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "data_card_mutation_source_matrix": matrix,
        "summary": {
            "row_count": len(matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "unclassified_count": int(classification_counts.get("unclassified", 0)),
            "mutation_source_counts": _merge_counter_rows(row.get("mutation_source_counts", {}) for row in rows),
            "record_type_counts": _merge_counter_rows(row.get("record_type_counts", {}) for row in rows),
        },
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "full_ir_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_files": [
                "validation_summary_p4_s9_data_card_mutation_source_linkage.json",
                "p4_s9_data_card_mutation_source_linkage_matrix.json",
            ],
        },
    }


def validate_p4_s9_data_card_mutation_source_linkage_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("data_card_mutation_source_matrix") or {})
    missing = sorted(REQUIRED_ROWS.difference(rows))
    invalid_classifications = sorted(
        row_id
        for row_id, row in rows.items()
        if str(row.get("classification") or "unclassified") not in CLASSIFICATION_STATES
    )
    gap_rows = [row for row in rows.values() if str(row.get("classification") or "") in GAP_STATES]
    executable_rows = [row for row in rows.values() if row.get("classification") == "executable"]
    checks = {
        "required_rows_present": not missing,
        "valid_classifications": not invalid_classifications,
        "unclassified_count_zero": int(matrix.get("summary", {}).get("unclassified_count") or 0) == 0,
        "row_checks_ok": all(dict(row.get("checks") or {}).get("ok") is True for row in rows.values()),
        "gap_rows_have_attribution": all(bool(row.get("gap_attribution")) for row in gap_rows),
        "executable_rows_have_audit_or_declared_boundary": all(
            _row_inner_check(row, "source_audit_or_declared_boundary") is True for row in executable_rows
        ),
        "direct_damage_resource_executable": rows.get("data_card_direct_damage_resource_linkage", {}).get("classification")
        == "executable",
        "status_damage_executable": rows.get("status_damage_dot_break_true_linkage", {}).get("classification") == "executable",
        "negative_boundary_no_mutation": _row_check(rows, "removed_defeated_untargetable_negative", "negative_cases_no_mutation"),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_rows": missing,
        "invalid_classifications": invalid_classifications,
    }


def _direct_damage_resource_row(selection: dict[str, Any], case: dict[str, Any], resource_case: dict[str, Any]) -> dict[str, JSONValue]:
    transition = dict(case["transition"])
    resource_transition = resource_case["transition"].to_json()
    mutation_counts = _merge_counter_rows((_mutation_source_counts(transition), _mutation_source_counts(resource_transition)))
    record_counts = _merge_counter_rows((_record_type_counts(transition), _record_type_counts(resource_transition)))
    damage_families = _damage_family_counts(transition)
    checks = {
        "case_ok": _nested_ok(case),
        "source_audit": bool(case["checks"].get("source_audit")),
        "replay": bool(case["checks"].get("replay")),
        "direct_damage_mutation_present": damage_families.get("direct", 0) > 0,
        "resource_effect_case_ok": bool(resource_case["checks"].get("ok")),
        "resource_source_audit": bool(resource_case["checks"].get("source_audit")),
        "resource_replay": bool(resource_case["checks"].get("replay")),
        "resource_mutation_present": bool(resource_case["checks"].get("mutation_present")),
        "damage_settlement_record_present": any("damage" in key for key in record_counts),
        "resource_settlement_record_present": any("resource" in key for key in record_counts),
        "source_audit_or_declared_boundary": bool(case["checks"].get("source_audit"))
        and bool(resource_case["checks"].get("source_audit")),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    action = selection["action"]
    return _row(
        "data_card_direct_damage_resource_linkage",
        "executable",
        checks,
        raw_count=1,
        executable_count=1,
        mutation_source_counts=mutation_counts,
        record_type_counts=record_counts,
        details={
            "action_id": action.action_id,
            "action_level": action.level,
            "damage_family_counts": damage_families,
            "resource_effect_id": resource_case["effect"].effect_id,
            "resource_opcode": resource_case["effect"].opcode,
            "selected_source_path": action.source.source_path,
        },
    )


def _break_row(selection: dict[str, Any], case: dict[str, Any]) -> dict[str, JSONValue]:
    transition = dict(case["transition"])
    mutation_counts = _mutation_source_counts(transition)
    record_counts = _record_type_counts(transition)
    checks = {
        "case_ok": _nested_ok(case),
        "source_audit": bool(case["checks"].get("source_audit")),
        "replay": bool(case["checks"].get("replay")),
        "toughness_mutation_present": mutation_counts.get("toughness_system", 0) > 0,
        "break_mutation_present": mutation_counts.get("break_system", 0) > 0,
        "break_settlement_record_present": any(key in {"break_lifecycle", "break_event"} for key in record_counts),
        "source_audit_or_declared_boundary": bool(case["checks"].get("source_audit")),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    emission = selection["emission"]
    return _row(
        "data_card_break_linkage",
        "executable",
        checks,
        raw_count=1,
        executable_count=1,
        mutation_source_counts=mutation_counts,
        record_type_counts=record_counts,
        details={
            "toughness_emission_id": emission.toughness_emission_id,
            "element_type": emission.element_type,
            "selected_source_path": emission.source.source_path,
        },
    )


def _super_break_row(case: dict[str, Any], negative_case: dict[str, Any]) -> dict[str, JSONValue]:
    transition = dict(case["transition"])
    mutation_counts = _mutation_source_counts(transition)
    record_counts = _record_type_counts(transition)
    checks = {
        "case_ok": _nested_ok(case),
        "source_audit": bool(case["checks"].get("source_audit")),
        "replay": bool(case["checks"].get("replay")),
        "super_break_mutation_present": bool(case["checks"].get("super_break_mutation_present")),
        "missing_total_stance_damage_no_mutation": bool(
            negative_case["checks"]["checks"].get("super_break_missing_no_mutation")
            if isinstance(negative_case.get("checks"), dict) and isinstance(negative_case["checks"].get("checks"), dict)
            else negative_case["checks"].get("super_break_missing_no_mutation")
        ),
        "source_audit_or_declared_boundary": bool(case["checks"].get("source_audit")),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    selected = case.get("selected_super_break", {})
    return _row(
        "data_card_super_break_linkage",
        "executable",
        checks,
        raw_count=1,
        executable_count=1,
        mutation_source_counts=mutation_counts,
        record_type_counts=record_counts,
        details={
            "super_break_emission_id": selected.get("super_break_emission_id", ""),
            "source_path": dict(selected.get("source") or {}).get("source_path", ""),
        },
    )


def _hp_loss_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    transition = case["transition"].to_json()
    mutation_counts = _mutation_source_counts(transition)
    record_counts = _record_type_counts(transition)
    damage_families = _damage_family_counts(transition)
    checks = {
        "case_ok": bool(case["checks"].get("ok")),
        "source_audit": bool(case["checks"].get("source_audit")),
        "replay": bool(case["checks"].get("replay")),
        "hp_loss_mutation_present": damage_families.get("hp_loss", 0) > 0,
        "hp_loss_record_present": record_counts.get("hp_loss", 0) > 0,
        "no_direct_multiplier_ledger": _hp_loss_has_no_normal_multiplier_terms(transition),
        "source_audit_or_declared_boundary": bool(case["checks"].get("source_audit")),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    effect = case["effect"]
    return _row(
        "data_card_hp_loss_linkage",
        "executable",
        checks,
        raw_count=1,
        executable_count=1,
        mutation_source_counts=mutation_counts,
        record_type_counts=record_counts,
        details={"effect_id": effect.effect_id, "opcode": effect.opcode, "source_path": effect.source.source_path},
    )


def _status_apply_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    mutation_counts = dict(case.get("mutation_source_counts") or {})
    checks = {
        "case_ok": _nested_ok(case),
        "status_mutation_present": mutation_counts.get("status_system", 0) > 0,
        "status_holder_is_servant": bool(case["checks"]["checks"].get("status_holder_is_servant")),
        "replay": bool(case.get("replay", {}).get("ok")),
        "source_audit": bool(case.get("source_audit", {}).get("ok")),
        "source_audit_or_declared_boundary": bool(case.get("source_audit", {}).get("ok")),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "data_card_status_apply_linkage",
        "executable",
        checks,
        raw_count=1,
        executable_count=1,
        mutation_source_counts=mutation_counts,
        record_type_counts=Counter(str(item) for item in case.get("record_types", ())),
        details={
            "servant_definition_id": case.get("servant_definition_id", ""),
            "action_id": case.get("action_id", ""),
            "servant_unit_id": case.get("servant_unit_id", ""),
        },
    )


def _status_refresh_replace_row(refresh_case: dict[str, Any], replace_case: dict[str, Any]) -> dict[str, JSONValue]:
    classification = "source_gap_blocked" if refresh_case.get("coverage_gap") else "executable"
    checks = {
        "refresh_case_ok": _nested_ok(refresh_case),
        "replace_case_ok": _nested_ok(replace_case),
        "refresh_has_source_audit_or_gap": bool(refresh_case.get("coverage_gap")) or bool(refresh_case.get("source_audit", {}).get("ok")),
        "replace_source_audit": bool(replace_case.get("source_audit", {}).get("ok")),
        "replace_replay": bool(replace_case.get("replay", {}).get("ok")),
        "source_audit_or_declared_boundary": bool(refresh_case.get("coverage_gap"))
        or bool(refresh_case.get("source_audit", {}).get("ok"))
        and bool(replace_case.get("source_audit", {}).get("ok")),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "status_refresh_replace_linkage",
        classification,
        checks,
        raw_count=2,
        executable_count=1 if classification != "executable" else 2,
        gap_attribution={"source_gap_blocked": 1} if classification == "source_gap_blocked" else {},
        details={
            "refresh_effect_id": dict(refresh_case.get("effect") or {}).get("effect_id", ""),
            "replace_effect_id": dict(replace_case.get("effect") or {}).get("effect_id", ""),
            "refresh_gap": str(refresh_case.get("coverage_gap") or ""),
        },
    )


def _status_remove_row(remove_case: dict[str, Any], remove_self_case: dict[str, Any]) -> dict[str, JSONValue]:
    checks = {
        "remove_modifier_ok": _nested_ok(remove_case),
        "remove_self_modifier_ok": _nested_ok(remove_self_case),
        "remove_modifier_source_audit": bool(remove_case["checks"]["checks"].get("source_audit")),
        "remove_self_source_audit": bool(remove_self_case["checks"]["checks"].get("source_audit")),
        "remove_modifier_replay": bool(remove_case["checks"]["checks"].get("replay")),
        "remove_self_replay": bool(remove_self_case["checks"]["checks"].get("replay")),
        "source_audit_or_declared_boundary": bool(remove_case["checks"]["checks"].get("source_audit"))
        and bool(remove_self_case["checks"]["checks"].get("source_audit")),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "status_remove_linkage",
        "executable",
        checks,
        raw_count=2,
        executable_count=2,
        details={
            "remove_modifier": remove_case.get("summary", {}),
            "remove_self_modifier": remove_self_case.get("summary", {}),
        },
    )


def _status_damage_row(
    ordinary_dot_case: dict[str, Any],
    break_dot_case: dict[str, Any],
    true_damage_case: dict[str, Any],
    multi_dot_case: dict[str, Any],
    dead_target_case: dict[str, Any],
    missing_status_case: dict[str, Any],
) -> dict[str, JSONValue]:
    cases = {
        "ordinary_dot": ordinary_dot_case,
        "break_dot": break_dot_case,
        "true_damage": true_damage_case,
        "multi_dot": multi_dot_case,
        "dead_target_skip": dead_target_case,
        "missing_status": missing_status_case,
    }
    classification = "executable"
    gaps = {}
    if ordinary_dot_case.get("summary", {}).get("classification") == "source_gap_blocked":
        classification = "source_gap_blocked"
        gaps = {"source_gap_blocked": 1}
    checks = {
        f"{name}_ok": _nested_ok(case)
        for name, case in cases.items()
    }
    checks.update(
        {
            "ordinary_dot_source_frame_present": bool(
                ordinary_dot_case.get("checks", {}).get("checks", {}).get("status_source_metadata_present")
            )
            or classification == "source_gap_blocked",
            "true_damage_checked": _nested_ok(true_damage_case),
        "dead_target_skip_no_mutation": bool(dead_target_case.get("checks", {}).get("checks", {}).get("no_damage_mutation")),
        "source_audit_or_declared_boundary": all(_nested_ok(case) for case in cases.values()),
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "status_damage_dot_break_true_linkage",
        classification,
        checks,
        raw_count=len(cases),
        executable_count=len(cases) - int(bool(gaps)),
        gap_attribution=gaps,
        details={name: case.get("summary", {}) for name, case in cases.items()},
    )


def _listener_queue_action_delay_resource_row(
    action_delay_case: dict[str, Any],
    automatic_extra_turn_case: dict[str, Any],
    resource_case: dict[str, Any],
) -> dict[str, JSONValue]:
    auto_status = str(automatic_extra_turn_case.get("status") or "executable")
    classification = "source_gap_blocked" if auto_status == "source_gap_blocked" else "executable"
    checks = {
        "action_delay_ok": _nested_ok(action_delay_case),
        "action_delay_source_audit": bool(action_delay_case.get("source_audit", {}).get("ok")),
        "automatic_extra_turn_ok": _nested_ok(automatic_extra_turn_case),
        "automatic_extra_turn_executable_or_gap": classification == "executable"
        or bool(automatic_extra_turn_case.get("checks", {}).get("automatic_extra_turn_source_gap_blocked")),
        "resource_effect_case_ok": bool(resource_case["checks"].get("ok")),
        "resource_effect_source_audit": bool(resource_case["checks"].get("source_audit")),
        "resource_effect_mutation_present": bool(resource_case["checks"].get("mutation_present")),
        "source_audit_or_declared_boundary": bool(action_delay_case.get("source_audit", {}).get("ok"))
        and bool(resource_case["checks"].get("source_audit"))
        and (
            classification != "executable"
            or all(bool(item.get("ok")) for item in automatic_extra_turn_case.get("source_audits", {}).values() if isinstance(item, dict))
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    gap_attribution = {"source_gap_blocked": 1} if classification == "source_gap_blocked" else {}
    return _row(
        "listener_queue_action_delay_resource_linkage",
        classification,
        checks,
        raw_count=3,
        executable_count=2 if classification != "executable" else 3,
        gap_attribution=gap_attribution,
        mutation_source_counts=_mutation_source_counts(action_delay_case.get("transition", {})),
        record_type_counts=_record_type_counts(action_delay_case.get("transition", {})),
        details={
            "action_delay_selected": action_delay_case.get("selected_delay", {}),
            "automatic_extra_turn_status": auto_status,
            "automatic_extra_turn_blocking_dependency": automatic_extra_turn_case.get("blocking_dependency", ""),
            "resource_effect_id": resource_case["effect"].effect_id,
        },
    )


def _kill_attribution_row(automatic_extra_turn_case: dict[str, Any], servant_kill_case: dict[str, Any]) -> dict[str, JSONValue]:
    auto_executable = str(automatic_extra_turn_case.get("status") or "executable") != "source_gap_blocked"
    defeat_events = automatic_extra_turn_case.get("defeat_events") if auto_executable else ()
    defeat_payload = {}
    if isinstance(defeat_events, list) and defeat_events:
        event = defeat_events[0]
        defeat_payload = event.get("payload") if isinstance(event, dict) and isinstance(event.get("payload"), dict) else {}
    servant_checks = servant_kill_case.get("checks", {}).get("checks", {})
    checks = {
        "automatic_kill_ok_or_gap": _nested_ok(automatic_extra_turn_case),
        "automatic_kill_has_source_audit_when_executable": not auto_executable
        or bool(automatic_extra_turn_case.get("source_audits", {}).get("damage", {}).get("ok")),
        "automatic_kill_credit_source_present": not auto_executable or bool(defeat_payload.get("kill_credit_source_id")),
        "servant_boundary_replay": bool(servant_kill_case.get("replay", {}).get("ok")),
        "servant_owner_source_frame_preserved": bool(servant_checks.get("kill_credit_owner_is_owner"))
        and bool(servant_checks.get("kill_credit_source_is_source_frame")),
        "servant_boundary_not_claimed_full_formula_executable": servant_kill_case.get("classification")
        == "engine_source_frame_boundary_not_servant_damage_formula_executable",
        "source_audit_or_declared_boundary": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "kill_attribution_source_frame_linkage",
        "boundary_only" if servant_kill_case.get("classification") else "executable",
        checks,
        raw_count=2,
        executable_count=1 if auto_executable else 0,
        gap_attribution={"admission_gap": 1} if not auto_executable else {},
        details={
            "automatic_defeat_payload": _compact_payload(defeat_payload),
            "servant_defeat_payload": _compact_payload(servant_kill_case.get("defeat_payload", {})),
            "servant_boundary_classification": servant_kill_case.get("classification", ""),
        },
    )


def _negative_lifecycle_targetability_row(
    removed_summon_case: dict[str, Any],
    dead_target_case: dict[str, Any],
    summon_negative_case: dict[str, Any],
) -> dict[str, JSONValue]:
    negative_cases = summon_negative_case.get("cases", {})
    checks = {
        "removed_summon_damage_blocked": _nested_ok(removed_summon_case)
        and bool(removed_summon_case["checks"]["checks"].get("damage_to_removed_blocked")),
        "defeated_dead_target_skipped": _nested_ok(dead_target_case),
        "untargetable_servant_blocked": bool(
            isinstance(negative_cases, dict)
            and isinstance(negative_cases.get("untargetable_servant"), dict)
            and negative_cases["untargetable_servant"].get("ok") is True
        ),
        "all_summon_target_negative_state_unchanged": bool(
            summon_negative_case.get("checks", {}).get("checks", {}).get("all_negative_cases_state_unchanged")
        ),
        "negative_cases_no_mutation": bool(removed_summon_case["checks"]["checks"].get("damage_to_removed_blocked"))
        and _nested_ok(dead_target_case)
        and bool(summon_negative_case.get("checks", {}).get("checks", {}).get("all_negative_cases_state_unchanged")),
        "source_audit_or_declared_boundary": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "removed_defeated_untargetable_negative",
        "boundary_only",
        checks,
        raw_count=3,
        executable_count=0,
        details={
            "removed_summon_damage_records": removed_summon_case.get("damage_records", []),
            "dead_target_summary": dead_target_case.get("summary", {}),
            "untargetable_servant_case": negative_cases.get("untargetable_servant", {}) if isinstance(negative_cases, dict) else {},
        },
    )


def _row(
    row_id: str,
    classification: str,
    checks: dict[str, Any],
    *,
    raw_count: int,
    executable_count: int,
    mutation_source_counts: dict[str, int] | Counter[str] | None = None,
    record_type_counts: dict[str, int] | Counter[str] | None = None,
    gap_attribution: dict[str, int] | None = None,
    details: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    return {
        "row_id": row_id,
        "classification": classification,
        "raw_count": raw_count,
        "executable_count": executable_count,
        "blocked_or_gap_count": max(0, raw_count - executable_count),
        "gap_attribution": gap_attribution or {},
        "mutation_source_counts": dict(sorted((mutation_source_counts or {}).items())),
        "record_type_counts": dict(sorted((record_type_counts or {}).items())),
        "checks": {"ok": bool(checks.get("ok")), "checks": checks},
        "details": details or {},
    }


def _nested_ok(case: dict[str, Any]) -> bool:
    checks = case.get("checks")
    if isinstance(checks, dict):
        return bool(checks.get("ok"))
    return False


def _transition_mutations(transition: dict[str, Any]) -> list[dict[str, Any]]:
    mutations = transition.get("mutations") if isinstance(transition, dict) else ()
    return [mutation for mutation in mutations if isinstance(mutation, dict)] if isinstance(mutations, list) else []


def _transition_records(transition: dict[str, Any]) -> list[dict[str, Any]]:
    settlement = transition.get("settlement") if isinstance(transition, dict) else {}
    records = settlement.get("records") if isinstance(settlement, dict) else ()
    return [record for record in records if isinstance(record, dict)] if isinstance(records, list) else []


def _mutation_source_counts(transition: dict[str, Any]) -> dict[str, int]:
    return dict(Counter(str(mutation.get("source") or "") for mutation in _transition_mutations(transition)))


def _record_type_counts(transition: dict[str, Any]) -> dict[str, int]:
    return dict(Counter(str(record.get("record_type") or "") for record in _transition_records(transition)))


def _damage_family_counts(transition: dict[str, Any]) -> dict[str, int]:
    return dict(
        Counter(
            str((mutation.get("metadata") if isinstance(mutation.get("metadata"), dict) else {}).get("damage_formula_family") or "")
            for mutation in _transition_mutations(transition)
            if mutation.get("source") == "damage_system"
        )
    )


def _hp_loss_has_no_normal_multiplier_terms(transition: dict[str, Any]) -> bool:
    for mutation in _transition_mutations(transition):
        metadata = mutation.get("metadata") if isinstance(mutation.get("metadata"), dict) else {}
        if metadata.get("damage_formula_family") != "hp_loss":
            continue
        if metadata.get("normal_multiplier_terms") not in (None, [], ()):
            return False
    return True


def _merge_counter_rows(rows: Iterable[dict[str, int] | Counter[str]]) -> dict[str, int]:
    merged: Counter[str] = Counter()
    for row in rows:
        for key, value in dict(row).items():
            merged[str(key)] += int(value or 0)
    return dict(sorted(merged.items()))


def _row_check(rows: dict[str, Any], row_id: str, check_key: str) -> bool:
    row = rows.get(row_id)
    if not isinstance(row, dict):
        return False
    return _row_inner_check(row, check_key)


def _row_inner_check(row: dict[str, Any], check_key: str) -> bool:
    checks = row.get("checks") if isinstance(row.get("checks"), dict) else {}
    inner = checks.get("checks") if isinstance(checks.get("checks"), dict) else {}
    return inner.get(check_key) is True


def _compact_payload(payload: object) -> dict[str, JSONValue]:
    if not isinstance(payload, dict):
        return {}
    keys = (
        "attacker_id",
        "killer_id",
        "defeated_unit_id",
        "kill_credit_owner_id",
        "kill_credit_source_id",
        "kill_credit_source_kind",
        "damage_sequence_id",
    )
    return {key: payload.get(key) for key in keys if key in payload}


if __name__ == "__main__":
    raise SystemExit(main())
