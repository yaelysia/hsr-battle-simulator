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
from ..rules.ir import ActionDefinitionIR, CanonicalIR, HitProfileIR
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
    _select_definition,
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


VALIDATION_VERSION = "v0_220"


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
        write_json(output_dir / "canonical_ir_v0_220.json", ir.to_json())
    write_json(output_dir / "canonical_ir_summary_v0_220.json", _canonical_ir_summary(ir))
    write_json(output_dir / "coverage_matrix_v0_220.json", coverage.to_json())
    write_json(output_dir / "fidelity_matrix_v0_220.json", fidelity.to_json())

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
    plan_cases = _plan_cases(rules, definitions)
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
        "action_event_ir": _action_event_ir_checks(ir, rules, definitions),
        "hit_profile_ir": _hit_profile_ir_checks(ir, definitions),
        "definition_selection": _definition_selection_checks(definitions),
        "action_execution_plan": _execution_plan_checks(execution_cases, plan_cases),
        "runtime_hit_profile_path": _runtime_hit_profile_path_checks(package_root, execution_cases, static_result.to_json()),
        "target_modes": _target_mode_checks(execution_cases),
        "multi_target_damage": _multi_target_damage_checks(execution_cases),
        "blocked_modes": _blocked_mode_checks(execution_cases, plan_cases),
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
    write_json(output_dir / "validation_summary_v0_220.json", result)
    write_json(output_dir / "sample_action_execution_plans_v0_220.json", plan_cases)
    write_json(output_dir / "sample_action_events_v0_220.json", _sample_action_events(rules, definitions))
    write_json(output_dir / "sample_hit_profiles_v0_220.json", _sample_hit_profiles(ir, definitions))
    for mode, case in execution_cases.items():
        transition = case.get("transition")
        write_json(output_dir / f"sample_{mode}_target_case_v0_220.json", _case_json(case))
        if transition is not None:
            write_json(output_dir / f"sample_{mode}_transition_v0_220.json", transition.to_json())
    for name, case in negative_cases.items():
        write_json(output_dir / f"sample_{name}_preflight_v0_220.json", _case_json(case))
        transition = case.get("transition")
        if transition is not None:
            write_json(output_dir / f"sample_{name}_transition_v0_220.json", transition.to_json())
    if status_ledger_transition is not None:
        write_json(output_dir / "sample_status_ledger_transition_v0_220.json", status_ledger_transition.to_json())
    write_json(output_dir / "sample_fixed_damage_families_v0_220.json", _damage_case_json(fixed_damage_cases))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 ActionEventIR and HitProfileIR action execution baseline.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_220"))
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
    target_mode_counts: dict[str, int] = {}
    hit_status_counts: dict[str, int] = {}
    for definition in ir.action_definitions:
        target_mode_counts[definition.target_mode] = target_mode_counts.get(definition.target_mode, 0) + 1
    for profile in ir.hit_profiles:
        hit_status_counts[profile.coverage_status] = hit_status_counts.get(profile.coverage_status, 0) + 1
    return {
        "version": ir.version,
        "metadata": ir.metadata,
        "counts": {
            "entities": len(ir.entities),
            "action_definitions": len(ir.action_definitions),
            "action_events": len(ir.action_events),
            "hit_profiles": len(ir.hit_profiles),
            "triggers": len(ir.triggers),
            "effects": len(ir.effects),
            "conditions": len(ir.conditions),
            "formulas": len(ir.formulas),
        },
        "target_mode_counts": dict(sorted(target_mode_counts.items())),
        "hit_profile_status_counts": dict(sorted(hit_status_counts.items())),
    }


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


def _action_event_ir_checks(
    ir: CanonicalIR,
    rules: RuleBook,
    definitions: dict[str, ActionDefinitionIR | None],
) -> dict[str, object]:
    checks = {
        "action_event_count_matches_definitions": len(ir.action_events) == len(ir.action_definitions),
        "all_events_have_source_trace": all(event.source.source_path for event in ir.action_events),
        "all_events_mark_derived": all(event.derived_status == "derived_from_action_definition" for event in ir.action_events),
    }
    details: dict[str, Any] = {}
    for mode, definition in definitions.items():
        if definition is None:
            checks[f"{mode}_event_available"] = False
            continue
        event = rules.action_event(definition.action_id, definition.level)
        checks[f"{mode}_event_available"] = event is not None
        checks[f"{mode}_event_matches_definition"] = bool(
            event is not None
            and event.action_id == definition.action_id
            and event.level == definition.level
            and event.target_mode == definition.target_mode
        )
        if mode in {"bounce", "unknown"}:
            checks[f"{mode}_event_blocked"] = bool(event and event.blocked_reason)
        if definition.damage_kind == "hp_damage" and definition.target_mode not in {"unknown", "bounce"}:
            checks[f"{mode}_event_has_hit_profile_ids"] = bool(event and event.hit_profile_ids)
        details[mode] = event.to_json() if event is not None else None
    return {"ok": all(checks.values()), "checks": checks, "details": details}


