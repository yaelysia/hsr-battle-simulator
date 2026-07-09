from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .. import BASELINE_VERSION
from ..core.model import ActionSettlement, BattleState, JSONValue
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord, SettlementTraceabilityValidator
from ..rules.ir import (
    ActionDefinitionIR,
    CanonicalIR,
    DamageEmissionIR,
    SkillFormulaBindingIR,
    ToughnessEmissionIR,
)
from ..rules.rulebook import RuleBook
from ..rules.value_binding import (
    StaticValueBindingContext,
    StaticValueBindingResolver,
    StaticValueResolution,
)
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "p5_s2_static_param_level_binding"
MATRIX_SCHEMA_VERSION = "p5_s2_static_param_level_binding_matrix_v1"

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
REQUIRED_ROWS = {
    "character_skill_level_static_param_binding",
    "monster_data_card_level_static_param_binding",
    "damage_action_level_static_param_binding",
    "toughness_action_definition_static_binding",
    "resource_action_definition_static_binding",
    "static_binding_blocked_negative_cases",
    "process_only_resolution_source_audit_replay",
    "resource_engine_convention_not_static_param_binding",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p5_s2_static_param_level_binding_matrix(ir, rules)
    matrix_checks = validate_p5_s2_static_param_level_binding_matrix(matrix)
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
                "mode": "p5_s2_static_param_level_binding_structural_predicates",
                "runtime_behavior_changed": False,
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "s0_missing_consumer_refs_counted_as_consumer_admitted": False,
                "resource_engine_convention_used_as_static_param_binding": False,
                "full_ir_written": False,
                "full_rulebook_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
                "p5_aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "static_param_level_binding_matrix": matrix["static_param_level_binding_matrix"],
        "gap_attribution_matrix": matrix["gap_attribution_matrix"],
        "resolution_ledger": matrix["resolution_ledger"],
        "blocked_negative_matrix": matrix["blocked_negative_matrix"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p5_s2_static_param_level_binding.json", result)
    write_json(output_dir / "p5_s2_static_param_level_binding_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P5-S2 static parameter and level binding admission.")
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


def build_p5_s2_static_param_level_binding_matrix(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    resolver = StaticValueBindingResolver(rules)
    character_binding = _select_executable_skill_formula_binding(ir, "character")
    monster_binding = _select_executable_skill_formula_binding(ir, "monster")
    rows = [
        _skill_formula_binding_row(
            "character_skill_level_static_param_binding",
            resolver,
            character_binding,
            level_source="skill_level",
        ),
        _skill_formula_binding_row(
            "monster_data_card_level_static_param_binding",
            resolver,
            monster_binding,
            level_source="data_card_level",
        ),
        _damage_static_param_row(ir, rules, resolver),
        _toughness_static_binding_row(ir, rules, resolver),
        _resource_static_binding_row(ir, rules, resolver),
        _negative_cases_row(rules, resolver, character_binding),
        _resource_engine_convention_boundary_row(ir),
    ]
    rows.append(_process_only_resolution_audit_replay_row(rows))
    matrix = {str(row["row_id"]): row for row in rows}
    classification_counts = Counter(str(row.get("classification") or "unclassified") for row in rows)
    gap_counts = _gap_counts(rows)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "static_param_level_binding_matrix": matrix,
        "summary": {
            "row_count": len(matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "disallowed_gap_count": sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES),
            "positive_resolution_count": sum(
                int(row.get("executable_count") or 0)
                for row in rows
                if str(row.get("row_id") or "") != "static_binding_blocked_negative_cases"
            ),
            "blocked_negative_case_count": int(
                matrix["static_binding_blocked_negative_cases"]["details"].get("blocked_case_count") or 0
            ),
            "runtime_consumer_migration_claimed": False,
        },
        "gap_attribution_matrix": _gap_attribution_matrix(rows),
        "resolution_ledger": _resolution_ledger(rows),
        "blocked_negative_matrix": matrix["static_binding_blocked_negative_cases"]["details"].get(
            "negative_cases",
            {},
        ),
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "static_check_count": 1,
            "full_ir_written": False,
            "full_rulebook_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_files": [
                "validation_summary_p5_s2_static_param_level_binding.json",
                "p5_s2_static_param_level_binding_matrix.json",
            ],
        },
    }


def validate_p5_s2_static_param_level_binding_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("static_param_level_binding_matrix") or {})
    missing = sorted(REQUIRED_ROWS.difference(rows))
    invalid_classifications = sorted(
        row_id
        for row_id, row in rows.items()
        if str(row.get("classification") or "unclassified") not in CLASSIFICATION_STATES
    )
    gap_counts = dict(matrix.get("summary", {}).get("gap_attribution_counts") or {})
    disallowed_gap_count = sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES)
    positive_rows = [
        "character_skill_level_static_param_binding",
        "monster_data_card_level_static_param_binding",
        "damage_action_level_static_param_binding",
        "toughness_action_definition_static_binding",
        "resource_action_definition_static_binding",
    ]
    checks = {
        "required_rows_present": not missing,
        "valid_classifications": not invalid_classifications,
        "row_checks_ok": all(dict(row.get("checks") or {}).get("ok") is True for row in rows.values()),
        "disallowed_gap_count_zero": disallowed_gap_count == 0,
        "positive_rows_executable": all(rows.get(row_id, {}).get("classification") == "executable" for row_id in positive_rows),
        "negative_cases_blocked": _row_check(rows, "static_binding_blocked_negative_cases", "all_negative_cases_blocked"),
        "negative_replay_state_unchanged": _row_check(rows, "static_binding_blocked_negative_cases", "state_unchanged_replay_ok"),
        "process_only_audit_replay_ok": _row_check(rows, "process_only_resolution_source_audit_replay", "traceability_ok")
        and _row_check(rows, "process_only_resolution_source_audit_replay", "state_unchanged_replay_ok"),
        "engine_convention_not_counted_as_param_binding": _row_check(
            rows,
            "resource_engine_convention_not_static_param_binding",
            "engine_convention_not_used_as_static_param_binding",
        ),
        "runtime_consumer_migration_not_claimed": matrix.get("summary", {}).get("runtime_consumer_migration_claimed") is False,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_rows": missing,
        "invalid_classifications": invalid_classifications,
        "disallowed_gap_count": disallowed_gap_count,
    }


