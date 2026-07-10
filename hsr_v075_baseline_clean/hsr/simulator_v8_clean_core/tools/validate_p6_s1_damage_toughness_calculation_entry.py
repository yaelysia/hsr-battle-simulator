from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from .. import BASELINE_VERSION
from ..core.action_plan import build_action_execution_plan
from ..core.executor import CombatExecutor, _damage_value_resolution, _toughness_value_resolution
from ..core.model import ActionCommand, BattleState, JSONValue, UnitState
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import CanonicalIR, ToughnessEmissionIR
from ..rules.rulebook import RuleBook
from ..systems.damage import DamagePacket, DamageSystem
from ..systems.toughness import ToughnessPacket, ToughnessSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json


VALIDATION_VERSION = "p6_s1_damage_toughness_calculation_entry"
MATRIX_SCHEMA_VERSION = "p6_s1_damage_toughness_calculation_entry_matrix_v1"

CLASSIFICATION_STATES = {
    "executable",
    "boundary_guard",
    "implementation_missing",
    "validation_gap",
}
REQUIRED_ROWS = {
    "damage_explicit_calculation_entry",
    "toughness_explicit_calculation_entry",
    "damage_missing_entry_blocked_no_mutation",
    "toughness_missing_entry_blocked_no_mutation",
    "executor_trace_mining_static_guard",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    case = _select_case(ir, rules)
    matrix = build_matrix(package_root, case)
    matrix_checks = validate_matrix(matrix)
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": matrix_checks["ok"],
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "structural_executable_damage_with_fixed_toughness_entry",
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "full_ir_written": False,
                "full_rulebook_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
            },
        },
        "checks": {"matrix": matrix_checks},
        "summary": matrix["summary"],
        "calculation_entry_matrix": matrix["calculation_entry_matrix"],
        "runtime_sample": matrix["runtime_sample"],
        "resource_budget": matrix["resource_budget"],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p6_s1_damage_toughness_calculation_entry.json", result)
    write_json(output_dir / "p6_s1_damage_toughness_calculation_entry_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P6-S1 explicit damage/toughness calculation entries.")
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
        f"classifications={result['summary']['classification_counts']}"
    )
    return 0 if result["ok"] else 1


def build_matrix(package_root: Path, case: dict[str, Any]) -> dict[str, Any]:
    rows = [
        _damage_positive_row(case),
        _toughness_positive_row(case),
        _damage_negative_row(case),
        _toughness_negative_row(case),
        _static_guard_row(package_root),
    ]
    matrix = {str(row["row_id"]): row for row in rows}
    classification_counts = Counter(str(row.get("classification") or "unclassified") for row in rows)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "calculation_entry_matrix": matrix,
        "summary": {
            "row_count": len(matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "runtime_action_sample_count": 1,
            "damage_value_resolution_count": len(case["damage_value_resolutions"]),
            "toughness_value_resolution_count": len(case["toughness_value_resolutions"]),
            "negative_blocked_resolution_count": 2,
        },
        "runtime_sample": case["runtime_sample"],
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "combat_executor_runtime_sample_count": 1,
            "negative_system_packet_count": 2,
            "full_ir_written": False,
            "full_rulebook_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_files": [
                "validation_summary_p6_s1_damage_toughness_calculation_entry.json",
                "p6_s1_damage_toughness_calculation_entry_matrix.json",
            ],
        },
    }


