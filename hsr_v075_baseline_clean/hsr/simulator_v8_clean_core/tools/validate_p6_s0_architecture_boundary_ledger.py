from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import JSONValue
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "p6_s0_architecture_boundary_ledger"
MATRIX_SCHEMA_VERSION = "p6_s0_architecture_boundary_ledger_matrix_v2"

QUESTION_IDS = {
    "q1_audit_trace_rule_input",
    "q2_runtime_unit_assembly",
    "q3_scenario_ui_rule_boundary",
    "q4_content_core_special_case",
    "q5_missing_source_fallback",
}

CLASSIFICATION_STATES = {
    "audit_only",
    "rule_input_violation",
    "content_assembly_in_runtime",
    "scenario_assembly_ok",
    "scenario_rule_violation",
    "content_execution_violation",
    "core_content_special_case",
    "fallback_execution_violation",
    "unclear",
}

VIOLATION_STATES = {
    "rule_input_violation",
    "content_assembly_in_runtime",
    "scenario_rule_violation",
    "content_execution_violation",
    "core_content_special_case",
    "fallback_execution_violation",
    "unclear",
}


@dataclass(frozen=True)
class AuditRule:
    finding_id: str
    question_id: str
    path: str
    tokens: tuple[str, ...]
    classification: str
    followup_stage: str
    current_behavior: str
    boundary_reason: str
    required_next_action: str


SCAN_COVERAGE_EXCLUSIONS: dict[str, str] = {
    "simulator_v8_clean_core/systems/unit_lifecycle.py": (
        "UnitLifecycleSystem receives an already-built UnitState and creates lifecycle mutations; "
        "it does not read content cards or assemble combatant rules."
    ),
}