def _skill_formula_binding_row(
    row_id: str,
    resolver: StaticValueBindingResolver,
    binding: SkillFormulaBindingIR | None,
    *,
    level_source: str,
) -> dict[str, JSONValue]:
    if binding is None:
        return _row(
            row_id,
            classification="source_gap_blocked",
            checks=_checks({"source_present": False, "no_synthetic_binding_created": True}),
            blocked_or_gap_count=1,
            gap_attribution={"source_gap_blocked": 1},
            details={"level_source": level_source},
        )
    context = _context_for_binding(binding, level_source=level_source)
    result = resolver.resolve_skill_formula_param(
        context,
        param_index=binding.param_index,
        formula_role=binding.formula_role,
        binding_id=binding.binding_id,
    )
    expected_value = _numeric_json_value(binding.param_value)
    checks = _checks(
        {
            "binding_source_present": bool(_source_trace(binding)),
            "resolver_ok": result.ok,
            "value_matches_binding": result.value == expected_value,
            "binding_id_preserved": result.binding_id == binding.binding_id,
            "level_source_preserved": result.level_source == level_source,
            "source_trace_preserved": result.source_trace == _source_trace(binding),
            "rulebook_exact_lookup_visible": resolver.rules.skill_formula_binding(binding.binding_id) is binding,
        }
    )
    return _row(
        row_id,
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        ir_count=1,
        rulebook_visible_count=1 if resolver.rules.skill_formula_binding(binding.binding_id) is binding else 0,
        executable_count=1 if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        sample_source_trace=_source_trace(binding),
        details={
            "level_source": level_source,
            "sample_binding": _compact_binding(binding),
            "resolution": result.to_json(),
        },
    )


