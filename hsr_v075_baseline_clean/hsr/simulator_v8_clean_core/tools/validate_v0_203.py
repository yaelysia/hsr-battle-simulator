from __future__ import annotations

import argparse
from pathlib import Path

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.fidelity import build_fidelity_matrix
from ..core.model import ActionCommand, BattleState, UnitState
from ..core.reducer import MutationReducer
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.transition_contract import TransitionContractValidator
from ..rules.rulebook import RuleBook
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import LoweringLimits, TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_203"


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    max_ability_files: int = 120,
) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root, LoweringLimits(max_ability_files=max_ability_files)).build()
    coverage = build_coverage_matrix(discovery, ir)
    fidelity = build_fidelity_matrix(discovery, ir)

    write_json(output_dir / "tbgd_discovery_v0_203.json", discovery.to_json())
    write_json(output_dir / "canonical_ir_v0_203.json", ir.to_json())
    write_json(output_dir / "coverage_matrix_v0_203.json", coverage.to_json())
    write_json(output_dir / "fidelity_matrix_v0_203.json", fidelity.to_json())

    state = _sample_state()
    executor = CombatExecutor(RuleBook(ir))
    after_state, transition = executor.execute(
        ActionCommand(
            actor_id="ally:seele",
            action_id="avatar_skill:101401",
            action_level=10,
            target_ids=("enemy:dummy",),
            metadata={"validation": VALIDATION_VERSION},
        ),
        state,
    )

    snapshot_validator = SnapshotCompletenessValidator()
    transition_validator = TransitionContractValidator()
    reducer = MutationReducer()

    before_snapshot = snapshot_validator.validate(transition.transaction.before)
    after_snapshot = snapshot_validator.validate(transition.after)
    transition_contract = transition_validator.validate(transition)
    replay = reducer.replay_snapshot(state, transition.transaction.mutations, after_state.snapshot().to_json())
    negative_snapshot = dict(transition.after.to_json())
    negative_snapshot.pop("timeline", None)
    negative_check = snapshot_validator.validate(negative_snapshot)
    static_result = run_static_checks(package_root)

    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(
            (
                static_result.ok,
                before_snapshot.ok,
                after_snapshot.ok,
                transition_contract.ok,
                replay.ok,
                not negative_check.ok,
                bool(fidelity.opcode_status),
                _has_block_reasons(fidelity.to_json()),
            )
        ),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "outputs": {
                "discovery": (output_dir / "tbgd_discovery_v0_203.json").as_posix(),
                "canonical_ir": (output_dir / "canonical_ir_v0_203.json").as_posix(),
                "coverage_matrix": (output_dir / "coverage_matrix_v0_203.json").as_posix(),
                "fidelity_matrix": (output_dir / "fidelity_matrix_v0_203.json").as_posix(),
            },
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
        "static_checks": static_result.to_json(),
        "snapshot_completeness": {
            "before": before_snapshot.to_json(),
            "after": after_snapshot.to_json(),
            "negative_missing_field_check": negative_check.to_json(),
        },
        "transition_contract": transition_contract.to_json(),
        "settlement_traceability": transition_contract.settlement_traceability,
        "replay": {
            "ok": replay.ok,
            "errors": list(replay.errors),
            "mutation_count": len(transition.transaction.mutations),
        },
        "fidelity": fidelity.to_json()["summary"],
    }
    write_json(output_dir / "validation_summary_v0_203.json", result)
    write_json(output_dir / "sample_transition_v0_203.json", transition.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 snapshot and fidelity contract.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_203"))
    parser.add_argument("--max-ability-files", type=int, default=120)
    args = parser.parse_args(argv)

    package_root = Path(__file__).resolve().parents[1]
    tbgd_root = args.tbgd_root.resolve() if args.tbgd_root else find_tbgd_root(package_root)
    result = run_validation(package_root, tbgd_root, args.output_dir, max_ability_files=args.max_ability_files)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _sample_state() -> BattleState:
    return BattleState(
        units={
            "ally:seele": UnitState(
                unit_id="ally:seele",
                side="ally",
                template_id="avatar:1102",
                max_hp=3000.0,
                hp=3000.0,
                attack=3200.0,
                defense=900.0,
                speed=143.0,
                energy=60.0,
                max_energy=120.0,
                flags={"position": 1, "weaknesses": ("Quantum",)},
            ),
            "enemy:dummy": UnitState(
                unit_id="enemy:dummy",
                side="enemy",
                template_id="monster:dummy",
                max_hp=10000.0,
                hp=10000.0,
                attack=1000.0,
                defense=1000.0,
                speed=100.0,
                toughness=90.0,
                max_toughness=90.0,
                flags={"position": 1, "weaknesses": ("Quantum",)},
            ),
        },
        skill_points=3,
        max_skill_points=5,
        global_flags={"phase": "validation", "current_window": "idle", "turn_owner_id": "ally:seele"},
    )


def _has_block_reasons(matrix: dict[str, object]) -> bool:
    opcodes = matrix.get("opcode_status")
    if not isinstance(opcodes, dict):
        return False
    for record in opcodes.values():
        if isinstance(record, dict) and record.get("fidelity_status") == "blocked" and record.get("reason"):
            return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
