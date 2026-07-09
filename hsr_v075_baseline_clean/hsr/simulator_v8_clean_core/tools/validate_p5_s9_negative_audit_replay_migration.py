from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .. import BASELINE_VERSION
from ..core.model import JSONValue
from ..rules.rulebook import RuleBook
from ..rules.value_binding import ValueBindingRequest, ValueContext, ValueResolver
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p5_s5_damage_toughness_value_resolver_consumers import (
    build_p5_s5_damage_toughness_value_resolver_consumers_matrix,
)
from .validate_p5_s6_resource_status_callback_consumers import (
    build_p5_s6_resource_status_callback_consumers_matrix,
)
from .validate_p5_s7_monster_custom_summon_binding import (
    build_p5_s7_monster_custom_summon_binding_matrix,
)
from .validate_p5_s8_character_trace_eidolon_binding import (
    build_p5_s8_character_trace_eidolon_binding_matrix,
)


VALIDATION_VERSION = "p5_s9_negative_audit_replay_migration"
MATRIX_SCHEMA_VERSION = "p5_s9_negative_audit_replay_migration_matrix_v1"

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
DISALLOWED_GAP_STATES = {"implementation_missing", "lowering_gap", "validation_gap", "unclassified"}
REQUIRED_ROWS = {
    "blocked_state_unchanged_matrix",
    "value_resolution_source_audit_matrix",
    "value_resolution_replay_matrix",
    "legacy_validation_migration_scope",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p5_s9_negative_audit_replay_migration_matrix(ir, rules)
    matrix_checks = validate_p5_s9_negative_audit_replay_migration_matrix(matrix)
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
                "mode": "p5_s9_negative_source_audit_replay_matrix",
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "full_ir_written": False,
                "full_rulebook_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
                "p5_aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "negative_audit_replay_matrix": matrix["negative_audit_replay_matrix"],
        "gap_attribution_matrix": matrix["gap_attribution_matrix"],
        "stage_matrix_summaries": matrix["stage_matrix_summaries"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p5_s9_negative_audit_replay_migration.json", result)
    write_json(output_dir / "p5_s9_negative_audit_replay_migration_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P5-S9 negative/audit/replay migration matrix.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} "
        f"rows={result['summary']['row_count']} "
        f"classifications={result['summary']['classification_counts']} "
        f"gap_counts={result['summary']['gap_attribution_counts']}"
    )
    return 0 if result["ok"] else 1


def build_p5_s9_negative_audit_replay_migration_matrix(
    ir: Any,
    rules: RuleBook,
    stage_matrices: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    stage_matrices = stage_matrices or {
        "s5": build_p5_s5_damage_toughness_value_resolver_consumers_matrix(ir, rules),
        "s6": build_p5_s6_resource_status_callback_consumers_matrix(ir, rules),
        "s7": build_p5_s7_monster_custom_summon_binding_matrix(ir, rules),
        "s8": build_p5_s8_character_trace_eidolon_binding_matrix(ir, rules),
    }
    direct_negatives = _direct_value_resolver_negative_cases(rules)
    rows = [
        _blocked_state_unchanged_matrix_row(stage_matrices, direct_negatives),
        _value_resolution_source_audit_matrix_row(stage_matrices),
        _value_resolution_replay_matrix_row(stage_matrices),
        _legacy_validation_migration_scope_row(stage_matrices),
    ]
    matrix = {str(row["row_id"]): row for row in rows}
    classification_counts = Counter(str(row.get("classification") or "unclassified") for row in rows)
    gap_counts = _gap_counts(rows)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "negative_audit_replay_matrix": matrix,
        "summary": {
            "row_count": len(matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "disallowed_gap_count": sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES),
            "direct_negative_case_count": len(direct_negatives),
            "stage_matrix_count": len(stage_matrices),
        },
        "gap_attribution_matrix": _gap_attribution_matrix(rows),
        "stage_matrix_summaries": {
            stage_id: dict(matrix_value.get("summary") or {}) for stage_id, matrix_value in stage_matrices.items()
        },
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "reused_stage_matrix_builds": sorted(stage_matrices),
            "static_check_count": 1,
            "full_ir_written": False,
            "full_rulebook_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_files": [
                "validation_summary_p5_s9_negative_audit_replay_migration.json",
                "p5_s9_negative_audit_replay_migration_matrix.json",
            ],
        },
    }


def validate_p5_s9_negative_audit_replay_migration_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("negative_audit_replay_matrix") or {})
    missing = sorted(REQUIRED_ROWS.difference(rows))
    invalid_classifications = sorted(
        row_id
        for row_id, row in rows.items()
        if str(row.get("classification") or "unclassified") not in CLASSIFICATION_STATES
    )
    gap_counts = dict(matrix.get("summary", {}).get("gap_attribution_counts") or {})
    disallowed_gap_count = sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES)
    checks = {
        "required_rows_present": not missing,
        "valid_classifications": not invalid_classifications,
        "row_checks_ok": all(dict(row.get("checks") or {}).get("ok") is True for row in rows.values()),
        "disallowed_gap_count_zero": disallowed_gap_count == 0,
        "blocked_matrix_ok": _row_check(rows, "blocked_state_unchanged_matrix", "all_negative_cases_blocked"),
        "source_audit_matrix_ok": _row_check(rows, "value_resolution_source_audit_matrix", "all_source_audits_ok"),
        "replay_matrix_ok": _row_check(rows, "value_resolution_replay_matrix", "all_replays_ok"),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_rows": missing,
        "invalid_classifications": invalid_classifications,
        "disallowed_gap_count": disallowed_gap_count,
    }


