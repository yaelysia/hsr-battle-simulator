from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .io import write_json
from .p7_evidence import (
    current_regression_structured_check_contract,
    current_regression_structured_check_negative_cases,
    source_tree_fingerprint,
)
from .static_checks import run_static_checks
from .validate_p7_s0_kernel_trust_baseline import EXPECTED_ISSUE_IDS, ISSUE_SPECS


VALIDATION_VERSION = "p7_s19_kernel_invariant_aggregate"


ISSUE_ROWS: tuple[dict[str, Any], ...] = (
    {"issue_id": "P7-I01", "stages": ("s1", "s3"), "code": ("core/transition_contract.py", "core/atomic_commit.py"), "validator": "validate_p7_s3_selected_graph_atomic_commit.py", "negative": "incomplete_selected_node_state_unchanged"},
    {"issue_id": "P7-I02", "stages": ("s6",), "code": ("systems/action_contract.py", "systems/action_availability.py"), "validator": "validate_p7_s6_action_ownership_window_contract.py", "negative": "non_owned_role_or_window_submission_blocked"},
    {"issue_id": "P7-I03", "stages": ("s8",), "code": ("systems/decision.py", "systems/scheduler.py"), "validator": "validate_p7_s8_decision_query_submit_loop.py", "negative": "query_is_idempotent_and_does_not_begin_turn_twice"},
    {"issue_id": "P7-I04", "stages": ("s8",), "code": ("systems/enemy_action.py", "systems/decision.py"), "validator": "validate_p7_s8_decision_query_submit_loop.py", "negative": "enemy_choice_not_selected_inside_core"},
    {"issue_id": "P7-I05", "stages": ("s7",), "code": ("systems/target.py", "systems/action_preflight.py"), "validator": "validate_p7_s7_target_selection_impact_contract.py", "negative": "single_target_cardinality_and_relation_rejected"},
    {"issue_id": "P7-I06", "stages": ("s9",), "code": ("systems/phase_machine.py", "systems/scheduler.py"), "validator": "validate_p7_s9_explicit_turn_event_phase_machine.py", "negative": "event_or_operation_outside_phase_blocked"},
    {"issue_id": "P7-I07", "stages": ("s10",), "code": ("systems/timeline.py", "systems/scheduler.py"), "validator": "validate_p7_s10_timeline_control_semantics.py", "negative": "controlled_turn_consumed_once_with_progress"},
    {"issue_id": "P7-I08", "stages": ("s10",), "code": ("systems/timeline.py", "systems/action_availability.py"), "validator": "validate_p7_s10_timeline_control_semantics.py", "negative": "remaining_action_value_and_typed_tie_choice_round_trip"},
    {"issue_id": "P7-I09", "stages": ("s13",), "code": ("systems/shield.py", "systems/damage.py"), "validator": "validate_p7_s13_shield_hp_routing.py", "negative": "shield_absorbs_before_hp_and_hp_loss_bypasses"},
    {"issue_id": "P7-I10", "stages": ("s12",), "code": ("systems/damage_pipeline.py", "systems/damage.py"), "validator": "validate_p7_s12_damage_toughness_pipeline.py", "negative": "damage_family_stage_applicability_is_explicit"},
    {"issue_id": "P7-I11", "stages": ("s12",), "code": ("systems/damage_pipeline.py", "core/executor.py"), "validator": "validate_p7_s12_damage_toughness_pipeline.py", "negative": "before_event_state_is_reloaded_before_calculation"},
    {"issue_id": "P7-I12", "stages": ("s2",), "code": ("core/reducer.py",), "validator": "validate_p7_s2_mutation_reducer_contract.py", "negative": "before_op_and_same_path_conflicts_are_atomic"},
    {"issue_id": "P7-I13", "stages": ("s14",), "code": ("systems/status.py",), "validator": "validate_p7_s14_status_application_admission.py", "negative": "multiply_hit_and_resistance_terms_before_final_probability_clamp"},
    {"issue_id": "P7-I14", "stages": ("s3", "s14"), "code": ("core/atomic_commit.py", "systems/status.py"), "validator": "validate_p7_s14_status_application_admission.py", "negative": "unsupported_status_is_partial_no_mutation"},
    {"issue_id": "P7-I15", "stages": ("s15",), "code": ("systems/rng.py", "systems/target.py", "core/executor.py"), "validator": "validate_p7_s15_rng_identity_replay.py", "negative": "random_target_identity_includes_action_task_hit_and_initial_target_events_enter_ledger"},
    {"issue_id": "P7-I16", "stages": ("s4",), "code": ("core/source_audit.py", "rules/engine_rule_registry.py"), "validator": "validate_p7_s4_rule_audit_separation.py", "negative": "runtime_behavior_independent_of_source_trace"},
    {"issue_id": "P7-I17", "stages": ("s5",), "code": ("rules/expression_ir.py", "tbgd/expression_lowering.py"), "validator": "validate_p7_s5_typed_expression_ir.py", "negative": "raw_expression_not_executed_at_runtime"},
    {"issue_id": "P7-I18", "stages": ("s4", "s5", "s14"), "code": ("systems/status.py", "rules/evaluator.py"), "validator": "validate_p7_s14_status_application_admission.py", "negative": "ambiguous_definition_or_binding_blocked"},
    {"issue_id": "P7-I19", "stages": ("s11",), "code": ("systems/queue.py", "systems/scheduler.py"), "validator": "validate_p7_s11_queue_terminal_progress.py", "negative": "invalid_head_terminalizes_or_blocks_without_livelock"},
    {"issue_id": "P7-I20", "stages": ("s16",), "code": ("systems/summon.py", "systems/unit_lifecycle.py", "tbgd/lowering.py"), "validator": "validate_p7_s16_in_combat_summon_lifecycle.py", "negative": "typed_replacement_policy_atomically_replaces_defeated_servant_without_audit_rule_input"},
    {"issue_id": "P7-I21", "stages": ("s9", "s17"), "code": ("systems/wave.py", "systems/event_dispatch.py"), "validator": "validate_p7_s17_wave_lifecycle_events.py", "negative": "missing_wave_event_payload_rolls_back_transition"},
    {"issue_id": "P7-I22", "stages": ("s4",), "code": ("rules/engine_rule_registry.py", "systems/resource.py"), "validator": "validate_p7_s4_rule_audit_separation.py", "negative": "unregistered_engine_convention_not_executable"},
    {"issue_id": "P7-I23", "stages": ("s18",), "code": ("core/compact_state.py",), "validator": "validate_p7_s18_compact_semantic_state.py", "negative": "equal_compact_keys_require_equal_timeline_summon_wave_and_action_query_behavior"},
    {"issue_id": "P7-I24", "stages": ("s0", "s19"), "code": ("tools/static_checks.py",), "validator": "validate_p7_s19_kernel_invariant_aggregate.py", "negative": "all_twenty_four_invariants_have_unique_evidence_rows"},
)