AUDIT_RULES: tuple[AuditRule, ...] = (
    AuditRule(
        finding_id="q1_action_plan_uses_emission_contract",
        question_id="q1_audit_trace_rule_input",
        path="simulator_v8_clean_core/core/action_plan.py",
        tokens=("def build_action_execution_plan", "damage_emissions", "toughness_emissions", "source_trace=source_trace or {}"),
        classification="audit_only",
        followup_stage="P6-S1",
        current_behavior="ActionExecutionPlan is built from ActionDefinitionIR, ActionEventIR, HitProfileIR, DamageEmissionIR, and ToughnessEmissionIR; source_trace is carried on the plan.",
        boundary_reason="This is the desired explicit mechanism-entry direction for damage/toughness, as long as source_trace remains audit metadata only.",
        required_next_action="Keep this as the S1 target contract and move remaining trace-derived value lookups onto explicit plan fields.",
    ),
    AuditRule(
        finding_id="q1_damage_value_resolution_reads_formula_binding_from_trace",
        question_id="q1_audit_trace_rule_input",
        path="simulator_v8_clean_core/core/executor.py",
        tokens=("def _damage_value_resolution", "_skill_formula_binding_from_trace(damage_plan.hit_source_trace)", "binding_kind=\"skill_formula_param\""),
        classification="rule_input_violation",
        followup_stage="P6-S1",
        current_behavior="Damage value resolution recursively extracts skill_formula_binding metadata from damage_plan.hit_source_trace before building ValueBindingRequest.",
        boundary_reason="The binding used to choose a runtime value request is being recovered from audit/source metadata instead of a stable calculation entry on the plan.",
        required_next_action="Add an explicit damage calculation/value-binding reference to the damage plan or emission consumer contract; source_trace must only audit the selected binding.",
    ),
    AuditRule(
        finding_id="q1_toughness_value_resolution_reads_binding_sources_from_trace",
        question_id="q1_audit_trace_rule_input",
        path="simulator_v8_clean_core/core/executor.py",
        tokens=("def _toughness_value_resolution", "binding_sources=_numeric_binding_sources_from_trace(toughness_plan.source_trace)", "source_trace=toughness_plan.source_trace"),
        classification="rule_input_violation",
        followup_stage="P6-S1",
        current_behavior="Toughness value resolution derives numeric binding sources by walking toughness_plan.source_trace.",
        boundary_reason="The runtime binding source for toughness amount is discovered by inspecting source metadata rather than by consuming an explicit calculation/value-binding slot.",
        required_next_action="Move toughness amount binding sources onto ToughnessPlan/ToughnessEmissionIR as a stable field and keep trace only for audit.",
    ),
    AuditRule(
        finding_id="q5_toughness_show_stance_list_fallback_after_dynamic_hash",
        question_id="q5_missing_source_fallback",
        path="simulator_v8_clean_core/core/executor.py",
        tokens=("fallback_request = ValueBindingRequest", "binding_kind=\"action_definition_list_item\"", "\"fallback_basis\": \"ActionDefinitionIR.show_stance_list\""),
        classification="fallback_execution_violation",
        followup_stage="P6-S1",
        current_behavior="When dynamic-hash toughness resolution fails, executor attempts a show_stance_list list-item fallback.",
        boundary_reason="A missing or unbound explicit toughness value can still execute through a secondary fallback path instead of staying blocked.",
        required_next_action="S1 must decide whether show_stance_list is an admitted explicit calculation entry; if not, missing dynamic binding must block/state-unchanged.",
    ),
    AuditRule(
        finding_id="q5_damage_formula_binding_absent_fixed_ratio_fallback",
        question_id="q5_missing_source_fallback",
        path="simulator_v8_clean_core/core/executor.py",
        tokens=("else:", "binding_kind=\"fixed_numeric_expression\"", "expression={\"kind\": \"fixed\", \"value\": damage_plan.scaling_ratio}"),
        classification="fallback_execution_violation",
        followup_stage="P6-S1",
        current_behavior="If _skill_formula_binding_from_trace returns no binding, damage value resolution falls back to the fixed scaling_ratio already on DamagePlan.",
        boundary_reason="The fallback may be valid only if DamagePlan's scaling_ratio is itself an admitted calculation entry; S0 cannot prove that from this local path.",
        required_next_action="S1 must make the admitted damage calculation source explicit and reject missing calculation entries rather than relying on trace absence.",
    ),
    AuditRule(
        finding_id="q2_summon_plan_reads_profile_and_monster_card",
        question_id="q2_runtime_unit_assembly",
        path="simulator_v8_clean_core/systems/summon.py",
        tokens=("def plan_spawn_summoned_monster", "profile = self.rules.combatant_profile(entry.monster_entity_ref)", "card = self.rules.monster_data_card_for_entity(entry.monster_entity_ref)"),
        classification="content_assembly_in_runtime",
        followup_stage="P6-S2",
        current_behavior="Summon planning reads combatant profile and monster data card for each intent entry.",
        boundary_reason="The summon runtime is checking and understanding content-card/profile assembly details that should be precompiled into a birth order.",
        required_next_action="S2 should make summon planning consume a complete birth order with admitted profile/card/action/lifecycle fields.",
    ),
    AuditRule(
        finding_id="q2_summon_apply_reloads_intent_and_builds_units",
        question_id="q2_runtime_unit_assembly",
        path="simulator_v8_clean_core/systems/summon.py",
        tokens=("def apply_spawn", "intent = self.rules.summon_monster_intent(plan.intent_id)", "self._unit_from_entry"),
        classification="content_assembly_in_runtime",
        followup_stage="P6-S2",
        current_behavior="Summon apply reloads SummonMonsterIntentIR by id, expands entries, and delegates UnitState construction to _unit_from_entry.",
        boundary_reason="The apply phase is not merely applying a prepared birth order; it reconstructs content details at mutation time.",
        required_next_action="S2 should make apply_spawn validate and apply a birth order carried by the plan rather than reopening intent/card/profile internals.",
    ),
    AuditRule(
        finding_id="q2_summon_unit_from_entry_constructs_combat_unit",
        question_id="q2_runtime_unit_assembly",
        path="simulator_v8_clean_core/systems/summon.py",
        tokens=("def _unit_from_entry", "timeline_rule = self.rules.default_timeline_rule()", "return UnitState("),
        classification="content_assembly_in_runtime",
        followup_stage="P6-S2",
        current_behavior="_unit_from_entry computes stats, resources, action value, flags, source traces, and action admission before returning UnitState.",
        boundary_reason="This is unit birth assembly inside summon runtime; P6 wants runtime to execute a birth order instead.",
        required_next_action="Move these fields into a generic birth-order structure owned by data-card/lowering assembly and shared by summon/wave/setup consumers.",
    ),
    AuditRule(
        finding_id="q2_servant_spawn_reopens_definition_and_constructs_unit",
        question_id="q2_runtime_unit_assembly",
        path="simulator_v8_clean_core/systems/summon.py",
        tokens=("def apply_spawn_servant", "definition = self.rules.servant_definition(plan.intent_id)", "unit = self._unit_from_servant_definition"),
        classification="content_assembly_in_runtime",
        followup_stage="P6-S2",
        current_behavior="Servant apply reloads ServantDefinitionIR and constructs a UnitState from definition and owner state.",
        boundary_reason="Servant-specific stat/lifecycle/action details are interpreted in summon runtime instead of being represented as a prepared birth order.",
        required_next_action="S2 should represent servant birth details as the same generic birth-order contract while preserving owner relation and audit evidence.",
    ),
    AuditRule(
        finding_id="q3_initial_servant_setup_reads_definition_and_invokes_summon_system",
        question_id="q3_scenario_ui_rule_boundary",
        path="simulator_v8_clean_core/scenarios/build_state.py",
        tokens=("def _apply_initial_servant", "definition = rules.servant_definition(servant_ref)", "plan = system.plan_spawn_servant", "result = system.apply_spawn_servant"),
        classification="scenario_assembly_ok",
        followup_stage="P6-S2/P6-S3",
        current_behavior="Initial servant setup resolves a ServantDefinitionIR and invokes SummonSystem plan/apply to spawn the setup servant.",
        boundary_reason="This is setup-time initial condition assembly, but it crosses the same servant birth-order boundary that S2/S3 must unify.",
        required_next_action="S2 should provide the servant birth-order contract; S3 should make initial setup consume that contract without scenario-specific rule execution.",
    ),
    AuditRule(
        finding_id="q3_initial_scenario_unit_assembly",
        question_id="q3_scenario_ui_rule_boundary",
        path="simulator_v8_clean_core/scenarios/build_state.py",
        tokens=("profile = self.rules.combatant_profile(unit.entity_ref)", "monster_card = self.rules.monster_data_card_for_entity(unit.entity_ref)", "units[unit.unit_id] = UnitState("),
        classification="scenario_assembly_ok",
        followup_stage="P6-S3",
        current_behavior="ScenarioStateBuilder uses RuleBook profile/card data to assemble initial UnitState for battle setup.",
        boundary_reason="This is currently initial-state assembly, not route-time rule execution; however, it duplicates unit-birth concerns that S3 should align with wave/summon generation.",
        required_next_action="S3 should decide how initial setup consumes or produces the shared birth-order structure without moving rule execution into scenario helpers.",
    ),
    AuditRule(
        finding_id="q3_initial_wave_spec_derives_unit_setup",
        question_id="q3_scenario_ui_rule_boundary",
        path="simulator_v8_clean_core/scenarios/build_state.py",
        tokens=("def _wave_unit_spec", "action_value, timeline_source = _initial_wave_action_value(rules, entry)", "PanelInput("),
        classification="scenario_assembly_ok",
        followup_stage="P6-S3",
        current_behavior="Initial wave setup converts WaveMonsterEntryIR into UnitSpec and computes initial action value from the timeline rule.",
        boundary_reason="The path is setup-only but overlaps with wave runtime spawning; P6-S3 should remove duplicated assembly semantics.",
        required_next_action="Unify initial wave, wave transition, and summon monster birth fields while keeping scenario setup as initial-condition assembly only.",
    ),
    AuditRule(
        finding_id="q3_identity_initial_servant_definition_validation",
        question_id="q3_scenario_ui_rule_boundary",
        path="simulator_v8_clean_core/scenarios/identity.py",
        tokens=("elif summon.kind == \"servant\":", "definition = self.rules.servant_definition(servant_ref)", "definition.owner_entity_ref and owner.entity_ref != definition.owner_entity_ref"),
        classification="scenario_assembly_ok",
        followup_stage="P6-S3",
        current_behavior="Scenario identity validation resolves initial servant definitions to validate refs, owner relation, executable status, and source trace.",
        boundary_reason="This is configuration validation and source collection, not combat rule execution; it still belongs in S0 so setup-time servant reads are explicit.",
        required_next_action="Keep as validation-only; after S2/S3 birth-order changes, ensure identity validation checks the stable setup reference rather than duplicating spawn semantics.",
    ),
    AuditRule(
        finding_id="q3_ui_report_consumes_candidate_targets",
        question_id="q3_scenario_ui_rule_boundary",
        path="simulator_v8_ui/report.py",
        tokens=("candidate = _dict(enemy_action_candidate)", "selectable_target_ids", "\"targets\": targets"),
        classification="audit_only",
        followup_stage="P6-S5",
        current_behavior="UI report consumes backend-provided enemy candidate target ids and formats them for display/selection.",
        boundary_reason="This inspected path does not calculate target legality; it displays/query-adapts core output.",
        required_next_action="S5 static boundary checks should continue preventing UI/scenario code from writing derived rule results into formal inputs.",
    ),
    AuditRule(
        finding_id="q3_action_availability_reads_data_cards_for_query_source_context",
        question_id="q3_scenario_ui_rule_boundary",
        path="simulator_v8_clean_core/systems/action_availability.py",
        tokens=("card = rules.monster_data_card(card_id) if card_id else None", "card = rules.monster_data_card_for_entity(actor.template_id)", "definition_id = str(actor.flags.get(\"servant_definition_id\") or actor.template_id)", "definition = rules.servant_definition(definition_id)"),
        classification="audit_only",
        followup_stage="P6-S4/P6-S5",
        current_behavior="Action availability query reads actor data cards or servant definitions to attach source/card context to query output.",
        boundary_reason="The inspected path is a query/source-description surface, not a mutation path; it should remain read-only and must not execute content-card mechanisms.",
        required_next_action="S4/S5 should keep action availability as a query contract and add static checks if it starts deriving rule results outside core contracts.",
    ),
    AuditRule(
        finding_id="q1_dynamic_value_store_reads_character_card_source_evidence",
        question_id="q1_audit_trace_rule_input",
        path="simulator_v8_clean_core/systems/dynamic_values.py",
        tokens=("def character_skill_param_binding_source(", "card = rules.character_data_card_for_entity(unit.template_id)", "config_bindings = card.source.evidence.get(\"character_config_dynamic_value_bindings\")"),
        classification="rule_input_violation",
        followup_stage="P6-S5",
        current_behavior="Dynamic value source projection reads character card source evidence to recover character config dynamic bindings.",
        boundary_reason="Runtime value binding should consume a stable data-card/IR field rather than mining source evidence for rule input.",
        required_next_action="S5 should move this onto a narrow accessor or explicit data-card dynamic binding view and prevent future source-evidence mining.",
    ),
    AuditRule(
        finding_id="q1_value_resolver_consumes_explicit_value_binding_requests",
        question_id="q1_audit_trace_rule_input",
        path="simulator_v8_clean_core/rules/value_binding.py",
        tokens=("class ValueResolver:", "SUPPORTED_BINDING_KINDS", "def resolve(self, request: ValueBindingRequest, context: ValueContext)"),
        classification="audit_only",
        followup_stage="P6-S1/P6-S5",
        current_behavior="ValueResolver consumes explicit ValueBindingRequest kinds and returns blocked ValueResolution when context or binding kind is missing.",
        boundary_reason="The resolver itself is the desired narrow calculation consumer; the S0 violations are callers deriving requests from trace/evidence before invoking it.",
        required_next_action="S1/S5 should keep this request-based contract while moving trace/evidence-mining callers to explicit request fields.",
    ),
    AuditRule(
        finding_id="q4_enemy_action_read_only_candidate_from_card",
        question_id="q4_content_core_special_case",
        path="simulator_v8_clean_core/systems/enemy_action.py",
        tokens=("This system never chooses a target or executes an action.", "MonsterDataCardIR action sequence", "target_policy_for_action"),
        classification="audit_only",
        followup_stage="P6-S4",
        current_behavior="EnemyActionSystem turns lowered MonsterDataCardIR action_sequence into a candidate and enumerates targets through TargetSystem.",
        boundary_reason="This is a generic data-card consumer, not a concrete monster/skill id branch, but it remains a high-value S4 review surface.",
        required_next_action="S4 should keep this read-only/query boundary and ensure no enemy AI execution or concrete monster special case is added here.",
    ),
    AuditRule(
        finding_id="q4_condition_compare_monster_id_uses_ir_payload",
        question_id="q4_content_core_special_case",
        path="simulator_v8_clean_core/rules/evaluator.py",
        tokens=("if opcode == \"ByCompareMonsterID\"", "payload.get(\"TargetMonsterID\")", "return _condition_blocked"),
        classification="audit_only",
        followup_stage="P6-S4",
        current_behavior="Condition evaluator supports a generic ByCompareMonsterID opcode using condition payload and blocks missing target/numeric data.",
        boundary_reason="The inspected path compares an IR payload value; it does not hard-code a specific monster id in core.",
        required_next_action="S4 should preserve this as a generic opcode path and only flag future concrete id/name branches as core_content_special_case.",
    ),
    AuditRule(
        finding_id="q4_source_audit_reads_summon_ir_for_audit_only",
        question_id="q4_content_core_special_case",
        path="simulator_v8_clean_core/core/source_audit.py",
        tokens=("def _audit_summon_mutation", "servant_definition = self.rules.servant_definition(intent_id)", "summon_intent = self.rules.summon_monster_intent(intent_id)"),
        classification="audit_only",
        followup_stage="P6-S5",
        current_behavior="Source audit resolves servant definitions and summon intents from mutation metadata to verify source traceability.",
        boundary_reason="This is an audit verifier and does not drive mutation execution; it is allowed to read IR for source validation.",
        required_next_action="S5 should preserve this audit-only access while preventing execution paths from using the same lookup pattern for rule input.",
    ),
    AuditRule(
        finding_id="q3_wave_runtime_constructs_next_wave_units",
        question_id="q3_scenario_ui_rule_boundary",
        path="simulator_v8_clean_core/systems/wave.py",
        tokens=("spawn_units = tuple(_unit_from_wave_entry", "self.lifecycle.spawn_mutation", "def _unit_from_wave_entry"),
        classification="content_assembly_in_runtime",
        followup_stage="P6-S3",
        current_behavior="Wave transition runtime builds UnitState for next-wave enemies before spawning them.",
        boundary_reason="Wave runtime repeats monster profile/card/unit assembly instead of consuming the same birth-order contract intended for all unit generation paths.",
        required_next_action="S3 should route next-wave spawning through the shared birth-order flow and keep wave runtime responsible for timing and lifecycle only.",
    ),
    AuditRule(
        finding_id="q5_missing_damage_or_toughness_emission_blocks",
        question_id="q5_missing_source_fallback",
        path="simulator_v8_clean_core/core/executor.py",
        tokens=("def _damage_emission_blocked_reason", "return \"damage_emission_missing\"", "def _toughness_emission_blocked_reason"),
        classification="audit_only",
        followup_stage="P6-S1",
        current_behavior="Executor has explicit blocked reasons for missing/non-executable damage and toughness emissions.",
        boundary_reason="This is the correct blocked/process-only direction and should be kept while removing fallback execution paths.",
        required_next_action="S1 validation should prove missing calculation entries record blocked reasons and produce no mutation.",
    ),
    AuditRule(
        finding_id="q5_status_callback_payload_target_fallback_returns_empty_when_missing",
        question_id="q5_missing_source_fallback",
        path="simulator_v8_clean_core/systems/status_callbacks.py",
        tokens=("def _list_alias_targets", "fallback = _first_payload_str", "return (fallback,) if fallback and fallback in state.units else ()"),
        classification="audit_only",
        followup_stage="P6-S5",
        current_behavior="Status callback target alias checks alternate event payload target keys and returns an empty target tuple if no valid payload target exists.",
        boundary_reason="The inspected fallback does not default to actor/all/enemy; missing payload yields no targets, which downstream admission should block.",
        required_next_action="S5 static checks should distinguish payload-key fallback from illegal default-target fallback and keep negative coverage for missing payload.",
    ),
)


