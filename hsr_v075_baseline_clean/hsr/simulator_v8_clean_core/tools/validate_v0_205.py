from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

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
from ..systems.resource import ResourcePlan, ResourceSystem
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import LoweringLimits, TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_205"


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    scenario_path: Path,
    max_ability_files: int | None = None,
) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root, LoweringLimits(max_ability_files=max_ability_files)).build()
    coverage = build_coverage_matrix(discovery, ir)
    fidelity = build_fidelity_matrix(discovery, ir)
    rules = RuleBook(ir)

    write_json(output_dir / "canonical_ir_v0_205.json", ir.to_json())
    write_json(output_dir / "coverage_matrix_v0_205.json", coverage.to_json())
    write_json(output_dir / "fidelity_matrix_v0_205.json", fidelity.to_json())

    loader = ScenarioLoader()
    scenario = loader.load_path(scenario_path)
    identity = IdentityResolver(rules)
    identity_result = identity.validate(scenario)
    unknown_target_identity = identity.validate(_scenario_with_unknown_target(scenario))

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
    positive = _positive_prelude_checks(transition, command.actor_id)

    unknown_state, unknown_transition = executor.execute(
        replace(command, target_ids=("enemy:missing",)),
        build_result.state,
    )
    unknown_target_executor = {
        "ok": (
            "enemy:missing" in unknown_transition.target_resolution.rejected
            and not bool(unknown_transition.coverage.get("target_ok", True))
            and not bool(unknown_transition.coverage.get("action_enabled", True))
            and build_result.state.snapshot().to_json() == unknown_state.snapshot().to_json()
            and not unknown_transition.transaction.mutations
        ),
        "after_skill_points": unknown_state.skill_points,
        "target_resolution": unknown_transition.target_resolution.to_json(),
        "coverage": unknown_transition.coverage,
        "mutation_count": len(unknown_transition.transaction.mutations),
    }

    insufficient_state = replace(build_result.state, skill_points=0)
    insufficient_command = replace(
        command,
        action_id="avatar_skill:101402",
        action_level=10,
        metadata={**command.metadata, "negative": "insufficient_skill_points"},
    )
    insufficient_after, insufficient_transition = executor.execute(insufficient_command, insufficient_state)
    insufficient_executor = _insufficient_executor_check(insufficient_state, insufficient_after, insufficient_transition)
    insufficient_direct = ResourceSystem().plan_action_resources(
        insufficient_state,
        command.actor_id,
        ResourcePlan(skill_point_delta=-1, source="validation_v0_205"),
    )
    insufficient_resource_system = {
        "ok": not insufficient_direct.ok and not insufficient_direct.mutations,
        "errors": list(insufficient_direct.errors),
        "mutation_count": len(insufficient_direct.mutations),
    }

    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(
            (
                static_result.ok,
                identity_result.ok,
                not unknown_target_identity.ok,
                snapshot_result.ok,
                transition_contract.ok,
                replay.ok,
                positive["ok"],
                unknown_target_executor["ok"],
                insufficient_executor["ok"],
                insufficient_resource_system["ok"],
            )
        ),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "scenario_path": scenario_path.as_posix(),
            "summary": {
                "discovery_files": len(discovery.files),
                "ir_entities": len(ir.entities),
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
        },
        "prelude": positive,
        "negative_checks": {
            "unknown_target_identity": unknown_target_identity.to_json(),
            "unknown_target_executor": unknown_target_executor,
            "insufficient_skill_points_executor": insufficient_executor,
            "insufficient_skill_points_resource_system": insufficient_resource_system,
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
    write_json(output_dir / "validation_summary_v0_205.json", result)
    write_json(output_dir / "sample_battle_state_v0_205.json", build_result.state.snapshot().to_json())
    write_json(output_dir / "sample_transition_v0_205.json", transition.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 target/resource/timeline action prelude.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_205"))
    parser.add_argument("--scenario", type=Path, default=None)
    parser.add_argument("--max-ability-files", type=int, default=None)
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


def _scenario_with_unknown_target(scenario):
    step = replace(
        scenario.route[0],
        target_ids=("enemy:missing",),
        metadata={**scenario.route[0].metadata, "negative": "unknown_target"},
    )
    return replace(scenario, route=(step, *scenario.route[1:]))


def _positive_prelude_checks(transition, actor_id: str) -> dict[str, object]:
    records = transition.transaction.settlement.records if transition.transaction.settlement else ()
    mutations = transition.transaction.mutations
    target_records = [record for record in records if record.get("record_type") == "target_resolution"]
    timeline_records = [record for record in records if record.get("record_type") == "timeline"]
    resource_records = [record for record in records if record.get("record_type") == "resource"]
    mutation_paths = [tuple(mutation.path) for mutation in mutations]
    checks = {
        "target_selected": transition.target_resolution.selected == ("enemy:target",),
        "target_record_process_only": any(bool(record.get("process_only")) for record in target_records),
        "timeline_linked_records": bool(timeline_records)
        and all(record.get("mutation_id") for record in timeline_records),
        "resource_linked_records": bool(resource_records)
        and all(record.get("mutation_id") for record in resource_records),
        "event_index_mutation": ("event_index",) in mutation_paths,
        "window_mutation": ("global_flags", "current_window") in mutation_paths,
        "turn_owner_mutation": ("global_flags", "turn_owner_id") in mutation_paths,
        "energy_mutation": ("units", actor_id, "energy") in mutation_paths,
        "av_reset_mutation": ("units", actor_id, "action_value") in mutation_paths,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "target_resolution": transition.target_resolution.to_json(),
        "mutation_count": len(mutations),
        "record_counts": {
            "target": len(target_records),
            "timeline": len(timeline_records),
            "resource": len(resource_records),
            "total": len(records),
        },
    }


def _insufficient_executor_check(before_state, after_state, transition) -> dict[str, object]:
    skill_point_mutations = [
        mutation.to_json()
        for mutation in transition.transaction.mutations
        if mutation.path == ("skill_points",)
    ]
    records = transition.transaction.settlement.records if transition.transaction.settlement else ()
    resource_errors = [record for record in records if record.get("record_type") == "resource_error"]
    return {
        "ok": (
            before_state.snapshot().to_json() == after_state.snapshot().to_json()
            and before_state.skill_points == after_state.skill_points
            and not transition.transaction.mutations
            and not skill_point_mutations
            and bool(resource_errors)
            and not bool(transition.coverage.get("resource_ok", True))
            and not bool(transition.coverage.get("action_enabled", True))
        ),
        "before_skill_points": before_state.skill_points,
        "after_skill_points": after_state.skill_points,
        "skill_point_mutations": skill_point_mutations,
        "mutation_count": len(transition.transaction.mutations),
        "resource_errors": resource_errors,
        "coverage": transition.coverage,
    }


if __name__ == "__main__":
    raise SystemExit(main())
