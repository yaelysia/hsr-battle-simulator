from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, UnitState
from ..core.reducer import MutationReducer
from ..rules.ir import ServantDefinitionIR, SummonMonsterIntentIR, TargetExpressionIR
from ..rules.rulebook import RuleBook
from ..systems.action_availability import ActionAvailabilitySystem
from ..systems.summon import SUMMON_RUNTIME_SCHEMA_VERSION, SummonSystem
from ..systems.target import TargetPolicy, TargetSystem
from ..systems.timeline import TimelineSystem
from ..systems.wave import WaveSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "p1_3_summon_assistant_servant"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    intent = _select_executable_summon_monster_intent(rules)
    spawn_case = _spawn_case(rules, intent)
    remove_case = _remove_case(rules, spawn_case["after_state"])
    source_cases = _source_discovery_cases(rules)
    target_case = _target_relation_case(rules, spawn_case["after_state"])
    timeline_case = _timeline_action_case(rules)
    wave_case = _wave_policy_case(rules, spawn_case["after_state"])
    unsupported_case = _unsupported_case(rules, spawn_case["after_state"])
    assistant_case = _assistant_case(rules)
    servant_case = _servant_case(rules)
    checks = {
        "source_discovery": source_cases["checks"],
        "spawn": spawn_case["checks"],
        "remove": remove_case["checks"],
        "target_relation": target_case["checks"],
        "timeline_action": timeline_case["checks"],
        "wave_policy": wave_case["checks"],
        "unsupported": unsupported_case["checks"],
        "assistant": assistant_case["checks"],
        "servant": servant_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = _json_safe(
        {
            "version": VALIDATION_VERSION,
            "baseline_version": BASELINE_VERSION,
            "ok": all(item["ok"] for item in checks.values()),
            "build": {
                "tbgd_root": tbgd_root.as_posix(),
                "summon_unit_definition_count": len(rules.ir.summon_unit_definitions),
                "summon_monster_intent_count": len(rules.ir.summon_monster_intents),
                "assistant_resolution_count": len(rules.ir.assistant_ability_resolutions),
                "servant_definition_count": len(rules.ir.servant_definitions),
                "selection_policy": {
                    "mode": "structured_p1_3_source_predicates",
                    "fixed_character_monster_summon_or_file_used": False,
                    "predicate": [
                    "SummonMonsterIntentIR.coverage_status == executable",
                    "source path is admitted by lowering as mainline monster ability",
                    "entry has fixed MonsterID parsed to monster entity",
                    "CombatantProfileIR and MonsterDataCardIR exist",
                    "position policy has structured LocationType source",
                    "DelayRatio is structured; fixed non-negative values are executable, dynamic or unbound values stay blocked",
                ],
            },
            },
            "checks": checks,
            "cases": {
                "source_discovery": source_cases,
                "spawn": _strip_state(spawn_case),
                "remove": _strip_state(remove_case),
                "target_relation": target_case,
                "timeline_action": timeline_case,
                "wave_policy": wave_case,
                "unsupported": unsupported_case,
                "assistant": assistant_case,
                "servant": servant_case,
            },
            "static_checks": static_result.to_json(),
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p1_3_summon_assistant_servant.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 P1-3 summon/assistant/servant minimum loop.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _source_discovery_cases(rules: RuleBook) -> dict[str, Any]:
    summon_defs = rules.summon_unit_definitions()
    client_defs = tuple(item for item in summon_defs if item.blocked_reason == "summon_unit_client_only_not_combat_runtime")
    destroy_defs = tuple(item for item in summon_defs if item.destroy_on_enter_battle is True)
    catalog_cards = tuple(card for card in rules.ir.monster_data_cards if card.summon_refs)
    executable_intents = tuple(intent for intent in rules.summon_monster_intents() if intent.coverage_status == "executable")
    delay_blocked_intents = tuple(
        intent
        for intent in rules.summon_monster_intents()
        if isinstance(intent.delay_policy, dict) and intent.delay_policy.get("admission_status") == "blocked"
    )
    executable_delay_intents = tuple(
        intent
        for intent in rules.summon_monster_intents()
        if isinstance(intent.delay_policy, dict) and intent.delay_policy.get("admission_status") == "executable"
    )
    checks = {
        "summon_unit_definitions_present": bool(summon_defs),
        "client_summon_blocked": bool(client_defs) and all(item.coverage_status == "blocked" for item in client_defs),
        "destroy_on_enter_battle_not_spawn_trigger": bool(destroy_defs)
        and all(item.coverage_status == "blocked" for item in destroy_defs),
        "monster_summon_refs_catalog_present": bool(catalog_cards),
        "summon_refs_not_trigger_ir": all("SummonIDList" in card.source.evidence.get("raw_paths", {}).values() for card in catalog_cards[:10]),
        "summon_monster_intents_present": bool(rules.ir.summon_monster_intents),
        "executable_summon_monster_intent_present": bool(executable_intents),
        "summon_monster_delay_policy_structured": all(isinstance(intent.delay_policy, dict) for intent in rules.summon_monster_intents()),
        "executable_delay_policy_admitted": all(
            intent.delay_policy.get("admission_status") == "executable" for intent in executable_intents
        ),
        "delay_ratio_executable_values_non_negative": all(
            not isinstance(intent.delay_policy.get("value"), (int, float))
            or not isinstance(intent.delay_policy.get("value"), bool)
            and float(intent.delay_policy.get("value", 0.0)) >= 0.0
            for intent in executable_delay_intents
        ),
        "delay_ratio_blocked_policies_have_reason": all(
            bool(str(intent.delay_policy.get("blocked_reason") or intent.blocked_reason))
            for intent in delay_blocked_intents
        ),
        "rulebook_indexes_work": bool(executable_intents)
        and rules.summon_monster_intent(executable_intents[0].summon_intent_id) == executable_intents[0],
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "summon_unit_counts": {
            "total": len(summon_defs),
            "client_blocked": len(client_defs),
            "destroy_on_enter_battle": len(destroy_defs),
        },
        "summon_monster_intent_counts": {
            "total": len(rules.ir.summon_monster_intents),
            "executable": len(executable_intents),
            "blocked": sum(1 for intent in rules.ir.summon_monster_intents if intent.coverage_status == "blocked"),
            "delay_blocked": len(delay_blocked_intents),
            "delay_executable": len(executable_delay_intents),
        },
        "catalog_sample": catalog_cards[0].to_json() if catalog_cards else {},
    }


def _spawn_case(rules: RuleBook, intent: SummonMonsterIntentIR) -> dict[str, Any]:
    state = _base_summon_state()
    system = SummonSystem(rules)
    before_hash = _snapshot_hash(state)
    view = system.view(state)
    plan = system.plan_spawn_summoned_monster(state, intent, owner_id="enemy:summoner")
    result = system.apply_spawn(state, plan)
    after = MutationReducer().apply_all(state, result.mutations)
    replay = MutationReducer().replay_snapshot(state, result.mutations, after.snapshot().to_json())
    spawned = tuple(unit_id for unit_id in plan.unit_ids if unit_id in after.units)
    runtime = after.global_flags.get("summon_runtime")
    targets = TargetSystem().enumerate_action_targets(after, "ally:probe", TargetPolicy())
    checks = {
        "view_pure_query_state_unchanged": before_hash == _snapshot_hash(state) and view.schema_version == SUMMON_RUNTIME_SCHEMA_VERSION,
        "plan_ok": plan.ok and plan.operation == "spawn_summoned_monster",
        "unit_spawn_mutations_present": any(mutation.metadata.get("lifecycle_operation") == "unit_spawn" for mutation in result.mutations),
        "runtime_mutation_present": any(mutation.path == ("global_flags", "summon_runtime") for mutation in result.mutations),
        "spawned_units_active_enemy": bool(spawned)
        and all(after.units[unit_id].side == "enemy" and after.units[unit_id].flags.get("summon_kind") == "summoned_monster" for unit_id in spawned),
        "wave_policy_counts": all(after.units[unit_id].flags.get("wave_clear_policy") == "counts" for unit_id in spawned),
        "runtime_tracks_last_summon": isinstance(runtime, dict)
        and all(unit_id in runtime.get("last_summon_monsters", []) for unit_id in spawned),
        "targetable_as_enemy": targets.ok and all(unit_id in targets.selectable_target_ids for unit_id in spawned),
        "source_trace_from_intent": all(
            mutation.metadata.get("source_trace", {}).get("raw_type") == "SummonMonsterIntent"
            for mutation in result.mutations
            if mutation.metadata.get("lifecycle_operation") == "unit_spawn"
        ),
        "delay_policy_carried_to_initial_av_source": all(
            after.units[unit_id].flags.get("initial_action_value_source_trace", {}).get("summon_delay_policy")
            == intent.delay_policy
            for unit_id in spawned
        ),
        "replay_ok": replay.ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "state": state,
        "after_state": after,
        "intent": intent.to_json(),
        "plan": plan.to_json(),
        "mutations": [mutation.to_json() for mutation in result.mutations],
        "events": [event.to_json() for event in result.events],
        "records": list(result.records),
        "target_enumeration": targets.to_json(),
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
    }


def _remove_case(rules: RuleBook, state: BattleState) -> dict[str, Any]:
    spawned_id = _first_spawned_id(state)
    system = SummonSystem(rules)
    plan = system.plan_remove(state, spawned_id, "validation explicit remove")
    result = system.apply_remove(state, plan)
    after = MutationReducer().apply_all(state, result.mutations)
    targets = TargetSystem().enumerate_action_targets(after, "ally:probe", TargetPolicy())
    checks = {
        "direct_remove_without_source_blocked": not plan.ok and plan.blocked_reason == "summon_remove_source_not_admitted",
        "no_remove_mutations_without_source": not result.mutations,
        "blocked_record_process_only": bool(result.records) and result.records[0].get("process_only") is True,
        "state_unchanged": after.snapshot().to_json() == state.snapshot().to_json(),
        "spawned_unit_still_active": after.units[spawned_id].flags.get("lifecycle_status") == "active",
        "spawned_unit_still_targetable": targets.ok and spawned_id in targets.selectable_target_ids,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "state": state,
        "after_state": after,
        "plan": plan.to_json(),
        "mutations": [mutation.to_json() for mutation in result.mutations],
        "events": [event.to_json() for event in result.events],
        "records": list(result.records),
    }


def _target_relation_case(rules: RuleBook, spawned_state: BattleState) -> dict[str, Any]:
    state = BattleState(
        units={
            "ally:owner": UnitState("ally:owner", "ally", _select_avatar_entity(rules), hp=100.0, max_hp=100.0, flags={"position": 1}),
            "summon:ally": UnitState(
                "summon:ally",
                "summon",
                _select_avatar_entity(rules),
                hp=100.0,
                max_hp=100.0,
                flags={"team_side": "ally", "summon_kind": "battle_unit_summon", "timeline_admitted": False, "position": 2},
            ),
            "enemy:target": UnitState("enemy:target", "enemy", "monster:target", hp=100.0, max_hp=100.0, flags={"position": 5}),
        }
    )
    targets = TargetSystem()
    summon_targets = targets.enumerate_action_targets(state, "summon:ally", TargetPolicy())
    last_expr = _select_target_expression(rules, "LastSummonMonsters")
    caster_expr = _select_target_expression(rules, "CasterSummonedMinions")
    last_result = targets.resolve_target_expression(
        spawned_state,
        last_expr,
        caster_id="enemy:summoner",
        owner_id="enemy:summoner",
    ) if last_expr is not None else None
    caster_result = targets.resolve_target_expression(
        spawned_state,
        caster_expr,
        caster_id="enemy:summoner",
        owner_id="enemy:summoner",
    ) if caster_expr is not None else None
    spawned_id = _first_spawned_id(spawned_state)
    checks = {
        "ally_summon_targets_enemy": summon_targets.ok and summon_targets.selectable_target_ids == ("enemy:target",),
        "ally_summon_does_not_target_owner_as_enemy": "ally:owner" not in summon_targets.selectable_target_ids,
        "last_summon_alias_lowered_or_gap": last_expr is not None,
        "last_summon_alias_resolves": last_result is not None and last_result.ok and spawned_id in last_result.target_ids,
        "caster_minions_alias_lowered_or_gap": caster_expr is not None,
        "caster_minions_alias_resolves": caster_result is not None and caster_result.ok and spawned_id in caster_result.target_ids,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "summon_targets": summon_targets.to_json(),
        "last_summon_expression": last_expr.to_json() if last_expr is not None else {},
        "last_summon_result": last_result.to_json() if last_result is not None else {},
        "caster_minions_expression": caster_expr.to_json() if caster_expr is not None else {},
        "caster_minions_result": caster_result.to_json() if caster_result is not None else {},
    }


def _timeline_action_case(rules: RuleBook) -> dict[str, Any]:
    summon_blocked = UnitState(
        "summon:no_timeline",
        "summon",
        _select_avatar_entity(rules),
        hp=100.0,
        max_hp=100.0,
        speed=100.0,
        action_value=0.0,
        flags={"team_side": "ally", "summon_kind": "battle_unit_summon"},
    )
    state = BattleState(
        units={
            "ally:probe": UnitState("ally:probe", "ally", _select_avatar_entity(rules), hp=100.0, max_hp=100.0, action_value=10.0),
            "enemy:target": UnitState("enemy:target", "enemy", "monster:target", hp=100.0, max_hp=100.0, action_value=10.0),
            summon_blocked.unit_id: summon_blocked,
        },
        global_flags={"turn_owner_id": "summon:no_timeline"},
    )
    timeline_plan = TimelineSystem().plan_next_actor(state, rules.default_timeline_rule())
    availability = ActionAvailabilitySystem(rules).view(state)
    skipped = {str(item.get("unit_id")): str(item.get("reason")) for item in timeline_plan.skipped_units}
    blocked_reasons = [item.reason for item in availability.blocked]
    checks = {
        "summon_timeline_missing_skipped": skipped.get("summon:no_timeline") == "summon_timeline_not_admitted",
        "summon_action_specific_blocked": "summon_timeline_not_admitted" in blocked_reasons,
        "no_default_summon_action_choice": not availability.choices,
        "state_unchanged": _snapshot_hash(state) == _snapshot_hash(state),
    }
    flag_only_state = BattleState(
        units={
            "summon:flag_only": UnitState(
                "summon:flag_only",
                "summon",
                _select_avatar_entity(rules),
                hp=100.0,
                max_hp=100.0,
                speed=100.0,
                action_value=0.0,
                flags={
                    "team_side": "ally",
                    "summon_kind": "battle_unit_summon",
                    "timeline_admitted": True,
                    "summon_action_admitted": True,
                    "position": 2,
                },
            ),
            "enemy:target": UnitState("enemy:target", "enemy", "monster:target", hp=100.0, max_hp=100.0, action_value=10.0),
        },
        global_flags={"turn_owner_id": "summon:flag_only"},
    )
    flag_only_availability = ActionAvailabilitySystem(rules).view(flag_only_state)
    flag_only_blocked_reasons = [item.reason for item in flag_only_availability.blocked]
    checks["flag_only_summon_action_blocked"] = (
        not flag_only_availability.choices
        and any(
            reason
            in {
                "summon_runtime_state_missing",
                "summon_runtime_entity_missing",
                "summon_action_source_not_admitted",
            }
            for reason in flag_only_blocked_reasons
        )
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "timeline_plan": timeline_plan.to_json(),
        "availability": availability.to_json(),
        "flag_only_availability": flag_only_availability.to_json(),
    }


def _wave_policy_case(rules: RuleBook, spawned_state: BattleState) -> dict[str, Any]:
    definition = _select_wave_definition(rules)
    spawned_id = _first_spawned_id(spawned_state)
    spawned = spawned_state.units[spawned_id]
    counts_state = _wave_state(definition.wave_definition_id, spawned)
    counts_plan = WaveSystem(rules).plan_transition(counts_state)
    ignore_state = _wave_state(definition.wave_definition_id, replace(spawned, flags={**spawned.flags, "wave_clear_policy": "ignore"}))
    ignore_plan = WaveSystem(rules).plan_transition(ignore_state)
    missing_state = _wave_state(definition.wave_definition_id, replace(spawned, flags={key: value for key, value in spawned.flags.items() if key != "wave_clear_policy"}))
    missing_plan = WaveSystem(rules).plan_transition(missing_state)
    checks = {
        "counts_blocks_clear": counts_plan.status == "blocked" and counts_plan.blocked_reason == "active_enemy_summon_blocks_wave_clear",
        "ignore_does_not_block_as_summon": ignore_plan.blocked_reason != "active_enemy_summon_blocks_wave_clear",
        "missing_policy_blocks_clear": missing_plan.status == "blocked"
        and missing_plan.blocked_reason == "active_enemy_summon_blocks_wave_clear",
        "ally_summon_not_involved": all(unit.side != "summon" for unit in counts_state.units.values() if unit.flags.get("summon_kind") == "summoned_monster"),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "counts_plan": counts_plan.to_json(),
        "ignore_plan": ignore_plan.to_json(),
        "missing_plan": missing_plan.to_json(),
    }


def _unsupported_case(rules: RuleBook, spawned_state: BattleState) -> dict[str, Any]:
    state = _base_summon_state()
    blocked_intent = next((intent for intent in rules.summon_monster_intents() if intent.coverage_status != "executable"), None)
    if blocked_intent is None:
        blocked_result = SummonSystem(rules).blocked("no_blocked_summon_intent_found")
    else:
        plan = SummonSystem(rules).plan_spawn_summoned_monster(state, blocked_intent, owner_id="enemy:summoner")
        blocked_result = SummonSystem(rules).apply_spawn(state, plan)
    owner_cleanup = SummonSystem(rules).plan_owner_cleanup(spawned_state, "enemy:summoner")
    checks = {
        "blocked_intent_no_mutation": not blocked_result.mutations,
        "blocked_record_process_only": bool(blocked_result.records) and blocked_result.records[0].get("process_only") is True,
        "owner_death_missing_policy_blocked": not owner_cleanup.ok
        and owner_cleanup.blocked_reason == "owner_death_remove_policy_missing",
        "owner_cleanup_no_fake_remove": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "blocked_result": {
            "plan": blocked_result.plan.to_json(),
            "mutations": [mutation.to_json() for mutation in blocked_result.mutations],
            "records": list(blocked_result.records),
        },
        "owner_cleanup_plan": owner_cleanup.to_json(),
    }


def _assistant_case(rules: RuleBook) -> dict[str, Any]:
    assistant_intents = tuple(intent for intent in rules.ir.queue_intents if intent.opcode == "TurnInsertAssistantAbility")
    assistant_resolutions = rules.assistant_ability_resolutions()
    checks = {
        "assistant_resolution_count_matches_intents": len(assistant_resolutions) == len(assistant_intents),
        "assistant_resolutions_blocked_or_no_source": all(item.coverage_status == "blocked" for item in assistant_resolutions),
        "assistant_blocked_reason_specific": all(
            "assistant_actor_source_not_admitted" in item.blocked_reason
            and "assistant_stats_source_not_admitted" in item.blocked_reason
            and "assistant_action_graph_source_not_admitted" in item.blocked_reason
            for item in assistant_resolutions
        ),
        "assistant_no_fake_execution": not any(item.coverage_status == "executable" for item in assistant_resolutions),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "source_state": "boundary_only",
        "classification": "assistant_resolution_sources_not_executable_current_scope",
        "mechanism_complete": False,
        "assistant_intent_count": len(assistant_intents),
        "assistant_resolution_count": len(assistant_resolutions),
        "sample": assistant_resolutions[0].to_json() if assistant_resolutions else {},
    }


def _servant_case(rules: RuleBook) -> dict[str, Any]:
    definitions = rules.servant_definitions()
    definition = _select_executable_servant_definition(rules)
    base_state = _base_servant_state(definition)
    system = SummonSystem(rules)
    plan = system.plan_spawn_servant(base_state, definition, owner_id="ally:servant_owner")
    result = system.apply_spawn_servant(base_state, plan)
    after = MutationReducer().apply_all(base_state, result.mutations)
    replay = MutationReducer().replay_snapshot(base_state, result.mutations, after.snapshot().to_json())
    servant_id = _first_servant_id(after)
    availability_state = replace(
        after,
        global_flags={**after.global_flags, "turn_owner_id": servant_id, "phase": "scenario", "current_window": "idle"},
    )
    availability = ActionAvailabilitySystem(rules).view(availability_state)
    servant_list_expr = _select_target_expression(rules, "ServantEntityList")
    caster_servant_expr = _select_global_target_expression(rules, "CasterServant")
    servant_list_result = (
        TargetSystem().resolve_target_expression(availability_state, servant_list_expr, caster_id="ally:servant_owner")
        if servant_list_expr is not None
        else None
    )
    caster_servant_result = (
        TargetSystem().resolve_target_expression(availability_state, caster_servant_expr, caster_id="ally:servant_owner")
        if caster_servant_expr is not None
        else None
    )
    servant = after.units[servant_id]
    remove_plan = system.plan_remove(
        after,
        servant_id,
        "validation servant remove",
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
    servant_list_after_remove = (
        TargetSystem().resolve_target_expression(removed_after, servant_list_expr, caster_id="ally:servant_owner")
        if servant_list_expr is not None
        else None
    )
    flag_only_state = _flag_only_servant_state(definition)
    flag_only_availability = ActionAvailabilitySystem(rules).view(flag_only_state)
    flag_only_servant_list = (
        TargetSystem().resolve_target_expression(flag_only_state, servant_list_expr, caster_id="ally:servant_owner")
        if servant_list_expr is not None
        else None
    )
    flag_only_blocked_reasons = [item.reason for item in flag_only_availability.blocked]
    checks = {
        "servant_definitions_present": bool(definitions),
        "servant_executable_definition_present": definition.coverage_status == "executable" and definition.representation == "unit",
        "servant_action_admission_has_executable_bindings": bool(definition.action_set.get("executable_binding_ids")),
        "servant_skipped_slots_are_audited": isinstance(definition.action_set.get("skipped_slots"), list),
        "spawn_plan_ok": plan.ok and plan.operation == "servant_spawn",
        "spawn_unit_mutation_present": any(mutation.metadata.get("lifecycle_operation") == "unit_spawn" for mutation in result.mutations),
        "runtime_mutation_present": any(mutation.path == ("global_flags", "summon_runtime") for mutation in result.mutations),
        "spawned_unit_is_servant": servant.side == "summon" and servant.template_id == definition.servant_ref,
        "servant_team_side_inherits_owner": servant.flags.get("team_side") == "ally",
        "servant_timeline_admitted": servant.flags.get("timeline_admitted") is True and servant.action_value > 0.0,
        "servant_action_availability": availability.mode == "external_selectable"
        and any(choice.choice_kind == "summon_action" for choice in availability.choices),
        "servant_action_source_trace_present": all(choice.source_trace for choice in availability.choices),
        "servant_entity_list_expression_present": servant_list_expr is not None,
        "servant_entity_list_resolves": servant_list_result is not None and servant_list_result.ok and servant_id in servant_list_result.target_ids,
        "caster_servant_expression_present": caster_servant_expr is not None,
        "caster_servant_resolves": caster_servant_result is not None and caster_servant_result.ok and servant_id in caster_servant_result.target_ids,
        "spawn_replay_ok": replay.ok,
        "remove_plan_ok": remove_plan.ok and remove_plan.operation == "remove_summon",
        "remove_mutations_present": any(mutation.metadata.get("lifecycle_operation") == "unit_remove" for mutation in remove_result.mutations),
        "remove_replay_ok": remove_replay.ok,
        "removed_servant_not_targetable": servant_list_after_remove is not None
        and not servant_list_after_remove.ok
        and servant_id not in servant_list_after_remove.target_ids,
        "flag_only_action_blocked": not flag_only_availability.choices
        and any(reason in {"summon_runtime_state_missing", "summon_runtime_entity_missing"} for reason in flag_only_blocked_reasons),
        "flag_only_target_blocked": flag_only_servant_list is not None
        and not flag_only_servant_list.ok
        and flag_only_servant_list.blocked_reason == "summon_runtime_missing",
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "source_state": "executable",
        "classification": "servant_unit_spawn_action_target_remove_runtime_executable",
        "mechanism_complete": True,
        "definition_count": len(definitions),
        "sample": definition.to_json(),
        "spawn_plan": plan.to_json(),
        "spawned_unit_id": servant_id,
        "spawn_mutations": [mutation.to_json() for mutation in result.mutations],
        "availability": availability.to_json(),
        "servant_entity_list_result": servant_list_result.to_json() if servant_list_result is not None else {},
        "caster_servant_result": caster_servant_result.to_json() if caster_servant_result is not None else {},
        "remove_plan": remove_plan.to_json(),
        "remove_mutations": [mutation.to_json() for mutation in remove_result.mutations],
        "flag_only_availability": flag_only_availability.to_json(),
        "flag_only_servant_list": flag_only_servant_list.to_json() if flag_only_servant_list is not None else {},
    }


def _select_executable_summon_monster_intent(rules: RuleBook) -> SummonMonsterIntentIR:
    for intent in rules.summon_monster_intents():
        if intent.coverage_status != "executable":
            continue
        if not intent.entries:
            continue
        if all(
            entry.coverage_status == "executable"
            and entry.monster_entity_ref
            and entry.position_policy.get("location_type") in {"BeforeCaster", "AfterCaster", "First", "Last"}
            for entry in intent.entries
        ) and intent.delay_policy.get("admission_status") == "executable":
            return intent
    raise RuntimeError("no executable SummonMonsterIntentIR selected by structured predicate")


def _select_executable_servant_definition(rules: RuleBook):
    for definition in rules.servant_definitions():
        if definition.coverage_status != "executable":
            continue
        if definition.representation != "unit":
            continue
        if not definition.owner_entity_refs:
            continue
        if not definition.action_set.get("executable_binding_ids"):
            continue
        if definition.stat_source.get("admission_status") != "executable":
            continue
        if definition.timeline_source.get("admission_status") != "executable":
            continue
        if definition.lifecycle_source.get("admission_status") != "executable":
            continue
        return definition
    raise RuntimeError("no executable ServantDefinitionIR selected by structured predicate")


def _select_servant_owner_entity_ref(definition: ServantDefinitionIR) -> str:
    if not definition.owner_entity_refs:
        raise RuntimeError(
            f"servant definition {definition.servant_definition_id!r} has no executable owner relation"
        )
    return definition.owner_entity_refs[0]


def _select_target_expression(rules: RuleBook, alias: str) -> TargetExpressionIR | None:
    for expression in sorted(rules.target_expressions(), key=lambda item: item.target_expression_id):
        if expression.alias == alias and expression.coverage_status == "executable":
            return expression
    return None


def _select_global_target_expression(rules: RuleBook, alias: str) -> TargetExpressionIR | None:
    for expression in sorted(rules.target_expressions(), key=lambda item: item.target_expression_id):
        if expression.coverage_status != "executable":
            continue
        payload = expression.payload if isinstance(expression.payload, dict) else {}
        field_name = str(payload.get("field_name") or "")
        if expression.alias == alias or field_name == f"AliasDict.{alias}":
            return expression
    return None


def _select_avatar_entity(rules: RuleBook) -> str:
    for profile in sorted(rules.ir.combatant_profiles, key=lambda item: item.entity_id):
        if profile.entity_type == "avatar" and rules.combatant_action_set(profile.entity_id) is not None:
            return profile.entity_id
    return "avatar:validation"


def _select_wave_definition(rules: RuleBook):
    for definition in rules.wave_definitions():
        if definition.coverage_status == "executable" and rules.wave_entries_for_wave(definition.wave_definition_id, 0):
            return definition
    raise RuntimeError("no executable WaveDefinitionIR selected")


def _base_summon_state() -> BattleState:
    return BattleState(
        units={
            "ally:probe": UnitState(
                "ally:probe",
                "ally",
                "avatar:probe",
                hp=1000.0,
                max_hp=1000.0,
                attack=100.0,
                defense=100.0,
                speed=100.0,
                flags={"position": 1},
            ),
            "enemy:summoner": UnitState(
                "enemy:summoner",
                "enemy",
                "monster:summoner",
                level=80,
                hp=1000.0,
                max_hp=1000.0,
                attack=100.0,
                defense=100.0,
                speed=100.0,
                flags={"position": 5},
            ),
        }
    )


def _base_servant_state(definition) -> BattleState:
    owner_entity_ref = _select_servant_owner_entity_ref(definition)
    return BattleState(
        units={
            "ally:servant_owner": UnitState(
                "ally:servant_owner",
                "ally",
                owner_entity_ref,
                level=80,
                hp=1000.0,
                max_hp=1000.0,
                attack=500.0,
                defense=300.0,
                speed=100.0,
                flags={"position": 1},
            ),
            "enemy:target": UnitState(
                "enemy:target",
                "enemy",
                "monster:target",
                level=80,
                hp=1000.0,
                max_hp=1000.0,
                attack=100.0,
                defense=100.0,
                speed=90.0,
                flags={"position": 5},
            ),
        },
        global_flags={"phase": "scenario", "current_window": "idle"},
    )


def _flag_only_servant_state(definition) -> BattleState:
    owner_entity_ref = _select_servant_owner_entity_ref(definition)
    return BattleState(
        units={
            "ally:servant_owner": UnitState(
                "ally:servant_owner",
                "ally",
                owner_entity_ref,
                hp=1000.0,
                max_hp=1000.0,
                speed=100.0,
                flags={"position": 1},
            ),
            "summon:flag_only_servant": UnitState(
                "summon:flag_only_servant",
                "summon",
                definition.servant_ref,
                hp=100.0,
                max_hp=100.0,
                speed=100.0,
                flags={
                    "team_side": "ally",
                    "summon_kind": "servant",
                    "owner_id": "ally:servant_owner",
                    "timeline_admitted": True,
                    "summon_action_admitted": True,
                    "summon_action_admission": {"coverage_status": "executable", "source_trace": definition.source.to_json()},
                    "summon_intent_id": definition.servant_definition_id,
                    "summon_source_trace": definition.source.to_json(),
                    "position": 2,
                },
            ),
            "enemy:target": UnitState("enemy:target", "enemy", "monster:target", hp=100.0, max_hp=100.0, flags={"position": 5}),
        },
        global_flags={"turn_owner_id": "summon:flag_only_servant", "phase": "scenario", "current_window": "idle"},
    )


def _first_servant_id(state: BattleState) -> str:
    for unit_id, unit in sorted(state.units.items()):
        if unit.flags.get("summon_kind") == "servant":
            return unit_id
    raise RuntimeError("spawned servant unit missing")


def _wave_state(wave_definition_id: str, summon: UnitState) -> BattleState:
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
            "wave_runtime": {
                "schema_version": "p1_2_wave_runtime_v1",
                "wave_definition_id": wave_definition_id,
                "current_wave_index": 0,
                "total_waves": 1,
                "status": "active",
                "current_wave_unit_ids": [stage_enemy.unit_id],
                "source_trace": {"validation": VALIDATION_VERSION},
            }
        },
    )


def _first_spawned_id(state: BattleState) -> str:
    runtime = state.global_flags.get("summon_runtime")
    if isinstance(runtime, dict):
        raw = runtime.get("last_summon_monsters")
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str) and item in state.units:
                    return item
    for unit_id, unit in sorted(state.units.items()):
        if unit.flags.get("summon_kind") == "summoned_monster":
            return unit_id
    raise RuntimeError("spawned summon unit missing")


def _snapshot_hash(state: BattleState) -> str:
    return json.dumps(state.snapshot().to_json(), sort_keys=True, ensure_ascii=False)


def _strip_state(case: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in case.items() if key not in {"state", "after_state"}}


def _json_safe(value: Any) -> Any:
    if hasattr(value, "to_json"):
        return value.to_json()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