ISSUE_EVIDENCE_PREDICATES: dict[str, tuple[tuple[str, str], ...]] = {
    "P7-I01": (("s1", "checks.contradictory_outcomes_rejected"), ("s3", "checks.mid_task_failure_is_atomic")),
    "P7-I02": (("s6", "checks.forged_action_authorization_blocked"), ("s6", "checks.blocked_submissions_state_unchanged")),
    "P7-I03": (("s8", "checks.query_is_idempotent"), ("s8", "checks.stale_token_blocked_state_unchanged")),
    "P7-I04": (("s8", "checks.no_scheduler_enemy_auto_selection"), ("s8", "checks.direct_scheduler_command_requires_token")),
    "P7-I05": (("s7", "checks.single_primary_contract"), ("s7", "checks.targetability_negatives_blocked")),
    "P7-I06": (("s9", "checks.corrupt_current_phase_blocked_state_unchanged"), ("s9", "checks.regular_turn_phase_path_complete")),
    "P7-I07": (("s10", "checks.controlled_turn_consumed_and_scheduler_progresses"),),
    "P7-I08": (("s10", "checks.tie_requires_sourced_priority_or_explicit_choice"), ("s10", "checks.speed_change_preserves_elapsed_progress")),
    "P7-I09": (("s13", "checks.full_absorption.ok"), ("s13", "checks.hp_loss_bypass.ok"), ("s13", "checks.forged_route_rule_blocked.ok")),
    "P7-I10": (("s12", "checks.all_damage_families_use_staged_pipeline"), ("s12", "checks.applied_and_skipped_terms_present")),
    "P7-I11": (("s12", "checks.before_event_reloads_updated_state"),),
    "P7-I12": (("s2", "checks.wrong_before_rolls_back_entire_batch"), ("s2", "checks.same_path_requires_continuous_before")),
    "P7-I13": (("s14", "checks.multiply_before_clamp.ok"), ("s14", "checks.base_chance_above_one.ok")),
    "P7-I14": (("s3", "checks.status_partial_activation_is_atomic"), ("s14", "checks.partial_no_mutation_gate.ok")),
    "P7-I15": (("s15", "checks.real_damage_multi_hit_identity.ok"), ("s15", "checks.executor_initial_target_ledger.ok")),
    "P7-I16": (("s4", "checks.complete_vs_minimal_audit_execution_equivalent"), ("s4", "checks.p7_i16_behavior_reads_absent")),
    "P7-I17": (("s5", "checks.runtime_raw_expression_parsers_absent"), ("s5", "checks.target_typed_positive")),
    "P7-I18": (("s5", "checks.ambiguous_reference_has_no_runtime_mutation"), ("s14", "checks.typed_program_numeric_fields.ok")),
    "P7-I19": (("s11", "checks.invalid_head_removed_then_valid_entry_executes"), ("s11", "checks.standalone_ability_partial_has_no_published_mutation")),
    "P7-I20": (("s16", "checks.owner_cleanup.replacement_policy_real_source"), ("s16", "checks.owner_cleanup.replacement_replay_ok")),
    "P7-I21": (("s17", "rows.event_payload_negative.ok"), ("s17", "rows.real_two_wave_advance.ok")),
    "P7-I22": (("s4", "checks.engine_registry_missing_rule_state_unchanged"),),
    "P7-I23": (("s18", "rows.audit_trim_behavior_equivalence.queue_behavior_equal"), ("s18", "rows.semantic_non_equivalence.ok")),
    "P7-I24": (("aggregate", "issue_ids_unique"), ("aggregate", "issue_ids_contiguous"), ("aggregate", "all_issues_bound_to_runtime_predicates")),
}


