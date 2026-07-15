from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, GameEvent, UnitState
from ..core.reducer import MutationReducer
from ..rules.ir import WaveDefinitionIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.schema import PanelInput, RouteStepSpec, ScenarioSpec, UnitSpec
from ..systems.action_availability import ActionAvailabilitySystem
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.scheduler import CombatScheduler
from ..systems.status import StatusSystem
from ..systems.target import TargetPolicy, TargetSystem
from ..systems.timeline import TimelineSystem
from ..systems.wave import WaveSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "p1_2_wave_system"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    candidate = _select_wave_definition(rules)
    action_ref, action_level = _select_action_definition(rules)
    setup_case = _initial_setup_case(rules, candidate, action_ref, action_level)
    start_case = _start_case(rules, setup_case["state"])
    started_state = start_case["after_state"]
    pure_query_case = _pure_query_case(rules, started_state)
    advance_case = _advance_case(rules, started_state)
    victory_case = _victory_case(rules, advance_case["after_state"])
    defeat_case = _defeat_case(rules, started_state)
    blocked_case = _blocked_case(rules, started_state, candidate)
    event_case = _event_case(rules, advance_case["after_state"], advance_case["events"])
    scheduler_case = _scheduler_case(rules, started_state)
    checks = {
        "lowering": _lowering_case(rules, candidate)["checks"],
        "initial_setup": setup_case["checks"],
        "initial_wave_start": start_case["checks"],
        "pure_query": pure_query_case["checks"],
        "advance": advance_case["checks"],
        "victory": victory_case["checks"],
        "defeat": defeat_case["checks"],
        "blocked": blocked_case["checks"],
        "events": event_case["checks"],
        "scheduler": scheduler_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = _json_safe(
        {
            "version": VALIDATION_VERSION,
            "baseline_version": BASELINE_VERSION,
            "ok": all(item["ok"] for item in checks.values()),
            "build": {
                "tbgd_root": tbgd_root.as_posix(),
                "wave_definition_count": len(ir.wave_definitions),
                "selection_policy": {
                    "mode": "structured_wave_definition_predicate",
                    "fixed_stage_id_or_monster_id_used_for_selection": False,
                    "predicate": [
                        "WaveDefinitionIR.coverage_status == executable",
                        "wave_count >= 2",
                        "wave 0 and wave 1 have executable WaveMonsterEntryIR entries",
                        "entry has monster entity, combatant profile and monster data card source",
                    ],
                },
            },
            "checks": checks,
            "cases": {
                "lowering": _lowering_case(rules, candidate),
                "initial_setup": _strip_state(setup_case),
                "initial_wave_start": _strip_state(start_case),
                "pure_query": pure_query_case,
                "advance": _strip_state(advance_case),
                "victory": _strip_state(victory_case),
                "defeat": _strip_state(defeat_case),
                "blocked": blocked_case,
                "events": event_case,
                "scheduler": _strip_state(scheduler_case),
            },
            "static_checks": static_result.to_json(),
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p1_2_wave_system.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 P1-2 wave system.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _lowering_case(rules: RuleBook, definition: WaveDefinitionIR) -> dict[str, Any]:
    entries = definition.entries
    checks = {
        "candidate_selected": bool(definition.wave_definition_id),
        "candidate_multi_wave": definition.wave_count >= 2,
        "candidate_executable": definition.coverage_status == "executable",
        "entries_have_stage_config_source": all(entry.source.source_path.endswith("StageConfig.json") for entry in entries),
        "entries_have_monster_sources": all(bool(entry.monster_entity_ref and entry.monster_raw_id) for entry in entries),
        "rulebook_stage_lookup": rules.wave_definition_for_stage(definition.stage_id) == definition,
        "rulebook_wave_entries_sorted": tuple(entry.entry_id for entry in rules.wave_entries_for_wave(definition.wave_definition_id, 0))
        == tuple(entry.entry_id for entry in sorted(rules.wave_entries_for_wave(definition.wave_definition_id, 0), key=lambda item: (item.position, item.entry_id))),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "definition": definition.to_json()}


def _initial_setup_case(
    rules: RuleBook,
    definition: WaveDefinitionIR,
    action_ref: str,
    action_level: int,
) -> dict[str, Any]:
    first_unit_id = _wave_unit_id(definition, rules.wave_entries_for_wave(definition.wave_definition_id, 0)[0])
    scenario = ScenarioSpec(
        scenario_id="validation:p1_2:wave_setup",
        version=VALIDATION_VERSION,
        units=(
            UnitSpec(
                unit_id="ally:probe",
                side="ally",
                build_mode="kernel_fixture",
                entity_ref=_select_avatar_entity(rules),
                panel=PanelInput(
                    explicit_fields=("max_hp", "hp", "attack", "defense", "speed", "energy", "max_energy", "flags"),
                    max_hp=1000.0,
                    hp=1000.0,
                    attack=100.0,
                    defense=100.0,
                    speed=100.0,
                    energy=60.0,
                    max_energy=120.0,
                ),
            ),
        ),
        route=(
            RouteStepSpec(
                actor_id="ally:probe",
                action_ref=action_ref,
                action_level=action_level,
                target_ids=(first_unit_id,),
            ),
        ),
        wave_definition_ref=definition.wave_definition_id,
        wave_index=0,
    )
    result = ScenarioStateBuilder(rules).build(scenario)
    state = result.state
    snapshot = state.snapshot().to_json()
    runtime = state.global_flags.get("wave_runtime")
    current_ids = tuple(runtime.get("current_wave_unit_ids", ())) if isinstance(runtime, dict) else ()
    next_ids = tuple(_wave_unit_id(definition, entry) for entry in rules.wave_entries_for_wave(definition.wave_definition_id, 1))
    checks = {
        "wave_runtime_present": isinstance(runtime, dict)
        and runtime.get("schema_version") == "p1_2_wave_runtime_v1"
        and runtime.get("status") == "pending_start",
        "current_wave_units_spawned": all(unit_id in state.units for unit_id in current_ids),
        "current_wave_units_active": all(snapshot["units"][unit_id]["lifecycle_status"] == "active" for unit_id in current_ids),
        "next_wave_units_absent": all(unit_id not in state.units for unit_id in next_ids),
        "membership_flags_present": all(state.units[unit_id].flags.get("wave_member_kind") == "stage_wave_enemy" for unit_id in current_ids),
        "action_value_source_present": all(bool(state.units[unit_id].flags.get("initial_action_value_source_trace")) for unit_id in current_ids),
        "route_target_generated_before_identity_validation": result.commands[0].target_ids == (first_unit_id,),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "state": state,
        "snapshot": snapshot,
        "source_traces": result.source_traces,
    }


def _start_case(rules: RuleBook, state: BattleState) -> dict[str, Any]:
    before_hash = _snapshot_hash(state)
    result = CombatScheduler(rules).step(state)
    after = result.after_state
    settlement_records = result.transition.transaction.settlement.records if result.transition.transaction.settlement else ()
    lifecycle_records = [
        record
        for record in settlement_records
        if record.get("record_type") in {"event_dispatch", "event_listener"}
    ]
    event_types = tuple(event.event_type for event in result.transition.transaction.events)
    runtime = after.global_flags.get("wave_runtime")
    checks = {
        "initial_wave_start_committed": result.transition.outcome.successor_eligible,
        "initial_wave_runtime_activated": isinstance(runtime, dict)
        and runtime.get("status") == "active"
        and state.wave_index in runtime.get("started_wave_indices", ()),
        "wave_started_dispatched": "wave.started" in event_types and bool(lifecycle_records),
        "wave_monster_dispatched": "wave.monster" in event_types
        and any(
            record.get("payload", {}).get("event", {}).get("event_type") == "wave.monster"
            for record in lifecycle_records
        ),
        "phase_returns_idle": after.global_flags.get("combat_phase") == "idle",
        "state_changed_only_by_transition": before_hash != _snapshot_hash(after)
        and result.transition.transaction.mutations,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "state": state,
        "after_state": after,
        "transition": result.transition.to_json(),
    }


def _pure_query_case(rules: RuleBook, state: BattleState) -> dict[str, Any]:
    before_hash = _snapshot_hash(state)
    system = WaveSystem(rules)
    view = system.view(state)
    plan = system.plan_transition(state)
    after_hash = _snapshot_hash(state)
    checks = {
        "view_configured": view.configured,
        "active_wave_enemy_blocks_advance": plan.status == "no_change" and bool(plan.blocking_unit_ids),
        "pure_query_state_unchanged": before_hash == after_hash,
        "plan_json_stable": plan.to_json() == json.loads(json.dumps(plan.to_json(), sort_keys=True)),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "view": view.to_json(), "plan": plan.to_json()}


def _advance_case(rules: RuleBook, state: BattleState) -> dict[str, Any]:
    cleared_state = _with_units_defeated(state, _current_wave_unit_ids(state))
    system = WaveSystem(rules)
    plan = system.plan_transition(cleared_state)
    result = system.apply_transition(cleared_state, plan)
    after = MutationReducer().apply_all(cleared_state, result.mutations)
    replay = MutationReducer().replay_snapshot(cleared_state, result.mutations, after.snapshot().to_json())
    runtime = after.global_flags.get("wave_runtime")
    next_ids = tuple(runtime.get("current_wave_unit_ids", ())) if isinstance(runtime, dict) else ()
    targets = TargetSystem().enumerate_action_targets(
        after,
        "ally:probe",
        TargetPolicy(
            policy_id="validation:p1_2:enemy_single",
            target_relation="enemy",
            selection_mode="explicit_primary",
            source_trace={"source_kind": "validation_fixture", "source_id": "p1_2:wave_targetability"},
        ),
    )
    timeline_plan = TimelineSystem().plan_next_actor(after, rules.default_timeline_rule())
    skipped = {str(item.get("unit_id")) for item in timeline_plan.skipped_units}
    wave_monster_events = [event for event in result.events if event.event_type == "wave.monster"]
    checks = {
        "plan_advances": plan.status == "advance_to_next_wave",
        "old_wave_removed": all(after.units[unit_id].flags.get("lifecycle_status") == "removed" for unit_id in plan.remove_unit_ids),
        "wave_index_mutated": after.wave_index == int(plan.next_wave_index),
        "next_wave_active": all(unit_id in after.units and after.units[unit_id].flags.get("lifecycle_status") == "active" for unit_id in next_ids),
        "next_wave_targetable": targets.ok and all(unit_id in targets.selectable_target_ids for unit_id in next_ids),
        "next_wave_timeline_eligible": all(unit_id not in skipped for unit_id in next_ids),
        "wave_monster_events_payload_complete": all(_wave_monster_payload_complete(event) for event in wave_monster_events),
        "spawn_mutations_have_stage_source": all(
            mutation.metadata.get("source_trace", {}).get("source_path") == "ExcelOutput/StageConfig.json"
            for mutation in result.mutations
            if mutation.metadata.get("lifecycle_operation") == "unit_spawn"
        ),
        "replay_ok": replay.ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "state": cleared_state,
        "after_state": after,
        "plan": plan.to_json(),
        "mutations": [mutation.to_json() for mutation in result.mutations],
        "events": [event.to_json() for event in result.events],
        "records": result.records,
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
    }


def _victory_case(rules: RuleBook, state: BattleState) -> dict[str, Any]:
    final_state = _with_units_defeated(state, _current_wave_unit_ids(state))
    system = WaveSystem(rules)
    plan = system.plan_transition(final_state)
    result = system.apply_transition(final_state, plan)
    after = MutationReducer().apply_all(final_state, result.mutations)
    replay = MutationReducer().replay_snapshot(final_state, result.mutations, after.snapshot().to_json())
    availability = ActionAvailabilitySystem(rules).view(after)
    scheduler_result = CombatScheduler(rules).step(after)
    checks = {
        "plan_victory": plan.status == "battle_victory",
        "battle_outcome_victory": after.global_flags.get("battle_outcome") == "victory",
        "battle_phase_ended": after.global_flags.get("phase") == "ended",
        "availability_blocked_after_end": availability.mode == "blocked" and availability.ordinary_input_blocked,
        "scheduler_blocked_after_end": scheduler_result.after_state == after
        and scheduler_result.transition.coverage.get("blocked_reason") == "battle_ended",
        "replay_ok": replay.ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "state": final_state,
        "after_state": after,
        "plan": plan.to_json(),
        "mutations": [mutation.to_json() for mutation in result.mutations],
        "events": [event.to_json() for event in result.events],
        "availability": availability.to_json(),
        "scheduler_after_end": scheduler_result.transition.to_json(),
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
    }


def _defeat_case(rules: RuleBook, state: BattleState) -> dict[str, Any]:
    defeated = _with_units_defeated(state, ("ally:probe",))
    system = WaveSystem(rules)
    plan = system.plan_transition(defeated)
    result = system.apply_transition(defeated, plan)
    after = MutationReducer().apply_all(defeated, result.mutations)
    replay = MutationReducer().replay_snapshot(defeated, result.mutations, after.snapshot().to_json())
    checks = {
        "plan_defeat": plan.status == "battle_defeat",
        "battle_outcome_defeat": after.global_flags.get("battle_outcome") == "defeat",
        "battle_phase_ended": after.global_flags.get("phase") == "ended",
        "replay_ok": replay.ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "state": defeated,
        "after_state": after,
        "plan": plan.to_json(),
        "mutations": [mutation.to_json() for mutation in result.mutations],
        "events": [event.to_json() for event in result.events],
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
    }


def _blocked_case(rules: RuleBook, state: BattleState, definition: WaveDefinitionIR) -> dict[str, Any]:
    system = WaveSystem(rules)
    cleared_state = _with_units_defeated(state, _current_wave_unit_ids(state))
    missing_runtime = dict(cleared_state.global_flags.get("wave_runtime", {}))
    missing_runtime["wave_definition_id"] = "wave_definition:missing"
    missing_state = replace(cleared_state, global_flags={**cleared_state.global_flags, "wave_runtime": missing_runtime})
    missing_plan = system.plan_transition(missing_state)
    missing_result = system.apply_transition(missing_state, missing_plan)
    unknown_state = _with_extra_enemy(cleared_state, "enemy:unknown", {})
    unknown_plan = system.plan_transition(unknown_state)
    summon_state = _with_extra_enemy(cleared_state, "enemy:summon", {"wave_member_kind": "enemy_summon"})
    summon_plan = system.plan_transition(summon_state)
    queued_state = replace(cleared_state, queues={"manual_ultimate": ({"entry_id": "pending"},)})
    queued_plan = system.plan_transition(queued_state)
    blocked_definition = next((item for item in rules.wave_definitions() if item.coverage_status == "blocked"), None)
    blocked_definition_ok = blocked_definition is not None and blocked_definition.coverage_status == "blocked"
    checks = {
        "missing_definition_blocked": missing_plan.status == "blocked" and missing_plan.blocked_reason == "wave_definition_missing",
        "missing_definition_no_mutations": not missing_result.mutations and _snapshot_hash(missing_state) == _snapshot_hash(missing_state),
        "active_unknown_enemy_blocks": unknown_plan.status == "blocked" and unknown_plan.blocked_reason == "active_enemy_without_wave_membership",
        "active_summon_blocks": summon_plan.status == "blocked" and summon_plan.blocked_reason == "active_enemy_summon_blocks_wave_clear",
        "pending_queue_blocks": queued_plan.status == "blocked" and queued_plan.blocked_reason == "pending_queue_before_wave_transition",
        "blocked_wave_definition_exists_and_not_executable": blocked_definition_ok,
        "blocked_definition_not_selected_as_positive": blocked_definition is None or blocked_definition.wave_definition_id != definition.wave_definition_id,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "missing_plan": missing_plan.to_json(),
        "unknown_plan": unknown_plan.to_json(),
        "summon_plan": summon_plan.to_json(),
        "queued_plan": queued_plan.to_json(),
        "blocked_definition": blocked_definition.to_json() if blocked_definition else {},
    }


def _event_case(rules: RuleBook, state: BattleState, events: list[dict[str, Any]]) -> dict[str, Any]:
    dispatcher = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules)))
    dispatch_state = replace(state, global_flags={**state.global_flags, "combat_phase": "wave_transition"})
    wave_event_json = next(event for event in events if event["event_type"] == "wave.monster")
    wave_event = GameEvent(
        "wave.monster",
        source_id=wave_event_json["source_id"],
        target_id=wave_event_json["target_id"],
        event_id=wave_event_json["event_id"],
        window=wave_event_json["window"],
        process_only=True,
        payload=wave_event_json["payload"],
    )
    dispatch = dispatcher.dispatch_event(dispatch_state, event=wave_event)
    fake = dispatcher.dispatch_event(
        dispatch_state,
        event=GameEvent("wave.monster", source_id="wave_system", target_id="enemy:fake"),
    )
    aliases = _aliases_from_records(dispatch.records)
    fake_aliases = _aliases_from_records(fake.records)
    family = rules.status_event_family("OnWaveMonster")
    checks = {
        "wave_event_routes_to_on_wave_monster": any(alias.get("callback_event") == "OnWaveMonster" for alias in aliases),
        "wave_event_alias_not_payload_blocked": all(alias.get("blocked_dependency") != "wave_monster_payload_incomplete" for alias in aliases),
        "fake_wave_event_blocked": any(alias.get("blocked_dependency") == "wave_monster_payload_incomplete" for alias in fake_aliases),
        "fake_wave_event_state_unchanged": fake.after_state == dispatch_state and not fake.mutations,
        "on_wave_monster_family_if_present_has_runtime_source": family is None or "wave.monster" in family.runtime_event_sources,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "aliases": aliases,
        "fake_aliases": fake_aliases,
        "family": family.to_json() if family else {},
        "dispatch_records": dispatch.records,
        "fake_records": fake.records,
    }


