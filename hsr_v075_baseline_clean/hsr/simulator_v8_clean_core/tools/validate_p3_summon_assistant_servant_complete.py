from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import JSONValue
from ..rules.rulebook import RuleBook
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p1_3_summon_assistant_servant import (
    _select_executable_servant_definition,
    _select_executable_summon_monster_intent,
)
from .validate_p1_8_battle_setup import _select_enemy_entity
from .validate_p3_s0_summon_source_inventory import (
    _assistant_source_matrix,
    _raw_ability_source_matrix,
    build_p3_summon_source_inventory_matrix,
    validate_p3_summon_source_inventory_matrix,
)
from .validate_p3_s1_summon_ir_rulebook_contract import (
    build_p3_s1_contract_matrix,
    validate_p3_s1_contract_matrix,
)
from .validate_p3_s2_summon_runtime_schema import (
    build_p3_s2_runtime_matrix,
    validate_p3_s2_runtime_matrix,
)
from .validate_p3_s3_summoned_monster_spawn import (
    _raw_summon_monster_matrix,
    build_p3_s3_spawn_matrix,
    validate_p3_s3_spawn_matrix,
)
from .validate_p3_s4_summon_unit_admission import (
    _raw_summon_unit_matrix,
    _summon_unit_reference_matrix,
    build_p3_s4_admission_matrix,
    validate_p3_s4_admission_matrix,
)
from .validate_p3_s5_servant_lifecycle import (
    _servant_definition_matrix,
    _servant_negative_boundary_cases,
    _servant_spawn_owner_lifecycle_case,
)
from .validate_p3_s6_summon_action_execution import (
    _executor_bypass_boundary_cases,
    _resource_pressure_boundary_case,
    _servant_action_execution_case,
    _summoned_monster_action_boundary_case,
)
from .validate_p3_s7_assistant_queue_execution import (
    _assistant_queue_drain_boundary_case,
    _assistant_queue_window_consistency_case,
    _assistant_scope_negative_cases,
    _assistant_source_layers_case,
)
from .validate_p3_s8_summon_target_relations import (
    _assistant_target_boundary_case,
    _combined_summon_state,
    _global_target_config,
    _source_backed_positive_relations_case,
    _target_relation_negative_cases,
    _target_source_matrix_case,
)
from .validate_p3_s9_summon_lifecycle_cleanup import (
    _explicit_remove_cleanup_case,
    _owner_cleanup_case,
    _wave_clear_policy_case,
)
from .validate_p3_s10_summon_status_resource_damage import (
    _kill_attribution_source_frame_case,
    _removed_summon_damage_negative_case,
    _resource_ownership_boundary_case,
    _servant_damage_stat_boundary_case,
    _servant_status_holder_case,
    _source_matrix_case as _status_resource_damage_source_matrix_case,
)
from .validate_p3_s11_battle_setup_scenario_route import (
    _illegal_damage_route_blocked_case,
    _initial_servant_route_execution_case,
    _initial_summon_blocked_boundary_case,
    _missing_target_route_blocked_case,
)


VALIDATION_VERSION = "p3_summon_assistant_servant_complete"