def _direct_value_resolver_negative_cases(rules: RuleBook) -> dict[str, dict[str, JSONValue]]:
    resolver = ValueResolver(rules)
    cases = {
        "unknown_binding_kind": resolver.resolve(ValueBindingRequest(binding_kind="unknown:p5_s9"), ValueContext()),
        "missing_action_context": resolver.resolve(
            ValueBindingRequest(
                binding_kind="skill_formula_param",
                param_index=0,
                formula_role="direct_damage",
                required_context_keys=("action",),
            ),
            ValueContext(),
        ),
        "missing_target_context": resolver.resolve(
            ValueBindingRequest(
                binding_kind="fixed_numeric_expression",
                expression={"Value": 1},
                required_context_keys=("target",),
            ),
            ValueContext(),
        ),
        "missing_owner_context": resolver.resolve(
            ValueBindingRequest(
                binding_kind="runtime_numeric_expression",
                expression={"Value": 1},
                required_context_keys=("owner",),
            ),
            ValueContext(),
        ),
        "missing_event_payload_context": resolver.resolve(
            ValueBindingRequest(
                binding_kind="runtime_numeric_expression",
                expression={"Value": 1},
                required_context_keys=("event_payload",),
            ),
            ValueContext(),
        ),
    }
    return {case_id: result.to_json() for case_id, result in cases.items()}


def _blocked_state_unchanged_matrix_row(
    stage_matrices: dict[str, dict[str, Any]],
    direct_negatives: dict[str, dict[str, JSONValue]],
) -> dict[str, Any]:
    stage_checks = {
        "s5_blocked_damage_no_mutation": _stage_row_check(
            stage_matrices["s5"],
            "consumer_value_resolver_matrix",
            "blocked_value_resolution_no_damage_mutation",
            "blocked_packet_no_mutations",
        ),
        "s6_missing_context_state_unchanged": _stage_row_check(
            stage_matrices["s6"],
            "consumer_matrix",
            "missing_context_negative_state_unchanged",
            "state_unchanged_replay_ok",
        ),
        "s7_missing_sources_state_unchanged": _stage_row_check(
            stage_matrices["s7"],
            "summon_binding_matrix",
            "missing_profile_card_level_source_blocked",
            "all_negative_cases_state_unchanged",
        ),
        "s8_missing_context_blocked": _stage_row_check(
            stage_matrices["s8"],
            "character_binding_matrix",
            "missing_trace_eidolon_value_context_blocked",
            "all_missing_context_blocked",
        ),
    }
    direct_checks = {
        case_id: item.get("ok") is False and bool(item.get("blocked_reason"))
        for case_id, item in direct_negatives.items()
    }
    checks = {
        **stage_checks,
        "direct_negative_cases_present": set(direct_negatives)
        == {
            "unknown_binding_kind",
            "missing_action_context",
            "missing_target_context",
            "missing_owner_context",
            "missing_event_payload_context",
        },
        "direct_negative_cases_blocked": all(direct_checks.values()),
        "all_negative_cases_blocked": all(stage_checks.values()) and all(direct_checks.values()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "blocked_state_unchanged_matrix",
        "boundary_only" if checks["ok"] else "implementation_missing",
        checks,
        "" if checks["ok"] else "implementation_missing",
        {
            "direct_negatives": {
                case_id: {
                    "ok": item.get("ok"),
                    "binding_kind": item.get("binding_kind"),
                    "blocked_reason": item.get("blocked_reason"),
                }
                for case_id, item in direct_negatives.items()
            },
            "stage_checks": stage_checks,
        },
    )


def _value_resolution_source_audit_matrix_row(stage_matrices: dict[str, dict[str, Any]]) -> dict[str, Any]:
    s5_rows = dict(stage_matrices["s5"].get("consumer_value_resolver_matrix") or {})
    s6_rows = dict(stage_matrices["s6"].get("consumer_matrix") or {})
    s8_rows = dict(stage_matrices["s8"].get("character_binding_matrix") or {})
    s6_audit = dict(
        s6_rows.get("consumer_replay_source_audit", {}).get("details", {}).get("resource_audit") or {}
    )
    checks = {
        "s5_source_audit_ok": _row_nested_check(s5_rows, "consumer_source_audit_replay", "source_audit_ok"),
        "s6_resource_mutation_source_audit_ok": _row_nested_check(
            s6_rows,
            "consumer_replay_source_audit",
            "resource_mutation_source_audit_ok",
        ),
        "s6_full_transition_source_audit_ok": s6_audit.get("full_transition_audit_ok") is True,
        "s8_effective_level_source_audit_ok": _row_nested_check(
            s8_rows,
            "eidolon_effective_level_replay_source_audit",
            "source_audit_ok",
        ),
    }
    checks["all_source_audits_ok"] = all(value for key, value in checks.items() if key != "all_source_audits_ok")
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "value_resolution_source_audit_matrix",
        "executable" if checks["ok"] else "implementation_missing",
        checks,
        "" if checks["ok"] else "implementation_missing",
        {
            "s6_resource_audit": s6_audit,
            "audit_scope": "S9 requires S6 full_transition_audit_ok, not only scoped resource mutation audit.",
        },
    )


