from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.fidelity import build_fidelity_matrix
from ..core.reducer import MutationReducer
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.transition_contract import TransitionContractValidator
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


VALIDATION_VERSION = "v0_206"


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    scenario_path: Path,
    max_ability_files: int = 120,
) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root, LoweringLimits(max_ability_files=max_ability_files)).build()
    coverage = build_coverage_matrix(discovery, ir)
    fidelity = build_fidelity_matrix(discovery, ir)
    rules = RuleBook(ir)

    write_json(output_dir / "canonical_ir_v0_206.json", ir.to_json())
    write_json(output_dir / "coverage_matrix_v0_206.json", coverage.to_json())
    write_json(output_dir / "fidelity_matrix_v0_206.json", fidelity.to_json())

    loader = ScenarioLoader()
    scenario = loader.load_path(scenario_path)
    identity = IdentityResolver(rules)
    identity_result = identity.validate(scenario)
    missing_action_level = _missing_action_level_check(loader, scenario_path)
    unknown_action_level = identity.validate(_scenario_with_action_level(scenario, 99))

    builder = ScenarioStateBuilder(rules)
    build_result = builder.build(scenario)
    command = build_result.commands[0]
    executor = CombatExecutor(rules)
    after_state, transition = executor.execute(command, build_result.state)

    snapshot_validator = SnapshotCompletenessValidator()
    transition_validator = TransitionContractValidator()
    reducer = MutationReducer()
    snapshot_result = snapshot_validator.validate(build_result.state.snapshot())
    transition_contract = transition_validator.validate(transition)
    replay = reducer.replay_snapshot(
        build_result.state,
        transition.transaction.mutations,
        after_state.snapshot().to_json(),
    )
    static_result = run_static_checks(package_root)

    action_definition = rules.require_action_definition("avatar_skill:101401", 10)
    action_definition_checks = _action_definition_checks(rules, action_definition)
    prelude_checks = _prelude_checks(build_result.state, after_state, transition)

    insufficient_state = replace(build_result.state, skill_points=0)
    insufficient_command = replace(
        command,
        action_id="avatar_skill:101402",
        action_level=10,
        metadata={**command.metadata, "negative": "insufficient_skill_points_v0_206"},
    )
    insufficient_after, insufficient_transition = executor.execute(insufficient_command, insufficient_state)
    insufficient_check = _insufficient_skill_points_check(
        insufficient_state,
        insufficient_after,
        insufficient_transition,
    )

    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(
            (
                static_result.ok,
                identity_result.ok,
                missing_action_level["ok"],
                not unknown_action_level.ok,
                snapshot_result.ok,
                transition_contract.ok,
                replay.ok,
                action_definition_checks["ok"],
                prelude_checks["ok"],
                insufficient_check["ok"],
            )
        ),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "scenario_path": scenario_path.as_posix(),
            "summary": {
                "discovery_files": len(discovery.files),
                "ir_entities": len(ir.entities),
                "ir_action_definitions": len(ir.action_definitions),
                "ir_triggers": len(ir.triggers),
                "ir_effects": len(ir.effects),
                "ir_conditions": len(ir.conditions),
                "ir_formulas": len(ir.formulas),
                "coverage_opcode_count": len(coverage.opcode_status),
            },
        },
        "scenario": {
            "scenario_id": scenario.scenario_id,
            "identity": identity_result.to_json(),
            "route_count": len(scenario.route),
            "command": {
                "action_id": command.action_id,
                "action_level": command.action_level,
                "metadata_keys": sorted(command.metadata.keys()),
            },
        },
        "action_definition": action_definition_checks,
        "prelude": prelude_checks,
        "negative_checks": {
            "missing_action_level": missing_action_level,
            "unknown_action_level": unknown_action_level.to_json(),
            "insufficient_skill_points": insufficient_check,
        },
        "snapshot_completeness": snapshot_result.to_json(),
        "transition_contract": transition_contract.to_json(),
        "replay": {
            "ok": replay.ok,
            "errors": list(replay.errors),
            "mutation_count": len(transition.transaction.mutations),
        },
        "static_checks": static_result.to_json(),
        "fidelity": fidelity.to_json()["summary"],
    }
    write_json(output_dir / "validation_summary_v0_206.json", result)
    write_json(output_dir / "sample_battle_state_v0_206.json", build_result.state.snapshot().to_json())
    write_json(output_dir / "sample_transition_v0_206.json", transition.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 action definition IR and rule-sourced prelude.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_206"))
    parser.add_argument("--scenario", type=Path, default=None)
    parser.add_argument("--max-ability-files", type=int, default=120)
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
    )
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _missing_action_level_check(loader: ScenarioLoader, scenario_path: Path) -> dict[str, object]:
    import json

    data = json.loads(scenario_path.read_text(encoding="utf-8"))
    del data["route"][0]["action_level"]
    try:
        loader.load_dict(data)
    except Exception as exc:
        return {"ok": "action_level" in str(exc), "error": str(exc)}
    return {"ok": False, "error": "missing action_level was accepted"}


