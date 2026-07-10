from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import JSONValue
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "p6_s4_s5_boundary_static"
MATRIX_SCHEMA_VERSION = "p6_s4_s5_boundary_static_matrix_v1"

CLASSIFICATION_STATES = {"boundary_guard", "audit_only", "implementation_missing"}
REQUIRED_ROWS = {
    "existing_runtime_static_checks",
    "dynamic_value_rulebook_accessor_boundary",
    "damage_toughness_trace_mining_boundary",
    "unit_spawn_apply_birth_plan_boundary",
    "action_availability_query_only_boundary",
    "ui_scenario_no_formal_rule_write_boundary",
}


def run_validation(package_root: Path, output_dir: Path) -> dict[str, Any]:
    matrix = build_matrix(package_root)
    matrix_checks = validate_matrix(matrix)
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": matrix_checks["ok"],
        "build": {
            "selection_policy": {
                "mode": "p6_s4_s5_static_file_scope_boundary_checks",
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "full_ir_written": False,
                "full_rulebook_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
            },
        },
        "checks": {"matrix": matrix_checks},
        "summary": matrix["summary"],
        "boundary_static_matrix": matrix["boundary_static_matrix"],
        "resource_budget": matrix["resource_budget"],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p6_s4_s5_boundary_static.json", result)
    write_json(output_dir / "p6_s4_s5_boundary_static_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P6-S4/S5 content/core/RuleBook boundary static guards.")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    result = run_validation(package_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} "
        f"rows={result['summary']['row_count']} "
        f"classifications={result['summary']['classification_counts']}"
    )
    return 0 if result["ok"] else 1


def build_matrix(package_root: Path) -> dict[str, Any]:
    rows = [
        _existing_static_row(package_root),
        _dynamic_value_accessor_row(package_root),
        _damage_toughness_trace_row(package_root),
        _unit_spawn_apply_row(package_root),
        _action_availability_row(package_root),
        _ui_scenario_row(package_root),
    ]
    matrix = {str(row["row_id"]): row for row in rows}
    classification_counts = Counter(str(row.get("classification") or "unclassified") for row in rows)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "boundary_static_matrix": matrix,
        "summary": {
            "row_count": len(matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "static_file_count": len(tuple(package_root.rglob("*.py"))),
        },
        "resource_budget": {
            "lowering_build_count": 0,
            "rulebook_build_count": 0,
            "runtime_sample_count": 0,
            "full_ir_written": False,
            "full_rulebook_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_files": [
                "validation_summary_p6_s4_s5_boundary_static.json",
                "p6_s4_s5_boundary_static_matrix.json",
            ],
        },
    }