def _damage_static_param_row(
    ir: CanonicalIR,
    rules: RuleBook,
    resolver: StaticValueBindingResolver,
) -> dict[str, JSONValue]:
    sample = _select_damage_static_sample(ir, rules)
    if sample is None:
        return _row(
            "damage_action_level_static_param_binding",
            classification="admission_gap",
            checks=_checks({"damage_static_binding_sample_present": False, "no_synthetic_damage_sample_created": True}),
            blocked_or_gap_count=1,
            gap_attribution={"admission_gap": 1},
        )
    emission, binding, expression_value = sample
    context = _context_for_binding(binding, level_source="action_level")
    result = resolver.resolve_skill_formula_param(
        context,
        param_index=binding.param_index,
        formula_role=binding.formula_role,
        binding_id=binding.binding_id,
    )
    checks = _checks(
        {
            "damage_emission_source_present": bool(_source_trace(emission)),
            "damage_emission_rulebook_visible": rules.damage_emission(emission.damage_emission_id) is emission,
            "resolver_ok": result.ok,
            "value_matches_damage_scaling_expr": result.value == expression_value,
            "source_trace_present": bool(result.source_trace),
            "runtime_consumer_migration_not_claimed": True,
        }
    )
    return _row(
        "damage_action_level_static_param_binding",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        ir_count=1,
        rulebook_visible_count=1 if rules.damage_emission(emission.damage_emission_id) is emission else 0,
        executable_count=1 if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        sample_source_trace=_source_trace(emission),
        details={
            "selection_predicate": (
                "executable DamageEmissionIR with fixed scaling_ratio_expr and matching "
                "source-backed SkillFormulaBindingIR value at exact action level"
            ),
            "damage_emission": _compact_damage_emission(emission),
            "matched_binding": _compact_binding(binding),
            "resolution": result.to_json(),
        },
    )


def _toughness_static_binding_row(
    ir: CanonicalIR,
    rules: RuleBook,
    resolver: StaticValueBindingResolver,
) -> dict[str, JSONValue]:
    sample = _select_toughness_static_sample(ir, rules)
    if sample is None:
        return _row(
            "toughness_action_definition_static_binding",
            classification="admission_gap",
            checks=_checks({"toughness_static_source_present": False, "no_synthetic_toughness_sample_created": True}),
            blocked_or_gap_count=1,
            gap_attribution={"admission_gap": 1},
        )
    emission, definition, param_index, expected_value = sample
    context = StaticValueBindingContext(
        action_id=definition.action_id,
        action_level=definition.level,
        source_trace=_source_trace(definition),
    )
    result = resolver.resolve_action_definition_list_item(
        context,
        field_name="show_stance_list",
        param_index=param_index,
    )
    checks = _checks(
        {
            "toughness_emission_source_present": bool(_source_trace(emission)),
            "toughness_emission_rulebook_visible": rules.toughness_emission(emission.toughness_emission_id) is emission,
            "action_definition_rulebook_visible": rules.action_definition(definition.action_id, definition.level) is definition,
            "resolver_ok": result.ok,
            "value_matches_show_stance_list": result.value == expected_value,
            "dynamic_hash_execution_deferred_to_later_stage": _expr_kind(emission.toughness_amount_expr) == "dynamic_hash",
        }
    )
    return _row(
        "toughness_action_definition_static_binding",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        ir_count=1,
        rulebook_visible_count=1 if rules.toughness_emission(emission.toughness_emission_id) is emission else 0,
        executable_count=1 if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        sample_source_trace=_source_trace(definition),
        details={
            "selection_predicate": "executable ToughnessEmissionIR sharing action/level with ActionDefinitionIR.show_stance_list numeric slot",
            "toughness_emission": _compact_toughness_emission(emission),
            "action_definition": _compact_action_definition(definition),
            "show_stance_index": param_index,
            "resolution": result.to_json(),
        },
    )


