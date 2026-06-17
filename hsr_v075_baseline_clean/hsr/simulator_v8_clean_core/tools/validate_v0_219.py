from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.fidelity import build_fidelity_matrix
from ..core.model import ActionCommand, BattleState
from ..core.reducer import MutationReducer
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..rules.ir import ActionDefinitionIR, CanonicalIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import LoweringLimits, TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_213 import (
    _damage_semantics_regression_checks,
    _formula_test_state,
    _status_ledger_transition,
    _status_modifier_ledger_regression_checks,
)
from .validate_v0_218 import (
    TARGET_MODES,
    _blocked_mode_checks,
    _canonical_ir_summary,
    _case_json,
    _damage_case_json,
    _damage_records_have_metadata_value,
    _definition_selection_checks,
    _execute_mode_case,
    _execution_plan_checks,
    _fixed_damage_family_cases,
    _fixed_damage_family_checks,
    _multi_enemy_state,
    _multi_target_damage_checks,
    _records_of_type,
    _select_definition,
    _target_mode_checks,
    _transition_quality_checks,
    _with_crit_mode,
)


VALIDATION_VERSION = "v0_219"


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    scenario_path: Path,
    max_ability_files: int | None = None,
    write_full_ir: bool = False,
) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root, LoweringLimits(max_ability_files=max_ability_files)).build()
    coverage = build_coverage_matrix(discovery, ir)
    fidelity = build_fidelity_matrix(discovery, ir)
    rules = RuleBook(ir)

    if write_full_ir:
        write_json(output_dir / "canonical_ir_v0_219.json", ir.to_json())
    write_json(output_dir / "canonical_ir_summary_v0_219.json", _canonical_ir_summary(ir))
    write_json(output_dir / "coverage_matrix_v0_219.json", coverage.to_json())
    write_json(output_dir / "fidelity_matrix_v0_219.json", fidelity.to_json())

    scenario = ScenarioLoader().load_path(scenario_path)
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    base_state = _multi_enemy_state(build_result.state)
    base_command = replace(
        build_result.commands[0],
        target_ids=("enemy:target",),
        metadata={**build_result.commands[0].metadata, "crit_mode": "noncrit", "reset_actor_av": False},
    )

    definitions = {mode: _select_definition(ir, mode) for mode in TARGET_MODES}
    execution_cases = {
        mode: _execute_mode_case(rules, base_state, base_command, definition, mode)
        for mode, definition in definitions.items()
    }
    negative_cases = _preflight_negative_cases(ir, rules, base_state, base_command, definitions)

    formula_state = _formula_test_state(build_result.state)
    status_ledger_transition = _status_ledger_transition(
        ir,
        rules,
        formula_state,
        _with_crit_mode(build_result.commands[0], "crit"),
    )
    fixed_damage_cases = _fixed_damage_family_cases(formula_state, build_result.commands[0])

    snapshot_result = SnapshotCompletenessValidator().validate(base_state.snapshot())
    static_result = run_static_checks(package_root)
    checks = {
        "definition_selection": _definition_selection_checks(definitions),
        "action_execution_plan": _execution_plan_checks(execution_cases, _plan_cases(rules, definitions)),
        "target_modes": _target_mode_checks(execution_cases),
        "multi_target_damage": _multi_target_damage_checks(execution_cases),
        "blocked_modes": _blocked_mode_checks(execution_cases, _plan_cases(rules, definitions)),
        "preflight_commit_gate": _preflight_commit_gate_checks(negative_cases),
        "multi_target_context": _multi_target_context_checks(execution_cases),
        "transition_quality": _transition_quality_checks({**execution_cases, **negative_cases}),
        "status_modifier_ledger_regression": _status_modifier_ledger_regression_checks(status_ledger_transition),
        "damage_semantics_regression": _damage_semantics_regression_checks(status_ledger_transition),
        "fixed_damage_families": _fixed_damage_family_checks(fixed_damage_cases),
        "runtime_import_boundary": _runtime_import_boundary_check(static_result.to_json()),
    }

    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(
            (
                identity_result.ok,
                static_result.ok,
                snapshot_result.ok,
                *(item["ok"] for item in checks.values()),
            )
        ),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "scenario_path": scenario_path.as_posix(),
        "summary": {
            "discovery_files": len(discovery.files),
            "ir_action_definitions": len(ir.action_definitions),
            "ir_action_events": len(ir.action_events),
            "ir_hit_profiles": len(ir.hit_profiles),
            "ir_effects": len(ir.effects),
            "sampled": ir.metadata.get("sampled", {}),
            },
        },
        "scenario": {
            "scenario_id": scenario.scenario_id,
            "identity": identity_result.to_json(),
            "base_command": {
                "actor_id": base_command.actor_id,
                "action_id": base_command.action_id,
                "action_level": base_command.action_level,
                "target_ids": list(base_command.target_ids),
            },
        },
        "checks": checks,
        "snapshot_completeness": snapshot_result.to_json(),
        "static_checks": static_result.to_json(),
        "fidelity": fidelity.to_json()["summary"],
    }
    write_json(output_dir / "validation_summary_v0_219.json", result)
    for mode, case in execution_cases.items():
        transition = case.get("transition")
        if transition is not None:
            write_json(output_dir / f"sample_{mode}_transition_v0_219.json", transition.to_json())
    for name, case in negative_cases.items():
        write_json(output_dir / f"sample_{name}_preflight_v0_219.json", _case_json(case))
        transition = case.get("transition")
        if transition is not None:
            write_json(output_dir / f"sample_{name}_transition_v0_219.json", transition.to_json())
    if status_ledger_transition is not None:
        write_json(output_dir / "sample_status_ledger_transition_v0_219.json", status_ledger_transition.to_json())
    write_json(output_dir / "sample_fixed_damage_families_v0_219.json", _damage_case_json(fixed_damage_cases))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 action preflight/commit gate and multi-target context guards.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_219"))
    parser.add_argument("--scenario", type=Path, default=None)
    parser.add_argument("--max-ability-files", type=int, default=None)
    parser.add_argument("--write-full-ir", action="store_true")
    args = parser.parse_args(argv)

    package_root = Path(__file__).resolve().parents[1]
    tbgd_root = args.tbgd_root.resolve() if args.tbgd_root else find_tbgd_root(package_root)
    scenario_path = args.scenario or package_root / "scenarios/examples/identity_smoke_v0_204.json"
    result = run_validation(
        package_root,
        tbgd_root,
        args.output_dir,
        scenario_path,
        max_ability_files=args.max_ability_files,
        write_full_ir=args.write_full_ir,
    )
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _plan_cases(rules: RuleBook, definitions: dict[str, ActionDefinitionIR | None]) -> dict[str, dict[str, object]]:
    from ..core.action_plan import build_action_execution_plan

    return {
        mode: build_action_execution_plan(
            definition,
            rules.require_action_event(definition.action_id, definition.level),
            rules.hit_profiles_for_action(definition.action_id, definition.level),
            requested_target_ids=("enemy:target",),
            resolved_target_groups={},
            source_trace=definition.source.to_json(),
        ).to_json()
        for mode, definition in definitions.items()
        if definition is not None
    }


