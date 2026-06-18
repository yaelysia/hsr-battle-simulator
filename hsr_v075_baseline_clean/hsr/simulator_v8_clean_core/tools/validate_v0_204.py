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
from ..scenarios.schema import RouteStepSpec
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import LoweringLimits, TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_204"


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

    write_json(output_dir / "canonical_ir_v0_204.json", ir.to_json())
    write_json(output_dir / "coverage_matrix_v0_204.json", coverage.to_json())
    write_json(output_dir / "fidelity_matrix_v0_204.json", fidelity.to_json())

    loader = ScenarioLoader()
    scenario = loader.load_path(scenario_path)
    identity = IdentityResolver(rules)
    identity_result = identity.validate(scenario)
    builder = ScenarioStateBuilder(rules)
    build_result = builder.build(scenario)

    snapshot_validator = SnapshotCompletenessValidator()
    transition_validator = TransitionContractValidator()
    reducer = MutationReducer()
    executor = CombatExecutor(rules)
    state = build_result.state
    transitions = []
    replay_results = []
    for command in build_result.commands:
        before_state = state
        state, transition = executor.execute(command, state)
        transitions.append(transition)
        replay_results.append(
            reducer.replay_snapshot(
                before_state,
                transition.transaction.mutations,
                transition.after.to_json(),
            )
        )

    first_transition = transitions[0]
    transition_contract = transition_validator.validate(first_transition)
    snapshot_result = snapshot_validator.validate(build_result.state.snapshot())
    missing_ref_result = identity.validate(_scenario_with_missing_ref(scenario))
    wrong_action_result = identity.validate(_scenario_with_wrong_action_type(scenario))
    static_result = run_static_checks(package_root)

    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(
            (
                static_result.ok,
                identity_result.ok,
                snapshot_result.ok,
                transition_contract.ok,
                all(item.ok for item in replay_results),
                not missing_ref_result.ok,
                not wrong_action_result.ok,
                bool(build_result.commands),
                rules.entity("avatar:1014") is not None,
                rules.entity("avatar_skill:101401") is not None,
                rules.entity("monster:1002011") is not None,
                rules.entity("monster_skill:100201101") is not None,
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
            "unit_count": len(scenario.units),
            "route_count": len(scenario.route),
            "identity": identity_result.to_json(),
            "source_trace_count": len(identity_result.source_traces),
        },
        "negative_checks": {
            "missing_entity_ref": missing_ref_result.to_json(),
            "wrong_action_type": wrong_action_result.to_json(),
        },
        "snapshot_completeness": snapshot_result.to_json(),
        "transition_contract": transition_contract.to_json(),
        "replay": {
            "ok": all(item.ok for item in replay_results),
            "results": [{"ok": item.ok, "errors": list(item.errors)} for item in replay_results],
        },
        "static_checks": static_result.to_json(),
        "fidelity": fidelity.to_json()["summary"],
    }
    write_json(output_dir / "validation_summary_v0_204.json", result)
    write_json(output_dir / "sample_battle_state_v0_204.json", build_result.state.snapshot().to_json())
    write_json(output_dir / "sample_transition_v0_204.json", first_transition.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 scenario identity and state build.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_204"))
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


def _scenario_with_missing_ref(scenario):
    unit = replace(scenario.units[0], entity_ref="avatar:missing_for_v0_204")
    return replace(scenario, units=(unit, *scenario.units[1:]))


def _scenario_with_wrong_action_type(scenario):
    step = replace(
        scenario.route[0],
        action_ref="monster:1002011",
        metadata={**scenario.route[0].metadata, "negative": "wrong_action_type"},
    )
    return replace(scenario, route=(step, *scenario.route[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