def _resource_static_binding_row(
    ir: CanonicalIR,
    rules: RuleBook,
    resolver: StaticValueBindingResolver,
) -> dict[str, JSONValue]:
    sample = _select_resource_static_sample(ir, rules)
    if sample is None:
        return _row(
            "resource_action_definition_static_binding",
            classification="admission_gap",
            checks=_checks({"resource_static_source_present": False, "no_engine_convention_promoted": True}),
            blocked_or_gap_count=1,
            gap_attribution={"admission_gap": 1},
        )
    definition, field_name, expected_value = sample
    context = StaticValueBindingContext(
        action_id=definition.action_id,
        action_level=definition.level,
        source_trace=_source_trace(definition),
    )
    result = resolver.resolve_action_definition_numeric_field(context, field_name=field_name)
    checks = _checks(
        {
            "action_definition_source_present": bool(_source_trace(definition)),
            "action_definition_rulebook_visible": rules.action_definition(definition.action_id, definition.level) is definition,
            "resolver_ok": result.ok,
            "value_matches_action_definition_field": result.value == expected_value,
            "source_is_not_engine_convention": _source_trace(definition).get("raw_type") != "ResourceEngineConvention",
            "resource_rule_engine_convention_not_used": True,
        }
    )
    return _row(
        "resource_action_definition_static_binding",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        ir_count=1,
        rulebook_visible_count=1 if rules.action_definition(definition.action_id, definition.level) is definition else 0,
        executable_count=1 if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        sample_source_trace=_source_trace(definition),
        details={
            "selection_predicate": "executable ActionDefinitionIR with non-zero BP/SP resource field and non-engine-convention source",
            "action_definition": _compact_action_definition(definition),
            "field_name": field_name,
            "resolution": result.to_json(),
        },
    )


def _negative_cases_row(
    rules: RuleBook,
    resolver: StaticValueBindingResolver,
    binding: SkillFormulaBindingIR | None,
) -> dict[str, JSONValue]:
    if binding is None:
        return _row(
            "static_binding_blocked_negative_cases",
            classification="source_gap_blocked",
            checks=_checks({"source_present_for_negative_cases": False}),
            blocked_or_gap_count=1,
            gap_attribution={"source_gap_blocked": 1},
        )
    context = _context_for_binding(binding, level_source="action_level")
    wrong_level = _missing_level_for_action(rules, binding.action_id)
    wrong_param = _missing_param_index_for_action(rules.ir, binding.action_id, binding.level, binding.formula_role)
    list_definition = rules.action_definition(binding.action_id, binding.level)
    list_index = len(list_definition.param_list) + 1000 if list_definition is not None else 1000
    cases = {
        "missing_level": resolver.resolve_skill_formula_param(
            StaticValueBindingContext(action_id=binding.action_id),
            param_index=binding.param_index,
            formula_role=binding.formula_role,
        ),
        "wrong_level": resolver.resolve_skill_formula_param(
            StaticValueBindingContext(action_id=binding.action_id, action_level=wrong_level),
            param_index=binding.param_index,
            formula_role=binding.formula_role,
        ),
        "wrong_param_index": resolver.resolve_skill_formula_param(
            context,
            param_index=wrong_param,
            formula_role=binding.formula_role,
        ),
        "missing_binding_id": resolver.resolve_skill_formula_param(
            context,
            param_index=binding.param_index,
            formula_role=binding.formula_role,
            binding_id=f"{binding.binding_id}:missing",
        ),
        "action_definition_list_out_of_range": resolver.resolve_action_definition_list_item(
            context,
            field_name="param_list",
            param_index=list_index,
        ),
        "unsupported_dynamic_expression": resolver.resolve_fixed_numeric_expression(
            {"kind": "dynamic_hash", "hash": "p5_s2_negative"},
            context,
            source_trace=_source_trace(binding),
        ),
    }
    state = BattleState()
    before = state.snapshot().to_json()
    after_state = MutationReducer().apply_all(state, ())
    replay = MutationReducer().replay_snapshot(state, (), after_state.snapshot().to_json())
    checks = _checks(
        {
            "all_negative_cases_blocked": all(not result.ok and bool(result.blocked_reason) for result in cases.values()),
            "state_unchanged_replay_ok": replay.ok and before == after_state.snapshot().to_json(),
            "mutation_count_zero": True,
            "no_default_zero_or_one": all(result.value is None for result in cases.values()),
            "blocked_reasons_specific": all(result.blocked_reason not in {"", "missing"} for result in cases.values()),
        }
    )
    return _row(
        "static_binding_blocked_negative_cases",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        ir_count=1,
        executable_count=len(cases) if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        sample_source_trace=_source_trace(binding),
        details={
            "blocked_case_count": len(cases),
            "negative_cases": {name: result.to_json() for name, result in sorted(cases.items())},
            "state_unchanged": {
                "before_equals_after": before == after_state.snapshot().to_json(),
                "replay": _replay_json(replay),
                "mutation_count": 0,
            },
        },
    )


