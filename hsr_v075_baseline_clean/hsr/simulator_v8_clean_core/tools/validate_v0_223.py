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
from ..rules.ir import ActionDefinitionIR, CanonicalIR, DamageEmissionIR
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
    _case_json,
    _damage_case_json,
    _damage_mutation_count,
    _fixed_damage_family_cases,
    _fixed_damage_family_checks,
    _multi_enemy_state,
    _records_of_type,
    _transition_quality_checks,
    _with_crit_mode,
)
from .validate_v0_219 import _runtime_import_boundary_check
from .validate_v0_221 import _runtime_raw_ability_static_guard
from .validate_v0_222 import _target_ids_for_definition


VALIDATION_VERSION = "v0_223"


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
        write_json(output_dir / "canonical_ir_v0_223.json", ir.to_json())
    write_json(output_dir / "canonical_ir_summary_v0_223.json", _canonical_ir_summary(ir))
    write_json(output_dir / "coverage_matrix_v0_223.json", coverage.to_json())
    write_json(output_dir / "fidelity_matrix_v0_223.json", fidelity.to_json())

    scenario = ScenarioLoader().load_path(scenario_path)
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    base_state = _multi_enemy_state(build_result.state)
    base_command = replace(
        build_result.commands[0],
        target_ids=("enemy:target",),
        metadata={**build_result.commands[0].metadata, "crit_mode": "noncrit", "reset_actor_av": False},
    )

    damage_emission_case = _executable_damage_emission_case(ir, rules, base_state, base_command)
    no_fake_damage_case = _no_executable_damage_emission_case(ir, rules, base_state, base_command)

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
        "damage_emission_ir": _damage_emission_ir_checks(ir, rules),
        "runtime_damage_emission_path": _runtime_damage_emission_path_checks(damage_emission_case),
        "no_fake_damage_without_emission": _no_fake_damage_checks(no_fake_damage_case),
        "transition_quality": _transition_quality_checks(
            {"damage_emission": damage_emission_case, "no_fake_damage": no_fake_damage_case}
        ),
        "status_modifier_ledger_regression": _status_modifier_ledger_regression_checks(status_ledger_transition),
        "damage_semantics_regression": _damage_semantics_regression_checks(status_ledger_transition),
        "fixed_damage_families": _fixed_damage_family_checks(fixed_damage_cases),
        "runtime_import_boundary": _runtime_import_boundary_check(static_result.to_json()),
        "runtime_raw_ability_static_guard": _runtime_raw_ability_static_guard(static_result.to_json()),
        "runtime_damage_opcode_static_guard": _runtime_damage_opcode_static_guard(static_result.to_json()),
        "sample_selection_policy": _sample_selection_policy_checks(damage_emission_case, no_fake_damage_case),
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
                "ir_ability_tasks": len(ir.ability_tasks),
                "ir_action_events": len(ir.action_events),
                "ir_hit_profiles": len(ir.hit_profiles),
                "ir_damage_emissions": len(ir.damage_emissions),
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
    write_json(output_dir / "validation_summary_v0_223.json", result)
    write_json(output_dir / "sample_damage_emissions_v0_223.json", _sample_damage_emissions(ir))
    write_json(output_dir / "sample_damage_emission_case_v0_223.json", _damage_emission_case_json(damage_emission_case))
    if damage_emission_case.get("transition") is not None:
        write_json(output_dir / "sample_damage_emission_transition_v0_223.json", damage_emission_case["transition"].to_json())
    write_json(output_dir / "sample_no_fake_damage_case_v0_223.json", _damage_emission_case_json(no_fake_damage_case))
    if no_fake_damage_case.get("transition") is not None:
        write_json(output_dir / "sample_no_fake_damage_transition_v0_223.json", no_fake_damage_case["transition"].to_json())
    if status_ledger_transition is not None:
        write_json(output_dir / "sample_status_ledger_transition_v0_223.json", status_ledger_transition.to_json())
    write_json(output_dir / "sample_fixed_damage_families_v0_223.json", _damage_case_json(fixed_damage_cases))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 DamageEmissionIR and task-sourced damage emission.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_223"))
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
    emission_status_counts: dict[str, int] = {}
    emission_blocked_reasons: dict[str, int] = {}
    emission_raw_ids: dict[str, int] = {}
    for emission in ir.damage_emissions:
        emission_status_counts[emission.coverage_status] = emission_status_counts.get(emission.coverage_status, 0) + 1
        if emission.blocked_reason:
            emission_blocked_reasons[emission.blocked_reason] = emission_blocked_reasons.get(emission.blocked_reason, 0) + 1
        emission_raw_ids[emission.source.raw_id] = emission_raw_ids.get(emission.source.raw_id, 0) + 1
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
            "damage_emissions": len(ir.damage_emissions),
            "effects": len(ir.effects),
            "conditions": len(ir.conditions),
            "formulas": len(ir.formulas),
        },
        "damage_emission_status_counts": dict(sorted(emission_status_counts.items())),
        "damage_emission_blocked_reasons": dict(
            sorted(emission_blocked_reasons.items(), key=lambda item: (-item[1], item[0]))[:20]
        ),
        "damage_emission_raw_ids": dict(sorted(emission_raw_ids.items(), key=lambda item: (-item[1], item[0]))[:20]),
    }


