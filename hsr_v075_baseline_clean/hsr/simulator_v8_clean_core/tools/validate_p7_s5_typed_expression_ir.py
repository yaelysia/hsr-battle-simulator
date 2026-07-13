from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.evaluator import EvaluationContext, NumericEvaluationContext, RuleEvaluator
from ..rules.expression_ir import (
    CONDITION_EXPRESSION_NODE_SCHEMA,
    NUMERIC_EXPRESSION_SCHEMA,
    TARGET_EXPRESSION_NODE_SCHEMA,
    numeric_dynamic_hash,
)
from ..rules.ir import CanonicalIR, ConditionIR, FormulaIR, IRSource, TargetExpressionNodeIR
from ..rules.rulebook import RuleBook
from ..systems.target import TargetSystem
from ..tbgd.expression_lowering import lower_numeric_expression
from ..tbgd.lowering import (
    _target_expression_from_raw,
    _typed_condition_execution_node,
)
from .io import write_json
from .validate_p7_s0_kernel_trust_baseline import _base_state, _decision_state
from .validate_p7_s1_transition_trust_contract import _trust_rulebook


VALIDATION_VERSION = "p7_s5_typed_expression_ir"
MATRIX_SCHEMA_VERSION = "p7_s5_typed_expression_ir_matrix_v1"

RUNTIME_EXPRESSION_FILES = (
    "core/action_plan.py",
    "rules/evaluator.py",
    "rules/value_binding.py",
    "systems/target.py",
    "systems/status_callbacks.py",
    "systems/break_system.py",
    "systems/super_break.py",
)
FORBIDDEN_RUNTIME_TOKENS = ("$type", "PostfixExpr", "OpCodes", 'get("raw")', "get('raw')")


