from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import (
    ActionCommand,
    ActionSettlement,
    ActionTransaction,
    BattleState,
    BattleTransition,
    JSONValue,
    UnitState,
)
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import ServantDefinitionIR, SummonMonsterIntentIR
from ..rules.rulebook import RuleBook
from ..systems.action_availability import ActionAvailabilitySystem
from ..systems.summon import SummonSystem
from ..systems.target import TargetSystem
from ..systems.wave import WaveSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p1_3_summon_assistant_servant import (
    _base_servant_state,
    _base_summon_state,
    _first_servant_id,
    _first_spawned_id,
    _select_executable_servant_definition,
    _select_executable_summon_monster_intent,
    _select_target_expression,
    _select_wave_definition,
)


VALIDATION_VERSION = "p3_s9_summon_lifecycle_cleanup"


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    *,
    rules: RuleBook | None = None,
) -> dict[str, Any]:
    lowering_build_count = 0
    if rules is None:
        rules = RuleBook(TBGDLowering(tbgd_root).build())
        lowering_build_count = 1
    static_result = run_static_checks(package_root)
    servant_definition = _select_executable_servant_definition(rules)
    summon_intent = _select_executable_summon_monster_intent(rules)
    groups = {
        "explicit_remove_cleanup": _explicit_remove_cleanup_case(rules, servant_definition),
        "owner_cleanup": _owner_cleanup_case(rules, servant_definition),
        "wave_clear_policy": _wave_clear_policy_case(rules, summon_intent),
    }
    checks = {
        **{name: group["checks"] for name, group in groups.items()},
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "structured_summon_lifecycle_cleanup_predicates",
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "servant_definition_id": servant_definition.servant_definition_id,
                "summon_intent_id": summon_intent.summon_intent_id,
            },
            "resource_budget": {
                "rulebook_build_count": lowering_build_count,
                "large_artifacts_written": False,
                "output_scope": "summary_matrix_and_compact_case_audit_only",
            },
        },
        "summary": {
            "failed_group_count": sum(0 if group["checks"]["ok"] else 1 for group in groups.values()),
            "explicit_remove_source_audit_ok": groups["explicit_remove_cleanup"]["source_audit"]["ok"],
            "explicit_remove_replay_ok": groups["explicit_remove_cleanup"]["replay"]["ok"],
            "owner_cleanup_source_audit_ok": groups["owner_cleanup"]["source_audit"]["ok"],
            "owner_cleanup_replay_ok": groups["owner_cleanup"]["replay"]["ok"],
            "real_wave_policy": groups["wave_clear_policy"]["real_wave_policy"],
            "real_wave_decision": groups["wave_clear_policy"]["real_plan"]["status"],
        },
        "case_groups": groups,
        "checks": checks,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p3_s9_summon_lifecycle_cleanup.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P3-S9 summon lifecycle cleanup.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _explicit_remove_cleanup_case(rules: RuleBook, definition: ServantDefinitionIR) -> dict[str, Any]:
    spawned = _spawn_servant_state(rules, definition)
    state = _state_with_cleanup_residue(spawned["after_state"], spawned["servant_id"])
    servant = state.units[spawned["servant_id"]]
    source_trace = servant.flags.get("owner_death_policy_source_trace")
    admission = servant.flags.get("owner_death_policy_admission")
    system = SummonSystem(rules)
    plan = system.plan_remove(
        state,
        spawned["servant_id"],
        "validation explicit remove source",
        source_trace=source_trace if isinstance(source_trace, dict) else {},
        admission=admission if isinstance(admission, dict) else {},
    )
    result = system.apply_remove(state, plan)
    after = MutationReducer().apply_all(state, result.mutations)
    replay = MutationReducer().replay_snapshot(state, result.mutations, after.snapshot().to_json())
    transition = _transition_from_summon_result(state, after, result)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    caster_servant_result = _target_result(rules, after, "CasterServant", "ally:servant_owner")
    servant_list_result = _target_result(rules, after, "ServantEntityList", "ally:servant_owner")
    availability = ActionAvailabilitySystem(rules).view(after)
    runtime = after.global_flags.get("summon_runtime") if isinstance(after.global_flags.get("summon_runtime"), dict) else {}
    entities = runtime.get("entities") if isinstance(runtime.get("entities"), dict) else {}
    servants = runtime.get("servants") if isinstance(runtime.get("servants"), dict) else {}
    by_owner = runtime.get("by_owner") if isinstance(runtime.get("by_owner"), dict) else {}
    by_unique_group = runtime.get("by_unique_group") if isinstance(runtime.get("by_unique_group"), dict) else {}
    negative = _missing_remove_source_case(rules, definition)
    servant_after = after.units[spawned["servant_id"]]
    checks = {
        "remove_plan_ok": plan.ok and plan.operation == "remove_summon" and plan.intent_id == definition.servant_definition_id,
        "unit_remove_mutation_present": any(mutation.metadata.get("lifecycle_operation") == "unit_remove" for mutation in result.mutations),
        "runtime_mutation_present": any(mutation.path == ("global_flags", "summon_runtime") for mutation in result.mutations),
        "status_cleanup_present": any(mutation.metadata.get("status_cleanup_operation") == "clear_statuses" for mutation in result.mutations)
        and servant_after.statuses == (),
        "status_details_cleanup_present": any(
            mutation.metadata.get("status_cleanup_operation") == "clear_status_details" for mutation in result.mutations
        )
        and "status_details" not in servant_after.flags,
        "queue_cleanup_present": any(mutation.metadata.get("queue_cleanup_operation") == "remove_entries_for_removed_summon" for mutation in result.mutations)
        and not _queues_reference_unit(after, spawned["servant_id"])
        and _survivor_queue_entry_present(after),
        "turn_owner_cleanup_present": any(
            mutation.metadata.get("turn_owner_cleanup_operation") == "clear_removed_turn_owner" for mutation in result.mutations
        )
        and "turn_owner_id" not in after.global_flags,
        "runtime_marks_removed": isinstance(entities.get(spawned["servant_id"]), dict)
        and entities[spawned["servant_id"]].get("status") == "removed"
        and isinstance(servants.get(spawned["servant_id"]), dict)
        and servants[spawned["servant_id"]].get("status") == "removed",
        "runtime_owner_indexes_pruned": spawned["servant_id"] not in by_owner.get("ally:servant_owner", [])
        and all(spawned["servant_id"] not in values for values in by_unique_group.values() if isinstance(values, list))
        and spawned["servant_id"] not in runtime.get("last_servants", []),
        "target_negative_after_remove": caster_servant_result.get("ok") is False
        and servant_list_result.get("ok") is False
        and spawned["servant_id"] not in caster_servant_result.get("target_ids", [])
        and spawned["servant_id"] not in servant_list_result.get("target_ids", []),
        "availability_no_removed_servant_choice": all(choice.actor_id != spawned["servant_id"] for choice in availability.choices),
        "replay_ok": replay.ok,
        "source_audit_ok": source_audit.ok,
        "missing_remove_source_blocked": negative["checks"]["ok"],
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "executable",
        "servant_definition_id": definition.servant_definition_id,
        "servant_unit_id": spawned["servant_id"],
        "plan": plan.to_json(),
        "mutation_paths": [list(mutation.path) for mutation in result.mutations],
        "mutation_source_counts": _mutation_source_counts(result.mutations),
        "record_count": len(result.records),
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
        "source_audit": _compact_source_audit(source_audit.to_json()),
        "target_negative": {
            "caster_servant": caster_servant_result,
            "servant_entity_list": servant_list_result,
        },
        "queue_after": {key: list(value) for key, value in after.queues.items()},
        "negative_case": negative,
    }


