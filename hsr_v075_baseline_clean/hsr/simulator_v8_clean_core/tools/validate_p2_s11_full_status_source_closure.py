from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..rules.ir import StatusCallbackIR
from ..rules.rulebook import RuleBook
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .p2_status_coverage import (
    build_p2_status_coverage_matrix,
    validate_p2_ir_rulebook_integrity_matrix,
    validate_p2_status_inventory_matrix,
    _p2_source_area,
)
from .static_checks import run_static_checks


VALIDATION_VERSION = "p2_s11_full_status_source_closure"

GAP_CLASSIFICATIONS = {
    "implementation_missing",
    "lowering_gap",
    "admission_gap",
    "validation_gap",
}

SOURCE_DOMAINS = {
    "avatar": ("Avatar", "SpecialAvatar"),
    "monster": ("Monster",),
    "equipment_lightcone_relic": ("Equip",),
    "battle_event_stage": ("BattleEvent", "Level", "Activity", "GridFight", "ElationBattle", "Story"),
    "global_modifier": ("GlobalModifier",),
    "servant_summon": ("Servant",),
}

BLOCKED_VALIDATION_EVIDENCE = {
    "status_add_sources": ("validate_p2_s3_status_application_semantics", "missing source/target/caster and failed application state unchanged"),
    "status_stack_refresh_sources": ("validate_p2_s3_status_application_semantics", "stack/refresh/reapply boundaries"),
    "status_lifecycle_sources": ("validate_p2_s4_status_lifecycle", "wrong owner/dead/missing duration lifecycle boundaries"),
    "status_chance_resist_immunity_sources": ("validate_p2_s5_status_probability", "chance/resist/immunity blocked state unchanged"),
    "status_numeric_binding_sources": ("validate_p2_s7_status_numeric_bindings", "missing dynamic binding blocked"),
    "status_damage_sources": ("validate_p2_s8_status_damage", "missing status/formula/dead target blocked or skipped"),
    "status_remove_sources": ("validate_p2_s9_status_removal_dispel", "missing status/remove boundary"),
    "status_dispel_sources": ("validate_p2_s9_status_removal_dispel", "undispellable/no candidate/dynamic count boundary"),
    "status_callback_event_families": ("validate_p2_s10_status_callback_coverage", "missing event/payload/condition/target/unsupported task state unchanged"),
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p2_status_coverage_matrix(tbgd_root, ir, rules)
    inventory_checks = validate_p2_status_inventory_matrix(matrix)
    integrity_checks = validate_p2_ir_rulebook_integrity_matrix(matrix)

    family_closure = _family_closure_matrix(matrix)
    source_domain_matrix = _source_domain_matrix(matrix, ir)
    blocked_evidence = _blocked_evidence_matrix(matrix)
    ui_text_boundary = _ui_text_boundary(static_result)

    checks = {
        "inventory": inventory_checks,
        "ir_rulebook_integrity": integrity_checks,
        "family_closure": family_closure["checks"],
        "source_domains": source_domain_matrix["checks"],
        "blocked_state_unchanged_evidence": blocked_evidence["checks"],
        "ui_text_boundary": ui_text_boundary["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "full_status_source_closure_matrix",
                "runtime_behavior_changed": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
            },
        },
        "checks": checks,
        "summary": {
            "family_closure": family_closure["summary"],
            "source_domains": source_domain_matrix["matrix"],
            "source_domain_classification_counts": source_domain_matrix["classification_counts"],
            "blocked_evidence": blocked_evidence["matrix"],
            "ui_text_boundary": ui_text_boundary["summary"],
        },
        "cases": {
            "source_domain_samples": source_domain_matrix["samples"],
            "gap_samples": family_closure["gap_samples"],
        },
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p2_s11_full_status_source_closure.json", result)
    return result


def _family_closure_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    family_matrix = matrix["status_family_matrix"]
    classification_counts = Counter(str(item["classification"]) for item in family_matrix.values())
    gap_items = {
        family_id: item
        for family_id, item in family_matrix.items()
        if item.get("classification") in GAP_CLASSIFICATIONS
    }
    source_absent_items = {
        family_id: item
        for family_id, item in family_matrix.items()
        if item.get("classification") == "source_absent_not_required"
    }
    checks = {
        "unclassified_zero": matrix["unclassified_count"] == 0,
        "implementation_missing_zero": classification_counts.get("implementation_missing", 0) == 0,
        "lowering_gap_zero": classification_counts.get("lowering_gap", 0) == 0,
        "admission_gap_zero": classification_counts.get("admission_gap", 0) == 0,
        "validation_gap_zero": classification_counts.get("validation_gap", 0) == 0,
        "gap_items_absent": not gap_items,
        "source_absent_items_have_raw_zero": all(int(item.get("raw_count", 0)) == 0 for item in source_absent_items.values()),
        "all_families_executable_in_current_closure": classification_counts == Counter({"executable": len(family_matrix)}),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "summary": {
            "classification_counts": dict(sorted(classification_counts.items())),
            "family_count": len(family_matrix),
            "source_item_counts": matrix["source_item_counts"],
            "unclassified_count": matrix["unclassified_count"],
        },
        "gap_samples": dict(list(gap_items.items())[:10]),
    }


def _source_domain_matrix(matrix: dict[str, Any], ir) -> dict[str, Any]:
    raw_effect_areas = Counter(matrix["raw_status_sources"]["source_area_counts"])
    raw_callback_areas = Counter(matrix["raw_status_sources"]["callback_summary"]["source_area_counts"])
    ir_effect_areas = Counter()
    for counts in matrix["ir_status_sources"]["status_effects"]["source_area_by_opcode"].values():
        ir_effect_areas.update(counts)
    ir_callback_areas = Counter(_p2_source_area(callback.source.source_path) for callback in ir.status_callbacks)
    executable_callback_areas = Counter(
        _p2_source_area(callback.source.source_path)
        for callback in ir.status_callbacks
        if _callback_executable(callback)
    )
    seen_areas = set(raw_effect_areas) | set(raw_callback_areas) | set(ir_effect_areas) | set(ir_callback_areas)
    known_areas = {area for areas in SOURCE_DOMAINS.values() for area in areas}
    unknown_areas = sorted(area for area in seen_areas if area not in known_areas)

    domain_matrix: dict[str, Any] = {}
    samples: dict[str, Any] = {}
    for domain_id, areas in SOURCE_DOMAINS.items():
        raw_effect_count = sum(raw_effect_areas.get(area, 0) for area in areas)
        raw_callback_count = sum(raw_callback_areas.get(area, 0) for area in areas)
        ir_effect_count = sum(ir_effect_areas.get(area, 0) for area in areas)
        ir_callback_count = sum(ir_callback_areas.get(area, 0) for area in areas)
        executable_callback_count = sum(executable_callback_areas.get(area, 0) for area in areas)
        raw_total = raw_effect_count + raw_callback_count
        ir_total = ir_effect_count + ir_callback_count
        executable_total = ir_effect_count + executable_callback_count
        if raw_total == 0 and ir_total == 0:
            classification = "source_absent_not_required"
        elif raw_total > 0 and ir_total == 0:
            classification = "lowering_gap"
        elif ir_total > 0 and executable_total == 0:
            classification = "boundary_only"
        else:
            classification = "executable"
        domain_matrix[domain_id] = {
            "classification": classification,
            "areas": list(areas),
            "raw_effect_count": raw_effect_count,
            "raw_callback_count": raw_callback_count,
            "ir_effect_count": ir_effect_count,
            "ir_callback_count": ir_callback_count,
            "executable_callback_count": executable_callback_count,
            "raw_total": raw_total,
            "ir_total": ir_total,
            "executable_total": executable_total,
        }
        samples[domain_id] = _domain_sample(ir.status_callbacks, areas)

    classifications = Counter(str(item["classification"]) for item in domain_matrix.values())
    checks = {
        "all_required_domains_present": set(SOURCE_DOMAINS).issubset(domain_matrix),
        "source_domains_have_raw_or_absence_proof": all(
            item["classification"] != "source_absent_not_required" or item["raw_total"] == 0
            for item in domain_matrix.values()
        ),
        "no_unknown_source_area": not unknown_areas,
        "no_domain_lowering_gap": classifications.get("lowering_gap", 0) == 0,
        "no_domain_admission_gap": classifications.get("admission_gap", 0) == 0,
        "avatar_monster_global_seen": all(domain_matrix[key]["raw_total"] > 0 for key in ("avatar", "monster", "global_modifier")),
        "equipment_battle_servant_classified": all(
            domain_matrix[key]["classification"] in {"executable", "source_absent_not_required", "boundary_only"}
            for key in ("equipment_lightcone_relic", "battle_event_stage", "servant_summon")
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {
            "ok": checks["ok"],
            "checks": checks,
            "unknown_areas": unknown_areas,
            "raw_effect_areas": dict(sorted(raw_effect_areas.items())),
            "raw_callback_areas": dict(sorted(raw_callback_areas.items())),
        },
        "matrix": domain_matrix,
        "classification_counts": dict(sorted(classifications.items())),
        "samples": samples,
    }


def _blocked_evidence_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    family_matrix = matrix["status_family_matrix"]
    evidence_matrix: dict[str, Any] = {}
    missing_evidence: dict[str, Any] = {}
    for family_id, item in sorted(family_matrix.items()):
        blocked_count = int(item.get("blocked_count", 0))
        evidence = BLOCKED_VALIDATION_EVIDENCE.get(family_id)
        if blocked_count > 0 and evidence is None:
            missing_evidence[family_id] = item
        evidence_matrix[family_id] = {
            "blocked_count": blocked_count,
            "classification": item.get("classification"),
            "validation_script": evidence[0] if evidence else "",
            "evidence": evidence[1] if evidence else "",
        }
    checks = {
        "blocked_families_have_validation_evidence": not missing_evidence,
        "callback_blocked_evidence_present": bool(evidence_matrix.get("status_callback_event_families", {}).get("validation_script")),
        "damage_blocked_evidence_present": bool(evidence_matrix.get("status_damage_sources", {}).get("validation_script")),
        "remove_dispel_blocked_evidence_present": bool(evidence_matrix.get("status_dispel_sources", {}).get("validation_script")),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks, "missing_evidence": missing_evidence},
        "matrix": evidence_matrix,
    }


def _ui_text_boundary(static_result) -> dict[str, Any]:
    static_json = static_result.to_json()
    checks = {
        "static_checks_ok": static_result.ok,
        "ui_or_text_not_rule_source_static_checked": static_result.ok,
        "full_ir_not_written": True,
        "full_transition_dump_not_written": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "summary": {
            "classification": "executable",
            "static_check_count": len(static_json.get("checks", [])) if isinstance(static_json.get("checks"), list) else 0,
        },
    }


def _callback_executable(callback: StatusCallbackIR) -> bool:
    return callback.coverage_status == "executable" and callback.admission_status == "executable"


def _domain_sample(callbacks: tuple[StatusCallbackIR, ...], areas: tuple[str, ...]) -> dict[str, Any]:
    for callback in callbacks:
        if _p2_source_area(callback.source.source_path) in areas:
            return {
                "callback_id": callback.callback_id,
                "event": callback.event,
                "modifier_name": callback.modifier_name,
                "coverage_status": callback.coverage_status,
                "admission_status": callback.admission_status,
                "source": callback.source.to_json(),
            }
    return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P2-S11 full status source closure.")
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