def _scheduler_case(rules: RuleBook, state: BattleState) -> dict[str, Any]:
    cleared_state = _with_units_defeated(state, _current_wave_unit_ids(state))
    availability = ActionAvailabilitySystem(rules).view(cleared_state)
    scheduler_result = CombatScheduler(rules).step(cleared_state)
    checks = {
        "availability_reports_wave_transition": availability.mode == "wave_transition_available",
        "scheduler_applies_wave_transition": scheduler_result.after_state.wave_index == 1,
        "scheduler_transition_has_wave_record": any(
            record.get("record_type") == "wave_transition"
            for record in (scheduler_result.transition.transaction.settlement.records if scheduler_result.transition.transaction.settlement else ())
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "state": cleared_state,
        "after_state": scheduler_result.after_state,
        "availability": availability.to_json(),
        "transition": scheduler_result.transition.to_json(),
    }


def _select_wave_definition(rules: RuleBook) -> WaveDefinitionIR:
    for definition in rules.wave_definitions():
        if definition.coverage_status != "executable" or definition.wave_count < 2:
            continue
        if rules.wave_entries_for_wave(definition.wave_definition_id, 0) and rules.wave_entries_for_wave(definition.wave_definition_id, 1):
            return definition
    raise AssertionError("no executable multi-wave WaveDefinitionIR found")


def _select_avatar_entity(rules: RuleBook) -> str:
    for entity in rules.entities_by_type("avatar"):
        return entity.entity_id
    raise AssertionError("no avatar entity found")


def _select_action_definition(rules: RuleBook) -> tuple[str, int]:
    for definition in sorted(rules.ir.action_definitions, key=lambda item: (item.action_id, item.level)):
        entity = rules.entity(definition.action_id)
        if entity is not None and entity.entity_type in {"avatar_skill", "active_skill"}:
            return definition.action_id, definition.level
    raise AssertionError("no avatar action definition found")


def _current_wave_unit_ids(state: BattleState) -> tuple[str, ...]:
    runtime = state.global_flags.get("wave_runtime")
    if not isinstance(runtime, dict):
        return ()
    raw = runtime.get("current_wave_unit_ids")
    return tuple(str(item) for item in raw if isinstance(item, str)) if isinstance(raw, list) else ()


def _with_units_defeated(state: BattleState, unit_ids: tuple[str, ...]) -> BattleState:
    units = dict(state.units)
    for unit_id in unit_ids:
        unit = units[unit_id]
        flags = dict(unit.flags)
        flags["lifecycle_status"] = "defeated"
        units[unit_id] = replace(unit, hp=0.0, flags=flags)
    return replace(state, units=units)


def _with_extra_enemy(state: BattleState, unit_id: str, flags: dict[str, Any]) -> BattleState:
    units = dict(state.units)
    units[unit_id] = UnitState(
        unit_id=unit_id,
        side="enemy",
        template_id="validation:enemy",
        max_hp=100.0,
        hp=100.0,
        speed=100.0,
        flags=dict(flags),
    )
    return replace(state, units=units)


def _wave_unit_id(definition: WaveDefinitionIR, entry) -> str:
    return f"enemy:stage:{definition.stage_id}:wave:{entry.wave_index}:pos:{entry.position}"


def _wave_monster_payload_complete(event: GameEvent) -> bool:
    required = ("wave_definition_id", "wave_index", "unit_id", "entry_id", "position", "source_trace")
    return all(key in event.payload for key in required) and isinstance(event.payload.get("source_trace"), dict)


def _aliases_from_records(records: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    aliases: list[dict[str, Any]] = []
    for record in records:
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            raw_aliases = metadata.get("event_aliases")
            if isinstance(raw_aliases, list):
                aliases.extend(alias for alias in raw_aliases if isinstance(alias, dict))
            raw_alias = metadata.get("event_alias")
            if isinstance(raw_alias, dict):
                aliases.append(raw_alias)
        raw_alias = payload.get("event_alias")
        if isinstance(raw_alias, dict):
            aliases.append(raw_alias)
    return aliases


def _snapshot_hash(state: BattleState) -> str:
    raw = json.dumps(state.snapshot().to_json(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _strip_state(case: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in case.items() if key not in {"state", "after_state"}}


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


if __name__ == "__main__":
    raise SystemExit(main())
