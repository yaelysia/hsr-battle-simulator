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
from ..rules.ir import AbilityTaskIR, ActionDefinitionIR, CanonicalIR
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
from .validate_v0_221 import (
    _ability_phase_ir_checks,
    _action_ability_binding_ir_checks,
    _no_binding_action_case,
    _plan_cases,
    _runtime_action_binding_path_checks,
    _runtime_raw_ability_static_guard,
    _sample_ability_phase_graphs,
    _sample_action_bindings,
    _select_bound_definition,
)


VALIDATION_VERSION = "v0_222"


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
        write_json(output_dir / "canonical_ir_v0_222.json", ir.to_json())
    write_json(output_dir / "canonical_ir_summary_v0_222.json", _canonical_ir_summary(ir))
    write_json(output_dir / "coverage_matrix_v0_222.json", coverage.to_json())
    write_json(output_dir / "fidelity_matrix_v0_222.json", fidelity.to_json())

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
    executable_task_case = _executable_ability_task_case(ir, rules, base_state, base_command)
    predicate_blocked_case = _predicate_blocked_case(ir, rules, base_state, base_command)

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
        "ability_task_ir": _ability_task_ir_checks(ir, rules),
        "action_event_ir": _action_event_ir_checks(ir, rules, definitions),
        "hit_profile_ir": _hit_profile_ir_checks(ir, definitions),
        "definition_selection": _definition_selection_checks(definitions),
        "action_execution_plan": _execution_plan_checks(execution_cases, plan_cases),
        "runtime_action_binding_path": _runtime_action_binding_path_checks(execution_cases, no_binding_case),
        "runtime_ability_task_execution": _runtime_ability_task_execution_checks(executable_task_case, predicate_blocked_case),
        "runtime_hit_profile_path": _runtime_hit_profile_path_checks(package_root, execution_cases, static_result.to_json()),
        "target_modes": _target_mode_checks(execution_cases),
        "multi_target_damage": _multi_target_damage_checks(execution_cases),
        "blocked_modes": _blocked_mode_checks(execution_cases, plan_cases),
        "preflight_commit_gate": _preflight_commit_gate_checks({**negative_cases, "no_binding_action": no_binding_case}),
        "multi_target_context": _multi_target_context_checks(execution_cases),
        "transition_quality": _transition_quality_checks(
            {**execution_cases, **negative_cases, "no_binding_action": no_binding_case, "executable_ability_task": executable_task_case, "predicate_blocked": predicate_blocked_case}
        ),
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
                "ir_ability_tasks": len(ir.ability_tasks),
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
    write_json(output_dir / "validation_summary_v0_222.json", result)
    write_json(output_dir / "sample_action_bindings_v0_222.json", _sample_action_bindings(rules, definitions))
    write_json(output_dir / "sample_ability_phase_graphs_v0_222.json", _sample_ability_phase_graphs(rules, definitions))
    write_json(output_dir / "sample_ability_tasks_v0_222.json", _sample_ability_tasks(ir, definitions))
    write_json(output_dir / "sample_action_execution_plans_v0_222.json", plan_cases)
    write_json(output_dir / "sample_action_events_v0_222.json", _sample_action_events(rules, definitions))
    write_json(output_dir / "sample_hit_profiles_v0_222.json", _sample_hit_profiles(ir, definitions))
    for mode, case in execution_cases.items():
        transition = case.get("transition")
        write_json(output_dir / f"sample_{mode}_target_case_v0_222.json", _case_json(case))
        if transition is not None:
            write_json(output_dir / f"sample_{mode}_transition_v0_222.json", transition.to_json())
    for name, case in {**negative_cases, "no_binding_action": no_binding_case}.items():
        write_json(output_dir / f"sample_{name}_preflight_v0_222.json", _case_json(case))
        transition = case.get("transition")
        if transition is not None:
            write_json(output_dir / f"sample_{name}_transition_v0_222.json", transition.to_json())
    for name, case in {"executable_ability_task": executable_task_case, "predicate_blocked": predicate_blocked_case}.items():
        write_json(output_dir / f"sample_{name}_case_v0_222.json", _case_json(case))
        transition = case.get("transition")
        if transition is not None:
            write_json(output_dir / f"sample_{name}_transition_v0_222.json", transition.to_json())
    if status_ledger_transition is not None:
        write_json(output_dir / "sample_status_ledger_transition_v0_222.json", status_ledger_transition.to_json())
    write_json(output_dir / "sample_fixed_damage_families_v0_222.json", _damage_case_json(fixed_damage_cases))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 AbilityTaskIR and phase effect execution spine.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_222"))
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
    task_status_counts: dict[str, int] = {}
    task_opcode_counts: dict[str, int] = {}
    for task in ir.ability_tasks:
        task_status_counts[task.coverage_status] = task_status_counts.get(task.coverage_status, 0) + 1
        task_opcode_counts[task.opcode] = task_opcode_counts.get(task.opcode, 0) + 1
    return {
        "version": ir.version,
        "metadata": ir.metadata,
        "counts": {
            "entities": len(ir.entities),
            "action_definitions": len(ir.action_definitions),
            "action_ability_bindings": len(ir.action_ability_bindings),
            "ability_phases": len(ir.ability_phases),
            "ability_tasks": len(ir.ability_tasks),
            "action_events": len(ir.action_events),
            "hit_profiles": len(ir.hit_profiles),
            "triggers": len(ir.triggers),
            "effects": len(ir.effects),
            "conditions": len(ir.conditions),
            "formulas": len(ir.formulas),
        },
        "ability_task_status_counts": dict(sorted(task_status_counts.items())),
        "ability_task_top_opcodes": dict(sorted(task_opcode_counts.items(), key=lambda item: (-item[1], item[0]))[:20]),
    }