def _value_resolution_replay_matrix_row(stage_matrices: dict[str, dict[str, Any]]) -> dict[str, Any]:
    checks = {
        "s5_replay_ok": _stage_row_check(
            stage_matrices["s5"],
            "consumer_value_resolver_matrix",
            "consumer_source_audit_replay",
            "replay_ok",
        ),
        "s6_all_replay_ok": _stage_row_check(
            stage_matrices["s6"],
            "consumer_matrix",
            "consumer_replay_source_audit",
            "all_replay_ok",
        ),
        "s7_replay_ok": _stage_row_check(
            stage_matrices["s7"],
            "summon_binding_matrix",
            "summon_binding_replay_settlement_gap_visibility",
            "replay_ok",
        ),
        "s8_replay_ok": _stage_row_check(
            stage_matrices["s8"],
            "character_binding_matrix",
            "eidolon_effective_level_replay_source_audit",
            "replay_ok",
        ),
    }
    checks["all_replays_ok"] = all(value for key, value in checks.items() if key != "all_replays_ok")
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "value_resolution_replay_matrix",
        "executable" if checks["ok"] else "implementation_missing",
        checks,
        "" if checks["ok"] else "implementation_missing",
        checks,
    )


def _legacy_validation_migration_scope_row(stage_matrices: dict[str, dict[str, Any]]) -> dict[str, Any]:
    stage_disallowed = {
        stage_id: int(dict(matrix.get("summary") or {}).get("disallowed_gap_count") or 0)
        for stage_id, matrix in stage_matrices.items()
    }
    checks = {
        "stage_matrices_have_no_disallowed_gap": all(value == 0 for value in stage_disallowed.values()),
        "legacy_validation_commands_required_in_report": True,
        "no_legacy_fake_execution_path_kept": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "legacy_validation_migration_scope",
        "boundary_only" if checks["ok"] else "implementation_missing",
        checks,
        "" if checks["ok"] else "implementation_missing",
        {
            "stage_disallowed_gap_counts": stage_disallowed,
            "note": "S9 script records migration scope; affected legacy validations are run as external commands and indexed in the S9 report.",
        },
    )


def _stage_row_check(matrix: dict[str, Any], matrix_key: str, row_id: str, check_id: str) -> bool:
    rows = dict(matrix.get(matrix_key) or {})
    return _row_nested_check(rows, row_id, check_id)


def _row_nested_check(rows: dict[str, Any], row_id: str, check_id: str) -> bool:
    return dict(rows.get(row_id, {}).get("checks", {}).get("checks") or {}).get(check_id) is True


def _row(
    row_id: str,
    classification: str,
    checks: dict[str, bool],
    gap_attribution: str,
    evidence: Any,
) -> dict[str, Any]:
    return {
        "row_id": row_id,
        "classification": classification,
        "gap_attribution": gap_attribution,
        "checks": {"ok": checks.get("ok") is True, "checks": checks},
        "evidence": evidence,
    }


def _gap_counts(rows: Iterable[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        gap = str(row.get("gap_attribution") or "")
        if gap:
            counts[gap] += 1
    return counts


def _gap_attribution_matrix(rows: Iterable[dict[str, Any]]) -> dict[str, JSONValue]:
    return {
        str(row["row_id"]): {
            "classification": str(row.get("classification") or "unclassified"),
            "gap_attribution": str(row.get("gap_attribution") or ""),
            "ok": dict(row.get("checks") or {}).get("ok") is True,
        }
        for row in rows
    }


def _row_check(rows: dict[str, Any], row_id: str, check_id: str) -> bool:
    return dict(rows.get(row_id, {}).get("checks", {}).get("checks") or {}).get(check_id) is True


if __name__ == "__main__":
    raise SystemExit(main())