STAGE_REPORTS = {
    "s0": "v8_p7_s0_kernel_trust_baseline_ready_for_review.md",
    "s1": "v8_p7_s1_transition_trust_contract_ready_for_review.md",
    "s2": "v8_p7_s2_mutation_reducer_contract_ready_for_review.md",
    "s3": "v8_p7_s3_selected_graph_atomic_commit_ready_for_review.md",
    "s4": "v8_p7_s4_rule_audit_separation_ready_for_review.md",
    "s5": "v8_p7_s5_typed_expression_ir_ready_for_review.md",
    "s6": "v8_p7_s6_action_ownership_window_contract_ready_for_review.md",
    "s7": "v8_p7_s7_target_selection_impact_contract_ready_for_review.md",
    "s8": "v8_p7_s8_decision_query_submit_loop_ready_for_review.md",
    "s9": "v8_p7_s9_explicit_turn_event_phase_machine_ready_for_review.md",
    "s10": "v8_p7_s10_timeline_control_semantics_ready_for_review.md",
    "s11": "v8_p7_s11_queue_terminal_progress_ready_for_review.md",
    "s12": "v8_p7_s12_damage_toughness_pipeline_ready_for_review.md",
    "s13": "v8_p7_s13_shield_hp_routing_ready_for_review.md",
    "s14": "v8_p7_s14_status_application_admission_ready_for_review.md",
    "s15": "v8_p7_s15_rng_identity_replay_ready_for_review.md",
    "s16": "v8_p7_s16_in_combat_summon_lifecycle_ready_for_review.md",
    "s17": "v8_p7_s17_wave_lifecycle_events_ready_for_review.md",
    "s18": "v8_p7_s18_compact_semantic_state_ready_for_review.md",
}


STAGE_REQUIRED_PREDICATES: dict[str, tuple[str, ...]] = {
    "s1": (
        "checks.committed_successor_eligible",
        "checks.blocked_not_successor_eligible",
        "checks.diagnostic_not_successor_eligible",
        "checks.no_selected_target_is_blocked",
        "checks.contradictory_outcomes_rejected",
        "checks.scheduler_outcomes_explicit",
    ),
    "s2": (
        "checks.wrong_before_rolls_back_entire_batch",
        "checks.same_path_requires_continuous_before",
        "checks.invalid_op_is_rejected",
        "checks.mutation_and_applied_state_reject_alias_pollution",
        "checks.replay_checks_before_order_after_and_types",
        "checks.snapshot_replay_direct_regression",
    ),
    "s3": (
        "checks.mid_task_failure_is_atomic",
        "checks.callback_mid_failure_is_atomic",
        "checks.status_partial_activation_is_atomic",
        "checks.reducer_conflict_is_atomic_and_structured",
        "checks.complete_multi_node_commits_once",
    ),
    "s4": (
        "checks.complete_vs_minimal_audit_execution_equivalent",
        "checks.unit_spawn_audit_trim_equivalent",
        "checks.callback_order_audit_trim_equivalent",
        "checks.servant_replacement_audit_trim_equivalent",
        "checks.wave_payload_audit_trim_equivalent",
        "checks.break_recovery_audit_trim_equivalent",
        "checks.p7_i16_behavior_reads_absent",
        "checks.engine_registry_missing_rule_state_unchanged",
    ),
    "s5": (
        "checks.target_typed_positive",
        "checks.numeric_typed_positive",
        "checks.condition_typed_positive",
        "checks.runtime_raw_expression_parsers_absent",
        "checks.ambiguous_reference_has_no_runtime_mutation",
    ),
    "s6": (
        "checks.forged_action_authorization_blocked",
        "checks.tampered_issued_authorization_blocked",
        "checks.issued_insert_authorization_committed",
        "checks.unqueried_direct_submissions_blocked",
        "checks.blocked_submissions_state_unchanged",
    ),
    "s7": (
        "checks.single_primary_contract",
        "checks.blast_impact_derived",
        "checks.aoe_auto_impact_derived",
        "checks.targetability_negatives_blocked",
        "checks.executor_negatives_state_unchanged",
    ),
    "s8": (
        "checks.query_is_idempotent",
        "checks.every_exposed_action_target_combination_submits",
        "checks.stale_token_blocked_state_unchanged",
        "checks.direct_scheduler_command_requires_token",
        "checks.no_scheduler_enemy_auto_selection",
    ),
    "s9": (
        "checks.regular_turn_phase_path_complete",
        "checks.dot_lifecycle_before_decision_and_action",
        "checks.extra_action_does_not_repeat_regular_turn",
        "checks.corrupt_current_phase_blocked_state_unchanged",
        "checks.wave_phase_mutations_source_audit_ok",
    ),
    "s10": (
        "checks.speed_change_preserves_elapsed_progress",
        "checks.tie_requires_sourced_priority_or_explicit_choice",
        "checks.controlled_turn_consumed_and_scheduler_progresses",
        "checks.advance_delay_immediate_share_adjustment_contract",
    ),
    "s11": (
        "checks.invalid_head_removed_then_valid_entry_executes",
        "checks.child_diagnostic_has_no_partial_mutation_and_entry_removed",
        "checks.standalone_ability_partial_has_no_published_mutation",
        "checks.wait_and_retarget_require_typed_admission",
        "checks.queue_policy_audit_trim_preserves_behavior",
    ),
    "s12": (
        "checks.all_damage_families_use_staged_pipeline",
        "checks.non_direct_pipeline_applies_status_modifier_terms",
        "checks.before_event_reloads_updated_state",
        "checks.applied_and_skipped_terms_present",
        "checks.damage_formula_rules_versioned_and_shared",
    ),
    "s13": (
        "checks.full_absorption.ok",
        "checks.partial_absorption.ok",
        "checks.same_effect_different_casters.ok",
        "checks.shield_exhaustion_event.ok",
        "checks.hp_loss_bypass.ok",
        "checks.forged_route_rule_blocked.ok",
        "checks.forged_priority_rule_blocked.ok",
        "checks.versioned_route_registry.ok",
        "checks.missing_canonical_route_blocked.ok",
    ),
    "s14": (
        "checks.guaranteed_application.ok",
        "checks.ordinary_debuff.ok",
        "checks.control_status.ok",
        "checks.multiply_before_clamp.ok",
        "checks.base_chance_above_one.ok",
        "checks.partial_no_mutation_gate.ok",
        "checks.typed_program_numeric_fields.ok",
    ),
    "s15": (
        "checks.same_target_multi_hit.ok",
        "checks.target_runtime_identity.ok",
        "checks.executor_initial_target_ledger.ok",
        "checks.duplicate_consumed_identity.ok",
        "checks.deterministic_replay.ok",
        "checks.real_damage_multi_hit_identity.ok",
    ),
    "s16": (
        "checks.in_combat_spawn.ok",
        "checks.presence_target_timeline.ok",
        "checks.owner_cleanup.replacement_policy_real_source",
        "checks.owner_cleanup.replacement_policy_audit_clear_behavior_equal",
        "checks.owner_cleanup.replacement_replay_ok",
        "checks.summon_action_source.ok",
    ),
    "s17": (
        "rows.initial_wave_start.ok",
        "rows.real_two_wave_advance.ok",
        "rows.battle_complete.ok",
        "rows.event_payload_negative.ok",
        "rows.source_and_residual_negative.audit_trace_expansion_does_not_change_wave_plan",
        "rows.source_and_residual_negative.definition_and_entry_audit_clear_does_not_change_wave_plan",
    ),
    "s18": (
        "rows.semantic_equivalence.ok",
        "rows.semantic_non_equivalence.ok",
        "rows.audit_trim_behavior_equivalence.compact_keys_equal",
        "rows.audit_trim_behavior_equivalence.timeline_behavior_equal",
        "rows.audit_trim_behavior_equivalence.summon_behavior_equal",
        "rows.audit_trim_behavior_equivalence.wave_behavior_equal",
        "rows.audit_trim_behavior_equivalence.action_query_behavior_equal",
        "rows.audit_trim_behavior_equivalence.queue_behavior_equal",
        "rows.round_trip_and_readonly.ok",
        "rows.serialization_budget.ok",
    ),
}


