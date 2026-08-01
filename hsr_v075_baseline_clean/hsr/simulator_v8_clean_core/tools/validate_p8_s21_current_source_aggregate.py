from __future__ import annotations

import argparse
import hashlib
import json
import re
import resource
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from ..builds.character_assembler import assemble_character_build
from ..builds.equipment_assembler import assemble_equipment_build
from ..builds.manifest import BuildLockedReplayVerifier, FormalBuildManifest
from ..builds.models import CharacterBuildInput
from ..equipment.models import (
    EquipmentBuildInput,
    LightConeInstanceInput,
    RelicInstanceInput,
)
from ..immutable_json import thaw_json
from ..queries.equipment import EquipmentQueryService
from ..rules.rulebook import RuleBook
from ..systems.ability_provider import register_dynamic_ability_providers
from ..tbgd.equipment_discovery import (
    build_primary_equipment_source_fingerprint,
    discover_primary_equipment_paths,
)
from ..tbgd.light_cone_cards import (
    build_light_cone_catalog,
    require_complete_light_cone_catalog,
)
from .io import write_json
from .validate_p8_s13_relic_set_thresholds import (
    _assemble as _assemble_relic_case,
    _distinct_templates,
    _find_set,
    _templates_by_set,
)
from .validate_p8_s15_relic_set_dynamic_startup import _build_bundle
from .validate_p8_s7_light_cone_status_condition_listener_closure import _family_inventory
from .validate_p8_s19_query_audit_snapshot_replay import _replay_negatives
from .validate_p8_s20_seele_complete_build_slice import (
    SEELE_CARD_ID,
    _build_formal_scene,
    _counterfactual_matrix,
    _definition_checks,
    _legality_matrix,
    _manifest_is_choice_only,
    _mechanism_matrix,
    _panel_matrix,
    _replay_matrix,
    _source_matrix,
    _static_scan,
)


VALIDATION_VERSION = "p8_s21_current_source_aggregate_v1"
S20_MANIFEST = "p8_s20_seele_complete_equipment_build.json"
STAGE_REPORTS = {
    "P8-S0": "v8_p8_s0_equipment_source_inventory_ready_for_review.md",
    "P8-S1": "v8_p8_s1_equipment_type_contract_ready_for_review.md",
    "P8-S2": "v8_p8_s2_character_build_base_panel_ready_for_review.md",
    "P8-S3": "v8_p8_s3_light_cone_data_cards_ready_for_review.md",
    "P8-S4": "v8_p8_s4_light_cone_instance_assembly_ready_for_review.md",
    "P8-S5": "v8_p8_s5_light_cone_static_contributions_ready_for_review.md",
    "P8-S6": "v8_p8_s6_light_cone_dynamic_startup_ready_for_review.md",
    "P8-S7": "v8_p8_s7_light_cone_status_condition_listener_closure_ready_for_review.md",
    "P8-S8": "v8_p8_s8_remaining_gameplay_ready_for_review.md",
    "P8-S9": "P8-S9_RELIC_DEFINITION_CARDS_ready_for_review.md",
    "P8-S10": "P8-S10_RELIC_INSTANCE_LEGALITY_ready_for_review.md",
    "P8-S11": "P8-S11_RELIC_MAIN_AFFIX_ready_for_review.md",
    "P8-S12": "P8-S12_RELIC_SUB_AFFIX_ROLLS_ready_for_review.md",
    "P8-S13": "P8-S13_RELIC_SET_THRESHOLDS_ready_for_review.md",
    "P8-S14": "P8-S14_RELIC_STATIC_CONTRIBUTIONS_ready_for_review.md",
    "P8-S15": "P8-S15_RELIC_SET_DYNAMIC_STARTUP_ready_for_review.md",
    "P8-S16": "P8-S16_RELIC_SET_STATUS_CONDITION_LISTENER_CLOSURE_ready_for_review.md",
    "P8-S17": "P8-S17_RELIC_SET_REMAINING_GAMEPLAY_CLOSURE_ready_for_review.md",
    "P8-S18": "P8-S18_FINAL_PANEL_AND_BIRTH_ORDER_ready_for_review.md",
    "P8-S19": "P8-S19_QUERY_AUDIT_SNAPSHOT_REPLAY_ready_for_review.md",
    "P8-S20": "P8-S20_SEELE_COMPLETE_BUILD_SLICE_accepted.md",
}
REPAIR_REPORTS = {
    "P8-R1-RUNTIME": "v8_p8_r1_runtime_repair_checkpoint.md",
    "P8-R2": "v8_p8_r2_memory_light_cone_formal_event_chain_ready_for_review.md",
}
ZERO_PREDICATES = {
    "published_light_cone_definition_gap_count",
    "published_relic_template_gap_count",
    "main_affix_gap_count",
    "sub_affix_gap_count",
    "set_threshold_gap_count",
    "light_cone_gameplay_gap_count",
    "relic_set_gameplay_gap_count",
    "unknown_gameplay_count",
}
FALSE_PREDICATES = {
    "aggregate_contains_runtime_fix_logic",
    "large_artifacts_written_by_default",
}


