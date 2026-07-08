from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, JSONValue, UnitState
from ..rules.rulebook import RuleBook
from ..systems.summon import SummonSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "p3_s4_summon_unit_admission"
MATRIX_SCHEMA_VERSION = "p3_summon_unit_admission_matrix_s4"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    raw_matrix = _raw_summon_unit_matrix(tbgd_root)
    reference_matrix = _summon_unit_reference_matrix(tbgd_root, raw_matrix["summon_unit_ids"])
    admission_matrix = build_p3_s4_admission_matrix(rules, raw_matrix, reference_matrix)
    admission_checks = validate_p3_s4_admission_matrix(admission_matrix)
    checks = {
        "summon_unit_admission": admission_checks,
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "p3_s4_summon_unit_source_classification_and_boundary_validation",
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "textmap_read": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
            },
        },
        "checks": checks,
        "summary": admission_matrix["summary"],
        "case_groups": admission_matrix["case_groups"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p3_s4_summon_unit_admission.json", result)
    write_json(output_dir / "p3_summon_unit_admission_matrix_s4.json", admission_matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P3-S4 SummonUnitData admission and runtime boundary.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def build_p3_s4_admission_matrix(
    rules: RuleBook,
    raw_matrix: dict[str, Any],
    reference_matrix: dict[str, Any],
) -> dict[str, Any]:
    definitions = tuple(rules.summon_unit_definitions())
    case_groups = {
        "raw_ir_classification": _raw_ir_classification_case(definitions, raw_matrix),
        "reference_trigger_scan": _reference_trigger_scan_case(definitions, reference_matrix),
        "battle_runtime_source_boundary": _battle_runtime_source_boundary_case(definitions, reference_matrix),
        "required_runtime_sources": _required_runtime_sources_case(definitions),
        "runtime_blocked_boundary": _runtime_blocked_boundary_case(rules, definitions),
    }
    failed = {
        group_id: [key for key, value in group["checks"]["checks"].items() if value is False]
        for group_id, group in case_groups.items()
        if not group["checks"]["ok"]
    }
    kind_counts = Counter(definition.summon_kind for definition in definitions)
    reason_counts = Counter(definition.blocked_reason for definition in definitions)
    source_mode_counts = Counter(str(definition.battle_admission.get("source_mode") or "") for definition in definitions)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "coverage_scope": {
            "runtime_behavior_changed": False,
            "raw_read_only_validation": True,
            "runtime_reads_raw_tbgd": False,
            "textmap_read": False,
            "full_ir_written": False,
            "full_transition_dump_written": False,
        },
        "case_groups": case_groups,
        "summary": {
            "raw_count": raw_matrix["raw_count"],
            "definition_count": len(definitions),
            "summon_kind_counts": dict(sorted(kind_counts.items())),
            "source_mode_counts": dict(sorted(source_mode_counts.items())),
            "blocked_reason_counts": dict(sorted(reason_counts.items())),
            "battle_runtime_trigger_ref_count": reference_matrix["summary"]["battle_runtime_trigger_ref_count"],
            "adventure_trigger_ref_count": reference_matrix["summary"]["adventure_trigger_ref_count"],
            "non_battle_ref_count": reference_matrix["summary"]["non_battle_ref_count"],
            "failed_group_count": len(failed),
            "failed_checks": failed,
        },
    }


def validate_p3_s4_admission_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    groups = matrix["case_groups"]
    checks = {
        "raw_ir_classification_ok": groups["raw_ir_classification"]["checks"]["ok"],
        "reference_trigger_scan_ok": groups["reference_trigger_scan"]["checks"]["ok"],
        "battle_runtime_source_boundary_ok": groups["battle_runtime_source_boundary"]["checks"]["ok"],
        "required_runtime_sources_ok": groups["required_runtime_sources"]["checks"]["ok"],
        "runtime_blocked_boundary_ok": groups["runtime_blocked_boundary"]["checks"]["ok"],
        "matrix_is_lightweight": (
            matrix["coverage_scope"]["full_ir_written"] is False
            and matrix["coverage_scope"]["full_transition_dump_written"] is False
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"ok": checks["ok"], "checks": checks}


def _raw_ir_classification_case(definitions: tuple[Any, ...], raw_matrix: dict[str, Any]) -> dict[str, Any]:
    source_modes = Counter(str(definition.battle_admission.get("source_mode") or "") for definition in definitions)
    checks = {
        "raw_count_matches_ir": raw_matrix["raw_count"] == len(definitions),
        "all_definitions_blocked": all(definition.coverage_status == "blocked" for definition in definitions),
        "no_unknown_summon_kind": all(definition.summon_kind not in {"", "unknown"} for definition in definitions),
        "no_unclassified_source_mode": all(definition.battle_admission.get("source_mode") for definition in definitions),
        "source_modes_are_boundary_modes": set(source_modes).issubset(
            {"client_or_visual", "destroy_on_enter_battle", "adventure_or_maze", "catalog_or_scene", "config_missing"}
        ),
        "raw_flags_projected": all(_raw_flags_projected(definition) for definition in definitions),
        "config_markers_projected": all(isinstance(definition.battle_admission.get("config_markers"), dict) for definition in definitions),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "boundary_only",
        "raw_summary": {
            "raw_count": raw_matrix["raw_count"],
            "raw_flag_counts": raw_matrix["raw_flag_counts"],
            "raw_group_config_counts": raw_matrix["raw_group_config_counts"],
            "samples": raw_matrix["samples"],
        },
        "source_mode_counts": dict(sorted(source_modes.items())),
    }


def _reference_trigger_scan_case(definitions: tuple[Any, ...], reference_matrix: dict[str, Any]) -> dict[str, Any]:
    ref_summary = reference_matrix["summary"]
    checks = {
        "reference_scan_covers_all_definitions": set(reference_matrix["by_id"]) == {definition.summon_unit_id for definition in definitions},
        "battle_runtime_refs_absent": ref_summary["battle_runtime_trigger_ref_count"] == 0,
        "adventure_or_non_battle_refs_recorded": ref_summary["adventure_trigger_ref_count"] > 0 or ref_summary["non_battle_ref_count"] > 0,
        "samples_are_lightweight": len(reference_matrix["samples"]) <= 12,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "source_absent_not_required",
        "reference_summary": ref_summary,
        "samples": reference_matrix["samples"],
    }


def _battle_runtime_source_boundary_case(definitions: tuple[Any, ...], reference_matrix: dict[str, Any]) -> dict[str, Any]:
    battle_candidates = tuple(
        definition
        for definition in definitions
        if definition.battle_admission.get("source_mode") == "battle_runtime_candidate"
    )
    adventure_or_maze = tuple(
        definition
        for definition in definitions
        if definition.battle_admission.get("source_mode") == "adventure_or_maze"
    )
    checks = {
        "current_database_has_no_battle_runtime_candidate": not battle_candidates,
        "current_database_has_no_battle_runtime_trigger_ref": reference_matrix["summary"]["battle_runtime_trigger_ref_count"] == 0,
        "adventure_or_maze_definitions_are_boundary": bool(adventure_or_maze)
        and all(definition.blocked_reason == "summon_unit_adventure_or_maze_not_combat_runtime" for definition in adventure_or_maze),
        "catalog_not_trigger_for_all": all(definition.battle_admission.get("catalog_not_trigger") is True for definition in definitions),
        "runtime_spawn_requires_explicit_intent_for_all": all(
            definition.battle_admission.get("runtime_spawn_requires_explicit_intent") is True for definition in definitions
        ),
        "no_definition_marked_executable": all(definition.coverage_status != "executable" for definition in definitions),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "source_absent_not_required",
        "battle_candidate_count": len(battle_candidates),
        "adventure_or_maze_count": len(adventure_or_maze),
        "adventure_or_maze_ids": [definition.summon_unit_id for definition in adventure_or_maze],
    }


def _required_runtime_sources_case(definitions: tuple[Any, ...]) -> dict[str, Any]:
    required_keys = {
        "battle_trigger",
        "unit_profile",
        "stats",
        "position",
        "lifetime",
        "targetability",
        "actionability",
    }
    missing: Counter[str] = Counter()
    executable_required: Counter[str] = Counter()
    for definition in definitions:
        sources = definition.battle_admission.get("required_runtime_sources")
        if not isinstance(sources, dict):
            missing["required_runtime_sources"] += 1
            continue
        for key in required_keys:
            item = sources.get(key)
            if not isinstance(item, dict):
                missing[key] += 1
            elif item.get("admission_status") == "executable":
                executable_required[key] += 1
    checks = {
        "required_runtime_sources_present": not missing,
        "no_runtime_source_executable_without_trigger": not executable_required,
        "all_definitions_blocked_before_runtime": all(definition.battle_admission.get("admission_status") == "blocked" for definition in definitions),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "boundary_only",
        "missing_required_sources": dict(sorted(missing.items())),
        "executable_required_sources": dict(sorted(executable_required.items())),
    }


def _runtime_blocked_boundary_case(rules: RuleBook, definitions: tuple[Any, ...]) -> dict[str, Any]:
    system = SummonSystem(rules)
    state = _base_state()
    before = _snapshot_hash(state)
    samples: dict[str, Any] = {}
    for source_mode in sorted({str(definition.battle_admission.get("source_mode") or "") for definition in definitions}):
        definition = next(item for item in definitions if item.battle_admission.get("source_mode") == source_mode)
        result = system.blocked(
            definition.blocked_reason,
            owner_id="ally:probe",
            source_trace=definition.source.to_json(),
        )
        samples[source_mode] = {
            "definition_id": definition.summon_definition_id,
            "result_plan": result.plan.to_json(),
            "mutation_count": len(result.mutations),
            "process_only_record": bool(result.records) and result.records[0].get("process_only") is True,
        }
    after = _snapshot_hash(state)
    checks = {
        "state_unchanged": before == after,
        "all_boundary_results_process_only": all(item["process_only_record"] is True for item in samples.values()),
        "no_boundary_mutations": all(item["mutation_count"] == 0 for item in samples.values()),
        "samples_cover_source_modes": set(samples) == {str(definition.battle_admission.get("source_mode") or "") for definition in definitions},
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "boundary_only",
        "samples": samples,
    }


def _raw_summon_unit_matrix(tbgd_root: Path) -> dict[str, Any]:
    path = tbgd_root / "ExcelOutput/SummonUnitData.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    summon_unit_ids: list[str] = []
    flag_counts: Counter[str] = Counter()
    group_counts: Counter[str] = Counter()
    samples: list[dict[str, JSONValue]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or row.get("ID") is None:
            continue
        summon_unit_id = str(row.get("ID"))
        summon_unit_ids.append(summon_unit_id)
        config_path = str(row.get("JsonPath") or "")
        config = _read_json(tbgd_root / config_path) if config_path else None
        group = str(config.get("GroupConfigName") or "") if isinstance(config, dict) else ""
        group_counts[group or "missing"] += 1
        for key in ("IsClient", "IsTeamSummon", "DestroyOnEnterBattle", "RemoveMazeBuffOnDestroy"):
            if row.get(key) is True:
                flag_counts[key] += 1
        if len(samples) < 8:
            samples.append(
                {
                    "row_index": index,
                    "summon_unit_id": summon_unit_id,
                    "json_path": config_path,
                    "is_client": row.get("IsClient") is True,
                    "is_team_summon": row.get("IsTeamSummon") is True,
                    "destroy_on_enter_battle": row.get("DestroyOnEnterBattle") is True,
                    "group_config_name": group,
                    "config_exists": isinstance(config, dict),
                }
            )
    return {
        "raw_count": len(summon_unit_ids),
        "summon_unit_ids": tuple(summon_unit_ids),
        "raw_flag_counts": dict(sorted(flag_counts.items())),
        "raw_group_config_counts": dict(sorted(group_counts.items())),
        "samples": samples,
    }


def _summon_unit_reference_matrix(tbgd_root: Path, summon_unit_ids: tuple[str, ...]) -> dict[str, Any]:
    id_set = set(summon_unit_ids)
    by_id = {summon_unit_id: {"battle_runtime": [], "adventure": [], "non_battle": []} for summon_unit_id in summon_unit_ids}
    samples: list[dict[str, JSONValue]] = []
    for path in sorted(tbgd_root.rglob("*.json")):
        rel = path.relative_to(tbgd_root).as_posix()
        if rel == "ExcelOutput/SummonUnitData.json" or rel.startswith("Config/ConfigSummonUnit/"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        matched = tuple(summon_unit_id for summon_unit_id in summon_unit_ids if summon_unit_id in text)
        if not matched:
            continue
        try:
            data = json.loads(text)
        except Exception:
            continue
        for record in _walk_matching_refs(data, rel, id_set):
            category = _reference_category(record)
            record = {**record, "category": category}
            by_id[record["summon_unit_id"]][category].append(record)
            if len(samples) < 12:
                samples.append({key: record[key] for key in ("summon_unit_id", "source_path", "json_path", "key", "category")})
    battle_count = sum(len(item["battle_runtime"]) for item in by_id.values())
    adventure_count = sum(len(item["adventure"]) for item in by_id.values())
    non_battle_count = sum(len(item["non_battle"]) for item in by_id.values())
    return {
        "by_id": {
            summon_unit_id: {
                key: {"count": len(value), "samples": value[:5]}
                for key, value in refs.items()
            }
            for summon_unit_id, refs in by_id.items()
        },
        "summary": {
            "battle_runtime_trigger_ref_count": battle_count,
            "adventure_trigger_ref_count": adventure_count,
            "non_battle_ref_count": non_battle_count,
        },
        "samples": samples,
    }


def _walk_matching_refs(value: Any, source_path: str, id_set: set[str], path: tuple[str, ...] = ()) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_id = _summon_id_value(child, id_set)
            if child_id is not None:
                records.append(
                    {
                        "summon_unit_id": child_id,
                        "source_path": source_path,
                        "json_path": "/".join((*path, str(key))),
                        "key": str(key),
                        "value": child,
                    }
                )
            records.extend(_walk_matching_refs(child, source_path, id_set, (*path, str(key))))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_id = _summon_id_value(child, id_set)
            if child_id is not None:
                records.append(
                    {
                        "summon_unit_id": child_id,
                        "source_path": source_path,
                        "json_path": "/".join((*path, str(index))),
                        "key": str(index),
                        "value": child,
                    }
                )
            records.extend(_walk_matching_refs(child, source_path, id_set, (*path, str(index))))
    return tuple(records)


def _reference_category(record: dict[str, Any]) -> str:
    source_path = str(record["source_path"])
    key = str(record["key"])
    json_path = str(record["json_path"])
    if (
        (source_path.startswith("Config/ConfigAbility/") or source_path.startswith("Config/ConfigGlobalModifier/"))
        and not source_path.endswith(".layout.json")
        and ("SummonUnit" in key or "SummonUnit" in json_path)
    ):
        return "battle_runtime"
    if source_path.startswith("Config/ConfigAdventureAbility/") and ("SummonUnit" in key or "SummonUnit" in json_path):
        return "adventure"
    return "non_battle"


def _summon_id_value(value: Any, id_set: set[str]) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and str(value) in id_set:
        return str(value)
    if isinstance(value, str) and value in id_set:
        return value
    return None


def _raw_flags_projected(definition: Any) -> bool:
    flags = definition.battle_admission.get("raw_flags")
    return (
        isinstance(flags, dict)
        and "is_client" in flags
        and "is_team_summon" in flags
        and "destroy_on_enter_battle" in flags
        and "remove_maze_buff_on_destroy" in flags
        and "max_summon_count" in flags
        and "unique_group" in flags
    )


def _base_state() -> BattleState:
    return BattleState(
        units={
            "ally:probe": UnitState(
                "ally:probe",
                "ally",
                "avatar:probe",
                hp=100.0,
                max_hp=100.0,
                flags={"position": 1},
            )
        }
    )


def _snapshot_hash(state: BattleState) -> str:
    return json.dumps(state.snapshot().to_json(), sort_keys=True, ensure_ascii=False)


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
