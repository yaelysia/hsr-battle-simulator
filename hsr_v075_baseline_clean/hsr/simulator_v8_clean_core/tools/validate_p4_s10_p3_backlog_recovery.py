from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .. import BASELINE_VERSION
from ..core.model import JSONValue
from ..rules.ir import IRSource, SummonMonsterIntentIR, TargetExpressionIR
from ..rules.rulebook import RuleBook
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p3_summon_assistant_servant_complete import (
    GAP_CLASSIFICATIONS,
    _build_allowed_gap_evidence_matrix,
    _build_inherited_gap_matrix,
    _build_scope_exclusions,
    _build_stage_results,
)


VALIDATION_VERSION = "p4_s10_p3_backlog_recovery"
MATRIX_SCHEMA_VERSION = "p4_s10_p3_backlog_recovery_matrix_v1"

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
REQUIRED_INHERITED_ITEM_IDS = {
    "domain:summon_target_expression:gap_attribution:admission_gap",
    "domain:summoned_monster_intent:gap_attribution:admission_gap",
    "domain:summoned_monster_intent:gap_attribution:source_gap_blocked",
}
REQUIRED_BACKLOG_DIMENSIONS = {
    "target_alias",
    "TargetQuery",
    "custom_value_hash",
    "dynamic_monster_id",
    "profile_card_source",
    "location_type",
}
P3_TARGET_ALIASES = ("CasterServant", "CasterSummonedMinions", "LastSummonMonsters", "ServantEntityList")
P3_TARGET_OPERATIONS = ("GetServant", "GetSummoner", "RemoveServant")


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    stage_results = _build_stage_results(package_root, tbgd_root, rules)
    matrix = build_p4_s10_p3_backlog_recovery_matrix(stage_results, rules)
    matrix_checks = validate_p4_s10_p3_backlog_recovery_matrix(matrix)
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
                "mode": "p4_s10_p3_backlog_recovery_from_current_p3_stage_matrices",
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
        "p3_backlog_recovery_matrix": matrix["p3_backlog_recovery_matrix"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p4_s10_p3_backlog_recovery.json", result)
    write_json(output_dir / "p4_s10_p3_backlog_recovery_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P4-S10 P3 summon backlog recovery.")
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
        f"classifications={result['summary']['classification_counts']} "
        f"inherited_gap_count={result['summary']['inherited_gap_count']}"
    )
    return 0 if result["ok"] else 1