GAP_CLASSIFICATIONS = {
    "source_gap_blocked",
    "implementation_missing",
    "lowering_gap",
    "admission_gap",
    "validation_gap",
    "unclassified",
}
FINAL_CLASSIFICATIONS = {"executable", "boundary_only", "source_absent_not_required", "out_of_scope"}


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    *,
    rules: RuleBook | None = None,
) -> dict[str, Any]:
    rulebook_build_count = 0
    if rules is None:
        rules = RuleBook(TBGDLowering(tbgd_root).build())
        rulebook_build_count = 1
    ir = rules.ir
    static_result = run_static_checks(package_root)
    stage_results = _build_stage_results(package_root, tbgd_root, rules)
    source_matrix = _build_final_source_matrix(stage_results)
    mechanism_matrix = _build_final_mechanism_matrix(stage_results)
    inherited_gap_matrix = _build_inherited_gap_matrix(stage_results)
    allowed_gap_evidence = _build_allowed_gap_evidence_matrix(inherited_gap_matrix)
    positive_samples = _build_positive_samples(stage_results)
    blocked_samples = _build_blocked_samples(stage_results)
    audit_samples = _build_audit_samples(stage_results)
    replay_samples = _build_replay_samples(stage_results)
    scope_exclusions = _build_scope_exclusions(stage_results)
    public_stage_results = _public_stage_results(stage_results)
    resource_budget = {
        "rulebook_build_count": rulebook_build_count,
        "static_check_count": 1,
        "subprocess_validation_count": 0,
        "subvalidators_reused_in_memory": True,
        "large_artifacts_written": False,
        "full_ir_written": False,
        "full_transition_dump_written": False,
        "output_scope": "summary_matrices_samples_and_resource_budget_only",
    }
    final_classification_counts = Counter(row["classification"] for row in mechanism_matrix["rows"])
    final_source_classification_counts = Counter(row["classification"] for row in source_matrix["rows"])
    gap_counts = _gap_counts(inherited_gap_matrix["rows"])
    stage_ok = all(item["ok"] for item in stage_results.values())
    classification_integrity_ok = (
        source_matrix["summary"]["unclassified_count"] == 0
        and mechanism_matrix["summary"]["unclassified_count"] == 0
        and inherited_gap_matrix["summary"]["unclassified_count"] == 0
    )
    phase_gap_free = (
        inherited_gap_matrix["summary"]["gap_count"] == 0
        and source_matrix["summary"]["gap_count"] == 0
        and mechanism_matrix["summary"]["gap_count"] == 0
        and all(value == 0 for value in gap_counts.values())
    )
    disallowed_gap_free = all(
        gap_counts[key] == 0 for key in ("implementation_missing", "lowering_gap", "validation_gap", "unclassified")
    )
    sample_ok = (
        positive_samples["summary"]["sample_count"] >= 6
        and blocked_samples["summary"]["sample_count"] >= 6
        and audit_samples["summary"]["all_ok"]
        and replay_samples["summary"]["all_ok"]
    )
    checks = {
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
        "stage_results": {"ok": stage_ok, "checks": {name: item["ok"] for name, item in stage_results.items()}},
        "source_matrix": {
            "ok": source_matrix["summary"]["unclassified_count"] == 0,
            "checks": {
                "sources_classified": source_matrix["summary"]["unclassified_count"] == 0,
                "source_gap_projection_count": source_matrix["summary"]["gap_count"],
            },
        },
        "mechanism_matrix": {
            "ok": mechanism_matrix["summary"]["unclassified_count"] == 0,
            "checks": {
                "mechanisms_classified": mechanism_matrix["summary"]["unclassified_count"] == 0,
                "mechanism_gap_projection_count": mechanism_matrix["summary"]["gap_count"],
            },
        },
        "inherited_stage_gaps": {
            "ok": inherited_gap_matrix["summary"]["unclassified_count"] == 0,
            "checks": {
                "stage_gap_rows_classified": inherited_gap_matrix["summary"]["unclassified_count"] == 0,
                "stage_gap_count": inherited_gap_matrix["summary"]["gap_count"],
                "stage_gap_counts": inherited_gap_matrix["summary"]["classification_counts"],
            },
        },
        "allowed_gap_evidence": {
            "ok": allowed_gap_evidence["summary"]["all_evidence_ok"],
            "checks": {
                "allowed_gap_row_count": allowed_gap_evidence["summary"]["row_count"],
                "allowed_gap_total_count": allowed_gap_evidence["summary"]["allowed_gap_count"],
                "all_allowed_gap_rows_have_evidence": allowed_gap_evidence["summary"]["all_evidence_ok"],
            },
        },
        "samples": {
            "ok": sample_ok,
            "checks": {
                "positive_sample_count": positive_samples["summary"]["sample_count"] >= 6,
                "blocked_sample_count": blocked_samples["summary"]["sample_count"] >= 6,
                "source_audit_samples_ok": audit_samples["summary"]["all_ok"],
                "replay_samples_ok": replay_samples["summary"]["all_ok"],
            },
        },
        "resource_budget": {
            "ok": resource_budget["rulebook_build_count"] <= 1
            and resource_budget["large_artifacts_written"] is False
            and resource_budget["full_ir_written"] is False
            and resource_budget["full_transition_dump_written"] is False,
            "checks": {
                "at_most_single_rulebook_build": resource_budget["rulebook_build_count"] <= 1,
                "no_large_artifacts": resource_budget["large_artifacts_written"] is False,
                "no_full_ir": resource_budget["full_ir_written"] is False,
                "no_full_transition_dump": resource_budget["full_transition_dump_written"] is False,
            },
        },
        "scope_exclusions": {
            "ok": scope_exclusions["summary"]["all_scope_exclusions_classified"],
            "checks": {
                "assistant_avatar_excluded_from_p3_summon_acceptance": scope_exclusions["summary"][
                    "assistant_avatar_excluded_from_p3_summon_acceptance"
                ],
                "scope_exclusion_rows_present": scope_exclusions["summary"]["row_count"] > 0,
            },
        },
    }
    validation_gate_ok = all(item["ok"] for item in checks.values())
    phase_completion_checks = {
        "validation_gate_ok": validation_gate_ok,
        "classification_integrity_ok": classification_integrity_ok,
        "allowed_gap_evidence_ok": allowed_gap_evidence["summary"]["all_evidence_ok"],
        "no_implementation_missing": gap_counts["implementation_missing"] == 0,
        "no_lowering_gap": gap_counts["lowering_gap"] == 0,
        "no_validation_gap": gap_counts["validation_gap"] == 0,
        "no_unclassified_gap": gap_counts["unclassified"] == 0,
    }
    foundation_closed = validation_gate_ok and disallowed_gap_free and all(phase_completion_checks.values())
    all_executable_complete = validation_gate_ok and phase_gap_free
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": validation_gate_ok,
        "validation_gate_ok": validation_gate_ok,
        "p3_summon_foundation_closed": foundation_closed,
        "p3_summon_all_executable_complete": all_executable_complete,
        "p3_summon_phase_complete": foundation_closed,
        "p3_summon_acceptance_ok": foundation_closed,
        "p3_summon_substrate_complete": foundation_closed,
        "p3_summon_result_status": (
            "foundation_closed_with_admission_or_source_gaps"
            if foundation_closed and not all_executable_complete
            else "all_executable_complete"
            if all_executable_complete
            else "validation_gate_ok_phase_incomplete_with_disallowed_gaps"
            if validation_gate_ok
            else "validation_gate_failed"
        ),
        "p3_summon_sources_classified": source_matrix["summary"]["unclassified_count"] == 0,
        "p3_summon_implementation_missing_count": gap_counts["implementation_missing"],
        "p3_summon_source_gap_blocked_count": gap_counts["source_gap_blocked"],
        "p3_summon_lowering_gap_count": gap_counts["lowering_gap"],
        "p3_summon_admission_gap_count": gap_counts["admission_gap"],
        "p3_summon_validation_gap_count": gap_counts["validation_gap"],
        "p3_summon_unclassified_count": gap_counts["unclassified"],
        "p3_summon_scope_exclusion_count": scope_exclusions["summary"]["row_count"],
        "source_absent_not_required_count": int(
            final_classification_counts.get("source_absent_not_required", 0)
            + final_source_classification_counts.get("source_absent_not_required", 0)
        ),
        "boundary_only_count": int(
            final_classification_counts.get("boundary_only", 0)
            + final_source_classification_counts.get("boundary_only", 0)
        ),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "p3_s12_single_rulebook_aggregate_structured_stage_evidence",
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "textmap_read": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
            },
            "resource_budget": resource_budget,
        },
        "summary": {
            "stage_count": len(stage_results),
            "failed_stage_count": sum(0 if item["ok"] else 1 for item in stage_results.values()),
            "source_classification_counts": dict(sorted(final_source_classification_counts.items())),
            "mechanism_classification_counts": dict(sorted(final_classification_counts.items())),
            "inherited_gap_classification_counts": inherited_gap_matrix["summary"]["classification_counts"],
            "inherited_gap_count": inherited_gap_matrix["summary"]["gap_count"],
            "gap_counts": dict(sorted(gap_counts.items())),
            "positive_sample_count": positive_samples["summary"]["sample_count"],
            "blocked_sample_count": blocked_samples["summary"]["sample_count"],
            "source_audit_sample_count": audit_samples["summary"]["sample_count"],
            "replay_sample_count": replay_samples["summary"]["sample_count"],
            "scope_exclusion_count": scope_exclusions["summary"]["row_count"],
        },
        "checks": checks,
        "phase_completion_checks": {"ok": foundation_closed, "checks": phase_completion_checks},
        "stage_results": public_stage_results,
        "source_matrix_summary": source_matrix["summary"],
        "mechanism_matrix_summary": mechanism_matrix["summary"],
        "inherited_gap_matrix_summary": inherited_gap_matrix["summary"],
        "allowed_gap_evidence_summary": allowed_gap_evidence["summary"],
        "scope_exclusions_summary": scope_exclusions["summary"],
        "positive_samples_summary": positive_samples["summary"],
        "blocked_samples_summary": blocked_samples["summary"],
        "source_audit_summary": audit_samples["summary"],
        "replay_summary": replay_samples["summary"],
        "resource_budget": resource_budget,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p3_summon_assistant_servant_complete.json", result)
    write_json(output_dir / "p3_summon_source_total_matrix.json", source_matrix)
    write_json(output_dir / "p3_summon_mechanism_classification_matrix.json", mechanism_matrix)
    write_json(output_dir / "p3_summon_inherited_gap_matrix.json", inherited_gap_matrix)
    write_json(output_dir / "p3_summon_allowed_gap_evidence_matrix.json", allowed_gap_evidence)
    write_json(output_dir / "p3_summon_scope_exclusions.json", scope_exclusions)
    write_json(
        output_dir / "p3_summon_transition_audit_samples.json",
        {
            "positive_samples": positive_samples,
            "blocked_samples": blocked_samples,
            "source_audit_samples": audit_samples,
            "replay_samples": replay_samples,
        },
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate P3 summon/servant closure with AssistantAvatar scope exclusion."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument(
        "--require-phase-complete",
        action="store_true",
        help="Return non-zero when the validation report is trustworthy but P3 phase gaps remain.",
    )
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} validation_gate_ok={result['validation_gate_ok']} "
        f"p3_summon_foundation_closed={result['p3_summon_foundation_closed']} "
        f"p3_summon_phase_complete={result['p3_summon_phase_complete']} "
        f"p3_summon_all_executable_complete={result['p3_summon_all_executable_complete']} "
        f"p3_summon_sources_classified={result['p3_summon_sources_classified']} "
        f"gap_counts={result['summary']['gap_counts']}"
    )
    if args.require_phase_complete and not result["p3_summon_phase_complete"]:
        return 1
    return 0 if result["ok"] else 1


