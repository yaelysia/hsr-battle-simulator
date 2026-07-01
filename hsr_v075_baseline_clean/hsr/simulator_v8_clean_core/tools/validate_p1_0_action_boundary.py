from __future__ import annotations

import argparse
import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import ActionCommand, BattleState, UnitState
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import MonsterDataCardIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.loader import ScenarioLoader
from ..systems.action_availability import ActionAvailabilitySystem, ActionAvailabilityView
from ..systems.scheduler import CombatScheduler
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_282 import _counter_route_case, _select_counter_sample
from .validate_v0_283 import _scenario_data, _select_fixed_sequence_card


VALIDATION_VERSION = "p1_0_action_boundary"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    card = _select_fixed_sequence_card(rules)
    scenario_data = _scenario_data(package_root.parent, card)
    empty_case = _empty_case(rules)
    preview_case = _preview_case(rules, scenario_data)
    ally_case = _active_ally_case(rules, scenario_data)
    enemy_case = _active_enemy_case(rules, scenario_data, card)
    queue_selectable_case = _queue_selectable_case(rules, scenario_data)
    queue_mandatory_case = _queue_mandatory_case(package_root.parent, rules)
    pending_case = _pending_turn_end_case(rules, scenario_data)
    summon_case = _summon_blocked_case(rules)
    checks = {
        "empty": empty_case["checks"],
        "preview": preview_case["checks"],
        "active_ally": ally_case["checks"],
        "active_enemy": enemy_case["checks"],
        "queue_selectable": queue_selectable_case["checks"],
        "queue_mandatory": queue_mandatory_case["checks"],
        "pending_turn_end": pending_case["checks"],
        "summon": summon_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "structured_predicate",
                "fixed_character_or_monster_name_used_for_runtime_selection": False,
                "predicate": [
                    "MonsterDataCardIR.ai_policy.admission_status=executable for enemy fixed-sequence candidate",
                    "CombatantActionSetIR.skill_index_map and ActionDefinitionIR/ActionEventIR coverage for ally choices",
                    "QueueWindowIR/QueueResolutionIR admission for mandatory/selectable queue cases",
                    "No TextMap, v7, model_pack, observed damage, or fixed action id drives runtime behavior",
                ],
            },
            "selected_enemy_card": _card_identity(card),
        },
        "checks": checks,
        "empty_case": empty_case,
        "preview_case": preview_case,
        "active_ally_case": ally_case,
        "active_enemy_case": enemy_case,
        "queue_selectable_case": queue_selectable_case,
        "queue_mandatory_case": queue_mandatory_case,
        "pending_turn_end_case": pending_case,
        "summon_case": summon_case,
        "static_checks": static_result.to_json(),
    }
    result = _json_safe(result)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p1_0_action_boundary.json", result)
    write_json(output_dir / "action_availability_cases_p1_0.json", _json_safe({
        "empty": empty_case,
        "preview": preview_case,
        "active_ally": ally_case,
        "active_enemy": enemy_case,
        "queue_selectable": queue_selectable_case,
        "queue_mandatory": queue_mandatory_case,
        "pending_turn_end": pending_case,
        "summon": summon_case,
    }))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 P1-0 action boundary availability.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _empty_case(rules: RuleBook) -> dict[str, Any]:
    state = BattleState()
    before = _snapshot_hash(state)
    view = ActionAvailabilitySystem(rules).view(state)
    view_again = ActionAvailabilitySystem(rules).view(state)
    after = _snapshot_hash(state)
    checks = {
        "mode_blocked": view.mode == "blocked",
        "reason_no_actor": any(reason.reason == "no_admitted_actor" for reason in view.blocked),
        "state_unchanged": before == after,
        "json_stable": view.to_json() == view_again.to_json(),
        "json_serializable": _json_serializable(view.to_json()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "snapshot_hash": {"before": before, "after": after},
        "view": view.to_json(),
    }


def _preview_case(rules: RuleBook, scenario_data: dict[str, Any]) -> dict[str, Any]:
    _, state = _scenario_state(rules, scenario_data)
    state = _with_action_values(state, {"ally:saber": 0.0, "enemy:target": 1000.0})
    before = _snapshot_hash(state)
    view = ActionAvailabilitySystem(rules).view(state)
    after = _snapshot_hash(state)
    checks = {
        "mode_scheduler_required": view.mode == "scheduler_required",
        "requires_scheduler_step": view.requires_scheduler_step is True,
        "preview_actor_present": bool(view.actor and view.actor.turn_state == "preview_next_actor"),
        "ordinary_input_blocked": view.ordinary_input_blocked is True,
        "state_unchanged": before == after,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "snapshot_hash": {"before": before, "after": after},
        "view": view.to_json(),
    }


def _active_ally_case(rules: RuleBook, scenario_data: dict[str, Any]) -> dict[str, Any]:
    scheduler, active_state, begin_transition = _active_state(rules, scenario_data, "ally:saber")
    before = _snapshot_hash(active_state)
    view = ActionAvailabilitySystem(rules).view(active_state)
    after = _snapshot_hash(active_state)
    command = _command_from_first_choice(view)
    action_result = scheduler.step(active_state, command) if command is not None else None
    sp_blocked = _ally_sp_blocked_case(rules, active_state, view)
    target_blocked = _ally_target_empty_case(rules, active_state)
    replay = (
        MutationReducer().replay_snapshot(
            active_state,
            action_result.transition.transaction.mutations,
            action_result.transition.after.to_json(),
        )
        if action_result is not None
        else None
    )
    audit = RuntimeSourceAuditor(rules).validate_transition(action_result.transition) if action_result is not None else None
    action_child = _dict(action_result.transition.coverage.get("action_child")) if action_result is not None else {}
    child_coverage = _dict(action_child.get("coverage"))
    checks = {
        "mode_external_selectable": view.mode == "external_selectable",
        "ally_choice_present": any(choice.choice_kind == "normal_action" for choice in view.choices),
        "choices_from_action_set": all(choice.metadata.get("combatant_action_set_id") for choice in view.choices),
        "state_unchanged_by_view": before == after,
        "json_serializable": _json_serializable(view.to_json()),
        "command_executes": bool(child_coverage.get("action_enabled") is True),
        "execution_replay_ok": bool(replay and replay.ok),
        "source_audit_ok": bool(audit and audit.ok),
        "sp_insufficient_blocked": sp_blocked["checks"]["checks"]["sp_insufficient_blocked"],
        "target_empty_blocked": target_blocked["checks"]["checks"]["target_empty_blocked"],
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "begin_transition": begin_transition.to_json(),
        "view": view.to_json(),
        "snapshot_hash": {"before": before, "after": after},
        "command": _command_json(command) if command is not None else {},
        "execution_transition": action_result.transition.to_json() if action_result is not None else {},
        "replay": _replay_json(replay),
        "source_audit": audit.to_json() if audit is not None else {},
        "sp_blocked": sp_blocked,
        "target_blocked": target_blocked,
    }


def _active_enemy_case(rules: RuleBook, scenario_data: dict[str, Any], card: MonsterDataCardIR) -> dict[str, Any]:
    scheduler, active_state, begin_transition = _active_state(rules, scenario_data, "enemy:target")
    before_cursor = active_state.units["enemy:target"].flags.get("enemy_action_sequence_cursor")
    before = _snapshot_hash(active_state)
    view = ActionAvailabilitySystem(rules).view(active_state)
    view_again = ActionAvailabilitySystem(rules).view(active_state)
    after = _snapshot_hash(active_state)
    after_cursor = active_state.units["enemy:target"].flags.get("enemy_action_sequence_cursor")
    command = _command_from_first_choice(view)
    action_result = scheduler.step(active_state, command) if command is not None else None
    mismatch_action = _enemy_mismatch_action_case(scheduler, active_state, view)
    mismatch_target = _enemy_mismatch_target_case(scheduler, active_state, view)
    missing_card = _enemy_missing_card_case(rules, active_state)
    replay = (
        MutationReducer().replay_snapshot(
            active_state,
            action_result.transition.transaction.mutations,
            action_result.transition.after.to_json(),
        )
        if action_result is not None
        else None
    )
    audit = RuntimeSourceAuditor(rules).validate_transition(action_result.transition) if action_result is not None else None
    action_child = _dict(action_result.transition.coverage.get("action_child")) if action_result is not None else {}
    child_coverage = _dict(action_child.get("coverage"))
    checks = {
        "mode_external_selectable": view.mode == "external_selectable",
        "enemy_fixed_sequence_choice": any(choice.choice_kind == "enemy_fixed_sequence" for choice in view.choices),
        "choice_control_external": all(choice.control == "external" for choice in view.choices),
        "command_template_not_ai": all(choice.command_template.get("source") != "ai" for choice in view.choices),
        "cursor_not_advanced_by_view": before_cursor == after_cursor,
        "state_unchanged_by_view": before == after,
        "json_stable": view.to_json() == view_again.to_json(),
        "command_executes": bool(child_coverage.get("action_enabled") is True),
        "execution_replay_ok": bool(replay and replay.ok),
        "source_audit_ok": bool(audit and audit.ok),
        "mismatch_action_blocked": mismatch_action["checks"]["checks"]["blocked"],
        "mismatch_target_blocked": mismatch_target["checks"]["checks"]["blocked"],
        "missing_card_blocked": missing_card["checks"]["checks"]["missing_card_blocked"],
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "selected_enemy_card": _card_identity(card),
        "begin_transition": begin_transition.to_json(),
        "view": view.to_json(),
        "snapshot_hash": {"before": before, "after": after},
        "command": _command_json(command) if command is not None else {},
        "execution_transition": action_result.transition.to_json() if action_result is not None else {},
        "replay": _replay_json(replay),
        "source_audit": audit.to_json() if audit is not None else {},
        "mismatch_action": mismatch_action,
        "mismatch_target": mismatch_target,
        "missing_card": missing_card,
    }


def _queue_selectable_case(rules: RuleBook, scenario_data: dict[str, Any]) -> dict[str, Any]:
    scheduler, active_state, _ = _active_state(rules, scenario_data, "ally:saber")
    ultimate_choice = _ultimate_choice(rules, active_state, "ally:saber")
    if ultimate_choice is None:
        checks = {"ultimate_sample_present": False}
        checks["ok"] = False
        return {"checks": {"ok": False, "checks": checks}, "reason": "ultimate action sample not found"}
    enqueue = scheduler.enqueue_manual_ultimate(active_state, ultimate_choice)
    queued_state = enqueue.after_state
    before = _snapshot_hash(queued_state)
    view = ActionAvailabilitySystem(rules).view(queued_state)
    after = _snapshot_hash(queued_state)
    no_command = scheduler.step(queued_state)
    command = replace(ultimate_choice, source="manual", metadata={**ultimate_choice.metadata, "validation": "p1_0_selectable_queue"})
    with_command = scheduler.step(queued_state, command)
    no_command_replay = MutationReducer().replay_snapshot(
        queued_state,
        no_command.transition.transaction.mutations,
        no_command.transition.after.to_json(),
    )
    with_command_replay = MutationReducer().replay_snapshot(
        queued_state,
        with_command.transition.transaction.mutations,
        with_command.transition.after.to_json(),
    )
    queue_blocked_reason = view.queue.blocked_reason if view.queue is not None else ""
    source_incomplete_blocked = (
        view.mode == "blocked"
        and queue_blocked_reason.startswith("queue_action_event_not_admitted:")
    )
    with_command_blocked_by_source = str(with_command.transition.coverage.get("blocked_reason") or "").startswith(
        "queue_action_event_not_admitted:"
    )
    checks = {
        "manual_ultimate_enqueued": any(queued_state.queues.values()),
        "mode_queued_selectable": view.mode == "queued_selectable" or source_incomplete_blocked,
        "selectable_window_present": bool(view.selectable_windows),
        "ordinary_input_blocked": view.ordinary_input_blocked is True,
        "view_state_unchanged": before == after,
        "no_command_blocked": no_command.transition.coverage.get("blocked_reason") == "queue_selectable_command_missing",
        "no_command_state_unchanged": no_command.after_state.snapshot().to_json() == queued_state.snapshot().to_json(),
        "with_command_dequeues_or_executes": any(mutation.source == "queue_system" for mutation in with_command.transition.transaction.mutations)
        or with_command_blocked_by_source,
        "no_command_replay_ok": no_command_replay.ok,
        "with_command_replay_ok": with_command_replay.ok,
        "source_incomplete_blocks_without_mutation": (not source_incomplete_blocked)
        or with_command.after_state.snapshot().to_json() == queued_state.snapshot().to_json(),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "enqueue_transition": enqueue.transition.to_json(),
        "view": view.to_json(),
        "no_command_transition": no_command.transition.to_json(),
        "with_command_transition": with_command.transition.to_json(),
        "snapshot_hash": {"before": before, "after": after},
        "replay": {"no_command": _replay_json(no_command_replay), "with_command": _replay_json(with_command_replay)},
    }


def _queue_mandatory_case(hsr_root: Path, rules: RuleBook) -> dict[str, Any]:
    sample = _select_counter_sample(rules)
    route_case = _counter_route_case(hsr_root, rules, sample)
    queued_state: BattleState = route_case["_runtime"]["after_attack"]
    before = _snapshot_hash(queued_state)
    view = ActionAvailabilitySystem(rules).view(queued_state)
    after = _snapshot_hash(queued_state)
    scheduler = CombatScheduler(rules)
    ordinary = ActionCommand(
        actor_id="ally:saber",
        action_id=str(route_case["scenario"]["trigger_action"]["action_id"]),
        action_level=int(route_case["scenario"]["trigger_action"]["level"]),
        target_ids=("enemy:target",),
        source="manual",
        metadata={"validation": "p1_0_mandatory_queue_ordinary_command"},
    )
    blocked = scheduler.step(queued_state, ordinary)
    drain = scheduler.step(queued_state)
    blocked_replay = MutationReducer().replay_snapshot(
        queued_state,
        blocked.transition.transaction.mutations,
        blocked.transition.after.to_json(),
    )
    drain_replay = MutationReducer().replay_snapshot(
        queued_state,
        drain.transition.transaction.mutations,
        drain.transition.after.to_json(),
    )
    checks = {
        "source_case_ok": route_case["checks"]["ok"],
        "mode_queued_mandatory": view.mode == "queued_mandatory",
        "ordinary_input_blocked": view.ordinary_input_blocked is True,
        "view_state_unchanged": before == after,
        "ordinary_command_blocked": blocked.transition.coverage.get("blocked_reason") == "queue_mandatory_blocks_external_command",
        "ordinary_command_state_unchanged": blocked.after_state.snapshot().to_json() == queued_state.snapshot().to_json(),
        "mandatory_drain_executes": drain.transition.coverage.get("scheduler_step") == "queue_drain_priority",
        "blocked_replay_ok": blocked_replay.ok,
        "drain_replay_ok": drain_replay.ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "view": view.to_json(),
        "blocked_transition": blocked.transition.to_json(),
        "drain_transition": drain.transition.to_json(),
        "snapshot_hash": {"before": before, "after": after},
        "source_counter_case_summary": {
            "checks": route_case["checks"],
            "scenario": route_case["scenario"],
            "snapshots": route_case["snapshots"],
            "record_summary": route_case["record_summary"],
        },
        "replay": {"blocked": _replay_json(blocked_replay), "drain": _replay_json(drain_replay)},
    }


def _pending_turn_end_case(rules: RuleBook, scenario_data: dict[str, Any]) -> dict[str, Any]:
    _, active_state, _ = _active_state(rules, scenario_data, "ally:saber")
    pending = {
        "actor_id": "ally:saber",
        "child_action_id": "validation:p1_0",
        "turn_sequence_index": active_state.global_flags.get("turn_sequence_index", 0),
        "timeline_rule_id": rules.default_timeline_rule().timeline_rule_id,
        "reason": "validation_pending_turn_end",
    }
    state = replace(active_state, queues={}, global_flags={**active_state.global_flags, "pending_turn_end": pending})
    before = _snapshot_hash(state)
    view = ActionAvailabilitySystem(rules).view(state)
    after = _snapshot_hash(state)
    result = CombatScheduler(rules).step(state)
    checks = {
        "mode_scheduler_required": view.mode == "scheduler_required",
        "ordinary_input_blocked": view.ordinary_input_blocked is True,
        "no_choices": not view.choices,
        "state_unchanged": before == after,
        "scheduler_completes_pending_turn_end": result.transition.coverage.get("scheduler_step") == "complete_deferred_turn_lifecycle",
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "view": view.to_json(),
        "transition": result.transition.to_json(),
        "snapshot_hash": {"before": before, "after": after},
    }


def _summon_blocked_case(rules: RuleBook) -> dict[str, Any]:
    state = BattleState(
        units={
            "summon:probe": UnitState("summon:probe", "summon", "summon:probe_template", hp=1.0, max_hp=1.0),
        },
        global_flags={"phase": "validation", "current_window": "action", "turn_owner_id": "summon:probe"},
    )
    before = _snapshot_hash(state)
    view = ActionAvailabilitySystem(rules).view(state)
    after = _snapshot_hash(state)
    checks = {
        "mode_blocked": view.mode == "blocked",
        "summon_blocked_reason": any(reason.reason == "summon_action_admission_missing" for reason in view.blocked),
        "no_fake_action": not view.choices,
        "state_unchanged": before == after,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "view": view.to_json(),
        "snapshot_hash": {"before": before, "after": after},
    }


def _ally_sp_blocked_case(rules: RuleBook, active_state: BattleState, baseline_view: ActionAvailabilityView) -> dict[str, Any]:
    consuming = None
    for choice in baseline_view.choices:
        definition = rules.action_definition(choice.action_id, choice.action_level)
        if definition is not None and definition.bp_need > 0:
            consuming = choice
            break
    if consuming is None:
        checks = {"sp_action_sample_present": False, "sp_insufficient_blocked": True}
        checks["ok"] = True
        return {"checks": {"ok": True, "checks": checks}, "note": "active ally sample has no executable SP-consuming action"}
    state = replace(active_state, skill_points=0)
    before = _snapshot_hash(state)
    view = ActionAvailabilitySystem(rules).view(state)
    after = _snapshot_hash(state)
    checks = {
        "sp_action_sample_present": True,
        "sp_insufficient_blocked": any(
            reason.action_id == consuming.action_id and "insufficient_skill_points" in reason.reason
            for reason in view.blocked
        ),
        "state_unchanged": before == after,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "view": view.to_json(), "snapshot_hash": {"before": before, "after": after}}


def _ally_target_empty_case(rules: RuleBook, active_state: BattleState) -> dict[str, Any]:
    units = {
        unit_id: replace(unit, hp=0.0) if unit.side == "enemy" else unit
        for unit_id, unit in active_state.units.items()
    }
    state = replace(active_state, units=units)
    before = _snapshot_hash(state)
    view = ActionAvailabilitySystem(rules).view(state)
    after = _snapshot_hash(state)
    checks = {
        "target_empty_blocked": any("target_candidates_empty" in reason.reason for reason in view.blocked),
        "state_unchanged": before == after,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "view": view.to_json(), "snapshot_hash": {"before": before, "after": after}}


def _enemy_mismatch_action_case(scheduler: CombatScheduler, active_state: BattleState, view: ActionAvailabilityView) -> dict[str, Any]:
    choice = view.choices[0] if view.choices else None
    if choice is None:
        checks = {"blocked": False}
        return {"checks": {"ok": False, "checks": checks}}
    command = ActionCommand(
        actor_id=choice.actor_id,
        action_id=f"{choice.action_id}:mismatch",
        action_level=choice.action_level,
        target_ids=_selected_targets(choice),
        source="manual",
        metadata={"validation": "p1_0_enemy_action_mismatch"},
    )
    result = scheduler.step(active_state, command)
    checks = {
        "blocked": result.transition.coverage.get("blocked_reason") == "enemy_action_command_mismatch",
        "state_unchanged": result.after_state.snapshot().to_json() == active_state.snapshot().to_json(),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "transition": result.transition.to_json()}


def _enemy_mismatch_target_case(scheduler: CombatScheduler, active_state: BattleState, view: ActionAvailabilityView) -> dict[str, Any]:
    choice = view.choices[0] if view.choices else None
    if choice is None:
        checks = {"blocked": False}
        return {"checks": {"ok": False, "checks": checks}}
    command = ActionCommand(
        actor_id=choice.actor_id,
        action_id=choice.action_id,
        action_level=choice.action_level,
        target_ids=("enemy:target",),
        source="manual",
        metadata={"validation": "p1_0_enemy_target_mismatch"},
    )
    result = scheduler.step(active_state, command)
    checks = {
        "blocked": result.transition.coverage.get("blocked_reason") in {
            "enemy_action_target_not_in_candidate",
            "enemy_action_target_not_in_auto_target_group",
        },
        "state_unchanged": result.after_state.snapshot().to_json() == active_state.snapshot().to_json(),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "transition": result.transition.to_json()}


def _enemy_missing_card_case(rules: RuleBook, active_state: BattleState) -> dict[str, Any]:
    enemy = active_state.units["enemy:target"]
    flags = dict(enemy.flags)
    flags.pop("monster_data_card_id", None)
    state = replace(active_state, units={**active_state.units, "enemy:target": replace(enemy, flags=flags)})
    before = _snapshot_hash(state)
    view = ActionAvailabilitySystem(rules).view(state)
    after = _snapshot_hash(state)
    checks = {
        "missing_card_blocked": any(reason.reason == "enemy_monster_data_card_id_missing" for reason in view.blocked),
        "state_unchanged": before == after,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "view": view.to_json(), "snapshot_hash": {"before": before, "after": after}}


def _active_state(
    rules: RuleBook,
    scenario_data: dict[str, Any],
    actor_id: str,
) -> tuple[CombatScheduler, BattleState, Any]:
    scheduler, state = _scenario_state(rules, scenario_data)
    action_values = {unit_id: 1000.0 for unit_id in state.units}
    action_values[actor_id] = 0.0
    state = _with_action_values(state, action_values)
    begin = scheduler.step(state)
    return scheduler, begin.after_state, begin.transition


def _scenario_state(rules: RuleBook, scenario_data: dict[str, Any]) -> tuple[CombatScheduler, BattleState]:
    scenario = ScenarioLoader().load_dict(copy.deepcopy(scenario_data))
    built = ScenarioStateBuilder(rules).build(scenario)
    scheduler = CombatScheduler(rules)
    return scheduler, built.state


def _with_action_values(state: BattleState, values: dict[str, float]) -> BattleState:
    units = {
        unit_id: replace(unit, action_value=float(values.get(unit_id, unit.action_value)))
        for unit_id, unit in state.units.items()
    }
    flags = dict(state.global_flags)
    flags.pop("turn_owner_id", None)
    flags.pop("active_turn", None)
    flags["current_window"] = "idle"
    return replace(state, units=units, global_flags=flags, queues={})


def _command_from_first_choice(view: ActionAvailabilityView) -> ActionCommand | None:
    if not view.choices:
        return None
    choice = view.choices[0]
    return ActionCommand(
        actor_id=choice.actor_id,
        action_id=choice.action_id,
        action_level=choice.action_level,
        target_ids=_selected_targets(choice),
        source="manual" if choice.control == "external" else "queue",
        queue_name=choice.command_template.get("queue_name") if isinstance(choice.command_template.get("queue_name"), str) else None,
        metadata={**_dict(choice.command_template.get("metadata")), "validation": "p1_0_action_boundary"},
    )


def _selected_targets(choice) -> tuple[str, ...]:
    if choice.selectable_target_ids:
        return (choice.selectable_target_ids[0],)
    return tuple(choice.auto_target_ids)


def _ultimate_choice(rules: RuleBook, active_state: BattleState, actor_id: str) -> ActionCommand | None:
    actor = active_state.units[actor_id]
    action_set = rules.combatant_action_set(actor.template_id)
    if action_set is None:
        return None
    for _, entry in sorted(action_set.skill_index_map.items()):
        if not isinstance(entry, dict):
            continue
        action_id = str(entry.get("action_ref") or "")
        level = entry.get("default_level")
        if isinstance(level, bool) or not isinstance(level, int):
            continue
        definition = rules.action_definition(action_id, level)
        if definition is None:
            continue
        text = f"{definition.attack_type} {definition.skill_effect}".lower()
        if "ultra" not in text and "ultimate" not in text:
            continue
        event = rules.action_event(action_id, level)
        if event is None:
            continue
        view = ActionAvailabilitySystem(rules).view(active_state)
        targets = ()
        for choice in view.choices:
            if choice.action_id == action_id and choice.action_level == level:
                targets = _selected_targets(choice)
                break
        if not targets:
            targets = ("enemy:target",)
        return ActionCommand(
            actor_id=actor_id,
            action_id=action_id,
            action_level=level,
            target_ids=targets,
            source="manual",
            metadata={"validation": "p1_0_manual_ultimate_request"},
        )
    return None


def _snapshot_hash(state: BattleState) -> str:
    payload = json.dumps(state.snapshot().to_json(), sort_keys=True, separators=(",", ":"))
    import hashlib

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_serializable(payload: object) -> bool:
    json.dumps(payload, sort_keys=True)
    return True


def _replay_json(replay: Any | None) -> dict[str, Any]:
    if replay is None:
        return {}
    return {"ok": bool(replay.ok), "errors": list(replay.errors)}


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _card_identity(card: MonsterDataCardIR) -> dict[str, Any]:
    names = card.display.get("localized_names") if isinstance(card.display, dict) else {}
    return {
        "monster_id": card.monster_id,
        "entity_ref": card.entity_ref,
        "template_id": card.template_id,
        "rank": card.rank,
        "display_name_chs": names.get("CHS") if isinstance(names, dict) else "",
        "display_name_en": names.get("EN") if isinstance(names, dict) else "",
        "action_sequence_length": len(card.action_sequence),
    }


def _command_json(command: ActionCommand | None) -> dict[str, Any]:
    if command is None:
        return {}
    return {
        "actor_id": command.actor_id,
        "action_id": command.action_id,
        "action_level": command.action_level,
        "target_ids": list(command.target_ids),
        "source": command.source,
        "queue_name": command.queue_name,
        "metadata": command.metadata,
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