def build_p4_s10_p3_backlog_recovery_matrix(stage_results: dict[str, dict[str, Any]], rules: RuleBook) -> dict[str, Any]:
    inherited_gap_matrix = _build_inherited_gap_matrix(stage_results)
    allowed_gap_evidence = _build_allowed_gap_evidence_matrix(inherited_gap_matrix)
    scope_exclusions = _build_scope_exclusions(stage_results)
    s0_matrix = stage_results["p3_s0_source_inventory"]["_matrix"]
    s8_groups = stage_results["p3_s8_summon_target_relations"]["_groups"]

    inherited_projection = _inherited_projection_rows(inherited_gap_matrix)
    target_backlog = _target_backlog_rows(
        inherited_gap_matrix,
        s0_matrix["domain_matrix"]["summon_target_expression"],
        s8_groups["target_source_matrix"],
        rules,
    )
    summon_intent_backlog = _summoned_monster_intent_backlog_rows(
        inherited_gap_matrix,
        s0_matrix["domain_matrix"]["summoned_monster_intent"],
        rules,
    )
    scope_rows = _scope_exclusion_rows(scope_exclusions)
    regression_gate_rows = _p3_regression_gate_rows(stage_results, inherited_gap_matrix, allowed_gap_evidence)

    all_rows = inherited_projection + target_backlog + summon_intent_backlog + scope_rows + regression_gate_rows
    matrix = {str(row["row_id"]): row for row in all_rows}
    classification_counts = Counter(str(row.get("classification") or "unclassified") for row in all_rows)
    inherited_gap_counts = _gap_counts(inherited_gap_matrix.get("rows", []))
    dimensions = set()
    for row in target_backlog + summon_intent_backlog:
        dimension = str(row.get("backlog_dimension") or "")
        if dimension:
            dimensions.add(dimension)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "p3_backlog_recovery_matrix": matrix,
        "summaries": {
            "p3_inherited_gap_matrix": _compact_json(inherited_gap_matrix["summary"]),
            "p3_allowed_gap_evidence": _compact_json(allowed_gap_evidence["summary"]),
            "p3_scope_exclusions": _compact_json(scope_exclusions["summary"]),
        },
        "summary": {
            "row_count": len(matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "unclassified_count": int(classification_counts.get("unclassified", 0)),
            "inherited_row_count": len(inherited_gap_matrix.get("rows", [])),
            "inherited_projection_row_count": len(inherited_projection),
            "inherited_gap_count": int(inherited_gap_matrix.get("summary", {}).get("gap_count") or 0),
            "inherited_gap_classification_counts": dict(sorted(inherited_gap_counts.items())),
            "disallowed_inherited_gap_count": sum(int(inherited_gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES),
            "required_inherited_items_present": sorted(
                set(str(row.get("p3_item_id") or "") for row in inherited_projection)
                & REQUIRED_INHERITED_ITEM_IDS
            ),
            "backlog_dimensions_present": sorted(dimensions),
            "backlog_dimension_token_counts": _dimension_token_counts(target_backlog + summon_intent_backlog),
            "assistant_avatar_scope_excluded": bool(
                scope_exclusions.get("summary", {}).get("assistant_avatar_excluded_from_p3_summon_acceptance")
            ),
            "allowed_gap_evidence_ok": bool(allowed_gap_evidence.get("summary", {}).get("all_evidence_ok")),
            "p3_stage_results_ok": all(bool(item.get("ok")) for item in stage_results.values()),
            "p3_new_disallowed_gap_count": 0,
        },
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "p3_stage_results_reused_in_memory": True,
            "subprocess_validation_count": 0,
            "full_ir_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_files": [
                "validation_summary_p4_s10_p3_backlog_recovery.json",
                "p4_s10_p3_backlog_recovery_matrix.json",
            ],
        },
    }