def _build_stage_results(package_root: Path, tbgd_root: Path, rules: RuleBook) -> dict[str, dict[str, Any]]:
    ir = rules.ir
    raw_ability_sources = _raw_ability_source_matrix(tbgd_root)
    s0_matrix = build_p3_summon_source_inventory_matrix(tbgd_root, ir, rules)
    s1_matrix = build_p3_s1_contract_matrix(ir, rules, s0_matrix)
    s2_matrix = build_p3_s2_runtime_matrix(rules)
    raw_summon_monster = _raw_summon_monster_matrix(tbgd_root)
    s3_matrix = build_p3_s3_spawn_matrix(rules, raw_summon_monster)
    raw_summon_unit = _raw_summon_unit_matrix(tbgd_root)
    summon_unit_refs = _summon_unit_reference_matrix(tbgd_root, raw_summon_unit["summon_unit_ids"])
    s4_matrix = build_p3_s4_admission_matrix(rules, raw_summon_unit, summon_unit_refs)
    servant_definition = _select_executable_servant_definition(rules)
    summon_intent = _select_executable_summon_monster_intent(rules)
    assistant_source_matrix = _assistant_source_matrix(raw_ability_sources, ir, rules)
    global_target_config = _global_target_config(tbgd_root)
    target_state_bundle = _combined_summon_state(rules)
    enemy_ref = _select_enemy_entity(rules)

    s5_groups = {
        "servant_definition_matrix": _servant_definition_matrix(tbgd_root, rules),
        "servant_spawn_owner_lifecycle": _servant_spawn_owner_lifecycle_case(rules, servant_definition),
        "servant_negative_boundaries": _servant_negative_boundary_cases(rules, servant_definition),
    }
    s6_groups = {
        "servant_action_execution": _servant_action_execution_case(rules, servant_definition),
        "summoned_monster_action_boundary": _summoned_monster_action_boundary_case(rules, summon_intent),
        "executor_bypass_boundaries": _executor_bypass_boundary_cases(rules, servant_definition),
        "resource_pressure_boundary": _resource_pressure_boundary_case(rules, servant_definition),
    }
    s7_groups = {
        "assistant_source_layers": _assistant_source_layers_case(raw_ability_sources, assistant_source_matrix, rules),
        "assistant_queue_window_consistency": _assistant_queue_window_consistency_case(rules),
        "assistant_scope_negative_cases": _assistant_scope_negative_cases(rules),
        "assistant_queue_drain_boundary": _assistant_queue_drain_boundary_case(rules),
    }
    s8_groups = {
        "target_source_matrix": _target_source_matrix_case(raw_ability_sources, global_target_config, rules),
        "source_backed_positive_relations": _source_backed_positive_relations_case(rules, target_state_bundle),
        "target_relation_negative_cases": _target_relation_negative_cases(rules, target_state_bundle),
        "assistant_target_boundary": _assistant_target_boundary_case(raw_ability_sources, rules, target_state_bundle),
    }
    s9_groups = {
        "explicit_remove_cleanup": _explicit_remove_cleanup_case(rules, servant_definition),
        "owner_cleanup": _owner_cleanup_case(rules, servant_definition),
        "wave_clear_policy": _wave_clear_policy_case(rules, summon_intent),
    }
    s10_groups = {
        "servant_status_holder_positive": _servant_status_holder_case(rules, servant_definition),
        "servant_damage_stat_boundary": _servant_damage_stat_boundary_case(rules, servant_definition),
        "resource_ownership_boundary": _resource_ownership_boundary_case(rules, servant_definition),
        "kill_attribution_source_frame_boundary": _kill_attribution_source_frame_case(rules, servant_definition),
        "removed_summon_damage_negative": _removed_summon_damage_negative_case(rules, servant_definition),
        "source_matrix": _status_resource_damage_source_matrix_case(tbgd_root, rules),
    }
    s11_groups = {
        "initial_servant_route_execution": _initial_servant_route_execution_case(rules, servant_definition, enemy_ref),
        "initial_summon_blocked_boundary": _initial_summon_blocked_boundary_case(rules, servant_definition, enemy_ref),
        "illegal_damage_route_blocked": _illegal_damage_route_blocked_case(rules, servant_definition, enemy_ref),
        "missing_target_route_blocked": _missing_target_route_blocked_case(rules, servant_definition, enemy_ref),
    }

    return {
        "p3_s0_source_inventory": _stage_matrix_result(validate_p3_summon_source_inventory_matrix(s0_matrix), s0_matrix),
        "p3_s1_ir_rulebook_contract": _stage_matrix_result(validate_p3_s1_contract_matrix(s1_matrix), s1_matrix),
        "p3_s2_runtime_schema": _stage_matrix_result(validate_p3_s2_runtime_matrix(s2_matrix), s2_matrix),
        "p3_s3_summoned_monster_spawn": _stage_matrix_result(validate_p3_s3_spawn_matrix(s3_matrix), s3_matrix),
        "p3_s4_summon_unit_admission": _stage_matrix_result(validate_p3_s4_admission_matrix(s4_matrix), s4_matrix),
        "p3_s5_servant_lifecycle": _stage_group_result(s5_groups, _s5_summary(s5_groups)),
        "p3_s6_summon_action_execution": _stage_group_result(s6_groups, _s6_summary(s6_groups)),
        "p3_s7_assistant_queue_execution": _stage_group_result(s7_groups, _s7_summary(s7_groups, assistant_source_matrix)),
        "p3_s8_summon_target_relations": _stage_group_result(s8_groups, _s8_summary(s8_groups)),
        "p3_s9_summon_lifecycle_cleanup": _stage_group_result(s9_groups, _s9_summary(s9_groups)),
        "p3_s10_status_resource_damage": _stage_group_result(s10_groups, _s10_summary(s10_groups)),
        "p3_s11_battle_setup_scenario_route": _stage_group_result(s11_groups, _s11_summary(s11_groups)),
    }


def _stage_matrix_result(check: dict[str, Any], matrix: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(check["ok"]),
        "checks": check,
        "summary": matrix.get("summary", {}),
        "matrix_ref": matrix.get("schema_version", ""),
        "coverage_scope": matrix.get("coverage_scope", {}),
        "_matrix": matrix,
    }


