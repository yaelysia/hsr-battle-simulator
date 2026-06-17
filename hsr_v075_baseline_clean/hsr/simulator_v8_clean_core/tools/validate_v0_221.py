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
    _case_json,
    _damage_case_json,
    _definition_selection_checks,
    _execute_mode_case,
    _execution_plan_checks,
    _fixed_damage_family_cases,
    _fixed_damage_family_checks,
    _multi_enemy_state,
    _multi_target_damage_checks,
    _records_of_type,
    _target_mode_checks,
    _transition_quality_checks,
    _with_crit_mode,
)
from .validate_v0_219 import (
    _multi_target_context_checks,
    _preflight_commit_gate_checks,
    _preflight_negative_cases,
    _runtime_import_boundary_check,
)
from .validate_v0_220 import (
    _action_event_ir_checks,
    _hit_profile_ir_checks,
    _runtime_hit_profile_path_checks,
    _sample_action_events,
    _sample_hit_profiles,
)


VALIDATION_VERSION = "v0_221"


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
        write_json(output_dir / "canonical_ir_v0_221.json", ir.to_json())
    write_json(output_dir / "canonical_ir_summary_v0_221.json", _canonical_ir_summary(ir))
    write_json(output_dir / "coverage_matrix_v0_221.json", coverage.to_json())
    write_json(output_dir / "fidelity_matrix_v0_221.json", fidelity.to_json())

    scenario = ScenarioLoader().load_path(scenario_path)
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    base_state = _multi_enemy_state(build_result.state)
    base_command = replace(
        build_result.commands[0],
        target_ids=("enemy:target",),
        metadata={**build_result.commands[0].metadata, "crit_mode": "noncrit", "reset_actor_av": False},
    )

    definitions = {mode: _select_bound_definition(ir, mode) for mode in TARGET_MODES}
    execution_cases = {
        mode: _execute_mode_case(rules, base_state, base_command, definition, mode)
        for mode, definition in definitions.items()
    }
    plan_cases = _plan_cases(rules, definitions)
    negative_cases = _preflight_negative_cases(ir, rules, base_state, base_command, definitions)
    no_binding_case = _no_binding_action_case(ir, rules, base_state, base_command)

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
        "action_ability_binding_ir": _action_ability_binding_ir_checks(ir, rules),
        "ability_phase_ir": _ability_phase_ir_checks(ir, rules),
        "action_event_ir": _action_event_ir_checks(ir, rules, definitions),
        "hit_profile_ir": _hit_profile_ir_checks(ir, definitions),
        "definition_selection": _definition_selection_checks(definitions),
        "action_execution_plan": _execution_plan_checks(execution_cases, plan_cases),
        "runtime_action_binding_path": _runtime_action_binding_path_checks(execution_cases, no_binding_case),
        "runtime_hit_profile_path": _runtime_hit_profile_path_checks(package_root, execution_cases, static_result.to_json()),
        "target_modes": _target_mode_checks(execution_cases),
        "multi_target_damage": _multi_target_damage_checks(execution_cases),
        "blocked_modes": _blocked_mode_checks(execution_cases, plan_cases),
        "preflight_commit_gate": _preflight_commit_gate_checks({**negative_cases, "no_binding_action": no_binding_case}),
        "multi_target_context": _multi_target_context_checks(execution_cases),
        "transition_quality": _transition_quality_checks({**execution_cases, **negative_cases, "no_binding_action": no_binding_case}),
        "status_modifier_ledger_regression": _status_modifier_ledger_regression_checks(status_ledger_transition),
        "damage_semantics_regression": _damage_semantics_regression_checks(status_ledger_transition),
        "fixed_damage_families": _fixed_damage_family_checks(fixed_damage_cases),
        "runtime_import_boundary": _runtime_import_boundary_check(static_result.to_json()),
        "runtime_raw_ability_static_guard": _runtime_raw_ability_static_guard(static_result.to_json()),
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
                "ir_action_ability_bindings": len(ir.action_ability_bindings),
                "ir_ability_phases": len(ir.ability_phases),
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
    write_json(output_dir / "validation_summary_v0_221.json", result)
    write_json(output_dir / "sample_action_bindings_v0_221.json", _sample_action_bindings(rules, definitions))
    write_json(output_dir / "sample_ability_phase_graphs_v0_221.json", _sample_ability_phase_graphs(rules, definitions))
    write_json(output_dir / "sample_action_execution_plans_v0_221.json", plan_cases)
    write_json(output_dir / "sample_action_events_v0_221.json", _sample_action_events(rules, definitions))
    write_json(output_dir / "sample_hit_profiles_v0_221.json", _sample_hit_profiles(ir, definitions))
    for mode, case in execution_cases.items():
        transition = case.get("transition")
        write_json(output_dir / f"sample_{mode}_target_case_v0_221.json", _case_json(case))
        if transition is not None:
            write_json(output_dir / f"sample_{mode}_transition_v0_221.json", transition.to_json())
    for name, case in {**negative_cases, "no_binding_action": no_binding_case}.items():
        write_json(output_dir / f"sample_{name}_preflight_v0_221.json", _case_json(case))
        transition = case.get("transition")
        if transition is not None:
            write_json(output_dir / f"sample_{name}_transition_v0_221.json", transition.to_json())
    if status_ledger_transition is not None:
        write_json(output_dir / "sample_status_ledger_transition_v0_221.json", status_ledger_transition.to_json())
    write_json(output_dir / "sample_fixed_damage_families_v0_221.json", _damage_case_json(fixed_damage_cases))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 action ability binding and Ability phase graph baseline.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_221"))
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