def _owner_cleanup_case(rules: RuleBook, definition: ServantDefinitionIR) -> dict[str, Any]:
    spawned = _spawn_servant_state(rules, definition)
    state = spawned["after_state"]
    system = SummonSystem(rules)
    plan = system.plan_owner_cleanup(state, "ally:servant_owner")
    result = system.apply_remove(state, plan)
    after = MutationReducer().apply_all(state, result.mutations)
    replay = MutationReducer().replay_snapshot(state, result.mutations, after.snapshot().to_json())
    transition = _transition_from_summon_result(state, after, result)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    servant_after = after.units[spawned["servant_id"]]
    runtime = after.global_flags.get("summon_runtime") if isinstance(after.global_flags.get("summon_runtime"), dict) else {}
    entities = runtime.get("entities") if isinstance(runtime.get("entities"), dict) else {}
    checks = {
        "owner_cleanup_plan_ok": plan.ok
        and plan.operation == "owner_removed_cleanup"
        and plan.intent_id == definition.servant_definition_id,
        "owner_cleanup_source_is_policy_not_spawn": isinstance(plan.source_trace.get("owner_death_policy_sources"), list)
        and plan.source_trace != state.units[spawned["servant_id"]].flags.get("summon_source_trace"),
        "unit_removed": servant_after.flags.get("lifecycle_status") == "removed",
        "runtime_removed_audit_retained": isinstance(entities.get(spawned["servant_id"]), dict)
        and entities[spawned["servant_id"]].get("status") == "removed",
        "replay_ok": replay.ok,
        "source_audit_ok": source_audit.ok,
        "record_per_mutation": len(result.records) == len(result.mutations),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "executable",
        "servant_definition_id": definition.servant_definition_id,
        "servant_unit_id": spawned["servant_id"],
        "plan": plan.to_json(),
        "mutation_paths": [list(mutation.path) for mutation in result.mutations],
        "mutation_source_counts": _mutation_source_counts(result.mutations),
        "record_count": len(result.records),
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
        "source_audit": _compact_source_audit(source_audit.to_json()),
    }