def _damage_emission_ir_checks(ir: CanonicalIR, rules: RuleBook) -> dict[str, object]:
    executable = [emission for emission in ir.damage_emissions if emission.coverage_status == "executable"]
    blocked = [emission for emission in ir.damage_emissions if emission.coverage_status == "blocked"]
    task_ids = {task.task_id for task in ir.ability_tasks}
    hit_profile_ids = {profile.hit_profile_id for profile in ir.hit_profiles}
    checks = {
        "damage_emissions_exist": bool(ir.damage_emissions),
        "executable_damage_emission_exists": bool(executable),
        "blocked_emissions_have_reason": all(emission.blocked_reason for emission in blocked),
        "emission_source_tasks_resolve": all(emission.source_task_id in task_ids for emission in ir.damage_emissions[:2000]),
        "emission_hit_profiles_resolve": all(emission.hit_profile_id in hit_profile_ids for emission in ir.damage_emissions[:2000]),
        "rulebook_returns_emission": bool(executable and rules.damage_emission(executable[0].damage_emission_id) is not None),
        "rulebook_task_index_returns_emission": bool(
            executable and rules.damage_emissions_for_task(executable[0].source_task_id)
        ),
        "executable_has_task_source_trace": all(
            emission.source.raw_type == "AbilityDamageEmission"
            and bool(emission.source_task_id)
            and bool(emission.source.evidence.get("task_id"))
            for emission in executable[:50]
        ),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "executable_sample": executable[0].to_json() if executable else None,
        "blocked_samples": [emission.to_json() for emission in blocked[:5]],
    }


def _executable_damage_emission_case(
    ir: CanonicalIR,
    rules: RuleBook,
    state: BattleState,
    base_command: ActionCommand,
) -> dict[str, Any]:
    for emission in _sorted_emissions(ir.damage_emissions):
        if emission.coverage_status != "executable" or emission.damage_formula_family != "direct":
            continue
        definition = rules.action_definition(emission.action_id, emission.level)
        if definition is None:
            continue
        if rules.ability_task(emission.source_task_id) is None:
            continue
        target_ids = _target_ids_for_definition(definition, base_command.actor_id)
        if target_ids is None:
            continue
        case = _execute_definition_case(rules, state, base_command, definition, target_ids=target_ids)
        transition = case.get("transition")
        if transition is not None and _transition_emits_damage_from_emission(transition, emission):
            case["selected_emission"] = emission
            case["selection"] = _selection_metadata(definition, emission, "executable_damage_emission")
            return case
    return {
        "definition": None,
        "selected_emission": None,
        "transition": None,
        "after": None,
        "error": "missing executable damage emission case",
    }


def _no_executable_damage_emission_case(
    ir: CanonicalIR,
    rules: RuleBook,
    state: BattleState,
    base_command: ActionCommand,
) -> dict[str, Any]:
    emissions_by_action: dict[tuple[str, int], list[DamageEmissionIR]] = {}
    for emission in ir.damage_emissions:
        emissions_by_action.setdefault((emission.action_id, emission.level), []).append(emission)
    for definition in sorted(ir.action_definitions, key=lambda item: (item.source.source_path, item.action_id, item.level)):
        if definition.damage_kind != "hp_damage" or definition.damage_formula_family != "direct":
            continue
        if definition.target_mode not in {"single", "aoe", "blast"}:
            continue
        emissions = emissions_by_action.get((definition.action_id, definition.level), [])
        if any(emission.coverage_status == "executable" for emission in emissions):
            continue
        if emissions and not any(emission.blocked_reason for emission in emissions):
            continue
        target_ids = _target_ids_for_definition(definition, base_command.actor_id)
        if target_ids is None:
            continue
        case = _execute_definition_case(rules, state, base_command, definition, target_ids=target_ids)
        case["selected_emissions"] = tuple(emissions[:10])
        case["selection"] = {
            "selection_mode": "structured_predicate",
            "reason": "supported action with blocked/non-executable damage emissions",
            "target_mode": definition.target_mode,
            "source_trace": definition.source.to_json(),
            "blocked_reasons": sorted({emission.blocked_reason for emission in emissions if emission.blocked_reason})
            or ["damage_emission_missing"],
        }
        if _damage_mutation_count(case.get("transition")) == 0:
            return case
    return {
        "definition": None,
        "selected_emissions": (),
        "transition": None,
        "after": None,
        "error": "missing no fake damage emission case",
    }


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