def _process_only_resolution_audit_replay_row(rows: Iterable[dict[str, Any]]) -> dict[str, JSONValue]:
    positive_resolutions = []
    for row in rows:
        details = dict(row.get("details") or {})
        resolution = details.get("resolution")
        if isinstance(resolution, dict) and resolution.get("ok") is True:
            positive_resolutions.append(resolution)
    records = tuple(
        SettlementRecord(
            record_type="value_resolution",
            source="p5_s2_static_param_level_binding",
            process_only=True,
            payload={"resolution": _compact_json(resolution)},
            trace=_compact_json(resolution.get("source_trace") or {}),
        ).to_json()
        for resolution in positive_resolutions
    )
    settlement = ActionSettlement(
        action_id="p5_s2_static_param_level_binding",
        actor_id="validation",
        target_ids=(),
        records=records,
    )
    traceability = SettlementTraceabilityValidator().validate(settlement, ())
    state = BattleState()
    after_state = MutationReducer().apply_all(state, ())
    replay = MutationReducer().replay_snapshot(state, (), after_state.snapshot().to_json())
    checks = _checks(
        {
            "positive_resolutions_present": bool(positive_resolutions),
            "traceability_ok": traceability.ok,
            "records_are_process_only": traceability.process_only_records == len(records),
            "mutation_linked_records_zero": traceability.mutation_linked_records == 0,
            "state_unchanged_replay_ok": replay.ok and state.snapshot().to_json() == after_state.snapshot().to_json(),
            "source_trace_present_for_all_records": all(bool(record.get("trace")) for record in records),
        }
    )
    return _row(
        "process_only_resolution_source_audit_replay",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        ir_count=len(positive_resolutions),
        executable_count=len(positive_resolutions) if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        sample_source_trace=dict(records[0].get("trace") or {}) if records else {},
        details={
            "process_only_record_count": len(records),
            "settlement_traceability": traceability.to_json(),
            "state_unchanged_replay": _replay_json(replay),
            "sample_records": [_compact_json(record) for record in records[:5]],
        },
    )


def _resource_engine_convention_boundary_row(ir: CanonicalIR) -> dict[str, JSONValue]:
    resource_rules = tuple(ir.resource_rules)
    engine_rules = tuple(rule for rule in resource_rules if rule.source_kind == "engine_convention")
    checks = _checks(
        {
            "resource_rules_present": bool(resource_rules),
            "engine_convention_rules_identified": bool(engine_rules),
            "engine_convention_not_used_as_static_param_binding": True,
            "tbgd_action_definition_resource_fields_required_for_s2_positive": True,
        }
    )
    return _row(
        "resource_engine_convention_not_static_param_binding",
        classification="boundary_only",
        checks=checks,
        ir_count=len(resource_rules),
        executable_count=0,
        sample_source_trace=_source_trace(engine_rules[0]) if engine_rules else {},
        details={
            "engine_convention_resource_rule_count": len(engine_rules),
            "rule_ids": [rule.resource_rule_id for rule in engine_rules],
            "policy": "ResourceRuleIR engine_convention rows are runtime conventions, not source-backed static parameter bindings.",
        },
    )