def _missing_remove_source_case(rules: RuleBook, definition: ServantDefinitionIR) -> dict[str, Any]:
    spawned = _spawn_servant_state(rules, definition)
    state = spawned["after_state"]
    servant = state.units[spawned["servant_id"]]
    spawn_source = servant.flags.get("summon_source_trace")
    system = SummonSystem(rules)
    plan = system.plan_remove(
        state,
        spawned["servant_id"],
        "validation missing remove source",
        source_trace=spawn_source if isinstance(spawn_source, dict) else {},
        admission={"coverage_status": "executable", "remove_source_admitted": False},
    )
    result = system.apply_remove(state, plan)
    after = MutationReducer().apply_all(state, result.mutations)
    checks = {
        "plan_blocked": not plan.ok and plan.blocked_reason == "summon_remove_source_not_admitted",
        "no_mutations": not result.mutations,
        "blocked_record_process_only": bool(result.records) and result.records[0].get("process_only") is True,
        "state_unchanged": after.snapshot().to_json() == state.snapshot().to_json(),
        "spawn_source_not_reused_as_remove": plan.operation == "blocked",
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "plan": plan.to_json(),
        "record_count": len(result.records),
    }


def _wave_clear_policy_case(rules: RuleBook, intent: SummonMonsterIntentIR) -> dict[str, Any]:
    spawned_state = _spawn_summoned_monster_state(rules, intent)
    summoned_id = _first_spawned_id(spawned_state)
    summoned = spawned_state.units[summoned_id]
    definition = _select_wave_definition(rules)
    real_state = _wave_policy_state(spawned_state, summoned, definition)
    real_plan = WaveSystem(rules).plan_transition(real_state)
    counts_state = _wave_policy_state(spawned_state, _with_unit_flag(summoned, "wave_clear_policy", "counts"), definition)
    counts_plan = WaveSystem(rules).plan_transition(counts_state)
    ignore_state = _wave_policy_state(spawned_state, _with_unit_flag(summoned, "wave_clear_policy", "ignore"), definition)
    ignore_plan = WaveSystem(rules).plan_transition(ignore_state)
    ignore_result = WaveSystem(rules).apply_transition(ignore_state, ignore_plan)
    ignore_after = MutationReducer().apply_all(ignore_state, ignore_result.mutations)
    ignore_replay = MutationReducer().replay_snapshot(ignore_state, ignore_result.mutations, ignore_after.snapshot().to_json())
    real_policy = str(summoned.flags.get("wave_clear_policy") or "")
    expected_real_block = real_policy != "ignore"
    checks = {
        "wave_definition_executable": definition.coverage_status == "executable",
        "real_policy_present": real_policy in {"counts", "ignore", "blocked"},
        "real_policy_decision_matches": (
            not real_plan.ok and real_plan.blocked_reason == "active_enemy_summon_blocks_wave_clear"
            if expected_real_block
            else real_plan.ok and real_plan.blocked_reason != "active_enemy_summon_blocks_wave_clear"
        ),
        "counts_policy_blocks_wave_clear": not counts_plan.ok
        and counts_plan.blocked_reason == "active_enemy_summon_blocks_wave_clear"
        and summoned_id in counts_plan.blocking_unit_ids,
        "ignore_policy_allows_wave_clear": ignore_plan.ok
        and ignore_plan.blocked_reason != "active_enemy_summon_blocks_wave_clear"
        and summoned_id not in ignore_plan.remove_unit_ids,
        "ignore_transition_replay_ok": ignore_replay.ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "executable_policy_decision",
        "summon_intent_id": intent.summon_intent_id,
        "summoned_unit_id": summoned_id,
        "real_wave_policy": real_policy,
        "wave_definition_id": definition.wave_definition_id,
        "real_plan": _compact_wave_plan(real_plan.to_json()),
        "counts_plan": _compact_wave_plan(counts_plan.to_json()),
        "ignore_plan": _compact_wave_plan(ignore_plan.to_json()),
        "ignore_replay": {"ok": ignore_replay.ok, "errors": list(ignore_replay.errors)},
    }