def _runtime_damage_emission_path_checks(case: dict[str, Any]) -> dict[str, object]:
    transition = case.get("transition")
    emission = case.get("selected_emission")
    checks = {
        "case_exists": transition is not None and isinstance(emission, DamageEmissionIR),
        "action_enabled": transition is not None and transition.coverage.get("action_enabled") is True,
        "coverage_has_damage_emission": transition is not None and transition.coverage.get("executable_damage_emission_count", 0) > 0,
        "has_damage_emissions_record": bool(_records_of_type(transition, "damage_emissions")),
        "has_action_execution_plan_record": bool(_records_of_type(transition, "action_execution_plan")),
        "damage_plan_source_is_emission_ir": _damage_plan_source(transition) == "damage_emission_ir_hit_profile_ir",
        "damage_mutation_exists": _damage_mutation_count(transition) > 0,
        "damage_record_exists": bool(_records_of_type(transition, "damage")),
        "damage_records_have_emission_metadata": _damage_records_have_emission_metadata(transition),
        "damage_mutations_have_emission_metadata": _damage_mutations_have_emission_metadata(transition),
        "selected_emission_reaches_damage_record": isinstance(emission, DamageEmissionIR)
        and _damage_record_has_emission_id(transition, emission.damage_emission_id),
        "selected_emission_task_resolves": isinstance(emission, DamageEmissionIR) and bool(emission.source_task_id),
        "replay_ok": bool(case.get("replay", {}).get("ok")),
    }
    return {"ok": all(checks.values()), "checks": checks, "case": _case_details(case)}


def _no_fake_damage_checks(case: dict[str, Any]) -> dict[str, object]:
    transition = case.get("transition")
    checks = {
        "case_exists": transition is not None,
        "has_blocked_damage_emission_record": _damage_emissions_have_blocked_reason(transition)
        or _has_damage_emission_blocked_record(transition),
        "no_damage_mutation": _damage_mutation_count(transition) == 0,
        "no_damage_record": not _records_of_type(transition, "damage"),
        "damage_plan_empty": not _damage_plan(transition),
        "replay_ok": bool(case.get("replay", {}).get("ok")),
    }
    return {"ok": all(checks.values()), "checks": checks, "case": _case_details(case)}


def _runtime_damage_opcode_static_guard(static_json: dict[str, Any]) -> dict[str, object]:
    violations = [
        violation
        for violation in static_json.get("violations", [])
        if isinstance(violation, dict)
        and str(violation.get("token", "")).startswith("runtime_action_inference:")
        and ("DamageByAttackProperty" in str(violation.get("token")) or "AttackData" in str(violation.get("token")))
    ]
    return {"ok": not violations, "violations": violations}


def _sample_selection_policy_checks(*cases: dict[str, Any]) -> dict[str, object]:
    checks = {}
    for index, case in enumerate(cases):
        selection = case.get("selection", {})
        checks[f"case_{index}_uses_structured_predicate"] = (
            isinstance(selection, dict) and selection.get("selection_mode") == "structured_predicate"
        )
        checks[f"case_{index}_has_source_trace"] = isinstance(selection, dict) and bool(selection.get("source_trace"))
    return {"ok": all(checks.values()), "checks": checks}


def _transition_emits_damage_from_emission(transition: Any, emission: DamageEmissionIR) -> bool:
    return (
        transition is not None
        and _damage_mutation_count(transition) > 0
        and _damage_record_has_emission_id(transition, emission.damage_emission_id)
        and _damage_mutation_has_emission_id(transition, emission.damage_emission_id)
    )


def _damage_records_have_emission_metadata(transition: Any) -> bool:
    records = _records_of_type(transition, "damage")
    if not records:
        return False
    required = ("damage_emission_id", "source_task_id", "hit_profile_id", "scaling_ratio", "hit_source_trace")
    for record in records:
        payload = record.get("payload", {})
        metadata = payload.get("packet_metadata", {}) if isinstance(payload, dict) else {}
        if not isinstance(metadata, dict) or not all(metadata.get(key) not in (None, "") for key in required):
            return False
        if not payload.get("damage_emission_id") or not payload.get("source_task_id"):
            return False
    return True