def _stage_group_result(groups: dict[str, dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    failed = {
        name: [
            key
            for key, value in group.get("checks", {}).get("checks", {}).items()
            if value is False
        ]
        for name, group in groups.items()
        if not group.get("checks", {}).get("ok")
    }
    return {
        "ok": not failed,
        "summary": {**summary, "failed_group_count": len(failed), "failed_checks": failed},
        "case_group_count": len(groups),
        "_groups": groups,
    }


def _public_stage_results(stage_results: dict[str, dict[str, Any]]) -> dict[str, dict[str, JSONValue]]:
    public: dict[str, dict[str, JSONValue]] = {}
    for name, result in stage_results.items():
        public[name] = {
            "ok": bool(result.get("ok")),
            "summary": _compact_json(result.get("summary", {})),
        }
        if result.get("matrix_ref"):
            public[name]["matrix_ref"] = str(result.get("matrix_ref"))
        if result.get("coverage_scope"):
            public[name]["coverage_scope"] = _compact_json(result.get("coverage_scope", {}))
        if result.get("checks") and isinstance(result["checks"], dict):
            public[name]["checks"] = _compact_json(result["checks"])
    return public


def _build_final_source_matrix(stage_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    s0 = stage_results["p3_s0_source_inventory"]["_matrix"]
    s1 = stage_results["p3_s1_ir_rulebook_contract"]["_matrix"]
    s4 = stage_results["p3_s4_summon_unit_admission"]["_matrix"]
    s8 = stage_results["p3_s8_summon_target_relations"]["summary"]
    s10 = stage_results["p3_s10_status_resource_damage"]["summary"]
    domains = s0["domain_matrix"]
    contracts = s1["contract_groups"]
    rows: list[dict[str, JSONValue]] = []
    rows.extend(
        _source_rows_from_s0_domain(
            "summoned_monster_intent",
            "executable",
            domains["summoned_monster_intent"],
            "S3 executable spawn trace validates mutation, settlement, replay, source audit, target registry.",
            contracts["summon_monster_intent_contract"],
        )
    )
    rows.extend(
        _source_rows_from_s0_domain(
            "summon_unit_config_catalog",
            "boundary_only",
            domains["summon_unit_config_catalog"],
            "S4 proves SummonUnitData is definition/catalog only unless a separate battle runtime trigger is present.",
            contracts["summon_unit_definition_contract"],
        )
    )
    rows.append(
        {
            "source_domain": "battle_unit_summon_runtime_trigger",
            "source_slice": "runtime_trigger_absence",
            "classification": "source_absent_not_required",
            "raw_count": int(s4["summary"]["battle_runtime_trigger_ref_count"]),
            "ir_count": int(s4["summary"]["battle_runtime_trigger_ref_count"]),
            "rulebook_visible_count": 0,
            "gap_count": 0,
            "sample_source_trace": {},
            "evidence": "S4 reference scan found no battle runtime trigger refs; S11 initial battle_unit_summon is blocked/state unchanged.",
        }
    )
    rows.extend(
        _source_rows_from_s0_domain(
            "client_scene_adventure_summon",
            "source_absent_not_required",
            domains["client_scene_adventure_summon"],
            "S4 keeps client, visual, scene, adventure, and catalog summon outside combat runtime spawn.",
            None,
        )
    )
    rows.extend(
        _source_rows_from_s0_domain(
            "monster_summon_catalog_ref",
            "boundary_only",
            domains["monster_summon_catalog_ref"],
            "Monster catalog refs are discoverable metadata, not an executable runtime trigger.",
            None,
        )
    )
    rows.extend(
        _source_rows_from_s0_domain(
            "servant_definition",
            "executable",
            domains["servant_definition"],
            "S5/S6/S10/S11 validate servant spawn, owner relation, action, status holder, and BattleSetup route.",
            contracts["servant_definition_contract"],
        )
    )
    rows.extend(
        _source_rows_from_s0_domain(
            "servant_skill_and_ability_files",
            "executable",
            domains["servant_skill_and_ability_files"],
            "S6/S10 validate source-backed servant actions and keep unsupported damage stat paths blocked.",
            contracts["queue_lifecycle_and_action_admission_contract"],
        )
    )
    rows.extend(
        _source_rows_from_s0_domain(
            "summon_target_relations",
            "executable",
            domains["summon_target_expression"],
            f"S8 positive relation count={s8.get('positive_case_count', 0)}; AssistantAvatar relation is outside P3 summon/servant acceptance.",
            contracts["target_and_cross_system_source_trace_contract"],
        )
    )
    rows.extend(
        _source_rows_from_s0_domain(
            "summon_lifecycle_sources",
            "executable",
            domains["lifecycle_cleanup_and_actionability_sources"],
            "S9 validates explicit remove, owner cleanup, and wave clear policy boundary.",
            contracts["queue_lifecycle_and_action_admission_contract"],
        )
    )
    rows.append(
        {
            "source_domain": "summon_status_resource_damage",
            "source_slice": "servant_status_holder_positive_slice",
            "classification": "executable",
            "raw_count": int(s10.get("servant_damage_action_ir_count", 0)),
            "ir_count": int(s10.get("servant_damage_action_ir_count", 0)),
            "rulebook_visible_count": int(s10.get("servant_damage_action_ir_count", 0)),
            "gap_count": 0,
            "sample_source_trace": {},
            "evidence": "S10 validates servant status holder executable and keeps resource/damage stat gaps blocked without mutation.",
        }
    )
    classification_counts = Counter(row["classification"] for row in rows)
    return {
        "schema_version": "p3_summon_source_total_matrix_s12",
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "classification_counts": dict(sorted(classification_counts.items())),
            "unclassified_count": sum(1 for row in rows if row["classification"] == "unclassified"),
            "gap_count": sum(
                int(row.get("gap_count") or 1) for row in rows if row["classification"] in GAP_CLASSIFICATIONS
            ),
        },
    }


def _source_rows_from_s0_domain(
    domain: str,
    final_classification: str,
    s0_row: dict[str, Any],
    evidence: str,
    contract_group: dict[str, Any] | None,
) -> list[dict[str, JSONValue]]:
    rows: list[dict[str, JSONValue]] = []
    executable_count = int(s0_row.get("executable_count") or 0)
    gap_attribution = s0_row.get("gap_attribution", {})
    if not isinstance(gap_attribution, dict):
        gap_attribution = {}
    has_gap_attribution = any(
        gap_kind in GAP_CLASSIFICATIONS and int(count or 0) > 0 for gap_kind, count in gap_attribution.items()
    )
    if executable_count > 0:
        rows.append(
            _source_row(
                domain,
                "executable",
                s0_row,
                evidence,
                contract_group,
                source_slice="executable_positive_slice",
                raw_count=executable_count,
                ir_count=executable_count,
                gap_count=0,
            )
        )
    elif not has_gap_attribution:
        rows.append(
            _source_row(
                domain,
                final_classification,
                s0_row,
                evidence,
                contract_group,
                source_slice="domain_boundary_or_gap_slice",
                gap_count=int(s0_row.get("gap_count") or 0)
                if final_classification in GAP_CLASSIFICATIONS
                else 0,
            )
        )
    for gap_kind, count in sorted(gap_attribution.items()):
        if gap_kind not in GAP_CLASSIFICATIONS or int(count or 0) <= 0:
            continue
        rows.append(
            _source_row(
                domain,
                str(gap_kind),
                s0_row,
                "Inherited S0 sub-source gap attribution; executable positives in the same domain do not close these sub-items.",
                contract_group,
                source_slice=f"gap_attribution:{gap_kind}",
                raw_count=int(count),
                ir_count=0,
                rulebook_visible_count=0,
                gap_count=int(count),
            )
        )
    return rows


def _source_row(
    domain: str,
    classification: str,
    s0_row: dict[str, Any],
    evidence: str,
    contract_group: dict[str, Any] | None,
    *,
    source_slice: str,
    raw_count: int | None = None,
    ir_count: int | None = None,
    rulebook_visible_count: int | None = None,
    gap_count: int = 0,
) -> dict[str, JSONValue]:
    return {
        "source_domain": domain,
        "source_slice": source_slice,
        "classification": classification,
        "raw_count": int(s0_row.get("raw_count") or 0) if raw_count is None else int(raw_count),
        "ir_count": int(s0_row.get("ir_count") or 0) if ir_count is None else int(ir_count),
        "rulebook_visible_count": (
            int((contract_group or {}).get("rulebook_visible_count") or 0)
            if rulebook_visible_count is None
            else int(rulebook_visible_count)
        ),
        "gap_count": int(gap_count),
        "sample_source_trace": s0_row.get("sample_source_trace", {}),
        "evidence": evidence,
    }


def _build_final_mechanism_matrix(stage_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    s0_domains = stage_results["p3_s0_source_inventory"]["_matrix"]["domain_matrix"]
    s6 = stage_results["p3_s6_summon_action_execution"]["summary"]
    s8 = stage_results["p3_s8_summon_target_relations"]["summary"]
    s9 = stage_results["p3_s9_summon_lifecycle_cleanup"]["summary"]
    s10 = stage_results["p3_s10_status_resource_damage"]["summary"]
    s11 = stage_results["p3_s11_battle_setup_scenario_route"]["summary"]
    rows = [
        _mechanism_row("source_inventory", "executable", "S0 source domains classified and unclassified_count=0."),
        _mechanism_row("ir_rulebook_contract", "executable", "S1 confirms existing IR is visible through RuleBook."),
        _mechanism_row("summon_runtime_schema_v2", "executable", "S2 validates spawn/remove/cleanup registry replay."),
        _mechanism_row("summoned_monster_spawn", "executable", "S3 validates source-backed SummonMonster spawn."),
        _mechanism_row("summon_unit_runtime_spawn", "boundary_only", "S4/S11 keep SummonUnitData without battle trigger blocked."),
        _mechanism_row("servant_lifecycle_owner_stats", "executable", "S5 validates servant definition, owner relation, spawn and cleanup."),
        _mechanism_row(
            "servant_action_execution",
            str(s6["servant_action_graph_classification"]),
            "S6 validates executable action only when the complete selected graph commits; current candidates remain an inherited content gap.",
            s6,
        ),
        _mechanism_row("summoned_monster_action_execution", "boundary_only", "S6 keeps summoned monster action without actor graph blocked."),
        _mechanism_row("target_relations", "executable", "S8 validates summon/servant target aliases and negative boundaries.", s8),
        _mechanism_row("remove_owner_cleanup_wave", "executable", "S9 validates explicit remove, owner cleanup and wave policy.", s9),
        _mechanism_row("servant_status_holder", "executable", "S10 validates servant as status actor/target/holder.", s10),
        _mechanism_row("servant_damage_formula", "boundary_only", "S10 blocks HP damage action until stat source is admitted."),
        _mechanism_row("servant_resource_ownership", "source_absent_not_required", "S10 found no executable resource-costing servant action sample."),
        _mechanism_row("kill_attribution_source_frame", "executable", "S10 validates source-frame owner credit boundary."),
        _mechanism_row(
            "battle_setup_initial_servant",
            "executable",
            "S11 validates initial servant scenario setup and runtime registration independently of action-graph completeness.",
            s11,
        ),
        _mechanism_row("illegal_route_and_missing_target", "boundary_only", "S11 validates illegal summon action and missing target blocked."),
    ]
    rows.extend(_mechanism_gap_rows_from_s0("summoned_monster_source_subitems", s0_domains["summoned_monster_intent"]))
    rows.extend(_mechanism_gap_rows_from_s0("target_relation_source_subitems", s0_domains["summon_target_expression"]))
    rows.extend(
        _mechanism_gap_rows_from_s0(
            "lifecycle_actionability_source_subitems",
            s0_domains["lifecycle_cleanup_and_actionability_sources"],
        )
    )
    classification_counts = Counter(row["classification"] for row in rows)
    return {
        "schema_version": "p3_summon_mechanism_classification_matrix_s12",
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "classification_counts": dict(sorted(classification_counts.items())),
            "unclassified_count": sum(1 for row in rows if row["classification"] == "unclassified"),
            "gap_count": sum(
                int(row.get("gap_count") or 1) for row in rows if row["classification"] in GAP_CLASSIFICATIONS
            ),
        },
    }


def _mechanism_gap_rows_from_s0(mechanism_prefix: str, s0_row: dict[str, Any]) -> list[dict[str, JSONValue]]:
    gap_attribution = s0_row.get("gap_attribution", {})
    if not isinstance(gap_attribution, dict):
        return []
    rows: list[dict[str, JSONValue]] = []
    for gap_kind, count in sorted(gap_attribution.items()):
        if gap_kind not in GAP_CLASSIFICATIONS or int(count or 0) <= 0:
            continue
        rows.append(
            _mechanism_row(
                f"{mechanism_prefix}:{gap_kind}",
                str(gap_kind),
                "Inherited S0 mechanism sub-gap; positive executable samples do not close all source subitems.",
                summary={
                    "source_domain": s0_row.get("source_domain", ""),
                    "domain_classification": s0_row.get("classification", ""),
                    "raw_count": int(s0_row.get("raw_count") or 0),
                    "ir_count": int(s0_row.get("ir_count") or 0),
                },
                gap_count=int(count),
            )
        )
    return rows


def _mechanism_row(
    mechanism: str,
    classification: str,
    evidence: str,
    summary: dict[str, Any] | None = None,
    *,
    gap_count: int = 0,
) -> dict[str, JSONValue]:
    return {
        "mechanism": mechanism,
        "classification": classification,
        "gap_count": int(gap_count),
        "evidence": evidence,
        "summary": _compact_json(summary or {}),
    }


def _build_inherited_gap_matrix(stage_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, JSONValue]] = []
    rows.extend(_s0_inherited_gap_rows(stage_results["p3_s0_source_inventory"]["_matrix"]))
    rows.extend(_s1_inherited_gap_rows(stage_results["p3_s1_ir_rulebook_contract"]["_matrix"]))
    rows.extend(_s8_inherited_gap_rows(stage_results["p3_s8_summon_target_relations"]["_groups"]))
    s6 = stage_results["p3_s6_summon_action_execution"]["summary"]
    if s6.get("servant_action_graph_classification") == "implementation_missing":
        rows.append(
            _inherited_gap_row(
                stage="P3-S6/P3-S11",
                item_id="servant_action_graph",
                classification="implementation_missing",
                gap_count=1,
                evidence=(
                    "Action query/route candidates are inspected through CombatExecutor, but no complete selected servant "
                    "action graph is successor eligible; initial servant setup remains executable."
                ),
                details={
                    "s6": s6,
                    "s11": stage_results["p3_s11_battle_setup_scenario_route"]["summary"],
                },
            )
        )
    rows = [row for row in rows if not _scope_excluded_gap_row(row)]
    classification_counts = Counter(str(row["classification"]) for row in rows)
    gap_count = sum(int(row.get("gap_count") or 1) for row in rows if row["classification"] in GAP_CLASSIFICATIONS)
    return {
        "schema_version": "p3_summon_inherited_gap_matrix_s12",
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "gap_count": gap_count,
            "unclassified_count": sum(1 for row in rows if row["classification"] == "unclassified"),
            "classification_counts": dict(sorted(classification_counts.items())),
            "source": "inherited_from_step_matrices_without_renaming",
        },
    }