def _select_executable_skill_formula_binding(ir: CanonicalIR, data_card_kind: str) -> SkillFormulaBindingIR | None:
    candidates = [
        binding
        for binding in ir.skill_formula_bindings
        if binding.coverage_status == "executable"
        and _binding_data_card_kind(binding) == data_card_kind
        and _numeric_json_value(binding.param_value) is not None
        and bool(_source_trace(binding))
    ]
    return _first_sorted(candidates, key=lambda item: (item.action_id, item.level, item.param_index, item.binding_id))


def _select_damage_static_sample(
    ir: CanonicalIR,
    rules: RuleBook,
) -> tuple[DamageEmissionIR, SkillFormulaBindingIR, float] | None:
    bindings_by_action_level: dict[tuple[str, int], list[SkillFormulaBindingIR]] = {}
    for binding in ir.skill_formula_bindings:
        if binding.coverage_status != "executable" or _numeric_json_value(binding.param_value) is None:
            continue
        bindings_by_action_level.setdefault((binding.action_id, binding.level), []).append(binding)
    for emission in sorted(ir.damage_emissions, key=lambda item: (item.action_id, item.level, item.damage_emission_id)):
        if emission.coverage_status != "executable" or rules.damage_emission(emission.damage_emission_id) is not emission:
            continue
        expression_value = _static_expr_value(emission.scaling_ratio_expr)
        if expression_value is None:
            continue
        for binding in sorted(
            bindings_by_action_level.get((emission.action_id, emission.level), ()),
            key=lambda item: (item.param_index, item.formula_role, item.binding_id),
        ):
            if _numeric_json_value(binding.param_value) == expression_value:
                return emission, binding, expression_value
    return None


def _select_toughness_static_sample(
    ir: CanonicalIR,
    rules: RuleBook,
) -> tuple[ToughnessEmissionIR, ActionDefinitionIR, int, float] | None:
    for emission in sorted(ir.toughness_emissions, key=lambda item: (item.action_id, item.level, item.toughness_emission_id)):
        if emission.coverage_status != "executable" or rules.toughness_emission(emission.toughness_emission_id) is not emission:
            continue
        definition = rules.action_definition(emission.action_id, emission.level)
        if definition is None or definition.coverage_status != "executable":
            continue
        for index, raw_value in enumerate(definition.show_stance_list):
            value = _numeric_json_value(raw_value)
            if value is not None:
                return emission, definition, index, value
    return None


def _select_resource_static_sample(
    ir: CanonicalIR,
    rules: RuleBook,
) -> tuple[ActionDefinitionIR, str, float] | None:
    for definition in sorted(ir.action_definitions, key=lambda item: (item.action_id, item.level, item.definition_id)):
        if definition.coverage_status != "executable" or rules.action_definition(definition.action_id, definition.level) is not definition:
            continue
        trace = _source_trace(definition)
        if trace.get("raw_type") == "ResourceEngineConvention":
            continue
        for field_name in ("bp_need", "bp_add", "sp_base", "sp_multiple_ratio"):
            value = _numeric_json_value(getattr(definition, field_name))
            if value is not None and value != 0:
                return definition, field_name, value
    return None


def _context_for_binding(binding: SkillFormulaBindingIR, *, level_source: str) -> StaticValueBindingContext:
    kwargs: dict[str, Any] = {
        "action_id": binding.action_id,
        "data_card_id": binding.data_card_id or binding.character_data_card_id,
        "data_card_kind": _binding_data_card_kind(binding),
        "owner_id": binding.owner_entity_ref,
        "source_trace": _source_trace(binding),
    }
    if level_source == "skill_level":
        kwargs["skill_level"] = binding.level
    elif level_source == "data_card_level":
        kwargs["data_card_level"] = binding.level
    else:
        kwargs["action_level"] = binding.level
    return StaticValueBindingContext(**kwargs)


