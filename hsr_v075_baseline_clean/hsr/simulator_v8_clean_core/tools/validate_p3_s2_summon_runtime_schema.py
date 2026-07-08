from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, JSONValue, UnitState
from ..core.reducer import MutationReducer
from ..rules.rulebook import RuleBook
from ..systems.action_availability import ActionAvailabilitySystem
from ..systems.summon import SUMMON_RUNTIME_SCHEMA_VERSION, SummonSystem
from ..systems.target import TargetSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p1_3_summon_assistant_servant import (
    _base_servant_state,
    _base_summon_state,
    _flag_only_servant_state,
    _first_servant_id,
    _select_executable_servant_definition,
    _select_executable_summon_monster_intent,
    _select_global_target_expression,
    _select_target_expression,
    _snapshot_hash,
)


VALIDATION_VERSION = "p3_s2_summon_runtime_schema"
MATRIX_SCHEMA_VERSION = "p3_summon_runtime_schema_matrix_s2"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    runtime_matrix = build_p3_s2_runtime_matrix(rules)
    runtime_checks = validate_p3_s2_runtime_matrix(runtime_matrix)
    checks = {
        "runtime_schema": runtime_checks,
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "p3_s2_runtime_schema_structured_positive_and_negative_validation",
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "textmap_read": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
            },
        },
        "checks": checks,
        "summary": runtime_matrix["summary"],
        "case_groups": runtime_matrix["case_groups"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p3_s2_summon_runtime_schema.json", result)
    write_json(output_dir / "p3_summon_runtime_schema_matrix_s2.json", runtime_matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P3-S2 summon runtime schema v2 and identity registry.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def build_p3_s2_runtime_matrix(rules: RuleBook) -> dict[str, Any]:
    case_groups = {
        "summoned_monster_runtime": _summoned_monster_runtime_case(rules),
        "servant_runtime_remove": _servant_runtime_remove_case(rules),
        "owner_cleanup_runtime": _owner_cleanup_runtime_case(rules),
        "legacy_view_normalization": _legacy_view_normalization_case(rules),
        "negative_boundaries": _negative_boundary_case(rules),
    }
    failed = {
        group_id: [key for key, value in group["checks"]["checks"].items() if value is False]
        for group_id, group in case_groups.items()
        if not group["checks"]["ok"]
    }
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "runtime_schema_version": SUMMON_RUNTIME_SCHEMA_VERSION,
        "coverage_scope": {
            "runtime_behavior_changed": True,
            "runtime_reads_raw_tbgd": False,
            "textmap_read": False,
            "full_ir_written": False,
            "full_transition_dump_written": False,
        },
        "case_groups": case_groups,
        "summary": {
            "case_group_count": len(case_groups),
            "failed_group_count": len(failed),
            "failed_checks": failed,
            "schema_version": SUMMON_RUNTIME_SCHEMA_VERSION,
            "positive_runtime_groups": [
                "summoned_monster_runtime",
                "servant_runtime_remove",
                "owner_cleanup_runtime",
            ],
            "negative_boundary_groups": ["negative_boundaries"],
        },
    }


def validate_p3_s2_runtime_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    groups = matrix["case_groups"]
    checks = {
        "summoned_monster_runtime_ok": groups["summoned_monster_runtime"]["checks"]["ok"],
        "servant_runtime_remove_ok": groups["servant_runtime_remove"]["checks"]["ok"],
        "owner_cleanup_runtime_ok": groups["owner_cleanup_runtime"]["checks"]["ok"],
        "legacy_view_normalization_ok": groups["legacy_view_normalization"]["checks"]["ok"],
        "negative_boundaries_ok": groups["negative_boundaries"]["checks"]["ok"],
        "schema_version_is_v2": matrix["runtime_schema_version"] == "p3_summon_runtime_v2",
        "matrix_is_lightweight": (
            matrix["coverage_scope"]["full_ir_written"] is False
            and matrix["coverage_scope"]["full_transition_dump_written"] is False
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"ok": checks["ok"], "checks": checks}


def _summoned_monster_runtime_case(rules: RuleBook) -> dict[str, Any]:
    intent = _select_executable_summon_monster_intent(rules)
    state = _base_summon_state()
    system = SummonSystem(rules)
    before_hash = _snapshot_hash(state)
    view = system.view(state)
    plan = system.plan_spawn_summoned_monster(state, intent, owner_id="enemy:summoner")
    result = system.apply_spawn(state, plan)
    after = MutationReducer().apply_all(state, result.mutations)
    replay = MutationReducer().replay_snapshot(state, result.mutations, after.snapshot().to_json())
    runtime = _runtime(after)
    spawned = tuple(unit_id for unit_id in plan.unit_ids if unit_id in after.units)
    entries = [_runtime_entry(runtime, unit_id) for unit_id in spawned]
    last_expr = _select_target_expression(rules, "LastSummonMonsters")
    last_result = (
        TargetSystem().resolve_target_expression(after, last_expr, caster_id="enemy:summoner")
        if last_expr is not None
        else None
    )
    checks = {
        "view_pure_query": before_hash == _snapshot_hash(state),
        "view_schema_v2": view.schema_version == SUMMON_RUNTIME_SCHEMA_VERSION,
        "view_schema_boundary_present": _schema_boundary_ok(view.runtime),
        "plan_ok": plan.ok and plan.operation == "spawn_summoned_monster",
        "runtime_mutation_present": _has_runtime_mutation(result.mutations),
        "runtime_schema_v2": runtime.get("schema_version") == SUMMON_RUNTIME_SCHEMA_VERSION,
        "runtime_schema_boundary_present": _schema_boundary_ok(runtime),
        "spawned_unit_count_matches_plan": bool(spawned) and len(spawned) == len(plan.unit_ids),
        "entity_records_complete": bool(entries)
        and all(_summoned_monster_entry_ok(entry, after.units[str(entry.get("unit_id"))]) for entry in entries),
        "by_owner_tracks_spawned": all(unit_id in runtime.get("by_owner", {}).get("enemy:summoner", []) for unit_id in spawned),
        "last_summon_tracks_spawned": all(unit_id in runtime.get("last_summon_monsters", []) for unit_id in spawned),
        "assistant_history_index_present": isinstance(runtime.get("assistant_history"), list),
        "target_expression_resolves_through_registry": last_result is not None
        and last_result.ok
        and all(unit_id in last_result.target_ids for unit_id in spawned),
        "replay_ok": replay.ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "executable",
        "selected_intent": intent.summon_intent_id,
        "spawned_unit_ids": list(spawned),
        "runtime_entity_sample": entries[0] if entries else {},
        "target_resolution": last_result.to_json() if last_result is not None else {},
        "mutation_count": len(result.mutations),
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
    }


def _servant_runtime_remove_case(rules: RuleBook) -> dict[str, Any]:
    definition = _select_executable_servant_definition(rules)
    base_state = _base_servant_state(definition)
    system = SummonSystem(rules)
    plan = system.plan_spawn_servant(base_state, definition, owner_id="ally:servant_owner")
    result = system.apply_spawn_servant(base_state, plan)
    after = MutationReducer().apply_all(base_state, result.mutations)
    spawn_replay = MutationReducer().replay_snapshot(base_state, result.mutations, after.snapshot().to_json())
    servant_id = _first_servant_id(after)
    runtime = _runtime(after)
    entry = _runtime_entry(runtime, servant_id)
    servant = after.units[servant_id]
    remove_plan = system.plan_remove(
        after,
        servant_id,
        "p3_s2_validation_remove",
        source_trace=servant.flags.get("owner_death_policy_source_trace")
        if isinstance(servant.flags.get("owner_death_policy_source_trace"), dict)
        else None,
        admission=servant.flags.get("owner_death_policy_admission")
        if isinstance(servant.flags.get("owner_death_policy_admission"), dict)
        else None,
    )
    remove_result = system.apply_remove(after, remove_plan)
    removed_after = MutationReducer().apply_all(after, remove_result.mutations)
    remove_replay = MutationReducer().replay_snapshot(after, remove_result.mutations, removed_after.snapshot().to_json())
    removed_runtime = _runtime(removed_after)
    removed_entry = _runtime_entry(removed_runtime, servant_id)
    removed_servant_entry = dict(removed_runtime.get("servants", {}).get(servant_id) or {})
    servant_list_expr = _select_target_expression(rules, "ServantEntityList")
    servant_list_after_remove = (
        TargetSystem().resolve_target_expression(removed_after, servant_list_expr, caster_id="ally:servant_owner")
        if servant_list_expr is not None
        else None
    )
    checks = {
        "spawn_plan_ok": plan.ok and plan.operation == "servant_spawn",
        "spawn_runtime_schema_v2": runtime.get("schema_version") == SUMMON_RUNTIME_SCHEMA_VERSION,
        "spawn_runtime_mutation_present": _has_runtime_mutation(result.mutations),
        "servant_entity_record_complete": _servant_entry_ok(entry, servant),
        "servant_index_tracks_entity": servant_id in runtime.get("servants", {}),
        "last_servants_tracks_entity": servant_id in runtime.get("last_servants", []),
        "spawn_replay_ok": spawn_replay.ok,
        "remove_plan_ok": remove_plan.ok and remove_plan.operation == "remove_summon",
        "remove_runtime_mutation_present": _has_runtime_mutation(remove_result.mutations),
        "removed_entity_retained": servant_id in removed_runtime.get("entities", {}),
        "removed_servant_retained": servant_id in removed_runtime.get("servants", {}),
        "removed_entity_marked_removed": removed_entry.get("status") == "removed"
        and removed_entry.get("removed_event_index") == after.event_index
        and removed_entry.get("removed_reason") == "p3_s2_validation_remove",
        "removed_servant_marked_removed": removed_servant_entry.get("status") == "removed"
        and removed_servant_entry.get("removed_event_index") == after.event_index,
        "removed_target_not_resolved": servant_list_after_remove is not None
        and not servant_list_after_remove.ok
        and servant_id not in servant_list_after_remove.target_ids,
        "remove_replay_ok": remove_replay.ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "executable",
        "selected_servant_definition": definition.servant_definition_id,
        "servant_unit_id": servant_id,
        "runtime_entity_sample": entry,
        "removed_runtime_entity_sample": removed_entry,
        "mutation_counts": {"spawn": len(result.mutations), "remove": len(remove_result.mutations)},
        "replay": {
            "spawn_ok": spawn_replay.ok,
            "spawn_errors": list(spawn_replay.errors),
            "remove_ok": remove_replay.ok,
            "remove_errors": list(remove_replay.errors),
        },
    }


def _owner_cleanup_runtime_case(rules: RuleBook) -> dict[str, Any]:
    definition = _select_executable_servant_definition(rules)
    base_state = _base_servant_state(definition)
    system = SummonSystem(rules)
    spawn_plan = system.plan_spawn_servant(base_state, definition, owner_id="ally:servant_owner")
    spawn_result = system.apply_spawn_servant(base_state, spawn_plan)
    after_spawn = MutationReducer().apply_all(base_state, spawn_result.mutations)
    servant_id = _first_servant_id(after_spawn)
    cleanup_plan = system.plan_owner_cleanup(after_spawn, "ally:servant_owner")
    cleanup_result = system.apply_remove(after_spawn, cleanup_plan)
    after_cleanup = MutationReducer().apply_all(after_spawn, cleanup_result.mutations)
    replay = MutationReducer().replay_snapshot(after_spawn, cleanup_result.mutations, after_cleanup.snapshot().to_json())
    runtime = _runtime(after_cleanup)
    entry = _runtime_entry(runtime, servant_id)
    checks = {
        "cleanup_plan_ok": cleanup_plan.ok and cleanup_plan.operation == "owner_removed_cleanup",
        "cleanup_runtime_mutation_present": _has_runtime_mutation(cleanup_result.mutations),
        "cleanup_removed_unit": after_cleanup.units[servant_id].flags.get("lifecycle_status") == "removed",
        "cleanup_entity_retained": servant_id in runtime.get("entities", {}),
        "cleanup_by_owner_clears_active_id": servant_id not in runtime.get("by_owner", {}).get("ally:servant_owner", []),
        "cleanup_servants_retains_audit_id": servant_id in runtime.get("servants", {}),
        "cleanup_marked_removed": entry.get("status") == "removed"
        and entry.get("removed_reason") == "owner_removed_cleanup"
        and entry.get("removed_event_index") == after_spawn.event_index,
        "cleanup_source_trace_retained": isinstance(entry.get("source_trace"), dict) and bool(entry.get("source_trace")),
        "cleanup_replay_ok": replay.ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "executable",
        "servant_unit_id": servant_id,
        "cleanup_plan": cleanup_plan.to_json(),
        "runtime_entity_sample": entry,
        "mutation_count": len(cleanup_result.mutations),
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
    }


def _legacy_view_normalization_case(rules: RuleBook) -> dict[str, Any]:
    state = BattleState(
        units={
            "enemy:legacy_owner": UnitState(
                "enemy:legacy_owner",
                "enemy",
                "monster:legacy_owner",
                hp=100.0,
                max_hp=100.0,
                flags={"position": 5},
            )
        },
        global_flags={
            "summon_runtime": {
                "schema_version": "p1_3_summon_runtime_v1",
                "entities": {
                    "summon:legacy": {
                        "summon_kind": "summoned_monster",
                        "owner_id": "enemy:legacy_owner",
                        "source_intent_id": "summon_intent:legacy",
                        "source_trace": {"source_path": "validation", "raw_type": "SummonMonsterIntent", "raw_id": "legacy"},
                    }
                },
                "by_owner": {"enemy:legacy_owner": ["summon:legacy"]},
                "last_summon_monsters": ["summon:legacy"],
            }
        },
    )
    before_hash = _snapshot_hash(state)
    view = SummonSystem(rules).view(state)
    runtime = view.runtime
    entry = _runtime_entry(runtime, "summon:legacy")
    checks = {
        "view_pure_query": before_hash == _snapshot_hash(state),
        "source_state_kept_legacy_schema": state.global_flags["summon_runtime"]["schema_version"] == "p1_3_summon_runtime_v1",
        "view_schema_upgraded_to_v2": view.schema_version == SUMMON_RUNTIME_SCHEMA_VERSION,
        "schema_boundary_mentions_previous": "p1_3_summon_runtime_v1"
        in runtime.get("schema_boundary", {}).get("previous_schema_versions", []),
        "legacy_entity_normalized_identity": entry.get("runtime_id") == "summon:legacy"
        and entry.get("unit_id") == "summon:legacy"
        and entry.get("status") == "active",
        "legacy_indexes_normalized": runtime.get("by_owner", {}).get("enemy:legacy_owner") == ["summon:legacy"]
        and runtime.get("last_summon_monsters") == ["summon:legacy"],
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "compatibility_boundary",
        "view_runtime": {
            "schema_version": runtime.get("schema_version"),
            "schema_boundary": runtime.get("schema_boundary"),
            "entity": entry,
        },
    }


def _negative_boundary_case(rules: RuleBook) -> dict[str, Any]:
    definition = _select_executable_servant_definition(rules)
    base_state = _base_servant_state(definition)
    system = SummonSystem(rules)
    spawn_plan = system.plan_spawn_servant(base_state, definition, owner_id="ally:servant_owner")
    spawn_result = system.apply_spawn_servant(base_state, spawn_plan)
    after_spawn = MutationReducer().apply_all(base_state, spawn_result.mutations)
    servant_id = _first_servant_id(after_spawn)
    servant_list_expr = _select_target_expression(rules, "ServantEntityList")
    caster_servant_expr = _select_global_target_expression(rules, "CasterServant")
    missing_runtime_state = replace(
        after_spawn,
        global_flags={key: value for key, value in after_spawn.global_flags.items() if key != "summon_runtime"},
    )
    wrong_schema_runtime = dict(_runtime(after_spawn))
    wrong_schema_runtime["schema_version"] = "unsupported_summon_runtime_schema"
    wrong_schema_state = replace(after_spawn, global_flags={**after_spawn.global_flags, "summon_runtime": wrong_schema_runtime})
    missing_source_state = _state_with_runtime_entity_source_removed(after_spawn, servant_id)
    flag_only_state = _flag_only_servant_state(definition)
    before_flag_hash = _snapshot_hash(flag_only_state)
    flag_only_availability = ActionAvailabilitySystem(rules).view(flag_only_state)
    missing_runtime_result = (
        TargetSystem().resolve_target_expression(missing_runtime_state, servant_list_expr, caster_id="ally:servant_owner")
        if servant_list_expr is not None
        else None
    )
    wrong_schema_result = (
        TargetSystem().resolve_target_expression(wrong_schema_state, servant_list_expr, caster_id="ally:servant_owner")
        if servant_list_expr is not None
        else None
    )
    flag_only_target = (
        TargetSystem().resolve_target_expression(flag_only_state, caster_servant_expr, caster_id="ally:servant_owner")
        if caster_servant_expr is not None
        else None
    )
    missing_source_target = (
        TargetSystem().resolve_target_expression(missing_source_state, servant_list_expr, caster_id="ally:servant_owner")
        if servant_list_expr is not None
        else None
    )
    flag_only_blocked_reasons = [item.reason for item in flag_only_availability.blocked]
    checks = {
        "servant_list_expression_present": servant_list_expr is not None,
        "caster_servant_expression_present": caster_servant_expr is not None,
        "missing_runtime_blocked": missing_runtime_result is not None
        and not missing_runtime_result.ok
        and missing_runtime_result.blocked_reason == "summon_runtime_missing",
        "wrong_schema_blocked": wrong_schema_result is not None
        and not wrong_schema_result.ok
        and wrong_schema_result.blocked_reason == "summon_runtime_missing",
        "flag_only_action_state_unchanged": before_flag_hash == _snapshot_hash(flag_only_state),
        "flag_only_action_blocked": not flag_only_availability.choices
        and any(reason in {"summon_runtime_state_missing", "summon_runtime_entity_missing"} for reason in flag_only_blocked_reasons),
        "flag_only_target_blocked": flag_only_target is not None
        and not flag_only_target.ok
        and flag_only_target.blocked_reason == "summon_runtime_missing",
        "missing_source_trace_target_blocked": missing_source_target is not None
        and not missing_source_target.ok
        and servant_id not in missing_source_target.target_ids,
        "missing_source_trace_reason_audited": missing_source_target is not None
        and missing_source_target.blocked_reason == "summon_runtime_entity_source_trace_missing",
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "boundary_only",
        "missing_runtime_resolution": missing_runtime_result.to_json() if missing_runtime_result is not None else {},
        "wrong_schema_resolution": wrong_schema_result.to_json() if wrong_schema_result is not None else {},
        "flag_only_target_resolution": flag_only_target.to_json() if flag_only_target is not None else {},
        "flag_only_action_blocked_reasons": flag_only_blocked_reasons,
        "missing_source_trace_resolution": missing_source_target.to_json() if missing_source_target is not None else {},
    }


def _summoned_monster_entry_ok(entry: dict[str, JSONValue], unit: UnitState) -> bool:
    return (
        entry.get("runtime_id") == unit.unit_id
        and entry.get("unit_id") == unit.unit_id
        and entry.get("template_ref") == unit.template_id
        and entry.get("summon_kind") == "summoned_monster"
        and entry.get("owner_id") == "enemy:summoner"
        and entry.get("summoner_id") == "enemy:summoner"
        and entry.get("team_side") == "enemy"
        and entry.get("status") == "active"
        and isinstance(entry.get("source_intent_id"), str)
        and bool(entry.get("source_intent_id"))
        and isinstance(entry.get("source_trace"), dict)
        and bool(entry.get("source_trace"))
        and isinstance(entry.get("source_entry_id"), str)
        and bool(entry.get("source_entry_id"))
        and isinstance(entry.get("source_entry_trace"), dict)
        and isinstance(entry.get("lifetime"), dict)
        and isinstance(entry.get("timeline"), dict)
        and isinstance(entry.get("targetability"), dict)
        and isinstance(entry.get("actionability"), dict)
        and entry.get("wave_clear_policy") in {"counts", "ignore", "blocked"}
        and entry.get("removed_event_index") is None
    )


def _servant_entry_ok(entry: dict[str, JSONValue], unit: UnitState) -> bool:
    return (
        entry.get("runtime_id") == unit.unit_id
        and entry.get("unit_id") == unit.unit_id
        and entry.get("template_ref") == unit.template_id
        and entry.get("summon_kind") == "servant"
        and entry.get("owner_id") == "ally:servant_owner"
        and entry.get("summoner_id") == "ally:servant_owner"
        and entry.get("team_side") == "ally"
        and entry.get("status") == "active"
        and isinstance(entry.get("source_intent_id"), str)
        and bool(entry.get("source_intent_id"))
        and isinstance(entry.get("source_trace"), dict)
        and bool(entry.get("source_trace"))
        and isinstance(entry.get("lifetime"), dict)
        and isinstance(entry.get("timeline"), dict)
        and isinstance(entry.get("targetability"), dict)
        and isinstance(entry.get("actionability"), dict)
        and entry.get("removed_event_index") is None
    )


def _schema_boundary_ok(runtime: dict[str, JSONValue]) -> bool:
    boundary = runtime.get("schema_boundary")
    return (
        isinstance(boundary, dict)
        and boundary.get("version") == SUMMON_RUNTIME_SCHEMA_VERSION
        and isinstance(boundary.get("forward_boundary"), str)
        and bool(boundary.get("forward_boundary"))
        and "p1_3_summon_runtime_v1" in boundary.get("previous_schema_versions", [])
    )


def _runtime(state: BattleState) -> dict[str, JSONValue]:
    runtime = state.global_flags.get("summon_runtime")
    return dict(runtime) if isinstance(runtime, dict) else {}


def _runtime_entry(runtime: dict[str, JSONValue], unit_id: str) -> dict[str, JSONValue]:
    entities = runtime.get("entities")
    if not isinstance(entities, dict):
        return {}
    entry = entities.get(unit_id)
    return dict(entry) if isinstance(entry, dict) else {}


def _has_runtime_mutation(mutations: tuple[Any, ...]) -> bool:
    return any(getattr(mutation, "path", ()) == ("global_flags", "summon_runtime") for mutation in mutations)


def _state_with_runtime_entity_source_removed(state: BattleState, unit_id: str) -> BattleState:
    runtime = dict(_runtime(state))
    entities = dict(runtime.get("entities") or {})
    entry = dict(entities.get(unit_id) or {})
    entry.pop("source_trace", None)
    entities[unit_id] = entry
    runtime["entities"] = entities
    return replace(state, global_flags={**state.global_flags, "summon_runtime": runtime})


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