def _preflight_negative_cases(
    ir: CanonicalIR,
    rules: RuleBook,
    base_state: BattleState,
    base_command: ActionCommand,
    definitions: dict[str, ActionDefinitionIR | None],
) -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    single = definitions.get("single")
    if single is not None:
        cases["unknown_target"] = _execute_definition_case(
            rules,
            base_state,
            base_command,
            single,
            target_ids=("enemy:missing",),
        )
    costing = _select_costing_definition(ir)
    if costing is not None:
        target_ids = () if costing.target_mode == "aoe" else ("enemy:target",)
        cases["insufficient_sp"] = _execute_definition_case(
            rules,
            replace(base_state, skill_points=0),
            base_command,
            costing,
            target_ids=target_ids,
        )
    if definitions.get("bounce") is not None:
        cases["bounce"] = _execute_definition_case(
            rules,
            base_state,
            base_command,
            definitions["bounce"],
            target_ids=("enemy:target",),
        )
    if definitions.get("unknown") is not None:
        cases["unknown_target_mode"] = _execute_definition_case(
            rules,
            base_state,
            base_command,
            definitions["unknown"],
            target_ids=("enemy:target",),
        )
    return cases


def _select_costing_definition(ir: CanonicalIR) -> ActionDefinitionIR | None:
    for definition in sorted(ir.action_definitions, key=lambda item: (item.source.source_path, item.action_id, item.level)):
        if definition.target_mode not in {"single", "blast", "aoe"}:
            continue
        if definition.damage_kind != "hp_damage" or definition.damage_formula_family != "direct":
            continue
        if definition.bp_need <= 0:
            continue
        if not definition.param_list:
            continue
        return definition
    return None