def _canonical_ir_summary(ir: CanonicalIR) -> dict[str, object]:
    binding_status_counts: dict[str, int] = {}
    phase_status_counts: dict[str, int] = {}
    event_source_counts: dict[str, int] = {}
    for binding in ir.action_ability_bindings:
        binding_status_counts[binding.coverage_status] = binding_status_counts.get(binding.coverage_status, 0) + 1
    for phase in ir.ability_phases:
        phase_status_counts[phase.coverage_status] = phase_status_counts.get(phase.coverage_status, 0) + 1
    for event in ir.action_events:
        event_source_counts[event.event_source_status] = event_source_counts.get(event.event_source_status, 0) + 1
    return {
        "version": ir.version,
        "metadata": ir.metadata,
        "counts": {
            "entities": len(ir.entities),
            "action_definitions": len(ir.action_definitions),
            "action_ability_bindings": len(ir.action_ability_bindings),
            "ability_phases": len(ir.ability_phases),
            "action_events": len(ir.action_events),
            "hit_profiles": len(ir.hit_profiles),
            "triggers": len(ir.triggers),
            "effects": len(ir.effects),
            "conditions": len(ir.conditions),
            "formulas": len(ir.formulas),
        },
        "binding_status_counts": dict(sorted(binding_status_counts.items())),
        "phase_status_counts": dict(sorted(phase_status_counts.items())),
        "event_source_status_counts": dict(sorted(event_source_counts.items())),
    }


def _select_bound_definition(ir: CanonicalIR, target_mode: str) -> ActionDefinitionIR | None:
    bindings = {(binding.action_id, binding.level): binding for binding in ir.action_ability_bindings}
    events = {(event.action_id, event.level): event for event in ir.action_events}
    profiles_by_action: dict[tuple[str, int], list[Any]] = {}
    for profile in ir.hit_profiles:
        profiles_by_action.setdefault((profile.action_id, profile.level), []).append(profile)
    for definition in sorted(ir.action_definitions, key=lambda item: (item.source.source_path, item.action_id, item.level)):
        if definition.target_mode != target_mode:
            continue
        binding = bindings.get((definition.action_id, definition.level))
        event = events.get((definition.action_id, definition.level))
        if not binding or binding.coverage_status != "executable" or not binding.phase_ids or event is None:
            continue
        if not _is_mainline_avatar_binding(binding):
            continue
        if target_mode in {"single", "aoe", "blast"}:
            if definition.damage_kind != "hp_damage" or definition.damage_formula_family != "direct":
                continue
            profiles = profiles_by_action.get((definition.action_id, definition.level), [])
            if any(profile.coverage_status == "executable" for profile in profiles):
                return definition
            continue
        return definition
    return None