def _scenario_with_action_level(scenario, level: int):
    step = replace(
        scenario.route[0],
        action_level=level,
        metadata={**scenario.route[0].metadata, "negative": "unknown_action_level"},
    )
    return replace(scenario, route=(step, *scenario.route[1:]))


def _action_definition_checks(rules: RuleBook, definition) -> dict[str, object]:
    levels = rules.action_levels("avatar_skill:101401")
    checks = {
        "has_10_levels": len(levels) == 10 and levels == tuple(range(1, 11)),
        "level_10_definition": definition.definition_id == "action_def:avatar_skill:101401:10",
        "bp_add_rule": definition.bp_add == 1.0,
        "bp_need_rule": definition.bp_need == -1.0,
        "sp_base_rule": definition.sp_base == 20.0,
        "param_level_10": definition.param_list == ({"Value": 1.4},),
        "source_is_tbgd_ld": definition.source.source_path == "ExcelOutput/AvatarSkillConfigLD.json",
        "source_row": definition.source.evidence.get("row_index") == 65,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "levels": list(levels),
        "definition": definition.to_json(),
    }


def _prelude_checks(before_state, after_state, transition) -> dict[str, object]:
    records = transition.transaction.settlement.records if transition.transaction.settlement else ()
    action_definition_records = [record for record in records if record.get("record_type") == "action_definition"]
    resource_records = [record for record in records if record.get("record_type") == "resource"]
    resource_mutations = [
        mutation.to_json()
        for mutation in transition.transaction.mutations
        if mutation.source == "combat_executor.resources"
    ]
    metadata_keys = set(transition.transaction.command.metadata)
    resource_metadata_ok = all(
        _has_definition_trace(mutation.get("metadata", {})) for mutation in resource_mutations
    )
    checks = {
        "metadata_no_resource_inputs": "skill_point_delta" not in metadata_keys and "energy_gain" not in metadata_keys,
        "action_definition_record": bool(action_definition_records)
        and all(bool(record.get("process_only")) for record in action_definition_records),
        "resource_records_linked": bool(resource_records)
        and all(record.get("mutation_id") for record in resource_records),
        "resource_metadata_has_definition_trace": resource_metadata_ok,
        "skill_points_3_to_4": before_state.skill_points == 3 and after_state.skill_points == 4,
        "energy_60_to_80": before_state.units["ally:saber"].energy == 60.0
        and after_state.units["ally:saber"].energy == 80.0,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "resource_mutations": resource_mutations,
        "record_counts": {
            "action_definition": len(action_definition_records),
            "resource": len(resource_records),
            "total": len(records),
        },
        "coverage": transition.coverage,
    }


def _insufficient_skill_points_check(before_state, after_state, transition) -> dict[str, object]:
    skill_point_mutations = [
        mutation.to_json()
        for mutation in transition.transaction.mutations
        if mutation.path == ("skill_points",)
    ]
    records = transition.transaction.settlement.records if transition.transaction.settlement else ()
    resource_errors = [record for record in records if record.get("record_type") == "resource_error"]
    definition_records = [record for record in records if record.get("record_type") == "action_definition"]
    return {
        "ok": (
            before_state.skill_points == after_state.skill_points
            and not skill_point_mutations
            and bool(resource_errors)
            and bool(definition_records)
            and transition.coverage.get("definition_id") == "action_def:avatar_skill:101402:10"
            and not bool(transition.coverage.get("resource_ok", True))
        ),
        "before_skill_points": before_state.skill_points,
        "after_skill_points": after_state.skill_points,
        "skill_point_mutations": skill_point_mutations,
        "resource_errors": resource_errors,
        "coverage": transition.coverage,
    }


def _has_definition_trace(metadata: dict[str, Any]) -> bool:
    source_trace = metadata.get("source_trace")
    return (
        metadata.get("definition_id") == "action_def:avatar_skill:101401:10"
        and isinstance(source_trace, dict)
        and bool(source_trace.get("source"))
    )


if __name__ == "__main__":
    raise SystemExit(main())