def _execute_definition_case(
    rules: RuleBook,
    state: BattleState,
    base_command: ActionCommand,
    definition: ActionDefinitionIR,
    *,
    target_ids: tuple[str, ...],
) -> dict[str, Any]:
    command = replace(
        base_command,
        action_id=definition.action_id,
        action_level=definition.level,
        target_ids=target_ids,
    )
    after, transition = CombatExecutor(rules).execute(command, state)
    replay = MutationReducer().replay_snapshot(state, transition.transaction.mutations, after.snapshot().to_json())
    return {
        "definition": definition,
        "before": state,
        "command": command,
        "transition": transition,
        "after": after,
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
    }


def _preflight_commit_gate_checks(cases: dict[str, dict[str, Any]]) -> dict[str, object]:
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    for name, case in cases.items():
        transition = case.get("transition")
        preflight = _preflight_payload(transition)
        checks[f"{name}_case_exists"] = transition is not None
        checks[f"{name}_snapshot_unchanged"] = _snapshot_unchanged(case)
        checks[f"{name}_no_mutations"] = transition is not None and not transition.transaction.mutations
        checks[f"{name}_no_trigger_windows"] = transition is not None and not transition.transaction.trigger_windows
        checks[f"{name}_no_rng_events"] = transition is not None and not transition.rng_events
        checks[f"{name}_action_disabled"] = transition is not None and transition.coverage.get("action_enabled") is False
        checks[f"{name}_blocked_reason_present"] = transition is not None and bool(transition.coverage.get("blocked_reason"))
        checks[f"{name}_preflight_record_consistent"] = bool(preflight) and preflight.get("action_enabled") is False
        checks[f"{name}_action_blocked_record"] = bool(_records_of_type(transition, "action_blocked"))
        checks[f"{name}_no_runtime_mutation_records"] = not any(
            _records_of_type(transition, record_type)
            for record_type in ("timeline", "resource", "damage", "status_lifecycle", "status")
        )
        details[name] = {
            "coverage": transition.coverage if transition is not None else {},
            "preflight": preflight,
            "mutation_count": len(transition.transaction.mutations) if transition is not None else None,
            "trigger_window_count": len(transition.transaction.trigger_windows) if transition is not None else None,
        }
    return {"ok": all(checks.values()), "checks": checks, "details": details}


def _multi_target_context_checks(cases: dict[str, dict[str, Any]]) -> dict[str, object]:
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    for mode in ("aoe", "blast"):
        transition = cases[mode].get("transition")
        plan = transition.coverage.get("action_execution_plan", {}) if transition is not None else {}
        windows = list(transition.transaction.trigger_windows) if transition is not None else []
        checks[f"{mode}_coverage_primary_target"] = bool(transition.coverage.get("primary_action_target_id")) if transition else False
        checks[f"{mode}_coverage_per_hit_context_marked"] = (
            transition is not None and transition.coverage.get("per_hit_target_context_not_implemented") is True
        )
        checks[f"{mode}_plan_per_hit_context_marked"] = isinstance(plan, dict) and plan.get("per_hit_target_context_not_implemented") is True
        checks[f"{mode}_trigger_metadata_multi_target_partial"] = bool(windows) and all(
            isinstance(window.get("metadata"), dict)
            and window["metadata"].get("multi_target_scope_partial") is True
            and window["metadata"].get("per_hit_target_context_not_implemented") is True
            for window in windows
        )
        checks[f"{mode}_damage_metadata_target_group_multiplier_pending"] = _damage_records_have_metadata_value(
            transition,
            "target_group_multiplier_not_implemented",
            True,
        )
        details[mode] = {
            "coverage": transition.coverage if transition is not None else {},
            "trigger_windows": windows,
        }
    return {"ok": all(checks.values()), "checks": checks, "details": details}


def _runtime_import_boundary_check(static_json: dict[str, object]) -> dict[str, object]:
    violations = [
        violation
        for violation in static_json.get("violations", [])
        if isinstance(violation, dict) and str(violation.get("token", "")).startswith("runtime_main_import:")
    ]
    return {"ok": not violations, "violations": violations}


def _snapshot_unchanged(case: dict[str, Any]) -> bool:
    before = case.get("before")
    after = case.get("after")
    if not isinstance(before, BattleState) or not isinstance(after, BattleState):
        return False
    return before.snapshot().to_json() == after.snapshot().to_json()


def _preflight_payload(transition) -> dict[str, Any]:
    records = _records_of_type(transition, "action_preflight")
    if not records:
        return {}
    payload = records[0].get("payload", {})
    return payload if isinstance(payload, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