def validate_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("boundary_static_matrix") or {})
    missing = sorted(REQUIRED_ROWS.difference(rows))
    invalid_classifications = sorted(
        row_id
        for row_id, row in rows.items()
        if str(row.get("classification") or "") not in CLASSIFICATION_STATES
    )
    checks = {
        "required_rows_present": not missing,
        "valid_classifications": not invalid_classifications,
        "row_checks_ok": all(dict(row.get("checks") or {}).get("ok") is True for row in rows.values()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_rows": missing,
        "invalid_classifications": invalid_classifications,
    }


def _existing_static_row(package_root: Path) -> dict[str, JSONValue]:
    result = run_static_checks(package_root)
    checks = _checks({"run_static_checks_ok": result.ok, "violation_count_zero": len(result.violations) == 0})
    return _row(
        "existing_runtime_static_checks",
        "boundary_guard",
        checks,
        {"violation_count": len(result.violations), "violations": list(result.violations)[:20]},
    )


def _dynamic_value_accessor_row(package_root: Path) -> dict[str, JSONValue]:
    systems_source = _read(package_root / "systems" / "dynamic_values.py")
    rulebook_source = _read(package_root / "rules" / "rulebook.py")
    checks = _checks(
        {
            "systems_does_not_read_card_source_evidence": "card.source.evidence" not in systems_source,
            "systems_uses_rulebook_accessor": "character_dynamic_value_bindings_for_card" in systems_source,
            "rulebook_accessor_exists": "def character_dynamic_value_bindings_for_card" in rulebook_source,
            "rulebook_accessor_returns_copy": "_json_object_copy(bindings)" in rulebook_source,
        }
    )
    return _row(
        "dynamic_value_rulebook_accessor_boundary",
        "boundary_guard",
        checks,
        {
            "runtime_file": "systems/dynamic_values.py",
            "accessor_file": "rules/rulebook.py",
            "policy": "Systems consume a narrow RuleBook dynamic-binding view instead of mining card.source.evidence.",
        },
    )


def _damage_toughness_trace_row(package_root: Path) -> dict[str, JSONValue]:
    executor_source = _read(package_root / "core" / "executor.py")
    checks = _checks(
        {
            "no_skill_formula_trace_helper": "_skill_formula_binding_from_trace" not in executor_source,
            "no_numeric_binding_trace_helper": "_numeric_binding_sources_from_trace" not in executor_source,
            "no_show_stance_fallback": "show_stance_list" not in executor_source and "fallback_basis" not in executor_source,
            "plan_value_request_consumer_present": "_resolve_plan_value_request" in executor_source,
        }
    )
    return _row(
        "damage_toughness_trace_mining_boundary",
        "boundary_guard",
        checks,
        {"checked_file": "core/executor.py"},
    )


def _unit_spawn_apply_row(package_root: Path) -> dict[str, JSONValue]:
    summon_source = _read(package_root / "systems" / "summon.py")
    wave_source = _read(package_root / "systems" / "wave.py")
    apply_spawn = _function_source(summon_source, "    def apply_spawn(")
    apply_servant = _function_source(summon_source, "    def apply_spawn_servant(")
    apply_wave = _function_source(wave_source, "    def apply_transition(")
    checks = _checks(
        {
            "summon_apply_consumes_birth_plan": "spawn_plans_from_metadata(plan.metadata)" in apply_spawn,
            "summon_apply_no_unit_from_entry_call": "self._unit_from_entry(" not in apply_spawn,
            "servant_apply_consumes_birth_plan": "spawn_plans_from_metadata(plan.metadata)" in apply_servant,
            "servant_apply_no_unit_from_definition_call": "self._unit_from_servant_definition(" not in apply_servant,
            "wave_apply_consumes_birth_plan": "spawn_plans_from_metadata" in apply_wave,
            "wave_apply_no_unit_from_wave_entry_call": "_unit_from_wave_entry(" not in apply_wave,
        }
    )
    return _row(
        "unit_spawn_apply_birth_plan_boundary",
        "boundary_guard",
        checks,
        {"checked_files": ["systems/summon.py", "systems/wave.py", "systems/unit_spawn.py"]},
    )


def _action_availability_row(package_root: Path) -> dict[str, JSONValue]:
    source = _read(package_root / "systems" / "action_availability.py")
    checks = _checks(
        {
            "no_mutation_construction": "Mutation(" not in source,
            "no_damage_or_toughness_apply": ".apply_packet(" not in source,
            "source_context_terms_are_present": "source_trace" in source and "servant_definition" in source,
        }
    )
    return _row(
        "action_availability_query_only_boundary",
        "audit_only",
        checks,
        {
            "checked_file": "systems/action_availability.py",
            "policy": "Action availability may attach source/query context but must not execute content-card mechanisms.",
        },
    )


def _ui_scenario_row(package_root: Path) -> dict[str, JSONValue]:
    hsr_root = package_root.parent
    ui_cases = tuple((hsr_root / "simulator_v8_ui" / "cases").glob("*.scenario.json"))
    scenario_text = "\n".join(path.read_text(encoding="utf-8") for path in ui_cases)
    forbidden_formal_inputs = (
        "damage_formula_family",
        "scaling_ratio",
        "toughness_amount_expr",
        "value_resolution",
        "show_stance_list",
    )
    checks = _checks(
        {
            "scenario_case_files_checked": bool(ui_cases),
            "scenario_cases_do_not_write_derived_rule_results": not any(token in scenario_text for token in forbidden_formal_inputs),
            "ui_static_display_only_for_damage_formula_family": "damage_formula_family" in _read(hsr_root / "simulator_v8_ui" / "report.py")
            or "damage_formula_family" in _read(hsr_root / "simulator_v8_ui" / "static" / "app.js"),
        }
    )
    return _row(
        "ui_scenario_no_formal_rule_write_boundary",
        "boundary_guard",
        checks,
        {
            "checked_scenario_case_count": len(ui_cases),
            "forbidden_formal_input_tokens": list(forbidden_formal_inputs),
            "policy": "UI may display core/API output, but checked saved scenario inputs must not persist derived combat-rule results.",
        },
    )


def _row(row_id: str, success_classification: str, checks: dict[str, JSONValue], details: dict[str, JSONValue]) -> dict[str, JSONValue]:
    return {
        "row_id": row_id,
        "classification": success_classification if checks["ok"] else "implementation_missing",
        "checks": {"ok": bool(checks["ok"]), "checks": checks},
        "details": details,
    }


def _checks(checks: dict[str, JSONValue]) -> dict[str, JSONValue]:
    return {"ok": all(bool(value) for value in checks.values()), **checks}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _function_source(source: str, marker: str) -> str:
    start = source.find(marker)
    if start < 0:
        return ""
    next_def = source.find("\n    def ", start + len(marker))
    if next_def < 0:
        return source[start:]
    return source[start:next_def]


if __name__ == "__main__":
    raise SystemExit(main())