def _scope_excluded_gap_row(row: dict[str, JSONValue]) -> bool:
    item_id = str(row.get("item_id") or "")
    return (
        item_id.startswith("domain:assistant_ability_queue")
        or item_id.startswith("contract:assistant_resolution_contract")
        or item_id.startswith("assistant_target_boundary:")
    )


def _build_scope_exclusions(stage_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    s0_row = stage_results["p3_s0_source_inventory"]["_matrix"]["domain_matrix"]["assistant_ability_queue"]
    s1_group = stage_results["p3_s1_ir_rulebook_contract"]["_matrix"]["contract_groups"][
        "assistant_resolution_contract"
    ]
    s7_summary = stage_results["p3_s7_assistant_queue_execution"]["summary"]
    rows = [
        {
            "item_id": "assistant_avatar_ability_config",
            "classification": "out_of_scope",
            "p3_gap_count": 0,
            "raw_count": int(s0_row.get("raw_count") or 0),
            "ir_count": int(s0_row.get("ir_count") or 0),
            "rulebook_visible_count": int(s1_group.get("rulebook_visible_count") or 0),
            "s0_classification": str(s0_row.get("classification") or ""),
            "s1_classification": str(s1_group.get("classification") or ""),
            "s7_classification": str(s7_summary.get("classification") or ""),
            "evidence": (
                "TurnInsertAssistantAbility / AssistantAbilityResolutionIR belongs to the AssistantAvatar "
                "avatar-assistant ability system. It has no summon monster, UnitSpawn, servant lifecycle, "
                "or SummonUnit runtime entity semantics, so P3 summon/servant acceptance excludes it."
            ),
            "follow_up_owner": "future AssistantAvatar / avatar assistant ability queue work",
            "s7_summary": _compact_json(s7_summary),
        }
    ]
    return {
        "schema_version": "p3_summon_scope_exclusions_s12",
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "classification_counts": dict(sorted(Counter(row["classification"] for row in rows).items())),
            "assistant_avatar_excluded_from_p3_summon_acceptance": True,
            "all_scope_exclusions_classified": all(row["classification"] == "out_of_scope" for row in rows),
        },
    }


