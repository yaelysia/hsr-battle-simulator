from __future__ import annotations

import argparse
from pathlib import Path

from .. import BASELINE_VERSION
from ..tbgd.paths import find_tbgd_root
from .build_ir import build_outputs
from .io import write_json
from .snapshot_replay import run_snapshot_replay_check
from .static_checks import run_static_checks


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path, max_ability_files: int | None = None) -> dict[str, object]:
    build_summary = build_outputs(tbgd_root, output_dir, max_ability_files=max_ability_files)
    static_result = run_static_checks(package_root)
    replay_result = run_snapshot_replay_check()
    result = {
        "version": BASELINE_VERSION,
        "ok": static_result.ok and bool(replay_result["ok"]),
        "build": build_summary,
        "static_checks": static_result.to_json(),
        "snapshot_replay": replay_result,
    }
    write_json(output_dir / "validation_summary_v0_200.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 TBGD-first clean core baseline.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_200"))
    parser.add_argument("--max-ability-files", type=int, default=None)
    args = parser.parse_args(argv)

    package_root = Path(__file__).resolve().parents[1]
    tbgd_root = args.tbgd_root.resolve() if args.tbgd_root else find_tbgd_root(package_root)
    result = run_validation(package_root, tbgd_root, args.output_dir, max_ability_files=args.max_ability_files)
    print(f"v8 {BASELINE_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
