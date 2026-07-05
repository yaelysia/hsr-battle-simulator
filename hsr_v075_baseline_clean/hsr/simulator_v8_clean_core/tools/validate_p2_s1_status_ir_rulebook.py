from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..rules.rulebook import RuleBook
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .p2_status_coverage import (
    build_p2_status_coverage_matrix,
    validate_p2_ir_rulebook_integrity_matrix,
    validate_p2_status_inventory_matrix,
)
from .static_checks import run_static_checks


VALIDATION_VERSION = "p2_s1_status_ir_rulebook"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p2_status_coverage_matrix(tbgd_root, ir, rules)
    inventory_checks = validate_p2_status_inventory_matrix(matrix)
    integrity_checks = validate_p2_ir_rulebook_integrity_matrix(matrix)
    definitions = matrix["ir_status_sources"]["definitions"]
    effects = matrix["ir_status_sources"]["status_effects"]
    callbacks = matrix["ir_status_sources"]["callbacks"]
    numeric = matrix["ir_status_sources"]["status_damage_and_numeric"]
    checks = {
        "inventory": inventory_checks,
        "ir_rulebook_integrity": integrity_checks,
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "raw_ir_rulebook_status_integrity",
                "runtime_behavior_changed": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
            },
        },
        "checks": checks,
        "summary": {
            "status_definition_total": matrix["status_catalog"]["status_definition_total"],
            "status_entity_count": definitions["status_entity_count"],
            "status_entities_rulebook_visible": definitions["status_entities_rulebook_visible"],
            "modifier_definition_count": definitions["modifier_definition_count"],
            "modifier_definitions_rulebook_visible": definitions["modifier_definitions_rulebook_visible"],
            "status_effect_source_trace_complete": effects["source_trace_complete"],
            "status_effect_total": effects["total"],
            "status_callback_count": callbacks["total_callbacks"],
            "status_callbacks_rulebook_visible": callbacks["callbacks_rulebook_visible"],
            "status_event_family_count": callbacks["total_event_families"],
            "status_event_families_rulebook_visible": callbacks["event_families_rulebook_visible"],
            "status_damage_emission_count": numeric["status_damage_emission_count"],
            "status_damage_source_trace_complete": numeric["status_damage_source_trace_complete"],
            "classification_counts": matrix["classification_counts"],
            "source_item_counts": matrix["source_item_counts"],
            "unclassified_count": matrix["unclassified_count"],
        },
        "field_presence": {
            "modifier_definition_required_field_counts": definitions["modifier_definition_required_field_counts"],
            "status_entity_field_counts": definitions["status_entity_field_counts"],
        },
        "status_family_matrix": matrix["status_family_matrix"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p2_s1_status_ir_rulebook.json", result)
    write_json(output_dir / "p2_status_coverage_matrix_s1.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P2-S1 status IR and RuleBook source integrity.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