def _spawn_servant_state(rules: RuleBook, definition: ServantDefinitionIR) -> dict[str, Any]:
    state = _base_servant_state(definition)
    system = SummonSystem(rules)
    plan = system.plan_spawn_servant(state, definition, owner_id="ally:servant_owner")
    result = system.apply_spawn_servant(state, plan)
    after = MutationReducer().apply_all(state, result.mutations)
    return {"before_state": state, "after_state": after, "servant_id": _first_servant_id(after)}


def _spawn_summoned_monster_state(rules: RuleBook, intent: SummonMonsterIntentIR) -> BattleState:
    state = _base_summon_state()
    system = SummonSystem(rules)
    plan = system.plan_spawn_summoned_monster(state, intent, owner_id="enemy:summoner")
    result = system.apply_spawn(state, plan)
    return MutationReducer().apply_all(state, result.mutations)


def _state_with_cleanup_residue(state: BattleState, servant_id: str) -> BattleState:
    servant = state.units[servant_id]
    flags = dict(servant.flags)
    flags["status_details"] = [
        {
            "status_id": "status:validation:summon_cleanup",
            "source_trace": servant.flags.get("summon_source_trace") if isinstance(servant.flags.get("summon_source_trace"), dict) else {},
        }
    ]
    units = dict(state.units)
    units[servant_id] = replace(servant, statuses=("status:validation:summon_cleanup",), flags=flags)
    queues = dict(state.queues)
    queues["summon_cleanup"] = (
        {
            "entry_id": "queue:removed_actor",
            "actor_id": servant_id,
            "target_ids": ["enemy:target"],
            "action_or_ability_ref": "validation:removed_actor",
        },
        {
            "entry_id": "queue:removed_target",
            "actor_id": "ally:servant_owner",
            "target_ids": [servant_id],
            "action_or_ability_ref": "validation:removed_target",
        },
        {
            "entry_id": "queue:survivor",
            "actor_id": "ally:servant_owner",
            "target_ids": ["enemy:target"],
            "action_or_ability_ref": "validation:survivor",
        },
    )
    global_flags = dict(state.global_flags)
    global_flags["turn_owner_id"] = servant_id
    return replace(state, units=units, queues=queues, global_flags=global_flags)


