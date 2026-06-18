from __future__ import annotations

import argparse
from pathlib import Path

from .. import BASELINE_VERSION
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import LoweringLimits, TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json


def build_outputs(tbgd_root: Path, output_dir: Path, max_ability_files: int | None = None) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root, LoweringLimits(max_ability_files=max_ability_files)).build()
    coverage = build_coverage_matrix(discovery, ir)

    discovery_path = output_dir / "tbgd_discovery_v0_200.json"
    ir_path = output_dir / "canonical_ir_v0_200.json"
    coverage_path = output_dir / "coverage_matrix_v0_200.json"
    write_json(discovery_path, discovery.to_json())
    write_json(ir_path, ir.to_json())
    write_json(coverage_path, coverage.to_json())

    return {
        "version": BASELINE_VERSION,
        "tbgd_root": tbgd_root.as_posix(),
        "outputs": {
            "discovery": discovery_path.as_posix(),
            "canonical_ir": ir_path.as_posix(),
            "coverage_matrix": coverage_path.as_posix(),
        },
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
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build v8 Canonical IR from TurnBasedGameData.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_200"))
    parser.add_argument("--max-ability-files", type=int, default=None)
    args = parser.parse_args(argv)

    tbgd_root = args.tbgd_root.resolve() if args.tbgd_root else find_tbgd_root()
    summary = build_outputs(tbgd_root, args.output_dir, max_ability_files=args.max_ability_files)
    write_json(args.output_dir / "build_ir_summary_v0_200.json", summary)
    print(f"wrote v8 IR outputs to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