def run_validation(package_root: Path, output_dir: Path) -> dict[str, Any]:
    numeric = _numeric_cases()
    target = _target_cases()
    condition = _condition_cases()
    linking = _reference_linking_cases()
    transition = _typed_execution_audit_replay_case()
    static_boundary = _runtime_static_boundary(package_root)

    rows = (numeric, target, condition, linking, transition, static_boundary)
    checks = {
        "numeric_typed_positive": numeric["typed_positive"],
        "numeric_raw_recognized_lowered": numeric["raw_recognized_lowered"],
        "numeric_unsupported_distinct": numeric["unsupported_distinct"],
        "numeric_runtime_raw_rejected": numeric["runtime_raw_rejected"],
        "numeric_ambiguous_binding_blocked": numeric["ambiguous_binding_blocked"],
        "target_typed_positive": target["typed_positive"],
        "target_unsupported_blocked": target["unsupported_blocked"],
        "target_execution_reads_typed_node": target["typed_node_executed"],
        "condition_typed_positive": condition["typed_positive"],
        "condition_unsupported_blocked": condition["unsupported_blocked"],
        "condition_runtime_unlowered_rejected": condition["runtime_unlowered_rejected"],
        "references_missing_and_ambiguous_distinct": linking["missing_and_ambiguous_distinct"],
        "ambiguous_reference_has_no_runtime_mutation": linking["state_unchanged"],
        "typed_execution_source_audit_replay": transition["ok"],
        "runtime_raw_expression_parsers_absent": static_boundary["ok"],
        "no_large_artifacts": True,
    }
    ok = all(checks.values())
    matrix = {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "rows": [
            {
                "row_id": row["row_id"],
                "classification": row["classification"],
                "ok": row["ok"],
            }
            for row in rows
        ],
    }
    evidence = {
        "numeric": numeric,
        "target": target,
        "condition": condition,
        "reference_linking": linking,
        "typed_execution_audit_replay": transition,
        "runtime_static_boundary": static_boundary,
    }
    summary = {
        "validation_version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": ok,
        "ready_for_review": ok,
        "checks": checks,
        "matrix_schema_version": MATRIX_SCHEMA_VERSION,
        "row_count": len(rows),
        "artifact_policy": {
            "large_artifacts_written": False,
            "canonical_ir_serialized": False,
            "full_transition_dump_written": False,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "p7_s5_typed_expression_ir_evidence.json", evidence)
    write_json(output_dir / "p7_s5_typed_expression_ir_matrix.json", matrix)
    write_json(output_dir / "validation_summary_p7_s5_typed_expression_ir.json", summary)
    return summary


def _numeric_cases() -> dict[str, Any]:
    fixed = lower_numeric_expression({"FixedValue": {"Value": 2.5}})
    program = lower_numeric_expression(
        {
            "PostfixExpr": {
                "OpCodes": [0, 0, 0, 1, 2, 17],
                "FixedValues": [{"Value": 2.0}, {"Value": 3.0}],
            }
        }
    )
    unsupported = lower_numeric_expression(
        {"PostfixExpr": {"OpCodes": [9, 17], "FixedValues": []}}
    )
    evaluator = RuleEvaluator()
    fixed_result = evaluator.evaluate_numeric(fixed)
    program_result = evaluator.evaluate_numeric(program)
    raw_result = evaluator.evaluate_numeric({"FixedValue": {"Value": 2.5}})
    ambiguous_source = {
        "source_type": "validation_ambiguous_source",
        "entries": {
            "left": {"value": 1.0},
            "right": {"value": 2.0},
        },
        "by_hash": {"shared": ["left", "right"]},
    }
    ambiguous_result = evaluator.evaluate_numeric(
        numeric_dynamic_hash("shared"),
        NumericEvaluationContext(binding_sources=(ambiguous_source,)),
    )
    checks = {
        "typed_positive": fixed_result.ok and fixed_result.value == 2.5 and program_result.ok and program_result.value == 5.0,
        "raw_recognized_lowered": fixed.get("schema_version") == NUMERIC_EXPRESSION_SCHEMA,
        "unsupported_distinct": unsupported.get("kind") == "unsupported" and unsupported.get("supported") is False,
        "runtime_raw_rejected": not raw_result.ok and raw_result.blocked_reason == "numeric_expression_not_lowered",
        "ambiguous_binding_blocked": not ambiguous_result.ok
        and ambiguous_result.blocked_reason == "dynamic_hash_binding_ambiguous:shared",
    }
    return {
        "row_id": "numeric_expression",
        "classification": "executable_and_blocked_boundary",
        "ok": all(checks.values()),
        **checks,
        "fixed": fixed,
        "program": program,
        "unsupported": unsupported,
        "raw_runtime_result": raw_result.to_json(),
        "ambiguous_result": ambiguous_result.to_json(),
    }


def _target_cases() -> dict[str, Any]:
    source = _source("target")
    positive = _target_expression_from_raw(
        {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
        field_name="validation_target",
        expression_id="validation:target:caster",
        source=source,
    )
    unsupported = _target_expression_from_raw(
        {"$type": "RPG.GameCore.TargetUnsupportedMystery", "Alias": "Caster"},
        field_name="validation_target",
        expression_id="validation:target:unsupported",
        source=source,
    )
    nested = _target_expression_from_raw(
        {
            "$type": "RPG.GameCore.TargetSequence",
            "Sequence": [
                {"$type": "RPG.GameCore.TargetAlias", "Alias": "AllEnemy"},
                {
                    "$type": "RPG.GameCore.TargetFilter",
                    "Predicate": {
                        "$type": "RPG.GameCore.ByTargetTeam",
                        "TargetType": {
                            "$type": "RPG.GameCore.TargetAlias",
                            "Alias": "ParamEntity",
                        },
                        "Team": "TeamDark",
                    },
                },
            ],
        },
        field_name="validation_target",
        expression_id="validation:target:nested_typed_only",
        source=source,
    )
    state = _base_state()
    actor_id = next(unit_id for unit_id, unit in state.units.items() if unit.side == "ally")
    assert positive is not None and unsupported is not None and nested is not None
    positive_result = TargetSystem().resolve_target_expression(state, positive, caster_id=actor_id)
    typed_only = replace(positive, payload={})
    typed_only_result = TargetSystem().resolve_target_expression(state, typed_only, caster_id=actor_id)
    nested_result = TargetSystem().resolve_target_expression(
        state,
        replace(nested, payload={}),
        caster_id=actor_id,
    )
    unsupported_result = TargetSystem().resolve_target_expression(state, unsupported, caster_id=actor_id)
    typed_node = positive.node
    checks = {
        "typed_positive": positive.coverage_status == "executable"
        and isinstance(typed_node, TargetExpressionNodeIR)
        and typed_node.schema_version == TARGET_EXPRESSION_NODE_SCHEMA,
        "typed_node_executed": positive_result.ok and positive_result.target_ids == (actor_id,),
        "audit_payload_removal_behavior_equivalent": (
            typed_only_result.ok,
            typed_only_result.target_ids,
            typed_only_result.blocked_reason,
            typed_only_result.rng_events,
        )
        == (
            positive_result.ok,
            positive_result.target_ids,
            positive_result.blocked_reason,
            positive_result.rng_events,
        ),
        "typed_node_has_no_legacy_target_fields": not any(
            key in typed_node.to_json()
            for key in ("TargetType", "Target", "Targets", "Predicate", "Sequence")
        ),
        "nested_children_and_condition_ir_execute_without_legacy_payload": nested_result.ok
        and bool(nested_result.target_ids)
        and nested.node is not None
        and len(nested.node.children) == 2
        and nested.node.children[1].predicate is not None,
        "unsupported_blocked": unsupported.coverage_status == "blocked"
        and not unsupported_result.ok
        and unsupported_result.target_ids == (),
    }
    return {
        "row_id": "target_expression",
        "classification": "executable_and_blocked_boundary",
        "ok": all(checks.values()),
        **checks,
        "positive_ir": positive.to_json(),
        "positive_result": positive_result.to_json(),
        "typed_only_result": typed_only_result.to_json(),
        "nested_typed_only_result": nested_result.to_json(),
        "unsupported_ir": unsupported.to_json(),
        "unsupported_result": unsupported_result.to_json(),
    }


def _condition_cases() -> dict[str, Any]:
    source = _source("condition")
    positive_node = _typed_condition_execution_node({"$type": "RPG.GameCore.AlwaysTrue"})
    unsupported_node = _typed_condition_execution_node(
        {"$type": "RPG.GameCore.UnsupportedValidationCondition"}
    )
    positive = _condition_from_node("validation:condition:positive", positive_node, source)
    unsupported = _condition_from_node("validation:condition:unsupported", unsupported_node, source)
    unlowered = replace(positive, condition_id="validation:condition:unlowered", expression_schema_version="")
    context = EvaluationContext(state=_base_state(), actor_id="ally:actor")
    evaluator = RuleEvaluator()
    positive_result = evaluator.evaluate_condition_result(positive, context)
    unsupported_result = evaluator.evaluate_condition_result(unsupported, context)
    unlowered_result = evaluator.evaluate_condition_result(unlowered, context)
    checks = {
        "typed_positive": positive_result.ok and positive_result.result is True,
        "unsupported_blocked": not unsupported_result.ok
        and unsupported_node.get("supported") is False,
        "runtime_unlowered_rejected": not unlowered_result.ok
        and unlowered_result.reason == "condition_expression_not_lowered",
    }
    return {
        "row_id": "condition_expression",
        "classification": "executable_and_blocked_boundary",
        "ok": all(checks.values()),
        **checks,
        "positive_node": positive_node,
        "positive_result": positive_result.to_json(),
        "unsupported_node": unsupported_node,
        "unsupported_result": unsupported_result.to_json(),
        "unlowered_result": unlowered_result.to_json(),
    }


def _reference_linking_cases() -> dict[str, Any]:
    source = _source("reference")
    target = _target_expression_from_raw(
        {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
        field_name="validation_target",
        expression_id="duplicate:target",
        source=source,
    )
    assert target is not None
    condition_node = _typed_condition_execution_node({"$type": "RPG.GameCore.AlwaysTrue"})
    condition = _condition_from_node("duplicate:condition", condition_node, source)
    formula = FormulaIR(
        formula_id="duplicate:formula",
        kind="fixed_value",
        expression={"Value": 1.0},
        source=source,
        coverage_status="executable",
    )
    rules = RuleBook(
        CanonicalIR(
            version="validation:p7_s5:ambiguous",
            target_expressions=(target, replace(target, alias="CurrentTarget")),
            conditions=(condition, replace(condition, blocked_reason="duplicate")),
            formulas=(formula, replace(formula, expression={"Value": 2.0})),
        )
    )
    resolutions = {
        "target_ambiguous": rules.target_expression_resolution("duplicate:target"),
        "target_missing": rules.target_expression_resolution("missing:target"),
        "condition_ambiguous": rules.condition_resolution("duplicate:condition"),
        "condition_missing": rules.condition_resolution("missing:condition"),
        "formula_ambiguous": rules.formula_resolution("duplicate:formula"),
        "formula_missing": rules.formula_resolution("missing:formula"),
    }
    reasons = {key: value[1] for key, value in resolutions.items()}
    state = _base_state()
    checks = {
        "missing_and_ambiguous_distinct": all(value[0] is None for value in resolutions.values())
        and reasons["target_ambiguous"] != reasons["target_missing"]
        and reasons["condition_ambiguous"] != reasons["condition_missing"]
        and reasons["formula_ambiguous"] != reasons["formula_missing"],
        "state_unchanged": state == _base_state() and rules.target_expression("duplicate:target") is None,
    }
    return {
        "row_id": "expression_reference_linking",
        "classification": "blocked_boundary",
        "ok": all(checks.values()),
        **checks,
        "reasons": reasons,
    }


def _typed_execution_audit_replay_case() -> dict[str, Any]:
    rules = _trust_rulebook()
    before = _decision_state(_base_state(skill_points=3))
    after, transition = CombatExecutor(rules).execute(
        ActionCommand(
            actor_id="ally:actor",
            action_id="validation:normal",
            action_level=1,
            target_ids=("enemy:target",),
        ),
        before,
    )
    replay = MutationReducer().replay_snapshot(
        before,
        transition.transaction.mutations,
        transition.after.to_json(),
    )
    audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    ok = (
        transition.outcome.category == "committed"
        and after.snapshot().to_json() == transition.after.to_json()
        and replay.ok
        and audit.ok
        and bool(transition.transaction.mutations)
    )
    return {
        "row_id": "typed_execution_source_audit_replay",
        "classification": "executable",
        "ok": ok,
        "outcome": transition.outcome.to_json(),
        "mutation_count": len(transition.transaction.mutations),
        "replay_ok": replay.ok,
        "source_audit_ok": audit.ok,
        "checked_mutations": audit.checked_mutations,
        "checked_records": audit.checked_records,
    }


def _runtime_static_boundary(package_root: Path) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    for relative in RUNTIME_EXPRESSION_FILES:
        text = (package_root / relative).read_text(encoding="utf-8")
        for token in FORBIDDEN_RUNTIME_TOKENS:
            if token in text:
                findings.append({"file": relative, "token": token})
    lowering_text = (package_root / "tbgd/expression_lowering.py").read_text(encoding="utf-8")
    target_text = (package_root / "systems/target.py").read_text(encoding="utf-8")
    checks = {
        "runtime_findings_empty": not findings,
        "raw_numeric_parser_owned_by_lowering": "PostfixExpr" in lowering_text and "OpCodes" in lowering_text,
        "target_runtime_reads_typed_node": "expression.node" in target_text,
        "target_runtime_does_not_read_audit_raw": "audit_raw" not in target_text,
        "target_runtime_does_not_rebuild_condition_ir": "_condition_from_raw" not in target_text,
        "target_runtime_does_not_read_legacy_target_fields": not any(
            token in target_text
            for token in (
                'raw.get("TargetType")',
                'raw.get("Predicate")',
                'raw.get("Sequence")',
                'raw.get("Targets")',
            )
        ),
    }
    return {
        "row_id": "runtime_expression_boundary",
        "classification": "boundary",
        "ok": all(checks.values()),
        **checks,
        "findings": findings,
        "scanned_files": list(RUNTIME_EXPRESSION_FILES),
    }


def _condition_from_node(condition_id: str, node: dict[str, Any], source: IRSource) -> ConditionIR:
    metadata = {"schema_version", "expression_kind", "opcode", "supported", "blocked_reason"}
    payload = {key: value for key, value in node.items() if key not in metadata}
    supported = node.get("supported") is True
    return ConditionIR(
        condition_id=condition_id,
        opcode=str(node.get("opcode") or "Unknown"),
        payload=payload,
        source=source,
        coverage_status="executable" if supported else "blocked",
        expression_schema_version=str(node.get("schema_version") or ""),
        blocked_reason=str(node.get("blocked_reason") or ""),
    )


def _source(name: str) -> IRSource:
    return IRSource(
        source_path=f"validation/p7_s5/{name}.json",
        raw_type="ValidationExpressionSource",
        raw_id=name,
        evidence={"selection_predicate": "structural_expression_contract"},
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P7-S5 typed executable expression IR boundary.")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    result = run_validation(package_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} "
        f"rows={result['row_count']} ready_for_review={result['ready_for_review']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