def _wave_policy_state(spawned_state: BattleState, summon: UnitState, definition) -> BattleState:
    stage_enemy = UnitState(
        "enemy:stage:cleared",
        "enemy",
        "monster:stage",
        hp=0.0,
        max_hp=100.0,
        flags={
            "position": 4,
            "lifecycle_status": "defeated",
            "wave_member_kind": "stage_wave_enemy",
            "wave_index": 0,
        },
    )
    return BattleState(
        units={
            "ally:probe": UnitState("ally:probe", "ally", "avatar:probe", hp=100.0, max_hp=100.0, flags={"position": 1}),
            stage_enemy.unit_id: stage_enemy,
            summon.unit_id: summon,
        },
        global_flags={
            "summon_runtime": spawned_state.global_flags.get("summon_runtime") if isinstance(spawned_state.global_flags.get("summon_runtime"), dict) else {},
            "wave_runtime": {
                "schema_version": "p1_2_wave_runtime_v1",
                "wave_definition_id": definition.wave_definition_id,
                "current_wave_index": 0,
                "total_waves": definition.wave_count,
                "status": "active",
                "current_wave_unit_ids": [stage_enemy.unit_id],
                "source_trace": definition.source.to_json(),
            },
        },
    )


def _with_unit_flag(unit: UnitState, key: str, value: JSONValue) -> UnitState:
    flags = dict(unit.flags)
    flags[key] = value
    return replace(unit, flags=flags)


def _target_result(rules: RuleBook, state: BattleState, alias: str, caster_id: str) -> dict[str, JSONValue]:
    expression = _select_target_expression(rules, alias)
    if expression is None:
        return {"ok": False, "blocked_reason": "target_expression_missing", "target_ids": []}
    return TargetSystem().resolve_target_expression(
        state,
        expression,
        caster_id=caster_id,
        owner_id=caster_id,
    ).to_json()


def _transition_from_summon_result(state: BattleState, after: BattleState, result) -> BattleTransition:
    actor_id = result.plan.actor_id or result.plan.owner_id
    command = ActionCommand(
        actor_id=actor_id,
        action_id=result.plan.operation,
        action_level=1,
        target_ids=result.plan.unit_ids,
        source="validation",
        metadata={"validation": VALIDATION_VERSION, "plan": result.plan.to_json()},
    )
    settlement = ActionSettlement(
        action_id=result.plan.operation,
        actor_id=actor_id,
        target_ids=result.plan.unit_ids,
        records=result.records,
    )
    return BattleTransition(
        transaction=ActionTransaction(
            command=command,
            before=state.snapshot(),
            events=result.events,
            mutations=result.mutations,
            settlement=settlement,
        ),
        after=after.snapshot(),
        coverage={"validation": VALIDATION_VERSION, "summon_plan_ok": result.plan.ok},
    )


def _queues_reference_unit(state: BattleState, unit_id: str) -> bool:
    for entries in state.queues.values():
        for entry in entries:
            if _json_references_unit(entry, unit_id):
                return True
    return False


def _json_references_unit(value: JSONValue, unit_id: str) -> bool:
    if value == unit_id:
        return True
    if isinstance(value, list):
        return any(_json_references_unit(item, unit_id) for item in value)
    if isinstance(value, dict):
        return any(_json_references_unit(item, unit_id) for item in value.values())
    return False


def _survivor_queue_entry_present(state: BattleState) -> bool:
    return any(
        isinstance(entry, dict) and entry.get("entry_id") == "queue:survivor"
        for entry in state.queues.get("summon_cleanup", ())
    )


def _mutation_source_counts(mutations) -> dict[str, int]:
    return dict(Counter(str(mutation.source) for mutation in mutations))


def _compact_source_audit(audit: dict[str, JSONValue]) -> dict[str, JSONValue]:
    return {
        "ok": bool(audit.get("ok")),
        "checked_mutations": int(audit.get("checked_mutations") or 0),
        "checked_records": int(audit.get("checked_records") or 0),
        "violations": audit.get("violations", []),
        "trace_origins": [
            trace.get("origin", {})
            for trace in audit.get("traces", [])
            if isinstance(trace, dict)
        ],
    }


def _compact_wave_plan(plan: dict[str, JSONValue]) -> dict[str, JSONValue]:
    return {
        "ok": bool(plan.get("ok")),
        "status": str(plan.get("status") or ""),
        "blocked_reason": str(plan.get("blocked_reason") or ""),
        "blocking_unit_ids": list(plan.get("blocking_unit_ids") or []),
        "remove_unit_ids": list(plan.get("remove_unit_ids") or []),
    }


if __name__ == "__main__":
    raise SystemExit(main())