def _build_allowed_gap_evidence_matrix(inherited_gap_matrix: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, JSONValue]] = []
    allowed = {"admission_gap", "source_gap_blocked"}
    for row in inherited_gap_matrix.get("rows", []):
        classification = str(row.get("classification") or "unclassified")
        if classification not in GAP_CLASSIFICATIONS:
            continue
        details = row.get("details", {}) if isinstance(row.get("details"), dict) else {}
        gap_attribution = details.get("gap_attribution", {}) if isinstance(details.get("gap_attribution"), dict) else {}
        reason_tokens = details.get("gap_reason_token_counts", [])
        contract_details = details.get("contract_details", {}) if isinstance(details.get("contract_details"), dict) else {}
        evidence_sources = {
            "has_gap_attribution": bool(gap_attribution),
            "has_reason_token_counts": bool(reason_tokens),
            "has_contract_details": bool(contract_details),
            "has_evidence_text": bool(row.get("evidence")),
        }
        allowed_classification = classification in allowed
        evidence_ok = any(evidence_sources.values())
        rows.append(
            {
                "stage": str(row.get("stage") or ""),
                "item_id": str(row.get("item_id") or ""),
                "classification": classification,
                "gap_count": int(row.get("gap_count") or 1),
                "allowed_for_foundation_closure": allowed_classification,
                "evidence_ok": evidence_ok,
                "evidence_sources": evidence_sources,
                "details": _compact_json(details),
            }
        )
    classification_counts = Counter(str(row["classification"]) for row in rows)
    return {
        "schema_version": "p3_summon_allowed_gap_evidence_matrix_s12",
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "allowed_gap_count": sum(
                int(row.get("gap_count") or 1) for row in rows if row["allowed_for_foundation_closure"]
            ),
            "disallowed_gap_count": sum(
                int(row.get("gap_count") or 1) for row in rows if not row["allowed_for_foundation_closure"]
            ),
            "classification_counts": dict(sorted(classification_counts.items())),
            "all_evidence_ok": all(bool(row["evidence_ok"]) for row in rows),
        },
    }


def _s0_inherited_gap_rows(matrix: dict[str, Any]) -> list[dict[str, JSONValue]]:
    rows: list[dict[str, JSONValue]] = []
    for domain_id, row in sorted(matrix.get("domain_matrix", {}).items()):
        classification = str(row.get("classification") or "unclassified")
        if classification in GAP_CLASSIFICATIONS:
            rows.append(
                _inherited_gap_row(
                    stage="P3-S0",
                    item_id=f"domain:{domain_id}",
                    classification=classification,
                    gap_count=int(row.get("gap_count") or 1),
                    evidence=(
                        "S0 domain classification is a gap; final aggregation must not rename it. "
                        f"notes={row.get('notes', '')}"
                    ),
                    details={
                        "raw_count": int(row.get("raw_count") or 0),
                        "ir_count": int(row.get("ir_count") or 0),
                        "gap_attribution": row.get("gap_attribution", {}),
                        "gap_reason_layer_counts": row.get("gap_reason_layer_counts", {}),
                        "gap_reason_token_counts": row.get("gap_reason_token_counts", []),
                    },
                )
            )
        gap_attribution = row.get("gap_attribution", {}) if isinstance(row.get("gap_attribution"), dict) else {}
        for gap_kind, count in sorted(gap_attribution.items()):
            if gap_kind not in GAP_CLASSIFICATIONS or int(count or 0) <= 0:
                continue
            if classification in GAP_CLASSIFICATIONS and gap_kind == classification:
                continue
            filtered_tokens = _gap_reason_tokens_for_kind(row, str(gap_kind))
            rows.append(
                _inherited_gap_row(
                    stage="P3-S0",
                    item_id=f"domain:{domain_id}:gap_attribution:{gap_kind}",
                    classification=str(gap_kind),
                    gap_count=int(count),
                    evidence=(
                        "S0 domain contains unresolved sub-source gap attribution. "
                        "A source domain with executable positives cannot hide unresolved sub-items."
                    ),
                    details={
                        "domain_classification": classification,
                        "raw_count": int(row.get("raw_count") or 0),
                        "ir_count": int(row.get("ir_count") or 0),
                        "gap_reason_layer_counts": {str(gap_kind): sum(int(item.get("count") or 0) for item in filtered_tokens)},
                        "gap_reason_token_counts": filtered_tokens,
                    },
                )
            )
    return rows


def _gap_reason_tokens_for_kind(row: dict[str, Any], classification: str) -> list[dict[str, Any]]:
    tokens = row.get("gap_reason_token_counts", [])
    if not isinstance(tokens, list):
        return []
    return [
        dict(item)
        for item in tokens
        if isinstance(item, dict) and str(item.get("classification") or "") == classification
    ]


