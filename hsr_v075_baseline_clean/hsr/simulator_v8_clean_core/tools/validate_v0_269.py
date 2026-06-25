from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..rules.rulebook import RuleBook
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_248 import _manual_ultimate_execution_case
from .validate_v0_249 import _ultimate_energy_mutation_json


VALIDATION_VERSION = "v0_269"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    manual_ultimate = _manual_ultimate_execution_case(ir, rules)
    selected_action = manual_ultimate["selected_action"]
    energy_mutation = _ultimate_energy_mutation_json(manual_ultimate)
    expected_after = float(selected_action.get("sp_base", 0.0))
    metadata = energy_mutation.get("metadata", {}) if isinstance(energy_mutation, dict) else {}
    local_spbase_distribution = _ultimate_spbase_distribution(ir)
    checks = {
        "manual_ultimate_execution": {
            "ok": bool(manual_ultimate["checks"].get("ok")),
            "checks": manual_ultimate["checks"],
        },
        "ultimate_post_use_energy": {
            "ok": all(
                (
                    isinstance(energy_mutation, dict),
                    expected_after > 0.0,
                    float(energy_mutation.get("after", -1.0)) == expected_after,
                    float(metadata.get("post_use_energy_gain", -1.0)) == expected_after,
                    metadata.get("post_use_energy_gain_source") == "ActionDefinitionIR.sp_base",
                    metadata.get("resource_operation") == "ultimate_energy_cost",
                )
            ),
            "checks": {
                "energy_mutation_present": isinstance(energy_mutation, dict),
                "selected_action_sp_base_positive": expected_after > 0.0,
                "after_energy_equals_action_sp_base": isinstance(energy_mutation, dict)
                and float(energy_mutation.get("after", -1.0)) == expected_after,
                "metadata_post_use_gain_equals_action_sp_base": float(metadata.get("post_use_energy_gain", -1.0)) == expected_after,
                "metadata_source_is_action_definition_sp_base": metadata.get("post_use_energy_gain_source") == "ActionDefinitionIR.sp_base",
                "resource_operation_is_ultimate_energy_cost": metadata.get("resource_operation") == "ultimate_energy_cost",
            },
            "expected_after_energy": expected_after,
            "energy_mutation": energy_mutation,
        },
        "source_audit": {
            "ok": bool(manual_ultimate["drain_source_audit"].get("ok")),
            "drain_source_audit": manual_ultimate["drain_source_audit"],
        },
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
            "selection_policy": {
                "ultimate": "manual ultimate request selected structurally from executable avatar ActionDefinitionIR; expected post-use energy is ActionDefinitionIR.sp_base, not a fixed hardcoded value",
            },
        },
        "checks": checks,
        "local_tbgd_ultimate_spbase_distribution": local_spbase_distribution,
        "selected_action": selected_action,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_269.json", result)
    write_json(output_dir / "sample_manual_ultimate_post_use_energy_v0_269.json", manual_ultimate["drain_transition"])
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_269 ultimate post-use energy from action SPBase.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _ultimate_spbase_distribution(ir) -> dict[str, Any]:
    values = Counter(
        str(action.sp_base)
        for action in ir.action_definitions
        if action.attack_type == "Ultra" and action.coverage_status == "executable"
    )
    return {
        "source": "Canonical ActionDefinitionIR built from TBGD AvatarSkillConfig.SPBase",
        "counts": dict(sorted(values.items())),
    }


if __name__ == "__main__":
    raise SystemExit(main())