def run_validation(
    package_root: Path,
    regression_root: Path,
    output_dir: Path,
    stage_evidence_manifest: Path,
    current_regression_manifest: Path,
) -> dict[str, Any]:
    hsr_root = package_root.parent
    reports_root = hsr_root / "live_validation_reports"
    tools_root = package_root / "tools"
    static = run_static_checks(package_root)
    stage_validation_evidence = _stage_validation_evidence(package_root, stage_evidence_manifest)
    current_regressions = _current_shared_regression_evidence(package_root, current_regression_manifest)
    structured_check_negatives = current_regression_structured_check_negative_cases(
        _current_regression_summary_checks
    )
    stale_evidence_negative = _stale_p4_p6_replacement_negative(
        package_root,
        current_regression_manifest,
    )

    report_checks: dict[str, dict[str, Any]] = {}
    for stage, filename in STAGE_REPORTS.items():
        path = reports_root / filename
        content = path.read_text(encoding="utf-8") if path.is_file() else ""
        report_checks[stage] = {
            "exists": path.is_file(),
            "ready_for_review": "ready_for_review=true" in content,
            "does_not_claim_accepted_fixed": _does_not_claim_acceptance(content),
            "path": path.as_posix(),
        }
        report_checks[stage]["ok"] = all(
            report_checks[stage][key]
            for key in ("exists", "ready_for_review", "does_not_claim_accepted_fixed")
        )

    issue_ids = tuple(row["issue_id"] for row in ISSUE_ROWS)
    aggregate_issue_predicates = {
        "issue_ids_unique": len(set(issue_ids)) == 24,
        "issue_ids_contiguous": issue_ids == tuple(f"P7-I{index:02d}" for index in range(1, 25)),
        "all_issues_bound_to_runtime_predicates": (
            set(ISSUE_EVIDENCE_PREDICATES) == set(issue_ids)
            and all(ISSUE_EVIDENCE_PREDICATES.get(issue_id) for issue_id in issue_ids)
            and all(
                stage == "aggregate"
                or (
                    stage in STAGE_REQUIRED_PREDICATES
                    and predicate in STAGE_REQUIRED_PREDICATES[stage]
                )
                for bindings in ISSUE_EVIDENCE_PREDICATES.values()
                for stage, predicate in bindings
            )
        ),
    }
    issue_checks: list[dict[str, Any]] = []
    for row in ISSUE_ROWS:
        code_paths = tuple(package_root / item for item in row["code"])
        validator_path = tools_root / row["validator"]
        stage_ready = all(report_checks[stage]["ok"] for stage in row["stages"] if stage != "s19")
        evidence_bindings = ISSUE_EVIDENCE_PREDICATES.get(row["issue_id"], ())
        runtime_predicate_checks: dict[str, bool] = {}
        for stage, predicate in evidence_bindings:
            key = f"{stage}:{predicate}"
            if stage == "aggregate":
                runtime_predicate_checks[key] = aggregate_issue_predicates.get(predicate) is True
            else:
                runtime_predicate_checks[key] = (
                    stage_validation_evidence.get(stage, {})
                    .get("required_predicates", {})
                    .get(predicate)
                    is True
                )
        stage_runtime_evidence_ready = bool(runtime_predicate_checks) and all(runtime_predicate_checks.values())
        check = {
            **row,
            "proposed_status": "ready_for_review",
            "acceptance_status": "awaiting_unified_acceptance",
            "code_paths": [path.as_posix() for path in code_paths],
            "code_evidence_exists": all(path.is_file() for path in code_paths),
            "validator_path": validator_path.as_posix(),
            "validator_exists": validator_path.is_file(),
            "stage_reports_ready": stage_ready,
            "stage_runtime_evidence_ready": stage_runtime_evidence_ready,
            "runtime_evidence_predicates": runtime_predicate_checks,
            "runtime_predicates_nonempty": bool(runtime_predicate_checks),
        }
        check["ok"] = all(
            check[key]
            for key in (
                "code_evidence_exists",
                "validator_exists",
                "stage_reports_ready",
                "stage_runtime_evidence_ready",
                "runtime_predicates_nonempty",
            )
        )
        issue_checks.append(check)

    regression_checks: dict[str, dict[str, Any]] = {
        phase: dict(current_regressions.get("entries", {}).get(phase) or {})
        for phase in ("p1", "p2", "p3")
    }
    regression_checks.update(
        _current_p4_p6_regression_checks(
            current_regressions=current_regressions,
            reports_root=reports_root,
            report_checks=report_checks,
            p3_ok=regression_checks["p3"].get("ok") is True,
        )
    )

    plan_path = package_root / "P7_KERNEL_TRUST_AND_COMBAT_SEMANTICS_REPAIR_TASK_PLAN.md"
    plan_text = plan_path.read_text(encoding="utf-8")
    pending_acceptance_stages_unchanged = all(
        re.search(rf"^- \[ \] P7-S{stage} ", plan_text, flags=re.MULTILINE)
        for stage in (19,)
    )
    s0_issue_ids = tuple(spec.issue_id for spec in ISSUE_SPECS)
    ledger_checks = {
        "issue_count_24": len(ISSUE_ROWS) == 24,
        "issue_ids_unique": len(set(issue_ids)) == 24,
        "issue_ids_contiguous": issue_ids == tuple(f"P7-I{index:02d}" for index in range(1, 25)),
        "s0_issue_set_inherited": s0_issue_ids == EXPECTED_ISSUE_IDS,
        "all_issue_evidence_ready": all(item["ok"] for item in issue_checks),
        "all_stage_reports_ready": all(item["ok"] for item in report_checks.values()),
        "all_stage_validation_evidence_current": (
            set(stage_validation_evidence) == set(STAGE_REQUIRED_PREDICATES)
            and all(item["ok"] for item in stage_validation_evidence.values())
        ),
        "current_shared_regression_manifest_matches_worktree": current_regressions.get("ok") is True,
        "structured_check_gate_negatives_ok": structured_check_negatives.get("ok") is True,
        "stale_p4_p6_summary_replacement_rejected": stale_evidence_negative.get("ok") is True,
        "p1_current_regression_ok": regression_checks["p1"].get("ok") is True,
        "p2_retained_action_delay_gap_explicit": (
            regression_checks["p2"].get("ok") is True
            and regression_checks["p2"].get("classification") == "retained_action_delay_content_gap"
        ),
        "p3_reopened_servant_gap_explicit": (
            regression_checks["p3"].get("ok") is True
            and regression_checks["p3"].get("classification") == "reopened_servant_action_content_gap"
        ),
        "p4_p6_current_targeted_evidence_ok": all(
            regression_checks[name].get("ok") is True for name in ("p4", "p5", "p6")
        ),
        "executor_pending_checklist_unchanged": pending_acceptance_stages_unchanged,
        "static_checks_ok": static.ok,
    }
    ledger_checks["ok"] = all(value for key, value in ledger_checks.items() if key != "ok")
    result = {
        "schema_version": "p7_s19_kernel_invariant_aggregate_v4",
        "ok": ledger_checks["ok"],
        "ready_for_review": ledger_checks["ok"],
        "p7_done": False,
        "completion_authority": "unified_acceptance_thread",
        "checks": ledger_checks,
        "issue_rows": issue_checks,
        "stage_reports": report_checks,
        "stage_validation_evidence": stage_validation_evidence,
        "current_shared_regressions": current_regressions,
        "structured_check_gate_negative_evidence": structured_check_negatives,
        "stale_p4_p6_replacement_negative": stale_evidence_negative,
        "p1_p6_regressions": regression_checks,
        "static_checks": static.to_json(),
        "scope_boundary": {
            "p7_kernel_invariants_ready_for_review": ledger_checks["ok"],
            "all_characters_monsters_equipment_stages_complete": False,
            "deferred_content_expansion_preserved": True,
        },
        "resource_budget": {
            "tbgd_build_count": current_regressions.get("resource_budget", {}).get("tbgd_lowering_build_count"),
            "reads_current_tree_fingerprint_bound_summaries": True,
            "p4_p6_validation_mode": "targeted_changed_surface",
            "full_p4_p6_aggregate_rerun": False,
            "large_artifacts_written": False,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p7_s19_kernel_invariant_aggregate.json", result)
    write_json(output_dir / "p7_s19_issue_invariant_matrix.json", {"rows": issue_checks})
    write_json(
        output_dir / "p7_s19_phase_regression_matrix.json",
        {
            "stage_reports": report_checks,
            "stage_validation_evidence": stage_validation_evidence,
            "p1_p6_regressions": regression_checks,
            "checks": ledger_checks,
        },
    )
    return result


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _stage_validation_evidence(package_root: Path, manifest_path: Path) -> dict[str, dict[str, Any]]:
    manifest = _read_json(manifest_path)
    manifest_root = manifest_path.parent
    stage_entries = dict(manifest.get("stages") or {})
    current_fingerprint = source_tree_fingerprint(package_root)
    manifest_fingerprint_matches = manifest.get("source_tree_fingerprint") == current_fingerprint
    result: dict[str, dict[str, Any]] = {}
    for stage, predicates in STAGE_REQUIRED_PREDICATES.items():
        entry = dict(stage_entries.get(stage) or {})
        summary_path = _manifest_path(manifest_root, entry.get("summary"))
        summary = _read_json(summary_path) if summary_path is not None else {}
        identity = str(
            summary.get("validation_version")
            or summary.get("version")
            or summary.get("schema_version")
            or ""
        )
        predicate_checks = {
            predicate: _value_at_path(summary, predicate) is True
            for predicate in predicates
        }
        check = {
            "summary_path": summary_path.as_posix() if summary_path is not None else "",
            "summary_exists": summary_path is not None and summary_path.is_file(),
            "summary_sha256": _sha256(summary_path),
            "summary_sha256_matches_manifest": (
                bool(entry.get("summary_sha256"))
                and entry.get("summary_sha256") == _sha256(summary_path)
            ),
            "generated_after_current_python_sources": entry.get("generated_after_current_python_sources") is True,
            "identity_matches_stage": f"p7_{stage}" in identity,
            "ok_field_true": summary.get("ok") is True,
            "ready_for_review_true": (
                summary.get("ready_for_review") is True
                or summary.get(f"p7_{stage}_ready_for_review") is True
            ),
            "required_predicates": predicate_checks,
            "all_required_predicates_true": all(predicate_checks.values()),
        }
        if stage == "s6":
            source_path = _manifest_path(manifest_root, entry.get("real_source_evidence"))
            source_payload = _read_json(source_path) if source_path is not None else {}
            source_samples = dict(source_payload.get("source_card_samples") or source_payload)
            samples = tuple(
                item for item in source_samples.get("samples", ())
                if isinstance(item, dict)
            )
            check["real_source_evidence_path"] = (
                source_path.as_posix() if source_path is not None else ""
            )
            check["real_source_evidence_sha256"] = _sha256(source_path)
            check["real_source_evidence_sha256_matches_manifest"] = (
                bool(entry.get("real_source_evidence_sha256"))
                and entry.get("real_source_evidence_sha256") == _sha256(source_path)
            )
            check["real_character_monster_servant_samples"] = (
                source_path is not None
                and source_path.is_file()
                and source_samples.get("ok") is True
                and source_samples.get("fixed_character_monster_servant_or_action_id_used") is False
                and {item.get("owner_kind") for item in samples}
                == {"character", "monster", "servant"}
                and all(
                    item.get("status") == "executable"
                    and bool(item.get("admission_id"))
                    and bool(dict(item.get("source") or {}).get("source_path"))
                    for item in samples
                )
            )
        check["ok"] = all(
            value
            for key, value in check.items()
            if key not in {
                "summary_path",
                "summary_sha256",
                "required_predicates",
                "real_source_evidence_path",
                "real_source_evidence_sha256",
                "ok",
            }
        )
        result[stage] = check
    result_ok = (
        manifest.get("schema_version") == "p7_s19_stage_evidence_manifest_v2"
        and manifest.get("ok") is True
        and manifest_fingerprint_matches
        and set(stage_entries) == set(STAGE_REQUIRED_PREDICATES)
        and all(item["ok"] for item in result.values())
    )
    if not result_ok:
        for item in result.values():
            item["manifest_complete"] = False
            item["ok"] = False
    return result


def _current_shared_regression_evidence(package_root: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    manifest_root = manifest_path.parent
    current_fingerprint = source_tree_fingerprint(package_root)
    entries = dict(manifest.get("entries") or {})
    expected_names = (
        "p1",
        "p2",
        "p3",
        "p4_s2",
        "p4_s3",
        "p6_s1",
        "p6_static",
        "s16",
        "s17",
    )
    checked_entries: dict[str, dict[str, Any]] = {}
    for name in expected_names:
        entry = dict(entries.get(name) or {})
        summary_path = _manifest_path(manifest_root, entry.get("summary"))
        summary = _read_json(summary_path) if summary_path is not None else {}
        semantic_checks = _current_regression_summary_checks(name, summary)
        source_binding = dict(summary.get("current_source_binding") or {})
        if name == "p2" and semantic_checks.get("single_action_delay_gap_explicit") is True:
            classification = "retained_action_delay_content_gap"
        elif name == "p3" and semantic_checks.get("servant_action_gap_reopened") is True:
            classification = "reopened_servant_action_content_gap"
        else:
            classification = (
                "current_tree_regression_passed"
                if summary.get("ok") is True
                else "current_tree_regression_failed"
            )
        check = {
            "summary": summary_path.as_posix() if summary_path is not None else "",
            "summary_exists": summary_path is not None and summary_path.is_file(),
            "summary_sha256": _sha256(summary_path),
            "summary_sha256_matches_manifest": (
                bool(entry.get("summary_sha256"))
                and entry.get("summary_sha256") == _sha256(summary_path)
            ),
            "current_source_binding_matches": (
                source_binding.get("schema_version") == "current_source_binding_v1"
                and source_binding.get("source_tree_fingerprint") == current_fingerprint
                and source_binding.get("shared_validation_version")
                == "p7_current_tree_shared_regressions"
                and source_binding.get("shared_rulebook_build_count") == 1
            ),
            "semantic_checks": semantic_checks,
            "all_semantic_checks_true": bool(semantic_checks) and all(semantic_checks.values()),
            "classification": classification,
            "classification_matches_manifest": entry.get("classification") == classification,
        }
        check["ok"] = all(
            value
            for key, value in check.items()
            if key not in {"summary", "summary_sha256", "semantic_checks", "classification", "ok"}
        )
        checked_entries[name] = check
    resource_budget = dict(manifest.get("resource_budget") or {})
    checks = {
        "schema_current": manifest.get("schema_version") == "p7_current_tree_shared_regressions_v3",
        "source_tree_fingerprint_matches": manifest.get("source_tree_fingerprint") == current_fingerprint,
        "exact_serial_sequence": tuple(manifest.get("sequence") or ()) == expected_names
        and tuple(manifest.get("completed_sequence") or ()) == expected_names,
        "exact_entry_set": set(entries) == set(expected_names),
        "all_entries_recomputed_ok": all(entry["ok"] for entry in checked_entries.values()),
        "manifest_ok": manifest.get("ok") is True,
        "single_shared_rulebook_build": resource_budget.get("tbgd_lowering_build_count") == 1
        and resource_budget.get("rulebook_build_count") == 1,
        "serial_execution": resource_budget.get("serial_execution") is True,
        "no_large_artifacts": resource_budget.get("large_artifacts_written") is False,
        "structured_check_gate_negatives_ok": (
            manifest.get("checks", {}).get("structured_check_gate_negatives_ok") is True
            and manifest.get("structured_check_gate_negative_evidence", {}).get("ok") is True
        ),
    }
    return {
        "manifest_path": manifest_path.as_posix(),
        "ok": all(checks.values()),
        "checks": checks,
        "source_tree_fingerprint": current_fingerprint,
        "entries": checked_entries,
        "resource_budget": resource_budget,
    }


def _current_regression_summary_checks(name: str, summary: dict[str, Any]) -> dict[str, bool]:
    if name == "p1":
        break_case = (
            summary.get("direct_regression_checks", {})
            .get("status_cases", {})
            .get("break_status", {})
        )
        break_checks = dict(break_case.get("checks") or {})
        return {
            "validation_gate_ok": summary.get("ok") is True,
            "break_status_case_ok": break_case.get("ok") is True,
            "break_status_mutation_ok": break_checks.get("real_break_status_mutation_ok") is True,
            "break_status_replay_ok": break_checks.get("real_break_replay_ok") is True,
            "break_status_source_audit_ok": break_checks.get("real_break_source_audit_ok") is True,
            "break_status_typed_target_ok": break_checks.get("executable_break_targets_typed") is True,
            "break_status_param_entity_ok": break_checks.get("param_entity_target_preserved") is True,
        }
    if name == "p2":
        summary_data = dict(summary.get("summary") or {})
        content_gaps = dict(summary_data.get("p2_status_content_coverage_gaps") or {})
        action_delay = dict(content_gaps.get("action_delay_callback_graph") or {})
        return {
            "historical_substrate_not_claimed": summary.get("ok") is False
            and summary_data.get("p2_status_substrate_complete") is False,
            "source_closure_ok": summary.get("checks", {}).get("s11_source_closure", {}).get("ok") is True,
            "source_audit_replay_samples_ok": summary.get("checks", {}).get("source_audit_replay_samples", {}).get("ok") is True,
            "single_action_delay_gap_explicit": set(content_gaps) == {"action_delay_callback_graph"}
            and action_delay.get("classification") == "implementation_missing"
            and action_delay.get("p7_invariant_blocker") is False
            and int(action_delay.get("primitive_runtime_candidate_count") or 0) > 0,
        }
    if name == "p3":
        return {
            "validation_gate_ok": summary.get("ok") is True and summary.get("validation_gate_ok") is True,
            "historical_foundation_not_claimed": summary.get("p3_summon_foundation_closed") is False,
            "servant_action_gap_reopened": int(summary.get("p3_summon_implementation_missing_count") or 0) > 0,
            "result_status_explicit": summary.get("p3_summon_result_status")
            == "validation_gate_ok_phase_incomplete_with_disallowed_gaps",
        }
    if name in {"p4_s2", "p4_s3", "p6_s1", "p6_static"}:
        budget = dict(summary.get("resource_budget") or {})
        return {
            "validation_gate_ok": summary.get("ok") is True,
            **current_regression_structured_check_contract(name, summary),
            "shared_rulebook_not_rebuilt": (
                budget.get("lowering_build_count") == 0
                and budget.get("rulebook_build_count") == 0
                and budget.get("shared_rulebook_reused") is True
            )
            if name != "p6_static"
            else budget.get("large_artifacts_written") is False,
            "no_large_artifacts": budget.get("large_artifacts_written") is False,
        }
    return {
        "validation_gate_ok": summary.get("ok") is True,
        "ready_for_review": summary.get("ready_for_review") is True,
    }


def _manifest_path(root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else root / path


def _value_at_path(value: Any, path: str) -> Any:
    current = value
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def _sha256(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _does_not_claim_acceptance(content: str) -> bool:
    forbidden_claims = (
        r"\baccepted_fixed\s*=\s*(?:true|1)\b",
        r"\bacceptance_status\s*[:=]\s*accepted_fixed\b",
        r"\bp7_done\s*=\s*(?:true|1)\b",
    )
    return not any(re.search(pattern, content, flags=re.IGNORECASE) for pattern in forbidden_claims)


def _current_p4_p6_regression_checks(
    *,
    current_regressions: dict[str, Any],
    reports_root: Path,
    report_checks: dict[str, dict[str, Any]],
    p3_ok: bool,
) -> dict[str, dict[str, Any]]:
    entries = dict(current_regressions.get("entries") or {})
    p4_s2 = dict(entries.get("p4_s2") or {})
    p4_s3 = dict(entries.get("p4_s3") or {})
    p6_s1 = dict(entries.get("p6_s1") or {})
    p6_static = dict(entries.get("p6_static") or {})

    p4_checks = {
        "historical_checkpoint_exists": (
            reports_root / "v8_p4_combatant_data_card_expansion_checkpoint.md"
        ).is_file(),
        "current_s2_bound_to_source_tree": p4_s2.get("ok") is True,
        "current_s3_bound_to_source_tree": p4_s3.get("ok") is True,
    }
    p4 = {
        "validation_mode": "current_shared_rulebook_targeted",
        "full_aggregate_rerun": False,
        "paths": [p4_s2.get("summary", ""), p4_s3.get("summary", "")],
        "checks": p4_checks,
    }
    p4["ok"] = all(p4_checks.values())

    p5_checks = {
        "historical_checkpoint_exists": (
            reports_root / "v8_p5_formula_dynamic_param_binding_checkpoint.md"
        ).is_file(),
        "current_formula_dynamic_source_scan_ok": p4_s3.get("ok") is True,
        "damage_toughness_consumer_invariant_ready": report_checks["s12"]["ok"],
        "status_consumer_invariant_ready": report_checks["s14"]["ok"],
        "rng_replay_invariant_ready": report_checks["s15"]["ok"],
        "summon_consumer_invariant_ready": report_checks["s16"]["ok"],
    }
    p5 = {
        "validation_mode": "current_p4_s3_plus_current_p7_consumers",
        "full_aggregate_rerun": False,
        "paths": [p4_s3.get("summary", "")],
        "checks": p5_checks,
    }
    p5["ok"] = all(p5_checks.values())

    p6_checks = {
        "historical_checkpoint_exists": (
            reports_root / "v8_p6_architecture_boundary_refactor_checkpoint.md"
        ).is_file(),
        "current_damage_toughness_entry_bound_to_source_tree": p6_s1.get("ok") is True,
        "current_boundary_static_bound_to_source_tree": p6_static.get("ok") is True,
        "unit_birth_current_regression_inherited": p3_ok,
    }
    p6 = {
        "validation_mode": "current_shared_rulebook_targeted",
        "full_aggregate_rerun": False,
        "paths": [p6_s1.get("summary", ""), p6_static.get("summary", "")],
        "checks": p6_checks,
    }
    p6["ok"] = all(p6_checks.values())
    return {"p4": p4, "p5": p5, "p6": p6}


def _stale_p4_p6_replacement_negative(
    package_root: Path,
    current_manifest_path: Path,
) -> dict[str, Any]:
    manifest = _read_json(current_manifest_path)
    target_name = "p4_s2"
    current_entry = dict(dict(manifest.get("entries") or {}).get(target_name) or {})
    current_path = _manifest_path(current_manifest_path.parent, current_entry.get("summary"))
    current_summary = _read_json(current_path) if current_path is not None else {}
    current_binding = dict(current_summary.get("current_source_binding") or {})
    current_fingerprint = dict(current_binding.get("source_tree_fingerprint") or {})
    current_sha = current_fingerprint.get("sha256")
    if not manifest or not current_summary or not isinstance(current_sha, str) or not current_sha:
        return {
            "ok": False,
            "current_summary_present": bool(current_summary),
            "reason": "current_p4_s2_source_binding_fixture_missing",
        }

    stale_summary = copy.deepcopy(current_summary)
    stale_binding = copy.deepcopy(current_binding)
    stale_fingerprint = copy.deepcopy(current_fingerprint)
    stale_fingerprint["sha256"] = "0" * 64 if current_sha != "0" * 64 else "f" * 64
    stale_binding["source_tree_fingerprint"] = stale_fingerprint
    stale_summary["current_source_binding"] = stale_binding
    stale_summary_path = (
        current_manifest_path.parent / "p7_synthetic_stale_p4_s2_summary.json"
    )
    write_json(stale_summary_path, stale_summary)

    tampered = copy.deepcopy(manifest)
    entry = dict(dict(tampered.get("entries") or {}).get(target_name) or {})
    entry["summary"] = stale_summary_path.as_posix()
    entry["summary_sha256"] = _sha256(stale_summary_path)
    tampered["entries"][target_name] = entry
    negative_path = (
        current_manifest_path.parent
        / "p7_synthetic_stale_p4_p6_replacement_negative_manifest.json"
    )
    write_json(negative_path, tampered)
    evidence = _current_shared_regression_evidence(package_root, negative_path)
    target = dict(evidence.get("entries", {}).get(target_name) or {})
    checks = {
        "current_summary_present": current_path is not None and current_path.is_file(),
        "synthetic_stale_summary_written": stale_summary_path.is_file(),
        "source_fingerprint_changed": stale_fingerprint != current_fingerprint,
        "source_binding_identity_preserved": all(
            stale_binding.get(key) == current_binding.get(key)
            for key in (
                "schema_version",
                "shared_validation_version",
                "shared_rulebook_build_count",
            )
        ),
        "attacker_updated_summary_hash": target.get("summary_sha256_matches_manifest") is True,
        "source_binding_rejected": target.get("current_source_binding_matches") is False,
        "tampered_manifest_rejected": evidence.get("ok") is False,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "target_entry": target_name,
        "current_summary_path": current_path.as_posix() if current_path is not None else "",
        "synthetic_stale_summary_path": stale_summary_path.as_posix(),
        "tampered_manifest_path": negative_path.as_posix(),
        "tampered_evidence_checks": evidence.get("checks", {}),
    }


def _retained_gap_summary(summary: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "summary",
        "allowed_gap_evidence_summary",
        "scope_exclusions",
        "allowed_gap_evidence_matrix",
        "source_gap_matrix",
    )
    return {key: summary[key] for key in keys if key in summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P7-S19 final invariant aggregate.")
    parser.add_argument("--regression-root", type=Path, required=True)
    parser.add_argument("--stage-evidence-manifest", type=Path, required=True)
    parser.add_argument("--current-regression-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    result = run_validation(
        package_root,
        args.regression_root,
        args.output_dir,
        args.stage_evidence_manifest,
        args.current_regression_manifest,
    )
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} issues={len(result['issue_rows'])} "
        f"p1_p2_current={sum(result['p1_p6_regressions'][name]['ok'] for name in ('p1', 'p2'))}/2 "
        f"p3_reopened={result['checks']['p3_reopened_servant_gap_explicit']} "
        f"ready_for_review={result['ready_for_review']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