def _ability_task_ir_checks(ir: CanonicalIR, rules: RuleBook) -> dict[str, object]:
    tasks_by_id = {task.task_id: task for task in ir.ability_tasks}
    executable = [task for task in ir.ability_tasks if task.coverage_status == "executable"]
    blocked = [task for task in ir.ability_tasks if task.coverage_status == "blocked"]
    predicate_blocked = [
        task
        for task in blocked
        if task.opcode == "PredicateTaskList" and task.blocked_reason.startswith("condition_not_executable")
    ]
    checks = {
        "ability_tasks_exist": bool(ir.ability_tasks),
        "executable_task_exists": bool(executable),
        "blocked_task_has_reason": all(task.blocked_reason for task in blocked),
        "phase_task_ids_resolve": all(
            task_id in tasks_by_id
            for phase in ir.ability_phases
            for task_id in phase.task_ids
        ),
        "task_phase_ids_resolve": all(
            any(phase.phase_id == task.phase_id for phase in ir.ability_phases)
            for task in ir.ability_tasks[:2000]
        ),
        "rulebook_returns_task": bool(executable and rules.ability_task(executable[0].task_id) is not None),
        "predicate_blocked_sample_exists": bool(predicate_blocked),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "executable_sample": executable[0].to_json() if executable else None,
        "predicate_blocked_sample": predicate_blocked[0].to_json() if predicate_blocked else None,
        "blocked_samples": [task.to_json() for task in blocked[:5]],
    }


def _executable_ability_task_case(
    ir: CanonicalIR,
    rules: RuleBook,
    state: BattleState,
    base_command: ActionCommand,
) -> dict[str, Any]:
    for task in sorted(ir.ability_tasks, key=lambda item: (item.source.source_path, item.action_id, item.level, item.task_path)):
        if task.coverage_status != "executable":
            continue
        definition = rules.action_definition(task.action_id, task.level)
        binding = rules.action_ability_binding(task.action_id, task.level)
        if definition is None or binding is None or binding.coverage_status != "executable":
            continue
        target_ids = _target_ids_for_definition(definition, base_command.actor_id)
        if target_ids is None:
            continue
        case = _execute_definition_case(rules, state, base_command, definition, target_ids=target_ids)
        transition = case.get("transition")
        if (
            transition is not None
            and transition.coverage.get("action_enabled") is True
            and transition.coverage.get("ability_task_mutation_count", 0) > 0
            and _has_task_record(transition, task.task_id, ok=True)
        ):
            case["selected_task"] = task
            return case
    return {"definition": None, "selected_task": None, "transition": None, "after": None, "error": "missing executable ability task case"}