def validate_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("calculation_entry_matrix") or {})
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
        "damage_positive_uses_plan_entry": _row_check(rows, "damage_explicit_calculation_entry", "plan_has_value_request")
        and _row_check(rows, "damage_explicit_calculation_entry", "resolution_ok"),
        "toughness_positive_uses_plan_entry": _row_check(rows, "toughness_explicit_calculation_entry", "plan_has_value_request")
        and _row_check(rows, "toughness_explicit_calculation_entry", "resolution_ok"),
        "negative_no_mutations": _row_check(rows, "damage_missing_entry_blocked_no_mutation", "no_mutations")
        and _row_check(rows, "toughness_missing_entry_blocked_no_mutation", "no_mutations"),
        "static_guard_ok": _row_check(rows, "executor_trace_mining_static_guard", "no_trace_binding_helper")
        and _row_check(rows, "executor_trace_mining_static_guard", "no_show_stance_fallback"),
        "plan_no_raw_param_path_parsing": _row_check(rows, "executor_trace_mining_static_guard", "action_plan_no_param_list_marker")
        and _row_check(rows, "executor_trace_mining_static_guard", "action_plan_no_raw_path_param_index"),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_rows": missing,
        "invalid_classifications": invalid_classifications,
    }


def _select_case(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    for toughness in sorted(ir.toughness_emissions, key=lambda item: (item.action_id, item.level, item.toughness_emission_id)):
        if toughness.coverage_status != "executable":
            continue
        if not _is_fixed_toughness_amount(toughness):
            continue
        if not rules.damage_emissions_for_action(toughness.action_id, toughness.level):
            continue
        definition = rules.action_definition(toughness.action_id, toughness.level)
        event = rules.action_event(toughness.action_id, toughness.level)
        if definition is None or event is None or definition.coverage_status != "executable":
            continue
        state = _sample_state()
        command = ActionCommand(
            actor_id="ally:p6_s1_actor",
            action_id=toughness.action_id,
            action_level=toughness.level,
            target_ids=("enemy:p6_s1_target",),
            source="validation",
            metadata={
                "p6_s1_selected_by_structural_predicate": True,
                "selection_predicate": "executable_fixed_toughness_emission_with_damage_emission",
            },
        )
        after, transition = CombatExecutor(rules).execute(command, state)
        replay = MutationReducer().replay_snapshot(state, transition.transaction.mutations, transition.after.to_json())
        audit = RuntimeSourceAuditor(rules).validate_transition(transition)
        damage_value_resolutions = _value_resolutions_from_mutations(transition.transaction.mutations, "damage_system")
        toughness_value_resolutions = _value_resolutions_from_mutations(transition.transaction.mutations, "toughness_system")
        if not (damage_value_resolutions and toughness_value_resolutions and replay.ok and audit.ok):
            continue
        plan = build_action_execution_plan(
            definition,
            event,
            rules.hit_profiles_for_action(toughness.action_id, toughness.level),
            rules.damage_emissions_for_action(toughness.action_id, toughness.level),
            rules.toughness_emissions_for_action(toughness.action_id, toughness.level),
            requested_target_ids=("enemy:p6_s1_target",),
            resolved_target_groups={"primary": ("enemy:p6_s1_target",), "selected": ("enemy:p6_s1_target",)},
            source_trace=definition.source.to_json(),
        )
        damage_plan = _first_executable_value_plan(plan.damage_plan)
        toughness_plan = _first_executable_value_plan(plan.toughness_plan)
        if damage_plan is None or toughness_plan is None:
            continue
        return {
            "rules": rules,
            "state": state,
            "after": after,
            "transition": transition,
            "definition": definition,
            "command": command,
            "plan": plan,
            "damage_plan": damage_plan,
            "toughness_plan": toughness_plan,
            "replay": replay,
            "audit": audit,
            "damage_value_resolutions": damage_value_resolutions,
            "toughness_value_resolutions": toughness_value_resolutions,
            "runtime_sample": {
                "action_id": toughness.action_id,
                "action_level": toughness.level,
                "selected_toughness_emission_id": toughness.toughness_emission_id,
                "selection_predicate": "executable_fixed_toughness_emission_with_damage_emission",
                "damage_value_resolution_count": len(damage_value_resolutions),
                "toughness_value_resolution_count": len(toughness_value_resolutions),
                "damage_mutation_count": transition.coverage.get("damage_mutation_count", 0),
                "toughness_mutation_count": transition.coverage.get("toughness_mutation_count", 0),
                "replay_ok": replay.ok,
                "source_audit_ok": audit.ok,
            },
        }
    raise RuntimeError("no P6-S1 explicit damage+toughness calculation-entry sample selected")


def _damage_positive_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    plan = case["damage_plan"]
    resolution = case["damage_value_resolutions"][0]
    request = plan.value_request if isinstance(plan.value_request, dict) else {}
    checks = _checks(
        {
            "plan_has_value_request": bool(request) and request.get("binding_kind") not in {"", "blocked"},
            "runtime_resolution_has_request": isinstance(resolution.get("request"), dict),
            "resolution_ok": resolution.get("ok") is True,
            "resolution_uses_supported_kind": resolution.get("binding_kind") in {"skill_formula_param", "fixed_numeric_expression"},
            "source_audit_ok": case["audit"].ok,
            "replay_ok": case["replay"].ok,
        }
    )
    return _row(
        "damage_explicit_calculation_entry",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        details={
            "plan_value_request": _request_summary(request),
            "sample_resolution": _value_resolution_summary(resolution),
        },
    )


def _toughness_positive_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    plan = case["toughness_plan"]
    resolution = case["toughness_value_resolutions"][0]
    request = plan.value_request if isinstance(plan.value_request, dict) else {}
    checks = _checks(
        {
            "plan_has_value_request": bool(request) and request.get("binding_kind") not in {"", "blocked"},
            "runtime_resolution_has_request": isinstance(resolution.get("request"), dict),
            "resolution_ok": resolution.get("ok") is True,
            "resolution_uses_supported_kind": resolution.get("binding_kind") in {"dynamic_hash", "fixed_numeric_expression"},
            "no_show_stance_fallback": _nested_value_missing(resolution, "fallback_basis"),
            "source_audit_ok": case["audit"].ok,
            "replay_ok": case["replay"].ok,
        }
    )
    return _row(
        "toughness_explicit_calculation_entry",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        details={
            "plan_value_request": _request_summary(request),
            "plan_binding_source_count": len(plan.value_binding_sources),
            "sample_resolution": _value_resolution_summary(resolution),
        },
    )


def _damage_negative_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    rules: RuleBook = case["rules"]
    state: BattleState = case["state"]
    command: ActionCommand = case["command"]
    definition = case["definition"]
    plan = replace(
        case["damage_plan"],
        value_request={
            "binding_kind": "blocked",
            "blocked_reason": "validation_missing_damage_value_request",
            "source_trace": {"validation": "p6_s1_missing_damage_value_request"},
        },
    )
    resolution = _damage_value_resolution(rules.value_resolver if hasattr(rules, "value_resolver") else _ValueResolver(rules), command, definition, plan)
    packet = DamagePacket(
        attacker_id=command.actor_id,
        target_id=plan.target_id,
        attack_type=definition.attack_type,
        damage_formula_family=plan.damage_formula_family,
        action_definition=definition,
        damage_emission_id=plan.damage_emission_id,
        hit_profile_id=plan.hit_profile_id,
        scaling_ratio=None,
        source_trace=plan.hit_source_trace,
        metadata={"value_resolution": resolution.to_json(), "value_resolver_admitted": False},
    )
    result = DamageSystem().apply_packet(state, packet)
    checks = _checks(
        {
            "resolution_blocked": not resolution.ok,
            "blocked_reason_present": bool(resolution.blocked_reason),
            "system_result_not_ok": not result.ok,
            "no_mutations": not result.mutations,
        }
    )
    return _row(
        "damage_missing_entry_blocked_no_mutation",
        classification="boundary_guard" if checks["ok"] else "implementation_missing",
        checks=checks,
        details={
            "blocked_resolution": _value_resolution_summary(resolution.to_json()),
            "system_errors": list(result.errors),
        },
    )


def _toughness_negative_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    rules: RuleBook = case["rules"]
    state: BattleState = case["state"]
    command: ActionCommand = case["command"]
    definition = case["definition"]
    plan = replace(
        case["toughness_plan"],
        value_request={
            "binding_kind": "blocked",
            "blocked_reason": "validation_missing_toughness_value_request",
            "source_trace": {"validation": "p6_s1_missing_toughness_value_request"},
        },
        value_binding_sources=(),
    )
    resolution = _toughness_value_resolution(_ValueResolver(rules), command, definition, plan)
    packet = ToughnessPacket(
        attacker_id=command.actor_id,
        target_id=plan.target_id,
        toughness_emission_id=plan.toughness_emission_id,
        source_task_id=plan.source_task_id,
        hit_profile_id=plan.hit_profile_id,
        element_type=plan.element_type,
        amount=None,
        amount_expr=plan.toughness_amount_expr,
        target_group=plan.target_group,
        coverage_status="blocked",
        source_trace=plan.source_trace,
        metadata={"value_resolution": resolution.to_json(), "value_resolver_admitted": False},
    )
    result = ToughnessSystem().apply_packet(state, packet)
    checks = _checks(
        {
            "resolution_blocked": not resolution.ok,
            "blocked_reason_present": bool(resolution.blocked_reason),
            "system_result_not_ok": not result.ok,
            "no_mutations": not result.mutations,
        }
    )
    return _row(
        "toughness_missing_entry_blocked_no_mutation",
        classification="boundary_guard" if checks["ok"] else "implementation_missing",
        checks=checks,
        details={
            "blocked_resolution": _value_resolution_summary(resolution.to_json()),
            "system_errors": list(result.errors),
        },
    )


def _static_guard_row(package_root: Path) -> dict[str, JSONValue]:
    executor_source = (package_root / "core" / "executor.py").read_text(encoding="utf-8")
    action_plan_source = (package_root / "core" / "action_plan.py").read_text(encoding="utf-8")
    checks = _checks(
        {
            "no_trace_binding_helper": "_skill_formula_binding_from_trace" not in executor_source,
            "no_trace_numeric_source_helper": "_numeric_binding_sources_from_trace" not in executor_source,
            "no_show_stance_fallback": "show_stance_list" not in executor_source and "fallback_basis" not in executor_source,
            "plan_request_consumer_present": "_resolve_plan_value_request" in executor_source,
            "action_plan_no_param_list_marker": "ParamList[" not in action_plan_source,
            "action_plan_no_raw_path_param_index": "raw_path" not in action_plan_source,
            "action_plan_structured_param_index_required": "_structured_param_index" in action_plan_source,
        }
    )
    return _row(
        "executor_trace_mining_static_guard",
        classification="boundary_guard" if checks["ok"] else "implementation_missing",
        checks=checks,
        details={
            "checked_files": ["core/executor.py", "core/action_plan.py"],
            "forbidden_tokens": [
                "_skill_formula_binding_from_trace",
                "_numeric_binding_sources_from_trace",
                "show_stance_list",
                "fallback_basis",
                "ParamList[ in core/action_plan.py",
                "raw_path in core/action_plan.py",
            ],
        },
    )


def _sample_state() -> BattleState:
    return BattleState(
        units={
            "ally:p6_s1_actor": UnitState(
                unit_id="ally:p6_s1_actor",
                side="ally",
                template_id="validation:p6_s1_actor",
                level=80,
                max_hp=3000.0,
                hp=3000.0,
                attack=1000.0,
                defense=500.0,
                speed=100.0,
                energy=100.0,
                max_energy=100.0,
            ),
            "enemy:p6_s1_target": UnitState(
                unit_id="enemy:p6_s1_target",
                side="enemy",
                template_id="validation:p6_s1_target",
                level=80,
                max_hp=100000.0,
                hp=100000.0,
                attack=100.0,
                defense=100.0,
                speed=100.0,
                toughness=120.0,
                max_toughness=120.0,
                flags={"weaknesses": ["Physical", "Fire", "Ice", "Thunder", "Wind", "Quantum", "Imaginary"]},
            ),
        },
        skill_points=5,
        max_skill_points=5,
        global_flags={"phase": "scenario", "current_window": "idle", "turn_owner_id": "ally:p6_s1_actor"},
    )


def _is_fixed_toughness_amount(emission: ToughnessEmissionIR) -> bool:
    expression = emission.toughness_amount_expr
    if not isinstance(expression, dict) or expression.get("kind") != "fixed":
        return False
    value = expression.get("value")
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _value_resolutions_from_mutations(mutations: tuple[Any, ...], source: str) -> list[dict[str, JSONValue]]:
    resolutions = []
    for mutation in mutations:
        if mutation.source != source:
            continue
        resolution = mutation.metadata.get("value_resolution") if isinstance(mutation.metadata, dict) else None
        if isinstance(resolution, dict):
            resolutions.append(resolution)
    return resolutions


def _first_executable_value_plan(plans: Iterable[Any]) -> Any | None:
    for plan in plans:
        request = getattr(plan, "value_request", None)
        if not isinstance(request, dict):
            continue
        if request.get("binding_kind") in {"", None, "blocked"}:
            continue
        return plan
    return None


def _row(
    row_id: str,
    *,
    classification: str,
    checks: dict[str, JSONValue],
    details: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    return {
        "row_id": row_id,
        "classification": classification,
        "checks": {"ok": bool(checks.get("ok")), "checks": checks},
        "details": details or {},
    }


def _checks(checks: dict[str, JSONValue]) -> dict[str, JSONValue]:
    return {"ok": all(bool(value) for value in checks.values()), **checks}


def _row_check(rows: dict[str, Any], row_id: str, check_name: str) -> bool:
    return bool(rows.get(row_id, {}).get("checks", {}).get("checks", {}).get(check_name))


def _request_summary(request: dict[str, Any]) -> dict[str, JSONValue]:
    return {
        "binding_kind": request.get("binding_kind", ""),
        "binding_id": request.get("binding_id", ""),
        "param_index": request.get("param_index"),
        "formula_role": request.get("formula_role", ""),
        "field_name": request.get("field_name", ""),
        "required_context_keys": list(request.get("required_context_keys") or []),
        "source_trace": _source_trace_summary(request.get("source_trace") if isinstance(request.get("source_trace"), dict) else {}),
    }


def _value_resolution_summary(resolution: dict[str, JSONValue]) -> dict[str, JSONValue]:
    request = resolution.get("request") if isinstance(resolution.get("request"), dict) else {}
    return {
        "ok": bool(resolution.get("ok")),
        "value": resolution.get("value"),
        "binding_kind": resolution.get("binding_kind", ""),
        "blocked_reason": resolution.get("blocked_reason", ""),
        "request": _request_summary(request),
        "context_keys": list(resolution.get("context_keys") or []),
        "source_trace": _source_trace_summary(
            resolution.get("source_trace") if isinstance(resolution.get("source_trace"), dict) else {}
        ),
    }


def _source_trace_summary(trace: dict[str, Any]) -> dict[str, JSONValue]:
    evidence = trace.get("evidence") if isinstance(trace.get("evidence"), dict) else {}
    return {
        "source_path": trace.get("source_path", ""),
        "raw_type": trace.get("raw_type", ""),
        "raw_id": trace.get("raw_id", ""),
        "evidence_keys": sorted(str(key) for key in evidence.keys())[:20],
        "value_request_source": trace.get("value_request_source", ""),
        "source_kind": trace.get("source_kind", ""),
    }


def _nested_value_missing(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        if key in value:
            return False
        return all(_nested_value_missing(item, key) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(_nested_value_missing(item, key) for item in value)
    return True


def _ValueResolver(rules: RuleBook) -> Any:
    from ..rules.value_binding import ValueResolver

    return ValueResolver(rules)


if __name__ == "__main__":
    raise SystemExit(main())