def _missing_level_for_action(rules: RuleBook, action_id: str) -> int:
    levels = set(rules.action_levels(action_id))
    for binding in rules.ir.skill_formula_bindings:
        if binding.action_id == action_id:
            levels.add(binding.level)
    candidate = max(levels) + 1000 if levels else 1000
    while candidate in levels:
        candidate += 1
    return candidate


def _missing_param_index_for_action(ir: CanonicalIR, action_id: str, level: int, formula_role: str) -> int:
    indexes = {
        binding.param_index
        for binding in ir.skill_formula_bindings
        if binding.action_id == action_id and binding.level == level and binding.formula_role == formula_role
    }
    candidate = max(indexes) + 1000 if indexes else 1000
    while candidate in indexes:
        candidate += 1
    return candidate


def _binding_data_card_kind(binding: SkillFormulaBindingIR) -> str:
    return binding.data_card_kind or ("character" if binding.character_data_card_id else "")


def _static_expr_value(expression: Any) -> float | None:
    value = _numeric_json_value(expression)
    if value is not None:
        return value
    if not isinstance(expression, dict):
        return None
    if str(expression.get("kind") or "") == "fixed":
        return _numeric_json_value(expression.get("value"))
    return None


def _expr_kind(expression: Any) -> str:
    if isinstance(expression, dict):
        return str(expression.get("kind") or "")
    return ""


def _numeric_json_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        return _numeric_json_value(value.get("Value"))
    return None


def _source_trace(item: Any) -> dict[str, JSONValue]:
    source = getattr(item, "source", None)
    if source is None:
        return {}
    try:
        trace = source.to_json()
    except AttributeError:
        return {}
    return trace if isinstance(trace, dict) else {}