def _is_mainline_avatar_binding(binding: Any) -> bool:
    config_source = binding.config_source if isinstance(binding.config_source, dict) else {}
    return (
        binding.source_mode == "mainline_avatar"
        and isinstance(binding.skill_trigger_key, str)
        and bool(binding.skill_trigger_key)
        and isinstance(binding.entry_ability, str)
        and bool(binding.entry_ability)
        and bool(binding.ability_names)
        and isinstance(config_source.get("character_config_path"), str)
        and str(config_source.get("character_config_path")).startswith("Config/ConfigCharacter/Avatar/")
        and isinstance(config_source.get("ability_file_path"), str)
        and str(config_source.get("ability_file_path")).startswith("Config/ConfigAbility/Avatar/")
    )


def _plan_cases(rules: RuleBook, definitions: dict[str, ActionDefinitionIR | None]) -> dict[str, dict[str, object]]:
    from ..core.action_plan import build_action_execution_plan

    return {
        mode: build_action_execution_plan(
            definition,
            rules.require_action_event(definition.action_id, definition.level),
            rules.hit_profiles_for_action(definition.action_id, definition.level),
            requested_target_ids=("enemy:target",),
            resolved_target_groups={},
            source_trace={
                **definition.source.to_json(),
                "binding_id": (
                    rules.action_ability_binding(definition.action_id, definition.level).binding_id
                    if rules.action_ability_binding(definition.action_id, definition.level)
                    else ""
                ),
                "phase_ids": [
                    phase.phase_id for phase in rules.ability_phases_for_action(definition.action_id, definition.level)
                ],
                "event_source_status": rules.require_action_event(definition.action_id, definition.level).event_source_status,
            },
        ).to_json()
        for mode, definition in definitions.items()
        if definition is not None
    }


def _no_binding_action_case(
    ir: CanonicalIR,
    rules: RuleBook,
    state: BattleState,
    base_command: ActionCommand,
) -> dict[str, Any]:
    definition = _select_no_binding_definition(ir)
    if definition is None:
        return {"definition": None, "transition": None, "after": None, "error": "missing no-binding action"}
    command = replace(
        base_command,
        action_id=definition.action_id,
        action_level=definition.level,
        target_ids=("enemy:target",),
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
        "selection": {
            "selection_mode": "structured_predicate",
            "reason": "binding blocked or missing phase graph",
            "source_trace": definition.source.to_json(),
        },
    }


def _select_no_binding_definition(ir: CanonicalIR) -> ActionDefinitionIR | None:
    bindings = {(binding.action_id, binding.level): binding for binding in ir.action_ability_bindings}
    for definition in sorted(ir.action_definitions, key=lambda item: (item.source.source_path, item.action_id, item.level)):
        if definition.target_mode not in {"single", "blast", "aoe"}:
            continue
        binding = bindings.get((definition.action_id, definition.level))
        if binding is None or binding.coverage_status != "executable":
            return definition
    return None


def _action_ability_binding_ir_checks(ir: CanonicalIR, rules: RuleBook) -> dict[str, object]:
    executable = [binding for binding in ir.action_ability_bindings if binding.coverage_status == "executable"]
    mainline = [binding for binding in executable if _is_mainline_avatar_binding(binding)]
    blocked = [binding for binding in ir.action_ability_bindings if binding.coverage_status == "blocked"]
    checks = {
        "binding_count_matches_definitions": len(ir.action_ability_bindings) == len(ir.action_definitions),
        "mainline_avatar_binding_exists": bool(mainline),
        "all_executable_bindings_have_phase_ids": all(binding.phase_ids for binding in executable),
        "all_blocked_bindings_have_reason": all(binding.blocked_reason for binding in blocked),
        "rulebook_returns_binding": bool(
            mainline
            and rules.action_ability_binding(mainline[0].action_id, mainline[0].level) is not None
        ),
        "sample_has_structured_config_source": bool(mainline and _is_mainline_avatar_binding(mainline[0])),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "sample": mainline[0].to_json() if mainline else None,
        "blocked_samples": [binding.to_json() for binding in blocked[:5]],
    }


def _ability_phase_ir_checks(ir: CanonicalIR, rules: RuleBook) -> dict[str, object]:
    phases = list(ir.ability_phases)
    sample = phases[0] if phases else None
    checks = {
        "ability_phases_exist": bool(phases),
        "all_phases_have_binding": all(phase.binding_id for phase in phases),
        "all_phases_have_ability_name": all(phase.ability_name for phase in phases),
        "all_phases_have_source_trace": all(phase.source.source_path for phase in phases),
        "all_phases_have_opcode_summary": all(isinstance(phase.opcode_summary, dict) for phase in phases),
        "rulebook_returns_phases": bool(
            sample and rules.ability_phases_for_action(sample.action_id, sample.level)
        ),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "sample": sample.to_json() if sample else None,
    }