def _s1_inherited_gap_rows(matrix: dict[str, Any]) -> list[dict[str, JSONValue]]:
    rows: list[dict[str, JSONValue]] = []
    for group_id, group in sorted(matrix.get("contract_groups", {}).items()):
        classification = str(group.get("classification") or "unclassified")
        if classification in GAP_CLASSIFICATIONS:
            rows.append(
                _inherited_gap_row(
                    stage="P3-S1",
                    item_id=f"contract:{group_id}",
                    classification=classification,
                    gap_count=1,
                    evidence="S1 contract group classification is still a gap.",
                    details={
                        "raw_count": int(group.get("raw_count") or 0),
                        "ir_count": int(group.get("ir_count") or 0),
                        "rulebook_visible_count": int(group.get("rulebook_visible_count") or 0),
                        "gap_attribution": group.get("gap_attribution", {}),
                        "contract_details": group.get("details", {}),
                    },
                )
            )
        gap_attribution = group.get("gap_attribution", {}) if isinstance(group.get("gap_attribution"), dict) else {}
        for gap_kind, count in sorted(gap_attribution.items()):
            if gap_kind not in GAP_CLASSIFICATIONS or int(count or 0) <= 0:
                continue
            rows.append(
                _inherited_gap_row(
                    stage="P3-S1",
                    item_id=f"contract:{group_id}:gap_attribution:{gap_kind}",
                    classification=str(gap_kind),
                    gap_count=int(count),
                    evidence="S1 contract group carries unresolved gap attribution.",
                    details={"contract_classification": classification, "contract_details": group.get("details", {})},
                )
            )
    return rows


def _s8_inherited_gap_rows(groups: dict[str, dict[str, Any]]) -> list[dict[str, JSONValue]]:
    rows: list[dict[str, JSONValue]] = []
    source_matrix = groups.get("target_source_matrix", {})
    for row in source_matrix.get("rows", []):
        classification = str(row.get("classification") or "unclassified")
        if classification not in GAP_CLASSIFICATIONS:
            continue
        rows.append(
            _inherited_gap_row(
                stage="P3-S8",
                item_id=f"target:{row.get('kind', '')}:{row.get('name', '')}",
                classification=classification,
                gap_count=1,
                evidence="S8 target source row is still classified as a gap.",
                details={
                    "raw_count": int(row.get("raw_count") or 0),
                    "global_config_count": int(row.get("global_config_count") or 0),
                    "ir_count": int(row.get("ir_count") or 0),
                    "executable_count": int(row.get("executable_count") or 0),
                },
            )
        )
    assistant_boundary = groups.get("assistant_target_boundary", {})
    boundary_classification = str(assistant_boundary.get("classification") or "")
    if boundary_classification in GAP_CLASSIFICATIONS:
        rows.append(
            _inherited_gap_row(
                stage="P3-S8",
                item_id="assistant_target_boundary:FriendServantSelect",
                classification=boundary_classification,
                gap_count=1,
                evidence="S8 assistant target boundary remains a gap and cannot be renamed to boundary_only in S12.",
                details={
                    "raw_count": int(assistant_boundary.get("raw_count") or 0),
                    "ir_count": int(assistant_boundary.get("ir_count") or 0),
                    "executable_count": int(assistant_boundary.get("executable_count") or 0),
                },
            )
        )
    return rows


def _inherited_gap_row(
    *,
    stage: str,
    item_id: str,
    classification: str,
    gap_count: int,
    evidence: str,
    details: dict[str, Any],
) -> dict[str, JSONValue]:
    return {
        "stage": stage,
        "item_id": item_id,
        "classification": classification,
        "gap_count": int(gap_count),
        "evidence": evidence,
        "details": _compact_json(details),
    }