def _predicate_blocked_case(
    ir: CanonicalIR,
    rules: RuleBook,
    state: BattleState,
    base_command: ActionCommand,
) -> dict[str, Any]:
    for task in sorted(ir.ability_tasks, key=lambda item: (item.source.source_path, item.action_id, item.level, item.task_path)):
        if task.opcode != "PredicateTaskList" or task.parent_task_id:
            continue
        if not task.blocked_reason.startswith("condition_not_executable"):
            continue
        definition = rules.action_definition(task.action_id, task.level)
        binding = rules.action_ability_binding(task.action_id, task.level)
        if definition is None or binding is None or binding.coverage_status != "executable":
            continue
        target_ids = _target_ids_for_definition(definition, base_command.actor_id)
        if target_ids is None:
            continue
        case = _execute_definition_case(rules, state, base_command, definition, target_ids=target_ids)
        transition = case.get("transition")
        if transition is not None and _has_task_record(transition, task.task_id, ok=False):
            case["selected_task"] = task
            return case
    return {"definition": None, "selected_task": None, "transition": None, "after": None, "error": "missing predicate blocked case"}


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


def _target_ids_for_definition(definition: ActionDefinitionIR, actor_id: str) -> tuple[str, ...] | None:
    if definition.target_mode == "aoe":
        return ()
    if definition.target_mode == "self_or_team":
        return (actor_id,)
    if definition.target_mode in {"single", "blast"}:
        return ("enemy:target",)
    return None


def _runtime_ability_task_execution_checks(
    executable_case: dict[str, Any],
    predicate_case: dict[str, Any],
) -> dict[str, object]:
    executable_transition = executable_case.get("transition")
    predicate_transition = predicate_case.get("transition")
    executable_task = executable_case.get("selected_task")
    predicate_task = predicate_case.get("selected_task")
    checks = {
        "executable_case_exists": executable_transition is not None and isinstance(executable_task, AbilityTaskIR),
        "executable_action_enabled": executable_transition is not None and executable_transition.coverage.get("action_enabled") is True,
        "executable_task_mutates": executable_transition is not None and executable_transition.coverage.get("ability_task_mutation_count", 0) > 0,
        "executable_task_record_ok": isinstance(executable_task, AbilityTaskIR)
        and _has_task_record(executable_transition, executable_task.task_id, ok=True),
        "executable_transition_has_task_graph": bool(_records_of_type(executable_transition, "ability_task_graph")),
        "executable_replay_ok": bool(executable_case.get("replay", {}).get("ok")),
        "predicate_case_exists": predicate_transition is not None and isinstance(predicate_task, AbilityTaskIR),
        "predicate_action_enabled": predicate_transition is not None and predicate_transition.coverage.get("action_enabled") is True,
        "predicate_blocked_record": isinstance(predicate_task, AbilityTaskIR)
        and _has_task_record(predicate_transition, predicate_task.task_id, ok=False),
        "predicate_did_not_default_success": isinstance(predicate_task, AbilityTaskIR)
        and not any(_has_task_record(predicate_transition, child_id, ok=True) for child_id in predicate_task.success_task_ids),
        "predicate_replay_ok": bool(predicate_case.get("replay", {}).get("ok")),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "executable": _case_details(executable_case),
        "predicate_blocked": _case_details(predicate_case),
    }


def _has_task_record(transition: Any, task_id: str, *, ok: bool) -> bool:
    for record in _records_of_type(transition, "ability_task"):
        payload = record.get("payload", {})
        if isinstance(payload, dict) and payload.get("task_id") == task_id and payload.get("ok") is ok:
            return True
    return False


def _case_details(case: dict[str, Any]) -> dict[str, Any]:
    transition = case.get("transition")
    task = case.get("selected_task")
    return {
        "definition": case.get("definition").to_json() if case.get("definition") else None,
        "selected_task": task.to_json() if isinstance(task, AbilityTaskIR) else None,
        "coverage": transition.coverage if transition is not None else {},
        "ability_task_records": _records_of_type(transition, "ability_task")[:10],
    }


def _sample_ability_tasks(ir: CanonicalIR, definitions: dict[str, ActionDefinitionIR | None]) -> dict[str, Any]:
    samples: dict[str, Any] = {}
    for mode, definition in definitions.items():
        if definition is None:
            samples[mode] = None
            continue
        samples[mode] = [
            task.to_json()
            for task in ir.ability_tasks
            if task.action_id == definition.action_id and task.level == definition.level
        ][:50]
    return samples


if __name__ == "__main__":
    raise SystemExit(main())