def run_validation(package_root: Path, output_dir: Path) -> dict[str, Any]:
    hsr_root = package_root.parent
    static_result = run_static_checks(package_root)
    matrix = build_p6_s0_architecture_boundary_ledger_matrix(hsr_root)
    matrix_checks = validate_p6_s0_architecture_boundary_ledger_matrix(matrix)
    checks = {
        "matrix": matrix_checks,
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(bool(item["ok"]) for item in checks.values()),
        "build": {
            "selection_policy": {
                "mode": "p6_s0_structured_boundary_path_ledger",
                "runtime_behavior_changed": False,
                "tbgd_lowering_built": False,
                "rulebook_built": False,
                "textmap_read": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "full_ir_written": False,
                "full_rulebook_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
                "p6_aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "boundary_ledger_matrix": matrix["boundary_ledger_matrix"],
        "question_coverage": matrix["question_coverage"],
        "scan_summaries": matrix["scan_summaries"],
        "scan_coverage": matrix["scan_coverage"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p6_s0_architecture_boundary_ledger.json", result)
    write_json(output_dir / "p6_s0_architecture_boundary_ledger_matrix.json", matrix)
    return result


def build_p6_s0_architecture_boundary_ledger_matrix(hsr_root: Path) -> dict[str, Any]:
    rows = [_row_from_rule(hsr_root, rule) for rule in AUDIT_RULES]
    classification_counts = Counter(str(row["classification"]) for row in rows)
    followup_stage_counts = Counter(str(row["followup_stage"]) for row in rows)
    question_coverage = {
        question_id: {
            "checked": any(row["question_id"] == question_id for row in rows),
            "row_count": sum(1 for row in rows if row["question_id"] == question_id),
            "violation_count": sum(
                1
                for row in rows
                if row["question_id"] == question_id and row["classification"] in VIOLATION_STATES
            ),
        }
        for question_id in sorted(QUESTION_IDS)
    }
    evidence_missing = [row["finding_id"] for row in rows if row["evidence_status"] != "present"]
    invalid_classification = [
        row["finding_id"] for row in rows if row["classification"] not in CLASSIFICATION_STATES
    ]
    invalid_question = [row["finding_id"] for row in rows if row["question_id"] not in QUESTION_IDS]
    scan_summaries = _scan_summaries(hsr_root)
    scan_coverage = _scan_coverage(rows, scan_summaries)
    uncovered_scan_files = tuple(scan_coverage["uncovered_files"])
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "boundary_ledger_matrix": {str(row["finding_id"]): row for row in rows},
        "summary": {
            "row_count": len(rows),
            "question_count": len(question_coverage),
            "questions_checked": sum(1 for item in question_coverage.values() if item["checked"]),
            "classification_counts": dict(sorted(classification_counts.items())),
            "followup_stage_counts": dict(sorted(followup_stage_counts.items())),
            "violation_row_count": sum(1 for row in rows if row["classification"] in VIOLATION_STATES),
            "unclear_count": int(classification_counts.get("unclear", 0)),
            "evidence_missing_count": len(evidence_missing),
            "invalid_classification_count": len(invalid_classification),
            "invalid_question_count": len(invalid_question),
            "high_risk_scan_uncovered_file_count": len(uncovered_scan_files),
            "high_risk_scan_excluded_file_count": len(scan_coverage["excluded_files"]),
            "runtime_behavior_changed": False,
            "s0_ready_for_s1_to_s5_routing": (
                len(evidence_missing) == 0
                and len(invalid_classification) == 0
                and len(invalid_question) == 0
                and len(uncovered_scan_files) == 0
                and all(item["checked"] for item in question_coverage.values())
            ),
        },
        "question_coverage": question_coverage,
        "evidence_missing": evidence_missing,
        "invalid_classification": invalid_classification,
        "invalid_question": invalid_question,
        "scan_summaries": scan_summaries,
        "scan_coverage": scan_coverage,
        "resource_budget": {
            "rulebook_build_count": 0,
            "tbgd_lowering_build_count": 0,
            "subprocess_validation_count": 0,
            "files_with_curated_evidence": len({rule.path for rule in AUDIT_RULES}),
            "curated_token_count": sum(len(rule.tokens) for rule in AUDIT_RULES),
            "lightweight_scan_count": len(scan_summaries),
            "large_artifacts_written": False,
            "full_ir_written": False,
            "full_rulebook_written": False,
            "full_transition_dump_written": False,
            "output_scope": "summary_and_curated_boundary_matrix_only",
        },
    }


def validate_p6_s0_architecture_boundary_ledger_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    summary = dict(matrix.get("summary") or {})
    question_coverage = dict(matrix.get("question_coverage") or {})
    checks = {
        "all_required_questions_checked": all(
            bool(dict(question_coverage.get(question_id) or {}).get("checked"))
            for question_id in QUESTION_IDS
        ),
        "all_rows_have_current_source_evidence": int(summary.get("evidence_missing_count") or 0) == 0,
        "all_rows_use_valid_classification": int(summary.get("invalid_classification_count") or 0) == 0,
        "all_rows_use_valid_question": int(summary.get("invalid_question_count") or 0) == 0,
        "all_high_risk_scan_files_classified_or_excluded": int(summary.get("high_risk_scan_uncovered_file_count") or 0) == 0,
        "runtime_behavior_unchanged": summary.get("runtime_behavior_changed") is False,
        "s1_to_s5_routing_available": bool(summary.get("s0_ready_for_s1_to_s5_routing")),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _row_from_rule(hsr_root: Path, rule: AuditRule) -> dict[str, JSONValue]:
    path = hsr_root / rule.path
    evidence = _evidence_for_tokens(path, rule.tokens)
    return {
        "finding_id": rule.finding_id,
        "question_id": rule.question_id,
        "path": rule.path,
        "classification": rule.classification,
        "followup_stage": rule.followup_stage,
        "current_behavior": rule.current_behavior,
        "boundary_reason": rule.boundary_reason,
        "required_next_action": rule.required_next_action,
        "evidence_status": "present" if not evidence["missing_tokens"] else "missing",
        "evidence_tokens": list(rule.tokens),
        "missing_tokens": evidence["missing_tokens"],
        "evidence_lines": evidence["lines"],
    }


def _evidence_for_tokens(path: Path, tokens: tuple[str, ...]) -> dict[str, Any]:
    if not path.exists():
        return {"missing_tokens": list(tokens), "lines": []}
    lines = path.read_text(encoding="utf-8").splitlines()
    evidence_lines: list[dict[str, JSONValue]] = []
    missing: list[str] = []
    seen_lines: set[tuple[int, str]] = set()
    for token in tokens:
        match = _first_line_containing(lines, token)
        if match is None:
            missing.append(token)
            continue
        line_number, line = match
        key = (line_number, line)
        if key not in seen_lines:
            evidence_lines.append({"line": line_number, "text": line.strip()})
            seen_lines.add(key)
    return {"missing_tokens": missing, "lines": evidence_lines}


def _first_line_containing(lines: list[str], token: str) -> tuple[int, str] | None:
    for line_number, line in enumerate(lines, start=1):
        if token in line:
            return line_number, line
    return None


def _scan_summaries(hsr_root: Path) -> dict[str, JSONValue]:
    return {
        "runtime_value_binding_trace_mining_scan": _token_scan(
            hsr_root,
            roots=(
                "simulator_v8_clean_core/core",
                "simulator_v8_clean_core/systems",
                "simulator_v8_clean_core/rules",
            ),
            tokens=(
                "_skill_formula_binding_from_trace",
                "_numeric_binding_sources_from_trace",
                "fallback_basis",
                "fixed_numeric_expression",
                "character_config_dynamic_value_bindings",
            ),
            max_samples=12,
            requires_matrix_coverage=True,
        ),
        "content_ir_lookup_boundary_scan": _token_scan(
            hsr_root,
            roots=(
                "simulator_v8_clean_core/core",
                "simulator_v8_clean_core/systems",
                "simulator_v8_clean_core/scenarios",
            ),
            tokens=(
                "servant_definition(",
                "summon_monster_intent(",
                "monster_data_card_for_entity",
                "character_data_card_for_entity",
                "combatant_profile(",
            ),
            max_samples=16,
            requires_matrix_coverage=True,
        ),
        "runtime_unit_assembly_token_scan": _token_scan(
            hsr_root,
            roots=("simulator_v8_clean_core/systems", "simulator_v8_clean_core/scenarios"),
            tokens=("UnitState(", "combatant_profile", "monster_data_card_for_entity", "servant_definition"),
            max_samples=12,
            requires_matrix_coverage=True,
        ),
        "content_special_case_literal_scan": _token_scan(
            hsr_root,
            roots=("simulator_v8_clean_core/core", "simulator_v8_clean_core/systems", "simulator_v8_clean_core/rules"),
            tokens=("template_id ==", "action_id ==", "skill_id ==", "monster_id ==", "ByCompareMonsterID"),
            max_samples=12,
            requires_matrix_coverage=False,
        ),
        "ui_scenario_rule_surface_scan": _token_scan(
            hsr_root,
            roots=("simulator_v8_clean_core/scenarios", "simulator_v8_ui"),
            tokens=("target_ids", "selectable_target_ids", "damage_records", "skill_points", "timeline"),
            max_samples=12,
            requires_matrix_coverage=False,
        ),
    }


def _scan_coverage(rows: list[dict[str, JSONValue]], scan_summaries: dict[str, JSONValue]) -> dict[str, JSONValue]:
    matrix_paths = {str(row.get("path") or "") for row in rows}
    required_files: dict[str, list[str]] = {}
    for scan_name, raw_scan in scan_summaries.items():
        scan = raw_scan if isinstance(raw_scan, dict) else {}
        if scan.get("requires_matrix_coverage") is not True:
            continue
        for file_path in scan.get("matched_files") or ():
            if not isinstance(file_path, str) or not file_path:
                continue
            required_files.setdefault(file_path, []).append(str(scan_name))
    covered: list[dict[str, JSONValue]] = []
    excluded: list[dict[str, JSONValue]] = []
    uncovered: list[dict[str, JSONValue]] = []
    for file_path, scan_names in sorted(required_files.items()):
        if file_path in matrix_paths:
            covered.append({"path": file_path, "scan_names": scan_names})
            continue
        exclusion_reason = SCAN_COVERAGE_EXCLUSIONS.get(file_path)
        if exclusion_reason:
            excluded.append({"path": file_path, "scan_names": scan_names, "reason": exclusion_reason})
            continue
        uncovered.append({"path": file_path, "scan_names": scan_names})
    return {
        "required_file_count": len(required_files),
        "covered_file_count": len(covered),
        "excluded_file_count": len(excluded),
        "uncovered_file_count": len(uncovered),
        "covered_files": covered,
        "excluded_files": excluded,
        "uncovered_files": uncovered,
        "exclusion_policy": {
            path: reason for path, reason in sorted(SCAN_COVERAGE_EXCLUSIONS.items())
        },
    }


def _token_scan(
    hsr_root: Path,
    *,
    roots: tuple[str, ...],
    tokens: tuple[str, ...],
    max_samples: int,
    requires_matrix_coverage: bool,
) -> dict[str, JSONValue]:
    samples: list[dict[str, JSONValue]] = []
    counts: Counter[str] = Counter()
    counts_by_file: dict[str, Counter[str]] = {}
    files_scanned = 0
    for root in roots:
        root_path = hsr_root / root
        if not root_path.exists():
            continue
        for path in sorted(root_path.rglob("*")):
            if path.suffix not in {".py", ".js", ".json", ".md"}:
                continue
            files_scanned += 1
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            relative = path.relative_to(hsr_root).as_posix()
            for line_number, line in enumerate(lines, start=1):
                for token in tokens:
                    if token not in line:
                        continue
                    counts[token] += 1
                    counts_by_file.setdefault(relative, Counter())[token] += 1
                    if len(samples) < max_samples:
                        samples.append(
                            {
                                "path": relative,
                                "line": line_number,
                                "token": token,
                                "text": line.strip(),
                            }
                        )
    return {
        "files_scanned": files_scanned,
        "tokens": list(tokens),
        "requires_matrix_coverage": requires_matrix_coverage,
        "match_counts": dict(sorted(counts.items())),
        "matched_files": sorted(counts_by_file),
        "match_counts_by_file": {
            path: dict(sorted(file_counts.items()))
            for path, file_counts in sorted(counts_by_file.items())
        },
        "sample_count": len(samples),
        "samples": samples,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P6-S0 architecture boundary ledger.")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    result = run_validation(package_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} "
        f"rows={result['summary']['row_count']} "
        f"violations={result['summary']['violation_row_count']} "
        f"questions_checked={result['summary']['questions_checked']}/{result['summary']['question_count']} "
        f"classifications={result['summary']['classification_counts']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