def _damage_mutations_have_emission_metadata(transition: Any) -> bool:
    if transition is None:
        return False
    mutations = [mutation for mutation in transition.transaction.mutations if mutation.source == "damage_system"]
    if not mutations:
        return False
    for mutation in mutations:
        metadata = mutation.metadata
        if not isinstance(metadata, dict):
            return False
        if not metadata.get("damage_emission_id") or not metadata.get("source_task_id") or not metadata.get("source_trace"):
            return False
    return True


def _damage_record_has_emission_id(transition: Any, emission_id: str) -> bool:
    for record in _records_of_type(transition, "damage"):
        payload = record.get("payload", {})
        if isinstance(payload, dict) and payload.get("damage_emission_id") == emission_id:
            return True
    return False


def _damage_mutation_has_emission_id(transition: Any, emission_id: str) -> bool:
    if transition is None:
        return False
    return any(
        mutation.source == "damage_system"
        and isinstance(mutation.metadata, dict)
        and mutation.metadata.get("damage_emission_id") == emission_id
        for mutation in transition.transaction.mutations
    )


def _damage_plan_source(transition: Any) -> str:
    plan = _action_execution_plan(transition)
    return str(plan.get("damage_plan_source") or "")


def _damage_plan(transition: Any) -> list[Any]:
    plan = _action_execution_plan(transition)
    value = plan.get("damage_plan", [])
    return value if isinstance(value, list) else []


def _action_execution_plan(transition: Any) -> dict[str, Any]:
    if transition is None:
        return {}
    plan = transition.coverage.get("action_execution_plan", {})
    return plan if isinstance(plan, dict) else {}


def _damage_emissions_have_blocked_reason(transition: Any) -> bool:
    for record in _records_of_type(transition, "damage_emissions"):
        payload = record.get("payload", {})
        emissions = payload.get("emissions", []) if isinstance(payload, dict) else []
        if isinstance(emissions, list) and any(
            isinstance(emission, dict) and emission.get("blocked_reason") for emission in emissions
        ):
            return True
    return False


def _has_damage_emission_blocked_record(transition: Any) -> bool:
    for record in _records_of_type(transition, "damage_emission_blocked"):
        payload = record.get("payload", {})
        if isinstance(payload, dict) and payload.get("reason"):
            return True
    return False


def _selection_metadata(
    definition: ActionDefinitionIR,
    emission: DamageEmissionIR,
    reason: str,
) -> dict[str, Any]:
    return {
        "selection_mode": "structured_predicate",
        "reason": reason,
        "target_mode": definition.target_mode,
        "damage_formula_family": emission.damage_formula_family,
        "source_trace": emission.source.to_json(),
    }


def _case_details(case: dict[str, Any]) -> dict[str, Any]:
    transition = case.get("transition")
    selected_emission = case.get("selected_emission")
    selected_emissions = case.get("selected_emissions", ())
    return {
        "definition": case.get("definition").to_json() if case.get("definition") else None,
        "selected_emission": selected_emission.to_json() if isinstance(selected_emission, DamageEmissionIR) else None,
        "selected_emissions": [
            emission.to_json() for emission in selected_emissions if isinstance(emission, DamageEmissionIR)
        ],
        "selection": case.get("selection", {}),
        "coverage": transition.coverage if transition is not None else {},
        "damage_records": _records_of_type(transition, "damage")[:10],
        "damage_emissions_records": _records_of_type(transition, "damage_emissions")[:2],
    }


def _damage_emission_case_json(case: dict[str, Any]) -> dict[str, Any]:
    encoded = _case_json({key: value for key, value in case.items() if key not in {"selected_emission", "selected_emissions"}})
    selected_emission = case.get("selected_emission")
    selected_emissions = case.get("selected_emissions", ())
    if isinstance(selected_emission, DamageEmissionIR):
        encoded["selected_emission"] = selected_emission.to_json()
    if isinstance(selected_emissions, tuple):
        encoded["selected_emissions"] = [
            emission.to_json() for emission in selected_emissions if isinstance(emission, DamageEmissionIR)
        ]
    return encoded


def _sample_damage_emissions(ir: CanonicalIR) -> dict[str, Any]:
    executable = [emission.to_json() for emission in _sorted_emissions(ir.damage_emissions) if emission.coverage_status == "executable"]
    blocked = [emission.to_json() for emission in _sorted_emissions(ir.damage_emissions) if emission.coverage_status == "blocked"]
    return {"executable": executable[:10], "blocked": blocked[:10]}


def _sorted_emissions(emissions: tuple[DamageEmissionIR, ...]) -> list[DamageEmissionIR]:
    return sorted(
        emissions,
        key=lambda emission: (
            emission.source.source_path,
            emission.action_id,
            emission.level,
            emission.phase_id,
            emission.source_task_id,
            emission.damage_emission_id,
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