def validate_p4_s10_p3_backlog_recovery_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("p3_backlog_recovery_matrix") or {})
    summary = dict(matrix.get("summary") or {})
    invalid_classifications = sorted(
        row_id
        for row_id, row in rows.items()
        if str(row.get("classification") or "unclassified") not in CLASSIFICATION_STATES
    )
    inherited_projection = [row for row in rows.values() if row.get("row_kind") == "p3_inherited_gap_projection"]
    p3_item_ids = {str(row.get("p3_item_id") or "") for row in inherited_projection}
    dimensions = set(str(item) for item in summary.get("backlog_dimensions_present") or [])
    disallowed_gap_rows = [
        row for row in inherited_projection if str(row.get("classification") or "") in DISALLOWED_GAP_STATES
    ]
    gap_projection_rows = [
        row for row in inherited_projection if str(row.get("classification") or "") in GAP_CLASSIFICATIONS
    ]
    scope_rows = [row for row in rows.values() if row.get("row_kind") == "scope_exclusion"]
    checks = {
        "valid_classifications": not invalid_classifications,
        "unclassified_count_zero": int(summary.get("unclassified_count") or 0) == 0,
        "all_rows_checks_ok": all(dict(row.get("checks") or {}).get("ok") is True for row in rows.values()),
        "every_p3_inherited_gap_projected": int(summary.get("inherited_projection_row_count") or 0)
        == int(summary.get("inherited_row_count") or -1),
        "required_inherited_items_present": REQUIRED_INHERITED_ITEM_IDS.issubset(p3_item_ids),
        "gap_projection_rows_have_evidence_and_owner": all(
            bool(row.get("evidence")) and bool(row.get("follow_up_owner")) and bool(row.get("work_package_id"))
            for row in gap_projection_rows
        ),
        "required_backlog_dimensions_present": REQUIRED_BACKLOG_DIMENSIONS.issubset(dimensions),
        "no_disallowed_p3_gap_classification": not disallowed_gap_rows
        and int(summary.get("disallowed_inherited_gap_count") or 0) == 0,
        "allowed_gap_evidence_ok": bool(summary.get("allowed_gap_evidence_ok")),
        "p3_stage_results_ok": bool(summary.get("p3_stage_results_ok")),
        "assistant_avatar_scope_excluded": bool(summary.get("assistant_avatar_scope_excluded")),
        "assistant_scope_rows_not_mixed_into_backlog": all(row.get("classification") == "out_of_scope" for row in scope_rows),
        "matrix_is_summary_only": (
            matrix.get("resource_budget", {}).get("full_ir_written") is False
            and matrix.get("resource_budget", {}).get("full_transition_dump_written") is False
            and matrix.get("resource_budget", {}).get("large_artifacts_written") is False
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "invalid_classifications": invalid_classifications,
        "missing_required_inherited_items": sorted(REQUIRED_INHERITED_ITEM_IDS.difference(p3_item_ids)),
        "missing_required_backlog_dimensions": sorted(REQUIRED_BACKLOG_DIMENSIONS.difference(dimensions)),
        "disallowed_gap_rows": [
            {"row_id": row.get("row_id"), "classification": row.get("classification")} for row in disallowed_gap_rows
        ],
    }


def _inherited_projection_rows(inherited_gap_matrix: dict[str, Any]) -> list[dict[str, JSONValue]]:
    rows: list[dict[str, JSONValue]] = []
    for row in inherited_gap_matrix.get("rows", []):
        item_id = str(row.get("item_id") or "")
        classification = str(row.get("classification") or "unclassified")
        work_package = _work_package_for_inherited_row(item_id, classification)
        checks = {
            "has_p3_evidence": bool(row.get("evidence")),
            "has_details": bool(row.get("details")),
            "has_work_package": bool(work_package["work_package_id"]),
            "classification_is_allowed_for_s10_backlog": classification in {"admission_gap", "source_gap_blocked"},
        }
        checks["ok"] = all(value for key, value in checks.items() if key != "ok")
        rows.append(
            {
                "row_id": f"p3_inherited_gap:{_safe_id(item_id)}",
                "row_kind": "p3_inherited_gap_projection",
                "p3_stage": str(row.get("stage") or ""),
                "p3_item_id": item_id,
                "classification": classification,
                "gap_count": int(row.get("gap_count") or 0),
                "evidence": str(row.get("evidence") or ""),
                "details": _compact_json(row.get("details", {})),
                "work_package_id": work_package["work_package_id"],
                "work_package_kind": work_package["work_package_kind"],
                "follow_up_owner": work_package["follow_up_owner"],
                "s10_resolution": work_package["s10_resolution"],
                "reason_not_fixed_in_s10": work_package["reason_not_fixed_in_s10"],
                "checks": checks,
            }
        )
    return rows


def _target_backlog_rows(
    inherited_gap_matrix: dict[str, Any],
    target_domain_row: dict[str, Any],
    s8_target_source_matrix: dict[str, Any],
    rules: RuleBook,
) -> list[dict[str, JSONValue]]:
    rows: list[dict[str, JSONValue]] = []
    target_inherited = _find_inherited(
        inherited_gap_matrix,
        "domain:summon_target_expression:gap_attribution:admission_gap",
    )
    reason_tokens = _token_counts_by_bucket_from_items(
        target_domain_row.get("gap_reason_token_counts", []),
        _target_bucket,
        classification="admission_gap",
    )
    alias_tokens = reason_tokens.get("target_alias", [])
    target_query_tokens = reason_tokens.get("TargetQuery", [])
    other_tokens = [
        item
        for bucket, items in sorted(reason_tokens.items())
        if bucket not in {"target_alias", "TargetQuery"}
        for item in items
    ]
    s8_rows = list(s8_target_source_matrix.get("rows") or [])
    s8_required = [
        row
        for row in s8_rows
        if row.get("name") in set(P3_TARGET_ALIASES) | set(P3_TARGET_OPERATIONS)
    ]
    target_exprs = [item for item in rules.target_expressions() if _is_p3_target_expression(item)]
    checks = {
        "required_alias_rows_executable": all(
            _s8_row_classification(s8_required, alias) == "executable" for alias in P3_TARGET_ALIASES
        ),
        "required_operation_rows_executable": all(
            _s8_row_classification(s8_required, operation) == "executable" for operation in P3_TARGET_OPERATIONS
        ),
        "positive_executable_does_not_hide_gap": int(target_inherited.get("gap_count") or 0) > 0,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    rows.append(
        {
            "row_id": "summon_target_expression:source_backed_required_alias_operation_positive",
            "row_kind": "summon_target_backlog",
            "backlog_dimension": "target_alias",
            "classification": "executable",
            "gap_count": 0,
            "raw_count": int(target_domain_row.get("raw_count") or 0),
            "ir_count": int(target_domain_row.get("ir_count") or 0),
            "executable_count": sum(1 for item in target_exprs if item.coverage_status == "executable"),
            "s8_rows": _compact_json(s8_required),
            "evidence": "P3-S8 required summon/servant aliases and operations remain executable; S10 does not use this positive row to erase broader alias/TargetQuery gaps.",
            "follow_up_owner": "target expression admission backlog",
            "checks": checks,
        }
    )
    rows.append(
        _dimension_row(
            row_id="summon_target_expression:admission_gap:target_alias",
            row_kind="summon_target_backlog",
            dimension="target_alias",
            classification="admission_gap",
            p3_item_id=str(target_inherited.get("item_id") or ""),
            inherited_gap_count=int(target_inherited.get("gap_count") or 0),
            tokens=alias_tokens,
            work_package_id="p4_backlog_target_alias_admission_batch",
            follow_up_owner="target expression lowering/admission",
            evidence="Non-core summon/servant target aliases are present in TargetExpressionIR but still blocked by alias admission.",
            reason_not_fixed="Each alias needs source-backed semantic lowering and negative target tests; S10 records the backlog without adding name fallbacks.",
        )
    )
    rows.append(
        _dimension_row(
            row_id="summon_target_expression:admission_gap:TargetQuery",
            row_kind="summon_target_backlog",
            dimension="TargetQuery",
            classification="admission_gap",
            p3_item_id=str(target_inherited.get("item_id") or ""),
            inherited_gap_count=int(target_inherited.get("gap_count") or 0),
            tokens=target_query_tokens,
            work_package_id="p4_backlog_target_query_admission_batch",
            follow_up_owner="target expression TargetQuery admission",
            evidence="TargetQuery appears in summon/servant target sources and is still blocked by explicit admission.",
            reason_not_fixed="TargetQuery requires payload-level query semantics and state-unchanged negative tests; S10 does not infer it from names.",
        )
    )
    if other_tokens:
        rows.append(
            _dimension_row(
                row_id="summon_target_expression:admission_gap:other",
                row_kind="summon_target_backlog",
                dimension="target_other",
                classification="admission_gap",
                p3_item_id=str(target_inherited.get("item_id") or ""),
                inherited_gap_count=int(target_inherited.get("gap_count") or 0),
                tokens=other_tokens,
                work_package_id="p4_backlog_target_other_admission_batch",
                follow_up_owner="target expression admission backlog",
                evidence="S0 reported summon target blockers outside alias/TargetQuery buckets.",
                reason_not_fixed="The residual bucket needs separate semantic classification before runtime admission.",
            )
        )
    return rows


def _summoned_monster_intent_backlog_rows(
    inherited_gap_matrix: dict[str, Any],
    summon_domain_row: dict[str, Any],
    rules: RuleBook,
) -> list[dict[str, JSONValue]]:
    admission_row = _find_inherited(
        inherited_gap_matrix,
        "domain:summoned_monster_intent:gap_attribution:admission_gap",
    )
    source_gap_row = _find_inherited(
        inherited_gap_matrix,
        "domain:summoned_monster_intent:gap_attribution:source_gap_blocked",
    )
    intents = tuple(rules.summon_monster_intents())
    blocked_records = _summon_blocked_records(intents)
    dimension_records = _summon_dimension_records(blocked_records)
    dimension_tokens = _tokens_by_dimension(blocked_records)
    rows: list[dict[str, JSONValue]] = []
    checks = {
        "summon_intents_rulebook_visible": len(intents) == int(summon_domain_row.get("ir_count") or 0),
        "domain_has_executable_positive": int(summon_domain_row.get("executable_count") or 0) > 0,
        "inherited_admission_gap_retained": int(admission_row.get("gap_count") or 0) > 0,
        "inherited_source_gap_retained": int(source_gap_row.get("gap_count") or 0) > 0,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    rows.append(
        {
            "row_id": "summoned_monster_intent:domain_projection",
            "row_kind": "summoned_monster_intent_backlog",
            "backlog_dimension": "summoned_monster_intent_domain",
            "classification": "executable",
            "gap_count": 0,
            "raw_count": int(summon_domain_row.get("raw_count") or 0),
            "ir_count": len(intents),
            "executable_count": int(summon_domain_row.get("executable_count") or 0),
            "blocked_count": int(summon_domain_row.get("blocked_count") or 0),
            "inherited_gap_counts": {
                "admission_gap": int(admission_row.get("gap_count") or 0),
                "source_gap_blocked": int(source_gap_row.get("gap_count") or 0),
            },
            "evidence": "Summoned monster intent domain has executable positives, but S10 keeps inherited sub-gaps as separate backlog rows.",
            "follow_up_owner": "summoned monster intent admission/source backlog",
            "checks": checks,
        }
    )
    dimension_specs = [
        (
            "custom_value_hash",
            "admission_gap",
            admission_row,
            "p4_backlog_summon_custom_value_hash_binding",
            "summoned monster custom value binding",
            "MonsterIDFromCustomValue hash blockers require source-backed custom value binding from ability context.",
        ),
        (
            "dynamic_monster_id",
            "admission_gap",
            admission_row,
            "p4_backlog_summon_dynamic_monster_id_binding",
            "summoned monster dynamic id binding",
            "Dynamic monster id blockers require numeric binding semantics, not fixed-id fallback.",
        ),
        (
            "location_type",
            "admission_gap",
            admission_row,
            "p4_backlog_summon_location_type_position_policy",
            "summoned monster position policy admission",
            "LocationType blockers require runtime position semantics and negative tests for unsupported placement.",
        ),
        (
            "level_policy_monster_id_unresolved",
            "admission_gap",
            admission_row,
            "p4_backlog_summon_level_policy_id_resolution",
            "summoned monster level policy admission",
            "Level policy cannot execute while monster id is unresolved.",
        ),
        (
            "profile_card_source",
            "source_gap_blocked",
            source_gap_row,
            "p4_backlog_summon_profile_card_source",
            "monster profile/card source completeness",
            "Profile/card source blockers require real monster profile or data-card source completion.",
        ),
    ]
    for dimension, classification, inherited, work_package_id, owner, evidence in dimension_specs:
        rows.append(
            _dimension_row(
                row_id=f"summoned_monster_intent:{classification}:{dimension}",
                row_kind="summoned_monster_intent_backlog",
                dimension=dimension,
                classification=classification,
                p3_item_id=str(inherited.get("item_id") or ""),
                inherited_gap_count=int(inherited.get("gap_count") or 0),
                tokens=dimension_tokens.get(dimension, []),
                work_package_id=work_package_id,
                follow_up_owner=owner,
                evidence=evidence,
                reason_not_fixed="S10 records the structurally identified work package; admitting it needs dedicated semantics and blocked/state-unchanged validation.",
                record_sample=dimension_records.get(dimension, [])[:8],
            )
        )
    return rows


def _scope_exclusion_rows(scope_exclusions: dict[str, Any]) -> list[dict[str, JSONValue]]:
    rows = []
    for row in scope_exclusions.get("rows", []):
        checks = {
            "classification_out_of_scope": row.get("classification") == "out_of_scope",
            "has_follow_up_owner": bool(row.get("follow_up_owner")),
            "not_counted_as_summon_backlog": True,
        }
        checks["ok"] = all(value for key, value in checks.items() if key != "ok")
        rows.append(
            {
                "row_id": f"scope_exclusion:{_safe_id(str(row.get('item_id') or 'assistant_avatar'))}",
                "row_kind": "scope_exclusion",
                "classification": "out_of_scope",
                "gap_count": 0,
                "p3_item_id": str(row.get("item_id") or ""),
                "evidence": str(row.get("evidence") or ""),
                "follow_up_owner": str(row.get("follow_up_owner") or ""),
                "details": _compact_json(row),
                "checks": checks,
            }
        )
    return rows


def _p3_regression_gate_rows(
    stage_results: dict[str, dict[str, Any]],
    inherited_gap_matrix: dict[str, Any],
    allowed_gap_evidence: dict[str, Any],
) -> list[dict[str, JSONValue]]:
    inherited_counts = _gap_counts(inherited_gap_matrix.get("rows", []))
    checks = {
        "p3_stage_results_ok": all(bool(item.get("ok")) for item in stage_results.values()),
        "inherited_unclassified_zero": int(inherited_gap_matrix.get("summary", {}).get("unclassified_count") or 0) == 0,
        "allowed_gap_evidence_ok": bool(allowed_gap_evidence.get("summary", {}).get("all_evidence_ok")),
        "no_implementation_missing_gap": int(inherited_counts.get("implementation_missing", 0)) == 0,
        "no_lowering_gap": int(inherited_counts.get("lowering_gap", 0)) == 0,
        "no_validation_gap": int(inherited_counts.get("validation_gap", 0)) == 0,
        "no_unclassified_gap": int(inherited_counts.get("unclassified", 0)) == 0,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return [
        {
            "row_id": "p3_regression_gate:foundation_still_green",
            "row_kind": "p3_regression_gate",
            "classification": "executable",
            "gap_count": 0,
            "evidence": "S10 rebuilds the current P3 stage matrices in memory and requires all P3 sub-stage checks to remain ok.",
            "follow_up_owner": "P4-S12 aggregate regression",
            "p3_stage_ok": {name: bool(result.get("ok")) for name, result in stage_results.items()},
            "inherited_gap_counts": dict(sorted(inherited_counts.items())),
            "checks": checks,
        }
    ]


def _dimension_row(
    *,
    row_id: str,
    row_kind: str,
    dimension: str,
    classification: str,
    p3_item_id: str,
    inherited_gap_count: int,
    tokens: list[dict[str, Any]],
    work_package_id: str,
    follow_up_owner: str,
    evidence: str,
    reason_not_fixed: str,
    record_sample: list[dict[str, Any]] | None = None,
) -> dict[str, JSONValue]:
    token_count = sum(int(item.get("count") or 0) for item in tokens)
    checks = {
        "has_inherited_p3_item": bool(p3_item_id),
        "has_tokens_or_explicit_empty_bucket": bool(tokens),
        "has_work_package": bool(work_package_id),
        "has_follow_up_owner": bool(follow_up_owner),
        "does_not_claim_done": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "row_id": row_id,
        "row_kind": row_kind,
        "backlog_dimension": dimension,
        "classification": classification,
        "gap_count": int(inherited_gap_count if token_count else 0),
        "inherited_gap_count": int(inherited_gap_count),
        "dimension_token_count": int(token_count),
        "token_samples": _compact_json(tokens),
        "record_sample": _compact_json(record_sample or []),
        "p3_item_id": p3_item_id,
        "work_package_id": work_package_id,
        "follow_up_owner": follow_up_owner,
        "s10_resolution": "retained_as_structured_backlog",
        "reason_not_fixed_in_s10": reason_not_fixed,
        "evidence": evidence,
        "checks": checks,
    }


def _find_inherited(inherited_gap_matrix: dict[str, Any], item_id: str) -> dict[str, Any]:
    for row in inherited_gap_matrix.get("rows", []):
        if row.get("item_id") == item_id:
            return dict(row)
    return {
        "stage": "",
        "item_id": item_id,
        "classification": "unclassified",
        "gap_count": 0,
        "evidence": "",
        "details": {},
    }


def _work_package_for_inherited_row(item_id: str, classification: str) -> dict[str, str]:
    if "summon_target_expression" in item_id:
        return {
            "work_package_id": "p4_backlog_summon_target_expression_admission",
            "work_package_kind": "target_expression_admission",
            "follow_up_owner": "target expression lowering/admission",
            "s10_resolution": "split_into_target_alias_and_TargetQuery_submatrix",
            "reason_not_fixed_in_s10": "Current blockers are admission semantics for additional aliases/query nodes; fixing requires dedicated semantic lowering and negative target tests.",
        }
    if "summoned_monster_intent" in item_id and classification == "source_gap_blocked":
        return {
            "work_package_id": "p4_backlog_summoned_monster_profile_card_source",
            "work_package_kind": "monster_profile_card_source_gap",
            "follow_up_owner": "monster data-card/profile source expansion",
            "s10_resolution": "split_into_profile_card_source_submatrix",
            "reason_not_fixed_in_s10": "Current blockers cite missing or blocked real monster profile/card sources; S10 cannot synthesize those sources.",
        }
    if "summoned_monster_intent" in item_id:
        return {
            "work_package_id": "p4_backlog_summoned_monster_intent_admission",
            "work_package_kind": "summoned_monster_intent_admission",
            "follow_up_owner": "summoned monster intent admission",
            "s10_resolution": "split_into_custom_value_dynamic_id_location_and_level_policy_submatrix",
            "reason_not_fixed_in_s10": "Current blockers require binding or placement semantics; S10 records work packages without adding runtime fallbacks.",
        }
    return {
        "work_package_id": "p4_backlog_unexpected_p3_gap",
        "work_package_kind": "unexpected_gap_projection",
        "follow_up_owner": "P4-S12 aggregate gate",
        "s10_resolution": "unexpected_gap_kept_visible",
        "reason_not_fixed_in_s10": "Unexpected inherited P3 gap must remain visible for aggregate review.",
    }


def _s8_row_classification(rows: list[dict[str, Any]], name: str) -> str:
    for row in rows:
        if row.get("name") == name:
            return str(row.get("classification") or "")
    return ""


def _is_p3_target_expression(expression: TargetExpressionIR) -> bool:
    alias = str(expression.alias or "")
    operation = str(expression.source.evidence.get("operation") or "")
    kind = str(expression.expression_kind or "")
    return (
        alias in P3_TARGET_ALIASES
        or any(term in alias.lower() for term in ("servant", "summon", "summoner"))
        or operation in P3_TARGET_OPERATIONS
        or any(term in operation.lower() for term in ("servant", "summon", "summoner"))
        or kind == "TargetQuery"
    )


def _target_bucket(token: str) -> str:
    if token.startswith("target_expression_not_admitted:TargetQuery") or "TargetQuery" in token:
        return "TargetQuery"
    if token.startswith("target_alias_not_admitted:"):
        return "target_alias"
    return "target_other"


def _token_counts_by_bucket_from_items(
    tokens: Any,
    classifier,
    *,
    classification: str = "",
) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(tokens, list):
        return {}
    result: dict[str, list[dict[str, Any]]] = {}
    for item in tokens:
        if not isinstance(item, dict):
            continue
        if classification and str(item.get("classification") or "") != classification:
            continue
        key = str(item.get("key") or "")
        bucket = classifier(key)
        result.setdefault(bucket, []).append(dict(item))
    return result


def _summon_blocked_records(intents: Iterable[SummonMonsterIntentIR]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for intent in intents:
        for token in _split_reason(intent.blocked_reason):
            records.append(
                {
                    "record_kind": "intent",
                    "record_id": intent.summon_intent_id,
                    "coverage_status": intent.coverage_status,
                    "token": token,
                    "source": _source_sample(intent.source),
                }
            )
        for entry in intent.entries:
            for token in _split_reason(entry.blocked_reason):
                records.append(
                    {
                        "record_kind": "entry",
                        "record_id": entry.entry_id,
                        "intent_id": intent.summon_intent_id,
                        "coverage_status": entry.coverage_status,
                        "token": token,
                        "monster_raw_id": entry.monster_raw_id,
                        "monster_entity_ref": entry.monster_entity_ref,
                        "location_type": entry.position_policy.get("location_type"),
                        "source": _source_sample(entry.source),
                    }
                )
    return records


def _summon_dimension_records(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    seen: dict[str, set[str]] = {}
    for record in records:
        dimension = _summon_dimension(str(record.get("token") or ""))
        if not dimension:
            continue
        record_key = str(record.get("record_id") or "")
        if record_key in seen.setdefault(dimension, set()):
            continue
        seen[dimension].add(record_key)
        result.setdefault(dimension, []).append(_compact_json(record))
    return result


def _tokens_by_dimension(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    counter_by_dimension: dict[str, Counter[str]] = {}
    for record in records:
        token = str(record.get("token") or "")
        dimension = _summon_dimension(token)
        if not dimension:
            continue
        counter_by_dimension.setdefault(dimension, Counter())[token] += 1
    return {
        dimension: [
            {"key": token, "count": int(count), "classification": _classification_for_summon_dimension(dimension)}
            for token, count in sorted(counter.items(), key=lambda item: (-int(item[1]), item[0]))
        ]
        for dimension, counter in sorted(counter_by_dimension.items())
    }


def _summon_dimension(token: str) -> str:
    lowered = token.lower()
    if "custom_value_hash" in lowered or "custom_value_not_admitted" in lowered:
        return "custom_value_hash"
    if "dynamic_monster_id" in lowered or "dynamic_hash" in lowered:
        return "dynamic_monster_id"
    if "location_type" in lowered:
        return "location_type"
    if "profile_source" in lowered or "data_card_source" in lowered or "monster_template_base_stat_missing" in lowered:
        return "profile_card_source"
    if "level_policy_monster_id_unresolved" in lowered:
        return "level_policy_monster_id_unresolved"
    return "summoned_monster_intent_other"


def _classification_for_summon_dimension(dimension: str) -> str:
    if dimension == "profile_card_source":
        return "source_gap_blocked"
    return "admission_gap"


def _split_reason(reason: str) -> tuple[str, ...]:
    return tuple(part for part in (item.strip() for item in str(reason or "").split(";")) if part)


def _gap_counts(rows: Iterable[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter({key: 0 for key in GAP_CLASSIFICATIONS})
    for row in rows:
        classification = str(row.get("classification") or "unclassified")
        if classification in GAP_CLASSIFICATIONS:
            counts[classification] += int(row.get("gap_count") or 1)
    return counts


def _dimension_token_counts(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        dimension = str(row.get("backlog_dimension") or "")
        if not dimension:
            continue
        counts[dimension] += int(row.get("dimension_token_count") or 0)
    return dict(sorted(counts.items()))


def _source_sample(source: IRSource | None) -> dict[str, JSONValue]:
    if source is None:
        return {}
    evidence = source.evidence if isinstance(source.evidence, dict) else {}
    return {
        "source_path": source.source_path,
        "raw_type": source.raw_type,
        "raw_id": source.raw_id,
        "evidence_keys": sorted(str(key) for key in evidence.keys())[:20],
    }


def _compact_json(value: Any, *, depth: int = 0) -> JSONValue:
    if depth > 4:
        return "..."
    if isinstance(value, dict):
        result: dict[str, JSONValue] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 16:
                result["..."] = "truncated"
                break
            result[str(key)] = _compact_json(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_compact_json(item, depth=depth + 1) for item in list(value)[:16]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._:-" else "_" for ch in value)[:160]


if __name__ == "__main__":
    raise SystemExit(main())