def validate(
    tbgd_root: Path,
    reports_root: Path,
    output_dir: Path,
    *,
    preflight_only: bool = False,
) -> dict[str, Any]:
    started = time.monotonic()
    output_dir.mkdir(parents=True, exist_ok=True)
    package_root = Path(__file__).resolve().parents[1]
    workspace_root = package_root.parent
    preflight = _preflight(
        tbgd_root.resolve(),
        reports_root.resolve(),
        package_root,
        workspace_root,
    )
    if preflight_only:
        return _write_preflight(output_dir, preflight, started)
    if not preflight["ok"]:
        summary = {
            "schema_version": VALIDATION_VERSION,
            "ok": False,
            "ready_for_review": False,
            "blocked_reason": "p8_s21_preflight_failed",
            "preflight": preflight["predicates"],
            "resources": _resource_row(started, 0, 0),
        }
        write_json(output_dir / "validation_summary_p8_s21_current_source_aggregate.json", summary)
        return summary

    production_before = _production_code_fingerprint(package_root)
    light_cone_result = build_light_cone_catalog(tbgd_root.resolve())
    light_cones = require_complete_light_cone_catalog(light_cone_result)
    bundle = _build_bundle(
        tbgd_root.resolve(),
        require_blocked_sample=False,
        inject_duplicate_probe=False,
        required_card_id=SEELE_CARD_ID,
        extra_light_cone_definitions=light_cones,
    )
    rules: RuleBook = bundle["rules"]
    definitions = _definition_aggregate(
        bundle,
        light_cone_result,
        preflight["evidence"]["source_fingerprint"],
    )
    gameplay = _gameplay_aggregate(bundle, definitions)
    sample = _seele_sample(package_root, bundle)
    sources = _six_source_walkbacks(rules, sample)
    negatives = _critical_negatives(rules, bundle, light_cones, sample)
    production_after = _production_code_fingerprint(package_root)

    artifacts = {
        "stage_evidence_manifest_p8_s21.json": preflight["evidence"],
        "definition_gameplay_aggregate_p8_s21.json": {
            "definitions": definitions,
            "gameplay": gameplay,
        },
        "source_negative_sample_p8_s21.json": {
            "source_walkbacks": sources,
            "critical_negatives": negatives,
            "seele_sample": sample["public"],
        },
    }
    for name, value in artifacts.items():
        write_json(output_dir / name, value)
    artifact_bytes = sum((output_dir / name).stat().st_size for name in artifacts)
    checks: dict[str, bool | int] = {
        "stage_evidence_count_matches_s0_through_s20": preflight["predicates"][
            "stage_evidence_count_matches_s0_through_s20"
        ],
        "all_stage_evidence_current": preflight["predicates"][
            "all_stage_evidence_current"
        ],
        "empty_or_fake_checks_rejected": preflight["predicates"][
            "empty_or_fake_checks_rejected"
        ],
        "current_source_inventory_non_empty": preflight["predicates"][
            "current_source_inventory_non_empty"
        ],
        "published_light_cone_definition_gap_count": definitions[
            "published_light_cone_definition_gap_count"
        ],
        "published_relic_template_gap_count": definitions[
            "published_relic_template_gap_count"
        ],
        "main_affix_gap_count": definitions["main_affix_gap_count"],
        "sub_affix_gap_count": definitions["sub_affix_gap_count"],
        "set_threshold_gap_count": definitions["set_threshold_gap_count"],
        "catalog_source_fingerprints_covered_by_primary": definitions[
            "source_fingerprints_covered_by_primary"
        ],
        "definition_aggregate_internal_consistent": definitions["ok"],
        "light_cone_gameplay_gap_count": gameplay[
            "light_cone_gameplay_gap_count"
        ],
        "relic_set_gameplay_gap_count": gameplay[
            "relic_set_gameplay_gap_count"
        ],
        "unknown_gameplay_count": gameplay["unknown_gameplay_count"],
        "gameplay_aggregate_internal_consistent": gameplay["ok"],
        "special_modes_fully_classified": definitions[
            "special_modes_fully_classified"
        ],
        "non_gameplay_rows_have_structured_evidence": gameplay[
            "non_gameplay_rows_have_structured_evidence"
        ],
        "six_source_walkbacks_complete": sources["ok"],
        "critical_negative_regressions_pass": negatives["ok"],
        "seele_slice_passes_as_sample": sample["ok"],
        "aggregate_contains_runtime_fix_logic": production_before != production_after,
        "large_artifacts_written_by_default": artifact_bytes > 20 * 1024 * 1024,
        "documentation_state_consistent": preflight["predicates"][
            "documentation_state_consistent"
        ],
    }
    ok = _predicates_ok(checks)
    summary = {
        "schema_version": VALIDATION_VERSION,
        "ok": ok,
        "ready_for_review": ok,
        "predicates": checks,
        "counts": {
            **definitions["counts"],
            "equipment_family_rows": gameplay["equipment_family_rows"],
            "non_gameplay_rows": gameplay["non_gameplay_row_count"],
            "source_walkback_categories": len(sources["rows"]),
            "critical_negative_cases": len(negatives["rows"]),
        },
        "fingerprints": {
            "source": preflight["evidence"]["source_fingerprint"],
            "production_code": production_after,
        },
        "resources": _resource_row(
            started,
            artifact_bytes,
            len(artifacts),
            light_cone_catalog_builds=1,
            relic_catalog_builds=1,
            focused_rulebooks=1,
            full_lowering_builds=0,
        ),
        "artifacts": list(artifacts),
        "implementation_status": "ready_for_review" if ok else "blocked",
    }
    write_json(output_dir / "validation_summary_p8_s21_current_source_aggregate.json", summary)
    return summary


