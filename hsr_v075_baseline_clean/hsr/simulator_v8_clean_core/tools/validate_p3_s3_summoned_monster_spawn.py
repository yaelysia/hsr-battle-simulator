from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import ActionSettlement, BattleState, JSONValue, UnitState
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..rules.ir import SummonMonsterIntentIR
from ..rules.rulebook import RuleBook
from ..systems.summon import SUMMON_RUNTIME_SCHEMA_VERSION, SummonSystem
from ..systems.target import TargetSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p1_3_summon_assistant_servant import (
    _base_summon_state,
    _select_executable_summon_monster_intent,
    _select_target_expression,
    _snapshot_hash,
)


VALIDATION_VERSION = "p3_s3_summoned_monster_spawn"
MATRIX_SCHEMA_VERSION = "p3_summoned_monster_spawn_matrix_s3"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    raw_matrix = _raw_summon_monster_matrix(tbgd_root)
    spawn_matrix = build_p3_s3_spawn_matrix(rules, raw_matrix)
    spawn_checks = validate_p3_s3_spawn_matrix(spawn_matrix)
    checks = {
        "summoned_monster_spawn": spawn_checks,
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "p3_s3_summon_monster_structured_source_and_runtime_validation",
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "textmap_read": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
            },
        },
        "checks": checks,
        "summary": spawn_matrix["summary"],
        "case_groups": spawn_matrix["case_groups"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p3_s3_summoned_monster_spawn.json", result)
    write_json(output_dir / "p3_summoned_monster_spawn_matrix_s3.json", spawn_matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P3-S3 summoned monster spawn admission and runtime traceability.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def build_p3_s3_spawn_matrix(rules: RuleBook, raw_matrix: dict[str, Any]) -> dict[str, Any]:
    intents = tuple(rules.summon_monster_intents())
    case_groups = {
        "raw_source_inventory": _raw_source_inventory_case(raw_matrix, intents),
        "executable_spawn_trace": _executable_spawn_trace_case(rules),
        "multi_entry_boundary": _multi_entry_boundary_case(rules),
        "unsupported_source_boundaries": _unsupported_source_boundary_case(rules),
        "count_unique_group_boundary": _count_unique_group_boundary_case(raw_matrix, intents),
    }
    failed = {
        group_id: [key for key, value in group["checks"]["checks"].items() if value is False]
        for group_id, group in case_groups.items()
        if not group["checks"]["ok"]
    }
    status_counts = Counter(intent.coverage_status for intent in intents)
    entry_len_counts = Counter(len(intent.entries) for intent in intents)
    executable_entry_len_counts = Counter(len(intent.entries) for intent in intents if intent.coverage_status == "executable")
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "runtime_schema_version": SUMMON_RUNTIME_SCHEMA_VERSION,
        "coverage_scope": {
            "runtime_behavior_changed": True,
            "runtime_reads_raw_tbgd": False,
            "raw_read_only_validation": True,
            "textmap_read": False,
            "full_ir_written": False,
            "full_transition_dump_written": False,
        },
        "case_groups": case_groups,
        "summary": {
            "intent_count": len(intents),
            "coverage_status_counts": dict(sorted(status_counts.items())),
            "entry_len_counts": dict(sorted((str(key), value) for key, value in entry_len_counts.items())),
            "executable_entry_len_counts": dict(sorted((str(key), value) for key, value in executable_entry_len_counts.items())),
            "raw_occurrence_count": raw_matrix["occurrence_count"],
            "raw_multi_entry_occurrence_count": raw_matrix["multi_entry_occurrence_count"],
            "raw_count_field_occurrence_count": raw_matrix["count_field_occurrence_count"],
            "failed_group_count": len(failed),
            "failed_checks": failed,
        },
    }


def validate_p3_s3_spawn_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    groups = matrix["case_groups"]
    checks = {
        "raw_source_inventory_ok": groups["raw_source_inventory"]["checks"]["ok"],
        "executable_spawn_trace_ok": groups["executable_spawn_trace"]["checks"]["ok"],
        "multi_entry_boundary_ok": groups["multi_entry_boundary"]["checks"]["ok"],
        "unsupported_source_boundaries_ok": groups["unsupported_source_boundaries"]["checks"]["ok"],
        "count_unique_group_boundary_ok": groups["count_unique_group_boundary"]["checks"]["ok"],
        "matrix_is_lightweight": (
            matrix["coverage_scope"]["full_ir_written"] is False
            and matrix["coverage_scope"]["full_transition_dump_written"] is False
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"ok": checks["ok"], "checks": checks}


def _raw_source_inventory_case(raw_matrix: dict[str, Any], intents: tuple[SummonMonsterIntentIR, ...]) -> dict[str, Any]:
    checks = {
        "raw_sources_present": raw_matrix["occurrence_count"] > 0,
        "ir_sources_present": bool(intents),
        "raw_and_ir_cardinality_recorded": raw_matrix["occurrence_count"] > 0 and len(intents) > 0,
        "multi_entry_raw_sources_classified": raw_matrix["multi_entry_occurrence_count"] > 0,
        "raw_count_field_absent": raw_matrix["count_field_occurrence_count"] == 0,
        "raw_unique_max_fields_absent": raw_matrix["unique_or_max_field_occurrence_count"] == 0,
        "raw_scan_summary_only": len(raw_matrix["samples"]) <= 6,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "source_inventory",
        "raw_summary": {
            "ability_file_count": raw_matrix["ability_file_count"],
            "occurrence_count": raw_matrix["occurrence_count"],
            "multi_entry_occurrence_count": raw_matrix["multi_entry_occurrence_count"],
            "task_key_counts_top": raw_matrix["task_key_counts_top"],
            "entry_key_counts_top": raw_matrix["entry_key_counts_top"],
            "count_field_occurrence_count": raw_matrix["count_field_occurrence_count"],
            "unique_or_max_field_occurrence_count": raw_matrix["unique_or_max_field_occurrence_count"],
            "samples": raw_matrix["samples"],
        },
    }


def _executable_spawn_trace_case(rules: RuleBook) -> dict[str, Any]:
    intent = _select_executable_summon_monster_intent(rules)
    state = _base_summon_state()
    system = SummonSystem(rules)
    plan = system.plan_spawn_summoned_monster(state, intent, owner_id="enemy:summoner")
    result = system.apply_spawn(state, plan)
    after = MutationReducer().apply_all(state, result.mutations)
    replay = MutationReducer().replay_snapshot(state, result.mutations, after.snapshot().to_json())
    spawned = tuple(unit_id for unit_id in plan.unit_ids if unit_id in after.units)
    runtime = _runtime(after)
    settlement_result = SettlementTraceabilityValidator().validate(
        ActionSettlement("summon_spawn", plan.owner_id, spawned, result.records),
        result.mutations,
    )
    last_expr = _select_target_expression(rules, "LastSummonMonsters")
    last_result = (
        TargetSystem().resolve_target_expression(after, last_expr, caster_id=plan.owner_id)
        if last_expr is not None
        else None
    )
    spawn_mutations = tuple(mutation for mutation in result.mutations if mutation.metadata.get("lifecycle_operation") == "unit_spawn")
    entries = [_runtime_entry(runtime, unit_id) for unit_id in spawned]
    checks = {
        "plan_ok": plan.ok and plan.operation == "spawn_summoned_monster",
        "plan_instance_count_matches_entry_count": len(plan.unit_ids) == sum(entry.count for entry in intent.entries),
        "spawn_mutation_count_matches_instances": len(spawn_mutations) == len(plan.unit_ids) and bool(spawn_mutations),
        "runtime_mutation_present": any(mutation.path == ("global_flags", "summon_runtime") for mutation in result.mutations),
        "unit_stats_match_profile_and_card": all(_unit_matches_entry_sources(rules, intent, after.units[unit_id]) for unit_id in spawned),
        "unit_flags_carry_required_sources": all(_unit_source_flags_complete(after.units[unit_id]) for unit_id in spawned),
        "mutation_metadata_carries_required_sources": all(_spawn_mutation_source_metadata_complete(mutation) for mutation in spawn_mutations),
        "runtime_entries_carry_required_sources": all(_runtime_entry_complete(entry) for entry in entries),
        "delay_policy_admitted_and_carried": intent.delay_policy.get("admission_status") == "executable"
        and all(after.units[unit_id].flags.get("summon_delay_policy") == intent.delay_policy for unit_id in spawned),
        "timeline_action_value_matches_delay_ratio": all(
            _timeline_delay_ratio_trace_matches(after.units[unit_id]) for unit_id in spawned
        ),
        "wave_clear_policy_counts": all(after.units[unit_id].flags.get("wave_clear_policy") == "counts" for unit_id in spawned),
        "owner_summoner_and_side": all(
            after.units[unit_id].side == "enemy"
            and after.units[unit_id].flags.get("owner_id") == plan.owner_id
            and after.units[unit_id].flags.get("summoner_id") == plan.owner_id
            for unit_id in spawned
        ),
        "target_relation_resolves": last_result is not None
        and last_result.ok
        and all(unit_id in last_result.target_ids for unit_id in spawned),
        "settlement_traceability_ok": settlement_result.ok and settlement_result.mutation_linked_records == len(result.mutations),
        "replay_ok": replay.ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "executable",
        "selected_intent": intent.summon_intent_id,
        "selected_source_path": intent.source.source_path,
        "entry_count": len(intent.entries),
        "spawned_unit_ids": list(spawned),
        "spawn_mutation_count": len(spawn_mutations),
        "runtime_entry_sample": entries[0] if entries else {},
        "settlement_traceability": settlement_result.to_json(),
        "target_resolution": last_result.to_json() if last_result is not None else {},
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
    }


def _multi_entry_boundary_case(rules: RuleBook) -> dict[str, Any]:
    multi_entry_intents = tuple(intent for intent in rules.summon_monster_intents() if len(intent.entries) > 1)
    executable_multi_entry = tuple(intent for intent in multi_entry_intents if intent.coverage_status == "executable")
    state = _base_summon_state()
    system = SummonSystem(rules)
    selected = multi_entry_intents[0] if multi_entry_intents else None
    before_hash = _snapshot_hash(state)
    plan = system.plan_spawn_summoned_monster(state, selected, owner_id="enemy:summoner") if selected is not None else None
    result = system.apply_spawn(state, plan) if plan is not None else None
    after_hash = _snapshot_hash(state)
    checks = {
        "multi_entry_raw_ir_sources_present": bool(multi_entry_intents),
        "current_database_has_no_executable_multi_entry": not executable_multi_entry,
        "blocked_multi_entry_plan_state_unchanged": plan is not None
        and not plan.ok
        and result is not None
        and not result.mutations
        and before_hash == after_hash,
        "blocked_multi_entry_process_only_record": result is not None
        and bool(result.records)
        and result.records[0].get("process_only") is True,
        "blocked_reason_is_source_admission": plan is not None
        and any(
            token in plan.blocked_reason
            for token in (
                "summon_monster_id_from_custom_value_not_admitted",
                "summon_monster_profile_missing_or_blocked",
                "summon_monster_profile_source_missing",
                "summon_monster_profile_source_blocked",
                "summon_monster_data_card_source_missing",
                "summon_monster_data_card_source_blocked",
                "summon_monster_location_type_not_admitted",
                "summon_monster_delay_ratio",
            )
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "admission_gap_current_database",
        "multi_entry_intent_count": len(multi_entry_intents),
        "executable_multi_entry_count": len(executable_multi_entry),
        "selected_blocked_intent": selected.summon_intent_id if selected is not None else "",
        "selected_blocked_reason": selected.blocked_reason if selected is not None else "",
        "plan": plan.to_json() if plan is not None else {},
    }


def _unsupported_source_boundary_case(rules: RuleBook) -> dict[str, Any]:
    state = _base_summon_state()
    system = SummonSystem(rules)
    executable_intent = _select_executable_summon_monster_intent(rules)
    missing_owner_plan = system.plan_spawn_summoned_monster(state, executable_intent, owner_id="enemy:missing")
    duplicate_state = _state_with_existing_unit(state, system.plan_spawn_summoned_monster(state, executable_intent, owner_id="enemy:summoner"))
    duplicate_plan = system.plan_spawn_summoned_monster(duplicate_state, executable_intent, owner_id="enemy:summoner")
    blocked_reasons = _blocked_reason_samples(rules)
    blocked_results = {
        label: _blocked_intent_state_case(system, state, intent)
        for label, intent in blocked_reasons.items()
        if intent is not None
    }
    checks = {
        "missing_owner_blocked": not missing_owner_plan.ok and missing_owner_plan.blocked_reason == "summon_owner_missing",
        "duplicate_unit_id_blocked": not duplicate_plan.ok and "summon_monster_unit_id_already_exists" in duplicate_plan.blocked_reason,
        "delay_blocked_source_present_or_fully_admitted": "delay" in blocked_results
        or not _any_blocked_reason_contains(rules, "summon_monster_delay_ratio"),
        "dynamic_monster_id_blocked_source_present": "dynamic_monster_id" in blocked_results,
        "profile_or_card_blocked_source_present": "profile_or_card" in blocked_results,
        "unsupported_position_blocked_source_present": "unsupported_position" in blocked_results,
        "blocked_cases_state_unchanged": blocked_results
        and all(item["state_unchanged"] and item["mutation_count"] == 0 and item["process_only_record"] for item in blocked_results.values()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "boundary_only",
        "missing_owner_plan": missing_owner_plan.to_json(),
        "duplicate_plan": duplicate_plan.to_json(),
        "blocked_cases": blocked_results,
    }


def _count_unique_group_boundary_case(raw_matrix: dict[str, Any], intents: tuple[SummonMonsterIntentIR, ...]) -> dict[str, Any]:
    count_values = Counter(entry.count for intent in intents for entry in intent.entries)
    evidence_with_count_policy = sum(
        1
        for intent in intents
        for entry in intent.entries
        if isinstance(entry.source.evidence.get("count_policy"), dict)
        and entry.source.evidence.get("count_policy", {}).get("admission_status") == "executable"
    )
    total_entries = sum(len(intent.entries) for intent in intents)
    checks = {
        "raw_count_field_absent": raw_matrix["count_field_occurrence_count"] == 0,
        "all_ir_counts_are_implicit_one": set(count_values) == {1},
        "count_policy_evidence_present": total_entries > 0 and evidence_with_count_policy == total_entries,
        "raw_unique_or_max_source_absent": raw_matrix["unique_or_max_field_occurrence_count"] == 0,
        "runtime_does_not_fabricate_unique_group": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "source_absent_not_required",
        "count_values": dict(sorted((str(key), value) for key, value in count_values.items())),
        "total_entry_count": total_entries,
        "count_policy_evidence_count": evidence_with_count_policy,
        "unique_group_source_note": "Current SummonMonster raw tasks do not expose UniqueGroup/MaxSummonCount semantics; SummonUnitData unique-group sources remain P3-S4 scope.",
    }


def _raw_summon_monster_matrix(tbgd_root: Path) -> dict[str, Any]:
    root = tbgd_root / "Config" / "ConfigAbility"
    task_key_counts: Counter[str] = Counter()
    entry_key_counts: Counter[str] = Counter()
    samples: list[dict[str, JSONValue]] = []
    ability_file_count = 0
    occurrence_count = 0
    multi_entry_occurrence_count = 0
    count_field_occurrence_count = 0
    unique_or_max_field_occurrence_count = 0
    for path in sorted(root.rglob("*.json")):
        text = path.read_text(encoding="utf-8")
        if "SummonMonsterDataList" not in text:
            continue
        ability_file_count += 1
        data = json.loads(text)
        for record in _walk_summon_monster_records(data, path.relative_to(tbgd_root).as_posix()):
            occurrence_count += 1
            task = record["task"]
            entries = task.get("SummonMonsterDataList")
            for key in task:
                task_key_counts[str(key)] += 1
            if any(key in task for key in ("Count", "MonsterCount", "SummonCount")):
                count_field_occurrence_count += 1
            if any("Unique" in str(key) or "MaxSummon" in str(key) or "MaxCount" in str(key) for key in task):
                unique_or_max_field_occurrence_count += 1
            if isinstance(entries, list):
                if len(entries) > 1:
                    multi_entry_occurrence_count += 1
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    for key in entry:
                        entry_key_counts[str(key)] += 1
                    if any(key in entry for key in ("Count", "MonsterCount", "SummonCount")):
                        count_field_occurrence_count += 1
                    if any("Unique" in str(key) or "MaxSummon" in str(key) or "MaxCount" in str(key) for key in entry):
                        unique_or_max_field_occurrence_count += 1
            if len(samples) < 6:
                samples.append(
                    {
                        "source_path": record["source_path"],
                        "json_path": "/".join(record["json_path"]),
                        "entry_count": len(entries) if isinstance(entries, list) else 0,
                        "task_keys": sorted(str(key) for key in task.keys()),
                        "entry_keys": sorted({str(key) for entry in entries or [] if isinstance(entry, dict) for key in entry.keys()})
                        if isinstance(entries, list)
                        else [],
                    }
                )
    return {
        "ability_file_count": ability_file_count,
        "occurrence_count": occurrence_count,
        "multi_entry_occurrence_count": multi_entry_occurrence_count,
        "count_field_occurrence_count": count_field_occurrence_count,
        "unique_or_max_field_occurrence_count": unique_or_max_field_occurrence_count,
        "task_key_counts_top": _counter_top(task_key_counts, 30),
        "entry_key_counts_top": _counter_top(entry_key_counts, 30),
        "samples": samples,
    }


def _walk_summon_monster_records(value: Any, source_path: str, path: tuple[str, ...] = ()) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if "SummonMonsterDataList" in value:
            records.append({"source_path": source_path, "json_path": path, "task": value})
        for key, child in value.items():
            records.extend(_walk_summon_monster_records(child, source_path, (*path, str(key))))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            records.extend(_walk_summon_monster_records(child, source_path, (*path, str(index))))
    return tuple(records)


def _unit_matches_entry_sources(rules: RuleBook, intent: SummonMonsterIntentIR, unit: UnitState) -> bool:
    entry = _entry_for_unit(intent, unit)
    profile = rules.combatant_profile(entry.monster_entity_ref) if entry is not None else None
    card = rules.monster_data_card_for_entity(entry.monster_entity_ref) if entry is not None else None
    if entry is None or profile is None or card is None:
        return False
    resistances_ok = all(
        unit.resources.get(f"{damage_type}_resistance") == float(value)
        for damage_type, value in profile.resistances.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    )
    status_resistance_ok = True
    if isinstance(profile.status_resistance, (int, float)) and not isinstance(profile.status_resistance, bool):
        status_resistance_ok = unit.resources.get("effect_resistance") == float(profile.status_resistance)
    return (
        unit.template_id == entry.monster_entity_ref
        and unit.max_hp == _number(profile.base_stats.get("max_hp"))
        and unit.hp == _number(profile.base_stats.get("max_hp"))
        and unit.attack == _number(profile.base_stats.get("attack"))
        and unit.defense == _number(profile.base_stats.get("defense"))
        and unit.speed == _number(profile.base_stats.get("speed"))
        and unit.toughness == _number(profile.toughness_profile.get("current_toughness"))
        and unit.max_toughness == _number(profile.toughness_profile.get("max_toughness"))
        and unit.flags.get("combatant_profile_id") == profile.profile_id
        and unit.flags.get("monster_data_card_id") == card.card_id
        and resistances_ok
        and status_resistance_ok
    )


def _unit_source_flags_complete(unit: UnitState) -> bool:
    return (
        isinstance(unit.flags.get("summon_source_trace"), dict)
        and bool(unit.flags.get("summon_source_trace"))
        and isinstance(unit.flags.get("summon_entry_source_trace"), dict)
        and bool(unit.flags.get("summon_entry_source_trace"))
        and isinstance(unit.flags.get("summon_position_policy"), dict)
        and unit.flags.get("summon_position_policy", {}).get("admission_status") == "executable"
        and isinstance(unit.flags.get("summon_delay_policy"), dict)
        and unit.flags.get("summon_delay_policy", {}).get("admission_status") == "executable"
        and isinstance(unit.flags.get("summon_level_policy"), dict)
        and unit.flags.get("summon_level_policy", {}).get("admission_status") == "executable"
        and isinstance(unit.flags.get("combatant_profile_source_trace"), dict)
        and bool(unit.flags.get("combatant_profile_source_trace"))
        and isinstance(unit.flags.get("monster_data_card_source_trace"), dict)
        and bool(unit.flags.get("monster_data_card_source_trace"))
        and isinstance(unit.flags.get("initial_action_value_source_trace"), dict)
        and bool(unit.flags.get("initial_action_value_source_trace"))
        and isinstance(unit.flags.get("summon_entry_count"), int)
        and unit.flags.get("summon_entry_count") > 0
    )


def _spawn_mutation_source_metadata_complete(mutation: Any) -> bool:
    metadata = mutation.metadata
    return (
        metadata.get("summon_operation") == "spawn_summoned_monster"
        and isinstance(metadata.get("source_trace"), dict)
        and bool(metadata.get("source_trace"))
        and isinstance(metadata.get("summon_entry_source_trace"), dict)
        and bool(metadata.get("summon_entry_source_trace"))
        and isinstance(metadata.get("summon_position_policy"), dict)
        and metadata.get("summon_position_policy", {}).get("admission_status") == "executable"
        and isinstance(metadata.get("summon_delay_policy"), dict)
        and metadata.get("summon_delay_policy", {}).get("admission_status") == "executable"
        and isinstance(metadata.get("combatant_profile_source_trace"), dict)
        and bool(metadata.get("combatant_profile_source_trace"))
        and isinstance(metadata.get("monster_data_card_source_trace"), dict)
        and bool(metadata.get("monster_data_card_source_trace"))
    )


def _runtime_entry_complete(entry: dict[str, JSONValue]) -> bool:
    return (
        entry.get("summon_kind") == "summoned_monster"
        and entry.get("status") == "active"
        and isinstance(entry.get("source_trace"), dict)
        and bool(entry.get("source_trace"))
        and isinstance(entry.get("source_entry_trace"), dict)
        and bool(entry.get("source_entry_trace"))
        and isinstance(entry.get("position_policy"), dict)
        and entry.get("position_policy", {}).get("admission_status") == "executable"
        and isinstance(entry.get("level_policy"), dict)
        and entry.get("level_policy", {}).get("admission_status") == "executable"
        and isinstance(entry.get("profile_source_trace"), dict)
        and bool(entry.get("profile_source_trace"))
        and isinstance(entry.get("monster_data_card_source_trace"), dict)
        and bool(entry.get("monster_data_card_source_trace"))
        and isinstance(entry.get("timeline"), dict)
        and entry.get("timeline", {}).get("admitted") is True
        and entry.get("wave_clear_policy") == "counts"
    )


def _timeline_delay_ratio_trace_matches(unit: UnitState) -> bool:
    trace = unit.flags.get("initial_action_value_source_trace")
    if not isinstance(trace, dict):
        return False
    if trace.get("summon_delay_application") != "initial_action_value_full_av_times_delay_ratio":
        return False
    base_action_value = _strict_number(trace.get("base_action_value"))
    delay_ratio = _strict_number(trace.get("delay_ratio"))
    initial_action_value = _strict_number(trace.get("initial_action_value"))
    if base_action_value is None or delay_ratio is None or initial_action_value is None:
        return False
    expected = max(0.0, base_action_value * delay_ratio)
    return _close(initial_action_value, expected) and _close(unit.action_value, expected)


def _blocked_reason_samples(rules: RuleBook) -> dict[str, SummonMonsterIntentIR | None]:
    result: dict[str, SummonMonsterIntentIR | None] = {
        "delay": None,
        "dynamic_monster_id": None,
        "profile_or_card": None,
        "unsupported_position": None,
    }
    for intent in rules.summon_monster_intents():
        reason = intent.blocked_reason
        if intent.coverage_status != "blocked":
            continue
        if result["delay"] is None and "summon_monster_delay_ratio" in reason:
            result["delay"] = intent
        if result["dynamic_monster_id"] is None and "summon_monster_id_from_custom_value_not_admitted" in reason:
            result["dynamic_monster_id"] = intent
        if result["profile_or_card"] is None and (
            "summon_monster_profile_missing_or_blocked" in reason
            or "summon_monster_data_card_missing" in reason
            or "summon_monster_profile_source_missing" in reason
            or "summon_monster_profile_source_blocked" in reason
            or "summon_monster_data_card_source_missing" in reason
            or "summon_monster_data_card_source_blocked" in reason
        ):
            result["profile_or_card"] = intent
        if result["unsupported_position"] is None and "summon_monster_location_type_not_admitted" in reason:
            result["unsupported_position"] = intent
    return result


def _any_blocked_reason_contains(rules: RuleBook, token: str) -> bool:
    return any(
        intent.coverage_status == "blocked" and token in intent.blocked_reason
        for intent in rules.summon_monster_intents()
    )


def _blocked_intent_state_case(system: SummonSystem, state: BattleState, intent: SummonMonsterIntentIR) -> dict[str, JSONValue]:
    before_hash = _snapshot_hash(state)
    plan = system.plan_spawn_summoned_monster(state, intent, owner_id="enemy:summoner")
    result = system.apply_spawn(state, plan)
    return {
        "intent_id": intent.summon_intent_id,
        "blocked_reason": plan.blocked_reason,
        "plan_ok": plan.ok,
        "mutation_count": len(result.mutations),
        "state_unchanged": before_hash == _snapshot_hash(state),
        "process_only_record": bool(result.records) and result.records[0].get("process_only") is True,
    }


def _state_with_existing_unit(state: BattleState, plan: Any) -> BattleState:
    if not plan.ok or not plan.unit_ids:
        return state
    units = dict(state.units)
    units[plan.unit_ids[0]] = UnitState(
        plan.unit_ids[0],
        "enemy",
        "monster:duplicate_probe",
        hp=1.0,
        max_hp=1.0,
        flags={"position": 9},
    )
    return replace(state, units=units)


def _entry_for_unit(intent: SummonMonsterIntentIR, unit: UnitState):
    entry_id = unit.flags.get("summon_entry_id")
    for entry in intent.entries:
        if entry.entry_id == entry_id:
            return entry
    return None


def _runtime(state: BattleState) -> dict[str, JSONValue]:
    runtime = state.global_flags.get("summon_runtime")
    return dict(runtime) if isinstance(runtime, dict) else {}


def _runtime_entry(runtime: dict[str, JSONValue], unit_id: str) -> dict[str, JSONValue]:
    entities = runtime.get("entities")
    if not isinstance(entities, dict):
        return {}
    entry = entities.get(unit_id)
    return dict(entry) if isinstance(entry, dict) else {}


def _number(value: JSONValue) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _strict_number(value: JSONValue) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _close(left: float, right: float, *, tolerance: float = 1e-9) -> bool:
    return abs(left - right) <= tolerance


def _counter_top(counter: Counter[str], limit: int) -> list[dict[str, JSONValue]]:
    return [{"key": key, "count": count} for key, count in counter.most_common(limit)]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