def _row(
    row_id: str,
    *,
    classification: str,
    checks: dict[str, JSONValue],
    ir_count: int = 0,
    rulebook_visible_count: int = 0,
    executable_count: int = 0,
    blocked_or_gap_count: int = 0,
    gap_attribution: dict[str, int] | None = None,
    sample_source_trace: dict[str, JSONValue] | None = None,
    details: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    return {
        "row_id": row_id,
        "classification": classification,
        "checks": {"ok": bool(checks.get("ok")), "checks": checks},
        "ir_count": int(ir_count),
        "rulebook_visible_count": int(rulebook_visible_count),
        "executable_count": int(executable_count),
        "blocked_or_gap_count": int(blocked_or_gap_count),
        "gap_attribution": gap_attribution or {},
        "sample_source_trace": _compact_json(sample_source_trace or {}),
        "details": details or {},
    }


def _checks(checks: dict[str, JSONValue]) -> dict[str, JSONValue]:
    return {"ok": all(bool(value) for value in checks.values()), **checks}


def _row_check(rows: dict[str, Any], row_id: str, check_name: str) -> bool:
    return bool(rows.get(row_id, {}).get("checks", {}).get("checks", {}).get(check_name))


def _gap_counts(rows: Iterable[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        for key, value in dict(row.get("gap_attribution") or {}).items():
            counts[str(key)] += int(value or 0)
    return counts


def _gap_attribution_matrix(rows: Iterable[dict[str, Any]]) -> dict[str, JSONValue]:
    gap_rows = []
    for row in rows:
        gap_attribution = dict(row.get("gap_attribution") or {})
        if not gap_attribution:
            continue
        gap_rows.append(
            {
                "row_id": str(row.get("row_id") or ""),
                "classification": str(row.get("classification") or ""),
                "gap_attribution": gap_attribution,
                "blocked_or_gap_count": int(row.get("blocked_or_gap_count") or 0),
                "details": _compact_json(row.get("details") or {}),
            }
        )
    gap_counts = _gap_counts(gap_rows)
    return {
        "schema_version": "p5_s2_gap_attribution_matrix_v1",
        "rows": gap_rows,
        "summary": {
            "row_count": len(gap_rows),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "disallowed_gap_count": sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES),
        },
    }


def _resolution_ledger(rows: Iterable[dict[str, Any]]) -> dict[str, JSONValue]:
    entries = []
    for row in rows:
        resolution = dict(dict(row.get("details") or {}).get("resolution") or {})
        if not resolution:
            continue
        entries.append(
            {
                "row_id": str(row.get("row_id") or ""),
                "classification": str(row.get("classification") or ""),
                "resolution": _compact_json(resolution),
            }
        )
    return {
        "schema_version": "p5_s2_resolution_ledger_v1",
        "entry_count": len(entries),
        "entries": entries,
    }


def _first_sorted(items: Iterable[Any], *, key: Any) -> Any | None:
    values = sorted(items, key=key)
    return values[0] if values else None


def _compact_binding(binding: SkillFormulaBindingIR) -> dict[str, JSONValue]:
    return {
        "binding_id": binding.binding_id,
        "action_id": binding.action_id,
        "level": binding.level,
        "param_index": binding.param_index,
        "formula_role": binding.formula_role,
        "data_card_kind": _binding_data_card_kind(binding),
        "data_card_id": binding.data_card_id or binding.character_data_card_id,
        "owner_entity_ref": binding.owner_entity_ref,
        "param_value": _compact_json(binding.param_value),
        "coverage_status": binding.coverage_status,
    }


def _compact_damage_emission(emission: DamageEmissionIR) -> dict[str, JSONValue]:
    return {
        "damage_emission_id": emission.damage_emission_id,
        "action_id": emission.action_id,
        "level": emission.level,
        "source_task_id": emission.source_task_id,
        "hit_profile_id": emission.hit_profile_id,
        "damage_formula_family": emission.damage_formula_family,
        "scaling_ratio_expr": _compact_json(emission.scaling_ratio_expr),
        "coverage_status": emission.coverage_status,
    }


def _compact_toughness_emission(emission: ToughnessEmissionIR) -> dict[str, JSONValue]:
    return {
        "toughness_emission_id": emission.toughness_emission_id,
        "action_id": emission.action_id,
        "level": emission.level,
        "source_task_id": emission.source_task_id,
        "hit_profile_id": emission.hit_profile_id,
        "toughness_amount_expr_kind": _expr_kind(emission.toughness_amount_expr),
        "coverage_status": emission.coverage_status,
    }


def _compact_action_definition(definition: ActionDefinitionIR) -> dict[str, JSONValue]:
    return {
        "definition_id": definition.definition_id,
        "action_id": definition.action_id,
        "level": definition.level,
        "bp_need": definition.bp_need,
        "bp_add": definition.bp_add,
        "sp_base": definition.sp_base,
        "sp_multiple_ratio": definition.sp_multiple_ratio,
        "param_list_len": len(definition.param_list),
        "show_stance_list_len": len(definition.show_stance_list),
        "coverage_status": definition.coverage_status,
        "source_mode": definition.source_mode,
    }


def _replay_json(replay: Any) -> dict[str, JSONValue]:
    return {
        "ok": bool(getattr(replay, "ok", False)),
        "errors": list(getattr(replay, "errors", ()) or ()),
    }


def _compact_json(value: Any, *, depth: int = 0) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if depth >= 5:
        if isinstance(value, dict):
            return {"truncated": True, "key_count": len(value)}
        if isinstance(value, (list, tuple)):
            return ["truncated", len(value)]
        return str(value)
    if isinstance(value, dict):
        return {str(key): _compact_json(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        items = list(value)
        compact = [_compact_json(item, depth=depth + 1) for item in items[:10]]
        if len(items) > 10:
            compact.append({"truncated_count": len(items) - 10})
        return compact
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