def _hit_profile_ir_checks(
    ir: CanonicalIR,
    definitions: dict[str, ActionDefinitionIR | None],
) -> dict[str, object]:
    profiles_by_action: dict[tuple[str, int], list[HitProfileIR]] = {}
    for profile in ir.hit_profiles:
        profiles_by_action.setdefault((profile.action_id, profile.level), []).append(profile)
    evidence_profiles = [
        profile
        for profile in ir.hit_profiles
        if profile.multiplier_source.get("multi_param_list_not_implemented") is True
        or profile.multiplier_source.get("show_damage_audit_only") is True
        or profile.stance_source.get("show_stance_audit_only") is True
    ]
    checks = {
        "hit_profiles_exist": bool(ir.hit_profiles),
        "blocked_profiles_have_reason": all(
            profile.coverage_status != "blocked" or bool(profile.blocked_reason)
            for profile in ir.hit_profiles
        ),
        "multi_param_or_show_evidence_lowered": bool(evidence_profiles),
        "evidence_profiles_mark_structural_or_blocked": bool(evidence_profiles)
        and all(
            profile.numeric_fidelity_status in {"structural_only", "blocked"}
            or bool(profile.blocked_reason)
            for profile in evidence_profiles[:20]
        ),
    }
    details: dict[str, Any] = {
        "evidence_samples": [profile.to_json() for profile in evidence_profiles[:5]],
    }
    for mode, definition in definitions.items():
        if definition is None:
            checks[f"{mode}_profiles_available"] = False
            continue
        profiles = profiles_by_action.get((definition.action_id, definition.level), [])
        checks[f"{mode}_profiles_available"] = bool(profiles) if definition.damage_kind == "hp_damage" else True
        if mode in {"single", "aoe", "blast"}:
            checks[f"{mode}_has_executable_profile"] = any(profile.coverage_status == "executable" for profile in profiles)
        if mode in {"bounce", "unknown"}:
            checks[f"{mode}_profile_absent_or_blocked"] = (
                not profiles or any(profile.coverage_status == "blocked" for profile in profiles)
            )
        details[mode] = [profile.to_json() for profile in profiles]
    return {"ok": all(checks.values()), "checks": checks, "details": details}


def _runtime_hit_profile_path_checks(
    package_root: Path,
    cases: dict[str, dict[str, Any]],
    static_json: dict[str, object],
) -> dict[str, object]:
    violations = [
        violation
        for violation in static_json.get("violations", [])
        if isinstance(violation, dict) and str(violation.get("token", "")).startswith("runtime_action_inference:")
    ]
    checks: dict[str, bool] = {
        "static_no_runtime_action_inference_tokens": not violations,
        "damage_formula_no_param_list_index": "param_list[0]" not in (
            package_root / "systems/damage_formula.py"
        ).read_text(encoding="utf-8"),
    }
    details: dict[str, Any] = {"static_violations": violations}
    for mode in ("single", "aoe", "blast"):
        transition = cases[mode].get("transition")
        damage_records = _records_of_type(transition, "damage")
        plan = transition.coverage.get("action_execution_plan", {}) if transition is not None else {}
        checks[f"{mode}_transition_has_action_event_ir_record"] = bool(_records_of_type(transition, "action_event_ir"))
        checks[f"{mode}_transition_has_hit_profiles_record"] = bool(_records_of_type(transition, "hit_profiles"))
        checks[f"{mode}_coverage_has_action_event_id"] = bool(
            transition is not None and transition.coverage.get("action_event_id")
        )
        checks[f"{mode}_plan_source_is_ir"] = isinstance(plan, dict) and plan.get("plan_source") == "action_event_ir_hit_profile_ir"
        checks[f"{mode}_hit_plan_has_profile_ids"] = _plan_hit_entries_have(plan, "hit_profile_id")
        checks[f"{mode}_damage_records_have_profile_ids"] = _damage_records_have_packet_metadata(damage_records, "hit_profile_id")
        checks[f"{mode}_damage_records_have_scaling_ratio"] = _damage_records_have_packet_metadata(damage_records, "scaling_ratio")
        checks[f"{mode}_damage_records_have_hit_source_trace"] = _damage_records_have_packet_metadata(damage_records, "hit_source_trace")
        checks[f"{mode}_damage_records_have_numeric_fidelity"] = _damage_records_have_packet_metadata(
            damage_records,
            "numeric_fidelity_status",
        )
        if mode in {"aoe", "blast"}:
            checks[f"{mode}_damage_structural_only"] = all(
                _packet_metadata(record).get("numeric_fidelity_status") == "structural_only"
                for record in damage_records
            )
        details[mode] = {
            "coverage": transition.coverage if transition is not None else {},
            "damage_record_count": len(damage_records),
            "first_damage_record": damage_records[0] if damage_records else None,
        }
    return {"ok": all(checks.values()), "checks": checks, "details": details}


def _plan_hit_entries_have(plan: dict[str, Any], key: str) -> bool:
    hit_plan = plan.get("hit_plan") if isinstance(plan, dict) else None
    if not isinstance(hit_plan, list) or not hit_plan:
        return False
    return all(isinstance(item, dict) and key in item for item in hit_plan)


def _damage_records_have_packet_metadata(records: list[dict[str, Any]], key: str) -> bool:
    if not records:
        return False
    return all(key in _packet_metadata(record) for record in records)


def _packet_metadata(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("payload", {}) if isinstance(record, dict) else {}
    metadata = payload.get("packet_metadata", {}) if isinstance(payload, dict) else {}
    return metadata if isinstance(metadata, dict) else {}


def _sample_action_events(
    rules: RuleBook,
    definitions: dict[str, ActionDefinitionIR | None],
) -> dict[str, Any]:
    samples: dict[str, Any] = {}
    for mode, definition in definitions.items():
        if definition is None:
            samples[mode] = None
            continue
        event = rules.action_event(definition.action_id, definition.level)
        samples[mode] = event.to_json() if event is not None else None
    return samples


def _sample_hit_profiles(
    ir: CanonicalIR,
    definitions: dict[str, ActionDefinitionIR | None],
) -> dict[str, Any]:
    samples: dict[str, Any] = {}
    for mode, definition in definitions.items():
        if definition is None:
            samples[mode] = None
            continue
        samples[mode] = [
            profile.to_json()
            for profile in ir.hit_profiles
            if profile.action_id == definition.action_id and profile.level == definition.level
        ]
    return samples


if __name__ == "__main__":
    raise SystemExit(main())
