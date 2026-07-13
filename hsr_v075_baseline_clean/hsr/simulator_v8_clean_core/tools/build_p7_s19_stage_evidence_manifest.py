from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .io import write_json
from .p7_evidence import file_sha256, source_tree_fingerprint


SUMMARY_FILES = {
    "s1": "validation_summary_p7_s1_transition_trust_contract.json",
    "s2": "validation_summary_p7_s2_mutation_reducer_contract.json",
    "s3": "validation_summary_p7_s3_selected_graph_atomic_commit.json",
    "s4": "validation_summary_p7_s4_rule_audit_separation.json",
    "s5": "validation_summary_p7_s5_typed_expression_ir.json",
    "s6": "validation_summary_p7_s6_action_ownership_window_runtime.json",
    "s7": "validation_summary_p7_s7_target_selection_impact_contract.json",
    "s8": "validation_summary_p7_s8_decision_query_submit_loop.json",
    "s9": "validation_summary_p7_s9_explicit_turn_event_phase_machine.json",
    "s10": "validation_summary_p7_s10_timeline_control_semantics.json",
    "s11": "validation_summary_p7_s11_queue_terminal_progress.json",
    "s12": "validation_summary_p7_s12_damage_toughness_pipeline.json",
    "s13": "validation_summary_p7_s13_shield_hp_routing.json",
    "s14": "validation_summary_p7_s14_status_application_admission.json",
    "s15": "validation_summary_p7_s15_rng_identity_replay.json",
    "s16": "validation_summary_p7_s16_in_combat_summon_lifecycle.json",
    "s17": "validation_summary_p7_s17_wave_lifecycle_events.json",
    "s18": "validation_summary_p7_s18_compact_semantic_state.json",
}


def build_manifest(
    package_root: Path,
    stage_root: Path,
    output_path: Path,
    *,
    s6_real_source_evidence: Path,
) -> dict[str, Any]:
    python_sources = tuple(path for path in package_root.rglob("*.py") if "__pycache__" not in path.parts)
    latest_source_mtime_ns = max((path.stat().st_mtime_ns for path in python_sources), default=0)
    stages: dict[str, dict[str, Any]] = {}
    for stage, filename in SUMMARY_FILES.items():
        summary_path = stage_root / stage / filename
        stages[stage] = {
            "summary": summary_path.as_posix(),
            "summary_sha256": file_sha256(summary_path),
            "summary_exists": summary_path.is_file(),
            "generated_after_current_python_sources": (
                summary_path.is_file() and summary_path.stat().st_mtime_ns >= latest_source_mtime_ns
            ),
        }
    stages["s6"]["real_source_evidence"] = s6_real_source_evidence.as_posix()
    stages["s6"]["real_source_evidence_sha256"] = file_sha256(s6_real_source_evidence)
    checks = {
        "all_summaries_exist": all(entry["summary_exists"] for entry in stages.values()),
        "all_summaries_generated_after_current_python_sources": all(
            entry["generated_after_current_python_sources"] for entry in stages.values()
        ),
        "s6_real_source_evidence_exists": s6_real_source_evidence.is_file(),
    }
    manifest = {
        "schema_version": "p7_s19_stage_evidence_manifest_v2",
        "ok": all(checks.values()),
        "source_tree_fingerprint": source_tree_fingerprint(package_root),
        "checks": checks,
        "stages": stages,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_path, manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bind current P7 stage summaries to the current Python source tree.")
    parser.add_argument("--stage-root", type=Path, required=True)
    parser.add_argument("--s6-real-source-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    result = build_manifest(
        package_root,
        args.stage_root,
        args.output,
        s6_real_source_evidence=args.s6_real_source_evidence,
    )
    print(f"p7_s19_stage_evidence_manifest ok={result['ok']} stages={len(result['stages'])}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