def _preflight(
    tbgd_root: Path,
    reports_root: Path,
    package_root: Path,
    workspace_root: Path,
) -> dict[str, Any]:
    plan_path = package_root / "P8_EQUIPMENT_BUILD_LIGHT_CONE_RELIC_TASK_PLAN.md"
    plan = plan_path.read_text(encoding="utf-8")
    rows = [
        _evidence_row(stage, reports_root / filename, plan)
        for stage, filename in STAGE_REPORTS.items()
    ]
    repairs = [
        _evidence_row(stage, reports_root / filename, plan)
        for stage, filename in REPAIR_REPORTS.items()
    ]
    source_fingerprint = _current_source_fingerprint(tbgd_root)
    s21_checked = "- [x] P8-S21 " in plan
    done_checked = "- [x] P8-DONE" in plan
    documentation_paths = (
        workspace_root / "CODEX_HANDOFF.md",
        package_root / "DOCUMENTATION_INDEX.md",
        package_root / "docs" / "p8_execution_cards" / "README.md",
        package_root / "docs" / "p8_execution_cards" / "P8-S21_CURRENT_SOURCE_AGGREGATE.md",
    )
    predicates = {
        "stage_evidence_count_matches_s0_through_s20": len(rows) == 21
        and {row["stage"] for row in rows} == set(STAGE_REPORTS),
        "all_stage_evidence_current": all(row["valid"] for row in (*rows, *repairs)),
        "empty_or_fake_checks_rejected": (
            not _report_text_valid("", "P8-S0")
            and not _report_text_valid("ready_for_review ok=true", "P8-S0")
        ),
        "current_source_inventory_non_empty": (
            int(source_fingerprint.get("file_count") or 0) > 9
            and int(source_fingerprint.get("byte_count") or 0) > 0
            and bool(source_fingerprint.get("sha256"))
        ),
        "documentation_state_consistent": (
            all(path.is_file() and path.stat().st_size > 0 for path in documentation_paths)
            and s21_checked == done_checked
        ),
    }
    evidence = {
        "schema_version": "p8_s21_stage_evidence_manifest_v1",
        "stage_reports": rows,
        "repair_reports": repairs,
        "source_fingerprint": source_fingerprint,
        "production_code_fingerprint": _production_code_fingerprint(package_root),
        "documentation_state": {
            "s21_checked": s21_checked,
            "p8_done_checked": done_checked,
            "paths": [str(path.relative_to(workspace_root)) for path in documentation_paths],
        },
    }
    return {"ok": all(predicates.values()), "predicates": predicates, "evidence": evidence}


def _evidence_row(stage: str, path: Path, plan: str) -> dict[str, Any]:
    exists = path.is_file()
    text = path.read_text(encoding="utf-8") if exists else ""
    checklist_key = stage
    accepted = bool(re.search(rf"^- \[x\] {re.escape(checklist_key)}\b", plan, re.MULTILINE))
    return {
        "stage": stage,
        "path": path.name,
        "exists": exists,
        "byte_count": len(text.encode("utf-8")),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if exists else "",
        "accepted_by_master_checklist": accepted,
        "report_contract_valid": _report_text_valid(text, stage),
        "valid": exists and accepted and _report_text_valid(text, stage),
    }


def _report_text_valid(text: str, stage: str) -> bool:
    lowered = text.lower()
    stage_tokens = {stage.lower()}
    if stage == "P8-R1-RUNTIME":
        stage_tokens.add("p8-r1")
    return (
        len(text.encode("utf-8")) >= 256
        and any(token in lowered for token in stage_tokens)
        and (
            "ready_for_review" in lowered
            or "ready for review" in lowered
            or "accepted" in lowered
        )
        and any(token in lowered for token in ("ok=true", "通过", "验收", "pass"))
    )