def _runtime_action_binding_path_checks(
    cases: dict[str, dict[str, Any]],
    no_binding_case: dict[str, Any],
) -> dict[str, object]:
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    for mode in ("single", "aoe", "blast"):
        transition = cases[mode].get("transition")
        binding_records = _records_of_type(transition, "action_ability_binding")
        phase_records = _records_of_type(transition, "ability_phase_graph")
        checks[f"{mode}_has_action_binding_record"] = bool(binding_records)
        checks[f"{mode}_has_ability_phase_graph_record"] = bool(phase_records)
        checks[f"{mode}_coverage_has_binding_id"] = bool(transition and transition.coverage.get("binding_id"))
        checks[f"{mode}_coverage_has_phase_ids"] = bool(transition and transition.coverage.get("phase_ids"))
        checks[f"{mode}_event_source_is_ability_graph"] = (
            transition is not None and transition.coverage.get("event_source_status") == "ability_phase_graph_bound"
        )
        details[mode] = {
            "binding_record": binding_records[0] if binding_records else None,
            "phase_record": phase_records[0] if phase_records else None,
            "coverage": transition.coverage if transition is not None else {},
        }
    no_binding_transition = no_binding_case.get("transition")
    checks["no_binding_case_exists"] = no_binding_transition is not None
    checks["no_binding_action_disabled"] = (
        no_binding_transition is not None and no_binding_transition.coverage.get("action_enabled") is False
    )
    checks["no_binding_snapshot_unchanged"] = _case_snapshot_unchanged(no_binding_case)
    no_binding_record = _records_of_type(no_binding_transition, "action_ability_binding")
    no_binding_payload = no_binding_record[0].get("payload", {}) if no_binding_record else {}
    checks["no_binding_has_blocked_reason"] = (
        no_binding_transition is not None
        and bool(no_binding_transition.coverage.get("blocked_reason"))
        and isinstance(no_binding_payload, dict)
        and no_binding_payload.get("coverage_status") == "blocked"
        and bool(no_binding_payload.get("blocked_reason"))
    )
    details["no_binding_action"] = {
        "definition": no_binding_case.get("definition").to_json() if no_binding_case.get("definition") else None,
        "coverage": no_binding_transition.coverage if no_binding_transition is not None else {},
    }
    return {"ok": all(checks.values()), "checks": checks, "details": details}


def _runtime_raw_ability_static_guard(static_json: dict[str, object]) -> dict[str, object]:
    violations = [
        violation
        for violation in static_json.get("violations", [])
        if isinstance(violation, dict)
        and str(violation.get("token", "")).startswith("runtime_action_inference:")
        and str(violation.get("token", "")).split(":", 1)[-1]
        in {"ConfigAbility", "ConfigCharacter", "AbilityList"}
    ]
    return {"ok": not violations, "violations": violations}


def _sample_action_bindings(rules: RuleBook, definitions: dict[str, ActionDefinitionIR | None]) -> dict[str, Any]:
    samples: dict[str, Any] = {}
    for mode, definition in definitions.items():
        if definition is None:
            samples[mode] = None
            continue
        binding = rules.action_ability_binding(definition.action_id, definition.level)
        samples[mode] = binding.to_json() if binding else None
    return samples


def _sample_ability_phase_graphs(rules: RuleBook, definitions: dict[str, ActionDefinitionIR | None]) -> dict[str, Any]:
    samples: dict[str, Any] = {}
    for mode, definition in definitions.items():
        if definition is None:
            samples[mode] = None
            continue
        samples[mode] = [
            phase.to_json()
            for phase in rules.ability_phases_for_action(definition.action_id, definition.level)
        ]
    return samples


def _case_snapshot_unchanged(case: dict[str, Any]) -> bool:
    before = case.get("before")
    after = case.get("after")
    if not isinstance(before, BattleState) or not isinstance(after, BattleState):
        return False
    return before.snapshot().to_json() == after.snapshot().to_json()


if __name__ == "__main__":
    raise SystemExit(main())
