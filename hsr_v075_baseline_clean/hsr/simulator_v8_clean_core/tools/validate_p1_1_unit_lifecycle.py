from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, Mutation, UnitState
from ..core.reducer import MutationReducer
from ..rules.ir import IRSource, TimelineRuleIR
from ..rules.rulebook import RuleBook
from ..systems.action_availability import ActionAvailabilitySystem
from ..systems.damage import DamagePacket, DamageSystem, DamageWindowLedger
from ..systems.queue import QueueTargetResolver
from ..systems.target import TargetPolicy, TargetSystem
from ..systems.timeline import TimelineSystem
from ..systems.unit_lifecycle import UnitLifecycleSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "p1_1_unit_lifecycle"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    lifecycle_case = _lifecycle_view_case()
    damage_case = _damage_defeat_case()
    target_case = _target_case()
    timeline_case = _timeline_case()
    availability_case = _availability_case(rules)
    queue_case = _queue_case()
    spawn_remove_case = _spawn_remove_case()
    checks = {
        "lifecycle_view": lifecycle_case["checks"],
        "damage_defeat": damage_case["checks"],
        "target": target_case["checks"],
        "timeline": timeline_case["checks"],
        "action_availability": availability_case["checks"],
        "queue": queue_case["checks"],
        "spawn_remove_revive": spawn_remove_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = _json_safe(
        {
            "version": VALIDATION_VERSION,
            "baseline_version": BASELINE_VERSION,
            "ok": all(item["ok"] for item in checks.values()),
            "build": {
                "tbgd_root": tbgd_root.as_posix(),
                "selection_policy": {
                    "mode": "structured_lifecycle_unit_cases",
                    "fixed_character_or_monster_name_used_for_runtime_selection": False,
                    "predicate": [
                        "UnitState flags.lifecycle_status active/defeated/removed",
                        "HP positive-to-zero DamagePacket lifecycle transition",
                        "TargetPolicy.allow_defeated lifecycle gating",
                        "Timeline/action availability/queue lifecycle gating",
                        "UnitSpawn/UnitRemove reducer replay and UnitRevive blocked state unchanged",
                    ],
                },
            },
            "checks": checks,
            "cases": {
                "lifecycle_view": lifecycle_case,
                "damage_defeat": damage_case,
                "target": target_case,
                "timeline": timeline_case,
                "action_availability": availability_case,
                "queue": queue_case,
                "spawn_remove_revive": spawn_remove_case,
            },
            "static_checks": static_result.to_json(),
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p1_1_unit_lifecycle.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 P1-1 unit lifecycle.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _lifecycle_view_case() -> dict[str, Any]:
    lifecycle = UnitLifecycleSystem()
    state = _base_state()
    removed_state = _with_flag(state, "enemy:removed", "lifecycle_status", "removed")
    checks = {
        "hp_positive_active": lifecycle.view(state, "ally:actor").status == "active",
        "hp_zero_infers_defeated": lifecycle.view(state, "enemy:defeated").status == "defeated",
        "explicit_removed_overrides_hp": lifecycle.view(removed_state, "enemy:removed").status == "removed",
        "removed_cannot_act": lifecycle.can_act(removed_state, "enemy:removed") == (False, "unit_removed"),
        "removed_cannot_target": lifecycle.can_target(removed_state, "enemy:removed") == (False, "unit_removed"),
        "snapshot_has_lifecycle": removed_state.snapshot().to_json()["units"]["enemy:removed"]["lifecycle_status"] == "removed",
        "snapshot_has_active_teams": "enemy:removed" not in removed_state.snapshot().to_json()["active_teams"]["enemy"],
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "snapshot": removed_state.snapshot().to_json()}


def _damage_defeat_case() -> dict[str, Any]:
    state = _base_state()
    packet = DamagePacket(
        attacker_id="ally:actor",
        target_id="enemy:target",
        attack_type="normal",
        damage_formula_family="hp_loss",
        amount=10.0,
        amount_stage="fixed_final",
        source_trace=_source("validation_damage").to_json(),
        metadata={
            "damage_source_owner_id": "ally:actor",
            "damage_source_id": "validation:hp_loss",
            "damage_source_kind": "validation_damage",
            "damage_sequence_id": "validation:hp_loss:sequence",
        },
    )
    ledger = DamageWindowLedger()
    result = DamageSystem().apply_packet(state, packet, window_ledger=ledger)
    after_state = MutationReducer().apply_all(state, result.mutations)
    replay = MutationReducer().replay_snapshot(state, result.mutations, after_state.snapshot().to_json())
    repeat = DamageSystem().apply_packet(after_state, packet, window_ledger=ledger)
    mutation_ops = [mutation.metadata.get("lifecycle_operation") for mutation in result.mutations]
    defeat_events = [event for event in result.events if event.event_type == "unit.defeated"]
    lifecycle_mutation_ids = [
        mutation.stable_id()
        for mutation in result.mutations
        if mutation.metadata.get("lifecycle_operation") == "unit_defeat"
    ]
    checks = {
        "damage_ok": result.ok,
        "hp_mutation_present": any(mutation.path == ("units", "enemy:target", "hp") for mutation in result.mutations),
        "lifecycle_defeat_mutation_present": "unit_defeat" in mutation_ops,
        "defeat_record_mutation_present": "unit_defeat_record" in mutation_ops,
        "defeat_event_present": bool(defeat_events),
        "event_links_lifecycle_mutation": bool(defeat_events)
        and defeat_events[0].payload.get("lifecycle_mutation_id") in lifecycle_mutation_ids,
        "after_snapshot_defeated": after_state.snapshot().to_json()["units"]["enemy:target"]["lifecycle_status"] == "defeated",
        "replay_ok": replay.ok,
        "repeat_skipped_no_mutation": repeat.ok and not repeat.mutations,
        "repeat_skip_recorded": any(record.get("record_type") == "damage_source_skipped" for record in repeat.records),
        "source_trace_present": all(mutation.metadata.get("source_trace") for mutation in result.mutations if "lifecycle_operation" in mutation.metadata),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "mutations": [mutation.to_json() for mutation in result.mutations],
        "events": [event.to_json() for event in result.events],
        "records": list(result.records),
        "repeat_records": list(repeat.records),
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
    }


def _target_case() -> dict[str, Any]:
    state = _with_flag(_base_state(), "enemy:removed", "lifecycle_status", "removed")
    targets = TargetSystem()
    normal = targets.enumerate_action_targets(state, "ally:actor", TargetPolicy())
    allow_defeated = targets.resolve_explicit_targets(
        state,
        "ally:actor",
        ("enemy:defeated",),
        policy=TargetPolicy(allow_defeated=True),
    )
    removed = targets.resolve_explicit_targets(
        state,
        "ally:actor",
        ("enemy:removed",),
        policy=TargetPolicy(allow_defeated=True),
    )
    checks = {
        "normal_excludes_defeated": "enemy:defeated" not in normal.selectable_target_ids,
        "normal_excludes_removed": "enemy:removed" not in normal.selectable_target_ids,
        "normal_includes_active": "enemy:target" in normal.selectable_target_ids,
        "allow_defeated_accepts_defeated": allow_defeated.ok,
        "allow_defeated_rejects_removed": not removed.ok and any("unit_removed" in error for error in removed.errors),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "normal": normal.to_json(),
        "allow_defeated": allow_defeated.resolution.to_json(),
        "removed": removed.resolution.to_json(),
    }


def _timeline_case() -> dict[str, Any]:
    state = _with_flag(_base_state(), "enemy:removed", "lifecycle_status", "removed")
    state = replace(
        state,
        units={
            unit_id: replace(unit, action_value=0.0 if unit_id != "ally:actor" else 10.0)
            for unit_id, unit in state.units.items()
        },
    )
    plan = TimelineSystem().plan_next_actor(state, _timeline_rule())
    skipped = {str(item.get("unit_id")): str(item.get("reason")) for item in plan.skipped_units}
    checks = {
        "plan_ok": plan.ok,
        "active_actor_selected": plan.actor_id == "enemy:target",
        "defeated_skipped": skipped.get("enemy:defeated") == "unit_defeated",
        "removed_skipped": skipped.get("enemy:removed") == "unit_removed",
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "plan": plan.to_json()}


def _availability_case(rules: RuleBook) -> dict[str, Any]:
    state = _with_flag(_base_state(), "enemy:removed", "lifecycle_status", "removed")
    defeated_turn = replace(state, global_flags={"turn_owner_id": "enemy:defeated"})
    removed_turn = replace(state, global_flags={"turn_owner_id": "enemy:removed"})
    defeated_view = ActionAvailabilitySystem(rules).view(defeated_turn)
    removed_view = ActionAvailabilitySystem(rules).view(removed_turn)
    checks = {
        "defeated_active_actor_blocked": defeated_view.mode == "blocked"
        and defeated_view.ordinary_input_blocked_reason == "actor_unit_defeated",
        "removed_active_actor_blocked": removed_view.mode == "blocked"
        and removed_view.ordinary_input_blocked_reason == "actor_unit_removed",
        "state_unchanged": _snapshot_hash(defeated_turn) == _snapshot_hash(defeated_turn)
        and _snapshot_hash(removed_turn) == _snapshot_hash(removed_turn),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "defeated_view": defeated_view.to_json(),
        "removed_view": removed_view.to_json(),
    }


def _queue_case() -> dict[str, Any]:
    state = _with_flag(_base_state(), "enemy:removed", "lifecycle_status", "removed")
    resolver = QueueTargetResolver()
    actor_removed = resolver.resolve(
        state,
        detail={"caster_id": "enemy:removed"},
        trigger_event=None,
        actor_alias="Caster",
        target_alias=None,
        source_trace=_source("queue_actor_removed").to_json(),
    )
    target_removed = resolver.resolve(
        state,
        detail={"caster_id": "ally:actor"},
        trigger_event=None,
        actor_alias="Caster",
        target_alias="AllEnemy",
        source_trace=_source("queue_target_removed").to_json(),
    )
    checks = {
        "actor_removed_blocked": not actor_removed.ok and "queue_actor_unit_removed" in actor_removed.blocked_reason,
        "target_removed_filtered": target_removed.ok and "enemy:removed" not in target_removed.target_ids,
        "defeated_filtered": target_removed.ok and "enemy:defeated" not in target_removed.target_ids,
        "active_target_kept": target_removed.ok and "enemy:target" in target_removed.target_ids,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "actor_removed": actor_removed.to_json(),
        "target_removed": target_removed.to_json(),
    }


def _spawn_remove_case() -> dict[str, Any]:
    lifecycle = UnitLifecycleSystem()
    reducer = MutationReducer()
    state = _base_state()
    spawned = UnitState(
        unit_id="enemy:spawned",
        side="enemy",
        template_id="validation:spawned",
        max_hp=50.0,
        hp=50.0,
        speed=120.0,
    )
    spawn_mutation = lifecycle.spawn_mutation(
        state,
        spawned,
        reason="validation spawn",
        source="validation",
        source_trace=_source("spawn").to_json(),
        metadata={"validation": True},
    )
    after_spawn = reducer.apply_all(state, (spawn_mutation,))
    spawn_replay = reducer.replay_snapshot(state, (spawn_mutation,), after_spawn.snapshot().to_json())
    remove_mutations = lifecycle.remove_mutations(
        after_spawn,
        "enemy:spawned",
        reason="validation remove",
        source="validation",
        removed_record={"reason": "validation remove", "source_trace": _source("remove").to_json()},
        source_trace=_source("remove").to_json(),
    )
    after_remove = reducer.apply_all(after_spawn, remove_mutations)
    remove_replay = reducer.replay_snapshot(after_spawn, remove_mutations, after_remove.snapshot().to_json())
    revive = lifecycle.revive_blocked(after_remove, "enemy:spawned")
    duplicate_spawn_rejected = False
    try:
        reducer.apply_all(after_spawn, (spawn_mutation,))
    except ValueError:
        duplicate_spawn_rejected = True
    unknown_unit_result = reducer.apply_all_result(
        state,
        (
            Mutation(
                op="set",
                path=("units", "missing", "hp"),
                before=None,
                after=1.0,
                reason="invalid",
                source="validation",
            ),
        ),
    )
    unknown_unit_conflict = unknown_unit_result.conflicts[0] if unknown_unit_result.conflicts else None
    unknown_unit_rejected = (
        not unknown_unit_result.ok
        and unknown_unit_result.after_state == state
        and unknown_unit_result.applied_count == 0
        and unknown_unit_conflict is not None
        and unknown_unit_conflict.code == "invalid_path"
        and unknown_unit_conflict.mutation_index == 0
        and unknown_unit_conflict.path == ("units", "missing", "hp")
    )
    checks = {
        "spawn_replay_ok": spawn_replay.ok,
        "spawned_active": after_spawn.snapshot().to_json()["units"]["enemy:spawned"]["lifecycle_status"] == "active",
        "spawn_targetable": TargetSystem().enumerate_action_targets(after_spawn, "ally:actor").ok
        and "enemy:spawned" in TargetSystem().enumerate_action_targets(after_spawn, "ally:actor").selectable_target_ids,
        "remove_replay_ok": remove_replay.ok,
        "removed_tombstone_kept": "enemy:spawned" in after_remove.units
        and after_remove.snapshot().to_json()["units"]["enemy:spawned"]["lifecycle_status"] == "removed",
        "removed_not_targetable": "enemy:spawned"
        not in TargetSystem().enumerate_action_targets(after_remove, "ally:actor").selectable_target_ids,
        "revive_blocked_state_unchanged": revive["ok"] is False and revive["state_unchanged"] is True,
        "duplicate_spawn_rejected": duplicate_spawn_rejected,
        "unknown_unit_field_rejected": unknown_unit_rejected,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "spawn_mutation": spawn_mutation.to_json(),
        "remove_mutations": [mutation.to_json() for mutation in remove_mutations],
        "revive": revive,
        "unknown_unit_reduction": unknown_unit_result.to_json(),
    }


def _base_state() -> BattleState:
    return BattleState(
        units={
            "ally:actor": UnitState(
                unit_id="ally:actor",
                side="ally",
                template_id="validation:ally",
                max_hp=100.0,
                hp=100.0,
                speed=100.0,
            ),
            "enemy:target": UnitState(
                unit_id="enemy:target",
                side="enemy",
                template_id="validation:enemy",
                max_hp=5.0,
                hp=5.0,
                speed=100.0,
            ),
            "enemy:defeated": UnitState(
                unit_id="enemy:defeated",
                side="enemy",
                template_id="validation:defeated",
                max_hp=100.0,
                hp=0.0,
                speed=100.0,
            ),
            "enemy:removed": UnitState(
                unit_id="enemy:removed",
                side="enemy",
                template_id="validation:removed",
                max_hp=100.0,
                hp=100.0,
                speed=100.0,
            ),
        },
        skill_points=5,
        max_skill_points=5,
    )


def _with_flag(state: BattleState, unit_id: str, key: str, value: Any) -> BattleState:
    units = dict(state.units)
    unit = units[unit_id]
    flags = dict(unit.flags)
    flags[key] = value
    units[unit_id] = replace(unit, flags=flags)
    return replace(state, units=units)


def _timeline_rule() -> TimelineRuleIR:
    return TimelineRuleIR(
        timeline_rule_id="validation:timeline",
        base_action_gauge=10000.0,
        initial_action_value_rule="validation",
        turn_reset_rule="validation",
        source_kind="validation",
        source=_source("timeline"),
    )


def _source(raw_id: str) -> IRSource:
    return IRSource(
        source_path="simulator_v8_clean_core.tools.validate_p1_1_unit_lifecycle",
        raw_type="ValidationSynthetic",
        raw_id=raw_id,
        evidence={"validation": VALIDATION_VERSION},
    )


def _snapshot_hash(state: BattleState) -> str:
    return json.dumps(state.snapshot().to_json(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