def _current_source_fingerprint(tbgd_root: Path) -> dict[str, Any]:
    discovery = discover_primary_equipment_paths(tbgd_root)
    paths = {
        *discovery["table_paths"].values(),
        *discovery["ability_paths"],
    }
    loaded = [
        (path.relative_to(tbgd_root).as_posix(), path.read_bytes())
        for path in sorted(paths)
    ]
    return build_primary_equipment_source_fingerprint(loaded)


def _production_code_fingerprint(package_root: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    files = [
        path
        for path in package_root.rglob("*.py")
        if path.relative_to(package_root).parts[0] != "tools"
    ]
    byte_count = 0
    for path in sorted(files):
        relative = path.relative_to(package_root).as_posix()
        raw = path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(raw)
        digest.update(b"\0")
        byte_count += len(raw)
    return {"algorithm": "sha256-path-content-v1", "sha256": digest.hexdigest(), "file_count": len(files), "byte_count": byte_count}


def _definition_aggregate(
    bundle: dict[str, Any],
    light_cone_result: Any,
    primary_source_fingerprint: Mapping[str, Any],
) -> dict[str, Any]:
    rules: RuleBook = bundle["rules"]
    catalog = bundle["catalog"]
    catalog_result = bundle["catalog_result"]
    light_cones = tuple(rules.ir.light_cone_definitions)
    basic_templates = tuple(
        item
        for item in catalog.template_definitions
        if item.publication_status == "published" and item.mode == "BASIC"
    )
    light_cone_definition_gaps = [
        item.definition_key.stable_id
        for item in light_cones
        if rules.light_cone_definition(item.definition_key.definition_identity).resolution_status
        != "resolved"
    ]
    template_gaps = [
        item.definition_key.stable_id
        for item in basic_templates
        if item.coverage_status not in {"lowered", "executable"}
        or rules.relic_template_definition(item.definition_key.definition_identity).resolution_status
        != "resolved"
    ]
    main_gaps = [
        item.definition_key.stable_id
        for item in catalog.main_affix_definitions
        if rules.relic_main_affix_definition(item.definition_key.definition_identity).resolution_status
        != "resolved"
    ]
    sub_gaps = [
        item.definition_key.stable_id
        for item in catalog.sub_affix_definitions
        if rules.relic_sub_affix_definition(item.definition_key.definition_identity).resolution_status
        != "resolved"
    ]
    threshold_gaps = [
        item.definition_key.stable_id
        for item in rules.ir.relic_set_thresholds
        if rules.relic_set_threshold(item.definition_key.definition_identity).resolution_status
        != "resolved"
        or (item.ability_source is None and bool(item.mechanism_ref_ids))
    ]
    special = _special_mode_matrix(rules, catalog)
    light_cone_source = thaw_json(light_cone_result.source_content_fingerprint)
    relic_source = thaw_json(catalog_result.source_content_fingerprint)
    source_coverage = (
        _fingerprint_covered_by_primary(light_cone_source, primary_source_fingerprint)
        and _fingerprint_covered_by_primary(relic_source, primary_source_fingerprint)
    )
    counts = {
        "published_light_cones": len(light_cones),
        "published_basic_relic_templates": len(basic_templates),
        "special_relic_templates": len(special["rows"]),
        "main_affixes": len(catalog.main_affix_definitions),
        "sub_affixes": len(catalog.sub_affix_definitions),
        "relic_sets": len(catalog.set_definitions),
        "set_thresholds": len(catalog.set_thresholds),
    }
    return {
        "ok": (
            light_cone_result.catalog_complete
            and catalog_result.catalog_complete
            and source_coverage
            and not light_cone_definition_gaps
            and not template_gaps
            and not main_gaps
            and not sub_gaps
            and not threshold_gaps
            and special["ok"]
        ),
        "published_light_cone_definition_gap_count": (
            light_cone_result.published_blocked_count
            + len(light_cone_definition_gaps)
            + abs(light_cone_result.published_source_count - len(light_cones))
        ),
        "published_relic_template_gap_count": (
            catalog_result.published_template_blocked_count
            + len(template_gaps)
            + abs(catalog_result.published_template_lowered_count - len(catalog.template_definitions))
        ),
        "main_affix_gap_count": len(main_gaps),
        "sub_affix_gap_count": len(sub_gaps),
        "set_threshold_gap_count": len(threshold_gaps),
        "special_modes_fully_classified": special["ok"],
        "counts": counts,
        "source_fingerprints_covered_by_primary": source_coverage,
        "source_fingerprints": {
            "light_cone": light_cone_source,
            "relic": relic_source,
        },
        "gap_samples": {
            "light_cones": light_cone_definition_gaps[:20],
            "templates": template_gaps[:20],
            "main_affixes": main_gaps[:20],
            "sub_affixes": sub_gaps[:20],
            "thresholds": threshold_gaps[:20],
        },
        "special_modes": special,
    }


def _fingerprint_covered_by_primary(
    domain: object,
    primary: Mapping[str, Any],
) -> bool:
    if not isinstance(domain, Mapping):
        return False
    domain_paths = domain.get("paths")
    primary_paths = primary.get("paths")
    return (
        isinstance(domain.get("sha256"), str)
        and len(domain["sha256"]) == 64
        and isinstance(domain_paths, (list, tuple))
        and bool(domain_paths)
        and len(domain_paths) == len(set(domain_paths))
        and domain.get("file_count") == len(domain_paths)
        and isinstance(domain.get("byte_count"), int)
        and domain["byte_count"] > 0
        and isinstance(primary_paths, (list, tuple))
        and set(domain_paths).issubset(primary_paths)
    )


def _special_mode_matrix(rules: RuleBook, catalog: Any) -> dict[str, Any]:
    groups = {item.definition_key: item for item in catalog.main_affix_group_definitions}
    rows = []
    for template in catalog.template_definitions:
        if template.mode == "BASIC":
            continue
        case = _assemble_relic_case(
            rules,
            (template,),
            groups,
            f"p8-s21-special:{template.definition_key.definition_identity}",
        )
        rejected = (
            case["assembly_status"] == "blocked"
            and any(
                str(reason).startswith("relic_template_mode_not_admitted:")
                for reason in case["diagnostics"]
            )
        )
        rows.append(
            {
                "template": template.definition_key.stable_id,
                "mode": template.mode,
                "raw_mode": template.raw_mode,
                "publication_status": template.publication_status,
                "source_path": template.source.source_path,
                "battle_build_rejected": rejected,
            }
        )
    return {
        "ok": all(
            row["mode"] in {"CUSTOM", "UNKNOWN"}
            and bool(row["raw_mode"])
            and bool(row["source_path"])
            and row["battle_build_rejected"]
            for row in rows
        ),
        "rows": rows,
    }


def _gameplay_aggregate(bundle: dict[str, Any], definitions: dict[str, Any]) -> dict[str, Any]:
    rules: RuleBook = bundle["rules"]
    inventory = _family_inventory({**bundle, "catalog": bundle["catalog_result"]})
    light_cone_graph_gaps = _dynamic_graph_gaps(rules, rules.ir.light_cone_definitions)
    relic_graph_gaps = _dynamic_graph_gaps(
        rules,
        tuple(item for item in rules.ir.relic_set_thresholds if item.ability_source is not None),
    )
    non_gameplay_rows = [
        row for row in inventory["rows"] if row["stage"] == "non_gameplay"
    ]
    unreferenced_rows = [
        row for row in inventory["rows"] if row["stage"] == "unreferenced"
    ]
    non_gameplay_ok = bool(non_gameplay_rows) and all(
        row["structured_evidence"] for row in (*non_gameplay_rows, *unreferenced_rows)
    )
    unknown_count = int(inventory["counts"].get("unknown", 0))
    return {
        "ok": (
            definitions["ok"]
            and inventory["ok"]
            and not unknown_count
            and not light_cone_graph_gaps
            and not relic_graph_gaps
            and non_gameplay_ok
        ),
        "light_cone_gameplay_gap_count": len(light_cone_graph_gaps),
        "relic_set_gameplay_gap_count": len(relic_graph_gaps),
        "unknown_gameplay_count": unknown_count,
        "non_gameplay_rows_have_structured_evidence": non_gameplay_ok,
        "equipment_family_rows": int(inventory["counts"].get("s7", 0))
        + int(inventory["counts"].get("s8", 0)),
        "non_gameplay_row_count": sum(row["raw_count"] for row in non_gameplay_rows),
        "unreferenced_row_count": sum(row["raw_count"] for row in unreferenced_rows),
        "family_counts": dict(inventory["counts"]),
        "graph_gap_samples": {
            "light_cone": light_cone_graph_gaps[:20],
            "relic_set": relic_graph_gaps[:20],
            "unknown": [
                row for row in inventory["rows"] if row["stage"] == "unknown"
            ][:20],
        },
        "non_gameplay_sample": non_gameplay_rows[:20],
        "unreferenced_sample": unreferenced_rows[:20],
    }


def _dynamic_graph_gaps(rules: RuleBook, definitions: tuple[Any, ...]) -> list[dict[str, Any]]:
    gaps = []
    for definition in definitions:
        mechanisms = tuple(
            rules.equipment_mechanism_ref(key.definition_identity)
            for key in definition.mechanism_ref_ids
        )
        graphs = tuple(
            rules.standalone_ability_graph(item.value.graph_ref_id)
            for item in mechanisms
            if item.resolution_status == "resolved" and item.value is not None
        )
        if (
            len(mechanisms) != 1
            or mechanisms[0].resolution_status != "resolved"
            or mechanisms[0].value is None
            or len(graphs) != 1
            or graphs[0] is None
            or graphs[0].coverage_status != "executable"
            or graphs[0].source != mechanisms[0].value.source
        ):
            gaps.append(
                {
                    "definition": definition.definition_key.stable_id,
                    "mechanism_count": len(mechanisms),
                    "resolved_mechanisms": sum(item.resolution_status == "resolved" for item in mechanisms),
                    "graph_statuses": [item.coverage_status if item else "missing" for item in graphs],
                }
            )
    return gaps


def _seele_sample(package_root: Path, bundle: dict[str, Any]) -> dict[str, Any]:
    manifest_path = package_root / "scenarios" / "examples" / S20_MANIFEST
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    build = CharacterBuildInput.from_json(payload)
    rules: RuleBook = bundle["rules"]
    query = EquipmentQueryService(rules)
    assembly = assemble_character_build(rules, build)
    submission = query.submit_character_build(payload)
    built = _build_formal_scene(rules, bundle["card"], build, "s21-final")
    legality = _legality_matrix(rules, build, assembly)
    panel = _panel_matrix(assembly)
    mechanisms = _mechanism_matrix(rules, assembly, built)
    counterfactuals = _counterfactual_matrix(
        rules, bundle["card"], build, assembly, built, mechanisms
    )
    sources = _source_matrix(query, assembly, built, mechanisms)
    replay = _replay_matrix(rules, built, mechanisms, counterfactuals)
    static_scan = _static_scan(manifest_path)
    checks = {
        "manifest_choice_only": _manifest_is_choice_only(payload),
        "definitions_resolved": all(_definition_checks(query, build).values()),
        "six_relics_legal": legality["six_relic_instances_legal"],
        "final_sub_affixes_legal": legality["all_final_sub_affix_values_legal"],
        "panel_reconstructs": panel["reconstructs"],
        "target_panel_met": panel["crit_rate_target"] and panel["crit_damage_target"] and panel["attack_target"],
        "sets_and_providers_active": mechanisms["sets_active"] and mechanisms["formal_boundary_ok"],
        "runtime_conditions": mechanisms["speed_tiers_ok"] and mechanisms["weakness_branch_ok"],
        "counterfactuals_isolated": counterfactuals["all_isolated"],
        "sources_walk_back": sources["ok"],
        "replay_equal": replay["ok"],
        "production_fixed_ids_absent": not static_scan["production_hits"],
        "production_manifest_reference_absent": not static_scan["manifest_references"],
        "formal_submission_admitted": submission.resolution_status == "resolved"
        and assembly.assembly_status == "assembled"
        and assembly.battle_admission_status == "admitted",
    }
    return {
        "ok": all(checks.values()),
        "public": {
            "sample_only": True,
            "checks": checks,
            "panel": panel.get("panel", {}),
            "dynamic_targets": mechanisms["dynamic_targets"],
            "static_thresholds": mechanisms["static_thresholds"],
            "source_summary": sources,
            "replay": replay,
        },
        "_build": build,
        "_assembly": assembly,
        "_built": built,
        "_mechanisms": mechanisms,
    }


def _six_source_walkbacks(rules: RuleBook, sample: dict[str, Any]) -> dict[str, Any]:
    assembly = sample["_assembly"]
    built = sample["_built"]
    equipment = assembly.equipment_assembly_result
    registration = built.ability_provider_registration
    if equipment is None or registration is None:
        return {"ok": False, "rows": [], "reason": "sample_equipment_or_registration_missing"}
    query = EquipmentQueryService(rules)
    rows: dict[str, dict[str, Any]] = {}
    static_categories = {
        "light_cone": "light_cone_static",
        "relic_main_affix": "main_affix",
        "relic_sub_affix": "sub_affix",
        "relic_set_threshold": "relic_set_static",
    }
    for contribution in equipment.static_contributions:
        category = static_categories.get(contribution.source_ref.definition_kind)
        if category is None or category in rows:
            continue
        view = query.get_static_contribution_source(assembly, contribution.contribution_id)
        rows[category] = {
            "resolution_status": view.resolution_status,
            "identity": contribution.contribution_id,
            "term_source": view.term_source.get("source_path") if isinstance(view.term_source, Mapping) else "",
            "definition_source": view.definition_source.get("source_path") if isinstance(view.definition_source, Mapping) else "",
        }
    provider_mutations = tuple(
        item for item in registration.mutations if item.source == "ability_provider_registry"
    )
    if len(provider_mutations) == 1:
        mutation = provider_mutations[0]
        providers = mutation.metadata.get("providers", ())
        transition = registration.to_transition()
        for provider in providers if isinstance(providers, (list, tuple)) else ():
            if not isinstance(provider, Mapping):
                continue
            target = provider.get("target_definition_key")
            kind = target.get("definition_kind") if isinstance(target, Mapping) else ""
            category = "light_cone_dynamic" if kind == "light_cone" else "relic_set_dynamic" if kind == "relic_set_threshold" else ""
            if not category or category in rows:
                continue
            view = query.get_dynamic_mutation_source(
                assembly,
                transition,
                mutation.stable_id(),
                provider_id=str(provider.get("provider_id") or ""),
            )
            encoded = view.to_json()
            rows[category] = {
                "resolution_status": view.resolution_status,
                "identity": str(provider.get("provider_id") or ""),
                "mechanism_source": encoded.get("mechanism_source", {}).get("source_path", ""),
                "target_source": encoded.get("target_source", {}).get("source_path", ""),
            }
    expected = {
        "light_cone_static",
        "light_cone_dynamic",
        "main_affix",
        "sub_affix",
        "relic_set_static",
        "relic_set_dynamic",
    }
    return {
        "ok": set(rows) == expected and all(row["resolution_status"] == "resolved" for row in rows.values()),
        "rows": [{"category": key, **rows[key]} for key in sorted(rows)],
    }


def _critical_negatives(
    rules: RuleBook,
    bundle: dict[str, Any],
    light_cones: tuple[Any, ...],
    sample: dict[str, Any],
) -> dict[str, Any]:
    build: CharacterBuildInput = sample["_build"]
    assembly = sample["_assembly"]
    built = sample["_built"]
    equipment = assembly.equipment_assembly_result
    if equipment is None:
        return {"ok": False, "rows": {"sample": {"ok": False}}}
    rows: dict[str, dict[str, Any]] = {}

    current_lc = rules.light_cone_definition(
        build.equipment_build.light_cone.definition_key.definition_identity
    ).value
    alternate = next(item for item in light_cones if current_lc is not None and item.path_type != current_lc.path_type)
    mismatch_instance = LightConeInstanceInput(
        instance_id="p8-s21:path-mismatch",
        definition_key=alternate.definition_key,
        level=1,
        promotion=0,
        superimposition=1,
    )
    mismatch_build = _replace_equipment_build(build, light_cone=mismatch_instance, tag="path-mismatch")
    mismatch = assemble_character_build(rules, mismatch_build)
    mismatch_equipment = mismatch.equipment_assembly_result
    activation = mismatch_equipment.activation_decisions[0] if mismatch_equipment and mismatch_equipment.activation_decisions else None
    rows["path_mismatch"] = {
        "ok": mismatch.assembly_status == "assembled"
        and mismatch.battle_admission_status == "admitted"
        and activation is not None
        and activation.activation_status == "inactive"
        and activation.reason_code == "light_cone_path_mismatch"
        and all(item.target_definition_key != alternate.definition_key for item in mismatch_equipment.dynamic_mechanisms),
        "activation_status": activation.activation_status if activation else "missing",
        "reason": activation.reason_code if activation else "missing",
    }

    original_static = {item.source_ref.definition_identity for item in equipment.static_contributions if item.source_ref.definition_kind == "relic_set_threshold"}
    original_dynamic = {item.target_definition_key.definition_identity for item in equipment.dynamic_mechanisms if item.target_definition_key.definition_kind == "relic_set_threshold"}
    rows["four_plus_two"] = {
        "ok": {"108:2", "309:2"}.issubset(original_static)
        and {"108:4", "309:2"}.issubset(original_dynamic),
        "static_thresholds": sorted(original_static),
        "dynamic_thresholds": sorted(original_dynamic),
    }

    catalog = bundle["catalog"]
    templates = tuple(item for item in catalog.template_definitions if item.publication_status == "published" and item.mode == "BASIC")
    sets = {item.definition_key: item for item in catalog.set_definitions}
    groups = {item.definition_key: item for item in catalog.main_affix_group_definitions}
    outer = _templates_by_set(templates, sets, "outer")
    set_a, templates_a = _find_set(outer, 2)
    set_b, templates_b = _find_set(outer, 2, excluded={set_a})
    two_plus_two = _assemble_relic_case(
        rules,
        (*templates_a[:2], *_distinct_templates(templates_b, templates_a[:2], 2)),
        groups,
        "p8-s21-two-plus-two",
    )
    active = [
        (item["set_key"]["stable_id"], item["required_count"])
        for item in two_plus_two["decisions"]
        if item["activation_status"] == "active"
    ]
    rows["two_plus_two"] = {
        "ok": two_plus_two["assembly_status"] == "assembled"
        and {(key, count) for key, count in active}
        == {(set_a.stable_id, 2), (set_b.stable_id, 2)},
        "active_thresholds": active,
    }

    first = build.equipment_build.relics[0]
    forged_rolls = (
        replace(first.sub_affix_rolls[0], affix_key=first.sub_affix_rolls[1].affix_key),
        *first.sub_affix_rolls[1:],
    )
    forged_relic = replace(first, sub_affix_rolls=forged_rolls)
    illegal_build = _replace_equipment_build(
        build,
        relics=(forged_relic, *build.equipment_build.relics[1:]),
        tag="illegal-affix",
    )
    illegal = assemble_character_build(rules, illegal_build)
    rows["illegal_affix"] = {
        "ok": illegal.assembly_status == "blocked"
        and illegal.base_panel is None
        and not illegal.contribution_ledger
        and not illegal.admitted_dynamic_mechanism_refs,
        "blocked_reasons": list(illegal.blocked_reasons),
    }

    selection = equipment.dynamic_mechanisms[0]
    missing_graph = selection.graph_ref_id + ":p8-s21-missing"
    partial_selection = replace(
        selection,
        graph_ref_id=missing_graph,
        parameter_bindings=tuple(replace(item, graph_ref_id=missing_graph) for item in selection.parameter_bindings),
    )
    partial = register_dynamic_ability_providers(
        built.state,
        rules,
        (("ally:seele", partial_selection),),
    )
    rows["partial_graph"] = {
        "ok": not partial.ok
        and partial.state_unchanged
        and partial.blocked_reason == "ability_provider_graph_missing_partial_or_wrong_source"
        and not partial.mutations,
        "blocked_reason": partial.blocked_reason,
    }

    manifest = FormalBuildManifest.from_state(built.state)
    stale_rows = _replay_negatives(BuildLockedReplayVerifier(rules), built.state, manifest)
    rows["stale_replay"] = {
        "ok": bool(stale_rows)
        and all(item["blocked"] and item["state_unchanged"] for item in stale_rows.values()),
        "case_count": len(stale_rows),
        "cases": stale_rows,
    }
    return {"ok": all(row["ok"] for row in rows.values()), "rows": rows}


def _replace_equipment_build(
    build: CharacterBuildInput,
    *,
    light_cone: LightConeInstanceInput | None = None,
    relics: tuple[RelicInstanceInput, ...] | None = None,
    tag: str,
) -> CharacterBuildInput:
    equipment = EquipmentBuildInput(
        build_id=f"{build.equipment_build.build_id}:{tag}",
        character_card_id=build.character_card_id,
        light_cone=light_cone if light_cone is not None else build.equipment_build.light_cone,
        relics=relics if relics is not None else build.equipment_build.relics,
        identity_labels=dict(build.equipment_build.identity_labels),
    )
    return replace(build, build_id=f"{build.build_id}:{tag}", equipment_build=equipment)


def _write_preflight(output_dir: Path, preflight: dict[str, Any], started: float) -> dict[str, Any]:
    evidence_name = "stage_evidence_manifest_p8_s21.json"
    write_json(output_dir / evidence_name, preflight["evidence"])
    summary = {
        "schema_version": VALIDATION_VERSION,
        "ok": preflight["ok"],
        "preflight_only": True,
        "predicates": preflight["predicates"],
        "resources": _resource_row(
            started,
            (output_dir / evidence_name).stat().st_size,
            1,
            light_cone_catalog_builds=0,
            relic_catalog_builds=0,
            focused_rulebooks=0,
            full_lowering_builds=0,
        ),
    }
    write_json(output_dir / "validation_summary_p8_s21_preflight.json", summary)
    return summary


def _predicates_ok(checks: Mapping[str, bool | int]) -> bool:
    return all(
        value == 0
        if key in ZERO_PREDICATES
        else value is False
        if key in FALSE_PREDICATES
        else value is True
        for key, value in checks.items()
    )


def _resource_row(
    started: float,
    artifact_bytes: int,
    artifact_count: int,
    **build_counts: int,
) -> dict[str, Any]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "wall_seconds": round(time.monotonic() - started, 6),
        "peak_rss_kib": usage.ru_maxrss,
        "input_blocks": usage.ru_inblock,
        "output_blocks": usage.ru_oublock,
        "artifact_count_before_summary": artifact_count,
        "artifact_bytes_before_summary": artifact_bytes,
        **build_counts,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the current-source P8 equipment aggregate")
    parser.add_argument("--tbgd-root", type=Path, required=True)
    parser.add_argument("--reports-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summary = validate(
        args.tbgd_root,
        args.reports_root,
        args.output_dir,
        preflight_only=args.preflight_only,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