def _build_positive_samples(stage_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    groups = _all_groups(stage_results)
    samples = [
        _sample("summoned_monster_spawn", "executable", groups["p3_s3_summoned_monster_spawn"]["executable_spawn_trace"]),
        _sample("runtime_summoned_monster", "executable", groups["p3_s2_runtime_schema"]["summoned_monster_runtime"]),
        _sample("servant_spawn_lifecycle", "executable", groups["p3_s5_servant_lifecycle"]["servant_spawn_owner_lifecycle"]),
        _sample("target_positive_relations", "executable", groups["p3_s8_summon_target_relations"]["source_backed_positive_relations"]),
        _sample("explicit_remove_cleanup", "executable", groups["p3_s9_summon_lifecycle_cleanup"]["explicit_remove_cleanup"]),
        _sample("servant_status_holder", "executable", groups["p3_s10_status_resource_damage"]["servant_status_holder_positive"]),
        _sample("battle_setup_initial_servant", "executable", groups["p3_s11_battle_setup_scenario_route"]["initial_servant_route_execution"]),
    ]
    return _sample_set("p3_positive_samples_s12", samples)


def _build_blocked_samples(stage_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    groups = _all_groups(stage_results)
    samples = [
        _sample("summon_unit_runtime_boundary", "boundary_only", groups["p3_s4_summon_unit_admission"]["runtime_blocked_boundary"]),
        _sample("servant_negative_boundaries", "boundary_only", groups["p3_s5_servant_lifecycle"]["servant_negative_boundaries"]),
        _sample("executor_bypass_boundaries", "boundary_only", groups["p3_s6_summon_action_execution"]["executor_bypass_boundaries"]),
        _sample("target_relation_negative", "boundary_only", groups["p3_s8_summon_target_relations"]["target_relation_negative_cases"]),
        _sample("damage_stat_boundary", "boundary_only", groups["p3_s10_status_resource_damage"]["servant_damage_stat_boundary"]),
        _sample("initial_battle_unit_summon_boundary", "boundary_only", groups["p3_s11_battle_setup_scenario_route"]["initial_summon_blocked_boundary"]),
        _sample("missing_target_route", "boundary_only", groups["p3_s11_battle_setup_scenario_route"]["missing_target_route_blocked"]),
    ]
    return _sample_set("p3_blocked_samples_s12", samples)


def _build_audit_samples(stage_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    groups = _all_groups(stage_results)
    rows = [
        _audit_row("explicit_remove_cleanup", groups["p3_s9_summon_lifecycle_cleanup"]["explicit_remove_cleanup"]),
        _audit_row("owner_cleanup", groups["p3_s9_summon_lifecycle_cleanup"]["owner_cleanup"]),
        _audit_row("servant_status_holder", groups["p3_s10_status_resource_damage"]["servant_status_holder_positive"]),
    ]
    return {
        "schema_version": "p3_source_audit_samples_s12",
        "rows": rows,
        "summary": {"sample_count": len(rows), "all_ok": all(row["ok"] for row in rows)},
    }


def _build_replay_samples(stage_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    groups = _all_groups(stage_results)
    rows = [
        _replay_row("summoned_monster_runtime", groups["p3_s2_runtime_schema"]["summoned_monster_runtime"]),
        _replay_row("summoned_monster_spawn", groups["p3_s3_summoned_monster_spawn"]["executable_spawn_trace"]),
        _replay_row("servant_spawn_lifecycle", groups["p3_s5_servant_lifecycle"]["servant_spawn_owner_lifecycle"]),
        _replay_row("explicit_remove_cleanup", groups["p3_s9_summon_lifecycle_cleanup"]["explicit_remove_cleanup"]),
        _replay_row("owner_cleanup", groups["p3_s9_summon_lifecycle_cleanup"]["owner_cleanup"]),
        _replay_row("servant_status_holder", groups["p3_s10_status_resource_damage"]["servant_status_holder_positive"]),
    ]
    return {
        "schema_version": "p3_replay_samples_s12",
        "rows": rows,
        "summary": {"sample_count": len(rows), "all_ok": all(row["ok"] for row in rows)},
    }


def _sample_set(schema_version: str, samples: list[dict[str, JSONValue]]) -> dict[str, Any]:
    classification_counts = Counter(sample["classification"] for sample in samples)
    return {
        "schema_version": schema_version,
        "samples": samples,
        "summary": {
            "sample_count": len(samples),
            "classification_counts": dict(sorted(classification_counts.items())),
            "all_checks_ok": all(sample["ok"] for sample in samples),
        },
    }


def _sample(sample_id: str, classification: str, group: dict[str, Any]) -> dict[str, JSONValue]:
    return {
        "sample_id": sample_id,
        "classification": classification,
        "ok": bool(group.get("checks", {}).get("ok")),
        "group_classification": str(group.get("classification") or ""),
        "checks": _compact_json(group.get("checks", {}).get("checks", {})),
        "evidence": _compact_json(_sample_evidence(group)),
    }


def _sample_evidence(group: dict[str, Any]) -> dict[str, JSONValue]:
    keys = (
        "action_id",
        "intent_id",
        "servant_definition_id",
        "servant_unit_id",
        "spawned_unit_ids",
        "blocked_reason",
        "negative_case_count",
        "positive_case_count",
        "mutation_count",
        "record_types",
        "classification",
        "coverage",
        "replay",
        "source_audit",
    )
    return {key: group[key] for key in keys if key in group}


def _audit_row(sample_id: str, group: dict[str, Any]) -> dict[str, JSONValue]:
    audit = group.get("source_audit", {})
    return {
        "sample_id": sample_id,
        "ok": bool(audit.get("ok")),
        "checked_mutations": int(audit.get("checked_mutations") or 0),
        "checked_records": int(audit.get("checked_records") or 0),
        "violations": _compact_json(audit.get("violations", [])),
    }


def _replay_row(sample_id: str, group: dict[str, Any]) -> dict[str, JSONValue]:
    replay = group.get("replay", {})
    ok = bool(replay.get("ok")) if isinstance(replay, dict) else False
    if sample_id == "servant_spawn_lifecycle" and isinstance(replay, dict):
        ok = bool(replay.get("spawn_ok")) and bool(replay.get("cleanup_ok"))
    return {
        "sample_id": sample_id,
        "ok": ok,
        "replay": _compact_json(replay),
    }


def _all_groups(stage_results: dict[str, dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    grouped = {}
    for name, result in stage_results.items():
        if "_groups" in result:
            grouped[name] = result["_groups"]
        elif "_matrix" in result:
            grouped[name] = result["_matrix"].get("case_groups", {})
    return grouped


def _gap_counts(*row_groups: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter({key: 0 for key in GAP_CLASSIFICATIONS})
    for rows in row_groups:
        for row in rows:
            classification = str(row.get("classification") or "unclassified")
            if classification in GAP_CLASSIFICATIONS:
                counts[classification] += int(row.get("gap_count") or 1)
    return counts


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


def _s5_summary(groups: dict[str, dict[str, Any]]) -> dict[str, Any]:
    matrix = groups["servant_definition_matrix"]
    return {
        "definition_count": matrix["definition_count"],
        "raw_count": matrix["raw_count"],
        "executable_definition_count": matrix["executable_definition_count"],
        "negative_case_count": groups["servant_negative_boundaries"]["negative_case_count"],
        "spawn_replay_ok": groups["servant_spawn_owner_lifecycle"]["replay"]["spawn_ok"],
        "cleanup_replay_ok": groups["servant_spawn_owner_lifecycle"]["replay"]["cleanup_ok"],
    }


def _s6_summary(groups: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "servant_action_graph_classification": groups["servant_action_execution"]["classification"],
        "servant_action_enabled": groups["servant_action_execution"]["transition_coverage"].get("action_enabled") is True,
        "servant_action_mutation_count": groups["servant_action_execution"]["mutation_count"],
        "servant_action_replay_ok": groups["servant_action_execution"]["replay"]["ok"],
        "servant_action_source_audit_ok": groups["servant_action_execution"]["source_audit"]["ok"],
        "summoned_monster_action_classification": groups["summoned_monster_action_boundary"]["classification"],
        "negative_case_count": groups["executor_bypass_boundaries"]["negative_case_count"],
        "resource_pressure_classification": groups["resource_pressure_boundary"]["classification"],
    }


def _s7_summary(groups: dict[str, dict[str, Any]], source_matrix: dict[str, Any]) -> dict[str, Any]:
    return {
        "assistant_raw_count": source_matrix["raw_count"],
        "assistant_queue_intent_ir_count": source_matrix["queue_intent_ir_count"],
        "assistant_resolution_ir_count": source_matrix["assistant_resolution_ir_count"],
        "assistant_queue_window_ir_count": source_matrix["assistant_queue_window_ir_count"],
        "classification": groups["assistant_source_layers"]["classification"],
        "negative_case_count": groups["assistant_scope_negative_cases"]["negative_case_count"],
        "queue_drain_classification": groups["assistant_queue_drain_boundary"]["classification"],
    }


def _s8_summary(groups: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "classification_counts": groups["target_source_matrix"]["classification_counts"],
        "positive_case_count": groups["source_backed_positive_relations"]["positive_case_count"],
        "negative_case_count": groups["target_relation_negative_cases"]["negative_case_count"],
        "assistant_boundary_classification": groups["assistant_target_boundary"]["classification"],
    }


def _s9_summary(groups: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "explicit_remove_source_audit_ok": groups["explicit_remove_cleanup"]["source_audit"]["ok"],
        "explicit_remove_replay_ok": groups["explicit_remove_cleanup"]["replay"]["ok"],
        "owner_cleanup_source_audit_ok": groups["owner_cleanup"]["source_audit"]["ok"],
        "owner_cleanup_replay_ok": groups["owner_cleanup"]["replay"]["ok"],
        "real_wave_policy": groups["wave_clear_policy"]["real_wave_policy"],
        "real_wave_decision": groups["wave_clear_policy"]["real_plan"]["status"],
    }


def _s10_summary(groups: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "status_positive_action_id": groups["servant_status_holder_positive"]["action_id"],
        "status_positive_replay_ok": groups["servant_status_holder_positive"]["replay"]["ok"],
        "status_positive_source_audit_ok": groups["servant_status_holder_positive"]["source_audit"]["ok"],
        "damage_boundary_reason": groups["servant_damage_stat_boundary"]["coverage"].get(
            "summon_damage_stat_blocked_reason",
            "",
        ),
        "kill_attribution_owner": groups["kill_attribution_source_frame_boundary"]["defeat_payload"].get(
            "kill_credit_owner_id", ""
        ),
        "servant_damage_action_ir_count": groups["source_matrix"]["servant_hp_damage_action_ir_count"],
    }


def _s11_summary(groups: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "initial_servant_setup_classification": groups["initial_servant_route_execution"].get(
            "setup_classification",
            "executable",
        ),
        "servant_route_action_graph_classification": groups["initial_servant_route_execution"]["classification"],
        "route_action_id": groups["initial_servant_route_execution"]["command"]["action_id"],
        "route_replay_ok": groups["initial_servant_route_execution"]["replay"]["ok"],
        "route_source_audit_ok": groups["initial_servant_route_execution"]["source_audit"]["ok"],
        "initial_blocked_reason": groups["initial_summon_blocked_boundary"]["blocked_reason"],
        "illegal_damage_route_reason": groups["illegal_damage_route_blocked"]["coverage"].get(
            "summon_damage_stat_blocked_reason",
            "",
        ),
        "missing_target_route_reason": groups["missing_target_route_blocked"]["coverage"].get(
            "blocked_reason",
            "",
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
